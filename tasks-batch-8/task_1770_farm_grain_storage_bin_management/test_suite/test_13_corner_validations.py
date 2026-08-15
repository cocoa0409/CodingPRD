"""Corner queue / validations section — existence-first 404, missing-auth
401, temporal window violations, fiscal/capacity violations, crop
consistency, conditional fields, cert/atmosphere checks, aggregate
insufficiency, loss-outside-period."""
import pytest

from test_helpers import (
    get_success_data, validate_success, validate_error,
    ApiErrorId, NON_EXISTENT_UUID,
    TEST_USERS, make_applicator_headers, make_site_manager_headers,
    make_safety_officer_headers,
    create_bin, create_lot, create_contract, create_applicator, create_policy,
    set_clock,
    setup_bin_with_lot, setup_dispatched_loadout,
    get_lot, get_first_alert_for_bin, create_hotspot_reading,
)
from test_helpers.api_client import api_client
from test_helpers.factories import (
    create_bin_payload, create_lot_payload, create_loadout_payload,
    create_fumigation_payload, create_permit_payload, create_policy_payload,
    create_claim_payload, deliver_payload,
)

SM = TEST_USERS["site_manager_headers"]
FO = TEST_USERS["farm_owner_headers"]


def test_existence_checked_before_state_returns_404(api):
    """PRD section 2.9: "When a request must resolve identifiers, the
    server validates path identifiers first, from left to right, and then
    foreign-key identifiers in the request body; the first identifier that
    does not resolve to an existing resource yields `ERR_NOT_FOUND` (HTTP
    404)."

    Dispatching a nonexistent loadout id yields 404, never a state error.

    Design: Corner/validations/existence_checked_before_state_returns_404
    """
    resp = api_client.dispatch_loadout(NON_EXISTENT_UUID, SM)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND, expected_status=404)


def test_missing_auth_header_returns_401(api):
    """PRD section 2.1: "A request missing either header, or presenting a
    role value outside that set, is rejected with `ERR_UNAUTHENTICATED`
    (HTTP 401)."

    Design: Corner/validations/missing_auth_header_returns_401
    """
    resp = api_client.create_bin(
        create_bin_payload(name="BIN-N"), headers={})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401)


def test_outside_delivery_window_rejected(api):
    """PRD section 3.5: "The load-out window must lie entirely within the
    contract's delivery window — `window_start` at or before
    `scheduled_start`, and `scheduled_end` at or before `window_end` —
    otherwise `ERR_OUTSIDE_DELIVERY_WINDOW`."

    A window ending 2027-01-06 against a contract window ending 2026-12-31
    is rejected.

    Design: Corner/validations/outside_delivery_window_rejected
    """
    b, lot = setup_bin_with_lot(bin_name="BIN-OW", original_bu=500.00)
    con = create_contract(contracted_bu=2000.00)
    resp = api_client.create_loadout(create_loadout_payload(
        con["id"], b["id"], con["version"], planned_bu=100.00,
        scheduled_start="2027-01-05T08:00:00Z",
        scheduled_end="2027-01-06T12:00:00Z",
    ), SM)
    validate_error(resp, ApiErrorId.ERR_OUTSIDE_DELIVERY_WINDOW,
                   expected_status=409)


def test_contract_remaining_exceeded_rejected(api):
    """PRD section 3.5: "And the contract must have room: `planned_bu` must
    not exceed `contracted_bu` minus `committed_bu` minus `delivered_bu`
    (otherwise `ERR_CONTRACT_REMAINING_EXCEEDED`)."

    planned 600.00 against remaining 500.00 -> 409; planned 500.00 (exact
    fit) -> 201.

    Design: Corner/validations/contract_remaining_exceeded_rejected
    """
    b, lot = setup_bin_with_lot(bin_name="BIN-RE", original_bu=800.00)
    con = create_contract(contracted_bu=500.00)
    bad = api_client.create_loadout(create_loadout_payload(
        con["id"], b["id"], con["version"], planned_bu=600.00), SM)
    validate_error(bad, ApiErrorId.ERR_CONTRACT_REMAINING_EXCEEDED,
                   expected_status=409)
    ok = api_client.create_loadout(create_loadout_payload(
        con["id"], b["id"], con["version"], planned_bu=500.00), SM)
    validate_success(ok, expected_status=201)


def test_lots_insufficient_on_confirm_rejected(api):
    """PRD section 3.6: "When the eligible bushels cannot cover the
    load-out's `settled_net_bu`, the confirmation is rejected with
    `ERR_LOTS_INSUFFICIENT` and nothing is debited."

    Aggregate 100.00 eligible vs settled_net 150.00; lot unchanged.

    Design: Corner/validations/lots_insufficient_on_confirm_rejected
    """
    b, lot, con, lo = setup_dispatched_loadout(
        bin_name="BIN-LI", original_bu=100.00, contracted_bu=2000.00,
        planned_bu=150.00,
    )
    get_success_data(api_client.deliver_loadout(lo["id"], deliver_payload(
        delivered_at="2026-08-10T10:00:00Z",
        scale_tickets=[
            {"ticket_no": "T1", "gross_bu": 150.00, "moisture_pct": 15.0},
        ],
    ), SM))
    resp = api_client.confirm_settlement(lo["id"], SM)
    validate_error(resp, ApiErrorId.ERR_LOTS_INSUFFICIENT, expected_status=409)
    assert get_lot(lot["id"])["current_bu"] == pytest.approx(100.00, abs=1e-9)


def test_crop_mix_rejected_on_lot_fill(api):
    """PRD section 3.1: "the lot's crop must equal the bin's crop
    (otherwise `ERR_CROP_MIX`)."

    SOYBEAN lot into a CORN bin -> 409 ERR_CROP_MIX.

    Design: Corner/validations/crop_mix_rejected_on_lot_fill
    """
    b = create_bin(name="BIN-CM")
    resp = api_client.create_lot(create_lot_payload(
        b["id"], crop="SOYBEAN", original_bu=100.00, fill_moisture_pct=13.0,
        fill_basis_cents=-30, reference_price_cents_per_bu=1000), SM)
    validate_error(resp, ApiErrorId.ERR_CROP_MIX, expected_status=409)


def test_bin_capacity_exact_fit_boundary(api):
    """PRD section 3.1: "the fill must fit — the sum of `current_bu` over the bin's existing lots plus the new lot's `original_bu` must not exceed `capacity_bu`, with an exact fit permitted (otherwise `ERR_BIN_CAPACITY_EXCEEDED`)".

    600 + 400 == 1000 (exact) is admitted; one more lot of 0.01 is
    rejected.

    Design: Corner/validations/bin_capacity_exact_fit_boundary
    """
    b = create_bin(name="BIN-CAP", capacity_bu=1000.00)
    create_lot(b["id"], original_bu=600.00)
    ok = api_client.create_lot(create_lot_payload(
        b["id"], original_bu=400.00), SM)
    validate_success(ok, expected_status=201)
    over = api_client.create_lot(create_lot_payload(
        b["id"], original_bu=0.01), SM)
    validate_error(over, ApiErrorId.ERR_BIN_CAPACITY_EXCEEDED,
                   expected_status=409)


def test_applicator_cert_expired_rejected(api):
    """PRD section 3.3: "The applicator's certification must cover the
    work — `cert_expires_at` must be at or after `application_start`,
    otherwise `ERR_APPLICATOR_CERT_EXPIRED`".

    cert_expires_at 2026-07-01 precedes application_start 2026-08-01.

    Design: Corner/validations/applicator_cert_expired_rejected
    """
    b = create_bin(name="BIN-CE")
    app = create_applicator(name="Exp Eddy", license_no="LIC-X",
                            cert_expires_at="2026-07-01T00:00:00Z")
    resp = api_client.create_fumigation(create_fumigation_payload(
        b["id"], app["id"]), make_applicator_headers(app["id"]))
    validate_error(resp, ApiErrorId.ERR_APPLICATOR_CERT_EXPIRED,
                   expected_status=409)


def test_atmosphere_unsafe_rejected_on_approve(api):
    """PRD section 3.4: "only then are the physical preconditions
    evaluated — both `atmosphere_test_passed` and `loto_confirmed` must be
    true, otherwise `ERR_ATMOSPHERE_UNSAFE`."

    atmosphere_test_passed=false (loto true) fails the physical
    precondition; the permit stays REQUESTED.

    Design: Corner/validations/atmosphere_unsafe_rejected_on_approve
    """
    b = create_bin(name="BIN-AU")
    permit = get_success_data(api_client.create_permit(create_permit_payload(
        b["id"], atmosphere_test_passed=False, loto_confirmed=True),
        make_site_manager_headers("mgr-1")))
    resp = api_client.approve_permit(
        permit["id"], make_safety_officer_headers("so-1"))
    validate_error(resp, ApiErrorId.ERR_ATMOSPHERE_UNSAFE, expected_status=409)
    assert get_success_data(api_client.get_permit(permit["id"], SM))[
        "status"] == "REQUESTED"


def test_loss_outside_policy_period_rejected(api):
    """PRD section 3.8: "the alert's `closed_at` must fall within the
    policy's coverage period, both bounds inclusive (otherwise
    `ERR_LOSS_OUTSIDE_PERIOD`)".

    Alert closed 2026-08-05 against a policy period ending 2026-07-31.

    Design: Corner/validations/loss_outside_policy_period_rejected
    """
    b = create_bin(name="BIN-LP")
    create_hotspot_reading(b["id"], recorded_at="2026-08-05T10:00:00Z")
    alert = get_first_alert_for_bin(b["id"])
    set_clock("2026-08-05T12:00:00Z")
    get_success_data(api_client.close_alert(
        alert["id"], {"outcome": "CONFIRMED_LOSS", "loss_bu": 10.00}, SM))
    pol = create_policy(period_start="2026-07-01T00:00:00Z",
                        period_end="2026-07-31T23:59:59Z")
    resp = api_client.create_claim(
        create_claim_payload(pol["id"], alert["id"]), SM)
    validate_error(resp, ApiErrorId.ERR_LOSS_OUTSIDE_PERIOD,
                   expected_status=409)


def test_close_resolved_with_loss_bu_rejected(api):
    """PRD section 3.2: "a closure with outcome `CONFIRMED_LOSS` must carry
    a `loss_bu` strictly greater than zero (2 decimal places), and a
    closure with outcome `RESOLVED` must not carry `loss_bu` at all;
    violations are rejected with `ERR_VALIDATION`."

    RESOLVED with loss_bu present -> 400 ERR_VALIDATION; alert stays OPEN.

    Design: Corner/validations/close_resolved_with_loss_bu_rejected
    """
    b = create_bin(name="BIN-RL")
    create_hotspot_reading(b["id"], recorded_at="2026-08-05T10:00:00Z")
    alert = get_first_alert_for_bin(b["id"])
    resp = api_client.close_alert(
        alert["id"], {"outcome": "RESOLVED", "loss_bu": 5.00}, SM)
    validate_error(resp, ApiErrorId.ERR_VALIDATION, expected_status=400)
    after = get_success_data(api_client.get_alert(alert["id"], SM))
    assert after["status"] == "OPEN"
