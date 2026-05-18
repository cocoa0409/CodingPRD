"""Distribution endpoints (propose / approve / execute / reject)."""
from __future__ import annotations

from flask import Blueprint, g

from db import store
from errors import err_forbidden, err_not_found
from middleware import require_auth
from response import success
from services.serializers import distribution_view
from services.trust_engine import (
    approve_distribution,
    execute_distribution,
    propose_distribution,
    reject_distribution,
)

from routes._helpers import (
    DISTRIBUTION_TYPES,
    enforce_grantor_owns_trust,
    enforce_trustee_is_under_trust,
    get_beneficiary_or_404,
    get_distribution_or_404,
    get_json,
    get_trust_or_404,
    require_date,
    require_enum,
    require_money,
    require_string,
)

bp = Blueprint("distributions", __name__)


@bp.post("/trusts/<trust_id>/distributions")
@require_auth(["Grantor", "Trustee"])
def propose_distribution_route(trust_id):
    body = get_json()
    beneficiary_id = require_string(body, "beneficiary_id")
    scheduled_date = require_date(body, "scheduled_date")
    amount_principal = require_money(body, "amount_principal")
    amount_income = require_money(body, "amount_income")
    distribution_type = require_enum(body, "distribution_type", DISTRIBUTION_TYPES)
    with store.lock:
        t = get_trust_or_404(trust_id)
        if g.role == "Grantor":
            enforce_grantor_owns_trust(t)
        if g.role == "Trustee":
            enforce_trustee_is_under_trust(t)
        # Sibling-reference existence (scaffold priority 4).
        get_beneficiary_or_404(t, beneficiary_id)
        d = propose_distribution(
            t,
            beneficiary_id=beneficiary_id,
            scheduled_date=scheduled_date,
            amount_principal=amount_principal,
            amount_income=amount_income,
            distribution_type=distribution_type,
            proposed_by_user_id=g.user_id,
        )
        return success(distribution_view(d), 201)


@bp.get("/trusts/<trust_id>/distributions/<distribution_id>")
@require_auth(["Grantor", "Trustee", "Beneficiary", "TaxPreparer", "Auditor"])
def read_distribution(trust_id, distribution_id):
    with store.lock:
        t = get_trust_or_404(trust_id)
        if g.role == "Grantor":
            enforce_grantor_owns_trust(t)
        if g.role == "Trustee":
            enforce_trustee_is_under_trust(t)
        d = get_distribution_or_404(t, distribution_id)
        if g.role == "Beneficiary":
            if d["beneficiary_id"] != g.user_id:
                raise err_forbidden("Beneficiary may only read own distribution.")
        return success(distribution_view(d), 200)


@bp.post("/trusts/<trust_id>/distributions/<distribution_id>/approve")
@require_auth(["Trustee"])
def approve_route(trust_id, distribution_id):
    with store.lock:
        t = get_trust_or_404(trust_id)
        enforce_trustee_is_under_trust(t)
        d = get_distribution_or_404(t, distribution_id)
        approve_distribution(t, d, g.user_id)
        return success(distribution_view(d), 200)


@bp.post("/trusts/<trust_id>/distributions/<distribution_id>/execute")
@require_auth(["Trustee"])
def execute_route(trust_id, distribution_id):
    with store.lock:
        t = get_trust_or_404(trust_id)
        enforce_trustee_is_under_trust(t)
        d = get_distribution_or_404(t, distribution_id)
        execute_distribution(t, d)
        return success(distribution_view(d), 200)


@bp.post("/trusts/<trust_id>/distributions/<distribution_id>/reject")
@require_auth(["Trustee"])
def reject_route(trust_id, distribution_id):
    with store.lock:
        t = get_trust_or_404(trust_id)
        enforce_trustee_is_under_trust(t)
        d = get_distribution_or_404(t, distribution_id)
        reject_distribution(t, d, g.user_id)
        return success(distribution_view(d), 200)
