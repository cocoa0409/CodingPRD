"""Pinned evaluation and rounding order in the fee, cost and score formulas."""

import pytest

from test_helpers import (
    ARCHIVIST_A,
    DIRECTOR_A,
    OFFICER_A,
    OFFICER_B,
    OFFICER_B_ID,
    PRESERV_A,
    assert_score_2dp,
    created,
    factories as f,
    fixtures as fx,
    ok,
)


def _three_line_media_request(client):
    """A MEDIA request over 2 + 2 + 6 units, screened GRANT_FULL by officer-a."""
    holding = fx.make_holding(
        client,
        item_specs=[
            {"unit_count": 2, "original_format": "PHOTO", "sensitivity_level": "INTERNAL"},
            {"unit_count": 2, "original_format": "PHOTO", "sensitivity_level": "INTERNAL"},
            {"unit_count": 6, "original_format": "PHOTO", "sensitivity_level": "INTERNAL"},
        ],
        series_overrides={"sensitivity_ceiling": "INTERNAL",
                          "earliest_record_year": 1980,
                          "latest_record_year": 2005},
    )
    case = fx.screened_case(
        client,
        holding,
        decision="GRANT_FULL",
        redaction_required=False,
        requester_overrides={"requester_class": "MEDIA", "nda_on_file": False},
        screener=OFFICER_A,
    )
    return holding, case


def test_service_fee_rounds_each_line_before_summation(client):
    """PRD §3.7: "`requested_page_count` is eleven pages for every unit in the
    requested items — that is, eleven multiplied by the sum of `unit_count` across the
    items named in `requested_item_ids`."
    PRD §3.7: "A single volume tier is selected once from that total and applied to
    every line: no discount when the total is 100 pages or fewer, 7.5 percent when it
    lies between 101 and 500 pages inclusive, and 12.5 percent when it is 501 pages or
    more."
    PRD §3.7: "Each line's billable amount is its gross amount multiplied by one minus
    the tier rate, **rounded half up to whole cents at that point, before any
    summation**; the alternative of summing the gross amounts first and rounding once
    at the end is explicitly not used and will produce off-by-one-cent answers."
    PRD §3.7: "`service_fee_cents` is that subtotal plus a base handling charge of
    2,500 cents, plus a media licensing surcharge of 15,000 cents when and only when
    the requester's class is `MEDIA`."

    Design: Difficulty/combinatorial_formula/access_service_fee_per_line_rounding_order_pinned
    """
    _, case = _three_line_media_request(client)
    assert case.request["requested_page_count"] == 110

    approved = ok(
        client.approve_access_request(
            case.request_id, f.approve_request_payload("FULL"), OFFICER_B
        )
    )
    assert approved["service_fee_cents"] == 26659


def test_full_approval_stamps_scope_and_decider_on_the_request(client):
    """PRD §3.7: "The `approval_scope` supplied on an approval determines the
    destination: `FULL` drives `SCREENING → APPROVED`, and `REDACTED` drives
    `SCREENING → PARTIALLY_APPROVED`."
    PRD §3.7: "Both branches stamp `decided_by` from `X-User-ID`, store the supplied
    `approval_scope`, and compute and store `service_fee_cents`."
    PRD §3.7: "On top of that, a `FULL` approval requires `post_screen_risk_score` to
    be strictly below 75; at 75 or above, the only permitted outcome is a `REDACTED`
    approval, and an attempt at full scope is refused with
    `ERR_RISK_THRESHOLD_REQUIRES_REDACTION`."

    Design: Difficulty/combinatorial_formula/access_service_fee_per_line_rounding_order_pinned
    """
    _, case = _three_line_media_request(client)
    assert case.request["post_screen_risk_score"] == 60

    approved = ok(
        client.approve_access_request(
            case.request_id, f.approve_request_payload("FULL"), OFFICER_B
        )
    )
    assert approved["status"] == "APPROVED"
    assert approved["approval_scope"] == "FULL"
    assert approved["decided_by"] == OFFICER_B_ID


def _tape_pallet_plan(client):
    """An active plan over a cold zone holding 40 FAIR magnetic-tape units."""
    holding = fx.make_holding(
        client,
        item_specs=[{"unit_count": 40, "condition_grade": "FAIR",
                     "original_format": "MAGNETIC_TAPE",
                     "sensitivity_level": "INTERNAL"}],
        zone_overrides={"temperature_c": 12.0, "relative_humidity_pct": 35.0,
                        "max_overlapping_migration_jobs": 2},
        series_overrides={"earliest_record_year": 1988, "latest_record_year": 2001},
    )
    plan = fx.make_plan(
        client, holding.zone_id, budget_cents=300000, plan_name="AV Reformatting 2026"
    )
    return holding, plan



def test_migration_cost_waterfall_freezes_all_six_steps_in_order(client):
    """PRD §3.6: "Step one sets `subtotal_cents` to the per-unit rate for the item's
    `original_format` multiplied by the job's `units`."
    PRD §3.6: "Step two selects `volume_discount_pct` from `subtotal_cents` and from
    nothing else: 0.00 when the subtotal is 50,000 cents or less, 0.06 when it lies
    between 50,001 and 200,000 cents inclusive, and 0.11 when it is 200,001 cents or
    more."
    PRD §3.6: "Step four selects `handling_fee_cents` from the step-three output: 1,500
    cents when `discounted_cents` is 25,000 or less, 4,000 cents when it lies between
    25,001 and 100,000 inclusive, and 9,000 cents when it is 100,001 or more."
    PRD §3.6: "Step six sets `committed_cost_cents` to `discounted_cents` plus
    `handling_fee_cents` plus `condition_surcharge_cents`."

    Design: Difficulty/combinatorial_formula/migration_job_cost_six_step_order_pinned
    """
    holding, plan = _tape_pallet_plan(client)

    job = created(
        client.create_migration_job(
            f.migration_job_payload(
                plan["id"], holding.item_id, units=40,
                target_format="PRESERVATION_MKV",
            ),
            PRESERV_A,
        )
    )
    assert job["subtotal_cents"] == 168000
    assert job["volume_discount_pct"] == pytest.approx(0.06, abs=0.001)
    assert job["discounted_cents"] == 157920
    assert job["handling_fee_cents"] == 9000
    assert job["condition_surcharge_cents"] == 8346
    assert job["committed_cost_cents"] == 175266


def test_job_creation_commits_no_money_against_the_plan(client):
    """PRD §3.6: "The job is created in `status` `PENDING_APPROVAL` with `requested_by`
    stamped from `X-User-ID`, `approved_by` and `cancel_reason` null."
    PRD §2.10: "A preservation plan's `budget_committed_cents` must, after every single
    request including every cascade, equal the exact sum of `committed_cost_cents` over
    the migration jobs on that plan whose status is `APPROVED` or `IN_PROGRESS`."
    PRD §3.6: "**The at-risk census** sums `unit_count` over every archival item whose
    `storage_zone_id` matches the plan's zone, whose status is one of `UNPROCESSED`,
    `ACCESSIONED` or `IN_TREATMENT`, whose `original_format` is `MAGNETIC_TAPE` or
    `FILM`, and whose `digital_surrogate_available` is false."

    Design: Difficulty/combinatorial_formula/migration_job_cost_six_step_order_pinned
    """
    holding, plan = _tape_pallet_plan(client)

    job = created(
        client.create_migration_job(
            f.migration_job_payload(
                plan["id"], holding.item_id, units=40,
                target_format="PRESERVATION_MKV",
            ),
            PRESERV_A,
        )
    )
    assert job["status"] == "PENDING_APPROVAL"
    assert job["approved_by"] is None

    reloaded = fx.read_plan(client, plan["id"])
    assert reloaded["budget_committed_cents"] == 0
    assert reloaded["at_risk_unit_count"] == 40


def _board_minute_books(client):
    """An 80-year span sitting exactly on the volume-penalty floor."""
    schedule = fx.make_schedule(
        client,
        retention_years=7,
        disposition_action="REVIEW",
        min_appraisal_score_for_permanent=80.00,
    )
    series = fx.make_series(
        client,
        schedule["id"],
        title="Board Minute Books",
        business_unit="CORP",
        sensitivity_ceiling="CONFIDENTIAL",
        annual_volume_linear_feet=50,
        earliest_record_year=1901,
        latest_record_year=1980,
    )
    appraisal = fx.make_appraisal(
        client,
        series,
        informational_value=8,
        evidential_value=7,
        brand_heritage_value=6,
        uniqueness_factor=5,
        provenance_verified=True,
    )
    return series, appraisal


def test_age_bonus_cap_and_volume_penalty_floor_interact_at_screening(client):
    """PRD §3.2: "The age bonus is one point for every complete five years of that
    span, discarding any remainder, capped at 10 points."
    PRD §3.2: "The volume penalty is zero when the series accrues 50 linear feet per
    year or less; above that floor it is one point for every complete 10 linear feet by
    which the annual volume exceeds 50, again discarding any remainder, capped at 15
    points and never negative."
    PRD §3.2: "The raw score is the core plus the age bonus minus the volume penalty,
    clamped into the range 0 through 100 inclusive."

    Design: Difficulty/combinatorial_formula/appraisal_score_nested_min_floor_clamp_interaction
    """
    _, appraisal = _board_minute_books(client)

    screened = ok(client.screen_appraisal(appraisal["id"], ARCHIVIST_A))
    assert_score_2dp(screened, "screening_score", 77.00)


def test_final_pass_drops_uncertified_brand_value_from_the_same_score(client):
    """PRD §3.2: "The screening variant and the final variant differ on exactly two
    inputs."
    PRD §3.2: "Packages in `DRAFT` or `REJECTED` status are ignored entirely."
    PRD §3.2: "Disposition derivation runs only in the final pass."

    Design: Difficulty/combinatorial_formula/appraisal_score_nested_min_floor_clamp_interaction
    """
    series, appraisal = _board_minute_books(client)
    ok(client.screen_appraisal(appraisal["id"], ARCHIVIST_A))

    finalized = ok(client.finalize_appraisal(appraisal["id"], DIRECTOR_A))
    assert_score_2dp(finalized, "final_score", 65.00)
    assert finalized["brand_heritage_counted"] is False
    assert finalized["recommended_disposition"] == "REVIEW"
    assert fx.read_series(client, series["id"])["disposition_state"] == (
        "ELIGIBLE_FOR_DISPOSITION"
    )
