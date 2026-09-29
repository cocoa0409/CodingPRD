"""Participant records, locator searches, mortality verification, benefit audits."""

import re

from flask import Blueprint, request

from db import db, make_entity, now, ordered, public, touch
from errors import api_error
from middleware import (
    authenticate,
    body,
    filter_arg,
    get_datetime,
    get_enum,
    get_int,
    get_string,
    lookup,
    pagination,
    require_range,
    slice_page,
)
from response import list_response, object_response
from services import calculations as calc
from services import domain as dom

bp = Blueprint("participants", __name__)

SSN_RE = re.compile(r"^\d{4}$")

PARTICIPANT_LIST_ROLES = [
    "PlanSponsor",
    "PlanFiduciary",
    "Actuary",
    "PlanAdministrator",
    "Regulator",
]
PARTICIPANT_GET_ROLES = PARTICIPANT_LIST_ROLES + ["Participant"]
AUDIT_LIST_ROLES = PARTICIPANT_LIST_ROLES

COHORTS = ("RETIREE_IN_PAY", "DEFERRED_VESTED")
AUDIT_BASES = ("PLAN_DOCUMENT", "COLLECTIVE_AGREEMENT", "PRIOR_ADMINISTRATOR_FILE")
TIERS = {1: "TIER_1", 2: "TIER_2", 3: "TIER_3"}


# --------------------------------------------------------------------------
# participants
# --------------------------------------------------------------------------


@bp.post("/prt/plans/<plan_id>/participants")
def create_participant(plan_id):
    authenticate(["PlanAdministrator"])
    plan = lookup("plans", plan_id)
    payload = body()
    reference = get_string(payload, "participant_reference")
    if len(reference) < 1 or len(reference) > 40:
        raise api_error("ERR_INVALID_REQUEST", "participant_reference has an invalid length.")
    cohort = get_enum(payload, "cohort", COHORTS)
    stated = get_int(payload, "stated_monthly_benefit_cents")
    fame = get_int(payload, "final_average_monthly_earnings_cents")
    service_months = get_int(payload, "credited_service_months")
    date_of_birth = get_datetime(payload, "date_of_birth", required=True)
    ssn_last4 = get_string(payload, "ssn_last4", required=False)
    if ssn_last4 is not None and not SSN_RE.match(ssn_last4.strip()):
        raise api_error("ERR_INVALID_REQUEST", "ssn_last4 must hold exactly four digits.")
    require_range(stated, "stated_monthly_benefit_cents", 1, None)
    require_range(fame, "final_average_monthly_earnings_cents", 1, None)
    require_range(service_months, "credited_service_months", 0, 600)
    for existing in db.participants.values():
        if existing["plan_id"] == plan["id"] and existing["participant_reference"] == reference:
            raise api_error(
                "ERR_INVALID_REQUEST", "participant_reference is already used in this plan."
            )

    participant = make_entity()
    participant["plan_id"] = plan["id"]
    participant["tranche_id"] = None
    participant["participant_reference"] = reference
    participant["cohort"] = cohort
    participant["date_of_birth"] = date_of_birth
    participant["ssn_last4"] = ssn_last4.strip() if ssn_last4 is not None else None
    participant["stated_monthly_benefit_cents"] = stated
    participant["final_average_monthly_earnings_cents"] = fame
    participant["credited_service_months"] = service_months
    participant["audited_monthly_benefit_cents"] = stated
    participant["participant_status"] = "IN_PLAN"
    participant["mortality_status"] = "UNVERIFIED"
    participant["address_status"] = "UNCONFIRMED"
    participant["address_search_tier"] = "NONE"
    participant["address_search_attempts"] = 0
    participant["confirmed_address_line1"] = None
    participant["confirmed_postal_code"] = None
    participant["date_of_death"] = None
    participant["benefit_audit_status"] = "NOT_AUDITED"
    participant["data_confidence_score"] = 0
    participant["data_status"] = "NEEDS_REVIEW"
    participant["accounting_liability_cents"] = 0
    participant["settlement_liability_cents"] = 0
    dom.refresh_participant(participant, bump=False)
    db.participants[participant["id"]] = participant
    dom.recompute_plan_participant_liability(plan)
    return object_response(public(participant), 201)


@bp.get("/prt/participants")
def list_participants():
    authenticate(PARTICIPANT_LIST_ROLES)
    plan_id = filter_arg("plans", "plan_id")
    tranche_id = filter_arg("tranches", "tranche_id")
    cohort = request.args.get("cohort")
    participant_status = request.args.get("participant_status")
    mortality_status = request.args.get("mortality_status")
    address_status = request.args.get("address_status")
    data_status = request.args.get("data_status")
    limit, offset = pagination()
    records = ordered(list(db.participants.values()))
    if plan_id is not None:
        records = [p for p in records if p["plan_id"] == plan_id]
    if tranche_id is not None:
        records = [p for p in records if p["tranche_id"] == tranche_id]
    if cohort is not None:
        records = [p for p in records if p["cohort"] == cohort]
    if participant_status is not None:
        records = [p for p in records if p["participant_status"] == participant_status]
    if mortality_status is not None:
        records = [p for p in records if p["mortality_status"] == mortality_status]
    if address_status is not None:
        records = [p for p in records if p["address_status"] == address_status]
    if data_status is not None:
        records = [p for p in records if p["data_status"] == data_status]
    page, total = slice_page(records, limit, offset)
    return list_response([public(p) for p in page], limit, offset, total)


@bp.get("/prt/participants/<participant_id>")
def get_participant(participant_id):
    authenticate(PARTICIPANT_GET_ROLES)
    participant = lookup("participants", participant_id)
    return object_response(public(participant))


# --------------------------------------------------------------------------
# address cleansing
# --------------------------------------------------------------------------


@bp.post("/prt/participants/<participant_id>/address-searches")
def address_search(participant_id):
    authenticate(["PlanAdministrator"])
    participant = lookup("participants", participant_id)
    payload = body()
    result = get_enum(payload, "search_result", ("NO_MATCH", "CONFIRMED_MATCH"))
    line1 = None
    postal = None
    if result == "CONFIRMED_MATCH":
        line1 = get_string(payload, "confirmed_address_line1")
        postal = get_string(payload, "confirmed_postal_code")

    if participant["address_search_attempts"] >= calc.ADDRESS_SEARCH_MAX_TIERS:
        raise api_error("ERR_ADDRESS_SEARCH_TIER_EXHAUSTED")
    if participant["address_status"] != "UNCONFIRMED":
        raise api_error("ERR_PARTICIPANT_STATE_INVALID")

    attempts = participant["address_search_attempts"] + 1
    participant["address_search_attempts"] = attempts
    participant["address_search_tier"] = TIERS[attempts]

    if result == "NO_MATCH":
        if attempts >= calc.ADDRESS_SEARCH_MAX_TIERS:
            participant["address_status"] = "UNLOCATABLE"
            dom.refresh_participant_confidence(participant)
        else:
            touch(participant)
        return object_response(public(participant))

    participant["address_status"] = "CONFIRMED"
    participant["confirmed_address_line1"] = line1
    participant["confirmed_postal_code"] = postal
    dom.refresh_participant_confidence(participant)
    tranche = dom.participant_open_tranche(participant)
    if tranche is not None:
        dom.recompute_tranche(tranche, count=False, liabilities=False)
    return object_response(public(participant))


# --------------------------------------------------------------------------
# mortality verification
# --------------------------------------------------------------------------

MATCH_RESULTS = (
    "NO_MATCH",
    "DEATH_MATCH",
    "DISPUTE_FILED",
    "DISPUTE_RESOLVED_ALIVE",
    "DISPUTE_RESOLVED_DECEASED",
)


@bp.post("/prt/participants/<participant_id>/mortality-checks")
def mortality_check(participant_id):
    authenticate(["PlanAdministrator"])
    participant = lookup("participants", participant_id)
    payload = body()
    result = get_enum(payload, "match_result", MATCH_RESULTS)
    date_of_death = None
    if result == "DEATH_MATCH":
        date_of_death = get_datetime(payload, "date_of_death")
    if result == "DISPUTE_FILED":
        get_string(payload, "dispute_reason")

    current = participant["mortality_status"]

    if result == "NO_MATCH":
        if current not in ("UNVERIFIED", "DEATH_DISPUTED"):
            raise api_error("ERR_PARTICIPANT_STATE_INVALID")
        participant["mortality_status"] = "ALIVE_CONFIRMED"
        dom.refresh_participant_confidence(participant)
        tranche = dom.participant_open_tranche(participant)
        if tranche is not None:
            dom.recompute_tranche(tranche, count=False, liabilities=False)
        return object_response(public(participant))

    if result == "DEATH_MATCH":
        if current not in ("UNVERIFIED", "ALIVE_CONFIRMED", "DEATH_DISPUTED"):
            raise api_error("ERR_PARTICIPANT_STATE_INVALID")
        participant["mortality_status"] = "DECEASED_CONFIRMED"
        participant["date_of_death"] = date_of_death
        for election in db.elections.values():
            if election["participant_id"] != participant["id"]:
                continue
            if election["election_status"] in (
                "NOTICE_SENT",
                "ELECTED_LUMP_SUM",
                "ELECTED_ANNUITY",
            ):
                election["election_status"] = "VOIDED"
                touch(election)
        dom.refresh_participant(participant)
        tranche = dom.participant_open_tranche(participant)
        if tranche is not None:
            dom.recompute_tranche(tranche, readiness="BLOCKED", count=False)
        return object_response(public(participant))

    if result == "DISPUTE_FILED":
        if current != "DECEASED_CONFIRMED":
            raise api_error("ERR_PARTICIPANT_STATE_INVALID")
        participant["mortality_status"] = "DEATH_DISPUTED"
        dom.refresh_participant_confidence(participant)
        return object_response(public(participant))

    if result == "DISPUTE_RESOLVED_ALIVE":
        if current != "DEATH_DISPUTED":
            raise api_error("ERR_PARTICIPANT_STATE_INVALID")
        participant["mortality_status"] = "ALIVE_CONFIRMED"
        participant["date_of_death"] = None
        dom.refresh_participant(participant)
        tranche = dom.participant_open_tranche(participant)
        if tranche is not None:
            dom.recompute_tranche(tranche, count=False)
        return object_response(public(participant))

    # DISPUTE_RESOLVED_DECEASED
    if current != "DEATH_DISPUTED":
        raise api_error("ERR_PARTICIPANT_STATE_INVALID")
    participant["mortality_status"] = "DECEASED_CONFIRMED"
    dom.refresh_participant_confidence(participant)
    return object_response(public(participant))


# --------------------------------------------------------------------------
# benefit audits
# --------------------------------------------------------------------------


@bp.post("/prt/participants/<participant_id>/benefit-audits")
def create_audit(participant_id):
    authenticate(["Actuary"])
    participant = lookup("participants", participant_id)
    payload = body()
    expected = get_int(payload, "expected_participant_version")
    basis = get_enum(payload, "audit_basis", AUDIT_BASES, required=False, default="PLAN_DOCUMENT")
    fame = get_int(payload, "final_average_monthly_earnings_cents", required=False)
    service_months = get_int(payload, "credited_service_months", required=False)
    require_range(fame, "final_average_monthly_earnings_cents", 0, None)
    require_range(service_months, "credited_service_months", 0, 600)
    if expected != participant["version"]:
        raise api_error("ERR_STALE_PARTICIPANT_VERSION")

    existing = dom.participant_audits(participant["id"])
    for audit in existing:
        if audit["audit_status"] != "SUPERSEDED":
            audit["audit_status"] = "SUPERSEDED"
            touch(audit)

    if fame is None:
        fame = participant["final_average_monthly_earnings_cents"]
    if service_months is None:
        service_months = participant["credited_service_months"]
    stated = participant["stated_monthly_benefit_cents"]
    recomputed, variance, status = calc.benefit_recomputation(fame, service_months, stated)

    audit = make_entity()
    audit["participant_id"] = participant["id"]
    audit["audit_basis"] = basis
    audit["audit_sequence"] = len(existing) + 1
    audit["stated_monthly_benefit_cents"] = stated
    audit["recomputed_monthly_benefit_cents"] = recomputed
    audit["variance_cents"] = variance
    audit["audit_status"] = status
    audit["resolution"] = None
    audit["override_rationale"] = None
    audit["reopened_by_complaint_id"] = None
    db.audits[audit["id"]] = audit

    if status == "PASSED":
        participant["benefit_audit_status"] = "AUDIT_OPEN"
        dom.refresh_participant_confidence(participant)
    else:
        participant["benefit_audit_status"] = "CORRECTION_REQUIRED"
        dom.refresh_participant_confidence(participant)
        tranche = dom.participant_open_tranche(participant)
        if tranche is not None:
            dom.recompute_tranche(tranche, readiness="BLOCKED", count=False, liabilities=False)
    return object_response(public(audit), 201)


@bp.get("/prt/participants/<participant_id>/benefit-audits")
def list_audits(participant_id):
    authenticate(AUDIT_LIST_ROLES)
    participant = lookup("participants", participant_id)
    audit_status = request.args.get("audit_status")
    limit, offset = pagination()
    records = dom.participant_audits(participant["id"])
    if audit_status is not None:
        records = [a for a in records if a["audit_status"] == audit_status]
    page, total = slice_page(records, limit, offset)
    return list_response([public(a) for a in page], limit, offset, total)


@bp.post("/prt/benefit-audits/<audit_id>/resolution")
def resolve_audit(audit_id):
    authenticate(["Actuary"])
    audit = lookup("audits", audit_id)
    payload = body()
    resolution = get_enum(payload, "resolution", ("APPLY_CORRECTION", "ACCEPT_AS_IS"))
    override_rationale = None
    if resolution == "ACCEPT_AS_IS" and audit["audit_status"] in (
        "CORRECTION_REQUIRED",
        "REOPENED",
    ):
        override_rationale = get_string(payload, "override_rationale")

    status = audit["audit_status"]
    participant = db.participants.get(audit["participant_id"])

    if resolution == "ACCEPT_AS_IS" and status in ("PASSED", "CORRECTION_REQUIRED", "REOPENED"):
        audit["audit_status"] = "PASSED_CLOSED"
        audit["resolution"] = resolution
        audit["override_rationale"] = override_rationale
        participant["audited_monthly_benefit_cents"] = audit["stated_monthly_benefit_cents"]
        participant["benefit_audit_status"] = "PASSED_CLOSED"
        dom.refresh_participant(participant)
        touch(audit)
        return object_response(public(audit))

    if resolution == "APPLY_CORRECTION" and status in ("CORRECTION_REQUIRED", "REOPENED"):
        audit["audit_status"] = "CORRECTED"
        audit["resolution"] = resolution
        participant["audited_monthly_benefit_cents"] = audit["recomputed_monthly_benefit_cents"]
        participant["benefit_audit_status"] = "CORRECTED"
        dom.refresh_participant(participant)
        tranche = dom.participant_open_tranche(participant)
        if tranche is not None:
            dom.recompute_tranche(tranche, count=False)
        touch(audit)
        return object_response(public(audit))

    raise api_error("ERR_AUDIT_STATE_INVALID")
