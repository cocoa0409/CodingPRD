"""Composite setup helpers for multi-step test prerequisites.

Every helper builds state from an empty database using only PRD-declared
endpoints, and uses get_success_data() so a setup failure surfaces as a clear
"Setup step failed" error rather than a confusing assertion deep in a test.

Identity threading: Grower calls that are ownership-gated always use
make_grower_headers(customer_id); Applicator calls that are assignment-gated
always use make_applicator_headers(applicator_id).
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from . import constants as C
from .api_client import api_client
from .factories import (
    create_customer_payload, create_field_payload, create_product_payload,
    create_product_p2_payload, create_compatibility_rule_payload,
    create_prescription_payload, create_applicator_payload,
    create_equipment_payload, create_calibration_record_payload,
    create_weather_observation_payload, create_work_order_payload,
    schedule_work_order_payload, create_rinsate_record_payload,
    create_drift_complaint_payload,
)
from .test_users import TEST_USERS, make_grower_headers, make_applicator_headers

ADMIN = TEST_USERS["admin_headers"]
AGRONOMIST = TEST_USERS["agronomist_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]
COMPLIANCE = TEST_USERS["compliance_headers"]


# ---------------------------------------------------------------------------
# Granular creators
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str) -> dict:
    """Advance the server logical clock (CoopAdmin test-driving capability)."""
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN))


def create_customer(**overrides) -> dict:
    return get_success_data(api_client.create_customer(create_customer_payload(**overrides), ADMIN))


def create_neighbor_customer(**overrides) -> dict:
    defaults = {"name": "Neighbor Ned", "billing_email": "n@farm.test",
                "rate_per_acre_cents": 1200, "credit_limit_cents": 100000}
    defaults.update(overrides)
    return create_customer(**defaults)


def create_field(customer_id: str, **overrides) -> dict:
    """Create a field as its owning Grower (ownership-gated call)."""
    return get_success_data(api_client.create_field(
        create_field_payload(customer_id, **overrides), make_grower_headers(customer_id)))


def create_product(**overrides) -> dict:
    return get_success_data(api_client.create_product(create_product_payload(**overrides), ADMIN))


def create_product_p2(**overrides) -> dict:
    return get_success_data(api_client.create_product(create_product_p2_payload(**overrides), ADMIN))


def create_compatibility_rule(product_a_id: str, product_b_id: str, verdict: str, **overrides) -> dict:
    return get_success_data(api_client.create_compatibility_rule(
        create_compatibility_rule_payload(product_a_id, product_b_id, verdict, **overrides), ADMIN))


def create_prescription(field_id: str, lines: list, **overrides) -> dict:
    """Create a DRAFT prescription as an Agronomist."""
    return get_success_data(api_client.create_prescription(
        create_prescription_payload(field_id, lines, **overrides), AGRONOMIST))


def approve_prescription(prescription: dict) -> dict:
    """Approve a DRAFT prescription, fetching the parent Field's live version
    first so the OCC expected_field_version is fresh."""
    field = get_success_data(api_client.get_field(prescription["field_id"], ADMIN))
    return get_success_data(api_client.approve_prescription(
        prescription["id"], {"expected_field_version": field["version"]}, AGRONOMIST))


def create_applicator(**overrides) -> dict:
    return get_success_data(api_client.create_applicator(create_applicator_payload(**overrides), ADMIN))


def create_equipment(**overrides) -> dict:
    return get_success_data(api_client.create_equipment(create_equipment_payload(**overrides), ADMIN))


def post_calibration(equipment_id: str, applicator_id: str,
                     target_gpa: float = 20.0, measured_gpa: float = 20.5) -> dict:
    """Post a calibration record as the given applicator (X-User-ID taken)."""
    return get_success_data(api_client.create_calibration_record(
        create_calibration_record_payload(equipment_id, target_gpa=target_gpa,
                                          measured_gpa=measured_gpa),
        make_applicator_headers(applicator_id)))


def post_weather(applicator_id: str = None, **overrides) -> dict:
    """Post a weather observation; defaults to a passing, fresh-envelope reading."""
    headers = (make_applicator_headers(applicator_id) if applicator_id
               else DISPATCHER)
    return get_success_data(api_client.create_weather_observation(
        create_weather_observation_payload(**overrides), headers))


def create_work_order(customer_id: str, field_id: str, prescription_id: str, **overrides) -> dict:
    """Create a DRAFT work order as its owning Grower (ownership-gated call)."""
    return get_success_data(api_client.create_work_order(
        create_work_order_payload(customer_id, field_id, prescription_id, **overrides),
        make_grower_headers(customer_id)))


def schedule_work_order(work_order_id: str, applicator_id: str, equipment_id: str, **overrides):
    """Raw schedule response (may be an error) — for gate tests."""
    return api_client.schedule_work_order(
        work_order_id,
        schedule_work_order_payload(applicator_id, equipment_id, **overrides),
        DISPATCHER)


def must_schedule(work_order_id: str, applicator_id: str, equipment_id: str, **overrides) -> dict:
    return get_success_data(schedule_work_order(work_order_id, applicator_id, equipment_id, **overrides))


def start_work_order(work_order_id: str, applicator_id: str):
    """Raw start response as the assigned applicator."""
    return api_client.start_work_order(work_order_id, make_applicator_headers(applicator_id))


def must_start(work_order_id: str, applicator_id: str) -> dict:
    return get_success_data(start_work_order(work_order_id, applicator_id))


def complete_work_order(work_order_id: str, applicator_id: str, lines: list):
    """Raw complete response as the assigned applicator."""
    return api_client.complete_work_order(work_order_id, {"lines": lines},
                                          make_applicator_headers(applicator_id))


def get_record_for_work_order(work_order_id: str) -> dict:
    """The 1:1 ApplicationRecord, discovered via the work_order_id filter (PRD §3.6)."""
    data, meta = validate_paginated(api_client.list_application_records(
        COMPLIANCE, params={"work_order_id": work_order_id}))
    assert len(data) == 1, f"expected exactly one ApplicationRecord for {work_order_id}"
    return data[0]


def get_invoice_for_work_order(work_order_id: str) -> dict:
    """The 1:1 Invoice, discovered via the work_order_id filter (PRD §3.9)."""
    data, meta = validate_paginated(api_client.list_invoices(
        ADMIN, params={"work_order_id": work_order_id}))
    assert len(data) == 1, f"expected exactly one Invoice for {work_order_id}"
    return data[0]


def certify_record(record_id: str, certifier_headers=None) -> dict:
    return get_success_data(api_client.certify_application_record(
        record_id, certifier_headers or COMPLIANCE))


def file_and_open_complaint(work_order_id: str, complainant_customer_id: str,
                            severity: str = "MINOR", description: str = "drift report") -> dict:
    """Grower files a complaint; ComplianceOfficer opens the investigation."""
    complaint = get_success_data(api_client.create_drift_complaint(
        create_drift_complaint_payload(work_order_id, severity=severity, description=description),
        make_grower_headers(complainant_customer_id)))
    return get_success_data(api_client.open_complaint_investigation(complaint["id"], COMPLIANCE))


def substantiate(complaint_id: str, findings_note: str = "confirmed") -> dict:
    return get_success_data(api_client.substantiate_complaint(
        complaint_id, {"findings_note": findings_note}, COMPLIANCE))


# ---------------------------------------------------------------------------
# Tier 1/2: the standard spray scenario
# ---------------------------------------------------------------------------

def base_environment(num_products: int = 2, customer_overrides: dict = None,
                     field_overrides: dict = None, applicator_overrides: dict = None,
                     equipment_overrides: dict = None, calibrate: bool = True,
                     with_work_order: bool = True, acres_to_treat=100,
                     prescription_overrides: dict = None,
                     approve: bool = True) -> dict:
    """Customer + field + product(s) + prescription (+ approval) + applicator
    + equipment (+ PASS calibration) + DRAFT work order.

    Standard literals: rate 1200c/acre, credit 2000000c; field 100 acres CORN
    buffer 300ft; P1 HERBICIDE rei24 wind10 40-85F buffer100 5000c+10%;
    P2 FUNGICIDE rei48 wind15 50-90F buffer0 2500c+20%; RX 2026 window
    2026-05-01..2026-06-30 carrier 12gpa P1@1.5 (+P2@0.4); applicator licensed
    [HERBICIDE, FUNGICIDE] through 2027-01-01; sprayer 400 gal.
    """
    env = {}
    cust = create_customer(**(customer_overrides or {}))
    env["customer"] = cust
    field = create_field(cust["id"], **(field_overrides or {}))
    env["field"] = field

    p1 = create_product()
    env["p1"] = p1
    p2 = None
    if num_products >= 2:
        p2 = create_product_p2()
        env["p2"] = p2

    lines = [{"product_id": p1["id"], "rate_per_acre": 1.5}]
    if p2 is not None:
        lines.append({"product_id": p2["id"], "rate_per_acre": 0.4})
    rx = create_prescription(field["id"], lines, **(prescription_overrides or {}))
    env["prescription"] = rx
    if approve:
        env["prescription"] = approve_prescription(rx)

    ap = create_applicator(**(applicator_overrides if applicator_overrides is not None else {}))
    env["applicator"] = ap
    eq = create_equipment(**(equipment_overrides or {}))
    env["equipment"] = eq
    if calibrate:
        env["calibration"] = post_calibration(eq["id"], ap["id"])

    if with_work_order:
        wo = create_work_order(cust["id"], field["id"], env["prescription"]["id"],
                               acres_to_treat=acres_to_treat)
        env["work_order"] = wo
    return env


def scheduled_environment(**kwargs) -> dict:
    """base_environment + the work order scheduled in the standard window."""
    start = kwargs.pop("scheduled_start", C.WO_SCHEDULED_START)
    end = kwargs.pop("scheduled_end", C.WO_SCHEDULED_END)
    env = base_environment(**kwargs)
    env["work_order"] = must_schedule(env["work_order"]["id"],
                                      env["applicator"]["id"], env["equipment"]["id"],
                                      scheduled_start=start, scheduled_end=end)
    return env


def in_progress_environment(**kwargs) -> dict:
    """scheduled_environment + fresh passing weather + clock at start + started."""
    start_at = kwargs.pop("start_at", C.WO_STARTED_AT)
    weather_at = kwargs.pop("weather_at", C.WEATHER_OBSERVED_AT)
    env = scheduled_environment(**kwargs)
    post_weather(env["applicator"]["id"], observed_at=weather_at)
    set_clock(start_at)
    env["work_order"] = must_start(env["work_order"]["id"], env["applicator"]["id"])
    return env


def completed_environment(actual_rates=None, complete_at: str = C.WO_COMPLETED_AT, **kwargs) -> dict:
    """in_progress_environment + completion with actual rates; adds
    record / invoice discovered via their work_order_id filters."""
    env = in_progress_environment(**kwargs)
    lines = []
    p1_rate = (actual_rates or {}).get("p1", 1.5)
    lines.append({"product_id": env["p1"]["id"], "actual_rate_per_acre": p1_rate})
    if env.get("p2") is not None:
        p2_rate = (actual_rates or {}).get("p2", 0.4)
        lines.append({"product_id": env["p2"]["id"], "actual_rate_per_acre": p2_rate})
    set_clock(complete_at)
    env["work_order"] = get_success_data(
        complete_work_order(env["work_order"]["id"], env["applicator"]["id"], lines))
    env["record"] = get_record_for_work_order(env["work_order"]["id"])
    env["invoice"] = get_invoice_for_work_order(env["work_order"]["id"])
    return env


def certified_environment(**kwargs) -> dict:
    """completed_environment + the application record CERTIFIED."""
    env = completed_environment(**kwargs)
    env["record"] = certify_record(env["record"]["id"])
    env["invoice"] = get_success_data(api_client.get_invoice(env["invoice"]["id"], ADMIN))
    return env
