"""Exact edges: the boundary value itself, and the value one unit past it.

Each pair below probes a single inclusive comparison from both sides — one cent
under and one cent over a headroom, one cent either side of a rounded ratio, one
cent either side of a cross-multiplied product — plus the empty-collection edge
where a rate has no denominator to divide by at all.
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import api_errors as E
from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as S
from test_helpers.assertions import assert_fields, round_half_up
from test_helpers.test_users import ADMIN_HEADERS, ANALYST_HEADERS, UNDERWRITER_HEADERS

# One VERIFIED milestone releasing 3000 bps of a 3500000 contract, with the
# completion cap at 7000 bps: the release cap is min(3000, 7000) == 3000 and the
# headroom is round_half_up(3500000 * 3000 / 10000) == 1050000.
SINGLE_MILESTONE_BPS = 3000
HEADROOM_CENTS = 1050000
ONE_CENT_OVER_HEADROOM_CENTS = 1050001

# FICO 742 sits in the 700-759 band: income factor 4500 bps, tier cap 5000000.
# The ceiling is min(round_half_up(9600000 * 4500 / 10000), 5000000) == 4320000.
CREDIT_CEILING_CENTS = C.CANONICAL_APPROVED_LIMIT_CENTS
# 4320479 * 10000 / 9600000 == 4500.4989...  -> 4500, which passes on `<=`.
TICKET_AT_DTI_CEILING_CENTS = 4320479
# 4320480 * 10000 / 9600000 == 4500.5 exactly -> 4501 under round_half_up.
TICKET_OVER_DTI_CEILING_CENTS = 4320480

# The pre-completion detector's two products for a 3500000 contract at 7000 bps.
CONTRACT_CENTS = C.CANONICAL_TICKET_CENTS
PRE_COMPLETION_CAP_BPS = 7000
DETECTOR_LIMIT_PRODUCT = PRE_COMPLETION_CAP_BPS * CONTRACT_CENTS
FIRST_DRAW_CENTS = 1050000
SECOND_DRAW_CENTS = 1399999
BELOW_THRESHOLD_CENTS = 2449999
AT_THRESHOLD_CENTS = 2450000
FINAL_CENT = 1
SYSTEM_ALERT_WEIGHT = 40


def _build_single_milestone_headroom(api):
    """A project with exactly one VERIFIED milestone and nothing drawn against it."""
    scenario = S.project_with_milestones(api, releases=(SINGLE_MILESTONE_BPS,), verify=(0,))
    assert_fields(
        scenario.project,
        verified_release_bps=SINGLE_MILESTONE_BPS,
        completion_status="IN_PROGRESS",
        max_fundable_now_cents=HEADROOM_CENTS,
    )
    return scenario


def _attempt_draw(api, scenario, amount_cents, milestone_index=0):
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


def _build_point_of_sale_book(api):
    """An enrolled merchant and a registered homeowner, with no application yet."""
    scenario = S.enrolled_merchant(api)
    scenario.consumer = S.register_consumer(api, scenario.merchant_id)
    return scenario


def _file_application(api, scenario, ticket_cents):
    """File one point-of-sale application and return the decided row."""
    return get_success_data(
        api.create_credit_application(
            F.credit_application_payload(
                scenario.merchant_id,
                scenario.consumer_id,
                scenario.plan_id,
                project_amount_cents=ticket_cents,
            ),
            scenario.as_merchant,
        )
    )


def _build_detector_book(api):
    """Settle a project's funding to one cent below the pre-completion threshold.

    All three milestones end `VERIFIED`, so the release cap stays pinned at the
    trade rule's 7000 basis points and exactly one cent of headroom is left.
    """
    scenario = S.project_with_milestones(api, releases=(3000, 4000, 3000), verify=(0,))
    S.request_draw(api, scenario, FIRST_DRAW_CENTS, 0)
    S.settle_draw(api, scenario)
    S.claim_milestone(api, scenario, 1)
    S.verify_milestone(api, scenario, 1)
    S.request_draw(api, scenario, SECOND_DRAW_CENTS, 1)
    S.settle_draw(api, scenario)
    S.claim_milestone(api, scenario, 2)
    S.verify_milestone(api, scenario, 2)
    scenario.project = S.read_project(api, scenario.project_id)
    assert_fields(scenario.project, settled_funded_cents=BELOW_THRESHOLD_CENTS)
    return scenario


def _settle_final_cent(api, scenario):
    """Draw and settle the one cent that makes the detector's two products equal."""
    final_draw = S.request_draw(api, scenario, FINAL_CENT, 2)
    settled = S.settle_draw(api, scenario, final_draw["id"])
    scenario.project = S.read_project(api, scenario.project_id)
    return settled


# ─── Staged-funding headroom, to the cent ─────────────────────────────

def test_one_cent_above_the_headroom_is_refused(api):
    """A draw for one cent more than the verified work supports is refused.

    PRD: "The boundary is inclusive: a draw that exactly exhausts the headroom settles, and one cent more is refused with `ERR_STAGED_FUNDING_LIMIT_EXCEEDED`."

    Design: Difficulty/boundary_precision_check/staged_funding_headroom_exact_exhaustion_boundary
    """
    scenario = _build_single_milestone_headroom(api)
    assert ONE_CENT_OVER_HEADROOM_CENTS == HEADROOM_CENTS + 1

    response = _attempt_draw(api, scenario, ONE_CENT_OVER_HEADROOM_CENTS)

    validate_error(response, E.ERR_STAGED_FUNDING_LIMIT_EXCEEDED)
    _draws, meta = validate_paginated(
        api.list_funding_draws(ADMIN_HEADERS, {"loan_account_id": scenario.loan_id})
    )
    assert meta["total_count"] == 0, "The refused request created no draw"


def test_a_draw_for_exactly_the_headroom_is_accepted(api):
    """A draw for the headroom to the cent is created and freezes its funded amount.

    PRD: "A created draw stands at `status` `REQUESTED`, and its `funded_amount_cents` is frozen at that moment as a copy of `requested_amount_cents`; nothing later changes it."

    Design: Difficulty/boundary_precision_check/staged_funding_headroom_exact_exhaustion_boundary
    """
    scenario = _build_single_milestone_headroom(api)
    # round_half_up(3500000 * 3000 / 10000) == 1050000, nothing settled or pending.
    assert HEADROOM_CENTS == round_half_up(
        C.CANONICAL_TICKET_CENTS * SINGLE_MILESTONE_BPS, 10000
    )

    response = api.create_funding_draw(
        F.funding_draw_payload(
            scenario.loan_id,
            scenario.milestone_id(0),
            HEADROOM_CENTS,
            S.loan_version(api, scenario.loan_id),
            "STANDARD_3DAY",
        ),
        scenario.as_merchant,
    )

    draw = validate_success(response, 201)
    assert_fields(
        draw,
        status="REQUESTED",
        requested_amount_cents=HEADROOM_CENTS,
        funded_amount_cents=HEADROOM_CENTS,
    )


def test_the_exact_draw_reserves_the_whole_headroom(api):
    """The accepted boundary draw leaves no headroom behind while it stands REQUESTED.

    PRD: "Pending draws therefore reserve headroom: a merchant cannot queue two draws that together exceed what the verified work supports."

    Design: Difficulty/boundary_precision_check/staged_funding_headroom_exact_exhaustion_boundary
    """
    scenario = _build_single_milestone_headroom(api)
    validate_error(
        _attempt_draw(api, scenario, ONE_CENT_OVER_HEADROOM_CENTS),
        E.ERR_STAGED_FUNDING_LIMIT_EXCEEDED,
    )

    S.request_draw(api, scenario, HEADROOM_CENTS, 0)

    assert_fields(S.read_project(api, scenario.project_id), max_fundable_now_cents=0)
    _draws, meta = validate_paginated(
        api.list_funding_draws(ADMIN_HEADERS, {"loan_account_id": scenario.loan_id})
    )
    assert meta["total_count"] == 1, "Only the accepted request wrote a row"


# ─── The debt-to-income ceiling, to the basis point ───────────────────

def test_a_ratio_rounding_to_exactly_the_ceiling_passes_the_dti_gate(api):
    """A ticket whose ratio rounds to exactly the ceiling clears the gate and is counter-offered.

    PRD: "A ratio of exactly four thousand five hundred passes."

    Design: Difficulty/boundary_precision_check/acceptance_dti_ceiling_round_half_up_boundary
    """
    scenario = _build_point_of_sale_book(api)
    # round_half_up(4320479 * 10000 / 9600000) == 4500, the inclusive ceiling.
    expected_bps = round_half_up(
        TICKET_AT_DTI_CEILING_CENTS * 10000, C.CANONICAL_CONSUMER["annual_income_cents"]
    )
    assert expected_bps == C.DTI_CEILING_BPS

    application = _file_application(api, scenario, TICKET_AT_DTI_CEILING_CENTS)

    assert_fields(
        application,
        decision_dti_bps=C.DTI_CEILING_BPS,
        decision="COUNTER_OFFERED",
        approved_limit_cents=CREDIT_CEILING_CENTS,
        decision_reason_codes=["LIMIT_BELOW_TICKET"],
    )


def test_one_cent_more_rounds_the_ratio_over_the_ceiling_and_declines(api):
    """One cent more rounds the ratio up past the ceiling and declines the application.

    PRD: "If that figure is strictly greater than four thousand five hundred basis points, the application is declined: `decision` becomes `DECLINED`, `approved_limit_cents` stays at zero and `decision_reason_codes` is written as the single code `DTI_ABOVE_CEILING`."

    Design: Difficulty/boundary_precision_check/acceptance_dti_ceiling_round_half_up_boundary
    """
    scenario = _build_point_of_sale_book(api)
    assert TICKET_OVER_DTI_CEILING_CENTS == TICKET_AT_DTI_CEILING_CENTS + 1
    # 4320480 * 10000 / 9600000 is exactly 4500.5, which rounds half up to 4501.
    expected_bps = round_half_up(
        TICKET_OVER_DTI_CEILING_CENTS * 10000, C.CANONICAL_CONSUMER["annual_income_cents"]
    )
    assert expected_bps == C.DTI_CEILING_BPS + 1

    application = _file_application(api, scenario, TICKET_OVER_DTI_CEILING_CENTS)

    assert_fields(
        application,
        decision_dti_bps=expected_bps,
        decision="DECLINED",
        approved_limit_cents=0,
        decision_reason_codes=["DTI_ABOVE_CEILING"],
    )


def test_a_declined_ratio_is_never_reported_as_a_limit_failure(api):
    """The oversized ticket is reported as unaffordable rather than as over the credit line.

    PRD: "A debt-to-income failure is never counter-offered — the program does not negotiate with an unaffordable ratio — and no later step runs."

    Design: Difficulty/boundary_precision_check/acceptance_dti_ceiling_round_half_up_boundary
    """
    scenario = _build_point_of_sale_book(api)
    at_ceiling = _file_application(api, scenario, TICKET_AT_DTI_CEILING_CENTS)

    over_ceiling = _file_application(api, scenario, TICKET_OVER_DTI_CEILING_CENTS)

    # Both tickets exceed the same 4320000 credit ceiling, so only the ordering of
    # the two steps decides which reason each application is given.
    assert TICKET_AT_DTI_CEILING_CENTS > CREDIT_CEILING_CENTS
    assert over_ceiling["decision_reason_codes"] == ["DTI_ABOVE_CEILING"]
    assert "LIMIT_BELOW_TICKET" not in over_ceiling["decision_reason_codes"]
    assert at_ceiling["decision_reason_codes"] == ["LIMIT_BELOW_TICKET"]
    for application in (at_ceiling, over_ceiling):
        assert_fields(application, disclosure_status="NOT_SENT")
    # Fourteen days after the 2026-08-01T00:00:00Z decision instant.
    assert at_ceiling["offer_expires_at"].startswith("2026-08-15T00:00:00")


# ─── The empty book: zero denominators and empty collections ──────────

def test_a_merchant_with_no_loan_accounts_reports_both_rates_as_zero(api):
    """With no loan accounts to divide by, both portfolio rates read zero rather than erroring.

    PRD: "When that count is zero, both `dispute_rate_bps` and `delinquency_rate_bps` are zero."

    Design: Difficulty/boundary_precision_check/zero_volume_merchant_empty_set_coverage_and_rate_defaults
    """
    scenario = S.approved_merchant(api)

    merchant = S.read_merchant(api, scenario.merchant_id)

    assert_fields(merchant, dispute_rate_bps=0, delinquency_rate_bps=0)
    _accounts, meta = validate_paginated(
        api.list_loan_accounts(ADMIN_HEADERS, {"merchant_id": scenario.merchant_id})
    )
    assert meta["total_count"] == 0, "The denominator really is empty"


def test_a_zero_reserve_target_reads_as_full_coverage_rather_than_none(api):
    """A merchant with no reserve target is reported as trivially fully covered.

    PRD: "It begins life with `enrollment_status` set to `DRAFT` and with every portfolio and reserve figure at its opening value: `funded_volume_cents`, `holdback_reserve_cents`, `holdback_target_cents`, `settlement_offset_receivable_cents`, `program_write_off_cents`, `dispute_rate_bps`, `delinquency_rate_bps` and `phantom_risk_score` all at zero, `reserve_coverage_bps` at ten thousand, `portfolio_grade` at `A`, `risk_tier` at `STANDARD` and `termination_recommended` false."

    Design: Difficulty/boundary_precision_check/zero_volume_merchant_empty_set_coverage_and_rate_defaults
    """
    scenario = S.approved_merchant(api)

    merchant = S.read_merchant(api, scenario.merchant_id)

    assert_fields(
        merchant,
        holdback_target_cents=0,
        holdback_reserve_cents=0,
        reserve_coverage_bps=C.FULL_COVERAGE_BPS,
        funded_volume_cents=0,
        settlement_offset_receivable_cents=0,
        program_write_off_cents=0,
    )
    assert merchant["reserve_coverage_bps"] != 0, "Zero target is full coverage, not none"


def test_an_unseasoned_merchant_grades_a_but_is_held_at_standard_risk_tier(api):
    """A spotless merchant with no settled draws keeps grade A while its tier stays STANDARD.

    PRD: "A merchant with fewer than five draws standing at `SETTLED` is held at `STANDARD` no matter how clean its grade looks; this is precisely why a brand-new merchant's very first draw is withheld against a four-hundred-basis-point target rather than a two-hundred-basis-point one."

    Design: Difficulty/boundary_precision_check/zero_volume_merchant_empty_set_coverage_and_rate_defaults
    """
    scenario = S.approved_merchant(api)

    merchant = S.read_merchant(api, scenario.merchant_id)

    assert_fields(
        merchant,
        portfolio_grade="A",
        risk_tier="STANDARD",
        phantom_risk_score=0,
        termination_recommended=False,
    )
    _draws, meta = validate_paginated(
        api.list_funding_draws(
            ADMIN_HEADERS, {"merchant_id": scenario.merchant_id, "status": "SETTLED"}
        )
    )
    assert meta["total_count"] < C.SEASONING_SETTLED_DRAWS, "The merchant is unseasoned"


def test_the_empty_collections_of_a_new_merchant_list_cleanly(api):
    """Both of a new merchant's collections answer with an empty page rather than an error.

    PRD: "List responses carry `limit`, `offset`, `total_count` and `has_more` inside the `meta` object of the envelope, where `total_count` reflects the number of records matching the filter before pagination is applied and `has_more` indicates whether records remain beyond the returned page."

    Design: Difficulty/boundary_precision_check/zero_volume_merchant_empty_set_coverage_and_rate_defaults
    """
    scenario = S.approved_merchant(api)

    alerts, alert_meta = validate_paginated(
        api.list_fraud_alerts(scenario.merchant_id, ANALYST_HEADERS)
    )
    draws, draw_meta = validate_paginated(
        api.list_funding_draws(ADMIN_HEADERS, {"merchant_id": scenario.merchant_id})
    )

    assert alerts == [], "A merchant nobody has flagged has no alerts"
    assert_fields(alert_meta, total_count=0, has_more=False)
    assert draws == [], "A merchant that has drawn nothing has no draws"
    assert_fields(draw_meta, total_count=0, has_more=False)


def test_approval_stamps_the_deciding_underwriter_on_the_merchant(api):
    """The approving underwriter's opaque identifier is recorded on the merchant it approves.

    PRD: "When `X-User-Role` is `ProgramUnderwriter`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server records it — as `verified_by_user_id` on a licence it decides and as `approved_by_user_id` on a merchant it approves — but never compares it to any entity's `id`."

    Design: Difficulty/boundary_precision_check/zero_volume_merchant_empty_set_coverage_and_rate_defaults
    """
    scenario = S.approved_merchant(api)

    merchant = S.read_merchant(api, scenario.merchant_id)

    assert_fields(
        merchant,
        enrollment_status="APPROVED",
        approved_by_user_id=UNDERWRITER_HEADERS["X-User-ID"],
    )
    # The clock has not moved off the suite's opening instant.
    assert merchant["approved_on"].startswith("2026-08-01")


# ─── The pre-completion detector's cross-multiplied edge ──────────────

def test_one_cent_below_the_cross_multiplied_products_mints_no_alert(api):
    """One cent short of the pre-completion cap the detector stays silent.

    PRD: "The test is a cross-multiplied integer comparison with no rounding whatsoever, so its boundary is exact: the project's `settled_funded_cents` multiplied by ten thousand is compared to the trade rule's `max_precompletion_release_bps` multiplied by the project's `contract_amount_cents`, and the detector fires when the former is greater than or equal to the latter while the project's `completion_status` is anything other than `CERTIFIED_COMPLETE`."

    Design: Difficulty/boundary_precision_check/pre_completion_release_alert_exact_cross_multiplied_boundary
    """
    scenario = _build_detector_book(api)
    # 2449999 * 10000 == 24499990000 < 7000 * 3500000 == 24500000000.
    assert BELOW_THRESHOLD_CENTS * 10000 < DETECTOR_LIMIT_PRODUCT

    assert_fields(
        scenario.project,
        settled_funded_cents=BELOW_THRESHOLD_CENTS,
        max_fundable_now_cents=1,
    )
    _alerts, meta = validate_paginated(
        api.list_fraud_alerts(scenario.merchant_id, ANALYST_HEADERS)
    )
    assert meta["total_count"] == 0, "The detector has not fired yet"
    assert_fields(S.read_merchant(api, scenario.merchant_id), phantom_risk_score=0)


def test_the_final_cent_makes_the_products_equal_and_mints_a_system_alert(api):
    """Settling the last cent makes the two products exactly equal and fires the detector.

    PRD: "When it fires it mints an alert with `source` `SYSTEM`, `alert_type` `PRE_COMPLETION_FULL_DRAW` and `severity_weight` 40."

    Design: Difficulty/boundary_precision_check/pre_completion_release_alert_exact_cross_multiplied_boundary
    """
    scenario = _build_detector_book(api)

    _settle_final_cent(api, scenario)

    # 2450000 * 10000 == 24500000000 == 7000 * 3500000, so `>=` holds exactly.
    assert AT_THRESHOLD_CENTS * 10000 == DETECTOR_LIMIT_PRODUCT
    assert_fields(scenario.project, settled_funded_cents=AT_THRESHOLD_CENTS)
    alerts, meta = validate_paginated(
        api.list_fraud_alerts(scenario.merchant_id, ANALYST_HEADERS)
    )
    assert meta["total_count"] == 1, "Exactly one system alert stands open for the project"
    assert_fields(
        alerts[0],
        source="SYSTEM",
        alert_type="PRE_COMPLETION_FULL_DRAW",
        severity_weight=SYSTEM_ALERT_WEIGHT,
        status="OPEN",
        opened_on="2026-08-01",
    )


def test_the_open_system_alert_scores_half_its_weight_and_holds_grade_a(api):
    """The one open system alert counts for half its weight, which grade A still tolerates.

    PRD: "Row `A` requires `dispute_rate_bps` no greater than 200, `delinquency_rate_bps` no greater than 300 and `phantom_risk_score` no greater than 20."

    Design: Difficulty/boundary_precision_check/pre_completion_release_alert_exact_cross_multiplied_boundary
    """
    scenario = _build_detector_book(api)

    _settle_final_cent(api, scenario)

    # No confirmed alerts, so the score is round_half_up(40 / 2) == 20, clamped at 100.
    expected_score = min(100, round_half_up(SYSTEM_ALERT_WEIGHT, 2))
    assert expected_score == 20
    assert_fields(
        S.read_merchant(api, scenario.merchant_id),
        phantom_risk_score=expected_score,
        portfolio_grade="A",
        enrollment_status="APPROVED",
        termination_recommended=False,
    )


def test_the_final_cent_exhausts_the_pre_completion_headroom(api):
    """Funding the project to its pre-completion cap leaves no headroom and seventy percent funded.

    PRD: "The project's `funded_pct_bps` is at all times the project's `settled_funded_cents` multiplied by ten thousand, divided by its `contract_amount_cents` and rounded half up."

    Design: Difficulty/boundary_precision_check/pre_completion_release_alert_exact_cross_multiplied_boundary
    """
    scenario = _build_detector_book(api)

    _settle_final_cent(api, scenario)

    # round_half_up(2450000 * 10000 / 3500000) == 7000, the release cap itself.
    expected_pct = round_half_up(AT_THRESHOLD_CENTS * 10000, CONTRACT_CENTS)
    assert expected_pct == PRE_COMPLETION_CAP_BPS
    assert_fields(
        scenario.project,
        funded_pct_bps=expected_pct,
        completion_status="SUBSTANTIALLY_COMPLETE",
        max_fundable_now_cents=0,
    )
