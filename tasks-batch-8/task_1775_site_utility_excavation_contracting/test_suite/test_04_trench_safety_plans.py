"""Trench safety plans: slope/depth compliance, review exclusivity, SoD,
the revision loop, and the groundwater readiness recompute."""

from test_helpers import (
    FOREMAN,
    FOREMAN_USER,
    PM_USER,
    PROJECT_MANAGER,
    SAFETY_USER,
    ApiErrorId,
    create_approved_plan,
    create_segment,
    create_unforeseen_condition,
    get_plan,
    get_project,
    get_segment,
    make_foreman_headers,
    make_project_manager_headers,
    make_safety_officer_headers,
    setup_project_with_active_ticket,
    setup_ready_segment,
    trench_plan_payload,
    validate_error,
    validate_success,
)


def test_slope_below_soil_class_minimum_rejected(api):
    """PRD §3.3: "For `SLOPING` or `BENCHING`, the `slope_ratio` must be
    present and must be at least the required ratio for the plan's soil class
    — 0.75 for `SOIL_A`, 1.0 for `SOIL_B`, and 1.5 for `SOIL_C` — with the
    boundary inclusive, so a ratio of exactly 1.5 on `SOIL_C` passes;
    shortfalls are rejected with `ERR_SLOPE_NONCOMPLIANT`."

    Design: Corner/validations/slope_below_soil_c_minimum_rejected
    """
    ctx = setup_project_with_active_ticket()
    segment = create_segment(ctx["project"], ctx["owner"], segment_label="WL-V-01")

    plan_bad = validate_success(
        api.create_trench_safety_plan(
            trench_plan_payload(
                ctx["project"]["id"], segment["id"], slope_ratio=1.4
            ),
            make_foreman_headers(),
        ),
        201,
    )
    plan_ok = validate_success(
        api.create_trench_safety_plan(
            trench_plan_payload(
                ctx["project"]["id"], segment["id"], slope_ratio=1.5
            ),
            make_foreman_headers(),
        ),
        201,
    )

    response = api.submit_trench_safety_plan(plan_bad["id"], make_foreman_headers())
    validate_error(response, ApiErrorId.ERR_SLOPE_NONCOMPLIANT, 422)
    assert get_plan(plan_bad["id"])["status"] == "DRAFT"

    submitted = validate_success(
        api.submit_trench_safety_plan(plan_ok["id"], make_foreman_headers())
    )
    assert submitted["status"] == "SUBMITTED"


def test_deep_trench_requires_engineered_system(api):
    """PRD §3.3: "Independently, any plan covering a `max_depth_ft` of 20 feet
    or more must specify `SHORING` or `TRENCH_BOX` and carry
    `engineered_certification` set to true; otherwise submission fails with
    `ERR_ENGINEERED_DESIGN_REQUIRED`."

    Design: Corner/validations/deep_trench_requires_engineered_system
    """
    ctx = setup_project_with_active_ticket()
    segment = create_segment(
        ctx["project"], ctx["owner"], segment_label="WL-V-02",
        pipe_material="RCP", diameter_in=36, length_ft=300.0,
        design_invert_depth_ft=24.0, design_slope_pct=0.3,
    )

    # SLOPING with a soil-compliant ratio is still forbidden at 25 ft.
    plan_sloping = validate_success(
        api.create_trench_safety_plan(
            trench_plan_payload(
                ctx["project"]["id"], segment["id"], max_depth_ft=25.0,
                soil_class="SOIL_B", protective_system="SLOPING", slope_ratio=1.0,
            ),
            make_foreman_headers(),
        ),
        201,
    )
    response = api.submit_trench_safety_plan(
        plan_sloping["id"], make_foreman_headers()
    )
    validate_error(response, ApiErrorId.ERR_ENGINEERED_DESIGN_REQUIRED, 422)

    # TRENCH_BOX without the PE certification is likewise rejected.
    plan_uncertified = validate_success(
        api.create_trench_safety_plan(
            trench_plan_payload(
                ctx["project"]["id"], segment["id"], max_depth_ft=25.0,
                soil_class="SOIL_B", protective_system="TRENCH_BOX",
                engineered_certification=False,
            ),
            make_foreman_headers(),
        ),
        201,
    )
    response = api.submit_trench_safety_plan(
        plan_uncertified["id"], make_foreman_headers()
    )
    validate_error(response, ApiErrorId.ERR_ENGINEERED_DESIGN_REQUIRED, 422)

    # Certified TRENCH_BOX passes.
    plan_certified = validate_success(
        api.create_trench_safety_plan(
            trench_plan_payload(
                ctx["project"]["id"], segment["id"], max_depth_ft=25.0,
                soil_class="SOIL_B", protective_system="TRENCH_BOX",
                engineered_certification=True,
            ),
            make_foreman_headers(),
        ),
        201,
    )
    submitted = validate_success(
        api.submit_trench_safety_plan(plan_certified["id"], make_foreman_headers())
    )
    assert submitted["status"] == "SUBMITTED"


def test_plan_review_exclusive_to_safety_officer(api):
    """PRD §3.3: "Review belongs to the `SafetyOfficer`, the competent person
    for excavation safety, who passes a `decision` of `APPROVE` or `REJECT`."
    PRD §2.1: "A request whose role is not permitted to perform the attempted
    operation is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."

    Design: Corner/rbac/plan_review_exclusive_to_safety_officer
    """
    ctx = setup_project_with_active_ticket()
    segment = create_segment(ctx["project"], ctx["owner"], segment_label="WL-R-20")
    plan = validate_success(
        api.create_trench_safety_plan(
            trench_plan_payload(ctx["project"]["id"], segment["id"]),
            make_foreman_headers(FOREMAN_USER),
        ),
        201,
    )
    validate_success(
        api.submit_trench_safety_plan(plan["id"], make_foreman_headers(FOREMAN_USER))
    )

    response = api.review_trench_safety_plan(
        plan["id"], "APPROVE", make_project_manager_headers(PM_USER)
    )
    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED_ROLE, 403)
    assert get_plan(plan["id"])["status"] == "SUBMITTED"

    reviewed = validate_success(
        api.review_trench_safety_plan(
            plan["id"], "APPROVE", make_safety_officer_headers(SAFETY_USER)
        )
    )
    assert reviewed["status"] == "APPROVED"


def test_same_user_review_violates_segregation_of_duties(api):
    """PRD §3.3: "Segregation of duties applies: the reviewer's `X-User-ID`
    must differ from `submitted_by_user_id`, else `ERR_SOD_VIOLATION`."
    PRD §2.1: "the reviewer's `X-User-ID` must differ from the identifier
    captured at submission or recording time, and a violation is rejected with
    `ERR_SOD_VIOLATION` (HTTP 403)."

    Design: Corner/rbac/sod_same_user_review_rejected
    """
    ctx = setup_project_with_active_ticket()
    segment = create_segment(ctx["project"], ctx["owner"], segment_label="WL-R-21")
    plan = validate_success(
        api.create_trench_safety_plan(
            trench_plan_payload(ctx["project"]["id"], segment["id"]),
            make_foreman_headers(FOREMAN_USER),
        ),
        201,
    )
    submitted = validate_success(
        api.submit_trench_safety_plan(plan["id"], make_foreman_headers(FOREMAN_USER))
    )
    assert submitted["submitted_by_user_id"] == FOREMAN_USER

    # A SafetyOfficer acting under the submitter's own user id is refused.
    response = api.review_trench_safety_plan(
        plan["id"], "APPROVE", make_safety_officer_headers(FOREMAN_USER)
    )
    validate_error(response, ApiErrorId.ERR_SOD_VIOLATION, 403)
    assert get_plan(plan["id"])["status"] == "SUBMITTED"


def test_trench_plan_revision_cycle(api):
    """PRD §3.3: "The reviewer is captured in `reviewed_by_user_id`, and the
    plan moves from `SUBMITTED` to `APPROVED` or `REJECTED` according to the
    decision. A `REJECTED` plan is not dead — the `Foreman` may revise it back
    to `DRAFT`, which increments `revision` by one and optionally applies new
    values for `max_depth_ft`, `soil_class`, `protective_system`,
    `slope_ratio`, or `engineered_certification` before the next submission."

    Design: Difficulty/non_linear_state_machine/trench_plan_revision_cycle
    """
    ctx = setup_project_with_active_ticket()
    segment = create_segment(ctx["project"], ctx["owner"], segment_label="WL-C-01")
    plan = validate_success(
        api.create_trench_safety_plan(
            trench_plan_payload(ctx["project"]["id"], segment["id"]),
            make_foreman_headers(FOREMAN_USER),
        ),
        201,
    )
    assert plan["revision"] == 1

    validate_success(
        api.submit_trench_safety_plan(plan["id"], make_foreman_headers(FOREMAN_USER))
    )
    rejected = validate_success(
        api.review_trench_safety_plan(
            plan["id"], "REJECT", make_safety_officer_headers(SAFETY_USER)
        )
    )
    assert rejected["status"] == "REJECTED"

    revised = validate_success(
        api.revise_trench_safety_plan(plan["id"], {}, make_foreman_headers())
    )
    assert revised["status"] == "DRAFT"
    assert revised["revision"] == 2

    validate_success(
        api.submit_trench_safety_plan(plan["id"], make_foreman_headers(FOREMAN_USER))
    )
    approved = validate_success(
        api.review_trench_safety_plan(
            plan["id"], "APPROVE", make_safety_officer_headers(SAFETY_USER)
        )
    )
    assert approved["status"] == "APPROVED"
    assert approved["submitted_by_user_id"] == FOREMAN_USER
    assert approved["reviewed_by_user_id"] == SAFETY_USER


def test_trench_plan_revise_applies_new_values(api):
    """PRD §3.3: "A `REJECTED` plan is not dead — the `Foreman` may revise it
    back to `DRAFT`, which increments `revision` by one and optionally applies
    new values for `max_depth_ft`, `soil_class`, `protective_system`,
    `slope_ratio`, or `engineered_certification` before the next submission."

    Design: Difficulty/non_linear_state_machine/trench_plan_revision_cycle
    """
    ctx = setup_project_with_active_ticket()
    segment = create_segment(ctx["project"], ctx["owner"], segment_label="WL-C-02")
    plan = validate_success(
        api.create_trench_safety_plan(
            trench_plan_payload(ctx["project"]["id"], segment["id"]),
            make_foreman_headers(FOREMAN_USER),
        ),
        201,
    )
    validate_success(
        api.submit_trench_safety_plan(plan["id"], make_foreman_headers(FOREMAN_USER))
    )
    validate_success(
        api.review_trench_safety_plan(
            plan["id"], "REJECT", make_safety_officer_headers(SAFETY_USER)
        )
    )

    revised = validate_success(
        api.revise_trench_safety_plan(
            plan["id"], {"slope_ratio": 2.0, "max_depth_ft": 10.0},
            make_foreman_headers(FOREMAN_USER),
        )
    )
    assert revised["status"] == "DRAFT"
    assert revised["revision"] == 2
    assert revised["slope_ratio"] == 2.0
    assert revised["max_depth_ft"] == 10.0

    resubmitted = validate_success(
        api.submit_trench_safety_plan(plan["id"], make_foreman_headers(FOREMAN_USER))
    )
    assert resubmitted["status"] == "SUBMITTED"


def test_groundwater_voids_only_sloped_plans(api):
    """PRD §3.3: "When an unforeseen condition of type `GROUNDWATER` is
    reported on the project (§3.7), the readiness recompute fires in a pinned
    order: first the project's open groundwater conditions are collected; then
    every `APPROVED` plan of the project built on `SLOPING` or `BENCHING`
    moves to `VOIDED`, since standing-water excavation cannot rely on sloped
    or benched walls; then every segment in `READY` whose plan was just voided
    reverts to `PLANNED`. Plans using `SHORING` or `TRENCH_BOX` ride the event
    out untouched."

    Design: Corner/state_machines/groundwater_voids_sloped_plans
    """
    ctx = setup_project_with_active_ticket()
    project, owner = ctx["project"], ctx["owner"]

    s1 = create_segment(project, owner, segment_label="WL-G-01")
    sp1 = create_approved_plan(project, s1)  # SLOPING, SOIL_C, ratio 1.5
    s1 = validate_success(api.mark_segment_ready(s1["id"], FOREMAN))

    s2 = create_segment(project, owner, segment_label="WL-G-02")
    sp2 = create_approved_plan(project, s2, protective_system="TRENCH_BOX",
                               slope_ratio=None)
    s2 = validate_success(api.mark_segment_ready(s2["id"], FOREMAN))
    assert s1["status"] == "READY" and s2["status"] == "READY"

    condition = create_unforeseen_condition(
        project, condition_type="GROUNDWATER", stop_work_required=False,
        description="groundwater at 6 ft",
    )
    assert condition["status"] == "OPEN"

    assert get_plan(sp1["id"])["status"] == "VOIDED"
    assert get_plan(sp2["id"])["status"] == "APPROVED"
    assert get_segment(s1["id"])["status"] == "PLANNED"
    assert get_segment(s2["id"])["status"] == "READY"
    assert get_project(project["id"])["work_posture"] == "CLEAR"
