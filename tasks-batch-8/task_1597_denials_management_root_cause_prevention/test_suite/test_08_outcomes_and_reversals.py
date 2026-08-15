"""Outcome recording, reversals, and their cascades (PRD §2.9, §3.1, §3.4)."""
from test_helpers import (
    ApiErrorId,
    assert_denial_dollar_conservation,
    build_user_headers,
    get_denial,
    get_payer,
    get_scorecard,
    make_appeal,
    make_lettered_appeal,
    make_queued_denial,
    make_scorecard,
    make_submitted_appeal,
    make_write_off,
    manager_headers,
    record_outcome,
    reversal_payload,
    set_clock,
    setup_catalog,
    setup_denial_with_submitted_appeal,
    validate_error,
    validate_paginated,
    validate_success,
)

OUTCOME_SHAPE_CITE = (
    'PRD §3.4: "The amount must match the outcome kind, else `ERR_OUTCOME_AMOUNT_INCONSISTENT`: '
    '`OVERTURNED` requires the recovered amount to equal the denial\'s current '
    '`open_balance_cents`; `PARTIALLY_OVERTURNED` requires it to be greater than zero and '
    'strictly less than the open balance; `UPHELD` requires it to be exactly zero."'
)


def test_overturn_outcome_resolves_denial_paid(api, specialist_headers):
    """PRD §3.4: "An `OVERTURNED` outcome adds the recovered amount to the denial's
    `recovered_amount_cents`; the open balance thereby reaches zero and, provided nothing has
    been written off, the denial resolves `IN_APPEAL` → `RESOLVED_PAID` with
    `next_appeal_deadline` cleared to null."
    PRD §2.9: "At all times, `open_balance_cents`, `recovered_amount_cents`, and
    `written_off_cents` sum exactly to `denied_amount_cents`, in integer cents."

    Design: Difficulty/transitive_cascade/overturn_outcome_recovery_cascade
    """
    catalog = setup_catalog(levels=(1,))
    make_scorecard()
    denial_id, appeal = setup_denial_with_submitted_appeal(
        catalog["payer"]["id"], catalog["code"]["id"], "CLM-701",
        denied_amount_cents=100000, billed_amount_cents=120000,
    )
    set_clock("2026-08-05T00:00:00Z")
    outcome = record_outcome(appeal["id"], "OVERTURNED", 100000)
    assert outcome["status"] == "OVERTURNED"
    assert outcome["outcome_amount_cents"] == 100000
    denial = get_denial(denial_id)
    assert denial["status"] == "RESOLVED_PAID"
    assert denial["recovered_amount_cents"] == 100000
    assert denial["open_balance_cents"] == 0
    assert denial["next_appeal_deadline"] is None
    assert_denial_dollar_conservation(denial)


def test_overturn_outcome_scorecard_recovered_cascade(api, manager_headers):
    """PRD §3.4: "All three kinds append an `OUTCOME_RECORDED` event, and all three feed the
    measurement layer: when an `OPEN` scorecard for the denial's `root_cause_department`
    covers the outcome date, its `recovered_cents` increases by the outcome amount, and the
    payer's trailing overturn rate and `appeal_policy_review_required` flag are recomputed
    per §3.1."
    PRD §3.1: "Below a sample of 3, the flag keeps whatever value it currently holds."

    Design: Difficulty/transitive_cascade/overturn_outcome_recovery_cascade
    """
    catalog = setup_catalog(levels=(1,))
    scorecard = make_scorecard()
    denial_id, appeal = setup_denial_with_submitted_appeal(
        catalog["payer"]["id"], catalog["code"]["id"], "CLM-701",
        denied_amount_cents=100000, billed_amount_cents=120000,
    )
    set_clock("2026-08-05T00:00:00Z")
    record_outcome(appeal["id"], "OVERTURNED", 100000)
    sc = get_scorecard(scorecard["id"])
    assert sc["recovered_cents"] == 100000
    payer = get_payer(catalog["payer"]["id"])
    assert payer["appeal_policy_review_required"] is False, (
        "one resolved appeal is below the sample of 3, so the flag keeps its current value"
    )


def test_outcome_reversal_restores_denial_dollars(api, auditor_headers):
    """PRD §2.9: "Recording an appeal outcome and later reversing that same outcome form a
    compensating pair, and approving a write-off and later rescinding it form another: each
    pair must leave the recovered amount (respectively the written-off amount) and the open
    balance identical to their values before the pair ran."
    PRD §3.4: "A denial that never left `IN_APPEAL` keeps its status and existing deadline,
    changed only by the dollar correction."

    Design: Difficulty/compensating_invariant/dollar_conservation_outcome_reversal
    """
    catalog = setup_catalog(levels=(1, 2))
    make_scorecard()
    denial_id, appeal = setup_denial_with_submitted_appeal(
        catalog["payer"]["id"], catalog["code"]["id"], "CLM-1601",
    )
    set_clock("2026-08-05T00:00:00Z")
    record_outcome(appeal["id"], "PARTIALLY_OVERTURNED", 100000)
    mid = get_denial(denial_id)
    assert mid["recovered_amount_cents"] == 100000
    assert mid["open_balance_cents"] == 150000
    assert mid["status"] == "IN_APPEAL"
    assert mid["next_appeal_deadline"] == "2026-09-19"  # outcome 2026-08-05 + level-2 45 days
    assert_denial_dollar_conservation(mid)
    reversed_appeal = validate_success(
        api.reverse_outcome(appeal["id"], reversal_payload(
            "Payer reissued the remittance; outcome miskeyed"), auditor_headers)
    )
    assert reversed_appeal["status"] == "SUBMITTED"
    assert reversed_appeal["outcome_amount_cents"] == 0


def test_outcome_reversal_leaves_no_drift(api, auditor_headers, manager_headers):
    """PRD §2.9: "Recording an appeal outcome and later reversing that same outcome form a
    compensating pair, and approving a write-off and later rescinding it form another: each
    pair must leave the recovered amount (respectively the written-off amount) and the open
    balance identical to their values before the pair ran."
    PRD §3.4: "The reversal subtracts the amount from the matching `OPEN` scorecard's
    `recovered_cents`, recomputes the payer's trailing rate and review flag, and appends an
    `OUTCOME_REVERSED` event."

    Design: Difficulty/compensating_invariant/dollar_conservation_outcome_reversal
    """
    catalog = setup_catalog(levels=(1, 2))
    scorecard = make_scorecard()
    denial_id, appeal = setup_denial_with_submitted_appeal(
        catalog["payer"]["id"], catalog["code"]["id"], "CLM-1601",
    )
    set_clock("2026-08-05T00:00:00Z")
    record_outcome(appeal["id"], "PARTIALLY_OVERTURNED", 100000)
    validate_success(api.reverse_outcome(appeal["id"], reversal_payload(), auditor_headers))
    denial = get_denial(denial_id)
    assert denial["recovered_amount_cents"] == 0, "identical to the pre-pair value"
    assert denial["open_balance_cents"] == 250000, "identical to the pre-pair value"
    assert denial["status"] == "IN_APPEAL"
    assert denial["next_appeal_deadline"] == "2026-09-19", "status and deadline kept"
    assert_denial_dollar_conservation(denial)
    sc = get_scorecard(scorecard["id"])
    assert sc["recovered_cents"] == 0, "100000 added at outcome, then subtracted at reversal"


def test_outcome_amount_shape_enforced(api, specialist_headers):
    """PRD §3.4: "The amount must match the outcome kind, else
    `ERR_OUTCOME_AMOUNT_INCONSISTENT`: `OVERTURNED` requires the recovered amount to equal
    the denial's current `open_balance_cents`; `PARTIALLY_OVERTURNED` requires it to be
    greater than zero and strictly less than the open balance; `UPHELD` requires it to be
    exactly zero."

    Design: Corner/validations/outcome_amount_shape_enforced
    """
    catalog = setup_catalog(levels=(1,))
    denial_id, appeal = setup_denial_with_submitted_appeal(
        catalog["payer"]["id"], catalog["code"]["id"], "CLM-2301",
    )
    resp1 = api.record_outcome(
        appeal["id"], {"outcome": "UPHELD", "recovered_amount_cents": 5000}, specialist_headers,
    )
    validate_error(resp1, ApiErrorId.ERR_OUTCOME_AMOUNT_INCONSISTENT, expected_status=422)
    resp2 = api.record_outcome(
        appeal["id"],
        {"outcome": "PARTIALLY_OVERTURNED", "recovered_amount_cents": 250000},
        specialist_headers,
    )
    validate_error(resp2, ApiErrorId.ERR_OUTCOME_AMOUNT_INCONSISTENT, expected_status=422)
    after = validate_success(api.get_appeal(appeal["id"], specialist_headers))
    assert after["status"] == "SUBMITTED"


def test_record_outcome_before_submit_rejected(api, specialist_headers):
    """PRD §3.4: "**Outcome recording** applies only from `SUBMITTED` (else
    `ERR_APPEAL_INVALID_STATE`) and takes an `outcome`, a `recovered_amount_cents` figure,
    and an optional `payer_response_code`."

    Design: Corner/state_machines/record_outcome_before_submit_rejected
    """
    catalog = setup_catalog(levels=(1,))
    denial = make_queued_denial(
        catalog["payer"]["id"], catalog["code"]["id"], claim_number="CLM-2103",
    )
    appeal = make_lettered_appeal(denial["id"])
    resp = api.record_outcome(
        appeal["id"], {"outcome": "UPHELD", "recovered_amount_cents": 0}, specialist_headers,
    )
    validate_error(resp, ApiErrorId.ERR_APPEAL_INVALID_STATE, expected_status=409)
    after = validate_success(api.get_appeal(appeal["id"], specialist_headers))
    assert after["status"] == "LETTER_GENERATED"


def test_resolved_paid_terminal_lockdown(api, specialist_headers):
    """PRD §3.2: "**Triage** moves a denial from `RECEIVED` to `TRIAGED` and is performed by
    a `DenialsSpecialist`; attempting it from any other status yields
    `ERR_DENIAL_INVALID_STATE`."
    PRD §3.4: "Creation evaluates its gates in §2.8's order: the denial must be in `QUEUED`
    or `IN_APPEAL` (else `ERR_DENIAL_INVALID_STATE`) ..."

    Design: Corner/state_machines/resolved_paid_terminal_lockdown
    """
    catalog = setup_catalog(levels=(1,))
    denial_id, appeal = setup_denial_with_submitted_appeal(
        catalog["payer"]["id"], catalog["code"]["id"], "CLM-2102",
        denied_amount_cents=100000, billed_amount_cents=120000,
    )
    record_outcome(appeal["id"], "OVERTURNED", 100000)
    assert get_denial(denial_id)["status"] == "RESOLVED_PAID"
    resp1 = api.triage_denial(denial_id, {"preventable_flag": False}, specialist_headers)
    validate_error(resp1, ApiErrorId.ERR_DENIAL_INVALID_STATE, expected_status=409)
    resp2 = api.create_appeal({"denial_case_id": denial_id}, specialist_headers)
    validate_error(resp2, ApiErrorId.ERR_DENIAL_INVALID_STATE, expected_status=409)
    assert get_denial(denial_id)["status"] == "RESOLVED_PAID"


def test_auditor_cannot_record_outcome(api, auditor_headers, specialist_headers):
    """PRD §2.8: "**Authorization.** The authenticated role must appear in the endpoint's
    authorized role list, else `ERR_FORBIDDEN` (403). Applies to every endpoint."
    PRD §4: "| POST | `/rcm/appeals/{id}/record-outcome` | Record the payer's decision with
    recovered dollars | DenialsSpecialist |"

    Design: Corner/rbac/auditor_cannot_record_outcome
    """
    catalog = setup_catalog(levels=(1,))
    denial_id, appeal = setup_denial_with_submitted_appeal(
        catalog["payer"]["id"], catalog["code"]["id"], "CLM-2502",
    )
    resp = api.record_outcome(
        appeal["id"], {"outcome": "UPHELD", "recovered_amount_cents": 0}, auditor_headers,
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN, expected_status=403)
    after = validate_success(api.get_appeal(appeal["id"], specialist_headers))
    assert after["status"] == "SUBMITTED"


def test_writeoff_approve_against_resolved_paid_rejected(api):
    """PRD §3.6: "The denial must be in `QUEUED`, `IN_APPEAL`, `CLOSED_EXHAUSTED`, or
    `CLOSED_EXPIRED` — approving against a denial in any other status, including
    `RESOLVED_PAID`, fails with `ERR_DENIAL_INVALID_STATE`."

    Design: Difficulty/cross_entity_state_dependency/writeoff_approve_requires_workable_denial
    """
    catalog = setup_catalog(levels=(1,))
    denial_id, appeal = setup_denial_with_submitted_appeal(
        catalog["payer"]["id"], catalog["code"]["id"], "CLM-1501",
        denied_amount_cents=100000, billed_amount_cents=120000,
    )
    request = make_write_off(denial_id, 100000, requester_user_id="spec-1")
    record_outcome(appeal["id"], "OVERTURNED", 100000)
    assert get_denial(denial_id)["status"] == "RESOLVED_PAID"
    resp = api.approve_write_off(request["id"], manager_headers("mgr-1"))
    validate_error(resp, ApiErrorId.ERR_DENIAL_INVALID_STATE, expected_status=409)


def test_writeoff_approve_blocked_request_undecided(api):
    """PRD §3.6: "The denial must be in `QUEUED`, `IN_APPEAL`, `CLOSED_EXHAUSTED`, or
    `CLOSED_EXPIRED` — approving against a denial in any other status, including
    `RESOLVED_PAID`, fails with `ERR_DENIAL_INVALID_STATE`."
    PRD §3.4: "An `OVERTURNED` outcome adds the recovered amount to the denial's
    `recovered_amount_cents`; the open balance thereby reaches zero and, provided nothing has
    been written off, the denial resolves `IN_APPEAL` → `RESOLVED_PAID` with
    `next_appeal_deadline` cleared to null."

    Design: Difficulty/cross_entity_state_dependency/writeoff_approve_requires_workable_denial
    """
    catalog = setup_catalog(levels=(1,))
    denial_id, appeal = setup_denial_with_submitted_appeal(
        catalog["payer"]["id"], catalog["code"]["id"], "CLM-1501",
        denied_amount_cents=100000, billed_amount_cents=120000,
    )
    request = make_write_off(denial_id, 100000, requester_user_id="spec-1")
    record_outcome(appeal["id"], "OVERTURNED", 100000)
    validate_error(
        api.approve_write_off(request["id"], manager_headers("mgr-1")),
        ApiErrorId.ERR_DENIAL_INVALID_STATE,
    )
    after = validate_success(api.get_write_off_request(request["id"], manager_headers("mgr-1")))
    assert after["status"] == "PENDING_MANAGER", "no decision recorded while the gate fails"
    denial = get_denial(denial_id)
    assert denial["recovered_amount_cents"] == 100000
    assert denial["open_balance_cents"] == 0


def test_payer_review_flag_threshold_trigger(api, manager_headers):
    """PRD §3.1: "Once the resolved sample reaches at least 3 appeals, the flag is set to
    true when the rate is strictly below 0.30 and reset to false when the rate is 0.30 or
    higher — a rate of exactly 0.30 is not flagged. Below a sample of 3, the flag keeps
    whatever value it currently holds."

    Design: Corner/complexity_layers/payer_review_flag_threshold_trigger
    """
    catalog = setup_catalog(levels=(1,))
    appeal_ids = []
    for claim in ("CLM-2605", "CLM-2606", "CLM-2607"):
        denial_id, appeal = setup_denial_with_submitted_appeal(
            catalog["payer"]["id"], catalog["code"]["id"], claim,
            denied_amount_cents=100000, billed_amount_cents=120000,
        )
        appeal_ids.append(appeal["id"])
    record_outcome(appeal_ids[0], "UPHELD", 0)
    record_outcome(appeal_ids[1], "UPHELD", 0)
    payer = get_payer(catalog["payer"]["id"])
    assert payer["appeal_policy_review_required"] is False, (
        "sample of 2 stays below the minimum of 3"
    )
    record_outcome(appeal_ids[2], "UPHELD", 0)
    payer = get_payer(catalog["payer"]["id"])
    assert payer["appeal_policy_review_required"] is True, (
        "sample of 3 with rate 0.0 strictly below 0.30 flips the flag"
    )
