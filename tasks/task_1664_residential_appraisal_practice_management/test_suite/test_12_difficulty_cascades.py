"""Difficulty queue A: transitive cascades — the sanction close chain and
the delivery retention pin (PRD 3.6, 3.8)."""
from test_helpers import (
    accept_order,
    assign_order,
    close_complaint,
    confirm_appointment,
    create_appointment,
    create_complaint,
    create_order,
    create_workfile,
    deliver_report,
    draft_complaint,
    first_workfile_of_type,
    get_order,
    get_scorecard,
    scope_order,
    set_clock,
    setup_delivered_order,
    setup_report_qc_passed,
    submit_complaint,
    validate_success,
)
from test_helpers import ADMIN


def _setup_sanction_cascade():
    """Order A desktop-delivered 2026-08-02 (complaint target); order B
    ASSIGNED to the same appraiser with a CONFIRMED appointment
    2026-08-09 09:00-10:00; complaint on A submitted, then closed
    SANCTIONED at 2026-08-20."""
    ctx = setup_delivered_order(delivery_clock="2026-08-02T00:00:00Z")

    order_b = create_order(
        ctx["client"]["id"], property_address="77 Birch Ln", requested_turn_days=14
    )
    order_b = scope_order(order_b["id"])
    order_b = accept_order(order_b["id"])
    order_b = assign_order(order_b["id"], ctx["appraiser"]["id"])
    appointment_b = create_appointment(
        order_b["id"],
        ctx["appraiser"]["id"],
        "2026-08-09T09:00:00Z",
        "2026-08-09T10:00:00Z",
    )
    confirm_appointment(appointment_b["id"], ctx["appraiser"]["id"])

    set_clock("2026-08-05T00:00:00Z")
    complaint = create_complaint(ctx["order"]["id"], ctx["appraiser"]["id"])
    draft_complaint(complaint["id"])
    submit_complaint(complaint["id"])

    set_clock("2026-08-20T00:00:00Z")
    close_complaint(complaint["id"], "SANCTIONED")
    return ctx, order_b, appointment_b


def test_sanction_close_sets_override_and_removes_memberships(api):
    """PRD 3.8: "First, the respondent appraiser's `sanction_override` is set,
    forcing `standing` to `PANEL_SUSPENDED` until a `FirmAdmin` clears it
    (§3.2)."
    PRD 3.8: "Second, every `ACTIVE` panel membership of the respondent
    moves to `REMOVED`, and every order assigned to the respondent in a
    working state — `ASSIGNED`, `INSPECTION_SCHEDULED`, `INSPECTED`,
    `IN_ANALYSIS`, `DRAFTING`, or `QC_REVIEW` — falls back to `ACCEPTED`
    with `assigned_appraiser_id` nulled and `requires_supervisor_cosign`
    reset to false."

    Design: Difficulty/transitive_cascade/sanction_close_cascades_appraiser_orders_appointments
    """
    ctx, _, _ = _setup_sanction_cascade()

    appraiser = validate_success(
        api.get_appraiser(ctx["appraiser"]["id"], ADMIN), 200
    )
    assert appraiser["sanction_override"] is True

    scorecard = get_scorecard(ctx["appraiser"]["id"])
    assert scorecard["standing"] == "PANEL_SUSPENDED"

    memberships = validate_success(
        api.list_panel_memberships(
            ADMIN, params={"appraiser_id": ctx["appraiser"]["id"]}
        ),
        200,
    )
    assert memberships, "expected the fixture membership to exist"
    assert all(m["status"] == "REMOVED" for m in memberships)


def test_sanction_close_unassigns_orders_and_cancels_appointments(api):
    """PRD 3.8: "every order assigned to the respondent in a working state —
    `ASSIGNED`, `INSPECTION_SCHEDULED`, `INSPECTED`, `IN_ANALYSIS`,
    `DRAFTING`, or `QC_REVIEW` — falls back to `ACCEPTED` with
    `assigned_appraiser_id` nulled and `requires_supervisor_cosign` reset to
    false. Third, each such unassigned order's `PROPOSED` or `CONFIRMED`
    appointments are moved to `CANCELLED`."

    Design: Difficulty/transitive_cascade/sanction_close_cascades_appraiser_orders_appointments
    """
    _, order_b, appointment_b = _setup_sanction_cascade()

    order_after = get_order(order_b["id"])
    assert order_after["status"] == "ACCEPTED"
    assert order_after["assigned_appraiser_id"] is None
    assert order_after["requires_supervisor_cosign"] is False

    appointment_after = validate_success(
        api.get_appointment(appointment_b["id"], ADMIN), 200
    )
    assert appointment_after["status"] == "CANCELLED"


def _setup_deliver_retention_pin():
    """Desktop order through QC_PASSED at clock 2026-08-01, with an extra
    manually-uploaded workfile created before delivery."""
    ctx = setup_report_qc_passed()
    manual = create_workfile(ctx["order"]["id"], "COMP_DATA")
    return ctx, manual


def test_deliver_moves_order_and_stamps_first_delivery(api):
    """PRD 3.6: "Delivery moves the order to `DELIVERED` — from `QC_REVIEW`
    on the first pass, or from `IN_REVISION` on a revised report — stamps
    `first_delivered_at` when it was previously null and never again, files
    `REPORT_PDF` and `CERTIFICATION` workfile records, pins `retention_until`
    on every non-`PURGED` workfile record of the order per §3.8, and, when
    the delivery closes a revision cycle, resolves the order's `ACCEPTED`
    revision request to `RESOLVED`."

    Design: Difficulty/transitive_cascade/deliver_pins_workfile_retention_via_order_delivery
    """
    ctx, manual = _setup_deliver_retention_pin()
    assert manual.get("retention_until") is None, "null pin before first delivery"

    set_clock("2026-08-02T00:00:00Z")
    deliver_report(ctx["report"]["id"], ctx["appraiser"]["id"])

    order = get_order(ctx["order"]["id"])
    assert order["status"] == "DELIVERED"
    assert order["first_delivered_at"] == "2026-08-02T00:00:00Z"


def test_deliver_pins_retention_on_preexisting_workfiles(api):
    """PRD 3.8: "The standard pin is five calendar years after
    `first_delivered_at`, where year addition is calendar-based, preserving
    the month and day."
    PRD 3.6: "pins `retention_until` on every non-`PURGED` workfile record of
    the order per §3.8".

    Design: Difficulty/transitive_cascade/deliver_pins_workfile_retention_via_order_delivery
    """
    ctx, manual = _setup_deliver_retention_pin()
    set_clock("2026-08-02T00:00:00Z")
    deliver_report(ctx["report"]["id"], ctx["appraiser"]["id"])

    record = validate_success(api.get_workfile_record(manual["id"], ADMIN), 200)
    # created long before delivery, pinned by the order's first delivery
    assert record["retention_until"] == "2031-08-02T00:00:00Z"
