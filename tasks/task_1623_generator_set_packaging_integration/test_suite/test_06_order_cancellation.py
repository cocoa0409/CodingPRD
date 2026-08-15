"""Order cancellation: 3-hop cascade, restocking refunds, credit round trip (PRD §3.8)."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_certificate,
    create_configuration,
    create_service_contract,
    get_success_data,
    setup_accepted_test,
    setup_approved_permit,
    setup_authorized_order,
    setup_booked_shipment,
    setup_commissioned_order,
    setup_locked_configuration,
    setup_submitted_permit,
    validate_error,
    validate_success,
)
from test_helpers.api_client import api_client
from test_helpers.factories import create_permit_case_payload

ADMIN = TEST_USERS["platform_admin_headers"]
SALES = TEST_USERS["sales_engineer_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]
APP_ENG = TEST_USERS["application_engineer_headers"]
LOGISTICS = TEST_USERS["logistics_coordinator_headers"]


# ---------------------------------------------------------------------------
# Difficulty/transitive_cascade/order_cancel_depth3_cascade
# ---------------------------------------------------------------------------

def test_order_cancel_depth3_cascade(api):
    """PRD §3.8: "The cascade then runs in hops. Hop 1 cancels every
    configuration of the order still in `DRAFT`, `LOCKED`, or `RELEASED`. Hop 2
    follows from hop 1: each cancelled configuration's permit case in `DRAFT`,
    `SUBMITTED`, or `CORRECTION_REQUESTED` moves to `WITHDRAWN` — and, for a
    configuration with no live permit at all, that configuration's certificate
    in `APP_DRAFT`, `SUBMITTED`, or `REJECTED` is voided directly at this hop.
    Hop 3 follows from hop 2: each permit withdrawal voids that configuration's
    certificate in `APP_DRAFT`, `SUBMITTED`, or `REJECTED`, moving it to
    `VOIDED`."

    A LOCKED configuration with a SUBMITTED permit and a SUBMITTED certificate
    walks all three hops.

    Design: Difficulty/transitive_cascade/order_cancel_depth3_cascade
    """
    ctx = setup_submitted_permit()
    cert = create_certificate(ctx["order"]["id"], ctx["configuration"]["id"])
    cert = get_success_data(api_client.submit_emissions_certificate(cert["id"], {}, COMPLIANCE))
    assert cert["status"] == "SUBMITTED"
    contract = create_service_contract(
        ctx["order"]["id"], pricing_variant="FLAT_RISK_PREMIUM",
        term_years=2, nameplate_kw=500,
    )
    assert contract["status"] == "QUOTED"

    cancelled = validate_success(api_client.cancel_order(ctx["order"]["id"], SALES))
    assert cancelled["build_status"] == "CANCELLED"

    config = get_success_data(api_client.get_configuration(ctx["configuration"]["id"], APP_ENG))
    assert config["status"] == "CANCELLED"
    permit = get_success_data(api_client.get_permit_case(ctx["permit"]["id"], COMPLIANCE))
    assert permit["status"] == "WITHDRAWN"
    cert = get_success_data(api_client.get_emissions_certificate(cert["id"], COMPLIANCE))
    assert cert["status"] == "VOIDED"
    contract = get_success_data(api_client.get_service_contract(contract["id"], SALES))
    assert contract["status"] == "CANCELLED"


def test_order_cancel_refund_and_credit_release(api):
    """PRD §3.8: "If the order's `commercial_status` is `AUTHORIZED` or
    `INVOICED`, a refund is computed: the restocking fee is zero when the order
    was still at `SPEC` or `SIZING` at cancel time, and otherwise it is 10
    percent of `committed_amount_cents` rounded half-up to whole cents;
    `refunded_amount_cents` is the committed amount minus that fee, the fee
    itself is recorded as `restocking_fee_cents`, `commercial_status` becomes
    `REFUNDED`, the customer's `credit_utilized_cents` falls by
    `committed_amount_cents`, and `committed_amount_cents` drops to 0."

    Cancel at PERMITTING (past SIZING): restocking 10% of 60000000 = 6000000,
    refund 54000000, utilization returns to 0.

    Design: Difficulty/transitive_cascade/order_cancel_depth3_cascade
    """
    ctx = setup_submitted_permit()
    customer_before = get_success_data(api_client.get_customer(ctx["customer"]["id"], SALES))
    assert customer_before["credit_utilized_cents"] == 60000000

    cancelled = validate_success(api_client.cancel_order(ctx["order"]["id"], SALES))
    assert cancelled["restocking_fee_cents"] == 6000000
    assert cancelled["refunded_amount_cents"] == 54000000
    assert cancelled["commercial_status"] == "REFUNDED"
    assert cancelled["committed_amount_cents"] == 0
    customer_after = get_success_data(api_client.get_customer(ctx["customer"]["id"], SALES))
    assert customer_after["credit_utilized_cents"] == 0


# ---------------------------------------------------------------------------
# Difficulty/transitive_cascade/test_fail_regress_releases_shipment
# ---------------------------------------------------------------------------

def test_test_fail_regress_releases_shipment(api):
    """PRD §3.7: "A `FAIL` has teeth. The order's `build_status` regresses —
    `TESTING` → `CONFIGURING`, or `READY_TO_SHIP` → `CONFIGURING` if the failure
    came from a post-acceptance retest — incrementing the order's `version`, and
    every `BOOKED` shipment for the order is released, returning its crane
    occupancy to the slot exactly as §3.8 describes."

    At READY_TO_SHIP with a BOOKED shipment (slot free 5.5), a failing retest
    regresses the build to CONFIGURING, releases the shipment, and returns the
    slot to free 8.0 / reserved 0.

    Design: Difficulty/transitive_cascade/test_fail_regress_releases_shipment
    """
    from test_helpers import create_factory_test, make_test_engineer_headers
    ctx = setup_booked_shipment(
        slot_overrides={"service_date": "2026-09-10"},
        shipment_overrides={"lift_start_hour": 8, "lift_hours": 2.0},
    )
    slot_before = get_success_data(api_client.get_crane_slot(ctx["crane_slot"]["id"], LOGISTICS))
    assert slot_before["free_hours"] == pytest.approx(5.5, abs=1e-6)

    # Post-acceptance retest (the config is RELEASED; the order is READY_TO_SHIP).
    # PRD §3.7: creation has no build_status gate — the ISSUED certificate is the
    # gate — so a fresh test can be scheduled while the order sits READY_TO_SHIP.
    retest = create_factory_test(
        ctx["order"]["id"], ctx["configuration"]["id"], ctx["bay"]["id"],
        service_date="2026-08-06",
    )
    recorder = make_test_engineer_headers("eng-rec-20")
    get_success_data(api_client.start_factory_test(retest["id"], recorder))
    recorded = validate_success(api_client.record_factory_test(
        retest["id"],
        {"readings": [{"kw": 100, "hours": 1.0, "power_factor": 0.70}]},
        recorder,
    ))
    assert recorded["verdict"] == "FAIL"

    order = get_success_data(api_client.get_order(ctx["order"]["id"], SALES))
    assert order["build_status"] == "CONFIGURING"
    shipment = get_success_data(api_client.get_shipment(ctx["shipment"]["id"], LOGISTICS))
    assert shipment["status"] == "RELEASED"
    slot_after = get_success_data(api_client.get_crane_slot(ctx["crane_slot"]["id"], LOGISTICS))
    assert slot_after["free_hours"] == pytest.approx(8.0, abs=1e-6)
    assert slot_after["reserved_hours"] == pytest.approx(0.0, abs=1e-6)


def test_test_fail_in_testing_releases_booked_shipment(api):
    """PRD §3.7: "A `FAIL` has teeth. The order's `build_status` regresses —
    `TESTING` → `CONFIGURING`, or `READY_TO_SHIP` → `CONFIGURING` if the failure
    came from a post-acceptance retest — incrementing the order's `version`, and
    every `BOOKED` shipment for the order is released, returning its crane
    occupancy to the slot exactly as §3.8 describes."

    A FAIL recorded from a post-acceptance retest while the order is
    READY_TO_SHIP releases the BOOKED shipment; the invariant `free_hours` plus
    `reserved_hours` always equals `window_end_hour` minus `window_start_hour`
    is re-verified after the compensating release.

    Design: Difficulty/transitive_cascade/test_fail_regress_releases_shipment
    """
    from test_helpers import create_factory_test, make_test_engineer_headers, assert_crane_slot_invariant
    ctx = setup_booked_shipment(
        slot_overrides={"service_date": "2026-09-10"},
        shipment_overrides={"lift_start_hour": 8, "lift_hours": 2.0},
    )
    retest = create_factory_test(
        ctx["order"]["id"], ctx["configuration"]["id"], ctx["bay"]["id"],
        service_date="2026-08-07",
    )
    recorder = make_test_engineer_headers("eng-rec-21")
    get_success_data(api_client.start_factory_test(retest["id"], recorder))
    validate_success(api_client.record_factory_test(
        retest["id"],
        {"readings": [{"kw": 100, "hours": 1.0, "power_factor": 0.70}]},
        recorder,
    ))
    slot_after = get_success_data(api_client.get_crane_slot(ctx["crane_slot"]["id"], LOGISTICS))
    assert_crane_slot_invariant(slot_after)
    assert slot_after["free_hours"] == pytest.approx(8.0, abs=1e-6)


# ---------------------------------------------------------------------------
# Difficulty/non_linear_state_machine/package_order_parallel_dims_with_revert
# ---------------------------------------------------------------------------

def test_build_regression_leaves_commercial_dimension_untouched(api):
    """PRD §2.6: "A `PackageOrder` does not have one status; it has two that
    evolve independently on the same row."
    PRD §3.7: "A `FAIL` has teeth. The order's `build_status` regresses —
    `TESTING` → `CONFIGURING`, or `READY_TO_SHIP` → `CONFIGURING` if the failure
    came from a post-acceptance retest..."

    After the retest FAIL: build_status regresses READY_TO_SHIP -> CONFIGURING
    while commercial_status stays AUTHORIZED (no delivery ever happened).

    Design: Difficulty/non_linear_state_machine/package_order_parallel_dims_with_revert
    """
    from test_helpers import create_factory_test, make_test_engineer_headers
    ctx = setup_booked_shipment(
        slot_overrides={"service_date": "2026-09-10"},
    )
    order = get_success_data(api_client.get_order(ctx["order"]["id"], SALES))
    assert order["build_status"] == "READY_TO_SHIP"
    assert order["commercial_status"] == "AUTHORIZED"

    retest = create_factory_test(
        ctx["order"]["id"], ctx["configuration"]["id"], ctx["bay"]["id"],
        service_date="2026-08-06",
    )
    recorder = make_test_engineer_headers("eng-rec-30")
    get_success_data(api_client.start_factory_test(retest["id"], recorder))
    validate_success(api_client.record_factory_test(
        retest["id"],
        {"readings": [{"kw": 100, "hours": 1.0, "power_factor": 0.70}]},
        recorder,
    ))
    order = get_success_data(api_client.get_order(ctx["order"]["id"], SALES))
    assert order["build_status"] == "CONFIGURING"
    assert order["commercial_status"] == "AUTHORIZED"


def test_acceptance_advances_build_and_releases_configuration(api):
    """PRD §3.7: "Acceptance stamps `accepted_by_user_id`, moves the test to the
    terminal `ACCEPTED` state, and cascades outward: the order's `build_status`
    goes `TESTING` → `READY_TO_SHIP` with its `version` incremented, and the
    configuration under test goes `LOCKED` → `RELEASED`."

    The two dimensions evolve independently: the commercial posture stays
    AUTHORIZED through test acceptance.

    Design: Difficulty/non_linear_state_machine/package_order_parallel_dims_with_revert
    """
    ctx = setup_accepted_test()
    assert ctx["test"]["status"] == "ACCEPTED"
    assert ctx["order"]["build_status"] == "READY_TO_SHIP"
    assert ctx["order"]["commercial_status"] == "AUTHORIZED"
    config = get_success_data(api_client.get_configuration(ctx["configuration"]["id"], APP_ENG))
    assert config["status"] == "RELEASED"


# ---------------------------------------------------------------------------
# Difficulty/compensating_invariant/customer_credit_authorize_cancel_round_trip
# ---------------------------------------------------------------------------

def test_credit_utilization_authorize_cancel_round_trip(api):
    """PRD §3.1: "An account's `status` starts `ACTIVE` and may be set
    `SUSPENDED`; its `credit_utilized_cents` starts at 0 and thereafter tracks,
    exactly and at all times, the sum of `committed_amount_cents` across that
    customer's orders whose `commercial_status` is either `AUTHORIZED` or
    `INVOICED`. Authorization adds to this figure and cancellation subtracts it
    back out, so an authorize-then-cancel round trip returns utilization to its
    pre-authorize value."

    Cancel at CONFIGURING (past SIZING): restocking 10% of 60000000 = 6000000,
    refund 54000000, utilization returns to exactly 0.

    Design: Difficulty/compensating_invariant/customer_credit_authorize_cancel_round_trip
    """
    ctx = setup_locked_configuration()
    customer = ctx["customer"]
    before = get_success_data(api_client.get_customer(customer["id"], SALES))
    assert before["credit_utilized_cents"] == 60000000

    cancelled = validate_success(api_client.cancel_order(ctx["order"]["id"], SALES))
    assert cancelled["restocking_fee_cents"] == 6000000
    assert cancelled["refunded_amount_cents"] == 54000000
    assert cancelled["commercial_status"] == "REFUNDED"

    after = get_success_data(api_client.get_customer(customer["id"], SALES))
    assert after["credit_utilized_cents"] == 0


def test_cancel_at_sizing_charges_no_restocking(api):
    """PRD §3.8: "If the order's `commercial_status` is `AUTHORIZED` or
    `INVOICED`, a refund is computed: the restocking fee is zero when the order
    was still at `SPEC` or `SIZING` at cancel time, and otherwise it is 10
    percent of `committed_amount_cents` rounded half-up to whole cents..."

    Cancel while build is SIZING (study approved, no configuration): restocking
    0, refund equals the full committed amount, utilization back to 0.

    Design: Difficulty/compensating_invariant/customer_credit_authorize_cancel_round_trip
    """
    ctx = setup_authorized_order(amount_cents=40000000, freight_charge_cents=0)
    assert ctx["order"]["build_status"] == "SIZING"
    cancelled = validate_success(api_client.cancel_order(ctx["order"]["id"], SALES))
    assert cancelled["restocking_fee_cents"] == 0
    assert cancelled["refunded_amount_cents"] == 40000000
    assert cancelled["commercial_status"] == "REFUNDED"
    customer = get_success_data(api_client.get_customer(ctx["customer"]["id"], SALES))
    assert customer["credit_utilized_cents"] == 0


# ---------------------------------------------------------------------------
# Corner/cross_cutting_layers/cascade_partial_state_only_non_terminal_children
# ---------------------------------------------------------------------------

def test_cancel_leaves_terminal_children_untouched(api):
    """PRD §3.8: "Hop 1 cancels every configuration of the order still in
    `DRAFT`, `LOCKED`, or `RELEASED`. Hop 2 follows from hop 1: each cancelled
    configuration's permit case in `DRAFT`, `SUBMITTED`, or
    `CORRECTION_REQUESTED` moves to `WITHDRAWN` — and, for a configuration with
    no live permit at all, that configuration's certificate in `APP_DRAFT`,
    `SUBMITTED`, or `REJECTED` is voided directly at this hop. Hop 3 follows
    from hop 2: each permit withdrawal voids that configuration's certificate in
    `APP_DRAFT`, `SUBMITTED`, or `REJECTED`, moving it to `VOIDED`."

    An APPROVED permit (terminal) and an ISSUED certificate (terminal) survive
    the cascade; a second configuration's SUBMITTED certificate (no permit) is
    voided directly.

    Design: Corner/cross_cutting_layers/cascade_partial_state_only_non_terminal_children
    """
    ctx = setup_approved_permit()
    cert_a = create_certificate(ctx["order"]["id"], ctx["configuration"]["id"])
    cert_a = get_success_data(api_client.submit_emissions_certificate(cert_a["id"], {}, COMPLIANCE))
    cert_a = get_success_data(api_client.issue_emissions_certificate(cert_a["id"], ADMIN))
    assert cert_a["status"] == "ISSUED"

    # Second configuration on the same approved study, locked, with its own SUBMITTED cert.
    cfg_b = create_configuration(
        ctx["order"]["id"], ctx["study"]["id"],
        enclosure_type="WEATHERPROOF", enclosure_price_cents=3000000,
        fuel_tank_gallons=500,
    )
    cfg_b = get_success_data(api_client.lock_configuration(cfg_b["id"], APP_ENG))
    cert_b = create_certificate(ctx["order"]["id"], cfg_b["id"])
    cert_b = get_success_data(api_client.submit_emissions_certificate(cert_b["id"], {}, COMPLIANCE))
    assert cert_b["status"] == "SUBMITTED"

    validate_success(api_client.cancel_order(ctx["order"]["id"], SALES))

    cfg_a_now = get_success_data(api_client.get_configuration(ctx["configuration"]["id"], APP_ENG))
    cfg_b_now = get_success_data(api_client.get_configuration(cfg_b["id"], APP_ENG))
    assert cfg_a_now["status"] == "CANCELLED"
    assert cfg_b_now["status"] == "CANCELLED"
    permit_now = get_success_data(api_client.get_permit_case(ctx["permit"]["id"], COMPLIANCE))
    assert permit_now["status"] == "APPROVED"
    cert_a_now = get_success_data(api_client.get_emissions_certificate(cert_a["id"], COMPLIANCE))
    assert cert_a_now["status"] == "ISSUED"
    cert_b_now = get_success_data(api_client.get_emissions_certificate(cert_b["id"], COMPLIANCE))
    assert cert_b_now["status"] == "VOIDED"
    order_now = get_success_data(api_client.get_order(ctx["order"]["id"], SALES))
    assert order_now["build_status"] == "CANCELLED"


# ---------------------------------------------------------------------------
# Corner/state_machines/order_cancel_terminal_lockdown_after_commissioned
# ---------------------------------------------------------------------------

def test_cancel_after_commissioned_rejected(api):
    """PRD §3.8: "Cancelling the order itself is the workflow's wrecking ball,
    swung by a `SalesEngineer`. The one gate is that `build_status` must not
    already be `COMMISSIONED` or `CANCELLED` — otherwise
    `ERR_INVALID_BUILD_STATE`."

    Design: Corner/state_machines/order_cancel_terminal_lockdown_after_commissioned
    """
    ctx = setup_commissioned_order()
    assert ctx["order"]["build_status"] == "COMMISSIONED"
    resp = api_client.cancel_order(ctx["order"]["id"], SALES)
    validate_error(resp, ApiErrorId.ERR_INVALID_BUILD_STATE)
    order = get_success_data(api_client.get_order(ctx["order"]["id"], SALES))
    assert order["build_status"] == "COMMISSIONED"


# ---------------------------------------------------------------------------
# Corner/consistency_model/immediate_visibility_of_cascade_in_same_request
# ---------------------------------------------------------------------------

def test_cancel_response_carries_final_state_immediately(api):
    """PRD §3.8: "If the order's `commercial_status` is `AUTHORIZED` or
    `INVOICED`, a refund is computed: ... `refunded_amount_cents` is the
    committed amount minus that fee, the fee itself is recorded as
    `restocking_fee_cents`, `commercial_status` becomes `REFUNDED`, the
    customer's `credit_utilized_cents` falls by `committed_amount_cents`, and
    `committed_amount_cents` drops to 0."

    The cancel response body itself carries the final refund figures, and a
    subsequent customer GET shows utilization already at 0 — no eventual lag.

    Design: Corner/consistency_model/immediate_visibility_of_cascade_in_same_request
    """
    ctx = setup_authorized_order(amount_cents=40000000, freight_charge_cents=0)
    assert ctx["order"]["build_status"] == "SIZING"
    cancelled = validate_success(api_client.cancel_order(ctx["order"]["id"], SALES))
    assert cancelled["build_status"] == "CANCELLED"
    assert cancelled["commercial_status"] == "REFUNDED"
    assert cancelled["refunded_amount_cents"] == 40000000
    assert cancelled["restocking_fee_cents"] == 0
    customer = get_success_data(api_client.get_customer(ctx["customer"]["id"], SALES))
    assert customer["credit_utilized_cents"] == 0
