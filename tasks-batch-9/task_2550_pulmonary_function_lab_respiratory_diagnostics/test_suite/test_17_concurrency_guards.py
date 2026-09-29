"""The two version-guarded writes, replayed against the version they consumed.

Both operations are unblocked by any state precondition — a second report
assignment supersedes the first, and a second medication hold supersedes its
predecessor — so the version guard is the only thing that decides which view of
the parent record the instruction was written against.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_STALE_ORDER_VERSION,
    ERR_STALE_SESSION_VERSION,
)
from test_helpers.assertions import (
    assert_instant,
    assert_page,
    assert_version_is,
)
from test_helpers.test_users import LAB_MANAGER

LATE_MORNING = "2026-08-03T10:00:00Z"
LATE_MORNING_SLOT = ("2026-08-03T11:00:00Z", "2026-08-03T11:30:00Z")
EARLY_MORNING = "2026-08-01T06:00:00Z"


class TestReportAssignmentVersionGuard:
    """The first assignment moves the study's version, so the replay is stale."""

    def test_the_replayed_assignment_is_refused_and_a_re_read_supersedes_instead(
        self, api
    ):
        """Only a fresh read of the study lets the supersession through.

        PRD 2.7: "Assigning an interpretation report to an accepted study requires
        the body field `expected_session_version`, carrying the `version` of that
        `TestSession` as the client last observed it. If the value does not equal
        the study's current `version`, the request is rejected with
        `ERR_STALE_SESSION_VERSION` (HTTP 412) and no report is created."

        PRD 3.9: "A second assignment on the same study is legitimate: any prior
        report on that study whose `status` is `ASSIGNED` moves to `REASSIGNED`
        with `superseded_by_report_id` pointing at the new report, and the losing
        interpreter's `open_report_count` drops by one while the winning
        interpreter's rises by one, so the laboratory-wide open total is
        unchanged."

        Design: Corner/cross_cutting_complexity_layers/report_assignment_rejects_the_session_version_its_own_predecessor_consumed
        """
        start, end = LATE_MORNING_SLOT
        lab = fx.build_lab(api, clock=LATE_MORNING, interpreters=2)
        session = fx.build_accepted_session(
            api, lab, scheduled_start_at=start, scheduled_end_at=end
        )
        observed_version = session["version"]

        first = validate_success(
            api.create_interpretation_report(
                session["id"],
                f.report_assignment_payload(observed_version),
                LAB_MANAGER,
            ),
            expected_status=201,
        )
        assert first["status"] == "ASSIGNED"
        assert first["interpreter_staff_id"] == lab.roster.rad1_id

        moved_on = validate_success(api.get_test_session(session["id"], LAB_MANAGER))
        assert_version_is(moved_on, observed_version + 1)

        validate_error(
            api.create_interpretation_report(
                session["id"],
                f.report_assignment_payload(observed_version),
                LAB_MANAGER,
            ),
            ERR_STALE_SESSION_VERSION,
        )

        _, meta = validate_paginated(
            api.list_interpretation_reports(LAB_MANAGER, session_id=session["id"])
        )
        assert_page(meta, total_count=1, has_more=False)

        second = validate_success(
            api.create_interpretation_report(
                session["id"],
                f.report_assignment_payload(moved_on["version"]),
                LAB_MANAGER,
            ),
            expected_status=201,
        )
        assert second["status"] == "ASSIGNED"
        assert second["interpreter_staff_id"] == lab.roster.rad2_id

        superseded = validate_success(
            api.get_interpretation_report(first["id"], LAB_MANAGER)
        )
        assert superseded["status"] == "REASSIGNED"
        assert superseded["superseded_by_report_id"] == second["id"]

        released = validate_success(api.get_staff(lab.roster.rad1_id, LAB_MANAGER))
        assert released["open_report_count"] == 0
        loaded = validate_success(api.get_staff(lab.roster.rad2_id, LAB_MANAGER))
        assert loaded["open_report_count"] == 1


class TestMedicationHoldVersionGuard:
    """Every hold increments the order, so the submit's version is already spent."""

    def test_the_second_hold_is_refused_on_the_version_the_first_hold_consumed(
        self, api
    ):
        """The refusal issues no instruction, so the release instant does not move.

        PRD 2.7: "Issuing a pre-test medication hold against a test order requires
        the body field `expected_order_version`, carrying the `version` of that
        `TestOrder` as the client last observed it. If the value does not equal the
        order's current `version`, the request is rejected with
        `ERR_STALE_ORDER_VERSION` (HTTP 412) and no hold is created."

        PRD 3.4: "The server stamps `instructed_at` from the logical clock, reads
        `required_hold_hours` from the fixed per-class table (`SABA` 6 hours,
        `SAMA` 8, `LABA` 24, `LAMA` 36, `ICS_LABA` 24, `ANTIHISTAMINE` 72 and
        `CAFFEINE` 8) and computes that hold's own `release_at` as `instructed_at`
        plus `required_hold_hours` hours."

        Design: Corner/cross_cutting_complexity_layers/hold_issuance_rejects_the_order_version_the_previous_hold_consumed
        """
        fx.set_clock(api, EARLY_MORNING)
        roster = fx.build_roster(api)
        patient = fx.register_patient(api)
        order = fx.draft_and_submit_order(
            api,
            patient["id"],
            roster.doc1,
            current_medication_classes=("SABA", "LAMA"),
        )
        assert order["status"] == "SUBMITTED"
        assert_version_is(order, 2)
        observed_version = order["version"]

        longest = validate_success(
            api.create_medication_hold(
                order["id"],
                f.medication_hold_payload("LAMA", observed_version),
                roster.tech1,
            ),
            expected_status=201,
        )
        assert longest["required_hold_hours"] == 36
        assert_instant(longest["release_at"], "2026-08-02T18:00:00Z")

        instructed = validate_success(api.get_test_order(order["id"], LAB_MANAGER))
        assert instructed["status"] == "MED_HOLD_ISSUED"
        assert_instant(instructed["hold_release_at"], "2026-08-02T18:00:00Z")
        assert_version_is(instructed, 3)

        validate_error(
            api.create_medication_hold(
                order["id"],
                f.medication_hold_payload("SABA", observed_version),
                roster.tech1,
            ),
            ERR_STALE_ORDER_VERSION,
        )

        _, meta = validate_paginated(
            api.list_medication_holds(LAB_MANAGER, order_id=order["id"])
        )
        assert_page(meta, total_count=1, has_more=False)

        unmoved = validate_success(api.get_test_order(order["id"], LAB_MANAGER))
        assert_instant(unmoved["hold_release_at"], "2026-08-02T18:00:00Z")
        assert_version_is(unmoved, 3)

        shortest = validate_success(
            api.create_medication_hold(
                order["id"],
                f.medication_hold_payload("SABA", unmoved["version"]),
                roster.tech1,
            ),
            expected_status=201,
        )
        assert shortest["required_hold_hours"] == 6
        assert_instant(shortest["release_at"], "2026-08-01T12:00:00Z")

        both_issued = validate_success(api.get_test_order(order["id"], LAB_MANAGER))
        assert_version_is(both_issued, 4)
        assert_instant(both_issued["hold_release_at"], "2026-08-02T18:00:00Z")

        _, final_meta = validate_paginated(
            api.list_medication_holds(LAB_MANAGER, order_id=order["id"])
        )
        assert_page(final_meta, total_count=2, has_more=False)
