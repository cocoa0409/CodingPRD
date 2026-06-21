"""Claim coverage trigger test, incurred computation, transaction validations, and
the claim lifecycle (reopen cycle, reserve-in-force dependency).

Covers Difficulty queue instances for coverage divergence, claims-made retro floor,
the claim reopen cycle, and the claim->policy in-force dependency; plus Corner queue
instances across claim computed fields, transaction immutability, and transaction
validation errors.
"""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS,
    assert_claim, assert_claim_transaction,
    factories, fixtures,
)

UW = TEST_USERS["underwriter_headers"]
ADMIN = TEST_USERS["insurer_admin_headers"]
ADJ = TEST_USERS["claims_adjuster_headers"]


def _two_policies_occ_and_cm(api):
    """Build one OCCURRENCE and one CLAIMS_MADE (retro 2025-07-01) policy on the same
    carrier/insured, both IN_FORCE, with the clock at 2026-06-01. Returns (insurer, p_occ, p_cm)."""
    insurer = fixtures.create_insurer()
    insured = fixtures.create_insured(insurer["id"])
    p_occ = fixtures.create_draft_policy(insurer["id"], insured["id"], "CGL-OCC",
                                         coverage_trigger="OCCURRENCE")
    fixtures.bind_policy(p_occ["id"]); fixtures.activate_policy(p_occ["id"])
    p_cm = fixtures.create_draft_policy(insurer["id"], insured["id"], "CGL-CM",
                                        coverage_trigger="CLAIMS_MADE",
                                        retroactive_date="2025-07-01T00:00:00.000Z")
    fixtures.bind_policy(p_cm["id"]); fixtures.activate_policy(p_cm["id"])
    validate_success(
        api.advance_clock(insurer["id"], {"to_iso8601": "2026-06-01T00:00:00.000Z"}, ADMIN), 200)
    return insurer, p_occ, p_cm


# ===========================================================================
# Difficulty/dual_variant_calc/occurrence_vs_claims_made_coverage_divergence
# ===========================================================================
def test_claims_made_covers_pair_that_occurrence_rejects(api):
    """PRD §3.5: "For a `CLAIMS_MADE` policy the test is different and the same occurrence-and-
    report pair can be covered under one trigger yet excluded under the other."
    PRD §3.5: "For an `OCCURRENCE` policy, coverage requires only that the `occurrence_date`
    fall at or after the `effective_date` and strictly before the `expiration_date` ... If the
    occurrence falls outside that window, the reserve is rejected with
    `ERR_OCCURRENCE_OUTSIDE_PERIOD`."

    Design: Difficulty/dual_variant_calc/occurrence_vs_claims_made_coverage_divergence
    """
    insurer, p_occ, p_cm = _two_policies_occ_and_cm(api)
    claim_cm = fixtures.open_claim(p_cm["id"], claimant_name="Pedestrian B",
                                   loss_type="BODILY_INJURY",
                                   occurrence_date="2025-08-01T00:00:00.000Z",
                                   reported_date="2026-06-01T00:00:00.000Z")
    # Claims-made: occurrence after retro 2025-07-01 AND reported in period -> covered.
    validate_success(
        api.post_transaction(claim_cm["id"],
                             factories.create_transaction_payload("RESERVE_SET", 5000000), ADJ), 201)
    after_cm = validate_success(api.get_claim(claim_cm["id"], ADJ), 200)
    assert after_cm["status"] == "RESERVED"


def test_occurrence_rejects_pair_that_claims_made_covers(api):
    """PRD §3.5: "For an `OCCURRENCE` policy, coverage requires only that the `occurrence_date`
    fall at or after the `effective_date` and strictly before the `expiration_date`; the
    `reported_date` and `retroactive_date` are not consulted. If the occurrence falls outside
    that window, the reserve is rejected with `ERR_OCCURRENCE_OUTSIDE_PERIOD`."

    Design: Difficulty/dual_variant_calc/occurrence_vs_claims_made_coverage_divergence
    """
    insurer, p_occ, p_cm = _two_policies_occ_and_cm(api)
    claim_occ = fixtures.open_claim(p_occ["id"], claimant_name="Pedestrian A",
                                    loss_type="BODILY_INJURY",
                                    occurrence_date="2025-08-01T00:00:00.000Z",
                                    reported_date="2026-06-01T00:00:00.000Z")
    # Occurrence 2025-08-01 is before effective_date 2026-01-01 -> rejected.
    resp = api.post_transaction(
        claim_occ["id"], factories.create_transaction_payload("RESERVE_SET", 5000000), ADJ)
    validate_error(resp, ApiErrorId.ERR_OCCURRENCE_OUTSIDE_PERIOD.value, 409)
    after = validate_success(api.get_claim(claim_occ["id"], ADJ), 200)
    assert after["status"] == "OPEN"


# ===========================================================================
# Difficulty/resource_temporal_overlap/claims_made_retro_floor_plus_reported_window
# ===========================================================================
def test_claims_made_occurrence_before_retro_rejected(api):
    """PRD §3.5: "First, the `occurrence_date` must be at or after the policy's
    `retroactive_date`; if the occurrence predates the retroactive date the reserve is rejected
    with `ERR_CLAIM_BEFORE_RETRO_DATE`."

    Design: Difficulty/resource_temporal_overlap/claims_made_retro_floor_plus_reported_window
    """
    insurer = fixtures.create_insurer()
    insured = fixtures.create_insured(insurer["id"])
    policy = fixtures.create_draft_policy(insurer["id"], insured["id"], "CGL-0014",
                                          coverage_trigger="CLAIMS_MADE",
                                          retroactive_date="2025-07-01T00:00:00.000Z")
    fixtures.bind_policy(policy["id"]); fixtures.activate_policy(policy["id"])
    validate_success(
        api.advance_clock(insurer["id"], {"to_iso8601": "2026-06-01T00:00:00.000Z"}, ADMIN), 200)
    claim = fixtures.open_claim(policy["id"], claimant_name="PreRetro G",
                                loss_type="BODILY_INJURY",
                                occurrence_date="2025-06-01T00:00:00.000Z",
                                reported_date="2026-06-01T00:00:00.000Z")
    resp = api.post_transaction(
        claim["id"], factories.create_transaction_payload("RESERVE_SET", 5000000), ADJ)
    validate_error(resp, ApiErrorId.ERR_CLAIM_BEFORE_RETRO_DATE.value, 409)
    after = validate_success(api.get_claim(claim["id"], ADJ), 200)
    assert after["status"] == "OPEN"


def test_claims_made_retro_check_precedes_reported_window_check(api):
    """PRD §3.5: "The retroactive-date check therefore always precedes the reported-in-period
    check."
    PRD §3.5: "if the occurrence predates the retroactive date the reserve is rejected with
    `ERR_CLAIM_BEFORE_RETRO_DATE`."

    Design: Difficulty/resource_temporal_overlap/claims_made_retro_floor_plus_reported_window
    """
    # Occurrence before retro AND reported also outside period: the retro check fires first,
    # so the error is ERR_CLAIM_BEFORE_RETRO_DATE (not ERR_OCCURRENCE_OUTSIDE_PERIOD).
    insurer = fixtures.create_insurer()
    insured = fixtures.create_insured(insurer["id"])
    policy = fixtures.create_draft_policy(insurer["id"], insured["id"], "CGL-RETRO2",
                                          coverage_trigger="CLAIMS_MADE",
                                          retroactive_date="2025-07-01T00:00:00.000Z")
    fixtures.bind_policy(policy["id"]); fixtures.activate_policy(policy["id"])
    validate_success(
        api.advance_clock(insurer["id"], {"to_iso8601": "2026-06-01T00:00:00.000Z"}, ADMIN), 200)
    # reported 2025-06-15 is before effective 2026-01-01 (out of window) and occurrence
    # 2025-06-01 is before retro 2025-07-01. Retro check must win.
    claim = fixtures.open_claim(policy["id"], claimant_name="DoubleFail",
                                loss_type="BODILY_INJURY",
                                occurrence_date="2025-06-01T00:00:00.000Z",
                                reported_date="2025-06-15T00:00:00.000Z")
    resp = api.post_transaction(
        claim["id"], factories.create_transaction_payload("RESERVE_SET", 5000000), ADJ)
    validate_error(resp, ApiErrorId.ERR_CLAIM_BEFORE_RETRO_DATE.value, 409)


# ===========================================================================
# Difficulty/cross_entity_state_dependency/claim_reserve_requires_policy_in_force
# ===========================================================================
def test_reserve_on_bound_policy_rejected_not_in_force(api):
    """PRD §3.5: "Two preconditions gate it: the policy must be `IN_FORCE` (else
    `ERR_POLICY_NOT_IN_FORCE`), and coverage must apply under the trigger test."

    Design: Difficulty/cross_entity_state_dependency/claim_reserve_requires_policy_in_force
    """
    insurer, insured, policy = fixtures.create_bound_policy(policy_number="CGL-0012")
    claim = fixtures.open_claim(policy["id"], claimant_name="Early F",
                                loss_type="BODILY_INJURY",
                                occurrence_date="2026-02-01T00:00:00.000Z",
                                reported_date="2026-02-02T00:00:00.000Z")
    resp = api.post_transaction(
        claim["id"], factories.create_transaction_payload("RESERVE_SET", 5000000), ADJ)
    validate_error(resp, ApiErrorId.ERR_POLICY_NOT_IN_FORCE.value, 409)
    after = validate_success(api.get_claim(claim["id"], ADJ), 200)
    assert after["status"] == "OPEN"


def test_reopen_closed_claim_requires_policy_in_force(api):
    """PRD §3.7: "Reopening a `CLOSED` claim is permitted only while the policy is `IN_FORCE`,
    else `ERR_POLICY_NOT_IN_FORCE`; it moves the claim from `CLOSED` to `REOPENED`".

    Design: Difficulty/cross_entity_state_dependency/claim_reserve_requires_policy_in_force
    """
    # Drive the policy out of force (EXPIRED) after closing a claim, then attempt reopen.
    insurer = fixtures.create_insurer()
    insured = fixtures.create_insured(insurer["id"])
    policy = fixtures.create_draft_policy(insurer["id"], insured["id"], "CGL-REOPEN-NF")
    fixtures.bind_policy(policy["id"]); fixtures.activate_policy(policy["id"])
    validate_success(
        api.advance_clock(insurer["id"], {"to_iso8601": "2026-06-01T00:00:00.000Z"}, ADMIN), 200)
    claim = fixtures.open_claim(policy["id"], claimant_name="ClosedThenExpired",
                                occurrence_date="2026-02-01T00:00:00.000Z",
                                reported_date="2026-02-02T00:00:00.000Z")
    fixtures.post_first_reserve(claim["id"], 5000000)
    pv = fixtures.current_policy_version(policy["id"])
    validate_success(api.post_transaction(
        claim["id"],
        factories.create_transaction_payload("RESERVE_RELEASE", 5000000, expected_policy_version=pv),
        ADJ), 201)
    validate_success(api.close_claim(claim["id"], ADJ), 200)
    # Expire the policy.
    validate_success(
        api.advance_clock(insurer["id"], {"to_iso8601": "2027-01-02T00:00:00.000Z"}, ADMIN), 200)
    resp = api.reopen_claim(claim["id"], ADJ)
    validate_error(resp, ApiErrorId.ERR_POLICY_NOT_IN_FORCE.value, 409)


# ===========================================================================
# Difficulty/non_linear_state_machine/claim_reopen_cycle_returns_to_reserved
# ===========================================================================
def test_claim_reopen_cycle_returns_to_reserved(api):
    """PRD §3.7: "Reopening a `CLOSED` claim is permitted only while the policy is `IN_FORCE` ...
    it moves the claim from `CLOSED` to `REOPENED`".
    PRD §3.7: "A reopened claim re-enters its financial life through a fresh `RESERVE_SET`, which
    — subject to the optimistic-concurrency check — moves it from `REOPENED` back to `RESERVED`
    and resumes erosion."

    Design: Difficulty/non_linear_state_machine/claim_reopen_cycle_returns_to_reserved
    """
    insurer, insured, policy = fixtures.create_in_force_policy(policy_number="CGL-0005")
    claim = fixtures.open_claim(policy["id"], claimant_name="Injured D",
                                occurrence_date="2026-02-01T00:00:00.000Z",
                                reported_date="2026-02-02T00:00:00.000Z")
    fixtures.post_first_reserve(claim["id"], 50000000)
    fixtures.post_transaction_occ(policy["id"], claim["id"], "PAYMENT", 50000000)
    fixtures.post_transaction_occ(policy["id"], claim["id"], "RESERVE_RELEASE", 50000000)
    validate_success(api.close_claim(claim["id"], ADJ), 200)

    reopened = validate_success(api.reopen_claim(claim["id"], ADJ), 200)
    assert reopened["status"] == "REOPENED"

    pv = fixtures.current_policy_version(policy["id"])
    validate_success(api.post_transaction(
        claim["id"],
        factories.create_transaction_payload("RESERVE_SET", 30000000, expected_policy_version=pv),
        ADJ), 201)
    after = validate_success(api.get_claim(claim["id"], ADJ), 200)
    assert after["status"] == "RESERVED"
    # incurred = open reserve 30000000 + payments 50000000 = 80000000.
    assert after["incurred_cents"] == 80000000


def test_reopen_non_closed_claim_rejected_invalid_state(api):
    """PRD §3.7: "`CLOSED` and `DENIED` are the claim's terminal states, except that a closed
    claim may be reopened."
    PRD §2.11: "Only then is the target resource's state checked to confirm the requested
    transition is legal from its current state (`ERR_INVALID_STATE`)."

    Design: Difficulty/non_linear_state_machine/claim_reopen_cycle_returns_to_reserved
    """
    insurer, insured, policy, claim = fixtures.setup_in_force_with_reserved_claim()
    # Claim is RESERVED, not CLOSED -> reopen is an illegal transition.
    resp = api.reopen_claim(claim["id"], ADJ)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)


# ===========================================================================
# Corner/entities/claim_aggregate_bucket_computed_from_loss_type
# ===========================================================================
def test_claim_aggregate_bucket_computed_from_loss_type(api):
    """PRD §2.7: "a claim whose `loss_type` is `PRODUCTS_COMPLETED_OPS` lands in the `PRODUCTS`
    bucket and every other loss type lands in `GENERAL`, recorded on the claim's
    `aggregate_bucket`."

    Design: Corner/entities/claim_aggregate_bucket_computed_from_loss_type
    """
    insurer, insured, policy = fixtures.create_in_force_policy(policy_number="CGL-C04")
    claim = fixtures.open_claim(policy["id"], claimant_name="Prod J",
                                loss_type="PRODUCTS_COMPLETED_OPS",
                                occurrence_date="2026-03-01T00:00:00.000Z",
                                reported_date="2026-03-02T00:00:00.000Z")
    assert_claim(claim)
    assert claim["aggregate_bucket"] == "PRODUCTS"


# ===========================================================================
# Corner/entities/claim_transaction_is_immutable_event
# ===========================================================================
def test_claim_transaction_is_immutable_ledger_entry(api):
    """PRD §2.4: "The single exception is the **ClaimTransaction**: a claim transaction is an
    immutable ledger entry, so it carries only `id` and `created_at` — it has neither an
    `updated_at` nor a `version`."
    PRD §3.6: "Every transaction is stamped with a monotonic per-claim `posted_sequence`, the
    first posted transaction on a claim being sequence one".

    Design: Corner/entities/claim_transaction_is_immutable_event
    """
    insurer, insured, policy = fixtures.create_in_force_policy(policy_number="CGL-C05")
    claim = fixtures.open_claim(policy["id"], claimant_name="K",
                                occurrence_date="2026-03-01T00:00:00.000Z",
                                reported_date="2026-03-02T00:00:00.000Z")
    txn = validate_success(api.post_transaction(
        claim["id"], factories.create_transaction_payload("RESERVE_SET", 5000000), ADJ), 201)
    fetched = validate_success(api.get_transaction(txn["id"], ADJ), 200)
    assert_claim_transaction(fetched)
    assert fetched["posted_sequence"] == 1
    assert fetched["amount_cents"] == 5000000


# ===========================================================================
# Corner/calculations/claim_incurred_subtracts_recovery
# ===========================================================================
def test_claim_incurred_open_reserve_plus_payments_minus_recoveries(api):
    """PRD §3.6: "The incurred figure is then the open reserve plus the sum of all `PAYMENT`
    amounts minus the sum of all `RECOVERY` amounts, with the whole figure floored at zero."

    Design: Corner/calculations/claim_incurred_subtracts_recovery
    """
    # Large limits so no per-occurrence cap interferes with the raw incurred figure.
    insurer, insured, policy = fixtures.create_in_force_policy(
        policy_number="CGL-C15",
        each_occurrence_limit_cents=1000000000,
        general_aggregate_limit_cents=2000000000,
        products_aggregate_limit_cents=1000000000)
    claim = fixtures.open_claim(policy["id"], claimant_name="Rec O",
                                occurrence_date="2026-03-01T00:00:00.000Z",
                                reported_date="2026-03-02T00:00:00.000Z")
    fixtures.post_first_reserve(claim["id"], 100000000)
    fixtures.post_transaction_occ(policy["id"], claim["id"], "PAYMENT", 40000000)
    fixtures.post_transaction_occ(policy["id"], claim["id"], "RECOVERY", 5000000)
    after = validate_success(api.get_claim(claim["id"], ADJ), 200)
    # open reserve 100000000 + payments 40000000 - recoveries 5000000 = 135000000.
    assert after["incurred_cents"] == 135000000


# ===========================================================================
# Corner/validations/claim_transaction_negative_amount_rejected
# ===========================================================================
def test_claim_transaction_zero_amount_rejected(api):
    """PRD §3.6: "The `amount_cents` must be a positive integer, else `ERR_INVALID_AMOUNT`."

    Design: Corner/validations/claim_transaction_negative_amount_rejected
    """
    insurer, insured, policy = fixtures.create_in_force_policy(policy_number="CGL-C20")
    claim = fixtures.open_claim(policy["id"], claimant_name="Q",
                                occurrence_date="2026-03-01T00:00:00.000Z",
                                reported_date="2026-03-02T00:00:00.000Z")
    resp = api.post_transaction(
        claim["id"], factories.create_transaction_payload("RESERVE_SET", 0), ADJ)
    validate_error(resp, ApiErrorId.ERR_INVALID_AMOUNT.value, 422)
    after = validate_success(api.get_claim(claim["id"], ADJ), 200)
    assert after["status"] == "OPEN"


# ===========================================================================
# Corner/validations/reserve_release_exceeds_open_reserve_rejected
# ===========================================================================
def test_reserve_release_exceeds_open_reserve_rejected(api):
    """PRD §3.6: "A `RESERVE_RELEASE` may not exceed the claim's current open reserve and a
    `RECOVERY` may not exceed the claim's cumulative payments; either overrun is rejected with
    `ERR_RELEASE_EXCEEDS_RESERVE`."

    Design: Corner/validations/reserve_release_exceeds_open_reserve_rejected
    """
    insurer, insured, policy, claim = fixtures.setup_in_force_with_reserved_claim(
        reserve_cents=50000000)
    pv = fixtures.current_policy_version(policy["id"])
    resp = api.post_transaction(
        claim["id"],
        factories.create_transaction_payload("RESERVE_RELEASE", 60000000, expected_policy_version=pv),
        ADJ)
    validate_error(resp, ApiErrorId.ERR_RELEASE_EXCEEDS_RESERVE.value, 422)


# ===========================================================================
# Corner/validations/close_claim_with_open_reserve_rejected
# ===========================================================================
def test_close_claim_with_open_reserve_rejected(api):
    """PRD §3.7: "A claim is closed by a `ClaimsAdjuster` only when its net open reserve — total
    `RESERVE_SET` less total `RESERVE_RELEASE` — is exactly zero; a non-zero open reserve blocks
    the close with `ERR_OPEN_RESERVE_REMAINS`."

    Design: Corner/validations/close_claim_with_open_reserve_rejected
    """
    insurer, insured, policy, claim = fixtures.setup_in_force_with_reserved_claim(
        reserve_cents=50000000)
    resp = api.close_claim(claim["id"], ADJ)
    validate_error(resp, ApiErrorId.ERR_OPEN_RESERVE_REMAINS.value, 409)
    after = validate_success(api.get_claim(claim["id"], ADJ), 200)
    assert after["status"] == "RESERVED"


# ===========================================================================
# Corner/validations/deny_paid_claim_rejected
# ===========================================================================
def test_deny_paid_claim_rejected(api):
    """PRD §3.7: "A claim may instead be denied, but only if it has never carried a `PAYMENT`
    transaction; an attempt to deny a claim that has been paid is rejected with
    `ERR_PAID_CLAIM_CANNOT_DENY`."

    Design: Corner/validations/deny_paid_claim_rejected
    """
    insurer, insured, policy = fixtures.create_in_force_policy(policy_number="CGL-C23")
    claim = fixtures.open_claim(policy["id"], claimant_name="T",
                                occurrence_date="2026-03-01T00:00:00.000Z",
                                reported_date="2026-03-02T00:00:00.000Z")
    fixtures.post_first_reserve(claim["id"], 50000000)
    fixtures.post_transaction_occ(policy["id"], claim["id"], "PAYMENT", 50000000)
    resp = api.deny_claim(claim["id"], ADJ)
    validate_error(resp, ApiErrorId.ERR_PAID_CLAIM_CANNOT_DENY.value, 409)
    after = validate_success(api.get_claim(claim["id"], ADJ), 200)
    assert after["status"] == "PAID"
