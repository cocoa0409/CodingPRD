"""Beneficiary endpoints."""
from __future__ import annotations

from flask import Blueprint, g

from db import store
from errors import err_forbidden
from middleware import require_auth
from response import success
from services.serializers import beneficiary_view
from services.trust_engine import add_beneficiary, terminate_beneficiary

from routes._helpers import (
    BENEFICIARY_CLASSES,
    BENEFICIARY_RELATION_CLASSES,
    DISTRIBUTION_TIERS,
    enforce_beneficiary_owns_record,
    enforce_grantor_owns_trust,
    enforce_trustee_is_under_trust,
    get_beneficiary_or_404,
    get_json,
    get_trust_or_404,
    require_date,
    require_enum,
    require_string,
)

bp = Blueprint("beneficiaries", __name__)


@bp.post("/trusts/<trust_id>/beneficiaries")
@require_auth(["Grantor"])
def create_beneficiary(trust_id):
    body = get_json()
    full_name = require_string(body, "full_name")
    relation_class = require_enum(body, "relation_class", BENEFICIARY_RELATION_CLASSES)
    beneficiary_class = require_enum(body, "beneficiary_class", BENEFICIARY_CLASSES)
    distribution_tier = require_enum(body, "distribution_tier", DISTRIBUTION_TIERS)
    birth_date = require_date(body, "birth_date")
    with store.lock:
        t = get_trust_or_404(trust_id)
        enforce_grantor_owns_trust(t)
        b = add_beneficiary(
            t,
            full_name=full_name,
            relation_class=relation_class,
            beneficiary_class=beneficiary_class,
            distribution_tier=distribution_tier,
            birth_date=birth_date,
        )
        return success(beneficiary_view(b), 201)


@bp.get("/trusts/<trust_id>/beneficiaries/<beneficiary_id>")
@require_auth(["Grantor", "Trustee", "Beneficiary", "TaxPreparer", "Auditor"])
def read_beneficiary(trust_id, beneficiary_id):
    with store.lock:
        t = get_trust_or_404(trust_id)
        if g.role == "Grantor":
            enforce_grantor_owns_trust(t)
        if g.role == "Trustee":
            enforce_trustee_is_under_trust(t)
        b = get_beneficiary_or_404(t, beneficiary_id)
        if g.role == "Beneficiary":
            enforce_beneficiary_owns_record(b)
        return success(beneficiary_view(b), 200)


@bp.post("/trusts/<trust_id>/beneficiaries/<beneficiary_id>/terminate")
@require_auth(["Trustee"])
def terminate_beneficiary_route(trust_id, beneficiary_id):
    with store.lock:
        t = get_trust_or_404(trust_id)
        enforce_trustee_is_under_trust(t)
        b = get_beneficiary_or_404(t, beneficiary_id)
        terminate_beneficiary(t, b)
        return success(beneficiary_view(b), 200)
