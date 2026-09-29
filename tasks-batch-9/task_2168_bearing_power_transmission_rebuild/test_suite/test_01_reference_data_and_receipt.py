"""Opening the books: accounts, machines, reman specs, benches and core receipt."""
import pytest

from test_helpers import (
    ADMIN_1, INSP_1, NON_EXISTENT_UUID, PLANNER_1, ApiErrorId, api_client as api,
    asset_payload, assert_bench, assert_clearance_standard, assert_core_unit,
    assert_customer, assert_customer_asset, assert_measurement,
    clearance_standard_payload, core_unit_payload, create_asset, create_bench,
    create_core, create_customer, create_order, create_reading, create_standard,
    customer_payload, ONE_BAND, FOUR_BANDS, add_measurement, credit_notes,
    is_valid_uuid, open_inspection, read_core, read_customer, setup_shop,
    validate_error, validate_paginated, validate_success,
)


class TestAccountsAndReferenceData:

    def test_new_account_opens_with_four_zero_balances_and_version_one(self):
        """PRD 3.1: "A newly opened account starts with all four ledger balances at zero."
        PRD 2.4: "Most resources additionally carry `updated_at`, in the same timestamp
        format, and `version`, an integer that starts at 1 when the row is created and
        increases by exactly 1 on every mutation of that row."

        Design: Corner/entities/customer_create_returns_zero_balances_and_version_one
        """
        resp = api.create_customer(
            customer_payload(name="Fresh Mill", account_code="FRS-001",
                             contact_email="rel@fresh.example"),
            ADMIN_1,
        )
        created = validate_success(resp, 201)
        assert_customer(created)

        fetched = validate_success(api.get_customer(created["id"], ADMIN_1))
        assert fetched["core_credit_balance_cents"] == 0
        assert fetched["warranty_credit_balance_cents"] == 0
        assert fetched["manual_credit_balance_cents"] == 0
        assert fetched["total_credit_balance_cents"] == 0
        assert fetched["version"] == 1, "a freshly opened account is at version 1"
        assert is_valid_uuid(fetched["id"]), "id must be a bare UUID with no type prefix"
        assert not fetched["id"].startswith("cust"), "the id carries no type prefix"
        assert fetched["account_code"] == "FRS-001"
        assert fetched["contact_email"] == "rel@fresh.example"

    def test_optional_reference_fields_take_their_declared_defaults(self):
        """PRD 3.1: "an optional `site_code` identifying the plant site, which defaults to
        `MAIN`."
        PRD 3.1: "and `cleanroom_required`, a boolean defaulting to false that says whether
        rebuilds of this model must occupy a cleanroom bench."
        PRD 3.1: "A bench's `committed_minutes` starts at zero and is maintained by the
        system thereafter; it is never client-supplied."
        PRD 3.2: "The number of prior rebuilds already on the core may be supplied as
        `rebuild_count` and defaults to zero when it is not."

        Design: Corner/entities/optional_fields_apply_their_declared_defaults
        """
        customer = create_customer(name="Default Mill", account_code="DEF-001")

        asset = validate_success(
            api.create_asset(customer["id"],
                             {"asset_tag": "DEF-01-GBX", "criticality": "STANDARD",
                              "duty_class": "STANDBY"}, ADMIN_1), 201)
        assert asset["site_code"] == "MAIN"

        standard = validate_success(api.create_clearance_standard({
            "model_code": "DEFAULT-SPEC-1", "base_core_value_cents": 90000,
            "max_rebuild_count": 3, "warranty_hours": 8000, "warranty_months": 18,
            "required_feature_codes": ["BORE"], "feature_bands": ONE_BAND,
        }, ADMIN_1), 201)
        assert standard["cleanroom_required"] is False

        bench = validate_success(api.create_bench(
            {"bench_code": "B-DEF", "parallel_slots": 1}, ADMIN_1), 201)
        assert bench["cleanroom"] is False
        assert bench["committed_minutes"] == 0

        core = validate_success(api.create_core_unit({
            "customer_id": customer["id"], "clearance_standard_id": standard["id"],
            "serial_no": "SN-DEF-1", "declared_condition_grade": "GRADE_B",
        }, ADMIN_1), 201)
        assert core["rebuild_count"] == 0
        assert core["provisional_core_credit_cents"] == 67500, (
            "GRADE_B on a 90000-cent base with no prior rebuilds is 67500"
        )

    def test_shape_violations_across_four_endpoints_are_invalid_request(self):
        """PRD 3.1: "a `criticality` that is either `CRITICAL` or `STANDARD`"
        PRD 3.1: "a `parallel_slots` count of at least 1 saying how many reservations may
        occupy the bench at the same instant"
        PRD 2.8: "That includes `qty` at least 1, `unit_cost_cents` at least 0, `labor_hours`
        strictly greater than 0, `run_hours_delta` strictly greater than 0, `parallel_slots`
        at least 1, `baseline_amplitude_g` strictly greater than 0, `amount_cents` at least 0,
        each band's upper micrometre bound strictly greater than its lower bound,
        `window_end_at` strictly after `window_start_at`"

        Design: Corner/entities/invalid_enum_and_out_of_range_values_are_rejected
        """
        world = setup_shop(account_code="RNG-001", customer_name="Range Mill",
                           asset_tag="RNG-01-GBX", serial_no="SN-RNG-1",
                           labor_hours=3.0, bench_code="B-RNG")
        cust_id, bench_id, order_id = (world["customer"]["id"], world["bench"]["id"],
                                       world["order"]["id"])

        validate_error(api.create_asset(cust_id, {
            "asset_tag": "RNG-02-GBX", "criticality": "SUPER_CRITICAL",
            "duty_class": "CONTINUOUS"}, ADMIN_1),
            ApiErrorId.ERR_INVALID_REQUEST.value, 400)

        validate_error(api.create_bench(
            {"bench_code": "B-RNG-2", "parallel_slots": 0, "cleanroom": False}, ADMIN_1),
            ApiErrorId.ERR_INVALID_REQUEST.value, 400)

        validate_error(api.create_bench_reservation({
            "rebuild_order_id": order_id, "bench_id": bench_id,
            "window_start_at": "2026-09-07T08:00:00Z",
            "window_end_at": "2026-09-07T08:00:00Z"}, PLANNER_1),
            ApiErrorId.ERR_INVALID_REQUEST.value, 400)

        validate_error(api.create_vibration_reading({
            "customer_asset_id": world["asset"]["id"],
            "reading_at": "2026-08-02T06:00:00Z", "overall_velocity_mm_s": 2.10,
            "bpfo_amplitude_g": 0.30, "bpfi_amplitude_g": 0.25,
            "baseline_amplitude_g": 0}, ADMIN_1),
            ApiErrorId.ERR_INVALID_REQUEST.value, 400)

        _, meta = validate_paginated(api.list_bench_reservations(bench_id, PLANNER_1))
        assert meta["total_count"] == 0, "no reservation survives the rejected request"
        _, meta = validate_paginated(api.list_customer_assets(cust_id, ADMIN_1))
        assert meta["total_count"] == 1, "the rejected asset was never registered"

    def test_missing_required_field_on_order_creation_is_invalid_request(self):
        """PRD 3.7: "A rebuild order is opened by a `Planner` or a `ShopAdmin` against the
        paying account's `customer_id`, the physical core's `core_unit_id`, the destination
        machine's `customer_asset_id`, and an estimate of bench `labor_hours` that must be
        strictly greater than zero."
        PRD 2.8: "Request-body shape: every required field present, every enum inside its
        declared value set, and every numeric range honoured."

        Design: Corner/entities/create_order_missing_required_fields_returns_invalid_request
        """
        world = setup_shop(account_code="REQ-001", customer_name="Req Mill",
                           asset_tag="REQ-01-GBX", serial_no="SN-REQ-1",
                           with_order=False)
        validate_error(api.create_rebuild_order({
            "customer_id": world["customer"]["id"],
            "core_unit_id": world["core"]["id"],
            "customer_asset_id": world["asset"]["id"]}, PLANNER_1),
            ApiErrorId.ERR_INVALID_REQUEST.value, 400)

        _, meta = validate_paginated(api.list_rebuild_orders(
            PLANNER_1, params={"customer_id": world["customer"]["id"]}))
        assert meta["total_count"] == 0, "the rejected creation writes no order row"

    def test_asset_creation_under_unknown_account_resolves_the_path_first(self):
        """PRD 2.5: "Identifiers embedded in a path are resolved strictly left to right, and
        the first identifier that fails to resolve determines the error."
        PRD 2.8: "Existence of every identifier embedded in the path, left to right — the
        per-entity 404 codes listed in §2.5."

        Design: Corner/entities/asset_creation_under_missing_customer_returns_not_found
        """
        anchor = create_customer(name="Anchor Mill", account_code="ANC-001")
        resp = api.create_asset("11111111-1111-4111-8111-111111111111",
                                {"asset_tag": "ORPHAN-01"}, ADMIN_1)
        error = validate_error(resp, ApiErrorId.ERR_CUSTOMER_NOT_FOUND.value, 404)
        assert error["error_id"] != ApiErrorId.ERR_INVALID_REQUEST.value, (
            "the unresolvable path id decides the answer before body shape is judged"
        )
        _, meta = validate_paginated(api.list_customer_assets(anchor["id"], ADMIN_1))
        assert meta["total_count"] == 0


class TestCoreReceiptAndListing:

    def test_receipt_ignores_client_supplied_computed_and_system_fields(self):
        """PRD 3.2: "The core's `model_code` is copied from the referenced spec at receipt and
        is never accepted from the client."
        PRD 2.4: "Clients never supply an `id`; an `id` offered in a request body is ignored,
        not rejected."
        PRD 2.8: "Unknown body fields are ignored rather than rejected, and so are client
        attempts to write computed or system-owned fields."

        Design: Corner/entities/core_unit_computed_and_system_fields_are_input_ignored
        """
        customer = create_customer(name="Ignore Mill", account_code="IGN-001")
        standard = create_standard(feature_bands=ONE_BAND)

        resp = api.create_core_unit({
            "customer_id": customer["id"], "clearance_standard_id": standard["id"],
            "serial_no": "SN-IGN-1", "rebuild_count": 1,
            "declared_condition_grade": "GRADE_D",
            "model_code": "FORGED-BY-CLIENT", "status": "SHIPPED",
            "provisional_core_credit_cents": 999999,
            "id": "00000000-0000-4000-8000-000000000000",
        }, ADMIN_1)
        core = validate_success(resp, 201)
        assert_core_unit(core)
        assert core["model_code"] == "SKF-22324-CCK"
        assert core["status"] == "RECEIVED"
        assert core["provisional_core_credit_cents"] == 10800
        assert core["id"] != "00000000-0000-4000-8000-000000000000"
        assert core["final_core_credit_cents"] is None
        assert read_customer(customer["id"])["core_credit_balance_cents"] == 10800

    def test_core_list_filters_on_each_declared_foreign_key(self):
        """PRD 3.2: "Cores can be listed and filtered by their `customer_id`, their
        `clearance_standard_id`, their `status`, and by `replacement_core_unit_id` — the last
        of which makes the self-referential replacement chain traversable, since a scrapped
        core may nominate the received core that takes its place."

        Design: Corner/entities/core_unit_filtered_list_resolves_children_from_each_declared_fk
        """
        from test_helpers import accept_inspection, submit_inspection
        world = setup_shop(account_code="FLT-001", customer_name="Filter Mill",
                           asset_tag="FLT-01-GBX", serial_no="SN-FLT-1",
                           declared_condition_grade="GRADE_D", labor_hours=4.0)
        cust_id, std_id = world["customer"]["id"], world["standard"]["id"]
        core_1 = world["core"]["id"]
        core_2 = create_core(cust_id, std_id, serial_no="SN-FLT-2",
                             declared_condition_grade="GRADE_B")["id"]

        reading = create_reading(world["asset"]["id"])
        insp = open_inspection(world["order"]["id"],
                               linked_vibration_reading_id=reading["id"])
        add_measurement(insp["id"], "BORE", 200)
        submit_inspection(insp["id"])
        accept_inspection(insp["id"])
        validate_success(api.advance_core_unit(
            core_1, {"action": "SCRAP", "replacement_core_unit_id": core_2}, ADMIN_1))

        _, meta = validate_paginated(api.list_core_units(ADMIN_1,
                                                         params={"customer_id": cust_id}))
        assert meta["total_count"] == 2
        _, meta = validate_paginated(
            api.list_core_units(ADMIN_1, params={"clearance_standard_id": std_id}))
        assert meta["total_count"] == 2
        rows, meta = validate_paginated(
            api.list_core_units(ADMIN_1, params={"replacement_core_unit_id": core_2}))
        assert meta["total_count"] == 1
        assert rows[0]["id"] == core_1

        scrapped = read_core(core_1)
        assert scrapped["status"] == "SCRAPPED"
        assert scrapped["replacement_core_unit_id"] == core_2

    def test_core_list_pages_report_total_count_and_has_more(self):
        """PRD 2.3: "`limit` controls page size: it defaults to 10 when omitted, may not be
        smaller than 1, and may not exceed 100."
        PRD 2.3: "The `meta` block of a list response carries `limit`, `offset`, `total_count`
        and `has_more`; `total_count` reports the number of rows matching the filter before
        paging is applied, and `has_more` is true exactly when rows remain beyond the current
        page."

        Design: Corner/entities/core_unit_listing_reports_total_count_and_has_more
        """
        customer = create_customer(name="Page Mill", account_code="PAG-001")
        standard = create_standard(feature_bands=ONE_BAND)
        for n in (1, 2, 3):
            create_core(customer["id"], standard["id"], serial_no=f"SN-PG-{n}",
                        declared_condition_grade="GRADE_B")

        rows, meta = validate_paginated(api.list_core_units(
            ADMIN_1, params={"customer_id": customer["id"], "limit": 2, "offset": 0}))
        assert len(rows) == 2 and meta["total_count"] == 3 and meta["has_more"] is True

        rows, meta = validate_paginated(api.list_core_units(
            ADMIN_1, params={"customer_id": customer["id"], "limit": 2, "offset": 2}))
        assert len(rows) == 1 and meta["total_count"] == 3 and meta["has_more"] is False

        _, meta = validate_paginated(api.list_core_units(
            ADMIN_1, params={"customer_id": customer["id"]}))
        assert meta["limit"] == 10, "limit defaults to 10 when omitted"

    def test_metrology_readings_are_append_only_observations(self):
        """PRD 2.4: "Two record types are deliberately leaner: a `Measurement` and a
        `VibrationReading` are immutable observations, so each carries only `id` and
        `created_at` — neither `updated_at` nor `version` is present on those two, and clients
        must not expect them."
        PRD 3.4: "The system stamps each reading with its owning `inspection_id`, taken from
        the path rather than the body, and with a `sequence_no`, a monotonic per-inspection
        counter starting at 1, which exists to break ties when two readings on the same
        feature share a creation instant."

        Design: Corner/entities/measurement_is_append_only_and_carries_no_version_field
        """
        world = setup_shop(account_code="IMM-001", customer_name="Immutable Mill",
                           asset_tag="IMM-01-GBX", serial_no="SN-IMM-1", labor_hours=3.0)
        insp = open_inspection(world["order"]["id"])

        first = validate_success(api.create_measurement(
            insp["id"], {"feature_code": "BORE", "measured_um": 70}, INSP_1), 201)
        second = validate_success(api.create_measurement(
            insp["id"], {"feature_code": "BORE", "measured_um": 72}, INSP_1), 201)

        for row in (first, second):
            assert_measurement(row)
            assert "updated_at" not in row
            assert "version" not in row
            assert row["band_result"] == "IN_SPEC"
            assert row["deviation_ratio"] == pytest.approx(0.0, abs=1e-9)
        assert first["sequence_no"] == 1 and second["sequence_no"] == 2

        rows, meta = validate_paginated(api.list_measurements(insp["id"], ADMIN_1))
        assert meta["total_count"] == 2
        for row in rows:
            assert "updated_at" not in row and "version" not in row


class TestProvisionalCoreValuation:

    def test_receipt_values_the_declared_grade_and_posts_the_provisional_note(self):
        """PRD 3.2: "First a tier: the base value is multiplied by the grade multiplier — 1.00
        for `GRADE_A`, 0.75 for `GRADE_B`, 0.45 for `GRADE_C`, 0.20 for `GRADE_D`, and 0.00 for
        `SCRAP` — and that product is rounded half up to whole cents."
        PRD 3.2: "Second a decay for prior service: eight percent of the base value, multiplied
        by the core's `rebuild_count`, rounded half up to whole cents, is subtracted."
        PRD 3.2: "A note is created with `kind` of `CORE_EXCHANGE`, `status` of `POSTED`, an
        `amount_cents` equal to the provisional credit, `core_unit_id` pointing at the core just
        received, and a system-written `memo`; the account's four balances are recomputed and
        the account's `version` advances by 1."

        Design: Difficulty/dual_variant_calc/core_credit_provisional_vs_final_diverge_on_same_core
        """
        world = setup_shop(account_code="NGM-001", asset_tag="CONV-04-GBX",
                           feature_bands=FOUR_BANDS, serial_no="SN-77001",
                           rebuild_count=1, declared_condition_grade="GRADE_D",
                           labor_hours=6.5)
        core = world["core"]
        assert core["provisional_core_credit_cents"] == 10800, (
            "round(90000 * 0.20) = 18000 less round(90000 * 0.08 * 1) = 7200"
        )
        assert core["condition_grade"] is None
        assert core["final_core_credit_cents"] is None

        rows, meta = credit_notes(core_unit_id=core["id"])
        assert meta["total_count"] == 1
        assert rows[0]["kind"] == "CORE_EXCHANGE"
        assert rows[0]["status"] == "POSTED"
        assert rows[0]["amount_cents"] == 10800
        assert rows[0]["core_unit_id"] == core["id"]

        customer = read_customer(world["customer"]["id"])
        assert customer["core_credit_balance_cents"] == 10800
        assert customer["total_credit_balance_cents"] == 10800
        assert customer["version"] > 1, "the balance recomputation advances the account"

    def test_bench_verdict_supersedes_the_declared_valuation_on_the_same_core(self):
        """PRD 3.6: "The grade in use is the bench-verified `remaining_life_grade` from the
        accepted inspection rather than the customer's `declared_condition_grade`, run through
        the same multipliers: 1.00 for `GRADE_A`, 0.75 for `GRADE_B`, 0.45 for `GRADE_C`, 0.20
        for `GRADE_D`, 0.00 for `SCRAP`, with the product rounded half up to whole cents."
        PRD 2.9: "A `CreditNote` is never edited in place and never deleted: it is created
        `POSTED` and, if it must be undone, transitioned to `VOID`."
        PRD 3.6: "The customer's balance therefore moves by the difference between the final and
        provisional valuations, which is frequently negative when the bench disagrees with the
        drop-off declaration."

        Design: Difficulty/dual_variant_calc/core_credit_provisional_vs_final_diverge_on_same_core
        """
        from test_helpers import inspect_order
        world = setup_shop(account_code="NGM-001", asset_tag="CONV-04-GBX",
                           feature_bands=FOUR_BANDS, serial_no="SN-77001",
                           rebuild_count=1, declared_condition_grade="GRADE_D",
                           labor_hours=6.5)
        inspect_order(world)

        core = read_core(world["core"]["id"])
        assert core["provisional_core_credit_cents"] == 10800
        assert core["condition_grade"] == "GRADE_A"
        assert core["final_core_credit_cents"] == 81450, (
            "90000 tiered, less 7200 decay, less the 1350 half-strength REWORKABLE line"
        )

        rows, meta = credit_notes(core_unit_id=core["id"])
        assert meta["total_count"] == 2, "the provisional note survives as a VOID row"
        by_amount = {row["amount_cents"]: row for row in rows}
        assert by_amount[10800]["status"] == "VOID"
        assert by_amount[81450]["status"] == "POSTED"

        customer = read_customer(world["customer"]["id"])
        assert customer["core_credit_balance_cents"] == 81450
        assert customer["total_credit_balance_cents"] == 81450
