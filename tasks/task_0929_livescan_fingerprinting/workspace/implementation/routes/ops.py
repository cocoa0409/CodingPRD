from flask import Blueprint

import billing
import constants as C
import derive
import validation as V
from envelope import object_response
from money import pct_of
from store import db
from timeutil import add_days, render_instant

bp = Blueprint("ops", __name__)


@bp.post("/livescan/_ops/aging-run")
def aging_run():
    data = V.body()
    write_off_over_days = V.opt_int(data, "write_off_over_days", default=None, minimum=0)

    invoices_aged = 0
    for invoice in list(db.invoices.values()):
        if invoice["status"] not in ("ISSUED", "PAST_DUE"):
            continue
        changed = False
        aging = derive.invoice_aging_days(invoice)
        if invoice["aging_days"] != aging:
            invoice["aging_days"] = aging
            changed = True
        if aging >= 1 and invoice["paid_cents"] < invoice["total_cents"]:
            if invoice["status"] == "ISSUED":
                invoice["status"] = "PAST_DUE"
                changed = True
            late = pct_of(C.INVOICE_LATE_FEE_PCT, invoice["total_cents"] - invoice["paid_cents"])
            if late:
                invoice["late_fee_cents"] += late
                invoice["total_cents"] = invoice["subtotal_cents"] + invoice["late_fee_cents"]
                changed = True
        if changed:
            db.touch(invoice)
            invoices_aged += 1

    if write_off_over_days is not None:
        for invoice in list(db.invoices.values()):
            if invoice["status"] != "PAST_DUE":
                continue
            if invoice["aging_days"] < write_off_over_days:
                continue
            invoice["status"] = "WRITTEN_OFF"
            db.touch(invoice)
            for assessment in db.assessments.values():
                if assessment["invoice_id"] != invoice["id"]:
                    continue
                if assessment["status"] != "INVOICED":
                    continue
                assessment["status"] = "CREDITED"
                assessment["credited_cents"] = assessment["total_cents"]
                db.touch(assessment)

    agencies_suspended = 0
    for agency in list(db.agencies.values()):
        if billing.recompute_agency_posture(agency):
            agencies_suspended += 1

    subscriptions_lapsed = 0
    for subscription in list(db.subscriptions.values()):
        if subscription["status"] not in ("ACTIVE", "RENEWAL_DUE"):
            continue
        if db.now() > subscription["term_end"]:
            subscription["status"] = "LAPSED"
            db.touch(subscription)
            subscriptions_lapsed += 1

    purges_auto_denied = 0
    for submission in list(db.submissions.values()):
        if submission["retention_status"] != "PURGE_REQUESTED":
            continue
        requested_at = submission["purge_requested_at"]
        if requested_at is None:
            continue
        if db.now() > add_days(requested_at, C.PURGE_DECISION_WINDOW_DAYS):
            submission["retention_status"] = "PURGE_DENIED"
            submission["purge_decided_by_user_id"] = None
            db.touch(submission)
            purges_auto_denied += 1

    return object_response(
        {
            "invoices_aged": invoices_aged,
            "agencies_suspended": agencies_suspended,
            "subscriptions_lapsed": subscriptions_lapsed,
            "purges_auto_denied": purges_auto_denied,
        }
    )


@bp.post("/livescan/_clock/set_current_utc")
def set_clock():
    data = V.body()
    instant = V.req_instant(data, "to_iso8601")
    db.set_clock(instant)
    return object_response({"current_utc": render_instant(instant)})
