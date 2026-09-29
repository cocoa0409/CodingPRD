"""Cycles that re-enter a state they have already occupied, and their ceilings."""

from prd_bench_local_runner.testing import validate_error

from test_helpers import fixtures as fx
from test_helpers import test_users as users
from test_helpers.api_errors import (
    ERR_REVISION_LIMIT_EXCEEDED,
    ERR_REWORK_LIMIT_EXCEEDED,
)
from test_helpers.assertions import (
    assert_cents,
    assert_fields,
    assert_score,
    updated,
)
from test_helpers.factories import determination_decision_payload, job_review_payload


def _submitted_determination(api):
    """A SUBMITTED determination authored by the field inspector, revision_round 0."""
    operator = fx.make_operator(
        api, name="Sandhill Petroleum", region_code="TX", bond_amount_cents=5000000
    )
    well = fx.make_well(api, operator["id"], spud_year=1972, total_depth_ft=3100)
    determination = fx.open_determination(
        api, well["id"], inspector_notes="first pass field notes"
    )
    determination = fx.submit_determination(api, determination["id"])
    return {"operator": operator, "well": well, "determination": determination}


def test_a_third_revision_request_is_refused_at_the_declared_ceiling(api):
    """Two revision cycles are allowed and the third request is refused.

    The counter advances only when the case is re-submitted, so it reads 0, then 1
    after the first re-submission and 2 after the second; the third request finds it
    already at 2, answers 422, and leaves the row SUBMITTED with the counter untouched.

    PRD: "A revision may be requested at most twice on one determination; a third
    request, made when `revision_round` already stands at 2, is rejected with
    `ERR_REVISION_LIMIT_EXCEEDED` (HTTP 422)."

    Design: Difficulty/non_linear_state_machine/determination_revision_cycle_reenters_submitted_twice_then_hits_limit
    """
    bundle = _submitted_determination(api)
    det_id = bundle["determination"]["id"]
    assert_fields(bundle["determination"], status="SUBMITTED", revision_round=0)

    first = fx.decide_determination(
        api, det_id, "REQUEST_REVISION", "attach groundwater survey"
    )
    assert_fields(first, status="REVISION_REQUESTED", revision_round=0)

    resubmitted = fx.submit_determination(api, det_id)
    assert_fields(resubmitted, status="SUBMITTED", revision_round=1)

    second = fx.decide_determination(
        api, det_id, "REQUEST_REVISION", "surface acreage still unmeasured"
    )
    assert_fields(second, status="REVISION_REQUESTED", revision_round=1)

    resubmitted_again = fx.submit_determination(api, det_id)
    assert_fields(resubmitted_again, status="SUBMITTED", revision_round=2)

    refused = api.decide_orphan_determination(
        det_id,
        determination_decision_payload(
            "REQUEST_REVISION", "third bite at the apple - must be rejected"
        ),
        users.REVIEWER,
    )
    validate_error(refused, ERR_REVISION_LIMIT_EXCEEDED)

    after = updated(api.get_orphan_determination(det_id, users.REVIEWER))
    assert_fields(after, status="SUBMITTED", revision_round=2)
    assert_fields(fx.read_well(api, bundle["well"]["id"]), status="ORPHAN_CANDIDATE")


def test_reentering_submitted_refreezes_the_criteria_snapshots(api):
    """SUBMITTED is reached a second time by a different edge and re-snapshots.

    The first submission freezes idle_months 999 and a zero de-minimis figure. The
    revision request sends the case back without demoting the well, a production month
    is then filed, and the re-submission freezes the new figures instead - 1 idle month
    and 10.00 barrels of oil equivalent - while the screening snapshot stays 59.90.

    PRD: "`REQUEST_REVISION` sends the case back: `status` becomes
    `REVISION_REQUESTED` and the well is deliberately **left** at `ORPHAN_CANDIDATE`,
    because the classification is still pending rather than resolved."

    Design: Difficulty/non_linear_state_machine/determination_revision_cycle_reenters_submitted_twice_then_hits_limit
    """
    bundle = _submitted_determination(api)
    det_id = bundle["determination"]["id"]
    well_id = bundle["well"]["id"]

    assert_fields(bundle["determination"], snapshot_idle_months=999)
    assert_score(
        bundle["determination"]["snapshot_screening_score"], 59.90, "snapshot_screening_score"
    )
    assert_score(
        bundle["determination"]["snapshot_cumulative_boe_60mo"],
        0,
        "snapshot_cumulative_boe_60mo",
    )
    assert_fields(fx.read_well(api, well_id), status="ORPHAN_CANDIDATE")

    sent_back = fx.decide_determination(
        api, det_id, "REQUEST_REVISION", "attach groundwater survey"
    )
    assert_fields(sent_back, status="REVISION_REQUESTED")
    assert_fields(fx.read_well(api, well_id), status="ORPHAN_CANDIDATE")

    fx.report_production(api, well_id, "2026-07", oil_bbl=10.0, gas_mcf=0)

    resubmitted = fx.submit_determination(api, det_id)
    assert_fields(resubmitted, status="SUBMITTED", revision_round=1, snapshot_idle_months=1)
    assert_score(
        resubmitted["snapshot_cumulative_boe_60mo"], 10.00, "snapshot_cumulative_boe_60mo"
    )
    assert_score(
        resubmitted["snapshot_screening_score"], 59.90, "snapshot_screening_score"
    )
    assert_fields(fx.read_well(api, well_id), status="ORPHAN_CANDIDATE")


def test_a_third_rework_order_is_refused_at_the_declared_ceiling(api):
    """Two rework turns are allowed and each one bills its own round cost.

    The first report costs 6328179, and the two rework rounds each add 2275505, taking
    the cumulative actual cost to 8603684 and then 10879189. The third rework order
    finds the counter already at 2, answers 422, and leaves the job FIELD_REPORTED.

    PRD: "this is permitted only while `rework_round` is still below the ceiling of 2
    completed rework cycles, and a third attempt made when `rework_round` already
    stands at 2 is rejected with `ERR_REWORK_LIMIT_EXCEEDED` (HTTP 422)."

    Design: Difficulty/non_linear_state_machine/plugging_job_rework_cycle_reenters_field_reported_twice_then_hits_limit
    """
    bundle = fx.make_scheduled_job(api, scheduled_start="2026-09-01T00:00:00Z")
    job_id = bundle["job"]["id"]
    fx.mobilize(api, job_id)

    reported = fx.file_field_report(
        api,
        job_id,
        downhole_conditions="as planned",
        plug_intervals=[
            {"top_ft": 2200, "bottom_ft": 2500, "sacks": 60},
            {"top_ft": 0, "bottom_ft": 100, "sacks": 40},
        ],
    )
    assert_cents(reported["last_round_cost_cents"], 6328179, "round one cost")
    assert_cents(reported["actual_cost_cents"], 6328179, "cumulative actual cost")

    rework_report = dict(
        cement_sacks_used=20,
        rig_days_used=1,
        casing_removed_ft=0,
        downhole_conditions="upper plug re-set with returns",
        plug_intervals=[{"top_ft": 0, "bottom_ft": 60, "sacks": 20}],
    )

    first_rework = fx.review_job(
        api, job_id, "REWORK", "no cement returns documented on the upper plug"
    )
    assert_fields(first_rework, status="REWORK_REQUIRED", rework_round=1)

    second = fx.file_field_report(api, job_id, **rework_report)
    assert_fields(second, status="FIELD_REPORTED")
    assert_cents(second["last_round_cost_cents"], 2275505, "round two cost")
    assert_cents(second["actual_cost_cents"], 8603684, "cumulative actual cost")

    second_rework = fx.review_job(api, job_id, "REWORK", "tag test still not documented")
    assert_fields(second_rework, status="REWORK_REQUIRED", rework_round=2)

    third = fx.file_field_report(api, job_id, **rework_report)
    assert_cents(third["last_round_cost_cents"], 2275505, "round three cost")
    assert_cents(third["actual_cost_cents"], 10879189, "cumulative actual cost")

    refused = api.review_plugging_job(
        job_id,
        job_review_payload("REWORK", "third rework attempt - must be rejected"),
        users.ADMIN,
    )
    validate_error(refused, ERR_REWORK_LIMIT_EXCEEDED)

    after = updated(api.get_plugging_job(job_id, users.ADMIN))
    assert_fields(after, status="FIELD_REPORTED", rework_round=2)

    contract = updated(
        api.get_unit_cost_contract(bundle["contract"]["id"], users.PROCUREMENT)
    )
    assert_cents(contract["obligated_cents"], 10879189, "obligated_cents")
    assert_fields(contract, status="ACTIVE")


def test_the_rework_cycle_accumulates_cost_and_still_ends_in_acceptance(api):
    """FIELD_REPORTED is reached from MOBILIZED and then again from REWORK_REQUIRED.

    The re-entry is cost bearing rather than idempotent: the second round adds its own
    2275505 on top of the first round's 6328179 instead of replacing it, and the job
    can then be accepted straight out of the second FIELD_REPORTED with the counter
    left at one completed cycle.

    PRD: "The operations cycle `FIELD_REPORTED → REWORK_REQUIRED → FIELD_REPORTED` is
    therefore bounded at two turns."

    Design: Difficulty/non_linear_state_machine/plugging_job_rework_cycle_reenters_field_reported_twice_then_hits_limit
    """
    bundle = fx.make_scheduled_job(api, scheduled_start="2026-09-01T00:00:00Z")
    job_id = bundle["job"]["id"]
    fx.mobilize(api, job_id)

    first = fx.file_field_report(api, job_id, downhole_conditions="as planned")
    assert_fields(first, status="FIELD_REPORTED", rework_round=0)
    assert_cents(first["actual_cost_cents"], 6328179, "cumulative actual cost")

    fx.review_job(api, job_id, "REWORK", "surface plug top too deep")
    second = fx.file_field_report(
        api,
        job_id,
        cement_sacks_used=20,
        rig_days_used=1,
        casing_removed_ft=0,
        downhole_conditions="surface plug re-set 0-60 ft",
        plug_intervals=[{"top_ft": 0, "bottom_ft": 60, "sacks": 20}],
    )
    assert_fields(second, status="FIELD_REPORTED", rework_round=1)
    assert_cents(second["last_round_cost_cents"], 2275505, "round two cost")
    assert_cents(second["actual_cost_cents"], 8603684, "cumulative actual cost")

    accepted = fx.review_job(api, job_id, "ACCEPT", "plugs verified by tag")
    assert_fields(accepted, status="PLUGGED", rework_round=1)
    assert_cents(
        accepted["actual_cost_cents"], 8603684, "cumulative actual cost after acceptance"
    )
    assert_cents(accepted["last_round_cost_cents"], 2275505, "last round cost retained")
