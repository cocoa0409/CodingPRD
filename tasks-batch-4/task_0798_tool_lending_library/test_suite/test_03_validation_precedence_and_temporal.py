"""Validation precedence, cross-entity state dependencies, and temporal overlap.

Difficulty queue A: priority_pair_validation_conflict, cross_entity_state_dependency,
resource_temporal_overlap, boundary_precision_check (empty candidate pool).
"""
from test_helpers import (
    create_member, create_item, add_copy, set_clock, ops_run, checkout,
    return_loan, create_reservation, create_ticket, get_member, get_item,
    get_copy, get_reservation, item_version,
    create_loan_payload, create_reservation_payload, create_ticket_payload,
    api_client, validate_error, TEST_USERS, make_member_headers,
)

COORD = TEST_USERS["coordinator_headers"]


# =========================================================================== #
# Difficulty/priority_pair_validation_conflict/checkout_member_suspended_beats_balance_limit
# =========================================================================== #
def _suspended_with_balance_and_target_item():
    member = create_member()
    item1 = create_item(name="Auger", category="OUTDOOR", replacement_value_cents=12345,
                        loan_period_days=7, daily_late_fee_cents=100)
    copy1 = add_copy(item1["id"], asset_tag="AU-1", acquired_on="2024-03-01T00:00:00Z")
    item2 = create_item(name="Mixer", category="KITCHEN", replacement_value_cents=4000,
                        loan_period_days=14, daily_late_fee_cents=50)
    copy2 = add_copy(item2["id"], asset_tag="MX-1", acquired_on="2025-01-01T00:00:00Z")
    set_clock("2026-03-13T00:00:00Z")
    loan1 = checkout(member["id"], copy1["id"], item1["id"])
    return_loan(loan1["id"], "MAJOR_DAMAGE")  # -> 9875 fee -> SUSPENDED, balance 9875
    return member, item2, copy2


def test_checkout_suspended_member_returns_member_not_active(api):
    """A SUSPENDED member with a high balance fails checkout; the member-active
    (state) check is ordered before the balance (fiscal) check, so the reported
    error is ERR_MEMBER_NOT_ACTIVE.

    PRD §3.4: "Among the checkout guards the order is: member-active state, then
    copy availability, then the loan-limit quota, then the fiscal balance check,
    and finally the stale-version concurrency check that carries
    `ERR_STALE_VERSION`."
    PRD §3.1: "a member who is `SUSPENDED` or `EXPIRED` causes the request to be
    rejected with `ERR_MEMBER_NOT_ACTIVE` (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/checkout_member_suspended_beats_balance_limit
    """
    _m, item2, copy2 = _suspended_with_balance_and_target_item()
    payload = create_loan_payload(_m["id"], copy2["id"], item_version(item2["id"]))
    res = api_client.create_loan(payload, COORD)
    validate_error(res, "ERR_MEMBER_NOT_ACTIVE")


def test_checkout_state_error_masks_balance_error(api):
    """The member is genuinely both suspended and over the balance threshold, yet
    only the state error surfaces (state masks fiscal).

    PRD §3.4: "Among the checkout guards the order is: member-active state, then
    copy availability, then the loan-limit quota, then the fiscal balance check,
    and finally the stale-version concurrency check that carries
    `ERR_STALE_VERSION`."

    Design: Difficulty/priority_pair_validation_conflict/checkout_member_suspended_beats_balance_limit
    """
    member, item2, copy2 = _suspended_with_balance_and_target_item()
    got = get_member(member["id"])
    assert got["status"] == "SUSPENDED"
    assert got["outstanding_balance_cents"] >= 2000
    payload = create_loan_payload(member["id"], copy2["id"], item_version(item2["id"]))
    res = api_client.create_loan(payload, COORD)
    validate_error(res, "ERR_MEMBER_NOT_ACTIVE")


# =========================================================================== #
# Difficulty/priority_pair_validation_conflict/checkout_copy_unavailable_beats_loan_limit
# =========================================================================== #
def _at_loan_limit_with_bad_copy():
    member = create_member(max_active_loans=1)
    item = create_item(name="Sander", category="TOOL", replacement_value_cents=7000,
                       loan_period_days=7, daily_late_fee_cents=100)
    copy_a = add_copy(item["id"], asset_tag="SA-1", acquired_on="2025-01-01T00:00:00Z")
    copy_b = add_copy(item["id"], asset_tag="SA-2", acquired_on="2025-01-01T00:00:00Z")
    set_clock("2026-03-01T00:00:00Z")
    create_ticket(copy_b["id"], reason="INSPECTION")  # immediate -> NEEDS_MAINTENANCE
    checkout(member["id"], copy_a["id"], item["id"])  # member now at max_active_loans=1
    return member, item, copy_b


def test_checkout_copy_unavailable_returns_copy_not_available(api):
    """At the loan limit AND checking out a non-GOOD copy, the copy-availability
    (safety) check is ordered before the loan-limit quota, so the error is
    ERR_COPY_NOT_AVAILABLE.

    PRD §3.4: "The chosen copy must be lendable — either `AVAILABLE`, or
    `RESERVED` to this member's own reservation — and `GOOD` on the condition
    axis; a copy that is otherwise reserved, on loan, or not in good condition is
    rejected with `ERR_COPY_NOT_AVAILABLE` (HTTP 409)."
    PRD §3.4: "Among the checkout guards the order is: member-active state, then
    copy availability, then the loan-limit quota, then the fiscal balance check,
    and finally the stale-version concurrency check that carries
    `ERR_STALE_VERSION`."

    Design: Difficulty/priority_pair_validation_conflict/checkout_copy_unavailable_beats_loan_limit
    """
    member, item, copy_b = _at_loan_limit_with_bad_copy()
    payload = create_loan_payload(member["id"], copy_b["id"], item_version(item["id"]))
    res = api_client.create_loan(payload, COORD)
    validate_error(res, "ERR_COPY_NOT_AVAILABLE")


def test_checkout_copy_unavailable_creates_no_second_loan(api):
    """The rejected checkout leaves the member with only their one existing loan.

    PRD §3.4: "The chosen copy must be lendable — either `AVAILABLE`, or
    `RESERVED` to this member's own reservation — and `GOOD` on the condition
    axis; a copy that is otherwise reserved, on loan, or not in good condition is
    rejected with `ERR_COPY_NOT_AVAILABLE` (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/checkout_copy_unavailable_beats_loan_limit
    """
    member, item, copy_b = _at_loan_limit_with_bad_copy()
    payload = create_loan_payload(member["id"], copy_b["id"], item_version(item["id"]))
    api_client.create_loan(payload, COORD)
    body = api_client.list_loans(COORD, params={"member_id": member["id"], "limit": 100}).json()
    assert body["meta"]["total_count"] == 1, "no second loan should be created"


# =========================================================================== #
# Difficulty/boundary_precision_check/reserve_empty_candidate_pool_boundary
# =========================================================================== #
def _single_copy_on_loan():
    m1 = create_member(name="Mo")
    m2 = create_member(name="Ned")
    item = create_item(name="Kettle", category="KITCHEN", replacement_value_cents=3000,
                       loan_period_days=14, daily_late_fee_cents=50)
    copy = add_copy(item["id"], asset_tag="KT-1", acquired_on="2025-01-01T00:00:00Z")
    set_clock("2026-03-01T00:00:00Z")
    checkout(m1["id"], copy["id"], item["id"])  # ON_LOAN, no scheduled return
    return m1, m2, item, copy


def test_reserve_with_empty_candidate_pool_rejected(api):
    """The item's only copy is ON_LOAN, so the free-copy candidate set is empty and
    the reservation is rejected with ERR_NO_COPY_AVAILABLE.

    PRD §3.3: "First, the item must have at least one serviceable copy free across
    the requested window; if the candidate set is empty, the request is rejected
    with `ERR_NO_COPY_AVAILABLE` (HTTP 409)."

    Design: Difficulty/boundary_precision_check/reserve_empty_candidate_pool_boundary
    """
    _m1, m2, item, _copy = _single_copy_on_loan()
    payload = create_reservation_payload(m2["id"], item["id"],
                                         "2026-04-01T00:00:00Z", "2026-04-03T00:00:00Z")
    res = api_client.create_reservation(payload, make_member_headers(m2["id"]))
    validate_error(res, "ERR_NO_COPY_AVAILABLE")


def test_reserve_empty_pool_has_zero_available_copies(api):
    """The empty candidate set corresponds to available_copies_count == 0 on the
    item, and reserving still fails.

    PRD §3.3: "First, the item must have at least one serviceable copy free across
    the requested window; if the candidate set is empty, the request is rejected
    with `ERR_NO_COPY_AVAILABLE` (HTTP 409)."

    Design: Difficulty/boundary_precision_check/reserve_empty_candidate_pool_boundary
    """
    _m1, m2, item, _copy = _single_copy_on_loan()
    assert get_item(item["id"])["available_copies_count"] == 0
    payload = create_reservation_payload(m2["id"], item["id"],
                                         "2026-04-01T00:00:00Z", "2026-04-03T00:00:00Z")
    res = api_client.create_reservation(payload, make_member_headers(m2["id"]))
    validate_error(res, "ERR_NO_COPY_AVAILABLE")


# =========================================================================== #
# Difficulty/cross_entity_state_dependency/checkout_depends_on_member_active
# =========================================================================== #
def _expired_member_with_available_copy():
    member = create_member(membership_expires_at="2026-03-05T00:00:00Z")
    item = create_item(name="Grill", category="OUTDOOR", replacement_value_cents=9000,
                       loan_period_days=7, daily_late_fee_cents=100)
    copy = add_copy(item["id"], asset_tag="G-1", acquired_on="2025-01-01T00:00:00Z")
    set_clock("2026-03-06T00:00:00Z")
    ops_run()  # membership expiry fires
    return member, item, copy


def test_membership_expires_via_ops_run(api):
    """Housekeeping past membership_expires_at moves the member to EXPIRED.

    PRD §3.1: "During housekeeping, any member — whether `ACTIVE` or `SUSPENDED` —
    whose `membership_expires_at` instant is at or before the current logical
    clock transitions to `EXPIRED`, which is terminal."

    Design: Difficulty/cross_entity_state_dependency/checkout_depends_on_member_active
    """
    member, _item, _copy = _expired_member_with_available_copy()
    assert get_member(member["id"])["status"] == "EXPIRED"


def test_checkout_gated_on_member_active_state(api):
    """With the member EXPIRED, checkout is refused with ERR_MEMBER_NOT_ACTIVE even
    though the copy is AVAILABLE and GOOD (Loan depends on Member state).

    PRD §3.1: "Wherever an operation requires the acting or target member to be in
    good standing — reserving, checking out, joining a waitlist, or renewing — a
    member who is `SUSPENDED` or `EXPIRED` causes the request to be rejected with
    `ERR_MEMBER_NOT_ACTIVE` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/checkout_depends_on_member_active
    """
    member, item, copy = _expired_member_with_available_copy()
    payload = create_loan_payload(member["id"], copy["id"], item_version(item["id"]))
    res = api_client.create_loan(payload, COORD)
    validate_error(res, "ERR_MEMBER_NOT_ACTIVE")


# =========================================================================== #
# Difficulty/cross_entity_state_dependency/reserve_depends_on_copy_condition
# =========================================================================== #
def _item_copy_needs_maintenance():
    member = create_member()
    item = create_item(name="Pump", category="TOOL", replacement_value_cents=5000,
                       loan_period_days=7, daily_late_fee_cents=100)
    copy = add_copy(item["id"], asset_tag="P-1", acquired_on="2025-01-01T00:00:00Z")
    set_clock("2026-03-01T00:00:00Z")
    create_ticket(copy["id"], reason="ROUTINE")  # immediate -> NEEDS_MAINTENANCE
    return member, item, copy


def test_reserve_gated_on_copy_condition(api):
    """The item's only copy is NEEDS_MAINTENANCE (not GOOD), so the free-copy set is
    empty and reservation is rejected with ERR_NO_COPY_AVAILABLE (Reservation
    depends on ItemCopy condition).

    PRD §3.3: "it picks a serviceable copy that is `GOOD` and free across the
    requested window and records its identifier on the reservation's
    server-assigned `copy_id`."
    PRD §3.3: "First, the item must have at least one serviceable copy free across
    the requested window; if the candidate set is empty, the request is rejected
    with `ERR_NO_COPY_AVAILABLE` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/reserve_depends_on_copy_condition
    """
    member, item, _copy = _item_copy_needs_maintenance()
    payload = create_reservation_payload(member["id"], item["id"],
                                         "2026-04-01T00:00:00Z", "2026-04-03T00:00:00Z")
    res = api_client.create_reservation(payload, make_member_headers(member["id"]))
    validate_error(res, "ERR_NO_COPY_AVAILABLE")


def test_reserve_needs_maintenance_copy_condition_confirmed(api):
    """The copy is confirmed NEEDS_MAINTENANCE and the reservation still fails.

    PRD §2.6: "The `condition_status` axis tracks physical condition and is one of
    `GOOD`, `NEEDS_MAINTENANCE`, `UNDER_MAINTENANCE`, or `RETIRED`."
    PRD §3.3: "First, the item must have at least one serviceable copy free across
    the requested window; if the candidate set is empty, the request is rejected
    with `ERR_NO_COPY_AVAILABLE` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/reserve_depends_on_copy_condition
    """
    member, item, copy = _item_copy_needs_maintenance()
    assert get_copy(copy["id"])["condition_status"] == "NEEDS_MAINTENANCE"
    payload = create_reservation_payload(member["id"], item["id"],
                                         "2026-04-01T00:00:00Z", "2026-04-03T00:00:00Z")
    res = api_client.create_reservation(payload, make_member_headers(member["id"]))
    validate_error(res, "ERR_NO_COPY_AVAILABLE")


# =========================================================================== #
# Difficulty/resource_temporal_overlap/reservation_window_aggregate_capacity_overlap
# =========================================================================== #
def _one_copy_with_existing_reservation():
    m1 = create_member(name="Qui")
    m2 = create_member(name="Rae")
    item = create_item(name="Canoe", category="OUTDOOR", replacement_value_cents=40000,
                       loan_period_days=3, daily_late_fee_cents=200)
    copy = add_copy(item["id"], asset_tag="C-1", acquired_on="2025-01-01T00:00:00Z")
    set_clock("2026-03-01T00:00:00Z")
    res1 = create_reservation(m1["id"], item["id"],
                              "2026-03-08T00:00:00Z", "2026-03-12T00:00:00Z")
    return m1, m2, item, copy, res1


def test_overlapping_window_exceeds_capacity_rejected(api):
    """A second reservation whose window overlaps the first exceeds the single
    copy's capacity and is rejected with ERR_ITEM_NO_CAPACITY_FOR_WINDOW.

    PRD §3.3: "Second, honoring the reservation must not push the item over its
    serviceable capacity at any instant within the half-open window
    `[window_start, window_end)` when aggregated against existing commitments
    that overlap that window; a window that would exceed capacity is rejected with
    `ERR_ITEM_NO_CAPACITY_FOR_WINDOW` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/reservation_window_aggregate_capacity_overlap
    """
    _m1, m2, item, _copy, _res1 = _one_copy_with_existing_reservation()
    payload = create_reservation_payload(m2["id"], item["id"],
                                         "2026-03-10T00:00:00Z", "2026-03-15T00:00:00Z")
    res = api_client.create_reservation(payload, make_member_headers(m2["id"]))
    validate_error(res, "ERR_ITEM_NO_CAPACITY_FOR_WINDOW")


def test_overlapping_window_leaves_existing_reservation_pending(api):
    """The rejected overlapping reservation does not disturb the existing PENDING
    reservation.

    PRD §3.3: "Second, honoring the reservation must not push the item over its
    serviceable capacity at any instant within the half-open window
    `[window_start, window_end)` when aggregated against existing commitments
    that overlap that window; a window that would exceed capacity is rejected with
    `ERR_ITEM_NO_CAPACITY_FOR_WINDOW` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/reservation_window_aggregate_capacity_overlap
    """
    _m1, m2, item, _copy, res1 = _one_copy_with_existing_reservation()
    payload = create_reservation_payload(m2["id"], item["id"],
                                         "2026-03-10T00:00:00Z", "2026-03-15T00:00:00Z")
    api_client.create_reservation(payload, make_member_headers(m2["id"]))
    assert get_reservation(res1["id"])["status"] == "PENDING"


# =========================================================================== #
# Difficulty/resource_temporal_overlap/maintenance_window_overlaps_loan_with_buffer
# =========================================================================== #
def _copy_on_loan_for_maintenance():
    member = create_member(name="Sam")
    item = create_item(name="Jack", category="TOOL", replacement_value_cents=6000,
                       loan_period_days=7, daily_late_fee_cents=100)
    copy = add_copy(item["id"], asset_tag="J-1", acquired_on="2025-01-01T00:00:00Z")
    set_clock("2026-03-01T00:00:00Z")
    checkout(member["id"], copy["id"], item["id"])  # active loan period 03-01..03-08
    return member, item, copy


def test_maintenance_window_overlapping_buffered_loan_rejected(api):
    """A maintenance window scheduled the day after the loan ends conflicts once the
    loan period is widened by the buffer, so it is rejected with
    ERR_MAINTENANCE_WINDOW_CONFLICT.

    PRD §3.8: "A planned maintenance window must not overlap the copy's active loan
    period, and the loan period is widened by a buffer of the configured buffer
    days on each side (a closed interval plus buffer); an overlapping window is
    rejected with `ERR_MAINTENANCE_WINDOW_CONFLICT` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/maintenance_window_overlaps_loan_with_buffer
    """
    _m, _item, copy = _copy_on_loan_for_maintenance()
    payload = create_ticket_payload(copy["id"], reason="ROUTINE",
                                    scheduled_start="2026-03-09T00:00:00Z",
                                    scheduled_end="2026-03-11T00:00:00Z")
    res = api_client.create_ticket(payload, COORD)
    validate_error(res, "ERR_MAINTENANCE_WINDOW_CONFLICT")


def test_maintenance_window_conflict_persists_no_ticket(api):
    """The conflicting maintenance ticket is not persisted.

    PRD §3.8: "A planned maintenance window must not overlap the copy's active loan
    period, and the loan period is widened by a buffer of the configured buffer
    days on each side (a closed interval plus buffer); an overlapping window is
    rejected with `ERR_MAINTENANCE_WINDOW_CONFLICT` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/maintenance_window_overlaps_loan_with_buffer
    """
    _m, _item, copy = _copy_on_loan_for_maintenance()
    payload = create_ticket_payload(copy["id"], reason="ROUTINE",
                                    scheduled_start="2026-03-09T00:00:00Z",
                                    scheduled_end="2026-03-11T00:00:00Z")
    api_client.create_ticket(payload, COORD)
    body = api_client.list_tickets(COORD, params={"copy_id": copy["id"], "limit": 100}).json()
    assert body["meta"]["total_count"] == 0, "no maintenance ticket should be persisted"
