"""Composite setup helpers.

Every helper builds its preconditions from scratch against a freshly started
server, using only endpoints declared in PRD §4. Setup calls go through the
lenient get_success_data() so failures surface as clear setup errors.

Identity threading (PRD §2.1): Patient and Prescriber are entity-backed
roles, so any ownership-gated call is made with make_patient_headers /
make_prescriber_headers carrying the real entity id.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    CLOCK_START_ISO,
    DEFAULT_ALLOCATED_CENTS,
    DEFAULT_LOT_EXPIRY,
    DEFAULT_PERIOD_END,
    DEFAULT_PERIOD_START,
)
from .factories import (
    create_application_payload,
    create_budget_period_payload,
    create_circumstance_payload,
    create_copay_card_payload,
    create_document_payload,
    create_lot_payload,
    create_patient_payload,
    create_prescriber_payload,
    create_program_payload,
    create_screening_payload,
    create_shipment_payload,
)
from .test_users import (
    TEST_USERS,
    make_appeals_officer_headers,
    make_case_worker_headers,
    make_patient_headers,
)

ADMIN = TEST_USERS["program_admin_headers"]
CW = TEST_USERS["case_worker_headers"]
AO = TEST_USERS["appeals_officer_headers"]
DISPENSER = TEST_USERS["dispenser_headers"]

DEFAULT_REVIEWER = "cw_1"


# ---------------------------------------------------------------------------
# Tier 0: clock and atomic creators
# ---------------------------------------------------------------------------

def set_clock(to_iso8601=CLOCK_START_ISO):
    """Advance the logical clock (PRD §2.5)."""
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


def run_sweep():
    return get_success_data(api_client.run_daily_sweep(ADMIN))


def create_program_record(**overrides) -> dict:
    return get_success_data(api_client.create_program(create_program_payload(**overrides), ADMIN))


def create_budget_period_record(program_id, **overrides) -> dict:
    return get_success_data(api_client.create_budget_period(
        create_budget_period_payload(program_id, **overrides), ADMIN))


def create_patient_record(**overrides) -> dict:
    return get_success_data(api_client.create_patient(create_patient_payload(**overrides), CW))


def create_prescriber_record(**overrides) -> dict:
    return get_success_data(api_client.create_prescriber(create_prescriber_payload(**overrides), CW))


def create_screening_record(patient_id, program_id, **overrides) -> dict:
    return get_success_data(api_client.create_screening(
        create_screening_payload(patient_id, program_id, **overrides),
        make_patient_headers(patient_id)))


def upload_document_record(screening_id, patient_id, doc_type, file_reference=None) -> dict:
    payload = create_document_payload(doc_type=doc_type)
    if file_reference is not None:
        payload["file_reference"] = file_reference
    return get_success_data(api_client.upload_screening_document(
        screening_id, payload, make_patient_headers(patient_id)))


def accept_document(document_id, reviewer=DEFAULT_REVIEWER) -> dict:
    return get_success_data(api_client.review_document(
        document_id, {"decision": "ACCEPTED"}, make_case_worker_headers(reviewer)))


def submit_screening_record(screening_id, patient_id) -> dict:
    return get_success_data(api_client.submit_screening(
        screening_id, make_patient_headers(patient_id)))


def verify_screening_record(screening_id, reviewer=DEFAULT_REVIEWER) -> dict:
    return get_success_data(api_client.decide_screening(
        screening_id, {"decision": "VERIFIED"}, make_case_worker_headers(reviewer)))


def create_lot_record(program_id, **overrides) -> dict:
    return get_success_data(api_client.create_inventory_lot(
        create_lot_payload(program_id, **overrides), ADMIN))


def create_copay_card_record(patient_id, program_id, **overrides) -> dict:
    return get_success_data(api_client.create_copay_card(
        create_copay_card_payload(patient_id, program_id, **overrides), CW))


def create_shipment_record(enrollment_id, *, as_headers=None, **overrides) -> dict:
    return get_success_data(api_client.create_shipment(
        create_shipment_payload(enrollment_id, **overrides), as_headers or CW))


# ---------------------------------------------------------------------------
# Tier 1: program and budget-period setup
# ---------------------------------------------------------------------------

def setup_program_with_period(*, allocated_cents=DEFAULT_ALLOCATED_CENTS,
                              clock=CLOCK_START_ISO,
                              program_overrides=None,
                              period_start=DEFAULT_PERIOD_START,
                              period_end=DEFAULT_PERIOD_END,
                              create_period=True) -> dict:
    """Clock + program (+ one budget period). Returns {"program", "budget_period"}."""
    if clock is not None:
        set_clock(clock)
    program = create_program_record(**(program_overrides or {}))
    period = None
    if create_period:
        period = create_budget_period_record(
            program["id"], allocated_cents=allocated_cents,
            period_start=period_start, period_end=period_end)
    return {"program": program, "budget_period": period}


# ---------------------------------------------------------------------------
# Tier 2: screening lifecycle
# ---------------------------------------------------------------------------

def upload_and_accept_required_documents(screening_id, patient_id, insurance_status="UNINSURED") -> list:
    """PROOF_OF_INCOME + IDENTITY always, plus INSURANCE_VERIFICATION unless
    UNINSURED (PRD §3.2); each reviewed to ACCEPTED."""
    docs = [
        upload_document_record(screening_id, patient_id, "PROOF_OF_INCOME"),
        upload_document_record(screening_id, patient_id, "IDENTITY"),
    ]
    if insurance_status != "UNINSURED":
        docs.append(upload_document_record(screening_id, patient_id, "INSURANCE_VERIFICATION"))
    for doc in docs:
        accept_document(doc["id"])
    return docs


def setup_submitted_screening(patient_id, program_id, *, accept_documents=True, **screening_overrides) -> dict:
    """DRAFT screening with all required documents uploaded (and optionally
    accepted), then submitted."""
    screening = create_screening_record(patient_id, program_id, **screening_overrides)
    insurance_status = screening_overrides.get("insurance_status", "UNINSURED")
    if accept_documents:
        upload_and_accept_required_documents(screening["id"], patient_id, insurance_status)
    else:
        docs = [upload_document_record(screening_id, patient_id, "PROOF_OF_INCOME"),
                upload_document_record(screening_id, patient_id, "IDENTITY")]
        if insurance_status != "UNINSURED":
            docs.append(upload_document_record(screening_id, patient_id, "INSURANCE_VERIFICATION"))
    submit_screening_record(screening["id"], patient_id)
    return get_success_data(api_client.get_screening(screening["id"], CW))


def setup_verified_screening(patient_id, program_id, **screening_overrides) -> dict:
    """Full screening lifecycle through VERIFIED."""
    screening = setup_submitted_screening(patient_id, program_id, **screening_overrides)
    return verify_screening_record(screening["id"])


# ---------------------------------------------------------------------------
# Tier 3: application / enrollment lifecycle
# ---------------------------------------------------------------------------

def setup_under_review_application(*, allocated_cents=DEFAULT_ALLOCATED_CENTS,
                                   clock=CLOCK_START_ISO,
                                   program_overrides=None,
                                   screening_overrides=None,
                                   patient_overrides=None,
                                   reviewer=DEFAULT_REVIEWER) -> dict:
    """Program + period + patient + VERIFIED screening + application claimed
    into UNDER_REVIEW by `reviewer`."""
    ctx = setup_program_with_period(allocated_cents=allocated_cents, clock=clock,
                                    program_overrides=program_overrides)
    patient = create_patient_record(**(patient_overrides or {}))
    screening = setup_verified_screening(patient["id"], ctx["program"]["id"],
                                         **(screening_overrides or {}))
    application = get_success_data(api_client.create_application(
        create_application_payload(patient["id"], ctx["program"]["id"], screening["id"]),
        make_patient_headers(patient["id"])))
    claimed = get_success_data(api_client.claim_application(
        application["id"], make_case_worker_headers(reviewer)))
    ctx.update({"patient": patient, "screening": screening, "application": claimed,
                "reviewer": reviewer})
    return ctx


def setup_approved_enrollment(*, allocated_cents=DEFAULT_ALLOCATED_CENTS,
                              clock=CLOCK_START_ISO,
                              program_overrides=None,
                              screening_overrides=None,
                              patient_overrides=None,
                              reviewer=DEFAULT_REVIEWER) -> dict:
    """Golden path: application approved; returns ctx including "enrollment"."""
    ctx = setup_under_review_application(
        allocated_cents=allocated_cents, clock=clock,
        program_overrides=program_overrides, screening_overrides=screening_overrides,
        patient_overrides=patient_overrides, reviewer=reviewer)
    decided = get_success_data(api_client.decide_application(
        ctx["application"]["id"], {"decision": "APPROVED"},
        make_case_worker_headers(reviewer)))
    enrollment = get_success_data(api_client.get_enrollment(decided["enrollment_id"], CW))
    ctx["application"] = decided
    ctx["enrollment"] = enrollment
    return ctx


def setup_denied_application(*, reviewer=DEFAULT_REVIEWER,
                             decision_reason="incomplete documentation", **kwargs) -> dict:
    """Application claimed then DENIED by the reviewer."""
    ctx = setup_under_review_application(reviewer=reviewer, **kwargs)
    decided = get_success_data(api_client.decide_application(
        ctx["application"]["id"],
        {"decision": "DENIED", "decision_reason": decision_reason},
        make_case_worker_headers(reviewer)))
    ctx["application"] = decided
    return ctx


def setup_filed_appeal(*, grounds="the decision was mistaken", **kwargs) -> dict:
    """Denied application + FILED appeal by the owning patient."""
    ctx = setup_denied_application(**kwargs)
    appeal = get_success_data(api_client.create_appeal(
        ctx["application"]["id"], {"grounds": grounds},
        make_patient_headers(ctx["patient"]["id"])))
    ctx["appeal"] = appeal
    return ctx


# ---------------------------------------------------------------------------
# Tier 4: shipments / dispensing
# ---------------------------------------------------------------------------

def setup_reserved_shipment(ctx=None, *, quantity_units=10, lot_quantity=100,
                            unit_cost="100.0000", expiry_date=DEFAULT_LOT_EXPIRY,
                            lot_number=None, idempotency_key=None,
                            destination="PATIENT") -> dict:
    """Approved enrollment + one lot + one RESERVED shipment."""
    if ctx is None:
        ctx = setup_approved_enrollment()
    lot_kwargs = {"quantity_received": lot_quantity, "unit_cost_per_unit": unit_cost,
                  "expiry_date": expiry_date}
    if lot_number is not None:
        lot_kwargs["lot_number"] = lot_number
    lot = create_lot_record(ctx["program"]["id"], **lot_kwargs)
    ship_kwargs = {"quantity_units": quantity_units, "destination": destination}
    if idempotency_key is not None:
        ship_kwargs["idempotency_key"] = idempotency_key
    shipment = create_shipment_record(ctx["enrollment"]["id"], **ship_kwargs)
    ctx["lot"] = lot
    ctx["shipment"] = shipment
    return ctx


def setup_dispatched_shipment(ctx=None, **kwargs) -> dict:
    ctx = setup_reserved_shipment(ctx, **kwargs)
    shipment = get_success_data(api_client.dispatch_shipment(ctx["shipment"]["id"], CW))
    ctx["shipment"] = shipment
    return ctx


def setup_delivered_shipment(ctx=None, **kwargs) -> dict:
    """DISPATCHED shipment delivered by the owning patient (PATIENT destination)."""
    ctx = setup_dispatched_shipment(ctx, **kwargs)
    shipment = get_success_data(api_client.deliver_shipment(
        ctx["shipment"]["id"], make_patient_headers(ctx["patient"]["id"])))
    ctx["shipment"] = shipment
    return ctx


def create_dispense_event_record(shipment_id, lot_id, quantity, **overrides) -> dict:
    payload = {"lot_id": lot_id, "quantity": quantity}
    payload.update(overrides)
    return get_success_data(api_client.create_dispense_event(shipment_id, payload, DISPENSER))


# ---------------------------------------------------------------------------
# Tier 5: circumstances / suspension / second-patient fiscal scenarios
# ---------------------------------------------------------------------------

def report_circumstance_record(enrollment_id, *, by_patient_id=None, **overrides) -> dict:
    """Report a circumstance; by the patient when by_patient_id is given,
    otherwise by a CaseWorker."""
    headers = make_patient_headers(by_patient_id) if by_patient_id else CW
    return get_success_data(api_client.report_circumstance(
        enrollment_id, create_circumstance_payload(**overrides), headers))


def setup_suspended_enrollment(ctx=None, **kwargs) -> dict:
    """Approved enrollment suspended via an APPLIED_SUSPEND circumstance review."""
    if ctx is None:
        ctx = setup_approved_enrollment(**kwargs)
    coc = report_circumstance_record(
        ctx["enrollment"]["id"], by_patient_id=ctx["patient"]["id"],
        circumstance_type="HOUSEHOLD_CHANGE", new_household_size=3,
        note="moved in with family")
    reviewed = get_success_data(api_client.review_circumstance(
        coc["id"], {"decision": "APPLIED_SUSPEND", "review_note": "pending re-verification"}, CW))
    ctx["circumstance"] = reviewed
    ctx["enrollment"] = get_success_data(api_client.get_enrollment(ctx["enrollment"]["id"], CW))
    return ctx


def setup_second_patient_application(*, first_allocated_cents,
                                     second_screening_overrides=None,
                                     claim_second=True,
                                     copay_card=None,
                                     reviewer=DEFAULT_REVIEWER) -> dict:
    """Program with patient A approved (cap 900000 committed) plus patient B
    fully verified with an application (claimed or left SUBMITTED).

    copay_card: when not None, a dict of coverage overrides — an ACTIVE copay
    card is issued for patient B before the application is filed.
    """
    ctx = setup_approved_enrollment(allocated_cents=first_allocated_cents,
                                    patient_overrides={"full_name": "Pat One"},
                                    reviewer=reviewer)
    patient_b = create_patient_record(full_name="Pat Two")
    screening_b = setup_verified_screening(
        patient_b["id"], ctx["program"]["id"], **(second_screening_overrides or {}))
    card = None
    if copay_card is not None:
        card = create_copay_card_record(patient_b["id"], ctx["program"]["id"], **copay_card)
    application_b = get_success_data(api_client.create_application(
        create_application_payload(patient_b["id"], ctx["program"]["id"], screening_b["id"]),
        make_patient_headers(patient_b["id"])))
    if claim_second:
        application_b = get_success_data(api_client.claim_application(
            application_b["id"], make_case_worker_headers(reviewer)))
    ctx.update({"patient_b": patient_b, "screening_b": screening_b,
                "application_b": application_b, "copay_card_b": card})
    return ctx


def get_utilization(program_id) -> dict:
    return get_success_data(api_client.get_program_utilization(program_id, ADMIN))


def refresh_enrollment(enrollment_id) -> dict:
    return get_success_data(api_client.get_enrollment(enrollment_id, CW))


def refresh_lot(lot_id) -> dict:
    return get_success_data(api_client.get_inventory_lot(lot_id, ADMIN))
