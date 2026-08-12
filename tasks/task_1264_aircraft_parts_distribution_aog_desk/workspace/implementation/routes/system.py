"""Platform endpoints: the logical clock and the operations sweep."""

from datetime import timedelta
from decimal import Decimal

from flask import Blueprint

from auth import require_roles
from db import store, clock
from errors import ApiError, ERR_CLOCK_REGRESSION, ERR_INVALID_REQUEST
from helpers import touch, post_ledger
from util import success, get_body, req_present, as_dt, bad

bp = Blueprint("system", __name__)


@bp.post("/_clock/set_current_utc")
def set_clock():
    require_roles("PlatformOps")
    body = get_body()
    raw = req_present(body, "to_iso8601")
    try:
        dt = as_dt(raw, "to_iso8601")
    except ApiError:
        raise
    except Exception:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "to_iso8601 must be a valid ISO 8601 timestamp")
    if dt < clock.current:
        raise ApiError(ERR_CLOCK_REGRESSION, 400,
                       "Cannot move the clock backwards")
    clock.current = dt
    clock.raw = raw if isinstance(raw, str) else dt.isoformat()
    return success({"current_utc": clock.raw})


@bp.post("/_system/run-sweeps")
def run_sweeps():
    require_roles("PlatformOps")
    now = clock.current
    counts = {
        "expired_quotes": 0,
        "overdue_core_returns": 0,
        "overdue_loans": 0,
        "lease_debits_posted": 0,
        "customers_suspended": 0,
        "tiers_updated": 0,
        "units_scrapped": 0,
    }

    # (1) expire ISSUED quotes past expires_at; release pinned units
    for q in list(store["quotes"].values()):
        if q["status"] == "ISSUED" and q.get("_expires_dt") is not None \
                and now > q["_expires_dt"]:
            q["status"] = "EXPIRED"
            touch(q)
            counts["expired_quotes"] += 1
            req = store["requests"].get(q["aog_request_id"])
            if req is not None and req.get("reserved_unit_id"):
                unit = store["units"].get(req["reserved_unit_id"])
                if unit is not None and unit["status"] == "RESERVED":
                    unit["status"] = "AVAILABLE"
                    unit["reserved_by_request_id"] = None
                    touch(unit)
                req["reserved_unit_id"] = None
                touch(req)

    # (2) OPEN core returns past due_at -> OVERDUE
    for cr in store["core_returns"].values():
        if cr["status"] == "OPEN" and now > cr["_due_dt"]:
            cr["status"] = "OVERDUE"
            touch(cr)
            counts["overdue_core_returns"] += 1

    # (3) ACTIVE loans past due_at -> OVERDUE
    for loan in store["loans"].values():
        if loan["status"] == "ACTIVE" and now > loan["_due_dt"]:
            loan["status"] = "OVERDUE"
            touch(loan)
            counts["overdue_loans"] += 1

    # (4) LEASE forward billing for crossed 30-day boundaries
    for loan in store["loans"].values():
        if loan["loan_type"] != "LEASE" or \
                loan["status"] not in ("ACTIVE", "OVERDUE"):
            continue
        elapsed = (now - loan["_start_dt"]).total_seconds()
        periods_due = int(elapsed // (30 * 86400)) + 1
        while loan["_periods_billed"] < periods_due:
            post_ledger(loan["customer_id"], "LEASE_DEBIT",
                        30 * loan["daily_rate_cents"], "LOAN_AGREEMENT",
                        loan["id"])
            loan["_periods_billed"] += 1
            counts["lease_debits_posted"] += 1

    # (5) tier recompute from trailing 180-day window + auto-suspension
    window_start = now - timedelta(days=180)
    for cust in store["customers"].values():
        settled = [c for c in store["core_returns"].values()
                   if c["customer_id"] == cust["id"]
                   and c["status"] == "SETTLED"
                   and c.get("_received_dt") is not None
                   and window_start < c["_received_dt"] <= now]
        count = len(settled)
        on_time = sum(1 for c in settled if c["_received_dt"] <= c["_due_dt"])
        rate = (Decimal(on_time) / Decimal(count)) if count else Decimal(0)
        fraud = cust["warranty_fraud_flags"]
        if count >= 2 and rate >= Decimal("0.95") and fraud == 0:
            tier = "PLATINUM"
        elif count >= 1 and rate >= Decimal("0.90") and fraud == 0:
            tier = "PRIORITY"
        else:
            tier = "STANDARD"
        changed = (cust["core_returns_settled_180d"] != count
                   or cust["core_returns_on_time_180d"] != on_time)
        cust["core_returns_settled_180d"] = count
        cust["core_returns_on_time_180d"] = on_time
        if cust["priority_tier"] != tier:
            cust["priority_tier"] = tier
            counts["tiers_updated"] += 1
            changed = True
        if cust["status"] == "ACTIVE" and \
                cust["outstanding_balance_cents"] > cust["credit_limit_cents"]:
            cust["status"] = "SUSPENDED"
            counts["customers_suspended"] += 1
            changed = True
        if changed:
            touch(cust)

    # (6) scrap QUARANTINED units
    for unit in store["units"].values():
        if unit["status"] == "QUARANTINED":
            unit["status"] = "SCRAPPED"
            touch(unit)
            counts["units_scrapped"] += 1

    return success(counts)
