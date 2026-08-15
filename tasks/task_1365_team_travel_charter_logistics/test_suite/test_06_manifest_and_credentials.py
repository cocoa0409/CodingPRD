"""Manifest capacity boundaries, bump/rebook conservation, credential cascades
(PRD §3.5, §3.10)."""
import pytest

from test_helpers import (
    TEST_USERS,
    add_manifest_entry, add_member, create_leg, confirm_manifest_entry,
    setup_approved_credential, setup_charter_leg_booked,
    validate_error, validate_success, get_success_data,
)

ANY = TEST_USERS["any_headers"]
MGR = TEST_USERS["manager_headers"]
COORD = TEST_USERS["coordinator_headers"]


def _entry(api, team_id, trip_id, leg_id, entry_id):
    return get_success_data(
        api.get_manifest_entry(team_id, trip_id, leg_id, entry_id, ANY))


def _two_seat_charter(api, num_members=2):
    """Booked charter leg on a 2-seat ACTIVE contract. Members must be added
    before booking (booking checks IN count against seat capacity)."""
    ctx = setup_charter_leg_booked(
        contract_overrides={"seat_capacity": 2, "cargo_capacity_lb": 5000},
        num_members=num_members,
        trip_overrides={"game_tipoff_utc": "2027-01-05T00:00:00Z",
                        "destination_code": "MIL"},
        leg_overrides={"scheduled_depart_utc": "2027-01-04T18:00:00Z",
                       "scheduled_arrive_utc": "2027-01-04T19:00:00Z"})
    return ctx


class TestManifestCapacityBoundary:
    def test_confirm_at_exact_capacity_then_overflow(self, api):
        """PRD §3.5: "at confirmation time the count of `CONFIRMED` entries must
        be strictly below `seat_capacity` — when the confirmed count equals
        `seat_capacity` minus one, exactly one more confirmation succeeds, and
        once the confirmed count equals `seat_capacity`, the next confirmation
        fails with `ERR_MANIFEST_FULL`."

        Design: Difficulty/boundary_precision_check/manifest_capacity_exactly_at_limit
        """
        ctx = _two_seat_charter(api, num_members=2)
        team_id, trip_id, leg_id = ctx["team"]["id"], ctx["trip"]["id"], ctx["leg"]["id"]
        m1, m2 = ctx["members"]
        # Third member added after booking (book-time IN-count check already passed).
        m3 = add_member(team_id, trip_id, member_ref="MC", party_role="COACH")

        e1 = add_manifest_entry(team_id, trip_id, leg_id, m1["id"], seat_assignment="1A")
        e2 = add_manifest_entry(team_id, trip_id, leg_id, m2["id"], seat_assignment="1B")
        e3 = add_manifest_entry(team_id, trip_id, leg_id, m3["id"], seat_assignment="1C")

        c1 = confirm_manifest_entry(team_id, trip_id, leg_id, e1["id"])
        assert c1["status"] == "CONFIRMED"
        c2 = confirm_manifest_entry(team_id, trip_id, leg_id, e2["id"])
        assert c2["status"] == "CONFIRMED", "confirmed count 1 == capacity - 1: one more succeeds"

        res = api.confirm_manifest_entry(team_id, trip_id, leg_id, e3["id"], COORD)
        validate_error(res, "ERR_MANIFEST_FULL", expected_status=409)
        assert _entry(api, team_id, trip_id, leg_id, e3["id"])["status"] == "PENDING"

    def test_capacity_one_boundary(self, api):
        """PRD §3.5: "once the confirmed count equals `seat_capacity`, the next
        confirmation fails with `ERR_MANIFEST_FULL`." With seat_capacity 1 the
        first confirmation succeeds and the second is rejected.

        Design: Difficulty/boundary_precision_check/manifest_capacity_exactly_at_limit
        """
        ctx = setup_charter_leg_booked(
            contract_overrides={"seat_capacity": 1, "cargo_capacity_lb": 5000},
            num_members=1,
            trip_overrides={"game_tipoff_utc": "2027-01-05T00:00:00Z"})
        team_id, trip_id, leg_id = ctx["team"]["id"], ctx["trip"]["id"], ctx["leg"]["id"]
        m1 = ctx["members"][0]
        m2 = add_member(team_id, trip_id, member_ref="MB", party_role="COACH")

        e1 = add_manifest_entry(team_id, trip_id, leg_id, m1["id"], seat_assignment="1A")
        e2 = add_manifest_entry(team_id, trip_id, leg_id, m2["id"], seat_assignment="1B")

        c1 = confirm_manifest_entry(team_id, trip_id, leg_id, e1["id"])
        assert c1["status"] == "CONFIRMED"
        res = api.confirm_manifest_entry(team_id, trip_id, leg_id, e2["id"], COORD)
        validate_error(res, "ERR_MANIFEST_FULL", expected_status=409)
        assert _entry(api, team_id, trip_id, leg_id, e2["id"])["status"] == "PENDING"


class TestSeatConservationAcrossBump:
    def test_bump_frees_seat_for_new_confirmation(self, api):
        """PRD §3.5: "The coordinator may bump a `CONFIRMED` entry to `BUMPED`,
        recording a `bump_reason` of `OVERBOOK`, `WEIGHT_BALANCE`,
        `SECURITY_DENIAL`, or `MEDICAL_SCRATCH`." Only CONFIRMED entries count
        against the capacity check of §3.5, so a bumped seat can be reoccupied
        exactly once.

        Design: Difficulty/compensating_invariant/manifest_seat_conservation_across_bump_rebook
        """
        ctx = _two_seat_charter(api, num_members=2)
        team_id, trip_id, leg_id = ctx["team"]["id"], ctx["trip"]["id"], ctx["leg"]["id"]
        m1, m2 = ctx["members"]

        e1 = add_manifest_entry(team_id, trip_id, leg_id, m1["id"], seat_assignment="1A")
        e2 = add_manifest_entry(team_id, trip_id, leg_id, m2["id"], seat_assignment="1B")
        confirm_manifest_entry(team_id, trip_id, leg_id, e1["id"])
        confirm_manifest_entry(team_id, trip_id, leg_id, e2["id"])

        bumped = validate_success(
            api.bump_manifest_entry(team_id, trip_id, leg_id, e1["id"],
                                    "WEIGHT_BALANCE", COORD), 200)
        assert bumped["status"] == "BUMPED"
        assert bumped["bump_reason"] == "WEIGHT_BALANCE"

        m3 = add_member(team_id, trip_id, member_ref="MM3", party_role="COACH")
        e3 = add_manifest_entry(team_id, trip_id, leg_id, m3["id"], seat_assignment="1A")
        c3 = confirm_manifest_entry(team_id, trip_id, leg_id, e3["id"])
        assert c3["status"] == "CONFIRMED", "the freed seat must be reoccupiable"

        statuses = {e["id"]: _entry(api, team_id, trip_id, leg_id, e["id"])["status"]
                    for e in (e1, e2, e3)}
        assert statuses[e1["id"]] == "BUMPED"
        assert statuses[e2["id"]] == "CONFIRMED"
        assert statuses[e3["id"]] == "CONFIRMED"
        confirmed_count = sum(1 for s in statuses.values() if s == "CONFIRMED")
        assert confirmed_count == 2, "conservation: confirmed <= seat_capacity preserved"

    def test_without_bump_third_confirmation_fails(self, api):
        """PRD §3.5: "once the confirmed count equals `seat_capacity`, the next
        confirmation fails with `ERR_MANIFEST_FULL`." Without a bump freeing a
        seat, no third confirmation is possible.

        Design: Difficulty/compensating_invariant/manifest_seat_conservation_across_bump_rebook
        """
        ctx = _two_seat_charter(api, num_members=2)
        team_id, trip_id, leg_id = ctx["team"]["id"], ctx["trip"]["id"], ctx["leg"]["id"]
        m1, m2 = ctx["members"]
        m3 = add_member(team_id, trip_id, member_ref="MM3", party_role="COACH")

        for m in (m1, m2):
            entry = add_manifest_entry(team_id, trip_id, leg_id, m["id"])
            confirm_manifest_entry(team_id, trip_id, leg_id, entry["id"])

        e3 = add_manifest_entry(team_id, trip_id, leg_id, m3["id"])
        res = api.confirm_manifest_entry(team_id, trip_id, leg_id, e3["id"], COORD)
        validate_error(res, "ERR_MANIFEST_FULL", expected_status=409)


class TestCredentialRevokeCascade:
    def _confirmed_entry_with_approved_credential(self, api, venue="BOS"):
        ctx = setup_charter_leg_booked(
            contract_overrides={"seat_capacity": 30, "cargo_capacity_lb": 15000},
            num_members=1,
            trip_overrides={"game_tipoff_utc": "2026-12-22T00:00:00Z",
                            "destination_code": venue},
            leg_overrides={"origin_code": "JFK", "destination_code": venue,
                           "scheduled_depart_utc": "2026-12-21T14:00:00Z",
                           "scheduled_arrive_utc": "2026-12-21T15:00:00Z"})
        member = ctx["members"][0]
        team_id, trip_id, leg_id = ctx["team"]["id"], ctx["trip"]["id"], ctx["leg"]["id"]
        cred = setup_approved_credential(team_id, trip_id, member["id"],
                                         venue_code=venue)
        entry = add_manifest_entry(team_id, trip_id, leg_id, member["id"],
                                   seat_assignment="1A")
        confirm_manifest_entry(team_id, trip_id, leg_id, entry["id"])
        ctx.update({"member": member, "cred": cred, "entry": entry})
        return ctx

    def test_revoke_bumps_confirmed_entries_with_security_denial(self, api):
        """PRD §3.10: "An approved credential may later be revoked by a
        `SecurityOfficer`; revocation moves `APPROVED` to `REVOKED` and applies
        the same manifest bump cascade with `SECURITY_DENIAL`." PRD §3.5: "a
        denied or revoked credential bumps the member's `CONFIRMED` entries on
        legs to that venue to `BUMPED` with `SECURITY_DENIAL`."

        Design: Difficulty/transitive_cascade/credential_revoke_cascade_depth2
        """
        from test_helpers import make_security_officer_headers
        ctx = self._confirmed_entry_with_approved_credential(api)
        team_id, trip_id = ctx["team"]["id"], ctx["trip"]["id"]

        revoked = validate_success(
            api.revoke_credential(team_id, trip_id, ctx["cred"]["id"],
                                  make_security_officer_headers("sec-officer-1")), 200)
        assert revoked["status"] == "REVOKED"

        entry = _entry(api, team_id, trip_id, ctx["leg"]["id"], ctx["entry"]["id"])
        assert entry["status"] == "BUMPED"
        assert entry["bump_reason"] == "SECURITY_DENIAL"

    def test_revoke_leaves_other_members_entries_untouched(self, api):
        """PRD §3.10: denial/revocation "bumps every `CONFIRMED` manifest entry
        for that member on legs to that venue with `bump_reason` `SECURITY_DENIAL`"
        — entries belonging to a different member are out of scope.

        Design: Difficulty/transitive_cascade/credential_revoke_cascade_depth2
        """
        from test_helpers import make_security_officer_headers
        ctx = self._confirmed_entry_with_approved_credential(api)
        team_id, trip_id, leg_id = ctx["team"]["id"], ctx["trip"]["id"], ctx["leg"]["id"]

        other = add_member(team_id, trip_id, member_ref="N02", party_role="COACH")
        # The leg's destination has a credential request on file, so the §3.5
        # venue credential gate is active: the second member must also hold an
        # APPROVED credential before their entry may confirm.
        setup_approved_credential(team_id, trip_id, other["id"],
                                  venue_code=ctx["leg"]["destination_code"])
        e2 = add_manifest_entry(team_id, trip_id, leg_id, other["id"],
                                seat_assignment="2A")
        confirm_manifest_entry(team_id, trip_id, leg_id, e2["id"])

        validate_success(
            api.revoke_credential(team_id, trip_id, ctx["cred"]["id"],
                                  make_security_officer_headers("sec-officer-1")), 200)

        e1_after = _entry(api, team_id, trip_id, leg_id, ctx["entry"]["id"])
        assert e1_after["status"] == "BUMPED"
        assert e1_after["bump_reason"] == "SECURITY_DENIAL"
        e2_after = _entry(api, team_id, trip_id, leg_id, e2["id"])
        assert e2_after["status"] == "CONFIRMED", \
            "the cascade is scoped to the revoked member's entries only"
