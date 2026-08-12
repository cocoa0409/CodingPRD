"""Screening dispositions, the red-flag cascade, and escalation lifecycle loops."""
import pytest

from test_helpers import (
    ApiErrorId,
    advance_to_dd_review,
    create_red_flag,
    disposition_check,
    escalate_flag,
    get_check_ids,
    get_open_case_id,
    get_third_party,
    officer_headers,
    setup_escalated_case,
    setup_third_party_in_state,
    submit_third_party,
    analyst_headers,
    finance_headers,
    approve_third_party,
    walk_to_questionnaire_accepted,
    validate_error,
    validate_success,
)
from test_helpers.test_users import OFFICER_1_ID, OFFICER_2_ID


class TestSanctionsHitScreeningCascade:
    """A confirmed SANCTIONS hit drives the four-level cascade while the party
    is still mid-screening."""

    def _setup_confirmed_sanctions_hit(self, api):
        ctx = setup_third_party_in_state("SCREENING", "BR", 30, "CONSULTING", "DIRECT",
                                         legal_name="BR Consulting Ltd")
        tp_id = ctx["third_party"]["id"]
        pep_id, am_id, san_id = get_check_ids(tp_id)
        disposition_check(san_id, "POTENTIAL_HIT", match_detail="entity on OFAC SDN list")
        confirmed = disposition_check(san_id, "HIT_CONFIRMED")
        disposition_check(pep_id, "CLEAR")
        disposition_check(am_id, "CLEAR")
        return tp_id, san_id, confirmed

    def test_hit_confirm_spawns_critical_flag_pinned_to_check(self, api):
        """PRD §3.3: "Second, a red flag is created with `source_type`
        `SCREENING`, `source_ref_id` pointing at the confirming check,
        `flag_status` `OPEN`, and a severity keyed to the check's `check_type` —
        `CRITICAL` for `SANCTIONS`, `HIGH` for `PEP`, `MEDIUM` for
        `ADVERSE_MEDIA`. Third, but only when that severity is `CRITICAL`, the
        newborn flag is immediately escalated: it moves from `OPEN` to
        `UNDER_ENHANCED_REVIEW`, and an escalation case opens in `ENHANCED_DD`
        with a null `escalated_by_user_id` to mark it as system-initiated."

        Design: Difficulty/transitive_cascade/sanctions_hit_screening_cascade
        """
        tp_id, san_id, confirmed = self._setup_confirmed_sanctions_hit(api)
        assert confirmed["check_status"] == "HIT_CONFIRMED"

        flags = validate_success(api.list_red_flags(tp_id, officer_headers()), 200)
        assert len(flags) == 1
        assert flags[0]["source_type"] == "SCREENING"
        assert flags[0]["source_ref_id"] == san_id, "flag must be pinned to the confirming check"
        assert flags[0]["severity"] == "CRITICAL"
        assert flags[0]["flag_status"] == "UNDER_ENHANCED_REVIEW"

        cases = validate_success(api.list_escalation_cases(tp_id, officer_headers()), 200)
        assert len(cases) == 1
        assert cases[0]["case_status"] == "ENHANCED_DD"
        assert cases[0]["escalated_by_user_id"] is None

    def test_hit_confirm_suppresses_auto_advance_and_overrides_score(self, api):
        """PRD §3.3: "First, the server recomputes the party's
        `risk_score_provisional` and `risk_tier` under the confirmed hit: a
        confirmed `SANCTIONS` check overrides the score to 100 and forces
        `CRITICAL`, while the `PEP` and `ADVERSE_MEDIA` increments are reserved
        for the final variant described in §3.4."
        PRD §3.3: "Fourth, again only for `CRITICAL`, the third party itself
        lurches — from `APPROVED` to `SUSPENDED` if it had already been approved,
        or from `SCREENING` or `DD_REVIEW` to `ENHANCED_REVIEW` if still
        onboarding. Only after this cascade does the server re-evaluate the
        screening-to-review auto-advance of §3.2, and only if the party is still
        in `SCREENING`."

        Design: Difficulty/transitive_cascade/sanctions_hit_screening_cascade
        """
        tp_id, _, _ = self._setup_confirmed_sanctions_hit(api)
        tp = get_third_party(tp_id)
        # Even though all three checks are now terminal, the cascade moved the
        # party out of SCREENING first, so no DD_REVIEW auto-advance occurs.
        assert tp["onboarding_status"] == "ENHANCED_REVIEW"
        assert tp["risk_score_provisional"] == 100
        assert tp["risk_tier"] == "CRITICAL"


class TestScreeningDispositionRules:
    def test_disposition_on_terminal_check_rejected(self, api, analyst_headers):
        """PRD §3.3: "Dispositions against an already-terminal check are refused
        with `ERR_ALREADY_TERMINAL`."

        Design: Corner/state_machines/disposition_on_terminal_check_rejected
        """
        ctx = setup_third_party_in_state("SCREENING", "CH", 80)
        tp_id = ctx["third_party"]["id"]
        pep_id, _, _ = get_check_ids(tp_id)
        disposition_check(pep_id, "CLEAR")

        resp = api.disposition_screening_check(
            pep_id, {"outcome": "POTENTIAL_HIT", "match_detail": "late match"}, analyst_headers
        )
        validate_error(resp, ApiErrorId.ERR_ALREADY_TERMINAL)

    def test_screening_auto_advance_after_third_disposition(self, api):
        """PRD §3.2: "After every screening disposition, the server re-checks
        whether all three of the party's checks have reached a terminal state —
        `CLEAR`, `HIT_CONFIRMED`, or `HIT_DISMISSED` — and, if the party is still
        sitting in `SCREENING`, moves it to `DD_REVIEW`."

        Design: Corner/state_machines/screening_auto_advance_after_third_disposition
        """
        ctx = setup_third_party_in_state("SCREENING", "CH", 80)
        tp_id = ctx["third_party"]["id"]
        pep_id, am_id, san_id = get_check_ids(tp_id)
        disposition_check(pep_id, "CLEAR")
        disposition_check(am_id, "POTENTIAL_HIT", match_detail="name-similarity match")
        disposition_check(am_id, "HIT_DISMISSED")

        # Two checks terminal, SANCTIONS still QUEUED: the party stays SCREENING.
        assert get_third_party(tp_id)["onboarding_status"] == "SCREENING"

        disposition_check(san_id, "CLEAR")
        assert get_third_party(tp_id)["onboarding_status"] == "DD_REVIEW"


class TestRedFlagRules:
    def test_manual_red_flag_on_draft_rejected(self, api, officer_headers):
        """PRD §3.3: "Red flags also arise by hand. A `ComplianceOfficer` or
        `ScreeningAnalyst` may raise one on any third party that has moved past
        `DRAFT`, supplying a `severity` of `LOW`, `MEDIUM`, `HIGH`, or `CRITICAL`
        and a free-text `description`; the flag is born `OPEN` with `source_type`
        `MANUAL` and a null `source_ref_id`."
        PRD §2.10: "a transition the machine does not permit from the entity's
        current non-terminal state is rejected with `ERR_INVALID_STATE`
        (HTTP 409)."

        Design: Corner/state_machines/manual_red_flag_on_draft_rejected
        """
        ctx = setup_third_party_in_state("DRAFT", "CH", 80)
        tp_id = ctx["third_party"]["id"]
        resp = api.create_red_flag(
            tp_id, {"severity": "LOW", "description": "too early"}, officer_headers
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_critical_red_flag_cannot_be_cleared_directly(self, api, officer_headers,
                                                          officer2_headers):
        """PRD §3.3: "A manually raised `CRITICAL` flag auto-escalates at creation
        exactly as a screening-sourced one does — flag to `UNDER_ENHANCED_REVIEW`,
        case opened in `ENHANCED_DD`, third party suspended or pushed into
        enhanced review — and the same treatment applies to the `SYSTEM`-sourced
        flags of §3.1 and the `AUDIT`-sourced flags of §3.9."
        PRD §3.3: "Clearing is unavailable for `CRITICAL` flags — they can only
        be resolved by the escalation decision of §3.5 — and escalating records
        the acting officer as the case's `escalated_by_user_id` while driving the
        same third-party status move as the automatic path. Flags under enhanced
        review are resolved only by that decision, never directly."
        PRD §2.10: "a transition the machine does not permit from the entity's
        current non-terminal state is rejected with `ERR_INVALID_STATE`
        (HTTP 409)."

        Design: Corner/state_machines/critical_red_flag_cannot_be_cleared_directly
        """
        ctx = setup_third_party_in_state("DD_REVIEW", "CH", 80)
        tp_id = ctx["third_party"]["id"]

        create_resp = api.create_red_flag(
            tp_id, {"severity": "CRITICAL", "description": "whistleblower allegation"},
            officer_headers,
        )
        flag = validate_success(create_resp, 201)
        assert flag["flag_status"] == "UNDER_ENHANCED_REVIEW", (
            "CRITICAL flags auto-escalate at creation"
        )

        resp = api.disposition_red_flag(
            flag["id"], {"disposition": "CLEARED", "note": "not credible"}, officer2_headers
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestEscalationLoops:
    def _setup_enhanced_review_via_medium_flag(self, api):
        """DD_REVIEW party with ACCEPTED questionnaire; MEDIUM flag escalated by
        officer u_co1 -> ENHANCED_REVIEW with an ENHANCED_DD case."""
        ctx = setup_third_party_in_state("DD_REVIEW", "CH", 80)
        tp_id = ctx["third_party"]["id"]
        walk_to_questionnaire_accepted(tp_id)
        esc = setup_escalated_case(tp_id, OFFICER_1_ID, severity="MEDIUM")
        return ctx, tp_id, esc

    def test_escalation_loop_returns_to_dd_review(self, api, officer2_headers):
        """PRD §3.5: "`APPROVE_WITH_CONDITIONS` clears the linked flags to
        `CLEARED` and restores the third party — from `ENHANCED_REVIEW` back to
        `DD_REVIEW`, or from `SUSPENDED` back to `APPROVED`."

        Design: Difficulty/non_linear_state_machine/third_party_enhanced_review_and_suspend_reinstate_cycles
        """
        _, tp_id, esc = self._setup_enhanced_review_via_medium_flag(api)
        assert get_third_party(tp_id)["onboarding_status"] == "ENHANCED_REVIEW"

        decide_resp = api.decide_escalation_case(
            esc["case_id"],
            {"outcome": "APPROVE_WITH_CONDITIONS",
             "conditions_note": "UBO disclosure within 30 days"},
            officer2_headers,
        )
        case = validate_success(decide_resp, 200)
        assert case["case_status"] == "DECIDED"

        flags = validate_success(api.list_red_flags(tp_id, officer_headers()), 200)
        assert flags[0]["flag_status"] == "CLEARED"
        assert get_third_party(tp_id)["onboarding_status"] == "DD_REVIEW"

    def test_suspend_reinstate_loop_and_approval_snapshot(self, api, officer_headers,
                                                          officer2_headers):
        """PRD §3.5: "Approval stamps `approval_tier_snapshot` with the current
        `risk_tier` and `approved_policy_id` with the active policy's id — from
        then on, contract clause requirements key off this snapshot rather than
        the live tier"
        PRD §3.5: "Suspension moves an `APPROVED` party to `SUSPENDED` — by
        officer action with an optional `reason`, by the system when a `CRITICAL`
        flag auto-escalates, or by the clock sweep when a re-diligence cycle has
        been `OVERDUE` for more than 30 days. Reinstatement returns a `SUSPENDED`
        party to `APPROVED` once no `OPEN` or `UNDER_ENHANCED_REVIEW` flag and no
        `ENHANCED_DD` case remains (`ERR_RED_FLAGS_OPEN` otherwise), and is
        equally reachable through an escalation decision of
        `APPROVE_WITH_CONDITIONS`."

        Design: Difficulty/non_linear_state_machine/third_party_enhanced_review_and_suspend_reinstate_cycles
        """
        ctx, tp_id, esc = self._setup_enhanced_review_via_medium_flag(api)
        decide_resp = api.decide_escalation_case(
            esc["case_id"],
            {"outcome": "APPROVE_WITH_CONDITIONS",
             "conditions_note": "UBO disclosure within 30 days"},
            officer2_headers,
        )
        validate_success(decide_resp, 200)

        approved = approve_third_party(tp_id)
        assert approved["onboarding_status"] == "APPROVED"
        assert approved["approval_tier_snapshot"] == "LOW"
        assert approved["approved_policy_id"] == ctx["policy"]["id"]

        susp_resp = api.suspend_third_party(tp_id, {"reason": "media allegation"},
                                            officer_headers)
        assert validate_success(susp_resp, 200)["onboarding_status"] == "SUSPENDED"

        rein_resp = api.reinstate_third_party(tp_id, officer_headers)
        assert validate_success(rein_resp, 200)["onboarding_status"] == "APPROVED"


class TestEscalationCaseRules:
    def test_decide_on_decided_case_rejected(self, api, officer2_headers):
        """PRD §2.10: "Terminal states — `REJECTED` and `TERMINATED` for a third
        party; `CLEAR`, `HIT_CONFIRMED`, and `HIT_DISMISSED` for a check;
        `ACCEPTED` and `SUPERSEDED` for a questionnaire; `CLEARED` and
        `SUBSTANTIATED` for a red flag; `DECIDED` for a case; `EXPIRED` and
        `TERMINATED` for a contract; `BLOCKED` and `REVERSED` for a payment;
        `REJECTED` and `VOIDED` for a gift entry; `COMPLETED` for a cycle;
        `CLOSED` for an audit; `COMPLETED` for a training assignment;
        `SUPERSEDED` for a policy — are locked: any further action attempted
        against an entity in one of them is rejected with `ERR_ALREADY_TERMINAL`
        (HTTP 409), while a transition the machine does not permit from the
        entity's current non-terminal state is rejected with `ERR_INVALID_STATE`
        (HTTP 409)."

        Design: Corner/state_machines/decide_on_decided_case_rejected
        """
        ctx = setup_third_party_in_state("DD_REVIEW", "CH", 80)
        tp_id = ctx["third_party"]["id"]
        esc = setup_escalated_case(tp_id, OFFICER_1_ID, severity="MEDIUM")

        first = api.decide_escalation_case(
            esc["case_id"],
            {"outcome": "APPROVE_WITH_CONDITIONS", "conditions_note": "UBO disclosure"},
            officer2_headers,
        )
        validate_success(first, 200)

        replay = api.decide_escalation_case(esc["case_id"], {"outcome": "TERMINATE"},
                                            officer2_headers)
        validate_error(replay, ApiErrorId.ERR_ALREADY_TERMINAL)

        tp = get_third_party(tp_id)
        assert tp["onboarding_status"] == "DD_REVIEW", (
            "the first decision's side effects must not be re-applied by a replay"
        )

    def test_escalation_decider_cannot_be_escalator(self, api, officer_headers,
                                                    officer2_headers):
        """PRD §2.8: "the officer who decides an escalation case must differ from
        the case's `escalated_by_user_id` whenever that field is non-null.
        System-initiated escalations carry a null `escalated_by_user_id` and
        impose no restriction on the decider. Each violation is rejected with
        `ERR_SOD_VIOLATION` (HTTP 403)."
        PRD §3.5: "auto-escalated cases carry a null escalator and may be decided
        by any officer."

        Design: Corner/rbac/escalation_decider_cannot_be_escalator
        """
        ctx = setup_third_party_in_state("DD_REVIEW", "CH", 80)
        tp_id = ctx["third_party"]["id"]
        esc = setup_escalated_case(tp_id, OFFICER_1_ID, severity="MEDIUM")

        cases = validate_success(api.list_escalation_cases(tp_id, officer_headers), 200)
        assert cases[0]["escalated_by_user_id"] == OFFICER_1_ID

        own = api.decide_escalation_case(
            esc["case_id"],
            {"outcome": "APPROVE_WITH_CONDITIONS", "conditions_note": "x"},
            officer_headers,  # u_co1 — the escalating officer
        )
        validate_error(own, ApiErrorId.ERR_SOD_VIOLATION)

        peer = api.decide_escalation_case(
            esc["case_id"],
            {"outcome": "APPROVE_WITH_CONDITIONS",
             "conditions_note": "UBO disclosure within 30 days"},
            officer2_headers,  # u_co2 — an independent officer
        )
        assert validate_success(peer, 200)["case_status"] == "DECIDED"


class TestScreeningRbac:
    def test_finance_reviewer_cannot_disposition_screening(self, api, finance_headers):
        """PRD §2.1: "A request whose role is not in the endpoint's authorized
        role list is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
        PRD §4 lists POST /compliance/screening-checks/{check_id}/disposition
        with ScreeningAnalyst as its only authorized role.

        Design: Corner/rbac/finance_reviewer_cannot_disposition_screening
        """
        ctx = setup_third_party_in_state("SCREENING", "CH", 80)
        tp_id = ctx["third_party"]["id"]
        pep_id, _, _ = get_check_ids(tp_id)

        resp = api.disposition_screening_check(pep_id, {"outcome": "CLEAR"}, finance_headers)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)

        checks = validate_success(api.list_screening_checks(tp_id, officer_headers()), 200)
        assert checks[0]["check_status"] == "QUEUED", "the check must be untouched"
