"""Composite setup helpers for multi-step test prerequisites.

The test runner restarts the API server before every test, so every fixture
builds its preconditions from scratch using only PRD-declared endpoints.
Setup calls use get_success_data() so a failed precondition surfaces as a
clear "setup failed" error rather than a confusing assertion failure.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_account_payload,
    create_adjustment_payload,
    create_application_payload,
    create_collection_action_payload,
    create_determination_payload,
    create_document_payload,
    create_member_payload,
    create_notice_payload,
    create_patient_payload,
    create_payment_payload,
    create_policy_payload,
    create_report_payload,
)
from .test_users import TEST_USERS

COUNSELOR = TEST_USERS["counselor_headers"]
REVIEWER = TEST_USERS["reviewer_headers"]
BILLING = TEST_USERS["billing_headers"]
COLLECTIONS = TEST_USERS["collections_headers"]
COMPLIANCE = TEST_USERS["compliance_headers"]


# ─── Clock ────────────────────────────────────────────

def set_clock(to_iso8601: str):
    """Advance the server-side logical clock (PRD §2.4)."""
    return get_success_data(api_client.set_clock(to_iso8601, COMPLIANCE))


# ─── Tier 1: single-entity creation ───────────────────

def create_policy(**overrides):
    """Create a DRAFT financial assistance policy."""
    return get_success_data(api_client.create_policy(create_policy_payload(**overrides), COMPLIANCE))


def create_active_policy(**overrides):
    """Create a policy and activate it (DRAFT -> ACTIVE). Returns the ACTIVE
    policy as returned by the activation call."""
    policy = create_policy(**overrides)
    return get_success_data(api_client.activate_policy(policy["id"], COMPLIANCE))


def create_patient(**overrides):
    return get_success_data(api_client.create_patient(create_patient_payload(**overrides), COUNSELOR))


def create_account(patient_id, **overrides):
    return get_success_data(
        api_client.create_account(create_account_payload(patient_id, **overrides), BILLING)
    )


def get_account(account_id, headers=BILLING):
    return get_success_data(api_client.get_account(account_id, headers))


def get_application(application_id, headers=COUNSELOR):
    return get_success_data(api_client.get_application(application_id, headers))


def get_policy(policy_id, headers=COMPLIANCE):
    return get_success_data(api_client.get_policy(policy_id, headers))


def issue_first_statement(account_id):
    """Issue the FIRST_STATEMENT notice; account moves to NOTICE_PERIOD (PRD §3.2)."""
    return get_success_data(api_client.issue_statement(account_id, BILLING))


def issue_notice(account_id, notice_type, delivery_channel="MAIL"):
    return get_success_data(
        api_client.issue_notice(
            account_id, create_notice_payload(notice_type, delivery_channel), BILLING
        )
    )


def post_payment(account_id, amount_cents, paid_at="2026-02-01T00:00:00Z", method="CARD",
                 headers=BILLING):
    return get_success_data(
        api_client.post_payment(
            account_id,
            create_payment_payload(amount_cents=amount_cents, paid_at=paid_at, method=method),
            headers,
        )
    )


def list_payments(account_id, headers=BILLING):
    data = get_success_data(api_client.list_payments(account_id, headers))
    return data if isinstance(data, list) else data.get("items", data)


def create_application(patient_id, headers=COUNSELOR, **overrides):
    return get_success_data(
        api_client.create_application(create_application_payload(patient_id, **overrides), headers)
    )


def add_member(application_id, full_name="Household Member", relationship="SELF", age=40,
               headers=COUNSELOR):
    return get_success_data(
        api_client.add_member(
            application_id,
            create_member_payload(full_name=full_name, relationship=relationship, age=age),
            headers,
        )
    )


def list_members(application_id, headers=COUNSELOR):
    return get_success_data(api_client.list_members(application_id, headers))


def submit_application(application_id, headers=COUNSELOR):
    return get_success_data(api_client.submit_application(application_id, headers))


def begin_review(application_id, headers=COUNSELOR):
    return get_success_data(api_client.begin_review(application_id, headers))


def request_documents(application_id, required_doc_types, headers=COUNSELOR):
    return get_success_data(
        api_client.request_documents(
            application_id, {"required_doc_types": required_doc_types}, headers
        )
    )


def resume_review(application_id, headers=COUNSELOR):
    return get_success_data(api_client.resume_review(application_id, headers))


def withdraw_application(application_id, headers=COUNSELOR, reason=None):
    payload = {} if reason is None else {"reason": reason}
    return get_success_data(api_client.withdraw_application(application_id, headers, payload))


def expire_application(application_id, headers=COUNSELOR):
    return get_success_data(api_client.expire_application(application_id, headers))


def upload_document(application_id, headers=COUNSELOR, **overrides):
    return get_success_data(
        api_client.upload_document(application_id, create_document_payload(**overrides), headers)
    )


def verify_document(document_id, headers=COUNSELOR):
    return get_success_data(api_client.verify_document(document_id, headers))


def reject_document(document_id, rejection_reason="illegible scan", headers=COUNSELOR):
    return get_success_data(
        api_client.reject_document(document_id, {"rejection_reason": rejection_reason}, headers)
    )


def run_screening(application_id, headers=COUNSELOR, **scores):
    """Run presumptive screening; only supplied (non-None) factors are sent."""
    payload = {k: v for k, v in scores.items() if v is not None}
    return get_success_data(api_client.run_presumptive_screening(application_id, payload, headers))


def get_screening(application_id, headers=COUNSELOR):
    """Fetch the application's screening list (0 or 1 entries)."""
    return get_success_data(api_client.get_presumptive_screening(application_id, headers))


# ─── Determinations (OCC-guarded, PRD §2.11) ──────────

def create_determination(application_id, basis, covered_account_ids, headers=REVIEWER):
    """Create a PRELIMINARY determination, OCC-guarded on the application's
    current version (read fresh immediately before the create)."""
    app = get_application(application_id)
    payload = create_determination_payload(
        application_id, basis, covered_account_ids, app["version"]
    )
    return get_success_data(api_client.create_determination(payload, headers))


def finalize_determination(determination_id, headers=REVIEWER):
    return get_success_data(api_client.finalize_determination(determination_id, headers))


def reverse_determination(determination_id, headers=REVIEWER, reason=None):
    payload = {} if reason is None else {"reason": reason}
    return get_success_data(api_client.reverse_determination(determination_id, headers, payload))


def get_determination(determination_id, headers=REVIEWER):
    return get_success_data(api_client.get_determination(determination_id, headers))


# ─── Adjustments (OCC-guarded, PRD §2.11) ─────────────

def post_adjustment(account_id, determination_id, headers=BILLING):
    """Post the WRITE_OFF adjustment (plus refund waterfall when retro-eligible),
    OCC-guarded on the account's current version (read fresh immediately before)."""
    account = get_account(account_id)
    payload = create_adjustment_payload(determination_id, account["version"])
    return get_success_data(api_client.post_adjustment(account_id, payload, headers))


def list_account_adjustments(account_id, headers=BILLING):
    return get_success_data(api_client.list_account_adjustments(account_id, headers))


def list_determination_adjustments(determination_id, headers=BILLING):
    return get_success_data(api_client.list_determination_adjustments(determination_id, headers))


# ─── Collections ──────────────────────────────────────

def evaluate_posture(account_id, headers=COLLECTIONS):
    return get_success_data(api_client.evaluate_posture(account_id, headers))


def create_collection_action(account_id, action_type="CREDIT_REPORT", headers=COLLECTIONS):
    return get_success_data(
        api_client.create_collection_action(
            account_id, create_collection_action_payload(action_type), headers
        )
    )


def halt_collection_action(action_id, reason=None, headers=COMPLIANCE):
    payload = {} if reason is None else {"reason": reason}
    return get_success_data(api_client.halt_collection_action(action_id, payload, headers))


def list_account_notices(account_id, headers=BILLING):
    return get_success_data(api_client.list_account_notices(account_id, headers))


def list_application_notices(application_id, headers=COUNSELOR):
    return get_success_data(api_client.list_application_notices(application_id, headers))


# ─── Community benefit reports ────────────────────────

def create_report(reporting_year=2026):
    return get_success_data(api_client.create_report(create_report_payload(reporting_year), COMPLIANCE))


def get_report(report_id, headers=COMPLIANCE):
    return get_success_data(api_client.get_report(report_id, headers))


def file_report(report_id):
    return get_success_data(api_client.file_report(report_id, COMPLIANCE))


def reopen_report(report_id):
    return get_success_data(api_client.reopen_report(report_id, COMPLIANCE))


def recompute_report(report_id):
    return get_success_data(api_client.recompute_report(report_id, COMPLIANCE))


# ─── Tier 2: application preambles ────────────────────

def build_under_review_application(
    *,
    patient_name="Applicant Alice",
    mrn="MRN-APP-1",
    ssn_last4="1001",
    date_of_birth="1980-01-01",
    screening_source="STANDARD",
    reported_income=2000000,
    reported_assets=0,
    members=(("SELF", 40),),
    accounts=(),
    counselor_headers=None,
    patient=None,
    encounter_date="2026-01-10",
):
    """Patient + accounts + application walked DRAFT -> SUBMITTED -> UNDER_REVIEW.
    An ACTIVE policy must already exist. Members is a tuple of (relationship, age);
    accounts a tuple of (total_charges_cents, insurance_paid_cents). Pass an
    existing `patient` dict to attach the application to that patient instead of
    registering a new one (needed when the patient's accounts already carry
    statements or payments)."""
    counselor = counselor_headers or COUNSELOR
    if patient is None:
        patient = create_patient(
            full_name=patient_name, date_of_birth=date_of_birth,
            ssn_last4=ssn_last4, mrn=mrn,
        )
    created_accounts = [
        create_account(
            patient["id"], total_charges_cents=charges,
            insurance_paid_cents=insurance, encounter_date=encounter_date,
        )
        for charges, insurance in accounts
    ]
    application = create_application(
        patient["id"],
        headers=counselor,
        screening_source=screening_source,
        reported_annual_income_cents=reported_income,
        reported_liquid_assets_cents=reported_assets,
    )
    created_members = [
        add_member(
            application["id"],
            full_name=patient_name if i == 0 else f"{patient_name} member {i}",
            relationship=relationship, age=age, headers=counselor,
        )
        for i, (relationship, age) in enumerate(members)
    ]
    submit_application(application["id"], headers=counselor)
    application = begin_review(application["id"], headers=counselor)
    return {
        "patient": patient,
        "application": application,
        "members": created_members,
        "accounts": created_accounts,
        "documents": [],
    }


def upload_and_verify(application_id, member_id, *, doc_type, amount_cents,
                      period_start="2025-01-01", period_end="2025-12-31",
                      verify=True, counselor_headers=None):
    """Upload one document (member-linked) and optionally verify it."""
    counselor = counselor_headers or COUNSELOR
    doc = upload_document(
        application_id,
        headers=counselor,
        doc_type=doc_type,
        period_start=period_start,
        period_end=period_end,
        amount_cents=amount_cents,
        household_member_id=member_id,
    )
    if verify:
        doc = verify_document(doc["id"], headers=counselor)
    return doc


def build_verified_application(
    *,
    tax_return_amount=2000000,
    extra_verified_docs=(),
    **kwargs,
):
    """build_under_review_application + a VERIFIED TAX_RETURN and a VERIFIED
    IDENTITY document (the evidence gate for basis=VERIFIED_APPLICATION,
    PRD §3.8). extra_verified_docs entries are dicts with doc_type/amount_cents
    and optional period_start/period_end, all member-linked and verified."""
    ctx = build_under_review_application(**kwargs)
    counselor = kwargs.get("counselor_headers") or COUNSELOR
    member_id = ctx["members"][0]["id"]
    app_id = ctx["application"]["id"]
    tax_doc = upload_and_verify(
        app_id, member_id, doc_type="TAX_RETURN", amount_cents=tax_return_amount,
        counselor_headers=counselor,
    )
    identity_doc = upload_and_verify(
        app_id, member_id, doc_type="IDENTITY", amount_cents=0,
        period_start="2026-01-01", period_end="2026-01-01",
        counselor_headers=counselor,
    )
    ctx["documents"] = [tax_doc, identity_doc]
    for spec in extra_verified_docs:
        ctx["documents"].append(
            upload_and_verify(app_id, member_id, counselor_headers=counselor, **spec)
        )
    ctx["application"] = get_application(app_id)
    return ctx


def setup_verified_application(
    *,
    clock="2026-02-01T00:00:00Z",
    policy_overrides=None,
    **kwargs,
):
    """Full standard-path preamble: logical clock set, ACTIVE policy, patient,
    accounts, application UNDER_REVIEW with verified TAX_RETURN + IDENTITY."""
    set_clock(clock)
    policy = create_active_policy(**(policy_overrides or {}))
    ctx = build_verified_application(**kwargs)
    ctx["policy"] = policy
    return ctx


def setup_presumptive_application(
    *,
    clock="2026-02-01T00:00:00Z",
    policy_overrides=None,
    screening_scores=None,
    counselor_headers=None,
    **kwargs,
):
    """PRESUMPTIVE application UNDER_REVIEW; when screening_scores is given the
    screening is run as well (PRD §3.7)."""
    set_clock(clock)
    policy = create_active_policy(**(policy_overrides or {}))
    kwargs.setdefault("screening_source", "PRESUMPTIVE")
    ctx = build_under_review_application(counselor_headers=counselor_headers, **kwargs)
    ctx["policy"] = policy
    if screening_scores is not None:
        ctx["screening"] = run_screening(
            ctx["application"]["id"], headers=counselor_headers or COUNSELOR,
            **screening_scores,
        )
    return ctx


# ─── Tier 3: determination / adjustment lifecycle ─────

def setup_final_determination(*, basis="VERIFIED_APPLICATION",
                              determination_headers=None, **kwargs):
    """Verified application + PRELIMINARY determination + finalize (FINAL)."""
    ctx = setup_verified_application(**kwargs)
    reviewer = determination_headers or REVIEWER
    covered = [a["id"] for a in ctx["accounts"]]
    det = create_determination(ctx["application"]["id"], basis, covered, headers=reviewer)
    det = finalize_determination(det["id"], headers=reviewer)
    ctx["determination"] = det
    ctx["application"] = get_application(ctx["application"]["id"])
    return ctx


def setup_posted_writeoff(**kwargs):
    """Full lifecycle through the posted WRITE_OFF adjustment on the first
    account. Returns ctx with 'determination' and 'adjustment'."""
    ctx = setup_final_determination(**kwargs)
    account = ctx["accounts"][0]
    adjustment = post_adjustment(account["id"], ctx["determination"]["id"])
    ctx["adjustment"] = adjustment
    ctx["accounts"][0] = get_account(account["id"])
    return ctx


# ─── Tier 4: collections timeline targeting ───────────

def setup_account_in_notice_period(
    *,
    patient_name="Window Will",
    mrn="MRN-WIN-1",
    ssn_last4="1313",
    total_charges=100000,
    insurance=0,
    statement_at="2026-01-01T00:00:00Z",
    policy_overrides=None,
):
    """ACTIVE policy + patient + account with FIRST_STATEMENT issued at
    statement_at, leaving the account in NOTICE_PERIOD."""
    set_clock(statement_at)
    policy = create_active_policy(**(policy_overrides or {}))
    patient = create_patient(
        full_name=patient_name, date_of_birth="1979-04-04",
        ssn_last4=ssn_last4, mrn=mrn,
    )
    account = create_account(
        patient["id"], total_charges_cents=total_charges, insurance_paid_cents=insurance,
        encounter_date="2025-12-15",
    )
    issue_first_statement(account["id"])
    return {"policy": policy, "patient": patient, "account": get_account(account["id"])}


def add_eca_warning(ctx, warning_at="2026-04-01T00:00:00Z", delivery_channel="MAIL"):
    """Issue an ECA_WARNING at the given logical-clock instant."""
    set_clock(warning_at)
    notice = issue_notice(ctx["account"]["id"], "ECA_WARNING", delivery_channel)
    ctx["warning"] = notice
    return notice


def setup_eca_active_account(
    *,
    action_type="CREDIT_REPORT",
    eval_at="2026-05-01T00:00:00Z",
    warning_at="2026-04-01T00:00:00Z",
    **kwargs,
):
    """Account walked to ECA_ACTIVE with one INITIATED collection action:
    FIRST_STATEMENT -> ECA_WARNING -> evaluate-posture (ECA_ELIGIBLE) -> action."""
    ctx = setup_account_in_notice_period(**kwargs)
    add_eca_warning(ctx, warning_at)
    set_clock(eval_at)
    account = evaluate_posture(ctx["account"]["id"])
    assert account["collection_posture"] == "ECA_ELIGIBLE", (
        f"setup failed: expected ECA_ELIGIBLE, got {account['collection_posture']}"
    )
    action = create_collection_action(ctx["account"]["id"], action_type)
    ctx["action"] = action
    ctx["account"] = get_account(ctx["account"]["id"])
    return ctx
