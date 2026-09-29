"""Multi-branch money formulas: caps, settlement, forgone revenue and credits.

Each formula here has a pinned evaluation order, and each test contrasts the
declared order with the arithmetic a shortcut would produce.
"""

from test_helpers import (
    ApiErrorId,
    BOX_OFFICE_AGENT,
    CredentialRequestStatus,
    DeviceBindingStatus,
    DistributionType,
    EventStatus,
    FraudRiskBasis,
    IncidentStatus,
    LifecycleStatus,
    ListingStatus,
    PriceCapRegime,
    SECURITY_INVESTIGATOR,
    TICKETING_APPROVER,
    TicketType,
    ZonePosture,
    constants as C,
    factories as f,
    fixtures as fx,
    make_patron_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

STATUTORY_ANCHOR_AT = "2026-09-13T18:00:00Z"


def _venue_under_regime(api, price_cap_regime, **overrides):
    """An `ON_SALE` event under one resale regime, with Ada holding a 12000 seat."""
    venue = fx.on_sale_venue(api, price_cap_regime=price_cap_regime, **overrides)
    ada = fx.register_patron(api)
    ticket = fx.issue_ticket(
        api, venue["event"]["id"], venue["zone"]["id"], ada["id"], face_value_cents=12000
    )
    venue.update({"holder": ada, "ticket": ticket})
    return venue


def test_venue_policy_cap_clamps_the_percentage_markup_at_the_absolute_ceiling(api):
    """Thirty percent of 12000 is 3600, so the 2500-cent clamp decides the cap.

    PRD: "Otherwise a percentage is selected from the regime — 0.10, that is ten percent, under `STATUTORY`, and 0.30, that is thirty percent, under `VENUE_POLICY` — and the permitted markup is the ticket's `face_value_cents` multiplied by that percentage, rounded half up to a whole cent, then reduced to 2500 cents if it came out higher; the cap is the ticket's `face_value_cents` plus that markup."

    Design: Difficulty/combinatorial_formula/resale_price_cap_nested_min_across_regime_and_seller_verification
    """
    venue = _venue_under_regime(api, PriceCapRegime.VENUE_POLICY)
    ticket = venue["ticket"]

    listing = validate_success(
        api.create_resale_listing(
            f.resale_listing_payload(ticket["id"], 14500, ticket["version"]),
            make_patron_headers(venue["holder"]["id"]),
        ),
        201,
    )

    assert listing["cap_price_cents"] == 14500
    assert listing["ask_price_cents"] == 14500
    assert listing["status"] == ListingStatus.LISTED
    assert listing["superseded_listing_id"] is None
    assert fx.read_ticket(api, ticket["id"])["lifecycle_status"] == LifecycleStatus.LISTED


def test_statutory_regime_swaps_the_percentage_branch_and_yields_a_lower_cap(api):
    """The same 12000-cent face value caps at 13200 once the regime is statutory.

    Ten percent of 12000 is 1200, which is below the 2500-cent ceiling, so the
    percentage branch decides the cap instead of the clamp. PRD: "A listing is accepted when there is no cap or when `ask_price_cents` is less than or equal to the cap; equality is accepted, and only a strictly greater ask is refused with `ERR_PRICE_CAP_EXCEEDED`."

    Design: Difficulty/combinatorial_formula/resale_price_cap_nested_min_across_regime_and_seller_verification
    """
    venue = _venue_under_regime(
        api,
        PriceCapRegime.STATUTORY,
        name="Statutory Matinee",
        barcode_anchor_at=STATUTORY_ANCHOR_AT,
        doors_open_at=STATUTORY_ANCHOR_AT,
        event_start_at="2026-09-13T19:00:00Z",
        transfer_window_closes_at="2026-09-13T17:00:00Z",
    )
    ticket = venue["ticket"]

    listing = validate_success(
        api.create_resale_listing(
            f.resale_listing_payload(ticket["id"], 13200, ticket["version"]),
            make_patron_headers(venue["holder"]["id"]),
        ),
        201,
    )

    assert listing["cap_price_cents"] == 13200
    assert listing["ask_price_cents"] == 13200
    assert listing["status"] == ListingStatus.LISTED
    assert listing["superseded_listing_id"] is None
    assert fx.read_ticket(api, ticket["id"])["lifecycle_status"] == LifecycleStatus.LISTED


def _sold_at_the_cap(api):
    """Ada's 14500-cent listing bought by Ben, whose money must split four ways."""
    venue = fx.two_patron_venue(api)
    fx.bind_device(api, venue["ticket"]["id"], venue["holder"]["id"], "DEV-ADA")
    listing = fx.create_listing(api, venue["ticket"]["id"], venue["holder"]["id"], 14500)
    validate_success(
        api.purchase_resale_listing(
            listing["id"], {}, make_patron_headers(venue["other"]["id"])
        )
    )
    venue["listing"] = validate_success(
        api.get_resale_listing(listing["id"], SECURITY_INVESTIGATOR)
    )
    return venue


def test_each_settlement_component_is_rounded_before_the_deductions_are_summed(api):
    """A 14500-cent sale deducts 2010, not the 2009 a single rounding would give.

    PRD: "Settlement is split at purchase from the listing's `ask_price_cents` as it stands at that moment, and **each component is rounded independently before anything is added**."
    PRD: "`seller_payout_cents` is the sale price minus the sum of those three rounded components."

    Design: Difficulty/combinatorial_formula/resale_settlement_split_round_per_component_before_sum
    """
    listing = _sold_at_the_cap(api)["listing"]

    assert listing["platform_fee_cents"] == 1051
    assert listing["venue_royalty_cents"] == 508
    assert listing["processing_fee_cents"] == 451
    assert listing["seller_payout_cents"] == 12490

    deductions = (
        listing["platform_fee_cents"]
        + listing["venue_royalty_cents"]
        + listing["processing_fee_cents"]
    )
    assert deductions == 2010
    # Rounding the summed 13.65 percent rate once and adding the flat leg gives 2009.
    assert listing["seller_payout_cents"] != 12491


def test_only_the_venue_royalty_of_a_completed_resale_reaches_the_settlement_pool(api):
    """The seller banks 12490 and the pool gains only the 508-cent royalty.

    PRD: "The seller's `payout_balance_cents` then rises by `seller_payout_cents` and the event's `settlement_pool_cents` rises by `venue_royalty_cents`; the platform and processing components leave the system."

    Design: Difficulty/combinatorial_formula/resale_settlement_split_round_per_component_before_sum
    """
    venue = _sold_at_the_cap(api)

    assert fx.read_patron(api, venue["holder"]["id"])["payout_balance_cents"] == 12490
    # 12000 collected at issuance plus the royalty, and nothing else.
    assert fx.read_event(api, venue["event"]["id"])["settlement_pool_cents"] == 12508

    assert venue["listing"]["status"] == ListingStatus.SOLD
    assert venue["listing"]["buyer_patron_id"] == venue["other"]["id"]

    ticket = fx.read_ticket(api, venue["ticket"]["id"])
    assert ticket["lifecycle_status"] == LifecycleStatus.RESOLD
    assert ticket["holder_patron_id"] == venue["other"]["id"]
    assert ticket["device_binding_status"] == DeviceBindingStatus.RELEASED
    assert ticket["bound_device_fingerprint"] is None


def _approved_comp_batch_of_four(api):
    """Four comps poured into a zone whose reference value rounds to a half cent."""
    venue = fx.on_sale_venue(api)
    zone = venue["zone"]
    recipient = fx.register_patron(api)
    request = fx.create_credential_draft(
        api,
        venue["event"]["id"],
        zone["id"],
        recipient["id"],
        distribution_type=DistributionType.COMP,
        quantity=4,
        valid_from="2026-09-12T18:00:00Z",
        valid_until="2026-09-12T22:00:00Z",
        justification="Four artist guest comps for the Aurora Night support act",
    )
    fx.submit_credential_request(api, request["id"])
    approved = validate_success(
        api.approve_credential_request(
            request["id"],
            f.note_payload("Approved against the artist allocation"),
            TICKETING_APPROVER,
        )
    )
    venue.update({"recipient": recipient, "request": approved})
    return venue


def test_forgone_revenue_rounds_the_per_ticket_figure_before_multiplying_by_quantity(api):
    """8750 at a 0.85 discount is 1312.5 per ticket, so four comps forgo 5252.

    PRD: "Rounding is per ticket and only then multiplied — computing the whole-batch product first and rounding once is wrong."

    Design: Difficulty/combinatorial_formula/credential_forgone_revenue_per_ticket_rounding_before_batch_multiply
    """
    venue = _approved_comp_batch_of_four(api)
    request = venue["request"]

    assert request["forgone_revenue_cents"] == 5252
    # Multiplying 1312.5 by four and rounding once would have booked 5250.
    assert request["forgone_revenue_cents"] != 5250
    assert request["status"] == CredentialRequestStatus.APPROVED
    assert request["approved_by_user_id"] == C.APPROVER_USER_ID
    assert request["issued_ticket_count"] == 4

    rows, meta = validate_paginated(
        api.list_tickets(BOX_OFFICE_AGENT, params={"credential_request_id": request["id"]})
    )
    assert meta["total_count"] == 4
    for ticket in rows:
        assert ticket["ticket_type"] == TicketType.COMP
        assert ticket["face_value_cents"] == 0
        assert ticket["holder_patron_id"] == venue["recipient"]["id"]
        assert ticket["lifecycle_status"] == LifecycleStatus.ISSUED
        assert ticket["access_zone_id"] == venue["zone"]["id"]
        assert ticket["device_binding_status"] == DeviceBindingStatus.UNBOUND


def test_the_approval_cascade_accumulates_the_booked_forgone_revenue_on_the_zone(api):
    """The zone's ledger takes the same 5252 the request booked, and no money moves.

    PRD: "Third, per issued ticket the zone's `issued_entitlement_count` and the event's `entitlements_outstanding` each rise by one, and the zone's `comp_forgone_cents` accumulates the booked forgone revenue."

    Design: Difficulty/combinatorial_formula/credential_forgone_revenue_per_ticket_rounding_before_batch_multiply
    """
    venue = _approved_comp_batch_of_four(api)

    zone = fx.read_zone(api, venue["zone"]["id"])
    assert zone["comp_forgone_cents"] == 5252
    assert zone["issued_entitlement_count"] == 4
    # Four of two hundred places is far below the advisory band.
    assert zone["posture"] == ZonePosture.OPEN

    event = fx.read_event(api, venue["event"]["id"])
    assert event["entitlements_outstanding"] == 4
    assert event["settlement_pool_cents"] == 0


def _two_mismatch_incidents_under_review(api):
    """Ada is denied twice on two seats while Ben's paid seat funds the pool."""
    venue = fx.on_sale_venue(api)
    event_id = venue["event"]["id"]
    ada = fx.register_patron(api)
    ben = fx.register_patron(
        api, email="ben@example.com", display_name="Ben Hall", document_reference="DL-BEN-1"
    )
    ticket_low = fx.issue_ticket(
        api, event_id, venue["zone"]["id"], ada["id"], face_value_cents=5000
    )
    ticket_mid = fx.issue_ticket(
        api, event_id, venue["zone"]["id"], ada["id"], face_value_cents=12000
    )
    fx.issue_ticket(api, event_id, venue["zone"]["id"], ben["id"], face_value_cents=20000)
    fx.bind_device(api, ticket_low["id"], ada["id"], "DEV-ADA-LOW")
    fx.bind_device(api, ticket_mid["id"], ada["id"], "DEV-ADA-MID")
    fx.advance_event(api, event_id, EventStatus.DOORS_OPEN)
    fx.set_clock(api, C.T_18_10_00)
    session = fx.open_scan_session(api, venue["gate"]["id"])

    for ticket, device, key in (
        (ticket_low, "DEV-IMPOSTOR-1", "S1-ONLINE-001"),
        (ticket_mid, "DEV-IMPOSTOR-2", "S1-ONLINE-002"),
    ):
        validate_error(
            fx.denied_scan_response(
                api, session["id"], fx.current_barcode(api, ticket["id"]), device, key
            ),
            ApiErrorId.DEVICE_MISMATCH,
            422,
        )

    incident_low = fx.list_incidents(api, ticket_id=ticket_low["id"])[0]
    incident_mid = fx.list_incidents(api, ticket_id=ticket_mid["id"])[0]
    for incident in (incident_low, incident_mid):
        validate_success(api.start_incident_review(incident["id"], {}, SECURITY_INVESTIGATOR))

    venue.update(
        {
            "ada": ada,
            "ben": ben,
            "ticket_low": ticket_low,
            "ticket_mid": ticket_mid,
            "incident_low": incident_low,
            "incident_mid": incident_mid,
        }
    )
    return venue


def _remediate(api, incident_id, note):
    return validate_success(
        api.remediate_incident(
            incident_id, f.resolution_payload(note), SECURITY_INVESTIGATOR
        )
    )


def test_goodwill_tier_is_selected_from_the_base_credit_before_goodwill_is_added(api):
    """A 5000-cent base sits on the inclusive ten-percent tier and pays 4500.

    PRD: "Step two: the goodwill percentage is selected **from the base credit alone** — 0.10, that is ten percent, when the base is at most 5000 cents; 0.15, that is fifteen percent, when the base is at most 15000 cents; and 0.20, that is twenty percent, otherwise, with both boundaries inclusive."

    Design: Difficulty/combinatorial_formula/remediation_credit_tier_keyed_on_base_before_goodwill
    """
    venue = _two_mismatch_incidents_under_review(api)
    # Both strikes are already booked, so both credits share the same penalty.
    assert fx.read_patron(api, venue["ada"]["id"])["strike_count"] == 2

    low = _remediate(api, venue["incident_low"]["id"], "Reader firmware fault on lane 1")
    mid = _remediate(api, venue["incident_mid"]["id"], "Reader firmware fault on lane 2")

    assert low["remediation_credit_cents"] == 4500
    # Keying the tier on base plus goodwill would have selected 0.15 and paid 4750.
    assert low["remediation_credit_cents"] != 4750
    assert mid["remediation_credit_cents"] == 12800
    assert low["status"] == IncidentStatus.REMEDIATED
    assert mid["status"] == IncidentStatus.REMEDIATED


def test_the_strike_penalty_is_read_after_this_incidents_own_strike_and_shared_by_both(api):
    """Two strikes cost 1000 cents on each credit, and the pool funds both.

    PRD: "Step four: the strike penalty is 500 cents for each strike on the patron's `strike_count`, reduced to 2000 cents if that product came out higher — and `strike_count` is read *after* the strike this very incident booked at creation, so the incident under remediation counts against its own credit."

    Design: Difficulty/combinatorial_formula/remediation_credit_tier_keyed_on_base_before_goodwill
    """
    venue = _two_mismatch_incidents_under_review(api)
    assert fx.read_event(api, venue["event"]["id"])["settlement_pool_cents"] == 37000

    _remediate(api, venue["incident_low"]["id"], "Reader firmware fault on lane 1")
    _remediate(api, venue["incident_mid"]["id"], "Reader firmware fault on lane 2")

    ada = fx.read_patron(api, venue["ada"]["id"])
    assert ada["remediation_credit_cents"] == 17300
    # Remediation grants credit but never withdraws a strike.
    assert ada["strike_count"] == 2
    assert ada["fraud_risk_score"] == 46
    assert ada["fraud_risk_basis"] == FraudRiskBasis.ADJUDICATED

    assert fx.read_event(api, venue["event"]["id"])["settlement_pool_cents"] == 19700
