"""Directed case assignment and the seven-part reviewer eligibility filter."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_fields,
    assert_instant_equals,
    expected_exposure_charge,
)
from test_helpers.factories import assign_case_payload
from test_helpers.fixtures import (
    build_escalated_case,
    build_pending_case,
    build_policy_baseline,
    build_workforce_baseline,
)
from test_helpers.test_users import ADMIN_HEADERS


def test_assign_with_fully_eligible_target_satisfies_every_check(api, world):
    """Every predicate holds, so the directed write lands with its full side effects.

    PRD 3.4: "A successful assignment sets `assigned_reviewer_id`, raises that
    reviewer's `open_case_count` by one, records `exposure_points_charged` on the
    case as the content item's `graphic_weight` multiplied by its media
    multiplier — 1 for `TEXT`, 2 for `IMAGE`, 3 for `VIDEO` — and adds that charge
    to the reviewer's `exposure_points_today`."

    Design: Corner/validations/assign_with_fully_eligible_target_satisfies_every_check
    """
    base = build_workforce_baseline(world)
    scenario = build_pending_case(
        base, content_overrides={"media_kind": "TEXT", "graphic_weight": 2}
    )
    assert scenario.case["version"] == 1

    assigned = validate_success(
        api.assign_case(
            scenario.case_id,
            assign_case_payload(scenario.case["version"], target_reviewer_id=base.frontline_id),
            headers=ADMIN_HEADERS,
        )
    )
    assert_fields(
        assigned,
        {
            "status": "ASSIGNED",
            "assigned_reviewer_id": base.frontline_id,
            "exposure_points_charged": 2,
            "reassignment_count": 0,
            "version": 2,
        },
        "assigned case",
    )
    assert_instant_equals(assigned["sla_due_at"], "2026-08-01T11:00:00Z", "sla_due_at")

    reviewer = world.get_reviewer(base.frontline_id)
    assert reviewer["open_case_count"] == 1
    assert reviewer["exposure_points_today"] == 2
    assert reviewer["max_concurrent_cases"] == 3
    assert reviewer["daily_exposure_cap_points"] == 20

    queue = world.get_queue(base.queue_id)
    assert queue["open_case_count"] == 1
    assert queue["unassigned_case_count"] == 0


def test_assign_to_off_shift_reviewer_rejected_as_off_shift(api, world):
    """The local-hour window is enforced on its own, with every other predicate clean.

    PRD 3.4: "Local time is derived by adding the reviewer's `utc_offset_minutes`
    to the logical clock's UTC instant and taking the hour of the resulting local
    time as a number from 0 to 23; the reviewer is in shift when that hour is at
    or after `shift_start_local_hour` and strictly before `shift_end_local_hour`,
    or, for a window that wraps midnight, when the hour is at or after
    `shift_start_local_hour` or strictly before `shift_end_local_hour`."

    Design: Corner/state_machines/assign_to_off_shift_reviewer_rejected_as_off_shift
    """
    base = build_workforce_baseline(world)
    scenario = build_pending_case(
        base, content_overrides={"media_kind": "TEXT", "graphic_weight": 2}
    )
    night = world.create_reviewer(
        display_name="Nadia Night",
        role_class="FRONTLINE",
        languages=[base.queue["language"]],
        specialties=[base.queue["specialty"]],
        shift_start_local_hour=20,
        shift_end_local_hour=24,
    )
    world.certify(night["id"], base.version_id)
    world.set_clock("2026-08-01T22:00:00Z")

    validate_error(
        api.assign_case(
            scenario.case_id,
            assign_case_payload(scenario.case["version"], target_reviewer_id=base.frontline_id),
            headers=ADMIN_HEADERS,
        ),
        ApiErrorId.REVIEWER_OFF_SHIFT.value,
    )
    refused = world.get_case(scenario.case_id)
    assert_fields(
        refused,
        {"status": "PENDING_ASSIGNMENT", "assigned_reviewer_id": None, "version": 1},
        "case after refusal",
    )
    day_reviewer = world.get_reviewer(base.frontline_id)
    assert day_reviewer["open_case_count"] == 0
    assert day_reviewer["exposure_points_today"] == 0
    assert world.get_queue(base.queue_id)["unassigned_case_count"] == 1

    accepted = validate_success(
        api.assign_case(
            scenario.case_id,
            assign_case_payload(1, target_reviewer_id=night["id"]),
            headers=ADMIN_HEADERS,
        )
    )
    assert accepted["status"] == "ASSIGNED"
    assert accepted["assigned_reviewer_id"] == night["id"]


def test_directed_target_with_language_mismatch_rejected(api, world):
    """The language predicate compares the queue's language, not the reviewer's caseload.

    PRD 3.4: "a reviewer who does not serve the queue's language or its specialty
    yields `ERR_REVIEWER_LANGUAGE_MISMATCH` (HTTP 422)"

    Design: Corner/errors/directed_target_with_language_mismatch_rejected
    """
    base = build_workforce_baseline(world)
    german_queue = world.create_queue(base.category_id, language="DE")
    item = world.create_content(base.account_id, language="DE", media_kind="TEXT", graphic_weight=2)
    signal = world.submit_signal(
        item["id"], policy_category_code=base.category_code, classifier_confidence=0.7
    )
    case = world.get_case(signal["resulting_case_id"])
    assert case["queue_id"] == german_queue["id"]
    assert world.get_reviewer(base.frontline_id)["certified_policy_version_ids"] == [
        base.version_id
    ]

    validate_error(
        api.assign_case(
            case["id"],
            assign_case_payload(case["version"], target_reviewer_id=base.frontline_id),
            headers=ADMIN_HEADERS,
        ),
        ApiErrorId.REVIEWER_LANGUAGE_MISMATCH.value,
    )
    unchanged = world.get_case(case["id"])
    assert_fields(
        unchanged,
        {
            "queue_id": german_queue["id"],
            "status": "PENDING_ASSIGNMENT",
            "assigned_reviewer_id": None,
            "version": 1,
        },
        "case after refusal",
    )
    reviewer = world.get_reviewer(base.frontline_id)
    assert reviewer["open_case_count"] == 0
    assert reviewer["exposure_points_today"] == 0


def test_frontline_target_for_escalated_case_rejected(api, world):
    """Once escalated, the very reviewer who held the case is ineligible for it.

    PRD 3.4: "One further predicate applies only when the case is `ESCALATED`:
    the reviewer's `role_class` must be `SENIOR` or `QA`."

    Design: Corner/errors/frontline_target_for_escalated_case_rejected
    """
    base = build_workforce_baseline(world)
    scenario = build_escalated_case(
        base, content_overrides={"media_kind": "TEXT", "graphic_weight": 2}
    )
    escalated_version = scenario.case["version"]
    assert scenario.case["status"] == "ESCALATED"
    assert base.frontline["role_class"] == "FRONTLINE"

    validate_error(
        api.assign_case(
            scenario.case_id,
            assign_case_payload(escalated_version, target_reviewer_id=base.frontline_id),
            headers=ADMIN_HEADERS,
        ),
        ApiErrorId.REVIEWER_NOT_ELIGIBLE_FOR_ESCALATION.value,
    )
    refused = world.get_case(scenario.case_id)
    assert_fields(
        refused,
        {
            "status": "ESCALATED",
            "assigned_reviewer_id": None,
            "reassignment_count": 0,
            "version": escalated_version,
        },
        "case after refusal",
    )
    frontline = world.get_reviewer(base.frontline_id)
    assert frontline["open_case_count"] == 0
    assert frontline["exposure_points_today"] == 0

    picked_up = validate_success(
        api.assign_case(
            scenario.case_id,
            assign_case_payload(escalated_version, target_reviewer_id=base.senior_id),
            headers=ADMIN_HEADERS,
        )
    )
    assert picked_up["status"] == "ASSIGNED"
    assert picked_up["assigned_reviewer_id"] == base.senior_id
    assert base.senior["role_class"] == "SENIOR"


def test_auto_assign_without_any_eligible_reviewer_rejected(api, world):
    """An empty candidate pool is the one assignment failure that also spares the version.

    PRD 3.4: "If no reviewer satisfies every predicate the assignment fails with
    `ERR_NO_ELIGIBLE_REVIEWER` (HTTP 409), the case keeps `PENDING_ASSIGNMENT`,
    and its `version` is **not** incremented."

    Design: Corner/errors/auto_assign_without_any_eligible_reviewer_rejected
    """
    base = build_workforce_baseline(world)
    hate = world.create_category(
        code="HATE_SPEECH", name="Hate Speech", severity_tier="T3", specialty="HATE"
    )
    world.create_active_version(hate["id"])
    hate_queue = world.create_queue(hate["id"], specialty="HATE")

    item = world.create_content(base.account_id, media_kind="TEXT", graphic_weight=2)
    signal = world.submit_signal(
        item["id"], policy_category_code="HATE_SPEECH", classifier_confidence=0.7
    )
    case = world.get_case(signal["resulting_case_id"])
    assert case["queue_id"] == hate_queue["id"]

    validate_error(
        api.assign_case(
            case["id"], assign_case_payload(case["version"]), headers=ADMIN_HEADERS
        ),
        ApiErrorId.NO_ELIGIBLE_REVIEWER.value,
    )
    unchanged = world.get_case(case["id"])
    assert_fields(
        unchanged,
        {"status": "PENDING_ASSIGNMENT", "assigned_reviewer_id": None, "version": 1},
        "case after refusal",
    )
    queue = world.get_queue(hate_queue["id"])
    assert queue["open_case_count"] == 1
    assert queue["unassigned_case_count"] == 1
    reviewer = world.get_reviewer(base.frontline_id)
    assert reviewer["open_case_count"] == 0
    assert reviewer["exposure_points_today"] == 0


def _capped_reviewer_world(world):
    """A reviewer whose exposure budget is exactly one IMAGE weight-3 case."""
    base = build_policy_baseline(world)
    reviewer = world.create_reviewer(
        display_name="Rita Capped",
        role_class="FRONTLINE",
        languages=[base.queue["language"]],
        specialties=[base.queue["specialty"]],
        daily_exposure_cap_points=6,
    )
    world.certify(reviewer["id"], base.version_id)
    heavy = world.create_content(base.account_id, media_kind="IMAGE", graphic_weight=3)
    light = world.create_content(base.account_id, media_kind="TEXT", graphic_weight=1)
    heavy_case = world.get_case(
        world.submit_signal(
            heavy["id"], policy_category_code=base.category_code, classifier_confidence=0.7
        )["resulting_case_id"]
    )
    light_case = world.get_case(
        world.submit_signal(
            light["id"], policy_category_code=base.category_code, classifier_confidence=0.7
        )["resulting_case_id"]
    )
    return base, reviewer, heavy_case, light_case


def test_exposure_charge_landing_exactly_on_the_cap_is_accepted(api, world):
    """A charge that lands the reviewer exactly on the cap is inside the budget.

    PRD 3.4: "The reviewer's `exposure_points_today` plus this case's exposure
    charge must be less than or equal to their `daily_exposure_cap_points`, so an
    assignment that lands exactly on the cap is allowed."

    Design: Difficulty/boundary_precision_check/exposure_cap_exactly_at_limit_allows_assignment
    """
    assert expected_exposure_charge(3, "IMAGE") == 6
    base, reviewer, heavy_case, _ = _capped_reviewer_world(world)
    assert reviewer["daily_exposure_cap_points"] == 6

    assigned = validate_success(
        api.assign_case(
            heavy_case["id"],
            assign_case_payload(heavy_case["version"], target_reviewer_id=reviewer["id"]),
            headers=ADMIN_HEADERS,
        )
    )
    assert assigned["status"] == "ASSIGNED"
    assert assigned["assigned_reviewer_id"] == reviewer["id"]
    assert assigned["exposure_points_charged"] == 6

    loaded = world.get_reviewer(reviewer["id"])
    assert loaded["exposure_points_today"] == 6
    assert loaded["exposure_points_today"] == loaded["daily_exposure_cap_points"]
    assert loaded["open_case_count"] == 1
    assert loaded["status"] == "ACTIVE"


def test_exposure_charge_one_point_over_the_cap_is_rejected(api, world):
    """One point past the budget is refused even with capacity to spare.

    PRD 3.4: "an assignment whose charge would push `exposure_points_today` past
    `daily_exposure_cap_points` yields `ERR_EXPOSURE_CAP_EXCEEDED` (HTTP 422)"

    Design: Difficulty/boundary_precision_check/exposure_cap_exactly_at_limit_allows_assignment
    """
    base, reviewer, heavy_case, light_case = _capped_reviewer_world(world)
    world.assign(heavy_case["id"], target_reviewer_id=reviewer["id"])
    at_cap = world.get_reviewer(reviewer["id"])
    assert at_cap["exposure_points_today"] == 6
    assert at_cap["open_case_count"] == 1
    assert at_cap["max_concurrent_cases"] == 3

    validate_error(
        api.assign_case(
            light_case["id"],
            assign_case_payload(light_case["version"], target_reviewer_id=reviewer["id"]),
            headers=ADMIN_HEADERS,
        ),
        ApiErrorId.EXPOSURE_CAP_EXCEEDED.value,
    )
    refused = world.get_case(light_case["id"])
    assert refused["status"] == "PENDING_ASSIGNMENT"
    assert refused["assigned_reviewer_id"] is None

    after = world.get_reviewer(reviewer["id"])
    assert after["open_case_count"] == 1
    assert after["exposure_points_today"] == 6

    queue = world.get_queue(base.queue_id)
    assert queue["open_case_count"] == 2
    assert queue["unassigned_case_count"] == 1
