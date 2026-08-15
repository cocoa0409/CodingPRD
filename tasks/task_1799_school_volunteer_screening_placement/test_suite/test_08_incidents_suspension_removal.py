"""Incident reporting, suspension cascades, reinstatement, and removal."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    adjudicate_incident,
    assert_clock_instant,
    check_in_volunteer,
    confirm_placement,
    create_active_volunteer,
    create_core_module_never_expires,
    create_lincoln_campus,
    create_open_opportunity,
    create_volunteer_applied,
    file_incident,
    get_opportunity,
    get_placement,
    get_success_data,
    get_volunteer,
    initiate_background_check,
    record_training,
    request_placement,
    set_clock,
    setup_volunteer_with_confirmed_placement,
    validate_error,
    validate_paginated,
    validate_success,
)

DC = TEST_USERS["coordinator_headers"]
CA = TEST_USERS["campus_admin_headers"]


class TestSuspensionCascade:
    def test_high_incident_suspends_with_full_cascade(self, api):
        """PRD: "Filing a `HIGH` report against a volunteer in `ACTIVE`,
        `RESCREEN_REQUIRED`, or `CLEARANCE_GRANTED` suspends them on the spot:
        the volunteer's status becomes `SUSPENDED`, `prior_status` records the
        status held at the moment of suspension, and `suspension_incident_id`
        records the new report's `id` so the system remembers which incident
        caused the suspension. The suspension cascade then releases the
        volunteer's commitments — every `CONFIRMED` placement is cancelled with
        `cancel_reason` `SYSTEM_SUSPENSION` and each affected opportunity's
        `committed_count` and `projected_count` are recomputed — and
        force-closes every `OPEN` campus visit with `close_reason`
        `SYSTEM_SUSPENSION`."
        PRD: "Visits can also be closed without anyone at the door: the
        suspension and removal cascades of §3.7 force-close every `OPEN` visit
        of the affected volunteer, stamping `checked_out_at` and recording
        `close_reason` as `SYSTEM_SUSPENSION` or `SYSTEM_REMOVAL`"

        Design: Difficulty/transitive_cascade/incident_suspension_cascade
        """
        scenario = setup_volunteer_with_confirmed_placement(
            full_name="Suspense Sue", email="sue@x.com")
        vid = scenario["volunteer"]["id"]
        placement = scenario["placement"]
        campus = scenario["campus"]
        opp = scenario["opportunity"]

        set_clock("2026-08-10T13:30:00Z")
        visit = check_in_volunteer(campus["id"], vid,
                                   placement_id=placement["id"])
        assert visit["badge_code"] == "LNC-0001"

        incident = file_incident(vid, severity="HIGH",
                                 description="Shouting match in the library",
                                 placement_id=placement["id"])
        assert incident["status"] == "OPEN"

        volunteer = get_volunteer(vid)
        assert volunteer["status"] == "SUSPENDED"
        assert volunteer["prior_status"] == "ACTIVE"
        assert volunteer["suspension_incident_id"] == incident["id"]

        placement_after = get_placement(placement["id"])
        assert placement_after["status"] == "CANCELLED"
        assert placement_after["cancel_reason"] == "SYSTEM_SUSPENSION"

        opp_after = get_opportunity(opp["id"])
        assert opp_after["committed_count"] == 0
        assert opp_after["projected_count"] == 0

        visit_after = get_success_data(api.get_check_in(visit["id"], DC))
        assert visit_after["status"] == "CLOSED"
        assert visit_after["close_reason"] == "SYSTEM_SUSPENSION"
        assert_clock_instant(visit_after["checked_out_at"],
                             "2026-08-10T13:30:00")

    def test_high_incident_cancels_confirmed_placement_and_recomputes(self, api):
        """PRD: "The suspension cascade then releases the volunteer's
        commitments — every `CONFIRMED` placement is cancelled with
        `cancel_reason` `SYSTEM_SUSPENSION` and each affected opportunity's
        `committed_count` and `projected_count` are recomputed — and
        force-closes every `OPEN` campus visit with `close_reason`
        `SYSTEM_SUSPENSION`. The volunteer's `version` increments by one when
        the suspension fires."

        Design: Difficulty/transitive_cascade/incident_suspension_cascade
        """
        scenario = setup_volunteer_with_confirmed_placement(
            full_name="Cascade Cody", email="cody@x.com")
        vid = scenario["volunteer"]["id"]
        placement = scenario["placement"]
        opp = scenario["opportunity"]
        version_before = get_volunteer(vid)["version"]

        incident = file_incident(vid, severity="HIGH",
                                 description="Argument with staff")

        volunteer = get_volunteer(vid)
        assert volunteer["status"] == "SUSPENDED"
        assert volunteer["prior_status"] == "ACTIVE"
        assert volunteer["suspension_incident_id"] == incident["id"]
        assert volunteer["version"] == version_before + 1

        placement_after = get_placement(placement["id"])
        assert placement_after["status"] == "CANCELLED"
        assert placement_after["cancel_reason"] == "SYSTEM_SUSPENSION"

        opp_after = get_opportunity(opp["id"])
        assert opp_after["committed_count"] == 0
        assert opp_after["projected_count"] == 0


class TestSubstantiatedRemoval:
    def test_substantiated_removes_volunteer_with_cascade(self, api):
        """PRD: "An outcome of `SUBSTANTIATED` removes the volunteer: the
        status becomes the terminal `REMOVED`, the full removal cascade runs —
        every placement in `REQUESTED` or `CONFIRMED` is cancelled with
        `cancel_reason` `SYSTEM_REMOVAL`, each affected opportunity's fill
        counts are recomputed, and every `OPEN` visit is force-closed with
        `close_reason` `SYSTEM_REMOVAL` — and `prior_status` and
        `suspension_incident_id` are cleared back to null."
        PRD: "A `LOW` or `MEDIUM` report simply enters the queue and the
        volunteer continues serving."

        Design: Corner/state_machines/substantiated_incident_removes_volunteer_with_cascade
        """
        recruited = create_active_volunteer("Removed Rex", "rex@x.com",
                                            "SUPERVISED")
        vid = recruited["volunteer"]["id"]
        campus = create_lincoln_campus()
        opp_a = create_open_opportunity(campus["id"], title="Opp A", capacity=2)
        opp_b = create_open_opportunity(
            campus["id"], title="Opp B", capacity=2,
            starts_at="2026-08-11T14:00:00Z", ends_at="2026-08-11T17:00:00Z")
        pa = request_placement(opp_a["id"], vid)
        confirm_placement(pa["id"])
        pb = request_placement(opp_b["id"], vid)

        # LOW severity: the volunteer keeps serving (no auto-suspension).
        incident = file_incident(vid, severity="LOW",
                                 description="Complaint from staff",
                                 placement_id=pa["id"])
        assert get_volunteer(vid)["status"] == "ACTIVE"

        resolved = adjudicate_incident(incident["id"], "SUBSTANTIATED")
        assert resolved["status"] == "SUBSTANTIATED"

        volunteer = get_volunteer(vid)
        assert volunteer["status"] == "REMOVED"
        assert volunteer["prior_status"] is None
        assert volunteer["suspension_incident_id"] is None

        for placement in (pa, pb):
            after = get_placement(placement["id"])
            assert after["status"] == "CANCELLED"
            assert after["cancel_reason"] == "SYSTEM_REMOVAL"

        opp_after = get_opportunity(opp_a["id"])
        assert opp_after["committed_count"] == 0
        assert opp_after["projected_count"] == 0


class TestUnfoundedReinstatement:
    def test_unfounded_reinstates_active(self, api):
        """PRD: "An outcome of `UNFOUNDED` instead looks at reinstatement, but
        only when the report being resolved is the one that caused the current
        suspension — that is, when the volunteer's `suspension_incident_id`
        equals this report's `id`. Reinstatement follows the recorded
        `prior_status` together with current clearance validity: a volunteer
        whose `prior_status` was `ACTIVE` returns to `ACTIVE` when
        `clearance_expires_at` is still strictly after the current time"
        PRD: "In each reinstatement branch `prior_status` and
        `suspension_incident_id` are nulled and the volunteer's `version`
        increments by one."

        Design: Corner/state_machines/unfounded_reinstates_active_when_clearance_valid
        """
        recruited = create_active_volunteer("Reinstate Ray", "ray@x.com",
                                            "SUPERVISED")
        vid = recruited["volunteer"]["id"]

        incident = file_incident(vid, severity="HIGH",
                                 description="Alleged altercation")
        assert get_volunteer(vid)["status"] == "SUSPENDED"

        resolved = adjudicate_incident(incident["id"], "UNFOUNDED")
        assert resolved["status"] == "UNFOUNDED"

        volunteer = get_volunteer(vid)
        assert volunteer["status"] == "ACTIVE"
        assert volunteer["prior_status"] is None
        assert volunteer["suspension_incident_id"] is None

    def test_unfounded_reinstates_rescreen(self, api):
        """PRD: "a volunteer whose `prior_status` was `ACTIVE` returns to
        `ACTIVE` when `clearance_expires_at` is still strictly after the
        current time, but drops to `RESCREEN_REQUIRED` when the clearance has
        lapsed (null, or at or before now)"
        PRD: "Second, each affected volunteer's `clearance_expires_at` is
        recomputed, and every `ACTIVE` volunteer left without a valid clearance
        — meaning the recomputed value is null or is at or before the new
        current time — is demoted from `ACTIVE` to `RESCREEN_REQUIRED`, with
        each affected volunteer's `version` incremented by one."

        Design: Corner/state_machines/unfounded_reinstates_rescreen_when_clearance_expired
        """
        module = create_core_module_never_expires()
        volunteer = create_volunteer_applied("Expired Erin", "erin@x.com",
                                             "UNSUPERVISED")
        check = initiate_background_check(volunteer, level="ENHANCED")
        record_training(volunteer["id"], module["id"])
        adjudicated = validate_success(api.adjudicate_background_check(
            check["id"], {"findings": "NONE"}, DC), 200)
        assert adjudicated["status"] == "CLEARED"

        incident = file_incident(volunteer["id"], severity="HIGH",
                                 description="Alleged policy violation")
        assert get_volunteer(volunteer["id"])["status"] == "SUSPENDED"

        # Past the ENHANCED expiry (2027-08-01): the check expires, but the
        # demotion sweep touches only ACTIVE volunteers.
        sweep = set_clock("2027-09-01T00:00:00Z")
        assert sweep["expired_check_count"] == 1
        assert sweep["volunteers_rescreened_count"] == 0
        assert get_success_data(
            api.get_background_check(check["id"], DC))["status"] == "EXPIRED"

        adjudicate_incident(incident["id"], "UNFOUNDED")

        after = get_volunteer(volunteer["id"])
        # The clearance lapsed during the suspension: reinstatement lands in
        # RESCREEN_REQUIRED rather than ACTIVE.
        assert after["status"] == "RESCREEN_REQUIRED"
        assert after["prior_status"] is None
        assert after["suspension_incident_id"] is None


class TestIncidentAdjudicationRules:
    def test_incident_double_adjudication_rejected(self, api):
        """PRD: "Adjudication by a `DistrictCoordinator` resolves an `OPEN`
        report through the payload's `outcome`; acting on a report that is no
        longer `OPEN` is rejected with `ERR_INCIDENT_INVALID_STATE`."
        PRD: "A `LOW` or `MEDIUM` report simply enters the queue and the
        volunteer continues serving."
        PRD: "When the resolved report did not cause the volunteer's suspension
        — or the volunteer was never suspended — the volunteer record is left
        unchanged."

        Design: Corner/state_machines/incident_double_adjudication_rejected
        """
        recruited = create_active_volunteer("Incident Ivy", "ivy@x.com",
                                            "SUPERVISED")
        vid = recruited["volunteer"]["id"]

        incident = file_incident(vid, severity="MEDIUM",
                                 description="Late twice")
        adjudicate_incident(incident["id"], "UNFOUNDED")

        second = api.adjudicate_incident(
            incident["id"], {"outcome": "SUBSTANTIATED"}, DC)
        validate_error(second, ApiErrorId.ERR_INCIDENT_INVALID_STATE)

        # The MEDIUM report never suspended, and UNFOUNDED is final.
        assert get_volunteer(vid)["status"] == "ACTIVE"

    def test_incident_on_ineligible_volunteer_rejected(self, api):
        """PRD: "Filing is permitted while the volunteer is `ACTIVE`,
        `RESCREEN_REQUIRED`, `CLEARANCE_GRANTED`, or `SUSPENDED`; against any
        other status it is rejected with `ERR_VOLUNTEER_INVALID_STATE`."

        Design: Corner/endpoints/incident_on_ineligible_volunteer_rejected
        """
        volunteer = create_volunteer_applied("Applicant Al", "al@x.com",
                                             "SUPERVISED")
        assert volunteer["status"] == "APPLIED"

        resp = api.create_incident_report(
            {"volunteer_id": volunteer["id"], "severity": "LOW",
             "description": "Premature report"}, CA)
        validate_error(resp, ApiErrorId.ERR_VOLUNTEER_INVALID_STATE)

        _, meta = validate_paginated(api.list_incident_reports(
            DC, params={"volunteer_id": volunteer["id"]}))
        assert meta["total_count"] == 0
