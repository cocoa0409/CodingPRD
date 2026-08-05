"""Coding scrub: line pricing resolution, provisional patient split, and scrub guards.

Translates the combinatorial-formula difficulty instance (patient-responsibility
cap) plus the entities/state_machines/validations corner instances around scrub.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId,
    make_account_manager_headers, make_coder_headers, make_biller_headers,
)
from test_helpers import fixtures as fx

AM = make_account_manager_headers()
CODER = make_coder_headers()
BILLER = make_biller_headers()


# ---- Difficulty: combinatorial_formula / patient_responsibility_min_cap_binds ----
def test_patient_responsibility_capped_at_total_allowed(api):
    """PRD §3.3: "The provisional `patient_responsibility_cents` is then the smaller of
    two quantities: the sum of the deductible applied, the rounded coinsurance, and the
    claim's `copay_cents`; and the total allowed."
    PRD §3.3: "It computes the provisional patient responsibility (below), sets
    `expected_reimbursement_cents` to the claim's `allowed_amount_cents` minus its
    `patient_responsibility_cents`"

    Design: Difficulty/combinatorial_formula/patient_responsibility_min_cap_binds
    """
    ctx = fx.setup_scrubbed_claim(
        api, prices={"99213": 5000}, credential="none", enrollment="none",
        deductible_remaining_cents=10000, coinsurance_pct=0.20, copay_cents=2000,
        lines=[{"cpt_code": "99213", "units": 1, "charge_amount_cents": 9000}],
        coder_user_id="coder-2")
    claim = validate_success(api.get_claim(ctx["claim"]["id"], CODER), 200)
    assert claim["patient_responsibility_cents"] == 5000, claim["patient_responsibility_cents"]
    assert claim["expected_reimbursement_cents"] == 0, claim["expected_reimbursement_cents"]


def test_patient_responsibility_cap_ledger_consistency(api):
    """PRD §3.3: "sets `contractual_adjustment_cents` to `billed_amount_cents` minus
    `allowed_amount_cents` — the write-down the payer contract mandates."
    PRD §3.6: "`outstanding_balance_cents` is `billed_amount_cents` minus
    `contractual_adjustment_cents` minus `insurance_paid_cents` minus
    `patient_responsibility_cents` minus `write_off_cents`."

    Design: Difficulty/combinatorial_formula/patient_responsibility_min_cap_binds
    """
    ctx = fx.setup_scrubbed_claim(
        api, prices={"99213": 5000}, credential="none", enrollment="none",
        deductible_remaining_cents=10000, coinsurance_pct=0.20, copay_cents=2000,
        lines=[{"cpt_code": "99213", "units": 1, "charge_amount_cents": 9000}],
        coder_user_id="coder-2")
    claim = validate_success(api.get_claim(ctx["claim"]["id"], CODER), 200)
    assert claim["contractual_adjustment_cents"] == 4000, claim["contractual_adjustment_cents"]
    assert claim["outstanding_balance_cents"] == 0, claim["outstanding_balance_cents"]


# ---- Corner: entities / claim_line_allowed_amount_computed_at_scrub ----
def test_claim_line_allowed_amount_resolved_at_scrub(api):
    """PRD §3.3: "the platform resolves each line's `allowed_amount_cents` as that
    line's `units` multiplied by the covering fee schedule's allowed amount for the
    line's `cpt_code`."
    PRD §3.3: "It then freezes the claim's `billed_amount_cents` as the sum of the
    lines' `charge_amount_cents` and the claim's `allowed_amount_cents` as the sum of
    the lines' resolved `allowed_amount_cents`"

    Design: Corner/entities/claim_line_allowed_amount_computed_at_scrub
    """
    ctx = fx.setup_scrubbed_claim(
        api, prices={"99213": 10000}, credential="none", enrollment="none",
        lines=[{"cpt_code": "99213", "units": 2, "charge_amount_cents": 40000}],
        coder_user_id="coder-c1")
    claim = validate_success(api.get_claim(ctx["claim"]["id"], CODER), 200)
    assert claim["allowed_amount_cents"] == 20000, claim["allowed_amount_cents"]
    assert claim["billed_amount_cents"] == 40000, claim["billed_amount_cents"]
    assert claim["contractual_adjustment_cents"] == 20000, claim["contractual_adjustment_cents"]
    lines, _ = validate_paginated(api.list_claim_lines(ctx["claim"]["id"], CODER))
    assert lines[0]["allowed_amount_cents"] == 20000, lines[0]["allowed_amount_cents"]


# ---- Corner: state_machines / scrub_already_scrubbed_claim_returns_invalid_state ----
def test_scrub_already_scrubbed_claim_returns_invalid_state(api):
    """PRD §3.3: "A scrub is allowed only from `DRAFT`."
    PRD §3: "if the target resource is not in a state from which the requested
    transition is defined, the request is rejected with `ERR_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/scrub_already_scrubbed_claim_returns_invalid_state
    """
    ctx = fx.setup_scrubbed_claim(api, credential="none", enrollment="none",
                                  coder_user_id="coder-c2")
    resp = api.scrub_claim(ctx["claim"]["id"], make_coder_headers("coder-c2"))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    claim = validate_success(api.get_claim(ctx["claim"]["id"], CODER), 200)
    assert claim["status"] == "SCRUBBED"


# ---- Corner: state_machines / accept_from_draft_returns_invalid_state ----
def test_accept_from_draft_returns_invalid_state(api):
    """PRD §3.4: "the `Biller` records the clearinghouse acknowledgement, moving the
    claim from `SUBMITTED` to `ACCEPTED` and incrementing its `version` by one"
    PRD §3: "if the target resource is not in a state from which the requested
    transition is defined, the request is rejected with `ERR_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/accept_from_draft_returns_invalid_state
    """
    fx.set_clock(api, "2026-06-01T00:00:00Z")
    prac = fx.new_practice(api)
    payer = fx.new_payer(api)
    prov = fx.new_provider(api, prac["id"])
    claim = fx.new_claim(api, prac["id"], prov["id"], payer["id"])
    resp = api.accept_claim(claim["id"], BILLER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    got = validate_success(api.get_claim(claim["id"], CODER), 200)
    assert got["status"] == "DRAFT"


# ---- Corner: validations / scrub_claim_with_no_lines_returns_no_claim_lines ----
def test_scrub_claim_with_no_lines_returns_no_claim_lines(api):
    """PRD §3.3: "the claim must have at least one `ClaimLine`, or it is rejected with
    `ERR_NO_CLAIM_LINES` (HTTP 422)"

    Design: Corner/validations/scrub_claim_with_no_lines_returns_no_claim_lines
    """
    ctx = fx.setup_billing_context(api, prices={"99213": 10000}, credential="none",
                                   enrollment="none")
    claim = fx.new_claim(api, ctx["practice"]["id"], ctx["provider"]["id"], ctx["payer"]["id"])
    resp = api.scrub_claim(claim["id"], make_coder_headers("coder-c4"))
    validate_error(resp, ApiErrorId.ERR_NO_CLAIM_LINES.value)
    got = validate_success(api.get_claim(claim["id"], CODER), 200)
    assert got["status"] == "DRAFT"


# ---- Corner: validations / scrub_cpt_not_priced_returns_cpt_not_in_fee_schedule ----
def test_scrub_cpt_not_priced_returns_cpt_not_in_fee_schedule(api):
    """PRD §3.3: "every `cpt_code` appearing on the claim's lines must be priced by that
    covering fee schedule, or it is rejected with `ERR_CPT_NOT_IN_FEE_SCHEDULE`
    (HTTP 422)."

    Design: Corner/validations/scrub_cpt_not_priced_returns_cpt_not_in_fee_schedule
    """
    ctx = fx.setup_billing_context(api, prices={"99213": 10000}, credential="none",
                                   enrollment="none")
    claim = fx.new_claim(api, ctx["practice"]["id"], ctx["provider"]["id"], ctx["payer"]["id"])
    fx.add_claim_line(api, claim["id"], cpt_code="99999", units=1, charge_amount_cents=15000)
    resp = api.scrub_claim(claim["id"], make_coder_headers("coder-c4"))
    validate_error(resp, ApiErrorId.ERR_CPT_NOT_IN_FEE_SCHEDULE.value)
    got = validate_success(api.get_claim(claim["id"], CODER), 200)
    assert got["status"] == "DRAFT"
