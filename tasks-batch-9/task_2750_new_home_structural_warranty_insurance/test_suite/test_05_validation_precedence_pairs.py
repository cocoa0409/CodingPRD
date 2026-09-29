"""Validation-precedence pairs: which error wins when one request breaks two rules.

PRD Section 2.8 fixes a single ascending ladder of checks for every endpoint in
the API, so a request that would fail more than one check has exactly one
correct answer. The two scenarios in this file each break two rules from
different rungs at once, and each is paired with a control scenario in which
only the lower-priority rule is broken, so that the winning error can never be
excused as "the other check simply never runs".
"""

from test_helpers import (
    ApiErrorId,
    CANONICAL_STRUCTURAL_TERM_END_DATE,
    create_homeowner,
    create_policy_payload,
    create_transfer_payload,
    make_builder_principal_headers,
    make_homeowner_headers,
    read_builder,
    read_policy,
    setup_active_policy,
    setup_insurer_arm_claim,
    suspend_builder,
    validate_error,
    validate_paginated,
)


# --------------------------------------------------------------------------
# Local setup helpers
# --------------------------------------------------------------------------
def _frozen_but_still_approved_builder():
    """One ACTIVE home whose insurer-arm structural claim has driven the
    builder's monitoring posture to FROZEN while its underwriting status is
    still APPROVED, plus a second registered buyer for the enrollment that the
    posture gate is about to block.

    The claim demands 2,187,500 cents at a substantiation ratio of 0.80, is
    designated structural by its engineering report, and therefore reserves
    1,380,000 cents against 363,894 cents of earned premium.
    """
    scenario = setup_insurer_arm_claim(
        claimed_amount_cents=2_187_500,
        substantiation_ratio=0.80,
        coverage_type="STRUCTURAL",
        defect_category="STRUCTURAL_CRACKING",
        assessments=[{
            "affected_elements": ["FOUNDATION_WALL"],
            "deflection_ratio": 0.0049,
            "load_bearing_affected": True,
        }],
        claim_overrides={
            "damage_description": "Stair-step cracking across the foundation wall",
        },
    )
    scenario["second_buyer"] = create_homeowner(
        full_name="Gita Prasad", email="gita.prasad@example.com",
    )
    scenario["builder"] = read_builder(scenario["builder"]["id"])
    return scenario


def _blocked_enrollment_payload(scenario):
    """A second home for the same builder, priced at 39,000,000 cents and
    closing on the current clock date."""
    return create_policy_payload(
        scenario["builder"]["id"],
        scenario["second_buyer"]["id"],
        street_address="7 Foxglove Way",
        state_code="TX",
        purchase_price_cents=39_000_000,
        closing_date="2028-09-01",
    )


# --------------------------------------------------------------------------
# Home enrollment: rung 13 (builder not approved) beats rung 17 (posture)
# --------------------------------------------------------------------------
def test_frozen_posture_alone_blocks_enrollment_with_the_fiscal_error(
        api, underwriting_officer_headers):
    """PRD §3.3: "The builder's `monitoring_posture` must not be `FROZEN`: a
    frozen builder cannot write new business at all, and the attempt is refused
    with `ERR_BUILDER_POSTURE_FROZEN`."
    PRD §2.10: "`FROZEN` blocks new home enrollments outright and also blocks
    the reinstatement of a suspended builder, and in addition marks the
    builder's not-yet-activated policies so that they cannot be put in force."

    The control case for the priority pair: with the builder still APPROVED,
    the fiscal rung is the only rule broken and must be the reported error.

    Design: Difficulty/priority_pair_validation_conflict/enrollment_prefers_builder_not_approved_over_builder_posture_frozen
    """
    scenario = _frozen_but_still_approved_builder()
    builder = scenario["builder"]
    assert builder["monitoring_posture"] == "FROZEN", (
        f"setup must leave the builder frozen, got {builder['monitoring_posture']}"
    )
    assert builder["underwriting_status"] == "APPROVED", (
        "setup must leave the builder approved so only the fiscal rule is broken, "
        f"got {builder['underwriting_status']}"
    )

    response = api.create_policy(
        _blocked_enrollment_payload(scenario),
        make_builder_principal_headers(builder["id"]),
    )
    validate_error(response, ApiErrorId.ERR_BUILDER_POSTURE_FROZEN.value)

    policies, meta = validate_paginated(
        api.list_policies(underwriting_officer_headers,
                          {"builder_id": builder["id"], "limit": 100})
    )
    assert meta["total_count"] == 1, (
        f"the refused enrollment must not create a policy, got {meta['total_count']}"
    )


def test_suspended_and_frozen_builder_enrollment_reports_the_approval_error_first(
        api, underwriting_officer_headers):
    """PRD §2.8: "Checks are evaluated in the ascending order below and **the
    first failure wins**; later checks are never reached and never mask an
    earlier one."
    PRD §2.8: "And because the posture gates sit at rung 17, behind everything
    else, a frozen builder attempting an enrollment that is *also* malformed
    hears about the malformation first."
    PRD §2.8 rung 13: "**Cross-entity and cross-axis state guards (409),** in
    this internal order: `ERR_BUILDER_NOT_APPROVED` (home enrollment and policy
    activation), then `ERR_PREMIUM_NOT_PAID` (activation), then
    `ERR_ENROLLMENT_ON_HOLD` (activation), then `ERR_POLICY_NOT_ACTIVE` (claim
    filing, transfer request creation, endorsement-term creation), then
    `ERR_COVERAGE_LIMIT_EXHAUSTED` (adjudication and payment), then the
    neutral-eligibility pair `ERR_NEUTRAL_INACTIVE` and
    `ERR_NEUTRAL_CREDENTIAL_MISMATCH` (escalation opening), then
    `ERR_MISSING_TRANSFER_DOCUMENTATION` (transfer decision), then
    `ERR_BUILDER_DEFAULTED` (obligation routing)."
    PRD §3.3: "The enrolling builder's `underwriting_status` must be exactly
    `APPROVED`, and an enrollment attempted against a builder in any other
    underwriting state is refused with `ERR_BUILDER_NOT_APPROVED`."

    Design: Difficulty/priority_pair_validation_conflict/enrollment_prefers_builder_not_approved_over_builder_posture_frozen
    """
    scenario = _frozen_but_still_approved_builder()
    builder_id = scenario["builder"]["id"]

    suspend_builder(builder_id, reason="posture breach pending remediation plan")
    builder = read_builder(builder_id)
    assert builder["underwriting_status"] == "SUSPENDED", (
        f"the builder must be suspended, got {builder['underwriting_status']}"
    )
    assert builder["monitoring_posture"] == "FROZEN", (
        "the fiscal rule must still be broken as well, got "
        f"{builder['monitoring_posture']}"
    )

    response = api.create_policy(
        _blocked_enrollment_payload(scenario),
        make_builder_principal_headers(builder_id),
    )
    error_data = validate_error(response, ApiErrorId.ERR_BUILDER_NOT_APPROVED.value)
    assert error_data["error_id"] != ApiErrorId.ERR_BUILDER_POSTURE_FROZEN.value, (
        "the rung-17 fiscal error must not pre-empt the rung-13 approval error"
    )

    policies, meta = validate_paginated(
        api.list_policies(underwriting_officer_headers,
                          {"builder_id": builder_id, "limit": 100})
    )
    assert meta["total_count"] == 1, (
        f"the refused enrollment must not create a policy, got {meta['total_count']}"
    )


# --------------------------------------------------------------------------
# Transfer request: rung 15 (elapsed term) beats rung 16 (self-transfer)
# --------------------------------------------------------------------------
def test_self_transfer_alone_reports_the_referential_error(
        api, underwriting_officer_headers):
    """PRD §3.5: "The `new_owner_id` must be someone other than the policy's
    `current_owner_id`; naming the current holder is refused with
    `ERR_TRANSFEREE_IS_CURRENT_OWNER`."

    The control case for the priority pair: the transfer date sits well inside
    the structural term's closed interval, so the referential rule is the only
    rule broken and must be the reported error.

    Design: Difficulty/priority_pair_validation_conflict/transfer_prefers_coverage_term_elapsed_over_transferee_is_current_owner
    """
    scenario = setup_active_policy()
    policy = scenario["policy"]
    owner_id = scenario["homeowner"]["id"]
    assert policy["coverage_status"] == "ACTIVE"
    assert policy["current_owner_id"] == owner_id

    response = api.create_transfer(
        policy["id"],
        create_transfer_payload(owner_id, policy["version"],
                                transfer_date="2028-09-05",
                                documents_reference="DEED-2028-0905"),
        make_homeowner_headers(owner_id),
    )
    validate_error(response, ApiErrorId.ERR_TRANSFEREE_IS_CURRENT_OWNER.value)

    transfers, meta = validate_paginated(
        api.list_transfers(underwriting_officer_headers,
                           {"policy_id": policy["id"], "limit": 100})
    )
    assert meta["total_count"] == 0, (
        f"the refused request must not create a transfer, got {meta['total_count']}"
    )


def test_transfer_date_past_the_structural_term_wins_over_the_self_transfer(
        api, underwriting_officer_headers):
    """PRD §2.8: "Checks are evaluated in the ascending order below and **the
    first failure wins**; later checks are never reached and never mask an
    earlier one."
    PRD §2.8 rung 15: "**Temporal guards,** in this internal order:
    `ERR_SESSION_WINDOW_NOT_STARTED` at HTTP 409 (session outcome and award),
    then `ERR_COVERAGE_TERM_ELAPSED` at 422 (transfer request creation), then
    `ERR_NO_COVERAGE_IN_FORCE` at 422 (claim filing), then
    `ERR_ESCALATION_WINDOW_ELAPSED` at 422 (escalation opening), then
    `ERR_NEUTRAL_WINDOW_CONFLICT` at 409 (escalation opening), then
    `ERR_COVERAGE_TERM_OVERLAP` at 409 (endorsement-term creation)."
    PRD §2.8 rung 16: "**Referential guards,** in this internal order:
    `ERR_TRANSFEREE_IS_CURRENT_OWNER` at 422 (transfer request creation), then
    `ERR_PRIOR_CASE_CLAIM_MISMATCH` at 422 (escalation opening), then
    `ERR_OPEN_DISPUTE_BLOCKS_TRANSFER` at 409 (transfer recording), then
    `ERR_ENTRY_NOT_REVERSIBLE` at 422 (payment reversal)."
    PRD §3.5: "The `transfer_date` must fall inside the closed interval of the
    policy's `BASE` term of type `STRUCTURAL` — on or after that term's
    `start_date` and on or before its `end_date` — and a date outside that
    window is refused with `ERR_COVERAGE_TERM_ELAPSED`."

    Design: Difficulty/priority_pair_validation_conflict/transfer_prefers_coverage_term_elapsed_over_transferee_is_current_owner
    """
    scenario = setup_active_policy()
    policy = scenario["policy"]
    owner_id = scenario["homeowner"]["id"]
    assert scenario["structural_term"]["end_date"] == CANONICAL_STRUCTURAL_TERM_END_DATE
    assert policy["coverage_status"] == "ACTIVE", (
        "the policy must stay ACTIVE so that no earlier state rung pre-empts the pair"
    )
    assert policy["current_owner_id"] == owner_id, (
        "the referential rule is broken by construction: the transferee is the holder"
    )

    response = api.create_transfer(
        policy["id"],
        create_transfer_payload(owner_id, policy["version"],
                                transfer_date="2036-08-15",
                                documents_reference="DEED-2036-0815"),
        make_homeowner_headers(owner_id),
    )
    error_data = validate_error(response, ApiErrorId.ERR_COVERAGE_TERM_ELAPSED.value)
    assert error_data["error_id"] != ApiErrorId.ERR_TRANSFEREE_IS_CURRENT_OWNER.value
    assert error_data["error_id"] != ApiErrorId.ERR_POLICY_NOT_ACTIVE.value

    transfers, meta = validate_paginated(
        api.list_transfers(underwriting_officer_headers,
                           {"policy_id": policy["id"], "limit": 100})
    )
    assert meta["total_count"] == 0, (
        f"the refused request must not create a transfer, got {meta['total_count']}"
    )
    after = read_policy(policy["id"])
    assert after["version"] == policy["version"], (
        "a refused request mutates nothing, so the policy version must not advance"
    )
    assert after["pending_transfer_id"] is None
