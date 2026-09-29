"""State-machine tests: initial states, single transitions, guards and terminals.

Each test drives one transition (or one refusal) and pins exactly what the
transition writes, what it leaves alone, and which cascade hops it sets off.
Every money figure asserted here is computed from the rates the program's
reference data carries, so the expected integers are exact rather than
approximate.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import api_errors as E
from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as S
from test_helpers.assertions import (
    assert_common_fields,
    assert_empty,
    assert_fields,
    assert_reason_codes,
    bps_of,
    ids_of,
    round_half_up,
)
from test_helpers.test_users import (
    ADMIN_HEADERS,
    AGENT_HEADERS,
    ANALYST_HEADERS,
    SECOND_UNDERWRITER_HEADERS,
    UNDERWRITER_HEADERS,
    UNDERWRITER_ID,
)


# ─── module-private builders ──────────────────────────

def _pending_review_merchant(api):
    """A merchant with a verified licence standing at `PENDING_REVIEW` at version 2."""
    return S.approved_merchant(api, approve=False)


def _declined_merchant(api):
    """A merchant declined out of review: terminal `DECLINED` at version 3."""
    scenario = _pending_review_merchant(api)
    scenario.merchant = S.decide_enrollment(
        api, scenario.merchant_id, "DECLINE",
        decision_note="State board complaint history",
    )
    return scenario


def _draft_merchant_with_trade_rule(api):
    """Reference data laid down and a merchant registered but never submitted."""
    scenario = S.program(api)
    scenario.merchant = S.register_merchant(api)
    return scenario


def _project_verified_to_seven_thousand_bps(api):
    """A project whose first two milestones are `VERIFIED` and whose third is `CLAIMED`."""
    scenario = S.project_with_milestones(
        api, releases=(3000, 4000, 3000), verify=(0, 1)
    )
    S.claim_milestone(api, scenario, 2)
    scenario.project = S.read_project(api, scenario.project_id)
    return scenario


def _milestones_with_distinct_signoff_flags(api):
    """Two claimed milestones: the first requires consumer signoff, the second does not."""
    scenario = S.project(api)
    for index, (share, flag) in enumerate(((3000, True), (4000, False))):
        scenario.milestones.append(
            validate_success(
                api.create_milestone(
                    scenario.project_id,
                    F.milestone_payload(
                        sequence_no=index + 1,
                        name=C.CANONICAL_MILESTONES[index]["name"],
                        release_pct_bps=share,
                        requires_consumer_signoff=flag,
                    ),
                    scenario.as_merchant,
                ),
                201,
            )
        )
        S.claim_milestone(api, scenario, index)
    return scenario


def _merchant_with_approved_and_declined_applications(api):
    """An enrolled merchant carrying one `APPROVED` and one `DECLINED` application."""
    scenario = S.enrolled_merchant(api)
    scenario.consumer = S.register_consumer(api, scenario.merchant_id)
    scenario.application = validate_success(
        api.create_credit_application(
            F.credit_application_payload(
                scenario.merchant_id, scenario.consumer_id, scenario.plan_id
            ),
            scenario.as_merchant,
        ),
        201,
    )
    weak = S.register_consumer(
        api, scenario.merchant_id, full_name="Marcus Pike", ssn_last4="3310",
        fico_score=619,
    )
    scenario.declined_application = validate_success(
        api.create_credit_application(
            F.credit_application_payload(
                scenario.merchant_id, weak["id"], scenario.plan_id,
                project_amount_cents=1000000,
            ),
            scenario.as_merchant,
        ),
        201,
    )
    return scenario


def _settled_draw_and_pending_draw(api):
    """One settled draw of 1,050,000 and one pending draw of 1,400,000 on the same project."""
    scenario = S.project_with_milestones(
        api, releases=(3000, 4000, 3000), verify=(0, 1)
    )
    S.request_draw(api, scenario, 1050000, milestone_index=0)
    S.settle_draw(api, scenario)
    S.request_draw(api, scenario, 1400000, milestone_index=1)
    return scenario


# ─── state_machines/every_entity_lands_in_its_declared_initial_state ───

def test_created_draw_stands_at_requested_with_no_settlement_facts_yet(api):
    """A draw is born REQUESTED with its funded amount frozen and every settlement fact empty.

    PRD: "A created draw stands at `status` `REQUESTED`, and its `funded_amount_cents` is frozen at that moment as a copy of `requested_amount_cents`; nothing later changes it."

    Design: Corner/state_machines/every_entity_lands_in_its_declared_initial_state
    """
    scenario = S.project_with_milestones(api, releases=(3000, 4000, 3000), verify=(0,))

    draw = S.request_draw(api, scenario, 1050000, milestone_index=0)

    assert_fields(
        draw,
        status="REQUESTED",
        requested_amount_cents=1050000,
        funded_amount_cents=1050000,
        merchant_id=scenario.merchant_id,
        loan_account_id=scenario.loan_id,
        project_milestone_id=scenario.milestone_id(0),
        settlement_speed="STANDARD_3DAY",
    )
    assert_empty(
        draw,
        "settled_on",
        "released_by_user_id",
        "denial_reason_code",
        "reversal_reason_code",
    )
    assert_common_fields(draw, expected_version=1)


def test_loan_account_opens_promo_active_and_current_with_no_money_on_it(api):
    """Origination puts the account at PROMO_ACTIVE and CURRENT with every money figure at zero.

    PRD: "Like the application, the account carries two independent dimensions: `promo_status`, which begins at `PROMO_ACTIVE` and may reach the terminal states `PROMO_SATISFIED` or `PROMO_EXPIRED_CAPITALIZED`; and `balance_status`, which begins at `CURRENT` and may reach `DELINQUENT` or the terminal states `PAID_OFF` and `CHARGED_OFF`."

    Design: Corner/state_machines/every_entity_lands_in_its_declared_initial_state
    """
    scenario = S.activated_loan(api)

    read = S.read_loan(api, scenario.loan_id)
    assert_fields(
        read,
        application_id=scenario.application_id,
        consumer_id=scenario.consumer_id,
        merchant_id=scenario.merchant_id,
        promo_status="PROMO_ACTIVE",
        balance_status="CURRENT",
        credit_limit_cents=C.CANONICAL_APPROVED_LIMIT_CENTS,
        principal_balance_cents=0,
        capitalized_interest_cents=0,
        accrued_deferred_interest_cents=0,
        waived_interest_cents=0,
        total_funded_cents=0,
        deferred_interest_at_risk_cents=0,
    )
    assert_empty(read, "first_funding_on", "last_payment_on")
    assert_common_fields(read, expected_version=1)


def test_enrollment_project_and_application_open_in_their_declared_states(api):
    """The enrollment, the activated application and the project each open where the contract says.

    PRD: "An enrollment is born `ACTIVE`."

    Design: Corner/state_machines/every_entity_lands_in_its_declared_initial_state
    """
    scenario = S.project(api)

    enrollments, meta = validate_paginated(
        api.list_merchant_promotion_enrollments(scenario.merchant_id, ADMIN_HEADERS)
    )
    assert meta["total_count"] == 1
    assert_fields(enrollments[0], status="ACTIVE")

    # The application is only ever observable from ACTIVATED onward: creation decides it
    # in the same request, and project creation requires it to be ACTIVATED already.
    assert_fields(S.read_application(api, scenario.application_id), decision="ACTIVATED")
    assert_fields(S.read_project(api, scenario.project_id), completion_status="IN_PROGRESS")
    assert_fields(S.read_merchant(api, scenario.merchant_id), enrollment_status="APPROVED")


# ─── state_machines/merchant_draft_to_pending_review_to_approved_valid_transitions ───

def test_submission_takes_the_merchant_from_draft_to_pending_review(api):
    """Submitting for review moves DRAFT to PENDING_REVIEW, stores the attestation and bumps version.

    PRD: "Submission takes `enrollment_status` from `DRAFT → PENDING_REVIEW`, or from `DOCS_REQUIRED → PENDING_REVIEW` when the merchant is answering a documentation request; in the latter case the previously stored `attestation_ref` is overwritten."

    Design: Corner/state_machines/merchant_draft_to_pending_review_to_approved_valid_transitions
    """
    scenario = _draft_merchant_with_trade_rule(api)
    licence = S.file_license(api, scenario.merchant_id)
    S.verify_license(api, scenario.merchant_id, licence["id"])

    submitted = validate_success(
        api.submit_enrollment(
            scenario.merchant_id, F.enrollment_submission_payload(), ADMIN_HEADERS
        )
    )
    assert_fields(
        submitted,
        enrollment_status="PENDING_REVIEW",
        attestation_ref=C.ATTESTATION_REF,
        version=2,
    )
    assert_empty(submitted, "approved_by_user_id", "approved_on")


def test_approval_records_the_deciding_underwriter_and_the_opening_risk_posture(api):
    """Approval stamps who approved and when, and lands an unfunded merchant at STANDARD and grade A.

    PRD: "Approval writes `approved_by_user_id` from the acting operator's identifier and `approved_on` from the logical clock"

    Design: Corner/state_machines/merchant_draft_to_pending_review_to_approved_valid_transitions
    """
    scenario = _pending_review_merchant(api)

    approved = validate_success(
        api.decide_enrollment(
            scenario.merchant_id,
            F.enrollment_decision_payload("APPROVE"),
            UNDERWRITER_HEADERS,
        )
    )
    assert_fields(
        approved,
        enrollment_status="APPROVED",
        approved_by_user_id=UNDERWRITER_ID,
        risk_tier="STANDARD",
        portfolio_grade="A",
        termination_recommended=False,
        version=3,
    )
    # The clock stands at 2026-08-01T00:00:00Z on a freshly booted server.
    assert approved["approved_on"][:10] == C.DEFAULT_CLOCK_DATE


# ─── state_machines/enrollment_approval_enforces_the_whole_month_licence_seasoning_precondition ───

def test_approval_is_refused_when_the_licence_has_four_months_of_coverage_left(api):
    """A licence expiring four whole months out fails the seasoning gate and leaves review untouched.

    PRD: "That covering licence must still have at least `min_license_months` whole months of coverage remaining, counted from the clock date to the exclusive `expires_on` date; a shorter remaining coverage fails with `ERR_LICENSE_COVERAGE_INSUFFICIENT`."

    Design: Corner/state_machines/enrollment_approval_enforces_the_whole_month_licence_seasoning_precondition
    """
    # The ROOFING rule demands six whole months; 2026-08-01 to 2026-12-01 is four.
    scenario = S.approved_merchant(
        api, approve=False, license_={"expires_on": "2026-12-01"}
    )

    validate_error(
        api.decide_enrollment(
            scenario.merchant_id,
            F.enrollment_decision_payload("APPROVE"),
            UNDERWRITER_HEADERS,
        ),
        E.ERR_LICENSE_COVERAGE_INSUFFICIENT,
    )

    unchanged = S.read_merchant(api, scenario.merchant_id)
    assert_fields(unchanged, enrollment_status="PENDING_REVIEW", version=2)
    assert_empty(unchanged, "approved_by_user_id", "approved_on")


def test_approval_succeeds_on_exactly_six_whole_months_of_remaining_coverage(api):
    """A licence expiring exactly six whole months out clears the gate, the boundary being inclusive.

    PRD: "That covering licence must still have at least `min_license_months` whole months of coverage remaining, counted from the clock date to the exclusive `expires_on` date; a shorter remaining coverage fails with `ERR_LICENSE_COVERAGE_INSUFFICIENT`."

    Design: Corner/state_machines/enrollment_approval_enforces_the_whole_month_licence_seasoning_precondition
    """
    # 2026-08-01 to 2027-02-01 is exactly six whole months.
    scenario = S.approved_merchant(
        api, approve=False, license_={"expires_on": "2027-02-01"}
    )

    approved = validate_success(
        api.decide_enrollment(
            scenario.merchant_id,
            F.enrollment_decision_payload("APPROVE"),
            UNDERWRITER_HEADERS,
        )
    )
    assert_fields(
        approved,
        enrollment_status="APPROVED",
        approved_by_user_id=UNDERWRITER_ID,
        version=3,
    )


# ─── state_machines/milestone_verification_side_effects_are_all_applied ───

def test_milestone_verification_stamps_the_milestone_and_lifts_project_headroom(api):
    """Verifying a milestone stamps it, adds its share to the project and recomputes the headroom.

    PRD: "Verification stamps `verified_at`, adds the milestone's `release_pct_bps` into the project's `verified_release_bps`, and recomputes the project's `max_fundable_now_cents`."

    Design: Corner/state_machines/milestone_verification_side_effects_are_all_applied
    """
    scenario = S.project_with_milestones(api, releases=(3000, 4000, 3000), verify=())
    before = S.read_project(api, scenario.project_id)
    assert_fields(before, verified_release_bps=0, max_fundable_now_cents=0)

    S.claim_milestone(api, scenario, 0)
    verified = S.verify_milestone(api, scenario, 0)

    assert_fields(verified, status="VERIFIED", rejection_count=0, is_funded=False)
    assert verified["verified_at"][:10] == C.DEFAULT_CLOCK_DATE

    after = S.read_project(api, scenario.project_id)
    # min(3000 verified, 7000 pre-completion cap) of a 3,500,000 contract = 1,050,000.
    assert_fields(
        after,
        verified_release_bps=3000,
        max_fundable_now_cents=bps_of(C.CANONICAL_PROJECT["contract_amount_cents"], 3000),
    )


def test_verification_below_the_substantial_completion_line_leaves_the_project_in_progress(api):
    """A single 3000 bps verification is far short of 8000, so the project does not bubble up.

    PRD: "If the recomputed `verified_release_bps` has reached eight thousand basis points — four fifths of the contract's release shares signed off — the project itself is bubbled up `IN_PROGRESS → SUBSTANTIALLY_COMPLETE` as a derived consequence, with `max_fundable_now_cents` recomputed."

    Design: Corner/state_machines/milestone_verification_side_effects_are_all_applied
    """
    scenario = S.project_with_milestones(api, releases=(3000, 4000, 3000), verify=())

    S.claim_milestone(api, scenario, 0)
    S.verify_milestone(api, scenario, 0)

    after = S.read_project(api, scenario.project_id)
    assert_fields(
        after,
        verified_release_bps=3000,
        completion_status="IN_PROGRESS",
        settled_funded_cents=0,
        funded_pct_bps=0,
        disputed_amount_cents=0,
    )


# ─── state_machines/reinstate_from_approved_and_decision_from_draft_are_invalid_transitions ───

def test_reinstating_an_approved_merchant_is_an_invalid_transition(api):
    """Reinstatement is reachable only from SUSPENDED, so an APPROVED merchant refuses it.

    PRD: "Merchant enrollment posture: the merchant's `enrollment_status` must admit the requested transition or dependent write — submission only from `DRAFT` or `DOCS_REQUIRED`, an enrollment decision only from `PENDING_REVIEW`, suspension or termination only from `APPROVED` or `SUSPENDED`, reinstatement only from `SUSPENDED`, and `APPROVED` for every funding-side write. Violations are `ERR_INVALID_MERCHANT_STATE`."

    Design: Corner/state_machines/reinstate_from_approved_and_decision_from_draft_are_invalid_transitions
    """
    scenario = S.approved_merchant(api)

    validate_error(
        api.program_action(
            scenario.merchant_id, F.program_action_payload("REINSTATE"), ADMIN_HEADERS
        ),
        E.ERR_INVALID_MERCHANT_STATE,
    )

    unchanged = S.read_merchant(api, scenario.merchant_id)
    assert_fields(unchanged, enrollment_status="APPROVED", version=3)
    assert_empty(unchanged, "suspension_reason_code")


def test_deciding_the_enrollment_of_a_draft_merchant_is_an_invalid_transition(api):
    """An enrollment decision is reachable only from PENDING_REVIEW, so a DRAFT merchant refuses it.

    PRD: "Merchant enrollment posture: the merchant's `enrollment_status` must admit the requested transition or dependent write — submission only from `DRAFT` or `DOCS_REQUIRED`, an enrollment decision only from `PENDING_REVIEW`, suspension or termination only from `APPROVED` or `SUSPENDED`, reinstatement only from `SUSPENDED`, and `APPROVED` for every funding-side write. Violations are `ERR_INVALID_MERCHANT_STATE`."

    Design: Corner/state_machines/reinstate_from_approved_and_decision_from_draft_are_invalid_transitions
    """
    scenario = _draft_merchant_with_trade_rule(api)

    validate_error(
        api.decide_enrollment(
            scenario.merchant_id,
            F.enrollment_decision_payload("APPROVE"),
            UNDERWRITER_HEADERS,
        ),
        E.ERR_INVALID_MERCHANT_STATE,
    )

    unchanged = S.read_merchant(api, scenario.merchant_id)
    assert_fields(unchanged, enrollment_status="DRAFT", version=1)
    assert_empty(unchanged, "approved_by_user_id", "approved_on")


def test_suspending_a_draft_merchant_is_an_invalid_transition(api):
    """Suspension is reachable only from APPROVED or SUSPENDED, so a DRAFT merchant refuses it.

    PRD: "Merchant enrollment posture: the merchant's `enrollment_status` must admit the requested transition or dependent write — submission only from `DRAFT` or `DOCS_REQUIRED`, an enrollment decision only from `PENDING_REVIEW`, suspension or termination only from `APPROVED` or `SUSPENDED`, reinstatement only from `SUSPENDED`, and `APPROVED` for every funding-side write. Violations are `ERR_INVALID_MERCHANT_STATE`."

    Design: Corner/state_machines/reinstate_from_approved_and_decision_from_draft_are_invalid_transitions
    """
    scenario = _draft_merchant_with_trade_rule(api)

    validate_error(
        api.program_action(
            scenario.merchant_id,
            F.program_action_payload("SUSPEND", reason_code="ANALYST_ACTION"),
            ADMIN_HEADERS,
        ),
        E.ERR_INVALID_MERCHANT_STATE,
    )

    unchanged = S.read_merchant(api, scenario.merchant_id)
    assert_fields(unchanged, enrollment_status="DRAFT", version=1)
    assert_empty(unchanged, "suspension_reason_code")


# ─── state_machines/declined_merchant_is_locked_down_in_its_terminal_state ───

def test_a_declined_merchant_can_neither_resubmit_nor_be_decided_again(api):
    """DECLINED is terminal: neither a fresh attestation nor a second decision is admitted.

    PRD: "`DECLINE` sends it `PENDING_REVIEW → DECLINED`, records the note, and is terminal — no further enrollment transition is reachable from `DECLINED`."

    Design: Corner/state_machines/declined_merchant_is_locked_down_in_its_terminal_state
    """
    scenario = _declined_merchant(api)
    assert_fields(scenario.merchant, enrollment_status="DECLINED", version=3)

    validate_error(
        api.submit_enrollment(
            scenario.merchant_id,
            F.enrollment_submission_payload(attestation_ref="ATT-2026-0802"),
            ADMIN_HEADERS,
        ),
        E.ERR_INVALID_MERCHANT_STATE,
    )
    validate_error(
        api.decide_enrollment(
            scenario.merchant_id,
            F.enrollment_decision_payload("APPROVE"),
            UNDERWRITER_HEADERS,
        ),
        E.ERR_INVALID_MERCHANT_STATE,
    )

    unchanged = S.read_merchant(api, scenario.merchant_id)
    assert_fields(
        unchanged,
        enrollment_status="DECLINED",
        attestation_ref=C.ATTESTATION_REF,
        version=3,
    )
    assert_empty(unchanged, "approved_by_user_id", "approved_on")


def test_a_declined_merchant_cannot_be_terminated(api):
    """Termination is reachable only from APPROVED or SUSPENDED, so DECLINED stays where it is.

    PRD: "Termination is the end of the road and is deliberately hard to reach: `APPROVED → TERMINATED` and `SUSPENDED → TERMINATED` both require the merchant's computed `termination_recommended` flag to be true, so an administrator cannot terminate a merchant the portfolio math has not condemned."

    Design: Corner/state_machines/declined_merchant_is_locked_down_in_its_terminal_state
    """
    scenario = _declined_merchant(api)

    validate_error(
        api.program_action(
            scenario.merchant_id,
            F.program_action_payload("TERMINATE", reason_code="FRAUD_CONFIRMED"),
            ADMIN_HEADERS,
        ),
        E.ERR_INVALID_MERCHANT_STATE,
    )

    unchanged = S.read_merchant(api, scenario.merchant_id)
    assert_fields(unchanged, enrollment_status="DECLINED", version=3)
    assert_empty(unchanged, "termination_reason_code")


# ─── state_machines/second_licence_verification_and_second_submission_are_not_idempotent ───

def test_a_second_licence_verification_is_refused_rather_than_replayed(api):
    """A licence already decided refuses a second verification and keeps the first decision intact.

    PRD: "A licence must still be `UNVERIFIED` when a verification decision arrives, otherwise `ERR_LICENSE_ALREADY_DECIDED`. Guards licence verification."

    Design: Corner/state_machines/second_licence_verification_and_second_submission_are_not_idempotent
    """
    merchant = S.register_merchant(api)
    licence = S.file_license(api, merchant["id"])

    first = validate_success(
        api.verify_license(
            merchant["id"],
            licence["id"],
            F.license_verification_payload(
                "VERIFIED", verification_note="State board record matched"
            ),
            UNDERWRITER_HEADERS,
        )
    )
    assert_fields(
        first,
        verification_status="VERIFIED",
        verified_by_user_id=UNDERWRITER_ID,
        verification_note="State board record matched",
        version=2,
    )

    validate_error(
        api.verify_license(
            merchant["id"],
            licence["id"],
            F.license_verification_payload("REJECTED"),
            SECOND_UNDERWRITER_HEADERS,
        ),
        E.ERR_LICENSE_ALREADY_DECIDED,
    )

    rows, _ = validate_paginated(api.list_licenses(merchant["id"], ADMIN_HEADERS))
    assert_fields(
        rows[0],
        id=licence["id"],
        verification_status="VERIFIED",
        verified_by_user_id=UNDERWRITER_ID,
        verification_note="State board record matched",
        version=2,
    )


def test_a_second_submission_from_pending_review_is_refused_and_overwrites_nothing(api):
    """Resubmitting from PENDING_REVIEW is refused, so the stored attestation is not overwritten.

    PRD: "Merchant enrollment posture: the merchant's `enrollment_status` must admit the requested transition or dependent write — submission only from `DRAFT` or `DOCS_REQUIRED`, an enrollment decision only from `PENDING_REVIEW`, suspension or termination only from `APPROVED` or `SUSPENDED`, reinstatement only from `SUSPENDED`, and `APPROVED` for every funding-side write. Violations are `ERR_INVALID_MERCHANT_STATE`."

    Design: Corner/state_machines/second_licence_verification_and_second_submission_are_not_idempotent
    """
    scenario = _pending_review_merchant(api)
    before = S.read_merchant(api, scenario.merchant_id)
    assert_fields(
        before,
        enrollment_status="PENDING_REVIEW",
        attestation_ref=C.ATTESTATION_REF,
        version=2,
    )

    validate_error(
        api.submit_enrollment(
            scenario.merchant_id,
            F.enrollment_submission_payload(attestation_ref="ATT-2026-0802"),
            ADMIN_HEADERS,
        ),
        E.ERR_INVALID_MERCHANT_STATE,
    )

    assert_fields(
        S.read_merchant(api, scenario.merchant_id),
        enrollment_status="PENDING_REVIEW",
        attestation_ref=C.ATTESTATION_REF,
        version=2,
    )


# ─── state_machines/project_completion_status_is_re_derived_from_the_milestone_aggregate ───

def test_project_headroom_is_capped_by_the_pre_completion_release_cap(api):
    """With 7000 bps verified against a 7000 bps cap, the headroom is the whole capped release.

    PRD: "Third, the release cap is the **lower** of the verified share and the completion cap, and the releasable amount is the project's `contract_amount_cents` multiplied by that release cap in basis points, divided by ten thousand and rounded half up."

    Design: Corner/state_machines/project_completion_status_is_re_derived_from_the_milestone_aggregate
    """
    scenario = _project_verified_to_seven_thousand_bps(api)

    read = S.read_project(api, scenario.project_id)
    # min(7000 verified, 7000 pre-completion cap) of a 3,500,000 contract = 2,450,000.
    assert_fields(
        read,
        verified_release_bps=7000,
        completion_status="IN_PROGRESS",
        settled_funded_cents=0,
        max_fundable_now_cents=bps_of(C.CANONICAL_PROJECT["contract_amount_cents"], 7000),
    )


def test_verifying_the_last_milestone_bubbles_the_project_up_but_not_its_headroom(api):
    """Reaching 10000 bps lifts the project to SUBSTANTIALLY_COMPLETE while the cap holds the headroom.

    PRD: "If the recomputed `verified_release_bps` has reached eight thousand basis points — four fifths of the contract's release shares signed off — the project itself is bubbled up `IN_PROGRESS → SUBSTANTIALLY_COMPLETE` as a derived consequence, with `max_fundable_now_cents` recomputed."

    Design: Corner/state_machines/project_completion_status_is_re_derived_from_the_milestone_aggregate
    """
    scenario = _project_verified_to_seven_thousand_bps(api)

    S.verify_milestone(api, scenario, 2)

    read = S.read_project(api, scenario.project_id)
    # The completion cap still bites: min(10000, 7000) leaves the headroom at 2,450,000.
    assert_fields(
        read,
        verified_release_bps=10000,
        completion_status="SUBSTANTIALLY_COMPLETE",
        max_fundable_now_cents=bps_of(C.CANONICAL_PROJECT["contract_amount_cents"], 7000),
    )


def test_rescinding_a_verified_milestone_falls_the_project_back_to_in_progress(api):
    """A homeowner's rescission takes the aggregate back under 8000 bps and the project falls back.

    PRD: "The rescission `VERIFIED → REJECTED` is available only to the owning `Consumer`, requires the milestone's `is_funded` to be false, increments `rejection_count`, and recomputes the project's `verified_release_bps` and `max_fundable_now_cents`."

    Design: Corner/state_machines/project_completion_status_is_re_derived_from_the_milestone_aggregate
    """
    scenario = _project_verified_to_seven_thousand_bps(api)
    S.verify_milestone(api, scenario, 2)

    rescinded = S.verify_milestone(api, scenario, 2, outcome="REJECT")
    assert_fields(rescinded, status="REJECTED", rejection_count=1, is_funded=False)
    assert_empty(rescinded, "verified_at")

    read = S.read_project(api, scenario.project_id)
    assert_fields(
        read,
        verified_release_bps=7000,
        completion_status="IN_PROGRESS",
        max_fundable_now_cents=bps_of(C.CANONICAL_PROJECT["contract_amount_cents"], 7000),
    )


# ─── state_machines/milestone_verification_is_guarded_by_the_consumer_signoff_flag ───

def test_a_servicing_agent_cannot_verify_a_milestone_that_demands_consumer_signoff(api):
    """A ServicingAgent signing off a signoff-required milestone is refused and nothing is released.

    PRD: "`CLAIMED → VERIFIED` requires the milestone to be standing at `CLAIMED`, and when `requires_consumer_signoff` is true the acting party must be the owning `Consumer` — a `ServicingAgent` attempting it is refused with `ERR_CONSUMER_SIGNOFF_REQUIRED`."

    Design: Corner/state_machines/milestone_verification_is_guarded_by_the_consumer_signoff_flag
    """
    scenario = _milestones_with_distinct_signoff_flags(api)

    validate_error(
        api.verify_milestone(
            scenario.project_id,
            scenario.milestone_id(0),
            F.milestone_verification_payload("VERIFY"),
            AGENT_HEADERS,
        ),
        E.ERR_CONSUMER_SIGNOFF_REQUIRED,
    )

    by_id = {m["id"]: m for m in S.read_milestones(api, scenario.project_id)}
    assert_fields(
        by_id[scenario.milestone_id(0)],
        status="CLAIMED",
        requires_consumer_signoff=True,
    )
    assert_fields(S.read_project(api, scenario.project_id), verified_release_bps=0)


def test_a_servicing_agent_may_verify_a_milestone_that_waives_consumer_signoff(api):
    """With the flag false the ServicingAgent signs off, releasing that milestone's share.

    PRD: "It also carries `requires_consumer_signoff`, which defaults to true when omitted: when true, only the owning homeowner may sign the milestone off; when false, a `ServicingAgent` may sign it off as well."

    Design: Corner/state_machines/milestone_verification_is_guarded_by_the_consumer_signoff_flag
    """
    scenario = _milestones_with_distinct_signoff_flags(api)

    verified = validate_success(
        api.verify_milestone(
            scenario.project_id,
            scenario.milestone_id(1),
            F.milestone_verification_payload("VERIFY"),
            AGENT_HEADERS,
        )
    )
    assert_fields(
        verified,
        id=scenario.milestone_id(1),
        status="VERIFIED",
        requires_consumer_signoff=False,
    )
    assert_fields(S.read_project(api, scenario.project_id), verified_release_bps=4000)


def test_the_owning_consumer_may_verify_the_milestone_that_demands_its_signoff(api):
    """The homeowner signs off the guarded milestone, taking the verified aggregate to 7000 bps.

    PRD: "`CLAIMED → VERIFIED` requires the milestone to be standing at `CLAIMED`, and when `requires_consumer_signoff` is true the acting party must be the owning `Consumer` — a `ServicingAgent` attempting it is refused with `ERR_CONSUMER_SIGNOFF_REQUIRED`."

    Design: Corner/state_machines/milestone_verification_is_guarded_by_the_consumer_signoff_flag
    """
    scenario = _milestones_with_distinct_signoff_flags(api)
    validate_success(
        api.verify_milestone(
            scenario.project_id,
            scenario.milestone_id(1),
            F.milestone_verification_payload("VERIFY"),
            AGENT_HEADERS,
        )
    )

    verified = validate_success(
        api.verify_milestone(
            scenario.project_id,
            scenario.milestone_id(0),
            F.milestone_verification_payload("VERIFY"),
            scenario.as_consumer,
        )
    )
    assert_fields(verified, id=scenario.milestone_id(0), status="VERIFIED")

    read = S.read_project(api, scenario.project_id)
    assert_fields(
        read,
        verified_release_bps=7000,
        completion_status="IN_PROGRESS",
        max_fundable_now_cents=bps_of(C.CANONICAL_PROJECT["contract_amount_cents"], 7000),
    )


# ─── state_machines/fraud_confirmation_and_termination_cascade_down_to_non_terminal_children_only ───

def test_an_open_alert_counts_at_half_weight_and_downgrades_without_suspending(api):
    """An open alert weighted 100 scores 50, which downgrades the grade but leaves the merchant approved.

    PRD: "Then halve the **aggregate** open total once — dividing it by two and rounding half up — and add the confirmed total, clamping the result at 100."

    Design: Corner/state_machines/fraud_confirmation_and_termination_cascade_down_to_non_terminal_children_only
    """
    scenario = _merchant_with_approved_and_declined_applications(api)

    alert = validate_success(
        api.create_fraud_alert(
            scenario.merchant_id,
            F.fraud_alert_payload("PHANTOM_PROJECT", 100),
            ANALYST_HEADERS,
        ),
        201,
    )
    assert_fields(
        alert,
        merchant_id=scenario.merchant_id,
        status="OPEN",
        source="ANALYST",
        alert_type="PHANTOM_PROJECT",
        severity_weight=100,
        opened_on=C.DEFAULT_CLOCK_DATE,
    )
    assert_empty(alert, "investigated_by_user_id", "investigation_note")

    merchant = S.read_merchant(api, scenario.merchant_id)
    assert_fields(
        merchant,
        phantom_risk_score=round_half_up(100, 2),  # 50
        enrollment_status="APPROVED",
        # No loan accounts exist, so both rate figures are zero and row C is the first
        # whose three conditions all hold at a phantom score of 50.
        dispute_rate_bps=0,
        delinquency_rate_bps=0,
        portfolio_grade="C",
        termination_recommended=False,
    )


def test_confirming_the_alert_suspends_the_merchant_and_its_enrollment_only(api):
    """Confirmation takes the score to 100, suspends the merchant and its enrollment, and stops there.

    PRD: "`OPEN → CONFIRMED` sets off three hops: first the merchant's `phantom_risk_score` is recomputed with this alert now counting at its full `severity_weight` rather than half; caused by that, `risk_tier`, `portfolio_grade` and `termination_recommended` are recomputed, and if the recomputed `phantom_risk_score` has reached 60 while the merchant is `APPROVED`, the merchant moves `APPROVED → SUSPENDED` with `suspension_reason_code` recorded as `FRAUD_CONFIRMED`; and caused by that suspension, every promotion enrollment of that merchant standing at `ACTIVE` moves to `SUSPENDED` and every funding draw standing at `REQUESTED` moves to `DENIED`."

    Design: Corner/state_machines/fraud_confirmation_and_termination_cascade_down_to_non_terminal_children_only
    """
    scenario = _merchant_with_approved_and_declined_applications(api)
    alert = validate_success(
        api.create_fraud_alert(
            scenario.merchant_id,
            F.fraud_alert_payload("PHANTOM_PROJECT", 100),
            ANALYST_HEADERS,
        ),
        201,
    )

    validate_success(
        api.investigate_fraud_alert(
            scenario.merchant_id,
            alert["id"],
            F.investigation_payload("CONFIRMED"),
            ANALYST_HEADERS,
        )
    )

    merchant = S.read_merchant(api, scenario.merchant_id)
    assert_fields(
        merchant,
        phantom_risk_score=100,
        enrollment_status="SUSPENDED",
        suspension_reason_code="FRAUD_CONFIRMED",
        portfolio_grade="D",
        termination_recommended=True,
    )

    enrollments, _ = validate_paginated(
        api.list_merchant_promotion_enrollments(scenario.merchant_id, ADMIN_HEADERS)
    )
    assert_fields(enrollments[0], status="SUSPENDED")

    # Suspension reaches enrollments and pending draws; it never touches applications.
    assert_fields(S.read_application(api, scenario.application_id), decision="APPROVED")
    assert_fields(
        S.read_application(api, scenario.declined_application["id"]), decision="DECLINED"
    )


def test_termination_revokes_the_live_application_and_spares_the_declined_one(api):
    """Termination revokes the approved offer and terminates the enrollment, leaving the declined offer alone.

    PRD: "Both paths record `termination_reason_code` and run an identical three-way cascade: every promotion enrollment of the merchant standing at `ACTIVE` or `SUSPENDED` becomes `TERMINATED`; every funding draw standing at `REQUESTED` becomes `DENIED` with `denial_reason_code` recorded as `MERCHANT_TERMINATED`; and every credit application of that merchant whose decision is `PENDING`, `APPROVED` or `COUNTER_OFFERED` becomes `REVOKED`, with `MERCHANT_TERMINATED` appended to its `decision_reason_codes`."

    Design: Corner/state_machines/fraud_confirmation_and_termination_cascade_down_to_non_terminal_children_only
    """
    scenario = _merchant_with_approved_and_declined_applications(api)
    alert = validate_success(
        api.create_fraud_alert(
            scenario.merchant_id,
            F.fraud_alert_payload("PHANTOM_PROJECT", 100),
            ANALYST_HEADERS,
        ),
        201,
    )
    validate_success(
        api.investigate_fraud_alert(
            scenario.merchant_id, alert["id"],
            F.investigation_payload("CONFIRMED"), ANALYST_HEADERS,
        )
    )

    terminated = validate_success(
        api.program_action(
            scenario.merchant_id,
            F.program_action_payload("TERMINATE", reason_code="FRAUD_CONFIRMED"),
            ADMIN_HEADERS,
        )
    )
    assert_fields(
        terminated,
        enrollment_status="TERMINATED",
        termination_reason_code="FRAUD_CONFIRMED",
    )

    enrollments, _ = validate_paginated(
        api.list_merchant_promotion_enrollments(scenario.merchant_id, ADMIN_HEADERS)
    )
    assert_fields(enrollments[0], status="TERMINATED")

    revoked = S.read_application(api, scenario.application_id)
    assert_fields(revoked, decision="REVOKED")
    assert_reason_codes(revoked, "WITHIN_LIMIT", "MERCHANT_TERMINATED")

    # DECLINED is terminal on the decision dimension, so the cascade passes it by.
    spared = S.read_application(api, scenario.declined_application["id"])
    assert_fields(spared, decision="DECLINED", approved_limit_cents=0)
    assert_reason_codes(spared, "FICO_BELOW_FLOOR")


# ─── state_machines/suspension_denies_only_the_requested_draw_and_reinstatement_does_not_undo_it ───

def test_suspension_denies_the_pending_draw_and_leaves_the_settled_one_intact(api):
    """Suspension denies the queued draw with MERCHANT_SUSPENDED and rewrites nothing on the settled one.

    PRD: "Suspension cascades twice: every promotion enrollment of that merchant standing at `ACTIVE` moves to `SUSPENDED`, and every funding draw of that merchant standing at `REQUESTED` moves to `DENIED` with `denial_reason_code` recorded as `MERCHANT_SUSPENDED`."

    Design: Corner/state_machines/suspension_denies_only_the_requested_draw_and_reinstatement_does_not_undo_it
    """
    scenario = _settled_draw_and_pending_draw(api)
    settled_id, pending_id = ids_of(scenario.draws)

    validate_success(
        api.program_action(
            scenario.merchant_id,
            F.program_action_payload("SUSPEND", reason_code="ANALYST_ACTION"),
            ADMIN_HEADERS,
        )
    )

    denied = S.read_draw(api, pending_id)
    assert_fields(
        denied,
        status="DENIED",
        denial_reason_code="MERCHANT_SUSPENDED",
        funded_amount_cents=1400000,
    )
    assert_empty(
        denied,
        "settled_on",
        "released_by_user_id",
        "merchant_discount_cents",
        "holdback_withheld_cents",
        "net_settlement_cents",
    )

    # 1,050,000 * 449 / 10000 = 47,145 discount; holdback is min(52,500, 42,000, 157,500).
    still_settled = S.read_draw(api, settled_id)
    assert_fields(
        still_settled,
        status="SETTLED",
        funded_amount_cents=1050000,
        effective_discount_bps=C.NEGOTIATED_DISCOUNT_BPS,
        volume_tier_credit_bps=0,
        merchant_discount_cents=bps_of(1050000, C.NEGOTIATED_DISCOUNT_BPS),
        holdback_withheld_cents=42000,
        net_settlement_cents=1050000 - 47145 - 42000,  # 960,855
        settled_on=C.DEFAULT_CLOCK_DATE,
    )


def test_suspension_cascades_to_the_enrollment_and_moves_no_money(api):
    """The enrollment follows the merchant into SUSPENDED while every reserve figure stands still.

    PRD: "Principal, reserve, funded volume and every rate figure are left exactly as they were."

    Design: Corner/state_machines/suspension_denies_only_the_requested_draw_and_reinstatement_does_not_undo_it
    """
    scenario = _settled_draw_and_pending_draw(api)

    validate_success(
        api.program_action(
            scenario.merchant_id,
            F.program_action_payload("SUSPEND", reason_code="ANALYST_ACTION"),
            ADMIN_HEADERS,
        )
    )

    merchant = S.read_merchant(api, scenario.merchant_id)
    assert_fields(
        merchant,
        enrollment_status="SUSPENDED",
        suspension_reason_code="ANALYST_ACTION",
        funded_volume_cents=1050000,
        holdback_reserve_cents=42000,
        holdback_target_cents=42000,
        reserve_coverage_bps=10000,
    )

    enrollments, _ = validate_paginated(
        api.list_merchant_promotion_enrollments(scenario.merchant_id, ADMIN_HEADERS)
    )
    assert_fields(enrollments[0], status="SUSPENDED")

    # The denial gave the reserved headroom back: 2,450,000 - 1,050,000 settled - 0 pending.
    assert_fields(
        S.read_project(api, scenario.project_id),
        settled_funded_cents=1050000,
        max_fundable_now_cents=1400000,
    )


def test_reinstatement_restores_the_enrollment_but_leaves_the_denied_draw_denied(api):
    """Reinstatement clears the suspension and revives the enrollment; the denied draw stays denied.

    PRD: "Reinstatement clears `suspension_reason_code`, returns every `SUSPENDED` promotion enrollment of that merchant to `ACTIVE`, and increments `version`."

    Design: Corner/state_machines/suspension_denies_only_the_requested_draw_and_reinstatement_does_not_undo_it
    """
    scenario = _settled_draw_and_pending_draw(api)
    pending_id = ids_of(scenario.draws)[1]
    validate_success(
        api.program_action(
            scenario.merchant_id,
            F.program_action_payload("SUSPEND", reason_code="ANALYST_ACTION"),
            ADMIN_HEADERS,
        )
    )

    reinstated = validate_success(
        api.program_action(
            scenario.merchant_id, F.program_action_payload("REINSTATE"), ADMIN_HEADERS
        )
    )
    assert_fields(reinstated, enrollment_status="APPROVED")
    assert_empty(reinstated, "suspension_reason_code")

    enrollments, _ = validate_paginated(
        api.list_merchant_promotion_enrollments(scenario.merchant_id, ADMIN_HEADERS)
    )
    assert_fields(enrollments[0], status="ACTIVE")

    # DENIED is terminal, so the draw the suspension killed is not resurrected.
    assert_fields(
        S.read_draw(api, pending_id),
        status="DENIED",
        denial_reason_code="MERCHANT_SUSPENDED",
    )
