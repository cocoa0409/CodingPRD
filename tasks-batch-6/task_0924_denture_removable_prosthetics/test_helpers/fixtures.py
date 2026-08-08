"""Composite setup helpers.

Every entity in this API is built through declared endpoints — the server seeds
nothing — and every window is evaluated against the logical clock, so each
helper below drives the clock explicitly and then walks the public workflow.

Setup calls use the lenient `get_success_data` validator so a broken precondition
surfaces as a clear "Setup step failed" rather than as a confusing assertion.
"""

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import DEFAULT_CLOCK_UTC, REQUIRED_MILESTONES
from . import factories as f
from .test_users import (
    CLINICAL_DIRECTOR_USER_ID,
    PROSTHODONTIST_USER_ID,
    TEST_USERS,
    make_clinical_director_headers,
    make_lab_technician_headers,
    make_patient_headers,
    make_prosthodontist_headers,
)

ADMIN = TEST_USERS["platform_admin_headers"]
FRONT_OFFICE = TEST_USERS["front_office_headers"]
PROSTHODONTIST = TEST_USERS["prosthodontist_headers"]
CLINICAL_DIRECTOR = TEST_USERS["clinical_director_headers"]


# ─────────────────────────────────────────────────────────────────────────
# Tier 0 — logical clock and single-step creates
# ─────────────────────────────────────────────────────────────────────────

def set_clock(to_iso8601=DEFAULT_CLOCK_UTC):
    """Move the server's logical clock and return the resulting clock body."""
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


def register_patient(**overrides):
    return get_success_data(
        api_client.create_patient(f.create_patient_payload(**overrides), FRONT_OFFICE)
    )


def register_lab(**overrides):
    return get_success_data(api_client.create_lab(f.create_lab_payload(**overrides), ADMIN))


def enrol_coverage(patient_id, **overrides):
    return get_success_data(
        api_client.create_coverage(
            f.create_coverage_payload(patient_id, **overrides), FRONT_OFFICE
        )
    )


def open_case(patient_id, prosthesis_type="FLEXIBLE_PARTIAL", **overrides):
    return get_success_data(
        api_client.create_case(
            f.create_case_payload(patient_id, prosthesis_type, **overrides), PROSTHODONTIST
        )
    )


def add_arch(case_id, arch_position="MAXILLARY", **overrides):
    return get_success_data(
        api_client.create_case_arch(
            f.create_case_arch_payload(case_id, arch_position, **overrides), PROSTHODONTIST
        )
    )


def complete_exam(case_id):
    return get_success_data(api_client.complete_exam(case_id, PROSTHODONTIST))


def read_case(case_id):
    return get_success_data(api_client.get_case(case_id, FRONT_OFFICE))


def read_arch(case_arch_id):
    return get_success_data(api_client.get_case_arch(case_arch_id, PROSTHODONTIST))


def read_prosthesis(prosthesis_id):
    return get_success_data(api_client.get_prosthesis(prosthesis_id, PROSTHODONTIST))


def read_patient(patient_id):
    return get_success_data(api_client.get_patient(patient_id, FRONT_OFFICE))


def read_lab(lab_id):
    return get_success_data(api_client.get_lab(lab_id, ADMIN))


def read_lab_case(lab_case_id):
    return get_success_data(api_client.get_lab_case(lab_case_id, PROSTHODONTIST))


def read_service(service_id):
    return get_success_data(api_client.get_service(service_id, PROSTHODONTIST))


def read_warranty_claim(warranty_claim_id):
    return get_success_data(api_client.get_warranty_claim(warranty_claim_id, PROSTHODONTIST))


def read_remake_request(remake_request_id):
    return get_success_data(api_client.get_remake_request(remake_request_id, PROSTHODONTIST))


def read_coverage(coverage_id):
    return get_success_data(api_client.get_coverage(coverage_id, FRONT_OFFICE))


def read_predetermination(predetermination_id):
    return get_success_data(api_client.get_predetermination(predetermination_id, FRONT_OFFICE))


def read_claim(claim_id):
    return get_success_data(api_client.get_claim(claim_id, FRONT_OFFICE))


def read_payment_plan(payment_plan_id):
    return get_success_data(api_client.get_payment_plan(payment_plan_id, FRONT_OFFICE))


def read_installment(installment_id):
    return get_success_data(api_client.get_installment(installment_id, FRONT_OFFICE))


def read_try_in(try_in_id):
    return get_success_data(api_client.get_try_in(try_in_id, PROSTHODONTIST))


def read_impression(impression_id):
    return get_success_data(api_client.get_impression(impression_id, PROSTHODONTIST))


def case_version(case_id):
    return read_case(case_id)["version"]


def arch_version(case_arch_id):
    return read_arch(case_arch_id)["version"]


def prosthesis_version(prosthesis_id):
    return read_prosthesis(prosthesis_id)["version"]


# ─────────────────────────────────────────────────────────────────────────
# Listing helpers (several rows are discoverable only through a list filter)
# ─────────────────────────────────────────────────────────────────────────

def installments_of(payment_plan_id, installment_status=None):
    params = {"payment_plan_id": payment_plan_id, "limit": 100, "offset": 0}
    if installment_status:
        params["installment_status"] = installment_status
    rows = get_success_data(api_client.list_installments(FRONT_OFFICE, params=params))
    return sorted(rows, key=lambda row: row["sequence_number"])


def remake_requests_of(case_arch_id):
    return get_success_data(
        api_client.list_remake_requests(
            PROSTHODONTIST, params={"case_arch_id": case_arch_id, "limit": 100, "offset": 0}
        )
    )


def lab_cases_of(case_arch_id):
    return get_success_data(
        api_client.list_lab_cases(
            PROSTHODONTIST, params={"case_arch_id": case_arch_id, "limit": 100, "offset": 0}
        )
    )


def services_of(prosthesis_id):
    return get_success_data(
        api_client.list_services(
            PROSTHODONTIST, params={"prosthesis_id": prosthesis_id, "limit": 100, "offset": 0}
        )
    )


def claims_of(case_id):
    return get_success_data(
        api_client.list_claims(
            FRONT_OFFICE, params={"case_id": case_id, "limit": 100, "offset": 0}
        )
    )


def impressions_of(case_arch_id):
    return get_success_data(
        api_client.list_impressions(
            PROSTHODONTIST, params={"case_arch_id": case_arch_id, "limit": 100, "offset": 0}
        )
    )


# ─────────────────────────────────────────────────────────────────────────
# Tier 1 — insurance preconditions
# ─────────────────────────────────────────────────────────────────────────

def submit_predetermination(case_id, coverage_id):
    return get_success_data(
        api_client.create_predetermination(
            f.create_predetermination_payload(case_id, coverage_id), FRONT_OFFICE
        )
    )


def determine_predetermination(predetermination_id, determination):
    return get_success_data(
        api_client.determine_predetermination(
            predetermination_id, {"determination": determination}, FRONT_OFFICE
        )
    )


def approved_predetermination(case_id, coverage_id):
    """Submit a preauthorization for the case and record an APPROVED answer."""
    predetermination = submit_predetermination(case_id, coverage_id)
    return determine_predetermination(predetermination["id"], "APPROVED")


def open_claim(case_id, coverage_id):
    return get_success_data(
        api_client.create_claim(f.create_claim_payload(case_id, coverage_id), FRONT_OFFICE)
    )


def submit_claim(claim_id):
    return get_success_data(api_client.submit_claim(claim_id, FRONT_OFFICE))


def post_claim_payment(claim_id, adjudication_outcome="PAID"):
    return get_success_data(
        api_client.post_claim_payment(
            claim_id, {"adjudication_outcome": adjudication_outcome}, FRONT_OFFICE
        )
    )


# ─────────────────────────────────────────────────────────────────────────
# Tier 2 — the fabrication walk, one arch at a time
# ─────────────────────────────────────────────────────────────────────────

def start_fabrication(case_arch_id):
    return get_success_data(api_client.start_fabrication(case_arch_id, PROSTHODONTIST))


def capture_impression(case_arch_id, capture_method="DIGITAL_SCAN"):
    return get_success_data(
        api_client.create_impression(
            f.create_impression_payload(case_arch_id, capture_method), PROSTHODONTIST
        )
    )


def review_impression(impression_id, quality_score):
    return get_success_data(
        api_client.review_impression(
            impression_id, f.review_impression_payload(quality_score), PROSTHODONTIST
        )
    )


def request_retake(impression_id, capture_method="PHYSICAL_IMPRESSION"):
    return get_success_data(
        api_client.request_retake(
            impression_id, {"capture_method": capture_method}, PROSTHODONTIST
        )
    )


def accepted_impression(case_arch_id, capture_method="DIGITAL_SCAN", quality_score=90):
    """Capture one impression and score it into the accepted band."""
    impression = capture_impression(case_arch_id, capture_method)
    return review_impression(impression["id"], quality_score)


def book_try_in(case_arch_id, milestone_kind):
    return get_success_data(
        api_client.create_try_in(
            f.create_try_in_payload(case_arch_id, milestone_kind), PROSTHODONTIST
        )
    )


def decide_try_in(try_in_id, decision, user_id=PROSTHODONTIST_USER_ID):
    return get_success_data(
        api_client.decide_try_in(
            try_in_id, {"decision": decision}, make_prosthodontist_headers(user_id)
        )
    )


def walk_all_milestones(case_arch_id, prosthesis_type):
    """Book and approve every required try-in milestone for the arch's type."""
    approved = []
    for milestone_kind in REQUIRED_MILESTONES[prosthesis_type]:
        milestone = book_try_in(case_arch_id, milestone_kind)
        approved.append(decide_try_in(milestone["id"], "APPROVE"))
    return approved


def draft_lab_case(case_arch_id, dental_lab_id, **overrides):
    """Draft a lab case, reading the arch's current version for the OCC guard."""
    expected = overrides.pop("expected_case_arch_version", None)
    if expected is None:
        expected = arch_version(case_arch_id)
    return get_success_data(
        api_client.create_lab_case(
            f.create_lab_case_payload(case_arch_id, dental_lab_id, expected, **overrides),
            PROSTHODONTIST,
        )
    )


def dispatch_lab_case(lab_case_id):
    return get_success_data(api_client.dispatch_lab_case(lab_case_id, FRONT_OFFICE))


def receive_lab_case(lab_case_id, dental_lab_id):
    return get_success_data(
        api_client.receive_lab_case(lab_case_id, make_lab_technician_headers(dental_lab_id))
    )


def qc_lab_case(lab_case_id, qc_result="PASS"):
    return get_success_data(
        api_client.qc_lab_case(lab_case_id, {"qc_result": qc_result}, PROSTHODONTIST)
    )


def resend_lab_case(lab_case_id):
    return get_success_data(api_client.resend_lab_case(lab_case_id, FRONT_OFFICE))


def run_lab_round_trip(case_arch_id, dental_lab_id, qc_result="PASS", **overrides):
    """Draft, dispatch, receive and QC one lab case for the arch."""
    lab_case = draft_lab_case(case_arch_id, dental_lab_id, **overrides)
    dispatch_lab_case(lab_case["id"])
    receive_lab_case(lab_case["id"], dental_lab_id)
    return qc_lab_case(lab_case["id"], qc_result)


def deliver_prosthesis(case_arch_id, superseded_prosthesis_id=None):
    payload = f.create_prosthesis_payload(case_arch_id)
    if superseded_prosthesis_id is not None:
        payload["superseded_prosthesis_id"] = superseded_prosthesis_id
    return get_success_data(api_client.create_prosthesis(payload, PROSTHODONTIST))


# ─────────────────────────────────────────────────────────────────────────
# Tier 3 — full-lifecycle composites
# ─────────────────────────────────────────────────────────────────────────

def setup_case_past_exam(
    prosthesis_type="FLEXIBLE_PARTIAL",
    arch_position="MAXILLARY",
    clock=DEFAULT_CLOCK_UTC,
    patient_overrides=None,
    with_coverage=False,
    coverage_overrides=None,
):
    """Patient + case + one arch + closed exam. Returns a context dict."""
    set_clock(clock)
    patient = register_patient(**(patient_overrides or {}))
    coverage = None
    if with_coverage:
        coverage = enrol_coverage(patient["id"], **(coverage_overrides or {}))
    case = open_case(patient["id"], prosthesis_type)
    arch = add_arch(case["id"], arch_position)
    case = complete_exam(case["id"])
    return {
        "patient": patient,
        "coverage": coverage,
        "case": case,
        "arch": arch,
        "prosthesis_type": prosthesis_type,
    }


def setup_arch_ready_for_delivery(
    prosthesis_type="FLEXIBLE_PARTIAL",
    arch_position="MAXILLARY",
    clock=DEFAULT_CLOCK_UTC,
    quality_score=90,
    capture_method="DIGITAL_SCAN",
    patient_overrides=None,
    lab_overrides=None,
    coverage_overrides=None,
    lab_case_overrides=None,
):
    """Drive one arch from registration all the way to READY_FOR_DELIVERY.

    A case whose fee schedule reaches the predetermination threshold gets a
    coverage and an approved preauthorization automatically, because the
    fabrication start is gated on one.
    """
    set_clock(clock)
    patient = register_patient(**(patient_overrides or {}))
    lab = register_lab(**(lab_overrides or {}))
    case = open_case(patient["id"], prosthesis_type)
    arch = add_arch(case["id"], arch_position)
    case = complete_exam(case["id"])

    coverage = None
    predetermination = None
    if case["predetermination_required"]:
        coverage = enrol_coverage(patient["id"], **(coverage_overrides or {}))
        predetermination = approved_predetermination(case["id"], coverage["id"])
    elif coverage_overrides is not None:
        coverage = enrol_coverage(patient["id"], **coverage_overrides)

    start_fabrication(arch["id"])
    impression = accepted_impression(arch["id"], capture_method, quality_score)
    walk_all_milestones(arch["id"], prosthesis_type)
    lab_case = run_lab_round_trip(arch["id"], lab["id"], "PASS", **(lab_case_overrides or {}))

    return {
        "patient": patient,
        "lab": lab,
        "case": read_case(case["id"]),
        "arch": read_arch(arch["id"]),
        "impression": impression,
        "lab_case": lab_case,
        "coverage": coverage,
        "predetermination": predetermination,
        "prosthesis_type": prosthesis_type,
    }


def drive_arch_to_lab_fabrication(
    patient_id,
    prosthesis_type="FLEXIBLE_PARTIAL",
    arch_position="MAXILLARY",
    quality_score=93,
    capture_method="DIGITAL_SCAN",
):
    """Open a case for an existing patient and walk one arch to LAB_FABRICATION."""
    case = open_case(patient_id, prosthesis_type)
    arch = add_arch(case["id"], arch_position)
    case = complete_exam(case["id"])
    start_fabrication(arch["id"])
    accepted_impression(arch["id"], capture_method, quality_score)
    walk_all_milestones(arch["id"], prosthesis_type)
    return {"case": read_case(case["id"]), "arch": read_arch(arch["id"])}


def setup_delivered_prosthesis(**kwargs):
    """Everything `setup_arch_ready_for_delivery` builds, then delivered."""
    ctx = setup_arch_ready_for_delivery(**kwargs)
    prosthesis = deliver_prosthesis(ctx["arch"]["id"])
    ctx["prosthesis"] = prosthesis
    ctx["case"] = read_case(ctx["case"]["id"])
    ctx["arch"] = read_arch(ctx["arch"]["id"])
    return ctx


# ─────────────────────────────────────────────────────────────────────────
# Tier 4 — post-delivery services, warranty and remake
# ─────────────────────────────────────────────────────────────────────────

def request_service(prosthesis_id, service_type, **overrides):
    expected = overrides.pop("expected_prosthesis_version", None)
    if expected is None:
        expected = prosthesis_version(prosthesis_id)
    payload = f.create_service_payload(prosthesis_id, service_type, expected, **overrides)
    return get_success_data(api_client.create_service(payload, PROSTHODONTIST))


def complete_service(service_id):
    return get_success_data(api_client.complete_service(service_id, PROSTHODONTIST))


def void_service(service_id):
    return get_success_data(api_client.void_service(service_id, FRONT_OFFICE))


def open_warranty_claim(prosthesis_id, reported_issue="Reported fault on the appliance", **over):
    return get_success_data(
        api_client.create_warranty_claim(
            f.create_warranty_claim_payload(prosthesis_id, reported_issue, **over), PROSTHODONTIST
        )
    )


def adjudicate_warranty_claim(
    warranty_claim_id, fault_verdict, director_user_id=CLINICAL_DIRECTOR_USER_ID
):
    return get_success_data(
        api_client.adjudicate_warranty_claim(
            warranty_claim_id,
            {"fault_verdict": fault_verdict},
            make_clinical_director_headers(director_user_id),
        )
    )


def clinical_review_warranty_claim(
    warranty_claim_id, resolved_verdict, director_user_id=CLINICAL_DIRECTOR_USER_ID
):
    return get_success_data(
        api_client.clinical_review_warranty_claim(
            warranty_claim_id,
            {"resolved_verdict": resolved_verdict},
            make_clinical_director_headers(director_user_id),
        )
    )


def request_remake(
    case_arch_id, reason_code="FIT_FAILURE", warranty_claim_id=None,
    requester_user_id=PROSTHODONTIST_USER_ID,
):
    payload = f.create_remake_request_payload(case_arch_id, reason_code)
    if warranty_claim_id is not None:
        payload["warranty_claim_id"] = warranty_claim_id
    return get_success_data(
        api_client.create_remake_request(payload, make_prosthodontist_headers(requester_user_id))
    )


def approve_remake(remake_request_id, director_user_id=CLINICAL_DIRECTOR_USER_ID):
    return get_success_data(
        api_client.approve_remake_request(
            remake_request_id, make_clinical_director_headers(director_user_id)
        )
    )


def deny_remake(remake_request_id, director_user_id=CLINICAL_DIRECTOR_USER_ID, denial_reason=None):
    payload = {} if denial_reason is None else {"denial_reason": denial_reason}
    return get_success_data(
        api_client.deny_remake_request(
            remake_request_id, make_clinical_director_headers(director_user_id), payload
        )
    )


def complete_recall(prosthesis_id, recall_outcome):
    return get_success_data(
        api_client.recall_complete(
            prosthesis_id, {"recall_outcome": recall_outcome}, PROSTHODONTIST
        )
    )


# ─────────────────────────────────────────────────────────────────────────
# Tier 5 — money: plans, installments and the delinquency sweep
# ─────────────────────────────────────────────────────────────────────────

def open_payment_plan(patient_id, case_id, **overrides):
    expected = overrides.pop("expected_prosthesis_case_version", None)
    if expected is None:
        expected = case_version(case_id)
    payload = f.create_payment_plan_payload(patient_id, case_id, expected, **overrides)
    return get_success_data(api_client.create_payment_plan(payload, FRONT_OFFICE))


def assess_delinquency(payment_plan_id):
    return get_success_data(api_client.assess_delinquency(payment_plan_id, ADMIN))


def pay_installment(installment_id, amount_paid, patient_id=None):
    headers = make_patient_headers(patient_id) if patient_id else FRONT_OFFICE
    return get_success_data(
        api_client.pay_installment(installment_id, f.pay_installment_payload(amount_paid), headers)
    )


def reverse_installment_payment(installment_id):
    return get_success_data(
        api_client.reverse_installment_payment(installment_id, FRONT_OFFICE)
    )


def setup_delinquent_plan(
    prosthesis_type="FLEXIBLE_PARTIAL",
    first_due_date="2026-05-05T00:00:00Z",
    sweep_clock="2026-05-20T00:00:00Z",
    ctx=None,
    **plan_overrides,
):
    """Strike a plan whose first installment is swept into MISSED, raising the gate.

    When `ctx` is supplied the plan is struck on that already-built case;
    otherwise a fresh single-arch case past complete-exam is built first.
    """
    if ctx is None:
        ctx = setup_case_past_exam(prosthesis_type=prosthesis_type)
    plan = open_payment_plan(
        ctx["patient"]["id"], ctx["case"]["id"], first_due_date=first_due_date, **plan_overrides
    )
    set_clock(sweep_clock)
    plan = assess_delinquency(plan["id"])
    ctx["plan"] = plan
    return ctx


def setup_lab_credit_ready_remake(lab_invoice_amount=1600.00):
    """A delivered appliance, an ACTIVE plan, and a LAB_FAULT claim already adjudicated.

    Leaves a PENDING_APPROVAL remake request citing that claim, so approving it
    exercises the whole credit-and-reschedule chain.
    """
    ctx = setup_delivered_prosthesis(
        lab_case_overrides={"lab_invoice_amount": lab_invoice_amount}
    )
    plan = open_payment_plan(ctx["patient"]["id"], ctx["case"]["id"])
    claim = open_warranty_claim(
        ctx["prosthesis"]["id"],
        "Base plate porosity traced to the laboratory pour",
        attributed_lab_case_id=ctx["lab_case"]["id"],
    )
    claim = adjudicate_warranty_claim(claim["id"], "LAB_FAULT")
    remake = request_remake(
        ctx["arch"]["id"], reason_code="LAB_DEFECT", warranty_claim_id=claim["id"]
    )
    ctx["plan"] = plan
    ctx["warranty_claim"] = claim
    ctx["remake_request"] = remake
    return ctx
