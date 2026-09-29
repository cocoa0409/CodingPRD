"""Composite setup helpers.

Every test starts against an empty database, so any precondition beyond a bare
create has to be walked through the API itself.  The helpers here build the
states the PRD's narratives presuppose — an ACTIVE permit term carrying its full
minimum control measure set, a construction site with an approved plan and an
actively disturbed field, a privately owned permanent control with a recorded
maintenance agreement, an illicit discharge case parked at a chosen point of its
cycle, an enforcement action on the ladder, and an annual report already
compiled or certified.

Each helper uses the role the PRD authorises for the operation in question, and
threads the acting identity where a rule keys on it: a fee credit application is
filed by the ``PropertyOwner`` whose ``X-User-ID`` is the account's own ``id``,
a sample is adjudicated by an operator other than its recorder, and a report is
certified by a manager other than the one who compiled it.
"""

from typing import Any, Dict, List, Optional, Sequence, Tuple

from prd_bench_local_runner.testing import get_success_data, validate_paginated

from . import factories
from .api_client import api_client
from .constants import STANDARD_MEASURE_SET
from .test_users import (
    CLERK_HEADERS,
    IDDE_HEADERS,
    INSPECTOR_HEADERS,
    MANAGER_HEADERS,
    MANAGER_TWO_HEADERS,
    OFFICER_HEADERS,
    OPERATIONS_HEADERS,
    OPERATIONS_TWO_HEADERS,
    make_property_owner_headers,
)


# ==========================================================================
# Logical clock
# ==========================================================================


def set_clock(to_iso8601: str) -> str:
    """Move the logical clock and return the instant it now reads."""
    data = get_success_data(api_client.set_clock(to_iso8601, MANAGER_HEADERS))
    return data["current_utc"]


# ==========================================================================
# Tier 1: permit term, measure set, outfalls, activation
# ==========================================================================


def create_permit_term(**overrides: Any) -> Dict[str, Any]:
    """A permit term in DRAFT."""
    payload = factories.permit_term_payload(**overrides)
    return get_success_data(api_client.create_permit_term(payload, MANAGER_HEADERS), 201)


def create_tmdl_permit_term(**overrides: Any) -> Dict[str, Any]:
    """A permit term in DRAFT carrying a waste load allocation."""
    payload = factories.tmdl_permit_term_payload(**overrides)
    return get_success_data(api_client.create_permit_term(payload, MANAGER_HEADERS), 201)


def register_standard_measure_set(
    term_id: str, overrides: Optional[Dict[str, Dict[str, Any]]] = None
) -> Dict[str, Dict[str, Any]]:
    """Register all six minimum control measures under a term.

    Returns the created measures keyed by ``measure_code``.  The municipal
    operations measure is registered with ``salt_storage_covered`` and
    ``fleet_wash_recycle`` true so that its gate is not tripped by default.
    """
    measures: Dict[str, Dict[str, Any]] = {}
    for code, defaults in STANDARD_MEASURE_SET.items():
        fields = dict(defaults)
        if overrides and code in overrides:
            fields.update(overrides[code])
        payload = factories.control_measure_payload(term_id, code, **fields)
        measures[code] = get_success_data(
            api_client.create_control_measure(payload, MANAGER_HEADERS), 201
        )
    return measures


def create_outfall(term_id: str, outfall_code: str = "OF-01", **overrides: Any) -> Dict[str, Any]:
    payload = factories.outfall_payload(term_id, outfall_code, **overrides)
    return get_success_data(api_client.create_outfall(payload, MANAGER_HEADERS), 201)


def setup_active_program(
    outfall_codes: Sequence[str] = ("OF-01",),
    tmdl: bool = False,
    measure_overrides: Optional[Dict[str, Dict[str, Any]]] = None,
    outfall_overrides: Optional[Dict[str, Any]] = None,
    **term_overrides: Any,
) -> Dict[str, Any]:
    """An ACTIVE permit term with its full measure set and outfall inventory.

    Returns a dict holding ``term`` (as read back after activation),
    ``measures`` keyed by ``measure_code``, ``outfalls`` keyed by
    ``outfall_code``, and ``term_id`` for convenience.
    """
    term = (
        create_tmdl_permit_term(**term_overrides)
        if tmdl
        else create_permit_term(**term_overrides)
    )
    measures = register_standard_measure_set(term["id"], measure_overrides)
    outfalls: Dict[str, Dict[str, Any]] = {}
    for code in outfall_codes:
        outfalls[code] = create_outfall(term["id"], code, **(outfall_overrides or {}))
    activated = get_success_data(api_client.activate_permit_term(term["id"], MANAGER_HEADERS))
    return {
        "term": activated,
        "term_id": term["id"],
        "measures": measures,
        "outfalls": outfalls,
    }


def setup_tmdl_program(**term_overrides: Any) -> Dict[str, Any]:
    """The programme most narratives presuppose: an ACTIVE term under a
    phosphorus waste load allocation of 50.00 pounds per year, carrying the six
    minimum control measures and one active outfall.
    """
    term_overrides.setdefault("outfall_codes", ("OF-01",))
    term_overrides["tmdl"] = True
    return setup_active_program(**term_overrides)


def read_term(term_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_permit_term(term_id, MANAGER_HEADERS))


def term_version(term_id: str) -> int:
    return read_term(term_id)["version"]


def read_measure(measure_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_control_measure(measure_id, MANAGER_HEADERS))


def read_outfall(outfall_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_outfall(outfall_id, MANAGER_HEADERS))


def read_site(site_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_construction_site(site_id, MANAGER_HEADERS))


def read_facility(facility_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.get_post_construction_facility(facility_id, MANAGER_HEADERS)
    )


def read_inspection(inspection_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_inspection(inspection_id, MANAGER_HEADERS))


def read_action(action_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_enforcement_action(action_id, MANAGER_HEADERS))


def read_account(account_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_account(account_id, CLERK_HEADERS))


def read_application(application_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.get_fee_credit_application(application_id, CLERK_HEADERS)
    )


def read_case(case_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_illicit_discharge_case(case_id, MANAGER_HEADERS))


def read_report(report_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_annual_report(report_id, MANAGER_HEADERS))


def report_progress(measure_id: str, measurable_goal_actual: float) -> Dict[str, Any]:
    return get_success_data(
        api_client.report_measure_progress(
            measure_id,
            factories.report_progress_payload(measurable_goal_actual),
            MANAGER_HEADERS,
        )
    )


# ==========================================================================
# Tier 2: outfall field work — screenings, samples, sweeping
# ==========================================================================


def record_screening(
    outfall_id: str, observed_at: str, suspect: bool = False, **overrides: Any
) -> Dict[str, Any]:
    payload = (
        factories.suspect_screening_payload(observed_at, **overrides)
        if suspect
        else factories.screening_payload(observed_at, **overrides)
    )
    return get_success_data(
        api_client.create_observation(outfall_id, payload, IDDE_HEADERS), 201
    )


def record_sample(
    outfall_id: str,
    observed_at: str = "2026-08-01T08:00:00Z",
    pollutant_concentration_mg_per_l: float = 0.40,
    runoff_volume_kl: float = 1000.00,
    **overrides: Any,
) -> Dict[str, Any]:
    """A wet-weather sample recorded by the operations supervisor.

    The recorder is deliberately ``ops-01`` so that ``ops-02`` remains available
    as an adjudicator who differs from the recorder.
    """
    payload = factories.sample_payload(
        observed_at, pollutant_concentration_mg_per_l, runoff_volume_kl, **overrides
    )
    return get_success_data(
        api_client.create_observation(outfall_id, payload, OPERATIONS_HEADERS), 201
    )


def record_validated_sample(
    outfall_id: str,
    observed_at: str = "2026-08-01T08:00:00Z",
    pollutant_concentration_mg_per_l: float = 0.40,
    runoff_volume_kl: float = 1000.00,
) -> Dict[str, Any]:
    """A wet-weather sample recorded and then adjudicated by a second operator."""
    observation = record_sample(
        outfall_id, observed_at, pollutant_concentration_mg_per_l, runoff_volume_kl
    )
    return get_success_data(
        api_client.validate_observation(
            observation["id"],
            factories.validate_observation_payload("VALIDATE"),
            OPERATIONS_TWO_HEADERS,
        )
    )


def append_sweeping_run(
    outfall_id: str,
    run_start_date: str,
    run_end_date: str,
    lane_miles_swept: float,
) -> Dict[str, Any]:
    payload = factories.sweeping_run_payload(run_start_date, run_end_date, lane_miles_swept)
    return get_success_data(
        api_client.create_sweeping_run(outfall_id, payload, OPERATIONS_HEADERS)
    )


def assess_load(
    outfall_id: str, variant: str = "FINAL", reporting_year: int = 2026
) -> Dict[str, Any]:
    payload = factories.load_assessment_payload(variant, reporting_year)
    return get_success_data(
        api_client.create_load_assessment(outfall_id, payload, MANAGER_HEADERS)
    )


# ==========================================================================
# Tier 3: illicit discharge cases
# ==========================================================================


def open_case_by_screening(
    outfall_id: str, observed_at: str = "2026-08-01T08:00:00Z"
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Drive the screening cascade that is a case's only origin.

    Returns the suspect observation and the case it opened.
    """
    observation = record_screening(outfall_id, observed_at, suspect=True)
    cases, _ = _list_cases({"origin_observation_id": observation["id"]})
    assert cases, "a SUSPECT screening must open an illicit discharge case"
    return observation, cases[0]


def _list_cases(params: Optional[Dict[str, Any]] = None) -> Tuple[List[Dict[str, Any]], Dict]:
    response = api_client.list_illicit_discharge_cases(MANAGER_HEADERS, params)
    return validate_paginated(response)


def setup_case_in_state(
    outfall_id: str,
    state: str,
    observed_at: str = "2026-08-01T08:00:00Z",
) -> Dict[str, Any]:
    """A case parked at ``OPEN``, ``TRACING`` or ``SOURCE_IDENTIFIED``."""
    _, case = open_case_by_screening(outfall_id, observed_at)
    if state == "OPEN":
        return case
    case = get_success_data(
        api_client.start_tracing(
            case["id"], factories.start_tracing_payload(), IDDE_HEADERS
        )
    )
    if state == "TRACING":
        return case
    case = get_success_data(
        api_client.identify_source(
            case["id"], factories.identify_source_payload(), IDDE_HEADERS
        )
    )
    if state == "SOURCE_IDENTIFIED":
        return case
    raise ValueError(f"unsupported case state for setup: {state}")


def setup_case_in_enforcement(
    outfall_id: str, observed_at: str = "2026-08-01T08:00:00Z"
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """A case driven to ``ENFORCEMENT`` by an action issued against it.

    Returns the case as read back and the enforcement action.
    """
    case = setup_case_in_state(outfall_id, "SOURCE_IDENTIFIED", observed_at)
    action = issue_enforcement_action(illicit_discharge_case_id=case["id"])
    return read_case(case["id"]), action


# ==========================================================================
# Tier 3: construction sites
# ==========================================================================


def create_site(term_id: str, **overrides: Any) -> Dict[str, Any]:
    payload = factories.construction_site_payload(term_id, **overrides)
    return get_success_data(
        api_client.create_construction_site(payload, INSPECTOR_HEADERS), 201
    )


def setup_site_with_approved_plan(
    term_id: str, esc_plan_reference: str = "ESC-A-1", **overrides: Any
) -> Dict[str, Any]:
    """A site whose plan is ``APPROVED`` and whose field is ``ACTIVE_DISTURBANCE``.

    Approval advances the field dimension only because the site is still in
    ``PRE_CONSTRUCTION`` when the plan is approved.
    """
    site = create_site(term_id, **overrides)
    get_success_data(
        api_client.submit_esc_plan(
            site["id"], factories.submit_esc_plan_payload(esc_plan_reference), INSPECTOR_HEADERS
        )
    )
    return get_success_data(
        api_client.esc_review(
            site["id"], factories.esc_review_payload("APPROVE"), INSPECTOR_HEADERS
        )
    )


def setup_stopped_site(term_id: str, **overrides: Any) -> Dict[str, Any]:
    """A site an enforcement officer has driven into ``STOP_WORK``."""
    site = setup_site_with_approved_plan(term_id, **overrides)
    return get_success_data(
        api_client.stop_work(site["id"], factories.stop_work_payload(), OFFICER_HEADERS)
    )


# ==========================================================================
# Tier 3: permanent controls
# ==========================================================================


def create_facility(site_id: str, ownership: str = "PRIVATE", **overrides: Any) -> Dict[str, Any]:
    payload = factories.facility_payload(site_id, ownership, **overrides)
    return get_success_data(
        api_client.create_post_construction_facility(payload, INSPECTOR_HEADERS), 201
    )


def setup_facility_with_agreement(
    site_id: str,
    recorded_at: str = "2026-08-01T00:00:00Z",
    inspection_interval_months: int = 12,
    **overrides: Any,
) -> Dict[str, Any]:
    """A privately owned permanent control whose agreement is ``RECORDED``.

    With the agreement recorded and no inspection yet overdue, the facility is
    credit eligible, which is what the utility credit programme leans on.
    """
    facility = create_facility(site_id, "PRIVATE", **overrides)
    return get_success_data(
        api_client.record_agreement(
            facility["id"],
            factories.record_agreement_payload(recorded_at, inspection_interval_months),
            INSPECTOR_HEADERS,
        )
    )


def setup_credit_eligible_facility(
    term_id: str, disturbed_acres: float = 3.00, **overrides: Any
) -> Dict[str, Any]:
    """A credit-eligible permanent control, together with its owning site."""
    site = setup_site_with_approved_plan(term_id, disturbed_acres=disturbed_acres)
    facility = setup_facility_with_agreement(site["id"], **overrides)
    return {"site": site, "facility": facility}


# ==========================================================================
# Tier 3: inspections
# ==========================================================================


def create_esc_inspection(
    site_id: str,
    period_start: str = "2026-06-01",
    period_end: str = "2026-06-10",
    rainfall_trigger: bool = False,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = factories.esc_inspection_payload(
        site_id, period_start, period_end, rainfall_trigger=rainfall_trigger, **overrides
    )
    return get_success_data(api_client.create_inspection(payload, INSPECTOR_HEADERS), 201)


def create_maintenance_inspection(
    facility_id: str,
    period_start: str = "2026-06-01",
    period_end: str = "2026-06-10",
    **overrides: Any,
) -> Dict[str, Any]:
    payload = factories.maintenance_inspection_payload(
        facility_id, period_start, period_end, **overrides
    )
    return get_success_data(api_client.create_inspection(payload, INSPECTOR_HEADERS), 201)


def add_findings(inspection_id: str, severities: Sequence[str]) -> Dict[str, Any]:
    inspection: Dict[str, Any] = {}
    for severity in severities:
        inspection = get_success_data(
            api_client.add_inspection_finding(
                inspection_id, factories.finding_payload(severity), INSPECTOR_HEADERS
            )
        )
    return inspection


def finalize_inspection(inspection_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(
        api_client.finalize_inspection(inspection_id, headers or INSPECTOR_HEADERS)
    )


def setup_finalized_esc_inspection(
    site_id: str,
    severities: Sequence[str] = ("MINOR",),
    rainfall_trigger: bool = False,
    period_start: str = "2026-06-01",
    period_end: str = "2026-06-10",
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """An erosion-control inspection with a frozen deficiency score."""
    inspection = create_esc_inspection(
        site_id, period_start, period_end, rainfall_trigger=rainfall_trigger
    )
    add_findings(inspection["id"], severities)
    return finalize_inspection(inspection["id"], headers)


def setup_finalized_maintenance_inspection(
    facility_id: str,
    severities: Sequence[str] = ("MINOR",),
    period_start: str = "2026-06-01",
    period_end: str = "2026-06-10",
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    inspection = create_maintenance_inspection(facility_id, period_start, period_end)
    add_findings(inspection["id"], severities)
    return finalize_inspection(inspection["id"], headers)


# ==========================================================================
# Tier 3: enforcement ladder
# ==========================================================================


def issue_enforcement_action(
    action_type: str = "NOTICE_OF_VIOLATION",
    headers: Optional[Dict[str, str]] = None,
    **subject_and_overrides: Any,
) -> Dict[str, Any]:
    """Issue an action naming exactly one subject."""
    payload = factories.enforcement_action_payload(action_type, **subject_and_overrides)
    return get_success_data(
        api_client.create_enforcement_action(payload, headers or OFFICER_HEADERS), 201
    )


def escalate_action(
    action_id: str, headers: Optional[Dict[str, str]] = None, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api_client.escalate_enforcement_action(
            action_id, factories.escalate_payload(**overrides), headers or OFFICER_HEADERS
        )
    )


def rescind_action(action_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api_client.rescind_enforcement_action(
            action_id, factories.rescind_payload(**overrides), OFFICER_HEADERS
        )
    )


def close_action(action_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api_client.close_enforcement_action(
            action_id, factories.close_enforcement_payload(**overrides), OFFICER_HEADERS
        )
    )


# ==========================================================================
# Tier 4: utility accounts, credits and billing
# ==========================================================================


def create_account(
    term_id: str,
    parcel_id: str = "PCL-0001",
    parcel_class: str = "RESIDENTIAL_SINGLE",
    impervious_area_sqft: float = 3000.0,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = factories.account_payload(
        term_id, parcel_id, parcel_class, impervious_area_sqft, **overrides
    )
    return get_success_data(api_client.create_account(payload, CLERK_HEADERS), 201)


def remeasure_account(account_id: str, impervious_area_sqft: float, expected_version: int) -> Dict[str, Any]:
    payload = factories.impervious_update_payload(impervious_area_sqft, expected_version)
    return get_success_data(api_client.create_impervious_update(account_id, payload, CLERK_HEADERS))


def file_credit_application(
    account: Dict[str, Any],
    requested_credit_pct: float = 0.2000,
    facility_id: Optional[str] = None,
    expected_version: Optional[int] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """File an application against an account.

    The default actor is the ``PropertyOwner`` acting as this very account, so
    that ``applicant_user_id`` is the account's own id and resubmission by the
    applicant is possible.
    """
    version = expected_version if expected_version is not None else account["version"]
    overrides: Dict[str, Any] = {}
    if facility_id is not None:
        overrides["post_construction_facility_id"] = facility_id
    payload = factories.credit_application_payload(
        account["id"], version, requested_credit_pct, **overrides
    )
    actor = headers or make_property_owner_headers(account["id"])
    return get_success_data(api_client.create_fee_credit_application(payload, actor), 201)


def review_credit_application(
    application_id: str, decision: str = "APPROVE", **overrides: Any
) -> Dict[str, Any]:
    payload = factories.credit_review_payload(decision, **overrides)
    return get_success_data(
        api_client.review_fee_credit_application(application_id, payload, CLERK_HEADERS)
    )


def setup_approved_credit(
    account: Dict[str, Any],
    requested_credit_pct: float = 0.2000,
    facility_id: Optional[str] = None,
    approved_credit_pct: Optional[float] = None,
) -> Dict[str, Any]:
    """An application already ``APPROVED`` against the account."""
    application = file_credit_application(
        account, requested_credit_pct, facility_id=facility_id
    )
    overrides: Dict[str, Any] = {}
    if approved_credit_pct is not None:
        overrides["approved_credit_pct"] = approved_credit_pct
    return review_credit_application(application["id"], "APPROVE", **overrides)


def setup_returned_credit_application(
    account: Dict[str, Any], requested_credit_pct: float = 0.2000
) -> Dict[str, Any]:
    """An application the clerk has returned to its applicant."""
    application = file_credit_application(account, requested_credit_pct)
    return review_credit_application(
        application["id"], "RETURN", return_reason="Substantiation incomplete."
    )


def run_billing(
    term_id: str,
    run_type: str = "FINAL",
    period_start: str = "2026-01-01",
    period_end: str = "2026-12-31",
) -> Dict[str, Any]:
    payload = factories.billing_run_payload(run_type, period_start, period_end)
    return get_success_data(api_client.create_billing_run(term_id, payload, CLERK_HEADERS))


# ==========================================================================
# Tier 5: annual reports
# ==========================================================================


def create_report(
    term_id: str,
    reporting_period_start: str = "2026-01-01",
    reporting_period_end: str = "2026-12-31",
    **overrides: Any,
) -> Dict[str, Any]:
    payload = factories.annual_report_payload(
        term_id, reporting_period_start, reporting_period_end, **overrides
    )
    return get_success_data(api_client.create_annual_report(payload, MANAGER_HEADERS), 201)


def compile_report(
    report_id: str,
    term_id: str,
    expected_version: Optional[int] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Compile against the term's current version unless one is forced."""
    version = expected_version if expected_version is not None else term_version(term_id)
    payload = factories.compile_report_payload(version)
    return get_success_data(
        api_client.compile_annual_report(report_id, payload, headers or MANAGER_HEADERS)
    )


def setup_compiled_report(
    term_id: str,
    reporting_period_start: str = "2026-01-01",
    reporting_period_end: str = "2026-12-31",
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """A report frozen at ``COMPILED`` by the first manager."""
    report = create_report(term_id, reporting_period_start, reporting_period_end)
    return compile_report(report["id"], term_id, headers=headers)


def certify_report(report_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Certify a compiled report using a manager other than the compiler."""
    return get_success_data(
        api_client.certify_annual_report(
            report_id, factories.certify_report_payload(), headers or MANAGER_TWO_HEADERS
        )
    )


def setup_certified_report(
    term_id: str,
    reporting_period_start: str = "2026-01-01",
    reporting_period_end: str = "2026-12-31",
) -> Dict[str, Any]:
    """A report compiled by ``mgr-01`` and certified by ``mgr-02``."""
    report = setup_compiled_report(term_id, reporting_period_start, reporting_period_end)
    return certify_report(report["id"])
