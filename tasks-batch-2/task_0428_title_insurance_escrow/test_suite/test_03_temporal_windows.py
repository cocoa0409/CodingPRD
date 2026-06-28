"""Temporal-overlap rules: the closed parcel gap window and the half-open wire window.

Covers queue A: resource_temporal_overlap (gap defect on parcel, wire-window overlap),
plus queue B validations corner (invalid gap window).
"""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    create_agency_and_order,
    setup_order_clear_to_close,
    add_title_search,
    complete_title_search,
    add_posted_deposit,
    add_wired_disbursement,
    add_approved_disbursement,
    TO,
    UW,
)


# ---------------------------------------------------------------------------
# Queue A — resource_temporal_overlap: gap defect (closed interval on parcel)
# ---------------------------------------------------------------------------
def test_lien_on_gap_lower_boundary_rejected_as_gap_defect(api):
    """PRD §3.3: "The gap window here is a closed interval: a `recorded_date` falling on
    `gap_from_date`, on `gap_to_date`, or anywhere between them lands inside the window.
    If the new lien or mortgage falls inside any such active gap window, the record is
    rejected with `ERR_GAP_DEFECT`, because it represents an encumbrance recorded during
    the uninsured gap that the policy would otherwise have to insure over."
    Gap window [2026-02-01, 2026-03-01]; a LIEN recorded on 2026-02-01 (inclusive lower
    boundary) is a gap defect.

    Design: Difficulty/resource_temporal_overlap/gap_defect_closed_interval_on_parcel
    """
    agency, order = create_agency_and_order(parcel_id="APN-GAP")
    search = add_title_search(order, searched_parcel_id="APN-GAP", effective_date="2026-02-01T00:00:00Z")
    complete_title_search(
        search, chain_verified=True,
        gap_from_date="2026-02-01T00:00:00Z", gap_to_date="2026-03-01T00:00:00Z",
    )
    payload = {
        "parcel_id": "APN-GAP", "county": "King", "instrument_type": "LIEN",
        "recorded_date": "2026-02-01T00:00:00Z", "sequence_no": 5, "grantor": "X", "grantee": "Y",
    }
    validate_error(api.create_plant_record(payload, TO), ApiErrorId.ERR_GAP_DEFECT.value)


def test_lien_outside_gap_window_accepted(api):
    """PRD §3.3: "Other instrument types, and liens or mortgages recorded outside every
    active gap window, are accepted."
    Gap window [2026-02-01, 2026-03-01]; a LIEN recorded 2026-04-01 (after the closed
    upper boundary) is accepted.

    Design: Difficulty/resource_temporal_overlap/gap_defect_closed_interval_on_parcel
    """
    agency, order = create_agency_and_order(parcel_id="APN-GAP2")
    search = add_title_search(order, searched_parcel_id="APN-GAP2", effective_date="2026-02-01T00:00:00Z")
    complete_title_search(
        search, chain_verified=True,
        gap_from_date="2026-02-01T00:00:00Z", gap_to_date="2026-03-01T00:00:00Z",
    )
    payload = {
        "parcel_id": "APN-GAP2", "county": "King", "instrument_type": "LIEN",
        "recorded_date": "2026-04-01T00:00:00Z", "sequence_no": 6, "grantor": "X", "grantee": "Y",
    }
    data = validate_success(api.create_plant_record(payload, TO), expected_status=201)
    assert data["instrument_type"] == "LIEN"


# ---------------------------------------------------------------------------
# Queue A — resource_temporal_overlap: wire-window overlap (half-open on order escrow)
# ---------------------------------------------------------------------------
def test_overlapping_wire_window_rejected(api):
    """PRD §3.7: "the disbursement's half-open wire window — from `wire_window_start`
    inclusive to `wire_window_end` exclusive — must not overlap the window of any other
    `WIRED` disbursement on the same order (otherwise `ERR_WIRE_WINDOW_OVERLAP`)."
    A WIRED [09:00,10:00) then a second wire [09:30,10:30) shares an interior instant.

    Design: Difficulty/resource_temporal_overlap/wire_window_overlap_half_open_on_order_escrow
    """
    agency, order, _commitment, _search, _policy = setup_order_clear_to_close()
    add_posted_deposit(order, agency, amount_cents=600_000, source_ref="WIRE-IN-WO")
    add_wired_disbursement(
        order, amount_cents=200_000, purpose="PAYOFF", payee="Payoff Bank",
        wire_window_start="2026-01-20T09:00:00Z", wire_window_end="2026-01-20T10:00:00Z",
    )
    disb2 = add_approved_disbursement(
        order, amount_cents=200_000, purpose="SELLER_PROCEEDS", payee="Seller",
        wire_window_start="2026-01-20T09:30:00Z", wire_window_end="2026-01-20T10:30:00Z",
    )
    validate_error(
        api.transition_disbursement(disb2["id"], {"to_status": "WIRED"}, UW),
        ApiErrorId.ERR_WIRE_WINDOW_OVERLAP.value,
    )
    refetched = validate_success(api.get_disbursement(disb2["id"], UW))
    assert refetched["status"] == "APPROVED", "rejected wire leaves the disbursement APPROVED"


def test_exactly_adjacent_wire_window_allowed(api):
    """PRD §3.7: "Because the wire windows are half-open, two windows that are exactly
    adjacent — one ending at the instant the next begins — do not overlap and are both
    allowed; only windows that share an interior instant collide."
    A WIRED [09:00,10:00) then a second wire [10:00,11:00) is exactly adjacent.

    Design: Difficulty/resource_temporal_overlap/wire_window_overlap_half_open_on_order_escrow
    """
    agency, order, _commitment, _search, _policy = setup_order_clear_to_close()
    add_posted_deposit(order, agency, amount_cents=600_000, source_ref="WIRE-IN-WA")
    add_wired_disbursement(
        order, amount_cents=200_000, purpose="PAYOFF", payee="Payoff Bank",
        wire_window_start="2026-01-20T09:00:00Z", wire_window_end="2026-01-20T10:00:00Z",
    )
    disb2 = add_approved_disbursement(
        order, amount_cents=200_000, purpose="SELLER_PROCEEDS", payee="Seller",
        wire_window_start="2026-01-20T10:00:00Z", wire_window_end="2026-01-20T11:00:00Z",
    )
    data = validate_success(api.transition_disbursement(disb2["id"], {"to_status": "WIRED"}, UW))
    assert data["status"] == "WIRED", "exactly-adjacent half-open windows must both be allowed"


# ---------------------------------------------------------------------------
# Queue B — validations: invalid gap window on search completion
# ---------------------------------------------------------------------------
def test_complete_search_with_inverted_gap_window_rejected(api):
    """PRD §3.3: "the transition to `COMPLETED` requires the request to supply
    `chain_verified`, `gap_from_date`, and `gap_to_date`, and `gap_from_date` must be less
    than or equal to `gap_to_date` (otherwise `ERR_INVALID_GAP_WINDOW`)."
    gap_from_date 2026-03-01 after gap_to_date 2026-02-01.

    Design: Corner/validations/invalid_gap_window_rejected
    """
    agency, order = create_agency_and_order(parcel_id="APN-IGW")
    search = add_title_search(order, searched_parcel_id="APN-IGW")
    validate_success(api.transition_title_search(search["id"], {"to_status": "IN_EXAM"}, TO))
    validate_error(
        api.transition_title_search(
            search["id"],
            {
                "to_status": "COMPLETED", "chain_verified": True,
                "gap_from_date": "2026-03-01T00:00:00Z", "gap_to_date": "2026-02-01T00:00:00Z",
            },
            TO,
        ),
        ApiErrorId.ERR_INVALID_GAP_WINDOW.value,
    )
    refetched = validate_success(api.get_title_search(search["id"], TO))
    assert refetched["status"] == "IN_EXAM", "search stays IN_EXAM after the rejected completion"
