"""Declared lifecycle transitions and the rejection of undeclared ones.

Every aggregate in the manufacturing chain publishes a fixed set of admissible
transitions, and this module walks them from both sides.  The forward checks pin
the entry states and the cascades that one transition drives in the same request
- a fresh pour opening with the whole heat provisionally good, certification
lifting the build order to `TESTED`, shipment closing the order and the enquiry.
The rejection checks pin the other half of the contract: a transition that is
not declared from the aggregate's current state is refused with that aggregate's
own invalid-state identifier and changes nothing at all, so a replayed or
skipped step can never quietly rewind or advance the record.
"""

import pytest

from test_helpers import (
    ApiErrorId,
    assertions as A,
    constants as K,
    factories as F,
    fixtures as X,
    get_success_data,
    validate_error,
    validate_success,
)
from test_helpers.test_users import PLATFORM_ADMIN


def _reread_foundry(api, foundry_id):
    """Read one foundry back, as any role may."""
    return get_success_data(api.get_foundry(foundry_id, PLATFORM_ADMIN))


# ─────────────────────────────────────────────────────────────────────────────
# Foundry
# ─────────────────────────────────────────────────────────────────────────────
class TestFoundryLifecycle:
    """A foundry has exactly one transition, and SUSPENDED is terminal."""

    def test_suspending_an_active_foundry_stores_the_reason_and_bumps_the_version(
        self, api, admin_headers
    ):
        """The single declared foundry transition, with its recorded reason.

        A newly registered foundry is ACTIVE with a null suspension_reason.  An
        administrator may suspend an ACTIVE foundry, moving it ACTIVE to
        SUSPENDED and storing the supplied suspension_reason verbatim.  The
        suspension is a mutation of the foundry, so its version advances from the
        1 it was created with to 2.

        Design: Corner/state_machines/suspend_active_foundry_moves_to_suspended
        """
        foundry = X.create_foundry(api)
        assert foundry["status"] == "ACTIVE"
        assert foundry["suspension_reason"] is None
        assert foundry["version"] == 1

        response = api.suspend_foundry(
            foundry["id"],
            F.suspend_foundry_payload(
                suspension_reason="failed annual alloy audit"
            ),
            admin_headers,
        )
        suspended = validate_success(response, 200)

        A.assert_foundry(suspended)
        assert suspended["status"] == "SUSPENDED"
        assert suspended["suspension_reason"] == "failed annual alloy audit"
        assert suspended["version"] == 2

    def test_a_second_suspension_is_refused_and_preserves_the_first_reason(
        self, api, admin_headers
    ):
        """Suspending twice is a rejection, not an idempotent success.

        SUSPENDED is terminal, so a second suspension attempt is rejected with
        ERR_FOUNDRY_SUSPENDED.  Because the request is refused before anything is
        written, the reason recorded by the first suspension stands unchanged and
        the version does not advance a second time.

        Design: Corner/state_machines/second_suspend_on_suspended_foundry_returns_foundry_suspended
        """
        foundry = X.create_foundry(api)
        get_success_data(
            api.suspend_foundry(
                foundry["id"],
                F.suspend_foundry_payload(
                    suspension_reason="failed annual alloy audit"
                ),
                admin_headers,
            )
        )

        response = api.suspend_foundry(
            foundry["id"],
            F.suspend_foundry_payload(suspension_reason="second attempt"),
            admin_headers,
        )
        validate_error(response, ApiErrorId.FOUNDRY_SUSPENDED)

        unchanged = _reread_foundry(api, foundry["id"])
        assert unchanged["status"] == "SUSPENDED"
        assert unchanged["suspension_reason"] == "failed annual alloy audit"
        assert unchanged["version"] == 2


# ─────────────────────────────────────────────────────────────────────────────
# Casting lot
# ─────────────────────────────────────────────────────────────────────────────
class TestCastingLotLifecycle:
    """A lot opens POURED with a full ledger and never re-enters inspection."""

    def test_a_fresh_pour_opens_poured_with_the_whole_heat_provisionally_good(
        self, api
    ):
        """The piece ledger starts at a full count and only ever falls.

        A new lot is POURED, with qty_scrapped and qty_rework_pending at 0,
        qty_accepted equal to qty_poured and committed_build_count at 0, so the
        conservation identity holds from the very first instant and every later
        movement is a reduction from a full heat.  Recording the pour also
        advances the tooling: pours_since_refurb is incremented by 1 and the
        wear index, being pours_since_refurb plus twice
        defect_pours_since_refurb, follows it to 1 - far below the pattern's
        withdrawal threshold of 20, so the tooling stays QUALIFIED.

        Design: Corner/state_machines/new_casting_lot_starts_poured_with_full_piece_ledger
        """
        world = X.setup_master_data(api)

        response = api.create_casting_lot(
            F.casting_lot_payload(
                world["pattern"]["id"], world["foundry"]["id"], qty_poured=4
            ),
            world["foundry_headers"],
        )
        lot = validate_success(response, 201)

        A.assert_casting_lot(lot)
        assert lot["status"] == "POURED"
        assert lot["qty_poured"] == 4
        assert lot["qty_accepted"] == 4
        assert lot["qty_scrapped"] == 0
        assert lot["qty_rework_pending"] == 0
        assert lot["committed_build_count"] == 0

        pattern = X.reread_pattern_asset(api, world["pattern"]["id"])
        assert pattern["pours_since_refurb"] == 1
        assert pattern["defect_pours_since_refurb"] == 0
        assert pattern["wear_index"] == 1
        assert pattern["status"] == "QUALIFIED"
        A.assert_wear_index(pattern)

    def test_replaying_inspect_against_an_accepted_lot_is_refused(
        self, api, inspector_headers
    ):
        """Inspection is declared from POURED and REWORK only.

        An inspector inspects a lot from either POURED or REWORK, in both cases
        landing on INSPECTED, so an already ACCEPTED lot admits no further
        inspection and the replay is rejected with
        ERR_CASTING_LOT_INVALID_STATE.  The acceptance is not rewound: the lot
        stays ACCEPTED at the version it reached, with its ledger untouched.

        Design: Corner/state_machines/second_inspect_on_accepted_lot_returns_casting_lot_invalid_state
        """
        world = X.setup_master_data(api)
        lot = X.setup_accepted_lot(api, world)
        assert lot["status"] == "ACCEPTED"
        version_at_acceptance = lot["version"]

        response = api.inspect_casting_lot(lot["id"], inspector_headers)
        validate_error(response, ApiErrorId.CASTING_LOT_INVALID_STATE)

        unchanged = X.reread_casting_lot(api, lot["id"])
        assert unchanged["status"] == "ACCEPTED"
        assert unchanged["version"] == version_at_acceptance
        assert unchanged["qty_accepted"] == 4


# ─────────────────────────────────────────────────────────────────────────────
# Casting defect
# ─────────────────────────────────────────────────────────────────────────────
class TestCastingDefectLifecycle:
    """USE_AS_IS binds an identity; repair sign-off binds a prior disposition."""

    def test_use_as_is_is_refused_to_the_reporter_and_granted_to_a_colleague(
        self, api, inspector_headers, other_inspector_headers
    ):
        """The only disposition that compares the actor against a stored identity.

        USE_AS_IS carries a segregation-of-duties requirement: the acting user
        must differ from reported_by_user_id, else ERR_SEGREGATION_OF_DUTIES.
        The inspector who logged the defect is therefore refused even though the
        role itself is authorised, and the defect stays REPORTED.  A second
        inspector applying the identical disposition succeeds, landing on the
        terminal DISPOSITIONED_USE_AS_IS with their own identity recorded.
        USE_AS_IS leaves the lot's piece ledger entirely unchanged, so all four
        pieces remain accepted through both attempts.

        Design: Corner/state_machines/use_as_is_disposition_by_the_reporting_user_returns_segregation_of_duties
        """
        world = X.setup_master_data(api)
        lot = X.pour_casting_lot(api, world)
        defect = X.report_defect(
            api,
            lot["id"],
            headers=inspector_headers,
            severity="MINOR",
            affected_qty=1,
        )
        assert defect["reported_by_user_id"] == inspector_headers["X-User-ID"]
        assert defect["status"] == "REPORTED"

        refused = api.disposition_casting_defect(
            defect["id"], F.disposition_payload("USE_AS_IS"), inspector_headers
        )
        validate_error(refused, ApiErrorId.SEGREGATION_OF_DUTIES)

        still_reported = X.reread_casting_defect(api, defect["id"])
        assert still_reported["status"] == "REPORTED"
        assert still_reported["disposition"] is None
        assert still_reported["dispositioned_by_user_id"] is None
        assert still_reported["version"] == defect["version"]

        response = api.disposition_casting_defect(
            defect["id"], F.disposition_payload("USE_AS_IS"), other_inspector_headers
        )
        dispositioned = validate_success(response, 200)

        A.assert_casting_defect(dispositioned)
        assert dispositioned["status"] == "DISPOSITIONED_USE_AS_IS"
        assert dispositioned["disposition"] == "USE_AS_IS"
        assert (
            dispositioned["dispositioned_by_user_id"]
            == other_inspector_headers["X-User-ID"]
        )

        unchanged_lot = X.reread_casting_lot(api, lot["id"])
        assert unchanged_lot["qty_accepted"] == 4
        assert unchanged_lot["qty_scrapped"] == 0
        assert unchanged_lot["qty_rework_pending"] == 0

    def test_signing_off_a_weld_repair_that_was_never_dispositioned_is_refused(
        self, api, inspector_headers
    ):
        """Repair sign-off requires the weld-repair disposition to exist first.

        The sign-off is declared as DISPOSITIONED_REPAIR to REPAIR_VERIFIED, so
        firing it straight from REPORTED skips the disposition step and is
        rejected with ERR_DEFECT_INVALID_STATE.  Reporting alone leaves the
        ledger untouched, and because the sign-off is refused nothing moves the
        pieces either: all four stay accepted and the weld-rework column stays
        empty.

        Design: Corner/state_machines/repair_verified_on_reported_defect_returns_defect_invalid_state
        """
        world = X.setup_master_data(api)
        lot = X.pour_casting_lot(api, world)
        defect = X.report_defect(
            api,
            lot["id"],
            headers=world["foundry_headers"],
            defect_type="SHRINKAGE",
            severity="MAJOR",
            affected_qty=2,
        )

        response = api.verify_casting_defect_repair(defect["id"], inspector_headers)
        validate_error(response, ApiErrorId.DEFECT_INVALID_STATE)

        unchanged_defect = X.reread_casting_defect(api, defect["id"])
        assert unchanged_defect["status"] == "REPORTED"
        assert unchanged_defect["disposition"] is None
        assert unchanged_defect["version"] == defect["version"]

        unchanged_lot = X.reread_casting_lot(api, lot["id"])
        assert unchanged_lot["qty_accepted"] == 4
        assert unchanged_lot["qty_rework_pending"] == 0
        assert unchanged_lot["qty_scrapped"] == 0


# ─────────────────────────────────────────────────────────────────────────────
# Casting pattern
# ─────────────────────────────────────────────────────────────────────────────
class TestPatternAssetLifecycle:
    """RETIRED is terminal for tooling: nothing leads out of it."""

    def test_neither_refurbishment_nor_a_fresh_pour_may_leave_retired_tooling(
        self, api, admin_headers
    ):
        """Both exits from RETIRED are refused and the pattern stays retired.

        Retirement is permitted from QUALIFIED or WORN and both are terminal.
        Starting a refurbishment is declared only as WORN to IN_REFURB, so
        against retired tooling it is rejected with ERR_PATTERN_INVALID_STATE;
        and a pour requires the pattern to be QUALIFIED, so pouring from tooling
        that is WORN, IN_REFURB or RETIRED is rejected with the same identifier.
        Retiring the model's only pattern leaves it with no QUALIFIED tooling at
        all, which drives the model ORDERABLE to PATTERN_CONSTRAINED in the
        retirement request itself.

        Design: Corner/state_machines/refurbishment_start_on_retired_pattern_returns_pattern_invalid_state
        """
        world = X.setup_master_data(api)
        retired = get_success_data(
            api.retire_pattern_asset(world["pattern"]["id"], admin_headers)
        )
        assert retired["status"] == "RETIRED"

        refurbishment = api.start_pattern_refurbishment(
            world["pattern"]["id"], admin_headers
        )
        validate_error(refurbishment, ApiErrorId.PATTERN_INVALID_STATE)

        pour = api.create_casting_lot(
            F.casting_lot_payload(world["pattern"]["id"], world["foundry"]["id"]),
            world["foundry_headers"],
        )
        validate_error(pour, ApiErrorId.PATTERN_INVALID_STATE)

        unchanged = X.reread_pattern_asset(api, world["pattern"]["id"])
        assert unchanged["status"] == "RETIRED"
        assert unchanged["pours_since_refurb"] == 0
        assert unchanged["refurb_cycles"] == 0
        assert unchanged["version"] == retired["version"]

        assert (
            X.reread_pump_model(api, world["model"]["id"])["status"]
            == "PATTERN_CONSTRAINED"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Selection
# ─────────────────────────────────────────────────────────────────────────────
class TestSelectionLifecycle:
    """An approved duty point cannot be re-opened by re-proposing it."""

    def test_re_proposing_an_approved_selection_is_refused(
        self, api, engineer_headers
    ):
        """Proposal is declared from DRAFT and from UNDER_REVIEW, never from APPROVED.

        An engineer proposes a selection DRAFT to PROPOSED, and a selection
        returned for review re-enters the cycle UNDER_REVIEW to PROPOSED.
        APPROVED is not one of those entry states, so re-proposing an approved
        selection is rejected with ERR_SELECTION_INVALID_STATE and the approved
        duty point stands: the selection stays APPROVED at its approval version
        with the approver's identity intact, and the parent enquiry stays
        SELECTION_LOCKED rather than returning to OPEN.  Re-opening it requires
        an explicit revision or supersession instead.

        Design: Corner/state_machines/propose_on_approved_selection_returns_selection_invalid_state
        """
        ctx = X.setup_approved_selection(api)
        selection = ctx["selection"]
        assert selection["status"] == "APPROVED"
        assert ctx["duty"]["status"] == "SELECTION_LOCKED"

        response = api.propose_selection(selection["id"], engineer_headers)
        validate_error(response, ApiErrorId.SELECTION_INVALID_STATE)

        unchanged = X.reread_selection(api, selection["id"])
        assert unchanged["status"] == "APPROVED"
        assert unchanged["version"] == selection["version"]
        assert unchanged["approved_by_user_id"] == selection["approved_by_user_id"]

        assert (
            X.reread_duty_application(api, ctx["duty"]["id"])["status"]
            == "SELECTION_LOCKED"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Build order
# ─────────────────────────────────────────────────────────────────────────────
class TestBuildOrderLifecycle:
    """As-built measurements are written once, on the PLANNED to ASSEMBLED hop."""

    def test_a_second_assembly_posting_is_refused_and_keeps_the_first_readings(
        self, api, planner_headers
    ):
        """Assembly is declared only from PLANNED, so it cannot be overwritten.

        Recording machining and assembly results moves the order PLANNED to
        ASSEMBLED, and that is the only declared entry to ASSEMBLED from
        planning, so a second posting against an already assembled order is
        rejected with ERR_BUILD_ORDER_INVALID_STATE.  The as-built record is
        therefore immutable in practice: the running clearance and residual
        unbalance measured the first time survive the attempt, the order stays
        ASSEMBLED at its assembly version, and the rework counter - which only
        the rework sign-off advances - stays at 0.

        Design: Corner/state_machines/assembly_on_already_assembled_build_order_returns_build_order_invalid_state
        """
        ctx = X.setup_assembled_build_order(api)
        build_order = ctx["build_order"]
        assert build_order["status"] == "ASSEMBLED"
        assert build_order["running_clearance_mm"] == pytest.approx(0.35, abs=0.01)
        assert build_order["residual_unbalance_g_mm"] == pytest.approx(900.00, abs=0.01)

        response = api.record_assembly(
            build_order["id"],
            F.assembly_payload(
                running_clearance_mm=0.40,
                residual_unbalance_g_mm=1100.00,
                seal_flush_plan_installed="API_PLAN_11",
            ),
            planner_headers,
        )
        validate_error(response, ApiErrorId.BUILD_ORDER_INVALID_STATE)

        unchanged = X.reread_build_order(api, build_order["id"])
        assert unchanged["status"] == "ASSEMBLED"
        assert unchanged["version"] == build_order["version"]
        assert unchanged["running_clearance_mm"] == pytest.approx(0.35, abs=0.01)
        assert unchanged["residual_unbalance_g_mm"] == pytest.approx(900.00, abs=0.01)
        assert unchanged["allowable_unbalance_g_mm"] == pytest.approx(
            K.BUILD_ALLOWABLE_UNBALANCE_G_MM, abs=0.01
        )
        assert unchanged["rework_cycles"] == 0


# ─────────────────────────────────────────────────────────────────────────────
# Performance test run
# ─────────────────────────────────────────────────────────────────────────────
class TestTestRunLifecycle:
    """Certification is reachable only from EVALUATED, and it lifts the order."""

    def test_certifying_an_open_run_is_refused_and_moves_no_dimension(
        self, api, test_engineer_headers
    ):
        """Freezing and evaluation cannot be skipped on the way to CERTIFIED.

        Execution moves OPEN to POINTS_LOCKED to EVALUATED to CERTIFIED, so
        certification fired on a run that still holds its point set open is
        rejected with ERR_TEST_RUN_INVALID_STATE even though the five measured
        points the grade requires are already recorded.  All three independent
        dimensions stay where a new run starts them - run_state OPEN,
        hydraulic_status NOT_EVALUATED and npsh_status NOT_VERIFIED - the seven
        reported values stay null, and the parent build order is not lifted out
        of ASSEMBLED.

        Design: Corner/state_machines/certify_test_run_while_run_state_open_returns_test_run_invalid_state
        """
        ctx = X.setup_assembled_build_order(api)
        run = X.setup_open_test_run(api, ctx["build_order"]["id"])
        A.assert_run_dimensions(run, "OPEN", "NOT_EVALUATED", "NOT_VERIFIED")

        response = api.certify_test_run(run["id"], test_engineer_headers)
        validate_error(response, ApiErrorId.TEST_RUN_INVALID_STATE)

        unchanged = X.reread_test_run(api, run["id"])
        A.assert_run_dimensions(unchanged, "OPEN", "NOT_EVALUATED", "NOT_VERIFIED")
        A.assert_run_results_cleared(unchanged)
        assert unchanged["version"] == run["version"]

        assert (
            X.reread_build_order(api, ctx["build_order"]["id"])["status"] == "ASSEMBLED"
        )

    def test_certification_is_the_only_path_from_assembled_to_tested(
        self, api, test_engineer_headers
    ):
        """One certify request certifies the run and lifts the order to TESTED.

        Certification drives run_state from EVALUATED to the terminal CERTIFIED
        and requires both result dimensions to have passed, and it drives the
        build order ASSEMBLED to TESTED in the same request - the planner never
        moves the order by hand.  The two result dimensions are untouched by the
        certification itself, staying WITHIN_TOLERANCE and VERIFIED.  A passing
        test triggers no cascade upstream, so the selection stays APPROVED and
        the enquiry stays CONTRACTED.

        Design: Corner/state_machines/certify_cascades_build_order_assembled_to_tested
        """
        ctx = X.setup_assembled_build_order(api)
        run = X.setup_evaluated_test_run(api, ctx["build_order"]["id"])
        A.assert_run_dimensions(run, "EVALUATED", "WITHIN_TOLERANCE", "VERIFIED")
        assert (
            X.reread_build_order(api, ctx["build_order"]["id"])["status"] == "ASSEMBLED"
        )

        response = api.certify_test_run(run["id"], test_engineer_headers)
        certified = validate_success(response, 200)

        A.assert_test_run(certified)
        A.assert_run_dimensions(certified, "CERTIFIED", "WITHIN_TOLERANCE", "VERIFIED")

        assert X.reread_build_order(api, ctx["build_order"]["id"])["status"] == "TESTED"
        assert X.reread_selection(api, ctx["selection"]["id"])["status"] == "APPROVED"
        assert (
            X.reread_duty_application(api, ctx["duty"]["id"])["status"] == "CONTRACTED"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Engineered package
# ─────────────────────────────────────────────────────────────────────────────
class TestPumpPackageLifecycle:
    """Shipment closes the whole chain; lifting a hold needs a hold to exist."""

    def test_shipment_drives_the_package_the_order_and_the_enquiry_together(
        self, api, planner_headers
    ):
        """One shipment request is the terminal event of the order chain.

        Shipment drives the package RELEASED to the terminal SHIPPED and stores
        the supplied actual_ship_date that anchors the warranty clock; it drives
        the build order TESTED to CLOSED while decrementing the bound lot's
        committed_build_count by 1; and it drives the enquiry CONTRACTED to
        CLOSED, two levels up from the package.  The guarantee basis was already
        frozen at release as CERTIFIED_CURVE, because the run was witnessed, and
        shipment does not disturb it.  The selection is not on that path and
        stays APPROVED.

        Design: Corner/state_machines/ship_closes_build_order_and_duty_application
        """
        ctx = X.setup_released_package(api)
        assert ctx["package"]["status"] == "RELEASED"
        assert ctx["package"]["guarantee_basis"] == "CERTIFIED_CURVE"
        assert X.reread_build_order(api, ctx["build_order"]["id"])["status"] == "TESTED"
        assert (
            X.reread_duty_application(api, ctx["duty"]["id"])["status"] == "CONTRACTED"
        )

        response = api.ship_pump_package(
            ctx["package"]["id"],
            F.ship_payload(K.DEFAULT_ACTUAL_SHIP_DATE),
            planner_headers,
        )
        shipped = validate_success(response, 200)

        A.assert_pump_package(shipped)
        assert shipped["status"] == "SHIPPED"
        assert shipped["actual_ship_date"].startswith("2026-09-15T00:00:00")
        assert shipped["guarantee_basis"] == "CERTIFIED_CURVE"

        assert X.reread_build_order(api, ctx["build_order"]["id"])["status"] == "CLOSED"
        assert X.reread_duty_application(api, ctx["duty"]["id"])["status"] == "CLOSED"
        assert X.reread_selection(api, ctx["selection"]["id"])["status"] == "APPROVED"
        assert X.reread_casting_lot(api, ctx["lot"]["id"])["committed_build_count"] == 0

    def test_lifting_a_hold_on_a_package_that_was_never_held_is_refused(
        self, api, planner_headers
    ):
        """Release-hold is declared only from HELD, not as a harmless no-op.

        A planner lifts a casting-short hold with a release-hold action that
        drives HELD to CONFIGURED.  A freshly engineered package is CONFIGURED
        and has never been put on hold, so the action has no declared source
        state and is rejected with ERR_PACKAGE_INVALID_STATE.  Nothing is
        written: the package stays CONFIGURED at the version 1 it was created
        with, its promised ship date intact.

        Design: Corner/state_machines/release_hold_on_configured_package_returns_package_invalid_state
        """
        ctx = X.setup_configured_package(api)
        package = ctx["package"]
        assert package["status"] == "CONFIGURED"
        assert package["version"] == 1
        assert X.reread_build_order(api, ctx["build_order"]["id"])["status"] == "TESTED"

        response = api.release_pump_package_hold(package["id"], planner_headers)
        validate_error(response, ApiErrorId.PACKAGE_INVALID_STATE)

        unchanged = X.reread_pump_package(api, package["id"])
        assert unchanged["status"] == "CONFIGURED"
        assert unchanged["version"] == 1
        assert unchanged["promised_ship_date"] == package["promised_ship_date"]
        assert unchanged["actual_ship_date"] is None


# ─────────────────────────────────────────────────────────────────────────────
# Kit allocation
# ─────────────────────────────────────────────────────────────────────────────
class TestKitAllocationLifecycle:
    """The allocation ladder is RESERVED, then ISSUED, then CONSUMED."""

    def test_consuming_straight_from_reserved_is_refused_and_drains_no_stock(
        self, api, planner_headers
    ):
        """Consumption is declared from ISSUED, so the issue step is mandatory.

        Reserved units are issued to the shop floor RESERVED to ISSUED and only
        issued units are booked as consumed ISSUED to CONSUMED, so booking a
        consumption directly against a reservation is rejected with
        ERR_ALLOCATION_INVALID_STATE.  Every unit stays exactly where the
        reservation left it: of the ten received, two remain in qty_reserved and
        eight on hand, with qty_issued and qty_consumed_total both 0, so the kit
        unit conservation identity still holds against qty_received_total.

        Design: Corner/state_machines/consume_on_reserved_allocation_returns_allocation_invalid_state
        """
        ctx = X.setup_planned_build_order(api)
        kit = X.setup_kit_with_stock(api, ctx["model"]["id"], qty=10)
        allocation = X.setup_reserved_allocation(
            api, kit, ctx["build_order"]["id"], requested_qty=2
        )
        assert allocation["status"] == "RESERVED"

        response = api.consume_kit_allocation(allocation["id"], planner_headers)
        validate_error(response, ApiErrorId.ALLOCATION_INVALID_STATE)

        unchanged = X.reread_kit_allocation(api, allocation["id"])
        assert unchanged["status"] == "RESERVED"
        assert unchanged["version"] == allocation["version"]

        stock = X.reread_repair_kit(api, kit["id"])
        A.assert_repair_kit(stock)
        assert stock["qty_received_total"] == 10
        assert stock["qty_reserved"] == 2
        assert stock["qty_on_hand"] == 8
        assert stock["qty_issued"] == 0
        assert stock["qty_consumed_total"] == 0


# ─────────────────────────────────────────────────────────────────────────────
# Warranty claim
# ─────────────────────────────────────────────────────────────────────────────
class TestWarrantyClaimLifecycle:
    """Settlement is reachable from the manufacturing branch and no other."""

    def test_settling_a_no_defect_claim_is_refused_and_computes_no_figures(
        self, api, adjudicator_headers
    ):
        """ADJUDICATED_NO_DEFECT is terminal, so no settlement is ever computed.

        The package shipped against a witnessed certified curve, so the promise
        is the measured machine: at the as-found flow of 300.0 the reported curve
        reads 70.00 m, the as-found 69.00 m is 1.43 percent short of it, and that
        shortfall is at least the negative of the 3.0 percent head tolerance the
        run's grade allows.  The first determination condition therefore wins and
        the claim closes as NO_DEFECT_FOUND, with the installation clean so
        application_error_flags stays empty.  Settlement is reachable only from
        ADJUDICATED_MANUFACTURING, so settle is rejected with
        ERR_CLAIM_INVALID_STATE and the three settlement figures remain null.
        The model's no-defect counter carries the single adjudication and neither
        of the other two counters moves.

        Design: Corner/state_machines/settle_on_no_defect_claim_returns_claim_invalid_state
        """
        ctx = X.setup_adjudicated_claim(
            api,
            claim={
                "as_found_flow_m3h": 300.0,
                "as_found_head_m": 69.0,
                "as_found_npsha_m": 5.50,
                "as_found_solids_pct": 0.0,
                "as_found_viscosity_cst": 1.2,
                "as_found_speed_rpm": 2950,
            },
            claim_lines=[F.claim_line("CL-1", "PARTS", 1205.00)],
        )
        claim = ctx["claim"]
        assert ctx["package"]["guarantee_basis"] == "CERTIFIED_CURVE"
        assert claim["status"] == "ADJUDICATED_NO_DEFECT"

        response = api.settle_claim(claim["id"], adjudicator_headers)
        validate_error(response, ApiErrorId.CLAIM_INVALID_STATE)

        unchanged = X.reread_warranty_claim(api, claim["id"])
        A.assert_warranty_claim(unchanged)
        assert unchanged["status"] == "ADJUDICATED_NO_DEFECT"
        assert unchanged["version"] == claim["version"]
        assert unchanged["determination"] == "NO_DEFECT_FOUND"
        assert unchanged["liability_basis"] == "CERTIFIED_CURVE"
        assert unchanged["expected_head_m"] == pytest.approx(70.00, abs=0.01)
        assert unchanged["head_shortfall_pct"] == pytest.approx(-1.43, abs=0.01)
        assert unchanged["application_error_flags"] == []
        assert unchanged["settlement_subtotal"] is None
        assert unchanged["admin_fee"] is None
        assert unchanged["settlement_total"] is None

        model = X.reread_pump_model(api, ctx["model"]["id"])
        assert model["no_defect_count"] == 1
        assert model["application_error_count"] == 0
        assert model["warranty_defect_count"] == 0
