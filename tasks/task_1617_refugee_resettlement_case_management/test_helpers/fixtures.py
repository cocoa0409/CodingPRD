"""Composite setup helpers for the resettlement case-management tests (PRD §3).

The test runner restarts the API server before every test, so each fixture
builds its preconditions from scratch using only PRD-declared endpoints.
Setup calls use the lenient get_success_data so a setup failure surfaces as a
clear "Setup failed" error rather than a confusing assertion failure.

Housing capacity note (PRD §3.2): the unit's bedrooms must be at least the
household size divided by two rounded up. The `setup_case_with_housing`
workhorse therefore defaults the unit's bedroom count to exactly that minimum
when the caller does not specify one, so every setup chain is valid regardless
of household size.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    DEFAULT_AGENCY_CODE,
    DEFAULT_ARRIVAL_DATE,
    DEFAULT_OCCUPANCY_END,
    DEFAULT_OCCUPANCY_START,
    REQUIRED_FURNISHINGS,
)
from .factories import (
    create_case_payload,
    create_member_payload,
    create_housing_unit_payload,
    create_housing_setup_payload,
    create_benefit_application_payload,
    create_employment_plan_payload,
    create_orientation_session_payload,
    create_case_note_payload,
    create_case_transfer_payload,
    create_federal_report_payload,
)
from .test_users import TEST_USERS

CM = TEST_USERS["case_manager_headers"]
HC = TEST_USERS["housing_coordinator_headers"]
ES = TEST_USERS["employment_specialist_headers"]
AD = TEST_USERS["agency_director_headers"]
FO = TEST_USERS["federal_officer_headers"]


def min_bedrooms_for(household_size: int) -> int:
    """Minimum bedrooms a unit needs for a household (PRD §3.2: household
    size divided by two, rounded up)."""
    return (household_size + 1) // 2


# --- Tier 1: single-entity creation ---

def make_case(case_number=None, household_size=1,
              scheduled_arrival_date=DEFAULT_ARRIVAL_DATE,
              agency_affiliate_code=DEFAULT_AGENCY_CODE,
              headers=None):
    overrides = {
        "household_size": household_size,
        "scheduled_arrival_date": scheduled_arrival_date,
        "agency_affiliate_code": agency_affiliate_code,
    }
    if case_number is not None:
        overrides["case_number"] = case_number
    resp = api_client.create_case(create_case_payload(**overrides), headers or CM)
    return get_success_data(resp)


def get_case(case_id, headers=None):
    return get_success_data(api_client.get_case(case_id, headers or CM))


def add_member(case_id, full_name="Member", date_of_birth="1990-01-01",
               relationship="PRINCIPAL", work_eligible=True, headers=None):
    resp = api_client.create_member(
        create_member_payload(
            case_id=case_id, full_name=full_name, date_of_birth=date_of_birth,
            relationship=relationship, work_eligible=work_eligible),
        headers or CM)
    return get_success_data(resp)


def make_housing_unit(address=None, bedrooms=1, headers=None):
    overrides = {"bedrooms": bedrooms}
    if address is not None:
        overrides["address"] = address
    resp = api_client.create_housing_unit(
        create_housing_unit_payload(**overrides), headers or HC)
    return get_success_data(resp)


def get_housing_unit(unit_id, headers=None):
    return get_success_data(api_client.get_housing_unit(unit_id, headers or HC))


def make_housing_setup(case_id, housing_unit_id,
                       occupancy_start=DEFAULT_OCCUPANCY_START,
                       occupancy_end=DEFAULT_OCCUPANCY_END, headers=None):
    resp = api_client.create_housing_setup(
        create_housing_setup_payload(
            case_id=case_id, housing_unit_id=housing_unit_id,
            occupancy_start=occupancy_start, occupancy_end=occupancy_end),
        headers or HC)
    return get_success_data(resp)


def furnish_item(setup_id, item, headers=None):
    return get_success_data(
        api_client.furnish_setup(setup_id, {"item": item}, headers or HC))


def furnish_all_items(setup_id, headers=None):
    """Complete every required furnishing item (PRD §3.2)."""
    setup = None
    for item in REQUIRED_FURNISHINGS:
        setup = furnish_item(setup_id, item, headers=headers)
    return setup


def mark_setup_ready(setup_id, headers=None):
    return get_success_data(api_client.ready_setup(setup_id, headers or HC))


def vacate_setup(setup_id, headers=None):
    return get_success_data(api_client.vacate_setup(setup_id, headers or HC))


def arrive_case(case_id, actual_arrival_date=DEFAULT_ARRIVAL_DATE, headers=None):
    return get_success_data(api_client.arrive_case(
        case_id, {"actual_arrival_date": actual_arrival_date}, headers or CM))


def set_clock(to_iso8601, headers=None):
    return get_success_data(
        api_client.set_clock({"to_iso8601": to_iso8601}, headers or AD))


# --- Tier 2: composite case + housing ---

def setup_case_with_housing(case_number=None, household_size=1, members=(),
                            bedrooms=None, address=None,
                            scheduled_arrival_date=DEFAULT_ARRIVAL_DATE,
                            actual_arrival_date=DEFAULT_ARRIVAL_DATE,
                            occupancy_start=None, occupancy_end=None,
                            furnish_count=len(REQUIRED_FURNISHINGS),
                            ready=True, arrive=True):
    """Case + members + unit + setup, optionally furnished/READY/arrived.

    members: iterable of dicts with add_member kwargs (full_name,
    date_of_birth, relationship, work_eligible).
    furnish_count: how many of the required furnishing items to complete
    (default all six; pass 5 to leave the setup one item short of READY).
    Returns {"case", "unit", "setup", "members"} — with setup None when the
    capacity rule rejects creation (never, under the default bedrooms).
    """
    case = make_case(case_number=case_number, household_size=household_size,
                     scheduled_arrival_date=scheduled_arrival_date)
    member_list = [add_member(case["id"], **m) for m in members]
    if bedrooms is None:
        bedrooms = min_bedrooms_for(household_size)
    unit = make_housing_unit(address=address, bedrooms=bedrooms)
    setup = make_housing_setup(
        case["id"], unit["id"],
        occupancy_start=occupancy_start or scheduled_arrival_date,
        occupancy_end=occupancy_end or DEFAULT_OCCUPANCY_END)
    for item in REQUIRED_FURNISHINGS[:furnish_count]:
        setup = furnish_item(setup["id"], item)
    if ready:
        setup = mark_setup_ready(setup["id"])
    if arrive:
        case = arrive_case(case["id"], actual_arrival_date=actual_arrival_date)
    return {"case": case, "unit": unit, "setup": setup, "members": member_list}


def setup_arrived_case(**kwargs):
    """The workhorse: a fully arrived case with READY-then-OCCUPIED housing."""
    return setup_case_with_housing(ready=True, arrive=True, **kwargs)


# --- Benchmarks ---

def list_case_benchmarks(case_id, headers=None, **filters):
    params = {k: v for k, v in filters.items() if v is not None}
    return get_success_data(
        api_client.list_case_benchmarks(case_id, headers or CM, params=params or None))


def get_benchmark_by_type(case_id, service_type, headers=None):
    """Fetch the case's benchmark of the given service type (seeding order is
    fixed by PRD §3.4, so the single matching row is deterministic)."""
    benchmarks = list_case_benchmarks(case_id, headers=headers, service_type=service_type)
    assert len(benchmarks) == 1, (
        f"Expected exactly 1 {service_type} benchmark for case {case_id}, "
        f"got {len(benchmarks)}")
    return benchmarks[0]


def fulfill_benchmark(benchmark_id, fulfilled_on, evidence_note_id,
                      enrolled_member_ids=None, headers=None):
    payload = {"fulfilled_on": fulfilled_on, "evidence_note_id": evidence_note_id}
    if enrolled_member_ids is not None:
        payload["enrolled_member_ids"] = enrolled_member_ids
    return get_success_data(
        api_client.fulfill_benchmark(benchmark_id, payload, headers or CM))


def waive_benchmark(benchmark_id, reason="Director waiver", headers=None):
    return get_success_data(
        api_client.waive_benchmark(benchmark_id, {"reason": reason}, headers or AD))


def rescind_benchmark(benchmark_id, headers=None):
    return get_success_data(api_client.rescind_benchmark(benchmark_id, headers or CM))


# --- Case notes ---

def make_case_note(case_id, note_type="GENERAL", body="Case note",
                   service_date=None, headers=None):
    payload = create_case_note_payload(
        case_id=case_id, note_type=note_type, body=body)
    if service_date is not None:
        payload["service_date"] = service_date
    return get_success_data(api_client.create_case_note(payload, headers or CM))


def make_service_delivery_note(case_id, body="Service delivered",
                               service_date="2026-08-15", headers=None):
    return make_case_note(case_id, note_type="SERVICE_DELIVERY", body=body,
                          service_date=service_date, headers=headers)


# --- Benefit applications ---

def make_benefit_application(case_id, member_id, benefit_type="SSN", headers=None):
    resp = api_client.create_benefit_application(
        create_benefit_application_payload(
            case_id=case_id, member_id=member_id, benefit_type=benefit_type),
        headers or CM)
    return get_success_data(resp)


def transition_application(application_id, to_status, headers=None):
    return get_success_data(api_client.transition_benefit_application(
        application_id, {"to_status": to_status}, headers or CM))


def make_filed_application(case_id, member_id, benefit_type="SSN", headers=None):
    app = make_benefit_application(case_id, member_id, benefit_type, headers=headers)
    return transition_application(app["id"], "FILED", headers=headers)


# --- Employment plans (OCC-guarded on Case.version, PRD §2.6) ---

def make_employment_plan(case_id, headers=None):
    """Create the ACTIVE plan for an arrived case; reads the current
    Case.version first so the OCC precondition is satisfied."""
    h = headers or ES
    case = get_case(case_id, headers=h)
    resp = api_client.create_employment_plan(
        create_employment_plan_payload(
            case_id=case_id, expected_case_version=case["version"]), h)
    return get_success_data(resp)


def patch_employment_plan(plan_id, headers=None, **fields):
    return get_success_data(
        api_client.patch_employment_plan(plan_id, fields, headers or ES))


def certify_employment_plan(plan_id, variant="MONTHLY", headers=None):
    return get_success_data(
        api_client.certify_employment_plan(plan_id, {"variant": variant}, headers or ES))


def list_employment_plans(case_id, headers=None):
    return get_success_data(
        api_client.list_employment_plans(case_id, headers or ES))


# --- Orientation sessions ---

def make_orientation_session(case_id, topic="US_LAWS",
                             start_at="2026-08-12T09:00:00Z",
                             end_at="2026-08-12T10:00:00Z", headers=None):
    resp = api_client.create_orientation_session(
        create_orientation_session_payload(
            case_id=case_id, topic=topic, start_at=start_at, end_at=end_at),
        headers or CM)
    return get_success_data(resp)


def complete_orientation_session(session_id, headers=None):
    return get_success_data(
        api_client.complete_orientation_session(session_id, headers or CM))


def list_orientation_sessions(case_id, headers=None):
    return get_success_data(
        api_client.list_orientation_sessions(case_id, headers or CM))


# --- Case transfers ---

def make_case_transfer(case_id, receiving_affiliate_code="AFF-99",
                       reason="SECONDARY_MIGRATION", headers=None):
    resp = api_client.create_case_transfer(
        create_case_transfer_payload(
            case_id=case_id,
            receiving_affiliate_code=receiving_affiliate_code,
            reason=reason),
        headers or CM)
    return get_success_data(resp)


def respond_case_transfer(transfer_id, decision, decision_note=None, headers=None):
    payload = {"decision": decision}
    if decision_note is not None:
        payload["decision_note"] = decision_note
    return get_success_data(
        api_client.respond_case_transfer(transfer_id, payload, headers or AD))


def withdraw_case_transfer(transfer_id, headers=None):
    return get_success_data(
        api_client.withdraw_case_transfer(transfer_id, headers or CM))


# --- Federal reports ---

def make_federal_report(period_start="2026-10-01", period_end="2027-01-01",
                        headers=None):
    resp = api_client.create_federal_report(
        create_federal_report_payload(
            period_start=period_start, period_end=period_end),
        headers or AD)
    return get_success_data(resp)


def submit_federal_report(report_id, headers=None):
    return get_success_data(
        api_client.submit_federal_report(report_id, headers or AD))


def review_federal_report(report_id, decision, headers=None):
    return get_success_data(
        api_client.review_federal_report(report_id, {"decision": decision},
                                         headers or FO))
