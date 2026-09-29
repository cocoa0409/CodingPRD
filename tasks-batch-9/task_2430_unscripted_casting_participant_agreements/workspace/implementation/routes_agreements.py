"""Participant agreements, negotiation rounds, post-obligations and complaints."""

from flask import Blueprint

import calc
import services
import store
from clock import clock, parse_date, parse_iso
from envelope import list_response, object_response
from errors import ApiError
from store import serialize, serialize_all, touch
from validation import (
    ALL_ROLES,
    OPERATOR_ROLES,
    authenticate,
    filter_arg,
    json_body,
    opt_bool,
    opt_int,
    opt_string,
    pagination,
    paginate,
    req_enum,
    req_int,
    req_string,
    require_owner,
)

bp = Blueprint("agreements", __name__)

CONFIDENTIALITY_TIERS = ("STANDARD", "ENHANCED", "PERPETUAL")
DEPICTION_SCOPES = ("FULL", "LIMITED", "PSEUDONYMIZED")
STIPEND_STRUCTURES = ("FLAT", "PER_EPISODE", "TIERED")
VOID_REASONS = ("WELFARE_BREACH", "APPLICANT_WITHDRAWN", "BUSINESS_AFFAIRS_VOID", "SUPERSEDED")
COMPLAINT_CATEGORIES = ("WELFARE", "MISREPRESENTATION", "HARASSMENT", "PAYMENT")
ROUTES = ("AFTERCARE", "ESCALATION")


# -------------------------------------------------------------------- drafting
@bp.post("/casting/participant-agreements")
def draft_agreement():
    user_id, _role = authenticate(("BusinessAffairs",))
    body = json_body()

    # rung 6 — body foreign keys, left to right
    applicant = None
    production = None
    supersede_target = None
    if isinstance(body.get("applicant_id"), str):
        applicant = services.get_applicant(body["applicant_id"])
    if isinstance(body.get("production_id"), str):
        production = services.get_production(body["production_id"])
    if isinstance(body.get("supersedes_agreement_id"), str):
        supersede_target = services.get_agreement(body["supersedes_agreement_id"])

    # rung 7 — body shape
    applicant_id = req_string(body, "applicant_id")
    if applicant is None:
        applicant = services.get_applicant(applicant_id)
    production_id = req_string(body, "production_id")
    if production is None:
        production = services.get_production(production_id)
    exclusivity_window_days = req_int(body, "exclusivity_window_days", minimum=0, maximum=730)
    confidentiality_tier = req_enum(body, "confidentiality_tier", CONFIDENTIALITY_TIERS)
    depiction_rights_scope = req_enum(body, "depiction_rights_scope", DEPICTION_SCOPES)
    stipend_structure = req_enum(body, "stipend_structure", STIPEND_STRUCTURES)
    base_stipend_cents = req_int(body, "base_stipend_cents", minimum=0)
    episodes_committed = req_int(body, "episodes_committed", minimum=1, maximum=40)
    expected_applicant_version = req_int(body, "expected_applicant_version")
    press_count = opt_int(body, "press_appearance_obligation_count", default=0, minimum=0, maximum=6)
    reunion_obligation = opt_bool(body, "reunion_obligation", default=False)
    supersedes_agreement_id = opt_string(body, "supersedes_agreement_id")

    # rung 9 — optimistic concurrency on the applicant
    if expected_applicant_version != applicant["version"]:
        raise ApiError("ERR_STALE_APPLICANT_VERSION")
    # rung 11
    if production["casting_posture"] == "FROZEN":
        raise ApiError("ERR_CASTING_FROZEN")
    # rung 35
    for other in services.agreements_of_applicant(applicant["id"]):
        if other["status"] not in services.LIVE_AGREEMENT:
            continue
        if supersedes_agreement_id is not None and other["id"] == supersedes_agreement_id:
            continue
        raise ApiError("ERR_DUPLICATE_AGREEMENT")
    # rung 36
    if supersedes_agreement_id is not None:
        if supersede_target is None:
            supersede_target = services.get_agreement(supersedes_agreement_id)
        if (
            supersede_target["applicant_id"] != applicant["id"]
            or supersede_target["status"] not in services.NEGOTIABLE_AGREEMENT
        ):
            raise ApiError("ERR_SUPERSEDE_TARGET_INVALID")

    record = store.new_record(
        "agreement",
        {
            "applicant_id": applicant["id"],
            "production_id": production["id"],
            "supersedes_agreement_id": supersedes_agreement_id,
            "status": "DRAFTED",
            "round_number": 0,
            "exclusivity_window_days": exclusivity_window_days,
            "confidentiality_tier": confidentiality_tier,
            "depiction_rights_scope": depiction_rights_scope,
            "stipend_structure": stipend_structure,
            "base_stipend_cents": base_stipend_cents,
            "episodes_committed": episodes_committed,
            "press_appearance_obligation_count": press_count,
            "reunion_obligation": reunion_obligation,
            "provisional_stipend_cents": 0,
            "total_stipend_commitment_cents": 0,
            "last_production_proposer_user_id": None,
            "executed_by_user_id": None,
            "executed_at": None,
            "welfare_hold": False,
            "void_reason": None,
        },
    )
    store.agreements[record["id"]] = record

    if supersede_target is not None:
        services.void_agreement(supersede_target, "SUPERSEDED")

    touch(applicant)
    return object_response(serialize(record), 201)


@bp.get("/casting/participant-agreements")
def list_agreements():
    authenticate(OPERATOR_ROLES)
    limit, offset = pagination()
    records = store.by_seq(list(store.agreements.values()))
    production_id = filter_arg("production_id")
    if production_id is not None:
        records = [r for r in records if r["production_id"] == production_id]
    applicant_id = filter_arg("applicant_id")
    if applicant_id is not None:
        records = [r for r in records if r["applicant_id"] == applicant_id]
    supersedes = filter_arg("supersedes_agreement_id")
    if supersedes is not None:
        records = [r for r in records if r["supersedes_agreement_id"] == supersedes]
    status = filter_arg("status")
    if status is not None:
        records = [r for r in records if r["status"] == status]
    page = paginate(records, limit, offset)
    return list_response(serialize_all(page), limit, offset, len(records))


@bp.get("/casting/participant-agreements/<agreement_id>")
def read_agreement(agreement_id):
    user_id, role = authenticate(ALL_ROLES)
    agreement = services.get_agreement(agreement_id)
    require_owner(role, user_id, agreement["applicant_id"])
    return object_response(serialize(agreement))


# ------------------------------------------------------------------------ send
@bp.post("/casting/participant-agreements/<agreement_id>/send")
def send_agreement(agreement_id):
    authenticate(("BusinessAffairs",))
    agreement = services.get_agreement(agreement_id)
    production = services.get_production(agreement["production_id"])
    applicant = services.get_applicant(agreement["applicant_id"])

    # rung 11
    if production["casting_posture"] == "FROZEN":
        raise ApiError("ERR_CASTING_FROZEN")
    # rung 13
    if agreement["status"] not in ("DRAFTED", "REVISED"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    # rung 14
    if agreement["welfare_hold"]:
        raise ApiError("ERR_WELFARE_HOLD_ACTIVE")
    # rung 21 / 22
    if applicant["screening_status"] != "CLEARED":
        raise ApiError("ERR_SCREENING_INCOMPLETE")
    if applicant["medical_status"] != "CLEARED":
        raise ApiError("ERR_MEDICAL_CLEARANCE_MISSING")
    # rung 23
    if applicant["psych_eval_required"] and not services.has_valid_psych_eval(applicant):
        raise ApiError("ERR_PSYCH_EVAL_REQUIRED")
    # rung 24
    if applicant["enhanced_support_required"]:
        photography_start = parse_iso(production["photography_start_utc"])
        photography_end = parse_iso(production["photography_end_utc"])
        covered = False
        for protocol in services.protocols_of_production(production["id"]):
            if protocol["status"] != "ACTIVE" or protocol["kind"] != "ONSET_PSYCH_SUPPORT":
                continue
            if (
                parse_iso(protocol["coverage_start_utc"]) <= photography_start
                and parse_iso(protocol["coverage_end_utc"]) >= photography_end
            ):
                covered = True
                break
        if not covered:
            raise ApiError("ERR_ENHANCED_SUPPORT_MISSING")
    # rung 25 / 26
    if applicant["is_minor"]:
        complete = services.complete_packets_of(applicant["id"])
        if not complete:
            raise ApiError("ERR_MINOR_PROTECTION_INCOMPLETE")
        today = clock.today()
        if not any(parse_date(p["permit_expires_on"]) > today for p in complete):
            raise ApiError("ERR_WORK_PERMIT_EXPIRED")
    # rung 44
    provisional = calc.agreement_stipend_commitment(agreement, production, "PROVISIONAL")
    if production["stipend_committed_cents"] + provisional > production["stipend_pool_cents"]:
        raise ApiError("ERR_STIPEND_POOL_EXCEEDED")

    agreement["provisional_stipend_cents"] = provisional
    agreement["status"] = "SENT"
    touch(agreement)
    return object_response(serialize(agreement))


# --------------------------------------------------------------- counter / revise
@bp.post("/casting/participant-agreements/<agreement_id>/counter-offer")
def counter_offer(agreement_id):
    user_id, role = authenticate(("Applicant",))
    agreement = services.get_agreement(agreement_id)
    require_owner(role, user_id, agreement["applicant_id"])
    body = json_body()
    requested_base = req_int(body, "requested_base_stipend_cents", minimum=0)
    requested_days = req_int(body, "requested_exclusivity_window_days", minimum=0, maximum=730)
    requested_scope = req_enum(body, "requested_depiction_rights_scope", DEPICTION_SCOPES)
    expected_agreement_version = req_int(body, "expected_agreement_version")

    # rung 10
    if expected_agreement_version != agreement["version"]:
        raise ApiError("ERR_STALE_AGREEMENT_VERSION")
    # rung 13
    if agreement["status"] != "SENT":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    # rung 14
    if agreement["welfare_hold"]:
        raise ApiError("ERR_WELFARE_HOLD_ACTIVE")

    _append_round(
        agreement,
        proposed_by="PARTICIPANT",
        disposition="COUNTERED",
        proposer_user_id=user_id,
        base_stipend_cents=requested_base,
        exclusivity_window_days=requested_days,
        depiction_rights_scope=requested_scope,
    )
    agreement["status"] = "COUNTERED"
    touch(agreement)
    return object_response(serialize(agreement))


@bp.post("/casting/participant-agreements/<agreement_id>/revise")
def revise_agreement(agreement_id):
    user_id, _role = authenticate(("BusinessAffairs",))
    agreement = services.get_agreement(agreement_id)
    body = json_body()
    base_stipend_cents = req_int(body, "base_stipend_cents", minimum=0)
    exclusivity_window_days = req_int(body, "exclusivity_window_days", minimum=0, maximum=730)
    depiction_rights_scope = req_enum(body, "depiction_rights_scope", DEPICTION_SCOPES)
    episodes_committed = opt_int(body, "episodes_committed", minimum=1, maximum=40)
    press_count = opt_int(body, "press_appearance_obligation_count", minimum=0, maximum=6)
    reunion_obligation = opt_bool(body, "reunion_obligation")

    # rung 13
    if agreement["status"] != "COUNTERED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    # rung 14
    if agreement["welfare_hold"]:
        raise ApiError("ERR_WELFARE_HOLD_ACTIVE")

    agreement["base_stipend_cents"] = base_stipend_cents
    agreement["exclusivity_window_days"] = exclusivity_window_days
    agreement["depiction_rights_scope"] = depiction_rights_scope
    if episodes_committed is not None:
        agreement["episodes_committed"] = episodes_committed
    if press_count is not None:
        agreement["press_appearance_obligation_count"] = press_count
    if reunion_obligation is not None:
        agreement["reunion_obligation"] = reunion_obligation

    _append_round(
        agreement,
        proposed_by="PRODUCTION",
        disposition="REVISED",
        proposer_user_id=user_id,
        base_stipend_cents=base_stipend_cents,
        exclusivity_window_days=exclusivity_window_days,
        depiction_rights_scope=depiction_rights_scope,
    )
    agreement["last_production_proposer_user_id"] = user_id
    agreement["status"] = "REVISED"
    touch(agreement)
    return object_response(serialize(agreement))


def _append_round(
    agreement,
    proposed_by,
    disposition,
    proposer_user_id,
    base_stipend_cents,
    exclusivity_window_days,
    depiction_rights_scope,
):
    round_number = agreement["round_number"] + 1
    record = store.new_record(
        "negotiation_round",
        {
            "agreement_id": agreement["id"],
            "round_number": round_number,
            "proposed_by": proposed_by,
            "proposer_user_id": proposer_user_id,
            "requested_base_stipend_cents": base_stipend_cents,
            "requested_exclusivity_window_days": exclusivity_window_days,
            "requested_depiction_rights_scope": depiction_rights_scope,
            "disposition": disposition,
            "recorded_at": clock.now_iso(),
        },
        versioned=False,
    )
    store.negotiation_rounds[record["id"]] = record
    agreement["round_number"] = round_number
    return record


# --------------------------------------------------------------- execute / void
@bp.post("/casting/participant-agreements/<agreement_id>/execute")
def execute_agreement(agreement_id):
    user_id, _role = authenticate(("BusinessAffairs",))
    agreement = services.get_agreement(agreement_id)
    production = services.get_production(agreement["production_id"])
    applicant = services.get_applicant(agreement["applicant_id"])

    # rung 11
    if production["casting_posture"] == "FROZEN":
        raise ApiError("ERR_CASTING_FROZEN")
    # rung 13
    if agreement["status"] != "SENT":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    # rung 14
    if agreement["welfare_hold"]:
        raise ApiError("ERR_WELFARE_HOLD_ACTIVE")
    # rung 20 — four-eyes execution
    proposer = agreement["last_production_proposer_user_id"]
    if proposer is not None and proposer == user_id:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    # rung 21 / 22
    if applicant["screening_status"] != "CLEARED":
        raise ApiError("ERR_SCREENING_INCOMPLETE")
    if applicant["medical_status"] != "CLEARED":
        raise ApiError("ERR_MEDICAL_CLEARANCE_MISSING")
    # rung 37
    if applicant["is_minor"] and (
        production["minor_participant_count"] + 1 > production["minor_participant_cap"]
    ):
        raise ApiError("ERR_MINOR_CAP_EXCEEDED")
    # rung 44
    final_total = calc.agreement_stipend_commitment(agreement, production, "FINAL")
    if production["stipend_committed_cents"] + final_total > production["stipend_pool_cents"]:
        raise ApiError("ERR_STIPEND_POOL_EXCEEDED")

    agreement["total_stipend_commitment_cents"] = final_total
    agreement["status"] = "EXECUTED"
    agreement["executed_by_user_id"] = user_id
    agreement["executed_at"] = clock.now_iso()
    touch(agreement)

    applicant["screening_status"] = "CAST"
    touch(applicant)

    services.recompute_stipend_committed(production)
    services.recompute_minor_participant_count(production)
    touch(production)
    services.recompute_posture(production)

    services.create_post_obligations(agreement, production)
    return object_response(serialize(agreement))


@bp.post("/casting/participant-agreements/<agreement_id>/void")
def void_agreement_endpoint(agreement_id):
    authenticate(("BusinessAffairs",))
    agreement = services.get_agreement(agreement_id)
    body = json_body()
    void_reason = req_enum(body, "void_reason", VOID_REASONS)

    # rung 13
    if agreement["status"] == "VOIDED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    production = services.void_agreement(agreement, void_reason)
    if production is not None:
        services.recompute_posture(production)
    return object_response(serialize(agreement))


# ------------------------------------------------------------ negotiation rounds
@bp.get("/casting/participant-agreements/<agreement_id>/negotiation-rounds")
def list_negotiation_rounds(agreement_id):
    authenticate(ALL_ROLES)
    agreement = services.get_agreement(agreement_id)
    limit, offset = pagination()
    records = services.rounds_of_agreement(agreement["id"])
    proposed_by = filter_arg("proposed_by")
    if proposed_by is not None:
        records = [r for r in records if r["proposed_by"] == proposed_by]
    page = paginate(records, limit, offset)
    return list_response(serialize_all(page), limit, offset, len(records))


# --------------------------------------------------------------- post obligations
@bp.get("/casting/participant-agreements/<agreement_id>/post-obligations")
def list_post_obligations(agreement_id):
    authenticate(
        ("ProductionAdmin", "CastingDirector", "BusinessAffairs", "WelfareOfficer", "Applicant")
    )
    agreement = services.get_agreement(agreement_id)
    limit, offset = pagination()
    records = services.obligations_of_agreement(agreement["id"])
    status = filter_arg("status")
    if status is not None:
        records = [r for r in records if r["status"] == status]
    kind = filter_arg("kind")
    if kind is not None:
        records = [r for r in records if r["kind"] == kind]
    page = paginate(records, limit, offset)
    return list_response(serialize_all(page), limit, offset, len(records))


@bp.post("/casting/post-obligations/<obligation_id>/fulfill")
def fulfill_post_obligation(obligation_id):
    authenticate(("BusinessAffairs",))
    obligation = services.get_post_obligation(obligation_id)
    agreement = store.agreements.get(obligation["agreement_id"])

    # rung 13
    if obligation["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    if agreement is None or agreement["status"] != "EXECUTED":
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION",
            "The owning agreement is no longer EXECUTED.",
        )

    obligation["status"] = "FULFILLED"
    obligation["fulfilled_at"] = clock.now_iso()
    touch(obligation)
    return object_response(serialize(obligation))


# -------------------------------------------------------------------- complaints
@bp.post("/casting/participant-agreements/<agreement_id>/complaints")
def file_complaint(agreement_id):
    user_id, role = authenticate(("Applicant",))
    agreement = services.get_agreement(agreement_id)
    require_owner(role, user_id, agreement["applicant_id"])
    body = json_body()
    category = req_enum(body, "category", COMPLAINT_CATEGORIES)
    severity = req_int(body, "severity", minimum=1, maximum=5)
    narrative = req_string(body, "narrative", min_len=1, max_len=2000)

    # rung 18
    if agreement["status"] not in ("EXECUTED", "VOIDED"):
        raise ApiError("ERR_COMPLAINT_TARGET_INVALID")

    record = store.new_record(
        "complaint",
        {
            "agreement_id": agreement["id"],
            "category": category,
            "severity": severity,
            "narrative": narrative,
            "status": "OPEN",
            "duty_of_care_breach": False,
            "aftercare_sessions_authorized": 0,
            "triaged_by_user_id": None,
            "routed_by_user_id": None,
            "resolution_note": None,
        },
    )
    store.complaints[record["id"]] = record
    return object_response(serialize(record), 201)


@bp.get("/casting/participant-agreements/<agreement_id>/complaints")
def list_complaints(agreement_id):
    authenticate(("ProductionAdmin", "BusinessAffairs", "WelfareOfficer", "Applicant"))
    agreement = services.get_agreement(agreement_id)
    limit, offset = pagination()
    records = services.complaints_of_agreement(agreement["id"])
    status = filter_arg("status")
    if status is not None:
        records = [r for r in records if r["status"] == status]
    category = filter_arg("category")
    if category is not None:
        records = [r for r in records if r["category"] == category]
    page = paginate(records, limit, offset)
    return list_response(serialize_all(page), limit, offset, len(records))


@bp.post("/casting/complaints/<complaint_id>/triage")
def triage_complaint(complaint_id):
    user_id, _role = authenticate(("WelfareOfficer",))
    complaint = services.get_complaint(complaint_id)
    if complaint["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    complaint["status"] = "TRIAGED"
    complaint["triaged_by_user_id"] = user_id
    touch(complaint)
    return object_response(serialize(complaint))


@bp.post("/casting/complaints/<complaint_id>/route")
def route_complaint(complaint_id):
    user_id, _role = authenticate(("WelfareOfficer",))
    complaint = services.get_complaint(complaint_id)
    body = json_body()
    route = req_enum(body, "route", ROUTES)

    if complaint["status"] != "TRIAGED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    agreement = store.agreements.get(complaint["agreement_id"])
    production = services.production_of_agreement(agreement) if agreement else None
    tier = production["duty_of_care_tier"] if production else "STANDARD"

    # sessions read the severity and the tier as of the START of this transition
    sessions = calc.aftercare_sessions(complaint["severity"], tier)
    complaint["aftercare_sessions_authorized"] = sessions
    complaint["routed_by_user_id"] = user_id

    if route == "AFTERCARE":
        complaint["status"] = "AFTERCARE_ACTIVE"
        touch(complaint)
        return object_response(serialize(complaint))

    complaint["status"] = "ESCALATED"
    breach = complaint["category"] in ("WELFARE", "HARASSMENT") and complaint["severity"] >= 4
    complaint["duty_of_care_breach"] = breach
    touch(complaint)

    if breach and production is not None:
        services.recompute_welfare_incident_count(production)
        production["duty_of_care_tier"] = calc.escalate_tier(production["duty_of_care_tier"])
        services.recompute_welfare_committed(production)
        touch(production)
        services.recompute_posture(production)

    return object_response(serialize(complaint))


@bp.post("/casting/complaints/<complaint_id>/resolve")
def resolve_complaint(complaint_id):
    authenticate(("WelfareOfficer",))
    complaint = services.get_complaint(complaint_id)
    body = json_body()
    resolution_note = req_string(body, "resolution_note")
    if complaint["status"] not in ("AFTERCARE_ACTIVE", "ESCALATED"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    complaint["status"] = "RESOLVED"
    complaint["resolution_note"] = resolution_note
    touch(complaint)
    return object_response(serialize(complaint))
