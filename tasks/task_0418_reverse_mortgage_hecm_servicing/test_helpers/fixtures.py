"""Composite setup helpers.

Encapsulates the multi-step API sequences that most tests need to reach a
specific system state. Every test starts against an empty database (the runner
restarts the server before each test), so every fixture builds its preconditions
from scratch using only PRD-declared endpoints.

Fixtures use get_success_data() (lenient) internally so setup failures surface as
clear "Setup failed" errors rather than confusing assertion failures.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import (
    TEST_USERS,
    make_borrower_headers,
)
from .factories import (
    create_lender_payload,
    create_plf_payload,
    set_clock_payload,
    create_borrower_payload,
    create_loan_payload,
    create_disbursement_payload,
    approve_disbursement_payload,
    create_lesa_payload,
    create_property_charge_payment_payload,
    create_occupancy_certification_payload,
    create_maturity_event_payload,
    create_nbs_deferral_payload,
    create_resolution_payload,
)
from .constants import (
    DEFAULT_CLOCK_ISO,
    DEFAULT_BORROWER_BIRTHDATE,
)

_SO = TEST_USERS["servicer_ops_headers"]
_CO = TEST_USERS["compliance_officer_headers"]


# ---------------------------------------------------------------------------
# Tier 0: low-level scaffolding
# ---------------------------------------------------------------------------
def create_lender(**overrides) -> dict:
    return get_success_data(api_client.create_lender(create_lender_payload(**overrides), _SO))


def create_plf(lender_id, **overrides) -> dict:
    return get_success_data(api_client.create_plf(create_plf_payload(lender_id, **overrides), _SO))


def set_clock(lender_id, to_iso8601=DEFAULT_CLOCK_ISO, headers=None):
    return get_success_data(
        api_client.set_clock(set_clock_payload(lender_id, to_iso8601), headers or _SO)
    )


def create_borrower(lender_id, **overrides) -> dict:
    return get_success_data(api_client.create_borrower(create_borrower_payload(lender_id, **overrides), _SO))


def create_loan(lender_id, borrower_id, **overrides) -> dict:
    return get_success_data(api_client.create_loan(create_loan_payload(lender_id, borrower_id, **overrides), _SO))


def setup_lender_with_plf(plf_overrides=None, clock_iso=DEFAULT_CLOCK_ISO, lender_overrides=None):
    """Lender + one PLF row (age 75 @ 500bps = 523000 by default) + clock set.
    Returns the lender dict."""
    lender = create_lender(**(lender_overrides or {}))
    create_plf(lender["id"], **(plf_overrides or {}))
    set_clock(lender["id"], clock_iso)
    return lender


# ---------------------------------------------------------------------------
# Tier 1/2: pre-origination and originated loans
# ---------------------------------------------------------------------------
def setup_preorigination_loan(loan_overrides=None, borrower_overrides=None,
                              plf_overrides=None, clock_iso=DEFAULT_CLOCK_ISO,
                              lender_overrides=None):
    """Lender + PLF + clock + borrower + a pre-origination loan (not yet
    originated). Returns (lender, borrower, loan)."""
    lender = setup_lender_with_plf(plf_overrides, clock_iso, lender_overrides)
    borrower = create_borrower(lender["id"], **(borrower_overrides or {}))
    loan = create_loan(lender["id"], borrower["id"], **(loan_overrides or {}))
    return lender, borrower, loan


def originate(loan_id):
    return get_success_data(api_client.originate_loan(loan_id, _SO))


def setup_originated_loan(loan_overrides=None, borrower_overrides=None,
                          plf_overrides=None, clock_iso=DEFAULT_CLOCK_ISO,
                          lender_overrides=None):
    """Lender + PLF + clock + borrower + originated loan.
    Returns (lender, borrower, loan) where loan is the originated record."""
    lender, borrower, loan = setup_preorigination_loan(
        loan_overrides, borrower_overrides, plf_overrides, clock_iso, lender_overrides
    )
    loan = originate(loan["id"])
    return lender, borrower, loan


def setup_originated_loc_base_loan():
    """The shared 'LOC base loan' from the difficulty index:
    appraised 30000000, expected_rate 500bps, PLF 523000, initial costs 1000000.
    After origination: gross 15690000, net 14690000, available line 14690000,
    balance 1000000. Returns (lender, borrower, loan)."""
    return setup_originated_loan()


def setup_originated_loan_with_lesa(funding_mode="FULLY_FUNDED",
                                    annual_property_charge_cents=600000,
                                    life_expectancy_years=10,
                                    loan_overrides=None, plf_overrides=None,
                                    clock_iso=DEFAULT_CLOCK_ISO):
    """Lender + PLF + clock + borrower + pre-origination loan + LESA, then
    originate (so the LESA's initial_amount_cents resolves). Returns
    (lender, borrower, loan, lesa)."""
    lender, borrower, loan = setup_preorigination_loan(
        loan_overrides, None, plf_overrides, clock_iso
    )
    lesa = get_success_data(api_client.create_lesa(
        create_lesa_payload(
            loan["id"],
            funding_mode=funding_mode,
            annual_property_charge_cents=annual_property_charge_cents,
            life_expectancy_years=life_expectancy_years,
        ), _SO))
    loan = originate(loan["id"])
    lesa = get_success_data(api_client.get_lesa(lesa["id"], _SO))
    return lender, borrower, loan, lesa


# ---------------------------------------------------------------------------
# Tier 3: disbursement lifecycle shortcuts
# ---------------------------------------------------------------------------
def loan_version(loan_id) -> int:
    return get_success_data(api_client.get_loan(loan_id, _SO))["version"]


def request_disbursement(loan_id, requested_amount_cents=100000, kind="LINE_DRAW",
                         headers=None) -> dict:
    return get_success_data(api_client.create_disbursement(
        create_disbursement_payload(loan_id, kind=kind,
                                    requested_amount_cents=requested_amount_cents),
        headers or _SO))


def request_disbursement_as_borrower(loan_id, borrower_id, requested_amount_cents=100000,
                                     kind="LINE_DRAW") -> dict:
    """Request a draw as the loan's Borrower (entity-backed ownership)."""
    return request_disbursement(loan_id, requested_amount_cents, kind,
                                headers=make_borrower_headers(borrower_id))


def approve_disbursement(disbursement_id, expected_loan_version) -> dict:
    return get_success_data(api_client.approve_disbursement(
        disbursement_id, approve_disbursement_payload(expected_loan_version), _SO))


def disburse(disbursement_id) -> dict:
    return get_success_data(api_client.disburse_disbursement(disbursement_id, _SO))


def setup_disbursed_draw(amount_cents=5000000):
    """Originated LOC base loan with one LINE_DRAW requested, approved, and
    disbursed for `amount_cents`. Returns (lender, borrower, loan, disbursement)."""
    lender, borrower, loan = setup_originated_loc_base_loan()
    v = loan["version"]
    disb = request_disbursement(loan["id"], requested_amount_cents=amount_cents)
    approve_disbursement(disb["id"], v)
    disb = disburse(disb["id"])
    return lender, borrower, loan, disb


# ---------------------------------------------------------------------------
# Tier 4: occupancy certification states
# ---------------------------------------------------------------------------
def open_certification(loan_id, certification_year=1) -> dict:
    return get_success_data(api_client.create_occupancy_certification(
        create_occupancy_certification_payload(loan_id, certification_year), _SO))


def setup_loan_with_pending_cert(certification_year=1):
    """Originated LOC base loan with one PENDING occupancy certification.
    Returns (lender, borrower, loan, cert)."""
    lender, borrower, loan = setup_originated_loc_base_loan()
    cert = open_certification(loan["id"], certification_year)
    return lender, borrower, loan, cert


def setup_loan_with_delinquent_cert():
    """Originated LOC base loan with a cert opened then driven DELINQUENT (so
    Loan.servicing_status == DELINQUENT_OCCUPANCY, disposition_status == ACTIVE).

    The year-1 certification's due_date is the origination anniversary
    (orig 2024-01-01 -> due 2025-01-01). Per PRD §3.7, a certification only
    lapses to DELINQUENT once the lender's clock_utc is strictly later than the
    due_date — whether via the explicit mark-delinquent action or the
    clock-advance sweep. We advance the clock past the due date, which runs the
    §3.1 occupancy sweep and moves the still-PENDING cert to DELINQUENT,
    cascading the loan's servicing axis to DELINQUENT_OCCUPANCY.
    Returns (lender, borrower, loan, cert)."""
    lender, borrower, loan, cert = setup_loan_with_pending_cert()
    set_clock(lender["id"], "2025-02-01T00:00:00.000Z")
    cert = get_success_data(api_client.get_occupancy_certification(cert["id"], _SO))
    loan = get_success_data(api_client.get_loan(loan["id"], _SO))
    return lender, borrower, loan, cert


# ---------------------------------------------------------------------------
# Tier 5: maturity / due-and-payable / deferral / resolution
# ---------------------------------------------------------------------------
def record_maturity_event(loan_id, event_type="PERMANENT_VACANCY", event_date="2024-06-01",
                          headers=None) -> dict:
    return get_success_data(api_client.create_maturity_event(
        create_maturity_event_payload(loan_id, event_type=event_type, event_date=event_date),
        headers or _CO))


def setup_due_and_payable_loan(draw_type="LUMP_SUM", event_type="SALE_OF_PROPERTY",
                               event_date="2024-06-01", loan_overrides=None):
    """Originated loan driven to disposition_status=DUE_AND_PAYABLE by a recorded
    maturity event. Returns (lender, borrower, loan, event)."""
    overrides = {"draw_type": draw_type}
    if loan_overrides:
        overrides.update(loan_overrides)
    lender, borrower, loan = setup_originated_loan(loan_overrides=overrides)
    event = record_maturity_event(loan["id"], event_type=event_type, event_date=event_date)
    loan = get_success_data(api_client.get_loan(loan["id"], _SO))
    return lender, borrower, loan, event


def setup_loan_with_qualified_nbs(draw_type="LUMP_SUM", nbs_qualifies=True,
                                  nbs_birthdate="1955-03-01"):
    """Lender + PLF + clock + borrower-of-record + non-borrowing spouse +
    originated loan that names the NBS. Returns (lender, borrower, nbs, loan)."""
    lender = setup_lender_with_plf()
    borrower = create_borrower(lender["id"])
    nbs = create_borrower(lender["id"], full_name="Test Spouse",
                          birthdate=nbs_birthdate,
                          is_non_borrowing_spouse=True, nbs_qualifies=nbs_qualifies)
    loan = create_loan(lender["id"], borrower["id"],
                       non_borrowing_spouse_id=nbs["id"], draw_type=draw_type)
    loan = originate(loan["id"])
    return lender, borrower, nbs, loan


def setup_deferred_loan(nbs_qualifies=True, event_date="2024-06-01"):
    """A BORROWER_DEATH maturity event drives the loan to DUE_AND_PAYABLE, then an
    NBS deferral moves it to DEFERRED (status ACTIVE). Returns
    (lender, borrower, nbs, loan, event, deferral)."""
    lender, borrower, nbs, loan = setup_loan_with_qualified_nbs(nbs_qualifies=nbs_qualifies)
    event = record_maturity_event(loan["id"], event_type="BORROWER_DEATH", event_date=event_date)
    deferral = get_success_data(api_client.create_nbs_deferral(
        create_nbs_deferral_payload(loan["id"], nbs["id"], event["id"]), _CO))
    loan = get_success_data(api_client.get_loan(loan["id"], _SO))
    return lender, borrower, nbs, loan, event, deferral


def open_resolution(loan_id, path="PAYOFF", **overrides) -> dict:
    return get_success_data(api_client.create_resolution(
        create_resolution_payload(loan_id, path=path, **overrides), _CO))


def setup_settled_resolution(path="PAYOFF", draw_type="LUMP_SUM"):
    """Loan -> DUE_AND_PAYABLE -> IN_RESOLUTION -> SETTLED (terminal).
    Returns (lender, borrower, loan, resolution)."""
    lender, borrower, loan, event = setup_due_and_payable_loan(draw_type=draw_type)
    res = open_resolution(loan["id"], path=path)
    res = get_success_data(api_client.settle_resolution(res["id"], _CO))
    return lender, borrower, loan, res


# ---------------------------------------------------------------------------
# Tier 6: LESA pool / property charge states
# ---------------------------------------------------------------------------
def pay_property_charge(loan_id, lesa_id, amount_cents=100000, charge_type="PROPERTY_TAX",
                        coverage_start="2024-01-01", coverage_end="2025-01-01") -> dict:
    return get_success_data(api_client.create_property_charge_payment(
        create_property_charge_payment_payload(
            loan_id, lesa_id, charge_type=charge_type,
            coverage_start=coverage_start, coverage_end=coverage_end,
            amount_cents=amount_cents), _SO))


def setup_exhausted_lesa():
    """Originated LOC loan with FULLY_FUNDED LESA (initial 6000000) drained by a
    single 6000000 payment so remaining_cents==0, status EXHAUSTED.
    Returns (lender, borrower, loan, lesa)."""
    lender, borrower, loan, lesa = setup_originated_loan_with_lesa()
    pay_property_charge(loan["id"], lesa["id"], amount_cents=6000000)
    lesa = get_success_data(api_client.get_lesa(lesa["id"], _SO))
    return lender, borrower, loan, lesa
