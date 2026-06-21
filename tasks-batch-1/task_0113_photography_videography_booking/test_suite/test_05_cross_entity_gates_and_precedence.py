"""Cross-entity confirmation gates (contract-signed, payment-status), and the
validation-precedence conflicts where a higher-priority check pre-empts a
lower-priority one.

Queue A (difficulty) instances exercised here:
  cross_entity_state_dependency / booking_confirm_requires_contract_signed
  cross_entity_state_dependency / shoot_complete_requires_booking_payment_status
  priority_pair_validation_conflict / confirm_state_beats_contract_not_signed
  priority_pair_validation_conflict / shooter_assign_stale_version_beats_double_booked
Queue B (corner) instances exercised here:
  validations / confirm_missing_model_release_returns_model_release_required
  validations / book_inactive_package_returns_package_inactive
  validations / settle_deposit_wrong_amount_returns_payment_amount_mismatch
  validations / create_booking_unknown_package_returns_invalid_reference
"""
from test_helpers import (
    validate_success, validate_error, get_success_data, api_client, TEST_USERS,
    ApiErrorId, make_client_headers, make_photographer_headers,
    # fixtures
    setup_draft_booking, setup_confirmed_booking, create_sent_contract,
    create_signed_contract, create_schedule, assign_second_shooter, set_clock,
    # factories
    create_booking_payload, create_payment_payload, second_shooter_assignment_payload,
    reschedule_payload, create_session_package_payload,
)

ADMIN = TEST_USERS["admin_headers"]


# ===========================================================================
# cross_entity_state_dependency / booking_confirm_requires_contract_signed
# ===========================================================================
def test_confirm_with_unsigned_contract_rejected(api):
    """PRD §3.4: "The booking's contract must exist and be SIGNED, or confirmation is
    rejected with ERR_CONTRACT_NOT_SIGNED."

    Contract is only SENT (not signed); confirm fails ERR_CONTRACT_NOT_SIGNED and the
    booking stays DRAFT.

    Design: Difficulty/cross_entity_state_dependency/booking_confirm_requires_contract_signed
    """
    base = setup_draft_booking()
    booking, client = base["booking"], base["client"]
    create_sent_contract(booking["id"])
    create_schedule(booking["id"], "2026-07-15T10:00:00Z", "2026-07-15T12:00:00Z")
    validate_error(
        api.confirm_booking(booking["id"], make_client_headers(client["id"])),
        ApiErrorId.ERR_CONTRACT_NOT_SIGNED.value,
    )
    booking_now = validate_success(api.get_booking(booking["id"], ADMIN))
    assert booking_now["workflow_status"] == "DRAFT"


def test_confirm_signed_contract_and_schedule_succeeds(api):
    """PRD §3.4: "The booking's contract must exist and be SIGNED ... A shoot schedule
    must already exist for the booking in SCHEDULED status. When all hold, confirmation
    recomputes total_fee_cents, pins deposit_due_cents, recomputes balance_due_cents, and
    bumps the booking's version."

    With the contract SIGNED and a SCHEDULED shoot, confirm succeeds (the gate is
    satisfied, the contrast case to the unsigned rejection).

    Design: Difficulty/cross_entity_state_dependency/booking_confirm_requires_contract_signed
    """
    base = setup_draft_booking()
    booking, client = base["booking"], base["client"]
    create_signed_contract(booking["id"], client["id"], includes_model_release=False)
    create_schedule(booking["id"], "2026-07-15T10:00:00Z", "2026-07-15T12:00:00Z")
    confirmed = validate_success(
        api.confirm_booking(booking["id"], make_client_headers(client["id"]))
    )
    assert confirmed["workflow_status"] == "CONFIRMED"


# ===========================================================================
# cross_entity_state_dependency / shoot_complete_requires_booking_payment_status
# ===========================================================================
def test_shoot_complete_requires_deposit_paid(api):
    """PRD §3.7: "Completion is permitted only when the schedule is SCHEDULED or
    RESCHEDULED, when the booking's payment_status is DEPOSIT_PAID or PAID_IN_FULL, and
    when the current time has reached or passed the window's end_utc ... a completion from
    a wrong state with ERR_INVALID_STATE."

    A CONFIRMED but UNPAID booking, shoot window already ended -> complete fails
    ERR_INVALID_STATE (payment-status precondition unmet) and the schedule stays SCHEDULED.

    Design: Difficulty/cross_entity_state_dependency/shoot_complete_requires_booking_payment_status
    """
    ctx = setup_confirmed_booking(
        start_utc="2026-07-02T10:00:00Z", end_utc="2026-07-02T12:00:00Z",
    )
    schedule, photographer = ctx["schedule"], ctx["photographer"]
    assert ctx["booking"]["payment_status"] == "UNPAID"
    set_clock("2026-07-02T12:30:00Z")
    validate_error(
        api.complete_shoot_schedule(schedule["id"], make_photographer_headers(photographer["id"])),
        ApiErrorId.ERR_INVALID_STATE.value,
    )
    schedule_now = validate_success(api.get_shoot_schedule(schedule["id"], ADMIN))
    assert schedule_now["status"] == "SCHEDULED"


def test_shoot_complete_after_deposit_paid_succeeds(api):
    """PRD §3.7: "Completion is permitted only when the schedule is SCHEDULED or
    RESCHEDULED, when the booking's payment_status is DEPOSIT_PAID or PAID_IN_FULL, and
    when the current time has reached or passed the window's end_utc."

    Same shape but with the deposit settled (DEPOSIT_PAID): the payment-status gate is
    satisfied and completion succeeds (booking -> SHOT).

    Design: Difficulty/cross_entity_state_dependency/shoot_complete_requires_booking_payment_status
    """
    from test_helpers import setup_deposit_paid_booking
    ctx = setup_deposit_paid_booking(
        start_utc="2026-07-02T10:00:00Z", end_utc="2026-07-02T12:00:00Z",
    )
    schedule, photographer, booking = ctx["schedule"], ctx["photographer"], ctx["booking"]
    set_clock("2026-07-02T12:30:00Z")
    completed = validate_success(
        api.complete_shoot_schedule(schedule["id"], make_photographer_headers(photographer["id"]))
    )
    assert completed["status"] == "COMPLETED"
    booking_now = validate_success(api.get_booking(booking["id"], ADMIN))
    assert booking_now["workflow_status"] == "SHOT"


# ===========================================================================
# priority_pair_validation_conflict / confirm_state_beats_contract_not_signed
# ===========================================================================
def test_reconfirm_confirmed_booking_state_check_wins(api):
    """PRD §2.7: "The legality of the requested state transition against the target's
    current state comes sixth (ERR_INVALID_STATE) ... Domain-specific business rules -
    the model-release gate, the signed-contract gate ... follow thereafter."

    Re-confirming an already-CONFIRMED booking fails the state precondition (sixth,
    ERR_INVALID_STATE) which outranks the contract-signed gate; the 409 wins.

    Design: Difficulty/priority_pair_validation_conflict/confirm_state_beats_contract_not_signed
    """
    ctx = setup_confirmed_booking(
        start_utc="2026-07-11T10:00:00Z", end_utc="2026-07-11T12:00:00Z",
    )
    booking, client = ctx["booking"], ctx["client"]
    validate_error(
        api.confirm_booking(booking["id"], make_client_headers(client["id"])),
        ApiErrorId.ERR_INVALID_STATE.value,
    )


def test_close_non_delivered_booking_state_check_wins(api):
    """PRD §3.8: "A StudioAdmin closes a booking, moving it DELIVERED -> CLOSED, which is
    permitted only when the booking is DELIVERED and its payment_status is PAID_IN_FULL;
    an attempt from any other state is rejected with ERR_INVALID_STATE."

    Closing a freshly CONFIRMED booking (neither DELIVERED nor PAID_IN_FULL) fails the
    state precondition first with ERR_INVALID_STATE — the state check pre-empts the
    payment-status gate.

    Design: Difficulty/priority_pair_validation_conflict/confirm_state_beats_contract_not_signed
    """
    ctx = setup_confirmed_booking(
        start_utc="2026-07-11T10:00:00Z", end_utc="2026-07-11T12:00:00Z",
    )
    booking = ctx["booking"]
    validate_error(
        api.close_booking(booking["id"], ADMIN),
        ApiErrorId.ERR_INVALID_STATE.value,
    )


# ===========================================================================
# priority_pair_validation_conflict / shooter_assign_stale_version_beats_double_booked
# ===========================================================================
def test_assign_stale_schedule_version_beats_double_booked(api):
    """PRD §2.7: "The optimistic-concurrency version check on the two guarded writes comes
    seventh (ERR_STALE_BOOKING_VERSION or ERR_STALE_SCHEDULE_VERSION). Domain-specific
    business rules - the model-release gate, the signed-contract gate, scheduling
    conflicts ... follow thereafter."

    A reschedule bumps schedule S's version. Re-assigning the same already-busy second
    shooter to S with the STALE pre-reschedule version would trip both the OCC check
    (seventh, ERR_STALE_SCHEDULE_VERSION, 412) and the double-booking check (later); the
    412 wins.

    Design: Difficulty/priority_pair_validation_conflict/shooter_assign_stale_version_beats_double_booked
    """
    client = get_success_data(api.create_client(
        {"email": "c10@studio.test", "full_name": "C Ten", "phone": "1000"}, ADMIN))
    lead_a = get_success_data(api.create_photographer(
        {"email": "lead10b@studio.test", "full_name": "Lead 10B", "skills": ["PHOTO"],
         "hourly_rate_cents": 12000}, ADMIN))
    lead_b = get_success_data(api.create_photographer(
        {"email": "lead10@studio.test", "full_name": "Lead 10", "skills": ["PHOTO"],
         "hourly_rate_cents": 12000}, ADMIN))
    second = get_success_data(api.create_photographer(
        {"email": "second10@studio.test", "full_name": "Second 10", "skills": ["PHOTO"],
         "hourly_rate_cents": 8000}, ADMIN))
    pkg = get_success_data(api.create_session_package(create_session_package_payload(
        name="Wedding 10", session_type="WEDDING", tier="STANDARD", base_fee_cents=200000,
        included_shoot_hours=6, overage_hourly_rate_cents=15000, included_edited_images=100,
        deposit_pct=0.30, requires_model_release=True, active=True), ADMIN))
    client_h = make_client_headers(client["id"])

    # Booking A: schedule overlapping window with second already assigned
    bk_a = get_success_data(api.create_booking(create_booking_payload(
        client["id"], pkg["id"], lead_a["id"], requested_shoot_hours=6), client_h))
    create_signed_contract(bk_a["id"], client["id"], includes_model_release=True)
    sch_a = get_success_data(api.create_shoot_schedule(
        {"booking_id": bk_a["id"], "start_utc": "2026-08-01T14:00:00Z",
         "end_utc": "2026-08-01T18:00:00Z"}, ADMIN))
    validate_success(api.confirm_booking(bk_a["id"], client_h))
    assign_second_shooter(sch_a["id"], second["id"], sch_a["version"])

    # Booking B: schedule S, capture its pre-reschedule version (stale value)
    bk_b = get_success_data(api.create_booking(create_booking_payload(
        client["id"], pkg["id"], lead_b["id"], requested_shoot_hours=6), client_h))
    create_signed_contract(bk_b["id"], client["id"], includes_model_release=True)
    sch_s = get_success_data(api.create_shoot_schedule(
        {"booking_id": bk_b["id"], "start_utc": "2026-08-10T09:00:00Z",
         "end_utc": "2026-08-10T11:00:00Z"}, ADMIN))
    stale_version = sch_s["version"]
    validate_success(api.confirm_booking(bk_b["id"], client_h))

    # Reschedule S into A's window -> bumps S.version (stale_version now out of date)
    get_success_data(api.reschedule_shoot_schedule(
        sch_s["id"],
        reschedule_payload("2026-08-01T15:00:00Z", "2026-08-01T17:00:00Z", "CLIENT_REQUEST"),
        ADMIN))

    # Trigger: assign the already-busy second shooter with the STALE version.
    validate_error(
        api.create_second_shooter_assignment(
            sch_s["id"],
            second_shooter_assignment_payload(second["id"], stale_version),
            ADMIN,
        ),
        ApiErrorId.ERR_STALE_SCHEDULE_VERSION.value,
    )


def test_assign_with_stale_schedule_version_after_reschedule_rejected(api):
    """PRD §2.6: "Assigning a second shooter to a shoot window requires
    expected_shoot_schedule_version in the request body, carrying the version of the
    ShootSchedule the client last observed. If the schedule's current version has advanced
    - most commonly because the window was rescheduled, which bumps the schedule's version
    - the assignment is rejected with ERR_STALE_SCHEDULE_VERSION (HTTP 412), since the
    billable window would otherwise be derived from a window that no longer exists."

    The seventh-priority OCC check (PRD §2.7) fires on its own: a reschedule bumps the
    schedule version, so an assignment carrying the pre-reschedule version is rejected
    ERR_STALE_SCHEDULE_VERSION even when the shooter is otherwise free — confirming the
    OCC layer that outranks the later double-booking check.

    Design: Difficulty/priority_pair_validation_conflict/shooter_assign_stale_version_beats_double_booked
    """
    ctx = setup_confirmed_booking(
        session_type="WEDDING", tier="STANDARD",
        base_fee_cents=200000, included_shoot_hours=6, overage_hourly_rate_cents=15000,
        included_edited_images=100, requested_shoot_hours=6, requires_model_release=True,
        lead_hourly_rate_cents=12000,
        start_utc="2026-09-20T14:00:00Z", end_utc="2026-09-20T18:00:00Z",
    )
    schedule = ctx["schedule"]
    stale_version = schedule["version"]
    second = get_success_data(api.create_photographer(
        {"email": "stale-second@studio.test", "full_name": "Second", "skills": ["PHOTO"],
         "hourly_rate_cents": 8000}, ADMIN))
    # reschedule bumps the schedule version
    get_success_data(api.reschedule_shoot_schedule(
        schedule["id"],
        reschedule_payload("2026-09-21T14:00:00Z", "2026-09-21T18:00:00Z", "WEATHER"),
        ADMIN))
    validate_error(
        api.create_second_shooter_assignment(
            schedule["id"],
            second_shooter_assignment_payload(second["id"], stale_version),
            ADMIN,
        ),
        ApiErrorId.ERR_STALE_SCHEDULE_VERSION.value,
    )


# ===========================================================================
# validations / confirm_missing_model_release_returns_model_release_required
# ===========================================================================
def test_confirm_without_model_release_rejected(api):
    """PRD §3.4: "If the package requires a model release, the contract's
    includes_model_release must be true, or confirmation is rejected with
    ERR_MODEL_RELEASE_REQUIRED."

    Package requires_model_release=true but the SIGNED contract has
    includes_model_release=false -> confirm fails ERR_MODEL_RELEASE_REQUIRED.

    Design: Corner/validations/confirm_missing_model_release_returns_model_release_required
    """
    base = setup_draft_booking(
        session_type="COMMERCIAL", tier="PREMIUM", base_fee_cents=300000,
        included_shoot_hours=4, overage_hourly_rate_cents=20000, included_edited_images=80,
        deposit_pct=0.40, requires_model_release=True, requested_shoot_hours=4,
    )
    booking, client = base["booking"], base["client"]
    # contract signed WITHOUT model release
    create_signed_contract(booking["id"], client["id"], includes_model_release=False)
    create_schedule(booking["id"], "2026-07-25T10:00:00Z", "2026-07-25T14:00:00Z")
    validate_error(
        api.confirm_booking(booking["id"], make_client_headers(client["id"])),
        ApiErrorId.ERR_MODEL_RELEASE_REQUIRED.value,
    )


# ===========================================================================
# validations / book_inactive_package_returns_package_inactive
# ===========================================================================
def test_book_inactive_package_rejected(api):
    """PRD §3.2: "The referenced package must be bookable: if its active flag is false the
    create is rejected with ERR_PACKAGE_INACTIVE."

    Creating a booking against a package with active=false -> ERR_PACKAGE_INACTIVE.

    Design: Corner/validations/book_inactive_package_returns_package_inactive
    """
    client = get_success_data(api.create_client(
        {"email": "inactive-c@studio.test", "full_name": "C", "phone": "13"}, ADMIN))
    photographer = get_success_data(api.create_photographer(
        {"email": "inactive-p@studio.test", "full_name": "P", "skills": ["PHOTO"],
         "hourly_rate_cents": 7000}, ADMIN))
    package = get_success_data(api.create_session_package(create_session_package_payload(
        name="Retired", active=False), ADMIN))
    validate_error(
        api.create_booking(
            create_booking_payload(client["id"], package["id"], photographer["id"],
                                   requested_shoot_hours=2),
            make_client_headers(client["id"]),
        ),
        ApiErrorId.ERR_PACKAGE_INACTIVE.value,
    )


# ===========================================================================
# validations / settle_deposit_wrong_amount_returns_payment_amount_mismatch
# ===========================================================================
def test_settle_deposit_wrong_amount_rejected(api):
    """PRD §3.6: "Settling a payment is a StudioAdmin action that drives the payment track,
    and the amount must agree exactly with what is owed for that kind or the settlement is
    rejected with ERR_PAYMENT_AMOUNT_MISMATCH ... Settling a DEPOSIT requires the booking to
    be UNPAID and the payment to be PENDING with its amount_cents equal to the booking's
    deposit_due_cents."

    deposit_due 30000 but a DEPOSIT payment of 25000 is settled -> ERR_PAYMENT_AMOUNT_MISMATCH.

    Design: Corner/validations/settle_deposit_wrong_amount_returns_payment_amount_mismatch
    """
    ctx = setup_confirmed_booking(
        start_utc="2026-07-01T10:00:00Z", end_utc="2026-07-01T12:00:00Z",
    )
    booking = ctx["booking"]
    assert booking["deposit_due_cents"] == 30000
    payment = get_success_data(
        api.create_payment(create_payment_payload(booking["id"], "DEPOSIT", 25000), ADMIN)
    )
    validate_error(
        api.settle_payment(payment["id"], ADMIN),
        ApiErrorId.ERR_PAYMENT_AMOUNT_MISMATCH.value,
    )


# ===========================================================================
# validations / create_booking_unknown_package_returns_invalid_reference
# ===========================================================================
def test_create_booking_unknown_package_invalid_reference(api):
    """PRD §2.7: "Body foreign keys are then checked against existing parents
    (ERR_INVALID_REFERENCE)."

    POST /studio/bookings with a package_id of valid UUID shape but no matching package ->
    ERR_INVALID_REFERENCE.

    Design: Corner/validations/create_booking_unknown_package_returns_invalid_reference
    """
    client = get_success_data(api.create_client(
        {"email": "ref-c@studio.test", "full_name": "C", "phone": "16"}, ADMIN))
    photographer = get_success_data(api.create_photographer(
        {"email": "ref-p@studio.test", "full_name": "P", "skills": ["PHOTO"],
         "hourly_rate_cents": 7000}, ADMIN))
    validate_error(
        api.create_booking(
            create_booking_payload(
                client["id"], "11111111-1111-4111-8111-111111111111",
                photographer["id"], requested_shoot_hours=2),
            make_client_headers(client["id"]),
        ),
        ApiErrorId.ERR_INVALID_REFERENCE.value,
    )
