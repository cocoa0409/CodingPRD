"""Compensating actions: a money ledger and a unit custody triple, restored exactly."""

from test_helpers import (
    ARCHIVIST_A,
    PRESERV_B,
    assert_budget_ledger,
    assert_custody_triple,
    factories as f,
    fixtures as fx,
    ok,
)

# PRD §2.4 renders every instant the API returns as "an ISO 8601 UTC instant with
# three fractional digits (for example 2025-05-24T10:30:00.123Z)", and §2.10 pins
# instant comparisons at millisecond resolution, so a clock-stamped audit field
# such as checked_out_at / returned_at (§2.5) comes back with the .000 fraction.
CHECK_OUT_INSTANT = "2026-08-15T00:00:00.000Z"


def _plan_with_two_approved_jobs(client):
    """A funded plan carrying 46000 + 175266 == 221266 of committed cost."""
    holding = fx.make_holding(
        client,
        item_specs=[
            {"unit_count": 10, "original_format": "MAGNETIC_TAPE",
             "condition_grade": "GOOD", "sensitivity_level": "INTERNAL"},
            {"unit_count": 40, "original_format": "MAGNETIC_TAPE",
             "condition_grade": "FAIR", "sensitivity_level": "INTERNAL"},
        ],
        schedule_overrides={"retention_years": 19, "disposition_action": "TRANSFER",
                            "min_appraisal_score_for_permanent": 74.00},
        series_overrides={"title": "Plant Safety Films", "business_unit": "EHS",
                          "sensitivity_ceiling": "INTERNAL",
                          "annual_volume_linear_feet": 28,
                          "earliest_record_year": 1981,
                          "latest_record_year": 2002},
        zone_overrides={"zone_code": "AV-COLD-5", "temperature_c": 13.0,
                        "relative_humidity_pct": 37.0,
                        "max_overlapping_migration_jobs": 3},
    )
    plan = fx.make_plan(client, holding.zone_id, budget_cents=300000)
    small = fx.make_job(
        client,
        plan["id"],
        holding.item_ids[0],
        stage="APPROVED",
        units=10,
        target_format="PRESERVATION_MKV",
        window_start="2026-09-05T00:00:00Z",
        window_end="2026-09-15T00:00:00Z",
    )
    large = fx.make_job(
        client,
        plan["id"],
        holding.item_ids[1],
        stage="APPROVED",
        units=40,
        target_format="PRESERVATION_MKV",
        window_start="2026-09-10T00:00:00Z",
        window_end="2026-10-20T00:00:00Z",
    )
    assert small["committed_cost_cents"] == 46000
    assert large["committed_cost_cents"] == 175266
    assert_budget_ledger(fx.read_plan(client, plan["id"]), 221266, 0)
    return plan, small, large


def test_cancelling_an_approved_job_releases_exactly_its_committed_cost(client):
    """PRD §3.6: "From `APPROVED` the job lands in the terminal `CANCELLED`, stores
    `cancel_reason`, and subtracts exactly `committed_cost_cents` from the plan's
    `budget_committed_cents`, restoring the precise pre-approval figure."
    PRD §2.10: "A preservation plan's `budget_committed_cents` must, after every single
    request including every cascade, equal the exact sum of `committed_cost_cents` over
    the migration jobs on that plan whose status is `APPROVED` or `IN_PROGRESS`."

    Design: Difficulty/compensating_invariant/preservation_budget_committed_restored_exactly_by_job_cancellation
    """
    plan, small, large = _plan_with_two_approved_jobs(client)

    cancelled = ok(
        client.cancel_migration_job(
            large["id"],
            PRESERV_B,
            f.cancel_job_payload("Vendor withdrew the reformatting quotation"),
        )
    )
    assert cancelled["status"] == "CANCELLED"
    assert fx.read_job(client, small["id"])["status"] == "APPROVED"
    assert_budget_ledger(fx.read_plan(client, plan["id"]), 46000, 0)


def test_the_cancelled_job_keeps_its_own_cost_and_the_plan_stays_active(client):
    """PRD §2.10: "Jobs in `PENDING_APPROVAL`, `REJECTED` and `CANCELLED` contribute to
    neither figure."
    PRD §2.10: "Its `budget_spent_cents` must equal the exact sum of
    `committed_cost_cents` over the jobs on that plan whose status is `COMPLETED`."
    PRD §2.10: "Because approval commits exactly a job's `committed_cost_cents` and
    cancellation from either `APPROVED` or `IN_PROGRESS` releases exactly the same amount,
    an approve-then-cancel sequence returns `budget_committed_cents` to precisely its
    pre-approval value."

    Design: Difficulty/compensating_invariant/preservation_budget_committed_restored_exactly_by_job_cancellation
    """
    plan, _small, large = _plan_with_two_approved_jobs(client)

    ok(
        client.cancel_migration_job(
            large["id"],
            PRESERV_B,
            f.cancel_job_payload("Vendor withdrew the reformatting quotation"),
        )
    )

    reloaded_job = fx.read_job(client, large["id"])
    assert reloaded_job["committed_cost_cents"] == 175266
    assert reloaded_job["cancel_reason"] == "Vendor withdrew the reformatting quotation"

    reloaded_plan = fx.read_plan(client, plan["id"])
    assert reloaded_plan["budget_cents"] == 300000
    assert reloaded_plan["status"] == "ACTIVE"
    assert_budget_ledger(reloaded_plan, 46000, 0)


def _confirmed_loan_inside_its_window(client):
    """A five-unit item with a confirmed two-unit loan and the clock inside it."""
    holding = fx.make_holding(
        client,
        item_specs=[{"unit_count": 5, "condition_grade": "GOOD",
                     "sensitivity_level": "PUBLIC"}],
        schedule_overrides={"retention_years": 13, "disposition_action": "REVIEW",
                            "min_appraisal_score_for_permanent": 66.00},
        series_overrides={"title": "Centenary Exhibit Collection",
                          "business_unit": "HERITAGE",
                          "sensitivity_ceiling": "PUBLIC",
                          "annual_volume_linear_feet": 7,
                          "earliest_record_year": 1926,
                          "latest_record_year": 1975},
        accession_overrides={"transfer_instrument": "DEED_OF_GIFT"},
    )
    assert_custody_triple(holding.item, 5, 0, 0)
    loan = fx.make_loan(
        client,
        holding.item_id,
        "2026-08-10T00:00:00Z",
        "2026-08-20T00:00:00Z",
        stage="CONFIRMED",
        units=2,
        exhibit_name="Centenary Main Hall",
    )
    fx.set_clock(client, CHECK_OUT_INSTANT)
    return holding, loan


def test_check_out_moves_exactly_the_loan_units_off_the_shelf(client):
    """PRD §3.8: "On success the loan moves to `OUT`, `checked_out_at` is stamped from the
    logical clock, and the item moves `ACCESSIONED → ON_LOAN` with the loan's `units`
    subtracted from `units_on_shelf` and the same number added to `units_on_loan`,
    preserving the conservation identity of §2.10 exactly."
    PRD §2.10: "For every archival item in any status other than `REJECTED_ITEM`,
    `unit_count` must equal `units_on_shelf` plus `units_on_loan` plus
    `units_deaccessioned` after every request."

    Design: Difficulty/compensating_invariant/unit_custody_triple_restored_exactly_by_exhibit_loan_return
    """
    holding, loan = _confirmed_loan_inside_its_window(client)

    out = ok(client.check_out_exhibit_loan(loan["id"], ARCHIVIST_A))
    assert out["status"] == "OUT"
    assert out["checked_out_at"] == CHECK_OUT_INSTANT

    item = fx.read_item(client, holding.item_id)
    assert item["status"] == "ON_LOAN"
    assert_custody_triple(item, 3, 2, 0)


def test_return_restores_the_custody_triple_but_not_the_condition_grade(client):
    """PRD §3.8: "The loan moves to `RETURNED`, `returned_at` is stamped from the logical
    clock, and the item moves `ON_LOAN → ACCESSIONED` with the loan's `units` subtracted
    from `units_on_loan` and the same number added back to `units_on_shelf`, restoring the
    pre-check-out split exactly and with zero drift."
    PRD §3.8: "The archivist supplies `returned_condition_grade`, one of `GOOD`, `FAIR`,
    `POOR` or `UNSTABLE`, which is stored on the loan and also overwrites the item's
    `condition_grade` — a piece returning in worse shape is thereby disqualified from
    future display."
    PRD §2.10: "Checking out an exhibit loan moves units from the shelf column to the loan
    column and returning it moves the identical number back, so the triple is restored
    exactly."

    Design: Difficulty/compensating_invariant/unit_custody_triple_restored_exactly_by_exhibit_loan_return
    """
    holding, loan = _confirmed_loan_inside_its_window(client)
    ok(client.check_out_exhibit_loan(loan["id"], ARCHIVIST_A))

    returned = ok(
        client.return_exhibit_loan(
            loan["id"], f.return_loan_payload("FAIR"), ARCHIVIST_A
        )
    )
    assert returned["status"] == "RETURNED"
    assert returned["returned_at"] == CHECK_OUT_INSTANT
    assert returned["returned_condition_grade"] == "FAIR"

    item = fx.read_item(client, holding.item_id)
    assert item["status"] == "ACCESSIONED"
    assert item["unit_count"] == 5
    assert item["condition_grade"] == "FAIR"
    assert_custody_triple(item, 5, 0, 0)
