"""SLA breach discipline and provider inbox burden measurement."""
from test_helpers import (
    Scenario,
    assert_burden_summary,
    assert_same_instant,
    message_in_review,
    provider_pool_practice,
    validate_success,
)


class TestSlaBreachBoundary:
    def _setup_triaged_urgent_from_receipt(self):
        """FROM_RECEIPT pool (URGENT target 120); message received at 10:00 and
        triaged URGENT, so response_due_at is 12:00. No staff reply is sent."""
        ctx = provider_pool_practice(with_biller=False, with_coverage=False,
                                     deadline_policy="FROM_RECEIPT")
        scn = ctx["scn"]
        msg = scn.send_message(ctx["patient"], subject="SLA", body="urgent")
        triaged = scn.triage(msg["id"], ctx["nurse"], "URGENT", "CLINICAL",
                             ctx["pool"]["id"])
        assert_same_instant(triaged["response_due_at"], "2026-08-03T12:00:00Z",
                            label="response_due_at")
        return ctx, msg

    def test_sla_no_breach_at_exact_deadline(self, api):
        """PRD §2.12: "A message is SLA-breached when its effective response
        moment — `first_response_at` if a staff reply has been sent, otherwise
        the current logical-clock time — is strictly later than
        `response_due_at`. Landing exactly on the deadline is not a breach."

        Design: Difficulty/boundary_precision_check/sla_breach_strictly_greater_than_due
        """
        ctx, msg = self._setup_triaged_urgent_from_receipt()
        scn = ctx["scn"]
        scn.set_clock("2026-08-03T12:00:00Z")
        sweep = validate_success(api.run_sla_sweep(scn.admin), 200)
        assert sweep["newly_breached_count"] == 0, (
            "landing exactly on the deadline is not a breach"
        )
        after = scn.get_message(msg["id"])
        assert after["sla_breached"] is False

    def test_sla_breach_one_second_after_deadline(self, api):
        """PRD §2.12: "A message is SLA-breached when its effective response
        moment — `first_response_at` if a staff reply has been sent, otherwise
        the current logical-clock time — is strictly later than
        `response_due_at`."
        PRD §2.12: "a `PracticeAdmin` may also invoke the SLA sweep capability,
        which evaluates every message not in `RESOLVED` or `CLOSED` with a
        non-null `response_due_at`, persists newly detected breaches, and
        reports `swept_count` (messages evaluated) and `newly_breached_count`
        (messages newly flagged)."

        One second past the deadline the sweep must persist the breach.

        Design: Difficulty/boundary_precision_check/sla_breach_strictly_greater_than_due
        """
        ctx, msg = self._setup_triaged_urgent_from_receipt()
        scn = ctx["scn"]
        scn.set_clock("2026-08-03T12:00:01Z")
        sweep = validate_success(api.run_sla_sweep(scn.admin), 200)
        assert sweep["newly_breached_count"] == 1, (
            "strictly-greater comparison: one second past due must breach"
        )
        after = scn.get_message(msg["id"])
        assert after["sla_breached"] is True


class TestOverloadFlagBoundary:
    def test_overload_flag_boundary_at_threshold(self, api):
        """PRD §2.11: "Whenever `open_inbox_count` changes, the boolean
        `inbox_overloaded` is re-evaluated: it is true exactly when the count is
        five or more. At the boundary, a count of five flags the staff member as
        overloaded; a count of four does not."

        Four assigned messages: flag false. A fifth assignment: flag true.
        Completing one drops the count to four and the flag back to false.

        Design: Corner/calculations/overload_flag_boundary_at_threshold
        """
        ctx = provider_pool_practice(with_biller=False)
        scn = ctx["scn"]
        provider = ctx["provider"]
        message_ids = []
        for i in range(1, 5):
            msg = scn.send_message(ctx["patient"], subject=f"A{i}", body=str(i))
            scn.triage(msg["id"], ctx["nurse"], "ROUTINE", "ADMINISTRATIVE",
                       ctx["pool"]["id"])
            scn.assign(msg["id"], ctx["nurse"], staff_id=provider["id"])
            message_ids.append(msg["id"])

        at_four = scn.get_staff(provider["id"])
        assert at_four["open_inbox_count"] == 4
        assert at_four["inbox_overloaded"] is False, (
            "a count of four does not flag the provider"
        )

        msg5 = scn.send_message(ctx["patient"], subject="A5", body="5")
        scn.triage(msg5["id"], ctx["nurse"], "ROUTINE", "ADMINISTRATIVE",
                   ctx["pool"]["id"])
        scn.assign(msg5["id"], ctx["nurse"], staff_id=provider["id"])
        at_five = scn.get_staff(provider["id"])
        assert at_five["open_inbox_count"] == 5
        assert at_five["inbox_overloaded"] is True, (
            "five open assigned messages must flag the provider as overloaded"
        )

        scn.start_review(message_ids[0], provider)
        scn.complete(message_ids[0], provider, summary="done")
        back_to_four = scn.get_staff(provider["id"])
        assert back_to_four["open_inbox_count"] == 4
        assert back_to_four["inbox_overloaded"] is False, (
            "dropping back to four must clear the overload flag"
        )


class TestBurdenSummary:
    def test_burden_summary_zero_state(self, api):
        """PRD §3.8: "The summary reports the staff member's stored
        `open_inbox_count` and `inbox_overloaded`, and adds three aggregates:
        `attributed_resolutions`, counting messages whose `resolved_by_id` names
        the staff member and whose `status` is `RESOLVED` or `CLOSED`;
        `touched_resolutions`, counting the distinct messages on which the staff
        member logged any time entry regardless of who resolved them; and
        `clinical_minutes`, the sum of `minutes` over the staff member's own
        `CLINICAL_REVIEW` entries."

        A brand-new provider's summary is all zeros.

        Design: Corner/endpoints/burden_summary_zero_state
        """
        scn = Scenario()
        provider = scn.add_staff("PROVIDER", "Dr Z")
        data = scn.burden(provider["id"])
        assert_burden_summary(data)
        assert data["open_inbox_count"] == 0
        assert data["inbox_overloaded"] is False
        assert data["attributed_resolutions"] == 0
        assert data["touched_resolutions"] == 0
        assert data["clinical_minutes"] == 0


class TestBurdenAttributedVsTouched:
    def _setup_two_message_burden(self):
        """P1 resolves M1 personally; M2 is worked by P1 (6 clinical minutes)
        but completed by the delegate nurse and cosigned by P2."""
        ctx = provider_pool_practice(with_biller=False)
        scn = ctx["scn"]
        delegate = scn.add_staff("NURSE", "Nurse Dee")
        p1 = ctx["provider"]
        p2 = scn.add_staff("PROVIDER", "Dr Two")
        scn.add_grant(p2, delegate["id"], ctx["pool"]["id"])

        # M1: P1 works and resolves it personally.
        m1 = message_in_review(ctx, urgency="URGENT", category="CLINICAL",
                               subject="M1", assignee_key="provider")
        scn.log_time(m1["id"], p1, 8, entry_kind="CLINICAL_REVIEW")
        scn.complete(m1["id"], p1, summary="M1 done")

        # M2: delegate nurse claims via the grant; P1 logs time; nurse
        # completes (cosign required); P2 cosigns.
        m2 = scn.send_message(ctx["patient"], subject="M2", body="M2 body")
        scn.triage(m2["id"], ctx["nurse"], "ROUTINE", "CLINICAL",
                   ctx["pool"]["id"])
        scn.assign(m2["id"], ctx["nurse"], staff_id=delegate["id"])
        scn.start_review(m2["id"], delegate)
        scn.log_time(m2["id"], p1, 6, entry_kind="CLINICAL_REVIEW")
        pending = scn.complete(m2["id"], delegate, summary="M2 drafted")
        assert pending["status"] == "PENDING_COSIGN"
        scn.cosign(m2["id"], p2, "COSIGN")
        return ctx, p1, p2, m1, m2

    def test_burden_attributed_counts_only_personally_resolved(self, api):
        """PRD §3.8: "`attributed_resolutions`, counting messages whose
        `resolved_by_id` names the staff member and whose `status` is `RESOLVED`
        or `CLOSED`".
        PRD §3.8: "a message resolved by another provider but worked by this one
        counts under `TOUCHED` and not under `ATTRIBUTED`."

        P1 personally resolved only M1 (M2 was resolved by P2's cosign), so
        attributed_resolutions is 1.

        Design: Difficulty/dual_variant_calc/burden_attributed_vs_touched
        """
        ctx, p1, p2, m1, m2 = self._setup_two_message_burden()
        scn = ctx["scn"]
        data = scn.burden(p1["id"])
        assert_burden_summary(data)
        assert data["attributed_resolutions"] == 1, (
            f"only M1 was resolved by P1, got "
            f"{data['attributed_resolutions']}"
        )
        m2_after = scn.get_message(m2["id"])
        assert m2_after["status"] == "RESOLVED"
        assert m2_after["resolved_by_id"] == p2["id"], (
            "M2's resolver is the cosigning provider, not P1"
        )

    def test_burden_touched_counts_messages_with_time_entries(self, api):
        """PRD §3.8: "`touched_resolutions`, counting the distinct messages on
        which the staff member logged any time entry regardless of who resolved
        them; and `clinical_minutes`, the sum of `minutes` over the staff
        member's own `CLINICAL_REVIEW` entries."

        P1 logged time on both M1 (8) and M2 (6): touched is 2 and
        clinical_minutes is 14 — the two variants diverge on identical
        underlying data.

        Design: Difficulty/dual_variant_calc/burden_attributed_vs_touched
        """
        ctx, p1, _p2, _m1, _m2 = self._setup_two_message_burden()
        scn = ctx["scn"]
        data = scn.burden(p1["id"])
        assert data["touched_resolutions"] == 2, (
            f"P1 logged time on both messages, got "
            f"{data['touched_resolutions']}"
        )
        assert data["clinical_minutes"] == 14, (
            f"8 + 6 clinical minutes, got {data['clinical_minutes']}"
        )
        assert data["open_inbox_count"] == 0, (
            "both messages are RESOLVED, so nothing remains open"
        )
        assert data["touched_resolutions"] != data["attributed_resolutions"]
