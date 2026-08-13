"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) so setup failures surface as
clear "Setup step failed" errors instead of confusing assertion failures.

Identity threading: every ownership-gated ContractorUser call is made with
make_contractor_headers(contractor["id"]) — never the shared constant.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_contractor_payload,
    create_equipment_model_payload,
    create_ahri_rating_payload,
    create_prebuy_program_payload,
    create_allocation_pool_payload,
    create_order_payload,
    create_order_line_payload,
    create_warranty_registration_payload,
    create_parts_claim_payload,
    create_cylinder_payload,
    create_rebate_submission_payload,
    create_training_course_payload,
    create_coop_claim_payload,
)
from .test_users import TEST_USERS, make_contractor_headers

ADMIN = TEST_USERS["distributor_admin_headers"]
PROCESSOR = TEST_USERS["warranty_processor_headers"]
OFFICER = TEST_USERS["compliance_officer_headers"]
COORDINATOR = TEST_USERS["training_coordinator_headers"]

DEFAULT_CLOCK = "2026-08-01T00:00:00Z"


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str) -> dict:
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN))


# ---------------------------------------------------------------------------
# Tier 1: single-entity creators
# ---------------------------------------------------------------------------

def make_contractor(license_number: str | None = None, **overrides) -> dict:
    payload = create_contractor_payload(**overrides)
    if license_number is not None:
        payload["license_number"] = license_number
    return get_success_data(api_client.create_contractor(payload, ADMIN))


def get_contractor(contractor_id: str) -> dict:
    return get_success_data(api_client.get_contractor(contractor_id, ADMIN))


def make_model(**overrides) -> dict:
    return get_success_data(api_client.create_equipment_model(
        create_equipment_model_payload(**overrides), ADMIN))


def make_ahri_rating(outdoor_unit_id: str, indoor_unit_id: str, **overrides) -> dict:
    return get_success_data(api_client.create_ahri_rating(
        create_ahri_rating_payload(outdoor_unit_id, indoor_unit_id, **overrides), ADMIN))


def make_system_rating(
    family_code: str,
    seer2: float = 17.0,
    eer2: float = 12.5,
    hspf2=None,
    ou_price_cents: int = 500_000,
    iu_price_cents: int = 100_000,
    ou_type: str = "CONDENSER",
    ou_refrigerant: str = "R454B",
    iu_refrigerant: str = "NONE",
    **rating_overrides,
):
    """Create an outdoor unit + indoor coil + ACTIVE rating. Returns (rating, ou, iu)."""
    ou = make_model(equipment_type=ou_type, refrigerant_type=ou_refrigerant,
                    family_code=family_code, list_price_cents=ou_price_cents)
    iu = make_model(equipment_type="COIL", refrigerant_type=iu_refrigerant,
                    family_code=family_code, list_price_cents=iu_price_cents)
    payload_overrides = dict(rating_overrides)
    if hspf2 is not None:
        payload_overrides["hspf2"] = hspf2
    rating = make_ahri_rating(ou["id"], iu["id"], seer2=seer2, eer2=eer2, **payload_overrides)
    return rating, ou, iu


def make_prebuy_program(**overrides) -> dict:
    return get_success_data(api_client.create_prebuy_program(
        create_prebuy_program_payload(**overrides), ADMIN))


def make_pool(**overrides) -> dict:
    return get_success_data(api_client.create_allocation_pool(
        create_allocation_pool_payload(**overrides), ADMIN))


def get_pool(pool_id: str) -> dict:
    return get_success_data(api_client.get_allocation_pool(pool_id, ADMIN))


def make_cylinder(**overrides) -> dict:
    return get_success_data(api_client.create_cylinder(
        create_cylinder_payload(**overrides), ADMIN))


def make_course(**overrides) -> dict:
    return get_success_data(api_client.create_training_course(
        create_training_course_payload(**overrides), COORDINATOR))


# ---------------------------------------------------------------------------
# Tier 2/3: order lifecycle shortcuts
# ---------------------------------------------------------------------------

def create_draft_order(contractor: dict, prebuy_program_id: str | None = None) -> dict:
    payload = create_order_payload(contractor["id"])
    if prebuy_program_id is not None:
        payload["prebuy_program_id"] = prebuy_program_id
    return get_success_data(api_client.create_order(
        payload, make_contractor_headers(contractor["id"])))


def add_line(order_id: str, contractor: dict, equipment_model_id: str | None = None,
             ahri_rating_id: str | None = None, quantity: int = 1) -> dict:
    payload = create_order_line_payload(quantity=quantity)
    if equipment_model_id is not None:
        payload["equipment_model_id"] = equipment_model_id
    if ahri_rating_id is not None:
        payload["ahri_rating_id"] = ahri_rating_id
    return get_success_data(api_client.add_order_line(
        order_id, payload, make_contractor_headers(contractor["id"])))


def submit_order(order_id: str, contractor: dict) -> dict:
    return get_success_data(api_client.submit_order(
        order_id, make_contractor_headers(contractor["id"])))


def ship_order(order_id: str) -> dict:
    return get_success_data(api_client.ship_order(order_id, ADMIN))


def deliver_order(order_id: str) -> dict:
    return get_success_data(api_client.deliver_order(order_id, ADMIN))


def get_order(order_id: str) -> dict:
    return get_success_data(api_client.get_order(order_id, ADMIN))


def deliver_merchandise(contractor: dict, list_price_cents: int,
                        family_code: str = "FAM-A", quantity: int = 1,
                        **model_overrides):
    """Create a model + order + line, then submit/ship/deliver. Returns (order, model)."""
    model = make_model(family_code=family_code, list_price_cents=list_price_cents,
                       **model_overrides)
    order = create_draft_order(contractor)
    add_line(order["id"], contractor, equipment_model_id=model["id"], quantity=quantity)
    submit_order(order["id"], contractor)
    ship_order(order["id"])
    return deliver_order(order["id"]), model


def seed_delivered_volume(contractor: dict, amounts_cents: list[int],
                          family_code: str = "FAM-SEED") -> dict:
    """Deliver one order per amount so ytd_purchase_cents accumulates.
    Returns the refreshed contractor."""
    for i, amount in enumerate(amounts_cents):
        deliver_merchandise(contractor, amount, family_code=f"{family_code}-{i}")
    return get_contractor(contractor["id"])


# ---------------------------------------------------------------------------
# Warranty / parts-claim composites
# ---------------------------------------------------------------------------

def create_registration(contractor: dict, model: dict, order: dict,
                        serial_number: str, install_date: str) -> dict:
    return get_success_data(api_client.create_warranty_registration(
        create_warranty_registration_payload(
            serial_number, model["id"], contractor["id"], order["id"], install_date),
        make_contractor_headers(contractor["id"])))


def register_warranty(registration_id: str, contractor: dict) -> dict:
    return get_success_data(api_client.register_warranty(
        registration_id, make_contractor_headers(contractor["id"])))


def file_claim(registration: dict, contractor: dict, failure_date: str,
               part_cost_cents: int = 100_000, labor_cost_cents: int = 40_000) -> dict:
    return get_success_data(api_client.create_parts_claim(
        create_parts_claim_payload(
            registration["id"], contractor["id"], failure_date,
            part_cost_cents=part_cost_cents, labor_cost_cents=labor_cost_cents),
        make_contractor_headers(contractor["id"])))


def claim_decision(claim_id: str, action: str, headers) -> dict:
    return get_success_data(api_client.parts_claim_decision(
        claim_id, {"action": action}, headers))


def setup_warranty_scenario(install_date: str, failure_date: str,
                            register: bool = True, with_claim: bool = True,
                            list_price_cents: int = 800_000) -> dict:
    """Contractor + delivered order + registration (+ optional register + claim).

    Caller must set the logical clock first when dates require it.
    Returns a context dict."""
    contractor = make_contractor()
    order, model = deliver_merchandise(contractor, list_price_cents, family_code="FAM-W")
    registration = create_registration(
        contractor, model, order,
        serial_number=f"SN-{contractor['id'][:8]}", install_date=install_date)
    ctx = {"contractor": contractor, "model": model, "order": order,
           "registration": registration}
    if register:
        ctx["registration"] = register_warranty(registration["id"], contractor)
    if with_claim:
        ctx["claim"] = file_claim(ctx["registration"], contractor, failure_date)
    return ctx


# ---------------------------------------------------------------------------
# Rebate composites
# ---------------------------------------------------------------------------

def setup_delivered_rating_order(seer2: float = 17.0, eer2: float = 12.5,
                                 hspf2=None, ou_price_cents: int = 500_000,
                                 iu_price_cents: int = 100_000,
                                 family_code: str = "FAM-RB") -> dict:
    """Contractor + PREMIUM-by-default AHRI system + DELIVERED order with one
    rating line. Returns a context dict with contractor/rating/order/models."""
    contractor = make_contractor()
    rating, ou, iu = make_system_rating(
        family_code, seer2=seer2, eer2=eer2, hspf2=hspf2,
        ou_price_cents=ou_price_cents, iu_price_cents=iu_price_cents)
    order = create_draft_order(contractor)
    add_line(order["id"], contractor, ahri_rating_id=rating["id"], quantity=1)
    submit_order(order["id"], contractor)
    ship_order(order["id"])
    order = deliver_order(order["id"])
    return {"contractor": contractor, "rating": rating, "ou": ou, "iu": iu,
            "order": order}


def create_dossier(ctx: dict, docs=None, program_type: str = "FEDERAL_TAX_CREDIT",
                   install_date: str | None = None, **overrides) -> dict:
    contractor = ctx["contractor"]
    payload = create_rebate_submission_payload(
        contractor["id"], ctx["order"]["id"], ctx["rating"]["id"],
        program_type=program_type, **overrides)
    if docs is not None:
        payload["docs"] = docs
    if install_date is not None:
        payload["install_date"] = install_date
    return get_success_data(api_client.create_rebate_submission(
        payload, make_contractor_headers(contractor["id"])))


def setup_docs_complete_rebate(**rating_kwargs) -> dict:
    """Delivered rating order + dossier submitted with all four docs attached,
    flowing to DOCS_COMPLETE in the submit request. Returns ctx with 'rebate'."""
    ctx = setup_delivered_rating_order(**rating_kwargs)
    contractor = ctx["contractor"]
    install_date = ctx["order"]["submitted_at"]
    rebate = create_dossier(
        ctx, docs=["AHRI_CERTIFICATE", "INVOICE", "LOAD_CALC", "PERMIT"],
        install_date=install_date)
    rebate = get_success_data(api_client.submit_rebate(
        rebate["id"], make_contractor_headers(contractor["id"])))
    ctx["rebate"] = rebate
    return ctx


# ---------------------------------------------------------------------------
# Refrigerant composites
# ---------------------------------------------------------------------------

def issue_cylinder(cylinder_id: str, contractor_id: str) -> dict:
    return get_success_data(api_client.issue_cylinder(
        cylinder_id, {"contractor_id": contractor_id}, ADMIN))


def return_cylinder(cylinder_id: str, returned_weight_lbs: float) -> dict:
    return get_success_data(api_client.return_cylinder(
        cylinder_id, {"returned_weight_lbs": returned_weight_lbs}, ADMIN))


def setup_issued_cylinder(tare: float = 20.00, full: float = 50.00,
                          refrigerant_type: str = "R410A") -> dict:
    """Contractor + cylinder issued to them. Returns ctx dict."""
    contractor = make_contractor()
    cylinder = make_cylinder(tare_weight_lbs=tare, full_weight_lbs=full,
                             refrigerant_type=refrigerant_type)
    cylinder = issue_cylinder(cylinder["id"], contractor["id"])
    return {"contractor": contractor, "cylinder": cylinder}


# ---------------------------------------------------------------------------
# Co-op claim composites
# ---------------------------------------------------------------------------

def setup_contractor_with_final_accrual(delivered_cents: int = 10_000_000) -> dict:
    """Contractor with one DELIVERED order of the given merchandise total."""
    contractor = make_contractor()
    order, model = deliver_merchandise(contractor, delivered_cents, family_code="FAM-CC")
    return {"contractor": get_contractor(contractor["id"]), "order": order,
            "model": model}


def file_coop_claim(contractor: dict, spend_cents: int = 50_000,
                    period: str = "2026-H2", invoice_reference: str | None = None) -> dict:
    payload = create_coop_claim_payload(
        contractor["id"], spend_cents=spend_cents, period=period)
    if invoice_reference is not None:
        payload["invoice_reference"] = invoice_reference
    return get_success_data(api_client.create_coop_claim(
        payload, make_contractor_headers(contractor["id"])))


def coop_decision(claim_id: str, payload: dict, headers=None) -> dict:
    return get_success_data(api_client.coop_claim_decision(
        claim_id, payload, headers or ADMIN))


# ---------------------------------------------------------------------------
# Training composites
# ---------------------------------------------------------------------------

def complete_course(course_id: str, attendee_contractor_ids: list) -> dict:
    return get_success_data(api_client.complete_training_course(
        course_id, {"attendee_contractor_ids": attendee_contractor_ids}, COORDINATOR))
