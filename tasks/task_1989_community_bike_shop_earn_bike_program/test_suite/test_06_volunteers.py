"""Volunteer dual-dimension state machine (queue A), promotion boundary and
RBAC corner cases (queue B)."""
from test_helpers import (
    api_client, validate_success, validate_error,
    make_volunteer, attend_sessions, make_apprentice, set_clock,
    TEST_USERS, make_coordinator_headers,
    create_shift_payload,
    ApiErrorId,
)

COORD = TEST_USERS["coordinator_headers"]
DIRECTOR = TEST_USERS["director_headers"]


def _five_session_volunteer() -> dict:
    """Volunteer with 5 ATTENDED sessions (30h, 5 sessions), not yet promoted."""
    v = make_volunteer(full_name="V Dual", email="vd@x.org")
    attend_sessions(
        v["id"],
        [
            {"topic": "T1", "scheduled_start": "2026-08-02T10:00:00Z",
             "scheduled_end": "2026-08-02T11:00:00Z", "credit_hours": 6},
            {"topic": "T2", "scheduled_start": "2026-08-03T10:00:00Z",
             "scheduled_end": "2026-08-03T11:00:00Z", "credit_hours": 6},
            {"topic": "T3", "scheduled_start": "2026-08-04T10:00:00Z",
             "scheduled_end": "2026-08-04T11:00:00Z", "credit_hours": 6},
            {"topic": "T4", "scheduled_start": "2026-08-05T10:00:00Z",
             "scheduled_end": "2026-08-05T11:00:00Z", "credit_hours": 6},
            {"topic": "T5", "scheduled_start": "2026-08-06T10:00:00Z",
             "scheduled_end": "2026-08-06T11:00:00Z", "credit_hours": 6},
        ],
    )
    return validate_success(api_client.get_volunteer(v["id"], COORD))


class TestVolunteerDualDimensions:
    def test_suspension_blocks_promote_and_shift_but_preserves_skill(self):
        """PRD §3.5: "Skill and engagement are independent dimensions on the
        same record: a journeyman can be suspended, and a trainee can be in
        perfect standing." and "promoting a suspended volunteer is rejected with
        `ERR_VOLUNTEER_SUSPENDED`." and PRD §3.6: "the volunteer must be
        `ACTIVE`, else `ERR_VOLUNTEER_SUSPENDED`."

        Design: Difficulty/non_linear_state_machine/volunteer_dual_dimensions_independent
        """
        v = _five_session_volunteer()
        validate_success(api_client.promote_volunteer(v["id"], DIRECTOR))
        suspended = validate_success(
            api_client.suspend_volunteer(v["id"], {"reason": "conduct"}, DIRECTOR)
        )
        assert suspended["engagement_status"] == "SUSPENDED"
        assert suspended["skill_level"] == "APPRENTICE"

        r_promote = api_client.promote_volunteer(v["id"], DIRECTOR)
        validate_error(r_promote, ApiErrorId.ERR_VOLUNTEER_SUSPENDED)
        r_shift = api_client.create_shift(
            create_shift_payload(
                v["id"], scheduled_start="2026-08-10T09:00:00Z",
                scheduled_end="2026-08-10T12:00:00Z",
            ),
            COORD,
        )
        validate_error(r_shift, ApiErrorId.ERR_VOLUNTEER_SUSPENDED)

    def test_reinstate_resets_strikes_and_preserves_skill(self):
        """PRD §3.5: "Reinstatement by a director flips the volunteer back to
        `ACTIVE`, resets `no_show_count` to 0, and preserves `skill_level`
        exactly as it was." and "`APPRENTICE → JOURNEYMAN` requires at least 24
        training hours and at least 5 sessions."

        Design: Difficulty/non_linear_state_machine/volunteer_dual_dimensions_independent
        """
        v = _five_session_volunteer()
        validate_success(api_client.promote_volunteer(v["id"], DIRECTOR))
        validate_success(
            api_client.suspend_volunteer(v["id"], {"reason": "conduct"}, DIRECTOR)
        )
        reinstated = validate_success(api_client.reinstate_volunteer(v["id"], DIRECTOR))
        assert reinstated["engagement_status"] == "ACTIVE"
        assert reinstated["no_show_count"] == 0
        assert reinstated["skill_level"] == "APPRENTICE"
        # post-reinstate promotion succeeds (30h >= 24 and 5 sessions >= 5)
        promoted = validate_success(api_client.promote_volunteer(v["id"], DIRECTOR))
        assert promoted["skill_level"] == "JOURNEYMAN"


class TestPromotionBoundary:
    def test_promotion_exact_threshold_boundary(self):
        """PRD §3.5: "Promotion advances a volunteer exactly one level per call,
        and the thresholds are inclusive — meeting the exact boundary is
        eligible. `TRAINEE → APPRENTICE` requires at least 8 `training_hours`
        and at least 2 `sessions_attended`." and "Falling short on any leg is
        rejected with `ERR_PROMOTION_CRITERIA_NOT_MET`, and promoting a
        suspended volunteer is rejected with `ERR_VOLUNTEER_SUSPENDED`."

        Design: Corner/calculations/promotion_exact_threshold_boundary
        """
        v1 = make_volunteer(full_name="V Edge", email="ve@x.org")
        v2 = make_volunteer(full_name="V Short", email="vsh@x.org")
        # V1: two 4-credit sessions (8h / 2 sessions exactly)
        attend_sessions(
            v1["id"],
            [
                {"topic": "E1", "scheduled_start": "2026-08-02T10:00:00Z",
                 "scheduled_end": "2026-08-02T11:00:00Z", "credit_hours": 4},
                {"topic": "E2", "scheduled_start": "2026-08-03T10:00:00Z",
                 "scheduled_end": "2026-08-03T11:00:00Z", "credit_hours": 4},
            ],
        )
        # V2: one 4-credit session (4h / 1 session)
        attend_sessions(
            v2["id"],
            [
                {"topic": "S1", "scheduled_start": "2026-08-04T10:00:00Z",
                 "scheduled_end": "2026-08-04T11:00:00Z", "credit_hours": 4},
            ],
        )
        promoted = validate_success(api_client.promote_volunteer(v1["id"], DIRECTOR))
        assert promoted["skill_level"] == "APPRENTICE"
        r = api_client.promote_volunteer(v2["id"], DIRECTOR)
        validate_error(r, ApiErrorId.ERR_PROMOTION_CRITERIA_NOT_MET)
        v2_after = validate_success(api_client.get_volunteer(v2["id"], COORD))
        assert v2_after["skill_level"] == "TRAINEE"


class TestVolunteerRbac:
    def test_coordinator_cannot_promote_volunteer(self):
        """PRD §3.5: "Only a `ProgramDirector` promotes." and PRD §2.1: "A
        request whose authenticated role is not in the endpoint's authorized
        list, or whose entity-backed identity does not own the targeted
        resource, is rejected with `ERR_FORBIDDEN`."

        Design: Corner/rbac/coordinator_cannot_promote_volunteer
        """
        v = make_volunteer(full_name="V P", email="vp@x.org")
        attend_sessions(
            v["id"],
            [
                {"topic": "P1", "scheduled_start": "2026-08-02T10:00:00Z",
                 "scheduled_end": "2026-08-02T11:00:00Z", "credit_hours": 5},
                {"topic": "P2", "scheduled_start": "2026-08-03T10:00:00Z",
                 "scheduled_end": "2026-08-03T11:00:00Z", "credit_hours": 5},
            ],
        )
        r = api_client.promote_volunteer(v["id"], COORD)
        validate_error(r, ApiErrorId.ERR_FORBIDDEN)
        ok = validate_success(api_client.promote_volunteer(v["id"], DIRECTOR))
        assert ok["skill_level"] == "APPRENTICE"
