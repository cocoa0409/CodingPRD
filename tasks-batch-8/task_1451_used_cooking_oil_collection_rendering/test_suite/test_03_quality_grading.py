"""Quality sampling, laboratory grading, and completion consistency tests."""
from datetime import datetime, timezone

import pytest

from test_helpers import (
    ApiErrorId,
    complete_visit,
    get_success_data,
    make_driver_headers,
    set_clock,
    setup_completed_visit,
    setup_dispatched_single_stop,
    start_visit,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import DISP, FOPS, PLANT


# ---------------------------------------------------------------------------
# Corner: immediate consistency of the complete response
# ---------------------------------------------------------------------------

def test_complete_response_carries_computed_net_gallons(api):
    """PRD §3.5: "On completion the system computes `net_gallons_provisional` —
    the pump gallons multiplied by one minus the field moisture fraction,
    rounded half-up to two decimal places — stamps `completed_at` from the
    logical clock"

    Design: Corner/consistency/c_immediate_consistency_complete_response
    """
    ctx = setup_dispatched_single_stop(
        name="Imm House", truck_plate="T-C21", container_fill_rate=200
    )
    set_clock("2026-08-05T08:00:00Z")
    start_visit(ctx["visit"]["id"])
    resp = api.complete_pickup_visit(
        ctx["visit"]["id"],
        {"pump_gallons": 200.00, "field_moisture_pct": 8.0},
        make_driver_headers("drv-1"),
    )
    data = validate_success(resp, expected_status=200)
    assert data["status"] == "COMPLETED"
    assert data["net_gallons_provisional"] == pytest.approx(184.00, abs=0.001), (
        "200 x (1 - 8.0/100) == 184.00"
    )
    # PRD pins the stamp to the logical-clock instant but not its fractional-
    # digit serialization; compare instants, not strings.
    completed_at = datetime.fromisoformat(data["completed_at"].replace("Z", "+00:00"))
    assert completed_at == datetime(2026, 8, 5, 8, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Corner: sample re-grade requires dispute
# ---------------------------------------------------------------------------

def _submitted_sample_setup(api):
    ctx = setup_completed_visit(name="Sample House", truck_plate="T-C4")
    sample = get_success_data(
        api.create_sample(ctx["visit"]["id"], make_driver_headers("drv-1"))
    )
    get_success_data(api.submit_sample(sample["id"], make_driver_headers("drv-1")))
    return ctx, sample


def test_grade_on_graded_sample_rejected_until_disputed(api):
    """PRD §3.6: "Grading a sample that is already `GRADED` is rejected with
    `ERR_SAMPLE_ALREADY_GRADED` — the only legitimate path back through the lab
    is a dispute."

    Design: Corner/state_machines/c_sample_regrade_requires_dispute
    """
    _, sample = _submitted_sample_setup(api)
    get_success_data(
        api.grade_sample(
            sample["id"],
            {"lab_moisture_pct": 16.0, "lab_impurity_pct": 1.0},
            PLANT,
        )
    )
    resp = api.grade_sample(
        sample["id"],
        {"lab_moisture_pct": 4.0, "lab_impurity_pct": 1.0},
        PLANT,
    )
    validate_error(resp, ApiErrorId.ERR_SAMPLE_ALREADY_GRADED, expected_status=409)


def test_dispute_then_regrade_overwrites_grade(api):
    """PRD §3.6: "A `FieldOpsManager` disputes a graded sample by supplying a
    `note`, persisted as `dispute_note`, which moves the sample `GRADED` →
    `DISPUTED`. Grading a `DISPUTED` sample recomputes and overwrites the
    grade, returning the sample to `GRADED`."

    Design: Corner/state_machines/c_sample_regrade_requires_dispute
    """
    _, sample = _submitted_sample_setup(api)
    graded = get_success_data(
        api.grade_sample(
            sample["id"],
            {"lab_moisture_pct": 16.0, "lab_impurity_pct": 1.0},
            PLANT,
        )
    )
    assert graded["grade"] == "C"
    get_success_data(
        api.dispute_sample(sample["id"], {"note": "lab rerun requested"}, FOPS)
    )
    regraded = get_success_data(
        api.grade_sample(
            sample["id"],
            {"lab_moisture_pct": 4.0, "lab_impurity_pct": 1.0},
            PLANT,
        )
    )
    assert regraded["grade"] == "A", "re-grade after dispute overwrites C with A"


# ---------------------------------------------------------------------------
# Difficulty: moisture boundary 15.00 -> C, 14.99 -> B
# ---------------------------------------------------------------------------

def _moisture_boundary_setup(api):
    """Two visits completed pump 100.00 field 5.0; one submitted sample each."""
    set_clock("2026-08-02T00:00:00Z")
    from test_helpers import (
        create_container,
        create_manifest,
        create_truck,
        dispatch_manifest,
        manifest_visits,
        container_visits,
    )
    from test_helpers.fixtures import create_active_customer

    customer, _ = create_active_customer(name="Boundary House")
    ctn1 = create_container(customer["id"], capacity=300, fill_rate=100,
                            lock_code="LKB1")
    ctn2 = create_container(customer["id"], capacity=300, fill_rate=100,
                            lock_code="LKB2")
    truck = create_truck(plate="T-9", tank_capacity=500)
    manifest = create_manifest(
        truck["id"], [ctn1["id"], ctn2["id"]], service_date="2026-08-05"
    )
    dispatch_manifest(manifest["id"], start_level=0)
    v1 = container_visits(ctn1["id"])[0]
    v2 = container_visits(ctn2["id"])[0]
    set_clock("2026-08-05T08:00:00Z")
    start_visit(v1["id"])
    complete_visit(v1["id"], pump_gallons=100.00, field_moisture_pct=5.0)
    start_visit(v2["id"])
    complete_visit(v2["id"], pump_gallons=100.00, field_moisture_pct=5.0)
    smp1 = get_success_data(api.create_sample(v1["id"], make_driver_headers("drv-1")))
    get_success_data(api.submit_sample(smp1["id"], make_driver_headers("drv-1")))
    smp2 = get_success_data(api.create_sample(v2["id"], make_driver_headers("drv-1")))
    get_success_data(api.submit_sample(smp2["id"], make_driver_headers("drv-1")))
    return smp1, smp2


def test_moisture_exactly_1500_grades_c(api):
    """PRD §3.6: "The moisture dimension is `A` when lab moisture is below 5.0,
    `B` when below 15.0, `C` when below 25.0, and `REJECT` at 25.0 or above."
    PRD §3.6: "Every threshold band is lower-bound inclusive and upper-bound
    exclusive: a lab moisture of exactly 15.00 lands in `C`, and a lab impurity
    of exactly 2.00 lands in `B`."

    Design: Difficulty/boundary_precision_check/moisture_boundary_1500_grades_c
    """
    smp1, _ = _moisture_boundary_setup(api)
    graded = get_success_data(
        api.grade_sample(
            smp1["id"],
            {"lab_moisture_pct": 15.00, "lab_impurity_pct": 1.0},
            PLANT,
        )
    )
    assert graded["grade"] == "C", "15.00 meets the C lower bound (>= semantics)"


def test_moisture_1499_grades_b(api):
    """PRD §3.6: "Every threshold band is lower-bound inclusive and upper-bound
    exclusive: a lab moisture of exactly 15.00 lands in `C`"
    PRD §2.6: "**Percentages** — field and laboratory moisture and impurity
    readings — are accepted at two decimal places, and grade-threshold
    comparisons against them are exact, with no tolerance."

    Design: Difficulty/boundary_precision_check/moisture_boundary_1500_grades_c
    """
    _, smp2 = _moisture_boundary_setup(api)
    graded = get_success_data(
        api.grade_sample(
            smp2["id"],
            {"lab_moisture_pct": 14.99, "lab_impurity_pct": 1.0},
            PLANT,
        )
    )
    assert graded["grade"] == "B", "14.99 stays below the C band edge"
