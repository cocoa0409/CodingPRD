"""Protocol submission gates: completeness, investigator eligibility, and the
fixed evaluation order when several gates fail at once (PRD §2.9, §3.2, §3.8).
"""
from test_helpers import (
    ApiErrorId,
    create_draft_protocol,
    file_adverse_event_ok,
    get_success_data,
    investigate_case,
    issue_finding_ok,
    make_pi_headers,
    open_manual_case,
    register_investigator,
    set_clock,
    setup_approved_protocol,
    upload_consent,
    validate_error,
)


class TestSubmissionCompleteness:
    def test_submit_without_consent_document_rejected(self, api, coordinator_headers):
        """PRD §3.2: "Finally, submission completeness requires at least one
        consent document of the protocol to sit in `SUBMITTED` or `APPROVED`,
        failing which the submit is rejected with `ERR_NO_CONSENT_DOCUMENT`."

        Design: Corner/validations/submit_without_consent_document_rejected
        """
        inv = register_investigator()
        proto = create_draft_protocol(inv["id"], title="NoConsent")

        resp = api.submit_protocol(proto["id"], make_pi_headers(inv["id"]))
        validate_error(resp, ApiErrorId.ERR_NO_CONSENT_DOCUMENT)

        upload_consent(proto["id"], inv["id"], file_ref="s3://consent/nc.pdf")
        ok = api.submit_protocol(proto["id"], make_pi_headers(inv["id"]))
        data = get_success_data(ok)
        assert data["status"] == "SUBMITTED", (
            f"Submit with a consent document must succeed, got {data['status']}"
        )


class TestInvestigatorEligibilityGates:
    def test_training_lapsed_submit_rejected(self, api, coordinator_headers):
        """PRD §3.2: "an investigator whose `training_expires_at` is not
        strictly after the current logical time is rejected with
        `ERR_PI_TRAINING_LAPSED`".

        Design: Corner/validations/training_lapsed_submit_rejected
        """
        inv = register_investigator(training_expires_at="2026-01-01T00:00:00Z")
        proto = create_draft_protocol(inv["id"], title="TL Study")
        upload_consent(proto["id"], inv["id"], file_ref="s3://consent/tl.pdf")

        resp = api.submit_protocol(proto["id"], make_pi_headers(inv["id"]))
        validate_error(resp, ApiErrorId.ERR_PI_TRAINING_LAPSED)

        current = get_success_data(api.get_protocol(proto["id"], coordinator_headers))
        assert current["status"] == "DRAFT"

    def test_debarred_investigator_cannot_submit(self, api, coordinator_headers):
        """PRD §3.8: "When the `final_compliance_score` drops below 60, the
        investigator's `status` flips to `DEBARRED`, which in turn blocks every
        future submission per §3.2." PRD §3.8: "The `final_compliance_score`
        deducts 20 points per confirmed finding — cases with `finding_confirmed`
        true sitting in `FINDING_CONFIRMED` or `CLOSED`." PRD §3.2: "an
        investigator whose `status` is `DEBARRED` is rejected with
        `ERR_INVESTIGATOR_DEBARRED`".

        Design: Corner/validations/debarred_investigator_cannot_submit
        """
        scenario = setup_approved_protocol()
        inv = scenario["investigator"]
        proto = scenario["protocol"]

        # Three confirmed findings: 100 - 3*20 = 40 < 60 -> DEBARRED.
        for reason in ("finding one", "finding two", "finding three"):
            case = open_manual_case(proto["id"], reason=reason)
            investigate_case(case["id"])
            issue_finding_ok(case["id"], "CONFIRMED")

        inv_after = get_success_data(api.get_investigator(inv["id"], coordinator_headers))
        assert inv_after["final_compliance_score"] == 40, (
            f"Expected final score 40 after three confirmed findings, got "
            f"{inv_after['final_compliance_score']}"
        )
        assert inv_after["status"] == "DEBARRED"

        proto2 = create_draft_protocol(inv["id"], title="Deb Study 2")
        upload_consent(proto2["id"], inv["id"], file_ref="s3://consent/deb2.pdf")
        resp = api.submit_protocol(proto2["id"], make_pi_headers(inv["id"]))
        validate_error(resp, ApiErrorId.ERR_INVESTIGATOR_DEBARRED)

        current = get_success_data(api.get_protocol(proto2["id"], coordinator_headers))
        assert current["status"] == "DRAFT"


class TestSubmissionGateOrdering:
    def test_submit_state_error_beats_training_safety_on_withdrawn(self, api, coordinator_headers):
        """PRD §2.9: "When several rules fail on the same request, the error
        surfaced is determined by a fixed evaluation order" — with
        "4. **State legality** — the target resource must sit in a from-state
        of the attempted transition (`ERR_INVALID_STATE`)" listed ahead of
        "5. **Business safety gates** — the investigator eligibility gate of
        §3.2 ...". PRD §3.2: "withdrawal from any other state is rejected with
        `ERR_INVALID_STATE`" for states outside DRAFT/SUBMITTED/RETURNED, and
        WITHDRAWN is terminal.

        Design: Difficulty/priority_pair_validation_conflict/submit_state_precondition_beats_training_safety
        """
        # Investigator whose training lapsed before the default clock.
        inv = register_investigator(training_expires_at="2026-01-01T00:00:00Z")
        proto = create_draft_protocol(inv["id"], title="Dual Fail Study")
        # Withdraw from DRAFT so the protocol sits in a terminal state.
        withdrawn = get_success_data(
            api.withdraw_protocol(proto["id"], make_pi_headers(inv["id"]))
        )
        assert withdrawn["status"] == "WITHDRAWN"

        # Both the state rule and the training gate fail; state wins.
        resp = api.submit_protocol(proto["id"], make_pi_headers(inv["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        current = get_success_data(api.get_protocol(proto["id"], coordinator_headers))
        assert current["status"] == "WITHDRAWN"

    def test_submit_training_error_surfaces_when_state_is_valid(self, api):
        """PRD §3.2: "an investigator whose `training_expires_at` is not
        strictly after the current logical time is rejected with
        `ERR_PI_TRAINING_LAPSED`". PRD §2.9 fixes state legality (step 4)
        ahead of the business safety gates (step 5), so the same lapsed
        investigator sees the training error only when the state check passes.

        Design: Difficulty/priority_pair_validation_conflict/submit_state_precondition_beats_training_safety
        """
        inv = register_investigator(training_expires_at="2026-01-01T00:00:00Z")
        proto = create_draft_protocol(inv["id"], title="Training Only Study")
        upload_consent(proto["id"], inv["id"], file_ref="s3://consent/tonly.pdf")

        resp = api.submit_protocol(proto["id"], make_pi_headers(inv["id"]))
        validate_error(resp, ApiErrorId.ERR_PI_TRAINING_LAPSED)


class TestComplianceScoreDualVariant:
    def _setup_score_scenario(self, api):
        """Investigator with an APPROVED protocol; two confirmed findings, one
        open case, and one late unfiled adverse-event report; plus a second
        DRAFT protocol with a consent document."""
        scenario = setup_approved_protocol()
        inv = scenario["investigator"]
        proto = scenario["protocol"]

        # Two confirmed findings (the first suspends the APPROVED protocol;
        # the second is recorded against the SUSPENDED protocol).
        for reason in ("audit finding one", "audit finding two"):
            case = open_manual_case(proto["id"], reason=reason)
            investigate_case(case["id"])
            issue_finding_ok(case["id"], "CONFIRMED")

        # A third case left OPENED.
        open_manual_case(proto["id"], reason="audit open three")

        # One late SERIOUS_ADVERSE_EVENT left FILED (never triaged):
        # occurred 2026-05-10, 5-day deadline 2026-05-15, reported at 2026-06-01.
        set_clock("2026-06-01T00:00:00Z")
        file_adverse_event_ok(
            proto["id"], inv["id"],
            event_type="SERIOUS_ADVERSE_EVENT",
            occurred_at="2026-05-10T00:00:00Z",
            description="late SAE",
        )

        proto2 = create_draft_protocol(inv["id"], title="Score Study 2")
        upload_consent(proto2["id"], inv["id"], file_ref="s3://consent/score2.pdf")
        return inv, proto, proto2

    def test_compliance_score_gate_blocks_second_submit(self, api, coordinator_headers):
        """PRD §3.2: "an investigator whose `provisional_compliance_score` is
        below the submission gate of 60 is rejected with
        `ERR_COMPLIANCE_SCORE_TOO_LOW`." PRD §3.8: "The
        `provisional_compliance_score` deducts those same confirmed findings
        and, on top, 5 points per case in `OPENED` or `INVESTIGATION` and 8
        points per late report still standing in `FILED`."

        Design: Difficulty/dual_variant_calc/compliance_score_provisional_gate_vs_final_adjudication
        """
        inv, _proto, proto2 = self._setup_score_scenario(api)

        # provisional = 100 - 2*20 (confirmed) - 5 (open case) - 8 (late FILED) = 47.
        resp = api.submit_protocol(proto2["id"], make_pi_headers(inv["id"]))
        validate_error(resp, ApiErrorId.ERR_COMPLIANCE_SCORE_TOO_LOW)

        current = get_success_data(api.get_protocol(proto2["id"], coordinator_headers))
        assert current["status"] == "DRAFT"

    def test_compliance_score_provisional_and_final_readback(self, api, coordinator_headers):
        """PRD §3.8: "The `final_compliance_score` deducts 20 points per
        confirmed finding — cases with `finding_confirmed` true sitting in
        `FINDING_CONFIRMED` or `CLOSED`." and "When the `final_compliance_score`
        drops below 60, the investigator's `status` flips to `DEBARRED`" — so a
        final score of exactly 60 leaves the investigator ACTIVE while the
        provisional score (47 here) already blocks submission.

        Design: Difficulty/dual_variant_calc/compliance_score_provisional_gate_vs_final_adjudication
        """
        inv, _proto, _proto2 = self._setup_score_scenario(api)

        inv_after = get_success_data(api.get_investigator(inv["id"], coordinator_headers))
        assert inv_after["final_compliance_score"] == 60, (
            f"final = 100 - 2*20 = 60, got {inv_after['final_compliance_score']}"
        )
        assert inv_after["provisional_compliance_score"] == 47, (
            f"provisional = 60 - 5 - 8 = 47, got {inv_after['provisional_compliance_score']}"
        )
        assert inv_after["status"] == "ACTIVE", (
            "final score of exactly 60 is not below the debarment threshold"
        )
