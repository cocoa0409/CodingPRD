"""Inter-library loan workflow tests (PRD §3.7)."""

import pytest

from test_helpers import (
    ADMIN_HEADERS,
    ILL_COORDINATOR_HEADERS,
    LIBRARIAN_HEADERS,
    advance_clock_days,
    api_client,
    assert_ill_request,
    create_book_title_with_copy,
    create_ill_request_payload,
    create_verified_reader_with_card,
    dispatch_ill_payload,
    emit_event_payload,
    expected_ill_settlement_total,
    ill_availability_event_payload,
    ill_delivered_event_payload,
    ill_return_initiated_event_payload,
    make_reader_headers,
    setup_ill_at_partner,
    setup_ill_returned_transit,
    submit_ill_request,
    validate_error,
    validate_success,
)


# =============================================================================
# Submission validation (PRD §3.7)
# =============================================================================


def test_create_ill_request_initial_state(api):
    """PRD §3.7: "The request enters SUBMITTED with handling_fee_cents
    initialized to the constant 300 cents per leg, settlement_total_cents
    zero, and the in-transit endpoints null."

    Claim: a freshly submitted ILLRequest has status=SUBMITTED,
    handling_fee_cents=300, settlement_total_cents=0, in_transit_from null,
    in_transit_to null.
    """
    title, _ = create_book_title_with_copy()
    reader, card = create_verified_reader_with_card()
    res = api.create_ill_request(
        create_ill_request_payload(
            card["id"],
            target_marc_control_number=title["marc_control_number"],
            shipping_cost_cents=1000,
        ),
        make_reader_headers(reader["id"]),
    )
    req = validate_success(res, 201)
    assert_ill_request(req)
    assert req["status"] == "SUBMITTED"
    assert req["handling_fee_cents"] == 300
    assert req["settlement_total_cents"] == 0
    assert req.get("in_transit_from") in (None,)
    assert req.get("in_transit_to") in (None,)


@pytest.mark.parametrize("bad_partner", ["PL_X", "FOO", ""])
def test_unknown_partner_rejected(api, bad_partner):
    """PRD §3.7: "the partner_library_code from the approved partner network
    (currently PL_A, PL_B, or PL_C; any other value is rejected with
    ERR_UNKNOWN_PARTNER)".

    Claim: a partner_library_code outside the approved set returns
    ERR_UNKNOWN_PARTNER (HTTP 422).
    """
    title, _ = create_book_title_with_copy()
    reader, card = create_verified_reader_with_card()
    res = api.create_ill_request(
        create_ill_request_payload(
            card["id"],
            partner_library_code=bad_partner,
            target_marc_control_number=title["marc_control_number"],
            shipping_cost_cents=1000,
        ),
        make_reader_headers(reader["id"]),
    )
    validate_error(res, "ERR_UNKNOWN_PARTNER", expected_status=422)


# =============================================================================
# Approval (PRD §3.7)
# =============================================================================


def test_approve_pinns_agreed_loan_days_to_min(api):
    """PRD §3.7: "On approval the negotiated agreed_loan_days is set to the
    smaller of the event's partner_max_days and the requester's maximum loan
    period of twenty-one days."

    Claim: when partner_max_days=14, agreed_loan_days is min(14, 21) = 14.
    """
    ctx = setup_ill_at_partner(partner_max_days=14, shipping_cost_cents=1000)
    assert ctx["ill_request"]["agreed_loan_days"] == 14


def test_approve_with_long_partner_max_caps_at_21(api):
    """PRD §3.7: "the smaller of the event's partner_max_days and the
    requester's maximum loan period of twenty-one days."

    Claim: when partner_max_days=30, agreed_loan_days is min(30, 21) = 21.
    """
    ctx = setup_ill_at_partner(partner_max_days=30, shipping_cost_cents=1000)
    assert ctx["ill_request"]["agreed_loan_days"] == 21


def test_return_received_before_loan_period_rejected(api):
    """PRD §3.7: "an attempt before the window opens is rejected with
    ERR_ILL_LOAN_PERIOD_NOT_MET."

    Claim: emitting ILL_RETURN_INITIATED before in_transit_from +
    agreed_loan_days returns ERR_ILL_LOAN_PERIOD_NOT_MET.
    """
    ctx = setup_ill_at_partner(partner_max_days=14, shipping_cost_cents=1000)
    # Advance only 13 days (less than agreed_loan_days=14).
    advance_clock_days(13)
    res = api.emit_event(
        ill_return_initiated_event_payload(ctx["ill_request"]["id"]),
        ADMIN_HEADERS,
    )
    # Either the emit itself surfaces the error, or a subsequent return-received
    # does. PRD §3.7 says the gate is on ILL_RETURN_INITIATED. We assert the
    # status-code shows a 4xx with this specific error_id.
    assert res.status_code == 409
    body = res.json()
    assert body["data"]["error_id"] == "ERR_ILL_LOAN_PERIOD_NOT_MET"


# =============================================================================
# Settlement (PRD §3.7)
# =============================================================================


def test_settlement_computes_per_leg_then_sums(api):
    """PRD §3.7: "For each leg the server computes the insurance charge as
    the leg's shipping_cost_cents multiplied by an insurance rate of 2.50%,
    rounded half-up to whole cents; the leg total is the sum of
    shipping_cost_cents, handling_fee_cents, and that insurance charge,
    rounded half-up to whole cents; and settlement_total_cents is the sum of
    the outbound leg total and the inbound leg total."

    Claim: for shipping_cost_cents=1000, handling=300, insurance=
    round_half_up(25.0)=25, per_leg = 1000+300+25 = 1325, total = 2650.
    """
    ctx = setup_ill_returned_transit(
        partner_max_days=14, shipping_cost_cents=1000
    )
    res = api.return_received_ill(
        ctx["ill_request"]["id"], None, ILL_COORDINATOR_HEADERS
    )
    settled = validate_success(res, 200)
    assert settled["status"] == "SETTLED"
    expected = expected_ill_settlement_total(1000, handling_fee_cents=300)
    assert settled["settlement_total_cents"] == expected, (
        f"PRD §3.7: per-leg rounding then sum for shipping=1000 → expected "
        f"{expected}, got {settled['settlement_total_cents']}"
    )


def test_settlement_round_per_leg_diverges_at_half_cent_boundary(api):
    """PRD §3.7: "the rounding happens per leg before the two legs are summed,
    not after."
    PRD §2.10: "Where rounding is required inside the ILL settlement
    computation, the rounding method is half-up (an amount of 0.5 cents
    rounds up to 1)."

    Claim: with shipping=20, insurance = round_half_up(20*0.025=0.5) = 1;
    per_leg = round_half_up(20+300+1) = 321; total = 642 (NOT 641 from
    sum-then-round).
    """
    ctx = setup_ill_returned_transit(
        partner_max_days=14, shipping_cost_cents=20
    )
    res = api.return_received_ill(
        ctx["ill_request"]["id"], None, ILL_COORDINATOR_HEADERS
    )
    settled = validate_success(res, 200)
    assert settled["settlement_total_cents"] == 642, (
        "PRD §3.7: with shipping=20 the per-leg-then-sum order produces 642, "
        f"not 641 (sum-then-round); got {settled['settlement_total_cents']}"
    )


def test_return_received_refreshes_copy_to_available(api):
    """PRD §3.7: "The copy's IN_TRANSIT_ILL reverts to AVAILABLE (possibly
    cascading to RESERVED via the standard promotion if a queue head exists)".

    Claim: after return-received, the dispatched Copy.status is AVAILABLE.
    """
    ctx = setup_ill_returned_transit(
        partner_max_days=14, shipping_cost_cents=1000
    )
    validate_success(
        api.return_received_ill(
            ctx["ill_request"]["id"], None, ILL_COORDINATOR_HEADERS
        ),
        200,
    )
    listing = api.list_copies(ctx["title"]["id"], LIBRARIAN_HEADERS)
    target = next(c for c in listing.json()["data"] if c["id"] == ctx["copy"]["id"])
    assert target["status"] == "AVAILABLE"


# =============================================================================
# Dispatch validation (PRD §3.7)
# =============================================================================


def test_dispatch_on_non_available_copy_rejected(api):
    """PRD §3.7: "the dispatch request supplies a copy_id of a copy whose
    underlying BookTitle carries the same marc_control_number as the request's
    target_marc_control_number and whose status is AVAILABLE."

    Claim: dispatch with a non-AVAILABLE copy is rejected.
    """
    title, copy = create_book_title_with_copy()
    reader, card = create_verified_reader_with_card()
    # Borrow the copy so it goes ON_LOAN.
    from test_helpers import create_loan_payload
    validate_success(
        api.create_loan(
            create_loan_payload(copy["id"], card["id"], channel="COUNTER"),
            make_reader_headers(reader["id"]),
        ),
        201,
    )
    # Submit + approve an ILL for the same MARC.
    req = submit_ill_request(
        reader, card, title["marc_control_number"], shipping_cost_cents=1000
    )
    validate_success(
        api.emit_event(
            ill_availability_event_payload(
                req["id"], available=True, partner_max_days=14
            ),
            ADMIN_HEADERS,
        ),
        200,
    )
    validate_success(api.approve_ill(req["id"], None, ILL_COORDINATOR_HEADERS), 200)

    res = api.dispatch_ill(
        req["id"], dispatch_ill_payload(copy["id"]), ILL_COORDINATOR_HEADERS
    )
    # PRD §3.7 says dispatch requires status=AVAILABLE; the COPY-state error
    # surface is ERR_COPY_NOT_AVAILABLE per PRD §3.3 and the priority-8
    # category. Or could be ERR_INVALID_STATE if the impl pre-empts there.
    assert res.status_code == 409
    body = res.json()
    assert body["data"]["error_id"] in (
        "ERR_COPY_NOT_AVAILABLE",
        "ERR_INVALID_STATE",
    )
