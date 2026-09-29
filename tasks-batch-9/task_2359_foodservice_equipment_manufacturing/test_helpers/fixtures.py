"""Composite setup helpers.

The harness restarts the API server before every test, so each test starts
against an empty database and must build all of its preconditions through the
endpoints the PRD declares. These helpers assemble the recurring chains:

  tier 1  single rows in a chosen state
  tier 2  parent/child hierarchies (model + listing, chain + configuration, ...)
  tier 3  full-lifecycle shortcuts (a RELEASED configuration, an AUTHORIZED
          service partner, an ACTIVE coverage)
  tier 4  accumulation / threshold targeting (reserve utilisation bands,
          committed-unit ledgers, cohort-sized fleets)
  tier 5  finalisation and terminal states (completed slots, closed campaigns)

Every helper accepts ``**overrides`` that are merged into the request body, and
uses the lenient ``get_success_data`` so a broken precondition fails loudly as
a setup error rather than as a misleading assertion.
"""

from typing import Any, Iterable, List, Optional, Sequence, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import DEFAULT_CLOCK_UTC
from .factories import (
    PASSING_TEST_RUNS,
    adjudication_payload,
    agency_decision_payload,
    branding_signoff_payload,
    build_line_payload,
    build_progress_payload,
    campaign_close_payload,
    certification_listing_payload,
    chain_account_payload,
    chain_configuration_payload,
    connected_unit_payload,
    construction_program_payload,
    coverage_action_payload,
    engineering_decision_payload,
    equipment_model_payload,
    firmware_campaign_payload,
    partner_authorization_payload,
    performance_validation_payload,
    production_slot_payload,
    service_partner_payload,
    site_order_payload,
    technician_certification_payload,
    technician_grade_payload,
    test_run_payload,
    unit_result_payload,
    warranty_claim_payload,
)
from .test_users import (
    TEST_USERS,
    make_chain_admin_headers,
    make_service_partner_headers,
)

Row = dict[str, Any]
TestRun = Tuple[int, int, float]


# ==========================================================================
# Tier 1 -- clock and single rows
# ==========================================================================


def set_clock(to_iso8601: str = DEFAULT_CLOCK_UTC) -> Row:
    """Move the server's logical clock (PRD §2.5, PlatformAdmin only)."""
    response = api_client.set_clock(to_iso8601, TEST_USERS["platform_admin"])
    return get_success_data(response)


def create_equipment_model(**overrides: Any) -> Row:
    response = api_client.create_equipment_model(
        equipment_model_payload(**overrides), TEST_USERS["compliance_engineer"]
    )
    return get_success_data(response, 201)


def create_chain_account(**overrides: Any) -> Row:
    response = api_client.create_chain_account(
        chain_account_payload(**overrides), TEST_USERS["channel_manager"]
    )
    return get_success_data(response, 201)


def create_build_line(**overrides: Any) -> Row:
    response = api_client.create_build_line(
        build_line_payload(**overrides), TEST_USERS["production_planner"]
    )
    return get_success_data(response, 201)


def create_service_partner(**overrides: Any) -> Row:
    response = api_client.create_service_partner(
        service_partner_payload(**overrides), TEST_USERS["channel_manager"]
    )
    return get_success_data(response, 201)


def create_connected_unit(
    equipment_model_id: str, serial_number: str = "SN-1", **overrides: Any
) -> Row:
    response = api_client.create_connected_unit(
        connected_unit_payload(equipment_model_id, serial_number, **overrides),
        TEST_USERS["connected_ops_engineer"],
    )
    return get_success_data(response, 201)


def create_firmware_campaign(
    equipment_model_id: str, campaign_code: str = "FW-1", **overrides: Any
) -> Row:
    response = api_client.create_firmware_campaign(
        firmware_campaign_payload(equipment_model_id, campaign_code, **overrides),
        TEST_USERS["connected_ops_engineer"],
    )
    return get_success_data(response, 201)


# ==========================================================================
# Tier 2 -- certification hierarchy
# ==========================================================================


def file_certification_listing(
    equipment_model_id: str,
    agency_code: str = "AGENCY_GAMMA",
    scopes: Optional[List[str]] = None,
    **overrides: Any,
) -> Row:
    response = api_client.create_certification_listing(
        certification_listing_payload(
            equipment_model_id, agency_code, scopes, **overrides
        ),
        TEST_USERS["compliance_engineer"],
    )
    return get_success_data(response, 201)


def submit_certification_listing(listing_id: str, headers: Optional[Row] = None) -> Row:
    response = api_client.submit_certification_listing(
        listing_id, {}, headers or TEST_USERS["compliance_engineer"]
    )
    return get_success_data(response)


def record_agency_decision(listing_id: str, decision: str, **overrides: Any) -> Row:
    response = api_client.record_agency_decision(
        listing_id,
        agency_decision_payload(decision, **overrides),
        TEST_USERS["listing_reviewer"],
    )
    return get_success_data(response)


def grant_certification_listing(listing_id: str) -> Row:
    """Walk DRAFT -> SUBMITTED -> UNDER_REVIEW -> LISTED for one listing."""
    submit_certification_listing(listing_id)
    record_agency_decision(listing_id, "ACKNOWLEDGE_REVIEW")
    return record_agency_decision(listing_id, "GRANT")


def setup_listed_model(
    agency_code: str = "AGENCY_GAMMA",
    scopes: Optional[List[str]] = None,
    **model_overrides: Any,
) -> Row:
    """A model whose certification posture has been derived to LISTED.

    Returns ``{"model": ..., "listing": ...}`` where the model row is re-read
    after the grant so its derived posture is current.
    """
    model = create_equipment_model(**model_overrides)
    listing = file_certification_listing(model["id"], agency_code, scopes)
    listing = grant_certification_listing(listing["id"])
    model = get_success_data(
        api_client.get_equipment_model(model["id"], TEST_USERS["compliance_engineer"])
    )
    return {"model": model, "listing": listing}


# ==========================================================================
# Tier 2 -- chain configuration hierarchy
# ==========================================================================


def create_chain_configuration(
    chain_account_id: str,
    equipment_model_id: str,
    expected_chain_account_version: Optional[int] = None,
    **overrides: Any,
) -> Row:
    """Create a configuration, re-reading the parent account version if needed.

    PRD §2.7 requires the caller to echo the chain account's current version.
    """
    if expected_chain_account_version is None:
        account = get_success_data(
            api_client.get_chain_account(
                chain_account_id, TEST_USERS["channel_manager"]
            )
        )
        expected_chain_account_version = account["version"]
    response = api_client.create_chain_configuration(
        chain_configuration_payload(
            chain_account_id,
            equipment_model_id,
            expected_chain_account_version,
            **overrides,
        ),
        TEST_USERS["application_engineer"],
    )
    return get_success_data(response, 201)


def open_performance_validation(
    chain_configuration_id: str,
    expected_chain_configuration_version: Optional[int] = None,
    **overrides: Any,
) -> Row:
    """Open a validation, echoing the configuration's current version."""
    if expected_chain_configuration_version is None:
        config = get_success_data(
            api_client.get_chain_configuration(
                chain_configuration_id, TEST_USERS["application_engineer"]
            )
        )
        expected_chain_configuration_version = config["version"]
    response = api_client.create_performance_validation(
        performance_validation_payload(
            chain_configuration_id,
            expected_chain_configuration_version,
            **overrides,
        ),
        TEST_USERS["application_engineer"],
    )
    return get_success_data(response, 201)


def add_test_runs(validation_id: str, runs: Sequence[TestRun]) -> Row:
    """Append a series of menu-item test runs to a validation."""
    data: Row = {}
    for units_produced, minutes, hold_temp_c in runs:
        data = get_success_data(
            api_client.add_test_run(
                validation_id,
                test_run_payload(units_produced, minutes, hold_temp_c),
                TEST_USERS["application_engineer"],
            )
        )
    return data


def conclude_validation(validation_id: str) -> Row:
    response = api_client.conclude_performance_validation(
        validation_id, {}, TEST_USERS["application_engineer"]
    )
    return get_success_data(response)


def retest_validation(validation_id: str) -> Row:
    response = api_client.retest_performance_validation(
        validation_id, {}, TEST_USERS["application_engineer"]
    )
    return get_success_data(response)


def setup_passed_validation(
    chain_configuration_id: str,
    runs: Sequence[TestRun] = PASSING_TEST_RUNS,
    **overrides: Any,
) -> Row:
    """A PASSED validation for the given configuration."""
    validation = open_performance_validation(chain_configuration_id, **overrides)
    add_test_runs(validation["id"], runs)
    return conclude_validation(validation["id"])


# ==========================================================================
# Tier 3 -- full configuration lifecycle
# ==========================================================================


def submit_configuration(config_id: str) -> Row:
    response = api_client.submit_chain_configuration(
        config_id, {}, TEST_USERS["application_engineer"]
    )
    return get_success_data(response)


def approve_configuration(config_id: str) -> Row:
    response = api_client.record_engineering_decision(
        config_id,
        engineering_decision_payload("APPROVE"),
        TEST_USERS["engineering_approver"],
    )
    return get_success_data(response)


def request_configuration_revision(config_id: str, revision_note: str) -> Row:
    response = api_client.record_engineering_decision(
        config_id,
        engineering_decision_payload("REQUEST_REVISION", revision_note=revision_note),
        TEST_USERS["engineering_approver"],
    )
    return get_success_data(response)


def sign_off_branding(
    config_id: str, chain_account_id: str, approved_artwork_ref: str = "ART-1"
) -> Row:
    response = api_client.sign_off_branding(
        config_id,
        branding_signoff_payload(approved_artwork_ref=approved_artwork_ref),
        make_chain_admin_headers(chain_account_id),
    )
    return get_success_data(response)


def release_configuration(config_id: str) -> Row:
    response = api_client.release_chain_configuration(
        config_id, {}, TEST_USERS["application_engineer"]
    )
    return get_success_data(response)


def setup_approved_configuration(
    model_overrides: Optional[Row] = None,
    account_overrides: Optional[Row] = None,
    config_overrides: Optional[Row] = None,
    validation_overrides: Optional[Row] = None,
    runs: Sequence[TestRun] = PASSING_TEST_RUNS,
    agency_code: str = "AGENCY_GAMMA",
    scopes: Optional[List[str]] = None,
    sign_off: bool = True,
    set_initial_clock: bool = True,
) -> Row:
    """A configuration in ENG_APPROVED with branding signed off.

    Returns ``{"model", "listing", "chain_account", "config", "validation"}``.
    """
    if set_initial_clock:
        set_clock()
    listed = setup_listed_model(agency_code, scopes, **(model_overrides or {}))
    account = create_chain_account(**(account_overrides or {}))
    config = create_chain_configuration(
        account["id"], listed["model"]["id"], **(config_overrides or {})
    )
    validation = setup_passed_validation(
        config["id"], runs, **(validation_overrides or {})
    )
    submit_configuration(config["id"])
    config = approve_configuration(config["id"])
    if sign_off:
        config = sign_off_branding(config["id"], account["id"])
    return {
        "model": listed["model"],
        "listing": listed["listing"],
        "chain_account": account,
        "config": config,
        "validation": validation,
    }


def setup_released_configuration(**kwargs: Any) -> Row:
    """A configuration walked all the way to RELEASED with a firm price."""
    state = setup_approved_configuration(**kwargs)
    state["config"] = release_configuration(state["config"]["id"])
    return state


# ==========================================================================
# Tier 3 -- programmes, site orders and slots
# ==========================================================================


def create_construction_program(chain_account_id: str, **overrides: Any) -> Row:
    response = api_client.create_construction_program(
        construction_program_payload(chain_account_id, **overrides),
        make_chain_admin_headers(chain_account_id),
    )
    return get_success_data(response, 201)


def create_site_order(
    construction_program_id: str,
    chain_configuration_id: str,
    chain_account_id: str,
    **overrides: Any,
) -> Row:
    response = api_client.create_site_order(
        site_order_payload(
            construction_program_id, chain_configuration_id, **overrides
        ),
        make_chain_admin_headers(chain_account_id),
    )
    return get_success_data(response, 201)


def reserve_production_slot(
    build_line_id: str, site_order_id: str, **overrides: Any
) -> Row:
    response = api_client.create_production_slot(
        production_slot_payload(build_line_id, site_order_id, **overrides),
        TEST_USERS["production_planner"],
    )
    return get_success_data(response, 201)


def advance_slot(slot_id: str, progress: str) -> Row:
    response = api_client.advance_build_progress(
        slot_id, build_progress_payload(progress), TEST_USERS["production_planner"]
    )
    return get_success_data(response)


def setup_program_with_site_order(
    released: Optional[Row] = None,
    program_overrides: Optional[Row] = None,
    site_order_overrides: Optional[Row] = None,
    **release_kwargs: Any,
) -> Row:
    """A RELEASED configuration plus a programme and one site order on it."""
    state = released or setup_released_configuration(**release_kwargs)
    account_id = state["chain_account"]["id"]
    program = create_construction_program(account_id, **(program_overrides or {}))
    site_order = create_site_order(
        program["id"],
        state["config"]["id"],
        account_id,
        **(site_order_overrides or {}),
    )
    state["program"] = program
    state["site_order"] = site_order
    return state


def setup_scheduled_site_order(
    line_overrides: Optional[Row] = None,
    slot_overrides: Optional[Row] = None,
    **kwargs: Any,
) -> Row:
    """A site order with one RESERVED production slot behind it."""
    state = setup_program_with_site_order(**kwargs)
    line = create_build_line(**(line_overrides or {}))
    slot = reserve_production_slot(
        line["id"], state["site_order"]["id"], **(slot_overrides or {})
    )
    state["build_line"] = line
    state["slot"] = slot
    return state


# ==========================================================================
# Tier 5 -- terminal production states
# ==========================================================================


def setup_completed_slot(
    build_clock: str = "2026-09-08T00:00:00Z", **kwargs: Any
) -> Row:
    """A slot advanced through CONFIRM, START and COMPLETE."""
    state = setup_scheduled_site_order(**kwargs)
    advance_slot(state["slot"]["id"], "CONFIRM")
    set_clock(build_clock)
    advance_slot(state["slot"]["id"], "START")
    state["slot"] = advance_slot(state["slot"]["id"], "COMPLETE")
    return state


# ==========================================================================
# Tier 3 -- service partners and technician certifications
# ==========================================================================


def enrol_technician(
    service_partner_id: str,
    equipment_model_id: str,
    technician_code: str = "T1",
    training_hours: float = 40,
    **overrides: Any,
) -> Row:
    response = api_client.create_technician_certification(
        technician_certification_payload(
            service_partner_id,
            equipment_model_id,
            technician_code,
            training_hours,
            **overrides,
        ),
        make_service_partner_headers(service_partner_id),
    )
    return get_success_data(response, 201)


def grade_technician(certification_id: str, exam_score: float) -> Row:
    response = api_client.grade_technician_certification(
        certification_id,
        technician_grade_payload(exam_score),
        TEST_USERS["channel_manager"],
    )
    return get_success_data(response)


def partner_authorization(partner_id: str, action: str) -> Row:
    response = api_client.partner_authorization(
        partner_id, partner_authorization_payload(action), TEST_USERS["channel_manager"]
    )
    return get_success_data(response)


def setup_certified_technicians(
    service_partner_id: str,
    equipment_model_id: str,
    technicians: Sequence[Tuple[str, float, float]] = (("T1", 40, 88), ("T2", 36, 91)),
) -> List[Row]:
    """Enrol and pass the given technicians on one model."""
    rows: List[Row] = []
    for technician_code, training_hours, exam_score in technicians:
        certification = enrol_technician(
            service_partner_id,
            equipment_model_id,
            technician_code,
            training_hours,
        )
        rows.append(grade_technician(certification["id"], exam_score))
    return rows


def setup_authorized_partner(
    equipment_model_id: str,
    partner_overrides: Optional[Row] = None,
    technicians: Sequence[Tuple[str, float, float]] = (("T1", 40, 88), ("T2", 36, 91)),
    authorize: bool = True,
) -> Row:
    """A service partner with two PASSED certifications, AUTHORIZED by default.

    Returns ``{"partner": ..., "certifications": [...]}``.
    """
    partner = create_service_partner(**(partner_overrides or {}))
    certifications = setup_certified_technicians(
        partner["id"], equipment_model_id, technicians
    )
    partner_authorization(partner["id"], "PROVISION")
    if authorize:
        partner = partner_authorization(partner["id"], "AUTHORIZE")
    else:
        partner = get_success_data(
            api_client.get_service_partner(
                partner["id"], TEST_USERS["channel_manager"]
            )
        )
    return {"partner": partner, "certifications": certifications}


# ==========================================================================
# Tier 3 / 4 -- connected units, coverage and warranty claims
# ==========================================================================


def coverage_action(unit_id: str, action: str) -> Row:
    response = api_client.coverage_action(
        unit_id, coverage_action_payload(action), TEST_USERS["warranty_adjudicator"]
    )
    return get_success_data(response)


def setup_covered_unit(
    equipment_model_id: str,
    serial_number: str = "SN-1",
    service_tier: str = "BASE",
    **overrides: Any,
) -> Row:
    """A connected unit whose warranty coverage has been activated."""
    unit = create_connected_unit(
        equipment_model_id,
        serial_number,
        service_tier=service_tier,
        **overrides,
    )
    return coverage_action(unit["id"], "ACTIVATE")


def file_warranty_claim(
    connected_unit_id: str,
    service_partner_id: str,
    technician_certification_id: str,
    claim_code: str = "CLM-1",
    parts_cost_cents: int = 123000,
    labor_hours: float = 3.0,
    **overrides: Any,
) -> Row:
    response = api_client.create_warranty_claim(
        warranty_claim_payload(
            connected_unit_id,
            service_partner_id,
            technician_certification_id,
            claim_code,
            parts_cost_cents,
            labor_hours,
            **overrides,
        ),
        make_service_partner_headers(service_partner_id),
    )
    return get_success_data(response, 201)


def adjudicate_claim(claim_id: str, decision: str, **overrides: Any) -> Row:
    response = api_client.adjudicate_warranty_claim(
        claim_id,
        adjudication_payload(decision, **overrides),
        TEST_USERS["warranty_adjudicator"],
    )
    return get_success_data(response)


def setup_warranty_environment(
    model_overrides: Optional[Row] = None,
    serial_number: str = "SN-1",
    service_tier: str = "BASE",
    unit_overrides: Optional[Row] = None,
    partner_overrides: Optional[Row] = None,
    technicians: Sequence[Tuple[str, float, float]] = (("T1", 40, 88), ("T2", 36, 91)),
    authorize: bool = True,
    activate_coverage: bool = True,
    set_initial_clock: bool = True,
) -> Row:
    """A LISTED model, a covered unit and an authorised partner with technicians.

    Returns ``{"model", "listing", "unit", "partner", "certifications"}``.
    """
    if set_initial_clock:
        set_clock()
    listed = setup_listed_model(**(model_overrides or {}))
    model_id = listed["model"]["id"]
    if activate_coverage:
        unit = setup_covered_unit(
            model_id, serial_number, service_tier, **(unit_overrides or {})
        )
    else:
        unit = create_connected_unit(
            model_id, serial_number, service_tier=service_tier, **(unit_overrides or {})
        )
    partner_state = setup_authorized_partner(
        model_id, partner_overrides, technicians, authorize
    )
    return {
        "model": listed["model"],
        "listing": listed["listing"],
        "unit": unit,
        "partner": partner_state["partner"],
        "certifications": partner_state["certifications"],
    }


def setup_reserve_utilisation(
    parts_cost_cents: int = 123000,
    labor_hours: float = 3.0,
    claim_code: str = "CLM-1",
    **environment_kwargs: Any,
) -> Row:
    """A warranty environment with one APPROVED claim already drawn down.

    Used to place the unit's reserve utilisation into a chosen coinsurance
    band before the claim under test is adjudicated.
    """
    state = setup_warranty_environment(**environment_kwargs)
    claim = file_warranty_claim(
        state["unit"]["id"],
        state["partner"]["id"],
        state["certifications"][0]["id"],
        claim_code,
        parts_cost_cents,
        labor_hours,
    )
    state["first_claim"] = adjudicate_claim(claim["id"], "APPROVE")
    state["unit"] = get_success_data(
        api_client.get_connected_unit(
            state["unit"]["id"], TEST_USERS["connected_ops_engineer"]
        )
    )
    return state


# ==========================================================================
# Tier 4 -- connected fleets and firmware campaigns
# ==========================================================================


def setup_active_fleet(
    equipment_model_id: str,
    units: Sequence[Tuple[str, str]] = (
        ("SN-1", "BASE"),
        ("SN-2", "BASE"),
        ("SN-3", "EXTENDED_PLUS"),
    ),
) -> List[Row]:
    """A fleet of units with coverage activated, ready to form a cohort."""
    rows: List[Row] = []
    for serial_number, service_tier in units:
        rows.append(setup_covered_unit(equipment_model_id, serial_number, service_tier))
    return rows


def schedule_campaign(campaign_id: str) -> Row:
    response = api_client.schedule_firmware_campaign(
        campaign_id, {}, TEST_USERS["connected_ops_engineer"]
    )
    return get_success_data(response)


def start_campaign(campaign_id: str) -> Row:
    response = api_client.start_firmware_campaign(
        campaign_id, {}, TEST_USERS["connected_ops_engineer"]
    )
    return get_success_data(response)


def report_unit_result(campaign_id: str, connected_unit_id: str, outcome: str) -> Row:
    response = api_client.report_unit_result(
        campaign_id,
        unit_result_payload(connected_unit_id, outcome),
        TEST_USERS["connected_ops_engineer"],
    )
    return get_success_data(response)


def close_campaign(campaign_id: str, disposition: str) -> Row:
    response = api_client.close_firmware_campaign(
        campaign_id,
        campaign_close_payload(disposition),
        TEST_USERS["connected_ops_engineer"],
    )
    return get_success_data(response)


def post_telemetry(
    unit_id: str, fault_count_30d: int, missed_heartbeat_count: int
) -> Row:
    from .factories import telemetry_payload

    response = api_client.post_telemetry(
        unit_id,
        telemetry_payload(fault_count_30d, missed_heartbeat_count),
        TEST_USERS["connected_ops_engineer"],
    )
    return get_success_data(response)


def setup_running_campaign(
    equipment_model_id: str,
    fleet: Optional[Iterable[Row]] = None,
    campaign_overrides: Optional[Row] = None,
    open_clock: str = "2026-10-01T00:00:00Z",
) -> Row:
    """A campaign scheduled with a frozen cohort and started in its window."""
    units = list(fleet) if fleet is not None else setup_active_fleet(equipment_model_id)
    campaign = create_firmware_campaign(
        equipment_model_id, **(campaign_overrides or {})
    )
    campaign = schedule_campaign(campaign["id"])
    set_clock(open_clock)
    campaign = start_campaign(campaign["id"])
    return {"units": units, "campaign": campaign}


def setup_completed_campaign(
    equipment_model_id: str,
    fleet: Optional[Iterable[Row]] = None,
    campaign_overrides: Optional[Row] = None,
    open_clock: str = "2026-10-01T00:00:00Z",
) -> Row:
    """A campaign closed as COMPLETE with every cohort unit reporting SUCCESS."""
    state = setup_running_campaign(
        equipment_model_id, fleet, campaign_overrides, open_clock
    )
    for unit_id in state["campaign"]["cohort_unit_ids"]:
        report_unit_result(state["campaign"]["id"], unit_id, "SUCCESS")
    state["campaign"] = close_campaign(state["campaign"]["id"], "COMPLETE")
    return state


# ==========================================================================
# Convenience re-reads
# ==========================================================================


def read_equipment_model(model_id: str) -> Row:
    return get_success_data(
        api_client.get_equipment_model(model_id, TEST_USERS["compliance_engineer"])
    )


def read_certification_listing(listing_id: str) -> Row:
    return get_success_data(
        api_client.get_certification_listing(
            listing_id, TEST_USERS["compliance_engineer"]
        )
    )


def read_chain_account(account_id: str) -> Row:
    return get_success_data(
        api_client.get_chain_account(account_id, TEST_USERS["channel_manager"])
    )


def read_chain_configuration(config_id: str) -> Row:
    return get_success_data(
        api_client.get_chain_configuration(config_id, TEST_USERS["application_engineer"])
    )


def read_performance_validation(validation_id: str) -> Row:
    return get_success_data(
        api_client.get_performance_validation(
            validation_id, TEST_USERS["application_engineer"]
        )
    )


def read_construction_program(program_id: str, chain_account_id: str) -> Row:
    return get_success_data(
        api_client.get_construction_program(
            program_id, make_chain_admin_headers(chain_account_id)
        )
    )


def read_site_order(site_order_id: str) -> Row:
    return get_success_data(
        api_client.get_site_order(site_order_id, TEST_USERS["production_planner"])
    )


def read_build_line(line_id: str) -> Row:
    return get_success_data(
        api_client.get_build_line(line_id, TEST_USERS["production_planner"])
    )


def read_production_slot(slot_id: str) -> Row:
    return get_success_data(
        api_client.get_production_slot(slot_id, TEST_USERS["production_planner"])
    )


def read_connected_unit(unit_id: str) -> Row:
    return get_success_data(
        api_client.get_connected_unit(unit_id, TEST_USERS["connected_ops_engineer"])
    )


def read_firmware_campaign(campaign_id: str) -> Row:
    return get_success_data(
        api_client.get_firmware_campaign(campaign_id, TEST_USERS["connected_ops_engineer"])
    )


def read_service_partner(partner_id: str) -> Row:
    return get_success_data(
        api_client.get_service_partner(partner_id, TEST_USERS["channel_manager"])
    )


def read_technician_certification(certification_id: str) -> Row:
    return get_success_data(
        api_client.get_technician_certification(
            certification_id, TEST_USERS["channel_manager"]
        )
    )


def read_warranty_claim(claim_id: str) -> Row:
    return get_success_data(
        api_client.get_warranty_claim(claim_id, TEST_USERS["warranty_adjudicator"])
    )
