"""Deep cascades: clearance revocation freezes posture and refills from the
waitlist; separation rescinds placements and reopens requests; waitlist promotion
skips the ineligible; activation prerequisite gates."""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data,
    api_client, ApiErrorId,
    set_clock, approve_application, create_cleared_volunteer, create_active_volunteer,
    create_department, create_role, create_open_request, create_published_shift,
    create_offer, accept_placement, complete_orientation, submit_clearance,
    adjudicate_clearance, signup, get_summary, get_volunteer, get_volunteer_badge,
    make_volunteer_headers, make_screener_headers,
)
from test_helpers import TEST_USERS

DIRECTOR = TEST_USERS["director_headers"]
COORDINATOR = TEST_USERS["coordinator_headers"]
SCREENER_2 = TEST_USERS["screener2_headers"]


def _infra(dept_name="Emergency", role_name="ED Greeter", category="PATIENT_FACING",
           minimum_age=18, slots=2):
    dept = create_department(name=dept_name, head_user_id="dh-1")
    role = create_role(name=role_name, category=category, minimum_age=minimum_age)
    request = create_open_request(dept["id"], role["id"], slots_needed=slots)
    return dept, role, request


class TestClearanceRevokeCascade:
    def _setup(self):
        set_clock("2026-08-01T00:00:00Z")
        dept, role, request = _infra(slots=2)
        a = create_active_volunteer(dept, role, request, full_name="A Target",
                                    date_of_birth="1990-01-01", email="a@x.org",
                                    phone="555-2001")
        b = create_active_volunteer(dept, role, request, full_name="B Waiter",
                                    date_of_birth="1991-02-02", email="b@x.org",
                                    phone="555-2002")
        shift = create_published_shift(dept["id"], role["id"], "2026-08-10T08:00:00Z",
                                       "2026-08-10T12:00:00Z", capacity=1,
                                       allow_waitlist=True)
        asg_a = signup(shift["id"], a["volunteer_id"])
        asg_b = signup(shift["id"], b["volunteer_id"])
        assert asg_a["status"] == "SIGNED_UP"
        assert asg_b["status"] == "WAITLISTED"
        return a, b, shift, asg_a, asg_b

    def test_revoke_freezes_cancels_and_promotes(self, api):
        """PRD §3.2: "Revocation leaves the volunteer with no cleared record of that
        type, so the `compliance_posture` of §2.9 recomputes to `FROZEN` — and a
        posture that has flipped to `FROZEN` cascades immediately: every assignment
        of the volunteer in `SIGNED_UP`, `CONFIRMED`, or `WAITLISTED` whose shift
        starts after now is cancelled, and each such cancellation on a `PUBLISHED`
        shift runs the waitlist promotion of §3.5."

        Design: Difficulty/transitive_cascade/clearance_revoke_freeze_cancels_and_promotes
        """
        a, b, shift, asg_a, asg_b = self._setup()
        bg_id = a["clearances"]["BACKGROUND"]["id"]
        validate_success(api.revoke_clearance(bg_id, {"reason": "background recheck failed"},
                                              SCREENER_2))

        summary = get_summary(a["volunteer_id"])
        assert summary["compliance_posture"] == "FROZEN", (
            "posture recomputes live and drives the cascade")

        row_a = get_success_data(api.get_shift_assignment(asg_a["id"], COORDINATOR))
        assert row_a["status"] == "CANCELLED", "the frozen volunteer's future signup is cancelled"
        row_b = get_success_data(api.get_shift_assignment(asg_b["id"], COORDINATOR))
        assert row_b["status"] == "SIGNED_UP", (
            "the earliest-created eligible waitlisted row is promoted")

        shift_now = get_success_data(api.get_shift(shift["id"], COORDINATOR))
        assert shift_now["filled_count"] == 1, "1 - 1 + 1: no drift through the chain"

    def test_revoked_clearance_is_terminal(self, api):
        """PRD §3.2: "a `CLEARED` record moves to the terminal `REVOKED` (any other
        state, `ERR_CLEARANCE_INVALID_STATE`)."

        Design: Difficulty/transitive_cascade/clearance_revoke_freeze_cancels_and_promotes
        """
        a, b, shift, asg_a, asg_b = self._setup()
        bg_id = a["clearances"]["BACKGROUND"]["id"]
        revoked = validate_success(api.revoke_clearance(
            bg_id, {"reason": "background recheck failed"}, SCREENER_2))
        assert revoked["status"] == "REVOKED"

        resp = api.revoke_clearance(bg_id, {"reason": "again"}, SCREENER_2)
        validate_error(resp, ApiErrorId.ERR_CLEARANCE_INVALID_STATE)

        summary = get_summary(a["volunteer_id"])
        assert summary["compliance_posture"] == "FROZEN", (
            "posture stays FROZEN while no CLEARED record of that type exists")


class TestSeparationCascade:
    def _setup_filled_request(self, activate=True):
        set_clock("2026-08-01T00:00:00Z")
        dept = create_department(name="Oncology", head_user_id="dh-1")
        role = create_role(name="Chemo Companion", category="PATIENT_FACING",
                           minimum_age=18)
        request = create_open_request(dept["id"], role["id"], slots_needed=1)
        if activate:
            ctx = create_active_volunteer(dept, role, request, full_name="C Leaving",
                                          date_of_birth="1979-04-11", email="c@x.org",
                                          phone="555-2101")
        else:
            ctx0 = create_cleared_volunteer(full_name="C Leaving",
                                            date_of_birth="1979-04-11",
                                            email="c@x.org", phone="555-2101")
            placement = create_offer(request["id"], ctx0["volunteer_id"])
            placement = accept_placement(placement["id"], ctx0["volunteer_id"])
            ctx = {"volunteer_id": ctx0["volunteer_id"], "placement": placement,
                   "department": dept, "role": role, "request": request}
        mid = get_success_data(api_client.get_department_request(request["id"], COORDINATOR))
        assert mid["status"] == "FILLED", "setup sanity: 1 of 1 slot accepted"
        return ctx

    def test_separation_rescinds_and_reopens_request(self, api):
        """PRD §3.4: "Every placement in `ACCEPTED` is rescinded with slot
        compensation: its request's `slots_filled` decrements by one, and a request
        that was `FILLED` reverts to `OPEN` with `filled_at` cleared."
        PRD §3.4: "The volunteer's badge, whatever its live state (`PENDING`,
        `ISSUED`, or `SUSPENDED`), is `REVOKED` with `revoke_reason` `SEPARATION`."

        Design: Difficulty/transitive_cascade/separation_rescind_reopens_request
        """
        ctx = self._setup_filled_request(activate=True)
        vol_id = ctx["volunteer_id"]

        separated = validate_success(api.separate_volunteer(
            vol_id, {"separation_reason": "VOLUNTARY"}, DIRECTOR))
        assert separated["service_status"] == "SEPARATED"

        placement = get_success_data(api.get_placement(ctx["placement"]["id"], COORDINATOR))
        assert placement["status"] == "RESCINDED", (
            "the cascade rescinds the ACCEPTED placement (no direct call)")

        request = get_success_data(api.get_department_request(ctx["request"]["id"], COORDINATOR))
        assert request["status"] == "OPEN"
        assert request["slots_filled"] == 0
        assert request.get("filled_at") is None

        badge = get_success_data(api.get_badge(ctx["badge"]["id"], COORDINATOR))
        assert badge["badge_number"] == "BDG-000001"
        assert badge["status"] == "REVOKED"
        assert badge["revoke_reason"] == "SEPARATION"

    def test_onboarding_separation_same_compensation(self, api):
        """PRD §3.4: "Separation is the director's heaviest cascade, available from
        `ONBOARDING`, `ACTIVE`, or `SUSPENDED`" — the same slot-compensation chain
        applies when the volunteer never activated (badge still `PENDING`).

        Design: Difficulty/transitive_cascade/separation_rescind_reopens_request
        """
        ctx = self._setup_filled_request(activate=False)
        vol_id = ctx["volunteer_id"]
        volunteer = get_volunteer(vol_id)
        assert volunteer["service_status"] == "ONBOARDING"

        validate_success(api.separate_volunteer(
            vol_id, {"separation_reason": "VOLUNTARY"}, DIRECTOR))
        request = get_success_data(api.get_department_request(ctx["request"]["id"], COORDINATOR))
        assert request["status"] == "OPEN"
        assert request["slots_filled"] == 0
        assert request.get("filled_at") is None

        badges = get_success_data(api.list_badges(COORDINATOR, params={"volunteer_id": vol_id}))
        assert len(badges) == 1
        assert badges[0]["status"] == "REVOKED"
        assert badges[0]["revoke_reason"] == "SEPARATION"


class TestWaitlistPromotionSkipsIneligible:
    def test_suspended_top_candidate_skipped(self, api):
        """PRD §3.5: "Eligible candidates are those whose volunteer is `ACTIVE`,
        whose posture is not `FROZEN`, and whose other `SIGNED_UP` or `CONFIRMED`
        assignments do not half-open-overlap this shift. The earliest-created
        eligible candidate wins; an ineligible top candidate is skipped in favor of
        the next eligible one".

        Design: Corner/calculations/waitlist_promotion_skips_ineligible
        """
        set_clock("2026-08-01T00:00:00Z")
        dept, role, request = _infra(slots=3)
        w1 = create_active_volunteer(dept, role, request, full_name="W One",
                                     date_of_birth="1990-01-01", email="w1@x.org",
                                     phone="555-9601")
        w2 = create_active_volunteer(dept, role, request, full_name="W Two",
                                     date_of_birth="1991-01-01", email="w2@x.org",
                                     phone="555-9602")
        w3 = create_active_volunteer(dept, role, request, full_name="W Three",
                                     date_of_birth="1992-02-02", email="w3@x.org",
                                     phone="555-9603")
        shift = create_published_shift(dept["id"], role["id"], "2026-08-10T08:00:00Z",
                                       "2026-08-10T12:00:00Z", capacity=1,
                                       allow_waitlist=True)
        asg1 = signup(shift["id"], w1["volunteer_id"])
        asg2 = signup(shift["id"], w2["volunteer_id"])   # WAITLISTED (earlier)
        asg3 = signup(shift["id"], w3["volunteer_id"])   # WAITLISTED (later)
        assert asg2["status"] == "WAITLISTED" and asg3["status"] == "WAITLISTED"

        validate_success(api.suspend_volunteer(w2["volunteer_id"],
                                               {"reason": "investigation"}, COORDINATOR))
        validate_success(api.cancel_assignment(asg1["id"], COORDINATOR))

        row2 = get_success_data(api.get_shift_assignment(asg2["id"], COORDINATOR))
        assert row2["status"] == "WAITLISTED", "SUSPENDED volunteer is ineligible at promotion"
        row3 = get_success_data(api.get_shift_assignment(asg3["id"], COORDINATOR))
        assert row3["status"] == "SIGNED_UP", "the next eligible row is promoted instead"
        shift_now = get_success_data(api.get_shift(shift["id"], COORDINATOR))
        assert shift_now["filled_count"] == 1


class TestActivatePrerequisites:
    def test_three_isolated_gate_failures(self, api):
        """PRD §3.4: "Beyond the state gate, four requirements stand: the
        `ORIENTATION` training record exists and is `VALID`
        (`ERR_ORIENTATION_INCOMPLETE`); for each of the three clearance types, the
        volunteer's latest-created clearance of that type is `CLEARED` with
        `expires_at` strictly after now (`ERR_CLEARANCE_REQUIREMENTS_UNMET`); at
        least one placement stands `ACCEPTED` (`ERR_NO_ACCEPTED_PLACEMENT`); and a
        badge in `PENDING` exists for the volunteer (`ERR_BADGE_INVALID_STATE`)."

        Design: Corner/errors/activate_prerequisite_failures
        """
        set_clock("2026-08-01T00:00:00Z")
        dept = create_department(name="Emergency", head_user_id="dh-1")
        role = create_role(name="ED Greeter", category="PATIENT_FACING", minimum_age=18)
        request = create_open_request(dept["id"], role["id"], slots_needed=3)

        # A: clearances + placement OK, ORIENTATION still PENDING
        _, vA = approve_application(full_name="A NoOrient", email="a1@x.org",
                                    phone="555-3011")
        for ctype in ("BACKGROUND", "HEALTH_TB", "HEALTH_FLU"):
            row = submit_clearance(vA, ctype, f"{ctype.lower()}-a")
            adjudicate_clearance(row["id"], "CLEARED")
        pA = create_offer(request["id"], vA)
        accept_placement(pA["id"], vA)
        resp = api.activate_volunteer(vA, COORDINATOR)
        validate_error(resp, ApiErrorId.ERR_ORIENTATION_INCOMPLETE)

        # C: orientation + all clearances OK, no placement at all
        _, vC = approve_application(full_name="C NoPlace", email="c1@x.org",
                                    phone="555-3013")
        for ctype in ("BACKGROUND", "HEALTH_TB", "HEALTH_FLU"):
            row = submit_clearance(vC, ctype, f"{ctype.lower()}-c")
            adjudicate_clearance(row["id"], "CLEARED")
        complete_orientation(vC)
        resp = api.activate_volunteer(vC, COORDINATOR)
        validate_error(resp, ApiErrorId.ERR_NO_ACCEPTED_PLACEMENT)

        # B: all gates pass at setup; then the clock moves so B's 12-month health
        # clearances lapse PAST expiry but inside the 30-day grace window (posture
        # RESTRICTED, not FROZEN — so placement accept stays legal per §3.3 while
        # the activation clearance gate fails on expires_at <= now).
        _, vB = approve_application(full_name="B NoFlu", email="b1@x.org",
                                    phone="555-3012")
        for ctype in ("BACKGROUND", "HEALTH_TB", "HEALTH_FLU"):
            row = submit_clearance(vB, ctype, f"{ctype.lower()}-b")
            adjudicate_clearance(row["id"], "CLEARED")
        complete_orientation(vB)
        set_clock("2027-08-15T00:00:00Z")  # TB/FLU expired 2027-08-01, inside grace
        pB = create_offer(request["id"], vB)
        accept_placement(pB["id"], vB)
        resp = api.activate_volunteer(vB, COORDINATOR)
        validate_error(resp, ApiErrorId.ERR_CLEARANCE_REQUIREMENTS_UNMET)

        for vol_id in (vA, vB, vC):
            assert get_volunteer(vol_id)["service_status"] == "ONBOARDING"
