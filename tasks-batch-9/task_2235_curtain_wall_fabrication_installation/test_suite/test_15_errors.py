"""Three refusals that carry real business weight: the dispute reference an
escalated resubmittal must carry, the frozen posture's reach across release and
field progress, and the half-open hoist window."""
import pytest
from prd_bench_local_runner.testing import get_success_data, validate_error, validate_success

from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.test_users import TEST_USERS

PM = TEST_USERS["cw_project_manager_headers"]
DETAILER = TEST_USERS["cw_detailer_headers"]
SUPERINTENDENT = TEST_USERS["field_superintendent_headers"]


class TestEscalatedResubmittalNeedsItsDisputeReference:
    """The escalated cycle edge is the one resubmittal that carries a
    precondition of its own."""

    def test_a_missing_and_an_empty_reference_are_both_refused_and_a_real_one_clears_the_freeze(self):
        """Two escalations later the set sits escalated with the package frozen; a
        resubmittal naming only the new drawing set is refused, so is one carrying
        an empty reference, and only a non-empty reference returns the set to
        submitted, clears its three seal fields and releases the posture.

        PRD: "An escalated submittal resubmitted without that reference is refused with `ERR_DISPUTE_REF_REQUIRED`."

        Design: Corner/errors/escalated_resubmit_without_a_dispute_reference_is_rejected
        """
        ctx = fx.setup_escalated_submittal()
        submittal_id = ctx["submittal_id"]
        escalated = get_success_data(api_client.get_submittal(submittal_id, DETAILER))
        assert escalated["state"] == "ESCALATED"
        assert escalated["revision_cycle"] == 3
        assert escalated["review_decision"] == "REVISION_REQUIRED"
        frozen = fx.refresh_package(ctx)
        assert frozen["engineering_posture"] == "FROZEN"
        assert frozen["blocking_submittal_count"] == 1

        validate_error(
            api_client.resubmit_submittal(
                submittal_id, f.resubmit_payload("SD-004"), DETAILER
            ),
            ApiErrorId.ERR_DISPUTE_REF_REQUIRED.value,
            expected_status=409,
        )
        validate_error(
            api_client.resubmit_submittal(
                submittal_id,
                f.resubmit_payload("SD-004", dispute_resolution_ref=""),
                DETAILER,
            ),
            ApiErrorId.ERR_DISPUTE_REF_REQUIRED.value,
            expected_status=409,
        )
        still = get_success_data(api_client.get_submittal(submittal_id, DETAILER))
        assert still["state"] == "ESCALATED"
        assert still["revision_cycle"] == 3
        assert still["drawing_set_ref"] == escalated["drawing_set_ref"]
        assert fx.refresh_package(ctx)["engineering_posture"] == "FROZEN"

        resubmitted = validate_success(
            api_client.resubmit_submittal(
                submittal_id,
                f.resubmit_payload("SD-004", dispute_resolution_ref="RFI-2287-RESOLVED"),
                DETAILER,
            ),
            expected_status=200,
        )
        assert resubmitted["state"] == "SUBMITTED"
        assert resubmitted["revision_cycle"] == 4
        assert resubmitted["drawing_set_ref"] == "SD-004"
        assert resubmitted["sealed_by_user_id"] is None
        assert resubmitted["seal_license_no"] is None
        assert resubmitted["sealed_at"] is None

        thawed = fx.refresh_package(ctx)
        assert thawed["engineering_posture"] == "OPEN"
        assert thawed["blocking_submittal_count"] == 0


class TestFrozenPostureBlocksReleaseAndField:
    """One escalated submittal halts work authorised by an entirely different,
    fully approved one."""

    @staticmethod
    def _approved_package_frozen_by_a_second_escalated_submittal():
        ctx = fx.setup_ready_for_release()
        approved_submittal_id = ctx["submittal_id"]
        zone_id = ctx["zone_ids"][0]
        fx.add_poured_embeds(ctx, zone_id)

        fx.create_submittal(
            ctx, title="mullion splice revision", drawing_set_ref="SD-900"
        )
        escalated_id = ctx["submittal_id"]
        for next_ref in ("SD-901", "SD-902", None):
            fx.seal_submittal(ctx)
            fx.start_review(ctx)
            fx.review_submittal(ctx, "REVISION_REQUIRED")
            if next_ref is not None:
                fx.resubmit_submittal(ctx, next_ref)

        ctx["submittal_id"] = approved_submittal_id
        return ctx, zone_id, escalated_id

    def test_the_release_and_the_anchors_both_stop_until_the_escalation_is_resolved(self):
        """While the posture is frozen the release of an approved submittal and the
        anchor step over a poured survey are both refused with the posture error and
        neither row moves; once the escalation is resubmitted away the release is
        issued and the anchors are set, carrying the package through fabrication into
        installation.

        PRD: "The package's `engineering_posture` must not be `FROZEN`, or the release is refused with `ERR_ENGINEERING_POSTURE_FROZEN`."

        Design: Corner/errors/frozen_posture_blocks_release_and_field_progress
        """
        ctx, zone_id, escalated_id = (
            self._approved_package_frozen_by_a_second_escalated_submittal()
        )
        frozen = fx.refresh_package(ctx)
        assert frozen["engineering_posture"] == "FROZEN"
        assert frozen["blocking_submittal_count"] == 1
        assert frozen["state"] == "MOCKUP_QUALIFIED"
        assert (
            get_success_data(api_client.get_submittal(ctx["submittal_id"], DETAILER))["state"]
            == "APPROVED"
        )

        validate_error(
            api_client.create_fabrication_release(
                f.create_fabrication_release_payload(
                    ctx["package_id"],
                    ctx["submittal_id"],
                    ctx["glass_order_id"],
                    [zone_id],
                    frozen["version"],
                ),
                PM,
            ),
            ApiErrorId.ERR_ENGINEERING_POSTURE_FROZEN.value,
            expected_status=422,
        )
        validate_error(
            api_client.set_anchors(zone_id, f.set_anchors_payload(), SUPERINTENDENT),
            ApiErrorId.ERR_ENGINEERING_POSTURE_FROZEN.value,
            expected_status=422,
        )
        assert (
            get_success_data(api_client.get_installation_zone(zone_id, PM))["install_status"]
            == "PLANNED"
        )
        assert fx.refresh_package(ctx)["state"] == "MOCKUP_QUALIFIED"

        fx.resubmit_submittal(
            ctx,
            "SD-903",
            submittal_id=escalated_id,
            dispute_resolution_ref="RFI-4410-RESOLVED",
        )
        assert fx.refresh_package(ctx)["engineering_posture"] == "OPEN"

        release = validate_success(
            api_client.create_fabrication_release(
                f.create_fabrication_release_payload(
                    ctx["package_id"],
                    ctx["submittal_id"],
                    ctx["glass_order_id"],
                    [zone_id],
                    fx.package_version(ctx),
                ),
                PM,
            ),
            expected_status=201,
        )
        assert release["state"] == "RELEASED"
        assert fx.refresh_package(ctx)["state"] == "IN_FABRICATION"

        anchored = validate_success(
            api_client.set_anchors(zone_id, f.set_anchors_payload(), SUPERINTENDENT),
            expected_status=200,
        )
        assert anchored["install_status"] == "ANCHORS_SET"
        assert fx.refresh_package(ctx)["state"] == "IN_INSTALLATION"


class TestHangingOutsideTheReservedWindow:
    """The hang's reservation must be live, must be this zone's, and must still
    be running on the logical clock."""

    @staticmethod
    def _anchored_zone_whose_window_has_closed():
        ctx = fx.setup_released_zone(zone_count=2)
        zone_a, zone_b = ctx["zone_ids"][0], ctx["zone_ids"][1]
        fx.prepare_zone_for_hang(ctx, zone_a)
        first = ctx["reservations"][zone_a]
        foreign = fx.create_reservation(
            ctx, zone_b, "2026-08-12T06:00:00Z", "2026-08-12T18:00:00Z"
        )
        fx.set_clock("2026-08-10T19:00:00Z")
        return ctx, zone_a, first, foreign

    def test_an_expired_window_and_a_foreign_zones_reservation_are_both_refused(self):
        """An hour after the window closes the hang is refused, so is a hang naming
        the other zone's reservation, and the zone is still waiting at its anchors
        with the original reservation unconsumed.

        PRD: "And the referenced reservation must have `status` `RESERVED`, must belong to this same zone, and the current logical-clock instant must fall inside its half-open window — at or after `window_start` and strictly before `window_end`; otherwise the request is refused with `ERR_HOIST_WINDOW_INVALID`."

        Design: Corner/errors/hanging_outside_the_reserved_window_is_rejected
        """
        ctx, zone_a, first, foreign = self._anchored_zone_whose_window_has_closed()
        assert first["window_start"] == "2026-08-10T06:00:00.000Z"
        assert first["window_end"] == "2026-08-10T18:00:00.000Z"

        validate_error(
            api_client.hang_panels(
                zone_a, f.hang_panels_payload(first["id"]), SUPERINTENDENT
            ),
            ApiErrorId.ERR_HOIST_WINDOW_INVALID.value,
            expected_status=422,
        )
        validate_error(
            api_client.hang_panels(
                zone_a, f.hang_panels_payload(foreign["id"]), SUPERINTENDENT
            ),
            ApiErrorId.ERR_HOIST_WINDOW_INVALID.value,
            expected_status=422,
        )

        zone = get_success_data(api_client.get_installation_zone(zone_a, PM))
        assert zone["install_status"] == "ANCHORS_SET"
        assert zone["hang_completed_at"] is None
        assert zone["provisional_labor_cost_cents"] is None
        assert (
            get_success_data(api_client.get_hoist_reservation(first["id"], PM))["status"]
            == "RESERVED"
        )
        assert (
            get_success_data(api_client.get_hoist_reservation(foreign["id"], PM))["status"]
            == "RESERVED"
        )

    def test_a_fresh_window_opened_past_the_buffer_lets_the_same_zone_hang(self):
        """The closed window's blocked interval ends at 18:45, so a 19:00 booking is
        accepted, and hanging inside it succeeds — consuming only the new reservation
        and leaving the expired one exactly where it was.

        PRD: "On success the zone stamps `hang_completed_at` from the logical clock, the referenced reservation transitions `RESERVED` → `CONSUMED`, and the zone's forward-looking labor estimate is written as described in §3.7."

        Design: Corner/errors/hanging_outside_the_reserved_window_is_rejected
        """
        ctx, zone_a, first, foreign = self._anchored_zone_whose_window_has_closed()
        assert first["blocked_until"] == "2026-08-10T18:45:00.000Z"

        replacement = validate_success(
            api_client.create_hoist_reservation(
                f.create_hoist_reservation_payload(
                    ctx["rig_id"], zone_a, "2026-08-10T19:00:00Z", "2026-08-10T22:00:00Z"
                ),
                SUPERINTENDENT,
            ),
            expected_status=201,
        )
        assert replacement["status"] == "RESERVED"

        hung = validate_success(
            api_client.hang_panels(
                zone_a, f.hang_panels_payload(replacement["id"]), SUPERINTENDENT
            ),
            expected_status=200,
        )
        assert hung["install_status"] == "PANELS_HUNG"
        assert hung["hang_completed_at"] == "2026-08-10T19:00:00.000Z"
        assert hung["provisional_labor_cost_cents"] == 940800
        assert hung["consumed_crew_hours"] == pytest.approx(0.0, abs=0.01)

        assert (
            get_success_data(api_client.get_hoist_reservation(replacement["id"], PM))["status"]
            == "CONSUMED"
        )
        assert (
            get_success_data(api_client.get_hoist_reservation(first["id"], PM))["status"]
            == "RESERVED"
        )
