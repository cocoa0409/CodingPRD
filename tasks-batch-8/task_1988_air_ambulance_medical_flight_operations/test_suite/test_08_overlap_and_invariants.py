"""Resource temporal overlap (aircraft half-open windows, crew-shift rest
buffer) and compensating invariants (invoice ledger conservation, aircraft
disposition balance)."""
from test_helpers import (
    ApiErrorId,
    abort_mission,
    accept_request,
    api_client,
    assert_invoice_ledger_invariant,
    close_shift,
    create_aircraft,
    create_base,
    create_crew_member,
    create_crew_shift,
    create_invoice,
    create_mission_request,
    create_patient,
    get_success_data,
    qa_review,
    set_clock,
    setup_base_with_crew,
    setup_member_protected_submitted_invoice,
    setup_planning_mission,
    submit_pcr,
    triage_request,
    validate_error,
    validate_paginated,
    TEST_USERS,
)

OPS = TEST_USERS["ops_admin_headers"]
DISP = TEST_USERS["dispatcher_headers"]
BILL = TEST_USERS["billing_specialist_headers"]


class TestAircraftHalfOpenWindowAdjacency:
    def _setup_one_booked_window(self):
        """One CCT tail; mission1 accepted with window [2026-08-05T08:00:00Z,
        +120 min); two further TRIAGED requests ready to accept."""
        set_clock()
        base, aircraft, roster = setup_base_with_crew(medical_config="CCT_CAPABLE")
        patient = create_patient()
        req_ids = []
        for _ in range(3):
            req = create_mission_request(patient["id"])
            req = triage_request(req["id"])
            req_ids.append(req["id"])
        crew = [(roster["PILOT"]["id"], "PILOT"), (roster["NURSE"]["id"], "NURSE")]
        m1 = accept_request(
            req_ids[0], aircraft["id"], crew,
            estimated_loaded_miles=50,
            planned_launch_iso="2026-08-05T08:00:00Z", planned_duration_min=120,
        )
        return aircraft, roster, req_ids, m1

    def test_adjacent_window_touching_endpoint_is_allowed(self):
        """PRD §3.3: "the new mission occupies the half-open window starting at
        `planned_launch_iso` and running for `planned_duration_min` minutes —
        the end instant itself is not part of the window — and if any other
        non-terminal mission on the same tail has a window overlapping it, the
        acceptance is rejected with `ERR_AIRCRAFT_SCHEDULE_CONFLICT`. Windows
        that touch endpoint-to-startpoint — one ending exactly when the other
        begins — are expressly allowed."

        Design: Difficulty/resource_temporal_overlap/aircraft_half_open_window_adjacency
        """
        aircraft, roster, req_ids, m1 = self._setup_one_booked_window()
        crew = [(roster["PILOT"]["id"], "PILOT"), (roster["NURSE"]["id"], "NURSE")]
        # m1 window [08:00, 10:00); the second window starts exactly at 10:00.
        m2 = accept_request(
            req_ids[1], aircraft["id"], crew,
            estimated_loaded_miles=50,
            planned_launch_iso="2026-08-05T10:00:00Z", planned_duration_min=120,
        )
        assert m2["status"] == "PLANNING", (
            "Endpoint-touching adjacency (10:00:00Z == m1 window end) must be allowed"
        )

    def test_overlapping_window_rejected_with_schedule_conflict(self):
        """PRD §3.3: "if any other non-terminal mission on the same tail has a
        window overlapping it, the acceptance is rejected with
        `ERR_AIRCRAFT_SCHEDULE_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/aircraft_half_open_window_adjacency
        """
        aircraft, roster, req_ids, m1 = self._setup_one_booked_window()
        crew = [(roster["PILOT"]["id"], "PILOT"), (roster["NURSE"]["id"], "NURSE")]
        # 09:59:00Z start intersects [08:00, 10:00) by one minute.
        resp = api_client.accept_mission_request(
            req_ids[2],
            {
                "aircraft_id": aircraft["id"],
                "crew": [
                    {"crew_member_id": roster["PILOT"]["id"], "role_in_mission": "PILOT"},
                    {"crew_member_id": roster["NURSE"]["id"], "role_in_mission": "NURSE"},
                ],
                "estimated_loaded_miles": 50,
                "planned_launch_iso": "2026-08-05T09:59:00Z",
                "planned_duration_min": 120,
            },
            DISP,
        )
        validate_error(resp, ApiErrorId.ERR_AIRCRAFT_SCHEDULE_CONFLICT)
        after = get_success_data(api_client.get_mission_request(req_ids[2], DISP))
        assert after["status"] == "TRIAGED"


class TestCrewShiftRestBufferSemantics:
    def _setup_member_with_morning_shift(self):
        set_clock("2026-08-01T00:00:00Z")
        base = create_base(name="Base Phi", region="NW-US")
        pilot = create_crew_member(base["id"], "Rachel Rest", "PILOT")
        shift1 = create_crew_shift(pilot["id"], "2026-08-01T00:00:00Z", "2026-08-01T10:00:00Z")
        set_clock("2026-08-01T10:00:00Z")
        close_shift(shift1["id"])
        return pilot

    def test_599_minute_rest_gap_rejected(self):
        """PRD §3.1: "The candidate's planned start must fall at least 600
        minutes (ten hours) after the end of the member's most recent prior
        shift — where "end" means the later of the shift's planned and actual
        end, considering only shifts ending at or before the candidate's start.
        A gap of exactly 600 minutes passes; anything less is rejected with
        `ERR_INSUFFICIENT_REST`."

        Design: Difficulty/resource_temporal_overlap/crew_shift_rest_buffer_semantics
        """
        pilot = self._setup_member_with_morning_shift()
        # 19:59 start is 599 minutes after the 10:00 close: inside the rest buffer.
        resp = api_client.create_crew_shift(
            {
                "crew_member_id": pilot["id"],
                "planned_start_iso": "2026-08-01T19:59:00Z",
                "planned_end_iso": "2026-08-01T21:59:00Z",
            },
            OPS,
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_REST)

    def test_exactly_600_minute_rest_gap_accepted(self):
        """PRD §3.1: "A gap of exactly 600 minutes passes; anything less is
        rejected with `ERR_INSUFFICIENT_REST`."
        PRD §3.1: "Two windows that merely touch end-to-start are not an
        overlap; that adjacency is governed by the rest rule below."

        Design: Difficulty/resource_temporal_overlap/crew_shift_rest_buffer_semantics
        """
        pilot = self._setup_member_with_morning_shift()
        # 20:00 start is exactly 600 minutes after the 10:00 close.
        shift2 = create_crew_shift(pilot["id"], "2026-08-01T20:00:00Z", "2026-08-01T22:00:00Z")
        assert shift2["status"] == "OPEN"
        assert shift2["planned_minutes"] == 120


class TestInvoiceLedgerConservationAcrossPostingAppealWriteoff:
    def test_invariant_holds_after_denial_posting(self):
        """PRD §3.8: "After every posting, appeal, and write-off, one conserved
        invariant holds: insurer paid plus contractual adjustment plus member
        write-off plus patient responsibility always equals `final_total_cents`."

        Design: Difficulty/compensating_invariant/invoice_ledger_conservation_across_posting_appeal_writeoff
        """
        _, invoice, _, _ = setup_member_protected_submitted_invoice()
        denied = get_success_data(
            api_client.payer_response(
                invoice["id"],
                {"outcome": "DENIED", "paid_cents": 200000, "contractual_adjustment_cents": 50000},
                BILL,
            )
        )
        assert denied["final_total_cents"] == 1808560
        assert denied["patient_responsibility_cents"] == 1558560
        assert_invoice_ledger_invariant(denied)

    def test_appeal_compensation_zeroes_posting_and_writeoff_closes_ledger(self):
        """PRD §3.8: "Appealing increments `appeal_count` by one and, as
        compensation for the denied posting, resets `insurer_paid_cents` and
        `contractual_adjustment_cents` to zero so the ledger invariant survives
        the reversal; `member_writeoff_cents` is expressly not reset, since a
        write-off requires a claim response to exist against."
        PRD §3.8: "After every posting, appeal, and write-off, one conserved
        invariant holds: insurer paid plus contractual adjustment plus member
        write-off plus patient responsibility always equals `final_total_cents`."

        Design: Difficulty/compensating_invariant/invoice_ledger_conservation_across_posting_appeal_writeoff
        """
        _, invoice, _, _ = setup_member_protected_submitted_invoice()
        get_success_data(
            api_client.payer_response(
                invoice["id"],
                {"outcome": "DENIED", "paid_cents": 200000, "contractual_adjustment_cents": 50000},
                BILL,
            )
        )
        appealed = get_success_data(api_client.appeal_invoice(invoice["id"], BILL))
        assert appealed["appeal_count"] == 1
        assert appealed["insurer_paid_cents"] == 0
        assert appealed["contractual_adjustment_cents"] == 0
        assert appealed["patient_responsibility_cents"] == 1808560
        assert_invoice_ledger_invariant(appealed)
        resubmitted = get_success_data(api_client.submit_invoice(invoice["id"], BILL))
        assert resubmitted["claim_status"] == "RESUBMITTED"
        paid = get_success_data(
            api_client.payer_response(
                invoice["id"],
                {"outcome": "PAID", "paid_cents": 400000, "contractual_adjustment_cents": 100000},
                BILL,
            )
        )
        assert paid["patient_responsibility_cents"] == 1308560
        assert_invoice_ledger_invariant(paid)
        written = get_success_data(api_client.member_writeoff(invoice["id"], BILL))
        assert written["member_writeoff_cents"] == 1308560
        assert written["patient_responsibility_cents"] == 0
        assert_invoice_ledger_invariant(written)


class TestAircraftAssignmentBalanceConserved:
    def test_accept_then_abort_returns_tail_to_available(self):
        """PRD §3.5: "An aircraft returns to `AVAILABLE` only when the last
        non-terminal mission bound to it reaches `COMPLETED`, `ABORTED`, or
        `CANCELLED`; a tail holding several non-overlapping future bookings
        stays `ASSIGNED` until its final open mission resolves."
        PRD §3.5: "From `PLANNING`, the mission moves to `CANCELLED`."

        Design: Difficulty/compensating_invariant/aircraft_assignment_balance_conserved
        """
        set_clock()
        ctx = setup_planning_mission(estimated_loaded_miles=60)
        aircraft = ctx["aircraft"]
        mid = get_success_data(api_client.get_aircraft(aircraft["id"], DISP))
        assert mid["status"] == "ASSIGNED", "Accept debited the available pool by one"
        aborted = abort_mission(ctx["mission"]["id"], "REQUESTER", DISP)
        assert aborted["status"] == "CANCELLED", (
            f"PLANNING + abort is a cancellation, got {aborted['status']}"
        )
        after = get_success_data(api_client.get_aircraft(aircraft["id"], DISP))
        assert after["status"] == "AVAILABLE", (
            "Compensating abort credits the tail back to AVAILABLE"
        )

    def test_sibling_tail_unaffected_and_fleet_disposition_balanced(self):
        """PRD §3.5: "An aircraft returns to `AVAILABLE` only when the last
        non-terminal mission bound to it reaches `COMPLETED`, `ABORTED`, or
        `CANCELLED`; a tail holding several non-overlapping future bookings
        stays `ASSIGNED` until its final open mission resolves."
        PRD §3.3: "The tail transitions `AVAILABLE` to `ASSIGNED` and its
        `version` bumps."

        Design: Difficulty/compensating_invariant/aircraft_assignment_balance_conserved
        """
        set_clock()
        base = create_base(name="Base Psi")
        ac1 = create_aircraft(base["id"], tail_number="N121AV")
        ac2 = create_aircraft(base["id"], tail_number="N122AV")
        pilot = create_crew_member(base["id"], "Pat Pilot", "PILOT")
        nurse = create_crew_member(base["id"], "Nina Nurse", "NURSE")
        patient = create_patient()
        req = triage_request(create_mission_request(patient["id"])["id"])
        mission = accept_request(
            req["id"], ac1["id"], [(pilot["id"], "PILOT"), (nurse["id"], "NURSE")],
            estimated_loaded_miles=60,
        )

        def disposition():
            data, meta = validate_paginated(
                api_client.list_aircraft(DISP, params={"base_id": base["id"], "limit": 100})
            )
            counts = {"AVAILABLE": 0, "ASSIGNED": 0, "MAINTENANCE": 0}
            for row in data:
                counts[row["status"]] += 1
            return counts

        before = {"AVAILABLE": 1, "ASSIGNED": 1, "MAINTENANCE": 0}
        assert disposition() == before, f"After accept: {disposition()}"
        abort_mission(mission["id"], "REQUESTER", DISP)
        after = disposition()
        assert after == {"AVAILABLE": 2, "ASSIGNED": 0, "MAINTENANCE": 0}, (
            f"After abort the fleet must return to the pre-pair disposition, got {after}"
        )
        # Conserved quantity: the three buckets always sum to the fleet size.
        assert sum(after.values()) == 2
        ac2_after = get_success_data(api_client.get_aircraft(ac2["id"], DISP))
        assert ac2_after["status"] == "AVAILABLE"
