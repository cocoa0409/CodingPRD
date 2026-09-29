"""The seven-step revenue waterfall, floor-then-residual dairy shares and the
covenant posture that gates payment."""
from test_helpers import (
    ADMIN,
    FINANCE_A,
    FINANCE_B,
    USER_FINANCE_A,
    approve_statement,
    create_statement,
    read_facility,
    set_clock,
    setup_two_dairy_issued_batch,
    setup_two_dairy_plant,
    validate_error,
    validate_success,
)


def test_01_dairy_shares_floor_each_line_then_hand_out_the_residual_cent(api):
    """A 610,194.03-cent pool splits into two floored lines plus one residual cent.

    PRD: "One cent is handed to each of the first lines in the residual pool, walking the same ordering — `committed_tonnes_per_day` descending, then `created_at` ascending — so `residual_cents` is 1 for the first as many lines as the residual pool holds and 0 for every line thereafter."

    Design: Difficulty/combinatorial_formula/cf_dairy_share_floor_per_line_then_residual_cent_by_committed_tonnage
    """
    plant = setup_two_dairy_issued_batch()
    assert plant["batch"]["credit_value_cents"] == 269027

    statement = create_statement(
        plant["facility"]["id"],
        gas_revenue_cents=1_736_376,
        period_start_date="2026-08-01",
        period_end_date="2026-08-31",
    )
    assert statement["credit_revenue_cents"] == 269027
    assert statement["net_distributable_cents"] == 1406289

    lines = statement["share_lines"]
    assert len(lines) == 2
    assert lines[0]["agreement_id"] == plant["agreement_one"]["id"]
    assert lines[0]["floor_cents"] == 309383
    assert lines[0]["residual_cents"] == 1
    assert lines[0]["share_cents"] == 309384
    assert lines[1]["agreement_id"] == plant["agreement_two"]["id"]
    assert lines[1]["floor_cents"] == 300810
    assert lines[1]["residual_cents"] == 0
    assert lines[1]["share_cents"] == 300810


def test_02_the_share_pool_creates_no_cent_and_loses_none(api):
    """Total dairy share plus retained cents reconstruct the distributable pool exactly.

    PRD: "`total_dairy_share_cents` is the sum of every line's `share_cents`, and `retained_cents` is `net_distributable_cents` less `total_dairy_share_cents`."

    Design: Difficulty/combinatorial_formula/cf_dairy_share_floor_per_line_then_residual_cent_by_committed_tonnage
    """
    plant = setup_two_dairy_issued_batch()
    statement = create_statement(
        plant["facility"]["id"],
        gas_revenue_cents=1_736_376,
        period_start_date="2026-08-01",
        period_end_date="2026-08-31",
    )
    assert statement["status"] == "DRAFT"
    assert statement["total_dairy_share_cents"] == 610194
    assert statement["retained_cents"] == 796095
    assert (
        statement["total_dairy_share_cents"] + statement["retained_cents"]
        == statement["net_distributable_cents"]
    )
    assert statement["total_dairy_share_cents"] == sum(
        line["share_cents"] for line in statement["share_lines"]
    )


def test_03_the_management_fee_tier_is_selected_from_gross_revenue(api):
    """Gross revenue of 2,600,000 cents buys the top tier even though the post-fee
    figure would sit a tier lower.

    PRD: "Step three selects `management_fee_rate` from `gross_revenue_cents` and never from any post-fee figure: 0.0800 when `gross_revenue_cents` is at most 1,000,000 cents (ten thousand dollars), 0.0650 when it is above that but at most 2,500,000 cents (twenty-five thousand dollars), and 0.0500 above that."

    Design: Difficulty/combinatorial_formula/cf_waterfall_fee_tier_keyed_on_gross_not_on_after_fee
    """
    plant = setup_two_dairy_issued_batch()
    statement = create_statement(
        plant["facility"]["id"],
        gas_revenue_cents=2_330_973,
        period_start_date="2026-08-01",
        period_end_date="2026-08-31",
    )
    assert statement["gross_revenue_cents"] == 2600000
    assert statement["management_fee_rate"] == 0.0500
    assert statement["management_fee_cents"] == 130000
    assert statement["after_fee_cents"] == 2470000
    assert statement["reserve_sweep_cents"] == 617500
    assert statement["net_distributable_cents"] == 1852500


def test_04_a_comfortable_coverage_ratio_keeps_distributions_open(api):
    """The same statement annualises to 1.647 and leaves the facility open.

    PRD: "The facility's `distribution_posture` is then `OPEN` when `dscr_at_close` is greater than or equal to `dscr_minimum` — the boundary is inclusive, so meeting the covenant exactly keeps distributions open."

    Design: Difficulty/combinatorial_formula/cf_waterfall_fee_tier_keyed_on_gross_not_on_after_fee
    """
    plant = setup_two_dairy_issued_batch()
    statement = create_statement(
        plant["facility"]["id"],
        gas_revenue_cents=2_330_973,
        period_start_date="2026-08-01",
        period_end_date="2026-08-31",
    )
    assert statement["dscr_at_close"] == 1.647
    assert statement["total_dairy_share_cents"] == 797550
    assert statement["retained_cents"] == 1054950

    facility = read_facility(plant["facility"]["id"])
    assert facility["distribution_posture"] == "OPEN"


def test_05_approval_is_allowed_while_the_facility_is_merely_restricted(api):
    """A restricted facility can still approve; only locking blocks approval.

    PRD: "It requires that the facility's `distribution_posture` is not `LOCKED`, otherwise `ERR_DISTRIBUTION_LOCKED`, and that `total_dairy_share_cents` is less than or equal to `net_distributable_cents`, otherwise `ERR_SHARE_EXCEEDS_DISTRIBUTABLE`."

    Design: Difficulty/cross_entity_state_dependency/ced_revenue_statement_pay_blocked_by_facility_distribution_posture_restricted
    """
    set_clock("2026-09-01T00:00:00Z")
    plant = setup_two_dairy_plant()
    statement = create_statement(
        plant["facility"]["id"],
        gas_revenue_cents=1_925_134,
        period_start_date="2026-08-01",
        period_end_date="2026-08-31",
    )
    assert statement["dscr_at_close"] == 1.200
    assert statement["net_distributable_cents"] == 1350000

    facility = read_facility(plant["facility"]["id"])
    assert facility["dscr_current"] == 1.200
    assert facility["distribution_posture"] == "RESTRICTED"

    approved = validate_success(
        api.approve_statement(
            statement["id"],
            {"approval_note": "August 2026 distribution approved under covenant watch"},
            FINANCE_A,
        )
    )
    assert approved["status"] == "APPROVED"
    assert approved["approved_by_user_id"] == USER_FINANCE_A


def test_06_payment_above_the_restricted_cap_is_refused_on_a_restricted_facility(api):
    """A 1,350,000-cent pool exceeds the restricted payment cap, so payment fails.

    PRD: "And the posture must be either `OPEN`, or `RESTRICTED` with `net_distributable_cents` no greater than the restricted payment cap of 1,000,000 cents (ten thousand dollars); a restricted facility attempting to pay out more than that cap is rejected with `ERR_DISTRIBUTION_RESTRICTED`."

    Design: Difficulty/cross_entity_state_dependency/ced_revenue_statement_pay_blocked_by_facility_distribution_posture_restricted
    """
    set_clock("2026-09-01T00:00:00Z")
    plant = setup_two_dairy_plant()
    statement = create_statement(
        plant["facility"]["id"],
        gas_revenue_cents=1_925_134,
        period_start_date="2026-08-01",
        period_end_date="2026-08-31",
    )
    assert statement["management_fee_cents"] == 125134
    assert statement["after_fee_cents"] == 1800000
    assert statement["reserve_sweep_cents"] == 450000
    assert statement["total_dairy_share_cents"] == 585770
    assert statement["retained_cents"] == 764230
    approve_statement(
        statement["id"],
        USER_FINANCE_A,
        "August 2026 distribution approved under covenant watch",
    )

    validate_error(
        api.pay_statement(
            statement["id"], {"payment_reference": "ACH-2026-09-0001"}, FINANCE_B
        ),
        "ERR_DISTRIBUTION_RESTRICTED",
        422,
    )

    unpaid = validate_success(api.get_statement(statement["id"], FINANCE_A))
    assert unpaid["status"] == "APPROVED"
    assert unpaid["paid_by_user_id"] is None
    facility = validate_success(api.get_facility(plant["facility"]["id"], ADMIN))
    assert facility["dairy_share_paid_cents"] == 0
    assert facility["reserve_balance_cents"] == 0
