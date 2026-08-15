"""Communications review and lexicon management: auto-tiering boundaries,
manual review workflow, activation supersession, retune rescore cascade, and
lexicon OCC (PRD §2.6, §3.8)."""
from test_helpers import (
    ApiErrorId,
    create_lexicon_policy_payload,
    list_cases,
    make_comm_item,
    make_employee,
    make_lexicon_active,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.test_users import TEST_USERS

CA = TEST_USERS["compliance_admin_headers"]
OPS = TEST_USERS["ops_admin_headers"]
SA = TEST_USERS["surveillance_analyst_headers"]

BOUNDARY_TERMS = [
    {"term": "guarantee", "weight": 60},
    {"term": "insider", "weight": 40},
    {"term": "confident", "weight": 39},
]


class TestCommScoreTiers:
    def _setup(self):
        employee = make_employee(employee_ref="EMP-801", full_name="Tia Lex")
        policy = make_lexicon_active(BOUNDARY_TERMS)
        return employee, policy

    def test_comm_score_100_escalates_99_queues(self, api):
        """PRD §3.8: "a score of 100 or more lands it directly in `ESCALATED`
        and immediately opens a surveillance case on the author; a score of at
        least 40 but below 100 leaves it `QUEUED` for analyst review".

        Design: Difficulty/boundary_precision_check/comm_score_tier_boundaries_100_and_40
        """
        employee, _policy = self._setup()
        item100 = make_comm_item(employee["id"], "We guarantee returns with insider diligence")
        assert item100["score"] == 100
        assert item100["status"] == "ESCALATED", "the >= 100 boundary is inclusive"

        cases, meta = list_cases({"source_comm_item_id": item100["id"]})
        assert meta["total_count"] == 1
        assert cases[0]["opened_from"] == "COMM_REVIEW"
        assert cases[0]["review_status"] == "OPEN"
        assert cases[0]["subject_employee_id"] == employee["id"]

        item99 = make_comm_item(employee["id"], "guarantee confident", channel="CHAT")
        assert item99["score"] == 99
        assert item99["status"] == "QUEUED", "one weight point below auto-escalation"

    def test_comm_score_40_queues_39_clears(self, api):
        """PRD §3.8: "a score of at least 40 but below 100 leaves it `QUEUED`
        for analyst review; and a score below 40 marks it `CLEARED` without
        further work."

        Design: Difficulty/boundary_precision_check/comm_score_tier_boundaries_100_and_40
        """
        employee, _policy = self._setup()
        item40 = make_comm_item(employee["id"], "insider", channel="CHAT")
        assert item40["score"] == 40
        assert item40["status"] == "QUEUED", "the review floor is inclusive"

        item39 = make_comm_item(employee["id"], "confident")
        assert item39["score"] == 39
        assert item39["status"] == "CLEARED", "one point below the floor auto-clears"


class TestCommReviewWorkflow:
    def test_comm_item_manual_review_workflow_and_terminal_lockdown(self, api):
        """PRD §3.8: "a `QUEUED` item moves to `IN_REVIEW`, and from either
        `QUEUED` or `IN_REVIEW` the analyst clears the item (`CLEARED`,
        terminal) or escalates it (`ESCALATED`, terminal)." PRD §2.10:
        "cleared or escalated communication items are all final."

        Design: Corner/state_machines/comm_item_manual_review_workflow_and_terminal_lockdown
        """
        employee = make_employee(employee_ref="EMP-811", full_name="Com Author")
        make_lexicon_active([{"term": "guarantee", "weight": 60}])
        item = make_comm_item(employee["id"], "We guarantee returns")
        assert item["status"] == "QUEUED"

        in_review = validate_success(api.comm_item_transition(item["id"], {"to_status": "IN_REVIEW"}, SA))
        assert in_review["status"] == "IN_REVIEW"
        cleared = validate_success(api.comm_item_transition(item["id"], {"to_status": "CLEARED"}, SA))
        assert cleared["status"] == "CLEARED"

        resp = api.comm_item_transition(item["id"], {"to_status": "ESCALATED"}, SA)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestLexiconActivation:
    def test_lexicon_activation_retires_previous_active_policy(self, api):
        """PRD §3.8: "Activating a `DRAFT` policy moves it to `ACTIVE` and
        retires whatever policy was previously active" and "items whose
        rescore drops — even below 40 — stay `QUEUED`".

        Design: Corner/complexity_layers/lexicon_activation_retires_previous_active_policy
        """
        employee = make_employee(employee_ref="EMP-L1", full_name="Lex Swap")
        l1 = make_lexicon_active([{"term": "guarantee", "weight": 60}], name="L1")
        item = make_comm_item(employee["id"], "guarantee")
        assert item["score"] == 60 and item["status"] == "QUEUED"

        l2_draft = validate_success(api.create_lexicon_policy(
            create_lexicon_policy_payload(name="L2", terms=[{"term": "guarantee", "weight": 10}]), CA),
            expected_status=201)
        l2 = validate_success(api.patch_lexicon_policy(
            l2_draft["id"],
            {"expected_lexicon_policy_version": l2_draft["version"], "to_status": "ACTIVE"},
            CA))
        assert l2["status"] == "ACTIVE"

        l1_after = validate_success(api.get_lexicon_policy(l1["id"], CA))
        assert l1_after["status"] == "RETIRED", "at most one ACTIVE policy fleet-wide"

        items, meta = validate_paginated(api.list_employee_comm_review_items(employee["id"], CA))
        assert meta["total_count"] == 1
        rescored = items[0]
        assert rescored["score"] == 10, "QUEUED items rescore under the newly active policy"
        assert rescored["status"] == "QUEUED", "rescore never auto-down-tiers"
        assert rescored["scored_policy_version"] == l2["version"]


class TestLexiconRetuneCascade:
    def _setup_retune(self):
        """Employee, ACTIVE policy [{guarantee,60},{insider,40}], and a QUEUED
        item scoring 60 (PRD §3.8)."""
        employee = make_employee(employee_ref="EMP-501", full_name="Kim Author")
        policy = make_lexicon_active(
            [{"term": "guarantee", "weight": 60}, {"term": "insider", "weight": 40}], name="L1")
        item = make_comm_item(employee["id"], "We guarantee returns")
        assert item["score"] == 60 and item["status"] == "QUEUED"
        return employee, policy, item

    def test_lexicon_retune_rescores_queued_items(self, api):
        """PRD §3.8: "Link one: every communications item still `QUEUED` is
        rescored against the newly active policy — `score`, `matched_terms`,
        and `scored_policy_version` all refresh."

        Design: Difficulty/transitive_cascade/lexicon_retune_rescore_escalation_cascade
        """
        _employee, policy, item = self._setup_retune()
        patched = validate_success(api.patch_lexicon_policy(
            policy["id"],
            {"expected_lexicon_policy_version": policy["version"],
             "terms": [{"term": "guarantee", "weight": 100}]},
            CA))
        assert patched["version"] == policy["version"] + 1

        items, meta = validate_paginated(
            api.list_employee_comm_review_items(item["author_employee_id"], CA))
        assert meta["total_count"] == 1
        assert items[0]["score"] == 100, "the retune rescores the QUEUED item"
        assert items[0]["scored_policy_version"] == patched["version"]

    def test_lexicon_retune_autoescalates_and_opens_case(self, api):
        """PRD §3.8: "Link two: each rescored item whose new score reaches 100
        or more auto-escalates to `ESCALATED`. Link three: each such
        auto-escalation creates its `COMM_REVIEW` case." PRD §3.1:
        "`open_case_count` is the number of surveillance cases whose
        `subject_employee_id` is this employee and whose `review_status` is
        `OPEN`, `UNDER_INVESTIGATION`, or `REOPENED`".

        Design: Difficulty/transitive_cascade/lexicon_retune_rescore_escalation_cascade
        """
        employee, policy, item = self._setup_retune()
        validate_success(api.patch_lexicon_policy(
            policy["id"],
            {"expected_lexicon_policy_version": policy["version"],
             "terms": [{"term": "guarantee", "weight": 100}]},
            CA))

        items, _meta = validate_paginated(
            api.list_employee_comm_review_items(employee["id"], CA))
        assert items[0]["status"] == "ESCALATED", "rescored to >= 100, the item auto-escalates"

        cases, meta = list_cases({"source_comm_item_id": item["id"]})
        assert meta["total_count"] == 1
        assert cases[0]["opened_from"] == "COMM_REVIEW"
        assert cases[0]["review_status"] == "OPEN"

        refreshed = validate_success(api.get_employee(employee["id"], CA))
        assert refreshed["open_case_count"] == 1


class TestLexiconOcc:
    def test_occ_lexicon_patch_stale_version_rejected(self, api):
        """PRD §2.6: "Patching a lexicon policy — whether retuning its terms,
        changing its status, or both — requires
        `expected_lexicon_policy_version`, matched against the policy's
        current `version`. A successful patch increments the policy's
        `version` by one." and "if the resource's current `version` has
        advanced beyond that observed value, the write is rejected with
        `ERR_STALE_VERSION` (HTTP 412)".

        Design: Corner/complexity_layers/occ_lexicon_patch_stale_version_rejected
        """
        policy = make_lexicon_active([{"term": "guarantee", "weight": 60}])
        observed = policy["version"]  # version after the activation bump

        retuned = validate_success(api.patch_lexicon_policy(
            policy["id"],
            {"expected_lexicon_policy_version": observed,
             "terms": [{"term": "guarantee", "weight": 70}]},
            CA))
        assert retuned["version"] == observed + 1

        stale = api.patch_lexicon_policy(
            policy["id"],
            {"expected_lexicon_policy_version": observed,
             "terms": [{"term": "guarantee", "weight": 80}]},
            CA)
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION)
