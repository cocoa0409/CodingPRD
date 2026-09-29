"""Reference check verification and background screening (PRD 3.3)."""

from flask import Blueprint, request

import db
from db import (
    MIN_CHAIN_MONTHS_VETTING_GATE,
    MIN_VERIFIED_REFERENCES,
    REFERENCE_STATUSES,
    RELATIONSHIP_TYPES,
    TERMINAL_BACKGROUND,
    TERMINAL_REFERENCE,
    serialize,
    store,
    touch,
)
from errors import fail
from middleware import (
    AGENCY_PRINCIPAL,
    COMPLIANCE_OFFICER,
    PLACEMENT_CONSULTANT,
    VETTING_SPECIALIST,
    authenticate,
)
from response import list_response, object_response
from services import domain
from validation import (
    apply_filters,
    body_of,
    check_enum,
    list_params,
    require_present,
    require_string,
)

bp = Blueprint("vetting", __name__)

READ_ROLES = {AGENCY_PRINCIPAL, PLACEMENT_CONSULTANT, VETTING_SPECIALIST, COMPLIANCE_OFFICER}


# ---------------------------------------------------------------------------
# Reference checks
# ---------------------------------------------------------------------------
@bp.get("/reference-checks/<reference_id>")
def get_reference_check(reference_id):
    authenticate(READ_ROLES)
    row = domain.resolve("reference_checks", reference_id)
    return object_response(serialize(row))


@bp.get("/reference-checks")
def list_reference_checks():
    authenticate(READ_ROLES)
    limit, offset, filters = list_params(
        request,
        enum_filters={"status": REFERENCE_STATUSES, "relationship_type": RELATIONSHIP_TYPES},
        plain_filters=("candidate_id", "prior_reference_id"),
    )
    rows = apply_filters(list(store.reference_checks.values()), filters)
    data, total = domain.page(rows, limit, offset)
    return list_response(data, limit, offset, total)


@bp.post("/reference-checks/<reference_id>/verify")
def verify_reference_check(reference_id):
    user_id, _role = authenticate({VETTING_SPECIALIST})
    body = body_of(request)

    require_present(body, "outcome")
    verification_note = require_string(body, "verification_note", 0, 100000, required=False)
    outcome = check_enum(body, "outcome", ["VERIFIED", "UNREACHABLE", "DISPUTED"])

    reference = domain.resolve("reference_checks", reference_id)
    domain.guard_terminal(reference["status"], TERMINAL_REFERENCE)

    # Maker and checker must differ (PRD 3.3).
    if user_id == reference["created_by_user_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES")

    reference["status"] = outcome
    reference["verified_by_user_id"] = user_id
    if verification_note is not None:
        reference["verification_note"] = verification_note
    touch(reference)

    candidate = store.candidates.get(reference["candidate_id"])
    if candidate is not None:
        figures = domain.recompute_candidate(candidate)
        if (
            outcome == "VERIFIED"
            and candidate["vetting_status"] == "SCREENING"
            and figures["verified_reference_count"] >= MIN_VERIFIED_REFERENCES
            and figures["longest_contiguous_months"] >= MIN_CHAIN_MONTHS_VETTING_GATE
        ):
            candidate["vetting_status"] = "REFERENCES_VERIFIED"
            touch(candidate)

    return object_response(serialize(reference))


# ---------------------------------------------------------------------------
# Background verifications
# ---------------------------------------------------------------------------
@bp.get("/background-verifications/<verification_id>")
def get_background_verification(verification_id):
    authenticate(READ_ROLES)
    row = domain.resolve("background_verifications", verification_id)
    return object_response(serialize(row))


@bp.post("/background-verifications/<verification_id>/record-result")
def record_background_result(verification_id):
    user_id, _role = authenticate({VETTING_SPECIALIST})
    body = body_of(request)

    require_present(body, "result")
    findings_note = require_string(body, "findings_note", 0, 100000, required=False)
    result = check_enum(body, "result", ["CLEARED", "FLAGGED", "INCONCLUSIVE"])

    verification = domain.resolve("background_verifications", verification_id)
    domain.guard_terminal(verification["status"], TERMINAL_BACKGROUND)
    if verification["status"] not in ("INITIATED", "INCONCLUSIVE"):
        fail("ERR_INVALID_STATE_TRANSITION")

    # rerun_count advances only when a screen that was already INCONCLUSIVE is
    # re-run to another INCONCLUSIVE result.
    if verification["status"] == "INCONCLUSIVE" and result == "INCONCLUSIVE":
        verification["rerun_count"] += 1

    verification["status"] = result
    verification["recorded_by_user_id"] = user_id
    if findings_note is not None:
        verification["findings_note"] = findings_note
    touch(verification)

    candidate = store.candidates.get(verification["candidate_id"])
    if candidate is not None:
        if result == "CLEARED" and candidate["vetting_status"] == "BACKGROUND_PENDING":
            candidate["vetting_status"] = "CLEARED"
            touch(candidate)
        domain.recompute_candidate(candidate)

    return object_response(serialize(verification))


@bp.post("/background-verifications/<verification_id>/adjudicate")
def adjudicate_background(verification_id):
    user_id, _role = authenticate({AGENCY_PRINCIPAL})
    body = body_of(request)

    require_present(body, "disposition", "expected_candidate_version")
    waiver_note = require_string(body, "waiver_note", 0, 100000, required=False)
    disposition = check_enum(body, "disposition", ["PASS", "FAIL"])

    verification = domain.resolve("background_verifications", verification_id)
    candidate = domain.resolve("candidates", verification["candidate_id"])

    # Optimistic concurrency outranks both the state check and terminality.
    if body["expected_candidate_version"] != candidate["version"]:
        fail("ERR_STALE_CANDIDATE_VERSION")

    domain.guard_terminal(verification["status"], TERMINAL_BACKGROUND)
    if verification["status"] != "FLAGGED":
        fail("ERR_BACKGROUND_NOT_FLAGGED")

    verification["adjudicated_by_user_id"] = user_id
    if waiver_note is not None:
        verification["waiver_note"] = waiver_note

    if disposition == "PASS":
        verification["status"] = "ADJUDICATED_PASS"
        touch(verification)
        if candidate["vetting_status"] == "BACKGROUND_PENDING":
            candidate["vetting_status"] = "CLEARED"
            touch(candidate)
        domain.recompute_candidate(candidate)
    else:
        verification["status"] = "ADJUDICATED_FAIL"
        touch(verification)

        # Hop one: the vetting axis is rejected.
        candidate["vetting_status"] = "REJECTED"
        touch(candidate)

        # Hop two: every active trial of the candidate is cancelled.
        affected_requisitions = set()
        for trial in db.sort_rows(domain.children("trial_engagements", "candidate_id", candidate["id"])):
            if trial["status"] in db.ACTIVE_TRIAL_STATUSES:
                domain.cancel_trial(trial, "VETTING_FAILED")
                affected_requisitions.add(trial["requisition_id"])

        # Hop three: emptied TRIALING requisitions fall back to SOURCING.
        for requisition_id in sorted(affected_requisitions):
            requisition = store.requisitions.get(requisition_id)
            if requisition is not None:
                domain.fallback_trialing_to_sourcing(requisition)

        # Hop four: the availability axis is parked at INACTIVE.
        if candidate["availability_status"] == "ON_TRIAL":
            candidate["availability_status"] = "INACTIVE"
            candidate["cooling_off_until"] = None
            touch(candidate)

        domain.recompute_candidate(candidate)

    return object_response(serialize(verification))
