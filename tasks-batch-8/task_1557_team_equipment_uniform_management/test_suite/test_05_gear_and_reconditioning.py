"""Protective gear: lookup, safety-gated issue, asset-tag uniqueness, and the
reconditioning loop with provider capacity."""
from test_helpers import (
    EM,
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_gear_item,
    assert_reconditioning_job,
    create_gear,
    create_player,
    create_reconditioning_job,
    get_gear,
    get_job,
    issue_gear,
    setup_player_with_issued_gear,
    validate_error,
    validate_success,
)


class TestGearLookup:
    def test_gear_get_not_found_returns_404(self, api):
        """PRD §2.9: "referenced resources exist, checked left-to-right across
        the path identifiers first and then the identifiers referenced in the
        body (`player_id`, pool ids, `supplier_contract_id`, `item_id`, and so
        on), each surfacing its specific not-found error such as
        `ERR_PLAYER_NOT_FOUND`, `ERR_POOL_NOT_FOUND`, `ERR_CONTRACT_NOT_FOUND`,
        `ERR_ORDER_NOT_FOUND`, `ERR_KIT_ASSIGNMENT_NOT_FOUND`,
        `ERR_GEAR_ITEM_NOT_FOUND`"

        Design: Corner/entities/gear_get_not_found_returns_404
        """
        resp = api.get_gear_item(NON_EXISTENT_UUID, EM)
        validate_error(resp, ApiErrorId.ERR_GEAR_ITEM_NOT_FOUND)
        assert resp.status_code == 404


class TestGearStateMachine:
    def test_gear_issue_from_issued_rejected(self, api):
        """PRD §3.5: "the item must be `IN_STOCK` (`ERR_GEAR_NOT_IN_STOCK`),
        the player must be `ACTIVE` (`ERR_PLAYER_NOT_ACTIVE`)"
        PRD §3.5: "Issue sets the item's `current_holder_id` to the player and
        increments its `version`."

        Design: Corner/state_machines/gear_issue_from_issued_rejected
        """
        p1 = create_player(full_name="G One")
        p2 = create_player(full_name="G Two", position_group="DEFENSE")
        gear = create_gear(asset_tag="HLM-904")
        issued = issue_gear(gear["id"], p1["id"])
        assert issued["status"] == "ISSUED"
        assert issued["current_holder_id"] == p1["id"]

        resp = api.issue_gear_item(gear["id"], {"player_id": p2["id"]}, EM)
        validate_error(resp, ApiErrorId.ERR_GEAR_NOT_IN_STOCK)
        after = get_gear(gear["id"])
        assert after["status"] == "ISSUED"
        assert after["current_holder_id"] == p1["id"], (
            "The rejected second issue does not move the holder")

    def test_gear_return_from_in_stock_rejected(self, api):
        """PRD §3.5: "A return — valid only from `ISSUED`
        (`ERR_GEAR_NOT_ISSUED`) — moves the item back to `IN_STOCK` and clears
        the holder."

        Design: Corner/state_machines/gear_return_from_in_stock_rejected
        """
        gear = create_gear(asset_tag="KBR-901", item_type="KNEE_BRACE",
                           size_spec="KNEE-M", certification_expires_on=None)
        assert gear["status"] == "IN_STOCK"

        resp = api.return_gear_item(gear["id"], EM)
        validate_error(resp, ApiErrorId.ERR_GEAR_NOT_ISSUED)
        assert get_gear(gear["id"])["status"] == "IN_STOCK"


class TestGearSafetyGates:
    def test_certification_expiry_boundary_exactly_now_rejected(self, api):
        """PRD §3.5: "for `HELMET` and `SHOULDER_PADS`,
        `certification_expires_on` must be present and strictly later than the
        logical clock's now (`ERR_GEAR_CERTIFICATION_EXPIRED`)"
        PRD §2.4: "At server startup the logical clock reads exactly
        `2026-08-01T00:00:00Z`."

        Design: Corner/calculations/certification_expiry_boundary_exactly_now_rejected
        """
        player = create_player(full_name="Cert One")
        expiring_now = create_gear(asset_tag="HLM-906",
                                   certification_expires_on="2026-08-01T00:00:00Z")
        one_second_later = create_gear(
            asset_tag="HLM-907", certification_expires_on="2026-08-01T00:00:01Z")

        resp = api.issue_gear_item(expiring_now["id"], {"player_id": player["id"]}, EM)
        validate_error(resp, ApiErrorId.ERR_GEAR_CERTIFICATION_EXPIRED)
        assert get_gear(expiring_now["id"])["status"] == "IN_STOCK", (
            "Expiry exactly at the clock is not strictly later than now")

        issued = validate_success(api.issue_gear_item(
            one_second_later["id"], {"player_id": player["id"]}, EM))
        assert issued["status"] == "ISSUED", (
            "One second past the clock satisfies the strict comparison")

    def test_gear_condition_f_not_issuable_rejected(self, api):
        """PRD §3.5: "no item graded `F` may ever be issued
        (`ERR_GEAR_CONDITION_NOT_ISSUABLE`)"
        PRD §3.5: "grades run `A`, `B`, `C`, and `F`, where `F` marks a failed,
        non-issuable item."

        Design: Corner/validations/gear_condition_f_not_issuable_rejected
        """
        player = create_player(full_name="Eff One")
        gear = create_gear(asset_tag="HLM-909", acquired_on="2024-01-01",
                           condition_grade="F",
                           certification_expires_on="2028-01-01T00:00:00Z")

        resp = api.issue_gear_item(gear["id"], {"player_id": player["id"]}, EM)
        validate_error(resp, ApiErrorId.ERR_GEAR_CONDITION_NOT_ISSUABLE)
        assert get_gear(gear["id"])["status"] == "IN_STOCK", (
            "A failed-grade item never leaves stock, even with a valid certification")

    def test_player_gear_limit_second_helmet_rejected(self, api):
        """PRD §3.5: "finally, a player may hold at most one issued item of
        each `item_type` (`ERR_PLAYER_GEAR_LIMIT_REACHED`)."

        Design: Corner/validations/player_gear_limit_second_helmet_rejected
        """
        player = create_player(full_name="Lim One")
        h1 = create_gear(asset_tag="HLM-910", size_spec="HELMET-L")
        h2 = create_gear(asset_tag="HLM-911", size_spec="HELMET-M")
        issue_gear(h1["id"], player["id"])

        resp = api.issue_gear_item(h2["id"], {"player_id": player["id"]}, EM)
        validate_error(resp, ApiErrorId.ERR_PLAYER_GEAR_LIMIT_REACHED)
        after = get_gear(h2["id"])
        assert after["status"] == "IN_STOCK"
        assert after["current_holder_id"] is None, (
            "The second helmet stays in stock with no holder")

    def test_gear_issue_safety_beats_gear_limit(self, api):
        """PRD §2.9: "Incoming requests are checked against a fixed priority
        cascade so that an earlier failure always masks a later one; the
        client sees the first failing category, not an arbitrary one."
        PRD §2.9: "6. **Protective-gear safety** — certification and condition
        gates on gear issue (`ERR_GEAR_CERTIFICATION_EXPIRED`,
        `ERR_GEAR_CONDITION_NOT_ISSUABLE`)."
        PRD §2.9: "7. **Uniqueness and structural constraints** — jersey
        numbers, asset tags, pool identity, one-issued-item-per-type, contract
        garment coverage, claim-subject ownership, and kit-pool season
        alignment"

        Design: Difficulty/priority_pair_validation_conflict/gear_issue_safety_beats_gear_limit
        """
        player = create_player(full_name="Safe One", position_group="DEFENSE")
        h1 = create_gear(asset_tag="HLM-401", acquired_on="2025-01-15",
                         certification_expires_on="2028-01-01T00:00:00Z")
        h2 = create_gear(asset_tag="HLM-402", acquired_on="2023-01-15",
                         certification_expires_on="2026-07-01T00:00:00Z")
        issue_gear(h1["id"], player["id"])

        resp = api.issue_gear_item(h2["id"], {"player_id": player["id"]}, EM)
        validate_error(resp, ApiErrorId.ERR_GEAR_CERTIFICATION_EXPIRED)
        assert resp.status_code == 409, (
            "The safety gate (priority 6) masks the one-per-type limit (priority 7)")
        after = get_gear(h2["id"])
        assert after["status"] == "IN_STOCK"
        assert after["current_holder_id"] is None


class TestGearIdentity:
    def test_gear_duplicate_asset_tag_rejected(self, api):
        """PRD §3.5: "An `EquipmentManager` registers a gear item with a
        unique `asset_tag` (duplicates answer `ERR_ASSET_TAG_TAKEN`)"

        Design: Corner/validations/gear_duplicate_asset_tag_rejected
        """
        create_gear(asset_tag="HLM-908")
        resp = api.create_gear_item(
            {
                "asset_tag": "HLM-908",
                "item_type": "SHOULDER_PADS",
                "size_spec": "PADS-L",
                "acquired_on": "2025-01-01",
            },
            EM,
        )
        validate_error(resp, ApiErrorId.ERR_ASSET_TAG_TAKEN)


class TestReconditioningCycle:
    def test_gear_item_issue_recondition_cycle(self, api):
        """PRD §3.5: "A return — valid only from `ISSUED`
        (`ERR_GEAR_NOT_ISSUED`) — moves the item back to `IN_STOCK` and clears
        the holder."
        PRD §3.5: "A created job is `OUT`, and the item moves to
        `OUT_FOR_RECONDITIONING`."
        PRD §3.5: "Each open job occupies a half-open window covering the send
        date up to but not including its `due_back_on`, which is exactly 45
        days after `sent_on`."
        PRD §3.5: "On a pass, the job's `result_recorded_on` is stamped with
        the logical clock's date, its `certification_valid_until` is computed
        as that date plus 365 days, and the item returns to `IN_STOCK` with
        its `condition_grade` set to the result grade and its
        `certification_expires_on` set to that validity date mapped to a
        timestamp at midnight UTC."

        Design: Difficulty/non_linear_state_machine/gear_item_issue_recondition_cycle
        """
        player = create_player(full_name="Cyc One")
        gear = create_gear(asset_tag="HLM-201", acquired_on="2025-06-01",
                           certification_expires_on="2028-01-01T00:00:00Z")
        assert gear["status"] == "IN_STOCK"

        issued = issue_gear(gear["id"], player["id"])
        assert issued["status"] == "ISSUED"

        returned = validate_success(api.return_gear_item(gear["id"], EM))
        assert returned["status"] == "IN_STOCK"
        assert returned["current_holder_id"] is None

        job = create_reconditioning_job(gear["id"], provider_name="RCOA",
                                        sent_on="2026-08-01")
        assert_reconditioning_job(job)
        assert job["status"] == "OUT"
        assert job["due_back_on"] == "2026-09-15", (
            "sent_on 2026-08-01 plus exactly 45 days")
        assert get_gear(gear["id"])["status"] == "OUT_FOR_RECONDITIONING"

        passed = validate_success(api.record_reconditioning_result(
            job["id"], {"outcome": "PASSED", "result_grade": "B"}, EM))
        assert passed["status"] == "PASSED"
        assert passed["result_recorded_on"] == "2026-08-01", (
            "The result date is stamped from the logical clock")
        assert passed["certification_valid_until"] == "2027-08-01", (
            "The result date plus 365 days")

        cycled = get_gear(gear["id"])
        assert_gear_item(cycled)
        assert cycled["status"] == "IN_STOCK", (
            "The item completes the cycle back into circulation")
        assert cycled["condition_grade"] == "B", (
            "The pass rewrites the condition grade to the result grade")
        assert cycled["certification_expires_on"] == "2027-08-01T00:00:00Z", (
            "The validity date mapped to a timestamp at midnight UTC")
        assert cycled["current_holder_id"] is None

    def test_job_record_result_after_passed_rejected(self, api):
        """PRD §3.5: "Recording a result closes the loop and is valid only
        while the job is `OUT` (`ERR_JOB_NOT_OPEN`)."

        Design: Corner/state_machines/job_record_result_after_passed_rejected
        """
        gear = create_gear(asset_tag="HLM-902")
        job = create_reconditioning_job(gear["id"], provider_name="RCOA",
                                        sent_on="2026-08-01")
        passed = validate_success(api.record_reconditioning_result(
            job["id"], {"outcome": "PASSED", "result_grade": "A"}, EM))
        assert passed["status"] == "PASSED"

        resp = api.record_reconditioning_result(
            job["id"], {"outcome": "PASSED", "result_grade": "A"}, EM)
        validate_error(resp, ApiErrorId.ERR_JOB_NOT_OPEN)
        assert get_job(job["id"])["status"] == "PASSED", (
            "A terminal job cannot be recorded against again")

    def test_provider_concurrent_job_capacity_enforced(self, api):
        """PRD §3.5: "Two jobs for the same provider overlap when the new
        job's send date falls before the existing job's due-back date and the
        existing job's send date falls before the new job's due-back date; a
        provider may sustain at most two overlapping open jobs, so creation is
        rejected with `ERR_VENDOR_CAPACITY_EXCEEDED` when two open jobs for
        that `provider_name` already overlap the new window."
        PRD §3.5: "Each open job occupies a half-open window covering the send
        date up to but not including its `due_back_on`, which is exactly 45
        days after `sent_on`."

        Design: Difficulty/resource_temporal_overlap/provider_concurrent_job_capacity_enforced
        """
        g1 = create_gear(asset_tag="HLM-501")
        g2 = create_gear(asset_tag="HLM-502")
        g3 = create_gear(asset_tag="HLM-503", size_spec="HELMET-M")

        j1 = create_reconditioning_job(g1["id"], provider_name="RCOA",
                                       sent_on="2026-01-05")
        j2 = create_reconditioning_job(g2["id"], provider_name="RCOA",
                                       sent_on="2026-01-10")
        assert j1["due_back_on"] == "2026-02-19"
        assert j2["due_back_on"] == "2026-02-24"

        resp = api.create_reconditioning_job(
            {"item_id": g3["id"], "provider_name": "RCOA",
             "sent_on": "2026-01-15"},
            EM,
        )
        validate_error(resp, ApiErrorId.ERR_VENDOR_CAPACITY_EXCEEDED)
        assert get_gear(g3["id"])["status"] == "IN_STOCK", (
            "The rejected job leaves the item in stock — no partial side effect")

        other = validate_success(api.create_reconditioning_job(
            {"item_id": g3["id"], "provider_name": "OTHERCO",
             "sent_on": "2026-01-15"},
            EM,
        ), 201)
        assert other["status"] == "OUT", (
            "The same window is fine at a different provider")
        assert get_gear(g3["id"])["status"] == "OUT_FOR_RECONDITIONING"
