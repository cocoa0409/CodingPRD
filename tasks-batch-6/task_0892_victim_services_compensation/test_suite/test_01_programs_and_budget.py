"""Program creation, RBAC, and the program-budget ledger (PRD §2.7, §2.8, §3.1, §3.6)."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, NON_EXISTENT_UUID, TEST_USERS,
    assert_program,
)
from test_helpers import fixtures as fx
from test_helpers import factories as fac

ADJ = TEST_USERS["adjudicator_headers"]
ADMIN = TEST_USERS["program_admin_headers"]
FINANCE = TEST_USERS["finance_officer_headers"]


# --------------------------------------------------------------------------
# Corner — program creation / read / RBAC
# --------------------------------------------------------------------------
def test_create_program_success(api):
    """PRD §3.1: "A newly created program begins in `status` `OPEN`, with its
    committed, disbursed, and recovered figures at zero and `budget_available_cents`
    equal to `total_budget_cents`."

    Design: Corner/entities/create_program_success_and_computed_budget_fields
    """
    resp = api.create_program(fac.create_program_payload(total_budget_cents=10000000), ADMIN)
    data = validate_success(resp, 201)
    prog = validate_success(api.get_program(data["id"], ADMIN))
    assert_program(prog)
    assert prog["status"] == "OPEN"
    assert prog["budget_available_cents"] == 10000000
    assert prog["budget_committed_cents"] == 0
    assert prog["budget_disbursed_cents"] == 0
    assert prog["budget_recovered_cents"] == 0
    assert prog["version"] == 1


def test_get_program_nonexistent_not_found(api):
    """PRD §2.9: "the existence of every resource named in the path is verified
    left-to-right ... an unresolved reference yields the resource-specific not-found
    error (for example `ERR_PROGRAM_NOT_FOUND` ... each HTTP 404)."

    Design: Corner/entities/get_program_nonexistent_returns_not_found
    """
    resp = api.get_program(NON_EXISTENT_UUID, ADMIN)
    validate_error(resp, ApiErrorId.ERR_PROGRAM_NOT_FOUND.value)


def test_finance_officer_cannot_create_program(api):
    """PRD §2.1: "When the headers are well-formed but the acting role is not
    permitted to perform the requested operation, the request is rejected with
    `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/finance_officer_cannot_create_program
    """
    resp = api.create_program(fac.create_program_payload(name="Rogue"), FINANCE)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


# --------------------------------------------------------------------------
# Difficulty — dual_variant_calc: committed vs disbursed on the Program domain
# --------------------------------------------------------------------------
def test_committed_reflects_calculated_award(api):
    """PRD §2.7: "The `budget_committed_cents` is the forward-looking exposure: the
    sum of `net_award_cents` across every `Award` belonging to the program's cases
    whose `approval_status` is `CALCULATED`, `APPROVED`, or `FINALIZED`."

    Design: Difficulty/dual_variant_calc/program_committed_vs_disbursed
    """
    program, case, claim, award, disb = fx.setup_finalized_award_with_disbursement(
        api, claimed_amount_cents=1000000, verified_amount_cents=1000000,
        disbursement_amount_cents=600000, payee_type="VICTIM",
    )
    fx.disbursement_transition(api, disb["id"], "PAID")
    prog = validate_success(api.get_program(program["id"], ADMIN))
    assert prog["budget_committed_cents"] == 1000000


def test_disbursed_reflects_paid_disbursements(api):
    """PRD §2.7: "The `budget_disbursed_cents` is the realized cash-out: the sum of
    `amount_cents` over every `Disbursement` in status `PAID`."

    Design: Difficulty/dual_variant_calc/program_committed_vs_disbursed
    """
    program, case, claim, award, disb = fx.setup_finalized_award_with_disbursement(
        api, claimed_amount_cents=1000000, verified_amount_cents=1000000,
        disbursement_amount_cents=600000, payee_type="VICTIM",
    )
    fx.disbursement_transition(api, disb["id"], "PAID")
    prog = validate_success(api.get_program(program["id"], ADMIN))
    assert prog["budget_disbursed_cents"] == 600000


# --------------------------------------------------------------------------
# Difficulty — boundary_precision_check: budget exact-fill vs over-by-one
# --------------------------------------------------------------------------
def _budget_boundary_program_with_case_a(api):
    """Program total_budget=4,000,000 (caps also 4,000,000); caseA has one APPROVED
    MEDICAL claim net=4,000,000. Returns (program, case_a)."""
    program = fx.make_program(
        api,
        total_budget_cents=4000000, overall_case_cap_cents=4000000,
        medical_cap_cents=4000000,
    )
    _, case_a = fx.make_eligible_case(api, program=program, victim_name="Case A")
    fx.make_approved_claim(api, case_a["id"], "MEDICAL",
                           claimed_amount_cents=4000000, verified_amount_cents=4000000)
    return program, case_a


def test_budget_exact_fill_allowed(api):
    """PRD §3.6: "The award's `net_award_cents` added to the program's current
    `budget_committed_cents` may not exceed the program's `total_budget_cents`; the
    boundary is allowed (a sum exactly equal to the total budget is fine) and only a
    strict excess is rejected, with `ERR_BUDGET_EXCEEDED` (HTTP 422)."

    Design: Difficulty/boundary_precision_check/budget_exact_fill_allowed_over_by_one_rejected
    """
    program, case_a = _budget_boundary_program_with_case_a(api)
    version = fx.program_version(api, program["id"])
    resp = api.create_award(fac.create_award_payload(case_a["id"], version), ADJ)
    award = validate_success(resp, 201)
    assert award["net_award_cents"] == 4000000
    prog = validate_success(api.get_program(program["id"], ADMIN))
    assert prog["budget_committed_cents"] == 4000000


def test_budget_over_by_one_rejected(api):
    """PRD §3.6: "The award's `net_award_cents` added to the program's current
    `budget_committed_cents` may not exceed the program's `total_budget_cents`; the
    boundary is allowed (a sum exactly equal to the total budget is fine) and only a
    strict excess is rejected, with `ERR_BUDGET_EXCEEDED` (HTTP 422)."

    Design: Difficulty/boundary_precision_check/budget_exact_fill_allowed_over_by_one_rejected
    """
    program, case_a = _budget_boundary_program_with_case_a(api)
    _, case_b = fx.make_eligible_case(api, program_id=program["id"], victim_name="Case B")
    fx.make_approved_claim(api, case_b["id"], "MEDICAL",
                           claimed_amount_cents=1, verified_amount_cents=1)
    # Fill the budget exactly with caseA's 4,000,000 award.
    v1 = fx.program_version(api, program["id"])
    fx.make_award(api, case_a["id"], v1)
    # A further award of net 1 makes 4,000,001 > 4,000,000.
    v2 = fx.program_version(api, program["id"])
    resp = api.create_award(fac.create_award_payload(case_b["id"], v2), ADJ)
    validate_error(resp, ApiErrorId.ERR_BUDGET_EXCEEDED.value)


# --------------------------------------------------------------------------
# Difficulty — priority_pair_validation_conflict: program-closed beats budget
# --------------------------------------------------------------------------
def test_program_closed_beats_budget_exceeded(api):
    """PRD §2.9: "After existence comes business-referential scoping
    (`ERR_REFERENCE_MISMATCH`, 409), then state-machine legality (`ERR_INVALID_STATE`,
    409), then cross-entity state preconditions, then segregation of duties, then
    program-closed checks, then the concurrency check, then temporal windows, then the
    remaining business constraints, and finally field-level shape validation
    (`ERR_VALIDATION`, 400)."
    PRD §3.1: "Once a program is `CLOSED`, any attempt to create a new case or a new
    award under it is rejected with `ERR_PROGRAM_CLOSED` (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/program_closed_beats_budget_exceeded_on_award_create
    """
    program = fx.make_program(api, name="Tiny Fund", total_budget_cents=500000)
    _, case = fx.make_eligible_case(api, program=program)
    fx.make_approved_claim(api, case["id"], "MEDICAL",
                           claimed_amount_cents=1000000, verified_amount_cents=1000000)
    version = fx.program_version(api, program["id"])
    validate_success(api.transition_program(program["id"], {"to_status": "CLOSED"}, ADMIN))
    resp = api.create_award(fac.create_award_payload(case["id"], version), ADJ)
    validate_error(resp, ApiErrorId.ERR_PROGRAM_CLOSED.value)


def test_award_create_on_closed_program_rejected(api):
    """PRD §3.1: "Once a program is `CLOSED`, any attempt to create a new case or a
    new award under it is rejected with `ERR_PROGRAM_CLOSED` (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/program_closed_beats_budget_exceeded_on_award_create
    """
    # Ample budget so ERR_BUDGET_EXCEEDED cannot fire — isolates the program-closed check.
    program = fx.make_program(api, total_budget_cents=10000000)
    _, case = fx.make_eligible_case(api, program=program)
    fx.make_approved_claim(api, case["id"], "MEDICAL",
                           claimed_amount_cents=1000000, verified_amount_cents=1000000)
    version = fx.program_version(api, program["id"])
    validate_success(api.transition_program(program["id"], {"to_status": "CLOSED"}, ADMIN))
    resp = api.create_award(fac.create_award_payload(case["id"], version), ADJ)
    validate_error(resp, ApiErrorId.ERR_PROGRAM_CLOSED.value)


# --------------------------------------------------------------------------
# Corner — optimistic concurrency on award create (§2.8)
# --------------------------------------------------------------------------
def test_occ_stale_program_version_rejected(api):
    """PRD §2.8: "If another award — for any case under the same program — has
    committed budget and advanced the program's `version` since the client last read
    it, then `expected_program_version` will be behind the program's current
    `version`, and the create is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_program_version_on_award_create
    """
    program = fx.make_program(api)
    stale_version = fx.program_version(api, program["id"])  # v1
    _, case_a = fx.make_eligible_case(api, program_id=program["id"], victim_name="Case A")
    fx.make_approved_claim(api, case_a["id"], "MEDICAL",
                           claimed_amount_cents=500000, verified_amount_cents=500000)
    _, case_b = fx.make_eligible_case(api, program_id=program["id"], victim_name="Case B")
    fx.make_approved_claim(api, case_b["id"], "MEDICAL",
                           claimed_amount_cents=500000, verified_amount_cents=500000)
    # First award with v1 succeeds and advances the program version to 2.
    validate_success(api.create_award(fac.create_award_payload(case_a["id"], stale_version), ADJ), 201)
    # Second award still carrying v1 is stale.
    resp = api.create_award(fac.create_award_payload(case_b["id"], stale_version), ADJ)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)
