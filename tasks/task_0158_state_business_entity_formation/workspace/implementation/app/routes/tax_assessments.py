"""Franchise tax assessment routes."""
from __future__ import annotations

from flask import Blueprint, jsonify

from ..auth import current_caller, require_auth
from ..envelope import object_response
from ..errors import (
    APIError,
    err_entity_not_active,
    err_invalid_input,
    err_invalid_state,
    err_not_found,
    err_segregation,
)
from ..store import store
from ..timeutil import march_first_of, now as clock_now
from ..util import get_json_body, new_uuid, require_enum, require_int, require_str
from ..services import serializers
from ..services.calculations import (
    authorized_shares_base_tax,
    assumed_par_value_base_tax,
    compute_late_fee_cents,
    compute_total_due,
)
from ..services.engine import emit_event, recompute_compliance_status, touch


bp = Blueprint("tax_assessments", __name__, url_prefix="/business-registry")


def _assessment_or_404(assessment_id):
    row = store.tax_assessments.get(assessment_id)
    if row is None:
        raise err_not_found(f"Tax assessment {assessment_id!r} not found")
    return row


def _validate_corp_sanity(entity: dict, chosen_method: str, chosen_base: int) -> None:
    """For CORP with both methods computable, ensure chosen <= 1.5 * other."""
    total_issued = int(entity.get("total_issued_shares") or 0)
    authorized = int(entity.get("authorized_shares") or 0)
    other_base = None
    if chosen_method == "AUTHORIZED_SHARES":
        if total_issued > 0:
            try:
                other_base = assumed_par_value_base_tax(
                    int(entity.get("total_gross_assets_cents") or 0),
                    total_issued,
                    authorized,
                )
            except ValueError:
                other_base = None
    elif chosen_method == "ASSUMED_PAR_VALUE":
        other_base = authorized_shares_base_tax(authorized)
    if other_base is None or other_base <= 0:
        # Other method is not computable; sanity rail does not apply.
        return
    # chosen > 1.5 * other → reject
    if chosen_base * 2 > other_base * 3:  # avoid float: chosen / other > 1.5  <=>  2*chosen > 3*other
        raise APIError("ERR_TAX_METHOD_MISMATCH",
                       "Chosen method exceeds the alternative by more than 50%", 422)


@bp.post("/tax-assessments")
@require_auth(["TaxOfficer"])
def create_tax_assessment():
    body = get_json_body()
    business_entity_id = require_str(body, "business_entity_id")
    tax_year = require_int(body, "tax_year", minimum=1900, maximum=9999)
    method = require_enum(body, "calculation_method", {"FLAT", "AUTHORIZED_SHARES", "ASSUMED_PAR_VALUE"})
    with store.lock:
        entity = store.business_entities.get(business_entity_id)
        if entity is None:
            raise err_not_found(f"business_entity_id {business_entity_id!r} not found")
        if entity.get("formation_status") != "ACTIVE":
            raise err_entity_not_active()
        # method vs type
        entity_type = entity.get("entity_type")
        if entity_type in ("LLC", "LP"):
            if method != "FLAT":
                raise APIError("ERR_INVALID_TAX_METHOD",
                               "LLC/LP entities may only use FLAT", 422)
        elif entity_type == "CORP":
            if method == "FLAT":
                raise APIError("ERR_INVALID_TAX_METHOD",
                               "CORP entities may not use FLAT", 422)
            if method == "ASSUMED_PAR_VALUE" and int(entity.get("total_issued_shares") or 0) <= 0:
                raise err_invalid_input("ASSUMED_PAR_VALUE method requires total_issued_shares > 0")
        else:
            raise err_invalid_input("Unknown entity_type")

        # Compute base tax
        if method == "FLAT":
            base_tax_cents = 30000
        elif method == "AUTHORIZED_SHARES":
            base_tax_cents = authorized_shares_base_tax(int(entity.get("authorized_shares") or 0))
        else:  # ASSUMED_PAR_VALUE
            base_tax_cents = assumed_par_value_base_tax(
                int(entity.get("total_gross_assets_cents") or 0),
                int(entity.get("total_issued_shares") or 0),
                int(entity.get("authorized_shares") or 0),
            )

        # Sanity rail (CORP only)
        if entity_type == "CORP":
            _validate_corp_sanity(entity, method, base_tax_cents)

        # Duplicate tax_year check
        for existing in store.tax_assessments.values():
            if (existing.get("business_entity_id") == business_entity_id
                    and existing.get("tax_year") == tax_year):
                raise APIError("ERR_DUPLICATE_TAX_YEAR",
                               f"Tax assessment for {tax_year} already exists", 409)

        now = clock_now()
        due_date = march_first_of(int(tax_year) + 1)
        # Initial total_due: apply credit even at creation per pinned order (status=ASSESSED, no late fee yet)
        credit = int(entity.get("credit_balance_cents", 0))
        pre_credit = base_tax_cents
        credit_applied = min(credit, pre_credit)
        total_due = pre_credit - credit_applied

        row = {
            "id": new_uuid(),
            "created_at": now,
            "updated_at": now,
            "version": 1,
            "business_entity_id": business_entity_id,
            "tax_year": tax_year,
            "calculation_method": method,
            "base_tax_cents": base_tax_cents,
            "late_fee_cents": 0,
            "total_due_cents": total_due,
            "credit_applied_cents": 0,  # only set on payment
            "due_date": due_date,
            "paid_at": None,
            "status": "ASSESSED",
        }
        store.tax_assessments[row["id"]] = row
        emit_event(business_entity_id, "TAX_ASSESSED",
                   {"assessment_id": row["id"], "tax_year": tax_year, "base_tax_cents": base_tax_cents}, occurred_at=now)
        return jsonify(object_response(serializers.tax_assessment(row))), 201


@bp.get("/tax-assessments/<assessment_id>")
@require_auth(["Filer", "TaxOfficer"])
def get_tax_assessment(assessment_id):
    row = _assessment_or_404(assessment_id)
    entity = store.business_entities.get(row.get("business_entity_id"))
    if entity is not None and entity.get("formation_status") == "ACTIVE":
        # Refresh compliance posture so downstream listings agree, but don't mutate the row.
        recompute_compliance_status(row.get("business_entity_id"))
    credit_balance = int(entity.get("credit_balance_cents", 0)) if entity else 0
    now = clock_now()
    late, total_due, credit_applied = compute_total_due(row, credit_balance, now)
    if row.get("status") != "PAID":
        # Refresh persisted late_fee/total_due for OVERDUE/DELINQUENT/ASSESSED so reads agree.
        row["late_fee_cents"] = late
        row["total_due_cents"] = total_due
    payload = serializers.tax_assessment(
        row,
        late_fee_cents=row["late_fee_cents"],
        total_due_cents=row["total_due_cents"],
        credit_applied_cents=credit_applied if row.get("status") != "PAID" else row.get("credit_applied_cents", 0),
    )
    return jsonify(object_response(payload)), 200


@bp.post("/tax-assessments/<assessment_id>/pay")
@require_auth(["Filer"])
def pay_tax_assessment(assessment_id):
    caller = current_caller()
    with store.lock:
        row = _assessment_or_404(assessment_id)
        if row.get("status") == "PAID":
            raise err_invalid_state("Assessment already PAID")
        entity = store.business_entities.get(row.get("business_entity_id"))
        if entity is None or entity.get("formation_status") != "ACTIVE":
            raise err_entity_not_active()
        if caller.user_id != row.get("business_entity_id"):
            raise APIError("ERR_FORBIDDEN", "Filer may not act on another entity", 403)
        # Segregation: Filer X-User-ID must not equal any TaxOfficer who accepted an
        # AnnualReport for this entity in this tax_year.
        key = (row.get("business_entity_id"), row.get("tax_year"))
        accept_actors = store.tax_accept_actor.get(key, set())
        if caller.user_id in accept_actors:
            raise err_segregation()

        now = clock_now()
        # Step 1-4 — pinned eval order using current status (no status flip yet).
        credit_balance = int(entity.get("credit_balance_cents", 0))
        late = compute_late_fee_cents(row.get("status"), now, row["due_date"], int(row["base_tax_cents"]))
        pre_credit = int(row["base_tax_cents"]) + late
        credit_applied = min(credit_balance, pre_credit)
        total_due = pre_credit - credit_applied

        # Step 5: decrement credit balance atomically and flip status.
        entity["credit_balance_cents"] = credit_balance - credit_applied
        touch(entity, ts=now)

        row["status"] = "PAID"
        row["paid_at"] = now
        row["late_fee_cents"] = late
        row["total_due_cents"] = total_due
        row["credit_applied_cents"] = credit_applied
        touch(row, ts=now)

        emit_event(row.get("business_entity_id"), "TAX_PAID",
                   {"assessment_id": row["id"], "amount_cents": total_due,
                    "credit_applied_cents": credit_applied}, occurred_at=now)
        recompute_compliance_status(row.get("business_entity_id"), at=now)
        return jsonify(object_response(serializers.tax_assessment(row))), 200


@bp.post("/tax-assessments/<assessment_id>/refund")
@require_auth(["TaxOfficer"])
def refund_tax_assessment(assessment_id):
    from datetime import timedelta
    with store.lock:
        row = _assessment_or_404(assessment_id)
        if row.get("status") != "PAID":
            raise err_invalid_state("Assessment is not PAID")
        entity = store.business_entities.get(row.get("business_entity_id"))
        if entity is None:
            raise err_not_found("Business entity missing for assessment")
        now = clock_now()
        credit_applied = int(row.get("credit_applied_cents", 0))
        # Restore credit balance.
        entity["credit_balance_cents"] = int(entity.get("credit_balance_cents", 0)) + credit_applied
        touch(entity, ts=now)
        # Recompute status from clock vs due_date.
        due_date = row["due_date"]
        if now <= due_date:
            new_status = "ASSESSED"
        elif now <= due_date + timedelta(days=90):
            new_status = "OVERDUE"
        else:
            new_status = "DELINQUENT"
        row["status"] = new_status
        row["paid_at"] = None
        # Recompute late fee for the new status.
        late = compute_late_fee_cents(new_status, now, due_date, int(row["base_tax_cents"]))
        row["late_fee_cents"] = late
        new_credit = int(entity.get("credit_balance_cents", 0))
        pre_credit = int(row["base_tax_cents"]) + late
        applied_now = min(new_credit, pre_credit)
        row["total_due_cents"] = pre_credit - applied_now
        row["credit_applied_cents"] = 0
        touch(row, ts=now)
        if entity.get("formation_status") == "ACTIVE":
            recompute_compliance_status(row.get("business_entity_id"), at=now)
        return jsonify(object_response(serializers.tax_assessment(row))), 200
