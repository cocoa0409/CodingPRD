"""Appeal routes — three-tier ladder."""
from flask import Blueprint, g, jsonify

from ..auth import require_auth
from ..clock import clock_now_dt, clock_now_iso, parse_iso
from ..errors import APIError
from ..helpers import check_version, get_json_body, optional_field, require_field
from ..responses import success_response
from ..services.calculations import (
    calc_appeal_decision_deadline,
    calc_approval_expiration,
)
from ..services.lookups import get_appeal_or_404, get_authorization_or_404
from ..services.serialize import serialize_appeal
from ..store import get_lock, get_store, new_id, stamp_create, stamp_update


bp = Blueprint("appeals", __name__)


# tier -> required role per PRD §3.11.
TIER_ROLE = {1: "InitialReviewer", 2: "MedicalDirector", 3: "ExternalReviewer"}


def _ensure_provider_owns(auth: dict) -> None:
    if g.user_role == "Provider" and auth.get("provider_id") != g.user_id:
        raise APIError(
            "ERR_FORBIDDEN", "Provider does not own this authorization"
        )


def _latest_denied_decision_for(auth_id: str):
    store = get_store()
    candidates = [
        d for d in store.decisions.values()
        if d["authorization_request_id"] == auth_id and d["outcome"] == "DENIED"
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda d: d["created_at"])
    return candidates[-1]


def _count_upheld_appeals(auth_id: str) -> int:
    return sum(
        1 for a in get_store().appeals.values()
        if a["authorization_request_id"] == auth_id and a["outcome"] == "UPHELD"
    )


@bp.post("/authorization-requests/<auth_id>/appeals")
@require_auth("Provider")
def file_appeal(auth_id: str):
    with get_lock():
        auth = get_authorization_or_404(auth_id)
        _ensure_provider_owns(auth)
        if auth["status"] != "DENIED":
            raise APIError(
                "ERR_INVALID_STATE",
                "Appeals may only be filed when authorization is DENIED",
            )

        body = get_json_body()
        reason = require_field(body, "reason")
        if not isinstance(reason, str) or len(reason) > 4000:
            raise APIError("ERR_VALIDATION", "reason must be a string up to 4000 chars")

        store = get_store()

        # tier = upheld_count + 1
        upheld = _count_upheld_appeals(auth_id)
        tier = upheld + 1
        if tier not in (1, 2, 3):
            raise APIError(
                "ERR_APPEAL_TIER_OUT_OF_ORDER",
                "Appeals exhausted past tier 3",
            )

        # Validation #17 — strict tier order. By construction tier == upheld + 1,
        # so out-of-order is implicit unless a PENDING appeal already exists at tier-1+.
        # The remaining out-of-order risk is when an appeal at tier N-1 is currently
        # PENDING (not yet UPHELD). In that case we should reject the attempt at tier N.
        # However since tier is computed from UPHELD count, a PENDING tier-1 appeal
        # would still produce tier=1 here. The "ALREADY_FILED" check below catches
        # that. Hence no extra work needed.

        # Validation #18 — no other PENDING appeal at the same tier.
        for a in store.appeals.values():
            if a["authorization_request_id"] != auth_id:
                continue
            if a["tier"] == tier and a["outcome"] == "PENDING":
                raise APIError(
                    "ERR_APPEAL_ALREADY_FILED",
                    f"A PENDING appeal at tier {tier} already exists for this authorization",
                )

        latest_denied = _latest_denied_decision_for(auth_id)
        superseded_decision_id = latest_denied["id"] if latest_denied else None

        filed_at = clock_now_iso()
        appeal = {
            "authorization_request_id": auth_id,
            "tier": tier,
            "reason": reason,
            "filed_at": filed_at,
            "decision_deadline_at": None,
            "outcome": "PENDING",
            "decided_at": None,
            "superseded_decision_id": superseded_decision_id,
        }
        stamp_create(appeal)
        appeal["decision_deadline_at"] = calc_appeal_decision_deadline(appeal, auth)
        store.appeals[appeal["id"]] = appeal

    body_out, status = success_response(serialize_appeal(appeal), status=201)
    return jsonify(body_out), status


@bp.get("/appeals/<appeal_id>")
@require_auth(
    "PlatformAdmin",
    "Provider",
    "InitialReviewer",
    "MedicalDirector",
    "ExternalReviewer",
)
def get_appeal(appeal_id: str):
    appeal = get_appeal_or_404(appeal_id)
    if g.user_role == "Provider":
        auth = get_authorization_or_404(appeal["authorization_request_id"])
        _ensure_provider_owns(auth)
    body_out, status = success_response(serialize_appeal(appeal))
    return jsonify(body_out), status


@bp.post("/appeals/<appeal_id>/decide")
@require_auth("InitialReviewer", "MedicalDirector", "ExternalReviewer")
def decide_appeal(appeal_id: str):
    with get_lock():
        appeal = get_appeal_or_404(appeal_id)

        # Priority #5 — state check (appeal must be PENDING, auth must be DENIED).
        if appeal["outcome"] != "PENDING":
            raise APIError("ERR_INVALID_STATE", "Appeal is not PENDING")

        auth = get_authorization_or_404(appeal["authorization_request_id"])
        if auth["status"] != "DENIED":
            raise APIError(
                "ERR_INVALID_STATE", "Parent authorization must be DENIED"
            )

        body = get_json_body()
        outcome = require_field(body, "outcome")
        rationale = require_field(body, "rationale")
        if outcome not in {"UPHELD", "OVERTURNED"}:
            raise APIError("ERR_VALIDATION", "outcome must be UPHELD or OVERTURNED")
        if not isinstance(rationale, str) or len(rationale) > 4000:
            raise APIError("ERR_VALIDATION", "rationale must be a string up to 4000 chars")

        # Priority #14 — approved_units range when OVERTURNED.
        approved_units = optional_field(body, "approved_units", None)
        if outcome == "OVERTURNED":
            if (
                not isinstance(approved_units, int)
                or isinstance(approved_units, bool)
                or approved_units < 1
            ):
                raise APIError(
                    "ERR_INVALID_APPROVED_UNITS",
                    "approved_units must be >= 1 when overturning an appeal",
                )
            if approved_units > auth["requested_units"]:
                # Tighter sanity: shouldn't exceed requested_units either.
                raise APIError(
                    "ERR_INVALID_APPROVED_UNITS",
                    "approved_units must be <= requested_units",
                )

        # Priority #16 — caller role must match tier.
        required_role = TIER_ROLE.get(appeal["tier"])
        if g.user_role != required_role:
            raise APIError(
                "ERR_APPEAL_TIER_ROLE_MISMATCH",
                f"Tier {appeal['tier']} appeals require role {required_role}",
            )

        # Priority #19 — deadline must not have passed.
        deadline_dt = parse_iso(appeal["decision_deadline_at"])
        if clock_now_dt() > deadline_dt:
            raise APIError(
                "ERR_APPEAL_DEADLINE_EXPIRED",
                "now() is past Appeal.decision_deadline_at",
            )

        # Priority #24 — OCC last.
        check_version(appeal, body.get("version"))

        now = clock_now_iso()
        appeal["outcome"] = outcome
        appeal["decided_at"] = now
        stamp_update(appeal)

        if outcome == "OVERTURNED":
            # Cascade: create new APPROVED Decision superseding the prior DENIED one.
            store = get_store()
            role_label = {
                "InitialReviewer": "INITIAL_REVIEWER",
                "MedicalDirector": "MEDICAL_DIRECTOR",
                "ExternalReviewer": "EXTERNAL_REVIEWER",
            }[g.user_role]
            new_decision = {
                "id": new_id(),
                "authorization_request_id": auth["id"],
                "outcome": "APPROVED",
                "rationale": rationale,
                "approved_units": approved_units,
                "denial_reason_code": None,
                "decided_by_role": role_label,
                "supersedes_decision_id": appeal.get("superseded_decision_id"),
                "created_at": now,
            }
            store.decisions[new_decision["id"]] = new_decision

            auth["status"] = "APPROVED"
            auth["decided_at"] = now
            # PRD §3.10: validity comes from the version-pinned catalog at original submission.
            auth["expires_at"] = calc_approval_expiration(auth)
            stamp_update(auth)

    body_out, status = success_response(serialize_appeal(appeal))
    return jsonify(body_out), status


@bp.post("/appeals/<appeal_id>/withdraw")
@require_auth("Provider")
def withdraw_appeal(appeal_id: str):
    with get_lock():
        appeal = get_appeal_or_404(appeal_id)
        auth = get_authorization_or_404(appeal["authorization_request_id"])
        _ensure_provider_owns(auth)

        if appeal["outcome"] != "PENDING":
            raise APIError("ERR_INVALID_STATE", "Only PENDING appeals may be withdrawn")

        body = get_json_body()
        check_version(appeal, body.get("version"))

        appeal["outcome"] = "WITHDRAWN"
        appeal["decided_at"] = clock_now_iso()
        stamp_update(appeal)

    body_out, status = success_response(serialize_appeal(appeal))
    return jsonify(body_out), status
