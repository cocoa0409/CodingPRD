"""Requests whose fate is decided by the state of a *different* row.

A transfer reads an instant off the event, a scan reads a status two hops away
on the gate, a purchase reads a boolean off the buyer, and a credential
submission reads a posture derived from a zone's paid population.
"""

from test_helpers import (
    AdmissionStatus,
    ApiErrorId,
    AuditAction,
    BOX_OFFICE_AGENT,
    CredentialRequestStatus,
    DeviceBindingStatus,
    DistributionType,
    EntitlementLevel,
    EventStatus,
    GATE_OPERATOR,
    GateStatus,
    LifecycleStatus,
    ListingStatus,
    Role,
    SECURITY_INVESTIGATOR,
    ScanResult,
    SessionStatus,
    TransferStatus,
    VENUE_ADMIN,
    ZonePosture,
    constants as C,
    factories as f,
    fixtures as fx,
    make_patron_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


def _two_seats_before_the_window_closes(api):
    """Ada holds two paid seats and has offered the first one to Ben at 16:59:59."""
    venue = fx.on_sale_venue(api)
    event_id = venue["event"]["id"]
    ada = fx.register_patron(api)
    ben = fx.register_patron(
        api, email="ben@example.com", display_name="Ben Hall", document_reference="DL-BEN-1"
    )
    first = fx.issue_ticket(api, event_id, venue["zone"]["id"], ada["id"])
    second = fx.issue_ticket(api, event_id, venue["zone"]["id"], ada["id"])

    fx.set_clock(api, C.T_16_59_59)
    offer = validate_success(
        api.create_transfer_request(
            f.transfer_request_payload(first["id"], ben["id"]), make_patron_headers(ada["id"])
        ),
        201,
    )
    venue.update(
        {"ada": ada, "ben": ben, "first": first, "second": second, "offer": offer}
    )
    return venue


def test_a_transfer_offered_one_second_inside_the_window_stands_and_the_next_is_refused(api):
    """16:59:59 opens an offer; the closing instant itself refuses a new one.

    PRD: "14. Transfers require the logical clock strictly before the event's `transfer_window_closes_at` and an event `status` of `ON_SALE` or `DOORS_OPEN` — `ERR_EVENT_STATE_FORBIDS_TRANSFER` (409), on transfer creation and transfer acceptance."

    Design: Difficulty/cross_entity_state_dependency/transfer_blocked_by_event_transfer_window_closing_instant
    """
    venue = _two_seats_before_the_window_closes(api)
    assert venue["offer"]["status"] == TransferStatus.PENDING
    assert venue["offer"]["decided_at"] is None

    fx.set_clock(api, C.TRANSFER_WINDOW_CLOSES_AT)
    validate_error(
        api.create_transfer_request(
            f.transfer_request_payload(venue["second"]["id"], venue["ben"]["id"]),
            make_patron_headers(venue["ada"]["id"]),
        ),
        ApiErrorId.EVENT_STATE_FORBIDS_TRANSFER,
        409,
    )

    _, meta = validate_paginated(
        api.list_transfer_requests(
            SECURITY_INVESTIGATOR, params={"ticket_id": venue["second"]["id"]}
        )
    )
    assert meta["total_count"] == 0
    assert fx.read_ticket(api, venue["second"]["id"])["holder_patron_id"] == venue["ada"]["id"]


def test_the_closing_instant_also_blocks_acceptance_and_strands_the_pending_offer(api):
    """The recipient's move carries the same cross-entity dependency, and nothing auto-declines.

    PRD: "**Acceptance** is the recipient's move and is the transition that actually moves the entitlement. It requires the offer to be `PENDING`, the acting patron to be the named `to_patron_id`, the logical clock to be strictly before `transfer_window_closes_at`, the ticket's `transfer_count` to be strictly below the event's `transfer_limit_per_ticket`, the recipient's `identity_verified` to be true, and the ticket's `lifecycle_status` to be `ISSUED` or `TRANSFERRED`."

    Design: Difficulty/cross_entity_state_dependency/transfer_blocked_by_event_transfer_window_closing_instant
    """
    venue = _two_seats_before_the_window_closes(api)

    fx.set_clock(api, C.TRANSFER_WINDOW_CLOSES_AT)
    validate_error(
        api.accept_transfer_request(
            venue["offer"]["id"], {}, make_patron_headers(venue["ben"]["id"])
        ),
        ApiErrorId.EVENT_STATE_FORBIDS_TRANSFER,
        409,
    )

    stranded = validate_success(
        api.get_transfer_request(venue["offer"]["id"], SECURITY_INVESTIGATOR)
    )
    # The window governs the transition, not the request: it is still on the table.
    assert stranded["status"] == TransferStatus.PENDING
    assert stranded["decided_at"] is None

    ticket = fx.read_ticket(api, venue["first"]["id"])
    assert ticket["holder_patron_id"] == venue["ada"]["id"]
    assert ticket["transfer_count"] == 0
    assert ticket["lifecycle_status"] == LifecycleStatus.ISSUED


def _gate_gone_idle_after_one_admission(api):
    """Ada is inside, Ben is still outside, and the only session has been closed."""
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
    fx.set_clock(api, C.T_18_10_30)
    closed = fx.close_scan_session(api, session["id"])

    fx.set_clock(api, C.T_18_11_00)
    venue.update(
        {
            "ada": ada,
            "ben": ben,
            "ticket_ada": ticket_ada,
            "ticket_ben": ticket_ben,
            "session": session,
            "closed": closed,
            "ben_barcode": fx.current_barcode(api, ticket_ben["id"]),
        }
    )
    return venue


def test_a_scan_through_a_closed_session_reports_the_gate_rather_than_the_session(api):
    """Closing flipped the gate to `IDLE`, and the higher-priority gate rule answers.

    PRD: "11. The scan session's gate has `status` `SCANNING` — `ERR_GATE_NOT_SCANNING` (409), on live scanning and offline batch upload. This sits deliberately *above* rule 15 so that both session errors stay reachable: closing a session flips the gate to `IDLE` and the session to `CLOSED`, and that combination must report `ERR_GATE_NOT_SCANNING`, leaving `ERR_SESSION_NOT_OPEN` to the `SYNCING` case where the gate is still `SCANNING`."
    PRD: "Closing the session is permitted from `OPEN` or from `SYNCING`. It sets the session's `status` to `CLOSED` and its `closed_at` to the logical clock, moves the gate `SCANNING → IDLE`, copies that `closed_at` onto the gate's `last_session_closed_at`, and increments the gate's `version`."

    Design: Difficulty/cross_entity_state_dependency/scan_refused_when_the_gate_of_the_session_is_no_longer_scanning
    """
    venue = _gate_gone_idle_after_one_admission(api)

    assert venue["closed"]["status"] == SessionStatus.CLOSED
    assert venue["closed"]["closed_at"] == C.T_18_10_30
    gate = fx.read_gate(api, venue["gate"]["id"])
    assert gate["status"] == GateStatus.IDLE
    assert gate["last_session_closed_at"] == C.T_18_10_30

    validate_error(
        fx.denied_scan_response(
            api, venue["session"]["id"], venue["ben_barcode"], "DEV-BEN", "S1-ONLINE-002"
        ),
        ApiErrorId.GATE_NOT_SCANNING,
        409,
    )

    # Rule 11 sits above the adjudication band, so the refusal wrote nothing.
    assert len(fx.list_scan_events(api, scan_session_id=venue["session"]["id"])) == 1
    stale = validate_success(api.get_scan_session(venue["session"]["id"], GATE_OPERATOR))
    assert stale["online_scan_count"] == 1
    assert fx.read_ticket(api, venue["ticket_ben"]["id"])["admission_status"] == (
        AdmissionStatus.NOT_ADMITTED
    )


def test_reopening_a_session_restores_the_gate_and_the_identical_scan_succeeds(api):
    """A fresh session past the closed boundary puts the gate back to `SCANNING`.

    PRD: "A new session opening at exactly a prior session's `closed_at` is accepted, because that boundary is excluded."
    PRD: "A gate's `status` is `IDLE` whenever no session is open on it and `SCANNING` while one is; `last_session_closed_at` mirrors the `closed_at` of the most recently closed session on that gate and stays null until one closes; and `admitted_scan_count` is the number of scan events recorded through that gate whose `result` is `ADMITTED`."

    Design: Difficulty/cross_entity_state_dependency/scan_refused_when_the_gate_of_the_session_is_no_longer_scanning
    """
    venue = _gate_gone_idle_after_one_admission(api)
    validate_error(
        fx.denied_scan_response(
            api, venue["session"]["id"], venue["ben_barcode"], "DEV-BEN", "S1-ONLINE-002"
        ),
        ApiErrorId.GATE_NOT_SCANNING,
        409,
    )

    second = fx.open_scan_session(api, venue["gate"]["id"])
    assert second["status"] == SessionStatus.OPEN
    assert fx.read_gate(api, venue["gate"]["id"])["status"] == GateStatus.SCANNING

    readmitted = fx.live_scan(
        api, second["id"], venue["ben_barcode"], "DEV-BEN", "S2-ONLINE-001"
    )
    # The payload never changed; only the gate's status did.
    assert readmitted["result"] == ScanResult.ADMITTED

    assert fx.read_ticket(api, venue["ticket_ben"]["id"])["admission_status"] == (
        AdmissionStatus.INSIDE
    )
    assert fx.read_event(api, venue["event"]["id"])["live_occupancy"] == 2
    assert fx.read_gate(api, venue["gate"]["id"])["admitted_scan_count"] == 2


def _listing_awaiting_an_unverified_buyer(api):
    """Ada's 14500-cent listing, and Cyd who has never shown identification."""
    venue = fx.ticketed_venue(api)
    listing = fx.create_listing(api, venue["ticket"]["id"], venue["holder"]["id"], 14500)
    cyd = fx.register_patron(
        api, email="cyd@example.com", display_name="Cyd Marsh", verify=False
    )
    venue.update({"listing": listing, "cyd": cyd})
    return venue


def test_a_purchase_by_an_unverified_buyer_is_refused_and_leaves_the_listing_open(api):
    """The listing and the ticket are both fine; the third row is the problem.

    PRD: "It requires the listing to be `LISTED`, its `marketplace` to be `VERIFIED_PRIMARY` or `VERIFIED_PARTNER`, the acting patron to be someone other than the `seller_patron_id` (a seller buying their own listing is refused with `ERR_SELF_PURCHASE`), the buyer's `identity_verified` to be true, and the event's `status` to be `ON_SALE` or `DOORS_OPEN`."

    Design: Difficulty/cross_entity_state_dependency/resale_purchase_refused_until_the_buyer_patron_is_identity_verified
    """
    venue = _listing_awaiting_an_unverified_buyer(api)
    assert fx.read_patron(api, venue["cyd"]["id"])["identity_verified"] is False

    validate_error(
        api.purchase_resale_listing(
            venue["listing"]["id"], {}, make_patron_headers(venue["cyd"]["id"])
        ),
        ApiErrorId.RECIPIENT_NOT_VERIFIED,
        422,
    )

    listing = validate_success(
        api.get_resale_listing(venue["listing"]["id"], SECURITY_INVESTIGATOR)
    )
    assert listing["status"] == ListingStatus.LISTED
    assert listing["buyer_patron_id"] is None
    assert listing["seller_payout_cents"] is None
    assert fx.read_ticket(api, venue["ticket"]["id"])["lifecycle_status"] == (
        LifecycleStatus.LISTED
    )


def test_verifying_the_buyer_lets_the_identical_purchase_through_and_writes_the_split(api):
    """One identity check later the same call settles 14500 cents four ways.

    PRD: "On success the listing moves `LISTED → SOLD` with `buyer_patron_id` set to the buyer, the ticket moves `LISTED → RESOLD`, the ticket's `holder_patron_id` becomes the buyer, and the ticket's `device_binding_status` becomes `RELEASED` with `bound_device_fingerprint` cleared to null — the new holder must bind their own device."

    Design: Difficulty/cross_entity_state_dependency/resale_purchase_refused_until_the_buyer_patron_is_identity_verified
    """
    venue = _listing_awaiting_an_unverified_buyer(api)
    validate_error(
        api.purchase_resale_listing(
            venue["listing"]["id"], {}, make_patron_headers(venue["cyd"]["id"])
        ),
        ApiErrorId.RECIPIENT_NOT_VERIFIED,
        422,
    )

    verified = validate_success(
        api.verify_patron_identity(
            venue["cyd"]["id"],
            f.verify_identity_payload(document_reference="DL-CYD-1"),
            BOX_OFFICE_AGENT,
        )
    )
    assert verified["identity_verified"] is True

    sold = validate_success(
        api.purchase_resale_listing(
            venue["listing"]["id"], {}, make_patron_headers(venue["cyd"]["id"])
        )
    )
    assert sold["status"] == ListingStatus.SOLD
    assert sold["platform_fee_cents"] == 1051
    assert sold["venue_royalty_cents"] == 508
    assert sold["processing_fee_cents"] == 451
    assert sold["seller_payout_cents"] == 12490

    ticket = fx.read_ticket(api, venue["ticket"]["id"])
    assert ticket["lifecycle_status"] == LifecycleStatus.RESOLD
    assert ticket["holder_patron_id"] == venue["cyd"]["id"]
    assert ticket["device_binding_status"] == DeviceBindingStatus.RELEASED

    assert fx.read_patron(api, venue["holder"]["id"])["payout_balance_cents"] == 12490
    assert fx.read_patron(api, venue["cyd"]["id"])["payout_balance_cents"] == 0
    assert fx.read_event(api, venue["event"]["id"])["settlement_pool_cents"] == 12508

    sales = fx.list_audit_entries(
        api, venue["event"]["id"], action=AuditAction.RESALE_SOLD
    )
    assert len(sales) == 1
    assert sales[0]["actor_role"] == Role.PATRON


def _frozen_pit_and_roomy_loge(api):
    """Two paid seats fill a two-place pit while the loge stays empty."""
    event = fx.create_event(api)
    pit = fx.create_zone(
        api,
        event["id"],
        zone_code="PIT",
        required_entitlement_level=EntitlementLevel.PREMIUM,
        fire_code_capacity=2,
        credential_capacity=8,
    )
    loge = fx.create_zone(
        api,
        event["id"],
        zone_code="LOGE",
        required_entitlement_level=EntitlementLevel.PREMIUM,
        fire_code_capacity=50,
        credential_capacity=8,
    )
    fx.create_gate(api, event["id"], pit["id"])
    fx.advance_event(api, event["id"], EventStatus.ON_SALE)

    ada = fx.register_patron(api)
    ben = fx.register_patron(
        api, email="ben@example.com", display_name="Ben Hall", document_reference="DL-BEN-1"
    )
    cyd = fx.register_patron(
        api, email="cyd@example.com", display_name="Cyd Marsh", document_reference="DL-CYD-1"
    )
    fx.issue_ticket(api, event["id"], pit["id"], ada["id"])
    postures = [fx.read_zone(api, pit["id"])["posture"]]
    fx.issue_ticket(api, event["id"], pit["id"], ben["id"])
    postures.append(fx.read_zone(api, pit["id"])["posture"])

    window = {"valid_from": "2026-09-12T18:00:00Z", "valid_until": "2026-09-12T22:00:00Z"}
    requests = {
        "pit": fx.create_credential_draft(
            api,
            event["id"],
            pit["id"],
            cyd["id"],
            distribution_type=DistributionType.COMP,
            quantity=1,
            justification="Artist guest in the pit",
            **window,
        ),
        "loge": fx.create_credential_draft(
            api,
            event["id"],
            loge["id"],
            cyd["id"],
            distribution_type=DistributionType.COMP,
            quantity=1,
            justification="Artist guest moved to the loge",
            **window,
        ),
    }
    return {
        "event": event,
        "pit": pit,
        "loge": loge,
        "cyd": cyd,
        "postures": postures,
        "requests": requests,
    }


def test_a_valid_draft_cannot_be_submitted_into_a_zone_the_paid_seats_have_frozen(api):
    """Two paid seats in two places drive the ratio to 1.00 and stop the comp.

    PRD: "The posture is derived from the exact ratio of `issued_entitlement_count` to the zone's `fire_code_capacity`, compared without rounding: the posture is `FROZEN` when that ratio is at least 1.00, `RESTRICTED` when it is at least 0.90 but below 1.00, and `OPEN` otherwise."
    PRD: "`RESTRICTED` is advisory and still permits credential submission and approval; `FROZEN` blocks both, with `ERR_ZONE_FROZEN`."

    Design: Difficulty/cross_entity_state_dependency/credential_submit_refused_while_the_access_zone_posture_is_frozen
    """
    venue = _frozen_pit_and_roomy_loge(api)

    # One of two places is a ratio of 0.50, below the advisory band.
    assert venue["postures"][0] == ZonePosture.OPEN
    assert venue["postures"][1] == ZonePosture.FROZEN
    pit = fx.read_zone(api, venue["pit"]["id"])
    assert pit["issued_entitlement_count"] == 2

    validate_error(
        api.submit_credential_request(
            venue["requests"]["pit"]["id"], {}, BOX_OFFICE_AGENT
        ),
        ApiErrorId.ZONE_FROZEN,
        409,
    )

    blocked = validate_success(
        api.get_credential_request(venue["requests"]["pit"]["id"], VENUE_ADMIN)
    )
    assert blocked["status"] == CredentialRequestStatus.DRAFT
    assert blocked["requested_by_user_id"] is None


def test_the_same_draft_against_a_roomy_zone_submits_normally(api):
    """The dependency is on the zone, so the loge copy of the request goes through.

    PRD: "Submission moves the request to `SUBMITTED` and stamps `requested_by_user_id` with the submitting agent's `X-User-ID`."

    Design: Difficulty/cross_entity_state_dependency/credential_submit_refused_while_the_access_zone_posture_is_frozen
    """
    venue = _frozen_pit_and_roomy_loge(api)
    validate_error(
        api.submit_credential_request(
            venue["requests"]["pit"]["id"], {}, BOX_OFFICE_AGENT
        ),
        ApiErrorId.ZONE_FROZEN,
        409,
    )

    submitted = validate_success(
        api.submit_credential_request(venue["requests"]["loge"]["id"], {}, BOX_OFFICE_AGENT)
    )
    assert submitted["status"] == CredentialRequestStatus.SUBMITTED
    assert submitted["requested_by_user_id"] == C.AGENT_USER_ID

    loge = fx.read_zone(api, venue["loge"]["id"])
    assert loge["posture"] == ZonePosture.OPEN
    assert loge["issued_entitlement_count"] == 0

    # Only the two paid seats are outstanding; a submission issues nothing.
    assert fx.read_event(api, venue["event"]["id"])["entitlements_outstanding"] == 2
