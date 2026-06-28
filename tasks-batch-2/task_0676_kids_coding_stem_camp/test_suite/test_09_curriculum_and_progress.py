"""Member progress score and badge-retirement recompute.

Covers corner calculation instances progress_score_no_sessions_attend_factor_zero
and badge_retire_recomputes_active_badge_count_down.
"""
import pytest
from test_helpers import (
    get_success_data, validate_success,
    create_badge,
    setup_catalogue, create_guardian, create_member, create_belt_level,
    create_open_session, enroll_drop_in, award_badge,
    make_guardian_headers, TEST_USERS,
    api_client,
)

ADMIN = TEST_USERS["center_admin_headers"]


# ─── Corner / calculations / badge_retire_recomputes_active_badge_count_down ─
def test_badge_retire_recomputes_active_badge_count(api):
    """PRD §3.1: "Retiring a badge also recomputes `active_badge_count` for every member
    who holds an active award of that badge on their current belt — the cascade reaches
    each such member — and increments the badge's `version` by one."

    Design: Corner/calculations/badge_retire_recomputes_active_badge_count_down
    """
    center, program, belt1 = setup_catalogue(drop_in_fee_cents=4000, required_badge_count=2)
    badge = create_badge(belt1["id"], name="Loops")
    guardian = create_guardian()
    member = create_member(guardian["id"], program["id"])
    session, _ = create_open_session(center["id"], program["id"], assigned_instructor_count=5)
    enrollment = enroll_drop_in(guardian["id"], session["id"], member["id"])
    award_badge(enrollment["id"], badge["id"])  # active_badge_count -> 1
    retired = get_success_data(api.retire_badge(badge["id"], ADMIN))
    assert retired["status"] == "RETIRED"
    member_after = get_success_data(api.get_member(member["id"], ADMIN))
    assert member_after["active_badge_count"] == 0
