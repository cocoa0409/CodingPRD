"""Business-rule validations: billing amount, Rx signing/PECOS gates, duplicate
milestone, repair-on-undelivered, appeal outcome, and FK existence.

Covers Queue B (Corner) section: validations. The kx_without_auth instance is an
excluded_because stub (owned by Difficulty/combinatorial_formula/
claim_line_allowed_modifier_branch_mode_a) and is intentionally not translated here.
"""
from test_helpers import validate_success, validate_error
from test_helpers.test_users import TEST_USERS, make_physician_headers, make_practitioner_headers
from test_helpers.constants import NONEXISTENT_UUID
from test_helpers.factories import (
    create_claim_line_payload, create_milestone_payload, create_device_order_payload,
    create_repair_request_payload,
)
from test_helpers.fixtures import (
    setup_order_at_intake, set_clock, create_physician, create_supplier, create_patient,
    create_signed_prescription, setup_denied_appealed_line,
)


def test_claim_line_zero_units_rejected(api):
    """PRD §3.6: "A claim line whose `billed_units` is below 1 or whose
    `fee_schedule_cents` is below 0 is rejected at creation with
    `ERR_INVALID_BILLING_AMOUNT`."

    Design: Corner/validations/claim_line_negative_billing_amount_rejected
    """
    cast = setup_order_at_intake()
    res = api.create_claim_line(
        create_claim_line_payload(cast["ord_id"], l_code="L1960", modifier="NONE",
                                  billed_units=0, fee_schedule_cents=30000),
        TEST_USERS["billing_headers"])
    validate_error(res, "ERR_INVALID_BILLING_AMOUNT")


def test_order_against_unsigned_rx_rejected(api):
    """PRD §3.3: "The prescription's `status` must be `SIGNED` — ordering against a
    prescription that is `DRAFT`, `VOIDED`, `CONSUMED`, or `EXPIRED` is rejected with
    `ERR_RX_NOT_SIGNED`."

    Design: Corner/validations/order_against_unsigned_rx_rejected
    """
    set_clock("2026-06-01T00:00:00Z")
    rx_phys = create_physician(pecos=True, npi="1111111111", name="Dr Rx")
    fit = create_physician(pecos=True, npi="2222222222", name="Tech Fit")
    supplier = create_supplier()
    patient = create_patient(medicare=False)
    # DRAFT (never signed) but in-window Rx (face_to_face 2026-05-20).
    rx = create_signed_prescription(patient["id"], rx_phys["id"],
                                    "LOWER_EXTREMITY_ORTHOSIS", "M21.6X1",
                                    face_to_face_date="2026-05-20", sign=False)
    res = api.create_device_order(
        create_device_order_payload(rx["id"], supplier["id"], fit["id"]),
        TEST_USERS["billing_headers"])
    validate_error(res, "ERR_RX_NOT_SIGNED")


def test_medicare_order_non_pecos_physician_rejected(api):
    """PRD §3.3: "When the patient's payer is Medicare, the prescribing physician's
    `pecos_enrolled` must be true at creation, or the order is rejected with
    `ERR_PHYSICIAN_NOT_PECOS`."

    Design: Corner/validations/medicare_order_non_pecos_physician_rejected
    """
    set_clock("2026-06-01T00:00:00Z")
    rx_phys = create_physician(pecos=False, npi="1111111111", name="Dr NoPecos")
    fit = create_physician(pecos=True, npi="2222222222", name="Tech Fit")
    supplier = create_supplier()
    patient = create_patient(medicare=True)
    rx = create_signed_prescription(patient["id"], rx_phys["id"],
                                    "LOWER_EXTREMITY_ORTHOSIS", "M21.6X1",
                                    face_to_face_date="2026-05-20")
    res = api.create_device_order(
        create_device_order_payload(rx["id"], supplier["id"], fit["id"]),
        TEST_USERS["billing_headers"])
    validate_error(res, "ERR_PHYSICIAN_NOT_PECOS")


def test_duplicate_milestone_step_rejected(api):
    """PRD §3.4: "Each step may appear at most once per order; a duplicate step is
    rejected with `ERR_DUPLICATE_MILESTONE`."

    Design: Corner/validations/duplicate_milestone_step_rejected
    """
    cast = setup_order_at_intake()
    validate_success(api.create_milestone(
        cast["ord_id"], create_milestone_payload(step="ASSEMBLY", weight=3),
        make_practitioner_headers(cast["fit_id"])), 201)
    res = api.create_milestone(
        cast["ord_id"], create_milestone_payload(step="ASSEMBLY", weight=2),
        make_practitioner_headers(cast["fit_id"]))
    validate_error(res, "ERR_DUPLICATE_MILESTONE")


def test_repair_on_undelivered_order_rejected(api):
    """PRD §3.7: "An adjustment or repair may only be created against an order that is in
    `DELIVERED` status; an attempt against an order in any other status is rejected with
    `ERR_NOT_DELIVERED`."

    Design: Corner/validations/repair_on_undelivered_order_rejected
    """
    cast = setup_order_at_intake()  # INTAKE, never delivered
    res = api.create_repair_request(
        create_repair_request_payload(cast["ord_id"]),
        make_practitioner_headers(cast["fit_id"]))
    validate_error(res, "ERR_NOT_DELIVERED")


def test_appeal_decision_invalid_outcome_rejected(api):
    """PRD §3.6: "A `ComplianceOfficer` then records the appeal outcome by supplying an
    `outcome`; the outcome must be either `UPHELD` or `OVERTURNED`, and any other value is
    rejected with `ERR_INVALID_APPEAL_OUTCOME`."

    Design: Corner/validations/appeal_decision_invalid_outcome_rejected
    """
    cast, cl = setup_denied_appealed_line(fee_schedule_cents=30000)
    res = api.appeal_decision(cl["id"], {"outcome": "MAYBE"}, TEST_USERS["compliance_headers"])
    validate_error(res, "ERR_INVALID_APPEAL_OUTCOME")


def test_order_create_nonexistent_supplier_not_found(api):
    """PRD §3.10: "Resource existence is checked third, validating path identifiers
    left-to-right and then body foreign keys, with a miss yielding
    `ERR_RESOURCE_NOT_FOUND`."

    Design: Corner/validations/order_create_referential_mismatch_rejected
    """
    set_clock("2026-06-01T00:00:00Z")
    rx_phys = create_physician(pecos=True, npi="1111111111", name="Dr Rx")
    fit = create_physician(pecos=True, npi="2222222222", name="Tech Fit")
    patient = create_patient(medicare=False)
    rx = create_signed_prescription(patient["id"], rx_phys["id"],
                                    "LOWER_EXTREMITY_ORTHOSIS", "M21.6X1",
                                    face_to_face_date="2026-05-20")
    res = api.create_device_order(
        create_device_order_payload(rx["id"], NONEXISTENT_UUID, fit["id"]),
        TEST_USERS["billing_headers"])
    validate_error(res, "ERR_RESOURCE_NOT_FOUND")
