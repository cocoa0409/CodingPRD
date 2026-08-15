"""Composite setup helpers.

Every helper builds preconditions from scratch using only PRD-declared
endpoints (each test runs against a freshly restarted server with an empty
database, and the logical clock starts at exactly 2026-08-01T00:00:00Z per
PRD section 2.5). Setup calls use get_success_data so failures surface as
clear "Setup failed" errors.

Identity threading: Contributor is entity-backed, so every ownership-gated
call passes make_contributor_headers(contributor["id"]). Segregation-of-
duties duties use distinct operator ids (fin-1 verifies/locks, fin-2
approves/releases, ve-recorder records, ve-adjudicator adjudicates).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    DEFAULT_DEADLINE,
    DEFAULT_START_CLOCK,
    FIN_USER_1,
    FIN_USER_2,
    VE_RECORDER,
)
from .factories import (
    accept_for_publication_payload,
    add_invoice_payload,
    adjudicate_payload,
    create_assignment_payload,
    create_contributor_payload,
    create_expense_claim_payload,
    create_invoice_payload,
    create_payment_batch_payload,
    create_rate_agreement_payload,
    create_tax_document_payload,
    expense_decision_payload,
    invoice_decision_payload,
    record_result_payload,
    release_batch_payload,
    set_clock_payload,
    settle_decision_payload,
    submit_expense_payload,
    tax_doc_decision_payload,
)
from .test_users import (
    TEST_USERS,
    make_contributor_headers,
    make_finance_headers,
    make_verification_editor_headers,
)

ADMIN = TEST_USERS["desk_admin_headers"]
EDITOR = TEST_USERS["editor_headers"]
VE_READ = TEST_USERS["verification_editor_headers"]


def _fail(step, resp):
    raise AssertionError(
        f"Setup failed at {step}: HTTP {resp.status_code} {resp.text}"
    )


def _ok(step, resp):
    try:
        return get_success_data(resp)
    except AssertionError:
        _fail(step, resp)


# ---------------------------------------------------------------------------
# Tier 0 — bootstrap and logical clock
# ---------------------------------------------------------------------------

def bootstrap_desk(overrides=None):
    """One-time DeskConfig bootstrap with documented defaults (PRD 3.10)."""
    resp = api_client.bootstrap_desk_config(overrides or {}, ADMIN)
    return _ok("bootstrap_desk_config", resp)


def set_clock(to_iso8601):
    resp = api_client.set_clock(set_clock_payload(to_iso8601), ADMIN)
    return _ok("set_clock", resp)


# ---------------------------------------------------------------------------
# Tier 1 — contributors, agreements, tax documents
# ---------------------------------------------------------------------------

def create_contributor(legal_name="Test Contributor", email=None,
                       tax_residency="DOMESTIC_US",
                       backup_withholding_flag=None):
    email = email or f"{legal_name.lower().replace(' ', '.')}@example.com"
    payload = create_contributor_payload(
        legal_name=legal_name, email=email, tax_residency=tax_residency)
    if backup_withholding_flag is not None:
        payload["backup_withholding_flag"] = backup_withholding_flag
    resp = api_client.create_contributor(payload, ADMIN)
    return _ok("create_contributor", resp)


def get_contributor(contributor_id):
    return _ok("get_contributor",
               api_client.get_contributor(contributor_id, ADMIN))


def add_rate_agreement(contributor, pricing_mode="FLAT",
                       per_word_rate_cents=None, flat_fee_cents=50000,
                       kill_fee_pct_num=25, rights_default="FIRST",
                       effective_from=DEFAULT_START_CLOCK, effective_to=None):
    """Create a RateAgreement for a contributor. The OCC guard carries the
    contributor version the caller last observed (PRD 2.4); pass a fresh
    contributor row (or re-read via get_contributor) after any mutation."""
    payload = create_rate_agreement_payload(
        pricing_mode=pricing_mode,
        kill_fee_pct_num=kill_fee_pct_num,
        rights_default=rights_default,
        effective_from=effective_from,
        expected_contributor_version=contributor["version"],
    )
    if pricing_mode == "PER_WORD":
        payload["per_word_rate_cents"] = (
            per_word_rate_cents if per_word_rate_cents is not None else 75)
        payload.pop("flat_fee_cents", None)
    else:
        payload["flat_fee_cents"] = flat_fee_cents
        payload.pop("per_word_rate_cents", None)
    if effective_to is not None:
        payload["effective_to"] = effective_to
    resp = api_client.create_rate_agreement(contributor["id"], payload, ADMIN)
    return _ok("create_rate_agreement", resp)


def submit_tax_document(contributor_id, doc_kind="W9", treaty_country=None,
                        tin_last4="1234"):
    payload = create_tax_document_payload(doc_kind=doc_kind,
                                          tin_last4=tin_last4)
    if treaty_country is not None:
        payload["treaty_country"] = treaty_country
    resp = api_client.create_tax_document(
        contributor_id, payload, make_contributor_headers(contributor_id))
    return _ok("create_tax_document", resp)


def verify_tax_document(document_id, decision="VERIFY", user_id=FIN_USER_1):
    resp = api_client.verify_tax_document(
        document_id, tax_doc_decision_payload(decision),
        make_finance_headers(user_id))
    return _ok("verify_tax_document", resp)


def create_verified_tax_document(contributor_id, doc_kind="W9",
                                 treaty_country=None, tin_last4="1234"):
    doc = submit_tax_document(contributor_id, doc_kind=doc_kind,
                              treaty_country=treaty_country,
                              tin_last4=tin_last4)
    return verify_tax_document(doc["id"], "VERIFY")


# ---------------------------------------------------------------------------
# Tier 1 — assignments and the editorial pipeline
# ---------------------------------------------------------------------------

def create_assignment(contributor_id, title="Test Story", brief="b",
                      commissioned_word_count=100,
                      deadline_utc=DEFAULT_DEADLINE):
    resp = api_client.create_assignment(
        create_assignment_payload(
            contributor_id=contributor_id, title=title, brief=brief,
            commissioned_word_count=commissioned_word_count,
            deadline_utc=deadline_utc),
        EDITOR)
    return _ok("create_assignment", resp)


def get_assignment(assignment_id):
    return _ok("get_assignment",
               api_client.get_assignment(assignment_id, EDITOR))


def offer_assignment(assignment_id):
    return _ok("offer_assignment",
               api_client.offer_assignment(assignment_id, EDITOR))


def accept_assignment(assignment_id, contributor_id):
    return _ok("accept_assignment",
               api_client.accept_assignment(
                   assignment_id, make_contributor_headers(contributor_id)))


def start_assignment(assignment_id, contributor_id):
    return _ok("start_assignment",
               api_client.start_assignment(
                   assignment_id, make_contributor_headers(contributor_id)))


def submit_assignment(assignment_id, contributor_id):
    return _ok("submit_assignment",
               api_client.submit_assignment(
                   assignment_id, make_contributor_headers(contributor_id)))


def kill_assignment(assignment_id):
    return _ok("kill_assignment",
               api_client.kill_assignment(assignment_id, EDITOR))


def walk_assignment(assignment_id, contributor_id, target):
    """Walk the editorial pipeline to the named state.
    target in {OFFERED, ACCEPTED, IN_PROGRESS, SUBMITTED, UNDER_VERIFICATION}.
    Idempotent: reads the assignment's current editorial status and applies
    only the remaining transitions, so it is safe to call on a partially
    advanced assignment. Returns the assignment dict at the target state."""
    order = {"DRAFT": 0, "OFFERED": 1, "ACCEPTED": 2, "IN_PROGRESS": 3,
             "SUBMITTED": 4, "UNDER_VERIFICATION": 4}
    if target not in order:
        raise ValueError(f"unsupported walk target {target}")
    tgt = order[target]
    data = get_assignment(assignment_id)
    cur = order.get(data["editorial_status"], -1)
    if cur < 0 or cur > tgt:
        raise ValueError(
            f"cannot walk from {data['editorial_status']} to {target}")
    if cur < 1 <= tgt:
        data = offer_assignment(assignment_id)
    if cur < 2 <= tgt:
        data = accept_assignment(assignment_id, contributor_id)
    if cur < 3 <= tgt:
        data = start_assignment(assignment_id, contributor_id)
    if cur < 4 <= tgt:
        data = submit_assignment(assignment_id, contributor_id)
    return data


# ---------------------------------------------------------------------------
# Tier 1 — verification reports
# ---------------------------------------------------------------------------

def list_reports(assignment_id):
    return _ok("list_verification_reports",
               api_client.list_verification_reports(assignment_id, VE_READ))


def record_result(report_id, similarity_score_bps=100, ai_probability_bps=100,
                  user_id=VE_RECORDER):
    return _ok("record_verification_result",
               api_client.record_verification_result(
                   report_id,
                   record_result_payload(similarity_score_bps,
                                         ai_probability_bps),
                   make_verification_editor_headers(user_id)))


def clear_all_reports(assignment_id, user_id=VE_RECORDER,
                      similarity_score_bps=100, ai_probability_bps=100):
    """Record below-threshold results on both auto-created reports so each
    lands CLEARED (PRD 3.5). Returns the report list (PLAGIARISM first)."""
    reports = list_reports(assignment_id)
    assert len(reports) == 2, "submission must auto-create two reports"
    assert reports[0]["checker_kind"] == "PLAGIARISM"
    assert reports[1]["checker_kind"] == "AI_CONTENT"
    for rep in reports:
        record_result(rep["id"], similarity_score_bps, ai_probability_bps,
                      user_id=user_id)
    return reports


def adjudicate_report(report_id, outcome, note="adjudicated",
                      user_id="ve-adjudicator"):
    return _ok("adjudicate_verification_report",
               api_client.adjudicate_verification_report(
                   report_id, adjudicate_payload(outcome, note),
                   make_verification_editor_headers(user_id)))


def accept_for_publication(assignment_id, final_word_count=100):
    return _ok("accept_for_publication",
               api_client.accept_for_publication(
                   assignment_id,
                   accept_for_publication_payload(final_word_count),
                   EDITOR))


# ---------------------------------------------------------------------------
# Tier 1 — expense claims
# ---------------------------------------------------------------------------

def create_expense_claim(assignment_id, contributor_id, category="TRAVEL",
                         requested_cents=1000):
    resp = api_client.create_expense_claim(
        assignment_id,
        create_expense_claim_payload(category=category,
                                     requested_cents=requested_cents),
        make_contributor_headers(contributor_id))
    return _ok("create_expense_claim", resp)


def decide_expense(claim_id, decision="APPROVE"):
    return _ok("decide_expense_claim",
               api_client.decide_expense_claim(
                   claim_id, expense_decision_payload(decision), EDITOR))


def submit_expense(claim_id, contributor_id, claimed_cents,
                   receipt_attached=False):
    return _ok("submit_expense_claim",
               api_client.submit_expense_claim(
                   claim_id,
                   submit_expense_payload(claimed_cents, receipt_attached),
                   make_contributor_headers(contributor_id)))


def settle_expense(claim_id, decision="REIMBURSE"):
    return _ok("settle_expense_claim",
               api_client.settle_expense_claim(
                   claim_id, settle_decision_payload(decision), EDITOR))


def get_expense_claim(claim_id):
    return _ok("get_expense_claim",
               api_client.get_expense_claim(claim_id, EDITOR))


# ---------------------------------------------------------------------------
# Tier 1 — rights purchases
# ---------------------------------------------------------------------------

def get_rights_purchase_for_assignment(assignment_id):
    rows = _ok("list_rights_purchases",
               api_client.list_rights_purchases(assignment_id, EDITOR))
    assert len(rows) == 1, "offer must create exactly one RightsPurchase"
    return rows[0]


# ---------------------------------------------------------------------------
# Tier 2 — invoicing pipeline
# ---------------------------------------------------------------------------

def submit_invoice(assignment_id, contributor_id, fee_claim_cents,
                   expense_claim_cents=0):
    resp = api_client.create_invoice(
        assignment_id,
        create_invoice_payload(fee_claim_cents, expense_claim_cents),
        make_contributor_headers(contributor_id))
    return _ok("create_invoice", resp)


def verify_invoice(invoice_id, decision="VERIFY", user_id=FIN_USER_1):
    return _ok("verify_invoice",
               api_client.verify_invoice(
                   invoice_id, invoice_decision_payload(decision),
                   make_finance_headers(user_id)))


def approve_invoice(invoice_id, user_id=FIN_USER_2):
    return _ok("approve_invoice",
               api_client.approve_invoice(invoice_id,
                                          make_finance_headers(user_id)))


def get_invoice(invoice_id):
    return _ok("get_invoice", api_client.get_invoice(invoice_id,
                                                     make_finance_headers(
                                                         FIN_USER_1)))


# ---------------------------------------------------------------------------
# Tier 2 — payment batches
# ---------------------------------------------------------------------------

def create_batch(scheduled_pay_date="2026-08-20T00:00:00Z"):
    return _ok("create_payment_batch",
               api_client.create_payment_batch(
                   create_payment_batch_payload(scheduled_pay_date),
                   make_finance_headers(FIN_USER_1)))


def add_invoice_to_batch(batch_id, invoice_id, user_id=FIN_USER_1):
    return _ok("add_invoice_to_batch",
               api_client.add_invoice_to_batch(
                   batch_id, add_invoice_payload(invoice_id),
                   make_finance_headers(user_id)))


def lock_batch(batch_id, user_id=FIN_USER_1):
    return _ok("lock_batch",
               api_client.lock_batch(batch_id, make_finance_headers(user_id)))


def release_batch(batch_id, expected_batch_version, user_id=FIN_USER_2):
    return _ok("release_batch",
               api_client.release_batch(
                   batch_id, release_batch_payload(expected_batch_version),
                   make_finance_headers(user_id)))


def get_batch(batch_id):
    return _ok("get_payment_batch",
               api_client.get_payment_batch(batch_id,
                                            make_finance_headers(FIN_USER_1)))


# ---------------------------------------------------------------------------
# Tier 3 — full lifecycle shortcuts
# ---------------------------------------------------------------------------

def setup_contributor_with_agreement(legal_name="Writer One", email=None,
                                     tax_residency="DOMESTIC_US",
                                     backup_withholding_flag=None,
                                     pricing_mode="FLAT",
                                     per_word_rate_cents=None,
                                     flat_fee_cents=50000,
                                     kill_fee_pct_num=25,
                                     rights_default="FIRST",
                                     effective_from=DEFAULT_START_CLOCK,
                                     effective_to=None,
                                     bootstrap=True):
    """Bootstrapped desk + contributor + one ACTIVE rate agreement.
    Returns (contributor, agreement)."""
    if bootstrap:
        bootstrap_desk()
    contributor = create_contributor(
        legal_name=legal_name, email=email, tax_residency=tax_residency,
        backup_withholding_flag=backup_withholding_flag)
    agreement = add_rate_agreement(
        contributor, pricing_mode=pricing_mode,
        per_word_rate_cents=per_word_rate_cents, flat_fee_cents=flat_fee_cents,
        kill_fee_pct_num=kill_fee_pct_num, rights_default=rights_default,
        effective_from=effective_from, effective_to=effective_to)
    return contributor, agreement


def setup_assignment_in_state(target_state, legal_name="Writer One",
                              email=None, commissioned_word_count=100,
                              deadline_utc=DEFAULT_DEADLINE,
                              **agreement_kwargs):
    """Contributor + agreement + one assignment walked to target_state
    (OFFERED / ACCEPTED / IN_PROGRESS / UNDER_VERIFICATION).
    Returns (contributor, agreement, assignment)."""
    contributor, agreement = setup_contributor_with_agreement(
        legal_name=legal_name, email=email, **agreement_kwargs)
    assignment = create_assignment(
        contributor["id"],
        commissioned_word_count=commissioned_word_count,
        deadline_utc=deadline_utc)
    walked = walk_assignment(assignment["id"], contributor["id"],
                             target_state)
    return contributor, agreement, walked


def setup_under_verification_cleared(legal_name="Writer One", email=None,
                                     plag_bps=100, ai_bps=100, **kwargs):
    """Assignment in UNDER_VERIFICATION with both reports recorded CLEARED.
    Returns (contributor, agreement, assignment, reports)."""
    contributor, agreement, assignment = setup_assignment_in_state(
        "UNDER_VERIFICATION", legal_name=legal_name, email=email, **kwargs)
    reports = clear_all_reports(assignment["id"],
                                similarity_score_bps=plag_bps,
                                ai_probability_bps=ai_bps)
    return contributor, agreement, assignment, reports


def setup_accepted_assignment(legal_name="Writer One", email=None,
                              final_word_count=100, **kwargs):
    """Full pipeline to ACCEPTED_FOR_PUBLICATION.
    Returns (contributor, agreement, assignment)."""
    contributor, agreement, assignment, _reports = (
        setup_under_verification_cleared(legal_name=legal_name, email=email,
                                         **kwargs))
    accepted = accept_for_publication(assignment["id"], final_word_count)
    return contributor, agreement, accepted


def setup_verified_invoice(legal_name="Writer One", email=None,
                           fee_claim_cents=None, expense_claim_cents=0,
                           with_verified_tax_doc=True, doc_kind=None,
                           treaty_country=None, final_word_count=100,
                           **agreement_kwargs):
    """Accepted assignment + submitted invoice, VERIFIED by fin-1.
    Returns ctx dict with contributor, agreement, assignment, invoice."""
    contributor, agreement, accepted = setup_accepted_assignment(
        legal_name=legal_name, email=email,
        final_word_count=final_word_count, **agreement_kwargs)
    if with_verified_tax_doc:
        kind = doc_kind or (
            "W9" if contributor["tax_residency"] == "DOMESTIC_US"
            else "W8BEN")
        create_verified_tax_document(contributor["id"], doc_kind=kind,
                                     treaty_country=treaty_country)
    fee = (fee_claim_cents if fee_claim_cents is not None
           else accepted["final_fee_cents"])
    invoice = submit_invoice(accepted["id"], contributor["id"], fee,
                             expense_claim_cents)
    verified = verify_invoice(invoice["id"], "VERIFY", user_id=FIN_USER_1)
    return {
        "contributor": contributor,
        "agreement": agreement,
        "assignment": accepted,
        "invoice": verified,
    }


def setup_approved_invoice(**kwargs):
    """Verified invoice approved by a second FinanceUser (SoD-clean).
    Returns ctx dict."""
    ctx = setup_verified_invoice(**kwargs)
    approved = approve_invoice(ctx["invoice"]["id"], user_id=FIN_USER_2)
    ctx["invoice"] = approved
    return ctx


def setup_batched_invoice(scheduled_pay_date="2026-08-20T00:00:00Z",
                          **kwargs):
    """Approved invoice added to an OPEN batch and the batch LOCKED by
    fin-1. Returns ctx dict extended with batch and batch_version."""
    ctx = setup_approved_invoice(**kwargs)
    batch = create_batch(scheduled_pay_date)
    batch = add_invoice_to_batch(batch["id"], ctx["invoice"]["id"])
    batch = lock_batch(batch["id"], user_id=FIN_USER_1)
    ctx["batch"] = batch
    ctx["batch_version"] = batch["version"]
    return ctx


def setup_paid_invoice(**kwargs):
    """Full settlement: batch released by fin-2. Returns ctx dict."""
    ctx = setup_batched_invoice(**kwargs)
    released = release_batch(ctx["batch"]["id"], ctx["batch_version"],
                             user_id=FIN_USER_2)
    ctx["batch"] = released
    return ctx


# ---------------------------------------------------------------------------
# Tier 4 — reimbursement-included pipeline
# ---------------------------------------------------------------------------

def setup_accepted_with_reimbursable_expense(
        legal_name="Writer One", email=None, category="TRAVEL",
        requested_cents=5000, claimed_cents=None, receipt_attached=True,
        **agreement_kwargs):
    """Accepted assignment carrying one REIMBURSABLE expense claim.
    Returns (ctx contributor/agreement/assignment, expense_claim)."""
    contributor, agreement = setup_contributor_with_agreement(
        legal_name=legal_name, email=email, **agreement_kwargs)
    assignment = create_assignment(contributor["id"])
    walk_assignment(assignment["id"], contributor["id"], "ACCEPTED")
    claim = create_expense_claim(assignment["id"], contributor["id"],
                                 category=category,
                                 requested_cents=requested_cents)
    decided = decide_expense(claim["id"], "APPROVE")
    claimed = (claimed_cents if claimed_cents is not None
               else decided["approved_cents"])
    submit_expense(claim["id"], contributor["id"], claimed,
                   receipt_attached=receipt_attached)
    walk_assignment(assignment["id"], contributor["id"],
                    "UNDER_VERIFICATION")
    clear_all_reports(assignment["id"])
    settled = settle_expense(claim["id"], "REIMBURSE")
    accepted = accept_for_publication(assignment["id"], 100)
    ctx = {"contributor": contributor, "agreement": agreement,
           "assignment": accepted}
    return ctx, settled
