"""Composite setup helpers.

Every helper builds preconditions from scratch using only PRD-declared
endpoints (each test runs against a freshly restarted server with an empty
database and the logical clock at its startup default). Setup calls use
get_success_data so failures surface as clear "Setup failed" errors.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import DEFAULT_RECIPIENT_COPY_DEADLINE, DEFAULT_TAX_YEAR
from .factories import (
    create_b_notice_payload,
    create_merge_request_payload,
    create_payment_payload,
    create_remittance_payload,
    create_state_rule_payload,
    create_tax_year_payload,
    create_transmittal_payload,
    create_vendor_payload,
    create_w9_submission_payload,
)
from .test_users import (
    TEST_USERS,
    make_ap_clerk_headers,
    make_irs_system_headers,
    make_tax_admin_headers,
    make_tax_specialist_headers,
    make_tax_transmitter_headers,
)

CLERK = TEST_USERS["ap_clerk_headers"]
SPEC = TEST_USERS["tax_specialist_headers"]
XMTR = TEST_USERS["tax_transmitter_headers"]
ADMIN = TEST_USERS["tax_admin_headers"]
IRS = TEST_USERS["irs_system_headers"]


def _ok(step, resp):
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 1 — calendar and vendors
# ---------------------------------------------------------------------------

def create_tax_year(headers=None, **overrides):
    """Create an OPEN tax year. Returns the TaxYear resource."""
    resp = api_client.create_tax_year(create_tax_year_payload(**overrides), headers or ADMIN)
    return _ok("create_tax_year", resp)


def create_vendor(headers=None, **overrides):
    """Onboard a vendor (ACTIVE, NOT_SUBMITTED). Returns the Vendor resource."""
    resp = api_client.create_vendor(create_vendor_payload(**overrides), headers or CLERK)
    return _ok("create_vendor", resp)


def submit_w9(vendor_id, headers=None, **overrides):
    """Submit a W-9 for a vendor; vendor moves to PENDING_MATCH."""
    resp = api_client.create_w9_submission(
        vendor_id, create_w9_submission_payload(**overrides), headers or CLERK
    )
    return _ok("submit_w9", resp)


def record_match(submission_id, match_result="MATCHED", mismatch_reason_code=None, headers=None):
    """IRS feed: record a MATCHED/MISMATCHED result for a PENDING submission."""
    payload = {"match_result": match_result}
    if mismatch_reason_code is not None:
        payload["mismatch_reason_code"] = mismatch_reason_code
    resp = api_client.record_match_result(submission_id, payload, headers or IRS)
    return _ok("record_match", resp)


def create_matched_vendor(tin="123456789", tin_type="SSN", classification=None,
                          headers=None, **vendor_overrides):
    """Vendor + W-9 + MATCHED result. Returns (vendor, w9_submission)."""
    classification = classification or vendor_overrides.pop(
        "entity_classification", "INDIVIDUAL_SOLE_PROP"
    )
    vendor = create_vendor(headers=headers, entity_classification=classification, **vendor_overrides)
    w9 = submit_w9(
        vendor["id"], headers=headers,
        submitted_legal_name=vendor.get("legal_name", "Test Vendor"),
        submitted_tin=tin, submitted_tin_type=tin_type,
    )
    record_match(w9["id"], "MATCHED")
    vendor = _ok("re-read vendor", api_client.get_vendor(vendor["id"], headers or CLERK))
    return vendor, w9


def create_mismatched_vendor(tin="123456789", tin_type="SSN", reason_code="IRS_CODE_1",
                             classification=None, headers=None,
                             **vendor_overrides):
    """Vendor + W-9 + MISMATCHED result (backup_withholding_flag true).

    The TIN is also supplied at onboarding so the vendor retains a non-null tin
    after the mismatch (a MISMATCHED result never populates tin by itself).
    Returns (vendor, w9_submission)."""
    classification = classification or vendor_overrides.pop(
        "entity_classification", "INDIVIDUAL_SOLE_PROP"
    )
    vendor = create_vendor(
        headers=headers, entity_classification=classification,
        tin=tin, tin_type=tin_type, **vendor_overrides,
    )
    w9 = submit_w9(
        vendor["id"], headers=headers,
        submitted_legal_name=vendor.get("legal_name", "Test Vendor"),
        submitted_tin=tin, submitted_tin_type=tin_type,
    )
    record_match(w9["id"], "MISMATCHED", mismatch_reason_code=reason_code)
    vendor = _ok("re-read vendor", api_client.get_vendor(vendor["id"], headers or CLERK))
    return vendor, w9


# ---------------------------------------------------------------------------
# Tier 2 — payments and ledger
# ---------------------------------------------------------------------------

def create_payment(vendor_id, amount_cents=100000, payment_date="2025-06-01T00:00:00Z",
                   payment_type="SERVICE", source_system="AP_ERP", headers=None, **overrides):
    """Record a payment. Returns the Payment resource."""
    resp = api_client.create_payment(
        create_payment_payload(
            vendor_id=vendor_id, amount_cents=amount_cents, payment_date=payment_date,
            payment_type=payment_type, source_system=source_system, **overrides,
        ),
        headers or CLERK,
    )
    return _ok("create_payment", resp)


def list_withholding_entries(headers=None, **params):
    resp = api_client.list_withholding_entries(headers or SPEC, params=params)
    return _ok("list_withholding_entries", resp)


def get_vendor(vendor_id, headers=None):
    return _ok("get_vendor", api_client.get_vendor(vendor_id, headers or CLERK))


# ---------------------------------------------------------------------------
# Tier 3 — returns lifecycle
# ---------------------------------------------------------------------------

def generate_returns(tax_year=DEFAULT_TAX_YEAR, headers=None):
    """Bulk-generate returns; returns {generated_count, generated_return_ids, skipped_count}."""
    resp = api_client.generate_returns({"tax_year": tax_year}, headers or SPEC)
    return _ok("generate_returns", resp)


def list_returns(headers=None, **params):
    resp = api_client.list_returns(headers or SPEC, params=params)
    return _ok("list_returns", resp)


def get_single_return(vendor_id, tax_year=None, form_type=None, headers=None):
    """Fetch exactly one return via list filters; asserts uniqueness."""
    params = {"vendor_id": vendor_id}
    if tax_year is not None:
        params["tax_year"] = tax_year
    if form_type is not None:
        params["form_type"] = form_type
    resp = api_client.list_returns(headers or SPEC, params=params)
    body = resp.json()
    data = body["data"]
    assert len(data) == 1, f"expected exactly one return for {params}, got {len(data)}"
    return data[0]


def create_validated_return(tin=None, amount_cents=100000, payment_date="2025-06-01T00:00:00Z",
                            payment_type="SERVICE", classification=None,
                            tax_year=DEFAULT_TAX_YEAR, form_type=None, mismatched=False,
                            **vendor_overrides):
    """Full chain: vendor (MATCHED or MISMATCHED) + payment + generate + validate.
    Returns (vendor, payment, tax_return)."""
    if mismatched:
        vendor, _w9 = create_mismatched_vendor(
            tin=tin or "123456789", classification=classification, **vendor_overrides
        )
    else:
        vendor, _w9 = create_matched_vendor(
            tin=tin or "123456789", classification=classification, **vendor_overrides
        )
    payment = create_payment(vendor["id"], amount_cents=amount_cents,
                             payment_date=payment_date, payment_type=payment_type)
    generate_returns(tax_year)
    tax_return = get_single_return(vendor["id"], tax_year=tax_year, form_type=form_type)
    resp = api_client.validate_return(tax_return["id"], SPEC)
    tax_return = _ok("validate_return", resp)
    return vendor, payment, tax_return


def create_accepted_return(tin=None, amount_cents=100000, payment_date="2025-06-01T00:00:00Z",
                           payment_type="SERVICE", classification=None,
                           tax_year=DEFAULT_TAX_YEAR, form_type="NEC", channel="PAPER",
                           sealer_id="spec-seal-1", submitter_id="xmtr-sub-1",
                           **vendor_overrides):
    """Full lifecycle through transmittal ACCEPTED. Default e-file threshold (10)
    keeps PAPER legal at small counts. Returns (vendor, payment, tax_return, transmittal)."""
    vendor, payment, tax_return = create_validated_return(
        tin=tin, amount_cents=amount_cents, payment_date=payment_date,
        payment_type=payment_type, classification=classification,
        tax_year=tax_year, form_type=form_type, **vendor_overrides,
    )
    transmittal = _ok(
        "create_transmittal",
        api_client.create_transmittal(
            create_transmittal_payload(tax_year=tax_year, form_type=tax_return["form_type"]), SPEC
        ),
    )
    sealed = _ok(
        "seal_transmittal",
        api_client.seal_transmittal(transmittal["id"], make_tax_specialist_headers(sealer_id)),
    )
    submitted = _ok(
        "submit_transmittal",
        api_client.submit_transmittal(
            sealed["id"], {"channel": channel}, make_tax_transmitter_headers(submitter_id)
        ),
    )
    _ok(
        "record_transmittal_outcome",
        api_client.record_transmittal_outcome(submitted["id"], {"outcome": "ACCEPTED"}, IRS),
    )
    tax_return = _ok("re-read return", api_client.get_return(tax_return["id"], SPEC))
    transmittal = _ok(
        "re-read transmittal", api_client.get_transmittal(submitted["id"], SPEC)
    )
    return vendor, payment, tax_return, transmittal


# ---------------------------------------------------------------------------
# Tier 4 — remittances
# ---------------------------------------------------------------------------

def create_draft_remittance(tax_year=DEFAULT_TAX_YEAR, quarter=1, creator_id="spec-rem-1"):
    """Draft a remittance as a TaxSpecialist with a steerable user id (SoD-relevant)."""
    resp = api_client.create_remittance(
        create_remittance_payload(tax_year=tax_year, quarter=quarter),
        make_tax_specialist_headers(creator_id),
    )
    return _ok("create_draft_remittance", resp)


def submit_remittance(remittance_id, submitter_id="xmtr-rem-1"):
    resp = api_client.submit_remittance(
        remittance_id, make_tax_transmitter_headers(submitter_id)
    )
    return _ok("submit_remittance", resp)


def setup_withheld_payment(tax_year=DEFAULT_TAX_YEAR, amount_cents=100000,
                           payment_date="2025-02-10T00:00:00Z", tin=None,
                           **vendor_overrides):
    """Tax year + MISMATCHED vendor + one withheld payment.
    Returns (tax_year_row, vendor, payment)."""
    year = create_tax_year(tax_year=tax_year)
    vendor, _w9 = create_mismatched_vendor(tin=tin or "123456789", **vendor_overrides)
    payment = create_payment(vendor["id"], amount_cents=amount_cents, payment_date=payment_date)
    return year, vendor, payment


# ---------------------------------------------------------------------------
# Tier 5 — B-notices, state rules, merges
# ---------------------------------------------------------------------------

def create_b_notice(vendor_id, notice_year=DEFAULT_TAX_YEAR, headers=None):
    resp = api_client.create_b_notice(
        create_b_notice_payload(vendor_id=vendor_id, notice_year=notice_year), headers or IRS
    )
    return _ok("create_b_notice", resp)


def setup_vendor_with_first_and_second_notice(tin="121212121", first_year=2024, second_year=2025,
                                              **vendor_overrides):
    """Vendor carrying an OPEN FIRST notice and an OPEN SECOND notice.
    Returns (vendor, first_notice, second_notice)."""
    vendor = create_vendor(**vendor_overrides)
    first = create_b_notice(vendor["id"], notice_year=first_year)
    second = create_b_notice(vendor["id"], notice_year=second_year)
    return vendor, first, second


def create_state_rule(headers=None, **overrides):
    resp = api_client.create_state_rule(create_state_rule_payload(**overrides), headers or ADMIN)
    return _ok("create_state_rule", resp)


def create_merge_request(source_vendor_id, target_vendor_id, reason="duplicate vendor record",
                         requester_id="clerk-req-1"):
    """Open a PENDING merge request as an APClerk with a steerable user id."""
    resp = api_client.create_merge_request(
        create_merge_request_payload(
            source_vendor_id=source_vendor_id, target_vendor_id=target_vendor_id, reason=reason
        ),
        make_ap_clerk_headers(requester_id),
    )
    return _ok("create_merge_request", resp)


def create_mergeable_pair(tin="123456789", requester_id="clerk-req-1"):
    """Two ACTIVE, MATCHED vendors sharing one TIN, plus a PENDING merge request
    (source -> target). Returns (source, target, merge_request)."""
    source, _w1 = create_matched_vendor(tin=tin, legal_name="Merge Source")
    target, _w2 = create_matched_vendor(tin=tin, legal_name="Merge Target")
    merge_request = create_merge_request(source["id"], target["id"], requester_id=requester_id)
    return source, target, merge_request


def approve_merge(request_id, approver_id="admin-app-1"):
    resp = api_client.approve_merge_request(request_id, make_tax_admin_headers(approver_id))
    return _ok("approve_merge", resp)


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

def set_clock(to_iso8601, headers=None):
    resp = api_client.set_clock({"to_iso8601": to_iso8601}, headers or ADMIN)
    return _ok("set_clock", resp)
