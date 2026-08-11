"""Staff engagements: classification cycle, activation gates, overlap intervals,
employment model gate, and contractor YTD boundaries (PRD §3.4, §3.5)."""
from test_helpers import (
    ApiErrorId,
    activate_engagement,
    countersign,
    create_active_bundle,
    create_active_engagement,
    create_approved_bundle,
    create_staff_engagement_payload,
    create_vetted_engagement,
    get_engagement,
    make_compliance_officer_headers,
    make_project_lead_headers,
    make_sponsor_admin_headers,
    pay_staff,
    propose_engagement,
    set_clock,
    create_received_donation,
    validate_error,
    validate_paginated,
    validate_success,
    vet_engagement,
)


class TestEngagementLifecycleGuards:
    def test_engagement_terminate_from_proposed_rejected(self, api):
        """PRD §3.5: "Termination is available to the `ProjectLead` or a
        `ComplianceOfficer` from `ACTIVE`, `VETTED`, or `CLASSIFICATION_REVIEW`, moving
        the engagement to `TERMINATED`"

        Design: Corner/state_machines/sm_engagement_terminate_from_proposed_rejected
        """
        bundle = create_active_bundle("user_c_et", project_name="ET", contact_email="et@x.org")
        pid = bundle["project_id"]
        engagement = propose_engagement(pid, "wet@x.org", rate_cents=1000)
        resp = api.terminate_engagement(engagement["id"], {"reason": "early"},
                                        make_project_lead_headers(pid))
        validate_error(resp, ApiErrorId.ERR_ENGAGEMENT_STATE_INVALID)
        after = get_engagement(engagement["id"])
        assert after["status"] == "PROPOSED"

    def test_engagement_dates_invalid(self, api):
        """PRD §3.5: "When provided, `end_date` must be strictly later than
        `start_date` (`ERR_ENGAGEMENT_DATES_INVALID`)."

        Design: Corner/validations/v_engagement_dates_invalid
        """
        bundle = create_active_bundle("user_c_v10", project_name="ED", contact_email="ed@x.org")
        pid = bundle["project_id"]
        resp = api.create_staff_engagement(
            pid,
            create_staff_engagement_payload(worker_email="wed@x.org", rate_cents=1000,
                                            start_date="2026-06-01", end_date="2026-01-01"),
            make_project_lead_headers(pid))
        validate_error(resp, ApiErrorId.ERR_ENGAGEMENT_DATES_INVALID)
        listed, _ = validate_paginated(api.list_project_staff_engagements(
            pid, make_sponsor_admin_headers()))
        assert listed == [], "no engagement may be persisted on a date-invalid create"


class TestClassificationCycle:
    def test_flag_misclassification_reopens_and_overrides_type(self, api):
        """PRD §3.5: "A `ComplianceOfficer` who suspects misclassification flags an
        `ACTIVE` engagement with a `reason`, moving it to `CLASSIFICATION_REVIEW`"
        PRD §3.5: "the engagement moves to `VETTED`, its `engagement_type` is set to
        the approved type, and `classification_overridden` records whether the approved
        type differs from the proposed one."

        Design: Difficulty/non_linear_state_machine/engagement_reclassification_cycle
        """
        bundle = create_active_bundle("user_app_i", project_name="Iota", contact_email="i@x.org")
        pid = bundle["project_id"]
        engagement = create_active_engagement(
            pid, "w1@x.org", engagement_type="CONTRACTOR", rate_cents=5000,
            start_date="2026-06-01", end_date="2026-09-01")

        flagged = validate_success(api.flag_misclassification(
            engagement["id"], {"reason": "set hours and supervision"},
            make_compliance_officer_headers()))
        assert flagged["status"] == "CLASSIFICATION_REVIEW"

        revetted = vet_engagement(engagement["id"], approved_type="EMPLOYEE",
                                  rationale="behavioral control")
        assert revetted["status"] == "VETTED"
        assert revetted["engagement_type"] == "EMPLOYEE"
        assert revetted["classification_overridden"] is True, (
            "approved EMPLOYEE differs from proposed CONTRACTOR")

    def test_reclassification_cycle_completes_to_active(self, api):
        """PRD §3.5: "the cycle `ACTIVE` to `CLASSIFICATION_REVIEW` to `VETTED` to
        `ACTIVE` may repeat, and each pass may flip `engagement_type`."

        Design: Difficulty/non_linear_state_machine/engagement_reclassification_cycle
        """
        bundle = create_active_bundle("user_app_i2", project_name="Iota2",
                                      contact_email="i2@x.org")
        pid = bundle["project_id"]
        engagement = create_active_engagement(pid, "w1b@x.org", engagement_type="CONTRACTOR",
                                              rate_cents=5000, start_date="2026-06-01",
                                              end_date="2026-09-01")
        validate_success(api.flag_misclassification(
            engagement["id"], {"reason": "set hours and supervision"},
            make_compliance_officer_headers()))
        vet_engagement(engagement["id"], approved_type="EMPLOYEE",
                       rationale="behavioral control")
        reactivated = activate_engagement(engagement["id"], pid)
        assert reactivated["status"] == "ACTIVE", "cycle completes back to ACTIVE"
        assert reactivated["engagement_type"] == "EMPLOYEE"


class TestActivationGates:
    def test_activate_blocked_before_countersign(self, api):
        """PRD §3.5: "Activation is the lead's act from `VETTED` and carries three
        guards: the agreement must be `ACTIVE` (`ERR_AGREEMENT_NOT_ACTIVE`)"

        Design: Difficulty/cross_entity_state_dependency/staff_activate_requires_agreement_active
        """
        bundle = create_approved_bundle("user_app_r", project_name="Sigma",
                                        contact_email="s@x.org")
        pid = bundle["project_id"]
        engagement = propose_engagement(pid, "w3@x.org", rate_cents=4000)
        vet_engagement(engagement["id"], approved_type="CONTRACTOR")
        resp = api.activate_engagement(engagement["id"], make_project_lead_headers(pid))
        validate_error(resp, ApiErrorId.ERR_AGREEMENT_NOT_ACTIVE)

    def test_activate_allowed_after_countersign(self, api):
        """PRD §3.5: "the agreement must be `ACTIVE` (`ERR_AGREEMENT_NOT_ACTIVE`)"
        PRD §3.2: "Countersignature fires a three-way activation: the agreement moves
        to `ACTIVE`, the project moves from `PROPOSED` to `ACTIVE`, and the fund moves
        from `PENDING` to `ACTIVE`."

        Design: Difficulty/cross_entity_state_dependency/staff_activate_requires_agreement_active
        """
        bundle = create_approved_bundle("user_app_r2", project_name="Sigma2",
                                        contact_email="s2@x.org")
        pid = bundle["project_id"]
        engagement = propose_engagement(pid, "w3b@x.org", rate_cents=4000)
        vet_engagement(engagement["id"], approved_type="CONTRACTOR")
        validate_error(api.activate_engagement(engagement["id"], make_project_lead_headers(pid)),
                       ApiErrorId.ERR_AGREEMENT_NOT_ACTIVE)
        countersign(bundle["agreement_id"], bundle["applicant_id"])
        activated = activate_engagement(engagement["id"], pid)
        assert activated["status"] == "ACTIVE"


class TestHalfOpenIntervalOverlap:
    def test_touching_intervals_activate(self, api):
        """PRD §3.5: "intervals that merely touch — one's `end_date` equal to the
        other's `start_date` — do not overlap."
        Existing ACTIVE [2026-06-01, 2026-09-01); new [2026-09-01, 2026-12-01) is
        legal adjacency under half-open semantics.

        Design: Difficulty/resource_temporal_overlap/engagement_half_open_interval_overlap
        """
        bundle = create_active_bundle("user_app_t", project_name="Upsilon",
                                      contact_email="u@x.org")
        pid = bundle["project_id"]
        create_active_engagement(pid, "w4@x.org", engagement_type="CONTRACTOR",
                                 rate_cents=4000, start_date="2026-06-01",
                                 end_date="2026-09-01")
        adjacent = create_vetted_engagement(pid, "w4@x.org", engagement_type="CONTRACTOR",
                                            rate_cents=4000, start_date="2026-09-01",
                                            end_date="2026-12-01")
        activated = activate_engagement(adjacent["id"], pid)
        assert activated["status"] == "ACTIVE", "end == start adjacency is not overlap"

    def test_one_day_overlap_rejected(self, api):
        """PRD §3.5: "the new engagement's half-open interval from `start_date`
        inclusive to `end_date` exclusive must not overlap any other `ACTIVE`
        engagement for the same `worker_email` on the same project
        (`ERR_ENGAGEMENT_OVERLAP`, HTTP 409)."
        [2026-08-31, 2026-10-01) overlaps ACTIVE [2026-06-01, 2026-09-01) by one day.

        Design: Difficulty/resource_temporal_overlap/engagement_half_open_interval_overlap
        """
        bundle = create_active_bundle("user_app_t2", project_name="Upsilon2",
                                      contact_email="u2@x.org")
        pid = bundle["project_id"]
        create_active_engagement(pid, "w4b@x.org", engagement_type="CONTRACTOR",
                                 rate_cents=4000, start_date="2026-06-01",
                                 end_date="2026-09-01")
        create_active_engagement(pid, "w4b@x.org", engagement_type="CONTRACTOR",
                                 rate_cents=4000, start_date="2026-09-01",
                                 end_date="2026-12-01")
        overlapping = create_vetted_engagement(pid, "w4b@x.org", engagement_type="CONTRACTOR",
                                               rate_cents=4000, start_date="2026-08-31",
                                               end_date="2026-10-01")
        resp = api.activate_engagement(overlapping["id"], make_project_lead_headers(pid))
        validate_error(resp, ApiErrorId.ERR_ENGAGEMENT_OVERLAP)
        after = get_engagement(overlapping["id"])
        assert after["status"] == "VETTED"


class TestEmploymentModelGate:
    def test_employee_proposal_under_grant_surfaces_model_error(self, api):
        """PRD §3.5: "Proposing an `EMPLOYEE` under a `PRE_APPROVED_GRANT` agreement is
        rejected with `ERR_MODEL_FORBIDS_EMPLOYMENT`."
        PRD §2.11 lists employment-classification legality ahead of duplicate
        engagements in the domain sequence: "the relative order is normative because it
        determines which error surfaces when several problems coexist." A worker who
        already holds a PROPOSED engagement triggers both rules; the safety error wins.

        Design: Difficulty/priority_pair_validation_conflict/employment_safety_error_beats_duplicate_constraint
        """
        bundle = create_active_bundle("user_app_m", model="PRE_APPROVED_GRANT",
                                      project_name="Nu", contact_email="n@x.org")
        pid = bundle["project_id"]
        propose_engagement(pid, "dup@x.org", engagement_type="CONTRACTOR", rate_cents=5000,
                           start_date="2026-06-01", end_date="2026-09-01")
        resp = api.create_staff_engagement(
            pid,
            create_staff_engagement_payload(
                worker_name="Dup", worker_email="dup@x.org", engagement_type="EMPLOYEE",
                compensation_type="SALARY", rate_cents=500000, start_date="2026-06-01"),
            make_project_lead_headers(pid))
        validate_error(resp, ApiErrorId.ERR_MODEL_FORBIDS_EMPLOYMENT)

    def test_rejected_employee_proposal_persists_nothing(self, api):
        """PRD §3.5: "if the same `worker_email` already has an engagement in
        `PROPOSED`, `VETTED`, or `CLASSIFICATION_REVIEW` on this project, the create is
        rejected with `ERR_DUPLICATE_ENGAGEMENT` (HTTP 409)" — the rejected create
        (whichever of the two PRD-listed guards reports it) must not persist a second
        engagement for the worker.

        Design: Difficulty/priority_pair_validation_conflict/employment_safety_error_beats_duplicate_constraint
        """
        bundle = create_active_bundle("user_app_m2", model="PRE_APPROVED_GRANT",
                                      project_name="Nu2", contact_email="n2@x.org")
        pid = bundle["project_id"]
        original = propose_engagement(pid, "dup2@x.org", engagement_type="CONTRACTOR",
                                      rate_cents=5000, start_date="2026-06-01",
                                      end_date="2026-09-01")
        validate_error(api.create_staff_engagement(
            pid,
            create_staff_engagement_payload(
                worker_name="Dup", worker_email="dup2@x.org", engagement_type="EMPLOYEE",
                compensation_type="SALARY", rate_cents=500000, start_date="2026-06-01"),
            make_project_lead_headers(pid)), ApiErrorId.ERR_MODEL_FORBIDS_EMPLOYMENT)
        listed, meta = validate_paginated(api.list_project_staff_engagements(
            pid, make_sponsor_admin_headers()))
        assert meta["total_count"] == 1, "rejected create must not persist"
        assert listed[0]["id"] == original["id"]
        assert listed[0]["status"] == "PROPOSED"


class TestContractorYtdBoundary:
    def _funded_project_with_contractor(self, api, applicant_id, name, email):
        bundle = create_active_bundle(applicant_id, project_name=name, contact_email=email)
        pid = bundle["project_id"]
        create_received_donation(pid, 500000)
        engagement = create_active_engagement(pid, "w2@x.org", engagement_type="CONTRACTOR",
                                              compensation_type="FIXED", rate_cents=30000,
                                              start_date="2026-05-10")
        return pid, engagement

    def test_contractor_ytd_below_boundary_keeps_flag_false(self, api):
        """PRD §3.5: "The `requires_1099` flag is true exactly when
        `contractor_ytd_cents` is at least 60,000 cents (six hundred dollars) — the
        boundary is inclusive."
        Payments of 30,000 then 29,999 accumulate to 59,999 — still below.

        Design: Difficulty/boundary_precision_check/contractor_ytd_exactly_60000_flags_1099
        """
        pid, engagement = self._funded_project_with_contractor(api, "user_app_p", "Pi", "p@x.org")
        pay_staff(pid, engagement["id"], 30000, "2026-06-01", purpose="milestone 1")
        mid = get_engagement(engagement["id"])
        assert mid["contractor_ytd_cents"] == 30000
        assert mid["requires_1099"] is False

        pay_staff(pid, engagement["id"], 29999, "2026-06-08", purpose="milestone 2")
        below = get_engagement(engagement["id"])
        assert below["contractor_ytd_cents"] == 59999
        assert below["requires_1099"] is False, "59,999 remains below the 60,000 line"

    def test_contractor_ytd_exactly_60000_sets_flag(self, api):
        """PRD §3.5: "The `requires_1099` flag is true exactly when
        `contractor_ytd_cents` is at least 60,000 cents (six hundred dollars) — the
        boundary is inclusive."
        59,999 accumulated; a 1-cent top-up crosses to exactly 60,000.

        Design: Difficulty/boundary_precision_check/contractor_ytd_exactly_60000_flags_1099
        """
        pid, engagement = self._funded_project_with_contractor(api, "user_app_p2", "Pi2",
                                                               "p2@x.org")
        pay_staff(pid, engagement["id"], 30000, "2026-06-01", purpose="milestone 1")
        pay_staff(pid, engagement["id"], 29999, "2026-06-08", purpose="milestone 2")
        pay_staff(pid, engagement["id"], 1, "2026-06-15", purpose="milestone 3 top-up")
        final = get_engagement(engagement["id"])
        assert final["contractor_ytd_cents"] == 60000
        assert final["requires_1099"] is True, ">= 60,000 is inclusive"

    def test_contractor_ytd_resets_on_calendar_year(self, api):
        """PRD §3.5: "if the engagement's `ytd_year` differs from that year,
        `contractor_ytd_cents` first resets to zero and `ytd_year` is set to the payment
        year, and only then is the disbursement's `amount_cents` added."
        PRD §2.4: the logical clock drives "the accumulation year behind contractor
        year-to-date totals".
        50,000 paid in 2026 then 50,000 paid in 2027 leaves YTD at 50,000, not 100,000.

        Design: Corner/calculations/c_contractor_ytd_resets_on_calendar_year
        """
        pid, engagement = self._funded_project_with_contractor(api, "user_c_f6", "F6",
                                                               "f6@x.org")
        set_clock("2026-06-01T00:00:00Z")
        pay_staff(pid, engagement["id"], 50000, "2026-06-01", purpose="2026 fee")
        first = get_engagement(engagement["id"])
        assert first["contractor_ytd_cents"] == 50000
        assert first["ytd_year"] == 2026

        set_clock("2027-01-02T00:00:00Z")
        pay_staff(pid, engagement["id"], 50000, "2027-01-02", purpose="2027 fee")
        second = get_engagement(engagement["id"])
        assert second["contractor_ytd_cents"] == 50000, "accumulator resets on year change"
        assert second["ytd_year"] == 2027
        assert second["requires_1099"] is False
