"""Damage-case parallel dimensions, evidence admissibility, ticket linkage, and
timeline reconstruction (PRD §2.6, §3.3, §3.4)."""
from test_helpers import (
    ApiErrorId,
    add_cost_line,
    add_evidence,
    assert_damage_case,
    create_case,
    create_completed_ticket,
    create_excavator,
    create_locator,
    create_locate_response,
    create_ticket,
    get_case,
    get_success_data,
    make_intake_headers,
    make_investigator_headers,
    make_manager_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestParallelDimensions:
    def test_cost_line_moves_recovery_only(self, api):
        """PRD §2.6: "A first `CostLineItem` flips the recovery dimension from
        `UNBILLED` to `COSTING`, recomputes the case's `subtotal_cents`, and bumps the
        case's `version`." The investigation dimension is untouched.

        Design: Difficulty/non_linear_state_machine/damage_case_parallel_dimensions_evolve_independently
        """
        excavator = create_excavator()
        case = create_case(excavator["id"], "2 Cedar Ln", "WATER", "MINOR",
                           "2026-05-06T09:00:00Z")
        assert case["investigation_status"] == "REPORTED"
        assert case["recovery_status"] == "UNBILLED"
        add_cost_line(case["id"], "EQUIPMENT", 2, 20000, description="vac truck")
        case_after = get_case(case["id"])
        assert_damage_case(case_after)
        assert case_after["investigation_status"] == "REPORTED", (
            "cost line must not move the investigation dimension"
        )
        assert case_after["recovery_status"] == "COSTING"

    def test_evidence_moves_investigation_only(self, api):
        """PRD §2.6: "A first `EvidenceItem` on a `DamageCase` flips the case's
        investigation dimension from `REPORTED` to `DOCUMENTING`, increments the case's
        `evidence_count`, and bumps its `version`." The recovery dimension already at
        `COSTING` stays put.

        Design: Difficulty/non_linear_state_machine/damage_case_parallel_dimensions_evolve_independently
        """
        excavator = create_excavator()
        case = create_case(excavator["id"], "2 Cedar Ln", "WATER", "MINOR",
                           "2026-05-06T09:00:00Z")
        add_cost_line(case["id"], "EQUIPMENT", 2, 20000, description="vac truck")
        add_evidence(case["id"], captured_at="2026-05-06T10:00:00Z")
        case_after = get_case(case["id"])
        assert case_after["investigation_status"] == "DOCUMENTING"
        assert case_after["recovery_status"] == "COSTING", (
            "evidence must not move the recovery dimension"
        )
        assert case_after["evidence_count"] == 1


class TestLinkTicket:
    def test_link_ticket_requires_completed_ticket_rejected_while_open(self, api):
        """PRD §3.3: "The link requires the target ticket's `status` to be `COMPLETED`
        (otherwise `ERR_INVALID_STATE`)"

        Design: Difficulty/cross_entity_state_dependency/link_ticket_requires_completed_ticket
        """
        excavator = create_excavator()
        create_locator()
        ticket = create_ticket(
            excavator["id"], "60 Ridge Rd", "2026-05-10T08:00:00Z", "2026-05-10T17:00:00Z",
        )
        case = create_case(excavator["id"], "60 Ridge Rd", "GAS", "MINOR",
                           "2026-05-10T10:00:00Z")
        resp = api.link_ticket(case["id"], {"locate_ticket_id": ticket["id"]},
                               make_intake_headers())
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

    def test_link_ticket_succeeds_after_response_completes_ticket(self, api):
        """PRD §3.3: "A successful link sets `locate_ticket_id` on the case and bumps the
        case's `version`." PRD §2.6: "A first `LocateResponse` on a ticket flips the
        ticket from `OPEN` to `COMPLETED`"

        Design: Difficulty/cross_entity_state_dependency/link_ticket_requires_completed_ticket
        """
        excavator = create_excavator()
        locator = create_locator()
        ticket = create_ticket(
            excavator["id"], "60 Ridge Rd", "2026-05-10T08:00:00Z", "2026-05-10T17:00:00Z",
        )
        case = create_case(excavator["id"], "60 Ridge Rd", "GAS", "MINOR",
                           "2026-05-10T10:00:00Z")
        create_locate_response(ticket["id"], locator["id"], "MARKED",
                               "2026-05-10T07:00:00Z")
        resp = api.link_ticket(case["id"], {"locate_ticket_id": ticket["id"]},
                               make_intake_headers())
        linked = validate_success(resp)
        assert linked["locate_ticket_id"] == ticket["id"]

    def test_link_ticket_outside_window_rejected(self, api):
        """PRD §3.3: "requires the case's `occurred_at` to fall within the ticket's
        half-open dig window `[work_start_at, work_end_at)` (otherwise
        `ERR_DAMAGE_OUTSIDE_TICKET_WINDOW`, HTTP 409)."

        Design: Corner/errors/link_ticket_outside_window_rejected
        """
        excavator = create_excavator()
        locator = create_locator()
        ticket, _response = create_completed_ticket(
            excavator["id"], locator["id"], "32 Rho St",
            "2026-05-02T08:00:00Z", "2026-05-02T17:00:00Z", "2026-05-02T07:00:00Z",
        )
        case = create_case(excavator["id"], "32 Rho St", "GAS", "MINOR",
                           "2026-05-03T10:00:00Z")
        resp = api.link_ticket(case["id"], {"locate_ticket_id": ticket["id"]},
                               make_intake_headers())
        validate_error(resp, ApiErrorId.ERR_DAMAGE_OUTSIDE_TICKET_WINDOW, expected_status=409)
        case_after = get_case(case["id"])
        assert case_after.get("locate_ticket_id") in (None,)


class TestEvidenceAdmissibility:
    def test_evidence_after_72h_window_rejected(self, api):
        """PRD §3.3: "`captured_at` must not be later than seventy-two hours after the
        case's `occurred_at` — evidence captured past that window is rejected with
        `ERR_EVIDENCE_INADMISSIBLE` (HTTP 422)." Captured at exactly occurred_at + 72h
        is not later than the window edge and is admitted.

        Design: Corner/validations/evidence_after_72h_window_rejected
        """
        excavator = create_excavator()
        case = create_case(excavator["id"], "24 Iota St", "GAS", "MINOR",
                           "2026-05-02T09:00:00Z")
        # occurred_at + 73h -> inadmissible
        resp_late = api.create_evidence_item(
            {
                "damage_case_id": case["id"], "evidence_type": "PHOTO",
                "captured_at": "2026-05-05T10:00:00Z", "description": "73h late",
            },
            make_intake_headers(),
        )
        validate_error(resp_late, ApiErrorId.ERR_EVIDENCE_INADMISSIBLE, expected_status=422)
        # occurred_at + 72h exactly -> admitted (boundary inclusive)
        resp_ok = api.create_evidence_item(
            {
                "damage_case_id": case["id"], "evidence_type": "PHOTO",
                "captured_at": "2026-05-05T09:00:00Z", "description": "exactly 72h",
            },
            make_intake_headers(),
        )
        evidence = validate_success(resp_ok, expected_status=201)
        assert evidence["id"]


class TestTimelineReconstruction:
    def test_reconstruct_without_sources_rejected(self, api):
        """PRD §3.4: "Invoking reconstruction when the case has neither a linked ticket,
        nor any responses, nor any evidence is rejected with `ERR_TIMELINE_EMPTY`
        (HTTP 409)."

        Design: Corner/errors/reconstruct_without_sources_rejected
        """
        excavator = create_excavator()
        case = create_case(excavator["id"], "40 Aleph St", "GAS", "MINOR",
                           "2026-05-02T09:00:00Z")
        resp = api.reconstruct_timeline(case["id"], make_investigator_headers("inv-1"))
        validate_error(resp, ApiErrorId.ERR_TIMELINE_EMPTY, expected_status=409)

    def test_timeline_reconstruction_chronological_order(self, api):
        """PRD §3.4: "Events sort by `event_at` ascending; ties break by the source
        record's `created_at` ascending; further ties break by `event_kind` in the order
        `TICKET_SUBMITTED` before `RESPONSE_SUBMITTED` before `EVIDENCE_CAPTURED` before
        `DAMAGE_OCCURRED`." With ticket created at the default clock, marks before work
        start, damage, then evidence, the four events fall in that order with no flags.

        Design: Corner/calculations/timeline_reconstruction_chronological_order
        """
        excavator = create_excavator()
        locator = create_locator()
        # Ticket created under the default clock 2026-05-01T00:00:00Z.
        ticket, _response = create_completed_ticket(
            excavator["id"], locator["id"], "18 Gamma St",
            "2026-05-02T08:00:00Z", "2026-05-02T17:00:00Z", "2026-05-02T07:00:00Z",
        )
        case = create_case(excavator["id"], "18 Gamma St", "GAS", "MINOR",
                           "2026-05-02T10:00:00Z", locate_ticket_id=ticket["id"])
        add_evidence(case["id"], captured_at="2026-05-02T12:00:00Z")
        resp = api.reconstruct_timeline(case["id"], make_investigator_headers("inv-1"))
        result = validate_success(resp)
        assert result["created_event_count"] == 4
        assert result["reconstruction_flags"] == []
        events_resp = api.list_timeline_events(
            make_manager_headers(), params={"damage_case_id": case["id"]},
        )
        events, _meta = validate_paginated(events_resp)
        events = [e for e in events if e.get("damage_case_id") in (None, case["id"])]
        kinds = [e["event_kind"] for e in events]
        assert kinds == [
            "TICKET_SUBMITTED", "RESPONSE_SUBMITTED", "DAMAGE_OCCURRED", "EVIDENCE_CAPTURED",
        ], f"expected chronological order, got {kinds}"
