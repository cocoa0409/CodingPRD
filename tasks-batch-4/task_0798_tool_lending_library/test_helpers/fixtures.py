"""Composite setup helpers for multi-step test prerequisites.

The runner restarts the server (empty database, logical clock reset to the
2026-03-01 startup default) before every test, so every helper here builds its
world from scratch. All setup calls use get_success_data() (lenient) so setup
failures surface as clear "Setup failed" errors rather than assertion noise.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_member_payload, create_volunteer_payload, create_item_payload,
    add_copy_payload, create_reservation_payload, create_loan_payload,
    return_loan_payload, create_hold_payload, create_donation_payload,
    accept_donation_payload, create_ticket_payload, resolve_ticket_payload,
    waive_fee_payload, set_clock_payload,
)
from .test_users import (
    TEST_USERS, make_member_headers, make_volunteer_headers,
)

COORD = TEST_USERS["coordinator_headers"]


# --------------------------------------------------------------------------- #
# Clock / housekeeping
# --------------------------------------------------------------------------- #
def set_clock(iso: str):
    """Set the logical clock (PRD §2.5). Returns the clock response data."""
    return get_success_data(api_client.set_clock(set_clock_payload(iso), COORD))


def ops_run():
    """Run the housekeeping batch (PRD §2.5). Returns the counts payload."""
    return get_success_data(api_client.ops_run(COORD))


# --------------------------------------------------------------------------- #
# Primitive creators (return the created entity data)
# --------------------------------------------------------------------------- #
def create_member(**overrides):
    return get_success_data(api_client.create_member(create_member_payload(**overrides), COORD))


def create_volunteer(**overrides):
    return get_success_data(api_client.create_volunteer(create_volunteer_payload(**overrides), COORD))


def create_item(**overrides):
    return get_success_data(api_client.create_item(create_item_payload(**overrides), COORD))


def add_copy(item_id, **overrides):
    return get_success_data(api_client.add_copy(item_id, add_copy_payload(**overrides), COORD))


def get_item(item_id):
    return get_success_data(api_client.get_item(item_id, COORD))


def item_version(item_id) -> int:
    return get_item(item_id)["version"]


def get_member(member_id):
    return get_success_data(api_client.get_member(member_id, COORD))


def get_copy(copy_id):
    return get_success_data(api_client.get_copy(copy_id, COORD))


def get_loan(loan_id):
    return get_success_data(api_client.get_loan(loan_id, COORD))


def get_reservation(reservation_id):
    return get_success_data(api_client.get_reservation(reservation_id, COORD))


def get_hold(hold_id):
    return get_success_data(api_client.get_hold(hold_id, COORD))


def get_fee(fee_id):
    return get_success_data(api_client.get_fee(fee_id, COORD))


# --------------------------------------------------------------------------- #
# Composite actions
# --------------------------------------------------------------------------- #
def checkout(member_id, copy_id, item_id, reservation_id=None, headers=None):
    """Read the item's current version and check out the copy (PRD §2.8, §3.4).
    Defaults to acting as a Coordinator (superset operator)."""
    hdrs = headers if headers is not None else COORD
    iv = item_version(item_id)
    payload = create_loan_payload(member_id, copy_id, iv, reservation_id=reservation_id)
    return get_success_data(api_client.create_loan(payload, hdrs))


def return_loan(loan_id, return_condition="GOOD", headers=None):
    hdrs = headers if headers is not None else COORD
    return get_success_data(api_client.return_loan(loan_id, return_loan_payload(return_condition), hdrs))


def renew_loan(loan_id, headers=None):
    hdrs = headers if headers is not None else COORD
    return get_success_data(api_client.renew_loan(loan_id, hdrs))


def create_reservation(member_id, item_id, window_start, window_end):
    """Create a MEMBER reservation as the owning member (PRD §3.3)."""
    payload = create_reservation_payload(member_id, item_id, window_start, window_end)
    return get_success_data(api_client.create_reservation(payload, make_member_headers(member_id)))


def cancel_reservation(reservation_id, member_id):
    return get_success_data(
        api_client.cancel_reservation(reservation_id, make_member_headers(member_id)))


def create_hold(member_id, item_id):
    """Join the waitlist as the owning member (PRD §3.7)."""
    payload = create_hold_payload(member_id, item_id)
    return get_success_data(api_client.create_hold(payload, make_member_headers(member_id)))


def create_ticket(copy_id, reason="ROUTINE", **overrides):
    return get_success_data(
        api_client.create_ticket(create_ticket_payload(copy_id, reason=reason, **overrides), COORD))


def resolve_ticket(ticket_id, outcome="RETURN_TO_SERVICE"):
    return get_success_data(
        api_client.resolve_ticket(ticket_id, resolve_ticket_payload(outcome), COORD))


def create_donation(item_id, **overrides):
    return get_success_data(api_client.create_donation(create_donation_payload(item_id, **overrides), COORD))


def accept_donation(donation_id, asset_tag="DON-1", **overrides):
    return get_success_data(
        api_client.accept_donation(donation_id, accept_donation_payload(asset_tag, **overrides), COORD))


def pay_fee(fee_id, headers=None):
    hdrs = headers if headers is not None else COORD
    return get_success_data(api_client.pay_fee(fee_id, hdrs))


def waive_fee(fee_id, reason=None):
    payload = waive_fee_payload(**({"reason": reason} if reason is not None else {}))
    return get_success_data(api_client.waive_fee(fee_id, payload, COORD))


# --------------------------------------------------------------------------- #
# Fee lookups
# --------------------------------------------------------------------------- #
def fees_for_loan(loan_id):
    """All fees whose loan_id matches, sorted by created_at ASC (list default)."""
    data, _meta = _paginate(api_client.list_fees(COORD, params={"loan_id": loan_id, "limit": 100}))
    return data


def first_fee_for_loan(loan_id):
    """The (single) fee raised for a loan. Fails setup if none exists."""
    fees = fees_for_loan(loan_id)
    assert fees, f"Setup failed: expected at least one fee for loan {loan_id}"
    return fees[0]


def _paginate(response):
    body = response.json()
    return body.get("data", []), body.get("meta", {})


# --------------------------------------------------------------------------- #
# Composite scenarios
# --------------------------------------------------------------------------- #
def setup_member_item_copy(clock="2026-03-01T00:00:00Z", member_overrides=None,
                           item_overrides=None, copy_overrides=None):
    """Base world: one ACTIVE member, one item, one GOOD AVAILABLE copy, clock set.
    Returns (member, item, copy)."""
    member = create_member(**(member_overrides or {}))
    item = create_item(**(item_overrides or {}))
    copy = add_copy(item["id"], **(copy_overrides or {}))
    set_clock(clock)
    return member, item, copy


def setup_checked_out_loan(clock="2026-03-01T00:00:00Z", member_overrides=None,
                           item_overrides=None, copy_overrides=None):
    """Base world + a walk-up checkout. Returns (member, item, copy, loan)."""
    member, item, copy = setup_member_item_copy(
        clock=clock, member_overrides=member_overrides,
        item_overrides=item_overrides, copy_overrides=copy_overrides)
    loan = checkout(member["id"], copy["id"], item["id"])
    return member, item, copy, loan


def setup_overdue_loan(clock_checkout="2026-03-01T00:00:00Z",
                       clock_overdue="2026-03-11T00:00:00Z",
                       item_overrides=None):
    """Checkout at clock_checkout, advance to clock_overdue, run housekeeping so the
    loan is OVERDUE with an ACCRUING LATE fee (PRD §3.4). Returns
    (member, item, copy, loan, fee)."""
    member, item, copy, loan = setup_checked_out_loan(
        clock=clock_checkout, item_overrides=item_overrides)
    set_clock(clock_overdue)
    ops_run()
    fee = first_fee_for_loan(loan["id"])
    return member, item, copy, loan, fee


def setup_pending_reservation(clock="2026-03-01T00:00:00Z",
                              window_start="2026-04-01T00:00:00Z",
                              window_end="2026-04-05T00:00:00Z",
                              item_overrides=None):
    """One ACTIVE member with a PENDING reservation on an item's only copy.
    Returns (member, item, copy, reservation)."""
    member, item, copy = setup_member_item_copy(clock=clock, item_overrides=item_overrides)
    reservation = create_reservation(member["id"], item["id"], window_start, window_end)
    return member, item, copy, reservation


def setup_copy_needs_maintenance(clock="2026-03-01T00:00:00Z", reason="ROUTINE",
                                 item_overrides=None):
    """One item whose only copy has been driven to NEEDS_MAINTENANCE by an immediate
    manual ticket (PRD §3.8). Returns (member, item, copy, ticket)."""
    member, item, copy = setup_member_item_copy(clock=clock, item_overrides=item_overrides)
    ticket = create_ticket(copy["id"], reason=reason)
    return member, item, copy, ticket
