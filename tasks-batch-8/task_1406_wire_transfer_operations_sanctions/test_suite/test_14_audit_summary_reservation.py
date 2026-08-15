"""The audit trail, the wire summary computed read, and reservation
conservation across every lifecycle exit."""
from test_helpers import (
    assert_audit_log_entry,
    create_approved_wire,
    create_submitted_wire,
    create_wire,
    dual_approve_wire,
    get_account,
    get_wire,
    place_fraud_hold,
    release_wire,
    repair_wire,
    setup_wire_room,
    simulate_hit,
    validate_paginated,
    validate_success,
)
from test_helpers import TEST_USERS

ADMIN = TEST_USERS["wire_ops_admin_headers"]
OPERATOR = TEST_USERS["wire_operator_headers"]
APPROVER_1 = TEST_USERS["wire_approver_headers"]
AUDITOR = TEST_USERS["auditor_headers"]
SCREENER = TEST_USERS["sanctions_screener_headers"]


class TestAuditLogShape:
    def test_audit_log_entries_immutable_and_append_only(self, api):
        """PRD §2.4: "An `AuditLogEntry` is append-only evidence: it carries
        `id` and `created_at` only, and has **no** `updated_at` and **no**
        `version` field, because an audit record is never mutated after it is
        written. Each entry records the `actor_user_id` and `actor_role` of
        the actor, an `action` label such as `wire.approve` or
        `sanctions.release`, the `entity_type` and `entity_id` of the affected
        resource (the latter serving identity only, carrying no business
        semantics), a `wire_id` whenever the action concerns a wire (null
        otherwise), and a free-text `detail` field that includes before/after
        states."
        PRD §3.2: "The initiator's identity is stamped onto the wire as
        `initiated_by`, and initiation is audit-logged."
        PRD §3.5: "Every cancellation path is audit-logged as `wire.cancel`."

        Initiating then cancelling a wire appends wire-scoped entries whose
        shape carries identity and creation time only.

        Design: Corner/entities/audit_log_entries_immutable_and_append_only
        """
        room = setup_wire_room()
        wire = create_wire(room["account"]["id"], room["beneficiary"]["id"],
                           100000, purpose="audit probe")
        validate_success(api.cancel_wire(wire["id"], OPERATOR), 200)

        entries, _meta = validate_paginated(
            api.list_audit_logs(AUDITOR, params={"wire_id": wire["id"]}))
        assert len(entries) >= 2, (
            f"wire.initiate and wire.cancel are both recorded, got "
            f"{len(entries)}")
        for entry in entries:
            assert_audit_log_entry(entry)
            assert entry["wire_id"] == wire["id"]
        actions = {entry["action"] for entry in entries}
        assert "wire.initiate" in actions
        assert "wire.cancel" in actions


class TestWireSummary:
    def test_wire_summary_computed_read(self, api):
        """PRD §3.11: "For an operator console, the wire summary is a computed
        read that assembles, in one document, the wire itself plus its
        `approvals` count (non-superseded records of the current repair
        round), `open_hits`, `open_holds`, `recalls`, `open_fees`, and the
        live `reserved_cents` amount. It is a read-only projection: it mutates
        nothing and takes no inputs beyond the path."
        PRD §3.3: "when screening lands a wire in `REVIEW` while the wire is
        already `APPROVED` and carrying no hold, the wire's `hold_reason_code`
        is set to `SANCTIONS_HOLD`; an existing `FRAUD_HOLD` is never
        overwritten."

        One APPROVED wire carrying two approvals, one open fraud hold, and one
        open sanctions hit summarizes as 2/1/1/0/0 with its full reservation.

        Design: Corner/endpoints/wire_summary_computed_read
        """
        room = setup_wire_room(business_date="2026-09-24")
        wire = create_approved_wire(
            room["account"]["id"], room["beneficiary"]["id"], "2026-09-24",
            300000, purpose="summary probe")
        place_fraud_hold(wire["id"], reason_code="ACCOUNT_TAKEOVER",
                         note="ato suspicion")
        simulate_hit(wire["id"], matched_list="INTERNAL_WATCH",
                     matched_party="EP Ben", match_score=58)

        summary = validate_success(api.get_wire_summary(wire["id"], ADMIN), 200)
        assert summary["wire"]["id"] == wire["id"]
        assert summary["approvals"] == 2, (
            f"non-superseded approvals of the current round, got "
            f"{summary['approvals']}")
        assert summary["open_hits"] == 1
        assert summary["open_holds"] == 1
        assert summary["recalls"] == 0
        assert summary["open_fees"] == 0
        assert summary["reserved_cents"] == 300000, (
            f"the reservation survives approval and holds, got "
            f"{summary['reserved_cents']}")

        wire_after = get_wire(wire["id"])
        assert wire_after["hold_reason_code"] == "FRAUD_HOLD", (
            "the fraud hold is never overwritten by the sanctions review")


class TestReservationConservation:
    def test_reservation_conservation_across_lifecycle_exits(self, api):
        """PRD §2.6: "Submission creates a reservation: the wire's
        `reservation_active` becomes true and the wire's `amount_cents` is
        added to the ordering account's `daily_reserved_cents`. Release
        converts the reservation: at the moment the release call dispatches to
        the network, the reservation is deactivated and the same
        `amount_cents` moves from `daily_reserved_cents` into
        `daily_released_cents`, so principal counts exactly once against the
        limit on the current business date. Any path that ends a wire before
        execution — rejection, cancellation from `PENDING_APPROVAL` or
        `REPAIR`, or a sanctions confirmation that rejects the wire —
        releases the reservation by subtracting the wire's `amount_cents` (the
        current, post-repair amount where a repair changed it) from
        `daily_reserved_cents` and setting `reservation_active` to false."
        PRD §3.4: "When the repair changes `amount_cents`, the account's
        `daily_reserved_cents` is re-based by the delta — the new amount minus
        the old — while `reservation_active` stays true"

        Three wires totalling 1000000 reserved exit four different ways —
        reject (300000), release-conversion (500000), repair re-base
        (200000 -> 250000), cancel from REPAIR — and the reserved tally is
        exact after every step.

        Design: Difficulty/compensating_invariant/reservation_conservation_across_lifecycle_exits
        """
        room = setup_wire_room(business_date="2026-08-19")
        account = room["account"]
        beneficiary = room["beneficiary"]

        wire_1 = create_submitted_wire(
            account["id"], beneficiary["id"], "2026-08-19", 500000)
        wire_2 = create_submitted_wire(
            account["id"], beneficiary["id"], "2026-08-19", 300000)
        wire_3 = create_submitted_wire(
            account["id"], beneficiary["id"], "2026-08-19", 200000)
        assert get_account(account["id"])["daily_reserved_cents"] == 1000000

        # Exit 1: rejection compensates exactly.
        validate_success(api.reject_wire(
            wire_2["id"], {"reason": "duplicate instruction"}, APPROVER_1), 200)
        assert get_account(account["id"])["daily_reserved_cents"] == 700000

        # Exit 2: release converts reserved into released, counted once.
        dual_approve_wire(wire_1["id"])
        released = release_wire(wire_1["id"])
        assert released["status"] == "EXECUTED"
        account_mid = get_account(account["id"])
        assert account_mid["daily_reserved_cents"] == 200000
        assert account_mid["daily_released_cents"] == 500000

        # Exit 3a: repair re-bases by the delta, not a re-add.
        repaired = repair_wire(wire_3["id"], amount_cents=250000)
        assert repaired["amount_cents"] == 250000
        assert get_account(account["id"])["daily_reserved_cents"] == 250000

        # Exit 3b: cancel from REPAIR releases at the current amount.
        validate_success(api.cancel_wire(wire_3["id"], OPERATOR), 200)
        account_final = get_account(account["id"])
        assert account_final["daily_reserved_cents"] == 0
        assert account_final["daily_released_cents"] == 500000

    def test_reservation_conservation_sanctions_confirm_exit(self, api):
        """PRD §2.6: "Any path that ends a wire before execution — rejection,
        cancellation from `PENDING_APPROVAL` or `REPAIR`, or a sanctions
        confirmation that rejects the wire — releases the reservation by
        subtracting the wire's `amount_cents` (the current, post-repair amount
        where a repair changed it) from `daily_reserved_cents` and setting
        `reservation_active` to false."

        Two wires hold 500000 reserved; a sanctions confirmation on the
        300000 wire releases exactly its share, leaving the other wire's
        reservation untouched.

        Design: Difficulty/compensating_invariant/reservation_conservation_across_lifecycle_exits
        """
        room = setup_wire_room(business_date="2026-08-19")
        account = room["account"]
        beneficiary = room["beneficiary"]

        wire_a = create_submitted_wire(
            account["id"], beneficiary["id"], "2026-08-19", 300000)
        wire_b = create_submitted_wire(
            account["id"], beneficiary["id"], "2026-08-19", 200000)
        assert get_account(account["id"])["daily_reserved_cents"] == 500000

        hit = simulate_hit(wire_a["id"], matched_list="OFAC_SDN",
                           matched_party="Vendor Eighteen", match_score=95)
        validate_success(api.confirm_sanctions_hit(
            hit["id"], {"rationale": "true match"}, SCREENER), 200)

        wire_a_after = get_wire(wire_a["id"])
        assert wire_a_after["status"] == "REJECTED"
        assert wire_a_after["reservation_active"] is False

        account_after = get_account(account["id"])
        assert account_after["daily_reserved_cents"] == 200000, (
            f"only the confirmed wire's reservation is released, got "
            f"{account_after['daily_reserved_cents']}")
        wire_b_after = get_wire(wire_b["id"])
        assert wire_b_after["status"] == "PENDING_APPROVAL"
        assert wire_b_after["reservation_active"] is True
