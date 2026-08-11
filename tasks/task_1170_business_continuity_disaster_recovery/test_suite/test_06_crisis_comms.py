"""Crisis communication trees, activations, and acknowledgements (PRD §3.8)."""
from test_helpers import (
    ApiErrorId,
    api_client,
    create_activation,
    create_active_process,
    create_comm_node,
    create_contact,
    make_crisis_officer_headers,
    set_clock,
    setup_activation_ready,
    validate_error,
    validate_success,
)


class TestActivationTerminalLockdown:
    def test_activate_terminal_state_lockdown(self, api):
        """PRD §3.8: "Stand-down is the terminal transition: the `CrisisOfficer` deactivates from any of `ACTIVE`, `ALL_NOTIFIED`, or `ACKNOWLEDGED` — any other state fails `ERR_INVALID_STATE` — moving the activation to `DEACTIVATED`, recording the acting contact in `deactivated_by_contact_id`, and incrementing `version`."

        DEACTIVATED is terminal: a second deactivate is rejected.

        Design: Corner/state_machines/activate_terminal_state_lockdown
        """
        ctx = setup_activation_ready("CrisisProc")
        crisis_headers = make_crisis_officer_headers(ctx["crisis"]["id"])
        create_comm_node(ctx["tree_label"], ctx["crisis"]["id"], None, 1,
                         contact_name="Duty Officer")
        activation = create_activation(ctx["process"]["id"], ctx["crisis"]["id"],
                                       declared_severity="SEV2",
                                       activation_criterion="CRITERION_A",
                                       criterion_justification="data center fire")
        deactivated = validate_success(
            api_client.deactivate_activation(activation["id"], crisis_headers))
        assert deactivated["status"] == "DEACTIVATED"
        second = api_client.deactivate_activation(activation["id"], crisis_headers)
        validate_error(second, ApiErrorId.ERR_INVALID_STATE)


class TestActivationFanout:
    def test_activation_fanout_counts_and_auto_bubble(self, api):
        """PRD §3.8: "The server pins `plan_id` to the process's currently `APPROVED` plan, computes `expected_notifications` as the count of distinct comm nodes whose `tree_label` equals the process's tree label (the literal prefix `TREE_` prepended to the process's `name`) and whose `active_flag` is true — a node reachable over several channels still counts once — and creates one notification per such node in tree order: breadth-first, with siblings taken in ascending `order_index` at each level."
        PRD §3.8: "As soon as fan-out completes, the moment `notified_count` reaches `expected_notifications`, the activation auto-advances `ACTIVE` → `ALL_NOTIFIED` with `escalation_level` held at zero and a `version` increment."
        PRD §3.8: "Each notification is created in `SENT` with its `channel` copied from the node, its `sent_at` stamped from the program clock, its `acked_at` empty, and a per-notification `ack_token` minted for the acknowledgement handshake."

        Root plus two active children and one inactive child: expected 3, notified 3,
        status ALL_NOTIFIED, every notification SENT with a token.

        Design: Corner/state_machines/activation_fanout_counts_and_auto_bubble
        """
        ctx = setup_activation_ready("FanoutProc")
        crisis_id = ctx["crisis"]["id"]
        crisis_headers = make_crisis_officer_headers(crisis_id)
        root = create_comm_node(ctx["tree_label"], crisis_id, None, 1,
                                contact_name="Root", channel="PHONE")
        create_comm_node(ctx["tree_label"], crisis_id, root["id"], 1,
                         contact_name="N1", channel="EMAIL")
        create_comm_node(ctx["tree_label"], crisis_id, root["id"], 2,
                         contact_name="N2", channel="SMS", ack_deadline_minutes=15)
        create_comm_node(ctx["tree_label"], crisis_id, root["id"], 3,
                         contact_name="N3", channel="EMAIL", ack_deadline_minutes=60,
                         active_flag=False)
        activation = create_activation(
            ctx["process"]["id"], crisis_id, declared_severity="SEV1",
            activation_criterion="CRITERION_B",
            criterion_justification="region loss")
        assert activation["expected_notifications"] == 3, (
            "the inactive node must be excluded from the fan-out count"
        )
        assert activation["notified_count"] == 3
        assert activation["status"] == "ALL_NOTIFIED"
        notifications = validate_success(
            api_client.list_activation_notifications(activation["id"], crisis_headers))
        assert len(notifications) == 3
        for notification in notifications:
            assert notification["status"] == "SENT"
            assert notification.get("ack_token"), "each notification mints an ack_token"
            assert notification.get("sent_at"), "each notification is stamped sent_at"


class TestNotificationAckBubble:
    def test_notification_ack_bubbles_activation_to_acknowledged(self, api):
        """PRD §3.8: "A valid acknowledgement stamps `acked_at` from the program clock, moves the notification `SENT` → `ACKED`, and increments the activation's `acked_count`; when that count reaches `expected_notifications`, the activation auto-advances `ALL_NOTIFIED` → `ACKNOWLEDGED`, stamps `acknowledged_at` with the current program time, and increments its `version`."

        Acking the single outstanding notification flips the parent activation.

        Design: Corner/state_machines/notification_ack_bubbles_activation_to_acknowledged
        """
        ctx = setup_activation_ready("BubbleProc")
        crisis_id = ctx["crisis"]["id"]
        crisis_headers = make_crisis_officer_headers(crisis_id)
        create_comm_node(ctx["tree_label"], crisis_id, None, 1, contact_name="Root")
        activation = create_activation(ctx["process"]["id"], crisis_id)
        notifications = validate_success(
            api_client.list_activation_notifications(activation["id"], crisis_headers))
        notification = notifications[0]
        acked = validate_success(
            api_client.ack_notification(notification["id"],
                                        {"ack_token": notification["ack_token"]},
                                        crisis_headers))
        assert acked["status"] == "ACKED"
        after = validate_success(api_client.get_activation(activation["id"], crisis_headers))
        assert after["status"] == "ACKNOWLEDGED", (
            "the last ack must bubble the activation to ACKNOWLEDGED"
        )
        assert after["acked_count"] == 1
        assert after.get("acknowledged_at"), "acknowledged_at must be stamped"


class TestEmptyTreeActivation:
    def test_activation_ack_coverage_empty_tree(self, api):
        """PRD §3.8: "The empty-tree guard is explicit: an activation over a tree with zero active nodes fans out nothing, passes straight through `ALL_NOTIFIED`, and — because zero acknowledgements already equal zero expected — lands immediately in `ACKNOWLEDGED`, reporting zero coverage."

        No comm nodes: expected 0, zero notifications, straight to ACKNOWLEDGED.

        Design: Corner/calculations/activation_ack_coverage_empty_tree
        """
        ctx = setup_activation_ready("EmptyTreeProc")
        crisis_headers = make_crisis_officer_headers(ctx["crisis"]["id"])
        activation = create_activation(ctx["process"]["id"], ctx["crisis"]["id"],
                                       criterion_justification="drill")
        assert activation["expected_notifications"] == 0
        assert activation["status"] == "ACKNOWLEDGED", (
            "0 == 0 parity must land the activation directly in ACKNOWLEDGED"
        )
        notifications = validate_success(
            api_client.list_activation_notifications(activation["id"], crisis_headers))
        assert notifications == [], "an empty tree fans out zero notifications"


class TestCommTreeIntegrity:
    def test_comm_tree_second_root_and_reparent_cycle(self, api):
        """PRD §3.8: "Structural integrity is enforced at write time: exactly one root — one node with an empty `parent_node_id` — may exist per `tree_label`, and a second is rejected with `ERR_TREE_ROOT_EXISTS`; re-parenting a node in a way that would make the node its own ancestor is rejected with `ERR_COMM_TREE_CYCLE`; sibling order is unique, so a colliding (`tree_label`, `parent_node_id`, `order_index`) triple fails with `ERR_DUPLICATE`; and a node may be deactivated — `active_flag` set false — only when every child node is already inactive, else `ERR_NODE_HAS_ACTIVE_CHILDREN`."

        Duplicate root, re-parenting the root under its own child, and deactivating
        a node with an active child each fail with their own error.

        Design: Corner/validations/comm_tree_second_root_and_reparent_cycle
        """
        officer = create_contact("Crisis Chris", "Crisis Officer")
        officer_headers = make_crisis_officer_headers(officer["id"])
        root = create_comm_node("TREE_T1", officer["id"], None, 1,
                                contact_name="Root", channel="PHONE")
        child = create_comm_node("TREE_T1", officer["id"], root["id"], 1,
                                 contact_name="Child", channel="EMAIL")

        second_root = api_client.create_comm_node(
            {"tree_label": "TREE_T1", "contact_name": "Root2", "role_title": "Duty",
             "parent_node_id": None, "order_index": 2, "channel": "SMS",
             "ack_deadline_minutes": 10},
            officer_headers)
        validate_error(second_root, ApiErrorId.ERR_TREE_ROOT_EXISTS)

        cycle = api_client.update_comm_node(root["id"], {"parent_node_id": child["id"]},
                                            officer_headers)
        validate_error(cycle, ApiErrorId.ERR_COMM_TREE_CYCLE)

        deactivate = api_client.update_comm_node(root["id"], {"active_flag": False},
                                                 officer_headers)
        validate_error(deactivate, ApiErrorId.ERR_NODE_HAS_ACTIVE_CHILDREN)


class TestActivationGating:
    def _setup(self):
        ctx = setup_activation_ready("CritProc")
        crisis = ctx["crisis"]
        create_comm_node(ctx["tree_label"], crisis["id"], None, 1,
                         contact_name="Root")
        no_plan_process = create_active_process(crisis["id"], name="NoPlanProc")
        return crisis, ctx, no_plan_process

    def test_activation_severity_criterion_matrix(self, api):
        """PRD §3.8: "And the declared severity must permit the requested criterion under a fixed mapping: `SEV1` permits `CRITERION_A` and `CRITERION_B`; `SEV2` permits `CRITERION_A` only; `SEV3` permits no criterion at all, so any request with `SEV3` is rejected with `ERR_CRITERION_NOT_ALLOWED`."
        PRD §3.8: "The process must have an `APPROVED` plan, else `ERR_NO_APPROVED_PLAN`. No other activation of the same process may be live — in `ACTIVE`, `ALL_NOTIFIED`, or `ACKNOWLEDGED` — else `ERR_ACTIVATION_ALREADY_ACTIVE`."

        SEV2 rejects CRITERION_B; a process without an approved plan is refused;
        a second live activation for the same process is refused.

        Design: Corner/validations/activation_severity_criterion_matrix
        """
        crisis, ctx, no_plan_process = self._setup()
        officer_headers = make_crisis_officer_headers(crisis["id"])

        bad_criterion = api_client.create_activation(
            {"process_id": ctx["process"]["id"], "declared_severity": "SEV2",
             "activation_criterion": "CRITERION_B", "criterion_justification": "x"},
            officer_headers)
        validate_error(bad_criterion, ApiErrorId.ERR_CRITERION_NOT_ALLOWED)

        no_plan = api_client.create_activation(
            {"process_id": no_plan_process["id"], "declared_severity": "SEV1",
             "activation_criterion": "CRITERION_A", "criterion_justification": "x"},
            officer_headers)
        validate_error(no_plan, ApiErrorId.ERR_NO_APPROVED_PLAN)

        first = create_activation(ctx["process"]["id"], ctx["crisis"]["id"],
                                  declared_severity="SEV2",
                                  activation_criterion="CRITERION_A",
                                  criterion_justification="x")
        assert first["id"]
        second = api_client.create_activation(
            {"process_id": ctx["process"]["id"], "declared_severity": "SEV1",
             "activation_criterion": "CRITERION_A",
             "criterion_justification": "second"},
            officer_headers)
        validate_error(second, ApiErrorId.ERR_ACTIVATION_ALREADY_ACTIVE)


class TestNotificationAckFailures:
    def test_ack_with_wrong_token_rejected(self, api):
        """PRD §3.8: "The token must match the one minted at fan-out (`ERR_ACK_TOKEN_MISMATCH` on a mismatch), the notification must still be `SENT` (`ERR_NOTIFICATION_ALREADY_ACKED` on a repeat), and the owning activation must still be in `ACTIVE` or `ALL_NOTIFIED` — acknowledgements against a deactivated or completed activation fail with `ERR_INVALID_STATE`."

        Wrong token is refused; the correct token succeeds; replaying it is refused.

        Design: Corner/errors/ack_with_wrong_token_rejected
        """
        ctx = setup_activation_ready("AckProc")
        crisis_id = ctx["crisis"]["id"]
        crisis_headers = make_crisis_officer_headers(crisis_id)
        create_comm_node(ctx["tree_label"], crisis_id, None, 1, contact_name="Root")
        activation = create_activation(ctx["process"]["id"], crisis_id,
                                       declared_severity="SEV1",
                                       activation_criterion="CRITERION_A",
                                       criterion_justification="x")
        notifications = validate_success(
            api_client.list_activation_notifications(activation["id"], crisis_headers))
        notification = notifications[0]

        wrong = api_client.ack_notification(notification["id"],
                                            {"ack_token": "wrong-token"},
                                            crisis_headers)
        validate_error(wrong, ApiErrorId.ERR_ACK_TOKEN_MISMATCH)

        acked = validate_success(
            api_client.ack_notification(notification["id"],
                                        {"ack_token": notification["ack_token"]},
                                        crisis_headers))
        assert acked["status"] == "ACKED"

        replay = api_client.ack_notification(notification["id"],
                                             {"ack_token": notification["ack_token"]},
                                             crisis_headers)
        validate_error(replay, ApiErrorId.ERR_NOTIFICATION_ALREADY_ACKED)
