"""Organizing group and organizer writes."""
import re
from decimal import Decimal

from flask import Blueprint

import calc
import cascade
import db
import response
import serialize
import validation as v
from errors import err
from middleware import authenticate
from routes.helpers import must_get

bp = Blueprint("groups", __name__)

CHARTER_TYPES = ("NATIONAL", "STATE_MEMBER", "STATE_NONMEMBER")
STAGES = (
    "ORGANIZING",
    "FILING_READY",
    "UNDER_REVIEW",
    "CONDITIONALLY_APPROVED",
    "PRE_OPENING",
    "OPEN",
    "ABANDONED",
)
BOARD_ROLES = (
    "PROPOSED_CEO",
    "PROPOSED_CFO",
    "PROPOSED_CRO",
    "PROPOSED_CCO",
    "DIRECTOR",
    "INVESTOR_ONLY",
)
FINDING_TYPES = ("NONE", "FINANCIAL_CRIME", "REGULATORY_ENFORCEMENT", "PERSONAL_BANKRUPTCY")
DIMENSIONS = ("FINGERPRINT", "CREDIT")
DIMENSION_OUTCOMES = {
    "FINGERPRINT": ("CLEARED", "FLAGGED"),
    "CREDIT": ("CLEARED", "ADVERSE"),
}
# PRD 304-312: UNDER_REVIEW and CONDITIONALLY_APPROVED are entered only by cascade.
STAGE_TRANSITIONS = {
    "ORGANIZING": ("FILING_READY", "ABANDONED"),
    "FILING_READY": ("ABANDONED",),
    "UNDER_REVIEW": ("ABANDONED",),
    "CONDITIONALLY_APPROVED": ("PRE_OPENING", "ABANDONED"),
    "PRE_OPENING": ("OPEN",),
    "OPEN": (),
    "ABANDONED": (),
}
_STATE_CODE = re.compile(r"^[A-Z]{2}$")


@bp.post("/de-novo/organizing-groups")
def create_group():
    authenticate(("CharterCounsel",))
    data = v.body()
    name = v.req_str(data, "proposed_bank_name", 1, 120)
    state_code = v.req_str(data, "home_state_code", 2, 2)
    if not _STATE_CODE.match(state_code):
        raise err("ERR_INVALID_REQUEST", "home_state_code must be two uppercase letters.")
    charter_type = v.req_enum(data, "charter_type", CHARTER_TYPES)
    target_opening_date = v.req_dt(data, "target_opening_date")
    if target_opening_date <= db.clock():
        raise err("ERR_TARGET_OPENING_DATE_IN_PAST")
    group = db.insert("groups", {
        "proposed_bank_name": name,
        "home_state_code": state_code,
        "charter_type": charter_type,
        "target_opening_date": target_opening_date,
        "stage": "ORGANIZING",
        "composition_status": "FORMING",
        "organizer_count": 0,
        "independent_organizer_count": 0,
        "max_affiliation_count": 0,
        "management_composite_score": Decimal("0.00"),
        "opening_blocked_reason": "NONE",
        "supervision_started_at": None,
        "supervision_year_index": 0,
    })
    db.commit()
    return response.object_response(serialize.group(group), 201)


@bp.post("/de-novo/organizing-groups/<group_id>/organizers")
def create_organizer(group_id):
    authenticate(("CharterCounsel",))
    data = v.body()
    full_name = v.req_str(data, "full_name", 1, 120)
    role_on_board = v.req_enum(data, "role_on_board", BOARD_ROLES)
    is_independent = v.req_bool(data, "is_independent")
    affiliation_code = v.req_str(data, "affiliation_code", 1, 32)
    banking_years = v.req_int(data, "banking_years", 0, 60)
    experience = v.req_int(data, "regulatory_experience_score", 0, 100)
    group = must_get("groups", group_id)
    if group["stage"] not in ("ORGANIZING", "FILING_READY"):
        raise err("ERR_GROUP_STAGE_LOCKED")
    if role_on_board in calc.KEY_OFFICER_ROLES:
        for row in calc.organizers_of(group["id"]):
            if row["role_on_board"] == role_on_board:
                raise err("ERR_OFFICER_ROLE_ALREADY_FILLED")
    organizer = db.insert("organizers", {
        "group_id": group["id"],
        "full_name": full_name,
        "role_on_board": role_on_board,
        "is_independent": is_independent,
        "affiliation_code": affiliation_code,
        "banking_years": banking_years,
        "regulatory_experience_score": experience,
        "fingerprint_state": "PENDING",
        "credit_state": "PENDING",
        "adverse_finding_type": "NONE",
        "qualification_subscore": 0,
        "waiver_granted": False,
        "waiver_rationale": None,
        "qualification_status": "PENDING",
    })
    calc.recompute_organizer(organizer)
    calc.recompute_group_derived(group)
    db.touch(group)
    db.commit()
    return response.object_response(serialize.organizer(organizer), 201)


@bp.post("/de-novo/organizers/<organizer_id>/background-result")
def background_result(organizer_id):
    authenticate(("CharteringExaminer",))
    data = v.body()
    dimension = v.req_enum(data, "dimension", DIMENSIONS)
    outcome = v.req_enum(data, "outcome", DIMENSION_OUTCOMES[dimension])
    finding_type = v.opt_enum(data, "adverse_finding_type", FINDING_TYPES)
    organizer = must_get("organizers", organizer_id)
    field = "fingerprint_state" if dimension == "FINGERPRINT" else "credit_state"
    if organizer[field] != "PENDING":
        raise err("ERR_BACKGROUND_ALREADY_RESOLVED")
    if outcome in ("FLAGGED", "ADVERSE") and (finding_type is None or finding_type == "NONE"):
        raise err("ERR_ADVERSE_FINDING_TYPE_REQUIRED")
    organizer[field] = outcome
    if finding_type is not None:
        organizer["adverse_finding_type"] = finding_type
    calc.recompute_organizer(organizer)
    db.touch(organizer)
    group = db.get("groups", organizer["group_id"])
    if group is not None:
        calc.recompute_group_derived(group)
        db.touch(group)
    db.commit()
    return response.object_response(serialize.organizer(organizer))


@bp.post("/de-novo/organizers/<organizer_id>/qualification-waiver")
def qualification_waiver(organizer_id):
    authenticate(("CharteringExaminer",))
    data = v.body()
    rationale = v.req_str(data, "waiver_rationale", 20, None)
    organizer = must_get("organizers", organizer_id)
    if organizer["qualification_status"] != "DISQUALIFIED" or organizer["waiver_granted"]:
        raise err("ERR_WAIVER_NOT_APPLICABLE")
    if organizer["adverse_finding_type"] == "FINANCIAL_CRIME":
        raise err("ERR_WAIVER_BARRED_BY_FINDING")
    organizer["waiver_granted"] = True
    organizer["waiver_rationale"] = rationale
    calc.recompute_organizer(organizer)
    db.touch(organizer)
    group = db.get("groups", organizer["group_id"])
    if group is not None:
        calc.recompute_group_derived(group)
        db.touch(group)
    db.commit()
    return response.object_response(serialize.organizer(organizer))


def _gate_filing_ready(group):
    if group["composition_status"] != "COMPOSITION_MET":
        raise err("ERR_GROUP_COMPOSITION_INCOMPLETE")
    if group["management_composite_score"] < calc.MIN_MANAGEMENT_COMPOSITE_SCORE:
        raise err("ERR_MANAGEMENT_SCORE_BELOW_MINIMUM")
    submitted = [p for p in calc.plans_of(group["id"]) if p["status"] == "SUBMITTED"]
    if not submitted:
        raise err("ERR_NO_SUBMITTED_BUSINESS_PLAN")


def _gate_pre_opening(group):
    filings = calc.filings_of(group["id"])
    approved = [f for f in filings if f["status"] == "CONDITIONALLY_APPROVED"]
    if len(approved) != 2:
        raise err("ERR_FILINGS_NOT_CONDITIONALLY_APPROVED")
    if calc.raise_in(group["id"], ("ESCROW_LOCKED", "RELEASED")) is None:
        raise err("ERR_ESCROW_NOT_LOCKED")
    accepted = set()
    for policy in calc.policies_of(group["id"]):
        if policy["status"] == "EXAMINER_ACCEPTED":
            accepted.add(policy["domain"])
    for domain in calc.REQUIRED_POLICY_DOMAINS:
        if domain not in accepted:
            raise err("ERR_POLICY_COVERAGE_INCOMPLETE")
    critical = [c for c in calc.contracts_of(group["id"]) if c["criticality"] == "CRITICAL"]
    if not critical:
        raise err("ERR_CRITICAL_VENDOR_NOT_SIGNED")
    for contract in critical:
        if contract["status"] != "SIGNED":
            raise err("ERR_CRITICAL_VENDOR_NOT_SIGNED")
    if not any(c["service_domain"] == "CORE_PROCESSING" for c in critical):
        raise err("ERR_CRITICAL_VENDOR_NOT_SIGNED")


def _gate_open(group):
    for filing in calc.filings_of(group["id"]):
        if filing["open_blocking_condition_count"] > 0:
            raise err("ERR_PRE_OPENING_CONDITIONS_OPEN")
    exams_passed = [e for e in calc.exams_of(group["id"]) if e["status"] == "PASSED"]
    final_filings = [f for f in calc.filings_of(group["id"]) if f["status"] == "FINAL_APPROVED"]
    released = calc.raise_in(group["id"], ("RELEASED",))
    if (not exams_passed or len(final_filings) != 2 or released is None
            or group["opening_blocked_reason"] != "NONE"):
        raise err("ERR_READINESS_EXAM_NOT_PASSED")


@bp.post("/de-novo/organizing-groups/<group_id>/advance")
def advance_group(group_id):
    authenticate(("CharterCounsel",))
    data = v.body()
    target_stage = v.req_enum(data, "target_stage", STAGES)
    group = must_get("groups", group_id)
    if target_stage not in STAGE_TRANSITIONS.get(group["stage"], ()):
        raise err("ERR_STAGE_TRANSITION_NOT_ALLOWED")
    if target_stage == "FILING_READY":
        _gate_filing_ready(group)
    elif target_stage == "PRE_OPENING":
        _gate_pre_opening(group)
    elif target_stage == "OPEN":
        _gate_open(group)

    previous_stage = group["stage"]
    group["stage"] = target_stage
    if target_stage in ("FILING_READY", "CONDITIONALLY_APPROVED", "PRE_OPENING"):
        group["opening_blocked_reason"] = "NONE"
    if target_stage == "OPEN":
        group["supervision_started_at"] = db.clock()
        calc.recompute_supervision(group)
    db.touch(group)
    if previous_stage == "PRE_OPENING":
        # PRD 314: leaving PRE_OPENING for any target stage wipes scheduled exams.
        cascade.cancel_scheduled_exams(group["id"])
    if target_stage == "ABANDONED":
        cascade.group_abandoned_cascade(group)
    db.commit()
    return response.object_response(serialize.group(group))
