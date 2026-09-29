"""Which error a request that breaks two rules at once is answered with.

Each rule pair below is proved three ways: the higher-priority check firing
alone, the lower-priority check firing alone, and both firing together — where
only the higher-priority error may be observed. The single-fault controls are
what make the ordering falsifiable: without them a suite could not tell a
correct ordering from an implementation that only ever raises one of the two.
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
)
from test_helpers import api_errors as E
from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as S
from test_helpers.assertions import assert_fields
from test_helpers.test_users import ADMIN_HEADERS

# Milestone 1 releases 3000 bps and is left at CLAIMED; milestone 2 releases
# 4000 bps and is carried to VERIFIED.  Only VERIFIED shares release money, so
# the release cap is min(4000, max_precompletion_release_bps 7000) == 4000 and
# the headroom is 3500000 * 4000 / 10000 with nothing funded or pending yet.
VERIFIED_RELEASE_BPS = 4000
HEADROOM_CENTS = 1400000
OVER_HEADROOM_CENTS = 1500000
WITHIN_HEADROOM_CENTS = 100000

# The plan and the ROOFING trade rule both cap the ticket at 5000000.
OVER_TICKET_CENTS = 6000000

# The offer is stamped fourteen days after the decision instant, and the
# decision lands at the suite's opening clock of 2026-08-01T00:00:00Z.
OFFER_EXPIRES_AT_PREFIX = "2026-08-15T00:00:00"
ONE_DAY_LATE = "2026-08-16T00:00:00Z"
ONE_DAY_LATE_PREFIX = "2026-08-16T00:00:00"


def _build_state_versus_fiscal_book(api):
    """A project whose second milestone is VERIFIED and whose first is only CLAIMED."""
    scenario = S.project_with_milestones(api, releases=(3000, 4000), verify=(1,))
    S.claim_milestone(api, scenario, 0)
    scenario.project = S.read_project(api, scenario.project_id)
    assert_fields(
        scenario.project,
        verified_release_bps=VERIFIED_RELEASE_BPS,
        completion_status="IN_PROGRESS",
        max_fundable_now_cents=HEADROOM_CENTS,
    )
    return scenario


def _attempt_draw(api, scenario, milestone_index, amount_cents):
    """Ask for a draw without demanding success, reading the loan version fresh."""
    return api.create_funding_draw(
        F.funding_draw_payload(
            scenario.loan_id,
            scenario.milestone_id(milestone_index),
            amount_cents,
            S.loan_version(api, scenario.loan_id),
            "STANDARD_3DAY",
        ),
        scenario.as_merchant,
    )


def _build_unenrolled_merchant(api):
    """An APPROVED merchant with a registered homeowner but no promotion enrollment."""
    scenario = S.approved_merchant(api)
    scenario.consumer = S.register_consumer(api, scenario.merchant_id)
    return scenario


def _attempt_application(api, scenario, ticket_cents):
    """File a point-of-sale application without demanding success."""
    return api.create_credit_application(
        F.credit_application_payload(
            scenario.merchant_id,
            scenario.consumer_id,
            scenario.plan_id,
            project_amount_cents=ticket_cents,
        ),
        scenario.as_merchant,
    )


def _build_expired_undisclosed_offer(api):
    """An APPROVED application whose offer has lapsed and whose disclosure was never sent."""
    scenario = S.application(api)
    assert_fields(scenario.application, decision="APPROVED", disclosure_status="NOT_SENT")
    # Fourteen days after the 2026-08-01T00:00:00Z decision instant.
    assert scenario.application["offer_expires_at"].startswith(OFFER_EXPIRES_AT_PREFIX)
    S.set_clock(api, ONE_DAY_LATE)
    return scenario


# ─── Milestone state versus staged-funding headroom ───────────────────

def test_over_headroom_draw_on_a_verified_milestone_fails_only_on_the_money(api):
    """With the milestone state clean, an oversized draw is refused for the fiscal reason.

    PRD: "The boundary is inclusive: a draw that exactly exhausts the headroom settles, and one cent more is refused with `ERR_STAGED_FUNDING_LIMIT_EXCEEDED`."

    Design: Difficulty/priority_pair_validation_conflict/milestone_state_beats_staged_funding_limit_on_draw_creation
    """
    scenario = _build_state_versus_fiscal_book(api)
    assert_fields(scenario.milestones[1], status="VERIFIED")

    response = _attempt_draw(api, scenario, 1, OVER_HEADROOM_CENTS)

    validate_error(response, E.ERR_STAGED_FUNDING_LIMIT_EXCEEDED)


def test_within_headroom_draw_on_a_claimed_milestone_fails_only_on_the_state(api):
    """With the money clean, a draw against an unverified milestone is refused for its state.

    PRD: "Violations are `ERR_INVALID_MILESTONE_STATE`, which is also the code raised when a draw names a milestone that is not `VERIFIED`."

    Design: Difficulty/priority_pair_validation_conflict/milestone_state_beats_staged_funding_limit_on_draw_creation
    """
    scenario = _build_state_versus_fiscal_book(api)
    assert_fields(scenario.milestones[0], status="CLAIMED")
    assert WITHIN_HEADROOM_CENTS <= HEADROOM_CENTS, "The fiscal gate is satisfied"

    response = _attempt_draw(api, scenario, 0, WITHIN_HEADROOM_CENTS)

    validate_error(response, E.ERR_INVALID_MILESTONE_STATE)


def test_milestone_state_outranks_the_headroom_gate_when_both_are_broken(api):
    """A draw breaking both rules answers with the state error and never reaches the money.

    PRD: "The first check whose condition is violated wins: the request is rejected with that check's error identifier and status, no later check runs, and no side effect of any kind is written."

    Design: Difficulty/priority_pair_validation_conflict/milestone_state_beats_staged_funding_limit_on_draw_creation
    """
    scenario = _build_state_versus_fiscal_book(api)

    response = _attempt_draw(api, scenario, 0, OVER_HEADROOM_CENTS)

    payload = validate_error(response, E.ERR_INVALID_MILESTONE_STATE)
    assert payload["error_id"] != E.ERR_STAGED_FUNDING_LIMIT_EXCEEDED
    _draws, meta = validate_paginated(
        api.list_funding_draws(ADMIN_HEADERS, {"loan_account_id": scenario.loan_id})
    )
    assert meta["total_count"] == 0, "A rejected request writes no draw"
    assert_fields(
        S.read_project(api, scenario.project_id), max_fundable_now_cents=HEADROOM_CENTS
    )


# ─── Promotion enrollment versus the ticket ceiling ───────────────────

def test_within_cap_application_without_an_enrollment_fails_on_the_enrollment(api):
    """A well-sized ticket sold on an unenrolled plan is refused for the missing enrollment.

    PRD: "At point of sale, the named `promotion_plan_id` must have an enrollment for this merchant whose `status` is `ACTIVE` and whose closed window from `window_start_date` through `window_end_date` contains the clock date, otherwise `ERR_PROMOTION_NOT_ENROLLED`; and the merchant must still hold a licence whose `verification_status` is `VERIFIED` — not one swept to `EXPIRED` — for its own `trade_type` and `state_code`, otherwise `ERR_LICENSE_EXPIRED`."

    Design: Difficulty/priority_pair_validation_conflict/promotion_enrollment_gate_beats_ticket_limit_on_application
    """
    scenario = _build_unenrolled_merchant(api)
    ceiling = min(
        C.DEFERRED_INTEREST_PLAN["max_ticket_cents"],
        C.ROOFING_TRADE_RULE["max_ticket_cents"],
    )
    assert C.CANONICAL_TICKET_CENTS <= ceiling, "The fiscal gate is satisfied"

    response = _attempt_application(api, scenario, C.CANONICAL_TICKET_CENTS)

    validate_error(response, E.ERR_PROMOTION_NOT_ENROLLED)


def test_oversized_application_with_an_enrollment_fails_on_the_ticket_ceiling(api):
    """With the enrollment in place, an oversized ticket is refused for the fiscal reason.

    PRD: "The requested `project_amount_cents` must not exceed the lower of the plan's `max_ticket_cents` and the governing trade rule's `max_ticket_cents`, otherwise `ERR_TICKET_LIMIT_EXCEEDED`."

    Design: Difficulty/priority_pair_validation_conflict/promotion_enrollment_gate_beats_ticket_limit_on_application
    """
    scenario = _build_unenrolled_merchant(api)
    scenario.enrollment = S.enroll_in_promotion(api, scenario.merchant_id, scenario.plan_id)
    assert_fields(scenario.enrollment, status="ACTIVE")
    # 6000000 exceeds min(5000000, 5000000).
    assert OVER_TICKET_CENTS > min(
        C.DEFERRED_INTEREST_PLAN["max_ticket_cents"],
        C.ROOFING_TRADE_RULE["max_ticket_cents"],
    )

    response = _attempt_application(api, scenario, OVER_TICKET_CENTS)

    validate_error(response, E.ERR_TICKET_LIMIT_EXCEEDED)


def test_missing_enrollment_outranks_the_ticket_ceiling_when_both_are_broken(api):
    """An oversized ticket on an unenrolled plan answers with the enrollment error alone.

    PRD: "Within the business bands the ordering runs safety and compliance first, then referential coherence, then structural constraints, then temporal deadlines, then money, because an undisclosed deferred-interest term or an unverified licence is a regulatory finding while a fiscal defect is only money."

    Design: Difficulty/priority_pair_validation_conflict/promotion_enrollment_gate_beats_ticket_limit_on_application
    """
    scenario = _build_unenrolled_merchant(api)

    response = _attempt_application(api, scenario, OVER_TICKET_CENTS)

    payload = validate_error(response, E.ERR_PROMOTION_NOT_ENROLLED)
    assert payload["error_id"] != E.ERR_TICKET_LIMIT_EXCEEDED
    _applications, meta = validate_paginated(
        api.list_credit_applications(ADMIN_HEADERS, {"merchant_id": scenario.merchant_id})
    )
    assert meta["total_count"] == 0, "A rejected application writes no row"


# ─── Disclosure acknowledgement versus the offer deadline ─────────────

def test_lapsed_offer_never_disclosed_answers_with_the_disclosure_error(api):
    """The consumer-protection check outranks the commercial deadline when both are broken.

    PRD: "An offer may only be accepted once `disclosure_status` is `ACKNOWLEDGED`, because the deferred-interest terms must be acknowledged before credit is extended; otherwise `ERR_DISCLOSURE_NOT_ACKNOWLEDGED`."

    Design: Difficulty/priority_pair_validation_conflict/disclosure_acknowledgement_beats_offer_expiry_on_acceptance
    """
    scenario = _build_expired_undisclosed_offer(api)

    response = api.accept_offer(
        scenario.application_id, F.acceptance_payload(), scenario.as_consumer
    )

    payload = validate_error(response, E.ERR_DISCLOSURE_NOT_ACKNOWLEDGED)
    assert payload["error_id"] != E.ERR_OFFER_EXPIRED


def test_disclosure_may_still_be_delivered_and_acknowledged_after_the_offer_lapses(api):
    """The lapsed deadline blocks acceptance only, so the disclosure can still be completed.

    PRD: "The move `NOT_SENT → DELIVERED` requires the application's `decision` to be `APPROVED` or `COUNTER_OFFERED`, and requires the supplied template version to equal the promotion plan's current `disclosure_template_version`; a mismatch is refused with `ERR_DISCLOSURE_TEMPLATE_MISMATCH`."

    Design: Difficulty/priority_pair_validation_conflict/disclosure_acknowledgement_beats_offer_expiry_on_acceptance
    """
    scenario = _build_expired_undisclosed_offer(api)

    delivered = get_success_data(
        api.deliver_disclosure(
            scenario.application_id,
            F.disclosure_delivery_payload(),
            scenario.as_merchant,
        )
    )

    assert_fields(delivered, disclosure_status="DELIVERED", decision="APPROVED")
    assert delivered["disclosure_delivered_at"].startswith(ONE_DAY_LATE_PREFIX)
    acknowledged = get_success_data(
        api.acknowledge_disclosure(
            scenario.application_id,
            F.disclosure_acknowledgement_payload(),
            scenario.as_consumer,
        )
    )
    assert_fields(acknowledged, disclosure_status="ACKNOWLEDGED")


def test_acknowledged_disclosure_leaves_only_the_lapsed_offer_to_refuse_acceptance(api):
    """Once the disclosure is acknowledged the same acceptance is refused for the deadline.

    PRD: "Acceptance must occur at or before `offer_expires_at`, the boundary being inclusive; later is `ERR_OFFER_EXPIRED`."

    Design: Difficulty/priority_pair_validation_conflict/disclosure_acknowledgement_beats_offer_expiry_on_acceptance
    """
    scenario = _build_expired_undisclosed_offer(api)
    get_success_data(
        api.deliver_disclosure(
            scenario.application_id, F.disclosure_delivery_payload(), scenario.as_merchant
        )
    )
    get_success_data(
        api.acknowledge_disclosure(
            scenario.application_id,
            F.disclosure_acknowledgement_payload(),
            scenario.as_consumer,
        )
    )

    response = api.accept_offer(
        scenario.application_id, F.acceptance_payload(), scenario.as_consumer
    )

    validate_error(response, E.ERR_OFFER_EXPIRED)
    # No sweep ran, so the offer is still APPROVED rather than EXPIRED.
    assert_fields(
        S.read_application(api, scenario.application_id),
        decision="APPROVED",
        disclosure_status="ACKNOWLEDGED",
    )
    _accounts, meta = validate_paginated(
        api.list_loan_accounts(ADMIN_HEADERS, {"application_id": scenario.application_id})
    )
    assert meta["total_count"] == 0, "A refused acceptance originates no loan account"
