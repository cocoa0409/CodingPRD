"""Composite setup helpers.

Multi-step API sequences shared by the test suite. Every helper builds its
preconditions from scratch through PRD-declared endpoints (each test runs
against a freshly restarted server with an empty database and the logical
clock at 2026-08-01T00:00:00Z). Setup calls use the lenient get_success_data
validator so a setup failure surfaces as a clear error naming the step.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_accident_payload,
    create_audit_case_payload,
    create_carrier_payload,
    create_category_payload,
    create_challenge_payload,
    create_coaching_payload,
    create_document_payload,
    create_driver_payload,
    create_inspection_payload,
    create_period_payload,
    create_premium_model_payload,
    create_test_payload,
    create_upgrade_request_payload,
    create_violation_payload,
)
from .test_users import (
    TEST_USERS,
    make_director_headers,
    make_manager_headers,
    make_mro_headers,
)

ADMIN = TEST_USERS["admin_headers"]
DIRECTOR = TEST_USERS["director_headers"]
MANAGER = TEST_USERS["manager_headers"]
ANALYST = TEST_USERS["analyst_headers"]
MRO = TEST_USERS["mro_headers"]
INSURANCE = TEST_USERS["insurance_headers"]

# Distinct operator ids used where segregation of duties compares X-User-ID.
RECORDER_USER = "sm-1"
DETERMINER_USER = "sd-1"
MRO_USER = "mro-1"


# ---------------------------------------------------------------------------
# Tier 1: single-entity creation
# ---------------------------------------------------------------------------

def make_carrier(headers=None, **overrides):
    resp = api_client.create_carrier(create_carrier_payload(**overrides), headers or ADMIN)
    return get_success_data(resp)


def make_category(headers=None, **overrides):
    resp = api_client.create_category(create_category_payload(**overrides), headers or ADMIN)
    return get_success_data(resp)


def make_driver(carrier_id, headers=None, **overrides):
    resp = api_client.create_driver(
        create_driver_payload(carrier_id, **overrides), headers or MANAGER
    )
    return get_success_data(resp)


def make_inspection(carrier_id, driver_id, headers=None, **overrides):
    resp = api_client.create_inspection(
        create_inspection_payload(carrier_id, driver_id, **overrides), headers or MANAGER
    )
    return get_success_data(resp)


def make_violation(inspection_id, category_id, headers=None, **overrides):
    resp = api_client.create_violation(
        create_violation_payload(inspection_id, category_id, **overrides),
        headers or MANAGER,
    )
    return get_success_data(resp)


def make_challenge(violation_id, headers=None, **overrides):
    resp = api_client.create_challenge(
        create_challenge_payload(violation_id, **overrides), headers or ANALYST
    )
    return get_success_data(resp)


def make_drug_test(driver_id, headers=None, **overrides):
    # Recorded by a stable user id so MRO verification by MRO_USER passes SoD.
    resp = api_client.create_test(
        create_test_payload(driver_id, **overrides),
        headers or make_manager_headers(RECORDER_USER),
    )
    return get_success_data(resp)


def make_accident(carrier_id, driver_id, headers=None, **overrides):
    # Registered by a stable user id so a SafetyDirector with DETERMINER_USER
    # passes the preventability SoD check.
    resp = api_client.create_accident(
        create_accident_payload(carrier_id, driver_id, **overrides),
        headers or make_manager_headers(RECORDER_USER),
    )
    return get_success_data(resp)


def make_audit_case(carrier_id, headers=None, **overrides):
    resp = api_client.create_audit_case(
        create_audit_case_payload(carrier_id, **overrides), headers or ADMIN
    )
    return get_success_data(resp)


def make_upgrade_request(carrier_id, headers=None, **overrides):
    resp = api_client.create_upgrade_request(
        create_upgrade_request_payload(carrier_id, **overrides), headers or MANAGER
    )
    return get_success_data(resp)


def make_premium_model(carrier_id, headers=None, **overrides):
    resp = api_client.create_premium_model(
        create_premium_model_payload(carrier_id, **overrides), headers or INSURANCE
    )
    return get_success_data(resp)


def make_document(carrier_id, headers=None, **overrides):
    resp = api_client.create_document(
        create_document_payload(carrier_id, **overrides), headers or MANAGER
    )
    return get_success_data(resp)


def make_period(carrier_id, headers=None, **overrides):
    resp = api_client.create_period(
        create_period_payload(carrier_id, **overrides), headers or MANAGER
    )
    return get_success_data(resp)


def set_clock(to_iso8601, headers=None):
    resp = api_client.set_clock({"to_iso8601": to_iso8601}, headers or ADMIN)
    return get_success_data(resp)


def run_cycle(carrier_id, headers=None):
    resp = api_client.run_measurement_cycle({"carrier_id": carrier_id}, headers or ANALYST)
    return get_success_data(resp)


def get_carrier(carrier_id, headers=None):
    return get_success_data(api_client.get_carrier(carrier_id, headers or ADMIN))


def get_driver(driver_id, headers=None):
    return get_success_data(api_client.get_driver(driver_id, headers or MANAGER))


def get_inspection(inspection_id, headers=None):
    return get_success_data(api_client.get_inspection(inspection_id, headers or MANAGER))


def get_violation(violation_id, headers=None):
    return get_success_data(api_client.get_violation(violation_id, headers or MANAGER))


def get_challenge(challenge_id, headers=None):
    return get_success_data(api_client.get_challenge(challenge_id, headers or ADMIN))


def get_coaching(coaching_id, headers=None):
    return get_success_data(api_client.get_coaching(coaching_id, headers or MANAGER))


def get_test(test_id, headers=None):
    return get_success_data(api_client.get_test(test_id, headers or MANAGER))


def get_premium_model(model_id, headers=None):
    return get_success_data(api_client.get_premium_model(model_id, headers or INSURANCE))


def get_document(document_id, headers=None):
    return get_success_data(api_client.get_document(document_id, headers or MANAGER))


def get_period(period_id, headers=None):
    return get_success_data(api_client.get_period(period_id, headers or MANAGER))


def list_snapshots(headers=None, **params):
    data, _meta = _list(api_client.list_snapshots(headers or ANALYST, params=params))
    return data


def _list(resp):
    from prd_bench_local_runner.testing import validate_paginated

    return validate_paginated(resp)


# ---------------------------------------------------------------------------
# Tier 2: small composites
# ---------------------------------------------------------------------------

def make_carrier_with_driver(headers=None, carrier_overrides=None, driver_overrides=None):
    carrier = make_carrier(headers=headers, **(carrier_overrides or {}))
    driver = make_driver(carrier["id"], **(driver_overrides or {}))
    return carrier, driver


def make_inspection_with_violation(
    category_code="VEHICLE_MAINTENANCE",
    severity_weight=5,
    occurred_at="2026-05-01T00:00:00Z",
    violation_overrides=None,
    **kwargs,
):
    """Carrier + category + driver + inspection + one violation."""
    carrier = make_carrier(**kwargs.pop("carrier_overrides", {}))
    category = make_category(category_code=category_code, **kwargs.pop("category_overrides", {}))
    driver = make_driver(carrier["id"], **kwargs.pop("driver_overrides", {}))
    inspection = make_inspection(
        carrier["id"], driver["id"], **kwargs.pop("inspection_overrides", {})
    )
    payload = {"severity_weight": severity_weight, "occurred_at": occurred_at}
    payload.update(violation_overrides or {})
    violation = make_violation(inspection["id"], category["id"], **payload)
    return carrier, category, driver, inspection, violation


def make_challenge_under_review(violation_id, **overrides):
    """File a challenge and move it SUBMITTED -> UNDER_REVIEW."""
    challenge = make_challenge(violation_id, **overrides)
    get_success_data(api_client.start_review_challenge(challenge["id"], ADMIN))
    return get_challenge(challenge["id"])


def make_coaching(driver_id, headers=None, **overrides):
    """Create coaching with the driver's CURRENT version (OCC, PRD §2.7)."""
    driver = get_driver(driver_id)
    payload = create_coaching_payload(driver_id, driver["version"], **overrides)
    resp = api_client.create_coaching(payload, headers or MANAGER)
    return get_success_data(resp)


def report_lab(test_id, lab_result, headers=None):
    resp = api_client.report_lab_result(test_id, {"lab_result": lab_result}, headers or MANAGER)
    return get_success_data(resp)


def mro_verify(test_id, verdict, user_id=MRO_USER):
    resp = api_client.verify_test(test_id, {"verdict": verdict}, make_mro_headers(user_id))
    return get_success_data(resp)


def make_verified_test(driver_id, lab_result, verdict, **overrides):
    """COLLECTED -> LAB_REPORTED -> MRO_VERIFIED."""
    test = make_drug_test(driver_id, **overrides)
    report_lab(test["id"], lab_result)
    return mro_verify(test["id"], verdict)


def determine_preventability(accident_id, determination, user_id=DETERMINER_USER):
    resp = api_client.determine_preventability(
        accident_id, {"determination": determination}, make_director_headers(user_id)
    )
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 3: audit lifecycle shortcuts
# ---------------------------------------------------------------------------

def audit_to_findings(carrier_id, acute_count, critical_count, **audit_overrides):
    """Create an audit, start field work (clock defaults to 2026-08-01, so the
    default scheduled_date of 2026-08-01 is already reached), issue findings.
    Returns the case data after findings."""
    case = make_audit_case(carrier_id, **audit_overrides)
    get_success_data(api_client.start_field_work(case["id"], ADMIN))
    resp = api_client.issue_findings(
        case["id"], {"acute_count": acute_count, "critical_count": critical_count}, ADMIN
    )
    return get_success_data(resp)


def close_audit(case_id, headers=None):
    resp = api_client.close_audit_case(case_id, headers or DIRECTOR)
    return get_success_data(resp)


def make_rated_carrier(rating, **carrier_overrides):
    """Drive a fresh carrier to a compliance-review rating via an audit close.

    rating CONDITIONAL -> findings (0 acute, 2 critical)
    rating UNSATISFACTORY -> findings (2 acute, 0 critical)
    rating SATISFACTORY -> findings (0 acute, 1 critical)
    """
    findings = {
        "SATISFACTORY": (0, 1),
        "CONDITIONAL": (0, 2),
        "UNSATISFACTORY": (2, 0),
    }
    acute, critical = findings[rating]
    carrier = make_carrier(**carrier_overrides)
    case = audit_to_findings(carrier["id"], acute, critical)
    close_audit(case["id"])
    return get_carrier(carrier["id"])


# ---------------------------------------------------------------------------
# Tier 4: premium model shortcuts
# ---------------------------------------------------------------------------

def make_quoted_model(carrier_id, **overrides):
    model = make_premium_model(carrier_id, **overrides)
    get_success_data(api_client.quote_premium_model(model["id"], INSURANCE))
    return get_premium_model(model["id"])


# ---------------------------------------------------------------------------
# Tier 5: full difficulty-design composites
# ---------------------------------------------------------------------------

def setup_measure_dual_variant_case():
    """Carrier fleet 10; VEHICLE_MAINTENANCE (threshold 65, benchmark 12.0);
    two violations occurred 2026-05-01 (sev 8 -> 24 pts, sev 4 -> 12 pts at
    time-weight 3); the sev-8 violation is CHALLENGED by a SUBMITTED challenge.
    Returns dict of ids; caller runs the measurement cycle."""
    carrier = make_carrier(fleet_size=10)
    category = make_category(
        category_code="VEHICLE_MAINTENANCE",
        display_name="Vehicle Maintenance",
        intervention_threshold=65,
        benchmark_measure=12.0,
    )
    driver = make_driver(carrier["id"])
    inspection = make_inspection(carrier["id"], driver["id"])
    v1 = make_violation(
        inspection["id"], category["id"], violation_code="396.3", severity_weight=8
    )
    v2 = make_violation(
        inspection["id"], category["id"], violation_code="396.5", severity_weight=4
    )
    challenge = make_challenge(
        v1["id"], reason_code="INCORRECT_DATA", evidence_note="Wrong trailer number on report"
    )
    return {
        "carrier": carrier,
        "category": category,
        "driver": driver,
        "inspection": inspection,
        "v1": v1,
        "v2": v2,
        "challenge": challenge,
    }


def setup_premium_dual_variant_case():
    """Carrier fleet 3, rating NONE; HOS category (threshold 65, benchmark
    10.0); driver HIGH (sev-8 violation, 24 pts); one preventable reportable
    accident; cycle run so HOS is alerted. Returns dict of ids."""
    carrier = make_carrier(fleet_size=3)
    category = make_category(
        category_code="HOURS_OF_SERVICE",
        display_name="HOS Compliance",
        intervention_threshold=65,
        benchmark_measure=10.0,
    )
    driver = make_driver(carrier["id"], hire_date="2025-02-01T00:00:00Z")
    inspection = make_inspection(
        carrier["id"], driver["id"], inspection_date="2026-06-01T00:00:00Z"
    )
    violation = make_violation(
        inspection["id"],
        category["id"],
        violation_code="395.8",
        severity_weight=8,
        occurred_at="2026-06-01T00:00:00Z",
    )
    accident = make_accident(
        carrier["id"],
        driver["id"],
        occurred_at="2026-06-15T00:00:00Z",
        fatalities=0,
        injuries=1,
        tow_away=True,
    )
    determine_preventability(accident["id"], "PREVENTABLE")
    run_cycle(carrier["id"])
    return {
        "carrier": get_carrier(carrier["id"]),
        "category": category,
        "driver": driver,
        "violation": violation,
        "accident": accident,
    }


def setup_premium_rounding_case():
    """Carrier fleet 1, rating NONE; HOS alerted; one preventable accident;
    one HIGH driver. Returns ids; caller creates the premium model."""
    carrier = make_carrier(fleet_size=1)
    category = make_category(
        category_code="HOURS_OF_SERVICE",
        display_name="HOS",
        intervention_threshold=65,
        benchmark_measure=10.0,
    )
    driver = make_driver(carrier["id"], hire_date="2025-04-01T00:00:00Z")
    inspection = make_inspection(carrier["id"], driver["id"])
    make_violation(
        inspection["id"], category["id"], violation_code="395.8", severity_weight=8
    )
    accident = make_accident(
        carrier["id"],
        driver["id"],
        occurred_at="2026-06-15T00:00:00Z",
        fatalities=0,
        injuries=1,
        tow_away=False,
    )
    determine_preventability(accident["id"], "PREVENTABLE")
    run_cycle(carrier["id"])
    return {"carrier": get_carrier(carrier["id"]), "driver": driver}


def setup_posture_first_match_case():
    """Carrier fleet 4; HOS + VM both alerted by the cycle (posture
    INTERVENTION_PRIORITY); then a COMPLIANCE_REVIEW audit reaches
    FINDINGS_ISSUED with acute_count 2 (proposed UNSATISFACTORY).
    Returns ids including the cycle summary and audit case."""
    carrier = make_carrier(fleet_size=4)
    cat_h = make_category(
        category_code="HOURS_OF_SERVICE", display_name="HOS",
        intervention_threshold=65, benchmark_measure=8.0,
    )
    cat_v = make_category(
        category_code="VEHICLE_MAINTENANCE", display_name="VM",
        intervention_threshold=65, benchmark_measure=8.0,
    )
    driver = make_driver(carrier["id"], hire_date="2025-03-01T00:00:00Z")
    make_document(
        carrier["id"], driver_id=driver["id"], document_type="DQ_FILE",
        filed_at="2026-01-01T00:00:00Z",
    )
    inspection = make_inspection(
        carrier["id"], driver["id"], inspection_level=2, state_code="OH"
    )
    make_violation(inspection["id"], cat_h["id"], violation_code="395.3", severity_weight=8)
    make_violation(inspection["id"], cat_v["id"], violation_code="396.3", severity_weight=8)
    cycle = run_cycle(carrier["id"])
    case = audit_to_findings(carrier["id"], 2, 0, field_work_duration_days=14)
    return {
        "carrier": carrier,
        "driver": driver,
        "cycle": cycle,
        "case": case,
    }


def setup_remand_loop_case():
    """One ACTIVE violation (sev 5) with a challenge that has been remanded
    twice and is back UNDER_REVIEW (remand_count == 2)."""
    carrier, category, driver, inspection, violation = make_inspection_with_violation(
        severity_weight=5, violation_overrides={"violation_code": "396.9"}
    )
    challenge = make_challenge(
        violation["id"], reason_code="WRONG_DRIVER", evidence_note="Driver was on leave"
    )
    for note in ("Added leave records", "Added payroll proof"):
        get_success_data(api_client.start_review_challenge(challenge["id"], ADMIN))
        get_success_data(api_client.decide_challenge(challenge["id"], {"outcome": "REMANDED"}, ADMIN))
        get_success_data(api_client.resubmit_challenge(challenge["id"], {"evidence_note": note}, ANALYST))
    get_success_data(api_client.start_review_challenge(challenge["id"], ADMIN))
    return {
        "carrier": carrier,
        "driver": driver,
        "inspection": inspection,
        "violation": violation,
        "challenge": get_challenge(challenge["id"]),
    }


def setup_stale_requote_loop_case():
    """Carrier fleet 2 rated CONDITIONAL via audit (0 acute, 2 critical); a
    QUOTED BASELINE model (rate 100000, period 2027); clock advanced past the
    cooling-off; upgrade request UNDER_REVIEW requesting SATISFACTORY."""
    carrier = make_carrier(fleet_size=2)
    driver = make_driver(carrier["id"], hire_date="2025-06-01T00:00:00Z")
    make_document(
        carrier["id"], driver_id=driver["id"], document_type="DQ_FILE",
        filed_at="2026-01-01T00:00:00Z",
    )
    case = audit_to_findings(carrier["id"], 0, 2, field_work_duration_days=14)
    close_audit(case["id"])
    model = make_quoted_model(carrier["id"], base_rate_cents_per_unit=100000)
    set_clock("2027-02-01T00:00:00Z")
    request = make_upgrade_request(
        carrier["id"], requested_rating="SATISFACTORY",
        justification_note="Corrective plan complete",
    )
    get_success_data(api_client.start_review_upgrade(request["id"], DIRECTOR))
    return {
        "carrier": get_carrier(carrier["id"]),
        "model": model,
        "request": get_success_data(api_client.get_upgrade_request(request["id"], DIRECTOR)),
    }


def setup_overturn_cascade_case():
    """Carrier fleet 2; HOS category (benchmark 100.0 so no alert); driver
    HIGH (sev-8 + sev-6 violations, 24+18=42 pts); QUOTED BASELINE model at
    107100 cents; challenge on the sev-8 violation UNDER_REVIEW."""
    carrier = make_carrier(fleet_size=2)
    category = make_category(
        category_code="HOURS_OF_SERVICE", display_name="HOS",
        intervention_threshold=65, benchmark_measure=100.0,
    )
    driver = make_driver(carrier["id"], hire_date="2025-07-01T00:00:00Z")
    inspection = make_inspection(carrier["id"], driver["id"], state_code="CO")
    v1 = make_violation(
        inspection["id"], category["id"], violation_code="395.8", severity_weight=8
    )
    v2 = make_violation(
        inspection["id"], category["id"], violation_code="395.3", severity_weight=6
    )
    model = make_quoted_model(carrier["id"], base_rate_cents_per_unit=50000)
    challenge = make_challenge(
        v1["id"], reason_code="INCORRECT_DATA", evidence_note="ELD extract attached"
    )
    get_success_data(api_client.start_review_challenge(challenge["id"], ADMIN))
    return {
        "carrier": carrier,
        "category": category,
        "driver": driver,
        "inspection": inspection,
        "v1": v1,
        "v2": v2,
        "model": model,
        "challenge": get_challenge(challenge["id"]),
    }


def setup_audit_close_cascade_case():
    """Carrier fleet 2 rating NONE; driver with DQ_FILE; QUOTED BASELINE model
    at 210000 cents; COMPLIANCE_REVIEW audit in FINDINGS_ISSUED with
    acute_count 2 (proposed UNSATISFACTORY)."""
    carrier = make_carrier(fleet_size=2)
    driver = make_driver(carrier["id"], hire_date="2025-08-01T00:00:00Z")
    make_document(
        carrier["id"], driver_id=driver["id"], document_type="DQ_FILE",
        filed_at="2026-01-01T00:00:00Z",
    )
    model = make_quoted_model(carrier["id"], base_rate_cents_per_unit=100000)
    case = audit_to_findings(carrier["id"], 2, 0, field_work_duration_days=14)
    return {
        "carrier": carrier,
        "driver": driver,
        "model": model,
        "case": case,
    }


def setup_post_accident_case():
    """Carrier + driver + reportable accident occurred 2026-07-01. Returns
    (carrier, driver, accident)."""
    carrier, driver = make_carrier_with_driver()
    accident = make_accident(
        carrier["id"], driver["id"], occurred_at="2026-07-01T00:00:00Z",
        fatalities=0, injuries=1, tow_away=False,
    )
    return carrier, driver, accident


def setup_upgrade_conflict_case():
    """Carrier CONDITIONAL (audit A1: acute 1); clock 2027-02-01; upgrade
    request R1 SUBMITTED; audit A2 closed UNSATISFACTORY (critical 4) while R1
    remains open — re-arming the cooling-off gate behind the open request."""
    carrier = make_carrier(fleet_size=1)
    driver = make_driver(carrier["id"], hire_date="2025-10-01T00:00:00Z")
    make_document(
        carrier["id"], driver_id=driver["id"], document_type="DQ_FILE",
        filed_at="2026-01-01T00:00:00Z",
    )
    case1 = audit_to_findings(carrier["id"], 1, 0, field_work_duration_days=14)
    close_audit(case1["id"])
    set_clock("2027-02-01T00:00:00Z")
    request = make_upgrade_request(
        carrier["id"], requested_rating="SATISFACTORY", justification_note="CAP evidence"
    )
    case2 = audit_to_findings(
        carrier["id"], 0, 4,
        scheduled_date="2027-02-01T00:00:00Z", field_work_duration_days=14,
    )
    close_audit(case2["id"])
    return {
        "carrier": get_carrier(carrier["id"]),
        "driver": driver,
        "request": request,
    }


def setup_time_weight_six_month_case():
    """Carrier fleet 5; UNSAFE_DRIVING category; violation A occurred exactly
    six calendar months before the default clock (2026-02-01), violation B one
    day older (2026-01-31); both severity 5."""
    carrier = make_carrier(fleet_size=5)
    category = make_category(
        category_code="UNSAFE_DRIVING", display_name="Unsafe Driving",
        intervention_threshold=65, benchmark_measure=10.0,
    )
    driver = make_driver(carrier["id"], hire_date="2025-01-15T00:00:00Z")
    inspection = make_inspection(
        carrier["id"], driver["id"],
        inspection_date="2026-01-31T00:00:00Z", inspection_level=2, state_code="WA",
    )
    va = make_violation(
        inspection["id"], category["id"], violation_code="392.2",
        severity_weight=5, occurred_at="2026-02-01T00:00:00Z",
    )
    vb = make_violation(
        inspection["id"], category["id"], violation_code="392.4",
        severity_weight=5, occurred_at="2026-01-31T00:00:00Z",
    )
    return {
        "carrier": carrier, "category": category, "driver": driver,
        "inspection": inspection, "va": va, "vb": vb,
    }


def setup_finalize_blocked_case():
    """Inspection UNDER_REVIEW with one violation (sev 3) carrying an open
    (SUBMITTED) challenge."""
    carrier, category, driver, inspection, violation = make_inspection_with_violation(
        severity_weight=3, violation_overrides={"violation_code": "396.1"},
        carrier_overrides={"fleet_size": 5},
        inspection_overrides={"inspection_level": 3, "state_code": "GA"},
    )
    get_success_data(api_client.begin_review_inspection(inspection["id"], ANALYST))
    challenge = make_challenge(
        violation["id"], reason_code="OTHER", evidence_note="Vendor invoice attached"
    )
    return {
        "carrier": carrier, "driver": driver, "inspection": inspection,
        "violation": violation, "challenge": challenge,
    }


def setup_suspended_by_positive_test():
    """Driver SUSPENDED via a VERIFIED_POSITIVE RANDOM drug test (collected
    2026-07-01, verified at the 2026-08-01 default clock)."""
    carrier, driver = make_carrier_with_driver()
    test = make_verified_test(
        driver["id"], "POSITIVE", "VERIFIED_POSITIVE",
        test_type="RANDOM", substance="DRUG", collected_at="2026-07-01T00:00:00Z",
    )
    return {
        "carrier": carrier,
        "driver": get_driver(driver["id"]),
        "test": test,
    }


def setup_uphold_conservation_case():
    """Carrier fleet 5; VM category; one violation (sev 5 -> 15 pts); cycle 1
    already run at the default clock (official and provisional measure 3.00)."""
    carrier, category, driver, inspection, violation = make_inspection_with_violation(
        severity_weight=5,
        carrier_overrides={"fleet_size": 5},
        inspection_overrides={"inspection_level": 2, "state_code": "NM"},
    )
    cycle1 = run_cycle(carrier["id"])
    snap1 = list_snapshots(carrier_id=carrier["id"], category_id=category["id"])[0]
    return {
        "carrier": carrier, "category": category, "driver": driver,
        "inspection": inspection, "violation": violation,
        "cycle1": cycle1, "snap1": snap1,
    }


def setup_premium_recompute_conservation_case():
    """Carrier fleet 2 rating NONE, no violations/accidents; QUOTED BASELINE
    model (rate 100000, period 2027) at 210000 cents."""
    carrier = make_carrier(fleet_size=2)
    model = make_quoted_model(carrier["id"], base_rate_cents_per_unit=100000)
    return {"carrier": carrier, "model": model}


def setup_overdue_coaching_case(coaching_type="TRAINING_COURSE", due_date="2026-08-10T00:00:00Z"):
    """Carrier + driver + open coaching due `due_date`; clock advanced to
    2026-08-11; cycle run so the assignment is OVERDUE."""
    carrier, driver = make_carrier_with_driver()
    coaching = make_coaching(driver["id"], coaching_type=coaching_type, due_date=due_date)
    set_clock("2026-08-11T00:00:00Z")
    cycle = run_cycle(carrier["id"])
    return {
        "carrier": carrier,
        "driver": driver,
        "coaching": coaching,
        "cycle": cycle,
    }


def setup_loading_caps_case():
    """Carrier fleet 1 rating NONE; all seven categories alerting (threshold 1,
    benchmark 1.0); six HIGH drivers; six preventable reportable accidents;
    cycle run. Caller creates the premium model."""
    carrier = make_carrier(fleet_size=1)
    categories = {}
    for code in (
        "UNSAFE_DRIVING", "HOURS_OF_SERVICE", "DRIVER_FITNESS",
        "CONTROLLED_SUBSTANCES_ALCOHOL", "VEHICLE_MAINTENANCE", "HAZMAT",
        "CRASH_INDICATOR",
    ):
        categories[code] = make_category(
            category_code=code, display_name=code.replace("_", " ").title(),
            intervention_threshold=1, benchmark_measure=1.0,
        )
    drivers = [make_driver(carrier["id"], hire_date="2024-01-01T00:00:00Z") for _ in range(6)]
    inspection = make_inspection(carrier["id"], drivers[0]["id"], state_code="SD")
    # Driver 1: one sev-1 violation per category -> 7 x 3 = 21 pts (HIGH).
    for code, category in categories.items():
        make_violation(
            inspection["id"], category["id"],
            violation_code=f"V-{code[:3]}", severity_weight=1,
        )
    # Drivers 2..6: one sev-8 violation each -> 24 pts (HIGH).
    for index, driver in enumerate(drivers[1:], start=2):
        make_violation(
            inspection["id"], categories["UNSAFE_DRIVING"]["id"],
            violation_code=f"V-D{index}", severity_weight=8, driver_id=driver["id"],
        )
    # Six preventable reportable accidents in the 36-month window.
    for day in range(1, 7):
        accident = make_accident(
            carrier["id"], drivers[0]["id"],
            occurred_at=f"2026-06-0{day}T00:00:00Z",
            fatalities=0, injuries=1, tow_away=False,
        )
        determine_preventability(accident["id"], "PREVENTABLE")
    run_cycle(carrier["id"])
    return {"carrier": get_carrier(carrier["id"]), "drivers": drivers}
