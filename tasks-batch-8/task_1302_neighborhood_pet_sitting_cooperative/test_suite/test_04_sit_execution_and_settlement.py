"""Sit execution: handoff gating, entry logs, checkout, settlement variants, and
the ledger (PRD §2.4, §3.5, §3.6)."""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId,
    create_entry_log_payload, create_accept_claim_payload, create_claim_payload,
    create_cancel_payload,
    make_member_headers,
    bootstrap_founders, create_pet, post_request, claim_request, accept_claim,
    setup_confirmed_sit, setup_in_progress_sit, setup_completed_sit, setup_settled_sit,
    get_assignment_for_request, get_handoff_for_assignment, get_member, list_ledger,
    set_clock, file_incident, resolve_incident_at_fault,
    ADMIN,
)


class TestEntryLogWindow:
    def test_entry_window_closed_buffered_containment(self, api):
        """PRD §3.5: "Entries are only accepted within the sit's plausible window,
        from 30 minutes before `scheduled_start_at` through 4 hours after
        `scheduled_end_at`, inclusive at both ends; anything outside is rejected
        with `ERR_ENTRY_OUT_OF_WINDOW` (HTTP 422)."

        Design: Difficulty/resource_temporal_overlap/entry_window_closed_buffered_containment
        """
        sit = setup_confirmed_sit()
        asg_id = sit["assignment"]["id"]
        sitter_headers = make_member_headers(sit["sitter"]["id"])

        res = api.create_entry_log(asg_id, create_entry_log_payload(
            "PET_FED", "2026-09-10T09:29:59Z"), sitter_headers)
        validate_error(res, ApiErrorId.ERR_ENTRY_OUT_OF_WINDOW, expected_status=422)

        low = validate_success(api.create_entry_log(asg_id, create_entry_log_payload(
            "PET_FED", "2026-09-10T09:30:00Z"), sitter_headers), 201)
        high = validate_success(api.create_entry_log(asg_id, create_entry_log_payload(
            "PET_FED", "2026-09-10T18:00:00Z"), sitter_headers), 201)

        res = api.create_entry_log(asg_id, create_entry_log_payload(
            "PET_FED", "2026-09-10T18:00:01Z"), sitter_headers)
        validate_error(res, ApiErrorId.ERR_ENTRY_OUT_OF_WINDOW, expected_status=422)

        logs = get_success_data(api.list_entry_logs(asg_id, ADMIN))
        assert len(logs) == 2, f"Only in-window entries may persist, got {len(logs)}"
        assert {e["id"] for e in logs} == {low["id"], high["id"]}

    def test_entry_window_lower_bound_inclusive(self, api):
        """PRD §3.5: "Entries are only accepted within the sit's plausible window,
        from 30 minutes before `scheduled_start_at` through 4 hours after
        `scheduled_end_at`, inclusive at both ends; anything outside is rejected
        with `ERR_ENTRY_OUT_OF_WINDOW` (HTTP 422)."

        Design: Difficulty/resource_temporal_overlap/entry_window_closed_buffered_containment
        """
        sit = setup_confirmed_sit()
        asg_id = sit["assignment"]["id"]
        sitter_headers = make_member_headers(sit["sitter"]["id"])
        res = api.create_entry_log(asg_id, create_entry_log_payload(
            "PET_FED", "2026-09-10T09:30:00Z"), sitter_headers)
        validate_success(res, 201)
        res = api.create_entry_log(asg_id, create_entry_log_payload(
            "PET_FED", "2026-09-10T18:00:00Z"), sitter_headers)
        validate_success(res, 201)

    def test_entry_notes_required_for_medication(self, api):
        """PRD §3.5: "...an `occurred_at` timestamp; and optional `notes` — which
        become required when the event is an `INCIDENT_NOTE` or a
        `MEDICATION_GIVEN`."
        PRD §3.3: "violations are rejected with `ERR_INVALID_REQUEST`."

        Design: Corner/validations/entry_notes_required_for_medication
        """
        sit = setup_confirmed_sit()
        asg_id = sit["assignment"]["id"]
        sitter_headers = make_member_headers(sit["sitter"]["id"])

        res = api.create_entry_log(asg_id, create_entry_log_payload(
            "MEDICATION_GIVEN", "2026-09-10T12:00:00Z"), sitter_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)

        ok = api.create_entry_log(asg_id, create_entry_log_payload(
            "PET_FED", "2026-09-10T12:00:00Z"), sitter_headers)
        validate_success(ok, 201)

        logs = get_success_data(api.list_entry_logs(asg_id, ADMIN))
        assert len(logs) == 1
        assert logs[0]["event_type"] == "PET_FED"


class TestHandoffAndCheckin:
    def test_checkin_blocked_until_handoff(self, api):
        """PRD §3.5: "The first `CHECK_IN` is load-bearing. If the assignment is
        still `CONFIRMED`, that check-in moves the assignment to `IN_PROGRESS` and
        the request to `IN_PROGRESS`, and stamps the assignment's `actual_start_at`
        with the entry's `occurred_at`. But no work may begin without keys: a
        check-in attempted while the handoff is not yet `HANDED_OFF` is rejected
        with `ERR_ACCESS_NOT_HANDED_OFF`."

        Design: Difficulty/cross_entity_state_dependency/checkin_blocked_until_handoff
        """
        sit = setup_confirmed_sit()
        set_clock("2026-09-10T10:00:00Z")  # within the handoff-allowed window
        res = api.create_entry_log(sit["assignment"]["id"], create_entry_log_payload(
            "CHECK_IN", "2026-09-10T10:00:00Z"), make_member_headers(sit["sitter"]["id"]))
        validate_error(res, ApiErrorId.ERR_ACCESS_NOT_HANDED_OFF, expected_status=409)
        logs = get_success_data(api.list_entry_logs(sit["assignment"]["id"], ADMIN))
        assert logs == [], "Rejected CHECK_IN must not persist"

        get_success_data(api.confirm_handoff(
            sit["handoff"]["id"], make_member_headers(sit["owner"]["id"])))
        ok = api.create_entry_log(sit["assignment"]["id"], create_entry_log_payload(
            "CHECK_IN", "2026-09-10T10:00:00Z"), make_member_headers(sit["sitter"]["id"]))
        entry = validate_success(ok, 201)
        assert entry["event_type"] == "CHECK_IN"

        asg = validate_success(api.get_assignment(sit["assignment"]["id"], ADMIN), 200)
        assert asg["status"] == "IN_PROGRESS"
        assert asg["actual_start_at"].startswith("2026-09-10T10:00:00")
        req = validate_success(api.get_sitting_request(sit["request"]["id"], ADMIN), 200)
        assert req["status"] == "IN_PROGRESS"

    def test_checkin_flips_assignment_and_request(self, api):
        """PRD §3.5: "The first `CHECK_IN` is load-bearing. If the assignment is
        still `CONFIRMED`, that check-in moves the assignment to `IN_PROGRESS` and
        the request to `IN_PROGRESS`, and stamps the assignment's `actual_start_at`
        with the entry's `occurred_at`."

        Design: Difficulty/cross_entity_state_dependency/checkin_blocked_until_handoff
        """
        sit = setup_confirmed_sit()
        set_clock("2026-09-10T08:30:00Z")
        handoff = get_success_data(api.confirm_handoff(
            sit["handoff"]["id"], make_member_headers(sit["owner"]["id"])))
        assert handoff["status"] == "HANDED_OFF"
        assert handoff["handed_off_at"] is not None

        set_clock("2026-09-10T10:00:00Z")
        validate_success(api.create_entry_log(sit["assignment"]["id"], create_entry_log_payload(
            "CHECK_IN", "2026-09-10T10:00:00Z"), make_member_headers(sit["sitter"]["id"])), 201)
        asg = validate_success(api.get_assignment(sit["assignment"]["id"], ADMIN), 200)
        assert asg["status"] == "IN_PROGRESS"
        assert asg["actual_start_at"].startswith("2026-09-10T10:00:00")
        req = validate_success(api.get_sitting_request(sit["request"]["id"], ADMIN), 200)
        assert req["status"] == "IN_PROGRESS"

    def test_handoff_too_early_then_boundary(self, api):
        """PRD §3.5: "When the keys physically change hands, the owner confirms the
        handoff; confirmation earlier than two hours before the scheduled start is
        rejected with `ERR_HANDOFF_TOO_EARLY`, and success stamps `handed_off_at`
        and moves the handoff to `HANDED_OFF`."

        Design: Corner/validations/handoff_confirm_too_early_then_exact_boundary
        """
        sit = setup_confirmed_sit()
        set_clock("2026-09-10T07:59:59Z")  # one second before start - 2h
        res = api.confirm_handoff(sit["handoff"]["id"], make_member_headers(sit["owner"]["id"]))
        validate_error(res, ApiErrorId.ERR_HANDOFF_TOO_EARLY, expected_status=409)
        handoff = get_handoff_for_assignment(sit["assignment"]["id"])
        assert handoff["status"] == "PENDING"

        set_clock("2026-09-10T08:00:00Z")  # exactly start - 2h: allowed
        ok = api.confirm_handoff(sit["handoff"]["id"], make_member_headers(sit["owner"]["id"]))
        confirmed = validate_success(ok, 200)
        assert confirmed["status"] == "HANDED_OFF"
        assert confirmed["handed_off_at"].startswith("2026-09-10T08:00:00")

    def test_confirm_return_pending_handoff_rejected(self, api):
        """PRD §3.5: "After the sit, the owner confirms the return of keys — allowed
        only when the assignment has reached `COMPLETED_PENDING_REVIEW`, `SETTLED`,
        `CANCELLED_BY_OWNER`, or `CANCELLED_BY_SITTER` (otherwise
        `ERR_INVALID_STATE`) — stamping `returned_at` and moving the handoff to
        `RETURNED`."

        Design: Corner/state_machines/confirm_return_pending_handoff_returns_invalid_state
        """
        sit = setup_confirmed_sit()
        res = api.confirm_return(sit["handoff"]["id"], make_member_headers(sit["owner"]["id"]))
        validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
        handoff = get_handoff_for_assignment(sit["assignment"]["id"])
        assert handoff["status"] == "PENDING"
        assert handoff["returned_at"] is None

    def test_handoff_report_lost_side_effects(self, api):
        """PRD §3.5: "If the credentials go missing, either the owner or the sitter
        reports the handoff lost; the handoff moves to `LOST`, the system
        automatically files an incident with `severity` `MAJOR` and the description
        "Access credentials lost", and the sitter's `reliability_score` drops by
        10."

        Design: Corner/state_machines/handoff_report_lost_side_effects
        """
        sit = setup_confirmed_sit()
        set_clock("2026-09-10T08:30:00Z")
        get_success_data(api.confirm_handoff(
            sit["handoff"]["id"], make_member_headers(sit["owner"]["id"])))

        res = api.report_lost(sit["handoff"]["id"], make_member_headers(sit["owner"]["id"]))
        handoff = validate_success(res, 200)
        assert handoff["status"] == "LOST"

        incidents = get_success_data(api.list_incidents(sit["assignment"]["id"], ADMIN))
        assert len(incidents) == 1
        assert incidents[0]["severity"] == "MAJOR"
        assert incidents[0]["status"] == "FILED"
        assert incidents[0]["description"] == "Access credentials lost"

        assert get_member(sit["sitter"]["id"])["reliability_score"] == 40


class TestCheckoutAndCompletion:
    def test_checkout_side_effects(self, api):
        """PRD §3.6: "Checkout stamps `actual_end_at` with the current time, appends
        a `CHECK_OUT` entry log, moves the assignment to `COMPLETED_PENDING_REVIEW`,
        and moves the request to `COMPLETED`."

        Design: Corner/state_machines/checkout_side_effects_request_completed
        """
        sit = setup_in_progress_sit()
        set_clock("2026-09-10T14:00:00Z")
        res = api.checkout_assignment(sit["assignment"]["id"],
                                      make_member_headers(sit["sitter"]["id"]))
        asg = validate_success(res, 200)
        assert asg["status"] == "COMPLETED_PENDING_REVIEW"
        assert asg["actual_end_at"].startswith("2026-09-10T14:00:00")

        req = validate_success(api.get_sitting_request(sit["request"]["id"], ADMIN), 200)
        assert req["status"] == "COMPLETED"

        logs = get_success_data(api.list_entry_logs(sit["assignment"]["id"], ADMIN))
        event_types = sorted((e["event_type"], e["occurred_at"][:19]) for e in logs)
        assert event_types == [("CHECK_IN", "2026-09-10T10:00:00"),
                               ("CHECK_OUT", "2026-09-10T14:00:00")]

    def test_cancel_completed_request_rejected(self, api):
        """PRD §3.4: "Once the request is `ASSIGNED`, either the owner or the sitter
        may cancel, recording the supplied `cancelled_reason`; ..."
        PRD §2.7: "5. State: the target resource must be in the state its transition
        requires — otherwise `ERR_INVALID_STATE` (HTTP 409)."

        Design: Corner/state_machines/cancel_completed_request_returns_invalid_state
        """
        sit = setup_completed_sit()
        res = api.cancel_sitting_request(sit["request"]["id"], create_cancel_payload(
            cancelled_reason="Too late to cancel"), make_member_headers(sit["owner"]["id"]))
        validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
        req = validate_success(api.get_sitting_request(sit["request"]["id"], ADMIN), 200)
        assert req["status"] == "COMPLETED"
        asg = validate_success(api.get_assignment(sit["assignment"]["id"], ADMIN), 200)
        assert asg["status"] == "COMPLETED_PENDING_REVIEW"

    def test_settle_confirmed_assignment_rejected(self, api):
        """PRD §3.6: "An administrator settles an assignment in
        `COMPLETED_PENDING_REVIEW` (`ERR_INVALID_STATE` otherwise), but only while
        no incident on that assignment remains `FILED` or `UNDER_REVIEW` — an open
        incident blocks settlement with `ERR_UNRESOLVED_INCIDENT`."

        Design: Corner/state_machines/settle_confirmed_assignment_returns_invalid_state
        """
        sit = setup_confirmed_sit()
        res = api.settle_assignment(sit["assignment"]["id"], ADMIN)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

        sitter = get_member(sit["sitter"]["id"])
        assert sitter["credit_balance_hours"] == pytest.approx(10.0, abs=0.001)
        assert sitter["provisional_credit_hours"] == pytest.approx(4.0, abs=0.001)
        earned = list_ledger(sit["sitter"]["id"], params={"entry_type": "SIT_EARNED"})
        spent = list_ledger(sit["owner"]["id"], params={"entry_type": "SIT_SPENT"})
        assert earned == [] and spent == []


class TestSettlement:
    def test_settlement_provisional_vs_final_divergence(self, api):
        """PRD §3.6: "The final settlement variant compares promise to reality: the
        scheduled duration and the actual duration — `scheduled_start_at` to
        `scheduled_end_at`, and `actual_start_at` to `actual_end_at` — are each
        measured in hours; the shortfall is the scheduled hours minus the actual
        hours, never below zero; and if that shortfall is strictly more than 25
        percent of the scheduled duration, the sitter departed early enough to
        reprice, so the base becomes the actual hours multiplied by the demand
        multiplier locked at posting and then multiplied by 0.5."
        PRD §3.6: "Note the deliberate divergence between the two variants: the
        provisional posting at acceptance is always the full offer, while the final
        settlement may be smaller when the sitter left early."

        Design: Difficulty/dual_variant_calc/settlement_provisional_vs_final_early_departure_divergence
        """
        # 4h sit, actual 2.5h: shortfall 1.5h = 37.5% > 25% -> base 2.5 x 1.0 x 0.5.
        sit = setup_completed_sit(checkout_clock="2026-09-10T12:30:00Z")
        before = get_member(sit["sitter"]["id"])
        assert before["provisional_credit_hours"] == pytest.approx(4.0, abs=0.001)

        res = api.settle_assignment(sit["assignment"]["id"], ADMIN)
        settled = validate_success(res, 200)
        assert settled["status"] == "SETTLED"
        assert settled["credit_hours_settled"] == pytest.approx(1.25, abs=0.001)

        sitter = get_member(sit["sitter"]["id"])
        assert sitter["credit_balance_hours"] == pytest.approx(11.25, abs=0.001)
        assert sitter["provisional_credit_hours"] == pytest.approx(0.0, abs=0.001)
        assert sitter["reliability_score"] == 52
        owner = get_member(sit["owner"]["id"])
        assert owner["credit_balance_hours"] == pytest.approx(8.75, abs=0.001)

    def test_settlement_final_variant_value(self, api):
        """PRD §3.6: "...if that shortfall is strictly more than 25 percent of the
        scheduled duration, the sitter departed early enough to reprice, so the base
        becomes the actual hours multiplied by the demand multiplier locked at
        posting and then multiplied by 0.5. When the shortfall is 25 percent or
        less, no repricing occurs and the base is the request's full
        `credit_hours_offered`. Either way the result, rounded half-up to 2 decimal
        places, is recorded as `credit_hours_settled`."

        Design: Difficulty/dual_variant_calc/settlement_provisional_vs_final_early_departure_divergence
        """
        sit = setup_completed_sit(checkout_clock="2026-09-10T12:30:00Z")
        res = api.settle_assignment(sit["assignment"]["id"], ADMIN)
        settled = validate_success(res, 200)
        assert settled["credit_hours_settled"] == pytest.approx(1.25, abs=0.001)
        earned = list_ledger(sit["sitter"]["id"], params={"entry_type": "SIT_EARNED"})
        assert len(earned) == 1
        assert earned[0]["delta_hours"] == pytest.approx(1.25, abs=0.001)

    def test_early_departure_exactly_quarter_vs_over(self, api):
        """PRD §3.6: "...if that shortfall is strictly more than 25 percent of the
        scheduled duration, the sitter departed early enough to reprice, so the base
        becomes the actual hours multiplied by the demand multiplier locked at
        posting and then multiplied by 0.5. When the shortfall is 25 percent or
        less, no repricing occurs and the base is the request's full
        `credit_hours_offered`. Either way the result, rounded half-up to 2 decimal
        places, is recorded as `credit_hours_settled`."

        Design: Difficulty/boundary_precision_check/early_departure_exactly_quarter_vs_over
        """
        f = bootstrap_founders()
        # Sit A: actual 3.0h of 4.0h -> shortfall exactly 25% -> NOT repriced.
        sit_a = setup_completed_sit(founders=f, checkout_clock="2026-09-10T13:00:00Z")
        # Sit B: actual 2h59m of 4.0h -> shortfall 0.25416.. > 25% -> repriced.
        sit_b = setup_completed_sit(founders=f, start_at="2026-09-11T10:00:00Z",
                                    end_at="2026-09-11T14:00:00Z",
                                    owner=f["f1"], pet=sit_a["pet"],
                                    checkout_clock="2026-09-11T12:59:00Z")
        settled_a = validate_success(api.settle_assignment(sit_a["assignment"]["id"], ADMIN), 200)
        assert settled_a["credit_hours_settled"] == pytest.approx(4.0, abs=0.001)
        settled_b = validate_success(api.settle_assignment(sit_b["assignment"]["id"], ADMIN), 200)
        # 2.983333.. x 1.0 x 0.5 = 1.491666.. -> round-half-up 1.49.
        assert settled_b["credit_hours_settled"] == pytest.approx(1.49, abs=0.001)

        sitter = get_member(f["f2"]["id"])
        assert sitter["credit_balance_hours"] == pytest.approx(15.49, abs=0.001)
        owner = get_member(f["f1"]["id"])
        assert owner["credit_balance_hours"] == pytest.approx(4.51, abs=0.001)

    def test_early_departure_over_quarter_repriced(self, api):
        """PRD §3.6: "...if that shortfall is strictly more than 25 percent of the
        scheduled duration, the sitter departed early enough to reprice, so the base
        becomes the actual hours multiplied by the demand multiplier locked at
        posting and then multiplied by 0.5."
        PRD §2.10: "All hour amounts in the system — offers, settlements, penalties,
        grants, and balances — are decimal values rounded half-up to exactly 2
        decimal places, and all internal arithmetic on hours is performed in decimal
        to avoid floating-point drift."

        Design: Difficulty/boundary_precision_check/early_departure_exactly_quarter_vs_over
        """
        sit = setup_completed_sit(start_at="2026-09-11T10:00:00Z",
                                  end_at="2026-09-11T14:00:00Z",
                                  checkout_clock="2026-09-11T12:59:00Z")
        settled = validate_success(api.settle_assignment(sit["assignment"]["id"], ADMIN), 200)
        assert settled["credit_hours_settled"] == pytest.approx(1.49, abs=0.001)

    def test_settle_blocked_by_open_incident(self, api):
        """PRD §3.6: "An administrator settles an assignment in
        `COMPLETED_PENDING_REVIEW` (`ERR_INVALID_STATE` otherwise), but only while
        no incident on that assignment remains `FILED` or `UNDER_REVIEW` — an open
        incident blocks settlement with `ERR_UNRESOLVED_INCIDENT`."

        Design: Difficulty/cross_entity_state_dependency/settle_blocked_by_open_incident
        """
        sit = setup_completed_sit()
        incident = file_incident(sit["assignment"]["id"], sit["owner"],
                                 description="Food bowl left empty overnight.")
        res = api.settle_assignment(sit["assignment"]["id"], ADMIN)
        validate_error(res, ApiErrorId.ERR_UNRESOLVED_INCIDENT, expected_status=409)

        get_success_data(api.dismiss_incident(incident["id"], ADMIN))
        settled = validate_success(api.settle_assignment(sit["assignment"]["id"], ADMIN), 200)
        assert settled["status"] == "SETTLED"
        assert settled["credit_hours_settled"] == pytest.approx(4.0, abs=0.001)

        sitter = get_member(sit["sitter"]["id"])
        assert sitter["credit_balance_hours"] == pytest.approx(14.0, abs=0.001)
        assert sitter["reliability_score"] == 52

    def test_settle_unblocked_after_incident_dismissed(self, api):
        """PRD §3.6: "An administrator settles an assignment in
        `COMPLETED_PENDING_REVIEW` (`ERR_INVALID_STATE` otherwise), but only while
        no incident on that assignment remains `FILED` or `UNDER_REVIEW` — an open
        incident blocks settlement with `ERR_UNRESOLVED_INCIDENT`."
        PRD §3.7: "An administrator takes it under review, moving it `FILED` →
        `UNDER_REVIEW`, and may dismiss an incident from either of those states,
        ending it as `DISMISSED`."

        Design: Difficulty/cross_entity_state_dependency/settle_blocked_by_open_incident
        """
        sit = setup_completed_sit()
        incident = file_incident(sit["assignment"]["id"], sit["owner"],
                                 description="Water bowl left empty overnight.")
        get_success_data(api.dismiss_incident(incident["id"], ADMIN))
        settled = validate_success(api.settle_assignment(sit["assignment"]["id"], ADMIN), 200)
        assert settled["status"] == "SETTLED"
        assert settled["credit_hours_settled"] == pytest.approx(4.0, abs=0.001)
        assert get_member(sit["sitter"]["id"])["credit_balance_hours"] == pytest.approx(14.0, abs=0.001)

    def test_settle_double_entry_conserves_total(self, api):
        """PRD §3.6: "The cascade then settles accounts: the sitter's
        `credit_balance_hours` increases by `credit_hours_settled` with a
        `SIT_EARNED` entry, the owner's `credit_balance_hours` decreases by the same
        amount with a `SIT_SPENT` entry, the sitter's `provisional_credit_hours` is
        reduced by the request's `credit_hours_offered`, and the sitter's
        `reliability_score` gains 2 points, capped at 100."

        Design: Difficulty/compensating_invariant/settle_double_entry_conserves_total_credit
        """
        sit = setup_completed_sit()
        before_sitter = get_member(sit["sitter"]["id"])["credit_balance_hours"]
        before_owner = get_member(sit["owner"]["id"])["credit_balance_hours"]
        assert before_sitter + before_owner == pytest.approx(20.0, abs=0.001)

        validate_success(api.settle_assignment(sit["assignment"]["id"], ADMIN), 200)

        sitter = get_member(sit["sitter"]["id"])
        owner = get_member(sit["owner"]["id"])
        assert sitter["credit_balance_hours"] == pytest.approx(14.0, abs=0.001)
        assert owner["credit_balance_hours"] == pytest.approx(6.0, abs=0.001)
        assert sitter["credit_balance_hours"] + owner["credit_balance_hours"] == pytest.approx(20.0, abs=0.001)

        earned = list_ledger(sit["sitter"]["id"], params={"entry_type": "SIT_EARNED"})
        spent = list_ledger(sit["owner"]["id"], params={"entry_type": "SIT_SPENT"})
        assert len(earned) == 1 and earned[0]["delta_hours"] == pytest.approx(4.0, abs=0.001)
        assert earned[0]["sitting_assignment_id"] == sit["assignment"]["id"]
        assert len(spent) == 1 and spent[0]["delta_hours"] == pytest.approx(-4.0, abs=0.001)
        assert spent[0]["sitting_assignment_id"] == sit["assignment"]["id"]
        assert earned[0]["delta_hours"] + spent[0]["delta_hours"] == pytest.approx(0.0, abs=0.001)

    def test_settle_ledger_rows_reference_assignment(self, api):
        """PRD §2.4: "Entries that arise from a sitting record the assignment's
        `sitting_assignment_id`; the field is null for entries unrelated to an
        assignment."
        PRD §3.6: "The cascade then settles accounts: the sitter's
        `credit_balance_hours` increases by `credit_hours_settled` with a
        `SIT_EARNED` entry, the owner's `credit_balance_hours` decreases by the same
        amount with a `SIT_SPENT` entry, ..."

        Design: Difficulty/compensating_invariant/settle_double_entry_conserves_total_credit
        """
        sit = setup_settled_sit()
        earned = list_ledger(sit["sitter"]["id"], params={"entry_type": "SIT_EARNED"})
        spent = list_ledger(sit["owner"]["id"], params={"entry_type": "SIT_SPENT"})
        assert len(earned) == 1 and len(spent) == 1
        assert earned[0]["sitting_assignment_id"] == sit["assignment"]["id"]
        assert spent[0]["sitting_assignment_id"] == sit["assignment"]["id"]
        assert earned[0]["delta_hours"] + spent[0]["delta_hours"] == pytest.approx(0.0, abs=0.001)

    def test_settle_response_immediately_reflects_final_state(self, api):
        """PRD §3.6: "Either way the result, rounded half-up to 2 decimal places, is
        recorded as `credit_hours_settled`."
        PRD §3.6: "The cascade then settles accounts: the sitter's
        `credit_balance_hours` increases by `credit_hours_settled` with a
        `SIT_EARNED` entry, the owner's `credit_balance_hours` decreases by the same
        amount with a `SIT_SPENT` entry, the sitter's `provisional_credit_hours` is
        reduced by the request's `credit_hours_offered`, and the sitter's
        `reliability_score` gains 2 points, capped at 100."

        Design: Corner/consistency_model/settle_response_immediately_reflects_final_state
        """
        sit = setup_completed_sit(checkout_clock="2026-09-10T12:30:00Z")
        res = api.settle_assignment(sit["assignment"]["id"], ADMIN)
        settled = validate_success(res, 200)
        assert settled["status"] == "SETTLED"
        assert settled["credit_hours_settled"] == pytest.approx(1.25, abs=0.001)

        reread = validate_success(api.get_assignment(sit["assignment"]["id"], ADMIN), 200)
        assert reread["status"] == "SETTLED"
        assert reread["credit_hours_settled"] == pytest.approx(1.25, abs=0.001)

    def test_member_balance_matches_ledger_replay(self, api):
        """PRD §2.4: "A member's `credit_balance_hours` is not stored as an
        independent fact: it is derived by replaying that member's ledger entries in
        chronological order — `created_at` ascending, with the entry's `id`
        ascending as the tiebreaker — and summing `delta_hours`. The balance is
        updated inline every time an entry is appended."

        Design: Corner/calculations/member_credit_balance_matches_ledger_replay
        """
        f = bootstrap_founders()
        pet = create_pet(f["f1"])
        sit = setup_completed_sit(founders=f, owner=f["f1"], pet=pet)
        validate_success(api.settle_assignment(sit["assignment"]["id"], ADMIN), 200)

        # Second sit late-cancelled by F2 at 23h before start.
        req2 = post_request(f["f1"], pet, start_at="2026-09-20T12:00:00Z",
                            end_at="2026-09-20T16:00:00Z", instructions="Late-cancel sit")
        claim2 = claim_request(req2, f["f2"], message="F2 takes it")
        accept_claim(req2, claim2, f["f1"])
        set_clock("2026-09-19T13:00:00Z")
        get_success_data(api.cancel_sitting_request(req2["id"], create_cancel_payload(
            cancelled_reason="Sitter bails at 23h"), make_member_headers(f["f2"]["id"])))

        f2 = get_member(f["f2"]["id"])
        assert f2["credit_balance_hours"] == pytest.approx(13.0, abs=0.001)
        assert f2["reliability_score"] == 44  # 50 + 2 settle - 8 late-cancel

        rows = list_ledger(f["f2"]["id"])
        assert [r["entry_type"] for r in rows] == [
            "JOINING_GRANT", "SIT_EARNED", "CANCELLATION_PENALTY"]
        assert rows[0]["delta_hours"] == pytest.approx(10.0, abs=0.001)
        assert rows[1]["delta_hours"] == pytest.approx(4.0, abs=0.001)
        assert rows[2]["delta_hours"] == pytest.approx(-1.0, abs=0.001)
        assert sum(r["delta_hours"] for r in rows) == pytest.approx(
            f2["credit_balance_hours"], abs=0.001)

    def test_immutable_entry_log_and_ledger_entry(self, api):
        """PRD §2.9: "Two record types are deliberately leaner: an EntryLog and a
        CreditLedgerEntry each carry only `id` and `created_at` — both `updated_at`
        and `version` are absent, because both records are immutable once appended."
        PRD §3.5: "The caller is recorded as `actor_member_id`."

        Design: Corner/entities/immutable_entry_log_and_ledger_entry
        """
        sit = setup_confirmed_sit()
        entry = validate_success(api.create_entry_log(
            sit["assignment"]["id"],
            create_entry_log_payload("PET_FED", "2026-09-10T12:00:00Z", notes="Half cup kibble"),
            make_member_headers(sit["sitter"]["id"])), 201)
        assert "version" not in entry, "EntryLog must not expose version"
        assert "updated_at" not in entry, "EntryLog must not expose updated_at"
        assert entry["id"]
        assert entry["created_at"]
        assert entry["actor_member_id"] == sit["sitter"]["id"]

        ledger_rows = list_ledger(sit["sitter"]["id"])
        assert len(ledger_rows) == 1 and ledger_rows[0]["entry_type"] == "JOINING_GRANT"
        for row in ledger_rows:
            assert "version" not in row, "CreditLedgerEntry must not expose version"
            assert "updated_at" not in row, "CreditLedgerEntry must not expose updated_at"
            assert row["id"] and row["created_at"]

    def test_accept_cancel_roundtrip_conserves_provisional(self, api):
        """PRD §3.4: "Once the request is `ASSIGNED`, either the owner or the sitter
        may cancel, recording the supplied `cancelled_reason`; the assignment
        becomes `CANCELLED_BY_OWNER` or `CANCELLED_BY_SITTER` accordingly and the
        provisional hours are reversed."
        PRD §3.4: "A sitter who cancels late pays for it: when fewer than 24 hours
        remain before `scheduled_start_at` — exactly 24 hours out is not late — ..."

        Design: Difficulty/compensating_invariant/accept_cancel_roundtrip_conserves_provisional
        """
        f = bootstrap_founders()
        pet = create_pet(f["f1"])
        request = post_request(f["f1"], pet)
        claim = claim_request(request, f["f2"])
        accept_claim(request, claim, f["f1"])
        asg = get_assignment_for_request(request["id"])
        assert get_member(f["f2"]["id"])["provisional_credit_hours"] == pytest.approx(4.0, abs=0.001)

        # Owner-cancel far outside the 24h late window: no sitter penalty.
        res = api.cancel_sitting_request(request["id"], create_cancel_payload(
            cancelled_reason="Owner trip cancelled"), make_member_headers(f["f1"]["id"]))
        validate_success(res, 200)

        sitter = get_member(f["f2"]["id"])
        assert sitter["provisional_credit_hours"] == pytest.approx(0.0, abs=0.001)
        assert sitter["credit_balance_hours"] == pytest.approx(10.0, abs=0.001)
        owner = get_member(f["f1"]["id"])
        assert owner["credit_balance_hours"] == pytest.approx(10.0, abs=0.001)

        assert validate_success(api.get_assignment(asg["id"], ADMIN), 200)["status"] == "CANCELLED_BY_OWNER"
        assert validate_success(api.get_sitting_request(request["id"], ADMIN), 200)["status"] == "CANCELLED"

        ledger = list_ledger(f["f2"]["id"])
        assert len(ledger) == 1 and ledger[0]["entry_type"] == "JOINING_GRANT"

    def test_accept_cancel_roundtrip_no_penalty_rows(self, api):
        """PRD §3.4: "Once the request is `ASSIGNED`, either the owner or the sitter
        may cancel, recording the supplied `cancelled_reason`; the assignment
        becomes `CANCELLED_BY_OWNER` or `CANCELLED_BY_SITTER` accordingly and the
        provisional hours are reversed."
        PRD §3.4: "A sitter who cancels late pays for it: when fewer than 24 hours
        remain before `scheduled_start_at` — exactly 24 hours out is not late — ..."

        Design: Difficulty/compensating_invariant/accept_cancel_roundtrip_conserves_provisional
        """
        f = bootstrap_founders()
        pet = create_pet(f["f1"])
        request = post_request(f["f1"], pet)
        claim = claim_request(request, f["f2"])
        accept_claim(request, claim, f["f1"])
        get_success_data(api.cancel_sitting_request(request["id"], create_cancel_payload(
            cancelled_reason="Owner trip cancelled"), make_member_headers(f["f1"]["id"])))
        assert list_ledger(f["f2"]["id"], params={"entry_type": "CANCELLATION_PENALTY"}) == []
        assert list_ledger(f["f2"]["id"], params={"entry_type": "SIT_EARNED"}) == []
        assert get_member(f["f2"]["id"])["provisional_credit_hours"] == pytest.approx(0.0, abs=0.001)


class TestSitterOverlap:
    def test_half_open_adjacency(self, api):
        """PRD §3.4: "...and the claimant must have no other assignment in
        `CONFIRMED` or `IN_PROGRESS` whose scheduled interval overlaps the request's
        interval (`ERR_SITTER_OVERLAP`). Overlap is judged on half-open intervals,
        so two sits where one ends exactly when the other begins do not conflict."

        Design: Difficulty/resource_temporal_overlap/sitter_overlap_half_open_adjacency
        """
        f = bootstrap_founders()
        pet1 = create_pet(f["f1"])
        # F2 occupies [10:00, 14:00).
        sit = post_request(f["f1"], pet1)
        accept_claim(sit, claim_request(sit, f["f2"]), f["f1"])
        pet3 = create_pet(f["f3"], pet_name="Kiwi", species="BIRD",
                          routine_notes="Cover cage at night.")

        # Adjacent [14:00, 18:00): allowed (half-open adjacency).
        req_adj = post_request(f["f3"], pet3, start_at="2026-09-10T14:00:00Z",
                               end_at="2026-09-10T18:00:00Z", instructions="Adjacent sit")
        claim_adj = claim_request(req_adj, f["f2"], message="Adjacent OK")
        accepted = validate_success(api.accept_claim(
            req_adj["id"], claim_adj["id"],
            create_accept_claim_payload(req_adj["version"]),
            make_member_headers(f["f3"]["id"])), 200)
        assert accepted["status"] == "ACCEPTED"

        # Overlapping [13:59, 17:00): rejected.
        req_ovl = post_request(f["f1"], pet1, start_at="2026-09-10T13:59:00Z",
                               end_at="2026-09-10T17:00:00Z", instructions="One-minute overlap sit")
        claim_ovl = claim_request(req_ovl, f["f2"], message="Overlapping claim")
        res = api.accept_claim(req_ovl["id"], claim_ovl["id"],
                               create_accept_claim_payload(req_ovl["version"]),
                               make_member_headers(f["f1"]["id"]))
        validate_error(res, ApiErrorId.ERR_SITTER_OVERLAP, expected_status=409)

        assert get_member(f["f2"]["id"])["provisional_credit_hours"] == pytest.approx(8.0, abs=0.001)

    def test_overlap_one_minute_rejected(self, api):
        """PRD §3.4: "...and the claimant must have no other assignment in
        `CONFIRMED` or `IN_PROGRESS` whose scheduled interval overlaps the request's
        interval (`ERR_SITTER_OVERLAP`). Overlap is judged on half-open intervals,
        so two sits where one ends exactly when the other begins do not conflict."

        Design: Difficulty/resource_temporal_overlap/sitter_overlap_half_open_adjacency
        """
        f = bootstrap_founders()
        pet1 = create_pet(f["f1"])
        sit = post_request(f["f1"], pet1)
        accept_claim(sit, claim_request(sit, f["f2"]), f["f1"])
        req_ovl = post_request(f["f1"], pet1, start_at="2026-09-10T13:59:00Z",
                               end_at="2026-09-10T17:00:00Z", instructions="One-minute overlap sit")
        claim_ovl = claim_request(req_ovl, f["f2"], message="Overlapping claim")
        res = api.accept_claim(req_ovl["id"], claim_ovl["id"],
                               create_accept_claim_payload(req_ovl["version"]),
                               make_member_headers(f["f1"]["id"]))
        validate_error(res, ApiErrorId.ERR_SITTER_OVERLAP, expected_status=409)
        claim_after = validate_success(api.get_claim(claim_ovl["id"], ADMIN), 200)
        assert claim_after["status"] == "PENDING"
        assert get_success_data(api.get_request_assignment(req_ovl["id"], ADMIN)) == []

    def test_overlap_ignores_cancelled_assignments(self, api):
        """PRD §3.4: "...and the claimant must have no other assignment in
        `CONFIRMED` or `IN_PROGRESS` whose scheduled interval overlaps the request's
        interval (`ERR_SITTER_OVERLAP`). Overlap is judged on half-open intervals,
        so two sits where one ends exactly when the other begins do not conflict."

        Design: Corner/calculations/sitter_overlap_ignores_cancelled_assignments
        """
        f = bootstrap_founders()
        pet1 = create_pet(f["f1"])
        # F2's [10:00, 14:00) assignment is owner-cancelled before the sit.
        sit = post_request(f["f1"], pet1)
        accept_claim(sit, claim_request(sit, f["f2"]), f["f1"])
        get_success_data(api.cancel_sitting_request(sit["id"], create_cancel_payload(
            cancelled_reason="Owner cancels early"), make_member_headers(f["f1"]["id"])))

        pet3 = create_pet(f["f3"], pet_name="Kiwi", species="BIRD",
                          routine_notes="Cover cage at night.")
        req2 = post_request(f["f3"], pet3, start_at="2026-09-10T11:00:00Z",
                            end_at="2026-09-10T13:00:00Z", instructions="Inside cancelled window")
        claim2 = claim_request(req2, f["f2"], message="F2 free after cancel")
        accepted = validate_success(api.accept_claim(
            req2["id"], claim2["id"], create_accept_claim_payload(req2["version"]),
            make_member_headers(f["f3"]["id"])), 200)
        assert accepted["status"] == "ACCEPTED"
        # Only the new 2.00-offered sit remains provisional; the cancelled 4.00 reversed.
        assert get_member(f["f2"]["id"])["provisional_credit_hours"] == pytest.approx(2.0, abs=0.001)
