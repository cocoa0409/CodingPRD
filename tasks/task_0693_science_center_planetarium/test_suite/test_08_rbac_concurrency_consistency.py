"""Role-based access control, optimistic-concurrency stale-version rejections,
scheduled membership-expiry sweeps, and immediate seat consistency.

Queue B (Corner): sections rbac, cross_cutting_complexity_layers, consistency_model.
"""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    NO_AUTH_HEADERS,
    create_dome,
    create_open_show,
    create_membership,
    create_sponsor,
    create_hold,
)

ADMIN = TEST_USERS["facility_admin_headers"]
BOX_OFFICE = TEST_USERS["box_office_headers"]
GROUP_SALES = TEST_USERS["group_sales_headers"]
CLERK = TEST_USERS["membership_clerk_headers"]
DEV = TEST_USERS["development_officer_headers"]


# --- rbac ---

def test_missing_auth_headers_unauthenticated(api):
    """PRD §2.1: "If either header is absent, or if `X-User-Role` does not name a role
    the system recognizes, the request is rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/missing_headers_unauthenticated
    """
    resp = api.create_venue(
        {"name": "NoAuth", "venue_type": "DOME", "seated_capacity": 30}, NO_AUTH_HEADERS)
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value, expected_status=401)


def test_group_sales_cannot_create_show(api):
    """PRD §2.1: "When the headers are well-formed but the named role is not permitted
    to invoke the requested operation, the request is rejected with
    `ERR_FORBIDDEN_ROLE`."

    POST /shows is authorized only for BoxOfficeOperator; a GroupSalesAgent is
    forbidden.

    Design: Corner/rbac/groupsales_cannot_create_show
    """
    dome = create_dome(seated_capacity=30, name="Dome II")
    resp = api.create_show(
        {"venue_id": dome["id"], "title": "Nope", "starts_at": "2026-05-22T10:00:00Z",
         "ends_at": "2026-05-22T11:00:00Z", "base_price_cents": 1000}, GROUP_SALES)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value, expected_status=403)


def test_membership_clerk_cannot_create_sponsor(api):
    """PRD §2.1: "When the headers are well-formed but the named role is not permitted
    to invoke the requested operation, the request is rejected with
    `ERR_FORBIDDEN_ROLE`."

    POST /sponsors is authorized only for DevelopmentOfficer; a MembershipClerk is
    forbidden.

    Design: Corner/rbac/membershipclerk_cannot_create_sponsor
    """
    resp = api.create_sponsor(
        {"org_name": "X", "sponsor_kind": "DONOR", "pledged_cents": 1000}, CLERK)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value, expected_status=403)


# --- optimistic concurrency ---

def test_stale_show_version_hold_rejected(api):
    """PRD §2.6: "When a seat hold is created on a show, the request must carry
    `expected_show_version` equal to the target ShowEvent's current `version`. If
    another writer has advanced that version since the client last read the show (by
    creating a competing hold, for instance, which bumps both `seats_sold` and
    `version`), the create is rejected with `ERR_STALE_SHOW_VERSION` and HTTP 412".

    First hold advances the version; a second hold echoing the pre-hold version is
    stale.

    Design: Corner/cross_cutting_complexity_layers/occ_stale_show_version_rejected
    """
    show = create_open_show(seated_capacity=40, base_price_cents=1000, title="Stale")
    stale_version = show["version"]
    create_hold(show["id"], party_size=1, expected_show_version=stale_version)

    resp = api.create_show_booking(
        {"show_event_id": show["id"], "party_size": 1, "expected_show_version": stale_version},
        BOX_OFFICE)
    validate_error(resp, ApiErrorId.ERR_STALE_SHOW_VERSION.value, expected_status=412)


def test_stale_sponsor_version_contribution_rejected(api):
    """PRD §2.6: "When a contribution is recorded against a sponsor, the request must
    carry `expected_sponsor_version` equal to the target Sponsor's current `version`.
    If another writer has already recorded an installment that advanced the sponsor
    toward fulfillment, the create is rejected with `ERR_STALE_SPONSOR_VERSION` and
    HTTP 412."

    First contribution advances the sponsor version; a second contribution echoing the
    pre-contribution version is stale.

    Design: Corner/cross_cutting_complexity_layers/occ_stale_sponsor_version_rejected
    """
    sponsor = create_sponsor(pledged_cents=10000, sponsor_kind="SPONSOR", org_name="StaleSp")
    stale_version = sponsor["version"]
    validate_success(api.create_contribution(
        sponsor["id"], {"amount_cents": 2000, "expected_sponsor_version": stale_version}, DEV),
        expected_status=201)

    resp = api.create_contribution(
        sponsor["id"], {"amount_cents": 2000, "expected_sponsor_version": stale_version}, DEV)
    validate_error(resp, ApiErrorId.ERR_STALE_SPONSOR_VERSION.value, expected_status=412)


# --- scheduled actions ---

def test_membership_expiry_sweep_transitions_active_to_expired(api):
    """PRD §2.5: "every membership that is `ACTIVE` and whose expiry instant the clock
    has reached or passed is moved to `EXPIRED`."
    PRD §3.2: "Once the logical clock reaches or passes `expires_at`, the next sweep
    moves an `ACTIVE` card to `EXPIRED` (Section 2.5)."

    Activate at default clock 2026-03-01 (expires 2027-03-01), advance past expiry,
    run sweep -> EXPIRED.

    Design: Corner/cross_cutting_complexity_layers/scheduled_membership_expiry_sweep
    """
    member = create_membership(tier="INDIVIDUAL", home_zip="90210", party_size=1,
                               primary_member_name="Exp")
    validate_success(api.activate_membership(member["id"], {"dues_cents": 6000}, CLERK))

    validate_success(api.set_clock("2027-03-02T00:00:00Z", ADMIN))
    validate_success(api.run_sweeps(ADMIN))

    after = validate_success(api.get_membership(member["id"], CLERK))
    assert after["status"] == "EXPIRED", f"expected EXPIRED after sweep, got {after['status']}"


# --- consistency model ---

def test_hold_seats_visible_immediately(api):
    """PRD §3.4: "A successful hold records `held_at` as the current logical-clock
    instant, snapshots the price (below), reserves the seats by recomputing the show's
    `seats_sold`, bubbles the show to `SOLD_OUT` if it just filled, and increments the
    show's `version`."

    After creating a 1-seat hold, a subsequent GET of the show shows seats_sold==1.

    Design: Corner/consistency_model/immediate_seats_visible_in_same_response
    """
    show = create_open_show(seated_capacity=10, base_price_cents=1000, title="Imm")
    create_hold(show["id"], party_size=1)

    fetched = validate_success(api.get_show(show["id"], BOX_OFFICE))
    assert fetched["seats_sold"] == 1, f"expected seats_sold 1, got {fetched['seats_sold']}"
