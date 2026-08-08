"""Validation-priority precedence pairs and the single-failure constraint rules.

Queue A (Difficulty): priority_pair_validation_conflict.
Queue B (Corner): validations.
"""
from test_helpers import (
    validate_error, get_success_data, ApiErrorId,
    register_host, register_tenant, create_unit, request_booking, confirm_booking,
    get_deposit_for_booking,
    setup_completed_booking,
    make_host_headers, make_tenant_headers, TEST_USERS,
    create_booking_payload,
)

REVIEWER = TEST_USERS["compliance_reviewer_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]


# --------------------------------------------------------------------------
# priority_pair_validation_conflict / confirm_state_beats_safety
# --------------------------------------------------------------------------

def test_confirm_declined_and_unverified_reports_invalid_state(api):
    """PRD §2.9: "When several checks could reject the same request, they are
    evaluated in a fixed priority order, and the error reported is the one
    belonging to the first failing check."
    PRD §2.9: "State legality — the target resource is in a state from which the
    requested transition is defined, else `ERR_INVALID_STATE` (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/confirm_state_beats_safety
    """
    host = register_host(api, verify_payout=True)
    tenant = register_tenant(api, verified=False, tenant_type="OTHER")
    unit = create_unit(api, host["id"], listed=True, cleaning_included=True, deposit_cents=0)
    booking = request_booking(api, unit["id"], tenant["id"], "2026-06-01", "2026-07-01")
    get_success_data(api.transition_booking(booking["id"], {"to_status": "DECLINED"}, make_host_headers(host["id"])))
    # State (pri 6) fails on the terminal DECLINED before tenant-verification (pri 7).
    resp = api.transition_booking(booking["id"], {"to_status": "CONFIRMED"}, make_host_headers(host["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_confirm_cancelled_and_unverified_reports_invalid_state(api):
    """PRD §2.9: "the error reported is the one belonging to the first failing
    check."
    PRD §2.9: "Tenant verification — a booking confirmation requires the tenant to
    be verified, else `ERR_TENANT_NOT_VERIFIED`."

    Design: Difficulty/priority_pair_validation_conflict/confirm_state_beats_safety
    """
    host = register_host(api, verify_payout=True)
    tenant = register_tenant(api, verified=False, tenant_type="OTHER")
    unit = create_unit(api, host["id"], listed=True, cleaning_included=True, deposit_cents=0)
    booking = request_booking(api, unit["id"], tenant["id"], "2026-06-01", "2026-07-01")
    get_success_data(api.transition_booking(booking["id"], {"to_status": "CANCELLED"}, make_tenant_headers(tenant["id"])))
    # A terminal CANCELLED booking with an unverified tenant still reports the
    # higher-priority state error, not ERR_TENANT_NOT_VERIFIED.
    resp = api.transition_booking(booking["id"], {"to_status": "CONFIRMED"}, make_host_headers(host["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


# --------------------------------------------------------------------------
# priority_pair_validation_conflict / confirm_constraint_beats_fiscal
# --------------------------------------------------------------------------

def test_confirm_draft_unit_beats_host_payout_fiscal(api):
    """PRD §2.9: "Term and listing constraints — unit listing status and
    term-length bounds, yielding `ERR_UNIT_NOT_LISTED`, `ERR_TERM_TOO_SHORT`, or
    `ERR_TERM_EXCEEDS_MAX` as applicable."
    PRD §2.9: "Fiscal constraints — host payout verification, damage-claim amount
    bounds, and payout segregation of duties, yielding
    `ERR_HOST_PAYOUT_NOT_VERIFIED`, `ERR_APPROVED_EXCEEDS_CLAIMED`,
    `ERR_APPROVED_EXCEEDS_HELD`, or `ERR_SEGREGATION_OF_DUTIES`."

    Design: Difficulty/priority_pair_validation_conflict/confirm_constraint_beats_fiscal
    """
    host = register_host(api, verify_payout=False)   # UNVERIFIED payout (fiscal, pri 11)
    tenant = register_tenant(api, verified=True)
    unit = create_unit(api, host["id"], listed=False, cleaning_included=True, deposit_cents=0)  # DRAFT (pri 8)
    booking = request_booking(api, unit["id"], tenant["id"], "2026-06-01", "2026-07-01")
    resp = api.transition_booking(booking["id"], {"to_status": "CONFIRMED"}, make_host_headers(host["id"]))
    validate_error(resp, ApiErrorId.ERR_UNIT_NOT_LISTED)


def test_confirm_suspended_unit_beats_host_payout_fiscal(api):
    """PRD §2.9: "the error reported is the one belonging to the first failing
    check."
    PRD §3.4: "The unit's `status` must be `LISTED` (otherwise
    `ERR_UNIT_NOT_LISTED`)."

    Design: Difficulty/priority_pair_validation_conflict/confirm_constraint_beats_fiscal
    """
    host = register_host(api, verify_payout=False)
    tenant = register_tenant(api, verified=True)
    unit = create_unit(api, host["id"], listed=True, cleaning_included=True, deposit_cents=0)
    booking = request_booking(api, unit["id"], tenant["id"], "2026-06-01", "2026-07-01")
    get_success_data(api.transition_unit(unit["id"], {"to_status": "SUSPENDED"}, make_host_headers(host["id"])))
    resp = api.transition_booking(booking["id"], {"to_status": "CONFIRMED"}, make_host_headers(host["id"]))
    validate_error(resp, ApiErrorId.ERR_UNIT_NOT_LISTED)


# --------------------------------------------------------------------------
# Corner / validations — single-failure scenarios
# --------------------------------------------------------------------------

def test_booking_end_before_start_rejected(api):
    """PRD §2.9: "Body well-formedness — required fields present, enum values
    legal, dates parseable, and a booking's `end_date` strictly later than its
    `start_date`, else `ERR_VALIDATION` (HTTP 422)."

    Design: Corner/validations/booking_end_before_start_rejected
    """
    host = register_host(api, verify_payout=False)
    tenant = register_tenant(api, verified=False)
    unit = create_unit(api, host["id"], listed=False, cleaning_included=True)
    resp = api.create_booking(
        create_booking_payload(unit["id"], tenant["id"], "2026-07-01", "2026-06-01"),
        make_tenant_headers(tenant["id"]))
    validate_error(resp, ApiErrorId.ERR_VALIDATION)


def test_booking_term_too_short_rejected(api):
    """PRD §3.3: "a term shorter than `min_term_days` is rejected with
    `ERR_TERM_TOO_SHORT`".

    Design: Corner/validations/booking_term_too_short_rejected
    """
    host = register_host(api, verify_payout=False)
    tenant = register_tenant(api, verified=False)
    unit = create_unit(api, host["id"], listed=False, cleaning_included=True, min_term_days=30)
    resp = api.create_booking(
        create_booking_payload(unit["id"], tenant["id"], "2026-06-01", "2026-06-21"),  # term 20
        make_tenant_headers(tenant["id"]))
    validate_error(resp, ApiErrorId.ERR_TERM_TOO_SHORT)


def test_booking_term_exceeds_max_rejected(api):
    """PRD §3.3: "a term longer than `max_term_days` is rejected with
    `ERR_TERM_EXCEEDS_MAX`".

    Design: Corner/validations/booking_term_exceeds_max_rejected
    """
    host = register_host(api, verify_payout=False)
    tenant = register_tenant(api, verified=False)
    unit = create_unit(api, host["id"], listed=False, cleaning_included=True, max_term_days=90)
    resp = api.create_booking(
        create_booking_payload(unit["id"], tenant["id"], "2026-06-01", "2026-09-29"),  # term 120
        make_tenant_headers(tenant["id"]))
    validate_error(resp, ApiErrorId.ERR_TERM_EXCEEDS_MAX)


def test_extension_not_later_rejected_at_approval(api):
    """PRD §3.7: "the `new_end_date` must be strictly later than the booking's
    current `end_date` (otherwise `ERR_EXTENSION_NOT_LATER`)".

    Design: Corner/validations/extension_not_later_rejected
    """
    host = register_host(api, verify_payout=True)
    tenant = register_tenant(api, verified=True)
    unit = create_unit(api, host["id"], listed=True, cleaning_included=True)
    booking = request_booking(api, unit["id"], tenant["id"], "2026-06-01", "2026-07-01")
    confirmed = confirm_booking(api, booking["id"], host["id"])
    ext = get_success_data(api.create_extension(
        {"booking_id": booking["id"], "expected_booking_version": confirmed["version"],
         "new_end_date": "2026-06-20"},
        make_tenant_headers(tenant["id"])))
    resp = api.transition_extension(ext["id"], {"to_status": "APPROVED"}, make_host_headers(host["id"]))
    validate_error(resp, ApiErrorId.ERR_EXTENSION_NOT_LATER)


def test_confirm_requires_coi_rejected(api):
    """PRD §3.4: "If the unit's `requires_coi` is true, there must exist a
    certificate of insurance for this booking that is `ACTIVE`, whose
    `coverage_cents` is at least the platform's minimum required coverage
    `COI_MIN_COVERAGE_CENTS`, and whose coverage window from `effective_start`
    through `effective_end` covers the booking's occupancy window; failing any of
    these the confirmation is rejected with `ERR_COI_REQUIRED`."

    Design: Corner/validations/confirm_requires_coi_rejected
    """
    host = register_host(api, verify_payout=True)
    tenant = register_tenant(api, verified=True)
    unit = create_unit(api, host["id"], listed=True, cleaning_included=True, requires_coi=True)
    booking = request_booking(api, unit["id"], tenant["id"], "2026-06-01", "2026-07-01")
    resp = api.transition_booking(booking["id"], {"to_status": "CONFIRMED"}, make_host_headers(host["id"]))
    validate_error(resp, ApiErrorId.ERR_COI_REQUIRED)


def test_coi_activate_insufficient_coverage_rejected(api):
    """PRD §3.5: "A `ComplianceReviewer` activates it, moving `PENDING` to
    `ACTIVE`, but only when its `coverage_cents` is at least the platform's minimum
    required coverage `COI_MIN_COVERAGE_CENTS`, which is `5000000` cents ($50,000)
    (otherwise `ERR_COI_INSUFFICIENT_COVERAGE`)".

    Design: Corner/validations/coi_activate_insufficient_coverage_rejected
    """
    host = register_host(api, verify_payout=False)
    tenant = register_tenant(api, verified=False)
    unit = create_unit(api, host["id"], listed=False, cleaning_included=True)
    booking = request_booking(api, unit["id"], tenant["id"], "2026-06-01", "2026-07-01")
    coi = get_success_data(api.create_coi_policy(
        {"booking_id": booking["id"], "coverage_cents": 1000000,
         "effective_start": "2026-05-01", "effective_end": "2026-08-01"},
        make_host_headers(host["id"])))
    resp = api.transition_coi_policy(coi["id"], {"to_status": "ACTIVE"}, REVIEWER)
    validate_error(resp, ApiErrorId.ERR_COI_INSUFFICIENT_COVERAGE)


def test_damage_approved_exceeds_claimed_rejected(api):
    """PRD §3.8: "the `approved_cents` must not exceed the claim's `claimed_cents`,
    else `ERR_APPROVED_EXCEEDS_CLAIMED`".

    Design: Corner/validations/damage_approved_exceeds_claimed_rejected
    """
    host = register_host(api, verify_payout=True)
    tenant = register_tenant(api, verified=True)
    unit = create_unit(api, host["id"], listed=True, cleaning_included=True, deposit_cents=150000)
    booking = request_booking(api, unit["id"], tenant["id"], "2026-06-01", "2026-07-01")
    confirm_booking(api, booking["id"], host["id"])
    deposit = get_deposit_for_booking(api, booking["id"])
    claim = get_success_data(api.create_damage_claim(
        {"deposit_id": deposit["id"], "expected_deposit_version": deposit["version"],
         "claimed_cents": 40000, "description": "chip"},
        make_host_headers(host["id"])))
    resp = api.transition_damage_claim(claim["id"], {"to_status": "APPROVED", "approved_cents": 50000}, REVIEWER)
    validate_error(resp, ApiErrorId.ERR_APPROVED_EXCEEDS_CLAIMED)


def test_damage_approved_exceeds_held_rejected(api):
    """PRD §3.8: "the `approved_cents` must not exceed the deposit's current
    `held_cents`, else `ERR_APPROVED_EXCEEDS_HELD`".

    Design: Corner/validations/damage_approved_exceeds_held_rejected
    """
    host = register_host(api, verify_payout=True)
    tenant = register_tenant(api, verified=True)
    unit = create_unit(api, host["id"], listed=True, cleaning_included=True, deposit_cents=30000)
    booking = request_booking(api, unit["id"], tenant["id"], "2026-06-01", "2026-07-01")
    confirm_booking(api, booking["id"], host["id"])
    deposit = get_deposit_for_booking(api, booking["id"])
    claim = get_success_data(api.create_damage_claim(
        {"deposit_id": deposit["id"], "expected_deposit_version": deposit["version"],
         "claimed_cents": 40000, "description": "door"},
        make_host_headers(host["id"])))
    resp = api.transition_damage_claim(claim["id"], {"to_status": "APPROVED", "approved_cents": 40000}, REVIEWER)
    validate_error(resp, ApiErrorId.ERR_APPROVED_EXCEEDS_HELD)


def test_settle_before_completion_rejected(api):
    """PRD §3.8: "A `ComplianceReviewer` settles a `HELD` deposit, which is
    permitted only once the booking is `COMPLETED` and no damage claim on the
    deposit is still open in `FILED` or `DISPUTED`; a premature settlement, or one
    attempted while an open claim exists, is rejected with
    `ERR_DEPOSIT_NOT_SETTLEABLE`."

    Design: Corner/validations/settle_before_completion_rejected
    """
    host = register_host(api, verify_payout=True)
    tenant = register_tenant(api, verified=True)
    unit = create_unit(api, host["id"], listed=True, cleaning_included=True, deposit_cents=100000)
    booking = request_booking(api, unit["id"], tenant["id"], "2026-06-01", "2026-07-01")
    confirm_booking(api, booking["id"], host["id"])  # booking only CONFIRMED, not COMPLETED
    deposit = get_deposit_for_booking(api, booking["id"])
    resp = api.settle_deposit(deposit["id"], REVIEWER)
    validate_error(resp, ApiErrorId.ERR_DEPOSIT_NOT_SETTLEABLE)


def test_claim_approve_after_settle_window_closed(api):
    """PRD §3.8: "the deposit must still be `HELD`, else `ERR_CLAIM_WINDOW_CLOSED`".

    Design: Corner/validations/claim_approve_after_settle_window_closed
    """
    ctx = setup_completed_booking(api, unit_overrides={"deposit_cents": 100000},
                                  start_date="2026-06-01", end_date="2026-07-01",
                                  activate_clock="2026-06-15", complete_clock="2026-07-01")
    host, booking = ctx["host"], ctx["booking"]
    deposit = get_deposit_for_booking(api, booking["id"])
    settled = get_success_data(api.settle_deposit(deposit["id"], REVIEWER))  # -> REFUNDED
    claim = get_success_data(api.create_damage_claim(
        {"deposit_id": deposit["id"], "expected_deposit_version": settled["version"],
         "claimed_cents": 20000, "description": "late"},
        make_host_headers(host["id"])))
    resp = api.transition_damage_claim(claim["id"], {"to_status": "APPROVED", "approved_cents": 20000}, REVIEWER)
    validate_error(resp, ApiErrorId.ERR_CLAIM_WINDOW_CLOSED)
