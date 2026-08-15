"""Insured tracking events and death claims (PRD §3.8)."""

from datetime import datetime, timedelta, timezone

from flask import Blueprint

import calc
from cascade import (
    CASE_TERMINAL,
    CLAIM_TERMINAL,
    maturity_cascade,
    recompute_reported_claim_sources,
    verified_death_source_count,
)
from db import stamp, store, touch
from errors import (
    ApiError,
    ERR_ALREADY_TERMINAL,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE_TRANSITION,
    ERR_POLICY_NOT_ACQUIRED,
    ERR_VERIFICATION_SOURCES_INSUFFICIENT,
)
from middleware import (
    READ_ALL,
    auth,
    get_body,
    lookup,
    opt,
    page_args,
    req,
    require_role,
    v_bool,
    v_date,
    v_enum,
    v_int,
)
from response import ok, ok_list
from serialize import ser_death_claim, ser_tracking_event

bp = Blueprint("tracking", __name__)

EVENT_TYPES = ["WELLNESS_CALL", "OBIT_SEARCH", "DMF_MATCH", "FAMILY_REPORT", "MEDICAL_RECORDS"]
OUTCOMES = ["ALIVE_CONFIRMED", "DEATH_INDICATED", "UNREACHABLE"]
CHANNELS = ["CALL", "OBIT", "DMF", "MEDICAL", "FAMILY"]


def _sorted(items):
    return sorted(items, key=lambda e: (e["created_at"], e["_seq"]))


def _list(items, serializer):
    limit, offset = page_args()
    items = _sorted(items)
    page = items[offset : offset + limit]
    return ok_list([serializer(e) for e in page], len(items), limit, offset)


def _case_acquired(case):
    if case["status"] in CASE_TERMINAL:
        raise ApiError(ERR_ALREADY_TERMINAL, 409, "Case is in terminal state %s" % case["status"])
    if case["status"] != "ACQUIRED":
        raise ApiError(ERR_POLICY_NOT_ACQUIRED, 409, "Case is not ACQUIRED")


# ---------------------------------------------------------------------------
# Tracking events
# ---------------------------------------------------------------------------


@bp.post("/api/cases/<cid>/tracking-events")
def create_tracking_event(cid):
    uid, role = auth()
    require_role(role, ["CaseManager"])
    body = get_body()
    event_type = v_enum(req(body, "event_type"), "event_type", EVENT_TYPES)
    outcome = v_enum(req(body, "outcome"), "outcome", OUTCOMES)
    channel = v_enum(req(body, "source_channel"), "source_channel", CHANNELS)
    event_date = v_date(req(body, "event_date"), "event_date")
    case = lookup(store.cases, cid, "PolicyCase")
    _case_acquired(case)
    coverage = datetime(
        event_date.year, event_date.month, event_date.day, tzinfo=timezone.utc
    ) + timedelta(days=calc.TRACKING_COVERAGE_DAYS)
    event = {
        "case_id": cid,
        "event_type": event_type,
        "outcome": outcome,
        "source_channel": channel,
        "event_date": event_date,
        "coverage_through": coverage,
        "status": "RECORDED",
    }
    stamp(event)
    store.tracking_events[event["id"]] = event
    return ok(ser_tracking_event(event), 201)


@bp.get("/api/cases/<cid>/tracking-events")
def list_tracking_events(cid):
    uid, role = auth()
    require_role(role, READ_ALL)
    lookup(store.cases, cid, "PolicyCase")
    return _list(
        [e for e in store.tracking_events.values() if e["case_id"] == cid],
        ser_tracking_event,
    )


@bp.post("/api/tracking-events/<eid>/verify")
def verify_tracking_event(eid):
    uid, role = auth()
    require_role(role, ["ComplianceOfficer"])
    event = lookup(store.tracking_events, eid, "TrackingEvent")
    if event["status"] in ("VERIFIED", "REJECTED"):
        raise ApiError(ERR_ALREADY_TERMINAL, 409, "Tracking event is %s" % event["status"])
    event["status"] = "VERIFIED"
    touch(event)
    recompute_reported_claim_sources(event["case_id"])
    return ok(ser_tracking_event(event))


@bp.post("/api/tracking-events/<eid>/reject")
def reject_tracking_event(eid):
    uid, role = auth()
    require_role(role, ["ComplianceOfficer"])
    event = lookup(store.tracking_events, eid, "TrackingEvent")
    if event["status"] in ("VERIFIED", "REJECTED"):
        raise ApiError(ERR_ALREADY_TERMINAL, 409, "Tracking event is %s" % event["status"])
    event["status"] = "REJECTED"
    touch(event)
    return ok(ser_tracking_event(event))


# ---------------------------------------------------------------------------
# Death claims
# ---------------------------------------------------------------------------


@bp.post("/api/cases/<cid>/death-claims")
def create_death_claim(cid):
    uid, role = auth()
    require_role(role, ["ComplianceOfficer"])
    body = get_body()
    date_of_death = v_date(req(body, "date_of_death"), "date_of_death")
    case = lookup(store.cases, cid, "PolicyCase")
    _case_acquired(case)
    if verified_death_source_count(cid) < 1:
        raise ApiError(
            ERR_VERIFICATION_SOURCES_INSUFFICIENT,
            422,
            "At least one VERIFIED DEATH_INDICATED event is required",
        )
    claim = {
        "case_id": cid,
        "date_of_death": date_of_death,
        "status": "REPORTED",
        "verification_source_count": 0,
        "certificate_received": False,
        "in_contestability": calc.claim_in_contestability(case["acquired_at"], date_of_death),
        "gross_proceeds_cents": None,
        "net_proceeds_cents": None,
    }
    stamp(claim)
    store.death_claims[claim["id"]] = claim
    return ok(ser_death_claim(claim), 201)


@bp.get("/api/death-claims/<cid>")
def get_death_claim(cid):
    uid, role = auth()
    require_role(role, READ_ALL)
    return ok(ser_death_claim(lookup(store.death_claims, cid, "DeathClaim")))


@bp.get("/api/cases/<cid>/death-claims")
def list_death_claims(cid):
    uid, role = auth()
    require_role(role, READ_ALL)
    lookup(store.cases, cid, "PolicyCase")
    return _list([c for c in store.death_claims.values() if c["case_id"] == cid], ser_death_claim)


@bp.post("/api/death-claims/<cid>/verify")
def verify_death_claim(cid):
    uid, role = auth()
    require_role(role, ["ComplianceOfficer"])
    body = get_body()
    certificate = v_bool(req(body, "certificate_received"), "certificate_received")
    if certificate is not True:
        raise ApiError(ERR_INVALID_REQUEST, 400, "certificate_received must be true")
    claim = lookup(store.death_claims, cid, "DeathClaim")
    if claim["status"] in CLAIM_TERMINAL:
        raise ApiError(ERR_ALREADY_TERMINAL, 409, "Claim is %s" % claim["status"])
    if claim["status"] != "REPORTED":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409, "Claim is not REPORTED")
    count = verified_death_source_count(claim["case_id"])
    if count < 2:
        raise ApiError(
            ERR_VERIFICATION_SOURCES_INSUFFICIENT,
            422,
            "Two distinct-source VERIFIED DEATH_INDICATED events are required",
        )
    claim["certificate_received"] = True
    claim["verification_source_count"] = count
    claim["status"] = "VERIFIED"
    touch(claim)
    return ok(ser_death_claim(claim))


@bp.post("/api/death-claims/<cid>/file")
def file_death_claim(cid):
    uid, role = auth()
    require_role(role, ["CaseManager"])
    claim = lookup(store.death_claims, cid, "DeathClaim")
    if claim["status"] in CLAIM_TERMINAL:
        raise ApiError(ERR_ALREADY_TERMINAL, 409, "Claim is %s" % claim["status"])
    if claim["status"] != "VERIFIED":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409, "Claim is not VERIFIED")
    claim["status"] = "FILED"
    touch(claim)
    return ok(ser_death_claim(claim))


@bp.post("/api/death-claims/<cid>/settle")
def settle_death_claim(cid):
    uid, role = auth()
    require_role(role, ["ComplianceOfficer"])
    body = get_body()
    outcome = v_enum(req(body, "outcome"), "outcome", ["PAID", "DENIED"])
    gross = None
    if outcome == "PAID":
        gross = v_int(req(body, "gross_proceeds_cents"), "gross_proceeds_cents", min_v=1)
    ack = opt(body, "contest_review_acknowledged", False)
    if ack is not None and not isinstance(ack, bool):
        raise ApiError(ERR_INVALID_REQUEST, 400, "contest_review_acknowledged must be boolean")
    claim = lookup(store.death_claims, cid, "DeathClaim")
    if claim["status"] in CLAIM_TERMINAL:
        raise ApiError(ERR_ALREADY_TERMINAL, 409, "Claim is %s" % claim["status"])
    if claim["status"] not in ("FILED", "CONTESTED"):
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409, "Claim is not FILED or CONTESTED")
    if outcome == "DENIED":
        claim["status"] = "DENIED"
        touch(claim)
        return ok(ser_death_claim(claim))
    # PAID path
    if claim["in_contestability"] and ack is not True:
        if claim["status"] == "FILED":
            claim["status"] = "CONTESTED"
            touch(claim)
        return ok(ser_death_claim(claim))
    case = store.cases[claim["case_id"]]
    policy = store.policies[case["policy_id"]]
    claim["gross_proceeds_cents"] = gross
    claim["net_proceeds_cents"] = calc.claim_net_proceeds(case, policy, gross, claim["date_of_death"])
    claim["status"] = "PAID"
    touch(claim)
    if case["status"] == "ACQUIRED":
        maturity_cascade(claim, case)
    return ok(ser_death_claim(claim))
