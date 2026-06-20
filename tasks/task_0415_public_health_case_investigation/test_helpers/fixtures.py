"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (the lenient validator) internally so setup failures
produce clear "Setup failed" errors rather than confusing assertion failures.

Identity threading: every jurisdiction-scoped operation uses the per-instance
builder make_<role>_headers(jurisdiction_id) with the real Jurisdiction.id, so
ownership checks see X-User-ID == the owning jurisdiction's id.

The test harness restarts the API server (empty DB) before every individual
test, so every helper builds its preconditions from scratch.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_program_payload,
    create_jurisdiction_payload,
    create_condition_payload,
    create_case_payload,
    create_lab_result_payload,
    create_contact_payload,
    create_monitoring_period_payload,
    create_transfer_payload,
    create_export_payload,
)
from .test_users import (
    TEST_USERS,
    make_admin_headers,
    make_epi_headers,
    make_intake_headers,
    make_investigator_headers,
    make_tracer_headers,
)

ADMIN = TEST_USERS["admin_headers"]
EPI = TEST_USERS["epi_headers"]


# ─── Tier 0: Program scaffolding ───────────────────────────────────────────
def create_program(name="State PH", **overrides):
    """Create a SurveillanceProgram. Returns the program entity."""
    res = api_client.create_program(create_program_payload(name=name, **overrides), ADMIN)
    return get_success_data(res)


def set_clock(program_id, to_iso8601):
    """Advance the deterministic surveillance clock. Returns the program."""
    res = api_client.set_clock(program_id, {"to_iso8601": to_iso8601}, ADMIN)
    return get_success_data(res)


def create_jurisdiction(program_id, name="County 1", fips_code="06001", **overrides):
    """Create a Jurisdiction under a program. Returns the jurisdiction entity."""
    res = api_client.create_jurisdiction(
        create_jurisdiction_payload(program_id, name=name, fips_code=fips_code, **overrides),
        ADMIN,
    )
    return get_success_data(res)


def create_condition(program_id, **overrides):
    """Create a ReportableCondition. Returns the condition entity."""
    res = api_client.create_condition(create_condition_payload(program_id, **overrides), ADMIN)
    return get_success_data(res)


def setup_program_jurisdiction_condition(condition_overrides=None, fips_code="06001"):
    """Program + one jurisdiction + one COVID19 condition.

    Returns (program, jurisdiction, condition).
    """
    program = create_program()
    jurisdiction = create_jurisdiction(program["id"], fips_code=fips_code)
    condition = create_condition(program["id"], **(condition_overrides or {}))
    return program, jurisdiction, condition


# ─── Tier 1: Case state progression ────────────────────────────────────────
def open_case(program_id, jurisdiction_id, **overrides):
    """Open an OPEN case (acting as CaseInvestigator scoped to jurisdiction_id)."""
    res = api_client.create_case(
        create_case_payload(program_id, jurisdiction_id, **overrides),
        make_investigator_headers(jurisdiction_id),
    )
    return get_success_data(res)


def open_and_interview_case(program_id, jurisdiction_id, case_overrides=None,
                            interview_payload=None):
    """Open a case then interview it -> UNDER_INVESTIGATION. Returns the case after
    interview (computed infectious window present)."""
    case = open_case(program_id, jurisdiction_id, **(case_overrides or {}))
    res = api_client.interview_case(
        case["id"], interview_payload or {}, make_investigator_headers(jurisdiction_id)
    )
    return get_success_data(res)


def setup_interviewed_case(condition_overrides=None, case_overrides=None):
    """Program + jurisdiction + condition + one interviewed (UNDER_INVESTIGATION) case.

    Returns (program, jurisdiction, condition, case).
    """
    program, jurisdiction, condition = setup_program_jurisdiction_condition(
        condition_overrides=condition_overrides
    )
    case = open_and_interview_case(program["id"], jurisdiction["id"], case_overrides=case_overrides)
    return program, jurisdiction, condition, case


def open_interview_classify_case(program_id, jurisdiction_id, classification,
                                 case_overrides=None):
    """Open -> interview -> classify a case. Returns the classified case."""
    case = open_and_interview_case(program_id, jurisdiction_id, case_overrides=case_overrides)
    res = api_client.classify_case(
        case["id"], {"classification": classification},
        make_investigator_headers(jurisdiction_id),
    )
    return get_success_data(res)


# ─── Tier 2: Lab linkage ───────────────────────────────────────────────────
def intake_lab(program_id, jurisdiction_id, **overrides):
    """Submit a lab result via ELR intake (IntakeProcessor). Returns the lab result."""
    res = api_client.create_lab_result(
        create_lab_result_payload(program_id, jurisdiction_id, **overrides),
        make_intake_headers(jurisdiction_id),
    )
    return get_success_data(res)


def link_lab_to_case(case_id, jurisdiction_id, lab_result_id):
    """Manually link a lab result to a case (CaseInvestigator). Returns the lab result."""
    res = api_client.link_lab_result(
        case_id, {"lab_result_id": lab_result_id},
        make_investigator_headers(jurisdiction_id),
    )
    return get_success_data(res)


def setup_confirmed_case_with_lab(condition_overrides=None, case_overrides=None,
                                  patient_reference="PT-1"):
    """Program + jurisdiction + condition (requires_lab_confirmation true) + one
    interviewed case with one POSITIVE lab linked, then classified CONFIRMED.

    Returns (program, jurisdiction, condition, case_after_classify, lab).
    """
    cond_over = dict(condition_overrides or {})
    program, jurisdiction, condition = setup_program_jurisdiction_condition(
        condition_overrides=cond_over
    )
    co = dict(case_overrides or {})
    co.setdefault("patient_reference", patient_reference)
    case = open_and_interview_case(program["id"], jurisdiction["id"], case_overrides=co)
    lab = intake_lab(
        program["id"], jurisdiction["id"], patient_reference="PT-NOBODY",
    )
    # intake auto-link tried PT-NOBODY (no match) -> UNLINKED; link a matching lab by hand
    lab = intake_lab(
        program["id"], jurisdiction["id"],
        patient_reference=co["patient_reference"], result_value="POSITIVE",
    )
    # ELR auto-link may have already linked it to the open case; only link if still unlinked.
    if lab.get("status") != "LINKED":
        link_lab_to_case(case["id"], jurisdiction["id"], lab["id"])
    classify = api_client.classify_case(
        case["id"], {"classification": "CONFIRMED"},
        make_investigator_headers(jurisdiction["id"]),
    )
    return program, jurisdiction, condition, get_success_data(classify), lab


# ─── Tier 3: Contact lifecycle ─────────────────────────────────────────────
def elicit_contact(program_id, source_case_id, monitoring_jurisdiction_id, **overrides):
    """Elicit a contact (ContactTracer). Returns the contact entity."""
    res = api_client.create_contact(
        create_contact_payload(program_id, source_case_id, monitoring_jurisdiction_id, **overrides),
        make_tracer_headers(monitoring_jurisdiction_id),
    )
    return get_success_data(res)


def queue_and_notify_contact(contact_id, jurisdiction_id, outcome="SUCCESS"):
    """queue-notification then record-notification. Returns the contact after recording."""
    api_client.queue_notification(contact_id, make_tracer_headers(jurisdiction_id))
    res = api_client.record_notification(
        contact_id, {"outcome": outcome}, make_tracer_headers(jurisdiction_id)
    )
    return get_success_data(res)


def schedule_monitoring(contact_id, jurisdiction_id, start_date, end_date,
                        monitoring_type="QUARANTINE"):
    """Schedule a monitoring period for a contact. Returns the period."""
    res = api_client.create_monitoring_period(
        contact_id,
        create_monitoring_period_payload(start_date, end_date, monitoring_type),
        make_tracer_headers(jurisdiction_id),
    )
    return get_success_data(res)


def setup_monitoring_active_contact(program_id, source_case_id, monitoring_jurisdiction_id,
                                    contact_overrides=None,
                                    mp_start="2026-03-16T00:00:00.000Z",
                                    mp_end="2026-03-29T00:00:00.000Z"):
    """Elicit -> queue -> notify -> schedule -> start-monitoring a contact.

    Returns (contact_after_start, monitoring_period). After this the contact is in
    MONITORING_ACTIVE and the jurisdiction's active_monitoring_count has risen by one.
    """
    contact = elicit_contact(
        program_id, source_case_id, monitoring_jurisdiction_id, **(contact_overrides or {})
    )
    queue_and_notify_contact(contact["id"], monitoring_jurisdiction_id, outcome="SUCCESS")
    mp = schedule_monitoring(contact["id"], monitoring_jurisdiction_id, mp_start, mp_end)
    res = api_client.start_monitoring(
        contact["id"], make_tracer_headers(monitoring_jurisdiction_id)
    )
    return get_success_data(res), mp


def setup_notified_contact(program_id, source_case_id, monitoring_jurisdiction_id,
                           contact_overrides=None):
    """Elicit -> queue -> notify a contact (NOTIFIED, no monitoring period). Returns the
    contact after recording the SUCCESS outcome."""
    contact = elicit_contact(
        program_id, source_case_id, monitoring_jurisdiction_id, **(contact_overrides or {})
    )
    return queue_and_notify_contact(contact["id"], monitoring_jurisdiction_id, outcome="SUCCESS")


# ─── Tier 4: Transfer lifecycle ────────────────────────────────────────────
def observe_case_version(case_id, headers=None):
    """Read the current case.version (as EpiAnalyst by default)."""
    res = api_client.get_case(case_id, headers or EPI)
    return get_success_data(res)["version"]


def request_transfer(program_id, case_id, to_jurisdiction_id, expected_case_version,
                     **overrides):
    """Open a jurisdiction transfer (EpiAnalyst). Returns the transfer entity."""
    res = api_client.create_transfer(
        create_transfer_payload(
            program_id, case_id, to_jurisdiction_id, expected_case_version, **overrides
        ),
        EPI,
    )
    return get_success_data(res)


def setup_transfer_requested(condition_overrides=None, prior_classification=None):
    """Program + two jurisdictions (J1, J2) + condition + a case in J1 driven to a
    transferable state, then a REQUESTED transfer to J2.

    If prior_classification is given (e.g. "PROBABLE"), the case is interviewed and
    classified before the transfer (prior status CLASSIFIED); otherwise it is only
    interviewed (prior status UNDER_INVESTIGATION).

    Returns (program, j1, j2, case, transfer).
    """
    program = create_program()
    j1 = create_jurisdiction(program["id"], name="County 1", fips_code="06001")
    j2 = create_jurisdiction(program["id"], name="County 2", fips_code="06002")
    create_condition(program["id"], **(condition_overrides or {}))
    if prior_classification:
        case = open_interview_classify_case(
            program["id"], j1["id"], prior_classification
        )
    else:
        case = open_and_interview_case(program["id"], j1["id"])
    version = observe_case_version(case["id"])
    transfer = request_transfer(program["id"], case["id"], j2["id"], version)
    return program, j1, j2, case, transfer


# ─── Tier 5: NEDSS export / cluster ────────────────────────────────────────
def generate_export(program_id, case_id):
    """Generate a NEDSS export snapshot (EpiAnalyst). Returns the export entity."""
    res = api_client.create_export(create_export_payload(program_id, case_id), EPI)
    return get_success_data(res)


def setup_three_colocated_confirmed_cases(location_id="VENUE-7",
                                          onsets=("2026-03-10", "2026-03-12", "2026-03-14"),
                                          cluster_min_cases=3, cluster_window_days=14):
    """Program + jurisdiction + condition (cluster params, requires_lab_confirmation false)
    + three co-located cases, each interviewed; the first (len-1) classified CONFIRMED.

    Returns (program, jurisdiction, condition, [case_ids]) — the last case is left
    interviewed-but-unclassified so a test can classify it to cross the cluster boundary.
    """
    program, jurisdiction, condition = setup_program_jurisdiction_condition(
        condition_overrides={
            "cluster_min_cases": cluster_min_cases,
            "cluster_window_days": cluster_window_days,
            "requires_lab_confirmation": False,
        }
    )
    case_ids = []
    for i, onset in enumerate(onsets):
        case = open_and_interview_case(
            program["id"], jurisdiction["id"],
            case_overrides={
                "patient_reference": f"PT-{chr(65 + i)}",
                "symptom_onset_date": f"{onset}T00:00:00.000Z",
                "exposure_setting_location_id": location_id,
            },
        )
        case_ids.append(case["id"])
    # Classify all but the last to CONFIRMED.
    for cid in case_ids[:-1]:
        api_client.classify_case(
            cid, {"classification": "CONFIRMED"},
            make_investigator_headers(jurisdiction["id"]),
        )
    return program, jurisdiction, condition, case_ids
