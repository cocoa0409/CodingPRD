"""Membership activation, freeze windows, term extension, and expiry."""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    TEST_USERS,
    ApiErrorId,
    fixtures as fx,
)
import test_helpers.factories as f

ADMIN = TEST_USERS["billing_admin_headers"]
SCREENING = TEST_USERS["screening_officer_headers"]
MATCHMAKER = TEST_USERS["matchmaker_headers"]


def test_activate_membership_requires_member_approved(api):
    """PRD §3.2: "Activation requires the member's `screening_decision` to be `APPROVED`;
    otherwise it is rejected with `ERR_MEMBER_NOT_APPROVED`."

    Design: Difficulty/cross_entity_state_dependency/membership_activation_requires_member_approved
    """
    fx.set_clock()
    plan = fx.create_plan()
    member = fx.register_prospect("x@x.com", gender="MALE")
    # Open a screening (member now SCREENING) but DO NOT decide it -> still PENDING.
    validate_success(
        api.create_screening(member["id"], f.create_screening_payload(), SCREENING), 201
    )
    resp = api.activate_membership(member["id"], f.activate_membership_payload(plan["id"]), ADMIN)
    validate_error(resp, ApiErrorId.ERR_MEMBER_NOT_APPROVED.value, 409)


def test_activate_membership_on_pending_screening_via_alt_path(api):
    """PRD §3.2: "Activation requires the member's `screening_decision` to be `APPROVED`;
    otherwise it is rejected with `ERR_MEMBER_NOT_APPROVED`." A member whose screening is
    still `PENDING` does not have an `APPROVED` screening_decision.

    Design: Difficulty/cross_entity_state_dependency/membership_activation_requires_member_approved
    """
    fx.set_clock()
    plan = fx.create_plan(tier="ELITE")
    member = fx.register_prospect("x2@x.com", gender="FEMALE")
    validate_success(
        api.create_screening(member["id"], f.create_screening_payload(questionnaire_score=50), SCREENING),
        201,
    )
    resp = api.activate_membership(member["id"], f.activate_membership_payload(plan["id"]), ADMIN)
    validate_error(resp, ApiErrorId.ERR_MEMBER_NOT_APPROVED.value, 409)


def test_membership_on_archived_plan_rejected(api):
    """PRD §3.2: "The named plan must not be archived; activation against an archived plan is rejected with `ERR_PLAN_ARCHIVED`."

    Design: Corner/validations/membership_on_archived_plan_rejected
    """
    fx.set_clock()
    plan = fx.create_plan()
    member = fx.register_prospect("ca11@x.com", gender="MALE")
    fx.open_and_decide_screening(member["id"], decision="APPROVED")
    validate_success(api.archive_plan(plan["id"], ADMIN), 200)
    resp = api.activate_membership(member["id"], f.activate_membership_payload(plan["id"]), ADMIN)
    validate_error(resp, ApiErrorId.ERR_PLAN_ARCHIVED.value, 422)


def test_resume_scheduled_freeze_not_active_returns_freeze_not_active(api):
    """PRD §3.8: "Resuming requires the freeze to be `ACTIVE` (else
    `ERR_FREEZE_NOT_ACTIVE`)."

    Design: Corner/state_machines/resume_scheduled_freeze_not_active_returns_freeze_not_active
    """
    member_id, membership_id, freeze_id = fx.setup_membership_with_scheduled_freeze(
        freeze_start="2026-07-01T00:00:00Z", freeze_end="2026-07-10T00:00:00Z", email="ca4@x.com"
    )
    resp = api.resume_freeze(membership_id, freeze_id, ADMIN)
    validate_error(resp, ApiErrorId.ERR_FREEZE_NOT_ACTIVE.value, 409)


def test_freeze_resume_bubbles_membership_active_and_extends_term(api):
    """PRD §3.8: "On resume, the freeze's `committed_days` is computed as the whole
    number of days from `start_at` up to the earlier of the freeze's `end_at` and the
    resume instant, rounded up to the next whole day. The freeze moves to `RESUMED`,
    those `committed_days` are added to the member's `frozen_days_total`, the member's
    `term_end_at` is recomputed to reflect the extension, the membership returns to
    `ACTIVE`, and the member returns to `ACTIVE`."

    Design: Corner/state_machines/freeze_resume_bubbles_membership_active_and_extends_term
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    plan = fx.create_plan()
    member, membership = fx.create_active_member(plan["id"], "ca6@x.com", with_preferences=False)
    frz = fx.schedule_freeze(membership["id"], "2026-06-10T00:00:00Z", "2026-06-30T00:00:00Z")
    fx.set_clock("2026-06-20T00:00:00Z")

    resp = api.resume_freeze(membership["id"], frz["id"], ADMIN)
    freeze_data = validate_success(resp, 200)
    assert freeze_data["committed_days"] == 10, (
        f"start 06-10 to resume 06-20 = 10 days, got {freeze_data['committed_days']}"
    )
    assert freeze_data["status"] == "RESUMED", f"expected RESUMED, got {freeze_data['status']}"

    member_after = validate_success(api.get_member(member["id"], MATCHMAKER), 200)
    assert member_after["frozen_days_total"] == 10, (
        f"frozen_days_total should be 10, got {member_after['frozen_days_total']}"
    )
    assert member_after["status"] == "ACTIVE", (
        f"member returns to ACTIVE after resume, got {member_after['status']}"
    )


def test_scheduled_freeze_activates_on_clock_advance(api):
    """PRD §3.8: "once the clock reaches the freeze's `start_at`, the next operation
    touching the record flips the freeze to `ACTIVE`, the membership to `FROZEN`, and
    the member to `FROZEN`."

    Design: Corner/cross_cutting_complexity_layers/scheduled_freeze_activates_on_clock_advance
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    plan = fx.create_plan()
    member, membership = fx.create_active_member(plan["id"], "ca18@x.com", with_preferences=False)
    fx.schedule_freeze(membership["id"], "2026-06-10T00:00:00Z", "2026-06-30T00:00:00Z")
    fx.set_clock("2026-06-11T00:00:00Z")

    ms = validate_success(api.get_membership(membership["id"], ADMIN), 200)
    assert ms["status"] == "FROZEN", f"membership should be FROZEN after clock advance, got {ms['status']}"
    mem = validate_success(api.get_member(member["id"], ADMIN), 200)
    assert mem["status"] == "FROZEN", f"member should be FROZEN after clock advance, got {mem['status']}"


def test_membership_expires_when_clock_passes_term_end(api):
    """PRD §3.9: "A membership in `ACTIVE` whose term has run out with the guarantee
    unmet — that is, the clock has reached or passed the member's `term_end_at` — flips
    to `EXPIRED`; this is evaluated lazily on the next read or operation that touches
    the membership after the clock advances past `term_end_at`."

    Design: Corner/cross_cutting_complexity_layers/membership_expires_when_clock_passes_term_end
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    plan = fx.create_plan(tier="BASIC", monthly_fee_cents=9000, term_months=1,
                          guaranteed_introductions=2, included_coaching_sessions=1,
                          coaching_value_cents=1000, background_check_addon_cents=2000)
    member, membership = fx.create_active_member(plan["id"], "ca19@x.com", with_preferences=False)
    fx.set_clock("2026-07-02T00:00:00Z")

    ms = validate_success(api.get_membership(membership["id"], ADMIN), 200)
    assert ms["status"] == "EXPIRED", (
        f"membership past term_end with guarantee unmet should be EXPIRED, got {ms['status']}"
    )


def test_archived_plan_excluded_from_default_list(api):
    """PRD §3.1: "Listing plans excludes archived plans unless the caller passes
    `include_archived` set to true."

    Design: Corner/cross_cutting_complexity_layers/archived_plan_excluded_from_default_list
    """
    plan = fx.create_plan(tier="BASIC", monthly_fee_cents=9000, term_months=3,
                          guaranteed_introductions=4, included_coaching_sessions=2,
                          coaching_value_cents=4000, background_check_addon_cents=2000)
    validate_success(api.archive_plan(plan["id"], ADMIN), 200)

    default_data, default_meta = validate_paginated(api.list_plans(ADMIN))
    assert default_meta["total_count"] == 0, (
        f"archived plan must be excluded by default, total_count={default_meta['total_count']}"
    )

    inc_data, inc_meta = validate_paginated(
        api.list_plans(ADMIN, params={"include_archived": "true"})
    )
    assert inc_meta["total_count"] == 1, (
        f"include_archived=true must include archived plan, total_count={inc_meta['total_count']}"
    )
