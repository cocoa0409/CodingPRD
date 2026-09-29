"""Operator capabilities: the logical clock and the compliance-sweep checkpoint."""

from flask import Blueprint

import access
import calc
import domain
import envelope
import schema
import store
from access import Checks, Ctx

bp = Blueprint("ops", __name__)


@bp.post("/cosmetics/_clock/set_current_utc")
def set_clock():
    access.authorize("SystemOperator")
    body = schema.raw_body()
    ctx = Ctx()
    checks = Checks()

    def validate():
        payload = body if body is not None else {}
        ctx.instant = schema.instant_field(payload, "current_utc")

    checks.add(access.R_INVALID, validate)
    checks.run()

    previous = store.set_clock(ctx.instant)
    # PRD §2.5: setting the clock performs no state transitions of its own.
    return envelope.ok({
        "current_utc": store.iso(ctx.instant),
        "previous_utc": store.iso(previous),
    })


@bp.post("/cosmetics/_ops/compliance-sweep")
def compliance_sweep():
    access.authorize("SystemOperator")
    counts = {
        "renewal_due_facility_count": 0,
        "lapsed_facility_count": 0,
        "suspended_listing_count": 0,
        "overdue_event_count": 0,
        "closed_vai_count": 0,
        "escalated_oai_count": 0,
        "revalidation_required_count": 0,
    }
    today = store.today()
    now = store.now()

    # ---------------------------------------------------------------- step 1
    for facility in store.by_created(store.all_of("facilities")):
        status = facility["registration_status"]
        period_end = facility["current_period_end"]
        window_open = facility["renewal_window_open_date"]
        if (status == "REGISTERED" and window_open is not None and period_end is not None
                and today >= window_open and today <= period_end):
            facility["registration_status"] = "RENEWAL_DUE"
            store.touch(facility)
            domain.ledger_append(facility["id"], "STATE_TRANSITION", "Facility", facility["id"],
                                 "renewal window open")
            counts["renewal_due_facility_count"] += 1
        elif (status in ("REGISTERED", "RENEWAL_DUE") and period_end is not None
                and today > period_end):
            suspended, affected = domain.lapse_facility(facility)
            counts["lapsed_facility_count"] += 1
            counts["suspended_listing_count"] += len(suspended)
            counts["revalidation_required_count"] += domain.revalidated_dossier_count(affected)

    # ---------------------------------------------------------------- step 2
    for event in store.by_created(store.all_of("adverse_events")):
        if event["report_status"] != "REPORT_DUE":
            continue
        deadline_at = event["deadline_at"]
        if deadline_at is None or now <= deadline_at:
            continue
        event["report_status"] = "REPORT_OVERDUE"
        event["lateness_days"] = calc.lateness_days(now, deadline_at)
        store.touch(event)
        counts["overdue_event_count"] += 1
        listing = store.get("listings", event["listing_id"])
        facility = domain.facility_of_listing(listing)
        changed, before, after, affected = domain.posture_refresh(facility)
        domain.ledger_append(facility["id"], "DEADLINE_BREACH", "AdverseEvent", event["id"],
                             "serious-event report deadline breached")
        if changed:
            domain.ledger_append(
                facility["id"], "POSTURE_CHANGE", "Facility", facility["id"],
                "compliance posture recomputed after a missed report deadline",
                posture_before=before, posture_after=after)
        domain.ledger_revalidation(facility, affected)
        counts["revalidation_required_count"] += domain.revalidated_dossier_count(affected)

    # ---------------------------------------------------------------- step 3
    for engagement in store.by_created(store.all_of("inspections")):
        status = engagement["status"]
        facility = store.get("facilities", engagement["facility_id"])
        if status == "RESPONSE_SUBMITTED":
            score = engagement["readiness_score"]
            if score is not None and score >= domain.GMP_VAI_THRESHOLD:
                domain.close_inspection_vai(engagement, facility)
                counts["closed_vai_count"] += 1
            else:
                affected = domain.escalate_inspection_oai(engagement, facility)
                counts["escalated_oai_count"] += 1
                counts["revalidation_required_count"] += domain.revalidated_dossier_count(affected)
        elif status == "OBSERVATIONS_ISSUED":
            due_at = engagement["response_due_at"]
            if due_at is not None and now > due_at:
                affected = domain.escalate_inspection_oai(engagement, facility)
                counts["escalated_oai_count"] += 1
                counts["revalidation_required_count"] += domain.revalidated_dossier_count(affected)

    counts["swept_at"] = store.now_iso()
    return envelope.ok(counts)
