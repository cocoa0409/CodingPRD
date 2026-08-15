"""Rigging plan lifecycle: optimistic concurrency, open-plan constraint,
weight gate, revision cycle, approval pin, and the supersede cascade
(PRD section 3.4)."""
from test_helpers import (
    ApiErrorId,
    create_approved_rigging_plan,
    create_project,
    create_rigging_plan_payload,
    find_lift_permit,
    find_rigging_plan,
    get_project,
    setup_project_installing,
    setup_project_with_approved_rigging,
    validate_error,
    validate_success,
)


def test_rigging_open_exists(api, pm_headers, sup_headers):
    """PRD section 3.4: "Only one rigging plan may be open at a time per
    project — if another plan already exists in `DRAFT` or `SUBMITTED`,
    creation is rejected with `ERR_RIGGING_PLAN_OPEN_EXISTS`."

    Design: Corner/validations/rigging_open_exists
    """
    project = create_project(name="Open Plan Job", site_address="44 Plant Rd")
    first = validate_success(
        api.create_rigging_plan(
            create_rigging_plan_payload(
                project_id=project["id"],
                expected_project_version=project["version"],
            ),
            sup_headers,
        ),
        201,
    )
    assert first["status"] == "DRAFT"

    current_version = get_project(project["id"])["version"]
    resp = api.create_rigging_plan(
        create_rigging_plan_payload(
            project_id=project["id"],
            expected_project_version=current_version,  # current: OCC passes
            lift_weight_tons=41,
        ),
        sup_headers,
    )
    validate_error(resp, ApiErrorId.ERR_RIGGING_PLAN_OPEN_EXISTS)


def test_occ_stale_version_rejected(api, pm_headers, sup_headers):
    """PRD section 2.7: "If the supplied value does not match the project's
    current `version`, the creation is rejected with `ERR_STALE_VERSION`
    (HTTP 412)."
    PRD section 3.4: "Each new plan receives a 1-based `revision` equal to the
    count of prior rigging plans for the project plus one, starts as `DRAFT`,
    and has its `weight_check_passed` computed immediately: true when
    `lift_weight_tons` is no more than `planned_crane_capacity_tons`, with
    equality passing."

    Design: Corner/complexity_layers/occ_stale_version_rejected
    """
    project = create_project(name="OCC Job", site_address="64 Plant Rd")
    plan1 = validate_success(
        api.create_rigging_plan(
            create_rigging_plan_payload(
                project_id=project["id"],
                expected_project_version=project["version"],
            ),
            sup_headers,
        ),
        201,
    )
    validate_success(api.submit_rigging_plan(plan1["id"], sup_headers))
    validate_success(
        api.review_rigging_plan(
            plan1["id"], {"outcome": "REJECTED", "reviewer_note": "redo"}, pm_headers
        )
    )

    current_version = get_project(project["id"])["version"]
    resp = api.create_rigging_plan(
        create_rigging_plan_payload(
            project_id=project["id"],
            expected_project_version=current_version - 1,  # one behind: stale
            lift_weight_tons=41,
        ),
        sup_headers,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION, 412)


def test_occ_current_version_create_succeeds(api, pm_headers, sup_headers):
    """PRD section 2.7: "That request must carry `expected_project_version`,
    a non-optional field holding the `version` of the parent project as the
    client last observed it."
    PRD section 3.4: "Each new plan receives a 1-based `revision` equal to the
    count of prior rigging plans for the project plus one, starts as `DRAFT`,
    and has its `weight_check_passed` computed immediately: true when
    `lift_weight_tons` is no more than `planned_crane_capacity_tons`, with
    equality passing."

    Design: Corner/complexity_layers/occ_stale_version_rejected
    """
    project = create_project(name="OCC Job", site_address="64 Plant Rd")
    plan1 = validate_success(
        api.create_rigging_plan(
            create_rigging_plan_payload(
                project_id=project["id"],
                expected_project_version=project["version"],
            ),
            sup_headers,
        ),
        201,
    )
    validate_success(api.submit_rigging_plan(plan1["id"], sup_headers))
    validate_success(
        api.review_rigging_plan(plan1["id"], {"outcome": "REJECTED"}, pm_headers)
    )

    current_version = get_project(project["id"])["version"]
    plan2 = validate_success(
        api.create_rigging_plan(
            create_rigging_plan_payload(
                project_id=project["id"],
                expected_project_version=current_version,
                lift_weight_tons=41,
            ),
            sup_headers,
        ),
        201,
    )
    assert plan2["status"] == "DRAFT"
    assert plan2["revision"] == 2, (
        f"Second plan for the project must receive revision 2, got {plan2['revision']}"
    )


def test_version_pinning_on_approval(api, pm_headers):
    """PRD section 3.4: "On approval, the project pins the plan —
    `approved_rigging_plan_id` is set to this plan's id and
    `approved_rigging_plan_revision` to this plan's `revision` — and the
    project `version` increments by one."

    Design: Corner/complexity_layers/version_pinning_on_approval
    """
    ctx = setup_project_installing(name="Pin Job", site_address="65 Plant Rd")
    project = ctx["project"]
    before_version = project["version"]
    plan = create_approved_rigging_plan(project["id"])

    pinned = get_project(project["id"])
    assert pinned["approved_rigging_plan_id"] == plan["id"]
    assert pinned["approved_rigging_plan_revision"] == plan["revision"] == 1
    assert pinned["version"] > before_version, (
        "Approval must increment the project version"
    )


def test_lift_weight_exceeded(api, pm_headers, sup_headers):
    """PRD section 3.4: "Approval is gated twice: some site survey of the
    project must stand `ACCEPTED` (otherwise `ERR_SITE_SURVEY_NOT_ACCEPTED`),
    and the plan's `weight_check_passed` must be true (otherwise
    `ERR_LIFT_WEIGHT_EXCEEDED`)."

    Design: Corner/validations/lift_weight_exceeded
    """
    ctx = setup_project_installing(name="Weight Job", site_address="47 Plant Rd")
    project = ctx["project"]
    plan = validate_success(
        api.create_rigging_plan(
            create_rigging_plan_payload(
                project_id=project["id"],
                expected_project_version=project["version"],
                lift_weight_tons=60,
                planned_crane_capacity_tons=50,
            ),
            sup_headers,
        ),
        201,
    )
    assert plan["weight_check_passed"] is False, (
        "60t against a 50t planned capacity must fail the weight check"
    )
    validate_success(api.submit_rigging_plan(plan["id"], sup_headers))

    resp = api.review_rigging_plan(plan["id"], {"outcome": "APPROVED"}, pm_headers)
    validate_error(resp, ApiErrorId.ERR_LIFT_WEIGHT_EXCEEDED)

    assert find_rigging_plan(project["id"], plan["id"])["status"] == "SUBMITTED"
    assert get_project(project["id"])["approved_rigging_plan_id"] is None


def test_rigging_revise_from_approved_rejected(api, sup_headers):
    """PRD section 3.4: "The `SiteSupervisor` may revise a `REJECTED` plan,
    which returns the same row to `DRAFT`; the revision request optionally
    supplies new `lift_weight_tons`, `planned_crane_capacity_tons`,
    `crane_model`, or `rigging_config` values, any supplied field replaces the
    prior value, and `weight_check_passed` is recomputed when the inputs
    changed."

    Design: Corner/state_machines/rigging_revise_from_approved_rejected
    """
    ctx = setup_project_with_approved_rigging(name="SM3 Job", site_address="25 Plant Rd")
    plan = ctx["rigging_plan"]
    assert plan["status"] == "APPROVED"

    resp = api.revise_rigging_plan(plan["id"], {"lift_weight_tons": 41}, sup_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    assert find_rigging_plan(ctx["project"]["id"], plan["id"])["status"] == "APPROVED"
    pinned = get_project(ctx["project"]["id"])
    assert pinned["approved_rigging_plan_id"] == plan["id"], "Pin must remain intact"


def test_rejected_plan_returns_to_draft_via_revise(api, pm_headers, sup_headers):
    """PRD section 3.4: "The `SiteSupervisor` may revise a `REJECTED` plan,
    which returns the same row to `DRAFT`; the revision request optionally
    supplies new `lift_weight_tons`, `planned_crane_capacity_tons`,
    `crane_model`, or `rigging_config` values, any supplied field replaces the
    prior value, and `weight_check_passed` is recomputed when the inputs
    changed."

    Design: Difficulty/non_linear_state_machine/rigging_plan_revision_cycle
    """
    ctx = setup_project_installing(name="Cycle Job", site_address="5 Plant Rd")
    project = ctx["project"]
    plan = validate_success(
        api.create_rigging_plan(
            create_rigging_plan_payload(
                project_id=project["id"],
                expected_project_version=project["version"],
            ),
            sup_headers,
        ),
        201,
    )
    validate_success(api.submit_rigging_plan(plan["id"], sup_headers))
    rejected = validate_success(
        api.review_rigging_plan(
            plan["id"],
            {"outcome": "REJECTED", "reviewer_note": "recheck sling angles"},
            pm_headers,
        )
    )
    assert rejected["status"] == "REJECTED"

    drafted = validate_success(
        api.revise_rigging_plan(plan["id"], {"lift_weight_tons": 45}, sup_headers)
    )
    assert drafted["status"] == "DRAFT", "Revise returns the same row to DRAFT"
    assert drafted["id"] == plan["id"], "The revision loop reuses the same row"
    assert drafted["lift_weight_tons"] == 45, "Supplied fields replace prior values"


def test_revised_plan_approves_with_same_revision(api, pm_headers, sup_headers):
    """PRD section 3.4: "The same row therefore cycles `DRAFT` → `SUBMITTED` →
    `REJECTED` → `DRAFT` as many times as review requires."
    PRD section 3.4: "On approval, the project pins the plan —
    `approved_rigging_plan_id` is set to this plan's id and
    `approved_rigging_plan_revision` to this plan's `revision` — and the
    project `version` increments by one."

    Design: Difficulty/non_linear_state_machine/rigging_plan_revision_cycle
    """
    ctx = setup_project_installing(name="Cycle Job", site_address="5 Plant Rd")
    project = ctx["project"]
    plan = validate_success(
        api.create_rigging_plan(
            create_rigging_plan_payload(
                project_id=project["id"],
                expected_project_version=project["version"],
            ),
            sup_headers,
        ),
        201,
    )
    validate_success(api.submit_rigging_plan(plan["id"], sup_headers))
    validate_success(
        api.review_rigging_plan(plan["id"], {"outcome": "REJECTED"}, pm_headers)
    )
    validate_success(api.revise_rigging_plan(plan["id"], {"lift_weight_tons": 45}, sup_headers))
    validate_success(api.submit_rigging_plan(plan["id"], sup_headers))
    approved = validate_success(
        api.review_rigging_plan(plan["id"], {"outcome": "APPROVED"}, pm_headers)
    )

    assert approved["status"] == "APPROVED"
    assert approved["revision"] == 1, (
        "The row cycled in place; no new plan row was created, so revision stays 1"
    )
    pinned = get_project(project["id"])
    assert pinned["approved_rigging_plan_id"] == plan["id"]
    assert pinned["approved_rigging_plan_revision"] == 1


def test_new_plan_supersedes_approved_and_clears_pin(api, sup_headers):
    """PRD section 3.4: "When a project currently has an `APPROVED` plan
    pinned, the creation of a new plan automatically moves that approved plan
    to `SUPERSEDED`, clears the project's pin (`approved_rigging_plan_id` and
    `approved_rigging_plan_revision` become null), cancels every lift permit of
    the project still in `ISSUED` status — each such permit's approval basis is
    gone — and increments the project's `version` by one."

    Design: Difficulty/transitive_cascade/rigging_supersede_cascade
    """
    ctx = setup_project_with_approved_rigging(name="Supersede Job", site_address="8 Plant Rd")
    project = ctx["project"]
    plan1 = ctx["rigging_plan"]

    current = get_project(project["id"])
    plan2 = validate_success(
        api.create_rigging_plan(
            create_rigging_plan_payload(
                project_id=project["id"],
                expected_project_version=current["version"],
                lift_weight_tons=45,
                planned_crane_capacity_tons=60,
                rigging_config="TANDEM",
            ),
            sup_headers,
        ),
        201,
    )

    assert find_rigging_plan(project["id"], plan1["id"])["status"] == "SUPERSEDED"
    cleared = get_project(project["id"])
    assert cleared["approved_rigging_plan_id"] is None
    assert cleared["approved_rigging_plan_revision"] is None
    assert plan2["status"] == "DRAFT"


def test_supersede_cancels_issued_permits_and_new_plan_is_revision_two(api, sup_headers):
    """PRD section 3.4: "When a project currently has an `APPROVED` plan
    pinned, the creation of a new plan automatically moves that approved plan
    to `SUPERSEDED`, clears the project's pin (`approved_rigging_plan_id` and
    `approved_rigging_plan_revision` become null), cancels every lift permit of
    the project still in `ISSUED` status — each such permit's approval basis is
    gone — and increments the project's `version` by one."
    PRD section 3.4: "Each new plan receives a 1-based `revision` equal to the
    count of prior rigging plans for the project plus one, starts as `DRAFT`,
    and has its `weight_check_passed` computed immediately: true when
    `lift_weight_tons` is no more than `planned_crane_capacity_tons`, with
    equality passing."

    Design: Difficulty/transitive_cascade/rigging_supersede_cascade
    """
    ctx = setup_project_with_approved_rigging(name="Supersede Job", site_address="8 Plant Rd")
    project = ctx["project"]
    permit = validate_success(
        api.create_lift_permit(
            {
                "project_id": project["id"],
                "crane_ref": "CR-7",
                "lift_starts_at": "2026-08-10T10:00:00Z",
                "lift_ends_at": "2026-08-10T14:00:00Z",
                "road_permit_required": False,
            },
            sup_headers,
        ),
        201,
    )
    assert permit["status"] == "ISSUED"

    current = get_project(project["id"])
    plan2 = validate_success(
        api.create_rigging_plan(
            create_rigging_plan_payload(
                project_id=project["id"],
                expected_project_version=current["version"],
                lift_weight_tons=45,
                planned_crane_capacity_tons=60,
                rigging_config="TANDEM",
            ),
            sup_headers,
        ),
        201,
    )

    assert find_lift_permit(project["id"], permit["id"])["status"] == "CANCELLED", (
        "The supersede cascade cancels every ISSUED lift permit of the project"
    )
    assert plan2["status"] == "DRAFT"
    assert plan2["revision"] == 2, (
        f"Second plan row for the project must receive revision 2, got {plan2['revision']}"
    )
