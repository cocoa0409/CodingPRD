"""Permit pools and passes: temporal-before-quota priority, quota decrement,
pass expiry on clock advance, and the fiscal sufficiency check.

Queue-A depth: priority_pair_validation_conflict (temporal beats constraint).
Queue-B: quota decrement, pass expiry, insufficient-credit.
"""
import pytest
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    new_member, new_permit_allocation, issue_permit, get_allocation, set_clock,
    create_permit_pass_payload, make_member_headers,
    TEST_USERS,
)

STAFF = TEST_USERS["staff_headers"]


def _issue_expecting_error(api, member, alloc, entry_date, expected_version=None):
    if expected_version is None:
        expected_version = get_allocation(alloc["id"])["version"]
    payload = create_permit_pass_payload(member["id"], alloc["id"], entry_date, expected_version)
    return api.create_permit_pass(payload, make_member_headers(member["id"]))


# ─── priority_pair / temporal_beats_constraint_on_permit_issue ─────────────

def test_permit_outside_season_and_quota_exhausted_returns_outside_season(api):
    """PRD §3.6: "Issuance is subject, in order, to the concurrency check of §2.7, to
    the member's membership_status being ACTIVE (else ERR_MEMBERSHIP_INACTIVE), to
    the temporal season check requiring entry_date to fall on or after season_start
    and on or before season_end (else ERR_OUTSIDE_SEASON), to the pool having at
    least one permit of available_quota remaining (else ERR_QUOTA_EXHAUSTED), and to
    the member's store_credit_cents being at least the pool's price_cents (else
    ERR_INSUFFICIENT_STORE_CREDIT)."

    Design: Difficulty/priority_pair_validation_conflict/temporal_beats_constraint_on_permit_issue
    """
    member = new_member(credit=10000)
    alloc = new_permit_allocation(total_quota=1, price_cents=2000, park_name="Enchantments")
    issue_permit(member, alloc, "2026-08-10T00:00:00Z")   # draws the only permit -> quota 0
    res = _issue_expecting_error(api, member, alloc, "2026-09-15T00:00:00Z")
    validate_error(res, ApiErrorId.ERR_OUTSIDE_SEASON.value)


def test_temporal_beats_constraint_permit(api):
    """PRD §3.6: "the temporal season check requiring entry_date to fall on or after
    season_start and on or before season_end (else ERR_OUTSIDE_SEASON), to the pool
    having at least one permit of available_quota remaining (else
    ERR_QUOTA_EXHAUSTED)".

    Entry outside season AND a fully-drawn pool: the temporal error (priority 6) is
    returned, not ERR_QUOTA_EXHAUSTED (priority 8).

    Design: Difficulty/priority_pair_validation_conflict/temporal_beats_constraint_on_permit_issue
    """
    member = new_member(credit=10000)
    alloc = new_permit_allocation(total_quota=1, price_cents=2000, park_name="Enchantments")
    issue_permit(member, alloc, "2026-08-10T00:00:00Z")
    res = _issue_expecting_error(api, member, alloc, "2026-09-15T00:00:00Z")
    body = res.json()["data"]
    assert body["error_id"] == ApiErrorId.ERR_OUTSIDE_SEASON.value
    assert body["error_id"] != ApiErrorId.ERR_QUOTA_EXHAUSTED.value


# ─── Queue-B calculations / permit_quota_decrements_on_issue ───────────────

def test_permit_quota_decrements_on_issue(api):
    """PRD §3.6: "On success the pass is created ISSUED; the pool's version
    increments by one; issued_count increases by one; the pool's price_cents is
    snapshotted onto the pass's own price_cents; and the pool's price_cents is
    debited from the member's store_credit_cents."
    PRD §3.6: "available_quota is total_quota minus issued_count, floored at zero."

    Design: Corner/calculations/permit_quota_decrements_on_issue
    """
    member = new_member(credit=5000)
    alloc = new_permit_allocation(total_quota=3, price_cents=2000, park_name="Olympic")
    pass_ = issue_permit(member, alloc, "2026-08-15T00:00:00Z")
    alloc_after = validate_success(api.get_permit_allocation(alloc["id"], STAFF), 200)
    assert alloc_after["issued_count"] == 1
    assert alloc_after["available_quota"] == 2
    assert pass_["price_cents"] == 2000


# ─── Queue-B state_machines / permit_pass_expires_after_clock_advances ─────

def test_permit_pass_expires_after_clock_advances(api):
    """PRD §2.9: "Whenever the clock is advanced, any PermitPass whose entry_date
    plus one day is strictly earlier than the new clock value transitions from ISSUED
    to EXPIRED".

    Entry 2026-08-10; advancing the clock to 2026-08-12 (past entry_date + 1 day)
    expires the pass.

    Design: Corner/state_machines/permit_pass_expires_after_clock_advances
    """
    member = new_member(credit=5000)
    alloc = new_permit_allocation(total_quota=5, price_cents=2000, park_name="Rainier")
    pass_ = issue_permit(member, alloc, "2026-08-10T00:00:00Z")
    set_clock("2026-08-12T00:00:00Z")
    pass_after = validate_success(api.get_permit_pass(pass_["id"], STAFF), 200)
    assert pass_after["status"] == "EXPIRED"


# ─── Queue-B validations / permit_rejected_when_insufficient_store_credit ──

def test_permit_rejected_when_insufficient_store_credit(api):
    """PRD §3.6: "to the member's store_credit_cents being at least the pool's
    price_cents (else ERR_INSUFFICIENT_STORE_CREDIT)."

    500 credit against a 2000 permit (within season, quota available) is rejected.

    Design: Corner/validations/permit_rejected_when_insufficient_store_credit
    """
    member = new_member(credit=500)
    alloc = new_permit_allocation(total_quota=2, price_cents=2000, park_name="Baker")
    res = _issue_expecting_error(api, member, alloc, "2026-08-12T00:00:00Z")
    validate_error(res, ApiErrorId.ERR_INSUFFICIENT_STORE_CREDIT.value)
