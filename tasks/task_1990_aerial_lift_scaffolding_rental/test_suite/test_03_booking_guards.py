"""Booking guards: familiarization, engineering, reach, windows, OCC."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, create_rental_line_payload,
    create_customer, create_equipment_class, create_equipment_unit,
    create_contract, get_contract, add_line, set_clock,
    create_training_record, setup_draft_contract_with_line,
    assert_rental_line,
)


class TestFamiliarizationGate:
    def test_line_creation_blocked_without_training_then_succeeds(
            self, api, rental_coordinator_headers):
        """PRD §3.3: "when the class's `requires_familiarization` is true, a
        valid training record must exist for the contract's customer on the
        line's class, otherwise `ERR_FAMILIARIZATION_REQUIRED`". PRD §3.7: "A
        qualifying record for the line-creation gate is one whose
        `customer_id` matches the contract's customer, whose `class_id`
        matches the line's class, and whose `is_valid` is true at that
        moment."

        Design: Difficulty/cross_entity_state_dependency/line_creation_requires_valid_training
        """
        set_clock("2026-08-01T09:00:00Z")
        customer = create_customer("Training Gate Co", "ops@tg.example")
        cls = create_equipment_class(class_code="BOOMT",
                                     max_working_height_ft=51,
                                     min_rental_days=4,
                                     daily_rate_cents=20000,
                                     weekly_rate_cents=80000,
                                     monthly_rate_cents=240000,
                                     replacement_value_cents=4_000_000,
                                     requires_familiarization=True)
        unit = create_equipment_unit(cls["id"], "BOOMT-001", "ANSI A92.20")
        contract = create_contract(customer["id"], "6 Gate Ln")
        version = contract["version"]

        blocked = api.create_rental_line(
            create_rental_line_payload(contract["id"], unit["id"],
                                       "2026-08-05", "2026-08-15", 40,
                                       version), rental_coordinator_headers)
        validate_error(blocked, ApiErrorId.ERR_FAMILIARIZATION_REQUIRED)

        create_training_record(customer["id"], cls["id"], "Op T",
                               "2026-08-01T10:00:00Z")
        line = add_line(contract["id"], unit["id"], "2026-08-05",
                        "2026-08-15", 40, expected_contract_version=version)
        assert_rental_line(line)
        assert line["status"] == "RESERVED"
        assert line["class_id"] == cls["id"], "class_id is copied from the unit"

    def test_familiarization_rejection_preserves_contract_version(self, api,
            rental_coordinator_headers):
        """PRD §3.3: a failed line creation is rejected with
        `ERR_FAMILIARIZATION_REQUIRED`; because nothing is written, the same
        `expected_contract_version` described in PRD §2.7 — "a non-optional
        `expected_contract_version` field carrying the client's last observed
        `version` of the parent rental contract" — still matches on retry.

        Design: Difficulty/cross_entity_state_dependency/line_creation_requires_valid_training
        """
        set_clock("2026-08-01T09:00:00Z")
        customer = create_customer("Version Safe Co", "ops@vs.example")
        cls = create_equipment_class(class_code="BOOMTV",
                                     requires_familiarization=True)
        unit = create_equipment_unit(cls["id"], "BOOMTV-001", "ANSI A92.20")
        contract = create_contract(customer["id"], "7 Gate Ln")
        version = contract["version"]

        blocked = api.create_rental_line(
            create_rental_line_payload(contract["id"], unit["id"],
                                       "2026-08-05", "2026-08-15", 20,
                                       version), rental_coordinator_headers)
        validate_error(blocked, ApiErrorId.ERR_FAMILIARIZATION_REQUIRED)

        after = get_contract(contract["id"])
        assert after["version"] == version, "rejection does not mutate the contract"

        create_training_record(customer["id"], cls["id"], "Op V",
                               "2026-08-01T10:00:00Z")
        line = validate_success(api.create_rental_line(
            create_rental_line_payload(contract["id"], unit["id"],
                                       "2026-08-05", "2026-08-15", 20,
                                       version), rental_coordinator_headers), 201)
        assert line["status"] == "RESERVED", "stale-looking token still matches after a clean retry"

    def test_expired_training_record_rejected(self, api,
                                              rental_coordinator_headers):
        """PRD §3.7: "The record's `valid_until` is computed as exactly three
        hundred sixty-five days after `trained_at`, and its `is_valid` is true
        exactly while the logical clock reads earlier than `valid_until`."
        PRD §3.3: "otherwise `ERR_FAMILIARIZATION_REQUIRED`".

        Design: Corner/validations/expired_training_record_rejected
        """
        set_clock("2026-08-01T09:00:00Z")
        customer = create_customer("Expired Training Co", "ops@et.example")
        cls = create_equipment_class(class_code="BOOMT2",
                                     max_working_height_ft=51,
                                     min_rental_days=4,
                                     daily_rate_cents=20000,
                                     weekly_rate_cents=80000,
                                     monthly_rate_cents=240000,
                                     replacement_value_cents=4_000_000,
                                     requires_familiarization=True)
        unit = create_equipment_unit(cls["id"], "BOOMT2-001", "ANSI A92.20")
        record = create_training_record(customer["id"], cls["id"], "Op Old",
                                        "2025-08-01T09:00:00Z")
        assert record["valid_until"] == "2026-08-01T09:00:00Z"
        # At the creation clock 2026-08-01T09:00:00Z the clock no longer reads
        # strictly earlier than valid_until, so the record is already invalid.
        assert record["is_valid"] is False

        contract = create_contract(customer["id"], "3 Old Cert Rd")
        set_clock("2026-08-10T09:00:00Z")
        res = api.create_rental_line(
            create_rental_line_payload(contract["id"], unit["id"],
                                       "2026-08-12", "2026-08-20", 40,
                                       contract["version"]),
            rental_coordinator_headers)
        validate_error(res, ApiErrorId.ERR_FAMILIARIZATION_REQUIRED)


class TestSafetyBeforeWindowOrder:
    def test_familiarization_error_precedes_window_conflict(self, api,
            rental_coordinator_headers):
        """PRD §3.3: "Line creation is the most heavily guarded write in the
        system, and its checks evaluate in a fixed order after authentication,
        authorization, request shape, existence, and the stale-version check
        of §2.7: familiarization first — when the class's
        `requires_familiarization` is true, a valid training record must exist
        for the contract's customer on the line's class, otherwise
        `ERR_FAMILIARIZATION_REQUIRED`; then engineering — when
        `requires_engineering` is true, a missing or empty
        `engineering_plan_ref` is rejected with
        `ERR_ENGINEERING_PLAN_REQUIRED`; then reach — a
        `required_working_height_ft` that exceeds the class's
        `max_working_height_ft` is rejected with `ERR_REACH_EXCEEDED`; then
        the unit window conflict of §2.9 (`ERR_UNIT_WINDOW_CONFLICT`); and
        finally the fiscal gate — a `SUSPENDED` customer yields
        `ERR_CUSTOMER_SUSPENDED`."

        Design: Difficulty/priority_pair_validation_conflict/familiarization_safety_beats_window_constraint
        """
        set_clock("2026-08-01T09:00:00Z")
        trained = create_customer("Trained Co", "a@trained.example")
        untrained = create_customer("Untrained Co", "b@untrained.example")
        cls = create_equipment_class(class_code="BOOMF",
                                     max_working_height_ft=51,
                                     min_rental_days=4,
                                     daily_rate_cents=20000,
                                     weekly_rate_cents=80000,
                                     monthly_rate_cents=240000,
                                     replacement_value_cents=4_000_000,
                                     requires_familiarization=True)
        unit = create_equipment_unit(cls["id"], "BOOMF-001", "ANSI A92.20")
        create_training_record(trained["id"], cls["id"], "Op One",
                               "2026-08-01T10:00:00Z")
        contract_a = create_contract(trained["id"], "1 A St")
        add_line(contract_a["id"], unit["id"], "2026-08-05", "2026-08-15", 40)
        contract_b = create_contract(untrained["id"], "2 B St")

        res = api.create_rental_line(
            create_rental_line_payload(contract_b["id"], unit["id"],
                                       "2026-08-10", "2026-08-20", 40,
                                       contract_b["version"]),
            rental_coordinator_headers)
        validate_error(res, ApiErrorId.ERR_FAMILIARIZATION_REQUIRED)

    def test_window_conflict_surfaces_once_trained(self, api,
                                                   rental_coordinator_headers):
        """PRD §3.3: "then the unit window conflict of §2.9
        (`ERR_UNIT_WINDOW_CONFLICT`)" — after the familiarization gate of
        PRD §3.3 ("a valid training record must exist for the contract's
        customer on the line's class") passes, the window check is what
        rejects an overlapping booking. PRD §2.9: "creating a line is rejected
        with `ERR_UNIT_WINDOW_CONFLICT` (HTTP 409) when another line on the
        same unit in `RESERVED`, `OUT_ON_RENT`, or `OFF_RENT` status has a
        window intersecting the new one."

        Design: Difficulty/priority_pair_validation_conflict/familiarization_safety_beats_window_constraint
        """
        set_clock("2026-08-01T09:00:00Z")
        trained = create_customer("Trained Co", "a@trained.example")
        learner = create_customer("Learner Co", "b@learner.example")
        cls = create_equipment_class(class_code="BOOMF2",
                                     max_working_height_ft=51,
                                     min_rental_days=4,
                                     daily_rate_cents=20000,
                                     weekly_rate_cents=80000,
                                     monthly_rate_cents=240000,
                                     replacement_value_cents=4_000_000,
                                     requires_familiarization=True)
        unit = create_equipment_unit(cls["id"], "BOOMF2-001", "ANSI A92.20")
        create_training_record(trained["id"], cls["id"], "Op One",
                               "2026-08-01T10:00:00Z")
        contract_a = create_contract(trained["id"], "1 A St")
        add_line(contract_a["id"], unit["id"], "2026-08-05", "2026-08-15", 40)
        contract_b = create_contract(learner["id"], "2 B St")
        payload = create_rental_line_payload(contract_b["id"], unit["id"],
                                             "2026-08-10", "2026-08-20", 40,
                                             contract_b["version"])

        first = api.create_rental_line(payload, rental_coordinator_headers)
        validate_error(first, ApiErrorId.ERR_FAMILIARIZATION_REQUIRED)

        create_training_record(learner["id"], cls["id"], "Op Two",
                               "2026-08-01T11:00:00Z")
        second = api.create_rental_line(payload, rental_coordinator_headers)
        validate_error(second, ApiErrorId.ERR_UNIT_WINDOW_CONFLICT)


class TestEngineeringAndReach:
    def test_engineering_plan_required_rejected(self, api,
                                                rental_coordinator_headers):
        """PRD §3.3: "when `requires_engineering` is true, a missing or empty
        `engineering_plan_ref` is rejected with
        `ERR_ENGINEERING_PLAN_REQUIRED`".

        Design: Corner/validations/engineering_plan_required_rejected
        """
        set_clock("2026-08-01T09:00:00Z")
        customer = create_customer("Scaffold Co", "ops@scaf.example")
        cls = create_equipment_class(
            class_code="SCAF5X5", category="SCAFFOLD", max_working_height_ft=20,
            min_rental_days=2, daily_rate_cents=8000, weekly_rate_cents=30000,
            monthly_rate_cents=90000, replacement_value_cents=500000,
            requires_engineering=True)
        unit = create_equipment_unit(cls["id"], "SCAF-001", "OSHA 1926.451")
        contract = create_contract(customer["id"], "8 Frame St")

        res = api.create_rental_line(
            create_rental_line_payload(contract["id"], unit["id"],
                                       "2026-08-10", "2026-08-20", 15,
                                       contract["version"]),
            rental_coordinator_headers)
        validate_error(res, ApiErrorId.ERR_ENGINEERING_PLAN_REQUIRED)

        line = validate_success(api.create_rental_line(
            create_rental_line_payload(contract["id"], unit["id"],
                                       "2026-08-10", "2026-08-20", 15,
                                       contract["version"],
                                       engineering_plan_ref="ENG-2026-114"),
            rental_coordinator_headers), 201)
        assert line["status"] == "RESERVED"

    def test_reach_exceeded_rejected(self, api, rental_coordinator_headers):
        """PRD §3.3: "then reach — a `required_working_height_ft` that exceeds
        the class's `max_working_height_ft` is rejected with
        `ERR_REACH_EXCEEDED`"."

        Design: Corner/validations/reach_exceeded_rejected
        """
        set_clock("2026-08-01T09:00:00Z")
        customer = create_customer("Reach Co", "ops@reach.example")
        cls = create_equipment_class(class_code="S19H", max_working_height_ft=25)
        unit = create_equipment_unit(cls["id"], "S19H-001")
        contract = create_contract(customer["id"], "3 Height Rd")

        res = api.create_rental_line(
            create_rental_line_payload(contract["id"], unit["id"],
                                       "2026-08-10", "2026-08-15", 26,
                                       contract["version"]),
            rental_coordinator_headers)
        validate_error(res, ApiErrorId.ERR_REACH_EXCEEDED)

        line = validate_success(api.create_rental_line(
            create_rental_line_payload(contract["id"], unit["id"],
                                       "2026-08-10", "2026-08-15", 25,
                                       contract["version"]),
            rental_coordinator_headers), 201)
        assert line["status"] == "RESERVED", "height equal to the class maximum passes"


class TestUnitWindowHalfOpen:
    def test_overlap_rejected_and_adjacency_allowed(self, api,
                                                    rental_coordinator_headers):
        """PRD §2.9: "creating a line is rejected with
        `ERR_UNIT_WINDOW_CONFLICT` (HTTP 409) when another line on the same
        unit in `RESERVED`, `OUT_ON_RENT`, or `OFF_RENT` status has a window
        intersecting the new one. Back-to-back bookings are expressly allowed
        — when an existing line's window ends exactly where the new window
        begins, that adjacency is not an intersection."

        Design: Difficulty/resource_temporal_overlap/unit_window_half_open
        """
        set_clock("2026-08-01T09:00:00Z")
        customer = create_customer("Window Co", "ops@window.example")
        cls = create_equipment_class(class_code="S19W")
        unit = create_equipment_unit(cls["id"], "S19W-001")
        contract_a = create_contract(customer["id"], "21 A Ave")
        add_line(contract_a["id"], unit["id"], "2026-08-05", "2026-08-10", 20)
        contract_b = create_contract(customer["id"], "22 B Ave")

        overlap = api.create_rental_line(
            create_rental_line_payload(contract_b["id"], unit["id"],
                                       "2026-08-10", "2026-08-12", 20,
                                       contract_b["version"]),
            rental_coordinator_headers)
        validate_error(overlap, ApiErrorId.ERR_UNIT_WINDOW_CONFLICT)

        adjacent = validate_success(api.create_rental_line(
            create_rental_line_payload(contract_b["id"], unit["id"],
                                       "2026-08-11", "2026-08-15", 20,
                                       contract_b["version"]),
            rental_coordinator_headers), 201)
        assert adjacent["status"] == "RESERVED", (
            "new start == existing window end is adjacency, not intersection")

    def test_window_rejection_preserves_contract_version(self, api,
            rental_coordinator_headers):
        """PRD §2.9: a window-overlapping line "is rejected with
        `ERR_UNIT_WINDOW_CONFLICT` (HTTP 409)"; nothing is written, so the
        `expected_contract_version` of PRD §2.7 ("the client's last observed
        `version` of the parent rental contract") still matches the retry.

        Design: Difficulty/resource_temporal_overlap/unit_window_half_open
        """
        set_clock("2026-08-01T09:00:00Z")
        customer = create_customer("Window2 Co", "ops@window2.example")
        cls = create_equipment_class(class_code="S19W2")
        unit = create_equipment_unit(cls["id"], "S19W2-001")
        contract_a = create_contract(customer["id"], "23 A Ave")
        add_line(contract_a["id"], unit["id"], "2026-08-05", "2026-08-10", 20)
        contract_b = create_contract(customer["id"], "24 B Ave")
        version_b = contract_b["version"]

        overlap = api.create_rental_line(
            create_rental_line_payload(contract_b["id"], unit["id"],
                                       "2026-08-08", "2026-08-12", 20,
                                       version_b), rental_coordinator_headers)
        validate_error(overlap, ApiErrorId.ERR_UNIT_WINDOW_CONFLICT)
        assert get_contract(contract_b["id"])["version"] == version_b

        adjacent = validate_success(api.create_rental_line(
            create_rental_line_payload(contract_b["id"], unit["id"],
                                       "2026-08-11", "2026-08-15", 20,
                                       version_b), rental_coordinator_headers), 201)
        assert adjacent["status"] == "RESERVED"


class TestOptimisticConcurrency:
    def test_occ_stale_version_rejected(self, api, rental_coordinator_headers):
        """PRD §2.7: "adding a rental line to a contract (`POST /rental-lines`)
        requires a non-optional `expected_contract_version` field carrying the
        client's last observed `version` of the parent rental contract. If the
        contract's current `version` no longer matches — because another
        writer added a line, activated the contract, or a cascade recomputed
        its subtotals — the request is rejected with `ERR_STALE_VERSION`
        (HTTP 412), preventing the client from writing against a contract it
        has not observed."

        Design: Corner/cross_cutting_complexity_layers/occ_stale_version_rejected
        """
        set_clock("2026-08-01T09:00:00Z")
        customer = create_customer("OCC Co", "ops@occ.example")
        cls = create_equipment_class(class_code="S19OC")
        u1 = create_equipment_unit(cls["id"], "S19OC-001")
        u2 = create_equipment_unit(cls["id"], "S19OC-002")
        contract = create_contract(customer["id"], "12 Version Ct")

        line1 = add_line(contract["id"], u1["id"], "2026-08-10",
                         "2026-08-15", 20,
                         expected_contract_version=contract["version"])
        assert line1["status"] == "RESERVED"
        version_2 = get_contract(contract["id"])["version"]

        line2 = add_line(contract["id"], u2["id"], "2026-08-10",
                         "2026-08-15", 20, expected_contract_version=version_2)
        assert line2["status"] == "RESERVED"

        stale = api.create_rental_line(
            create_rental_line_payload(contract["id"], u1["id"],
                                       "2026-08-20", "2026-08-25", 20,
                                       version_2), rental_coordinator_headers)
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION)

        data, meta = validate_paginated(api.list_rental_lines(
            rental_coordinator_headers,
            params={"contract_id": contract["id"]}))
        assert meta["total_count"] == 2, "rejected add created nothing"


class TestImmediateConsistency:
    def test_line_visible_in_list_with_computed_fields(self, api,
            rental_coordinator_headers):
        """PRD §3.4: "For a `RESERVED` line, the projected segment runs from
        midnight UTC on `requested_start_date` to midnight UTC on the day
        after `requested_end_date`, and the provisional charge is the
        best-rate calculation over that window." PRD §3.4: "Lines are listed
        with optional `contract_id`, `unit_id`, `class_id`, and `status`
        filters plus `limit` and `offset`, and are readable by
        `BranchManager`, `RentalCoordinator`, and `Customer`."

        Design: Corner/consistency_model/immediate_consistency_line_visible_in_list
        """
        ctx = setup_draft_contract_with_line(requested_start_date="2026-08-10",
                                             requested_end_date="2026-08-12")
        line = ctx["line"]
        assert line["status"] == "RESERVED"
        # 3 inclusive days: min(14500*3=43500, 43500*1, 99000*1) = 43500.
        assert line["provisional_charge_cents"] == 43500

        data, meta = validate_paginated(api.list_rental_lines(
            rental_coordinator_headers,
            params={"contract_id": ctx["contract"]["id"]}))
        assert meta["total_count"] == 1
        assert data[0]["id"] == line["id"], "created line is visible on the very next read"
