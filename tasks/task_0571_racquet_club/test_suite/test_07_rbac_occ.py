"""Role-based access control and optimistic-concurrency (OCC) guards."""
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    setup_booking_scenario, setup_change_plan_occ, setup_reschedule_occ,
    make_member, make_reservation, create_court_payload, create_reservation_payload,
    make_member_headers, TEST_USERS,
)

FD = TEST_USERS["frontdesk_headers"]


# ─── Corner: rbac_member_cannot_create_court ──────────────────────────
def test_member_cannot_create_court():
    """PRD §2.1: "When a well-authenticated caller attempts an operation their role is
    not permitted to perform — or an ownership-scoped role acts on a resource it does
    not own — the request is rejected with ERR_UNAUTHORIZED (HTTP 403)."

    Design: Corner/rbac/rbac_member_cannot_create_court
    """
    member = make_member()
    headers = make_member_headers(member["id"])
    res = api_client.create_court(
        create_court_payload(name="Sneaky"), headers)
    validate_error(res, "ERR_UNAUTHORIZED")


# ─── Corner: rbac_member_cannot_mark_no_show ──────────────────────────
def test_member_cannot_mark_no_show():
    """PRD §2.1: "When a well-authenticated caller attempts an operation their role is
    not permitted to perform — or an ownership-scoped role acts on a resource it does
    not own — the request is rejected with ERR_UNAUTHORIZED (HTTP 403)."

    Design: Corner/rbac/rbac_member_cannot_mark_no_show
    """
    s = setup_booking_scenario()
    res = make_reservation(s["court"]["id"], s["member"]["id"],
                           "2026-05-05T10:00:00Z", "2026-05-05T11:00:00Z")
    headers = make_member_headers(s["member"]["id"])
    resp = api_client.mark_no_show(res["id"], headers)
    validate_error(resp, "ERR_UNAUTHORIZED")


# ─── Corner: rbac_member_cannot_cancel_others_reservation ─────────────
def test_member_cannot_cancel_another_members_reservation():
    """PRD §2.1: "A member may therefore book, check in, cancel, and reschedule only
    their own reservations, enroll only themselves, register only themselves as a
    competitor, request stringing only for themselves, and freeze, unfreeze, change, or
    cancel only their own subscription."

    Design: Corner/rbac/rbac_member_cannot_cancel_others_reservation
    """
    s = setup_booking_scenario()  # member B holds the reservation
    res = make_reservation(s["court"]["id"], s["member"]["id"],
                           "2026-05-05T10:00:00Z", "2026-05-05T11:00:00Z")
    member_a = make_member()
    headers_a = make_member_headers(member_a["id"])
    resp = api_client.cancel_reservation(res["id"], headers_a)
    validate_error(resp, "ERR_UNAUTHORIZED")
    after = validate_success(api_client.get_reservation(res["id"], FD), 200)
    assert after["status"] == "BOOKED"


# ─── Corner: rbac_member_books_own_reservation_allowed ────────────────
def test_member_books_own_reservation_allowed():
    """PRD §2.1: "When X-User-Role is Member, X-User-ID is the id of the acting Member;
    ownership checks on any resource that references a Member compare that resource's
    member foreign key (its member_id) to X-User-ID."

    Design: Corner/rbac/rbac_member_books_own_reservation_allowed
    """
    s = setup_booking_scenario()
    headers = make_member_headers(s["member"]["id"])
    res = get_success_data(api_client.create_reservation(
        create_reservation_payload(s["court"]["id"], s["member"]["id"],
                                   "2026-05-05T10:00:00Z", "2026-05-05T11:00:00Z"), headers))
    assert res["status"] == "BOOKED"
    assert res["member_id"] == s["member"]["id"]


# ─── Corner: occ_subscription_change_plan_stale_version_conflict ──────
def test_change_plan_with_stale_version_rejected():
    """PRD §2.7: "a second change carrying a stale version is not blocked by any state
    check — only by the OCC check. A prior plan change or a renewal reconciliation
    silently advances the subscription's version, so if the version the client last
    observed no longer matches, the change is rejected with ERR_STALE_VERSION (HTTP
    412)."

    Design: Corner/cross_cutting/occ_subscription_change_plan_stale_version_conflict
    """
    ctx = setup_change_plan_occ()
    get_success_data(api_client.change_plan(
        ctx["sub"]["id"],
        {"plan_id": ctx["plan_b"]["id"], "expected_subscription_version": ctx["v0"]}, FD))
    res = api_client.change_plan(
        ctx["sub"]["id"],
        {"plan_id": ctx["plan_a"]["id"], "expected_subscription_version": ctx["v0"]}, FD)
    validate_error(res, "ERR_STALE_VERSION")
    after = validate_success(api_client.get_subscription(ctx["sub"]["id"], FD), 200)
    assert after["plan_id"] == ctx["plan_b"]["id"]


# ─── Corner: occ_reservation_reschedule_stale_version_conflict ────────
def test_reschedule_with_stale_version_rejected():
    """PRD §2.7: "rescheduling a reservation requires expected_reservation_version to
    equal the reservation's current version; because a booked reservation may be moved
    more than once, a second reschedule carrying a stale version is rejected purely by
    the OCC check with ERR_STALE_VERSION (HTTP 412), never by a state precondition."

    Design: Corner/cross_cutting/occ_reservation_reschedule_stale_version_conflict
    """
    ctx = setup_reschedule_occ()
    get_success_data(api_client.reschedule_reservation(
        ctx["reservation"]["id"],
        {"start_time": "2026-05-14T14:00:00Z", "end_time": "2026-05-14T15:00:00Z",
         "expected_reservation_version": ctx["rv0"]}, FD))
    res = api_client.reschedule_reservation(
        ctx["reservation"]["id"],
        {"start_time": "2026-05-14T16:00:00Z", "end_time": "2026-05-14T17:00:00Z",
         "expected_reservation_version": ctx["rv0"]}, FD)
    validate_error(res, "ERR_STALE_VERSION")
