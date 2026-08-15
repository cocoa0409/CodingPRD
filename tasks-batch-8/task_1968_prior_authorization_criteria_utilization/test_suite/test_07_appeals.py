"""Appeals: filing, review segregation, decisions, overturn cascade (PRD §3.5, §3.8)."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    basic_um_environment,
    begin_appeal_review,
    decide_appeal,
    denied_determination,
    file_appeal,
    get_appeal,
    get_determination,
    get_provider,
    list_request_events,
    make_appeals_reviewer_headers,
    setup_appeal_scenario,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["um_admin_headers"]
CLERK = TEST_USERS["appeals_clerk_headers"]


class TestBeginReview:
    def test_begin_review_assigns_reviewer(self, api):
        """PRD §3.5: "Beginning review moves the appeal to `IN_REVIEW` and records the caller as `reviewer_id`."
        PRD §3.5: "A filed appeal starts `RECEIVED`, stamps `received_at` from the clock, and computes its `due_at` as `received_at` plus 720 hours."

        Design: Corner/state_machines/appeal_begin_review_assigns_reviewer
        """
        ctx = setup_appeal_scenario()
        appeal = ctx["appeal"]
        assert appeal["due_at"] == "2026-08-31T00:00:00.000Z", (
            "received 2026-08-01 at the startup clock plus the 720-hour "
            "appeal SLA"
        )
        reviewed = begin_appeal_review(appeal["id"], user_id="u-ar-1")
        assert reviewed["status"] == "IN_REVIEW"
        assert reviewed["reviewer_id"] == "u-ar-1"

    def test_begin_review_by_original_decider_rejected(self, api):
        """PRD §2.8: "An `AppealsReviewer` may not begin review of an appeal whose underlying determination they issued: when the determination's `decided_by_user_id` is non-null, a begin-review caller equal to it is rejected with `ERR_SEGREGATION_OF_DUTIES` (a system-issued auto-approval has a null decider and imposes no such bar)."

        Design: Corner/validations/appeal_review_by_original_decider_rejected
        """
        ctx = setup_appeal_scenario(reviewer_user_id="u-rev-1")
        appeal = ctx["appeal"]
        resp = api.begin_appeal_review(
            appeal["id"], make_appeals_reviewer_headers("u-rev-1"),
        )
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        reviewed = begin_appeal_review(appeal["id"], user_id="u-ar-1")
        assert reviewed["status"] == "IN_REVIEW"
        assert reviewed["reviewer_id"] == "u-ar-1"


class TestDecide:
    def test_decide_by_unassigned_reviewer_rejected(self, api):
        """PRD §2.8: "An appeal decision must come from the assigned reviewer — the caller must equal the appeal's `reviewer_id`, else `ERR_NOT_ASSIGNED_REVIEWER`."

        Design: Corner/validations/decide_by_unassigned_reviewer_rejected
        """
        ctx = setup_appeal_scenario(begin_review=True,
                                    appeals_reviewer_user_id="u-ar-1")
        resp = api.decide_appeal(
            ctx["appeal"]["id"], {"outcome": "UPHELD"},
            make_appeals_reviewer_headers("u-ar-2"),
        )
        validate_error(resp, ApiErrorId.ERR_NOT_ASSIGNED_REVIEWER)
        assert get_appeal(ctx["appeal"]["id"])["status"] == "IN_REVIEW"

    def test_decide_after_upheld_rejected(self, api):
        """PRD §3.5: "An `UPHELD` decision ends the matter."
        PRD §3.5: "The assigned reviewer — and only the assigned reviewer (`ERR_NOT_ASSIGNED_REVIEWER`) — then decides the appeal by supplying an `outcome` of `UPHELD` or `OVERTURNED` with an optional `rationale`; deciding from any state other than `IN_REVIEW` is `ERR_INVALID_APPEAL_STATE`."

        Design: Corner/state_machines/appeal_decide_after_upheld_rejected
        """
        ctx = setup_appeal_scenario(begin_review=True,
                                    appeals_reviewer_user_id="u-ar-1")
        first = decide_appeal(ctx["appeal"]["id"], "UPHELD", user_id="u-ar-1")
        assert first["status"] == "UPHELD"
        resp = api.decide_appeal(
            ctx["appeal"]["id"], {"outcome": "OVERTURNED"},
            make_appeals_reviewer_headers("u-ar-1"),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_APPEAL_STATE)
        reread = get_appeal(ctx["appeal"]["id"])
        assert reread["status"] == "UPHELD"
        assert reread["decided_at"] == first["decided_at"], (
            "terminal state locked: the rejected second decide changed nothing"
        )

    def test_state_error_wins_over_reviewer_assignment(self, api):
        """PRD §2.7: "Sixth, target-state preconditions (the state-machine guards of §3, e.g. `ERR_REQUEST_NOT_PENDING`). Seventh, segregation-of-duties and due-process rules."
        PRD §2.7: "A request that fails an earlier category never surfaces a later category's error."
        PRD §3.5: "deciding from any state other than `IN_REVIEW` is `ERR_INVALID_APPEAL_STATE`."

        Design: Difficulty/priority_pair_validation_conflict/appeal_decide_state_priority_over_reviewer_assignment
        """
        # Appeal still RECEIVED: reviewer_id is null, so caller u-ar-9 violates
        # the assignment rule, and the missing IN_REVIEW state violates the
        # state guard; the state category is checked first.
        ctx = setup_appeal_scenario(begin_review=False)
        resp = api.decide_appeal(
            ctx["appeal"]["id"], {"outcome": "UPHELD"},
            make_appeals_reviewer_headers("u-ar-9"),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_APPEAL_STATE)

    def test_rejected_decide_leaves_appeal_untouched(self, api):
        """PRD §2.7: "A request that fails an earlier category never surfaces a later category's error."
        PRD §3.5: "A filed appeal starts `RECEIVED`, stamps `received_at` from the clock, and computes its `due_at` as `received_at` plus 720 hours. Its `is_tat_breached` flag follows the sweep rules of §2.5, and its `decided_at` stays null until a decision."

        Design: Difficulty/priority_pair_validation_conflict/appeal_decide_state_priority_over_reviewer_assignment
        """
        ctx = setup_appeal_scenario(begin_review=False)
        resp = api.decide_appeal(
            ctx["appeal"]["id"], {"outcome": "UPHELD"},
            make_appeals_reviewer_headers("u-ar-9"),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_APPEAL_STATE)
        reread = get_appeal(ctx["appeal"]["id"])
        assert reread["status"] == "RECEIVED", "no side effects fired"
        assert reread["decided_at"] is None


class TestOneAppealPerDetermination:
    def test_second_appeal_while_open_rejected(self, api):
        """PRD §3.5: "At most one appeal per determination may exist in a non-withdrawn status — a second filing while an earlier appeal sits in `RECEIVED`, `IN_REVIEW`, `UPHELD`, or `OVERTURNED` is rejected with `ERR_APPEAL_ALREADY_OPEN`."

        Design: Corner/validations/second_appeal_while_open_rejected
        """
        ctx = setup_appeal_scenario(begin_review=True,
                                    appeals_reviewer_user_id="u-ar-1")
        resp = api.create_appeal(
            ctx["determination"]["id"], {"appeal_reason": "Second"}, CLERK,
        )
        validate_error(resp, ApiErrorId.ERR_APPEAL_ALREADY_OPEN)
        appeals = validate_success(
            api.list_determination_appeals(ctx["determination"]["id"], CLERK)
        )
        assert len(appeals) == 1


class TestOverturnCascade:
    def test_overturn_cascades_to_determination_and_request(self, api):
        """PRD §3.5: "An `OVERTURNED` decision fires a cross-entity cascade: the determination moves `FINAL → OVERTURNED` (keeping its recorded `outcome` of `DENIED` — the overturn is expressed through status, not by rewriting the outcome), the request moves `DENIED → APPROVED`, provider statistics recompute with the overturned denial now counting as an approval, and an `APPEAL_OVERTURNED` compliance event is recorded with the request and provider ids."

        Design: Difficulty/transitive_cascade/appeal_overturn_cascade_depth3
        """
        ctx = setup_appeal_scenario(begin_review=True,
                                    appeals_reviewer_user_id="u-ar-1")
        decided = decide_appeal(ctx["appeal"]["id"], "OVERTURNED",
                                user_id="u-ar-1")
        assert decided["status"] == "OVERTURNED"
        det = get_determination(ctx["determination"]["id"])
        assert det["status"] == "OVERTURNED", (
            "link 1: the appeal mutation mutated the determination"
        )
        assert det["outcome"] == "DENIED", (
            "the overturn is expressed through status, not outcome"
        )
        req = validate_success(
            api.get_prior_auth_request(ctx["request"]["id"], ADMIN)
        )
        assert req["status"] == "APPROVED", (
            "link 2: the determination mutation mutated the request"
        )

    def test_overturn_recomputes_provider_stats_and_emits_event(self, api):
        """PRD §3.5: "An `OVERTURNED` decision fires a cross-entity cascade: the determination moves `FINAL → OVERTURNED` (keeping its recorded `outcome` of `DENIED` — the overturn is expressed through status, not by rewriting the outcome), the request moves `DENIED → APPROVED`, provider statistics recompute with the overturned denial now counting as an approval, and an `APPEAL_OVERTURNED` compliance event is recorded with the request and provider ids."
        PRD §3.6: "Within that set, a determination counts as an effective approval when it is `FINAL` with `outcome` `APPROVED`, or when it is `OVERTURNED` regardless of the recorded outcome."

        Design: Difficulty/transitive_cascade/appeal_overturn_cascade_depth3
        """
        ctx = setup_appeal_scenario(begin_review=True,
                                    appeals_reviewer_user_id="u-ar-1")
        decide_appeal(ctx["appeal"]["id"], "OVERTURNED", user_id="u-ar-1")
        provider = get_provider(ctx["provider"]["id"])
        assert provider["rolling_determination_count"] == 1
        assert provider["rolling_approval_count"] == 1, (
            "link 3: the overturned denial now counts as an approval"
        )
        assert provider["lifetime_approval_count"] == 1
        events = list_request_events(
            ctx["request"]["id"], event_type="APPEAL_OVERTURNED",
        )
        assert len(events) == 1
        assert events[0]["provider_id"] == ctx["provider"]["id"]


class TestOverturnMetrics:
    def _setup_three_appeals(self, api):
        """One OVERTURNED, one UPHELD, one WITHDRAWN appeal on three separate
        reviewer-denied determinations."""
        provider, cs, _gv = basic_um_environment()
        _r1, d1 = denied_determination(
            provider["id"], cs["id"], member_ref="M-01",
            deny_reason_code="EXPERIMENTAL_INVESTIGATIONAL",
        )
        _r2, d2 = denied_determination(
            provider["id"], cs["id"], member_ref="M-02",
            deny_reason_code="MEDICAL_NECESSITY_NOT_MET",
        )
        _r3, d3 = denied_determination(
            provider["id"], cs["id"], member_ref="M-03",
            deny_reason_code="INSUFFICIENT_INFO",
        )
        a1 = file_appeal(d1["id"], appeal_reason="Additional records attached")
        begin_appeal_review(a1["id"], user_id="u-ar-1")
        decide_appeal(a1["id"], "OVERTURNED", user_id="u-ar-1",
                      rationale="Criteria met on resubmission")
        a2 = file_appeal(d2["id"], appeal_reason="Dispute reading")
        begin_appeal_review(a2["id"], user_id="u-ar-1")
        decide_appeal(a2["id"], "UPHELD", user_id="u-ar-1")
        a3 = file_appeal(d3["id"], appeal_reason="Provider withdrew interest")
        validate_success(api.withdraw_appeal(a3["id"], CLERK))

    def test_overturn_metrics_counts(self, api):
        """PRD §3.8: "Program-level oversight reads from a dedicated metrics endpoint returning seven aggregates over all appeal rows: `appeals_filed` (every appeal ever created, any status, including withdrawn and in-flight), `appeals_decided` (appeals in `UPHELD` or `OVERTURNED`), `appeals_withdrawn`, `overturned_count`, `upheld_count`, and two rate variants at 4 decimal places round-half-up."

        Design: Difficulty/dual_variant_calc/appeal_overturn_rate_decided_vs_filed
        """
        self._setup_three_appeals(api)
        metrics = validate_success(
            api.get_overturn_analysis(TEST_USERS["compliance_officer_headers"])
        )
        assert metrics["appeals_filed"] == 3
        assert metrics["appeals_decided"] == 2
        assert metrics["appeals_withdrawn"] == 1
        assert metrics["overturned_count"] == 1
        assert metrics["upheld_count"] == 1

    def test_overturn_rate_variants(self, api):
        """PRD §3.8: "`overturn_rate_decided` divides `overturned_count` by the sum of `upheld_count` and `overturned_count` — the regulatory overturn analysis, whose denominator excludes withdrawn and undecided appeals. `overturn_rate_filed` divides `overturned_count` by `appeals_filed` — the program-intake burden view, which for identical data is strictly smaller whenever undecided or withdrawn appeals exist. Either rate is null when its denominator is zero."
        PRD §2.10: "All approval and overturn rates in the system are computed to 4 decimal places using round-half-up. A rate whose denominator count is zero is represented as null rather than zero."

        Design: Difficulty/dual_variant_calc/appeal_overturn_rate_decided_vs_filed
        """
        self._setup_three_appeals(api)
        metrics = validate_success(
            api.get_overturn_analysis(TEST_USERS["compliance_officer_headers"])
        )
        assert metrics["overturn_rate_decided"] == pytest.approx(0.5), (
            "1 / (1 upheld + 1 overturned), decided-only denominator"
        )
        assert metrics["overturn_rate_filed"] == pytest.approx(0.3333), (
            "1 / 3 filed, 4dp round-half-up"
        )

    def test_overturn_rates_null_denominators(self, api):
        """PRD §3.8: "Either rate is null when its denominator is zero."
        PRD §2.10: "All approval and overturn rates in the system are computed to 4 decimal places using round-half-up. A rate whose denominator count is zero is represented as null rather than zero."

        Design: Corner/calculations/overturn_rates_null_denominators
        """
        ctx = setup_appeal_scenario(begin_review=False)
        assert ctx["appeal"]["status"] == "RECEIVED"
        metrics = validate_success(
            api.get_overturn_analysis(TEST_USERS["compliance_officer_headers"])
        )
        assert metrics["appeals_filed"] == 1
        assert metrics["appeals_decided"] == 0
        assert metrics["appeals_withdrawn"] == 0
        assert metrics["overturn_rate_decided"] is None, (
            "no decided appeals: null, not zero"
        )
        assert metrics["overturn_rate_filed"] == pytest.approx(0.0), "0 / 1"
