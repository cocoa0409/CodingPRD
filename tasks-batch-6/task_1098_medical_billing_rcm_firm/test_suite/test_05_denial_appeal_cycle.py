"""Denial management and the cyclic appeal workflow: submit cascade, overturn vs
uphold branches, appeal window, and denial-rate KPI.

Translates the non_linear_state_machine and transitive_cascade (appeal submit)
difficulty instances plus the appeal-window and KPI corner instances.
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    make_account_manager_headers, make_denial_specialist_headers,
)
from test_helpers import fixtures as fx

AM = make_account_manager_headers()
DS = make_denial_specialist_headers()


# ---- Difficulty: non_linear_state_machine / cyclic DENIED->APPEALED->DENIED (uphold) ----
def test_appeal_uphold_returns_claim_to_denied(api):
    """PRD §3.5: "An **uphold** outcome moves the appeal from `SUBMITTED` to `UPHELD`,
    moves the denial to `UPHELD`, and cascades the claim from `APPEALED` back to
    `DENIED`, leaving the denial standing — a divergent side-effect set from the
    overturn branch, with no recovery and no ledger restoration."

    Design: Difficulty/non_linear_state_machine/claim_cyclic_denied_appealed_denied
    """
    ctx = fx.setup_appealed_claim(api, denied_amount_cents=8000)
    validate_success(api.decide_appeal(ctx["appeal"]["id"], {"outcome": "UPHOLD"}, DS), 200)
    claim = validate_success(api.get_claim(ctx["claim"]["id"], AM), 200)
    assert claim["status"] == "DENIED", claim["status"]
    assert claim["appeal_round"] == 1, claim["appeal_round"]


def test_appeal_uphold_marks_appeal_and_denial_upheld(api):
    """PRD §3.5: "An **uphold** outcome moves the appeal from `SUBMITTED` to `UPHELD`,
    moves the denial to `UPHELD`, and cascades the claim from `APPEALED` back to
    `DENIED`, leaving the denial standing"

    Design: Difficulty/non_linear_state_machine/claim_cyclic_denied_appealed_denied
    """
    ctx = fx.setup_appealed_claim(api, denied_amount_cents=8000)
    appeal = validate_success(api.decide_appeal(ctx["appeal"]["id"], {"outcome": "UPHOLD"}, DS), 200)
    assert appeal["status"] == "UPHELD", appeal["status"]
    denial = validate_success(api.get_denial(ctx["denial"]["id"], AM), 200)
    assert denial["status"] == "UPHELD", denial["status"]


# ---- Difficulty: non_linear_state_machine / overturn branch reopens claim ----
def test_appeal_overturn_records_recovery_on_appeal(api):
    """PRD §3.5: "An **overturn** outcome moves the appeal from `SUBMITTED` to
    `OVERTURNED`, records the `recovered_amount_cents` onto the appeal, moves the denial
    to `OVERTURNED`, and reopens the claim by cascading it from `APPEALED` back to
    `ACCEPTED`"

    Design: Difficulty/non_linear_state_machine/appeal_branch_overturn_reopens_claim
    """
    ctx = fx.setup_appealed_claim(api, denied_amount_cents=5000)
    appeal = validate_success(
        api.decide_appeal(ctx["appeal"]["id"],
                          {"outcome": "OVERTURN", "recovered_amount_cents": 5000}, DS), 200)
    assert appeal["status"] == "OVERTURNED", appeal["status"]
    assert appeal["recovered_amount_cents"] == 5000, appeal["recovered_amount_cents"]


def test_appeal_overturn_reopens_claim_to_accepted(api):
    """PRD §3.5: "An **overturn** outcome moves the appeal from `SUBMITTED` to
    `OVERTURNED`, records the `recovered_amount_cents` onto the appeal, moves the denial
    to `OVERTURNED`, and reopens the claim by cascading it from `APPEALED` back to
    `ACCEPTED`"

    Design: Difficulty/non_linear_state_machine/appeal_branch_overturn_reopens_claim
    """
    ctx = fx.setup_appealed_claim(api, denied_amount_cents=5000)
    api.decide_appeal(ctx["appeal"]["id"],
                      {"outcome": "OVERTURN", "recovered_amount_cents": 5000}, DS)
    denial = validate_success(api.get_denial(ctx["denial"]["id"], AM), 200)
    assert denial["status"] == "OVERTURNED", denial["status"]
    claim = validate_success(api.get_claim(ctx["claim"]["id"], AM), 200)
    assert claim["status"] == "ACCEPTED", claim["status"]


# ---- Difficulty: transitive_cascade / appeal submit cascades denial then claim ----
def test_appeal_submit_cascades_denial_to_appealed(api):
    """PRD §3.5: "A successful submission sets the appeal to `SUBMITTED`, stamps
    `submitted_date` with the current clock, moves the denial from `OPEN` to `APPEALED`,
    cascades the claim from `DENIED` to `APPEALED`, and increments the claim's
    `appeal_round` by one."

    Design: Difficulty/transitive_cascade/appeal_submit_cascades_denial_then_claim
    """
    ctx = fx.setup_drafted_appeal(api, denial_code="CO-45", denied_amount_cents=4000)
    appeal = validate_success(api.submit_appeal(ctx["appeal"]["id"], DS), 200)
    assert appeal["status"] == "SUBMITTED", appeal["status"]
    denial = validate_success(api.get_denial(ctx["denial"]["id"], AM), 200)
    assert denial["status"] == "APPEALED", denial["status"]


def test_appeal_submit_cascades_claim_to_appealed(api):
    """PRD §3.5: "A successful submission sets the appeal to `SUBMITTED`, stamps
    `submitted_date` with the current clock, moves the denial from `OPEN` to `APPEALED`,
    cascades the claim from `DENIED` to `APPEALED`, and increments the claim's
    `appeal_round` by one."

    Design: Difficulty/transitive_cascade/appeal_submit_cascades_denial_then_claim
    """
    ctx = fx.setup_drafted_appeal(api, denial_code="CO-45", denied_amount_cents=4000)
    api.submit_appeal(ctx["appeal"]["id"], DS)
    claim = validate_success(api.get_claim(ctx["claim"]["id"], AM), 200)
    assert claim["status"] == "APPEALED", claim["status"]
    assert claim["appeal_round"] == 1, claim["appeal_round"]


# ---- Corner: validations / appeal submit past window ----
def test_appeal_submit_past_window_returns_appeal_window_exceeded(api):
    """PRD §3.5: "the number of whole days from the denial's `denial_date` to the
    current logical clock does not exceed the payer's `appeal_window_days`; exceeding
    that window is rejected with `ERR_APPEAL_WINDOW_EXCEEDED` (HTTP 422)."

    Design: Corner/validations/appeal_submit_past_window_returns_appeal_window_exceeded
    """
    ctx = fx.setup_drafted_appeal(api, timely_filing_days=365, appeal_window_days=60,
                                  denial_code="CO-16", denied_amount_cents=5000,
                                  denial_date="2026-01-01T00:00:00Z", narrative="Late appeal attempt.")
    resp = api.submit_appeal(ctx["appeal"]["id"], DS)
    validate_error(resp, ApiErrorId.ERR_APPEAL_WINDOW_EXCEEDED.value)
    appeal = validate_success(api.get_appeal(ctx["appeal"]["id"], AM), 200)
    assert appeal["status"] == "DRAFT", appeal["status"]


# ---- Corner: calculations / KPI denial rate for a single denied claim ----
def test_kpi_denial_rate_for_single_denied_claim(api):
    """PRD §3.8: "The `total_claims` count is the number of the practice's claims whose
    status is neither `DRAFT` nor `VOID`."
    PRD §3.8: "a claim is counted as "denied" when it ever entered denial — meaning it
    is currently `DENIED` or `APPEALED`, or it has any `Denial` recorded against it. ...
    The `denial_rate` is the count of denied claims divided by `total_claims`, rounded
    half-up to four decimal places, and is 0 when there are no counted claims."

    Design: Corner/calculations/kpi_denial_rate_for_single_denied_claim
    """
    ctx = fx.setup_denied_claim(api, denial_code="CO-97", denied_amount_cents=5000)
    data = validate_success(api.get_practice_kpi(ctx["practice"]["id"], AM), 200)
    assert data["total_claims"] == 1, data["total_claims"]
    assert data["denial_rate"] == 1.0, data["denial_rate"]
    assert data["clean_claim_rate"] == 0.0, data["clean_claim_rate"]
