"""Board proceedings: the parallel claim/defense state machine, the central-attack
cascade through Registration to Madrid, default judgment side effects, the
withdraw deadline invariant, and clerk-exclusive authorization.

Sources: Difficulty/non_linear_state_machine, Difficulty/transitive_cascade,
Difficulty/compensating_invariant, Corner/state_machines, Corner/rbac.
"""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_paginated,
    setup_opposition_with_owner_and_rival,
    setup_registered_with_certified_madrid,
    answer_proceeding,
    set_for_trial,
    institute_cancellation,
    set_clock,
    examiner_headers,
    ttab_clerk_headers,
)
from test_helpers.factories import decide_payload


class TestParallelClaimAndDefenseDimensions:
    """defense_status advances AWAITING_ANSWER -> ANSWERED independently, and
    claim_status advances PLEADED -> TRIAL only after defense_status==ANSWERED."""

    def test_set_for_trial_after_answer_advances_claim_to_trial(self, api):
        """PRD §3.6: "When a proceeding has been answered, a clerk may set it for
        trial, moving claim_status from PLEADED to TRIAL, permitted only when
        claim_status is PLEADED and defense_status is ANSWERED."

        Design: Difficulty/non_linear_state_machine/ttab_parallel_claim_and_defense_dimensions
        """
        s = setup_opposition_with_owner_and_rival(class_numbers=(9,), mark_text="PARALLEL")
        answer_proceeding(s["proceeding"]["id"], s["owner_headers"])
        trial = validate_success(api.set_for_trial_ttab_proceeding(
            s["proceeding"]["id"], ttab_clerk_headers()), 200)
        assert trial["claim_status"] == "TRIAL"

    def test_defense_status_answered_independent_of_claim(self, api):
        """PRD §3.6: "The defendant answers, moving defense_status from
        AWAITING_ANSWER to ANSWERED."
        PRD §3.6: "Every proceeding tracks two independent dimensions."

        Design: Difficulty/non_linear_state_machine/ttab_parallel_claim_and_defense_dimensions
        """
        s = setup_opposition_with_owner_and_rival(class_numbers=(9,), mark_text="PARALLEL2")
        answer_proceeding(s["proceeding"]["id"], s["owner_headers"])
        trial = validate_success(api.set_for_trial_ttab_proceeding(
            s["proceeding"]["id"], ttab_clerk_headers()), 200)
        # Both dimensions reflect their independent progress on the same row.
        assert trial["defense_status"] == "ANSWERED"
        assert trial["claim_status"] == "TRIAL"


class TestCancellationCascadeToMadrid:
    """decide(SUSTAIN) on a CANCELLATION cancels the Registration, and that
    cancellation within the dependency period ceases the dependent Madrid app —
    a depth-3 cascade."""

    def _setup_to_trial(self):
        s = setup_registered_with_certified_madrid(
            class_numbers=(9,), designated_countries=("FR", "DE", "JP"), mark_text="CENTRAL")
        proc = institute_cancellation(
            s["registration"]["id"], s["rival"]["id"], s["att_headers"])
        answer_proceeding(proc["id"], s["att_headers"])
        set_for_trial(proc["id"])
        s["proceeding"] = proc
        return s

    def test_sustained_cancellation_cancels_registration(self, api):
        """PRD §3.6: "a cancellation cancels the targeted registration and nulls its
        next_maintenance_due_at"

        Design: Difficulty/transitive_cascade/cancellation_sustained_cascades_registration_then_madrid
        """
        s = self._setup_to_trial()
        decided = validate_success(api.decide_ttab_proceeding(
            s["proceeding"]["id"], decide_payload("SUSTAIN"), ttab_clerk_headers()), 200)
        assert decided["claim_status"] == "SUSTAINED"
        reg = validate_success(api.get_registration(
            s["registration"]["id"], examiner_headers()), 200)
        assert reg["status"] == "CANCELLED"
        assert reg["next_maintenance_due_at"] is None

    def test_sustained_cancellation_ceases_dependent_madrid(self, api):
        """PRD §3.6: "for every MadridApplication whose basic application is the
        cancelled registration's underlying application, and for which the current
        instant is still before that international application's dependency_end_at,
        the international application's status is set to CEASED."

        Design: Difficulty/transitive_cascade/cancellation_sustained_cascades_registration_then_madrid
        """
        s = self._setup_to_trial()
        validate_success(api.decide_ttab_proceeding(
            s["proceeding"]["id"], decide_payload("SUSTAIN"), ttab_clerk_headers()), 200)
        madrid = validate_success(api.get_madrid_application(
            s["madrid"]["id"], examiner_headers()), 200)
        assert madrid["status"] == "CEASED"


class TestEnterDefaultSideEffects:
    """Past the answer_deadline with no answer, enter-default sets defense
    DEFAULTED, claim SUSTAINED, and abandons the opposed application."""

    def test_enter_default_sustains_and_abandons(self, api):
        """PRD §3.6: "a clerk enters default, moving defense_status from
        AWAITING_ANSWER to DEFAULTED, valid only once the current instant is past
        the answer_deadline."
        PRD §3.6: "sets the claim_status to SUSTAINED and cascades to the attacked
        mark: for an opposition, the targeted application's status becomes ABANDONED
        and that applicant's open_application_count is decremented by one"

        Design: Corner/state_machines/ttab_enter_default_after_answer_deadline_sustains_and_abandons
        """
        s = setup_opposition_with_owner_and_rival(class_numbers=(9,), mark_text="DEFAULTED")
        # filed 2026-01-01, answer_deadline = +40d = 2026-02-10; advance past it.
        set_clock("2026-03-01T00:00:00Z")
        defaulted = validate_success(api.enter_default_ttab_proceeding(
            s["proceeding"]["id"], ttab_clerk_headers()), 200)
        assert defaulted["defense_status"] == "DEFAULTED"
        assert defaulted["claim_status"] == "SUSTAINED"
        app = validate_success(api.get_application(
            s["application"]["id"], examiner_headers()), 200)
        assert app["status"] == "ABANDONED"


class TestWithdrawConservesPendingDeadline:
    """Institution creates one PENDING OPPOSITION_ANSWER deadline; withdraw
    cancels it, leaving zero PENDING OPPOSITION_ANSWER deadlines."""

    def test_institute_then_withdraw_leaves_no_pending_answer_deadline(self, api):
        """PRD §3.6: "A petitioner may also withdraw a pleaded proceeding, moving
        claim_status from PLEADED to WITHDRAWN, which cancels any still-PENDING
        OPPOSITION_ANSWER docket deadline for the proceeding."

        Design: Difficulty/compensating_invariant/pending_answer_deadline_conserved_institute_then_withdraw
        """
        s = setup_opposition_with_owner_and_rival(class_numbers=(9,), mark_text="ANSWER")
        withdrawn = validate_success(api.withdraw_ttab_proceeding(
            s["proceeding"]["id"], s["rival_headers"]), 200)
        assert withdrawn["claim_status"] == "WITHDRAWN"
        # The proceeding's OPPOSITION_ANSWER deadlines roll up to the application.
        data, meta = validate_paginated(api.list_application_docket_deadlines(
            s["application"]["id"], examiner_headers(),
            params={"status": "PENDING"}))
        pending_answers = [
            d for d in data
            if d["subject_type"] == "OPPOSITION_ANSWER" and d["subject_id"] == s["proceeding"]["id"]
        ]
        assert len(pending_answers) == 0, (
            f"expected zero PENDING OPPOSITION_ANSWER deadlines, got {len(pending_answers)}")

    def test_withdraw_does_not_abandon_target_application(self, api):
        """PRD §3.6: "A petitioner may also withdraw a pleaded proceeding, moving
        claim_status from PLEADED to WITHDRAWN, which cancels any still-PENDING
        OPPOSITION_ANSWER docket deadline for the proceeding."

        Design: Difficulty/compensating_invariant/pending_answer_deadline_conserved_institute_then_withdraw
        """
        s = setup_opposition_with_owner_and_rival(class_numbers=(9,), mark_text="ANSWER2")
        validate_success(api.withdraw_ttab_proceeding(
            s["proceeding"]["id"], s["rival_headers"]), 200)
        # Withdrawal carries no cascade; the attacked application survives PUBLISHED.
        app = validate_success(api.get_application(
            s["application"]["id"], examiner_headers()), 200)
        assert app["status"] == "PUBLISHED"


class TestTTabAuthorization:
    """Clerk-exclusive operations reject other roles."""

    def test_attorney_cannot_decide_proceeding(self, api):
        """PRD §2.1: "When the headers are well-formed but the named role is not
        permitted to perform the requested operation, the request is rejected with
        ERR_UNAUTHORIZED."

        Design: Corner/rbac/attorney_cannot_decide_ttab_returns_unauthorized
        """
        s = setup_opposition_with_owner_and_rival(class_numbers=(9,), mark_text="CLERKONLY")
        answer_proceeding(s["proceeding"]["id"], s["owner_headers"])
        set_for_trial(s["proceeding"]["id"])
        # An Attorney (the attorney of record) tries the TTABClerk-only decide.
        res = api.decide_ttab_proceeding(
            s["proceeding"]["id"], decide_payload("SUSTAIN"), s["att_headers"])
        validate_error(res, "ERR_UNAUTHORIZED")
