"""Volunteer reliability, shift claiming, overlap and skill gates (PRD §3.8)."""
from test_helpers import (
    api_client, TEST_USERS, ApiErrorId,
    validate_success, validate_error, get_success_data,
    barn_shift_payload,
    make_volunteer_headers,
    register_volunteer, create_shift, claim_shift, get_volunteer,
)

VOL_COORD = TEST_USERS["vol_coordinator_headers"]


class TestClaimReleaseCycle:
    def test_shift_claim_release_reclaim_cycle(self):
        """PRD §3.8: "A successful claim moves the shift `OPEN` → `ASSIGNED` and
        sets `volunteer_id` to the caller."
        PRD §3.8: "Releasing a shift — allowed only to the assigned volunteer
        (`ERR_FORBIDDEN`) and only from `ASSIGNED` — returns it to `OPEN` and
        clears `volunteer_id` to null."

        Design: Corner/state_machines/shift_claim_release_reclaim_cycle
        """
        v1 = register_volunteer(name="V1", contact_email="v1@x.com")
        v2 = register_volunteer(name="V2", contact_email="v2@x.com")
        shift = create_shift(shift_date="2026-08-05T00:00:00Z",
                             start_time="06:00", end_time="08:00",
                             barn_zone="MAIN_BARN", required_skill="FEEDING")

        claimed = claim_shift(shift["id"], v1["id"])
        assert claimed["status"] == "ASSIGNED"
        assert claimed["volunteer_id"] == v1["id"]

        released = validate_success(api_client.release_barn_shift(
            shift["id"], make_volunteer_headers(v1["id"])))
        assert released["status"] == "OPEN"
        assert released["volunteer_id"] is None

        reclaimed = claim_shift(shift["id"], v2["id"])
        assert reclaimed["status"] == "ASSIGNED"
        assert reclaimed["volunteer_id"] == v2["id"]


class TestReliabilityAndSuspension:
    def test_no_show_twice_suspends_volunteer(self):
        """PRD §3.8: "Marking a no-show (`ASSIGNED` → `NO_SHOW`) increments
        `no_show_count` by one, recomputes reliability, and — when the recomputed
        score falls below 20 — automatically moves the volunteer to `SUSPENDED`."
        PRD §3.8: "the score is 50, plus 5 for every completed shift, minus 20 for
        every no-show, clamped so it never falls below 0 or rises above 100."
        PRD §3.8: "the caller's volunteer record must be `ACTIVE`
        (`ERR_VOLUNTEER_NOT_ACTIVE`)"

        Design: Corner/state_machines/no_show_twice_suspends_volunteer
        """
        v = register_volunteer()
        s1 = create_shift(shift_date="2026-08-05T00:00:00Z", start_time="06:00",
                          end_time="08:00")
        s2 = create_shift(shift_date="2026-08-05T00:00:00Z", start_time="08:00",
                          end_time="10:00")
        s3 = create_shift(shift_date="2026-08-05T00:00:00Z", start_time="10:00",
                          end_time="12:00")
        claim_shift(s1["id"], v["id"])
        claim_shift(s2["id"], v["id"])

        get_success_data(api_client.mark_barn_shift_no_show(s1["id"], VOL_COORD))
        mid = get_volunteer(v["id"])
        assert mid["reliability_score"] == 30, "50 - 20"
        assert mid["status"] == "ACTIVE", "no suspension at exactly 30"

        get_success_data(api_client.mark_barn_shift_no_show(s2["id"], VOL_COORD))
        after = get_volunteer(v["id"])
        assert after["reliability_score"] == 10, "50 - 20 - 20"
        assert after["status"] == "SUSPENDED", "10 < 20 floor crossed"

        resp = api_client.claim_barn_shift(
            s3["id"], make_volunteer_headers(v["id"]))
        validate_error(resp, ApiErrorId.ERR_VOLUNTEER_NOT_ACTIVE, 422)

    def test_reliability_gate_boundary(self):
        """PRD §3.8: "the caller's `reliability_score` must be at least 40 —
        exactly 40 is allowed — (`ERR_RELIABILITY_TOO_LOW`)"
        PRD §3.8: "Completing one (`ASSIGNED` → `COMPLETED`) increments the
        volunteer's `completed_shift_count` by one and recomputes reliability."

        Design: Corner/calculations/reliability_gate_boundary
        """
        v = register_volunteer()
        shifts = [create_shift(shift_date="2026-08-05T00:00:00Z",
                               start_time=start, end_time=end)
                  for start, end in (("06:00", "08:00"), ("08:00", "10:00"),
                                     ("10:00", "12:00"), ("12:00", "14:00"))]
        s1, s2, s3, s4 = [s["id"] for s in shifts]
        claim_shift(s1, v["id"])
        claim_shift(s2, v["id"])
        claim_shift(s3, v["id"])

        get_success_data(api_client.mark_barn_shift_no_show(s1, VOL_COORD))
        resp = api_client.claim_barn_shift(s4, make_volunteer_headers(v["id"]))
        validate_error(resp, ApiErrorId.ERR_RELIABILITY_TOO_LOW, 422)

        get_success_data(api_client.complete_barn_shift(s2, VOL_COORD))
        get_success_data(api_client.complete_barn_shift(s3, VOL_COORD))
        assert get_volunteer(v["id"])["reliability_score"] == 40, (
            "50 - 20 + 5 + 5")

        claimed = claim_shift(s4, v["id"])
        assert claimed["status"] == "ASSIGNED"
        assert claimed["volunteer_id"] == v["id"], (
            "exactly 40 passes the >= 40 gate")


class TestSkillAndOverlapGates:
    def test_shift_overlap_priority_over_skill(self):
        """PRD §2.7: "Evaluation stops at the first failing tier, so the error a
        caller receives is always the highest-priority failure their request would
        have produced."
        PRD §2.7: "16. **Volunteer shift overlap.** A volunteer's assigned shifts
        on a date must not overlap as half-open intervals; failure is
        `ERR_SHIFT_OVERLAP` (HTTP 422)."
        PRD §2.7: "23. **Specialty, skill, and reliability gates.** The booked
        practitioner's specialty must cover the requested service
        (`ERR_SERVICE_SPECIALTY_MISMATCH`); the claiming volunteer must be
        `ACTIVE` (`ERR_VOLUNTEER_NOT_ACTIVE`), must clear the reliability floor
        (`ERR_RELIABILITY_TOO_LOW`), and must hold the required skill
        (`ERR_SKILL_MISMATCH`). All HTTP 422."

        Design: Corner/validations/shift_overlap_priority_over_skill
        """
        v = register_volunteer()  # skills [FEEDING]
        sb = create_shift(shift_date="2026-08-05T00:00:00Z", start_time="09:00",
                          end_time="10:00", barn_zone="MAIN_BARN",
                          required_skill="FEEDING")
        claim_shift(sb["id"], v["id"])
        sc = create_shift(shift_date="2026-08-05T00:00:00Z", start_time="09:30",
                          end_time="10:30", barn_zone="MAIN_BARN",
                          required_skill="HANDLING")
        resp = api_client.claim_barn_shift(sc["id"], make_volunteer_headers(v["id"]))
        validate_error(resp, ApiErrorId.ERR_SHIFT_OVERLAP, 422)

    def test_skill_mismatch_rejected(self):
        """PRD §3.8: "the shift's `required_skill` must be `ANY` or appear among
        the caller's `skills` (`ERR_SKILL_MISMATCH`)"

        Design: Corner/validations/skill_mismatch_rejected
        """
        v = register_volunteer()  # skills [FEEDING]
        sh1 = create_shift(shift_date="2026-08-06T00:00:00Z", start_time="09:00",
                           end_time="10:00", barn_zone="PASTURES",
                           required_skill="HANDLING")
        sh2 = create_shift(shift_date="2026-08-06T00:00:00Z", start_time="10:00",
                           end_time="11:00", barn_zone="PASTURES",
                           required_skill="ANY")
        resp = api_client.claim_barn_shift(
            sh1["id"], make_volunteer_headers(v["id"]))
        validate_error(resp, ApiErrorId.ERR_SKILL_MISMATCH, 422)
        claimed = claim_shift(sh2["id"], v["id"])
        assert claimed["status"] == "ASSIGNED", "ANY bypasses the skill gate"
