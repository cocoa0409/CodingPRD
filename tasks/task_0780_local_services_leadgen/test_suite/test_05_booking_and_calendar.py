"""Booking: the largest cascade, verification and referential gates, the
calendar overlap/buffer rules, and slot compensation on cancel."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS, make_customer_headers, make_pro_headers,
    create_category, create_customer, create_verified_pro, create_request,
    distribute_once, lead_for, create_slot, reset_clock,
    create_quote_payload, create_booking_payload, create_slot_payload,
    setup_quoted_lead, setup_confirmed_booking,
)

ADMIN = TEST_USERS["admin_headers"]


# --------------------------------------------------------------------------
# Booking cascade (depth-3)
# --------------------------------------------------------------------------
def _booking_cascade_scenario(api):
    """Two eligible pros, request distributed twice (each pro holds one lead).
    Pro-1's lead is contacted + quoted and its quote is booked onto pro-1's slot."""
    reset_clock(api)
    cat = create_category(api, max_leads_per_request=2, min_rating_to_receive_leads=0.0)
    cust = create_customer(api)
    pg1 = create_verified_pro(api, wallet=20000, category_ids=[cat["id"]], zip_codes=["94016"])
    pg2 = create_verified_pro(api, wallet=20000, category_ids=[cat["id"]], zip_codes=["94016"])
    slot = create_slot(pg1["id"], "2026-03-05T08:00:00Z", "2026-03-05T20:00:00Z", api=api)
    req = create_request(cust["id"], cat["id"], api=api)
    r2 = distribute_once(req["id"], req["version"], api=api)
    distribute_once(req["id"], r2["version"], api=api)
    lead1 = lead_for(req["id"], pg1["id"], api=api)
    lead2 = lead_for(req["id"], pg2["id"], api=api)
    get_success_data(api.contact_lead(lead1["id"], make_pro_headers(pg1["id"])))
    quote1 = get_success_data(
        api.create_quote(create_quote_payload(lead1["id"], amount_cents=10000),
                         make_pro_headers(pg1["id"]))
    )
    booking = get_success_data(
        api.create_booking(
            create_booking_payload(quote1["id"], slot["id"],
                                   "2026-03-05T10:00:00Z", "2026-03-05T11:00:00Z"),
            make_customer_headers(cust["id"]),
        )
    )
    return {"req": req, "slot": slot, "quote1": quote1,
            "lead1": lead1, "lead2": lead2, "booking": booking}


def test_booking_cascade_accepts_quote_and_converts_winning_lead(api):
    """PRD 3.5: "the accepted quote moves SENT -> ACCEPTED; the quote's lead
    moves contact_status QUOTED -> CONVERTED; every sibling lead of the same
    request still in an open contact stage (DISTRIBUTED, CONTACTED, or QUOTED) is
    moved to CLOSED; the service request moves to BOOKED; and the reserved slot
    moves OPEN -> BOOKED with its booking_id set to the new booking."

    Design: Difficulty/transitive_cascade/booking_cascade_quote_lead_sibling_request_slot_depth3
    """
    ctx = _booking_cascade_scenario(api)
    quote = get_success_data(api.get_quote(ctx["quote1"]["id"], ADMIN))
    lead1 = get_success_data(api.get_lead(ctx["lead1"]["id"], ADMIN))
    assert quote["status"] == "ACCEPTED"
    assert lead1["contact_status"] == "CONVERTED"


def test_booking_cascade_closes_sibling_and_books_request_and_slot(api):
    """PRD 3.5: "the accepted quote moves SENT -> ACCEPTED; the quote's lead
    moves contact_status QUOTED -> CONVERTED; every sibling lead of the same
    request still in an open contact stage (DISTRIBUTED, CONTACTED, or QUOTED) is
    moved to CLOSED; the service request moves to BOOKED; and the reserved slot
    moves OPEN -> BOOKED with its booking_id set to the new booking."

    Design: Difficulty/transitive_cascade/booking_cascade_quote_lead_sibling_request_slot_depth3
    """
    ctx = _booking_cascade_scenario(api)
    lead2 = get_success_data(api.get_lead(ctx["lead2"]["id"], ADMIN))
    req = get_success_data(api.get_service_request(ctx["req"]["id"], ADMIN))
    slot = get_success_data(api.get_availability_slot(ctx["slot"]["id"], ADMIN))
    assert lead2["contact_status"] == "CLOSED"
    assert req["status"] == "BOOKED"
    assert slot["status"] == "BOOKED"
    assert slot["booking_id"] == ctx["booking"]["id"]


# --------------------------------------------------------------------------
# Pro-verification gate on booking
# --------------------------------------------------------------------------
def test_booking_against_suspended_pro_rejected(api):
    """PRD 3.5: "The quote's pro must be `VERIFIED`, or the booking is rejected
    with `ERR_PRO_NOT_VERIFIED`."

    Design: Difficulty/cross_entity_state_dependency/booking_requires_pro_verified
    """
    ctx = setup_quoted_lead(api=api)
    pid = ctx["pro"]["id"]
    slot = create_slot(pid, "2026-03-05T08:00:00Z", "2026-03-05T20:00:00Z", api=api)
    get_success_data(api.verify_pro(pid, {"decision": "SUSPEND"}, ADMIN))
    resp = api.create_booking(
        create_booking_payload(ctx["quote"]["id"], slot["id"],
                               "2026-03-05T10:00:00Z", "2026-03-05T11:00:00Z"),
        make_customer_headers(ctx["customer"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_PRO_NOT_VERIFIED)


def test_booking_against_verified_pro_succeeds(api):
    """PRD 3.5: "A successful booking copies the quote's pro onto the booking as
    pro_id, the quote's customer as customer_id, and the quote's amount_cents
    onto the booking as price_cents; its payout_cents starts at zero and its
    status starts at CONFIRMED."

    Design: Difficulty/cross_entity_state_dependency/booking_requires_pro_verified
    """
    ctx = setup_confirmed_booking(api=api, amount_cents=10000)
    assert ctx["booking"]["status"] == "CONFIRMED"
    assert ctx["booking"]["price_cents"] == 10000
    assert ctx["booking"]["payout_cents"] == 0


# --------------------------------------------------------------------------
# Referential coherence outranks the verification check
# --------------------------------------------------------------------------
def _referential_vs_safety_scenario(api):
    """A quote from a now-SUSPENDED pro PJ, booked against a slot owned by a
    DIFFERENT pro PK. PK does not serve the request zip so the lead lands on PJ."""
    reset_clock(api)
    cat = create_category(api, min_rating_to_receive_leads=0.0)
    cust = create_customer(api)
    pj = create_verified_pro(api, wallet=20000, category_ids=[cat["id"]], zip_codes=["94016"])
    pk = create_verified_pro(api, wallet=20000, category_ids=[cat["id"]], zip_codes=["99999"])
    slot_k = create_slot(pk["id"], "2026-03-05T08:00:00Z", "2026-03-05T20:00:00Z", api=api)
    req = create_request(cust["id"], cat["id"], api=api, zip_code="94016")
    distribute_once(req["id"], req["version"], api=api)
    lead = lead_for(req["id"], pj["id"], api=api)
    get_success_data(api.contact_lead(lead["id"], make_pro_headers(pj["id"])))
    quote = get_success_data(
        api.create_quote(create_quote_payload(lead["id"], amount_cents=10000),
                         make_pro_headers(pj["id"]))
    )
    get_success_data(api.verify_pro(pj["id"], {"decision": "SUSPEND"}, ADMIN))
    return {"cust": cust, "quote": quote, "slot_k": slot_k}


def test_booking_slot_owner_mismatch_reports_reference_error_first(api):
    """PRD 3.5: "Referential coherence requires that the slot belong to the same
    pro as the quote; a mismatch yields ERR_REFERENCE_MISMATCH."
    PRD 2.9: "6. Referential coherence — cross-referenced resources cohere (see
    the endpoints that carry this rule), else ERR_REFERENCE_MISMATCH (409)."
    PRD 2.9: "7. Pro verification — when booking, the quote's pro is VERIFIED,
    else ERR_PRO_NOT_VERIFIED (409)."

    Design: Difficulty/priority_pair_validation_conflict/booking_referential_beats_safety
    """
    ctx = _referential_vs_safety_scenario(api)
    resp = api.create_booking(
        create_booking_payload(ctx["quote"]["id"], ctx["slot_k"]["id"],
                               "2026-03-05T10:00:00Z", "2026-03-05T11:00:00Z"),
        make_customer_headers(ctx["cust"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_REFERENCE_MISMATCH)


def test_rejected_booking_leaves_no_cascade_side_effects(api):
    """PRD 2.7: "the platform never leaves a partially-applied cascade — either
    every dependent effect of an operation lands, or the operation is rejected
    before any effect is applied."

    Design: Difficulty/priority_pair_validation_conflict/booking_referential_beats_safety
    """
    ctx = _referential_vs_safety_scenario(api)
    api.create_booking(
        create_booking_payload(ctx["quote"]["id"], ctx["slot_k"]["id"],
                               "2026-03-05T10:00:00Z", "2026-03-05T11:00:00Z"),
        make_customer_headers(ctx["cust"]["id"]),
    )
    slot = get_success_data(api.get_availability_slot(ctx["slot_k"]["id"], ADMIN))
    assert slot["status"] == "OPEN", "a rejected booking must not book the slot"
    assert slot["booking_id"] is None


# --------------------------------------------------------------------------
# AvailabilitySlot half-open overlap
# --------------------------------------------------------------------------
def test_overlapping_slot_rejected(api):
    """PRD 3.5: "Slots are treated as half-open intervals [start_utc, end_utc): a
    new slot may share an exact endpoint with an existing slot of the same pro
    (touching is allowed), but any true overlap with another slot of that pro is
    rejected with ERR_SLOT_OVERLAP."

    Design: Difficulty/resource_temporal_overlap/availability_slot_halfopen_overlap_rejected_adjacent_allowed
    """
    reset_clock(api)
    pro = create_verified_pro(api, zip_codes=["94016"])
    create_slot(pro["id"], "2026-03-05T10:00:00Z", "2026-03-05T11:00:00Z", api=api)
    resp = api.create_availability_slot(
        create_slot_payload(pro["id"], "2026-03-05T10:30:00Z", "2026-03-05T11:30:00Z"),
        make_pro_headers(pro["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_SLOT_OVERLAP)


def test_touching_slot_allowed(api):
    """PRD 3.5: "Slots are treated as half-open intervals [start_utc, end_utc): a
    new slot may share an exact endpoint with an existing slot of the same pro
    (touching is allowed), but any true overlap with another slot of that pro is
    rejected with ERR_SLOT_OVERLAP."

    Design: Difficulty/resource_temporal_overlap/availability_slot_halfopen_overlap_rejected_adjacent_allowed
    """
    reset_clock(api)
    pro = create_verified_pro(api, zip_codes=["94016"])
    create_slot(pro["id"], "2026-03-05T10:00:00Z", "2026-03-05T11:00:00Z", api=api)
    adj = validate_success(
        api.create_availability_slot(
            create_slot_payload(pro["id"], "2026-03-05T11:00:00Z", "2026-03-05T12:00:00Z"),
            make_pro_headers(pro["id"]),
        ),
        expected_status=201,
    )
    assert adj["status"] == "OPEN"


# --------------------------------------------------------------------------
# Booking travel-buffer conflict
# --------------------------------------------------------------------------
def _pq_second_quote_ready(api):
    """Pro PQ with a CONFIRMED booking 12:00-13:00 and a second SENT quote whose
    lead is contacted, plus a wide second slot [13:15,14:30)."""
    reset_clock(api)
    cat = create_category(api, max_leads_per_request=2, min_rating_to_receive_leads=0.0)
    cust = create_customer(api)
    pq = create_verified_pro(api, wallet=30000, category_ids=[cat["id"]], zip_codes=["94016"])
    slot1 = create_slot(pq["id"], "2026-03-05T11:30:00Z", "2026-03-05T13:00:00Z", api=api)
    slot2 = create_slot(pq["id"], "2026-03-05T13:15:00Z", "2026-03-05T14:30:00Z", api=api)
    # First booking 12:00-13:00.
    req1 = create_request(cust["id"], cat["id"], api=api, description="r1")
    distribute_once(req1["id"], req1["version"], api=api)
    lead1 = lead_for(req1["id"], pq["id"], api=api)
    get_success_data(api.contact_lead(lead1["id"], make_pro_headers(pq["id"])))
    q1 = get_success_data(api.create_quote(create_quote_payload(lead1["id"]), make_pro_headers(pq["id"])))
    get_success_data(api.create_booking(
        create_booking_payload(q1["id"], slot1["id"], "2026-03-05T12:00:00Z", "2026-03-05T13:00:00Z"),
        make_customer_headers(cust["id"])))
    # Second quote, not yet booked.
    req2 = create_request(cust["id"], cat["id"], api=api, description="r2")
    distribute_once(req2["id"], req2["version"], api=api)
    lead2 = lead_for(req2["id"], pq["id"], api=api)
    get_success_data(api.contact_lead(lead2["id"], make_pro_headers(pq["id"])))
    q2 = get_success_data(api.create_quote(create_quote_payload(lead2["id"]), make_pro_headers(pq["id"])))
    return {"cust": cust, "slot2": slot2, "q2": q2}


def test_booking_within_travel_buffer_rejected(api):
    """PRD 3.5: "In addition, it must stay clear of every other CONFIRMED booking
    of the same pro by at least a thirty-minute travel buffer: treat each
    existing confirmed booking's window as a closed interval, expand it by thirty
    minutes on both the leading and trailing side, and reject the new booking if
    it intersects any such expanded interval."

    Design: Difficulty/resource_temporal_overlap/booking_buffered_overlap_rejected
    """
    ctx = _pq_second_quote_ready(api)
    resp = api.create_booking(
        create_booking_payload(ctx["q2"]["id"], ctx["slot2"]["id"],
                               "2026-03-05T13:15:00Z", "2026-03-05T14:00:00Z"),
        make_customer_headers(ctx["cust"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_BOOKING_CONFLICT)


def test_booking_clear_of_travel_buffer_succeeds(api):
    """PRD 3.5: "In addition, it must stay clear of every other CONFIRMED booking
    of the same pro by at least a thirty-minute travel buffer: treat each
    existing confirmed booking's window as a closed interval, expand it by thirty
    minutes on both the leading and trailing side, and reject the new booking if
    it intersects any such expanded interval."

    Design: Difficulty/resource_temporal_overlap/booking_buffered_overlap_rejected
    """
    ctx = _pq_second_quote_ready(api)
    booking = validate_success(
        api.create_booking(
            create_booking_payload(ctx["q2"]["id"], ctx["slot2"]["id"],
                                   "2026-03-05T14:00:00Z", "2026-03-05T14:30:00Z"),
            make_customer_headers(ctx["cust"]["id"]),
        ),
        expected_status=201,
    )
    assert booking["status"] == "CONFIRMED"


# --------------------------------------------------------------------------
# Terminal-state lockdown + slot compensation on cancel
# --------------------------------------------------------------------------
def test_cancel_already_cancelled_booking_returns_invalid_state(api):
    """PRD 3.5: "Either party to a booking — its customer or its pro — may cancel
    a CONFIRMED booking, optionally supplying a cancellation_reason."
    PRD 2.9: "State — the target resource is in a state that permits the
    requested transition, else ERR_INVALID_STATE (409)."

    Design: Corner/state_machines/cancel_already_cancelled_booking_terminal_lockdown
    """
    ctx = setup_confirmed_booking(api=api)
    cid = ctx["customer"]["id"]
    bk = ctx["booking"]["id"]
    get_success_data(api.cancel_booking(bk, {"cancellation_reason": "x"}, make_customer_headers(cid)))
    resp = api.cancel_booking(bk, {"cancellation_reason": "again"}, make_customer_headers(cid))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_booking_reserves_slot(api):
    """PRD 3.5: "the reserved slot moves `OPEN → BOOKED` with its `booking_id`
    set to the new booking."

    Design: Difficulty/compensating_invariant/pro_slot_minutes_conserved_book_then_cancel
    """
    ctx = setup_confirmed_booking(api=api)
    slot = get_success_data(api.get_availability_slot(ctx["slot"]["id"], ADMIN))
    assert slot["status"] == "BOOKED"
    assert slot["booking_id"] == ctx["booking"]["id"]


def test_cancel_frees_slot_back_to_open(api):
    """PRD 3.5: "Cancellation sets the booking's status to CANCELLED and, as
    compensation, returns the referenced slot from BOOKED back to OPEN and clears
    its booking_id to null, so the pro's calendar minute is freed for reuse."

    Design: Difficulty/compensating_invariant/pro_slot_minutes_conserved_book_then_cancel
    """
    ctx = setup_confirmed_booking(api=api)
    cid = ctx["customer"]["id"]
    booking = validate_success(
        api.cancel_booking(ctx["booking"]["id"], {"cancellation_reason": "changed mind"},
                           make_customer_headers(cid))
    )
    assert booking["status"] == "CANCELLED"
    slot = get_success_data(api.get_availability_slot(ctx["slot"]["id"], ADMIN))
    assert slot["status"] == "OPEN"
    assert slot["booking_id"] is None
