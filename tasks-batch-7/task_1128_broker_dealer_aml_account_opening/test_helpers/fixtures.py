"""Composite setup helpers (PRD §2.5, §3).

Every helper builds its preconditions from scratch via PRD-declared endpoints,
using get_success_data so setup failures surface as clear setup errors.
"""
from typing import Optional

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_paginated,
    validate_success,
)

from .api_client import api_client
from .factories import (
    create_account_payload,
    create_case_payload,
    create_certification_payload,
    create_customer_payload,
    create_deposit_payload,
    create_edd_review_payload,
    create_engagement_payload,
    create_fincen_request_payload,
    create_finding_payload,
    create_lost_stolen_payload,
    create_rep_payload,
    create_rule_payload,
    create_sar_filing_payload,
    post_transaction_payload,
    submit_document_payload,
    add_owner_payload,
)
from .test_users import (
    TEST_USERS,
    make_rep_headers,
)

CLOCK_START_ISO = "2026-05-01T00:00:00Z"
FAR_EXPIRY = "2030-01-01"


# --- Clock & sweep ---------------------------------------------------------


def set_clock(to_iso8601: str = CLOCK_START_ISO) -> dict:
    resp = api_client.set_clock({"to_iso8601": to_iso8601}, TEST_USERS["admin_headers"])
    return get_success_data(resp)


def run_daily_sweep() -> dict:
    resp = api_client.run_daily_sweep(TEST_USERS["admin_headers"])
    return get_success_data(resp)


# --- Reps / customers / documents ------------------------------------------


def create_rep(**overrides) -> dict:
    resp = api_client.create_rep(create_rep_payload(**overrides), TEST_USERS["admin_headers"])
    return get_success_data(resp)


def rep_headers(rep: dict) -> dict:
    return make_rep_headers(rep["id"])


def create_customer(rep: dict, **overrides) -> dict:
    resp = api_client.create_customer(create_customer_payload(**overrides), rep_headers(rep))
    return get_success_data(resp)


def submit_document(customer_id: str, rep: dict, **overrides) -> dict:
    resp = api_client.submit_document(
        customer_id, submit_document_payload(**overrides), rep_headers(rep)
    )
    return get_success_data(resp)


def verify_document(doc_id: str) -> dict:
    resp = api_client.verify_document(doc_id, TEST_USERS["analyst_headers"])
    return get_success_data(resp)


def submit_and_verify_document(
    customer_id: str,
    rep: dict,
    doc_type: str = "GOVERNMENT_ID",
    expiry_date: str = FAR_EXPIRY,
    **overrides,
) -> dict:
    doc = submit_document(
        customer_id, rep, doc_type=doc_type, expiry_date=expiry_date, **overrides
    )
    return verify_document(doc["id"])


# --- Accounts ---------------------------------------------------------------


def create_account(customer_id: str, rep: dict, **overrides) -> dict:
    resp = api_client.create_account(
        create_account_payload(customer_id, **overrides), rep_headers(rep)
    )
    return get_success_data(resp)


def approve_account(account_id: str) -> dict:
    resp = api_client.approve_account(account_id, TEST_USERS["officer_headers"])
    return get_success_data(resp)


def get_account(account_id: str) -> dict:
    resp = api_client.get_account(account_id, TEST_USERS["officer_headers"])
    return get_success_data(resp)


def setup_pending_account(
    country_risk_tier: str = "LOW",
    is_pep: bool = False,
    product_set=("CASH",),
    customer_type: str = "INDIVIDUAL",
    doc_expiry: str = FAR_EXPIRY,
    verify_doc: bool = True,
    set_clock_first: bool = True,
    **customer_overrides,
) -> dict:
    """Rep + customer (+ VERIFIED GOVERNMENT_ID doc) + PENDING_APPROVAL account."""
    if set_clock_first:
        set_clock()
    rep = create_rep()
    customer = create_customer(
        rep,
        customer_type=customer_type,
        country_risk_tier=country_risk_tier,
        is_pep=is_pep,
        **customer_overrides,
    )
    doc = None
    if verify_doc:
        doc = submit_and_verify_document(customer["id"], rep, expiry_date=doc_expiry)
    account = create_account(customer["id"], rep, product_set=list(product_set))
    return {"rep": rep, "customer": customer, "doc": doc, "account": account}


def setup_open_account(**kwargs) -> dict:
    """Rep + customer + VERIFIED doc + OPEN (approved) account."""
    ctx = setup_pending_account(**kwargs)
    ctx["account"] = approve_account(ctx["account"]["id"])
    return ctx


# --- Beneficial ownership ---------------------------------------------------


def create_certification(customer_id: str, rep: dict, **overrides) -> dict:
    resp = api_client.create_certification(
        customer_id, create_certification_payload(**overrides), rep_headers(rep)
    )
    return get_success_data(resp)


def add_owner(cert_id: str, rep: dict, **overrides) -> dict:
    resp = api_client.add_owner(cert_id, add_owner_payload(**overrides), rep_headers(rep))
    return get_success_data(resp)


def certify(cert_id: str) -> dict:
    resp = api_client.certify(cert_id, TEST_USERS["officer_headers"])
    return get_success_data(resp)


def setup_certified_certification(rep: dict, customer_id: str, **cert_overrides) -> dict:
    """DRAFT certification + one 100% control-person owner with full KYC -> CERTIFIED."""
    cert = create_certification(customer_id, rep, **cert_overrides)
    add_owner(cert["id"], rep, ownership_pct=100.00, is_control_person=True)
    return certify(cert["id"])


# --- Transactions ------------------------------------------------------------


def post_wire(account_id: str, rep: dict, amount: float) -> dict:
    resp = api_client.post_transaction(
        account_id,
        post_transaction_payload(txn_type="WIRE_OUT", amount=amount),
        rep_headers(rep),
    )
    return get_success_data(resp)


def post_security_txn(
    account_id: str,
    rep: Optional[dict],
    txn_type: str,
    security_id: str,
    quantity,
    unit_price,
    headers: Optional[dict] = None,
) -> dict:
    hdrs = headers if headers is not None else rep_headers(rep)
    resp = api_client.post_transaction(
        account_id,
        post_transaction_payload(
            txn_type=txn_type,
            security_id=security_id,
            quantity=quantity,
            unit_price=unit_price,
        ),
        hdrs,
    )
    return get_success_data(resp)


def post_structuring_buys(
    account_id: str, rep: dict, count: int = 3, quantity=100, unit_price=40.00
) -> list:
    return [
        post_security_txn(account_id, rep, "BUY", "ACME", quantity, unit_price)
        for _ in range(count)
    ]


# --- Monitoring rules / scans / alerts --------------------------------------


def create_rule(**overrides) -> dict:
    resp = api_client.create_rule(create_rule_payload(**overrides), TEST_USERS["admin_headers"])
    return get_success_data(resp)


def run_scan() -> dict:
    resp = api_client.run_scan(TEST_USERS["analyst_headers"])
    return get_success_data(resp)


def list_alerts_for_account(account_id: str) -> list:
    resp = api_client.list_alerts(
        TEST_USERS["analyst_headers"], params={"account_id": account_id}
    )
    data, _meta = validate_paginated(resp)
    return data


def get_alert(alert_id: str) -> dict:
    resp = api_client.get_alert(alert_id, TEST_USERS["analyst_headers"])
    return get_success_data(resp)


def setup_structuring_alert(account_id: Optional[str] = None, under_review: bool = True) -> dict:
    """OPEN LOW account + STRUCTURING rule + 3 BUYs of 4000.00 + scan -> one alert.

    If account_id is None, builds the whole account context first.
    """
    if account_id is None:
        ctx = setup_open_account()
        account_id = ctx["account"]["id"]
        rep = ctx["rep"]
    else:
        ctx = {"account": get_account(account_id)}
        rep = None
    create_rule(rule_code="STRUCTURING", threshold_amount=10000.00, window_days=2,
                min_transaction_count=3)
    post_structuring_buys(account_id, rep)
    run_scan()
    alerts = list_alerts_for_account(account_id)
    assert len(alerts) == 1, f"Setup failed: expected 1 alert, got {len(alerts)}"
    alert = alerts[0]
    if under_review:
        resp = api_client.begin_alert_review(alert["id"], TEST_USERS["analyst_headers"])
        alert = get_success_data(resp)
    ctx["alert"] = alert
    return ctx


# --- Cases -------------------------------------------------------------------


def get_account_version(account_id: str) -> int:
    return get_account(account_id)["version"]


def get_case(case_id: str) -> dict:
    resp = api_client.get_case(case_id, TEST_USERS["analyst_headers"])
    return get_success_data(resp)


def create_manual_case(account_id: str, **overrides) -> dict:
    version = get_account_version(account_id)
    resp = api_client.create_case(
        create_case_payload(account_id, version, **overrides),
        TEST_USERS["analyst_headers"],
    )
    return get_success_data(resp)


def escalate_alert(alert_id: str) -> dict:
    resp = api_client.escalate_alert(alert_id, TEST_USERS["analyst_headers"])
    return validate_success(resp, expected_status=201)


def setup_case_via_escalation() -> dict:
    """STRUCTURING alert UNDER_REVIEW escalated -> AMLCase OPEN."""
    ctx = setup_structuring_alert(under_review=True)
    escalation = escalate_alert(ctx["alert"]["id"])
    ctx["case_id"] = escalation["case_id"]
    ctx["case_priority"] = escalation["case_priority"]
    resp = api_client.get_case(ctx["case_id"], TEST_USERS["analyst_headers"])
    ctx["case"] = get_success_data(resp)
    return ctx


def begin_investigation(case_id: str) -> dict:
    resp = api_client.begin_investigation(case_id, TEST_USERS["analyst_headers"])
    return get_success_data(resp)


def recommend_sar(
    case_id: str,
    analyst_id: str = "analyst-recommender",
    initial_detection_date: str = "2026-05-01",
    recommendation_note: str = "file a SAR",
) -> dict:
    from .test_users import make_analyst_headers

    resp = api_client.recommend_sar(
        case_id,
        {
            "recommendation_note": recommendation_note,
            "initial_detection_date": initial_detection_date,
        },
        make_analyst_headers(analyst_id),
    )
    return get_success_data(resp)


def setup_case_in_state(
    target_state: str = "INVESTIGATING",
    detection_date: str = "2026-05-01",
    analyst_id: str = "analyst-recommender",
) -> dict:
    """OPEN LOW account + manual case walked to the requested state.

    Supported: OPEN, INVESTIGATING, SAR_RECOMMENDED.
    """
    ctx = setup_open_account()
    case = create_manual_case(ctx["account"]["id"])
    ctx["case"] = case
    if target_state == "OPEN":
        return ctx
    case = begin_investigation(case["id"])
    ctx["case"] = case
    if target_state == "INVESTIGATING":
        return ctx
    case = recommend_sar(
        case["id"], analyst_id=analyst_id, initial_detection_date=detection_date
    )
    ctx["case"] = case
    return ctx


# --- SAR filings --------------------------------------------------------------


def create_sar_filing(case_id: str, sar_officer_id: str = "saroff-1", **overrides) -> dict:
    from .test_users import make_sar_officer_headers

    resp = api_client.create_sar_filing(
        create_sar_filing_payload(case_id, **overrides),
        make_sar_officer_headers(sar_officer_id),
    )
    return get_success_data(resp)


def file_sar(filing_id: str, sar_officer_id: str = "saroff-1") -> dict:
    from .test_users import make_sar_officer_headers

    resp = api_client.file_sar(filing_id, make_sar_officer_headers(sar_officer_id))
    return get_success_data(resp)


def get_sar_filing(filing_id: str) -> dict:
    resp = api_client.get_sar_filing(filing_id, TEST_USERS["sar_officer_headers"])
    return get_success_data(resp)


def setup_filed_sar(
    detection_date: str = "2026-05-01",
    analyst_id: str = "analyst-recommender",
    sar_officer_id: str = "saroff-1",
    **sar_overrides,
) -> dict:
    """Manual case -> INVESTIGATING -> SAR_RECOMMENDED -> DRAFT SAR -> FILED.

    Case ends DECIDED_FILED. Returns context with case, sar, account, rep.
    """
    ctx = setup_case_in_state(
        "SAR_RECOMMENDED", detection_date=detection_date, analyst_id=analyst_id
    )
    sar_overrides.setdefault("activity_start", "2026-05-01")
    sar_overrides.setdefault("activity_end", "2026-05-01")
    sar = create_sar_filing(
        ctx["case"]["id"],
        sar_officer_id=sar_officer_id,
        **sar_overrides,
    )
    sar = file_sar(sar["id"], sar_officer_id=sar_officer_id)
    ctx["sar"] = sar
    return ctx


# --- FinCEN 314(a) ------------------------------------------------------------


def create_fincen_request(subjects=None, **overrides) -> dict:
    resp = api_client.create_fincen_request(
        create_fincen_request_payload(subjects=subjects, **overrides),
        TEST_USERS["officer_headers"],
    )
    return get_success_data(resp)


def scan_fincen_request(request_id: str) -> dict:
    resp = api_client.scan_fincen_request(request_id, TEST_USERS["officer_headers"])
    return get_success_data(resp)


def list_matches_for_request(request_id: str) -> list:
    resp = api_client.list_matches(
        TEST_USERS["officer_headers"], params={"request_id": request_id}
    )
    data, _meta = validate_paginated(resp)
    return data


def setup_scanned_314a_match(
    subject_name: Optional[str] = None,
    subject_tax_id: Optional[str] = None,
    subject_dob: Optional[str] = None,
    confirmed: bool = False,
    **account_kwargs,
) -> dict:
    """OPEN account whose customer matches a scanned 314(a) subject.

    Defaults to a TAX_ID_EXACT match on the customer's tax_id. Returns context with
    account, request, and match (PENDING_REVIEW or CONFIRMED).
    """
    ctx = setup_open_account(**account_kwargs)
    customer = ctx["customer"]
    subject = {"name": subject_name or customer["full_name"], "subject_type": "INDIVIDUAL"}
    subject["tax_id"] = subject_tax_id if subject_tax_id is not None else customer["tax_id"]
    if subject_dob is not None:
        subject["date_of_birth"] = subject_dob
    request = create_fincen_request(subjects=[subject])
    scan_fincen_request(request["id"])
    matches = list_matches_for_request(request["id"])
    assert len(matches) == 1, f"Setup failed: expected 1 match, got {len(matches)}"
    match = matches[0]
    if confirmed:
        resp = api_client.confirm_match(match["id"], TEST_USERS["officer_headers"])
        match = get_success_data(resp)
    ctx["request"] = request
    ctx["match"] = match
    return ctx


# --- Physical certificate deposits --------------------------------------------


def create_deposit(account_id: str, **overrides) -> dict:
    resp = api_client.create_deposit(
        account_id, create_deposit_payload(**overrides), TEST_USERS["ops_headers"]
    )
    return get_success_data(resp)


def advance_deposit(deposit_id: str) -> dict:
    resp = api_client.advance_deposit(deposit_id, TEST_USERS["ops_headers"])
    return get_success_data(resp)


def get_deposit(deposit_id: str) -> dict:
    resp = api_client.get_deposit(deposit_id, TEST_USERS["ops_headers"])
    return get_success_data(resp)


def setup_deposit_in_clearance_hold(account_id: Optional[str] = None, **deposit_overrides) -> dict:
    """OPEN LOW account + deposit advanced RECEIVED -> ELIGIBILITY_REVIEW ->
    AUTHENTICITY_REVIEW -> CLEARANCE_HOLD (hold_release_date set on entry)."""
    if account_id is None:
        ctx = setup_open_account()
        account_id = ctx["account"]["id"]
    else:
        ctx = {"account": get_account(account_id)}
    deposit = create_deposit(account_id, **deposit_overrides)
    deposit = advance_deposit(deposit["id"])
    deposit = advance_deposit(deposit["id"])
    deposit = advance_deposit(deposit["id"])
    ctx["deposit"] = deposit
    return ctx


def setup_ready_deposit(release_clock: str = "2026-05-06T00:00:00Z", **deposit_overrides) -> dict:
    """Deposit in CLEARANCE_HOLD at CLOCK_START released to READY_TO_ACCEPT by a
    sweep at release_clock (default covers the regular 5-day hold)."""
    ctx = setup_deposit_in_clearance_hold(**deposit_overrides)
    set_clock(release_clock)
    run_daily_sweep()
    ctx["deposit"] = get_deposit(ctx["deposit"]["id"])
    assert ctx["deposit"]["status"] == "READY_TO_ACCEPT", (
        f"Setup failed: deposit is {ctx['deposit']['status']}, expected READY_TO_ACCEPT"
    )
    return ctx


def report_lost_stolen(**overrides) -> dict:
    resp = api_client.create_lost_stolen_entry(
        create_lost_stolen_payload(**overrides), TEST_USERS["admin_headers"]
    )
    return get_success_data(resp)


# --- EDD reviews ---------------------------------------------------------------


def create_edd_review(account_id: str, **overrides) -> dict:
    resp = api_client.create_edd_review(
        account_id, create_edd_review_payload(**overrides), TEST_USERS["analyst_headers"]
    )
    return get_success_data(resp)


def begin_edd_review(review_id: str) -> dict:
    resp = api_client.begin_edd_review(review_id, TEST_USERS["analyst_headers"])
    return get_success_data(resp)


def complete_edd_review(review_id: str, decision: str, notes: str = "review complete") -> dict:
    resp = api_client.complete_edd_review(
        review_id, {"decision": decision, "notes": notes}, TEST_USERS["officer_headers"]
    )
    return get_success_data(resp)


def setup_edd_review_in_review(account_id: str, **overrides) -> dict:
    review = create_edd_review(account_id, **overrides)
    return begin_edd_review(review["id"])


# --- Audit engagements & findings ----------------------------------------------


def create_engagement(auditor_id: str = "auditor-1", **overrides) -> dict:
    from .test_users import make_auditor_headers

    resp = api_client.create_engagement(
        create_engagement_payload(**overrides), make_auditor_headers(auditor_id)
    )
    return get_success_data(resp)


def begin_fieldwork(engagement_id: str, auditor_id: str = "auditor-1") -> dict:
    from .test_users import make_auditor_headers

    resp = api_client.begin_fieldwork(engagement_id, make_auditor_headers(auditor_id))
    return get_success_data(resp)


def issue_report(engagement_id: str, report_summary: str = "report", auditor_id: str = "auditor-1") -> dict:
    from .test_users import make_auditor_headers

    resp = api_client.issue_report(
        engagement_id, {"report_summary": report_summary}, make_auditor_headers(auditor_id)
    )
    return get_success_data(resp)


def create_finding(engagement_id: str, auditor_id: str = "auditor-1", **overrides) -> dict:
    from .test_users import make_auditor_headers

    resp = api_client.create_finding(
        engagement_id, create_finding_payload(**overrides), make_auditor_headers(auditor_id)
    )
    return get_success_data(resp)


def setup_engagement_with_finding(
    severity: str = "MEDIUM",
    engagement_state: str = "FIELDWORK",
    auditor_id: str = "auditor-1",
    **engagement_overrides,
) -> dict:
    """Engagement in FIELDWORK (or REPORTED) with one OPEN finding."""
    set_clock()
    engagement = create_engagement(auditor_id=auditor_id, **engagement_overrides)
    engagement = begin_fieldwork(engagement["id"], auditor_id=auditor_id)
    finding = create_finding(engagement["id"], auditor_id=auditor_id, severity=severity)
    if engagement_state == "REPORTED":
        engagement = issue_report(engagement["id"], auditor_id=auditor_id)
    return {"engagement": engagement, "finding": finding}
