"""ACH debit block/filter rules: half-open window overlap, suspend/resume
cycles, retire lockdown, and optimistic concurrency."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_ach_rule,
    create_ach_rule,
    create_active_enrollment,
    set_clock,
    validate_error,
    validate_success,
)

BANK_MGR = TEST_USERS["bank_treasury_manager_headers"]
BANK_OPS = TEST_USERS["bank_ops_headers"]


class TestAchRuleWindowOverlap:
    def _setup(self):
        b = create_active_enrollment("WinCo", "POSITIVE_PAY", "PAY",
                                     account_number="990006")
        rule_a = create_ach_rule(b["account"]["id"], b["headers"]["ADMIN"],
                                 rule_type="BLOCK", originator_company_id="ORG1",
                                 sec_code="CCD",
                                 effective_start_date="2026-08-01",
                                 effective_end_date="2026-08-10")
        assert_ach_rule(rule_a)
        return b, rule_a

    def test_adjacent_window_and_different_originator_allowed(self, api):
        """PRD §3.6: "Windows are half-open — the start date is included and the
        end date excluded — so two windows that merely touch, one's end date
        equal to the other's start date, do not overlap and are allowed".
        PRD §3.6: "Window overlap is policed within the triple of `account_id`,
        `originator_company_id`, and `sec_code`".

        Design: Difficulty/resource_temporal_overlap/ach_rule_half_open_window_overlap
        """
        b, _ = self._setup()
        rule_b = create_ach_rule(b["account"]["id"], b["headers"]["ADMIN"],
                                 rule_type="FILTER", originator_company_id="ORG1",
                                 sec_code="CCD", max_amount_cents=5000,
                                 effective_start_date="2026-08-10",
                                 effective_end_date="2026-08-20")
        assert rule_b["status"] == "ACTIVE", "adjacency (end == start) is allowed"
        rule_d = create_ach_rule(b["account"]["id"], b["headers"]["ADMIN"],
                                 rule_type="BLOCK", originator_company_id="ORG2",
                                 sec_code="CCD",
                                 effective_start_date="2026-08-01",
                                 effective_end_date="2026-08-10")
        assert rule_d["status"] == "ACTIVE", (
            "a different originator_company_id is an independent scope")

    def test_overlap_and_open_ended_swallow_rejected(self, api):
        """PRD §3.6: "a create is rejected with `ERR_ACH_RULE_WINDOW_OVERLAP`
        when another rule with the same triple, in `ACTIVE` or `SUSPENDED`
        status, has a window intersecting the new one ... a null end date makes
        the window open-ended."

        Design: Difficulty/resource_temporal_overlap/ach_rule_half_open_window_overlap
        """
        b, _ = self._setup()
        create_ach_rule(b["account"]["id"], b["headers"]["ADMIN"],
                        rule_type="FILTER", originator_company_id="ORG1",
                        sec_code="CCD", max_amount_cents=5000,
                        effective_start_date="2026-08-10",
                        effective_end_date="2026-08-20")
        resp = api.create_ach_rule(
            {"account_id": b["account"]["id"], "rule_type": "BLOCK",
             "originator_company_id": "ORG1", "sec_code": "CCD",
             "effective_start_date": "2026-08-09",
             "effective_end_date": "2026-08-15"}, b["headers"]["ADMIN"])
        validate_error(resp, ApiErrorId.ERR_ACH_RULE_WINDOW_OVERLAP)
        rule_e = create_ach_rule(b["account"]["id"], b["headers"]["ADMIN"],
                                 rule_type="BLOCK", originator_company_id="ORG1",
                                 sec_code="CCD",
                                 effective_start_date="2026-08-20")
        assert rule_e["effective_end_date"] is None
        resp = api.create_ach_rule(
            {"account_id": b["account"]["id"], "rule_type": "BLOCK",
             "originator_company_id": "ORG1", "sec_code": "CCD",
             "effective_start_date": "2026-09-01",
             "effective_end_date": "2026-09-05"}, b["headers"]["ADMIN"])
        validate_error(resp, ApiErrorId.ERR_ACH_RULE_WINDOW_OVERLAP)


class TestAchRuleCycle:
    def _setup(self):
        b = create_active_enrollment("RuleCo", "POSITIVE_PAY", "RETURN",
                                     account_number="960002")
        rule = create_ach_rule(b["account"]["id"], b["headers"]["ADMIN"],
                               rule_type="BLOCK", originator_company_id="ORG1",
                               sec_code="CCD",
                               effective_start_date="2026-08-01",
                               effective_end_date="2026-09-01")
        return b, rule

    def test_suspend_resume_cycle_works_repeatedly(self, api):
        """PRD §3.6: "Suspension and resumption cycle the rule between `ACTIVE`
        and `SUSPENDED`."

        Design: Difficulty/non_linear_state_machine/ach_rule_suspend_resume_cycle_retire_lockdown
        """
        b, rule = self._setup()
        headers = b["headers"]["ADMIN"]
        s1 = validate_success(api.suspend_ach_rule(rule["id"], headers))
        assert s1["status"] == "SUSPENDED"
        s2 = validate_success(api.resume_ach_rule(rule["id"], headers))
        assert s2["status"] == "ACTIVE"
        s3 = validate_success(api.suspend_ach_rule(rule["id"], headers))
        assert s3["status"] == "SUSPENDED"

    def test_retire_is_terminal_and_resume_rejected(self, api):
        """PRD §3.6: "Either state may be retired to the terminal `RETIRED`
        status."
        PRD §3.6: "Suspending requires the rule be `ACTIVE` and resuming
        requires it be `SUSPENDED`; either call against the wrong state is
        `ERR_ACH_RULE_NOT_ACTIVE`."

        Design: Difficulty/non_linear_state_machine/ach_rule_suspend_resume_cycle_retire_lockdown
        """
        b, rule = self._setup()
        headers = b["headers"]["ADMIN"]
        validate_success(api.suspend_ach_rule(rule["id"], headers))
        retired = validate_success(api.retire_ach_rule(rule["id"], headers))
        assert retired["status"] == "RETIRED"
        resp = api.resume_ach_rule(rule["id"], headers)
        validate_error(resp, ApiErrorId.ERR_ACH_RULE_NOT_ACTIVE)

    def test_resume_with_elapsed_window_rejected(self, api):
        """PRD §3.6: "Resumption additionally re-validates that the window has
        not elapsed — the `effective_end_date` must be null or on or after the
        current logical date, otherwise `ERR_ACH_RULE_NOT_ACTIVE`".

        Design: Corner/state_machines/resume_elapsed_window_rejected
        """
        b = create_active_enrollment("ElapCo", "POSITIVE_PAY", "PAY",
                                     account_number="810008")
        rule = create_ach_rule(b["account"]["id"], b["headers"]["ADMIN"],
                               rule_type="BLOCK", originator_company_id="ORG9",
                               sec_code="WEB",
                               effective_start_date="2026-08-01",
                               effective_end_date="2026-08-05")
        validate_success(api.suspend_ach_rule(rule["id"], b["headers"]["ADMIN"]))
        set_clock("2026-08-06T00:00:00Z")
        resp = api.resume_ach_rule(rule["id"], b["headers"]["ADMIN"])
        validate_error(resp, ApiErrorId.ERR_ACH_RULE_NOT_ACTIVE)


class TestAchRuleOcc:
    def test_stale_rule_patch_rejected(self, api):
        """PRD §2.7: "An edit to an ACH debit rule must carry
        `expected_ach_rule_version` matching the rule's current `version`."
        PRD §3.6: "the edit must carry `expected_ach_rule_version` per §2.7,
        rejects a stale version with `ERR_STALE_VERSION` ... and increments the
        rule's `version`."

        Design: Corner/complexity_layers/occ_ach_rule_patch_stale
        """
        b = create_active_enrollment("OccRCo", "POSITIVE_PAY", "PAY",
                                     account_number="860001")
        rule = create_ach_rule(b["account"]["id"], b["headers"]["ADMIN"],
                               rule_type="FILTER", originator_company_id="ORG1",
                               sec_code="CCD", max_amount_cents=5000,
                               effective_start_date="2026-08-01")
        rv1 = rule["version"]
        patched = validate_success(api.patch_ach_rule(
            rule["id"], {"expected_ach_rule_version": rv1,
                         "max_amount_cents": 7000}, b["headers"]["ADMIN"]))
        assert patched["version"] == rv1 + 1
        resp = api.patch_ach_rule(
            rule["id"], {"expected_ach_rule_version": rv1,
                         "max_amount_cents": 9000}, b["headers"]["ADMIN"])
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
