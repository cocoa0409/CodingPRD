"""Transitive cascades (finalize -> ledger -> version -> stale-create; cancel
-> release -> free calendar), optimistic concurrency on booking create, the
priority-pair conflicts, and cancel cascades (PRD §2.5, §2.8, §2.9, §3.8–§3.10).

Difficulty: transitive_cascade, priority_pair_validation_conflict.
Corner: OCC happy path, cancel cascades.
"""
from test_helpers import (
    validate_success,
    validate_error,
    api_client,
    ApiErrorId,
    create_service_area,
    create_crew,
    create_work_order,
    add_tree,
    assess,
    create_estimate,
    add_line_item,
    issue_estimate,
    accept_estimate,
    current_version,
    create_booking,
    finalize_booking,
    record_disposal_ticket,
    setup_scheduled_with_crew,
    setup_permit_work_order_under_review,
    TEST_USERS,
    make_client_headers,
)


def _scheduled_hourly_with_crew(crew_rate=9000, tree_overrides=None):
    area = create_service_area(disposal_fee_cents_per_ton=8000)
    crew = create_crew(area["id"], name="Crew A", hourly_rate_cents=crew_rate)
    wo = create_work_order(area["id"], pricing_mode="HOURLY")
    tree = add_tree(wo["id"], **(tree_overrides or {"species": "Maple", "dbh_inches": 20}))
    assess(wo["id"])
    est = create_estimate(wo["id"])
    add_line_item(est["id"], service_type="REMOVAL", quantity=1, tree_asset_id=tree["id"])
    issue_estimate(wo["id"], est["id"])
    accept_estimate(wo["id"], est["id"])
    return area, wo, tree, crew


# ─── transitive_cascade / booking_finalize_cascade_ledger_version_stale ───


def test_finalize_cascades_to_ledger_and_billed_cost(api):
    """PRD §3.9: "On finalization the server computes the booking's
    `billed_cost_cents`, adds it to the work order's
    `labor_cost_accrued_cents`, and increments the work order's `version` by
    one."

    Design: Difficulty/transitive_cascade/booking_finalize_cascade_ledger_version_stale_create
    """
    area, wo, tree, crew = _scheduled_hourly_with_crew()
    bk = create_booking(
        wo["id"], "CREW", crew_id=crew["id"],
        start_at="2026-07-01T09:00:00Z", end_at="2026-07-01T18:00:00Z",
    )
    finalized = finalize_booking(bk["id"], 9)
    # 9000*8 + 9000*1.5*1 = 72000 + 13500 = 85500
    assert finalized["billed_cost_cents"] == 85500
    wo_after = validate_success(
        api.get_work_order(wo["id"], TEST_USERS["dispatcher_headers"]), 200,
    )
    assert wo_after["labor_cost_accrued_cents"] == 85500


def test_finalize_bumps_version_so_stale_booking_create_rejected(api):
    """PRD §2.8: "If another writer has advanced that version since the client
    read it — a sibling booking create, a booking finalize, a disposal-ticket
    finalize, or an estimate acceptance each does so — then the carried value
    is stale, the client is acting on an out-of-date view of the schedule and
    budget, and the reservation is rejected with `ERR_STALE_WORK_ORDER_VERSION`
    (HTTP 412)."

    Design: Difficulty/transitive_cascade/booking_finalize_cascade_ledger_version_stale_create
    """
    area, wo, tree, crew = _scheduled_hourly_with_crew()
    bk = create_booking(
        wo["id"], "CREW", crew_id=crew["id"],
        start_at="2026-07-01T09:00:00Z", end_at="2026-07-01T18:00:00Z",
    )
    version_before_finalize = current_version(wo["id"])
    finalize_booking(bk["id"], 9)   # bumps WorkOrder.version
    res = api.create_booking(
        {"work_order_id": wo["id"], "resource_kind": "CREW", "crew_id": crew["id"],
         "start_at": "2026-07-02T09:00:00Z", "end_at": "2026-07-02T12:00:00Z",
         "expected_work_order_version": version_before_finalize},
        TEST_USERS["dispatcher_headers"],
    )
    validate_error(res, ApiErrorId.ERR_STALE_WORK_ORDER_VERSION.value)


# ─── transitive_cascade / cancel_cascade_release_frees_resource_window ───


def test_cancel_release_frees_crew_window_for_new_booking(api):
    """PRD §3.10: "every `RESERVED` booking is released, freeing that
    resource's calendar window" PRD §3.8: "For a `CREW` booking, the new
    window is checked for overlap against every other `RESERVED` or
    `FINALIZED` booking of the same crew ... any intersection is rejected with
    `ERR_CREW_DOUBLE_BOOKED`"

    Design: Difficulty/transitive_cascade/cancel_cascade_release_frees_resource_window
    """
    area = create_service_area(disposal_fee_cents_per_ton=8000)
    crew = create_crew(area["id"], name="Crew A", hourly_rate_cents=9000)

    # W1 reserves the crew for 09:00-12:00 on 2026-07-05.
    w1 = create_work_order(area["id"], pricing_mode="HOURLY", site_address="9 Aspen St")
    t1 = add_tree(w1["id"], species="Maple", dbh_inches=20)
    assess(w1["id"])
    e1 = create_estimate(w1["id"])
    add_line_item(e1["id"], service_type="REMOVAL", quantity=1, tree_asset_id=t1["id"])
    issue_estimate(w1["id"], e1["id"])
    accept_estimate(w1["id"], e1["id"])
    bk1 = create_booking(
        w1["id"], "CREW", crew_id=crew["id"],
        start_at="2026-07-05T09:00:00Z", end_at="2026-07-05T12:00:00Z",
    )

    # W2 wants the same crew for an overlapping window 10:00-11:00.
    w2 = create_work_order(area["id"], pricing_mode="HOURLY", site_address="10 Aspen St")
    t2 = add_tree(w2["id"], species="Maple", dbh_inches=20)
    assess(w2["id"])
    e2 = create_estimate(w2["id"])
    add_line_item(e2["id"], service_type="REMOVAL", quantity=1, tree_asset_id=t2["id"])
    issue_estimate(w2["id"], e2["id"])
    accept_estimate(w2["id"], e2["id"])
    pre = api.create_booking(
        {"work_order_id": w2["id"], "resource_kind": "CREW", "crew_id": crew["id"],
         "start_at": "2026-07-05T10:00:00Z", "end_at": "2026-07-05T11:00:00Z",
         "expected_work_order_version": current_version(w2["id"])},
        TEST_USERS["dispatcher_headers"],
    )
    validate_error(pre, ApiErrorId.ERR_CREW_DOUBLE_BOOKED.value)

    # Cancel W1 -> bk1 released -> the crew window is freed.
    cancelled = validate_success(
        api.cancel_work_order(w1["id"], TEST_USERS["dispatcher_headers"]), 200,
    )
    assert cancelled["status"] == "CANCELLED"
    bk1_after = validate_success(
        api.get_booking(bk1["id"], TEST_USERS["dispatcher_headers"]), 200,
    )
    assert bk1_after["status"] == "RELEASED"

    bk2 = validate_success(api.create_booking(
        {"work_order_id": w2["id"], "resource_kind": "CREW", "crew_id": crew["id"],
         "start_at": "2026-07-05T10:00:00Z", "end_at": "2026-07-05T11:00:00Z",
         "expected_work_order_version": current_version(w2["id"])},
        TEST_USERS["dispatcher_headers"],
    ), 201)
    assert bk2["status"] == "RESERVED"


def test_cancel_releases_reserved_booking_freeing_window(api):
    """PRD §2.5: "When a work order is cancelled, the server reaches across
    every dependent resource to unwind it — reserved bookings are released,
    recorded disposal tickets are voided, and any estimate still in `DRAFT` or
    `ISSUED` is superseded — all as side effects of the single cancel action."

    Design: Difficulty/transitive_cascade/cancel_cascade_release_frees_resource_window
    """
    area, wo, tree, est, crew = setup_scheduled_with_crew()
    bk = create_booking(
        wo["id"], "CREW", crew_id=crew["id"],
        start_at="2026-07-06T09:00:00Z", end_at="2026-07-06T12:00:00Z",
    )
    validate_success(api.cancel_work_order(wo["id"], TEST_USERS["dispatcher_headers"]), 200)
    bk_after = validate_success(
        api.get_booking(bk["id"], TEST_USERS["dispatcher_headers"]), 200,
    )
    assert bk_after["status"] == "RELEASED"


# ─── priority_pair_validation_conflict / occ_state_beats_utility_safety ───


def test_stale_version_outranks_utility_clearance_on_booking(api):
    """PRD §2.8: "the reservation is rejected with
    `ERR_STALE_WORK_ORDER_VERSION` (HTTP 412)." PRD §2.9: "After shape
    validation, the optimistic-concurrency version check runs on booking
    creation. Then state-transition legality is checked" PRD §2.9: "The
    domain-specific business checks then run in the priority order **safety
    before scheduling before fiscal**. Utility-line clearance is verified
    first"

    Design: Difficulty/priority_pair_validation_conflict/occ_state_beats_utility_safety_on_booking
    """
    area = create_service_area(disposal_fee_cents_per_ton=8000)
    crew_nc = create_crew(area["id"], name="NonClear", hourly_rate_cents=9000,
                          certified_utility_clearance=False)
    crew_c = create_crew(area["id"], name="Clear", hourly_rate_cents=9000,
                         certified_utility_clearance=True)
    wo = create_work_order(area["id"], pricing_mode="HOURLY")
    tree = add_tree(wo["id"], species="Maple", dbh_inches=20, near_utility_line=True)
    assess(wo["id"])
    est = create_estimate(wo["id"])
    add_line_item(est["id"], service_type="REMOVAL", quantity=1, tree_asset_id=tree["id"])
    issue_estimate(wo["id"], est["id"])
    accept_estimate(wo["id"], est["id"])
    # Finalize a clearance-crew booking to advance the version.
    bk1 = create_booking(
        wo["id"], "CREW", crew_id=crew_c["id"],
        start_at="2026-07-10T09:00:00Z", end_at="2026-07-10T17:00:00Z",
    )
    finalize_booking(bk1["id"], 5)
    current = current_version(wo["id"])
    # Stale version AND non-clearance crew on a near-utility work order:
    # the higher-priority OCC state error must surface.
    res = api.create_booking(
        {"work_order_id": wo["id"], "resource_kind": "CREW", "crew_id": crew_nc["id"],
         "start_at": "2026-07-11T09:00:00Z", "end_at": "2026-07-11T17:00:00Z",
         "expected_work_order_version": current - 1},
        TEST_USERS["dispatcher_headers"],
    )
    validate_error(res, ApiErrorId.ERR_STALE_WORK_ORDER_VERSION.value)


# ─── priority_pair_validation_conflict / permit_safety_beats_ownership ───


def test_permit_required_outranks_ownership_on_accept(api):
    """PRD §3.7: "this gate is checked at priority 10 — ahead of ownership.
    Second, the acting client must own the work order ... a mismatch is
    refused with `ERR_NOT_RESOURCE_OWNER` at priority 11." PRD §2.9: "at
    estimate acceptance the permit-required gate (`ERR_PERMIT_REQUIRED`) is
    evaluated at priority 10, strictly **before** the ownership check
    (`ERR_NOT_RESOURCE_OWNER`) at priority 11, so a missing permit surfaces
    ahead of an ownership failure."

    Design: Difficulty/priority_pair_validation_conflict/permit_safety_beats_ownership_on_accept
    """
    area, wo, tree, est, permit = setup_permit_work_order_under_review()
    # client-2 is NOT the owner AND no APPROVED permit exists: permit gate wins.
    res = api.accept_estimate(wo["id"], est["id"], make_client_headers("client-2"))
    validate_error(res, ApiErrorId.ERR_PERMIT_REQUIRED.value)


# ─── Corner / OCC happy path + cancel cascade ───────────


def test_booking_with_correct_version_succeeds_and_bumps_version(api):
    """PRD §2.8: "Only when the supplied version matches the live version does
    the reservation proceed." PRD §3.8: "A new booking begins in `RESERVED`,
    occupies the chosen resource's window, and increments the work order's
    `version` by one (so a later create still carrying the prior version
    becomes stale)."

    Design: Corner/cross_cutting_complexity_layers/occ_correct_version_succeeds
    """
    area, wo, tree, crew = _scheduled_hourly_with_crew()
    v_sched = current_version(wo["id"])
    res = api.create_booking(
        {"work_order_id": wo["id"], "resource_kind": "CREW", "crew_id": crew["id"],
         "start_at": "2026-09-10T09:00:00Z", "end_at": "2026-09-10T12:00:00Z",
         "expected_work_order_version": v_sched},
        TEST_USERS["dispatcher_headers"],
    )
    bk = validate_success(res, 201)
    assert bk["status"] == "RESERVED"
    assert current_version(wo["id"]) == v_sched + 1


def test_cancel_voids_recorded_disposal_ticket(api):
    """PRD §2.5: "reserved bookings are released, recorded disposal tickets
    are voided, and any estimate still in `DRAFT` or `ISSUED` is superseded —
    all as side effects of the single cancel action." PRD §3.10:
    "`final_invoice_cents` is set to 0"

    Design: Corner/cross_cutting_complexity_layers/cascade_cancel_voids_recorded_disposal_ticket
    """
    area = create_service_area(disposal_fee_cents_per_ton=8000)
    wo = create_work_order(area["id"], pricing_mode="HOURLY")
    tree = add_tree(wo["id"], species="Pine", dbh_inches=12)
    assess(wo["id"])
    est = create_estimate(wo["id"])
    add_line_item(est["id"], service_type="REMOVAL", quantity=1, tree_asset_id=tree["id"])
    issue_estimate(wo["id"], est["id"])
    accept_estimate(wo["id"], est["id"])
    ticket = record_disposal_ticket(wo["id"], debris_tons=2)
    cancelled = validate_success(
        api.cancel_work_order(wo["id"], TEST_USERS["dispatcher_headers"]), 200,
    )
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["final_invoice_cents"] == 0
    ticket_after = validate_success(
        api.get_disposal_ticket(wo["id"], ticket["id"], TEST_USERS["finance_clerk_headers"]), 200,
    )
    assert ticket_after["status"] == "VOIDED"
