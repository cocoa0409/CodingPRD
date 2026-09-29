"""Composite setup helpers.

Every helper builds its preconditions from scratch through PRD-declared
endpoints only, and uses the lenient `get_success_data` validator so a broken
precondition surfaces as a setup failure rather than as a confusing assertion.

`FacilityOperator` calls always thread the facility's own `operator_org`
through `make_facility_operator_headers`, because the server compares that
value against `X-User-ID` (PRD §2.1).
"""
from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS
from .factories import (
    allowance_account_payload,
    allowance_transaction_payload,
    appendix_d_hour_payload,
    bulk_hours_payload,
    cems_hour_payload,
    certification_payload,
    control_outage_payload,
    daily_calibration_payload,
    facility_payload,
    fuel_analysis_payload,
    fuel_sample_payload,
    monitoring_system_payload,
    permit_limit_payload,
    quarterly_report_payload,
    rata_runs_payload,
    rata_test_payload,
    single_hour_payload,
    unit_payload,
)
from .test_users import TEST_USERS, make_facility_operator_headers

# The recipes in this suite pin the logical clock before anything else so that
# every window rule and every deadline comparison is deterministic.
CLOCK_Q2 = "2026-04-02T00:00:00Z"
TRUE_UP_DEADLINE = "2027-03-01T00:00:00Z"

REVIEWER = TEST_USERS["regulatory_reviewer_headers"]
QA = TEST_USERS["qa_analyst_headers"]
PREPARER = TEST_USERS["preparer_headers"]
SECOND_PREPARER = TEST_USERS["second_preparer_headers"]
REPRESENTATIVE = TEST_USERS["representative_headers"]
SECOND_REPRESENTATIVE = TEST_USERS["second_representative_headers"]
TRADER = TEST_USERS["allowance_trader_headers"]


# --------------------------------------------------------------------------
# Tier 1 — single steps
# --------------------------------------------------------------------------
def set_clock(to_iso8601: str = CLOCK_Q2, headers: Optional[Dict] = None) -> Dict:
    return get_success_data(
        api_client.set_clock({"to_iso8601": to_iso8601}, headers or REVIEWER)
    )


def create_facility(**overrides) -> Dict:
    # An explicit `true_up_deadline_utc` override wins over the suite default;
    # passing both positionally raised a TypeError.
    overrides.setdefault("true_up_deadline_utc", TRUE_UP_DEADLINE)
    payload = facility_payload(**overrides)
    return get_success_data(api_client.create_facility(payload, REVIEWER))


def create_unit(facility_id: str, **overrides) -> Dict:
    return get_success_data(
        api_client.create_unit(facility_id, unit_payload(**overrides), REVIEWER)
    )


def bring_unit_online(unit_id: str, operator_org: str) -> Dict:
    return get_success_data(
        api_client.set_unit_dispatch(
            unit_id,
            {"dispatch_state": "ONLINE"},
            make_facility_operator_headers(operator_org),
        )
    )


def install_monitoring_system(unit_id: str, **overrides) -> Dict:
    return get_success_data(
        api_client.install_monitoring_system(
            unit_id, monitoring_system_payload(**overrides), QA
        )
    )


def record_daily_calibration(
    system_id: str, expected_monitoring_system_version: int, **overrides
) -> Dict:
    return get_success_data(
        api_client.record_daily_calibration(
            system_id,
            daily_calibration_payload(expected_monitoring_system_version, **overrides),
            QA,
        )
    )


def drive_qa_status(system_id: str, action: str, **extra) -> Dict:
    payload = {"action": action}
    payload.update(extra)
    return get_success_data(api_client.drive_qa_status(system_id, payload, QA))


def open_quarterly_report(
    unit_id: str, year: int = 2026, quarter: int = 2, headers: Optional[Dict] = None
) -> Dict:
    return get_success_data(
        api_client.open_quarterly_report(
            unit_id, quarterly_report_payload(year, quarter), headers or PREPARER
        )
    )


def append_hour(
    unit_id: str,
    expected_quarterly_report_version: int,
    hour: Dict[str, Any],
    headers: Optional[Dict] = None,
) -> Dict:
    return get_success_data(
        api_client.append_operating_hour(
            unit_id,
            single_hour_payload(expected_quarterly_report_version, hour),
            headers or PREPARER,
        )
    )


def append_hours_bulk(
    unit_id: str,
    expected_quarterly_report_version: int,
    hours: List[Dict[str, Any]],
    headers: Optional[Dict] = None,
) -> List[Dict]:
    return get_success_data(
        api_client.append_operating_hours_bulk(
            unit_id,
            bulk_hours_payload(expected_quarterly_report_version, hours),
            headers or PREPARER,
        )
    )


def open_allowance_account(facility_id: str, **overrides) -> Dict:
    return get_success_data(
        api_client.open_allowance_account(
            facility_id, allowance_account_payload(**overrides), REVIEWER
        )
    )


def create_permit_limit(unit_id: str, **overrides) -> Dict:
    return get_success_data(
        api_client.create_permit_limit(unit_id, permit_limit_payload(**overrides), REVIEWER)
    )


def evaluate_permit_limit(permit_limit_id: str, anchor_utc: str) -> Dict:
    return get_success_data(
        api_client.evaluate_permit_limit(
            permit_limit_id, {"anchor_utc": anchor_utc}, REVIEWER
        )
    )


def plan_control_outage(unit_id: str, operator_org: str, **overrides) -> Dict:
    return get_success_data(
        api_client.plan_control_outage(
            unit_id,
            control_outage_payload(**overrides),
            make_facility_operator_headers(operator_org),
        )
    )


def transition_control_outage(
    outage_id: str, operator_org: str, action: str, **extra
) -> Dict:
    payload = {"action": action}
    payload.update(extra)
    return get_success_data(
        api_client.transition_control_outage(
            outage_id, payload, make_facility_operator_headers(operator_org)
        )
    )


# --------------------------------------------------------------------------
# Hour templates used by several recipes
# --------------------------------------------------------------------------
def cems_hours(
    count: int,
    start_hour: int = 0,
    day: str = "2026-04-01",
    **hour_overrides,
) -> List[Dict[str, Any]]:
    """`count` consecutive identical CEMS hours starting at `start_hour`."""
    return [
        cems_hour_payload(f"{day}T{(start_hour + i):02d}:00:00Z", **hour_overrides)
        for i in range(count)
    ]


HIGH_EMISSION_HOUR = {
    "flow_scfh": 20000000.0,
    "co2_conc_pct": 12.5,
    "so2_conc_ppm": 1500.0,
    "nox_rate_lb_mmbtu": 0.150,
}


# --------------------------------------------------------------------------
# Tier 2 — station hierarchy
# --------------------------------------------------------------------------
def setup_facility_and_unit(
    clock: Optional[str] = CLOCK_Q2,
    online: bool = False,
    facility_overrides: Optional[Dict] = None,
    unit_overrides: Optional[Dict] = None,
) -> Dict[str, Any]:
    """Logical clock + one facility + one unit. The workhorse preamble."""
    if clock:
        set_clock(clock)
    facility = create_facility(**(facility_overrides or {}))
    unit = create_unit(facility["id"], **(unit_overrides or {}))
    if online:
        unit = bring_unit_online(unit["id"], facility["operator_org"])
    return {"facility": facility, "unit": unit}


def setup_certified_cem(
    unit_id: str,
    parameter: str = "SO2",
    span_value: float = 400.0,
    calibration_error_spec_pct: float = 2.5,
    calibration_utc: str = "2026-04-01T00:00:00Z",
    span_reference_value: Optional[float] = None,
    span_measured_value: Optional[float] = None,
) -> Dict[str, Any]:
    """Install a CEM, pass one calibration (so `cal_status` is `CAL_CURRENT`)
    and certify it. Returns the system as it stands after certification."""
    system = install_monitoring_system(
        unit_id,
        parameter=parameter,
        system_type="CEM",
        span_value=span_value,
        calibration_error_spec_pct=calibration_error_spec_pct,
    )
    if span_reference_value is None:
        span_reference_value = round(span_value * 0.9, 6)
    if span_measured_value is None:
        # 2.00 % of span — comfortably inside the 2.5 % specification.
        span_measured_value = round(span_reference_value + span_value * 0.02, 6)
    calibration = record_daily_calibration(
        system["id"],
        system["version"],
        calibration_utc=calibration_utc,
        span_reference_value=span_reference_value,
        span_measured_value=span_measured_value,
    )
    certified = drive_qa_status(system["id"], "CERTIFY")
    return {"system": certified, "calibration": calibration}


def setup_certified_so2_station(
    clock: Optional[str] = CLOCK_Q2,
    online: bool = False,
    span_value: float = 400.0,
    calibration_error_spec_pct: float = 2.5,
    facility_overrides: Optional[Dict] = None,
    unit_overrides: Optional[Dict] = None,
) -> Dict[str, Any]:
    """Facility + unit + one CERTIFIED, CAL_CURRENT SO2 CEM."""
    station = setup_facility_and_unit(
        clock=clock,
        online=online,
        facility_overrides=facility_overrides,
        unit_overrides=unit_overrides,
    )
    cem = setup_certified_cem(
        station["unit"]["id"],
        span_value=span_value,
        calibration_error_spec_pct=calibration_error_spec_pct,
    )
    station["system"] = cem["system"]
    station["calibration"] = cem["calibration"]
    return station


def setup_analyzed_fuel_sample(
    unit_id: str, operator_org: str, analysis_overrides: Optional[Dict] = None, **overrides
) -> Dict:
    """A fuel sample standing at ANALYZED, ready to back an Appendix D hour."""
    sample = get_success_data(
        api_client.record_fuel_sample(
            unit_id,
            fuel_sample_payload(**overrides),
            make_facility_operator_headers(operator_org),
        )
    )
    return get_success_data(
        api_client.record_fuel_analysis(
            sample["id"], fuel_analysis_payload(**(analysis_overrides or {})), QA
        )
    )


def setup_appendix_d_system(
    unit_id: str, parameter: str = "CO2", span_value: float = 20.0
) -> Dict:
    """A CERTIFIED, CAL_CURRENT excepted Appendix D system on the unit."""
    system = install_monitoring_system(
        unit_id,
        parameter=parameter,
        system_type="EXCEPTED_APPENDIX_D",
        span_value=span_value,
        calibration_error_spec_pct=2.5,
    )
    record_daily_calibration(
        system["id"],
        system["version"],
        calibration_utc="2026-04-01T00:00:00Z",
        span_reference_value=round(span_value * 0.9, 6),
        span_measured_value=round(span_value * 0.9 + span_value * 0.02, 6),
    )
    return drive_qa_status(system["id"], "CERTIFY")


# --------------------------------------------------------------------------
# Tier 3 — report lifecycle shortcuts
# --------------------------------------------------------------------------
def setup_draft_report_with_cems_hours(
    hour_count: int = 3,
    clock: Optional[str] = CLOCK_Q2,
    span_value: float = 400.0,
    hour_overrides: Optional[Dict] = None,
    year: int = 2026,
    quarter: int = 2,
    online: bool = False,
) -> Dict[str, Any]:
    """Station with a CERTIFIED SO2 CEM and a DRAFT report carrying
    `hour_count` identical MEASURED CEMS hours appended in one bulk call."""
    station = setup_certified_so2_station(
        clock=clock, online=online, span_value=span_value
    )
    report = open_quarterly_report(station["unit"]["id"], year, quarter)
    hours = append_hours_bulk(
        station["unit"]["id"],
        report["version"],
        cems_hours(hour_count, **(hour_overrides or {})),
    )
    station["report"] = get_success_data(
        api_client.get_quarterly_report(report["id"], PREPARER)
    )
    station["hours"] = hours
    return station


def setup_dual_method_station(
    clock: Optional[str] = CLOCK_Q2,
    gcv_btu_per_lb: float = 12500.0,
    sulfur_content_pct: float = 0.85,
    year: int = 2026,
    quarter: int = 2,
) -> Dict[str, Any]:
    """A unit able to record hours under BOTH determination methods: a
    CERTIFIED SO2 CEM, a CERTIFIED excepted Appendix D CO2 system, one ANALYZED
    fuel sample and an empty DRAFT report."""
    station = setup_certified_so2_station(clock=clock)
    station["appendix_d_system"] = setup_appendix_d_system(station["unit"]["id"])
    station["fuel_sample"] = setup_analyzed_fuel_sample(
        station["unit"]["id"],
        station["facility"]["operator_org"],
        analysis_overrides={
            "gcv_btu_per_lb": gcv_btu_per_lb,
            "sulfur_content_pct": sulfur_content_pct,
        },
    )
    station["report"] = open_quarterly_report(station["unit"]["id"], year, quarter)
    return station


def setup_appendix_d_only_station(
    clock: Optional[str] = CLOCK_Q2,
    gcv_btu_per_lb: float = 12500.0,
    sulfur_content_pct: float = 0.85,
) -> Dict[str, Any]:
    """A gas unit whose only monitoring system is a CERTIFIED excepted
    Appendix D CO2 system, with one ANALYZED sample and an empty DRAFT report."""
    station = setup_facility_and_unit(
        clock=clock,
        unit_overrides={
            "primary_fuel": "NATURAL_GAS",
            "nameplate_capacity_mw": 300,
            "max_rated_heat_input_mmbtu_hr": 3000,
            "control_device": "NONE",
        },
    )
    station["appendix_d_system"] = setup_appendix_d_system(station["unit"]["id"])
    station["fuel_sample"] = setup_analyzed_fuel_sample(
        station["unit"]["id"],
        station["facility"]["operator_org"],
        analysis_overrides={
            "gcv_btu_per_lb": gcv_btu_per_lb,
            "sulfur_content_pct": sulfur_content_pct,
        },
        fuel_type="NATURAL_GAS",
        lot_identifier="LOT-G1",
    )
    station["report"] = open_quarterly_report(station["unit"]["id"])
    return station


def validate_report(report_id: str, headers: Optional[Dict] = None) -> Dict:
    return get_success_data(
        api_client.validate_quarterly_report(report_id, {}, headers or PREPARER)
    )


def submit_report(
    report_id: str, submission_format: str = "XML_ECMPS", headers: Optional[Dict] = None
) -> Dict:
    return get_success_data(
        api_client.submit_quarterly_report(
            report_id, {"submission_format": submission_format}, headers or PREPARER
        )
    )


def sign_certification(
    report_id: str,
    expected_quarterly_report_version: int,
    headers: Optional[Dict] = None,
    **overrides,
) -> Dict:
    return get_success_data(
        api_client.sign_certification(
            report_id,
            certification_payload(expected_quarterly_report_version, **overrides),
            headers or REPRESENTATIVE,
        )
    )


def accept_report(report_id: str) -> Dict:
    return get_success_data(
        api_client.disposition_quarterly_report(
            report_id, {"decision": "ACCEPT"}, REVIEWER
        )
    )


def reject_report(report_id: str, reason: str) -> Dict:
    return get_success_data(
        api_client.disposition_quarterly_report(
            report_id, {"decision": "REJECT", "reason": reason}, REVIEWER
        )
    )


def drive_report_to_certified(
    report_id: str,
    preparer_headers: Optional[Dict] = None,
    signer_headers: Optional[Dict] = None,
) -> Dict[str, Any]:
    """DRAFT -> VALIDATED -> SUBMITTED -> CERTIFIED. Returns report and
    certification as they stand after signing."""
    validate_report(report_id, preparer_headers)
    submitted = submit_report(report_id, headers=preparer_headers)
    certification = sign_certification(
        report_id, submitted["version"], headers=signer_headers
    )
    report = get_success_data(api_client.get_quarterly_report(report_id, PREPARER))
    return {"report": report, "certification": certification}


def drive_report_to_accepted(
    report_id: str,
    preparer_headers: Optional[Dict] = None,
    signer_headers: Optional[Dict] = None,
) -> Dict[str, Any]:
    result = drive_report_to_certified(report_id, preparer_headers, signer_headers)
    result["report"] = accept_report(report_id)
    return result


def setup_accepted_report_with_hours(
    hour_count: int = 12,
    hour_overrides: Optional[Dict] = None,
    span_value: float = 2000.0,
    clock: Optional[str] = CLOCK_Q2,
    online: bool = False,
    facility_overrides: Optional[Dict] = None,
    second_unit: bool = False,
) -> Dict[str, Any]:
    """A full year-quarter of accepted emissions, ready for a true-up."""
    station = setup_facility_and_unit(
        clock=clock, online=online, facility_overrides=facility_overrides
    )
    if second_unit:
        station["unit2"] = create_unit(
            station["facility"]["id"],
            unit_identifier="U2",
            primary_fuel="NATURAL_GAS",
            nameplate_capacity_mw=200,
            max_rated_heat_input_mmbtu_hr=2000,
            control_device="NONE",
        )
    cem = setup_certified_cem(station["unit"]["id"], span_value=span_value)
    station["system"] = cem["system"]
    report = open_quarterly_report(station["unit"]["id"])
    append_hours_bulk(
        station["unit"]["id"],
        report["version"],
        cems_hours(hour_count, **(hour_overrides or HIGH_EMISSION_HOUR)),
    )
    lifecycle = drive_report_to_accepted(report["id"])
    station["report"] = lifecycle["report"]
    station["certification"] = lifecycle["certification"]
    return station


# --------------------------------------------------------------------------
# Tier 4 — allowance / true-up targeting
# --------------------------------------------------------------------------
def propose_transaction(
    account_id: str, expected_version: int, **overrides
) -> Dict:
    return get_success_data(
        api_client.propose_allowance_transaction(
            allowance_transaction_payload(expected_version, account_id, **overrides),
            TRADER,
        )
    )


def transition_transaction(transaction_id: str, action: str, **extra) -> Dict:
    payload = {"action": action}
    payload.update(extra)
    return get_success_data(
        api_client.transition_allowance_transaction(
            transaction_id, payload, REPRESENTATIVE
        )
    )


def settle_transaction(account_id: str, expected_version: int, **overrides) -> Dict:
    """Propose, record and settle one transaction. Returns the SETTLED row."""
    transaction = propose_transaction(account_id, expected_version, **overrides)
    transition_transaction(transaction["id"], "RECORD")
    return transition_transaction(transaction["id"], "SETTLE")


def setup_true_up_shortfall_state(
    holdings_prior: float = 7.0,
    holdings_current: float = 18.0,
    holdings_next: float = 15.0,
    hour_count: int = 12,
    second_unit: bool = True,
    run_true_up: bool = True,
) -> Dict[str, Any]:
    """Station with an ACCEPTED quarter, an allowance account endowed below the
    resulting obligation, the clock advanced to the true-up deadline, and — when
    `run_true_up` is set — the true-up already run so the account stands at
    TRUE_UP_LOCKED with its surrender and penalty rows."""
    station = setup_accepted_report_with_hours(
        hour_count=hour_count, online=True, second_unit=second_unit
    )
    station["account"] = open_allowance_account(
        station["facility"]["id"],
        holdings_prior_vintage_tons=holdings_prior,
        holdings_current_vintage_tons=holdings_current,
        holdings_next_vintage_tons=holdings_next,
    )
    set_clock(TRUE_UP_DEADLINE)
    if run_true_up:
        station["account"] = get_success_data(
            api_client.run_true_up(station["account"]["id"], {}, REVIEWER)
        )
        transactions = get_success_data(
            api_client.list_allowance_transactions(
                REVIEWER, {"allowance_account_id": station["account"]["id"]}
            )
        )
        station["transactions"] = transactions
        station["surrender_transaction"] = next(
            (t for t in transactions if t["origin"] == "TRUE_UP_SURRENDER"), None
        )
        station["penalty_transaction"] = next(
            (t for t in transactions if t["origin"] == "TRUE_UP_PENALTY"), None
        )
    return station


# --------------------------------------------------------------------------
# Tier 5 — audits, limits and events
# --------------------------------------------------------------------------

# Nine paired measurements with a reference mean of 0.2700 and a monitor mean
# of 0.2481: relative accuracy 10.0 percent against the reference mean.
RATA_RUNS_PASSING: List[Dict[str, float]] = [
    {"reference_value": 0.262, "cems_value": 0.248},
    {"reference_value": 0.266, "cems_value": 0.240},
    {"reference_value": 0.268, "cems_value": 0.234},
    {"reference_value": 0.270, "cems_value": 0.252},
    {"reference_value": 0.270, "cems_value": 0.256},
    {"reference_value": 0.272, "cems_value": 0.252},
    {"reference_value": 0.274, "cems_value": 0.240},
    {"reference_value": 0.274, "cems_value": 0.260},
    {"reference_value": 0.274, "cems_value": 0.251},
]

# The same reference values against a monitor mean of 0.2456: relative accuracy
# 10.7 percent against the reference mean, 5.8 against a 0.500 standard.
RATA_RUNS_FAILING: List[Dict[str, float]] = [
    {"reference_value": 0.262, "cems_value": 0.246},
    {"reference_value": 0.266, "cems_value": 0.236},
    {"reference_value": 0.268, "cems_value": 0.244},
    {"reference_value": 0.270, "cems_value": 0.258},
    {"reference_value": 0.270, "cems_value": 0.238},
    {"reference_value": 0.272, "cems_value": 0.248},
    {"reference_value": 0.274, "cems_value": 0.254},
    {"reference_value": 0.274, "cems_value": 0.246},
    {"reference_value": 0.274, "cems_value": 0.240},
]


def setup_scheduled_rata_test(
    parameter: str = "NOX_RATE",
    span_value: float = 0.800,
    online: bool = True,
    clock: Optional[str] = CLOCK_Q2,
    certify_system: bool = False,
    **rata_overrides,
) -> Dict[str, Any]:
    """Station + one monitoring system + one SCHEDULED audit."""
    station = setup_facility_and_unit(clock=clock, online=online)
    if certify_system:
        cem = setup_certified_cem(
            station["unit"]["id"], parameter=parameter, span_value=span_value
        )
        station["system"] = cem["system"]
    else:
        station["system"] = install_monitoring_system(
            station["unit"]["id"],
            parameter=parameter,
            system_type="CEM",
            span_value=span_value,
        )
    station["rata_test"] = get_success_data(
        api_client.schedule_rata_test(
            station["system"]["id"], rata_test_payload(**rata_overrides), QA
        )
    )
    return station


def record_rata_runs(rata_test_id: str, pairs: List[Dict[str, float]]) -> Dict:
    return get_success_data(
        api_client.record_rata_runs(rata_test_id, rata_runs_payload(pairs), QA)
    )


def evaluate_rata_test(rata_test_id: str, ra_basis: str = "REFERENCE_MEAN") -> Dict:
    return get_success_data(
        api_client.evaluate_rata_test(rata_test_id, {"ra_basis": ra_basis}, QA)
    )


def setup_exceeded_permit_limit(
    hour_count: int = 3,
    limit_value: float = 250.0,
    anchor_utc: str = "2026-04-01T03:00:00Z",
    hour_overrides: Optional[Dict] = None,
    validate: bool = False,
    **limit_overrides,
) -> Dict[str, Any]:
    """Station with measured hours, one permit limit already evaluated at
    `anchor_utc`, and — when the rolling value exceeds — one DETECTED event."""
    station = setup_draft_report_with_cems_hours(
        hour_count=hour_count, hour_overrides=hour_overrides
    )
    station["permit_limit"] = create_permit_limit(
        station["unit"]["id"], limit_value=limit_value, **limit_overrides
    )
    station["permit_limit"] = evaluate_permit_limit(
        station["permit_limit"]["id"], anchor_utc
    )
    events = get_success_data(
        api_client.list_excess_emission_events(
            REVIEWER, {"permit_limit_id": station["permit_limit"]["id"]}
        )
    )
    station["events"] = events
    station["event"] = events[0] if events else None
    if validate:
        station["report"] = validate_report(station["report"]["id"])
    return station


def file_and_review_event(event_id: str) -> Dict:
    get_success_data(
        api_client.file_excess_emission_report(
            event_id,
            {
                "narrative": "Wet scrubber recycle pump tripped during the hour.",
                "corrective_action": "Pump rebuilt and returned to service.",
            },
            PREPARER,
        )
    )
    return get_success_data(
        api_client.review_excess_emission_event(event_id, {}, REVIEWER)
    )
