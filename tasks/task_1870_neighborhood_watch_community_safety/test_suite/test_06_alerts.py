"""Alerts: fan-out rounding, acknowledgement posture, scheduling gates, OCC,
and the materials-ledger conservation across send and recall."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    ack_alert_payload,
    add_block,
    assert_alert,
    create_alert,
    create_alert_payload,
    create_watch_group,
    get_group_version,
    issue_materials,
    make_member_headers,
    queue_alert,
    register_block,
    send_alert_at,
    send_group_alert,
    set_clock,
    setup_group_with_registered_block,
    setup_operational_group,
    validate_error,
    validate_success,
)

COORD = TEST_USERS["coordinator_headers"]


def _phone_tree_group(api):
    """OPERATIONAL group: two REGISTERED blocks, each with exactly one ACTIVE
    PHONE_TREE member (who is also the block's captain)."""
    return setup_operational_group(
        "Fanout Watch", "PCT4",
        member_channels=("PHONE_TREE", "PHONE_TREE"),
        train_member_indexes=(0, 1),
        badge_number="B400",
        street_segments=("10-20 Elm St", "30-40 Elm St"),
    )


class TestFanoutRoundingOrder:
    def test_per_block_ceil_then_sum(self, api):
        """PRD §3.4: "The rounding order is pinned and observable: two blocks
        each holding a single `PHONE_TREE` member yield 3 plus 3, that is 6
        recipients, because each block's raw 2.5 is rounded up individually;
        collapsing the sum first would wrongly produce 5."
        PRD §2.9: "The alert fan-out uses ceiling rounding to whole recipients,
        applied per block before any cross-block summation, and a final ceiling
        when converting recipients to printed flyers."

        Design: Difficulty/combinatorial_formula/alert_fanout_per_block_ceil_order_mode_b
        """
        ws = _phone_tree_group(api)
        alert = create_alert(ws["group"]["id"], scheduled_send_at="2026-08-09T12:00:00Z")
        queue_alert(alert["id"])
        sent = send_alert_at(alert["id"], "2026-08-09T12:00:00Z")
        assert sent["distribution_status"] == "SENT"
        assert sent["recipient_count"] == 6, (
            "ceil(2.5) + ceil(2.5) = 3 + 3 = 6; the forbidden sum-then-ceil "
            "order would produce ceil(5.0) = 5"
        )

    def test_send_charges_flyers_per_ten_recipients(self, api):
        """PRD §3.4: "The same transition charges the materials ledger: the group
        is deemed to print one flyer per 10 recipients, rounded up, and
        `materials_inventory_count` increases by that flyer quantity."

        Design: Difficulty/combinatorial_formula/alert_fanout_per_block_ceil_order_mode_b
        """
        ws = _phone_tree_group(api)
        assert ws["group"]["materials_inventory_count"] == 0
        sent = send_group_alert(ws["group"]["id"], "2026-08-09T12:00:00Z")
        assert sent["recipient_count"] == 6

        group = validate_success(api.get_watch_group(ws["group"]["id"], COORD))
        assert group["materials_inventory_count"] == 1, (
            "ceil(6 recipients / 10) = 1 flyer charged to the ledger"
        )


class TestFanoutInputSet:
    def test_suspended_members_excluded_from_fanout(self, api):
        """PRD §3.4: "Only `ACTIVE` members count; `SUSPENDED` and `WITHDRAWN`
        members are excluded."

        Design: Corner/calculations/alert_fanout_input_set_excludes_suspended_members
        """
        ws = setup_operational_group(
            "Filter Watch", "C02",
            member_channels=("SMS", "SMS", "SMS"),
            train_member_indexes=(0,),
            badge_number="BC02",
        )
        block = ws["blocks"][0]
        suspended = ws["members"][2]  # never a captain: no vacancy is created
        validate_success(api.suspend_member(suspended["id"], COORD))

        group = validate_success(api.get_watch_group(ws["group"]["id"], COORD))
        assert group["posture"] == "OPERATIONAL", (
            "Suspending a non-captain leaves the captain coverage intact"
        )

        alert = create_alert(
            group["id"], audience_scope="BLOCK", target_block_id=block["id"],
            scheduled_send_at="2026-08-09T12:00:00Z",
        )
        queue_alert(alert["id"])
        sent = send_alert_at(alert["id"], "2026-08-09T12:00:00Z")
        assert sent["recipient_count"] == 2, (
            "2 ACTIVE SMS members counted; the SUSPENDED member is excluded"
        )


class TestAcknowledgementPosture:
    def _sent_alert_with_three_recipients(self, api):
        ws = setup_operational_group(
            "Ack Watch", "PCT6",
            member_channels=("SMS", "SMS", "SMS"),
            train_member_indexes=(0,),
            badge_number="B600",
        )
        alert = create_alert(ws["group"]["id"],
                             scheduled_send_at="2026-08-09T12:00:00Z")
        queue_alert(alert["id"])
        sent = send_alert_at(alert["id"], "2026-08-09T12:00:00Z")
        assert sent["recipient_count"] == 3
        return ws, sent

    def test_ack_posture_walks_partial_majority_full(self, api):
        """PRD §3.4: "The `ack_posture` derives from the counts: it leaves
        `UNTRACKED` for `PARTIAL` once at least one member has acknowledged,
        advances to `MAJORITY` once `ack_count` reaches at least half of
        `recipient_count` rounded down plus one, and reaches `FULL` when
        `ack_count` equals `recipient_count` with a nonzero recipient count."

        Design: Difficulty/non_linear_state_machine/alert_parallel_dimensions_ack_posture
        """
        ws, sent = self._sent_alert_with_three_recipients(api)
        members = ws["members"]

        first = validate_success(
            api.ack_alert(sent["id"], ack_alert_payload(members[0]["id"]),
                          make_member_headers(members[0]["id"]))
        )
        assert first["ack_posture"] == "PARTIAL"
        assert first["distribution_status"] == "SENT", (
            "The acknowledgement axis moves without touching distribution_status"
        )

        second = validate_success(
            api.ack_alert(sent["id"], ack_alert_payload(members[1]["id"]),
                          make_member_headers(members[1]["id"]))
        )
        assert second["ack_posture"] == "MAJORITY", (
            "ack_count 2 >= floor(3/2)+1 = 2"
        )

        third = validate_success(
            api.ack_alert(sent["id"], ack_alert_payload(members[2]["id"]),
                          make_member_headers(members[2]["id"]))
        )
        assert third["ack_posture"] == "FULL"
        assert third["ack_count"] == 3
        assert third["distribution_status"] == "SENT", (
            "The two dimensions stay independent on the same row"
        )

    def test_duplicate_ack_rejected_and_distribution_untouched(self, api):
        """PRD §3.4: "A member or captain records an acknowledgement by supplying
        their `member_id`; each acknowledgement increments `ack_count`, and a
        second acknowledgement from the same member is rejected with
        `ERR_CONSTRAINT_VIOLATION`."

        Design: Difficulty/non_linear_state_machine/alert_parallel_dimensions_ack_posture
        """
        ws, sent = self._sent_alert_with_three_recipients(api)
        member = ws["members"][0]
        validate_success(
            api.ack_alert(sent["id"], ack_alert_payload(member["id"]),
                          make_member_headers(member["id"]))
        )
        resp = api.ack_alert(sent["id"], ack_alert_payload(member["id"]),
                             make_member_headers(member["id"]))
        validate_error(resp, ApiErrorId.ERR_CONSTRAINT_VIOLATION)

        after = validate_success(api.get_alert(sent["id"], COORD))
        assert after["ack_count"] == 1, "The duplicate ack does not double-count"
        assert after["ack_posture"] == "PARTIAL"
        assert after["distribution_status"] == "SENT"


class TestSendGates:
    def test_send_before_scheduled_instant_rejected_then_fires(self, api):
        """PRD §3.4: "Sending before the scheduled instant is rejected with
        `ERR_INVALID_STATE` — the scheduled instant itself is fireable — and
        sending still requires posture `OPERATIONAL` and the quiet-hours rule of
        §2.11."

        Design: Corner/cross_cutting_layers/scheduled_action_alert_send_at_exact_time
        """
        ws = setup_operational_group(
            "Sched Watch", "L04",
            member_channels=("SMS",), badge_number="BL04",
        )
        alert = create_alert(ws["group"]["id"],
                             scheduled_send_at="2026-08-09T12:00:00Z")
        queue_alert(alert["id"])

        set_clock("2026-08-09T11:59:00Z")
        resp = api.send_alert(alert["id"], COORD)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        held = validate_success(api.get_alert(alert["id"], COORD))
        assert held["distribution_status"] == "QUEUED"

        sent = send_alert_at(alert["id"], "2026-08-09T12:00:00Z")
        assert sent["distribution_status"] == "SENT", (
            "The scheduled instant itself is fireable (inclusive boundary)"
        )

    def test_quiet_hours_reject_non_bulletin_alert_at_create(self, api):
        """PRD §2.11: "An alert whose `scheduled_send_at` falls inside quiet
        hours is rejected with `ERR_QUIET_HOURS` (HTTP 422) at the time the
        schedule is set, and an immediate send attempted during quiet hours is
        rejected the same way."
        PRD §2.11: "The single exemption is an alert whose `alert_kind` is
        `INCIDENT_BULLETIN`"

        Design: Corner/validations/quiet_hours_violation_non_bulletin_alert_create
        """
        group = create_watch_group("Quiet Watch", "V04")
        version = get_group_version(group["id"])
        resp = api.create_alert(
            create_alert_payload(
                group["id"], version, alert_kind="MEETING_NOTICE",
                audience_scope="GROUP",
                scheduled_send_at="2026-08-10T23:15:00Z",
            ),
            COORD,
        )
        validate_error(resp, ApiErrorId.ERR_QUIET_HOURS)


class TestValidationPriorityOnSend:
    def test_state_check_precedes_quiet_hours_on_send(self, api):
        """PRD §2.6: "fourth, whether the target resource is in a state from
        which the requested transition exists (`ERR_INVALID_STATE`); fifth, the
        watch-group posture gate (`ERR_POSTURE_GATED`); sixth, segregation of
        duties (`ERR_SEGREGATION_OF_DUTIES`); seventh, the temporal rules, in the
        order quiet hours (`ERR_QUIET_HOURS`)"

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_temporal_on_alert_send
        """
        ws = setup_operational_group(
            "Prio Watch A", "PCT9",
            member_channels=("SMS",), badge_number="B900",
        )
        # DRAFT alert, schedule legal at create; the clock is then advanced into
        # quiet hours so the send attempt violates BOTH the state rule (DRAFT
        # has no ->SENT path) and the quiet-hours rule.
        alert = create_alert(ws["group"]["id"],
                             scheduled_send_at="2026-08-10T12:00:00Z")
        set_clock("2026-08-10T23:30:00Z")
        resp = api.send_alert(alert["id"], COORD)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        after = validate_success(api.get_alert(alert["id"], COORD))
        assert after["distribution_status"] == "DRAFT"

    def test_quiet_hours_fires_when_state_allows_send(self, api):
        """PRD §2.11: "an immediate send attempted during quiet hours is rejected
        the same way."
        PRD §2.6: "fourth, whether the target resource is in a state from which
        the requested transition exists (`ERR_INVALID_STATE`); fifth, the
        watch-group posture gate (`ERR_POSTURE_GATED`); sixth, segregation of
        duties (`ERR_SEGREGATION_OF_DUTIES`); seventh, the temporal rules, in the
        order quiet hours (`ERR_QUIET_HOURS`)"

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_temporal_on_alert_send
        """
        ws = setup_operational_group(
            "Prio Watch A", "PCT9",
            member_channels=("SMS",), badge_number="B900",
        )
        # QUEUED alert whose scheduled instant (21:00, outside 22:00-07:00) has
        # passed — only the quiet-hours rule is violated by the 23:30 send.
        alert = create_alert(ws["group"]["id"],
                             scheduled_send_at="2026-08-10T21:00:00Z")
        queue_alert(alert["id"])
        set_clock("2026-08-10T23:30:00Z")
        resp = api.send_alert(alert["id"], COORD)
        validate_error(resp, ApiErrorId.ERR_QUIET_HOURS)

        after = validate_success(api.get_alert(alert["id"], COORD))
        assert after["distribution_status"] == "QUEUED"


class TestBlockScopeCaptainGate:
    def test_block_alert_create_requires_active_captain(self, api):
        """PRD §3.4: "Because a block that loses its captain drags its group
        toward `DEGRADED`, the active-captain requirement for block-scoped alerts
        is verified at creation time — the target block must hold exactly one
        `ACTIVE` captain assignment, else `ERR_NO_ACTIVE_CAPTAIN` (HTTP 409) —
        so the captainless-block case surfaces instead of being masked by the
        posture gate that guards queueing and sending."

        Design: Corner/errors/err_no_active_captain_on_block_alert_queue
        """
        group, block = setup_group_with_registered_block(
            "NoCap Watch", "X01", "1-1 Capless St", 4,
        )
        version = get_group_version(group["id"])
        resp = api.create_alert(
            create_alert_payload(
                group["id"], version, alert_kind="SAFETY_TIP",
                audience_scope="BLOCK", target_block_id=block["id"],
                scheduled_send_at="2026-08-09T12:00:00Z",
            ),
            COORD,
        )
        validate_error(resp, ApiErrorId.ERR_NO_ACTIVE_CAPTAIN)


class TestAlertOptimisticConcurrency:
    def test_stale_group_version_rejected_after_cascade(self, api):
        """PRD §2.7: "Creating an alert — `POST /watch/alerts` — requires a
        non-optional `expected_watch_group_version` field carrying the client's
        last observed `version` of the parent watch group. If the group's current
        `version` does not match, the create is rejected with `ERR_STALE_VERSION`
        (HTTP 412), preventing the client from drafting against a group state it
        has not observed."
        PRD §2.4: "A mutation that cascades into a parent resource — for example,
        a block registration that recomputes the parent group's posture —
        independently updates the parent's `updated_at` and increments its
        `version`"

        Design: Corner/cross_cutting_layers/occ_stale_version_alert_create_after_cascade
        """
        group = create_watch_group("OCC Watch", "L01")
        observed_version = group["version"]
        block = add_block(group["id"], "1-1 Occ St", 4)
        register_block(block["id"])  # cascade bumps the group's version

        resp = api.create_alert(
            create_alert_payload(
                group["id"], observed_version, alert_kind="SAFETY_TIP",
                audience_scope="GROUP",
                scheduled_send_at="2026-08-09T12:00:00Z",
            ),
            COORD,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

        fresh_version = get_group_version(group["id"])
        assert fresh_version != observed_version
        ok = validate_success(
            api.create_alert(
                create_alert_payload(
                    group["id"], fresh_version, alert_kind="SAFETY_TIP",
                    audience_scope="GROUP",
                    scheduled_send_at="2026-08-09T12:00:00Z",
                ),
                COORD,
            ),
            201,
        )
        assert_alert(ok)
        assert ok["distribution_status"] == "DRAFT"


class TestMaterialsConservation:
    def test_send_increments_materials_by_printed_flyers(self, api):
        """PRD §3.4: "The same transition charges the materials ledger: the group
        is deemed to print one flyer per 10 recipients, rounded up, and
        `materials_inventory_count` increases by that flyer quantity."

        Design: Difficulty/compensating_invariant/alert_send_recall_conserves_materials_inventory
        """
        ws = _phone_tree_group(api)
        issue_materials(ws["group"]["id"], signs=10, materials=100)

        sent = send_group_alert(ws["group"]["id"], "2026-08-09T12:00:00Z")
        assert sent["recipient_count"] == 6
        group = validate_success(api.get_watch_group(ws["group"]["id"], COORD))
        assert group["materials_inventory_count"] == 101, (
            "The forward send debits the ledger by exactly printed_flyers = 1"
        )

    def test_recall_restores_materials_ledger(self, api):
        """PRD §3.4: "Recalling a `SENT` alert — a coordinator action — moves it
        to `RECALLED`, terminal, and credits back exactly the flyer quantity that
        was added at send, conserving the ledger; the alert's `ack_posture` is
        frozen at whatever value it held at recall."

        Design: Difficulty/compensating_invariant/alert_send_recall_conserves_materials_inventory
        """
        ws = _phone_tree_group(api)
        issue_materials(ws["group"]["id"], signs=10, materials=100)
        sent = send_group_alert(ws["group"]["id"], "2026-08-09T12:00:00Z")
        assert validate_success(api.get_watch_group(ws["group"]["id"], COORD))[
            "materials_inventory_count"
        ] == 101

        recalled = validate_success(api.recall_alert(sent["id"], COORD))
        assert recalled["distribution_status"] == "RECALLED"
        assert recalled["ack_posture"] == "UNTRACKED", (
            "ack_posture freezes at its recall-time value (none acknowledged)"
        )
        group = validate_success(api.get_watch_group(ws["group"]["id"], COORD))
        assert group["materials_inventory_count"] == 100, (
            "The compensating recall restores the ledger: 100 -> 101 -> 100"
        )
