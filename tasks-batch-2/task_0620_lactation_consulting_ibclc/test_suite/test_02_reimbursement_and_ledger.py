"""Superbill reimbursement: ACA vs standard cost-share, the non-linear deductible
clamp, the denied/resubmit cycle, the pay->ledger cascade, ledger reversal on
void, and the optimistic-concurrency guard.

Depth instances (queue A): dual_variant_calc, combinatorial_formula,
non_linear_state_machine, transitive_cascade, compensating_invariant; plus
corner-design breadth for the OCC stale-version path.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    create_completed_consult, create_submitted_superbill, create_paid_superbill,
    draft_superbill, submit_superbill, adjudicate_superbill, get_client,
    TEST_USERS,
)

BILLING = TEST_USERS["billing_specialist_headers"]


# ─── dual_variant_calc / reimbursement_aca_preventive_vs_standard_cost_share ─

def test_aca_preventive_reimburses_full_allowed(api):
    """PRD §3.9: "If the superbill is ACA-preventive — `is_aca_preventive` is true and
    the practice's `aca_preventive_enabled` is true — the full allowed amount is
    reimbursed: `reimbursed_amount_cents` equals `allowed_amount_cents` and
    `patient_responsibility_cents` is 0 regardless of any deductible or coinsurance."

    Allowed 15000, ACA preventive -> reimbursed 15000, patient responsibility 0.

    Design: Difficulty/dual_variant_calc/reimbursement_aca_preventive_vs_standard_cost_share
    """
    ctx = create_submitted_superbill(
        billed_amount_cents=25000, allowed_amount_cents=15000, is_aca_preventive=True)
    paid = validate_success(
        api.adjudicate_superbill(ctx["superbill"]["id"], {"outcome": "PAID"}, BILLING), 200)
    assert paid["reimbursed_amount_cents"] == 15000
    assert paid["patient_responsibility_cents"] == 0


def test_standard_cost_share_subtracts_deductible_and_coinsurance(api):
    """PRD §3.9: "The deductible actually applied is the smaller of the allowed
    amount and `deductible_remaining_cents`."
    PRD §3.9: "The coinsurance is that after-deductible amount multiplied by
    `coinsurance_pct`, divided by one hundred, rounded half-up to whole cents. The
    patient responsibility is the applied deductible plus the coinsurance, and
    `reimbursed_amount_cents` is the allowed amount minus that patient responsibility."

    Allowed 15000, deductible 4000, coinsurance 20%: applied deductible 4000,
    after-deductible 11000, coinsurance 2200, patient responsibility 6200,
    reimbursed 8800.

    Design: Difficulty/dual_variant_calc/reimbursement_aca_preventive_vs_standard_cost_share
    """
    ctx = create_submitted_superbill(
        billed_amount_cents=25000, allowed_amount_cents=15000,
        is_aca_preventive=False, deductible_remaining_cents=4000, coinsurance_pct=20)
    paid = validate_success(
        api.adjudicate_superbill(ctx["superbill"]["id"], {"outcome": "PAID"}, BILLING), 200)
    assert paid["reimbursed_amount_cents"] == 8800, (
        f"expected 8800, got {paid['reimbursed_amount_cents']}")
    assert paid["patient_responsibility_cents"] == 6200, (
        f"expected 6200, got {paid['patient_responsibility_cents']}")


# ─── combinatorial_formula / reimbursement_three_input_nonlinear_clamp ──────

def test_reimbursement_deductible_clamped_to_allowed(api):
    """PRD §3.9: "The deductible actually applied is the smaller of the allowed
    amount and `deductible_remaining_cents`. The amount remaining after the
    deductible is the allowed amount minus that applied deductible."

    Deductible 20000 exceeds allowed 15000, so applied deductible clamps to 15000;
    after-deductible 0, coinsurance 0, reimbursed 0, patient responsibility 15000.

    Design: Difficulty/combinatorial_formula/reimbursement_three_input_nonlinear_clamp
    """
    ctx = create_submitted_superbill(
        billed_amount_cents=25000, allowed_amount_cents=15000,
        is_aca_preventive=False, deductible_remaining_cents=20000, coinsurance_pct=20)
    paid = validate_success(
        api.adjudicate_superbill(ctx["superbill"]["id"], {"outcome": "PAID"}, BILLING), 200)
    assert paid["reimbursed_amount_cents"] == 0, (
        f"expected 0, got {paid['reimbursed_amount_cents']}")
    assert paid["patient_responsibility_cents"] == 15000, (
        f"expected 15000, got {paid['patient_responsibility_cents']}")


def test_patient_responsibility_complements_reimbursed(api):
    """PRD §3.9: "In both branches `patient_responsibility_cents` equals
    `allowed_amount_cents` minus `reimbursed_amount_cents`."

    With the deductible fully clamping the allowed amount, reimbursed 0 implies
    patient responsibility == allowed 15000.

    Design: Difficulty/combinatorial_formula/reimbursement_three_input_nonlinear_clamp
    """
    ctx = create_submitted_superbill(
        billed_amount_cents=25000, allowed_amount_cents=15000,
        is_aca_preventive=False, deductible_remaining_cents=20000, coinsurance_pct=20)
    paid = validate_success(
        api.adjudicate_superbill(ctx["superbill"]["id"], {"outcome": "PAID"}, BILLING), 200)
    assert (paid["patient_responsibility_cents"]
            == paid["allowed_amount_cents"] - paid["reimbursed_amount_cents"])


# ─── non_linear_state_machine / superbill_denied_resubmit_cycle ─────────────

def test_superbill_denied_then_resubmit_then_paid(api):
    """PRD §3.9: "A denied superbill may be resubmitted, advancing `DENIED →
    SUBMITTED` under the same preconditions as a first submit".
    PRD §3.9: "When `outcome` is `PAID`, the superbill advances `SUBMITTED → PAID`,
    the reimbursement figures are computed (below)".

    DENIED -> SUBMITTED -> PAID loops back through SUBMITTED; with allowed 10000,
    deductible 0, coinsurance 0 -> reimbursed 10000.

    Design: Difficulty/non_linear_state_machine/superbill_denied_resubmit_cycle
    """
    ctx = create_submitted_superbill(
        billed_amount_cents=20000, allowed_amount_cents=10000,
        is_aca_preventive=False, deductible_remaining_cents=0, coinsurance_pct=0)
    sb_id = ctx["superbill"]["id"]
    adjudicate_superbill(sb_id, "DENIED")

    submit_superbill(sb_id)
    paid = validate_success(
        api.adjudicate_superbill(sb_id, {"outcome": "PAID"}, BILLING), 200)
    assert paid["status"] == "PAID", f"expected PAID, got {paid['status']}"
    assert paid["reimbursed_amount_cents"] == 10000


def test_superbill_denied_sets_full_patient_responsibility(api):
    """PRD §3.9: "When `outcome` is `DENIED`, the superbill advances `SUBMITTED →
    DENIED`, `reimbursed_amount_cents` is set to 0, and `patient_responsibility_cents`
    is set to the full `allowed_amount_cents`."

    Design: Difficulty/non_linear_state_machine/superbill_denied_resubmit_cycle
    """
    ctx = create_submitted_superbill(
        billed_amount_cents=20000, allowed_amount_cents=10000,
        is_aca_preventive=False, deductible_remaining_cents=0, coinsurance_pct=0)
    denied = validate_success(
        api.adjudicate_superbill(ctx["superbill"]["id"], {"outcome": "DENIED"}, BILLING), 200)
    assert denied["status"] == "DENIED"
    assert denied["reimbursed_amount_cents"] == 0
    assert denied["patient_responsibility_cents"] == 10000


# ─── transitive_cascade / superbill_pay_ledger_sync_depth2 ──────────────────

def test_paid_adjudication_increases_client_ledger(api):
    """PRD §3.9: "the client's reimbursement ledger is increased:
    `reimbursement_ledger_cents` grows by the just-computed `reimbursed_amount_cents`".

    A PAID ACA-preventive superbill (allowed 15000) drives the client's
    reimbursement_ledger_cents to 15000.

    Design: Difficulty/transitive_cascade/superbill_pay_ledger_sync_depth2
    """
    ctx = create_submitted_superbill(
        billed_amount_cents=25000, allowed_amount_cents=15000, is_aca_preventive=True)
    paid = validate_success(
        api.adjudicate_superbill(ctx["superbill"]["id"], {"outcome": "PAID"}, BILLING), 200)
    assert paid["reimbursed_amount_cents"] == 15000

    client = get_success_data(api.get_client(ctx["client"]["id"], BILLING))
    assert client["reimbursement_ledger_cents"] == 15000, (
        f"expected ledger 15000, got {client['reimbursement_ledger_cents']}")


def test_paid_adjudication_bumps_client_version(api):
    """PRD §3.9: "and as a ledger mutation the client's `version` advances by one."

    The PAID adjudication is a client mutation, so the client's version is strictly
    greater after payout than before.

    Design: Difficulty/transitive_cascade/superbill_pay_ledger_sync_depth2
    """
    ctx = create_submitted_superbill(
        billed_amount_cents=25000, allowed_amount_cents=15000, is_aca_preventive=True)
    before = get_success_data(api.get_client(ctx["client"]["id"], BILLING))["version"]
    validate_success(
        api.adjudicate_superbill(ctx["superbill"]["id"], {"outcome": "PAID"}, BILLING), 200)
    after = get_success_data(api.get_client(ctx["client"]["id"], BILLING))["version"]
    assert after > before, f"client version must advance: before {before}, after {after}"


# ─── compensating_invariant / reimbursement_ledger_conserved_on_void ────────

def test_void_paid_superbill_reverses_ledger_to_zero(api):
    """PRD §3.9: "A paid superbill can be voided, advancing `PAID → VOID`, which
    reverses its contribution to the client ledger: `reimbursement_ledger_cents` is
    decreased by the superbill's `reimbursed_amount_cents` so the ledger returns to
    its pre-payment value, and the client's `version` advances by one."

    Voiding a PAID superbill (reimbursed 15000) returns the ledger to 0.

    Design: Difficulty/compensating_invariant/reimbursement_ledger_conserved_on_void
    """
    ctx = create_paid_superbill(
        billed_amount_cents=25000, allowed_amount_cents=15000, is_aca_preventive=True)
    client_ver = get_success_data(api.get_client(ctx["client"]["id"], BILLING))["version"]

    voided = validate_success(api.void_superbill(
        ctx["superbill"]["id"], {"expected_client_version": client_ver}, BILLING), 200)
    assert voided["status"] == "VOID", f"expected VOID, got {voided['status']}"

    client = get_success_data(api.get_client(ctx["client"]["id"], BILLING))
    assert client["reimbursement_ledger_cents"] == 0, (
        f"ledger must return to 0, got {client['reimbursement_ledger_cents']}")


def test_void_superbill_status_becomes_void(api):
    """PRD §3.9: "A paid superbill can be voided, advancing `PAID → VOID`".

    The voided superbill lands in the terminal VOID state.

    Design: Difficulty/compensating_invariant/reimbursement_ledger_conserved_on_void
    """
    ctx = create_paid_superbill(
        billed_amount_cents=25000, allowed_amount_cents=15000, is_aca_preventive=True)
    client_ver = get_success_data(api.get_client(ctx["client"]["id"], BILLING))["version"]
    voided = validate_success(api.void_superbill(
        ctx["superbill"]["id"], {"expected_client_version": client_ver}, BILLING), 200)
    assert voided["status"] == "VOID"


# ─── Corner: cross_cutting_complexity_layers / occ_void_stale_client_version ─

def test_void_with_stale_client_version_rejected(api):
    """PRD §2.9: "The server compares `expected_client_version` to the client's
    current `version`. If another mutation — a second superbill paying out, or a
    no-show strike — has advanced the client's `version` since the caller last read
    it, the values differ and the void is rejected with `ERR_STALE_CLIENT_VERSION`
    (HTTP 412), so the reversal is never applied on top of an out-of-date balance."

    A version observed BEFORE the PAID adjudication (which bumps the client version)
    is stale; the void is rejected and the ledger stays at 15000.

    Design: Corner/cross_cutting_complexity_layers/occ_void_stale_client_version_returns_412
    """
    # Build a completed consult, capture the stale client version, then pay out.
    ctx = create_completed_consult()
    stale_ver = get_success_data(api.get_client(ctx["client"]["id"], BILLING))["version"]

    sb = draft_superbill(ctx["consult"]["id"], 25000, 15000, is_aca_preventive=True)
    submit_superbill(sb["id"])
    adjudicate_superbill(sb["id"], "PAID")  # bumps client.version

    resp = api.void_superbill(sb["id"], {"expected_client_version": stale_ver}, BILLING)
    validate_error(resp, ApiErrorId.ERR_STALE_CLIENT_VERSION.value)

    client = get_success_data(api.get_client(ctx["client"]["id"], BILLING))
    assert client["reimbursement_ledger_cents"] == 15000, (
        "ledger must be untouched when the void is rejected")
