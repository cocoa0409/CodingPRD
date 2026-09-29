"""Processing a sold pass and the season-end expiry cascade."""

from test_helpers import (
    BRONZE,
    ApiErrorId,
    BillingStatus,
    PassStatus,
    ProgramStatus,
    ReservationStatus,
    assert_day_counters,
    assert_grant_count_conserved,
    assert_pass_dimensions,
    assert_version,
    advance_program,
    book_reservation,
    build_active_pass,
    build_pending_pass,
    build_program,
    clerk_headers,
    create_park_day,
    get_park_day,
    get_pass,
    process_pass,
    process_payload,
    program_admin_headers,
    validate_error,
    validate_success,
)


def _reservation(api, reservation_id):
    return validate_success(api.get_reservation(reservation_id, headers=clerk_headers()))


class TestProcessingBindsIdentity:
    """Processing is the moment the photograph and the document are bound."""

    def test_processing_stores_both_credentials_and_activates_the_pass(self, api, sales_open_program):
        """Both flags flip, the pass activates and the programme recounts.

        PRD: "On success the pass stores both values, sets `photo_captured` and
        `identity_bound` to true, advances `pass_status` from `PENDING_PROCESSING` to
        `ACTIVE`, causes the programme's `active_pass_count` to be recomputed, and
        increments the pass's `version` by 1."

        Design: Corner/state_machines/process_pass_sets_photo_capture_and_identity_binding
        """
        pending = build_pending_pass(api, sales_open_program, tier_name="BRONZE")

        processed = process_pass(
            api, pending.id, photo_hash="sha256:aaa", government_id_last4="1234"
        )

        assert_pass_dimensions(processed, pass_status=PassStatus.ACTIVE.value)
        assert processed["photo_captured"] is True, "processing captures the photograph"
        assert processed["identity_bound"] is True, "processing binds the identity document"
        assert processed["photo_hash"] == "sha256:aaa", (
            f"the supplied digest should be stored, got {processed['photo_hash']!r}"
        )
        assert processed["government_id_last4"] == "1234", (
            f"the last four digits should be stored, got {processed['government_id_last4']!r}"
        )
        assert_version(processed, 2, "season pass")
        program_row = validate_success(
            api.get_pass_program(sales_open_program.id, headers=program_admin_headers())
        )
        assert program_row["active_pass_count"] == 1, (
            f"the programme should now count one active pass, got {program_row['active_pass_count']!r}"
        )

    def test_processing_the_same_pass_twice_is_refused(self, api, sales_open_program):
        """Processing happens exactly once per pass.

        PRD: "It also happens exactly once per pass: a pass whose `pass_status` is
        anything other than `PENDING_PROCESSING` is refused with
        `ERR_PASS_ALREADY_PROCESSED` (HTTP 409)."

        Design: Corner/state_machines/second_process_call_on_the_same_pass_is_rejected
        """
        pass_ctx = build_active_pass(api, sales_open_program, tier_name="BRONZE")

        response = api.process_season_pass(
            pass_ctx.id,
            process_payload(photo_hash="sha256:bbb", government_id_last4="9999"),
            headers=clerk_headers(),
        )

        validate_error(response, ApiErrorId.ERR_PASS_ALREADY_PROCESSED.value, 409)
        unchanged = get_pass(api, pass_ctx.id)
        assert unchanged["photo_hash"] == "sha256:aaa", (
            f"the refused call must not overwrite the digest, got {unchanged['photo_hash']!r}"
        )
        assert unchanged["government_id_last4"] == "1234", (
            "the refused call must not overwrite the document digits, got "
            f"{unchanged['government_id_last4']!r}"
        )
        assert_version(unchanged, 2, "season pass")


class TestSeasonEndExpiry:
    """Closing the programme expires the live passes and sweeps their bookings."""

    def test_closing_expires_the_pass_and_marks_its_reservation_a_no_show(self, api, default_clock):
        """The guest who never showed up is recorded as a no-show, not a release.

        PRD: "Reaching `CLOSED` runs the season-end expiry: every season pass of this
        programme whose `pass_status` is `PENDING_PROCESSING`, `ACTIVE` or `SUSPENDED`
        becomes `EXPIRED`; because those passes expired, each of their reservations still in
        `CONFIRMED` becomes `NO_SHOW` and every affected park day recomputes its
        `no_show_count`, `reserved_count` and `remaining_slot_count`; and the programme's
        `active_pass_count`, `base_revenue_cents`, `recognized_revenue_cents` and
        `deferred_revenue_cents` are all recomputed."

        Design: Corner/state_machines/program_close_expires_passes_and_sweeps_reservations_to_no_show
        """
        program = build_program(api, tiers=(BRONZE,), status=ProgramStatus.SEASON_ACTIVE.value)
        day = create_park_day(api, program.id, "2026-10-20")
        pass_ctx = build_active_pass(api, program, tier_name="BRONZE")
        reservation = book_reservation(api, pass_ctx.id, day["id"], "10:00", "13:00")

        advance_program(api, program.id, ProgramStatus.CLOSED.value)

        expired = get_pass(api, pass_ctx.id)
        assert_pass_dimensions(
            expired,
            pass_status=PassStatus.EXPIRED.value,
            billing_status=BillingStatus.PAID_IN_FULL.value,
        )
        assert (
            _reservation(api, reservation["id"])["status"] == ReservationStatus.NO_SHOW.value
        ), "the unredeemed booking of an expired pass becomes a no-show"
        day_row = get_park_day(api, day["id"])
        assert_day_counters(day_row, reserved=0, no_show=1, released=0, redeemed=0, grant=1)
        assert_grant_count_conserved(day_row)
        program_row = validate_success(
            api.get_pass_program(program.id, headers=program_admin_headers())
        )
        assert program_row["active_pass_count"] == 0, (
            f"an expired pass is no longer active, got {program_row['active_pass_count']!r}"
        )
        assert program_row["base_revenue_cents"] == 12000, (
            "the money the guest paid stays booked as base revenue, got "
            f"{program_row['base_revenue_cents']!r}"
        )
