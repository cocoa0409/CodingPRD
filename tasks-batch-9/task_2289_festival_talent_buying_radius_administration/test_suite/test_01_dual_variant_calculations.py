"""Paired-variant figures: rider scopes, risk scores and cash recovery.

Each test builds every precondition it needs from an empty database and sets
the logical clock explicitly wherever a temporal rule matters.
"""

import pytest
from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import (
    BUSINESS_AFFAIRS,
    FINANCE_CONTROLLER,
    TALENT_BUYER,
    expected_adjudicated_risk_score,
    expected_draw_penalty,
    expected_line_cost_cents,
    expected_strict_risk_score,
)
from test_helpers import fixtures as fx
from test_helpers.constants import (
    PORTLAND_DISTANCE_MILES,
    RISK_BLOCK_THRESHOLD,
)
from test_helpers.factories import cancel_payload


# --------------------------------------------------------------------------
# Composite state builders used by the tests below.
# --------------------------------------------------------------------------
def _booking_with_mixed_rider_lines(api):
    """Accepted booking whose six rider lines exercise both rider scopes.

    Two plain approvals, one substitution, one promoter-provided approval, one
    line left undecided and one rejection.
    """
    ctx = fx.three_tier_edition(api)
    booking = fx.accepted_booking(api, ctx)
    artist_id = ctx["artist"]["id"]
    lines = {
        "technical": fx.add_rider_line(
            api,
            booking["id"],
            artist_id,
            category="TECHNICAL",
            description="Line array supplement",
            quantity=2,
            unit_cost_cents=125000,
            is_promoter_provided=False,
        ),
        "hospitality_capped": fx.add_rider_line(
            api,
            booking["id"],
            artist_id,
            category="HOSPITALITY",
            description="Dressing room build-out",
            quantity=4,
            unit_cost_cents=60000,
            is_promoter_provided=False,
        ),
        "travel_substituted": fx.add_rider_line(
            api,
            booking["id"],
            artist_id,
            category="TRAVEL",
            description="Crew ground transfers",
            quantity=3,
            unit_cost_cents=83333,
            is_promoter_provided=False,
        ),
        "promoter_provided": fx.add_rider_line(
            api,
            booking["id"],
            artist_id,
            category="TECHNICAL",
            description="House console upgrade",
            quantity=1,
            unit_cost_cents=90000,
            is_promoter_provided=True,
        ),
        "still_proposed": fx.add_rider_line(
            api,
            booking["id"],
            artist_id,
            category="HOSPITALITY",
            description="Post-show catering",
            quantity=2,
            unit_cost_cents=30000,
            is_promoter_provided=False,
        ),
        "rejected": fx.add_rider_line(
            api,
            booking["id"],
            artist_id,
            category="TRAVEL",
            description="Charter upgrade",
            quantity=1,
            unit_cost_cents=50000,
            is_promoter_provided=False,
        ),
    }
    fx.decide_rider_line(api, lines["technical"]["id"], "APPROVED")
    fx.decide_rider_line(api, lines["hospitality_capped"]["id"], "APPROVED")
    fx.decide_rider_line(
        api,
        lines["travel_substituted"]["id"],
        "SUBSTITUTED",
        substitute_unit_cost_cents=71501,
    )
    fx.decide_rider_line(api, lines["promoter_provided"]["id"], "APPROVED")
    fx.decide_rider_line(api, lines["rejected"]["id"], "REJECTED")
    return {"ctx": ctx, "booking": booking, "lines": lines}


def _act_with_three_open_reports_and_one_violation(api):
    """Act carrying an ACTIVE clause, three REPORTED conflicts and one violation."""
    ctx = fx.single_tier_edition(api, artist_overrides={"draw_score": 80})
    artist_id = ctx["artist"]["id"]
    fx.issued_offer(api, ctx, guarantee_cents=2000000)
    reports = [
        fx.report_performance(api, artist_id, performance_date=date)
        for date in ("2026-11-20", "2026-11-21", "2026-11-22", "2026-11-23")
    ]
    fx.adjudicate(
        api, reports[0]["id"], "VIOLATION", "Portland date inside the Seattle radius"
    )
    return {"ctx": ctx, "reports": reports}


def _cancelled_booking_with_paid_deposit(api):
    """Booking whose deposit was paid and which the ARTIST then cancelled."""
    ctx = fx.single_tier_edition(api)
    booking = fx.accepted_booking(api, ctx)
    installments = fx.installments_of(api, booking["id"])
    deposit = installments["DEPOSIT"]
    fx.set_clock(api, "2026-08-25T09:00:00Z")
    validate_success(api.release_installment(deposit["id"], FINANCE_CONTROLLER))
    validate_success(
        api.mark_installment_paid(
            deposit["id"], {"paid_amount_cents": 900000}, FINANCE_CONTROLLER
        )
    )
    fx.set_clock(api, "2026-11-20T12:00:00Z")
    cancelled = validate_success(
        api.cancel_booking(
            booking["id"],
            cancel_payload(
                cancelling_party="ARTIST", cancellation_reason="Artist illness"
            ),
            BUSINESS_AFFAIRS,
        )
    )
    return {"booking": cancelled, "deposit": deposit, "installments": installments}


# --------------------------------------------------------------------------
# rider scope variants
# --------------------------------------------------------------------------
def test_rider_proposed_and_contracted_scopes_diverge(api):
    """The two rider scopes read the same lines and return different totals.

    "`rider_proposed_cents` is the **proposed scope**: it sums `line_cost_cents` over every line whose `approval_status` is `PROPOSED`, `APPROVED` or `SUBSTITUTED`, charges promoter-provided lines at their full cost, and applies no per-line cap."
    "`rider_estimate_cents` is the **contracted scope**: it sums only lines whose `approval_status` is `APPROVED` or `SUBSTITUTED` — dropping both undecided and rejected lines — contributes 0 for any line whose `is_promoter_provided` is true, contributes the lesser of the line's `line_cost_cents` and 150000 cents (fifteen hundred dollars) for any `HOSPITALITY` line, and contributes the full `line_cost_cents` otherwise."

    Design: Difficulty/dual_variant_calc/rider_scope_variant_divergence_on_booking
    """
    state = _booking_with_mixed_rider_lines(api)

    estimate = validate_success(
        api.get_rider_estimate(
            state["booking"]["id"], BUSINESS_AFFAIRS, {"variant": "BOTH"}
        )
    )

    assert estimate["proposed_scope_cents"] == 880243
    assert estimate["contracted_scope_cents"] == 640243
    assert estimate["variant_delta_cents"] == 240000
    assert estimate["capped_line_count"] == 1


def test_substituted_travel_line_prices_off_the_substitute_unit_cost(api):
    """A substituted line re-prices per line and both booking totals follow it.

    "`line_cost_cents` is then the `quantity` multiplied by the effective unit price multiplied by one plus the escalation, rounded half up to whole cents."

    Design: Difficulty/dual_variant_calc/rider_scope_variant_divergence_on_booking
    """
    state = _booking_with_mixed_rider_lines(api)

    substituted = validate_success(
        api.get_rider_item(state["lines"]["travel_substituted"]["id"], TALENT_BUYER)
    )
    assert substituted["line_cost_cents"] == 240243
    assert substituted["line_cost_cents"] == expected_line_cost_cents(
        3, 71501, "TRAVEL"
    )

    booking = validate_success(api.get_booking(state["booking"]["id"], TALENT_BUYER))
    assert booking["rider_proposed_cents"] == 880243
    assert booking["rider_estimate_cents"] == 640243


def test_booking_stays_pending_rider_while_one_line_is_undecided(api):
    """One still-PROPOSED line keeps the contracting dimension where it was.

    "In all three branches, when the decision leaves no line of that booking still `PROPOSED` and the booking has at least one rider line, the booking's `contract_status` moves `PENDING_RIDER → RIDER_SETTLED`."

    Design: Difficulty/dual_variant_calc/rider_scope_variant_divergence_on_booking
    """
    state = _booking_with_mixed_rider_lines(api)

    undecided = validate_success(
        api.get_rider_item(state["lines"]["still_proposed"]["id"], TALENT_BUYER)
    )
    assert undecided["approval_status"] == "PROPOSED"

    booking = validate_success(api.get_booking(state["booking"]["id"], TALENT_BUYER))
    assert booking["contract_status"] == "PENDING_RIDER"


# --------------------------------------------------------------------------
# artist risk variants
# --------------------------------------------------------------------------
def test_strict_risk_variant_counts_unadjudicated_reports(api):
    """The strict variant charges open reports and blocks at the threshold.

    "`strict_risk_score` is the smaller of 100 and the sum of twelve points per unadjudicated conflict, twenty-five points per adjudicated breach, and the draw penalty."
    "It returns the requested `variant`, the act's `reported_conflict_count` and `radius_breach_count`, the `draw_penalty` in points, the resulting `risk_score`, and a `blocked` flag reflecting whether that variant's score has reached the blocking threshold of 60."

    Design: Difficulty/dual_variant_calc/artist_risk_variant_divergence_on_roster
    """
    state = _act_with_three_open_reports_and_one_violation(api)

    risk = validate_success(
        api.get_radius_risk(
            state["ctx"]["artist"]["id"], TALENT_BUYER, {"variant": "STRICT"}
        )
    )

    assert risk["variant"] == "STRICT"
    assert risk["reported_conflict_count"] == 3
    assert risk["radius_breach_count"] == 1
    assert risk["draw_penalty"] == 4
    assert risk["risk_score"] == 65
    assert risk["risk_score"] == expected_strict_risk_score(3, 1, 80)
    assert risk["blocked"] is True
    assert risk["risk_score"] >= RISK_BLOCK_THRESHOLD


def test_adjudicated_risk_variant_ignores_unadjudicated_reports(api):
    """The adjudicated variant drops the open reports and does not block.

    "`adjudicated_risk_score` is the smaller of 100 and the sum of twenty-five points per adjudicated breach and the draw penalty — it ignores unadjudicated reports entirely, so an act with three open reports and no adjudicated violation is not blocked."

    Design: Difficulty/dual_variant_calc/artist_risk_variant_divergence_on_roster
    """
    state = _act_with_three_open_reports_and_one_violation(api)

    risk = validate_success(
        api.get_radius_risk(
            state["ctx"]["artist"]["id"], TALENT_BUYER, {"variant": "ADJUDICATED"}
        )
    )

    assert risk["variant"] == "ADJUDICATED"
    assert risk["reported_conflict_count"] == 3
    assert risk["radius_breach_count"] == 1
    assert risk["draw_penalty"] == expected_draw_penalty(80)
    assert risk["risk_score"] == 29
    assert risk["risk_score"] == expected_adjudicated_risk_score(1, 80)
    assert risk["blocked"] is False


def test_both_stored_risk_scores_follow_the_adjudication(api):
    """The act's stored scores and the detected distance agree with the variants.

    "Otherwise the candidates are ranked by `radius_miles` descending, then `window_start_date` ascending, then `created_at` ascending, and the first is the winner: `conflict_assessment` becomes `CONFLICT`, `conflicting_radius_clause_id` names the winning clause, and `distance_to_market_miles` records the distance to that winner's market, rounded half up to two decimals."

    Design: Difficulty/dual_variant_calc/artist_risk_variant_divergence_on_roster
    """
    state = _act_with_three_open_reports_and_one_violation(api)

    artist = validate_success(
        api.get_artist(state["ctx"]["artist"]["id"], TALENT_BUYER)
    )
    assert artist["strict_risk_score"] == 65
    assert artist["adjudicated_risk_score"] == 29
    assert artist["reported_conflict_count"] == 3
    assert artist["radius_breach_count"] == 1

    last_report = validate_success(
        api.get_competing_performance(state["reports"][3]["id"], BUSINESS_AFFAIRS)
    )
    assert last_report["conflict_assessment"] == "CONFLICT"
    assert last_report["distance_to_market_miles"] == pytest.approx(
        PORTLAND_DISTANCE_MILES
    )
    assert last_report["distance_to_market_miles"] == pytest.approx(145.41)


# --------------------------------------------------------------------------
# contractual versus actually recovered cash
# --------------------------------------------------------------------------
def test_contractual_recovery_exceeds_the_replayed_actual_recovery(api):
    """Liquidated damages sit in the contractual figure that no installment carried.

    "`contractual_recovery_cents` is then the booking's `deposit_paid_cents` multiplied by the party percentage and rounded half up, **plus separately** the booking's `guarantee_cents` multiplied by the liquidated-damages percentage and rounded half up."
    "The booking's `actual_recovered_cents` is then re-derived by replaying the booking's installments in `due_date` ascending order with `created_at` ascending as the tie-break, accumulating the `recovered_cents` of every row whose `status` is `RECOVERED`, and clamping the running total at `contractual_recovery_cents`."

    Design: Difficulty/dual_variant_calc/deposit_recovery_contractual_versus_actual_chronological
    """
    state = _cancelled_booking_with_paid_deposit(api)
    assert state["booking"]["contractual_recovery_cents"] == 1080000

    installment = validate_success(
        api.clawback_installment(
            state["deposit"]["id"], {"recovered_cents": 900000}, FINANCE_CONTROLLER
        )
    )
    assert installment["status"] == "RECOVERED"
    assert installment["recovered_cents"] == 900000

    booking = validate_success(api.get_booking(state["booking"]["id"], TALENT_BUYER))
    assert booking["contractual_recovery_cents"] == 1080000
    assert booking["actual_recovered_cents"] == 900000
    assert (
        booking["contractual_recovery_cents"] - booking["actual_recovered_cents"]
        == 180000
    )
    assert booking["settlement_status"] == "RECOVERED"


def test_second_clawback_on_a_recovered_installment_is_refused(api):
    """A recovered installment is closed to any further recovery.

    "Any installment transition that is not declared — releasing a `PAID` row, paying a `SCHEDULED` one, touching a `VOIDED` or `RECOVERED` row — is `ERR_INVALID_INSTALLMENT_STATE`."

    Design: Difficulty/dual_variant_calc/deposit_recovery_contractual_versus_actual_chronological
    """
    state = _cancelled_booking_with_paid_deposit(api)
    validate_success(
        api.clawback_installment(
            state["deposit"]["id"], {"recovered_cents": 900000}, FINANCE_CONTROLLER
        )
    )

    validate_error(
        api.clawback_installment(
            state["deposit"]["id"], {"recovered_cents": 1}, FINANCE_CONTROLLER
        ),
        "ERR_INVALID_INSTALLMENT_STATE",
        409,
    )

    booking = validate_success(api.get_booking(state["booking"]["id"], TALENT_BUYER))
    assert booking["actual_recovered_cents"] == 900000
