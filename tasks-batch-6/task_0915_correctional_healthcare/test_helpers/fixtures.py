"""Composite setup helpers.

Every helper builds its state from scratch through declared endpoints only: the test
harness relaunches the server before each individual test, so no row and no clock
setting survives from one test to the next. The logical clock therefore always starts
at 2026-05-01T00:00:00Z inside each helper's first call.
"""

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    administration_payload,
    assign_escort_payload,
    book_inmate_payload,
    chronic_enrollment_payload,
    copay_charge_payload,
    grievance_payload,
    hold_status_payload,
    ledger_entry_payload,
    medication_order_payload,
    release_plan_payload,
    review_decision_payload,
    sick_call_payload,
    specialty_referral_payload,
    submit_for_review_payload,
    transport_order_payload,
    triage_payload,
)
from .test_users import (
    TEST_USERS,
    make_custody_officer_headers,
    make_grievance_coordinator_headers,
    make_inmate_headers,
    make_nurse_headers,
    make_peer_reviewer_headers,
    make_provider_headers,
    make_utilization_reviewer_headers,
)

ADMIN = TEST_USERS["health_services_admin_headers"]
INTAKE = TEST_USERS["intake_officer_headers"]
NURSE = TEST_USERS["nurse_headers"]
PROVIDER = TEST_USERS["provider_headers"]
UR = TEST_USERS["utilization_reviewer_headers"]
PEER = TEST_USERS["peer_reviewer_headers"]
CUSTODY = TEST_USERS["custody_officer_headers"]
COORDINATOR = TEST_USERS["grievance_coordinator_headers"]


# ─── Clock ────────────────────────────────────────────

def set_clock(instant: str) -> dict:
    """Advance the logical clock and run the two-step overdue/lapse sweep."""
    return get_success_data(api_client.set_clock(instant, ADMIN))


# ─── Inmates ──────────────────────────────────────────

def book_inmate(**overrides) -> dict:
    """Book one inmate. Returns the created Inmate resource."""
    return get_success_data(
        api_client.create_inmate(book_inmate_payload(**overrides), INTAKE)
    )


def read_inmate(inmate_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_inmate(inmate_id, headers or ADMIN))


def inmate_version(inmate_id: str) -> int:
    """Read the inmate's current version — the value a medication-order writer echoes."""
    return read_inmate(inmate_id)["version"]


def deposit(inmate_id: str, amount_cents: int, memo: str = "commissary deposit") -> dict:
    """Post an operator DEPOSIT into the trust account."""
    return get_success_data(
        api_client.create_ledger_entry(
            inmate_id, ledger_entry_payload(amount_cents, memo=memo), ADMIN
        )
    )


def ledger_entries_for(inmate_id: str) -> list:
    """All ledger entries of one inmate, ordered by created_at ascending."""
    resp = api_client.list_ledger_entries(
        ADMIN, params={"inmate_id": inmate_id, "limit": 100}
    )
    assert resp.status_code == 200, f"Ledger listing failed: {resp.text}"
    return resp.json()["data"]


def freeze_records(inmate_id: str) -> dict:
    return get_success_data(api_client.freeze_records(inmate_id, ADMIN))


def unfreeze_records(inmate_id: str) -> dict:
    return get_success_data(api_client.unfreeze_records(inmate_id, ADMIN))


# ─── Intake screenings ────────────────────────────────

def open_screening(inmate_id: str, screening_type: str = "RECEIVING") -> dict:
    return get_success_data(
        api_client.create_intake_screening(
            inmate_id, {"screening_type": screening_type}, INTAKE
        )
    )


def read_screening(inmate_id: str, screening_id: str) -> dict:
    """Screenings are addressed through their parent inmate's listing endpoint."""
    resp = api_client.list_intake_screenings(inmate_id, ADMIN, params={"limit": 100})
    assert resp.status_code == 200, f"Screening listing failed: {resp.text}"
    for row in resp.json()["data"]:
        if row["id"] == screening_id:
            return row
    raise AssertionError(f"Screening {screening_id} not found for inmate {inmate_id}")


def setup_inmate_with_overdue_receiving_screening(**inmate_overrides):
    """Book an inmate, open a RECEIVING screening and push the clock one second past
    its due_at so the sweep marks it OVERDUE. Returns (inmate, screening)."""
    set_clock("2026-05-01T00:00:00Z")
    inmate = book_inmate(booked_at="2026-05-01T00:00:00Z", **inmate_overrides)
    screening = open_screening(inmate["id"], "RECEIVING")
    set_clock("2026-05-01T12:00:01Z")
    return inmate, read_screening(inmate["id"], screening["id"])


# ─── Chronic care ─────────────────────────────────────

def enrol_chronic(inmate_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_chronic_enrollment(
            inmate_id, chronic_enrollment_payload(**overrides), PROVIDER
        )
    )


def read_enrollment(enrollment_id: str) -> dict:
    return get_success_data(api_client.get_chronic_enrollment(enrollment_id, PROVIDER))


def record_visit(enrollment_id: str, outcome: str) -> dict:
    return get_success_data(
        api_client.create_chronic_visit(enrollment_id, {"outcome": outcome}, NURSE)
    )


def visits_for(enrollment_id: str) -> list:
    resp = api_client.list_chronic_visits(enrollment_id, NURSE, params={"limit": 100})
    assert resp.status_code == 200, f"Visit listing failed: {resp.text}"
    return resp.json()["data"]


# ─── Sick call ────────────────────────────────────────

def submit_sick_call(inmate_id: str, **overrides) -> dict:
    """The inmate submits their own slip, so the entity-backed identity is threaded."""
    return get_success_data(
        api_client.create_sick_call_request(
            sick_call_payload(inmate_id, **overrides), make_inmate_headers(inmate_id)
        )
    )


def read_sick_call(request_id: str) -> dict:
    return get_success_data(api_client.get_sick_call_request(request_id, NURSE))


def triage(request_id: str, acuity: str) -> dict:
    return get_success_data(
        api_client.triage_sick_call_request(request_id, triage_payload(acuity=acuity), NURSE)
    )


def setup_triaged_sick_call(inmate_id: str, acuity: str = "ROUTINE", **overrides):
    """Submit a slip and triage it. Returns the triaged SickCallRequest."""
    request = submit_sick_call(inmate_id, **overrides)
    return triage(request["id"], acuity)


def setup_scheduled_sick_call(inmate_id: str, acuity: str = "ROUTINE", **overrides):
    """Submit → triage → schedule. Returns the SCHEDULED SickCallRequest."""
    request = setup_triaged_sick_call(inmate_id, acuity, **overrides)
    return get_success_data(api_client.schedule_sick_call_request(request["id"], NURSE))


def setup_seen_sick_call(inmate_id: str, acuity: str = "ROUTINE", **overrides):
    """Submit → triage → schedule → see, which posts the co-pay charge.
    Returns the SEEN SickCallRequest."""
    request = setup_scheduled_sick_call(inmate_id, acuity, **overrides)
    return get_success_data(api_client.see_sick_call_request(request["id"], PROVIDER))


# ─── Medication orders ────────────────────────────────

def write_medication_order(inmate_id: str, prescriber_id: str = "u-prov-1", **overrides) -> dict:
    """Write an order, reading the inmate's live version for the mandatory
    expected_inmate_version field first."""
    version = overrides.pop("expected_inmate_version", None)
    if version is None:
        version = inmate_version(inmate_id)
    return get_success_data(
        api_client.create_medication_order(
            medication_order_payload(inmate_id, version, **overrides),
            make_provider_headers(prescriber_id),
        )
    )


def read_order(order_id: str) -> dict:
    return get_success_data(api_client.get_medication_order(order_id, PROVIDER))


def schedule_dose(order_id: str, scheduled_at: str, nurse_id: str = "u-nurse-1") -> dict:
    return get_success_data(
        api_client.create_administration(
            order_id, administration_payload(scheduled_at), make_nurse_headers(nurse_id)
        )
    )


def administrations_for(order_id: str) -> list:
    """MAR rows of one order, returned by scheduled_at ascending."""
    resp = api_client.list_administrations(order_id, NURSE, params={"limit": 100})
    assert resp.status_code == 200, f"MAR listing failed: {resp.text}"
    return resp.json()["data"]


def read_administration(order_id: str, administration_id: str) -> dict:
    for row in administrations_for(order_id):
        if row["id"] == administration_id:
            return row
    raise AssertionError(f"Administration {administration_id} not found on order {order_id}")


def record_dose(administration_id: str, payload: dict, nurse_id: str = "u-nurse-1") -> dict:
    return get_success_data(
        api_client.record_administration(
            administration_id, payload, make_nurse_headers(nurse_id)
        )
    )


def hold_order(order_id: str, prescriber_id: str = "u-prov-1") -> dict:
    return get_success_data(
        api_client.set_medication_order_hold(
            order_id, hold_status_payload(True), make_provider_headers(prescriber_id)
        )
    )


def resume_order(order_id: str, prescriber_id: str = "u-prov-1") -> dict:
    return get_success_data(
        api_client.set_medication_order_hold(
            order_id, hold_status_payload(False), make_provider_headers(prescriber_id)
        )
    )


def setup_dot_order_with_doses(inmate_id: str, scheduled_ats, prescriber_id="u-prov-1",
                               **order_overrides):
    """One ACTIVE DOT order plus one SCHEDULED dose row per instant supplied.
    Returns (order, [administrations])."""
    order = write_medication_order(
        inmate_id, prescriber_id=prescriber_id, route_mode="DOT", **order_overrides
    )
    doses = [schedule_dose(order["id"], at) for at in scheduled_ats]
    return order, doses


# ─── Specialty referrals and utilization review ───────

def request_referral(inmate_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_specialty_referral(
            specialty_referral_payload(inmate_id, **overrides), PROVIDER
        )
    )


def read_referral(referral_id: str) -> dict:
    return get_success_data(api_client.get_specialty_referral(referral_id, CUSTODY))


def referral_version(referral_id: str) -> int:
    """Read the referral's current version — the value a transport writer echoes."""
    return read_referral(referral_id)["version"]


def submit_for_review(referral_id: str, retrospective: bool = False) -> dict:
    return get_success_data(
        api_client.submit_referral_for_review(
            referral_id, submit_for_review_payload(retrospective=retrospective), PROVIDER
        )
    )


def read_review(referral_id: str, review_id: str) -> dict:
    """Reviews are addressed through their parent referral's listing endpoint."""
    resp = api_client.list_utilization_reviews(referral_id, PROVIDER, params={"limit": 100})
    assert resp.status_code == 200, f"Review listing failed: {resp.text}"
    for row in resp.json()["data"]:
        if row["id"] == review_id:
            return row
    raise AssertionError(f"Review {review_id} not found on referral {referral_id}")


def decide_review(review_id: str, decision: str, reviewer_id: str = "u-ur-1") -> dict:
    return get_success_data(
        api_client.decide_utilization_review(
            review_id,
            review_decision_payload(decision=decision),
            make_utilization_reviewer_headers(reviewer_id),
        )
    )


def setup_pending_ur_referral(inmate_id: str, **overrides):
    """Request a referral and open utilization review. Returns (referral, review)."""
    retrospective = overrides.pop("retrospective", False)
    referral = request_referral(inmate_id, **overrides)
    review = submit_for_review(referral["id"], retrospective)
    return read_referral(referral["id"]), review


def setup_authorized_referral(inmate_id: str, **overrides):
    """Request → submit for review → APPROVE, leaving the referral AUTHORIZED.
    Returns (referral, review)."""
    referral, review = setup_pending_ur_referral(inmate_id, **overrides)
    decide_review(review["id"], "APPROVE")
    return read_referral(referral["id"]), read_review(referral["id"], review["id"])


def setup_denied_review_in_peer_review(inmate_id: str, denier_id: str = "u-ur-1",
                                       **overrides):
    """Request → submit → DENY → escalate, leaving the review in PEER_REVIEW.
    Returns (referral, review)."""
    referral, review = setup_pending_ur_referral(inmate_id, **overrides)
    decide_review(review["id"], "DENY", reviewer_id=denier_id)
    get_success_data(api_client.escalate_peer_review(review["id"], PROVIDER))
    return read_referral(referral["id"]), read_review(referral["id"], review["id"])


def peer_decide(review_id: str, peer_decision: str, peer_id: str = "u-peer-1") -> dict:
    return get_success_data(
        api_client.peer_decide_utilization_review(
            review_id,
            {"peer_decision": peer_decision},
            make_peer_reviewer_headers(peer_id),
        )
    )


# ─── Transport ────────────────────────────────────────

def create_transport(referral_id: str, appointment_at: str, officer_id: str = "u-co-1",
                     expected_referral_version=None) -> dict:
    """Create a trip, reading the referral's live version for the mandatory
    expected_referral_version field first."""
    if expected_referral_version is None:
        expected_referral_version = referral_version(referral_id)
    return get_success_data(
        api_client.create_transport_order(
            transport_order_payload(referral_id, appointment_at, expected_referral_version),
            make_custody_officer_headers(officer_id),
        )
    )


def transports_for(referral_id: str) -> list:
    resp = api_client.list_transport_orders(referral_id, CUSTODY, params={"limit": 100})
    assert resp.status_code == 200, f"Transport listing failed: {resp.text}"
    return resp.json()["data"]


def read_transport(referral_id: str, transport_id: str) -> dict:
    for row in transports_for(referral_id):
        if row["id"] == transport_id:
            return row
    raise AssertionError(f"Transport {transport_id} not found on referral {referral_id}")


def assign_escort(transport_id: str, escort_level: str) -> dict:
    return get_success_data(
        api_client.assign_escort(
            transport_id, assign_escort_payload(escort_level), CUSTODY
        )
    )


def dispatch(transport_id: str) -> dict:
    return get_success_data(api_client.dispatch_transport(transport_id, CUSTODY))


def setup_dispatched_trip(referral_id: str, appointment_at: str, escort_level: str):
    """Create → assign escort → dispatch. Returns the DISPATCHED TransportOrder."""
    trip = create_transport(referral_id, appointment_at)
    assign_escort(trip["id"], escort_level)
    return dispatch(trip["id"])


# ─── Trust account ────────────────────────────────────

def post_copay_charge(inmate_id: str, encounter_type: str = "SICK_CALL", **overrides) -> dict:
    return get_success_data(
        api_client.create_copay_charge(
            inmate_id,
            copay_charge_payload(encounter_type=encounter_type, **overrides),
            ADMIN,
        )
    )


def read_charge(charge_id: str) -> dict:
    return get_success_data(api_client.get_copay_charge(charge_id, ADMIN))


# ─── Grievances ───────────────────────────────────────

def file_grievance(inmate_id: str, grieved_event_at: str, **overrides) -> dict:
    """The grievant files their own grievance, so the entity-backed identity is threaded."""
    return get_success_data(
        api_client.create_grievance(
            inmate_id,
            grievance_payload(grieved_event_at, **overrides),
            make_inmate_headers(inmate_id),
        )
    )


def read_grievance(grievance_id: str) -> dict:
    return get_success_data(api_client.get_grievance(grievance_id, COORDINATOR))


def accept_grievance(grievance_id: str, coordinator_id: str = "u-gc-1") -> dict:
    return get_success_data(
        api_client.accept_grievance(
            grievance_id, make_grievance_coordinator_headers(coordinator_id)
        )
    )


def decide_grievance(grievance_id: str, outcome: str, coordinator_id: str = "u-gc-1") -> dict:
    return get_success_data(
        api_client.decide_grievance(
            grievance_id, {"outcome": outcome}, make_grievance_coordinator_headers(coordinator_id)
        )
    )


def escalate_grievance(grievance_id: str, inmate_id: str) -> dict:
    return get_success_data(
        api_client.escalate_grievance(grievance_id, make_inmate_headers(inmate_id))
    )


def setup_accepted_grievance(inmate_id: str, grieved_event_at: str, **overrides):
    """File a grievance and accept it for review. Returns the UNDER_REVIEW Grievance."""
    grievance = file_grievance(inmate_id, grieved_event_at, **overrides)
    return accept_grievance(grievance["id"])


def setup_grievance_at_appeal_under_review(inmate_id: str, grieved_event_at: str):
    """Climb the ladder INFORMAL → FORMAL → APPEAL, leaving the grievance UNDER_REVIEW at
    stage APPEAL. Returns the Grievance."""
    grievance = setup_accepted_grievance(inmate_id, grieved_event_at)
    decide_grievance(grievance["id"], "DENIED")
    escalate_grievance(grievance["id"], inmate_id)
    accept_grievance(grievance["id"])
    decide_grievance(grievance["id"], "DENIED")
    escalate_grievance(grievance["id"], inmate_id)
    return accept_grievance(grievance["id"])


# ─── Release planning and mortality review ────────────

def open_release_plan(inmate_id: str, planned_release_at: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_release_plan(
            inmate_id, release_plan_payload(planned_release_at, **overrides), ADMIN
        )
    )


def release_plans_for(inmate_id: str) -> list:
    resp = api_client.list_release_plans(inmate_id, ADMIN, params={"limit": 100})
    assert resp.status_code == 200, f"Release-plan listing failed: {resp.text}"
    return resp.json()["data"]


def read_release_plan(inmate_id: str, plan_id: str) -> dict:
    for row in release_plans_for(inmate_id):
        if row["id"] == plan_id:
            return row
    raise AssertionError(f"Release plan {plan_id} not found for inmate {inmate_id}")


def finalize_release_plan(plan_id: str) -> dict:
    return get_success_data(api_client.finalize_release_plan(plan_id, ADMIN))


def setup_released_inmate(inmate_id: str, planned_release_at: str,
                          release_type: str = "UNEXPECTED"):
    """Open a plan, finalize it and release the patient. Returns (plan, inmate)."""
    plan = open_release_plan(
        inmate_id, planned_release_at, release_type=release_type
    )
    finalize_release_plan(plan["id"])
    inmate = get_success_data(api_client.release_inmate(inmate_id, ADMIN))
    return read_release_plan(inmate_id, plan["id"]), inmate


def record_death(inmate_id: str, death_at: str, manner: str = "NATURAL") -> dict:
    """Record the in-custody death; the response body is the new mortality review."""
    return get_success_data(
        api_client.record_death_event(
            inmate_id, {"death_at": death_at, "manner": manner}, ADMIN
        )
    )


def mortality_reviews_for(inmate_id: str) -> list:
    resp = api_client.list_mortality_reviews(inmate_id, ADMIN, params={"limit": 100})
    assert resp.status_code == 200, f"Mortality-review listing failed: {resp.text}"
    return resp.json()["data"]


def read_mortality_review(inmate_id: str, review_id: str) -> dict:
    for row in mortality_reviews_for(inmate_id):
        if row["id"] == review_id:
            return row
    raise AssertionError(f"Mortality review {review_id} not found for inmate {inmate_id}")


# ─── Composite scenarios shared by several tests ──────

def setup_dot_and_kop_orders_for_one_patient():
    """One patient holding two ACTIVE orders of different drug_class — a DOT PSYCHOTROPIC
    order and a KOP CHRONIC_MAINTENANCE order, both 2 doses/day from 2026-05-01 through
    2026-05-03 — with the DOT order carrying an ON_TIME administration, a LATE
    administration and a MISSED dose. The clock ends at 2026-05-02T08:00:00Z.

    Returns dict with keys: inmate, dot_order, kop_order, dose_on_time, dose_late,
    dose_missed.
    """
    set_clock("2026-05-01T00:00:00Z")
    inmate = book_inmate(
        booking_number="D-1010", full_name="Casey Nunez", booked_at="2026-05-01T00:00:00Z"
    )
    dot_order = write_medication_order(
        inmate["id"],
        drug_name="Sertraline",
        drug_class="PSYCHOTROPIC",
        route_mode="DOT",
        doses_per_day=2,
        start_date="2026-05-01T00:00:00Z",
        end_date="2026-05-03T00:00:00Z",
    )
    kop_order = write_medication_order(
        inmate["id"],
        drug_name="Lisinopril",
        drug_class="CHRONIC_MAINTENANCE",
        route_mode="KOP",
        doses_per_day=2,
        start_date="2026-05-01T00:00:00Z",
        end_date="2026-05-03T00:00:00Z",
    )
    d1 = schedule_dose(dot_order["id"], "2026-05-01T08:00:00Z")
    d2 = schedule_dose(dot_order["id"], "2026-05-01T20:00:00Z")
    d3 = schedule_dose(dot_order["id"], "2026-05-02T08:00:00Z")

    set_clock("2026-05-01T08:00:00Z")
    record_dose(d1["id"], {"outcome": "ADMINISTERED", "observed_swallow": True})
    set_clock("2026-05-01T21:30:00Z")
    record_dose(d2["id"], {"outcome": "ADMINISTERED", "observed_swallow": True})
    set_clock("2026-05-02T08:00:00Z")
    record_dose(d3["id"], {"outcome": "MISSED"})

    return {
        "inmate": inmate,
        "dot_order": dot_order,
        "kop_order": kop_order,
        "dose_on_time": d1,
        "dose_late": d2,
        "dose_missed": d3,
    }


def setup_three_orders_at_one_facility():
    """One patient at FAC-01 with three ACTIVE DOT orders of different drug_class, all
    1 dose/day from 2026-05-01 through 2026-05-05. Order A ends at 33.33 adherence (one
    ADMINISTERED ON_TIME plus two MISSED), orders B and C at 100.00 each.

    Returns dict with keys: inmate, order_a, order_b, order_c.
    """
    set_clock("2026-05-01T00:00:00Z")
    inmate = book_inmate(
        booking_number="D-1030",
        full_name="Emery Fox",
        facility_code="FAC-01",
        custody_level="MINIMUM",
        booked_at="2026-05-01T00:00:00Z",
    )
    common = dict(
        route_mode="DOT",
        doses_per_day=1,
        start_date="2026-05-01T00:00:00Z",
        end_date="2026-05-05T00:00:00Z",
    )
    order_a = write_medication_order(
        inmate["id"], drug_name="Sertraline", drug_class="PSYCHOTROPIC", **common
    )
    order_b = write_medication_order(
        inmate["id"], drug_name="Lisinopril", drug_class="CHRONIC_MAINTENANCE", **common
    )
    order_c = write_medication_order(
        inmate["id"], drug_name="Amoxicillin", drug_class="ACUTE_SHORT_COURSE", **common
    )

    a1 = schedule_dose(order_a["id"], "2026-05-01T08:00:00Z")
    a2 = schedule_dose(order_a["id"], "2026-05-02T08:00:00Z")
    a3 = schedule_dose(order_a["id"], "2026-05-03T08:00:00Z")
    b1 = schedule_dose(order_b["id"], "2026-05-01T09:00:00Z")
    c1 = schedule_dose(order_c["id"], "2026-05-01T10:00:00Z")

    set_clock("2026-05-01T08:00:00Z")
    record_dose(a1["id"], {"outcome": "ADMINISTERED", "observed_swallow": True})
    set_clock("2026-05-01T09:00:00Z")
    record_dose(b1["id"], {"outcome": "ADMINISTERED", "observed_swallow": True})
    set_clock("2026-05-01T10:00:00Z")
    record_dose(c1["id"], {"outcome": "ADMINISTERED", "observed_swallow": True})
    set_clock("2026-05-02T08:00:00Z")
    record_dose(a2["id"], {"outcome": "MISSED"})
    set_clock("2026-05-03T08:00:00Z")
    record_dose(a3["id"], {"outcome": "MISSED"})

    return {
        "inmate": inmate,
        "order_a": order_a,
        "order_b": order_b,
        "order_c": order_c,
    }


def setup_order_with_mixed_dose_outcomes():
    """One ACTIVE DOT order with four scheduled doses: the first ADMINISTERED ON_TIME, the
    second REFUSED, the third MISSED and the fourth still SCHEDULED. Clock ends at
    2026-05-03T08:00:00Z.

    Returns dict with keys: inmate, order, doses (list of four).
    """
    set_clock("2026-05-01T00:00:00Z")
    inmate = book_inmate(
        booking_number="D-1230", full_name="Bo Chen", booked_at="2026-05-01T00:00:00Z"
    )
    order, doses = setup_dot_order_with_doses(
        inmate["id"],
        [
            "2026-05-01T08:00:00Z",
            "2026-05-02T08:00:00Z",
            "2026-05-03T08:00:00Z",
            "2026-05-04T08:00:00Z",
        ],
        drug_name="Sertraline",
        drug_class="PSYCHOTROPIC",
        doses_per_day=1,
        start_date="2026-05-01T00:00:00Z",
        end_date="2026-05-10T00:00:00Z",
    )
    set_clock("2026-05-01T08:00:00Z")
    record_dose(doses[0]["id"], {"outcome": "ADMINISTERED", "observed_swallow": True})
    set_clock("2026-05-02T08:00:00Z")
    record_dose(doses[1]["id"], {"outcome": "REFUSED"})
    set_clock("2026-05-03T08:00:00Z")
    record_dose(doses[2]["id"], {"outcome": "MISSED"})
    return {"inmate": inmate, "order": order, "doses": doses}


def setup_frozen_patient_with_scheduled_dot_dose():
    """One patient with an ACTIVE DOT order carrying one SCHEDULED dose, whose record has
    then been frozen by a litigation hold while custody_status is still IN_CUSTODY.
    Clock ends at 2026-05-01T08:00:00Z.

    Returns dict with keys: inmate, order, dose.
    """
    set_clock("2026-05-01T00:00:00Z")
    inmate = book_inmate(
        booking_number="D-1110", full_name="Nico Osei", booked_at="2026-05-01T00:00:00Z"
    )
    order, doses = setup_dot_order_with_doses(
        inmate["id"],
        ["2026-05-01T08:00:00Z"],
        drug_name="Sertraline",
        drug_class="PSYCHOTROPIC",
        doses_per_day=1,
        start_date="2026-05-01T00:00:00Z",
        end_date="2026-05-10T00:00:00Z",
    )
    set_clock("2026-05-01T08:00:00Z")
    freeze_records(inmate["id"])
    return {"inmate": inmate, "order": order, "dose": doses[0]}


def setup_held_order_with_scheduled_dose(prescriber_id: str = "u-prov-1",
                                         booking_number: str = "D-1170"):
    """One HELD DOT order with one SCHEDULED dose, written by `prescriber_id`.
    Clock ends at 2026-05-01T08:00:00Z.

    Returns dict with keys: inmate, order, dose.
    """
    set_clock("2026-05-01T00:00:00Z")
    inmate = book_inmate(
        booking_number=booking_number, full_name="Uma Vega", booked_at="2026-05-01T00:00:00Z"
    )
    order, doses = setup_dot_order_with_doses(
        inmate["id"],
        ["2026-05-01T08:00:00Z"],
        prescriber_id=prescriber_id,
        drug_name="Sertraline",
        drug_class="PSYCHOTROPIC",
        doses_per_day=1,
        start_date="2026-05-01T00:00:00Z",
        end_date="2026-05-10T00:00:00Z",
    )
    set_clock("2026-05-01T08:00:00Z")
    hold_order(order["id"], prescriber_id=prescriber_id)
    return {"inmate": inmate, "order": order, "dose": doses[0]}


def setup_two_no_show_trips_on_one_referral():
    """A MEDIUM-custody patient with a ROUTINE referral approved through utilization
    review, a first trip booked/escorted/dispatched and recorded NO_SHOW, and a second
    trip booked/escorted/dispatched and still awaiting its outcome. Clock held at
    2026-05-01T00:00:00Z.

    Returns dict with keys: inmate, referral, trip1, trip2.
    """
    set_clock("2026-05-01T00:00:00Z")
    inmate = book_inmate(
        booking_number="D-1100", full_name="Lane Mercer", booked_at="2026-05-01T00:00:00Z"
    )
    referral, _review = setup_authorized_referral(
        inmate["id"], specialty="OPHTHALMOLOGY", urgency="ROUTINE"
    )
    trip1 = setup_dispatched_trip(referral["id"], "2026-05-03T00:00:00Z", "ESCORT_2")
    get_success_data(
        api_client.record_transport_outcome(trip1["id"], {"outcome": "NO_SHOW"}, CUSTODY)
    )
    trip2 = setup_dispatched_trip(referral["id"], "2026-05-04T00:00:00Z", "ESCORT_2")
    return {"inmate": inmate, "referral": referral, "trip1": trip1, "trip2": trip2}


def setup_escalated_dot_order_before_death():
    """One patient with an ACTIVE DOT order carrying four scheduled doses, three of them
    recorded MISSED in a row so consecutive_missed_count is 3 and escalated_to_prescriber
    is true, and the fourth still SCHEDULED. Clock ends at 2026-05-03T08:00:00Z.

    Returns dict with keys: inmate, order, doses.
    """
    set_clock("2026-05-01T00:00:00Z")
    inmate = book_inmate(
        booking_number="D-1080", full_name="Jamie Kohl", booked_at="2026-05-01T00:00:00Z"
    )
    order, doses = setup_dot_order_with_doses(
        inmate["id"],
        [
            "2026-05-01T08:00:00Z",
            "2026-05-02T08:00:00Z",
            "2026-05-03T08:00:00Z",
            "2026-05-04T08:00:00Z",
        ],
        drug_name="Sertraline",
        drug_class="PSYCHOTROPIC",
        doses_per_day=1,
        start_date="2026-05-01T00:00:00Z",
        end_date="2026-05-10T00:00:00Z",
    )
    for index, instant in enumerate(
        ["2026-05-01T08:00:00Z", "2026-05-02T08:00:00Z", "2026-05-03T08:00:00Z"]
    ):
        set_clock(instant)
        record_dose(doses[index]["id"], {"outcome": "MISSED"})
    return {"inmate": inmate, "order": order, "doses": doses}


def setup_billing_grievance_after_lookback_window():
    """A 600-cent deposit at 2026-05-01, a FUNDED 500-cent SICK_CALL charge at 2026-05-02
    leaving the balance at 100, and a billing grievance naming that charge filed and
    accepted on the same day. The clock then moves to 2026-06-05T00:00:00Z, so both earlier
    ledger entries fall outside the 30-day lookback.

    Returns dict with keys: inmate, charge, grievance.
    """
    set_clock("2026-05-01T00:00:00Z")
    inmate = book_inmate(
        booking_number="D-1090", full_name="Kai Lomax", booked_at="2026-05-01T00:00:00Z"
    )
    deposit(inmate["id"], 600)
    set_clock("2026-05-02T00:00:00Z")
    charge = post_copay_charge(inmate["id"], "SICK_CALL")
    grievance = file_grievance(
        inmate["id"],
        "2026-05-02T00:00:00Z",
        grievance_text="co-pay charged for a nurse-initiated visit",
        subject_copay_charge_id=charge["id"],
    )
    accept_grievance(grievance["id"])
    set_clock("2026-06-05T00:00:00Z")
    return {"inmate": inmate, "charge": charge, "grievance": grievance}


def setup_billing_grievance_over_sick_call_charge():
    """A 1000-cent deposit, a sick-call encounter triaged URGENT, scheduled and seen — which
    posts a FUNDED 500-cent charge and leaves the balance at 500 — and a billing grievance
    naming that charge, accepted for review. Clock held at 2026-05-01T00:00:00Z.

    Returns dict with keys: inmate, sick_call, charge_id, grievance.
    """
    set_clock("2026-05-01T00:00:00Z")
    inmate = book_inmate(
        booking_number="D-1220", full_name="Ada Byrne", booked_at="2026-05-01T00:00:00Z"
    )
    deposit(inmate["id"], 1000)
    sick_call = setup_seen_sick_call(
        inmate["id"], "URGENT", complaint_text="persistent cough"
    )
    grievance = file_grievance(
        inmate["id"],
        "2026-05-01T00:00:00Z",
        grievance_text="this visit was staff initiated",
        subject_copay_charge_id=sick_call["copay_charge_id"],
    )
    accept_grievance(grievance["id"])
    return {
        "inmate": inmate,
        "sick_call": sick_call,
        "charge_id": sick_call["copay_charge_id"],
        "grievance": grievance,
    }


def setup_two_authorized_referrals_with_one_draft_trip():
    """A MEDIUM-custody patient with two AUTHORIZED ROUTINE referrals and a DRAFT trip on
    the first for 2026-05-05T08:00:00Z, occupying the half-open slot [08:00, 12:00).
    Clock held at 2026-05-01T00:00:00Z.

    Returns dict with keys: inmate, referral_one, referral_two, trip.
    """
    set_clock("2026-05-01T00:00:00Z")
    inmate = book_inmate(
        booking_number="D-1210", full_name="Zia Ames", booked_at="2026-05-01T00:00:00Z"
    )
    referral_one, _ = setup_authorized_referral(
        inmate["id"], specialty="CARDIOLOGY", urgency="ROUTINE"
    )
    referral_two, _ = setup_authorized_referral(
        inmate["id"], specialty="OPHTHALMOLOGY", urgency="ROUTINE"
    )
    trip = create_transport(referral_one["id"], "2026-05-05T08:00:00Z")
    return {
        "inmate": inmate,
        "referral_one": referral_one,
        "referral_two": referral_two,
        "trip": trip,
    }


def setup_cancelled_and_draft_trips_past_their_cutoff():
    """A MEDIUM-custody patient with a ROUTINE referral AUTHORIZED at 2026-05-01T00:00:00Z,
    trip 1 booked for 2026-05-03T00:00:00Z and already CANCELLED inside its cutoff, and
    trip 2 booked for 2026-05-05T00:00:00Z and left in DRAFT. The clock ends at
    2026-05-04T23:00:00Z, past both cutoffs.

    Returns dict with keys: inmate, referral, trip_cancelled, trip_draft.
    """
    set_clock("2026-05-01T00:00:00Z")
    inmate = book_inmate(
        booking_number="D-1130", full_name="Pat Quill", booked_at="2026-05-01T00:00:00Z"
    )
    referral, _ = setup_authorized_referral(
        inmate["id"], specialty="DIALYSIS", urgency="ROUTINE"
    )
    trip_cancelled = create_transport(referral["id"], "2026-05-03T00:00:00Z")
    get_success_data(
        api_client.cancel_transport(
            trip_cancelled["id"], {"cancel_reason": "VENDOR_CANCELLED"}, CUSTODY
        )
    )
    set_clock("2026-05-02T23:00:00Z")
    trip_draft = create_transport(referral["id"], "2026-05-05T00:00:00Z")
    set_clock("2026-05-04T23:00:00Z")
    return {
        "inmate": inmate,
        "referral": referral,
        "trip_cancelled": trip_cancelled,
        "trip_draft": trip_draft,
    }


def setup_patient_with_two_medication_orders_and_tier1_enrollment():
    """One patient with an ACTIVE PSYCHOTROPIC order running 2026-05-01 to 2026-05-20, an
    ACTIVE CONTROLLED order running 2026-05-01 to 2026-05-03, and one ACTIVE TIER_1
    chronic-care enrollment. Clock held at 2026-05-01T00:00:00Z.

    Returns dict with keys: inmate, order_psych, order_controlled, enrollment.
    """
    set_clock("2026-05-01T00:00:00Z")
    inmate = book_inmate(
        booking_number="D-1190",
        full_name="Wren Xu",
        custody_level="MINIMUM",
        booked_at="2026-05-01T00:00:00Z",
    )
    order_psych = write_medication_order(
        inmate["id"],
        drug_name="Sertraline",
        drug_class="PSYCHOTROPIC",
        route_mode="DOT",
        doses_per_day=1,
        start_date="2026-05-01T00:00:00Z",
        end_date="2026-05-20T00:00:00Z",
    )
    order_controlled = write_medication_order(
        inmate["id"],
        drug_name="Oxycodone",
        drug_class="CONTROLLED",
        route_mode="DOT",
        doses_per_day=1,
        start_date="2026-05-01T00:00:00Z",
        end_date="2026-05-03T00:00:00Z",
    )
    enrollment = enrol_chronic(inmate["id"], condition_code="DIABETES", severity="SEVERE")
    return {
        "inmate": inmate,
        "order_psych": order_psych,
        "order_controlled": order_controlled,
        "enrollment": enrollment,
    }
