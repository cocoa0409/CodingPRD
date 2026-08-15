"""RBAC denial, entity-backed ownership, segregation of duties, and OCC."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    TEST_USERS,
    create_campaign,
    create_curriculum,
    create_employee,
    create_regulator,
    find_assignment,
    get_assignment,
    get_success_data,
    list_completions,
    make_employee_headers,
    make_manager_headers,
    set_clock,
    setup_curriculum_stack,
    setup_employee_with_assignment,
    setup_managed_employee_with_assignment,
    submit_completion,
    validate_error,
    validate_success,
)
from test_helpers import factories

ADMIN = TEST_USERS["compliance_admin_headers"]
HR = TEST_USERS["hr_admin_headers"]
AUDITOR = TEST_USERS["auditor_headers"]
ANON = TEST_USERS["anonymous_headers"]


def test_anonymous_role_forbidden_on_admin_endpoint(api):
    """PRD §2.1: "A request whose role is not permitted for the target endpoint
    is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403); an `Anonymous` caller — an
    unauthenticated or unrecognized role used to verify denial — holds no
    permissions at all."

    Design: Corner/rbac/anonymous_role_forbidden_on_admin_endpoint
    """
    resp = api.create_regulator(
        factories.create_regulator_payload(
            code="REG-ANO", name="Anon Regulator", recordkeeping_years=5,
        ),
        ANON,
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


def test_auditor_cannot_create_regulator(api):
    """PRD §2.1: "An `Auditor` is the independent audit function, segregated
    from administration and review: auditors finalize closed campaigns and
    generate audit reports."
    PRD §2.1: "A request whose role is not permitted for the target endpoint is
    rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)"

    Design: Corner/rbac/auditor_cannot_create_regulator
    """
    resp = api.create_regulator(
        factories.create_regulator_payload(
            code="REG-AUD", name="Aud Regulator", recordkeeping_years=5,
        ),
        AUDITOR,
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


def test_hradmin_cannot_review_completion(api):
    """PRD §2.1: "A `ComplianceAdmin` is the corporate compliance training
    office administrator: this role owns regulator, role, and curriculum
    configuration, reviews completion submissions, runs attestation campaigns,
    decides exception requests, and operates the logical clock and the sweep."
    PRD §2.1: "A request whose role is not permitted for the target endpoint is
    rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)"

    Design: Corner/rbac/hradmin_cannot_review_completion
    """
    ctx = setup_employee_with_assignment("RB2")
    asg, emp = ctx["assignment"], ctx["employee"]
    c1 = submit_completion(asg["id"], emp["id"], score_pct=90)

    resp = api.accept_completion(c1["id"], {}, HR)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)

    records, _ = list_completions(asg["id"])
    assert records[0]["review_status"] == "PENDING_REVIEW", "unchanged"


def test_employee_cannot_open_campaign(api):
    """PRD §2.1: "A request whose role is not permitted for the target endpoint
    is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)"
    PRD §2.9: "1. **Authentication context first** — the presence and
    non-emptiness of `X-User-ID` and `X-User-Role`
    (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`). 2. **Role authorization** —
    whether the caller's role is permitted for the endpoint at all
    (`ERR_FORBIDDEN_ROLE`)."

    Design: Corner/rbac/employee_cannot_open_campaign
    """
    set_clock("2026-08-03T09:00:00Z")
    reg = create_regulator(code="REG-RB4", name="RB4 Regulator")
    camp = create_campaign(reg["id"], statement_version="STMT-RB4")

    resp = api.open_campaign(camp["id"], make_employee_headers(NON_EXISTENT_UUID))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)

    current = get_success_data(api.get_campaign(camp["id"], ADMIN), 200)
    assert current["status"] == "DRAFT", "unchanged"


def test_employee_cannot_start_other_employees_assignment(api):
    """PRD §2.1: "An `Employee` caller therefore acts only on their own
    assignments and attestations, and a `Manager` caller only on assignments and
    attestations belonging to their direct reports; a mismatch is rejected with
    `ERR_OWNERSHIP_MISMATCH` (HTTP 403)."
    PRD §3.4: "the caller must be the assignment's own employee
    (`ERR_OWNERSHIP_MISMATCH`)"

    Design: Corner/validations/employee_cannot_start_other_employees_assignment
    """
    ctx = setup_employee_with_assignment("OWN")
    role = ctx["role"]
    e1 = ctx["employee"]
    e2 = create_employee("E-O2", role["id"], full_name="Own Two")
    a2 = find_assignment(e2["id"], curriculum_id=ctx["curriculum"]["id"])

    resp = api.start_assignment(a2["id"], make_employee_headers(e1["id"]))
    validate_error(resp, ApiErrorId.ERR_OWNERSHIP_MISMATCH.value)
    assert get_assignment(a2["id"])["progress_status"] == "ASSIGNED", "unchanged"


def test_manager_cannot_grant_extension_on_own_assignment(api):
    """PRD §2.1: "managers grant and revoke due-date extensions and request
    attestation exceptions, but only for their direct reports, and a manager may
    never act on their own assignment or attestation — such self-service
    attempts are rejected with `ERR_SELF_ACTION_FORBIDDEN` (HTTP 403)."
    PRD §3.5: "Granting an extension requires the caller to be the direct
    manager of the assignment's employee (`ERR_OWNERSHIP_MISMATCH`) and not the
    employee themselves (`ERR_SELF_ACTION_FORBIDDEN`)"

    Design: Corner/validations/manager_cannot_grant_extension_on_own_assignment
    """
    set_clock("2026-08-03T09:00:00Z")
    stack = setup_curriculum_stack("SOD")
    mgr = create_employee("M-SOD-1", stack["role"]["id"], full_name="Sod Mgr")
    asg = find_assignment(mgr["id"], curriculum_id=stack["curriculum"]["id"])

    resp = api.grant_extension(
        asg["id"],
        factories.grant_extension_payload(
            asg["version"], extend_by_days=5, reason="self grant",
        ),
        make_manager_headers(mgr["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_SELF_ACTION_FORBIDDEN.value)


def test_occ_stale_curriculum_patch_returns_412(api):
    """PRD §2.7: "Updating a Curriculum requires `expected_curriculum_version`,
    the caller's last-observed `version` of that Curriculum."
    PRD §2.7: "In each case, if the supplied value does not match the parent
    entity's current `version` — meaning another writer has advanced the entity
    since the caller last read it — the request is rejected with
    `ERR_STALE_VERSION` (HTTP 412), and the caller must re-read and re-apply."
    PRD §3.1: "The override is optional at creation and is one of the fields a
    `ComplianceAdmin` may change through the OCC-guarded curriculum update
    (which also covers `validity_months`, `max_attempts`, and `status`, and
    increments the curriculum's `version` by 1 on any change)."

    Design: Corner/complexity_layers/occ_stale_curriculum_patch_returns_412
    """
    reg = create_regulator(code="REG-OCC1", name="OCC1 Regulator")
    cur = create_curriculum(reg["id"], code="CUR-OCC1", title="OCC1 Course")
    observed_version = cur["version"]

    first = api.update_curriculum(
        cur["id"],
        {"validity_months": 6, "expected_curriculum_version": observed_version},
        ADMIN,
    )
    patched = validate_success(first, 200)
    assert patched["version"] == observed_version + 1, "first patch applied"

    replay = api.update_curriculum(
        cur["id"],
        {"validity_months": 9, "expected_curriculum_version": observed_version},
        ADMIN,
    )
    validate_error(replay, ApiErrorId.ERR_STALE_VERSION.value)

    current = get_success_data(api.get_curriculum(cur["id"], ADMIN), 200)
    assert current["validity_months"] == 6, "losing patch left no trace"
    assert current["version"] == observed_version + 1


def test_occ_stale_extension_grant_returns_412(api):
    """PRD §2.7: "Granting an extension on a TrainingAssignment requires
    `expected_assignment_version`, the caller's last-observed `version` of that
    assignment."
    PRD §2.7: "In each case, if the supplied value does not match the parent
    entity's current `version` — meaning another writer has advanced the entity
    since the caller last read it — the request is rejected with
    `ERR_STALE_VERSION` (HTTP 412), and the caller must re-read and re-apply."
    PRD §2.9: "6. **Optimistic concurrency** — the `expected_*_version` match on
    the four guarded endpoints (`ERR_STALE_VERSION`)."

    Design: Corner/complexity_layers/occ_stale_extension_grant_returns_412
    """
    ctx = setup_managed_employee_with_assignment("OCC2")
    asg, mgr = ctx["assignment"], ctx["manager"]
    observed_version = asg["version"]

    first = api.grant_extension(
        asg["id"],
        factories.grant_extension_payload(observed_version, extend_by_days=3, reason="travel"),
        make_manager_headers(mgr["id"]),
    )
    granted = validate_success(first, 200)
    assert granted["version"] == observed_version + 1, "first grant bumped the version"

    replay = api.grant_extension(
        asg["id"],
        factories.grant_extension_payload(
            observed_version, extend_by_days=3, reason="travel again",
        ),
        make_manager_headers(mgr["id"]),
    )
    validate_error(replay, ApiErrorId.ERR_STALE_VERSION.value)
