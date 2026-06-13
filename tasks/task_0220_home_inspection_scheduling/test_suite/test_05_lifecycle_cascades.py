"""Order lifecycle branching, cancellation/delivery cascades, terminal lockdown,
fiscal conservation, re-inspection gating, and reverse-reachability reads.
"""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId, TEST_USERS, make_client_headers,
    setup_requested_order, setup_scheduled_order,
    setup_report_draft_order, setup_approved_report, setup_delivered_order,
    setup_delivered_failing_parent, add_defects, reinspect, assert_money_conserved,
)
from test_helpers import factories as F

SCHED = TEST_USERS["scheduler_headers"]


# ---------------------------------------------------------------------------
# branching state machine: REPORT_DRAFT cancel branch voids the report
# ---------------------------------------------------------------------------
def test_order_report_draft_cancel_branch_voids_report(api):
    """PRD §3.9: "Any report on the order is moved to `VOIDED`, and as a consequence of
    that void, all of that report's non-`VOIDED` defects are themselves moved to
    `VOIDED`."
    PRD §3.9: "A `Scheduler` may cancel any non-terminal order — one whose `status` is
    `REQUESTED`, `SCHEDULED`, `IN_PROGRESS`, or `REPORT_DRAFT` — moving it to the
    terminal `CANCELLED` state and triggering a coordinated unwind."

    Design: Difficulty/non_linear_state_machine/order_branches_deliver_vs_cancel
    """
    # Report approved (order still REPORT_DRAFT), then cancel via the cancel branch.
    cfg, order, report, _ = setup_approved_report(
        inspection_type="BUYER", certifications=["BUYER"],
        scheduled_start="2026-07-05T13:00:00Z")
    cancelled = validate_success(api.cancel_order(order["id"], SCHED))
    assert cancelled["status"] == "CANCELLED"
    voided_report = validate_success(api.get_report(report["id"], SCHED))
    assert voided_report["status"] == "VOIDED"


def test_order_report_draft_deliver_branch_reaches_delivered(api):
    """PRD §3.5: "Delivery is the closing act, performed by a `Scheduler`: it moves a
    `REPORT_DRAFT` order to `DELIVERED`."
    PRD §3.9: "A `Scheduler` may cancel any non-terminal order — one whose `status` is
    `REQUESTED`, `SCHEDULED`, `IN_PROGRESS`, or `REPORT_DRAFT` — moving it to the
    terminal `CANCELLED` state and triggering a coordinated unwind."

    Design: Difficulty/non_linear_state_machine/order_branches_deliver_vs_cancel
    """
    # Same starting state (REPORT_DRAFT, report APPROVED) but take the DELIVER fork.
    cfg, order, report, _ = setup_delivered_order(
        inspection_type="BUYER", certifications=["BUYER"],
        scheduled_start="2026-07-25T13:00:00Z", pay_amount=43000)
    assert order["status"] == "DELIVERED"
    # The report is finalized (delivered-locked), not voided.
    final_report = validate_success(api.get_report(report["id"], SCHED))
    assert final_report["status"] != "VOIDED"


# ---------------------------------------------------------------------------
# transitive cascade depth 3: cancel -> report VOIDED -> defect VOIDED
# ---------------------------------------------------------------------------
def test_cancel_cascades_to_report_and_defect(api):
    """PRD §3.9: "Any report on the order is moved to `VOIDED`, and as a consequence of
    that void, all of that report's non-`VOIDED` defects are themselves moved to
    `VOIDED`."

    Design: Difficulty/transitive_cascade/cancel_order_voids_report_then_defects_depth3
    """
    cfg, order, report = setup_report_draft_order(
        inspection_type="BUYER", certifications=["BUYER"],
        scheduled_start="2026-07-06T13:00:00Z")
    defect = add_defects(report["id"], cfg["inspector"]["id"], [("Panel", "MAJOR")])[0]
    cancelled = validate_success(api.cancel_order(order["id"], SCHED))
    assert cancelled["status"] == "CANCELLED"
    voided_report = validate_success(api.get_report(report["id"], SCHED))
    assert voided_report["status"] == "VOIDED"
    defects = get_success_data(api.list_defects(report["id"], SCHED))
    matched = [d for d in defects if d["id"] == defect["id"]]
    assert len(matched) == 1 and matched[0]["status"] == "VOIDED"


def test_cancel_voids_all_defects_on_report(api):
    """PRD §3.9: "Any report on the order is moved to `VOIDED`, and as a consequence of
    that void, all of that report's non-`VOIDED` defects are themselves moved to
    `VOIDED`."

    Design: Difficulty/transitive_cascade/cancel_order_voids_report_then_defects_depth3
    """
    # Two distinct defects on the report -> both follow the report to VOIDED.
    cfg, order, report = setup_report_draft_order(
        inspection_type="BUYER", certifications=["BUYER"],
        scheduled_start="2026-07-31T13:00:00Z")
    defects = add_defects(report["id"], cfg["inspector"]["id"],
                          [("Panel", "MAJOR"), ("Foundation", "CRITICAL")])
    validate_success(api.cancel_order(order["id"], SCHED))
    listed = get_success_data(api.list_defects(report["id"], SCHED))
    by_id = {d["id"]: d for d in listed}
    for created in defects:
        assert by_id[created["id"]]["status"] == "VOIDED"


# ---------------------------------------------------------------------------
# transitive cascade depth 2: deliver -> report locked + two SENT deliveries
# ---------------------------------------------------------------------------
def test_deliver_creates_two_sent_deliveries_with_band_snapshot(api):
    """PRD §3.5: "On delivery the system creates exactly two delivery rows, one with
    `recipient_kind` of `CLIENT` and one of `AGENT`, each in `SENT` status. Each row
    stamps a `recipient_email` captured from the corresponding client or agent at
    delivery time and a `severity_band_snapshot` copied from the report's grade at that
    moment."
    PRD §3.6: "A score from 133 up to but not including 666 yields `MAJOR` — so a single
    confirmed `MAJOR` defect, at 133, lands exactly on the `MAJOR` floor."

    Design: Difficulty/transitive_cascade/deliver_order_locks_report_creates_deliveries_depth2
    """
    # One MAJOR defect -> final 133 -> band MAJOR.
    cfg, order, report, _ = setup_delivered_order(
        inspection_type="BUYER", certifications=["BUYER"],
        scheduled_start="2026-07-07T13:00:00Z",
        defects=[("Panel", "MAJOR")], pay_amount=43000)
    assert order["status"] == "DELIVERED"
    deliveries, meta = validate_paginated(api.list_deliveries(order["id"], SCHED))
    assert len(deliveries) == 2
    assert all(d["status"] == "SENT" for d in deliveries)
    assert all(d["severity_band_snapshot"] == "MAJOR" for d in deliveries)
    kinds = sorted(d["recipient_kind"] for d in deliveries)
    assert kinds == ["AGENT", "CLIENT"]


def test_deliver_snapshots_critical_band_into_deliveries(api):
    """PRD §3.5: "a `severity_band_snapshot` copied from the report's grade at that
    moment."
    PRD §3.6: "A score of 666 or more yields `CRITICAL` — so two confirmed `CRITICAL`
    defects, at 666, land exactly on the `CRITICAL` floor."

    Design: Difficulty/transitive_cascade/deliver_order_locks_report_creates_deliveries_depth2
    """
    # Two CRITICAL defects -> final 666 -> band CRITICAL, snapshotted on both deliveries.
    cfg, order, report, _ = setup_delivered_order(
        inspection_type="BUYER", certifications=["BUYER"],
        scheduled_start="2026-08-21T13:00:00Z",
        defects=[("Panel", "CRITICAL"), ("Foundation", "CRITICAL")], pay_amount=43000)
    assert order["status"] == "DELIVERED"
    deliveries, meta = validate_paginated(api.list_deliveries(order["id"], SCHED))
    assert len(deliveries) == 2
    assert all(d["severity_band_snapshot"] == "CRITICAL" for d in deliveries)
    assert all(d["status"] == "SENT" for d in deliveries)


# ---------------------------------------------------------------------------
# compensating invariant: pay then cancel conserves money (full refund)
# ---------------------------------------------------------------------------
def test_pay_then_cancel_full_refund_conserves_money(api):
    """PRD §2.9: "When an order is cancelled, every cent recorded as paid is refunded,
    so the cumulative refunded total equals the cumulative paid total and the net
    collected on a cancelled order is zero."
    PRD §3.9: "Every cent of `amount_paid_cents` is refunded by adding it to
    `amount_refunded_cents`, conserving money so that nothing remains net-collected."

    Design: Difficulty/compensating_invariant/pay_then_cancel_conserves_order_money
    """
    # Scheduled BUYER 2200 quoted 40600; pay 43000 (overpaid); then cancel.
    cfg, order = setup_scheduled_order(inspection_type="BUYER", certifications=["BUYER"],
                                       scheduled_start="2026-07-18T13:00:00Z",
                                       square_footage=2200)
    get_success_data(api.pay_order(order["id"], F.pay_order_payload(43000), SCHED))
    cancelled = validate_success(api.cancel_order(order["id"], SCHED))
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["amount_paid_cents"] == 43000
    assert cancelled["amount_refunded_cents"] == 43000
    assert_money_conserved(cancelled)


def test_exact_payment_then_cancel_refunds_in_full(api):
    """PRD §2.9: "When an order is cancelled, every cent recorded as paid is refunded,
    so the cumulative refunded total equals the cumulative paid total and the net
    collected on a cancelled order is zero. Money is neither created nor destroyed by any
    transition."

    Design: Difficulty/compensating_invariant/pay_then_cancel_conserves_order_money
    """
    # Pay exactly the quoted fee (40600) then cancel -> refunded equals paid.
    cfg, order = setup_scheduled_order(inspection_type="BUYER", certifications=["BUYER"],
                                       scheduled_start="2026-08-22T13:00:00Z",
                                       square_footage=2200)
    get_success_data(api.pay_order(order["id"], F.pay_order_payload(40600), SCHED))
    cancelled = validate_success(api.cancel_order(order["id"], SCHED))
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["amount_paid_cents"] == 40600
    assert cancelled["amount_refunded_cents"] == 40600
    assert_money_conserved(cancelled)


# ---------------------------------------------------------------------------
# deliver gated on full payment (fiscal check isolated)
# ---------------------------------------------------------------------------
def test_deliver_unpaid_order_returns_order_unpaid(api):
    """PRD §3.5: "Delivery is gated on three conditions — the order must be in
    `REPORT_DRAFT` (else `ERR_INVALID_STATE`), the order's report must be `APPROVED`, and
    the order must be fully paid, meaning `amount_due_cents` is at most 0; an attempt to
    deliver an order that still owes money is rejected with `ERR_ORDER_UNPAID`."

    Design: Corner/validations/corner_deliver_unpaid_only_returns_unpaid
    """
    # Report APPROVED but order never paid -> amount_due_cents > 0.
    cfg, order, report, _ = setup_approved_report(
        inspection_type="BUYER", certifications=["BUYER"],
        scheduled_start="2026-08-15T13:00:00Z", pay_amount=None)
    resp = api.deliver_order(order["id"], SCHED)
    validate_error(resp, ApiErrorId.ERR_ORDER_UNPAID.value)


# ---------------------------------------------------------------------------
# re-inspection gating
# ---------------------------------------------------------------------------
def test_reinspect_passing_parent_not_warranted(api):
    """PRD §3.8: "The parent report's `severity_band` must be `MAJOR` or `CRITICAL`,
    since only a failing inspection warrants a re-inspection; a parent that graded `PASS`
    or `MINOR` is rejected with `ERR_REINSPECTION_NOT_WARRANTED`."

    Design: Corner/validations/corner_reinspection_not_warranted_rejected
    """
    # Parent DELIVERED with ZERO defects -> severity_band PASS.
    cfg, order, report, _ = setup_delivered_order(
        inspection_type="BUYER", certifications=["BUYER"],
        scheduled_start="2026-08-09T13:00:00Z", defects=[], pay_amount=43000)
    resp = reinspect(order["id"], cfg["inspector"]["id"], "2026-08-12T13:00:00Z",
                     order["version"])
    validate_error(resp, ApiErrorId.ERR_REINSPECTION_NOT_WARRANTED.value)


def test_reinspect_too_soon_within_48_hours(api):
    """PRD §3.8: "The new `scheduled_start` must be at least 48 hours after the parent
    order's `scheduled_start`, or the request is rejected with `ERR_REINSPECTION_TOO_SOON`."

    Design: Corner/validations/corner_reinspection_too_soon_rejected
    """
    # Parent scheduled 2026-08-13T13:00; reinspect at +24h is too soon.
    cfg, parent, report = setup_delivered_failing_parent(
        inspection_type="BUYER", certifications=["BUYER"],
        scheduled_start="2026-08-13T13:00:00Z", property_sqft=2200,
        measured_square_footage=2200, defects=[("Panel", "MAJOR")],
        addons=None, pay_amount=43000)
    resp = reinspect(parent["id"], cfg["inspector"]["id"], "2026-08-14T13:00:00Z",
                     parent["version"])
    validate_error(resp, ApiErrorId.ERR_REINSPECTION_TOO_SOON.value)


def test_reinspect_stale_parent_version_rejected(api):
    """PRD §2.8: "If `expected_order_version` does not equal the parent order's current
    `version`, the request is rejected with `ERR_STALE_VERSION` and HTTP status 412."
    PRD §2.8: "a first re-inspection call legitimately creates the child and advances the
    parent, while a second call that still carries the pre-spawn `version` is detected as
    stale and rejected, preventing a duplicate re-inspection for the same delivered order."

    Design: Corner/cross_cutting_complexity_layers/corner_occ_stale_parent_version_reinspect
    """
    cfg, parent, report = setup_delivered_failing_parent(
        inspection_type="BUYER", certifications=["BUYER"],
        scheduled_start="2026-08-18T09:00:00Z", property_sqft=2200,
        measured_square_footage=2200, defects=[("Panel", "MAJOR")],
        addons=None, pay_amount=43000)
    stale_version = parent["version"]
    # First reinspect succeeds and bumps the parent version.
    first = reinspect(parent["id"], cfg["inspector"]["id"], "2026-08-25T09:00:00Z",
                      stale_version)
    validate_success(first, 201)
    # Second reinspect still carrying the pre-spawn version is stale.
    second = reinspect(parent["id"], cfg["inspector"]["id"], "2026-08-26T09:00:00Z",
                       stale_version)
    validate_error(second, ApiErrorId.ERR_STALE_VERSION.value)


# ---------------------------------------------------------------------------
# reverse-reachability read: list an order's add-ons
# ---------------------------------------------------------------------------
def test_list_order_addons_returns_attached_addons(api):
    """PRD §3.4: "An **AddOn** is created with only a `kind` of `RADON`, `TERMITE`, or
    `SEWER`; on creation the system stamps it with the matching `order_id`."

    Design: Corner/endpoints/corner_list_addons_reverse_reachability
    """
    cfg, order = setup_requested_order(inspection_type="BUYER")
    addon = validate_success(
        api.create_addon(order["id"], F.create_addon_payload("RADON"), SCHED), 201)
    cli_headers = make_client_headers(cfg["client"]["id"])
    addons, meta = validate_paginated(api.list_addons(order["id"], cli_headers))
    assert len(addons) == 1
    assert addons[0]["kind"] == "RADON"
    assert addons[0]["id"] == addon["id"]
