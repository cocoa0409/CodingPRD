"""Trust CRUD + lifecycle action endpoints."""
from __future__ import annotations

from flask import Blueprint, g, request

from db import store
from middleware import require_auth
from response import list_success, success
from services.serializers import trust_view
from services.trust_engine import (
    activate_trust,
    create_trust,
    patch_trust,
    revoke_trust,
    terminate_trust,
)

from routes._helpers import (
    GRANTOR_TAX_STATUSES,
    TRUST_STATUSES,
    TRUST_TYPES,
    check_version,
    enforce_grantor_owns_trust,
    enforce_trustee_is_under_trust,
    get_json,
    get_trust_or_404,
    paginate,
    parse_pagination,
    parse_version,
    require_bool,
    require_date,
    require_enum,
    require_string,
    sort_by_created_at,
)

bp = Blueprint("trusts", __name__)


# ── Create ──────────────────────────────────────────────────────────────────


@bp.post("/trusts")
@require_auth(["Grantor"])
def create_trust_route():
    body = get_json()
    name = require_string(body, "name")
    trust_type = require_enum(body, "trust_type", TRUST_TYPES)
    grantor_tax_status = require_enum(body, "grantor_tax_status", GRANTOR_TAX_STATUSES)
    has_grantor_powers = require_bool(body, "has_grantor_powers", default=False)
    situs_state = require_string(body, "situs_state")
    inception_date = require_date(body, "inception_date")
    with store.lock:
        t = create_trust(
            name=name,
            trust_type=trust_type,
            grantor_tax_status=grantor_tax_status,
            has_grantor_powers=has_grantor_powers,
            situs_state=situs_state,
            inception_date=inception_date,
            grantor_user_id=g.user_id,
        )
    return success(trust_view(t), 201)


# ── Read single + list ──────────────────────────────────────────────────────


@bp.get("/trusts/<trust_id>")
@require_auth(["Grantor", "Trustee", "Beneficiary", "TaxPreparer", "Auditor"])
def read_trust(trust_id):
    with store.lock:
        t = get_trust_or_404(trust_id)
        # Role-scoped reads:
        #  - Grantor sees own trust; Trustee must be under it; Beneficiary
        #    must have a Beneficiary record under it (their X-User-ID is the
        #    beneficiary id).
        if g.role == "Grantor" and t["grantor_user_id"] != g.user_id:
            from errors import err_forbidden
            raise err_forbidden("Grantor may only read own trust.")
        if g.role == "Trustee":
            enforce_trustee_is_under_trust(t)
        if g.role == "Beneficiary":
            # The caller must have a Beneficiary record under this trust whose
            # id matches X-User-ID.
            owns = any(
                b for b in store.beneficiaries.values()
                if b["trust_id"] == t["id"] and b["id"] == g.user_id
            )
            if not owns:
                from errors import err_forbidden
                raise err_forbidden("Beneficiary may only read own trust.")
        return success(trust_view(t), 200)


@bp.get("/trusts")
@require_auth(["Grantor", "Trustee", "TaxPreparer", "Auditor"])
def list_trusts():
    with store.lock:
        status_q = request.args.get("status")
        type_q = request.args.get("trust_type")
        items = list(store.trusts.values())
        # Role-scope filter:
        if g.role == "Grantor":
            items = [t for t in items if t["grantor_user_id"] == g.user_id]
        elif g.role == "Trustee":
            # Only trusts where this user_id is an ACTIVE Trustee.
            user_trust_ids = {
                t["trust_id"] for t in store.trustees.values()
                if t["user_id"] == g.user_id and t["status"] == "ACTIVE"
            }
            items = [t for t in items if t["id"] in user_trust_ids]
        # TaxPreparer and Auditor see all.
        if status_q:
            items = [t for t in items if t["status"] == status_q]
        if type_q:
            items = [t for t in items if t["trust_type"] == type_q]
        items = sort_by_created_at(items)
        limit, offset = parse_pagination()
        total = len(items)
        page = paginate(items, limit, offset)
        return list_success([trust_view(t) for t in page], limit, offset, total, 200)


# ── PATCH ───────────────────────────────────────────────────────────────────


@bp.patch("/trusts/<trust_id>")
@require_auth(["Grantor"])
def patch_trust_route(trust_id):
    body = get_json()
    with store.lock:
        t = get_trust_or_404(trust_id)
        enforce_grantor_owns_trust(t)
        check_version(t, parse_version(body))
        # PRD §2.11: trust_type/grantor_tax_status frozen post-ACTIVE.
        patch_trust(t, body)
        return success(trust_view(t), 200)


# ── Lifecycle actions ───────────────────────────────────────────────────────


@bp.post("/trusts/<trust_id>/activate")
@require_auth(["Grantor"])
def activate(trust_id):
    with store.lock:
        t = get_trust_or_404(trust_id)
        enforce_grantor_owns_trust(t)
        activate_trust(t)
        return success(trust_view(t), 200)


@bp.post("/trusts/<trust_id>/revoke")
@require_auth(["Grantor"])
def revoke(trust_id):
    with store.lock:
        t = get_trust_or_404(trust_id)
        enforce_grantor_owns_trust(t)
        revoke_trust(t)
        return success(trust_view(t), 200)


@bp.post("/trusts/<trust_id>/terminate")
@require_auth(["Trustee"])
def terminate(trust_id):
    with store.lock:
        t = get_trust_or_404(trust_id)
        enforce_trustee_is_under_trust(t)
        terminate_trust(t)
        return success(trust_view(t), 200)
