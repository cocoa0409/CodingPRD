"""Cross-cutting layers: optimistic concurrency, version arithmetic and derived counters."""

from test_helpers import (
    ApiErrorId,
    adjudicate_case,
    assign_storage,
    audit_session_payload,
    charge_case,
    disposition_order_payload,
    log_and_store_item,
    log_item,
    read_case,
    read_item,
    read_location,
    read_room,
    reject_payload,
    retention_determination_payload,
    run_sweep,
    set_clock,
    setup_corner_base,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestOptimisticConcurrencyGuards:
    """The two create operations guarded against a stale parent version."""

    def test_retention_determination_with_a_stale_item_version_is_refused(self, api):
        """A storage assignment behind the client's back invalidates the observed version.

        PRD 2.9: "Recording a retention determination requires
        `expected_evidence_item_version` in the request body as a non-optional field,
        carrying the `version` of the target evidence item as the client last observed it."
        PRD 2.9: "If that value does not equal the item's current `version`, the request is
        rejected with `ERR_STALE_EVIDENCE_ITEM_VERSION` (HTTP 412)."
        PRD 2.9: "A new determination legitimately supersedes the previous one, so without
        this guard a client whose view predates, say, an adjudication cascade that already
        rewrote `retention_release_at` would silently overwrite a posture it never saw."
        PRD 2.4: "Property rooms, offense statutes, storage locations, custodians, cases,
        evidence items, retention determinations, custody transfers, disposition orders,
        owner claims, audit sessions and discrepancies additionally carry `updated_at`,
        refreshed on every mutation, and `version`, an integer that increments by one on
        every mutation — including mutations that only touch derived counters."

        Design: Corner/cross_cutting_complexity_layers/retention_determination_with_stale_item_version_returns_412
        """
        env = setup_corner_base()
        logged = log_item(
            env,
            case_id=env["case1_id"],
            item_description="Item read before assignment",
            category="GENERAL",
            packaging_type="PAPER_BAG",
            appraised_value_cents=100,
            seized_at="2026-07-31T12:00:00Z",
        )
        stale_version = logged["version"]
        stored = assign_storage(env, logged["id"], env["loc_g_id"])
        fresh_version = stored["version"]
        assert stale_version == 1
        assert fresh_version == 2

        validate_error(
            api.create_retention_determination(
                retention_determination_payload(logged["id"], "PRELIMINARY", stale_version),
                env["manager"],
            ),
            ApiErrorId.ERR_STALE_EVIDENCE_ITEM_VERSION,
            412,
        )

        rows, meta = validate_paginated(
            api.list_retention_determinations(
                env["manager"], params={"evidence_item_id": logged["id"]}
            )
        )
        # Only the determination written by the intake cascade exists.
        assert meta["total_count"] == 1
        assert rows[0]["superseded"] is False
        assert read_item(env, logged["id"])["version"] == 2

        replayed = validate_success(
            api.create_retention_determination(
                retention_determination_payload(logged["id"], "PRELIMINARY", fresh_version),
                env["manager"],
            ),
            201,
        )
        assert replayed["resolved_basis"] == "PRELIMINARY"
        assert replayed["statute_days_applied"] == 365
        assert replayed["anchor_at"] == "2026-08-01T00:00:00.000Z"
        assert replayed["computed_release_at"] == "2027-08-01T00:00:00.000Z"
        assert replayed["superseded"] is False

        rows, meta = validate_paginated(
            api.list_retention_determinations(
                env["manager"], params={"evidence_item_id": logged["id"]}
            )
        )
        assert meta["total_count"] == 2
        previous = [row for row in rows if row["id"] != replayed["id"]][0]
        assert previous["superseded"] is True
        assert read_item(env, logged["id"])["version"] == 3

    def test_audit_session_with_a_stale_location_version_is_refused(self, api):
        """Storing an item bumps the bin's version, so the auditor's snapshot goes stale.

        PRD 2.9: "Scheduling an audit session requires `expected_storage_location_version`
        in the request body as a non-optional field, carrying the `version` of the target
        storage location as the client last observed it."
        PRD 2.9: "If that value does not equal the location's current `version`, the
        request is rejected with `ERR_STALE_STORAGE_LOCATION_VERSION` (HTTP 412)."
        PRD 2.9: "Multiple non-overlapping sessions may legitimately be scheduled against
        one location, so the stale version is what tells the scheduler that the location's
        occupancy or seal state has moved since it was read."
        PRD 3.3: "A successful assignment writes `storage_location_id` onto the item,
        increments the chosen location's `occupied_slots` by 1 and that location's
        `version` by 1, appends a chain entry with `event_type` of `STORAGE_ASSIGN`, and
        recomputes the room's `posture`."
        PRD 3.8: "Creating it also increments the target location's `version` by 1."

        Design: Corner/cross_cutting_complexity_layers/audit_session_with_stale_location_version_returns_412
        """
        env = setup_corner_base()
        stale_location_version = env["loc_g_version"]
        log_and_store_item(
            env,
            case_id=env["case1_id"],
            location_id=env["loc_g_id"],
            item_description="Item stored after the auditor's read",
            category="GENERAL",
            packaging_type="PAPER_BAG",
            appraised_value_cents=100,
            seized_at="2026-07-31T12:00:00Z",
        )
        observed = validate_success(
            api.get_storage_location(env["loc_g_id"], env["aud_headers"]), 200
        )
        fresh_location_version = observed["version"]
        assert stale_location_version == 1
        assert fresh_location_version == 2

        stale_body = audit_session_payload(
            env["loc_g_id"],
            env["aud_id"],
            "2026-08-10T09:00:00Z",
            "2026-08-10T17:00:00Z",
            stale_location_version,
        )
        validate_error(
            api.create_audit_session(stale_body, env["aud_headers"]),
            ApiErrorId.ERR_STALE_STORAGE_LOCATION_VERSION,
            412,
        )
        _, meta = validate_paginated(
            api.list_audit_sessions(
                env["manager"], params={"storage_location_id": env["loc_g_id"]}
            )
        )
        assert meta["total_count"] == 0

        fresh_body = audit_session_payload(
            env["loc_g_id"],
            env["aud_id"],
            "2026-08-10T09:00:00Z",
            "2026-08-10T17:00:00Z",
            fresh_location_version,
        )
        session = validate_success(api.create_audit_session(fresh_body, env["aud_headers"]), 201)
        assert session["status"] == "SCHEDULED"
        assert session["expected_item_count"] == 0
        assert session["scanned_item_count"] == 0
        assert read_location(env, env["loc_g_id"])["version"] == 3

        # Scheduling itself bumped the version, so the client must re-read every time.
        validate_error(
            api.create_audit_session(fresh_body, env["aud_headers"]),
            ApiErrorId.ERR_STALE_STORAGE_LOCATION_VERSION,
            412,
        )

    def test_evidence_item_version_increments_on_every_write_including_a_cascade(self, api):
        """Intake, storage assignment and the adjudication cascade each bump the version.

        PRD 2.4: "Property rooms, offense statutes, storage locations, custodians, cases,
        evidence items, retention determinations, custody transfers, disposition orders,
        owner claims, audit sessions and discrepancies additionally carry `updated_at`,
        refreshed on every mutation, and `version`, an integer that increments by one on
        every mutation — including mutations that only touch derived counters."
        PRD 3.4: "An `Investigator` (or a `PropertyRoomManager`) records that charges were
        filed, moving the case from `OPEN` to `CHARGED` and stamping `charged_at` from the
        logical clock."
        PRD 3.4: "Adjudication, performed by a `CourtClerk` or a `PropertyRoomManager`,
        moves the case `CHARGED → ADJUDICATED`, stamps `adjudicated_at`, and then walks
        every evidence item of the case in ascending `created_at` order: for each item it
        creates a determination with a requested `basis` of `FINAL`, marks the prior
        determination superseded, rewrites the item's `retention_release_at` and
        `retention_basis`, appends a `RETENTION_SET` chain entry, and increments that
        item's `version` by 1."

        Design: Corner/cross_cutting_complexity_layers/version_increments_on_every_write_to_evidence_item
        """
        env = setup_corner_base()
        logged = log_item(
            env,
            case_id=env["case1_id"],
            item_description="Item whose version we track",
            category="GENERAL",
            packaging_type="PAPER_BAG",
            appraised_value_cents=100,
            seized_at="2026-07-31T12:00:00Z",
        )
        assert logged["version"] == 1

        stored = assign_storage(env, logged["id"], env["loc_g_id"])
        assert stored["version"] == 2

        charge_case(env, env["case1_id"])
        # Charging the case writes nothing to the item, so its version stands still.
        assert read_item(env, logged["id"])["version"] == 2

        set_clock("2026-08-05T00:00:00Z")
        adjudicate_case(env, env["case1_id"])

        after_cascade = validate_success(
            api.get_evidence_item(logged["id"], env["manager"]), 200
        )
        assert after_cascade["version"] == 3
        assert after_cascade["retention_basis"] == "FINAL"
        # 30 appeal days plus half of 365 rounded up to 183 days from 2026-08-05.
        assert after_cascade["retention_release_at"] == "2027-03-06T00:00:00.000Z"

        # A read is not a mutation, so a second read reports the same version.
        assert validate_success(
            api.get_evidence_item(logged["id"], env["manager"]), 200
        )["version"] == 3


class TestDerivedCounterReconciliation:
    """The room's disposal_eligible_count across an order-and-rejection round trip."""

    def test_disposal_eligible_count_survives_the_order_and_rejection_round_trip(self, api):
        """The counter tracks the item's disposition state at every observable point.

        PRD 3.4: "Any item whose newly computed `retention_release_at` is at or before the
        current instant and whose `custody_state` is `STORED` continues in the same request
        from `RETAINED` to `DISPOSAL_ELIGIBLE`, and the room's `disposal_eligible_count`
        and `posture` are recomputed as a consequence."
        PRD 3.7: "A successful creation moves the item's disposition dimension from
        `DISPOSAL_ELIGIBLE` or `UNCLAIMED_ELIGIBLE` to `ORDER_PENDING` and starts the order
        in `PENDING_COURT_AUTH` with `auto_authorized` false, `court_order_number`,
        `gross_sale_cents`, `commission_cents`, `storage_recovery_cents`,
        `settled_net_proceeds_cents`, `executed_by_custodian_id`, `witness_custodian_id`,
        `authorized_at`, `executed_at`, `settlement_deadline_at`, `settled_at` and
        `payee_reference` all null, and `settlement_status` at `NONE`."
        PRD 3.7: "The same clerk may instead refuse the disposition, supplying a `reason`;
        refusal moves the order `PENDING_COURT_AUTH → REJECTED` without recording any
        `court_order_number`, returns the item's disposition dimension `ORDER_PENDING →
        RETAINED`, decrements the room's `disposal_eligible_count` and recomputes `posture`
        — the next nightly sweep will re-derive eligibility from scratch."
        PRD 3.8: "**Step three** matures retention: every item whose `custody_state` is
        `STORED` and whose `retention_release_at` is non-null and at or before the current
        instant moves `RETAINED → DISPOSAL_ELIGIBLE`."
        PRD 3.8: "**Step four** re-derives every dependent figure on the room:
        `open_discrepancy_count`, `missing_high_risk_count`, `sealed_location_count`,
        `disposal_eligible_count`, `escrow_balance_cents` and `posture`, and finally stamps
        `last_sweep_at` with the current instant."

        Design: Corner/cross_cutting_complexity_layers/derived_field_reconciliation_disposal_eligible_count_after_reject
        """
        env = setup_corner_base()
        item = log_and_store_item(
            env,
            case_id=env["case2_id"],
            location_id=env["loc_v_id"],
            item_description="Firearm in the eligibility ledger",
            category="FIREARM",
            packaging_type="RIGID_BOX",
            appraised_value_cents=45000,
            seized_at="2026-07-30T09:00:00Z",
        )
        charge_case(env, env["case2_id"])
        set_clock("2026-10-30T00:00:00Z")
        adjudicate_case(env, env["case2_id"])

        # The 90-day floor on the FINAL variant lands exactly on the current instant.
        matured = read_item(env, item["id"])
        assert matured["retention_release_at"] == "2026-10-30T00:00:00.000Z"
        assert matured["disposition_state"] == "DISPOSAL_ELIGIBLE"
        assert read_room(env)["disposal_eligible_count"] == 1

        order = validate_success(
            api.create_disposition_order(
                disposition_order_payload(item["id"], "DESTRUCTION", env["tech_id"]),
                env["tech_headers"],
            ),
            201,
        )
        assert order["status"] == "PENDING_COURT_AUTH"
        assert read_item(env, item["id"])["disposition_state"] == "ORDER_PENDING"
        assert read_room(env)["disposal_eligible_count"] == 0

        rejected = validate_success(
            api.reject_order(
                order["id"], reject_payload("Forfeiture petition still pending"), env["clerk"]
            ),
            200,
        )
        assert rejected["status"] == "REJECTED"
        returned = read_item(env, item["id"])
        assert returned["disposition_state"] == "RETAINED"
        assert returned["custody_state"] == "STORED"
        assert read_room(env)["disposal_eligible_count"] == 0

        run_sweep(env)

        assert read_item(env, item["id"])["disposition_state"] == "DISPOSAL_ELIGIBLE"
        assert read_room(env)["disposal_eligible_count"] == 1
        # Nothing was ever disposed, so the case's own counter never moved.
        assert read_case(env, env["case2_id"])["undisposed_item_count"] == 1
