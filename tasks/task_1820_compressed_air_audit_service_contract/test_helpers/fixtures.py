"""Composite setup helpers.

Encapsulates the multi-step setup sequences the PRD's workflows require so
tests can focus on assertions. All helpers build preconditions from scratch
via PRD-declared endpoints (each test runs against a fresh server) and use
the lenient setup validator so failures surface as clear "Setup step failed"
errors.

Identity threading: FacilityManager calls are ownership-gated (PRD §2.1), so
every such call uses make_facility_manager_headers(facility["id"]).
"""
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_compressor_payload,
    create_demand_profile_payload,
    create_facility_payload,
    create_guarantee_certificate_payload,
    create_leak_survey_payload,
    create_leak_tag_payload,
    create_rental_asset_payload,
    create_rental_reservation_payload,
    create_retrofit_project_payload,
    create_savings_case_payload,
    create_service_contract_payload,
    create_service_ticket_payload,
)
from .test_users import (
    make_contract_manager_headers,
    make_dealer_admin_headers,
    make_energy_engineer_headers,
    make_facility_manager_headers,
    make_service_tech_headers,
)

ADMIN = make_dealer_admin_headers()
ENGINEER = make_energy_engineer_headers("eng-1")
TECH = make_service_tech_headers("tech-1")
CONTRACT_MGR = make_contract_manager_headers()


# ---------------------------------------------------------------------------
# Time helpers (logical clock values; second-granularity ISO 8601 UTC, PRD §2.8)
# ---------------------------------------------------------------------------

def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def plus_seconds(value: str, seconds: int) -> str:
    return iso(parse_iso(value) + timedelta(seconds=seconds))


def plus_days(value: str, days: int) -> str:
    return iso(parse_iso(value) + timedelta(days=days))


def set_clock(to_iso8601: str) -> dict:
    """Advance the server logical clock (DealerAdmin-only, PRD §2.5)."""
    return get_success_data(
        api_client.set_current_utc({"to_iso8601": to_iso8601}, ADMIN)
    )


# ---------------------------------------------------------------------------
# Tier 1: basic entity creation and state progression
# ---------------------------------------------------------------------------

def create_facility(
    name: str = "Test Facility",
    utility_rate_cents_per_kwh: int = 12,
    operating_hours_per_year: int = 6000,
    repair_budget_cents: int = 5_000_000,
    activate: bool = True,
) -> dict:
    """Create a Facility; optionally activate it (ONBOARDING -> ACTIVE)."""
    facility = get_success_data(
        api_client.create_facility(
            create_facility_payload(
                name=name,
                utility_rate_cents_per_kwh=utility_rate_cents_per_kwh,
                operating_hours_per_year=operating_hours_per_year,
                repair_budget_cents=repair_budget_cents,
            ),
            ADMIN,
        )
    )
    if activate:
        facility = get_success_data(api_client.activate_facility(facility["id"], ADMIN))
    return facility


def get_facility(facility_id: str) -> dict:
    return get_success_data(api_client.get_facility(facility_id, ADMIN))


def get_facility_version(facility_id: str) -> int:
    return get_facility(facility_id)["version"]


def create_compressor(
    facility_id: str,
    asset_tag: str = "C1",
    rated_kw: int = 75,
    rated_cfm: int = 400,
    run_hours_total: Optional[int] = None,
) -> dict:
    payload = create_compressor_payload(
        facility_id=facility_id,
        asset_tag=asset_tag,
        rated_kw=rated_kw,
        rated_cfm=rated_cfm,
    )
    if run_hours_total is not None:
        payload["run_hours_total"] = run_hours_total
    return get_success_data(api_client.create_compressor(payload, TECH))


def log_run_hours(compressor_id: str, run_hours_total: int) -> dict:
    return get_success_data(
        api_client.log_run_hours(compressor_id, {"run_hours_total": run_hours_total}, TECH)
    )


def create_demand_profile(
    facility_id: str,
    window_start_date: str = "2026-03-01",
    window_end_date: str = "2026-03-31",
    measured_kwh: int = 248000,
    measured_avg_cfm: float = 350.0,
    measured_peak_cfm: float = 520.0,
) -> dict:
    return get_success_data(
        api_client.create_demand_profile(
            create_demand_profile_payload(
                facility_id=facility_id,
                window_start_date=window_start_date,
                window_end_date=window_end_date,
                measured_kwh=measured_kwh,
                measured_avg_cfm=measured_avg_cfm,
                measured_peak_cfm=measured_peak_cfm,
            ),
            ENGINEER,
        )
    )


def lock_demand_profile(facility_id: str, profile_id: str, user_id: str = "eng-1") -> dict:
    """Lock a COLLECTING profile; refreshes the OCC expected facility version
    right before the write (PRD §2.7)."""
    version = get_facility_version(facility_id)
    return get_success_data(
        api_client.lock_demand_profile(
            profile_id,
            {"expected_facility_version": version},
            make_energy_engineer_headers(user_id),
        )
    )


def create_and_activate_contract(
    facility_id: str,
    tier: str = "STANDARD",
    start_date: str = "2026-08-01",
    term_months: int = 12,
    monthly_fee_cents: int = 400000,
) -> dict:
    """Create a ServiceContract and activate it (DRAFT -> ACTIVE, OCC-guarded)."""
    contract = get_success_data(
        api_client.create_service_contract(
            create_service_contract_payload(
                facility_id=facility_id,
                tier=tier,
                start_date=start_date,
                term_months=term_months,
                monthly_fee_cents=monthly_fee_cents,
            ),
            CONTRACT_MGR,
        )
    )
    version = get_facility_version(facility_id)
    return get_success_data(
        api_client.activate_service_contract(
            contract["id"], {"expected_facility_version": version}, CONTRACT_MGR
        )
    )


# ---------------------------------------------------------------------------
# Tier 2: leak survey hierarchy and repair pipeline
# ---------------------------------------------------------------------------

def create_leak_survey(facility_id: str, survey_date: str = "2026-03-15") -> dict:
    """Create a DRAFT leak survey (PRD §3.4)."""
    return get_success_data(
        api_client.create_leak_survey(
            create_leak_survey_payload(facility_id=facility_id, survey_date=survey_date),
            ENGINEER,
        )
    )


def create_leak_tag(
    survey_id: str,
    location_description: str = "leak",
    cfm_loss: float = 5.0,
    repair_quote_cents: int = 100000,
) -> dict:
    """Add a TAGGED leak tag to a DRAFT survey (PRD §3.4)."""
    return get_success_data(
        api_client.create_leak_tag(
            survey_id,
            create_leak_tag_payload(
                location_description=location_description,
                cfm_loss=cfm_loss,
                repair_quote_cents=repair_quote_cents,
            ),
            ENGINEER,
        )
    )


def create_verified_survey(
    facility_id: str,
    tags: Optional[List[dict]] = None,
    survey_date: str = "2026-03-15",
    submitter: str = "eng-1",
    verifier: str = "eng-2",
) -> tuple:
    """Create a survey with tags, submit it, and verify it (two different
    engineers, per the segregation-of-duties rule in PRD §3.4).
    Returns (survey, [tag, ...])."""
    if tags is None:
        tags = [{"location_description": "leak", "cfm_loss": 5.0, "repair_quote_cents": 100000}]
    survey = get_success_data(
        api_client.create_leak_survey(
            create_leak_survey_payload(facility_id=facility_id, survey_date=survey_date),
            ENGINEER,
        )
    )
    created_tags = [
        get_success_data(api_client.create_leak_tag(survey["id"], create_leak_tag_payload(**t), ENGINEER))
        for t in tags
    ]
    survey = get_success_data(
        api_client.submit_leak_survey(survey["id"], make_energy_engineer_headers(submitter))
    )
    survey = get_success_data(
        api_client.verify_leak_survey(survey["id"], make_energy_engineer_headers(verifier))
    )
    created_tags = [
        get_success_data(api_client.get_leak_tag(t["id"], ENGINEER)) for t in created_tags
    ]
    return survey, created_tags


def authorize_and_close_tag(
    tag_id: str,
    facility_id: str,
    tech_user_id: str = "tech-1",
    closer: str = "eng-1",
) -> dict:
    """Walk a QUOTED tag through REPAIR_AUTHORIZED -> REPAIRED -> VERIFIED_CLOSED
    (PRD §3.4). Returns the closed tag."""
    tag = get_success_data(
        api_client.authorize_repair(tag_id, make_facility_manager_headers(facility_id))
    )
    tag = get_success_data(
        api_client.mark_repaired(tag["id"], make_service_tech_headers(tech_user_id))
    )
    return get_success_data(
        api_client.verify_closure(tag["id"], make_energy_engineer_headers(closer))
    )


# ---------------------------------------------------------------------------
# Tier 3: retrofit lifecycle and savings-case pipeline
# ---------------------------------------------------------------------------

def create_retrofit_project(
    facility_id: str,
    compressor_ids: List[str],
    baseline_pressure_psi: int = 125,
    target_pressure_psi: int = 100,
    project_cost_cents: int = 50_000_000,
) -> dict:
    return get_success_data(
        api_client.create_retrofit_project(
            create_retrofit_project_payload(
                facility_id=facility_id,
                baseline_pressure_psi=baseline_pressure_psi,
                target_pressure_psi=target_pressure_psi,
                sequence_compressor_ids=compressor_ids,
                project_cost_cents=project_cost_cents,
            ),
            ENGINEER,
        )
    )


def approve_retrofit_project(project_id: str, facility_id: str) -> dict:
    return get_success_data(
        api_client.approve_retrofit_project(
            project_id, make_facility_manager_headers(facility_id)
        )
    )


def walk_retrofit_to_accepted(
    project_id: str,
    facility_id: str,
    accept_date: str = "2026-05-15",
) -> dict:
    """APPROVED -> INSTALLED -> COMMISSIONED -> ACCEPTED, stamping accepted_date
    from the logical clock (PRD §3.5)."""
    project = get_success_data(api_client.mark_retrofit_installed(project_id, TECH))
    project = get_success_data(api_client.commission_retrofit_project(project["id"], TECH))
    set_clock(f"{accept_date}T00:00:00Z")
    return get_success_data(
        api_client.accept_retrofit_project(
            project["id"], make_facility_manager_headers(facility_id)
        )
    )


def create_savings_case(
    facility_id: str,
    baseline_profile_id: str,
    retrofit_project_id: str,
) -> dict:
    return get_success_data(
        api_client.create_savings_case(
            create_savings_case_payload(
                facility_id=facility_id,
                baseline_profile_id=baseline_profile_id,
                retrofit_project_id=retrofit_project_id,
            ),
            ENGINEER,
        )
    )


def model_savings_case(case_id: str) -> dict:
    return get_success_data(api_client.model_savings_case(case_id, ENGINEER))


# ---------------------------------------------------------------------------
# Tier 4: the canonical savings pipeline (baseline -> leaks -> retrofit -> case)
# ---------------------------------------------------------------------------

def setup_savings_pipeline(
    *,
    name: str = "F-SP",
    utility_rate_cents_per_kwh: int = 12,
    operating_hours_per_year: int = 6000,
    repair_budget_cents: int = 5_000_000,
    num_compressors: int = 1,
    baseline_window: tuple = ("2026-03-01", "2026-03-31"),
    baseline_kwh: int = 248000,
    leaks: Optional[List[dict]] = None,
    close_leak_indices: Optional[List[int]] = None,
    baseline_pressure_psi: int = 125,
    target_pressure_psi: int = 100,
    project_cost_cents: int = 50_000_000,
    approve_project: bool = True,
    accept_project: Optional[bool] = None,
    accept_date: str = "2026-05-15",
    post_window: tuple = ("2026-06-01", "2026-06-30"),
    post_kwh: int = 200000,
    advance_to: str = "MODELED",
    baseline_locker: str = "eng-1",
    measurement_closer: str = "eng-2",
    post_locker: Optional[str] = None,
) -> dict:
    """Build the full savings-case pipeline up to a chosen stage.

    Stages (advance_to):
      DRAFT            — case created (baseline LOCKED, project APPROVED-or-later)
      MODELED          — case modeled; deemed_annual_savings_kwh computed
      MEASUREMENT_OPEN — measurement opened (project walked to ACCEPTED)
      MEASURED         — post profile locked, measurement closed; measured computed

    leaks: list of {"location_description", "cfm_loss", "repair_quote_cents"} added
    to a verified survey; close_leak_indices selects which tags are walked to
    VERIFIED_CLOSED (default: all).
    """
    facility = create_facility(
        name=name,
        utility_rate_cents_per_kwh=utility_rate_cents_per_kwh,
        operating_hours_per_year=operating_hours_per_year,
        repair_budget_cents=repair_budget_cents,
    )
    compressors = [
        create_compressor(facility["id"], asset_tag=f"C{i + 1}")
        for i in range(num_compressors)
    ]
    baseline = create_demand_profile(
        facility["id"],
        window_start_date=baseline_window[0],
        window_end_date=baseline_window[1],
        measured_kwh=baseline_kwh,
    )
    baseline = lock_demand_profile(facility["id"], baseline["id"], user_id=baseline_locker)

    survey = None
    tags: List[dict] = []
    if leaks:
        survey, tags = create_verified_survey(facility["id"], tags=leaks)
        indices = (
            close_leak_indices
            if close_leak_indices is not None
            else list(range(len(tags)))
        )
        for i in indices:
            tags[i] = authorize_and_close_tag(tags[i]["id"], facility["id"])

    project = create_retrofit_project(
        facility["id"],
        [c["id"] for c in compressors],
        baseline_pressure_psi=baseline_pressure_psi,
        target_pressure_psi=target_pressure_psi,
        project_cost_cents=project_cost_cents,
    )
    if approve_project:
        project = approve_retrofit_project(project["id"], facility["id"])
    if accept_project is None:
        accept_project = advance_to in ("MEASUREMENT_OPEN", "MEASURED")
    if accept_project:
        project = walk_retrofit_to_accepted(
            project["id"], facility["id"], accept_date=accept_date
        )

    case = create_savings_case(facility["id"], baseline["id"], project["id"])
    if advance_to in ("MODELED", "MEASUREMENT_OPEN", "MEASURED"):
        case = model_savings_case(case["id"])
    if advance_to in ("MEASUREMENT_OPEN", "MEASURED"):
        case = get_success_data(api_client.open_measurement(case["id"], ENGINEER))

    post_profile = None
    if advance_to == "MEASURED":
        post_profile = create_demand_profile(
            facility["id"],
            window_start_date=post_window[0],
            window_end_date=post_window[1],
            measured_kwh=post_kwh,
            measured_avg_cfm=300.0,
            measured_peak_cfm=480.0,
        )
        post_profile = lock_demand_profile(
            facility["id"],
            post_profile["id"],
            user_id=post_locker or baseline_locker,
        )
        case = get_success_data(
            api_client.close_measurement(
                case["id"],
                {"post_profile_id": post_profile["id"]},
                make_energy_engineer_headers(measurement_closer),
            )
        )

    return {
        "facility": facility,
        "compressors": compressors,
        "baseline_profile": baseline,
        "survey": survey,
        "tags": tags,
        "project": project,
        "case": case,
        "post_profile": post_profile,
    }


# ---------------------------------------------------------------------------
# Tier 4: ticket / SLA-breach accumulation
# ---------------------------------------------------------------------------

def setup_ticket_scenario(
    name: str = "F-TK",
    tier: str = "STANDARD",
    monthly_fee_cents: int = 400000,
) -> dict:
    """Facility ACTIVE + compressor + ACTIVE contract of the given tier."""
    facility = create_facility(name=name)
    compressor = create_compressor(facility["id"])
    contract = create_and_activate_contract(
        facility["id"], tier=tier, monthly_fee_cents=monthly_fee_cents
    )
    return {"facility": facility, "compressor": compressor, "contract": contract}


def open_ticket(facility_id: str, compressor_id: str, severity: str, reported_at: str) -> dict:
    """Set the logical clock, then open a ticket as the FacilityManager."""
    set_clock(reported_at)
    return get_success_data(
        api_client.create_service_ticket(
            create_service_ticket_payload(
                facility_id=facility_id,
                compressor_id=compressor_id,
                severity=severity,
            ),
            make_facility_manager_headers(facility_id),
        )
    )


def respond_to_ticket(ticket_id: str, respond_at: str) -> dict:
    """Dispatch a ticket, set the clock, and record the first response."""
    get_success_data(api_client.dispatch_ticket(ticket_id, TECH))
    set_clock(respond_at)
    return get_success_data(api_client.record_response(ticket_id, TECH))


def breach_ticket(ticket: dict, late_seconds: int = 1) -> dict:
    """Record a response `late_seconds` after the ticket's SLA deadline,
    producing an SLA breach (PRD §3.7). Returns the ON_SITE ticket."""
    respond_at = plus_seconds(ticket["sla_deadline"], late_seconds)
    return respond_to_ticket(ticket["id"], respond_at)


def list_contract_credits(contract_id: str, status: Optional[str] = None) -> list:
    params = {"contract_id": contract_id}
    if status:
        params["status"] = status
    data = get_success_data(api_client.list_service_credits(CONTRACT_MGR, params=params))
    return data


def setup_contract_with_breaches(
    count: int,
    name: str = "F-BR",
    tier: str = "STANDARD",
    monthly_fee_cents: int = 400000,
    severity: str = "URGENT",
    clock_base: str = "2026-08-10T09:00:00Z",
) -> dict:
    """Facility with an ACTIVE contract that has accrued `count` SLA breaches.
    Each breach is one ticket answered one second past its deadline; the
    logical clock only moves forward. Returns scenario dict including tickets
    and credits."""
    scenario = setup_ticket_scenario(
        name=name, tier=tier, monthly_fee_cents=monthly_fee_cents
    )
    tickets = []
    now = parse_iso(clock_base)
    for _ in range(count):
        ticket = open_ticket(
            scenario["facility"]["id"],
            scenario["compressor"]["id"],
            severity,
            iso(now),
        )
        ticket = breach_ticket(ticket)
        tickets.append(ticket)
        # Keep the logical clock strictly increasing for the next ticket.
        now = parse_iso(ticket["first_response_at"]) + timedelta(seconds=1)
    credits = list_contract_credits(scenario["contract"]["id"])
    scenario.update({"tickets": tickets, "credits": credits})
    return scenario


# ---------------------------------------------------------------------------
# Tier 4: rental fleet scenarios
# ---------------------------------------------------------------------------

def create_rental_asset(
    fleet_tag: str = "A1",
    rated_cfm: int = 500,
    daily_rate_cents: int = 35000,
    deposit_cents: int = 100000,
) -> dict:
    return get_success_data(
        api_client.create_rental_asset(
            create_rental_asset_payload(
                fleet_tag=fleet_tag,
                rated_cfm=rated_cfm,
                daily_rate_cents=daily_rate_cents,
                deposit_cents=deposit_cents,
            ),
            ADMIN,
        )
    )


def setup_rental_scenario(
    name: str = "F-RN",
    tier: str = "STANDARD",
    monthly_fee_cents: int = 400000,
    compressor_cfm: int = 400,
    assets: Optional[List[dict]] = None,
    mark_down: bool = True,
) -> dict:
    """Facility ACTIVE + ACTIVE contract + one compressor (optionally DOWN)
    + rental fleet assets (default: a single 500 CFM unit)."""
    if assets is None:
        assets = [{"fleet_tag": "A1", "rated_cfm": 500, "daily_rate_cents": 35000, "deposit_cents": 100000}]
    facility = create_facility(name=name)
    compressor = create_compressor(facility["id"], rated_cfm=compressor_cfm)
    contract = create_and_activate_contract(
        facility["id"], tier=tier, monthly_fee_cents=monthly_fee_cents
    )
    if mark_down:
        compressor = get_success_data(api_client.mark_down(compressor["id"], TECH))
    created_assets = [create_rental_asset(**a) for a in assets]
    return {
        "facility": facility,
        "compressor": compressor,
        "contract": contract,
        "assets": created_assets,
    }


def create_reservation(
    facility_id: str,
    down_compressor_id: str,
    start_date: str,
    end_date: str,
    rental_asset_id: Optional[str] = None,
) -> dict:
    payload = create_rental_reservation_payload(
        facility_id=facility_id,
        down_compressor_id=down_compressor_id,
        start_date=start_date,
        end_date=end_date,
    )
    if rental_asset_id is not None:
        payload["rental_asset_id"] = rental_asset_id
    return get_success_data(
        api_client.create_rental_reservation(
            payload, make_facility_manager_headers(facility_id)
        )
    )


def deliver_and_return(reservation_id: str, actual_return_date: str) -> dict:
    """RESERVED -> ON_RENT -> RETURNED (PRD §3.8). Returns the returned reservation."""
    get_success_data(api_client.deliver_reservation(reservation_id, TECH))
    return get_success_data(
        api_client.return_reservation(
            reservation_id, {"actual_return_date": actual_return_date}, TECH
        )
    )


# ---------------------------------------------------------------------------
# Tier 5: guarantee certificate pipeline
# ---------------------------------------------------------------------------

def create_certificate(
    facility_id: str,
    contract_id: str,
    savings_case_id: str,
    guaranteed_pct: float = 0.90,
) -> dict:
    return get_success_data(
        api_client.create_guarantee_certificate(
            create_guarantee_certificate_payload(
                facility_id=facility_id,
                contract_id=contract_id,
                savings_case_id=savings_case_id,
                guaranteed_pct=guaranteed_pct,
            ),
            CONTRACT_MGR,
        )
    )


def setup_certificate_pipeline(
    *,
    name: str = "F-CP",
    case_stage: str = "MEASURED",
    monthly_fee_cents: int = 900000,
    guaranteed_pct: float = 0.90,
    post_kwh: int = 200000,
    operating_hours_per_year: int = 6000,
    utility_rate_cents_per_kwh: int = 12,
    project_cost_cents: int = 50_000_000,
    leaks: Optional[List[dict]] = None,
) -> dict:
    """Full pipeline: savings case at `case_stage` + ACTIVE PREMIUM contract +
    GuaranteeCertificate. Returns the savings-pipeline dict plus contract and
    certificate."""
    pipeline = setup_savings_pipeline(
        name=name,
        utility_rate_cents_per_kwh=utility_rate_cents_per_kwh,
        operating_hours_per_year=operating_hours_per_year,
        post_kwh=post_kwh,
        project_cost_cents=project_cost_cents,
        leaks=leaks,
        advance_to=case_stage,
        # Certificate flows may open measurement later; the project must be
        # ACCEPTED even when the case itself is only MODELED (PRD §3.6).
        accept_project=True,
    )
    contract = create_and_activate_contract(
        pipeline["facility"]["id"], tier="PREMIUM", monthly_fee_cents=monthly_fee_cents
    )
    certificate = create_certificate(
        pipeline["facility"]["id"], contract["id"], pipeline["case"]["id"], guaranteed_pct
    )
    pipeline.update({"contract": contract, "certificate": certificate})
    return pipeline
