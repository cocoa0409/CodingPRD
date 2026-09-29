"""Coverage-limit, builder-default, session-window, panel-credential and
reserve-ledger refusals from the error catalogue.

Every test builds its own world from scratch through PRD-declared endpoints,
because each test runs against a freshly restarted server with an empty
database. Monetary amounts are JSON integers in cents throughout.
"""

from test_helpers import (
    ADJUSTER_USER_ID,
    CANONICAL_CLOSING_INSTANT,
    ApiErrorId,
    add_endorsement_term,
    adjudicate_claim,
    adjudication_payload,
    assert_claim_money_conserved,
    assert_coverage_capacity_conserved,
    assert_escalation_case,
    assert_reserve_entry,
    assert_same_instant,
    authorize_reserve,
    create_escalation_payload,
    create_neutral,
    declare_builder_default,
    file_claim,
    get_success_data,
    investigate_claim,
    latest_payment_entry_id,
    make_homeowner_headers,
    obligation_routing_payload,
    pay_claim,
    payment_reversal_payload,
    read_builder,
    read_claim,
    read_coverage_term,
    read_escalation_case,
    read_neutral,
    read_policy,
    read_reserve_entries,
    reserve_entry_payload,
    route_claim,
    session_outcome_payload,
    set_clock,
    setup_active_policy,
    setup_approved_claim,
    setup_denied_claim,
    setup_mediation_case,
    setup_routed_claim,
    validate_error,
    validate_paginated,
    validate_success,
)

MEDIATION_WINDOW_START = "2028-09-20T14:00:00Z"
MEDIATION_WINDOW_END = "2028-09-20T18:00:00Z"


# ==========================================================================
# An exhausted coverage term still admits intake, but blocks approval
# ==========================================================================
def _setup_exhausted_endorsement_term():
    """One ACTIVE home whose WORKMANSHIP endorsement term of 500,000 cents has
    been driven to exactly zero remaining capacity by a single disbursement."""
    scenario = setup_active_policy()
    set_clock("2028-09-01T00:00:00Z")
    endorsement = add_endorsement_term(
        scenario["policy"]["id"],
        coverage_type="WORKMANSHIP",
        start_date="2028-09-01",
        end_date="2029-08-31",
        limit_cents=500_000,
        deductible_cents=100_000,
    )
    first = file_claim(
        scenario["policy"]["id"], scenario["homeowner"]["id"],
        coverage_type="WORKMANSHIP",
        defect_category="WORKMANSHIP_DEFECT",
        claimed_amount_cents=800_000,
        damage_description="Cabinetry and trim installed out of tolerance",
    )
    investigate_claim(first["id"], 1.00)
    route_claim(first["id"])
    adjudicate_claim(first["id"], "APPROVE", adjuster_user_id=ADJUSTER_USER_ID)
    pay_claim(first["id"], 500_000, memo="endorsement limit disbursed in full")
    scenario["endorsement_term"] = read_coverage_term(endorsement["id"])
    scenario["first_claim"] = read_claim(first["id"])
    return scenario


def _file_second_workmanship_claim(scenario):
    """A second WORKMANSHIP loss on the same home, carried to the point of
    adjudication."""
    second = file_claim(
        scenario["policy"]["id"], scenario["homeowner"]["id"],
        coverage_type="WORKMANSHIP",
        defect_category="WORKMANSHIP_DEFECT",
        claimed_amount_cents=600_000,
        damage_description="Second workmanship loss on the same finished home",
    )
    investigate_claim(second["id"], 1.00)
    route_claim(second["id"])
    return read_claim(second["id"])


def test_approving_a_claim_whose_coverage_term_is_exhausted_is_refused(
    api, claims_adjuster_headers
):
    """PRD Section 3.8: "When that charge drives the term's `remaining_limit_cents` to
    exactly 0, the term transitions `OPEN → LIMIT_EXHAUSTED` and its `version`
    advances by 1".

    PRD Section 3.6: "The candidate set is the terms of that policy whose `status` is
    `OPEN` or `LIMIT_EXHAUSTED`; terms already `ELAPSED` are excluded outright."

    PRD Section 3.7: "`net_payable_cents` is the smaller of two figures: the
    provisional net less `betterment_cents`, and the `remaining_limit_cents` of the
    coverage term named by the claim's `coverage_term_id`."

    PRD Section 3.7: "`APPROVE` advances the claim `INSURER_ADJUDICATION → APPROVED`
    and carries one guard the denial branch does not: the coverage term resolved for
    the claim must have a `status` of exactly `OPEN`. A term that has been exhausted
    or has lapsed blocks approval with `ERR_COVERAGE_LIMIT_EXHAUSTED`."

    Design: Corner/Table 6 Errors/an_exhausted_coverage_term_blocks_the_next_approval_with_coverage_limit_exhausted
    """
    scenario = _setup_exhausted_endorsement_term()
    term = scenario["endorsement_term"]
    assert scenario["first_claim"]["status"] == "CLOSED_PAID"
    assert term["status"] == "LIMIT_EXHAUSTED"
    assert term["remaining_limit_cents"] == 0
    assert_coverage_capacity_conserved(term)

    second = _file_second_workmanship_claim(scenario)
    assert second["coverage_term_id"] == term["id"]
    assert second["gross_adjusted_cents"] == 600_000
    assert second["net_payable_cents"] == 0
    assert second["reserve_cents"] == 0
    assert second["status"] == "INSURER_ADJUDICATION"

    response = api.create_adjudication(
        second["id"], adjudication_payload("APPROVE"), claims_adjuster_headers
    )
    validate_error(response, ApiErrorId.ERR_COVERAGE_LIMIT_EXHAUSTED.value)
    assert read_claim(second["id"])["status"] == "INSURER_ADJUDICATION"


def test_denying_a_claim_whose_coverage_term_is_exhausted_is_allowed(
    api, claims_adjuster_headers
):
    """PRD Section 3.7: "`APPROVE` advances the claim `INSURER_ADJUDICATION → APPROVED`
    and carries one guard the denial branch does not: the coverage term resolved for
    the claim must have a `status` of exactly `OPEN`."

    PRD Section 3.7: "`DENY` advances the claim `INSURER_ADJUDICATION → DENIED` and
    does considerably more."

    Design: Corner/Table 6 Errors/an_exhausted_coverage_term_blocks_the_next_approval_with_coverage_limit_exhausted
    """
    scenario = _setup_exhausted_endorsement_term()
    second = _file_second_workmanship_claim(scenario)
    assert second["coverage_term_id"] == scenario["endorsement_term"]["id"]

    response = api.create_adjudication(
        second["id"], adjudication_payload("DENY"), claims_adjuster_headers
    )
    validate_success(response, 200)
    assert read_claim(second["id"])["status"] == "DENIED"


# ==========================================================================
# A defaulted builder can no longer take a claim into the obligation arm
# ==========================================================================
def test_routing_a_claim_into_the_builder_arm_of_a_defaulted_builder_is_refused(
    api, claims_adjuster_headers
):
    """PRD Section 3.7: "One extra guard applies only here: the builder behind the
    claim's policy must not already have an `underwriting_status` of `DEFAULTED`, and
    routing a claim into the builder arm for a defaulted builder is refused with
    `ERR_BUILDER_DEFAULTED`."

    PRD Section 3.2: "A `ComplianceOfficer` supplies a `reason`, and a builder in
    either `APPROVED` or `SUSPENDED` moves to `DEFAULTED` — a terminal state from which
    there is no return. `default_declared_at` is stamped with the logical clock's
    current instant."

    PRD Section 3.2: "The **first link** re-parties every stranded claim: each claim on
    any policy of this builder whose `status` is `BUILDER_OBLIGATION_NOTICE`
    transitions to `INSURER_ADJUDICATION`, and its `obligor` is rewritten from
    `BUILDER` to `INSURER`."

    PRD Section 3.2: "Separately from the three-link chain, every policy of this
    builder still sitting in `PENDING_ENROLLMENT` transitions to `VOIDED`".

    Design: Corner/Table 6 Errors/a_defaulted_builder_cannot_take_a_claim_into_the_obligation_arm
    """
    scenario = setup_routed_claim(
        claimed_amount_cents=2_187_500,
        substantiation_ratio=0.80,
        coverage_type="STRUCTURAL",
        defect_category="WATER_INTRUSION",
        claim_instant=None,
        route=False,
        claim_overrides={
            "damage_description": "Foundation slab displacement inside the "
                                  "builder obligation period",
        },
    )
    claim = scenario["claim"]
    assert claim["status"] == "UNDER_INVESTIGATION"
    assert claim["obligor"] == "BUILDER"
    assert claim["version"] == 2

    declare_builder_default(
        scenario["builder"]["id"], reason="Builder abandoned the subdivision"
    )
    builder = read_builder(scenario["builder"]["id"])
    assert builder["underwriting_status"] == "DEFAULTED"
    assert_same_instant(builder["default_declared_at"], CANONICAL_CLOSING_INSTANT)

    response = api.route_claim_obligation(
        claim["id"],
        obligation_routing_payload(routing_note="Builder-arm routing attempt"),
        claims_adjuster_headers,
    )
    validate_error(response, ApiErrorId.ERR_BUILDER_DEFAULTED.value)

    after = read_claim(claim["id"])
    assert after["status"] == "UNDER_INVESTIGATION"
    assert after["obligor"] == "BUILDER"
    assert after["version"] == 2
    assert read_policy(scenario["policy"]["id"])["coverage_status"] == "ACTIVE"


# ==========================================================================
# A session outcome may not be recorded before the window opens
# ==========================================================================
def _setup_scheduled_mediation_on_a_mediator():
    """A denied claim with one MEDIATION case booked on a MEDIATOR-credentialled
    neutral for a window that opens on 2028-09-20."""
    return setup_mediation_case(
        claimed_amount_cents=2_187_500,
        substantiation_ratio=0.80,
        coverage_type="STRUCTURAL",
        defect_category="WATER_INTRUSION",
        neutral_overrides={"full_name": "Marcia Vance", "credential": "MEDIATOR"},
        window_start=MEDIATION_WINDOW_START,
        window_end=MEDIATION_WINDOW_END,
    )


def test_recording_a_session_outcome_before_the_window_start_is_refused(
    api, claims_adjuster_headers
):
    """PRD Section 3.9: "Recording how a session ended is the adjuster's job, and it may
    not be done before the session was scheduled to begin: the logical clock's current
    instant must be at or after the case's `window_start`, or the request is refused
    with `ERR_SESSION_WINDOW_NOT_STARTED`."

    PRD Section 3.7: "`escalation_deadline_date` is set to that denial date plus 60
    days — the mediation window, and the deadline is **inclusive**".

    Design: Corner/Table 6 Errors/a_session_outcome_before_the_window_opens_is_refused_then_accepted_at_the_window_start
    """
    scenario = _setup_scheduled_mediation_on_a_mediator()
    case = scenario["mediation_case"]
    assert scenario["claim"]["status"] == "MEDIATION"
    assert scenario["claim"]["escalation_deadline_date"] == "2028-10-31"

    set_clock("2028-09-10T15:00:00Z")
    response = api.record_session_outcome(
        case["id"], session_outcome_payload("IMPASSE"), claims_adjuster_headers
    )
    validate_error(response, ApiErrorId.ERR_SESSION_WINDOW_NOT_STARTED.value)

    still_scheduled = read_escalation_case(case["id"])
    assert still_scheduled["status"] == "SCHEDULED"
    assert read_claim(scenario["claim"]["id"])["escalation_deadline_date"] == "2028-10-31"


def test_recording_a_session_outcome_at_exactly_the_window_start_is_accepted(
    api, claims_adjuster_headers
):
    """PRD Section 3.9: "the logical clock's current instant must be at or after the
    case's `window_start`, or the request is refused with
    `ERR_SESSION_WINDOW_NOT_STARTED`."

    PRD Section 3.9: "both stamp the acting `X-User-ID` as the case's
    `outcome_recorded_by_user_id` and advance both the case's `version` and the claim's
    `version` by 1."

    PRD Section 3.9: "An outcome of `IMPASSE` moves the case `SCHEDULED → IMPASSE` and
    deliberately leaves the claim's `status` alone — a deadlocked mediation keeps the
    claim in `MEDIATION` so the arbitration rung remains reachable. What it does change
    is the clock on that rung: the claim's `escalation_deadline_date` is rewritten to
    the logical clock's current date plus 30 days, the arbitration window."

    Design: Corner/Table 6 Errors/a_session_outcome_before_the_window_opens_is_refused_then_accepted_at_the_window_start
    """
    scenario = _setup_scheduled_mediation_on_a_mediator()
    case = scenario["mediation_case"]

    set_clock(MEDIATION_WINDOW_START)
    response = api.record_session_outcome(
        case["id"], session_outcome_payload("IMPASSE"), claims_adjuster_headers
    )
    validate_success(response, 200)

    recorded = read_escalation_case(case["id"])
    assert recorded["status"] == "IMPASSE"
    assert recorded["outcome_recorded_by_user_id"] == ADJUSTER_USER_ID
    assert_escalation_case(recorded)

    claim = read_claim(scenario["claim"]["id"])
    assert claim["status"] == "MEDIATION"
    assert claim["escalation_deadline_date"] == "2028-10-20"


# ==========================================================================
# A neutral's credential must admit the stage being booked
# ==========================================================================
def _setup_denied_claim_with_two_neutrals():
    """A denied claim plus two ACTIVE panel members: one ARBITRATOR-only and one
    dual-credentialled."""
    arbitrator = create_neutral(full_name="Priya Raman", credential="ARBITRATOR",
                               state_code="TX")
    dual = create_neutral(full_name="Dana Okafor", credential="BOTH",
                          state_code="TX")
    scenario = setup_denied_claim(
        claimed_amount_cents=2_187_500,
        substantiation_ratio=0.80,
        coverage_type="STRUCTURAL",
        defect_category="WATER_INTRUSION",
    )
    scenario["arbitrator_neutral"] = arbitrator
    scenario["dual_neutral"] = dual
    return scenario


def test_booking_a_mediation_on_an_arbitrator_only_neutral_is_refused(api):
    """PRD Section 3.9: "The neutral's `credential` must admit the requested stage —
    `MEDIATOR` or `BOTH` for a `MEDIATION` case, `ARBITRATOR` or `BOTH` for an
    `ARBITRATION` case — or `ERR_NEUTRAL_CREDENTIAL_MISMATCH`."

    PRD Section 3.4: "A new neutral is born with `status` `ACTIVE` and
    `booked_session_count` of 0."

    Design: Corner/Table 6 Errors/a_neutral_credential_mismatch_blocks_the_booking_for_that_stage
    """
    scenario = _setup_denied_claim_with_two_neutrals()
    owner_headers = make_homeowner_headers(scenario["homeowner"]["id"])
    arbitrator = scenario["arbitrator_neutral"]

    response = api.create_escalation(
        scenario["claim"]["id"],
        create_escalation_payload(arbitrator["id"], "MEDIATION",
                                  MEDIATION_WINDOW_START, MEDIATION_WINDOW_END),
        owner_headers,
    )
    validate_error(response, ApiErrorId.ERR_NEUTRAL_CREDENTIAL_MISMATCH.value)

    assert read_neutral(arbitrator["id"])["booked_session_count"] == 0
    assert read_claim(scenario["claim"]["id"])["status"] == "DENIED"


def test_booking_a_mediation_on_a_dual_credentialled_neutral_is_accepted(
    api, claims_adjuster_headers
):
    """PRD Section 3.9: "The neutral's `credential` must admit the requested stage —
    `MEDIATOR` or `BOTH` for a `MEDIATION` case, `ARBITRATOR` or `BOTH` for an
    `ARBITRATION` case — or `ERR_NEUTRAL_CREDENTIAL_MISMATCH`."

    PRD Section 3.9: "A successful booking creates an escalation case against the claim
    named in its `claim_id`, in `status` `SCHEDULED`, with `binding` false for a
    `MEDIATION` case and true for an `ARBITRATION` case".

    PRD Section 3.9: "The booked neutral's `booked_session_count` is incremented by 1
    and its `version` advances by 1; that counter is the number of escalation cases
    naming this neutral whose `status` is `SCHEDULED`, `SETTLED`, `IMPASSE` or
    `AWARD_ISSUED`."

    PRD Section 3.9: "Clients inspect a conflict by listing escalation cases filtered on
    the neutral in question."

    Design: Corner/Table 6 Errors/a_neutral_credential_mismatch_blocks_the_booking_for_that_stage
    """
    scenario = _setup_denied_claim_with_two_neutrals()
    owner_headers = make_homeowner_headers(scenario["homeowner"]["id"])
    dual = scenario["dual_neutral"]

    response = api.create_escalation(
        scenario["claim"]["id"],
        create_escalation_payload(dual["id"], "MEDIATION",
                                  MEDIATION_WINDOW_START, MEDIATION_WINDOW_END),
        owner_headers,
    )
    case = validate_success(response, 201)
    assert case["status"] == "SCHEDULED"
    assert case["binding"] is False
    assert_escalation_case(case)

    assert read_neutral(dual["id"])["booked_session_count"] == 1
    assert read_claim(scenario["claim"]["id"])["status"] == "MEDIATION"

    cases, meta = validate_paginated(
        api.list_escalation_cases(claims_adjuster_headers,
                                  {"neutral_id": dual["id"]})
    )
    assert meta["total_count"] == 1
    assert cases[0]["id"] == case["id"]


# ==========================================================================
# Only an unreversed PAYMENT row of the same claim can be reversed
# ==========================================================================
def _setup_two_partly_paid_claims():
    """Two APPROVED insurer-arm claims on the same home, each carrying one
    PAYMENT row; the primary claim also carries its INITIAL authorisation."""
    scenario = setup_approved_claim(
        claimed_amount_cents=2_187_500,
        substantiation_ratio=0.80,
        coverage_type="STRUCTURAL",
        defect_category="WATER_INTRUSION",
    )
    primary = scenario["claim"]
    scenario["initial_entry"] = authorize_reserve(
        primary["id"], 1_518_000, entry_type="INITIAL",
        memo="Case reserve authorised at the net payable",
    )
    pay_claim(primary["id"], 500_000, memo="First indemnity instalment")

    sibling = file_claim(
        scenario["policy"]["id"], scenario["homeowner"]["id"],
        coverage_type="STRUCTURAL",
        defect_category="WATER_INTRUSION",
        claimed_amount_cents=500_000,
        damage_description="Separate slab defect on the same home",
    )
    investigate_claim(sibling["id"], 1.00)
    route_claim(sibling["id"])
    adjudicate_claim(sibling["id"], "APPROVE", adjuster_user_id=ADJUSTER_USER_ID)
    pay_claim(sibling["id"], 100_000, memo="Indemnity on the sibling claim")

    scenario["primary_payment_entry_id"] = latest_payment_entry_id(primary["id"])
    scenario["sibling_payment_entry_id"] = latest_payment_entry_id(sibling["id"])
    scenario["claim"] = read_claim(primary["id"])
    scenario["sibling_claim"] = read_claim(sibling["id"])
    return scenario


def test_reversing_a_journal_row_that_is_not_a_payment_is_refused(
    api, compliance_officer_headers
):
    """PRD Section 3.8: "The named row must belong to the claim in question, must have
    an `entry_type` of `PAYMENT`, and must not already have been reversed; a row failing
    any of those tests is refused with `ERR_ENTRY_NOT_REVERSIBLE`."

    PRD Section 2.6: "Reserve entries are filterable by `claim_id`, `reversed_entry_id`
    and `entry_type`, and this is the only channel through which a client can discover
    the identifier of a system-created payment entry that a reversal must name."

    Design: Corner/Table 6 Errors/only_an_unreversed_payment_entry_of_the_same_claim_is_reversible
    """
    scenario = _setup_two_partly_paid_claims()
    initial_entry = scenario["initial_entry"]
    assert initial_entry["entry_type"] == "INITIAL"
    assert_reserve_entry(initial_entry)

    response = api.create_payment_reversal(
        scenario["claim"]["id"],
        payment_reversal_payload(initial_entry["id"],
                                 memo="Attempt to undo an authorisation"),
        compliance_officer_headers,
    )
    validate_error(response, ApiErrorId.ERR_ENTRY_NOT_REVERSIBLE.value)

    claim = read_claim(scenario["claim"]["id"])
    assert claim["paid_cents"] == 500_000
    assert claim["reserve_cents"] == 1_018_000
    assert_claim_money_conserved(claim)
    assert len(read_reserve_entries(claim["id"])) == 2


def test_reversing_a_payment_that_belongs_to_another_claim_is_refused(
    api, compliance_officer_headers
):
    """PRD Section 3.8: "The named row must belong to the claim in question, must have
    an `entry_type` of `PAYMENT`, and must not already have been reversed; a row failing
    any of those tests is refused with `ERR_ENTRY_NOT_REVERSIBLE`."

    Design: Corner/Table 6 Errors/only_an_unreversed_payment_entry_of_the_same_claim_is_reversible
    """
    scenario = _setup_two_partly_paid_claims()

    response = api.create_payment_reversal(
        scenario["claim"]["id"],
        payment_reversal_payload(scenario["sibling_payment_entry_id"],
                                 memo="Payment row of a different claim"),
        compliance_officer_headers,
    )
    validate_error(response, ApiErrorId.ERR_ENTRY_NOT_REVERSIBLE.value)

    assert read_claim(scenario["claim"]["id"])["paid_cents"] == 500_000
    assert read_claim(scenario["sibling_claim"]["id"])["paid_cents"] == 100_000


def test_a_payment_reversal_is_an_exact_no_op_and_cannot_be_applied_twice(
    api, compliance_officer_headers
):
    """PRD Section 3.8: "On success a journal row of `entry_type` `PAYMENT_REVERSAL` is
    appended with its `reversed_entry_id` naming the undone payment. The reversed amount
    is subtracted from the claim's `paid_cents` and added back to its `reserve_cents`,
    leaving `incurred_authorized_cents` untouched".

    PRD Section 3.8: "A payment followed by its reversal is therefore an exact no-op on
    all four claim money fields and on both term capacity fields."

    PRD Section 3.8: "The named row must belong to the claim in question, must have an
    `entry_type` of `PAYMENT`, and must not already have been reversed; a row failing any
    of those tests is refused with `ERR_ENTRY_NOT_REVERSIBLE`."

    PRD Section 2.6: "Reserve entries are filterable by `claim_id`, `reversed_entry_id`
    and `entry_type`".

    Design: Corner/Table 6 Errors/only_an_unreversed_payment_entry_of_the_same_claim_is_reversible
    """
    scenario = _setup_two_partly_paid_claims()
    claim_id = scenario["claim"]["id"]
    payment_entry_id = scenario["primary_payment_entry_id"]

    accepted = api.create_payment_reversal(
        claim_id,
        payment_reversal_payload(payment_entry_id, memo="Disbursed in error"),
        compliance_officer_headers,
    )
    get_success_data(accepted)

    claim = read_claim(claim_id)
    assert claim["paid_cents"] == 0
    assert claim["reserve_cents"] == 1_518_000
    assert claim["incurred_authorized_cents"] == 1_518_000
    assert_claim_money_conserved(claim)

    repeated = api.create_payment_reversal(
        claim_id,
        payment_reversal_payload(payment_entry_id, memo="Second attempt"),
        compliance_officer_headers,
    )
    validate_error(repeated, ApiErrorId.ERR_ENTRY_NOT_REVERSIBLE.value)

    entries, meta = validate_paginated(
        api.list_reserve_entries(compliance_officer_headers,
                                 {"claim_id": claim_id, "limit": 100})
    )
    assert meta["total_count"] == 3
    assert [entry["entry_type"] for entry in entries] == [
        "INITIAL", "PAYMENT", "PAYMENT_REVERSAL",
    ]

    reversals, reversal_meta = validate_paginated(
        api.list_reserve_entries(compliance_officer_headers,
                                 {"reversed_entry_id": payment_entry_id})
    )
    assert reversal_meta["total_count"] == 1
    assert reversals[0]["entry_type"] == "PAYMENT_REVERSAL"
    assert reversals[0]["reversed_entry_id"] == payment_entry_id

    assert read_claim(scenario["sibling_claim"]["id"])["paid_cents"] == 100_000


# ==========================================================================
# The two fiscal guards on a reserve authorisation
# ==========================================================================
def _setup_claim_with_reserve_and_one_payment():
    """An APPROVED insurer-arm claim carrying an INITIAL authorisation of
    1,518,000 cents of which 500,000 cents has been disbursed."""
    scenario = setup_approved_claim(
        claimed_amount_cents=2_187_500,
        substantiation_ratio=0.80,
        coverage_type="STRUCTURAL",
        defect_category="WATER_INTRUSION",
    )
    claim_id = scenario["claim"]["id"]
    scenario["initial_entry"] = authorize_reserve(
        claim_id, 1_518_000, entry_type="INITIAL",
        memo="Case reserve authorised at the net payable",
    )
    pay_claim(claim_id, 500_000, memo="First indemnity instalment")
    scenario["claim"] = read_claim(claim_id)
    return scenario


def test_a_second_initial_reserve_authorisation_is_refused(
    api, claims_adjuster_headers
):
    """PRD Section 3.8: "An `INITIAL` entry is refused when the claim **already** carries
    an entry of type `INITIAL` or `ADJUSTMENT`, with `ERR_INITIAL_RESERVE_ALREADY_SET`: a
    reserve that already exists is re-authorised with `ADJUSTMENT`, never
    re-initialised."

    PRD Section 3.8: "It moves money on the claim: `amount_cents` is added to
    `paid_cents` and subtracted from `reserve_cents`, leaving
    `incurred_authorized_cents` untouched."

    Design: Corner/Table 6 Errors/reserve_entry_guards_refuse_a_second_initial_and_an_authorisation_below_the_paid_amount
    """
    scenario = _setup_claim_with_reserve_and_one_payment()
    claim = scenario["claim"]
    assert scenario["initial_entry"]["balance_after_reserve_cents"] == 1_518_000
    assert claim["paid_cents"] == 500_000
    assert claim["reserve_cents"] == 1_018_000

    response = api.create_reserve_entry(
        claim["id"],
        reserve_entry_payload(1_400_000, claim["version"], "INITIAL",
                              memo="Second initial authorisation"),
        claims_adjuster_headers,
    )
    validate_error(response, ApiErrorId.ERR_INITIAL_RESERVE_ALREADY_SET.value)

    unchanged = read_claim(claim["id"])
    assert unchanged["version"] == claim["version"]
    assert unchanged["reserve_cents"] == 1_018_000
    assert len(read_reserve_entries(claim["id"])) == 2


def test_an_adjustment_below_the_disbursed_amount_is_refused(
    api, claims_adjuster_headers
):
    """PRD Section 3.8: "And an `ADJUSTMENT` entry's `amount_cents` may not be lower than
    the claim's `paid_cents`, because the re-authorised reserve may never fall below what
    has already been disbursed; the attempt is refused with
    `ERR_AUTHORIZATION_BELOW_DISBURSED`."

    Design: Corner/Table 6 Errors/reserve_entry_guards_refuse_a_second_initial_and_an_authorisation_below_the_paid_amount
    """
    scenario = _setup_claim_with_reserve_and_one_payment()
    claim = scenario["claim"]
    assert claim["paid_cents"] == 500_000

    response = api.create_reserve_entry(
        claim["id"],
        reserve_entry_payload(400_000, claim["version"], "ADJUSTMENT",
                              memo="Re-authorisation below the disbursed amount"),
        claims_adjuster_headers,
    )
    validate_error(response, ApiErrorId.ERR_AUTHORIZATION_BELOW_DISBURSED.value)

    unchanged = read_claim(claim["id"])
    assert unchanged["version"] == claim["version"]
    assert unchanged["reserve_cents"] == 1_018_000
    assert len(read_reserve_entries(claim["id"])) == 2


def test_an_adjustment_at_or_above_the_disbursed_amount_overwrites_the_reserve(
    api, claims_adjuster_headers
):
    """PRD Section 3.8: "Crucially, an authorisation **overwrites the reserve target
    rather than adding to it**. On success the claim's `reserve_cents` becomes exactly the
    authorised `amount_cents`, and its `incurred_authorized_cents` becomes the sum of its
    existing `paid_cents`, its existing `released_cents` and that same authorised
    amount."

    PRD Section 2.4: "`version`, an integer that starts at 1 when the row is created and
    increases by exactly 1 each time the row is mutated."

    PRD Section 2.4: "A single mutating request bumps `version` on a given row by exactly
    one, no matter how many fields inside that row it rewrites."

    Design: Corner/Table 6 Errors/reserve_entry_guards_refuse_a_second_initial_and_an_authorisation_below_the_paid_amount
    """
    scenario = _setup_claim_with_reserve_and_one_payment()
    claim = scenario["claim"]
    assert claim["version"] == 6

    response = api.create_reserve_entry(
        claim["id"],
        reserve_entry_payload(600_000, claim["version"], "ADJUSTMENT",
                              memo="Re-authorised above the disbursed amount"),
        claims_adjuster_headers,
    )
    entry = validate_success(response, 201)
    assert_reserve_entry(entry)
    assert entry["entry_type"] == "ADJUSTMENT"
    assert entry["balance_after_reserve_cents"] == 600_000
    assert entry["balance_after_paid_cents"] == 500_000

    after = read_claim(claim["id"])
    assert after["reserve_cents"] == 600_000
    assert after["paid_cents"] == 500_000
    assert after["incurred_authorized_cents"] == 1_100_000
    assert after["version"] == 7
    assert_claim_money_conserved(after)
