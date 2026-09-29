"""Requests that break two rules at once, where only the higher-ranked rule is
allowed to speak."""
from prd_bench_local_runner.testing import get_success_data, validate_error

from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.constants import CLOCK_HANG_DAY, USER_IDS
from test_helpers.test_users import TEST_USERS

PM = TEST_USERS["cw_project_manager_headers"]
SUPERINTENDENT = TEST_USERS["field_superintendent_headers"]


def _zone_awaiting_anchors():
    """A released zone whose lot is still batched and whose anchors were never
    set, with a live reservation covering the logical clock."""
    ctx = fx.setup_released_zone()
    zone_id = ctx["zone_ids"][0]
    fx.add_poured_embeds(ctx, zone_id)
    fx.create_rig(ctx)
    fx.create_reservation(
        ctx, zone_id, "2026-08-10T06:00:00Z", "2026-08-10T18:00:00Z"
    )
    fx.set_clock(CLOCK_HANG_DAY)
    return ctx, zone_id


class TestZoneSequenceBeforePanelLotShipment:
    """Both the sequence defect and the unshipped lot hold on one hang call."""

    def test_planned_zone_with_batched_lot_reports_only_the_sequence_violation(self):
        """The zone is in PLANNED and its only lot is BATCHED, so both blockers
        are live, yet the hang call reports the sequence violation alone and
        leaves every row it touched untouched.

        PRD: "A zone still in `PLANNED` whose lots are unshipped reports the sequence violation, not the unshipped-lot error, because the zone-sequence check outranks the panel-lot readiness check."

        Design: Difficulty/priority_pair_validation_conflict/zone_sequence_error_precedes_panel_lot_shipment_error
        """
        ctx, zone_id = _zone_awaiting_anchors()
        lot_id = ctx["lots"][zone_id][0]["id"]
        reservation_id = ctx["reservations"][zone_id]["id"]
        before = get_success_data(api_client.get_installation_zone(zone_id, PM))
        assert before["install_status"] == "PLANNED"
        assert (
            get_success_data(api_client.get_panel_lot(lot_id, PM))["fabrication_status"]
            == "BATCHED"
        )

        refused = api_client.hang_panels(
            zone_id, f.hang_panels_payload(reservation_id), SUPERINTENDENT
        )
        error = validate_error(
            refused, ApiErrorId.ERR_ZONE_SEQUENCE_VIOLATION.value, expected_status=409
        )
        assert error["error_id"] != ApiErrorId.ERR_PANEL_LOTS_NOT_SHIPPED.value

        after = get_success_data(api_client.get_installation_zone(zone_id, PM))
        assert after["install_status"] == "PLANNED"
        assert after["provisional_labor_cost_cents"] is None
        assert after["version"] == before["version"]
        assert (
            get_success_data(api_client.get_hoist_reservation(reservation_id, PM))["status"]
            == "RESERVED"
        )

    def test_repairing_the_sequence_uncovers_the_masked_unshipped_lot_error(self):
        """Setting the anchors moves the zone to ANCHORS_SET and increments its
        version exactly once, and the very same hang call then reports the
        unshipped panel lot without consuming the reservation.

        PRD: "The zone must have at least one panel lot and **every** panel lot pointing at the zone must have reached `fabrication_status` `SHIPPED` — a zone with no lots at all, or with a single lot still `BATCHED`, `GLAZED` or `ON_HOLD`, is refused with `ERR_PANEL_LOTS_NOT_SHIPPED`."

        Design: Difficulty/priority_pair_validation_conflict/zone_sequence_error_precedes_panel_lot_shipment_error
        """
        ctx, zone_id = _zone_awaiting_anchors()
        lot_id = ctx["lots"][zone_id][0]["id"]
        reservation_id = ctx["reservations"][zone_id]["id"]
        before = get_success_data(api_client.get_installation_zone(zone_id, PM))

        api_client.hang_panels(
            zone_id, f.hang_panels_payload(reservation_id), SUPERINTENDENT
        )
        anchored = get_success_data(
            api_client.set_anchors(zone_id, f.set_anchors_payload(), SUPERINTENDENT)
        )
        assert anchored["install_status"] == "ANCHORS_SET"
        assert anchored["version"] == before["version"] + 1

        refused = api_client.hang_panels(
            zone_id, f.hang_panels_payload(reservation_id), SUPERINTENDENT
        )
        validate_error(
            refused, ApiErrorId.ERR_PANEL_LOTS_NOT_SHIPPED.value, expected_status=422
        )

        lot = get_success_data(api_client.get_panel_lot(lot_id, PM))
        assert lot["fabrication_status"] == "BATCHED"
        zone = get_success_data(api_client.get_installation_zone(zone_id, PM))
        assert zone["install_status"] == "ANCHORS_SET"
        assert zone["provisional_labor_cost_cents"] is None
        reservation = get_success_data(
            api_client.get_hoist_reservation(reservation_id, PM)
        )
        assert reservation["status"] == "RESERVED"


class TestOpenCriticalDefectBeforeBillingCeiling:
    """A zone that is both unsafe to certify and too expensive to bill."""

    @staticmethod
    def _zone_over_contract_with_a_critical_defect():
        ctx = fx.setup_zone_ready_to_certify(contract_value_cents=50000000)
        zone_id = ctx["zone_ids"][0]
        defect = fx.raise_defect(
            ctx,
            user_id=USER_IDS["QC_3"],
            zone_id=zone_id,
            origin="PUNCH_LIST",
            severity="CRITICAL",
            description="displaced pressure plate at grid 4 head condition",
        )
        return ctx, zone_id, defect

    def test_critical_defect_blocks_certification_while_open_and_while_submitted(self):
        """The certification is refused for the critical defect both while it is
        OPEN and after remediation has been submitted, because the safety gate
        covers both of those statuses.

        PRD: "No defect item of the zone may have `severity` `CRITICAL` with `status` `OPEN` or `REMEDIATION_SUBMITTED`; otherwise `ERR_OPEN_CRITICAL_DEFECT`."

        Design: Difficulty/priority_pair_validation_conflict/open_critical_defect_error_masks_billing_ceiling_error
        """
        ctx, zone_id, defect = self._zone_over_contract_with_a_critical_defect()

        while_open = api_client.certify_weather_tight(
            zone_id, f.certify_weather_tight_payload(), PM
        )
        validate_error(
            while_open, ApiErrorId.ERR_OPEN_CRITICAL_DEFECT.value, expected_status=422
        )

        submitted = fx.submit_remediation(ctx, defect["id"])
        assert submitted["status"] == "REMEDIATION_SUBMITTED"

        while_submitted = api_client.certify_weather_tight(
            zone_id, f.certify_weather_tight_payload(), PM
        )
        validate_error(
            while_submitted,
            ApiErrorId.ERR_OPEN_CRITICAL_DEFECT.value,
            expected_status=422,
        )

        zone = get_success_data(api_client.get_installation_zone(zone_id, PM))
        assert zone["weather_status"] == "NOT_TIGHT"
        assert zone["weather_tight_cycle_count"] == 0

    def test_closing_the_defect_reveals_the_billing_ceiling_underneath(self):
        """Once the defect closes and the posture reopens, the same certification
        is refused for the fiscal ceiling instead, so the safety error had been
        masking it all along.

        PRD: "And a certification attempt on a zone with an open critical defect that would also bill past the contract value reports the open critical defect, because safety outranks fiscal."

        Design: Difficulty/priority_pair_validation_conflict/open_critical_defect_error_masks_billing_ceiling_error
        """
        ctx, zone_id, defect = self._zone_over_contract_with_a_critical_defect()
        fx.submit_remediation(ctx, defect["id"])
        closed = fx.reinspect_defect(ctx, defect["id"], "PASS", USER_IDS["QC_1"])
        assert closed["status"] == "CLOSED"

        package = fx.refresh_package(ctx)
        assert package["open_critical_defect_count"] == 0
        assert package["engineering_posture"] == "OPEN"

        refused = api_client.certify_weather_tight(
            zone_id, f.certify_weather_tight_payload(), PM
        )
        validate_error(
            refused, ApiErrorId.ERR_BILLING_EXCEEDS_CONTRACT.value, expected_status=422
        )

        zone = get_success_data(api_client.get_installation_zone(zone_id, PM))
        assert zone["weather_status"] == "NOT_TIGHT"
        assert zone["certified_line_cents"] is None
        final = fx.refresh_package(ctx)
        assert final["earned_value_certified_cents"] == 0
        assert final["state"] == "IN_INSTALLATION"
        assert final["contract_value_cents"] == 50000000


class TestSubmittalApprovalBeforeGlassBalance:
    """A release request that is wrong referentially and wrong on capacity."""

    @staticmethod
    def _release_blocked_two_ways():
        ctx = fx.setup_qualified_package()
        fx.create_submittal(ctx)
        fx.seal_submittal(ctx)
        fx.start_review(ctx)
        fx.add_received_glass_order(ctx, ordered_lites=20, quoted_lead_time_days=60)
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
                panels_per_zone=36,
                lites_per_panel=2,
            ),
            PM,
        )

    def test_undecided_submittal_reports_admissibility_not_the_lite_shortfall(self):
        """The submittal is only UNDER_REVIEW and the 72 requested lites exceed
        the 20 available, yet the refusal names the submittal and nothing is
        created.

        PRD: "A release quoting an unapproved submittal against an order with insufficient glass reports the unapproved submittal, because release admissibility outranks capacity."

        Design: Difficulty/priority_pair_validation_conflict/submittal_approval_error_precedes_glass_balance_error_on_release
        """
        ctx = self._release_blocked_two_ways()
        assert ctx["submittal"]["state"] == "UNDER_REVIEW"

        refused = self._attempt_release(ctx)
        error = validate_error(
            refused, ApiErrorId.ERR_SUBMITTAL_NOT_APPROVED.value, expected_status=422
        )
        assert error["error_id"] != ApiErrorId.ERR_GLASS_BALANCE_INSUFFICIENT.value

        releases = get_success_data(api_client.list_fabrication_releases(PM))
        assert releases == []
        lots = get_success_data(api_client.list_panel_lots(PM))
        assert lots == []
        assert fx.refresh_package(ctx)["state"] == "MOCKUP_QUALIFIED"

    def test_approving_the_submittal_exposes_the_glass_balance_shortfall(self):
        """With the submittal APPROVED and a freshly read package version, the
        identical request is refused for the lite shortfall against a ledger that
        reserves nothing for breakage.

        PRD: "The glass balance must cover the request: the total requested panel count across the covered zones, multiplied by the standard glazing content of two lites per panel, must not exceed the order's `unallocated_lites`, or the release is refused with `ERR_GLASS_BALANCE_INSUFFICIENT`."

        Design: Difficulty/priority_pair_validation_conflict/submittal_approval_error_precedes_glass_balance_error_on_release
        """
        ctx = self._release_blocked_two_ways()
        self._attempt_release(ctx)

        approved = fx.review_submittal(ctx, "APPROVED")
        assert approved["state"] == "APPROVED"
        assert approved["open_notes_count"] == 0

        refused = self._attempt_release(ctx)
        validate_error(
            refused, ApiErrorId.ERR_GLASS_BALANCE_INSUFFICIENT.value, expected_status=422
        )
        assert (
            refused.json()["data"]["error_id"]
            != ApiErrorId.ERR_STALE_PACKAGE_VERSION.value
        )

        order = fx.refresh_glass_order(ctx)
        assert order["committable_lites"] == 20
        assert order["allocated_lites"] == 0
        assert order["breakage_stock_lites"] == 0
        assert order["unallocated_lites"] == 20
        assert get_success_data(api_client.list_fabrication_releases(PM)) == []
