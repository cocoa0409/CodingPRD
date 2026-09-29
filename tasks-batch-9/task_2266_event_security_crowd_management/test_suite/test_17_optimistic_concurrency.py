"""Version pinning, and the clock checkpoint that reports its own work.

Each version value authorises exactly one write, and the cases below spend one,
replay it, and watch the replay refused. The last case is the other cross-cutting
mechanism: the clock advance reports the rows it actually transitioned rather
than the rows it looked at.
"""

from test_helpers import (
    AUDITOR_HEADERS,
    COORDINATOR_HEADERS,
    DIRECTOR_HEADERS,
    OPERATOR_HEADERS,
    ApiClient,
    ApiErrorId,
    EventStatus,
    PlanStatus,
    PostStatus,
    PostType,
    ReadinessPosture,
    VerificationStatus,
    assert_coverage,
    assert_ledger,
    assert_post_fill,
    build_approved_assessment_world,
    build_clock_world,
    build_plan_with_perimeter_post_world,
    build_published_plan_with_posts_world,
    confirm,
    create_assignment,
    create_verified_guard,
    read_event_version,
    read_post_version,
    staffing_plan_payload,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_one_observed_event_version_authorises_exactly_one_profile_edit():
    """Spend a version, replay it, and the replay is refused twice over.

    Box-office edits legitimately overwrite one another, so the only way to catch
    a lost update is the version the client last observed — and a value that has
    already been consumed is as stale as one that was never current. Neither
    refused field was written, and the lifecycle never entered into it.

    PRD: "`PATCH /event-security/security-events/{id}` likewise requires `expected_event_version`, and a mismatch against the event's current `version` is rejected with `ERR_STALE_EVENT_VERSION` (412)."
    Design: Corner/cross_cutting_complexity_layers/occ_event_profile_update_rejects_stale_expected_event_version
    """
    api = ApiClient()
    world = build_approved_assessment_world(api)
    first_version = world.event_v

    accepted = validate_success(
        api.update_event(
            world.event_id,
            {"expected_event_version": first_version, "ticketed_attendance": 400},
            DIRECTOR_HEADERS,
        )
    )
    assert accepted["ticketed_attendance"] == 400
    assert accepted["version"] == first_version + 1

    validate_error(
        api.update_event(
            world.event_id,
            {"expected_event_version": first_version, "ticketed_attendance": 500},
            DIRECTOR_HEADERS,
        ),
        ApiErrorId.STALE_EVENT_VERSION,
    )
    assert (
        validate_success(api.get_event(world.event_id, DIRECTOR_HEADERS))["ticketed_attendance"]
        == 400
    )

    second_version = read_event_version(api, world.event_id)
    vip_set = validate_success(
        api.update_event(
            world.event_id,
            {"expected_event_version": second_version, "vip_present": True},
            DIRECTOR_HEADERS,
        )
    )
    assert vip_set["vip_present"] is True

    validate_error(
        api.update_event(
            world.event_id,
            {"expected_event_version": second_version, "alcohol_served": True},
            DIRECTOR_HEADERS,
        ),
        ApiErrorId.STALE_EVENT_VERSION,
    )

    final = validate_success(api.get_event(world.event_id, DIRECTOR_HEADERS))
    assert final["ticketed_attendance"] == 400
    assert final["vip_present"] is True
    assert final["alcohol_served"] is False
    assert final["version"] == first_version + 2
    assert final["status"] == EventStatus.RISK_ASSESSED


def test_a_plan_create_on_a_stale_event_view_supersedes_nothing():
    """The pin exists precisely because a plan create destroys planning work.

    A profile edit moves the event underneath the coordinator, so the create is
    refused — and the refusal is total: the incumbent plan is still current and
    still DRAFT, and its post is still open rather than closed. Carrying the fresh
    version through does supersede, which is what makes the earlier refusal
    meaningful.

    PRD: "`POST /event-security/security-events/{id}/staffing-plans` requires `expected_event_version` carrying the client's last observed `version` of the target `SecurityEvent`. If that value does not equal the event's current `version`, the create is rejected with `ERR_STALE_EVENT_VERSION` (412)."
    Design: Corner/cross_cutting_complexity_layers/occ_plan_create_rejects_stale_expected_event_version
    """
    api = ApiClient()
    world = build_plan_with_perimeter_post_world(api)
    observed_version = read_event_version(api, world.event_id)

    validate_success(
        api.update_event(
            world.event_id,
            {"expected_event_version": observed_version, "ticketed_attendance": 400},
            DIRECTOR_HEADERS,
        )
    )

    validate_error(
        api.create_staffing_plan(
            world.event_id,
            staffing_plan_payload(world.ra_id, observed_version),
            COORDINATOR_HEADERS,
        ),
        ApiErrorId.STALE_EVENT_VERSION,
    )
    rows, meta = validate_paginated(
        api.list_staffing_plans(
            COORDINATOR_HEADERS, params={"event_id": world.event_id, "is_current": True}
        )
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == world.plan_id
    assert rows[0]["status"] == PlanStatus.DRAFT
    assert (
        validate_success(api.get_post(world.p1_id, COORDINATOR_HEADERS))["status"]
        == PostStatus.OPEN
    )

    replacement = validate_success(
        api.create_staffing_plan(
            world.event_id,
            staffing_plan_payload(world.ra_id, read_event_version(api, world.event_id)),
            COORDINATOR_HEADERS,
        ),
        expected_status=201,
    )
    assert replacement["status"] == PlanStatus.DRAFT
    assert replacement["is_current"] is True
    assert replacement["supersedes_plan_id"] == world.plan_id

    _, meta = validate_paginated(
        api.list_staffing_plans(COORDINATOR_HEADERS, params={"event_id": world.event_id})
    )
    assert meta["total_count"] == 2
    superseded = validate_success(api.get_staffing_plan(world.plan_id, COORDINATOR_HEADERS))
    assert superseded["status"] == PlanStatus.SUPERSEDED
    assert superseded["is_current"] is False


def test_a_cascaded_post_bump_invalidates_a_re_profile_just_as_a_direct_write_would():
    """The client never issued the write that stole its version.

    A confirmation on the post's roster advances the post's own version as a side
    effect, so a version read before that confirmation is stale afterwards — the
    pin does not distinguish between a rival editor and a cascade. Three refused
    re-profiles later, the plan's figures are exactly what the two accepted writes
    left behind.

    PRD: "A mismatch against the post's current `version` is rejected with `ERR_STALE_POST_VERSION` (412). Successive re-profiles legitimately overwrite one another, and cascaded roster changes advance a post's `version` behind the client's back, so the observed version is the only safe basis for a re-profile."
    Design: Corner/cross_cutting_complexity_layers/occ_post_update_rejects_stale_expected_post_version
    """
    api = ApiClient()
    world = build_published_plan_with_posts_world(
        api, [{"code": "P1", "post_type": PostType.PERIMETER, "required_guard_count": 5}]
    )
    guard_id = create_verified_guard(api, "GC-7001", credential_level=3)
    row = create_assignment(api, world.p1_id, guard_id)
    first_version = read_post_version(api, world.p1_id)

    widened = validate_success(
        api.update_post(
            world.p1_id,
            {"expected_post_version": first_version, "required_guard_count": 6},
            COORDINATOR_HEADERS,
        )
    )
    assert widened["required_guard_count"] == 6
    assert widened["version"] == first_version + 1

    validate_error(
        api.update_post(
            world.p1_id,
            {"expected_post_version": first_version, "min_credential_level": 2},
            COORDINATOR_HEADERS,
        ),
        ApiErrorId.STALE_POST_VERSION,
    )
    stale_view = validate_success(api.get_post(world.p1_id, COORDINATOR_HEADERS))
    assert stale_view["min_credential_level"] == 1
    second_version = stale_view["version"]

    confirm(api, row)
    after_confirm = validate_success(api.get_post(world.p1_id, COORDINATOR_HEADERS))
    assert_post_fill(after_confirm, 1, PostStatus.PARTIALLY_STAFFED)
    assert after_confirm["version"] == second_version + 1

    validate_error(
        api.update_post(
            world.p1_id,
            {"expected_post_version": second_version, "min_credential_level": 2},
            COORDINATOR_HEADERS,
        ),
        ApiErrorId.STALE_POST_VERSION,
    )

    reprofiled = validate_success(
        api.update_post(
            world.p1_id,
            {
                "expected_post_version": read_post_version(api, world.p1_id),
                "min_credential_level": 2,
            },
            COORDINATOR_HEADERS,
        )
    )
    assert reprofiled["min_credential_level"] == 2

    summary = validate_success(api.get_coverage_summary(world.plan_id, COORDINATOR_HEADERS))
    assert_coverage(summary, 6, 1, 0.17, ReadinessPosture.BLOCKED)
    assert_ledger(summary, 16500, 7.50)


def test_the_clock_checkpoint_reports_the_rows_it_transitioned_and_no_others():
    """Nothing due, then the boundary instant, then nothing left to sweep.

    Advancing to an instant with no card due reports zero, and re-setting the same
    instant reports zero again. The predicate is inclusive, so a card expiring at
    exactly the new clock value is swept — once. The already-expired row is no
    longer VERIFIED, so a later advance passes over it, and the guard holds no
    roster rows for the void cascade to touch.

    PRD: "When a `SystemOperator` advances the logical clock, the same call runs a credential-expiry sweep over guards in ascending `created_at` order: every guard whose `verification_status` is `VERIFIED` and whose `credential_expires_on` is at or before the new clock value moves `VERIFIED → EXPIRED`, has `verified_at` cleared to null, and runs the identical four-hop void cascade described above — assignments voided, posts re-derived, plans re-derived across coverage and ledger alike, events' `gate_posture` re-derived."
    Design: Corner/cross_cutting_complexity_layers/clock_checkpoint_counts_only_the_rows_it_actually_transitioned
    """
    api = ApiClient()
    build_clock_world(api)
    guard_id = create_verified_guard(api, "GC-7001")
    verified_version = validate_success(api.get_guard(guard_id, AUDITOR_HEADERS))["version"]

    for _ in range(2):
        report = validate_success(api.set_clock("2026-09-05T00:00:00Z", OPERATOR_HEADERS))
        assert report["current_utc"] == "2026-09-05T00:00:00Z"
        assert report["expired_guard_count"] == 0
        assert report["voided_assignment_count"] == 0

    untouched = validate_success(api.get_guard(guard_id, AUDITOR_HEADERS))
    assert untouched["verification_status"] == VerificationStatus.VERIFIED
    assert untouched["version"] == verified_version

    on_boundary = validate_success(api.set_clock("2026-12-31T00:00:00Z", OPERATOR_HEADERS))
    assert on_boundary["expired_guard_count"] == 1
    assert on_boundary["voided_assignment_count"] == 0

    expired = validate_success(api.get_guard(guard_id, AUDITOR_HEADERS))
    assert expired["verification_status"] == VerificationStatus.EXPIRED
    assert expired["verified_at"] is None
    assert expired["version"] == verified_version + 1

    later = validate_success(api.set_clock("2027-01-15T00:00:00Z", OPERATOR_HEADERS))
    assert later["expired_guard_count"] == 0
    assert later["voided_assignment_count"] == 0

    _, meta = validate_paginated(
        api.list_guards(
            AUDITOR_HEADERS, params={"verification_status": VerificationStatus.EXPIRED}
        )
    )
    assert meta["total_count"] == 1
