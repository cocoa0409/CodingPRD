"""RentReduction routes."""
from flask import Blueprint

from common import (
    check_version,
    get_application_or_404,
    get_contract_or_404,
    get_json_body,
    get_program_or_404,
    get_rent_reduction_or_404,
    require_field,
    require_int,
    stamp_new,
    stamp_update,
)
from db import db
from errors import api_error
from middleware import require_roles
from response import success
from services.calc import (
    CATEGORY_BOOST,
    compute_monthly_effective_rent,
    compute_reduction_bps,
)
from services.sync import latest_event

bp = Blueprint("rent_reductions", __name__)


VALID_CATEGORIES = set(CATEGORY_BOOST.keys())


def _validate_documents(docs):
    if not isinstance(docs, list):
        raise api_error("ERR_INVALID_REQUEST",
                        "supporting_documents must be an array")
    for d in docs:
        if not isinstance(d, dict):
            raise api_error("ERR_INVALID_REQUEST",
                            "supporting_documents entries must be objects")
        for f in ("doc_type", "doc_ref", "issued_period"):
            if f not in d:
                raise api_error("ERR_INVALID_REQUEST",
                                f"supporting_documents entry missing {f}")


def _provisional_bps(contract: dict, declared_income: int,
                     hardship_category: str) -> int:
    unit = db.housing_units.get(contract["housing_unit_id"])
    base_rent = int(unit.get("monthly_base_rent_cents", 0)) if unit else 0
    return compute_reduction_bps(declared_income, base_rent, hardship_category)


# ----------------------------------------------------------------------------
# POST /contracts/{contractId}/rent-reductions  — Applicant (owns contract)
# ----------------------------------------------------------------------------
@bp.post("/housing-programs/<program_id>/contracts/<contract_id>/rent-reductions")
def create_rent_reduction(program_id, contract_id):
    user_id, _ = require_roles("Applicant")
    get_program_or_404(program_id)
    contract = get_contract_or_404(program_id, contract_id)

    application = get_application_or_404(program_id, contract["application_id"])
    if application.get("applicant_user_id") != user_id:
        raise api_error("ERR_INSUFFICIENT_PERMISSIONS",
                        "Only the owning applicant may apply for a rent reduction")

    body = get_json_body()
    hardship_category = require_field(body, "hardship_category")
    if hardship_category not in VALID_CATEGORIES:
        raise api_error("ERR_INVALID_REQUEST", "Invalid hardship_category")
    declared_income = require_int(body, "declared_hardship_income_cents", minimum=0)
    documents = require_field(body, "supporting_documents")
    _validate_documents(documents)
    if len(documents) < 1:
        raise api_error("ERR_INVALID_REQUEST",
                        "supporting_documents must contain at least one element")

    # requested_discount_bps is intentionally ignored per PRD §3.6
    with db.lock:
        provisional = _provisional_bps(contract, declared_income, hardship_category)
        rr = {
            "contract_id": contract["id"],
            "hardship_category": hardship_category,
            "declared_hardship_income_cents": declared_income,
            "supporting_documents": documents,
            "requested_discount_bps": body.get("requested_discount_bps"),
            "provisional_discount_bps": provisional,
            "final_discount_bps": None,
            "validity_start_period": None,
            "validity_end_period": None,
            "primary_review_user_id": None,
            "secondary_review_user_id": None,
            "status": "SUBMITTED",
        }
        stamp_new(rr)
        db.rent_reductions[rr["id"]] = rr
    return success(rr, status=201)


# ----------------------------------------------------------------------------
# GET /rent-reductions/{rrId}
# ----------------------------------------------------------------------------
@bp.get("/housing-programs/<program_id>/rent-reductions/<rr_id>")
def get_rent_reduction(program_id, rr_id):
    require_roles("HousingDirector", "HousingOfficer", "Applicant", "Citizen",
                  "IntegrationGateway")
    get_program_or_404(program_id)
    rr = get_rent_reduction_or_404(program_id, rr_id)
    return success(rr)


# ----------------------------------------------------------------------------
# POST /rent-reductions/{rrId}/advance-to-primary  — HousingOfficer
# ----------------------------------------------------------------------------
@bp.post("/housing-programs/<program_id>/rent-reductions/<rr_id>/advance-to-primary")
def advance_to_primary(program_id, rr_id):
    require_roles("HousingOfficer")
    get_program_or_404(program_id)
    rr = get_rent_reduction_or_404(program_id, rr_id)
    body = get_json_body()
    check_version(rr, body)

    with db.lock:
        if rr.get("status") != "SUBMITTED":
            raise api_error("ERR_RENT_REDUCTION_NOT_SUBMITTED",
                            "RentReduction must be SUBMITTED")
        if not rr.get("supporting_documents"):
            raise api_error("ERR_INVALID_REQUEST",
                            "supporting_documents must be non-empty")
        rr["status"] = "PRIMARY_REVIEW"
        stamp_update(rr)
    return success(rr)


# ----------------------------------------------------------------------------
# POST /rent-reductions/{rrId}/advance-to-secondary  — HousingOfficer
# ----------------------------------------------------------------------------
@bp.post("/housing-programs/<program_id>/rent-reductions/<rr_id>/advance-to-secondary")
def advance_to_secondary(program_id, rr_id):
    user_id, _ = require_roles("HousingOfficer")
    get_program_or_404(program_id)
    rr = get_rent_reduction_or_404(program_id, rr_id)
    body = get_json_body()
    check_version(rr, body)

    with db.lock:
        if rr.get("status") != "PRIMARY_REVIEW":
            raise api_error("ERR_RENT_REDUCTION_NOT_IN_PRIMARY",
                            "RentReduction must be PRIMARY_REVIEW")
        rr["status"] = "SECONDARY_REVIEW"
        rr["primary_review_user_id"] = user_id
        stamp_update(rr)
    return success(rr)


# ----------------------------------------------------------------------------
# POST /rent-reductions/{rrId}/final-approve  — HousingDirector
# ----------------------------------------------------------------------------
@bp.post("/housing-programs/<program_id>/rent-reductions/<rr_id>/final-approve")
def final_approve(program_id, rr_id):
    user_id, _ = require_roles("HousingDirector")
    program = get_program_or_404(program_id)
    rr = get_rent_reduction_or_404(program_id, rr_id)
    body = get_json_body()
    check_version(rr, body)

    with db.lock:
        if rr.get("status") != "SECONDARY_REVIEW":
            raise api_error("ERR_RENT_REDUCTION_NOT_IN_SECONDARY",
                            "RentReduction must be SECONDARY_REVIEW")
        # Segregation of duties (priority 22)
        if user_id == rr.get("primary_review_user_id"):
            raise api_error("ERR_SEGREGATION_OF_DUTIES_VIOLATION",
                            "Final approver must differ from primary reviewer")

        cpi = int(program["current_period_index"])
        validity_start = cpi
        validity_end = cpi + 12

        # Overlap check (priority 23): no FINAL_APPROVED RR on same contract
        # whose [start, end) intersects the new [validity_start, validity_end).
        for other in db.rent_reductions.values():
            if other is rr:
                continue
            if other.get("contract_id") != rr["contract_id"]:
                continue
            if other.get("status") != "FINAL_APPROVED":
                continue
            os_ = other.get("validity_start_period")
            oe_ = other.get("validity_end_period")
            if os_ is None or oe_ is None:
                continue
            # Half-open interval intersection: max(s1, s2) < min(e1, e2)
            if max(int(os_), validity_start) < min(int(oe_), validity_end):
                raise api_error("ERR_OVERLAPPING_RENT_REDUCTION",
                                "New validity window overlaps existing FINAL_APPROVED reduction")

        # Compute final_discount_bps using verified income (latest TAX_INCOME_ASSETS
        # for parent application).
        contract = db.contracts.get(rr["contract_id"])
        application_id = contract.get("application_id") if contract else None
        verified_income = 0
        if application_id:
            tax_evt = latest_event(event_type="TAX_INCOME_ASSETS",
                                   subject_id=application_id)
            if tax_evt:
                verified_income = int((tax_evt.get("payload") or {}).get(
                    "monthly_income_cents", 0))
        unit = db.housing_units.get(contract.get("housing_unit_id")) if contract else None
        base_rent = int(unit.get("monthly_base_rent_cents", 0)) if unit else 0
        final_bps = compute_reduction_bps(verified_income, base_rent,
                                          rr.get("hardship_category"))

        rr["secondary_review_user_id"] = user_id
        rr["final_discount_bps"] = final_bps
        rr["validity_start_period"] = validity_start
        rr["validity_end_period"] = validity_end
        rr["status"] = "FINAL_APPROVED"
        stamp_update(rr)

        # Recompute monthly_effective_rent_cents
        if contract:
            contract["monthly_effective_rent_cents"] = compute_monthly_effective_rent(
                contract, current_period_index=cpi)
            stamp_update(contract)
    return success(rr)


# ----------------------------------------------------------------------------
# POST /rent-reductions/{rrId}/reject  — HousingOfficer or HousingDirector
# ----------------------------------------------------------------------------
@bp.post("/housing-programs/<program_id>/rent-reductions/<rr_id>/reject")
def reject_rent_reduction(program_id, rr_id):
    require_roles("HousingOfficer", "HousingDirector")
    get_program_or_404(program_id)
    rr = get_rent_reduction_or_404(program_id, rr_id)
    body = get_json_body()
    check_version(rr, body)

    with db.lock:
        if rr.get("status") not in {"PRIMARY_REVIEW", "SECONDARY_REVIEW"}:
            raise api_error("ERR_RENT_REDUCTION_NOT_REJECTABLE",
                            "RentReduction must be in {PRIMARY_REVIEW, SECONDARY_REVIEW}")
        rr["status"] = "REJECTED"
        stamp_update(rr)
    return success(rr)


# ----------------------------------------------------------------------------
# POST /rent-reductions/{rrId}/resubmit  — Applicant
# ----------------------------------------------------------------------------
@bp.post("/housing-programs/<program_id>/rent-reductions/<rr_id>/resubmit")
def resubmit_rent_reduction(program_id, rr_id):
    user_id, _ = require_roles("Applicant")
    get_program_or_404(program_id)
    rr = get_rent_reduction_or_404(program_id, rr_id)
    body = get_json_body()
    check_version(rr, body)

    contract = db.contracts.get(rr["contract_id"])
    application = db.applications.get(contract["application_id"]) if contract else None
    if not application or application.get("applicant_user_id") != user_id:
        raise api_error("ERR_INSUFFICIENT_PERMISSIONS",
                        "Only the owning applicant may resubmit this reduction")

    with db.lock:
        if rr.get("status") != "REJECTED":
            raise api_error("ERR_RENT_REDUCTION_NOT_REJECTED",
                            "RentReduction must be REJECTED to resubmit")

        # Optional updates
        if "hardship_category" in body and body["hardship_category"] is not None:
            if body["hardship_category"] not in VALID_CATEGORIES:
                raise api_error("ERR_INVALID_REQUEST", "Invalid hardship_category")
            rr["hardship_category"] = body["hardship_category"]
        if ("declared_hardship_income_cents" in body
                and body["declared_hardship_income_cents"] is not None):
            try:
                v = int(body["declared_hardship_income_cents"])
            except (TypeError, ValueError):
                raise api_error("ERR_INVALID_REQUEST",
                                "declared_hardship_income_cents must be integer")
            if v < 0:
                raise api_error("ERR_INVALID_REQUEST",
                                "declared_hardship_income_cents must be >= 0")
            rr["declared_hardship_income_cents"] = v
        if "supporting_documents" in body and body["supporting_documents"] is not None:
            _validate_documents(body["supporting_documents"])
            rr["supporting_documents"] = body["supporting_documents"]

        rr["status"] = "SUBMITTED"
        rr["primary_review_user_id"] = None
        rr["secondary_review_user_id"] = None
        rr["provisional_discount_bps"] = _provisional_bps(
            contract, int(rr["declared_hardship_income_cents"]),
            rr["hardship_category"],
        )
        stamp_update(rr)
    return success(rr)
