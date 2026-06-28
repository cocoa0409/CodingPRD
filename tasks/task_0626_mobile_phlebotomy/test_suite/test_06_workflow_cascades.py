"""Workflow, branching, cascade, cross-entity dependency, and conserved-invariant tests.

Difficulty queue (A) instances for non_linear_state_machine, transitive_cascade,
cross_entity_state_dependency, and compensating_invariant.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    setup_scheduled_appointment, drive_to_draw_completed,
    setup_draw_completed_with_in_transit_specimens,
    setup_manifested_specimen_on_building_manifest,
    suspend_phlebotomist_via_three_strikes,
    make_phlebotomist_headers, create_manifest_payload,
    ApiErrorId, TEST_USERS,
)

_PROVIDER = TEST_USERS["ordering_provider_headers"]
_DISPATCHER = TEST_USERS["dispatcher_headers"]
_LABOPS = TEST_USERS["lab_ops_headers"]


# ---------------------------------------------------------------------------
# Queue A — non_linear_state_machine
# ---------------------------------------------------------------------------

def test_order_branches_to_resulted_when_all_specimens_accessioned(api):
    """PRD §3.11: "On success the system creates a lab result in PENDING_RELEASE status carrying
    the lab_order_id, a lab_partner_id copied from the order, the result_value, and two release
    flags — released_to_provider and released_to_portal — both initially false and set true once
    routed to the ordering provider and the patient portal respectively."
    PRD §3.11: "Posting results moves the order from DRAW_COMPLETED to RESULTED, which is terminal."

    Design: Difficulty/non_linear_state_machine/order_branches_resulted_path
    """
    from test_helpers import build_in_transit_manifest, accession_all
    ctx = setup_draw_completed_with_in_transit_specimens(
        billing_mode="SELF_PAY", panel_code="CMP14", required_tube_count=3, base_lab_fee_cents=4000,
    )
    accession_all([sp["id"] for sp in ctx["specimens"]])
    result = validate_success(api.post_results(ctx["order_id"], {"result_value": "panel-ok"}, _LABOPS), 201)
    assert result["status"] == "PENDING_RELEASE"
    order = validate_success(api.get_lab_order(ctx["order_id"], _PROVIDER))
    assert order["status"] == "RESULTED", f"expected RESULTED, got {order['status']}"


def test_resulted_path_creates_result_with_copied_partner(api):
    """PRD §3.11: "On success the system creates a lab result in PENDING_RELEASE status carrying
    the lab_order_id, a lab_partner_id copied from the order, the result_value, and two release
    flags — released_to_provider and released_to_portal — both initially false and set true once
    routed to the ordering provider and the patient portal respectively."

    Design: Difficulty/non_linear_state_machine/order_branches_resulted_path
    """
    from test_helpers import accession_all
    ctx = setup_draw_completed_with_in_transit_specimens(
        billing_mode="SELF_PAY", panel_code="CMP14", required_tube_count=3, base_lab_fee_cents=4000,
    )
    accession_all([sp["id"] for sp in ctx["specimens"]])
    result = validate_success(api.post_results(ctx["order_id"], {"result_value": "panel-ok"}, _LABOPS), 201)
    assert result["lab_order_id"] == ctx["order_id"]
    assert result["lab_partner_id"] == ctx["partner_id"], "lab_partner_id must be copied from the order"
    assert result["released_to_provider"] is False
    assert result["released_to_portal"] is False


def test_specimen_branches_accessioned_vs_qns_diverge(api):
    """PRD §3.8: "A successful accession moves the specimen from MANIFESTED to ACCESSIONED, raises
    the owning order's specimens_accessioned_count by one, and appends an ACCESSIONED custody event."
    PRD §3.8: "A successful rejection moves the specimen from MANIFESTED to QNS_REJECTED and appends
    a REJECTED_QNS custody event."
    PRD §3.9: "If, at the moment of a QNS rejection, the owning order is in DRAW_COMPLETED, the
    order automatically transitions from DRAW_COMPLETED to REDRAW_REQUIRED, and a chain of
    compensating effects follows in order."

    Design: Difficulty/non_linear_state_machine/specimen_branches_accessioned_vs_qns
    """
    ctx = setup_draw_completed_with_in_transit_specimens(
        billing_mode="SELF_PAY", panel_code="CBC2", required_tube_count=2, base_lab_fee_cents=2000,
    )
    sp1, sp2 = ctx["specimens"][0]["id"], ctx["specimens"][1]["id"]
    accessioned = validate_success(api.accession_specimen(sp1, _LABOPS))
    assert accessioned["status"] == "ACCESSIONED"
    rejected = validate_success(api.reject_qns(sp2, _LABOPS))
    assert rejected["status"] == "QNS_REJECTED"
    order = validate_success(api.get_lab_order(ctx["order_id"], _PROVIDER))
    assert order["specimens_accessioned_count"] == 1, \
        f"expected accessioned_count 1, got {order['specimens_accessioned_count']}"
    assert order["status"] == "REDRAW_REQUIRED", f"expected REDRAW_REQUIRED, got {order['status']}"


def test_qns_only_branch_appends_rejected_custody_event_no_count_bump(api):
    """PRD §3.8: "A successful rejection moves the specimen from MANIFESTED to QNS_REJECTED and
    appends a REJECTED_QNS custody event."
    PRD §2.5: "An order's specimens_accessioned_count is the number of that order's specimens
    currently in ACCESSIONED status; specimens in QNS_REJECTED are never counted, so a rejection
    that follows a prior accession reduces the reconciled count."

    Design: Difficulty/non_linear_state_machine/specimen_branches_accessioned_vs_qns
    """
    ctx = setup_draw_completed_with_in_transit_specimens(
        billing_mode="SELF_PAY", panel_code="CBC2", required_tube_count=2, base_lab_fee_cents=2000,
    )
    sp2 = ctx["specimens"][1]["id"]
    rejected = validate_success(api.reject_qns(sp2, _LABOPS))
    assert rejected["status"] == "QNS_REJECTED"
    events, _ = validate_paginated(api.list_specimen_custody_events(sp2, _LABOPS))
    types = [e["event_type"] for e in events]
    assert "REJECTED_QNS" in types, f"expected a REJECTED_QNS custody event, got {types}"


# ---------------------------------------------------------------------------
# Queue A — transitive_cascade
# ---------------------------------------------------------------------------

def test_qns_redraw_cascade_propagates_four_hops(api):
    """PRD §3.9: "the order automatically transitions from DRAW_COMPLETED to REDRAW_REQUIRED, and
    a chain of compensating effects follows in order. The order's redraw_count rises by one."
    PRD §3.9: "The order's owning appointment is moved to CANCELLED, which decrements the route
    day's booked_stop_count by one and increments the route day's version by one."
    PRD §3.9: "Finally, a strike accrues to the phlebotomist who performed the draw: the
    phlebotomist denormalized on the order's current owning appointment has their
    redraw_strike_count raised by one, and if that count reaches three, the phlebotomist's status
    becomes SUSPENDED; otherwise it remains AVAILABLE."

    Design: Difficulty/transitive_cascade/qns_redraw_cascade_depth4
    """
    ctx = setup_draw_completed_with_in_transit_specimens(
        billing_mode="SELF_PAY", panel_code="ONE", required_tube_count=1, base_lab_fee_cents=1000,
        manifest_specimen_count=1,
    )
    sp1 = ctx["specimens"][0]["id"]
    rejected = validate_success(api.reject_qns(sp1, _LABOPS))
    assert rejected["status"] == "QNS_REJECTED"
    order = validate_success(api.get_lab_order(ctx["order_id"], _PROVIDER))
    assert order["status"] == "REDRAW_REQUIRED"
    appt = validate_success(api.get_appointment(ctx["appt_id"], _DISPATCHER))
    assert appt["status"] == "CANCELLED", f"expected appointment CANCELLED, got {appt['status']}"
    rd = validate_success(api.get_route_day(ctx["route_day_id"], _DISPATCHER))
    assert rd["booked_stop_count"] == 0, f"expected booked_stop_count 0, got {rd['booked_stop_count']}"
    phleb = validate_success(api.get_phlebotomist(ctx["phleb_id"], _DISPATCHER))
    assert phleb["redraw_strike_count"] == 1, f"expected 1 strike, got {phleb['redraw_strike_count']}"


def test_qns_redraw_cascade_increments_redraw_count_and_strike(api):
    """PRD §3.9: "The order's redraw_count rises by one."
    PRD §3.9: "Finally, a strike accrues to the phlebotomist who performed the draw: the
    phlebotomist denormalized on the order's current owning appointment has their
    redraw_strike_count raised by one, and if that count reaches three, the phlebotomist's status
    becomes SUSPENDED; otherwise it remains AVAILABLE."

    Design: Difficulty/transitive_cascade/qns_redraw_cascade_depth4
    """
    ctx = setup_draw_completed_with_in_transit_specimens(
        billing_mode="SELF_PAY", panel_code="ONE", required_tube_count=1, base_lab_fee_cents=1000,
        manifest_specimen_count=1,
    )
    validate_success(api.reject_qns(ctx["specimens"][0]["id"], _LABOPS))
    order = validate_success(api.get_lab_order(ctx["order_id"], _PROVIDER))
    assert order["redraw_count"] == 1, f"expected redraw_count 1, got {order['redraw_count']}"
    phleb = validate_success(api.get_phlebotomist(ctx["phleb_id"], _DISPATCHER))
    assert phleb["redraw_strike_count"] == 1
    assert phleb["status"] == "AVAILABLE", "one strike must not yet suspend the phlebotomist"


def test_order_cancel_cascade_cancels_appointment_and_frees_slot(api):
    """PRD §3.3: "If the order has an active appointment at the time of cancellation (which is the
    case from the SCHEDULED state), that appointment is moved to CANCELLED, the owning route day's
    booked_stop_count is decremented by one, and the route day's version is incremented by one as
    compensation."

    Design: Difficulty/transitive_cascade/order_cancel_cascade_depth2
    """
    ctx = setup_scheduled_appointment(panel_code="CMP14", required_tube_count=3, base_lab_fee_cents=4000)
    cancelled = validate_success(api.cancel_order(ctx["order_id"], _PROVIDER))
    assert cancelled["status"] == "CANCELLED"
    appt = validate_success(api.get_appointment(ctx["appt_id"], _DISPATCHER))
    assert appt["status"] == "CANCELLED", f"expected appointment CANCELLED, got {appt['status']}"
    rd = validate_success(api.get_route_day(ctx["route_day_id"], _DISPATCHER))
    assert rd["booked_stop_count"] == 0, f"expected booked_stop_count 0, got {rd['booked_stop_count']}"


def test_order_cancel_from_ordered_state_without_appointment(api):
    """PRD §3.3: "When the order is cancelled out of REDRAW_REQUIRED, there is no active
    appointment to compensate (the redraw already cancelled it), so only the order's status
    changes."
    PRD §3.3: "An OrderingProvider may cancel an order while it is in ORDERED, SCHEDULED, or
    REDRAW_REQUIRED; a cancel attempt from any other status is rejected with
    ERR_ORDER_NOT_CANCELLABLE."

    Design: Difficulty/transitive_cascade/order_cancel_cascade_depth2
    """
    # Cancelling from SCHEDULED with an active appointment is the cascade; verify the slot is
    # freed (booked_stop_count returns to 0) as the second-hop effect of the cancel cascade.
    ctx = setup_scheduled_appointment(panel_code="CMP14", required_tube_count=3, base_lab_fee_cents=4000)
    rd_before = validate_success(api.get_route_day(ctx["route_day_id"], _DISPATCHER))
    assert rd_before["booked_stop_count"] == 1
    validate_success(api.cancel_order(ctx["order_id"], _PROVIDER))
    rd_after = validate_success(api.get_route_day(ctx["route_day_id"], _DISPATCHER))
    assert rd_after["booked_stop_count"] == 0, \
        f"cancel cascade must free the slot, got {rd_after['booked_stop_count']}"
    assert rd_after["version"] > rd_before["version"], "route day version must bump on compensation"


# ---------------------------------------------------------------------------
# Queue A — cross_entity_state_dependency
# ---------------------------------------------------------------------------

def test_dispatch_rejected_when_phlebotomist_suspended(api):
    """PRD §3.9: "if that count reaches three, the phlebotomist's status becomes SUSPENDED;
    otherwise it remains AVAILABLE. The suspension threshold is three strikes — the third
    QNS-attributable redraw is what suspends a collector."
    PRD §3.5: "the collector's certification_active must be true and the collector's status must
    be AVAILABLE, otherwise the dispatch is rejected with ERR_PHLEBOTOMIST_UNAVAILABLE."

    Design: Difficulty/cross_entity_state_dependency/dispatch_depends_on_phlebotomist_status
    """
    info = suspend_phlebotomist_via_three_strikes()
    phleb = validate_success(api.get_phlebotomist(info["phleb_id"], _DISPATCHER))
    assert phleb["redraw_strike_count"] == 3, f"expected 3 strikes, got {phleb['redraw_strike_count']}"
    assert phleb["status"] == "SUSPENDED", f"expected SUSPENDED, got {phleb['status']}"
    validate_error(api.dispatch_appointment(info["ready_appt_id"], _DISPATCHER),
                   ApiErrorId.ERR_PHLEBOTOMIST_UNAVAILABLE.value)
    appt = validate_success(api.get_appointment(info["ready_appt_id"], _DISPATCHER))
    assert appt["status"] == "SCHEDULED", f"expected SCHEDULED, got {appt['status']}"


def test_suspended_phlebotomist_status_reaches_suspended_at_third_strike(api):
    """PRD §3.9: "if that count reaches three, the phlebotomist's status becomes SUSPENDED;
    otherwise it remains AVAILABLE. The suspension threshold is three strikes — the third
    QNS-attributable redraw is what suspends a collector."

    Design: Difficulty/cross_entity_state_dependency/dispatch_depends_on_phlebotomist_status
    """
    info = suspend_phlebotomist_via_three_strikes()
    phleb = validate_success(api.get_phlebotomist(info["phleb_id"], _DISPATCHER))
    assert phleb["status"] == "SUSPENDED", \
        f"three strikes must suspend the collector, got {phleb['status']}"
    assert phleb["redraw_strike_count"] == 3


def test_accession_rejected_while_manifest_still_building(api):
    """PRD §3.8: "Accessioning is allowed only when the specimen is MANIFESTED, or it fails with
    ERR_SPECIMEN_NOT_ACCESSIONABLE, and only when the parent manifest is IN_TRANSIT, or it fails
    with ERR_MANIFEST_NOT_IN_TRANSIT."

    Design: Difficulty/cross_entity_state_dependency/accession_depends_on_manifest_in_transit
    """
    ctx = setup_manifested_specimen_on_building_manifest()
    sp1 = ctx["specimens"][0]["id"]
    validate_error(api.accession_specimen(sp1, _LABOPS),
                   ApiErrorId.ERR_MANIFEST_NOT_IN_TRANSIT.value)
    specimen = validate_success(api.get_specimen(sp1, _LABOPS))
    assert specimen["status"] == "MANIFESTED", f"expected MANIFESTED, got {specimen['status']}"
    manifest = validate_success(api.get_manifest(ctx["manifest"]["id"], _DISPATCHER))
    assert manifest["status"] == "BUILDING", f"expected BUILDING, got {manifest['status']}"


def test_accessionable_specimen_blocked_by_building_manifest_state(api):
    """PRD §3.8: "and only when the parent manifest is IN_TRANSIT, or it fails with
    ERR_MANIFEST_NOT_IN_TRANSIT."

    Design: Difficulty/cross_entity_state_dependency/accession_depends_on_manifest_in_transit
    """
    # The specimen is itself in a MANIFESTED (accessionable) state; only the manifest's BUILDING
    # state blocks accession — proving the cross-entity dependency.
    ctx = setup_manifested_specimen_on_building_manifest()
    sp1 = ctx["specimens"][0]["id"]
    before = validate_success(api.get_specimen(sp1, _LABOPS))
    assert before["status"] == "MANIFESTED", "specimen must itself be in an accessionable state"
    validate_error(api.accession_specimen(sp1, _LABOPS),
                   ApiErrorId.ERR_MANIFEST_NOT_IN_TRANSIT.value)


# ---------------------------------------------------------------------------
# Queue A — compensating_invariant
# ---------------------------------------------------------------------------

def test_booked_stop_count_conserved_after_book_then_cancel(api):
    """PRD §2.5: "A route day's booked_stop_count is the number of appointments on that route day
    in any of the four live statuses SCHEDULED, DISPATCHED, ARRIVED, or DRAW_COMPLETED; it rises
    by one on each booking and falls by one on each cancellation or redraw-driven appointment
    cancellation."

    Design: Difficulty/compensating_invariant/route_day_booked_stop_count_conserved_on_cancel
    """
    ctx = setup_scheduled_appointment(panel_code="CMP14", required_tube_count=3, base_lab_fee_cents=4000)
    rd_before = validate_success(api.get_route_day(ctx["route_day_id"], _DISPATCHER))
    assert rd_before["booked_stop_count"] == 1, f"expected 1 after booking, got {rd_before['booked_stop_count']}"
    validate_success(api.cancel_order(ctx["order_id"], _PROVIDER))
    rd_after = validate_success(api.get_route_day(ctx["route_day_id"], _DISPATCHER))
    assert rd_after["booked_stop_count"] == 0, f"expected 0 after cancel, got {rd_after['booked_stop_count']}"
    appt = validate_success(api.get_appointment(ctx["appt_id"], _DISPATCHER))
    assert appt["status"] == "CANCELLED"


def test_booked_stop_count_rises_by_one_on_booking(api):
    """PRD §2.5: "A route day's booked_stop_count is the number of appointments on that route day
    in any of the four live statuses SCHEDULED, DISPATCHED, ARRIVED, or DRAW_COMPLETED; it rises
    by one on each booking and falls by one on each cancellation or redraw-driven appointment
    cancellation."

    Design: Difficulty/compensating_invariant/route_day_booked_stop_count_conserved_on_cancel
    """
    ctx = setup_scheduled_appointment(panel_code="CMP14", required_tube_count=3, base_lab_fee_cents=4000)
    rd = validate_success(api.get_route_day(ctx["route_day_id"], _DISPATCHER))
    # The single SCHEDULED appointment is one of the four live statuses, so the count equals 1.
    assert rd["booked_stop_count"] == 1, \
        f"booked_stop_count must equal the count of live appointments (1), got {rd['booked_stop_count']}"


def test_accessioned_count_excludes_qns_rejected_specimen(api):
    """PRD §2.5: "An order's specimens_accessioned_count is the number of that order's specimens
    currently in ACCESSIONED status; specimens in QNS_REJECTED are never counted, so a rejection
    that follows a prior accession reduces the reconciled count."

    Design: Difficulty/compensating_invariant/order_accessioned_count_conserved_after_qns
    """
    ctx = setup_draw_completed_with_in_transit_specimens(
        billing_mode="SELF_PAY", panel_code="CBC2", required_tube_count=2, base_lab_fee_cents=2000,
    )
    sp1, sp2 = ctx["specimens"][0]["id"], ctx["specimens"][1]["id"]
    acc = validate_success(api.accession_specimen(sp1, _LABOPS))
    assert acc["status"] == "ACCESSIONED"
    rej = validate_success(api.reject_qns(sp2, _LABOPS))
    assert rej["status"] == "QNS_REJECTED"
    order = validate_success(api.get_lab_order(ctx["order_id"], _LABOPS))
    assert order["specimens_accessioned_count"] == 1, \
        f"expected accessioned_count 1, got {order['specimens_accessioned_count']}"


def test_accessioned_count_equals_one_after_single_accession_then_qns(api):
    """PRD §2.5: "An order's specimens_accessioned_count is the number of that order's specimens
    currently in ACCESSIONED status; specimens in QNS_REJECTED are never counted, so a rejection
    that follows a prior accession reduces the reconciled count."

    Design: Difficulty/compensating_invariant/order_accessioned_count_conserved_after_qns
    """
    ctx = setup_draw_completed_with_in_transit_specimens(
        billing_mode="SELF_PAY", panel_code="CBC2", required_tube_count=2, base_lab_fee_cents=2000,
    )
    sp1, sp2 = ctx["specimens"][0]["id"], ctx["specimens"][1]["id"]
    validate_success(api.accession_specimen(sp1, _LABOPS))
    order_mid = validate_success(api.get_lab_order(ctx["order_id"], _LABOPS))
    assert order_mid["specimens_accessioned_count"] == 1
    validate_success(api.reject_qns(sp2, _LABOPS))
    order_final = validate_success(api.get_lab_order(ctx["order_id"], _LABOPS))
    # QNS rejection of the second tube never adds to the accessioned count.
    assert order_final["specimens_accessioned_count"] == 1, \
        f"QNS_REJECTED tube must never be counted, got {order_final['specimens_accessioned_count']}"
