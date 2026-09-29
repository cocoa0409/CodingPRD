"""Queue A — rule_id: dual_variant_calc.

Two variants of one calculation over identical stored data must diverge:
deployment cost (provisional vs final-settled) and event loss estimation
(EXPOSURE_BASED vs INCURRED_DEVELOPMENT).
"""
from test_helpers import get_success_data, validate_success
from test_helpers.assertions import (
    assert_deployment,
    assert_loss_estimate_snapshot,
    assert_money_equals,
)
from test_helpers.test_users import (
    make_catastrophe_manager_headers,
    make_claims_examiner_headers,
    make_deployment_coordinator_headers,
)

CM = make_catastrophe_manager_headers("cm_1")
DC = make_deployment_coordinator_headers("dc_1")
CE = make_claims_examiner_headers("ce_1")


# ---------------------------------------------------------------------------
# Instance 1 — deployment_cost_provisional_vs_final_settled_divergence
# ---------------------------------------------------------------------------
def _independent_field_deployment(api):
    """CAT-2026-114 DECLARED; INDEPENDENT adjuster (900/150); ACTIVE 40-room
    block at 200/night; FIELD deployment 2026-09-01 -> 2026-09-11, 2 rooms."""
    event = validate_success(
        api.create_event(
            {
                "cat_code": "CAT-2026-114",
                "peril_type": "HURRICANE",
                "jurisdiction_state": "FL",
                "event_start_utc": "2026-08-01T00:00:00.000Z",
                "exposure_count": 1000,
                "avg_insured_value": 250000,
                "expected_severity_index": 0.0400,
            },
            CM,
        ),
        201,
    )
    validate_success(api.declare_event(event["id"], CM))
    adjuster = validate_success(
        api.create_adjuster(
            {
                "full_name": "Ivy Independent",
                "employment_type": "INDEPENDENT",
                "home_state": "GA",
                "licensed_states": ["FL", "GA"],
                "license_expiry_utc": "2027-06-30T00:00:00.000Z",
                "max_open_claims": 10,
                "daily_rate": 900,
                "per_diem_rate": 150,
                "desk_certified": False,
                "aerial_certified": False,
            },
            DC,
        ),
        201,
    )
    block = validate_success(
        api.create_housing_block(
            {
                "event_id": event["id"],
                "hotel_name": "Gulf Inn",
                "city": "Tampa",
                "rooms_total": 40,
                "nightly_rate": 200,
                "block_start_date": "2026-09-01T00:00:00.000Z",
                "block_end_date": "2026-09-15T00:00:00.000Z",
            },
            DC,
        ),
        201,
    )
    validate_success(api.open_housing_block(block["id"], DC))
    deployment = validate_success(
        api.create_deployment(
            {
                "event_id": event["id"],
                "role_type": "FIELD",
                "window_start_utc": "2026-09-01T00:00:00.000Z",
                "window_end_utc": "2026-09-11T00:00:00.000Z",
                "adjuster_id": adjuster["id"],
                "housing_block_id": block["id"],
                "rooms_reserved": 2,
            },
            DC,
        ),
        201,
    )
    return event, adjuster, block, deployment


def test_provisional_variant_bills_full_window_with_unconditional_per_diem(api):
    """PRD §3.5: "The **provisional** variant, stamped into `provisional_cost` at
    confirmation, uses the deployment's full requested `window_end_utc` as the
    settle-end instant and treats per-diem eligibility as 1 unconditionally, so an
    independent adjuster with a hotel room is charged per-diem *and* housing."
    PRD §3.5: "Step four picks the tier **from that subtotal alone, never from the
    post-premium total**, so no iteration is needed and the answer is well-defined
    in a single pass: a subtotal of 20000.00 or more is `TIER_HIGH` at a premium
    rate of 11 percent; a subtotal of 5000.00 or more but below 20000.00 is
    `TIER_MID` at 6 percent; anything below 5000.00 is `TIER_NONE` at zero."

    Design: Difficulty/dual_variant_calc/deployment_cost_provisional_vs_final_settled_divergence
    """
    _, _, _, deployment = _independent_field_deployment(api)

    confirmed = validate_success(api.confirm_deployment(deployment["id"], DC))

    assert_deployment(confirmed)
    # nights 10; labour round(900*1.35*10)=12150.00; per-diem round(150*10*1)=1500.00;
    # housing round(200*2*10)=4000.00; subtotal 17650.00 -> TIER_MID 6% -> 1059.00.
    assert_money_equals(confirmed["provisional_cost"], 18709.00, "provisional_cost")
    assert confirmed["surge_premium_tier"] == "TIER_MID"


def test_final_settled_variant_truncates_nights_and_drops_independent_per_diem(api):
    """PRD §3.5: "The **final-settled** variant, stamped into `final_settled_cost`
    at demobilization, uses the earlier of the deployment's `window_end_utc` and its
    `demobilized_at_utc` as the settle-end instant, so an early demobilization
    shortens the nights; and it grants per-diem eligibility of 1 only when the
    adjuster's `employment_type` is `STAFF` or the deployment names no housing
    block, so an independent adjuster in company housing loses per-diem entirely."
    PRD §3.5: "Link one stamps `demobilized_at_utc` with the current logical-clock
    instant, stamps `final_settled_cost` from the final-settled variant of the cost
    rule, and re-stamps `surge_premium_tier`; the block's `rooms_occupied` falls by
    the deployment's `rooms_reserved`, `rooms_available` is recomputed, and a block
    that was `EXHAUSTED` returns to `ACTIVE` once availability is 1 or more."
    PRD §3.1: "`deployment_settled_cost` sums the `final_settled_cost` of every
    deployment on the event that has reached `DEMOBILIZED`, to 2 decimal places."

    Design: Difficulty/dual_variant_calc/deployment_cost_provisional_vs_final_settled_divergence
    """
    event, _, _, deployment = _independent_field_deployment(api)
    confirmed = validate_success(api.confirm_deployment(deployment["id"], DC))
    provisional = confirmed["provisional_cost"]

    validate_success(api.set_clock("2026-09-06T00:00:00.000Z", DC))
    settled = validate_success(api.demobilize_deployment(deployment["id"], DC))

    # settle-end 2026-09-06 -> nights 5; labour round(900*1.35*5)=6075.00;
    # per-diem 0.00 (INDEPENDENT in company housing); housing round(200*2*5)=2000.00;
    # subtotal 8075.00 -> TIER_MID 6% -> 484.50.
    assert_money_equals(settled["final_settled_cost"], 8559.50, "final_settled_cost")
    assert settled["final_settled_cost"] != provisional
    assert_money_equals(settled["provisional_cost"], 18709.00, "provisional_cost")
    assert settled["surge_premium_tier"] == "TIER_MID"
    assert settled["demobilized_at_utc"] == "2026-09-06T00:00:00.000Z"

    refreshed_event = validate_success(api.get_event(event["id"], CM))
    assert_money_equals(
        refreshed_event["deployment_settled_cost"], 8559.50, "deployment_settled_cost"
    )


# ---------------------------------------------------------------------------
# Instance 2 — event_loss_estimate_exposure_based_vs_incurred_development_divergence
# ---------------------------------------------------------------------------
def _event_with_one_triaged_claim(api):
    """CAT-2026-115 DECLARED (HURRICANE/FL, 1000 x 250000 @ 0.0400) carrying one
    TRIAGED claim whose INITIAL_CASE ledger row is 65250.00."""
    event = validate_success(
        api.create_event(
            {
                "cat_code": "CAT-2026-115",
                "peril_type": "HURRICANE",
                "jurisdiction_state": "FL",
                "event_start_utc": "2026-08-01T00:00:00.000Z",
                "exposure_count": 1000,
                "avg_insured_value": 250000,
                "expected_severity_index": 0.0400,
            },
            CM,
        ),
        201,
    )
    validate_success(api.declare_event(event["id"], CM))
    claim = validate_success(
        api.create_claim(
            {
                "policy_number": "POL-7001",
                "loss_state": "FL",
                "loss_date_utc": "2026-07-30T00:00:00.000Z",
                "reported_loss_amount": 120000,
                "coverage_lines": [
                    {
                        "coverage_code": "DWELLING",
                        "limit_amount": 400000,
                        "deductible_amount": 5000,
                        "estimated_damage_amount": 150000,
                    }
                ],
                "event_id": event["id"],
                "access_status": "ACCESSIBLE",
            },
            CE,
        ),
        201,
    )
    triaged = validate_success(api.triage_claim(claim["id"], CE))
    return event, triaged


def test_exposure_based_snapshot_reads_footprint_exposure(api):
    """PRD §3.8: "The `EXPOSURE_BASED` method is the catastrophe-modelling view used
    before enough claims have developed, and it ignores how many claims have
    actually reported. Multiply the event's `exposure_count` by its
    `avg_insured_value`, by its `expected_severity_index`, and by the peril
    development factor — 1.40 for `HURRICANE`, 1.55 for `WILDFIRE`, 1.65 for
    `FLOOD`, 1.20 for `HAIL`, 1.10 for `WINTER_STORM`, 1.80 for `EARTHQUAKE` — to
    obtain the modelled ultimate. The `ibnr_component` is that modelled figure less
    the `reported_component`, floored at 0.00 and rounded to 2 decimal places."
    PRD §3.8: "Both methods share a common base: the `reported_component` is the
    event's `incurred_total`, that is its `case_reserve_total` plus its `paid_total`."
    PRD §3.8: "Each snapshot records `input_reserve_sequence_high_water`, the
    greatest ledger `sequence_no` on the event at snapshot time, or 0 when the event
    had no entries, and `computed_at_utc` at the current logical-clock instant, and
    is born non-stale."

    Design: Difficulty/dual_variant_calc/event_loss_estimate_exposure_based_vs_incurred_development_divergence
    """
    event, claim = _event_with_one_triaged_claim(api)
    assert_money_equals(claim["severity_score"], 35.30, "severity_score")
    assert claim["triage_tier"] == "STANDARD"
    assert_money_equals(claim["case_reserve"], 65250.00, "case_reserve")

    live = validate_success(api.get_event(event["id"], CM))
    snapshot = validate_success(
        api.create_loss_estimate(
            {
                "event_id": event["id"],
                "method": "EXPOSURE_BASED",
                "expected_event_version": live["version"],
            },
            CM,
        ),
        201,
    )

    assert_loss_estimate_snapshot(snapshot)
    assert_money_equals(snapshot["reported_component"], 65250.00, "reported_component")
    # 1000 * 250000 * 0.0400 * 1.40 = 14000000.00 modelled ultimate.
    assert_money_equals(snapshot["ibnr_component"], 13934750.00, "ibnr_component")
    assert_money_equals(snapshot["gross_estimate"], 14000000.00, "gross_estimate")
    assert snapshot["input_reserve_sequence_high_water"] == 1
    assert snapshot["stale"] is False


def test_incurred_development_snapshot_develops_observed_reserves(api):
    """PRD §3.8: "The `INCURRED_DEVELOPMENT` method is the chronological view that
    develops observed reserves forward. Count the distinct claims among the event's
    `INITIAL_CASE` ledger entries to get the reported claim count. Divide the
    `reported_component` by that count — or by 1 when the count is zero — to get the
    average incurred per reported claim. Separately, multiply the event's
    `exposure_count` by its `expected_severity_index` by a report rate of 35 percent
    and round the product **up** to the next whole number to get the ultimate claim
    count; this ceiling is taken on the exact value, never via a floating-point
    shortcut. The `ibnr_component` is the average incurred per claim multiplied by
    the ultimate claim count less the reported claim count (with that difference
    floored at zero), the whole product floored at 0.00 and rounded to 2 decimal
    places."

    Design: Difficulty/dual_variant_calc/event_loss_estimate_exposure_based_vs_incurred_development_divergence
    """
    event, _ = _event_with_one_triaged_claim(api)
    live = validate_success(api.get_event(event["id"], CM))
    snapshot = validate_success(
        api.create_loss_estimate(
            {
                "event_id": event["id"],
                "method": "INCURRED_DEVELOPMENT",
                "expected_event_version": live["version"],
            },
            CM,
        ),
        201,
    )

    assert_loss_estimate_snapshot(snapshot)
    assert_money_equals(snapshot["reported_component"], 65250.00, "reported_component")
    # avg 65250.00; ultimate claim count ceil(1000 * 0.0400 * 0.35) = 14; 14 - 1 = 13.
    assert_money_equals(snapshot["ibnr_component"], 848250.00, "ibnr_component")
    assert_money_equals(snapshot["gross_estimate"], 913500.00, "gross_estimate")


def test_two_methods_diverge_and_event_mirrors_created_at_tie_break_winner(api):
    """PRD §3.8: "For identical stored inputs this yields a different
    `gross_estimate` from the exposure-based method whenever the observed average
    severity per reported claim differs from the modelled per-risk severity."
    PRD §3.1: "`gross_loss_estimate` mirrors the `gross_estimate` of the event's
    latest loss-estimate snapshot — the one with the greatest `computed_at_utc`,
    with ties broken in favour of the earliest `created_at` — and reads 0.00 when
    the event has no snapshot."

    Design: Difficulty/dual_variant_calc/event_loss_estimate_exposure_based_vs_incurred_development_divergence
    """
    event, _ = _event_with_one_triaged_claim(api)

    v1 = validate_success(api.get_event(event["id"], CM))["version"]
    exposure = validate_success(
        api.create_loss_estimate(
            {
                "event_id": event["id"],
                "method": "EXPOSURE_BASED",
                "expected_event_version": v1,
            },
            CM,
        ),
        201,
    )
    v2 = validate_success(api.get_event(event["id"], CM))["version"]
    incurred = validate_success(
        api.create_loss_estimate(
            {
                "event_id": event["id"],
                "method": "INCURRED_DEVELOPMENT",
                "expected_event_version": v2,
            },
            CM,
        ),
        201,
    )

    assert exposure["gross_estimate"] != incurred["gross_estimate"]
    assert_money_equals(exposure["gross_estimate"], 14000000.00, "gross_estimate")
    assert_money_equals(incurred["gross_estimate"], 913500.00, "gross_estimate")
    # The clock never moved, so both snapshots share computed_at_utc and the
    # earliest created_at — the exposure-based row — wins the tie-break.
    assert exposure["computed_at_utc"] == incurred["computed_at_utc"]
    refreshed = get_success_data(api.get_event(event["id"], CM))
    assert_money_equals(refreshed["gross_loss_estimate"], 14000000.00, "gross_loss_estimate")
