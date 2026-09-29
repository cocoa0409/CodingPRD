"""Intervals whose endpoints decide the answer, and whose scope decides who collides.

A gate session occupies a half-open interval over its own gate; a re-entry
lockout is a closed interval owned by one ticket; a credential window competes
only with the windows it genuinely overlaps.
"""

from test_helpers import (
    AdmissionStatus,
    ApiErrorId,
    BOX_OFFICE_AGENT,
    CredentialRequestStatus,
    DistributionType,
    EntitlementLevel,
    EventStatus,
    GATE_OPERATOR,
    GateStatus,
    ScanResult,
    SessionMode,
    TICKETING_APPROVER,
    TicketType,
    ZonePosture,
    constants as C,
    factories as f,
    fixtures as fx,
    validate_error,
    validate_paginated,
    validate_success,
)


def _two_gates_one_open_session(api):
    """G1 is scanning from 18:10:00; G2 has never been used."""
    event = fx.create_event(api)
    zone = fx.create_zone(api, event["id"])
    first = fx.create_gate(api, event["id"], zone["id"], gate_code="G1", lanes_open=2)
    second = fx.create_gate(api, event["id"], zone["id"], gate_code="G2", lanes_open=1)
    fx.advance_event_to(api, event["id"], EventStatus.DOORS_OPEN)

    fx.set_clock(api, C.T_18_10_00)
    session = fx.open_scan_session(api, first["id"])
    return {
        "event": event,
        "zone": zone,
        "g1": first,
        "g2": second,
        "session": session,
    }


def _sessions_on(api, gate_id):
    _, meta = validate_paginated(
        api.list_scan_sessions(GATE_OPERATOR, params={"gate_id": gate_id})
    )
    return meta["total_count"]


def test_a_second_session_inside_an_open_interval_collides_only_on_its_own_gate(api):
    """18:15:00 lies inside G1's unbounded interval, while G2 is free to open.

    PRD: "Opening requires the event's `status` to be `DOORS_OPEN` or `IN_PROGRESS` and requires that the logical clock not fall inside the half-open interval from any existing session's `opened_at` up to but not including its `closed_at`, where a still-`OPEN` or `SYNCING` session is treated as having no upper bound."
    PRD: "This interval rule is the *only* thing governing gate occupancy at session creation: an attempt to open a second session on a gate that is already `SCANNING` must report `ERR_GATE_SESSION_OVERLAP` and never `ERR_INVALID_STATE`."

    Design: Difficulty/resource_temporal_overlap/gate_session_interval_is_half_open_and_an_adjacent_open_is_accepted
    """
    venue = _two_gates_one_open_session(api)
    assert venue["session"]["opened_at"] == C.T_18_10_00

    # The contended resource is the gate, so the neighbouring turnstile opens freely.
    other = fx.open_scan_session(api, venue["g2"]["id"], operator_device_id="SCN-2")
    assert other["opened_at"] == C.T_18_10_00

    fx.set_clock(api, C.T_18_15_00)
    gate = fx.read_gate(api, venue["g1"]["id"])
    assert gate["status"] == GateStatus.SCANNING

    validate_error(
        api.create_scan_session(
            f.scan_session_payload(
                venue["g1"]["id"], gate["version"], operator_device_id="SCN-3"
            ),
            GATE_OPERATOR,
        ),
        ApiErrorId.GATE_SESSION_OVERLAP,
        409,
    )

    assert _sessions_on(api, venue["g1"]["id"]) == 1
    assert fx.read_gate(api, venue["g1"]["id"])["version"] == gate["version"]


def test_a_session_opening_exactly_at_the_predecessors_closing_instant_is_accepted(api):
    """The upper bound is excluded, so 18:20:00 belongs to the successor.

    PRD: "A new session opening at exactly a prior session's `closed_at` is accepted, because that boundary is excluded."

    Design: Difficulty/resource_temporal_overlap/gate_session_interval_is_half_open_and_an_adjacent_open_is_accepted
    """
    venue = _two_gates_one_open_session(api)
    fx.open_scan_session(api, venue["g2"]["id"], operator_device_id="SCN-2")

    fx.set_clock(api, C.T_18_20_00)
    closed = fx.close_scan_session(api, venue["session"]["id"])
    assert closed["closed_at"] == C.T_18_20_00

    successor = fx.open_scan_session(
        api,
        venue["g1"]["id"],
        operator_device_id="SCN-3",
        mode=SessionMode.OFFLINE_CAPABLE,
    )
    assert successor["opened_at"] == C.T_18_20_00
    assert successor["mode"] == SessionMode.OFFLINE_CAPABLE

    assert _sessions_on(api, venue["g1"]["id"]) == 2
    assert _sessions_on(api, venue["g2"]["id"]) == 1
    assert fx.read_gate(api, venue["g1"]["id"])["status"] == GateStatus.SCANNING
    assert fx.read_gate(api, venue["g2"]["id"])["status"] == GateStatus.SCANNING


def _one_patron_two_tickets_one_exited(api):
    """Ada holds two bound seats; the first walked out at 18:10:30 and the second never moved."""
    venue = fx.on_sale_venue(api)
    event_id = venue["event"]["id"]
    ada = fx.register_patron(api)
    first = fx.issue_ticket(api, event_id, venue["zone"]["id"], ada["id"])
    second = fx.issue_ticket(api, event_id, venue["zone"]["id"], ada["id"])
    fx.bind_device(api, first["id"], ada["id"], "DEV-A1")
    fx.bind_device(api, second["id"], ada["id"], "DEV-A2")
    fx.advance_event(api, event_id, EventStatus.DOORS_OPEN)

    fx.set_clock(api, C.T_18_10_00)
    session = fx.open_scan_session(api, venue["gate"]["id"])
    fx.admit_ticket(api, session["id"], first["id"], "DEV-A1", "S1-ONLINE-001")
    fx.set_clock(api, C.T_18_10_30)
    fx.exit_ticket(api, session["id"], first["id"], "DEV-A1", "S1-ONLINE-002")

    fx.set_clock(api, C.T_18_12_00)
    venue.update(
        {"ada": ada, "first": first, "second": second, "session": session}
    )
    return venue


def test_a_locked_out_ticket_does_not_lock_out_its_holders_other_ticket(api):
    """At 18:12:00 the exited seat is refused while the sibling seat walks in.

    PRD: "The window is per ticket, not per patron: a second ticket held by the same person carries its own independent window, which is what stops a phone being handed back over the fence on one barcode while permitting a legitimate second holder to walk in."

    Design: Difficulty/resource_temporal_overlap/reentry_lockout_interval_is_scoped_per_ticket_not_per_patron
    """
    venue = _one_patron_two_tickets_one_exited(api)

    locked = fx.get_barcode(api, venue["first"]["id"])
    sibling = fx.get_barcode(api, venue["second"]["id"])
    # Both presentations are on the current epoch, so the barcode rule is not the discriminator.
    assert locked["barcode_epoch_index"] == C.EPOCH_AT_18_12_00
    assert sibling["barcode_epoch_index"] == C.EPOCH_AT_18_12_00

    validate_error(
        fx.denied_scan_response(
            api,
            venue["session"]["id"],
            locked["current_barcode"],
            "DEV-A1",
            "S1-ONLINE-003",
        ),
        ApiErrorId.REENTRY_LOCKOUT,
        409,
    )

    admitted = fx.live_scan(
        api,
        venue["session"]["id"],
        sibling["current_barcode"],
        "DEV-A2",
        "S1-ONLINE-004",
    )
    assert admitted["result"] == ScanResult.ADMITTED


def test_the_two_tickets_of_one_patron_keep_separate_presence_and_no_strike_is_booked(api):
    """One seat stays `EXITED`, the other is `INSIDE`, and the head count is one.

    PRD: "The three **operational** denials — `DENIED_CAPACITY`, `DENIED_REENTRY_LOCKOUT` and `DENIED_VOIDED` — persist their scan event but open no incident, book no strike and leave the patron's `fraud_risk_score` untouched, because a full house is not the patron's fault."

    Design: Difficulty/resource_temporal_overlap/reentry_lockout_interval_is_scoped_per_ticket_not_per_patron
    """
    venue = _one_patron_two_tickets_one_exited(api)
    validate_error(
        fx.denied_scan_response(
            api,
            venue["session"]["id"],
            fx.current_barcode(api, venue["first"]["id"]),
            "DEV-A1",
            "S1-ONLINE-003",
        ),
        ApiErrorId.REENTRY_LOCKOUT,
        409,
    )
    fx.live_scan(
        api,
        venue["session"]["id"],
        fx.current_barcode(api, venue["second"]["id"]),
        "DEV-A2",
        "S1-ONLINE-004",
    )

    locked = fx.read_ticket(api, venue["first"]["id"])
    assert locked["admission_status"] == AdmissionStatus.EXITED
    assert locked["admitted_scan_count"] == 1
    assert locked["last_exited_at"] == C.T_18_10_30

    sibling = fx.read_ticket(api, venue["second"]["id"])
    assert sibling["admission_status"] == AdmissionStatus.INSIDE
    assert sibling["admitted_scan_count"] == 1
    assert sibling["last_exited_at"] is None

    event = fx.read_event(api, venue["event"]["id"])
    assert event["live_occupancy"] == 1
    assert event["peak_live_occupancy"] == 1
    assert fx.read_zone(api, venue["zone"]["id"])["occupancy_count"] == 1

    ada = fx.read_patron(api, venue["ada"]["id"])
    assert ada["strike_count"] == 0
    assert ada["fraud_risk_score"] == 0

    assert len(fx.list_scan_events(api, ticket_id=venue["first"]["id"])) == 3
    assert len(fx.list_scan_events(api, ticket_id=venue["second"]["id"])) == 1


CREW_WINDOWS = {
    "first_shift": ("2026-09-12T18:00:00Z", "2026-09-12T20:00:00Z"),
    "overlapping_pair": ("2026-09-12T19:00:00Z", "2026-09-12T21:00:00Z"),
    "second_shift": ("2026-09-12T20:00:00Z", "2026-09-12T22:00:00Z"),
}


def _three_submitted_crew_shifts(api):
    """A four-pass crew budget with three shifts queued against it."""
    event = fx.create_event(api)
    zone = fx.create_zone(
        api,
        event["id"],
        zone_code="CREW",
        required_entitlement_level=EntitlementLevel.BACK_OF_HOUSE,
        fire_code_capacity=100,
        credential_capacity=4,
    )
    fx.create_gate(api, event["id"], zone["id"])
    fx.advance_event(api, event["id"], EventStatus.ON_SALE)

    people = {}
    for key, email, name, reference in (
        ("ada", "ada@example.com", "Ada Lovelace", "DL-ADA-1"),
        ("ben", "ben@example.com", "Ben Hall", "DL-BEN-1"),
        ("cyd", "cyd@example.com", "Cyd Marsh", "DL-CYD-1"),
    ):
        people[key] = fx.register_patron(
            api, email=email, display_name=name, document_reference=reference
        )

    requests = {}
    for key, holder, quantity, window, why in (
        ("first_shift", "ada", 3, "first_shift", "Load-in crew, first shift"),
        ("overlapping_pair", "ben", 2, "overlapping_pair", "Overlapping stage-hand pair"),
        ("second_shift", "cyd", 4, "second_shift", "Load-out crew, second shift"),
    ):
        valid_from, valid_until = CREW_WINDOWS[window]
        draft = fx.create_credential_draft(
            api,
            event["id"],
            zone["id"],
            people[holder]["id"],
            distribution_type=DistributionType.CREDENTIAL,
            quantity=quantity,
            valid_from=valid_from,
            valid_until=valid_until,
            justification=why,
        )
        requests[key] = fx.submit_credential_request(api, draft["id"])

    return {"event": event, "zone": zone, "people": people, "requests": requests}


def _approve(api, request_id, note):
    return api.approve_credential_request(
        request_id, f.note_payload(note), TICKETING_APPROVER
    )


def test_an_overlapping_shift_is_refused_once_the_earlier_shift_holds_the_budget(api):
    """Three approved passes plus two overlapping ones exceed a budget of four.

    PRD: "Approving a `CREDENTIAL` distribution therefore sums the `quantity` of every already-`APPROVED` credential request in the same zone whose window overlaps the candidate's window, adds the candidate's own `quantity`, and requires the total to be no greater than the zone's `credential_capacity`."
    PRD: "Equality is accepted; one pass beyond is refused with `ERR_ZONE_CREDENTIAL_WINDOW_CAPACITY`."

    Design: Difficulty/resource_temporal_overlap/credential_window_capacity_aggregates_only_overlapping_approved_requests
    """
    venue = _three_submitted_crew_shifts(api)

    first = validate_success(
        _approve(api, venue["requests"]["first_shift"]["id"], "First shift approved")
    )
    assert first["status"] == CredentialRequestStatus.APPROVED
    assert first["issued_ticket_count"] == 3
    assert first["forgone_revenue_cents"] == 3939

    validate_error(
        _approve(
            api, venue["requests"]["overlapping_pair"]["id"], "Trying the overlapping pair"
        ),
        ApiErrorId.ZONE_CREDENTIAL_WINDOW_CAPACITY,
        409,
    )

    refused = validate_success(
        api.get_credential_request(
            venue["requests"]["overlapping_pair"]["id"], TICKETING_APPROVER
        )
    )
    assert refused["status"] == CredentialRequestStatus.SUBMITTED
    assert refused["issued_ticket_count"] == 0
    assert refused["forgone_revenue_cents"] == 0
    _, meta = validate_paginated(
        api.list_tickets(
            BOX_OFFICE_AGENT,
            params={"credential_request_id": venue["requests"]["overlapping_pair"]["id"]},
        )
    )
    assert meta["total_count"] == 0


def test_a_shift_that_merely_touches_an_approved_window_gets_the_whole_budget(api):
    """The second shift starts exactly where the first ends, so it competes with nobody.

    PRD: "Two validity windows overlap when the first starts strictly before the second ends and the second starts strictly before the first ends; windows that merely touch — one ending at exactly the instant the other begins — do not overlap, so the later shift starts from a clean slate."

    Design: Difficulty/resource_temporal_overlap/credential_window_capacity_aggregates_only_overlapping_approved_requests
    """
    venue = _three_submitted_crew_shifts(api)
    validate_success(
        _approve(api, venue["requests"]["first_shift"]["id"], "First shift approved")
    )
    validate_error(
        _approve(
            api, venue["requests"]["overlapping_pair"]["id"], "Trying the overlapping pair"
        ),
        ApiErrorId.ZONE_CREDENTIAL_WINDOW_CAPACITY,
        409,
    )

    second = validate_success(
        _approve(api, venue["requests"]["second_shift"]["id"], "Second shift approved")
    )
    assert second["status"] == CredentialRequestStatus.APPROVED
    assert second["issued_ticket_count"] == 4
    assert second["forgone_revenue_cents"] == 5252

    zone = fx.read_zone(api, venue["zone"]["id"])
    assert zone["issued_entitlement_count"] == 7
    assert zone["comp_forgone_cents"] == 9191
    # The credential budget is a separate ledger from the fire-code ratio.
    assert zone["posture"] == ZonePosture.OPEN

    event = fx.read_event(api, venue["event"]["id"])
    assert event["entitlements_outstanding"] == 7
    assert event["settlement_pool_cents"] == 0

    for key, expected in (("first_shift", 3), ("second_shift", 4)):
        rows, meta = validate_paginated(
            api.list_tickets(
                BOX_OFFICE_AGENT,
                params={"credential_request_id": venue["requests"][key]["id"]},
            )
        )
        assert meta["total_count"] == expected
        for ticket in rows:
            assert ticket["ticket_type"] == TicketType.CREDENTIAL
            assert ticket["face_value_cents"] == 0
