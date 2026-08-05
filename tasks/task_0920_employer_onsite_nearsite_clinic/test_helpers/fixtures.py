"""Composite setup helpers.

Ordering rules baked into these helpers, because two ladder rungs sit above
almost everything else and would otherwise mask the error a test is looking for:

* The confidentiality wall (PRD 2.6 rung 3) refuses the two employer-side roles on
  the eight clinical read routes. Every clinical read performed during setup is
  therefore made by a clinic-side role or by ProgramAdmin, never by
  EmployerBenefitsAdmin or PayrollProcessor.
* The reporting-period freeze (PRD 2.6 rung 6) refuses writes whose governing date
  falls inside a FINALIZED or CLOSED period. `setup_clinic` therefore only ever
  opens a period (status OPEN, which does not freeze), and finalization is an
  explicit last step a test performs itself once all clinical writes are done.
"""

from types import SimpleNamespace

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS
from .factories import (
    create_alternative_standard_payload,
    create_appointment_payload,
    create_eligibility_record_payload,
    create_employer_payload,
    create_health_assessment_payload,
    create_incentive_award_payload,
    create_participant_payload,
    create_provider_payload,
    create_referral_payload,
    create_reporting_period_payload,
    create_site_payload,
    create_staffing_shift_payload,
    create_vendor_contract_payload,
)
from .test_users import (
    TEST_USERS,
    make_clinician_headers,
    make_employer_admin_headers,
    make_navigator_headers,
    make_participant_headers,
)

ADMIN = TEST_USERS["program_admin_headers"]
MANAGER = TEST_USERS["clinic_manager_headers"]
PAYROLL = TEST_USERS["payroll_processor_headers"]


# ---------------------------------------------------------------- clock ----
def set_clock(to_iso8601, headers=None):
    """Advance the logical clock and return the sweep report."""
    return get_success_data(
        api_client.set_clock({"to_iso8601": to_iso8601}, headers or ADMIN)
    )


# ------------------------------------------------------ single-entity ----
def new_employer(**overrides):
    return get_success_data(
        api_client.create_employer(create_employer_payload(**overrides), ADMIN)
    )


def new_site(**overrides):
    return get_success_data(api_client.create_site(create_site_payload(**overrides), ADMIN))


def new_contract(site_id, employer_id, **overrides):
    return get_success_data(
        api_client.create_vendor_contract(
            create_vendor_contract_payload(site_id, employer_id, **overrides), ADMIN
        )
    )


def new_provider(site_id, **overrides):
    return get_success_data(
        api_client.create_provider(create_provider_payload(site_id, **overrides), MANAGER)
    )


def new_shift(site_id, provider_id, **overrides):
    return get_success_data(
        api_client.create_staffing_shift(
            create_staffing_shift_payload(site_id, provider_id, **overrides), MANAGER
        )
    )


def new_eligibility(employer_id, **overrides):
    return get_success_data(
        api_client.create_eligibility_record(
            create_eligibility_record_payload(employer_id, **overrides),
            make_employer_admin_headers(employer_id),
        )
    )


def enroll(employer_id, eligibility_record_id, **overrides):
    return get_success_data(
        api_client.create_participant(
            create_participant_payload(employer_id, eligibility_record_id, **overrides),
            make_employer_admin_headers(employer_id),
        )
    )


def new_reporting_period(employer_id, **overrides):
    return get_success_data(
        api_client.create_reporting_period(
            create_reporting_period_payload(employer_id, **overrides), ADMIN
        )
    )


def record_decision(participant_id, decision):
    return get_success_data(
        api_client.record_authorization_decision(
            participant_id, {"decision": decision}, make_participant_headers(participant_id)
        )
    )


def grant_authorization(participant_id):
    return record_decision(participant_id, "GRANT")


def revoke_authorization(participant_id):
    return record_decision(participant_id, "REVOKE")


# --------------------------------------------------------- scheduling ----
def read_site(site_id, headers=None):
    return get_success_data(api_client.get_site(site_id, headers or ADMIN))


def site_version(site_id, headers=None):
    """Re-read the site so a booking can echo a fresh expected_site_version."""
    return read_site(site_id, headers)["version"]


def read_participant(participant_id, employer_id):
    return get_success_data(
        api_client.get_participant(
            participant_id, make_employer_admin_headers(employer_id)
        )
    )


def participant_version(participant_id, employer_id):
    return read_participant(participant_id, employer_id)["version"]


def book(
    participant_id,
    site_id,
    provider_id,
    scheduled_start,
    visit_type="PRIMARY_CARE",
    headers=None,
    expected_site_version=None,
    **extra,
):
    """Book one appointment, re-reading the site version unless one is supplied."""
    acting = headers or make_participant_headers(participant_id)
    version = (
        expected_site_version
        if expected_site_version is not None
        else site_version(site_id, acting)
    )
    payload = create_appointment_payload(
        participant_id,
        site_id,
        provider_id,
        scheduled_start,
        version,
        visit_type=visit_type,
        **extra,
    )
    return get_success_data(api_client.create_appointment(payload, acting))


def check_in(appointment_id, clinician_id):
    """Check in and return the newly created Visit."""
    return get_success_data(
        api_client.check_in_appointment(appointment_id, make_clinician_headers(clinician_id))
    )


def start_encounter(visit_id, clinician_id):
    return get_success_data(
        api_client.start_visit(visit_id, make_clinician_headers(clinician_id))
    )


def complete_encounter(visit_id, clinician_id, **payload):
    return get_success_data(
        api_client.complete_visit(visit_id, payload, make_clinician_headers(clinician_id))
    )


def amend_encounter(visit_id, clinician_id, expected_visit_version, **payload):
    body = {"expected_visit_version": expected_visit_version}
    body.update(payload)
    return get_success_data(
        api_client.amend_visit(visit_id, body, make_clinician_headers(clinician_id))
    )


def release_disclosure(visit_id, clinician_id):
    return get_success_data(
        api_client.release_visit_disclosure(
            visit_id, make_clinician_headers(clinician_id)
        )
    )


def read_visit(visit_id, clinician_id):
    """Clinical read - always performed by a clinic-side role (rung 3)."""
    return get_success_data(
        api_client.get_visit(visit_id, make_clinician_headers(clinician_id))
    )


# ------------------------------------------------------------ clinical ----
def new_assessment(participant_id, actor_headers, **overrides):
    return get_success_data(
        api_client.create_health_assessment(
            create_health_assessment_payload(participant_id, **overrides), actor_headers
        )
    )


def new_clinic_assessment(participant_id, clinician_id, visit_id, **overrides):
    payload = dict(overrides)
    payload["visit_id"] = visit_id
    return new_assessment(participant_id, make_clinician_headers(clinician_id), **payload)


def new_self_attested_assessment(participant_id, **overrides):
    payload = {"source_type": "SELF_ATTESTED", "bmi": 24.0, "self_reported_tobacco": False}
    payload.update(overrides)
    payload.pop("visit_id", None)
    body = {
        "participant_id": participant_id,
        "measurement_date": TEST_DEFAULTS["SERVICE_DAY"],
    }
    body.update(payload)
    return get_success_data(
        api_client.create_health_assessment(body, make_participant_headers(participant_id))
    )


def raise_referral(participant_id, visit_id, actor_headers, **overrides):
    return get_success_data(
        api_client.create_referral(
            create_referral_payload(participant_id, visit_id, **overrides), actor_headers
        )
    )


def request_alternative(participant_id, health_assessment_id, **overrides):
    return get_success_data(
        api_client.create_alternative_standard(
            create_alternative_standard_payload(
                participant_id, health_assessment_id, **overrides
            ),
            make_participant_headers(participant_id),
        )
    )


def assign_alternative(standard_id, navigator_id, alternative_type="COACHING_PROGRAM"):
    return get_success_data(
        api_client.assign_alternative_standard(
            standard_id,
            {"alternative_type": alternative_type},
            make_navigator_headers(navigator_id),
        )
    )


# -------------------------------------------------------------- money ----
def new_award(participant_id, employer_id, reporting_period_id, **overrides):
    version = overrides.pop("expected_participant_version", None)
    if version is None:
        version = participant_version(participant_id, employer_id)
    payload = create_incentive_award_payload(
        participant_id, reporting_period_id, version, **overrides
    )
    return get_success_data(
        api_client.create_incentive_award(payload, make_employer_admin_headers(employer_id))
    )


def approve_award(award_id, employer_id):
    return get_success_data(
        api_client.approve_incentive_award(award_id, make_employer_admin_headers(employer_id))
    )


def export_award(award_id, payroll_reference="PR-2026-06-001"):
    return get_success_data(
        api_client.export_incentive_award(
            award_id, {"payroll_reference": payroll_reference}, PAYROLL
        )
    )


def mark_award_paid(award_id):
    return get_success_data(api_client.mark_incentive_award_paid(award_id, PAYROLL))


def reverse_award(award_id, employer_id):
    return get_success_data(
        api_client.reverse_incentive_award(award_id, make_employer_admin_headers(employer_id))
    )


def read_period(period_id, headers=None):
    return get_success_data(api_client.get_reporting_period(period_id, headers or ADMIN))


def finalize_period(period_id):
    """Finalize LAST: from this point rung 6 freezes every governed write."""
    return get_success_data(api_client.finalize_reporting_period(period_id, ADMIN))


def restate_period(period_id):
    return get_success_data(api_client.restate_reporting_period(period_id, ADMIN))


def read_report(period_id, headers=None):
    return get_success_data(api_client.get_utilization_report(period_id, headers or ADMIN))


# ----------------------------------------------------- composite setups ----
def setup_clinic(
    clock=TEST_DEFAULTS["SETUP_CLOCK"],
    employer=None,
    site=None,
    contract=None,
    provider=None,
    shift=None,
    coverage_role="PRIMARY_CARE",
    with_navigator=False,
    navigator_count=1,
    eligibility=None,
    participant=None,
    reporting_period=None,
):
    """Employer + site + contract + credentialed clinician + shift + participant.

    Pass ``contract=False``, ``shift=False`` or ``participant=False`` to skip that
    step. ``reporting_period`` opens a period (status OPEN, which does not freeze
    anything); a test that needs a frozen period calls ``finalize_period`` itself
    after all its clinical writes have landed.
    """
    world = SimpleNamespace(
        admin_headers=ADMIN, manager_headers=MANAGER, payroll_headers=PAYROLL
    )

    if clock is not None:
        world.clock = set_clock(clock)

    world.employer = new_employer(**(employer or {}))
    world.employer_id = world.employer["id"]
    world.employer_headers = make_employer_admin_headers(world.employer_id)

    site_overrides = dict(site or {})
    site_type = site_overrides.get("site_type", "ON_SITE")
    if site_type == "ON_SITE" and "host_employer_id" not in site_overrides:
        site_overrides["host_employer_id"] = world.employer_id
    world.site = new_site(**site_overrides)
    world.site_id = world.site["id"]

    world.contract = None
    world.contract_id = None
    if contract is not False:
        world.contract = new_contract(world.site_id, world.employer_id, **(contract or {}))
        world.contract_id = world.contract["id"]

    world.clinician = new_provider(world.site_id, **(provider or {}))
    world.clinician_id = world.clinician["id"]
    world.clinician_headers = make_clinician_headers(world.clinician_id)

    world.navigators = []
    world.navigator = None
    world.navigator_id = None
    world.navigator_headers = None
    if with_navigator:
        for index in range(navigator_count):
            navigator = new_provider(
                world.site_id,
                full_name=f"Navigator {index + 1}",
                provider_function="NAVIGATOR",
            )
            world.navigators.append(navigator)
        world.navigator = world.navigators[0]
        world.navigator_id = world.navigator["id"]
        world.navigator_headers = make_navigator_headers(world.navigator_id)

    world.shift = None
    if shift is not False:
        shift_overrides = dict(shift or {})
        shift_overrides.setdefault("coverage_role", coverage_role)
        world.shift = new_shift(world.site_id, world.clinician_id, **shift_overrides)

    world.eligibility = new_eligibility(world.employer_id, **(eligibility or {}))
    world.eligibility_id = world.eligibility["id"]

    world.participant = None
    world.participant_id = None
    world.participant_headers = None
    if participant is not False:
        world.participant = enroll(
            world.employer_id, world.eligibility_id, **(participant or {})
        )
        world.participant_id = world.participant["id"]
        world.participant_headers = make_participant_headers(world.participant_id)

    world.period = None
    world.period_id = None
    if reporting_period is not None:
        world.period = new_reporting_period(world.employer_id, **(reporting_period or {}))
        world.period_id = world.period["id"]

    return world


def add_member(world, suffix, display_name=None, **eligibility_overrides):
    """Enrol one more member of the same employer and return the participant."""
    overrides = {
        "subscriber_external_id": f"S-{suffix}",
        "member_external_id": f"M-{suffix}",
    }
    overrides.update(eligibility_overrides)
    record = new_eligibility(world.employer_id, **overrides)
    return enroll(
        world.employer_id, record["id"], display_name=display_name or f"Member {suffix}"
    )


def setup_checked_in_visit(
    visit_type="PRIMARY_CARE",
    scheduled_start="2026-06-08T09:00:00Z",
    visit_clock="2026-06-08T10:00:00Z",
    authorization=None,
    world=None,
    **clinic_kwargs,
):
    """Book one appointment and check it in. Returns the world with .appointment
    and .visit attached."""
    if world is None:
        clinic_kwargs.setdefault("coverage_role", visit_type)
        world = setup_clinic(**clinic_kwargs)
    if authorization:
        record_decision(world.participant_id, authorization)
    world.appointment = book(
        world.participant_id,
        world.site_id,
        world.clinician_id,
        scheduled_start,
        visit_type=visit_type,
    )
    world.appointment_id = world.appointment["id"]
    if visit_clock is not None:
        set_clock(visit_clock)
    world.visit = check_in(world.appointment_id, world.clinician_id)
    world.visit_id = world.visit["id"]
    return world


def setup_completed_visit(
    visit_type="PRIMARY_CARE",
    scheduled_start="2026-06-08T09:00:00Z",
    visit_clock="2026-06-08T10:00:00Z",
    authorization=None,
    completion=None,
    world=None,
    **clinic_kwargs,
):
    """Book -> check in -> start -> complete. Returns the world with .visit set to
    the completed encounter."""
    world = setup_checked_in_visit(
        visit_type=visit_type,
        scheduled_start=scheduled_start,
        visit_clock=visit_clock,
        authorization=authorization,
        world=world,
        **clinic_kwargs,
    )
    start_encounter(world.visit_id, world.clinician_id)
    body = dict(completion or {})
    if visit_type == "OCC_HEALTH" and "fitness_conclusion" not in body:
        body["fitness_conclusion"] = "FIT_FOR_DUTY"
    world.visit = complete_encounter(world.visit_id, world.clinician_id, **body)
    return world


def add_completed_visit(world, participant_id, scheduled_start, visit_type, **completion):
    """Book, check in, start and complete one more encounter inside an existing world."""
    appointment = book(
        participant_id,
        world.site_id,
        world.clinician_id,
        scheduled_start,
        visit_type=visit_type,
    )
    visit = check_in(appointment["id"], world.clinician_id)
    start_encounter(visit["id"], world.clinician_id)
    body = dict(completion)
    if visit_type == "OCC_HEALTH" and "fitness_conclusion" not in body:
        body["fitness_conclusion"] = "FIT_FOR_DUTY"
    return appointment, complete_encounter(visit["id"], world.clinician_id, **body)


def setup_high_risk_assessment(
    world=None, measurement_date="2026-06-08", **clinic_kwargs
):
    """A CLINIC_MEASURED assessment scoring 14 points, so outcome_credit_status is
    PENDING_ALTERNATIVE and a reasonable alternative can be requested."""
    clinic_kwargs.setdefault("with_navigator", True)
    world = setup_checked_in_visit(
        visit_type="WELLNESS", world=world, **clinic_kwargs
    )
    world.assessment = new_clinic_assessment(
        world.participant_id,
        world.clinician_id,
        world.visit_id,
        measurement_date=measurement_date,
        systolic_mmhg=145,
        diastolic_mmhg=92,
        bmi=36.0,
        a1c_pct=6.6,
        ldl_mg_dl=165,
        cotinine_ng_ml=12.0,
    )
    world.assessment_id = world.assessment["id"]
    return world
