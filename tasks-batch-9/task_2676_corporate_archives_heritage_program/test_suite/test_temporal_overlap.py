"""Two occupancy rules with deliberately opposite interval geometry."""

from test_helpers import (
    DIRECTOR_A,
    PRESERV_B,
    assert_total_count,
    created,
    factories as f,
    failed,
    fixtures as fx,
    ok,
)
from test_helpers.api_errors import (
    ERR_LOAN_WINDOW_CONFLICT,
    ERR_ZONE_MIGRATION_CAPACITY_EXCEEDED,
)

L1_START = "2026-09-01T00:00:00Z"
L1_END = "2026-09-30T00:00:00Z"
# PRD §2.4 renders every instant the API returns as "an ISO 8601 UTC instant with
# three fractional digits (for example 2025-05-24T10:30:00.123Z)", and §2.10 pins
# instant comparisons at millisecond resolution, so the derived recovery_until of
# §3.8 comes back with the .000 fraction.
L1_RECOVERY = "2026-11-14T00:00:00.000Z"


def _item_with_an_incumbent_loan(client):
    """One shelved item carrying a single REQUESTED loan over September."""
    holding = fx.make_holding(
        client,
        item_specs=[{"unit_count": 5, "condition_grade": "GOOD",
                     "sensitivity_level": "PUBLIC"}],
        schedule_overrides={"retention_years": 16, "disposition_action": "REVIEW",
                            "min_appraisal_score_for_permanent": 67.00},
        series_overrides={"title": "Founder Artefacts", "business_unit": "HERITAGE",
                          "sensitivity_ceiling": "PUBLIC",
                          "annual_volume_linear_feet": 6,
                          "earliest_record_year": 1912,
                          "latest_record_year": 1960},
        accession_overrides={"transfer_instrument": "DEED_OF_GIFT"},
    )
    loan = fx.make_loan(
        client,
        holding.item_id,
        L1_START,
        L1_END,
        units=1,
        exhibit_name="Autumn Heritage Display",
    )
    assert loan["status"] == "REQUESTED"
    assert loan["recovery_until"] == L1_RECOVERY
    return holding, loan


def test_a_window_falling_inside_the_light_recovery_buffer_still_conflicts(client):
    """PRD §3.8: "The loan is created in `status` `REQUESTED` with
    `returned_condition_grade`, `checked_out_at` and `returned_at` null, and its
    `recovery_until` derived as `window_end` plus a 45-day light-recovery buffer — the
    effective end of this loan's occupation of the item, during which the material rests
    out of the light."
    PRD §3.8: "An existing loan's occupation, however, runs from its own `window_start`
    up to but not including its `window_end` plus the 45-day recovery buffer — the buffer
    is appended to the end only, never to the front."
    PRD §3.8: "The new loan conflicts with a candidate when the new window's start falls
    strictly before that candidate's buffered end **and** that candidate's start falls
    strictly before the new window's end."

    Design: Difficulty/resource_temporal_overlap/exhibit_loan_half_open_window_plus_light_recovery_buffer_on_item
    """
    holding, _loan = _item_with_an_incumbent_loan(client)

    failed(
        client.create_exhibit_loan(
            f.exhibit_loan_payload(
                holding.item_id,
                "2026-10-15T00:00:00Z",
                "2026-10-20T00:00:00Z",
                units=1,
                exhibit_name="October Pop-up (inside buffer)",
            ),
            DIRECTOR_A,
        ),
        ERR_LOAN_WINDOW_CONFLICT,
        409,
    )

    rows = assert_total_count(
        client.list_exhibit_loans(DIRECTOR_A, {"archival_item_id": holding.item_id}), 1
    )
    assert len(rows) == 1


def test_touching_the_front_and_starting_at_the_recovery_end_are_both_accepted(client):
    """PRD §3.8: "A display window is **half-open**: it includes its `window_start` and
    excludes its `window_end`."
    PRD §3.8: "Three consequences of this geometry are worth spelling out: a new window
    starting at the exact instant an existing loan's `window_end` falls **does** conflict,
    because it lands inside the recovery buffer; a new window ending at the exact instant
    an existing loan's `window_start` falls does **not** conflict, because the new window
    is half-open at its end and no buffer is applied to the front of the existing loan;
    and a new window starting exactly 45 days after an existing loan's `window_end` does
    **not** conflict, because the comparison against the buffered end is strict."

    Design: Difficulty/resource_temporal_overlap/exhibit_loan_half_open_window_plus_light_recovery_buffer_on_item
    """
    holding, _loan = _item_with_an_incumbent_loan(client)

    front = created(
        client.create_exhibit_loan(
            f.exhibit_loan_payload(
                holding.item_id,
                "2026-08-01T00:00:00Z",
                L1_START,
                units=1,
                exhibit_name="August Preview (touching front)",
            ),
            DIRECTOR_A,
        )
    )
    assert front["status"] == "REQUESTED"
    assert front["recovery_until"] == "2026-10-16T00:00:00.000Z"

    after = created(
        client.create_exhibit_loan(
            f.exhibit_loan_payload(
                holding.item_id,
                L1_RECOVERY,
                "2026-11-20T00:00:00Z",
                units=1,
                exhibit_name="November Reopening (at recovery end)",
            ),
            DIRECTOR_A,
        )
    )
    assert after["status"] == "REQUESTED"

    assert_total_count(
        client.list_exhibit_loans(DIRECTOR_A, {"archival_item_id": holding.item_id}), 3
    )
    assert fx.read_item(client, holding.item_id)["units_on_shelf"] == 5


def _zone_with_two_touching_windows(client):
    """A ceiling-2 zone holding one approved job and two unapproved ones."""
    tape = {"unit_count": 10, "original_format": "MAGNETIC_TAPE",
            "condition_grade": "GOOD", "sensitivity_level": "INTERNAL"}
    holding = fx.make_holding(
        client,
        item_specs=[dict(tape), dict(tape), dict(tape)],
        schedule_overrides={"retention_years": 21, "disposition_action": "TRANSFER",
                            "min_appraisal_score_for_permanent": 72.00},
        series_overrides={"title": "Regional Broadcast Archive",
                          "business_unit": "COMMS",
                          "sensitivity_ceiling": "INTERNAL",
                          "annual_volume_linear_feet": 30,
                          "earliest_record_year": 1982,
                          "latest_record_year": 2004},
        zone_overrides={"zone_code": "AV-COLD-4", "temperature_c": 12.5,
                        "relative_humidity_pct": 36.0,
                        "max_overlapping_migration_jobs": 2},
    )
    plan = fx.make_plan(client, holding.zone_id, budget_cents=500000)
    windows = [
        ("2026-09-01T00:00:00Z", "2026-09-30T00:00:00Z"),
        ("2026-09-30T00:00:00Z", "2026-10-31T00:00:00Z"),
        ("2026-09-25T00:00:00Z", "2026-10-05T00:00:00Z"),
    ]
    jobs = [
        fx.make_job(
            client,
            plan["id"],
            item_id,
            units=10,
            target_format="PRESERVATION_MKV",
            window_start=start,
            window_end=end,
        )
        for item_id, (start, end) in zip(holding.item_ids, windows)
    ]
    assert all(job["committed_cost_cents"] == 46000 for job in jobs)
    ok(client.approve_migration_job(jobs[0]["id"], PRESERV_B))
    return plan, jobs


def test_two_touching_migration_windows_may_sit_exactly_on_the_zone_ceiling(client):
    """PRD §3.6: "A migration window is treated as **closed on both ends**, so two
    windows that merely touch — one ending at the exact instant another begins — do
    overlap."
    PRD §3.6: "The approval is refused with `ERR_ZONE_MIGRATION_CAPACITY_EXCEEDED` only
    when that peak is strictly greater than the zone's `max_overlapping_migration_jobs`;
    a peak exactly equal to the ceiling is permitted."

    Design: Difficulty/resource_temporal_overlap/zone_migration_closed_interval_aggregate_capacity_ceiling
    """
    plan, jobs = _zone_with_two_touching_windows(client)

    second = ok(client.approve_migration_job(jobs[1]["id"], PRESERV_B))
    assert second["status"] == "APPROVED"

    reloaded = fx.read_plan(client, plan["id"])
    assert reloaded["budget_committed_cents"] == 92000
    assert reloaded["budget_spent_cents"] == 0


def test_a_straddling_third_job_pushes_the_peak_past_the_zone_ceiling(client):
    """PRD §3.6: "**Zone treatment capacity** is an aggregate rule, not a pairwise one:
    windows in a zone are allowed to overlap freely until the number of jobs covering
    some single instant would exceed the zone's ceiling."
    PRD §3.6: "The candidate set is every other migration job whose item shares the zone
    and whose status is `APPROVED` or `IN_PROGRESS`; jobs in `PENDING_APPROVAL`,
    `COMPLETED`, `CANCELLED` and `REJECTED` occupy nothing."
    PRD §2.6: "33. **Zone treatment capacity** — inserting this job's treatment window
    must not push the zone's simultaneous approved-or-in-progress job count above
    `max_overlapping_migration_jobs` at any instant."

    Design: Difficulty/resource_temporal_overlap/zone_migration_closed_interval_aggregate_capacity_ceiling
    """
    plan, jobs = _zone_with_two_touching_windows(client)
    ok(client.approve_migration_job(jobs[1]["id"], PRESERV_B))

    failed(
        client.approve_migration_job(jobs[2]["id"], PRESERV_B),
        ERR_ZONE_MIGRATION_CAPACITY_EXCEEDED,
        409,
    )

    third = fx.read_job(client, jobs[2]["id"])
    assert third["status"] == "PENDING_APPROVAL"
    assert third["approved_by"] is None

    reloaded = fx.read_plan(client, plan["id"])
    assert reloaded["budget_committed_cents"] == 92000
    assert reloaded["budget_spent_cents"] == 0
