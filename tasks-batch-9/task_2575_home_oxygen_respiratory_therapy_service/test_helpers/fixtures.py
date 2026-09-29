"""Composite setup helpers.

Every test starts against an empty database, so all state is built from scratch
through the endpoints the PRD declares.  These helpers encapsulate the multi-step
preambles — branch and fleet onboarding, admission, a qualifying study, a
certificate driven through to ACTIVE, a rental contract, equipment assignment,
a route driven through to DISPATCHED and an in-home setup — so tests can focus
on the behaviour under examination.

Setup calls use the lenient ``get_success_data`` so a broken preamble reports a
clear setup failure rather than a confusing assertion failure.
"""

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    complete_setup_payload,
    create_branch_payload,
    create_cmn_payload,
    create_delivery_route_payload,
    create_equipment_assignment_payload,
    create_equipment_unit_payload,
    create_patient_payload,
    create_qualifying_test_payload,
    create_rental_contract_payload,
    create_route_stop_payload,
    create_transfer_request_payload,
    create_travel_authorization_payload,
    post_billing_month_payload,
    set_clock_payload,
)
from .test_users import (
    BILLING_SPECIALIST,
    BRANCH_MANAGER,
    COMPLIANCE_AUDITOR,
    DELIVERY_DRIVER,
    INTAKE_COORDINATOR,
    PHYSICIAN,
    RESPIRATORY_THERAPIST,
)

# ─── Primitive creators ───────────────────────────────


def make_branch(**overrides) -> dict:
    """Register one service branch.  Defaults to a competitive-bid, non-liquid
    branch with the declared default refill capacity and turnaround buffer."""
    payload = create_branch_payload(**overrides)
    return get_success_data(api_client.create_branch(payload, BRANCH_MANAGER))


def make_liquid_branch(**overrides) -> dict:
    """Register a liquid-oxygen-certified branch."""
    defaults = {
        "name": "Tampa Bay Liquid",
        "liquid_oxygen_certified": True,
        "refill_capacity_per_day": 4,
    }
    defaults.update(overrides)
    return make_branch(**defaults)


def make_equipment_unit(branch_id: str, **overrides) -> dict:
    """Add one physical unit to a branch's fleet."""
    payload = create_equipment_unit_payload(branch_id, **overrides)
    return get_success_data(api_client.create_equipment_unit(payload, BRANCH_MANAGER))


def make_stationary_unit(branch_id: str, **overrides) -> dict:
    """A 5.0 lpm stationary concentrator, the canonical primary-role unit."""
    defaults = {
        "serial_number": "SC-1001",
        "model_code": "CONC-5L",
        "equipment_class": "STATIONARY_CONCENTRATOR",
        "max_continuous_lpm": 5.0,
        "max_pulse_setting": 0,
        "pm_interval_days": 365,
        "next_pm_due_date": "2027-06-01",
    }
    defaults.update(overrides)
    return make_equipment_unit(branch_id, **defaults)


def make_portable_unit(branch_id: str, **overrides) -> dict:
    """A 3.0 lpm portable concentrator, the canonical portable-role unit."""
    defaults = {
        "serial_number": "PC-2001",
        "model_code": "POC-3L",
        "equipment_class": "PORTABLE_CONCENTRATOR",
        "max_continuous_lpm": 3.0,
        "max_pulse_setting": 5,
        "pm_interval_days": 365,
        "next_pm_due_date": "2027-06-01",
    }
    defaults.update(overrides)
    return make_equipment_unit(branch_id, **defaults)


def make_patient(branch_id: str, **overrides) -> dict:
    """Admit one patient to a branch's service population."""
    payload = create_patient_payload(branch_id, **overrides)
    return get_success_data(api_client.create_patient(payload, INTAKE_COORDINATOR))


def make_qualifying_test(patient_id: str, **overrides) -> dict:
    """Record one qualifying study.  Defaults to the canonical Group I
    resting-room-air study at 87 percent saturation."""
    payload = create_qualifying_test_payload(patient_id, **overrides)
    return get_success_data(api_client.create_qualifying_test(payload, INTAKE_COORDINATOR))


def make_cmn(patient: dict, qualifying_test_id: str, **overrides) -> dict:
    """Draft one certificate against a study, carrying the patient's observed
    version as the stale-read token."""
    payload = create_cmn_payload(
        patient["id"], qualifying_test_id, patient["version"], **overrides
    )
    return get_success_data(api_client.create_cmn(payload, INTAKE_COORDINATOR))


def make_rental_contract(patient_id: str, cmn_id: str, **overrides) -> dict:
    """Open one capped-rental contract against an ACTIVE certificate."""
    payload = create_rental_contract_payload(patient_id, cmn_id, **overrides)
    return get_success_data(
        api_client.create_rental_contract(payload, BILLING_SPECIALIST)
    )


def make_delivery_route(branch_id: str, **overrides) -> dict:
    """Create one driver route for one service date."""
    payload = create_delivery_route_payload(branch_id, **overrides)
    return get_success_data(api_client.create_delivery_route(payload, BRANCH_MANAGER))


def make_route_stop(route_id: str, contract_id: str, **overrides) -> dict:
    """Schedule one stop onto an editable route."""
    payload = create_route_stop_payload(route_id, contract_id, **overrides)
    return get_success_data(api_client.create_route_stop(payload, BRANCH_MANAGER))


def assign_equipment(contract_id: str, role: str = "PRIMARY_STATIONARY", **overrides) -> dict:
    """Run the equipment selection rule for one role on one contract."""
    payload = create_equipment_assignment_payload(role, **overrides)
    return get_success_data(
        api_client.create_equipment_assignment(contract_id, payload, RESPIRATORY_THERAPIST)
    )


def advance_clock(to_iso8601: str) -> dict:
    """Advance the logical clock, running the certificate expiry sweep."""
    return get_success_data(
        api_client.set_clock(set_clock_payload(to_iso8601), BRANCH_MANAGER)
    )


# ─── Read-back helpers ────────────────────────────────


def read_branch(branch_id: str) -> dict:
    return get_success_data(api_client.get_branch(branch_id, BRANCH_MANAGER))


def read_patient(patient_id: str) -> dict:
    return get_success_data(api_client.get_patient(patient_id, INTAKE_COORDINATOR))


def read_cmn(cmn_id: str) -> dict:
    return get_success_data(api_client.get_cmn(cmn_id, COMPLIANCE_AUDITOR))


def read_contract(contract_id: str) -> dict:
    return get_success_data(
        api_client.get_rental_contract(contract_id, BILLING_SPECIALIST)
    )


def read_equipment_unit(unit_id: str) -> dict:
    return get_success_data(api_client.get_equipment_unit(unit_id, BRANCH_MANAGER))


def read_placement(placement_id: str) -> dict:
    return get_success_data(api_client.get_placement(placement_id, BRANCH_MANAGER))


def read_route(route_id: str) -> dict:
    return get_success_data(api_client.get_delivery_route(route_id, BRANCH_MANAGER))


def read_route_stop(stop_id: str) -> dict:
    return get_success_data(api_client.get_route_stop(stop_id, BRANCH_MANAGER))


def read_recall_notice(recall_notice_id: str) -> dict:
    return get_success_data(
        api_client.get_recall_notice(recall_notice_id, COMPLIANCE_AUDITOR)
    )


def read_travel_authorization(travel_authorization_id: str) -> dict:
    return get_success_data(
        api_client.get_travel_authorization(travel_authorization_id, BRANCH_MANAGER)
    )


def placements_for_contract(contract_id: str, **filters) -> list:
    """The placement list is the only discovery channel for placements created
    by the equipment-assignment cascade."""
    params = {"contract_id": contract_id, "limit": 100}
    params.update(filters)
    body = api_client.list_placements(BRANCH_MANAGER, params=params)
    return get_success_data(body)


def sole_placement(contract_id: str, **filters) -> dict:
    rows = placements_for_contract(contract_id, **filters)
    assert len(rows) == 1, f"expected exactly one placement, found {len(rows)}"
    return rows[0]


def placement_for_role(contract_id: str, role: str) -> dict:
    rows = placements_for_contract(contract_id, role=role)
    assert rows, f"no placement found for role {role}"
    return rows[0]


# ─── Certificate lifecycle shortcuts ──────────────────


def submit_cmn(cmn_id: str) -> dict:
    """Submit a drafted certificate for physician signature."""
    return get_success_data(api_client.submit_cmn(cmn_id, INTAKE_COORDINATOR))


def sign_cmn(cmn_id: str) -> dict:
    """Physician signature on a submitted certificate."""
    return get_success_data(api_client.sign_cmn(cmn_id, PHYSICIAN))


def approve_cmn(cmn_id: str) -> dict:
    """Compliance approval.  The auditor's operator identifier differs from both
    the stored submitter and the stored signer, as segregation of duties
    requires."""
    return get_success_data(api_client.approve_cmn(cmn_id, COMPLIANCE_AUDITOR))


def drive_cmn_to_active(cmn_id: str) -> dict:
    """Submit, sign and approve one certificate, leaving it ACTIVE."""
    submit_cmn(cmn_id)
    sign_cmn(cmn_id)
    return approve_cmn(cmn_id)


# ─── Tier 2: entity hierarchy ─────────────────────────


def setup_branch_with_fleet(
    branch_overrides: dict = None,
    unit_specs: list = None,
) -> dict:
    """One branch plus its fleet.

    ``unit_specs`` is a list of override dicts, one per unit; it defaults to the
    canonical stationary concentrator plus a portable concentrator.  Returns
    ``{"branch": ..., "units": [...], "stationary_unit": ..., "portable_unit": ...}``.
    """
    branch = make_branch(**(branch_overrides or {}))
    if unit_specs is None:
        units = [
            make_stationary_unit(branch["id"]),
            make_portable_unit(branch["id"]),
        ]
    else:
        units = [make_equipment_unit(branch["id"], **spec) for spec in unit_specs]
    scenario = {"branch": branch, "units": units}
    for unit in units:
        if unit["equipment_class"] in ("STATIONARY_CONCENTRATOR", "LIQUID_RESERVOIR"):
            scenario.setdefault("stationary_unit", unit)
        else:
            scenario.setdefault("portable_unit", unit)
    return scenario


def setup_admitted_patient(
    branch_overrides: dict = None,
    unit_specs: list = None,
    patient_overrides: dict = None,
) -> dict:
    """Branch plus fleet plus one admitted patient."""
    scenario = setup_branch_with_fleet(branch_overrides, unit_specs)
    scenario["patient"] = make_patient(
        scenario["branch"]["id"], **(patient_overrides or {})
    )
    return scenario


def setup_qualifying_study(
    branch_overrides: dict = None,
    unit_specs: list = None,
    patient_overrides: dict = None,
    test_overrides: dict = None,
) -> dict:
    """Branch, fleet, patient and one qualifying study."""
    scenario = setup_admitted_patient(branch_overrides, unit_specs, patient_overrides)
    scenario["qualifying_test"] = make_qualifying_test(
        scenario["patient"]["id"], **(test_overrides or {})
    )
    return scenario


def setup_drafted_cmn(
    branch_overrides: dict = None,
    unit_specs: list = None,
    patient_overrides: dict = None,
    test_overrides: dict = None,
    cmn_overrides: dict = None,
) -> dict:
    """Everything above plus one certificate in DRAFT."""
    scenario = setup_qualifying_study(
        branch_overrides, unit_specs, patient_overrides, test_overrides
    )
    scenario["cmn"] = make_cmn(
        scenario["patient"], scenario["qualifying_test"]["id"], **(cmn_overrides or {})
    )
    scenario["patient"] = read_patient(scenario["patient"]["id"])
    return scenario


# ─── Tier 3: full lifecycle shortcuts ─────────────────


def setup_active_cmn(
    branch_overrides: dict = None,
    unit_specs: list = None,
    patient_overrides: dict = None,
    test_overrides: dict = None,
    cmn_overrides: dict = None,
) -> dict:
    """Everything above with the certificate driven through to ACTIVE."""
    scenario = setup_drafted_cmn(
        branch_overrides, unit_specs, patient_overrides, test_overrides, cmn_overrides
    )
    scenario["cmn"] = drive_cmn_to_active(scenario["cmn"]["id"])
    scenario["patient"] = read_patient(scenario["patient"]["id"])
    return scenario


def setup_open_contract(
    branch_overrides: dict = None,
    unit_specs: list = None,
    patient_overrides: dict = None,
    test_overrides: dict = None,
    cmn_overrides: dict = None,
    contract_overrides: dict = None,
) -> dict:
    """An ACTIVE certificate plus a freshly opened contract: ACCRUING on the
    billing dimension and PENDING_SETUP on the service dimension."""
    scenario = setup_active_cmn(
        branch_overrides, unit_specs, patient_overrides, test_overrides, cmn_overrides
    )
    scenario["contract"] = make_rental_contract(
        scenario["patient"]["id"], scenario["cmn"]["id"], **(contract_overrides or {})
    )
    return scenario


def setup_reserved_equipment(
    roles: list = None,
    branch_overrides: dict = None,
    unit_specs: list = None,
    patient_overrides: dict = None,
    test_overrides: dict = None,
    cmn_overrides: dict = None,
    contract_overrides: dict = None,
) -> dict:
    """An open contract with equipment reserved for each named role.

    ``roles`` defaults to ``["PRIMARY_STATIONARY"]``.  Adds
    ``placements`` (the created placement rows, in request order) and refreshes
    ``contract`` from the server.
    """
    scenario = setup_open_contract(
        branch_overrides,
        unit_specs,
        patient_overrides,
        test_overrides,
        cmn_overrides,
        contract_overrides,
    )
    scenario["placements"] = [
        assign_equipment(scenario["contract"]["id"], role)
        for role in (roles or ["PRIMARY_STATIONARY"])
    ]
    scenario["placement"] = scenario["placements"][0]
    scenario["contract"] = read_contract(scenario["contract"]["id"])
    return scenario


def setup_dispatched_setup_stop(
    roles: list = None,
    branch_overrides: dict = None,
    unit_specs: list = None,
    patient_overrides: dict = None,
    test_overrides: dict = None,
    cmn_overrides: dict = None,
    contract_overrides: dict = None,
    route_overrides: dict = None,
    stop_overrides: dict = None,
) -> dict:
    """Reserved equipment plus a SETUP_DELIVERY stop on a DISPATCHED route,
    ready for the in-home assessment.  Adds ``route`` and ``stop``."""
    scenario = setup_reserved_equipment(
        roles,
        branch_overrides,
        unit_specs,
        patient_overrides,
        test_overrides,
        cmn_overrides,
        contract_overrides,
    )
    route = make_delivery_route(scenario["branch"]["id"], **(route_overrides or {}))
    stop = make_route_stop(
        route["id"], scenario["contract"]["id"], **(stop_overrides or {})
    )
    get_success_data(api_client.lock_route(route["id"], BRANCH_MANAGER))
    get_success_data(api_client.dispatch_route(route["id"], BRANCH_MANAGER))
    scenario["route"] = read_route(route["id"])
    scenario["stop"] = read_route_stop(stop["id"])
    return scenario


def complete_in_home_setup(stop_id: str, **overrides) -> dict:
    """Close a SETUP_DELIVERY stop with the in-home education and safety
    assessment.  Defaults to a passing assessment."""
    payload = complete_setup_payload(**overrides)
    return get_success_data(api_client.complete_setup(stop_id, payload, RESPIRATORY_THERAPIST))


def setup_contract_in_service(
    roles: list = None,
    branch_overrides: dict = None,
    unit_specs: list = None,
    patient_overrides: dict = None,
    test_overrides: dict = None,
    cmn_overrides: dict = None,
    contract_overrides: dict = None,
    route_overrides: dict = None,
    stop_overrides: dict = None,
    setup_overrides: dict = None,
) -> dict:
    """The full happy path: a contract IN_SERVICE with its equipment PLACED,
    its units DEPLOYED and its monthly allowable computed.

    Adds ``setup_stop`` (the completed stop) and refreshes ``contract``,
    ``patient``, ``placements`` and ``route``.
    """
    scenario = setup_dispatched_setup_stop(
        roles,
        branch_overrides,
        unit_specs,
        patient_overrides,
        test_overrides,
        cmn_overrides,
        contract_overrides,
        route_overrides,
        stop_overrides,
    )
    scenario["setup_stop"] = complete_in_home_setup(
        scenario["stop"]["id"], **(setup_overrides or {})
    )
    scenario["stop"] = read_route_stop(scenario["stop"]["id"])
    scenario["contract"] = read_contract(scenario["contract"]["id"])
    scenario["patient"] = read_patient(scenario["patient"]["id"])
    scenario["route"] = read_route(scenario["route"]["id"])
    scenario["placements"] = placements_for_contract(scenario["contract"]["id"])
    scenario["placement"] = scenario["placements"][0]
    return scenario


def setup_failed_setup(
    branch_overrides: dict = None,
    unit_specs: list = None,
    patient_overrides: dict = None,
    test_overrides: dict = None,
    cmn_overrides: dict = None,
    contract_overrides: dict = None,
) -> dict:
    """A contract whose in-home assessment found smoking, firing the
    setup-failure cascade: service dimension SETUP_FAILED, billing dimension
    SUSPENDED with reason SETUP_FAILED, placements REMOVED and units in
    quarantine for SAFETY."""
    return setup_contract_in_service(
        branch_overrides=branch_overrides,
        unit_specs=unit_specs,
        patient_overrides=patient_overrides,
        test_overrides=test_overrides,
        cmn_overrides=cmn_overrides,
        contract_overrides=contract_overrides,
        setup_overrides={"smoking_in_home": True},
    )


def schedule_pickup_stop(scenario: dict, **stop_overrides) -> dict:
    """Schedule a PICKUP stop for an IN_SERVICE contract, which moves its
    service dimension to PICKUP_SCHEDULED.  Returns the created stop."""
    route = make_delivery_route(
        scenario["branch"]["id"],
        service_date="2026-08-02",
        shift_start_utc="2026-08-02T12:00:00Z",
        shift_end_utc="2026-08-02T22:00:00Z",
    )
    defaults = {
        "stop_type": "PICKUP",
        "window_start_utc": "2026-08-02T13:00:00Z",
        "window_end_utc": "2026-08-02T14:00:00Z",
        "service_minutes": 30,
        "cylinders_requested": 0,
    }
    defaults.update(stop_overrides)
    stop = make_route_stop(route["id"], scenario["contract"]["id"], **defaults)
    scenario["pickup_route"] = route
    scenario["pickup_stop"] = stop
    return stop


def setup_returned_contract(**kwargs) -> dict:
    """An IN_SERVICE contract taken all the way to RETURNED: a PICKUP stop is
    scheduled, its route dispatched and the stop completed by the driver."""
    scenario = setup_contract_in_service(**kwargs)
    stop = schedule_pickup_stop(scenario)
    route_id = scenario["pickup_route"]["id"]
    get_success_data(api_client.lock_route(route_id, BRANCH_MANAGER))
    get_success_data(api_client.dispatch_route(route_id, BRANCH_MANAGER))
    get_success_data(api_client.complete_route_stop(stop["id"], DELIVERY_DRIVER))
    scenario["pickup_stop"] = read_route_stop(stop["id"])
    scenario["pickup_route"] = read_route(route_id)
    scenario["contract"] = read_contract(scenario["contract"]["id"])
    scenario["placements"] = placements_for_contract(scenario["contract"]["id"])
    return scenario


# ─── Tier 4: billing accumulation and cap targeting ───


def post_month(contract_id: str, service_month: str = "2026-08") -> dict:
    """Post one rental month against the cap."""
    payload = post_billing_month_payload(service_month)
    return get_success_data(
        api_client.post_billing_month(contract_id, payload, BILLING_SPECIALIST)
    )


def reverse_month(contract_id: str, service_month: str) -> dict:
    """Reverse a previously posted rental month."""
    return get_success_data(
        api_client.reverse_billing_month(contract_id, service_month, BILLING_SPECIALIST)
    )


def setup_posted_month(
    service_month: str = "2026-08",
    **kwargs,
) -> dict:
    """An IN_SERVICE contract with one month already posted.  Adds
    ``posted_month`` and refreshes ``contract``."""
    scenario = setup_contract_in_service(**kwargs)
    scenario["posted_month"] = post_month(scenario["contract"]["id"], service_month)
    scenario["contract"] = read_contract(scenario["contract"]["id"])
    return scenario


def setup_cap_reached_contract(
    cap_month_limit: int = 1,
    service_month: str = "2026-08",
    **kwargs,
) -> dict:
    """An IN_SERVICE contract whose posted month drives the effective cap
    position to exactly ``cap_month_limit``, leaving the billing dimension in
    CAP_REACHED."""
    contract_overrides = dict(kwargs.pop("contract_overrides", None) or {})
    contract_overrides.setdefault("cap_month_limit", cap_month_limit)
    return setup_posted_month(
        service_month, contract_overrides=contract_overrides, **kwargs
    )


# ─── Tier 5: suspension, travel, recall, transfer ──────


def void_active_cmn(cmn_id: str, void_reason: str = "Prescription withdrawn.") -> dict:
    """Void an ACTIVE certificate, suspending every contract hanging off it."""
    return get_success_data(
        api_client.void_cmn(cmn_id, {"void_reason": void_reason}, COMPLIANCE_AUDITOR)
    )


def setup_suspended_by_void(**kwargs) -> dict:
    """An IN_SERVICE contract suspended because its certificate was voided."""
    scenario = setup_contract_in_service(**kwargs)
    scenario["cmn"] = void_active_cmn(scenario["cmn"]["id"])
    scenario["contract"] = read_contract(scenario["contract"]["id"])
    scenario["patient"] = read_patient(scenario["patient"]["id"])
    return scenario


def request_travel(contract: dict, **overrides) -> dict:
    """Request travel supply against a contract, carrying its observed version
    as the stale-read token."""
    payload = create_travel_authorization_payload(contract["version"], **overrides)
    return get_success_data(
        api_client.create_travel_authorization(contract["id"], payload, INTAKE_COORDINATOR)
    )


def setup_requested_travel(travel_overrides: dict = None, **kwargs) -> dict:
    """An IN_SERVICE contract with one travel authorization in REQUESTED.
    Adds ``travel_authorization``."""
    scenario = setup_contract_in_service(**kwargs)
    scenario["travel_authorization"] = request_travel(
        scenario["contract"], **(travel_overrides or {})
    )
    scenario["contract"] = read_contract(scenario["contract"]["id"])
    return scenario


def publish_recall(model_code: str, severity: str = "CLASS_I") -> dict:
    """Publish a manufacturer recall against a model code."""
    return get_success_data(
        api_client.create_recall_notice(
            {"model_code": model_code, "severity": severity}, COMPLIANCE_AUDITOR
        )
    )


def setup_recalled_contract(severity: str = "CLASS_I", **kwargs) -> dict:
    """An IN_SERVICE contract whose stationary unit's model code is recalled.
    A CLASS_I notice quarantines the fleet, takes the placement out of service
    and suspends the contract.  Adds ``recall_notice``."""
    scenario = setup_contract_in_service(**kwargs)
    model_code = scenario["stationary_unit"]["model_code"]
    scenario["recall_notice"] = publish_recall(model_code, severity)
    scenario["contract"] = read_contract(scenario["contract"]["id"])
    scenario["placements"] = placements_for_contract(scenario["contract"]["id"])
    scenario["stationary_unit"] = read_equipment_unit(scenario["stationary_unit"]["id"])
    return scenario


def file_malfunction(placement_id: str, symptom: str = "NO_FLOW", oxygen_gap_minutes: int = 0) -> dict:
    """File a malfunction report against a placed unit."""
    return get_success_data(
        api_client.report_malfunction(
            placement_id,
            {"symptom": symptom, "oxygen_gap_minutes": oxygen_gap_minutes},
            RESPIRATORY_THERAPIST,
        )
    )


def open_transfer(patient_id: str, receiving_branch_id: str, transfer_effective_date: str = "2026-08-15") -> dict:
    """Open a patient transfer to another branch."""
    payload = create_transfer_request_payload(receiving_branch_id, transfer_effective_date)
    return get_success_data(
        api_client.create_transfer_request(patient_id, payload, INTAKE_COORDINATOR)
    )


def setup_transfer_pending(transfer_effective_date: str = "2026-08-15", **kwargs) -> dict:
    """An IN_SERVICE contract whose patient has a pending transfer to a second
    branch, which suspends the contract with reason TRANSFER.  Adds
    ``receiving_branch``."""
    scenario = setup_contract_in_service(**kwargs)
    scenario["receiving_branch"] = make_branch(
        name="Orlando", state_code="FL", competitive_bid_area=False
    )
    scenario["patient"] = open_transfer(
        scenario["patient"]["id"],
        scenario["receiving_branch"]["id"],
        transfer_effective_date,
    )
    scenario["contract"] = read_contract(scenario["contract"]["id"])
    return scenario


# ─── Certificate correction cycle ─────────────────────


def return_cmn_for_correction(cmn_id: str, correction_notes: str = "Narrative incomplete.") -> dict:
    """Return a submitted or signed certificate to the intake queue."""
    return get_success_data(
        api_client.return_cmn_for_correction(
            cmn_id, {"correction_notes": correction_notes}, COMPLIANCE_AUDITOR
        )
    )


def setup_returned_for_correction_cmn(
    branch_overrides: dict = None,
    unit_specs: list = None,
    patient_overrides: dict = None,
    test_overrides: dict = None,
    cmn_overrides: dict = None,
) -> dict:
    """A certificate drafted, submitted and then returned for correction, so it
    sits in RETURNED_FOR_CORRECTION at revision round 1."""
    scenario = setup_drafted_cmn(
        branch_overrides, unit_specs, patient_overrides, test_overrides, cmn_overrides
    )
    submit_cmn(scenario["cmn"]["id"])
    scenario["cmn"] = return_cmn_for_correction(scenario["cmn"]["id"])
    scenario["patient"] = read_patient(scenario["patient"]["id"])
    return scenario


def apply_cmn_corrections(cmn_id: str, **fields) -> dict:
    """Apply corrections to a returned certificate, moving it back to DRAFT."""
    return get_success_data(api_client.update_cmn(cmn_id, fields, INTAKE_COORDINATOR))


# ─── Equipment selection pools ────────────────────────


def setup_open_contract_with_pool(
    unit_specs: list,
    prescribed_lpm: float = 3.0,
    patient_overrides: dict = None,
    branch_overrides: dict = None,
    contract_overrides: dict = None,
    cmn_overrides: dict = None,
    test_overrides: dict = None,
) -> dict:
    """An open contract whose branch fleet is exactly ``unit_specs``.

    Used by the equipment-selection tests, which need a controlled candidate
    pool and a known prescribed flow.  ``units`` holds the created rows in the
    order the specs were given, and ``units_by_serial`` indexes them.
    """
    merged_cmn = {"prescribed_lpm": prescribed_lpm}
    merged_cmn.update(cmn_overrides or {})
    scenario = setup_open_contract(
        branch_overrides=branch_overrides,
        unit_specs=unit_specs,
        patient_overrides=patient_overrides,
        test_overrides=test_overrides,
        cmn_overrides=merged_cmn,
        contract_overrides=contract_overrides,
    )
    scenario["units_by_serial"] = {u["serial_number"]: u for u in scenario["units"]}
    return scenario


def setup_liquid_in_service(
    prescribed_lpm: float = 3.0,
    refill_capacity_per_day: int = 4,
    **kwargs,
) -> dict:
    """A liquid-certified branch serving an IN_SERVICE contract with a liquid
    reservoir in the primary role and a liquid portable in the portable role —
    the only configuration a PORTABLE_REFILL stop is permitted against."""
    branch_overrides = {
        "name": "Tampa Bay Liquid",
        "liquid_oxygen_certified": True,
        "refill_capacity_per_day": refill_capacity_per_day,
    }
    branch_overrides.update(kwargs.pop("branch_overrides", None) or {})
    unit_specs = kwargs.pop(
        "unit_specs",
        [
            {
                "serial_number": "LIQ-RES-1",
                "model_code": "LIQ-RES",
                "equipment_class": "LIQUID_RESERVOIR",
                "max_continuous_lpm": 5.0,
                "max_pulse_setting": 0,
                "pm_interval_days": 365,
                "next_pm_due_date": "2027-06-01",
            },
            {
                "serial_number": "LIQ-POR-1",
                "model_code": "LIQ-POR",
                "equipment_class": "LIQUID_PORTABLE",
                "max_continuous_lpm": 4.0,
                "max_pulse_setting": 0,
                "pm_interval_days": 365,
                "next_pm_due_date": "2027-06-01",
            },
        ],
    )
    patient_overrides = {"mobility_profile": "LIMITED_AMBULATORY"}
    patient_overrides.update(kwargs.pop("patient_overrides", None) or {})
    cmn_overrides = {"prescribed_lpm": prescribed_lpm, "portable_prescribed": True}
    cmn_overrides.update(kwargs.pop("cmn_overrides", None) or {})
    return setup_contract_in_service(
        roles=["PRIMARY_STATIONARY", "PORTABLE"],
        branch_overrides=branch_overrides,
        unit_specs=unit_specs,
        patient_overrides=patient_overrides,
        cmn_overrides=cmn_overrides,
        **kwargs,
    )


# ─── Route helpers ────────────────────────────────────


def setup_in_service_with_planning_route(
    service_date: str = "2026-08-01",
    shift_start_utc: str = "2026-08-01T06:00:00Z",
    shift_end_utc: str = "2026-08-01T23:00:00Z",
    **kwargs,
) -> dict:
    """An IN_SERVICE contract plus a fresh route in PLANNING on the same branch,
    with a wide shift, ready for stop-window scheduling tests.  Adds
    ``planning_route``."""
    scenario = setup_contract_in_service(**kwargs)
    scenario["planning_route"] = make_delivery_route(
        scenario["branch"]["id"],
        service_date=service_date,
        shift_start_utc=shift_start_utc,
        shift_end_utc=shift_end_utc,
    )
    return scenario


def lock_route(route_id: str) -> dict:
    return get_success_data(api_client.lock_route(route_id, BRANCH_MANAGER))


def unlock_route(route_id: str) -> dict:
    return get_success_data(api_client.unlock_route(route_id, BRANCH_MANAGER))


def dispatch_route(route_id: str) -> dict:
    return get_success_data(api_client.dispatch_route(route_id, BRANCH_MANAGER))


def complete_stop(stop_id: str) -> dict:
    return get_success_data(api_client.complete_route_stop(stop_id, DELIVERY_DRIVER))


def miss_stop(stop_id: str) -> dict:
    return get_success_data(api_client.miss_route_stop(stop_id, DELIVERY_DRIVER))


def cancel_stop(stop_id: str) -> dict:
    return get_success_data(api_client.cancel_route_stop(stop_id, BRANCH_MANAGER))


def service_unit(unit_id: str) -> dict:
    return get_success_data(
        api_client.service_equipment_unit(unit_id, RESPIRATORY_THERAPIST)
    )


def retire_unit(unit_id: str) -> dict:
    return get_success_data(api_client.retire_equipment_unit(unit_id, BRANCH_MANAGER))


def release_placement(placement_id: str) -> dict:
    return get_success_data(
        api_client.release_placement(placement_id, RESPIRATORY_THERAPIST)
    )


def resume_billing(contract_id: str) -> dict:
    return get_success_data(api_client.resume_billing(contract_id, BILLING_SPECIALIST))


def close_contract(contract_id: str) -> dict:
    return get_success_data(
        api_client.close_rental_contract(contract_id, BILLING_SPECIALIST)
    )
