"""Optimistic concurrency control on enrollment-create and showcase-entry-accept,
plus immediate-consistency visibility of derived seat count.

Covers corner cross_cutting instances occ_correct_version_enrollment_succeeds_and_bumps,
occ_stale_session_version_enrollment_rejected, occ_stale_showcase_version_accept_rejected,
and the consistency_model instance enrollment_create_immediately_reflects_seat_count.
"""
import pytest
from test_helpers import (
    get_success_data, validate_success, validate_error,
    create_enrollment_payload, create_accept_payload,
    setup_catalogue, create_guardian, create_member, create_open_session,
    enroll_drop_in, current_session_version, submit_entry,
    make_guardian_headers, TEST_USERS,
    api_client,
)

ADMIN = TEST_USERS["center_admin_headers"]


# ─── Corner / cross_cutting / occ_correct_version_enrollment_succeeds_and_bumps ─
def test_enrollment_with_current_version_succeeds_and_bumps(api):
    """PRD §2.11: "The enrollment-create operation requires `expected_session_version`,
    carrying the client's last observed `version` of the target session."
    PRD §3.5: "In both cases the session's `confirmed_seat_count` is incremented by one,
    the session posture is re-derived per §2.6, and the session's `version` is incremented
    by one."

    Design: Corner/cross_cutting_complexity_layers/occ_correct_version_enrollment_succeeds_and_bumps
    """
    center, program, _ = setup_catalogue(drop_in_fee_cents=4000)
    guardian = create_guardian()
    member = create_member(guardian["id"], program["id"])
    session, v0 = create_open_session(center["id"], program["id"], assigned_instructor_count=5)
    res = api.create_enrollment(
        create_enrollment_payload(session["id"], member["id"], v0, coverage="DROP_IN",
                                 sibling_index=1),
        make_guardian_headers(guardian["id"]),
    )
    validate_success(res, 201)
    after = get_success_data(api.get_session(session["id"], ADMIN))
    assert after["confirmed_seat_count"] == 1
    assert after["version"] == v0 + 1


# ─── Corner / cross_cutting / occ_stale_session_version_enrollment_rejected ─
def test_stale_session_version_enrollment_rejected(api):
    """PRD §2.11: "If `expected_session_version` does not match the session's current
    `version`, the create is operating on a stale view of remaining capacity and is rejected
    with `ERR_STALE_SESSION_VERSION` (HTTP 412) rather than silently over-subscribing the lab."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_session_version_enrollment_rejected
    """
    center, program, _ = setup_catalogue(drop_in_fee_cents=4000)
    guardian = create_guardian()
    m1 = create_member(guardian["id"], program["id"])
    m2 = create_member(guardian["id"], program["id"])
    session, v_stale = create_open_session(center["id"], program["id"], assigned_instructor_count=5)
    # First enrollment bumps the session version.
    enroll_drop_in(guardian["id"], session["id"], m1["id"], sibling_index=1,
                   expected_session_version=v_stale)
    # Second create still carries the pre-bump stale version.
    res = api.create_enrollment(
        create_enrollment_payload(session["id"], m2["id"], v_stale, coverage="DROP_IN",
                                 sibling_index=2),
        make_guardian_headers(guardian["id"]),
    )
    validate_error(res, "ERR_STALE_SESSION_VERSION")


# ─── Corner / cross_cutting / occ_stale_showcase_version_accept_rejected ─
def test_stale_showcase_version_accept_rejected(api):
    """PRD §2.11: "If `expected_showcase_version` does not match the showcase's current
    `version`, the accept is rejected with `ERR_STALE_SHOWCASE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_showcase_version_accept_rejected
    """
    center, program, _ = setup_catalogue(drop_in_fee_cents=4000)
    guardian = create_guardian()
    m1 = create_member(guardian["id"], program["id"])
    m2 = create_member(guardian["id"], program["id"])
    created = get_success_data(api.create_showcase(
        {"center_id": center["id"], "program_id": program["id"], "min_belt_rank": 1,
         "capacity": 5, "starts_at": "2026-05-11T09:00:00Z",
         "entry_deadline_at": "2026-05-10T12:00:00Z"}, ADMIN))
    opened = get_success_data(api.open_showcase(created["id"], ADMIN))
    sh_stale = opened["version"]
    e1 = submit_entry(guardian["id"], opened["id"], m1["id"])
    e2 = submit_entry(guardian["id"], opened["id"], m2["id"])
    # First accept bumps the showcase version (uses the now-stale version).
    get_success_data(api.accept_showcase_entry(e1["id"], create_accept_payload(sh_stale), ADMIN))
    # Second accept still carries the pre-bump version.
    res = api.accept_showcase_entry(e2["id"], create_accept_payload(sh_stale), ADMIN)
    validate_error(res, "ERR_STALE_SHOWCASE_VERSION")


# ─── Corner / consistency_model / enrollment_create_immediately_reflects_seat_count ─
def test_enrollment_seat_count_immediately_visible(api):
    """PRD §2.8: "These chains are applied immediately and synchronously; the system
    maintains an immediate consistency model in which derived fields and dependent states
    are reconciled within the same operation that triggered them."

    Design: Corner/consistency_model/enrollment_create_immediately_reflects_seat_count
    """
    center, program, _ = setup_catalogue(drop_in_fee_cents=4000)
    guardian = create_guardian()
    member = create_member(guardian["id"], program["id"])
    session, _ = create_open_session(center["id"], program["id"], assigned_instructor_count=5)
    enroll_drop_in(guardian["id"], session["id"], member["id"])
    after = get_success_data(api.get_session(session["id"], ADMIN))
    assert after["confirmed_seat_count"] == 1
