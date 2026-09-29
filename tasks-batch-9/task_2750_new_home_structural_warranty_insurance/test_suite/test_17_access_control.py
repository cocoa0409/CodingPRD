"""Access-control corner cases: the two header rungs of the validation ladder,
the two entity-backed ownership rungs, the segregation-of-duties rung, and the
positive half of the role matrix where each role performs its own work.

Every test builds its own world from scratch against a freshly restarted server
with an empty database.
"""

from test_helpers import (
    ADJUSTER_USER_ID,
    CANONICAL_CLOSING_INSTANT,
    NON_EXISTENT_UUID,
    SECOND_ADJUSTER_USER_ID,
    ApiErrorId,
    adjudication_payload,
    assert_same_instant,
    award_payload,
    builder_response_payload,
    create_approved_builder,
    create_builder_payload,
    create_claim_payload,
    create_coverage_term_payload,
    create_homeowner,
    create_homeowner_payload,
    create_neutral_payload,
    create_policy_payload,
    create_transfer_payload,
    enroll_policy,
    get_success_data,
    investigation_payload,
    invoice_policy,
    make_builder_principal_headers,
    make_claims_adjuster_headers,
    make_headers,
    make_homeowner_headers,
    payment_payload,
    premium_payment_payload,
    read_builder,
    read_claim,
    read_escalation_case,
    read_loss_monitor,
    read_policy,
    read_reserve_entries,
    set_clock,
    set_clock_payload,
    setup_active_policy,
    setup_approved_claim,
    setup_arbitration_case,
    setup_builder_arm_claim,
    setup_insurer_arm_claim,
    submit_builder_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

SECOND_BUILDER = {
    "company_name": "Larkspur Builders",
    "years_in_business": 8,
    "homes_closed_last_year": 60,
    "claims_history_score": 88,
    "financial_strength_tier": "TIER_2",
}


# ==========================================================================
# Table 7 RBAC — rungs 1 and 2 run ahead of everything else
# ==========================================================================
def test_absent_identity_headers_are_refused_before_the_request_is_examined(api):
    """A policy read carrying neither identity header.

    PRD Section 2.1: "Every request to this API — read or write — must carry two
    headers." "If either header is absent, empty, or consists only of whitespace,
    the request is refused with `ERR_UNAUTHENTICATED` and HTTP 401 before
    anything else about the request is examined."

    Design: Corner/Table 7 RBAC/missing_or_unknown_role_headers_are_rejected_before_any_ownership_check
    """
    scenario = setup_active_policy()

    response = api.get_policy(
        scenario["policy"]["id"], {"Content-Type": "application/json"}
    )

    validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)


def test_an_unauthenticated_read_of_an_unresolvable_policy_answers_401_not_404(
    api, underwriting_officer_headers
):
    """Rung 1 outranks the path-resolution rung, so the 404 is never reached.

    PRD Section 2.8: "Checks are evaluated in the ascending order below and **the
    first failure wins**; later checks are never reached and never mask an
    earlier one."

    PRD Section 2.1: "If either header is absent, empty, or consists only of
    whitespace, the request is refused with `ERR_UNAUTHENTICATED` and HTTP 401
    before anything else about the request is examined."

    PRD Section 2.6: "A request naming a builder that does not exist yields
    `ERR_BUILDER_NOT_FOUND`; a homeowner, `ERR_HOMEOWNER_NOT_FOUND`; a policy,
    `ERR_POLICY_NOT_FOUND`; a coverage term, `ERR_COVERAGE_TERM_NOT_FOUND`; a
    claim, `ERR_CLAIM_NOT_FOUND`; a transfer request, `ERR_TRANSFER_NOT_FOUND`;
    an escalation case, `ERR_ESCALATION_CASE_NOT_FOUND`; a neutral,
    `ERR_NEUTRAL_NOT_FOUND`; a reserve-journal entry,
    `ERR_RESERVE_ENTRY_NOT_FOUND`."

    Design: Corner/Table 7 RBAC/missing_or_unknown_role_headers_are_rejected_before_any_ownership_check
    """
    unauthenticated = api.get_policy(
        NON_EXISTENT_UUID, {"Content-Type": "application/json"}
    )
    validate_error(unauthenticated, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)

    # The very same path, authenticated, proves the identifier really is
    # unresolvable — so rung 1 masked a genuine rung-6 failure.
    authenticated = api.get_policy(NON_EXISTENT_UUID, underwriting_officer_headers)
    validate_error(authenticated, ApiErrorId.ERR_POLICY_NOT_FOUND.value, 404)


def test_a_blank_identity_header_is_treated_exactly_as_an_absent_one(api):
    """Whitespace-only header values are refused at rung 1.

    PRD Section 2.1: "If either header is absent, empty, or consists only of
    whitespace, the request is refused with `ERR_UNAUTHENTICATED` and HTTP 401
    before anything else about the request is examined."

    Design: Corner/Table 7 RBAC/missing_or_unknown_role_headers_are_rejected_before_any_ownership_check
    """
    scenario = setup_active_policy()
    policy_id = scenario["policy"]["id"]

    # HTTP forbids a whitespace-only field value on the wire, so "empty" is the
    # blank form the PRD sentence covers that a client can actually transmit.
    blank_user = api.get_policy(policy_id, make_headers("", "UnderwritingOfficer"))
    validate_error(blank_user, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)

    blank_role = api.get_policy(policy_id, make_headers("uw-officer-001", ""))
    validate_error(blank_role, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)


def test_an_undeclared_role_name_is_authenticated_but_never_permitted(api):
    """A syntactically valid role string that is not one of the five is a 403.

    PRD Section 2.1: "If both headers are present but the value of `X-User-Role`
    is not one of the five role names declared below, or is a declared role that
    does not appear in the authorized-roles list of the endpoint being called,
    the request is refused with `ERR_ROLE_NOT_PERMITTED` and HTTP 403."

    PRD Section 2.1: "The five roles are `UnderwritingOfficer`,
    `ComplianceOfficer`, `ClaimsAdjuster`, `BuilderPrincipal` and `Homeowner`."

    Design: Corner/Table 7 RBAC/missing_or_unknown_role_headers_are_rejected_before_any_ownership_check
    """
    scenario = setup_active_policy()

    response = api.get_policy(
        scenario["policy"]["id"], make_headers("auditor-001", "MarketConductAuditor")
    )

    validate_error(response, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, 403)


def test_a_declared_role_absent_from_the_endpoint_list_writes_nothing(
    api, underwriting_officer_headers
):
    """A `Homeowner` aimed at the underwriter-only builder create is refused and
    the builder table is left exactly as it was.

    PRD Section 2.1: "If both headers are present but the value of `X-User-Role`
    is not one of the five role names declared below, or is a declared role that
    does not appear in the authorized-roles list of the endpoint being called,
    the request is refused with `ERR_ROLE_NOT_PERMITTED` and HTTP 403."

    PRD Section 4, `POST /warranty/builders`: "Open a builder enrollment file
    with the six declared underwriting inputs; lands in `DRAFT` with no risk
    score." Authorized role: UnderwritingOfficer.

    Design: Corner/Table 7 RBAC/missing_or_unknown_role_headers_are_rejected_before_any_ownership_check
    """
    scenario = setup_active_policy()

    refused = api.create_builder(
        create_builder_payload(
            company_name="Interloper Homes",
            years_in_business=3,
            homes_closed_last_year=10,
            claims_history_score=90,
            financial_strength_tier="TIER_2",
        ),
        scenario["owner_headers"],
    )
    validate_error(refused, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, 403)

    _, meta = validate_paginated(
        api.list_builders(underwriting_officer_headers, {"limit": 100})
    )
    assert meta["total_count"] == 1, (
        "the refused create must not have written a builder file"
    )


# ==========================================================================
# Table 7 RBAC — no role reaches another role's exclusive operation
# ==========================================================================
def test_the_owning_homeowner_still_cannot_adjudicate_its_own_claim(api):
    """Adjudication belongs to the adjuster, so the claimant is refused on a row
    it is entitled to read.

    PRD Section 2.1: "If both headers are present but the value of `X-User-Role`
    is not one of the five role names declared below, or is a declared role that
    does not appear in the authorized-roles list of the endpoint being called,
    the request is refused with `ERR_ROLE_NOT_PERMITTED` and HTTP 403."

    PRD Section 3.7: "Adjudication closes the insurer arm's deliberation. A
    `ClaimsAdjuster` submits an `outcome` of `APPROVE` or `DENY` with an optional
    `adjudication_note`, from a claim in `INSURER_ADJUDICATION`, and in both
    branches the acting `X-User-ID` is recorded as the claim's
    `adjudicated_by_user_id` and the claim's `version` advances by 1."

    Design: Corner/Table 7 RBAC/a_homeowner_cannot_adjudicate_and_an_adjuster_cannot_enroll_a_home
    """
    scenario = setup_insurer_arm_claim(
        claimed_amount_cents=2_187_500, substantiation_ratio=0.80
    )
    claim_id = scenario["claim"]["id"]
    assert scenario["claim"]["status"] == "INSURER_ADJUDICATION"

    response = api.create_adjudication(
        claim_id, adjudication_payload("APPROVE"), scenario["owner_headers"]
    )
    validate_error(response, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, 403)

    after = read_claim(claim_id)
    assert after["status"] == "INSURER_ADJUDICATION"
    assert after["adjudicated_by_user_id"] is None
    assert after["version"] == scenario["claim"]["version"]


def test_a_claims_adjuster_cannot_enroll_a_home(api, claims_adjuster_headers):
    """Home enrollment is the builder's act; the adjuster is not on that list.

    PRD Section 2.1: "If both headers are present but the value of `X-User-Role`
    is not one of the five role names declared below, or is a declared role that
    does not appear in the authorized-roles list of the endpoint being called,
    the request is refused with `ERR_ROLE_NOT_PERMITTED` and HTTP 403."

    PRD Section 3.3: "Enrollment itself is the builder's act, performed at
    closing."

    Design: Corner/Table 7 RBAC/a_homeowner_cannot_adjudicate_and_an_adjuster_cannot_enroll_a_home
    """
    scenario = setup_active_policy()

    response = api.create_policy(
        create_policy_payload(
            scenario["builder"]["id"],
            scenario["homeowner"]["id"],
            street_address="9 Adjuster Way",
            purchase_price_cents=5_000_000,
        ),
        claims_adjuster_headers,
    )
    validate_error(response, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, 403)

    _, meta = validate_paginated(
        api.list_policies(claims_adjuster_headers, {"limit": 100})
    )
    assert meta["total_count"] == 1, (
        "the refused enrollment must not have written a policy"
    )


def test_a_builder_principal_activating_its_own_policy_hears_403_not_a_state_conflict(
    api,
):
    """Rung 2 runs long before the state machine: activating an already-ACTIVE
    policy would also be a conflict, and the role check still wins.

    PRD Section 2.8: "Checks are evaluated in the ascending order below and **the
    first failure wins**; later checks are never reached and never mask an
    earlier one."

    PRD Section 2.8, rung 2: "**Role admission (403).** `X-User-Role` is one of
    the five declared roles and is listed on the called endpoint, or
    `ERR_ROLE_NOT_PERMITTED`. Applies to every endpoint."

    PRD Section 3.4: "The policy must be in `PENDING_ENROLLMENT` on the coverage
    axis, or `ERR_INVALID_POLICY_STATE`."

    Design: Corner/Table 7 RBAC/a_homeowner_cannot_adjudicate_and_an_adjuster_cannot_enroll_a_home
    """
    scenario = setup_active_policy()
    policy_id = scenario["policy"]["id"]

    response = api.activate_policy(policy_id, scenario["builder_headers"])
    validate_error(response, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, 403)

    after = read_policy(policy_id)
    assert after["coverage_status"] == "ACTIVE"
    assert after["version"] == scenario["policy"]["version"]


def test_an_underwriting_officer_filing_a_claim_hears_403_not_the_ownership_error(
    api, underwriting_officer_headers
):
    """The role check at rung 2 precedes the homeowner-ownership check at rung 4,
    even though the underwriter's opaque identifier can never be an owner.

    PRD Section 2.8: "Checks are evaluated in the ascending order below and **the
    first failure wins**; later checks are never reached and never mask an
    earlier one."

    PRD Section 2.8, rung 4: "**Homeowner ownership (403).**
    `ERR_NOT_POLICY_OWNER`, on exactly four operations: transfer request
    creation, transfer resubmission, claim filing, and the opening of an
    escalation rung."

    PRD Section 3.6: "The homeowner who currently holds the warranty files the
    claim."

    Design: Corner/Table 7 RBAC/a_homeowner_cannot_adjudicate_and_an_adjuster_cannot_enroll_a_home
    """
    scenario = setup_active_policy()

    response = api.create_claim(
        create_claim_payload(
            scenario["policy"]["id"],
            damage_description="Filed by the underwriter",
            claimed_amount_cents=100_000,
        ),
        underwriting_officer_headers,
    )
    validate_error(response, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, 403)

    _, meta = validate_paginated(
        api.list_claims(underwriting_officer_headers, {"limit": 100})
    )
    assert meta["total_count"] == 0, "the refused intake must not have written a claim"


def test_an_underwriting_officer_cannot_move_the_logical_clock(
    api, underwriting_officer_headers
):
    """Moving the clock is compliance's exclusive operation, and the refusal
    leaves the clock exactly where it was.

    PRD Section 2.1: "A `ComplianceOfficer` handles market conduct. It suspends
    builders, declares builders in default, curates the panel of neutrals, and is
    the only role permitted to reverse a payment that has already been disbursed
    or to move the server's logical clock."

    PRD Section 3.4: "The clock never regresses: an instant earlier than the
    current one is refused with `ERR_CLOCK_REGRESSION`."

    Design: Corner/Table 7 RBAC/a_homeowner_cannot_adjudicate_and_an_adjuster_cannot_enroll_a_home
    """
    setup_active_policy()

    response = api.set_clock(
        set_clock_payload("2026-09-01T00:00:00Z"), underwriting_officer_headers
    )
    validate_error(response, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, 403)

    # Re-setting the clock to the instant it already holds is not a regression,
    # so this succeeds and reports where the clock actually stands.
    reasserted = set_clock(CANONICAL_CLOSING_INSTANT)
    assert_same_instant(reasserted["current_utc"], CANONICAL_CLOSING_INSTANT)


# ==========================================================================
# Table 7 RBAC — rung 3, the builder-principal ownership check
# ==========================================================================
def test_a_builder_cannot_pay_the_premium_on_another_builders_home(api):
    """The premium invoice belongs to the enrolling builder's file, and an
    outsider holding the right role is still refused.

    PRD Section 2.1: "Concretely, the addressed builder is either the builder
    named in the URL path, or the `builder_id` of the addressed policy, or the
    `builder_id` of the policy behind the addressed claim, and a mismatch is
    refused with `ERR_NOT_BUILDER_PRINCIPAL` and HTTP 403. This check guards
    builder submission, home enrollment, premium payment, the builder's response
    to an obligation notice, and the report of a completed repair."

    PRD Section 2.8, rung 3: "**Builder-principal ownership (403).**
    `ERR_NOT_BUILDER_PRINCIPAL`, on exactly five operations: builder submission,
    home enrollment, premium payment, the builder's obligation response, and the
    report of repair completion."

    Design: Corner/Table 7 RBAC/a_builder_principal_cannot_act_on_another_builders_policy
    """
    host = create_approved_builder()
    buyer = create_homeowner()
    set_clock(CANONICAL_CLOSING_INSTANT)
    policy = enroll_policy(host["id"], buyer["id"])
    invoice_policy(policy["id"])
    intruder = create_approved_builder(**SECOND_BUILDER)

    response = api.create_premium_payment(
        policy["id"],
        premium_payment_payload(),
        make_builder_principal_headers(intruder["id"]),
    )
    validate_error(response, ApiErrorId.ERR_NOT_BUILDER_PRINCIPAL.value, 403)

    after = read_policy(policy["id"])
    assert after["premium_status"] == "INVOICED"
    assert after["coverage_status"] == "PENDING_ENROLLMENT"


def test_a_builder_cannot_answer_the_obligation_notice_on_another_builders_claim(api):
    """The obligation response reaches through the claim to the policy's builder.

    PRD Section 2.1: "Concretely, the addressed builder is either the builder
    named in the URL path, or the `builder_id` of the addressed policy, or the
    `builder_id` of the policy behind the addressed claim, and a mismatch is
    refused with `ERR_NOT_BUILDER_PRINCIPAL` and HTTP 403. This check guards
    builder submission, home enrollment, premium payment, the builder's response
    to an obligation notice, and the report of a completed repair."

    PRD Section 3.7: "A `BuilderPrincipal`, whose `X-User-ID` must equal the
    `builder_id` of the claim's policy, submits a `response` of either
    `ACCEPT_OBLIGATION` or `REFUSE_OBLIGATION` with an optional `response_note`."

    Design: Corner/Table 7 RBAC/a_builder_principal_cannot_act_on_another_builders_policy
    """
    scenario = setup_builder_arm_claim(
        claimed_amount_cents=2_187_500, substantiation_ratio=0.80
    )
    claim_id = scenario["claim"]["id"]
    assert scenario["claim"]["obligor"] == "BUILDER"
    assert scenario["claim"]["status"] == "BUILDER_OBLIGATION_NOTICE"
    intruder = create_approved_builder(**SECOND_BUILDER)

    response = api.create_builder_response(
        claim_id,
        builder_response_payload("ACCEPT_OBLIGATION"),
        make_builder_principal_headers(intruder["id"]),
    )
    validate_error(response, ApiErrorId.ERR_NOT_BUILDER_PRINCIPAL.value, 403)

    after = read_claim(claim_id)
    assert after["status"] == "BUILDER_OBLIGATION_NOTICE"
    assert after["version"] == scenario["claim"]["version"]


def test_a_builder_submitting_another_builders_file_hears_403_not_a_state_conflict(api):
    """Rung 3 outranks the from-state rung at 12: the addressed file is APPROVED
    and could never be submitted, yet the ownership error is what comes back.

    PRD Section 2.8: "Checks are evaluated in the ascending order below and **the
    first failure wins**; later checks are never reached and never mask an
    earlier one."

    PRD Section 2.8, rung 3: "**Builder-principal ownership (403).**
    `ERR_NOT_BUILDER_PRINCIPAL`, on exactly five operations: builder submission,
    home enrollment, premium payment, the builder's obligation response, and the
    report of repair completion."

    PRD Section 2.8, rung 12: "The addressed row is in a declared origin state
    for the requested transition, or the matching state error:
    `ERR_INVALID_BUILDER_STATE`, `ERR_INVALID_POLICY_STATE` for the coverage
    axis, `ERR_INVALID_PREMIUM_STATE` for the premium axis,
    `ERR_INVALID_CLAIM_STATE`, `ERR_INVALID_TRANSFER_STATE`,
    `ERR_INVALID_ESCALATION_STATE`, or `ERR_INVALID_NEUTRAL_STATE`."

    Design: Corner/Table 7 RBAC/a_builder_principal_cannot_act_on_another_builders_policy
    """
    host = create_approved_builder()
    intruder = create_approved_builder(**SECOND_BUILDER)
    assert host["underwriting_status"] == "APPROVED"

    response = api.submit_builder(
        host["id"],
        submit_builder_payload(),
        make_builder_principal_headers(intruder["id"]),
    )
    validate_error(response, ApiErrorId.ERR_NOT_BUILDER_PRINCIPAL.value, 403)

    after = read_builder(host["id"])
    assert after["underwriting_status"] == "APPROVED"
    assert after["version"] == host["version"]


def test_a_homeowner_cannot_request_a_transfer_of_a_home_it_does_not_hold(api):
    """Rung 4 compares the policy's `current_owner_id` to the acting identity,
    and a correct `expected_policy_version` does not buy the stranger anything.

    PRD Section 2.1: "When `X-User-Role` is `Homeowner`, `X-User-ID` is the `id`
    of the acting `Homeowner` row; ownership checks compare the addressed
    policy's `current_owner_id` to `X-User-ID`, with one exception — on the
    resubmission of a transfer request the comparison is against that request's
    `requested_by_owner_id` instead, because a policy can change hands while a
    request is in flight."

    PRD Section 2.1: "A mismatch is refused with `ERR_NOT_POLICY_OWNER` and HTTP
    403. This check guards transfer requests, transfer resubmission, claim
    filing, and the opening of an escalation rung."

    Design: Corner/Table 7 RBAC/a_builder_principal_cannot_act_on_another_builders_policy
    """
    scenario = setup_active_policy()
    policy_id = scenario["policy"]["id"]
    newcomer = create_homeowner(
        full_name="Bob Crane", email="bob.crane@example.com"
    )

    response = api.create_transfer(
        policy_id,
        create_transfer_payload(newcomer["id"], scenario["policy"]["version"]),
        make_homeowner_headers(newcomer["id"]),
    )
    validate_error(response, ApiErrorId.ERR_NOT_POLICY_OWNER.value, 403)

    after = read_policy(policy_id)
    assert after["current_owner_id"] == scenario["homeowner"]["id"]
    assert after["pending_transfer_id"] is None
    assert after["transfer_count"] == 0
    assert after["version"] == scenario["policy"]["version"]


# ==========================================================================
# Table 7 RBAC — rung 5, segregation of duties on disbursement
# ==========================================================================
def test_the_adjudicating_adjuster_may_not_disburse_on_that_claim(api):
    """The adjuster stamped as `adjudicated_by_user_id` is refused, and no money
    or journal row appears.

    PRD Section 2.10: "First, the `ClaimsAdjuster` whose `X-User-ID` was recorded
    as a claim's `adjudicated_by_user_id` may not disburse money on that claim; a
    payment request whose `X-User-ID` equals the claim's
    `adjudicated_by_user_id` is refused with `ERR_SEGREGATION_OF_DUTIES` and HTTP
    403."

    PRD Section 3.8: "Disbursement is also the adjuster's operation, subject to
    the segregation-of-duties rule of §2.10 — the adjuster recorded as the
    claim's `adjudicated_by_user_id` may not pay it."

    Design: Corner/Table 7 RBAC/the_adjudicating_adjuster_cannot_pay_the_claim
    """
    scenario = setup_approved_claim(
        claimed_amount_cents=2_187_500,
        substantiation_ratio=0.80,
        adjuster_user_id=ADJUSTER_USER_ID,
    )
    claim_id = scenario["claim"]["id"]
    assert scenario["claim"]["adjudicated_by_user_id"] == ADJUSTER_USER_ID
    assert scenario["claim"]["reserve_cents"] == 1_518_000

    response = api.create_payment(
        claim_id,
        payment_payload(500_000),
        make_claims_adjuster_headers(ADJUSTER_USER_ID),
    )
    validate_error(response, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403)

    after = read_claim(claim_id)
    assert after["paid_cents"] == 0
    assert after["reserve_cents"] == 1_518_000
    assert after["status"] == "APPROVED"
    assert after["version"] == scenario["claim"]["version"]
    assert read_reserve_entries(claim_id, entry_type="PAYMENT") == []


def test_the_adjudicator_hears_the_duties_error_before_any_fiscal_ceiling(api):
    """Rung 5 sits far above the fiscal guards at rung 17, so an amount that also
    blows through the reserve is refused for the identity, not the amount.

    PRD Section 2.8: "Checks are evaluated in the ascending order below and **the
    first failure wins**; later checks are never reached and never mask an
    earlier one."

    PRD Section 2.8, rung 5: "**Segregation of duties (403).**
    `ERR_SEGREGATION_OF_DUTIES`, on exactly two operations: claim payment and
    arbitration award."

    PRD Section 3.8: "Two ceilings then apply, in order: the amount may not
    exceed the claim's `reserve_cents`, or `ERR_PAYMENT_EXCEEDS_RESERVE`; and it
    may not exceed the `remaining_limit_cents` of the claim's coverage term, or
    `ERR_COVERAGE_LIMIT_EXCEEDED`."

    Design: Corner/Table 7 RBAC/the_adjudicating_adjuster_cannot_pay_the_claim
    """
    scenario = setup_approved_claim(
        claimed_amount_cents=2_187_500,
        substantiation_ratio=0.80,
        adjuster_user_id=ADJUSTER_USER_ID,
    )
    claim_id = scenario["claim"]["id"]

    response = api.create_payment(
        claim_id,
        payment_payload(9_000_000),
        make_claims_adjuster_headers(ADJUSTER_USER_ID),
    )
    validate_error(response, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403)

    after = read_claim(claim_id)
    assert after["paid_cents"] == 0
    assert after["reserve_cents"] == 1_518_000


def test_a_second_adjuster_disburses_the_very_payment_the_adjudicator_was_denied(api):
    """The identical request from a different operator succeeds, which proves the
    refusal turned on the identity alone.

    PRD Section 2.10: "First, the `ClaimsAdjuster` whose `X-User-ID` was recorded
    as a claim's `adjudicated_by_user_id` may not disburse money on that claim; a
    payment request whose `X-User-ID` equals the claim's
    `adjudicated_by_user_id` is refused with `ERR_SEGREGATION_OF_DUTIES` and HTTP
    403."

    PRD Section 3.8: "It appends a journal row of `entry_type` `PAYMENT` with
    `recorded_by_user_id` set to the acting `X-User-ID`. It moves money on the
    claim: `amount_cents` is added to `paid_cents` and subtracted from
    `reserve_cents`, leaving `incurred_authorized_cents` untouched."

    Design: Corner/Table 7 RBAC/the_adjudicating_adjuster_cannot_pay_the_claim
    """
    scenario = setup_approved_claim(
        claimed_amount_cents=2_187_500,
        substantiation_ratio=0.80,
        adjuster_user_id=ADJUSTER_USER_ID,
    )
    claim_id = scenario["claim"]["id"]

    get_success_data(
        api.create_payment(
            claim_id,
            payment_payload(500_000),
            make_claims_adjuster_headers(SECOND_ADJUSTER_USER_ID),
        )
    )

    entries = read_reserve_entries(claim_id, entry_type="PAYMENT")
    assert len(entries) == 1
    assert entries[0]["recorded_by_user_id"] == SECOND_ADJUSTER_USER_ID
    assert entries[0]["amount_cents"] == 500_000
    assert entries[0]["balance_after_paid_cents"] == 500_000
    assert entries[0]["balance_after_reserve_cents"] == 1_018_000

    after = read_claim(claim_id)
    assert after["paid_cents"] == 500_000
    assert after["reserve_cents"] == 1_018_000
    assert after["incurred_authorized_cents"] == 1_518_000
    assert after["status"] == "APPROVED"


# ==========================================================================
# Table 7 RBAC — rung 5 again, this time across two escalation rungs
# ==========================================================================
def test_the_mediation_outcome_adjuster_may_not_issue_the_arbitration_award(api):
    """The refusal reaches back through the arbitration case's `prior_case_id` to
    the mediation case's `outcome_recorded_by_user_id`.

    PRD Section 2.10: "Second, the adjuster whose `X-User-ID` was recorded as
    `outcome_recorded_by_user_id` on a mediation case may not issue the award on
    the arbitration case that succeeds it; an award request whose `X-User-ID`
    equals the `outcome_recorded_by_user_id` of the case named by the
    arbitration's `prior_case_id` is refused with the same error and status."

    Design: Corner/Table 7 RBAC/the_mediation_outcome_adjuster_cannot_issue_the_arbitration_award
    """
    scenario = setup_arbitration_case(
        mediation_outcome_adjuster=ADJUSTER_USER_ID,
        adjuster_user_id=ADJUSTER_USER_ID,
        claimed_amount_cents=2_187_500,
        substantiation_ratio=0.80,
    )
    arbitration_case_id = scenario["arbitration_case"]["id"]
    claim_id = scenario["claim"]["id"]
    mediation = read_escalation_case(scenario["mediation_case"]["id"])
    assert mediation["outcome_recorded_by_user_id"] == ADJUSTER_USER_ID
    assert scenario["arbitration_case"]["prior_case_id"] == mediation["id"]
    assert scenario["arbitration_case"]["binding"] is True
    set_clock("2028-09-20T15:00:00Z")

    response = api.create_award(
        arbitration_case_id,
        award_payload(500_000),
        make_claims_adjuster_headers(ADJUSTER_USER_ID),
    )
    validate_error(response, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403)

    case_after = read_escalation_case(arbitration_case_id)
    assert case_after["status"] == "SCHEDULED"
    assert case_after["award_amount_cents"] is None
    assert case_after["version"] == scenario["arbitration_case"]["version"]

    claim_after = read_claim(claim_id)
    assert claim_after["status"] == "ARBITRATION"
    assert claim_after["reserve_cents"] == 0
    assert claim_after["released_cents"] == 1_518_000


def test_a_different_adjuster_issues_the_award_the_mediator_was_denied(api):
    """The same award from an untainted operator lands, closing the claim
    `CLOSED_AWARDED` and re-reserving the awarded amount.

    PRD Section 2.10: "Second, the adjuster whose `X-User-ID` was recorded as
    `outcome_recorded_by_user_id` on a mediation case may not issue the award on
    the arbitration case that succeeds it; an award request whose `X-User-ID`
    equals the `outcome_recorded_by_user_id` of the case named by the
    arbitration's `prior_case_id` is refused with the same error and status."

    PRD Section 3.9: "When `award_amount_cents` is greater than 0, the claim
    advances `ARBITRATION → CLOSED_AWARDED`, its `incurred_authorized_cents` is
    set to the sum of its `paid_cents`, its `released_cents` and the awarded
    amount, and its `reserve_cents` is set to the awarded amount."

    Design: Corner/Table 7 RBAC/the_mediation_outcome_adjuster_cannot_issue_the_arbitration_award
    """
    scenario = setup_arbitration_case(
        mediation_outcome_adjuster=ADJUSTER_USER_ID,
        adjuster_user_id=ADJUSTER_USER_ID,
        claimed_amount_cents=2_187_500,
        substantiation_ratio=0.80,
    )
    arbitration_case_id = scenario["arbitration_case"]["id"]
    claim_id = scenario["claim"]["id"]
    set_clock("2028-09-20T15:00:00Z")

    get_success_data(
        api.create_award(
            arbitration_case_id,
            award_payload(500_000),
            make_claims_adjuster_headers(SECOND_ADJUSTER_USER_ID),
        )
    )

    case_after = read_escalation_case(arbitration_case_id)
    assert case_after["status"] == "AWARD_ISSUED"
    assert case_after["award_amount_cents"] == 500_000

    claim_after = read_claim(claim_id)
    assert claim_after["status"] == "CLOSED_AWARDED"
    assert claim_after["paid_cents"] == 0
    assert claim_after["reserve_cents"] == 500_000
    assert claim_after["released_cents"] == 1_518_000
    assert claim_after["incurred_authorized_cents"] == 2_018_000

    monitor = read_loss_monitor(scenario["builder"]["id"])
    assert monitor["incurred_loss_cents"] == 500_000
    assert monitor["loss_ratio"] == 1.3740
    assert monitor["monitoring_posture"] == "FROZEN"


# ==========================================================================
# Table 7 RBAC — the positive half of the matrix
# ==========================================================================
def test_compliance_moves_the_clock_and_curates_the_neutral_panel(
    api, compliance_officer_headers
):
    """The two operations §2.1 reserves to compliance both succeed for it.

    PRD Section 2.1: "A `ComplianceOfficer` handles market conduct. It suspends
    builders, declares builders in default, curates the panel of neutrals, and is
    the only role permitted to reverse a payment that has already been disbursed
    or to move the server's logical clock."

    PRD Section 4: "Status codes follow one rule throughout: an operation that
    brings a **new** resource into existence answers 201 Created, and every other
    successful operation — state transitions, decisions, payments, reads and list
    queries — answers 200 OK."

    Design: Corner/Table 7 RBAC/each_role_performs_its_own_exclusive_operations_and_the_shared_reads
    """
    moved = validate_success(
        api.set_clock(
            set_clock_payload("2028-09-01T00:00:00Z"), compliance_officer_headers
        ),
        200,
    )
    assert_same_instant(moved["current_utc"], "2028-09-01T00:00:00Z")

    neutral = validate_success(
        api.create_neutral(create_neutral_payload(), compliance_officer_headers), 201
    )
    assert neutral["status"] == "ACTIVE"
    assert neutral["booked_session_count"] == 0


def test_the_underwriter_endorses_coverage_and_the_builder_registers_a_buyer(
    api, underwriting_officer_headers
):
    """Endorsement is the underwriter's alone, while buyer registration is one of
    the two operations §2.1 shares with the builder.

    PRD Section 3.3: "Coverage can be extended after the fact. An
    `UnderwritingOfficer` attaches an endorsement term to a policy by supplying a
    `coverage_type`, a `start_date`, an `end_date` that is not earlier than the
    `start_date`, a `limit_cents` of at least 1, and a `deductible_cents` of at
    least 0. The new term is born with `term_kind` `ENDORSEMENT`, `status` `OPEN`,
    `consumed_limit_cents` of 0 and `remaining_limit_cents` equal to its
    `limit_cents`, and the policy's `version` advances by 1."

    PRD Section 2.1: "Registering a homeowner is shared between
    `UnderwritingOfficer` and `BuilderPrincipal`."

    Design: Corner/Table 7 RBAC/each_role_performs_its_own_exclusive_operations_and_the_shared_reads
    """
    scenario = setup_active_policy()

    term = validate_success(
        api.create_coverage_term(
            scenario["policy"]["id"],
            create_coverage_term_payload(
                coverage_type="WORKMANSHIP",
                start_date="2028-09-01",
                end_date="2029-08-31",
                limit_cents=1_000_000,
                deductible_cents=100_000,
            ),
            underwriting_officer_headers,
        ),
        201,
    )
    assert term["term_kind"] == "ENDORSEMENT"
    assert term["status"] == "OPEN"
    assert term["consumed_limit_cents"] == 0
    assert term["remaining_limit_cents"] == 1_000_000

    buyer = validate_success(
        api.create_homeowner(
            create_homeowner_payload(
                full_name="Dana Ruiz", email="dana.ruiz@example.com"
            ),
            scenario["builder_headers"],
        ),
        201,
    )
    assert buyer["full_name"] == "Dana Ruiz"


def test_the_owner_files_the_claim_and_the_adjuster_investigates_it(
    api, claims_adjuster_headers
):
    """Intake belongs to the holder of the warranty and investigation to the
    adjuster, and each lands on the other's row.

    PRD Section 3.6: "A fresh claim lands in `status` `SUBMITTED` with
    `designated_structural` false and with all four money fields —
    `reserve_cents`, `paid_cents`, `released_cents` and
    `incurred_authorized_cents` — at 0."

    PRD Section 3.6: "Investigation is the adjuster's first move. A
    `ClaimsAdjuster` records a `substantiation_ratio` — the share of the claimed
    amount the carrier accepts as substantiated, between 0.00 and 1.00 inclusive
    with at most two decimal places — and the claim advances from `SUBMITTED` to
    `UNDER_INVESTIGATION`."

    Design: Corner/Table 7 RBAC/each_role_performs_its_own_exclusive_operations_and_the_shared_reads
    """
    scenario = setup_active_policy()

    claim = validate_success(
        api.create_claim(
            create_claim_payload(
                scenario["policy"]["id"], claimed_amount_cents=2_187_500
            ),
            scenario["owner_headers"],
        ),
        201,
    )
    assert claim["status"] == "SUBMITTED"
    assert claim["filed_by_owner_id"] == scenario["homeowner"]["id"]
    assert claim["gross_adjusted_cents"] == 0

    investigated = validate_success(
        api.create_investigation(
            claim["id"], investigation_payload(0.80), claims_adjuster_headers
        ),
        200,
    )
    assert investigated["status"] == "UNDER_INVESTIGATION"
    assert investigated["gross_adjusted_cents"] == 1_750_000


def test_all_five_roles_read_the_same_home(
    api, underwriting_officer_headers, compliance_officer_headers,
    claims_adjuster_headers
):
    """The policy read is shared, so each of the five roles sees the identical row.

    PRD Section 2.1: "Read endpoints are shared broadly. Every carrier-side role
    may read every resource under `/warranty`. A `BuilderPrincipal` may read
    builder files, policies and their coverage terms, individual coverage terms,
    claims and engineering assessments. A `Homeowner` may read homeowner records,
    policies and coverage terms, the neutral panel, transfer requests, claims,
    engineering assessments and escalation cases."

    Design: Corner/Table 7 RBAC/each_role_performs_its_own_exclusive_operations_and_the_shared_reads
    """
    scenario = setup_active_policy()
    policy_id = scenario["policy"]["id"]

    for headers in (
        underwriting_officer_headers,
        compliance_officer_headers,
        claims_adjuster_headers,
        scenario["builder_headers"],
        scenario["owner_headers"],
    ):
        seen = validate_success(api.get_policy(policy_id, headers), 200)
        assert seen["id"] == policy_id
        assert seen["coverage_status"] == "ACTIVE"
        assert seen["premium_status"] == "PAID"
        assert seen["version"] == scenario["policy"]["version"]
