"""
Queue A — §1.8 rule ``combinatorial_formula``.

Each instance below pins a formula whose factors could be combined in several
defensible orders, and asserts the one order the PRD names.
"""

from prd_bench_local_runner.testing import get_success_data, validate_success

from test_helpers.assertions import (
    assert_fields,
    assert_iso_equal,
    assert_loan_ledger,
    assert_nulls,
    assert_ratio,
)
from test_helpers.factories import (
    collateral_asset_payload,
    covenant_test_payload,
    draw_disbursement_payload,
)
from test_helpers.fixtures import (
    build_approved_draw,
    build_covenant,
    build_institution,
    chain_through_loan,
)
from test_helpers.test_users import CREDIT_ANALYST, LOAN_SERVICER


def _register_asset(api, institution_id, **overrides):
    return get_success_data(
        api.create_collateral_asset(
            collateral_asset_payload(institution_id, **overrides), CREDIT_ANALYST
        ),
        201,
    )


def _four_assets(api, institution_id):
    asset_a = _register_asset(
        api,
        institution_id,
        description_label="Sanctuary A score 2 seasoned appraisal",
        appraised_value_cents=500000000,
        appraisal_date="2025-06-01T00:00:00Z",
        alternative_use_score=2,
    )
    asset_b = _register_asset(
        api,
        institution_id,
        description_label="Sanctuary B score 5 fresh appraisal",
        appraised_value_cents=500000000,
        appraisal_date="2026-05-01T00:00:00Z",
        alternative_use_score=5,
    )
    asset_c = _register_asset(
        api,
        institution_id,
        asset_type="FELLOWSHIP_HALL",
        description_label="Fellowship hall C score 4 fresh appraisal",
        appraised_value_cents=100000000,
        appraisal_date="2026-05-01T00:00:00Z",
        alternative_use_score=4,
    )
    asset_d = _register_asset(
        api,
        institution_id,
        description_label="Sanctuary D score 5 seasoned appraisal",
        appraised_value_cents=500000000,
        appraisal_date="2025-06-01T00:00:00Z",
        alternative_use_score=5,
    )
    return asset_a, asset_b, asset_c, asset_d


def test_lending_value_takes_the_lower_of_the_score_rate_and_the_type_ceiling(api):
    """
    Four registrations isolate the score tier, the type ceiling and their interaction.

    PRD §3.4: "The alternative-use score proposes a rate — 40 percent at a score of
    1, 50 percent at 2, 60 percent at 3, 70 percent at 4 and 75 percent at 5 — and
    the asset type imposes a ceiling on it: 55 percent for a `SANCTUARY`, 65 percent
    for an `EDUCATION_WING`, 70 percent for a `PARSONAGE`, 50 percent for `LAND`, 60
    percent for a `FELLOWSHIP_HALL` and 0 percent for a `DONOR_RESTRICTED_ENDOWMENT`."

    PRD §3.4: "The effective advance rate is whichever of the two is lower, so a
    readily convertible sanctuary is still capped at 55 percent, and a
    donor-restricted endowment is valued at nothing whatever its score."

    PRD §3.4: "The **lending value** is built in three multiplications, each floored
    to whole cents before the next begins, and the order is pinned."

    Design: Difficulty/combinatorial_formula/collateral_lending_value_nested_min_of_score_tier_and_type_cap
    """
    institution = build_institution(api)
    asset_a, asset_b, asset_c, asset_d = _four_assets(api, institution["id"])

    assert_fields(asset_a, lending_value_cents=225000000, appraisal_age_days=426)
    assert_fields(asset_b, lending_value_cents=275000000, appraisal_age_days=92)
    assert_fields(asset_c, lending_value_cents=60000000, appraisal_age_days=92)
    assert_fields(asset_d, lending_value_cents=247500000, appraisal_age_days=426)


def test_seasoning_discount_and_score_tier_are_separately_observable(api):
    """
    The seasoning factor and the score tier each move the value by their own amount.

    PRD §3.4: "When `appraisal_age_days` is strictly greater than 365 — that is, when
    the appraisal report is more than a year old on the logical clock — the running
    figure is multiplied by 90 percent; at 365 days or fewer no seasoning discount
    applies."

    PRD §3.4: "An asset with no current assignment is valued as though it would take
    a first lien."

    PRD §3.4: "Registration computes `appraisal_age_days` and `lending_value_cents`
    immediately, and leaves `assigned_loan_application_id`, `lien_position`,
    `lien_effective_from` and `lien_effective_to` all null with `lien_history` an
    empty list."

    Design: Difficulty/combinatorial_formula/collateral_lending_value_nested_min_of_score_tier_and_type_cap
    """
    institution = build_institution(api)
    asset_a, asset_b, asset_c, asset_d = _four_assets(api, institution["id"])

    assert asset_b["lending_value_cents"] - asset_a["lending_value_cents"] == 50000000
    assert asset_b["lending_value_cents"] - asset_d["lending_value_cents"] == 27500000

    for asset in (asset_a, asset_b, asset_c, asset_d):
        assert_nulls(
            asset,
            "assigned_loan_application_id",
            "lien_position",
            "lien_effective_from",
            "lien_effective_to",
        )
        assert asset["lien_history"] == [], f"lien_history: got {asset['lien_history']!r}"


def test_covenant_test_numerator_rounds_each_period_to_dollars_before_summing(api):
    """
    Three of the four periods land on a half-cent boundary, so only the pinned order gives 432001.

    PRD §3.5: "Convert that per-period cent figure to whole dollars by dividing by
    100 and rounding half up. Only then sum the four rounded per-period dollar
    figures."

    PRD §3.5: "Summing the four periods in cents and rounding the single total to
    dollars at the end produces a different answer — the two orders differ by a
    dollar on realistic figures — and an implementation must use the
    per-period-then-sum order everywhere this quantity appears: on the institution,
    in the application snapshot, in the covenant test of §3.8 and in the computed
    underwriting summary."

    PRD §3.8: "The numerator is the net-available-for-debt-service figure of §3.5 in
    whole dollars, computed for the institution that borrowed — reached through the
    loan's application — under the basis frozen on the loan as `giving_basis`, with
    the four-period window selected as of the submitted `as_of_date` rather than the
    current clock."

    Design: Difficulty/combinatorial_formula/dscr_numerator_per_period_rounding_before_summation
    """
    chain = chain_through_loan(api)
    covenant = build_covenant(api, chain.loan_id, threshold_ratio=1.2000)

    tested = get_success_data(
        api.run_covenant_test(
            covenant["id"], covenant_test_payload("2026-08-01T00:00:00Z"), LOAN_SERVICER
        )
    )

    assert_fields(
        tested,
        last_test_numerator_dollars=432001,
        last_test_denominator_dollars=360000,
        last_test_result="PASS",
        status="COMPLIANT",
        test_count=1,
        consecutive_fail_count=0,
    )
    assert_ratio(tested["last_test_ratio"], 1.2000, "last_test_ratio")
    assert_iso_equal(tested["last_test_as_of"], "2026-08-01T00:00:00Z", "last_test_as_of")


def test_passing_covenant_test_leaves_the_posture_open_and_agrees_with_the_snapshot(api):
    """
    The same pinned numerator was frozen at submit-underwriting, and a pass moves no posture.

    PRD §3.8: "**Risk posture is derived, never set.** After every covenant creation,
    test, cure and waiver, and after every workout approval, the loan's
    `risk_posture` is recomputed from scratch by evaluating four clauses in exactly
    this order and taking the first that matches."

    PRD §3.5: "The giving base computed under that basis is stored as
    `giving_base_cents`, and the net-available-for-debt-service figure under the same
    basis is stored as `net_available_dollars`."

    PRD §3.8: "The test result is `PASS` when the ratio is greater than or equal to
    the covenant's `threshold_ratio` and `FAIL` otherwise — the boundary is
    inclusive, so a ratio landing exactly on the threshold passes."

    Design: Difficulty/combinatorial_formula/dscr_numerator_per_period_rounding_before_summation
    """
    chain = chain_through_loan(api)
    covenant = build_covenant(api, chain.loan_id, threshold_ratio=1.2000)

    validate_success(
        api.run_covenant_test(
            covenant["id"], covenant_test_payload("2026-08-01T00:00:00Z"), LOAN_SERVICER
        )
    )

    assert_fields(chain.read_loan(), risk_posture="OPEN", servicing_status="PENDING_FIRST_DRAW")
    assert_fields(
        chain.read_application(), net_available_dollars=432001, giving_basis="AUDITED_ONLY"
    )


def _two_approved_draws(api, loan_id):
    first = build_approved_draw(
        api, loan_id, project_phase="FOUNDATION", requested_amount_cents=60000000,
        percent_complete=0.3000,
    )
    second = build_approved_draw(
        api, loan_id, project_phase="SHELL", requested_amount_cents=60000000,
        percent_complete=0.6000,
    )
    return first, second


def test_draw_waterfall_reads_the_retainage_tier_from_the_post_draw_position(api):
    """
    Two identical gross draws net different cash because each draw creates its own tier.

    PRD §3.7: "Step one establishes the completion tier from the **post-draw**
    cumulative position — the tier this very draw creates, not the one it started
    from."

    PRD §3.7: "Add the gross amount to the loan's `disbursed_principal_cents` as it
    stands immediately before this disbursement, multiply that post-draw total by
    10000, divide by the loan's `principal_cents` discarding any remainder, then
    divide by 10000 again to express the result as a fraction floored to four decimal
    places."

    PRD §3.7: "Below a completion fraction of 0.5000 the rate is 10 percent; from
    0.5000 up to but not including 0.9000 it is 5 percent; at 0.9000 and above it is
    0 percent."

    Design: Difficulty/combinatorial_formula/draw_net_disbursement_waterfall_with_post_draw_retainage_tier
    """
    chain = chain_through_loan(api)
    first, second = _two_approved_draws(api, chain.loan_id)

    disbursed_first = get_success_data(
        api.disburse_draw_request(
            first["id"], draw_disbursement_payload(disbursement_date="2026-08-05T00:00:00Z"),
            LOAN_SERVICER,
        )
    )
    disbursed_second = get_success_data(
        api.disburse_draw_request(
            second["id"], draw_disbursement_payload(disbursement_date="2026-08-20T00:00:00Z"),
            LOAN_SERVICER,
        )
    )

    assert_ratio(
        disbursed_first["completion_pct_at_disbursement"], 0.2666, "draw 1 completion_pct"
    )
    assert_fields(
        disbursed_first,
        retainage_cents=6000000,
        interest_reserve_applied_cents=1500000,
        inspection_fee_cents=45000,
        net_disbursed_cents=52455000,
        status="DISBURSED",
    )

    assert_ratio(
        disbursed_second["completion_pct_at_disbursement"], 0.5333, "draw 2 completion_pct"
    )
    assert_fields(
        disbursed_second,
        retainage_cents=3000000,
        interest_reserve_applied_cents=0,
        inspection_fee_cents=45000,
        net_disbursed_cents=56955000,
        status="DISBURSED",
    )

    assert (
        disbursed_second["net_disbursed_cents"] - disbursed_first["net_disbursed_cents"]
        == 4500000
    )
    assert disbursed_first["completion_pct_at_disbursement"] != first["percent_complete"]
    assert disbursed_second["completion_pct_at_disbursement"] != second["percent_complete"]


def test_two_disbursements_leave_the_loan_ledger_conserved(api):
    """
    The interest-reserve sweep, the inspection fee and both retainage tiers reconcile on the loan.

    PRD §3.7: "The first bucket sweeps the interest reserve: it takes whichever is
    smaller of the pool and the loan's `interest_reserve_shortfall_cents`, and that
    amount is stored as `interest_reserve_applied_cents` and removed from the pool."

    PRD §3.7: "On the loan, `reserved_draw_cents` falls by the approved amount
    because the reservation has been consumed; `disbursed_principal_cents` rises by
    the approved amount and `undrawn_commitment_cents` falls by the same amount;
    `outstanding_principal_cents` rises by the approved amount; `retainage_held_cents`
    rises by `retainage_cents`; and `interest_reserve_shortfall_cents` falls by
    `interest_reserve_applied_cents`."

    PRD §3.7: "When this is the first disbursement on the loan — that is, when
    `disbursed_principal_cents` stood at 0 before it — the loan also moves
    `PENDING_FIRST_DRAW → CONSTRUCTION_DRAW` on its servicing dimension."

    Design: Difficulty/combinatorial_formula/draw_net_disbursement_waterfall_with_post_draw_retainage_tier
    """
    chain = chain_through_loan(api)
    first, second = _two_approved_draws(api, chain.loan_id)

    validate_success(
        api.disburse_draw_request(
            first["id"], draw_disbursement_payload(disbursement_date="2026-08-05T00:00:00Z"),
            LOAN_SERVICER,
        )
    )
    validate_success(
        api.disburse_draw_request(
            second["id"], draw_disbursement_payload(disbursement_date="2026-08-20T00:00:00Z"),
            LOAN_SERVICER,
        )
    )

    assert_loan_ledger(
        chain.read_loan(),
        principal_cents=225000000,
        disbursed_principal_cents=120000000,
        undrawn_commitment_cents=105000000,
        cancelled_commitment_cents=0,
        reserved_draw_cents=0,
        retainage_held_cents=9000000,
        retainage_released_cents=0,
        interest_reserve_shortfall_cents=0,
        outstanding_principal_cents=120000000,
        servicing_status="CONSTRUCTION_DRAW",
        risk_posture="OPEN",
    )
