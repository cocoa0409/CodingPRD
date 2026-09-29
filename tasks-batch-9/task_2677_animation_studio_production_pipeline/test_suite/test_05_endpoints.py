"""Endpoint tests: re-derived calibration, package linkage and shipping gates."""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import assert_budget_position, assert_instant, assert_two_decimal
from test_helpers.constants import (
    CALIBRATION_CALIBRATED,
    CALIBRATION_EXPIRED,
    CALIBRATION_UNCALIBRATED,
    DELIVERABLE_DELIVERED,
    DELIVERABLE_QC_PASSED,
    NEUTRAL_QUALITY_SCORE,
    PACKAGE_DRAFT,
    PACKAGE_IN_PROGRESS,
    PACKAGE_ISSUED,
    PARTNER_APPROVED,
    PHASE_DELIVERY,
    SESSION_IN_PROGRESS,
    SESSION_SCHEDULED,
    TASK_NOT_STARTED,
)
from test_helpers.test_users import (
    COORDINATOR_HEADERS,
    DIRECTOR_HEADERS,
    PRODUCTION_MANAGER_HEADERS,
)


class TestScreeningRoomCalibration:
    def test_calibration_status_is_re_derived_on_every_read(self, client):
        """The stored stamp never moves on its own, yet the room reads UNCALIBRATED, then
        CALIBRATED, then EXPIRED purely because the clock moved, and re-calibrating restores it.

        PRD: "`calibration_status` itself is never stored as an independent decision — it is
        derived on every read from three things: it is `UNCALIBRATED` when
        `last_calibrated_at` is null; it is `EXPIRED` when the age of the calibration in whole
        days is strictly greater than `calibration_valid_days`; and it is `CALIBRATED`
        otherwise."
        PRD: "It requires the session to be `SCHEDULED` (otherwise
        `ERR_SESSION_STATE_INVALID`), the production to be `PRODUCTION_ACTIVE` or `DELIVERY`,
        and — evaluated at the moment of the call, not at booking time — the room's
        `calibration_status` to be exactly `CALIBRATED`, otherwise `ERR_CALIBRATION_EXPIRED`."

        Design: Corner/endpoints/screening_room_calibrate_refreshes_derived_calibration_status
        """
        room = fx.create_room(
            client, name="SCREEN_1", seat_capacity=12, calibration_valid_days=30
        )
        assert room["calibration_status"] == CALIBRATION_UNCALIBRATED
        assert room["last_calibrated_at"] is None

        production = fx.active_production(
            client, title="Aurora Drift", production_code="AD01", gate_types=["SCRIPT"]
        )
        booking = f.review_session_payload(
            production["id"],
            room["id"],
            window_start="2026-09-10T09:00:00Z",
            window_end="2026-09-10T11:00:00Z",
            attendee_count=4,
        )
        validate_error(
            client.create_review_session(booking, DIRECTOR_HEADERS),
            "ERR_ROOM_NOT_CALIBRATED",
            422,
        )

        calibrated = validate_success(
            client.calibrate_screening_room(room["id"], {}, PRODUCTION_MANAGER_HEADERS)
        )
        assert_instant(calibrated["last_calibrated_at"], "2026-08-01T00:00:00Z")
        assert calibrated["calibration_status"] == CALIBRATION_CALIBRATED

        session = validate_success(
            client.create_review_session(booking, DIRECTOR_HEADERS), 201
        )
        assert session["status"] == SESSION_SCHEDULED

        fx.move_clock(client, "2026-09-10T09:00:00Z")
        stale = fx.read_room(client, room["id"])
        assert_instant(stale["last_calibrated_at"], "2026-08-01T00:00:00Z")
        assert stale["calibration_status"] == CALIBRATION_EXPIRED

        validate_error(
            client.start_review_session(session["id"], {}, DIRECTOR_HEADERS),
            "ERR_CALIBRATION_EXPIRED",
            422,
        )

        recalibrated = validate_success(
            client.calibrate_screening_room(room["id"], {}, PRODUCTION_MANAGER_HEADERS)
        )
        assert_instant(recalibrated["last_calibrated_at"], "2026-09-10T09:00:00Z")
        assert recalibrated["calibration_status"] == CALIBRATION_CALIBRATED

        opened = fx.open_session(client, session["id"])
        assert opened["status"] == SESSION_IN_PROGRESS
        assert_instant(opened["opened_at"], "2026-09-10T09:00:00Z")

        _, meta = validate_paginated(
            client.list_screening_rooms(
                PRODUCTION_MANAGER_HEADERS, {"calibration_status": CALIBRATION_CALIBRATED}
            )
        )
        assert meta["total_count"] == 1


class TestPackageIssueAndAccept:
    def test_issue_links_the_scoped_tasks_and_only_accept_commits_the_fee(self, client):
        """Issuing sets the link on the scoped stage task while the show's money is untouched;
        the vendor's own acceptance is what commits the fee and pulls overhead with it.

        PRD: "When all five pass, every task in `stage_task_ids` has its
        `outsource_package_id` set to this package, and **no money is committed yet**:
        `fee_committed_cents` stays at 0 until the vendor accepts."
        PRD: "Acceptance is the money event: `fee_committed_cents` is set to `fee_cents`, and
        the production's `direct_committed_cents`, `overhead_fee_cents`,
        `total_committed_cents` and `available_cents` are recomputed."

        Design: Corner/endpoints/package_issue_links_scoped_stage_tasks_and_accept_commits_the_fee
        """
        partner = fx.approved_partner(
            client,
            legal_name="Ink & Pixel Studios",
            security_certification_level="TIER1",
            mfa_enforced=True,
            watermark_required=True,
        )
        assert partner["status"] == PARTNER_APPROVED
        assert_two_decimal(
            partner["quality_score_rolling"], NEUTRAL_QUALITY_SCORE, "quality_score_rolling"
        )

        production = fx.active_production(
            client,
            title="Aurora Drift",
            production_code="AD01",
            gate_types=["SCRIPT"],
            budget_cents=100000000,
        )
        shot = fx.create_shot(
            client,
            production["id"],
            shot_code="AD01_010_0010",
            planned_finish_at="2026-09-30T00:00:00Z",
        )
        task = fx.task_for_stage(client, shot["id"], "LAYOUT")
        assert task["outsource_package_id"] is None

        package = fx.draft_package(
            client,
            production["id"],
            partner["id"],
            package_code="AD01_PKG_01",
            security_tier="TIER1",
            fee_cents=500000,
            stage_task_ids=[task["id"]],
            quality_min_score=50.00,
        )
        assert package["status"] == PACKAGE_DRAFT
        assert package["fee_committed_cents"] == 0
        before = fx.read_production(client, production["id"])
        assert_budget_position(before, 0)

        issued = fx.issue_package(client, package["id"])
        assert issued["status"] == PACKAGE_ISSUED
        assert issued["fee_committed_cents"] == 0

        linked, meta = validate_paginated(
            client.list_stage_tasks(
                COORDINATOR_HEADERS, {"outsource_package_id": package["id"]}
            )
        )
        assert meta["total_count"] == 1
        assert linked[0]["id"] == task["id"]
        assert linked[0]["status"] == TASK_NOT_STARTED

        at_issue = fx.read_production(client, production["id"])
        assert_budget_position(at_issue, 0)

        accepted = fx.accept_package(client, package["id"], partner["id"])
        assert accepted["status"] == PACKAGE_IN_PROGRESS
        assert accepted["fee_committed_cents"] == 500000

        after = fx.read_production(client, production["id"])
        assert_budget_position(after, 500000, expected_overhead_cents=75000)
        assert after["available_cents"] == 109425000


class TestDeliverableShipping:
    def test_shipping_waits_for_the_delivery_phase_and_then_becomes_terminal(self, client):
        """A QC-passed deliverable cannot ship while the show is still in production; once the
        phase advances the identical call ships it, stamping the clock of that later moment,
        and a repeat is refused because DELIVERED is terminal.

        PRD: "Shipping the deliverable moves it `QC_PASSED → DELIVERED` and stamps
        `delivered_at` from the logical clock, after which the row is immutable."
        PRD: "It is legal only from `QC_PASSED` — anything else is
        `ERR_DELIVERABLE_STATE_INVALID` — and only while the production has reached
        `DELIVERY`; attempting it while the show is still `PRODUCTION_ACTIVE` is
        `ERR_PRODUCTION_PHASE_INVALID`."

        Design: Corner/endpoints/deliverable_deliver_requires_delivery_phase
        """
        production = fx.active_production(
            client,
            title="Slate Harbour",
            production_code="AD05",
            format="SHORT",
            budget_cents=20000000,
            render_allowance_cents=2000000,
            gate_types=["SCRIPT"],
            approved_color_spaces=["ACEScg", "Rec709"],
        )
        deliverable = fx.qc_passed_deliverable(
            client,
            production["id"],
            qc_note="Levels and audio sync verified.",
            deliverable_type="PROXY_MP4",
            color_space="Rec709",
            resolution="1920x1080",
            bit_depth=8,
        )
        assert deliverable["status"] == DELIVERABLE_QC_PASSED
        assert deliverable["qc_note"] == "Levels and audio sync verified."

        too_early = client.deliver_deliverable(
            deliverable["id"], {}, PRODUCTION_MANAGER_HEADERS
        )
        validate_error(too_early, "ERR_PRODUCTION_PHASE_INVALID", 409)

        fx.move_clock(client, "2026-08-20T12:00:00Z")
        moved = fx.advance_to_delivery(client, production["id"])
        assert moved["phase"] == PHASE_DELIVERY

        shipped = validate_success(
            client.deliver_deliverable(deliverable["id"], {}, PRODUCTION_MANAGER_HEADERS)
        )
        assert shipped["status"] == DELIVERABLE_DELIVERED
        assert_instant(shipped["delivered_at"], "2026-08-20T12:00:00Z")

        again = client.deliver_deliverable(
            deliverable["id"], {}, PRODUCTION_MANAGER_HEADERS
        )
        validate_error(again, "ERR_DELIVERABLE_STATE_INVALID", 409)
