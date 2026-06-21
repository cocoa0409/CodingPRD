"""Provider registration, provider lifecycle, and promotional-plan onboarding.

Queue B (Corner) — sections: entities, state_machines.
"""
import pytest
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_paginated,
    assert_provider,
    create_provider_payload,
    TEST_USERS,
    NON_EXISTENT_UUID,
    create_enrolled_provider,
    set_clock,
    setup_provider_plan_promotion,
    authorize_purchase,
    create_active_account,
)

ADMIN = TEST_USERS["admin_headers"]


def test_create_provider_returns_201_with_pending_status(api):
    """PRD §3.1: "A newly registered provider begins with its `status` field set to
    `PENDING`, and with its computed `monthly_settled_volume_cents` and
    `settled_net_cents` both at zero."
    PRD §2.4: "The `version` begins at 1 and increments by one on every mutation of
    that resource".

    Design: Corner/entities/create_provider_returns_201_with_pending_status
    """
    res = api.create_provider(
        create_provider_payload(legal_name="New Clinic", specialty="DENTAL",
                                tax_id="TX-NEW-1", base_merchant_discount_rate=0.08),
        ADMIN)
    provider = validate_success(res, 201)
    assert_provider(provider)
    assert provider["status"] == "PENDING"
    assert provider["monthly_settled_volume_cents"] == 0
    assert provider["settled_net_cents"] == 0
    assert provider["version"] == 1


def test_create_provider_missing_specialty_returns_invalid_request(api):
    """PRD §2.8: "(5) presence, type, and enum validity of required body fields
    (`ERR_INVALID_REQUEST`)".
    PRD §3.1: "A `PlatformAdmin` registers a clinic by supplying its `legal_name`, its
    `specialty` ... its `tax_id`, and its floor merchant discount fraction
    `base_merchant_discount_rate`."

    Design: Corner/entities/create_provider_missing_specialty_returns_invalid_request
    """
    payload = create_provider_payload(legal_name="No Spec", tax_id="TX-NS-1",
                                      base_merchant_discount_rate=0.08)
    del payload["specialty"]
    res = api.create_provider(payload, ADMIN)
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=400)


def test_create_provider_invalid_specialty_enum_returns_invalid_request(api):
    """PRD §2.8: "(5) presence, type, and enum validity of required body fields
    (`ERR_INVALID_REQUEST`)".
    PRD §3.1: "its `specialty` (one of `DENTAL`, `VISION`, `VETERINARY`, `DERMATOLOGY`,
    or `GENERAL`)".

    Design: Corner/entities/create_provider_invalid_specialty_enum_returns_invalid_request
    """
    res = api.create_provider(
        create_provider_payload(legal_name="Bad Enum", specialty="CARDIOLOGY",
                                tax_id="TX-BE-1", base_merchant_discount_rate=0.08),
        ADMIN)
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=400)


def test_create_provider_rate_above_cap_returns_validation_amount(api):
    """PRD §2.8: "range checks on individual numeric fields are surfaced as
    `ERR_VALIDATION_AMOUNT` (HTTP 422): ... a `base_merchant_discount_rate` outside the
    inclusive range from 0 through 0.30".

    Design: Corner/entities/create_provider_rate_above_cap_returns_validation_amount
    """
    res = api.create_provider(
        create_provider_payload(legal_name="High Rate", specialty="VISION",
                                tax_id="TX-HR-1", base_merchant_discount_rate=0.40),
        ADMIN)
    validate_error(res, "ERR_VALIDATION_AMOUNT", expected_status=422)


def test_provider_get_nonexistent_returns_not_found(api):
    """PRD §2.5: "the system validates each identifier in left-to-right order and
    rejects the request with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that
    does not resolve to an existing resource."

    Design: Corner/entities/provider_get_nonexistent_returns_not_found
    """
    res = api.get_provider(NON_EXISTENT_UUID, ADMIN)
    validate_error(res, "ERR_NOT_FOUND", expected_status=404)


def test_provider_list_pagination_envelope_fields(api):
    """PRD §2.3: "The `limit` parameter caps the number of items returned ... Every
    list response carries `limit`, `offset`, `total_count`, and `has_more` inside the
    `meta` object of the envelope."

    Design: Corner/entities/provider_list_pagination_envelope_fields
    """
    api.create_provider(create_provider_payload(legal_name="L1", specialty="DENTAL",
                                                tax_id="TX-L-1", base_merchant_discount_rate=0.08),
                        ADMIN)
    api.create_provider(create_provider_payload(legal_name="L2", specialty="VISION",
                                                tax_id="TX-L-2", base_merchant_discount_rate=0.08),
                        ADMIN)
    data, meta = validate_paginated(api.list_providers(ADMIN, params={"limit": 1, "offset": 0}))
    assert len(data) == 1
    assert meta["total_count"] == 2
    assert meta["has_more"] is True


def test_duplicate_tax_id_among_non_terminated_returns_duplicate(api):
    """PRD §3.1: "The `tax_id` must be unique among all providers that are not
    `TERMINATED`; a collision is rejected with `ERR_DUPLICATE_RESOURCE`."

    Design: Corner/entities/duplicate_tax_id_among_non_terminated_returns_duplicate
    """
    a = validate_success(api.create_provider(
        create_provider_payload(legal_name="Dup A", specialty="DENTAL",
                                tax_id="TX-DUP-1", base_merchant_discount_rate=0.08), ADMIN), 201)
    api.enroll_provider(a["id"], ADMIN)
    res = api.create_provider(
        create_provider_payload(legal_name="Dup B", specialty="VISION",
                                tax_id="TX-DUP-1", base_merchant_discount_rate=0.08), ADMIN)
    validate_error(res, "ERR_DUPLICATE_RESOURCE", expected_status=409)


def test_enroll_already_enrolled_provider_returns_invalid_state(api):
    """PRD §3.1: "enrolling a `PENDING` or `SUSPENDED` provider advances it to
    `ENROLLED`".
    PRD §2.8: "(6) the target's state admitting the requested transition
    (`ERR_INVALID_STATE`)".

    Design: Corner/state_machines/enroll_already_enrolled_provider_returns_invalid_state
    """
    provider = create_enrolled_provider(tax_id="TX-EE-1")
    res = api.enroll_provider(provider["id"], ADMIN)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_terminate_provider_with_authorized_purchase_returns_invalid_state(api):
    """PRD §3.1: "Terminating a provider is permitted from either `ENROLLED` or
    `SUSPENDED`, but only when no `FinancedPurchase` belonging to that provider is still
    in `AUTHORIZED` settlement status".

    Design: Corner/state_machines/terminate_provider_with_authorized_purchase_returns_invalid_state
    """
    set_clock("2026-01-01T00:00:00Z")
    provider, plan, promotion = setup_provider_plan_promotion()
    account = create_active_account()
    authorize_purchase(provider, account, promotion, 100_000)
    res = api.terminate_provider(provider["id"], ADMIN)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)
    after = validate_success(api.get_provider(provider["id"], ADMIN), 200)
    assert after["status"] == "ENROLLED"


def test_terminal_terminated_provider_rejects_further_transitions(api):
    """PRD §3.1: "Terminating a provider is permitted from either `ENROLLED` or
    `SUSPENDED`, but only when no `FinancedPurchase` belonging to that provider is still
    in `AUTHORIZED` settlement status; `TERMINATED` is terminal."

    Design: Corner/state_machines/terminal_terminated_provider_rejects_further_transitions
    """
    provider = create_enrolled_provider(tax_id="TX-LK-1")
    validate_success(api.terminate_provider(provider["id"], ADMIN), 200)
    res = api.enroll_provider(provider["id"], ADMIN)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_provider_reinstatement_cycle_suspended_to_enrolled(api):
    """PRD §3.1: "suspending an `ENROLLED` provider moves it to `SUSPENDED`;
    re-enrolling a `SUSPENDED` provider returns it to `ENROLLED`."

    Design: Corner/state_machines/provider_reinstatement_cycle_suspended_to_enrolled
    """
    provider = create_enrolled_provider(tax_id="TX-RI-1", specialty="VISION")
    validate_success(api.suspend_provider(provider["id"], ADMIN), 200)
    res = api.enroll_provider(provider["id"], ADMIN)
    reinstated = validate_success(res, 200)
    assert reinstated["status"] == "ENROLLED"
