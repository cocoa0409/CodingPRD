"""Composite setup helpers.

These encapsulate the multi-step preambles the test claims require. Every
fixture builds its preconditions from scratch using only PRD-declared endpoints,
because the server database is empty at the start of every test.

Setup calls use get_success_data() (lenient) so a setup failure surfaces as a
clear "Setup failed" rather than a confusing assertion mismatch.

Identity threading: the Examiner is entity-backed; proctor/score calls always use
make_examiner_headers(examiner["id"]) so ownership/segregation comparisons resolve.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import (
    make_clerk_headers,
    make_proctor_headers,
    make_officer_headers,
    make_examiner_headers,
)
from .factories import (
    create_driver_record_payload,
    create_examiner_payload,
    create_knowledge_test_payload,
    create_road_test_appointment_payload,
    create_license_payload,
    create_violation_payload,
    create_fee_payment_payload,
    create_medical_card_payload,
    maneuver_auto,
    maneuver_scored,
)

CLERK = make_clerk_headers("clerk-1")
PROCTOR = make_proctor_headers("kp-1")
OFFICER = make_officer_headers("officer-1")
OFFICER2 = make_officer_headers("officer-2")


# ---------------------------------------------------------------------------
# Tier 1 — single-entity primitives
# ---------------------------------------------------------------------------
def create_driver_record(**overrides) -> dict:
    """Create a fresh DriverRecord (UNLICENSED, no history)."""
    resp = api_client.create_driver_record(create_driver_record_payload(**overrides), CLERK)
    return get_success_data(resp)


def create_examiner(certified_classes=None, opaque_user_id="exu-1", full_name="Ex One") -> dict:
    """Register an Examiner certified for the given classes."""
    payload = create_examiner_payload(
        full_name=full_name,
        certified_classes=certified_classes or ["D"],
        opaque_user_id=opaque_user_id,
    )
    resp = api_client.create_examiner(payload, OFFICER)
    return get_success_data(resp)


def pass_knowledge_test(record_id, scheduled_period=0, correct_answers=40, total_questions=40) -> dict:
    """Schedule and grade a knowledge test to PASSED for a record at the given period."""
    kt = get_success_data(api_client.create_knowledge_test(
        create_knowledge_test_payload(
            record_id, scheduled_period=scheduled_period, total_questions=total_questions,
        ),
        PROCTOR,
    ))
    graded = get_success_data(api_client.grade_knowledge_test(
        kt["id"], {"correct_answers": correct_answers}, PROCTOR,
    ))
    return graded


def get_record(record_id) -> dict:
    return get_success_data(api_client.get_driver_record(record_id, CLERK))


def get_record_version(record_id) -> int:
    return get_record(record_id)["version"]


def capture_fee(record_id, purpose, amount_cents) -> dict:
    resp = api_client.create_fee_payment(
        create_fee_payment_payload(record_id, purpose, amount_cents), CLERK,
    )
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 2/3 — road-test lifecycle shortcuts
# ---------------------------------------------------------------------------
def book_appointment(record_id, examiner, license_class="D",
                     slot_start_period=0, slot_end_period=1) -> dict:
    """Book a road-test appointment on an examiner slot."""
    resp = api_client.create_road_test_appointment(
        create_road_test_appointment_payload(
            record_id, examiner["id"], license_class=license_class,
            slot_start_period=slot_start_period, slot_end_period=slot_end_period,
        ),
        CLERK,
    )
    return get_success_data(resp)


def proctor_and_score(appt_id, examiner, auto_items, score_items) -> dict:
    """Proctor (auto) then score (examiner-adjusted) an appointment to SCORED.

    auto_items / score_items are lists of (maneuver, weight, value) tuples.
    Uses the examiner's own id as X-User-ID so ownership checks pass.
    """
    ex_headers = make_examiner_headers(examiner["id"])
    proctor_payload = {"maneuver_scores": [maneuver_auto(*it) for it in auto_items]}
    get_success_data(api_client.proctor_appointment(appt_id, proctor_payload, ex_headers))
    score_payload = {"maneuver_scores": [maneuver_scored(*it) for it in score_items]}
    return get_success_data(api_client.score_appointment(appt_id, score_payload, ex_headers))


def scored_appointment(record_id, examiner, license_class="D",
                       auto_items=None, score_items=None,
                       slot_start_period=0, slot_end_period=1) -> dict:
    """Book + proctor + score a road test. Returns the SCORED appointment.

    Defaults to a single weight-1 maneuver at 95 (a clear PASS).
    """
    auto_items = auto_items or [("ALL", 1, 95)]
    score_items = score_items or [("ALL", 1, 95)]
    appt = book_appointment(
        record_id, examiner, license_class=license_class,
        slot_start_period=slot_start_period, slot_end_period=slot_end_period,
    )
    proctor_and_score(appt["id"], examiner, auto_items, score_items)
    return get_success_data(api_client.get_road_test_appointment(appt["id"], CLERK))


# ---------------------------------------------------------------------------
# Tier 2/3 — record reaches ELIGIBLE / ACTIVE-licensed
# ---------------------------------------------------------------------------
def eligible_record_with_passed_appointment(license_class="D", dob="1986-01-01",
                                            auto_items=None, score_items=None,
                                            examiner_classes=None, opaque_user_id="exu-1",
                                            full_name="Test Driver") -> dict:
    """A knowledge-passed ELIGIBLE record plus a SCORED appointment.

    Returns dict with: record, examiner, appointment.
    The appointment's outcome depends on the score items (default PASS).
    """
    examiner_classes = examiner_classes or [license_class]
    record = create_driver_record(date_of_birth=dob, full_name=full_name)
    pass_knowledge_test(record["id"])
    examiner = create_examiner(
        certified_classes=examiner_classes, opaque_user_id=opaque_user_id,
    )
    appt = scored_appointment(
        record["id"], examiner, license_class=license_class,
        auto_items=auto_items, score_items=score_items,
    )
    return {"record": record, "examiner": examiner, "appointment": appt}


def active_licensed_record(license_class="D", dob="1986-01-01", is_real_id=False,
                           examiner_classes=None, opaque_user_id="exu-1",
                           full_name="Test Driver", base_fee_cents=None) -> dict:
    """An ELIGIBLE record carried through to an ACTIVE license (ISSUED).

    Returns dict with: record, examiner, appointment, license.
    """
    from .constants import CLASS_BASE_FEE_CENTS
    fee = base_fee_cents if base_fee_cents is not None else CLASS_BASE_FEE_CENTS[license_class]
    ctx = eligible_record_with_passed_appointment(
        license_class=license_class, dob=dob,
        examiner_classes=examiner_classes, opaque_user_id=opaque_user_id,
        full_name=full_name,
    )
    record, examiner, appt = ctx["record"], ctx["examiner"], ctx["appointment"]
    capture_fee(record["id"], "RENEWAL", fee)
    lic_payload = create_license_payload(record["id"], appt["id"], license_class=license_class)
    if is_real_id:
        lic_payload["is_real_id"] = True
    # Issue by a DIFFERENT operator id than the scoring examiner (segregation of duties).
    lic = get_success_data(api_client.create_license(lic_payload, CLERK))
    return {"record": record, "examiner": examiner, "appointment": appt, "license": lic}


# ---------------------------------------------------------------------------
# Tier 4/5 — suspension / reinstatement targeting
# ---------------------------------------------------------------------------
def suspend_active_record(record_id, points=12, occurred_period=0,
                          code="RECKLESS") -> dict:
    """Post a violation that drives an ACTIVE record to SUSPENDED.

    Returns the created violation. Caller fetches the suspension via list.
    """
    resp = api_client.create_violation(
        create_violation_payload(
            record_id, code=code, points=points, occurred_period=occurred_period,
        ),
        OFFICER,
    )
    return get_success_data(resp)


def get_first_suspension(record_id) -> dict:
    data = get_success_data(api_client.list_record_suspensions(record_id, CLERK))
    items = data if isinstance(data, list) else data.get("data", data)
    return items[0]


def setup_served_suspension(points=12, occurred_period=0, advance_to=30,
                            full_name="Susp Driver", opaque_user_id="exu-1") -> dict:
    """Active licensed record -> 12-pt violation opens SUSPENDED (duration 30) ->
    clock advanced so the suspension is SERVED.

    Returns dict with: record, examiner, appointment, license, violation, suspension.
    The record version is NOT re-read here; callers needing OCC read it themselves.
    """
    ctx = active_licensed_record(full_name=full_name, opaque_user_id=opaque_user_id)
    record = ctx["record"]
    violation = suspend_active_record(record["id"], points=points, occurred_period=occurred_period)
    api_client.advance_clock(advance_to, OFFICER)
    suspension = get_first_suspension(record["id"])
    ctx["violation"] = violation
    ctx["suspension"] = suspension
    return ctx


def setup_active_suspension(points=12, occurred_period=0,
                            full_name="Susp Driver", opaque_user_id="exu-1") -> dict:
    """Active licensed record -> 12-pt violation opens an ACTIVE suspension; clock NOT advanced.

    Returns dict with: record, examiner, appointment, license, violation, suspension.
    """
    ctx = active_licensed_record(full_name=full_name, opaque_user_id=opaque_user_id)
    record = ctx["record"]
    violation = suspend_active_record(record["id"], points=points, occurred_period=occurred_period)
    suspension = get_first_suspension(record["id"])
    ctx["violation"] = violation
    ctx["suspension"] = suspension
    return ctx


# ---------------------------------------------------------------------------
# CDL track
# ---------------------------------------------------------------------------
def active_record_with_medical_card(valid_through_period=100, issued_period=0,
                                    license_class="A", opaque_user_id="exu-1",
                                    full_name="Cdl Driver") -> dict:
    """An ACTIVE licensed record (class A) with a VALID medical card, cdl_status NONE.

    Returns dict with: record, examiner, appointment, license, medical_card.
    """
    ctx = active_licensed_record(
        license_class=license_class, opaque_user_id=opaque_user_id, full_name=full_name,
    )
    record = ctx["record"]
    card = get_success_data(api_client.create_medical_card(
        create_medical_card_payload(
            record["id"], issued_period=issued_period, valid_through_period=valid_through_period,
        ),
        CLERK,
    ))
    ctx["medical_card"] = card
    return ctx
