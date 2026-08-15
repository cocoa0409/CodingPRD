"""Composite setup helpers for multi-step test prerequisites.

Every fixture builds its preconditions from scratch using only PRD-declared
endpoints (each test runs against a freshly restarted server). Setup calls
use get_success_data() so failures surface as clear "Setup failed" errors.

Identity threading: after creating an entity-backed role record, all
ownership-gated calls in the same fixture use make_*_headers(entity["id"]).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS
from .factories import (
    create_airport_payload,
    create_species_payload,
    create_biologist_payload,
    create_atc_controller_payload,
    create_regulator_payload,
    create_strike_report_payload,
    create_habitat_assessment_payload,
    create_mitigation_action_payload,
    create_dispersal_activity_payload,
    create_take_permit_payload,
    create_advisory_payload,
    create_runway_closure_payload,
    create_annual_plan_payload,
    create_training_record_payload,
)
from .test_users import (
    TEST_USERS,
    make_biologist_headers,
    make_atc_controller_headers,
    make_regulator_headers,
)

DEFAULT_CLOCK = TEST_DEFAULTS["DEFAULT_CLOCK"]  # 2026-08-01T00:00:00Z


# ─── Tier 0: clock + reference data ───────────────────

def set_clock(to_iso8601: str = DEFAULT_CLOCK):
    """Drive the logical clock; setting it triggers all pending
    time-driven transitions (per PRD logical-clock section)."""
    return get_success_data(api_client.set_clock(to_iso8601, TEST_USERS["admin_headers"]))


def create_airport(icao_code: str = "KAAA", name: str = "Alpha Airport",
                   annual_plan_cycle_year: int = 2026) -> dict:
    return get_success_data(api_client.create_airport(
        create_airport_payload(
            icao_code=icao_code, name=name,
            annual_plan_cycle_year=annual_plan_cycle_year,
        ),
        TEST_USERS["admin_headers"],
    ))


def create_species(common_name: str = "Mourning Dove",
                   scientific_name: str = "Zenaida macroura",
                   risk_tier: str = "LOW", guild: str = "SONGBIRD",
                   body_mass_g=120, is_protected_federally: bool = False) -> dict:
    return get_success_data(api_client.create_species(
        create_species_payload(
            common_name=common_name, scientific_name=scientific_name,
            guild=guild, risk_tier=risk_tier, body_mass_g=body_mass_g,
            is_protected_federally=is_protected_federally,
        ),
        TEST_USERS["admin_headers"],
    ))


def create_biologist(airport_id: str, is_senior: bool = False,
                     full_name: str = "B One", certification_id: str = "CERT-001") -> dict:
    return get_success_data(api_client.create_biologist(
        create_biologist_payload(
            airport_id, full_name=full_name,
            certification_id=certification_id, is_senior=is_senior,
        ),
        TEST_USERS["admin_headers"],
    ))


def create_atc_controller(airport_id: str, full_name: str = "C One",
                          facility_id: str = "TWR-001") -> dict:
    return get_success_data(api_client.create_atc_controller(
        create_atc_controller_payload(
            airport_id, full_name=full_name, facility_id=facility_id,
        ),
        TEST_USERS["admin_headers"],
    ))


def create_regulator(agency: str = "USFWS", full_name: str = "R One",
                     badge_number: str = "USFWS-9001") -> dict:
    return get_success_data(api_client.create_regulator(
        create_regulator_payload(
            full_name=full_name, agency=agency, badge_number=badge_number,
        ),
        TEST_USERS["admin_headers"],
    ))


# ─── Tier 1: common one-call contexts ─────────────────

def setup_airport_with_biologists(icao_code: str = "KAAA",
                                  senior_name: str = "B One",
                                  junior_name: str = "B Two",
                                  cert_senior: str = "CERT-001",
                                  cert_junior: str = "CERT-002"):
    """Airport + senior biologist + non-senior biologist.

    Returns (airport, senior, junior, senior_headers, junior_headers).
    """
    airport = create_airport(icao_code=icao_code)
    senior = create_biologist(airport["id"], is_senior=True,
                              full_name=senior_name, certification_id=cert_senior)
    junior = create_biologist(airport["id"], is_senior=False,
                              full_name=junior_name, certification_id=cert_junior)
    return (
        airport,
        senior,
        junior,
        make_biologist_headers(senior["id"]),
        make_biologist_headers(junior["id"]),
    )


# ─── Tier 2: strike lifecycle ─────────────────────────

def create_draft_strike(airport_id: str, reporter: dict, species_id: str,
                        strike_at: str = "2026-07-15T10:00:00Z",
                        damage_class: str = "NONE",
                        carcass_present: bool = False,
                        aircraft_registration: str = "N100") -> dict:
    """Create a DRAFT strike report; reporter acts as themselves."""
    headers = make_biologist_headers(reporter["id"])
    return get_success_data(api_client.create_strike_report(
        create_strike_report_payload(
            airport_id, reporter["id"], species_id,
            strike_at=strike_at, damage_class=damage_class,
            carcass_present=carcass_present,
            aircraft_registration=aircraft_registration,
        ),
        headers,
    ))


def submit_strike(report_id: str, actor: dict) -> dict:
    return get_success_data(
        api_client.submit_strike_report(report_id, make_biologist_headers(actor["id"]))
    )


def begin_review_strike(report_id: str, reviewer: dict) -> dict:
    return get_success_data(
        api_client.begin_review_strike_report(report_id, make_biologist_headers(reviewer["id"]))
    )


def confirm_strike(report_id: str, confirmer: dict, notes: str = "ok") -> dict:
    return get_success_data(api_client.confirm_strike_report(
        report_id, {"confirmation_notes": notes}, make_biologist_headers(confirmer["id"]),
    ))


def create_confirmed_strike(airport_id: str, reporter: dict, confirmer: dict,
                            species_id: str, strike_at: str,
                            damage_class: str = "NONE",
                            carcass_present: bool = False,
                            aircraft_registration: str = "N100") -> dict:
    """Walk a strike report DRAFT -> SUBMITTED -> UNDER_REVIEW -> CONFIRMED.

    reporter != confirmer (segregation of duties). Returns the CONFIRMED report.
    """
    strike = create_draft_strike(
        airport_id, reporter, species_id,
        strike_at=strike_at, damage_class=damage_class,
        carcass_present=carcass_present,
        aircraft_registration=aircraft_registration,
    )
    submit_strike(strike["id"], reporter)
    begin_review_strike(strike["id"], confirmer)
    return confirm_strike(strike["id"], confirmer)


def create_under_review_strike(airport_id: str, reporter: dict, reviewer: dict,
                               species_id: str, strike_at: str = "2026-07-15T10:00:00Z",
                               damage_class: str = "NONE",
                               carcass_present: bool = False,
                               aircraft_registration: str = "N100") -> dict:
    """Create a strike and walk it to UNDER_REVIEW (reviewer != reporter)."""
    strike = create_draft_strike(
        airport_id, reporter, species_id,
        strike_at=strike_at, damage_class=damage_class,
        carcass_present=carcass_present,
        aircraft_registration=aircraft_registration,
    )
    submit_strike(strike["id"], reporter)
    begin_review_strike(strike["id"], reviewer)
    return get_success_data(
        api_client.get_strike_report(strike["id"], make_biologist_headers(reviewer["id"]))
    )


def confirm_n_strikes(airport_id: str, reporter: dict, confirmer: dict,
                      species_id: str, count: int,
                      start_date: str = "2026-07-01",
                      damage_class: str = "NONE",
                      registration_prefix: str = "N") -> list:
    """Confirm `count` strikes on consecutive days starting at start_date.

    Accumulation helper for trailing-window threshold tests.
    """
    strikes = []
    year, month, day = (int(p) for p in start_date.split("-"))
    for i in range(count):
        strike_at = f"{year:04d}-{month:02d}-{day + i:02d}T00:00:00Z"
        strikes.append(create_confirmed_strike(
            airport_id, reporter, confirmer, species_id,
            strike_at=strike_at, damage_class=damage_class,
            aircraft_registration=f"{registration_prefix}{100 + i}",
        ))
    return strikes


def get_airport(airport_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_airport(
        airport_id, headers or TEST_USERS["admin_headers"],
    ))


def force_airport_hazard(airport_id: str, reporter: dict, confirmer: dict,
                         species_id: str, target: str) -> dict:
    """Raise the airport to a hazard level via confirmed strikes.

    target "HIGH": one SUBSTANTIAL strike; target "CRITICAL": two.
    Returns the refreshed airport.
    """
    n_high_risk = {"HIGH": 1, "CRITICAL": 2}[target]
    confirm_n_strikes(
        airport_id, reporter, confirmer, species_id,
        count=n_high_risk, damage_class="SUBSTANTIAL",
        registration_prefix="N7",
    )
    return get_airport(airport_id, make_biologist_headers(confirmer["id"]))


# ─── Tier 3: carcass records ──────────────────────────

def setup_confirmed_strike_with_carcass(icao_code: str = "KFFF",
                                        risk_tier: str = "MEDIUM"):
    """Confirmed strike with carcass_present=true; auto-created CarcassRecord.

    Returns dict with airport, species, second species, senior/reporter
    biologists (+headers), strike, carcass record.
    """
    set_clock()
    airport = create_airport(icao_code=icao_code)
    sp1 = create_species(
        common_name="Red-tailed Hawk", scientific_name="Buteo jamaicensis",
        guild="RAPTOR", risk_tier=risk_tier, body_mass_g=1100,
        is_protected_federally=True,
    )
    sp2 = create_species(
        common_name="European Starling", scientific_name="Sturnus vulgaris",
        guild="SONGBIRD", risk_tier="LOW", body_mass_g=85,
        is_protected_federally=False,
    )
    b1 = create_biologist(airport["id"], is_senior=True,
                          full_name="B One", certification_id="CERT-501")
    b2 = create_biologist(airport["id"], is_senior=True,
                          full_name="B Two", certification_id="CERT-502")
    b3 = create_biologist(airport["id"], is_senior=False,
                          full_name="B Three", certification_id="CERT-503")
    strike = create_confirmed_strike(
        airport["id"], b3, b1, sp1["id"],
        strike_at="2026-07-01T10:00:00Z", damage_class="MINOR",
        carcass_present=True, aircraft_registration="N301",
    )
    carcasses = get_success_data(api_client.list_carcass_records_for_strike(
        strike["id"], make_biologist_headers(b1["id"]),
    ))
    return {
        "airport": airport, "sp1": sp1, "sp2": sp2,
        "b1": b1, "b2": b2, "b3": b3,
        "b1_headers": make_biologist_headers(b1["id"]),
        "b2_headers": make_biologist_headers(b2["id"]),
        "b3_headers": make_biologist_headers(b3["id"]),
        "strike": strike, "carcass": carcasses[0],
    }


# ─── Tier 4: permits & dispersals ─────────────────────

def setup_permit_scenario(icao_code: str = "KBBB",
                          authorized_take_total: int = 10,
                          valid_from: str = "2026-01-01",
                          valid_to: str = "2026-12-31",
                          clock: str = DEFAULT_CLOCK,
                          permit_number: str = "MB0001-00"):
    """Airport + species + senior/performer biologists + USFWS regulator
    + take permit driven to ACTIVE via a clock-set evaluation.

    Returns dict with all entities and per-entity headers.
    """
    set_clock(clock)
    airport = create_airport(icao_code=icao_code)
    species = create_species(
        common_name="Rock Pigeon", scientific_name="Columba livia",
        guild="SONGBIRD", risk_tier="LOW", body_mass_g=300,
        is_protected_federally=False,
    )
    senior = create_biologist(airport["id"], is_senior=True,
                              full_name="B One", certification_id="CERT-101")
    performer = create_biologist(airport["id"], is_senior=False,
                                 full_name="B Two", certification_id="CERT-102")
    regulator = create_regulator(agency="USFWS", badge_number="USFWS-9001")
    reg_headers = make_regulator_headers(regulator["id"])
    permit = get_success_data(api_client.create_take_permit(
        create_take_permit_payload(
            airport["id"], species["id"], regulator["id"],
            permit_number=permit_number,
            authorized_take_total=authorized_take_total,
            valid_from=valid_from, valid_to=valid_to,
        ),
        reg_headers,
    ))
    # Clock-set evaluates pending time-driven transitions (ISSUED -> ACTIVE
    # when the clock has reached valid_from).
    set_clock(clock)
    permit = get_success_data(api_client.get_take_permit(permit["id"], reg_headers))
    return {
        "airport": airport, "species": species,
        "senior": senior, "performer": performer, "regulator": regulator,
        "senior_headers": make_biologist_headers(senior["id"]),
        "performer_headers": make_biologist_headers(performer["id"]),
        "regulator_headers": reg_headers,
        "permit": permit,
    }


def create_logged_dispersal(airport_id: str, performer: dict, species_id: str,
                            performed_at: str = "2026-07-15T10:00:00Z",
                            method: str = "PYROTECHNICS",
                            animals_dispersed: int = 5,
                            animals_taken_lethal: int = 0,
                            take_permit_id=None) -> dict:
    payload = create_dispersal_activity_payload(
        airport_id, performer["id"], species_id,
        performed_at=performed_at, method=method,
        animals_dispersed=animals_dispersed,
        animals_taken_lethal=animals_taken_lethal,
    )
    if take_permit_id is not None:
        payload["take_permit_id"] = take_permit_id
    return get_success_data(api_client.create_dispersal_activity(
        payload, make_biologist_headers(performer["id"]),
    ))


def review_dispersal(dispersal_id: str, reviewer: dict) -> dict:
    return get_success_data(api_client.review_dispersal_activity(
        dispersal_id, make_biologist_headers(reviewer["id"]),
    ))


def close_dispersal(dispersal_id: str, closer: dict) -> dict:
    return get_success_data(api_client.close_dispersal_activity(
        dispersal_id, make_biologist_headers(closer["id"]),
    ))


def create_closed_dispersal(airport_id: str, performer: dict, reviewer: dict,
                            species_id: str, **kwargs) -> dict:
    """Create -> review -> close. reviewer must differ from performer and be
    senior for the close."""
    d = create_logged_dispersal(airport_id, performer, species_id, **kwargs)
    review_dispersal(d["id"], reviewer)
    return close_dispersal(d["id"], reviewer)


# ─── Tier 5: advisories / closures / plans / habitat ──

def create_draft_advisory(airport_id: str, issuer: dict,
                          hazard_level: str = "ELEVATED",
                          effective_from: str = "2026-08-01T00:00:00Z",
                          effective_to: str = "2026-09-01T00:00:00Z",
                          reason_code: str = "STRIKE_SPIKE",
                          issued_at: str = "2026-07-15T10:00:00Z") -> dict:
    return get_success_data(api_client.create_operational_advisory(
        create_advisory_payload(
            airport_id, issuer["id"],
            hazard_level=hazard_level, effective_from=effective_from,
            effective_to=effective_to, reason_code=reason_code,
            issued_at=issued_at,
        ),
        make_biologist_headers(issuer["id"]),
    ))


def activate_advisory(advisory_id: str, actor: dict, airport_id: str) -> dict:
    """Read the airport's current version, then activate with OCC."""
    headers = make_biologist_headers(actor["id"])
    airport = get_airport(airport_id, headers)
    return get_success_data(api_client.activate_operational_advisory(
        advisory_id, {"expected_airport_version": airport["version"]}, headers,
    ))


def create_requested_closure(airport_id: str, requester: dict,
                             runway_designator: str = "09L",
                             closure_start: str = "2026-08-01T09:00:00Z",
                             closure_end: str = "2026-08-01T10:00:00Z",
                             reason: str = "HAZARD_SWEEP") -> dict:
    return get_success_data(api_client.create_runway_closure(
        create_runway_closure_payload(
            airport_id, requester["id"],
            runway_designator=runway_designator,
            closure_start=closure_start, closure_end=closure_end,
            reason=reason,
        ),
        make_biologist_headers(requester["id"]),
    ))


def authorize_closure(closure_id: str, controller: dict) -> dict:
    return get_success_data(api_client.authorize_runway_closure(
        closure_id, make_atc_controller_headers(controller["id"]),
    ))


def create_draft_plan(airport_id: str, author: dict, plan_year: int = 2027,
                      version_note: str = "v1") -> dict:
    return get_success_data(api_client.create_annual_plan(
        create_annual_plan_payload(
            airport_id, plan_year=plan_year, version_note=version_note,
        ),
        make_biologist_headers(author["id"]),
    ))


def submit_plan(plan_id: str, author: dict) -> dict:
    return get_success_data(api_client.submit_annual_plan(
        plan_id, make_biologist_headers(author["id"]),
    ))


def approve_plan(plan_id: str, regulator: dict) -> dict:
    return get_success_data(api_client.approve_annual_plan(
        plan_id, make_regulator_headers(regulator["id"]),
    ))


def publish_plan(plan_id: str, author: dict, airport_id: str) -> dict:
    """Read airport version, then publish with OCC."""
    headers = make_biologist_headers(author["id"])
    airport = get_airport(airport_id, headers)
    return get_success_data(api_client.publish_annual_plan(
        plan_id, {"expected_airport_version": airport["version"]}, headers,
    ))


def create_assessment(airport_id: str, biologist: dict,
                      attractiveness_score: int = 5, severity_score: int = 5,
                      habitat_feature: str = "STANDING_WATER",
                      assessed_at: str = "2026-06-15T10:00:00Z") -> dict:
    return get_success_data(api_client.create_habitat_assessment(
        create_habitat_assessment_payload(
            airport_id, biologist["id"],
            assessed_at=assessed_at, habitat_feature=habitat_feature,
            attractiveness_score=attractiveness_score,
            severity_score=severity_score,
        ),
        make_biologist_headers(biologist["id"]),
    ))


def create_proposed_mitigation(assessment_id: str, proposer: dict,
                               action_type: str = "DRAINAGE",
                               target_completion_date: str = "2026-12-31") -> dict:
    return get_success_data(api_client.create_mitigation_action(
        assessment_id,
        create_mitigation_action_payload(
            proposer["id"], action_type=action_type,
            target_completion_date=target_completion_date,
        ),
        make_biologist_headers(proposer["id"]),
    ))


def mitigation_in_progress(assessment_id: str, proposer: dict, approver: dict,
                           target_completion_date: str = "2026-07-01") -> dict:
    """Propose -> approve (senior, != proposer) -> start-work. IN_PROGRESS.

    The approve call documents an explicit override so the walk is valid both
    for assessments at or above the mandatory threshold of 60 (composite
    confirmed, note ignored) and below it (PRD §3.3: "the reviewer must either
    confirm that the parent assessment's `composite_score` is at least the
    mandatory threshold of 60 or document an explicit override").
    """
    action = create_proposed_mitigation(
        assessment_id, proposer, target_completion_date=target_completion_date,
    )
    get_success_data(api_client.approve_mitigation_action(
        action["id"], make_biologist_headers(approver["id"]),
        payload={"override_note": "override documented by reviewing senior biologist"},
    ))
    return get_success_data(api_client.start_mitigation_work(
        action["id"], make_biologist_headers(proposer["id"]),
    ))


def setup_overdue_mitigation_scenario(icao_code: str = "KCCC"):
    """Airport with zero strikes and one IN_PROGRESS mitigation whose
    target_completion_date (2026-07-01) is before the logical clock
    (2026-08-01), i.e. overdue.

    The assessment uses a sub-threshold composite (5 * 9 = 45 < 60): PRD §3.3
    rejects at creation time any assessment whose composite_score is at least
    60 ("an assessment that would remain in breach of this rule at creation
    time surfaces ERR_MITIGATION_REQUIRED"), so the overdue-mitigation
    precondition is built below the threshold and approval goes through the
    PRD's explicit-override branch.

    Returns dict with airport, species, biologists (+headers), assessment,
    mitigation action.
    """
    set_clock()
    airport = create_airport(icao_code=icao_code, name="Charlie Airport")
    species = create_species(
        common_name="Canada Goose", scientific_name="Branta canadensis",
        guild="WATERFOWL", risk_tier="MEDIUM", body_mass_g=4500,
        is_protected_federally=True,
    )
    b1 = create_biologist(airport["id"], is_senior=True,
                          full_name="B One", certification_id="CERT-201")
    b3 = create_biologist(airport["id"], is_senior=True,
                          full_name="B Three", certification_id="CERT-203")
    assessment = create_assessment(
        airport["id"], b1, attractiveness_score=5, severity_score=9,
    )
    action = mitigation_in_progress(
        assessment["id"], b1, b3, target_completion_date="2026-07-01",
    )
    return {
        "airport": airport, "species": species, "b1": b1, "b3": b3,
        "b1_headers": make_biologist_headers(b1["id"]),
        "b3_headers": make_biologist_headers(b3["id"]),
        "assessment": assessment, "action": action,
    }
