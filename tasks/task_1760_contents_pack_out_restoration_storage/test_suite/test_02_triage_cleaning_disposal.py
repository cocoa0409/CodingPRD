"""Triage loop, cleaning rework loop, disposal pipeline, and item-level OCC
(PRD §2.6, §3.2, §3.3).
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
    setup_job_with_room, register_item, triage_item, get_item,
    create_cleaning_task, transition_cleaning_task,
    setup_item_in_storage, create_statement, set_clock,
    setup_documented_disposal, setup_disposed_item, get_disposal_record_for_item,
    make_project_manager_headers,
)

PM = TEST_USERS["project_manager_headers"]
TECH = TEST_USERS["inventory_technician_headers"]
TECH1 = TEST_USERS["tech1_headers"]
PM9 = TEST_USERS["pm9_headers"]


class TestRetriageLoop:
    def test_retriage_loop_cycles_both_item_dimensions(self, api):
        """PRD §3.2: "Triage is a cyclic dimension: from `PENDING`, `SALVAGEABLE`,
        or `NON_SALVAGEABLE` an item may be re-determined to either outcome,
        provided the item's `processing_status` has not reached one of the terminal
        states `DISPOSED`, `DELIVERED`, or `CLAIM_SETTLED` — any mutation of a
        terminal item is rejected with `ERR_ITEM_TERMINAL` — and provided the item
        currently sits in `REGISTERED`, `AWAITING_CLEANING`, `IN_STORAGE`, or
        `AWAITING_DISPOSAL`; triage from any other processing state is rejected with
        `ERR_INVALID_TRANSITION`."
        PRD §3.2: "Every successful triage decision, including a re-triage,
        increments the item's `triage_count` by one and bumps the item's `version`
        by one."
        PRD §3.2: "A `SALVAGEABLE` determination moves the item's `processing_status`
        to `AWAITING_CLEANING`."

        Design: Difficulty/non_linear_state_machine/item_parallel_dimensions_retriage_loop
        """
        job, room = setup_job_with_room(
            job_overrides={"claim_number": "CLM-NL2", "property_address": "8 Maple Dr"},
            room_overrides={"name": "Bedroom", "room_type": "BEDROOM"})
        item = register_item(room["id"], barcode="BC-NL2", description="Dresser",
                             item_category="FURNITURE", declared_value_cents=30000,
                             volume_cu_ft=20)

        v = item["version"]
        for determination in ("SALVAGEABLE", "NON_SALVAGEABLE", "SALVAGEABLE"):
            updated = triage_item(item["id"], v, determination)
            v = updated["version"]

        final = get_item(item["id"])
        assert final["condition_triage"] == "SALVAGEABLE", (
            f"after SALV->NON_SALV->SALV cycle expected SALVAGEABLE, got {final['condition_triage']}")
        assert final["processing_status"] == "AWAITING_CLEANING", (
            f"processing dimension must track the latest determination, got {final['processing_status']}")
        assert final["triage_count"] == 3, (
            f"three successful triage decisions must yield triage_count 3, got {final['triage_count']}")

    def test_retriage_salvageable_voids_pending_disposal_record(self, api):
        """PRD §3.2: "If the item was sitting in `AWAITING_DISPOSAL`, the re-triage
        pulls it back from the brink: its disposal record, if still `DRAFT` or
        `DOCUMENTED` (that is, not yet verified), is automatically voided."

        Design: Difficulty/non_linear_state_machine/item_parallel_dimensions_retriage_loop
        """
        job, room = setup_job_with_room(
            job_overrides={"claim_number": "CLM-NL2B", "property_address": "8 Maple Dr"},
            room_overrides={"name": "Bedroom", "room_type": "BEDROOM"})
        item = register_item(room["id"], barcode="BC-NL2B", description="Dresser",
                             item_category="FURNITURE", declared_value_cents=30000,
                             volume_cu_ft=20)

        v = triage_item(item["id"], item["version"], "SALVAGEABLE")["version"]
        v = triage_item(item["id"], v, "NON_SALVAGEABLE")["version"]

        records = get_disposal_record_for_item(item["id"])
        assert len(records) == 1 and records[0]["status"] == "DRAFT", (
            f"precondition: NON_SALVAGEABLE leg auto-creates a DRAFT record, got {records}")
        first_record_id = records[0]["id"]

        # The void itself is not directly observable through the fetch endpoint:
        # PRD pins the fetch only as "an array of zero or one entries" and pins
        # the auto-create rule to "if no non-voided one exists", so whether a
        # VOIDED record is returned by the fetch is not uniquely derivable.
        # Observe the void through the auto-create rule instead: re-entering
        # AWAITING_DISPOSAL must create a fresh DRAFT record, which is possible
        # only if the SALVAGEABLE re-triage voided the first record.
        v = triage_item(item["id"], v, "SALVAGEABLE")["version"]
        triage_item(item["id"], v, "NON_SALVAGEABLE")

        records = get_disposal_record_for_item(item["id"])
        assert len(records) == 1, f"the record is 1:1 with the item, got {len(records)}"
        assert records[0]["status"] == "DRAFT", (
            f"re-entry to AWAITING_DISPOSAL auto-creates a DRAFT record, "
            f"got {records[0]['status']}")
        assert records[0]["id"] != first_record_id, (
            "a fresh record exists only because the SALVAGEABLE re-triage voided "
            "the unverified first record (auto-create fires only when no "
            "non-voided record exists)")


class TestDisposalCascadeFromStorage:
    def _setup_stored_item_with_provisional_statement(self):
        """GENERAL item (vol 40) IN_STORAGE at rate 150/cu ft (monthly 6000),
        placed 2026-08-10; PROVISIONAL statement [2026-08-01, 2026-09-01) created
        2026-08-15 showing 6000 (one calendar month touched)."""
        ctx = setup_item_in_storage(
            job_overrides={"claim_number": "CLM-TC1", "property_address": "11 Ash St"},
            room_overrides={"name": "Garage", "room_type": "GARAGE"},
            item_overrides={"barcode": "BC-TC1", "description": "Workbench",
                            "item_category": "GENERAL", "declared_value_cents": 40000,
                            "volume_cu_ft": 40},
            vault_overrides={"code": "V-TC1", "climate_class": "CLIMATE_CONTROLLED",
                             "capacity_cu_ft": 10000, "monthly_rate_cents_per_cu_ft": 150},
            placed_clock_iso="2026-08-10T09:00:00Z")
        set_clock("2026-08-15T09:00:00Z")
        stmt = create_statement(ctx["job"]["id"], "2026-08-01", "2026-09-01")
        assert stmt["provisional_total_cents"] == 6000, (
            f"precondition: provisional accrual 6000, got {stmt['provisional_total_cents']}")
        ctx["statement"] = stmt
        return ctx

    def test_non_salvageable_triage_creates_draft_disposal_record(self, api):
        """PRD §3.2: "A `NON_SALVAGEABLE` determination moves the item to
        `AWAITING_DISPOSAL` and sets off a four-link cascade."
        PRD §3.2: "Second, entering `AWAITING_DISPOSAL` auto-creates a `DRAFT`
        disposal record for the item if no non-voided one exists — the record is
        one-to-one with the item."

        Design: Difficulty/transitive_cascade/disposal_retriage_cascade_depth4
        """
        ctx = self._setup_stored_item_with_provisional_statement()
        item = ctx["item"]

        triage_item(item["id"], item["version"], "NON_SALVAGEABLE")

        after = get_item(item["id"])
        assert after["processing_status"] == "AWAITING_DISPOSAL", (
            f"cascade link 1: expected AWAITING_DISPOSAL, got {after['processing_status']}")
        records = get_disposal_record_for_item(item["id"])
        assert len(records) == 1, f"cascade link 2: exactly one record, got {len(records)}"
        assert records[0]["status"] == "DRAFT", (
            f"cascade link 2: auto-created record must be DRAFT, got {records[0]['status']}")

    def test_non_salvageable_triage_releases_placement_and_recomputes_accrual(self, api):
        """PRD §3.2: "Third, if the item was in `IN_STORAGE`, its active storage
        placement is automatically released with `release_reason` `DISPOSAL`.
        Fourth, that release decrements the vault's `occupied_cu_ft` by the item's
        `volume_cu_ft` and recomputes `provisional_total_cents` on every
        `PROVISIONAL` statement of the job plus the job's
        `accrued_storage_total_cents`."

        Design: Difficulty/transitive_cascade/disposal_retriage_cascade_depth4
        """
        ctx = self._setup_stored_item_with_provisional_statement()
        item, vault, stmt = ctx["item"], ctx["vault"], ctx["statement"]

        triage_item(item["id"], item["version"], "NON_SALVAGEABLE")

        placements = get_success_data(api.list_item_placements(item["id"], TECH))
        assert len(placements) == 1
        assert placements[0]["status"] == "RELEASED", (
            f"cascade link 3: placement must be RELEASED, got {placements[0]['status']}")
        assert placements[0]["release_reason"] == "DISPOSAL", (
            f"cascade link 3: release_reason must be DISPOSAL, got {placements[0]['release_reason']}")

        vault_after = get_success_data(api.get_vault(vault["id"], TECH))
        assert vault_after["occupied_cu_ft"] == 0, (
            f"cascade link 4: occupancy must drop from 40 to 0, got {vault_after['occupied_cu_ft']}")

        stmt_after = get_success_data(api.get_storage_statement(stmt["id"], TEST_USERS["billing_clerk_headers"]))
        assert stmt_after["provisional_total_cents"] == 0, (
            f"cascade link 4: provisional recompute must exclude the released placement "
            f"(was 6000), got {stmt_after['provisional_total_cents']}")

        job_after = get_success_data(api.get_pack_out_job(ctx["job"]["id"], TECH))
        assert job_after["accrued_storage_total_cents"] == 0, (
            f"cascade link 4: job accrual must recompute to 0, got {job_after['accrued_storage_total_cents']}")


class TestCleaningRework:
    def _setup_failed_task(self):
        """APPLIANCE item triaged SALVAGEABLE; task START then QA_FAIL."""
        job, room = setup_job_with_room(
            job_overrides={"claim_number": "CLM-NL1", "property_address": "7 Willow Way"},
            room_overrides={"name": "Kitchen", "room_type": "KITCHEN"})
        item = register_item(room["id"], barcode="BC-NL1", description="Toaster",
                             item_category="APPLIANCE", declared_value_cents=8000,
                             volume_cu_ft=3)
        triage_item(item["id"], item["version"], "SALVAGEABLE")
        task = create_cleaning_task(item["id"])
        transition_cleaning_task(task["id"], "START")
        failed = transition_cleaning_task(task["id"], "QA_FAIL", qa_note="odor remains")
        assert failed["status"] == "FAILED", f"precondition FAILED, got {failed['status']}"
        return job, item, task

    def test_rework_cycle_returns_task_to_in_progress_then_passes(self, api):
        """PRD §3.3: "A failing QA moves the task to `FAILED` while the item stays
        `IN_CLEANING` awaiting rework; a subsequent rework returns the task to
        `IN_PROGRESS` and increments its `rework_count` by one. The rework cycle
        may repeat as often as needed."

        Design: Difficulty/non_linear_state_machine/cleaning_task_rework_cycle
        """
        _job, item, task = self._setup_failed_task()

        reworked = transition_cleaning_task(task["id"], "REWORK")
        assert reworked["status"] == "IN_PROGRESS", (
            f"REWORK must return the task to IN_PROGRESS, got {reworked['status']}")
        assert reworked["rework_count"] == 1, (
            f"one REWORK must set rework_count to 1, got {reworked['rework_count']}")

        passed = transition_cleaning_task(task["id"], "QA_PASS")
        assert passed["status"] == "PASSED", (
            f"the loop closes at terminal PASSED, got {passed['status']}")
        assert passed["rework_count"] == 1

    def test_passed_task_computes_base_fee_and_cleans_item(self, api):
        """PRD §3.3: "A passing QA moves the task to its terminal `PASSED` state,
        moves the item to `CLEANED`, bumps the item's `version`, and computes the
        task's `fee_cents`: a base of 12000 cents plus a deodorization adder of
        4000 cents when `deodorization_required` was snapshotted true, exact
        integer cents with no rounding."

        Design: Difficulty/non_linear_state_machine/cleaning_task_rework_cycle
        """
        _job, item, task = self._setup_failed_task()
        transition_cleaning_task(task["id"], "REWORK")
        passed = transition_cleaning_task(task["id"], "QA_PASS")

        assert passed["fee_cents"] == 12000, (
            f"no smoke damage -> base fee only, expected 12000, got {passed['fee_cents']}")
        item_after = get_item(item["id"])
        assert item_after["processing_status"] == "CLEANED", (
            f"passing QA moves the item to CLEANED, got {item_after['processing_status']}")

    def test_cleaning_start_twice_returns_invalid_transition(self, api):
        """PRD §3.3: "Starting it — permitted only while the item's
        `processing_status` is `AWAITING_CLEANING`, otherwise
        `ERR_INVALID_TRANSITION`"

        Design: Corner/state_machines/cleaning_start_twice_returns_invalid_transition
        """
        job, room = setup_job_with_room(
            job_overrides={"claim_number": "CLM-SM2", "property_address": "48 Cedar St"},
            room_overrides={"name": "Kitchen", "room_type": "KITCHEN"})
        item = register_item(room["id"], barcode="BC-SM2", description="Blender",
                             item_category="APPLIANCE", declared_value_cents=3000,
                             volume_cu_ft=2)
        triage_item(item["id"], item["version"], "SALVAGEABLE")
        task = create_cleaning_task(item["id"])
        started = transition_cleaning_task(task["id"], "START")
        assert started["status"] == "IN_PROGRESS"

        res = api.transition_cleaning_task(task["id"], {"action": "START"}, TECH)
        validate_error(res, ApiErrorId.ERR_INVALID_TRANSITION, expected_status=409)

        tasks = get_success_data(api.list_cleaning_tasks(item["id"], TECH))
        assert tasks[0]["status"] == "IN_PROGRESS", (
            f"the rejected duplicate START must leave the task IN_PROGRESS, got {tasks[0]['status']}")

    def test_cleaning_fee_deodorization_adder(self, api):
        """PRD §3.3: "At the same moment the task snapshots `deodorization_required`
        from the item's `smoke_damage_flag`; later flag changes on the item do not
        alter the task."
        PRD §3.3: "computes the task's `fee_cents`: a base of 12000 cents plus a
        deodorization adder of 4000 cents when `deodorization_required` was
        snapshotted true, exact integer cents with no rounding."

        Design: Corner/calculations/cleaning_fee_deodorization_adder
        """
        job, room = setup_job_with_room(
            job_overrides={"claim_number": "CLM-CA1", "property_address": "60 Cherry St"},
            room_overrides={"name": "Kitchen", "room_type": "KITCHEN"})
        item = register_item(room["id"], barcode="BC-CA1", description="Smoke sofa",
                             item_category="GENERAL", declared_value_cents=3000,
                             volume_cu_ft=20, smoke_damage_flag=True)
        triage_item(item["id"], item["version"], "SALVAGEABLE")
        task = create_cleaning_task(item["id"])
        assert task["deodorization_required"] is True, (
            "the flag must be snapshotted from the smoke-damaged item at task creation")

        transition_cleaning_task(task["id"], "START")
        passed = transition_cleaning_task(task["id"], "QA_PASS")
        assert passed["fee_cents"] == 16000, (
            f"12000 base + 4000 deodorization adder, expected 16000, got {passed['fee_cents']}")


class TestDisposalPipeline:
    def test_disposal_verify_completes_item(self, api):
        """PRD §3.2: "Verification is then performed by a `ProjectManager` whose
        identity differs from `documented_by_user_id` — the segregation-of-duties
        rule of §2.1, violated requests rejected with `ERR_SEGREGATION_OF_DUTIES` —
        which stamps `verified_by_user_id`, moves the record to `VERIFIED`, flips
        the item's `processing_status` to `DISPOSED`, and triggers the room and job
        compound recompute that bubbles up the tree."

        Design: Corner/state_machines/disposal_verify_completes_item
        """
        ctx = setup_documented_disposal(
            item_overrides={"barcode": "BC-SM6", "description": "Moldy boxes",
                            "item_category": "GENERAL", "declared_value_cents": 200,
                            "volume_cu_ft": 6})
        record = ctx["record"]
        assert record["status"] == "DOCUMENTED" and record["documented_by_user_id"] == "tech-1"

        res = api.transition_disposal_record(record["id"], {"action": "VERIFY"}, PM9)
        verified = validate_success(res, 200)
        assert verified["status"] == "VERIFIED"
        assert verified["verified_by_user_id"] == "pm-9"

        item_after = get_item(ctx["item"]["id"])
        assert item_after["processing_status"] == "DISPOSED", (
            f"VERIFY flips the item to terminal DISPOSED, got {item_after['processing_status']}")

    def test_disposal_verify_same_user_rejected(self, api):
        """PRD §2.1: "The operator verifying a disposal record must differ from the
        operator who documented it, so `verified_by_user_id` may never equal
        `documented_by_user_id`." and "Any violation of these rules is rejected
        with `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/validations/disposal_verify_same_user_rejected
        """
        ctx = setup_documented_disposal(
            item_overrides={"barcode": "BC-V7", "description": "Contaminated chair",
                            "item_category": "FURNITURE", "declared_value_cents": 1000,
                            "volume_cu_ft": 10})
        record = ctx["record"]

        res = api.transition_disposal_record(
            record["id"], {"action": "VERIFY"}, make_project_manager_headers("tech-1"))
        validate_error(res, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, expected_status=403)

        records = get_disposal_record_for_item(ctx["item"]["id"])
        assert records[0]["status"] == "DOCUMENTED", (
            f"the rejected VERIFY must leave the record DOCUMENTED, got {records[0]['status']}")

    def test_hazmat_disposal_document_without_manifest_rejected(self, api):
        """PRD §3.2: "When the item's `hazmat_flag` is true, documentation
        additionally requires a `manifest_number` and the `disposal_method` must be
        `HAZARDOUS_WASTE`; a hazmat documentation missing the manifest or naming
        any other method is rejected with `ERR_HAZMAT_MANIFEST_REQUIRED`."

        Design: Corner/validations/hazmat_disposal_document_without_manifest_rejected
        """
        job, room = setup_job_with_room(
            job_overrides={"claim_number": "CLM-V10", "property_address": "102 Elm St"},
            room_overrides={"name": "Basement", "room_type": "BASEMENT"})
        item = register_item(room["id"], barcode="BC-V10", description="Chemical drums",
                             item_category="GENERAL", declared_value_cents=500,
                             volume_cu_ft=6, hazmat_flag=True)
        triage_item(item["id"], item["version"], "NON_SALVAGEABLE")
        record = get_disposal_record_for_item(item["id"])[0]

        res = api.transition_disposal_record(record["id"], {
            "action": "DOCUMENT", "disposal_method": "LANDFILL",
            "facility_name": "City Landfill"}, TECH1)
        validate_error(res, ApiErrorId.ERR_HAZMAT_MANIFEST_REQUIRED, expected_status=422)

        records = get_disposal_record_for_item(item["id"])
        assert records[0]["status"] == "DRAFT", (
            f"the rejected DOCUMENT must leave the record DRAFT, got {records[0]['status']}")

    def test_terminal_item_rejects_triage(self, api):
        """PRD §3.2: "provided the item's `processing_status` has not reached one of
        the terminal states `DISPOSED`, `DELIVERED`, or `CLAIM_SETTLED` — any
        mutation of a terminal item is rejected with `ERR_ITEM_TERMINAL`"

        Design: Corner/state_machines/terminal_item_rejects_triage
        """
        ctx = setup_disposed_item(
            item_overrides={"barcode": "BC-SM1", "description": "Soaked sofa",
                            "item_category": "FURNITURE", "declared_value_cents": 4000,
                            "volume_cu_ft": 30})
        item = ctx["item"]
        assert item["processing_status"] == "DISPOSED", "precondition: item terminal"

        res = api.triage_item(item["id"], {
            "determination": "SALVAGEABLE",
            "expected_item_version": item["version"]}, TECH)
        validate_error(res, ApiErrorId.ERR_ITEM_TERMINAL, expected_status=409)

        after = get_item(item["id"])
        assert after["processing_status"] == "DISPOSED"
        assert after["condition_triage"] == "NON_SALVAGEABLE"


class TestItemOptimisticConcurrency:
    def test_occ_stale_item_version_returns_412(self, api):
        """PRD §2.6: "If another triage decision has advanced the item's `version`
        since the client last read it, the request is rejected with
        `ERR_STALE_ITEM_VERSION` (HTTP 412)."
        PRD §2.6: "a second triage request observes a valid triage state and would
        succeed on state grounds alone; the version check is what prevents a client
        from overwriting a decision it has not observed."

        Design: Corner/cross_cutting_layers/occ_stale_item_version_returns_412
        """
        job, room = setup_job_with_room(
            job_overrides={"claim_number": "CLM-LA1", "property_address": "92 Pine St"},
            room_overrides={"name": "Study", "room_type": "OTHER"})
        item = register_item(room["id"], barcode="BC-LA1", description="Desk",
                             item_category="FURNITURE", declared_value_cents=5000,
                             volume_cu_ft=12)
        stale_version = item["version"]

        first = api.triage_item(item["id"], {
            "determination": "SALVAGEABLE", "expected_item_version": stale_version}, TECH)
        updated = validate_success(first, 200)
        assert updated["version"] == stale_version + 1

        res = api.triage_item(item["id"], {
            "determination": "NON_SALVAGEABLE", "expected_item_version": stale_version}, TECH)
        validate_error(res, ApiErrorId.ERR_STALE_ITEM_VERSION, expected_status=412)

        after = get_item(item["id"])
        assert after["condition_triage"] == "SALVAGEABLE", (
            f"the stale request must not overwrite the observed decision, got {after['condition_triage']}")
