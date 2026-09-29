"""Composite setup helpers.

Each test starts against an empty store, so every helper here builds the state
it needs from scratch through the API's own declared endpoints. Setup steps use
`get_success_data`, which accepts any 2xx and raises immediately with the
server's error identifier if a setup step fails — so a broken setup never
masquerades as a failed assertion.

The returned context dictionaries are plain dicts; a test reads only the keys it
cares about.
"""

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import FIVE_BAND_LADDER, TEST_DEFAULTS, TWO_BAND_LADDER
from .factories import (
    adopt_fee_schedule_payload,
    bill_encounter_payload,
    claim_wraparound_payload,
    create_board_member_payload,
    create_corrective_action_plan_payload,
    create_discount_tier_payload,
    create_encounter_payload,
    create_fee_schedule_payload,
    create_health_center_payload,
    create_income_verification_payload,
    create_patient_payload,
    create_patient_seat_payload,
    create_poverty_guideline_payload,
    create_quality_measure_result_payload,
    create_scope_change_request_payload,
    create_service_definition_payload,
    create_service_site_payload,
    create_site_visit_finding_payload,
    create_uds_report_payload,
    create_waiver_payload,
    decide_waiver_payload,
    record_payment_payload,
    set_clock_payload,
    verify_income_verification_payload,
)
from .test_users import (
    SECOND_USERS,
    TEST_USERS,
    make_board_chair_headers,
)

ADMIN = TEST_USERS["platform_admin_headers"]
OFFICER = TEST_USERS["compliance_officer_headers"]
VERIFIER = TEST_USERS["eligibility_verifier_headers"]
REP = TEST_USERS["patient_services_rep_headers"]
BILLER = TEST_USERS["billing_specialist_headers"]
PROJECT_OFFICER = TEST_USERS["project_officer_headers"]

SECOND_OFFICER = SECOND_USERS["compliance_officer_headers"]
SECOND_VERIFIER = SECOND_USERS["eligibility_verifier_headers"]
SECOND_REP = SECOND_USERS["patient_services_rep_headers"]
SECOND_BILLER = SECOND_USERS["billing_specialist_headers"]
SECOND_PROJECT_OFFICER = SECOND_USERS["project_officer_headers"]

DEFAULT_GUIDELINE_YEARS = (
    (
        2025,
        TEST_DEFAULTS["GUIDELINE_2025_BASE_CENTS"],
        TEST_DEFAULTS["GUIDELINE_2025_INCREMENT_CENTS"],
    ),
    (
        2026,
        TEST_DEFAULTS["GUIDELINE_2026_BASE_CENTS"],
        TEST_DEFAULTS["GUIDELINE_2026_INCREMENT_CENTS"],
    ),
)


# ---------------------------------------------------------------------------
# Small utilities
# ---------------------------------------------------------------------------


def advance_clock(current_utc: str) -> dict:
    """Move the logical compliance clock to an explicit instant."""
    return get_success_data(api_client.set_clock(set_clock_payload(current_utc), ADMIN))


def refresh_health_center(health_center_id: str, headers: dict = None) -> dict:
    return get_success_data(
        api_client.get_health_center(health_center_id, headers or ADMIN)
    )


def refresh_encounter(encounter_id: str, headers: dict = None) -> dict:
    return get_success_data(api_client.get_encounter(encounter_id, headers or BILLER))


def refresh_patient(patient_id: str, headers: dict = None) -> dict:
    return get_success_data(api_client.get_patient(patient_id, headers or REP))


def refresh_service_site(service_site_id: str, headers: dict = None) -> dict:
    return get_success_data(
        api_client.get_service_site(service_site_id, headers or ADMIN)
    )


def refresh_fee_schedule(fee_schedule_id: str, headers: dict = None) -> dict:
    return get_success_data(
        api_client.get_fee_schedule(fee_schedule_id, headers or OFFICER)
    )


def refresh_finding(site_visit_finding_id: str, headers: dict = None) -> dict:
    return get_success_data(
        api_client.get_site_visit_finding(site_visit_finding_id, headers or OFFICER)
    )


def refresh_scope_change_request(request_id: str, headers: dict = None) -> dict:
    return get_success_data(
        api_client.get_scope_change_request(request_id, headers or OFFICER)
    )


def refresh_uds_report(uds_report_id: str, headers: dict = None) -> dict:
    return get_success_data(
        api_client.get_uds_report(uds_report_id, headers or OFFICER)
    )


# ---------------------------------------------------------------------------
# Poverty guidelines
# ---------------------------------------------------------------------------


def seed_poverty_guidelines(years=DEFAULT_GUIDELINE_YEARS) -> dict:
    """Insert one guideline row per requested year; returns {year: row}."""
    rows = {}
    for year, base_amount_cents, increment_cents in years:
        rows[year] = get_success_data(
            api_client.create_poverty_guideline(
                create_poverty_guideline_payload(
                    guideline_year=year,
                    base_amount_cents=base_amount_cents,
                    increment_cents=increment_cents,
                ),
                ADMIN,
            )
        )
    return rows


# ---------------------------------------------------------------------------
# Grantee scaffolding
# ---------------------------------------------------------------------------


def setup_grantee(
    *,
    legal_name: str = "Riverbend Community Health",
    grant_number: str = "H80CS00426",
    pps_base_rate_cents: int = TEST_DEFAULTS["PPS_BASE_RATE_CENTS"],
    medicare_upper_limit_cents: int = TEST_DEFAULTS["MEDICARE_UPPER_LIMIT_CENTS"],
    nominal_fee_cap_cents: int = TEST_DEFAULTS["NOMINAL_FEE_CAP_CENTS"],
    **overrides,
) -> dict:
    """Register a grantee only — no sites, services, board or schedule."""
    payload = create_health_center_payload(
        legal_name=legal_name,
        grant_number=grant_number,
        pps_base_rate_cents=pps_base_rate_cents,
        medicare_upper_limit_cents=medicare_upper_limit_cents,
        nominal_fee_cap_cents=nominal_fee_cap_cents,
        **overrides,
    )
    return get_success_data(api_client.create_health_center(payload, ADMIN))


def setup_baseline_site(
    health_center_id: str,
    *,
    site_name: str = "Main Clinic",
    site_type: str = "SERVICE_DELIVERY",
    in_initial_scope: bool = True,
    **overrides,
) -> dict:
    payload = create_service_site_payload(
        site_name=site_name,
        site_type=site_type,
        in_initial_scope=in_initial_scope,
        **overrides,
    )
    return get_success_data(
        api_client.create_service_site(health_center_id, payload, ADMIN)
    )


def setup_baseline_service(
    health_center_id: str,
    *,
    service_code: str = "GEN_PRIMARY_CARE",
    service_category: str = "REQUIRED_PRIMARY",
    delivery_method: str = "COLUMN_I_DIRECT",
    in_initial_scope: bool = True,
    **overrides,
) -> dict:
    payload = create_service_definition_payload(
        service_code=service_code,
        service_category=service_category,
        delivery_method=delivery_method,
        in_initial_scope=in_initial_scope,
        **overrides,
    )
    return get_success_data(
        api_client.create_service_definition(health_center_id, payload, ADMIN)
    )


def setup_board_seat(health_center_id: str, **overrides) -> dict:
    """Seat one non-patient board member; its id is the chair's identity."""
    payload = create_board_member_payload(**overrides)
    return get_success_data(
        api_client.create_board_member(health_center_id, payload, OFFICER)
    )


def setup_tier_ladder(fee_schedule_id: str, ladder=FIVE_BAND_LADDER) -> list:
    tiers = []
    for band in ladder:
        tiers.append(
            get_success_data(
                api_client.create_discount_tier(
                    fee_schedule_id, create_discount_tier_payload(**band), OFFICER
                )
            )
        )
    return tiers


def setup_draft_fee_schedule(
    health_center_id: str,
    *,
    fpg_year: int = TEST_DEFAULTS["FPG_YEAR"],
    effective_start: str = TEST_DEFAULTS["EFFECTIVE_START"],
    effective_end: str = TEST_DEFAULTS["EFFECTIVE_END"],
    nominal_fee_cents: int = TEST_DEFAULTS["NOMINAL_FEE_CENTS"],
    ladder=FIVE_BAND_LADDER,
    **overrides,
) -> dict:
    """Create a DRAFT schedule and hang a well-formed tier ladder on it."""
    schedule = get_success_data(
        api_client.create_fee_schedule(
            health_center_id,
            create_fee_schedule_payload(
                fpg_year=fpg_year,
                effective_start=effective_start,
                effective_end=effective_end,
                nominal_fee_cents=nominal_fee_cents,
                **overrides,
            ),
            OFFICER,
        )
    )
    tiers = setup_tier_ladder(schedule["id"], ladder) if ladder else []
    return {"fee_schedule": schedule, "tiers": tiers}


def adopt_schedule(health_center_id: str, fee_schedule_id: str, chair_id: str) -> dict:
    """Adopt a schedule, reading the grantee's version immediately beforehand.

    The chair is the seated board member whose row backs the acting identity;
    the adopt call carries the grantee version observed by that fresh read.
    """
    chair_headers = make_board_chair_headers(chair_id)
    observed = get_success_data(
        api_client.get_health_center(health_center_id, chair_headers)
    )
    adopted = get_success_data(
        api_client.adopt_fee_schedule(
            fee_schedule_id,
            adopt_fee_schedule_payload(observed["version"]),
            chair_headers,
        )
    )
    return {"fee_schedule": adopted, "observed_version": observed["version"]}


def setup_grantee_with_adopted_schedule(
    *,
    legal_name: str = "Riverbend Community Health",
    grant_number: str = "H80CS00426",
    pps_base_rate_cents: int = TEST_DEFAULTS["PPS_BASE_RATE_CENTS"],
    medicare_upper_limit_cents: int = TEST_DEFAULTS["MEDICARE_UPPER_LIMIT_CENTS"],
    nominal_fee_cap_cents: int = TEST_DEFAULTS["NOMINAL_FEE_CAP_CENTS"],
    guideline_years=DEFAULT_GUIDELINE_YEARS,
    site_name: str = "Main Clinic",
    site_type: str = "SERVICE_DELIVERY",
    service_code: str = "GEN_PRIMARY_CARE",
    service_category: str = "REQUIRED_PRIMARY",
    delivery_method: str = "COLUMN_I_DIRECT",
    fpg_year: int = TEST_DEFAULTS["FPG_YEAR"],
    effective_start: str = TEST_DEFAULTS["EFFECTIVE_START"],
    effective_end: str = TEST_DEFAULTS["EFFECTIVE_END"],
    nominal_fee_cents: int = TEST_DEFAULTS["NOMINAL_FEE_CENTS"],
    ladder=FIVE_BAND_LADDER,
) -> dict:
    """The full sliding-fee bootstrap.

    Guidelines, a grantee, one baseline site, one baseline service, one seated
    board member, a draft schedule with its tier ladder, and adoption by the
    chair — leaving a grantee that can price an encounter.
    """
    guidelines = seed_poverty_guidelines(guideline_years) if guideline_years else {}
    health_center = setup_grantee(
        legal_name=legal_name,
        grant_number=grant_number,
        pps_base_rate_cents=pps_base_rate_cents,
        medicare_upper_limit_cents=medicare_upper_limit_cents,
        nominal_fee_cap_cents=nominal_fee_cap_cents,
    )
    site = setup_baseline_site(
        health_center["id"], site_name=site_name, site_type=site_type
    )
    service = setup_baseline_service(
        health_center["id"],
        service_code=service_code,
        service_category=service_category,
        delivery_method=delivery_method,
    )
    chair = setup_board_seat(health_center["id"])
    draft = setup_draft_fee_schedule(
        health_center["id"],
        fpg_year=fpg_year,
        effective_start=effective_start,
        effective_end=effective_end,
        nominal_fee_cents=nominal_fee_cents,
        ladder=ladder,
    )
    adoption = adopt_schedule(health_center["id"], draft["fee_schedule"]["id"], chair["id"])
    return {
        "guidelines": guidelines,
        "health_center": health_center,
        "health_center_id": health_center["id"],
        "site": site,
        "site_id": site["id"],
        "service": service,
        "service_id": service["id"],
        "chair": chair,
        "chair_id": chair["id"],
        "chair_headers": make_board_chair_headers(chair["id"]),
        "fee_schedule": adoption["fee_schedule"],
        "fee_schedule_id": adoption["fee_schedule"]["id"],
        "tiers": draft["tiers"],
        "tiers_by_label": {t["tier_label"]: t for t in draft["tiers"]},
        "observed_version_at_adopt": adoption["observed_version"],
    }


def setup_grantee_scope_only(
    *,
    legal_name: str = "Riverbend Community Health",
    grant_number: str = "H80CS00426",
    guideline_years=DEFAULT_GUIDELINE_YEARS,
    site_type: str = "SERVICE_DELIVERY",
    **overrides,
) -> dict:
    """A grantee with baseline scope and a seated chair but no fee schedule."""
    guidelines = seed_poverty_guidelines(guideline_years) if guideline_years else {}
    health_center = setup_grantee(
        legal_name=legal_name, grant_number=grant_number, **overrides
    )
    site = setup_baseline_site(health_center["id"], site_type=site_type)
    service = setup_baseline_service(health_center["id"])
    chair = setup_board_seat(health_center["id"])
    return {
        "guidelines": guidelines,
        "health_center": health_center,
        "health_center_id": health_center["id"],
        "site": site,
        "site_id": site["id"],
        "service": service,
        "service_id": service["id"],
        "chair": chair,
        "chair_id": chair["id"],
        "chair_headers": make_board_chair_headers(chair["id"]),
    }


# ---------------------------------------------------------------------------
# Named bootstraps reused across many scenarios
# ---------------------------------------------------------------------------


def setup_boot_fs() -> dict:
    """Riverbend with the five-band ladder adopted for calendar 2026."""
    return setup_grantee_with_adopted_schedule()


def setup_boot_core() -> dict:
    """A grantee with the minimal two-band ladder adopted for calendar 2026."""
    return setup_grantee_with_adopted_schedule(
        legal_name="Corner Community Health",
        grant_number="H80CS00500",
        pps_base_rate_cents=20000,
        guideline_years=((2026, 1620000, 570000),),
        site_name="Corner Clinic",
        ladder=TWO_BAND_LADDER,
    )


def setup_boot_gov() -> dict:
    """The five-band bootstrap plus a patient-majority board.

    Two patients with verified income and one encounter each become the
    occupants of two patient seats, bringing the board to three seated members
    of whom two hold patient seats.
    """
    ctx = setup_boot_fs()
    first = setup_verified_patient(
        ctx,
        mrn="MRN-001",
        full_name="Ada Rivera",
        household_size=2,
        declared_annual_income_cents=2190000,
    )
    first_encounter = setup_encounter(ctx, first["patient"]["id"])
    second = setup_verified_patient(
        ctx,
        mrn="MRN-002",
        full_name="Bo Nkemi",
        household_size=2,
        declared_annual_income_cents=2188000,
        documentation_type="PAY_STUBS",
    )
    second_encounter = setup_encounter(
        ctx, second["patient"]["id"], gross_charge_cents=20000
    )
    seat_two = get_success_data(
        api_client.create_board_member(
            ctx["health_center_id"],
            create_patient_seat_payload(first["patient"]["id"], seat_number=2),
            OFFICER,
        )
    )
    seat_three = get_success_data(
        api_client.create_board_member(
            ctx["health_center_id"],
            create_patient_seat_payload(second["patient"]["id"], seat_number=3),
            OFFICER,
        )
    )
    ctx.update(
        {
            "patient_one": first["patient"],
            "verification_one": first["income_verification"],
            "encounter_one": first_encounter,
            "patient_two": second["patient"],
            "verification_two": second["income_verification"],
            "encounter_two": second_encounter,
            "patient_seats": [seat_two, seat_three],
            "health_center": refresh_health_center(ctx["health_center_id"]),
        }
    )
    return ctx


def setup_boot_pt() -> dict:
    """The two-band bootstrap plus one patient whose income is verified."""
    ctx = setup_boot_core()
    verified = setup_verified_patient(
        ctx,
        mrn="MRN-C01",
        full_name="Val Osei",
        household_size=1,
        declared_annual_income_cents=1000000,
        effective_date="2026-03-01T00:00:00Z",
    )
    ctx.update(verified)
    return ctx


# ---------------------------------------------------------------------------
# Patients and income verification
# ---------------------------------------------------------------------------


def setup_patient(
    *,
    mrn: str = "MRN-001",
    full_name: str = "Ada Rivera",
    household_size: int = 2,
    **overrides,
) -> dict:
    return get_success_data(
        api_client.create_patient(
            create_patient_payload(
                mrn=mrn,
                full_name=full_name,
                household_size=household_size,
                **overrides,
            ),
            REP,
        )
    )


def setup_income_verification(
    patient: dict,
    *,
    declared_annual_income_cents: int = 2190000,
    household_size: int = None,
    documentation_type: str = "TAX_RETURN",
    effective_date: str = "2026-02-01T00:00:00Z",
    headers: dict = None,
    **overrides,
) -> dict:
    """File an income verification, threading the patient's current version."""
    payload = create_income_verification_payload(
        patient["version"],
        declared_annual_income_cents=declared_annual_income_cents,
        household_size=(
            household_size
            if household_size is not None
            else patient["household_size"]
        ),
        documentation_type=documentation_type,
        effective_date=effective_date,
        **overrides,
    )
    return get_success_data(
        api_client.create_income_verification(patient["id"], payload, headers or REP)
    )


def verify_income(income_verification: dict, headers: dict = None) -> dict:
    return get_success_data(
        api_client.verify_income_verification(
            income_verification["id"],
            verify_income_verification_payload("VERIFY"),
            headers or VERIFIER,
        )
    )


def setup_verified_patient(
    ctx: dict = None,
    *,
    mrn: str = "MRN-001",
    full_name: str = "Ada Rivera",
    household_size: int = 2,
    declared_annual_income_cents: int = 2190000,
    documentation_type: str = "TAX_RETURN",
    effective_date: str = "2026-02-01T00:00:00Z",
) -> dict:
    """A patient with one verified income verification on file."""
    patient = setup_patient(
        mrn=mrn, full_name=full_name, household_size=household_size
    )
    verification = setup_income_verification(
        patient,
        declared_annual_income_cents=declared_annual_income_cents,
        household_size=household_size,
        documentation_type=documentation_type,
        effective_date=effective_date,
    )
    verified = verify_income(verification)
    return {
        "patient": refresh_patient(patient["id"]),
        "patient_id": patient["id"],
        "income_verification": verified,
        "income_verification_id": verified["id"],
    }


def setup_unverified_patient(
    *, mrn: str = "MRN-900", full_name: str = "Unverified Patient", household_size: int = 1
) -> dict:
    return setup_patient(mrn=mrn, full_name=full_name, household_size=household_size)


# ---------------------------------------------------------------------------
# Encounters
# ---------------------------------------------------------------------------


def setup_encounter(
    ctx: dict,
    patient_id: str,
    *,
    encounter_date: str = "2026-03-01T00:00:00Z",
    payer_type: str = "SELF_PAY",
    gross_charge_cents: int = 12000,
    service_site_id: str = None,
    service_definition_id: str = None,
    headers: dict = None,
    **overrides,
) -> dict:
    payload = create_encounter_payload(
        patient_id,
        service_site_id or ctx["site_id"],
        service_definition_id or ctx["service_id"],
        encounter_date=encounter_date,
        payer_type=payer_type,
        gross_charge_cents=gross_charge_cents,
        **overrides,
    )
    return get_success_data(api_client.create_encounter(payload, headers or BILLER))


def bill_encounter(
    encounter: dict, claim_reference: str = "CLM-3001", headers: dict = None
) -> dict:
    return get_success_data(
        api_client.bill_encounter(
            encounter["id"], bill_encounter_payload(claim_reference), headers or BILLER
        )
    )


def setup_billed_encounter(
    ctx: dict,
    patient_id: str,
    *,
    claim_reference: str = "CLM-3001",
    **encounter_kwargs,
) -> dict:
    encounter = setup_encounter(ctx, patient_id, **encounter_kwargs)
    return bill_encounter(encounter, claim_reference)


def setup_wraparound_claimed_encounter(
    ctx: dict,
    patient_id: str,
    *,
    payer_type: str = "MEDICAID_MCO",
    gross_charge_cents: int = 30000,
    claim_reference: str = "CLM-4001",
    mco_paid_cents: int = 14000,
    **encounter_kwargs,
) -> dict:
    """An encounter billed, part-paid by the plan, with the residual claimed."""
    encounter = setup_encounter(
        ctx,
        patient_id,
        payer_type=payer_type,
        gross_charge_cents=gross_charge_cents,
        **encounter_kwargs,
    )
    bill_encounter(encounter, claim_reference)
    get_success_data(
        api_client.record_encounter_payment(
            encounter["id"], record_payment_payload(mco_paid_cents), BILLER
        )
    )
    return get_success_data(
        api_client.claim_wraparound(encounter["id"], BILLER, claim_wraparound_payload())
    )


# ---------------------------------------------------------------------------
# Waivers
# ---------------------------------------------------------------------------


def setup_requested_waiver(
    encounter: dict,
    *,
    waiver_reason: str = "NO_INCOME",
    headers: dict = None,
    **overrides,
) -> dict:
    return get_success_data(
        api_client.create_waiver(
            encounter["id"],
            create_waiver_payload(waiver_reason=waiver_reason, **overrides),
            headers or SECOND_REP,
        )
    )


def decide_waiver(waiver: dict, decision: str, headers: dict = None) -> dict:
    """Adjudicate a waiver as an operator other than the one who filed it."""
    return get_success_data(
        api_client.decide_waiver(
            waiver["id"], decide_waiver_payload(decision), headers or SECOND_OFFICER
        )
    )


def setup_granted_waiver(encounter: dict, *, waiver_reason: str = "NO_INCOME") -> dict:
    waiver = setup_requested_waiver(encounter, waiver_reason=waiver_reason)
    return decide_waiver(waiver, "GRANT")


# ---------------------------------------------------------------------------
# Uniform data system reporting
# ---------------------------------------------------------------------------


def setup_draft_uds_report(ctx: dict, *, reporting_year: int = 2026) -> dict:
    return get_success_data(
        api_client.create_uds_report(
            ctx["health_center_id"],
            create_uds_report_payload(reporting_year=reporting_year),
            OFFICER,
        )
    )


def setup_quality_measure(
    uds_report: dict,
    *,
    measure_code: str = "DIABETES_A1C",
    numerator: int = 7,
    denominator: int = 9,
    benchmark_pct: float = 77.8,
) -> dict:
    return get_success_data(
        api_client.create_quality_measure_result(
            uds_report["id"],
            create_quality_measure_result_payload(
                measure_code=measure_code,
                numerator=numerator,
                denominator=denominator,
                benchmark_pct=benchmark_pct,
            ),
            OFFICER,
        )
    )


def compute_uds_report(uds_report: dict, headers: dict = None) -> dict:
    return get_success_data(
        api_client.compute_uds_report(uds_report["id"], headers or OFFICER)
    )


def submit_uds_report(uds_report: dict, headers: dict = None) -> dict:
    return get_success_data(
        api_client.submit_uds_report(uds_report["id"], headers or OFFICER)
    )


def setup_submitted_uds_report(
    ctx: dict, *, reporting_year: int = 2026, measures=()
) -> dict:
    """A report with its measures recorded, computed and then submitted."""
    report = setup_draft_uds_report(ctx, reporting_year=reporting_year)
    recorded = [setup_quality_measure(report, **measure) for measure in measures]
    compute_uds_report(report)
    submitted = submit_uds_report(report)
    return {"uds_report": submitted, "quality_measures": recorded}


# ---------------------------------------------------------------------------
# Site visit findings and corrective action plans
# ---------------------------------------------------------------------------


def setup_open_finding(
    ctx: dict,
    *,
    requirement_code: str = "REQ_SLIDING_FEE_16",
    severity: str = "CONDITION",
    cap_due_days: int = 30,
    headers: dict = None,
    **overrides,
) -> dict:
    return get_success_data(
        api_client.create_site_visit_finding(
            ctx["health_center_id"],
            create_site_visit_finding_payload(
                requirement_code=requirement_code,
                severity=severity,
                cap_due_days=cap_due_days,
                **overrides,
            ),
            headers or PROJECT_OFFICER,
        )
    )


def setup_draft_corrective_action_plan(
    finding: dict,
    *,
    target_completion_date: str = "2026-08-15T00:00:00Z",
    milestone_count: int = 3,
    headers: dict = None,
    **overrides,
) -> dict:
    return get_success_data(
        api_client.create_corrective_action_plan(
            finding["id"],
            create_corrective_action_plan_payload(
                target_completion_date=target_completion_date,
                milestone_count=milestone_count,
                **overrides,
            ),
            headers or OFFICER,
        )
    )


def setup_submitted_corrective_action_plan(finding: dict, **overrides) -> dict:
    plan = setup_draft_corrective_action_plan(finding, **overrides)
    return get_success_data(
        api_client.submit_corrective_action_plan(plan["id"], OFFICER)
    )


# ---------------------------------------------------------------------------
# Change-in-scope requests
# ---------------------------------------------------------------------------


def lock_scope_baseline(ctx: dict) -> dict:
    """Lock the Notice-of-Award baseline, so later sites are created PROPOSED."""
    return get_success_data(
        api_client.lock_scope_baseline(ctx["health_center_id"], ADMIN)
    )


def setup_proposed_site(
    ctx: dict, *, site_name: str = "Corner Annex Clinic", **overrides
) -> dict:
    """A site created without the baseline flag, so it sits at PROPOSED."""
    return get_success_data(
        api_client.create_service_site(
            ctx["health_center_id"],
            create_service_site_payload(
                site_name=site_name, in_initial_scope=False, **overrides
            ),
            ADMIN,
        )
    )


def setup_draft_scope_change_request(
    ctx: dict,
    *,
    request_type: str = "ADD_SITE",
    target_site_id: str = None,
    target_service_definition_id: str = None,
    headers: dict = None,
    **overrides,
) -> dict:
    payload = create_scope_change_request_payload(request_type=request_type, **overrides)
    if target_site_id is not None:
        payload["target_site_id"] = target_site_id
    if target_service_definition_id is not None:
        payload["target_service_definition_id"] = target_service_definition_id
    return get_success_data(
        api_client.create_scope_change_request(
            ctx["health_center_id"], payload, headers or OFFICER
        )
    )


def submit_scope_change_request(request: dict, headers: dict = None) -> dict:
    return get_success_data(
        api_client.submit_scope_change_request(request["id"], headers or SECOND_OFFICER)
    )


def begin_review_scope_change_request(request: dict, chair_id: str) -> dict:
    return get_success_data(
        api_client.begin_review_scope_change_request(
            request["id"], make_board_chair_headers(chair_id)
        )
    )


def setup_scope_change_request_under_review(
    ctx: dict, *, request_type: str = "ADD_SITE", target_site_id: str = None, **overrides
) -> dict:
    """A request drafted, submitted by a second officer, then taken under review."""
    request = setup_draft_scope_change_request(
        ctx,
        request_type=request_type,
        target_site_id=target_site_id,
        **overrides,
    )
    submit_scope_change_request(request)
    return begin_review_scope_change_request(request, ctx["chair_id"])


# ---------------------------------------------------------------------------
# Second grantee, for cross-grantee reference scenarios
# ---------------------------------------------------------------------------


def setup_second_grantee_with_scope(
    *,
    legal_name: str = "Northgate Community Health",
    grant_number: str = "H80CS00999",
    guideline_years=(),
) -> dict:
    """A distinct grantee with its own site, service and seated chair."""
    return setup_grantee_scope_only(
        legal_name=legal_name,
        grant_number=grant_number,
        guideline_years=guideline_years,
    )
