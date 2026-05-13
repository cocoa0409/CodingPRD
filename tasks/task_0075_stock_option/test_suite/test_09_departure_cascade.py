"""Departure workflow and forfeiture cascade (PRD §3.10)."""
from __future__ import annotations

import datetime as _dt

import pytest

from test_helpers import (
    ApiErrorId,
    POST_DEPARTURE_DEATH_DAYS,
    POST_DEPARTURE_GOOD_LEAVER_FLOOR_DAYS,
    POST_DEPARTURE_RESIGNATION_DAYS,
    POST_DEPARTURE_RETIREMENT_DAYS,
    POST_DEPARTURE_TERMINATION_DAYS,
    TEST_USERS,
    advance_clock_by_months,
    assert_departure_record,
    create_and_activate_plan,
    create_and_open_batch,
    create_departure_draft,
    create_grant_and_drive_to_live,
    create_grant_payload,
    list_audit_for_target,
    register_grantee,
    settle_departure,
    validate_error,
    validate_success,
)


def test_bad_leaver_requires_termination(api, plan_admin_headers):
    """PRD §3.10: "Supplying leaver_class equal to BAD_LEAVER with any
    departure_type other than TERMINATION is rejected with
    ERR_BAD_LEAVER_REQUIRES_TERMINATION."
    """
    plan = create_and_activate_plan()
    grantee = register_grantee(plan["id"])
    res = api.create_departure_record(
        plan["id"], grantee["id"],
        {"departure_type": "RESIGNATION",
         "leaver_class": "BAD_LEAVER",
         "departed_ts": plan["current_clock_ts"]},
        plan_admin_headers,
    )
    validate_error(res, ApiErrorId.ERR_BAD_LEAVER_REQUIRES_TERMINATION.value)


def test_resignation_window_is_90_days(api, plan_admin_headers):
    """PRD §3.10: "the base window is 90 days for RESIGNATION..."
    """
    plan = create_and_activate_plan(jurisdiction_code="US")
    grantee = register_grantee(plan["id"])
    res = api.create_departure_record(
        plan["id"], grantee["id"],
        {"departure_type": "RESIGNATION",
         "departed_ts": plan["current_clock_ts"]},
        plan_admin_headers,
    )
    rec = validate_success(res, expected_status=201)
    assert_departure_record(rec)
    assert rec["post_departure_window_days"] == POST_DEPARTURE_RESIGNATION_DAYS


def test_uk_floor_120_days_for_good_leaver(api, plan_admin_headers):
    """PRD §3.10: "A jurisdiction floor applies: when leaver_class is
    GOOD_LEAVER and plan.jurisdiction_code is UK or SG,
    post_departure_window_days is the larger of the base window and
    120 days."
    """
    plan = create_and_activate_plan(jurisdiction_code="UK")
    grantee = register_grantee(plan["id"], tax_residency="UK")
    res = api.create_departure_record(
        plan["id"], grantee["id"],
        {"departure_type": "RESIGNATION",
         "departed_ts": plan["current_clock_ts"]},
        plan_admin_headers,
    )
    rec = validate_success(res, expected_status=201)
    assert rec["post_departure_window_days"] == max(
        POST_DEPARTURE_RESIGNATION_DAYS,
        POST_DEPARTURE_GOOD_LEAVER_FLOOR_DAYS,
    )


def test_bad_leaver_window_is_zero_and_deadline_null(api, plan_admin_headers):
    """PRD §3.10: "For BAD_LEAVER, post_departure_window_days is zero
    and post_departure_exercise_deadline_ts is null — the bad-leaver
    classification carries no exercise tail."
    """
    plan = create_and_activate_plan()
    grantee = register_grantee(plan["id"])
    res = api.create_departure_record(
        plan["id"], grantee["id"],
        {"departure_type": "TERMINATION",
         "leaver_class": "BAD_LEAVER",
         "departed_ts": plan["current_clock_ts"]},
        plan_admin_headers,
    )
    rec = validate_success(res, expected_status=201)
    assert rec["post_departure_window_days"] == 0
    assert rec["post_departure_exercise_deadline_ts"] is None


def test_retirement_window_is_1095_days(api, plan_admin_headers):
    """PRD §3.10: "1095 days (three years) for RETIREMENT..."
    """
    plan = create_and_activate_plan(jurisdiction_code="US")
    grantee = register_grantee(plan["id"])
    res = api.create_departure_record(
        plan["id"], grantee["id"],
        {"departure_type": "RETIREMENT",
         "departed_ts": plan["current_clock_ts"]},
        plan_admin_headers,
    )
    rec = validate_success(res, expected_status=201)
    assert rec["post_departure_window_days"] == POST_DEPARTURE_RETIREMENT_DAYS


def test_death_window_is_365_days(api, plan_admin_headers):
    """PRD §3.10: "and 365 days for DEATH..."
    """
    plan = create_and_activate_plan(jurisdiction_code="US")
    grantee = register_grantee(plan["id"])
    res = api.create_departure_record(
        plan["id"], grantee["id"],
        {"departure_type": "DEATH",
         "departed_ts": plan["current_clock_ts"]},
        plan_admin_headers,
    )
    rec = validate_success(res, expected_status=201)
    assert rec["post_departure_window_days"] == POST_DEPARTURE_DEATH_DAYS


# ---------------------------------------------------------------------------
# Settle cascade (PRD §3.10)
# ---------------------------------------------------------------------------
def test_settle_flips_grantee_to_departed(api, plan_admin_headers):
    """PRD §3.10: "On success, the grantee's eligibility_status flips to
    DEPARTED and departed_at is set to the record's departed_ts."
    """
    plan = create_and_activate_plan()
    grantee = register_grantee(plan["id"])
    advance_clock_by_months(plan["id"], 1)
    plan_now = api.get_option_plan(
        plan["id"], plan_admin_headers,
    ).json()["data"]
    dep = create_departure_draft(
        plan["id"], grantee["id"],
        departure_type="RESIGNATION",
        departed_ts=plan_now["current_clock_ts"],
    )
    settle_departure(grantee["id"], dep["id"])
    grantees = api.list_grantees(
        plan["id"], plan_admin_headers,
    ).json()["data"]
    g = next(x for x in grantees if x["id"] == grantee["id"])
    assert g["eligibility_status"] == "DEPARTED"


def test_settle_rejects_duplicate(api, plan_admin_headers):
    """PRD §3.10: "Settlement of the departure transitions it from DRAFT
    to SETTLED and is gated by two checks: the record must be in DRAFT
    (else ERR_DEPARTURE_NOT_DRAFT)..."
    """
    plan = create_and_activate_plan()
    grantee = register_grantee(plan["id"])
    advance_clock_by_months(plan["id"], 1)
    plan_now = api.get_option_plan(
        plan["id"], plan_admin_headers,
    ).json()["data"]
    dep = create_departure_draft(
        plan["id"], grantee["id"],
        departure_type="RESIGNATION",
        departed_ts=plan_now["current_clock_ts"],
    )
    settle_departure(grantee["id"], dep["id"])
    # Second settle on same record:
    res = api.settle_departure_record(
        grantee["id"], dep["id"], plan_admin_headers,
    )
    validate_error(res, ApiErrorId.ERR_DEPARTURE_NOT_DRAFT.value)


def test_settle_already_departed_grantee_rejected(api, plan_admin_headers):
    """PRD §3.10: "...and the grantee must still be ELIGIBLE (else
    ERR_GRANTEE_ALREADY_DEPARTED)."
    """
    plan = create_and_activate_plan()
    grantee = register_grantee(plan["id"])
    advance_clock_by_months(plan["id"], 1)
    plan_now = api.get_option_plan(
        plan["id"], plan_admin_headers,
    ).json()["data"]
    dep1 = create_departure_draft(
        plan["id"], grantee["id"],
        departure_type="RESIGNATION",
        departed_ts=plan_now["current_clock_ts"],
    )
    settle_departure(grantee["id"], dep1["id"])
    # Try creating a second departure record on the same grantee.
    dep2_res = api.create_departure_record(
        plan["id"], grantee["id"],
        {"departure_type": "RESIGNATION",
         "departed_ts": plan_now["current_clock_ts"]},
        plan_admin_headers,
    )
    if dep2_res.status_code == 201:
        dep2 = dep2_res.json()["data"]
        res = api.settle_departure_record(
            grantee["id"], dep2["id"], plan_admin_headers,
        )
        validate_error(res, ApiErrorId.ERR_GRANTEE_ALREADY_DEPARTED.value)
    else:
        # Server may reject creation of second draft directly.
        assert dep2_res.status_code in (409, 422)


def test_bad_leaver_cascade_terminates_grants(api, plan_admin_headers):
    """PRD §3.10: "For BAD_LEAVER, the outstanding-vested portion is
    also added to forfeited_quantity and plan.pool_reserved_options is
    decreased accordingly; the grant transitions from LIVE or FROZEN to
    TERMINATED..."
    """
    plan = create_and_activate_plan(pool_total_options=5000)
    batch = create_and_open_batch(plan["id"])
    grantee = register_grantee(plan["id"])
    grant = create_grant_and_drive_to_live(
        plan, batch, grantee, quantity=1200,
    )
    advance_clock_by_months(plan["id"], 15)
    plan_now = api.get_option_plan(
        plan["id"], plan_admin_headers,
    ).json()["data"]
    dep = create_departure_draft(
        plan["id"], grantee["id"],
        departure_type="TERMINATION",
        leaver_class="BAD_LEAVER",
        departed_ts=plan_now["current_clock_ts"],
    )
    settle_departure(grantee["id"], dep["id"])
    g_after = validate_success(api.get_grant(
        grant["id"], plan_admin_headers,
    ), expected_status=200)
    assert g_after["status"] == "TERMINATED"


def test_good_leaver_cascade_keeps_grant_live(api, plan_admin_headers):
    """PRD §3.10: "For GOOD_LEAVER, the grant stays in LIVE or FROZEN
    and the outstanding-vested portion remains exercisable, but only
    while the plan clock has not yet exceeded
    post_departure_exercise_deadline_ts..."
    """
    plan = create_and_activate_plan(pool_total_options=5000)
    batch = create_and_open_batch(plan["id"])
    grantee = register_grantee(plan["id"])
    grant = create_grant_and_drive_to_live(
        plan, batch, grantee, quantity=1200,
    )
    advance_clock_by_months(plan["id"], 15)
    plan_now = api.get_option_plan(
        plan["id"], plan_admin_headers,
    ).json()["data"]
    dep = create_departure_draft(
        plan["id"], grantee["id"],
        departure_type="RESIGNATION",
        departed_ts=plan_now["current_clock_ts"],
    )
    settle_departure(grantee["id"], dep["id"])
    g_after = validate_success(api.get_grant(
        grant["id"], plan_admin_headers,
    ), expected_status=200)
    assert g_after["status"] in {"LIVE", "FROZEN"}


def test_departure_settled_audit_entry_appended(api, plan_admin_headers):
    """PRD §3.10: "the departure-settle itself appends an audit entry
    with action_code DEPARTURE_SETTLED."
    """
    plan = create_and_activate_plan()
    grantee = register_grantee(plan["id"])
    advance_clock_by_months(plan["id"], 1)
    plan_now = api.get_option_plan(
        plan["id"], plan_admin_headers,
    ).json()["data"]
    dep = create_departure_draft(
        plan["id"], grantee["id"],
        departure_type="RESIGNATION",
        departed_ts=plan_now["current_clock_ts"],
    )
    settle_departure(grantee["id"], dep["id"])
    entries = list_audit_for_target(
        plan["id"], dep["id"], action_code="DEPARTURE_SETTLED",
    )
    assert len(entries) >= 1
