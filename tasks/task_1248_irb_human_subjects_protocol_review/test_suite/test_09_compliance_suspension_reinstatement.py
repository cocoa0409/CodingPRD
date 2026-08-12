"""Non-compliance findings, the suspension cascade, reinstatement
compensation, protocol withdrawal/closure, and the protocol revision loops
(PRD §2.10, §3.2, §3.5, §3.8).
"""
from test_helpers import (
    ApiErrorId,
    add_agenda_item_ok,
    approve_consent_document,
    close_case_ok,
    create_draft_protocol,
    create_modification_ok,
    create_reliance,
    drive_to_under_expedited_review,
    execute_reliance_ok,
    file_recommendation,
    get_agenda_item,
    get_meeting,
    get_protocol,
    get_reliance,
    get_success_data,
    investigate_case,
    issue_finding_ok,
    make_chair_headers,
    make_pi_headers,
    offer_assignment,
    open_manual_case,
    record_determination_ok,
    register_chair,
    register_investigator,
    register_member,
    respond_to_assignment,
    schedule_meeting,
    setup_approved_protocol,
    submit_protocol_ok,
    suspend_protocol_via_confirmed_finding,
    unique_email,
    upload_consent,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

COORDINATOR = TEST_USERS["coordinator_headers"]


class TestFindingConfirmedCascade:
    def _setup_cascade_scenario(self, api):
        """APPROVED protocol + EXECUTED reliance + SUBMITTED MAJOR modification
        whose agenda item is the ONLY LISTED item on a SCHEDULED meeting; the
        case under investigation is returned for the trigger."""
        scenario = setup_approved_protocol()
        inv, proto = scenario["investigator"], scenario["protocol"]

        rel = create_reliance(proto["id"], ceding_institution_code="INST_A")
        execute_reliance_ok(rel["id"])

        pv = get_protocol(proto["id"])["version"]
        mod = create_modification_ok(
            proto["id"], inv["id"], pv, scope="MAJOR",
            description="add a second cohort",
        )
        meeting = schedule_meeting(room_id="R-CASC", scheduled_at="2026-06-01T10:00:00Z",
                                   duration_minutes=90)
        item = add_agenda_item_ok(
            meeting["id"], proto["id"], meeting["version"],
            modification_id=mod["id"],
        )

        case = open_manual_case(proto["id"], reason="serious protocol violation")
        investigate_case(case["id"])
        return scenario, rel, mod, meeting, item, case

    def test_finding_cascade_suspends_protocol_and_reliance(self, api):
        """PRD §3.8: "the protocol first records its `pre_suspension_state` —
        `APPROVED` or `EXEMPT_ACTIVE` — then moves to `SUSPENDED`" and "The
        cascade then propagates in three links: every reliance agreement of the
        protocol in `EXECUTED` moves to `SUSPENDED`; every agenda item of the
        protocol still `LISTED` on a `SCHEDULED` meeting moves to `REMOVED`
        with the meeting's `item_count` recomputed; and any meeting whose
        `item_count` reaches zero through those removals moves to `CANCELLED`."

        Design: Difficulty/transitive_cascade/finding_confirmed_cascade_to_meeting_cancellation
        """
        scenario, rel, _mod, _meeting, _item, case = self._setup_cascade_scenario(api)
        proto = scenario["protocol"]

        case_after = issue_finding_ok(case["id"], "CONFIRMED")
        assert case_after["status"] == "FINDING_CONFIRMED"

        proto_after = get_protocol(proto["id"])
        assert proto_after["status"] == "SUSPENDED"
        assert proto_after["pre_suspension_state"] == "APPROVED"

        rel_after = get_reliance(rel["id"])
        assert rel_after["status"] == "SUSPENDED", (
            "Cascade link: EXECUTED reliance follows its protocol into SUSPENDED"
        )

    def test_finding_cascade_removes_item_and_cancels_empty_meeting(self, api):
        """PRD §3.8: "every agenda item of the protocol still `LISTED` on a
        `SCHEDULED` meeting moves to `REMOVED` with the meeting's `item_count`
        recomputed; and any meeting whose `item_count` reaches zero through
        those removals moves to `CANCELLED`." PRD §3.6: "a meeting created with
        zero items is never auto-cancelled — only a removal event triggers that
        transition."

        Design: Difficulty/transitive_cascade/finding_confirmed_cascade_to_meeting_cancellation
        """
        _scenario, _rel, _mod, meeting, item, case = self._setup_cascade_scenario(api)

        issue_finding_ok(case["id"], "CONFIRMED")

        item_after = get_agenda_item(item["id"])
        assert item_after["status"] == "REMOVED"

        meeting_after = get_meeting(meeting["id"])
        assert meeting_after["item_count"] == 0
        assert meeting_after["status"] == "CANCELLED", (
            "The removal of its last LISTED item cancels a SCHEDULED meeting"
        )


class TestProtocolRevisionAndSuspensionLoops:
    def _setup(self):
        inv = register_investigator()
        chair = register_chair(email=unique_email("chair"))
        rev_e = register_member("SCIENTIST", email=unique_email("reve"))
        rev_f = register_member("UNAFFILIATED", email=unique_email("revf"))
        proto = create_draft_protocol(
            inv["id"], title="Cycle Study", claimed_review_level="EXPEDITED",
            risk_level="MINIMAL",
        )
        cd = upload_consent(proto["id"], inv["id"], file_ref="s3://consent/cycle-v1.pdf")
        approve_consent_document(cd["id"], chair["id"])
        return inv, chair, rev_e, rev_f, proto

    def _drive_through_revision_loop(self, api, inv, chair, rev_e, rev_f, proto):
        """SUBMITTED -> RETURNED -> SUBMITTED -> UNDER_EXPEDITED_REVIEW ->
        CHANGES_REQUESTED -> UNDER_EXPEDITED_REVIEW -> APPROVED."""
        submit_protocol_ok(proto["id"], inv["id"])

        # Completeness loop: coordinator returns the SUBMITTED protocol.
        returned = validate_success(
            api.return_protocol(
                proto["id"], {"reason": "missing recruitment plan"}, COORDINATOR
            )
        )
        assert returned["status"] == "RETURNED"
        resubmitted = submit_protocol_ok(proto["id"], inv["id"])
        assert resubmitted["status"] == "SUBMITTED"

        record_determination_ok(proto["id"], "EXPEDITED")

        a_e = offer_assignment(proto["id"], reviewer_id=rev_e["id"], reviewer_role="PRIMARY")
        a_f = offer_assignment(proto["id"], reviewer_id=rev_f["id"], reviewer_role="SECONDARY")
        respond_to_assignment(a_e["id"], rev_e["id"], "ACCEPT")
        respond_to_assignment(a_f["id"], rev_f["id"], "ACCEPT")
        file_recommendation(a_e["id"], rev_e["id"], "MINOR_REVISIONS")
        file_recommendation(a_f["id"], rev_f["id"], "MINOR_REVISIONS")

        changes = validate_success(
            api.expedited_determination(
                proto["id"], {"outcome": "REQUIRE_CHANGES"},
                make_chair_headers(chair["id"]),
            )
        )
        assert changes["status"] == "CHANGES_REQUESTED"

        # Revision loop: resubmission re-enters expedited review.
        revised = submit_protocol_ok(proto["id"], inv["id"])
        assert revised["status"] == "UNDER_EXPEDITED_REVIEW"

        approved = validate_success(
            api.expedited_determination(
                proto["id"], {"outcome": "APPROVE"}, make_chair_headers(chair["id"])
            )
        )
        assert approved["status"] == "APPROVED"
        return approved

    def test_protocol_revision_loop_reaches_approval(self, api):
        """PRD §3.2: "From `SUBMITTED`, an `IrbCoordinator` holds two levers.
        Returning the protocol moves it `SUBMITTED` → `RETURNED` with a
        free-text `reason`, signalling the PI to complete and resubmit." PRD
        §3.5: "Requesting changes requires a lighter gate — at least one
        non-voided submitted recommendation, else
        `ERR_INSUFFICIENT_RECOMMENDATIONS` — and moves the protocol to
        `CHANGES_REQUESTED`, from which the PI resubmits per §3.2." PRD §3.2:
        "from `CHANGES_REQUESTED` it re-enters `UNDER_EXPEDITED_REVIEW`".

        Design: Difficulty/non_linear_state_machine/protocol_revision_loop_and_suspension_cycle
        """
        inv, chair, rev_e, rev_f, proto = self._setup()
        initial_version = proto["version"]

        approved = self._drive_through_revision_loop(
            api, inv, chair, rev_e, rev_f, proto
        )
        assert approved["status"] == "APPROVED"
        assert approved["version"] > initial_version, (
            "Every mutation increments the protocol version (PRD §2.5)"
        )

    def test_protocol_suspension_loop_reinstates_to_approved(self, api):
        """PRD §3.8: "Whether triggered by a confirmed finding or by a
        suspend-protocol disposition, the protocol first records its
        `pre_suspension_state` — `APPROVED` or `EXEMPT_ACTIVE` — then moves to
        `SUSPENDED`". PRD §3.8: "A clean reinstatement returns the protocol to
        its recorded `pre_suspension_state`, clears that field, and flips every
        reliance agreement of the protocol from `SUSPENDED` back to
        `EXECUTED`."

        Design: Difficulty/non_linear_state_machine/protocol_revision_loop_and_suspension_cycle
        """
        inv, chair, rev_e, rev_f, proto = self._setup()
        self._drive_through_revision_loop(api, inv, chair, rev_e, rev_f, proto)

        # Suspension loop: confirmed finding suspends; case closure + chair
        # reinstatement returns the protocol to APPROVED.
        case = open_manual_case(proto["id"], reason="mid-study audit")
        investigate_case(case["id"])
        issue_finding_ok(case["id"], "CONFIRMED")
        suspended = get_protocol(proto["id"])
        assert suspended["status"] == "SUSPENDED"
        assert suspended["pre_suspension_state"] == "APPROVED"

        close_case_ok(case["id"], closure_note="corrective plan accepted")
        reinstated = validate_success(
            api.reinstate_protocol(proto["id"], make_chair_headers(chair["id"]))
        )
        assert reinstated["status"] == "APPROVED"
        assert reinstated["pre_suspension_state"] is None, (
            "Reinstatement clears the recorded pre-suspension state"
        )


class TestWithdrawalAndClosureGates:
    def test_withdraw_from_approved_rejected(self, api):
        """PRD §3.2: "A PI who abandons a study may withdraw it from `DRAFT`,
        `SUBMITTED`, or `RETURNED`, moving it to the terminal `WITHDRAWN`
        state; withdrawal from any other state is rejected with
        `ERR_INVALID_STATE`".

        Design: Corner/state_machines/withdraw_from_approved_rejected
        """
        scenario = setup_approved_protocol()
        inv, proto = scenario["investigator"], scenario["protocol"]

        resp = api.withdraw_protocol(proto["id"], make_pi_headers(inv["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert get_protocol(proto["id"])["status"] == "APPROVED"

    def test_close_blocked_by_open_case(self, api):
        """PRD §3.8: "the owning PI may close a protocol in `APPROVED` or
        `EXEMPT_ACTIVE`, subject to the same open-cases check
        (`ERR_OPEN_CASES_REMAIN`), moving it to the terminal `CLOSED` state".

        Design: Corner/validations/close_blocked_by_open_case
        """
        scenario = setup_approved_protocol()
        inv, proto = scenario["investigator"], scenario["protocol"]

        case = open_manual_case(proto["id"], reason="whistleblower report")
        resp = api.close_protocol(proto["id"], make_pi_headers(inv["id"]))
        validate_error(resp, ApiErrorId.ERR_OPEN_CASES_REMAIN)

        investigate_case(case["id"])
        issue_finding_ok(case["id"], "NOT_CONFIRMED")
        close_case_ok(case["id"], closure_note="unsubstantiated")

        data = validate_success(api.close_protocol(proto["id"], make_pi_headers(inv["id"])))
        assert data["status"] == "CLOSED"


class TestReinstatementGate:
    def test_reinstate_blocked_while_cases_open(self, api):
        """PRD §3.8: "The protocol must sit in `SUSPENDED` (else
        `ERR_INVALID_STATE`), and no non-compliance case of the protocol may
        remain in `OPENED`, `INVESTIGATION`, or `FINDING_CONFIRMED` — open
        cases block reinstatement with `ERR_OPEN_CASES_REMAIN`. A clean
        reinstatement returns the protocol to its recorded
        `pre_suspension_state`".

        Design: Corner/validations/reinstate_blocked_while_cases_open
        """
        scenario = setup_approved_protocol()
        chair, proto = scenario["chair"], scenario["protocol"]

        case = open_manual_case(proto["id"], reason="deviation pattern")
        investigate_case(case["id"])
        issue_finding_ok(case["id"], "CONFIRMED")
        assert get_protocol(proto["id"])["status"] == "SUSPENDED"

        # The suspending case is still FINDING_CONFIRMED: reinstatement fails.
        resp = api.reinstate_protocol(proto["id"], make_chair_headers(chair["id"]))
        validate_error(resp, ApiErrorId.ERR_OPEN_CASES_REMAIN)
        assert get_protocol(proto["id"])["status"] == "SUSPENDED"

        close_case_ok(case["id"], closure_note="corrective plan verified")
        data = validate_success(
            api.reinstate_protocol(proto["id"], make_chair_headers(chair["id"]))
        )
        assert data["status"] == "APPROVED"
