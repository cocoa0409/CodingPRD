"""Due-date extensions: grant/revoke arithmetic, bounds, OCC, single-active limit."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_due_at_invariant,
    assert_instant_equal,
    get_assignment,
    make_manager_headers,
    setup_managed_employee_with_assignment,
    submit_completion,
    validate_error,
    validate_success,
)
from test_helpers import factories

ADMIN = TEST_USERS["compliance_admin_headers"]


class TestGrantRevokeConservation:
    def _setup(self):
        return setup_managed_employee_with_assignment(
            "X9A", reminder_days_before_due=3, due_in_days=5,
        )

    def test_grant_pushes_due_at_by_extension_days(self, api):
        """PRD §3.5: "The effective `due_at` always equals `base_due_at` plus
        `active_extension_days` days — an invariant that holds at all times,
        with `active_extension_days` at zero whenever no extension is active."
        PRD §3.5: "A grant sets `active_extension_days` to the granted number of
        days, pushes `due_at` out by the same amount, records the manager's
        `reason`, increments the assignment's `version`, and recomputes
        `deadline_status` against the new due date (pinned `FROZEN` if the
        employee is on leave) — creating no notices."

        Design: Difficulty/compensating_invariant/extension_grant_revoke_conserves_due_at
        """
        ctx = self._setup()
        asg, mgr = ctx["assignment"], ctx["manager"]
        assert_instant_equal(asg["base_due_at"], "2026-08-08T09:00:00Z", "base_due_at")

        resp = api.grant_extension(
            asg["id"],
            factories.grant_extension_payload(
                asg["version"], extend_by_days=7, reason="Business travel",
            ),
            make_manager_headers(mgr["id"]),
        )
        granted = validate_success(resp, 200)
        assert_instant_equal(granted["due_at"], "2026-08-15T09:00:00Z", "due_at after grant")
        assert granted["active_extension_days"] == 7
        assert_instant_equal(granted["base_due_at"], "2026-08-08T09:00:00Z", "base unchanged")
        assert granted["version"] == asg["version"] + 1, "grant increments the version by 1"
        assert_due_at_invariant(granted)

    def test_revoke_restores_base_due_at_exactly(self, api):
        """PRD §3.5: "A valid revocation subtracts the active extension from
        `due_at` — restoring `base_due_at` exactly — zeroes
        `active_extension_days`, increments the version, and recomputes the
        deadline status and block posture exactly as a grant does, again
        creating no notices, and again guarded by `expected_assignment_version`
        against stale reads."
        PRD §3.5: "The effective `due_at` always equals `base_due_at` plus
        `active_extension_days` days — an invariant that holds at all times,
        with `active_extension_days` at zero whenever no extension is active."

        Design: Difficulty/compensating_invariant/extension_grant_revoke_conserves_due_at
        """
        ctx = self._setup()
        asg, mgr = ctx["assignment"], ctx["manager"]
        granted = validate_success(
            api.grant_extension(
                asg["id"],
                factories.grant_extension_payload(asg["version"], extend_by_days=7),
                make_manager_headers(mgr["id"]),
            ),
            200,
        )
        revoked = validate_success(
            api.revoke_extension(
                asg["id"],
                {"expected_assignment_version": granted["version"]},
                make_manager_headers(mgr["id"]),
            ),
            200,
        )
        assert_instant_equal(revoked["due_at"], "2026-08-08T09:00:00Z", "due_at restored")
        assert revoked["active_extension_days"] == 0
        assert_instant_equal(revoked["base_due_at"], "2026-08-08T09:00:00Z", "base_due_at")
        assert_due_at_invariant(revoked)


def test_extension_beyond_thirty_days_rejected(api):
    """PRD §3.5: "the requested `extend_by_days` must be between 1 and 30
    inclusive (`ERR_EXTENSION_DAYS_INVALID`)"

    Design: Corner/validations/extension_beyond_thirty_days_rejected
    """
    ctx = setup_managed_employee_with_assignment("XD")
    asg, mgr = ctx["assignment"], ctx["manager"]
    resp = api.grant_extension(
        asg["id"],
        factories.grant_extension_payload(
            asg["version"], extend_by_days=31, reason="too long",
        ),
        make_manager_headers(mgr["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_EXTENSION_DAYS_INVALID.value)


def test_revoke_without_active_extension_rejected(api):
    """PRD §3.5: "Revocation is the mirror action, available only while an
    extension is active: with `active_extension_days` at zero, revocation fails
    with `ERR_NO_ACTIVE_EXTENSION`."

    Design: Corner/validations/revoke_without_active_extension_returns_409
    """
    ctx = setup_managed_employee_with_assignment("RV0")
    asg, mgr = ctx["assignment"], ctx["manager"]
    assert asg["active_extension_days"] == 0
    resp = api.revoke_extension(
        asg["id"],
        {"expected_assignment_version": asg["version"]},
        make_manager_headers(mgr["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_NO_ACTIVE_EXTENSION.value)


def test_extension_on_submitted_assignment_rejected(api):
    """PRD §3.5: "the assignment's progress must be `ASSIGNED` or `IN_PROGRESS`
    (`ERR_ASSIGNMENT_NOT_EXTENDABLE`)"

    Design: Corner/validations/extension_on_submitted_assignment_rejected
    """
    ctx = setup_managed_employee_with_assignment("XS")
    asg, mgr, emp = ctx["assignment"], ctx["manager"], ctx["employee"]
    submit_completion(asg["id"], emp["id"], score_pct=90)

    current = get_assignment(asg["id"])
    assert current["progress_status"] == "SUBMITTED"
    resp = api.grant_extension(
        asg["id"],
        factories.grant_extension_payload(
            current["version"], extend_by_days=5, reason="late review",
        ),
        make_manager_headers(mgr["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_ASSIGNMENT_NOT_EXTENDABLE.value)


def test_second_extension_grant_while_active_rejected(api):
    """PRD §3.5: "no extension may already be active (`ERR_EXTENSION_LIMIT_ACTIVE`
    — the system allows a single active extension at a time)"

    Design: Corner/complexity_layers/extension_limit_after_successful_grant_returns_409
    """
    ctx = setup_managed_employee_with_assignment("XL")
    asg, mgr = ctx["assignment"], ctx["manager"]
    validate_success(
        api.grant_extension(
            asg["id"],
            factories.grant_extension_payload(asg["version"], extend_by_days=5, reason="first"),
            make_manager_headers(mgr["id"]),
        ),
        200,
    )
    current = get_assignment(asg["id"])
    assert current["active_extension_days"] == 5

    resp = api.grant_extension(
        asg["id"],
        factories.grant_extension_payload(
            current["version"], extend_by_days=4, reason="second",
        ),
        make_manager_headers(mgr["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_EXTENSION_LIMIT_ACTIVE.value)
