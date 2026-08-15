"""Precision alignment records and the commissioning checklist: tolerance
boundaries, the alignment gate, completeness counting, sign-off authority
(PRD sections 3.6 and 3.7)."""
from test_helpers import (
    ApiErrorId,
    check_all_items,
    create_accepted_passing_alignment,
    create_alignment_record_payload,
    create_checklist,
    create_project,
    get_project,
    setup_project_commissioning,
    setup_project_installing,
    setup_submitted_checklist,
    validate_error,
    validate_success,
)


def test_alignment_at_exact_precision_tolerance_passes(api, sup_headers):
    """PRD section 3.6: "The verdict is computed at creation against the
    declared class, with equality passing on every comparison."
    PRD section 3.6: "A `PRECISION` point tightens those limits to no more
    than 2.0 mils of offset and no more than 0.5 mils per inch of angular
    misalignment."
    PRD section 3.6: "The record exposes both outcomes as `offset_passed` and
    `angular_passed`, and its `verdict` is `PASS` only when both checks
    passed, otherwise `FAIL`."

    Design: Difficulty/boundary_precision_check/alignment_exact_tolerance_passes
    """
    project = create_project(name="Alignment Job", site_address="12 Plant Rd")
    record = validate_success(
        api.create_alignment_record(
            create_alignment_record_payload(
                project_id=project["id"],
                measured_offset_mils=2.0,
                measured_angular_mils_per_in=0.5,
            ),
            sup_headers,
        ),
        201,
    )
    assert record["offset_passed"] is True, "Exactly 2.0 mils equals the PRECISION limit"
    assert record["angular_passed"] is True, "Exactly 0.5 mils/in equals the PRECISION limit"
    assert record["verdict"] == "PASS"


def test_alignment_one_cent_over_tolerance_fails(api, sup_headers):
    """PRD section 3.6: "A `PRECISION` point tightens those limits to no more
    than 2.0 mils of offset and no more than 0.5 mils per inch of angular
    misalignment."
    PRD section 2.8: "Tolerance comparisons for anchors, alignment, and lift
    weight are made in the raw input units with no rounding at all, and in
    every such comparison a value exactly equal to the limit passes."

    Design: Difficulty/boundary_precision_check/alignment_exact_tolerance_passes
    """
    project = create_project(name="Alignment Job", site_address="12 Plant Rd")
    record = validate_success(
        api.create_alignment_record(
            create_alignment_record_payload(
                project_id=project["id"],
                measurement_point="GEARBOX-MOTOR",
                measured_offset_mils=2.01,
                measured_angular_mils_per_in=0.5,
            ),
            sup_headers,
        ),
        201,
    )
    assert record["offset_passed"] is False
    assert record["verdict"] == "FAIL", "2.01 mils exceeds the 2.0 PRECISION limit"


def test_checklist_exists(api, pm_headers):
    """PRD section 3.7: "At most one checklist per project may be non-terminal
    at a time; if one already exists in `IN_PROGRESS` or `SUBMITTED`, creation
    of another is rejected with `ERR_CHECKLIST_EXISTS`."

    Design: Corner/validations/checklist_exists
    """
    ctx = setup_project_installing(name="One Checklist Job", site_address="43 Plant Rd")
    project = ctx["project"]
    create_checklist(project["id"])

    resp = api.create_commissioning_checklist(
        {
            "project_id": project["id"],
            "items": [
                {"item_key": "VIBRATION", "description": "vibration test", "required": True}
            ],
        },
        pm_headers,
    )
    validate_error(resp, ApiErrorId.ERR_CHECKLIST_EXISTS)


def test_checklist_incomplete(api, pm_headers, sup_headers):
    """PRD section 3.7: "Every required item must be checked, so that
    `checked_required_count` equals `required_count` (otherwise
    `ERR_CHECKLIST_INCOMPLETE`)."

    Design: Corner/validations/checklist_incomplete
    """
    ctx = setup_project_commissioning(name="Incomplete Job", site_address="51 Plant Rd")
    project = ctx["project"]
    checklist = create_checklist(
        project["id"],
        items=[
            {"item_key": "GROUT", "description": "grout cured", "required": True},
            {"item_key": "RUN_TEST", "description": "no-load run test", "required": True},
        ],
    )
    assert checklist["required_count"] == 2
    # Alignment gate satisfied; only the completeness count falls short.
    create_accepted_passing_alignment(project["id"])
    validate_success(
        api.check_checklist_item(checklist["id"], {"item_key": "GROUT"}, sup_headers)
    )

    resp = api.submit_commissioning_checklist(checklist["id"], pm_headers)
    validate_error(resp, ApiErrorId.ERR_CHECKLIST_INCOMPLETE)

    checklists = api.list_commissioning_checklists(project["id"], pm_headers).json()["data"]
    assert checklists[0]["status"] == "IN_PROGRESS"
    assert checklists[0]["checked_required_count"] == 1


def test_checklist_signoff_before_submit_rejected(api, cust_headers):
    """PRD section 3.7: "A `CustomerRep` signs off a `SUBMITTED` checklist,
    optionally attaching a `signoff_note`; sign-off moves the checklist to
    `SIGNED_OFF`, records the representative's `X-User-ID` as
    `signed_off_by_user_id`, and increments the project's `version` by one."

    Design: Corner/state_machines/checklist_signoff_before_submit_rejected
    """
    ctx = setup_project_installing(name="SM7 Job", site_address="29 Plant Rd")
    checklist = create_checklist(ctx["project"]["id"])
    assert checklist["status"] == "IN_PROGRESS"

    resp = api.sign_off_checklist(checklist["id"], {}, cust_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    checklists = api.list_commissioning_checklists(ctx["project"]["id"], cust_headers).json()[
        "data"
    ]
    assert checklists[0]["status"] == "IN_PROGRESS"


def test_checklist_submit_blocked_by_pending_alignment(api, pm_headers, sup_headers):
    """PRD section 3.7: "And the alignment gate must be satisfied: at least
    one alignment record of the project must stand `ACCEPTED` with a `verdict`
    of `PASS`, and no alignment record of the project may remain in `RECORDED`
    awaiting review — a project with passing records but unreviewed
    measurements still fails, with `ERR_ALIGNMENT_OUTSTANDING` covering both
    halves of the gate."

    Design: Difficulty/cross_entity_state_dependency/checklist_submit_requires_alignment_clearance
    """
    ctx = setup_project_commissioning(name="Alignment Gate Job", site_address="15 Plant Rd")
    project = ctx["project"]
    checklist = create_checklist(project["id"])
    check_all_items(checklist)
    # A passing measurement that is still RECORDED (awaiting review).
    record = validate_success(
        api.create_alignment_record(
            create_alignment_record_payload(project_id=project["id"]), sup_headers
        ),
        201,
    )
    assert record["verdict"] == "PASS"
    assert record["status"] == "RECORDED"

    resp = api.submit_commissioning_checklist(checklist["id"], pm_headers)
    validate_error(resp, ApiErrorId.ERR_ALIGNMENT_OUTSTANDING)


def test_checklist_submit_after_alignment_acceptance_succeeds(api, pm_headers, sup_headers):
    """PRD section 3.7: "And the alignment gate must be satisfied: at least
    one alignment record of the project must stand `ACCEPTED` with a `verdict`
    of `PASS`, and no alignment record of the project may remain in `RECORDED`
    awaiting review — a project with passing records but unreviewed
    measurements still fails, with `ERR_ALIGNMENT_OUTSTANDING` covering both
    halves of the gate."

    Design: Difficulty/cross_entity_state_dependency/checklist_submit_requires_alignment_clearance
    """
    ctx = setup_project_commissioning(name="Alignment Gate Job", site_address="15 Plant Rd")
    project = ctx["project"]
    checklist = create_checklist(project["id"])
    check_all_items(checklist)
    record = validate_success(
        api.create_alignment_record(
            create_alignment_record_payload(project_id=project["id"]), sup_headers
        ),
        201,
    )

    blocked = api.submit_commissioning_checklist(checklist["id"], pm_headers)
    validate_error(blocked, ApiErrorId.ERR_ALIGNMENT_OUTSTANDING)

    validate_success(
        api.review_alignment_record(record["id"], {"outcome": "ACCEPTED"}, pm_headers)
    )
    submitted = validate_success(api.submit_commissioning_checklist(checklist["id"], pm_headers))
    assert submitted["status"] == "SUBMITTED"


def test_checklist_not_signed_off_on_complete(api, pm_headers):
    """PRD section 3.7: "`SIGNED_OFF` is terminal and unlocks the last
    work-phase hop: advancing from `COMMISSIONING` to `COMPLETED` requires
    some checklist of the project to stand `SIGNED_OFF`, failing with
    `ERR_CHECKLIST_NOT_SIGNED_OFF` otherwise."

    Design: Corner/validations/checklist_not_signed_off_on_complete
    """
    ctx = setup_project_commissioning(name="Signoff Gate Job", site_address="54 Plant Rd")
    project = ctx["project"]
    checklist_ctx = setup_submitted_checklist(project["id"])
    assert checklist_ctx["checklist"]["status"] == "SUBMITTED"

    resp = api.advance_project(project["id"], pm_headers)
    validate_error(resp, ApiErrorId.ERR_CHECKLIST_NOT_SIGNED_OFF)
    assert get_project(project["id"])["work_status"] == "COMMISSIONING"


def test_project_manager_cannot_signoff_checklist(api, pm_headers):
    """PRD section 2.1: "When the role is recognized but not permitted to
    invoke the requested operation, the request is rejected with
    `ERR_FORBIDDEN`."
    PRD section 2.1: "The division of labor across roles follows a strict
    segregation-of-duties model: the `SiteSupervisor` records field data
    (surveys, rigging plans, lift bookings, alignment measurements, labor
    entries, checklist items), the `ProjectManager` owns the project
    lifecycle, reviews, invoicing, and the test clock, the `SafetyOfficer`
    alone manages the safety plan and lockout-tagout windows, the
    `PayrollClerk` approves or rejects submitted labor and is deliberately
    distinct from the submitting supervisor, and the `CustomerRep` holds sole
    authority for commissioning sign-off."

    Design: Corner/rbac/project_manager_cannot_signoff_checklist
    """
    ctx = setup_project_commissioning(name="RBAC5 Job", site_address="63 Plant Rd")
    checklist_ctx = setup_submitted_checklist(ctx["project"]["id"])
    checklist = checklist_ctx["checklist"]
    assert checklist["status"] == "SUBMITTED"

    resp = api.sign_off_checklist(checklist["id"], {}, pm_headers)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    checklists = api.list_commissioning_checklists(ctx["project"]["id"], pm_headers).json()[
        "data"
    ]
    assert checklists[0]["status"] == "SUBMITTED"
