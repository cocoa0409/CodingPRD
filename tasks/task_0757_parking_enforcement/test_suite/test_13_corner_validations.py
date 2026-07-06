"""Corner section: validations (fiscal bounds, field-level, boot-already-active)."""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    make_enforcement_officer_headers,
    setup_issuing_context,
    issue_in_context,
    create_officer,
    create_beat,
    setup_boot_eligible_vehicle,
)

SUPERVISOR = TEST_USERS["supervisor_headers"]
MOTORIST = TEST_USERS["motorist_headers"]


def test_payment_amount_exceeds_due_returns_mismatch(api):
    """PRD §3.5: "The amount must be at least 1 cent and no greater than the
    citation's current `amount_due_cents` at the moment of creation; an amount
    outside that range is rejected with `ERR_PAYMENT_AMOUNT_MISMATCH`."

    Design: Corner/validations/payment_amount_exceeds_due_returns_mismatch
    """
    ctx = setup_issuing_context(base_fine_cents=5000, code="EXP_METER")
    cit = issue_in_context(ctx)  # fine 5000, amount_due 5000
    validate_error(
        api.create_payment(
            {"citation_id": cit["id"], "amount_cents": 6000, "method": "CARD"}, MOTORIST),
        ApiErrorId.ERR_PAYMENT_AMOUNT_MISMATCH.value)


def test_adjustment_exceeds_balance_returns_error(api):
    """PRD §3.7: "The waiver amount must not exceed that citation's current
    `amount_due_cents`; an excessive waiver is rejected with
    `ERR_ADJUSTMENT_EXCEEDS_BALANCE`."

    Design: Corner/validations/adjustment_exceeds_balance_returns_error
    """
    ctx = setup_issuing_context(base_fine_cents=5000, code="EXP_METER")
    cit = issue_in_context(ctx)  # amount_due 5000
    vid = ctx["vehicle"]["id"]
    version = validate_success(api.get_vehicle(vid, SUPERVISOR))["version"]
    validate_error(
        api.create_adjustment(
            vid,
            {"citation_id": cit["id"], "waive_amount_cents": 6000,
             "expected_vehicle_version": version}, SUPERVISOR),
        ApiErrorId.ERR_ADJUSTMENT_EXCEEDS_BALANCE.value)


def test_shift_end_before_start_returns_validation(api):
    """PRD §3.2: "Opening a shift names the working `officer_id`, the `beat_id` being
    patrolled, and the shift window as `scheduled_start` and `scheduled_end`, where
    `scheduled_end` must be strictly later than `scheduled_start`."

    Design: Corner/validations/shift_end_before_start_returns_validation
    """
    officer = create_officer(badge_number="B-VA3")
    beat = create_beat(patrol_zone="RESIDENTIAL", beat_code="VAB3")
    validate_error(
        api.create_shift(
            {"officer_id": officer["id"], "beat_id": beat["id"],
             "scheduled_start": "2026-03-02T12:00:00Z",
             "scheduled_end": "2026-03-02T08:00:00Z"},
            make_enforcement_officer_headers(officer["id"])),
        ApiErrorId.ERR_VALIDATION.value)


def test_boot_already_active_returns_error(api):
    """PRD §3.8: "Only one active order may exist per vehicle: if an order in `status`
    `ORDERED` or `APPLIED` already exists for it, a new one is rejected with
    `ERR_BOOT_ALREADY_ACTIVE`."

    Design: Corner/validations/boot_already_active_returns_error
    """
    ctx = setup_boot_eligible_vehicle()  # has an auto ORDERED boot
    validate_error(
        api.create_boot_tow_order(
            {"vehicle_id": ctx["vehicle"]["id"], "order_type": "TOW"}, SUPERVISOR),
        ApiErrorId.ERR_BOOT_ALREADY_ACTIVE.value)
