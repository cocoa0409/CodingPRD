"""Reversals that must restore one quantity while deliberately leaving another alone.

An exit gives back the head count but not the high-water mark; remediation moves
money without minting it; a void gives back two live counts without rewriting the
ledger of revenue already given away.
"""

from test_helpers import (
    AdmissionStatus,
    ApiErrorId,
    AuditAction,
    AuditSubjectType,
    BOX_OFFICE_AGENT,
    DistributionType,
    EntitlementLevel,
    EventStatus,
    FraudRiskBasis,
    GATE_OPERATOR,
    IncidentStatus,
    LifecycleStatus,
    SECURITY_INVESTIGATOR,
    ScanResult,
    TICKETING_APPROVER,
    VENUE_ADMIN,
    ZonePosture,
    constants as C,
    factories as f,
    fixtures as fx,
    validate_error,
    validate_paginated,
    validate_success,
)


def _two_inside_one_about_to_leave(api):
    """Ada and Ben are both inside through G1, which runs two lanes at twenty a minute."""
    venue = fx.on_sale_venue(api)
    event_id = venue["event"]["id"]
    ada = fx.register_patron(api)
    ben = fx.register_patron(
        api, email="ben@example.com", display_name="Ben Hall", document_reference="DL-BEN-1"
    )
    ticket_ada = fx.issue_ticket(api, event_id, venue["zone"]["id"], ada["id"])
    ticket_ben = fx.issue_ticket(api, event_id, venue["zone"]["id"], ben["id"])
    fx.bind_device(api, ticket_ada["id"], ada["id"], "DEV-ADA")
    fx.bind_device(api, ticket_ben["id"], ben["id"], "DEV-BEN")
    fx.advance_event(api, event_id, EventStatus.DOORS_OPEN)

    fx.set_clock(api, C.T_18_10_00)
    session = fx.open_scan_session(api, venue["gate"]["id"])
    fx.admit_ticket(api, session["id"], ticket_ada["id"], "DEV-ADA", "S1-ONLINE-001")
    fx.admit_ticket(api, session["id"], ticket_ben["id"], "DEV-BEN", "S1-ONLINE-002")

    venue.update(
        {
            "ada": ada,
            "ben": ben,
            "ticket_ada": ticket_ada,
            "ticket_ben": ticket_ben,
            "session": session,
        }
    )
    return venue


def test_an_exit_restores_the_head_count_but_never_the_high_water_mark(api):
    """Live falls from two back to one while the peak stays pinned at two.

    PRD: "An event also keeps `peak_live_occupancy`, the highest value its `live_occupancy` has reached since the event was created, raised whenever the live figure exceeds it."
    PRD: "Alongside it the read reports the event's `event_id`, `live_occupancy`, `peak_live_occupancy`, `reconciled_attendance`, `fire_code_capacity`, the `headroom` remaining (the event's fire-code capacity less its live occupancy), and a `zone_occupancy` array carrying, for each access zone of the event, that zone's `id`, `zone_code`, `occupancy_count` and `fire_code_capacity`."

    Design: Difficulty/compensating_invariant/exit_scan_restores_occupancy_while_peak_occupancy_is_retained
    """
    venue = _two_inside_one_about_to_leave(api)

    before = fx.read_occupancy(api, venue["event"]["id"])
    assert before["live_occupancy"] == 2
    assert before["peak_live_occupancy"] == 2
    assert before["headroom"] == 198

    exit_event = fx.exit_ticket(
        api, venue["session"]["id"], venue["ticket_ben"]["id"], "DEV-BEN", "S1-ONLINE-003"
    )
    assert exit_event["result"] == ScanResult.EXIT_RECORDED

    after = fx.read_occupancy(api, venue["event"]["id"])
    assert after["live_occupancy"] == 1
    # A high-water mark recomputed from the current head count would report 1 here.
    assert after["peak_live_occupancy"] == 2
    assert after["headroom"] == 199
    # Forty places a minute and nobody left waiting outside.
    assert after["projected_clearance_minutes"] == 0


def test_the_admission_counters_are_cumulative_and_the_exit_leaves_them_untouched(api):
    """Presence goes down; the tallies of how many admissions happened do not.

    PRD: "`admitted_scan_count` counts admitted scans on the ticket across every source."
    PRD: "Admission moves the ticket `NOT_ADMITTED → INSIDE`, refreshes `last_admitted_at` and increments the ticket's `admitted_scan_count`, raises the zone's `occupancy_count` and the event's `live_occupancy` by one each, raises the event's `peak_live_occupancy` whenever the new live figure exceeds it, and increments the gate's `admitted_scan_count` and the session's `online_scan_count`."

    Design: Difficulty/compensating_invariant/exit_scan_restores_occupancy_while_peak_occupancy_is_retained
    """
    venue = _two_inside_one_about_to_leave(api)
    fx.exit_ticket(
        api, venue["session"]["id"], venue["ticket_ben"]["id"], "DEV-BEN", "S1-ONLINE-003"
    )

    left = fx.read_ticket(api, venue["ticket_ben"]["id"])
    assert left["admission_status"] == AdmissionStatus.EXITED
    assert left["admitted_scan_count"] == 1

    stayed = fx.read_ticket(api, venue["ticket_ada"]["id"])
    assert stayed["admission_status"] == AdmissionStatus.INSIDE
    assert stayed["admitted_scan_count"] == 1

    zone = fx.read_zone(api, venue["zone"]["id"])
    assert zone["occupancy_count"] == 1
    # Presence fell, but nobody's entitlement stopped existing.
    assert zone["issued_entitlement_count"] == 2

    assert fx.read_gate(api, venue["gate"]["id"])["admitted_scan_count"] == 2
    session = validate_success(api.get_scan_session(venue["session"]["id"], GATE_OPERATOR))
    assert session["online_scan_count"] == 3


def _mismatch_under_review_on_a_fourteen_thousand_seat(api):
    """Ada's 14000-cent seat was refused on a stolen phone; the pool holds 26000."""
    venue = fx.on_sale_venue(api)
    event_id = venue["event"]["id"]
    ada = fx.register_patron(api)
    ben = fx.register_patron(
        api, email="ben@example.com", display_name="Ben Hall", document_reference="DL-BEN-1"
    )
    ticket = fx.issue_ticket(
        api, event_id, venue["zone"]["id"], ada["id"], face_value_cents=14000
    )
    fx.issue_ticket(api, event_id, venue["zone"]["id"], ben["id"], face_value_cents=12000)
    fx.bind_device(api, ticket["id"], ada["id"], "DEV-ADA")
    fx.advance_event(api, event_id, EventStatus.DOORS_OPEN)

    fx.set_clock(api, C.T_18_10_00)
    session = fx.open_scan_session(api, venue["gate"]["id"])
    validate_error(
        fx.denied_scan_response(
            api,
            session["id"],
            fx.current_barcode(api, ticket["id"]),
            "DEV-STOLEN",
            "S1-ONLINE-001",
        ),
        ApiErrorId.DEVICE_MISMATCH,
        422,
    )
    incident = fx.list_incidents(api, ticket_id=ticket["id"])[0]
    under_review = validate_success(
        api.start_incident_review(incident["id"], {}, SECURITY_INVESTIGATOR)
    )

    venue.update(
        {"ada": ada, "ben": ben, "ticket": ticket, "incident": under_review}
    )
    return venue


def test_remediation_moves_money_out_of_the_pool_without_minting_any(api):
    """15600 cents leave the pool and land on the patron, so the total is unchanged.

    PRD: "**Remediation** requires the incident to be `UNDER_REVIEW`, its `ticket_id` to be non-null, and the event's `settlement_pool_cents` to be at least the credit about to be granted — an underfunded pool is refused with `ERR_SETTLEMENT_POOL_INSUFFICIENT`."
    PRD: "Step five: the granted credit is the base plus the goodwill less the penalty, floored at 0 so it can never be negative."

    Design: Difficulty/compensating_invariant/settlement_pool_plus_patron_credits_is_conserved_by_remediation
    """
    venue = _mismatch_under_review_on_a_fourteen_thousand_seat(api)
    assert venue["incident"]["status"] == IncidentStatus.UNDER_REVIEW

    pool_before = fx.read_event(api, venue["event"]["id"])["settlement_pool_cents"]
    assert pool_before == 26000

    remediated = validate_success(
        api.remediate_incident(
            venue["incident"]["id"],
            f.resolution_payload("Reader firmware fault confirmed; goodwill credit issued"),
            SECURITY_INVESTIGATOR,
        )
    )
    # Base 14000 on the fifteen-percent tier, 2100 goodwill, one strike at 500.
    assert remediated["remediation_credit_cents"] == 15600
    assert remediated["status"] == IncidentStatus.REMEDIATED

    pool_after = fx.read_event(api, venue["event"]["id"])["settlement_pool_cents"]
    ada_credit = fx.read_patron(api, venue["ada"]["id"])["remediation_credit_cents"]
    assert pool_after == 10400
    assert ada_credit == 15600
    assert pool_after + ada_credit == pool_before

    # No other patron ledger moved.
    assert fx.read_patron(api, venue["ben"]["id"])["remediation_credit_cents"] == 0


def test_the_payout_does_not_compensate_away_the_strike_it_was_paid_for(api):
    """The credit is granted and the strike still stands at one, scoring 23.

    PRD: "A single `DEVICE_MISMATCH` incident therefore scores 45 provisionally and 23 once adjudicated."

    Design: Difficulty/compensating_invariant/settlement_pool_plus_patron_credits_is_conserved_by_remediation
    """
    venue = _mismatch_under_review_on_a_fourteen_thousand_seat(api)
    validate_success(
        api.remediate_incident(
            venue["incident"]["id"],
            f.resolution_payload("Reader firmware fault confirmed; goodwill credit issued"),
            SECURITY_INVESTIGATOR,
        )
    )

    ada = fx.read_patron(api, venue["ada"]["id"])
    assert ada["strike_count"] == 1
    assert ada["fraud_risk_score"] == 23
    assert ada["fraud_risk_basis"] == FraudRiskBasis.ADJUDICATED

    ticket = fx.read_ticket(api, venue["ticket"]["id"])
    # Money changed hands; nobody was let in.
    assert ticket["admission_status"] == AdmissionStatus.DENIED_FLAGGED
    assert ticket["admitted_scan_count"] == 0
    assert fx.read_event(api, venue["event"]["id"])["live_occupancy"] == 0


def _two_credential_passes_issued(api):
    """Two audio-tech credentials approved into a crew zone, booking 2626 cents."""
    event = fx.create_event(api)
    zone = fx.create_zone(
        api,
        event["id"],
        zone_code="CREW",
        required_entitlement_level=EntitlementLevel.BACK_OF_HOUSE,
        fire_code_capacity=100,
        credential_capacity=8,
    )
    fx.create_gate(api, event["id"], zone["id"])
    fx.advance_event(api, event["id"], EventStatus.ON_SALE)
    ada = fx.register_patron(api)

    draft = fx.create_credential_draft(
        api,
        event["id"],
        zone["id"],
        ada["id"],
        distribution_type=DistributionType.CREDENTIAL,
        quantity=2,
        valid_from="2026-09-12T18:00:00Z",
        valid_until="2026-09-12T23:00:00Z",
        justification="Two audio techs",
    )
    fx.submit_credential_request(api, draft["id"])
    request = validate_success(
        api.approve_credential_request(
            draft["id"], f.note_payload("Audio crew approved"), TICKETING_APPROVER
        )
    )
    rows, meta = validate_paginated(
        api.list_tickets(VENUE_ADMIN, params={"credential_request_id": draft["id"]})
    )
    assert meta["total_count"] == 2

    return {
        "event": event,
        "zone": zone,
        "ada": ada,
        "request": request,
        "passes": rows,
    }


def test_voiding_a_pass_gives_back_both_live_counts_but_not_the_forgone_ledger(api):
    """Issued and outstanding fall from two to one while 2626 cents stay booked.

    PRD: "In every case the zone's `issued_entitlement_count` falls by one and its `posture` is recomputed, and the event's `entitlements_outstanding` falls by one."
    PRD: "Third, per issued ticket the zone's `issued_entitlement_count` and the event's `entitlements_outstanding` each rise by one, and the zone's `comp_forgone_cents` accumulates the booked forgone revenue."

    Design: Difficulty/compensating_invariant/voiding_a_credential_ticket_restores_counts_but_not_the_forgone_ledger
    """
    venue = _two_credential_passes_issued(api)
    assert venue["request"]["issued_ticket_count"] == 2
    assert venue["request"]["forgone_revenue_cents"] == 2626

    zone_before = fx.read_zone(api, venue["zone"]["id"])
    assert zone_before["issued_entitlement_count"] == 2
    assert zone_before["comp_forgone_cents"] == 2626
    assert fx.read_event(api, venue["event"]["id"])["entitlements_outstanding"] == 2

    voided = fx.void_ticket(
        api,
        venue["passes"][0]["id"],
        refund_to_holder=False,
        reason="Tech left the tour; credential surrendered",
    )
    assert voided["lifecycle_status"] == LifecycleStatus.VOIDED
    assert voided["face_value_cents"] == 0

    zone_after = fx.read_zone(api, venue["zone"]["id"])
    assert zone_after["issued_entitlement_count"] == 1
    # The give-away already happened, so the ledger of it is one-way.
    assert zone_after["comp_forgone_cents"] == 2626
    assert fx.read_event(api, venue["event"]["id"])["entitlements_outstanding"] == 1

    request = validate_success(
        api.get_credential_request(venue["request"]["id"], TICKETING_APPROVER)
    )
    # The request records what it granted, not what survived.
    assert request["issued_ticket_count"] == 2
    assert request["forgone_revenue_cents"] == 2626


def test_voiding_an_unrefunded_zero_face_pass_moves_no_money_at_all(api):
    """A false refund flag on a zero-face pass leaves both money fields alone.

    PRD: "When `refund_to_holder` is true *and* the ticket's `ticket_type` is `PAID`, the event's `settlement_pool_cents` falls by the ticket's `face_value_cents` and the holder's `remediation_credit_cents` rises by the same amount; when the flag is false, or the ticket was never paid for, no money moves."

    Design: Difficulty/compensating_invariant/voiding_a_credential_ticket_restores_counts_but_not_the_forgone_ledger
    """
    venue = _two_credential_passes_issued(api)
    assert fx.read_event(api, venue["event"]["id"])["settlement_pool_cents"] == 0

    fx.void_ticket(
        api,
        venue["passes"][0]["id"],
        refund_to_holder=False,
        reason="Tech left the tour; credential surrendered",
    )

    assert fx.read_event(api, venue["event"]["id"])["settlement_pool_cents"] == 0
    assert fx.read_patron(api, venue["ada"]["id"])["remediation_credit_cents"] == 0

    zone = fx.read_zone(api, venue["zone"]["id"])
    assert zone["posture"] == ZonePosture.OPEN

    _, meta = validate_paginated(
        api.list_tickets(
            BOX_OFFICE_AGENT,
            params={
                "credential_request_id": venue["request"]["id"],
                "lifecycle_status": LifecycleStatus.ISSUED,
            },
        )
    )
    assert meta["total_count"] == 1

    entries = fx.list_audit_entries(
        api, venue["event"]["id"], subject_type=AuditSubjectType.TICKET
    )
    assert len(entries) == 1
    assert entries[0]["action"] == AuditAction.TICKET_VOIDED
