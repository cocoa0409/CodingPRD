"""Composite setup helpers.

Every test starts against an empty database (the harness restarts the server
before each test), so these helpers build complete precondition chains out of
PRD-declared endpoints only. All helpers use get_success_data() so a setup
failure raises a clear "Setup step failed" error instead of a confusing
assertion failure inside a test.

OCC discipline: any write that carries expected_tax_year_version (valuation
allowance create, filing file) is always preceded by a fresh GET of the
TaxYear, so the helpers never depend on which intermediate recomputes bump
the year's version.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_audit_payload,
    create_difference_payload,
    create_estimated_payment_payload,
    create_filing_payload,
    create_generate_schedule_payload,
    create_jurisdiction_payload,
    create_notice_payload,
    create_tax_year_payload,
    create_utp_payload,
    create_valuation_allowance_payload,
)
from .test_users import (
    TEST_USERS,
    make_tax_accountant_headers,
    make_tax_director_headers,
    make_tax_manager_headers,
)

ACCT = TEST_USERS["tax_accountant_headers"]
MGR = TEST_USERS["tax_manager_headers"]
DIR = TEST_USERS["tax_director_headers"]
AUD = TEST_USERS["auditor_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]

DEFAULT_DUE_DATE = "2027-04-15"


# ---------------------------------------------------------------------------
# Tier 0: clock + single-resource creation
# ---------------------------------------------------------------------------

def set_logical_clock(to_iso8601: str) -> dict:
    """Advance the logical clock; returns the clock response data (with the
    late_payment_ids / overdue_notice_ids / lapsed_position_ids lists)."""
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


def create_fy2026_tax_year(**overrides) -> dict:
    """Create the canonical FY2026 TaxYear (OPEN). Returns the year."""
    return get_success_data(
        api_client.create_tax_year(create_tax_year_payload(**overrides), MGR))


def create_jurisdiction_record(**overrides) -> dict:
    """Create a jurisdiction; defaults to US-FED (2100 bp, 100% apportionment)."""
    return get_success_data(
        api_client.create_jurisdiction(create_jurisdiction_payload(**overrides),
                                       MGR))


def create_us_fed_jurisdiction() -> dict:
    return create_jurisdiction_record()


def create_us_ca_jurisdiction() -> dict:
    return create_jurisdiction_record(
        code="US-CA", name="California", level="STATE", statutory_rate_bp=884,
        apportionment_pct_bp=2500, return_due_month=4, return_due_day=15,
        extension_months=7)


def create_us_il_jurisdiction() -> dict:
    return create_jurisdiction_record(
        code="US-IL", name="Illinois", level="STATE", statutory_rate_bp=883,
        apportionment_pct_bp=2503, return_due_month=4, return_due_day=15,
        extension_months=6)


def create_us_ny_jurisdiction() -> dict:
    return create_jurisdiction_record(
        code="US-NY", name="New York", level="STATE", statutory_rate_bp=883,
        apportionment_pct_bp=2503, return_due_month=4, return_due_day=15,
        extension_months=6)


def setup_open_year_with_jurisdiction(jurisdiction_factory=None):
    """FY2026 TaxYear (OPEN) + one jurisdiction. Returns (tax_year, jurisdiction)."""
    ty = create_fy2026_tax_year()
    jur = (jurisdiction_factory or create_us_fed_jurisdiction)()
    return ty, jur


def get_tax_year(tax_year_id: str) -> dict:
    return get_success_data(api_client.get_tax_year(tax_year_id, AUD))


def current_tax_year_version(tax_year_id: str) -> int:
    """Fresh OCC read of the year's version (use immediately before any
    expected_tax_year_version-carrying write)."""
    return get_tax_year(tax_year_id)["version"]


# ---------------------------------------------------------------------------
# Tier 1: book-tax differences and the deferred rollforward
# ---------------------------------------------------------------------------

def create_difference(tax_year_id, jurisdiction_id=None,
                      book_amount_cents=5000000, tax_amount_cents=2000000,
                      difference_type="TEMPORARY", description="accrued warranty",
                      creator_user_id="acct-1") -> dict:
    """Create a BookTaxDifference (lands IDENTIFIED)."""
    payload = create_difference_payload(
        tax_year_id, jurisdiction_id=jurisdiction_id,
        description=description, book_amount_cents=book_amount_cents,
        tax_amount_cents=tax_amount_cents, difference_type=difference_type)
    return get_success_data(api_client.create_book_tax_difference(
        payload, make_tax_accountant_headers(creator_user_id)))


def create_reviewed_difference(tax_year_id, jurisdiction_id=None,
                               reviewer_user_id="mgr-1", **kwargs) -> dict:
    """Create + review (IDENTIFIED -> REVIEWED)."""
    diff = create_difference(tax_year_id, jurisdiction_id=jurisdiction_id,
                             **kwargs)
    return get_success_data(api_client.review_difference(
        diff["id"], make_tax_manager_headers(reviewer_user_id)))


def create_locked_difference(tax_year_id, jurisdiction_id=None,
                             locker_user_id="mgr-1", **kwargs) -> dict:
    """Create + review + lock (fires the deferred-tax cascade)."""
    diff = create_reviewed_difference(tax_year_id,
                                      jurisdiction_id=jurisdiction_id,
                                      **kwargs)
    return get_success_data(api_client.lock_difference(
        diff["id"], make_tax_manager_headers(locker_user_id)))


def list_deferred_items(params=None) -> list:
    return get_success_data(api_client.list_deferred_tax_items(AUD,
                                                               params=params))


# ---------------------------------------------------------------------------
# Tier 2: valuation allowances
# ---------------------------------------------------------------------------

def create_draft_allowance(tax_year_id, more_likely_than_not=False,
                           projected_taxable_income_cents=0,
                           reversing_dtl_cents=0, preparer_user_id="mgr-1",
                           expected_tax_year_version=None,
                           assessment_note=None) -> dict:
    """Create a DRAFT valuation allowance. When expected_tax_year_version is
    omitted, a fresh version is read from the year first (OCC)."""
    if expected_tax_year_version is None:
        expected_tax_year_version = current_tax_year_version(tax_year_id)
    payload = create_valuation_allowance_payload(
        tax_year_id, expected_tax_year_version,
        more_likely_than_not=more_likely_than_not,
        projected_taxable_income_cents=projected_taxable_income_cents,
        reversing_dtl_cents=reversing_dtl_cents,
        assessment_note=assessment_note)
    return get_success_data(api_client.create_valuation_allowance(
        payload, make_tax_manager_headers(preparer_user_id)))


def create_submitted_allowance(tax_year_id, preparer_user_id="mgr-1",
                               **kwargs) -> dict:
    """DRAFT -> SUBMITTED."""
    va = create_draft_allowance(tax_year_id, preparer_user_id=preparer_user_id,
                                **kwargs)
    return get_success_data(api_client.submit_valuation_allowance(
        va["id"], make_tax_manager_headers(preparer_user_id)))


def create_approved_allowance(tax_year_id, preparer_user_id="mgr-1",
                              approver_user_id="dir-1", **kwargs) -> dict:
    """DRAFT -> SUBMITTED -> APPROVED (approver differs from preparer)."""
    va = create_submitted_allowance(tax_year_id,
                                    preparer_user_id=preparer_user_id,
                                    **kwargs)
    return get_success_data(api_client.approve_valuation_allowance(
        va["id"], make_tax_director_headers(approver_user_id)))


def approve_zero_allowance(tax_year_id) -> dict:
    """Convenience: approve an mltn=false zero-evidence allowance (amount 0
    on an empty DTA pool) — the standard unblocker for lock-provision."""
    return create_approved_allowance(tax_year_id, more_likely_than_not=False,
                                     projected_taxable_income_cents=0,
                                     reversing_dtl_cents=0)


# ---------------------------------------------------------------------------
# Tier 3: filings and the provision-locked year
# ---------------------------------------------------------------------------

def create_filing_record(tax_year_id, jurisdiction_id,
                         original_due_date=DEFAULT_DUE_DATE,
                         creator_user_id="acct-1") -> dict:
    """Open a filing slot (PENDING, extension_status NONE)."""
    return get_success_data(api_client.create_filing(
        create_filing_payload(tax_year_id, jurisdiction_id,
                              original_due_date=original_due_date),
        make_tax_accountant_headers(creator_user_id)))


def mark_filing_ready_with_liability(filing_id, return_tax_liability_cents,
                                     user_id="acct-1") -> dict:
    return get_success_data(api_client.mark_filing_ready(
        filing_id, return_tax_liability_cents,
        make_tax_accountant_headers(user_id)))


def file_ready_filing(filing_id, tax_year_id, director_user_id="dir-1") -> dict:
    """READY -> FILED with a fresh OCC version read."""
    version = current_tax_year_version(tax_year_id)
    return get_success_data(api_client.file_filing(
        filing_id, version, make_tax_director_headers(director_user_id)))


def setup_locked_year_with_filing(mark_ready_liability=None,
                                  original_due_date=DEFAULT_DUE_DATE) -> dict:
    """FY2026 + US-FED jurisdiction + one FED filing + approved zero allowance,
    provision locked. When mark_ready_liability is given, the filing is also
    marked READY with that liability. Returns a dict of all artifacts."""
    ty = create_fy2026_tax_year()
    jur = create_us_fed_jurisdiction()
    filing = create_filing_record(ty["id"], jur["id"],
                                  original_due_date=original_due_date)
    va = approve_zero_allowance(ty["id"])
    ty = get_success_data(api_client.lock_provision(ty["id"], DIR))
    if mark_ready_liability is not None:
        filing = mark_filing_ready_with_liability(filing["id"],
                                                  mark_ready_liability)
    return {"tax_year": ty, "jurisdiction": jur, "filing": filing,
            "allowance": va}


# ---------------------------------------------------------------------------
# Tier 4: estimated payment schedules
# ---------------------------------------------------------------------------

def generate_sorted_schedule(tax_year_id, jurisdiction_id,
                             method="CURRENT_YEAR_ANNUALIZED") -> list:
    """Generate the four-quarter schedule; returns the payments sorted by
    quarter_index ascending."""
    data = get_success_data(api_client.generate_payment_schedule(
        create_generate_schedule_payload(tax_year_id, jurisdiction_id,
                                         method=method), MGR))
    assert isinstance(data, list) and len(data) == 4, \
        f"generate-schedule must return four quarters, got {data!r}"
    return sorted(data, key=lambda p: p["quarter_index"])


def setup_year_with_annualized_schedule():
    """FY2026 + US-IL (883 bp, 2503 bp apportionment) + annualized schedule
    (Q1 552,537 / Q2 552,538 / Q3 552,537 / Q4 552,537).
    Returns (tax_year, jurisdiction, payments)."""
    ty = create_fy2026_tax_year()
    jur = create_us_il_jurisdiction()
    payments = generate_sorted_schedule(ty["id"], jur["id"],
                                        method="CURRENT_YEAR_ANNUALIZED")
    return ty, jur, payments


def get_estimated_payment(payment_id) -> dict:
    return get_success_data(api_client.get_estimated_payment(payment_id, AUD))


# ---------------------------------------------------------------------------
# Tier 5: uncertain tax positions
# ---------------------------------------------------------------------------

def create_position(tax_year_id, jurisdiction_id,
                    position_amount_cents=1000000,
                    description="transfer pricing",
                    creator_user_id="acct-1") -> dict:
    """Identify a UTP (lands IDENTIFIED)."""
    return get_success_data(api_client.create_uncertain_tax_position(
        create_utp_payload(tax_year_id, jurisdiction_id,
                           description=description,
                           position_amount_cents=position_amount_cents),
        make_tax_accountant_headers(creator_user_id)))


def create_measured_position(tax_year_id, jurisdiction_id,
                             position_amount_cents=1000000,
                             cumulative_probability_bp=4000,
                             description="transfer pricing") -> dict:
    """Identify + measure a UTP (lands MEASURED)."""
    utp = create_position(tax_year_id, jurisdiction_id,
                          position_amount_cents=position_amount_cents,
                          description=description)
    return get_success_data(api_client.measure_position(
        utp["id"], cumulative_probability_bp, MGR))


def setup_locked_year_ready_filing_and_disclosed_utp(
        return_liability=21000000, position_amount_cents=1000000,
        cumulative_probability_bp=4000) -> dict:
    """PROVISION_LOCKED year + FED filing READY + a measured, disclosed UTP
    (liability fully reserved at the default sub-threshold probability).
    Returns a dict of all artifacts."""
    scenario = setup_locked_year_with_filing(
        mark_ready_liability=return_liability)
    ty = scenario["tax_year"]
    jur = scenario["jurisdiction"]
    utp = create_measured_position(ty["id"], jur["id"],
                                   position_amount_cents=position_amount_cents,
                                   cumulative_probability_bp=
                                   cumulative_probability_bp)
    utp = get_success_data(api_client.disclose_position(utp["id"], MGR))
    scenario["position"] = utp
    return scenario


# ---------------------------------------------------------------------------
# Tier 6: notices and audits
# ---------------------------------------------------------------------------

def create_notice_record(jurisdiction_id, audit_case_id=None,
                         notice_type="INFORMATION_REQUEST",
                         received_on="2026-01-10", response_due_on="2026-02-09",
                         creator_user_id="acct-1") -> dict:
    return get_success_data(api_client.create_notice(
        create_notice_payload(jurisdiction_id, audit_case_id=audit_case_id,
                              notice_type=notice_type, received_on=received_on,
                              response_due_on=response_due_on),
        make_tax_accountant_headers(creator_user_id)))


def create_audit_record(tax_year_id, jurisdiction_id,
                        exam_period_start="2026-01-01",
                        exam_period_end="2027-01-01") -> dict:
    return get_success_data(api_client.create_audit(
        create_audit_payload(tax_year_id, jurisdiction_id,
                             exam_period_start=exam_period_start,
                             exam_period_end=exam_period_end), MGR))


# ---------------------------------------------------------------------------
# Tier 7: full-scenario composites (multi-artifact provision states)
# ---------------------------------------------------------------------------

def setup_dual_variant_etr_scenario() -> dict:
    """The full provision scenario behind the ETR dual-variant checks:

    FY2026 (book 100,000,000; prior 8,000,000; federal rate 2100 bp) with
    US-FED + US-CA; a LOCKED PERMANENT difference +2,000,000 and a LOCKED
    TEMPORARY difference +3,000,000 (DTA 630,000); an APPROVED mltn=true
    allowance of 320,000; UTP1 2,000,000 @6000 bp (fully recognized) and
    UTP2 1,000,000 @4000 bp (liability 1,000,000, disclosed so the FED file
    gate passes); provision locked; FED filed at 20,800,000 and CA filed at
    2,300,000.

    Post-state: current_provision 23,200,818; forecast_etr_bp 2389;
    actual_etr_bp 2279; return_to_provision_adjustment_cents -100,818.
    """
    set_logical_clock("2026-01-05T00:00:00Z")
    ty = create_fy2026_tax_year()
    jur_fed = create_us_fed_jurisdiction()
    jur_ca = create_us_ca_jurisdiction()

    diff_perm = create_difference(
        ty["id"], jur_fed["id"], book_amount_cents=2000000,
        tax_amount_cents=0, difference_type="PERMANENT",
        description="meals 50pct limitation")
    get_success_data(api_client.review_difference(diff_perm["id"], MGR))

    diff_temp = create_difference(ty["id"], jur_fed["id"])
    get_success_data(api_client.review_difference(diff_temp["id"], MGR))

    fil_fed = create_filing_record(ty["id"], jur_fed["id"])
    fil_ca = create_filing_record(ty["id"], jur_ca["id"])

    get_success_data(api_client.lock_difference(diff_perm["id"], MGR))
    get_success_data(api_client.lock_difference(diff_temp["id"], MGR))

    va = create_approved_allowance(
        ty["id"], more_likely_than_not=True,
        projected_taxable_income_cents=1000000, reversing_dtl_cents=100000)

    utp1 = create_measured_position(ty["id"], jur_fed["id"],
                                    position_amount_cents=2000000,
                                    cumulative_probability_bp=6000,
                                    description="R&D credit")
    utp2 = create_measured_position(ty["id"], jur_fed["id"],
                                    position_amount_cents=1000000,
                                    cumulative_probability_bp=4000)

    ty = get_success_data(api_client.lock_provision(ty["id"], DIR))

    fil_fed = mark_filing_ready_with_liability(fil_fed["id"], 20800000)
    fil_ca = mark_filing_ready_with_liability(fil_ca["id"], 2300000)

    # Disclose the sub-threshold position so the FED file gate passes
    # (disclosure requires a READY/FILED/ACCEPTED filing for the pair).
    utp2 = get_success_data(api_client.disclose_position(utp2["id"], MGR))

    fil_fed = file_ready_filing(fil_fed["id"], ty["id"])
    fil_ca = file_ready_filing(fil_ca["id"], ty["id"])

    return {"tax_year": ty, "jur_fed": jur_fed, "jur_ca": jur_ca,
            "diff_perm": diff_perm, "diff_temp": diff_temp,
            "fil_fed": fil_fed, "fil_ca": fil_ca, "allowance": va,
            "utp1": utp1, "utp2": utp2}


def setup_rtp_respread_scenario() -> dict:
    """Provision-locked FY2026 with FED + CA filings behind the RTP re-spread
    checks: LOCKED PERMANENT +2,000,000; CA annualized schedule (4 x 552,500)
    with quarter 1 PAID in full; FED filed at 20,800,000 (delta -146,618, no
    FED payments to re-spread); CA ready at 2,300,000 and then filed (delta
    +45,800 spread across the three remaining SCHEDULED quarters).
    """
    set_logical_clock("2026-01-05T00:00:00Z")
    ty = create_fy2026_tax_year()
    jur_fed = create_us_fed_jurisdiction()
    jur_ca = create_us_ca_jurisdiction()

    diff_perm = create_difference(
        ty["id"], jur_fed["id"], book_amount_cents=2000000,
        tax_amount_cents=0, difference_type="PERMANENT",
        description="meals 50pct limitation")
    get_success_data(api_client.review_difference(diff_perm["id"], MGR))
    get_success_data(api_client.lock_difference(diff_perm["id"], MGR))

    fil_fed = create_filing_record(ty["id"], jur_fed["id"])
    fil_ca = create_filing_record(ty["id"], jur_ca["id"])

    approve_zero_allowance(ty["id"])
    ty = get_success_data(api_client.lock_provision(ty["id"], DIR))

    ca_payments = generate_sorted_schedule(ty["id"], jur_ca["id"],
                                           method="CURRENT_YEAR_ANNUALIZED")
    # Pay quarter 1 in full (552,500) so it is never re-spread.
    get_success_data(api_client.record_payment(
        ca_payments[0]["id"], ca_payments[0]["scheduled_amount_cents"], ACCT))

    fil_fed = mark_filing_ready_with_liability(fil_fed["id"], 20800000)
    fil_ca = mark_filing_ready_with_liability(fil_ca["id"], 2300000)

    fil_fed = file_ready_filing(fil_fed["id"], ty["id"])
    fil_ca = file_ready_filing(fil_ca["id"], ty["id"])

    return {"tax_year": ty, "jur_fed": jur_fed, "jur_ca": jur_ca,
            "fil_fed": fil_fed, "fil_ca": fil_ca,
            "ca_payment_ids": [p["id"] for p in ca_payments],
            "ca_base_amounts": [p["scheduled_amount_cents"]
                                for p in ca_payments]}
