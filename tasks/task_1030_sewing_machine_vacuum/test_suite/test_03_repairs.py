"""Repair tickets: labor/parts invoicing, the reject/re-quote cycle, warranty
waiver, part-category and ownership constraints.
"""
from test_helpers import (
    TEST_USERS,
    create_repair_ticket_payload,
    make_customer_headers,
    new_customer,
    new_inventory_item,
    new_product,
    setup_quoted_repair,
    setup_repair_in_repair,
    validate_error,
    validate_success,
)

SA = TEST_USERS["sales_associate_headers"]
ST = TEST_USERS["service_tech_headers"]


# ─────────────── dual-variant labor estimate vs final invoice ──────────────
def test_labor_estimate_and_parts_accumulate_before_completion(api):
    """PRD §3.4: "A consumed part moves `IN_STOCK → SOLD` and its `list_price_cents`
    is added to the ticket's running `parts_cost_cents`."

    Design: Difficulty/dual_variant_calc/repair_labor_estimate_vs_final_invoice
    """
    _cust, _machine, ticket, _parts = setup_repair_in_repair(
        is_warranty=False, labor_hours=2.5, part_prices=(3000, 4500),
    )
    current = validate_success(api.get_repair_ticket(ticket["id"], ST), 200)
    assert current["labor_estimate_cents"] == 22500
    assert current["parts_cost_cents"] == 7500


def test_final_invoice_is_labor_plus_parts_for_non_warranty(api):
    """PRD §3.4: "when the ticket is a warranty job, labor is waived entirely and
    the final invoice equals the accumulated `parts_cost_cents`; otherwise the final
    invoice equals `labor_estimate_cents` plus `parts_cost_cents`."

    Design: Difficulty/dual_variant_calc/repair_labor_estimate_vs_final_invoice
    """
    _cust, _machine, ticket, _parts = setup_repair_in_repair(
        is_warranty=False, labor_hours=2.5, part_prices=(3000, 4500),
    )
    completed = validate_success(api.complete_repair_ticket(ticket["id"], ST), 200)
    assert completed["final_invoice_cents"] == 30000


# ───────────────── non-linear reject / re-quote revision loop ──────────────
def test_reject_returns_ticket_to_intake_and_clears_quote(api):
    """PRD §3.4: "it returns the ticket `AWAITING_APPROVAL → INTAKE` and clears the
    earlier quote — `diagnosis` back to null, `labor_hours` back to null, and
    `labor_estimate_cents` reset to 0 — so the technician can re-quote from scratch."

    Design: Difficulty/non_linear_state_machine/repair_ticket_reject_requote_cycle
    """
    _cust, _machine, ticket = setup_quoted_repair(labor_hours=1.0)
    rejected = validate_success(api.reject_repair_ticket(ticket["id"], SA), 200)
    assert rejected["status"] == "INTAKE"
    assert rejected["diagnosis"] is None
    assert rejected["labor_estimate_cents"] == 0


def test_requote_after_reject_returns_to_awaiting_approval_with_new_estimate(api):
    """PRD §3.4: "A `ServiceTech` quotes the job from `INTAKE`, supplying a
    `diagnosis` and the estimated `labor_hours`; this moves the ticket to
    `AWAITING_APPROVAL`, stores both values, and sets a provisional
    `labor_estimate_cents` equal to `labor_hours` multiplied by the labor rate of
    9,000 cents per hour, rounded half up to whole cents."

    Design: Difficulty/non_linear_state_machine/repair_ticket_reject_requote_cycle
    """
    _cust, _machine, ticket = setup_quoted_repair(labor_hours=1.0)
    api.reject_repair_ticket(ticket["id"], SA)
    requoted = validate_success(
        api.quote_repair_ticket(
            ticket["id"], {"diagnosis": "Battery + trigger fault", "labor_hours": 2.0}, ST
        ),
        200,
    )
    assert requoted["status"] == "AWAITING_APPROVAL"
    assert requoted["labor_estimate_cents"] == 18000


# ──────────────────────────── corner instances ────────────────────────────
def test_warranty_ticket_final_invoice_waives_labor(api):
    """PRD §3.4: "when the ticket is a warranty job, labor is waived entirely and
    the final invoice equals the accumulated `parts_cost_cents`; otherwise the final
    invoice equals `labor_estimate_cents` plus `parts_cost_cents`."

    Design: Corner/calculations/repair_invoice_warranty_waives_labor
    """
    _cust, _machine, ticket, _parts = setup_repair_in_repair(
        is_warranty=True, labor_hours=3.0, part_prices=(5000,),
    )
    current = validate_success(api.get_repair_ticket(ticket["id"], ST), 200)
    assert current["labor_estimate_cents"] == 27000
    completed = validate_success(api.complete_repair_ticket(ticket["id"], ST), 200)
    assert completed["final_invoice_cents"] == 5000


def test_close_ticket_still_in_intake_invalid_state(api):
    """PRD §3.4: "Handover is performed by a `SalesAssociate`, who closes a `READY`
    ticket (else `ERR_INVALID_STATE`), moving it `READY → CLOSED`."

    Design: Corner/state_machines/repair_close_from_intake_invalid
    """
    cust = new_customer("RT Cust", "rt@example.com")
    prod = new_product(model_name="RT Model", category="SEWING_MACHINE", brand="G", msrp_cents=50000)
    ticket = validate_success(
        api.create_repair_ticket(create_repair_ticket_payload(cust["id"], prod["id"]), ST), 201
    )
    res = api.close_repair_ticket(ticket["id"], SA)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_repair_approve_denied_for_non_owning_customer(api):
    """PRD §2.1: "the acting `X-User-ID` must equal the owning `customer_id` of the
    target resource; otherwise the request is rejected with `ERR_FORBIDDEN` (HTTP
    403)."

    Design: Corner/validations/repair_approve_ownership_denied_for_wrong_customer
    """
    owner = new_customer("Own1", "own1@example.com")
    other = new_customer("Own2", "own2@example.com")
    prod = new_product(model_name="Own Model", category="SEWING_MACHINE", brand="G", msrp_cents=50000)
    ticket = validate_success(
        api.create_repair_ticket(create_repair_ticket_payload(owner["id"], prod["id"]), ST), 201
    )
    validate_success(
        api.quote_repair_ticket(ticket["id"], {"diagnosis": "d", "labor_hours": 1.0}, ST), 200
    )
    res = api.approve_repair_ticket(ticket["id"], make_customer_headers(other["id"]))
    validate_error(res, "ERR_FORBIDDEN", expected_status=403)


def test_consume_non_part_unit_rejected(api):
    """PRD §3.4: "the unit must be `IN_STOCK` (else `ERR_ITEM_NOT_AVAILABLE`) and its
    product's `category` must be `PART` (else `ERR_NOT_A_PART`)."

    Design: Corner/errors/consume_part_non_part_rejected
    """
    _cust, _machine, ticket, _parts = setup_repair_in_repair(labor_hours=1.0, part_prices=())
    vac_prod = new_product(model_name="Np Vac", category="VACUUM", brand="G", msrp_cents=30000)
    vac_item = new_inventory_item(
        vac_prod["id"], serial_number="SN-NV", acquisition_cost_cents=18000, list_price_cents=30000
    )
    res = api.consume_part(ticket["id"], {"inventory_item_id": vac_item["id"]}, ST)
    validate_error(res, "ERR_NOT_A_PART", expected_status=409)


def test_consume_part_denied_for_sales_associate(api):
    """PRD §2.1: "When the headers are well-formed but the role is not permitted to
    perform the requested operation, the request is rejected with `ERR_FORBIDDEN`
    (HTTP 403)."

    Design: Corner/rbac/consume_part_denied_for_salesassociate
    """
    _cust, _machine, ticket, _parts = setup_repair_in_repair(labor_hours=1.0, part_prices=())
    part_prod = new_product(model_name="Rb Part", category="PART", brand="G", msrp_cents=3000)
    part_item = new_inventory_item(
        part_prod["id"], serial_number=None, acquisition_cost_cents=1000, list_price_cents=3000
    )
    res = api.consume_part(ticket["id"], {"inventory_item_id": part_item["id"]}, SA)
    validate_error(res, "ERR_FORBIDDEN", expected_status=403)
