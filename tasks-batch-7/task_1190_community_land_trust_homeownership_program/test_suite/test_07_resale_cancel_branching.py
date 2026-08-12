"""ResaleListing branching — cancel from MATCHED restores buyer entry and unit."""
import pytest

from test_helpers import (
    TEST_USERS,
    api_client,
    get_success_data,
    setup_matched_resale,
    setup_program,
)


def _lm():
    return TEST_USERS["lease_manager_headers"]


def test_cancel_matched_listing_restores_buyer_entry_to_active():
    """PRD §3.5: "A listing in `OPEN` or `MATCHED` may be cancelled by a
    `LeaseManager`. Cancellation sets the listing's status to `CANCELLED`; if
    the listing was `MATCHED`, the previously matched waitlist entry is
    returned to `ACTIVE` with `matched_unit_id`, `matched_at`, and
    `match_rank_at_match` all cleared."

    Design: Difficulty/non_linear_state_machine/resale_listing_branching_cancel_path
    """
    prog = setup_program(name="P-CXL1")
    _, unit, _, _, listing, _, entry = setup_matched_resale(prog["id"])

    cancelled = get_success_data(
        api_client.cancel_resale_listing(prog["id"], unit["id"], listing["id"], _lm())
    )
    assert cancelled["status"] == "CANCELLED"

    entry_after = get_success_data(
        api_client.get_waitlist_entry(prog["id"], entry["id"], _lm())
    )
    assert entry_after["status"] == "ACTIVE"
    assert entry_after["matched_unit_id"] is None
    assert entry_after["matched_at"] is None
    assert entry_after["match_rank_at_match"] is None


def test_cancel_matched_listing_returns_unit_to_occupied():
    """PRD §3.5: "The unit's `occupancy_status` returns to `OCCUPIED` — the
    seller remains in place."

    Design: Difficulty/non_linear_state_machine/resale_listing_branching_cancel_path
    """
    prog = setup_program(name="P-CXL2")
    _, unit, _, _, listing, _, _ = setup_matched_resale(prog["id"])

    get_success_data(
        api_client.cancel_resale_listing(prog["id"], unit["id"], listing["id"], _lm())
    )

    unit_after = get_success_data(api_client.get_unit(prog["id"], unit["id"], _lm()))
    assert unit_after["occupancy_status"] == "OCCUPIED"


def test_cancel_from_open_leaves_no_buyer_side_effects():
    """PRD §3.5: "A listing in `OPEN` or `MATCHED` may be cancelled by a
    `LeaseManager`. Cancellation sets the listing's status to `CANCELLED`..."

    Cancelling from OPEN is a valid transition that does not require any
    matched buyer to unwind.

    Design: Difficulty/non_linear_state_machine/resale_listing_branching_cancel_path
    """
    from test_helpers import setup_listed_resale

    prog = setup_program(name="P-CXL3")
    _, unit, _, _, listing = setup_listed_resale(prog["id"])
    assert listing["status"] == "OPEN"

    cancelled = get_success_data(
        api_client.cancel_resale_listing(prog["id"], unit["id"], listing["id"], _lm())
    )
    assert cancelled["status"] == "CANCELLED"
