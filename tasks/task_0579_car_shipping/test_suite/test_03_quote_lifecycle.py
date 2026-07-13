"""Quote acceptance lifecycle: expiry boundary, re-acceptance, empty vehicle set.

Translated from SCAFFOLD_DIFFICULTY_DESIGN.yaml §1.8 (boundary_precision_check)
and SCAFFOLD_CORNER_DESIGN.yaml §1.9 (state_machines, validations).
"""
from test_helpers import (
    attach_vehicle,
    create_order,
    generate_quote,
    make_shipper_headers,
    register_shipper,
    set_clock,
    setup_order_with_offered_quote,
    setup_quoted_order,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)


def _quote_at_clock(clock_iso, order_window_start, order_window_end):
    """Set the clock, then build a DRAFT order + one vehicle + a generated quote.
    Returns (shipper_id, order_id, quote_id). The quote's valid_until is
    created_at + 72h relative to the logical clock (PRD §3.3)."""
    set_clock(clock_iso)
    shipper = register_shipper()
    order = create_order(
        shipper["id"], route_miles=1200, transport_type="OPEN",
        pickup_window_start=order_window_start, pickup_window_end=order_window_end,
    )
    attach_vehicle(order["id"], shipper["id"], declared_value_cents=1_000_000)
    quote = generate_quote(order["id"], shipper["id"])
    return shipper["id"], order["id"], quote["id"]


# ─── boundary_precision_check / quote expiry (inclusive) — 2 tests ──────────

def test_accept_at_exactly_valid_until_advances_order_to_quoted(api):
    """PRD §2.6: "A quote's valid_until is compared against the logical clock at
    acceptance time; a quote may only be accepted while the clock is at or before
    valid_until."
    PRD §3.3: "Its valid_until is set to its created_at plus 72 hours, after which
    it can no longer be accepted."
    PRD §3.3: "When the Shipper accepts an OFFERED quote, the order advances from
    DRAFT to QUOTED."

    Design: Difficulty/boundary_precision_check/quote_expiry_inclusive_boundary_accept_at_valid_until
    """
    shipper_id, order_id, quote_id = _quote_at_clock(
        "2026-06-01T00:00:00Z", "2026-07-01T08:00:00Z", "2026-07-05T18:00:00Z"
    )
    set_clock("2026-06-04T00:00:00Z")  # exactly created_at + 72h
    resp = api.accept_quote(order_id, quote_id, make_shipper_headers(shipper_id))
    order = validate_success(resp, expected_status=200)
    assert order["status"] == "QUOTED"


def test_accept_at_exactly_valid_until_marks_quote_accepted(api):
    """PRD §2.6: "a quote may only be accepted while the clock is at or before
    valid_until."
    PRD §3.3: "the accepted quote flips to ACCEPTED while all sibling OFFERED
    quotes on the order flip to SUPERSEDED".

    Design: Difficulty/boundary_precision_check/quote_expiry_inclusive_boundary_accept_at_valid_until
    """
    shipper_id, order_id, quote_id = _quote_at_clock(
        "2026-06-01T00:00:00Z", "2026-07-01T08:00:00Z", "2026-07-05T18:00:00Z"
    )
    set_clock("2026-06-04T00:00:00Z")
    validate_success(api.accept_quote(order_id, quote_id, make_shipper_headers(shipper_id)), 200)
    quote = validate_success(api.get_quote(quote_id, make_shipper_headers(shipper_id)), 200)
    assert quote["status"] == "ACCEPTED"


# ─── state_machines / re-acceptance ────────────────────────────────────────

def test_accepting_an_already_accepted_quote_is_rejected(api):
    """PRD §3.3: "Acceptance requires that the order have at least one vehicle,
    else it is rejected with ERR_NO_VEHICLES; that the quote be in OFFERED status,
    else ERR_QUOTE_NOT_OFFERED; and that the logical clock be at or before the
    quote's valid_until, else ERR_QUOTE_EXPIRED."
    PRD §2.1: "then whether the target resource is in a state that permits the
    transition (ERR_INVALID_STATE, 409, unless a more specific domain state error
    is declared for that transition)".

    A PRD-only implementer may reject the re-acceptance either on the quote-status
    precondition (ERR_QUOTE_NOT_OFFERED) or on the generic order-state check
    (ERR_INVALID_STATE); both are faithful, so this asserts the family.

    Design: Corner/state_machines/accept_quote_twice_returns_quote_not_offered
    """
    ctx = setup_quoted_order(route_miles=1200, declared_value_cents=1_000_000)
    resp = api.accept_quote(ctx["order"]["id"], ctx["quote"]["id"],
                            make_shipper_headers(ctx["shipper"]["id"]))
    validate_error_is_one_of(resp, ["ERR_QUOTE_NOT_OFFERED", "ERR_INVALID_STATE"])


# ─── validations / empty vehicle set ───────────────────────────────────────

def test_accept_quote_with_no_vehicles_rejected(api):
    """PRD §3.3: "Acceptance requires that the order have at least one vehicle,
    else it is rejected with ERR_NO_VEHICLES".

    Design: Corner/validations/accept_quote_with_no_vehicles_returns_no_vehicles
    """
    ctx = setup_order_with_offered_quote(route_miles=1200, attach=False)
    resp = api.accept_quote(ctx["order"]["id"], ctx["quote"]["id"],
                            make_shipper_headers(ctx["shipper"]["id"]))
    validate_error(resp, "ERR_NO_VEHICLES", expected_status=409)
