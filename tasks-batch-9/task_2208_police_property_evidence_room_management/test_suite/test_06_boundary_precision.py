"""Inclusive boundaries: the vault threshold, an empty audit and the sweep instant."""

from decimal import Decimal

from test_helpers import (
    ApiErrorId,
    assign_storage,
    close_audit,
    log_and_store_item,
    log_item,
    read_item,
    read_location,
    read_room,
    reconcile_audit,
    run_sweep,
    set_clock,
    setup_difficulty_base,
    setup_started_audit,
    storage_assignment_payload,
    validate_error,
    validate_paginated,
)


class TestHighValueVaultThreshold:
    """500000 cents already qualifies for the vault, PRD section 3.2."""

    def test_one_cent_below_the_threshold_still_requires_a_general_bin(self, api):
        """499999 derives GENERAL while exactly 500000 derives HIGH_VALUE_VAULT.

        PRD 3.2: "The derivation looks only at the item's own `category` and
        `appraised_value_cents`."
        PRD 3.2: "A `GENERAL` item requires `HIGH_VALUE_VAULT` when its appraised value
        is at least 500000 cents — that is, five thousand dollars or more, with exactly
        500000 already qualifying — and `GENERAL` otherwise."

        Design: Difficulty/boundary_precision_check/appraised_value_exactly_500000_requires_high_value_vault
        """
        env = setup_difficulty_base()

        low = log_item(
            env,
            case_id=env["case1_id"],
            item_description="Coin album just under threshold",
            category="GENERAL",
            packaging_type="RIGID_BOX",
            appraised_value_cents=499999,
            seized_at="2026-07-31T15:00:00Z",
        )
        at_threshold = log_item(
            env,
            case_id=env["case1_id"],
            item_description="Coin album at threshold",
            category="GENERAL",
            packaging_type="RIGID_BOX",
            appraised_value_cents=500000,
            seized_at="2026-07-31T15:10:00Z",
        )

        assert low["required_storage_category"] == "GENERAL"
        assert at_threshold["required_storage_category"] == "HIGH_VALUE_VAULT"

    def test_the_derived_category_governs_which_bin_will_accept_the_item(self, api):
        """The boundary item is refused by the general bin and taken by the vault.

        PRD 3.3: "The location's `category` must equal the item's
        `required_storage_category`, otherwise `ERR_STORAGE_CATEGORY_MISMATCH`."
        PRD 3.3: "A successful assignment writes `storage_location_id` onto the item,
        increments the chosen location's `occupied_slots` by 1 and that location's
        `version` by 1, appends a chain entry with `event_type` of `STORAGE_ASSIGN`, and
        recomputes the room's `posture`."
        PRD 3.2: "Where the item must live is derived at intake and stored on the item as
        `required_storage_category`, and it is re-read on every storage assignment and on
        every relocation of a misplaced item."

        Design: Difficulty/boundary_precision_check/appraised_value_exactly_500000_requires_high_value_vault
        """
        env = setup_difficulty_base()
        low = log_and_store_item(
            env,
            case_id=env["case1_id"],
            location_id=env["loc_g_id"],
            item_description="Coin album just under threshold",
            category="GENERAL",
            packaging_type="RIGID_BOX",
            appraised_value_cents=499999,
            seized_at="2026-07-31T15:00:00Z",
        )
        at_threshold = log_item(
            env,
            case_id=env["case1_id"],
            item_description="Coin album at threshold",
            category="GENERAL",
            packaging_type="RIGID_BOX",
            appraised_value_cents=500000,
            seized_at="2026-07-31T15:10:00Z",
        )

        refused = api.assign_storage(
            at_threshold["id"],
            storage_assignment_payload(env["loc_g_id"]),
            env["tech_headers"],
        )

        validate_error(refused, ApiErrorId.ERR_STORAGE_CATEGORY_MISMATCH, 409)
        stored = assign_storage(env, at_threshold["id"], env["loc_v_id"])
        assert stored["storage_location_id"] == env["loc_v_id"]
        assert stored["custody_state"] == "STORED"
        assert low["storage_location_id"] == env["loc_g_id"]
        assert low["custody_state"] == "STORED"
        assert read_location(env, env["loc_g_id"])["occupied_slots"] == 1
        assert read_location(env, env["loc_v_id"])["occupied_slots"] == 1


class TestEmptyLocationAudit:
    """An audit of a bin holding nothing scores exactly zero, PRD section 3.8."""

    def _audit_of_the_empty_refrigerator(self, env):
        location = read_location(env, env["loc_r2_id"])
        return setup_started_audit(
            env,
            env["loc_r2_id"],
            location["version"],
            scheduled_start_at="2026-08-08T09:00:00Z",
            scheduled_end_at="2026-08-08T17:00:00Z",
        )

    def test_reconciling_an_empty_bin_yields_a_zero_risk_index(self, api):
        """No expected items means no discrepancies and a 0.00 index.

        PRD 3.8: "Starting the session moves it `SCHEDULED → IN_PROGRESS`, stamps
        `started_at`, and snapshots the inventory the auditor is expected to find:
        `expected_evidence_item_ids` is the list of identifiers of the evidence items
        whose `storage_location_id` is that location and whose `custody_state` is
        `STORED`, ordered by `created_at` ascending, and `expected_item_count` is the
        length of that list."
        PRD 3.8: "Reconciliation is the counterpart: it moves the session
        `IN_PROGRESS → RECONCILED`, stamps `reconciled_at`, and accounts for everything
        expected but never scanned."
        PRD 3.8: "The location itself moves `OPEN → SEALED_FOR_AUDIT`, records the
        session in `sealed_by_audit_session_id`, and has its `version` incremented by 1;
        the room's `sealed_location_count` is incremented and its `posture` recomputed,
        which takes a clean room from `OPEN` to `RESTRICTED` for the duration."

        Design: Difficulty/boundary_precision_check/reconcile_with_zero_expected_items_yields_zero_risk_index
        """
        env = setup_difficulty_base()
        session = self._audit_of_the_empty_refrigerator(env)

        reconciled = reconcile_audit(env, session["id"])

        assert reconciled["status"] == "RECONCILED"
        assert reconciled["expected_item_count"] == 0
        assert reconciled["expected_evidence_item_ids"] == []
        assert Decimal(str(reconciled["risk_index"])) == Decimal("0.00")
        assert reconciled["missing_count"] == 0
        assert reconciled["misplaced_count"] == 0
        rows, meta = validate_paginated(
            api.list_discrepancies(env["manager"], params={"audit_session_id": session["id"]})
        )
        assert meta["total_count"] == 0
        assert rows == []
        room = read_room(env)
        assert room["sealed_location_count"] == 1
        assert room["posture"] == "RESTRICTED"

    def test_closing_the_empty_audit_releases_the_seal_and_reopens_the_room(self, api):
        """The seal, not a discrepancy, was the only thing restricting the room.

        PRD 3.8: "Closing stamps `closed_at`, returns the location
        `SEALED_FOR_AUDIT → OPEN`, clears `sealed_by_audit_session_id`, increments the
        location's `version` by 1, decrements the room's `sealed_location_count` and
        recomputes its `posture`."
        PRD 2.6: "When the last open discrepancy is resolved and every seal is released,
        the room returns to `OPEN` and all gated operations become available again."

        Design: Difficulty/boundary_precision_check/reconcile_with_zero_expected_items_yields_zero_risk_index
        """
        env = setup_difficulty_base()
        session = self._audit_of_the_empty_refrigerator(env)
        reconcile_audit(env, session["id"])

        closed = close_audit(env, session["id"])

        assert closed["status"] == "CLOSED"
        location = read_location(env, env["loc_r2_id"])
        assert location["status"] == "OPEN"
        assert location["sealed_by_audit_session_id"] is None
        room = read_room(env)
        assert room["sealed_location_count"] == 0
        assert room["open_discrepancy_count"] == 0
        assert room["posture"] == "OPEN"


class TestSweepReleaseInstantIsInclusive:
    """The sweep matures retention at or before the current instant, PRD section 3.8."""

    def _stored_item_one_millisecond_short(self, env):
        """An item whose preliminary release lands on 2027-08-01, clock just before it."""
        item = log_and_store_item(
            env,
            case_id=env["case1_id"],
            location_id=env["loc_g_id"],
            item_description="Shell casing envelope",
            category="GENERAL",
            packaging_type="SEALED_ENVELOPE",
            appraised_value_cents=500,
            seized_at="2026-07-31T18:00:00Z",
        )
        assert item["retention_release_at"] == "2027-08-01T00:00:00.000Z"
        set_clock("2027-07-31T23:59:59.999Z")
        return item

    def test_one_millisecond_before_the_release_the_item_stays_retained(self, api):
        """A sweep just short of the instant promotes nothing.

        PRD 3.8: "**Step three** matures retention: every item whose `custody_state` is
        `STORED` and whose `retention_release_at` is non-null and at or before the current
        instant moves `RETAINED → DISPOSAL_ELIGIBLE`."
        PRD 2.8: "Retention periods and notice periods are expressed in whole days and
        are added to a UTC instant as exact increments of 86,400 seconds."

        Design: Difficulty/boundary_precision_check/sweep_marks_item_eligible_when_release_at_equals_clock
        """
        env = setup_difficulty_base()
        item = self._stored_item_one_millisecond_short(env)

        swept = run_sweep(env)

        assert swept["disposal_eligible_count"] == 0
        assert swept["last_sweep_at"] == "2027-07-31T23:59:59.999Z"
        after = read_item(env, item["id"])
        assert after["disposition_state"] == "RETAINED"
        assert after["custody_state"] == "STORED"

    def test_at_exactly_the_release_instant_the_item_becomes_eligible(self, api):
        """The comparison is inclusive, so equality promotes the item.

        PRD 3.8: "**Step four** re-derives every dependent figure on the room:
        `open_discrepancy_count`, `missing_high_risk_count`, `sealed_location_count`,
        `disposal_eligible_count`, `escrow_balance_cents` and `posture`, and finally
        stamps `last_sweep_at` with the current instant."
        PRD 2.7: "`StorageLocation.occupied_slots` equals the number of evidence items
        whose `storage_location_id` is that location and whose `custody_state` is either
        `STORED` or `CHECKED_OUT`."

        Design: Difficulty/boundary_precision_check/sweep_marks_item_eligible_when_release_at_equals_clock
        """
        env = setup_difficulty_base()
        item = self._stored_item_one_millisecond_short(env)
        run_sweep(env)
        set_clock("2027-08-01T00:00:00Z")

        swept = run_sweep(env)

        assert swept["disposal_eligible_count"] == 1
        assert swept["last_sweep_at"] == "2027-08-01T00:00:00.000Z"
        after = read_item(env, item["id"])
        assert after["disposition_state"] == "DISPOSAL_ELIGIBLE"
        assert after["custody_state"] == "STORED"
        assert read_location(env, env["loc_g_id"])["occupied_slots"] == 1
