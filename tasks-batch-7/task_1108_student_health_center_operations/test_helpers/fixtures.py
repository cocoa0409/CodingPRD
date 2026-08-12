"""Composite setup helpers for multi-step test prerequisites.

Most PRD claims require the system to be in a specific state that takes
5-15 API calls to reach (a billed sports encounter, a confirmed disease case,
an auto-opened outbreak, ...). These helpers encapsulate those preambles so
tests can focus on assertions. All helpers use get_success_data() so a broken
precondition surfaces as a clear "Setup step failed" error.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_appointment_payload,
    create_health_fee_pool_payload,
    create_immunization_record_payload,
    create_immunization_requirement_payload,
    create_insurance_policy_payload,
    create_invoice_payload,
    create_lab_order_payload,
    create_medication_stock_payload,
    create_on_call_shift_payload,
    create_prescription_payload,
    create_provider_payload,
    create_student_payload,
    result_lab_order_payload,
    set_clock_payload,
)
from .test_users import TEST_USERS, make_clinician_headers

_ADMIN = TEST_USERS["health_admin_headers"]
_FRONT_DESK = TEST_USERS["front_desk_headers"]
_NURSE = TEST_USERS["nurse_headers"]
_CLINICIAN = TEST_USERS["clinician_headers"]
_PHARMACIST = TEST_USERS["pharmacist_headers"]
_BILLING = TEST_USERS["billing_officer_headers"]


# ---------------------------------------------------------------------------
# Tier 0: atomic creators
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str):
    """Set the logical clock (PRD §2.4) and run the deterministic sweep."""
    return get_success_data(api_client.set_clock(set_clock_payload(to_iso8601), _ADMIN))


def make_student(external_ref: str, full_name: str = "Test Student",
                 enrollment_status: str = None) -> dict:
    """Register a student (PRD §3.1). Returns the created Student."""
    overrides = {}
    if enrollment_status is not None:
        overrides["enrollment_status"] = enrollment_status
    return get_success_data(api_client.create_student(
        create_student_payload(external_ref=external_ref, full_name=full_name, **overrides),
        _ADMIN,
    ))


def make_provider(full_name: str = "Dr Test", provider_type: str = "CLINICIAN") -> dict:
    """Register a provider (PRD §3.9). Returns the created Provider."""
    return get_success_data(api_client.create_provider(
        create_provider_payload(full_name=full_name, provider_type=provider_type),
        _ADMIN,
    ))


def make_pool(term_code: str = "SP26", budget_cents: int = 100000,
              term_end_date: str = "2026-08-31") -> dict:
    """Open a term health-fee pool (PRD §3.8). Returns the created pool."""
    return get_success_data(api_client.create_health_fee_pool(
        create_health_fee_pool_payload(
            term_code=term_code, budget_cents=budget_cents, term_end_date=term_end_date
        ),
        _ADMIN,
    ))


def make_requirement(vaccine_code: str = "MMR", required_doses: int = 2,
                     min_interval_days: int = 28, deadline_date: str = "2026-08-01",
                     grace_period_days: int = 0) -> dict:
    """Define an immunization requirement (PRD §3.3)."""
    return get_success_data(api_client.create_immunization_requirement(
        create_immunization_requirement_payload(
            vaccine_code=vaccine_code,
            required_doses=required_doses,
            min_interval_days=min_interval_days,
            deadline_date=deadline_date,
            grace_period_days=grace_period_days,
        ),
        _ADMIN,
    ))


def make_immunization_record(student_id: str, requirement_id: str) -> dict:
    """Open an immunization record (PRD §3.3). Returns the created record."""
    return get_success_data(api_client.create_immunization_record(
        create_immunization_record_payload(student_id, requirement_id), _NURSE
    ))


def make_stock(medication_code: str, initial_on_hand: int = 100,
               reorder_threshold: int = 0, medication_name: str = None) -> dict:
    """Create a medication stock item (PRD §3.6). on_hand starts at initial."""
    return get_success_data(api_client.create_medication_stock(
        create_medication_stock_payload(
            medication_code=medication_code,
            medication_name=medication_name or f"{medication_code} Drug",
            initial_on_hand=initial_on_hand,
            reorder_threshold=reorder_threshold,
        ),
        _PHARMACIST,
    ))


def make_on_call_shift(provider_id: str, shift_start: str, shift_end: str) -> dict:
    """Schedule an on-call shift (PRD §3.9)."""
    return get_success_data(api_client.create_on_call_shift(
        create_on_call_shift_payload(provider_id, shift_start, shift_end), _ADMIN
    ))


def get_student(student_id: str) -> dict:
    return get_success_data(api_client.get_student(student_id, _ADMIN))


def get_invoice(invoice_id: str) -> dict:
    return get_success_data(api_client.get_invoice(invoice_id, _ADMIN))


def get_pool_by_term(term_code: str) -> dict:
    """Fetch the single pool matching term_code from the list endpoint."""
    pools = get_success_data(api_client.list_health_fee_pools(
        _ADMIN, params={"term_code": term_code}
    ))
    assert isinstance(pools, list) and len(pools) == 1, (
        f"expected exactly one pool with term_code={term_code}, got {pools}"
    )
    return pools[0]


def get_stock_by_code(medication_code: str) -> dict:
    """Fetch the single stock matching medication_code from the list endpoint."""
    stocks = get_success_data(api_client.list_medication_stocks(
        _ADMIN, params={"medication_code": medication_code}
    ))
    assert isinstance(stocks, list) and len(stocks) == 1, (
        f"expected exactly one stock with medication_code={medication_code}, got {stocks}"
    )
    return stocks[0]


def list_outbreaks(disease_code: str) -> list:
    """List outbreak investigations filtered by disease_code (PRD §4)."""
    return get_success_data(api_client.list_outbreak_investigations(
        _ADMIN, params={"disease_code": disease_code}
    ))


# ---------------------------------------------------------------------------
# Tier 1: state progression
# ---------------------------------------------------------------------------

def make_policy(student: dict, payer_type: str = "EXTERNAL", policy_number: str = "POL-1",
                coverage_start: str = "2026-04-01T00:00:00Z",
                coverage_end: str = "2027-03-31T00:00:00Z", copay_cents: int = 0,
                deductible_cents: int = 0, coinsurance_pct: float = 0.0) -> dict:
    """Create a policy for the student (PRD §3.2), threading the OCC field
    expected_student_version from the student's current version (PRD §2.8)."""
    return get_success_data(api_client.create_insurance_policy(
        create_insurance_policy_payload(
            student["id"], student["version"],
            payer_type=payer_type, policy_number=policy_number,
            coverage_start=coverage_start, coverage_end=coverage_end,
            copay_cents=copay_cents, deductible_cents=deductible_cents,
            coinsurance_pct=coinsurance_pct,
        ),
        _BILLING,
    ))


def make_verified_policy(student: dict, **terms) -> dict:
    """Create + verify a policy (PRD §3.2). Returns the VERIFIED policy."""
    policy = make_policy(student, **terms)
    return get_success_data(api_client.verify_insurance_policy(policy["id"], _BILLING))


def book_appointment(student_id: str, provider_id: str, visit_type: str,
                     start: str, end: str) -> dict:
    """Book an appointment as front desk (PRD §3.4). Returns BOOKED appointment."""
    return get_success_data(api_client.create_appointment(
        create_appointment_payload(student_id, provider_id, visit_type, start, end),
        _FRONT_DESK,
    ))


def check_in(appointment_id: str) -> dict:
    """Check in a BOOKED appointment (PRD §3.5). Returns the OPEN encounter."""
    return get_success_data(api_client.check_in_appointment(appointment_id, _FRONT_DESK))


# ---------------------------------------------------------------------------
# Tier 2: entity hierarchy (student + provider + appointment + encounter)
# ---------------------------------------------------------------------------

def book_and_check_in(student_id: str, provider_id: str, visit_type: str,
                      start: str, end: str) -> tuple:
    """Book + check in. Returns (appointment, OPEN encounter)."""
    appt = book_appointment(student_id, provider_id, visit_type, start, end)
    encounter = check_in(appt["id"])
    return appt, encounter


def setup_open_encounter(external_ref: str = "S-ENC", visit_type: str = "PRIMARY_URGENT",
                         start: str = "2026-05-02T10:00:00Z",
                         end: str = "2026-05-02T10:30:00Z",
                         student_name: str = "Encounter Student") -> tuple:
    """Student + provider + checked-in appointment. Returns (student, provider, appt, encounter)."""
    student = make_student(external_ref, student_name)
    provider = make_provider()
    appt, encounter = book_and_check_in(
        student["id"], provider["id"], visit_type, start, end
    )
    return student, provider, appt, encounter


def make_prescription(encounter_id: str, medication_stock_id: str, quantity: int) -> dict:
    """Write a prescription on an OPEN encounter (PRD §3.6). Returns WRITTEN rx."""
    return get_success_data(api_client.create_prescription(
        encounter_id,
        create_prescription_payload(medication_stock_id, quantity),
        _CLINICIAN,
    ))


def setup_encounter_with_prescription(stock_code: str = "AMOX500",
                                      initial_on_hand: int = 100,
                                      reorder_threshold: int = 5,
                                      quantity: int = 5,
                                      external_ref: str = "S-RX") -> tuple:
    """Urgent OPEN encounter + stock + WRITTEN prescription.
    Returns (student, provider, appt, encounter, stock, prescription)."""
    student, provider, appt, encounter = setup_open_encounter(external_ref=external_ref)
    stock = make_stock(stock_code, initial_on_hand, reorder_threshold)
    rx = make_prescription(encounter["id"], stock["id"], quantity)
    return student, provider, appt, encounter, stock, rx


# ---------------------------------------------------------------------------
# Tier 3: full lifecycle shortcuts (labs, disease cases, billing)
# ---------------------------------------------------------------------------

def make_lab_order(encounter_id: str, test_code: str = "CBC",
                   reportable_disease_code: str = None) -> dict:
    """Order a lab test on an OPEN encounter (PRD §3.7). Returns ORDERED order."""
    return get_success_data(api_client.create_lab_order(
        encounter_id,
        create_lab_order_payload(test_code, reportable_disease_code),
        _CLINICIAN,
    ))


def make_suspected_case(encounter_id: str, test_code: str = "MEASLES_IGM",
                        disease_code: str = "MEASLES") -> dict:
    """Lab order -> collect -> reportable result -> auto-created SUSPECTED case
    (PRD §3.7 cascade). Returns the DiseaseCase."""
    lab = make_lab_order(encounter_id, test_code, disease_code)
    get_success_data(api_client.collect_lab_order(lab["id"], _NURSE))
    get_success_data(api_client.result_lab_order(
        lab["id"],
        result_lab_order_payload(result_summary="positive", flags_reportable=True),
        _NURSE,
    ))
    cases = get_success_data(api_client.list_lab_order_disease_cases(lab["id"], _ADMIN))
    assert isinstance(cases, list) and len(cases) == 1, (
        f"expected exactly one auto-created disease case, got {cases}"
    )
    return cases[0]


def confirm_case(case_id: str, user_id: str = "clin-1") -> dict:
    """Confirm a SUSPECTED case as the given clinician user (PRD §3.7)."""
    return get_success_data(api_client.confirm_disease_case(
        case_id, make_clinician_headers(user_id)
    ))


def create_confirmed_case(provider_id: str, external_ref: str, full_name: str,
                          appt_start: str, appt_end: str,
                          disease_code: str = "MEASLES",
                          confirmer_user_id: str = "clin-1") -> dict:
    """Full chain: student -> appointment -> check-in -> lab -> reportable
    result -> SUSPECTED case -> CONFIRMED (PRD §3.7). The caller must have set
    the logical clock before calling; the confirm stamps confirmed_at with the
    current logical time. Returns the CONFIRMED DiseaseCase."""
    student = make_student(external_ref, full_name)
    _, encounter = book_and_check_in(
        student["id"], provider_id, "PRIMARY_URGENT", appt_start, appt_end
    )
    case = make_suspected_case(encounter["id"], disease_code=disease_code)
    return confirm_case(case["id"], confirmer_user_id)


def setup_active_outbreak(disease_code: str = "MEASLES",
                          clock: str = "2026-05-11T12:00:00Z",
                          ref_prefix: str = "S-OB") -> tuple:
    """Three confirmed cases at the same clock time so the rolling count
    reaches the outbreak threshold and an investigation auto-opens (PRD §3.7).
    Returns (provider, investigation, [case1, case2, case3])."""
    set_clock(clock)
    provider = make_provider()
    cases = []
    for idx in range(3):
        cases.append(create_confirmed_case(
            provider["id"],
            f"{ref_prefix}{idx + 1}",
            f"Outbreak Case {idx + 1}",
            f"2026-05-11T{13 + idx:02d}:00:00Z",
            f"2026-05-11T{13 + idx:02d}:30:00Z",
            disease_code=disease_code,
        ))
    investigations = list_outbreaks(disease_code)
    assert len(investigations) == 1 and investigations[0]["status"] == "ACTIVE", (
        f"expected one ACTIVE investigation after 3 confirms, got {investigations}"
    )
    return provider, investigations[0], cases


def setup_chargeable_encounter(external_ref: str = "S-BILL",
                               visit_type: str = "SPORTS_PHYSICAL",
                               start: str = "2026-05-02T10:00:00Z",
                               end: str = "2026-05-02T10:30:00Z") -> tuple:
    """Chargeable (non-fee-covered) OPEN encounter: student + provider +
    checked-in sports/travel appointment (PRD §3.5).
    Returns (student, provider, appt, encounter)."""
    return setup_open_encounter(
        external_ref=external_ref, visit_type=visit_type, start=start, end=end
    )


def make_invoice(encounter_id: str, lines: list) -> dict:
    """Generate the DRAFT/PROVISIONAL invoice for a chargeable encounter
    (PRD §3.8). Returns the created Invoice."""
    return get_success_data(api_client.create_invoice(
        encounter_id, create_invoice_payload(lines), _BILLING
    ))


def setup_issued_invoice(external_ref: str = "S-ISS", charge_cents: int = 5000,
                         service_category: str = "SPORTS_FEE",
                         visit_type: str = "SPORTS_PHYSICAL",
                         start: str = "2026-05-02T10:00:00Z",
                         end: str = "2026-05-02T10:30:00Z",
                         policy_terms: dict = None) -> tuple:
    """Chargeable encounter + invoice generated + issued (PRD §3.8).
    When policy_terms is given, a VERIFIED policy with those terms exists for
    the student at issue time (adjudicated final split); otherwise self-pay.
    Returns (student, provider, appt, encounter, invoice)."""
    student, provider, appt, encounter = setup_chargeable_encounter(
        external_ref=external_ref, visit_type=visit_type, start=start, end=end
    )
    if policy_terms is not None:
        make_verified_policy(student, **policy_terms)
    invoice = make_invoice(encounter["id"], [
        {"service_category": service_category, "charge_cents": charge_cents}
    ])
    invoice = get_success_data(api_client.issue_invoice(invoice["id"], _BILLING))
    return student, provider, appt, encounter, invoice


def setup_overdue_invoice_scenario(ref: str = "S-OVD") -> tuple:
    """Self-pay sports invoice issued at the default clock (due 30 days later),
    plus one future elective (SPORTS_PHYSICAL) and one future urgent
    (PRIMARY_URGENT) booking, then the clock advanced past the due date so the
    invoice ages to OVERDUE (PRD §3.8 sweep).
    Returns (student, provider, invoice, elective_appt, urgent_appt)."""
    set_clock("2026-05-01T00:00:00Z")
    student = make_student(ref, "Overdue Student")
    provider = make_provider()
    appt_charge, encounter = book_and_check_in(
        student["id"], provider["id"], "SPORTS_PHYSICAL",
        "2026-05-02T10:00:00Z", "2026-05-02T10:30:00Z",
    )
    elective = book_appointment(
        student["id"], provider["id"], "SPORTS_PHYSICAL",
        "2026-06-10T10:00:00Z", "2026-06-10T10:30:00Z",
    )
    urgent = book_appointment(
        student["id"], provider["id"], "PRIMARY_URGENT",
        "2026-06-10T11:00:00Z", "2026-06-10T11:30:00Z",
    )
    invoice = make_invoice(encounter["id"], [
        {"service_category": "SPORTS_FEE", "charge_cents": 5000}
    ])
    invoice = get_success_data(api_client.issue_invoice(invoice["id"], _BILLING))
    set_clock("2026-06-01T00:00:00Z")
    return student, provider, invoice, elective, urgent


# ---------------------------------------------------------------------------
# Tier 4: compliance-hold scenarios (threshold targeting via the clock sweep)
# ---------------------------------------------------------------------------

def setup_registration_hold_student(ref: str = "S-HOLD", vaccine_code: str = "MMR",
                                    deadline_date: str = "2026-05-10",
                                    grace_period_days: int = 5,
                                    hold_clock: str = "2026-05-16T00:00:00Z") -> tuple:
    """Student with an immunization record swept past deadline+grace, yielding
    posture REGISTRATION_HOLD with IMMUNIZATION in active_hold_types
    (PRD §3.1, §3.3). Returns (student, requirement, record, provider)."""
    set_clock("2026-05-01T00:00:00Z")
    requirement = make_requirement(
        vaccine_code=vaccine_code, deadline_date=deadline_date,
        grace_period_days=grace_period_days,
    )
    student = make_student(ref, "Held Student")
    record = make_immunization_record(student["id"], requirement["id"])
    provider = make_provider()
    set_clock(hold_clock)
    return student, requirement, record, provider


def setup_clearance_blocked_encounter() -> tuple:
    """SPORTS_PHYSICAL encounter (billing coded) whose student is in
    REGISTRATION_HOLD from an OVERDUE immunization record (PRD §3.3, §3.5).
    Returns (student, provider, appt, encounter, invoice)."""
    set_clock("2026-05-01T00:00:00Z")
    requirement = make_requirement(
        vaccine_code="MMR", deadline_date="2026-05-10", grace_period_days=5
    )
    student = make_student("S-CLR", "Clearance Student")
    make_immunization_record(student["id"], requirement["id"])
    provider = make_provider()
    appt, encounter = book_and_check_in(
        student["id"], provider["id"], "SPORTS_PHYSICAL",
        "2026-05-08T10:00:00Z", "2026-05-08T10:30:00Z",
    )
    invoice = make_invoice(encounter["id"], [
        {"service_category": "SPORTS_FEE", "charge_cents": 3000}
    ])
    set_clock("2026-05-16T00:00:00Z")
    return student, provider, appt, encounter, invoice
