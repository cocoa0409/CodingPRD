"""URA relocation case lifecycle."""
from flask import Blueprint

import calc
import lookups
import store
import web
from core import fail
from web import endpoint

bp = Blueprint("relocation", __name__)

_OPTIONAL_CENTS = [
    "comparable_dwelling_price_cents",
    "actual_purchase_price_cents",
    "current_rent_cents",
    "current_utility_cents",
    "comparable_rent_cents",
    "comparable_utility_cents",
    "monthly_gross_income_cents",
    "moving_expense_cents",
]


@bp.post("/parcels/<parcel_id>/relocation-cases")
@endpoint("RelocationSpecialist")
def create_case(parcel_id):
    parcel = lookups.get_parcel(parcel_id)
    body = web.get_body()
    displacee_type = web.req_enum(body, "displacee_type", store.DISPLACEE_TYPES)
    household_reference = web.req_string(body, "household_reference")
    rhp_method = web.req_enum(body, "rhp_method", store.RHP_METHODS)
    web.req_date(body, "rental_assistance_start_date")
    amounts = {}
    for name in _OPTIONAL_CENTS:
        amounts[name] = web.int_field(body, name, required=False, default=0, minimum=0)
    if (displacee_type == "OWNER_OCCUPANT" and rhp_method == "COMPARABLE_DWELLING"
            and not web.present(body, "comparable_dwelling_price_cents")):
        fail("ERR_INVALID_REQUEST",
             "Field 'comparable_dwelling_price_cents' is required for an owner occupant "
             "using the COMPARABLE_DWELLING method.")
    if rhp_method == "ACTUAL_REPLACEMENT" and not web.present(body, "actual_purchase_price_cents"):
        fail("ERR_INVALID_REQUEST",
             "Field 'actual_purchase_price_cents' is required when rhp_method is ACTUAL_REPLACEMENT.")

    for existing in calc.parcel_cases(parcel_id):
        if existing["household_reference"] == household_reference:
            fail("ERR_DUPLICATE_HOUSEHOLD_REFERENCE")

    fields = {
        "parcel_id": parcel_id,
        "displacee_type": displacee_type,
        "household_reference": household_reference,
        "acquisition_price_cents": 0,
        "rhp_method": rhp_method,
        "rental_assistance_start_date": body["rental_assistance_start_date"],
        "rental_assistance_months": 0,
        "rental_assistance_end_date": None,
        "replacement_housing_payment_cents": 0,
        "rental_assistance_cents": 0,
        "total_relocation_benefit_cents": 0,
        "denial_reason": None,
        "appeal_basis": None,
        "appeal_count": 0,
        "status": "OPENED",
    }
    fields.update(amounts)
    record = store.new_record("RelocationCase", fields)
    store.cases[record["id"]] = record
    return web.respond_object(record, 201)


@bp.get("/relocation-cases")
@endpoint("ProgramAdministrator", "SubrecipientCoordinator", "RelocationSpecialist",
          "ComplianceMonitor")
def list_cases():
    parcel_id = web.query_str("parcel_id")
    displacee_type = web.query_enum("displacee_type", store.DISPLACEE_TYPES)
    status = web.query_enum("status", store.CASE_STATUSES)
    household_reference = web.query_str("household_reference")
    rows = list(store.cases.values())
    if parcel_id is not None:
        rows = [r for r in rows if r["parcel_id"] == parcel_id]
    if displacee_type is not None:
        rows = [r for r in rows if r["displacee_type"] == displacee_type]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if household_reference is not None:
        rows = [r for r in rows if r["household_reference"] == household_reference]
    return web.list_response(rows)


@bp.get("/relocation-cases/<case_id>")
@endpoint("ProgramAdministrator", "SubrecipientCoordinator", "RelocationSpecialist",
          "ComplianceMonitor")
def read_case(case_id):
    return web.respond_object(lookups.get_case(case_id))


@bp.post("/relocation-cases/<case_id>/determine-eligibility")
@endpoint("RelocationSpecialist")
def determine_eligibility(case_id):
    case = lookups.get_case(case_id)
    if case["status"] != "OPENED":
        fail("ERR_INVALID_CASE_STATE")
    accepted = None
    for offer in store.by_created(calc.parcel_offers(case["parcel_id"])):
        if offer["status"] == "ACCEPTED":
            accepted = offer
            break
    if accepted is None:
        fail("ERR_OFFER_NOT_FOUND")

    parcel = store.parcels.get(case["parcel_id"])
    project_id = parcel["project_id"] if parcel else None
    peer_ids = calc.project_parcel_ids(project_id) if project_id else set()
    start, end = calc.case_interval(case, projected=True)
    for other in store.cases.values():
        if other["id"] == case_id:
            continue
        if other["parcel_id"] not in peer_ids:
            continue
        if other["household_reference"] != case["household_reference"]:
            continue
        peer = calc.case_interval(other)
        if peer is None:
            continue
        other_start, other_end = peer
        if start < other_end and other_start < end:
            fail("ERR_RELOCATION_PERIOD_OVERLAP")

    computed = calc.relocation_benefits(case, accepted["net_offer_cents"])
    case.update(computed)
    case["status"] = "ELIGIBILITY_DETERMINED"
    store.touch(case)
    return web.respond_object(case)


@bp.post("/relocation-cases/<case_id>/submit-claim")
@endpoint("RelocationSpecialist")
def submit_claim(case_id):
    case = lookups.get_case(case_id)
    body = web.get_body()
    web.opt_string(body, "claim_note")
    if case["status"] not in ("ELIGIBILITY_DETERMINED", "APPEALED"):
        fail("ERR_INVALID_CASE_STATE")
    if case["displacee_type"] == "TENANT_UNDER_90_DAY":
        fail("ERR_TENANT_INELIGIBLE")
    case["status"] = "CLAIM_SUBMITTED"
    store.touch(case)
    return web.respond_object(case)


@bp.post("/relocation-cases/<case_id>/resolve-claim")
@endpoint("ProgramAdministrator")
def resolve_claim(case_id):
    case = lookups.get_case(case_id)
    body = web.get_body()
    decision = web.req_enum(body, "decision", ["PAY", "DENY"])
    denial_reason = web.opt_string(body, "denial_reason")
    if case["status"] not in ("CLAIM_SUBMITTED", "APPEALED"):
        fail("ERR_INVALID_CASE_STATE")
    if decision == "PAY" and case["status"] != "CLAIM_SUBMITTED":
        fail("ERR_INVALID_CASE_STATE")

    parcel = store.parcels.get(case["parcel_id"])
    project = lookups.project_of_parcel(parcel) if parcel else None

    if decision == "PAY":
        item = calc.federal_item(case["total_relocation_benefit_cents"],
                                 project["cost_share_federal_pct"])
        if (int(project["federal_obligated_cents"]) + item
                > int(project["total_federal_share_cap_cents"])):
            fail("ERR_FEDERAL_SHARE_CAP_EXCEEDED")
        case["status"] = "CLAIM_PAID"
        store.touch(case)
        calc.recompute_federal_obligated(project)
        store.touch(project)
        return web.respond_object(case)

    case["status"] = "CLAIM_DENIED_FINAL" if case["status"] == "APPEALED" else "CLAIM_DENIED"
    case["denial_reason"] = denial_reason
    store.touch(case)
    return web.respond_object(case)


@bp.post("/relocation-cases/<case_id>/appeal")
@endpoint("RelocationSpecialist")
def appeal_case(case_id):
    case = lookups.get_case(case_id)
    body = web.get_body()
    basis = web.req_string(body, "appeal_basis")
    if case["status"] != "CLAIM_DENIED":
        fail("ERR_INVALID_CASE_STATE")
    if int(case["appeal_count"]) >= store.MAX_RELOCATION_APPEALS:
        fail("ERR_APPEAL_LIMIT_REACHED")
    case["status"] = "APPEALED"
    case["appeal_basis"] = basis
    case["appeal_count"] = int(case["appeal_count"]) + 1
    store.touch(case)
    return web.respond_object(case)
