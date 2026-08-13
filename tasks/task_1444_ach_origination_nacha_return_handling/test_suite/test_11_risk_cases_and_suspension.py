"""Risk-case resolution branches, originator status cycle, suspension cascade."""
from test_helpers import (
    RISK_OFFICER_USER_ID,
    ApiErrorId,
    create_active_originator,
    define_next_day_window,
    entry_payload,
    get_success_data,
    list_file_entries,
    open_manual_risk_case,
    read_entry,
    read_file,
    read_originator,
    resolve_case_ok,
    set_clock,
    setup_file_with_entries,
    setup_standard_environment,
    validate_error,
)


def test_watch_suspend_reinstate_status_cycle(api, risk_officer_headers):
    """PRD 3.8: "`SUSPEND` applies to an originator in `ACTIVE` or `WATCH` and
    moves it to `SUSPENDED`. `WATCH` applies only to an `ACTIVE` originator and
    moves it to `WATCH`. `REINSTATE` applies to an originator in `SUSPENDED` or
    `WATCH` and moves it one step back toward good standing — `SUSPENDED` to
    `WATCH`, `WATCH` to `ACTIVE`."

    Design: Difficulty/non_linear_state_machine/originator_watch_suspend_reinstate_cycle
    """
    org = create_active_originator("Eta Partners", ["PPD"],
                                   exposure_limit_cents=5_000_000)
    cases = [open_manual_risk_case(org["id"]) for _ in range(4)]

    resolve_case_ok(cases[0]["id"], "WATCH")
    assert read_originator(org["id"])["status"] == "WATCH"

    resolve_case_ok(cases[1]["id"], "SUSPEND")
    assert read_originator(org["id"])["status"] == "SUSPENDED"

    # REINSTATE is sibling-state-dependent: SUSPENDED lands on WATCH.
    resolve_case_ok(cases[2]["id"], "REINSTATE")
    assert read_originator(org["id"])["status"] == "WATCH"

    # ... while WATCH lands on ACTIVE.
    resolve_case_ok(cases[3]["id"], "REINSTATE")
    assert read_originator(org["id"])["status"] == "ACTIVE"


def test_resolutions_persist_action_and_resolving_officer(api,
                                                          risk_officer_headers):
    """PRD 3.8: "Resolution persists the `resolution_action` and the resolving
    officer's `X-User-ID` as `resolved_by_user_id`."

    Design: Difficulty/non_linear_state_machine/originator_watch_suspend_reinstate_cycle
    """
    org = create_active_originator("Eta Partners", ["PPD"],
                                   exposure_limit_cents=5_000_000)
    cases = [open_manual_risk_case(org["id"]) for _ in range(4)]
    for case, action in zip(cases, ("WATCH", "SUSPEND", "REINSTATE", "REINSTATE")):
        resolve_case_ok(case["id"], action)

    resolved = get_success_data(api.list_risk_cases(org["id"],
                                                    risk_officer_headers))
    assert len(resolved) == 4
    assert [c["status"] for c in resolved] == ["RESOLVED"] * 4
    assert [c["resolution_action"] for c in resolved] == [
        "WATCH", "SUSPEND", "REINSTATE", "REINSTATE"]
    for case in resolved:
        assert case["resolved_by_user_id"] == RISK_OFFICER_USER_ID


def _setup_two_originators_with_cases():
    """Originators A and B, each ACTIVE with a one-entry WAREHOUSED file and
    one OPEN manual risk case."""
    define_next_day_window()
    org_a = create_active_originator("Theta A", ["CCD"])
    org_b = create_active_originator("Theta B", ["CCD"])
    set_clock("2026-08-03T10:00:00Z")
    file_a = setup_file_with_entries(org_a,
                                     [entry_payload("DEBIT", 100_000, "ta-1")])
    file_b = setup_file_with_entries(org_b,
                                     [entry_payload("DEBIT", 100_000, "tb-1")])
    case_a = open_manual_risk_case(org_a["id"])
    case_b = open_manual_risk_case(org_b["id"])
    return org_a, file_a, case_a, org_b, file_b, case_b


class TestRiskResolutionBranchDivergence:
    def test_suspend_branch_mutates_and_cascades(self, api):
        """PRD 3.8: "`SUSPEND` applies to an originator in `ACTIVE` or `WATCH`
        and moves it to `SUSPENDED`."
        PRD 2.9: "Suspending or terminating an originator rejects its warehoused
        files and cancels the warehoused entries inside them, then recomputes
        the originator's exposure."

        Design: Difficulty/non_linear_state_machine/risk_case_branching_divergent_side_effects
        """
        org_a, file_a, case_a, _, _, _ = _setup_two_originators_with_cases()

        resolved = resolve_case_ok(case_a["id"], "SUSPEND")
        assert resolved["status"] == "RESOLVED"
        assert resolved["resolution_action"] == "SUSPEND"

        assert read_originator(org_a["id"])["status"] == "SUSPENDED"
        assert read_file(file_a["id"])["status"] == "REJECTED"

    def test_dismiss_branch_leaves_everything_untouched(self, api):
        """PRD 3.8: "`DISMISS` is always allowed and leaves the originator's
        status untouched."

        Design: Difficulty/non_linear_state_machine/risk_case_branching_divergent_side_effects
        """
        _, _, _, org_b, file_b, case_b = _setup_two_originators_with_cases()

        resolved = resolve_case_ok(case_b["id"], "DISMISS")
        assert resolved["status"] == "RESOLVED"
        assert resolved["resolution_action"] == "DISMISS"

        assert read_originator(org_b["id"])["status"] == "ACTIVE"
        assert read_file(file_b["id"])["status"] == "WAREHOUSED"


def _setup_suspended_with_open_case():
    """Originator moved ACTIVE -> SUSPENDED by a first case; a second OPEN
    case is left pending. Returns (org, pending_case)."""
    org = create_active_originator("Rho Inc", ["PPD"],
                                   exposure_limit_cents=5_000_000)
    resolve_case_ok(open_manual_risk_case(org["id"])["id"], "SUSPEND")
    pending = open_manual_risk_case(org["id"])
    return org, pending


class TestResolutionApplicability:
    def test_watch_resolution_requires_active_originator(
            self, api, risk_officer_headers):
        """PRD 3.8: "The case must still be `OPEN` — resolving an
        already-resolved case is rejected with
        `ERR_RISK_CASE_ALREADY_RESOLVED` — and the action must be applicable to
        the originator's current status, otherwise
        `ERR_RESOLUTION_NOT_APPLICABLE`."
        PRD 3.8: "`WATCH` applies only to an `ACTIVE` originator and moves it to
        `WATCH`."

        Design: Difficulty/cross_entity_state_dependency/risk_resolution_requires_originator_status
        """
        org, pending = _setup_suspended_with_open_case()

        res = api.resolve_risk_case(pending["id"], {"action": "WATCH"},
                                    risk_officer_headers)
        validate_error(res, ApiErrorId.ERR_RESOLUTION_NOT_APPLICABLE,
                       expected_status=409)
        assert read_originator(org["id"])["status"] == "SUSPENDED"

    def test_case_stays_open_after_inapplicable_action(self, api,
                                                       risk_officer_headers):
        """PRD 3.8: "`REINSTATE` applies to an originator in `SUSPENDED` or
        `WATCH` and moves it one step back toward good standing — `SUSPENDED` to
        `WATCH`, `WATCH` to `ACTIVE`."

        Design: Difficulty/cross_entity_state_dependency/risk_resolution_requires_originator_status
        """
        org, pending = _setup_suspended_with_open_case()

        res = api.resolve_risk_case(pending["id"], {"action": "WATCH"},
                                    risk_officer_headers)
        validate_error(res, ApiErrorId.ERR_RESOLUTION_NOT_APPLICABLE,
                       expected_status=409)

        cases = get_success_data(api.list_risk_cases(org["id"],
                                                     risk_officer_headers))
        pending_after = next(c for c in cases if c["id"] == pending["id"])
        assert pending_after["status"] == "OPEN", \
            "a rejected resolution must leave the case resolvable"

        # The still-OPEN case accepts an applicable action afterwards.
        resolve_case_ok(pending["id"], "REINSTATE")
        assert read_originator(org["id"])["status"] == "WATCH"


def _setup_suspension_cascade():
    """ACTIVE originator (limit 10000000) with a WAREHOUSED file holding two
    DEBIT entries of 1000000 each, plus one OPEN manual risk case."""
    org = setup_standard_environment("Iota Inc", exposure_limit_cents=10_000_000)
    ach_file = setup_file_with_entries(org, [
        entry_payload("DEBIT", 1_000_000, "i-1"),
        entry_payload("DEBIT", 1_000_000, "i-2"),
    ])
    case = open_manual_risk_case(org["id"])
    return org, ach_file, case


class TestSuspensionCascade:
    def test_suspend_rejects_files_and_cancels_entries(self, api):
        """PRD 2.9: "Suspending or terminating an originator rejects its
        warehoused files and cancels the warehoused entries inside them, then
        recomputes the originator's exposure."

        Design: Difficulty/transitive_cascade/suspension_cascade_file_reject_entry_cancel
        """
        org, ach_file, case = _setup_suspension_cascade()
        entry_ids = [e["id"] for e in list_file_entries(ach_file["id"])]

        resolve_case_ok(case["id"], "SUSPEND")

        assert read_originator(org["id"])["status"] == "SUSPENDED"
        assert read_file(ach_file["id"])["status"] == "REJECTED"
        for entry_id in entry_ids:
            assert read_entry(entry_id)["status"] == "CANCELLED"

    def test_suspend_recomputes_exposure_to_zero(self, api):
        """PRD 2.9: "Suspending or terminating an originator rejects its
        warehoused files and cancels the warehoused entries inside them, then
        recomputes the originator's exposure."
        PRD 3.3: "Outstanding exposure itself is defined over the originator's
        entries in `WAREHOUSED` or `TRANSMITTED` status only — entries that have
        settled, returned, closed, or cancelled are excluded."

        Design: Difficulty/transitive_cascade/suspension_cascade_file_reject_entry_cancel
        """
        org, _, case = _setup_suspension_cascade()
        before = read_originator(org["id"])
        assert before["outstanding_exposure_debit_cents"] == 2_000_000

        resolve_case_ok(case["id"], "SUSPEND")

        after = read_originator(org["id"])
        assert after["outstanding_exposure_debit_cents"] == 0
        assert after["outstanding_exposure_gross_cents"] == 0


def test_double_resolve_rejected(api, risk_officer_headers):
    """PRD 3.8: "The case must still be `OPEN` — resolving an already-resolved
    case is rejected with `ERR_RISK_CASE_ALREADY_RESOLVED` — and the action must
    be applicable to the originator's current status, otherwise
    `ERR_RESOLUTION_NOT_APPLICABLE`."
    PRD 3.8: "`DISMISS` is always allowed and leaves the originator's status
    untouched."

    Design: Corner/state_machines/double_resolve_risk_case_returns_invalid_state
    """
    org = create_active_originator("Lock Co", ["PPD"],
                                   exposure_limit_cents=5_000_000)
    case = open_manual_risk_case(org["id"])
    resolve_case_ok(case["id"], "DISMISS")

    res = api.resolve_risk_case(case["id"], {"action": "WATCH"},
                                risk_officer_headers)
    validate_error(res, ApiErrorId.ERR_RISK_CASE_ALREADY_RESOLVED,
                   expected_status=409)

    # DISMISS left the status untouched, and the second resolve did not fire.
    assert read_originator(org["id"])["status"] == "ACTIVE"
