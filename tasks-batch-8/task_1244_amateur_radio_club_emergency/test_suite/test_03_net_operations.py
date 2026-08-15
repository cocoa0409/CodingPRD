"""Net scheduling and lifecycle (PRD §3.3): half-open overlap rule, open
preconditions, terminal lockdown, net-control ownership, filtered listings."""
from test_helpers import (
    ApiErrorId,
    check_in,
    close_net,
    create_active_member,
    create_net_control,
    create_net_session_payload,
    get_success_data,
    make_netcontrol_headers,
    open_net,
    repeater_set_status,
    schedule_net,
    setup_operational_repeater,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestNetOverlap:
    def test_adjacent_net_allowed(self, api, admin_headers):
        """PRD §3.3: "Net windows are *half-open* — a net occupies from
        `scheduled_start` inclusive to `scheduled_end` exclusive — so two nets
        on the same repeater may not overlap while both are `SCHEDULED` or
        `OPEN`, but back-to-back nets whose boundary instants touch are
        explicitly allowed; a genuine conflict is rejected with
        `ERR_NET_TIME_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/net_half_open_overlap_allows_adjacent
        """
        _, repeater = setup_operational_repeater()
        nc = create_net_control()
        schedule_net(repeater["id"], nc["id"], name="Net 1",
                     scheduled_start="2026-05-01T00:00:00Z",
                     scheduled_end="2026-05-01T02:00:00Z")
        adjacent = api.create_net_session(
            create_net_session_payload(
                repeater["id"], name="Net 2",
                scheduled_start="2026-05-01T02:00:00Z",
                scheduled_end="2026-05-01T04:00:00Z"),
            make_netcontrol_headers(nc["id"]))
        net2 = validate_success(adjacent, 201)
        assert net2["status"] == "SCHEDULED"

    def test_overlapping_net_rejected(self, api, admin_headers):
        """PRD §3.3: "Net windows are *half-open* — a net occupies from
        `scheduled_start` inclusive to `scheduled_end` exclusive — so two nets
        on the same repeater may not overlap while both are `SCHEDULED` or
        `OPEN`, but back-to-back nets whose boundary instants touch are
        explicitly allowed; a genuine conflict is rejected with
        `ERR_NET_TIME_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/net_half_open_overlap_allows_adjacent
        """
        _, repeater = setup_operational_repeater()
        nc = create_net_control()
        schedule_net(repeater["id"], nc["id"], name="Net 1",
                     scheduled_start="2026-05-01T00:00:00Z",
                     scheduled_end="2026-05-01T02:00:00Z")
        schedule_net(repeater["id"], nc["id"], name="Net 2",
                     scheduled_start="2026-05-01T02:00:00Z",
                     scheduled_end="2026-05-01T04:00:00Z")
        overlapping = api.create_net_session(
            create_net_session_payload(
                repeater["id"], name="Net 3",
                scheduled_start="2026-05-01T01:00:00Z",
                scheduled_end="2026-05-01T03:00:00Z"),
            make_netcontrol_headers(nc["id"]))
        validate_error(overlapping, ApiErrorId.ERR_NET_TIME_CONFLICT)
        _, meta = validate_paginated(
            api.list_net_sessions(admin_headers, params={"repeater_id": repeater["id"]}))
        assert meta["total_count"] == 2


class TestNetScheduleValidationOrder:
    def test_under_licensed_control_rejected_before_overlap(self, api, admin_headers):
        """PRD §2.10: "Sixth, field-domain and structural rules: uniqueness,
        license class and expiry, frequency bands, traffic consistency,
        duplicate participation, loan windows, and operator-count caps.
        Seventh, temporal interval rules: net scheduling overlaps and
        site-lease window overlaps." and "the reported error is always the
        earliest applicable one."
        PRD §3.3: "The designated control operator must hold a `license_class`
        ordinally at or above the net's `min_license_class` (else
        `ERR_LICENSE_CLASS_INSUFFICIENT`)."

        Design: Difficulty/priority_pair_validation_conflict/net_schedule_constraint_beats_temporal
        """
        _, repeater = setup_operational_repeater()
        nc1 = create_net_control("W1NCS")
        nc2 = create_net_control("K2TEC", license_class="TECHNICIAN")
        schedule_net(repeater["id"], nc1["id"], name="Net 1",
                     scheduled_start="2026-05-01T00:00:00Z",
                     scheduled_end="2026-05-01T02:00:00Z")
        resp = api.create_net_session(
            create_net_session_payload(
                repeater["id"], name="Net 2",
                scheduled_start="2026-05-01T01:00:00Z",
                scheduled_end="2026-05-01T03:00:00Z",
                min_license_class="GENERAL"),
            make_netcontrol_headers(nc2["id"]))
        validate_error(resp, ApiErrorId.ERR_LICENSE_CLASS_INSUFFICIENT)

    def test_rejected_net_is_not_persisted(self, api, admin_headers):
        """PRD §2.10: "the reported error is always the earliest applicable
        one." — the license-class failure (sixth) pre-empts the overlap
        failure (seventh), so no second net is recorded for the repeater.
        PRD §3.3: "Nets can be listed with `repeater_id`,
        `net_control_member_id`, and `status` filters."

        Design: Difficulty/priority_pair_validation_conflict/net_schedule_constraint_beats_temporal
        """
        _, repeater = setup_operational_repeater()
        nc1 = create_net_control("W1NCS")
        nc2 = create_net_control("K2TEC", license_class="TECHNICIAN")
        schedule_net(repeater["id"], nc1["id"], name="Net 1",
                     scheduled_start="2026-05-01T00:00:00Z",
                     scheduled_end="2026-05-01T02:00:00Z")
        api.create_net_session(
            create_net_session_payload(
                repeater["id"], name="Net 2",
                scheduled_start="2026-05-01T01:00:00Z",
                scheduled_end="2026-05-01T03:00:00Z",
                min_license_class="GENERAL"),
            make_netcontrol_headers(nc2["id"]))
        _, meta = validate_paginated(
            api.list_net_sessions(admin_headers, params={"repeater_id": repeater["id"]}))
        assert meta["total_count"] == 1


class TestNetOpenPreconditions:
    def test_open_before_window_rejected(self, api, admin_headers):
        """PRD §3.3: "the current clock must sit inside the window — at or
        after `scheduled_start` and strictly before `scheduled_end` (else
        `ERR_NET_WINDOW_NOT_STARTED`)".

        Design: Corner/state_machines/net_open_before_window_returns_window_error
        """
        _, repeater = setup_operational_repeater()
        nc = create_net_control()
        net = schedule_net(repeater["id"], nc["id"], name="Net 1",
                           scheduled_start="2026-05-02T00:00:00Z",
                           scheduled_end="2026-05-03T00:00:00Z")
        resp = api.net_session_set_status(
            net["id"], {"to": "OPEN"}, make_netcontrol_headers(nc["id"]))
        validate_error(resp, ApiErrorId.ERR_NET_WINDOW_NOT_STARTED)
        after = get_success_data(api.get_net_session(net["id"], admin_headers))
        assert after["status"] == "SCHEDULED"

    def test_open_requires_repeater_operational_error(self, api, admin_headers):
        """PRD §3.3: "and the repeater must currently be `OPERATIONAL` (else
        `ERR_REPEATER_NOT_OPERATIONAL`)".

        Design: Difficulty/cross_entity_state_dependency/net_open_requires_repeater_operational
        """
        _, repeater = setup_operational_repeater()
        nc = create_net_control()
        net = schedule_net(repeater["id"], nc["id"], name="Net 1")
        repeater_set_status(repeater["id"], "DEGRADED")
        resp = api.net_session_set_status(
            net["id"], {"to": "OPEN"}, make_netcontrol_headers(nc["id"]))
        validate_error(resp, ApiErrorId.ERR_REPEATER_NOT_OPERATIONAL)

    def test_open_rejected_leaves_net_scheduled(self, api, admin_headers):
        """PRD §3.3: "Opening a net (`SCHEDULED` → `OPEN`) is guarded three
        ways." — a rejected open attempt leaves the net in `SCHEDULED`.
        PRD §3.3: "the repeater must currently be `OPERATIONAL` (else
        `ERR_REPEATER_NOT_OPERATIONAL`)".

        Design: Difficulty/cross_entity_state_dependency/net_open_requires_repeater_operational
        """
        _, repeater = setup_operational_repeater()
        nc = create_net_control()
        net = schedule_net(repeater["id"], nc["id"], name="Net 1")
        repeater_set_status(repeater["id"], "DEGRADED")
        api.net_session_set_status(
            net["id"], {"to": "OPEN"}, make_netcontrol_headers(nc["id"]))
        after = get_success_data(api.get_net_session(net["id"], admin_headers))
        assert after["status"] == "SCHEDULED"


class TestNetCloseAndCancel:
    def test_closed_net_is_terminal(self, api, admin_headers):
        """PRD §3.3: "`CLOSED` and `CANCELLED` are terminal." and §2.10:
        "Fourth, the from-state of the primary resource for the requested
        transition — generic invalid-from rejections are `ERR_INVALID_STATE`".

        Design: Corner/state_machines/net_closed_terminal_lockdown
        """
        _, repeater = setup_operational_repeater()
        nc = create_net_control()
        net = schedule_net(repeater["id"], nc["id"], name="Net 1")
        open_net(net["id"], nc["id"])
        close_net(net["id"], nc["id"])
        resp = api.net_session_set_status(
            net["id"], {"to": "OPEN"}, make_netcontrol_headers(nc["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        after = get_success_data(api.get_net_session(net["id"], admin_headers))
        assert after["status"] == "CLOSED"

    def test_netcontrol_cannot_open_others_net(self, api, admin_headers):
        """PRD §3.3: "The caller must be the net's control operator or a
        `ClubAdmin` (else `ERR_FORBIDDEN`)".

        Design: Corner/rbac/netcontrol_cannot_open_others_net
        """
        _, repeater = setup_operational_repeater()
        nc1 = create_net_control("W1NCS")
        nc2 = create_net_control("K2NCS")
        net = schedule_net(repeater["id"], nc1["id"], name="Net 1")
        resp = api.net_session_set_status(
            net["id"], {"to": "OPEN"}, make_netcontrol_headers(nc2["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        after = get_success_data(api.get_net_session(net["id"], admin_headers))
        assert after["status"] == "SCHEDULED"


class TestReverseReachability:
    def test_foreign_keys_reachable_via_filtered_lists(self, api, admin_headers):
        """PRD §3.3: "Check-in records are immutable once written and can be
        listed with `net_session_id` and `member_id` filters."
        PRD §3.2: "The new request starts in `DRAFT` and can be listed with
        `repeater_id` and `status` filters."
        PRD §3.3: "Nets can be listed with `repeater_id`,
        `net_control_member_id`, and `status` filters."

        Design: Corner/endpoints/reverse_reachability_filtered_lists
        """
        _, repeater = setup_operational_repeater()
        nc = create_net_control()
        member = create_active_member("K1OPR")
        net = schedule_net(repeater["id"], nc["id"], name="Net 1")
        open_net(net["id"], nc["id"])
        check_in(net["id"], member["id"])

        by_net, meta_net = validate_paginated(
            api.list_check_ins(admin_headers, params={"net_session_id": net["id"]}))
        assert meta_net["total_count"] == 1
        assert by_net[0]["member_id"] == member["id"]

        by_member, meta_member = validate_paginated(
            api.list_check_ins(admin_headers, params={"member_id": member["id"]}))
        assert meta_member["total_count"] == 1
        assert by_member[0]["net_session_id"] == net["id"]

        _, meta_cr = validate_paginated(
            api.list_coordination_requests(admin_headers,
                                           params={"repeater_id": repeater["id"]}))
        assert meta_cr["total_count"] == 1

        _, meta_nets = validate_paginated(
            api.list_net_sessions(admin_headers, params={"repeater_id": repeater["id"]}))
        assert meta_nets["total_count"] == 1
