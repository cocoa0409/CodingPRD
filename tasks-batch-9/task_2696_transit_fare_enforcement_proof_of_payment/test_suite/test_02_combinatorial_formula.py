"""
Multi-step formulas whose rounding order and clamp nesting are normative: the
same inputs produce different answers if the steps are reordered.
"""

from decimal import Decimal

from prd_bench_local_runner.testing import validate_success

from test_helpers import factories, fixtures
from test_helpers.assertions import (
    assert_instant_equals,
    assert_citation_money_identity,
    assert_installment_schedule,
    assert_rate_equals,
    quantize_rate,
)
from test_helpers.constants import (
    BAND_A,
    BAND_B,
    GROUP_BY_DEMOGRAPHIC_BAND,
    IDENTITY_SELF_REPORTED,
    MEDIA_MOBILE_QR,
    MEDIA_NONE,
    MEDIA_PAPER_TRANSFER,
    MEDIA_SMARTCARD,
    PAYMENT_SOURCE_DOWN_PAYMENT,
    PLAN_STATUS_ACTIVE,
    SAMPLING_CLUSTER_RANDOM,
    SAMPLING_STRATIFIED_TIME,
    SETTLEMENT_PLAN_ACTIVE,
    VALIDATION_EXPIRED,
    VALIDATION_UNVALIDATED_TAP,
)
from test_helpers.test_users import ANALYST_HEADERS, make_rider_headers


# ── The clamp wraps the conditional discount ─────────────────────────

def _third_rung_assisted_rider(api):
    """
    A fare-assistance rider on the third rung of the warning-inclusive ladder,
    presenting an expired paper transfer.
    """
    env = fixtures.build_environment(
        api,
        zone_code="ZN2",
        zone_name="Riverside POP Zone",
        penalty_multiplier_bps=12345,
        rider_ref="R-300",
        rider_display_name="Rider Three",
        demographic_band="BAND_C",
        residence_geo_tract="T-003",
        fare_assistance_enrolled=True,
    )
    deployment = fixtures.build_active_deployment(
        api, env,
        sampling_method=SAMPLING_STRATIFIED_TIME,
        target_sample_size=3,
        observe_at="2026-08-05T10:00:00Z",
    )
    inspector_id = env["inspector"]["id"]
    for occurred_at in ("2026-08-05T07:00:00Z", "2026-08-05T08:00:00Z"):
        warned = fixtures.build_pending_encounter(
            api, env, deployment, occurred_at=occurred_at, fare_media_type=MEDIA_NONE
        )
        fixtures.resolve(api, warned["id"], inspector_id, "WARNING_ISSUED")
    subject = fixtures.build_pending_encounter(
        api, env, deployment,
        occurred_at="2026-08-05T09:00:00Z",
        fare_media_type=MEDIA_PAPER_TRANSFER,
        media_reference="PT-001",
        media_expires_at="2026-08-05T08:00:00Z",
        media_zone_code="ZN2",
    )
    return env, subject


def test_assistance_discount_is_applied_before_the_clamp(api):
    """
    The scaled figure is discounted for a fare-assistance rider and only then is
    the result raised to the penalty floor and lowered to the penalty cap, so a
    third-rung base of 25000 scaled to 30863 and halved to 15432 stays at 15432
    rather than being capped to 27500 first and halved after.

    Design: Difficulty/combinatorial_formula/assessed_penalty_nested_clamp_after_conditional_assistance_discount
    """
    env, subject = _third_rung_assisted_rider(api)

    assert fixtures.read_encounter(api, subject["id"])["validation_result"] == VALIDATION_EXPIRED

    citation = validate_success(
        api.create_citation(
            factories.citation_payload(subject["id"]),
            fixtures.make_fare_inspector_headers(env["inspector"]["id"]),
        ),
        201,
    )

    assert citation["offense_sequence"] == 3
    assert citation["citation_only_sequence"] == 1
    assert citation["assessed_penalty_cents"] == 15432
    assert citation["assessed_penalty_cents"] != 13750


def test_each_multiplicative_step_is_rounded_before_the_next(api):
    """
    Each multiplicative step is rounded before the next consumes its result, so
    25000 at 12345 basis points rounds to 30863 and halving that rounds to 15432;
    computing the whole chain and rounding once at the end would yield 15431.

    Design: Difficulty/combinatorial_formula/assessed_penalty_nested_clamp_after_conditional_assistance_discount
    """
    env, subject = _third_rung_assisted_rider(api)

    citation = fixtures.issue_citation(api, subject["id"], env["inspector"]["id"])

    assert citation["assessed_penalty_cents"] == 15432
    assert citation["assessed_penalty_cents"] != 15431
    assert citation["reduction_floor_cents"] == 4630
    assert citation["admin_fee_cents"] == 1852
    assert citation["total_due_cents"] == 17284
    assert_citation_money_identity(citation)


# ── Floor the installments, absorb the remainder in the last one ─────

def _plan_over_a_second_offence_balance(api):
    """A second-offence citation of 20160, ready to be financed."""
    env = fixtures.build_environment(api)
    deployment = fixtures.build_active_deployment(api, env)
    inspector_id = env["inspector"]["id"]
    warned = fixtures.build_pending_encounter(
        api, env, deployment, occurred_at="2026-08-05T07:00:00Z"
    )
    fixtures.resolve(api, warned["id"], inspector_id, "WARNING_ISSUED")
    cited = fixtures.build_pending_encounter(
        api, env, deployment, occurred_at="2026-08-05T08:00:00Z"
    )
    citation = fixtures.issue_citation(api, cited["id"], inspector_id)
    fixtures.move_clock(api, "2026-08-06T00:00:00Z")
    citation = fixtures.read_citation(api, citation["id"])
    return env, citation


def test_installment_schedule_floors_the_base_and_pushes_the_remainder_last(api):
    """
    The base installment is the financed total divided by the installment count
    rounded down, and the whole remainder is pushed into the final installment,
    so 17660 over three installments is 5886, 5886 and 5888 rather than three
    equal amounts that would over-collect.

    Design: Difficulty/combinatorial_formula/payment_plan_floor_then_absorb_remainder_in_final_installment
    """
    env, citation = _plan_over_a_second_offence_balance(api)

    plan = validate_success(
        api.create_payment_plan(
            factories.payment_plan_payload(
                citation_id=citation["id"],
                installment_count=3,
                down_payment_cents=2500,
                expected_citation_version=citation["version"],
            ),
            make_rider_headers(env["rider"]["id"]),
        ),
        201,
    )

    assert plan["status"] == PLAN_STATUS_ACTIVE
    assert plan["financed_cents"] == 17660
    assert plan["base_installment_cents"] == 5886
    assert plan["final_installment_cents"] == 5888
    assert plan["final_installment_cents"] != 5886
    assert plan["base_installment_cents"] * 2 + plan["final_installment_cents"] == 17660
    assert_installment_schedule(plan)


def test_opening_the_plan_books_the_down_payment_and_moves_the_citation(api):
    """
    A new plan opens with `remaining_balance_cents` equal to `financed_cents` and
    no installments paid, the down payment is booked as a ledger row that raises
    the citation's `amount_paid_cents`, and the citation's settlement dimension
    moves to `PLAN_ACTIVE` with the first installment due 30 days out.

    Design: Difficulty/combinatorial_formula/payment_plan_floor_then_absorb_remainder_in_final_installment
    """
    env, citation = _plan_over_a_second_offence_balance(api)

    plan = fixtures.get_success_data(
        api.create_payment_plan(
            factories.payment_plan_payload(
                citation_id=citation["id"],
                installment_count=3,
                down_payment_cents=2500,
                expected_citation_version=citation["version"],
            ),
            make_rider_headers(env["rider"]["id"]),
        )
    )

    assert plan["remaining_balance_cents"] == 17660
    assert plan["installments_paid_count"] == 0
    assert_instant_equals(plan["first_due_at"], "2026-09-05T00:00:00Z", "plan.first_due_at")

    financed = fixtures.read_citation(api, citation["id"])
    assert financed["amount_paid_cents"] == 2500
    assert financed["outstanding_balance_cents"] == 17660
    assert financed["settlement_status"] == SETTLEMENT_PLAN_ACTIVE

    rows = fixtures.citation_ledger(api, citation["id"])
    assert [row["source"] for row in rows] == [PAYMENT_SOURCE_DOWN_PAYMENT]
    assert rows[0]["amount_cents"] == 2500


# ── Group rates are rounded before their deviations are taken ────────

EQUITY_WINDOW = ("2026-08-01T00:00:00Z", "2026-09-01T00:00:00Z")

VALID_SMARTCARD = {
    "fare_media_type": MEDIA_SMARTCARD,
    "media_expires_at": "2026-08-05T23:00:00Z",
    "media_zone_code": "ZN1",
}


def _two_bands_one_citation_each(api):
    """Three BAND_A riders and two BAND_B riders, one cited in each band."""
    env = fixtures.build_environment(
        api, rider_ref="RA-1", rider_display_name="Rider A1", demographic_band=BAND_A
    )
    others = [
        fixtures.register_rider(
            api, rider_ref="RA-2", display_name="Rider A2",
            demographic_band=BAND_A, residence_geo_tract="T-001",
        ),
        fixtures.register_rider(
            api, rider_ref="RA-3", display_name="Rider A3",
            demographic_band=BAND_A, residence_geo_tract="T-002",
        ),
        fixtures.register_rider(
            api, rider_ref="RB-1", display_name="Rider B1",
            demographic_band=BAND_B, residence_geo_tract="T-003",
        ),
        fixtures.register_rider(
            api, rider_ref="RB-2", display_name="Rider B2",
            demographic_band=BAND_B, residence_geo_tract="T-003",
        ),
    ]
    deployment = fixtures.build_active_deployment(
        api, env,
        sampling_method=SAMPLING_CLUSTER_RANDOM,
        target_sample_size=5,
        observe_at="2026-08-05T12:00:00Z",
    )
    inspector_id = env["inspector"]["id"]

    cited_a = fixtures.build_pending_encounter(
        api, env, deployment, occurred_at="2026-08-05T07:00:00Z"
    )
    fixtures.issue_citation(api, cited_a["id"], inspector_id)
    for rider, occurred_at, reference, validated_at in (
        (others[0], "2026-08-05T07:10:00Z", "SC-A2", "2026-08-05T07:05:00Z"),
        (others[1], "2026-08-05T07:20:00Z", "SC-A3", "2026-08-05T07:15:00Z"),
    ):
        compliant = fixtures.build_pending_encounter(
            api, env, deployment, rider=rider, occurred_at=occurred_at,
            media_reference=reference, media_validated_at=validated_at, **VALID_SMARTCARD
        )
        fixtures.resolve(api, compliant["id"], inspector_id, "COMPLIANT")
    cited_b = fixtures.build_pending_encounter(
        api, env, deployment, rider=others[2], occurred_at="2026-08-05T07:30:00Z"
    )
    fixtures.issue_citation(api, cited_b["id"], inspector_id)
    compliant_b = fixtures.build_pending_encounter(
        api, env, deployment, rider=others[3], occurred_at="2026-08-05T07:40:00Z",
        media_reference="SC-B2", media_validated_at="2026-08-05T07:35:00Z", **VALID_SMARTCARD
    )
    fixtures.resolve(api, compliant_b["id"], inspector_id, "COMPLIANT")
    fixtures.move_clock(api, "2026-08-06T00:00:00Z")
    return env


def test_disparity_index_deviates_from_the_rounded_group_rates(api):
    """
    The disparity index is the mean absolute deviation of the rounded group rates
    from the systemwide rate, rounded again, so one BAND_A citation in three
    encounters contributes a deviation taken from 0.3333 and the index lands on
    0.0834 rather than on the 0.0833 an unrounded aggregation would give.

    Design: Difficulty/combinatorial_formula/equity_disparity_index_rounds_group_rates_before_deviation
    """
    _two_bands_one_citation_each(api)

    report = validate_success(
        api.get_equity_distribution_report(
            factories.equity_report_params(*EQUITY_WINDOW, group_by=GROUP_BY_DEMOGRAPHIC_BAND),
            ANALYST_HEADERS,
        ),
        200,
    )

    assert report["group_by"] == GROUP_BY_DEMOGRAPHIC_BAND
    assert report["groups_evaluated"] == 2
    assert report["encounter_pool_count"] == 5
    assert report["citation_count"] == 2
    assert_rate_equals(report["systemwide_citation_rate"], 0.4000, "systemwide_citation_rate")
    assert_rate_equals(report["disparity_index"], 0.0834, "disparity_index")
    assert quantize_rate(report["disparity_index"]) != Decimal("0.0833")


def test_each_group_carries_its_own_rate_and_signed_delta(api):
    """
    Groups are listed in ascending key order with only the non-empty ones
    counted, and each carries its own citation rate and its signed deviation from
    the systemwide rate.

    Design: Difficulty/combinatorial_formula/equity_disparity_index_rounds_group_rates_before_deviation
    """
    _two_bands_one_citation_each(api)

    report = fixtures.get_success_data(
        api.get_equity_distribution_report(
            factories.equity_report_params(*EQUITY_WINDOW, group_by=GROUP_BY_DEMOGRAPHIC_BAND),
            ANALYST_HEADERS,
        )
    )
    groups = report["groups"]

    assert [group["group_key"] for group in groups] == [BAND_A, BAND_B]
    assert groups[0]["encounter_pool_count"] == 3
    assert groups[0]["citation_count"] == 1
    assert_rate_equals(groups[0]["citation_rate"], 0.3333, "BAND_A citation_rate")
    assert_rate_equals(groups[0]["rate_delta"], -0.0667, "BAND_A rate_delta")
    assert groups[1]["encounter_pool_count"] == 2
    assert groups[1]["citation_count"] == 1
    assert_rate_equals(groups[1]["citation_rate"], 0.5000, "BAND_B citation_rate")
    assert_rate_equals(groups[1]["rate_delta"], 0.1000, "BAND_B rate_delta")


# ── The fee band is keyed on the pre-fee penalty ─────────────────────

def _penalty_landing_exactly_on_the_band_edge(api):
    """A second-rung citation whose scaled penalty rounds to exactly 20000."""
    env = fixtures.build_environment(
        api,
        zone_code="ZN3",
        zone_name="Airport POP Zone",
        penalty_multiplier_bps=13333,
        rider_ref="R-400",
        rider_display_name="Rider Four",
        demographic_band="BAND_D",
        residence_geo_tract="T-004",
    )
    deployment = fixtures.build_active_deployment(
        api, env, target_sample_size=3, observe_at="2026-08-05T10:00:00Z"
    )
    inspector_id = env["inspector"]["id"]
    unvalidated = fixtures.build_pending_encounter(
        api, env, deployment,
        occurred_at="2026-08-05T07:00:00Z",
        fare_media_type=MEDIA_MOBILE_QR,
        media_reference="QR-001",
        media_zone_code="ZN3",
        identity_capture_method=IDENTITY_SELF_REPORTED,
    )
    fixtures.resolve(api, unvalidated["id"], inspector_id, "WARNING_ISSUED")
    subject = fixtures.build_pending_encounter(
        api, env, deployment, occurred_at="2026-08-05T08:00:00Z"
    )
    return env, unvalidated, subject


def test_fee_band_edge_uses_the_pre_fee_penalty_not_the_total(api):
    """
    The band is keyed on `assessed_penalty_cents`, the pre-fee penalty, and never
    on `total_due_cents`, so an assessed penalty of exactly 20000 attracts 1200
    basis points for a fee of 2400 and a total of 22400.

    Design: Difficulty/combinatorial_formula/admin_fee_band_keyed_on_pre_fee_assessed_penalty_at_band_edge
    """
    env, _unvalidated, subject = _penalty_landing_exactly_on_the_band_edge(api)

    citation = validate_success(
        api.create_citation(
            factories.citation_payload(subject["id"]),
            fixtures.make_fare_inspector_headers(env["inspector"]["id"]),
        ),
        201,
    )

    assert citation["offense_sequence"] == 2
    assert citation["assessed_penalty_cents"] == 20000
    assert citation["admin_fee_cents"] == 2400
    assert citation["admin_fee_cents"] != 3000
    assert citation["total_due_cents"] == 22400
    assert citation["total_due_cents"] != 23000


def test_the_band_edge_citation_keeps_its_floor_and_its_balance(api):
    """
    The same citation carries a reduction floor assessed from the citation-only
    rung and opens with `outstanding_balance_cents` equal to `total_due_cents`,
    while the earlier warning came from a tap with no validation record.

    Design: Difficulty/combinatorial_formula/admin_fee_band_keyed_on_pre_fee_assessed_penalty_at_band_edge
    """
    env, unvalidated, subject = _penalty_landing_exactly_on_the_band_edge(api)

    assert (
        fixtures.read_encounter(api, unvalidated["id"])["validation_result"]
        == VALIDATION_UNVALIDATED_TAP
    )

    citation = fixtures.issue_citation(api, subject["id"], env["inspector"]["id"])

    assert citation["reduction_floor_cents"] == 10000
    assert citation["outstanding_balance_cents"] == 22400
    assert_citation_money_identity(citation)
