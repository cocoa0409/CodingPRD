"""Adverse-event timeliness boundaries and reliance agreement gates: protocol
approval cross-entity gate, closed-window overlap geometry, and date-range
validation (PRD §3.8, §3.9).
"""
from test_helpers import (
    ApiErrorId,
    approve_consent_document,
    create_draft_protocol,
    create_reliance,
    drive_to_under_expedited_review,
    execute_reliance_ok,
    file_adverse_event_ok,
    file_recommendation,
    get_reliance,
    get_success_data,
    make_chair_headers,
    make_pi_headers,
    offer_assignment,
    register_chair,
    register_investigator,
    register_member,
    respond_to_assignment,
    set_clock,
    setup_approved_protocol,
    unique_email,
    upload_consent,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import TEST_USERS

COORDINATOR = TEST_USERS["coordinator_headers"]
OFFICER = TEST_USERS["officer_headers"]
ADMIN = TEST_USERS["admin_headers"]


class TestAdverseEventTemporalValidation:
    def test_ae_occurred_in_future_rejected(self, api):
        """PRD §3.8: "An `occurred_at` after the current logical time is
        rejected with `ERR_AE_OCCURRED_IN_FUTURE`."

        Design: Corner/validations/ae_occurred_in_future_rejected
        """
        scenario = setup_approved_protocol()
        inv, proto = scenario["investigator"], scenario["protocol"]

        # The logical clock is at the startup default 2026-05-01T00:00:00Z.
        resp = api.file_adverse_event(
            proto["id"],
            {"event_type": "SERIOUS_ADVERSE_EVENT",
             "occurred_at": "2026-05-02T00:00:00Z",
             "description": "from the future"},
            make_pi_headers(inv["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_AE_OCCURRED_IN_FUTURE)


class TestAdverseEventDeadlineBoundary:
    def _setup_two_reports(self, api):
        """APPROVED protocol; one SAE filed exactly at its 5-day deadline and
        one filed one second past it."""
        scenario = setup_approved_protocol()
        inv, proto = scenario["investigator"], scenario["protocol"]

        # occurred 2026-05-10T00:00:00Z; deadline = occurred + 5 days.
        set_clock("2026-05-15T00:00:00Z")
        ae_on_time = file_adverse_event_ok(
            proto["id"], inv["id"], event_type="SERIOUS_ADVERSE_EVENT",
            occurred_at="2026-05-10T00:00:00Z", description="on-time SAE",
        )
        set_clock("2026-05-15T00:00:01Z")
        ae_late = file_adverse_event_ok(
            proto["id"], inv["id"], event_type="SERIOUS_ADVERSE_EVENT",
            occurred_at="2026-05-10T00:00:00Z", description="one-second-late SAE",
        )
        return scenario, ae_on_time, ae_late

    def test_ae_deadline_exact_second_boundary(self, api):
        """PRD §3.8: "`deadline_at` is `occurred_at` plus five days for a
        serious adverse event or an unanticipated problem, or plus fifteen days
        for a protocol deviation with harm, and `is_late` is true only when
        `reported_at` falls strictly after `deadline_at` — a report filed
        exactly at its deadline is on time."

        Design: Difficulty/boundary_precision_check/ae_deadline_exact_second_boundary
        """
        _scenario, ae_on_time, ae_late = self._setup_two_reports(api)

        on_time = get_success_data(api.get_adverse_event(ae_on_time["id"], COORDINATOR))
        late = get_success_data(api.get_adverse_event(ae_late["id"], COORDINATOR))
        assert on_time["is_late"] is False, (
            "A report filed exactly at its deadline is on time"
        )
        assert late["is_late"] is True, (
            "reported_at strictly after deadline_at marks the report late"
        )

    def test_ae_late_triage_opens_late_ae_case(self, api):
        """PRD §3.8: "Triage of a late report has teeth: the system opens a
        non-compliance case of source `LATE_AE` in `OPENED` on the protocol and
        recomputes the investigator's provisional score, where the five-point
        open-case deduction replaces the eight-point late-unfiled deduction now
        that the report has left `FILED`."

        Design: Difficulty/boundary_precision_check/ae_deadline_exact_second_boundary
        """
        scenario, ae_on_time, ae_late = self._setup_two_reports(api)
        inv, proto = scenario["investigator"], scenario["protocol"]

        validate_success(api.triage_adverse_event(ae_on_time["id"], {}, OFFICER))
        validate_success(api.triage_adverse_event(ae_late["id"], {}, OFFICER))

        cases, _meta = validate_paginated(
            api.list_non_compliance_cases(proto["id"], COORDINATOR)
        )
        assert len(cases) == 1, (
            f"Only the late report's triage opens a case, got {len(cases)}"
        )
        assert cases[0]["source"] == "LATE_AE"
        assert cases[0]["status"] == "OPENED"

        inv_after = get_success_data(api.get_investigator(inv["id"], COORDINATOR))
        assert inv_after["provisional_compliance_score"] == 95, (
            f"provisional = 100 - 5 for the open case, got "
            f"{inv_after['provisional_compliance_score']}"
        )


class TestRelianceCrossEntityGate:
    def _setup_under_review_with_reliance(self, api):
        """Protocol UNDER_EXPEDITED_REVIEW (reviewers not yet recommended) with
        a PROPOSED reliance agreement."""
        inv = register_investigator()
        chair = register_chair(email=unique_email("chair"))
        rev_o = register_member("SCIENTIST", email=unique_email("revo"))
        rev_p = register_member("NON_SCIENTIST", email=unique_email("revp"))
        proto = create_draft_protocol(
            inv["id"], title="Reliance Study", claimed_review_level="EXPEDITED",
            risk_level="MINIMAL",
        )
        cd = upload_consent(proto["id"], inv["id"], file_ref="s3://consent/rely-v1.pdf")
        approve_consent_document(cd["id"], chair["id"])
        drive_to_under_expedited_review(proto["id"], inv["id"])
        rel = create_reliance(proto["id"], ceding_institution_code="INST_A")
        return inv, chair, rev_o, rev_p, proto, rel

    def test_reliance_execute_requires_approved_protocol_rejected(self, api):
        """PRD §3.9: "Execution activates the agreement and carries three
        gates: the agreement must be `PROPOSED` (else `ERR_INVALID_STATE`); the
        protocol must be `APPROVED` — a cross-entity gate failing with
        `ERR_PROTOCOL_NOT_APPROVED`".

        Design: Difficulty/cross_entity_state_dependency/reliance_execute_requires_approved_protocol
        """
        _inv, _chair, _ro, _rp, proto, rel = self._setup_under_review_with_reliance(api)

        resp = api.execute_reliance_agreement(rel["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_PROTOCOL_NOT_APPROVED)
        assert get_reliance(rel["id"])["status"] == "PROPOSED"

    def test_reliance_execute_succeeds_after_approval(self, api):
        """PRD §3.9: "the protocol must be `APPROVED` — a cross-entity gate
        failing with `ERR_PROTOCOL_NOT_APPROVED`". The identical execute call
        succeeds once the protocol reaches APPROVED.

        Design: Difficulty/cross_entity_state_dependency/reliance_execute_requires_approved_protocol
        """
        inv, chair, rev_o, rev_p, proto, rel = self._setup_under_review_with_reliance(api)

        resp = api.execute_reliance_agreement(rel["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_PROTOCOL_NOT_APPROVED)

        a_o = offer_assignment(proto["id"], reviewer_id=rev_o["id"], reviewer_role="PRIMARY")
        a_p = offer_assignment(proto["id"], reviewer_id=rev_p["id"], reviewer_role="SECONDARY")
        respond_to_assignment(a_o["id"], rev_o["id"], "ACCEPT")
        respond_to_assignment(a_p["id"], rev_p["id"], "ACCEPT")
        file_recommendation(a_o["id"], rev_o["id"], "APPROVE")
        file_recommendation(a_p["id"], rev_p["id"], "APPROVE")
        validate_success(
            api.expedited_determination(
                proto["id"], {"outcome": "APPROVE"}, make_chair_headers(chair["id"])
            )
        )

        data = validate_success(
            api.execute_reliance_agreement(rel["id"], ADMIN)
        )
        assert data["status"] == "EXECUTED"


class TestRelianceWindowGeometry:
    def _setup_executed_reliance(self, api):
        """APPROVED protocol with R1 EXECUTED over the closed window
        [2026-06-01, 2026-12-31] for (protocol, INST_A)."""
        scenario = setup_approved_protocol()
        proto = scenario["protocol"]
        rel1 = create_reliance(
            proto["id"], ceding_institution_code="INST_A",
            effective_start_date="2026-06-01T00:00:00Z",
            effective_end_date="2026-12-31T00:00:00Z",
        )
        execute_reliance_ok(rel1["id"])
        return scenario, rel1

    def test_reliance_window_touching_endpoints_overlap(self, api):
        """PRD §3.9: "no other `EXECUTED` agreement may exist for the same
        protocol and ceding institution whose closed window intersects the new
        one, with the boundary rule that windows touching at a single shared
        date do intersect, a violation drawing `ERR_RELIANCE_WINDOW_OVERLAP`
        (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/reliance_window_closed_interval_touching
        """
        scenario, _rel1 = self._setup_executed_reliance(api)
        proto = scenario["protocol"]

        # 2026-12-31 belongs to both closed windows: the touch intersects.
        rel2 = create_reliance(
            proto["id"], ceding_institution_code="INST_A",
            effective_start_date="2026-12-31T00:00:00Z",
            effective_end_date="2027-06-30T00:00:00Z",
        )
        resp = api.execute_reliance_agreement(rel2["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_RELIANCE_WINDOW_OVERLAP)
        assert get_reliance(rel2["id"])["status"] == "PROPOSED"

    def test_reliance_window_day_after_end_executes(self, api):
        """PRD §3.9: "The window is a closed interval — both endpoints
        inclusive" — so a window starting one day after the incumbent's end
        date shares no date with it and its execution is not an overlap.

        Design: Difficulty/resource_temporal_overlap/reliance_window_closed_interval_touching
        """
        scenario, _rel1 = self._setup_executed_reliance(api)
        proto = scenario["protocol"]

        rel3 = create_reliance(
            proto["id"], ceding_institution_code="INST_A",
            effective_start_date="2027-01-01T00:00:00Z",
            effective_end_date="2027-06-30T00:00:00Z",
        )
        data = validate_success(
            api.execute_reliance_agreement(rel3["id"], ADMIN)
        )
        assert data["status"] == "EXECUTED"


class TestRelianceDateRangeValidation:
    def test_reliance_invalid_date_range_rejected(self, api):
        """PRD §3.9: "The window is a closed interval — both endpoints
        inclusive — and a start date later than the end date is rejected with
        `ERR_INVALID_DATE_RANGE`."

        Design: Corner/validations/reliance_invalid_date_range_rejected
        """
        inv = register_investigator()
        proto = create_draft_protocol(inv["id"], title="DateRange")

        resp = api.create_reliance_agreement(
            {"protocol_id": proto["id"], "ceding_institution_code": "INST_A",
             "reviewing_institution_code": "UNIV",
             "effective_start_date": "2027-01-01T00:00:00Z",
             "effective_end_date": "2026-06-01T00:00:00Z"},
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_DATE_RANGE)
