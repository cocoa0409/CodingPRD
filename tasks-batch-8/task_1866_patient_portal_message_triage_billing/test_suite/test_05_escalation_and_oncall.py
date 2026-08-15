"""After-hours escalation, the on-call selector, and inbox-count conservation."""
from test_helpers import (
    ApiErrorId,
    assert_escalation,
    assert_same_instant,
    escalate_payload,
    provider_pool_practice,
    staff_headers,
    validate_error,
    validate_success,
)


def _setup_escalatable(scn, ctx, urgency="URGENT"):
    """Message triaged to the provider pool with the given urgency."""
    msg = scn.send_message(ctx["patient"], subject="S", body="B")
    scn.triage(msg["id"], ctx["nurse"], urgency, "CLINICAL", ctx["pool"]["id"])
    return msg


class TestEscalationLifecycle:
    def test_escalate_acknowledge_moves_message_to_in_review(self, api):
        """PRD §3.5: "The escalation must still be `OPEN` — an
        already-acknowledged one fails with `ERR_ESCALATION_INVALID_STATE` — and
        the caller must be the on-call provider named on it, with anyone else
        rejected as `ERR_NOT_ASSIGNEE`. The escalation moves to `ACKNOWLEDGED`
        with `acknowledged_at` stamped, and the message returns to `IN_REVIEW`
        with the assignee retained and counts unchanged, both being counted
        statuses."

        Design: Corner/state_machines/escalate_acknowledge_moves_message_to_in_review
        """
        ctx = provider_pool_practice(with_biller=False)
        scn = ctx["scn"]
        p3 = scn.add_staff("PROVIDER", "Dr P3")
        scn.add_on_call_shift(p3["id"], "2026-08-03T08:00:00Z",
                              "2026-08-03T20:00:00Z")
        msg = _setup_escalatable(scn, ctx, urgency="URGENT")

        esc = scn.escalate(msg["id"], ctx["nurse"], reason="after-hours urgent")
        assert_escalation(esc)
        assert esc["status"] == "OPEN"
        assert esc["provider_id"] == p3["id"]
        escalated = scn.get_message(msg["id"])
        assert escalated["status"] == "ESCALATED"
        assert escalated["assignee_id"] == p3["id"]

        ack = scn.acknowledge_escalation(esc["id"], p3)
        assert ack["status"] == "ACKNOWLEDGED"
        assert_same_instant(ack["acknowledged_at"], "2026-08-03T10:00:00Z",
                            label="acknowledged_at (logical clock)")
        after = scn.get_message(msg["id"])
        assert after["status"] == "IN_REVIEW"
        assert after["assignee_id"] == p3["id"], "assignee retained"

        resp_again = api.acknowledge_escalation(esc["id"], staff_headers(p3))
        validate_error(resp_again, ApiErrorId.ERR_ESCALATION_INVALID_STATE)

    def test_escalate_routine_urgency_rejected(self, api):
        """PRD §3.5: "Three gates then apply in order: the state gate just
        named; an urgency gate requiring `urgency` to be `URGENT` or `EMERGENT`
        (`ROUTINE` messages are rejected with `ERR_URGENCY_NOT_ESCALATABLE`);
        and the on-call selector, which must yield a provider or the escalation
        fails with `ERR_NO_ONCALL_COVERAGE`."

        Design: Corner/state_machines/escalate_routine_urgency_rejected
        """
        ctx = provider_pool_practice(with_biller=False)
        scn = ctx["scn"]
        p3 = scn.add_staff("PROVIDER", "Dr P3")
        scn.add_on_call_shift(p3["id"], "2026-08-03T08:00:00Z",
                              "2026-08-03T20:00:00Z")
        msg = _setup_escalatable(scn, ctx, urgency="ROUTINE")
        resp = api.escalate_message(msg["id"], escalate_payload("not urgent"),
                                    staff_headers(ctx["nurse"]))
        validate_error(resp, ApiErrorId.ERR_URGENCY_NOT_ESCALATABLE)
        _escs, meta = scn.list_escalations(message_id=msg["id"])
        assert meta["total_count"] == 0, (
            "no Escalation may be created for a ROUTINE message"
        )


class TestOnCallSelector:
    def test_oncall_selector_empty_fallback(self, api):
        """PRD §3.5: "An empty candidate set is the `ERR_NO_ONCALL_COVERAGE`
        fallback above."

        With no shift covering the logical now, escalation is rejected and the
        message stays TRIAGED with no assignee.

        Design: Corner/cross_cutting_layers/oncall_selector_empty_fallback
        """
        ctx = provider_pool_practice(with_biller=False)
        scn = ctx["scn"]
        msg = _setup_escalatable(scn, ctx, urgency="URGENT")
        resp = api.escalate_message(msg["id"], escalate_payload("nobody home"),
                                    staff_headers(ctx["nurse"]))
        validate_error(resp, ApiErrorId.ERR_NO_ONCALL_COVERAGE)
        after = scn.get_message(msg["id"])
        assert after["status"] == "TRIAGED"
        assert after.get("assignee_id") is None
        _escs, meta = scn.list_escalations(message_id=msg["id"])
        assert meta["total_count"] == 0

    def test_oncall_selector_tie_break_earliest_created(self, api):
        """PRD §3.5: "Candidates are ranked by their covering shift's
        `start_utc`, earliest-starting first; ties break by the covering shift's
        `created_at`, earliest-created first. Neither the shift's nor the
        provider's `id` ever participates in ranking or tie-breaking."

        Two providers hold identical shifts [17:00, 23:00]; PA's shift was
        created at 09:00 and PB's at 09:01, so PA wins the tie.

        Design: Corner/cross_cutting_layers/oncall_selector_tie_break_earliest_created
        """
        ctx = provider_pool_practice(with_biller=False)
        scn = ctx["scn"]
        pa = scn.add_staff("PROVIDER", "Dr PA")
        pb = scn.add_staff("PROVIDER", "Dr PB")
        scn.set_clock("2026-08-03T09:00:00Z")
        scn.add_on_call_shift(pa["id"], "2026-08-03T17:00:00Z",
                              "2026-08-03T23:00:00Z")
        scn.set_clock("2026-08-03T09:01:00Z")
        scn.add_on_call_shift(pb["id"], "2026-08-03T17:00:00Z",
                              "2026-08-03T23:00:00Z")
        scn.set_clock("2026-08-03T18:00:00Z")
        msg = scn.send_message(ctx["patient"], subject="S", body="B")
        scn.triage(msg["id"], ctx["nurse"], "URGENT", "CLINICAL",
                   ctx["pool"]["id"])

        esc = scn.escalate(msg["id"], ctx["nurse"], reason="tie test")
        assert esc["provider_id"] == pa["id"], (
            "the earliest-created covering shift must win the tie"
        )
        after = scn.get_message(msg["id"])
        assert after["assignee_id"] == pa["id"]

    def test_escalation_reverse_lookup_after_escalate(self, api):
        """PRD §3.5: "A successful escalation creates an `Escalation` resource
        in `OPEN` status with the reason, the message's `message_id`, and a
        `provider_id` chosen by the selector — the call therefore returns `201
        Created`."
        PRD §3.5: "Escalation lists may be filtered by `message_id`,
        `provider_id`, and `status`."

        Design: Corner/endpoints/escalation_reverse_lookup_after_escalate
        """
        ctx = provider_pool_practice(with_biller=False)
        scn = ctx["scn"]
        p3 = scn.add_staff("PROVIDER", "Dr P3")
        scn.add_on_call_shift(p3["id"], "2026-08-03T08:00:00Z",
                              "2026-08-03T20:00:00Z")
        msg = _setup_escalatable(scn, ctx, urgency="URGENT")

        resp = api.escalate_message(msg["id"], escalate_payload("after hours"),
                                    staff_headers(ctx["nurse"]))
        esc = validate_success(resp, 201)
        assert_escalation(esc)
        assert esc["status"] == "OPEN"
        assert esc["provider_id"] == p3["id"]
        assert esc["message_id"] == msg["id"]

        data, meta = scn.list_escalations(message_id=msg["id"])
        assert meta["total_count"] == 1
        assert data[0]["id"] == esc["id"]
        assert data[0]["status"] == "OPEN"
        assert data[0]["provider_id"] == p3["id"]

        after = scn.get_message(msg["id"])
        assert after["status"] == "ESCALATED"
        assert after["assignee_id"] == p3["id"]


class TestOpenInboxCountConservation:
    def _setup_chain(self):
        """Nurse, providers P1/P2, on-call P3 ([08:00, 20:00]); an URGENT
        message triaged to the provider pool at 10:00."""
        ctx = provider_pool_practice(with_biller=False)
        scn = ctx["scn"]
        p1 = ctx["provider"]
        p2 = scn.add_staff("PROVIDER", "Dr P2")
        p3 = scn.add_staff("PROVIDER", "Dr P3")
        scn.add_on_call_shift(p3["id"], "2026-08-03T08:00:00Z",
                              "2026-08-03T20:00:00Z")
        msg = _setup_escalatable(scn, ctx, urgency="URGENT")
        return scn, ctx, msg, p1, p2, p3

    def test_open_count_forward_and_zero_sum_moves(self, api):
        """PRD §3.3: "The assign call accepts an optional `staff_id`: when
        present, the named staff member becomes the `assignee_id`, their
        `open_inbox_count` rises by one, and the message enters `ASSIGNED`".
        PRD §2.11: "reassignment-style operations (re-route, escalation,
        delegation-revoke cascade) are zero-sum across staff: the global sum of
        `open_inbox_count` over all staff always equals the number of messages
        in counted statuses with a non-null assignee."

        Assign P1 (+1); re-route to P2 (P1 -1, P2 +1); escalate to the on-call
        provider P3 (P2 -1, P3 +1).

        Design: Difficulty/compensating_invariant/open_inbox_count_conservation
        """
        scn, ctx, msg, p1, p2, p3 = self._setup_chain()
        scn.assign(msg["id"], ctx["nurse"], staff_id=p1["id"])
        assert scn.get_staff(p1["id"])["open_inbox_count"] == 1

        scn.assign(msg["id"], ctx["nurse"], staff_id=p2["id"])
        assert scn.get_staff(p1["id"])["open_inbox_count"] == 0
        assert scn.get_staff(p2["id"])["open_inbox_count"] == 1

        esc = scn.escalate(msg["id"], ctx["nurse"], reason="patient worsening")
        assert esc["provider_id"] == p3["id"]
        assert scn.get_staff(p2["id"])["open_inbox_count"] == 0
        assert scn.get_staff(p3["id"])["open_inbox_count"] == 1
        after = scn.get_message(msg["id"])
        assert after["status"] == "ESCALATED"
        assert after["assignee_id"] == p3["id"]

    def test_open_count_compensating_complete_returns_to_zero(self, api):
        """PRD §3.4: "When cosign is not required, completion resolves the
        message outright: `resolved_by_id` records the caller, `resolved_at`
        stamps the logical now, the assignee's `open_inbox_count` falls by one
        with `inbox_overloaded` re-evaluated, and the SLA flag latches per
        §2.12."
        PRD §2.11: "the global sum of `open_inbox_count` over all staff always
        equals the number of messages in counted statuses with a non-null
        assignee."

        After the full assign -> re-route -> escalate -> acknowledge ->
        complete chain, every staff member is back to zero.

        Design: Difficulty/compensating_invariant/open_inbox_count_conservation
        """
        scn, ctx, msg, p1, p2, p3 = self._setup_chain()
        scn.assign(msg["id"], ctx["nurse"], staff_id=p1["id"])
        scn.assign(msg["id"], ctx["nurse"], staff_id=p2["id"])
        esc = scn.escalate(msg["id"], ctx["nurse"], reason="patient worsening")
        scn.acknowledge_escalation(esc["id"], p3)
        final = scn.complete(msg["id"], p3, summary="resolved by on-call")
        assert final["status"] == "RESOLVED"

        for staff, label in ((p1, "P1"), (p2, "P2"), (p3, "P3")):
            after = scn.get_staff(staff["id"])
            assert after["open_inbox_count"] == 0, (
                f"{label} must be back to 0 after the compensating complete, "
                f"got {after['open_inbox_count']}"
            )
            assert after["inbox_overloaded"] is False
