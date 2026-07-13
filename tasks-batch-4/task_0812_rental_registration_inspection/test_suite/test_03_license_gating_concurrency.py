"""License payment gating (safety / fiscal / passed-inspection precedence), the
already-active idempotency guard, and optimistic-concurrency (OCC) rejection.
"""
from test_helpers import (
    ApiErrorId, TEST_USERS, get_success_data,
    validate_error, validate_success,
    make_landlord_headers,
    create_landlord, create_property, issue_license,
    setup_property_with_active_license, setup_property_with_pending_license,
    setup_landlord_inspector_property, run_periodic_with_fail_items,
    create_license_payload,
)

REGISTRAR = TEST_USERS["registrar_headers"]


def _pending_license_with_open_critical(api):
    """PASSED periodic (so ERR_NO_PASSED_INSPECTION cannot fire) + PENDING license +
    a later FAILED inspection leaving one OPEN CRITICAL violation (property SUSPENDED)."""
    ctx = setup_property_with_pending_license(api, unit_count=3, year_built=1980, run_inspection=True)
    get_success_data(api.set_clock("2026-06-05T09:00:00Z", REGISTRAR))
    run_periodic_with_fail_items(
        api, ctx,
        fail_items=[{"category": "LIFE_SAFETY", "code": "FIRE_EXIT", "severity": "CRITICAL"}],
        pass_items=[{"category": "HABITABILITY", "code": "HEAT"}],
        scheduled_date="2026-06-05T09:00:00Z",
    )
    return ctx


# --- Difficulty: priority_pair_validation_conflict / license_pay_safety_beats_fiscal

def test_pay_safety_beats_fiscal_returns_unsafe_habitability(api):
    """PRD §3.5: "Activation is gated by several checks: the license must currently be
    PENDING_PAYMENT; the property must have no open critical violations, otherwise payment is
    blocked with ERR_UNSAFE_HABITABILITY; the property must already have at least one PERIODIC
    inspection in status PASSED, otherwise payment is blocked with ERR_NO_PASSED_INSPECTION; and
    the tendered amount_cents must exactly equal the license's computed fee_cents, otherwise the
    payment is rejected with ERR_FEE_MISMATCH (HTTP 402)."

    Design: Difficulty/priority_pair_validation_conflict/license_pay_safety_beats_fiscal
    """
    ctx = _pending_license_with_open_critical(api)
    # amount_cents=1 is also wrong (fiscal), but safety is checked first per the gating order.
    resp = api.pay_license(ctx["license"]["id"], {"amount_cents": 1},
                           make_landlord_headers(ctx["landlord_id"]))
    validate_error(resp, ApiErrorId.ERR_UNSAFE_HABITABILITY.value)


def test_pay_safety_beats_fiscal_leaves_license_pending(api):
    """PRD §3.5: "A Landlord pays the fee to activate a PENDING_PAYMENT license, advancing it
    to ACTIVE."
    PRD §3.5: "the property must have no open critical violations, otherwise payment is blocked
    with ERR_UNSAFE_HABITABILITY".

    Design: Difficulty/priority_pair_validation_conflict/license_pay_safety_beats_fiscal
    """
    ctx = _pending_license_with_open_critical(api)
    api.pay_license(ctx["license"]["id"], {"amount_cents": 1},
                    make_landlord_headers(ctx["landlord_id"]))
    lic = get_success_data(api.list_property_licenses(ctx["property_id"], REGISTRAR))[0]
    assert lic["status"] == "PENDING_PAYMENT", "blocked pay leaves the license unchanged"


# --- Difficulty: cross_entity_state_dependency / license_pay_blocked_without_passed_inspection

def test_pay_blocked_without_passed_inspection(api):
    """PRD §3.5: "the property must already have at least one PERIODIC inspection in status
    PASSED, otherwise payment is blocked with ERR_NO_PASSED_INSPECTION".

    Design: Difficulty/cross_entity_state_dependency/license_pay_blocked_without_passed_inspection
    """
    ctx = setup_property_with_pending_license(api, unit_count=3, year_built=1980, run_inspection=False)
    resp = api.pay_license(ctx["license"]["id"], {"amount_cents": 30000},
                           make_landlord_headers(ctx["landlord_id"]))
    validate_error(resp, ApiErrorId.ERR_NO_PASSED_INSPECTION.value)


def test_pay_blocked_without_passed_inspection_leaves_pending(api):
    """PRD §3.5: "A Landlord pays the fee to activate a PENDING_PAYMENT license, advancing it
    to ACTIVE."
    PRD §3.5: "the property must already have at least one PERIODIC inspection in status
    PASSED, otherwise payment is blocked with ERR_NO_PASSED_INSPECTION".

    Design: Difficulty/cross_entity_state_dependency/license_pay_blocked_without_passed_inspection
    """
    ctx = setup_property_with_pending_license(api, unit_count=3, year_built=1980, run_inspection=False)
    api.pay_license(ctx["license"]["id"], {"amount_cents": 30000},
                    make_landlord_headers(ctx["landlord_id"]))
    lic = get_success_data(api.list_property_licenses(ctx["property_id"], REGISTRAR))[0]
    assert lic["status"] == "PENDING_PAYMENT"


# --- Corner: validations / pay_wrong_amount_without_critical_returns_fee_mismatch

def test_pay_wrong_amount_returns_fee_mismatch(api):
    """PRD §3.5: "the tendered amount_cents must exactly equal the license's computed fee_cents,
    otherwise the payment is rejected with ERR_FEE_MISMATCH (HTTP 402)."

    Design: Corner/validations/pay_wrong_amount_without_critical_returns_fee_mismatch
    """
    ctx = setup_property_with_pending_license(api, unit_count=3, year_built=1980, run_inspection=True)
    resp = api.pay_license(ctx["license"]["id"], {"amount_cents": 99999},
                           make_landlord_headers(ctx["landlord_id"]))
    validate_error(resp, ApiErrorId.ERR_FEE_MISMATCH.value)


# --- Corner: state_machines / pay_already_active_license_returns_invalid_state

def test_pay_already_active_license_returns_invalid_state(api):
    """PRD §3.5: "A Landlord pays the fee to activate a PENDING_PAYMENT license, advancing it
    to ACTIVE."
    PRD §2.10: "if a transition is attempted from a state that does not allow it, the request
    is rejected with ERR_INVALID_STATE."

    Design: Corner/state_machines/pay_already_active_license_returns_invalid_state
    """
    ctx = setup_property_with_active_license(api, unit_count=3, year_built=1980)
    resp = api.pay_license(ctx["license"]["id"], {"amount_cents": 30000},
                           make_landlord_headers(ctx["landlord_id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# --- Corner: cross_cutting / occ_license_create_stale_property_returns_412

def test_occ_license_create_stale_property_version(api):
    """PRD §2.7: "Issuing a new license against a property requires the request to carry
    expected_property_version, which must equal the target property's current version."
    PRD §2.7: "when expected_property_version does not match the property's current version, the
    request is rejected with ERR_STALE_VERSION (HTTP 412)."

    Design: Corner/cross_cutting/occ_license_create_stale_property_returns_412
    """
    landlord = create_landlord(api)
    get_success_data(api.set_clock("2026-06-01T09:00:00Z", REGISTRAR))
    prop = create_property(api, landlord["id"], unit_count=3, year_built=1980)
    stale_version = prop["version"]
    # First issuance succeeds and bumps Property.version.
    validate_success(api.create_license(create_license_payload(prop["id"], stale_version), REGISTRAR),
                     expected_status=201)
    # Second issuance still carrying the pre-issue version is stale.
    resp = api.create_license(create_license_payload(prop["id"], stale_version), REGISTRAR)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)


# --- Corner: cross_cutting / occ_license_renew_stale_license_returns_412

def test_occ_license_renew_stale_license_version(api):
    """PRD §2.7: "Renewing a license requires the request to carry expected_license_version,
    which must equal the target license's current version. A prior renewal, or a cascaded
    suspension of the license, advances the license's version; a renewal that still carries the
    earlier value is stale and is rejected with ERR_STALE_VERSION (HTTP 412)."

    Design: Corner/cross_cutting/occ_license_renew_stale_license_returns_412
    """
    ctx = setup_property_with_active_license(api, unit_count=3, year_built=1980)
    stale_version = ctx["license"]["version"]
    # First renewal succeeds and advances RentalLicense.version.
    validate_success(api.renew_license(ctx["license"]["id"], {"expected_license_version": stale_version},
                                       make_landlord_headers(ctx["landlord_id"])))
    # Second renewal still carrying the pre-renew version is stale.
    resp = api.renew_license(ctx["license"]["id"], {"expected_license_version": stale_version},
                             make_landlord_headers(ctx["landlord_id"]))
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)
