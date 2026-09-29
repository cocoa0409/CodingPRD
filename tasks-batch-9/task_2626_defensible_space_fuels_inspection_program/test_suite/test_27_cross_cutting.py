"""Optimistic concurrency: the two version tokens that guard a lost update."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import (
    EPOCH_CLOCK_UTC,
    ERR_STALE_PARCEL_VERSION,
    ERR_STALE_PROGRAM_VERSION,
    add_zones,
    assert_award,
    assert_notice_schedule,
    assert_posture,
    assert_program_capacity,
    assert_version,
    complete_inspection,
    create_parcel,
    create_program,
    discretionary_notice_payload,
    enroll,
    get_notice,
    get_parcel,
    get_program,
    list_enrollments,
    list_notices,
    noticed_world,
    open_cycle,
    parcel_patch,
)
from test_helpers.test_users import PROGRAM_ADMIN_HEADERS


class TestStaleParcelVersionOnDiscretionaryNotice:
    """One cascade, one version increment - and a token from before it is dead."""

    def test_a_token_held_across_the_fail_cascade_is_refused_on_both_parcel_writes(
        self, client
    ):
        """The five-link FAIL cascade moves the parcel from version 1 to version 2, so
        the discretionary notice and the parcel PATCH are both refused 412 until the
        client re-reads.

        PRD: "version, an integer that starts at 1 when the resource is created and
        increments by exactly 1 on every successful mutation of that resource."

        PRD: "completed_at_utc is stamped with the logical clock, the submitted result
        is stored, the parcel is rescored under the post-inspection-verified variant with
        risk_score_basis set to POST_INSPECTION_VERIFIED and risk_class re-banded, the
        inspection moves NOTICED -> COMPLETED, the assigned inspector's
        assigned_open_count drops by 1, and both the inspection's and the parcel's
        version advance by 1."

        PRD: "If that value does not equal the parcel's current version, the request is
        rejected with ERR_STALE_PARCEL_VERSION (HTTP 412) and no notice is created."

        PRD: "The same expected_parcel_version field, with the same rejection code and
        status, is required when updating a parcel's attributes."

        PRD: "any existing notice on the same parcel standing in ISSUED, EXTENDED or
        OVERDUE is driven to VOIDED with its void_reason recorded as
        SUPERSEDED_BY_NEW_NOTICE, and the new notice's supersedes_notice_id is set to the
        identifier of the notice it replaced."

        Design: Corner/cross-cutting complexity layers/stale_parcel_version_blocks_discretionary_notice
        """
        world = noticed_world(client)
        parcel_id = world["parcel"]["id"]
        stale_version = world["parcel"]["version"]
        assert_version(world["parcel"], 1)

        add_zones(client, world["inspection"]["id"], world["inspector"]["id"])
        complete_inspection(
            client, world["inspection"]["id"], world["inspector"]["id"], "FAIL"
        )
        # Five cascade links fired, yet the parcel took exactly one increment.
        after_cascade = get_parcel(client, parcel_id)
        assert_version(after_cascade, 2)
        current_version = after_cascade["version"]
        assert_posture(after_cascade, "NON_COMPLIANT", open_violation_count=1)
        cascade_notice_id = list_notices(client, parcel_id=parcel_id)[0][0]["id"]

        # A second notice is otherwise perfectly legitimate, so only the token can
        # tell a deliberate supersession from a lost update.
        validate_error(
            client.create_discretionary_notice(
                parcel_id,
                discretionary_notice_payload(
                    world["inspection"]["id"], stale_version, notice_method="EMAIL"
                ),
                headers=PROGRAM_ADMIN_HEADERS,
            ),
            ERR_STALE_PARCEL_VERSION,
            412,
        )
        held = get_parcel(client, parcel_id)
        assert held["open_violation_count"] == 1
        # A rejected write neither creates a notice nor voids one, and does not
        # itself advance the version.
        _rows, meta = list_notices(client, parcel_id=parcel_id)
        assert meta["total_count"] == 1
        assert_version(held, 2)
        assert get_notice(client, cascade_notice_id)["status"] == "ISSUED"

        # The same token guards the other parcel write of this rule.
        validate_error(
            client.update_parcel(
                parcel_id,
                parcel_patch(stale_version, access_constraint="NONE"),
                headers=PROGRAM_ADMIN_HEADERS,
            ),
            ERR_STALE_PARCEL_VERSION,
            412,
        )
        assert_version(get_parcel(client, parcel_id), 2)

        # Re-reading and retrying succeeds, and the supersession runs.
        superseding = validate_success(
            client.create_discretionary_notice(
                parcel_id,
                discretionary_notice_payload(
                    world["inspection"]["id"], current_version, notice_method="EMAIL"
                ),
                headers=PROGRAM_ADMIN_HEADERS,
            ),
            201,
        )
        assert superseding["supersedes_notice_id"] == cascade_notice_id
        assert_notice_schedule(
            superseding, "MAJOR", EPOCH_CLOCK_UTC, 30, "2026-08-31", status="ISSUED"
        )
        voided = get_notice(client, cascade_notice_id)
        assert voided["status"] == "VOIDED"
        assert voided["void_reason"] == "SUPERSEDED_BY_NEW_NOTICE"
        assert_posture(
            get_parcel(client, parcel_id), "NON_COMPLIANT", open_violation_count=1
        )


class TestStaleProgramVersionOnEnrollment:
    """Budget the first writer already reserved cannot be spent twice."""

    def test_a_second_parcel_enrolling_on_the_pre_reservation_token_is_refused(
        self, client
    ):
        """Parcel B is refused 412 even though a slot and 380,000 cents remain, and the
        retry on the fresh token is sized against the reduced budget.

        PRD: "Creating a support enrollment requires a non-optional
        expected_program_version field carrying the client's last observed version of the
        target SupportProgram. A mismatch with the program's current version is rejected
        with ERR_STALE_PROGRAM_VERSION (HTTP 412)."

        PRD: "Enrollment admission reads budget_remaining_cents and reserved_slots, both
        of which any prior enrollment writer will have moved; without the version check a
        later client would be admitted against budget that is already reserved."

        PRD: "At creation budget_remaining_cents is initialised to budget_total_cents and
        reserved_slots to 0."

        PRD: "Approval sets reserved_amount_cents to award_cents for a grant, debits the
        program's budget_remaining_cents by that same amount, increments reserved_slots
        by 1, leaves waitlist_position null, and advances the program's version by 1."

        PRD: "The base match rate is read from the parcel's risk_class as it stands at
        decision time: an EXTREME parcel is matched at 0.75, a HIGH parcel at 0.60, a
        MODERATE parcel at 0.45 and a LOW parcel at 0.30."

        PRD: "a pre-bonus award below 50,000 cents draws 0.15"

        Design: Corner/cross-cutting complexity layers/stale_program_version_blocks_enrollment
        """
        cycle = open_cycle(client)
        parcel_a = create_parcel(client)
        parcel_b = create_parcel(client)
        program = create_program(
            client, cycle["id"], budget_total_cents=500000, capacity_slots=3
        )
        stale_version = program["version"]
        assert_version(program, 1)
        assert_program_capacity(program, 500000, 0)

        # Parcel A is admitted first and moves the programme behind B's back.
        first = enroll(
            client,
            program["id"],
            parcel_a["id"],
            stale_version,
            vendor_invoice_cents=200000,
        )
        assert first["status"] == "APPROVED"
        assert_award(first, 120000, 0.05, 0, 120000, reserved=120000)
        reserved_program = get_program(client, program["id"])
        assert_version(reserved_program, 2)
        assert_program_capacity(reserved_program, 380000, 1)
        current_version = reserved_program["version"]

        validate_error(
            client.create_enrollment(
                {
                    "support_program_id": program["id"],
                    "parcel_id": parcel_b["id"],
                    "expected_program_version": stale_version,
                    "vendor_invoice_cents": 60000,
                },
                headers=PROGRAM_ADMIN_HEADERS,
            ),
            ERR_STALE_PROGRAM_VERSION,
            412,
        )
        # The refused enrollment reserved nothing at all.
        untouched = get_program(client, program["id"])
        assert_program_capacity(untouched, 380000, 1)
        assert_version(untouched, 2)
        _rows, meta = list_enrollments(client, support_program_id=program["id"])
        assert meta["total_count"] == 1

        # Retrying on the fresh token is admitted, and sized at the HIGH match rate.
        second = enroll(
            client,
            program["id"],
            parcel_b["id"],
            current_version,
            vendor_invoice_cents=60000,
        )
        assert second["status"] == "APPROVED"
        assert second["waitlist_position"] is None
        assert_award(second, 36000, 0.15, 0, 36000, reserved=36000)
        settled = get_program(client, program["id"])
        assert_program_capacity(settled, 344000, 2)
        assert_version(settled, 3)
