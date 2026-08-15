"""Composite setup helpers.

Every helper builds preconditions from scratch using only PRD-declared
endpoints (each test runs against a freshly restarted server whose logical
clock reads 2026-08-01T00:00:00Z and whose database is empty). Setup calls
use get_success_data so failures surface as clear "Setup failed" errors
instead of confusing assertion failures.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_adverse_event_payload,
    create_bi_payload,
    create_drug_program_payload,
    create_enrollment_payload,
    create_foundation_pool_payload,
    create_nurse_visit_payload,
    create_pa_payload,
    create_shipment_payload,
    deliver_shipment_payload,
    match_assistance_payload,
    pa_decision_payload,
    resolve_visit_payload,
    set_clock_payload,
)
from .test_users import (
    TEST_USERS,
    make_case_manager_headers,
    make_financial_counselor_headers,
    make_nurse_educator_headers,
)

ADMIN = TEST_USERS["hub_admin_headers"]
CM = TEST_USERS["case_manager_headers"]
FC = TEST_USERS["financial_counselor_headers"]
RX = TEST_USERS["pharmacy_partner_headers"]
PR = TEST_USERS["payer_reviewer_headers"]
MM = TEST_USERS["manufacturer_monitor_headers"]


def _ok(step, resp, expected_status=None):
    data = get_success_data(resp)
    if expected_status is not None and isinstance(data, dict):
        status = data.get("status")
        assert status == expected_status, (
            f"Setup failed at {step}: expected status {expected_status}, "
            f"got {status}"
        )
    return data


# ---------------------------------------------------------------------------
# Tier 1 — configuration and single-entity creation
# ---------------------------------------------------------------------------

def create_program(name="Prog", **overrides):
    resp = api_client.create_drug_program(
        create_drug_program_payload(name=name, **overrides), ADMIN)
    return _ok("create_program", resp)


def create_pool(name="Fund", **overrides):
    resp = api_client.create_foundation_pool(
        create_foundation_pool_payload(name=name, **overrides), ADMIN)
    return _ok("create_pool", resp)


def create_enrollment(program_id, patient_ref="PAT-1", diagnosis_code="C50",
                      as_headers=None):
    resp = api_client.create_enrollment(
        create_enrollment_payload(
            program_id, patient_ref=patient_ref, diagnosis_code=diagnosis_code),
        as_headers or CM)
    return _ok("create_enrollment", resp, expected_status="INTAKE")


def get_enrollment(enrollment_id):
    resp = api_client.get_enrollment(enrollment_id, CM)
    return _ok("get_enrollment", resp)


def enrollment_version(enrollment_id):
    return get_enrollment(enrollment_id)["version"]


def set_clock(to_iso8601):
    resp = api_client.set_clock(set_clock_payload(to_iso8601), ADMIN)
    return _ok("set_clock", resp)


# ---------------------------------------------------------------------------
# Tier 2 — enrollment lifecycle walks
# ---------------------------------------------------------------------------

def record_benefits_investigation(enrollment_id, **overrides):
    """Post the benefits investigation. With requires_prior_auth False the
    enrollment auto-advances to APPROVED; with True it lands in
    BENEFITS_VERIFIED."""
    resp = api_client.create_benefits_investigation(
        enrollment_id, create_bi_payload(**overrides), CM)
    return _ok("record_benefits_investigation", resp)


def create_approved_enrollment(program_id=None, patient_ref="PAT-1",
                               bi_overrides=None, program_overrides=None):
    """Program + enrollment + benefits investigation with no prior-auth
    requirement -> enrollment APPROVED. Returns context dict."""
    program = program_id and None  # placeholder guard; program built below
    prog = create_program(**(program_overrides or {})) if program_id is None \
        else {"id": program_id}
    enr = create_enrollment(prog["id"], patient_ref=patient_ref)
    bi = record_benefits_investigation(
        enr["id"], **({"requires_prior_auth": False} | (bi_overrides or {})))
    enr_after = get_enrollment(enr["id"])
    assert enr_after["status"] == "APPROVED", (
        f"Setup failed: expected APPROVED, got {enr_after['status']}")
    return {"program": prog, "enrollment": enr_after, "bi": bi}


def create_pa_pending_enrollment(patient_ref="PAT-1", bi_overrides=None,
                                 program_overrides=None):
    """Program + enrollment + BI (requires_prior_auth True) + PA ->
    enrollment PA_PENDING, PA SUBMITTED with appeal_round 0."""
    prog = create_program(**(program_overrides or {}))
    enr = create_enrollment(prog["id"], patient_ref=patient_ref)
    bi = record_benefits_investigation(
        enr["id"], **({"requires_prior_auth": True} | (bi_overrides or {})))
    resp = api_client.create_prior_authorization(
        enr["id"], create_pa_payload(), CM)
    pa = _ok("create_prior_authorization", resp, expected_status="SUBMITTED")
    enr_after = get_enrollment(enr["id"])
    assert enr_after["status"] == "PA_PENDING", (
        f"Setup failed: expected PA_PENDING, got {enr_after['status']}")
    return {"program": prog, "enrollment": enr_after, "bi": bi, "pa": pa}


# ---------------------------------------------------------------------------
# Tier 3 — assistance matching and shipment lifecycle shortcuts
# ---------------------------------------------------------------------------

def match_assistance(enrollment_id, assistance_type="COPAY_CARD",
                     counselor_id="fc-1"):
    """Read the enrollment version, then run an OCC-guarded match as the
    given FinancialCounselor. Returns the created assistance record."""
    version = enrollment_version(enrollment_id)
    resp = api_client.match_copay_assistance(
        enrollment_id,
        match_assistance_payload(version, assistance_type=assistance_type),
        make_financial_counselor_headers(counselor_id))
    return _ok("match_assistance", resp)


def request_shipment(enrollment_id, requested_delivery_date="2026-08-03",
                     transit_hours=24, days_supply=30):
    resp = api_client.create_shipment(
        enrollment_id,
        create_shipment_payload(
            requested_delivery_date=requested_delivery_date,
            transit_hours=transit_hours, days_supply=days_supply),
        CM)
    return _ok("request_shipment", resp)


def ship(shipment_id):
    resp = api_client.ship_shipment(shipment_id, RX)
    return _ok("ship", resp, expected_status="SHIPPED")


def deliver(shipment_id, delivered_date):
    resp = api_client.deliver_shipment(
        shipment_id, deliver_shipment_payload(delivered_date), RX)
    return _ok("deliver", resp, expected_status="DELIVERED")


def spoil(shipment_id, reason="temperature excursion"):
    resp = api_client.spoil_shipment(shipment_id, {"reason": reason}, RX)
    return _ok("spoil", resp, expected_status="SPOILED")


def schedule_visit(enrollment_id, nurse_id="nurse-1",
                   window_start="2026-08-02T14:00:00Z",
                   window_end="2026-08-02T15:00:00Z"):
    resp = api_client.create_nurse_visit(
        enrollment_id,
        create_nurse_visit_payload(
            nurse_id=nurse_id, window_start=window_start,
            window_end=window_end),
        CM)
    return _ok("schedule_visit", resp, expected_status="SCHEDULED")


def resolve_visit(visit_id, nurse_id, outcome="COMPLETED"):
    resp = api_client.resolve_nurse_visit(
        visit_id, resolve_visit_payload(outcome),
        make_nurse_educator_headers(nurse_id))
    return _ok("resolve_visit", resp, expected_status=outcome)


def complete_training_visit(enrollment_id, nurse_id="nurse-1",
                            window_start="2026-08-02T10:00:00Z",
                            window_end="2026-08-02T11:00:00Z"):
    """Schedule + resolve one COMPLETED visit; increments the enrollment's
    training_sessions_completed by one."""
    visit = schedule_visit(enrollment_id, nurse_id=nurse_id,
                           window_start=window_start, window_end=window_end)
    return resolve_visit(visit["id"], nurse_id, outcome="COMPLETED")


def report_adverse_event(enrollment_id, as_headers=None, **overrides):
    resp = api_client.create_adverse_event(
        enrollment_id, create_adverse_event_payload(**overrides),
        as_headers or CM)
    return _ok("report_adverse_event", resp, expected_status="REPORTED")


# ---------------------------------------------------------------------------
# Tier 4 — therapy / fulfillment scenarios
# ---------------------------------------------------------------------------

def create_approved_with_card(patient_ref="PAT-1", counselor_id="fc-1",
                              bi_overrides=None, program_overrides=None):
    """APPROVED enrollment with an immediately-ACTIVE COPAY_CARD assistance.
    Returns ctx with program / enrollment / assistance."""
    ctx = create_approved_enrollment(
        patient_ref=patient_ref, bi_overrides=bi_overrides,
        program_overrides=program_overrides)
    assistance = match_assistance(
        ctx["enrollment"]["id"], "COPAY_CARD", counselor_id=counselor_id)
    assert assistance["status"] == "ACTIVE", (
        f"Setup failed: expected assistance ACTIVE, got {assistance['status']}")
    ctx["assistance"] = assistance
    ctx["enrollment"] = get_enrollment(ctx["enrollment"]["id"])
    return ctx


def create_active_with_delivered_fill(patient_ref="PAT-1", with_card=False,
                                      days_supply=30,
                                      requested_delivery_date="2026-08-01",
                                      delivered_date="2026-08-01",
                                      bi_overrides=None,
                                      program_overrides=None,
                                      counselor_id="fc-1"):
    """Full walk to enrollment ACTIVE: program -> enrollment -> BI (no PA)
    -> optional card match -> fill -> ship -> deliver.

    Returns ctx with program / enrollment (ACTIVE, re-read) / fill /
    assistance (when with_card)."""
    if with_card:
        ctx = create_approved_with_card(
            patient_ref=patient_ref, bi_overrides=bi_overrides,
            program_overrides=program_overrides, counselor_id=counselor_id)
    else:
        ctx = create_approved_enrollment(
            patient_ref=patient_ref, bi_overrides=bi_overrides,
            program_overrides=program_overrides)
    enr_id = ctx["enrollment"]["id"]
    fill = request_shipment(
        enr_id, requested_delivery_date=requested_delivery_date,
        days_supply=days_supply)
    assert fill["status"] == "SCHEDULED", (
        f"Setup failed: expected fill SCHEDULED, got {fill['status']}")
    ship(fill["id"])
    delivered = deliver(fill["id"], delivered_date)
    ctx["fill"] = delivered
    ctx["enrollment"] = get_enrollment(enr_id)
    assert ctx["enrollment"]["status"] == "ACTIVE", (
        f"Setup failed: expected ACTIVE, got {ctx['enrollment']['status']}")
    return ctx


def setup_delivered_fill_then_shipped_refill(patient_ref="PAT-1",
                                             days_supply=30,
                                             refill_requested="2026-08-22"):
    """ACTIVE enrollment with fill 1 DELIVERED (days_supply) and fill 2
    SHIPPED but not delivered; the clock ends at refill ship time
    (2026-08-21). Caller advances the clock to the evaluation date.

    Returns ctx with enrollment / fill_1 / fill_2."""
    ctx = create_active_with_delivered_fill(
        patient_ref=patient_ref, days_supply=days_supply,
        requested_delivery_date="2026-08-01", delivered_date="2026-08-01")
    enr_id = ctx["enrollment"]["id"]
    set_clock("2026-08-21T00:00:00Z")
    fill_2 = request_shipment(
        enr_id, requested_delivery_date=refill_requested,
        days_supply=days_supply)
    ship(fill_2["id"])
    ctx["fill_2"] = fill_2
    ctx["fill_1"] = ctx.pop("fill")
    return ctx


def setup_pa_pending_with_reserved_card_and_requested_shipment(
        patient_ref="PAT-1"):
    """PA_PENDING enrollment with injection training completed, a RESERVED
    copay card (matched while PA pending), and one REQUESTED fill blocked on
    financial clearance. For PA-approval cascade tests."""
    ctx = create_pa_pending_enrollment(
        patient_ref=patient_ref,
        program_overrides={"requires_injection_training": True})
    enr_id = ctx["enrollment"]["id"]
    complete_training_visit(enr_id, nurse_id="nurse-1")
    assistance = match_assistance(enr_id, "COPAY_CARD")
    assert assistance["status"] == "RESERVED", (
        f"Setup failed: expected assistance RESERVED, got {assistance['status']}")
    fill = request_shipment(enr_id, requested_delivery_date="2026-08-05")
    assert fill["status"] == "REQUESTED", (
        f"Setup failed: expected fill REQUESTED, got {fill['status']}")
    ctx["assistance"] = assistance
    ctx["fill"] = fill
    ctx["enrollment"] = get_enrollment(enr_id)
    return ctx
