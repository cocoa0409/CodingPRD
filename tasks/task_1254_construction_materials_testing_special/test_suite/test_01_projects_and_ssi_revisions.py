"""Project registration and the statement-of-special-inspections lifecycle:
creation defaults, permit uniqueness, revision snapshot semantics, approval
supersession, rejection finality, and the approval optimistic-concurrency rule."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    TEST_USERS,
    approve_decision_payload,
    approve_revision,
    assert_iso8601_millis,
    create_project,
    create_project_payload,
    create_ssi_revision,
    create_ssi_revision_payload,
    get_project,
    get_revision,
    get_scope_items,
    is_valid_uuid,
    soil_scope_item,
    submit_revision,
    validate_error,
    validate_success,
    weld_scope_item,
)

ADMIN = TEST_USERS["agency_admin_headers"]
PM = TEST_USERS["project_manager_headers"]
ENGINEER = TEST_USERS["engineer_of_record_headers"]


def test_create_project_applies_server_defaults(api):
    """PRD §3.1: "A new project starts in `ACTIVE` status with
    `compliance_posture` of `IN_PROGRESS`, an `open_ncr_count` of zero,
    `letter_status` of `NONE`, and no approved statement yet —
    `current_approved_ssi_id`, `letter_issued_at`, `letter_issued_by`, and
    `letter_void_reason` are all null."
    PRD §2.4: "The `id` is a server-minted UUID with no type prefix; whenever a
    URL contains an `{id}` segment, it refers to this value. `created_at` and
    `updated_at` are ISO 8601 UTC timestamps with three fractional digits,
    stamped from the logical clock described in §2.5."

    Design: Corner/entities/create_project_defaults_applied
    """
    data = validate_success(
        api.create_project(
            create_project_payload(name="Defaults", permit_number="P-ENT-1"), ADMIN
        ),
        201,
    )
    assert is_valid_uuid(data["id"]), "id must be a server-minted UUID"
    assert data["status"] == "ACTIVE"
    assert data["compliance_posture"] == "IN_PROGRESS"
    assert data["open_ncr_count"] == 0
    assert data["letter_status"] == "NONE"
    assert data["current_approved_ssi_id"] is None
    assert data["letter_issued_at"] is None
    assert data["letter_issued_by"] is None
    assert data["letter_void_reason"] is None
    assert isinstance(data["version"], int), "version is an integer per PRD §2.4"
    assert_iso8601_millis(data["created_at"])
    assert_iso8601_millis(data["updated_at"])


def test_get_project_unknown_id_returns_not_found(api):
    """PRD §2.8: "Where a URL nests resources — a project's SSI revisions, an
    assignment's field tests, a lab's samples — path identifiers are validated
    left to right: the project first, then the revision, assignment, sample,
    test, report, or ticket. The first segment that fails to resolve yields
    `ERR_NOT_FOUND`."

    Design: Corner/entities/get_project_not_found_returns_404
    """
    resp = api.get_project(NON_EXISTENT_UUID, PM)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
    assert resp.status_code == 404


def test_duplicate_permit_number_rejected(api):
    """PRD §3.1: "The permit number is unique across all projects; a duplicate
    is rejected with `ERR_VALIDATION`."

    Design: Corner/entities/duplicate_permit_number_rejected
    """
    first = validate_success(
        api.create_project(create_project_payload(name="First", permit_number="P-ENT-2"), ADMIN),
        201,
    )
    resp = api.create_project(
        create_project_payload(
            name="Second",
            permit_number="P-ENT-2",
            jurisdiction="City B",
            contractor_name="Other Co",
            building_official_name="BO Jones",
        ),
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_VALIDATION)
    assert resp.status_code == 400
    reread = validate_success(api.get_project(first["id"], ADMIN), 200)
    assert reread["name"] == "First", "the first project remains intact"
    assert reread["permit_number"] == "P-ENT-2"


def test_revision_created_with_scope_item_snapshot(api):
    """PRD §3.1: "A revision receives its `revision_number` automatically — a
    per-project monotone sequence starting at 1, assigned in creation order —
    and starts in `DRAFT`."
    PRD §3.1: "Scope items are born with `completed_count` zero and `status` of
    `OPEN`, each pinned to its owning revision via `ssi_revision_id`, and a
    listing of a revision's scope items returns them in creation order."

    Design: Corner/entities/scope_items_created_as_revision_snapshot
    """
    project = create_project(name="Snapshot", permit_number="P-ENT-3")
    ssi = validate_success(
        api.create_ssi_revision(
            project["id"],
            create_ssi_revision_payload(
                [
                    soil_scope_item(description="pad"),
                    weld_scope_item(description="frames", required_cert_level=2,
                                    required_count=3),
                ],
                specified_fc_psi=4000,
            ),
            PM,
        ),
        201,
    )
    assert ssi["status"] == "DRAFT"
    assert ssi["revision_number"] == 1
    items = validate_success(api.list_scope_items(ssi["id"], PM), 200)
    assert len(items) == 2
    assert items[0]["status"] == "OPEN" and items[0]["completed_count"] == 0
    assert items[1]["status"] == "OPEN" and items[1]["completed_count"] == 0
    assert items[0]["test_method"] == "SOIL_COMPACTION"
    assert items[1]["test_method"] == "WELD_VISUAL"


def test_approving_second_revision_supersedes_first(api):
    """PRD §3.1: "Approval moves the revision `SUBMITTED → APPROVED`, stamps
    `approved_at`, flips any previously approved revision of the same project
    to `SUPERSEDED`, points the project's `current_approved_ssi_id` at the
    newly approved revision, increments the project's `version` by one, and
    recomputes the project's compliance posture."

    Design: Corner/state_machines/ssi_approve_supersedes_prior_revision
    """
    project = create_project(name="Supersede", permit_number="P-SM-1")
    r1 = create_ssi_revision(
        project["id"], [weld_scope_item(description="frames")], specified_fc_psi=4000
    )
    submit_revision(r1["id"])
    approve_revision(r1["id"], project["id"])
    r2 = create_ssi_revision(
        project["id"], [weld_scope_item(description="frames v2", required_count=2)],
        specified_fc_psi=4500,
    )
    submit_revision(r2["id"])
    approve_revision(r2["id"], project["id"])

    r1_after = get_revision(r1["id"])
    r2_after = get_revision(r2["id"])
    assert r1_after["status"] == "SUPERSEDED", "prior APPROVED revision flips to SUPERSEDED"
    assert r2_after["status"] == "APPROVED"
    project_after = get_project(project["id"])
    assert project_after["current_approved_ssi_id"] == r2["id"]


def test_rejected_revision_is_terminal(api):
    """PRD §3.1: "Rejection moves the revision `SUBMITTED → REJECTED`, terminal,
    and still increments the project `version` by one."
    PRD §3.1: "Submission by a `ProjectManager` moves it `DRAFT → SUBMITTED` and
    stamps `submitted_at` from the clock; submitting an empty revision with no
    scope items is rejected with `ERR_INVALID_STATE`, and submission under a
    completed project fails with `ERR_PROJECT_COMPLETED`."

    Design: Corner/state_machines/ssi_reject_is_terminal_lockdown
    """
    project = create_project(name="Reject", permit_number="P-SM-2")
    r1 = create_ssi_revision(
        project["id"], [weld_scope_item(description="frames")], specified_fc_psi=4000
    )
    submit_revision(r1["id"])
    rejected = approve_revision(r1["id"], project["id"], decision="REJECT")
    assert rejected["status"] == "REJECTED"

    resp = api.submit_ssi_revision(r1["id"], PM)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    assert get_revision(r1["id"])["status"] == "REJECTED", "REJECTED is terminal"


def test_approve_with_stale_project_version_rejected(api):
    """PRD §2.7: "That request must carry `expected_project_version`, a
    non-optional field holding the `version` of the parent project as the
    client last observed it. If the project's current `version` has advanced
    beyond what the client saw — because another approval or rejection landed
    in the meantime — the decision is rejected with `ERR_STALE_VERSION`
    (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/ssi_approve_occ_stale_version_rejected
    """
    project = create_project(name="OCC", permit_number="P-OCC-1")
    observed_version = project["version"]
    r1 = create_ssi_revision(
        project["id"], [weld_scope_item(description="frames r1")], specified_fc_psi=4000
    )
    submit_revision(r1["id"])
    r2 = create_ssi_revision(
        project["id"], [weld_scope_item(description="frames r2")], specified_fc_psi=4500
    )
    submit_revision(r2["id"])

    approved = validate_success(
        api.approve_ssi_revision(
            r1["id"], approve_decision_payload("APPROVE", observed_version), ENGINEER
        ),
        200,
    )
    assert approved["status"] == "APPROVED", "first approval against the observed version succeeds"

    stale = api.approve_ssi_revision(
        r2["id"], approve_decision_payload("APPROVE", observed_version), ENGINEER
    )
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION)
    assert stale.status_code == 412

    fresh_version = get_project(project["id"])["version"]
    approved2 = validate_success(
        api.approve_ssi_revision(
            r2["id"], approve_decision_payload("APPROVE", fresh_version), ENGINEER
        ),
        200,
    )
    assert approved2["status"] == "APPROVED", "re-reading the version and resubmitting succeeds"
    assert get_revision(r1["id"])["status"] == "SUPERSEDED"
