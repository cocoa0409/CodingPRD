"""Complaint investigation cycle, risk scoring, segregation, and bond settlement.

Covers the risk-score dual-variant, the complaint review cycle, the
settle->exhaust->suspend->terminate cascade, the bond-face-value conservation
invariant, and the complaint/settlement validation corners.
"""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    assert_bond_ledger_invariant,
    make_notary_headers,
    make_commission_authority_headers,
    create_complaint_payload,
    TEST_USERS,
)
import test_helpers as th

CA = TEST_USERS["commission_authority_headers"]


# ===========================================================================
# dual_variant_calc: notary risk provisional vs final score
# ===========================================================================
def test_risk_score_provisional_at_substantiate(api):
    """PRD §3.8: "Substantiating a complaint moves it from `UNDER_REVIEW` to
    `SUBSTANTIATED` ... and recomputes the subject notary's `risk_score`. The risk
    score is a weighted tally over all of that notary's complaints whose status is
    `SUBSTANTIATED` or `SETTLED` ... a `FEE_OVERCHARGE` complaint adds 20"

    Design: Difficulty/dual_variant_calc/notary_risk_provisional_vs_final_score
    """
    notary = th.setup_active_notary(notary_overrides={"email": "nrisk@x.com"})["notary"]
    cmp = th.file_and_substantiate_complaint(notary["id"], "FEE_OVERCHARGE", claim_amount_cents=100000, operator_id="auditor-7")
    assert cmp["status"] == "SUBSTANTIATED"
    refreshed = validate_success(api.get_notary(notary["id"], CA))
    assert refreshed["risk_score"] == 20


def test_risk_score_unchanged_after_settle(api):
    """PRD §3.8: "The risk score is a weighted tally over all of that notary's
    complaints whose status is `SUBSTANTIATED` or `SETTLED`, taken in `created_at`
    ascending order ... a `FEE_OVERCHARGE` complaint adds 20"
    PRD §3.8: "On settlement the server draws against the bond: the draw is the
    smaller of the complaint's `claim_amount_cents` and the bond's current
    `remaining_cents`. That draw amount is recorded as the complaint's
    `settled_claim_cents`"

    Design: Difficulty/dual_variant_calc/notary_risk_provisional_vs_final_score
    """
    notary = th.setup_active_notary(notary_overrides={"email": "nrisk2@x.com"})["notary"]
    hdr_op = make_commission_authority_headers("auditor-7b")
    cmp = th.file_and_substantiate_complaint(notary["id"], "FEE_OVERCHARGE", claim_amount_cents=100000, operator_id="auditor-7b")
    settled = validate_success(api.settle(cmp["id"], hdr_op))
    assert settled["status"] == "SETTLED"
    assert settled["settled_claim_cents"] == 100000
    refreshed = validate_success(api.get_notary(notary["id"], CA))
    assert refreshed["risk_score"] == 20  # remains 20: complaint still in SUBSTANTIATED/SETTLED set


# ===========================================================================
# non_linear_state_machine: complaint review/info-request cycle
# ===========================================================================
def test_complaint_resume_review_returns_to_under_review(api):
    """PRD §3.8: "From `UNDER_REVIEW`, the office may request additional
    information, moving the complaint to `INFO_REQUESTED` (the complaint must be
    `UNDER_REVIEW`, else `ERR_INVALID_STATE`). From `INFO_REQUESTED`, resuming
    review returns it to `UNDER_REVIEW` (the complaint must be `INFO_REQUESTED`,
    else `ERR_INVALID_STATE`) and writes an audit record"

    Design: Difficulty/non_linear_state_machine/complaint_review_info_request_cycle
    """
    notary = th.setup_active_notary(notary_overrides={"email": "ncyc@x.com"})["notary"]
    op = make_commission_authority_headers("auditor-1")
    cmp = th.file_and_open_complaint(notary["id"], "RECORDKEEPING", operator_id="auditor-1")
    validate_success(api.request_info(cmp["id"], op))
    resumed = validate_success(api.resume_review(cmp["id"], op))
    assert resumed["status"] == "UNDER_REVIEW"


def test_complaint_request_info_moves_to_info_requested(api):
    """PRD §3.8: "From `UNDER_REVIEW`, the office may request additional
    information, moving the complaint to `INFO_REQUESTED` (the complaint must be
    `UNDER_REVIEW`, else `ERR_INVALID_STATE`)."

    Design: Difficulty/non_linear_state_machine/complaint_review_info_request_cycle
    """
    notary = th.setup_active_notary(notary_overrides={"email": "ncyc2@x.com"})["notary"]
    op = make_commission_authority_headers("auditor-1b")
    cmp = th.file_and_open_complaint(notary["id"], "RECORDKEEPING", operator_id="auditor-1b")
    data = validate_success(api.request_info(cmp["id"], op))
    assert data["status"] == "INFO_REQUESTED"


# ===========================================================================
# Corner: risk-score accumulation below / crossing threshold
# ===========================================================================
def test_two_substantiations_below_threshold_keep_notary_active(api):
    """PRD §3.8: "a `FEE_OVERCHARGE` complaint adds 20, a `RECORDKEEPING` complaint
    adds 15 ... If, after this recomputation, the notary's `risk_score` is at least
    50 and the notary is currently `ACTIVE`, the system suspends the notary
    automatically as a cascade of substantiation."

    Design: Corner/calculations/risk_score_two_substantiated_below_threshold_no_auto_suspend
    """
    notary = th.setup_active_notary(notary_overrides={"email": "risk2@x.com"})["notary"]
    th.raise_risk_with_substantiations(notary["id"], ["FEE_OVERCHARGE", "RECORDKEEPING"], operator_id="auditor-3")
    refreshed = validate_success(api.get_notary(notary["id"], CA))
    assert refreshed["risk_score"] == 35  # 20 + 15
    assert refreshed["status"] == "ACTIVE"


def test_substantiation_crossing_threshold_auto_suspends(api):
    """PRD §3.8: "a `FRAUD` complaint adds 40 ... If, after this recomputation, the
    notary's `risk_score` is at least 50 and the notary is currently `ACTIVE`, the
    system suspends the notary automatically as a cascade of substantiation."

    Design: Corner/calculations/risk_score_crossing_threshold_auto_suspends_notary
    """
    notary = th.setup_active_notary(notary_overrides={"email": "risk3@x.com"})["notary"]
    th.raise_risk_with_substantiations(
        notary["id"], ["FEE_OVERCHARGE", "RECORDKEEPING", "FRAUD"], operator_id="auditor-4"
    )
    refreshed = validate_success(api.get_notary(notary["id"], CA))
    assert refreshed["risk_score"] == 75  # 20 + 15 + 40
    assert refreshed["status"] == "SUSPENDED"


# ===========================================================================
# Corner: segregation of duties on open-review
# ===========================================================================
def test_open_review_by_subject_notary_returns_segregation_violation(api):
    """PRD §3.8: "Opening review advances a complaint from `FILED` to
    `UNDER_REVIEW` and is the system's segregation-of-duties checkpoint. ... it
    requires that the operator opening review is not the subject notary ... A
    notary attempting to adjudicate a complaint against itself is rejected with
    `ERR_SEGREGATION_VIOLATION`."

    Design: Corner/validations/open_review_by_subject_notary_returns_segregation_violation
    """
    notary = th.setup_active_notary(notary_overrides={"email": "seg@x.com"})["notary"]
    # file the complaint with X-User-ID equal to the subject notary's id
    op_self = make_commission_authority_headers(notary["id"])
    cmp = validate_success(
        api.create_complaint(create_complaint_payload(notary["id"], "OTHER"), op_self), 201
    )
    resp = api.open_review(cmp["id"], op_self)
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_VIOLATION.value, expected_status=403)
    refreshed = validate_success(api.get_complaint(cmp["id"], CA))
    assert refreshed["status"] == "FILED"


# ===========================================================================
# Corner: settlement validations
# ===========================================================================
def test_settle_when_bond_not_active_returns_bond_not_active(api):
    """PRD §3.8: "Settlement ... requires the complaint to be `SUBSTANTIATED` (else
    `ERR_INVALID_STATE`), the subject notary's bond to be `ACTIVE` (else
    `ERR_BOND_NOT_ACTIVE`)"

    Design: Corner/validations/settle_when_bond_not_active_returns_bond_not_active
    """
    # APPLIED notary whose only bond is still PENDING; complaint can still reach SUBSTANTIATED
    ctx = th.setup_applied_notary_with_pending_bond(notary_overrides={"email": "pend@x.com"})
    notary = ctx["notary"]
    op = make_commission_authority_headers("auditor-5")
    cmp = th.file_and_substantiate_complaint(notary["id"], "FRAUD", claim_amount_cents=100000, operator_id="auditor-5")
    resp = api.settle(cmp["id"], op)
    validate_error(resp, ApiErrorId.ERR_BOND_NOT_ACTIVE.value, expected_status=409)
    refreshed = validate_success(api.get_complaint(cmp["id"], CA))
    assert refreshed["status"] == "SUBSTANTIATED"


def test_settle_with_zero_claim_returns_no_claim_amount(api):
    """PRD §3.8: "a positive claim — a complaint whose `claim_amount_cents` is 0
    cannot be settled and is rejected with `ERR_NO_CLAIM_AMOUNT`."

    Design: Corner/validations/settle_with_zero_claim_returns_no_claim_amount
    """
    notary = th.setup_active_notary(notary_overrides={"email": "zero@x.com"})["notary"]
    op = make_commission_authority_headers("auditor-6")
    # claim_amount_cents omitted -> defaults 0
    cmp = th.file_and_substantiate_complaint(notary["id"], "FRAUD", operator_id="auditor-6")
    resp = api.settle(cmp["id"], op)
    validate_error(resp, ApiErrorId.ERR_NO_CLAIM_AMOUNT.value, expected_status=409)
    refreshed = validate_success(api.get_complaint(cmp["id"], CA))
    assert refreshed["status"] == "SUBSTANTIATED"


def test_reinstate_while_risk_at_threshold_returns_risk_threshold_block(api):
    """PRD §3.9: "Reinstatement requires the notary to be `SUSPENDED` (else
    `ERR_INVALID_STATE`), requires the `risk_score` to be below the suspension
    threshold of 50 — a notary still at or above that threshold cannot be
    reinstated and is rejected with `ERR_RISK_THRESHOLD_BLOCK`"

    Design: Corner/validations/reinstate_while_risk_at_threshold_returns_risk_threshold_block
    """
    notary = th.setup_active_notary(notary_overrides={"email": "rein@x.com"})["notary"]
    # two FRAUD substantiations -> risk 80, auto-suspended
    th.raise_risk_with_substantiations(notary["id"], ["FRAUD", "FRAUD"], operator_id="auditor-8")
    suspended = validate_success(api.get_notary(notary["id"], CA))
    assert suspended["risk_score"] == 80
    assert suspended["status"] == "SUSPENDED"
    resp = api.reinstate_notary(notary["id"], CA)
    validate_error(resp, ApiErrorId.ERR_RISK_THRESHOLD_BLOCK.value, expected_status=409)


# ===========================================================================
# compensating_invariant: bond settlement conserves face value
# ===========================================================================
def test_bond_settlement_partial_draw_conserves_face_value(api):
    """PRD §3.8: "On settlement the server draws against the bond: the draw is the
    smaller of the complaint's `claim_amount_cents` and the bond's current
    `remaining_cents`. That draw amount is recorded as the complaint's
    `settled_claim_cents`; it is added to the bond's `claims_paid_cents` and
    subtracted from the bond's `remaining_cents`, preserving the invariant that
    face value always equals claims paid plus remaining."

    Design: Difficulty/compensating_invariant/bond_settlement_conserves_face_value
    """
    ctx = th.setup_active_notary(notary_overrides={"email": "nci2@x.com"})
    notary, bond = ctx["notary"], ctx["bond"]
    op = make_commission_authority_headers("auditor-2")
    cmp = th.file_and_substantiate_complaint(notary["id"], "FEE_OVERCHARGE", claim_amount_cents=250000, operator_id="auditor-2")
    validate_success(api.settle(cmp["id"], op))
    refreshed = validate_success(api.get_bond(bond["id"], CA))
    assert refreshed["claims_paid_cents"] == 250000
    assert refreshed["remaining_cents"] == 750000
    assert refreshed["face_value_cents"] == 1000000
    assert refreshed["status"] == "ACTIVE"
    assert_bond_ledger_invariant(refreshed)


def test_bond_ledger_invariant_holds_before_settlement(api):
    """PRD §3.3: "Its `remaining_cents` is always its `face_value_cents` less its
    `claims_paid_cents`, and the invariant that face value equals claims paid plus
    remaining holds before and after every settlement."
    PRD §3.2: "On a successful activation the server sets `remaining_cents` equal to
    `face_value_cents` and `claims_paid_cents` to 0."

    Design: Difficulty/compensating_invariant/bond_settlement_conserves_face_value
    """
    ctx = th.setup_active_notary(notary_overrides={"email": "nci2b@x.com"})
    bond = validate_success(api.get_bond(ctx["bond"]["id"], CA))
    assert bond["claims_paid_cents"] == 0
    assert bond["remaining_cents"] == bond["face_value_cents"] == 1000000
    assert_bond_ledger_invariant(bond)


# ===========================================================================
# transitive_cascade: settle -> exhaust -> suspend -> terminate session
# ===========================================================================
def test_settle_exhausts_bond_suspends_notary_terminates_session(api):
    """PRD §3.8: "Should the draw bring the bond's `remaining_cents` to exactly 0,
    the bond transitions to `EXHAUSTED`, and that exhaustion in turn suspends the
    subject notary if the notary is currently `ACTIVE` — a three-deep cascade from
    settlement, to bond exhaustion, to notary suspension."
    PRD §3.9: "every session of that notary in `SCHEDULED`, `IDENTITY_PENDING`,
    `ID_VERIFIED`, or `ACTIVE` status is cascaded to `TERMINATED`, and each such
    session's `PENDING` documents are cascaded to `REFUSED`."

    Design: Difficulty/transitive_cascade/settle_exhausts_bond_suspends_notary_terminates_session
    """
    ctx = th.setup_active_notary(notary_overrides={"enotary_requested": True, "email": "ncasc@x.com"})
    notary, bond = ctx["notary"], ctx["bond"]
    hdr = make_notary_headers(notary["id"])
    # start an ACTIVE session with one PENDING document (not yet notarized)
    built = th.setup_session_to_active(
        notary["id"], "2026-06-14T09:00:00Z", "2026-06-14T10:00:00Z",
        documents=[("OATH", 500)],
    )
    sess = built["session"]
    doc = built["documents"][0]
    # substantiate a FRAUD complaint claiming the full bond face value, then settle
    op = make_commission_authority_headers("auditor-9")
    cmp = th.file_and_substantiate_complaint(notary["id"], "FRAUD", claim_amount_cents=1000000, operator_id="auditor-9")
    validate_success(api.settle(cmp["id"], op))

    refreshed_bond = validate_success(api.get_bond(bond["id"], CA))
    assert refreshed_bond["remaining_cents"] == 0
    assert refreshed_bond["claims_paid_cents"] == 1000000
    assert refreshed_bond["status"] == "EXHAUSTED"
    refreshed_notary = validate_success(api.get_notary(notary["id"], CA))
    assert refreshed_notary["status"] == "SUSPENDED"
    refreshed_sess = validate_success(api.get_session(sess["id"], CA))
    assert refreshed_sess["status"] == "TERMINATED"
    refreshed_doc = validate_success(api.get_document(doc["id"], CA))
    assert refreshed_doc["status"] == "REFUSED"


def test_settle_full_draw_exhausts_bond(api):
    """PRD §3.8: "Should the draw bring the bond's `remaining_cents` to exactly 0,
    the bond transitions to `EXHAUSTED`"
    PRD §3.8: "it is added to the bond's `claims_paid_cents` and subtracted from
    the bond's `remaining_cents`, preserving the invariant that face value always
    equals claims paid plus remaining."

    Design: Difficulty/transitive_cascade/settle_exhausts_bond_suspends_notary_terminates_session
    """
    ctx = th.setup_active_notary(notary_overrides={"email": "ncasc2@x.com"})
    notary, bond = ctx["notary"], ctx["bond"]
    op = make_commission_authority_headers("auditor-9b")
    cmp = th.file_and_substantiate_complaint(notary["id"], "FRAUD", claim_amount_cents=1000000, operator_id="auditor-9b")
    validate_success(api.settle(cmp["id"], op))
    refreshed_bond = validate_success(api.get_bond(bond["id"], CA))
    assert refreshed_bond["status"] == "EXHAUSTED"
    assert refreshed_bond["remaining_cents"] == 0
    assert_bond_ledger_invariant(refreshed_bond)
