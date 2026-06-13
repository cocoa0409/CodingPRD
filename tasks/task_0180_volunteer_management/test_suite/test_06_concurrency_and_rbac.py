"""Optimistic concurrency, the no-show strike-limit threshold, and role/ownership
enforcement.

Queue B (Corner): cross_cutting_complexity_layers (OCC, rate-threshold), rbac.
"""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
)
from test_helpers.fixtures import (
    create_organization, create_volunteer, create_opportunity, create_shift,
    publish_opportunity, set_clock, get_shift, get_volunteer,
    create_signup, create_confirmed_signup, create_attended_signup,
    setup_approved_corporate_group, COMPLIANCE,
)
from test_helpers.test_users import TEST_USERS, make_volunteer_headers

COORD = TEST_USERS["shift_coordinator_headers"]


def test_group_allocate_stale_shift_version_rejected(api):
    """PRD §2.6: "Allocating a corporate group, which creates seat-occupying signups on
    the target shift, likewise requires `expected_shift_version` matching that shift's
    current `version`, with a mismatch rejected as `ERR_STALE_SHIFT_VERSION` at 412."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_shift_version_on_group_allocate
    """
    org, opp, shift, grp = setup_approved_corporate_group(requested_seats=2, capacity=10)
    # Read a version, then advance it via an individual signup so the read goes stale.
    stale = get_shift(shift["id"], headers=COORD)
    vol = create_volunteer(org["id"], headers=COORD)
    create_signup(stale["id"], vol["id"], stale["version"])  # advances shift.version

    resp = api.allocate_corporate_group(
        grp["id"], {"expected_shift_version": stale["version"]}, COORD)
    validate_error(resp, ApiErrorId.ERR_STALE_SHIFT_VERSION.value)


def test_archive_then_stale_archive_rejected(api):
    """PRD §2.6: "Archiving requires `expected_organization_version` matching the
    organization's current `version`, and a mismatch is rejected with
    `ERR_STALE_ORGANIZATION_VERSION` at HTTP status 412."

    Design: Corner/cross_cutting_complexity_layers/occ_org_version_archive_then_stale_archive
    """
    org = create_organization(headers=COMPLIANCE)
    v1 = org["version"]
    first = validate_success(
        api.archive_organization(org["id"], {"expected_organization_version": v1}, COMPLIANCE))
    assert first["status"] == "ARCHIVED", f"expected ARCHIVED, got {first['status']}"
    assert first["version"] == 2, f"archive must bump version to 2, got {first['version']}"

    resp = api.archive_organization(org["id"], {"expected_organization_version": v1}, COMPLIANCE)
    validate_error(resp, ApiErrorId.ERR_STALE_ORGANIZATION_VERSION.value)


def test_suspension_triggers_exactly_at_strike_limit(api):
    """PRD §3.5: "If, after the recompute, the volunteer's `reliability_score` is
    strictly below the organization's `reliability_suspension_threshold`, or the
    volunteer's `lifetime_no_show_count` is greater than or equal to the organization's
    `no_show_strike_limit`, the volunteer's `status` is transitioned to `SUSPENDED`."

    Design: Corner/cross_cutting_complexity_layers/rate_threshold_suspension_at_strike_limit
    """
    # strike_limit 2, suspension_threshold 0 so only the strike count can suspend.
    org = create_organization(headers=COORD, no_show_strike_limit=2, reliability_suspension_threshold=0)
    set_clock("2026-06-15T00:00:00Z", headers=COORD)
    vol = create_volunteer(org["id"], headers=COORD)
    opp = create_opportunity(org["id"], headers=COORD)
    sa = create_shift(opp["id"], "2026-07-01T09:00:00Z", "2026-07-01T12:00:00Z", 5, headers=COORD)
    sb = create_shift(opp["id"], "2026-07-02T09:00:00Z", "2026-07-02T12:00:00Z", 5, headers=COORD)
    publish_opportunity(opp["id"], headers=COORD)

    su_a = create_confirmed_signup(sa, vol["id"])
    su_b = create_confirmed_signup(sb, vol["id"])

    validate_success(api.mark_no_show_signup(su_a["id"], COORD))
    after_1 = get_volunteer(vol["id"], headers=COORD)
    assert after_1["status"] == "ACTIVE", \
        f"after 1 no-show (count 1 < limit 2) expected ACTIVE, got {after_1['status']}"

    validate_success(api.mark_no_show_signup(su_b["id"], COORD))
    after_2 = get_volunteer(vol["id"], headers=COORD)
    assert after_2["status"] == "SUSPENDED", \
        f"at 2nd no-show (count 2 >= limit 2) expected SUSPENDED, got {after_2['status']}"
    assert after_2["lifetime_no_show_count"] == 2


def test_volunteer_cannot_verify_hours(api):
    """PRD §2.1: "When the headers are present and valid but the declared role is not
    permitted to perform the requested operation, the request is rejected with
    `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/volunteer_cannot_verify_hours
    """
    org = create_organization(headers=COORD)
    set_clock("2026-06-15T00:00:00Z", headers=COORD)
    vol = create_volunteer(org["id"], headers=COORD)
    opp = create_opportunity(org["id"], headers=COORD)
    shift = create_shift(opp["id"], "2026-07-01T09:00:00Z", "2026-07-01T12:00:00Z", 2, headers=COORD)
    publish_opportunity(opp["id"], headers=COORD)
    su = create_confirmed_signup(shift, vol["id"])
    set_clock("2026-07-01T12:30:00Z", headers=COORD)
    validate_success(api.check_in_signup(su["id"], COORD))
    validate_success(api.log_hours_signup(su["id"], {"logged_hours": 2.0},
                                          make_volunteer_headers(vol["id"])))
    # verify-hours is ShiftCoordinator-exclusive; Volunteer must be denied.
    resp = api.verify_hours_signup(su["id"], make_volunteer_headers(vol["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


def test_volunteer_cannot_log_hours_on_anothers_signup(api):
    """PRD §2.1: "the actions a volunteer takes on a signup it owns — confirming,
    cancelling, and logging hours — require that the `volunteer_id` recorded on the
    target signup equal `X-User-ID`, and a mismatch is rejected with
    `ERR_NOT_SIGNUP_OWNER`."

    Design: Corner/rbac/volunteer_cannot_log_hours_on_other_volunteers_signup
    """
    org = create_organization(headers=COORD)
    set_clock("2026-06-15T00:00:00Z", headers=COORD)
    vol_a = create_volunteer(org["id"], headers=COORD, full_name="A")
    vol_b = create_volunteer(org["id"], headers=COORD, full_name="B")
    opp = create_opportunity(org["id"], headers=COORD)
    shift = create_shift(opp["id"], "2026-07-01T09:00:00Z", "2026-07-01T12:00:00Z", 5, headers=COORD)
    publish_opportunity(opp["id"], headers=COORD)

    su = create_attended_signup(shift, vol_a["id"], "2026-07-01T12:30:00Z")
    # Volunteer B (not the owner) attempts to log hours on A's signup.
    resp = api.log_hours_signup(su["id"], {"logged_hours": 2.0}, make_volunteer_headers(vol_b["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_SIGNUP_OWNER.value)
