"""The aging epoch job and the logical-clock test-driving endpoint."""

from flask import Blueprint

import derive
import envelope
import lookup
import store
import validation as v
from auth import require

bp = Blueprint("ops", __name__, url_prefix="/research-billing")


@bp.post("/_ops/aging-run")
@require("ResearchBillingManager")
def aging_run():
    body = v.body()
    study_id = v.req_id(body, "study_id")
    study = lookup.study(study_id)

    # The run date is snapshotted once; every bucket is frozen against it.
    run_date = store.today()

    charges_aged_count = 0
    delinquent_charge_count = 0
    for charge in derive.charges_of(study["id"]):
        if charge["billing_state"] != "UNBILLED":
            continue
        baseline = store.iso(charge["unbilled_since"])[:10]
        days = v.days_between(baseline, run_date)
        if days < 0:
            days = 0
        charge["aging_days"] = days
        charge["aging_bucket"] = derive.aging_bucket_for(days)
        store.touch(charge)
        charges_aged_count += 1
        if charge["aging_bucket"] == "DELINQUENT_90_PLUS":
            delinquent_charge_count += 1

    visits_missed_count = 0
    for visit in derive.subject_visits_of_study(study["id"]):
        if visit["status"] != "SCHEDULED":
            continue
        subject = store.subjects.get(visit["study_subject_id"])
        calendar_visit = store.calendar_visits.get(visit["calendar_visit_id"])
        if subject is None or calendar_visit is None or subject["consent_date"] is None:
            continue
        window_close = v.shift_date(subject["consent_date"], calendar_visit["window_end_day"])
        if run_date > window_close:
            visit["status"] = "MISSED"
            store.touch(visit)
            visits_missed_count += 1

    return envelope.ok({
        "study_id": study["id"],
        "run_date": run_date,
        "charges_aged_count": charges_aged_count,
        "visits_missed_count": visits_missed_count,
        "delinquent_charge_count": delinquent_charge_count,
        "delinquent_sponsor_cents": derive.study_ledger(study)["delinquent_sponsor_cents"],
    })


@bp.post("/_clock/set_current_utc")
@require("ResearchBillingManager")
def set_clock():
    body = v.body()
    if "to_iso8601" not in body:
        raise v.bad("Missing required field: to_iso8601")
    instant = v.parse_iso8601(body["to_iso8601"], "to_iso8601")
    store.set_clock(instant)
    return envelope.ok({"current_utc": store.iso(store.now())})
