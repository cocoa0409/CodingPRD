"""Requests that violate two rules at once, plus the control that proves the loser lives.

Each pair is chosen so the winning rule cannot be identified from the HTTP
status alone, or so both rules need real computation before either can fire.
"""

from test_helpers import (
    AdmissionStatus,
    ApiErrorId,
    BOX_OFFICE_AGENT,
    EventStatus,
    LifecycleStatus,
    SECURITY_INVESTIGATOR,
    ScanResult,
    TransferStatus,
    constants as C,
    factories as f,
    fixtures as fx,
    make_patron_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


def _full_zone_with_a_voided_ticket(api):
    """A one-place zone already at its ceiling, one voided seat and one healthy one."""
    event = fx.create_event(api)
    zone = fx.create_zone(api, event["id"], fire_code_capacity=1)
    gate = fx.create_gate(api, event["id"], zone["id"])
    fx.advance_event(api, event["id"], EventStatus.ON_SALE)

    holders = {}
    for key, email, name, reference in (
        ("ada", "ada@example.com", "Ada Lovelace", "DL-ADA-1"),
        ("ben", "ben@example.com", "Ben Hall", "DL-BEN-1"),
        ("cyd", "cyd@example.com", "Cyd Marsh", "DL-CYD-1"),
    ):
        patron = fx.register_patron(
            api, email=email, display_name=name, document_reference=reference
        )
        ticket = fx.issue_ticket(api, event["id"], zone["id"], patron["id"])
        fx.bind_device(api, ticket["id"], patron["id"], f"DEV-{key.upper()}")
        holders[key] = {"patron": patron, "ticket": ticket}

    fx.advance_event(api, event["id"], EventStatus.DOORS_OPEN)
    fx.set_clock(api, C.T_18_10_00)
    session = fx.open_scan_session(api, gate["id"])

    barcodes = {
        key: fx.current_barcode(api, holders[key]["ticket"]["id"]) for key in holders
    }
    fx.live_scan(api, session["id"], barcodes["ada"], "DEV-ADA", "S1-ONLINE-001")
    fx.void_ticket(
        api,
        holders["ben"]["ticket"]["id"],
        refund_to_holder=False,
        reason="Fraudulent purchase instrument",
    )

    return {
        "event": event,
        "zone": zone,
        "gate": gate,
        "session": session,
        "holders": holders,
        "barcodes": barcodes,
    }


def test_the_voided_ticket_rule_wins_over_the_zone_capacity_rule_at_the_same_status(api):
    """Both refusals are 409, and the earlier rule is the one that answers.

    PRD: "When several rules could reject the same request, the lowest-numbered rule below wins and no later rule is evaluated."
    PRD: "10. The target ticket is not `VOIDED` — `ERR_TICKET_VOIDED` (409), on device binding, transfer creation, resale listing creation, live scanning and offline batch upload."

    Design: Difficulty/priority_pair_validation_conflict/voided_ticket_outranks_zone_capacity_full
    """
    venue = _full_zone_with_a_voided_ticket(api)
    ben = venue["holders"]["ben"]

    validate_error(
        fx.denied_scan_response(
            api, venue["session"]["id"], venue["barcodes"]["ben"], "DEV-BEN", "S1-ONLINE-002"
        ),
        ApiErrorId.TICKET_VOIDED,
        409,
    )

    # A refusal above the adjudication band persists nothing at all.
    assert fx.list_scan_events(api, ticket_id=ben["ticket"]["id"]) == []
    assert fx.read_ticket(api, ben["ticket"]["id"])["admission_status"] == (
        AdmissionStatus.NOT_ADMITTED
    )
    assert fx.list_incidents(api, ticket_id=ben["ticket"]["id"]) == []

    assert fx.read_zone(api, venue["zone"]["id"])["occupancy_count"] == 1
    assert fx.read_event(api, venue["event"]["id"])["live_occupancy"] == 1


def test_the_zone_capacity_rule_still_fires_for_a_ticket_that_is_not_voided(api):
    """The healthy holder reaches the capacity check and is turned away by it.

    PRD: "26. Zone fire code: admitting one more person keeps the zone's `occupancy_count` at or below its `fire_code_capacity` — `ERR_ZONE_CAPACITY_FULL` (409), on live scanning only."

    Design: Difficulty/priority_pair_validation_conflict/voided_ticket_outranks_zone_capacity_full
    """
    venue = _full_zone_with_a_voided_ticket(api)
    cyd = venue["holders"]["cyd"]

    validate_error(
        fx.denied_scan_response(
            api, venue["session"]["id"], venue["barcodes"]["cyd"], "DEV-CYD", "S1-ONLINE-003"
        ),
        ApiErrorId.ZONE_CAPACITY_FULL,
        409,
    )

    events = fx.list_scan_events(api, ticket_id=cyd["ticket"]["id"])
    assert len(events) == 1
    assert events[0]["result"] == ScanResult.DENIED_CAPACITY
    assert events[0]["denied_reason_code"] == ApiErrorId.ZONE_CAPACITY_FULL
    assert fx.read_ticket(api, cyd["ticket"]["id"])["admission_status"] == (
        AdmissionStatus.NOT_ADMITTED
    )

    # A full house is nobody's fault, so no investigation and no strike.
    assert fx.list_incidents(api, ticket_id=cyd["ticket"]["id"]) == []
    assert fx.read_patron(api, cyd["patron"]["id"])["strike_count"] == 0

    assert len(fx.list_scan_events(api, scan_session_id=venue["session"]["id"])) == 2
    assert fx.read_zone(api, venue["zone"]["id"])["occupancy_count"] == 1


def _blocked_seller_and_clean_seller(api):
    """Ada is at 45 after a mismatch; Ben is spotless. Both hold a 12000-cent seat."""
    venue = fx.on_sale_venue(api)
    event_id = venue["event"]["id"]
    ada = fx.register_patron(api)
    ben = fx.register_patron(
        api, email="ben@example.com", display_name="Ben Hall", document_reference="DL-BEN-1"
    )
    scanned = fx.issue_ticket(api, event_id, venue["zone"]["id"], ada["id"])
    ada_spare = fx.issue_ticket(api, event_id, venue["zone"]["id"], ada["id"])
    ben_ticket = fx.issue_ticket(api, event_id, venue["zone"]["id"], ben["id"])
    fx.bind_device(api, scanned["id"], ada["id"], "DEV-ADA")
    fx.advance_event(api, event_id, EventStatus.DOORS_OPEN)
    fx.set_clock(api, C.T_18_10_00)
    session = fx.open_scan_session(api, venue["gate"]["id"])

    validate_error(
        fx.denied_scan_response(
            api,
            session["id"],
            fx.current_barcode(api, scanned["id"]),
            "DEV-IMPOSTER",
            "S1-ONLINE-001",
        ),
        ApiErrorId.DEVICE_MISMATCH,
        422,
    )
    assert fx.read_patron(api, ada["id"])["fraud_risk_score"] == 45

    venue.update(
        {"ada": ada, "ben": ben, "ada_spare": ada_spare, "ben_ticket": ben_ticket}
    )
    return venue


def test_the_fraud_block_wins_over_the_price_cap_for_a_blocked_seller(api):
    """A blocked seller asking far over the cap is refused for the block, not the price.

    PRD: "28. The acting patron's `fraud_risk_score` is strictly below 40 — `ERR_PATRON_FRAUD_BLOCKED` (403), on resale listing creation and transfer creation."

    Design: Difficulty/priority_pair_validation_conflict/fraud_block_outranks_price_cap_exceeded
    """
    venue = _blocked_seller_and_clean_seller(api)
    ticket = fx.read_ticket(api, venue["ada_spare"]["id"])

    validate_error(
        api.create_resale_listing(
            f.resale_listing_payload(ticket["id"], 99999, ticket["version"]),
            make_patron_headers(venue["ada"]["id"]),
        ),
        ApiErrorId.PATRON_FRAUD_BLOCKED,
        403,
    )

    _, meta = validate_paginated(
        api.list_resale_listings(SECURITY_INVESTIGATOR, params={"ticket_id": ticket["id"]})
    )
    assert meta["total_count"] == 0

    after = fx.read_ticket(api, ticket["id"])
    assert after["lifecycle_status"] == LifecycleStatus.ISSUED
    # A refused create is not a mutation.
    assert after["version"] == ticket["version"]


def test_the_price_cap_still_fires_for_a_seller_with_a_clean_record(api):
    """The same over-cap ask from a clean seller is refused by the cap rule.

    PRD: "35. `ask_price_cents` does not exceed the computed cap — `ERR_PRICE_CAP_EXCEEDED` (422), on resale listing creation."

    Design: Difficulty/priority_pair_validation_conflict/fraud_block_outranks_price_cap_exceeded
    """
    venue = _blocked_seller_and_clean_seller(api)
    ticket = fx.read_ticket(api, venue["ben_ticket"]["id"])

    validate_error(
        api.create_resale_listing(
            f.resale_listing_payload(ticket["id"], 99999, ticket["version"]),
            make_patron_headers(venue["ben"]["id"]),
        ),
        ApiErrorId.PRICE_CAP_EXCEEDED,
        422,
    )

    _, meta = validate_paginated(
        api.list_resale_listings(SECURITY_INVESTIGATOR, params={"ticket_id": ticket["id"]})
    )
    assert meta["total_count"] == 0

    after = fx.read_ticket(api, ticket["id"])
    assert after["lifecycle_status"] == LifecycleStatus.ISSUED
    assert after["version"] == ticket["version"]

    # The same seat listed at its 14500-cent cap is accepted, so the cap really is 14500.
    listing = fx.create_listing(api, ticket["id"], venue["ben"]["id"], 14500)
    assert listing["cap_price_cents"] == 14500


def _ticket_at_its_transfer_limit(api):
    """Ben holds a once-transferred seat and a fresh one; Cyd is unverified."""
    venue = fx.on_sale_venue(api, transfer_limit_per_ticket=1)
    event_id = venue["event"]["id"]
    ada = fx.register_patron(api)
    ben = fx.register_patron(
        api, email="ben@example.com", display_name="Ben Hall", document_reference="DL-BEN-1"
    )
    cyd = fx.register_patron(
        api, email="cyd@example.com", display_name="Cyd Marsh", verify=False
    )
    handed_over = fx.issue_ticket(api, event_id, venue["zone"]["id"], ada["id"])
    ben_own = fx.issue_ticket(api, event_id, venue["zone"]["id"], ben["id"])

    offer = validate_success(
        api.create_transfer_request(
            f.transfer_request_payload(handed_over["id"], ben["id"]),
            make_patron_headers(ada["id"]),
        ),
        201,
    )
    accepted = validate_success(
        api.accept_transfer_request(offer["id"], {}, make_patron_headers(ben["id"]))
    )

    venue.update(
        {
            "ada": ada,
            "ben": ben,
            "cyd": cyd,
            "handed_over": handed_over,
            "ben_own": ben_own,
            "offer": offer,
            "accepted": accepted,
        }
    )
    return venue


def test_the_transfer_limit_wins_over_the_recipient_verification_check(api):
    """A ticket at its limit offered to an unverified patron reports the limit.

    PRD: "30. Transfer limit: the ticket's `transfer_count` is strictly below the event's `transfer_limit_per_ticket` — `ERR_TRANSFER_LIMIT_EXCEEDED` (409), on transfer creation and transfer acceptance."

    Design: Difficulty/priority_pair_validation_conflict/transfer_limit_outranks_recipient_not_verified
    """
    venue = _ticket_at_its_transfer_limit(api)

    assert venue["accepted"]["status"] == TransferStatus.ACCEPTED
    moved = fx.read_ticket(api, venue["handed_over"]["id"])
    assert moved["transfer_count"] == 1
    assert moved["lifecycle_status"] == LifecycleStatus.TRANSFERRED
    assert moved["holder_patron_id"] == venue["ben"]["id"]

    validate_error(
        api.create_transfer_request(
            f.transfer_request_payload(venue["handed_over"]["id"], venue["cyd"]["id"]),
            make_patron_headers(venue["ben"]["id"]),
        ),
        ApiErrorId.TRANSFER_LIMIT_EXCEEDED,
        409,
    )

    _, meta = validate_paginated(
        api.list_transfer_requests(
            SECURITY_INVESTIGATOR, params={"ticket_id": venue["handed_over"]["id"]}
        )
    )
    # Only the accepted offer exists; the refused one was never written.
    assert meta["total_count"] == 1
    assert fx.read_ticket(api, venue["handed_over"]["id"])["transfer_count"] == 1


def test_the_recipient_verification_check_still_fires_below_the_transfer_limit(api):
    """A never-transferred seat reaches the identity rule and is refused by it.

    PRD: "32. Identity: a transfer recipient's `identity_verified` is true, and a resale buyer's `identity_verified` is true — `ERR_RECIPIENT_NOT_VERIFIED` (422), on transfer creation, transfer acceptance and resale purchase."

    Design: Difficulty/priority_pair_validation_conflict/transfer_limit_outranks_recipient_not_verified
    """
    venue = _ticket_at_its_transfer_limit(api)
    assert fx.read_ticket(api, venue["ben_own"]["id"])["transfer_count"] == 0

    validate_error(
        api.create_transfer_request(
            f.transfer_request_payload(venue["ben_own"]["id"], venue["cyd"]["id"]),
            make_patron_headers(venue["ben"]["id"]),
        ),
        ApiErrorId.RECIPIENT_NOT_VERIFIED,
        422,
    )

    _, offers = validate_paginated(
        api.list_transfer_requests(
            SECURITY_INVESTIGATOR, params={"ticket_id": venue["ben_own"]["id"]}
        )
    )
    assert offers["total_count"] == 0
    assert fx.read_ticket(api, venue["ben_own"]["id"])["transfer_count"] == 0

    assert fx.read_patron(api, venue["cyd"]["id"])["identity_verified"] is False
    _, held = validate_paginated(
        api.list_tickets(BOX_OFFICE_AGENT, params={"holder_patron_id": venue["cyd"]["id"]})
    )
    assert held["total_count"] == 0
