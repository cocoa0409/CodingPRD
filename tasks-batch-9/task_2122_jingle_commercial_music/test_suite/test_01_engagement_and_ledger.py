"""Opening an engagement, freezing it, resuming it, and the budget posture gate."""
from test_helpers import (
    ApiErrorId,
    assert_ledger,
    assert_project,
    create_client,
    create_composer,
    create_project,
    get_project,
    make_composer_headers,
    make_producer_headers,
    pitch_demo,
    setup_engagement_in_demo,
    setup_engagement_in_production,
    create_studio_room,
    schedule_session_call,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.factories import create_project_payload


def test_opening_an_engagement_seeds_the_whole_budget_as_available(api):
    """PRD §3.2: "The engagement opens in `DRAFT` with its whole budget free:
    `available_cents` equal to `budget_cents`, `committed_cents` and `spent_cents`
    at zero, `budget_posture` at `HEALTHY`, and `status_before_hold` null."
    PRD §2.4: "`version` is an integer that starts at 1 when the row is created
    and increases by exactly 1 on every mutation of that row, cascade-driven
    mutations included."

    Design: Corner/entities/corner_project_creation_seeds_the_full_budget_ledger
    """
    client = create_client(name="Harborline Foods")
    response = api.create_project(
        create_project_payload(client["id"], title="Winter Warmth", budget_cents=1_200_000,
                               delivery_deadline_utc="2026-12-01T00:00:00Z"),
        make_producer_headers())
    project = validate_success(response, 201)
    assert_project(project)
    assert project["status"] == "DRAFT", f"Expected DRAFT, got {project['status']}"
    assert project["version"] == 1, f"Expected version 1, got {project['version']}"
    assert project["budget_cents"] == 1_200_000
    assert_ledger(project, committed=0, available=1_200_000, spent=0)
    assert project["budget_posture"] == "HEALTHY"
    assert project["status_before_hold"] is None, (
        f"Expected status_before_hold null, got {project['status_before_hold']}")


def test_unknown_engagement_id_is_reported_as_not_found(api):
    """PRD §2.5: "**Path existence.** Every identifier embedded in the request path
    resolves to a live row, validated from left to right, on every endpoint that has
    one — otherwise `ERR_PROJECT_NOT_FOUND`, `ERR_BRIEF_NOT_FOUND`, `ERR_DEMO_NOT_FOUND`,
    `ERR_MUSICIAN_NOT_FOUND`, `ERR_SESSION_CALL_NOT_FOUND`, `ERR_BOOKING_NOT_FOUND`,
    `ERR_LICENSE_DEAL_NOT_FOUND`, `ERR_DELIVERABLE_NOT_FOUND` or
    `ERR_CUE_ENTRY_NOT_FOUND` (404)."

    Design: Corner/entities/corner_unknown_project_id_returns_project_not_found
    """
    create_client(name="Harborline Foods")
    response = api.get_project("8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2", make_producer_headers())
    validate_error(response, ApiErrorId.ERR_PROJECT_NOT_FOUND.value, 404)


def test_engagement_creation_without_a_budget_is_rejected(api):
    """PRD §3.2: "A campaign engagement is opened by a `MusicHouseProducer` against a
    registered advertiser, naming the `client_id` that will govern every later
    ownership check, a campaign `title`, an approved `budget_cents` figure strictly
    greater than zero, and the client's air-date `delivery_deadline_utc`."
    PRD §2.5: "**Request shape.** On every write endpoint, all required body fields are
    present, every enum-typed value is a declared member, every integer respects its
    declared range, and every array field is non-empty and free of duplicates —
    otherwise `ERR_INVALID_REQUEST` (400)."

    Design: Corner/entities/corner_project_create_without_budget_cents_is_rejected
    """
    client = create_client(name="Harborline Foods")
    response = api.create_project(
        {"client_id": client["id"], "title": "Winter Warmth",
         "delivery_deadline_utc": "2026-12-01T00:00:00Z"},
        make_producer_headers())
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 400)
    rows, meta = validate_paginated(
        api.list_projects(make_producer_headers(), params={"client_id": client["id"]}))
    assert meta["total_count"] == 0, (
        f"No engagement may be stored for a rejected request; got {meta['total_count']}")


def test_hold_freezes_the_engagement_and_resume_restores_it(api):
    """PRD §3.2: "Freezing captures the engagement's current status into
    `status_before_hold` and moves the engagement to `ON_HOLD` along whichever of the
    three edges applies — `BRIEFING → ON_HOLD`, `IN_DEMO → ON_HOLD` or
    `IN_PRODUCTION → ON_HOLD` — forces `budget_posture` to `FROZEN`, and moves every
    session call of that engagement whose status is `SCHEDULED` to `SUSPENDED_BUDGET`,
    processed in `scheduled_start_utc` ascending order with `created_at` ascending as
    tie-break."
    PRD §3.2: "Resuming is the mirror image and is refused with
    `ERR_PROJECT_NOT_ON_HOLD` unless the engagement is `ON_HOLD`: the engagement's
    status is restored to exactly the value held in `status_before_hold`, so the resume
    edge is `ON_HOLD → IN_PRODUCTION` when the snapshot reads `IN_PRODUCTION`,
    `ON_HOLD → IN_DEMO` when it reads `IN_DEMO`, and `ON_HOLD → BRIEFING` when it reads
    `BRIEFING` — after which `status_before_hold` is set back to null and
    `budget_posture` is recomputed from the ledger."

    Design: Corner/state_machines/corner_hold_freezes_then_resume_restores_status_and_unsuspends_calls
    """
    set_clock("2026-09-01T00:00:00Z")
    env = setup_engagement_in_production(target_markets=["US_LOCAL"], required_lengths=[30])
    room = create_studio_room()
    call = schedule_session_call(env["project"]["id"], room["id"])
    assert call["status"] == "SCHEDULED"

    held = validate_success(api.hold_project(
        env["project"]["id"], {"hold_reason": "client legal review"}, make_producer_headers()))
    assert held["status"] == "ON_HOLD", f"Expected ON_HOLD, got {held['status']}"
    assert held["status_before_hold"] == "IN_PRODUCTION", (
        f"Expected the snapshot IN_PRODUCTION, got {held['status_before_hold']}")
    assert held["budget_posture"] == "FROZEN", f"Expected FROZEN, got {held['budget_posture']}"
    suspended = validate_success(api.get_session_call(call["id"], make_producer_headers()))
    assert suspended["status"] == "SUSPENDED_BUDGET", (
        f"Hold must suspend the SCHEDULED call; got {suspended['status']}")

    resumed = validate_success(api.resume_project(env["project"]["id"], make_producer_headers()))
    assert resumed["status"] == "IN_PRODUCTION", f"Expected IN_PRODUCTION, got {resumed['status']}"
    assert resumed["status_before_hold"] is None, (
        f"Expected status_before_hold back to null, got {resumed['status_before_hold']}")
    assert resumed["budget_posture"] == "HEALTHY", (
        f"Expected HEALTHY, got {resumed['budget_posture']}")
    assert resumed["available_cents"] == 3_900_000, (
        f"Expected available_cents 3900000, got {resumed['available_cents']}")
    restored = validate_success(api.get_session_call(call["id"], make_producer_headers()))
    assert restored["status"] == "SCHEDULED", (
        f"A HEALTHY resume must return the call to SCHEDULED; got {restored['status']}")


def test_hold_and_resume_guards_reject_wrong_starting_states(api):
    """PRD §3.2: "A producer may freeze an engagement that is in `BRIEFING`, `IN_DEMO`
    or `IN_PRODUCTION`, supplying a `hold_reason`; any other status is refused with
    `ERR_PROJECT_NOT_HOLDABLE`."
    PRD §3.2: "Resuming is the mirror image and is refused with
    `ERR_PROJECT_NOT_ON_HOLD` unless the engagement is `ON_HOLD`: the engagement's
    status is restored to exactly the value held in `status_before_hold`, so the resume
    edge is `ON_HOLD → IN_PRODUCTION` when the snapshot reads `IN_PRODUCTION`,
    `ON_HOLD → IN_DEMO` when it reads `IN_DEMO`, and `ON_HOLD → BRIEFING` when it reads
    `BRIEFING` — after which `status_before_hold` is set back to null and
    `budget_posture` is recomputed from the ledger."

    Design: Corner/errors/corner_hold_and_resume_guards_reject_wrong_starting_states
    """
    client = create_client(name="Harborline Foods")
    project = create_project(client["id"], title="Winter Warmth", budget_cents=4_000_000)
    assert project["status"] == "DRAFT"

    validate_error(
        api.hold_project(project["id"], {"hold_reason": "too early"}, make_producer_headers()),
        ApiErrorId.ERR_PROJECT_NOT_HOLDABLE.value, 409)
    validate_error(
        api.resume_project(project["id"], make_producer_headers()),
        ApiErrorId.ERR_PROJECT_NOT_ON_HOLD.value, 409)

    after = get_project(project["id"])
    assert after["status"] == "DRAFT", f"Expected DRAFT, got {after['status']}"
    assert after["status_before_hold"] is None
    assert after["budget_posture"] == "HEALTHY"


def test_stage_gates_reject_a_late_brief_and_a_late_demo(api):
    """PRD §3.2: "Attempting to attach a brief to an engagement in any other status is
    refused with `ERR_PROJECT_NOT_IN_BRIEFING`."
    PRD §3.3: "Creation is refused with `ERR_PROJECT_NOT_IN_DEMO` unless the engagement
    is in `IN_DEMO`."

    Design: Corner/errors/corner_project_stage_gates_reject_a_late_brief_and_a_late_demo
    """
    set_clock("2026-09-01T00:00:00Z")
    env = setup_engagement_in_production()

    validate_error(
        api.create_brief(env["project"]["id"],
                         {"tempo_bpm": 100, "mood_tags": ["late"],
                          "target_markets": ["US_LOCAL"], "required_lengths": [15]},
                         make_producer_headers()),
        ApiErrorId.ERR_PROJECT_NOT_IN_BRIEFING.value, 409)
    validate_error(
        api.create_demo(env["project"]["id"],
                        {"title": "Cut Two", "demo_fee_cents": 50_000,
                         "submitted_length_seconds": 30},
                        make_composer_headers(env["composer"]["id"])),
        ApiErrorId.ERR_PROJECT_NOT_IN_DEMO.value, 409)

    _, brief_meta = validate_paginated(
        api.list_project_briefs(env["project"]["id"], make_producer_headers()))
    assert brief_meta["total_count"] == 1, (
        f"The late brief must not be stored; got {brief_meta['total_count']} briefs")
    _, demo_meta = validate_paginated(
        api.list_demos(make_producer_headers(), params={"project_id": env["project"]["id"]}))
    assert demo_meta["total_count"] == 1, (
        f"The late demo must not be stored; got {demo_meta['total_count']} demos")
    project = get_project(env["project"]["id"])
    assert_ledger(project, committed=0, available=3_900_000, spent=100_000)


def test_posture_is_healthy_when_available_is_exactly_a_quarter_of_the_budget(api):
    """PRD §2.7: "Otherwise, the posture is `CONSTRAINED` when `available_cents`
    multiplied by 100 is strictly less than 25 multiplied by `budget_cents` — that is,
    when strictly less than a quarter of the original budget remains free — and
    `HEALTHY` in every other case."
    PRD §2.7: "**The boundary is strict:** an engagement sitting on exactly a quarter
    of its budget is `HEALTHY`, not `CONSTRAINED`."

    Design: Difficulty/boundary_precision_check/posture_stays_healthy_when_available_is_exactly_twenty_five_percent
    """
    set_clock("2026-09-01T00:00:00Z")
    env = setup_engagement_in_demo(budget_cents=500_000)
    composer = create_composer(index=0)
    response = api.create_demo(
        env["project"]["id"],
        {"title": "Edge Cut", "demo_fee_cents": 375_000, "submitted_length_seconds": 30},
        make_composer_headers(composer["id"]))
    demo = validate_success(response, 201)
    assert demo["status"] == "DRAFT", f"Expected DRAFT, got {demo['status']}"
    assert demo["accrued_fee_cents"] == 375_000

    project = get_project(env["project"]["id"])
    assert_ledger(project, committed=375_000, available=125_000, spent=0)
    assert project["budget_posture"] == "HEALTHY", (
        "125000 * 100 == 25 * 500000 sits exactly on the boundary and must stay HEALTHY; "
        f"got {project['budget_posture']}")


def test_posture_turns_constrained_one_cent_below_the_quarter_boundary(api):
    """PRD §2.7: "Otherwise, the posture is `CONSTRAINED` when `available_cents`
    multiplied by 100 is strictly less than 25 multiplied by `budget_cents` — that is,
    when strictly less than a quarter of the original budget remains free — and
    `HEALTHY` in every other case."

    Design: Difficulty/boundary_precision_check/posture_stays_healthy_when_available_is_exactly_twenty_five_percent
    """
    set_clock("2026-09-01T00:00:00Z")
    env = setup_engagement_in_demo(budget_cents=500_000)
    composer = create_composer(index=0)
    demo = pitch_demo(env["project"]["id"], composer["id"],
                      title="Edge Cut", demo_fee_cents=375_001, submitted_length_seconds=30)
    assert demo["accrued_fee_cents"] == 375_001

    project = get_project(env["project"]["id"])
    assert_ledger(project, committed=375_001, available=124_999, spent=0)
    assert project["budget_posture"] == "CONSTRAINED", (
        "124999 * 100 is strictly below 25 * 500000, so the posture must be CONSTRAINED; "
        f"got {project['budget_posture']}")
