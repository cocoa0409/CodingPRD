"""TPA engagement oversight: window exclusivity, suspend/reinstate loop,
remediation notes, breach auto-suspension, and authority-vs-evidence gating."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    attach_evidence,
    create_claim,
    create_employer,
    create_separation,
    create_state_rule,
    create_tpa_engagement,
    draft_response,
    file_late_response,
    get_claim,
    get_employer,
    get_engagement,
    get_response,
    set_clock,
    submit_response,
    validate_error,
    validate_success,
)

ANALYST = TEST_USERS["claims_analyst_headers"]
TPA_AGENT = TEST_USERS["tpa_agent_headers"]
TPA_MANAGER = TEST_USERS["tpa_manager_headers"]


class TestEngagementWindowExclusivity:
    def test_touching_windows_intersect_closed_interval(self, api):
        """PRD §3.1: "Engagement windows are exclusive per employer: creating
        an engagement whose closed interval — both endpoints included —
        intersects the interval of any existing non-`TERMINATED` engagement for
        the same employer is rejected with `ERR_TPA_WINDOW_OVERLAP`, and two
        windows that merely touch at a boundary timestamp do intersect."

        Design: Difficulty/resource_temporal_overlap/tpa_engagement_window_closed_interval_overlap
        """
        set_clock("2026-08-03T09:00:00Z")
        employer = create_employer(legal_name="WinCo")
        eng1 = create_tpa_engagement(employer["id"], tpa_name="FirstTpa",
                                     effective_from="2026-01-01T00:00:00Z",
                                     effective_to="2026-06-30T23:59:59Z")
        assert eng1["oversight_status"] == "ACTIVE"

        # Starting exactly at the existing window's inclusive end intersects.
        err = api.create_tpa_engagement(
            {"employer_id": employer["id"], "tpa_name": "TouchTpa",
             "authority_scope": "RESPONSE_ONLY",
             "effective_from": "2026-06-30T23:59:59Z",
             "effective_to": "2026-12-31T23:59:59Z"}, TPA_MANAGER)
        validate_error(err, ApiErrorId.ERR_TPA_WINDOW_OVERLAP, 409)

        # One second later the windows are disjoint.
        eng2 = validate_success(
            api.create_tpa_engagement(
                {"employer_id": employer["id"], "tpa_name": "CleanTpa",
                 "authority_scope": "RESPONSE_ONLY",
                 "effective_from": "2026-07-01T00:00:00Z",
                 "effective_to": "2026-12-31T23:59:59Z"}, TPA_MANAGER), 201)
        assert eng2["oversight_status"] == "ACTIVE"
        assert get_engagement(eng1["id"])["oversight_status"] == "ACTIVE"

    def test_terminated_engagement_frees_its_window(self, api):
        """PRD §3.1: "creating an engagement whose closed interval — both
        endpoints included — intersects the interval of any existing
        non-`TERMINATED` engagement for the same employer is rejected with
        `ERR_TPA_WINDOW_OVERLAP`"
        PRD §3.1: "otherwise the engagement becomes `TERMINATED`, its terminal
        state."

        Design: Difficulty/resource_temporal_overlap/tpa_engagement_window_closed_interval_overlap
        """
        set_clock("2026-08-03T09:00:00Z")
        employer = create_employer(legal_name="TermWinCo")
        eng1 = create_tpa_engagement(employer["id"], tpa_name="OldTpa",
                                     effective_from="2026-01-01T00:00:00Z",
                                     effective_to="2026-06-30T23:59:59Z")
        terminated = validate_success(
            api.terminate_tpa_engagement(eng1["id"], TPA_MANAGER), 200)
        assert terminated["oversight_status"] == "TERMINATED"

        # A TERMINATED engagement no longer blocks the window.
        eng2 = validate_success(
            api.create_tpa_engagement(
                {"employer_id": employer["id"], "tpa_name": "NewTpa",
                 "authority_scope": "FULL",
                 "effective_from": "2026-03-01T00:00:00Z",
                 "effective_to": "2026-12-31T23:59:59Z"}, TPA_MANAGER), 201)
        assert eng2["oversight_status"] == "ACTIVE"


class TestSuspendReinstateLoop:
    def test_suspend_then_reinstate_resets_breach_count_to_one(self, api):
        """PRD §3.1: "Reinstatement requires the engagement to be `SUSPENDED`
        (otherwise `ERR_TPA_NOT_SUSPENDED`) and a `remediation_note` of at
        least 20 characters (otherwise `ERR_REMEDIATION_NOTE_SHORT`); a
        reinstated engagement's `breach_count` resets to one, not zero — prior
        history is retained."

        Design: Difficulty/non_linear_state_machine/tpa_suspend_reinstate_loop
        """
        set_clock("2026-08-03T09:00:00Z")
        employer = create_employer(legal_name="TpaCo")
        eng = create_tpa_engagement(employer["id"], tpa_name="ClaimShield")
        assert eng["oversight_status"] == "ACTIVE"
        assert eng["breach_count"] == 0

        suspended = validate_success(
            api.suspend_tpa_engagement(eng["id"], TPA_MANAGER), 200)
        assert suspended["oversight_status"] == "SUSPENDED"

        reinstated = validate_success(
            api.reinstate_tpa_engagement(eng["id"],
                                         "Staff retrained on deadline tracking.",
                                         TPA_MANAGER), 200)
        assert reinstated["oversight_status"] == "REINSTATED"
        assert reinstated["breach_count"] == 1

    def test_reinstate_requires_suspended_state(self, api):
        """PRD §3.1: "Reinstatement requires the engagement to be `SUSPENDED`
        (otherwise `ERR_TPA_NOT_SUSPENDED`)"

        Design: Difficulty/non_linear_state_machine/tpa_suspend_reinstate_loop
        """
        set_clock("2026-08-03T09:00:00Z")
        employer = create_employer(legal_name="LoopCo")
        eng = create_tpa_engagement(employer["id"])

        err_active = api.reinstate_tpa_engagement(
            eng["id"], "A sufficiently long remediation note.", TPA_MANAGER)
        validate_error(err_active, ApiErrorId.ERR_TPA_NOT_SUSPENDED, 409)

        validate_success(api.suspend_tpa_engagement(eng["id"], TPA_MANAGER), 200)
        reinstated = validate_success(
            api.reinstate_tpa_engagement(eng["id"],
                                         "A sufficiently long remediation note.",
                                         TPA_MANAGER), 200)
        assert reinstated["oversight_status"] == "REINSTATED"

        # REINSTATED is not SUSPENDED: a second reinstate is rejected.
        err_again = api.reinstate_tpa_engagement(
            eng["id"], "A sufficiently long remediation note.", TPA_MANAGER)
        validate_error(err_again, ApiErrorId.ERR_TPA_NOT_SUSPENDED, 409)

    def test_remediation_note_too_short_rejected(self, api):
        """PRD §3.1: "a `remediation_note` of at least 20 characters (otherwise
        `ERR_REMEDIATION_NOTE_SHORT`)"

        Design: Corner/errors/error_remediate_note_too_short
        """
        set_clock("2026-08-03T09:00:00Z")
        employer = create_employer(legal_name="RemCo")
        eng = create_tpa_engagement(employer["id"], tpa_name="NoteTpa")
        validate_success(api.suspend_tpa_engagement(eng["id"], TPA_MANAGER), 200)

        err = api.reinstate_tpa_engagement(eng["id"], "too short", TPA_MANAGER)
        validate_error(err, ApiErrorId.ERR_REMEDIATION_NOTE_SHORT, 422)
        assert get_engagement(eng["id"])["oversight_status"] == "SUSPENDED"

    def test_remediation_note_exactly_twenty_chars_accepted(self, api):
        """PRD §3.1: "a `remediation_note` of at least 20 characters (otherwise
        `ERR_REMEDIATION_NOTE_SHORT`); a reinstated engagement's `breach_count`
        resets to one, not zero — prior history is retained."

        Design: Corner/errors/error_remediate_note_too_short
        """
        set_clock("2026-08-03T09:00:00Z")
        employer = create_employer(legal_name="RemEdgeCo")
        eng = create_tpa_engagement(employer["id"], tpa_name="EdgeTpa")
        validate_success(api.suspend_tpa_engagement(eng["id"], TPA_MANAGER), 200)

        reinstated = validate_success(
            api.reinstate_tpa_engagement(eng["id"], "12345678901234567890",
                                         TPA_MANAGER), 200)
        assert reinstated["oversight_status"] == "REINSTATED"
        assert reinstated["breach_count"] == 1


class TestTpaBreachAutoSuspendChain:
    def _setup_engagement_with_two_breaches(self, api):
        """Employer, FULL engagement, and two late TPA-filed responses
        (breach_count 2, two late strikes)."""
        set_clock("2026-08-03T09:00:00Z")
        create_state_rule("XX", response_window_days=5, window_basis="CALENDAR",
                          weekend_shift="NONE")
        employer = create_employer(legal_name="BreachCo")
        eng = create_tpa_engagement(employer["id"], tpa_name="FileLate",
                                    authority_scope="FULL")
        separations = [create_separation(employer["id"], claimant_name=name,
                                         ssn_last4=ssn)
                       for name, ssn in (("Jan", "9001"), ("Kay", "9002"),
                                         ("Lou", "9003"), ("Meg", "9004"))]

        # First claim: drafted before the clock passes its deadline.
        claim1 = create_claim(employer["id"], separations[0]["id"])
        resp1 = draft_response(claim1["id"], response_type="NO_PROTEST",
                               narrative="No protest.",
                               filed_by_tpa_id=eng["id"], as_tpa=True)
        attach_evidence(claim1["id"], resp1["id"], as_tpa=True)
        set_clock("2026-08-09T18:00:00Z")  # past the 5-day deadline
        submitted1 = submit_response(claim1["id"], resp1["id"], headers=TPA_AGENT)
        assert submitted1["timeliness"] == "LATE"

        # Second claim: notice already in the past at intake, filed late.
        file_late_response(employer["id"], separations[1]["id"],
                           filed_by_tpa_id=eng["id"], as_tpa=True)
        assert get_engagement(eng["id"])["breach_count"] == 2
        return employer, eng, separations

    def test_third_late_tpa_filing_auto_suspends_engagement(self, api):
        """PRD §3.4: "A late submission instead branches the claim to
        `LATE_RESPONSE`, and the lateness cascades: the employer's
        `late_response_strikes` increases by one and its `compliance_posture`
        is recomputed per §2.10, and if the filing was TPA-made the
        engagement's `breach_count` increases by one with automatic suspension
        at three breaches per §3.1."
        PRD §2.10: "an effective count of at least two but fewer than four
        yields `WATCH`"

        Design: Difficulty/transitive_cascade/late_response_tpa_breach_auto_suspend_chain
        """
        employer, eng, separations = self._setup_engagement_with_two_breaches(api)

        submitted3 = file_late_response(employer["id"], separations[2]["id"],
                                        filed_by_tpa_id=eng["id"], as_tpa=True)
        assert submitted3["timeliness"] == "LATE"
        claim3 = get_claim(submitted3["claim_id"])
        assert claim3["status"] == "LATE_RESPONSE"

        eng_after = get_engagement(eng["id"])
        assert eng_after["breach_count"] == 3
        assert eng_after["oversight_status"] == "SUSPENDED"

        employer_after = get_employer(employer["id"])
        assert employer_after["late_response_strikes"] == 3
        assert employer_after["compliance_posture"] == "WATCH"

    def test_suspended_engagement_blocks_further_tpa_filings(self, api):
        """PRD §3.1: "While an engagement is `SUSPENDED`, every `TpaAgent`
        filing under it is rejected with `ERR_TPA_NOT_ACTIVE`."

        Design: Difficulty/transitive_cascade/late_response_tpa_breach_auto_suspend_chain
        """
        employer, eng, separations = self._setup_engagement_with_two_breaches(api)
        file_late_response(employer["id"], separations[2]["id"],
                           filed_by_tpa_id=eng["id"], as_tpa=True)
        assert get_engagement(eng["id"])["oversight_status"] == "SUSPENDED"

        claim4 = create_claim(employer["id"], separations[3]["id"])
        err = api.create_response(
            claim4["id"],
            {"response_type": "NO_PROTEST", "separation_reason_code": "LAYOFF",
             "narrative": "Blocked.", "filed_by_tpa_id": eng["id"]},
            TPA_AGENT)
        validate_error(err, ApiErrorId.ERR_TPA_NOT_ACTIVE, 403)


class TestAuthorityBeforeEvidenceSufficiency:
    def test_suspended_tpa_submit_reports_authority_not_incompleteness(self, api):
        """PRD §2.8: "The tiers, evaluated in strict order, are:"
        PRD §2.8: "**TPA authority and segregation of duties** — the engagement
        must be active, in-window, and scoped for the filing, and the operator
        who drafted a response may not be the one to accept or reject it; this
        category, `ERR_AUTHORITY_VIOLATION` (HTTP 403), surfaces concretely as
        `ERR_TPA_SCOPE_VIOLATION`, `ERR_TPA_NOT_ACTIVE`, or a
        segregation-of-duties rejection."
        PRD §2.8: "**Evidence sufficiency gates** — the category
        `ERR_INSUFFICIENT_EVIDENCE` (HTTP 422) surfaces concretely as
        `ERR_RESPONSE_INCOMPLETE`, `ERR_CODING_EVIDENCE_MISSING`,
        `ERR_CONTINUANCE_LIMIT`, or `ERR_PROTEST_EVIDENCE_WEAK`."
        PRD §3.4: "a TPA-filed response must be backed by an engagement that is
        `ACTIVE` at filing time (otherwise `ERR_TPA_NOT_ACTIVE`)."

        Design: Difficulty/priority_pair_validation_conflict/business_safety_vs_business_constraint_on_tpa_file
        """
        set_clock("2026-08-03T09:00:00Z")
        create_state_rule("XX")
        employer = create_employer(legal_name="SafCo")
        eng = create_tpa_engagement(employer["id"], tpa_name="ScopeLtd")
        separation = create_separation(employer["id"])
        claim = create_claim(employer["id"], separation["id"])
        resp = draft_response(claim["id"], response_type="NO_PROTEST",
                              narrative="x", filed_by_tpa_id=eng["id"],
                              as_tpa=True)  # no evidence: score 0
        validate_success(api.suspend_tpa_engagement(eng["id"], TPA_MANAGER), 200)

        version = get_claim(claim["id"])["version"]
        err = api.submit_response(claim["id"], resp["id"], version, TPA_AGENT)
        validate_error(err, ApiErrorId.ERR_TPA_NOT_ACTIVE, 403)

    def test_each_gate_fires_in_isolation(self, api):
        """PRD §3.4: "its `completeness_score` must be at least 40 (otherwise
        `ERR_RESPONSE_INCOMPLETE`), and a TPA-filed response must be backed by
        an engagement that is `ACTIVE` at filing time (otherwise
        `ERR_TPA_NOT_ACTIVE`)."

        Design: Difficulty/priority_pair_validation_conflict/business_safety_vs_business_constraint_on_tpa_file
        """
        set_clock("2026-08-03T09:00:00Z")
        create_state_rule("XX")
        employer = create_employer(legal_name="IsoCo")
        eng = create_tpa_engagement(employer["id"], tpa_name="IsoTpa")
        sep_a = create_separation(employer["id"], claimant_name="A",
                                  ssn_last4="7001")
        sep_b = create_separation(employer["id"], claimant_name="B",
                                  ssn_last4="7002")

        # (a) ACTIVE engagement, evidence-free draft: only the score gate fails.
        claim_a = create_claim(employer["id"], sep_a["id"])
        resp_a = draft_response(claim_a["id"], response_type="NO_PROTEST",
                                narrative="x", filed_by_tpa_id=eng["id"],
                                as_tpa=True)
        version_a = get_claim(claim_a["id"])["version"]
        err_a = api.submit_response(claim_a["id"], resp_a["id"], version_a,
                                    TPA_AGENT)
        validate_error(err_a, ApiErrorId.ERR_RESPONSE_INCOMPLETE, 422)

        # (b) SUSPENDED engagement, complete draft: only authority fails.
        claim_b = create_claim(employer["id"], sep_b["id"])
        resp_b = draft_response(claim_b["id"], response_type="NO_PROTEST",
                                narrative="complete", filed_by_tpa_id=eng["id"],
                                as_tpa=True)
        attach_evidence(claim_b["id"], resp_b["id"], as_tpa=True)
        validate_success(api.suspend_tpa_engagement(eng["id"], TPA_MANAGER), 200)
        version_b = get_claim(claim_b["id"])["version"]
        err_b = api.submit_response(claim_b["id"], resp_b["id"], version_b,
                                    TPA_AGENT)
        validate_error(err_b, ApiErrorId.ERR_TPA_NOT_ACTIVE, 403)
        assert get_response(resp_b["id"])["status"] == "DRAFT"
