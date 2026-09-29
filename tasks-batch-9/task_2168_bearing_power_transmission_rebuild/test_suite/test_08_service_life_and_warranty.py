# -*- coding: utf-8 -*-
"""In-service tracking by asset and pro-rata warranty settlement."""
import pytest

from test_helpers import (
    ADMIN_1, FOUR_BANDS, ONE_BAND, PLANNER_1, ApiErrorId, adjudicate_claim,
    api_client as api, asset_version, claim_action, credit_notes, file_claim,
    install_unit, make_customer_headers, order_action, read_asset, read_claim,
    read_customer, read_inspection, read_installation, read_order,
    record_hours, remove_installation, set_clock, setup_claimed_installation,
    setup_delivered_pipeline, setup_failed_installation, setup_installed_unit,
    validate_error, validate_paginated, validate_success,
)


class TestWarrantyEligibility:

    def test_a_running_unit_cannot_be_claimed(self):
        """PRD 3.9: "A warranty claim is filed by the account or by a `ShopAdmin` against an
        `installation_id` with a `claimed_reason`. The installation must be
        `FAILED_IN_SERVICE`; a claim against a running or removed unit is
        `ERR_WARRANTY_NOT_ELIGIBLE` (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/warranty_claim_blocked_by_running_installation
        """
        world = setup_installed_unit(account_code="NGM-013", serial_no="SN-77013",
                                     bench_code="B-5", run_hours=100)
        validate_error(api.create_warranty_claim(
            {"installation_id": world["installation"]["id"],
             "claimed_reason": "noise complaint"},
            make_customer_headers(world["customer"]["id"])),
            ApiErrorId.ERR_WARRANTY_NOT_ELIGIBLE.value, 409)

    def test_the_refused_claim_writes_no_row_and_leaves_the_unit_running(self):
        """PRD 3.9: "Logging run hours supplies a `run_hours_delta` that must be strictly
        greater than zero; the delta is added to the installation's `run_hours`, and the first
        such log moves the record `INSTALLED → RUNNING`."
        PRD 3.9: "Reporting an in-service failure, which either a `ShopAdmin` or the account may
        do, moves the record to `FAILED_IN_SERVICE` from either `INSTALLED` or `RUNNING` and
        stamps `failed_at` from the logical clock."

        Design: Difficulty/cross_entity_state_dependency/warranty_claim_blocked_by_running_installation
        """
        world = setup_installed_unit(account_code="NGM-013", serial_no="SN-77013",
                                     bench_code="B-5", run_hours=100)
        validate_error(api.create_warranty_claim(
            {"installation_id": world["installation"]["id"],
             "claimed_reason": "noise complaint"},
            make_customer_headers(world["customer"]["id"])),
            ApiErrorId.ERR_WARRANTY_NOT_ELIGIBLE.value, 409)

        installation = read_installation(world["installation"]["id"])
        assert installation["status"] == "RUNNING"
        assert installation["run_hours"] == 100
        assert installation["failed_at"] is None

        _, meta = validate_paginated(api.list_installation_warranty_claims(
            world["installation"]["id"], ADMIN_1))
        assert meta["total_count"] == 0


class TestChangeoverBuffer:

    def _removed_then_free_asset(self):
        world = setup_delivered_pipeline(account_code="NGM-015", serial_no="SN-77015",
                                         bench_code="B-7")
        set_clock("2026-08-10T00:00:00Z")
        world["inst_1"] = install_unit(world["core"]["id"], world["asset"]["id"],
                                       world["order"]["id"])
        set_clock("2026-08-12T00:00:00Z")
        world["inst_1"] = remove_installation(world["inst_1"]["id"])
        return world

    def test_one_second_short_of_the_buffer_is_an_install_buffer_violation(self):
        """PRD 3.9: "First the **changeover buffer**: gather the asset's installations whose
        `status` is `REMOVED_PLANNED` or `FAILED_IN_SERVICE`, and if there are any, take the
        latest of their off-service instants — a planned removal's `removed_at` or a failure's
        `failed_at`, whichever that record carries — with ties broken by the greater
        `created_at`."
        PRD 3.9: "The new installation's moment, taken from the logical clock, must be at least
        24 hours after that instant; the edge is inclusive, so exactly 24 hours later is
        admissible while anything earlier is `ERR_INSTALL_BUFFER_VIOLATION` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/asset_changeover_buffer_inclusive_at_exactly_twenty_four_hours
        """
        world = self._removed_then_free_asset()
        assert world["inst_1"]["status"] == "REMOVED_PLANNED"
        assert world["inst_1"]["removed_at"] == "2026-08-12T00:00:00.000Z"

        set_clock("2026-08-12T23:59:59Z")
        version_before = asset_version(world["asset"]["id"])
        validate_error(api.create_installation({
            "core_unit_id": world["core"]["id"],
            "customer_asset_id": world["asset"]["id"],
            "rebuild_order_id": world["order"]["id"],
            "expected_asset_version": version_before}, ADMIN_1),
            ApiErrorId.ERR_INSTALL_BUFFER_VIOLATION.value, 409)

        assert asset_version(world["asset"]["id"]) == version_before, (
            "the rejected attempt never advanced the asset"
        )

    def test_exactly_twenty_four_hours_after_the_removal_is_admissible(self):
        """PRD 3.9: "The new installation's moment, taken from the logical clock, must be at
        least 24 hours after that instant; the edge is inclusive, so exactly 24 hours later is
        admissible while anything earlier is `ERR_INSTALL_BUFFER_VIOLATION` (HTTP 409)."
        PRD 3.9: "A successful installation stamps `in_service_start_at` from the logical clock,
        sets `status` to `INSTALLED` and `run_hours` to 0, leaves `removed_at` and `failed_at`
        null, and copies three snapshots that freeze the warranty terms at that instant:
        `warranty_hours_snapshot` and `warranty_months_snapshot` from the core's governing spec,
        and `covered_base_cents_snapshot` from the producing order's `covered_base_cents`."

        Design: Difficulty/resource_temporal_overlap/asset_changeover_buffer_inclusive_at_exactly_twenty_four_hours
        """
        world = self._removed_then_free_asset()
        set_clock("2026-08-12T23:59:59Z")
        stale_version = asset_version(world["asset"]["id"])
        validate_error(api.create_installation({
            "core_unit_id": world["core"]["id"],
            "customer_asset_id": world["asset"]["id"],
            "rebuild_order_id": world["order"]["id"],
            "expected_asset_version": stale_version}, ADMIN_1),
            ApiErrorId.ERR_INSTALL_BUFFER_VIOLATION.value, 409)

        set_clock("2026-08-13T00:00:00Z")
        version_now = asset_version(world["asset"]["id"])
        assert version_now == stale_version
        second = validate_success(api.create_installation({
            "core_unit_id": world["core"]["id"],
            "customer_asset_id": world["asset"]["id"],
            "rebuild_order_id": world["order"]["id"],
            "expected_asset_version": version_now}, ADMIN_1), 201)

        assert second["in_service_start_at"] == "2026-08-13T00:00:00.000Z"
        assert second["status"] == "INSTALLED"
        assert second["run_hours"] == 0

        _, meta = validate_paginated(api.list_installations(
            ADMIN_1, params={"customer_asset_id": world["asset"]["id"]}))
        assert meta["total_count"] == 2

    def test_the_buffer_check_pre_empts_the_asset_occupancy_check(self):
        """PRD 3.9: "Only then is **occupancy** examined: if the asset already carries an
        installation whose `status` is `INSTALLED` or `RUNNING`, the attempt is
        `ERR_ASSET_OCCUPIED` (HTTP 409). Because the buffer test runs first, an asset that both
        still carries a live unit and lies inside the changeover window reports the buffer
        violation, not the occupancy one."

        Design: Corner/validations/install_buffer_temporal_error_beats_asset_occupied_constraint
        """
        world = setup_delivered_pipeline(account_code="BUF-001", serial_no="SN-BUF-1",
                                         bench_code="B-BUF")
        core_id, asset_id, order_id = (world["core"]["id"], world["asset"]["id"],
                                       world["order"]["id"])
        set_clock("2026-08-10T00:00:00Z")
        inst_1 = install_unit(core_id, asset_id, order_id)

        validate_error(api.create_installation({
            "core_unit_id": core_id, "customer_asset_id": asset_id,
            "rebuild_order_id": order_id,
            "expected_asset_version": asset_version(asset_id)}, ADMIN_1),
            ApiErrorId.ERR_ASSET_OCCUPIED.value, 409)

        set_clock("2026-08-12T00:00:00Z")
        removed = remove_installation(inst_1["id"])
        assert removed["status"] == "REMOVED_PLANNED"
        assert removed["removed_at"] == "2026-08-12T00:00:00.000Z"

        set_clock("2026-08-13T00:00:00Z")
        inst_2 = install_unit(core_id, asset_id, order_id)
        assert inst_2["in_service_start_at"] == "2026-08-13T00:00:00.000Z"
        assert inst_2["status"] == "INSTALLED"

        set_clock("2026-08-12T06:00:00Z")
        error = validate_error(api.create_installation({
            "core_unit_id": core_id, "customer_asset_id": asset_id,
            "rebuild_order_id": order_id,
            "expected_asset_version": asset_version(asset_id)}, ADMIN_1),
            ApiErrorId.ERR_INSTALL_BUFFER_VIOLATION.value, 409)
        assert error["error_id"] != ApiErrorId.ERR_ASSET_OCCUPIED.value

        _, meta = validate_paginated(api.list_installations(
            ADMIN_1, params={"customer_asset_id": asset_id}))
        assert meta["total_count"] == 2


class TestProRataBasis:

    def _canonical_claim(self):
        return setup_claimed_installation(
            account_code="NGM-002", serial_no="SN-77002", bench_code="B-1",
            feature_bands=FOUR_BANDS,
            measurements=(("BORE", 85), ("JOURNAL", 58),
                          ("HOUSING_FIT", 44), ("END_PLAY", 160)),
            install_at="2026-08-05T00:00:00Z", run_hours=5200,
            fail_at="2027-02-01T00:00:00Z",
            claimed_reason="outer race spall at 5200 hours")

    def test_the_frozen_working_reports_both_consumed_fractions(self):
        """PRD 3.9: "The `elapsed_days` figure is the whole number of days between the
        installation's `in_service_start_at` and its `failed_at`, truncated downward from the
        elapsed seconds."
        PRD 3.9: "The `hours_consumed_fraction` is the installation's `run_hours` divided by its
        `warranty_hours_snapshot`, capped at 1, rounded half up to six decimal places."
        PRD 3.9: "The `calendar_consumed_fraction` is `elapsed_days` divided by the product of
        `warranty_months_snapshot` and 30 — a warranty month is exactly thirty days for this
        purpose — likewise capped at 1 and rounded half up to six decimal places."

        Design: Difficulty/dual_variant_calc/warranty_hours_basis_overrides_calendar_basis_on_same_claim
        """
        world = self._canonical_claim()
        installation = read_installation(world["installation"]["id"])
        assert installation["covered_base_cents_snapshot"] == 171250

        claim = read_claim(world["claim"]["id"])
        assert claim["elapsed_days"] == 180
        assert claim["hours_consumed_fraction"] == pytest.approx(0.650000, abs=1e-9)
        assert claim["calendar_consumed_fraction"] == pytest.approx(0.333333, abs=1e-9)

    def test_the_basis_that_consumed_more_warranty_governs_the_credit(self):
        """PRD 3.9: "Otherwise the basis that consumed *more* warranty governs, so that the
        customer is never credited on the more generous clock: `governing_basis` is `HOURS` when
        `hours_consumed_fraction` is greater than or equal to `calendar_consumed_fraction` —
        ties go to hours — and `CALENDAR` when the calendar fraction is strictly the greater. In
        that case `remaining_fraction` is 1 less the greater of the two fractions, rounded half
        up to six decimal places."
        PRD 3.9: "Finally `pro_rata_credit_cents` is `covered_base_cents_snapshot` multiplied by
        `remaining_fraction`, rounded half up to whole cents."

        Design: Difficulty/dual_variant_calc/warranty_hours_basis_overrides_calendar_basis_on_same_claim
        """
        world = self._canonical_claim()
        claim = read_claim(world["claim"]["id"])
        assert claim["governing_basis"] == "HOURS"
        assert claim["remaining_fraction"] == pytest.approx(0.350000, abs=1e-9)
        assert claim["pro_rata_credit_cents"] == 59938
        assert claim["pro_rata_credit_cents"] != 114167, (
            "114167 is the calendar-basis answer on the same data"
        )

    def test_a_workmanship_cause_forces_the_goodwill_basis_and_pays_in_full(self):
        """PRD 3.9: "If the accepted inspection of the claim's rebuild order coded a
        `failure_cause_code` of `WORKMANSHIP`, the shop accepts that it built the unit badly:
        `governing_basis` is `GOODWILL` and `remaining_fraction` is forced to exactly 1, so the
        entire covered base is credited regardless of how much of the warranty was consumed."
        PRD 3.9: "Issuing the credit is the final hop and is `ShopAdmin`-only, available from
        `APPROVED`. The claim moves to `CREDITED`; caused by that, a note is created with `kind`
        of `WARRANTY_PRORATA`, `status` of `POSTED`, an `amount_cents` equal to the claim's
        `pro_rata_credit_cents`, `warranty_claim_id` pointing at this claim"
        PRD 3.5: "First: if the inspection carries a `cause_code_override`, that value becomes
        the code and the confidence is `ASSERTED`."

        Design: Corner/calculations/warranty_goodwill_variant_pays_the_whole_covered_base_and_posts_a_credit
        """
        world = setup_claimed_installation(
            account_code="GDW-001", serial_no="SN-GDW-1", bench_code="B-GDW",
            inspection_overrides={"cause_code_override": "WORKMANSHIP",
                                  "inspector_note": "prior rebuild left the outer race proud"},
            install_at="2026-08-05T00:00:00Z", run_hours=5200,
            fail_at="2027-02-01T00:00:00Z",
            claimed_reason="same failure mode as the last rebuild")
        claim_id, cust_id = world["claim"]["id"], world["customer"]["id"]

        insp = read_inspection(world["inspection"]["id"])
        assert insp["failure_cause_code"] == "WORKMANSHIP"
        assert insp["cause_confidence"] == "ASSERTED"

        claim = read_claim(claim_id)
        assert claim["governing_basis"] == "GOODWILL"
        assert claim["hours_consumed_fraction"] == pytest.approx(0.650000, abs=1e-9)
        assert claim["remaining_fraction"] == pytest.approx(1.000000, abs=1e-9)
        assert claim["pro_rata_credit_cents"] == 171250

        claim_action(claim_id, "REVIEW")
        claim_action(claim_id, "REQUEST_INFO", info_note="send the oil analysis report")
        resubmitted = claim_action(claim_id, "RESUBMIT",
                                   headers=make_customer_headers(cust_id),
                                   info_note="oil analysis attached")
        assert resubmitted["status"] == "UNDER_REVIEW"
        assert resubmitted["info_note"] == "oil analysis attached"

        approved = adjudicate_claim(claim_id, "APPROVE", user_id="admin-1",
                                    adjudication_note="shop workmanship")
        assert approved["status"] == "APPROVED"

        credited = claim_action(claim_id, "ISSUE_CREDIT")
        assert credited["status"] == "CREDITED"

        rows, meta = credit_notes(warranty_claim_id=claim_id)
        assert meta["total_count"] == 1
        assert rows[0]["kind"] == "WARRANTY_PRORATA"
        assert rows[0]["amount_cents"] == 171250
        assert rows[0]["status"] == "POSTED"

        customer = read_customer(cust_id)
        assert customer["warranty_credit_balance_cents"] == 171250
        assert customer["core_credit_balance_cents"] == 82800
        assert customer["total_credit_balance_cents"] == 254050
        assert read_installation(world["installation"]["id"])["covered_base_cents_snapshot"] == 171250


class TestDeliveryAndDuplicateClaims:

    def test_an_undelivered_unit_cannot_be_installed_and_a_claim_cannot_be_filed_twice(self):
        """PRD 3.9: "The unit must genuinely be finished and matched: the core's `status` must
        be `SHIPPED`, the order's `work_status` must be `DELIVERED`, and the order's own core
        and asset references must agree with the body's, failing any of which the attempt is
        `ERR_UNIT_NOT_DELIVERED` (HTTP 409); a scrapped core is separately rejected with
        `ERR_CORE_SCRAPPED`."
        PRD 3.9: "And an installation may carry only one open claim at a time: if a sibling
        claim on the same installation is in `SUBMITTED`, `UNDER_REVIEW`, `INFO_REQUESTED` or
        `APPROVED`, the new filing is `ERR_DUPLICATE_CLAIM` (HTTP 409)."

        Design: Corner/errors/undelivered_unit_and_duplicate_claim_are_rejected
        """
        world = setup_delivered_pipeline(account_code="DLV-001", serial_no="SN-DLV-1",
                                         bench_code="B-DLV", stop_at="COMPLETED")
        core_id, asset_id, order_id = (world["core"]["id"], world["asset"]["id"],
                                       world["order"]["id"])
        cust_id = world["customer"]["id"]
        set_clock("2026-08-05T00:00:00Z")

        validate_error(api.create_installation({
            "core_unit_id": core_id, "customer_asset_id": asset_id,
            "rebuild_order_id": order_id,
            "expected_asset_version": asset_version(asset_id)}, ADMIN_1),
            ApiErrorId.ERR_UNIT_NOT_DELIVERED.value, 409)

        order_action(order_id, "DELIVER")
        installation = install_unit(core_id, asset_id, order_id)
        assert installation["in_service_start_at"] == "2026-08-05T00:00:00.000Z"

        record_hours(installation["id"], 1200)
        set_clock("2026-10-01T00:00:00Z")
        validate_success(api.advance_installation(installation["id"],
                                                  {"action": "FAIL"}, ADMIN_1))

        claim = file_claim(installation["id"], cust_id,
                           claimed_reason="seized after 1200 hours")
        assert claim["elapsed_days"] == 57
        assert claim["hours_consumed_fraction"] == pytest.approx(0.150000, abs=1e-9)
        assert claim["calendar_consumed_fraction"] == pytest.approx(0.105556, abs=1e-9)
        assert claim["governing_basis"] == "HOURS"
        assert claim["remaining_fraction"] == pytest.approx(0.850000, abs=1e-9)
        assert claim["pro_rata_credit_cents"] == 145563

        validate_error(api.create_warranty_claim(
            {"installation_id": installation["id"],
             "claimed_reason": "filed twice by mistake"},
            make_customer_headers(cust_id)),
            ApiErrorId.ERR_DUPLICATE_CLAIM.value, 409)

        _, meta = validate_paginated(
            api.list_installation_warranty_claims(installation["id"], ADMIN_1))
        assert meta["total_count"] == 1

    def test_a_unit_that_has_run_its_whole_warranty_is_expired(self):
        """PRD 3.9: "Neither warranty clock may have run out: the installation's `run_hours`
        must be strictly less than its `warranty_hours_snapshot` **and** the elapsed whole days
        must be strictly less than `warranty_months_snapshot` multiplied by 30, both edges being
        exclusive — so exactly 8,000 hours against an 8,000-hour warranty is expired, and the
        claim is `ERR_WARRANTY_EXPIRED` (HTTP 422)."

        Design: Corner/errors/warranty_claim_after_the_hour_clock_expires_is_rejected
        """
        world = setup_failed_installation(
            account_code="EXP-001", serial_no="SN-EXP-1", bench_code="B-EXP",
            standard_overrides={"model_code": "SHORT-WARRANTY-1", "warranty_hours": 4000},
            install_at="2026-08-05T00:00:00Z", run_hours=4000,
            fail_at="2026-10-01T00:00:00Z")
        installation = read_installation(world["installation"]["id"])
        assert installation["run_hours"] == 4000
        assert installation["warranty_hours_snapshot"] == 4000

        validate_error(api.create_warranty_claim(
            {"installation_id": installation["id"],
             "claimed_reason": "failed right at the hour limit"},
            make_customer_headers(world["customer"]["id"])),
            ApiErrorId.ERR_WARRANTY_EXPIRED.value, 422)

        _, meta = validate_paginated(
            api.list_installation_warranty_claims(installation["id"], ADMIN_1))
        assert meta["total_count"] == 0


class TestTerminalLockdown:

    def test_a_failed_installation_and_an_unreviewed_claim_reject_further_actions(self):
        """PRD 3.9: "Both of those are terminal, and every action attempted against a terminal
        installation — or against a state that does not admit it — is
        `ERR_INSTALLATION_INVALID_STATE` (HTTP 409)."
        PRD 3.9: "Adjudication is `ShopAdmin`-only, available only from `UNDER_REVIEW`, and
        carries a `decision` of `APPROVE` or `DENY` plus an optional `adjudication_note`; the
        caller is recorded as `adjudicated_by_user_id`."
        PRD 3.9: "Any action attempted from a state that does not admit it is
        `ERR_CLAIM_INVALID_STATE` (HTTP 409)."

        Design: Corner/state_machines/terminal_installation_and_unreviewed_claim_reject_further_actions
        """
        world = setup_claimed_installation(
            account_code="TRM-001", serial_no="SN-TRM-1", bench_code="B-TRM",
            install_at="2026-08-05T00:00:00Z", run_hours=1200,
            fail_at="2026-10-01T00:00:00Z", claimed_reason="seized bearing")
        inst_id, claim_id = world["installation"]["id"], world["claim"]["id"]

        validate_error(api.advance_installation(
            inst_id, {"action": "RECORD_HOURS", "run_hours_delta": 100}, ADMIN_1),
            ApiErrorId.ERR_INSTALLATION_INVALID_STATE.value, 409)
        installation = read_installation(inst_id)
        assert installation["run_hours"] == 1200
        assert installation["status"] == "FAILED_IN_SERVICE"

        error = validate_error(api.adjudicate_warranty_claim(
            claim_id, {"decision": "DENY", "adjudication_note": "too early to decide"},
            ADMIN_1), ApiErrorId.ERR_CLAIM_INVALID_STATE.value, 409)
        assert error["error_id"] != ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value

        claim = read_claim(claim_id)
        assert claim["status"] == "SUBMITTED"
        assert claim["adjudicated_by_user_id"] is None

        _, meta = validate_paginated(api.list_installations(
            ADMIN_1, params={"customer_asset_id": world["asset"]["id"],
                             "status": "FAILED_IN_SERVICE"}))
        assert meta["total_count"] == 1
        _, meta = validate_paginated(
            api.list_installation_warranty_claims(inst_id, ADMIN_1))
        assert meta["total_count"] == 1
