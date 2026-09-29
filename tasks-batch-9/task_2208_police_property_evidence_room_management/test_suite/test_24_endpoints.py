"""Endpoint behaviour: round-trip reads, action endpoints, derived reads and the sweep."""

from test_helpers import (
    ApiErrorId,
    adjudicate_case,
    assert_custodian,
    assert_property_room,
    authorize_order,
    charge_case,
    custodian_payload,
    disposition_order_payload,
    execute_order,
    execute_payload,
    issue_notice,
    log_and_store_item,
    read_case,
    read_item,
    release_transfer,
    request_transfer,
    run_sweep,
    set_clock,
    setup_corner_base,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestCustodianCreateAndRead:
    """Registering a custodian and reading the row back, single and filtered."""

    def test_custodian_create_then_read_and_filtered_list_agree(self, api):
        """A registered custodian is echoed unchanged by its read and by the filter.

        PRD 4: "Operations that bring a new resource into existence — registering a
        room, statute, location or custodian, opening a case, logging an evidence item,
        recording a retention determination, requesting a custody transfer, opening a
        disposition order, issuing an owner notice, or scheduling an audit session —
        return `201 Created`."
        PRD 3.1: "A `Custodian` belongs to a room through `property_room_id`, is
        identified by a `badge_number` of 1 to 16 characters that must be unique within
        that room (`ERR_DUPLICATE_BADGE_NUMBER` otherwise), prints `full_name` on chain
        of custody documents, holds a functional `role_type` of `EVIDENCE_TECH`,
        `INVESTIGATOR`, `LAB_ANALYST` or `AUDITOR`, and carries
        `certification_expires_at`."
        PRD 3.1: "New custodians begin `ACTIVE` with `suspension_reason` null and
        `open_escort_count` at 0; that counter is the number of custody transfers naming
        this custodian as receiver whose `status` is `REQUESTED`, `RELEASED` or
        `OVERDUE`."
        PRD 2.4: "Custodians may be filtered by `property_room_id`, `role_type` and
        `status`."

        Design: Corner/endpoints/custodian_create_then_read_round_trip
        """
        env = setup_corner_base()

        created = validate_success(
            api.create_custodian(
                custodian_payload(
                    env["room_id"],
                    badge_number="T-500",
                    full_name="Nia Fowler",
                    role_type="EVIDENCE_TECH",
                    certification_expires_at="2028-01-01T00:00:00Z",
                ),
                env["manager"],
            ),
            201,
        )
        assert_custodian(created)
        assert created["status"] == "ACTIVE"
        assert created["suspension_reason"] is None
        assert created["open_escort_count"] == 0

        read = validate_success(api.get_custodian(created["id"], env["manager"]), 200)
        assert read["id"] == created["id"]
        assert read["property_room_id"] == env["room_id"]
        assert read["badge_number"] == "T-500"
        assert read["full_name"] == "Nia Fowler"
        assert read["role_type"] == "EVIDENCE_TECH"
        assert read["certification_expires_at"] == "2028-01-01T00:00:00.000Z"
        assert read["status"] == "ACTIVE"
        assert read["suspension_reason"] is None
        assert read["open_escort_count"] == 0

        technicians, tech_meta = validate_paginated(
            api.list_custodians(
                env["manager"],
                params={"property_room_id": env["room_id"], "role_type": "EVIDENCE_TECH"},
            )
        )
        # The base roster holds T-100 and T-101, plus the T-500 registered above.
        assert tech_meta["total_count"] == 3
        assert created["id"] in [row["id"] for row in technicians]
        assert all(row["role_type"] == "EVIDENCE_TECH" for row in technicians)

        auditors, auditor_meta = validate_paginated(
            api.list_custodians(
                env["manager"],
                params={"property_room_id": env["room_id"], "role_type": "AUDITOR"},
            )
        )
        # The filter is applied rather than ignored: the new technician is excluded.
        assert auditor_meta["total_count"] == 1
        assert [row["id"] for row in auditors] == [env["aud_id"]]


class TestCaseChargeAction:
    """Recording that charges were filed, and what the second attempt does."""

    def test_case_charge_action_sets_charged_at(self, api):
        """Charging an open case stamps the logical clock and is not repeatable.

        PRD 3.4: "An `Investigator` (or a `PropertyRoomManager`) records that charges
        were filed, moving the case from `OPEN` to `CHARGED` and stamping `charged_at`
        from the logical clock."
        PRD 3.1: "A case opens in `OPEN` with `charged_at`, `adjudicated_at`,
        `appeal_opened_at` and `closed_at` all null and both `item_count` and
        `undisposed_item_count` at 0."
        PRD 2.5: "All temporal reasoning in this service — retention arithmetic, claim
        deadlines, custody window overlap, certification expiry, settlement windows and
        the nightly sweep — reads a single server-side logical clock, never the host's
        wall clock."
        PRD 2.4: "Property rooms, offense statutes, storage locations, custodians,
        cases, evidence items, retention determinations, custody transfers, disposition
        orders, owner claims, audit sessions and discrepancies additionally carry
        `updated_at`, refreshed on every mutation, and `version`, an integer that
        increments by one on every mutation — including mutations that only touch
        derived counters."
        PRD 2.10: "The target resource is in a state that permits the requested
        transition, and neither the source nor the destination storage location is
        sealed — `ERR_ITEM_CUSTODY_STATE_INVALID`, `ERR_ITEM_DISPOSITION_STATE_INVALID`,
        `ERR_CASE_STATE_INVALID`, `ERR_TRANSFER_STATE_INVALID`,
        `ERR_ORDER_STATE_INVALID`, `ERR_CLAIM_STATE_INVALID`, `ERR_AUDIT_STATE_INVALID`,
        `ERR_DISCREPANCY_STATE_INVALID` or `ERR_LOCATION_SEALED` (all 409)."
        PRD 4: "Every other operation, including all reads, all state transitions on an
        existing resource, the nightly sweep and the clock capability, returns
        `200 OK`."

        Design: Corner/endpoints/case_charge_action_sets_charged_at
        """
        env = setup_corner_base()
        before = read_case(env, env["case1_id"])
        assert before["status"] == "OPEN"
        assert before["charged_at"] is None
        set_clock("2026-08-04T14:00:00Z")

        charged = validate_success(
            api.charge_case(env["case1_id"], env["inv_headers"]), 200
        )

        assert charged["status"] == "CHARGED"
        assert charged["charged_at"] == "2026-08-04T14:00:00.000Z"
        assert charged["adjudicated_at"] is None
        assert charged["appeal_opened_at"] is None
        assert charged["closed_at"] is None
        assert charged["version"] == before["version"] + 1

        repeat = api.charge_case(env["case1_id"], env["inv_headers"])
        validate_error(repeat, ApiErrorId.ERR_CASE_STATE_INVALID, 409)

        after = read_case(env, env["case1_id"])
        assert after["status"] == "CHARGED"
        assert after["charged_at"] == "2026-08-04T14:00:00.000Z"
        assert after["version"] == charged["version"]


class TestPropertyRoomDerivedRead:
    """The room read as a projection of live child state."""

    def test_property_room_read_exposes_derived_counters(self, api):
        """A clean room reads OPEN with every counter at 0 and no sweep stamp.

        PRD 3.1: "A newly registered room opens with `posture` of `OPEN`, with
        `open_discrepancy_count`, `missing_high_risk_count`, `sealed_location_count`,
        `disposal_eligible_count` and `escrow_balance_cents` all at 0, and with
        `last_sweep_at` null until the nightly sweep first runs."
        PRD 2.6: "Otherwise, if `open_discrepancy_count` is at least 1 or
        `sealed_location_count` is at least 1, the posture is `RESTRICTED`."
        PRD 2.6: "Otherwise it is `OPEN`."
        PRD 3.8: "**Step three** matures retention: every item whose `custody_state` is
        `STORED` and whose `retention_release_at` is non-null and at or before the
        current instant moves `RETAINED → DISPOSAL_ELIGIBLE`."
        PRD 3.8: "**Step four** re-derives every dependent figure on the room:
        `open_discrepancy_count`, `missing_high_risk_count`, `sealed_location_count`,
        `disposal_eligible_count`, `escrow_balance_cents` and `posture`, and finally
        stamps `last_sweep_at` with the current instant."

        Design: Corner/endpoints/property_room_read_exposes_derived_counters
        """
        env = setup_corner_base()
        item = log_and_store_item(
            env,
            case_id=env["case1_id"],
            location_id=env["loc_g_id"],
            item_description="Stored evidence",
            category="GENERAL",
            packaging_type="PAPER_BAG",
            appraised_value_cents=1000,
            seized_at="2026-07-31T12:00:00Z",
        )

        room = validate_success(
            api.get_property_room(env["room_id"], env["aud_headers"]), 200
        )

        assert_property_room(room)
        assert room["name"] == "Central Property Unit"
        assert room["agency_code"] == "CPD"
        assert room["posture"] == "OPEN"
        assert room["open_discrepancy_count"] == 0
        assert room["missing_high_risk_count"] == 0
        assert room["sealed_location_count"] == 0
        assert room["disposal_eligible_count"] == 0
        assert room["escrow_balance_cents"] == 0
        assert room["last_sweep_at"] is None

        # Statute TH-3 carries 365 statutory days from the 2026-08-01 intake.
        set_clock("2027-08-01T00:00:00Z")
        run_sweep(env)

        after = validate_success(
            api.get_property_room(env["room_id"], env["aud_headers"]), 200
        )
        assert read_item(env, item["id"])["disposition_state"] == "DISPOSAL_ELIGIBLE"
        assert after["disposal_eligible_count"] == 1
        assert after["last_sweep_at"] == "2027-08-01T00:00:00.000Z"
        assert after["posture"] == "OPEN"
        assert after["open_discrepancy_count"] == 0
        assert after["escrow_balance_cents"] == 0


class TestAutomaticDispositionAuthorization:
    """Which destruction orders skip the courthouse, and which must wait for it."""

    def test_auto_authorized_destruction_order_skips_court_authorization(self, api):
        """A low-value GENERAL destruction self-authorizes; a firearm does not.

        PRD 3.7: "Automatic authorization applies only when all four of the following
        hold: the order's `type` is `DESTRUCTION`; the case's statute has
        `destruction_requires_court_order` set to false; the item's `category` is none
        of `FIREARM`, `CURRENCY`, `NARCOTICS` or `BIOLOGICAL`; and the item's
        `appraised_value_cents` is strictly below 500000 cents, so that an item
        appraised at exactly five thousand dollars still requires a judge."
        PRD 3.7: "When the predicate holds, the order transitions
        `PENDING_COURT_AUTH → AUTHORIZED` in the same request, `auto_authorized` is set
        to true, `authorized_at` is stamped from the logical clock, and
        `court_order_number` stays null."
        PRD 3.7: "When it does not hold, the order waits: a `CourtClerk` supplies a
        `court_order_number`, which moves the order `PENDING_COURT_AUTH → AUTHORIZED`,
        stamps `authorized_at`, and leaves `auto_authorized` false."
        PRD 3.7: "It requires the order to be `AUTHORIZED`, the room's `posture` to be
        neither `RESTRICTED` nor `LOCKED_DOWN`, the item's `custody_state` to be
        `STORED`, the segregation-of-duties inequalities of §2.11 to hold, both named
        custodians to be `ACTIVE` and certified, and — for a `RETURN_TO_OWNER` order —
        the referenced owner claim to be in `VERIFIED`, failing which the request is
        refused with `ERR_CLAIM_NOT_VERIFIED`."
        PRD 3.7: "Non-auction dispositions have nothing to sell, so execution settles
        them immediately: an order whose `type` is `RETURN_TO_OWNER`, `DESTRUCTION` or
        `CONVERSION` continues `EXECUTED → SETTLED` inside the same request with
        `settled_net_proceeds_cents` of 0, `settlement_status` of `NONE`, and
        `settled_at` stamped from the logical clock."

        Design: Corner/endpoints/auto_authorized_destruction_order_skips_court_authorization
        """
        env = setup_corner_base()
        plain_item = log_and_store_item(
            env,
            case_id=env["case2_id"],
            location_id=env["loc_g_id"],
            item_description="Broken bicycle",
            category="GENERAL",
            packaging_type="CHAIN_TAG_ONLY",
            appraised_value_cents=40000,
            seized_at="2026-07-30T09:00:00Z",
        )
        gun_item = log_and_store_item(
            env,
            case_id=env["case2_id"],
            location_id=env["loc_v_id"],
            item_description="Surrendered revolver",
            category="FIREARM",
            packaging_type="RIGID_BOX",
            appraised_value_cents=45000,
            seized_at="2026-07-30T09:00:00Z",
        )
        charge_case(env, env["case2_id"])
        # Statute AB-1 carries 0 statutory and 0 appeal days, so the FINAL variant
        # falls back on the floor of intake plus 90 days, that is 2026-10-30.
        set_clock("2026-10-30T00:00:00Z")
        adjudicate_case(env, env["case2_id"])
        assert read_item(env, plain_item["id"])["disposition_state"] == "DISPOSAL_ELIGIBLE"
        assert read_item(env, gun_item["id"])["disposition_state"] == "DISPOSAL_ELIGIBLE"

        auto_order = validate_success(
            api.create_disposition_order(
                disposition_order_payload(plain_item["id"], "DESTRUCTION", env["tech_id"]),
                env["tech_headers"],
            ),
            201,
        )
        manual_order = validate_success(
            api.create_disposition_order(
                disposition_order_payload(gun_item["id"], "DESTRUCTION", env["tech_id"]),
                env["tech_headers"],
            ),
            201,
        )

        assert auto_order["auto_authorized"] is True
        assert auto_order["status"] == "AUTHORIZED"
        assert auto_order["authorized_at"] == "2026-10-30T00:00:00.000Z"
        assert auto_order["court_order_number"] is None
        # The FIREARM category disqualifies the second order regardless of its value.
        assert manual_order["auto_authorized"] is False
        assert manual_order["status"] == "PENDING_COURT_AUTH"
        assert manual_order["authorized_at"] is None
        assert manual_order["court_order_number"] is None

        premature = api.execute_order(
            manual_order["id"],
            execute_payload(env["tech2_id"], env["aud_id"]),
            env["manager"],
        )
        validate_error(premature, ApiErrorId.ERR_ORDER_STATE_INVALID, 409)

        authorized = authorize_order(env, manual_order["id"], "CO-2026-5150")
        assert authorized["status"] == "AUTHORIZED"
        assert authorized["auto_authorized"] is False
        assert authorized["court_order_number"] == "CO-2026-5150"

        executed = execute_order(env, manual_order["id"], env["tech2_id"], env["aud_id"])
        assert executed["status"] == "SETTLED"
        assert executed["settlement_status"] == "NONE"
        assert executed["settled_net_proceeds_cents"] == 0


class TestDailySweepStepOrder:
    """The nightly sweep's four steps, observed through the rows they touch."""

    def test_daily_sweep_processes_steps_in_declared_order(self, api):
        """Overdue escorts, then expired notices, then matured retention, then counters.

        PRD 3.8: "The nightly sweep is the room-level reconciliation, run by a
        `PropertyRoomManager`, and it executes four steps strictly in order, each
        processing candidate rows in ascending `created_at` order."
        PRD 3.8: "**Step one** flags overdue escorts: every custody transfer in
        `RELEASED` whose `due_back_at` is at or before the current instant becomes
        `OVERDUE`."
        PRD 3.8: "**Step two** expires owner notices: every claim in `NOTICE_SENT` whose
        `claim_deadline_at` is at or before the current instant becomes `EXPIRED` and
        moves its item `RETAINED → UNCLAIMED_ELIGIBLE`."
        PRD 3.8: "**Step three** matures retention: every item whose `custody_state` is
        `STORED` and whose `retention_release_at` is non-null and at or before the
        current instant moves `RETAINED → DISPOSAL_ELIGIBLE`."
        PRD 3.8: "Because step two runs before step three, an item whose notice expired
        on this very sweep becomes `UNCLAIMED_ELIGIBLE` rather than `DISPOSAL_ELIGIBLE`
        — the unclaimed pathway wins the tie."
        PRD 3.8: "**Step four** re-derives every dependent figure on the room:
        `open_discrepancy_count`, `missing_high_risk_count`, `sealed_location_count`,
        `disposal_eligible_count`, `escrow_balance_cents` and `posture`, and finally
        stamps `last_sweep_at` with the current instant."
        PRD 3.6: "The base period is 90 days when the item's `is_found_property` flag is
        true, and 30 days otherwise."
        PRD 3.6: "The deadline is `notified_at` plus the sum of the base period and the
        extension, added as whole days."
        PRD 3.6: "During the nightly sweep, a claim still in `NOTICE_SENT` whose
        `claim_deadline_at` is at or before the current instant moves to `EXPIRED`, and
        its item's disposition dimension moves `RETAINED → UNCLAIMED_ELIGIBLE`,
        incrementing the room's `disposal_eligible_count`."

        Design: Corner/endpoints/daily_sweep_processes_steps_in_declared_order
        """
        env = setup_corner_base()
        item_a = log_and_store_item(
            env,
            case_id=env["case1_id"],
            location_id=env["loc_g9_id"],
            item_description="Item A out at the laboratory",
            category="GENERAL",
            packaging_type="PAPER_BAG",
            appraised_value_cents=500,
            seized_at="2026-07-31T12:00:00Z",
        )
        transfer = request_transfer(
            env,
            item_a["id"],
            env["lab_id"],
            "LAB_ANALYSIS",
            "2026-08-02T09:00:00Z",
            "2026-08-12T09:00:00Z",
            headers=env["lab_headers"],
        )
        release_transfer(env, transfer["id"], "T.NG-2026-08-02")
        # Items B and C sit under statute AB-1, whose 0 statutory days put their
        # preliminary release instant at their 2026-08-01 intake.
        item_b = log_and_store_item(
            env,
            case_id=env["case2_id"],
            location_id=env["loc_g_id"],
            item_description="Item B with an owner notice",
            category="GENERAL",
            packaging_type="CHAIN_TAG_ONLY",
            appraised_value_cents=20000,
            seized_at="2026-07-30T09:00:00Z",
        )
        claim = issue_notice(
            env,
            item_b["id"],
            claimant_name="Unresponsive owner",
            claimant_contact="Counter notice served",
            notice_method="IN_PERSON",
        )
        item_c = log_and_store_item(
            env,
            case_id=env["case2_id"],
            location_id=env["loc_g_id"],
            item_description="Item C with no owner notice",
            category="GENERAL",
            packaging_type="CHAIN_TAG_ONLY",
            appraised_value_cents=20000,
            seized_at="2026-07-30T09:00:00Z",
        )
        # 30 seized-property days from the 2026-08-01 notice, no publication extension.
        assert claim["claim_deadline_at"] == "2026-08-31T00:00:00.000Z"
        set_clock("2026-09-05T00:00:00Z")

        swept = validate_success(api.daily_sweep(env["room_id"], env["manager"]), 200)

        transfer_after = validate_success(
            api.get_custody_transfer(transfer["id"], env["manager"]), 200
        )
        assert transfer_after["status"] == "OVERDUE"
        item_a_after = read_item(env, item_a["id"])
        assert item_a_after["custody_state"] == "CHECKED_OUT"
        # Step three only touches STORED items, so item A is skipped.
        assert item_a_after["disposition_state"] == "RETAINED"

        claim_after = validate_success(
            api.get_owner_claim(claim["id"], env["manager"]), 200
        )
        assert claim_after["status"] == "EXPIRED"
        # Item B's retention had also matured, so step two winning the tie is visible.
        assert read_item(env, item_b["id"])["disposition_state"] == "UNCLAIMED_ELIGIBLE"
        assert read_item(env, item_c["id"])["disposition_state"] == "DISPOSAL_ELIGIBLE"

        assert swept["disposal_eligible_count"] == 2
        assert swept["last_sweep_at"] == "2026-09-05T00:00:00.000Z"
        assert swept["posture"] == "OPEN"

        reswept = run_sweep(env)

        assert reswept["disposal_eligible_count"] == 2
        assert reswept["last_sweep_at"] == "2026-09-05T00:00:00.000Z"
        assert (
            validate_success(api.get_custody_transfer(transfer["id"], env["manager"]), 200)[
                "status"
            ]
            == "OVERDUE"
        )
        assert (
            validate_success(api.get_owner_claim(claim["id"], env["manager"]), 200)["status"]
            == "EXPIRED"
        )
