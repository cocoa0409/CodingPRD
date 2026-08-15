"""Auto-adjudication lanes at intake and their interaction with stats (PRD §3.2, §3.6)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    accumulate_human_determinations,
    assert_provider,
    basic_um_environment,
    create_guideline_version,
    create_prior_auth_request_payload,
    create_provider,
    get_criteria_set,
    get_provider,
    list_request_events,
    make_active_criteria_set,
    publish_guideline_version,
    reviewer_decide,
    run_gold_card_evaluation,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["um_admin_headers"]
INTAKE = TEST_USERS["intake_specialist_headers"]


def _setup_gold_and_plain_providers():
    """Active IMAGING set whose v1 (not auto-eligible) is superseded by v2
    (auto-eligible); provider A GOLD_CARDED for IMAGING via 10 reviewer
    approvals on v1; provider B with no determinations."""
    cs, gv1 = make_active_criteria_set(auto_approve_eligible=False)
    provider_a = create_provider(name="Gold Provider A")
    accumulate_human_determinations(provider_a["id"], cs["id"], approvals=10)
    evaluation = run_gold_card_evaluation(provider_a["id"], "IMAGING")
    assert evaluation["decision"] == "GRANTED", (
        "Setup: 10/10 = 1.0000 rolling rate with count >= 10 grants the card"
    )
    provider_b = create_provider(name="Plain Provider B")
    gv2 = create_guideline_version(
        cs["id"], version_label="2.0", content="Clinical criteria v2",
        auto_approve_eligible=True, effective_from="2026-01-01T00:00:00Z",
        supersedes_version_id=gv1["id"],
    )
    publish_guideline_version(gv2["id"], get_criteria_set(cs["id"])["version"])
    return cs, provider_a, provider_b


def _intake(api, provider_id, criteria_set_id, member_ref, channel, docs_complete):
    payload = create_prior_auth_request_payload(
        provider_id=provider_id, criteria_set_id=criteria_set_id,
        member_ref=member_ref, intake_channel=channel,
        documentation_complete=docs_complete,
    )
    return validate_success(
        api.create_prior_auth_request(payload, INTAKE), expected_status=201,
    )


def _sole_determination(api, request_id):
    rows = validate_success(
        api.list_determinations(ADMIN, params={"request_id": request_id})
    )
    assert len(rows) == 1
    return rows[0]


class TestGoldLaneVsRulesLane:
    def test_gold_lane_fires_despite_rules_lane_failure(self, api):
        """PRD §3.2: "The **gold lane** fires when the provider's `gold_card_status` is `GOLD_CARDED` and the provider's `gold_card_service_category` equals the criteria set's `service_category`."
        PRD §3.2: "When the gold lane fires, the request becomes `AUTO_APPROVED` and a determination is created with `outcome` `APPROVED`, `reason_code` `GOLD_CARD_AUTO`, `decided_by_role` `SYSTEM_RULE`, `decided_by_user_id` null, `guideline_version_id` copied from the pinned version, `status` `FINAL`, and `issued_at` from the clock; the request's `determined_at` is set to that same instant, and an `AUTO_APPROVAL_FIRED` compliance event is recorded with the request and provider ids."

        Design: Difficulty/combinatorial_formula/auto_approval_gold_lane_vs_rules_lane
        """
        cs, provider_a, _pb = _setup_gold_and_plain_providers()
        # FAX + incomplete documentation fails the rules lane; the gold lane
        # does not inspect channel or documentation, so it still fires.
        t1 = _intake(api, provider_a["id"], cs["id"], "T-01", "FAX", False)
        assert t1["status"] == "AUTO_APPROVED"
        det = _sole_determination(api, t1["id"])
        assert det["reason_code"] == "GOLD_CARD_AUTO"
        assert det["outcome"] == "APPROVED"
        assert det["decided_by_role"] == "SYSTEM_RULE"
        assert det["decided_by_user_id"] is None
        assert det["status"] == "FINAL"
        events = list_request_events(t1["id"], event_type="AUTO_APPROVAL_FIRED")
        assert len(events) == 1
        assert events[0]["provider_id"] == provider_a["id"]

    def test_gold_lane_wins_when_both_lanes_satisfiable(self, api):
        """PRD §3.2: "The gold lane is evaluated first, so a request satisfying both lanes records `reason_code` `GOLD_CARD_AUTO`."

        Design: Difficulty/combinatorial_formula/auto_approval_gold_lane_vs_rules_lane
        """
        cs, provider_a, _pb = _setup_gold_and_plain_providers()
        # PORTAL + complete documentation satisfies the rules lane under v2,
        # and the provider satisfies the gold lane; the pinned order wins.
        t2 = _intake(api, provider_a["id"], cs["id"], "T-02", "PORTAL", True)
        assert t2["status"] == "AUTO_APPROVED"
        det = _sole_determination(api, t2["id"])
        assert det["reason_code"] == "GOLD_CARD_AUTO"
        assert det["decided_by_role"] == "SYSTEM_RULE"

    def test_rules_lane_fires_for_non_gold_provider(self, api):
        """PRD §3.2: "The **rules lane** fires when the pinned guideline version's `auto_approve_eligible` is true, the `intake_channel` is `PORTAL` or `EDI`, and `documentation_complete` is true."
        PRD §3.2: "When only the rules lane fires the same shape results with `reason_code` `AUTO_RULE`."

        Design: Difficulty/combinatorial_formula/auto_approval_gold_lane_vs_rules_lane
        """
        cs, _pa, provider_b = _setup_gold_and_plain_providers()
        t3 = _intake(api, provider_b["id"], cs["id"], "T-03", "PORTAL", True)
        assert t3["status"] == "AUTO_APPROVED"
        det = _sole_determination(api, t3["id"])
        assert det["reason_code"] == "AUTO_RULE"
        assert det["decided_by_role"] == "SYSTEM_RULE"


class TestAutoApprovedRequestIsTerminal:
    def test_reviewer_decision_on_auto_approved_rejected(self, api):
        """PRD §3.3: "Any reviewer decision on a request not in `PENDED_REVIEW` is rejected with `ERR_REQUEST_NOT_PENDING`."
        PRD §3.4: "A request carries at most one non-`VOID` determination, and its `determined_at` mirrors the current non-void determination's `issued_at`."
        PRD §3.2: "The transient `RECEIVED` state exists only inside the intake call and is never observable afterwards."

        Design: Corner/state_machines/reviewer_decision_on_auto_approved_rejected
        """
        provider, cs, _gv = basic_um_environment(auto_approve_eligible=True)
        req = _intake(api, provider["id"], cs["id"], "M-01", "PORTAL", True)
        assert req["status"] == "AUTO_APPROVED"
        resp = api.reviewer_decision(
            req["id"],
            {"decision": "APPROVE", "reason_code": "MEDICAL_NECESSITY_MET"},
            TEST_USERS["clinical_reviewer_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_REQUEST_NOT_PENDING)
        det = _sole_determination(api, req["id"])
        assert det["decided_by_role"] == "SYSTEM_RULE", (
            "no new determination was created by the rejected decision"
        )


class TestAutoLaneExcludedFromProviderStats:
    def test_lifetime_and_rolling_stats_exclude_system_rule_rows(self, api):
        """PRD §3.6: "Provider oversight rests on a single inclusion set: determinations joined through their requests' `provider_id` whose status is `FINAL` or `OVERTURNED` and whose `decided_by_role` is `CLINICAL_REVIEWER` or `MEDICAL_DIRECTOR`. System-rule auto-approvals and voided determinations never count."

        Design: Corner/cross_cutting_layers/lifetime_stats_exclude_auto_lane
        """
        provider, cs, _gv = basic_um_environment(auto_approve_eligible=True)
        a1 = _intake(api, provider["id"], cs["id"], "A-01", "PORTAL", True)
        assert a1["status"] == "AUTO_APPROVED"
        a2 = _intake(api, provider["id"], cs["id"], "A-02", "PORTAL", True)
        assert a2["status"] == "AUTO_APPROVED"
        reviewer_decide(
            _pended(api, provider["id"], cs["id"])["id"],
            "APPROVE", reason_code="MEDICAL_NECESSITY_MET",
        )
        provider = get_provider(provider["id"])
        assert_provider(provider)
        assert provider["lifetime_determination_count"] == 1, (
            "only the human-lane determination counts"
        )
        assert provider["lifetime_approval_count"] == 1
        assert provider["rolling_determination_count"] == 1


def _pended(api, provider_id, criteria_set_id):
    payload = create_prior_auth_request_payload(
        provider_id=provider_id, criteria_set_id=criteria_set_id,
        member_ref="H-01",
    )
    return validate_success(
        api.create_prior_auth_request(payload, INTAKE), expected_status=201,
    )
