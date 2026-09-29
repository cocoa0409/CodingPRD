"""Composite setup helpers for multi-step prerequisites.

Every helper uses `get_success_data()` so a broken setup step reports itself as a
setup failure rather than as a confusing assertion failure inside a test.

Layout mirrors the shape of the domain: the clock is set first, then a certificate
and a covered site, then operators / instruments / storage, then the reagent-lot
verification chain, and finally the cascade and ledger states that most claims need.
"""

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import CLOCK_STARTUP, TEST_DEFAULTS
from .factories import (
    assessment_decision_payload,
    assessment_payload,
    certificate_payload,
    correction_decision_payload,
    correction_submission_payload,
    coverage_payload,
    deficiency_payload,
    device_payload,
    director_payload,
    inspection_payload,
    issue_payload,
    lot_verify_payload,
    moderate_certificate_payload,
    operator_payload,
    patient_result_payload,
    post_payload,
    pt_enrollment_payload,
    pt_event_payload,
    pt_score_payload,
    qc_run_payload,
    reagent_lot_payload,
    site_payload,
    storage_unit_payload,
    temperature_reading_payload,
    training_payload,
)
from .test_users import (
    TEST_USERS,
    make_lab_director_headers,
    make_operator_headers,
    make_surveyor_headers,
)

ADMIN = TEST_USERS["program_admin_headers"]
COORDINATOR = TEST_USERS["quality_coordinator_headers"]
SURVEYOR = TEST_USERS["surveyor_headers"]
SURVEYOR_BETA = TEST_USERS["surveyor_beta_headers"]


# ─── Tier 1: State Progression ─────────────────────────────────────


def set_clock(to_iso8601=CLOCK_STARTUP):
    """Pin the logical clock (PRD 2.4). Returns the resulting clock payload."""
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


def create_certificate(**overrides):
    """Register an ACTIVE certificate of waiver."""
    return get_success_data(
        api_client.create_certificate(certificate_payload(**overrides), ADMIN)
    )


def create_moderate_certificate(**overrides):
    """Register an ACTIVE certificate of compliance permitting MODERATE."""
    return get_success_data(
        api_client.create_certificate(moderate_certificate_payload(**overrides), ADMIN)
    )


def create_site(**overrides):
    """Create a testing site; it is born OPEN with no coverage."""
    return get_success_data(api_client.create_site(site_payload(**overrides), ADMIN))


def create_coverage(site_id, certificate_id, **overrides):
    """Attach a certificate to a site over a closed date window."""
    return get_success_data(
        api_client.create_coverage(
            coverage_payload(site_id, certificate_id, **overrides), ADMIN
        )
    )


def create_operator(site_id, **overrides):
    """Add an operator; starts PENDING competency and LOCKED_OUT access."""
    return get_success_data(
        api_client.create_operator(operator_payload(site_id, **overrides), ADMIN)
    )


def create_trained_operator(site_id, **overrides):
    """Add an operator and record training, reaching PROVISIONAL + ACTIVE."""
    training = overrides.pop("training", {})
    operator = create_operator(site_id, **overrides)
    return get_success_data(
        api_client.record_training(
            operator["id"], training_payload(**training), ADMIN
        )
    )


def create_device(site_id, **overrides):
    """Install an instrument at a covered site."""
    return get_success_data(
        api_client.create_device(device_payload(site_id, **overrides), ADMIN)
    )


def create_storage_unit(site_id, **overrides):
    """Register a storage unit with its acceptable temperature band."""
    return get_success_data(
        api_client.create_storage_unit(storage_unit_payload(site_id, **overrides), ADMIN)
    )


def create_reagent_lot(site_id, storage_unit_id, **overrides):
    """Receive a reagent lot; it starts UNVERIFIED."""
    return get_success_data(
        api_client.create_reagent_lot(
            reagent_lot_payload(site_id, storage_unit_id, **overrides), COORDINATOR
        )
    )


def record_qc_run(device_id, lot_id, operator_id, control_level, measured_value, **kw):
    """Record a control run as the named operator (PRD 2.1 identity semantics)."""
    return get_success_data(
        api_client.create_qc_run(
            qc_run_payload(
                device_id, lot_id, operator_id, control_level, measured_value, **kw
            ),
            make_operator_headers(operator_id),
        )
    )


def verify_lot(lot_id, device_id, operator_id, level_1_value=100.0,
               level_2_value=300.0):
    """Two passing runs on one instrument move the lot UNVERIFIED -> VERIFIED."""
    run_1 = record_qc_run(device_id, lot_id, operator_id, "LEVEL_1", level_1_value)
    run_2 = record_qc_run(device_id, lot_id, operator_id, "LEVEL_2", level_2_value)
    lot = get_success_data(
        api_client.verify_reagent_lot(
            lot_id, lot_verify_payload(run_1["id"], run_2["id"]), COORDINATOR
        )
    )
    return lot, run_1, run_2


# ─── Tier 2: Entity Hierarchy ──────────────────────────────────────


def setup_covered_site(certificate_overrides=None, site_overrides=None,
                       coverage_overrides=None, clock=CLOCK_STARTUP):
    """Clock -> certificate -> site -> coverage. Returns (certificate, site, coverage)."""
    if clock:
        set_clock(clock)
    certificate = create_certificate(**(certificate_overrides or {}))
    site = create_site(**(site_overrides or {}))
    coverage = create_coverage(
        site["id"], certificate["id"], **(coverage_overrides or {})
    )
    return certificate, site, coverage


def setup_site_with_operator(**kwargs):
    """Covered site plus one trained operator. Returns a dict environment."""
    operator_overrides = kwargs.pop("operator_overrides", {})
    certificate, site, coverage = setup_covered_site(**kwargs)
    operator = create_trained_operator(site["id"], **operator_overrides)
    return {
        "certificate": certificate,
        "site": site,
        "coverage": coverage,
        "operator": operator,
    }


def setup_site_with_device(**kwargs):
    """Covered site + trained operator + one instrument + one storage unit."""
    device_overrides = kwargs.pop("device_overrides", {})
    storage_overrides = kwargs.pop("storage_overrides", {})
    env = setup_site_with_operator(**kwargs)
    env["device"] = create_device(env["site"]["id"], **device_overrides)
    env["storage_unit"] = create_storage_unit(env["site"]["id"], **storage_overrides)
    return env


def setup_site_with_unverified_lot(**kwargs):
    """As `setup_site_with_device`, plus one received (UNVERIFIED) reagent lot."""
    lot_overrides = kwargs.pop("lot_overrides", {})
    env = setup_site_with_device(**kwargs)
    env["lot"] = create_reagent_lot(
        env["site"]["id"], env["storage_unit"]["id"], **lot_overrides
    )
    return env


def setup_site_with_verified_lot(**kwargs):
    """Full testing-ready environment: covered site, trained operator, instrument,
    storage unit and a VERIFIED lot backed by a LEVEL_1 and LEVEL_2 pass."""
    env = setup_site_with_unverified_lot(**kwargs)
    lot, run_1, run_2 = verify_lot(
        env["lot"]["id"], env["device"]["id"], env["operator"]["id"]
    )
    env["lot"] = lot
    env["qc_run_level_1"] = run_1
    env["qc_run_level_2"] = run_2
    return env


# ─── Tier 3: Full Lifecycle Shortcuts ──────────────────────────────


def capture_result(env, **overrides):
    """Capture one patient result as the environment's operator."""
    operator_id = overrides.pop("operator_id", env["operator"]["id"])
    return get_success_data(
        api_client.create_test_result(
            patient_result_payload(
                env["device"]["id"], operator_id, env["lot"]["id"], **overrides
            ),
            make_operator_headers(operator_id),
        )
    )


def capture_results(env, count, **overrides):
    """Capture `count` PENDING_REVIEW results on the environment's instrument."""
    return [capture_result(env, **overrides) for _ in range(count)]


def post_result(result_id, actor_headers, **overrides):
    """Post a captured result to the medical record."""
    return get_success_data(
        api_client.post_test_result(result_id, post_payload(**overrides), actor_headers)
    )


def capture_and_post_result(env, **overrides):
    """Capture then post one INTERFACED result as the environment's operator."""
    result = capture_result(env, **overrides)
    return post_result(
        result["id"], make_operator_headers(env["operator"]["id"])
    )


def assign_director(site_id, operator_id):
    """Name the site's CLIA laboratory director of record."""
    return get_success_data(
        api_client.assign_director(site_id, director_payload(operator_id), ADMIN)
    )


def setup_site_with_director(**kwargs):
    """Covered site whose director of record is a trained PHYSICIAN operator.

    Returns the environment dict with `director` added, plus a `director_headers`
    key carrying that director's `LabDirector` headers (PRD 2.1 / 2.8).
    """
    director_overrides = kwargs.pop("director_overrides", {})
    certificate, site, coverage = setup_covered_site(**kwargs)
    director = create_trained_operator(
        site["id"],
        full_name=director_overrides.get("full_name", "Dr Iris Vale"),
        role_title=director_overrides.get("role_title", "PHYSICIAN"),
        hire_date=director_overrides.get("hire_date", "2026-01-15"),
    )
    site = assign_director(site["id"], director["id"])
    return {
        "certificate": certificate,
        "site": site,
        "coverage": coverage,
        "director": director,
        "director_headers": make_lab_director_headers(director["id"]),
    }


def submit_assessment(operator_id, assessor_operator_id, **overrides):
    """Submit a competency assessment, refreshing the operator version first.

    PRD 2.9 requires `expected_operator_version` to equal the subject operator's
    current `version`, and both submissions and approvals bump that version.
    """
    if "expected_operator_version" in overrides:
        version = overrides.pop("expected_operator_version")
    else:
        operator = get_success_data(api_client.get_operator(operator_id, ADMIN))
        version = operator["version"]
    return get_success_data(
        api_client.create_assessment(
            assessment_payload(
                operator_id, assessor_operator_id, version, **overrides
            ),
            COORDINATOR,
        )
    )


def decide_assessment(assessment_id, decision, actor_headers, **overrides):
    """Approve or reject a submitted competency assessment."""
    return get_success_data(
        api_client.decide_assessment(
            assessment_id, assessment_decision_payload(decision, **overrides),
            actor_headers,
        )
    )


def setup_competent_operator(**kwargs):
    """Site with a director, an assessor and a subject operator whose competency
    has been approved, so the subject reads COMPETENT.

    Returns the environment dict with `assessor`, `subject` and `assessment`.
    """
    assessment_overrides = kwargs.pop("assessment_overrides", {})
    env = setup_site_with_director(**kwargs)
    env["assessor"] = create_trained_operator(
        env["site"]["id"], full_name="Ben Osei", role_title="MEDICAL_TECHNOLOGIST"
    )
    env["subject"] = create_trained_operator(
        env["site"]["id"], full_name="Alma Ruiz", role_title="MEDICAL_ASSISTANT",
        hire_date="2026-03-01",
    )
    assessment = submit_assessment(
        env["subject"]["id"], env["assessor"]["id"], **assessment_overrides
    )
    env["assessment"] = decide_assessment(
        assessment["id"], "APPROVE", env["director_headers"]
    )
    return env


# ─── Tier 4: Accumulation / Threshold Targeting ────────────────────


SEVERITY_FOR_WEIGHT = {
    8.00: "CONDITION_LEVEL",
    3.00: "STANDARD_LEVEL",
    1.00: "ADVISORY",
}

_FINDING_CATEGORIES = [
    "PERSONNEL_COMPETENCY",
    "QUALITY_CONTROL",
    "RESULT_REPORTING",
    "REAGENT_STORAGE",
    "PROFICIENCY_TESTING",
    "CERTIFICATE_SCOPE",
]


def open_survey(site_id, surveyor_headers=None, **overrides):
    """Open a survey against a site; it is created directly IN_PROGRESS."""
    return get_success_data(
        api_client.create_inspection(
            inspection_payload(site_id, **overrides), surveyor_headers or SURVEYOR
        )
    )


def add_finding(inspection_id, surveyor_headers=None, **overrides):
    """Add a DRAFT deficiency finding to an in-progress survey."""
    return get_success_data(
        api_client.create_deficiency(
            deficiency_payload(inspection_id, **overrides),
            surveyor_headers or SURVEYOR,
        )
    )


def issue_survey(inspection_id, surveyor_headers=None, **overrides):
    """Issue the deficiency statement, pinning every draft finding's weight."""
    return get_success_data(
        api_client.issue_inspection(
            inspection_id, issue_payload(**overrides), surveyor_headers or SURVEYOR
        )
    )


def setup_issued_findings(site_id, severities, surveyor_headers=None,
                          categories=None, inspection_overrides=None,
                          finding_overrides=None):
    """Open a survey, add one finding per severity, and issue the statement.

    `severities` is a list drawn from CONDITION_LEVEL (8.00), STANDARD_LEVEL (3.00)
    and ADVISORY (1.00), so a caller can target an exact `open_deficiency_weight`.
    Returns (inspection, findings).
    """
    headers = surveyor_headers or SURVEYOR
    categories = categories or _FINDING_CATEGORIES
    inspection = open_survey(
        site_id, headers, **(inspection_overrides or {})
    )
    findings = []
    for index, severity in enumerate(severities):
        findings.append(
            add_finding(
                inspection["id"], headers,
                category=categories[index % len(categories)],
                severity=severity,
                description=f"Finding {index + 1} raised on survey",
                **(finding_overrides or {}),
            )
        )
    inspection = issue_survey(inspection["id"], headers)
    return inspection, findings


def setup_site_with_open_weight(target_weight, **kwargs):
    """Covered site carrying exactly `target_weight` of open deficiency weight.

    Supported targets are built from the severity bases of PRD 3.8:
    3.00, 6.00, 8.00, 11.00, 14.00 and 16.00.
    """
    surveyor_headers = kwargs.pop("surveyor_headers", None)
    combinations = {
        1.00: ["ADVISORY"],
        3.00: ["STANDARD_LEVEL"],
        6.00: ["STANDARD_LEVEL", "STANDARD_LEVEL"],
        8.00: ["CONDITION_LEVEL"],
        11.00: ["CONDITION_LEVEL", "STANDARD_LEVEL"],
        14.00: ["CONDITION_LEVEL", "STANDARD_LEVEL", "STANDARD_LEVEL"],
        16.00: ["CONDITION_LEVEL", "CONDITION_LEVEL"],
    }
    assert target_weight in combinations, (
        f"no severity combination is registered for weight {target_weight}"
    )
    certificate, site, coverage = setup_covered_site(**kwargs)
    inspection, findings = setup_issued_findings(
        site["id"], combinations[target_weight], surveyor_headers
    )
    return {
        "certificate": certificate,
        "site": site,
        "coverage": coverage,
        "inspection": inspection,
        "findings": findings,
    }


def setup_closed_finding(site_id, category, surveyor_headers=None,
                         severity="STANDARD_LEVEL"):
    """Drive one finding all the way to CLOSED so a later same-category finding
    earns the 2.0 repeat multiplier (PRD 3.8).

    Returns (inspection, finding) with the finding read back in CLOSED.
    """
    issuing = surveyor_headers or SURVEYOR
    inspection, findings = setup_issued_findings(
        site_id, [severity], issuing, categories=[category]
    )
    finding = findings[0]
    get_success_data(
        api_client.submit_correction(
            finding["id"], correction_submission_payload(), COORDINATOR
        )
    )
    closed = get_success_data(
        api_client.decide_correction(
            finding["id"], correction_decision_payload("ACCEPT"), SURVEYOR_BETA
        )
    )
    return inspection, closed


def setup_qc_failure_cascade(held_count=3, **kwargs):
    """Drive the quality-control failure cascade of PRD 3.4.

    Captures `held_count` PENDING_REVIEW results, then records a failing LEVEL_1
    control run so the instrument locks with QC_FAILURE and those results move to
    HELD. Returns the environment dict with `results` and `failing_run`.
    """
    env = setup_site_with_verified_lot(**kwargs)
    env["results"] = capture_results(env, held_count)
    env["failing_run"] = record_qc_run(
        env["device"]["id"], env["lot"]["id"], env["operator"]["id"],
        "LEVEL_1", 140.0,
    )
    return env


def confirming_pass_run(env, measured_value=100.0):
    """Record the passing LEVEL_1 run that a qc-unlock will cite as evidence."""
    return record_qc_run(
        env["device"]["id"], env["lot"]["id"], env["operator"]["id"],
        "LEVEL_1", measured_value,
    )


def record_temperature_reading(storage_unit_id, reading_c, actor_headers=None,
                               **overrides):
    """Record one probe reading against a storage unit."""
    return get_success_data(
        api_client.create_temperature_reading(
            storage_unit_id, temperature_reading_payload(reading_c, **overrides),
            actor_headers or COORDINATOR,
        )
    )


def setup_temperature_excursion(result_count=2, **kwargs):
    """Drive the temperature excursion cascade of PRD 3.5.

    A VERIFIED lot with `result_count` PENDING_REVIEW results against it, then a
    12.5 C reading that quarantines the lot, locks the instrument with
    LOT_QUARANTINE and rejects those results.
    """
    env = setup_site_with_verified_lot(**kwargs)
    env["results"] = capture_results(env, result_count)
    env["excursion_reading"] = record_temperature_reading(
        env["storage_unit"]["id"], 12.5
    )
    return env


def enroll_pt(site_id, **overrides):
    """Enrol a site in a proficiency-testing programme for one analyte and year."""
    return get_success_data(
        api_client.create_pt_enrollment(
            pt_enrollment_payload(site_id, **overrides), COORDINATOR
        )
    )


def register_pt_event(enrollment_id, shipment_number, **overrides):
    """Register one shipment under an enrolment."""
    return get_success_data(
        api_client.create_pt_event(
            pt_event_payload(enrollment_id, shipment_number, **overrides), COORDINATOR
        )
    )


def score_pt_event(event_id, score_pct, **overrides):
    """Record the graded score for a shipment."""
    return get_success_data(
        api_client.score_pt_event(
            event_id, pt_score_payload(score_pct, **overrides), COORDINATOR
        )
    )


def setup_pt_graded_events(site_id, scores, enrollment_overrides=None,
                           due_dates=None):
    """Enrol a site and grade one shipment per entry in `scores`.

    Shipment numbers are the ordinals 1..3 of PRD 3.7. Returns
    (enrollment, [events]) with each event read back after grading.
    """
    enrollment = enroll_pt(site_id, **(enrollment_overrides or {}))
    default_dates = ["2026-08-10", "2026-08-20", "2026-08-30"]
    dates = due_dates or default_dates
    events = []
    for index, score in enumerate(scores):
        event = register_pt_event(
            enrollment["id"], index + 1, due_date=dates[index % len(dates)]
        )
        events.append(score_pt_event(event["id"], score))
    return enrollment, events


# ─── Tier 5: Finalization / Terminal State ─────────────────────────


def retire_device(device_id, **overrides):
    """Retire an instrument so it leaves the compliance-index denominator."""
    from .factories import retire_payload

    return get_success_data(
        api_client.retire_device(device_id, retire_payload(**overrides), ADMIN)
    )


def rescind_survey(inspection_id, surveyor_headers=None, **overrides):
    """Rescind a survey; every non-terminal finding is voided."""
    from .factories import rescind_payload

    return get_success_data(
        api_client.rescind_inspection(
            inspection_id, rescind_payload(**overrides), surveyor_headers or SURVEYOR
        )
    )


def suspend_certificate(certificate_id, **overrides):
    """Suspend an ACTIVE certificate, driving the withdrawal cascade."""
    payload = {"reason": "Certificate withdrawn pending state review"}
    payload.update(overrides)
    return get_success_data(
        api_client.suspend_certificate(certificate_id, payload, ADMIN)
    )


def run_oversight(**overrides):
    """Invoke the oversight run: the only time-driven sweep in the system."""
    from .factories import oversight_run_payload

    return get_success_data(
        api_client.create_oversight_run(oversight_run_payload(**overrides), ADMIN)
    )


def read_site(site_id, headers=None):
    """Read one site, forcing the recompute-on-read of PRD 2.11."""
    return get_success_data(api_client.get_site(site_id, headers or ADMIN))


def read_operator(operator_id, headers=None):
    return get_success_data(api_client.get_operator(operator_id, headers or ADMIN))


def read_device(device_id, headers=None):
    return get_success_data(api_client.get_device(device_id, headers or ADMIN))


def read_lot(lot_id, headers=None):
    return get_success_data(api_client.get_reagent_lot(lot_id, headers or ADMIN))


def read_result(result_id, headers=None):
    return get_success_data(api_client.get_test_result(result_id, headers or ADMIN))


def read_deficiency(finding_id, headers=None):
    return get_success_data(api_client.get_deficiency(finding_id, headers or SURVEYOR))


def read_inspection(inspection_id, headers=None):
    return get_success_data(
        api_client.get_inspection(inspection_id, headers or SURVEYOR)
    )


def read_readiness(site_id, headers=None, basis=None):
    params = {"basis": basis} if basis else None
    return get_success_data(
        api_client.get_site_readiness(site_id, headers or ADMIN, params=params)
    )


def read_storage_unit(unit_id, headers=None):
    return get_success_data(api_client.get_storage_unit(unit_id, headers or COORDINATOR))


def read_certificate(certificate_id, headers=None):
    return get_success_data(
        api_client.get_certificate(certificate_id, headers or ADMIN)
    )


def read_coverage(coverage_id, headers=None):
    return get_success_data(api_client.get_coverage(coverage_id, headers or ADMIN))


def read_pt_enrollment(enrollment_id, headers=None):
    return get_success_data(
        api_client.get_pt_enrollment(enrollment_id, headers or COORDINATOR)
    )


def read_pt_event(event_id, headers=None):
    return get_success_data(api_client.get_pt_event(event_id, headers or COORDINATOR))


def read_assessment(assessment_id, headers=None):
    return get_success_data(
        api_client.get_assessment(assessment_id, headers or COORDINATOR)
    )


__all__ = [name for name in dir() if not name.startswith("_")]
