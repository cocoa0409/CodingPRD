"""Annexation cases, parcels, territory certification and the case-level actions."""

from decimal import Decimal

from flask import Blueprint

import validate as v
from auth import ANY_ROLE, check_municipality_scope, check_segregation_of_duties, prelude
from clockutil import days_inclusive, fiscal_year_end
from db import base_record, db, touch
from errors import ApiError
from response import object_response, paginate
from services import calc, domain

bp = Blueprint("cases", __name__)

METHODS = ("PETITION_100", "PETITION_MAJORITY", "REFERENDUM", "INVOLUNTARY_ORDINANCE")
PETITION_METHODS = ("PETITION_100", "PETITION_MAJORITY")


def case_for_write(case_id, roles, municipality_scoped=True):
    """Steps 1-3 and 6 for a case-rooted write: role, scope, then the 404."""
    user_id, role = prelude(roles)
    if municipality_scoped:
        soft_case = domain.soft("cases", case_id)
        check_municipality_scope(role, user_id, domain.municipality_id_of_case(soft_case))
    case = domain.path_record("cases", case_id)
    return case, user_id, role


def case_context(case):
    municipality = domain.municipality_of_case(case)
    statute = domain.statute_of_municipality(municipality)
    return municipality, statute


# ---------------------------------------------------------------------------
# Cases (PRD §3.2)
# ---------------------------------------------------------------------------

@bp.post("/annexation-cases")
def create_case():
    user_id, role = prelude(("MunicipalPlanner",))
    body = v.get_body()

    raw_municipality = body.get("municipality_id")
    if isinstance(raw_municipality, str):
        check_municipality_scope(role, user_id, raw_municipality)

    municipality_id = v.id_field(body, "municipality_id")
    municipality = domain.body_ref("municipalities", municipality_id)
    predecessor_id = v.id_field(body, "predecessor_case_id", required=False)
    predecessor = domain.body_ref("cases", predecessor_id) if predecessor_id is not None else None

    method = v.enum_field(body, "method", METHODS)
    case_type = v.enum_field(
        body, "case_type", ("ANNEXATION", "DE_ANNEXATION"), required=False, default="ANNEXATION"
    )
    shared_boundary_feet = v.num_field(body, "shared_boundary_feet", minimum=0)
    total_lot_count = v.int_field(body, "total_lot_count", minimum=0)
    developed_lot_count = v.int_field(body, "developed_lot_count", minimum=0)
    dwelling_units = v.int_field(body, "dwelling_units", minimum=0)
    max_distance = v.num_field(
        body, "max_service_distance_miles", required=False, default=Decimal(0), minimum=0
    )
    if developed_lot_count > total_lot_count:
        v.bad("developed_lot_count may not exceed total_lot_count.")

    statute = domain.statute_of_municipality(municipality)
    if case_type == "DE_ANNEXATION":
        if not statute["de_annexation_allowed"]:
            raise ApiError(
                "ERR_DE_ANNEXATION_NOT_ALLOWED",
                "The governing statute does not permit de-annexation cases.",
            )
        if predecessor_id is None:
            raise ApiError(
                "ERR_DE_ANNEXATION_NOT_ALLOWED",
                "A de-annexation case requires a predecessor_case_id.",
            )
    elif predecessor_id is not None:
        raise ApiError(
            "ERR_DE_ANNEXATION_NOT_ALLOWED",
            "An annexation case may not name a predecessor_case_id.",
        )

    record = base_record()
    record.update(
        {
            "municipality_id": municipality_id,
            "predecessor_case_id": predecessor_id,
            "case_type": case_type,
            "method": method,
            "status": "DRAFT",
            "tax_roll_status": "NOT_TRANSFERRED",
            "shared_boundary_feet": shared_boundary_feet,
            "total_lot_count": total_lot_count,
            "developed_lot_count": developed_lot_count,
            "dwelling_units": dwelling_units,
            "max_service_distance_miles": max_distance,
            "parcel_count": 0,
            "territory_acreage": Decimal("0.00"),
            "territory_assessed_value_cents": 0,
            "contiguity_ratio": Decimal("0.0000"),
            "urban_development_qualified": False,
            "qualification_index": Decimal("0.00"),
            "effective_date": None,
            "protest_pct": Decimal("0.00"),
            "protest_outcome": "NOT_EVALUATED",
            "referendum_result": "NOT_HELD",
            "commission_review_status": "NOT_REQUIRED",
            "fiscal_finalized_by_user_id": None,
            "hearing_held_at": None,
            "ordinance_adopted_at": None,
            "tax_roll_transferred_assessed_value_cents": 0,
            "tax_roll_transferred_tax_cents": 0,
            "de_annexation_refund_cents": 0,
            "msd_annual_assessment_cents": 0,
        }
    )
    db.cases[record["id"]] = record
    return object_response(record, 201)


@bp.get("/annexation-cases/<case_id>")
def read_case(case_id):
    prelude(ANY_ROLE)
    return object_response(domain.path_record("cases", case_id))


@bp.get("/annexation-cases")
def list_cases():
    prelude(ANY_ROLE)
    return paginate(
        domain.rows("cases"),
        ("municipality_id", "predecessor_case_id", "status", "case_type"),
    )


# ---------------------------------------------------------------------------
# Parcels (PRD §3.2)
# ---------------------------------------------------------------------------

@bp.post("/annexation-cases/<case_id>/parcels")
def add_parcel(case_id):
    case, _user_id, _role = case_for_write(case_id, ("MunicipalPlanner",))
    body = v.get_body()

    owner_id = v.id_field(body, "primary_owner_id")
    domain.body_ref("property_owners", owner_id)

    parcel_apn = v.str_field(body, "parcel_apn", min_len=1, max_len=40)
    assessed_value_cents = v.int_field(body, "assessed_value_cents", minimum=1)
    acreage = v.num_field(body, "acreage", exclusive_minimum=0, places=2)
    is_developed = v.bool_field(body, "is_developed", default=False)
    dwelling_units = v.int_field(body, "dwelling_units", required=False, default=0, minimum=0)

    domain.assert_case_not_terminal(case)

    if case["status"] != "DRAFT" or case["case_type"] != "ANNEXATION":
        raise ApiError(
            "ERR_PARCEL_STATE_INVALID",
            "Parcels may only be added while an ANNEXATION case is still DRAFT.",
        )

    for other in domain.rows("parcels"):
        if other["parcel_apn"] != parcel_apn:
            continue
        if other["annexation_case_id"] == case["id"]:
            continue
        if other["parcel_status"] not in domain.LIVE_PARCEL_STATUSES:
            continue
        other_case = domain.case_of_parcel(other)
        if other_case is None or other_case["municipality_id"] != case["municipality_id"]:
            continue
        if other_case["status"] in domain.TERMINAL_CASE_STATUSES or other_case["status"] == "EFFECTIVE":
            continue
        raise ApiError(
            "ERR_PARCEL_ALREADY_IN_PENDING_CASE",
            "Parcel %s is already claimed by a live case of this municipality." % parcel_apn,
        )

    record = base_record()
    record.update(
        {
            "annexation_case_id": case["id"],
            "primary_owner_id": owner_id,
            "parcel_apn": parcel_apn,
            "assessed_value_cents": assessed_value_cents,
            "acreage": acreage,
            "is_developed": is_developed,
            "dwelling_units": dwelling_units,
            "parcel_status": "PROPOSED",
            "annual_tax_cents": 0,
            "prorated_tax_cents": 0,
        }
    )
    db.parcels[record["id"]] = record

    domain.recompute_territory_aggregates(case)
    if case["status"] == "DRAFT":
        domain.restamp_qualification(case)
    touch(case)
    return object_response(record, 201)


@bp.get("/parcels/<parcel_id>")
def read_parcel(parcel_id):
    prelude(ANY_ROLE)
    return object_response(domain.path_record("parcels", parcel_id))


@bp.get("/parcels")
def list_parcels():
    prelude(ANY_ROLE)
    return paginate(
        domain.rows("parcels"), ("annexation_case_id", "primary_owner_id", "parcel_status")
    )


@bp.post("/parcels/<parcel_id>/exclude")
def exclude_parcel(parcel_id):
    user_id, role = prelude(("MunicipalPlanner",))
    soft_parcel = domain.soft("parcels", parcel_id)
    check_municipality_scope(
        role, user_id, domain.municipality_id_of_case(domain.case_of_parcel(soft_parcel))
    )
    parcel = domain.path_record("parcels", parcel_id)
    case = domain.case_of_parcel(parcel)
    domain.assert_case_not_terminal(case)

    if parcel["parcel_status"] not in ("PROPOSED", "PENDING_ANNEX"):
        raise ApiError(
            "ERR_PARCEL_STATE_INVALID",
            "Only a PROPOSED or PENDING_ANNEX parcel may be excluded.",
        )

    parcel["parcel_status"] = "EXCLUDED"
    touch(parcel)
    for account in domain.parcel_accounts(parcel):
        if account["account_status"] == "OUTSIDE_CITY":
            account["account_status"] = "DISCONNECTED"
            touch(account)

    if case is not None:
        domain.recompute_territory_aggregates(case)
        if case["status"] == "DRAFT":
            domain.restamp_qualification(case)
        touch(case)
    return object_response(parcel)


@bp.post("/annexation-cases/<case_id>/certify-territory")
def certify_territory(case_id):
    case, _user_id, _role = case_for_write(case_id, ("MunicipalPlanner",))
    domain.assert_case_not_terminal(case)
    municipality, statute = case_context(case)

    if case["status"] != "DRAFT":
        raise ApiError("ERR_CASE_STATE_INVALID", "Only a DRAFT case may be certified.")
    if case["method"] not in statute["authorized_methods"]:
        raise ApiError(
            "ERR_METHOD_NOT_AUTHORIZED_BY_STATUTE",
            "Method %s is not authorized by the governing statute." % case["method"],
        )

    parcels = domain.territory_parcels(case)
    if case["case_type"] == "ANNEXATION":
        eligible = [p for p in parcels if p["parcel_status"] in ("PROPOSED", "PENDING_ANNEX")]
    else:
        eligible = [p for p in parcels if p["parcel_status"] == "INCORPORATED"]
    if not eligible:
        raise ApiError("ERR_TERRITORY_EMPTY", "The proposed territory holds no eligible parcel.")

    count, acreage, value = calc.territory_aggregates(parcels)
    result = calc.territory_qualification(case, municipality, statute, acreage)

    if result["contiguity_ratio"] < calc.D(statute["contiguity_min_ratio"]):
        raise ApiError(
            "ERR_TERRITORY_NOT_CONTIGUOUS",
            "The territory does not meet the statutory contiguity ratio.",
        )
    if not result["urban_development_qualified"]:
        raise ApiError(
            "ERR_URBAN_DEVELOPMENT_TEST_FAILED",
            "Neither limb of the urban-development test passes.",
        )
    if result["qualification_index"] < calc.D(statute["min_qualification_index"]):
        raise ApiError(
            "ERR_SERVICE_CAPABILITY_INSUFFICIENT",
            "The qualification index is below the statutory minimum.",
        )

    if case["case_type"] == "DE_ANNEXATION":
        if not statute["de_annexation_allowed"]:
            raise ApiError(
                "ERR_DE_ANNEXATION_NOT_ALLOWED",
                "The governing statute does not permit de-annexation.",
            )
        predecessor = domain.soft("cases", case.get("predecessor_case_id"))
        if (
            predecessor is None
            or predecessor["status"] != "EFFECTIVE"
            or predecessor["municipality_id"] != case["municipality_id"]
        ):
            raise ApiError(
                "ERR_PREDECESSOR_NOT_EFFECTIVE",
                "The predecessor case must be EFFECTIVE and belong to the same municipality.",
            )

    case["parcel_count"] = count
    case["territory_acreage"] = acreage
    case["territory_assessed_value_cents"] = value
    case["contiguity_ratio"] = result["contiguity_ratio"]
    case["urban_development_qualified"] = result["urban_development_qualified"]
    case["qualification_index"] = result["qualification_index"]
    case["status"] = "TERRITORY_CERTIFIED"

    for parcel in domain.own_parcels(case):
        if parcel["parcel_status"] == "PROPOSED":
            parcel["parcel_status"] = "PENDING_ANNEX"
            touch(parcel)

    touch(case)
    return object_response(case)


# ---------------------------------------------------------------------------
# Ordinance, referendum, commission (PRD §3.7)
# ---------------------------------------------------------------------------

@bp.post("/annexation-cases/<case_id>/adopt-ordinance")
def adopt_ordinance(case_id):
    case, _user_id, _role = case_for_write(case_id, ("CityClerk",))
    domain.assert_case_not_terminal(case)
    municipality, statute = case_context(case)

    if case["status"] != "HEARING_HELD":
        raise ApiError(
            "ERR_CASE_STATE_INVALID", "The ordinance may only be adopted from HEARING_HELD."
        )
    if case["method"] not in statute["authorized_methods"]:
        raise ApiError(
            "ERR_METHOD_NOT_AUTHORIZED_BY_STATUTE",
            "Method %s is not authorized by the governing statute." % case["method"],
        )
    if domain.adopted_plan(case) is None:
        raise ApiError("ERR_PLAN_NOT_ADOPTED", "The case has no ADOPTED plan of services.")
    if case["protest_outcome"] != "FAILED":
        raise ApiError("ERR_PROTEST_PERIOD_OPEN", "The protest period has not been tabulated.")

    held_at = case.get("hearing_held_at")
    if held_at is not None:
        from clockutil import add_days

        if db.now() < add_days(held_at, statute["hearing_to_ordinance_min_days"]):
            raise ApiError(
                "ERR_COOLING_OFF_NOT_ELAPSED",
                "The statutory cooling-off period has not elapsed.",
            )

    finalized = [
        a
        for a in domain.rows("analyses")
        if a["annexation_case_id"] == case["id"] and a["status"] == "FINALIZED"
    ]
    if not finalized:
        raise ApiError(
            "ERR_FISCAL_ANALYSIS_NOT_FINALIZED",
            "The case has no FINALIZED fiscal impact analysis.",
        )
    analysis = finalized[0]
    if calc.D(analysis["deficit_ratio_pct"]) > calc.D(municipality["fiscal_deficit_tolerance_pct"]):
        raise ApiError(
            "ERR_FISCAL_DEFICIT_EXCEEDS_TOLERANCE",
            "The projected deficit exceeds the municipality's tolerance.",
        )

    case["ordinance_adopted_at"] = db.now()
    if case["method"] in statute["referendum_required_methods"]:
        case["status"] = "REFERENDUM_PENDING"
    else:
        case["status"] = "ORDINANCE_ADOPTED"
        if statute["boundary_commission_required"]:
            case["commission_review_status"] = "PENDING"
    touch(case)
    return object_response(case)


@bp.post("/annexation-cases/<case_id>/record-referendum")
def record_referendum(case_id):
    case, _user_id, _role = case_for_write(case_id, ("CityClerk",))
    body = v.get_body()
    result = v.enum_field(body, "result", ("APPROVED", "REJECTED"))
    domain.assert_case_not_terminal(case)
    _municipality, statute = case_context(case)

    if case["status"] != "REFERENDUM_PENDING":
        raise ApiError(
            "ERR_CASE_STATE_INVALID", "The referendum may only be recorded from REFERENDUM_PENDING."
        )

    if result == "APPROVED":
        case["referendum_result"] = "APPROVED"
        case["status"] = "REFERENDUM_APPROVED"
        if statute["boundary_commission_required"]:
            case["commission_review_status"] = "PENDING"
    else:
        case["referendum_result"] = "REJECTED"
        case["status"] = "DENIED"
        domain.rescind_cascade(case, statute)
    touch(case)
    return object_response(case)


@bp.post("/annexation-cases/<case_id>/submit-to-commission")
def submit_to_commission(case_id):
    case, _user_id, _role = case_for_write(case_id, ("MunicipalPlanner",))
    domain.assert_case_not_terminal(case)

    if case["status"] not in ("ORDINANCE_ADOPTED", "REFERENDUM_APPROVED"):
        raise ApiError(
            "ERR_CASE_STATE_INVALID",
            "Only an adopted or referendum-approved case may be submitted to the commission.",
        )
    if case["commission_review_status"] != "PENDING":
        raise ApiError(
            "ERR_COMMISSION_REVIEW_NOT_PENDING", "The commission review is not PENDING."
        )

    case["status"] = "COMMISSION_REVIEW"
    touch(case)
    return object_response(case)


@bp.post("/annexation-cases/<case_id>/commission-decision")
def commission_decision(case_id):
    user_id, _role = prelude(("BoundaryCommissioner",))
    check_segregation_of_duties(user_id, domain.soft("cases", case_id))
    case = domain.path_record("cases", case_id)

    body = v.get_body()
    decision = v.enum_field(body, "decision", ("APPROVED", "DENIED"))
    domain.assert_case_not_terminal(case)
    _municipality, statute = case_context(case)

    if case["status"] != "COMMISSION_REVIEW":
        raise ApiError(
            "ERR_CASE_STATE_INVALID", "The decision may only be recorded from COMMISSION_REVIEW."
        )
    if case["commission_review_status"] != "PENDING":
        raise ApiError(
            "ERR_COMMISSION_REVIEW_NOT_PENDING", "The commission review is not PENDING."
        )

    if decision == "APPROVED":
        case["commission_review_status"] = "APPROVED"
        case["status"] = "COMMISSION_APPROVED"
    else:
        case["commission_review_status"] = "DENIED"
        case["status"] = "DENIED"
        domain.rescind_cascade(case, statute)
    touch(case)
    return object_response(case)


# ---------------------------------------------------------------------------
# Effectuation, tax roll, MSD alternative (PRD §3.8, §3.9)
# ---------------------------------------------------------------------------

@bp.post("/annexation-cases/<case_id>/effectuate")
def effectuate(case_id):
    case, _user_id, _role = case_for_write(case_id, ("MunicipalPlanner",))
    body = v.get_body()
    effective_date = v.date_field(body, "effective_date")
    domain.assert_case_not_terminal(case)
    municipality, statute = case_context(case)

    if case["status"] not in ("ORDINANCE_ADOPTED", "REFERENDUM_APPROVED", "COMMISSION_APPROVED"):
        raise ApiError(
            "ERR_CASE_STATE_INVALID", "The case is not in a state that may be effectuated."
        )
    if case["method"] in statute["referendum_required_methods"] and case["referendum_result"] != "APPROVED":
        raise ApiError(
            "ERR_CASE_STATE_INVALID", "The ratification referendum has not been approved."
        )

    clock_date = db.now().date()
    year_end = fiscal_year_end(clock_date, statute["fiscal_year_end_month_day"])
    if not calc.effective_date_admissible(
        statute["effective_date_rule"], effective_date, clock_date, year_end
    ):
        raise ApiError(
            "ERR_EFFECTIVE_DATE_INVALID",
            "The submitted effective_date is not admissible under the statute's rule.",
        )

    if case["case_type"] == "DE_ANNEXATION":
        predecessor = domain.soft("cases", case.get("predecessor_case_id"))
        if (
            predecessor is None
            or predecessor["status"] != "EFFECTIVE"
            or predecessor["municipality_id"] != case["municipality_id"]
        ):
            raise ApiError(
                "ERR_PREDECESSOR_NOT_EFFECTIVE",
                "The predecessor case must be EFFECTIVE and belong to the same municipality.",
            )

    if statute["boundary_commission_required"] and case["commission_review_status"] != "APPROVED":
        raise ApiError(
            "ERR_COMMISSION_APPROVAL_REQUIRED",
            "Boundary commission approval is required before effectuation.",
        )

    case["status"] = "EFFECTIVE"
    case["effective_date"] = effective_date
    domain.effectuation_cascade(case, statute, municipality)
    if case["case_type"] == "DE_ANNEXATION":
        domain.deannexation_cascade(case, statute, municipality)
    touch(case)
    return object_response(case)


@bp.post("/annexation-cases/<case_id>/post-tax-roll")
def post_tax_roll(case_id):
    # The county assessor's X-User-ID is opaque: no municipality scope applies.
    case, _user_id, _role = case_for_write(case_id, ("CountyAssessor",), municipality_scoped=False)
    domain.assert_case_not_terminal(case)
    municipality, statute = case_context(case)

    if case["status"] != "EFFECTIVE":
        raise ApiError(
            "ERR_CASE_STATE_INVALID", "The tax roll may only be posted for an EFFECTIVE case."
        )
    if case["tax_roll_status"] != "NOT_TRANSFERRED":
        raise ApiError("ERR_TAX_ROLL_ALREADY_POSTED", "The tax roll has already been posted.")

    effective_date = case["effective_date"]
    year_end = fiscal_year_end(effective_date, statute["fiscal_year_end_month_day"])
    remaining_days = days_inclusive(effective_date, year_end)

    total_tax = 0
    total_value = 0
    for parcel in domain.own_parcels(case):
        if parcel["parcel_status"] != "INCORPORATED":
            continue
        annual = calc.parcel_annual_tax_cents(
            parcel["assessed_value_cents"], municipality["general_fund_millage_rate"]
        )
        prorated = calc.parcel_prorated_tax_cents(annual, remaining_days)
        parcel["annual_tax_cents"] = annual
        parcel["prorated_tax_cents"] = prorated
        touch(parcel)
        total_tax += prorated
        total_value += int(parcel["assessed_value_cents"])

    case["tax_roll_transferred_tax_cents"] = total_tax
    case["tax_roll_transferred_assessed_value_cents"] = total_value
    case["tax_roll_status"] = "POSTED"
    municipality["taxable_assessed_value_cents"] = (
        int(municipality["taxable_assessed_value_cents"]) + total_value
    )
    touch(municipality)
    touch(case)
    return object_response(case)


@bp.post("/annexation-cases/<case_id>/adopt-msd-alternative")
def adopt_msd_alternative(case_id):
    case, _user_id, _role = case_for_write(case_id, ("CityClerk",))
    domain.assert_case_not_terminal(case)
    _municipality, statute = case_context(case)

    if case["status"] != "PROTEST_SUSTAINED":
        raise ApiError(
            "ERR_CASE_STATE_INVALID",
            "The municipal service district alternative requires a sustained protest.",
        )
    plan = domain.adopted_plan(case)
    if plan is None:
        raise ApiError("ERR_PLAN_NOT_ADOPTED", "The case has no ADOPTED plan of services.")
    if not statute["msd_alternative_allowed"]:
        raise ApiError(
            "ERR_MSD_ALTERNATIVE_NOT_ALLOWED",
            "The governing statute does not permit a municipal service district alternative.",
        )

    case["msd_annual_assessment_cents"] = calc.msd_assessment_cents(
        plan["committed_cost_cents"], statute["msd_cost_recovery_pct"]
    )
    case["status"] = "MSD_ALTERNATIVE_ADOPTED"
    domain.msd_cascade(case)
    touch(case)
    return object_response(case)
