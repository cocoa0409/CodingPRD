"""Two-axis item state and the adjudication/appeal cycle on a case."""

from test_helpers import (
    adjudicate_case,
    charge_case,
    log_and_store_item,
    open_appeal,
    read_case,
    read_item,
    read_location,
    request_transfer,
    release_transfer,
    resolve_appeal,
    return_transfer,
    set_clock,
    setup_difficulty_base,
    validate_paginated,
    validate_success,
)


class TestParallelCustodyAndDispositionDimensions:
    """The custody axis and the disposition axis advance independently."""

    def _item_out_at_the_laboratory(self, env):
        """A stored item, adjudicated, then released to the laboratory analyst."""
        item = log_and_store_item(
            env,
            case_id=env["case1_id"],
            location_id=env["loc_g_id"],
            item_description="Latent print card set",
            category="GENERAL",
            packaging_type="SEALED_ENVELOPE",
            appraised_value_cents=1000,
            seized_at="2026-07-31T10:00:00Z",
        )
        charge_case(env, env["case1_id"])
        set_clock("2026-09-15T00:00:00Z")
        adjudicate_case(env, env["case1_id"])
        transfer = request_transfer(
            env,
            item["id"],
            env["lab_id"],
            "LAB_ANALYSIS",
            "2026-09-16T00:00:00Z",
            "2026-09-20T00:00:00Z",
            headers=env["lab_headers"],
        )
        released = release_transfer(env, transfer["id"], "T.NG-2026-09-16")
        return item, released

    def test_opening_an_appeal_leaves_the_checked_out_custody_state_untouched(self, api):
        """The disposition axis moves to court hold while the item stays signed out.

        PRD 3.5: "Release is an `EvidenceTechnician` action and drives two state
        machines at once, moving the transfer `REQUESTED → RELEASED` and the item's
        custody dimension `STORED → CHECKED_OUT`."
        PRD 3.4: "Every non-`DISPOSED` item of the case moves on its disposition axis to
        `COURT_HOLD` — from `RETAINED` or from `DISPOSAL_ELIGIBLE` alike — with
        `retention_release_at` set to null and `retention_basis` set to `COURT_HOLD`, and
        a fresh determination recording a `resolved_basis` of `COURT_HOLD` and a null
        `computed_release_at` is written per item while the prior determination is
        superseded, accompanied by a `RETENTION_SET` chain entry."
        PRD 3.5: "The bin is not freed: `occupied_slots` stays exactly as it was, because
        the slot remains reserved for the absent item."

        Design: Difficulty/non_linear_state_machine/evidence_item_parallel_custody_and_disposition_dimensions_advance_independently
        """
        env = setup_difficulty_base()
        item, released = self._item_out_at_the_laboratory(env)

        after_release = read_item(env, item["id"])
        assert after_release["custody_state"] == "CHECKED_OUT"
        assert after_release["disposition_state"] == "RETAINED"
        assert after_release["retention_release_at"] == "2027-04-16T00:00:00.000Z"
        assert after_release["current_holder_id"] == env["lab_id"]
        assert read_location(env, env["loc_g_id"])["occupied_slots"] == 1

        open_appeal(env, env["case1_id"])

        mid = read_item(env, item["id"])
        assert mid["custody_state"] == "CHECKED_OUT"
        assert mid["disposition_state"] == "COURT_HOLD"
        assert mid["retention_release_at"] is None
        assert mid["retention_basis"] == "COURT_HOLD"
        assert read_location(env, env["loc_g_id"])["occupied_slots"] == 1

    def test_returning_the_item_leaves_the_court_hold_disposition_untouched(self, api):
        """The custody axis comes home while the disposition axis stays at court hold.

        PRD 3.5: "It moves the transfer to `RETURNED`, stamps `returned_at` from the
        logical clock — which closes the custody interval for overlap purposes — moves
        the item's custody dimension `CHECKED_OUT → STORED`, clears `current_holder_id`,
        appends a `RECEIPT` chain entry carrying the `receipt_signature` in
        `signature_ref`, and decrements both the receiving custodian's
        `open_escort_count` and the item's `open_transfer_count`."
        PRD 2.7: "The consequence is that an item signed out to a laboratory keeps its
        bin reserved — releasing it does not free a slot — whereas an item that goes
        `MISSING` releases its slot immediately, and recovering it consumes a slot
        again."

        Design: Difficulty/non_linear_state_machine/evidence_item_parallel_custody_and_disposition_dimensions_advance_independently
        """
        env = setup_difficulty_base()
        item, released = self._item_out_at_the_laboratory(env)
        open_appeal(env, env["case1_id"])

        returned = return_transfer(env, released["id"], "L.RUIZ-2026-09-16")

        assert returned["status"] == "RETURNED"
        final = read_item(env, item["id"])
        assert final["custody_state"] == "STORED"
        assert final["disposition_state"] == "COURT_HOLD"
        assert final["retention_release_at"] is None
        assert final["current_holder_id"] is None
        assert final["open_transfer_count"] == 0
        assert read_location(env, env["loc_g_id"])["occupied_slots"] == 1


class TestAdjudicationAppealCycle:
    """The ADJUDICATED to APPEAL_PENDING to ADJUDICATED loop re-anchors retention."""

    def _adjudicated_item(self, env):
        """One general item under a charged, then adjudicated, case."""
        item = log_and_store_item(
            env,
            case_id=env["case1_id"],
            location_id=env["loc_g_id"],
            item_description="Ledger notebook",
            category="GENERAL",
            packaging_type="PAPER_BAG",
            appraised_value_cents=2000,
            seized_at="2026-07-31T11:00:00Z",
        )
        charge_case(env, env["case1_id"])
        set_clock("2026-09-15T00:00:00Z")
        adjudicate_case(env, env["case1_id"])
        return item

    def test_second_pass_through_the_loop_produces_a_strictly_later_release(self, api):
        """Release moves 2027-04-16, then null, then 2027-07-02 as the anchor advances.

        PRD 3.4: "Resolving the appeal, again a `CourtClerk` action, closes the cycle:
        the case moves `APPEAL_PENDING → ADJUDICATED`, `adjudicated_at` is re-stamped to
        the current instant and `appeal_opened_at` is cleared."
        PRD 3.4: "Every non-`DISPOSED` item leaves `COURT_HOLD` and returns to
        `RETAINED` with a new `FINAL` determination computed against the new anchor;
        because the anchor has moved forward, the second pass necessarily produces a
        strictly later release instant than the first."
        PRD 3.4: "The `ADJUDICATED → APPEAL_PENDING → ADJUDICATED` cycle may repeat
        without limit, re-anchoring retention on every pass."

        Design: Difficulty/non_linear_state_machine/case_adjudicated_appeal_pending_cycle_recomputes_retention_twice
        """
        env = setup_difficulty_base()
        item = self._adjudicated_item(env)
        first_release = read_item(env, item["id"])["retention_release_at"]
        assert first_release == "2027-04-16T00:00:00.000Z"

        appealed = open_appeal(env, env["case1_id"])
        assert appealed["status"] == "APPEAL_PENDING"
        assert appealed["appeal_opened_at"] == "2026-09-15T00:00:00.000Z"
        assert read_item(env, item["id"])["retention_release_at"] is None
        set_clock("2026-12-01T00:00:00Z")
        resolved = resolve_appeal(env, env["case1_id"])

        assert resolved["status"] == "ADJUDICATED"
        assert resolved["adjudicated_at"] == "2026-12-01T00:00:00.000Z"
        assert resolved["appeal_opened_at"] is None
        after = read_item(env, item["id"])
        assert after["retention_release_at"] == "2027-07-02T00:00:00.000Z"
        assert after["retention_basis"] == "FINAL"
        assert after["retention_release_at"] > first_release
        assert after["disposition_state"] == "RETAINED"

    def test_each_pass_writes_a_determination_and_supersedes_the_previous_one(self, api):
        """Four determinations accumulate and exactly one remains current.

        PRD 3.4: "Under the `FINAL` variant — which requires the case to have reached
        `ADJUDICATED`, and which is otherwise refused with `ERR_CASE_STATE_INVALID` — the
        `anchor_at` is the case's `adjudicated_at`, and the `statute_days_applied` is the
        statute's `appeal_window_days` plus half of `statutory_retention_days` rounded up
        to the next whole day."
        PRD 3.4: "If the item's `disposition_state` is `COURT_HOLD`, or its case's
        `status` is `APPEAL_PENDING`, the resolved basis is `COURT_HOLD`, the release
        instant is null and `statute_days_applied` is 0."
        PRD 3.4: "The determination stores its `resolved_basis`, `anchor_at`,
        `statute_days_applied` and `computed_release_at`; the previously current
        determination for that item has its `superseded` flag set to true; the item's
        `retention_release_at` and `retention_basis` are rewritten; a chain entry with
        `event_type` of `RETENTION_SET` is appended; and the item's `version` is
        incremented by 1."

        Design: Difficulty/non_linear_state_machine/case_adjudicated_appeal_pending_cycle_recomputes_retention_twice
        """
        env = setup_difficulty_base()
        item = self._adjudicated_item(env)
        open_appeal(env, env["case1_id"])
        set_clock("2026-12-01T00:00:00Z")
        resolve_appeal(env, env["case1_id"])

        rows, meta = validate_paginated(
            api.list_retention_determinations(
                env["manager"], params={"evidence_item_id": item["id"]}
            )
        )

        assert meta["total_count"] == 4
        assert [row["resolved_basis"] for row in rows] == [
            "PRELIMINARY",
            "FINAL",
            "COURT_HOLD",
            "FINAL",
        ]
        current = [row for row in rows if row["superseded"] is False]
        assert len(current) == 1
        court_hold = rows[2]
        assert court_hold["computed_release_at"] is None
        assert court_hold["statute_days_applied"] == 0
        last = rows[3]
        assert last is current[0]
        assert last["anchor_at"] == "2026-12-01T00:00:00.000Z"
        # 30 appeal days plus half of 365 rounded up to 183 whole days.
        assert last["statute_days_applied"] == 213
        assert last["computed_release_at"] == "2027-07-02T00:00:00.000Z"
        case = read_case(env, env["case1_id"])
        assert case["status"] == "ADJUDICATED"
        assert validate_success(
            api.get_evidence_item(item["id"], env["manager"]), 200
        )["retention_basis"] == "FINAL"
