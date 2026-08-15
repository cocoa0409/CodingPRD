"""Master data defaults, schema validation, alloy rules, routing validation, RBAC."""
import pytest

from test_helpers import (
    ApiErrorId,
    CHEM,
    EHS,
    MGR,
    NON_EXISTENT_UUID,
    OP,
    QC,
    create_bath,
    create_compat_rule,
    create_customer,
    create_fixture,
    create_titrated_bath,
    get_success_data,
    get_work_order,
    prepare_work_order,
    setup_routed_order,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.api_client import api_client
from test_helpers.factories import (
    create_alloy_rule_payload,
    create_bath_payload,
    create_customer_payload,
    create_fixture_payload,
    create_work_order_payload,
)
from test_helpers.test_users import make_customer_headers


def test_customer_defaults_applied():
    """PRD §3.1: "A `ShopManager` registers each **Customer** with a `company_name`, an
    optional `priority_tier` of `STANDARD` (the default) or `PREFERRED`, an optional
    `credit_hold` flag (default false), and an optional `status` that begins as
    `ACTIVE`."

    Design: Corner/entities/customer_defaults_applied
    """
    customer = get_success_data(
        api_client.create_customer({"company_name": "Default Co"}, MGR)
    )
    assert customer["priority_tier"] == "STANDARD"
    assert customer["credit_hold"] is False
    assert customer["status"] == "ACTIVE"
    assert customer["version"] == 1


def test_fixture_amortization_computed_at_creation():
    """PRD §3.1: "From these, the system computes `amortization_cents_per_use` at
    creation time as the purchase cost divided by the rated uses, rounded up to the
    next whole cent; the amortization is immutable thereafter and feeds the pricing
    formula of §3.4."

    Design: Corner/entities/fixture_amortization_computed_at_creation
    """
    fa = create_fixture(fixture_code="RACK-A", routing_mode="RACK", capacity_dm2=500,
                        purchase_cost_cents=120000, rated_uses=50)
    assert fa["amortization_cents_per_use"] == 2400  # 120000 / 50 exact
    fb = create_fixture(fixture_code="RACK-B", routing_mode="RACK", capacity_dm2=500,
                        purchase_cost_cents=100001, rated_uses=40)
    assert fb["amortization_cents_per_use"] == 2501  # ceil of 2500.025


def test_get_not_found_returns_404():
    """PRD §2.8: "Path identifiers are validated left-to-right — the first path id that
    does not correspond to an existing resource yields `ERR_NOT_FOUND` (HTTP 404)"

    Design: Corner/entities/bath_get_not_found_returns_404
    """
    resp_bath = api_client.get_bath(NON_EXISTENT_UUID, CHEM)
    validate_error(resp_bath, ApiErrorId.ERR_NOT_FOUND)
    resp_wo = api_client.get_work_order(NON_EXISTENT_UUID, OP)
    validate_error(resp_wo, ApiErrorId.ERR_NOT_FOUND)


def test_workorder_missing_required_field_returns_400():
    """PRD §2.8: "Request schema. Required fields present, types correct, enum members
    valid, ranges valid: the thickness minimum must not exceed the thickness maximum,
    an inspection must carry at least three thickness readings, a permit's `limits`
    must be non-empty with no repeated analyte, a sample must not repeat an analyte
    across its readings, and a manifest ship request must include the transporter.
    Violations yield `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/workorder_missing_required_field_returns_400
    """
    customer = create_customer(company_name="Req Co")
    payload = create_work_order_payload(customer_id=customer["id"], part_number="PN-X")
    del payload["thickness_spec_max_um"]
    resp = api_client.create_work_order(payload, make_customer_headers(customer["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
    # No work order was persisted.
    data, meta = validate_paginated(
        api_client.list_work_orders(OP, params={"customer_id": customer["id"]})
    )
    assert len(data) == 0
    assert meta["total_count"] == 0


def test_workorder_spec_inverted_returns_400():
    """PRD §3.4: "the inclusive thickness band `thickness_spec_min_um` (greater than
    zero and not above the maximum) and `thickness_spec_max_um` (not below the
    minimum)"
    PRD §2.8: "the thickness minimum must not exceed the thickness maximum"

    Design: Corner/entities/workorder_spec_inverted_returns_400
    """
    customer = create_customer(company_name="Range Co")
    payload = create_work_order_payload(
        customer_id=customer["id"], part_number="PN-INV",
        thickness_spec_min_um=18.0, thickness_spec_max_um=12.0,
    )
    resp = api_client.create_work_order(payload, make_customer_headers(customer["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_untitrated_bath_blocks_routing():
    """PRD §3.3: "Because the pessimistic variant needs a real concentration, routing a
    bath that has never been titrated is rejected with
    `ERR_BATH_CONCENTRATION_OUT_OF_BAND`."

    Design: Corner/entities/untitrated_or_out_of_band_bath_blocks_routing
    """
    customer = create_customer(company_name="Band Co")
    create_compat_rule()
    # Never titrated.
    bath_u = create_bath(bath_code="ANO-U", routing_modes_supported=["BARREL"])
    wo = get_success_data(api_client.create_work_order(
        create_work_order_payload(customer_id=customer["id"], part_number="PN-U"),
        make_customer_headers(customer["id"]),
    ))
    prepare_work_order(wo["id"])
    resp = api_client.route_work_order(
        wo["id"],
        {"bath_id": bath_u["id"], "planned_duration_minutes": 40,
         "planned_current_density_a_dm2": 1.5},
        OP,
    )
    validate_error(resp, ApiErrorId.ERR_BATH_CONCENTRATION_OUT_OF_BAND)


def test_alloy_rule_duplicate_rejected():
    """PRD §3.1: "A system-maintained `uniqueness` constraint spans the triple of
    alloy, process, and chemistry family: a duplicate submission is rejected with
    `ERR_DUPLICATE_COMPATIBILITY_RULE`."

    Design: Corner/entities/alloy_rule_duplicate_rejected
    """
    create_compat_rule(alloy_code="AL6061", process_type="ANODIZE",
                       chemistry_family="SULFURIC", compatibility="COMPATIBLE")
    # Same triple, even with a different compatibility verdict, is a duplicate.
    resp_dup = api_client.create_alloy_rule(
        create_alloy_rule_payload(alloy_code="AL6061", process_type="ANODIZE",
                                  chemistry_family="SULFURIC",
                                  compatibility="INCOMPATIBLE"),
        CHEM,
    )
    validate_error(resp_dup, ApiErrorId.ERR_DUPLICATE_COMPATIBILITY_RULE)
    # A different chemistry family is a different triple: accepted.
    resp_ok = api_client.create_alloy_rule(
        create_alloy_rule_payload(alloy_code="AL6061", process_type="ANODIZE",
                                  chemistry_family="CHROMIC",
                                  compatibility="CONDITIONAL"),
        CHEM,
    )
    validate_success(resp_ok, expected_status=201)


def test_alloy_rule_delete_restores_fail_closed():
    """PRD §3.1: "Deleting a rule — a `LabChemist` or `ShopManager` operation returning
    204 with no body — reopens the fail-closed default: routing afterwards treats the
    now-missing triple as incompatible (§3.5)."
    PRD §3.5: "the alloy compatibility rule for the order's alloy, process, and the
    bath's chemistry family must exist and not be `INCOMPATIBLE` (a missing rule fails
    closed and either case yields `ERR_ALLOY_BATH_INCOMPATIBLE`)"

    Design: Corner/entities/alloy_rule_delete_restores_fail_closed
    """
    customer = create_customer(company_name="Del Co")
    rule = create_compat_rule(alloy_code="AL5052", process_type="ANODIZE",
                              chemistry_family="SULFURIC", compatibility="COMPATIBLE")
    bath = create_titrated_bath(bath_code="ANO-D", routing_modes_supported=["BARREL"])
    wo = get_success_data(api_client.create_work_order(
        create_work_order_payload(customer_id=customer["id"], part_number="PN-D",
                                  alloy_code="AL5052"),
        make_customer_headers(customer["id"]),
    ))
    prepare_work_order(wo["id"])
    resp_del = api_client.delete_alloy_rule(rule["id"], CHEM)
    assert resp_del.status_code == 204
    resp = api_client.route_work_order(
        wo["id"],
        {"bath_id": bath["id"], "planned_duration_minutes": 40,
         "planned_current_density_a_dm2": 1.5},
        OP,
    )
    validate_error(resp, ApiErrorId.ERR_ALLOY_BATH_INCOMPATIBLE)


def test_prepare_masking_minutes_validation():
    """PRD §3.5: "When `requires_masking` is true, the request must supply
    `masking_minutes`; when masking is not required, the field must be absent — either
    violation is `ERR_MASKING_MINUTES_REQUIRED`. The minutes are recorded as
    `masking_minutes_actual` (zero when masking is not required) and
    `provisional_quote_cents` is recomputed with the real masking figure."

    Design: Corner/validations/prepare_masking_minutes_validation
    """
    customer = create_customer(company_name="Mask Co")
    wmk = get_success_data(api_client.create_work_order(
        create_work_order_payload(customer_id=customer["id"], part_number="PN-MK",
                                  requires_masking=True),
        make_customer_headers(customer["id"]),
    ))
    wnm = get_success_data(api_client.create_work_order(
        create_work_order_payload(customer_id=customer["id"], part_number="PN-NM"),
        make_customer_headers(customer["id"]),
    ))
    # Masking order without minutes.
    resp_mk = api_client.prepare_work_order(wmk["id"], {}, OP)
    validate_error(resp_mk, ApiErrorId.ERR_MASKING_MINUTES_REQUIRED)
    # Non-masking order with minutes.
    resp_nm = api_client.prepare_work_order(wnm["id"], {"masking_minutes": 10}, OP)
    validate_error(resp_nm, ApiErrorId.ERR_MASKING_MINUTES_REQUIRED)
    # Correct combinations succeed; the quote picks up the masking line 25 x 85 = 2125.
    prepared = get_success_data(
        api_client.prepare_work_order(wmk["id"], {"masking_minutes": 25}, OP)
    )
    assert prepared["status"] == "READY_FOR_ROUTING"
    # barrel 1200 + processing round(25 x 15.0 x 15) = 5625 + masking 2125 = 8950
    assert prepared["provisional_quote_cents"] == 8950, (
        f"Quote: expected 8950, got {prepared['provisional_quote_cents']}"
    )
    prepared_nm = get_success_data(api_client.prepare_work_order(wnm["id"], {}, OP))
    assert prepared_nm["status"] == "READY_FOR_ROUTING"


def test_route_process_and_mode_mismatch_rejected():
    """PRD §3.5: "the bath's `process_type` must equal the order's (else
    `ERR_PROCESS_TYPE_MISMATCH`), the order's `routing_mode` must appear in the bath's
    `routing_modes_supported` (else `ERR_ROUTING_MODE_NOT_SUPPORTED`)"

    Design: Corner/validations/route_process_and_mode_mismatch_rejected
    """
    customer = create_customer(company_name="Mismatch Co")
    create_compat_rule(alloy_code="AL6061", process_type="ANODIZE",
                       chemistry_family="SULFURIC", compatibility="COMPATIBLE")
    create_compat_rule(alloy_code="AL6061", process_type="ANODIZE",
                       chemistry_family="COPPER", compatibility="COMPATIBLE")
    bath_plate = create_titrated_bath(
        bath_code="PLT-MM", process_type="PLATE", chemistry_family="COPPER",
        routing_modes_supported=["BARREL"],
        titration_overrides={"titrant_volume_ml": 15.727, "titrant_normality": 0.1,
                             "sample_volume_ml": 10.0},
    )
    bath_rack_only = create_titrated_bath(
        bath_code="ANO-MM", process_type="ANODIZE", chemistry_family="SULFURIC",
        routing_modes_supported=["RACK"],
    )
    wo = get_success_data(api_client.create_work_order(
        create_work_order_payload(customer_id=customer["id"], part_number="PN-MM",
                                  routing_mode="BARREL"),
        make_customer_headers(customer["id"]),
    ))
    prepare_work_order(wo["id"])
    resp_pt = api_client.route_work_order(
        wo["id"],
        {"bath_id": bath_plate["id"], "planned_duration_minutes": 40,
         "planned_current_density_a_dm2": 1.5},
        OP,
    )
    validate_error(resp_pt, ApiErrorId.ERR_PROCESS_TYPE_MISMATCH)
    resp_rm = api_client.route_work_order(
        wo["id"],
        {"bath_id": bath_rack_only["id"], "planned_duration_minutes": 40,
         "planned_current_density_a_dm2": 1.5},
        OP,
    )
    validate_error(resp_rm, ApiErrorId.ERR_ROUTING_MODE_NOT_SUPPORTED)
    assert get_work_order(wo["id"])["status"] == "READY_FOR_ROUTING"


def test_route_fixture_mode_and_capacity_rejected():
    """PRD §3.5: "for a `RACK` order `fixture_id` is required, the fixture's
    `routing_mode` must be `RACK` (else `ERR_FIXTURE_ROUTING_MODE_MISMATCH`), and its
    `capacity_dm2` must be at least the order's `surface_area_total_dm2` (else
    `ERR_FIXTURE_CAPACITY_INSUFFICIENT`), while for a `BARREL` order `fixture_id` must
    be null (supplying one is the same mismatch error)"

    Design: Corner/validations/route_fixture_mode_and_capacity_rejected
    """
    customer = create_customer(company_name="Fixture Co")
    create_compat_rule()
    fb = create_fixture(fixture_code="BAR-1", routing_mode="BARREL", capacity_dm2=500,
                        purchase_cost_cents=40000, rated_uses=40)
    fs = create_fixture(fixture_code="RACK-S", routing_mode="RACK", capacity_dm2=20,
                        purchase_cost_cents=40000, rated_uses=40)
    fg = create_fixture(fixture_code="RACK-G", routing_mode="RACK", capacity_dm2=500,
                        purchase_cost_cents=120000, rated_uses=50)
    bath = create_titrated_bath(bath_code="ANO-FX", routing_modes_supported=["RACK"])
    wo = get_success_data(api_client.create_work_order(
        create_work_order_payload(customer_id=customer["id"], part_number="PN-FX",
                                  routing_mode="RACK"),
        make_customer_headers(customer["id"]),
    ))
    prepare_work_order(wo["id"])
    # BARREL fixture on a RACK order.
    resp_fm = api_client.route_work_order(
        wo["id"],
        {"bath_id": bath["id"], "fixture_id": fb["id"],
         "planned_duration_minutes": 40, "planned_current_density_a_dm2": 1.5},
        OP,
    )
    validate_error(resp_fm, ApiErrorId.ERR_FIXTURE_ROUTING_MODE_MISMATCH)
    # Capacity 20 < 25 dm2 total surface.
    resp_fc = api_client.route_work_order(
        wo["id"],
        {"bath_id": bath["id"], "fixture_id": fs["id"],
         "planned_duration_minutes": 40, "planned_current_density_a_dm2": 1.5},
        OP,
    )
    validate_error(resp_fc, ApiErrorId.ERR_FIXTURE_CAPACITY_INSUFFICIENT)
    # Adequate fixture routes.
    routed = get_success_data(api_client.route_work_order(
        wo["id"],
        {"bath_id": bath["id"], "fixture_id": fg["id"],
         "planned_duration_minutes": 40, "planned_current_density_a_dm2": 1.5},
        OP,
    ))
    assert routed["status"] == "ROUTED"
    assert routed["fixture_id"] == fg["id"]


def test_suspended_customer_blocked():
    """PRD §3.1: "When a customer is patched to `SUSPENDED`, new work orders for that
    customer are rejected while in-flight work orders are unaffected; patching back to
    `ACTIVE` restores intake."
    PRD §3.1: "a `SUSPENDED` customer hits `ERR_CUSTOMER_SUSPENDED` at work order
    creation, routing, load start, and shipping."

    Design: Corner/validations/suspended_customer_blocked
    """
    customer = create_customer(company_name="Susp Co")
    create_compat_rule()
    bath = create_titrated_bath(bath_code="ANO-SU2", routing_modes_supported=["BARREL"])
    wo = get_success_data(api_client.create_work_order(
        create_work_order_payload(customer_id=customer["id"], part_number="PN-SU"),
        make_customer_headers(customer["id"]),
    ))
    prepare_work_order(wo["id"])
    patched = get_success_data(
        api_client.patch_customer(customer["id"], {"status": "SUSPENDED"}, MGR)
    )
    assert patched["status"] == "SUSPENDED"
    # New work order creation is rejected.
    resp_new = api_client.create_work_order(
        create_work_order_payload(customer_id=customer["id"], part_number="PN-SU2",
                                  part_count=5, surface_area_dm2_per_part=2.0,
                                  thickness_spec_min_um=10.0, thickness_spec_max_um=14.0),
        MGR,
    )
    validate_error(resp_new, ApiErrorId.ERR_CUSTOMER_SUSPENDED)
    # Routing an existing prepared order is rejected.
    resp_route = api_client.route_work_order(
        wo["id"],
        {"bath_id": bath["id"], "planned_duration_minutes": 40,
         "planned_current_density_a_dm2": 1.5},
        OP,
    )
    validate_error(resp_route, ApiErrorId.ERR_CUSTOMER_SUSPENDED)


def test_route_nonexistent_bath_returns_404():
    """PRD §2.8: "Path identifiers are validated left-to-right — the first path id that
    does not correspond to an existing resource yields `ERR_NOT_FOUND` (HTTP 404)
    before any later segment is examined — followed by foreign-key references in the
    body (`bath_id`, `fixture_id`, `manifest_id`, `work_order_id`), which must also
    exist."

    Design: Corner/validations/route_nonexistent_bath_returns_404
    """
    customer = create_customer(company_name="Ghost Co")
    wo = get_success_data(api_client.create_work_order(
        create_work_order_payload(customer_id=customer["id"], part_number="PN-NB"),
        make_customer_headers(customer["id"]),
    ))
    prepare_work_order(wo["id"])
    resp = api_client.route_work_order(
        wo["id"],
        {"bath_id": NON_EXISTENT_UUID, "planned_duration_minutes": 40,
         "planned_current_density_a_dm2": 1.5},
        OP,
    )
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_nonexistent_bath_titration_returns_404():
    """PRD §2.9: "Requests that target nested resources validate path identifiers
    sequentially from left to right and are rejected with `ERR_NOT_FOUND` at the first
    identifier that does not resolve to an existing resource; the system never
    evaluates a child segment before its parent."

    Design: Corner/validations/nonexistent_bath_titration_returns_404
    """
    # The path id does not exist; the body is also missing required fields, but
    # existence (tier 4) outranks schema (tier 5).
    resp = api_client.create_titration(NON_EXISTENT_UUID, {}, CHEM)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
