"""Negotiation rounds, offers, good faith, impasse and blackout notices
(PRD 3.5, 3.6, 3.7 acceptance)."""
from flask import Blueprint

import calc
import derive
from common import (
    authenticate,
    body_json,
    pagination,
    paginate,
    query_enum,
    query_str,
    take_bool,
    take_dt,
    take_enum,
    take_int,
    take_str,
)
from envelope import array_response, object_response
from errors import ApiError
from routes_setup import TIERS
from store import (
    ALL_ROLES,
    MAX_RATE_PER_SUB_CENTS,
    MIN_GOOD_FAITH_MEETINGS,
    RIGHTS_TERM_ORDER,
    base_row,
    clock,
    db,
    fmt_dt,
    now_iso,
    parse_iso,
    sort_rows,
    touch,
)

bp = Blueprint("negotiations", __name__)

SIDES = ["STATION_GROUP", "DISTRIBUTOR"]
OFFER_STATUSES = ["SUBMITTED", "ACCEPTED", "REJECTED", "EXPIRED"]
NEGOTIATION_STATUSES = [
    "OPEN", "AWAITING_STATION_OFFER", "AWAITING_DISTRIBUTOR_RESPONSE",
    "IMPASSE", "CONSENTED", "CANCELLED",
]
OPEN_STATUSES = ("OPEN", "AWAITING_STATION_OFFER", "AWAITING_DISTRIBUTOR_RESPONSE", "IMPASSE")
EVENT_TYPES = [
    "MEETING_HELD", "PROPOSAL_EXCHANGED", "INFORMATION_REQUEST",
    "INFORMATION_RESPONSE", "DELAY_OBJECTION",
]
NOTICE_CHANNELS = ["ON_AIR_CRAWL", "BILL_INSERT", "EMAIL", "WEBSITE"]
NOTICE_STATUSES = ["SERVED", "SUPERSEDED"]
PRICEABLE_STATUSES = ("REPORTED", "UNDER_AUDIT", "ADJUSTED", "ACCEPTED")


def _supersede_notices(negotiation):
    """A notice moves SERVED -> SUPERSEDED whenever its negotiation leaves IMPASSE."""
    for notice in derive.notices_of(negotiation["id"]):
        if notice["status"] == "SERVED":
            notice["status"] = "SUPERSEDED"
            touch(notice)


@bp.get("/retrans/negotiations/<negotiation_id>")
def read_negotiation(negotiation_id):
    authenticate(ALL_ROLES)
    negotiation = derive.get_negotiation(negotiation_id)
    return object_response(derive.negotiation_json(negotiation))


@bp.post("/retrans/negotiations/<negotiation_id>/offers")
def create_offer(negotiation_id):
    user_id, role = authenticate(["StationGroupNegotiator", "DistributorRep"])
    body = body_json()
    base_rate = take_int(body, "base_rate_per_sub_cents", minimum=1,
                         maximum=MAX_RATE_PER_SUB_CENTS)
    escalator = take_int(body, "escalator_bp_per_year", minimum=0, maximum=1000)
    term_months = take_int(body, "term_months", minimum=12, maximum=120)
    tier = take_enum(body, "tier", TIERS)
    penetration = take_int(body, "penetration_commitment_bp", minimum=0, maximum=10000)
    includes_digital = take_bool(body, "includes_digital_rights")
    includes_ooh = take_bool(body, "includes_ooh_rights")
    includes_streaming = take_bool(body, "includes_streaming_rights")
    report_id = take_str(body, "subscriber_report_id")

    negotiation = derive.get_negotiation(negotiation_id)
    report = derive.get_report(report_id)
    election = derive.election_of_negotiation(negotiation)

    side = "STATION_GROUP" if role == "StationGroupNegotiator" else "DISTRIBUTOR"
    # Priority 6 -- the caller must be the counterparty its side names.
    if side == "STATION_GROUP":
        if user_id != election["station_id"]:
            raise ApiError("ERR_NOT_COUNTERPARTY")
        allowed_states = ("OPEN", "AWAITING_STATION_OFFER", "IMPASSE")
    else:
        if user_id != election["distributor_id"]:
            raise ApiError("ERR_NOT_COUNTERPARTY")
        allowed_states = ("OPEN", "AWAITING_DISTRIBUTOR_RESPONSE")
    # Priority 10 -- turn order and the two terminal negotiation states.
    if negotiation["status"] not in allowed_states or election["status"] != "NEGOTIATING":
        raise ApiError("ERR_NEGOTIATION_NOT_OPEN")
    # Priority 17 -- a must-carry election has nothing to negotiate.
    if election["election_type"] != "RETRANS_CONSENT":
        raise ApiError("ERR_MUST_CARRY_NO_NEGOTIATION")

    affiliation = derive.active_affiliation(election["station_id"])
    # Priority 25 -- every right in the grant must be grantable.
    grantable = {
        "includes_digital_rights": bool(affiliation and affiliation["digital_rights_grantable"]),
        "includes_ooh_rights": bool(affiliation and affiliation["ooh_rights_grantable"]),
        "includes_streaming_rights": bool(affiliation and affiliation["streaming_rights_grantable"]),
    }
    requested = {
        "includes_digital_rights": includes_digital,
        "includes_ooh_rights": includes_ooh,
        "includes_streaming_rights": includes_streaming,
    }
    for field, wanted in requested.items():
        if wanted and not grantable[field]:
            raise ApiError("ERR_RIGHTS_NOT_GRANTABLE")
    # Priority 26 -- the station must hold an ACTIVE affiliation.
    if affiliation is None:
        raise ApiError("ERR_AFFILIATION_NOT_ACTIVE")
    # Priority 28 -- the offered tier must be permitted by that affiliation.
    if tier not in affiliation["permitted_tiers"]:
        raise ApiError("ERR_TIER_NOT_PERMITTED")

    compound = calc.compound_annual_ladder(base_rate, escalator, term_months)
    # Priority 33 -- the cap applies to every rate in the projected ladder.
    if any(rate > MAX_RATE_PER_SUB_CENTS for rate in compound):
        raise ApiError("ERR_RATE_CAP_EXCEEDED")

    # Priority 35 -- the report must be this counterparty pair's and priceable.
    if (report["station_id"] != election["station_id"]
            or report["distributor_id"] != election["distributor_id"]
            or report["status"] not in PRICEABLE_STATUSES):
        raise ApiError("ERR_REPORT_NOT_PRICEABLE")

    _adjusted, basis = derive.report_basis(report, True)
    row = base_row()
    row.update({
        "negotiation_id": negotiation_id,
        "offered_by": side,
        "round_number": derive.round_number(negotiation_id) + 1,
        "base_rate_per_sub_cents": base_rate,
        "escalator_bp_per_year": escalator,
        "term_months": term_months,
        "tier": tier,
        "penetration_commitment_bp": penetration,
        "includes_digital_rights": includes_digital,
        "includes_ooh_rights": includes_ooh,
        "includes_streaming_rights": includes_streaming,
        "subscriber_report_id": report_id,
        "projection_basis_subscribers": basis,
        "year_rate_schedule_compound_cents": compound,
        "projected_total_fee_cents": calc.whole_term_total_fee(compound, basis, term_months),
        "status": "SUBMITTED",
        "rejection_reason": None,
    })
    db.offers[row["id"]] = row

    was_impasse = negotiation["status"] == "IMPASSE"
    negotiation["status"] = (
        "AWAITING_DISTRIBUTOR_RESPONSE" if side == "STATION_GROUP" else "AWAITING_STATION_OFFER"
    )
    if was_impasse and side == "STATION_GROUP":
        _supersede_notices(negotiation)
    touch(negotiation)
    return object_response(derive.offer_json(row), 201)


@bp.get("/retrans/negotiations/<negotiation_id>/offers")
def list_negotiation_offers(negotiation_id):
    authenticate(ALL_ROLES)
    limit, offset = pagination()
    offered_by = query_enum("offered_by", SIDES)
    status = query_enum("status", OFFER_STATUSES)
    derive.get_negotiation(negotiation_id)
    rows = derive.offers_of(negotiation_id)
    if offered_by is not None:
        rows = [r for r in rows if r["offered_by"] == offered_by]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    items, total = paginate(rows, limit, offset, derive.offer_json)
    return array_response(items, limit, offset, total)


@bp.get("/retrans/offers")
def list_offers():
    authenticate(ALL_ROLES)
    limit, offset = pagination()
    negotiation_id = query_str("negotiation_id")
    report_id = query_str("subscriber_report_id")
    offered_by = query_enum("offered_by", SIDES)
    status = query_enum("status", OFFER_STATUSES)
    rows = derive.rows_of(db.offers)
    if negotiation_id is not None:
        rows = [r for r in rows if r["negotiation_id"] == negotiation_id]
    if report_id is not None:
        rows = [r for r in rows if r["subscriber_report_id"] == report_id]
    if offered_by is not None:
        rows = [r for r in rows if r["offered_by"] == offered_by]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    items, total = paginate(rows, limit, offset, derive.offer_json)
    return array_response(items, limit, offset, total)


@bp.get("/retrans/offers/<offer_id>")
def read_offer(offer_id):
    authenticate(ALL_ROLES)
    offer = derive.get_offer(offer_id)
    return object_response(derive.offer_json(offer))


@bp.post("/retrans/offers/<offer_id>/accept")
def accept_offer(offer_id):
    user_id, _role = authenticate(["GroupCounsel"])
    body = body_json()
    expected_version = take_int(body, "expected_negotiation_version")
    effective_start = take_dt(body, "effective_start_utc")
    effective_end = take_dt(body, "effective_end_utc")
    if effective_end <= effective_start:
        raise ApiError("ERR_INVALID_REQUEST",
                       "Field 'effective_end_utc' must be strictly after 'effective_start_utc'.")
    offer = derive.get_offer(offer_id)
    negotiation = derive.get_negotiation(offer["negotiation_id"])
    election = derive.election_of_negotiation(negotiation)
    # Priority 11 -- only an outstanding offer may be accepted.
    if offer["status"] != "SUBMITTED":
        raise ApiError("ERR_OFFER_NOT_OUTSTANDING")
    if negotiation["status"] not in OPEN_STATUSES or election["status"] != "NEGOTIATING":
        raise ApiError("ERR_NEGOTIATION_NOT_OPEN")
    if election["election_type"] != "RETRANS_CONSENT":
        raise ApiError("ERR_MUST_CARRY_NO_NEGOTIATION")

    # Priority 31 -- carriage terms are half-open and may not overlap on a slot.
    slot = (election["station_id"], election["distributor_id"])
    for other in sort_rows(list(db.agreements.values())):
        if other["execution_status"] not in ("PENDING_EXECUTION", "EXECUTED"):
            continue
        if derive.slot_of_agreement(other) != slot:
            continue
        other_start = parse_iso(other["effective_start_utc"])
        other_end = parse_iso(other["effective_end_utc"])
        if other_start is None or other_end is None:
            continue
        if effective_start < other_end and other_start < effective_end:
            raise ApiError("ERR_CARRIAGE_TERM_OVERLAP")

    # Priority 38 -- the staleness guard sits last in the sequence.
    if expected_version != negotiation["version"]:
        raise ApiError("ERR_STALE_NEGOTIATION_VERSION")

    station = db.stations[election["station_id"]]
    scope = []
    if offer["includes_digital_rights"]:
        scope.append("DIGITAL")
    if offer["includes_ooh_rights"]:
        scope.append("OUT_OF_HOME")
    if offer["includes_streaming_rights"]:
        scope.append("STREAMING")
    scope = [term for term in RIGHTS_TERM_ORDER if term in scope]

    agreement = base_row()
    agreement.update({
        "negotiation_id": negotiation["id"],
        "accepted_offer_id": offer["id"],
        "effective_start_utc": fmt_dt(effective_start),
        "effective_end_utc": fmt_dt(effective_end),
        "execution_status": "PENDING_EXECUTION",
        "network_approval_status": (
            "NOT_REQUIRED" if station["network_affiliation"] == "INDEPENDENT" else "PENDING_NETWORK"
        ),
        "accepted_by_user_id": user_id,
        "executed_by_user_id": None,
        "granted_rights_scope": scope,
        "contract_year_rate_schedule_cents": calc.simple_annual_ladder(
            offer["base_rate_per_sub_cents"],
            offer["escalator_bp_per_year"],
            offer["term_months"],
        ),
        "decision_note": None,
    })
    db.agreements[agreement["id"]] = agreement

    offer["status"] = "ACCEPTED"
    touch(offer)
    was_impasse = negotiation["status"] == "IMPASSE"
    negotiation["status"] = "CONSENTED"
    touch(negotiation)
    election["status"] = "CONSENT_GRANTED"
    touch(election)
    touch(station)
    for sibling in derive.offers_of(negotiation["id"]):
        if sibling["id"] != offer["id"] and sibling["status"] == "SUBMITTED":
            sibling["status"] = "EXPIRED"
            touch(sibling)
    if was_impasse:
        _supersede_notices(negotiation)
    return object_response(derive.agreement_json(agreement), 201)


@bp.post("/retrans/offers/<offer_id>/reject")
def reject_offer(offer_id):
    user_id, role = authenticate(["StationGroupNegotiator", "DistributorRep"])
    body = body_json()
    reason = take_str(body, "rejection_reason", min_len=1)
    offer = derive.get_offer(offer_id)
    negotiation = derive.get_negotiation(offer["negotiation_id"])
    election = derive.election_of_negotiation(negotiation)
    # Priority 6 -- only the counterparty of offered_by may reject.
    if offer["offered_by"] == "STATION_GROUP":
        if role != "DistributorRep" or user_id != election["distributor_id"]:
            raise ApiError("ERR_NOT_COUNTERPARTY")
    else:
        if role != "StationGroupNegotiator" or user_id != election["station_id"]:
            raise ApiError("ERR_NOT_COUNTERPARTY")
    # Priority 11 -- the offer must still be outstanding.
    if offer["status"] != "SUBMITTED":
        raise ApiError("ERR_OFFER_NOT_OUTSTANDING")
    if negotiation["status"] not in OPEN_STATUSES:
        raise ApiError("ERR_NEGOTIATION_NOT_OPEN")

    offer["status"] = "REJECTED"
    offer["rejection_reason"] = reason
    touch(offer)
    # Rejection is a position statement: the negotiation is left untouched.
    return object_response(derive.offer_json(offer))


@bp.post("/retrans/negotiations/<negotiation_id>/good-faith-log")
def append_good_faith(negotiation_id):
    _user_id, role = authenticate(["StationGroupNegotiator", "DistributorRep", "ComplianceOfficer"])
    body = body_json()
    event_type = take_enum(body, "event_type", EVENT_TYPES)
    occurred_at = take_dt(body, "occurred_at_utc")
    summary = take_str(body, "summary", min_len=1, max_len=500)
    negotiation = derive.get_negotiation(negotiation_id)
    # Priority 10 -- CONSENTED and CANCELLED negotiations accept no entries.
    if negotiation["status"] not in OPEN_STATUSES:
        raise ApiError("ERR_NEGOTIATION_NOT_OPEN")

    row = base_row(with_version=False)
    row.update({
        "negotiation_id": negotiation_id,
        "event_type": event_type,
        "occurred_at_utc": fmt_dt(occurred_at),
        "summary": summary,
        "actor_role": role,
        "sequence_index": len([
            e for e in db.good_faith.values() if e["negotiation_id"] == negotiation_id
        ]) + 1,
    })
    db.good_faith[row["id"]] = row
    return object_response(derive.good_faith_json(row), 201)


@bp.get("/retrans/negotiations/<negotiation_id>/good-faith-log")
def list_good_faith(negotiation_id):
    authenticate(ALL_ROLES)
    limit, offset = pagination()
    event_type = query_enum("event_type", EVENT_TYPES)
    derive.get_negotiation(negotiation_id)
    rows = derive.rows_of(db.good_faith, negotiation_id=negotiation_id)
    if event_type is not None:
        rows = [r for r in rows if r["event_type"] == event_type]
    items, total = paginate(rows, limit, offset, derive.good_faith_json)
    return array_response(items, limit, offset, total)


@bp.post("/retrans/negotiations/<negotiation_id>/declare-impasse")
def declare_impasse(negotiation_id):
    user_id, _role = authenticate(["StationGroupNegotiator"])
    body = body_json()
    take_str(body, "impasse_statement", min_len=1)
    negotiation = derive.get_negotiation(negotiation_id)
    election = derive.election_of_negotiation(negotiation)
    # Priority 6 -- the declaring negotiator must be the election's station.
    if user_id != election["station_id"]:
        raise ApiError("ERR_NOT_COUNTERPARTY")
    # Priority 10 -- CONSENTED and CANCELLED negotiations accept no declaration.
    if negotiation["status"] not in OPEN_STATUSES:
        raise ApiError("ERR_NEGOTIATION_NOT_OPEN")
    # Priority 23 -- at least three MEETING_HELD entries; exactly three passes.
    if derive.good_faith_meeting_count(negotiation_id) < MIN_GOOD_FAITH_MEETINGS:
        raise ApiError("ERR_GOOD_FAITH_NOT_SATISFIED")
    # Priority 24 -- both sides must have tabled at least one offer.
    if (derive.side_offer_count(negotiation_id, "STATION_GROUP") < 1
            or derive.side_offer_count(negotiation_id, "DISTRIBUTOR") < 1):
        raise ApiError("ERR_NO_OFFERS_EXCHANGED")

    negotiation["status"] = "IMPASSE"
    negotiation["impasse_declared_at_utc"] = now_iso()
    touch(negotiation)
    return object_response(derive.negotiation_json(negotiation))


@bp.post("/retrans/negotiations/<negotiation_id>/blackout-notices")
def serve_notice(negotiation_id):
    authenticate(["ComplianceOfficer"])
    body = body_json()
    notice_count = take_int(body, "subscriber_notice_count", minimum=1)
    channel = take_enum(body, "notice_channel", NOTICE_CHANNELS)
    negotiation = derive.get_negotiation(negotiation_id)
    # Priority 10 -- CONSENTED and CANCELLED negotiations accept no notice.
    if negotiation["status"] not in OPEN_STATUSES:
        raise ApiError("ERR_NEGOTIATION_NOT_OPEN")
    # Priority 22 -- service is timely at or before the deadline instant.
    deadline = parse_iso(negotiation.get("blackout_notice_deadline_utc"))
    if deadline is None or clock() > deadline:
        raise ApiError("ERR_BLACKOUT_NOTICE_LATE")

    election = derive.election_of_negotiation(negotiation)
    distributor = db.distributors[election["distributor_id"]]
    row = base_row()
    row.update({
        "negotiation_id": negotiation_id,
        "subscriber_notice_count": notice_count,
        "notice_channel": channel,
        "served_at_utc": now_iso(),
        "required_notice_days_snapshot": distributor["required_blackout_notice_days"],
        "status": "SERVED",
    })
    db.notices[row["id"]] = row
    return object_response(derive.notice_json(row), 201)


@bp.get("/retrans/negotiations/<negotiation_id>/blackout-notices")
def list_notices(negotiation_id):
    authenticate(ALL_ROLES)
    limit, offset = pagination()
    status = query_enum("status", NOTICE_STATUSES)
    derive.get_negotiation(negotiation_id)
    rows = derive.notices_of(negotiation_id)
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    items, total = paginate(rows, limit, offset, derive.notice_json)
    return array_response(items, limit, offset, total)
