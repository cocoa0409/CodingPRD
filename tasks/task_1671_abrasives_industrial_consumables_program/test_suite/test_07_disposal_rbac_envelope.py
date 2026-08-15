"""Disposal manifests (hazard obligations, monthly mass threshold), RBAC,
response envelope, initial states, missing-auth rejection."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_disposal_record,
    make_blanket_order,
    make_contract,
    make_machine,
    make_product,
    make_release,
    make_standard,
    make_trial,
    make_lot,
    validate_error,
    validate_success,
    TEST_USERS,
)

ADMIN = TEST_USERS["program_admin_headers"]
AM = TEST_USERS["account_manager_headers"]
EHS = TEST_USERS["ehs_officer_headers"]


# ---------------------------------------------------------------------------
# Difficulty / boundary_precision_check / hazard_month_mass_exactly_1000_boundary
# ---------------------------------------------------------------------------


def _make_hazard_product(sku="GW-HZ"):
    return make_product(
        sku=sku,
        name="Grinding Wheel HZ",
        product_form="BONDED",
        max_operating_speed_rpm=6000,
        shelf_life_months=36,
        used_media_hazard_class="METAL_SWARF",
    )


def test_hazard_month_mass_below_threshold_no_regulator_ref_needed(api):
    """PRD §3.9: "the program aggregates the month's hazardous mass: the total
    `gross_weight_kg` over all disposal records sharing the new record's
    `customer_ref`, whose products are hazard-classed, and whose `disposed_at`
    falls in the same calendar month as the new record's `disposed_at` — the
    month running from its first day inclusive to the next month's first day
    exclusive — **including the new record itself**. When that monthly total
    reaches at least 1000.00 kg (the boundary is inclusive: exactly 1000.00 kg
    triggers the obligation), the record must carry a `regulator_report_ref`;
    its absence is rejected with `ERR_REGULATOR_REPORT_REQUIRED`."

    Design: Difficulty/boundary_precision_check/hazard_month_mass_exactly_1000_boundary
    """
    product = _make_hazard_product()
    resp = api.create_disposal_record(
        {
            "customer_ref": "PLANT-HZ",
            "product_id": product["id"],
            "qty_disposed": 10,
            "gross_weight_kg": 600.00,
            "disposal_method": "HAZARDOUS_WASTE_FACILITY",
            "manifest_number": "MF-1",
            "certified_facility_ref": "FAC-1",
            "disposed_at": "2026-08-05",
        },
        EHS,
    )
    record = validate_success(resp, 201)
    assert_disposal_record(record)
    # 600.00 < 1000.00: no regulator_report_ref required.


def test_hazard_month_mass_exactly_1000_requires_regulator_ref(api):
    """PRD §3.9: "When that monthly total reaches at least 1000.00 kg (the
    boundary is inclusive: exactly 1000.00 kg triggers the obligation), the
    record must carry a `regulator_report_ref`; its absence is rejected with
    `ERR_REGULATOR_REPORT_REQUIRED`."

    Design: Difficulty/boundary_precision_check/hazard_month_mass_exactly_1000_boundary
    """
    product = _make_hazard_product("GW-HZ2")
    first = api.create_disposal_record(
        {
            "customer_ref": "PLANT-HZ2",
            "product_id": product["id"],
            "qty_disposed": 10,
            "gross_weight_kg": 600.00,
            "disposal_method": "HAZARDOUS_WASTE_FACILITY",
            "manifest_number": "MF-1",
            "certified_facility_ref": "FAC-1",
            "disposed_at": "2026-08-05",
        },
        EHS,
    )
    validate_success(first, 201)

    # Month total would reach exactly 1000.00 kg including this record.
    resp = api.create_disposal_record(
        {
            "customer_ref": "PLANT-HZ2",
            "product_id": product["id"],
            "qty_disposed": 10,
            "gross_weight_kg": 400.00,
            "disposal_method": "HAZARDOUS_WASTE_FACILITY",
            "manifest_number": "MF-2",
            "certified_facility_ref": "FAC-1",
            "disposed_at": "2026-08-06",
        },
        EHS,
    )
    validate_error(resp, ApiErrorId.ERR_REGULATOR_REPORT_REQUIRED.value)

    # Same payload with regulator_report_ref succeeds.
    ok = api.create_disposal_record(
        {
            "customer_ref": "PLANT-HZ2",
            "product_id": product["id"],
            "qty_disposed": 10,
            "gross_weight_kg": 400.00,
            "disposal_method": "HAZARDOUS_WASTE_FACILITY",
            "manifest_number": "MF-2",
            "certified_facility_ref": "FAC-1",
            "regulator_report_ref": "RR-9",
            "disposed_at": "2026-08-06",
        },
        EHS,
    )
    validate_success(ok, 201)


# ---------------------------------------------------------------------------
# Corner / validations / disposal_hazard_method_rejected
# ---------------------------------------------------------------------------


def test_disposal_hazard_method_rejected(api):
    """PRD §3.9: "First, the `disposal_method` must be
    `HAZARDOUS_WASTE_FACILITY`; any other method is rejected with
    `ERR_HAZARD_DISPOSAL_METHOD_REQUIRED`."

    Design: Corner/validations/disposal_hazard_method_rejected
    """
    product = _make_hazard_product("DH-1")
    resp = api.create_disposal_record(
        {
            "customer_ref": "PLANT-DH",
            "product_id": product["id"],
            "qty_disposed": 10,
            "gross_weight_kg": 10.00,
            "disposal_method": "LANDFILL",
            "manifest_number": "MF-1",
            "certified_facility_ref": "FAC-1",
            "disposed_at": "2026-08-05",
        },
        EHS,
    )
    validate_error(resp, ApiErrorId.ERR_HAZARD_DISPOSAL_METHOD_REQUIRED.value)


# ---------------------------------------------------------------------------
# Corner / validations / disposal_manifest_fields_rejected
# ---------------------------------------------------------------------------


def test_disposal_manifest_fields_rejected(api):
    """PRD §3.9: "Second, both `manifest_number` and `certified_facility_ref`
    must be present; a missing field is rejected with
    `ERR_MANIFEST_FIELDS_REQUIRED` (HTTP 400)."

    Design: Corner/validations/disposal_manifest_fields_rejected
    """
    product = _make_hazard_product("DM-1")
    resp = api.create_disposal_record(
        {
            "customer_ref": "PLANT-DM",
            "product_id": product["id"],
            "qty_disposed": 10,
            "gross_weight_kg": 10.00,
            "disposal_method": "HAZARDOUS_WASTE_FACILITY",
            "disposed_at": "2026-08-05",
        },
        EHS,
    )
    validate_error(resp, ApiErrorId.ERR_MANIFEST_FIELDS_REQUIRED.value)


# ---------------------------------------------------------------------------
# Corner / validations / disposal_non_hazard_recycling_ok
# ---------------------------------------------------------------------------


def test_disposal_non_hazard_recycling_ok(api):
    """PRD §3.9: "Records for products whose hazard class is `NONE` carry none
    of these three obligations."
    PRD §3.1: "`used_media_hazard_class` classifies the spent media as `NONE`,
    `METAL_SWARF`, or `OIL_CONTAMINATED`, defaulting to `NONE`."

    Design: Corner/validations/disposal_non_hazard_recycling_ok
    """
    product = make_product(sku="DN-1", name="NonHaz Disc")  # hazard defaults NONE
    resp = api.create_disposal_record(
        {
            "customer_ref": "PLANT-DN",
            "product_id": product["id"],
            "qty_disposed": 12,
            "gross_weight_kg": 25.50,
            "disposal_method": "RECYCLING",
            "disposed_at": "2026-08-05",
        },
        EHS,
    )
    record = validate_success(resp, 201)
    assert_disposal_record(record)
    assert record["customer_ref"] == "PLANT-DN"


# ---------------------------------------------------------------------------
# Corner / rbac / rbac_product_create_forbidden_for_account_manager
# ---------------------------------------------------------------------------


def test_rbac_product_create_forbidden_for_account_manager(api):
    """PRD §2.1: "`ProgramAdmin` — the distributor's program administrator. This
    role owns the product catalog (registration and discontinuation)"
    PRD §2.1: "Any attempt to invoke an operation outside the caller's role is
    rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."

    Design: Corner/rbac/rbac_product_create_forbidden_for_account_manager
    """
    resp = api.create_product(
        {
            "sku": "RB-1",
            "name": "Rbac Disc",
            "product_form": "COATED",
            "max_operating_speed_rpm": 6000,
        },
        AM,
    )
    error = validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE.value)
    body = resp.json()
    assert body["response_type"] == "error"
    assert isinstance(error["message"], str) and error["message"].strip()


# ---------------------------------------------------------------------------
# Corner / rbac / rbac_submit_results_forbidden_for_program_admin
# ---------------------------------------------------------------------------


def test_rbac_submit_results_forbidden_for_program_admin(api):
    """PRD §2.1: "`EHSOfficer` — the customer-side environmental, health and
    safety officer. This role quarantines and reinstates machines, submits
    trial results and safety documentation, and files waste-disposal
    manifests."
    PRD §2.1: "Any attempt to invoke an operation outside the caller's role is
    rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."

    Design: Corner/rbac/rbac_submit_results_forbidden_for_program_admin
    """
    product = make_product(sku="RB-2", name="Rbac Trial Disc")
    machine = make_machine(customer_ref="PLANT-RB", asset_tag="GR-RB")
    trial = make_trial(machine["id"], product["id"],
                       scheduled_start="2026-09-01", scheduled_end="2026-09-03")

    resp = api.submit_trial_results(
        trial["id"],
        {
            "measured_removal_rate_g_per_min": 12.5,
            "parts_per_unit_media": 120,
            "cost_per_part_cents": 42,
        },
        ADMIN,  # ProgramAdmin is NOT the EHSOfficer role this endpoint requires
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE.value)
    assert api.get_trial(trial["id"], ADMIN).json()["data"]["status"] == "ACTIVE", (
        "denied submission must not change trial state"
    )


# ---------------------------------------------------------------------------
# Corner / rbac / missing_auth_header_returns_400
# ---------------------------------------------------------------------------


def test_missing_auth_header_returns_400(api):
    """PRD §2.1: "Every request must carry two HTTP headers: `X-User-ID`,
    identifying the acting operator, and `X-User-Role`, naming their
    operational capacity. A request in which either header is missing or
    malformed is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`
    (HTTP 400)."

    Design: Corner/rbac/missing_auth_header_returns_400
    """
    product = make_product(sku="RB-3", name="Header Disc")
    resp = api.get_product(product["id"], headers={})
    validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.value)


# ---------------------------------------------------------------------------
# Corner / endpoints / release_create_success_envelope
# ---------------------------------------------------------------------------


def test_release_create_success_envelope(api):
    """PRD §2.2: "The `api_request_id` is a server-generated unique identifier
    for the request that starts with `req_`." / "The `response_type` is either
    "object" for a single resource or "array" for a list of resources."
    PRD §3.6: "On acceptance the release starts `SCHEDULED` ... At scheduling
    time, `final_unit_price_cents` and `billed_total_cents` are null and
    `allocations` is empty."

    Design: Corner/endpoints/release_create_success_envelope
    """
    product = make_product(sku="EN-1", name="Envelope Disc")
    contract = make_contract(
        [{"product_id": product["id"], "base_unit_price_cents": 10000}],
        customer_ref="PLANT-EN", contract_number="C-EN",
    )
    order = make_blanket_order(contract["id"], product["id"], committed_qty=20)

    resp = api.create_release(
        order["id"],
        {"qty": 5, "scheduled_ship_date": "2026-09-01",
         "expected_blanket_order_version": order["version"]},
        AM,
    )
    data = validate_success(resp, 201)
    body = resp.json()
    assert body["response_type"] == "object"
    assert isinstance(body["meta"].get("api_request_id"), str)
    assert isinstance(body["meta"].get("api_request_timestamp"), str)

    assert data["status"] == "SCHEDULED"
    assert data["provisional_unit_price_cents"] == 10000
    assert data["allocations"] == []
    assert data["final_unit_price_cents"] is None
    assert data["billed_total_cents"] is None


# ---------------------------------------------------------------------------
# Corner / state_machines / initial_states_on_create
# ---------------------------------------------------------------------------


def test_initial_states_on_create(api):
    """PRD §3.1: "A new product starts `ACTIVE`."
    PRD §3.2: "A new machine starts `ACTIVE` with `consumption_flag` set to
    `NORMAL`."
    PRD §3.3: "The lot starts `AVAILABLE`"
    PRD §3.4: "A new standard starts `ACTIVE` with `needs_review` false."
    PRD §3.5: "The contract starts `DRAFT`"
    PRD §3.6: "The draft starts in `DRAFT` with `substitution_status` `NONE` and
    `remaining_qty` null"
    PRD §3.6: "On acceptance the release starts `SCHEDULED`"
    PRD §3.8: "A new trial starts `ACTIVE`, with its measurement fields null."

    Design: Corner/state_machines/initial_states_on_create
    """
    product = make_product(sku="IS-1", name="Init Disc")
    assert product["status"] == "ACTIVE"

    machine = make_machine(customer_ref="PLANT-IS", asset_tag="GR-IS")
    assert machine["status"] == "ACTIVE"
    assert machine["consumption_flag"] == "NORMAL"

    lot = make_lot(product["id"], lot_code="L-IS", qty_received=50)
    assert lot["status"] == "AVAILABLE"

    standard = make_standard(machine["id"], product["id"],
                             operation_name="DEBURR",
                             standard_qty_per_part=0.0250,
                             effective_from="2026-01-01")
    assert standard["status"] == "ACTIVE"
    assert standard["needs_review"] is False

    contract = make_contract(
        [{"product_id": product["id"], "base_unit_price_cents": 10000}],
        customer_ref="PLANT-IS", contract_number="C-IS", activate=False,
    )
    assert contract["status"] == "DRAFT"

    order = make_blanket_order(contract["id"], product["id"], committed_qty=20,
                               confirm=False)
    assert order["status"] == "DRAFT"
    assert order["substitution_status"] == "NONE"

    # Move contract + order to ACTIVE/OPEN so a release can be scheduled.
    validate_success(api.activate_contract(contract["id"], ADMIN), 200)
    opened = validate_success(api.confirm_blanket_order(order["id"], ADMIN), 200)
    release = make_release(order["id"], opened["version"], qty=5,
                           scheduled_ship_date="2026-09-01")
    assert release["status"] == "SCHEDULED"

    trial = make_trial(machine["id"], product["id"],
                       scheduled_start="2026-09-10", scheduled_end="2026-09-12")
    assert trial["status"] == "ACTIVE"


# ---------------------------------------------------------------------------
# Corner / validations / window_shape_invalid_rejected (trial half)
# ---------------------------------------------------------------------------


def test_trial_end_before_start_rejected(api):
    """PRD §2.8 item 3: "window shape (a trial's `scheduled_end` on or after its
    `scheduled_start`; a standard's `effective_to` strictly after its
    `effective_from` when present)"
    PRD §3.8: "a closed scheduling window from `scheduled_start` through
    `scheduled_end` (both dates inclusive; the end must be on or after the
    start)"

    Design: Corner/validations/window_shape_invalid_rejected
    """
    product = make_product(sku="WS-2", name="Window Shape Trial Disc")
    machine = make_machine(customer_ref="PLANT-WS2", asset_tag="GR-WS2")
    resp = api.create_trial(
        {
            "machine_id": machine["id"],
            "product_id": product["id"],
            "scheduled_start": "2026-09-10",
            "scheduled_end": "2026-09-05",
        },
        AM,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)
