"""Guards whose scope, ordering and case-folding decide whether a call survives.

Uniqueness measured per event and per session rather than globally, an email
compared without regard to case, an approver who is also the requester, and an
adjudication ladder that answers with its first failing rung.
"""

from test_helpers import (
    AdmissionStatus,
    ApiErrorId,
    BOX_OFFICE_AGENT,
    CredentialRequestStatus,
    DeviceBindingStatus,
    DistributionType,
    EntitlementLevel,
    EventStatus,
    FraudRiskBasis,
    IncidentCategory,
    IncidentStatus,
    LifecycleStatus,
    ListingStatus,
    Marketplace,
    ScanResult,
    TICKETING_APPROVER,
    TICKETING_APPROVER_AS_AGENT,
    TicketType,
    VENUE_ADMIN,
    constants as C,
    factories as f,
    fixtures as fx,
    make_patron_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_the_same_zone_and_gate_codes_collide_inside_one_event_and_not_across_two(api):
    """GA1 twice in one event is a conflict; GA1 in the next event is a clean create.

    PRD: "38. `zone_code` and `gate_code` are unique within the event — `ERR_DUPLICATE_CODE` (409), on access-zone and gate creation."
    PRD: "A duplicate `zone_code` within the same event is rejected with `ERR_DUPLICATE_CODE`."
    PRD: "It carries a `gate_code` unique within the event, an `access_zone_id` naming the zone it admits into, a rated `throughput_per_minute` of at least 1 for one open lane, and an optional `lanes_open` count of at least 1 that defaults to 1."

    Design: Corner/validations/zone_and_gate_codes_are_unique_per_event_but_reusable_across_events
    """
    first = fx.create_event(api)
    second = fx.create_event(
        api,
        name="Boreal Matinee",
        barcode_anchor_at="2026-09-13T18:00:00Z",
        doors_open_at="2026-09-13T18:00:00Z",
        event_start_at="2026-09-13T19:00:00Z",
        transfer_window_closes_at="2026-09-13T17:00:00Z",
    )
    zone = fx.create_zone(api, first["id"])
    gate = fx.create_gate(api, first["id"], zone["id"])
    assert zone["zone_code"] == "GA1"
    assert gate["gate_code"] == "G1"

    # Everything else about the second zone differs; only the code is taken.
    validate_error(
        api.create_access_zone(
            first["id"],
            f.access_zone_payload(
                zone_code="GA1",
                required_entitlement_level=EntitlementLevel.PREMIUM,
                fire_code_capacity=40,
                face_value_reference_cents=22000,
            ),
            VENUE_ADMIN,
        ),
        ApiErrorId.DUPLICATE_CODE,
        409,
    )
    validate_error(
        api.create_gate(
            first["id"],
            f.gate_payload(zone["id"], gate_code="G1", throughput_per_minute=15),
            VENUE_ADMIN,
        ),
        ApiErrorId.DUPLICATE_CODE,
        409,
    )

    # Uniqueness is scoped to the event, so the neighbouring season reuses the code.
    twin = validate_success(
        api.create_access_zone(second["id"], f.access_zone_payload(), VENUE_ADMIN), 201
    )
    assert twin["zone_code"] == "GA1"
    assert twin["id"] != zone["id"]

    _, zone_meta = validate_paginated(
        api.list_access_zones(VENUE_ADMIN, params={"event_id": first["id"]})
    )
    assert zone_meta["total_count"] == 1
    _, gate_meta = validate_paginated(
        api.list_gates(VENUE_ADMIN, params={"event_id": first["id"]})
    )
    assert gate_meta["total_count"] == 1
    # The refused duplicate did not overwrite the original's lane count.
    assert fx.read_gate(api, gate["id"])["lanes_open"] == 2


def test_an_address_differing_only_in_letter_case_is_the_same_patron(api):
    """ADA@Example.COM collides with ada@example.com; a different address does not.

    PRD: "39. A patron's `email` is globally unique, compared case-insensitively — `ERR_DUPLICATE_EMAIL` (409), on patron registration."
    PRD: "The email is globally unique compared case-insensitively, so a second registration differing only in letter case is rejected with `ERR_DUPLICATE_EMAIL`."
    PRD: "A new patron starts with `identity_verified` false, `device_rebind_count`, `strike_count`, `fraud_risk_score`, `remediation_credit_cents` and `payout_balance_cents` all at zero, and a `fraud_risk_basis` of `PROVISIONAL`."

    Design: Corner/validations/patron_email_uniqueness_is_compared_case_insensitively
    """
    ada = validate_success(
        api.create_patron(f.patron_payload(), BOX_OFFICE_AGENT), 201
    )
    assert ada["email"] == "ada@example.com"
    assert ada["identity_verified"] is False
    assert ada["fraud_risk_basis"] == FraudRiskBasis.PROVISIONAL
    assert ada["strike_count"] == 0
    assert ada["fraud_risk_score"] == 0

    validate_error(
        api.create_patron(
            f.patron_payload(email="ADA@Example.COM", display_name="Ada L."),
            BOX_OFFICE_AGENT,
        ),
        ApiErrorId.DUPLICATE_EMAIL,
        409,
    )

    bob = validate_success(
        api.create_patron(
            f.patron_payload(email="bob@example.com", display_name="Bob Bell"),
            BOX_OFFICE_AGENT,
        ),
        201,
    )
    assert bob["id"] != ada["id"]

    _, meta = validate_paginated(api.list_patrons(BOX_OFFICE_AGENT))
    assert meta["total_count"] == 2
    # The rejected registration did not rename the person it collided with.
    assert fx.read_patron(api, ada["id"])["display_name"] == "Ada Lovelace"


def test_the_agent_who_submitted_the_request_may_not_approve_it_wearing_another_hat(api):
    """The check compares identifiers, so the approver role does not launder the identity.

    PRD: "18. Segregation of duties: the deciding `X-User-ID` differs from the request's `requested_by_user_id` — `ERR_SEGREGATION_OF_DUTIES` (403), on credential-request approval and rejection."
    PRD: "An approver who tries to decide their own submission is refused with `ERR_SEGREGATION_OF_DUTIES`, whichever of the two decisions they attempt."
    PRD: "Submission moves the request to `SUBMITTED` and stamps `requested_by_user_id` with the submitting agent's `X-User-ID`."
    PRD: "The per-ticket forgone amount is the zone's `face_value_reference_cents` multiplied by one minus the zone's `comp_discount_pct`, rounded half up to a whole cent; the request's `forgone_revenue_cents` is that per-ticket figure multiplied by the request's `quantity`."

    Design: Corner/validations/segregation_of_duties_blocks_the_requester_from_approving_the_request
    """
    venue = fx.on_sale_venue(api)
    ada = fx.register_patron(api)
    draft = fx.create_credential_draft(
        api,
        venue["event"]["id"],
        venue["zone"]["id"],
        ada["id"],
        distribution_type=DistributionType.COMP,
        quantity=1,
        valid_from="2026-09-12T18:00:00Z",
        valid_until="2026-09-12T22:00:00Z",
        justification="Artist guest",
    )
    submitted = fx.submit_credential_request(api, draft["id"])
    assert submitted["status"] == CredentialRequestStatus.SUBMITTED
    assert submitted["requested_by_user_id"] == C.AGENT_USER_ID

    # Same human, approver's role, and still the identifier that raised the request.
    validate_error(
        api.approve_credential_request(
            draft["id"], f.note_payload("Self-approval attempt"), TICKETING_APPROVER_AS_AGENT
        ),
        ApiErrorId.SEGREGATION_OF_DUTIES,
        403,
    )
    still_open = validate_success(api.get_credential_request(draft["id"], TICKETING_APPROVER))
    assert still_open["status"] == CredentialRequestStatus.SUBMITTED
    assert still_open["issued_ticket_count"] == 0

    approved = validate_success(
        api.approve_credential_request(
            draft["id"], f.note_payload("Independent approval"), TICKETING_APPROVER
        )
    )
    assert approved["status"] == CredentialRequestStatus.APPROVED
    assert approved["approved_by_user_id"] == C.APPROVER_USER_ID
    assert approved["issued_ticket_count"] == 1
    # 8750 at fifteen percent is 1312.5, which rounds half up to 1313.
    assert approved["forgone_revenue_cents"] == 1313

    passes, meta = validate_paginated(
        api.list_tickets(BOX_OFFICE_AGENT, params={"credential_request_id": draft["id"]})
    )
    assert meta["total_count"] == 1
    assert passes[0]["ticket_type"] == TicketType.COMP
    assert passes[0]["face_value_cents"] == 0
    assert passes[0]["device_binding_status"] == DeviceBindingStatus.UNBOUND
    # A zero-face entitlement collects nothing.
    assert fx.read_event(api, venue["event"]["id"])["settlement_pool_cents"] == 0


def _two_bound_tickets_and_two_open_sessions(api):
    """Ada and Bob are outside, each with a bound seat, facing G1 and G2 at 18:10:00."""
    event = fx.create_event(api)
    zone = fx.create_zone(api, event["id"], fire_code_capacity=150)
    first = fx.create_gate(api, event["id"], zone["id"], gate_code="G1", lanes_open=2)
    second = fx.create_gate(api, event["id"], zone["id"], gate_code="G2", lanes_open=1)
    fx.advance_event(api, event["id"], EventStatus.ON_SALE)

    ada = fx.register_patron(api)
    bob = fx.register_patron(
        api, email="bob@example.com", display_name="Bob Bell", document_reference="DL-BOB-1"
    )
    ticket_ada = fx.issue_ticket(api, event["id"], zone["id"], ada["id"])
    ticket_bob = fx.issue_ticket(api, event["id"], zone["id"], bob["id"])
    fx.bind_device(api, ticket_ada["id"], ada["id"], "DEV-ADA")
    fx.bind_device(api, ticket_bob["id"], bob["id"], "DEV-BOB")
    fx.advance_event(api, event["id"], EventStatus.DOORS_OPEN)

    fx.set_clock(api, C.T_18_10_00)
    return {
        "event": event,
        "zone": zone,
        "ada": ada,
        "bob": bob,
        "ticket_ada": ticket_ada,
        "ticket_bob": ticket_bob,
        "s1": fx.open_scan_session(api, first["id"], operator_device_id="SCN-1"),
        "s2": fx.open_scan_session(api, second["id"], operator_device_id="SCN-2"),
    }


def test_a_dedupe_key_is_spent_only_inside_its_own_session(api):
    """K1 is refused a second time on S1 and accepted on S2.

    PRD: "19. `dedupe_key` is unused within the scan session — `ERR_DUPLICATE_DEDUPE_KEY` (409), on live scanning."
    PRD: "A live scan is submitted with the `presented_barcode`, the `device_fingerprint` of the device that rendered it, a `direction` of `IN` or `OUT`, a `dedupe_key` that must be unused within the session, and an optional `scanned_at` client instant that defaults to the logical clock."
    PRD: "Failures at rules 1 through 19 of §2.12 are **hard request errors**: nothing is persisted — no scan event, no incident, no counter movement, no strike."

    Design: Corner/validations/dedupe_key_uniqueness_is_scoped_to_one_scan_session
    """
    venue = _two_bound_tickets_and_two_open_sessions(api)

    admitted = fx.admit_ticket(api, venue["s1"]["id"], venue["ticket_ada"]["id"], "DEV-ADA", "K1")
    assert admitted["result"] == ScanResult.ADMITTED

    validate_error(
        fx.denied_scan_response(
            api,
            venue["s1"]["id"],
            fx.current_barcode(api, venue["ticket_bob"]["id"]),
            "DEV-BOB",
            "K1",
        ),
        ApiErrorId.DUPLICATE_DEDUPE_KEY,
        409,
    )

    second = fx.admit_ticket(api, venue["s1"]["id"], venue["ticket_bob"]["id"], "DEV-BOB", "K2")
    assert second["result"] == ScanResult.ADMITTED
    left = fx.exit_ticket(api, venue["s2"]["id"], venue["ticket_ada"]["id"], "DEV-ADA", "K1")
    # The very same key is free in the second session.
    assert left["result"] == ScanResult.EXIT_RECORDED

    assert len(fx.list_scan_events(api, scan_session_id=venue["s1"]["id"])) == 2
    assert len(fx.list_scan_events(api, scan_session_id=venue["s2"]["id"])) == 1
    # A rejection above the adjudication band leaves no evidence behind.
    assert len(fx.list_incidents(api)) == 0

    occupancy = fx.read_occupancy(api, venue["event"]["id"])
    assert occupancy["live_occupancy"] == 1
    assert occupancy["peak_live_occupancy"] == 2
    assert fx.read_ticket(api, venue["ticket_ada"]["id"])["admission_status"] == (
        AdmissionStatus.EXITED
    )
    assert fx.read_ticket(api, venue["ticket_bob"]["id"])["admission_status"] == (
        AdmissionStatus.INSIDE
    )


def test_an_unverified_channel_and_a_giveaway_are_both_refused_before_a_clean_listing(api):
    """Two refusals on two rules, one strike booked, and then a 14500-cent ceiling.

    PRD: "A `marketplace` of `UNVERIFIED` is refused with `ERR_MARKETPLACE_NOT_VERIFIED`, no listing row is created and the ticket's `lifecycle_status` is unchanged — but a denied-entry incident *is* opened with `category` `UNAUTHORIZED_RESALE`, its `ticket_id` set to the offered ticket and its `patron_id` set to the acting seller, a strike is booked against that seller's `strike_count`, and the seller's `fraud_risk_score` is recomputed under the provisional reading."
    PRD: "33. `COMP` and `CREDENTIAL` tickets may be neither transferred nor listed — `ERR_TICKET_NOT_TRANSFERABLE` (422), on transfer creation and resale listing creation."
    PRD: "Otherwise a percentage is selected from the regime — 0.10, that is ten percent, under `STATUTORY`, and 0.30, that is thirty percent, under `VENUE_POLICY` — and the permitted markup is the ticket's `face_value_cents` multiplied by that percentage, rounded half up to a whole cent, then reduced to 2500 cents if it came out higher; the cap is the ticket's `face_value_cents` plus that markup."

    Design: Corner/validations/unverified_channel_and_giveaway_tickets_cannot_be_listed_while_a_clean_listing_passes
    """
    venue = fx.on_sale_venue(api)
    ada = fx.register_patron(api)
    seller = make_patron_headers(ada["id"])
    paid = fx.issue_ticket(
        api, venue["event"]["id"], venue["zone"]["id"], ada["id"], face_value_cents=12000
    )
    comp = fx.issue_ticket(
        api,
        venue["event"]["id"],
        venue["zone"]["id"],
        ada["id"],
        ticket_type=TicketType.COMP,
        face_value_cents=0,
    )

    validate_error(
        api.create_resale_listing(
            f.resale_listing_payload(
                paid["id"], 12000, paid["version"], marketplace=Marketplace.UNVERIFIED
            ),
            seller,
        ),
        ApiErrorId.MARKETPLACE_NOT_VERIFIED,
        422,
    )
    assert len(fx.list_listings(api)) == 0

    punished = fx.read_patron(api, ada["id"])
    assert punished["strike_count"] == 1
    # One unauthorized-resale incident weighs 30, still short of the blocking threshold.
    assert punished["fraud_risk_score"] == 30

    incidents = fx.list_incidents(api, category=IncidentCategory.UNAUTHORIZED_RESALE)
    assert len(incidents) == 1
    assert incidents[0]["ticket_id"] == paid["id"]
    assert incidents[0]["patron_id"] == ada["id"]
    assert incidents[0]["status"] == IncidentStatus.OPEN

    # The give-away is barred by type, one rung above the channel and cap checks.
    validate_error(
        api.create_resale_listing(
            f.resale_listing_payload(comp["id"], 0, comp["version"]), seller
        ),
        ApiErrorId.TICKET_NOT_TRANSFERABLE,
        422,
    )

    listing = validate_success(
        api.create_resale_listing(
            f.resale_listing_payload(
                paid["id"], 12000, paid["version"], marketplace=Marketplace.VERIFIED_PARTNER
            ),
            seller,
        ),
        201,
    )
    assert listing["status"] == ListingStatus.LISTED
    # Thirty percent of 12000 is 3600, clamped to the 2500-cent absolute markup.
    assert listing["cap_price_cents"] == 14500

    listed = fx.read_ticket(api, paid["id"])
    assert listed["lifecycle_status"] == LifecycleStatus.LISTED
    assert listed["version"] == paid["version"] + 1
    untouched = fx.read_ticket(api, comp["id"])
    assert untouched["lifecycle_status"] == LifecycleStatus.ISSUED
    assert untouched["version"] == comp["version"]


def test_the_seller_cannot_buy_their_own_listing_but_a_stranger_can(api):
    """Wash trading is refused at 422; Bob's purchase then splits 12000 four ways.

    PRD: "41. The purchasing patron is not the listing's seller — `ERR_SELF_PURCHASE` (422), on resale purchase."
    PRD: "`processing_fee_cents` is the sale price multiplied by 0.0290, that is 2.90 percent, rounded half up, plus a flat 30 cents."
    PRD: "`seller_payout_cents` is the sale price minus the sum of those three rounded components."
    PRD: "The seller's `payout_balance_cents` then rises by `seller_payout_cents` and the event's `settlement_pool_cents` rises by `venue_royalty_cents`; the platform and processing components leave the system."

    Design: Corner/validations/self_purchase_is_rejected_then_a_third_party_purchase_settles
    """
    venue = fx.ticketed_venue(api)
    ada = venue["holder"]
    bob = fx.register_patron(
        api, email="bob@example.com", display_name="Bob Bell", document_reference="DL-BOB-1"
    )
    fx.bind_device(api, venue["ticket"]["id"], ada["id"], "DEV-ADA")
    listing = fx.create_listing(
        api,
        venue["ticket"]["id"],
        ada["id"],
        12000,
        marketplace=Marketplace.VERIFIED_PARTNER,
    )

    validate_error(
        api.purchase_resale_listing(listing["id"], {}, make_patron_headers(ada["id"])),
        ApiErrorId.SELF_PURCHASE,
        422,
    )
    assert validate_success(api.get_resale_listing(listing["id"], VENUE_ADMIN))["status"] == (
        ListingStatus.LISTED
    )

    sold = validate_success(
        api.purchase_resale_listing(listing["id"], {}, make_patron_headers(bob["id"]))
    )
    assert sold["status"] == ListingStatus.SOLD
    assert sold["buyer_patron_id"] == bob["id"]
    assert sold["platform_fee_cents"] == 870
    assert sold["venue_royalty_cents"] == 420
    # 348 on the percentage plus the flat thirty cents.
    assert sold["processing_fee_cents"] == 378
    assert sold["seller_payout_cents"] == 10332

    assert fx.read_patron(api, ada["id"])["payout_balance_cents"] == 10332
    assert fx.read_patron(api, bob["id"])["payout_balance_cents"] == 0
    # The 12000 booked at issuance plus the venue royalty alone.
    assert fx.read_event(api, venue["event"]["id"])["settlement_pool_cents"] == 12420

    ticket = fx.read_ticket(api, venue["ticket"]["id"])
    assert ticket["lifecycle_status"] == LifecycleStatus.RESOLD
    assert ticket["holder_patron_id"] == bob["id"]
    assert ticket["device_binding_status"] == DeviceBindingStatus.RELEASED


def test_an_unknown_seed_answers_before_the_epoch_and_the_epoch_before_the_device(api):
    """One presentation fails three clauses at once and reports the first of them.

    PRD: "If no ticket's `barcode_seed` equals the seed part, the scan is adjudicated `DENIED_COUNTERFEIT` and reported as `ERR_COUNTERFEIT_BARCODE`."
    PRD: "Otherwise the server computes the epoch index of the logical clock; if the presented epoch part is greater than that index, or is smaller than that index minus one, the scan is adjudicated `DENIED_STALE_BARCODE` and reported as `ERR_BARCODE_EPOCH_INVALID`."
    PRD: "One special case breaks the chain: when the seed part resolves to no ticket at all, there is no holder to punish, so the persisted scan event and the `COUNTERFEIT` incident both carry a null `ticket_id`, the incident carries a null `patron_id`, no strike is booked and no risk score moves — the incident still opens so the denial remains auditable."
    PRD: "`DENIED_COUNTERFEIT` maps to incident `category` `COUNTERFEIT`; `DENIED_STALE_BARCODE` also maps to `COUNTERFEIT`, because an out-of-window epoch is a replayed screenshot; `DENIED_DEVICE_MISMATCH` maps to `DEVICE_MISMATCH`; `DENIED_DUPLICATE` maps to `DUPLICATE`; and `DENIED_ZONE` maps to `ZONE_VIOLATION`."

    Design: Corner/validations/counterfeit_seed_is_adjudicated_before_the_epoch_and_device_checks
    """
    venue = fx.scan_ready_venue(api, device_fingerprint="DEV-ADA")
    ada = venue["holder"]
    ticket = venue["ticket"]
    session = venue["session"]

    # An unresolvable seed and a wrong fingerprint: the seed rung answers.
    validate_error(
        fx.denied_scan_response(api, session["id"], "NOSUCHSEED-20", "DEV-WRONG", "K1"),
        ApiErrorId.COUNTERFEIT_BARCODE,
        422,
    )
    clean = fx.read_patron(api, ada["id"])
    # Nobody was identified, so nobody could be punished.
    assert clean["strike_count"] == 0
    assert clean["fraud_risk_score"] == 0

    # A real seed at a future epoch, same wrong fingerprint: the epoch rung answers.
    validate_error(
        fx.denied_scan_response(
            api, session["id"], fx.barcode_at_epoch(api, ticket["id"], 99), "DEV-WRONG", "K2"
        ),
        ApiErrorId.BARCODE_EPOCH_INVALID,
        422,
    )
    struck = fx.read_patron(api, ada["id"])
    assert struck["strike_count"] == 1
    # A replayed screenshot is counterfeit, weighing 50, with no device churn to add.
    assert struck["fraud_risk_score"] == 50
    assert struck["device_rebind_count"] == 0

    admitted = fx.live_scan(
        api, session["id"], fx.current_barcode(api, ticket["id"]), "DEV-ADA", "K3"
    )
    assert admitted["result"] == ScanResult.ADMITTED

    results = [row["result"] for row in fx.list_scan_events(api, scan_session_id=session["id"])]
    assert len(results) == 3
    assert sorted(results) == sorted(
        [ScanResult.DENIED_COUNTERFEIT, ScanResult.DENIED_STALE_BARCODE, ScanResult.ADMITTED]
    )

    counterfeits = fx.list_incidents(api, category=IncidentCategory.COUNTERFEIT)
    assert len(counterfeits) == 2
    assert {row["ticket_id"] for row in counterfeits} == {None, ticket["id"]}
    assert {row["patron_id"] for row in counterfeits} == {None, ada["id"]}

    assert fx.read_ticket(api, ticket["id"])["admission_status"] == AdmissionStatus.INSIDE
