"""Composite setup helpers.

Every test runs against a freshly restarted server (empty database), so each
fixture builds its preconditions from scratch using only PRD-declared
endpoints. Setup calls go through ``get_success_data`` so a setup failure
surfaces as a clear "Setup step failed" error rather than a confusing
assertion failure deep in a test.

Covered fixture tiers:
  Tier 1  state progression: approved plans, departed voyages, rectified
          deficiencies, evaluated/closed inspections.
  Tier 2  entity hierarchy: vessel -> plan -> voyage -> events/inspections.
  Tier 3  full-lifecycle shortcuts: voyage driven to a terminal compliance
          status, enforcement case driven ACTIVE -> UNDER_REVIEW.
  Tier 4  threshold targeting: sampling/exceedance and sulfur boundary
          setups, overdue/escalation clock choreography.
  Tier 5  terminal states: sealed books, closed enforcement cases.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import CLOCK_DEFAULT, TEST_DEFAULTS
from .factories import (
    create_vessel_payload,
    create_plan_payload,
    create_voyage_payload,
    create_ballast_event_payload,
    uptake_event_payload,
    discharge_event_payload,
    exchange_complete_event_payload,
    treatment_complete_event_payload,
    create_inspection_payload,
    create_emissions_payload,
    create_drill_payload,
    create_record_book_payload,
    create_record_book_entry_payload,
)
from .test_users import (
    TEST_USERS,
    make_flag_surveyor_headers,
    make_psc_officer_headers,
    make_vessel_master_headers,
    make_shore_officer_headers,
)

SHORE = TEST_USERS["shore_officer_headers"]
MASTER = TEST_USERS["vessel_master_headers"]
SURVEYOR = TEST_USERS["flag_surveyor_headers"]
PSC = TEST_USERS["psc_officer_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str = CLOCK_DEFAULT):
    """Advance the server logical clock (PlatformAdmin-only test-driving endpoint)."""
    resp = api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN)
    get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 1/2: vessel + plan hierarchy
# ---------------------------------------------------------------------------

def create_vessel(imo_number="9000001", vessel_name="MV Test Vessel",
                  bwms_type="TREATMENT_USCG_TYPE_APPROVED", **overrides) -> dict:
    """Register a vessel. bwms_type != NONE automatically carries an installation date."""
    if bwms_type == "NONE":
        payload = create_vessel_payload(
            imo_number=imo_number, vessel_name=vessel_name, bwms_type=bwms_type,
            bwms_installation_date=None, **overrides,
        )
    else:
        payload = create_vessel_payload(
            imo_number=imo_number, vessel_name=vessel_name, bwms_type=bwms_type, **overrides
        )
    return get_success_data(api_client.create_vessel(payload, SHORE))


def get_vessel(vessel_id) -> dict:
    return get_success_data(api_client.get_vessel(vessel_id, SHORE))


def get_vessel_version(vessel_id) -> int:
    return get_vessel(vessel_id)["version"]


def create_plan(vessel_id, plan_revision=1, expected_vessel_version=None, **overrides) -> dict:
    """Create a plan revision in DRAFT. When expected_vessel_version is not
    supplied, the live vessel version is fetched (happy-path OCC)."""
    if expected_vessel_version is None:
        expected_vessel_version = get_vessel_version(vessel_id)
    payload = create_plan_payload(expected_vessel_version, plan_revision=plan_revision, **overrides)
    return get_success_data(api_client.create_plan(vessel_id, payload, SHORE))


def submit_plan(vessel_id, plan_id) -> dict:
    return get_success_data(api_client.submit_plan(vessel_id, plan_id, SHORE))


def approve_plan(vessel_id, plan_id) -> dict:
    return get_success_data(api_client.approve_plan(vessel_id, plan_id, SURVEYOR))


def setup_vessel_with_approved_plan(imo_number="9000001", vessel_name="MV Test Vessel",
                                    bwms_type="TREATMENT_USCG_TYPE_APPROVED",
                                    exchange_distance_nm=200, clock=CLOCK_DEFAULT,
                                    **vessel_overrides):
    """Vessel + plan revision 1 walked DRAFT -> SUBMITTED -> APPROVED.

    Returns (vessel, plan)."""
    set_clock(clock)
    vessel = create_vessel(imo_number=imo_number, vessel_name=vessel_name,
                           bwms_type=bwms_type, **vessel_overrides)
    plan = create_plan(vessel["id"], plan_revision=1, exchange_distance_nm=exchange_distance_nm)
    submit_plan(vessel["id"], plan["id"])
    plan = approve_plan(vessel["id"], plan["id"])
    return vessel, plan


# ---------------------------------------------------------------------------
# Tier 2: voyages
# ---------------------------------------------------------------------------

def create_voyage(vessel_id, voyage_number="V1001", arrived_at=None,
                  crosses_captain_of_port_zones=True, enters_us_eez=True,
                  departure_port="USNYC", arrival_port="USLAX", as_shore=False,
                  **overrides) -> dict:
    """Create a voyage in PENDING x NOT_DUE."""
    payload = create_voyage_payload(
        voyage_number=voyage_number,
        departure_port=departure_port,
        arrival_port=arrival_port,
        departed_at=overrides.pop("departed_at", TEST_DEFAULTS["DEPARTED_AT"]),
        arrived_at=arrived_at,
        crosses_captain_of_port_zones=crosses_captain_of_port_zones,
        enters_us_eez=enters_us_eez,
        **overrides,
    )
    headers = SHORE if as_shore else MASTER
    return get_success_data(api_client.create_voyage(vessel_id, payload, headers))


def get_voyage(vessel_id, voyage_id) -> dict:
    return get_success_data(api_client.get_voyage(vessel_id, voyage_id, MASTER))


def get_voyage_version(vessel_id, voyage_id) -> int:
    return get_voyage(vessel_id, voyage_id)["version"]


def depart_voyage(vessel_id, voyage_id) -> dict:
    return get_success_data(api_client.depart_voyage(vessel_id, voyage_id, MASTER))


def arrive_voyage(vessel_id, voyage_id, arrived_at=TEST_DEFAULTS["ARRIVED_AT"]) -> dict:
    return get_success_data(
        api_client.arrive_voyage(vessel_id, voyage_id, {"arrived_at": arrived_at}, MASTER)
    )


def setup_voyage_in_progress(imo_number="9000001", vessel_name="MV Test Vessel",
                             voyage_number="V1001", arrived_at=None,
                             crosses_captain_of_port_zones=True, enters_us_eez=True,
                             bwms_type="TREATMENT_USCG_TYPE_APPROVED",
                             departure_port="USNYC", arrival_port="USLAX",
                             clock=CLOCK_DEFAULT):
    """Vessel with APPROVED plan + one departed (IN_PROGRESS x DUE) voyage.

    Returns (vessel, plan, voyage)."""
    vessel, plan = setup_vessel_with_approved_plan(
        imo_number=imo_number, vessel_name=vessel_name, bwms_type=bwms_type, clock=clock
    )
    voyage = create_voyage(
        vessel["id"], voyage_number=voyage_number, arrived_at=arrived_at,
        crosses_captain_of_port_zones=crosses_captain_of_port_zones,
        enters_us_eez=enters_us_eez, departure_port=departure_port,
        arrival_port=arrival_port,
    )
    voyage = depart_voyage(vessel["id"], voyage["id"])
    return vessel, plan, voyage


# ---------------------------------------------------------------------------
# Tier 2/4: ballast events (OCC-guarded; version auto-fetched when omitted)
# ---------------------------------------------------------------------------

def post_ballast_event(vessel_id, voyage_id, expected_voyage_version=None, **event_fields):
    """Raw-response variant for error-path tests. When expected_voyage_version
    is None the live voyage version is fetched first."""
    if expected_voyage_version is None:
        expected_voyage_version = get_voyage_version(vessel_id, voyage_id)
    payload = create_ballast_event_payload(expected_voyage_version, **event_fields)
    return api_client.create_ballast_event(vessel_id, voyage_id, payload, MASTER)


def post_ballast_event_ok(vessel_id, voyage_id, expected_voyage_version=None, **event_fields) -> dict:
    return get_success_data(
        post_ballast_event(vessel_id, voyage_id, expected_voyage_version, **event_fields)
    )


def post_uptake(vessel_id, voyage_id, tank_id="T1", volume_m3=500,
                occurred_at="2026-07-28T06:00:00Z", salinity_ppt=32.0,
                source_port_locode="USNYC") -> dict:
    version = get_voyage_version(vessel_id, voyage_id)
    payload = uptake_event_payload(
        version, occurred_at=occurred_at, tank_id=tank_id, volume_m3=volume_m3,
        salinity_ppt=salinity_ppt, source_port_locode=source_port_locode,
    )
    return get_success_data(api_client.create_ballast_event(vessel_id, voyage_id, payload, MASTER))


def post_treatment_complete(vessel_id, voyage_id, tank_id="T1", volume_m3=500,
                            occurred_at="2026-07-29T06:00:00Z") -> dict:
    version = get_voyage_version(vessel_id, voyage_id)
    payload = treatment_complete_event_payload(
        version, occurred_at=occurred_at, tank_id=tank_id, volume_m3=volume_m3
    )
    return get_success_data(api_client.create_ballast_event(vessel_id, voyage_id, payload, MASTER))


def post_exchange_complete(vessel_id, voyage_id, tank_id="T1", volume_m3=400,
                           occurred_at="2026-07-29T06:00:00Z", latitude=30.0,
                           longitude=-150.0, distance_from_shore_nm=200.0) -> dict:
    version = get_voyage_version(vessel_id, voyage_id)
    payload = exchange_complete_event_payload(
        version, occurred_at=occurred_at, tank_id=tank_id, volume_m3=volume_m3,
        latitude=latitude, longitude=longitude, distance_from_shore_nm=distance_from_shore_nm,
    )
    return get_success_data(api_client.create_ballast_event(vessel_id, voyage_id, payload, MASTER))


def post_discharge(vessel_id, voyage_id, tank_id="T1", volume_m3=500,
                   occurred_at="2026-07-30T06:00:00Z", latitude=35.0,
                   longitude=-140.0, distance_from_shore_nm=250) -> dict:
    version = get_voyage_version(vessel_id, voyage_id)
    payload = discharge_event_payload(
        version, occurred_at=occurred_at, tank_id=tank_id, volume_m3=volume_m3,
        latitude=latitude, longitude=longitude, distance_from_shore_nm=distance_from_shore_nm,
    )
    return get_success_data(api_client.create_ballast_event(vessel_id, voyage_id, payload, MASTER))


def post_treatment_compliant_event_set(vessel_id, voyage_id, tank_id="T1", volume_m3=500):
    """UPTAKE -> TREATMENT_COMPLETE -> DISCHARGE (250 nm offshore) on one tank.
    Every subsequent determination over this stream is TREATMENT_COMPLIANT."""
    post_uptake(vessel_id, voyage_id, tank_id=tank_id, volume_m3=volume_m3)
    post_treatment_complete(vessel_id, voyage_id, tank_id=tank_id, volume_m3=volume_m3)
    post_discharge(vessel_id, voyage_id, tank_id=tank_id, volume_m3=volume_m3)


def list_ballast_events(vessel_id, voyage_id) -> list:
    return get_success_data(api_client.list_ballast_events(vessel_id, voyage_id, MASTER))


# ---------------------------------------------------------------------------
# Determinations
# ---------------------------------------------------------------------------

def list_determinations(vessel_id, voyage_id) -> list:
    """Determinations, newest first per the PRD endpoint table."""
    return get_success_data(api_client.list_determinations(vessel_id, voyage_id, SURVEYOR))


def current_determination(vessel_id, voyage_id) -> dict:
    return list_determinations(vessel_id, voyage_id)[0]


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------

def list_reports(vessel_id, voyage_id) -> list:
    return get_success_data(api_client.list_reports(vessel_id, voyage_id, MASTER))


def find_report(vessel_id, voyage_id, report_type) -> dict:
    """Find a report by its stored report_type field (no query-filter reliance)."""
    matches = [r for r in list_reports(vessel_id, voyage_id) if r.get("report_type") == report_type]
    assert matches, f"No {report_type} report found for voyage {voyage_id}"
    return matches[0]


def submit_report_ok(vessel_id, voyage_id, report_id, payload_summary=None) -> dict:
    payload = {"payload_summary": payload_summary or {"note": "pre-arrival"}}
    return get_success_data(api_client.submit_report(vessel_id, voyage_id, report_id, payload, MASTER))


# ---------------------------------------------------------------------------
# Sampling / inspections
# ---------------------------------------------------------------------------

def record_inspection(vessel_id, voyage_id, inspection_kind="PORT_STATE_CONTROL",
                      organism=12.0, tss=10.0, sampled_at="2026-07-29T00:00:00Z",
                      findings=None, recorder_user_id="psc-1") -> dict:
    """Record a sampling inspection. PSC inspections are recorded by a
    PSCOfficer; all other kinds by a FlagSurveyor. The recorder's X-User-ID is
    pinned so a *different* user can evaluate without tripping segregation of
    duties."""
    sampled_by_role = "PSC_OFFICER" if inspection_kind == "PORT_STATE_CONTROL" else "FLAG_SURVEYOR"
    if inspection_kind == "COMPANY_INTERNAL":
        sampled_by_role = "COMPANY_AUDITOR"
    payload = create_inspection_payload(
        inspection_kind=inspection_kind, sampled_at=sampled_at,
        sampled_by_role=sampled_by_role,
        indicator_organism_concentration=organism, tss_mg_per_l=tss,
        findings=list(findings or []),
    )
    if inspection_kind == "PORT_STATE_CONTROL":
        headers = make_psc_officer_headers(recorder_user_id)
    else:
        headers = make_flag_surveyor_headers(recorder_user_id)
    return get_success_data(api_client.create_inspection(vessel_id, voyage_id, payload, headers))


def evaluate_inspection_ok(vessel_id, voyage_id, inspection_id, evaluator_user_id="fs-1") -> dict:
    return get_success_data(
        api_client.evaluate_inspection(
            vessel_id, voyage_id, inspection_id, make_flag_surveyor_headers(evaluator_user_id)
        )
    )


def close_inspection_ok(vessel_id, voyage_id, inspection_id) -> dict:
    return get_success_data(api_client.close_inspection(vessel_id, voyage_id, inspection_id, SURVEYOR))


def list_inspections(vessel_id, voyage_id) -> list:
    return get_success_data(api_client.list_inspections(vessel_id, voyage_id, SURVEYOR))


# ---------------------------------------------------------------------------
# Noncompliance records
# ---------------------------------------------------------------------------

def list_noncompliance(vessel_id, voyage_id) -> list:
    return get_success_data(api_client.list_noncompliance(vessel_id, voyage_id, SURVEYOR))


def find_noncompliance(vessel_id, voyage_id, source_type=None, severity=None) -> dict:
    """Find a noncompliance record by its stored fields (no query-filter reliance)."""
    records = list_noncompliance(vessel_id, voyage_id)
    for record in records:
        if source_type is not None and record.get("source_type") != source_type:
            continue
        if severity is not None and record.get("severity") != severity:
            continue
        return record
    raise AssertionError(
        f"No noncompliance record matching source_type={source_type} severity={severity}; "
        f"saw {[(r.get('source_type'), r.get('severity')) for r in records]}"
    )


def respond_noncompliance_ok(vessel_id, voyage_id, record_id) -> dict:
    return get_success_data(api_client.respond_noncompliance(vessel_id, voyage_id, record_id, SHORE))


def close_noncompliance_ok(vessel_id, voyage_id, record_id) -> dict:
    return get_success_data(api_client.close_noncompliance(vessel_id, voyage_id, record_id, SURVEYOR))


# ---------------------------------------------------------------------------
# Deficiencies
# ---------------------------------------------------------------------------

def list_deficiencies(vessel_id) -> list:
    return get_success_data(api_client.list_deficiencies(vessel_id, MASTER))


def setup_psc_exceeded_deficiency(vessel_id, voyage_id, organism=12.0, tss=10.0,
                                  findings=("BWMS-01",), recorder_user_id="psc-1",
                                  evaluator_user_id="fs-1"):
    """PSC inspection exceeding statutory limits, evaluated: spawns an OPEN
    priority-one (A15) deficiency and a MAJOR sampling-exceedance record, and
    leaves the vessel RESTRICTED. Returns (inspection, deficiency, record)."""
    inspection = record_inspection(
        vessel_id, voyage_id, inspection_kind="PORT_STATE_CONTROL", organism=organism,
        tss=tss, findings=findings, recorder_user_id=recorder_user_id,
    )
    inspection = evaluate_inspection_ok(
        vessel_id, voyage_id, inspection["id"], evaluator_user_id=evaluator_user_id
    )
    deficiencies = list_deficiencies(vessel_id)
    assert deficiencies, "Expected an auto-created PSC deficiency"
    deficiency = deficiencies[0]
    record = find_noncompliance(vessel_id, voyage_id, source_type="SAMPLING_EXCEEDANCE")
    return inspection, deficiency, record


def get_deficiency(vessel_id, deficiency_id) -> dict:
    for row in list_deficiencies(vessel_id):
        if row["id"] == deficiency_id:
            return row
    raise AssertionError(f"Deficiency {deficiency_id} not found")


def begin_rectification_ok(vessel_id, deficiency_id) -> dict:
    return get_success_data(api_client.begin_rectification(vessel_id, deficiency_id, MASTER))


def claim_rectified_ok(vessel_id, deficiency_id, claimer_user_id="master-1") -> dict:
    """Claim rectification with a fresh OCC version, as the given master user."""
    version = get_deficiency(vessel_id, deficiency_id)["version"]
    return get_success_data(
        api_client.claim_rectified(
            vessel_id, deficiency_id, {"expected_deficiency_version": version},
            make_vessel_master_headers(claimer_user_id),
        )
    )


def rectify_deficiency_to_rectified(vessel_id, deficiency_id, claimer_user_id="master-1") -> dict:
    """OPEN -> RECTIFYING -> RECTIFIED with OCC discipline. Returns the RECTIFIED row."""
    begin_rectification_ok(vessel_id, deficiency_id)
    return claim_rectified_ok(vessel_id, deficiency_id, claimer_user_id=claimer_user_id)


# ---------------------------------------------------------------------------
# Record books
# ---------------------------------------------------------------------------

def create_record_book(vessel_id, book_kind="GARBAGE", voyage_id=None) -> dict:
    payload = create_record_book_payload(book_kind=book_kind, voyage_id=voyage_id)
    return get_success_data(api_client.create_record_book(vessel_id, payload, MASTER))


def list_record_books(vessel_id) -> list:
    return get_success_data(api_client.list_record_books(vessel_id, MASTER))


def find_ballast_book(vessel_id, voyage_id) -> dict:
    """The voyage-scoped BALLAST_WATER book auto-created on departure."""
    for book in list_record_books(vessel_id):
        if book.get("book_kind") == "BALLAST_WATER" and book.get("voyage_id") == voyage_id:
            return book
    raise AssertionError(f"No BALLAST_WATER book found for voyage {voyage_id}")


def post_book_entry_ok(vessel_id, book_id, **entry_fields) -> dict:
    payload = create_record_book_entry_payload(**entry_fields)
    return get_success_data(api_client.create_record_book_entry(vessel_id, book_id, payload, MASTER))


def seal_book_ok(vessel_id, book_id) -> dict:
    return get_success_data(api_client.seal_record_book(vessel_id, book_id, MASTER))


# ---------------------------------------------------------------------------
# Emissions
# ---------------------------------------------------------------------------

def create_emissions_record(vessel_id, voyage_id, **overrides) -> dict:
    payload = create_emissions_payload(**overrides)
    return get_success_data(api_client.create_emissions_record(vessel_id, voyage_id, payload, MASTER))


def evaluate_emissions_ok(vessel_id, voyage_id, record_id) -> dict:
    return get_success_data(api_client.evaluate_emissions(vessel_id, voyage_id, record_id, SHORE))


# ---------------------------------------------------------------------------
# Drills
# ---------------------------------------------------------------------------

def create_drill(vessel_id, drill_kind="MARPOL_AWARENESS",
                 scheduled_for="2026-08-20T00:00:00Z", attendees=None) -> dict:
    payload = create_drill_payload(
        drill_kind=drill_kind, scheduled_for=scheduled_for,
        attendees=list(attendees) if attendees is not None else ["CREW:Able", "CREW:Baker"],
    )
    return get_success_data(api_client.create_drill(vessel_id, payload, MASTER))


def get_drill(vessel_id, drill_id) -> dict:
    for row in get_success_data(api_client.list_drills(vessel_id, MASTER)):
        if row["id"] == drill_id:
            return row
    raise AssertionError(f"Drill {drill_id} not found")


# ---------------------------------------------------------------------------
# Enforcement cases
# ---------------------------------------------------------------------------

def list_enforcement_cases(vessel_id) -> list:
    return get_success_data(api_client.list_enforcement_cases(vessel_id, SHORE))


def get_single_case(vessel_id) -> dict:
    cases = list_enforcement_cases(vessel_id)
    assert cases, "Expected at least one enforcement case"
    return cases[0]
