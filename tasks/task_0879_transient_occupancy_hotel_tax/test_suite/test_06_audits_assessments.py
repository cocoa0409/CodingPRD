"""Audits and assessments: STANDARD-vs-AUDIT tax recomputation, the issuance
delinquency cascade, cyclic reopen-fieldwork, four-eyes issuance, and the
guards on proposing, amending-under-assessment, and appeal submission."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    assert_assessment, assert_operator,
    TEST_USERS, make_operator_headers,
    single_line, setup_operator_with_property,
    create_draft_return, create_exemption, verify_exemption, file_return,
    open_audit, begin_fieldwork, propose_assessment, record_response,
    reopen_fieldwork, setup_proposed_assessment, setup_issued_assessment,
    create_active_operator, get_operator,
)

ADMIN = TEST_USERS["taxadmin_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


# ============================================================
# Difficulty: dual_variant_calc/tax_recompute_standard_vs_audit
# ============================================================
def _standard_vs_audit_setup(api):
    base = setup_operator_with_property(api)
    op, prop = base["operator"], base["property"]
    ret = create_draft_return(api, op["id"], single_line(prop["id"], 10000000))
    ex_gov = create_exemption(api, ret["id"], "GOVERNMENT", 2000000, guest_ref="G-1")
    verify_exemption(api, ex_gov["id"])
    create_exemption(api, ret["id"], "LONG_TERM_30DAY", 1000000, guest_ref="G-2", stay_nights=29)
    ret = file_return(api, ret["id"], op["id"])  # STANDARD honors both -> taxable 7M
    aud = open_audit(api, op["id"])
    begin_fieldwork(api, aud["id"])
    asmt = propose_assessment(api, aud["id"], 8000000, "NEGLIGENCE")
    return ret, asmt


def test_standard_self_report_honors_claimed_exemptions(api):
    """PRD 3.4: "the honored set is every exemption claim on the return that is
    `CLAIMED` or `VERIFIED` (that is, not `REJECTED`); this is the STANDARD variant,
    and it includes claimed-but-not-yet-verified exemptions, producing a lower
    taxable base and lower tax."

    Design: Difficulty/dual_variant_calc/tax_recompute_standard_vs_audit
    """
    ret, _ = _standard_vs_audit_setup(api)
    # (10,000,000 - 2,000,000 GOV - 1,000,000 CLAIMED LT) * 12% = 840,000.
    assert ret["tax_due_cents"] == 840000


def test_audit_variant_excludes_unverified_and_drives_deficiency(api):
    """PRD 3.8: "The `assessed_tax_cents` is the auditor's recomputed tax using the
    AUDIT variant of the tax computation: the honored exemption set is restricted to
    `VERIFIED` claims only (claimed-but-unverified exemptions are excluded)".
    PRD 3.8: "The `deficiency_cents` is the assessed tax minus the self-reported tax,
    floored at zero."

    Design: Difficulty/dual_variant_calc/tax_recompute_standard_vs_audit
    """
    _, asmt = _standard_vs_audit_setup(api)
    assert_assessment(asmt)
    assert asmt["assessed_tax_cents"] == 960000       # 8,000,000 * 12%
    assert asmt["self_reported_tax_cents"] == 840000
    assert asmt["deficiency_cents"] == 120000


# ============================================================
# Difficulty: transitive_cascade/assessment_issue_to_delinquent_cascade
# ============================================================
def test_issue_assessment_posts_total_and_moves_issued(api):
    """PRD 3.8: "On issuance both the audit and the assessment move to `ISSUED`, and
    the server posts an `ASSESSMENT` ledger entry for the positive
    `total_assessed_cents`, which cascades to the operator's balance".
    PRD 3.8: "The `total_assessed_cents` is the sum of `deficiency_cents`,
    `penalty_cents`, and `interest_cents`."

    Design: Difficulty/transitive_cascade/assessment_issue_to_delinquent_cascade
    """
    bundle = setup_issued_assessment(api, gross=1000000, audited_taxable_cents=6000000,
                                     classification="NEGLIGENCE", pay_full=True)
    asmt = bundle["assessment"]
    assert asmt["status"] == "ISSUED"
    # deficiency 600,000 + NEGLIGENCE penalty 60,000 + interest 0.
    assert asmt["total_assessed_cents"] == 660000


def test_issue_assessment_cascades_operator_to_delinquent(api):
    """PRD 2.7: "An `ACTIVE` operator whose balance becomes strictly greater than
    zero moves to `DELINQUENT`, but only when there is a concrete delinquency
    trigger: at least one `FILED` or `AMENDED` return that is past its `due_date` and
    not yet fully settled, or an `ISSUED` assessment."

    Design: Difficulty/transitive_cascade/assessment_issue_to_delinquent_cascade
    """
    bundle = setup_issued_assessment(api, gross=1000000, audited_taxable_cents=6000000,
                                     classification="NEGLIGENCE", pay_full=True)
    op = get_operator(api, bundle["operator"]["id"])
    assert_operator(op)
    assert op["account_balance_cents"] == 660000
    assert op["status"] == "DELINQUENT"


# ============================================================
# Difficulty: non_linear_state_machine/audit_cyclic_reopen_fieldwork
# ============================================================
def _audit_at_response(api):
    bundle = setup_proposed_assessment(api, gross=1000000, audited_taxable_cents=2000000)
    record_response(api, bundle["audit"]["id"])
    return bundle


def test_reopen_fieldwork_returns_audit_to_fieldwork(api):
    """PRD 3.8: "From `RESPONSE` the auditor may reopen fieldwork, returning the audit
    to `FIELDWORK` for another proposal round; this is the cyclic negotiation path,
    and it abandons the still-`PROPOSED` assessment by driving it to `ABATED`".

    Design: Difficulty/non_linear_state_machine/audit_cyclic_reopen_fieldwork
    """
    bundle = _audit_at_response(api)
    reopen_fieldwork(api, bundle["audit"]["id"])
    aud = validate_success(api.get_audit(bundle["audit"]["id"], ADMIN), 200)
    assert aud["status"] == "FIELDWORK"


def test_reopen_fieldwork_abates_proposed_assessment(api):
    """PRD 3.8: "it abandons the still-`PROPOSED` assessment by driving it to
    `ABATED` (a terminal state with no ledger impact, because that assessment was
    never issued)."

    Design: Difficulty/non_linear_state_machine/audit_cyclic_reopen_fieldwork
    """
    bundle = _audit_at_response(api)
    reopen_fieldwork(api, bundle["audit"]["id"])
    asmt = validate_success(api.get_assessment(bundle["assessment"]["id"], ADMIN), 200)
    assert asmt["status"] == "ABATED"


# ============================================================
# Difficulty: cross_entity_state_dependency/appeal_submit_requires_assessment_issued
# ============================================================
def test_appeal_on_proposed_assessment_rejected(api):
    """PRD 3.9: "appeal submission is permitted only while the assessment is
    `ISSUED`, else `ERR_INVALID_STATE`."

    Design: Difficulty/cross_entity_state_dependency/appeal_submit_requires_assessment_issued
    """
    bundle = setup_proposed_assessment(api, gross=1000000, audited_taxable_cents=2000000)
    op = bundle["operator"]
    resp = api.submit_appeal(bundle["assessment"]["id"], {"grounds": "disagree"},
                             make_operator_headers(op["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_appeal_on_proposed_leaves_assessment_proposed(api):
    """PRD 3.9: "Submitting an appeal moves the assessment from `ISSUED` to
    `APPEALED` and creates the appeal in `SUBMITTED`".

    Design: Difficulty/cross_entity_state_dependency/appeal_submit_requires_assessment_issued
    """
    bundle = setup_proposed_assessment(api, gross=1000000, audited_taxable_cents=2000000)
    op = bundle["operator"]
    api.submit_appeal(bundle["assessment"]["id"], {"grounds": "disagree"}, make_operator_headers(op["id"]))
    asmt = validate_success(api.get_assessment(bundle["assessment"]["id"], ADMIN), 200)
    assert asmt["status"] == "PROPOSED"


# ---- Corner: state_machines/amend_return_under_issued_assessment_rejected ----
def test_amend_under_issued_assessment_rejected(api):
    """PRD 3.4: "Amendment is blocked when the return is covered by an assessment that
    has been issued or made final — that is, an `ISSUED` or `FINAL` assessment — in
    which case it is rejected with `ERR_RETURN_UNDER_ASSESSMENT`."

    Design: Corner/state_machines/amend_return_under_issued_assessment_rejected
    """
    bundle = setup_issued_assessment(api, gross=1000000, audited_taxable_cents=2000000, pay_full=True)
    op, ret, prop = bundle["operator"], bundle["return"], bundle["property"]
    resp = api.amend_return(ret["id"], make_operator_headers(op["id"]),
                            {"line_items": single_line(prop["id"], 900000)})
    validate_error(resp, ApiErrorId.ERR_RETURN_UNDER_ASSESSMENT.value)
    assert validate_success(api.get_return(ret["id"], ADMIN), 200)["filing_status"] == "FILED"


# ---- Corner: validations/propose_assessment_no_returns_in_period ----
def test_propose_assessment_with_no_returns_rejected(api):
    """PRD 3.8: "Proposing requires that at least one `FILED` or `AMENDED` return
    falls within the audit period, otherwise it is rejected with
    `ERR_NO_RETURNS_IN_PERIOD`."

    Design: Corner/validations/propose_assessment_no_returns_in_period
    """
    op = create_active_operator(api)
    aud = open_audit(api, op["id"])
    begin_fieldwork(api, aud["id"])
    resp = api.propose_assessment(aud["id"], {"audited_taxable_cents": 500000, "classification": "NEGLIGENCE"}, AUDITOR)
    validate_error(resp, ApiErrorId.ERR_NO_RETURNS_IN_PERIOD.value)
    assert validate_success(api.get_audit(aud["id"], ADMIN), 200)["status"] == "FIELDWORK"


# ---- Corner: rbac/auditor_cannot_issue_assessment_forbidden ----
def test_auditor_cannot_issue_assessment(api):
    """PRD 2.1: "An auditor may never issue an assessment — issuance is reserved to
    `TaxAdmin` (see the four-eyes rule in Section 3.8)."

    Design: Corner/rbac/auditor_cannot_issue_assessment_forbidden
    """
    bundle = setup_proposed_assessment(api, gross=1000000, audited_taxable_cents=2000000)
    resp = api.issue_assessment(bundle["assessment"]["id"], AUDITOR)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)
    assert validate_success(api.get_assessment(bundle["assessment"]["id"], ADMIN), 200)["status"] == "PROPOSED"
