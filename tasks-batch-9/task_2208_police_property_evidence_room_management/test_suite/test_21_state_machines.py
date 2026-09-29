"""State machine coverage: initial states, valid and invalid transitions, terminal
states, preconditions and the cross-entity side effects a transition drives."""

from test_helpers import (
    adjudicate_case,
    assert_two_decimal_exactness,
    audit_session_payload,
    authorize_order,
    authorize_payload,
    charge_case,
    execute_order,
    log_and_store_item,
    open_order,
    read_case,
    read_item,
    read_location,
    read_room,
    reject_payload,
    release_payload,
    release_transfer,
    report_lost_payload,
    request_transfer,
    schedule_audit,
    set_clock,
    setup_corner_base,
    storage_assignment_payload,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestAuditSessionLifecycle:
    """Scheduling and starting an inventory audit of a single storage location."""

    def test_scheduled_session_opens_in_scheduled_with_every_counter_at_rest(self, api):
        """Scheduling mints a SCHEDULED session and bumps the bin's version without sealing it.

        PRD 3.8: "A session begins with `status` of `SCHEDULED`, a `risk_index` of 0.00,
        empty `expected_evidence_item_ids` and `scanned_evidence_item_ids`, zero
        `expected_item_count`, `scanned_item_count`, `missing_count` and
        `misplaced_count`, and null `started_at`, `reconciled_at` and `closed_at`."
        PRD 3.8: "Creating it also increments the target location's `version` by 1."
        PRD 3.1: "A new location starts with `occupied_slots` at 0, `status` of `OPEN` and
        `sealed_by_audit_session_id` null."
        PRD 2.6: "Otherwise, if `open_discrepancy_count` is at least 1 or
        `sealed_location_count` is at least 1, the posture is `RESTRICTED`. Otherwise it
        is `OPEN`."

        Design: Corner/state_machines/audit_session_starts_in_scheduled_state
        """
        env = setup_corner_base()

        session = validate_success(
            api.create_audit_session(
                audit_session_payload(
                    env["loc_g_id"],
                    env["aud_id"],
                    "2026-08-10T09:00:00Z",
                    "2026-08-10T17:00:00Z",
                    env["loc_g_version"],
                ),
                env["aud_headers"],
            ),
            201,
        )

        assert session["status"] == "SCHEDULED"
        assert_two_decimal_exactness(session["risk_index"])
        assert float(session["risk_index"]) == 0.00
        assert session["expected_evidence_item_ids"] == []
        assert session["scanned_evidence_item_ids"] == []
        assert session["expected_item_count"] == 0
        assert session["scanned_item_count"] == 0
        assert session["missing_count"] == 0
        assert session["misplaced_count"] == 0
        assert session["started_at"] is None
        assert session["reconciled_at"] is None
        assert session["closed_at"] is None

        # Scheduling does not seal the bin; only starting the session does.
        location = read_location(env, env["loc_g_id"])
        assert location["status"] == "OPEN"
        assert location["sealed_by_audit_session_id"] is None
        assert location["version"] == env["loc_g_version"] + 1

        room = read_room(env)
        assert room["sealed_location_count"] == 0
        assert room["posture"] == "OPEN"

    def test_start_seals_the_bin_and_snapshots_only_its_stored_items(self, api):
        """Starting seals the audited bin, snapshots its stored inventory and restricts the room.

        PRD 3.8: "Starting the session moves it `SCHEDULED → IN_PROGRESS`, stamps
        `started_at`, and snapshots the inventory the auditor is expected to find:
        `expected_evidence_item_ids` is the list of identifiers of the evidence items
        whose `storage_location_id` is that location and whose `custody_state` is
        `STORED`, ordered by `created_at` ascending, and `expected_item_count` is the
        length of that list."
        PRD 3.8: "The location itself moves `OPEN → SEALED_FOR_AUDIT`, records the session
        in `sealed_by_audit_session_id`, and has its `version` incremented by 1; the
        room's `sealed_location_count` is incremented and its `posture` recomputed, which
        takes a clean room from `OPEN` to `RESTRICTED` for the duration."

        Design: Corner/state_machines/audit_session_start_seals_location_and_snapshots_expected_items
        """
        env = setup_corner_base()
        item_a = log_and_store_item(
            env,
            case_id=env["case1_id"],
            location_id=env["loc_g_id"],
            item_description="Audited item A",
            category="GENERAL",
            packaging_type="PAPER_BAG",
            appraised_value_cents=1000,
            seized_at="2026-07-31T12:00:00Z",
        )
        item_b = log_and_store_item(
            env,
            case_id=env["case1_id"],
            location_id=env["loc_g_id"],
            item_description="Audited item B",
            category="GENERAL",
            packaging_type="PAPER_BAG",
            appraised_value_cents=2000,
            seized_at="2026-07-31T12:05:00Z",
        )
        item_c = log_and_store_item(
            env,
            case_id=env["case1_id"],
            location_id=env["loc_g9_id"],
            item_description="Elsewhere item C",
            category="GENERAL",
            packaging_type="PAPER_BAG",
            appraised_value_cents=3000,
            seized_at="2026-07-31T12:10:00Z",
        )
        audited = read_location(env, env["loc_g_id"])
        session = schedule_audit(
            env, env["loc_g_id"], audited["version"],
            "2026-08-10T09:00:00Z", "2026-08-10T17:00:00Z",
        )

        started = validate_success(
            api.start_audit_session(session["id"], env["aud_headers"]), 200
        )

        assert started["status"] == "IN_PROGRESS"
        assert started["started_at"] == "2026-08-01T00:00:00.000Z"
        assert started["expected_item_count"] == 2
        assert started["expected_evidence_item_ids"] == [item_a["id"], item_b["id"]]
        assert item_c["id"] not in started["expected_evidence_item_ids"]

        sealed = read_location(env, env["loc_g_id"])
        assert sealed["status"] == "SEALED_FOR_AUDIT"
        assert sealed["sealed_by_audit_session_id"] == session["id"]
        # Scheduling bumped the bin's version once (PRD 3.8) and starting bumps it again.
        assert sealed["version"] == audited["version"] + 2

        # The seal is scoped to the audited bin alone.
        untouched = read_location(env, env["loc_g9_id"])
        assert untouched["status"] == "OPEN"
        assert untouched["sealed_by_audit_session_id"] is None

        room = read_room(env)
        assert room["sealed_location_count"] == 1
        assert room["posture"] == "RESTRICTED"


class TestCustodyTransferTransitions:
    """Release drives the transfer and the item together, and only once."""

    def test_releasing_an_already_released_transfer_is_refused_not_repeated(self, api):
        """A second release is rejected on the transfer's own state and stores nothing.

        PRD 3.5: "Release further requires the room's `posture` to be neither
        `RESTRICTED` nor `LOCKED_DOWN`, the transfer to be in `REQUESTED`, the item to be
        in `STORED`, the item's storage location to be `OPEN` rather than sealed, and the
        receiving custodian to be `ACTIVE` with a `certification_expires_at` strictly
        after the current instant."
        PRD 2.10: "The target resource is in a state that permits the requested
        transition, and neither the source nor the destination storage location is sealed
        — `ERR_ITEM_CUSTODY_STATE_INVALID`, `ERR_ITEM_DISPOSITION_STATE_INVALID`,
        `ERR_CASE_STATE_INVALID`, `ERR_TRANSFER_STATE_INVALID`,
        `ERR_ORDER_STATE_INVALID`, `ERR_CLAIM_STATE_INVALID`, `ERR_AUDIT_STATE_INVALID`,
        `ERR_DISCREPANCY_STATE_INVALID` or `ERR_LOCATION_SEALED` (all 409)."
        PRD 3.5: "On success the acting technician's identity is written to
        `from_custodian_id`, both captured signatures are stored, the item's
        `current_holder_id` is set to the transfer's `to_custodian_id`, and a chain entry
        with `event_type` of `RELEASE` is appended carrying the `released_signature` in
        its `signature_ref`."

        Design: Corner/state_machines/custody_transfer_release_twice_rejected
        """
        env = setup_corner_base()
        item = log_and_store_item(
            env,
            case_id=env["case1_id"],
            location_id=env["loc_g_id"],
            item_description="Latent print card",
            category="GENERAL",
            packaging_type="PAPER_BAG",
            appraised_value_cents=100,
            seized_at="2026-07-31T12:00:00Z",
        )
        transfer = request_transfer(
            env, item["id"], env["lab_id"], "LAB_ANALYSIS",
            "2026-08-02T09:00:00Z", "2026-08-10T09:00:00Z",
            headers=env["lab_headers"],
        )
        release_transfer(env, transfer["id"], "sig-release-1")

        validate_error(
            api.release_transfer(
                transfer["id"], release_payload("sig-release-2"), env["tech_headers"]
            ),
            "ERR_TRANSFER_STATE_INVALID",
            409,
        )

        after = validate_success(
            api.get_custody_transfer(transfer["id"], env["manager"]), 200
        )
        assert after["status"] == "RELEASED"
        assert after["released_signature"] == "sig-release-1"

        held = read_item(env, item["id"])
        assert held["custody_state"] == "CHECKED_OUT"
        assert held["current_holder_id"] == env["lab_id"]
        assert held["open_transfer_count"] == 1

        events, meta = validate_paginated(
            api.list_chain_events(env["manager"], params={"evidence_item_id": item["id"]})
        )
        assert meta["total_count"] == 3
        assert [event["event_type"] for event in events] == [
            "INTAKE",
            "STORAGE_ASSIGN",
            "RELEASE",
        ]


class TestDispositionOrderTransitions:
    """Authorization is reachable only from PENDING_COURT_AUTH."""

    def test_authorizing_an_authorized_order_again_is_refused(self, api):
        """Neither a second authorization nor a refusal is available out of AUTHORIZED.

        PRD 3.7: "When it does not hold, the order waits: a `CourtClerk` supplies a
        `court_order_number`, which moves the order `PENDING_COURT_AUTH → AUTHORIZED`,
        stamps `authorized_at`, and leaves `auto_authorized` false."
        PRD 3.7: "The same clerk may instead refuse the disposition, supplying a
        `reason`; refusal moves the order `PENDING_COURT_AUTH → REJECTED` without
        recording any `court_order_number`, returns the item's disposition dimension
        `ORDER_PENDING → RETAINED`, decrements the room's `disposal_eligible_count` and
        recomputes `posture` — the next nightly sweep will re-derive eligibility from
        scratch."
        PRD 2.10: "The target resource is in a state that permits the requested
        transition, and neither the source nor the destination storage location is sealed
        — `ERR_ITEM_CUSTODY_STATE_INVALID`, `ERR_ITEM_DISPOSITION_STATE_INVALID`,
        `ERR_CASE_STATE_INVALID`, `ERR_TRANSFER_STATE_INVALID`,
        `ERR_ORDER_STATE_INVALID`, `ERR_CLAIM_STATE_INVALID`, `ERR_AUDIT_STATE_INVALID`,
        `ERR_DISCREPANCY_STATE_INVALID` or `ERR_LOCATION_SEALED` (all 409)."

        Design: Corner/state_machines/disposition_order_authorize_from_authorized_rejected
        """
        env = setup_corner_base()
        item = log_and_store_item(
            env,
            case_id=env["case2_id"],
            location_id=env["loc_g_id"],
            item_description="Recovered road bicycle",
            category="GENERAL",
            packaging_type="CHAIN_TAG_ONLY",
            appraised_value_cents=40000,
            seized_at="2026-07-30T09:00:00Z",
        )
        charge_case(env, env["case2_id"])
        # The FINAL variant floors at intake plus 90 whole days, that is 2026-10-30.
        set_clock("2026-10-30T00:00:00Z")
        adjudicate_case(env, env["case2_id"])
        assert read_item(env, item["id"])["disposition_state"] == "DISPOSAL_ELIGIBLE"
        order = open_order(env, item["id"], "AUCTION", reserve_price_cents=10000)
        authorized = authorize_order(env, order["id"], "CO-2026-0001")
        assert authorized["status"] == "AUTHORIZED"
        assert authorized["auto_authorized"] is False

        validate_error(
            api.authorize_order(
                order["id"], authorize_payload("CO-2026-0002"), env["clerk"]
            ),
            "ERR_ORDER_STATE_INVALID",
            409,
        )
        validate_error(
            api.reject_order(
                order["id"], reject_payload("Court refused the disposition"), env["clerk"]
            ),
            "ERR_ORDER_STATE_INVALID",
            409,
        )

        after = validate_success(
            api.get_disposition_order(order["id"], env["manager"]), 200
        )
        assert after["status"] == "AUTHORIZED"
        assert after["court_order_number"] == "CO-2026-0001"
        assert after["authorized_at"] == "2026-10-30T00:00:00.000Z"
        assert after["auto_authorized"] is False
        assert read_item(env, item["id"])["disposition_state"] == "ORDER_PENDING"


class TestDisposedItemTerminalStates:
    """An executed disposition retires the item on both axes, permanently."""

    def test_a_purged_item_admits_no_further_custody_transition(self, api):
        """After execution the item is PURGED and DISPOSED, and nothing moves it again.

        PRD 3.7: "Automatic authorization applies only when all four of the following
        hold: the order's `type` is `DESTRUCTION`; the case's statute has
        `destruction_requires_court_order` set to false; the item's `category` is none of
        `FIREARM`, `CURRENCY`, `NARCOTICS` or `BIOLOGICAL`; and the item's
        `appraised_value_cents` is strictly below 500000 cents, so that an item appraised
        at exactly five thousand dollars still requires a judge."
        PRD 3.7: "When the predicate holds, the order transitions `PENDING_COURT_AUTH →
        AUTHORIZED` in the same request, `auto_authorized` is set to true,
        `authorized_at` is stamped from the logical clock, and `court_order_number` stays
        null."
        PRD 3.7: "The item is retired on both axes at once — `custody_state` to `PURGED`
        and `disposition_state` to `DISPOSED` — its storage location's `occupied_slots`
        is decremented by 1, the room's `disposal_eligible_count` is decremented, the
        case's `undisposed_item_count` is decremented, a chain entry with `event_type` of
        `DISPOSITION_EXECUTED` is appended, and for a `RETURN_TO_OWNER` order the owner
        claim moves `VERIFIED → RELEASED`."
        PRD 3.5: "Release is an `EvidenceTechnician` action and drives two state machines
        at once, moving the transfer `REQUESTED → RELEASED` and the item's custody
        dimension `STORED → CHECKED_OUT`."
        PRD 3.3: "Storage assignment advances an item's custody dimension from `LOGGED` to
        `STORED` and is performed by an `EvidenceTechnician`."
        PRD 2.10: "The target resource is in a state that permits the requested
        transition, and neither the source nor the destination storage location is sealed
        — `ERR_ITEM_CUSTODY_STATE_INVALID`, `ERR_ITEM_DISPOSITION_STATE_INVALID`,
        `ERR_CASE_STATE_INVALID`, `ERR_TRANSFER_STATE_INVALID`,
        `ERR_ORDER_STATE_INVALID`, `ERR_CLAIM_STATE_INVALID`, `ERR_AUDIT_STATE_INVALID`,
        `ERR_DISCREPANCY_STATE_INVALID` or `ERR_LOCATION_SEALED` (all 409)."

        Design: Corner/state_machines/disposed_item_cannot_start_new_transfer
        """
        env = setup_corner_base()
        item = log_and_store_item(
            env,
            case_id=env["case2_id"],
            location_id=env["loc_g_id"],
            item_description="Damaged bicycle for destruction",
            category="GENERAL",
            packaging_type="CHAIN_TAG_ONLY",
            appraised_value_cents=40000,
            seized_at="2026-07-30T09:00:00Z",
        )
        charge_case(env, env["case2_id"])
        set_clock("2026-10-30T00:00:00Z")
        adjudicate_case(env, env["case2_id"])

        order = open_order(env, item["id"], "DESTRUCTION")
        # Statute AB-1 leaves destruction_requires_court_order false, the category is
        # GENERAL and 40000 is strictly below 500000, so no clerk is needed.
        assert order["auto_authorized"] is True
        assert order["status"] == "AUTHORIZED"
        assert order["authorized_at"] == "2026-10-30T00:00:00.000Z"
        assert order["court_order_number"] is None
        execute_order(env, order["id"], env["tech2_id"], env["aud_id"])

        disposed = read_item(env, item["id"])
        assert disposed["custody_state"] == "PURGED"
        assert disposed["disposition_state"] == "DISPOSED"

        validate_error(
            api.assign_storage(
                item["id"], storage_assignment_payload(env["loc_g_id"]),
                env["tech_headers"],
            ),
            "ERR_ITEM_CUSTODY_STATE_INVALID",
            409,
        )

        location = read_location(env, env["loc_g_id"])
        assert location["occupied_slots"] == 0


class TestCaseClosure:
    """Closure is gated on a live count of the case's undisposed items."""

    def test_closing_a_case_holding_an_undisposed_item_is_refused(self, api):
        """The gate is the current undisposed count, and it clears once the item is disposed.

        PRD 3.4: "Case closure belongs to the `PropertyRoomManager` and moves the case
        `ADJUDICATED → CLOSED`, stamping `closed_at`."
        PRD 3.4: "It is permitted only when the case's `undisposed_item_count` — the
        number of its items whose `disposition_state` is anything other than `DISPOSED` —
        has reached 0; otherwise the request is refused with
        `ERR_CASE_HAS_UNDISPOSED_ITEMS`."

        Design: Corner/state_machines/case_close_with_undisposed_items_rejected
        """
        env = setup_corner_base()
        item = log_and_store_item(
            env,
            case_id=env["case2_id"],
            location_id=env["loc_g_id"],
            item_description="Still-held bicycle",
            category="GENERAL",
            packaging_type="CHAIN_TAG_ONLY",
            appraised_value_cents=40000,
            seized_at="2026-07-30T09:00:00Z",
        )
        charge_case(env, env["case2_id"])
        set_clock("2026-10-30T00:00:00Z")
        adjudicate_case(env, env["case2_id"])
        assert read_case(env, env["case2_id"])["undisposed_item_count"] == 1

        validate_error(
            api.close_case(env["case2_id"], env["manager"]),
            "ERR_CASE_HAS_UNDISPOSED_ITEMS",
            409,
        )

        blocked = read_case(env, env["case2_id"])
        assert blocked["status"] == "ADJUDICATED"
        assert blocked["closed_at"] is None

        order = open_order(env, item["id"], "DESTRUCTION")
        execute_order(env, order["id"], env["tech2_id"], env["aud_id"])
        assert read_case(env, env["case2_id"])["undisposed_item_count"] == 0

        closed = validate_success(
            api.close_case(env["case2_id"], env["manager"]), 200
        )
        assert closed["status"] == "CLOSED"
        assert closed["closed_at"] == "2026-10-30T00:00:00.000Z"


class TestReportLostSideEffects:
    """Reporting a released item lost fans out across item, bin and room."""

    def test_report_lost_moves_the_item_missing_and_frees_its_slot(self, api):
        """One transition writes the item, the bin, a standalone discrepancy and the posture.

        PRD 3.5: "When an item cannot be produced at all, a `PropertyRoomManager` reports
        it lost, supplying a `reason` that is stored in `denial_reason`."
        PRD 3.5: "That moves the transfer from `RELEASED` or `OVERDUE` to `LOST`, moves
        the item `CHECKED_OUT → MISSING`, clears `current_holder_id`, creates a
        discrepancy with `kind` of `MISSING`, a null `audit_session_id` and `status` of
        `OPEN`, decrements the item's storage location `occupied_slots` by 1 because the
        item has left the occupancy set, increments the room's `open_discrepancy_count`
        and — when the item's `category` is `FIREARM`, `CURRENCY` or `NARCOTICS` — its
        `missing_high_risk_count`, appends a `DISCREPANCY_RAISED` chain entry, and
        recomputes the room's `posture`."
        PRD 2.6: "Otherwise, if `open_discrepancy_count` is at least 1 or
        `sealed_location_count` is at least 1, the posture is `RESTRICTED`."
        PRD 2.12: "Entries also carry `sequence_no`, a 1-based and gapless sequence **per
        evidence item**, assigned in ascending `occurred_at` order and, where two entries
        share an instant, in ascending `created_at` order."

        Design: Corner/state_machines/report_lost_cross_entity_side_effects_on_item_location_and_room
        """
        env = setup_corner_base()
        item = log_and_store_item(
            env,
            case_id=env["case1_id"],
            location_id=env["loc_g_id"],
            item_description="Swab kit for typing",
            category="GENERAL",
            packaging_type="PAPER_BAG",
            appraised_value_cents=1500,
            seized_at="2026-07-31T12:00:00Z",
        )
        transfer = request_transfer(
            env, item["id"], env["lab_id"], "LAB_ANALYSIS",
            "2026-08-02T09:00:00Z", "2026-08-10T09:00:00Z",
            headers=env["lab_headers"],
        )
        release_transfer(env, transfer["id"], "sig-release-1")
        # The bin stays reserved while the item is out at the laboratory.
        assert read_location(env, env["loc_g_id"])["occupied_slots"] == 1

        lost = validate_success(
            api.report_transfer_lost(
                transfer["id"],
                report_lost_payload("Not returned by the laboratory courier"),
                env["manager"],
            ),
            200,
        )

        assert lost["status"] == "LOST"
        assert lost["denial_reason"] == "Not returned by the laboratory courier"

        missing = read_item(env, item["id"])
        assert missing["custody_state"] == "MISSING"
        assert missing["current_holder_id"] is None
        # The disposition dimension is untouched by a custody-side loss.
        assert missing["disposition_state"] == "RETAINED"
        assert read_location(env, env["loc_g_id"])["occupied_slots"] == 0

        rows, meta = validate_paginated(
            api.list_discrepancies(
                env["manager"], params={"evidence_item_id": item["id"]}
            )
        )
        assert meta["total_count"] == 1
        assert rows[0]["kind"] == "MISSING"
        assert rows[0]["status"] == "OPEN"
        assert rows[0]["audit_session_id"] is None

        room = read_room(env)
        assert room["open_discrepancy_count"] == 1
        assert room["missing_high_risk_count"] == 0
        assert room["posture"] == "RESTRICTED"

        events, event_meta = validate_paginated(
            api.list_chain_events(env["manager"], params={"evidence_item_id": item["id"]})
        )
        assert event_meta["total_count"] == 4
        assert events[3]["sequence_no"] == 4
        assert events[3]["event_type"] == "DISCREPANCY_RAISED"
