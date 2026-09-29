"""The two policy axes, declared initial states, terminal-state lockdown and the
guarded transitions of the claim and escalation machines.

Every test builds its own world from an empty database through PRD-declared
endpoints only.
"""

from test_helpers import (
    ADJUSTER_USER_ID,
    SECOND_ADJUSTER_USER_ID,
    ApiErrorId,
    activate_policy,
    adjudication_payload,
    assert_builder,
    assert_calendar_date,
    assert_claim,
    assert_claim_money_conserved,
    assert_coverage_term,
    assert_escalation_case,
    assert_loss_monitor,
    assert_money_cents,
    assert_neutral,
    assert_policy,
    assert_reserve_entry,
    award_payload,
    complete_repair,
    create_builder_payload,
    create_claim_payload,
    create_escalation_payload,
    create_neutral,
    create_neutral_payload,
    create_policy_payload,
    deactivate_neutral_payload,
    enroll_policy,
    find_term,
    invoice_policy,
    investigation_payload,
    make_builder_principal_headers,
    make_claims_adjuster_headers,
    pay_policy_premium,
    payment_payload,
    read_builder,
    read_claim,
    read_escalation_case,
    read_loss_monitor,
    read_neutral,
    read_policy,
    respond_to_obligation,
    set_clock,
    setup_approved_builder_and_owner,
    setup_arbitration_case,
    setup_builder_arm_claim,
    setup_denied_claim,
    setup_routed_claim,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
)

# The canonical class-C home: 44,500,000 cents in TX closing 2026-08-15 rates a
# premium of 363,894 cents and a builder-obligation boundary of 2028-08-14.
CANONICAL_PREMIUM = 363_894
CLOSING_INSTANT = "2026-08-15T00:00:00Z"


def test_premium_axis_reaches_paid_while_the_coverage_axis_stays_pending_enrollment(
    api, underwriting_officer_headers
):
    """PRD 3.4: "Neither axis waits for the other in general: `premium_status` may
    reach `PAID` while `coverage_status` is still `PENDING_ENROLLMENT`, and
    `coverage_status` may reach `EXPIRED` without `premium_status` ever leaving
    `UNBILLED`."
    PRD 3.2: "The denominator, `earned_premium_cents`, is the sum of `premium_cents`
    over the builder's policies that are **both** in a coverage state of `ACTIVE` or
    `EXPIRED` **and** in a premium state of `PAID`; policies still in
    `PENDING_ENROLLMENT` and policies that were `VOIDED` are excluded, and so is an
    in-force policy whose premium was never paid."
    PRD 3.4: "On success the builder's `earned_premium_cents`, `loss_ratio` and
    `monitoring_posture` are recomputed, this time with real effect, and the policy's
    `version` advances by 1."

    Design: Corner/Table 2 State Machines/premium_axis_reaches_paid_while_the_coverage_axis_stays_pending_enrollment
    """
    scenario = setup_approved_builder_and_owner(clock=CLOSING_INSTANT)
    builder = scenario["builder"]
    policy = enroll_policy(builder["id"], scenario["homeowner"]["id"])
    assert policy["version"] == 1, "a freshly enrolled policy is at version 1"

    invoiced = validate_success(
        api.create_premium_invoice(
            policy["id"], {"invoice_reference": "INV-2026-0815"},
            underwriting_officer_headers,
        )
    )
    assert_policy(invoiced)
    assert invoiced["premium_status"] == "INVOICED"
    assert invoiced["coverage_status"] == "PENDING_ENROLLMENT", (
        "billing moves only the premium axis"
    )
    assert invoiced["version"] == 2

    paid = validate_success(
        api.create_premium_payment(
            policy["id"], {"payment_reference": "ACH-88112"},
            make_builder_principal_headers(builder["id"]),
        )
    )
    assert paid["premium_status"] == "PAID", "the premium axis is now terminal"
    assert paid["coverage_status"] == "PENDING_ENROLLMENT", (
        "the coverage axis is still at its initial state"
    )
    assert paid["version"] == 3

    before = read_loss_monitor(builder["id"])
    assert_loss_monitor(before)
    assert before["earned_premium_cents"] == 0, (
        "a PAID premium on a PENDING_ENROLLMENT policy is excluded from the denominator"
    )
    assert before["policy_count"] == 0

    active = validate_success(api.activate_policy(policy["id"], underwriting_officer_headers))
    assert active["premium_status"] == "PAID", (
        "the coverage axis moved without disturbing the premium axis"
    )
    assert active["coverage_status"] == "ACTIVE"
    assert active["version"] == 4

    after = read_loss_monitor(builder["id"])
    assert after["earned_premium_cents"] == CANONICAL_PREMIUM, (
        f"the premium enters the denominator only once both axes qualify, "
        f"expected {CANONICAL_PREMIUM}, got {after['earned_premium_cents']}"
    )
    assert_money_cents(after["earned_premium_cents"], "earned_premium_cents")
    assert after["policy_count"] == 1

    reread_builder = read_builder(builder["id"])
    assert reread_builder["loss_ratio"] == 0.0000, "no claim exists so the numerator is 0"
    assert reread_builder["monitoring_posture"] == "OPEN"


def test_activation_before_the_premium_payment_is_refused_as_premium_not_paid(
    api, underwriting_officer_headers
):
    """PRD 3.4: "Its `premium_status` must be exactly `PAID` — this is the cross-axis
    guard, and a policy whose premium is `UNBILLED` or `INVOICED` is refused with
    `ERR_PREMIUM_NOT_PAID`."
    PRD 3.4: "An `UnderwritingOfficer` drives `coverage_status` from
    `PENDING_ENROLLMENT` to `ACTIVE` with no request body at all, and four conditions
    must hold."

    Design: Corner/Table 2 State Machines/activation_before_the_premium_payment_is_refused_as_premium_not_paid
    """
    scenario = setup_approved_builder_and_owner(clock=CLOSING_INSTANT)
    builder = scenario["builder"]
    policy = enroll_policy(builder["id"], scenario["homeowner"]["id"])
    invoiced = invoice_policy(policy["id"])
    assert invoiced["version"] == 2, "the invoice is the policy's first mutation"

    refused = api.activate_policy(policy["id"], underwriting_officer_headers)
    validate_error(refused, ApiErrorId.ERR_PREMIUM_NOT_PAID.value)

    unchanged = read_policy(policy["id"])
    assert unchanged["version"] == 2, "the refused transition wrote nothing"
    assert unchanged["coverage_status"] == "PENDING_ENROLLMENT"
    assert unchanged["premium_status"] == "INVOICED"

    pay_policy_premium(policy["id"], builder["id"])
    activated = validate_success(
        api.activate_policy(policy["id"], underwriting_officer_headers)
    )
    assert activated["coverage_status"] == "ACTIVE", (
        "the same call succeeds once the payment lands"
    )
    assert activated["version"] == 4

    assert read_builder(builder["id"])["earned_premium_cents"] == CANONICAL_PREMIUM, (
        "the premium enters the denominator only after the successful activation"
    )


def test_enrollment_mints_three_base_terms_with_pinned_windows_limits_and_deductibles(
    api, underwriting_officer_headers
):
    """PRD 3.3: "The same enrollment mints the home's coverage. Three `BASE`
    coverage terms are created, one per `coverage_type`, all sharing a `start_date`
    equal to the policy's `coverage_start_date`."
    PRD 3.3: "Their `end_date` values are derived by an anniversary rule: take the
    closing date, advance the year by the term's length in years while keeping the
    same month and day, and then step back one day."
    PRD 3.3: "The same anniversary arithmetic, applied with the builder's
    `obligation_period_years` of 2, yields `builder_obligation_end_date` on the
    policy — which is therefore the same calendar date as the systems term's
    `end_date`, and is the boundary that decides who answers for a claim."
    PRD 3.3: "`deductible_cents` is 100,000 cents — one thousand dollars — on the
    workmanship and systems terms, and 250,000 cents on the structural term,
    reflecting the heavier engineering cost of a structural claim."
    PRD 3.3: "Every new term is born with `term_kind` `BASE`, `status` `OPEN`,
    `consumed_limit_cents` of 0, and `remaining_limit_cents` equal to its
    `limit_cents`."

    Design: Corner/Table 2 State Machines/enrollment_mints_three_base_terms_with_pinned_windows_limits_and_deductibles
    """
    scenario = setup_approved_builder_and_owner(clock=CLOSING_INSTANT)
    created = validate_success(
        api.create_policy(
            create_policy_payload(scenario["builder"]["id"],
                                  scenario["homeowner"]["id"]),
            scenario["builder_headers"],
        ),
        expected_status=201,
    )
    assert_policy(created)
    assert created["coverage_start_date"] == "2026-08-15", (
        "coverage_start_date is the closing date itself"
    )
    assert created["builder_obligation_end_date"] == "2028-08-14", (
        "the two-year anniversary of 2026-08-15 stepped back one day"
    )
    assert_calendar_date(created["builder_obligation_end_date"])

    rows, meta = validate_paginated(
        api.list_policy_coverage_terms(created["id"], underwriting_officer_headers,
                                       {"limit": 100})
    )
    assert meta["total_count"] == 3, (
        f"enrollment mints exactly three BASE terms, saw {meta['total_count']}"
    )
    assert len(rows) == 3

    expected = {
        "WORKMANSHIP": ("2027-08-14", 2_000_000, 100_000),
        "SYSTEMS": ("2028-08-14", 6_000_000, 100_000),
        "STRUCTURAL": ("2036-08-14", 44_500_000, 250_000),
    }
    for coverage_type, (end_date, limit_cents, deductible_cents) in expected.items():
        term = find_term(rows, coverage_type)
        assert_coverage_term(term)
        assert term["policy_id"] == created["id"]
        assert term["term_kind"] == "BASE"
        assert term["status"] == "OPEN"
        assert term["start_date"] == "2026-08-15", (
            f"the {coverage_type} term is anchored on coverage_start_date"
        )
        assert term["end_date"] == end_date, (
            f"{coverage_type} end_date expected {end_date}, got {term['end_date']}"
        )
        assert term["limit_cents"] == limit_cents, (
            f"{coverage_type} limit_cents expected {limit_cents}, "
            f"got {term['limit_cents']}"
        )
        assert term["deductible_cents"] == deductible_cents, (
            f"{coverage_type} deductible_cents expected {deductible_cents}, "
            f"got {term['deductible_cents']}"
        )
        assert term["consumed_limit_cents"] == 0
        assert term["remaining_limit_cents"] == term["limit_cents"]
        assert term["version"] == 1, "a freshly minted term has never been mutated"

    assert find_term(rows, "SYSTEMS")["end_date"] == (
        created["builder_obligation_end_date"]
    ), "the obligation boundary is the systems term's own end date"


def test_a_second_investigation_on_the_same_claim_returns_invalid_claim_state(
    api, claims_adjuster_headers
):
    """PRD 3.6: "Investigating a claim that is not in `SUBMITTED` is refused with
    `ERR_INVALID_CLAIM_STATE`."
    PRD 3.6: "A `ClaimsAdjuster` records a `substantiation_ratio` — the share of the
    claimed amount the carrier accepts as substantiated, between 0.00 and 1.00
    inclusive with at most two decimal places — and the claim advances from
    `SUBMITTED` to `UNDER_INVESTIGATION`."
    PRD 3.6: "The ratio is stored on the claim and the first step of the settlement
    waterfall runs immediately so that the substantiated figure is observable before
    any routing decision: `gross_adjusted_cents` is the `claimed_amount_cents`
    multiplied by the `substantiation_ratio`, rounded half up to whole cents."

    Design: Corner/Table 2 State Machines/a_second_investigation_on_the_same_claim_returns_invalid_claim_state
    """
    scenario = setup_routed_claim(claimed_amount_cents=2_187_500,
                                 substantiation_ratio=0.80, route=False)
    claim = scenario["claim"]
    assert claim["status"] == "UNDER_INVESTIGATION", (
        "the first investigation already consumed the SUBMITTED origin state"
    )
    assert claim["substantiation_ratio"] == 0.80
    assert claim["gross_adjusted_cents"] == 1_750_000, (
        "2,187,500 at 0.80 substantiated is 1,750,000 cents"
    )
    assert claim["version"] == 2

    refused = api.create_investigation(
        claim["id"], investigation_payload(0.40), claims_adjuster_headers
    )
    validate_error(refused, ApiErrorId.ERR_INVALID_CLAIM_STATE.value)

    unchanged = read_claim(claim["id"])
    assert_claim(unchanged)
    assert unchanged["substantiation_ratio"] == 0.80, (
        "the refused call must not overwrite the stored ratio"
    )
    assert unchanged["gross_adjusted_cents"] == 1_750_000, (
        "the substantiated gross must not be recomputed from the refused ratio"
    )
    assert unchanged["status"] == "UNDER_INVESTIGATION"
    assert unchanged["version"] == 2, "a refused transition advances nothing"


def test_every_machine_starts_in_its_declared_initial_state(
    api, underwriting_officer_headers, compliance_officer_headers
):
    """PRD 3.1: "The new file lands in `underwriting_status` `DRAFT` with no score at
    all — `risk_score`, `risk_class` and `risk_basis` are all null — and with its
    monitoring counters at rest: `earned_premium_cents` and `incurred_loss_cents` are
    0, `loss_ratio` is 0.0000, `monitoring_posture` is `OPEN`, and
    `default_declared_at` is null."
    PRD 3.3: "The policy's two independent state axes begin at `coverage_status`
    `PENDING_ENROLLMENT` and `premium_status` `UNBILLED`."
    PRD 3.3: "Every new term is born with `term_kind` `BASE`, `status` `OPEN`,
    `consumed_limit_cents` of 0, and `remaining_limit_cents` equal to its
    `limit_cents`."
    PRD 3.9: "A new neutral is born with `status` `ACTIVE` and
    `booked_session_count` of 0."
    PRD 3.6: "A fresh claim lands in `status` `SUBMITTED` with `designated_structural`
    false and with all four money fields — `reserve_cents`, `paid_cents`,
    `released_cents` and `incurred_authorized_cents` — at 0."

    Design: Corner/Table 2 State Machines/every_machine_starts_in_its_declared_initial_state
    """
    draft = validate_success(
        api.create_builder(create_builder_payload(), underwriting_officer_headers),
        expected_status=201,
    )
    assert_builder(draft)
    assert draft["underwriting_status"] == "DRAFT"
    assert draft["risk_score"] is None, "a DRAFT file carries no score at all"
    assert draft["risk_class"] is None
    assert draft["risk_basis"] is None
    assert draft["earned_premium_cents"] == 0
    assert draft["incurred_loss_cents"] == 0
    assert draft["loss_ratio"] == 0.0000
    assert draft["monitoring_posture"] == "OPEN"
    assert draft["default_declared_at"] is None
    assert draft["version"] == 1

    panel_member = validate_success(
        api.create_neutral(create_neutral_payload(), compliance_officer_headers),
        expected_status=201,
    )
    assert_neutral(panel_member)
    assert panel_member["status"] == "ACTIVE"
    assert panel_member["booked_session_count"] == 0
    assert panel_member["version"] == 1

    scenario = setup_approved_builder_and_owner(clock=CLOSING_INSTANT)
    policy = validate_success(
        api.create_policy(
            create_policy_payload(scenario["builder"]["id"],
                                  scenario["homeowner"]["id"]),
            scenario["builder_headers"],
        ),
        expected_status=201,
    )
    assert policy["coverage_status"] == "PENDING_ENROLLMENT", (
        "the coverage axis starts at PENDING_ENROLLMENT"
    )
    assert policy["premium_status"] == "UNBILLED", (
        "the premium axis starts at UNBILLED"
    )
    assert policy["transfer_count"] == 0
    assert policy["enrollment_hold"] is False
    assert policy["pending_transfer_id"] is None
    assert policy["version"] == 1

    open_terms, terms_meta = validate_paginated(
        api.list_policy_coverage_terms(policy["id"], underwriting_officer_headers,
                                       {"status": "OPEN", "limit": 100})
    )
    assert terms_meta["total_count"] == 3, (
        "all three freshly minted terms start OPEN, "
        f"saw {terms_meta['total_count']}"
    )
    for term in open_terms:
        assert term["term_kind"] == "BASE"
        assert term["status"] == "OPEN"
        assert term["consumed_limit_cents"] == 0
        assert term["remaining_limit_cents"] == term["limit_cents"]

    invoice_policy(policy["id"])
    pay_policy_premium(policy["id"], scenario["builder"]["id"])
    activate_policy(policy["id"])
    fresh_claim = validate_success(
        api.create_claim(
            create_claim_payload(policy["id"], coverage_type="WORKMANSHIP",
                                 defect_category="WORKMANSHIP_DEFECT",
                                 claimed_amount_cents=400_000),
            scenario["owner_headers"],
        ),
        expected_status=201,
    )
    assert_claim(fresh_claim)
    assert fresh_claim["status"] == "SUBMITTED", "the claim machine starts at SUBMITTED"
    assert fresh_claim["designated_structural"] is False
    for field in ("reserve_cents", "paid_cents", "released_cents",
                  "incurred_authorized_cents", "gross_adjusted_cents",
                  "deductible_applied_cents", "betterment_cents",
                  "net_payable_cents"):
        assert fresh_claim[field] == 0, f"{field} starts at 0, got {fresh_claim[field]}"
    assert fresh_claim["substantiation_ratio"] is None
    assert fresh_claim["adjudicated_by_user_id"] is None
    assert fresh_claim["denial_date"] is None
    assert fresh_claim["escalation_deadline_date"] is None
    assert fresh_claim["version"] == 1


def test_closed_repaired_holds_the_builder_arm_settlement_with_no_insurer_money(api):
    """PRD 3.7: "When the repair is finished the same builder reports a
    `completion_date`, and the claim advances `BUILDER_REPAIR_ACCEPTED →
    CLOSED_REPAIRED`, a terminal state reached with **zero insurer money**:
    `reserve_cents`, `paid_cents`, `released_cents` and `incurred_authorized_cents`
    are all still 0."
    PRD 3.7: "The settlement waterfall runs under the **builder-obligation variant**,
    writing `betterment_cents` and `net_payable_cents` and forcing
    `deductible_applied_cents` to 0 — the builder repairs in kind, so no policy
    deductible is charged to the homeowner."
    PRD 3.2: "`open_claim_count` is the number of claims on any policy of this builder
    whose `status` is not one of the six terminal claim states, namely
    `CLOSED_REPAIRED`, `CLOSED_PAID`, `CLOSED_SETTLED`, `CLOSED_AWARDED`,
    `CLOSED_DENIED_FINAL` and `SUSPENDED_NO_LIMIT`."

    Design: Corner/Table 2 State Machines/closed_repaired_is_terminal_so_adjudication_payment_and_escalation_are_all_refused
    """
    scenario = setup_builder_arm_claim(claimed_amount_cents=2_187_500,
                                      substantiation_ratio=0.80)
    builder = scenario["builder"]
    claim = scenario["claim"]
    assert claim["status"] == "BUILDER_OBLIGATION_NOTICE"
    assert claim["obligor"] == "BUILDER"

    respond_to_obligation(claim["id"], builder["id"], "ACCEPT_OBLIGATION")
    complete_repair(claim["id"], builder["id"], completion_date="2026-08-20")

    repaired = read_claim(claim["id"])
    assert_claim(repaired)
    assert repaired["status"] == "CLOSED_REPAIRED", (
        "the builder arm ends in its own terminal state"
    )
    assert repaired["gross_adjusted_cents"] == 1_750_000
    assert repaired["deductible_applied_cents"] == 0, (
        "the builder-obligation variant charges no deductible"
    )
    assert repaired["betterment_cents"] == 140_000, (
        "8 percent of a provisional net of 1,750,000 cents"
    )
    assert repaired["net_payable_cents"] == 1_610_000, (
        f"1,750,000 less 140,000 betterment, got {repaired['net_payable_cents']}"
    )
    for field in ("reserve_cents", "paid_cents", "released_cents",
                  "incurred_authorized_cents"):
        assert repaired[field] == 0, (
            f"no insurer money ever moved, yet {field} is {repaired[field]}"
        )
    assert_claim_money_conserved(repaired)
    assert repaired["version"] == 5, (
        "filing, investigation, routing, acceptance and completion are five writes"
    )

    monitor = read_loss_monitor(builder["id"])
    assert_loss_monitor(monitor)
    assert monitor["incurred_loss_cents"] == 0, (
        "a builder-arm claim never enters the numerator"
    )
    assert monitor["loss_ratio"] == 0.0000
    assert monitor["monitoring_posture"] == "OPEN"
    assert monitor["open_claim_count"] == 0, (
        "CLOSED_REPAIRED is one of the six terminal claim states"
    )


def test_closed_repaired_refuses_adjudication_payment_and_escalation(
    api, claims_adjuster_headers, compliance_officer_headers
):
    """PRD 2.8: "**From-state admission (409).** The addressed row is in a declared
    origin state for the requested transition, or the matching state error:
    `ERR_INVALID_BUILDER_STATE`, `ERR_INVALID_POLICY_STATE` for the coverage axis,
    `ERR_INVALID_PREMIUM_STATE` for the premium axis, `ERR_INVALID_CLAIM_STATE`,
    `ERR_INVALID_TRANSFER_STATE`, `ERR_INVALID_ESCALATION_STATE`, or
    `ERR_INVALID_NEUTRAL_STATE`. Applies to every state-transition endpoint."
    PRD 3.7: "Adjudication closes the insurer arm's deliberation. A `ClaimsAdjuster`
    submits an `outcome` of `APPROVE` or `DENY` with an optional `adjudication_note`,
    from a claim in `INSURER_ADJUDICATION`, and in both branches the acting
    `X-User-ID` is recorded as the claim's `adjudicated_by_user_id` and the claim's
    `version` advances by 1."
    PRD 3.8: "Two ceilings then apply, in order: the amount may not exceed the claim's
    `reserve_cents`, or `ERR_PAYMENT_EXCEEDS_RESERVE`; and it may not exceed the
    `remaining_limit_cents` of the claim's coverage term, or
    `ERR_COVERAGE_LIMIT_EXCEEDED`."
    PRD 3.9: "The first rung requires the claim to be in `DENIED` and advances it
    `DENIED → MEDIATION`."

    Design: Corner/Table 2 State Machines/closed_repaired_is_terminal_so_adjudication_payment_and_escalation_are_all_refused
    """
    scenario = setup_builder_arm_claim(claimed_amount_cents=2_187_500,
                                      substantiation_ratio=0.80)
    builder = scenario["builder"]
    claim = scenario["claim"]
    respond_to_obligation(claim["id"], builder["id"], "ACCEPT_OBLIGATION")
    complete_repair(claim["id"], builder["id"], completion_date="2026-08-20")
    assert read_claim(claim["id"])["status"] == "CLOSED_REPAIRED"

    validate_error(
        api.create_adjudication(claim["id"], adjudication_payload("APPROVE"),
                                claims_adjuster_headers),
        ApiErrorId.ERR_INVALID_CLAIM_STATE.value,
    )

    # The PRD states no from-state precondition for a disbursement, so a
    # terminal claim carrying a zero reserve may be refused either by the claim
    # machine or by the reserve ceiling; both are faithful to the document.
    validate_error_is_one_of(
        api.create_payment(claim["id"], payment_payload(100_000),
                           make_claims_adjuster_headers(SECOND_ADJUSTER_USER_ID)),
        [ApiErrorId.ERR_INVALID_CLAIM_STATE.value,
         ApiErrorId.ERR_PAYMENT_EXCEEDS_RESERVE.value],
    )

    mediator = create_neutral(full_name="Ivo Rand", credential="MEDIATOR")
    validate_error(
        api.create_escalation(
            claim["id"],
            create_escalation_payload(mediator["id"], "MEDIATION",
                                      "2026-09-05T14:00:00Z",
                                      "2026-09-05T16:00:00Z"),
            scenario["owner_headers"],
        ),
        ApiErrorId.ERR_INVALID_CLAIM_STATE.value,
    )

    untouched = read_claim(claim["id"])
    assert untouched["status"] == "CLOSED_REPAIRED", "the terminal state is a lockdown"
    assert untouched["version"] == 5, "three refusals wrote nothing at all"
    assert untouched["adjudicated_by_user_id"] is None, (
        "the refused adjudication must not stamp an adjudicator"
    )
    for field in ("reserve_cents", "paid_cents", "released_cents",
                  "incurred_authorized_cents"):
        assert untouched[field] == 0, f"{field} moved on a refused request"

    assert read_neutral(mediator["id"])["booked_session_count"] == 0, (
        "the refused booking must not consume the neutral's calendar"
    )
    cases, cases_meta = validate_paginated(
        api.list_escalation_cases(compliance_officer_headers,
                                  {"claim_id": claim["id"], "limit": 100})
    )
    assert cases_meta["total_count"] == 0, (
        f"a refused rung creates no escalation case, saw {cases_meta['total_count']}"
    )
    assert cases == []


def test_a_deactivated_neutral_cannot_be_booked_for_a_new_mediation(
    api, compliance_officer_headers
):
    """PRD 3.9: "Retiring a neutral is also compliance's move: with a `reason`, the
    neutral moves `ACTIVE → INACTIVE`, a terminal state, and its `version` advances by
    1; a deactivation aimed at a neutral that is already `INACTIVE` is refused with
    `ERR_INVALID_NEUTRAL_STATE`."
    PRD 3.9: "The booked neutral's `status` must be `ACTIVE`, or
    `ERR_NEUTRAL_INACTIVE`."
    PRD 3.9: "A successful booking creates an escalation case against the claim named
    in its `claim_id`, in `status` `SCHEDULED`, with `binding` false for a `MEDIATION`
    case and true for an `ARBITRATION` case — `binding` is derived from the stage and
    is never supplied by the client."
    PRD 3.9: "The booked neutral's `booked_session_count` is incremented by 1 and its
    `version` advances by 1; that counter is the number of escalation cases naming
    this neutral whose `status` is `SCHEDULED`, `SETTLED`, `IMPASSE` or
    `AWARD_ISSUED`."
    PRD 3.7: "`escalation_deadline_date` is set to that denial date plus 60 days — the
    mediation window, and the deadline is **inclusive**, so opening the next rung
    exactly on `escalation_deadline_date` is allowed and one day later is not."

    Design: Corner/Table 2 State Machines/a_deactivated_neutral_cannot_be_booked_for_a_new_mediation
    """
    scenario = setup_denied_claim(claimed_amount_cents=2_187_500,
                                 substantiation_ratio=0.80)
    claim = scenario["claim"]
    assert claim["status"] == "DENIED"
    assert claim["escalation_deadline_date"] == "2028-10-31", (
        "a denial on 2028-09-01 opens a 60-day inclusive mediation window"
    )

    retired = create_neutral(full_name="Ivo Rand", credential="MEDIATOR")
    deactivated = validate_success(
        api.deactivate_neutral(retired["id"], deactivate_neutral_payload(),
                               compliance_officer_headers)
    )
    assert_neutral(deactivated)
    assert deactivated["status"] == "INACTIVE"
    assert deactivated["version"] == 2, "retirement is the neutral's first mutation"

    validate_error(
        api.create_escalation(
            claim["id"],
            create_escalation_payload(retired["id"], "MEDIATION",
                                      "2028-09-10T14:00:00Z",
                                      "2028-09-10T16:00:00Z"),
            scenario["owner_headers"],
        ),
        ApiErrorId.ERR_NEUTRAL_INACTIVE.value,
    )
    after_refusal = read_neutral(retired["id"])
    assert after_refusal["booked_session_count"] == 0, (
        "a retired neutral takes no new bookings"
    )
    assert after_refusal["version"] == 2, "the refused booking rewrote nothing"
    assert read_claim(claim["id"])["status"] == "DENIED", (
        "the claim machine did not advance on the refused rung"
    )

    serving = create_neutral(full_name="Marta Quill", credential="MEDIATOR")
    case = validate_success(
        api.create_escalation(
            claim["id"],
            create_escalation_payload(serving["id"], "MEDIATION",
                                      "2028-09-10T14:00:00Z",
                                      "2028-09-10T16:00:00Z"),
            scenario["owner_headers"],
        ),
        expected_status=201,
    )
    assert_escalation_case(case)
    assert case["claim_id"] == claim["id"]
    assert case["neutral_id"] == serving["id"]
    assert case["stage"] == "MEDIATION"
    assert case["status"] == "SCHEDULED"
    assert case["binding"] is False, "a mediation case is never binding"
    assert case["settlement_amount_cents"] is None
    assert case["award_amount_cents"] is None
    assert case["version"] == 1

    booked = read_neutral(serving["id"])
    assert booked["booked_session_count"] == 1, (
        "the ACTIVE neutral's calendar took the SCHEDULED case"
    )
    assert booked["version"] == 2
    escalated_claim = read_claim(claim["id"])
    assert escalated_claim["status"] == "MEDIATION"
    assert escalated_claim["version"] == 5, (
        "filing, investigation, routing, denial and the rung are five writes"
    )

    rows, meta = validate_paginated(
        api.list_escalation_cases(compliance_officer_headers,
                                  {"claim_id": claim["id"], "limit": 100})
    )
    assert meta["total_count"] == 1, (
        f"only the successful booking exists, saw {meta['total_count']}"
    )
    assert rows[0]["id"] == case["id"]


def test_denial_releases_the_reserve_and_syncs_the_builder_incurred_ledger(
    api, compliance_officer_headers
):
    """PRD 3.7: "The reserve is given back: the whole of the claim's `reserve_cents` is
    added to its `released_cents` and `reserve_cents` is set to 0, leaving
    `incurred_authorized_cents` unchanged."
    PRD 3.7: "A reserve-journal row of `entry_type` `RELEASE` is appended for the
    released amount with `recorded_by_user_id` set to the acting `X-User-ID` — but only
    when the released amount is at least 1 cent; a denial of a claim carrying no
    reserve appends no journal row."
    PRD 3.7: "Finally the builder's `incurred_loss_cents`, `loss_ratio` and
    `monitoring_posture` are recomputed, and because releasing a reserve removes it
    from the numerator, a denial *lowers* the builder's loss ratio."
    PRD 3.2: "A claim's `released_cents` never enters the numerator, which is why
    releasing a reserve lowers a builder's incurred loss."

    Design: Corner/Table 2 State Machines/denial_releases_the_reserve_and_syncs_the_builder_incurred_ledger
    """
    scenario = setup_routed_claim(claimed_amount_cents=2_187_500,
                                 substantiation_ratio=0.80)
    builder = scenario["builder"]
    claim = scenario["claim"]
    assert claim["status"] == "INSURER_ADJUDICATION"
    assert claim["obligor"] == "INSURER"
    assert claim["net_payable_cents"] == 1_518_000, (
        "1,750,000 less a 100,000 deductible less 132,000 betterment"
    )
    assert claim["reserve_cents"] == 1_518_000
    assert claim["incurred_authorized_cents"] == 1_518_000
    assert claim["released_cents"] == 0

    before = read_loss_monitor(builder["id"])
    assert before["earned_premium_cents"] == CANONICAL_PREMIUM
    assert before["incurred_loss_cents"] == 1_518_000, (
        "the reserve on an insurer-arm claim is the whole numerator"
    )
    assert before["loss_ratio"] == 4.1715, (
        f"1,518,000 over 363,894 rounds half up to 4.1715, got {before['loss_ratio']}"
    )
    assert before["monitoring_posture"] == "FROZEN"
    assert before["open_claim_count"] == 1

    denied = validate_success(
        api.create_adjudication(
            claim["id"],
            adjudication_payload("DENY", adjudication_note="maintenance exclusion"),
            make_claims_adjuster_headers(ADJUSTER_USER_ID),
        )
    )
    assert_claim(denied)
    assert denied["status"] == "DENIED"
    assert denied["denial_date"] == "2028-09-01", (
        "denial_date comes from the logical clock, never from the request"
    )
    assert denied["adjudicated_by_user_id"] == ADJUSTER_USER_ID
    assert denied["reserve_cents"] == 0, "the whole reserve was given back"
    assert denied["released_cents"] == 1_518_000
    assert denied["paid_cents"] == 0
    assert denied["incurred_authorized_cents"] == 1_518_000, (
        "a release never disturbs the authorised total"
    )
    assert_claim_money_conserved(denied)
    assert denied["version"] == 4

    after = read_loss_monitor(builder["id"])
    assert after["earned_premium_cents"] == CANONICAL_PREMIUM, (
        "the denominator is untouched by a denial"
    )
    assert after["incurred_loss_cents"] == 0, (
        f"released money leaves the numerator, got {after['incurred_loss_cents']}"
    )
    assert after["loss_ratio"] == 0.0000, "the denial lowered the ratio to nothing"
    assert after["monitoring_posture"] == "OPEN"
    assert after["open_claim_count"] == 1, "DENIED is not one of the terminal states"
    assert read_builder(builder["id"])["incurred_loss_cents"] == 0, (
        "the builder row carries the same recomputed figure as the monitor view"
    )

    rows, meta = validate_paginated(
        api.list_reserve_entries(compliance_officer_headers,
                                 {"claim_id": claim["id"],
                                  "entry_type": "RELEASE", "limit": 100})
    )
    assert meta["total_count"] == 1, (
        f"exactly one RELEASE row records the give-back, saw {meta['total_count']}"
    )
    release = rows[0]
    assert_reserve_entry(release)
    assert release["entry_type"] == "RELEASE"
    assert release["amount_cents"] == 1_518_000
    assert release["recorded_by_user_id"] == ADJUSTER_USER_ID
    assert release["balance_after_reserve_cents"] == 0
    assert release["balance_after_paid_cents"] == 0


def test_a_zero_arbitration_award_is_the_binding_final_denial(
    api, compliance_officer_headers
):
    """PRD 3.9: "The award has two symmetric branches, and **a zero award is a legal
    value, not a validation error** — it is the binding final denial."
    PRD 3.9: "When `award_amount_cents` is exactly 0, the claim advances `ARBITRATION →
    CLOSED_DENIED_FINAL`, the whole of its `reserve_cents` is added to its
    `released_cents` and its `reserve_cents` is set to 0, leaving
    `incurred_authorized_cents` unchanged, and a journal row of `entry_type` `RELEASE`
    for the released amount is appended when that amount is at least 1 cent."
    PRD 3.9: "The request carries the `award_amount_cents` and an optional
    `award_note`, and the case moves `SCHEDULED → AWARD_ISSUED` with
    `award_amount_cents` recorded."
    PRD 3.9: "An outcome of `IMPASSE` moves the case `SCHEDULED → IMPASSE` and
    deliberately leaves the claim's `status` alone — a deadlocked mediation keeps the
    claim in `MEDIATION` so the arbitration rung remains reachable."
    PRD 3.9: "What it does change is the clock on that rung: the claim's
    `escalation_deadline_date` is rewritten to the logical clock's current date plus 30
    days, the arbitration window."

    Design: Corner/Table 2 State Machines/a_zero_arbitration_award_is_the_binding_final_denial
    """
    scenario = setup_arbitration_case(claimed_amount_cents=2_187_500,
                                     substantiation_ratio=0.80)
    builder = scenario["builder"]
    claim = scenario["claim"]
    arbitration_case = scenario["arbitration_case"]
    assert claim["status"] == "ARBITRATION"
    assert claim["escalation_deadline_date"] == "2028-10-10", (
        "the impasse on 2028-09-10 rewrote the deadline 30 days out"
    )
    assert claim["released_cents"] == 1_518_000, (
        "the denial had already released the whole reserve"
    )
    assert claim["reserve_cents"] == 0

    set_clock("2028-09-20T15:00:00Z")
    awarded = validate_success(
        api.create_award(arbitration_case["id"], award_payload(0),
                         make_claims_adjuster_headers(ADJUSTER_USER_ID))
    )
    assert_escalation_case(awarded)
    assert awarded["stage"] == "ARBITRATION"
    assert awarded["status"] == "AWARD_ISSUED"
    assert awarded["award_amount_cents"] == 0, "a zero award is a legal outcome"
    assert awarded["binding"] is True, "the arbitration rung is binding"
    assert awarded["version"] == 2

    final = read_claim(claim["id"])
    assert_claim(final)
    assert final["status"] == "CLOSED_DENIED_FINAL", (
        "a zero award closes the claim as a binding final denial"
    )
    assert final["reserve_cents"] == 0
    assert final["paid_cents"] == 0
    assert final["released_cents"] == 1_518_000, (
        "there was nothing left to release, so the figure is unchanged"
    )
    assert final["incurred_authorized_cents"] == 1_518_000
    assert_claim_money_conserved(final)
    assert final["version"] == 8, (
        "filing, investigation, routing, denial, two rungs, the impasse and the "
        "award are eight writes"
    )

    mediation = read_escalation_case(scenario["mediation_case"]["id"])
    assert mediation["status"] == "IMPASSE", "the deadlocked rung stays IMPASSE"
    assert mediation["binding"] is False
    assert mediation["outcome_recorded_by_user_id"] == SECOND_ADJUSTER_USER_ID, (
        "a different adjuster recorded the impasse, so the award is permitted"
    )
    assert mediation["version"] == 2

    rows, meta = validate_paginated(
        api.list_reserve_entries(compliance_officer_headers,
                                 {"claim_id": claim["id"],
                                  "entry_type": "RELEASE", "limit": 100})
    )
    assert meta["total_count"] == 1, (
        "a zero release appends no second journal row, "
        f"saw {meta['total_count']} RELEASE rows"
    )
    assert rows[0]["amount_cents"] == 1_518_000

    monitor = read_loss_monitor(builder["id"])
    assert_loss_monitor(monitor)
    assert monitor["incurred_loss_cents"] == 0
    assert monitor["loss_ratio"] == 0.0000
    assert monitor["monitoring_posture"] == "OPEN"
    assert monitor["open_claim_count"] == 0, (
        "CLOSED_DENIED_FINAL is one of the six terminal claim states"
    )
