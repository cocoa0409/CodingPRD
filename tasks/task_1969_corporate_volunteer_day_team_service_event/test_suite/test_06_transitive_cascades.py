"""Transitive cascades: waiver-version bump (depth 4) and supervision withdraw (depth 2)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    get_assignment,
    get_event,
    get_project,
    get_registration,
    setup_ready_event,
    validate_success,
    withdraw_assignment,
)

CEM = TEST_USERS["cem_headers"]


class TestWaiverVersionBumpCascade:
    def _setup_ready_verified(self):
        """READY event: 1 CONFIRMED adult whose waiver is VERIFIED at document version 1."""
        return setup_ready_event(event_name="Day G", verify_waivers=True)

    def test_bump_voids_waiver_and_demotes_rsvp(self, api, cem_headers):
        """PRD §3.4: "When the legal text changes mid-cycle, a manager advances the event's `waiver_document_version` by exactly 1. Every waiver whose `waiver_signed_version` is below the new version and currently `WAIVER_SIGNED` or `WAIVER_VERIFIED` is automatically moved to `WAIVER_VOIDED`. Each affected registration whose `rsvp_status` was `CONFIRMED` demotes back to `REGISTERED`, decrementing the project's `confirmed_volunteer_count` and recomputing `required_staff_leads`; when a `LOCKED` project thereby falls below `min_volunteers` or has its requirement exceed its active leads, it demotes `LOCKED` → `MATCHED`."

        Design: Difficulty/transitive_cascade/waiver_version_bump_four_link_cascade
        """
        sc = self._setup_ready_verified()
        event_id = sc["event"]["id"]
        reg_id = sc["registrations"][0]["id"]
        assert get_event(event_id)["waiver_document_version"] == 1

        validate_success(api.bump_waiver_version(event_id, cem_headers), 200)

        reg = get_registration(reg_id)
        assert reg["waiver_status"] == "WAIVER_VOIDED"  # link 1
        assert reg["rsvp_status"] == "REGISTERED"  # link 2: demoted from CONFIRMED
        assert get_event(event_id)["waiver_document_version"] == 2

    def test_bump_demotes_project_and_degrades_posture(self, api, cem_headers):
        """PRD §3.4: "when a `LOCKED` project thereby falls below `min_volunteers` or has its requirement exceed its active leads, it demotes `LOCKED` → `MATCHED`. The event's posture recomputes and its `version` increments by 1."
        PRD §2.7: "A posture that was `READY` therefore degrades to `PARTIAL` the moment any single condition breaks — a lead withdraws, a confirm pushes the supervision requirement above the staffed leads, an order goes back into the approval pipeline, a project demotes — which is exactly the mechanism that keeps an unready event from starting."

        Design: Difficulty/transitive_cascade/waiver_version_bump_four_link_cascade
        """
        sc = self._setup_ready_verified()
        event_id = sc["event"]["id"]
        assert get_event(event_id)["readiness_posture"] == "READY"

        validate_success(api.bump_waiver_version(event_id, cem_headers), 200)

        project = get_project(sc["project"]["id"])
        assert project["status"] == "MATCHED"  # link 3: auto-demoted off 0 < min 1
        assert project["confirmed_volunteer_count"] == 0
        event = get_event(event_id)
        assert event["readiness_posture"] == "PARTIAL"  # link 4
        assert event["waiver_document_version"] == 2


class TestSupervisionWithdrawCascade:
    def _setup_ready(self):
        return setup_ready_event(event_name="Day H", verify_waivers=False)

    def test_withdraw_demotes_locked_project(self, api, cem_headers):
        """PRD §3.3: "The withdrawal decrements the project's `active_staff_leads`, and if the project is `LOCKED` and now has fewer active leads than required, the project automatically demotes from `LOCKED` back to `MATCHED` and the event's posture is recomputed."

        Design: Difficulty/transitive_cascade/supervision_withdraw_posture_cascade
        """
        sc = self._setup_ready()
        assert get_event(sc["event"]["id"])["readiness_posture"] == "READY"

        withdrawn = validate_success(
            api.withdraw_supervision_assignment(sc["assignment"]["id"], cem_headers), 200
        )
        assert withdrawn["status"] == "WITHDRAWN"

        project = get_project(sc["project"]["id"])
        assert project["status"] == "MATCHED"  # link 1
        assert project["active_staff_leads"] == 0
        assert project["required_staff_leads"] == 1

    def test_withdraw_degrades_event_posture(self, api, cem_headers):
        """PRD §2.7: "A posture that was `READY` therefore degrades to `PARTIAL` the moment any single condition breaks — a lead withdraws, a confirm pushes the supervision requirement above the staffed leads, an order goes back into the approval pipeline, a project demotes — which is exactly the mechanism that keeps an unready event from starting."

        Design: Difficulty/transitive_cascade/supervision_withdraw_posture_cascade
        """
        sc = self._setup_ready()
        assert get_event(sc["event"]["id"])["readiness_posture"] == "READY"

        withdraw_assignment(sc["assignment"]["id"])

        assert get_project(sc["project"]["id"])["status"] == "MATCHED"
        assert get_event(sc["event"]["id"])["readiness_posture"] == "PARTIAL"  # link 2
        assert get_assignment(sc["assignment"]["id"])["status"] == "WITHDRAWN"
