"""The nightly batch and the logical-clock test-driving endpoint."""
from datetime import timedelta

from flask import Blueprint

import calc
import services as svc
from errors import fail
from middleware import endpoint, get_body
from response import object_response
from store import by_created, db, iso, now, parse_ts, pdt, set_clock, touch

bp = Blueprint("ops", __name__)


def _by_due_date(rows):
    return sorted(rows, key=lambda r: (r["due_date"], r["created_at"], r["_seq"]))


@bp.route("/cbb/ops/nightly-run", methods=["POST"])
@endpoint("PlatformAdmin")
def nightly_run(user_id, role):
    get_body()
    clock = now()
    counters = {
        "kits_expired": 0,
        "screenings_expired": 0,
        "reservations_expired": 0,
        "excursions_escalated": 0,
        "tanks_entered_maintenance": 0,
        "tanks_exited_maintenance": 0,
        "invoices_advanced_past_due": 0,
        "invoices_advanced_delinquent": 0,
        "accounts_advanced": 0,
        "units_flagged_pending_abandonment": 0,
    }

    # ---------------------------------------------------------- 1. kit expiry
    for kit in by_created(list(db.kits.values())):
        if kit["status"] not in ("DISPATCHED", "HELD"):
            continue
        expires = pdt(kit["expires_at"])
        if expires is not None and clock > expires:
            kit["status"] = "EXPIRED"
            touch(kit)
            counters["kits_expired"] += 1

    # ------------------------------------------------------ 2. panel expiry
    for screening in by_created(list(db.screenings.values())):
        if screening["status"] != "COMPLETED":
            continue
        valid_until = pdt(screening["valid_until"])
        if valid_until is None or clock <= valid_until:
            continue
        enrollment = db.enrollments.get(screening["enrollment_id"])
        governing = (svc.governing_panel(enrollment["id"])
                     if enrollment is not None else None)
        was_governing = governing is not None and governing["id"] == screening["id"]
        screening["status"] = "EXPIRED"
        touch(screening)
        counters["screenings_expired"] += 1
        if enrollment is None or not was_governing:
            continue
        for unit in svc.enrollment_units(enrollment["id"]):
            if unit["eligibility_status"] != "ELIGIBLE":
                continue
            unit["eligibility_status"] = "INDETERMINATE"
            unit["eligibility_reason_code"] = "SCREENING_EXPIRED"
            touch(unit)
            for listing in svc.unit_listings(unit["id"]):
                if listing["listing_status"] == "ACTIVE":
                    listing["listing_status"] = "SUSPENDED"
                    listing["suspension_reason_code"] = "SCREENING_EXPIRED"
                    touch(listing)

    # -------------------------------------------------- 3. hold window lapse
    for reservation in by_created(list(db.reservations.values())):
        if reservation["status"] != "PENDING_CONFIRMATORY":
            continue
        deadline = pdt(reservation["created_at"]) + timedelta(
            hours=calc.CONFIRM_WINDOW_HOURS)
        if clock > deadline:
            reservation["status"] = "EXPIRED"
            reservation["cancellation_reason_code"] = "CONFIRM_WINDOW_LAPSED"
            touch(reservation)
            counters["reservations_expired"] += 1

    # ------------------------------------------------ 4. excursion escalation
    for excursion in by_created(list(db.excursions.values())):
        if excursion["status"] != "OPEN":
            continue
        detected = pdt(excursion["detected_at"])
        if detected is not None and clock > detected + timedelta(
                minutes=calc.MAX_ACK_MINUTES):
            excursion["status"] = "ESCALATED"
            touch(excursion)
            counters["excursions_escalated"] += 1

    # ------------------------------------------------- 5. maintenance windows
    for tank in by_created(list(db.tanks.values())):
        start = pdt(tank["maintenance_window_start"])
        end = pdt(tank["maintenance_window_end"])
        inside = (start is not None and end is not None
                  and start <= clock < end)
        if tank["status"] == "ONLINE" and inside:
            tank["status"] = "MAINTENANCE"
            touch(tank)
            counters["tanks_entered_maintenance"] += 1
        elif tank["status"] == "MAINTENANCE" and not inside:
            tank["status"] = "ONLINE"
            touch(tank)
            counters["tanks_exited_maintenance"] += 1

    # --------------------------------------------- 6. the invoice ladder
    advanced_past_due = set()
    advanced_delinquent = set()
    for invoice in _by_due_date(list(db.invoices.values())):
        if invoice["status"] not in ("ISSUED", "PAST_DUE"):
            continue
        residual = invoice["amount_due_cents"] - invoice["amount_paid_cents"]
        if residual <= 0:
            continue
        dpd = calc.days_past_due(pdt(invoice["due_date"]), clock)
        target = None
        if invoice["status"] == "ISSUED" and dpd >= calc.PAST_DUE_DAYS:
            target = "PAST_DUE"
        elif invoice["status"] == "PAST_DUE" and dpd >= calc.DELINQUENT_DAYS:
            target = "DELINQUENT"
        if target is None:
            continue
        invoice["status"] = target
        invoice["late_fee_line_cents"] = (invoice["late_fee_line_cents"]
                                          + calc.late_fee_increment(residual))
        svc.refresh_invoice_total(invoice)
        invoice["stage_advanced_at"] = iso(clock)
        touch(invoice)
        if target == "PAST_DUE":
            counters["invoices_advanced_past_due"] += 1
            advanced_past_due.add(invoice["account_id"])
        else:
            counters["invoices_advanced_delinquent"] += 1
            advanced_delinquent.add(invoice["account_id"])

    # --------------------------------------------- 7. the account ladder
    for account in by_created(list(db.accounts.values())):
        status = account["status"]
        advanced = False
        if status == "ACTIVE" and account["id"] in advanced_past_due:
            account["status"] = "PAST_DUE"
            advanced = True
        elif status == "PAST_DUE" and account["id"] in advanced_delinquent:
            account["status"] = "DELINQUENT"
            advanced = True
            for unit in svc.account_units(account["id"]):
                if unit["availability_status"] != "PRIVATE_STORED":
                    continue
                unit["availability_status"] = "PENDING_ABANDONMENT"
                touch(unit)
                counters["units_flagged_pending_abandonment"] += 1
                for res in svc.unit_reservations(unit["id"]):
                    if res["status"] == "PENDING_CONFIRMATORY":
                        res["status"] = "DECLINED"
                        res["cancellation_reason_code"] = "ACCOUNT_DELINQUENT"
                        touch(res)
        elif status in ("DELINQUENT", "ABANDONMENT_NOTICE"):
            oldest = None
            for invoice in _by_due_date(svc.account_invoices(account["id"])):
                if invoice["status"] == "DELINQUENT":
                    oldest = invoice
                    break
            if oldest is not None:
                dpd = calc.days_past_due(pdt(oldest["due_date"]), clock)
                if status == "DELINQUENT" and dpd >= calc.ABANDONMENT_NOTICE_DAYS:
                    account["status"] = "ABANDONMENT_NOTICE"
                    advanced = True
                elif status == "ABANDONMENT_NOTICE" and dpd >= calc.ABANDONMENT_DAYS:
                    account["status"] = "ABANDONED"
                    advanced = True
        if advanced:
            account["delinquency_stage_entered_at"] = iso(clock)
            touch(account)
            svc.reconcile_balance(account)
            counters["accounts_advanced"] += 1

    return object_response(counters)


@bp.route("/_clock/set_current_utc", methods=["POST"])
@endpoint("PlatformAdmin")
def set_current_utc(user_id, role):
    body = get_body()
    raw = body.get("current_utc")
    if not isinstance(raw, str) or parse_ts(raw) is None:
        fail("ERR_VALIDATION_FAILED",
             "Field 'current_utc' must be an RFC3339 UTC timestamp.")
    set_clock(parse_ts(raw))
    return object_response({"current_utc": raw})
