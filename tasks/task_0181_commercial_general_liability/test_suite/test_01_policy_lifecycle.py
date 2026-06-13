"""Policy drafting, binding, premium rating, activation, expiry and cancellation.

Covers Difficulty queue instances for premium rounding order, and Corner queue
instances across policy CRUD, bind validations, premium floor, and clock cascades.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS,
    assert_policy,
    factories, fixtures,
)

UW = TEST_USERS["underwriter_headers"]
ADMIN = TEST_USERS["insurer_admin_headers"]
ADJ = TEST_USERS["claims_adjuster_headers"]


# ===========================================================================
# Difficulty/combinatorial_formula/premium_floor_per_unit_then_multiply_rounding_order
# ===========================================================================
def test_estimated_premium_floors_basis_before_multiply(api):
    """PRD §2.9: "the whole-dollar basis is divided by one thousand and the quotient is
    reduced to a whole number by discarding any remainder (any partial thousand is dropped
    before multiplying, never rounded), then multiplied by the rate."
    PRD §3.2: "the basis is the policy's `estimated_exposure_units` in whole dollars; this is
    divided by one thousand and reduced to a whole number by discarding any remainder, then
    multiplied by `rate_per_unit_cents` to produce a raw premium."

    Design: Difficulty/combinatorial_formula/premium_floor_per_unit_then_multiply_rounding_order
    """
    insurer, insured = fixtures.create_carrier_with_insured()
    policy = fixtures.create_draft_policy(
        insurer["id"], insured["id"], "CGL-0003", estimated_exposure_units=1000500)
    resp = api.bind_policy(policy["id"], UW)
    data = validate_success(resp, 200)
    # floor(1000500 / 1000) = 1000; 1000 * 300 = 300000 (NOT 1000.5 * 300 = 300150).
    assert data["estimated_premium_cents"] == 300000, \
        f"floor-then-multiply must yield 300000, got {data['estimated_premium_cents']}"
    assert data["status"] == "BOUND"


def test_estimated_premium_rounding_order_distinct_from_multiply_then_floor(api):
    """PRD §2.9: "This truncate-then-multiply order is mandatory and identical in both
    directions."
    PRD §3.2: "this is divided by one thousand and reduced to a whole number by discarding
    any remainder, then multiplied by `rate_per_unit_cents` to produce a raw premium."

    Design: Difficulty/combinatorial_formula/premium_floor_per_unit_then_multiply_rounding_order
    """
    insurer, insured = fixtures.create_carrier_with_insured()
    # 1999 units / 1000 -> floor 1 -> *300 = 300; minimum floor 100000 wins, so use exposure
    # that exceeds the minimum to isolate the rounding order: 1500999 -> floor(1500.999)=1500.
    policy = fixtures.create_draft_policy(
        insurer["id"], insured["id"], "CGL-RND", estimated_exposure_units=1500999)
    data = validate_success(api.bind_policy(policy["id"], UW), 200)
    # floor(1500999/1000)=1500; 1500*300 = 450000 (multiply-then-floor would give 450299).
    assert data["estimated_premium_cents"] == 450000, \
        f"expected 450000 from floor(1500.999)*300, got {data['estimated_premium_cents']}"


# ===========================================================================
# Corner/entities/create_policy_returns_201_with_all_fields
# ===========================================================================
def test_create_policy_returns_draft_with_null_computed_fields(api):
    """PRD §3.2: "A freshly created policy is `DRAFT`."
    PRD §3.2: "Until a policy is bound, its `estimated_premium_cents`, `audited_premium_cents`,
    both aggregate-remaining figures, and `posture` are null."

    Design: Corner/entities/create_policy_returns_201_with_all_fields
    """
    insurer, insured = fixtures.create_carrier_with_insured()
    resp = api.create_policy(
        factories.create_policy_payload(insurer["id"], insured["id"], "CGL-C01"), UW)
    data = validate_success(resp, 201)
    assert_policy(data)
    assert data["status"] == "DRAFT"
    assert data["version"] == 1
    assert data["estimated_premium_cents"] is None
    assert data["posture"] is None


# ===========================================================================
# Corner/entities/get_policy_nonexistent_returns_not_found
# ===========================================================================
def test_get_nonexistent_policy_returns_not_found(api):
    """PRD §2.10: "each path segment's identifier is validated left to right, and the first
    identifier that does not name an existing resource yields `ERR_NOT_FOUND` before any later
    segment or body rule is evaluated."

    Design: Corner/entities/get_policy_nonexistent_returns_not_found
    """
    resp = api.get_policy("00000000-0000-4000-8000-000000000000", UW)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value, 404)


# ===========================================================================
# Corner/entities/duplicate_fein_rejected
# ===========================================================================
def test_duplicate_fein_within_insurer_rejected(api):
    """PRD §3.1: "A `fein` must be unique within the carrier; a repeat is rejected with
    `ERR_DUPLICATE_FEIN`."

    Design: Corner/entities/duplicate_fein_rejected
    """
    insurer = fixtures.create_insurer()
    fixtures.create_insured(insurer["id"], fein="11-1111111")
    resp = api.create_insured(
        factories.create_insured_payload(insurer["id"], legal_name="Other LLC",
                                         fein="11-1111111", primary_basis="SALES"), UW)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_FEIN.value, 409)


# ===========================================================================
# Corner/entities/duplicate_policy_number_rejected
# ===========================================================================
def test_duplicate_policy_number_within_insurer_rejected(api):
    """PRD §3.2: "a `policy_number` unique within the carrier (a repeat is rejected with
    `ERR_DUPLICATE_POLICY_NUMBER`)".

    Design: Corner/entities/duplicate_policy_number_rejected
    """
    insurer, insured = fixtures.create_carrier_with_insured()
    fixtures.create_draft_policy(insurer["id"], insured["id"], "CGL-DUP")
    resp = api.create_policy(
        factories.create_policy_payload(insurer["id"], insured["id"], "CGL-DUP"), UW)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_POLICY_NUMBER.value, 409)


# ===========================================================================
# Corner/entities/cross_insurer_insured_reference_rejected
# ===========================================================================
def test_cross_insurer_insured_reference_rejected(api):
    """PRD §2.10: "A body foreign key that does not resolve, or that points at a resource
    belonging to a different carrier, is rejected with `ERR_REFERENCE_NOT_FOUND`."

    Design: Corner/entities/cross_insurer_insured_reference_rejected
    """
    insurer_a = fixtures.create_insurer(name="Insurer A", naic_code="11111")
    insurer_b = fixtures.create_insurer(name="Insurer B", naic_code="22222")
    insured_b = fixtures.create_insured(insurer_b["id"], fein="22-2222222")
    resp = api.create_policy(
        factories.create_policy_payload(insurer_a["id"], insured_b["id"], "CGL-X01"), UW)
    validate_error(resp, ApiErrorId.ERR_REFERENCE_NOT_FOUND.value, 422)


# ===========================================================================
# Corner/calculations/estimated_premium_floors_at_minimum_premium
# ===========================================================================
def test_estimated_premium_floors_at_minimum(api):
    """PRD §3.2: "The stored `estimated_premium_cents` is the greater of that raw figure and
    the policy's `minimum_premium_cents` — the policy never bills below its minimum floor."

    Design: Corner/calculations/estimated_premium_floors_at_minimum_premium
    """
    insurer, insured = fixtures.create_carrier_with_insured()
    policy = fixtures.create_draft_policy(
        insurer["id"], insured["id"], "CGL-C12", estimated_exposure_units=10000)
    data = validate_success(api.bind_policy(policy["id"], UW), 200)
    # raw = floor(10000/1000)*300 = 10*300 = 3000; floored up to minimum 100000.
    assert data["estimated_premium_cents"] == 100000


# ===========================================================================
# Corner/validations/occurrence_policy_with_retro_date_rejected_on_bind
# ===========================================================================
def test_occurrence_policy_with_retro_date_rejected_on_bind(api):
    """PRD §3.2: "An occurrence policy must carry a null `retroactive_date`; supplying one is
    rejected with `ERR_RETRO_DATE_NOT_ALLOWED`."

    Design: Corner/validations/occurrence_policy_with_retro_date_rejected_on_bind
    """
    insurer, insured = fixtures.create_carrier_with_insured()
    policy = fixtures.create_draft_policy(
        insurer["id"], insured["id"], "CGL-C16",
        coverage_trigger="OCCURRENCE", retroactive_date="2025-07-01T00:00:00.000Z")
    resp = api.bind_policy(policy["id"], UW)
    validate_error(resp, ApiErrorId.ERR_RETRO_DATE_NOT_ALLOWED.value, 422)
    after = validate_success(api.get_policy(policy["id"], UW), 200)
    assert after["status"] == "DRAFT"


# ===========================================================================
# Corner/validations/invalid_policy_period_rejected_on_bind
# ===========================================================================
def test_invalid_policy_period_rejected_on_bind(api):
    """PRD §3.2: "The `effective_date` must be strictly before the `expiration_date`, else
    `ERR_INVALID_POLICY_PERIOD`."

    Design: Corner/validations/invalid_policy_period_rejected_on_bind
    """
    insurer, insured = fixtures.create_carrier_with_insured()
    policy = fixtures.create_draft_policy(
        insurer["id"], insured["id"], "CGL-C17",
        effective_date="2026-01-01T00:00:00.000Z",
        expiration_date="2026-01-01T00:00:00.000Z")
    resp = api.bind_policy(policy["id"], UW)
    validate_error(resp, ApiErrorId.ERR_INVALID_POLICY_PERIOD.value, 422)


# ===========================================================================
# Corner/validations/aggregate_limit_invalid_rejected_on_bind
# ===========================================================================
def test_aggregate_limit_invalid_rejected_on_bind(api):
    """PRD §3.2: "And the `products_aggregate_limit_cents` must be no greater than the
    `general_aggregate_limit_cents`, else `ERR_AGGREGATE_LIMIT_INVALID`."

    Design: Corner/validations/aggregate_limit_invalid_rejected_on_bind
    """
    insurer, insured = fixtures.create_carrier_with_insured()
    policy = fixtures.create_draft_policy(
        insurer["id"], insured["id"], "CGL-C18",
        general_aggregate_limit_cents=200000000,
        products_aggregate_limit_cents=300000000)
    resp = api.bind_policy(policy["id"], UW)
    validate_error(resp, ApiErrorId.ERR_AGGREGATE_LIMIT_INVALID.value, 422)


# ===========================================================================
# Corner/validations/claims_made_missing_retro_date_rejected
# ===========================================================================
def test_claims_made_missing_retro_date_rejected_on_bind(api):
    """PRD §3.2: "A claims-made policy must carry a non-null `retroactive_date` that is on or
    before its `effective_date`; if it is missing or later than the effective date, the bind is
    rejected with `ERR_RETRO_DATE_REQUIRED`."

    Design: Corner/validations/claims_made_missing_retro_date_rejected
    """
    insurer, insured = fixtures.create_carrier_with_insured()
    policy = fixtures.create_draft_policy(
        insurer["id"], insured["id"], "CGL-C19", coverage_trigger="CLAIMS_MADE")
    resp = api.bind_policy(policy["id"], UW)
    validate_error(resp, ApiErrorId.ERR_RETRO_DATE_REQUIRED.value, 422)


# ===========================================================================
# Corner/state_machines/bind_already_bound_policy_returns_invalid_state
# ===========================================================================
def test_bind_already_bound_policy_returns_invalid_state(api):
    """PRD §3.2: "Binding the policy advances it from `DRAFT` to `BOUND`".
    PRD §2.11: "Only then is the target resource's state checked to confirm the requested
    transition is legal from its current state (`ERR_INVALID_STATE`)."

    Design: Corner/state_machines/bind_already_bound_policy_returns_invalid_state
    """
    insurer, insured, policy = fixtures.create_bound_policy(policy_number="CGL-C06")
    resp = api.bind_policy(policy["id"], UW)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)
    after = validate_success(api.get_policy(policy["id"], UW), 200)
    assert after["status"] == "BOUND"


# ===========================================================================
# Corner/state_machines/activate_before_effective_date_rejected
# ===========================================================================
def test_activate_before_effective_date_rejected(api):
    """PRD §3.3: "Activation is permitted only once the insurer's `current_date` has reached the
    policy's `effective_date`; an attempt before then is rejected with
    `ERR_POLICY_NOT_YET_EFFECTIVE`."

    Design: Corner/state_machines/activate_before_effective_date_rejected
    """
    insurer, insured = fixtures.create_carrier_with_insured()
    policy = fixtures.create_draft_policy(
        insurer["id"], insured["id"], "CGL-C07",
        effective_date="2026-06-01T00:00:00.000Z",
        expiration_date="2027-06-01T00:00:00.000Z")
    fixtures.bind_policy(policy["id"])
    resp = api.activate_policy(policy["id"], UW)  # clock still default 2026-01-01
    validate_error(resp, ApiErrorId.ERR_POLICY_NOT_YET_EFFECTIVE.value, 409)
    after = validate_success(api.get_policy(policy["id"], UW), 200)
    assert after["status"] == "BOUND"


# ===========================================================================
# Corner/state_machines/clock_expiry_cascades_certificate_to_expired
# ===========================================================================
def test_clock_expiry_cascades_policy_and_certificate_to_expired(api):
    """PRD §2.5: "Whenever the clock advances, every `IN_FORCE` policy whose `expiration_date` is
    at or before the new `current_date` transitions to `EXPIRED`".
    PRD §2.6: "When the clock advance expires an `IN_FORCE` policy, every `ISSUED` Certificate of
    Insurance on that policy is simultaneously moved from `ISSUED` to `EXPIRED`."

    Design: Corner/state_machines/clock_expiry_cascades_certificate_to_expired
    """
    insurer, insured, holder, policy, cert = \
        fixtures.setup_in_force_with_informational_issued_cert()
    validate_success(
        api.advance_clock(insurer["id"], {"to_iso8601": "2027-01-02T00:00:00.000Z"}, ADMIN), 200)
    pol = validate_success(api.get_policy(policy["id"], UW), 200)
    assert pol["status"] == "EXPIRED"
    coi = validate_success(api.get_certificate(cert["id"], UW), 200)
    assert coi["status"] == "EXPIRED"


# ===========================================================================
# Corner/state_machines/policy_cancel_cascades_void_endorsement_and_revoke_coi
# ===========================================================================
def test_policy_cancel_cascades_void_endorsement_and_revoke_certificate(api):
    """PRD §3.3: "when permitted, cancellation moves the policy to `CANCELLED`, voids every
    `ACTIVE` endorsement on it, revokes every `ISSUED` certificate on it, and increments the
    version."

    Design: Corner/state_machines/policy_cancel_cascades_void_endorsement_and_revoke_coi
    """
    insurer, insured, holder, policy, endo, cert = \
        fixtures.setup_in_force_with_issued_ai_cert()
    pol = validate_success(api.cancel_policy(policy["id"], UW), 200)
    assert pol["status"] == "CANCELLED"
    endo_after = validate_success(api.get_endorsement(endo["id"], UW), 200)
    assert endo_after["status"] == "VOID"
    coi_after = validate_success(api.get_certificate(cert["id"], UW), 200)
    assert coi_after["status"] == "REVOKED"


# ===========================================================================
# Corner/state_machines/open_claims_block_in_force_cancel
# ===========================================================================
def test_open_claims_block_in_force_cancel(api):
    """PRD §3.3: "Cancelling an `IN_FORCE` policy is blocked while any claim on it is still live
    — that is, in `OPEN`, `RESERVED`, `PAID`, or `REOPENED` — and such an attempt is rejected
    with `ERR_OPEN_CLAIMS_BLOCK_CANCEL`".

    Design: Corner/state_machines/open_claims_block_in_force_cancel
    """
    insurer, insured, policy, claim = fixtures.setup_in_force_with_reserved_claim()
    resp = api.cancel_policy(policy["id"], UW)
    validate_error(resp, ApiErrorId.ERR_OPEN_CLAIMS_BLOCK_CANCEL.value, 409)
    after = validate_success(api.get_policy(policy["id"], UW), 200)
    assert after["status"] == "IN_FORCE"


# ===========================================================================
# Corner/validations/clock_rewind_rejected
# ===========================================================================
def test_clock_rewind_rejected(api):
    """PRD §2.5: "the new value must be at or after the present `current_date`, and an attempt
    to move it backward is rejected with `ERR_CLOCK_NOT_MONOTONIC`."

    Design: Corner/validations/clock_rewind_rejected
    """
    insurer = fixtures.create_insurer()
    validate_success(
        api.advance_clock(insurer["id"], {"to_iso8601": "2026-06-01T00:00:00.000Z"}, ADMIN), 200)
    resp = api.advance_clock(insurer["id"], {"to_iso8601": "2026-03-01T00:00:00.000Z"}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_CLOCK_NOT_MONOTONIC.value, 422)
    after = validate_success(api.get_insurer(insurer["id"], ADMIN), 200)
    assert after["current_date"] == "2026-06-01T00:00:00.000Z"
