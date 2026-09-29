"""Endpoint surface: the computed earned-value projection, the declared query
filters, the reopen edge on the approved-as-noted path, the three rows one hang
writes and the fan-out of one release over several zones."""
import pytest
from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import assert_envelope_meta
from test_helpers.constants import USER_IDS
from test_helpers.test_users import TEST_USERS, make_architect_of_record_headers

PM = TEST_USERS["cw_project_manager_headers"]
DETAILER = TEST_USERS["cw_detailer_headers"]
ARCHITECT = TEST_USERS["architect_of_record_headers"]
PROCUREMENT = TEST_USERS["glazing_procurement_headers"]
STRUCTURAL = TEST_USERS["structural_contractor_headers"]
SUPERINTENDENT = TEST_USERS["field_superintendent_headers"]
QC = TEST_USERS["qc_inspector_headers"]


class TestEarnedValueProjection:
    """The computed read is a projection of the stored aggregates, not a second
    algorithm."""

    def test_the_read_agrees_with_the_package_to_the_cent_and_mutates_nothing(self):
        """Two certified zones give 801.00 sqm, a 113178377 subtotal, 5658919
        retention and 107519458 earned; the same four figures read off the package
        itself; and two successive reads return identical payloads while the
        package's version stands still.

        PRD: "A dedicated computed read on the package re-derives the whole ledger from the current weather-tight zone set without mutating anything, reporting `certified_area_sqm`, the `certified_subtotal_cents` intermediate, `retention_held_cents`, `earned_value_certified_cents`, `weather_tight_zone_count` and the `contract_value_cents` ceiling side by side."

        Design: Corner/endpoints/earned_value_computed_read_agrees_with_the_stored_package_aggregates
        """
        ctx = fx.setup_two_certified_zones()
        response = api_client.get_earned_value(ctx["package_id"], PROCUREMENT)
        read = validate_success(response, expected_status=200)
        assert read["certified_area_sqm"] == pytest.approx(801.00, abs=0.01)
        assert read["certified_subtotal_cents"] == 113178377
        assert read["retention_held_cents"] == 5658919
        assert read["earned_value_certified_cents"] == 107519458
        assert read["weather_tight_zone_count"] == 2
        assert read["contract_value_cents"] == 1450000000
        assert response.json()["response_type"] == "object"
        assert_envelope_meta(response.json())

        package = validate_success(
            api_client.get_facade_package(ctx["package_id"], PM), expected_status=200
        )
        assert package["state"] == "WEATHER_TIGHT_ACHIEVED"
        assert package["certified_area_sqm"] == pytest.approx(read["certified_area_sqm"], abs=0.01)
        assert package["retention_held_cents"] == read["retention_held_cents"]
        assert package["earned_value_certified_cents"] == read["earned_value_certified_cents"]
        assert package["weather_tight_zone_count"] == read["weather_tight_zone_count"]

        again = validate_success(
            api_client.get_earned_value(ctx["package_id"], STRUCTURAL), expected_status=200
        )
        assert again == read
        assert (
            validate_success(
                api_client.get_facade_package(ctx["package_id"], PM), expected_status=200
            )["version"]
            == package["version"]
        )


class TestDeclaredListingFilters:
    """Each listing filters on its own declared fields, conjunctively."""

    @staticmethod
    def _one_certified_zone_one_planned_zone_and_one_minor_defect():
        ctx = fx.setup_certified_zone(zone_count=2)
        zone_a, zone_b = ctx["zone_ids"][0], ctx["zone_ids"][1]
        defect = fx.raise_defect(
            ctx, zone_id=zone_a, origin="PUNCH_LIST", severity="MINOR",
            description="gasket dressing at grid 3",
        )
        return ctx, zone_a, zone_b, defect

    def test_zone_defect_and_field_test_filters_narrow_the_set_and_the_window_walks_it(self):
        """The weather-tight filter returns only the certified zone, the planned
        filter only the untouched one, a severity-and-status pair returns the one
        minor item while the critical probe returns nothing, a kind-and-state pair
        returns one of the zone's two passed tests, and the unfiltered listing
        reports both zones under the default window.

        PRD: "The installation-zone list accepts `package_id`, `install_status`, `weather_status` and `floor_number`."

        Design: Corner/endpoints/listings_filter_and_paginate_over_the_declared_query_fields
        """
        ctx, zone_a, zone_b, defect = (
            self._one_certified_zone_one_planned_zone_and_one_minor_defect()
        )

        tight = get_success_data(
            api_client.list_package_zones(
                ctx["package_id"], PM, params={"weather_status": "WEATHER_TIGHT"}
            )
        )
        assert [row["id"] for row in tight] == [zone_a]

        planned, planned_meta = validate_paginated(
            api_client.list_installation_zones(
                PM,
                params={
                    "package_id": ctx["package_id"],
                    "install_status": "PLANNED",
                    "limit": 1,
                    "offset": 0,
                },
            )
        )
        assert [row["id"] for row in planned] == [zone_b]
        assert planned_meta["total_count"] == 1
        assert planned_meta["has_more"] is False

        minor, minor_meta = validate_paginated(
            api_client.list_defect_items(
                ARCHITECT,
                params={
                    "package_id": ctx["package_id"],
                    "severity": "MINOR",
                    "status": "OPEN",
                },
            )
        )
        assert [row["id"] for row in minor] == [defect["id"]]
        assert minor_meta["total_count"] == 1

        critical, critical_meta = validate_paginated(
            api_client.list_defect_items(
                ARCHITECT,
                params={
                    "package_id": ctx["package_id"],
                    "severity": "CRITICAL",
                    "status": "OPEN",
                },
            )
        )
        assert critical == []
        assert critical_meta["total_count"] == 0

        air, air_meta = validate_paginated(
            api_client.list_field_tests(
                QC,
                params={"zone_id": zone_a, "test_kind": "AIR_INFILTRATION", "state": "PASSED"},
            )
        )
        assert len(air) == 1
        assert air[0]["test_kind"] == "AIR_INFILTRATION"
        assert air[0]["state"] == "PASSED"
        assert air_meta["total_count"] == 1

        every_zone, every_meta = validate_paginated(
            api_client.list_installation_zones(PM, params={"package_id": ctx["package_id"]})
        )
        assert len(every_zone) == 2
        assert every_meta["total_count"] == 2
        assert every_meta["limit"] == 10
        assert every_meta["offset"] == 0


class TestReopenReviewEdge:
    """Reopening depends on the notes still being open and on who is asking."""

    def test_the_sealer_cannot_reopen_and_a_burned_down_set_can_no_longer_be_reopened(self):
        """The sealing engineer's reopen is refused for segregation of duties, the
        architect's reopen drags the set back under review while its decision and
        its two notes survive, and once the notes reach zero the same call has no
        transition left to take.

        PRD: "An `ArchitectOfRecord` may **reopen** a submittal, dragging it `APPROVED_AS_NOTED` → `UNDER_REVIEW` while its `open_notes_count` is at least 1 and while the acting `X-User-ID` differs from `sealed_by_user_id`."

        Design: Corner/endpoints/reopen_review_is_conditional_on_open_notes_and_a_non_sealer_reviewer
        """
        ctx = fx.setup_approved_as_noted_submittal(notes_count=2)
        submittal_id = ctx["submittal_id"]
        noted = get_success_data(api_client.get_submittal(submittal_id, DETAILER))
        assert noted["state"] == "APPROVED_AS_NOTED"
        assert noted["open_notes_count"] == 2
        assert noted["sealed_by_user_id"] == USER_IDS["ENGINEER"]

        validate_error(
            api_client.reopen_submittal_review(
                submittal_id,
                f.reopen_review_payload("sealer second thoughts"),
                make_architect_of_record_headers(USER_IDS["ENGINEER"]),
            ),
            ApiErrorId.ERR_SEALER_CANNOT_REVIEW.value,
            expected_status=422,
        )
        assert (
            get_success_data(api_client.get_submittal(submittal_id, DETAILER))["state"]
            == "APPROVED_AS_NOTED"
        )

        architect = make_architect_of_record_headers(USER_IDS["ARCHITECT"])
        reopened = validate_success(
            api_client.reopen_submittal_review(
                submittal_id,
                f.reopen_review_payload("late owner comment on the sill detail"),
                architect,
            ),
            expected_status=200,
        )
        assert reopened["state"] == "UNDER_REVIEW"
        assert reopened["review_decision"] == "APPROVED_AS_NOTED"
        assert reopened["open_notes_count"] == 2
        assert reopened["reopen_reason"] == "late owner comment on the sill detail"
        assert fx.refresh_package(ctx)["engineering_posture"] == "OPEN"

        renoted = validate_success(
            api_client.review_submittal(
                submittal_id, f.review_payload("APPROVED_AS_NOTED", notes_count=2), architect
            ),
            expected_status=200,
        )
        assert renoted["state"] == "APPROVED_AS_NOTED"
        assert renoted["open_notes_count"] == 2

        burned = validate_success(
            api_client.close_submittal_notes(
                submittal_id, f.close_notes_payload(2), architect
            ),
            expected_status=200,
        )
        assert burned["open_notes_count"] == 0

        validate_error(
            api_client.reopen_submittal_review(
                submittal_id, f.reopen_review_payload("one more comment"), architect
            ),
            ApiErrorId.ERR_INVALID_STATE.value,
            expected_status=409,
        )
        assert (
            get_success_data(api_client.get_submittal(submittal_id, DETAILER))["state"]
            == "APPROVED_AS_NOTED"
        )

    def test_a_plainly_approved_set_reports_a_terminal_state_instead(self):
        """The two approval flavours diverge on this edge: the plainly approved set
        is terminal, so its reopen is refused as terminal rather than for the
        notes.

        PRD: "`APPROVED` is terminal: the submittal accepts no further transitions."

        Design: Corner/endpoints/reopen_review_is_conditional_on_open_notes_and_a_non_sealer_reviewer
        """
        ctx = fx.setup_qualified_package()
        approved = fx.add_approved_submittal(ctx)
        assert approved["state"] == "APPROVED"
        assert approved["open_notes_count"] == 0

        validate_error(
            api_client.reopen_submittal_review(
                approved["id"],
                f.reopen_review_payload("late owner comment"),
                make_architect_of_record_headers(USER_IDS["ARCHITECT"]),
            ),
            ApiErrorId.ERR_TERMINAL_STATE.value,
            expected_status=409,
        )


class TestHangWritesThreeRows:
    """One action call touches the zone, the reservation and the package."""

    def test_the_hang_stamps_the_zone_prices_the_estimate_and_consumes_the_reservation(self):
        """The zone reaches its hung state stamped from the logical clock with a
        940800-cent estimate and no actual yet, the named reservation is consumed
        with its version bumped, the package sits in installation, and a second
        hang is refused without consuming anything twice.

        PRD: "On success the zone stamps `hang_completed_at` from the logical clock, the referenced reservation transitions `RESERVED` → `CONSUMED`, and the zone's forward-looking labor estimate is written as described in §3.7."

        Design: Corner/endpoints/hang_panels_consumes_the_reservation_and_prices_the_provisional_cost
        """
        ctx = fx.setup_zone_ready_to_hang()
        zone_id = ctx["zone_ids"][0]
        reservation = ctx["reservations"][zone_id]
        before = get_success_data(api_client.get_installation_zone(zone_id, PM))
        assert before["install_status"] == "ANCHORS_SET"
        assert before["planned_panel_count"] == 36

        hung = validate_success(
            api_client.hang_panels(
                zone_id, f.hang_panels_payload(reservation["id"]), SUPERINTENDENT
            ),
            expected_status=200,
        )
        assert hung["install_status"] == "PANELS_HUNG"
        assert hung["hang_completed_at"] == "2026-08-10T09:00:00.000Z"
        assert hung["weather_status"] == "NOT_TIGHT"
        assert hung["provisional_labor_cost_cents"] == 940800
        assert hung["final_labor_cost_cents"] is None

        consumed = get_success_data(
            api_client.get_hoist_reservation(reservation["id"], PM)
        )
        assert consumed["status"] == "CONSUMED"
        assert consumed["version"] == reservation["version"] + 1
        assert fx.refresh_package(ctx)["state"] == "IN_INSTALLATION"

        validate_error(
            api_client.hang_panels(
                zone_id, f.hang_panels_payload(reservation["id"]), SUPERINTENDENT
            ),
            ApiErrorId.ERR_ZONE_SEQUENCE_VIOLATION.value,
            expected_status=409,
        )
        still_consumed = get_success_data(
            api_client.get_hoist_reservation(reservation["id"], PM)
        )
        assert still_consumed["status"] == "CONSUMED"
        assert still_consumed["version"] == consumed["version"]


class TestReleaseFansOutOverZones:
    """One release, one lot per named zone."""

    def test_two_named_zones_yield_two_batched_lots_and_one_allocation(self):
        """The release reports two lots, each zone owns exactly one batched lot of
        36 panels and 72 lites, the order's ledger allocates 144 lites behind its
        seven-lite reserve, and the package advances into fabrication past the
        version the request carried.

        PRD: "It then creates **one panel lot per covered zone**, in the order the `zone_ids` array listed them, and sets `lot_count` to the number of lots created."

        Design: Corner/endpoints/release_creates_one_panel_lot_per_named_zone
        """
        ctx = fx.setup_ready_for_release(zone_count=2)
        zone_a, zone_b = ctx["zone_ids"][0], ctx["zone_ids"][1]
        before = fx.refresh_package(ctx)
        assert before["state"] == "MOCKUP_QUALIFIED"

        release = validate_success(
            api_client.create_fabrication_release(
                f.create_fabrication_release_payload(
                    ctx["package_id"],
                    ctx["submittal_id"],
                    ctx["glass_order_id"],
                    [zone_a, zone_b],
                    before["version"],
                    panels_per_zone=36,
                    lites_per_panel=2,
                ),
                PM,
            ),
            expected_status=201,
        )
        assert release["state"] == "RELEASED"
        assert release["lot_count"] == 2
        assert release["panels_per_zone"] == 36
        assert release["lites_per_panel"] == 2

        for zone_id in (zone_a, zone_b):
            lots = get_success_data(
                api_client.list_panel_lots(SUPERINTENDENT, params={"zone_id": zone_id})
            )
            assert len(lots) == 1
            assert lots[0]["zone_id"] == zone_id
            assert lots[0]["fabrication_status"] == "BATCHED"
            assert lots[0]["panel_count"] == 36
            assert lots[0]["lite_count"] == 72

        order = fx.refresh_glass_order(ctx)
        assert order["allocated_lites"] == 144
        assert order["breakage_stock_lites"] == 7
        assert order["unallocated_lites"] == 89

        after = fx.refresh_package(ctx)
        assert after["state"] == "IN_FABRICATION"
        assert after["version"] > before["version"]

        child_lots, child_meta = validate_paginated(
            api_client.list_panel_lots(PM, params={"release_id": release["id"]})
        )
        assert len(child_lots) == 2
        assert child_meta["total_count"] == 2
        assert len(get_success_data(api_client.list_release_panel_lots(release["id"], PM))) == 2
