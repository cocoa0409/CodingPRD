"""Formula lifecycle: initial state, invalid transitions, terminal lockdown,
withdraw cascade (PRD §2.10, §3.3)."""
from test_helpers import (
    ApiErrorId,
    add_ingredient_line,
    create_formula,
    create_ingredient,
    get_formula,
    get_registration,
    setup_draft_formula,
    setup_locked_formula,
    setup_nutrient_review_formula,
    setup_registration,
    validate_error,
    validate_success,
)


def test_formula_created_in_initial_state_draft(api, formulation_scientist_headers):
    """PRD §3.3: "A formula starts in `DRAFT` with `revision_number` 1,
    `substantiation_locked_version` null, `total_batch_count` zero, and
    `open_recall_flag` false."

    Design: Corner/state_machines/formula_created_in_initial_state_draft
    """
    brand_resp_ctx = setup_draft_formula()
    formula = get_formula(brand_resp_ctx["formula"]["id"])
    assert formula["status"] == "DRAFT"


def test_formula_lock_from_draft_fails_invalid_state(api, qa_approver_headers):
    """PRD §3.3: "Locking moves a `SUBSTANTIATED` formula to `LOCKED`, the only
    state from which production may be scheduled."
    PRD §2.10: "Fourth, transition validity: the requested action must correspond
    to a transition that exists from the resource's current state, else
    `ERR_INVALID_STATE` (HTTP 409)"

    Design: Corner/state_machines/formula_lock_from_draft_fails_invalid_state
    """
    ctx = setup_draft_formula()
    resp = api.lock_formula(ctx["formula"]["id"], qa_approver_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    assert get_formula(ctx["formula"]["id"])["status"] == "DRAFT"


def test_formula_line_add_after_submit_fails_invalid_state(
    api, formulation_scientist_headers
):
    """PRD §3.3: "While a formula is in `DRAFT`, the `FormulationScientist` builds
    its composition as **Formula Ingredient** lines."
    PRD §2.10: "Fourth, transition validity: the requested action must correspond
    to a transition that exists from the resource's current state, else
    `ERR_INVALID_STATE` (HTTP 409)"

    Design: Corner/state_machines/formula_line_add_after_submit_fails_invalid_state
    """
    ctx = setup_nutrient_review_formula()
    extra = create_ingredient()
    resp = api.add_formula_ingredient(
        ctx["formula"]["id"],
        {"ingredient_id": extra["id"], "inclusion_pct": 10.0},
        formulation_scientist_headers,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_formula_second_lock_fails_invalid_state(api, qa_approver_headers):
    """PRD §3.3: "Locking moves a `SUBSTANTIATED` formula to `LOCKED`, the only
    state from which production may be scheduled."
    PRD §2.10: "Fourth, transition validity: the requested action must correspond
    to a transition that exists from the resource's current state, else
    `ERR_INVALID_STATE` (HTTP 409)"

    Design: Corner/state_machines/formula_second_lock_fails_invalid_state
    """
    ctx = setup_locked_formula()
    assert ctx["formula"]["status"] == "LOCKED"
    resp = api.lock_formula(ctx["formula"]["id"], qa_approver_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    assert get_formula(ctx["formula"]["id"])["status"] == "LOCKED"


def test_formula_withdraw_cascades_approved_registration(api, qa_approver_headers):
    """PRD §3.3: "Withdrawal moves a `LOCKED` formula to `WITHDRAWN` and requires
    that every production batch of the formula already sits in a terminal state —
    `COMPLETED`, `REJECTED`, or `RECALLED`; withdrawal cascades by moving every
    registration of the formula in `APPROVED` to `REVOKED`."
    PRD §3.7: "Either decision stamps `decided_at`; rejection moves the
    registration to `REJECTED`."

    Design: Corner/state_machines/formula_withdraw_cascades_approved_registration
    """
    # SUBSTANTIATED formula + registration walked to APPROVED, then lock.
    ctx = setup_registration(target_state="APPROVED", state_code="WA")
    assert ctx["registration"]["status"] == "APPROVED"
    decided_at = ctx["registration"]["decided_at"]
    assert decided_at, "approval must stamp decided_at"
    locked = validate_success(api.lock_formula(ctx["formula"]["id"], qa_approver_headers))
    assert locked["status"] == "LOCKED"

    withdrawn = validate_success(api.withdraw_formula(ctx["formula"]["id"], qa_approver_headers))
    assert withdrawn["status"] == "WITHDRAWN"
    registration = get_registration(ctx["registration"]["id"])
    assert registration["status"] == "REVOKED"
    assert registration["decided_at"] == decided_at


def test_formula_withdrawn_locks_all_transitions(
    api, qa_approver_headers, formulation_scientist_headers
):
    """PRD §3.3: "`SUPERSEDED` and `WITHDRAWN` are the formula's terminal states."
    PRD §2.10: "a resource already in a terminal state accepts no further
    transitions at all and rejects them with `ERR_ALREADY_TERMINAL` (HTTP 409)."

    Design: Corner/state_machines/formula_withdrawn_locks_all_transitions
    """
    ctx = setup_locked_formula()
    withdrawn = validate_success(api.withdraw_formula(ctx["formula"]["id"], qa_approver_headers))
    assert withdrawn["status"] == "WITHDRAWN"

    resp = api.submit_nutrient_review(ctx["formula"]["id"], formulation_scientist_headers)
    validate_error(resp, ApiErrorId.ERR_ALREADY_TERMINAL.value)
    assert get_formula(ctx["formula"]["id"])["status"] == "WITHDRAWN"
