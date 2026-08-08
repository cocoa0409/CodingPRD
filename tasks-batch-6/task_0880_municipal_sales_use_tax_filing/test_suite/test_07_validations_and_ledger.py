"""Cross-entity guards, interval-overlap semantics, precedence, and the balance ledger."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    make_taxpayer_headers, make_admin_headers,
    create_active_taxpayer, create_jurisdiction, create_draft_return,
    create_filed_return, file_return, set_clock,
    open_field_audit, create_certificate, create_remittance,
    create_open_refund_claim, get_taxpayer,
    create_return_line, create_return_payload, create_jurisdiction_payload,
    create_certificate_payload,
)


def _amend(api, taxpayer_id, return_id, version, jurisdiction_id, gross_sales_cents=500000):
    line = create_return_line(jurisdiction_id, gross_sales_cents=gross_sales_cents)
    return api.amend_return(
        return_id,
        {"expected_return_version": version, "lines": [line]},
        make_taxpayer_headers(taxpayer_id),
    )


# --- Cross-entity: amend blocked by open audit --------------------------------
def test_amend_blocked_by_open_audit_same_period(api):
    """PRD §3.4: "that no `Audit` exists for the same `taxpayer_id` and `period_key` in
    `OPEN` status, otherwise `ERR_AUDIT_OPEN_ON_PERIOD`."

    Design: Difficulty/cross_entity_state_dependency/return_amend_blocked_by_open_audit
    """
    tp = create_active_taxpayer(api)
    jur = create_jurisdiction(api, rate_bps=850)
    filed = create_filed_return(api, tp["id"], jurisdiction_id=jur["id"], period_key="2026-Q1")
    open_field_audit(api, tp["id"], period_key="2026-Q1")
    resp = _amend(api, tp["id"], filed["id"], filed["version"], jur["id"])
    validate_error(resp, ApiErrorId.ERR_AUDIT_OPEN_ON_PERIOD, expected_status=409)


def test_amend_allowed_when_open_audit_on_different_period(api):
    """PRD §3.4: "that no `Audit` exists for the same `taxpayer_id` and `period_key` in
    `OPEN` status, otherwise `ERR_AUDIT_OPEN_ON_PERIOD`."

    Design: Difficulty/cross_entity_state_dependency/return_amend_blocked_by_open_audit
    """
    tp = create_active_taxpayer(api)
    jur = create_jurisdiction(api, rate_bps=850)
    filed = create_filed_return(api, tp["id"], jurisdiction_id=jur["id"], period_key="2026-Q1")
    open_field_audit(api, tp["id"], period_key="2026-Q2")  # different period, must not block
    amended = validate_success(_amend(api, tp["id"], filed["id"], filed["version"], jur["id"]))
    assert amended["status"] == "AMENDING"


# --- Cross-entity: refund approval blocked by suspension -----------------------
def test_refund_approve_blocked_when_taxpayer_suspended(api):
    """PRD §3.7: "Approval requires the claim to be `OPEN` (otherwise `ERR_REFUND_NOT_OPEN`)
    and the owning taxpayer to not be `SUSPENDED`, otherwise `ERR_ACCOUNT_SUSPENDED`."

    Design: Difficulty/cross_entity_state_dependency/refund_approve_blocked_by_suspended_taxpayer
    """
    tp = create_active_taxpayer(api)
    jur = create_jurisdiction(api, rate_bps=850)
    filed = create_filed_return(api, tp["id"], jurisdiction_id=jur["id"])
    claim = create_open_refund_claim(api, tp["id"], filed["id"], filed["version"],
                                     claim_amount_cents=5000)
    validate_success(api.suspend_taxpayer(tp["id"], {"suspend_reason": "Delinquent"},
                                          make_admin_headers()))
    resp = api.approve_refund_claim(claim["id"], make_admin_headers())
    validate_error(resp, ApiErrorId.ERR_ACCOUNT_SUSPENDED, expected_status=409)


def test_refund_approve_succeeds_after_reinstatement(api):
    """PRD §3.7: "Approval requires the claim to be `OPEN` (otherwise `ERR_REFUND_NOT_OPEN`)
    and the owning taxpayer to not be `SUSPENDED`, otherwise `ERR_ACCOUNT_SUSPENDED`."

    Design: Difficulty/cross_entity_state_dependency/refund_approve_blocked_by_suspended_taxpayer
    """
    tp = create_active_taxpayer(api)
    jur = create_jurisdiction(api, rate_bps=850)
    filed = create_filed_return(api, tp["id"], jurisdiction_id=jur["id"])
    claim = create_open_refund_claim(api, tp["id"], filed["id"], filed["version"],
                                     claim_amount_cents=5000)
    validate_success(api.suspend_taxpayer(tp["id"], {"suspend_reason": "Delinquent"},
                                          make_admin_headers()))
    validate_success(api.activate_taxpayer(tp["id"], make_admin_headers()))  # reinstate -> ACTIVE
    approved = validate_success(api.approve_refund_claim(claim["id"], make_admin_headers()))
    assert approved["status"] == "APPROVED"


# --- Resource temporal overlap: closed-interval return periods ----------------
def test_return_period_overlap_closed_interval_rejected(api):
    """PRD §3.3: "if any existing return's period interval `[period_start_date,
    period_end_date]` — treated as a closed interval on both ends — overlaps the new one,
    the request is rejected with `ERR_PERIOD_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/return_period_overlap_closed_interval
    """
    tp = create_active_taxpayer(api)
    jur = create_jurisdiction(api, rate_bps=850)
    create_draft_return(api, tp["id"], jurisdiction_id=jur["id"], period_key="2026-Q1",
                        period_start_date="2026-01-01T00:00:00Z",
                        period_end_date="2026-03-31T00:00:00Z",
                        filing_due_date="2026-04-20T00:00:00Z")
    resp = api.create_return(
        create_return_payload(tp["id"], jurisdiction_id=jur["id"], period_key="2026-Q2",
                              period_start_date="2026-03-31T00:00:00Z",
                              period_end_date="2026-06-30T00:00:00Z",
                              filing_due_date="2026-07-20T00:00:00Z"),
        make_taxpayer_headers(tp["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_PERIOD_OVERLAP, expected_status=409)


def test_return_period_adjacent_does_not_overlap(api):
    """PRD §3.3: "if any existing return's period interval `[period_start_date,
    period_end_date]` — treated as a closed interval on both ends — overlaps the new one,
    the request is rejected with `ERR_PERIOD_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/return_period_overlap_closed_interval
    """
    tp = create_active_taxpayer(api)
    jur = create_jurisdiction(api, rate_bps=850)
    create_draft_return(api, tp["id"], jurisdiction_id=jur["id"], period_key="2026-Q1",
                        period_start_date="2026-01-01T00:00:00Z",
                        period_end_date="2026-03-31T00:00:00Z",
                        filing_due_date="2026-04-20T00:00:00Z")
    resp = api.create_return(
        create_return_payload(tp["id"], jurisdiction_id=jur["id"], period_key="2026-Q2",
                              period_start_date="2026-04-01T00:00:00Z",
                              period_end_date="2026-06-30T00:00:00Z",
                              filing_due_date="2026-07-20T00:00:00Z"),
        make_taxpayer_headers(tp["id"]),
    )
    validate_success(resp, expected_status=201)


# --- Resource temporal overlap: half-open exemption certificates --------------
def test_certificate_overlap_half_open_interval_rejected(api):
    """PRD §3.2: "the system rejects it if the same taxpayer already holds a certificate
    of the same `exemption_type` whose half-open validity interval overlaps the new one,
    returning `ERR_CERTIFICATE_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/exemption_certificate_overlap_half_open_interval
    """
    tp = create_active_taxpayer(api)
    create_certificate(api, tp["id"], exemption_type="RESALE", certificate_number="R-A",
                       effective_date="2026-01-01T00:00:00Z", expiry_date="2026-07-01T00:00:00Z")
    resp = api.create_certificate(
        create_certificate_payload(tp["id"], exemption_type="RESALE", certificate_number="R-B",
                                   effective_date="2026-06-01T00:00:00Z",
                                   expiry_date="2026-12-01T00:00:00Z"),
        make_taxpayer_headers(tp["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_CERTIFICATE_OVERLAP, expected_status=409)


def test_certificate_adjacent_half_open_does_not_overlap(api):
    """PRD §3.2: "A certificate's validity interval is half-open: it covers `effective_date`
    up to but not including `expiry_date`."
    PRD §3.2: "the system rejects it if the same taxpayer already holds a certificate of the
    same `exemption_type` whose half-open validity interval overlaps the new one, returning
    `ERR_CERTIFICATE_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/exemption_certificate_overlap_half_open_interval
    """
    tp = create_active_taxpayer(api)
    create_certificate(api, tp["id"], exemption_type="RESALE", certificate_number="R-A",
                       effective_date="2026-01-01T00:00:00Z", expiry_date="2026-07-01T00:00:00Z")
    resp = api.create_certificate(
        create_certificate_payload(tp["id"], exemption_type="RESALE", certificate_number="R-B",
                                   effective_date="2026-07-01T00:00:00Z",
                                   expiry_date="2026-12-01T00:00:00Z"),
        make_taxpayer_headers(tp["id"]),
    )
    validate_success(resp, expected_status=201)


# --- Priority pair: certificate owner-mismatch beats expiry --------------------
def test_certificate_owner_mismatch_beats_expiry(api):
    """PRD §3.3: "the certificate must belong to the same taxpayer as the return (otherwise
    `ERR_CERTIFICATE_OWNER_MISMATCH`), and it must be valid at the return's `period_end_date`
    ... otherwise `ERR_CERTIFICATE_EXPIRED`. The owner check precedes the validity check."

    Design: Difficulty/priority_pair_validation_conflict/return_referential_beats_temporal_on_certificate
    """
    tp1 = create_active_taxpayer(api)
    tp2 = create_active_taxpayer(api)
    jur = create_jurisdiction(api, rate_bps=850)
    cert = create_certificate(api, tp2["id"], exemption_type="RESALE", certificate_number="R-1",
                              effective_date="2025-01-01T00:00:00Z",
                              expiry_date="2025-06-01T00:00:00Z")  # expired for a 2026-Q1 period
    resp = api.create_return(
        create_return_payload(tp1["id"], jurisdiction_id=jur["id"],
                              exemption_certificate_id=cert["id"]),
        make_taxpayer_headers(tp1["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_CERTIFICATE_OWNER_MISMATCH, expected_status=409)


def test_certificate_owner_mismatch_with_valid_certificate(api):
    """PRD §3.3: "the certificate must belong to the same taxpayer as the return (otherwise
    `ERR_CERTIFICATE_OWNER_MISMATCH`), and it must be valid at the return's `period_end_date`
    ... otherwise `ERR_CERTIFICATE_EXPIRED`. The owner check precedes the validity check."

    Design: Difficulty/priority_pair_validation_conflict/return_referential_beats_temporal_on_certificate
    """
    tp1 = create_active_taxpayer(api)
    tp2 = create_active_taxpayer(api)
    jur = create_jurisdiction(api, rate_bps=850)
    cert = create_certificate(api, tp2["id"], exemption_type="RESALE", certificate_number="R-1",
                              effective_date="2026-01-01T00:00:00Z",
                              expiry_date="2026-07-01T00:00:00Z")  # valid at 2026-03-31
    resp = api.create_return(
        create_return_payload(tp1["id"], jurisdiction_id=jur["id"],
                              exemption_certificate_id=cert["id"]),
        make_taxpayer_headers(tp1["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_CERTIFICATE_OWNER_MISMATCH, expected_status=409)


# --- Validation corner: duplicate jurisdiction code ---------------------------
def test_duplicate_jurisdiction_code_rejected(api):
    """PRD §3.2: "A jurisdiction carries a short `code` that must be unique across all
    jurisdictions (a duplicate is rejected with `ERR_DUPLICATE_JURISDICTION`)".

    Design: Corner/validations/duplicate_jurisdiction_code_rejected
    """
    create_jurisdiction(api, code="CITY", name="City", rate_bps=850)
    resp = api.create_jurisdiction(
        create_jurisdiction_payload(code="CITY", name="City Dup", rate_bps=900),
        make_admin_headers(),
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_JURISDICTION, expected_status=409)


# --- Consistency model: balance is derived-on-read ----------------------------
def test_account_balance_immediate_after_file(api):
    """PRD §2.6: "A taxpayer's `account_balance_cents` is never stored as a mutable field;
    it is derived on read every time a taxpayer is fetched and recomputed after any mutation
    to that taxpayer's returns, assessments, remittances, or refunds."

    Design: Corner/consistency_model/account_balance_immediate_after_file
    """
    tp = create_active_taxpayer(api)
    jur = create_jurisdiction(api, rate_bps=850)
    line = create_return_line(jur["id"], gross_sales_cents=1000000, exempt_sales_cents=200000)
    ret = create_draft_return(api, tp["id"], lines=[line], filing_due_date="2026-04-20T00:00:00Z")
    set_clock(api, "2026-04-20T00:00:00Z")
    file_return(api, tp["id"], ret["id"])
    fetched = get_taxpayer(api, tp["id"])
    assert fetched["account_balance_cents"] == 66980
