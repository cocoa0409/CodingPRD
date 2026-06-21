"""Invalid/valid transitions, compact eligibility, override flow, and follow-up lifecycle.

Breadth coverage for the state_machines corner section: license-state guards, visit
state guards, compact-expedited preconditions, the suspended-license compliance block,
officer override, and follow-up lapse/fulfill.
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_paginated,
    make_physician_headers,
    make_patient_headers,
    board_headers,
    officer_headers,
    set_clock,
    create_physician,
    issue_license,
    create_patient,
    request_visit,
    setup_licensed_physician,
    setup_requested_visit,
    setup_cleared_visit,
    setup_approved_visit,
    complete_visit,
)


class TestLicenseStateGuards:

    def test_suspend_already_suspended_returns_invalid_state(self, api):
        """PRD §3.4: "Any transition requested from a license state that does not define it
        — for instance suspending an already-suspended license, or reinstating one that is
        not suspended — is rejected with `ERR_INVALID_STATE`."

        Design: Corner/state_machines/suspend_already_suspended_returns_invalid_state
        """
        physician, license_ = setup_licensed_physician(state_code="CA")
        api.suspend_state_license(license_["id"], {"suspension_reason": "first"}, board_headers())
        res = api.suspend_state_license(license_["id"], {"suspension_reason": "second"}, board_headers())
        validate_error(res, "ERR_INVALID_STATE")

    def test_reinstate_revoked_license_returns_invalid_state(self, api):
        """PRD §3.4: "Any transition requested from a license state that does not define it
        — for instance suspending an already-suspended license, or reinstating one that is
        not suspended — is rejected with `ERR_INVALID_STATE`."

        Design: Corner/state_machines/reinstate_revoked_license_returns_invalid_state
        """
        physician, license_ = setup_licensed_physician(state_code="CA")
        api.revoke_state_license(license_["id"], board_headers())
        res = api.reinstate_state_license(license_["id"], board_headers())
        validate_error(res, "ERR_INVALID_STATE")


class TestVisitStateGuards:

    def test_approve_visit_before_compliance_cleared_returns_invalid_state(self, api):
        """PRD §3.5: "Once a visit is `COMPLIANCE_CLEARED`, its conducting `Physician`
        approves it, and approval forks based purely on whether the patient is insured."

        Design: Corner/state_machines/approve_visit_before_compliance_cleared_returns_invalid_state
        """
        physician, license_, patient, visit = setup_requested_visit(state_code="CA")
        phys_headers = make_physician_headers(physician["id"])
        res = api.approve_visit(visit["id"], phys_headers)
        validate_error(res, "ERR_INVALID_STATE")

    def test_override_without_prior_block_returns_invalid_state(self, api):
        """PRD §3.3: "The officer may override a recorded block, but only on a visit still
        in `REQUESTED` status and only when the *most recent* `ComplianceCheck` for that
        visit has an `outcome` of `BLOCKED` — an override may follow only a recorded block."

        Design: Corner/state_machines/override_without_prior_block_returns_invalid_state
        """
        physician, license_, patient, visit = setup_requested_visit(state_code="CA")
        res = api.override_compliance(visit["id"], officer_headers())
        validate_error(res, "ERR_INVALID_STATE")

    def test_cancel_cleared_visit_succeeds(self, api):
        """PRD §3.2: "A `Patient` may cancel a visit they own while it is still `REQUESTED`
        or once it is `COMPLIANCE_CLEARED`, moving it to `CANCELLED`; cancellation has no
        further side effects."

        Design: Corner/state_machines/cancel_cleared_visit_succeeds
        """
        physician, license_, patient, cleared = setup_cleared_visit(state_code="CA")
        res = api.cancel_visit(cleared["id"], make_patient_headers(patient["id"]))
        cancelled = validate_success(res, 200)
        assert cancelled["status"] == "CANCELLED", f"expected CANCELLED, got {cancelled['status']}"


class TestCompactEligibility:

    def test_compact_expedited_in_home_state_returns_compact_ineligible(self, api):
        """PRD §2.9: "A `COMPACT_EXPEDITED` license may be created only for a `Physician`
        whose `imlc_eligible` flag is true, and only for a `state_code` that differs from
        that physician's `home_state_code` — the compact issues expedited licenses in
        states *other than* the principal state."
        PRD §2.9: "A request that violates either condition (a non-eligible physician, or
        an expedited license in the physician's own home state) is rejected with
        `ERR_COMPACT_INELIGIBLE`."

        Design: Corner/state_machines/compact_expedited_in_home_state_returns_compact_ineligible
        """
        physician = create_physician(imlc_eligible=True, home_state_code="CA")
        res = api.create_state_license(physician["id"], {
            "state_code": "CA", "issuance_type": "COMPACT_EXPEDITED",
            "effective_date": "2026-01-01T00:00:00.000Z", "expiration_date": "2027-01-01T00:00:00.000Z",
        }, board_headers())
        validate_error(res, "ERR_COMPACT_INELIGIBLE")

    def test_compact_expedited_for_non_imlc_physician_returns_compact_ineligible(self, api):
        """PRD §2.9: "A `COMPACT_EXPEDITED` license may be created only for a `Physician`
        whose `imlc_eligible` flag is true, and only for a `state_code` that differs from
        that physician's `home_state_code` — the compact issues expedited licenses in
        states *other than* the principal state."
        PRD §2.9: "A request that violates either condition (a non-eligible physician, or
        an expedited license in the physician's own home state) is rejected with
        `ERR_COMPACT_INELIGIBLE`."

        Design: Corner/state_machines/compact_expedited_for_non_imlc_physician_returns_compact_ineligible
        """
        physician = create_physician(home_state_code="CA")  # imlc_eligible defaults false
        res = api.create_state_license(physician["id"], {
            "state_code": "TX", "issuance_type": "COMPACT_EXPEDITED",
            "effective_date": "2026-01-01T00:00:00.000Z", "expiration_date": "2027-01-01T00:00:00.000Z",
        }, board_headers())
        validate_error(res, "ERR_COMPACT_INELIGIBLE")


class TestComplianceOutcomes:

    def test_license_not_active_blocks_run_compliance(self, api):
        """PRD §3.3: "Second, the licensure rule: when no candidate license qualifies, the
        outcome is `BLOCKED` with a null `matched_license_id`, and the request is rejected
        with `ERR_NO_LICENSE_IN_STATE`."
        PRD §3.3: "`LICENSE_NOT_ACTIVE` when a license for that physician and state exists
        but is not `ACTIVE` (for example, suspended or revoked)".

        Design: Corner/state_machines/license_not_active_blocks_run_compliance
        """
        physician, license_ = setup_licensed_physician(state_code="CA")
        api.suspend_state_license(license_["id"], {"suspension_reason": "audit"}, board_headers())
        patient = create_patient(residence_state_code="CA")
        visit = request_visit(physician["id"], patient["id"], determined_state_code="CA")
        phys_headers = make_physician_headers(physician["id"])
        res = api.run_compliance(visit["id"], phys_headers)
        validate_error(res, "ERR_NO_LICENSE_IN_STATE")
        data, _ = validate_paginated(api.list_visit_compliance_checks(visit["id"], officer_headers()))
        assert data[0]["outcome"] == "BLOCKED", f"expected BLOCKED, got {data[0]['outcome']}"
        assert data[0]["reason_code"] == "LICENSE_NOT_ACTIVE", (
            f"suspended-license block reason should be LICENSE_NOT_ACTIVE, got {data[0]['reason_code']}"
        )

    def test_officer_override_clears_blocked_visit(self, api):
        """PRD §3.3: "Overriding appends a `ComplianceCheck` with an `outcome` of
        `OVERRIDDEN`, a null `matched_license_id`, and a `reason_code` of `OFFICER_OVERRIDE`,
        and advances the visit from `REQUESTED` to `COMPLIANCE_CLEARED`."

        Design: Corner/state_machines/officer_override_clears_blocked_visit
        """
        # Physician licensed only in CA; visit in TX -> run-compliance BLOCKED (no TX license).
        set_clock("2026-04-01T09:00:00.000Z")
        physician = create_physician(home_state_code="CA")
        issue_license(physician["id"], state_code="CA", issuance_type="FULL")
        patient = create_patient(residence_state_code="TX")
        visit = request_visit(physician["id"], patient["id"], determined_state_code="TX")
        phys_headers = make_physician_headers(physician["id"])
        api.run_compliance(visit["id"], phys_headers)  # records BLOCKED
        overridden = validate_success(api.override_compliance(visit["id"], officer_headers()), 200)
        assert overridden["status"] == "COMPLIANCE_CLEARED", (
            f"override should advance to COMPLIANCE_CLEARED, got {overridden['status']}"
        )
        data, _ = validate_paginated(api.list_visit_compliance_checks(visit["id"], officer_headers()))
        latest = data[-1]
        assert latest["outcome"] == "OVERRIDDEN", f"latest check should be OVERRIDDEN, got {latest['outcome']}"
        assert latest["reason_code"] == "OFFICER_OVERRIDE", (
            f"latest reason should be OFFICER_OVERRIDE, got {latest['reason_code']}"
        )


class TestFollowUpLifecycle:

    def test_lapse_followup_before_due_returns_not_due(self, api):
        """PRD §3.8: "An attempt to lapse a follow-up before its due instant has been
        reached is rejected with `ERR_NOT_DUE`."

        Design: Corner/state_machines/lapse_followup_before_due_returns_not_due
        """
        # Completed at clock 2026-03-01T12:00Z -> due 2026-03-31T12:00Z; clock NOT advanced.
        ctx = setup_approved_visit(clock="2026-03-01T12:00:00.000Z", insured=False,
                                   visit_overrides={"scheduled_at": "2026-03-02T10:00:00.000Z"})
        complete_visit(ctx["visit"]["id"], ctx["physician"]["id"])
        phys_headers = make_physician_headers(ctx["physician"]["id"])
        data, _ = validate_paginated(api.list_visit_follow_ups(ctx["visit"]["id"], phys_headers))
        fu_id = data[0]["id"]
        res = api.lapse_follow_up(fu_id, officer_headers())
        validate_error(res, "ERR_NOT_DUE")
        after = validate_success(api.get_follow_up(fu_id, officer_headers()), 200)
        assert after["status"] == "OPEN", f"follow-up should stay OPEN, got {after['status']}"

    def test_fulfill_followup_links_new_visit(self, api):
        """PRD §3.8: "A `Physician` fulfills an open follow-up by supplying the
        `linked_visit_id` of the new visit booked to satisfy it; this sets the follow-up's
        `linked_visit_id` and moves its `status` from `OPEN` to `FULFILLED`."

        Design: Corner/state_machines/fulfill_followup_links_new_visit
        """
        ctx = setup_approved_visit(clock="2026-03-01T12:00:00.000Z", insured=False,
                                   visit_overrides={"scheduled_at": "2026-03-02T10:00:00.000Z"})
        complete_visit(ctx["visit"]["id"], ctx["physician"]["id"])
        phys_headers = make_physician_headers(ctx["physician"]["id"])
        data, _ = validate_paginated(api.list_visit_follow_ups(ctx["visit"]["id"], phys_headers))
        fu_id = data[0]["id"]
        v2 = request_visit(ctx["physician"]["id"], ctx["patient"]["id"],
                           determined_state_code="CA", scheduled_at="2026-04-15T10:00:00.000Z")
        fulfilled = validate_success(api.fulfill_follow_up(fu_id, {"linked_visit_id": v2["id"]}, phys_headers), 200)
        assert fulfilled["status"] == "FULFILLED", f"expected FULFILLED, got {fulfilled['status']}"
        assert fulfilled["linked_visit_id"] == v2["id"], (
            f"linked_visit_id should be set to v2, got {fulfilled['linked_visit_id']}"
        )
