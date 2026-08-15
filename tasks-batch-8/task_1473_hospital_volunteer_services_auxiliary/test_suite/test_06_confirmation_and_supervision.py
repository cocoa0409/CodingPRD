"""Shift-assignment confirmation gates: state-first priority, cross-entity gates
(volunteer state, badge state), junior supervision (required / eligible / ratio),
and required annual training."""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_error_is_one_of, get_success_data,
    api_client, ApiErrorId,
    set_clock, create_cleared_volunteer, create_active_volunteer, create_department,
    create_role, create_open_request, create_published_shift, signup,
    confirm_assignment, enroll_and_complete_training,
    make_volunteer_headers,
)
from test_helpers import TEST_USERS

DIRECTOR = TEST_USERS["director_headers"]
COORDINATOR = TEST_USERS["coordinator_headers"]


def _junior_infra(slots=2, can_supervise=True, min_age=14, **role_extra):
    dept = create_department(name="Library Cart", head_user_id="dh-1")
    role = create_role(name="Book Cart Aide", category="COMMUNITY",
                       minimum_age=min_age, can_supervise_juniors=can_supervise,
                       **role_extra)
    request = create_open_request(dept["id"], role["id"], slots_needed=slots)
    return dept, role, request


def _junior(dept, role, request, name, email):
    return create_active_volunteer(dept, role, request, full_name=name,
                                   date_of_birth="2011-06-15", email=email)


class TestConfirmStateBeatsSafety:
    def _setup_cancelled_junior_assignment(self):
        set_clock("2026-08-01T00:00:00Z")
        dept, role, request = _junior_infra(slots=1)
        j_ctx = create_active_volunteer(dept, role, request, full_name="J Teen",
                                        date_of_birth="2011-06-15", email="j@x.org",
                                        phone="555-3001")
        shift = create_published_shift(dept["id"], role["id"], "2026-08-10T08:00:00Z",
                                       "2026-08-10T12:00:00Z", capacity=5)
        asg = signup(shift["id"], j_ctx["volunteer_id"])
        validate_success(api_client.cancel_assignment(asg["id"], COORDINATOR))
        return j_ctx, asg

    def test_state_error_beats_supervision_error(self, api):
        """PRD §2.8: "Checks are evaluated in a fixed thirteen-tier order, and the
        earliest failing tier wins — an earlier failure masks later ones, so the
        client always sees the same error for the same doubly-invalid request."
        (Tier 8, State preconditions — which lists ERR_ASSIGNMENT_INVALID_STATE —
        precedes tier 9, Minor-protection and training gates — which lists
        ERR_SUPERVISION_REQUIRED.)

        Design: Difficulty/priority_pair_validation_conflict/confirm_state_error_beats_safety_error
        """
        _, asg = self._setup_cancelled_junior_assignment()
        # CANCELLED junior assignment confirmed without a supervisor: both the
        # tier-8 state check and the tier-9 supervision check would fail.
        resp = api.confirm_assignment(asg["id"], {}, COORDINATOR)
        validate_error(resp, ApiErrorId.ERR_ASSIGNMENT_INVALID_STATE)

    def test_state_error_in_isolation_adult(self, api):
        """PRD §3.5: "Confirmation is the coordinator's final gate before service,
        moving `SIGNED_UP` → `CONFIRMED` — any other assignment state is
        `ERR_ASSIGNMENT_INVALID_STATE`."
        (Isolation control: an adult's cancelled assignment fails only the state
        gate — no supervision rule is in play.)

        Design: Difficulty/priority_pair_validation_conflict/confirm_state_error_beats_safety_error
        """
        set_clock("2026-08-01T00:00:00Z")
        dept = create_department(name="Emergency", head_user_id="dh-1")
        role = create_role(name="ED Greeter", category="PATIENT_FACING", minimum_age=18)
        request = create_open_request(dept["id"], role["id"], slots_needed=1)
        ctx = create_active_volunteer(dept, role, request, full_name="V Adult",
                                      email="va2@x.org")
        shift = create_published_shift(dept["id"], role["id"], "2026-08-10T08:00:00Z",
                                       "2026-08-10T12:00:00Z", capacity=5)
        asg = signup(shift["id"], ctx["volunteer_id"])
        validate_success(api.cancel_assignment(asg["id"], COORDINATOR))
        resp = api.confirm_assignment(asg["id"], {}, COORDINATOR)
        validate_error(resp, ApiErrorId.ERR_ASSIGNMENT_INVALID_STATE)


class TestConfirmCrossEntityGates:
    def _setup_signed_up(self):
        set_clock("2026-08-01T00:00:00Z")
        dept = create_department(name="Emergency", head_user_id="dh-1")
        role = create_role(name="ED Greeter", category="PATIENT_FACING", minimum_age=18)
        request = create_open_request(dept["id"], role["id"], slots_needed=1)
        ctx = create_active_volunteer(dept, role, request, full_name="V Gate",
                                      email="vg@x.org", phone="555-5001")
        shift = create_published_shift(dept["id"], role["id"], "2026-08-10T08:00:00Z",
                                       "2026-08-10T12:00:00Z", capacity=5)
        asg = signup(shift["id"], ctx["volunteer_id"])
        return ctx, asg

    def test_confirm_blocked_by_revoked_badge(self, api):
        """PRD §3.5: "The volunteer must be `ACTIVE` (`ERR_VOLUNTEER_INVALID_STATE`);
        posture must be fully `CLEAR`, since `RESTRICTED` is not good enough for
        confirmed service (`ERR_POSTURE_NOT_CLEAR`); and the volunteer must hold an
        `ISSUED` badge (`ERR_BADGE_INVALID_STATE`)."

        Design: Difficulty/cross_entity_state_dependency/confirm_gated_by_volunteer_and_badge_state
        """
        ctx, asg = self._setup_signed_up()
        validate_success(api.revoke_badge(ctx["badge"]["id"],
                                          {"reason": "security pull"}, COORDINATOR))
        # Volunteer still ACTIVE with posture CLEAR; only the badge gate fails.
        resp = api.confirm_assignment(asg["id"], {}, COORDINATOR)
        validate_error(resp, ApiErrorId.ERR_BADGE_INVALID_STATE)
        row = get_success_data(api.get_shift_assignment(asg["id"], COORDINATOR))
        assert row["status"] == "SIGNED_UP", "a failed confirm causes no drift"

    def test_confirm_blocked_by_suspended_volunteer(self, api):
        """PRD §3.5: "The volunteer must be `ACTIVE` (`ERR_VOLUNTEER_INVALID_STATE`)".
        (Suspension also flips the badge ISSUED → SUSPENDED per §3.4, so the badge
        gate fails too; either same-tier error satisfies the two-gate rule.)

        Design: Difficulty/cross_entity_state_dependency/confirm_gated_by_volunteer_and_badge_state
        """
        ctx, asg = self._setup_signed_up()
        validate_success(api.suspend_volunteer(ctx["volunteer_id"],
                                               {"reason": "investigation"}, COORDINATOR))
        resp = api.confirm_assignment(asg["id"], {}, COORDINATOR)
        validate_error_is_one_of(resp, [
            ApiErrorId.ERR_VOLUNTEER_INVALID_STATE,
            ApiErrorId.ERR_BADGE_INVALID_STATE,
        ])
        row = get_success_data(api.get_shift_assignment(asg["id"], COORDINATOR))
        assert row["status"] == "SIGNED_UP", "a failed confirm causes no drift"


class TestJuniorSupervision:
    def _setup_junior_and_adult(self):
        set_clock("2026-08-01T00:00:00Z")
        dept, role, request = _junior_infra(slots=2)
        j_ctx = _junior(dept, role, request, "J Teen", "j@x.org")
        a_ctx = create_active_volunteer(dept, role, request, full_name="A Adult",
                                        date_of_birth="1990-01-01", email="a@x.org",
                                        phone="555-3002")
        shift = create_published_shift(dept["id"], role["id"], "2026-08-10T08:00:00Z",
                                       "2026-08-10T12:00:00Z", capacity=5)
        asg_j = signup(shift["id"], j_ctx["volunteer_id"])
        asg_a = signup(shift["id"], a_ctx["volunteer_id"])
        return shift, asg_j, asg_a

    def test_supervision_required_and_ineligible(self, api):
        """PRD §3.5: "When the assignee is a junior at the shift's start date,
        supervision rules engage: the request must carry `supervisor_assignment_id`
        (`ERR_SUPERVISION_REQUIRED`), and that identifier must reference a
        `CONFIRMED` assignment on the same shift whose volunteer is at least 21 years
        old at the shift date and whose role has `can_supervise_juniors` true
        (`ERR_SUPERVISOR_INELIGIBLE`)".

        Design: Corner/errors/junior_confirm_supervision_required_and_ineligible
        """
        _, asg_j, asg_a = self._setup_junior_and_adult()

        resp = api.confirm_assignment(asg_j["id"], {}, COORDINATOR)
        validate_error(resp, ApiErrorId.ERR_SUPERVISION_REQUIRED)

        # The named supervisor assignment is on the same shift but only SIGNED_UP.
        resp = api.confirm_assignment(
            asg_j["id"], {"supervisor_assignment_id": asg_a["id"]}, COORDINATOR)
        validate_error(resp, ApiErrorId.ERR_SUPERVISOR_INELIGIBLE)

        row = get_success_data(api.get_shift_assignment(asg_j["id"], COORDINATOR))
        assert row["status"] == "SIGNED_UP", "both failures leave the junior SIGNED_UP"


class TestSupervisorRatio:
    def test_fourth_supervisee_rejected(self, api):
        """PRD §3.5: "counting this confirmation, that supervisor may not exceed three
        junior supervisees on the shift (`ERR_SUPERVISOR_RATIO_EXCEEDED`)".

        Design: Corner/errors/supervisor_ratio_1_to_3_exceeded
        """
        set_clock("2026-08-01T00:00:00Z")
        dept, role, request = _junior_infra(slots=5)
        sup_ctx = create_active_volunteer(dept, role, request, full_name="Sup Sam",
                                          date_of_birth="1990-01-01",
                                          email="sup@x.org", phone="555-3003")
        juniors = [
            _junior(dept, role, request, f"J {i}", f"j{i}@x.org")
            for i in ("One", "Two", "Three", "Four")
        ]
        shift = create_published_shift(dept["id"], role["id"], "2026-08-10T08:00:00Z",
                                       "2026-08-10T12:00:00Z", capacity=6)
        asg_sup = signup(shift["id"], sup_ctx["volunteer_id"])
        confirm_assignment(asg_sup["id"])
        asg_js = [signup(shift["id"], j["volunteer_id"]) for j in juniors]

        for asg_j in asg_js[:3]:
            confirmed = validate_success(api.confirm_assignment(
                asg_j["id"], {"supervisor_assignment_id": asg_sup["id"]}, COORDINATOR))
            assert confirmed["status"] == "CONFIRMED", "ratio 1:3 exactly is allowed"

        resp = api.confirm_assignment(
            asg_js[3]["id"], {"supervisor_assignment_id": asg_sup["id"]}, COORDINATOR)
        validate_error(resp, ApiErrorId.ERR_SUPERVISOR_RATIO_EXCEEDED)
        row = get_success_data(api.get_shift_assignment(asg_js[3]["id"], COORDINATOR))
        assert row["status"] == "SIGNED_UP"


class TestConfirmTrainingGate:
    def test_confirm_blocked_until_annual_training_valid(self, api):
        """PRD §3.5: "Every code in the shift role's `required_training_codes` must
        have a `VALID` training record for the volunteer
        (`ERR_TRAINING_REQUIREMENT_UNMET`)."

        Design: Corner/errors/confirm_blocked_by_missing_annual_training
        """
        set_clock("2026-08-01T00:00:00Z")
        dept = create_department(name="Ward 4", head_user_id="dh-1")
        role = create_role(name="Ward Visitor", category="PATIENT_FACING",
                           minimum_age=18, required_training_codes=["HIPAA_ANNUAL"])
        request = create_open_request(dept["id"], role["id"], slots_needed=1)
        ctx = create_active_volunteer(dept, role, request, full_name="Train Tess",
                                      email="tt@x.org", phone="555-3004")
        shift = create_published_shift(dept["id"], role["id"], "2026-08-10T08:00:00Z",
                                       "2026-08-10T12:00:00Z", capacity=2)
        asg = signup(shift["id"], ctx["volunteer_id"])

        resp = api.confirm_assignment(asg["id"], {}, COORDINATOR)
        validate_error(resp, ApiErrorId.ERR_TRAINING_REQUIREMENT_UNMET)

        enroll_and_complete_training(ctx["volunteer_id"], "HIPAA_ANNUAL", "ANNUAL")
        confirmed = validate_success(api.confirm_assignment(asg["id"], {}, COORDINATOR))
        assert confirmed["status"] == "CONFIRMED"
        assert confirmed.get("confirmed_at") is not None
