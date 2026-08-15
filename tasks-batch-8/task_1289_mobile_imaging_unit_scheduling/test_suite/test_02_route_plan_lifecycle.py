"""Route plan lifecycle: draft/publish/unpublish, supersede, week conflict, OCC."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    add_site_day,
    create_route_plan,
    create_route_plan_payload,
    create_unit,
    get_unit_fresh,
    publish_plan,
    setup_bookable_day,
    validate_error,
    validate_success,
)

OPS = TEST_USERS["operations_director_headers"]


def test_route_plan_starts_in_draft(api):
    """PRD §3.2: "The new plan starts `DRAFT`."

    Design: Corner/state_machines/route_plan_starts_in_draft
    """
    unit = create_unit()
    plan = create_route_plan(unit["id"])
    assert plan["status"] == "DRAFT", f"New plan must start DRAFT, got {plan['status']}"


def test_publish_empty_plan_rejected(api):
    """PRD §3.2: "Publishing requires the plan to be `DRAFT` and to contain at
    least one site day: a publish against a non-draft plan fails with
    `ERR_PLAN_NOT_PUBLISHED`, and an empty plan fails with
    `ERR_EMPTY_ROUTE_PLAN`."

    Design: Corner/state_machines/publish_empty_plan_rejected
    """
    unit = create_unit()
    plan = create_route_plan(unit["id"])
    resp = api.publish_route_plan(plan["id"], OPS)
    validate_error(resp, ApiErrorId.ERR_EMPTY_ROUTE_PLAN)


def test_route_plan_publish_unpublish_publish_cycle(api):
    """PRD §3.2: "Unpublishing returns a `PUBLISHED` plan to `DRAFT`, but only
    when every one of its days is still `SCHEDULED` or already `CANCELLED`; a
    plan with any day past scheduling is rejected with
    `ERR_PLAN_HAS_ACTIVE_DAYS`, and a plan that is not `PUBLISHED` is rejected
    with `ERR_PLAN_NOT_PUBLISHED`. The `DRAFT` → `PUBLISHED` → `DRAFT` cycle
    may repeat freely."

    Design: Corner/state_machines/route_plan_publish_unpublish_publish_cycle
    """
    bundle = setup_bookable_day()  # plan PUBLISHED with one SCHEDULED day
    plan_id = bundle["plan"]["id"]

    resp1 = api.unpublish_route_plan(plan_id, OPS)
    data1 = validate_success(resp1)
    assert data1["status"] == "DRAFT", f"After unpublish expected DRAFT, got {data1['status']}"

    resp2 = api.publish_route_plan(plan_id, OPS)
    data2 = validate_success(resp2)
    assert data2["status"] == "PUBLISHED", (
        f"After re-publish expected PUBLISHED, got {data2['status']}"
    )


def test_plan_week_conflict_on_published_plan(api):
    """PRD §3.2: "If a plan already exists for the same unit and week start and
    it is still `DRAFT`, that earlier plan is automatically moved to
    `SUPERSEDED` and the new plan's `supersedes_plan_id` points at it; if the
    earlier plan is `PUBLISHED` or `LOCKED`, the create instead fails with
    `ERR_PLAN_WEEK_CONFLICT`."

    Design: Corner/errors/plan_week_conflict_on_published_plan
    """
    bundle = setup_bookable_day()  # week 2026-08-03, PUBLISHED
    unit = get_unit_fresh(bundle["unit"]["id"])
    payload = create_route_plan_payload(
        bundle["unit"]["id"], "2026-08-03", unit["version"]
    )
    resp = api.create_route_plan(payload, OPS)
    validate_error(resp, ApiErrorId.ERR_PLAN_WEEK_CONFLICT)


def test_draft_plan_superseded_by_new_plan(api):
    """PRD §3.2: "If a plan already exists for the same unit and week start and
    it is still `DRAFT`, that earlier plan is automatically moved to
    `SUPERSEDED` and the new plan's `supersedes_plan_id` points at it; if the
    earlier plan is `PUBLISHED` or `LOCKED`, the create instead fails with
    `ERR_PLAN_WEEK_CONFLICT`."

    Design: Corner/errors/draft_plan_superseded_by_new_plan
    """
    unit = create_unit()
    plan1 = create_route_plan(unit["id"], week_start_date="2026-08-03")
    plan2 = create_route_plan(unit["id"], week_start_date="2026-08-03")

    assert plan2["supersedes_plan_id"] == plan1["id"], (
        f"New plan supersedes_plan_id must be {plan1['id']}, got {plan2['supersedes_plan_id']}"
    )
    old = validate_success(api.get_route_plan(plan1["id"], OPS))
    assert old["status"] == "SUPERSEDED", (
        f"Superseded draft plan must be SUPERSEDED, got {old['status']}"
    )


def test_route_plan_computed_site_day_count(api):
    """PRD §3.2: "A created day starts `SCHEDULED`, its `unit_id` is
    denormalized from the plan at creation, and the plan's `version` increments
    by one while its `site_day_count` — the count of the plan's site days in
    any status — increases by one."

    Design: Corner/entities/route_plan_computed_site_day_count
    """
    bundle = setup_bookable_day(publish=False)
    # The bundle created the plan (count 0) then added one site day; a second
    # plan on a fresh week gives the clean 0 -> 2 progression.
    plan2 = create_route_plan(bundle["unit"]["id"], week_start_date="2026-08-10")
    assert plan2["site_day_count"] == 0, (
        f"Fresh plan site_day_count must be 0, got {plan2['site_day_count']}"
    )
    add_site_day(plan2["id"], bundle["facility"]["id"], bundle["contract"]["id"], "2026-08-11")
    add_site_day(plan2["id"], bundle["facility"]["id"], bundle["contract"]["id"], "2026-08-12")
    after = validate_success(api.get_route_plan(plan2["id"], OPS))
    assert after["site_day_count"] == 2, (
        f"Plan with two site days must report site_day_count 2, got {after['site_day_count']}"
    )


def test_version_increments_on_every_mutation(api):
    """PRD §2.5: "`version` (integer): a system-managed integer that increments
    with every modification to the resource, including mutations caused by
    cascades and recomputed derived fields. Newly created resources begin at
    `version` 1."
    PRD §3.2: "A created day starts `SCHEDULED`, its `unit_id` is denormalized
    from the plan at creation, and the plan's `version` increments by one while
    its `site_day_count` — the count of the plan's site days in any status —
    increases by one."

    Design: Corner/cross_cutting_layers/version_increments_on_every_mutation
    """
    bundle = setup_bookable_day(publish=False)
    plan_id = bundle["plan"]["id"]
    # Bundle created the plan (v1) then one site day (v2).
    assert bundle["plan"]["version"] == 1, (
        f"Plan version at create must be 1, got {bundle['plan']['version']}"
    )
    after_day = validate_success(api.get_route_plan(plan_id, OPS))
    assert after_day["version"] == 2, (
        f"Site-day creation must bump plan version to 2, got {after_day['version']}"
    )
    published = validate_success(api.publish_route_plan(plan_id, OPS))
    assert published["version"] == 3, (
        f"Publish must bump plan version to 3, got {published['version']}"
    )
    unpublished = validate_success(api.unpublish_route_plan(plan_id, OPS))
    assert unpublished["version"] == 4, (
        f"Unpublish must bump plan version to 4, got {unpublished['version']}"
    )


def test_occ_stale_unit_version_on_route_plan_create(api):
    """PRD §2.7: "Creating a route plan requires the request body to carry
    `expected_unit_version`, the `version` of the target `MobileImagingUnit` as
    the client last observed it. If the unit's current `version` has advanced
    since that observation — for example because another plan creation for the
    same unit and week has already legitimately superseded the prior draft —
    the create is rejected with `ERR_STALE_UNIT_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_layers/occ_stale_unit_version_on_route_plan_create
    """
    unit = create_unit()
    assert unit["version"] == 1
    first = create_route_plan_payload(unit["id"], "2026-08-03", unit["version"])
    resp1 = api.create_route_plan(first, OPS)
    validate_success(resp1, 201)

    stale = create_route_plan_payload(unit["id"], "2026-08-10", 1)
    resp2 = api.create_route_plan(stale, OPS)
    validate_error(resp2, ApiErrorId.ERR_STALE_UNIT_VERSION)


def test_route_plan_not_found_returns_404(api):
    """PRD §2.8: "The existence family comprises `ERR_FACILITY_NOT_FOUND`,
    `ERR_UNIT_NOT_FOUND`, `ERR_CONTRACT_NOT_FOUND`, `ERR_ROUTE_PLAN_NOT_FOUND`,
    `ERR_SITE_DAY_NOT_FOUND`, ... and the generic `ERR_NOT_FOUND`."

    Design: Corner/errors/route_plan_not_found_returns_404
    """
    resp = api.get_route_plan(NON_EXISTENT_UUID, OPS)
    validate_error(resp, ApiErrorId.ERR_ROUTE_PLAN_NOT_FOUND)
