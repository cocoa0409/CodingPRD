"""Role-based access control, ownership / assignment checks, missing auth, and optimistic
concurrency (stale-version) on event-block booking and package purchase.

Queue B (Corner): section `rbac`; section `cross_cutting_complexity_layers` (OCC instances).
"""
import pytest
from test_helpers import (
    validate_success, validate_error,
    create_member, create_stylist, create_style_service, create_chair,
    setup_base_scenario, setup_completed_standalone,
    setup_event_block_with_two_appointments, current_block_version,
    make_member_headers, make_stylist_headers, TEST_USERS,
)

FD = TEST_USERS["front_desk_headers"]
FM = TEST_USERS["finance_manager_headers"]


# ─── Queue B: RBAC role denial ────────────────────────────────────────────────

def test_member_cannot_create_style_service(api):
    """PRD §4: "| POST | `/style-services` | Create a style menu item | FrontDesk |"
    PRD §2.1: "When a well-authenticated caller attempts an operation their role is not
    permitted to perform, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Design: Corner/rbac/rbac_member_cannot_create_style_service
    """
    member = create_member(full_name="M")
    res = api.create_style_service(
        {"name": "Hack", "base_duration_minutes": 45, "base_price_cents": 6000},
        make_member_headers(member["id"]))
    validate_error(res, "ERR_FORBIDDEN_ROLE", expected_status=403)


def test_frontdesk_cannot_settle(api):
    """PRD §4: "| POST | `/appointments/{id}/settle` | Settle a completed appointment |
    FinanceManager |"
    PRD §2.1: "When a well-authenticated caller attempts an operation their role is not
    permitted to perform, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Design: Corner/rbac/rbac_frontdesk_cannot_settle
    """
    scenario, appt = setup_completed_standalone()
    res = api.settle_appointment(appt["id"], {"tip_cents": 0}, FD)
    validate_error(res, "ERR_FORBIDDEN_ROLE", expected_status=403)


def test_member_cancel_other_members_appointment_not_owner(api):
    """PRD §2.1: "A `Member` acting on an appointment that is not theirs is rejected with
    `ERR_NOT_OWNER` (HTTP 403) ..."
    PRD §3.9: "when the actor is a `Member`, their `X-User-ID` must equal the appointment's
    `member_id` (otherwise `ERR_NOT_OWNER`, 403)."

    Design: Corner/rbac/rbac_member_cancel_other_member_appt_not_owner
    """
    service = create_style_service()
    chair = create_chair()
    stylist = create_stylist(full_name="Sam")
    mem_a = create_member(full_name="Member A")
    mem_b = create_member(full_name="Member B")
    appt = validate_success(api.create_appointment(
        {"member_id": mem_a["id"], "chair_id": chair["id"], "stylist_id": stylist["id"],
         "style_service_id": service["id"], "start_minute": 600, "payment_method": "CREDIT"},
        make_member_headers(mem_a["id"])), 201)
    res = api.cancel_appointment(appt["id"], make_member_headers(mem_b["id"]))
    validate_error(res, "ERR_NOT_OWNER", expected_status=403)


def test_other_stylist_cannot_start_appointment(api):
    """PRD §2.1: "a `Stylist` attempting to start or complete an appointment to which they
    are not assigned is rejected with `ERR_NOT_ASSIGNED_STYLIST` (HTTP 403)."
    PRD §3.7: "the acting stylist's `X-User-ID` to equal the appointment's `stylist_id`
    (otherwise `ERR_NOT_ASSIGNED_STYLIST`, 403)."

    Design: Corner/rbac/rbac_other_stylist_cannot_start_appt
    """
    service = create_style_service()
    chair = create_chair()
    s1 = create_stylist(full_name="S1")
    s2 = create_stylist(full_name="S2")
    member = create_member(full_name="M")
    appt = validate_success(api.create_appointment(
        {"member_id": member["id"], "chair_id": chair["id"], "stylist_id": s1["id"],
         "style_service_id": service["id"], "start_minute": 600, "payment_method": "CREDIT"},
        FD), 201)
    validate_success(api.check_in_appointment(appt["id"], {"arrival_status": "ON_TIME"}, FD), 200)
    res = api.start_appointment(appt["id"], make_stylist_headers(s2["id"]))
    validate_error(res, "ERR_NOT_ASSIGNED_STYLIST", expected_status=403)


def test_missing_auth_header_rejected(api):
    """PRD §2.1: "Every request other than the health probe must carry two HTTP headers:
    `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in
    which they act. If either header is missing or malformed, the request is rejected with
    `ERR_MISSING_AUTH_CONTEXT` (HTTP 401)."

    Design: Corner/rbac/rbac_missing_auth_header_rejected
    """
    res = api.create_style_service(
        {"name": "NoAuth", "base_duration_minutes": 45, "base_price_cents": 6000},
        {})  # no X-User-ID / X-User-Role headers
    validate_error(res, "ERR_MISSING_AUTH_CONTEXT", expected_status=401)


# ─── Queue B: OCC stale-version (event-block booking, package purchase) ───────

def test_book_into_stale_event_block_rejected(api):
    """PRD §2.8: "Booking an appointment into an event block requires
    `expected_event_block_version` to match that event block's current `version`. If a
    prior writer has reopened or cancelled the block — legitimately superseding its
    reserved chairs and window — the client's view is stale and the booking is rejected
    with `ERR_STALE_VERSION` (HTTP 412)."

    A first booking into the block bumps its version; a second booking still carrying the
    original (now stale) expected_event_block_version is rejected.

    Design: Corner/cross_cutting_complexity_layers/occ_book_into_stale_event_block_rejected
    """
    service = create_style_service()
    chair_a = create_chair(label="Chair A")
    chair_b = create_chair(label="Chair B")
    s1 = create_stylist(full_name="S1")
    s2 = create_stylist(full_name="S2")
    org = create_member(full_name="Org")
    guest = create_member(full_name="G2")
    block = validate_success(api.create_event_block(
        {"organizer_member_id": org["id"], "block_type": "GROUP",
         "window_start_minute": 540, "window_end_minute": 900,
         "reserved_chair_ids": [chair_a["id"], chair_b["id"]], "party_size": 3}, FD), 201)
    stale_version = block["version"]
    # First booking bumps the block version.
    validate_success(api.create_appointment(
        {"member_id": org["id"], "chair_id": chair_a["id"], "stylist_id": s1["id"],
         "style_service_id": service["id"], "start_minute": 600, "payment_method": "CREDIT",
         "event_block_id": block["id"], "expected_event_block_version": stale_version}, FD), 201)
    # Second booking still carrying the stale version is rejected.
    res = api.create_appointment(
        {"member_id": guest["id"], "chair_id": chair_b["id"], "stylist_id": s2["id"],
         "style_service_id": service["id"], "start_minute": 600, "payment_method": "CREDIT",
         "event_block_id": block["id"], "expected_event_block_version": stale_version}, FD)
    validate_error(res, "ERR_STALE_VERSION", expected_status=412)


def test_package_purchase_stale_member_rejected(api):
    """PRD §2.8: "Purchasing a prepaid credit package requires `expected_member_version` to
    match the target member's current `version`. If another writer has granted credits,
    refunded a prior package, or reinstated the member since the client last read it — each
    of which legitimately changes the credit or prepay ledger — the purchase is rejected
    with `ERR_STALE_VERSION` (HTTP 412)."

    A prepay top-up advances the member version; a package purchase still carrying the
    pre-top-up version is rejected.

    Design: Corner/cross_cutting_complexity_layers/occ_package_purchase_stale_member_rejected
    """
    member = create_member(full_name="Pkg Stale")
    stale_version = member["version"]
    validate_success(api.prepay_member(member["id"], {"amount_cents": 1000}, FD), 200)
    res = api.create_package_purchase(
        {"member_id": member["id"], "credits_purchased": 3, "price_cents": 15000,
         "expected_member_version": stale_version}, FD)
    validate_error(res, "ERR_STALE_VERSION", expected_status=412)
