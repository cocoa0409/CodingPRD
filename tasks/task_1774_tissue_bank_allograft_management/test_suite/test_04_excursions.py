"""Temperature excursions: severity model, resolution dispositions, quarantine
cascade depth, unit quarantine cycles, and conserved invariants."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    advance_clock,
    build_user_headers,
    create_par_policy,
    create_shipment,
    get_success_data,
    investigate_excursion,
    make_manifest_item,
    open_excursion_via_reading,
    release_units,
    report_manual_excursion,
    resolve_excursion_ok,
    units_of_shipment,
    setup_available_units,
    setup_case,
    setup_excursion_over_units,
    setup_freezer,
    setup_reservation,
    setup_supplier_and_freezer,
    validate_error,
    validate_success,
)

COORD = TEST_USERS["coordinator_headers"]
COORD2 = TEST_USERS["coordinator2_headers"]
QM = TEST_USERS["quality_headers"]
QM2 = TEST_USERS["quality2_headers"]
ADMIN = TEST_USERS["admin_headers"]

class TestManualExcursionReport:
    def test_manual_report_while_excursion_active_rejected(self, api):
        """PRD §3.3: "manual reports carry `origin` `MANUAL_REPORT` and stamp
        `reported_by_user_id`, start with `max_deviation_celsius` at 0, and are
        refused with `ERR_EXCURSION_INVALID_STATE` while the freezer is already
        `EXCURSION_ACTIVE`."

        Design: Corner/state_machines/excursion_manual_report_while_active_rejected
        """
        freezer = setup_freezer()
        excursion = report_manual_excursion(freezer["id"], "Door ajar observed")
        assert excursion["origin"] == "MANUAL_REPORT"
        assert excursion["reported_by_user_id"] == "tbc-1"
        resp = api.report_excursion(
            freezer["id"], {"reason": "Second report while active"}, COORD2
        )
        validate_error(resp, ApiErrorId.ERR_EXCURSION_INVALID_STATE)
        freezer_after = validate_success(api.get_freezer(freezer["id"], ADMIN))
        assert freezer_after["current_excursion_id"] == excursion["id"]

    def test_resolve_from_open_rejected(self, api):
        """PRD §3.3: "Opening an investigation moves the excursion from `OPEN`
        to `UNDER_INVESTIGATION`; both investigation and resolution are
        rejected with `ERR_EXCURSION_INVALID_STATE` from any other state."

        Design: Corner/errors/error_excursion_resolve_from_open_blocked
        """
        freezer = setup_freezer()
        excursion_id = open_excursion_via_reading(freezer["id"], -50.0)
        resp = api.resolve_excursion(
            excursion_id,
            {"disposition": "RELEASE", "resolution_notes": "Skipping investigation step"},
            QM,
        )
        validate_error(resp, ApiErrorId.ERR_EXCURSION_INVALID_STATE)
        excursion = validate_success(api.get_excursion(excursion_id, QM))
        assert excursion["status"] == "OPEN"

    def test_resolve_by_manual_reporter_blocked_sod(self, api):
        """PRD §2.10: "Second, the `QualityManager` who resolves a manually
        reported excursion must not be the operator recorded as
        `reported_by_user_id` on it (excursions opened automatically by an
        out-of-range reading carry no reporter, so this restriction does not
        apply to them)."
        PRD §2.10: "Any violation of these three pairings is rejected with
        `ERR_SEGREGATION_OF_DUTIES` (HTTP 409)."

        Design: Corner/state_machines/excursion_resolve_by_manual_reporter_blocked_sod
        """
        freezer = setup_freezer()
        excursion = report_manual_excursion(
            freezer["id"], "Door ajar on morning rounds"
        )
        investigate_excursion(excursion["id"])
        reporter_as_qm = build_user_headers("tbc-1", "QualityManager")
        resp = api.resolve_excursion(
            excursion["id"],
            {"disposition": "RELEASE",
             "resolution_notes": "Reporter attempting self-resolution"},
            reporter_as_qm,
        )
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        resolved = validate_success(
            api.resolve_excursion(
                excursion["id"],
                {"disposition": "RELEASE",
                 "resolution_notes": "Independent reviewer release"},
                QM,
            )
        )
        assert resolved["status"] == "RESOLVED_RELEASE"


class TestSeverityModel:
    def test_severity_high_forbids_release_and_requires_destroy(self, api):
        """PRD §3.3: "Resolution requires a `disposition` of `RELEASE` or
        `DESTROY` and `resolution_notes` of at least ten characters (shorter
        notes fail with `ERR_INVALID_REQUEST`), honors the segregation rule of
        §2.10 against `reported_by_user_id` for manually reported excursions,
        and is gated by severity: an excursion whose `severity_class` is `HIGH`
        may not be released — such a resolution is rejected with
        `ERR_SEVERITY_REQUIRES_DESTROY`, leaving destruction as the only lawful
        outcome."
        PRD §3.3: "Deviation contributes the smaller of 40 points and the `max_deviation_celsius` rounded up to the next whole degree, multiplied by 8 points per degree. Duration contributes 6 points per full hour between `opened_at` and the resolution time — or the current clock while unresolved — with partial hours discarded, capped at 30 points. Affected stock contributes 2 points per unit held for this excursion, capped at 20 points. Criticality contributes 10 points when the highest `criticality_tier` among affected units is `CRITICAL`, 5 when it is `SENSITIVE`, and 0 when it is `STANDARD` — and an excursion holding no units is scored as `STANDARD`. The four components sum to `severity_score`; `severity_class` is `LOW` below 25 points, `MEDIUM` from 25 up to and including 59, and `HIGH` at 60 or above."

        Design: Difficulty/combinatorial_formula/excursion_severity_nested_caps_and_tier_branch
        """
        bundle = setup_excursion_over_units(
            items=[
                make_manifest_item(tissue_type="CARDIOVASCULAR", serial_number="U-001",
                                   criticality_tier="CRITICAL"),
                make_manifest_item(tissue_type="CARDIOVASCULAR", serial_number="U-002",
                                   criticality_tier="CRITICAL"),
                make_manifest_item(tissue_type="CARDIOVASCULAR", serial_number="U-003",
                                   criticality_tier="CRITICAL"),
            ],
            reading_temp=-50.0,
        )
        excursion_id = bundle["excursion_id"]
        investigate_excursion(excursion_id)
        advance_clock("2026-08-05T11:30:00Z")  # 150 minutes open

        excursion = validate_success(api.get_excursion(excursion_id, QM))
        # min(40, ceil(10.0)*8)=40 + min(30, (150//60)*6)=12 + min(20, 3*2)=6
        # + CRITICAL=10 -> 68, HIGH.
        assert excursion["affected_unit_count"] == 3
        assert excursion["severity_score"] == 68
        assert excursion["severity_class"] == "HIGH"

        resp = api.resolve_excursion(
            excursion_id,
            {"disposition": "RELEASE",
             "resolution_notes": "Attempted release of HIGH severity excursion"},
            QM,
        )
        validate_error(resp, ApiErrorId.ERR_SEVERITY_REQUIRES_DESTROY)

    def test_severity_high_destroy_resolution_cascades(self, api):
        """PRD §3.3: "A `DESTROY` resolution moves those same units to
        `DISCARDED`, clears their `hold_reason`, and creates one `DRAFT`
        disposition record of type `DESTROYED` per unit. Either resolution
        stamps `resolved_by_user_id` and `resolved_at`, returns the freezer to
        `OPERATIONAL` with `current_excursion_id` cleared to null"

        Design: Difficulty/combinatorial_formula/excursion_severity_nested_caps_and_tier_branch
        """
        bundle = setup_excursion_over_units(
            items=[
                make_manifest_item(tissue_type="CARDIOVASCULAR", serial_number="U-001",
                                   criticality_tier="CRITICAL"),
                make_manifest_item(tissue_type="CARDIOVASCULAR", serial_number="U-002",
                                   criticality_tier="CRITICAL"),
                make_manifest_item(tissue_type="CARDIOVASCULAR", serial_number="U-003",
                                   criticality_tier="CRITICAL"),
            ],
            reading_temp=-50.0,
        )
        excursion_id = bundle["excursion_id"]
        investigate_excursion(excursion_id)
        advance_clock("2026-08-05T11:30:00Z")
        resolved = resolve_excursion_ok(
            excursion_id, "DESTROY", "Destroyed after HIGH severity review"
        )
        assert resolved["status"] == "RESOLVED_DESTROY"
        assert resolved["resolved_by_user_id"] == "qm-1"
        for unit in bundle["units"]:
            after = validate_success(api.get_tissue_unit(unit["id"], QM))
            assert after["status"] == "DISCARDED"
            records = get_success_data(api.list_unit_disposition_records(unit["id"], QM))
            assert len(records) == 1
            assert records[0]["disposition_type"] == "DESTROYED"
            assert records[0]["status"] == "DRAFT"
        freezer_after = validate_success(api.get_freezer(bundle["freezer"]["id"], ADMIN))
        assert freezer_after["status"] == "OPERATIONAL"
        assert freezer_after["current_excursion_id"] is None

    def test_severity_medium_class_permits_release(self, api):
        """PRD §3.3: "Deviation contributes the smaller of 40 points and the `max_deviation_celsius` rounded up to the next whole degree, multiplied by 8 points per degree. Duration contributes 6 points per full hour between `opened_at` and the resolution time — or the current clock while unresolved — with partial hours discarded, capped at 30 points. Affected stock contributes 2 points per unit held for this excursion, capped at 20 points. Criticality contributes 10 points when the highest `criticality_tier` among affected units is `CRITICAL`, 5 when it is `SENSITIVE`, and 0 when it is `STANDARD` — and an excursion holding no units is scored as `STANDARD`. The four components sum to `severity_score`; `severity_class` is `LOW` below 25 points, `MEDIUM` from 25 up to and including 59, and `HIGH` at 60 or above."
        PRD §3.3: "A `RELEASE` resolution moves every unit held with
        `hold_reason` `EXCURSION` in that freezer back to `AVAILABLE` with
        `hold_reason` cleared to `NONE`."

        Design: Corner/calculations/severity_medium_class_permits_release_disposition
        """
        bundle = setup_excursion_over_units(
            items=[
                make_manifest_item(tissue_type="SKIN", serial_number="U-001",
                                   criticality_tier="SENSITIVE"),
                make_manifest_item(tissue_type="SKIN", serial_number="U-002",
                                   criticality_tier="SENSITIVE"),
            ],
            reading_temp=-58.0,
        )
        excursion_id = bundle["excursion_id"]
        investigate_excursion(excursion_id)
        advance_clock("2026-08-05T10:30:00Z")  # 90 minutes open
        excursion = validate_success(api.get_excursion(excursion_id, QM))
        # min(40, ceil(2.0)*8)=16 + min(30, (90//60)*6)=6 + min(20, 2*2)=4
        # + SENSITIVE=5 -> 31, MEDIUM.
        assert excursion["severity_score"] == 31
        assert excursion["severity_class"] == "MEDIUM"
        resolved = resolve_excursion_ok(
            excursion_id, "RELEASE", "MEDIUM severity, units verified intact"
        )
        assert resolved["status"] == "RESOLVED_RELEASE"
        for unit in bundle["units"]:
            after = validate_success(api.get_tissue_unit(unit["id"], QM))
            assert after["status"] == "AVAILABLE"
            assert after["hold_reason"] == "NONE"

    def test_severity_duration_truncates_to_whole_hours(self, api):
        """PRD §3.3: "Duration contributes 6 points per full hour between
        `opened_at` and the resolution time — or the current clock while
        unresolved — with partial hours discarded, capped at 30 points."

        Design: Corner/calculations/severity_duration_truncates_to_whole_hours
        """
        bundle = setup_excursion_over_units(
            items=[make_manifest_item(serial_number="U-001")],
            reading_temp=-59.0,
        )
        excursion_id = bundle["excursion_id"]
        investigate_excursion(excursion_id)
        advance_clock("2026-08-05T10:59:00Z")  # 119 minutes open -> 1 full hour
        excursion = validate_success(api.get_excursion(excursion_id, QM))
        # min(40, ceil(1.0)*8)=8 + (119//60)*6=6 + min(20, 1*2)=2 + 0 -> 16, LOW.
        assert excursion["severity_score"] == 16
        assert excursion["severity_class"] == "LOW"


class TestExcursionCascadeDepth:
    def test_reading_cascade_quarantines_units_and_releases_reservation(self, api):
        """PRD §3.3: "Opening an excursion flips the freezer from `OPERATIONAL`
        to `EXCURSION_ACTIVE`, records the new excursion as the freezer's
        `current_excursion_id`, increments the freezer's `version` by one, and
        fires the quarantine cascade: every unit stored there in `AVAILABLE`
        moves to `QUARANTINED` with `hold_reason` `EXCURSION`, every `RESERVED`
        unit moves to `QUARANTINED` with `hold_reason` `EXCURSION` while its
        `ACTIVE` reservation is released with `release_reason` `EXCURSION`, and
        par-level availability is recomputed for each affected tissue type."

        Design: Difficulty/transitive_cascade/excursion_reading_cascade_releases_reservation_and_recomputes_par
        """
        supplier, freezer = setup_supplier_and_freezer()
        create_par_policy(tissue_type="BONE", par_quantity=2)
        shipment = create_shipment(
            supplier["id"],
            freezer["id"],
            [make_manifest_item(serial_number="U-001"),
             make_manifest_item(serial_number="U-002")],
        )
        get_success_data(api.accept_shipment(shipment["id"], COORD))
        units = release_units(units_of_shipment(shipment["id"]))
        case = setup_case()
        reservation = setup_reservation(case["id"], units[0]["id"])

        reading = validate_success(
            api.create_reading(freezer["id"], {"temp_celsius": -50.0}, COORD), 201
        )
        assert reading["in_range"] is False
        excursion_id = reading["excursion_id"]
        assert excursion_id is not None

        freezer_after = validate_success(api.get_freezer(freezer["id"], ADMIN))
        assert freezer_after["status"] == "EXCURSION_ACTIVE"
        assert freezer_after["current_excursion_id"] == excursion_id

        unit1 = validate_success(api.get_tissue_unit(units[0]["id"], QM))
        assert unit1["status"] == "QUARANTINED"
        assert unit1["hold_reason"] == "EXCURSION"
        unit2 = validate_success(api.get_tissue_unit(units[1]["id"], QM))
        assert unit2["status"] == "QUARANTINED"
        assert unit2["hold_reason"] == "EXCURSION"

        reservation_after = validate_success(api.get_reservation(reservation["id"], COORD))
        assert reservation_after["status"] == "RELEASED"
        assert reservation_after["release_reason"] == "EXCURSION"

    def test_reading_cascade_recomputes_par_policy(self, api):
        """PRD §3.9: "`on_hand_available` counts only units of the policy's
        tissue type currently `AVAILABLE` — quarantined, reserved, issued, and
        terminal units are all excluded. `deficit` is the larger of zero and
        `par_quantity` minus `on_hand_available`. `needs_reorder` is true only
        when `on_hand_available` is strictly below `par_quantity`; sitting
        exactly at par means no reorder."
        PRD §3.3: "par-level availability is recomputed for each affected
        tissue type."

        Design: Difficulty/transitive_cascade/excursion_reading_cascade_releases_reservation_and_recomputes_par
        """
        supplier, freezer = setup_supplier_and_freezer()
        policy = create_par_policy(tissue_type="BONE", par_quantity=2)
        shipment = create_shipment(
            supplier["id"],
            freezer["id"],
            [make_manifest_item(serial_number="U-001"),
             make_manifest_item(serial_number="U-002")],
        )
        get_success_data(api.accept_shipment(shipment["id"], COORD))
        units = release_units(units_of_shipment(shipment["id"]))
        case = setup_case()
        setup_reservation(case["id"], units[0]["id"])

        open_excursion_via_reading(freezer["id"], -50.0)

        policy_after = validate_success(api.get_par_policy(policy["id"], ADMIN))
        assert policy_after["on_hand_available"] == 0
        assert policy_after["deficit"] == 2
        assert policy_after["needs_reorder"] is True


class TestUnitQuarantineCycle:
    def test_unit_cycle_returns_to_available(self, api):
        """PRD §3.3: "A `RELEASE` resolution moves every unit held with
        `hold_reason` `EXCURSION` in that freezer back to `AVAILABLE` with
        `hold_reason` cleared to `NONE`."
        PRD §2.5: "Cascaded recomputations count as mutations: when an
        automatic sweep, a quarantine cascade, or a derived-field
        reconciliation changes a resource, that resource's `updated_at` is
        refreshed and its `version` is incremented."

        Design: Difficulty/non_linear_state_machine/tissue_unit_quarantine_release_cycle
        """
        bundle = setup_excursion_over_units(
            items=[make_manifest_item(serial_number="U-001")],
            reading_temp=-55.0,
            opened_at="2026-08-03T09:00:00Z",
        )
        unit = bundle["units"][0]
        mid = validate_success(api.get_tissue_unit(unit["id"], QM))
        assert mid["status"] == "QUARANTINED"
        assert mid["hold_reason"] == "EXCURSION"
        investigate_excursion(bundle["excursion_id"])
        advance_clock("2026-08-03T09:30:00Z")
        resolve_excursion_ok(
            bundle["excursion_id"], "RELEASE", "Deviation brief, units unaffected"
        )
        after = validate_success(api.get_tissue_unit(unit["id"], QM))
        assert after["status"] == "AVAILABLE"
        assert after["hold_reason"] == "NONE"
        # create v1 -> release v2 -> excursion cascade v3 -> resolve-release v4
        assert after["version"] == 4

    def test_unit_usable_for_reservation_after_cycle(self, api):
        """PRD §3.5: "The unit must be `AVAILABLE` (`ERR_UNIT_NOT_RESERVABLE`)"
        PRD §3.3: "The four components sum to `severity_score`;
        `severity_class` is `LOW` below 25 points, `MEDIUM` from 25 up to and
        including 59, and `HIGH` at 60 or above."

        Design: Difficulty/non_linear_state_machine/tissue_unit_quarantine_release_cycle
        """
        bundle = setup_excursion_over_units(
            items=[make_manifest_item(serial_number="U-001")],
            reading_temp=-55.0,
            opened_at="2026-08-03T09:00:00Z",
        )
        case = setup_case()
        investigate_excursion(bundle["excursion_id"])
        advance_clock("2026-08-03T09:30:00Z")
        # deviation min(40, ceil(5.0)*8)=40 + duration 0 + 1 unit*2=2 + 0 -> 42
        excursion = validate_success(api.get_excursion(bundle["excursion_id"], QM))
        assert excursion["severity_score"] == 42
        assert excursion["severity_class"] == "MEDIUM"
        resolve_excursion_ok(
            bundle["excursion_id"], "RELEASE", "Deviation brief, units unaffected"
        )
        reservation = validate_success(
            api.create_reservation(
                case["id"], {"tissue_unit_id": bundle["units"][0]["id"]}, COORD
            ),
            201,
        )
        assert reservation["status"] == "ACTIVE"
        unit_after = validate_success(api.get_tissue_unit(bundle["units"][0]["id"], QM))
        assert unit_after["status"] == "RESERVED"


class TestReleaseBlockedByExcursion:
    def test_unit_release_blocked_by_freezer_excursion(self, api):
        """PRD §3.4: "its freezer must be `OPERATIONAL` rather than
        `EXCURSION_ACTIVE` (`ERR_FREEZER_IN_EXCURSION`)"

        Design: Difficulty/cross_entity_state_dependency/unit_release_blocked_by_freezer_excursion
        """
        supplier, freezer = setup_supplier_and_freezer()
        shipment = create_shipment(
            supplier["id"], freezer["id"], [make_manifest_item(serial_number="U-001")]
        )
        get_success_data(api.accept_shipment(shipment["id"], COORD))
        unit = units_of_shipment(shipment["id"])[0]
        report_manual_excursion(freezer["id"], "Door left ajar observed on rounds")
        resp = api.release_unit(unit["id"], QM)
        validate_error(resp, ApiErrorId.ERR_FREEZER_IN_EXCURSION)

    def test_unit_release_succeeds_after_excursion_resolved_release(self, api):
        """PRD §3.3: "A `RELEASE` resolution moves every unit held with
        `hold_reason` `EXCURSION` in that freezer back to `AVAILABLE` with
        `hold_reason` cleared to `NONE`."
        PRD §3.3: "Either resolution stamps `resolved_by_user_id` and
        `resolved_at`, returns the freezer to `OPERATIONAL` with
        `current_excursion_id` cleared to null"

        Design: Difficulty/cross_entity_state_dependency/unit_release_blocked_by_freezer_excursion
        """
        supplier, freezer = setup_supplier_and_freezer()
        shipment = create_shipment(
            supplier["id"], freezer["id"], [make_manifest_item(serial_number="U-001")]
        )
        get_success_data(api.accept_shipment(shipment["id"], COORD))
        unit = units_of_shipment(shipment["id"])[0]
        excursion = report_manual_excursion(
            freezer["id"], "Door left ajar observed on rounds"
        )
        investigate_excursion(excursion["id"])
        excursion_read = validate_success(api.get_excursion(excursion["id"], QM))
        # manual report: deviation 0, duration < 1h, 1 STANDARD unit -> 2 pts.
        assert excursion_read["severity_class"] == "LOW"
        resolve_excursion_ok(
            excursion["id"], "RELEASE", "Brief door-ajar, temps verified stable"
        )
        unit_after = validate_success(api.get_tissue_unit(unit["id"], QM))
        assert unit_after["status"] == "AVAILABLE"
        freezer_after = validate_success(api.get_freezer(freezer["id"], ADMIN))
        assert freezer_after["status"] == "OPERATIONAL"
        assert freezer_after["current_excursion_id"] is None


class TestCompensatingInvariants:
    def test_excursion_release_cycle_conserves_physical_unit_count(self, api):
        """PRD §3.3: "First, `occupied_count` counts the units stored in the
        freezer — those in `QUARANTINED`, `AVAILABLE`, or `RESERVED`."
        PRD §3.3: "A `RELEASE` resolution moves every unit held with
        `hold_reason` `EXCURSION` in that freezer back to `AVAILABLE` with
        `hold_reason` cleared to `NONE`."

        Design: Difficulty/compensating_invariant/excursion_release_cycle_conserves_physical_unit_count
        """
        supplier, freezer = setup_supplier_and_freezer()
        shipment = create_shipment(
            supplier["id"],
            freezer["id"],
            [
                make_manifest_item(serial_number="U-001", unit_cost_cents=10001),
                make_manifest_item(serial_number="U-002", unit_cost_cents=10001),
                make_manifest_item(serial_number="U-003", unit_cost_cents=10002),
            ],
        )
        get_success_data(api.accept_shipment(shipment["id"], COORD))
        units = release_units(units_of_shipment(shipment["id"]))
        case = setup_case()
        reservation = setup_reservation(case["id"], units[0]["id"])

        excursion_id = open_excursion_via_reading(freezer["id"], -55.0)
        mid = validate_success(api.get_freezer(freezer["id"], ADMIN))
        assert mid["occupied_count"] == 3

        investigate_excursion(excursion_id)
        resolve_excursion_ok(
            excursion_id, "RELEASE", "Brief 5-degree spike, media verified"
        )
        post = validate_success(api.get_freezer(freezer["id"], ADMIN))
        assert post["occupied_count"] == 3

        reservation_after = validate_success(
            api.get_reservation(reservation["id"], COORD)
        )
        assert reservation_after["status"] == "RELEASED"
        assert reservation_after["release_reason"] == "EXCURSION"
        for unit in units:
            after = validate_success(api.get_tissue_unit(unit["id"], QM))
            assert after["status"] == "AVAILABLE"
            assert after["hold_reason"] == "NONE"

    def test_excursion_release_cycle_severity_and_reservation_consumed(self, api):
        """PRD §3.3: "Deviation contributes the smaller of 40 points and the `max_deviation_celsius` rounded up to the next whole degree, multiplied by 8 points per degree. Duration contributes 6 points per full hour between `opened_at` and the resolution time — or the current clock while unresolved — with partial hours discarded, capped at 30 points. Affected stock contributes 2 points per unit held for this excursion, capped at 20 points. Criticality contributes 10 points when the highest `criticality_tier` among affected units is `CRITICAL`, 5 when it is `SENSITIVE`, and 0 when it is `STANDARD` — and an excursion holding no units is scored as `STANDARD`. The four components sum to `severity_score`; `severity_class` is `LOW` below 25 points, `MEDIUM` from 25 up to and including 59, and `HIGH` at 60 or above."
        PRD §3.3: "every `RESERVED` unit moves to `QUARANTINED` with
        `hold_reason` `EXCURSION` while its `ACTIVE` reservation is released
        with `release_reason` `EXCURSION`"

        Design: Difficulty/compensating_invariant/excursion_release_cycle_conserves_physical_unit_count
        """
        supplier, freezer = setup_supplier_and_freezer()
        shipment = create_shipment(
            supplier["id"],
            freezer["id"],
            [
                make_manifest_item(serial_number="U-001", unit_cost_cents=10001),
                make_manifest_item(serial_number="U-002", unit_cost_cents=10001),
                make_manifest_item(serial_number="U-003", unit_cost_cents=10002),
            ],
        )
        get_success_data(api.accept_shipment(shipment["id"], COORD))
        units = release_units(units_of_shipment(shipment["id"]))
        case = setup_case()
        reservation = setup_reservation(case["id"], units[0]["id"])

        excursion_id = open_excursion_via_reading(freezer["id"], -55.0)
        investigate_excursion(excursion_id)
        excursion = validate_success(api.get_excursion(excursion_id, QM))
        # deviation min(40, ceil(5.0)*8)=40 + duration 0 + 3 units*2=6 + 0 -> 46.
        assert excursion["severity_score"] == 46
        assert excursion["severity_class"] == "MEDIUM"
        resolve_excursion_ok(
            excursion_id, "RELEASE", "Brief 5-degree spike, media verified"
        )
        reservation_after = validate_success(
            api.get_reservation(reservation["id"], COORD)
        )
        assert reservation_after["status"] == "RELEASED"
        assert reservation_after["release_reason"] == "EXCURSION"

    def test_excursion_release_cycle_conserves_inventory_valuation(self, api):
        """PRD §3.9: "the on-hand subset being those population units in
        `QUARANTINED`, `AVAILABLE`, `RESERVED`, or `ISSUED`; `on_hand_count` is
        the size of that subset."
        PRD §3.9: "For each distinct `lot_number` present among the on-hand
        units, taken in ascending lot order, a lot line value is formed by
        multiplying that unrounded mean by the number of on-hand units in the
        lot and rounding the product half-up to two decimal places;
        `total_value` is the sum of those per-lot line values."

        Design: Difficulty/compensating_invariant/excursion_release_cycle_conserves_inventory_valuation
        """
        _, freezer, _, _ = setup_available_units(
            items=[
                make_manifest_item(serial_number="U-001", unit_cost_cents=10001),
                make_manifest_item(serial_number="U-002", unit_cost_cents=10001),
                make_manifest_item(serial_number="U-003", unit_cost_cents=10002),
            ]
        )
        # single lot L1: round_half_up(10001.333... x 3, 2dp) = 30004.00
        val_pre = validate_success(
            api.get_inventory_valuation("BONE", "WEIGHTED_AVERAGE", ADMIN)
        )
        assert val_pre["total_value"] == pytest.approx(30004.00, abs=0.005)

        excursion_id = open_excursion_via_reading(freezer["id"], -55.0)
        val_mid = validate_success(
            api.get_inventory_valuation("BONE", "WEIGHTED_AVERAGE", ADMIN)
        )
        assert val_mid["on_hand_count"] == 3
        assert val_mid["total_value"] == pytest.approx(30004.00, abs=0.005)

        investigate_excursion(excursion_id)
        resolve_excursion_ok(
            excursion_id, "RELEASE", "Brief 5-degree spike, media verified"
        )
        val_post = validate_success(
            api.get_inventory_valuation("BONE", "WEIGHTED_AVERAGE", ADMIN)
        )
        assert val_post["total_value"] == pytest.approx(30004.00, abs=0.005)

    def test_excursion_release_cycle_keeps_quarantined_units_in_population(self, api):
        """PRD §3.9: "Both methods share a population definition: every unit of
        the named tissue type whose shipment reached `ACCEPTED`, in any unit
        status including terminal ones, with the on-hand subset being those
        population units in `QUARANTINED`, `AVAILABLE`, `RESERVED`, or
        `ISSUED`; `on_hand_count` is the size of that subset."

        Design: Difficulty/compensating_invariant/excursion_release_cycle_conserves_inventory_valuation
        """
        _, freezer, _, _ = setup_available_units(
            items=[
                make_manifest_item(serial_number="U-001", unit_cost_cents=10001),
                make_manifest_item(serial_number="U-002", unit_cost_cents=10001),
                make_manifest_item(serial_number="U-003", unit_cost_cents=10002),
            ]
        )
        excursion_id = open_excursion_via_reading(freezer["id"], -55.0)
        val_mid = validate_success(
            api.get_inventory_valuation("BONE", "WEIGHTED_AVERAGE", ADMIN)
        )
        assert val_mid["on_hand_count"] == 3
        assert val_mid["total_value"] == pytest.approx(30004.00, abs=0.005)
        investigate_excursion(excursion_id)
        resolve_excursion_ok(
            excursion_id, "RELEASE", "Brief 5-degree spike, media verified"
        )
        val_post = validate_success(
            api.get_inventory_valuation("BONE", "WEIGHTED_AVERAGE", ADMIN)
        )
        assert val_post["on_hand_count"] == 3
        assert val_post["total_value"] == pytest.approx(30004.00, abs=0.005)
