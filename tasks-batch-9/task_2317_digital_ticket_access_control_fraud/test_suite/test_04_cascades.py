"""Chains where a later hop is only reachable because an earlier one landed.

One denied scan reaches across four entities; one approval freezes a zone and
closes the door behind it; one void reverses a listing, two counters and a
money movement in a single call.
"""

from test_helpers import (
    AdmissionStatus,
    ApiErrorId,
    AuditAction,
    AuditSubjectType,
    BOX_OFFICE_AGENT,
    CredentialRequestStatus,
    DeviceBindingStatus,
    DistributionType,
    EntitlementLevel,
    EventStatus,
    FraudRiskBasis,
    GATE_OPERATOR,
    IncidentCategory,
    IncidentStatus,
    LifecycleStatus,
    ListingStatus,
    Role,
    SECURITY_INVESTIGATOR,
    ScanResult,
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

ADA_DEVICE = "DEV-ADA"


def _listed_ticket_denied_at_the_gate(api):
    """Ada's listed seat is presented at the turnstile by a borrowed phone."""
    venue = fx.on_sale_venue(api)
    event_id = venue["event"]["id"]
    ada = fx.register_patron(api)
    ticket = fx.issue_ticket(
        api, event_id, venue["zone"]["id"], ada["id"], face_value_cents=12000
    )
    fx.bind_device(api, ticket["id"], ada["id"], ADA_DEVICE)
    listing = fx.create_listing(api, ticket["id"], ada["id"], 14500)
    fx.advance_event(api, event_id, EventStatus.DOORS_OPEN)
    fx.set_clock(api, C.T_18_10_00)
    session = fx.open_scan_session(api, venue["gate"]["id"])

    response = fx.denied_scan_response(
        api,
        session["id"],
        fx.current_barcode(api, ticket["id"]),
        "DEV-BORROWED",
        "S1-ONLINE-001",
    )
    validate_error(response, ApiErrorId.DEVICE_MISMATCH, 422)

    venue.update({"ada": ada, "ticket": ticket, "listing": listing, "session": session})
    return venue


def test_the_mismatch_denial_persists_a_scan_event_an_incident_and_a_strike(api):
    """The 422 still leaves a scan event, an `OPEN` incident and a score of 45 behind.

    PRD: "Failures at rules 20 through 27 are **adjudication failures on a well-formed scan**: the server persists a scan event carrying the mapped denial result and the mapped error identifier as its `denied_reason_code`, and *then* returns that error with its declared HTTP status."
    PRD: "When a fraud-bearing denial does open an incident, the cascade runs in four links within the same request: the incident is created in `OPEN`; the holder's `strike_count` rises by one and their `fraud_risk_score` is recomputed under the provisional reading; if that recomputed score reaches 40, every `LISTED` listing of that patron is suspended; and each suspended listing reverts its ticket's `lifecycle_status` to `ISSUED`."

    Design: Difficulty/transitive_cascade/device_mismatch_denial_cascades_to_listing_suspension_and_lifecycle_revert
    """
    venue = _listed_ticket_denied_at_the_gate(api)
    assert venue["listing"]["cap_price_cents"] == 14500

    events = fx.list_scan_events(api, ticket_id=venue["ticket"]["id"])
    assert len(events) == 1
    assert events[0]["result"] == ScanResult.DENIED_DEVICE_MISMATCH
    assert events[0]["denied_reason_code"] == ApiErrorId.DEVICE_MISMATCH

    incidents = fx.list_incidents(api, ticket_id=venue["ticket"]["id"])
    assert len(incidents) == 1
    assert incidents[0]["category"] == IncidentCategory.DEVICE_MISMATCH
    assert incidents[0]["status"] == IncidentStatus.OPEN
    assert incidents[0]["patron_id"] == venue["ada"]["id"]
    assert incidents[0]["scan_event_id"] == events[0]["id"]

    ada = fx.read_patron(api, venue["ada"]["id"])
    assert ada["strike_count"] == 1
    assert ada["fraud_risk_score"] == 45
    assert ada["fraud_risk_basis"] == FraudRiskBasis.PROVISIONAL


def test_crossing_the_block_threshold_suspends_the_listing_and_frees_the_ticket(api):
    """45 clears the block threshold, so the listing dies and the ticket returns to `ISSUED`.

    PRD: "When a denied-entry incident is created against a patron and their recomputed `fraud_risk_score` reaches 40, or when a ticket carrying a live listing is voided, every `LISTED` listing of that seller moves `LISTED → SUSPENDED` and an audit entry with the action `RESALE_LISTING_SUSPENDED` is appended."
    PRD: "Suspension reverts the affected ticket's `lifecycle_status` from `LISTED` back to `ISSUED`, except where the ticket is itself being voided, in which case the void's own terminal status wins."

    Design: Difficulty/transitive_cascade/device_mismatch_denial_cascades_to_listing_suspension_and_lifecycle_revert
    """
    venue = _listed_ticket_denied_at_the_gate(api)

    listing = validate_success(
        api.get_resale_listing(venue["listing"]["id"], SECURITY_INVESTIGATOR)
    )
    assert listing["status"] == ListingStatus.SUSPENDED

    ticket = fx.read_ticket(api, venue["ticket"]["id"])
    assert ticket["lifecycle_status"] == LifecycleStatus.ISSUED
    assert ticket["admission_status"] == AdmissionStatus.DENIED_FLAGGED
    assert ticket["admitted_scan_count"] == 0

    # A denial never admits anybody, so no head count moved.
    assert fx.read_event(api, venue["event"]["id"])["live_occupancy"] == 0
    assert fx.read_zone(api, venue["zone"]["id"])["occupancy_count"] == 0
    assert fx.read_gate(api, venue["gate"]["id"])["admitted_scan_count"] == 0

    session = validate_success(api.get_scan_session(venue["session"]["id"], GATE_OPERATOR))
    assert session["online_scan_count"] == 1

    suspensions = fx.list_audit_entries(
        api, venue["event"]["id"], action=AuditAction.RESALE_LISTING_SUSPENDED
    )
    assert len(suspensions) == 1
    assert suspensions[0]["subject_id"] == venue["listing"]["id"]


def _back_of_house_with_a_submitted_batch_of_four(api):
    """A four-place back-of-house zone with four passes queued and one more drafted."""
    event = fx.create_event(api)
    zone = fx.create_zone(
        api,
        event["id"],
        zone_code="BOH",
        required_entitlement_level=EntitlementLevel.BACK_OF_HOUSE,
        fire_code_capacity=4,
        credential_capacity=8,
    )
    gate = fx.create_gate(api, event["id"], zone["id"])
    event = fx.advance_event(api, event["id"], EventStatus.ON_SALE)
    ada = fx.register_patron(api)
    ben = fx.register_patron(
        api, email="ben@example.com", display_name="Ben Hall", document_reference="DL-BEN-1"
    )

    window = {"valid_from": "2026-09-12T18:00:00Z", "valid_until": "2026-09-12T23:00:00Z"}
    first = fx.create_credential_draft(
        api,
        event["id"],
        zone["id"],
        ada["id"],
        distribution_type=DistributionType.CREDENTIAL,
        quantity=4,
        justification="Stage crew back-of-house passes",
        **window,
    )
    fx.submit_credential_request(api, first["id"])
    second = fx.create_credential_draft(
        api,
        event["id"],
        zone["id"],
        ben["id"],
        distribution_type=DistributionType.CREDENTIAL,
        quantity=1,
        justification="Late-added runner pass",
        **window,
    )
    return {
        "event": event,
        "zone": zone,
        "gate": gate,
        "ada": ada,
        "ben": ben,
        "first": first,
        "second": second,
    }


def test_approval_issues_the_batch_and_books_its_forgone_revenue_on_the_zone(api):
    """Four passes land, and 5252 cents of give-away value lands with them.

    PRD: "Second, as many tickets as the `quantity` are auto-issued to the `recipient_patron_id` in the request's zone, each with `ticket_type` equal to the request's `distribution_type`, `face_value_cents` of 0, `credential_request_id` pointing back at this request, `lifecycle_status` `ISSUED`, `admission_status` `NOT_ADMITTED` and `device_binding_status` `UNBOUND`, each with its own freshly minted `barcode_seed`; because the face value is zero, the event's `settlement_pool_cents` does not move."

    Design: Difficulty/transitive_cascade/credential_approval_cascade_freezes_zone_and_blocks_the_next_submit
    """
    venue = _back_of_house_with_a_submitted_batch_of_four(api)

    approved = validate_success(
        api.approve_credential_request(
            venue["first"]["id"], f.note_payload("Approved by ticketing"), TICKETING_APPROVER
        )
    )

    assert approved["status"] == CredentialRequestStatus.APPROVED
    assert approved["issued_ticket_count"] == 4
    assert approved["forgone_revenue_cents"] == 5252
    assert approved["approved_by_user_id"] == C.APPROVER_USER_ID
    assert approved["requested_by_user_id"] == C.AGENT_USER_ID

    rows, meta = validate_paginated(
        api.list_tickets(
            BOX_OFFICE_AGENT, params={"credential_request_id": venue["first"]["id"]}
        )
    )
    assert meta["total_count"] == 4
    seeds = set()
    for ticket in rows:
        assert ticket["ticket_type"] == TicketType.CREDENTIAL
        assert ticket["face_value_cents"] == 0
        assert ticket["device_binding_status"] == DeviceBindingStatus.UNBOUND
        assert ticket["lifecycle_status"] == LifecycleStatus.ISSUED
        assert ticket["admission_status"] == AdmissionStatus.NOT_ADMITTED
        seeds.add(fx.get_barcode(api, ticket["id"])["barcode_seed"])
    assert len(seeds) == 4

    zone = fx.read_zone(api, venue["zone"]["id"])
    assert zone["issued_entitlement_count"] == 4
    assert zone["comp_forgone_cents"] == 5252

    event = fx.read_event(api, venue["event"]["id"])
    assert event["entitlements_outstanding"] == 4
    # Give-aways carry no face value, so no cash reached the pool.
    assert event["settlement_pool_cents"] == 0

    entries = fx.list_audit_entries(
        api, venue["event"]["id"], subject_type=AuditSubjectType.CREDENTIAL_REQUEST
    )
    approvals = [e for e in entries if e["action"] == AuditAction.CREDENTIAL_REQUEST_APPROVED]
    assert len(approvals) == 1
    assert approvals[0]["actor_role"] == Role.TICKETING_APPROVER
    assert approvals[0]["subject_id"] == venue["first"]["id"]


def test_the_zone_freezes_on_the_same_call_and_refuses_the_next_submission(api):
    """The ratio jumps straight to 1.00, so the following submit is refused.

    PRD: "The posture is derived from the exact ratio of `issued_entitlement_count` to the zone's `fire_code_capacity`, compared without rounding: the posture is `FROZEN` when that ratio is at least 1.00, `RESTRICTED` when it is at least 0.90 but below 1.00, and `OPEN` otherwise."
    PRD: "Submission requires the event to be `ON_SALE` or `DOORS_OPEN` and the target zone's `posture` to be anything other than `FROZEN`, and it appends an audit entry with the action `CREDENTIAL_REQUEST_SUBMITTED`."

    Design: Difficulty/transitive_cascade/credential_approval_cascade_freezes_zone_and_blocks_the_next_submit
    """
    venue = _back_of_house_with_a_submitted_batch_of_four(api)
    assert fx.read_zone(api, venue["zone"]["id"])["posture"] == ZonePosture.OPEN

    validate_success(
        api.approve_credential_request(
            venue["first"]["id"], f.note_payload("Approved by ticketing"), TICKETING_APPROVER
        )
    )

    # Four of four places: the advisory band was never entered.
    assert fx.read_zone(api, venue["zone"]["id"])["posture"] == ZonePosture.FROZEN

    validate_error(
        api.submit_credential_request(venue["second"]["id"], {}, BOX_OFFICE_AGENT),
        ApiErrorId.ZONE_FROZEN,
        409,
    )

    stalled = validate_success(
        api.get_credential_request(venue["second"]["id"], TICKETING_APPROVER)
    )
    assert stalled["status"] == CredentialRequestStatus.DRAFT
    assert stalled["revision_count"] == 0
    assert stalled["requested_by_user_id"] is None


def _listed_ticket_ready_to_void(api):
    """Ada's paid seat is bound and listed, and the pool is holding her money."""
    venue = fx.on_sale_venue(api)
    ada = fx.register_patron(api)
    ticket = fx.issue_ticket(
        api, venue["event"]["id"], venue["zone"]["id"], ada["id"], face_value_cents=12000
    )
    fx.bind_device(api, ticket["id"], ada["id"], ADA_DEVICE)
    listing = fx.create_listing(api, ticket["id"], ada["id"], 14500)
    venue.update({"ada": ada, "ticket": ticket, "listing": listing})
    return venue


def test_voiding_a_listed_ticket_suspends_the_listing_and_leaves_the_binding_alone(api):
    """The listing dies with the ticket while presence and device stay exactly as they were.

    PRD: "Voiding from `LISTED` additionally sets that ticket's `LISTED` resale listing to `SUSPENDED`."
    PRD: "Every void appends an audit entry with `subject_type` `TICKET` and the action `TICKET_VOIDED`."

    Design: Difficulty/transitive_cascade/ticket_void_cascade_reverses_listing_zone_and_settlement_pool
    """
    venue = _listed_ticket_ready_to_void(api)

    voided = fx.void_ticket(
        api,
        venue["ticket"]["id"],
        refund_to_holder=True,
        reason="Chargeback on the original purchase",
    )

    assert voided["lifecycle_status"] == LifecycleStatus.VOIDED
    # Voiding is a lifecycle move only; the presence dimension is untouched.
    assert voided["admission_status"] == AdmissionStatus.NOT_ADMITTED
    assert voided["device_binding_status"] == DeviceBindingStatus.BOUND
    assert voided["bound_device_fingerprint"] == ADA_DEVICE

    listing = validate_success(
        api.get_resale_listing(venue["listing"]["id"], SECURITY_INVESTIGATOR)
    )
    assert listing["status"] == ListingStatus.SUSPENDED
    assert listing["buyer_patron_id"] is None

    entries = fx.list_audit_entries(
        api, venue["event"]["id"], subject_type=AuditSubjectType.TICKET
    )
    voids = [e for e in entries if e["action"] == AuditAction.TICKET_VOIDED]
    assert len(voids) == 1
    assert voids[0]["actor_role"] == Role.SECURITY_INVESTIGATOR
    assert voids[0]["subject_id"] == venue["ticket"]["id"]


def test_the_void_decrements_both_counters_and_moves_the_refund_out_of_the_pool(api):
    """Twelve thousand cents leave the pool for the holder and both counters fall.

    PRD: "In every case the zone's `issued_entitlement_count` falls by one and its `posture` is recomputed, and the event's `entitlements_outstanding` falls by one."
    PRD: "When `refund_to_holder` is true *and* the ticket's `ticket_type` is `PAID`, the event's `settlement_pool_cents` falls by the ticket's `face_value_cents` and the holder's `remediation_credit_cents` rises by the same amount; when the flag is false, or the ticket was never paid for, no money moves."

    Design: Difficulty/transitive_cascade/ticket_void_cascade_reverses_listing_zone_and_settlement_pool
    """
    venue = _listed_ticket_ready_to_void(api)

    before = fx.read_event(api, venue["event"]["id"])
    assert before["settlement_pool_cents"] == 12000
    assert before["entitlements_outstanding"] == 1
    assert fx.read_zone(api, venue["zone"]["id"])["issued_entitlement_count"] == 1
    assert fx.read_patron(api, venue["ada"]["id"])["remediation_credit_cents"] == 0

    fx.void_ticket(
        api,
        venue["ticket"]["id"],
        refund_to_holder=True,
        reason="Chargeback on the original purchase",
    )

    zone = fx.read_zone(api, venue["zone"]["id"])
    assert zone["issued_entitlement_count"] == 0
    assert zone["posture"] == ZonePosture.OPEN

    after = fx.read_event(api, venue["event"]["id"])
    assert after["entitlements_outstanding"] == 0
    assert after["settlement_pool_cents"] == 0

    ada = fx.read_patron(api, venue["ada"]["id"])
    assert ada["remediation_credit_cents"] == 12000
    # The money moved rather than evaporating.
    assert after["settlement_pool_cents"] + ada["remediation_credit_cents"] == 12000
