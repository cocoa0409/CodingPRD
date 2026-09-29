"""Certification submissions, reviews and credential issuance (PRD 3.4, 3.8)."""

from flask import Blueprint

import calc
import cascade
import common as C
import enums as E
import middleware as M
import queries as Q
import shape as S
from db import new_row, now, ordered, set_fields, store
from errors import ApiError
from response import list_response, object_response
from serial import public, public_list

bp = Blueprint("submissions", __name__)

SUBMIT_ORIGINS = ("DRAFT", "RETURNED_FOR_INFO")
WITHDRAW_ORIGINS = ("DRAFT", "SUBMITTED", "IN_REVIEW", "RETURNED_FOR_INFO")


def _baseline_declaration_ok(spec, secure_boot, capability):
    if spec["security_baseline_level"] in ("SB2", "SB3"):
        return bool(secure_boot) and capability == "OTA_SIGNED"
    return True


@bp.post("/submissions")
def create_submission():
    user_id, _ = M.auth([M.MEMBER])
    body = S.body_obj()
    # rung 3 -- the payload member_id must be the acting member
    raw_member_id = body.get("member_id")
    if isinstance(raw_member_id, str):
        M.own(user_id, raw_member_id)
    # rung 5 -- body foreign keys in input-declaration order
    member = C.body_fk("member", body, "member_id")
    spec = C.body_fk("specification", body, "specification_id")
    # rung 6 -- shape and ranges
    S.req_str(body, "member_id")
    S.req_str(body, "specification_id")
    device_model = S.req_str(body, "device_model", 1, 80)
    device_type = S.req_str(body, "device_type")
    declared_codes = S.req_str_array(body, "declared_feature_codes", allow_empty=True)
    declared_secure_boot = S.req_bool(body, "declared_secure_boot")
    capability = S.req_str(body, "declared_firmware_update_capability")
    fingerprint = S.req_str(body, "attestation_key_fingerprint", 1, 64)
    review_track = S.opt_str(body, "review_track") or "STANDARD"
    # rung 7 -- enum membership
    S.check_enum(device_type, E.DEVICE_TYPES, "device_type")
    S.check_enum(capability, E.FIRMWARE_CAPABILITIES, "declared_firmware_update_capability")
    S.check_enum(review_track, E.REVIEW_TRACKS, "review_track")
    # rung 33 -- declared feature codes must resolve inside the pinned device class
    known = {fs["feature_code"] for fs in Q.feature_sets_for(spec["id"], device_type)}
    for code in declared_codes:
        if code not in known:
            raise ApiError("ERR_UNKNOWN_FEATURE_CODE",
                           "feature_code %s is unknown for this specification and device class" % code)

    fee = calc.certification_fee_cents(
        device_type, len(declared_codes), spec["security_baseline_level"],
        member["tier"], review_track,
    )
    submission = new_row(
        member_id=member["id"],
        specification_id=spec["id"],
        device_model=device_model,
        device_type=device_type,
        declared_feature_codes=list(declared_codes),
        review_track=review_track,
        declared_secure_boot=declared_secure_boot,
        declared_firmware_update_capability=capability,
        attestation_key_fingerprint=fingerprint,
        state="DRAFT",
        conformance_review_state="PENDING",
        security_review_state="PENDING",
        dac_state="NOT_ISSUED",
        dac_serial=None,
        secure_boot_verified=None,
        verified_firmware_update_capability=None,
        conformance_reviewer_user_id=None,
        security_reviewer_user_id=None,
        revision_round=0,
        certification_fee_cents=fee,
        fee_escrowed_cents=0,
        provisional_readiness_score=None,
        final_readiness_score=None,
        plugfest_credit_count=0,
        submitted_at=None,
        review_started_at=None,
        certified_at=None,
    )
    store.submissions[submission["id"]] = submission
    return object_response(public(submission), 201)


@bp.get("/submissions/<submission_id>")
def get_submission(submission_id):
    M.auth(M.NON_PUBLIC_READ)
    return object_response(public(C.must("submission", submission_id)), 200)


@bp.get("/submissions")
def list_submissions():
    M.auth(M.NON_PUBLIC_READ)
    limit, offset = S.paging()
    member_id = S.q_str("member_id")
    specification_id = S.q_str("specification_id")
    state = S.q_str("state")
    dac_state = S.q_str("dac_state")
    device_type = S.q_enum("device_type", E.DEVICE_TYPES)
    rows = ordered(store.submissions.values())
    if member_id is not None:
        rows = [r for r in rows if r["member_id"] == member_id]
    if specification_id is not None:
        rows = [r for r in rows if r["specification_id"] == specification_id]
    if state is not None:
        rows = [r for r in rows if r["state"] == state]
    if dac_state is not None:
        rows = [r for r in rows if r["dac_state"] == dac_state]
    if device_type is not None:
        rows = [r for r in rows if r["device_type"] == device_type]
    page, total = C.paginate(rows, limit, offset)
    return list_response(public_list(page), limit, offset, total)


@bp.post("/submissions/<submission_id>/submit")
def submit_submission(submission_id):
    user_id, _ = M.auth([M.MEMBER])
    submission = C.must("submission", submission_id)
    M.own(user_id, submission["member_id"])
    spec = store.specifications[submission["specification_id"]]
    member = store.members[submission["member_id"]]
    # rung 13
    if spec["status"] != "RATIFIED":
        raise ApiError("ERR_INVALID_SPECIFICATION_STATE",
                       "submitting requires a RATIFIED specification")
    # rung 16
    if submission["state"] not in SUBMIT_ORIGINS:
        raise ApiError("ERR_INVALID_SUBMISSION_STATE",
                       "submit is only available from DRAFT or RETURNED_FOR_INFO")
    # rung 25
    if not member["good_standing"]:
        raise ApiError("ERR_MEMBER_NOT_IN_GOOD_STANDING", "the member is not in good standing")
    # rung 26
    if member["ip_scope_specification_id"] != submission["specification_id"]:
        raise ApiError("ERR_IP_COMMITMENT_REQUIRED",
                       "the member's IP commitment does not cover this specification")
    # rung 27
    if not _baseline_declaration_ok(spec, submission["declared_secure_boot"],
                                    submission["declared_firmware_update_capability"]):
        raise ApiError("ERR_SECURITY_BASELINE_NOT_MET",
                       "the security self-declaration does not meet the baseline")

    first_submit = submission["state"] == "DRAFT"
    if first_submit:
        # rung 50
        if member["credit_balance_cents"] < submission["certification_fee_cents"]:
            raise ApiError("ERR_INSUFFICIENT_CREDIT", "insufficient programme credit")
        set_fields(submission, state="SUBMITTED", submitted_at=now(),
                   fee_escrowed_cents=submission["certification_fee_cents"])
        cascade.recompute_member(member)
    else:
        set_fields(submission, state="SUBMITTED", submitted_at=now(),
                   conformance_review_state="PENDING")
    return object_response(public(submission), 200)


@bp.post("/submissions/<submission_id>/start-review")
def start_review(submission_id):
    M.auth([M.CONFORMANCE_REVIEWER])
    submission = C.must("submission", submission_id)
    if submission["state"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_SUBMISSION_STATE", "a review starts from SUBMITTED")
    set_fields(submission, state="IN_REVIEW", review_started_at=now())
    return object_response(public(submission), 200)


@bp.post("/submissions/<submission_id>/return-for-info")
def return_for_info(submission_id):
    user_id, _ = M.auth([M.CONFORMANCE_REVIEWER])
    submission = C.must("submission", submission_id)
    body = S.body_obj()
    S.req_str(body, "reason", 1, 500)
    # rung 16
    if submission["state"] != "IN_REVIEW":
        raise ApiError("ERR_INVALID_SUBMISSION_STATE", "a return requires IN_REVIEW")
    # rung 17
    if submission["conformance_review_state"] != "PENDING":
        raise ApiError("ERR_REVIEW_ALREADY_DECIDED", "the conformance verdict is already recorded")
    # rung 46
    if submission["revision_round"] >= E.MAX_REVISION_ROUNDS:
        raise ApiError("ERR_REVISION_LIMIT_EXCEEDED", "the revision limit is exhausted")
    set_fields(
        submission,
        state="RETURNED_FOR_INFO",
        conformance_review_state="RETURNED",
        revision_round=submission["revision_round"] + 1,
        conformance_reviewer_user_id=user_id,
    )
    return object_response(public(submission), 200)


def _resolve_primary_axis(submission, fields):
    """PRD 3.8 compound bubble-up, evaluated at the end of either decision."""
    conformance = fields.get("conformance_review_state", submission["conformance_review_state"])
    security = fields.get("security_review_state", submission["security_review_state"])
    if submission["state"] != "IN_REVIEW":
        return False
    if conformance == "APPROVED" and security == "APPROVED":
        fields["state"] = "REVIEW_COMPLETE"
        return False
    if conformance == "REJECTED" or security == "REJECTED":
        fields["state"] = "REJECTED"
        fields["fee_escrowed_cents"] = 0
        return True
    return False


@bp.post("/submissions/<submission_id>/conformance-decision")
def conformance_decision(submission_id):
    user_id, _ = M.auth([M.CONFORMANCE_REVIEWER])
    submission = C.must("submission", submission_id)
    body = S.body_obj()
    # rung 6 / 7
    decision = S.req_str(body, "decision")
    S.opt_str(body, "note", 0, 1000)
    S.check_enum(decision, E.REVIEW_DECISIONS, "decision")
    spec = store.specifications[submission["specification_id"]]
    # rung 16
    if submission["state"] != "IN_REVIEW":
        raise ApiError("ERR_INVALID_SUBMISSION_STATE", "a conformance decision requires IN_REVIEW")
    # rung 17
    if submission["conformance_review_state"] != "PENDING":
        raise ApiError("ERR_REVIEW_ALREADY_DECIDED", "the conformance verdict is already recorded")
    plan = Q.live_plan(submission["id"])
    # rung 43 -- rung 18 does not reach the conformance decision, so a plan that
    # is not COMPLETE is a coverage failure here, not a plan-state failure.
    if plan is None or plan["state"] != "COMPLETE" or not cascade.mandatory_coverage_complete(plan):
        raise ApiError("ERR_MANDATORY_COVERAGE_INCOMPLETE",
                       "mandatory coverage is incomplete for this submission")
    # both decisions compute the FINAL score before any threshold is evaluated
    final_score = calc.readiness(submission, "FINAL")["score"]
    if decision == "APPROVE":
        # rung 44
        if submission["plugfest_credit_count"] < spec["min_plugfest_credits"]:
            raise ApiError("ERR_INSUFFICIENT_PLUGFEST_CREDITS", "not enough plugfest credits")
        # rung 45
        if final_score < E.FINAL_APPROVAL_THRESHOLD:
            raise ApiError("ERR_READINESS_BELOW_THRESHOLD",
                           "the final readiness score is below the approval threshold")

    fields = {
        "final_readiness_score": final_score,
        "conformance_review_state": "APPROVED" if decision == "APPROVE" else "REJECTED",
        "conformance_reviewer_user_id": user_id,
    }
    released = _resolve_primary_axis(submission, fields)
    set_fields(submission, **fields)
    if released:
        cascade.recompute_member(store.members[submission["member_id"]])
    return object_response(public(submission), 200)


@bp.post("/submissions/<submission_id>/security-decision")
def security_decision(submission_id):
    user_id, _ = M.auth([M.SECURITY_REVIEWER])
    submission = C.must("submission", submission_id)
    body = S.body_obj()
    # rung 6 / 7
    decision = S.req_str(body, "decision")
    secure_boot_verified = S.req_bool(body, "secure_boot_verified")
    capability = S.req_str(body, "verified_firmware_update_capability")
    S.check_enum(decision, E.REVIEW_DECISIONS, "decision")
    S.check_enum(capability, E.FIRMWARE_CAPABILITIES, "verified_firmware_update_capability")
    spec = store.specifications[submission["specification_id"]]
    # rung 16
    if submission["state"] != "IN_REVIEW":
        raise ApiError("ERR_INVALID_SUBMISSION_STATE", "a security decision requires IN_REVIEW")
    # rung 17
    if submission["security_review_state"] != "PENDING":
        raise ApiError("ERR_REVIEW_ALREADY_DECIDED", "the security verdict is already recorded")
    # rung 24 -- segregation of duties against the conformance reviewer
    if (submission["conformance_reviewer_user_id"] is not None
            and submission["conformance_reviewer_user_id"] == user_id):
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "the security reviewer must differ from the conformance reviewer")
    if decision == "APPROVE":
        # rung 27
        if spec["security_baseline_level"] in ("SB2", "SB3") and capability != "OTA_SIGNED":
            raise ApiError("ERR_SECURITY_BASELINE_NOT_MET",
                           "this baseline requires OTA_SIGNED firmware update capability")
        # rung 28
        if not secure_boot_verified:
            raise ApiError("ERR_SECURE_BOOT_NOT_VERIFIED", "secure boot was not verified")

    fields = {
        "secure_boot_verified": secure_boot_verified,
        "verified_firmware_update_capability": capability,
        "security_review_state": "APPROVED" if decision == "APPROVE" else "REJECTED",
        "security_reviewer_user_id": user_id,
    }
    released = _resolve_primary_axis(submission, fields)
    set_fields(submission, **fields)
    if released:
        cascade.recompute_member(store.members[submission["member_id"]])
    return object_response(public(submission), 200)


@bp.post("/submissions/<submission_id>/issue-credential")
def issue_credential(submission_id):
    M.auth([M.PROGRAM_ADMIN])
    submission = C.must("submission", submission_id)
    body = S.body_obj()
    dac_serial = S.req_str(body, "dac_serial", 1, 64)
    # rung 16
    if submission["state"] != "REVIEW_COMPLETE" or submission["dac_state"] != "NOT_ISSUED":
        raise ApiError("ERR_INVALID_SUBMISSION_STATE",
                       "issuance requires REVIEW_COMPLETE and a NOT_ISSUED credential")
    if submission["fee_escrowed_cents"] != submission["certification_fee_cents"]:
        raise ApiError("ERR_INVALID_SUBMISSION_STATE", "the certification fee is not escrowed")
    # rung 28
    if (not submission["secure_boot_verified"]
            or submission["verified_firmware_update_capability"] == "NONE"
            or submission["verified_firmware_update_capability"] is None):
        raise ApiError("ERR_SECURE_BOOT_NOT_VERIFIED",
                       "the recorded attestation findings do not permit issuance")
    # rung 35
    for row in store.submissions.values():
        if row["dac_serial"] == dac_serial:
            raise ApiError("ERR_DUPLICATE_DAC_SERIAL", "dac_serial is already held")

    member = store.members[submission["member_id"]]
    consumed = submission["fee_escrowed_cents"]
    set_fields(submission, state="CERTIFIED", certified_at=now(), dac_state="ISSUED",
               dac_serial=dac_serial, fee_escrowed_cents=0)
    set_fields(member, credits_consumed_cents=member["credits_consumed_cents"] + consumed)
    cascade.recompute_member(member)
    return object_response(public(submission), 200)


@bp.post("/submissions/<submission_id>/withdraw")
def withdraw_submission(submission_id):
    user_id, _ = M.auth([M.MEMBER])
    submission = C.must("submission", submission_id)
    M.own(user_id, submission["member_id"])
    if submission["state"] not in WITHDRAW_ORIGINS:
        raise ApiError("ERR_INVALID_SUBMISSION_STATE",
                       "withdrawal is not available from %s" % submission["state"])
    set_fields(submission, state="WITHDRAWN", fee_escrowed_cents=0)
    cascade.recompute_member(store.members[submission["member_id"]])
    plan = Q.live_plan(submission["id"])
    if plan is not None:
        cascade.void_plan(plan, "SUPERSEDED_BY_NEW_PLAN")
    return object_response(public(submission), 200)


@bp.get("/submissions/<submission_id>/readiness")
def read_readiness(submission_id):
    M.auth([M.PROGRAM_ADMIN, M.MEMBER, M.CONFORMANCE_REVIEWER, M.SECURITY_REVIEWER])
    submission = C.must("submission", submission_id)
    variant = S.q_enum("variant", E.READINESS_VARIANTS) or "PROVISIONAL"
    result = calc.readiness(submission, variant)
    result["score"] = str(result["score"])
    return object_response(result, 200)
