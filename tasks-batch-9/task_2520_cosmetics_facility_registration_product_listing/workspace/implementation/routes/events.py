"""Adverse-event recordkeeping, the fifteen-day report clock and its cascades."""

from flask import Blueprint, request

import access
import calc
import domain
import envelope
import schema
import store
from access import Checks, Ctx

bp = Blueprint("events", __name__)


def _listing_of(event):
    return store.get("listings", event["listing_id"])


def _owner_of_event(auth, event):
    listing = _listing_of(event)
    if listing is not None:
        access.owner_of_listing(auth, listing)


def _deadline_from(basis):
    """PRD §3.6: end of the fifteenth day after the day of the basis instant."""
    return store.end_of_day(store.add_days(basis.date(), domain.SERIOUS_REPORT_DEADLINE_DAYS))


@bp.post("/cosmetics/listings/<lid>/adverse-events")
def record_event(lid):
    auth = access.authorize("ResponsiblePersonAgent")
    body = schema.raw_body()
    ctx = Ctx()
    checks = Checks()
    checks.add(access.R_LISTING, lambda: ctx.set("listing", access.need_listing(lid)))
    checks.add(access.R_OWNER, lambda: access.owner_of_listing(auth, ctx.listing))

    def validate():
        payload = body if body is not None else {}
        ctx.description = schema.string_field(payload, "event_description", max_len=1000)
        ctx.received_at = schema.instant_field(payload, "received_at")
        ctx.seriousness = schema.enum_field(payload, "seriousness", domain.SERIOUSNESS_VALUES)
        ctx.outcome = schema.enum_field(payload, "outcome_code", domain.OUTCOME_CODES,
                                        required=False, default=None)

    checks.add(access.R_INVALID, validate)
    checks.add(access.R_RECEIVED_FUTURE, lambda: access.state_error(
        ctx.received_at <= store.now(), "ERR_RECEIVED_AT_IN_FUTURE"))
    checks.run()

    serious = ctx.seriousness == "SERIOUS"
    basis = ctx.received_at if serious else None
    event = store.insert("adverse_events", {
        "listing_id": lid,
        "event_description": ctx.description,
        "received_at": ctx.received_at,
        "seriousness": ctx.seriousness,
        "outcome_code": ctx.outcome,
        # RECORDED is never observable: the intake applies the automatic transition.
        "report_status": "REPORT_DUE" if serious else "RETAINED",
        "deadline_basis_at": basis,
        "deadline_at": _deadline_from(basis) if serious else None,
        "reclassified_at": None,
        "submitted_at": None,
        "lateness_days": 0,
    })
    return envelope.created(domain.adverse_event_json(event))


@bp.get("/cosmetics/listings/<lid>/adverse-events")
def list_events(lid):
    auth = access.authorize(domain.ROLES)
    ctx = Ctx()
    checks = Checks()
    checks.add(access.R_LISTING, lambda: ctx.set("listing", access.need_listing(lid)))
    checks.add(access.R_OWNER, lambda: access.owner_of_listing(auth, ctx.listing))
    checks.run()
    records = domain.events_of_listing(lid)
    for name in ("seriousness", "report_status"):
        value = request.args.get(name)
        if value:
            records = [r for r in records if r[name] == value]
    # PRD §3.6: a listing's events are listed newest first.
    return envelope.paginate(store.by_created_desc(records), domain.adverse_event_json)


@bp.post("/cosmetics/adverse-events/<eid>/report")
def report_event(eid):
    auth = access.authorize("ResponsiblePersonAgent")
    body = schema.raw_body()
    ctx = Ctx()
    checks = Checks()
    checks.add(access.R_EVENT, lambda: ctx.set("event", access.need_event(eid)))
    checks.add(access.R_OWNER, lambda: _owner_of_event(auth, ctx.event))

    def validate():
        payload = body if body is not None else {}
        schema.string_field(payload, "report_narrative", required=False, max_len=2000, default=None)

    checks.add(access.R_INVALID, validate)
    checks.add(access.R_STATE_EVENT, lambda: access.state_error(
        ctx.event["report_status"] in ("REPORT_DUE", "REPORT_OVERDUE"),
        "ERR_INVALID_ADVERSE_EVENT_STATE"))
    checks.run()

    event = ctx.event
    listing = _listing_of(event)
    facility = domain.facility_of_listing(listing)
    submitted_at = store.now()
    deadline_at = event["deadline_at"]
    event["submitted_at"] = submitted_at
    if deadline_at is not None and submitted_at > deadline_at:
        event["report_status"] = "REPORTED_LATE"
        event["lateness_days"] = calc.lateness_days(submitted_at, deadline_at)
    else:
        # The deadline is inclusive to the millisecond.
        event["report_status"] = "REPORTED_TIMELY"
        event["lateness_days"] = 0
    store.touch(event)

    changed, before, after, affected = domain.posture_refresh(facility)
    domain.ledger_append(facility["id"], "ADVERSE_EVENT_REPORT", "AdverseEvent", event["id"],
                         "adverse event report filed")
    if changed:
        domain.ledger_append(facility["id"], "POSTURE_CHANGE", "Facility", facility["id"],
                             "compliance posture recomputed after adverse-event report",
                             posture_before=before, posture_after=after)
    domain.ledger_revalidation(facility, affected)
    return envelope.ok(domain.adverse_event_json(event))


@bp.post("/cosmetics/adverse-events/<eid>/reclassify")
def reclassify_event(eid):
    auth = access.authorize("RegulatoryReviewer", "ResponsiblePersonAgent")
    body = schema.raw_body()
    ctx = Ctx()
    checks = Checks()
    checks.add(access.R_EVENT, lambda: ctx.set("event", access.need_event(eid)))
    checks.add(access.R_OWNER, lambda: _owner_of_event(auth, ctx.event))

    def validate():
        payload = body if body is not None else {}
        ctx.seriousness = schema.enum_field(payload, "seriousness", domain.SERIOUSNESS_VALUES)
        ctx.outcome = schema.enum_field(payload, "outcome_code", domain.OUTCOME_CODES,
                                        required=False, default=None)

    checks.add(access.R_INVALID, validate)
    checks.add(access.R_STATE_EVENT, lambda: access.state_error(
        ctx.event["report_status"] == "RETAINED"
        and ctx.event["seriousness"] == "NON_SERIOUS",
        "ERR_INVALID_ADVERSE_EVENT_STATE"))
    checks.run()

    event = ctx.event
    reclassified_at = store.now()
    event["seriousness"] = "SERIOUS"
    if ctx.outcome is not None:
        event["outcome_code"] = ctx.outcome
    event["reclassified_at"] = reclassified_at
    # PRD §3.6: the clock is rebased on the reclassification instant.
    event["deadline_basis_at"] = reclassified_at
    event["deadline_at"] = _deadline_from(reclassified_at)
    event["report_status"] = "REPORT_DUE"
    store.touch(event)
    return envelope.ok(domain.adverse_event_json(event))
