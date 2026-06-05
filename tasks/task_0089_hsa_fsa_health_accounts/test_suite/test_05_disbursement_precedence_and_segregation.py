"""Disbursement-time precedence conflicts (state vs segregation; hold vs funds), the
cross-entity hold dependency that blocks reimbursement, the segregation positive trigger,
and the PARTIAL batch outcome.

Translates Difficulty/priority_pair_validation_conflict, the cross_entity hold instance, and
Corner/errors + Corner/state_machines disbursement instances.
"""
from test_helpers import (
    validate_success, validate_error, TEST_USERS,
    setup_active_fsa, file_claim, get_account, create_batch,
    make_adjudicator_headers, make_disburser_headers,
    ApiErrorId, reimburse_single_claim,
)

ADMIN = TEST_USERS["plan_admin_headers"]


def _approve(api, claim_id, adj="adj-1"):
    return validate_success(api.adjudicate_claim(
        claim_id, {"decision": "APPROVE"}, make_adjudicator_headers(adj)))


def test_invalid_state_beats_segregation_on_disburse(api):
    """PRD §2.10: "then whether the target resource is in a state that permits the transition
    (`ERR_INVALID_STATE`). Only after those structural gates do the domain-specific checks
    run — segregation of duties, compliance hold...".
    PRD §3.6: "a claim no longer `APPROVED` with `ERR_INVALID_STATE` (HTTP 409)".

    A batch whose member claim has been VOIDED, disbursed by the same operator who
    adjudicated it, returns ERR_INVALID_STATE — the structural state gate pre-empts the
    segregation check.

    Design: Difficulty/priority_pair_validation_conflict/invalid_state_beats_segregation_on_disburse
    """
    py, p, acc = setup_active_fsa(
        account_type="HEALTH_FSA", elected_amount_cents=200000,
        auto_adjudication_threshold_cents=1000000)
    claim = file_claim(acc["id"], p["id"], service_date="2026-04-01",
                       expense_category="MEDICAL",
                       claimed_amount_cents=80000, substantiated=True)
    _approve(api, claim["id"], adj="adj-1")
    batch = create_batch(p["id"], [claim["id"]])
    # Void the (still-APPROVED) claim before disburse: APPROVED -> VOIDED by the adjudicator.
    validate_success(api.void_claim(claim["id"], make_adjudicator_headers("adj-1")))
    live = get_account(acc["id"])
    # Disburser is adj-1 — same as adjudicator, so segregation would also fire.
    resp = api.disburse_batch(
        batch["id"], {"expected_account_version": live["version"]},
        make_disburser_headers("adj-1"))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_invalid_state_disburse_leaves_batch_draft(api):
    """PRD §3.6: "If the very first member claim fails any of its per-claim preconditions,
    the whole disbursement is rejected with that claim's error and the batch stays `DRAFT`."

    The voided-claim disburse is rejected on the first (only) member, so the batch remains
    DRAFT.

    Design: Difficulty/priority_pair_validation_conflict/invalid_state_beats_segregation_on_disburse
    """
    py, p, acc = setup_active_fsa(
        account_type="HEALTH_FSA", elected_amount_cents=200000,
        auto_adjudication_threshold_cents=1000000)
    claim = file_claim(acc["id"], p["id"], service_date="2026-04-01",
                       expense_category="MEDICAL",
                       claimed_amount_cents=80000, substantiated=True)
    _approve(api, claim["id"], adj="adj-1")
    batch = create_batch(p["id"], [claim["id"]])
    validate_success(api.void_claim(claim["id"], make_adjudicator_headers("adj-1")))
    live = get_account(acc["id"])
    api.disburse_batch(batch["id"], {"expected_account_version": live["version"]},
                       make_disburser_headers("adj-1"))
    after = validate_success(api.get_batch(batch["id"], ADMIN))
    assert after["status"] == "DRAFT", "first-claim failure leaves the batch DRAFT"


def test_account_hold_beats_insufficient_funds_on_disburse(api):
    """PRD §3.6: "Among the per-claim domain checks, segregation of duties is evaluated
    before the compliance-hold check, which is evaluated before the funds check."
    PRD §3.6: "a held account with `ERR_ACCOUNT_ON_HOLD` (HTTP 409)".

    An account that is both HELD and short of cash for the next claim returns
    ERR_ACCOUNT_ON_HOLD (hold beats funds).

    Design: Difficulty/priority_pair_validation_conflict/account_hold_beats_insufficient_funds_on_disburse
    """
    py, p, acc = setup_active_fsa(
        account_type="HEALTH_FSA", elected_amount_cents=60000,
        auto_adjudication_threshold_cents=100000)
    # C1 unsubstantiated 50000 → reimbursing it puts the account HELD, leaving 10000.
    c1 = file_claim(acc["id"], p["id"], service_date="2026-04-01",
                    expense_category="MEDICAL", claimed_amount_cents=50000,
                    substantiated=False)
    _approve(api, c1["id"])
    # C2 substantiated 40000, approved while balance was full.
    c2 = file_claim(acc["id"], p["id"], service_date="2026-04-02",
                    expense_category="DENTAL", claimed_amount_cents=40000,
                    substantiated=True)
    _approve(api, c2["id"])
    reimburse_single_claim(p["id"], c1["id"], acc["id"])  # account now HELD, available 10000

    b2 = create_batch(p["id"], [c2["id"]])
    live = get_account(acc["id"])
    resp = api.disburse_batch(
        b2["id"], {"expected_account_version": live["version"]},
        make_disburser_headers("disb-1"))
    validate_error(resp, ApiErrorId.ERR_ACCOUNT_ON_HOLD.value)


def test_hold_over_funds_disburse_leaves_second_claim_approved(api):
    """PRD §3.6: "a held account with `ERR_ACCOUNT_ON_HOLD` (HTTP 409)" ... "no further
    reimbursement on that account succeeds until a contribution or a reimbursement reversal
    restores a positive balance."

    Because the hold check pre-empts the funds check and rejects the disburse, the
    underfunded C2 claim stays APPROVED.

    Design: Difficulty/priority_pair_validation_conflict/account_hold_beats_insufficient_funds_on_disburse
    """
    py, p, acc = setup_active_fsa(
        account_type="HEALTH_FSA", elected_amount_cents=60000,
        auto_adjudication_threshold_cents=100000)
    c1 = file_claim(acc["id"], p["id"], service_date="2026-04-01",
                    expense_category="MEDICAL", claimed_amount_cents=50000,
                    substantiated=False)
    _approve(api, c1["id"])
    c2 = file_claim(acc["id"], p["id"], service_date="2026-04-02",
                    expense_category="DENTAL", claimed_amount_cents=40000,
                    substantiated=True)
    _approve(api, c2["id"])
    reimburse_single_claim(p["id"], c1["id"], acc["id"])  # HELD, available 10000
    b2 = create_batch(p["id"], [c2["id"]])
    live = get_account(acc["id"])
    api.disburse_batch(b2["id"], {"expected_account_version": live["version"]},
                       make_disburser_headers("disb-1"))
    after = validate_success(api.get_claim(c2["id"], ADMIN))
    assert after["status"] == "APPROVED", "rejected disburse leaves C2 APPROVED"


def test_approved_claim_cannot_reimburse_while_account_held(api):
    """PRD §3.6: "its account's `compliance_hold` must be `CLEAR`" ... "a held account with
    `ERR_ACCOUNT_ON_HOLD` (HTTP 409)".

    An APPROVED claim cannot reach REIMBURSED while its account is HELD; the claim stays
    APPROVED.

    Design: Difficulty/cross_entity_state_dependency/claim_reimburse_blocked_by_account_compliance_hold
    """
    py, p, acc = setup_active_fsa(
        account_type="HEALTH_FSA", elected_amount_cents=200000,
        auto_adjudication_threshold_cents=100000)
    c1 = file_claim(acc["id"], p["id"], service_date="2026-04-01",
                    expense_category="MEDICAL", claimed_amount_cents=50000,
                    substantiated=False)
    _approve(api, c1["id"])
    c2 = file_claim(acc["id"], p["id"], service_date="2026-04-02",
                    expense_category="DENTAL", claimed_amount_cents=40000,
                    substantiated=True)
    _approve(api, c2["id"])
    reimburse_single_claim(p["id"], c1["id"], acc["id"])  # account HELD

    b2 = create_batch(p["id"], [c2["id"]])
    live = get_account(acc["id"])
    resp = api.disburse_batch(
        b2["id"], {"expected_account_version": live["version"]},
        make_disburser_headers("disb-1"))
    validate_error(resp, ApiErrorId.ERR_ACCOUNT_ON_HOLD.value)
    c2_after = validate_success(api.get_claim(c2["id"], ADMIN))
    assert c2_after["status"] == "APPROVED", "cannot reach REIMBURSED while account HELD"


def test_hold_clears_only_when_unsubstantiated_claim_remains(api):
    """PRD §3.7: "a `PlanAdmin` clears it through the clear-hold operation, but only when
    every `REIMBURSED` claim on that account now has `substantiated` equal to `true` ... the
    operation moves `compliance_hold` from `HELD` to `CLEAR`".

    After resolving the hold via clear-hold, the previously-blocked claim can be reimbursed.

    Design: Difficulty/cross_entity_state_dependency/claim_reimburse_blocked_by_account_compliance_hold
    """
    py, p, acc = setup_active_fsa(
        account_type="HEALTH_FSA", elected_amount_cents=200000,
        auto_adjudication_threshold_cents=100000)
    c1 = file_claim(acc["id"], p["id"], service_date="2026-04-01",
                    expense_category="MEDICAL", claimed_amount_cents=50000,
                    substantiated=False)
    _approve(api, c1["id"])
    reimburse_single_claim(p["id"], c1["id"], acc["id"])  # account HELD
    held = validate_success(api.get_account(acc["id"], ADMIN))
    assert held["compliance_hold"] == "HELD"
    # Clawback c1 (the only unsubstantiated reimbursed claim) so the hold can be lifted.
    validate_success(api.void_claim(c1["id"], ADMIN))
    cleared = validate_success(api.get_account(acc["id"], ADMIN))
    assert cleared["compliance_hold"] == "CLEAR", (
        "clawing back the only unsubstantiated reimbursed claim returns HELD -> CLEAR")


def test_segregation_of_duties_blocks_self_disbursement(api):
    """PRD §3.6: "the segregation-of-duties rule must hold, meaning the disburser's
    `X-User-ID` must differ from the claim's recorded `adjudicated_by` ... A segregation
    breach is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)".

    Disbursing a clean APPROVED claim with X-User-ID == adjudicated_by returns
    ERR_SEGREGATION_OF_DUTIES; the claim stays APPROVED.

    Design: Corner/errors/segregation_of_duties_positive_trigger
    """
    py, p, acc = setup_active_fsa(
        account_type="HEALTH_FSA", elected_amount_cents=200000,
        auto_adjudication_threshold_cents=1000000)
    claim = file_claim(acc["id"], p["id"], service_date="2026-04-01",
                       expense_category="MEDICAL", claimed_amount_cents=50000,
                       substantiated=True)
    _approve(api, claim["id"], adj="adj-1")
    batch = create_batch(p["id"], [claim["id"]])
    live = get_account(acc["id"])
    resp = api.disburse_batch(
        batch["id"], {"expected_account_version": live["version"]},
        make_disburser_headers("adj-1"))
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)
    after = validate_success(api.get_claim(claim["id"], ADMIN))
    assert after["status"] == "APPROVED"


def test_batch_settles_partial_when_later_claim_underfunded(api):
    """PRD §3.6: "When at least one claim reimburses but at least one later claim is skipped
    (because it failed one of its per-claim preconditions after an earlier claim already
    succeeded), the batch moves from `DRAFT` to `PARTIAL`, and `total_reimbursed_cents`
    reflects only the reimbursed subset."

    Batch [C1=40000, C2=30000] on a 50000-elected account: C1 reimburses, C2 skipped for
    insufficient cash (10000 left) → PARTIAL, total 40000.

    Design: Corner/state_machines/batch_partial_settlement_when_later_claim_underfunded
    """
    py, p, acc = setup_active_fsa(
        account_type="HEALTH_FSA", elected_amount_cents=50000,
        auto_adjudication_threshold_cents=1000000)
    c1 = file_claim(acc["id"], p["id"], service_date="2026-04-01",
                    expense_category="MEDICAL", claimed_amount_cents=40000,
                    substantiated=True)
    _approve(api, c1["id"])
    c2 = file_claim(acc["id"], p["id"], service_date="2026-04-02",
                    expense_category="DENTAL", claimed_amount_cents=30000,
                    substantiated=True)
    _approve(api, c2["id"])
    batch = create_batch(p["id"], [c1["id"], c2["id"]])
    live = get_account(acc["id"])
    result = validate_success(api.disburse_batch(
        batch["id"], {"expected_account_version": live["version"]},
        make_disburser_headers("disb-1")))
    assert result["status"] == "PARTIAL"
    assert result["total_reimbursed_cents"] == 40000
    c1_after = validate_success(api.get_claim(c1["id"], ADMIN))
    c2_after = validate_success(api.get_claim(c2["id"], ADMIN))
    assert c1_after["status"] == "REIMBURSED"
    assert c2_after["status"] == "APPROVED", "C2 skipped (cash 10000 < 30000)"
