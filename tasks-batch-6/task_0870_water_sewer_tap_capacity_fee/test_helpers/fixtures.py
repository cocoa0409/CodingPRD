"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) internally so setup failures surface as
clear "Setup failed" errors rather than confusing assertion failures. Every helper
builds its preconditions from scratch — the server database is empty before each test.
"""
from prd_bench_local_runner.testing import get_success_data as _data
from .api_client import api_client
from .factories import (
    create_meter_size_schedule_payload, create_fee_schedule_payload,
    create_inspector_payload, create_meter_crew_payload, create_application_payload,
    create_availability_payload, create_project_payload, create_agreement_payload,
    create_escrow_transaction_payload, create_inspection_payload,
    create_meter_set_payload, create_latecomer_payload,
)
from .test_users import (
    TEST_USERS, make_applicant_headers, make_developer_headers,
    make_reviewer_headers, make_field_inspector_headers,
)

ADMIN = TEST_USERS["admin_headers"]


# ─── Reference data ────────────────────────────────────────────────────
def ensure_meter_schedule(meter_size="ONE", eru_factor=2.5, tap_install_fee_cents=250000):
    res = api_client.create_meter_size_schedule(
        create_meter_size_schedule_payload(
            meter_size=meter_size, eru_factor=eru_factor,
            tap_install_fee_cents=tap_install_fee_cents),
        ADMIN)
    return _data(res)


def ensure_fee_schedule(**fee_overrides):
    res = api_client.create_fee_schedule(create_fee_schedule_payload(**fee_overrides), ADMIN)
    return _data(res)


def setup_reference_data(meter_size="ONE", eru_factor=2.5, tap_install_fee_cents=250000,
                         fee_overrides=None):
    """Create a meter-size schedule row + the governing fee schedule."""
    schedule = ensure_meter_schedule(meter_size, eru_factor, tap_install_fee_cents)
    fee = ensure_fee_schedule(**(fee_overrides or {}))
    return schedule, fee


def create_inspector(name="Test Inspector"):
    return _data(api_client.create_inspector(create_inspector_payload(name=name), ADMIN))


def create_meter_crew(name="Test Crew"):
    return _data(api_client.create_meter_crew(create_meter_crew_payload(name=name), ADMIN))


# ─── Connection application building blocks ────────────────────────────
def create_application(applicant_user_id="appl-1", **overrides):
    res = api_client.create_application(
        create_application_payload(**overrides), make_applicant_headers(applicant_user_id))
    return _data(res)


def submit_application(app_id, applicant_user_id="appl-1"):
    return _data(api_client.submit_application(app_id, make_applicant_headers(applicant_user_id)))


def start_review(app_id, reviewer_id="rev-1"):
    return _data(api_client.start_review(app_id, make_reviewer_headers(reviewer_id)))


def record_availability(app_id, distance_to_main_ft=120, reviewer_id="rev-1"):
    res = api_client.create_availability_determination(
        create_availability_payload(app_id, distance_to_main_ft),
        make_reviewer_headers(reviewer_id))
    return _data(res)


def approve_now(app_id, approver_id="rev-2"):
    return _data(api_client.approve_application(app_id, make_reviewer_headers(approver_id)))


def application_under_review(meter_size="ONE", eru_factor=2.5, tap_install_fee_cents=250000,
                            with_fee=False, applicant_user_id="appl-1", reviewer_id="rev-1",
                            **app_overrides):
    """Create reference data, then an application driven to UNDER_REVIEW."""
    ensure_meter_schedule(meter_size, eru_factor, tap_install_fee_cents)
    if with_fee:
        ensure_fee_schedule()
    app_overrides.setdefault("meter_size", meter_size)
    app = create_application(applicant_user_id=applicant_user_id, **app_overrides)
    submit_application(app["id"], applicant_user_id)
    start_review(app["id"], reviewer_id)
    return app


def application_with_availability(distance_to_main_ft=120, availability_reviewer_id="rev-1",
                                  **kw):
    """UNDER_REVIEW application + a recorded availability determination."""
    app = application_under_review(reviewer_id=availability_reviewer_id, with_fee=True, **kw)
    determination = record_availability(app["id"], distance_to_main_ft, availability_reviewer_id)
    return app, determination


def approved_application(service_type="WATER", use_type="RESIDENTIAL", meter_size="ONE",
                         eru_factor=2.5, tap_install_fee_cents=250000,
                         requires_pavement_cut=None, assessment_basis=None, prior_credit_eru=None,
                         distance_to_main_ft=120, availability_reviewer_id="rev-1",
                         approver_id="rev-2", fee_overrides=None, applicant_user_id="appl-1",
                         parcel_id="APN-AP"):
    """Full path: reference data -> create -> submit -> start-review -> availability -> approve.

    Returns the application object after approval (fees stamped)."""
    ensure_meter_schedule(meter_size, eru_factor, tap_install_fee_cents)
    ensure_fee_schedule(**(fee_overrides or {}))
    app_kwargs = dict(parcel_id=parcel_id, service_type=service_type,
                      meter_size=meter_size, use_type=use_type)
    if requires_pavement_cut is not None:
        app_kwargs["requires_pavement_cut"] = requires_pavement_cut
    if assessment_basis is not None:
        app_kwargs["assessment_basis"] = assessment_basis
    if prior_credit_eru is not None:
        app_kwargs["prior_credit_eru"] = prior_credit_eru
    app = create_application(applicant_user_id=applicant_user_id, **app_kwargs)
    submit_application(app["id"], applicant_user_id)
    start_review(app["id"], availability_reviewer_id)
    record_availability(app["id"], distance_to_main_ft, availability_reviewer_id)
    return approve_now(app["id"], approver_id)


# ─── Developer agreement / escrow ──────────────────────────────────────
def agreement_version(agreement_id, developer_user_id="dev-1"):
    return _data(api_client.get_agreement(
        agreement_id, make_developer_headers(developer_user_id)))["version"]


def post_escrow(agreement_id, txn_type, amount_cents, developer_user_id="dev-1",
                expected_version=None):
    """Post an escrow transaction. Fetches the current agreement version unless one is
    supplied (supply a stale one to exercise the OCC guard). Returns the raw response."""
    if expected_version is None:
        expected_version = agreement_version(agreement_id, developer_user_id)
    return api_client.create_escrow_transaction(
        agreement_id,
        create_escrow_transaction_payload(txn_type, amount_cents, expected_version),
        make_developer_headers(developer_user_id))


def setup_offered_agreement(estimated_cost_cents=4000000, reimbursement_cap_cents=5000000,
                            total_assessable_front_ft=400, total_assessable_area_sqft=80000,
                            length_ft=400, developer_user_id="dev-1", application_id=None):
    """App (bare draft) -> project (PROPOSED) -> agreement -> offer (PENDING_ESCROW).

    Returns dict with ids and the post-offer agreement version."""
    if application_id is None:
        application_id = create_application(parcel_id="APN-AGR")["id"]
    project = _data(api_client.create_project(
        create_project_payload(
            application_id, developer_user_id=developer_user_id,
            length_ft=length_ft, estimated_cost_cents=estimated_cost_cents,
            total_assessable_front_ft=total_assessable_front_ft,
            total_assessable_area_sqft=total_assessable_area_sqft,
            reimbursement_cap_cents=reimbursement_cap_cents),
        make_developer_headers(developer_user_id)))
    agreement = _data(api_client.create_agreement(
        create_agreement_payload(project["id"], developer_user_id=developer_user_id), ADMIN))
    offered = _data(api_client.offer_agreement(agreement["id"], ADMIN))
    return {
        "application_id": application_id,
        "project_id": project["id"],
        "agreement_id": agreement["id"],
        "developer_user_id": developer_user_id,
        "agreement_version": offered["version"],
    }


def setup_executed_agreement(estimated_cost_cents=4000000, **kw):
    """Offered agreement, fully funded, then EXECUTED (project -> APPROVED_TO_CONSTRUCT)."""
    ctx = setup_offered_agreement(estimated_cost_cents=estimated_cost_cents, **kw)
    dev = ctx["developer_user_id"]
    post_escrow(ctx["agreement_id"], "DEPOSIT", estimated_cost_cents, dev,
                expected_version=ctx["agreement_version"])
    _data(api_client.execute_agreement(ctx["agreement_id"], make_developer_headers(dev)))
    return ctx


def _drive_project_to_inspected(application_id, estimated_cost_cents, reimbursement_cap_cents,
                                total_assessable_front_ft, total_assessable_area_sqft,
                                length_ft, developer_user_id="dev-1"):
    ctx = setup_executed_agreement(
        estimated_cost_cents=estimated_cost_cents, reimbursement_cap_cents=reimbursement_cap_cents,
        total_assessable_front_ft=total_assessable_front_ft,
        total_assessable_area_sqft=total_assessable_area_sqft,
        length_ft=length_ft, developer_user_id=developer_user_id, application_id=application_id)
    dev = ctx["developer_user_id"]
    _data(api_client.start_construction(ctx["project_id"], make_developer_headers(dev)))
    inspector = create_inspector(name="Construction Inspector")
    _data(api_client.record_inspection(
        ctx["project_id"], make_field_inspector_headers(inspector["id"])))
    ctx["inspector_id"] = inspector["id"]
    return ctx


def setup_accepted_project(estimated_cost_cents=4000000, actual_construction_cost_cents=5000000,
                           reimbursement_cap_cents=6000000, total_assessable_front_ft=500,
                           total_assessable_area_sqft=100000, length_ft=500,
                           developer_user_id="dev-1", application_id=None):
    """Drive a fresh project through to ACCEPTED (pool established).

    Returns dict incl. the post-accept project version for OCC-guarded latecomer creates."""
    if application_id is None:
        application_id = create_application(parcel_id="APN-EXT")["id"]
    ctx = _drive_project_to_inspected(
        application_id, estimated_cost_cents, reimbursement_cap_cents,
        total_assessable_front_ft, total_assessable_area_sqft, length_ft, developer_user_id)
    accepted = _data(api_client.accept_project(
        ctx["project_id"],
        {"actual_construction_cost_cents": actual_construction_cost_cents},
        make_reviewer_headers("rev-1")))
    ctx["project_version"] = accepted["version"]
    return ctx


def setup_extension_ready_to_accept(distance_to_main_ft=300, estimated_cost_cents=3000000,
                                    reimbursement_cap_cents=4000000, total_assessable_front_ft=300,
                                    total_assessable_area_sqft=60000, length_ft=300):
    """An UNDER_REVIEW application with an unavailable determination, whose extension project
    is driven to INSPECTED (agreement EXECUTED). Ready for the accept-cascade test.

    Returns ids incl. the availability determination id that the cascade should flip."""
    ensure_meter_schedule()
    app = create_application(parcel_id="APN-EXTACC", service_type="WATER",
                             meter_size="ONE", use_type="RESIDENTIAL")
    submit_application(app["id"])
    start_review(app["id"], "rev-1")
    determination = record_availability(app["id"], distance_to_main_ft, "rev-1")
    ctx = _drive_project_to_inspected(
        app["id"], estimated_cost_cents, reimbursement_cap_cents,
        total_assessable_front_ft, total_assessable_area_sqft, length_ft, "dev-1")
    ctx["determination_id"] = determination["id"]
    return ctx


def create_latecomer(project_id, benefiting_application_id, method, parcel_front_ft,
                     parcel_area_sqft, expected_version):
    return api_client.create_latecomer_reimbursement(
        create_latecomer_payload(project_id, benefiting_application_id, method,
                                 parcel_front_ft, parcel_area_sqft, expected_version),
        ADMIN)


# ─── Inspections & meter sets ──────────────────────────────────────────
def create_inspection(app_id, inspector_id, inspection_type, scheduled_start, scheduled_end):
    res = api_client.create_inspection(
        create_inspection_payload(app_id, inspector_id, inspection_type,
                                  scheduled_start, scheduled_end),
        make_field_inspector_headers(inspector_id))
    return _data(res)


def create_scheduled_inspection(app_id, inspector_id, inspection_type,
                                scheduled_start, scheduled_end):
    insp = create_inspection(app_id, inspector_id, inspection_type, scheduled_start, scheduled_end)
    _data(api_client.schedule_inspection(insp["id"], make_field_inspector_headers(inspector_id)))
    return insp


def pass_inspection_full(app_id, inspector_id, inspection_type,
                         scheduled_start, scheduled_end):
    """Create -> schedule -> start -> pass an inspection. Returns the inspection id."""
    insp = create_scheduled_inspection(app_id, inspector_id, inspection_type,
                                       scheduled_start, scheduled_end)
    hdr = make_field_inspector_headers(inspector_id)
    _data(api_client.start_inspection(insp["id"], hdr))
    _data(api_client.pass_inspection(insp["id"], hdr))
    return insp["id"]


def create_scheduled_meter_set(app_id, crew_id, inspector_id, appointment_start, appointment_end):
    ms = _data(api_client.create_meter_set(
        create_meter_set_payload(app_id, crew_id, appointment_start, appointment_end),
        make_field_inspector_headers(inspector_id)))
    _data(api_client.schedule_meter_set(ms["id"], make_field_inspector_headers(inspector_id)))
    return ms


def setup_meter_set_installed(app, inspector_id=None, crew_id=None):
    """Given an APPROVED application, pass the TAP inspection, schedule + complete the meter
    set (-> SET), then create the METER_SET inspection and leave it IN_PROGRESS so a test can
    trigger the passing cascade. Returns ids used by the meter-set cascade tests."""
    app_id = app["id"]
    inspector_id = inspector_id or create_inspector(name="Field Inspector")["id"]
    crew_id = crew_id or create_meter_crew(name="Meter Crew")["id"]
    hdr = make_field_inspector_headers(inspector_id)
    # TAP inspection passes (precondition of complete-install).
    pass_inspection_full(app_id, inspector_id, "TAP",
                         "2026-06-01T09:00:00Z", "2026-06-01T10:00:00Z")
    # Meter set: schedule then complete-install (-> SET).
    ms = create_scheduled_meter_set(app_id, crew_id, inspector_id,
                                    "2026-06-03T09:00:00Z", "2026-06-03T10:00:00Z")
    _data(api_client.complete_install_meter_set(ms["id"], hdr))
    # METER_SET inspection driven to IN_PROGRESS (test triggers the pass).
    ms_insp = create_scheduled_inspection(app_id, inspector_id, "METER_SET",
                                          "2026-06-04T09:00:00Z", "2026-06-04T10:00:00Z")
    _data(api_client.start_inspection(ms_insp["id"], hdr))
    return {
        "application_id": app_id,
        "inspector_id": inspector_id,
        "crew_id": crew_id,
        "meter_set_id": ms["id"],
        "meter_set_inspection_id": ms_insp["id"],
    }


def setup_ready_for_activation(service_type="WATER", use_type="RESIDENTIAL", meter_size="ONE",
                               eru_factor=2.5, tap_install_fee_cents=250000,
                               applicant_user_id="appl-1", parcel_id="APN-RFA"):
    """Full lifecycle to READY_FOR_ACTIVATION (RESIDENTIAL, no backflow).

    Returns dict incl. total_fees_due_cents captured at approval, for pay-then-activate tests."""
    app = approved_application(service_type=service_type, use_type=use_type,
                               meter_size=meter_size, eru_factor=eru_factor,
                               tap_install_fee_cents=tap_install_fee_cents,
                               applicant_user_id=applicant_user_id, parcel_id=parcel_id)
    ctx = setup_meter_set_installed(app)
    # Pass the METER_SET inspection -> meter set INSTALLED -> app READY_FOR_ACTIVATION.
    _data(api_client.pass_inspection(
        ctx["meter_set_inspection_id"], make_field_inspector_headers(ctx["inspector_id"])))
    ctx["total_fees_due_cents"] = app["total_fees_due_cents"]
    ctx["applicant_user_id"] = applicant_user_id
    return ctx
