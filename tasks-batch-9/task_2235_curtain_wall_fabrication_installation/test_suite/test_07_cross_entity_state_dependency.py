"""Writes whose admissibility is decided entirely by the state of other rows:
the embed survey that unlocks a zone, the mockup and submittal that unlock a
release, and the full set of lots that unlocks a hang."""
from prd_bench_local_runner.testing import get_success_data, validate_error, validate_success

from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.constants import CLOCK_HANG_DAY
from test_helpers.test_users import TEST_USERS

PM = TEST_USERS["cw_project_manager_headers"]
PROCUREMENT = TEST_USERS["glazing_procurement_headers"]
STRUCTURAL = TEST_USERS["structural_contractor_headers"]
SUPERINTENDENT = TEST_USERS["field_superintendent_headers"]


class TestAnchorStepGatedByTheEmbedSurvey:
    """The zone advances on evidence stored on a different entity."""

    @staticmethod
    def _released_zone_with_a_pending_survey():
        ctx = fx.setup_released_zone()
        zone_id = ctx["zone_ids"][0]
        survey = fx.open_embed_survey(ctx, zone_id, planned_anchor_count=72)
        return ctx, zone_id, survey

    def test_deviation_equal_to_the_tolerance_rejects_and_a_rejected_survey_refuses_the_pour(self):
        """Anchors cannot be set while the survey is only PENDING_SURVEY, a
        deviation of exactly 25.0 against a 25.0 tolerance rejects, and the
        rejected survey refuses the pour without leaving its state.

        PRD: "The outcome is `ACCEPTED` only when both conditions hold: the `surveyed_anchor_count` equals the `planned_anchor_count`, and the `max_deviation_mm` is strictly less than the survey's `tolerance_mm`."

        Design: Difficulty/cross_entity_state_dependency/zone_anchor_step_gated_by_separate_embed_survey_entity_state
        """
        ctx, zone_id, survey = self._released_zone_with_a_pending_survey()
        assert survey["state"] == "PENDING_SURVEY"
        assert survey["tolerance_mm"] == 25.0
        assert survey["survey_attempt_count"] == 0

        while_pending = api_client.set_anchors(zone_id, f.set_anchors_payload(), SUPERINTENDENT)
        validate_error(
            while_pending,
            ApiErrorId.ERR_EMBED_SURVEY_NOT_ACCEPTED.value,
            expected_status=422,
        )

        at_tolerance = fx.record_survey(
            ctx, zone_id, surveyed_anchor_count=72, max_deviation_mm=25.0
        )
        assert at_tolerance["state"] == "REJECTED"
        assert at_tolerance["survey_attempt_count"] == 1

        early_pour = api_client.confirm_pour(
            survey["id"], f.confirm_pour_payload("2026-08-06T12:00:00Z"), STRUCTURAL
        )
        validate_error(
            early_pour,
            ApiErrorId.ERR_POUR_BEFORE_ACCEPTANCE.value,
            expected_status=422,
        )
        assert (
            get_success_data(api_client.get_embed_survey(survey["id"], STRUCTURAL))["state"]
            == "REJECTED"
        )

    def test_acceptance_alone_does_not_unlock_the_zone_but_the_pour_does(self):
        """A re-survey at 24.9 accepts on its second attempt, yet the anchors are
        still refused until the pour is confirmed, and the successful anchor step
        bubbles the package into installation on the erection axis only.

        PRD: "The zone must have an embed survey in state `POURED`, or the request is refused with `ERR_EMBED_SURVEY_NOT_ACCEPTED`; an accepted-but-unpoured survey is not sufficient."

        Design: Difficulty/cross_entity_state_dependency/zone_anchor_step_gated_by_separate_embed_survey_entity_state
        """
        ctx, zone_id, survey = self._released_zone_with_a_pending_survey()
        assert fx.refresh_package(ctx)["state"] == "IN_FABRICATION"
        fx.record_survey(ctx, zone_id, surveyed_anchor_count=72, max_deviation_mm=25.0)

        accepted = fx.record_survey(
            ctx, zone_id, surveyed_anchor_count=72, max_deviation_mm=24.9
        )
        assert accepted["state"] == "ACCEPTED"
        assert accepted["survey_attempt_count"] == 2

        while_unpoured = api_client.set_anchors(
            zone_id, f.set_anchors_payload(), SUPERINTENDENT
        )
        validate_error(
            while_unpoured,
            ApiErrorId.ERR_EMBED_SURVEY_NOT_ACCEPTED.value,
            expected_status=422,
        )

        poured = fx.confirm_pour(ctx, zone_id, "2026-08-06T12:00:00Z")
        assert poured["state"] == "POURED"
        assert poured["poured_at"] == "2026-08-06T12:00:00.000Z"

        zone = validate_success(
            api_client.set_anchors(zone_id, f.set_anchors_payload(), SUPERINTENDENT),
            expected_status=200,
        )
        assert zone["install_status"] == "ANCHORS_SET"
        assert zone["weather_status"] == "NOT_TIGHT"
        assert fx.refresh_package(ctx)["state"] == "IN_INSTALLATION"


class TestReleaseAdmissibilityFlipsOnOtherRows:
    """One unchanged payload is refused twice and then accepted."""

    @staticmethod
    def _package_blocked_by_a_failed_mockup():
        ctx = fx.new_project()
        fx.add_failed_mockup(ctx)
        fx.create_submittal(ctx)
        fx.seal_submittal(ctx)
        fx.start_review(ctx)
        fx.add_received_glass_order(ctx, ordered_lites=240)
        fx.add_zone_a(ctx)
        return ctx

    @staticmethod
    def _attempt_release(ctx):
        return api_client.create_fabrication_release(
            f.create_fabrication_release_payload(
                ctx["package_id"],
                ctx["submittal_id"],
                ctx["glass_order_id"],
                list(ctx["zone_ids"]),
                fx.package_version(ctx),
            ),
            PM,
        )

    @staticmethod
    def _pass_the_retest(ctx):
        first = ctx["mockups"][0]
        retest = get_success_data(
            api_client.create_mockup_test(
                f.create_mockup_test_payload(
                    ctx["package_id"],
                    ctx["lab_id"],
                    window_start="2026-08-06T06:00:00Z",
                    window_end="2026-08-06T20:00:00Z",
                    retest_of_test_id=first["id"],
                    attempt_no=2,
                ),
                PM,
            )
        )
        ctx["mockups"].append(retest)
        ctx["mockup_id"] = retest["id"]
        return fx.record_mockup_result(ctx, retest["id"])

    def test_qualifying_the_mockup_changes_which_gate_refuses_the_same_payload(self):
        """Release admissibility is ordered, so the unreviewed submittal masks the
        unqualified mockup; once the submittal is approved the byte-identical
        request is refused for the mockup instead, and passing a retest qualifies
        the package.

        PRD: "Release admissibility, in this internal order: `ERR_SUBMITTAL_NOT_APPROVED` (422), then `ERR_ENGINEERING_POSTURE_FROZEN` (422), then `ERR_MOCKUP_NOT_QUALIFIED` (422)."

        PRD: "The package's `mockup_qualified` must be true — meaning some mockup test of the package has reached `PASSED` — or the release is refused with `ERR_MOCKUP_NOT_QUALIFIED`."

        Design: Difficulty/cross_entity_state_dependency/release_admissibility_flips_on_other_entities_states_with_identical_payload
        """
        ctx = self._package_blocked_by_a_failed_mockup()
        assert fx.refresh_package(ctx)["mockup_qualified"] is False

        first_attempt = self._attempt_release(ctx)
        validate_error(
            first_attempt,
            ApiErrorId.ERR_SUBMITTAL_NOT_APPROVED.value,
            expected_status=422,
        )

        fx.review_submittal(ctx, "APPROVED")
        assert fx.refresh_package(ctx)["mockup_qualified"] is False

        second_attempt = self._attempt_release(ctx)
        validate_error(
            second_attempt, ApiErrorId.ERR_MOCKUP_NOT_QUALIFIED.value, expected_status=422
        )

        passed = self._pass_the_retest(ctx)
        assert passed["state"] == "PASSED"
        qualified = fx.refresh_package(ctx)
        assert qualified["mockup_qualified"] is True
        assert qualified["state"] == "MOCKUP_QUALIFIED"

    def test_a_restricted_posture_does_not_block_the_release_once_both_parents_are_ready(self):
        """With the mockup passed and the submittal approved the same payload is
        accepted, even though the failed mockup's critical defect still holds the
        package at RESTRICTED, because only FROZEN blocks a release.

        PRD: "The package's `engineering_posture` must not be `FROZEN`, or the release is refused with `ERR_ENGINEERING_POSTURE_FROZEN`."

        Design: Difficulty/cross_entity_state_dependency/release_admissibility_flips_on_other_entities_states_with_identical_payload
        """
        ctx = self._package_blocked_by_a_failed_mockup()
        self._attempt_release(ctx)
        self._pass_the_retest(ctx)
        self._attempt_release(ctx)
        fx.review_submittal(ctx, "APPROVED")

        restricted = fx.refresh_package(ctx)
        assert restricted["engineering_posture"] == "RESTRICTED"
        assert restricted["open_critical_defect_count"] == 1

        release = validate_success(self._attempt_release(ctx), expected_status=201)
        assert release["state"] == "RELEASED"
        assert release["lot_count"] == 1
        assert release["system_type_at_release"] == "UNITIZED"

        lots = get_success_data(
            api_client.list_panel_lots(PM, params={"zone_id": ctx["zone_ids"][0]})
        )
        assert len(lots) == 1
        assert lots[0]["panel_count"] == 36
        assert lots[0]["lite_count"] == 72
        assert lots[0]["fabrication_status"] == "BATCHED"

        order = fx.refresh_glass_order(ctx)
        assert order["allocated_lites"] == 72
        assert order["unallocated_lites"] == 161
        assert fx.refresh_package(ctx)["state"] == "IN_FABRICATION"


class TestHangRequiresEveryLotOfTheZone:
    """The shipment gate is universally quantified over the zone's lots."""

    @staticmethod
    def _anchored_zone_with_one_shipped_and_one_glazed_lot():
        ctx = fx.setup_released_zone()
        zone_id = ctx["zone_ids"][0]
        first_lot = ctx["lots"][zone_id][0]
        fx.advance_lot(ctx, first_lot["id"], "GLAZED")
        fx.advance_lot(ctx, first_lot["id"], "SHIPPED")
        fx.add_poured_embeds(ctx, zone_id)
        fx.set_anchors(ctx, zone_id)

        fx.create_release(ctx, zone_ids=[zone_id], panels_per_zone=18)
        second_lot = ctx["lots"][zone_id][-1]
        fx.advance_lot(ctx, second_lot["id"], "GLAZED")

        fx.create_rig(ctx)
        fx.create_reservation(
            ctx, zone_id, "2026-08-10T06:00:00Z", "2026-08-10T18:00:00Z"
        )
        fx.set_clock(CLOCK_HANG_DAY)
        return ctx, zone_id, first_lot, second_lot

    def test_one_shipped_lot_is_not_enough_while_a_sibling_lot_is_only_glazed(self):
        """The zone holds two lots, one SHIPPED and one GLAZED, and the hang is
        refused for the unshipped one without consuming the reservation.

        PRD: "The zone must have at least one panel lot and **every** panel lot pointing at the zone must have reached `fabrication_status` `SHIPPED` — a zone with no lots at all, or with a single lot still `BATCHED`, `GLAZED` or `ON_HOLD`, is refused with `ERR_PANEL_LOTS_NOT_SHIPPED`."

        Design: Difficulty/cross_entity_state_dependency/hang_requires_every_lot_of_the_zone_shipped_not_just_one
        """
        ctx, zone_id, first_lot, second_lot = (
            self._anchored_zone_with_one_shipped_and_one_glazed_lot()
        )
        reservation_id = ctx["reservations"][zone_id]["id"]

        lots = get_success_data(
            api_client.list_panel_lots(PM, params={"zone_id": zone_id})
        )
        assert len(lots) == 2
        assert sorted(row["fabrication_status"] for row in lots) == ["GLAZED", "SHIPPED"]

        refused = api_client.hang_panels(
            zone_id, f.hang_panels_payload(reservation_id), SUPERINTENDENT
        )
        validate_error(
            refused, ApiErrorId.ERR_PANEL_LOTS_NOT_SHIPPED.value, expected_status=422
        )

        zone = get_success_data(api_client.get_installation_zone(zone_id, PM))
        assert zone["install_status"] == "ANCHORS_SET"
        assert zone["provisional_labor_cost_cents"] is None
        assert (
            get_success_data(api_client.get_hoist_reservation(reservation_id, PM))["status"]
            == "RESERVED"
        )

    def test_shipping_the_second_lot_closes_both_releases_and_lets_the_hang_land(self):
        """Shipping the replacement lot stamps it from the logical clock and
        closes both releases, after which the same hang succeeds, consumes the
        reservation and prices the estimate from the zone's planned panel count
        rather than from the 54 panels the two lots contain.

        PRD: "Shipping also triggers two bubble-up closures: when every lot of the release has reached `SHIPPED`, the release transitions `RELEASED` → `CLOSED`; and when every lot of the glass order has reached `SHIPPED` and the order's `unallocated_lites` is 0, the order transitions `RECEIVED` → `CLOSED`."

        Design: Difficulty/cross_entity_state_dependency/hang_requires_every_lot_of_the_zone_shipped_not_just_one
        """
        ctx, zone_id, first_lot, second_lot = (
            self._anchored_zone_with_one_shipped_and_one_glazed_lot()
        )
        reservation_id = ctx["reservations"][zone_id]["id"]
        api_client.hang_panels(zone_id, f.hang_panels_payload(reservation_id), SUPERINTENDENT)

        shipped = fx.advance_lot(ctx, second_lot["id"], "SHIPPED")
        assert shipped["fabrication_status"] == "SHIPPED"
        assert shipped["shipped_at"] == "2026-08-10T09:00:00.000Z"

        for release in ctx["releases"]:
            row = get_success_data(api_client.get_fabrication_release(release["id"], PM))
            assert row["state"] == "CLOSED"

        zone = validate_success(
            api_client.hang_panels(
                zone_id, f.hang_panels_payload(reservation_id), SUPERINTENDENT
            ),
            expected_status=200,
        )
        assert zone["install_status"] == "PANELS_HUNG"
        assert zone["hang_completed_at"] == "2026-08-10T09:00:00.000Z"
        assert zone["provisional_labor_cost_cents"] == 940800
        assert zone["weather_status"] == "NOT_TIGHT"
        assert zone["final_labor_cost_cents"] is None
        assert (
            get_success_data(api_client.get_hoist_reservation(reservation_id, PM))["status"]
            == "CONSUMED"
        )
