"""The logical clock and the daily time sweep (PRD 2.4)."""

from datetime import date, timedelta

from db import CLOCK, STORE
from errors import bad_request
from services.cascade import adverse_notice_if_drop
from services.rates import create_notice, recompute_account_rates
from utils import bump, parse_datetime_val


def set_clock(to_iso8601):
    new_dt = parse_datetime_val(to_iso8601)
    if new_dt is None:
        raise bad_request("to_iso8601 must be an ISO 8601 datetime")
    old_dt = CLOCK["now"]
    if new_dt < old_dt:
        raise bad_request("The logical clock cannot move backwards")
    old_date = old_dt.date()
    new_date = new_dt.date()
    elapsed = (new_date - old_date).days
    # The clock reads the new instant while the sweep replays each elapsed day.
    CLOCK["now"] = new_dt
    for i in range(1, elapsed + 1):
        sweep_day(old_date + timedelta(days=i))
    return new_dt


def sweep_day(d):
    """One elapsed day of the sweep; the six steps in PRD 2.4 order."""
    # 1. Daily interest accrual (floor to integer milli-cents) for non-CLOSED.
    for a in STORE["accounts"].values():
        if a["lifecycle"] == "CLOSED":
            continue
        daily_milli = (a["balance_cents"] * a["current_rate_bp"]) // 3650
        if daily_milli:
            a["unposted_accrual_milli"] += daily_milli
            bump(a)

    # 2. Promotional-offer activation and expiry.
    for o in STORE["promos"].values():
        if o["status"] == "SCHEDULED" and date.fromisoformat(o["enrollment_start"]) <= d:
            o["status"] = "ACTIVE"
            bump(o)
    for o in STORE["promos"].values():
        if o["status"] in ("SCHEDULED", "ACTIVE") and date.fromisoformat(o["enrollment_end"]) < d:
            o["status"] = "EXPIRED"
            bump(o)

    # 3. Per-account promo rollover once promo_end_date has passed.
    for a in STORE["accounts"].values():
        if a["rate_source"] != "PROMO" or not a["promo_end_date"]:
            continue
        if date.fromisoformat(a["promo_end_date"]) >= d:
            continue
        offer = STORE["promos"].get(a["promo_offer_id"])
        if (
            offer is not None
            and offer["rollover_treatment"] == "RENEW_THEN_SHEET"
            and offer["status"] == "ACTIVE"
        ):
            new_end = date.fromisoformat(a["promo_end_date"]) + timedelta(
                days=offer["promo_term_days"]
            )
            a["promo_end_date"] = new_end.isoformat()
            bump(a)  # stays PROMO; no transition
        else:
            old_rate = a["current_rate_bp"]
            a["rate_source"] = "SHEET"
            a["promo_offer_id"] = None
            a["promo_end_date"] = None
            recompute_account_rates(a)
            bump(a)
            adverse_notice_if_drop(a, old_rate, a["sheet_id"], d.isoformat())

    # 4. Applied exceptions whose exception_end_date has passed expire.
    for e in STORE["exceptions"].values():
        if e["status"] != "APPLIED":
            continue
        a = STORE["accounts"].get(e["account_id"])
        end = a["exception_end_date"] if a is not None else None
        if end is None or date.fromisoformat(end) >= d:
            continue
        e["status"] = "EXPIRED"
        bump(e)
        if a is not None and a["exception_request_id"] == e["id"]:
            old_rate = a["current_rate_bp"]
            a["rate_source"] = "SHEET"
            a["exception_request_id"] = None
            a["exception_end_date"] = None
            a["exception_rate_bp"] = None
            recompute_account_rates(a)
            bump(a)
            adverse_notice_if_drop(a, old_rate, a["sheet_id"], d.isoformat())

    # 5. PROMO_EXPIRY notices exactly thirty days before promo_end_date.
    for a in STORE["accounts"].values():
        if a["rate_source"] != "PROMO" or not a["promo_end_date"]:
            continue
        if date.fromisoformat(a["promo_end_date"]) - timedelta(days=30) == d:
            create_notice(
                a["sheet_id"], a["id"], a["channel"], "PROMO_EXPIRY", d.isoformat()
            )

    # 6. APPROVED-but-unapplied exceptions expire 30 days past the decision date.
    for e in STORE["exceptions"].values():
        if e["status"] != "APPROVED":
            continue
        decided = e.get("_decided_date")
        if decided and date.fromisoformat(decided) + timedelta(days=30) < d:
            e["status"] = "EXPIRED"
            bump(e)
