"""Reconsideration request endpoints (§3.10)."""
from __future__ import annotations

from flask import Blueprint

from app.auth import enforce_taxpayer_ownership, require_roles
from app.envelope import success
from app.errors import (
    ERR_INVALID_STATE,
    ERR_NOT_FOUND,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_VALIDATION,
    raise_error,
)
from app.services.calculations import project_payoff
from app.services.common import bump_version, check_version, init_common_fields
from app.services.csed import close_events_of_kind
from app.services.taxpayers import refresh_taxpayer_aggregates
from app.store import STORE, new_id
from app.timeutil import now_iso
from app.util import (
    get_json_body,
    optional_version,
    require_enum,
    require_fields,
    require_str,
)


bp = Blueprint("reconsiderations", __name__, url_prefix="/collections/reconsideration-requests")


REASONS = ("HARDSHIP", "INCOME_CHANGE", "OIC_DENIED_REVERT", "MISSED_PAYMENT_CURE")


def _serialize(r: dict) -> dict:
    return {
        "id": r["id"],
        "agreement_id": r["agreement_id"],
        "prior_request_id": r.get("prior_request_id"),
        "reason": r["reason"],
        "status": r["status"],
        "decision_officer_id": r.get("decision_officer_id"),
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


@bp.route("", methods=["POST"])
@require_roles("Taxpayer", "IRSOfficer")
def create_request(identity):
    body = get_json_body()
    require_fields(body, ["agreement_id", "reason"])
    agreement_id = require_str(body, "agreement_id")
    reason = require_enum(body, "reason", REASONS)
    prior = body.get("prior_request_id")
    if prior is not None and not isinstance(prior, str):
        raise_error(ERR_VALIDATION, "prior_request_id must be a string when supplied.")

    with STORE.lock:
        ia = STORE.installment_agreements.get(agreement_id)
        if ia is None:
            raise_error(ERR_NOT_FOUND, f"InstallmentAgreement {agreement_id!r} not found.")
        enforce_taxpayer_ownership(identity, ia["taxpayer_id"])
        if ia["status"] != "DEFAULTED":
            raise_error(ERR_INVALID_STATE, f"Agreement is in status {ia['status']}, cannot open reconsideration.")

        if prior:
            prior_req = STORE.reconsiderations.get(prior)
            if prior_req is None or prior_req["agreement_id"] != agreement_id:
                raise_error(ERR_VALIDATION, "prior_request_id must reference a record on the same agreement.")

        r = {
            "id": new_id(),
            "agreement_id": agreement_id,
            "prior_request_id": prior,
            "reason": reason,
            "status": "PENDING",
            "decision_officer_id": None,
        }
        init_common_fields(r)
        STORE.reconsiderations[r["id"]] = r

    return success(_serialize(r), status=201)


@bp.route("/<req_id>/decide", methods=["POST"])
@require_roles("IRSOfficer")
def decide(identity, req_id):
    body = get_json_body()
    require_fields(body, ["status"])
    decision = require_enum(body, "status", ("APPROVED", "DENIED"))

    with STORE.lock:
        r = STORE.reconsiderations.get(req_id)
        if r is None:
            raise_error(ERR_NOT_FOUND, f"ReconsiderationRequest {req_id!r} not found.")
        if r["status"] != "PENDING":
            raise_error(ERR_INVALID_STATE, f"Request in status {r['status']}, cannot decide.")
        check_version(r, optional_version(body))

        ia = STORE.installment_agreements.get(r["agreement_id"])
        if ia is None:
            raise_error(ERR_NOT_FOUND, "Underlying agreement no longer exists.")

        # Segregation of duties (priority 9)
        if ia.get("activated_by_officer_id") and identity.user_id == ia["activated_by_officer_id"]:
            raise_error(ERR_SEGREGATION_OF_DUTIES,
                        "Officer who activated the agreement cannot decide its reconsideration.")

        # priority 21: If all covered liabilities reached PAID or EXPIRED, cannot revive
        if decision == "APPROVED":
            liabs = [STORE.tax_liabilities[lid] for lid in ia["liability_ids"]]
            if all(l["status"] in ("PAID", "EXPIRED") for l in liabs):
                raise_error(ERR_INVALID_STATE, "Cannot revive agreement: all covered liabilities already terminal.")

        r["status"] = decision
        r["decision_officer_id"] = identity.user_id
        bump_version(r)

        if decision == "APPROVED" and ia["status"] == "DEFAULTED":
            # Cascade DEFAULTED → ACTIVE
            ia["status"] = "ACTIVE"
            ia["missed_payment_count"] = 0
            # Recompute planned_payoff_date
            from app.timeutil import parse_iso
            liabs = [STORE.tax_liabilities[lid] for lid in ia["liability_ids"]]
            csed_min = min(l["csed_effective_date"] for l in liabs)
            balance = sum(l["current_balance_cents"] for l in liabs)
            activation_iso = now_iso()
            ia["planned_payoff_date"] = project_payoff(
                initial_balance_cents=balance,
                monthly_payment_cents=ia["proposed_monthly_payment_cents"],
                activation_iso=activation_iso,
                csed_effective_min_iso=csed_min,
                agreement_type=ia["agreement_type"],
            )
            bump_version(ia)
            for lid in ia["liability_ids"]:
                close_events_of_kind(lid, "INSTALLMENT_PENDING")

        refresh_taxpayer_aggregates(ia["taxpayer_id"])
        return success(_serialize(r))


@bp.route("/<req_id>", methods=["GET"])
@require_roles("IRSOfficer", "OICOfficer", "Taxpayer")
def get_request(identity, req_id):
    with STORE.lock:
        r = STORE.reconsiderations.get(req_id)
        if r is None:
            raise_error(ERR_NOT_FOUND, f"ReconsiderationRequest {req_id!r} not found.")
        ia = STORE.installment_agreements.get(r["agreement_id"])
        if ia is not None:
            enforce_taxpayer_ownership(identity, ia["taxpayer_id"])
        return success(_serialize(r))
