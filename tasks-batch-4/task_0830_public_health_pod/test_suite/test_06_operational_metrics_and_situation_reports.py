"""Operational-metrics read (dual throughput/demand variants, the surge-bonus
nonlinear branch) and situation-report rollups (reimbursement rounding order,
zero-assignment boundary, RESTRICTED-forces-RED)."""
from test_helpers import (
    validate_success,
    create_activated_hazard_plan,
    create_open_pod,
    restrict_pod,
    create_countermeasure,
    create_pod_inventory_lot,
    setup_pod_with_staffed_lanes,
    setup_dispensing_events_mixed_states,
    create_verified_staff_member,
    create_reserved_mutual_aid_allocation_request,
    fulfill_allocation_request,
    create_situation_report,
)


def test_current_throughput_uses_only_checked_in_staff(api, admin_headers):
    """PRD §3.8: "`lanes_staffed_current` is the count of this POD's
    `ShiftAssignment` rows that are `CHECKED_IN` and whose `[start_time,
    end_time)` interval contains the current logical clock time, divided by 2
    (two staff cover one lane) and truncated down; `lanes_staffed_planned` is
    the same computation but counting rows in `CONFIRMED` or `CHECKED_IN` — a
    forward-looking count that includes staff not yet on site."
    PRD §3.8: "The result of this calculation using the current-staffing
    variant is returned as `current_throughput_capacity_per_hour`; the
    planned-staffing variant is returned as `planned_throughput_capacity_per_hour`."

    Design: Difficulty/dual_variant_calc/pod_throughput_current_vs_planned_diverge
    """
    hp, pod = setup_pod_with_staffed_lanes(
        pod_overrides={"staffing_capacity_lanes": 10, "lane_throughput_rate_per_hour": 40},
        checked_in_count=4, confirmed_only_count=2,
    )
    cm = create_countermeasure(doses_required=1)
    create_pod_inventory_lot(cm["id"], pod["id"], on_hand_quantity=500)

    res = api.get_pod_operational_metrics(pod["id"], admin_headers, params={"countermeasure_id": cm["id"]})
    metrics = validate_success(res, 200)
    assert metrics["current_throughput_capacity_per_hour"] == 80


def test_planned_throughput_uses_confirmed_and_checked_in_staff(api, admin_headers):
    """PRD §3.8: "`lanes_staffed_current` is the count of this POD's
    `ShiftAssignment` rows that are `CHECKED_IN` and whose `[start_time,
    end_time)` interval contains the current logical clock time, divided by 2
    (two staff cover one lane) and truncated down; `lanes_staffed_planned` is
    the same computation but counting rows in `CONFIRMED` or `CHECKED_IN` — a
    forward-looking count that includes staff not yet on site."
    PRD §3.8: "The result of this calculation using the current-staffing
    variant is returned as `current_throughput_capacity_per_hour`; the
    planned-staffing variant is returned as `planned_throughput_capacity_per_hour`."

    Design: Difficulty/dual_variant_calc/pod_throughput_current_vs_planned_diverge
    """
    hp, pod = setup_pod_with_staffed_lanes(
        pod_overrides={"staffing_capacity_lanes": 10, "lane_throughput_rate_per_hour": 40},
        checked_in_count=4, confirmed_only_count=2,
    )
    cm = create_countermeasure(doses_required=1)
    create_pod_inventory_lot(cm["id"], pod["id"], on_hand_quantity=500)

    res = api.get_pod_operational_metrics(pod["id"], admin_headers, params={"countermeasure_id": cm["id"]})
    metrics = validate_success(res, 200)
    assert metrics["planned_throughput_capacity_per_hour"] == 120
    assert (
        metrics["current_throughput_capacity_per_hour"]
        != metrics["planned_throughput_capacity_per_hour"]
    ), "same POD/InventoryLot, different ShiftAssignment status filter must diverge"


def test_surge_bonus_applied_at_lane_threshold(api, admin_headers):
    """PRD §3.8: "The smaller of those two hourly figures is the base capacity;
    if the effective-lane count reaches or exceeds six lanes, a 1.15x surge
    bonus is applied to the base capacity and the result is truncated down
    again, otherwise the base capacity stands as-is."

    Design: Difficulty/combinatorial_formula/pod_throughput_surge_bonus_nonlinear_branch
    """
    hp, pod = setup_pod_with_staffed_lanes(
        pod_overrides={"staffing_capacity_lanes": 20, "lane_throughput_rate_per_hour": 10},
        checked_in_count=12, confirmed_only_count=0,
    )
    cm = create_countermeasure(doses_required=1)
    create_pod_inventory_lot(cm["id"], pod["id"], on_hand_quantity=10000)

    res = api.get_pod_operational_metrics(pod["id"], admin_headers, params={"countermeasure_id": cm["id"]})
    metrics = validate_success(res, 200)
    assert metrics["current_throughput_capacity_per_hour"] == 69, (
        "floor(12/2)=6 effective lanes meets the surge threshold: "
        "floor(min(6*10,10000)*1.15) = floor(69.0) = 69"
    )


def test_surge_bonus_not_applied_below_lane_threshold(api, admin_headers):
    """PRD §3.8: "The smaller of those two hourly figures is the base capacity;
    if the effective-lane count reaches or exceeds six lanes, a 1.15x surge
    bonus is applied to the base capacity and the result is truncated down
    again, otherwise the base capacity stands as-is."

    Design: Difficulty/combinatorial_formula/pod_throughput_surge_bonus_nonlinear_branch
    """
    hp, pod = setup_pod_with_staffed_lanes(
        pod_overrides={"staffing_capacity_lanes": 20, "lane_throughput_rate_per_hour": 10},
        checked_in_count=10, confirmed_only_count=0,
    )
    cm = create_countermeasure(doses_required=1)
    create_pod_inventory_lot(cm["id"], pod["id"], on_hand_quantity=10000)

    res = api.get_pod_operational_metrics(pod["id"], admin_headers, params={"countermeasure_id": cm["id"]})
    metrics = validate_success(res, 200)
    assert metrics["current_throughput_capacity_per_hour"] == 50, (
        "floor(10/2)=5 effective lanes stays below the surge threshold of 6: "
        "min(5*10,10000) = 50, no surge bonus applied"
    )


def test_provisional_demand_counts_pending_registrants_discounted(api, admin_headers):
    """PRD §3.8: "`provisional_demand_doses` looks forward: it counts this
    POD's `DispensingEvent` rows for the countermeasure currently in
    `REGISTERED`, `SCREENED`, or `DEFERRED`, discounts that count by a 10
    percent no-show rate (i.e., multiplies by 0.90), multiplies by the
    countermeasure's `doses_required`, and rounds the result up to the next
    whole dose."

    Design: Difficulty/dual_variant_calc/allocation_demand_provisional_vs_final_diverge
    """
    hp = create_activated_hazard_plan()
    pod = create_open_pod(hp["id"])
    cm = create_countermeasure(doses_required=1)
    create_pod_inventory_lot(cm["id"], pod["id"], on_hand_quantity=50)
    staff = create_verified_staff_member(primary_role="CLINICAL_LEAD", credential_type="RN_LICENSE")

    setup_dispensing_events_mixed_states(
        pod["id"], cm["id"], staff["id"], registered=2, screened=1, deferred=1, dispensed=2,
    )

    res = api.get_pod_operational_metrics(pod["id"], admin_headers, params={"countermeasure_id": cm["id"]})
    metrics = validate_success(res, 200)
    assert metrics["provisional_demand_doses"] == 4, (
        "pending = 2 REGISTERED + 1 SCREENED + 1 DEFERRED = 4; ceil(4*0.9*1) = 4"
    )


def test_final_demand_counts_only_dispensed_doses_exactly(api, admin_headers):
    """PRD §3.8: "`final_demand_doses` looks backward: it is the exact integer
    sum of `dose_count` across this POD's `DISPENSED` events for the
    countermeasure, with no discount applied."

    Design: Difficulty/dual_variant_calc/allocation_demand_provisional_vs_final_diverge
    """
    hp = create_activated_hazard_plan()
    pod = create_open_pod(hp["id"])
    cm = create_countermeasure(doses_required=1)
    create_pod_inventory_lot(cm["id"], pod["id"], on_hand_quantity=50)
    staff = create_verified_staff_member(primary_role="CLINICAL_LEAD", credential_type="RN_LICENSE")

    setup_dispensing_events_mixed_states(
        pod["id"], cm["id"], staff["id"], registered=2, screened=1, deferred=1, dispensed=2,
    )

    res = api.get_pod_operational_metrics(pod["id"], admin_headers, params={"countermeasure_id": cm["id"]})
    metrics = validate_success(res, 200)
    assert metrics["final_demand_doses"] == 2
    assert metrics["provisional_demand_doses"] != metrics["final_demand_doses"]


def test_mutual_aid_reimbursement_cost_rounds_per_line(api, admin_headers):
    """PRD §3.5: "...the countermeasure's `unit_cost_cents` divided by its
    `doses_required` gives a cost-per-dose in cents, which is multiplied by
    `fulfilled_quantity`, divided by 100 to convert to dollars, and rounded to
    2 decimal places, round-half-up..."

    Design: Corner/calculations/mutual_aid_reimbursement_cost_rounding_per_line_then_sum
    """
    hp = create_activated_hazard_plan()
    req_pod = create_open_pod(hp["id"])
    partner_pod = create_open_pod(hp["id"])
    cm = create_countermeasure(unit_cost_cents=1000, doses_required=3, reorder_point_quantity=2)
    lot = create_pod_inventory_lot(cm["id"], partner_pod["id"], on_hand_quantity=10)

    fulfilled = create_reserved_mutual_aid_allocation_request(
        req_pod["id"], cm["id"], partner_pod["id"], lot["id"], 1,
    )
    fulfilled = fulfill_allocation_request(fulfilled["id"])

    assert fulfilled["reimbursement_cost_usd"] == 3.33, (
        "cost_per_dose_cents = 1000/3 = 333.333...; round((333.333...*1)/100, 2) = 3.33"
    )


def test_situation_report_staffing_fill_rate_zero_when_no_assignments(api, admin_headers):
    """PRD §3.8: "`staffing_fill_rate_pct` is 0 when this plan's PODs have no
    `ShiftAssignment` rows at all..."
    PRD §3.8: "`readiness_status` is `RED` when `pods_restricted_count` is one
    or more, or when `staffing_fill_rate_pct` falls below 50.0..."

    Design: Corner/calculations/situation_report_staffing_fill_rate_zero_when_no_assignments
    """
    hp = create_activated_hazard_plan()
    create_open_pod(hp["id"])

    report = create_situation_report(hp["id"], report_period_label="OPS_PERIOD_1")
    assert report["staffing_fill_rate_pct"] == 0
    assert report["readiness_status"] == "RED"


def test_situation_report_readiness_red_when_pod_restricted(api, admin_headers):
    """PRD §3.8: "`readiness_status` is `RED` when `pods_restricted_count` is
    one or more, or when `staffing_fill_rate_pct` falls below 50.0..."

    Design: Corner/calculations/situation_report_readiness_status_red_when_pod_restricted
    """
    hp = create_activated_hazard_plan()
    pod = create_open_pod(hp["id"])
    restrict_pod(pod["id"])

    report = create_situation_report(hp["id"], report_period_label="OPS_PERIOD_2")
    assert report["pods_restricted_count"] == 1
    assert report["readiness_status"] == "RED"
