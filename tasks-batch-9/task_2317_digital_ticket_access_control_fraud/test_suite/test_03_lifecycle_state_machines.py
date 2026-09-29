"""State machines with shapes other than a straight line.

A ticket carries two independent status dimensions, a credential request loops
back on itself a bounded number of times, and an incident under review has two
exits whose side effects point in opposite directions.
"""

from test_helpers import (
    AdmissionStatus,
    ApiErrorId,
    BOX_OFFICE_AGENT,
    CredentialRequestStatus,
    DistributionType,
    EventStatus,
    FraudRiskBasis,
    IncidentStatus,
    LifecycleStatus,
    ListingStatus,
    SECURITY_INVESTIGATOR,
    TICKETING_APPROVER,
    ZonePosture,
    constants as C,
    factories as f,
    fixtures as fx,
    make_patron_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

ADA_DEVICE = "DEV-ADA"


def _bound_ticket_at_the_gate(api):
    """Ada's bound 12000-cent seat, doors open, clock at 18:10 and a session up."""
    return fx.scan_ready_venue(api, device_fingerprint=ADA_DEVICE)


def test_listing_and_delisting_walk_the_lifecycle_dimension_and_leave_admission_alone(api):
    """`ISSUED → LISTED → ISSUED` completes without disturbing `admission_status`.

    PRD: "Listing moves the ticket `ISSUED → LISTED` (or `TRANSFERRED → LISTED` for a ticket that has changed hands), opens the listing in `LISTED` with `platform_fee_cents`, `venue_royalty_cents`, `processing_fee_cents` and `seller_payout_cents` all null, increments the ticket's `version`, and appends an audit entry with the action `RESALE_LISTED` against `subject_type` `RESALE_LISTING`."
    PRD: "it moves the listing `LISTED → DELISTED`, reverts the ticket's `lifecycle_status` to `ISSUED`, and increments the ticket's `version`."

    Design: Difficulty/non_linear_state_machine/ticket_lifecycle_and_admission_dimensions_advance_independently
    """
    venue = _bound_ticket_at_the_gate(api)
    holder = make_patron_headers(venue["holder"]["id"])

    listing = fx.create_listing(api, venue["ticket"]["id"], venue["holder"]["id"], 14500)
    listed = fx.read_ticket(api, venue["ticket"]["id"])
    assert listed["lifecycle_status"] == LifecycleStatus.LISTED
    assert listed["admission_status"] == AdmissionStatus.NOT_ADMITTED

    validate_success(api.delist_resale_listing(listing["id"], {}, holder))

    delisted = fx.read_ticket(api, venue["ticket"]["id"])
    assert delisted["lifecycle_status"] == LifecycleStatus.ISSUED
    # The round trip through the marketplace never touched the presence dimension.
    assert delisted["admission_status"] == AdmissionStatus.NOT_ADMITTED
    assert delisted["version"] > listed["version"]

    assert validate_success(
        api.get_resale_listing(listing["id"], SECURITY_INVESTIGATOR)
    )["status"] == ListingStatus.DELISTED


def test_an_entry_and_an_exit_walk_the_admission_dimension_and_leave_lifecycle_alone(api):
    """`NOT_ADMITTED → INSIDE → EXITED` completes while the lifecycle stays `ISSUED`.

    PRD: "An **exit** scan is far simpler: it requires the ticket's `admission_status` to be `INSIDE` and the session to be `OPEN`, persists a scan event with `result` `EXIT_RECORDED`, moves the ticket `INSIDE → EXITED`, sets `last_exited_at` to the logical clock, and lowers the zone's `occupancy_count` and the event's `live_occupancy` by one each, conserving the head count."

    Design: Difficulty/non_linear_state_machine/ticket_lifecycle_and_admission_dimensions_advance_independently
    """
    venue = _bound_ticket_at_the_gate(api)
    ticket_id = venue["ticket"]["id"]
    session_id = venue["session"]["id"]

    listing = fx.create_listing(api, ticket_id, venue["holder"]["id"], 14500)
    validate_success(
        api.delist_resale_listing(
            listing["id"], {}, make_patron_headers(venue["holder"]["id"])
        )
    )

    fx.admit_ticket(api, session_id, ticket_id, ADA_DEVICE, "S1-ONLINE-001")
    admitted = fx.read_ticket(api, ticket_id)
    assert admitted["admission_status"] == AdmissionStatus.INSIDE
    assert admitted["lifecycle_status"] == LifecycleStatus.ISSUED

    fx.exit_ticket(api, session_id, ticket_id, ADA_DEVICE, "S1-ONLINE-002")

    exited = fx.read_ticket(api, ticket_id)
    assert exited["admission_status"] == AdmissionStatus.EXITED
    # A ticket that walked in and out again is still a perfectly ordinary entitlement.
    assert exited["lifecycle_status"] == LifecycleStatus.ISSUED
    assert exited["admitted_scan_count"] == 1
    assert exited["last_exited_at"] == C.T_18_10_00

    event = fx.read_event(api, venue["event"]["id"])
    assert event["live_occupancy"] == 0
    assert event["peak_live_occupancy"] == 1
    assert fx.read_zone(api, venue["zone"]["id"])["occupancy_count"] == 0


def _drafted_single_comp(api):
    """One `DRAFT` comp request for a single pass, ready to loop through review."""
    venue = fx.on_sale_venue(api)
    recipient = fx.register_patron(api)
    venue["request"] = fx.create_credential_draft(
        api,
        venue["event"]["id"],
        venue["zone"]["id"],
        recipient["id"],
        distribution_type=DistributionType.COMP,
        quantity=1,
        justification="One promoter comp, pending name confirmation",
    )
    venue["recipient"] = recipient
    return venue


def _request_changes(api, request_id, note):
    return validate_success(
        api.request_changes_credential_request(
            request_id, f.note_payload(note), TICKETING_APPROVER
        )
    )


def test_the_first_submission_out_of_draft_is_not_counted_as_a_revision(api):
    """Two resubmissions raise `revision_count` from zero to exactly two.

    PRD: "`revision_count` moves only on a resubmission out of `CHANGES_REQUESTED`; the first submission out of `DRAFT` leaves it at zero."

    Design: Difficulty/non_linear_state_machine/credential_request_revision_cycle_caps_at_two_resubmissions
    """
    venue = _drafted_single_comp(api)
    request_id = venue["request"]["id"]

    first = fx.submit_credential_request(api, request_id)
    assert first["status"] == CredentialRequestStatus.SUBMITTED
    assert first["revision_count"] == 0

    _request_changes(api, request_id, "Name the recipient on the request")
    second = fx.submit_credential_request(api, request_id)
    assert second["revision_count"] == 1

    _request_changes(api, request_id, "Justification still too thin")
    third = fx.submit_credential_request(api, request_id)
    assert third["revision_count"] == 2
    assert third["status"] == CredentialRequestStatus.SUBMITTED


def test_a_third_resubmission_is_refused_and_the_request_stays_in_changes_requested(api):
    """The loop terminates on the counter, leaving the request where it stood.

    PRD: "It again requires the event to be `ON_SALE` or `DOORS_OPEN` and the zone not to be `FROZEN`, and additionally requires `revision_count` to be strictly below 2; a third resubmission is refused with `ERR_MAX_REVISIONS_EXCEEDED`."

    Design: Difficulty/non_linear_state_machine/credential_request_revision_cycle_caps_at_two_resubmissions
    """
    venue = _drafted_single_comp(api)
    request_id = venue["request"]["id"]

    fx.submit_credential_request(api, request_id)
    for note in ("Name the recipient on the request", "Justification still too thin"):
        _request_changes(api, request_id, note)
        fx.submit_credential_request(api, request_id)
    _request_changes(api, request_id, "Zone assignment is wrong")

    validate_error(
        api.submit_credential_request(request_id, {}, BOX_OFFICE_AGENT),
        ApiErrorId.MAX_REVISIONS_EXCEEDED,
        409,
    )

    stuck = validate_success(api.get_credential_request(request_id, TICKETING_APPROVER))
    assert stuck["status"] == CredentialRequestStatus.CHANGES_REQUESTED
    assert stuck["revision_count"] == 2

    # Approval is declared out of SUBMITTED only, so this exit is not available.
    validate_error(
        api.approve_credential_request(
            request_id,
            f.note_payload("Trying to approve straight out of CHANGES_REQUESTED"),
            TICKETING_APPROVER,
        ),
        ApiErrorId.INVALID_STATE,
        409,
    )

    assert stuck["issued_ticket_count"] == 0
    assert stuck["forgone_revenue_cents"] == 0
    rows, meta = validate_paginated(
        api.list_tickets(
            BOX_OFFICE_AGENT, params={"credential_request_id": request_id}
        )
    )
    assert rows == []
    assert meta["total_count"] == 0

    zone = fx.read_zone(api, venue["zone"]["id"])
    assert zone["issued_entitlement_count"] == 0
    assert zone["posture"] == ZonePosture.OPEN


def _two_incidents_under_review(api):
    """Ada and Ben each carry one 6000-cent seat and one mismatch under review."""
    venue = fx.on_sale_venue(api)
    event_id = venue["event"]["id"]
    ada = fx.register_patron(api)
    ben = fx.register_patron(
        api, email="ben@example.com", display_name="Ben Hall", document_reference="DL-BEN-1"
    )
    ticket_ada = fx.issue_ticket(
        api, event_id, venue["zone"]["id"], ada["id"], face_value_cents=6000
    )
    ticket_ben = fx.issue_ticket(
        api, event_id, venue["zone"]["id"], ben["id"], face_value_cents=6000
    )
    fx.bind_device(api, ticket_ada["id"], ada["id"], ADA_DEVICE)
    fx.bind_device(api, ticket_ben["id"], ben["id"], "DEV-BEN")
    fx.advance_event(api, event_id, EventStatus.DOORS_OPEN)
    fx.set_clock(api, C.T_18_10_00)
    session = fx.open_scan_session(api, venue["gate"]["id"])

    for ticket, device, key in (
        (ticket_ada, "DEV-WRONG-A", "S1-ONLINE-001"),
        (ticket_ben, "DEV-WRONG-B", "S1-ONLINE-002"),
    ):
        validate_error(
            fx.denied_scan_response(
                api, session["id"], fx.current_barcode(api, ticket["id"]), device, key
            ),
            ApiErrorId.DEVICE_MISMATCH,
            422,
        )

    incident_ada = fx.list_incidents(api, ticket_id=ticket_ada["id"])[0]
    incident_ben = fx.list_incidents(api, ticket_id=ticket_ben["id"])[0]
    for incident in (incident_ada, incident_ben):
        validate_success(api.start_incident_review(incident["id"], {}, SECURITY_INVESTIGATOR))

    venue.update(
        {
            "ada": ada,
            "ben": ben,
            "ticket_ada": ticket_ada,
            "ticket_ben": ticket_ben,
            "incident_ada": incident_ada,
            "incident_ben": incident_ben,
        }
    )
    return venue


def test_remediation_pays_out_of_the_pool_while_dismissal_moves_no_money(api):
    """The same `UNDER_REVIEW` state pays 6400 through one exit and nothing through the other.

    PRD: "**Dismissal** requires the incident to be `UNDER_REVIEW`. It moves the incident `UNDER_REVIEW → DISMISSED`, grants no credit at all so `remediation_credit_cents` stays null, *withdraws* the strike booked when the incident was created by lowering the holder's `strike_count` by one, recomputes the patron's `fraud_risk_score` under the adjudicated reading — which drops dismissed incidents from the sum entirely — sets `fraud_risk_basis` to `ADJUDICATED`, and appends an audit entry with the action `DENIED_ENTRY_DISMISSED`."

    Design: Difficulty/non_linear_state_machine/denied_entry_incident_fork_remediate_and_dismiss_diverge
    """
    venue = _two_incidents_under_review(api)
    assert fx.read_event(api, venue["event"]["id"])["settlement_pool_cents"] == 12000

    remediated = validate_success(
        api.remediate_incident(
            venue["incident_ada"]["id"],
            f.resolution_payload("Genuine holder; reader fault"),
            SECURITY_INVESTIGATOR,
        )
    )
    dismissed = validate_success(
        api.dismiss_incident(
            venue["incident_ben"]["id"],
            f.resolution_payload("Operator scanned the wrong lane; no fraud and no loss"),
            SECURITY_INVESTIGATOR,
        )
    )

    # Base 6000 on the fifteen-percent tier, plus 900 goodwill, less one strike.
    assert remediated["status"] == IncidentStatus.REMEDIATED
    assert remediated["remediation_credit_cents"] == 6400
    assert dismissed["status"] == IncidentStatus.DISMISSED
    assert dismissed["remediation_credit_cents"] is None
    assert remediated["reviewer_user_id"] == C.INVESTIGATOR_USER_ID
    assert dismissed["reviewer_user_id"] == C.INVESTIGATOR_USER_ID

    assert fx.read_event(api, venue["event"]["id"])["settlement_pool_cents"] == 5600


def test_dismissal_withdraws_the_strike_that_remediation_keeps(api):
    """One holder ends at 23 with a strike, the other back at 0 with none.

    PRD: "On success the incident moves `UNDER_REVIEW → REMEDIATED`, `remediation_credit_cents` is written with the computed credit, the holder's `remediation_credit_cents` rises by that amount and the event's `settlement_pool_cents` falls by exactly the same amount, the patron's `fraud_risk_score` is recomputed under the adjudicated reading and `fraud_risk_basis` is set to `ADJUDICATED`, and an audit entry with the action `DENIED_ENTRY_REMEDIATED` is appended."

    Design: Difficulty/non_linear_state_machine/denied_entry_incident_fork_remediate_and_dismiss_diverge
    """
    venue = _two_incidents_under_review(api)

    validate_success(
        api.remediate_incident(
            venue["incident_ada"]["id"],
            f.resolution_payload("Genuine holder; reader fault"),
            SECURITY_INVESTIGATOR,
        )
    )
    validate_success(
        api.dismiss_incident(
            venue["incident_ben"]["id"],
            f.resolution_payload("Operator scanned the wrong lane; no fraud and no loss"),
            SECURITY_INVESTIGATOR,
        )
    )

    ada = fx.read_patron(api, venue["ada"]["id"])
    assert ada["strike_count"] == 1
    assert ada["remediation_credit_cents"] == 6400
    assert ada["fraud_risk_score"] == 23
    assert ada["fraud_risk_basis"] == FraudRiskBasis.ADJUDICATED

    ben = fx.read_patron(api, venue["ben"]["id"])
    assert ben["strike_count"] == 0
    assert ben["remediation_credit_cents"] == 0
    assert ben["fraud_risk_score"] == 0
    assert ben["fraud_risk_basis"] == FraudRiskBasis.ADJUDICATED

    # Adjudication decides money and risk, never the presence dimension.
    for ticket_key in ("ticket_ada", "ticket_ben"):
        ticket = fx.read_ticket(api, venue[ticket_key]["id"])
        assert ticket["admission_status"] == AdmissionStatus.DENIED_FLAGGED
