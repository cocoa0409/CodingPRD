"""InsuranceClaim endpoints — PRD §3.6."""
from flask import Blueprint, jsonify, request

from ..auth import require_auth
from ..errors import APIError
from ..helpers import (
    get_json_body,
    get_pagination_params,
    optional_field,
    paginate,
    require_field,
)
from ..responses import list_response, success_response
from ..services.calculations import (
    compute_reimbursed_amount_cents,
    compute_submitted_amount_cents,
    compute_supervision_ratio,
    recompute_authorization_consumption,
    recompute_patient_progress_scores,
)
from ..services.cascades import maybe_auto_exhaust
from ..services.ledger import append_ledger_entry
from ..services.lookups import (
    get_authorization,
    get_claim,
    get_patient,
)
from ..services.serialize import serialize_claim
from ..store import get_lock, get_store, stamp_create, stamp_update


bp = Blueprint("claims", __name__)


VALID_DENIAL_REASONS = {
    "SUPERVISION_RATIO_BREACH",
    "UNITS_OUT_OF_AUTH",
    "MISSING_PROGRESS_NOTE",
    "DUPLICATE_LINE",
}


def _claim_blocks_session(claim_status: str) -> bool:
    """A session can only belong to one claim that is not in {DRAFT, DENIED}.

    Per PRD §3.6: 'no session may already appear in another claim that is
    SUBMITTED, ADJUDICATED, PAID, or APPEALED'.
    """
    return claim_status in ("SUBMITTED", "ADJUDICATED", "PAID", "APPEALED")


@bp.post("/patients/<patient_id>/claims")
@require_auth("ClinicAdmin")
def create_claim(patient_id):
    body = get_json_body()
    with get_lock():
        patient = get_patient(patient_id)
        clinic = get_store().clinics[patient["clinic_id"]]
        store = get_store()

        authorization_id = require_field(body, "authorization_id")
        session_ids = require_field(body, "session_ids")
        if not isinstance(session_ids, list):
            raise APIError("ERR_VALIDATION", "session_ids must be an array")

        auth = get_authorization(authorization_id)
        if auth["patient_id"] != patient_id:
            raise APIError("ERR_VALIDATION",
                           "authorization must belong to the same patient")

        # Validate each session_id exists, COMPLETED, single-auth, not in another claim.
        for sid in session_ids:
            if not isinstance(sid, str):
                raise APIError("ERR_VALIDATION", "every session_id must be a string")
            s = store.sessions.get(sid)
            if s is None:
                raise APIError("ERR_NOT_FOUND", f"session {sid} not found")
            if s["status"] != "COMPLETED":
                raise APIError("ERR_INVALID_STATE",
                               f"session {sid} must be COMPLETED")
            if s["authorization_id"] != authorization_id:
                raise APIError("ERR_SESSION_AUTH_MISMATCH",
                               f"session {sid} references a different authorization")
            for c in store.claims.values():
                if sid in c["session_ids"] and _claim_blocks_session(c["status"]):
                    raise APIError("ERR_SESSION_ALREADY_CLAIMED",
                                   f"session {sid} already on another in-flight claim")

        record = stamp_create(
            {
                "patient_id": patient_id,
                "authorization_id": authorization_id,
                "session_ids": list(session_ids),
                "appeal_round": 0,
                "submitted_amount_cents": 0,
                "reimbursed_amount_cents": 0,
                "denial_reason": None,
                "status": "DRAFT",
            },
            now=clinic["now_ts"],
        )
        store.claims[record["id"]] = record

    body_out, status = success_response(serialize_claim(record), status=201)
    return jsonify(body_out), status


@bp.post("/claims/<claim_id>/submit")
@require_auth("ClinicAdmin")
def submit_claim(claim_id):
    with get_lock():
        claim = get_claim(claim_id)
        if claim["status"] != "DRAFT":
            raise APIError("ERR_INVALID_STATE",
                           f"Cannot submit claim in status {claim['status']}")
        store = get_store()
        auth = get_authorization(claim["authorization_id"])

        # Re-verify session_ids COMPLETED + single-auth + not in another claim.
        for sid in claim["session_ids"]:
            s = store.sessions.get(sid)
            if s is None:
                raise APIError("ERR_NOT_FOUND", f"session {sid} not found")
            if s["status"] != "COMPLETED":
                raise APIError("ERR_SESSION_NOT_COMPLETED",
                               f"session {sid} is not COMPLETED")
            if s["authorization_id"] != claim["authorization_id"]:
                raise APIError("ERR_SESSION_AUTH_MISMATCH",
                               f"session {sid} references a different authorization")
            for c in store.claims.values():
                if c["id"] == claim_id:
                    continue
                if sid in c["session_ids"] and _claim_blocks_session(c["status"]):
                    raise APIError("ERR_SESSION_ALREADY_CLAIMED",
                                   f"session {sid} already on another in-flight claim")

        # sum(billed_units) > 0.
        total_units = 0
        for sid in claim["session_ids"]:
            s = store.sessions[sid]
            total_units += s.get("billed_units") or 0
        if total_units <= 0:
            raise APIError("ERR_EMPTY_CLAIM",
                           "claim must reference sessions whose total billed_units > 0")

        patient = get_patient(claim["patient_id"])
        clinic = store.clinics[patient["clinic_id"]]
        now_ts = clinic["now_ts"]

        # Cascade: each referenced TherapySession COMPLETED → BILLED.
        for sid in claim["session_ids"]:
            s = store.sessions[sid]
            s["status"] = "BILLED"
            stamp_update(s, now=now_ts)

        # Compute submitted amount.
        claim["submitted_amount_cents"] = compute_submitted_amount_cents(claim, auth)
        claim["status"] = "SUBMITTED"
        stamp_update(claim, now=now_ts)

    body_out, status = success_response(serialize_claim(claim))
    return jsonify(body_out), status


@bp.post("/claims/<claim_id>/adjudicate")
@require_auth("PayerAdmin")
def adjudicate_claim(claim_id):
    body = get_json_body()
    denial_reason = optional_field(body, "denial_reason")
    with get_lock():
        claim = get_claim(claim_id)
        if claim["status"] not in ("SUBMITTED", "APPEALED"):
            raise APIError("ERR_INVALID_STATE",
                           f"Cannot adjudicate claim in status {claim['status']}")
        if denial_reason is not None and denial_reason not in VALID_DENIAL_REASONS:
            raise APIError("ERR_VALIDATION",
                           f"denial_reason must be one of {sorted(VALID_DENIAL_REASONS)}")
        patient = get_patient(claim["patient_id"])
        clinic = get_store().clinics[patient["clinic_id"]]
        claim["denial_reason"] = denial_reason
        claim["status"] = "ADJUDICATED"
        stamp_update(claim, now=clinic["now_ts"])

    body_out, status = success_response(serialize_claim(claim))
    return jsonify(body_out), status


@bp.post("/claims/<claim_id>/pay")
@require_auth("PayerAdmin")
def pay_claim(claim_id):
    with get_lock():
        claim = get_claim(claim_id)
        if claim["status"] != "ADJUDICATED":
            raise APIError("ERR_INVALID_STATE",
                           f"Cannot pay claim in status {claim['status']}")
        if claim.get("denial_reason") is not None:
            raise APIError("ERR_INVALID_STATE",
                           "Cannot pay a claim that has a denial_reason recorded")

        patient = get_patient(claim["patient_id"])
        clinic = get_store().clinics[patient["clinic_id"]]
        now_ts = clinic["now_ts"]

        # Supervision ratio gate at payment time (priority 9, after state).
        snapshot = compute_supervision_ratio(patient["id"], now_ts)
        if not snapshot["compliant"]:
            raise APIError("ERR_SUPERVISION_RATIO_BREACH",
                           "supervision ratio below 0.10 at payment time")

        store = get_store()
        auth = store.authorizations[claim["authorization_id"]]

        # Compute reimbursement.
        claim["reimbursed_amount_cents"] = compute_reimbursed_amount_cents(claim, auth)
        claim["status"] = "PAID"
        stamp_update(claim, now=now_ts)

        # Append ADJUDICATED_DEBIT for the sum of billed_units across the claim.
        total_billed = 0
        for sid in claim["session_ids"]:
            s = store.sessions[sid]
            total_billed += s.get("billed_units") or 0
        append_ledger_entry(
            authorization_id=auth["id"],
            entry_type="ADJUDICATED_DEBIT",
            units_delta=-total_billed,
            reason_code="CLAIM_PAID",
            now=now_ts,
            claim_id=claim["id"],
        )
        recompute_authorization_consumption(auth)
        maybe_auto_exhaust(auth, now_ts)
        recompute_patient_progress_scores(patient, now_ts)

    body_out, status = success_response(serialize_claim(claim))
    return jsonify(body_out), status


@bp.post("/claims/<claim_id>/deny")
@require_auth("PayerAdmin")
def deny_claim(claim_id):
    with get_lock():
        claim = get_claim(claim_id)
        if claim["status"] != "ADJUDICATED":
            raise APIError("ERR_INVALID_STATE",
                           f"Cannot deny claim in status {claim['status']}")
        if claim.get("denial_reason") is None:
            raise APIError("ERR_INVALID_STATE",
                           "Cannot deny a claim without a recorded denial_reason")

        patient = get_patient(claim["patient_id"])
        clinic = get_store().clinics[patient["clinic_id"]]
        now_ts = clinic["now_ts"]
        store = get_store()
        auth = store.authorizations[claim["authorization_id"]]

        # Cascade: each referenced session BILLED → COMPLETED.
        total_billed = 0
        for sid in claim["session_ids"]:
            s = store.sessions[sid]
            if s["status"] == "BILLED":
                s["status"] = "COMPLETED"
                stamp_update(s, now=now_ts)
            total_billed += s.get("billed_units") or 0

        claim["status"] = "DENIED"
        stamp_update(claim, now=now_ts)

        append_ledger_entry(
            authorization_id=auth["id"],
            entry_type="PROVISIONAL_CREDIT",
            units_delta=+total_billed,
            reason_code="CLAIM_DENIED",
            now=now_ts,
            claim_id=claim["id"],
        )
        recompute_authorization_consumption(auth)
        recompute_patient_progress_scores(patient, now_ts)

    body_out, status = success_response(serialize_claim(claim))
    return jsonify(body_out), status


@bp.post("/claims/<claim_id>/appeal")
@require_auth("ClinicAdmin")
def appeal_claim(claim_id):
    with get_lock():
        claim = get_claim(claim_id)
        if claim["status"] != "DENIED":
            raise APIError("ERR_INVALID_STATE",
                           f"Cannot appeal claim in status {claim['status']}")
        if claim["appeal_round"] >= 2:
            raise APIError("ERR_APPEAL_LIMIT_REACHED",
                           "claim has already been appealed twice")

        patient = get_patient(claim["patient_id"])
        clinic = get_store().clinics[patient["clinic_id"]]
        now_ts = clinic["now_ts"]
        store = get_store()

        # Cascade: each referenced session COMPLETED → BILLED.
        for sid in claim["session_ids"]:
            s = store.sessions[sid]
            if s["status"] == "COMPLETED":
                s["status"] = "BILLED"
                stamp_update(s, now=now_ts)

        claim["appeal_round"] += 1
        claim["denial_reason"] = None
        claim["status"] = "APPEALED"
        stamp_update(claim, now=now_ts)

    body_out, status = success_response(serialize_claim(claim))
    return jsonify(body_out), status


@bp.get("/patients/<patient_id>/claims")
@require_auth("ClinicAdmin", "BCBA", "PayerAdmin")
def list_claims(patient_id):
    limit, offset = get_pagination_params()
    status_filter = request.args.get("status")
    with get_lock():
        get_patient(patient_id)
        items = [
            c for c in get_store().claims.values()
            if c["patient_id"] == patient_id
            and (status_filter is None or c["status"] == status_filter)
        ]
        items.sort(key=lambda c: c["created_at"])
        page, total = paginate(items, limit, offset)
        body_out, status = list_response(
            [serialize_claim(c) for c in page], total, limit, offset
        )
    return jsonify(body_out), status


@bp.get("/claims/<claim_id>")
@require_auth("ClinicAdmin", "BCBA", "PayerAdmin")
def read_claim(claim_id):
    with get_lock():
        c = get_claim(claim_id)
    body_out, status = success_response(serialize_claim(c))
    return jsonify(body_out), status
