"""Pinned arithmetic order: cap before penalty, per-component rounding, stamp base."""

from test_helpers import assert_instant_equals
from test_helpers import fixtures as fx

CLOCK_START = "2026-08-01T00:00:00Z"


# ---------------------------------------------------------------------------
# Qualification: cap first, then subtract the no-show penalty
# ---------------------------------------------------------------------------


def _channel_with_a_total_no_show_history():
    """An affinity channel whose only tour was a no-show, so its rate is 1.0000."""
    fx.pin_clock(CLOCK_START)
    gallery = fx.create_gallery()
    fx.create_representatives(gallery["id"], 1)
    channel = fx.create_channel(
        name="In-House Referral Desk",
        channel_code="IN_HOUSE_REFERRAL",
        incentive_gift_value_cents=7500,
        min_age=21,
        min_household_income_cents=5_000_000,
        min_qualification_score=60,
    )
    prospect = fx.create_prospect(
        household_name="Whitfield Household",
        primary_age=55,
        household_income_cents=15_000_000,
        marital_status="MARRIED",
    )
    first = fx.create_booking(
        channel["id"],
        prospect["id"],
        gallery["id"],
        scheduled_start_utc="2026-08-02T09:00:00Z",
    )
    fx.pin_clock("2026-08-02T09:00:00Z")
    fx.mark_no_show(first["id"])
    return {
        "gallery": gallery,
        "channel": channel,
        "prospect": prospect,
        "first_booking": first,
    }


def test_bucket_total_is_capped_at_one_hundred_before_the_penalty_is_removed():
    """A 110-point household on a channel at rate 1.0000 stores 70, never 80.

    The PRD states: "The five buckets are summed, then the sum is **capped at 100
    first**, and only then is the no-show penalty subtracted."

    Design: Difficulty/combinatorial_formula/qualification_cap_before_no_show_penalty_step_order
    """
    scene = _channel_with_a_total_no_show_history()

    channel = fx.read_channel(scene["channel"]["id"])
    assert channel["no_show_count"] == 1
    assert channel["toured_count"] == 0
    assert channel["historical_no_show_rate"] == 1.0
    assert channel["status"] == "ACTIVE"

    scored = fx.create_booking(
        scene["channel"]["id"],
        scene["prospect"]["id"],
        scene["gallery"]["id"],
        scheduled_start_utc="2026-08-03T09:00:00Z",
    )

    assert scored["qualification_penalty_points"] == 30
    assert scored["qualification_score"] == 70
    assert scored["qualification_score"] != 80


def test_penalty_is_the_channel_rate_times_thirty_rounded_to_a_whole_point():
    """The first booking on a clean channel takes no penalty and stores the cap.

    The PRD states: "The penalty is the channel's `historical_no_show_rate`
    multiplied by a weight of 30, rounded half-up to a whole point, and it is
    stored as `qualification_penalty_points`."

    Design: Difficulty/combinatorial_formula/qualification_cap_before_no_show_penalty_step_order
    """
    scene = _channel_with_a_total_no_show_history()

    first = fx.read_booking(scene["first_booking"]["id"])
    assert first["qualification_penalty_points"] == 0
    assert first["qualification_score"] == 100

    scored = fx.create_booking(
        scene["channel"]["id"],
        scene["prospect"]["id"],
        scene["gallery"]["id"],
        scheduled_start_utc="2026-08-03T09:00:00Z",
    )
    assert scored["qualification_penalty_points"] == 30
    assert scored["qualification_score"] == 100 - 30


# ---------------------------------------------------------------------------
# Trade-in equity credit: round each component before summing
# ---------------------------------------------------------------------------


def _upgrade_against_a_delivered_prior_agreement():
    """A delivered all-cash Nevada agreement, then an owner-upgrade tour on it.

    The prior contract is funded at 2026-08-09T00:00:00Z and the upgrade executes
    at 2028-11-06T09:00:00Z, which is 2.2476 years of hold time.
    """
    fx.pin_clock(CLOCK_START)
    scene = fx.setup_executed_agreement(
        check_in_at="2026-08-03T12:00:00Z",
        execute_at="2026-08-03T14:00:00Z",
        issue_incentive_gift=False,
        booking_overrides={"scheduled_start_utc": "2026-08-03T12:00:00Z"},
        agreement_overrides={
            "state_code": "NV",
            "purchase_price_cents": 2_480_000,
            "down_payment_cents": 2_480_000,
            "pos_delivered_at": "2026-08-03T13:00:00Z",
        },
    )
    fx.setup_expired_agreement(scene=scene)
    fx.setup_funded_agreement(scene=scene)
    fx.setup_delivered_agreement(scene=scene)
    scene["prior_agreement"] = scene["agreement"]

    fx.pin_clock("2028-11-06T07:00:00Z")
    upgrade_channel = fx.create_channel(
        name="Owner Upgrade Desk",
        channel_code="OWNER_UPGRADE",
        incentive_gift_value_cents=0,
        min_age=21,
        min_household_income_cents=5_000_000,
        min_qualification_score=60,
    )
    upgrade_booking = fx.create_booking(
        upgrade_channel["id"],
        scene["prospect"]["id"],
        scene["gallery"]["id"],
        scheduled_start_utc="2028-11-06T08:00:00Z",
    )
    fx.pin_clock("2028-11-06T08:00:00Z")
    checked_in = fx.check_in(upgrade_booking["id"], False)
    rep_id = checked_in["assigned_rep_id"]
    presentation = fx.open_presentation(
        upgrade_booking["id"], rep_id, recorded_ack_reference="REC-UP-0001"
    )
    fx.acknowledge_required_disclosures(presentation["id"], rep_id)
    scene["upgrade_presentation"] = fx.review_presentation(presentation["id"], "CLEAR")
    scene["upgrade_booking"] = upgrade_booking
    scene["upgrade_rep_id"] = rep_id
    fx.pin_clock("2028-11-06T09:00:00Z")
    return scene


def _execute_upgrade(scene):
    return fx.execute_agreement(
        scene["upgrade_presentation"]["id"],
        scene["upgrade_rep_id"],
        product_type="RIGHT_TO_USE",
        state_code="FL",
        purchase_price_cents=4_200_000,
        down_payment_cents=316_460,
        pos_delivered_at="2028-11-05T09:00:00Z",
        traded_in_agreement_id=scene["prior_agreement"]["id"],
    )


def test_equity_components_are_each_rounded_before_they_are_summed():
    """The four-component waterfall credits 1035397 cents, not 1035398.

    The PRD states: "Each of the four components is then rounded to a whole cent,
    half-up, *individually*, and only the rounded components are summed; summing
    first and rounding once is explicitly rejected and produces different money."

    Design: Difficulty/combinatorial_formula/trade_in_equity_credit_per_component_rounding_order
    """
    scene = _upgrade_against_a_delivered_prior_agreement()

    prior = fx.read_agreement(scene["prior_agreement"]["id"])
    assert_instant_equals(prior["funded_at"], "2026-08-09T00:00:00Z", "funded_at")
    assert prior["financed_amount_cents"] == 0
    assert prior["escrow_collected_cents"] == 2_480_000

    upgrade = _execute_upgrade(scene)

    assert upgrade["trade_in_equity_credit_cents"] == 1_035_397
    assert upgrade["trade_in_equity_credit_cents"] != 1_035_398

    assert fx.read_agreement(prior["id"])["fulfillment_status"] == "TRADED_IN"


def test_the_credit_propagates_into_every_downstream_financial_field():
    """The one-cent rounding choice moves total due, the stamp and the financed sum.

    The PRD states: "`total_due_cents` is the `purchase_price_cents` less
    `trade_in_equity_credit_cents`, floored at 0."

    Design: Difficulty/combinatorial_formula/trade_in_equity_credit_per_component_rounding_order
    """
    scene = _upgrade_against_a_delivered_prior_agreement()
    upgrade = _execute_upgrade(scene)

    assert upgrade["total_due_cents"] == 3_164_603
    assert upgrade["down_payment_required_cents"] == 316_460
    assert upgrade["base_financed_cents"] == 2_848_143
    assert upgrade["doc_stamp_cents"] == 9_969
    assert upgrade["closing_cost_fee_cents"] == 139_869
    assert upgrade["financed_amount_cents"] == 2_988_012
    assert upgrade["escrow_collected_cents"] == 316_460
    assert_instant_equals(
        upgrade["rescission_deadline_utc"],
        "2028-11-16T23:59:59.999Z",
        "rescission_deadline_utc",
    )

    assert fx.read_prospect(scene["prospect"]["id"])["is_existing_owner"] is True
    assert fx.read_booking(scene["upgrade_booking"]["id"])["qualification_score"] == 100


# ---------------------------------------------------------------------------
# Contract financials: the stamp is assessed on the base, not on its own output
# ---------------------------------------------------------------------------


def test_document_stamp_is_assessed_on_the_base_financed_amount():
    """A base of 2880000 stamps 10080 cents, not the self-referential 10572.

    The PRD states: "The stamp is assessed on `base_financed_cents` and never on
    `financed_amount_cents`."

    Design: Difficulty/combinatorial_formula/agreement_financials_doc_stamp_on_base_financed_pinned_order
    """
    fx.pin_clock(CLOCK_START)
    scene = fx.setup_executed_agreement(issue_incentive_gift=False)
    agreement = scene["agreement"]

    assert agreement["trade_in_equity_credit_cents"] == 0
    assert agreement["total_due_cents"] == 3_200_000
    assert agreement["down_payment_required_cents"] == 320_000
    assert agreement["base_financed_cents"] == 2_880_000
    assert agreement["doc_stamp_cents"] == 10_080
    assert agreement["doc_stamp_cents"] != 10_572


def test_financed_amount_is_the_base_plus_the_closing_fee_without_iterating():
    """Closing costs are 129900 plus the stamp, and the financed total is 3019980.

    The PRD states: "`financed_amount_cents` is 0 when `base_financed_cents` is 0,
    and otherwise is `base_financed_cents` plus `closing_cost_fee_cents`."

    Design: Difficulty/combinatorial_formula/agreement_financials_doc_stamp_on_base_financed_pinned_order
    """
    fx.pin_clock(CLOCK_START)
    scene = fx.setup_executed_agreement(issue_incentive_gift=False)
    agreement = scene["agreement"]

    assert agreement["closing_cost_fee_cents"] == 139_980
    assert agreement["financed_amount_cents"] == 3_019_980
    assert agreement["financed_amount_cents"] != 3_020_472
    assert agreement["escrow_collected_cents"] == 320_000
