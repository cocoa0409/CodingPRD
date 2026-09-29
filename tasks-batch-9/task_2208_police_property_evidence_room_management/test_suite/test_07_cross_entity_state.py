"""Gates that live on a neighbouring entity: the case, the bin and the owner claim."""

from test_helpers import (
    ApiErrorId,
    adjudicate_case,
    authorize_order,
    charge_case,
    close_audit,
    execute_payload,
    file_claim,
    issue_notice,
    log_and_store_item,
    open_order,
    read_case,
    read_item,
    read_location,
    read_room,
    release_transfer,
    request_transfer,
    retention_determination_payload,
    return_payload,
    return_transfer,
    run_sweep,
    set_clock,
    setup_difficulty_base,
    setup_started_audit,
    validate_error,
    validate_paginated,
    validate_success,
    verify_claim,
)


class TestFinalRetentionNeedsAnAdjudicatedCase:
    """The FINAL variant is gated on the parent case, not on the item."""

    def _charged_but_unadjudicated_item(self, env):
        """A pry bar stored in G-01 whose case has been charged only."""
        item = log_and_store_item(
            env,
            case_id=env["case1_id"],
            location_id=env["loc_g_id"],
            item_description="Burglary pry bar",
            category="GENERAL",
            packaging_type="RIGID_BOX",
            appraised_value_cents=4000,
            seized_at="2026-07-31T19:00:00Z",
        )
        charge_case(env, env["case1_id"])
        set_clock("2026-09-15T00:00:00Z")
        return item

    def test_final_basis_is_refused_while_the_case_is_only_charged(self, api):
        """The case state, not the item state, is what the request fails on.

        PRD 3.4: "Under the `FINAL` variant — which requires the case to have reached
        `ADJUDICATED`, and which is otherwise refused with `ERR_CASE_STATE_INVALID` — the
        `anchor_at` is the case's `adjudicated_at`, and the `statute_days_applied` is the
        statute's `appeal_window_days` plus half of `statutory_retention_days` rounded up
        to the next whole day."
        PRD 3.4: "Under the `PRELIMINARY` variant the `anchor_at` is the item's
        `intake_at`, the `statute_days_applied` is the statute's full
        `statutory_retention_days`, and the release instant is the anchor plus those whole
        days; the appeal window and the ninety-day floor are both ignored."

        Design: Difficulty/cross_entity_state_dependency/final_retention_requires_case_adjudicated
        """
        env = setup_difficulty_base()
        item = self._charged_but_unadjudicated_item(env)
        before = read_item(env, item["id"])

        response = api.create_retention_determination(
            retention_determination_payload(item["id"], "FINAL", before["version"]),
            env["manager"],
        )

        validate_error(response, ApiErrorId.ERR_CASE_STATE_INVALID, 409)
        assert read_case(env, env["case1_id"])["status"] == "CHARGED"
        rows, meta = validate_paginated(
            api.list_retention_determinations(
                env["manager"], params={"evidence_item_id": item["id"]}
            )
        )
        # Only the determination written at intake exists.
        assert meta["total_count"] == 1
        assert rows[0]["resolved_basis"] == "PRELIMINARY"
        after = read_item(env, item["id"])
        assert after["retention_release_at"] == "2027-08-01T00:00:00.000Z"
        assert after["retention_basis"] == "PRELIMINARY"
        assert after["version"] == before["version"]

    def test_the_identical_request_succeeds_once_the_case_is_adjudicated(self, api):
        """Adjudication supplies the anchor the FINAL variant needs.

        PRD 3.4: "The candidate release instant is the anchor plus those days; a floor
        instant is computed as the item's `intake_at` plus 90 days; and the release
        instant actually applied is the later of the candidate and the floor."
        PRD 3.4: "The determination stores its `resolved_basis`, `anchor_at`,
        `statute_days_applied` and `computed_release_at`; the previously current
        determination for that item has its `superseded` flag set to true; the item's
        `retention_release_at` and `retention_basis` are rewritten; a chain entry with
        `event_type` of `RETENTION_SET` is appended; and the item's `version` is
        incremented by 1."

        Design: Difficulty/cross_entity_state_dependency/final_retention_requires_case_adjudicated
        """
        env = setup_difficulty_base()
        item = self._charged_but_unadjudicated_item(env)
        api.create_retention_determination(
            retention_determination_payload(
                item["id"], "FINAL", read_item(env, item["id"])["version"]
            ),
            env["manager"],
        )

        adjudicate_case(env, env["case1_id"])
        current_version = read_item(env, item["id"])["version"]
        determination = validate_success(
            api.create_retention_determination(
                retention_determination_payload(item["id"], "FINAL", current_version),
                env["manager"],
            ),
            201,
        )

        assert determination["resolved_basis"] == "FINAL"
        assert determination["anchor_at"] == "2026-09-15T00:00:00.000Z"
        # 30 appeal days plus half of 365 rounded up to 183 whole days.
        assert determination["statute_days_applied"] == 213
        assert determination["computed_release_at"] == "2027-04-16T00:00:00.000Z"
        assert determination["superseded"] is False
        after = read_item(env, item["id"])
        assert after["retention_release_at"] == "2027-04-16T00:00:00.000Z"
        assert after["version"] == current_version + 1


class TestReturnBlockedByASealedBin:
    """A checked-out item cannot come home while its bin is sealed for audit."""

    def _released_item_whose_bin_is_sealed(self, env):
        """A drive signed out to the investigator, then an audit seals G-01 behind it."""
        item = log_and_store_item(
            env,
            case_id=env["case1_id"],
            location_id=env["loc_g_id"],
            item_description="Surveillance drive",
            category="GENERAL",
            packaging_type="SEALED_ENVELOPE",
            appraised_value_cents=6000,
            seized_at="2026-07-31T20:00:00Z",
        )
        transfer = request_transfer(
            env,
            item["id"],
            env["inv_id"],
            "INVESTIGATIVE_REVIEW",
            "2026-08-02T09:00:00Z",
            "2026-08-07T09:00:00Z",
            headers=env["inv_headers"],
        )
        release_transfer(env, transfer["id"], "T.NG-2026-08-02")
        location = read_location(env, env["loc_g_id"])
        session = setup_started_audit(
            env,
            env["loc_g_id"],
            location["version"],
            scheduled_start_at="2026-08-04T09:00:00Z",
            scheduled_end_at="2026-08-04T17:00:00Z",
        )
        return item, transfer, session

    def test_the_sealed_bin_refuses_the_return_and_changes_nothing(self, api):
        """The gate is on the location, and the checked-out item is not even expected.

        PRD 3.8: "A sealed location blocks storage assignment into it, release out of it
        and return into it, all with `ERR_LOCATION_SEALED`."
        PRD 3.5: "Return, also an `EvidenceTechnician` action, requires a
        `receipt_signature` and accepts a transfer whose `status` is either `RELEASED` or
        `OVERDUE`, provided the item is currently `CHECKED_OUT` and its storage location
        is `OPEN` rather than sealed."
        PRD 3.5: "The bin is not freed: `occupied_slots` stays exactly as it was, because
        the slot remains reserved for the absent item."

        Design: Difficulty/cross_entity_state_dependency/return_blocked_while_storage_location_sealed
        """
        env = setup_difficulty_base()
        item, transfer, session = self._released_item_whose_bin_is_sealed(env)

        response = api.return_transfer(
            transfer["id"], return_payload("I.COLE-2026-08-04"), env["tech_headers"]
        )

        validate_error(response, ApiErrorId.ERR_LOCATION_SEALED, 409)
        assert read_location(env, env["loc_g_id"])["status"] == "SEALED_FOR_AUDIT"
        # The item was CHECKED_OUT when the snapshot was taken, so it is not expected.
        assert session["expected_item_count"] == 0
        still_out = validate_success(
            api.get_custody_transfer(transfer["id"], env["manager"]), 200
        )
        assert still_out["status"] == "RELEASED"
        assert still_out["returned_at"] is None
        assert read_item(env, item["id"])["custody_state"] == "CHECKED_OUT"
        assert read_location(env, env["loc_g_id"])["occupied_slots"] == 1

    def test_closing_the_audit_lets_the_identical_return_through(self, api):
        """Unsealing the bin is the only thing that changes between the two attempts.

        PRD 3.8: "Closing stamps `closed_at`, returns the location
        `SEALED_FOR_AUDIT → OPEN`, clears `sealed_by_audit_session_id`, increments the
        location's `version` by 1, decrements the room's `sealed_location_count` and
        recomputes its `posture`."
        PRD 3.5: "It moves the transfer to `RETURNED`, stamps `returned_at` from the
        logical clock — which closes the custody interval for overlap purposes — moves the
        item's custody dimension `CHECKED_OUT → STORED`, clears `current_holder_id`,
        appends a `RECEIPT` chain entry carrying the `receipt_signature` in
        `signature_ref`, and decrements both the receiving custodian's `open_escort_count`
        and the item's `open_transfer_count`."

        Design: Difficulty/cross_entity_state_dependency/return_blocked_while_storage_location_sealed
        """
        env = setup_difficulty_base()
        item, transfer, session = self._released_item_whose_bin_is_sealed(env)
        api.return_transfer(
            transfer["id"], return_payload("I.COLE-2026-08-04"), env["tech_headers"]
        )

        close_audit(env, session["id"])
        assert read_location(env, env["loc_g_id"])["status"] == "OPEN"
        assert read_room(env)["sealed_location_count"] == 0
        returned = return_transfer(env, transfer["id"], "I.COLE-2026-08-04")

        assert returned["status"] == "RETURNED"
        after = read_item(env, item["id"])
        assert after["custody_state"] == "STORED"
        assert after["current_holder_id"] is None
        assert read_location(env, env["loc_g_id"])["occupied_slots"] == 1


class TestReturnToOwnerNeedsAVerifiedClaim:
    """Execution of a return-to-owner order is gated on the owner claim."""

    def _authorized_order_over_a_filed_claim(self, env):
        """A found satchel, eligible for disposal, with a claim only filed so far."""
        item = log_and_store_item(
            env,
            case_id=env["case2_id"],
            location_id=env["loc_g_id"],
            item_description="Found leather satchel",
            category="GENERAL",
            packaging_type="PAPER_BAG",
            appraised_value_cents=25000,
            seized_at="2026-07-27T11:00:00Z",
            is_found_property=True,
        )
        charge_case(env, env["case2_id"])
        adjudicate_case(env, env["case2_id"])
        set_clock("2026-10-30T00:00:00Z")
        run_sweep(env)
        claim = issue_notice(env, item["id"], claimant_name="Marta Silva",
                             claimant_contact="418 Bay Street, Apt 5",
                             notice_method="CERTIFIED_MAIL")
        file_claim(env, claim["id"], "PROOF-2026-3311")
        order = open_order(
            env, item["id"], "RETURN_TO_OWNER", owner_claim_id=claim["id"]
        )
        authorized = authorize_order(env, order["id"], "CO-2026-6640")
        return item, claim, authorized

    def test_execute_is_refused_while_the_claim_is_only_filed(self, api):
        """The claim, not the order, is what holds the execution back.

        PRD 3.7: "Execution belongs solely to the `PropertyRoomManager`, who supplies the
        `executed_by_custodian_id` and the `witness_custodian_id`."
        PRD 3.6: "The base period is 90 days when the item's `is_found_property` flag is
        true, and 30 days otherwise."
        PRD 3.6: "Publication earns a further 15 days on top, because a notice in a
        newspaper reaches a claimant more slowly than a certified letter or a
        conversation; `CERTIFIED_MAIL` and `IN_PERSON` add nothing."

        Design: Difficulty/cross_entity_state_dependency/return_to_owner_execute_requires_verified_claim
        """
        env = setup_difficulty_base()
        item, claim, order = self._authorized_order_over_a_filed_claim(env)
        assert claim["claim_deadline_at"] == "2027-01-28T00:00:00.000Z"

        response = api.execute_order(
            order["id"], execute_payload(env["tech2_id"], env["inv_id"]), env["manager"]
        )

        validate_error(response, ApiErrorId.ERR_CLAIM_NOT_VERIFIED, 409)
        filed = validate_success(api.get_owner_claim(claim["id"], env["manager"]), 200)
        assert filed["status"] == "CLAIM_FILED"
        after = validate_success(api.get_disposition_order(order["id"], env["manager"]), 200)
        assert after["status"] == "AUTHORIZED"
        assert after["executed_at"] is None
        assert read_item(env, item["id"])["custody_state"] == "STORED"

    def test_verifying_the_claim_lets_the_release_to_the_claimant_complete(self, api):
        """Verification unlocks the order and hands the item to the claimant.

        PRD 3.6: "A `PropertyRoomManager` then verifies the filed claim, moving it
        `CLAIM_FILED → VERIFIED` and stamping `verified_at`; verification requires the
        room not to be `LOCKED_DOWN`."
        PRD 3.7: "The item is retired on both axes at once — `custody_state` to `PURGED`
        and `disposition_state` to `DISPOSED` — its storage location's `occupied_slots` is
        decremented by 1, the room's `disposal_eligible_count` is decremented, the case's
        `undisposed_item_count` is decremented, a chain entry with `event_type` of
        `DISPOSITION_EXECUTED` is appended, and for a `RETURN_TO_OWNER` order the owner
        claim moves `VERIFIED → RELEASED`."
        PRD 3.7: "Non-auction dispositions have nothing to sell, so execution settles them
        immediately: an order whose `type` is `RETURN_TO_OWNER`, `DESTRUCTION` or
        `CONVERSION` continues `EXECUTED → SETTLED` inside the same request with
        `settled_net_proceeds_cents` of 0, `settlement_status` of `NONE`, and `settled_at`
        stamped from the logical clock."

        Design: Difficulty/cross_entity_state_dependency/return_to_owner_execute_requires_verified_claim
        """
        env = setup_difficulty_base()
        item, claim, order = self._authorized_order_over_a_filed_claim(env)
        api.execute_order(
            order["id"], execute_payload(env["tech2_id"], env["inv_id"]), env["manager"]
        )

        verified = verify_claim(env, claim["id"])
        assert verified["status"] == "VERIFIED"
        assert verified["verified_at"] == "2026-10-30T00:00:00.000Z"
        executed = validate_success(
            api.execute_order(
                order["id"],
                execute_payload(env["tech2_id"], env["inv_id"]),
                env["manager"],
            ),
            200,
        )

        assert executed["status"] == "SETTLED"
        assert executed["settled_net_proceeds_cents"] == 0
        assert executed["settlement_status"] == "NONE"
        released = validate_success(api.get_owner_claim(claim["id"], env["manager"]), 200)
        assert released["status"] == "RELEASED"
        final_item = read_item(env, item["id"])
        assert final_item["custody_state"] == "PURGED"
        assert final_item["disposition_state"] == "DISPOSED"
        assert read_location(env, env["loc_g_id"])["occupied_slots"] == 0
        assert read_case(env, env["case2_id"])["undisposed_item_count"] == 0
