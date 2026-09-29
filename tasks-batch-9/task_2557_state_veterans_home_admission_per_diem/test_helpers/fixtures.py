"""Scenario builders that drive the API to a wanted starting state.

The builders are layered. The lowest layer wraps a single call and returns the
created record. On top of that sit the shortcuts that most scenarios need: an
admitted resident (which alone takes ten calls: clock, home, unit, applicant,
eligibility, waitlist entry, assessment, assessment submission, unit version
read, admission decision), an admitted resident with an active care plan, a
month of census days, and a claim carried to any point of its lifecycle.

Builders use the lenient success extraction so that a setup step failing for an
unrelated reason surfaces as a readable error in the test that asked for it.
Two rules of the API shape these helpers. A decision may not be taken by the
user who wrote the assessment it cites, and a reversal may not be posted by the
user who recorded the entry it negates, so acting user identifiers are always
explicit parameters. And the logical clock is a server-side value, so every
builder that depends on "today" sets the clock first.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .api_client import ApiClient
from .assertions import data_of
from .constants import CLOCK_EPOCH
from . import factories as f
from .test_users import (
    DEFAULT_ASSESSOR_USER,
    DEFAULT_AUDITOR_USER,
    DEFAULT_BOM_USER,
    DEFAULT_COORDINATOR_USER,
    make_admissions_coordinator_headers,
    make_business_office_manager_headers,
    make_clinical_assessor_headers,
    make_federal_per_diem_auditor_headers,
    make_state_program_admin_headers,
    make_survey_agency_headers,
)


# ---------------------------------------------------------------------------
# Tier 1: single-call wrappers
# ---------------------------------------------------------------------------
def set_clock(api: ApiClient, to_iso8601: str) -> Dict[str, Any]:
    return data_of(api.set_clock(f.clock_payload(to_iso8601), make_state_program_admin_headers()))


def create_home(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    return data_of(
        api.create_veterans_home(f.veterans_home_payload(**overrides), make_state_program_admin_headers())
    )


def create_unit(api: ApiClient, home_id: str, **overrides: Any) -> Dict[str, Any]:
    return data_of(
        api.create_care_unit(home_id, f.care_unit_payload(**overrides), make_state_program_admin_headers())
    )


def create_applicant(api: ApiClient, home_id: str, **overrides: Any) -> Dict[str, Any]:
    return data_of(
        api.create_applicant(
            f.applicant_payload(home_id, **overrides), make_admissions_coordinator_headers()
        )
    )


def determine_eligibility(api: ApiClient, applicant_id: str) -> Dict[str, Any]:
    return data_of(api.determine_eligibility(applicant_id, {}, make_admissions_coordinator_headers()))


def create_waitlist_entry(api: ApiClient, applicant_id: str, care_unit_id: str) -> Dict[str, Any]:
    return data_of(
        api.create_waitlist_entry(
            f.waitlist_entry_payload(applicant_id, care_unit_id), make_admissions_coordinator_headers()
        )
    )


def create_assessment(
    api: ApiClient,
    applicant_id: str,
    assessor_user_id: str = DEFAULT_ASSESSOR_USER,
    **overrides: Any,
) -> Dict[str, Any]:
    return data_of(
        api.create_clinical_assessment(
            applicant_id,
            f.clinical_assessment_payload(**overrides),
            make_clinical_assessor_headers(assessor_user_id),
        )
    )


def submit_assessment(
    api: ApiClient, assessment_id: str, assessor_user_id: str = DEFAULT_ASSESSOR_USER
) -> Dict[str, Any]:
    return data_of(
        api.submit_clinical_assessment(
            assessment_id, {}, make_clinical_assessor_headers(assessor_user_id)
        )
    )


def read_unit(api: ApiClient, care_unit_id: str) -> Dict[str, Any]:
    return data_of(api.get_care_unit(care_unit_id, make_state_program_admin_headers()))


def read_home(api: ApiClient, home_id: str) -> Dict[str, Any]:
    return data_of(api.get_veterans_home(home_id, make_state_program_admin_headers()))


def read_resident(api: ApiClient, resident_id: str) -> Dict[str, Any]:
    return data_of(api.get_resident(resident_id, make_state_program_admin_headers()))


def read_care_plan(api: ApiClient, care_plan_id: str) -> Dict[str, Any]:
    return data_of(api.get_care_plan(care_plan_id, make_state_program_admin_headers()))


def read_claim(api: ApiClient, claim_id: str) -> Dict[str, Any]:
    return data_of(api.get_per_diem_claim(claim_id, make_state_program_admin_headers()))


def read_transaction(api: ApiClient, transaction_id: str) -> Dict[str, Any]:
    return data_of(
        api.get_trust_fund_transaction(transaction_id, make_state_program_admin_headers())
    )


def read_applicant(api: ApiClient, applicant_id: str) -> Dict[str, Any]:
    return data_of(api.get_applicant(applicant_id, make_admissions_coordinator_headers()))


def read_waitlist_entries_for_unit(api: ApiClient, care_unit_id: str) -> List[Dict[str, Any]]:
    body = api.list_unit_waitlist_entries(
        care_unit_id, make_admissions_coordinator_headers(), {"limit": 100}
    ).json()
    return body.get("data", [])


def read_waitlist_entries_for_applicant(api: ApiClient, applicant_id: str) -> List[Dict[str, Any]]:
    body = api.list_applicant_waitlist_entries(
        applicant_id, make_admissions_coordinator_headers(), {"limit": 100}
    ).json()
    return body.get("data", [])


def read_census_days(api: ApiClient, **params: Any) -> List[Dict[str, Any]]:
    params.setdefault("limit", 100)
    body = api.list_census_days(make_business_office_manager_headers(), params).json()
    return body.get("data", [])


def read_transactions(api: ApiClient, **params: Any) -> List[Dict[str, Any]]:
    params.setdefault("limit", 100)
    body = api.list_trust_fund_transactions(make_business_office_manager_headers(), params).json()
    return body.get("data", [])


def record_survey(
    api: ApiClient, care_unit_id: str, survey_date: str, deficiencies: Optional[List[Dict[str, Any]]] = None
) -> Dict[str, Any]:
    return data_of(
        api.record_survey_result(
            care_unit_id,
            f.survey_result_payload(survey_date, deficiencies or []),
            make_survey_agency_headers(),
        )
    )


def set_recognition(
    api: ApiClient, home_id: str, action: str, effective_date: str, note: Optional[str] = None
) -> Dict[str, Any]:
    return data_of(
        api.set_recognition(
            home_id, f.recognition_payload(action, effective_date, note), make_state_program_admin_headers()
        )
    )


def census_run(
    api: ApiClient, through_date: str, veterans_home_id: Optional[str] = None
) -> Dict[str, Any]:
    return data_of(
        api.census_run(
            f.census_run_payload(through_date, veterans_home_id), make_state_program_admin_headers()
        )
    )


# ---------------------------------------------------------------------------
# Tier 2: the admission chain
# ---------------------------------------------------------------------------
@dataclass
class AdmittedScenario:
    """Everything the admission chain produced, so a test can reach any of it."""

    home_id: str
    unit_id: str
    applicant_id: str
    waitlist_entry_id: str
    assessment_id: str
    resident_id: str
    admission_date: str
    care_level: str
    assessor_user_id: str
    coordinator_user_id: str
    care_plan_id: Optional[str] = None
    extra_unit_ids: List[str] = field(default_factory=list)


def approve_admission(
    api: ApiClient,
    applicant_id: str,
    care_unit_id: str,
    assessment_id: str,
    admission_date: str,
    coordinator_user_id: str = DEFAULT_COORDINATOR_USER,
    **overrides: Any,
):
    """Take an admission decision, reading the unit version immediately beforehand."""
    unit_version = read_unit(api, care_unit_id)["version"]
    payload = f.admission_decision_payload(
        care_unit_id, assessment_id, unit_version, admission_date, **overrides
    )
    return api.admission_decision(
        applicant_id, payload, make_admissions_coordinator_headers(coordinator_user_id)
    )


def admitted_resident(
    api: ApiClient,
    admission_date: str = "2026-08-01",
    care_level: str = "NURSING",
    licensed_bed_count: int = 2,
    out_of_service_bed_count: int = 0,
    clock_at_start: Optional[str] = None,
    assessor_user_id: str = DEFAULT_ASSESSOR_USER,
    coordinator_user_id: str = DEFAULT_COORDINATOR_USER,
    home_overrides: Optional[Dict[str, Any]] = None,
    applicant_overrides: Optional[Dict[str, Any]] = None,
    assessment_overrides: Optional[Dict[str, Any]] = None,
    application_date: Optional[str] = None,
    clock_before_decision: Optional[str] = None,
) -> AdmittedScenario:
    """Drive the whole admission chain and return one admitted resident.

    The clock is placed at `clock_at_start` (defaulting to the application date
    at midnight) because the application and assessment dates may not lie in the
    future of the logical clock. When the admission itself happens later than the
    application, `clock_before_decision` moves the clock forward just before the
    decision is taken.
    """
    application_date = application_date or admission_date
    set_clock(api, clock_at_start or f"{application_date}T00:00:00Z")
    home = create_home(api, **(home_overrides or {}))
    unit = create_unit(
        api,
        home["id"],
        care_level=care_level,
        licensed_bed_count=licensed_bed_count,
        out_of_service_bed_count=out_of_service_bed_count,
    )
    applicant_fields = {
        "requested_care_level": care_level,
        "application_received_date": application_date,
    }
    applicant_fields.update(applicant_overrides or {})
    applicant = create_applicant(api, home["id"], **applicant_fields)
    determine_eligibility(api, applicant["id"])
    entry = create_waitlist_entry(api, applicant["id"], unit["id"])
    assessment_fields = {
        "assessed_care_level": care_level,
        "assessment_date": application_date,
    }
    assessment_fields.update(assessment_overrides or {})
    assessment = create_assessment(api, applicant["id"], assessor_user_id, **assessment_fields)
    submit_assessment(api, assessment["id"], assessor_user_id)
    if clock_before_decision:
        set_clock(api, clock_before_decision)
    resident = data_of(
        approve_admission(
            api,
            applicant["id"],
            unit["id"],
            assessment["id"],
            admission_date,
            coordinator_user_id,
        )
    )
    return AdmittedScenario(
        home_id=home["id"],
        unit_id=unit["id"],
        applicant_id=applicant["id"],
        waitlist_entry_id=entry["id"],
        assessment_id=assessment["id"],
        resident_id=resident["id"],
        admission_date=admission_date,
        care_level=care_level,
        assessor_user_id=assessor_user_id,
        coordinator_user_id=coordinator_user_id,
    )


def add_unit(api: ApiClient, scenario: AdmittedScenario, **overrides: Any) -> Dict[str, Any]:
    """Add a second care unit to the scenario's home and remember its id."""
    unit = create_unit(api, scenario.home_id, **overrides)
    scenario.extra_unit_ids.append(unit["id"])
    return unit


def activate_care_plan(
    api: ApiClient,
    resident_id: str,
    care_level: str = "NURSING",
    plan_date: str = "2026-08-01",
    adl_support_level: str = "HIGH",
    assessor_user_id: str = DEFAULT_ASSESSOR_USER,
    supersedes_care_plan_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Author a plan and activate it, returning the activated plan."""
    plan = data_of(
        api.create_care_plan(
            resident_id,
            f.care_plan_payload(
                care_level=care_level,
                adl_support_level=adl_support_level,
                plan_date=plan_date,
                supersedes_care_plan_id=supersedes_care_plan_id,
            ),
            make_clinical_assessor_headers(assessor_user_id),
        )
    )
    return data_of(
        api.activate_care_plan(plan["id"], {}, make_clinical_assessor_headers(assessor_user_id))
    )


def admitted_resident_with_care_plan(api: ApiClient, **kwargs: Any) -> AdmittedScenario:
    """An admitted resident whose care plan is ACTIVE at the same care level."""
    scenario = admitted_resident(api, **kwargs)
    plan = activate_care_plan(
        api,
        scenario.resident_id,
        care_level=scenario.care_level,
        plan_date=scenario.admission_date,
        assessor_user_id=scenario.assessor_user_id,
    )
    scenario.care_plan_id = plan["id"]
    return scenario


# ---------------------------------------------------------------------------
# Tier 3: waitlist depth
# ---------------------------------------------------------------------------
def queue_second_applicant(
    api: ApiClient,
    scenario: AdmittedScenario,
    application_received_date: Optional[str] = None,
    care_unit_id: Optional[str] = None,
    **applicant_overrides: Any,
) -> Dict[str, Any]:
    """Add one more eligible, waitlisted applicant to a unit's queue."""
    overrides = {
        "requested_care_level": scenario.care_level,
        "application_received_date": application_received_date or scenario.admission_date,
    }
    overrides.update(applicant_overrides)
    applicant = create_applicant(api, scenario.home_id, **overrides)
    determine_eligibility(api, applicant["id"])
    entry = create_waitlist_entry(api, applicant["id"], care_unit_id or scenario.unit_id)
    return {"applicant": applicant, "entry": entry}


# ---------------------------------------------------------------------------
# Tier 4: money and census accumulation
# ---------------------------------------------------------------------------
def declare_income(
    api: ApiClient,
    resident_id: str,
    income_type: str,
    monthly_amount_cents: int,
    effective_month: str = "2026-08",
    verify: bool = True,
    bom_user_id: str = DEFAULT_BOM_USER,
) -> Dict[str, Any]:
    """Declare one income stream, optionally carrying it through verification."""
    record = data_of(
        api.create_income_record(
            resident_id,
            f.income_record_payload(income_type, monthly_amount_cents, effective_month),
            make_business_office_manager_headers(bom_user_id),
        )
    )
    if verify:
        record = data_of(
            api.verify_income_record(
                record["id"],
                f.income_verification_payload("VERIFIED"),
                make_business_office_manager_headers(bom_user_id),
            )
        )
    return record


def determine_cost_share(
    api: ApiClient,
    resident_id: str,
    variant: str = "PROVISIONAL",
    effective_month: str = "2026-08",
    declared_medical_expense_cents: Optional[int] = None,
    bom_user_id: str = DEFAULT_BOM_USER,
):
    """Compute a cost-share determination, pinning the resident version first."""
    resident_version = read_resident(api, resident_id)["version"]
    return api.create_cost_share_determination(
        resident_id,
        f.cost_share_payload(
            resident_version,
            variant=variant,
            effective_month=effective_month,
            declared_medical_expense_cents=declared_medical_expense_cents,
        ),
        make_business_office_manager_headers(bom_user_id),
    )


def post_trust_entry(
    api: ApiClient,
    resident_id: str,
    txn_type: str,
    amount_cents: int,
    effective_date: str,
    memo: str = "test posting",
    bom_user_id: str = DEFAULT_BOM_USER,
):
    return api.create_trust_fund_transaction(
        resident_id,
        f.trust_fund_payload(txn_type, amount_cents, effective_date, memo),
        make_business_office_manager_headers(bom_user_id),
    )


def hospitalize(api: ApiClient, resident_id: str, start_date: str, clock: Optional[str] = None):
    if clock:
        set_clock(api, clock)
    return api.hospitalize_resident(
        resident_id, f.hospitalization_payload(start_date), make_admissions_coordinator_headers()
    )


def readmit(api: ApiClient, resident_id: str, readmission_date: str, clock: Optional[str] = None):
    if clock:
        set_clock(api, clock)
    return api.readmit_resident(
        resident_id, f.readmission_payload(readmission_date), make_admissions_coordinator_headers()
    )


def transfer(api: ApiClient, resident_id: str, target_unit_id: str, effective_date: str):
    return api.transfer_resident(
        resident_id,
        f.transfer_payload(target_unit_id, effective_date),
        make_admissions_coordinator_headers(),
    )


def discharge(
    api: ApiClient, resident_id: str, discharge_date: str, discharge_reason: str = "VOLUNTARY"
):
    return api.discharge_resident(
        resident_id,
        f.discharge_payload(discharge_date, discharge_reason),
        make_admissions_coordinator_headers(),
    )


# ---------------------------------------------------------------------------
# Tier 5: claim lifecycle shortcuts
# ---------------------------------------------------------------------------
def open_claim(
    api: ApiClient,
    home_id: str,
    care_unit_id: str,
    claim_month: str = "2026-08",
    basis: str = "AUDITED_BASIS",
    bom_user_id: str = DEFAULT_BOM_USER,
):
    return api.create_per_diem_claim(
        f.per_diem_claim_payload(home_id, care_unit_id, claim_month, basis),
        make_business_office_manager_headers(bom_user_id),
    )


def submit_claim(api: ApiClient, claim_id: str, bom_user_id: str = DEFAULT_BOM_USER):
    return api.submit_per_diem_claim(claim_id, {}, make_business_office_manager_headers(bom_user_id))


def adjudicate_claim(
    api: ApiClient,
    claim_id: str,
    outcome: str = "PAID",
    rejection_code: Optional[str] = None,
    note: str = "reviewed",
    auditor_user_id: str = DEFAULT_AUDITOR_USER,
):
    return api.adjudicate_per_diem_claim(
        claim_id,
        f.adjudication_payload(outcome, note, rejection_code),
        make_federal_per_diem_auditor_headers(auditor_user_id),
    )


def correct_claim(
    api: ApiClient,
    claim_id: str,
    correction_note: str = "rate audit rerun",
    bom_user_id: str = DEFAULT_BOM_USER,
    **overrides: Any,
):
    """Open a correcting claim, pinning the corrected claim's version first."""
    claim_version = read_claim(api, claim_id)["version"]
    return api.correct_per_diem_claim(
        claim_id,
        f.correction_payload(claim_version, correction_note, **overrides),
        make_business_office_manager_headers(bom_user_id),
    )


def billed_month(
    api: ApiClient,
    admission_date: str = "2026-08-01",
    through_date: str = "2026-08-31",
    clock_after_month: str = "2026-09-01T00:00:00Z",
    care_level: str = "NURSING",
    with_care_plan: bool = False,
    **kwargs: Any,
) -> AdmittedScenario:
    """An admitted resident with a materialised month of census days behind them."""
    builder = admitted_resident_with_care_plan if with_care_plan else admitted_resident
    scenario = builder(api, admission_date=admission_date, care_level=care_level, **kwargs)
    set_clock(api, clock_after_month)
    census_run(api, through_date, scenario.home_id)
    return scenario


CLOCK_START = CLOCK_EPOCH
