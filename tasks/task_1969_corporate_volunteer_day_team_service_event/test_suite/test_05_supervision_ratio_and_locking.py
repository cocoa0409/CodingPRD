"""Supervision ratio formula, the 8:1 boundary, the lock/demote/re-lock cycle,
and the event-state gate on locking."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_signed_registration,
    assign_lead,
    begin_ready_event,
    confirm_registration,
    create_order,
    create_received_order,
    create_volunteer,
    get_event,
    get_project,
    lock_project,
    make_staff_lead_headers,
    match_project,
    open_event_registration,
    register_volunteer,
    setup_matched_scenario,
    setup_ready_event,
    sign_waiver_guardian,
    sign_waiver_self,
    submit_order,
    approve_order,
    validate_error,
    validate_success,
    vet_project,
    withdraw_assignment,
    MINOR_DOB,
    LEAD_DOB,
    create_partner,
    create_project,
    create_event,
)

CEM = TEST_USERS["cem_headers"]


def _add_minor(sc, idx):
    teen = create_volunteer(
        f"Minor {idx}", f"m{idx}@corp.com", date_of_birth=MINOR_DOB, department="Intern"
    )
    reg = register_volunteer(teen, sc["event"]["id"], sc["project"]["id"], wants_meal=False)
    sign_waiver_guardian(reg["id"], teen, guardian_name=f"Guard {idx}")
    return teen, reg


class TestDualCeilingFormula:
    def test_one_adult_four_minors_requires_two_leads(self, api):
        """PRD §3.3: "Otherwise it is the confirmed adult count divided by 8 and rounded up to a whole number, plus the confirmed minor count divided by 4 and rounded up to a whole number — so exactly 8 confirmed adults need 1 lead while 9 need 2, and exactly 4 confirmed minors need 1 dedicated lead while 5 need 2."

        Design: Difficulty/combinatorial_formula/supervision_requirement_dual_ceiling_mixed_minors
        """
        sc = setup_matched_scenario(event_name="Day C", min_volunteers=1, max_volunteers=12)
        adult = create_volunteer("Adult A", "a@corp.com")
        reg_a = register_volunteer(
            adult, sc["event"]["id"], sc["project"]["id"], wants_meal=False
        )
        sign_waiver_self(reg_a["id"], adult)
        confirm_registration(reg_a["id"])
        minors = [_add_minor(sc, i) for i in range(1, 6)]
        for _, reg in minors[:4]:
            confirm_registration(reg["id"])

        # ceil(1/8) + ceil(4/4) = 1 + 1 = 2
        project = get_project(sc["project"]["id"])
        assert project["confirmed_volunteer_count"] == 5
        assert project["required_staff_leads"] == 2

    def test_fifth_minor_moves_only_the_minor_ceiling(self, api):
        """PRD §3.3: "Otherwise it is the confirmed adult count divided by 8 and rounded up to a whole number, plus the confirmed minor count divided by 4 and rounded up to a whole number — so exactly 8 confirmed adults need 1 lead while 9 need 2, and exactly 4 confirmed minors need 1 dedicated lead while 5 need 2."

        Design: Difficulty/combinatorial_formula/supervision_requirement_dual_ceiling_mixed_minors
        """
        sc = setup_matched_scenario(event_name="Day C2", min_volunteers=1, max_volunteers=12)
        adult = create_volunteer("Adult A", "a@corp.com")
        reg_a = register_volunteer(
            adult, sc["event"]["id"], sc["project"]["id"], wants_meal=False
        )
        sign_waiver_self(reg_a["id"], adult)
        confirm_registration(reg_a["id"])
        minors = [_add_minor(sc, i) for i in range(1, 6)]
        for _, reg in minors[:4]:
            confirm_registration(reg["id"])
        assert get_project(sc["project"]["id"])["required_staff_leads"] == 2

        # The 5th minor confirmation: ceil(1/8) + ceil(5/4) = 1 + 2 = 3
        confirm_registration(minors[4][1]["id"])
        project = get_project(sc["project"]["id"])
        assert project["required_staff_leads"] == 3
        assert project["confirmed_volunteer_count"] == 6


class TestEightAdultBoundary:
    def _setup_eight_confirmed(self):
        sc = setup_ready_event(
            event_name="Day K",
            num_adults=8,
            min_volunteers=8,
            max_volunteers=10,
            verify_waivers=False,
        )
        return sc

    def test_lock_succeeds_at_exactly_eight_confirmed_adults(self, api):
        """PRD §3.3: "so exactly 8 confirmed adults need 1 lead while 9 need 2, and exactly 4 confirmed minors need 1 dedicated lead while 5 need 2."
        PRD §3.3: "Third, supervision must be both present and sufficient: `required_staff_leads` must be at least 1, and `active_staff_leads` must be at least `required_staff_leads`, otherwise `ERR_INSUFFICIENT_SUPERVISION`."

        Design: Difficulty/boundary_precision_check/supervision_ratio_eight_adult_boundary_lock
        """
        sc = self._setup_eight_confirmed()
        # 8 confirmed adults -> required ceil(8/8) == 1, staffed by 1 ACTIVE lead
        assert sc["project"]["status"] == "LOCKED"
        project = get_project(sc["project"]["id"])
        assert project["required_staff_leads"] == 1
        assert project["confirmed_volunteer_count"] == 8

    def test_ninth_confirm_demotes_and_relock_is_rejected(self, api, cem_headers):
        """PRD §3.4: "A successful confirm increments the project's `confirmed_volunteer_count` by one and recomputes `required_staff_leads` per the supervision rule; if the project was `LOCKED` and the new requirement now exceeds `active_staff_leads`, the project automatically demotes `LOCKED` → `MATCHED` and the event's posture is recomputed."
        PRD §3.3: "Third, supervision must be both present and sufficient: `required_staff_leads` must be at least 1, and `active_staff_leads` must be at least `required_staff_leads`, otherwise `ERR_INSUFFICIENT_SUPERVISION`."

        Design: Difficulty/boundary_precision_check/supervision_ratio_eight_adult_boundary_lock
        """
        sc = self._setup_eight_confirmed()
        assert sc["project"]["status"] == "LOCKED"

        vol9 = create_volunteer("Vol 9", "vol9_boundary@corp.com")
        reg9 = register_volunteer(
            vol9, sc["event"]["id"], sc["project"]["id"], wants_meal=False
        )
        sign_waiver_self(reg9["id"], vol9)
        confirm_registration(reg9["id"])  # 9 confirmed adults -> required ceil(9/8) = 2 > 1 active

        project = get_project(sc["project"]["id"])
        assert project["status"] == "MATCHED", "9th confirm must auto-demote the LOCKED project"
        assert project["required_staff_leads"] == 2
        assert project["active_staff_leads"] == 1

        resp = api.lock_project(sc["project"]["id"], cem_headers)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_SUPERVISION)


class TestLockDemoteRelockCycle:
    def _setup_locked(self):
        return setup_ready_event(
            event_name="Day F", num_adults=3, verify_waivers=False
        )

    def test_withdraw_demotes_locked_project(self, api):
        """PRD §3.3: "The withdrawal decrements the project's `active_staff_leads`, and if the project is `LOCKED` and now has fewer active leads than required, the project automatically demotes from `LOCKED` back to `MATCHED` and the event's posture is recomputed."

        Design: Difficulty/non_linear_state_machine/project_lock_demote_relock_cycle
        """
        sc = self._setup_locked()
        assert sc["project"]["status"] == "LOCKED"

        # The lead withdraws their own assignment (X-User-ID == lead_volunteer_id)
        withdraw_assignment(
            sc["assignment"]["id"], make_staff_lead_headers(sc["lead"]["id"])
        )
        project = get_project(sc["project"]["id"])
        assert project["status"] == "MATCHED"
        assert project["active_staff_leads"] == 0

    def test_reassign_and_relock_completes_the_cycle(self, api, cem_headers):
        """PRD §3.3: "Once a project is staffed and stocked, a `CommunityEngagementManager` locks it, moving `MATCHED` → `LOCKED`; a project in any other from-state is rejected with `ERR_INVALID_PROJECT_TRANSITION`."
        PRD §3.3: "The withdrawal decrements the project's `active_staff_leads`, and if the project is `LOCKED` and now has fewer active leads than required, the project automatically demotes from `LOCKED` back to `MATCHED` and the event's posture is recomputed."

        Design: Difficulty/non_linear_state_machine/project_lock_demote_relock_cycle
        """
        sc = self._setup_locked()
        withdraw_assignment(
            sc["assignment"]["id"], make_staff_lead_headers(sc["lead"]["id"])
        )
        assert get_project(sc["project"]["id"])["status"] == "MATCHED"

        # Re-staff and re-lock: the cycle MATCHED -> LOCKED -> MATCHED -> LOCKED
        new_assignment = assign_lead(sc["project"]["id"], sc["lead"])
        assert new_assignment["status"] == "ACTIVE"
        resp = api.lock_project(sc["project"]["id"], cem_headers)
        assert validate_success(resp, 200)["status"] == "LOCKED"


class TestLockAfterEventBegins:
    def _setup_two_project_event(self):
        """Event IN_PROGRESS via P1 (LOCKED); P2 MATCHED with all local gates green."""
        partner = create_partner()
        proj1 = create_project(partner["id"], "Trail Repair")
        proj2 = create_project(partner["id"], "Fence Paint")
        event = create_event("Day N")
        vet_project(proj1["id"])
        vet_project(proj2["id"])
        match_project(proj1["id"], event["id"])
        match_project(proj2["id"], event["id"])
        event = open_event_registration(event["id"])
        vol1 = create_volunteer("Vol One", "v1@corp.com")
        vol2 = create_volunteer("Vol Two", "v2@corp.com")
        add_signed_registration(event["id"], proj1["id"], vol1, wants_meal=False, confirm=True)
        add_signed_registration(event["id"], proj2["id"], vol2, wants_meal=False, confirm=True)
        lead1 = create_volunteer("Lead One", "lead1@corp.com", date_of_birth=LEAD_DOB, is_staff_lead=True)
        lead2 = create_volunteer("Lead Two", "lead2@corp.com", date_of_birth="1986-04-04", is_staff_lead=True)
        assign_lead(proj1["id"], lead1)
        assign_lead(proj2["id"], lead2)
        create_received_order(event["id"], proj1["id"])
        create_received_order(
            event["id"],
            proj2["id"],
            lines=[{"item_name": "Paint", "quantity": 4, "unit_cost_cents": 700}],
        )
        lock_project(proj1["id"])
        begin_ready_event(event["id"])
        return {"partner": partner, "proj1": proj1, "proj2": proj2, "event": event}

    def test_project_lock_blocked_after_event_begins(self, api, cem_headers):
        """PRD §3.3: "First, the project's event must be in `REGISTRATION_OPEN` or `REGISTRATION_LOCKED` status — a project cannot be locked while its event is still `PLANNING` or already running — failing as `ERR_EVENT_STATE_FORBIDS_WRITE`."

        Design: Difficulty/cross_entity_state_dependency/project_lock_blocked_after_event_begins
        """
        sc = self._setup_two_project_event()
        resp = api.lock_project(sc["proj2"]["id"], cem_headers)
        validate_error(resp, ApiErrorId.ERR_EVENT_STATE_FORBIDS_WRITE)

    def test_unlocked_project_stays_matched_after_event_begins(self, api, cem_headers):
        """PRD §3.3: "First, the project's event must be in `REGISTRATION_OPEN` or `REGISTRATION_LOCKED` status — a project cannot be locked while its event is still `PLANNING` or already running — failing as `ERR_EVENT_STATE_FORBIDS_WRITE`."

        Design: Difficulty/cross_entity_state_dependency/project_lock_blocked_after_event_begins
        """
        sc = self._setup_two_project_event()
        api.lock_project(sc["proj2"]["id"], cem_headers)
        # Despite confirmed headcount, an ACTIVE lead, and a RECEIVED order (all the
        # project-local gates green), the project remains MATCHED
        project = get_project(sc["proj2"]["id"])
        assert project["status"] == "MATCHED"
        assert project["confirmed_volunteer_count"] == 1
        assert project["active_staff_leads"] == 1
        assert project["site_prep_complete"] is True
