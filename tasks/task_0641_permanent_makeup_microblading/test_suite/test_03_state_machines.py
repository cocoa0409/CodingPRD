"""Appointment parallel-axis lifecycle, patch-test machine, redo cycle, and
cancellation/no-show/void transitions.

Translates queue-A non_linear_state_machine instances and queue-B state_machine
corner instances.
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    TEST_USERS,
    make_technician_headers,
    setup_booking_ready,
    book_initial_appointment,
    setup_deposited_appointment,
    setup_completed_appointment,
    pay_deposit,
    set_clock,
    create_redo_request_payload,
    schedule_redo_payload,
    create_healing_log_payload,
)

FRONT = TEST_USERS["front_desk_headers"]
ADMIN = TEST_USERS["studio_admin_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]
TECH = TEST_USERS["technician_headers"]


# ─────────────────────────────────────────────────────────────────────────────
# Queue A: non_linear_state_machine
# ─────────────────────────────────────────────────────────────────────────────
class TestAppointmentParallelAxes:
    """Deposit moves payment_status while lifecycle stays BOOKED; only /start
    moves lifecycle."""

    def test_deposit_advances_payment_only_lifecycle_stays_booked(self, api):
        """PRD §3.6: "A `BOOKED` appointment can move from `AWAITING_DEPOSIT` to
        `DEPOSIT_PAID` without any lifecycle change."

        Design: Difficulty/non_linear_state_machine/nlsm_appointment_parallel_payment_lifecycle
        """
        ctx, appt = setup_deposited_appointment(scheduled_start="2026-01-06T10:00:00Z")
        assert appt["payment_status"] == "DEPOSIT_PAID"
        assert appt["lifecycle_status"] == "BOOKED", (
            "paying the deposit must not change the lifecycle axis"
        )

    def test_start_advances_lifecycle_while_payment_unchanged(self, api):
        """PRD §3.6: "A `Technician` starts the procedure, advancing the
        lifecycle from `BOOKED` to `IN_PROCEDURE`."

        Design: Difficulty/non_linear_state_machine/nlsm_appointment_parallel_payment_lifecycle
        """
        ctx, appt = setup_deposited_appointment(scheduled_start="2026-01-06T10:00:00Z")
        started = validate_success(
            api.start_appointment(appt["id"], make_technician_headers(ctx["technician"]["id"])),
            200,
        )
        assert started["lifecycle_status"] == "IN_PROCEDURE"
        assert started["payment_status"] == "DEPOSIT_PAID", (
            "start advances the lifecycle axis only; payment stays DEPOSIT_PAID"
        )


class TestRedoRequestCycle:
    """COMPLETED+POOR -> REQUESTED -> APPROVED -> SCHEDULED creates a REDO
    appointment that completes and bubbles the redo to FULFILLED."""

    def _approved_redo(self, api):
        ctx, completed = setup_completed_appointment(
            healing_outcome_flag="POOR",
            healing_day_offset=21,
            scheduled_start="2026-01-06T10:00:00Z",
            complete_clock="2026-02-01T00:00:00Z",
        )
        assert completed["healing_outcome"] == "POOR"
        redo = get_success_data(
            api.create_redo_request(create_redo_request_payload(completed["id"]), FRONT)
        )
        get_success_data(api.approve_redo(redo["id"], COMPLIANCE))
        return ctx, completed, redo

    def test_schedule_creates_free_redo_appointment(self, api):
        """PRD §3.7: "Scheduling creates a new appointment of kind `REDO` whose
        `parent_appointment_id` is the source appointment, with
        `session_price_cents` of 0, `deposit_required_cents` of 0,
        `payment_status` of `PAID_IN_FULL`, and `lifecycle_status` of `BOOKED`".

        Design: Difficulty/non_linear_state_machine/nlsm_redo_request_cycle_completed_back_to_completed
        """
        ctx, completed, redo = self._approved_redo(api)
        scheduled = validate_success(
            api.schedule_redo(
                redo["id"],
                schedule_redo_payload(
                    ctx["technician"]["id"],
                    ctx["formula"]["id"],
                    ctx["patch_test"]["id"],
                    expected_appointment_version=completed["version"],
                    scheduled_start="2026-02-10T10:00:00Z",
                ),
                FRONT,
            ),
            200,
        )
        assert scheduled["status"] == "SCHEDULED"
        redo_appt = validate_success(
            api.get_appointment(scheduled["redo_appointment_id"], FRONT), 200
        )
        assert redo_appt["appointment_kind"] == "REDO"
        assert redo_appt["session_price_cents"] == 0
        assert redo_appt["payment_status"] == "PAID_IN_FULL"

    def test_redo_fulfilled_when_redo_appointment_completes(self, api):
        """PRD §3.7: "When that redo appointment is later completed, its redo
        request bubbles up to `FULFILLED`, closing the loop from a `COMPLETED`
        source through `REQUESTED → APPROVED → SCHEDULED` to `FULFILLED`."

        Design: Difficulty/non_linear_state_machine/nlsm_redo_request_cycle_completed_back_to_completed
        """
        ctx, completed, redo = self._approved_redo(api)
        scheduled = get_success_data(
            api.schedule_redo(
                redo["id"],
                schedule_redo_payload(
                    ctx["technician"]["id"],
                    ctx["formula"]["id"],
                    ctx["patch_test"]["id"],
                    expected_appointment_version=completed["version"],
                    scheduled_start="2026-02-10T10:00:00Z",
                ),
                FRONT,
            )
        )
        redo_appt_id = scheduled["redo_appointment_id"]
        tech_headers = make_technician_headers(ctx["technician"]["id"])
        # Drive the REDO appointment (already PAID_IN_FULL, BOOKED) to COMPLETED.
        get_success_data(api.start_appointment(redo_appt_id, tech_headers))
        get_success_data(api.finish_procedure(redo_appt_id, tech_headers))
        get_success_data(
            api.create_healing_log(
                create_healing_log_payload(redo_appt_id, day_offset=14, outcome_flag="GOOD"),
                tech_headers,
            )
        )
        get_success_data(api.complete_appointment(redo_appt_id, tech_headers))

        final_redo = validate_success(api.get_redo_request(redo["id"], FRONT), 200)
        assert final_redo["status"] == "FULFILLED"


# ─────────────────────────────────────────────────────────────────────────────
# Queue B: state_machines
# ─────────────────────────────────────────────────────────────────────────────
def test_new_appointment_starts_booked_awaiting_deposit(api):
    """PRD §3.5: "A new booking begins with `lifecycle_status` of `BOOKED`,
    `payment_status` of `AWAITING_DEPOSIT`, and `appointment_kind` of `INITIAL`".

    Design: Corner/state_machines/sm_appointment_initial_state_booked
    """
    ctx = setup_booking_ready()
    appt = book_initial_appointment(ctx, scheduled_start="2026-01-06T10:00:00Z")
    assert appt["lifecycle_status"] == "BOOKED"
    assert appt["payment_status"] == "AWAITING_DEPOSIT"


def test_start_without_deposit_invalid_state(api):
    """PRD §3.6: "Starting is permitted only when the lifecycle is `BOOKED`, the
    payment status is `DEPOSIT_PAID` or `PAID_IN_FULL` ...".
    PRD §2.9: "the system verifies that the target resource is in a valid source
    state for the requested transition (`ERR_INVALID_STATE`)."

    Design: Corner/state_machines/sm_appointment_start_from_booked_without_deposit_invalid
    """
    ctx = setup_booking_ready()
    appt = book_initial_appointment(ctx, scheduled_start="2026-01-06T10:00:00Z")
    res = api.start_appointment(appt["id"], make_technician_headers(ctx["technician"]["id"]))
    validate_error(res, "ERR_INVALID_STATE")


def test_read_patch_test_twice_invalid_state(api):
    """PRD §3.3: "A patch test's `status` follows a state machine with `APPLIED`
    as the initial state and `READ` and `VOIDED` as terminal states." and "The
    read is permitted only when the test is currently `APPLIED` ...".
    PRD §2.9: "the target resource is in a valid source state for the requested
    transition (`ERR_INVALID_STATE`)."

    Design: Corner/state_machines/sm_patchtest_read_twice_invalid_state
    """
    set_clock("2026-01-01T00:00:00Z")
    studio = get_success_data(api.create_studio({"name": "Ink", "state_code": "CA", "sterile_kit_total": 5}, ADMIN))
    tech = get_success_data(
        api.create_technician(
            {
                "studio_id": studio["id"],
                "full_name": "T",
                "license_number": "L1",
                "bbp_cert_expiry": "2030-01-01T00:00:00Z",
                "license_expiry": "2030-01-01T00:00:00Z",
            },
            ADMIN,
        )
    )
    client = get_success_data(api.create_client({"studio_id": studio["id"], "full_name": "C", "date_of_birth": "1990-01-01T00:00:00Z"}, FRONT))
    pt = get_success_data(api.create_patch_test({"client_id": client["id"]}, TECH))
    set_clock("2026-01-03T01:00:00Z")
    tech_headers = make_technician_headers(tech["id"])
    get_success_data(api.read_patch_test(pt["id"], {"reaction_grade": 1}, tech_headers))
    res = api.read_patch_test(pt["id"], {"reaction_grade": 1}, tech_headers)
    validate_error(res, "ERR_INVALID_STATE")


def test_cancel_completed_appointment_invalid_state(api):
    """PRD §3.9: "A `FrontDesk` operator cancels a `BOOKED` appointment ...;
    cancellation is permitted only while the lifecycle is `BOOKED`."
    PRD §2.9: "the target resource is in a valid source state for the requested
    transition (`ERR_INVALID_STATE`)."

    Design: Corner/state_machines/sm_appointment_complete_terminal_then_cancel_invalid
    """
    ctx, completed = setup_completed_appointment(
        scheduled_start="2026-01-06T10:00:00Z", complete_clock="2026-02-01T00:00:00Z"
    )
    res = api.cancel_appointment(completed["id"], FRONT)
    validate_error(res, "ERR_INVALID_STATE")


def test_cancel_early_issues_full_refund(api):
    """PRD §3.9: "if the current logical-clock time is at or before the
    `scheduled_start` minus the 48-hour free-cancel window, the studio issues a
    full refund — a `REFUND` deposit transaction for the full `deposit_paid_cents`
    and the payment status moves to `REFUNDED`."

    Design: Corner/state_machines/sm_cancel_early_full_refund
    """
    # scheduled_start 2026-01-10, deposit paid, cancel at 2026-01-02 (>48h before).
    ctx, appt = setup_deposited_appointment(scheduled_start="2026-01-10T10:00:00Z")
    set_clock("2026-01-02T00:00:00Z")
    cancelled = validate_success(api.cancel_appointment(appt["id"], FRONT), 200)
    assert cancelled["lifecycle_status"] == "CANCELLED"
    assert cancelled["payment_status"] == "REFUNDED"
    assert cancelled["deposit_paid_cents"] == 0


def test_cancel_late_forfeits_deposit(api):
    """PRD §3.9: "Otherwise the cancellation is late: the studio emits a
    `FORFEIT` deposit transaction for the `deposit_paid_cents`, the deposit is
    kept, and the payment status remains `DEPOSIT_PAID`."

    Design: Corner/state_machines/sm_cancel_late_forfeit
    """
    # scheduled_start 2026-01-06, deposit paid, cancel at 2026-01-05 (<48h before).
    ctx, appt = setup_deposited_appointment(scheduled_start="2026-01-06T10:00:00Z")
    set_clock("2026-01-05T10:00:00Z")
    cancelled = validate_success(api.cancel_appointment(appt["id"], FRONT), 200)
    assert cancelled["lifecycle_status"] == "CANCELLED"
    assert cancelled["payment_status"] == "DEPOSIT_PAID"
    assert cancelled["deposit_paid_cents"] == 13000


def test_deny_redo_leaves_no_redo_appointment(api):
    """PRD §3.7: "Alternatively a `ComplianceOfficer` denies the request, moving
    it from `REQUESTED` to `DENIED` with no redo appointment created."

    Design: Corner/state_machines/sm_redo_deny_no_appointment_created
    """
    ctx, completed = setup_completed_appointment(
        healing_outcome_flag="POOR",
        healing_day_offset=21,
        scheduled_start="2026-01-06T10:00:00Z",
        complete_clock="2026-02-01T00:00:00Z",
    )
    redo = get_success_data(
        api.create_redo_request(create_redo_request_payload(completed["id"], reason="uneven"), FRONT)
    )
    denied = validate_success(api.deny_redo(redo["id"], COMPLIANCE), 200)
    assert denied["status"] == "DENIED"
    assert denied["redo_appointment_id"] is None


def test_void_completed_appointment_invalid_state(api):
    """PRD §3.9: "A `ComplianceOfficer` may void a `BOOKED` appointment
    directly ...; voiding is permitted only while the lifecycle is `BOOKED`."
    PRD §2.9: "the target resource is in a valid source state for the requested
    transition (`ERR_INVALID_STATE`)."

    Design: Corner/state_machines/sm_appointment_void_from_completed_invalid
    """
    ctx, completed = setup_completed_appointment(
        scheduled_start="2026-01-06T10:00:00Z", complete_clock="2026-02-01T00:00:00Z"
    )
    res = api.void_appointment(completed["id"], COMPLIANCE)
    validate_error(res, "ERR_INVALID_STATE")
