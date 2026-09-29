"""The error catalogue seen from three angles: identifiers that do not resolve
(in the path and in the body), a rejected page window, and transitions replayed
against a row that has already left the origin state.

Every test builds its own world from scratch through PRD-declared endpoints,
because the server is restarted with an empty database before each test.
"""

import pytest

from test_helpers import (
    ADJUSTER_USER_ID,
    INSURER_PERIOD_INSTANT,
    SECOND_ADJUSTER_USER_ID,
    ApiErrorId,
    adjudication_payload,
    assert_claim,
    assert_escalation_case,
    assert_neutral,
    assert_policy,
    assert_structural_assessment,
    create_claim_payload,
    create_escalation_payload,
    create_homeowner,
    create_neutral,
    create_transfer_payload,
    deactivate_neutral_payload,
    enroll_policy,
    file_claim,
    find_term,
    invoice_policy,
    make_builder_principal_headers,
    make_claims_adjuster_headers,
    make_homeowner_headers,
    payment_reversal_payload,
    premium_invoice_payload,
    read_builder,
    read_claim,
    read_coverage_terms,
    read_neutral,
    read_policy,
    read_transfer,
    request_transfer,
    session_outcome_payload,
    set_clock,
    setup_active_policy,
    setup_mediation_case,
    setup_routed_claim,
    structural_assessment_payload,
    submit_builder_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

# A syntactically valid UUID that is never assigned to any row.
UNASSIGNED_UUID = "00000000-0000-4000-8000-000000000000"


@pytest.mark.parametrize(
    "accessor,expected_error_id",
    [
        ("get_builder", ApiErrorId.ERR_BUILDER_NOT_FOUND),
        ("get_homeowner", ApiErrorId.ERR_HOMEOWNER_NOT_FOUND),
        ("get_policy", ApiErrorId.ERR_POLICY_NOT_FOUND),
        ("get_coverage_term", ApiErrorId.ERR_COVERAGE_TERM_NOT_FOUND),
        ("get_claim", ApiErrorId.ERR_CLAIM_NOT_FOUND),
        ("get_transfer", ApiErrorId.ERR_TRANSFER_NOT_FOUND),
        ("get_escalation_case", ApiErrorId.ERR_ESCALATION_CASE_NOT_FOUND),
        ("get_neutral", ApiErrorId.ERR_NEUTRAL_NOT_FOUND),
        ("get_reserve_entry", ApiErrorId.ERR_RESERVE_ENTRY_NOT_FOUND),
    ],
)
def test_path_ids_that_do_not_resolve_return_each_entity_specific_not_found(
    api, underwriting_officer_headers, accessor, expected_error_id
):
    """Against a wholly empty database, every single-resource read of an
    unassigned identifier answers the not-found code belonging to that entity
    type - never a shared generic code and never an authorisation refusal.

    PRD Section 2.6: "Path parameters are resolved strictly left to right, and the
    first identifier that fails to resolve determines the error. A request naming a
    builder that does not exist yields `ERR_BUILDER_NOT_FOUND`; a homeowner,
    `ERR_HOMEOWNER_NOT_FOUND`; a policy, `ERR_POLICY_NOT_FOUND`; a coverage term,
    `ERR_COVERAGE_TERM_NOT_FOUND`; a claim, `ERR_CLAIM_NOT_FOUND`; a transfer
    request, `ERR_TRANSFER_NOT_FOUND`; an escalation case,
    `ERR_ESCALATION_CASE_NOT_FOUND`; a neutral, `ERR_NEUTRAL_NOT_FOUND`; a
    reserve-journal entry, `ERR_RESERVE_ENTRY_NOT_FOUND`. All nine are HTTP 404."

    The acting principal is an `UnderwritingOfficer`, which appears in the
    authorized-roles list of all nine reads, so nothing here can be answered with
    `ERR_UNAUTHENTICATED` or `ERR_ROLE_NOT_PERMITTED`.

    Design: Corner/Table 6 Errors/path_ids_that_do_not_resolve_return_each_entity_specific_not_found
    """
    response = getattr(api, accessor)(UNASSIGNED_UUID, underwriting_officer_headers)
    validate_error(response, expected_error_id.value)


def test_body_foreign_keys_that_do_not_resolve_return_not_found_for_the_named_entity(
    api, compliance_officer_headers
):
    """An unresolvable foreign key carried in a request body answers with the
    not-found code of the entity that key names, and it does so ahead of every
    ownership, state, credential and reversibility guard that the same request
    would also have failed.

    PRD Section 2.6: "The same catalogue applies to foreign keys supplied in a
    request body rather than in the path. A `builder_id` that does not resolve
    yields `ERR_BUILDER_NOT_FOUND`; an `initial_owner_id` or `new_owner_id`,
    `ERR_HOMEOWNER_NOT_FOUND`; a `policy_id`, `ERR_POLICY_NOT_FOUND`; a
    `neutral_id`, `ERR_NEUTRAL_NOT_FOUND`; a `prior_case_id`,
    `ERR_ESCALATION_CASE_NOT_FOUND`; a `reserve_entry_id`,
    `ERR_RESERVE_ENTRY_NOT_FOUND`. Body-level foreign-key resolution is checked on
    home enrollment, on transfer request creation, on claim filing, on the opening
    of an escalation rung, and on a payment reversal."

    PRD Section 2.8, rung 7: "Body foreign-key existence (404). Every foreign key
    in the request body resolves, per Section 2.6. Applies to home enrollment,
    transfer request creation, claim filing, escalation opening, and payment
    reversal." Rung 7 sits ahead of optimistic concurrency at rung 11, from-state
    admission at rung 12, the neutral-eligibility pair at rung 13, mediation
    exhaustion at rung 14 and `ERR_ENTRY_NOT_REVERSIBLE` at rung 16.

    PRD Section 2.1: "When `X-User-Role` is `Homeowner`, `X-User-ID` is the `id` of
    the acting `Homeowner` row; ownership checks compare the addressed policy's
    `current_owner_id` to `X-User-ID` ... A mismatch is refused with
    `ERR_NOT_POLICY_OWNER` and HTTP 403." The comparison needs a resolved policy,
    so a claim filed by a genuinely registered buyer against a `policy_id` that
    names nothing answers `ERR_POLICY_NOT_FOUND` and not an ownership refusal.

    Design: Corner/Table 6 Errors/body_foreign_keys_that_do_not_resolve_return_not_found_for_the_named_entity
    """
    scenario = setup_mediation_case(
        neutral_overrides={"full_name": "Marcia Vance", "credential": "MEDIATOR"},
        window_start="2028-09-20T14:00:00Z",
        window_end="2028-09-20T18:00:00Z",
        claimed_amount_cents=2_187_500,
        substantiation_ratio=0.80,
        coverage_type="STRUCTURAL",
        defect_category="WATER_INTRUSION",
    )
    policy = read_policy(scenario["policy"]["id"])
    claim = scenario["claim"]
    neutral = scenario["neutral"]
    owner_headers = make_homeowner_headers(scenario["homeowner"]["id"])
    assert claim["status"] == "MEDIATION"
    assert policy["coverage_status"] == "ACTIVE"

    # new_owner_id names nobody: the transferee is a homeowner, so this is the
    # homeowner code even though the acting caller is a valid owner.
    validate_error(
        api.create_transfer(
            policy["id"],
            create_transfer_payload(UNASSIGNED_UUID, policy["version"],
                                    transfer_date="2028-09-05"),
            owner_headers,
        ),
        ApiErrorId.ERR_HOMEOWNER_NOT_FOUND.value,
    )

    # policy_id names nobody, so there is no current_owner_id to compare against.
    validate_error(
        api.create_claim(
            create_claim_payload(UNASSIGNED_UUID, coverage_type="STRUCTURAL",
                                 defect_category="WATER_INTRUSION",
                                 claimed_amount_cents=400_000),
            owner_headers,
        ),
        ApiErrorId.ERR_POLICY_NOT_FOUND.value,
    )

    # The claim already sits in MEDIATION, which is not an origin state for a
    # mediation booking - but the unresolved neutral is reported first.
    validate_error(
        api.create_escalation(
            claim["id"],
            create_escalation_payload(UNASSIGNED_UUID, "MEDIATION",
                                      "2028-09-28T14:00:00Z",
                                      "2028-09-28T18:00:00Z"),
            owner_headers,
        ),
        ApiErrorId.ERR_NEUTRAL_NOT_FOUND.value,
    )

    # The booked neutral holds only a MEDIATOR credential, so an arbitration on it
    # would also fail rung 13 - but the unresolved prior case is reported first.
    assert neutral["credential"] == "MEDIATOR"
    validate_error(
        api.create_escalation(
            claim["id"],
            create_escalation_payload(neutral["id"], "ARBITRATION",
                                      "2028-09-28T14:00:00Z",
                                      "2028-09-28T18:00:00Z",
                                      prior_case_id=UNASSIGNED_UUID),
            owner_headers,
        ),
        ApiErrorId.ERR_ESCALATION_CASE_NOT_FOUND.value,
    )

    # No payment entry exists on this claim at all, so ERR_ENTRY_NOT_REVERSIBLE at
    # rung 16 is unreachable behind rung 7. PRD 3.10 makes reversal compliance's
    # exclusive operation, so the call must act as a ComplianceOfficer for the
    # body foreign-key rung to be the first one it fails.
    validate_error(
        api.create_payment_reversal(
            claim["id"], payment_reversal_payload(UNASSIGNED_UUID),
            compliance_officer_headers,
        ),
        ApiErrorId.ERR_RESERVE_ENTRY_NOT_FOUND.value,
    )

    # Five refusals, nothing written.
    after_claim = read_claim(claim["id"])
    assert_claim(after_claim)
    assert after_claim["status"] == "MEDIATION"
    assert after_claim["version"] == claim["version"]
    after_policy = read_policy(policy["id"])
    assert_policy(after_policy)
    assert after_policy.get("pending_transfer_id") is None
    assert after_policy["transfer_count"] == 0
    assert after_policy["version"] == policy["version"]
    after_neutral = read_neutral(neutral["id"])
    assert_neutral(after_neutral)
    assert after_neutral["booked_session_count"] == 1


def test_invalid_pagination_parameters_are_rejected_on_a_list_endpoint(
    api, claims_adjuster_headers
):
    """Both ends of the `limit` range and the `offset` floor are refused with the
    pagination error, while the extreme values that are still inside the accepted
    ranges are served normally.

    PRD Section 2.3: "`limit` controls page size: it defaults to 10, its minimum
    accepted value is 1 and its maximum accepted value is 100. `offset` controls
    how many rows are skipped before the page begins: it defaults to 0 and its
    minimum accepted value is 0, with no upper bound. A `limit` that is not an
    integer or falls outside the range from 1 to 100 inclusive, or an `offset` that
    is not an integer or is below 0, is refused with `ERR_INVALID_PAGINATION` and
    HTTP 422."

    PRD Section 2.3: "List responses populate four pagination fields inside `meta`:
    `limit` and `offset` echo the effective values used for the query,
    `total_count` reports the number of rows that match the filter before
    pagination is applied, and `has_more` is true when rows remain beyond the
    current page."

    Design: Corner/Table 6 Errors/invalid_pagination_parameters_are_rejected_on_a_list_endpoint
    """
    scenario = setup_active_policy()
    policy = scenario["policy"]
    set_clock(INSURER_PERIOD_INSTANT)
    file_claim(
        policy["id"], scenario["homeowner"]["id"],
        coverage_type="STRUCTURAL", defect_category="WATER_INTRUSION",
        claimed_amount_cents=2_187_500,
    )

    # limit 0 is one below the minimum accepted value of 1.
    validate_error(
        api.list_claims(claims_adjuster_headers,
                        {"policy_id": policy["id"], "limit": 0, "offset": 0}),
        ApiErrorId.ERR_INVALID_PAGINATION.value,
    )
    # limit 101 is one above the maximum accepted value of 100.
    validate_error(
        api.list_claims(claims_adjuster_headers,
                        {"policy_id": policy["id"], "limit": 101, "offset": 0}),
        ApiErrorId.ERR_INVALID_PAGINATION.value,
    )
    # offset -1 is below the minimum accepted value of 0.
    validate_error(
        api.list_claims(claims_adjuster_headers,
                        {"policy_id": policy["id"], "limit": 10, "offset": -1}),
        ApiErrorId.ERR_INVALID_PAGINATION.value,
    )

    # The inclusive boundaries themselves are accepted.
    rows, meta = validate_paginated(
        api.list_claims(claims_adjuster_headers,
                        {"policy_id": policy["id"], "limit": 100, "offset": 0})
    )
    assert meta["limit"] == 100
    assert meta["offset"] == 0
    assert meta["total_count"] == 1
    assert meta["has_more"] is False
    assert len(rows) == 1
    rows, meta = validate_paginated(
        api.list_claims(claims_adjuster_headers,
                        {"policy_id": policy["id"], "limit": 1, "offset": 0})
    )
    assert meta["limit"] == 1
    assert meta["total_count"] == 1
    assert meta["has_more"] is False
    assert len(rows) == 1


def test_replaying_a_transition_surfaces_the_builder_policy_premium_and_transfer_state_errors(
    api, underwriting_officer_headers
):
    """Four transitions are each replayed against a row that has already left the
    declared origin state, and each is refused with the state error belonging to
    its own axis - builder, premium axis, coverage axis and transfer.

    PRD Section 2.8, rung 12: "From-state admission (409). The addressed row is in a
    declared origin state for the requested transition, or the matching state
    error: `ERR_INVALID_BUILDER_STATE`, `ERR_INVALID_POLICY_STATE` for the coverage
    axis, `ERR_INVALID_PREMIUM_STATE` for the premium axis,
    `ERR_INVALID_CLAIM_STATE`, `ERR_INVALID_TRANSFER_STATE`,
    `ERR_INVALID_ESCALATION_STATE`, or `ERR_INVALID_NEUTRAL_STATE`. Applies to
    every state-transition endpoint."

    PRD Section 3.1: "A `BuilderPrincipal` submits the file with an
    `attestation_signed` flag, moving `underwriting_status` from `DRAFT` to
    `SUBMITTED`; the file must actually be in `DRAFT`, and a submission against a
    file in any other underwriting state is refused with
    `ERR_INVALID_BUILDER_STATE`."

    PRD Section 3.4: "An `UnderwritingOfficer`, optionally recording an
    `invoice_reference`, drives `premium_status` from `UNBILLED` to `INVOICED`; the
    policy must be in `UNBILLED` on the premium axis (otherwise
    `ERR_INVALID_PREMIUM_STATE`) and still in `PENDING_ENROLLMENT` on the coverage
    axis (otherwise `ERR_INVALID_POLICY_STATE`)." The replayed invoice below is
    aimed at a policy whose coverage axis is still `PENDING_ENROLLMENT`, so only
    the premium-axis condition is broken.

    PRD Section 3.4: "The policy must be in `PENDING_ENROLLMENT` on the coverage
    axis, or `ERR_INVALID_POLICY_STATE`." The replayed activation below is aimed at
    a policy whose premium is already `PAID`, whose `enrollment_hold` is false and
    whose builder is still `APPROVED`, so the coverage axis is the only broken
    condition and `ERR_PREMIUM_NOT_PAID` cannot apply.

    PRD Section 3.5: "An `UnderwritingOfficer` moves the request from `APPROVED` to
    the terminal `RECORDED` with no request body, and the effects reach across
    three rows."

    Design: Corner/Table 6 Errors/replaying_a_transition_surfaces_the_builder_policy_premium_and_transfer_state_errors
    """
    scenario = setup_active_policy()
    builder = scenario["builder"]
    builder_headers = make_builder_principal_headers(builder["id"])
    active_policy = scenario["policy"]
    assert builder["underwriting_status"] == "APPROVED"
    assert active_policy["coverage_status"] == "ACTIVE"
    assert active_policy["premium_status"] == "PAID"

    # A second home stopped one step short: INVOICED premium, coverage still
    # PENDING_ENROLLMENT.
    invoiced_policy = enroll_policy(
        builder["id"], scenario["homeowner"]["id"],
        street_address="212 Cedar Ridge Ct",
    )
    invoiced_policy = invoice_policy(invoiced_policy["id"])
    assert invoiced_policy["premium_status"] == "INVOICED"
    assert invoiced_policy["coverage_status"] == "PENDING_ENROLLMENT"

    # An open transfer request that has not been decided, so it is still REQUESTED
    # rather than APPROVED.
    next_owner = create_homeowner(full_name="Beatrix Coyle",
                                  email="beatrix.coyle@example.com")
    transfer = request_transfer(
        active_policy["id"], scenario["homeowner"]["id"], next_owner["id"],
        expected_policy_version=active_policy["version"],
        transfer_date="2026-09-01",
    )
    assert transfer["status"] == "REQUESTED"
    policy_before = read_policy(active_policy["id"])

    validate_error(
        api.submit_builder(builder["id"], submit_builder_payload(), builder_headers),
        ApiErrorId.ERR_INVALID_BUILDER_STATE.value,
    )
    validate_error(
        api.create_premium_invoice(invoiced_policy["id"], premium_invoice_payload(),
                                   underwriting_officer_headers),
        ApiErrorId.ERR_INVALID_PREMIUM_STATE.value,
    )
    validate_error(
        api.activate_policy(active_policy["id"], underwriting_officer_headers),
        ApiErrorId.ERR_INVALID_POLICY_STATE.value,
    )
    validate_error(
        api.record_transfer(transfer["id"], underwriting_officer_headers),
        ApiErrorId.ERR_INVALID_TRANSFER_STATE.value,
    )

    # Four refusals, no version advanced and no ownership moved.
    policy_after = read_policy(active_policy["id"])
    assert_policy(policy_after)
    assert policy_after["version"] == policy_before["version"]
    assert policy_after["coverage_status"] == "ACTIVE"
    assert policy_after["current_owner_id"] == scenario["homeowner"]["id"]
    assert policy_after["transfer_count"] == 0
    transfer_after = read_transfer(transfer["id"])
    assert transfer_after["status"] == "REQUESTED"
    assert transfer_after["version"] == transfer["version"]
    assert read_builder(builder["id"])["underwriting_status"] == "APPROVED"
    assert read_policy(invoiced_policy["id"])["premium_status"] == "INVOICED"


def test_replaying_a_session_outcome_and_a_deactivation_surfaces_the_escalation_and_neutral_state_errors(
    api, compliance_officer_headers
):
    """A second outcome on a case that already deadlocked and a second retirement
    of an already-retired neutral are each refused with their own state error, and
    neither refusal overwrites the first recording.

    PRD Section 3.9: "Both outcomes require the case to be in `SCHEDULED` - anything
    else is `ERR_INVALID_ESCALATION_STATE` - and both stamp the acting `X-User-ID`
    as the case's `outcome_recorded_by_user_id` and advance both the case's
    `version` and the claim's `version` by 1."

    PRD Section 3.9: "An outcome of `IMPASSE` moves the case `SCHEDULED -> IMPASSE`
    and deliberately leaves the claim's `status` alone - a deadlocked mediation
    keeps the claim in `MEDIATION` so the arbitration rung remains reachable."

    PRD Section 3.9: "Its `settlement_amount_cents` and `award_amount_cents` both
    start null and are never accepted at case creation."

    PRD Section 3.9: "Retiring a neutral is also compliance's move: with a `reason`,
    the neutral moves `ACTIVE -> INACTIVE`, a terminal state, and its `version`
    advances by 1; a deactivation aimed at a neutral that is already `INACTIVE` is
    refused with `ERR_INVALID_NEUTRAL_STATE`."

    Design: Corner/Table 6 Errors/replaying_a_session_outcome_and_a_deactivation_surfaces_the_escalation_and_neutral_state_errors
    """
    scenario = setup_mediation_case(
        claimed_amount_cents=2_187_500,
        substantiation_ratio=0.80,
        coverage_type="STRUCTURAL",
        defect_category="WATER_INTRUSION",
    )
    case = scenario["mediation_case"]
    claim = scenario["claim"]
    assert case["status"] == "SCHEDULED"
    assert claim["status"] == "MEDIATION"

    # The clock must be at or after window_start before an outcome may be recorded.
    set_clock("2028-09-10T15:00:00Z")
    deadlocked = validate_success(
        api.record_session_outcome(
            case["id"], session_outcome_payload("IMPASSE"),
            make_claims_adjuster_headers(ADJUSTER_USER_ID),
        )
    )
    assert_escalation_case(deadlocked)
    assert deadlocked["status"] == "IMPASSE"
    assert deadlocked["outcome_recorded_by_user_id"] == ADJUSTER_USER_ID

    retired = create_neutral(full_name="Ilya Brandt", credential="BOTH")
    retired = validate_success(
        api.deactivate_neutral(retired["id"], deactivate_neutral_payload(),
                               compliance_officer_headers)
    )
    assert_neutral(retired)
    assert retired["status"] == "INACTIVE"

    # A different adjuster replaying a different outcome still finds the case out
    # of SCHEDULED.
    validate_error(
        api.record_session_outcome(
            case["id"],
            session_outcome_payload("SETTLED", settlement_amount_cents=250_000),
            make_claims_adjuster_headers(SECOND_ADJUSTER_USER_ID),
        ),
        ApiErrorId.ERR_INVALID_ESCALATION_STATE.value,
    )
    validate_error(
        api.deactivate_neutral(retired["id"], deactivate_neutral_payload(),
                               compliance_officer_headers),
        ApiErrorId.ERR_INVALID_NEUTRAL_STATE.value,
    )

    after_case = validate_success(
        api.get_escalation_case(case["id"], compliance_officer_headers)
    )
    assert_escalation_case(after_case)
    assert after_case["status"] == "IMPASSE"
    assert after_case["version"] == deadlocked["version"]
    # The first recorder is not overwritten by the replay.
    assert after_case["outcome_recorded_by_user_id"] == ADJUSTER_USER_ID
    assert after_case.get("settlement_amount_cents") is None

    after_claim = read_claim(claim["id"])
    assert_claim(after_claim)
    assert after_claim["status"] == "MEDIATION"
    assert after_claim["reserve_cents"] == 0
    after_neutral = read_neutral(retired["id"])
    assert_neutral(after_neutral)
    assert after_neutral["status"] == "INACTIVE"
    assert after_neutral["version"] == retired["version"]


def test_claim_intake_with_no_term_in_force_returns_no_coverage_in_force(
    api, claims_adjuster_headers
):
    """Once the sweep has elapsed the two short terms, the two coverage types they
    carried have no candidate term left and intake is refused - while the still-open
    structural term keeps accepting claims on the very same, still-`ACTIVE` policy.

    PRD Section 3.6: "The candidate set is the terms of that policy whose `status` is
    `OPEN` or `LIMIT_EXHAUSTED`; terms already `ELAPSED` are excluded outright. From
    those, the terms whose `coverage_type` equals the claimed `coverage_type` and
    whose closed interval contains the `reported_date` - on or after `start_date` and
    on or before `end_date` - are ranked with `BASE` terms ahead of `ENDORSEMENT`
    terms, then by `start_date` ascending, then by `created_at` ascending, and the
    first is chosen. When that candidate set is legitimately empty - no term of the
    claimed type covers the reported date - the intake is refused with
    `ERR_NO_COVERAGE_IN_FORCE`."

    PRD Section 3.6: "Claims can only be filed against a policy whose
    `coverage_status` is `ACTIVE`, and an attempt against any other coverage state is
    refused with `ERR_POLICY_NOT_ACTIVE`." The policy here is still `ACTIVE`, so the
    refusal is about the missing term and not about the policy.

    PRD Section 3.6: "When the `reported_date` is on or before the policy's
    `builder_obligation_end_date`, the `obligor` is `BUILDER`; when it falls after
    that date, the `obligor` is `INSURER`."

    Design: Corner/Table 6 Errors/claim_intake_with_no_term_in_force_returns_no_coverage_in_force
    """
    scenario = setup_active_policy()
    policy = scenario["policy"]
    owner_headers = make_homeowner_headers(scenario["homeowner"]["id"])

    # 2028-09-01 is past the workmanship end (2027-08-14) and the systems end
    # (2028-08-14) but well inside the structural term (through 2036-08-14).
    set_clock(INSURER_PERIOD_INSTANT)
    terms = read_coverage_terms(policy["id"])
    assert find_term(terms, "WORKMANSHIP")["status"] == "ELAPSED"
    assert find_term(terms, "SYSTEMS")["status"] == "ELAPSED"
    structural_term = find_term(terms, "STRUCTURAL")
    assert structural_term["status"] == "OPEN"
    assert read_policy(policy["id"])["coverage_status"] == "ACTIVE"

    validate_error(
        api.create_claim(
            create_claim_payload(policy["id"], coverage_type="WORKMANSHIP",
                                 defect_category="WORKMANSHIP_DEFECT",
                                 claimed_amount_cents=400_000),
            owner_headers,
        ),
        ApiErrorId.ERR_NO_COVERAGE_IN_FORCE.value,
    )
    validate_error(
        api.create_claim(
            create_claim_payload(policy["id"], coverage_type="SYSTEMS",
                                 defect_category="SYSTEM_FAILURE",
                                 claimed_amount_cents=400_000),
            owner_headers,
        ),
        ApiErrorId.ERR_NO_COVERAGE_IN_FORCE.value,
    )

    accepted = validate_success(
        api.create_claim(
            create_claim_payload(policy["id"], coverage_type="STRUCTURAL",
                                 defect_category="WATER_INTRUSION",
                                 claimed_amount_cents=400_000),
            owner_headers,
        ),
        201,
    )
    assert_claim(accepted)
    assert accepted["status"] == "SUBMITTED"
    assert accepted["coverage_term_id"] == structural_term["id"]
    # reported_date 2028-09-01 falls after builder_obligation_end_date 2028-08-14.
    assert accepted["reported_date"] == "2028-09-01"
    assert accepted["obligor"] == "INSURER"

    after_policy = read_policy(policy["id"])
    assert_policy(after_policy)
    assert after_policy["coverage_status"] == "ACTIVE"

    rows, meta = validate_paginated(
        api.list_claims(claims_adjuster_headers, {"policy_id": policy["id"]})
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == accepted["id"]


def test_a_structural_defect_category_cannot_be_adjudicated_without_an_assessment(
    api, claims_adjuster_headers
):
    """A `LOAD_BEARING_FAILURE` claim cannot be ruled on until an engineer has
    filed a report - and the report that unblocks adjudication does not have to
    reach a structural verdict, so the deductible schedule and the settlement
    figures are unchanged by it.

    PRD Section 3.7: "Both branches also share one safety guard: when the claim's
    `defect_category` is `STRUCTURAL_CRACKING` or `LOAD_BEARING_FAILURE`, at least
    one engineering assessment must already be on file for that claim, and
    adjudicating such a claim with no assessment is refused with
    `ERR_STRUCTURAL_ASSESSMENT_REQUIRED`. The carrier will not rule on a structural
    allegation it has not had an engineer look at."

    PRD Section 3.7, waterfall step 2: "The deductible schedule is selected by the
    claim's `designated_structural` flag: 250,000 cents when the flag is true, and
    100,000 cents when it is false. Note that the switch is the structural
    designation from the engineering reports, not the claimant's own
    `defect_category` and not the term's recorded `deductible_cents`."

    PRD Section 3.6: "The report's own `designated_structural` verdict requires all
    three of the following to hold at once: `load_bearing_affected` is true; at least
    one entry in `affected_elements` is a load-bearing element, meaning one of
    `FOOTING`, `FOUNDATION_WALL`, `BEAM`, `LOAD_BEARING_WALL`, `ROOF_TRUSS` or
    `SLAB`; and the `deflection_ratio` is 0.0033 or greater, the threshold value
    itself qualifying. `NON_BEARING_PARTITION` and `FINISH` are explicitly not
    load-bearing elements, so a report naming only those two fails the second
    conjunct."

    PRD Section 3.6: "The server stamps `assessed_by_user_id` from the acting
    `X-User-ID` and `assessment_date` from the logical clock's current date;
    `assessment_date` is never accepted as request input."

    PRD Section 3.7: "`APPROVE` advances the claim `INSURER_ADJUDICATION ->
    APPROVED` ... Nothing financial moves on approval itself; approval merely
    authorises disbursement."

    Design: Corner/Table 6 Errors/a_structural_defect_category_cannot_be_adjudicated_without_an_assessment_on_file
    """
    scenario = setup_routed_claim(
        claimed_amount_cents=2_187_500,
        substantiation_ratio=0.80,
        coverage_type="STRUCTURAL",
        defect_category="LOAD_BEARING_FAILURE",
        claim_instant=INSURER_PERIOD_INSTANT,
    )
    claim = scenario["claim"]
    assert_claim(claim)
    assert claim["status"] == "INSURER_ADJUDICATION"
    assert claim["obligor"] == "INSURER"
    # No assessment has been filed, so the claim-level flag is still false and the
    # non-structural 100,000 schedule was selected despite the defect category.
    assert claim["designated_structural"] is False
    assert claim["gross_adjusted_cents"] == 1_750_000
    assert claim["deductible_applied_cents"] == 100_000
    assert claim["betterment_cents"] == 132_000
    assert claim["net_payable_cents"] == 1_518_000

    validate_error(
        api.create_adjudication(claim["id"], adjudication_payload("APPROVE"),
                                claims_adjuster_headers),
        ApiErrorId.ERR_STRUCTURAL_ASSESSMENT_REQUIRED.value,
    )

    # FINISH is not a load-bearing element, so this report fails the second
    # conjunct and returns a false verdict - but it is still an assessment on file.
    assessment = validate_success(
        api.create_structural_assessment(
            claim["id"],
            structural_assessment_payload(affected_elements=["FINISH"],
                                          deflection_ratio=0.0100,
                                          load_bearing_affected=True),
            claims_adjuster_headers,
        ),
        201,
    )
    assert_structural_assessment(assessment)
    assert assessment["designated_structural"] is False
    assert assessment["assessment_date"] == "2028-09-01"
    assert assessment["assessed_by_user_id"] == ADJUSTER_USER_ID

    approved = validate_success(
        api.create_adjudication(claim["id"], adjudication_payload("APPROVE"),
                                claims_adjuster_headers)
    )
    assert_claim(approved)
    assert approved["status"] == "APPROVED"
    assert approved["adjudicated_by_user_id"] == ADJUSTER_USER_ID
    # The gate opened without changing the designation or re-running the waterfall.
    assert approved["designated_structural"] is False
    assert approved["deductible_applied_cents"] == 100_000
    assert approved["betterment_cents"] == 132_000
    assert approved["net_payable_cents"] == 1_518_000
    assert approved["reserve_cents"] == 1_518_000
    assert approved["paid_cents"] == 0
