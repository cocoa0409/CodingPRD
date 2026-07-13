"""Body/state validations, RBAC denials, and optimistic concurrency at checkout.

Corner queue B: validations, rbac, cross_cutting_complexity_layers
(optimistic_concurrency).
"""
from test_helpers import (
    api_client, validate_success, validate_error,
    create_member, create_volunteer, create_item, add_copy, set_clock, checkout,
    create_reservation, item_version,
    create_reservation_payload, create_hold_payload, create_item_payload,
    create_loan_payload,
    TEST_USERS, make_member_headers, make_volunteer_headers,
)

COORD = TEST_USERS["coordinator_headers"]


# =========================================================================== #
# Corner/validations/reserve_start_after_end_returns_invalid_window
# =========================================================================== #
def test_reserve_start_not_before_end_rejected(api):
    """A reservation whose window_start is not strictly before window_end is
    rejected with ERR_INVALID_WINDOW.

    PRD §3.3: "The window must be well-formed: if `window_start` is not strictly
    before `window_end`, the request is rejected with `ERR_INVALID_WINDOW` (HTTP
    400)."

    Design: Corner/validations/reserve_start_after_end_returns_invalid_window
    """
    member = create_member()
    item = create_item(name="Rake", category="OUTDOOR", replacement_value_cents=1500,
                       loan_period_days=3, daily_late_fee_cents=200)
    add_copy(item["id"], asset_tag="RK-1")
    payload = create_reservation_payload(member["id"], item["id"],
                                         "2026-04-05T00:00:00Z", "2026-04-01T00:00:00Z")
    res = api_client.create_reservation(payload, make_member_headers(member["id"]))
    validate_error(res, "ERR_INVALID_WINDOW")


# =========================================================================== #
# Corner/validations/join_waitlist_when_copy_available_rejected
# =========================================================================== #
def test_join_waitlist_with_available_copy_rejected(api):
    """Joining a waitlist while a lendable copy exists is refused with
    ERR_COPY_AVAILABLE_NO_HOLD.

    PRD §3.7: "The item must currently have zero `AVAILABLE` serviceable copies —
    if a lendable copy exists right now, joining is refused with
    `ERR_COPY_AVAILABLE_NO_HOLD` (HTTP 409), since the member should simply
    reserve or borrow it."

    Design: Corner/validations/join_waitlist_when_copy_available_rejected
    """
    member = create_member()
    item = create_item(name="Torch", category="TOOL", replacement_value_cents=2000,
                       loan_period_days=7, daily_late_fee_cents=100)
    add_copy(item["id"], asset_tag="TR-1")
    payload = create_hold_payload(member["id"], item["id"])
    res = api_client.create_hold(payload, make_member_headers(member["id"]))
    validate_error(res, "ERR_COPY_AVAILABLE_NO_HOLD")


# =========================================================================== #
# Corner/validations/duplicate_hold_rejected
# =========================================================================== #
def test_duplicate_hold_rejected(api):
    """A member already holding a PENDING hold on an item cannot join again —
    ERR_DUPLICATE_HOLD.

    PRD §3.7: "And the member must not already hold a `PENDING` or `PROMOTED` hold
    on the same item; a second hold is rejected with `ERR_DUPLICATE_HOLD` (HTTP
    409)."

    Design: Corner/validations/duplicate_hold_rejected
    """
    m1 = create_member(name="Du1")
    m2 = create_member(name="Du2")
    item = create_item(name="Auger2", category="OUTDOOR", replacement_value_cents=8000,
                       loan_period_days=3, daily_late_fee_cents=200)
    copy = add_copy(item["id"], asset_tag="AG-1")
    set_clock("2026-03-01T00:00:00Z")
    checkout(m1["id"], copy["id"], item["id"])  # copy ON_LOAN -> 0 available
    first = api_client.create_hold(create_hold_payload(m2["id"], item["id"]),
                                   make_member_headers(m2["id"]))
    validate_success(first, 201)
    dup = api_client.create_hold(create_hold_payload(m2["id"], item["id"]),
                                 make_member_headers(m2["id"]))
    validate_error(dup, "ERR_DUPLICATE_HOLD")


# =========================================================================== #
# Corner/validations/renew_with_active_waitlist_rejected
# =========================================================================== #
def test_renew_blocked_by_active_waitlist(api):
    """Renewing a loan whose item has a PENDING hold is rejected with
    ERR_RENEWAL_BLOCKED_WAITLIST.

    PRD §3.4: "and there is no `PENDING` or `PROMOTED` hold waiting on the loan's
    item, since renewing would be unfair to those waiting (otherwise
    `ERR_RENEWAL_BLOCKED_WAITLIST`, HTTP 409)."

    Design: Corner/validations/renew_with_active_waitlist_rejected
    """
    m1 = create_member(name="Rn1")
    m2 = create_member(name="Rn2")
    item = create_item(name="Nailer", category="TOOL", replacement_value_cents=9000,
                       loan_period_days=7, daily_late_fee_cents=100, max_renewals=2)
    copy = add_copy(item["id"], asset_tag="N-1")
    set_clock("2026-03-01T00:00:00Z")
    loan = checkout(m1["id"], copy["id"], item["id"])
    validate_success(api_client.create_hold(create_hold_payload(m2["id"], item["id"]),
                                            make_member_headers(m2["id"])), 201)
    res = api_client.renew_loan(loan["id"], COORD)
    validate_error(res, "ERR_RENEWAL_BLOCKED_WAITLIST")


# =========================================================================== #
# Corner/rbac/member_cannot_create_item_unauthorized
# =========================================================================== #
def test_member_cannot_create_item(api):
    """A Member calling the Coordinator-exclusive create-item endpoint is rejected
    with ERR_UNAUTHORIZED.

    PRD §2.1: "If the headers are well-formed but the named role is not permitted
    to perform the requested operation, the request is rejected with
    `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/member_cannot_create_item_unauthorized
    """
    member = create_member(name="Mc")
    payload = create_item_payload(name="Sneaky", category="TOOL",
                                  replacement_value_cents=100, loan_period_days=7,
                                  daily_late_fee_cents=100)
    res = api_client.create_item(payload, make_member_headers(member["id"]))
    validate_error(res, "ERR_UNAUTHORIZED")


# =========================================================================== #
# Corner/rbac/member_cannot_cancel_others_reservation
# =========================================================================== #
def test_member_cannot_cancel_others_reservation(api):
    """A Member cancelling another member's reservation is rejected with
    ERR_FORBIDDEN_NOT_OWNER.

    PRD §2.1: "A member acting on a reservation cancel, a loan renew, a fee
    payment, or a hold may only touch resources whose `member_id` equals their own
    `X-User-ID`; a mismatch is rejected with `ERR_FORBIDDEN_NOT_OWNER` (HTTP 403)."

    Design: Corner/rbac/member_cannot_cancel_others_reservation
    """
    m1 = create_member(name="Ow1")
    m2 = create_member(name="Ow2")
    item = create_item(name="Waders", category="OUTDOOR", replacement_value_cents=5000,
                       loan_period_days=3, daily_late_fee_cents=200)
    add_copy(item["id"], asset_tag="WD-1")
    set_clock("2026-03-01T00:00:00Z")
    reservation = create_reservation(m1["id"], item["id"],
                                     "2026-04-01T00:00:00Z", "2026-04-03T00:00:00Z")
    res = api_client.cancel_reservation(reservation["id"], make_member_headers(m2["id"]))
    validate_error(res, "ERR_FORBIDDEN_NOT_OWNER")


# =========================================================================== #
# Corner/rbac/volunteer_entity_backed_checkout_succeeds
# =========================================================================== #
def test_volunteer_can_perform_checkout(api):
    """A Volunteer (X-User-ID = a Volunteer.id) may perform checkout and it
    succeeds (201, loan ACTIVE).

    PRD §2.1: "When `X-User-Role` is `Volunteer`, `X-User-ID` is the `id` of the
    acting `Volunteer` entity. At checkout the server records this identifier on
    the loan's `checked_out_by_volunteer_id` field for audit purposes only; ..."

    Design: Corner/rbac/volunteer_entity_backed_checkout_succeeds
    """
    volunteer = create_volunteer(name="Val", role_level="VOLUNTEER")
    member = create_member(name="Vm")
    item = create_item(name="Broom", category="KITCHEN", replacement_value_cents=1000,
                       loan_period_days=14, daily_late_fee_cents=50)
    copy = add_copy(item["id"], asset_tag="BR-1")
    set_clock("2026-03-01T00:00:00Z")
    payload = create_loan_payload(member["id"], copy["id"], item_version(item["id"]))
    loan = validate_success(
        api_client.create_loan(payload, make_volunteer_headers(volunteer["id"])), 201)
    assert loan["status"] == "ACTIVE"


# =========================================================================== #
# Corner/cross_cutting_complexity_layers/checkout_stale_item_version_conflict
# =========================================================================== #
def test_checkout_with_stale_item_version_rejected(api):
    """A second checkout carrying the pre-bump expected_item_version is rejected
    with ERR_STALE_VERSION after the first checkout advanced the item's version.

    PRD §2.8: "Before creating the loan, the server compares `expected_item_version`
    against the item's current `version`. If another writer has advanced the
    item's `version` since the client last read it — for example by consuming the
    last serviceable copy under the quota model — the client's view of which
    copies remain available is stale, and the checkout is rejected with
    `ERR_STALE_VERSION` (HTTP 412). A successful checkout increments the item's
    `version` by one."

    Design: Corner/cross_cutting_complexity_layers/checkout_stale_item_version_conflict
    """
    member = create_member(name="Occ")
    item = create_item(name="Jigsaw", category="TOOL", replacement_value_cents=8000,
                       loan_period_days=7, daily_late_fee_cents=100)
    copy_a = add_copy(item["id"], asset_tag="JS-1")
    copy_b = add_copy(item["id"], asset_tag="JS-2")
    set_clock("2026-03-01T00:00:00Z")
    stale_version = item_version(item["id"])
    validate_success(api_client.create_loan(
        create_loan_payload(member["id"], copy_a["id"], stale_version), COORD), 201)
    res = api_client.create_loan(
        create_loan_payload(member["id"], copy_b["id"], stale_version), COORD)
    validate_error(res, "ERR_STALE_VERSION")
