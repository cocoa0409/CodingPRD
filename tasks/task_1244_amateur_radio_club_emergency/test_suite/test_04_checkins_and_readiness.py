"""Check-in logging and member readiness inputs (PRD §3.1, §3.3): immutable
check-in rows, traffic consistency, duplicate and credential enforcement, and
the verified-vs-optimistic readiness variants."""
from test_helpers import (
    ApiErrorId,
    accumulate_closed_check_ins,
    assert_check_in,
    assert_instant_equals,
    assert_member_invariants,
    check_in,
    create_active_member,
    create_check_in_payload,
    create_net_control,
    get_success_data,
    make_member_headers,
    open_net,
    schedule_net,
    setup_operational_repeater,
    suspend_member,
    validate_error,
    validate_success,
)


def _open_net_scenario(api, admin_headers, member_overrides=None):
    """Operational repeater + net control + one ACTIVE member + one OPEN net."""
    _, repeater = setup_operational_repeater()
    nc = create_net_control()
    member = create_active_member("K1OPR", **(member_overrides or {}))
    net = schedule_net(repeater["id"], nc["id"], name="Net 1")
    open_net(net["id"], nc["id"])
    return repeater, nc, member, net


class TestCheckInRecord:
    def test_checkin_carries_no_version_or_updated_at(self, api, admin_headers):
        """PRD §2.4: "A `CheckIn` carries only `id` and `created_at`; both
        `updated_at` and `version` are absent, because a check-in is immutable
        once written."

        Design: Corner/entities/checkin_immutable_no_version_field
        """
        _, _, member, net = _open_net_scenario(api, admin_headers)
        resp = api.create_check_in(create_check_in_payload(net["id"]),
                                   make_member_headers(member["id"]))
        record = validate_success(resp, 201)
        assert_check_in(record)
        assert_instant_equals(record["checked_in_at"], "2026-05-01T00:00:00Z",
                              "checked_in_at")


class TestCheckInValidation:
    def test_traffic_consistency_violation_rejected(self, api, admin_headers):
        """PRD §3.3: "`traffic_count` must be zero when `has_traffic` is false
        and at least one when it is true — an inconsistent pair is rejected
        with `ERR_INVALID_TRAFFIC_COUNT`."

        Design: Corner/validations/checkin_traffic_count_consistency
        """
        _, _, member, net = _open_net_scenario(api, admin_headers)
        resp = api.create_check_in(
            create_check_in_payload(net["id"], has_traffic=True, traffic_count=0),
            make_member_headers(member["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_TRAFFIC_COUNT)

    def test_duplicate_checkin_rejected(self, api, admin_headers):
        """PRD §3.3: "Each member may check in to a given net at most once
        (`ERR_ALREADY_CHECKED_IN`)." and "A successful check-in stamps
        `checked_in_at` from the clock, recomputes the net's `checkin_count`".

        Design: Corner/validations/duplicate_checkin_rejected
        """
        _, nc, member, net = _open_net_scenario(api, admin_headers)
        check_in(net["id"], member["id"])
        resp = api.create_check_in(create_check_in_payload(net["id"]),
                                   make_member_headers(member["id"]))
        validate_error(resp, ApiErrorId.ERR_ALREADY_CHECKED_IN)
        net_after = get_success_data(api.get_net_session(net["id"], admin_headers))
        assert net_after["checkin_count"] == 1

    def test_expired_license_checkin_rejected(self, api, admin_headers):
        """PRD §2.7: "an actor whose license expiry is at or before the current
        logical-clock reading is treated as expired and rejected with
        `ERR_LICENSE_EXPIRED`".

        Design: Corner/validations/expired_license_checkin_rejected
        """
        _, _, member, net = _open_net_scenario(
            api, admin_headers,
            member_overrides={"license_expires_at": "2026-04-01T00:00:00Z"})
        resp = api.create_check_in(create_check_in_payload(net["id"]),
                                   make_member_headers(member["id"]))
        validate_error(resp, ApiErrorId.ERR_LICENSE_EXPIRED)

    def test_suspended_member_checkin_rejected(self, api, admin_headers):
        """PRD §3.3: "Check-in is refused unless the net is currently `OPEN`
        (`ERR_NET_NOT_OPEN`), the caller's `membership_status` is `ACTIVE`
        (`ERR_MEMBERSHIP_NOT_ACTIVE`), and the caller's license satisfies the
        net's `min_license_class` and is unexpired."

        Design: Corner/validations/suspended_member_checkin_rejected
        """
        _, _, member, net = _open_net_scenario(api, admin_headers)
        suspend_member(member["id"])
        resp = api.create_check_in(create_check_in_payload(net["id"]),
                                   make_member_headers(member["id"]))
        validate_error(resp, ApiErrorId.ERR_MEMBERSHIP_NOT_ACTIVE)

    def test_checkin_to_scheduled_net_rejected(self, api, admin_headers):
        """PRD §3.3: "Check-in is refused unless the net is currently `OPEN`
        (`ERR_NET_NOT_OPEN`)".

        Design: Corner/errors/checkin_to_scheduled_net_rejected
        """
        _, repeater = setup_operational_repeater()
        nc = create_net_control()
        member = create_active_member("K1OPR")
        net = schedule_net(repeater["id"], nc["id"], name="Net 1")
        assert net["status"] == "SCHEDULED"
        resp = api.create_check_in(create_check_in_payload(net["id"]),
                                   make_member_headers(member["id"]))
        validate_error(resp, ApiErrorId.ERR_NET_NOT_OPEN)


class TestReadinessVariants:
    def test_verified_score_waits_for_net_close(self, api, admin_headers):
        """PRD §3.1: "The verified score, stored as `readiness_score`, counts
        only confirmed participation: check-ins the member made on nets that
        have reached `CLOSED` with `checked_in_at` inside the trailing 365 days
        of the logical clock".

        Design: Difficulty/dual_variant_calc/member_readiness_optimistic_vs_verified
        """
        _, _, member, net = _open_net_scenario(api, admin_headers)
        check_in(net["id"], member["id"])
        detail = get_success_data(api.get_member(member["id"], admin_headers))
        assert detail["readiness_score"] == 20
        assert detail["readiness_tier"] == "INELIGIBLE"
        assert_member_invariants(detail)

    def test_optimistic_score_counts_open_net_immediately(self, api, admin_headers):
        """PRD §3.1: "The optimistic score, stored as
        `readiness_score_optimistic`, is identical except that nets in either
        `OPEN` or `CLOSED` count and drills in either `IN_PROGRESS` or
        `COMPLETED` count; it is informational only and never gates anything."
        PRD §3.3: "the optimistic variant counts the participation immediately,
        while the verified variant waits for the net to close."

        Design: Difficulty/dual_variant_calc/member_readiness_optimistic_vs_verified
        """
        _, _, member, net = _open_net_scenario(api, admin_headers)
        check_in(net["id"], member["id"])
        detail = get_success_data(api.get_member(member["id"], admin_headers))
        # One qualifying check-in: 50 * (1/6) + 20 no-show-free bonus = 28.33,
        # rounded half-up once -> 28 (PRD §2.8 single final rounding).
        assert detail["readiness_score_optimistic"] == 28


class TestReadinessTierBoundary:
    def test_score_70_is_eligible(self, api, admin_headers):
        """PRD §3.1: "The tier follows: `ELIGIBLE` at a score of 70 or higher,
        `PROVISIONAL` at 40 or higher but below 70, and `INELIGIBLE` below 40."

        Design: Difficulty/boundary_precision_check/readiness_tier_boundary_70
        """
        _, repeater = setup_operational_repeater()
        nc = create_net_control()
        member = create_active_member("K1A")
        accumulate_closed_check_ins([member["id"]], 6, repeater["id"], nc["id"])
        detail = get_success_data(api.get_member(member["id"], admin_headers))
        # 6 qualifying check-ins: 50 * (6/6) + 20 = 70 exactly.
        assert detail["readiness_score"] == 70
        assert detail["readiness_tier"] == "ELIGIBLE"

    def test_score_62_is_provisional(self, api, admin_headers):
        """PRD §3.1: "The tier follows: `ELIGIBLE` at a score of 70 or higher,
        `PROVISIONAL` at 40 or higher but below 70, and `INELIGIBLE` below 40."
        PRD §2.8: "The member readiness score is computed from weighted
        components and rounded half-up to a whole number exactly once, after
        all components — check-in component, drill component, no-show bonus,
        and privilege penalty — have been summed".

        Design: Difficulty/boundary_precision_check/readiness_tier_boundary_70
        """
        _, repeater = setup_operational_repeater()
        nc = create_net_control()
        member = create_active_member("K2B")
        accumulate_closed_check_ins([member["id"]], 5, repeater["id"], nc["id"])
        detail = get_success_data(api.get_member(member["id"], admin_headers))
        # 5 qualifying check-ins: 50 * (5/6) + 20 = 61.67 -> 62, below 70.
        assert detail["readiness_score"] == 62
        assert detail["readiness_tier"] == "PROVISIONAL"
