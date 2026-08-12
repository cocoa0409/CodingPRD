"""OCC guards and side-effect execution."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    get_success_data,
    setup_active_lease,
    setup_matched_resale,
    setup_program,
    setup_under_contract_resale,
    validate_error,
)


def _lm():
    return TEST_USERS["lease_manager_headers"]


def _insp():
    return TEST_USERS["inspector_headers"]


def _is():
    return TEST_USERS["intake_specialist_headers"]


def test_stale_unit_version_returns_412_on_lease_activate():
    """PRD §2.6: "Activating a ground lease requires `expected_unit_version`
    matching the target `Unit.version`. ... If the value supplied does not
    match the parent entity's current `version` at the time the write is
    attempted, the request is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/endpoints/stale_unit_version_returns_412
    """
    prog = setup_program(name="P-OCC1")
    from test_helpers import (
        create_lease_payload,
        setup_eligible_household,
        setup_unit,
    )

    unit = setup_unit(prog["id"])
    hh, _, _ = setup_eligible_household(prog["id"])
    lease = get_success_data(
        api_client.create_lease(
            prog["id"], unit["id"],
            create_lease_payload(household_id=hh["id"]),
            _lm(),
        )
    )
    unit_now = get_success_data(api_client.get_unit(prog["id"], unit["id"], _lm()))
    # Stale by one.
    resp = api_client.activate_lease(
        prog["id"],
        unit["id"],
        lease["id"],
        {"expected_unit_version": unit_now["version"] - 1},
        _lm(),
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value, expected_status=412)

    lease_after = get_success_data(
        api_client.get_lease(prog["id"], unit["id"], lease["id"], _lm())
    )
    assert lease_after["status"] == "DRAFT"


def test_resale_listing_close_creates_buyer_draft_lease():
    """PRD §3.5: "On a successful close, the listing's `version` increments
    by 1 and its status becomes `CLOSED`; the seller's `GroundLease`
    transitions to `TERMINATED` ... a new buyer `GroundLease` is auto-created
    in `DRAFT` status (a separate activation step is required before the
    buyer occupies); the buyer's waitlist entry transitions to `FULFILLED`;
    and the unit's `occupancy_status` transitions to `VACANT`..."

    Design: Corner/endpoints/resale_listing_close_creates_buyer_draft_lease
    """
    prog = setup_program(name="P-CLS")
    _, unit, hh_s, lease_s, listing, hh_b, entry = setup_under_contract_resale(prog["id"])

    listing_now = get_success_data(
        api_client.get_resale_listing(prog["id"], unit["id"], listing["id"], _lm())
    )
    closed = get_success_data(
        api_client.close_resale_listing(
            prog["id"],
            unit["id"],
            listing["id"],
            {
                "expected_listing_version": listing_now["version"],
                "confirmed_funds": True,
            },
            _lm(),
        )
    )
    assert closed["status"] == "CLOSED"

    seller_lease_after = get_success_data(
        api_client.get_lease(prog["id"], unit["id"], lease_s["id"], _lm())
    )
    assert seller_lease_after["status"] == "TERMINATED"

    entry_after = get_success_data(
        api_client.get_waitlist_entry(prog["id"], entry["id"], _lm())
    )
    assert entry_after["status"] == "FULFILLED"

    unit_after = get_success_data(api_client.get_unit(prog["id"], unit["id"], _lm()))
    assert unit_after["occupancy_status"] == "VACANT"

    # Buyer draft lease created on the unit.
    leases = get_success_data(
        api_client.list_leases(prog["id"], unit["id"], _lm())
    )
    buyer_drafts = [
        l for l in leases
        if l["household_id"] == hh_b["id"] and l["status"] == "DRAFT"
    ]
    assert len(buyer_drafts) == 1, (
        f"Expected one buyer DRAFT lease on the unit, found {len(buyer_drafts)}"
    )
