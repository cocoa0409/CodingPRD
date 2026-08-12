"""Cross-entity cascades (PRD §2.6): the site-expiry chain repeater -> net ->
readiness, and the damaged-return chain privilege -> readiness tier -> roster
withdrawal -> activation staffing."""
from test_helpers import (
    assert_activation_invariants,
    check_in,
    create_active_member,
    create_active_site_agreement,
    create_loan,
    create_net_control,
    create_repeater,
    file_coordination_request,
    get_success_data,
    grant_coordination,
    open_net,
    repeater_set_status,
    return_loan,
    schedule_net,
    set_clock,
    setup_eligible_member_with_confirmed_roster,
)


class TestSiteExpiryCascade:
    def _scenario(self, api, admin_headers):
        """OPERATIONAL repeater under a site agreement whose lease ends
        2026-05-10; an OPEN net on it with one checked-in member (optimistic
        readiness 28)."""
        agreement = create_active_site_agreement(
            lease_start="2026-01-01T00:00:00Z", lease_end="2026-05-10T00:00:00Z")
        repeater = create_repeater(agreement["id"])
        request = file_coordination_request(repeater["id"], repeater["version"])
        grant_coordination(request["id"])
        repeater = repeater_set_status(repeater["id"], "OPERATIONAL")
        nc = create_net_control("W1NCS")
        member = create_active_member("K1OPR")
        net = schedule_net(repeater["id"], nc["id"], name="ARES Net 1")
        open_net(net["id"], nc["id"])
        check_in(net["id"], member["id"])
        return agreement, repeater, net, member

    def test_expiry_forces_repeater_offline_and_cancels_net(self, api, admin_headers):
        """PRD §2.6: "When a site agreement leaves `ACTIVE` — whether by clock
        expiry or by administrative termination — every repeater homed at that
        site is forced `OFFLINE`, every net scheduled or running on such a
        repeater is `CANCELLED`, and every member who checked in to one of
        those nets has their readiness recomputed, because a cancelled net's
        check-ins stop counting in both readiness variants."
        PRD §2.5: "Every antenna site agreement whose `lease_end` has been
        passed transitions from `ACTIVE` to `EXPIRED`, firing the full
        repeater/net/readiness cascade described in §2.6."

        Design: Difficulty/transitive_cascade/site_expiry_cascade_to_member_readiness
        """
        agreement, repeater, net, _ = self._scenario(api, admin_headers)
        set_clock("2026-05-11T00:00:00Z")
        agreement_after = get_success_data(
            api.get_antenna_site_agreement(agreement["id"], admin_headers))
        assert agreement_after["status"] == "EXPIRED"
        repeater_after = get_success_data(api.get_repeater(repeater["id"], admin_headers))
        assert repeater_after["status"] == "OFFLINE"
        net_after = get_success_data(api.get_net_session(net["id"], admin_headers))
        assert net_after["status"] == "CANCELLED"

    def test_cancelled_net_stops_counting_in_both_readiness_variants(self, api, admin_headers):
        """PRD §2.6: "every member who checked in to one of those nets has
        their readiness recomputed, because a cancelled net's check-ins stop
        counting in both readiness variants."
        PRD §3.1: "The optimistic score, stored as
        `readiness_score_optimistic`, is identical except that nets in either
        `OPEN` or `CLOSED` count".

        Design: Difficulty/transitive_cascade/site_expiry_cascade_to_member_readiness
        """
        _, _, _, member = self._scenario(api, admin_headers)
        before = get_success_data(api.get_member(member["id"], admin_headers))
        assert before["readiness_score_optimistic"] == 28
        set_clock("2026-05-11T00:00:00Z")
        after = get_success_data(api.get_member(member["id"], admin_headers))
        # The cancelled net feeds neither variant: only the 20-point
        # no-show-free bonus remains in both.
        assert after["readiness_score_optimistic"] == 20
        assert after["readiness_score"] == 20


class TestDamagedReturnPrivilegeCascade:
    def _scenario(self, api, admin_headers):
        """Member with 6 closed-net check-ins and 1 completed drill (verified
        readiness 85, ELIGIBLE), CONFIRMED on a STANDBY activation with
        required_operators 5 (confirmed_count 1), holding an ACTIVE loan."""
        bundle = setup_eligible_member_with_confirmed_roster(
            checkins=6, drills=1, required_operators=5)
        member = bundle["member"]
        before = get_success_data(api.get_member(member["id"], admin_headers))
        assert before["readiness_score"] == 85
        assert before["readiness_tier"] == "ELIGIBLE"
        loan = create_loan(member["id"], item_tag="HT-200",
                           due_at="2026-07-01T00:00:00Z",
                           estimated_value_cents=2000)
        bundle["loan"] = loan
        return bundle

    def test_damaged_return_fee_and_privilege(self, api, admin_headers):
        """PRD §3.8: "When the `return_condition` is `DAMAGED`, a damage fee of
        one tenth of the declared value — ten percent of
        `estimated_value_cents`, itself rounded half-up to whole cents — is
        computed." and "A `DAMAGED` return ... suspends the member's
        `equipment_privilege` (`GOOD_STANDING` → `SUSPENDED`)".

        Design: Difficulty/transitive_cascade/damaged_return_privilege_cascade
        """
        bundle = self._scenario(api, admin_headers)
        returned = return_loan(bundle["loan"]["id"], bundle["member"]["id"], "DAMAGED")
        assert returned["status"] == "RETURNED"
        # Returned before due_at: base fee 0; damage fee = 2000 * 10% = 200.
        assert returned["late_fee_cents"] == 200
        member_after = get_success_data(
            api.get_member(bundle["member"]["id"], admin_headers))
        assert member_after["equipment_privilege"] == "SUSPENDED"

    def test_tier_flip_withdraws_confirmed_roster_entry(self, api, admin_headers):
        """PRD §3.8: "If that recomputation flips the member's `readiness_tier`
        to `INELIGIBLE`, the roster cascade fires: every roster entry the
        member holds on a live (`STANDBY` or `ACTIVATED`) activation is
        withdrawn — `VOLUNTEERED` entries and `CONFIRMED` entries alike — and
        each `CONFIRMED` withdrawal recomputes its activation's
        `confirmed_count` and `staffing_posture`."
        PRD §3.1: "A member whose `equipment_privilege` is `SUSPENDED` takes a
        flat penalty of 50."

        Design: Difficulty/transitive_cascade/damaged_return_privilege_cascade
        """
        bundle = self._scenario(api, admin_headers)
        return_loan(bundle["loan"]["id"], bundle["member"]["id"], "DAMAGED")
        member_after = get_success_data(
            api.get_member(bundle["member"]["id"], admin_headers))
        # 85 - 50 privilege penalty = 35 < 40 -> INELIGIBLE.
        assert member_after["readiness_score"] == 35
        assert member_after["readiness_tier"] == "INELIGIBLE"
        entry_after = get_success_data(
            api.get_roster_entry(bundle["roster_entry"]["id"], admin_headers))
        assert entry_after["status"] == "WITHDRAWN"
        act_after = get_success_data(
            api.get_emergency_activation(bundle["activation"]["id"], admin_headers))
        assert act_after["confirmed_count"] == 0
        assert act_after["staffing_posture"] == "UNDERSTAFFED"
        assert_activation_invariants(act_after)
