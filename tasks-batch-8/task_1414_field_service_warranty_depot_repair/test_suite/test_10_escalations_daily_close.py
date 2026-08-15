"""Escalation lifecycle, monitoring recurrence/expiry, and the daily close."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    authorize_rma,
    consume_part_ok,
    create_draft_rma,
    create_manual_escalation,
    diagnose_rma,
    get_escalation,
    get_rma,
    list_notifications,
    make_depot_technician_headers,
    planned_part_line,
    qa_release,
    receive_rma,
    repair_complete,
    run_daily_close,
    set_clock,
    setup_authorized_rma,
    setup_catalog,
    setup_monitoring_escalation,
    ship_rma,
    triage_rma,
    validate_error,
    validate_success,
)

TECH2 = make_depot_technician_headers("tech-2")


def test_monitoring_recurrence_reopens_escalation(api):
    """PRD §3.8: "Closure also recomputes the recurring-failure score of §3.3
    and performs the recurrence bookkeeping: when a `MONITORING` escalation
    exists for the RMA's (model, primary failure code) pair and the logical
    clock date is on or before its `monitoring_until`, that escalation reopens
    to `OPEN` with its `recurrence_count` incremented by one and an
    `ESCALATION_OPENED` notification on the triggering RMA."

    Design: Corner/state_machines/monitoring_recurrence_reopens_escalation
    """
    ctx = setup_monitoring_escalation()
    esc_id = ctx["esc"]["id"]
    # Cancel the DRAFT trigger RMA, then drive a new RMA for the same unit and
    # failure code all the way to CLOSED.
    validate_success(api.cancel_rma(ctx["rma"]["id"], TEST_USERS["intake_agent_headers"]),
                     200)
    rma_z = create_draft_rma(ctx["customer"]["id"], ctx["unit"]["id"],
                             reported_issue="second")
    authorize_rma(rma_z["id"])
    receive_rma(rma_z["id"], ctx["unit"]["serial_number"])
    triage_rma(rma_z["id"], ctx["fc"]["id"])
    rma_z = diagnose_rma(rma_z["id"], labor_minutes_est=10,
                         planned_parts=[planned_part_line(ctx["part"]["id"], 1)])
    consume_part_ok(rma_z["id"], ctx["part"]["id"], 1, ctx["fc"]["id"],
                    rma_z["version"])
    repair_complete(rma_z["id"])
    qa_release(rma_z["id"], "PASS", tech_headers=TECH2)
    ship_rma(rma_z["id"], tech_headers=TECH2)
    closed = validate_success(
        api.close_rma(rma_z["id"], TEST_USERS["intake_agent_headers"]), 200)
    assert closed["status"] == "CLOSED"

    esc_after = get_escalation(esc_id)
    assert esc_after["status"] == "OPEN", (
        f"the MONITORING escalation must reopen to OPEN, got {esc_after['status']}")
    assert esc_after["recurrence_count"] == 1, (
        f"recurrence_count must increment to 1, got {esc_after['recurrence_count']}")


def test_monitoring_expiry_closes_final_via_daily_close(api):
    """PRD §3.9: "Resolving, which requires a `resolution_note`, is lawful from
    `OPEN`, `ACKNOWLEDGED`, or `CONTAINMENT_ACTIVE`: the escalation moves to
    `RESOLVED` and immediately on to `MONITORING` as an automatic companion
    transition, with `monitoring_until` set to the logical clock date plus 90
    days."
    PRD §3.9: "Once the clock date passes `monitoring_until` without a
    recurrence, the daily close moves the escalation to its terminal
    `CLOSED_FINAL`."

    Design: Corner/state_machines/monitoring_expiry_closes_final_via_daily_close
    """
    ctx = setup_monitoring_escalation()
    esc_id = ctx["esc"]["id"]
    # resolved at 2026-08-01 -> monitoring_until 2026-10-30
    assert ctx["esc"]["monitoring_until"][:10] == "2026-10-30", (
        f"monitoring_until must be 2026-08-01 + 90 days = 2026-10-30, got "
        f"{ctx['esc']['monitoring_until']}")

    set_clock("2026-10-30T00:00:00Z")
    sweep1 = run_daily_close()
    assert esc_id not in sweep1["closed_final_escalation_ids"], (
        "on monitoring_until itself the clock has not passed the date")
    assert get_escalation(esc_id)["status"] == "MONITORING"

    set_clock("2026-10-31T00:00:00Z")
    sweep2 = run_daily_close()
    assert esc_id in sweep2["closed_final_escalation_ids"], (
        "one day past monitoring_until the daily close must close it")
    assert get_escalation(esc_id)["status"] == "CLOSED_FINAL"


def test_escalate_contain_after_resolve_rejected(api):
    """PRD §3.9: "Activating containment — available from either `OPEN` or
    `ACKNOWLEDGED` — moves it to `CONTAINMENT_ACTIVE` and sets the model's
    `containment_flag` true, which is precisely what blocks replacement shipment
    of that model per §3.8."
    PRD §2.8: "Sixth, state-machine legality — whether the target entity is in a
    state permitting the requested transition — yielding the matching error
    among `ERR_INVALID_RMA_STATE`, `ERR_INVALID_QUOTE_STATE`,
    `ERR_INVALID_RESERVATION_STATE`, `ERR_INVALID_LOANER_STATE`,
    `ERR_INVALID_ESCALATION_STATE`, and `ERR_INVALID_LINE_STATE`."

    Design: Corner/state_machines/escalate_contain_after_resolve_rejected
    """
    ctx = setup_monitoring_escalation()
    res = api.contain_escalation(ctx["esc"]["id"],
                                 TEST_USERS["engineering_lead_headers"])
    validate_error(res, ApiErrorId.ERR_INVALID_ESCALATION_STATE)
    assert res.status_code == 409
    after = get_escalation(ctx["esc"]["id"])
    assert after["status"] == "MONITORING"
    assert after["monitoring_until"][:10] == "2026-10-30"


def test_stale_authorized_rma_auto_cancelled_after_30_days(api):
    """PRD §3.9: "Every RMA still in `AUTHORIZED` whose `authorized_at` is more
    than 30 calendar days behind the clock — a unit that was never received —
    is auto-cancelled to `CANCELLED`: its `RESERVED` reservations are cancelled,
    their loaner units return to `AVAILABLE`, the customers' deposit exposure is
    released, and a `CANCELLED` notification fires."

    Design: Corner/state_machines/stale_authorized_rma_auto_cancelled_after_30_days
    """
    ctx = setup_authorized_rma()  # authorized at the default clock 2026-08-01
    rma_id = ctx["rma"]["id"]

    # Exactly 30 days old: not yet stale ("more than 30 calendar days").
    set_clock("2026-08-31T00:00:00Z")
    sweep1 = run_daily_close()
    assert rma_id not in sweep1["auto_cancelled_rma_ids"], (
        "at exactly 30 days the RMA must not be auto-cancelled")
    assert get_rma(rma_id)["status"] == "AUTHORIZED"

    set_clock("2026-09-01T00:00:00Z")
    sweep2 = run_daily_close()
    assert rma_id in sweep2["auto_cancelled_rma_ids"], (
        "at 31 days the never-received RMA must be auto-cancelled")
    assert get_rma(rma_id)["status"] == "CANCELLED"
    events = list_notifications(rma_id, params={"event_type": "CANCELLED"})
    assert len(events) == 1, "a CANCELLED notification must fire on auto-cancel"


def test_sla_breach_only_when_net_strictly_greater(api):
    """PRD §3.9: "When the net is strictly greater than the model's
    `sla_turnaround_business_days` — a net exactly equal to the target is not a
    breach — and the RMA is not already flagged, `sla_breached` is set and an
    `SLA_BREACH` notification fires."
    PRD §2.4: "Wherever this document speaks of business days, a business day is
    a Monday-through-Friday calendar date; there is no holiday calendar. The
    business-day count between two dates is the number of business-day dates
    strictly after the first date and on or before the second date."

    Design: Corner/calculations/sla_breach_only_when_net_strictly_greater
    """
    # Receive Monday 2026-08-03; SLA target 5 business days.
    set_clock("2026-08-03T00:00:00Z")
    ctx = setup_authorized_rma()
    rma_id = ctx["rma"]["id"]
    receive_rma(rma_id, ctx["unit"]["serial_number"])

    # 2026-08-10: business days strictly after 08-03 on/before 08-10 are
    # 08-04..08-07 and 08-10 -> net 5 == target -> no breach.
    set_clock("2026-08-10T00:00:00Z")
    sweep1 = run_daily_close()
    assert rma_id not in sweep1["sla_breached_rma_ids"], (
        "net 5 == target 5 must not breach")
    assert get_rma(rma_id)["sla_breached"] is False

    # 2026-08-11: net 6 > 5 -> breach, exactly one SLA_BREACH notification.
    set_clock("2026-08-11T00:00:00Z")
    sweep2 = run_daily_close()
    assert rma_id in sweep2["sla_breached_rma_ids"], (
        "net 6 > target 5 must breach")
    assert get_rma(rma_id)["sla_breached"] is True
    breaches = list_notifications(rma_id, params={"event_type": "SLA_BREACH"})
    assert len(breaches) == 1, (
        f"exactly one SLA_BREACH notification must fire, got {len(breaches)}")


def test_quote_expiry_swept_by_daily_close(api):
    """PRD §3.9: "In order of concern: every quote still `SENT` whose
    `expires_at` is strictly before the clock becomes `EXPIRED` with a
    `QUOTE_EXPIRED` notification, leaving its RMA paused in
    `AWAITING_QUOTE_APPROVAL` per §3.5."
    PRD §3.5: "A quote's `sent_at` records when it became `SENT`, and its
    `expires_at` is `sent_at` extended by the model's `quote_valid_days`"

    Design: Corner/calculations/quote_expiry_swept_by_daily_close
    """
    from test_helpers import get_quote, setup_awaiting_quote_rma
    ctx = setup_awaiting_quote_rma(quote_valid_days=14)
    q1 = ctx["quote"]
    # sent 2026-08-01 -> expires 2026-08-15; sweep at 2026-08-16.
    set_clock("2026-08-16T00:00:00Z")
    sweep = run_daily_close()
    assert q1["id"] in sweep["expired_quote_ids"], (
        "the sweep must report the expired quote id")
    assert get_quote(q1["id"])["status"] == "EXPIRED"
    assert get_rma(ctx["rma"]["id"])["status"] == "AWAITING_QUOTE_APPROVAL", (
        "the RMA stays paused in AWAITING_QUOTE_APPROVAL")
    expired_events = list_notifications(ctx["rma"]["id"],
                                        params={"event_type": "QUOTE_EXPIRED"})
    assert len(expired_events) == 1, "a QUOTE_EXPIRED notification must fire"
