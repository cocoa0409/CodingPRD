"""Two lifecycles that loop back on themselves and then hit a hard ceiling."""

from test_helpers import (
    SHOP_ESTIMATOR,
    assert_money_chain,
    assert_supplement_state,
    assert_technician_pay,
    bring_vehicle_to,
    drive_rework_count_to,
    file_supplement,
    make_insurer_adjuster_headers,
    read_facility,
    read_insurer,
    read_supplement,
    read_technician,
    read_vehicle,
    read_work_ticket,
    record_inspection,
    review_supplement,
    revise_supplement,
    setup_operational_facility,
    supplement_review_payload,
    tech_id,
    triage_vehicle,
    validate_error,
    validate_paginated,
)


def _car_stuck_at_the_rework_ceiling(api):
    """Fail the same car three times so `rework_count` reaches 3."""
    scenario = setup_operational_facility(api, technicians=("TA", "TI"))
    car = bring_vehicle_to(api, scenario, "QC_PENDING", damage_profile="three_panel")
    inspections = drive_rework_count_to(api, scenario, car["vehicle_id"], 2)
    inspections.append(
        record_inspection(
            api, car["vehicle_id"], tech_id(scenario, "TI"), "FAIL", ["HOOD"]
        )
    )
    return scenario, car, inspections


def test_the_rework_loop_cycles_back_onto_the_floor_until_the_count_passes_two(api):
    """PRD §3.7: "A vehicle in `QC_FAILED` whose `rework_count` is at most 2 may
    be started again by the estimator, moving `QC_FAILED` → `IN_REPAIR` with the
    same authorization and posture gates as the first start; tickets already
    `SUBMITTED` on that vehicle deliberately stay `SUBMITTED`, since labour
    already claimed is not discarded by a rework."

    PRD §3.7: "But the loop is bounded, and the boundary is a mirror image: once
    `rework_count` is greater than 2, start-repair is refused with
    `ERR_REWORK_LIMIT_EXCEEDED`, and the only way forward is a **re-triage** from
    `QC_FAILED` — which, symmetrically, is itself refused with
    `ERR_REWORK_LIMIT_EXCEEDED` whenever `rework_count` is 2 or less."

    Design: Difficulty/non_linear_state_machine/vehicle_rework_cycle_returns_to_in_repair_and_resets_on_retriage
    """
    scenario, car, inspections = _car_stuck_at_the_rework_ceiling(api)

    # Each inspection stamped the count as it stood after that failure.
    assert [i["rework_index"] for i in inspections] == [1, 2, 3]
    assert all(i["result"] == "FAIL" for i in inspections)

    vehicle = read_vehicle(api, car["vehicle_id"])
    assert vehicle["repair_status"] == "QC_FAILED"
    assert vehicle["rework_count"] == 3

    # The two restarts each re-opened the floor, and the labour claimed on the
    # earlier passes was never discarded.
    tickets = [read_work_ticket(api, t["id"]) for t in car["work_tickets"]]
    assert [t["status"] for t in tickets] == ["SUBMITTED"]

    response = api.start_vehicle_repair(car["vehicle_id"], SHOP_ESTIMATOR)
    validate_error(response, "ERR_REWORK_LIMIT_EXCEEDED", 409)
    assert read_vehicle(api, car["vehicle_id"])["repair_status"] == "QC_FAILED"


def test_re_triage_forces_the_conventional_path_and_resets_the_rework_budget(api):
    """PRD §3.7: "Re-triage declares the paintless path exhausted: it forces
    `pdr_feasible` to false and re-runs the triage formula with the conventional
    variant forced as the candidate, rewriting `triage_disposition` and
    `approved_repair_cents` and resetting `rework_count` to 0 so the vehicle gets
    a fresh rework budget."

    PRD §3.7: "Every work ticket of the vehicle whose `status` is `OPEN` or
    `SUBMITTED` is moved to `VOIDED`, which is terminal, with `payable_cents`
    left at 0 and a `version` increment on each — the labour claimed against a
    repair philosophy that failed is written off."

    PRD §3.7: "The money chain is recomputed, and when the vehicle's
    `billing_status` is `AUTHORIZED`, `BILLED` or `PAID`, the facility's
    `billable_accrued_cents` and the carrier's `outstanding_direct_bill_cents`
    absorb the resulting change in `net_billable_cents`."

    Design: Difficulty/non_linear_state_machine/vehicle_rework_cycle_returns_to_in_repair_and_resets_on_retriage
    """
    scenario, car, _ = _car_stuck_at_the_rework_ceiling(api)
    assert read_facility(api, scenario["facility_id"])["billable_accrued_cents"] == 213030

    vehicle = triage_vehicle(api, car["vehicle_id"])

    assert vehicle["repair_status"] == "TRIAGED"
    assert vehicle["rework_count"] == 0
    assert vehicle["pdr_feasible"] is False
    assert vehicle["triage_disposition"] == "CONVENTIONAL"
    assert vehicle["approved_repair_cents"] == 257750
    assert vehicle["billing_status"] == "AUTHORIZED"
    assert_money_chain(
        vehicle,
        admin_fee_cents=12888,
        gross_billable_cents=270638,
        discount_cents=5413,
        net_billable_cents=265225,
    )

    # All three tickets claimed against the abandoned paintless plan are void.
    response = api.list_work_tickets(SHOP_ESTIMATOR, {"vehicle_id": car["vehicle_id"]})
    tickets, meta = validate_paginated(response)
    assert meta["total_count"] == 3
    assert all(t["status"] == "VOIDED" for t in tickets)
    assert all(t["payable_cents"] == 0 for t in tickets)
    assert_technician_pay(
        read_technician(api, tech_id(scenario, "TA")),
        accrued_pay_cents=0,
        approved_ticket_count=0,
    )

    assert read_facility(api, scenario["facility_id"])["billable_accrued_cents"] == 265225
    assert (
        read_insurer(api, scenario["insurer_id"])["outstanding_direct_bill_cents"]
        == 265225
    )


def _negotiation_at_the_third_round(api):
    """Walk one supplement through two full counter/revise rounds."""
    scenario = setup_operational_facility(api)
    car = bring_vehicle_to(api, scenario, "AUTHORIZED", damage_profile="three_panel")
    insurer_id = scenario["insurer_id"]

    supplement = file_supplement(api, car["vehicle_id"], 60000)
    trail = [dict(supplement)]

    trail.append(review_supplement(api, supplement["id"], insurer_id, "COUNTER", 40000))
    trail.append(revise_supplement(api, supplement["id"], "REVISE", 50000))
    trail.append(review_supplement(api, supplement["id"], insurer_id, "COUNTER", 30000))
    trail.append(revise_supplement(api, supplement["id"], "REVISE", 45000))
    return scenario, car, supplement["id"], trail


def test_each_revision_reopens_review_and_advances_the_round_index(api):
    """PRD §3.8: "A successful revision overwrites `requested_amount_cents` with
    `revised_amount_cents`, increases `round_index` by one, and returns the
    supplement `COUNTERED` → `UNDER_REVIEW` with a `version` increment — closing
    the `UNDER_REVIEW` → `COUNTERED` → `UNDER_REVIEW` negotiation cycle."

    PRD §3.8: "Auto-approval is deliberately **not** re-evaluated on these later
    rounds: only a round-one filing can auto-approve, however small the revised
    figure becomes."

    Design: Difficulty/non_linear_state_machine/supplement_counter_revise_negotiation_cycle_hits_round_limit
    """
    scenario, car, supplement_id, trail = _negotiation_at_the_third_round(api)

    assert_supplement_state(
        trail[0], status="UNDER_REVIEW", round_index=1, requested_amount_cents=60000
    )
    assert_supplement_state(
        trail[1], status="COUNTERED", round_index=1, counter_amount_cents=40000
    )
    assert_supplement_state(
        trail[2], status="UNDER_REVIEW", round_index=2, requested_amount_cents=50000
    )
    assert_supplement_state(
        trail[3], status="COUNTERED", round_index=2, counter_amount_cents=30000
    )
    assert_supplement_state(
        trail[4],
        status="UNDER_REVIEW",
        round_index=3,
        requested_amount_cents=45000,
        approved_amount_cents=0,
    )
    # Round three's figure is below the auto-approval threshold that the filing
    # was measured against, and it still does not auto-approve.
    assert trail[4]["status"] != "AUTO_APPROVED"


def test_the_third_counter_is_refused_and_freezes_the_negotiation(api):
    """PRD §3.8: "`COUNTER` moves `UNDER_REVIEW` → `COUNTERED` and is the one
    branch with its own inputs and limits: it must supply `counter_amount_cents`
    strictly greater than 0 and strictly less than the current
    `requested_amount_cents` — a counter at or above the claim is not a counter —
    and it requires `round_index` to still be less than 3, else
    `ERR_SUPPLEMENT_ROUND_LIMIT`."

    PRD §3.6: "The rates always come from the vehicle's pinned agreement and
    never from whichever agreement is currently `ACTIVE`, and the supplement
    contribution counts only supplements whose `status` is `AUTO_APPROVED` or
    `APPROVED` — a `DENIED`, `WITHDRAWN`, `COUNTERED` or `UNDER_REVIEW`
    supplement contributes nothing."

    Design: Difficulty/non_linear_state_machine/supplement_counter_revise_negotiation_cycle_hits_round_limit
    """
    scenario, car, supplement_id, _ = _negotiation_at_the_third_round(api)

    response = api.review_supplement(
        supplement_id,
        supplement_review_payload("COUNTER", 25000),
        make_insurer_adjuster_headers(scenario["insurer_id"]),
    )
    validate_error(response, "ERR_SUPPLEMENT_ROUND_LIMIT", 409)

    supplement = read_supplement(api, supplement_id)
    assert_supplement_state(
        supplement,
        status="UNDER_REVIEW",
        round_index=3,
        requested_amount_cents=45000,
        counter_amount_cents=30000,
        approved_amount_cents=0,
    )

    # Nothing under review ever reached the money chain.
    vehicle = read_vehicle(api, car["vehicle_id"])
    assert vehicle["approved_supplement_cents"] == 0
    assert vehicle["net_billable_cents"] == 213030
    assert (
        read_insurer(api, scenario["insurer_id"])["outstanding_direct_bill_cents"]
        == 213030
    )
