"""Lifecycle edges: initial states, legal transitions, refused transitions,
terminal lockdown and the side effects each transition carries."""

import pytest

from test_helpers import (
    ADMIN_1_USER_ID,
    ADMIN_2_USER_ID,
    AUDITOR_1_USER_ID,
    TEST_USERS,
    accept_volume_report,
    adjudicate_claim,
    approve_rate,
    assert_custody_buckets,
    attach_claim,
    close_audit,
    complete_take_back,
    create_active_rate,
    create_approved_rate,
    create_ca_program,
    create_enrolled_site,
    create_hauler,
    create_registrant,
    create_remittance,
    create_site,
    create_take_back,
    create_wa_program,
    dispatch_order,
    enroll_site,
    file_remittance,
    make_hauler_headers,
    open_audit,
    pay_remittance,
    pickup_and_deliver,
    propose_rate,
    read_program,
    reinstate_site,
    set_clock,
    setup_inspected_order,
    setup_logistics_chain,
    setup_paid_remittance,
    setup_scheduled_order,
    submit_volume_report,
    suspend_certification,
    suspend_site,
    validate_error,
    validate_paginated,
    validate_success,
    waive_take_back,
)

ADMIN = TEST_USERS["admin_headers"]
ADMIN_2 = TEST_USERS["admin_2_headers"]
ADMIN_3 = TEST_USERS["admin_3_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


def test_a_new_rate_proposal_lands_in_proposed_with_its_band_frozen(api):
    """PRD §3.2: "A proposal starts in `PROPOSED`, records the acting administrator
    as `proposed_by_user_id`, and leaves `approved_by_user_id` null. It snapshots the
    program's recommended rate at that instant into
    `recommended_rate_cents_at_proposal` and derives `band_low_cents` and
    `band_high_cents` from that snapshot, and it increments the program's `version`
    by one."

    Design: Corner/state_machines/fee_rate_schedule_initial_state_is_proposed
    """
    program = create_ca_program(api)

    schedule = propose_rate(
        api,
        program["id"],
        unit_class="MATTRESS",
        fee_cents_per_unit=1100,
        effective_from="2026-01-01T00:00:00Z",
    )

    assert schedule["status"] == "PROPOSED"
    assert schedule["proposed_by_user_id"] == ADMIN_1_USER_ID
    assert schedule["approved_by_user_id"] is None
    assert schedule["recommended_rate_cents_at_proposal"] == 1075
    assert schedule["band_low_cents"] == 860
    assert schedule["band_high_cents"] == 1290
    assert read_program(api, program["id"])["version"] == 2


def test_approval_by_a_second_administrator_stamps_that_administrator(api):
    """PRD §3.2: "Approval moves a schedule `PROPOSED → APPROVED` and requires a
    second `ProgramAdministrator` user as described in §2.1." On success, the
    approving administrator's identifier is recorded as `approved_by_user_id`.

    Design: Corner/state_machines/fee_rate_schedule_approve_by_second_administrator_records_approver
    """
    program = create_ca_program(api)
    schedule = propose_rate(
        api,
        program["id"],
        unit_class="MATTRESS",
        fee_cents_per_unit=1100,
        effective_from="2026-01-01T00:00:00Z",
    )

    approved = validate_success(api.approve_fee_rate_schedule(schedule["id"], ADMIN_2))

    assert approved["status"] == "APPROVED"
    assert approved["approved_by_user_id"] == ADMIN_2_USER_ID
    assert approved["proposed_by_user_id"] == ADMIN_1_USER_ID
    assert approved["effective_from"] == "2026-01-01T00:00:00Z"
    assert approved["effective_to"] is None


def test_activation_waits_for_the_clock_to_reach_the_effective_instant(api):
    """PRD §3.2: "Activation moves a schedule `APPROVED → ACTIVE`. It is only legal
    from `APPROVED` — otherwise `ERR_RATE_SCHEDULE_NOT_APPROVABLE` — and only once
    the logical clock has reached or passed the schedule's `effective_from`;
    activating early is refused with `ERR_RATE_NOT_YET_EFFECTIVE`."

    Design: Corner/state_machines/activate_before_effective_from_precondition_rejected
    """
    program = create_ca_program(api)
    schedule = create_approved_rate(
        api,
        program["id"],
        unit_class="MATTRESS",
        fee_cents_per_unit=1100,
        effective_from="2026-09-01T00:00:00Z",
    )

    early = api.activate_fee_rate_schedule(schedule["id"], ADMIN)

    validate_error(early, "ERR_RATE_NOT_YET_EFFECTIVE", 409)
    assert (
        validate_success(api.get_fee_rate_schedule(schedule["id"], ADMIN))["status"]
        == "APPROVED"
    )

    set_clock(api, "2026-09-01T00:00:00Z")
    on_time = validate_success(api.activate_fee_rate_schedule(schedule["id"], ADMIN))

    assert on_time["status"] == "ACTIVE"


def test_activating_a_successor_supersedes_the_predecessor_for_good(api):
    """PRD §3.2: "Activation cascades. Any schedule for the same program and unit
    class currently in `ACTIVE` transitions `ACTIVE → SUPERSEDED`, and if that
    superseded schedule's `effective_to` was null it is set to the newly activated
    schedule's `effective_from`; a superseded schedule that had an explicitly
    proposed `effective_to` keeps it, preserving the half-open interval it was
    proposed with."

    Design: Corner/state_machines/activation_supersedes_predecessor_and_supersession_is_terminal
    """
    program = create_ca_program(api)
    predecessor = create_active_rate(
        api,
        program["id"],
        unit_class="MATTRESS",
        fee_cents_per_unit=1000,
        effective_from="2026-01-01T00:00:00Z",
        effective_to="2026-09-01T00:00:00Z",
    )
    successor = create_approved_rate(
        api,
        program["id"],
        unit_class="MATTRESS",
        fee_cents_per_unit=1100,
        effective_from="2026-09-01T00:00:00Z",
    )
    set_clock(api, "2026-09-01T00:00:00Z")

    activated = validate_success(api.activate_fee_rate_schedule(successor["id"], ADMIN))

    assert activated["status"] == "ACTIVE"
    superseded = validate_success(api.get_fee_rate_schedule(predecessor["id"], ADMIN))
    assert superseded["status"] == "SUPERSEDED"
    assert superseded["effective_to"] == "2026-09-01T00:00:00Z"
    _, meta = validate_paginated(
        api.list_fee_rate_schedules(
            ADMIN,
            params={
                "state_program_id": program["id"],
                "unit_class": "MATTRESS",
                "status": "ACTIVE",
            },
        )
    )
    assert meta["total_count"] == 1
    validate_error(
        api.approve_fee_rate_schedule(predecessor["id"], ADMIN_2),
        "ERR_RATE_SCHEDULE_NOT_APPROVABLE",
        409,
    )


def test_a_second_approval_of_the_same_schedule_keeps_the_first_approver(api):
    """PRD §3.2: "Approval is only legal from `PROPOSED`; from any other status the
    request is rejected with `ERR_RATE_SCHEDULE_NOT_APPROVABLE`."

    Design: Corner/state_machines/second_approve_of_same_schedule_is_not_idempotent_and_rejected
    """
    program = create_ca_program(api)
    schedule = propose_rate(
        api,
        program["id"],
        unit_class="MATTRESS",
        fee_cents_per_unit=1100,
        effective_from="2026-01-01T00:00:00Z",
    )
    approve_rate(api, schedule["id"])

    response = api.approve_fee_rate_schedule(schedule["id"], ADMIN_3)

    validate_error(response, "ERR_RATE_SCHEDULE_NOT_APPROVABLE", 409)
    stored = validate_success(api.get_fee_rate_schedule(schedule["id"], ADMIN))
    assert stored["status"] == "APPROVED"
    assert stored["approved_by_user_id"] == ADMIN_2_USER_ID


def test_accepting_the_same_volume_report_twice_pays_the_credit_only_once(api):
    """PRD §3.5: "Acceptance moves a report `SUBMITTED → ACCEPTED`, the report's only
    transition and its terminal status. It requires the report to be in `SUBMITTED`,
    refusing otherwise with `ERR_VOLUME_REPORT_NOT_SUBMITTED`, and it requires the
    owning site to still be `ENROLLED`, refusing otherwise with
    `ERR_SITE_NOT_ENROLLED` — a report submitted before a suspension cannot be
    accepted after it."

    Design: Corner/state_machines/volume_report_second_accept_rejected_and_credit_not_paid_twice
    """
    program = create_wa_program(api)
    site = create_enrolled_site(api, program["id"])
    report = submit_volume_report(
        api, site["id"], period_month="2026-08", units_mattress=320, units_foundation=190
    )
    accept_volume_report(api, report["id"])

    response = api.accept_volume_report(report["id"], ADMIN)

    validate_error(response, "ERR_VOLUME_REPORT_NOT_SUBMITTED", 409)
    stored_reports, _ = validate_paginated(api.list_volume_reports(site["id"], ADMIN))
    stored = stored_reports[0]
    assert stored["status"] == "ACCEPTED"
    assert stored["accepted_at"] == "2026-08-01T00:00:00Z"
    assert stored["credit_cents"] == 163_328
    stored_program = read_program(api, program["id"])
    assert stored_program["site_credit_paid_cents"] == 163_328, (
        "the refused second acceptance must not book the credit again"
    )
    assert stored_program["reserve_balance_cents"] == 4_836_672
    stored_site = validate_success(api.get_collection_site(site["id"], ADMIN))
    assert stored_site["units_on_hand"] == 510
    assert stored_site["units_reported_total"] == 510


def test_delivering_a_load_that_was_never_picked_up_is_refused(api):
    """PRD §3.6: "Every operation on a pickup order requires the right
    `fulfillment_status` to start from — `SCHEDULED` to confirm pickup or to void,
    `PICKED_UP` to deliver, `DELIVERED` to inspect or to finalize settlement — and a
    mismatch is rejected with `ERR_PICKUP_STATE_INVALID`."

    Design: Corner/state_machines/deliver_before_pickup_confirm_is_an_invalid_transition
    """
    chain = setup_scheduled_order(api)

    response = api.deliver_pickup_order(
        chain["order_id"], {"units_delivered": 240}, make_hauler_headers(chain["hauler_id"])
    )

    validate_error(response, "ERR_PICKUP_STATE_INVALID", 409)
    order = validate_success(api.get_pickup_order(chain["order_id"], ADMIN))
    assert order["fulfillment_status"] == "SCHEDULED"
    assert order["settlement_status"] == "UNSETTLED"
    assert order["units_delivered"] is None
    assert order["estimated_payment_cents"] is None
    site = validate_success(api.get_collection_site(chain["site_id"], ADMIN))
    assert_custody_buckets(site, 270, 240, 0, 0, 0, reported_total=510)
    recycler = validate_success(api.get_recycler(chain["recycler_id"], ADMIN))
    assert recycler["units_received_count"] == 0


def adjudication_chain(api):
    """A paid California filing under audit carrying one documented and one
    undocumented mattress claim."""
    program = create_ca_program(api)
    create_active_rate(
        api,
        program["id"],
        unit_class="MATTRESS",
        fee_cents_per_unit=1100,
        effective_from="2026-01-01T00:00:00Z",
    )
    registrant = create_registrant(api)
    remittance = create_remittance(
        api,
        registrant["id"],
        program["id"],
        period_code="2026Q2",
        units_sold_mattress=500,
        units_sold_foundation=0,
    )
    documented = attach_claim(
        api,
        remittance["id"],
        registrant["id"],
        claim_type="OUT_OF_STATE_SHIPMENT",
        unit_class="MATTRESS",
        units=40,
        documentation_reference="BOL-2026-0412",
    )
    undocumented = attach_claim(
        api,
        remittance["id"],
        registrant["id"],
        claim_type="EXEMPT_SALE",
        unit_class="MATTRESS",
        units=60,
        documentation_reference=None,
    )
    file_remittance(api, remittance["id"], registrant["id"])
    pay_remittance(api, remittance["id"], registrant["id"], 440_000)
    open_audit(api, remittance["id"])
    return {
        "program_id": program["id"],
        "registrant_id": registrant["id"],
        "remittance_id": remittance["id"],
        "documented_claim_id": documented["id"],
        "undocumented_claim_id": undocumented["id"],
    }


def test_adjudication_takes_one_of_two_edges_out_of_a_pending_claim(api):
    """PRD §3.4: "Deciding to disallow moves the claim `PENDING → DISALLOWED`. It
    records `adjudicated_by_user_id` as the acting auditor and stores the supplied
    `disallow_reason`."

    Design: Corner/state_machines/exemption_claim_adjudication_branches_on_decision_value
    """
    chain = adjudication_chain(api)

    substantiated = adjudicate_claim(api, chain["documented_claim_id"], "SUBSTANTIATE")
    disallowed = adjudicate_claim(
        api,
        chain["undocumented_claim_id"],
        "DISALLOW",
        disallow_reason="MISSING_DOCUMENTATION",
    )

    assert substantiated["status"] == "SUBSTANTIATED"
    assert substantiated["disallow_reason"] is None
    assert substantiated["adjudicated_by_user_id"] == AUDITOR_1_USER_ID
    assert disallowed["status"] == "DISALLOWED"
    assert disallowed["disallow_reason"] == "MISSING_DOCUMENTATION"
    assert disallowed["adjudicated_by_user_id"] == AUDITOR_1_USER_ID
    remittance = validate_success(api.get_sales_remittance(chain["remittance_id"], AUDITOR))
    assert remittance["status"] == "UNDER_AUDIT"
    assert remittance["fee_self_assessed_cents"] == 440_000


def take_back_chain(api):
    """A California program with one enrolled western collection site and one
    retailer registrant."""
    program = create_ca_program(api)
    site = create_site(
        api,
        program["id"],
        operator_name="Bay Area Collection Site",
        site_type="COLLECTION_SITE",
        region_code="WEST",
    )
    enroll_site(api, site["id"])
    registrant = create_registrant(api)
    return {
        "program_id": program["id"],
        "site_id": site["id"],
        "registrant_id": registrant["id"],
    }


def test_a_short_take_back_breaches_while_a_full_one_meets_the_obligation(api):
    """PRD §3.8: "When the collected count falls short of `units_delivered_new`, the
    delivery moves `SCHEDULED → OBLIGATION_BREACHED`. The collected count is stored,
    `breach_units` is set to the obligation less the collected count, and
    `breach_penalty_cents` is set to 2,500 cents — twenty-five dollars — for each
    breached unit."

    Design: Corner/state_machines/take_back_delivery_branches_on_units_collected
    """
    chain = take_back_chain(api)
    met = create_take_back(
        api,
        chain["registrant_id"],
        chain["site_id"],
        delivery_reference="DEL-1001",
        units_delivered_new=10,
        units_takeback_offered=10,
    )
    breached = create_take_back(
        api,
        chain["registrant_id"],
        chain["site_id"],
        delivery_reference="DEL-1002",
        units_delivered_new=10,
        units_takeback_offered=10,
    )

    met_result = complete_take_back(api, met["id"], chain["registrant_id"], 10)
    breached_result = complete_take_back(api, breached["id"], chain["registrant_id"], 4)

    assert met_result["status"] == "OBLIGATION_MET"
    assert met_result["breach_units"] == 0
    assert met_result["breach_penalty_cents"] == 0
    assert breached_result["status"] == "OBLIGATION_BREACHED"
    assert breached_result["breach_units"] == 6
    assert breached_result["breach_penalty_cents"] == 15_000
    registrant = validate_success(api.get_registrant(chain["registrant_id"], ADMIN))
    assert registrant["takeback_breach_count"] == 1
    assert registrant["delinquent_balance_cents"] == 15_000
    assert registrant["compliance_status"] == "DELINQUENT"
    site = validate_success(api.get_collection_site(chain["site_id"], ADMIN))
    assert site["units_on_hand"] == 14
    assert site["units_reported_total"] == 14


def test_a_documented_declination_discharges_the_obligation_without_penalty(api):
    """PRD §3.8: "Waiving supplies a `waiver_reference` recording the declination,
    and moves the delivery `SCHEDULED → WAIVED` with `units_takeback_collected` set
    to 0, `breach_units` at 0 and `breach_penalty_cents` at 0. No units move into the
    receiving site, nothing is added to any lifetime total, and no penalty is charged
    — a documented declination discharges the obligation cleanly."

    Design: Corner/state_machines/take_back_waiver_is_the_third_outgoing_edge_without_penalty
    """
    chain = take_back_chain(api)
    delivery = create_take_back(
        api,
        chain["registrant_id"],
        chain["site_id"],
        delivery_reference="DEL-1003",
        units_delivered_new=10,
        units_takeback_offered=10,
    )

    waived = waive_take_back(api, delivery["id"], chain["registrant_id"], "WVR-2026-77")

    assert waived["status"] == "WAIVED"
    assert waived["waiver_reference"] == "WVR-2026-77"
    assert waived["units_takeback_collected"] == 0
    assert waived["breach_units"] == 0
    assert waived["breach_penalty_cents"] == 0
    registrant = validate_success(api.get_registrant(chain["registrant_id"], ADMIN))
    assert registrant["takeback_breach_count"] == 0
    assert registrant["delinquent_balance_cents"] == 0
    site = validate_success(api.get_collection_site(chain["site_id"], ADMIN))
    assert site["units_on_hand"] == 0
    assert site["units_reported_total"] == 0


def test_reinstating_a_suspended_site_restarts_its_strike_counter(api):
    """PRD §3.5: "Reinstatement moves the site `SUSPENDED → ENROLLED`, resets
    `contamination_strike_count` to 0 so the strike counter restarts, and increments
    the program's `enrolled_site_count` by one; it is blocked while an infestation
    quarantine is still running, which is to say it requires either that
    `infestation_quarantine_until` is null or that the logical clock has reached or
    passed it, and a site still inside its quarantine window is refused with
    `ERR_SITE_QUARANTINED`."

    Design: Corner/state_machines/site_suspend_reinstate_cycle_resets_contamination_strike_counter
    """
    chain = setup_logistics_chain(api)
    order = dispatch_order(
        api,
        chain["site_id"],
        chain["recycler_id"],
        hauler_id=chain["hauler_id"],
        units_manifested=100,
        route_distance_km=40.0,
        pickup_window_start="2026-08-05T09:00:00Z",
        pickup_window_end="2026-08-05T10:00:00Z",
    )
    pickup_and_deliver(api, order["id"], chain["hauler_id"], 100)
    inspection = validate_success(
        api.create_load_inspection(
            order["id"],
            {"contaminated_unit_count": 6, "infestation_finding": "NONE"},
            chain["recycler_headers"],
        ),
        201,
    )
    assert inspection["disposition"] == "FULL_REJECT"

    suspended = suspend_site(api, chain["site_id"], "OPERATOR_REQUESTED_PAUSE")
    assert suspended["enrollment_status"] == "SUSPENDED"
    assert suspended["suspended_at"] == "2026-08-01T00:00:00Z"
    assert suspended["contamination_strike_count"] == 1
    assert read_program(api, chain["program_id"])["enrolled_site_count"] == 0

    reinstated = reinstate_site(api, chain["site_id"])

    assert reinstated["enrollment_status"] == "ENROLLED"
    assert reinstated["contamination_strike_count"] == 0
    assert read_program(api, chain["program_id"])["enrolled_site_count"] == 1
    assert_custody_buckets(reinstated, 410, 0, 0, 0, 100, reported_total=510)


def test_suspending_a_site_cancels_its_open_routes_and_spares_the_delivered_one(api):
    """PRD §3.5: "Suspension moves it `ENROLLED → SUSPENDED`, carries a `reason`,
    stamps `suspended_at` from the logical clock, and decrements the program's
    `enrolled_site_count` by one; it also reaches into logistics, cancelling every
    pickup order of this site whose `fulfillment_status` is `SCHEDULED` or
    `PICKED_UP` — each such order's `fulfillment_status` becomes `CANCELLED`, its
    `settlement_status` becomes `VOIDED`, and its manifested units move back out of
    the site's `units_in_transit` into `units_on_hand`."

    Design: Corner/state_machines/manual_site_suspension_cancels_only_open_pickup_orders
    """
    chain = setup_logistics_chain(api)
    hauler = create_hauler(
        api,
        chain["program_id"],
        company_name="Puget Fleet Hauling",
        max_concurrent_routes=3,
    )

    def dispatch(window_start, window_end):
        return dispatch_order(
            api,
            chain["site_id"],
            chain["recycler_id"],
            hauler_id=hauler["id"],
            units_manifested=100,
            route_distance_km=40.0,
            pickup_window_start=window_start,
            pickup_window_end=window_end,
        )

    delivered = dispatch("2026-08-05T06:00:00Z", "2026-08-05T07:00:00Z")
    pickup_and_deliver(api, delivered["id"], hauler["id"], 100)
    picked_up = dispatch("2026-08-05T09:00:00Z", "2026-08-05T10:00:00Z")
    validate_success(api.confirm_pickup(picked_up["id"], make_hauler_headers(hauler["id"])))
    scheduled = dispatch("2026-08-05T12:00:00Z", "2026-08-05T13:00:00Z")

    site = suspend_site(api, chain["site_id"], "REPEATED_MANIFEST_ERRORS")

    assert site["enrollment_status"] == "SUSPENDED"
    cancelled_scheduled = validate_success(api.get_pickup_order(scheduled["id"], ADMIN))
    assert cancelled_scheduled["fulfillment_status"] == "CANCELLED"
    assert cancelled_scheduled["settlement_status"] == "VOIDED"
    cancelled_picked_up = validate_success(api.get_pickup_order(picked_up["id"], ADMIN))
    assert cancelled_picked_up["fulfillment_status"] == "CANCELLED"
    assert cancelled_picked_up["settlement_status"] == "VOIDED"
    untouched = validate_success(api.get_pickup_order(delivered["id"], ADMIN))
    assert untouched["fulfillment_status"] == "DELIVERED"
    assert untouched["settlement_status"] == "ESTIMATED"
    assert untouched["estimated_payment_cents"] == 54_700
    assert_custody_buckets(site, 410, 0, 100, 0, 0, reported_total=510)
    assert validate_success(api.get_hauler(hauler["id"], ADMIN))["active_route_count"] == 1


def test_a_facility_whose_certification_is_suspended_can_no_longer_receive_loads(api):
    """PRD §3.7: "Suspending certification moves it `CERTIFIED → SUSPENDED`, carries
    a `reason`, and clears `certified_at` to null; while a facility is suspended, new
    pickup orders naming it are refused."

    Design: Corner/state_machines/recycler_certification_suspension_clears_certified_at_and_blocks_dispatch
    """
    chain = setup_logistics_chain(api)

    suspended = suspend_certification(api, chain["recycler_id"], "OUTPUT_AUDIT_FAILURE")

    assert suspended["certification_status"] == "SUSPENDED"
    assert suspended["certified_at"] is None

    response = api.create_pickup_order(
        {
            "collection_site_id": chain["site_id"],
            "recycler_id": chain["recycler_id"],
            "hauler_id": chain["hauler_id"],
            "units_manifested": 100,
            "route_distance_km": 40.0,
            "pickup_window_start": "2026-08-05T09:00:00Z",
            "pickup_window_end": "2026-08-05T10:00:00Z",
        },
        chain["site_headers"],
    )

    validate_error(response, "ERR_RECYCLER_NOT_CERTIFIED", 409)
    site = validate_success(api.get_collection_site(chain["site_id"], ADMIN))
    assert_custody_buckets(site, 510, 0, 0, 0, 0, reported_total=510)
    assert validate_success(api.get_hauler(chain["hauler_id"], ADMIN))["active_route_count"] == 0


def test_a_recorded_inspection_cannot_be_replaced_by_a_harsher_one(api):
    """PRD §3.7: "An inspection has a single lifecycle state, `RECORDED`, which is
    both where it begins and where it ends: creation is its only event, it is never
    advanced, amended or withdrawn, and the whole of its effect lands in the request
    that writes it."

    Design: Corner/state_machines/load_inspection_recorded_is_both_initial_and_terminal_state
    """
    chain = setup_inspected_order(api, contaminated_unit_count=12, units_delivered=240)

    response = api.create_load_inspection(
        chain["order_id"],
        {"contaminated_unit_count": 200, "infestation_finding": "BED_BUG"},
        chain["recycler_headers"],
    )

    validate_error(response, "ERR_LOAD_ALREADY_INSPECTED", 409)
    inspections, meta = validate_paginated(
        api.list_load_inspections(chain["order_id"], chain["recycler_headers"])
    )
    assert meta["total_count"] == 1
    assert inspections[0]["disposition"] == "PARTIAL_ACCEPT"
    assert inspections[0]["units_accepted"] == 228
    assert inspections[0]["contamination_pct"] == pytest.approx(5.00)
    site = validate_success(api.get_collection_site(chain["site_id"], ADMIN))
    assert site["contamination_strike_count"] == 0
    assert site["infestation_quarantine_until"] is None


def test_a_closed_audit_is_terminal_so_the_cash_can_no_longer_be_refunded(api):
    """PRD §3.3: "A refund is only legal from `PAID`; from any other status the
    answer is `ERR_REMITTANCE_NOT_PAID`."

    Design: Corner/state_machines/audit_closed_remittance_is_terminal_and_refuses_refund
    """
    chain = setup_paid_remittance(api)
    open_audit(api, chain["remittance_id"])
    closed = close_audit(api, chain["remittance_id"])
    assert closed["status"] == "AUDIT_CLOSED"

    response = api.refund_sales_remittance(
        chain["remittance_id"],
        {"amount_cents": 550_000, "reason": "POST_CLOSURE_ADJUSTMENT"},
        ADMIN,
    )

    validate_error(response, "ERR_REMITTANCE_NOT_PAID", 409)
    stored = validate_success(api.get_sales_remittance(chain["remittance_id"], ADMIN))
    assert stored["status"] == "AUDIT_CLOSED"
    assert stored["fee_paid_cents"] == 550_000
    assert stored["fee_refunded_cents"] == 0
    assert stored["fee_reconciled_cents"] == 550_000
    assert stored["balance_due_cents"] == 0
    program = read_program(api, chain["program_id"])
    assert program["fee_collected_cents"] == 550_000
    assert program["reserve_balance_cents"] == 5_550_000
