"""Reviewer onboarding, certification grants and the protective wellness break."""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_fields,
    assert_instant_equals,
    expected_exposure_charge,
)
from test_helpers.factories import certification_payload, wellness_break_payload
from test_helpers.fixtures import (
    build_pending_case,
    build_policy_baseline,
    build_workforce_baseline,
)
from test_helpers.test_users import (
    ADMIN_HEADERS,
    LEGAL_HEADERS,
    POLICY_AUTHOR_HEADERS,
    make_qa_auditor_headers,
)


def test_certification_with_unknown_policy_version_returns_not_found(api, world):
    """The link needs both sides: the path reviewer resolves, the body version does not.

    PRD 2.8: "**Body-referenced identifiers and natural keys**, resolved in the
    order the operation's input list declares them: `account_id`, then
    `content_item_id`, then `policy_category_id`, then `policy_category_code`,
    then `policy_version_id`, then `case_id`, then `target_reviewer_id`, then
    each member of `exclude_reviewer_ids`."

    Design: Corner/endpoints/certification_with_unknown_policy_version_returns_not_found
    """
    base = build_policy_baseline(world)
    reviewer = world.create_reviewer(display_name="Rita Frontline")
    assert reviewer["version"] == 1
    assert reviewer["certified_policy_version_ids"] == []

    validate_error(
        api.grant_certification(
            reviewer["id"],
            certification_payload(NON_EXISTENT_UUID, reviewer["version"]),
            headers=POLICY_AUTHOR_HEADERS,
        ),
        ApiErrorId.POLICY_VERSION_NOT_FOUND.value,
    )
    unchanged = world.get_reviewer(reviewer["id"])
    assert unchanged["version"] == 1
    assert unchanged["certified_policy_version_ids"] == []

    validate_error(
        api.grant_certification(
            NON_EXISTENT_UUID,
            certification_payload(base.version_id, 1),
            headers=POLICY_AUTHOR_HEADERS,
        ),
        ApiErrorId.REVIEWER_NOT_FOUND.value,
    )

    granted = world.certify(reviewer["id"], base.version_id)
    assert granted["certified_policy_version_ids"] == [base.version_id]
    assert granted["version"] == 2


def test_reviewer_read_reflects_derived_workload_and_exposure(api, world):
    """A reviewer read derives exposure from graphic weight times the media multiplier.

    PRD 3.6: "Every case charges `exposure_points_charged` equal to the content
    item's `graphic_weight` multiplied by the media multiplier of its
    `media_kind` — 1 for `TEXT`, 2 for `IMAGE`, 3 for `VIDEO` — so a
    graphic-weight-6 video costs 18 points against a default budget of 20 while
    the same weight in text costs 6."

    Design: Corner/endpoints/reviewer_read_reflects_derived_workload_and_exposure
    """
    assert expected_exposure_charge(2, "TEXT") == 2
    assert expected_exposure_charge(2, "VIDEO") == 6

    base = build_workforce_baseline(world)
    text_case = build_pending_case(
        base, content_overrides={"media_kind": "TEXT", "graphic_weight": 2}
    )
    video_case = build_pending_case(
        base, content_overrides={"media_kind": "VIDEO", "graphic_weight": 2}
    )
    world.assign(text_case.case_id, target_reviewer_id=base.frontline_id)
    world.assign(video_case.case_id, target_reviewer_id=base.frontline_id)

    read = validate_success(
        api.get_reviewer(base.frontline_id, headers=make_qa_auditor_headers(base.auditor_id))
    )
    assert_fields(
        read,
        {
            "open_case_count": 2,
            "exposure_points_today": 8,
            "max_concurrent_cases": 3,
            "daily_exposure_cap_points": 20,
            "accuracy_score_audit_only": None,
            "accuracy_score_blended": None,
            "pending_retraining_version_ids": [],
            "status": "ACTIVE",
        },
        "reviewer read",
    )
    assert read["certified_policy_version_ids"] == [base.version_id]

    assert world.get_case(text_case.case_id)["exposure_points_charged"] == 2
    assert world.get_case(video_case.case_id)["exposure_points_charged"] == 6

    rows, meta = validate_paginated(
        api.list_moderation_cases(headers=ADMIN_HEADERS, assigned_reviewer_id=base.frontline_id)
    )
    assert meta["total_count"] == 2
    assert sorted(row["id"] for row in rows) == sorted([text_case.case_id, video_case.case_id])


def test_certification_on_draft_version_rejected(api, world):
    """A draft rule cannot pre-certify the workforce ahead of its measurement.

    PRD 3.4: "The version being granted must be in `BACKTESTING` or `ACTIVE`; a
    `DRAFT` or `SUPERSEDED` version cannot be certified on and is rejected with
    `ERR_POLICY_VERSION_NOT_CERTIFIABLE` (HTTP 409)."

    Design: Corner/errors/certification_on_draft_version_rejected
    """
    base = build_workforce_baseline(world)
    draft = world.create_draft_version(base.category_id, review_sla_minutes=60)
    assert draft["status"] == "DRAFT"
    current_version = world.get_reviewer(base.frontline_id)["version"]

    validate_error(
        api.grant_certification(
            base.frontline_id,
            certification_payload(draft["id"], current_version),
            headers=POLICY_AUTHOR_HEADERS,
        ),
        ApiErrorId.POLICY_VERSION_NOT_CERTIFIABLE.value,
    )
    unchanged = world.get_reviewer(base.frontline_id)
    assert unchanged["certified_policy_version_ids"] == [base.version_id]
    assert unchanged["version"] == current_version

    world.back_test(draft["id"])
    assert world.get_policy_version(draft["id"])["status"] == "BACKTESTING"
    granted = world.certify(base.frontline_id, draft["id"])
    assert granted["certified_policy_version_ids"] == [base.version_id, draft["id"]]
    assert granted["version"] == current_version + 1


def test_return_to_duty_for_active_reviewer_rejected(api, world):
    """Return-to-duty is only legal from a break, so it never silently clears the window.

    PRD 3.6: "Ending a break moves the reviewer `ON_WELLNESS_BREAK → ACTIVE`; a
    reviewer who is not `ON_WELLNESS_BREAK` cannot be returned to duty and the
    attempt yields `ERR_REVIEWER_NOT_ON_BREAK` (HTTP 409)."

    Design: Corner/errors/return_to_duty_for_active_reviewer_rejected
    """
    base = build_workforce_baseline(world)
    before = world.get_reviewer(base.frontline_id)
    assert_fields(
        before,
        {
            "status": "ACTIVE",
            "wellness_break_start": None,
            "wellness_break_end": None,
            "wellness_breaks_taken": 0,
        },
        "reviewer before",
    )

    validate_error(
        api.return_to_duty(base.frontline_id, headers=ADMIN_HEADERS),
        ApiErrorId.REVIEWER_NOT_ON_BREAK.value,
    )
    after_refusal = world.get_reviewer(base.frontline_id)
    assert_fields(
        after_refusal,
        {
            "status": "ACTIVE",
            "wellness_break_start": None,
            "wellness_break_end": None,
            "wellness_breaks_taken": 0,
        },
        "reviewer after refusal",
    )

    on_break = world.start_wellness_break(base.frontline_id, break_minutes=60)
    assert on_break["status"] == "ON_WELLNESS_BREAK"
    back = world.return_to_duty(base.frontline_id)
    assert back["status"] == "ACTIVE"
    assert_instant_equals(back["wellness_break_start"], "2026-08-01T09:00:00Z", "retained start")
    assert_instant_equals(back["wellness_break_end"], "2026-08-01T10:00:00Z", "retained end")
    assert back["wellness_breaks_taken"] == 1


def test_stale_expected_reviewer_version_on_certification_rejected(api, world):
    """A version spent on the first grant cannot be replayed on the second.

    PRD 2.9: "Granting a reviewer certification requires
    `expected_reviewer_version`, carrying the client's last observed `version` of
    the target `Reviewer`. A mismatch with the reviewer's current `version` is
    rejected with `ERR_STALE_REVIEWER_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/stale_expected_reviewer_version_on_certification_rejected
    """
    base = build_workforce_baseline(world)
    spent_version = 1
    current = world.get_reviewer(base.frontline_id)
    assert current["version"] == spent_version + 1

    second = world.create_draft_version(base.category_id, review_sla_minutes=120)
    world.back_test(second["id"])
    assert world.get_policy_version(second["id"])["status"] == "BACKTESTING"

    validate_error(
        api.grant_certification(
            base.frontline_id,
            certification_payload(second["id"], spent_version),
            headers=POLICY_AUTHOR_HEADERS,
        ),
        ApiErrorId.STALE_REVIEWER_VERSION.value,
    )
    unchanged = world.get_reviewer(base.frontline_id)
    assert unchanged["certified_policy_version_ids"] == [base.version_id]
    assert unchanged["version"] == spent_version + 1

    retried = world.certify(base.frontline_id, second["id"], unchanged["version"])
    assert retried["certified_policy_version_ids"] == [base.version_id, second["id"]]
    assert retried["version"] == spent_version + 2


def test_legal_counsel_cannot_grant_reviewer_certification(api, world):
    """Legal counsel may decide escalated legal work but cannot mint certifications.

    PRD 3.4: "Certification is a `PolicyManager` act. A grant names the
    `policy_version_id` being granted and carries `expected_reviewer_version` as
    described in §2.9."

    Design: Corner/rbac/legal_counsel_cannot_grant_reviewer_certification
    """
    base = build_workforce_baseline(world)
    second = world.create_draft_version(base.category_id, review_sla_minutes=120)
    world.back_test(second["id"])
    reviewer_version = world.get_reviewer(base.frontline_id)["version"]

    refused = api.grant_certification(
        base.frontline_id,
        certification_payload(second["id"], reviewer_version),
        headers=LEGAL_HEADERS,
    )
    assert refused.status_code == 403
    validate_error(refused, ApiErrorId.UNAUTHORIZED.value)

    unchanged = world.get_reviewer(base.frontline_id)
    assert unchanged["certified_policy_version_ids"] == [base.version_id]
    assert unchanged["version"] == reviewer_version

    granted = world.certify(base.frontline_id, second["id"], reviewer_version)
    assert granted["certified_policy_version_ids"] == [base.version_id, second["id"]]


def test_wellness_break_overlapping_retained_window_rejected(api, world, clock_at_t0):
    """A break beginning inside the retained window is refused and changes nothing.

    PRD 3.6: "The requested break occupies the half-open window beginning at the
    current logical instant and ending `break_minutes` later, and it may not
    overlap the reviewer's retained window running from `wellness_break_start` up
    to but not including `wellness_break_end`; an overlap is rejected with
    `ERR_WELLNESS_BREAK_OVERLAP` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/wellness_break_half_open_adjacent_accepted_overlap_rejected
    """
    reviewer = world.create_reviewer(display_name="Rita Frontline")
    world.start_wellness_break(reviewer["id"], break_minutes=60)
    returned = world.return_to_duty(reviewer["id"])
    assert_instant_equals(returned["wellness_break_start"], "2026-08-01T09:00:00Z", "b1 start")
    assert_instant_equals(returned["wellness_break_end"], "2026-08-01T10:00:00Z", "b1 end")

    validate_success(api.set_clock("2026-08-01T09:59:00Z", headers=ADMIN_HEADERS))
    validate_error(
        api.start_wellness_break(
            reviewer["id"], wellness_break_payload(break_minutes=30), headers=ADMIN_HEADERS
        ),
        ApiErrorId.WELLNESS_BREAK_OVERLAP.value,
    )

    after = world.get_reviewer(reviewer["id"])
    assert after["status"] == "ACTIVE"
    assert after["wellness_breaks_taken"] == 1
    assert_instant_equals(after["wellness_break_start"], "2026-08-01T09:00:00Z", "start unchanged")
    assert_instant_equals(after["wellness_break_end"], "2026-08-01T10:00:00Z", "end unchanged")
    assert after["open_case_count"] == 0
    assert after["exposure_points_today"] == 0


def test_wellness_break_starting_at_retained_window_end_accepted(api, world, clock_at_t0):
    """The retained window excludes its end instant, so an adjacent break is legal.

    PRD 3.6: "Because both windows are half-open, a request that starts exactly
    at the retained window's end instant does not overlap and is accepted."

    Design: Difficulty/resource_temporal_overlap/wellness_break_half_open_adjacent_accepted_overlap_rejected
    """
    reviewer = world.create_reviewer(display_name="Rita Frontline")
    world.start_wellness_break(reviewer["id"], break_minutes=60)
    world.return_to_duty(reviewer["id"])

    validate_success(api.set_clock("2026-08-01T10:00:00Z", headers=ADMIN_HEADERS))
    adjacent = validate_success(
        api.start_wellness_break(
            reviewer["id"], wellness_break_payload(break_minutes=30), headers=ADMIN_HEADERS
        )
    )
    assert adjacent["status"] == "ON_WELLNESS_BREAK"
    assert_instant_equals(adjacent["wellness_break_start"], "2026-08-01T10:00:00Z", "b2 start")
    assert_instant_equals(adjacent["wellness_break_end"], "2026-08-01T10:30:00Z", "b2 end")
    assert adjacent["wellness_breaks_taken"] == 2
    assert adjacent["open_case_count"] == 0
    assert adjacent["exposure_points_today"] == 0


def _reviewer_holding_two_cases(world):
    """Load one reviewer with a weight-2 and a weight-3 TEXT case, both ASSIGNED."""
    base = build_workforce_baseline(world)
    light = build_pending_case(base, content_overrides={"media_kind": "TEXT", "graphic_weight": 2})
    heavy = build_pending_case(base, content_overrides={"media_kind": "TEXT", "graphic_weight": 3})
    world.assign(light.case_id, target_reviewer_id=base.frontline_id)
    world.assign(heavy.case_id, target_reviewer_id=base.frontline_id)
    return base, light, heavy


def test_wellness_break_refunds_every_held_case_charge(api, world):
    """Both charges are refunded in full, not just the last one taken.

    PRD 3.6: "Because those cases have returned, the reviewer's `open_case_count`
    is set to 0 and their `exposure_points_today` is set to 0 — the reset
    discards even the exposure retained from cases they had already decided — and
    each affected queue's `unassigned_case_count` rises by one per returned case."

    Design: Difficulty/compensating_invariant/reviewer_workload_and_exposure_conserved_across_wellness_break
    """
    base, light, heavy = _reviewer_holding_two_cases(world)
    loaded = world.get_reviewer(base.frontline_id)
    assert loaded["open_case_count"] == 2
    assert loaded["exposure_points_today"] == 5
    assert world.get_case(light.case_id)["exposure_points_charged"] == 2
    assert world.get_case(heavy.case_id)["exposure_points_charged"] == 3

    on_break = validate_success(
        api.start_wellness_break(
            base.frontline_id, wellness_break_payload(break_minutes=45), headers=ADMIN_HEADERS
        )
    )
    assert_fields(
        on_break,
        {
            "status": "ON_WELLNESS_BREAK",
            "open_case_count": 0,
            "exposure_points_today": 0,
            "wellness_breaks_taken": 1,
        },
        "reviewer on break",
    )
    assert_instant_equals(on_break["wellness_break_start"], "2026-08-01T09:00:00Z", "break start")
    assert_instant_equals(on_break["wellness_break_end"], "2026-08-01T09:45:00Z", "break end")

    _, meta = validate_paginated(
        api.list_moderation_cases(headers=ADMIN_HEADERS, assigned_reviewer_id=base.frontline_id)
    )
    assert meta["total_count"] == 0


def test_wellness_break_leaves_queue_open_count_and_deadlines_alone(api, world):
    """The returned cases stay open and keep their deadlines; only assignability changes.

    PRD 3.6: "Two things are deliberately left alone: each affected queue's
    `open_case_count`, because those cases never stopped being open, and each
    returned case's `sla_due_at`, which is not recomputed; the deadline is only
    ever recomputed on the explicit return-to-queue path described in §3.5."

    Design: Difficulty/compensating_invariant/reviewer_workload_and_exposure_conserved_across_wellness_break
    """
    base, light, heavy = _reviewer_holding_two_cases(world)
    for scenario in (light, heavy):
        assert_instant_equals(
            world.get_case(scenario.case_id)["sla_due_at"],
            "2026-08-01T11:00:00Z",
            "sla_due_at before the break",
        )

    world.start_wellness_break(base.frontline_id, break_minutes=45)

    for scenario, charge in ((light, 2), (heavy, 3)):
        case = world.get_case(scenario.case_id)
        assert_fields(
            case,
            {
                "status": "PENDING_ASSIGNMENT",
                "assigned_reviewer_id": None,
                "exposure_points_charged": charge,
                "sla_breached": False,
            },
            "returned case",
        )
        assert_instant_equals(
            case["sla_due_at"], "2026-08-01T11:00:00Z", "sla_due_at after the break"
        )

    queue = world.get_queue(base.queue_id)
    assert queue["open_case_count"] == 2
    assert queue["unassigned_case_count"] == 2

    account = world.get_account(base.account_id)
    assert account["strike_points"] == 0
    assert account["standing"] == "GOOD_STANDING"
