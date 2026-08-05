"""Manual incentive awards: validation precedence, OCC on program version, budget."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId, TEST_USERS,
    setup_active_enrollment, read_program, read_program_version, read_enrollment,
)
from test_helpers import factories as F

PA = TEST_USERS["program_admin_headers"]
CM = TEST_USERS["case_manager_headers"]


def _award(api, enrollment_id, amount, expected_version, milestone="DISCRETIONARY"):
    return api.create_incentive_award(
        enrollment_id,
        F.create_incentive_award_payload(
            milestone_type=milestone, amount_cents=amount,
            expected_employer_program_version=expected_version,
        ),
        CM,
    )


def test_state_check_beats_fiscal_on_disenrolled_enrollment(api):
    """PRD §2.5: "4. **State admissibility** — the target resource is in a state that
    admits the requested transition, and enrollment-scoped operations require the
    enrollment to be `ACTIVE`, else `ERR_INVALID_STATE` or `ERR_ENROLLMENT_NOT_ACTIVE`
    (409)."
    PRD §2.5: "9. **Fiscal sufficiency** — the sponsor budget must cover an award
    amount, else `ERR_PROGRAM_BUDGET_EXCEEDED` (402)."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_manual_award
    """
    ctx = setup_active_enrollment(api, cpd=10, sponsored=True, budget=100000,
                                  clock="2026-06-01T00:00:00Z")
    validate_success(api.disenroll_enrollment(ctx["enrollment_id"], CM))
    version = read_program_version(api, ctx["program_id"])
    # Amount also exceeds the budget, but the state gate (p4) pre-empts fiscal (p9).
    resp = _award(api, ctx["enrollment_id"], 999999999, version)
    validate_error(resp, ApiErrorId.ERR_ENROLLMENT_NOT_ACTIVE.value)


def test_state_check_fires_on_disenrolled_even_within_budget(api):
    """PRD §2.5: "4. **State admissibility** — the target resource is in a state that
    admits the requested transition, and enrollment-scoped operations require the
    enrollment to be `ACTIVE`, else `ERR_INVALID_STATE` or `ERR_ENROLLMENT_NOT_ACTIVE`
    (409)."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_manual_award
    """
    ctx = setup_active_enrollment(api, cpd=10, sponsored=True, budget=100000,
                                  clock="2026-06-01T00:00:00Z")
    validate_success(api.disenroll_enrollment(ctx["enrollment_id"], CM))
    version = read_program_version(api, ctx["program_id"])
    # A small, budget-affordable award is still rejected: the enrollment is not ACTIVE.
    resp = _award(api, ctx["enrollment_id"], 500, version)
    validate_error(resp, ApiErrorId.ERR_ENROLLMENT_NOT_ACTIVE.value)


def test_manual_award_stale_program_version_rejected(api):
    """PRD §2.8: "The create request must carry `expected_employer_program_version`
    equal to the sponsor program's current `version`. If another writer — a system
    milestone award or an earlier manual award — has advanced the program's `version`
    since the client last read it, the create is rejected with `ERR_STALE_VERSION`
    (HTTP 412)".

    Design: Corner/cross_cutting_complexity_layers/occ_stale_program_version_on_manual_award
    """
    ctx = setup_active_enrollment(api, cpd=10, sponsored=True, budget=100000,
                                  clock="2026-06-01T00:00:00Z")
    stale_version = ctx["program"]["version"]  # captured at creation (v1)
    # Activation's ENROLLMENT award has since bumped the program to v2.
    resp = _award(api, ctx["enrollment_id"], 500, stale_version)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)


def test_manual_award_correct_version_succeeds_and_debits_budget(api):
    """PRD §3.8: "The award is created with `status` `EARNED` and `source` `MANUAL`,
    debits the sponsor's `budget_remaining_cents` by `amount_cents`, and increments
    the program's `version`."

    Design: Corner/cross_cutting_complexity_layers/occ_correct_program_version_on_manual_award_succeeds
    """
    ctx = setup_active_enrollment(api, cpd=10, sponsored=True, budget=100000,
                                  clock="2026-06-01T00:00:00Z")
    version = read_program_version(api, ctx["program_id"])  # fresh v2
    award = validate_success(_award(api, ctx["enrollment_id"], 500, version), 201)
    assert award["status"] == "EARNED"
    assert award["source"] == "MANUAL"
    program = read_program(api, ctx["program_id"])
    # 100000 - 1000 (ENROLLMENT) - 500 (manual) == 98500
    assert program["budget_remaining_cents"] == 98500


def test_manual_award_exceeds_budget_returns_fiscal_error(api):
    """PRD §2.9: "Before any award is created, the sponsor's `budget_remaining_cents`
    must be able to cover the award's `amount_cents`; a shortfall is rejected with
    `ERR_PROGRAM_BUDGET_EXCEEDED`."

    Design: Corner/validations/manual_award_exceeds_budget_returns_fiscal_error
    """
    ctx = setup_active_enrollment(api, cpd=10, sponsored=True, budget=2000,
                                  clock="2026-06-01T00:00:00Z")
    # ENROLLMENT award debited 1000, leaving budget_remaining 1000.
    version = read_program_version(api, ctx["program_id"])
    resp = _award(api, ctx["enrollment_id"], 999999, version)
    validate_error(resp, ApiErrorId.ERR_PROGRAM_BUDGET_EXCEEDED.value)


def test_manual_award_on_closed_program_rejected(api):
    """PRD §3.1: "Once a program is `CLOSED`, any subsequent manual incentive award
    recorded against one of its participants is rejected with `ERR_PROGRAM_CLOSED`."

    Design: Corner/validations/manual_award_on_closed_program_rejected
    """
    ctx = setup_active_enrollment(api, cpd=10, sponsored=True, budget=100000,
                                  clock="2026-06-01T00:00:00Z")
    version = read_program_version(api, ctx["program_id"])
    closed = validate_success(
        api.close_employer_program(
            ctx["program_id"], {"expected_employer_program_version": version}, PA
        )
    )
    resp = _award(api, ctx["enrollment_id"], 500, closed["version"])
    validate_error(resp, ApiErrorId.ERR_PROGRAM_CLOSED.value)


def test_manual_award_on_self_pay_returns_program_not_found(api):
    """PRD §2.9: "Self-pay participants — those with no sponsor — accrue no awards
    against any budget; a manual award naming a self-pay participant's enrollment
    resolves to `ERR_EMPLOYER_PROGRAM_NOT_FOUND`."

    Design: Corner/endpoints/manual_award_on_self_pay_returns_program_not_found
    """
    ctx = setup_active_enrollment(api, cpd=10, sponsored=False)
    enr = read_enrollment(api, ctx["enrollment_id"])
    resp = _award(api, ctx["enrollment_id"], 500, enr["version"])
    validate_error(resp, ApiErrorId.ERR_EMPLOYER_PROGRAM_NOT_FOUND.value)
