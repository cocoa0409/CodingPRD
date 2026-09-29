"""Multi-link cascades rooted in reconciliation and in adjudication."""

from decimal import Decimal

from test_helpers import (
    adjudicate_case,
    charge_case,
    log_and_store_item,
    read_case,
    read_custodian,
    read_item,
    read_location,
    read_room,
    reconcile_audit,
    request_transfer,
    set_clock,
    setup_difficulty_base,
    setup_started_audit,
    validate_paginated,
    validate_success,
)


class TestReconcileMissingCascade:
    """A missing vault item drags the room and an unrelated transfer with it."""

    def _audit_over_a_missing_currency_bundle(self, env):
        """Cash in the vault, clothing in a bin, one requested transfer, one audit."""
        cash = log_and_store_item(
            env,
            case_id=env["case1_id"],
            location_id=env["loc_v_id"],
            item_description="Seized US currency bundle",
            category="CURRENCY",
            packaging_type="SEALED_ENVELOPE",
            appraised_value_cents=300000,
            seized_at="2026-07-31T07:00:00Z",
        )
        cloth = log_and_store_item(
            env,
            case_id=env["case1_id"],
            location_id=env["loc_g_id"],
            item_description="Suspect clothing bag",
            category="GENERAL",
            packaging_type="PAPER_BAG",
            appraised_value_cents=5000,
            seized_at="2026-07-31T07:20:00Z",
        )
        transfer = request_transfer(
            env,
            cloth["id"],
            env["inv_id"],
            "INVESTIGATIVE_REVIEW",
            "2026-08-20T09:00:00Z",
            "2026-08-25T09:00:00Z",
            headers=env["inv_headers"],
        )
        vault = read_location(env, env["loc_v_id"])
        session = setup_started_audit(
            env,
            env["loc_v_id"],
            vault["version"],
            scheduled_start_at="2026-08-07T09:00:00Z",
            scheduled_end_at="2026-08-07T17:00:00Z",
        )
        return cash, cloth, transfer, session

    def test_unscanned_vault_item_goes_missing_and_frees_its_slot(self, api):
        """Reconciliation raises the discrepancy that drives the item out of the bin.

        PRD 3.8: "Each such discrepancy drives its item `STORED → MISSING`, which
        decrements the location's `occupied_slots` by 1 and increments the room's
        `open_discrepancy_count` and, for a `FIREARM`, `CURRENCY` or `NARCOTICS` item,
        its `missing_high_risk_count`; a `DISCREPANCY_RAISED` chain entry is appended."
        PRD 2.7: "The consequence is that an item signed out to a laboratory keeps its
        bin reserved — releasing it does not free a slot — whereas an item that goes
        `MISSING` releases its slot immediately, and recovering it consumes a slot
        again."
        PRD 3.8: "The category multiplier is 1.5 when the audited location's `category`
        is `HIGH_VALUE_VAULT` or `REFRIGERATED`, and 1.0 for `GENERAL` and
        `OVERSIZED_YARD`."

        Design: Difficulty/transitive_cascade/audit_reconcile_missing_cascades_to_transfer_denial
        """
        env = setup_difficulty_base()
        cash, cloth, transfer, session = self._audit_over_a_missing_currency_bundle(env)

        reconciled = reconcile_audit(env, session["id"])

        rows, meta = validate_paginated(
            api.list_discrepancies(env["manager"], params={"audit_session_id": session["id"]})
        )
        assert meta["total_count"] == 1
        discrepancy = rows[0]
        assert discrepancy["kind"] == "MISSING"
        assert discrepancy["status"] == "OPEN"
        assert discrepancy["evidence_item_id"] == cash["id"]
        # 5.0 missing weight * 1.3 value multiplier * 1.5 vault multiplier.
        assert Decimal(str(discrepancy["weight_contribution"])) == Decimal("9.75")
        assert reconciled["missing_count"] == 1
        assert Decimal(str(reconciled["risk_index"])) == Decimal("9.75")
        missing_item = read_item(env, cash["id"])
        assert missing_item["custody_state"] == "MISSING"
        # The custody cascade leaves the disposition dimension alone.
        assert missing_item["disposition_state"] == "RETAINED"
        assert read_location(env, env["loc_v_id"])["occupied_slots"] == 0

    def test_lockdown_denies_the_unrelated_requested_transfer(self, api):
        """One missing banknote bundle locks the room and denies a pending escort.

        PRD 2.6: "`missing_high_risk_count` — the subset of those rows whose `kind` is
        `MISSING` and whose evidence item has a `category` of `FIREARM`, `CURRENCY` or
        `NARCOTICS`."
        PRD 2.6: "First, whenever a recomputation moves the room into `LOCKED_DOWN` —
        whether from `OPEN` or from `RESTRICTED` — every custody transfer in that room
        whose `status` is `REQUESTED` is moved to `DENIED`, has its `denial_reason` set
        to the literal string `ROOM_LOCKED_DOWN`, and releases the escort capacity it
        was holding, decrementing `open_escort_count` on its receiving custodian."
        PRD 3.8: "Finally the room's `posture` is recomputed from the new counters; if
        the result is `LOCKED_DOWN`, every custody transfer in the room still sitting in
        `REQUESTED` is denied as described in §2.6."

        Design: Difficulty/transitive_cascade/audit_reconcile_missing_cascades_to_transfer_denial
        """
        env = setup_difficulty_base()
        cash, cloth, transfer, session = self._audit_over_a_missing_currency_bundle(env)
        assert transfer["status"] == "REQUESTED"
        assert read_custodian(env, env["inv_id"])["open_escort_count"] == 1

        reconcile_audit(env, session["id"])

        room = read_room(env)
        assert room["missing_high_risk_count"] == 1
        assert room["open_discrepancy_count"] == 1
        assert room["posture"] == "LOCKED_DOWN"
        denied = validate_success(
            api.get_custody_transfer(transfer["id"], env["manager"]), 200
        )
        assert denied["status"] == "DENIED"
        assert denied["denial_reason"] == "ROOM_LOCKED_DOWN"
        assert read_custodian(env, env["inv_id"])["open_escort_count"] == 0


class TestAdjudicationEligibilityCascade:
    """Adjudication matures retention and raises the room's eligibility counter."""

    def _charged_case_past_the_floor(self, env):
        """A watch under the zero-day statute, charged, with the clock past the floor."""
        item = log_and_store_item(
            env,
            case_id=env["case2_id"],
            location_id=env["loc_g_id"],
            item_description="Found wristwatch",
            category="GENERAL",
            packaging_type="SEALED_ENVELOPE",
            appraised_value_cents=15000,
            seized_at="2026-07-28T16:00:00Z",
        )
        charge_case(env, env["case2_id"])
        set_clock("2026-11-30T00:00:00Z")
        return item

    def test_adjudication_writes_a_final_determination_against_the_new_anchor(self, api):
        """A zero-day statute makes the anchor itself the release instant.

        PRD 3.4: "Under the `PRELIMINARY` variant the `anchor_at` is the item's
        `intake_at`, the `statute_days_applied` is the statute's full
        `statutory_retention_days`, and the release instant is the anchor plus those
        whole days; the appeal window and the ninety-day floor are both ignored."
        PRD 3.4: "The candidate release instant is the anchor plus those days; a floor
        instant is computed as the item's `intake_at` plus 90 days; and the release
        instant actually applied is the later of the candidate and the floor."
        PRD 3.4: "Adjudication, performed by a `CourtClerk` or a `PropertyRoomManager`,
        moves the case `CHARGED → ADJUDICATED`, stamps `adjudicated_at`, and then walks
        every evidence item of the case in ascending `created_at` order: for each item it
        creates a determination with a requested `basis` of `FINAL`, marks the prior
        determination superseded, rewrites the item's `retention_release_at` and
        `retention_basis`, appends a `RETENTION_SET` chain entry, and increments that
        item's `version` by 1."

        Design: Difficulty/transitive_cascade/case_adjudicate_cascades_to_disposal_eligibility_counter
        """
        env = setup_difficulty_base()
        item = self._charged_case_past_the_floor(env)
        before = read_item(env, item["id"])
        assert before["retention_release_at"] == "2026-08-01T00:00:00.000Z"
        assert before["disposition_state"] == "RETAINED"
        assert read_room(env)["disposal_eligible_count"] == 0

        adjudicated = adjudicate_case(env, env["case2_id"])

        assert adjudicated["status"] == "ADJUDICATED"
        assert adjudicated["adjudicated_at"] == "2026-11-30T00:00:00.000Z"
        rows, meta = validate_paginated(
            api.list_retention_determinations(
                env["manager"], params={"evidence_item_id": item["id"]}
            )
        )
        assert meta["total_count"] == 2
        final = rows[1]
        assert final["resolved_basis"] == "FINAL"
        assert final["anchor_at"] == "2026-11-30T00:00:00.000Z"
        assert final["statute_days_applied"] == 0
        # The intake-plus-90-days floor of 2026-10-30 is earlier, so it does not bind.
        assert final["computed_release_at"] == "2026-11-30T00:00:00.000Z"
        assert final["superseded"] is False

    def test_matured_release_promotes_the_item_and_the_room_counter_at_once(self, api):
        """The item reaches DISPOSAL_ELIGIBLE inside the adjudication request itself.

        PRD 3.4: "Any item whose newly computed `retention_release_at` is at or before
        the current instant and whose `custody_state` is `STORED` continues in the same
        request from `RETAINED` to `DISPOSAL_ELIGIBLE`, and the room's
        `disposal_eligible_count` and `posture` are recomputed as a consequence."
        PRD 3.4: "It is permitted only when the case's `undisposed_item_count` — the
        number of its items whose `disposition_state` is anything other than `DISPOSED` —
        has reached 0; otherwise the request is refused with
        `ERR_CASE_HAS_UNDISPOSED_ITEMS`."

        Design: Difficulty/transitive_cascade/case_adjudicate_cascades_to_disposal_eligibility_counter
        """
        env = setup_difficulty_base()
        item = self._charged_case_past_the_floor(env)

        adjudicate_case(env, env["case2_id"])

        after = read_item(env, item["id"])
        assert after["disposition_state"] == "DISPOSAL_ELIGIBLE"
        assert after["custody_state"] == "STORED"
        assert after["retention_release_at"] == "2026-11-30T00:00:00.000Z"
        assert read_room(env)["disposal_eligible_count"] == 1
        case = read_case(env, env["case2_id"])
        assert case["item_count"] == 1
        assert case["undisposed_item_count"] == 1
