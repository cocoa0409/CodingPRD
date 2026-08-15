"""Neighbor complaints: escalation guard, role-gated resolution, WATCH posture."""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId,
    make_coordinator_headers, make_officer_headers,
    setup_caretaker_with_colony, create_cat, create_partner_clinic,
    create_clinic_day, list_slots, create_complaint, get_colony,
    drive_cat_to_post_surgery,
)


class TestEscalation:
    def test_escalate_standard_complaint_rejected(self, api):
        """PRD §3.7: "escalating a `STANDARD` complaint requests a transition
        that does not exist and is rejected with `ERR_INVALID_STATE`."

        Design: Corner/state_machines/escalate_standard_complaint_rejected
        """
        ct, cth, col = setup_caretaker_with_colony()
        oh = make_officer_headers()
        cmp = create_complaint(col, officer_headers=oh, complainant_name="N",
                               category="NOISE")
        assert cmp["severity"] == "STANDARD"

        resp = api.escalate_complaint(cmp["id"], oh)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

    def test_escalated_complaint_officer_cannot_resolve(self, api):
        """PRD §3.7: "An escalated complaint requires coordinator sign-off to
        close — resolution moves it from `ESCALATED` to `RESOLVED` under the
        `ProgramCoordinator`, whereas an officer attempting to resolve an
        escalated complaint, or a coordinator attempting to resolve a
        merely-mediated one, requests a transition that does not exist for their
        role and is rejected with `ERR_INVALID_STATE`."

        Design: Corner/state_machines/escalated_complaint_officer_cannot_resolve
        """
        ct, cth, col = setup_caretaker_with_colony()
        oh = make_officer_headers()
        cmp = create_complaint(col, officer_headers=oh, complainant_name="N",
                               category="WILDLIFE_CONFLICT")
        assert cmp["severity"] == "HIGH"
        get_success_data(api.escalate_complaint(cmp["id"], oh))

        resp = api.resolve_complaint(cmp["id"], oh)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)


class TestMonitoringWatchPosture:
    def test_monitoring_status_watch_with_open_complaint(self, api):
        """PRD §2.6: "It is `WATCH` when the sterilized fraction reaches that same
        three-quarter threshold but at least one complaint stands `OPEN`."
        PRD §2.6: "Only `OPEN` complaints participate in this rule — complaints
        in `IN_MEDIATION`, `ESCALATED`, or `RESOLVED` do not block `STABLE`."

        Design: Corner/calculations/monitoring_status_watch_with_open_complaint
        """
        ct, cth, col = setup_caretaker_with_colony(estimated_population=4)
        cats = [create_cat(col, intake_tag=f"W{i}", approximate_age_months=24)
                for i in range(1, 5)]
        clinic = create_partner_clinic(name="WatchVet", voucher_reimbursement_cents=5000)
        day = create_clinic_day(clinic, service_date="2026-08-19T00:00:00Z",
                                base_capacity=3, surge_capacity=0)
        slots = list_slots(day)
        ch = make_coordinator_headers()

        # Drive 3 of the 4 cats to RETURNED (sterilized), leaving 1 AT_LARGE.
        for i in range(3):
            _, _, cat_after = drive_cat_to_post_surgery(
                cats[i], cth, day["id"], slots[i], trap_date="2026-08-18T00:00:00Z")
            get_success_data(api.decide_pathway(
                cat_after["id"],
                {"pathway": "RETURN_TO_FIELD",
                 "expected_cat_version": cat_after["version"]}, ch))

        colony = get_colony(col["id"])
        assert colony["sterilized_pct"] == 0.75, \
            f"3 of 4 residents sterilized must give 0.75, got {colony['sterilized_pct']}"

        cmp = create_complaint(col, complainant_name="Neigh Bor", category="ODOR")
        colony = get_colony(col["id"])
        assert colony["monitoring_status"] == "WATCH", \
            f"0.75 sterilized with an OPEN complaint must be WATCH, got {colony['monitoring_status']}"

        get_success_data(api.start_mediation(cmp["id"], make_officer_headers()))
        colony = get_colony(col["id"])
        assert colony["monitoring_status"] == "STABLE", \
            f"IN_MEDIATION does not block STABLE, got {colony['monitoring_status']}"
