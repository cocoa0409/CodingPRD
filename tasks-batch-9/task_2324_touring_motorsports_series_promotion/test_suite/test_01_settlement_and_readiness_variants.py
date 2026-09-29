"""The two dual-variant calculations: settlement money and entry readiness.

A settlement is cut once but computed twice. Preparation writes every money field
under the ``PROVISIONAL`` variant; approval re-runs the whole computation under
``FINAL`` over a freshly re-read inclusion set, which is where a sponsor holdback
and an order refunded after preparation change the answer.

An entry's readiness score is likewise computed under two variants. Creation
scores the promised arrival under ``PRE_STAGING``; check-in and every inspection
attempt discard that projection and score realized facts under ``POST_STAGING``.
"""

from __future__ import annotations

from typing import Any, Callable, Dict

import pytest

from test_helpers import (
    ApiClient,
    FINANCE_APPROVER_USER_ID,
    assert_event_settlement,
    assert_profitability_margin,
    assert_readiness_score,
    assert_vehicle_entry,
    make_approve_settlement_payload,
    make_check_in_payload,
    make_refund_payload,
    make_tech_inspection_payload,
    make_vehicle_entry_payload,
    validate_success,
)
from test_helpers import fixtures as helpers

# The design scenario's ATL figures. The tour stop is the canonical Atlanta stop:
# a 3,000,000-cent rental base, a 0.12 revenue share and a 350-cent per-ticket
# facility fee, two tiers of 3,000 seats each and a 854,000-cent safety bill.
_ORDER_A_QTY = 600
_ORDER_B_QTY = 900
_ORDER_B_PIT_PARTY_QTY = 300
_DIGITAL_ALLOCATION_CENTS = 1_200_000

# The entry of the readiness scenario promises a transporter twelve hours before
# the staging window closes and then arrives eight hours late.
_PROMISED_ARRIVAL_UTC = "2026-11-14T09:00:00Z"
_ACTUAL_ARRIVAL_UTC = "2026-11-14T17:00:00Z"


def _atl_stop_with_two_paid_orders(api: ApiClient) -> Dict[str, Any]:
    """The closed ATL stop of the settlement scenario, with both orders settled.

    Two allocations put 2,000,000 cents of marketing in the market, a 600-seat
    group order sits on the PITSIDE tier and a 900-seat order carrying 300 pit
    party heads sits on the UPPER tier. One entry is staged, so the purse counts
    one competitor, and one activation is live but never fulfilled.
    """
    state = helpers.stop_on_sale(api)
    helpers.commit_marketing_allocation(
        api,
        state["stop_id"],
        state["season_id"],
        channel="DIGITAL",
        amount_cents=_DIGITAL_ALLOCATION_CENTS,
    )
    order_a = helpers.place_paid_ticket_order(
        api,
        state["stop_id"],
        state["tier_id"],
        qty=_ORDER_A_QTY,
        is_group=True,
        purchaser_name="Group A",
        purchaser_email="group-a@example.com",
    )
    order_b = helpers.place_paid_ticket_order(
        api,
        state["stop_id"],
        state["second_tier_id"],
        qty=_ORDER_B_QTY,
        pit_party_addon_qty=_ORDER_B_PIT_PARTY_QTY,
        purchaser_name="Walk Up B",
        purchaser_email="walkup-b@example.com",
    )
    state["order_a_id"] = order_a["order_id"]
    state["order_b_id"] = order_b["order_id"]
    helpers.stage_and_close_stop(
        api, state, scheduled_arrival_utc=_PROMISED_ARRIVAL_UTC
    )
    return state


def _prepare_settlement(
    api: ApiClient, stop_id: str, headers: Dict[str, str]
) -> Dict[str, Any]:
    """Cut the stop's settlement, which lands under the provisional variant."""
    return validate_success(
        api.create_settlement(stop_id, headers=headers), expected_status=201
    )


class TestSettlementProvisionalThenFinalVariants:
    """The provisional and final variants of the settlement money computation."""

    def test_provisional_preparation_recognizes_both_paid_orders_and_the_whole_sponsor_fee(
        self,
        api: ApiClient,
        finance_preparer_headers: Dict[str, str],
    ) -> None:
        """PRD §3.9: "Under `PROVISIONAL`, the included orders are those whose `status` is `PAID` as of preparation, and each activation in `ACTIVATED` or `FULFILLED` recognizes its full `fee_cents` with no holdback."

        PRD §3.9: "`rental_due_pre_credit_cents` is then the greater of the booking's `rental_base_cents` and that share component, plus the facility fee total."

        Design: Difficulty/dual_variant_calc/settlement_provisional_then_final_sponsor_holdback_and_refund_dropout
        """
        state = _atl_stop_with_two_paid_orders(api)

        settlement = _prepare_settlement(
            api, state["stop_id"], finance_preparer_headers
        )

        assert_event_settlement(settlement)
        assert settlement["variant"] == "PROVISIONAL"
        assert settlement["state"] == "PREPARED"

        # Both orders are PAID at preparation: 600 x 4750 less the 356,250-cent
        # group discount, plus 900 x 2500 with no discount.
        assert settlement["ticket_revenue_cents"] == 4_743_750
        # Only order B carries pit party heads: 300 x 2450, undiscounted because
        # 300 heads do not match its 900 seats.
        assert settlement["addon_revenue_cents"] == 735_000
        assert settlement["facility_fee_cents"] == 525_000
        # The activation is still ACTIVATED, and the provisional variant applies
        # no holdback to it.
        assert settlement["sponsorship_revenue_cents"] == 1_500_000
        assert settlement["collected_cash_cents"] == 7_503_750

        # The share component is 4,743,750 x 0.12 = 569,250, so the 3,000,000-cent
        # rental base is the greater figure; the facility fee total is added on top.
        assert settlement["rental_due_pre_credit_cents"] == 3_525_000
        assert settlement["coop_credit_pct"] == pytest.approx(0.04, abs=0.01)
        assert settlement["coop_credit_cents"] == 141_000
        assert settlement["venue_due_cents"] == 3_384_000

        assert settlement["net_to_promoter_cents"] == 1_115_750
        assert settlement["profitability_margin_pct"] == pytest.approx(
            14.87, abs=0.01
        )
        assert_profitability_margin(settlement)

    def test_final_approval_drops_the_refunded_order_and_halves_the_activated_sponsor_fee(
        self,
        api: ApiClient,
        finance_preparer_headers: Dict[str, str],
        finance_approver_headers: Dict[str, str],
        ticketing_headers: Dict[str, str],
    ) -> None:
        """PRD §3.9: "Under `FINAL`, the included orders are those whose `status` is `PAID` as of approval — so anything refunded after preparation drops out — and recognition splits: an activation in `FULFILLED` recognizes its full `fee_cents`, while an activation still in `ACTIVATED` recognizes only its `fee_cents` multiplied by 50 percent, rounded half up to whole cents."

        PRD §2.9: "Because the stop became `SETTLED`, the season's `settled_stop_count` increments by one, the settlement's `net_to_promoter_cents` is added to the season's `season_net_cents`, and the season's `version` increments by one."

        Design: Difficulty/dual_variant_calc/settlement_provisional_then_final_sponsor_holdback_and_refund_dropout
        """
        state = _atl_stop_with_two_paid_orders(api)
        settlement = _prepare_settlement(
            api, state["stop_id"], finance_preparer_headers
        )

        validate_success(
            api.refund_ticket_order(
                state["order_b_id"],
                make_refund_payload(reason="purchaser chargeback after preparation"),
                headers=ticketing_headers,
            )
        )
        approved = validate_success(
            api.approve_settlement(
                settlement["id"],
                make_approve_settlement_payload(note="final settlement with venue"),
                headers=finance_approver_headers,
            )
        )

        assert_event_settlement(approved)
        assert approved["variant"] == "FINAL"
        assert approved["state"] == "APPROVED"
        assert approved["approved_by_user_id"] == FINANCE_APPROVER_USER_ID

        # Order B was refunded after preparation, so only the group order on the
        # PITSIDE tier survives into the final inclusion set.
        assert approved["ticket_revenue_cents"] == 2_493_750
        assert approved["addon_revenue_cents"] == 0
        assert approved["facility_fee_cents"] == 210_000
        # The activation never reached FULFILLED, so half of its 1,500,000-cent
        # fee is held back.
        assert approved["sponsorship_revenue_cents"] == 750_000
        assert approved["collected_cash_cents"] == 3_453_750

        # The smaller inclusion set drags the facility fee total down with it, so
        # the pre-credit rental total and the credit both shrink.
        assert approved["rental_due_pre_credit_cents"] == 3_210_000
        assert approved["coop_credit_cents"] == 128_400
        assert approved["venue_due_cents"] == 3_081_600

        assert approved["net_to_promoter_cents"] == -2_631_850
        assert approved["profitability_margin_pct"] == pytest.approx(
            -76.20, abs=0.01
        )

        stop = helpers.fetch_stop(api, state["stop_id"])
        assert stop["sales_state"] == "SETTLED"
        season = helpers.fetch_season(api, state["season_id"])
        assert season["settled_stop_count"] == 1
        assert season["season_net_cents"] == -2_631_850
        assert season["status"] == "CLOSED"

    def test_the_payout_waterfall_moves_from_fully_funded_to_a_shortfall_between_the_variants(
        self,
        api: ApiClient,
        finance_preparer_headers: Dict[str, str],
        finance_approver_headers: Dict[str, str],
        ticketing_headers: Dict[str, str],
    ) -> None:
        """PRD §3.9: "Immediately after those figures, and in both variants, the payout waterfall funds four buckets in this exact order out of `collected_cash_cents`."

        PRD §3.9: "These are integer subtractions with no rounding, and every settlement must satisfy the identity that `net_to_promoter_cents` equals `promoter_remainder_cents` minus `shortfall_cents` under both variants."

        Design: Difficulty/dual_variant_calc/settlement_provisional_then_final_sponsor_holdback_and_refund_dropout
        """
        state = _atl_stop_with_two_paid_orders(api)

        provisional = _prepare_settlement(
            api, state["stop_id"], finance_preparer_headers
        )

        # The three obligations outside the box office are variant-independent:
        # the certified plan's provisioning bill, the committed marketing money
        # and 150,000 cents of purse for the one staged entry.
        assert provisional["safety_cost_cents"] == 854_000
        assert provisional["marketing_spend_cents"] == 2_000_000
        assert provisional["purse_cents"] == 150_000

        # 7,503,750 cents of collected cash funds all four buckets in full.
        assert provisional["payout_venue_cents"] == 3_384_000
        assert provisional["payout_safety_cents"] == 854_000
        assert provisional["payout_marketing_cents"] == 2_000_000
        assert provisional["payout_purse_cents"] == 150_000
        assert provisional["promoter_remainder_cents"] == 1_115_750
        assert provisional["shortfall_cents"] == 0
        assert (
            provisional["net_to_promoter_cents"]
            == provisional["promoter_remainder_cents"]
            - provisional["shortfall_cents"]
        )

        validate_success(
            api.refund_ticket_order(
                state["order_b_id"],
                make_refund_payload(reason="purchaser chargeback after preparation"),
                headers=ticketing_headers,
            )
        )
        final = validate_success(
            api.approve_settlement(
                provisional["id"],
                make_approve_settlement_payload(note="final settlement with venue"),
                headers=finance_approver_headers,
            )
        )

        # 3,453,750 cents of collected cash covers the building, leaves only
        # 372,150 for the safety desk and nothing at all for the last two buckets.
        assert final["payout_venue_cents"] == 3_081_600
        assert final["payout_safety_cents"] == 372_150
        assert final["payout_marketing_cents"] == 0
        assert final["payout_purse_cents"] == 0
        assert final["promoter_remainder_cents"] == 0
        assert final["shortfall_cents"] == 2_631_850
        assert (
            final["net_to_promoter_cents"]
            == final["promoter_remainder_cents"] - final["shortfall_cents"]
        )


class TestVehicleReadinessPreStagingVersusPostStaging:
    """The pre-staging projection and the post-staging actuals of one entry."""

    @staticmethod
    def _certified_stop(api: ApiClient) -> Dict[str, Any]:
        """A confirmed ATL stop whose safety plan is certified, so check-in lands.

        Check-in requires a certified safety envelope, which the readiness
        scenario needs before the transporter can be recorded as arrived.
        """
        state = helpers.stop_with_show_timing(api)
        state.update(helpers.certified_safety_plan(api, state["stop_id"]))
        return state

    @staticmethod
    def _enter_vehicle(
        api: ApiClient, stop_id: str, competitor_id: str, headers: Dict[str, str]
    ) -> Dict[str, Any]:
        """Enter the 7,200-pound rig that hauls 1,200 miles to this stop."""
        return validate_success(
            api.create_vehicle_entry(
                make_vehicle_entry_payload(
                    competitor_id,
                    stop_id,
                    scheduled_arrival_utc=_PROMISED_ARRIVAL_UTC,
                ),
                headers=headers,
            ),
            expected_status=201,
        )

    def test_pre_staging_variant_scores_the_promised_arrival_at_entry_creation(
        self,
        api: ApiClient,
        competitor_team_headers: Callable[[str], Dict[str, str]],
    ) -> None:
        """PRD §3.3: "Under the **`PRE_STAGING`** variant, which runs at entry creation while the transporter has not yet arrived and the entry is still `ENTERED`, the schedule penalty is 15 points when the promised `scheduled_arrival_utc` falls later than the staging close instant — that is, later than two hours before `show_start_utc` — and 0 otherwise."

        Design: Difficulty/dual_variant_calc/vehicle_readiness_pre_staging_projection_vs_post_staging_actuals
        """
        state = self._certified_stop(api)
        competitor = helpers.create_competitor(api)

        entry = self._enter_vehicle(
            api,
            state["stop_id"],
            competitor["competitor_id"],
            competitor_team_headers(competitor["competitor_id"]),
        )

        assert_vehicle_entry(entry)
        # 1,200 miles is two complete 500-mile blocks, so the shared haul penalty
        # costs 10 points; the 09:00Z promise precedes the 21:00Z staging close,
        # so the projected-late penalty is not charged and no inspection exists.
        assert_readiness_score(entry, 90, "PRE_STAGING")
        assert entry["actual_arrival_utc"] is None
        assert entry["logistics_state"] == "ENTERED"
        assert entry["tech_status"] == "TECH_PENDING"
        assert entry["staging_bay_index"] == 1

    def test_check_in_switches_to_the_post_staging_variant_and_scores_the_actual_arrival(
        self,
        api: ApiClient,
        competitor_team_headers: Callable[[str], Dict[str, str]],
    ) -> None:
        """PRD §3.3: "Under the **`POST_STAGING`** variant, which runs from check-in onwards while the entry is `STAGED` and is recomputed after every inspection attempt, the projection is discarded entirely: the schedule penalty is 15 points when the actual `actual_arrival_utc` is later than the promised `scheduled_arrival_utc`, and 0 otherwise."

        Design: Difficulty/dual_variant_calc/vehicle_readiness_pre_staging_projection_vs_post_staging_actuals
        """
        state = self._certified_stop(api)
        competitor = helpers.create_competitor(api)
        team_headers = competitor_team_headers(competitor["competitor_id"])
        entry = self._enter_vehicle(
            api, state["stop_id"], competitor["competitor_id"], team_headers
        )

        helpers.set_clock(api, _ACTUAL_ARRIVAL_UTC)
        staged = validate_success(
            api.check_in_vehicle_entry(
                entry["id"],
                make_check_in_payload(
                    arrival_note="transporter late off the interstate"
                ),
                headers=team_headers,
            )
        )

        # The transporter promised 09:00Z and arrived at 17:00Z, so the realized
        # arrival slip now costs 15 points on top of the 10-point haul penalty.
        assert_readiness_score(staged, 75, "POST_STAGING")
        assert staged["logistics_state"] == "STAGED"
        assert staged["actual_arrival_utc"] == _ACTUAL_ARRIVAL_UTC
        assert staged["actual_arrival_utc"] > staged["scheduled_arrival_utc"]
        assert staged["tech_attempt_count"] == 0
        assert staged["failed_attempt_count"] == 0

    def test_post_staging_rescoring_charges_the_failed_attempt_then_the_conditional_result(
        self,
        api: ApiClient,
        competitor_team_headers: Callable[[str], Dict[str, str]],
        safety_inspector_headers: Dict[str, str],
    ) -> None:
        """PRD §3.3: "The inspection penalty is 25 points for each failed attempt the entry has accumulated in `failed_attempt_count`, plus a further 10 points when the most recently filed inspection carries a `result` of `CONDITIONAL`."

        PRD §3.3: "A `FAILED` result moves the entry to `TECH_HELD`, increments both `tech_attempt_count` and `failed_attempt_count`, re-scores readiness with the 25-point-per-failure penalty, and — uniquely among the three branches — reaches across to the stop: the stop's posture is recomputed and becomes `RESTRICTED` while any live entry of the stop sits at `TECH_HELD`, which in turn drives a stop that was `ON_SALE` to `SALES_HALTED`."

        Design: Difficulty/dual_variant_calc/vehicle_readiness_pre_staging_projection_vs_post_staging_actuals
        """
        state = self._certified_stop(api)
        competitor = helpers.create_competitor(api)
        team_headers = competitor_team_headers(competitor["competitor_id"])
        entry = self._enter_vehicle(
            api, state["stop_id"], competitor["competitor_id"], team_headers
        )
        helpers.set_clock(api, _ACTUAL_ARRIVAL_UTC)
        validate_success(
            api.check_in_vehicle_entry(
                entry["id"],
                make_check_in_payload(
                    arrival_note="transporter late off the interstate"
                ),
                headers=team_headers,
            )
        )

        validate_success(
            api.create_tech_inspection(
                entry["id"],
                make_tech_inspection_payload(
                    result="FAILED",
                    defect_severity="MAJOR",
                    notes="fuel cell strap",
                ),
                headers=safety_inspector_headers,
            ),
            expected_status=201,
        )

        after_failure = helpers.fetch_entry(api, entry["id"])
        # 100 less 10 haul, less 15 arrival slip, less 25 for the one failure.
        assert_readiness_score(after_failure, 50, "POST_STAGING")
        assert after_failure["tech_attempt_count"] == 1
        assert after_failure["failed_attempt_count"] == 1
        assert after_failure["tech_status"] == "TECH_HELD"

        validate_success(
            api.create_tech_inspection(
                entry["id"],
                make_tech_inspection_payload(
                    result="CONDITIONAL",
                    defect_severity="MINOR",
                    notes="strap re-rated, monitor",
                ),
                headers=safety_inspector_headers,
            ),
            expected_status=201,
        )

        after_conditional = helpers.fetch_entry(api, entry["id"])
        # The earlier failure still counts, and the latest result being
        # CONDITIONAL costs a further 10 points.
        assert_readiness_score(after_conditional, 40, "POST_STAGING")
        assert after_conditional["tech_attempt_count"] == 2
        assert after_conditional["failed_attempt_count"] == 1
        assert after_conditional["tech_status"] == "TECH_CONDITIONAL"
