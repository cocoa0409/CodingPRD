"""AuthorizationRequest routes and state machine."""
from flask import Blueprint, g, jsonify, request

from ..auth import require_auth
from ..clock import clock_now_dt, clock_now_iso
from ..errors import APIError
from ..helpers import (
    check_version,
    get_json_body,
    get_pagination_params,
    optional_field,
    require_field,
)
from ..responses import list_response, success_response
from ..services.calculations import (
    calc_approval_expiration,
    calc_decision_deadline,
    recompute_evidence_metrics,
)
from ..services.lookups import (
    get_authorization_or_404,
    get_catalog_or_404,
    get_patient_or_404,
    get_provider_or_404,
    reference_or_404,
)
from ..services.serialize import serialize_authorization, serialize_decision
from ..store import get_lock, get_store, new_id, stamp_create, stamp_update


bp = Blueprint("authorizations", __name__)


VALID_URGENCIES = {"STANDARD", "EXPEDITED"}
VALID_DENIAL_REASONS = {
    "NOT_MEDICALLY_NECESSARY",
    "EXPERIMENTAL",
    "OUT_OF_NETWORK",
    "EVIDENCE_INSUFFICIENT",
    "NON_COVERED_BENEFIT",
}


def _ensure_provider_owns(auth: dict) -> None:
    """Ownership: a Provider may only act on auths where provider_id == X-User-ID."""
    if g.user_role == "Provider" and auth.get("provider_id") != g.user_id:
        raise APIError("ERR_FORBIDDEN", "Provider does not own this authorization")


def _pin_catalog(catalog: dict) -> dict:
    """Snapshot the catalog fields that downstream calculations depend on."""
    return {
        "code": catalog["code"],
        "version": catalog["version"],
        "standard_sla_hours": catalog["standard_sla_hours"],
        "expedited_sla_hours": catalog["expedited_sla_hours"],
        "approval_validity_days": catalog["approval_validity_days"],
        "required_evidence_categories": list(catalog.get("required_evidence_categories") or []),
    }


# --- CRUD --------------------------------------------------------------------


@bp.post("/authorization-requests")
@require_auth("Provider")
def create_authorization():
    body = get_json_body()
    patient_id = require_field(body, "patient_id")
    provider_id = require_field(body, "provider_id")
    service_catalog_item_id = require_field(body, "service_catalog_item_id")
    urgency = optional_field(body, "urgency", "STANDARD")
    if urgency not in VALID_URGENCIES:
        raise APIError("ERR_VALIDATION", f"urgency must be one of {sorted(VALID_URGENCIES)}")
    clinical_justification = require_field(body, "clinical_justification")
    if not isinstance(clinical_justification, str) or len(clinical_justification) > 4000:
        raise APIError(
            "ERR_VALIDATION", "clinical_justification must be a string up to 4000 chars"
        )
    requested_units = require_field(body, "requested_units")
    if (
        not isinstance(requested_units, int)
        or isinstance(requested_units, bool)
        or requested_units < 1
    ):
        raise APIError("ERR_VALIDATION", "requested_units must be an integer >= 1")
    prior_request_id = optional_field(body, "prior_request_id", None)

    with get_lock():
        store = get_store()

        # Validation #4 — FK body references must resolve.
        reference_or_404(store.patients, patient_id, "Patient")
        reference_or_404(store.providers, provider_id, "Provider")
        reference_or_404(store.catalog_items, service_catalog_item_id, "ServiceCatalogItem")

        # Provider ownership: provider_id in body must equal X-User-ID.
        if g.user_role == "Provider" and provider_id != g.user_id:
            raise APIError("ERR_FORBIDDEN", "provider_id must match the authenticated Provider")

        if prior_request_id is not None:
            # ERR_PRIOR_REQUEST_NOT_FOUND is its own 404 case (PRD §3.8).
            prior = store.authorization_requests.get(prior_request_id)
            if prior is None:
                raise APIError("ERR_PRIOR_REQUEST_NOT_FOUND", "prior_request_id not found")
            # Validation #12 — prior must be EXPIRED.
            if prior.get("status") != "EXPIRED":
                raise APIError(
                    "ERR_PRIOR_REQUEST_NOT_EXPIRED",
                    "prior_request_id must reference an EXPIRED authorization",
                )
            # Validation #13 — at most one resubmission per prior_request_id.
            for existing in store.authorization_requests.values():
                if existing.get("prior_request_id") == prior_request_id:
                    raise APIError(
                        "ERR_RESUBMISSION_ALREADY_EXISTS",
                        "A resubmission already exists for this prior_request_id",
                    )

        rec = {
            "patient_id": patient_id,
            "provider_id": provider_id,
            "service_code": None,
            "service_catalog_item_id": service_catalog_item_id,
            "service_catalog_item_version": None,
            "urgency": urgency,
            "clinical_justification": clinical_justification,
            "requested_units": requested_units,
            "prior_request_id": prior_request_id,
            "status": "DRAFT",
            "submitted_at": None,
            "decision_deadline_at": None,
            "decided_at": None,
            "expires_at": None,
            "evidence_completeness_score": 0.00,
            "evidence_reuse_discount": 0.00,
            "_pending_info_cycles": 0,
            "_pinned_catalog": None,
        }
        stamp_create(rec)
        store.authorization_requests[rec["id"]] = rec

    body_out, status = success_response(serialize_authorization(rec), status=201)
    return jsonify(body_out), status


@bp.get("/authorization-requests/<auth_id>")
@require_auth(
    "PlatformAdmin",
    "Provider",
    "InitialReviewer",
    "MedicalDirector",
    "ExternalReviewer",
    "PayerReviewer",
)
def get_authorization(auth_id: str):
    auth = get_authorization_or_404(auth_id)
    _ensure_provider_owns(auth)
    body_out, status = success_response(serialize_authorization(auth))
    return jsonify(body_out), status


@bp.get("/authorization-requests")
@require_auth(
    "PlatformAdmin", "Provider", "InitialReviewer", "MedicalDirector", "ExternalReviewer"
)
def list_authorizations():
    limit, offset = get_pagination_params()
    status_filter = request.args.get("status")
    urgency_filter = request.args.get("urgency")
    patient_filter = request.args.get("patient_id")
    provider_filter = request.args.get("provider_id")

    store = get_store()
    items = list(store.authorization_requests.values())

    # Providers may only see their own auths.
    if g.user_role == "Provider":
        items = [a for a in items if a["provider_id"] == g.user_id]

    if status_filter is not None:
        items = [a for a in items if a["status"] == status_filter]
    if urgency_filter is not None:
        items = [a for a in items if a["urgency"] == urgency_filter]
    if patient_filter is not None:
        items = [a for a in items if a["patient_id"] == patient_filter]
    if provider_filter is not None:
        items = [a for a in items if a["provider_id"] == provider_filter]

    items.sort(key=lambda a: a["created_at"])
    total = len(items)
    page = items[offset : offset + limit]
    serialized = [serialize_authorization(a) for a in page]

    body_out, status = list_response(serialized, total=total, limit=limit, offset=offset)
    return jsonify(body_out), status


@bp.patch("/authorization-requests/<auth_id>")
@require_auth("Provider")
def update_authorization(auth_id: str):
    with get_lock():
        auth = get_authorization_or_404(auth_id)
        _ensure_provider_owns(auth)
        if auth["status"] != "DRAFT":
            raise APIError(
                "ERR_INVALID_STATE", "AuthorizationRequest may be edited only while in DRAFT"
            )
        body = get_json_body()
        check_version(auth, body.get("version"))

        if "clinical_justification" in body:
            cj = body["clinical_justification"]
            if not isinstance(cj, str) or len(cj) > 4000:
                raise APIError(
                    "ERR_VALIDATION", "clinical_justification must be a string up to 4000 chars"
                )
            auth["clinical_justification"] = cj
        if "requested_units" in body:
            ru = body["requested_units"]
            if not isinstance(ru, int) or isinstance(ru, bool) or ru < 1:
                raise APIError("ERR_VALIDATION", "requested_units must be an integer >= 1")
            auth["requested_units"] = ru
        if "urgency" in body:
            u = body["urgency"]
            if u not in VALID_URGENCIES:
                raise APIError(
                    "ERR_VALIDATION", f"urgency must be one of {sorted(VALID_URGENCIES)}"
                )
            auth["urgency"] = u
        stamp_update(auth)

    body_out, status = success_response(serialize_authorization(auth))
    return jsonify(body_out), status


# --- State machine -----------------------------------------------------------


@bp.post("/authorization-requests/<auth_id>/submit")
@require_auth("Provider")
def submit_authorization(auth_id: str):
    with get_lock():
        auth = get_authorization_or_404(auth_id)
        _ensure_provider_owns(auth)
        if auth["status"] != "DRAFT":
            raise APIError("ERR_INVALID_STATE", "Only DRAFT authorizations may be submitted")

        body = get_json_body()

        store = get_store()
        catalog = store.catalog_items.get(auth["service_catalog_item_id"])
        patient = store.patients.get(auth["patient_id"])
        provider = store.providers.get(auth["provider_id"])

        # Validation priority order #6, #7, #8.
        if catalog is None or catalog["status"] != "ACTIVE":
            raise APIError(
                "ERR_CATALOG_RETIRED",
                "ServiceCatalogItem must be ACTIVE at submission",
            )
        if patient is None or patient["status"] != "ACTIVE":
            raise APIError("ERR_PATIENT_INACTIVE", "Patient must be ACTIVE at submission")
        if provider is None or provider["status"] != "ACTIVE":
            raise APIError("ERR_PROVIDER_SUSPENDED", "Provider must be ACTIVE at submission")

        # Validation #9 — expedited justification length.
        if auth["urgency"] == "EXPEDITED":
            non_ws = sum(1 for c in (auth.get("clinical_justification") or "") if not c.isspace())
            if non_ws < 50:
                raise APIError(
                    "ERR_EXPEDITED_JUSTIFICATION_REQUIRED",
                    "Expedited requests require >= 50 non-whitespace chars in clinical_justification",
                )

        # OCC last — priority #24.
        check_version(auth, body.get("version"))

        # Side effects on successful submission.
        auth["submitted_at"] = clock_now_iso()
        auth["service_code"] = catalog["code"]
        auth["service_catalog_item_version"] = catalog["version"]
        auth["_pinned_catalog"] = _pin_catalog(catalog)
        auth["status"] = "SUBMITTED"
        auth["decision_deadline_at"] = calc_decision_deadline(auth)
        recompute_evidence_metrics(auth)
        stamp_update(auth)

    body_out, status = success_response(serialize_authorization(auth))
    return jsonify(body_out), status


@bp.post("/authorization-requests/<auth_id>/start-review")
@require_auth("InitialReviewer")
def start_review(auth_id: str):
    with get_lock():
        auth = get_authorization_or_404(auth_id)
        if auth["status"] != "SUBMITTED":
            raise APIError(
                "ERR_INVALID_STATE", "start-review requires SUBMITTED status"
            )
        body = get_json_body()

        recompute_evidence_metrics(auth)
        if (auth.get("evidence_completeness_score") or 0.00) < 0.50:
            raise APIError(
                "ERR_EVIDENCE_INSUFFICIENT",
                "evidence_completeness_score must be >= 0.50 to start review",
            )

        check_version(auth, body.get("version"))

        auth["status"] = "UNDER_REVIEW"
        stamp_update(auth)

    body_out, status = success_response(serialize_authorization(auth))
    return jsonify(body_out), status


@bp.post("/authorization-requests/<auth_id>/request-info")
@require_auth("InitialReviewer")
def request_info(auth_id: str):
    with get_lock():
        auth = get_authorization_or_404(auth_id)
        if auth["status"] != "UNDER_REVIEW":
            raise APIError(
                "ERR_INVALID_STATE", "request-info requires UNDER_REVIEW status"
            )
        body = get_json_body()
        check_version(auth, body.get("version"))  # OCC last among checks, no business gates here

        auth["status"] = "PENDING_INFO"
        # Recompute completeness on the transition (PRD §3.7).
        recompute_evidence_metrics(auth)
        # Increment pending-info cycle counter and recompute the deadline.
        # NOTE: cycle counts a completed UNDER_REVIEW -> PENDING_INFO -> UNDER_REVIEW.
        # Per scaffold calc, the extension applies once a cycle exists; we increment
        # on each PENDING_INFO entry so the deadline grows on entry and stays grown
        # on resume.
        auth["_pending_info_cycles"] = auth.get("_pending_info_cycles", 0) + 1
        auth["decision_deadline_at"] = calc_decision_deadline(auth)
        stamp_update(auth)

    body_out, status = success_response(serialize_authorization(auth))
    return jsonify(body_out), status


@bp.post("/authorization-requests/<auth_id>/resume-review")
@require_auth("InitialReviewer")
def resume_review(auth_id: str):
    with get_lock():
        auth = get_authorization_or_404(auth_id)
        if auth["status"] != "PENDING_INFO":
            raise APIError(
                "ERR_INVALID_STATE", "resume-review requires PENDING_INFO status"
            )
        body = get_json_body()

        recompute_evidence_metrics(auth)
        if (auth.get("evidence_completeness_score") or 0.00) < 0.75:
            raise APIError(
                "ERR_EVIDENCE_INSUFFICIENT",
                "evidence_completeness_score must be >= 0.75 to resume from PENDING_INFO",
            )

        check_version(auth, body.get("version"))

        auth["status"] = "UNDER_REVIEW"
        auth["decision_deadline_at"] = calc_decision_deadline(auth)
        stamp_update(auth)

    body_out, status = success_response(serialize_authorization(auth))
    return jsonify(body_out), status


@bp.post("/authorization-requests/<auth_id>/peer-to-peer")
@require_auth("Provider")
def schedule_peer_to_peer(auth_id: str):
    with get_lock():
        auth = get_authorization_or_404(auth_id)
        _ensure_provider_owns(auth)
        if auth["status"] != "UNDER_REVIEW":
            raise APIError(
                "ERR_INVALID_STATE", "peer-to-peer requires UNDER_REVIEW status"
            )

        body = get_json_body()
        scheduled_at = require_field(body, "scheduled_at")
        duration_minutes = require_field(body, "duration_minutes")
        payer_reviewer_id = require_field(body, "payer_reviewer_id")

        if (
            not isinstance(duration_minutes, int)
            or isinstance(duration_minutes, bool)
            or duration_minutes < 15
            or duration_minutes > 60
        ):
            raise APIError("ERR_VALIDATION", "duration_minutes must be an integer in [15,60]")
        if not isinstance(payer_reviewer_id, str) or not payer_reviewer_id:
            raise APIError("ERR_VALIDATION", "payer_reviewer_id must be a non-empty string")

        # Parse and validate scheduled_at: must be strictly after now().
        from ..clock import parse_iso

        scheduled_dt = parse_iso(scheduled_at)
        now_dt = clock_now_dt()
        if scheduled_dt <= now_dt:
            raise APIError(
                "ERR_VALIDATION", "scheduled_at must be strictly after current server time"
            )

        store = get_store()

        # Validation #20 — at most one P2P in SCHEDULED or COMPLETED per auth.
        for p in store.peer_to_peer_reviews.values():
            if p["authorization_request_id"] == auth["id"] and p["status"] in {
                "SCHEDULED",
                "COMPLETED",
            }:
                raise APIError(
                    "ERR_PEER_REVIEW_ALREADY_SCHEDULED",
                    "A peer-to-peer review already exists for this authorization",
                )

        # Validation #21 — time conflict with another SCHEDULED P2P for same payer_reviewer_id.
        from datetime import timedelta

        new_start = scheduled_dt
        new_end = scheduled_dt + timedelta(minutes=duration_minutes)
        for p in store.peer_to_peer_reviews.values():
            if p["status"] != "SCHEDULED":
                continue
            if p["payer_reviewer_id"] != payer_reviewer_id:
                continue
            other_start = parse_iso(p["scheduled_at"])
            other_end = other_start + timedelta(minutes=p["duration_minutes"])
            # half-open intervals [start, end): overlap iff start < other_end and other_start < end
            if new_start < other_end and other_start < new_end:
                raise APIError(
                    "ERR_PEER_REVIEW_TIME_CONFLICT",
                    "Proposed P2P time conflicts with another scheduled review for this reviewer",
                )

        # OCC last — priority #24.
        check_version(auth, body.get("version"))

        p2p = {
            "authorization_request_id": auth["id"],
            "scheduled_at": scheduled_at,
            "duration_minutes": duration_minutes,
            "payer_reviewer_id": payer_reviewer_id,
            "outcome": "PENDING",
            "status": "SCHEDULED",
            "notes": None,
        }
        stamp_create(p2p)
        store.peer_to_peer_reviews[p2p["id"]] = p2p

        auth["status"] = "PEER_REVIEW"
        stamp_update(auth)

    from ..services.serialize import serialize_p2p

    body_out, status = success_response(serialize_p2p(p2p), status=201)
    return jsonify(body_out), status


@bp.post("/authorization-requests/<auth_id>/decide")
@require_auth("InitialReviewer")
def decide_authorization(auth_id: str):
    with get_lock():
        auth = get_authorization_or_404(auth_id)
        if auth["status"] != "UNDER_REVIEW":
            raise APIError(
                "ERR_INVALID_STATE", "Initial decision requires UNDER_REVIEW status"
            )
        body = get_json_body()

        outcome = require_field(body, "outcome")
        rationale = require_field(body, "rationale")
        if outcome not in {"APPROVED", "DENIED"}:
            raise APIError("ERR_VALIDATION", "outcome must be APPROVED or DENIED")
        if not isinstance(rationale, str) or len(rationale) > 4000:
            raise APIError("ERR_VALIDATION", "rationale must be a string up to 4000 chars")

        approved_units = optional_field(body, "approved_units", 0)
        denial_reason_code = optional_field(body, "denial_reason_code", None)

        # Validation #14 — approved_units range.
        if outcome == "APPROVED":
            if (
                not isinstance(approved_units, int)
                or isinstance(approved_units, bool)
                or approved_units < 1
                or approved_units > auth["requested_units"]
            ):
                raise APIError(
                    "ERR_INVALID_APPROVED_UNITS",
                    "approved_units must be in [1, requested_units] when APPROVED",
                )
        else:  # DENIED
            if (
                not isinstance(approved_units, int)
                or isinstance(approved_units, bool)
                or approved_units != 0
            ):
                raise APIError(
                    "ERR_INVALID_APPROVED_UNITS",
                    "approved_units must be 0 when outcome=DENIED",
                )
            # Validation #15 — denial reason required.
            if denial_reason_code is None:
                raise APIError(
                    "ERR_DENIAL_REASON_REQUIRED",
                    "denial_reason_code is required when outcome=DENIED",
                )
            if denial_reason_code not in VALID_DENIAL_REASONS:
                raise APIError(
                    "ERR_VALIDATION",
                    f"denial_reason_code must be one of {sorted(VALID_DENIAL_REASONS)}",
                )

        # OCC last — priority #24.
        check_version(auth, body.get("version"))

        store = get_store()
        # Side effects.
        now = clock_now_iso()
        decision = {
            "id": new_id(),
            "authorization_request_id": auth["id"],
            "outcome": outcome,
            "rationale": rationale,
            "approved_units": approved_units if outcome == "APPROVED" else 0,
            "denial_reason_code": denial_reason_code if outcome == "DENIED" else None,
            "decided_by_role": "INITIAL_REVIEWER",
            "supersedes_decision_id": None,
            "created_at": now,
        }
        store.decisions[decision["id"]] = decision

        auth["status"] = outcome
        auth["decided_at"] = now
        if outcome == "APPROVED":
            auth["expires_at"] = calc_approval_expiration(auth)
        stamp_update(auth)

    body_out, status = success_response(serialize_decision(decision), status=201)
    return jsonify(body_out), status


@bp.post("/authorization-requests/<auth_id>/withdraw")
@require_auth("Provider")
def withdraw_authorization(auth_id: str):
    with get_lock():
        auth = get_authorization_or_404(auth_id)
        _ensure_provider_owns(auth)
        if auth["status"] not in {"DRAFT", "SUBMITTED", "PENDING_INFO"}:
            raise APIError(
                "ERR_INVALID_STATE",
                "Withdraw is only allowed from DRAFT, SUBMITTED, or PENDING_INFO",
            )
        body = get_json_body()
        check_version(auth, body.get("version"))

        prior_status = auth["status"]
        auth["status"] = "WITHDRAWN"
        stamp_update(auth)

        # Cascade: when SUBMITTED -> WITHDRAWN, cancel any SCHEDULED P2P.
        # (The scaffold also lists this side-effect path; it should be a no-op in
        # other cases because we only enter PEER_REVIEW from UNDER_REVIEW which
        # blocks withdrawal anyway.)
        if prior_status == "SUBMITTED":
            store = get_store()
            for p in store.peer_to_peer_reviews.values():
                if (
                    p["authorization_request_id"] == auth["id"]
                    and p["status"] == "SCHEDULED"
                ):
                    p["status"] = "CANCELLED"
                    stamp_update(p)

    body_out, status = success_response(serialize_authorization(auth))
    return jsonify(body_out), status
