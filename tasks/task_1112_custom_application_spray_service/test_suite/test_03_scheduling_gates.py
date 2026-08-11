"""The scheduling gauntlet: linked-state, safety, temporal, and fiscal gates."""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    create_customer, create_neighbor_customer, create_field, create_product,
    create_product_p2, create_prescription, approve_prescription,
    create_applicator, create_equipment, post_calibration, create_work_order,
    create_work_order_payload, create_compatibility_rule,
    schedule_work_order, must_schedule, base_environment,
    make_grower_headers,
    EXPECTED, TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]
AGRONOMIST = TEST_USERS["agronomist_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]

START = "2026-05-10T08:00:00Z"
END = "2026-05-10T11:00:00Z"


def test_schedule_blocked_by_draft_prescription(api):
    """PRD §3.4: "The referenced prescription must be `APPROVED`, else
    `ERR_PRESCRIPTION_NOT_APPROVED`."

    Design: Difficulty/cross_entity_state_dependency/schedule_blocked_by_draft_prescription
    """
    env = base_environment(approve=False)
    wo = env["work_order"]
    res = schedule_work_order(wo["id"], env["applicator"]["id"], env["equipment"]["id"],
                              scheduled_start=START, scheduled_end=END)
    validate_error(res, "ERR_PRESCRIPTION_NOT_APPROVED", expected_status=409)
    wo_after = validate_success(api.get_work_order(wo["id"], DISPATCHER), 200)
    assert wo_after["status"] == "DRAFT", "rejected schedule leaves the work order DRAFT"


def test_schedule_blocked_by_superseded_prescription(api):
    """PRD §3.4: "The referenced prescription must be `APPROVED`, else
    `ERR_PRESCRIPTION_NOT_APPROVED`."
    PRD §3.2: "Any other `APPROVED` prescription for the same field and
    `season_year` is automatically moved to `SUPERSEDED`"

    Design: Difficulty/cross_entity_state_dependency/schedule_blocked_by_draft_prescription
    """
    env = base_environment()  # RX approved
    rx1 = env["prescription"]
    # A second prescription for the same field+season wins approval, superseding RX1.
    rx2 = create_prescription(env["field"]["id"],
                              [{"product_id": env["p1"]["id"], "rate_per_acre": 2.0}],
                              carrier_gpa=15)
    approve_prescription(rx2)
    rx1_after = validate_success(api_client.get_prescription(rx1["id"], ADMIN), 200)
    assert rx1_after["status"] == "SUPERSEDED"

    res = schedule_work_order(env["work_order"]["id"], env["applicator"]["id"],
                              env["equipment"]["id"],
                              scheduled_start=START, scheduled_end=END)
    validate_error(res, "ERR_PRESCRIPTION_NOT_APPROVED", expected_status=409)


def test_conditional_pair_requires_adjuvant_at_schedule(api):
    """PRD §3.4: "if any pair is ruled `CONDITIONAL`, the payload must set
    `uses_adjuvant` true, else `ERR_ADJUVANT_REQUIRED`."
    PRD §3.1: "A `CONDITIONAL` verdict means the pair may run only when the
    work order's tank mix includes the required adjuvant, signaled by
    `uses_adjuvant`"

    Design: Corner/validations/conditional_pair_requires_adjuvant_at_schedule
    """
    env = base_environment()
    create_compatibility_rule(env["p1"]["id"], env["p2"]["id"], "CONDITIONAL",
                              note="needs adjuvant")
    wo = env["work_order"]
    res = schedule_work_order(wo["id"], env["applicator"]["id"], env["equipment"]["id"],
                              scheduled_start=START, scheduled_end=END, uses_adjuvant=False)
    validate_error(res, "ERR_ADJUVANT_REQUIRED", expected_status=409)

    scheduled = must_schedule(wo["id"], env["applicator"]["id"], env["equipment"]["id"],
                              scheduled_start=START, scheduled_end=END, uses_adjuvant=True)
    assert scheduled["status"] == "SCHEDULED"
    assert scheduled["uses_adjuvant"] is True


def test_schedule_with_expired_license_rejected(api):
    """PRD §3.4: "The applicator's `license_expires_on` must be on or after
    `scheduled_end`, else `ERR_LICENSE_EXPIRED`."

    Design: Corner/validations/schedule_with_expired_license_rejected
    """
    env = base_environment(num_products=1,
                           applicator_overrides={"display_name": "Ed Expiring",
                                                 "license_no": "L-900",
                                                 "license_expires_on": "2026-05-09T00:00:00Z",
                                                 "license_categories": ["HERBICIDE"]})
    res = schedule_work_order(env["work_order"]["id"], env["applicator"]["id"],
                              env["equipment"]["id"], scheduled_start=START, scheduled_end=END)
    validate_error(res, "ERR_LICENSE_EXPIRED", expected_status=409)


def test_schedule_with_missing_license_category_rejected(api):
    """PRD §3.4: "The applicator's `license_categories` must cover every
    product `category` appearing in the prescription's lines, else
    `ERR_LICENSE_CATEGORY_MISSING`."

    Design: Corner/validations/schedule_with_missing_license_category_rejected
    """
    env = base_environment(num_products=2,
                           applicator_overrides={"display_name": "Herb Only",
                                                 "license_no": "L-300",
                                                 "license_categories": ["HERBICIDE"]})
    res = schedule_work_order(env["work_order"]["id"], env["applicator"]["id"],
                              env["equipment"]["id"], scheduled_start=START, scheduled_end=END)
    validate_error(res, "ERR_LICENSE_CATEGORY_MISSING", expected_status=409)


def test_schedule_with_uncalibrated_equipment_rejected(api):
    """PRD §3.4: "The sprayer must be `AVAILABLE` with a
    `calibration_valid_until` that is non-null and on or after `scheduled_end`,
    else `ERR_CALIBRATION_OVERDUE`."

    Design: Corner/validations/schedule_with_uncalibrated_equipment_rejected
    """
    env = base_environment(num_products=1, calibrate=False)
    res = schedule_work_order(env["work_order"]["id"], env["applicator"]["id"],
                              env["equipment"]["id"], scheduled_start=START, scheduled_end=END)
    validate_error(res, "ERR_CALIBRATION_OVERDUE", expected_status=409)


def test_schedule_outside_prescription_window_rejected(api):
    """PRD §3.4: "The window must sit inside the prescription's validity:
    `scheduled_start` on or after `valid_from` and `scheduled_end` on or before
    `valid_to`, else `ERR_OUTSIDE_APPLICATION_WINDOW`"

    Design: Corner/validations/schedule_outside_prescription_window_rejected
    """
    env = base_environment(num_products=1)
    res = schedule_work_order(env["work_order"]["id"], env["applicator"]["id"],
                              env["equipment"]["id"],
                              scheduled_start="2026-04-30T08:00:00Z",
                              scheduled_end="2026-04-30T11:00:00Z")
    validate_error(res, "ERR_OUTSIDE_APPLICATION_WINDOW", expected_status=409)


def test_schedule_with_inverted_window_returns_validation_error(api):
    """PRD §3.4: "a range whose start is not strictly before its end is
    malformed, `ERR_VALIDATION`."

    Design: Corner/entities/schedule_with_inverted_window_returns_invalid_request
    """
    env = base_environment()
    res = schedule_work_order(env["work_order"]["id"], env["applicator"]["id"],
                              env["equipment"]["id"],
                              scheduled_start="2026-05-10T11:00:00Z",
                              scheduled_end="2026-05-10T08:00:00Z")
    validate_error(res, "ERR_VALIDATION", expected_status=400)


def test_work_order_acreage_exceeds_field_rejected(api):
    """PRD §3.4: "The acreage must be positive (a non-positive value is a
    body-shape failure, `ERR_VALIDATION`) and may not exceed the field's total
    `acres` — overshooting the field is rejected with `ERR_ACREAGE_EXCEEDED`."

    Design: Corner/validations/work_order_acreage_exceeds_field_rejected
    """
    env = base_environment(num_products=1, with_work_order=False)
    res = api_client.create_work_order(
        create_work_order_payload(env["customer"]["id"], env["field"]["id"],
                                  env["prescription"]["id"], acres_to_treat=150),
        make_grower_headers(env["customer"]["id"]))
    validate_error(res, "ERR_ACREAGE_EXCEEDED", expected_status=409)


def test_schedule_over_credit_limit_rejected(api):
    """PRD §3.4: "Finally, the fiscal gate of §2.10: the customer's
    `outstanding_cents` plus this job's `estimated_total_cents` must not exceed
    `credit_limit_cents`, else `ERR_CREDIT_LIMIT_EXCEEDED`."

    Design: Corner/validations/schedule_over_credit_limit_rejected
    """
    env = base_environment(customer_overrides={"name": "Thin Credit",
                                               "billing_email": "t@farm.test",
                                               "credit_limit_cents": 500000})
    res = schedule_work_order(env["work_order"]["id"], env["applicator"]["id"],
                              env["equipment"]["id"], scheduled_start=START, scheduled_end=END)
    validate_error(res, "ERR_CREDIT_LIMIT_EXCEEDED", expected_status=409)


def test_temporal_conflict_beats_credit_breach_on_schedule(api):
    """PRD §2.9: "When several checks could reject the same request, the server
    evaluates them in a fixed precedence order so the reported failure is
    deterministic." — temporal windows and interval conflicts (category 8,
    surfacing `ERR_APPLICATOR_TIME_CONFLICT`) are evaluated before the fiscal
    limit (category 10, surfacing `ERR_CREDIT_LIMIT_EXCEEDED`).

    Design: Difficulty/priority_pair_validation_conflict/temporal_beats_fiscal_on_schedule
    """
    env = base_environment(customer_overrides={"credit_limit_cents": 2000000})
    # First job occupies AP1 08:00-11:00 on the first customer's field.
    must_schedule(env["work_order"]["id"], env["applicator"]["id"], env["equipment"]["id"],
                  scheduled_start=START, scheduled_end=END)

    # Second customer with a near-zero credit limit, own field + approved RX.
    c2 = create_neighbor_customer(name="Broke Brook", billing_email="b@farm.test",
                                  credit_limit_cents=100)
    f2 = create_field(c2["id"], label="Brook 5", crop="SOY")
    rx2 = create_prescription(f2["id"], [
        {"product_id": env["p1"]["id"], "rate_per_acre": 1.5},
        {"product_id": env["p2"]["id"], "rate_per_acre": 0.4},
    ])
    approve_prescription(rx2)
    eq2 = create_equipment(unit_label="Sprayer-2")
    post_calibration(eq2["id"], env["applicator"]["id"])
    wo2 = create_work_order(c2["id"], f2["id"], rx2["id"], acres_to_treat=100)

    # 10:00-13:00 with AP1 both pads into the 08:00-11:00 job AND breaches credit.
    res = schedule_work_order(wo2["id"], env["applicator"]["id"], eq2["id"],
                              scheduled_start="2026-05-10T10:00:00Z",
                              scheduled_end="2026-05-10T13:00:00Z")
    validate_error(res, "ERR_APPLICATOR_TIME_CONFLICT", expected_status=409)


def test_window_violation_beats_credit_breach_on_schedule(api):
    """PRD §2.9: "When several checks could reject the same request, the server
    evaluates them in a fixed precedence order so the reported failure is
    deterministic." — temporal windows and interval conflicts (category 8,
    surfacing `ERR_OUTSIDE_APPLICATION_WINDOW`) are evaluated before the fiscal
    limit (category 10, surfacing `ERR_CREDIT_LIMIT_EXCEEDED`).
    PRD §2.9: "a credit-limit breach is only ever reported after every safety,
    temporal, and domain constraint has passed."

    Design: Difficulty/priority_pair_validation_conflict/temporal_beats_fiscal_on_schedule
    """
    c2 = create_neighbor_customer(name="Broke Brook", billing_email="b@farm.test",
                                  credit_limit_cents=100)
    f2 = create_field(c2["id"], label="Brook 5", crop="SOY")
    p1 = create_product()
    rx2 = create_prescription(f2["id"], [{"product_id": p1["id"], "rate_per_acre": 1.5}])
    approve_prescription(rx2)
    ap = create_applicator(license_categories=["HERBICIDE"])
    eq = create_equipment()
    post_calibration(eq["id"], ap["id"])
    wo2 = create_work_order(c2["id"], f2["id"], rx2["id"], acres_to_treat=100)

    # Window before valid_from AND credit breach: the temporal error wins.
    res = schedule_work_order(wo2["id"], ap["id"], eq["id"],
                              scheduled_start="2026-04-30T08:00:00Z",
                              scheduled_end="2026-04-30T11:00:00Z")
    validate_error(res, "ERR_OUTSIDE_APPLICATION_WINDOW", expected_status=409)


def test_schedule_response_immediately_reflects_effects(api):
    """PRD §3.4: "When the gauntlet passes, the schedule writes
    `applicator_id`, `equipment_id`, `scheduled_start`, `scheduled_end`, and
    `uses_adjuvant` onto the order, computes `estimated_total_cents` as the
    provisional invoice amount described next, and increments the WorkOrder's
    `version`."
    PRD §2.2: "Unless otherwise noted, operations that create or modify a
    resource will return the created or updated resource object in the data
    field."

    Design: Corner/consistency_model/schedule_response_immediately_reflects_effects
    """
    env = base_environment()
    scheduled = must_schedule(env["work_order"]["id"], env["applicator"]["id"],
                              env["equipment"]["id"],
                              scheduled_start=START, scheduled_end=END)
    assert scheduled["status"] == "SCHEDULED"
    assert scheduled["applicator_id"] == env["applicator"]["id"]
    assert scheduled["equipment_id"] == env["equipment"]["id"]
    assert scheduled["estimated_total_cents"] == EXPECTED["PROVISIONAL_100AC"], \
        f"expected provisional 1065000, got {scheduled['estimated_total_cents']}"
