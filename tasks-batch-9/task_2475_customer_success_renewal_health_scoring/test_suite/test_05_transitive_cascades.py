"""Cascades whose links reach entities the request never mentioned.

Three chains are exercised: releasing one account's coverage, which ends by
opening a different account; a remediation commitment breaching in the nightly
sweep, which ends by moving the account's stored health scores; and the
time-to-value comparison in that same sweep, which ends by blocking every
onboarding milestone of the account it froze.
"""

from test_helpers import (
    ASSIGNMENT_COMMITTED,
    ASSIGNMENT_QUEUED,
    ASSIGNMENT_RELEASED,
    CASE_ACTION_COMMIT,
    CASE_COMMITTED,
    CASE_DISPUTED,
    CODE_DATA_INTEGRATION,
    CODE_FIRST_VALUE,
    CODE_GO_LIVE,
    CODE_KICKOFF,
    COMMITMENT_ACTION_ACCEPT,
    COMMITMENT_BREACHED,
    HEALTH_AMBER,
    HEALTH_GREEN,
    LIFECYCLE_ACTION_WAIVE_TTV_BREACH,
    LIFECYCLE_ONBOARDING,
    MILESTONE_ACTION_WAIVE,
    MILESTONE_BLOCKED,
    MILESTONE_PENDING,
    NEWEST_USAGE_ROW,
    NORTHWIND,
    OPS_ADMIN_HEADERS,
    PLAY_ACTION_ACTIVATE,
    PLAY_ACTIVE,
    PLAY_FAILED,
    PLAY_TYPE_TECHNICAL_REMEDIATION,
    POSTURE_FROZEN,
    POSTURE_OPEN,
    POSTURE_RESTRICTED,
    RISING_USAGE_ROWS,
    RISK_SUPPORT_ESCALATION,
    SEGMENT_MIDMARKET,
    SEVERITY_HIGH,
    TIER_HIGH_TOUCH,
    ApiClient,
    add_sponsor,
    add_usage_signal,
    assert_capacity_conserved,
    assert_credit_ledger,
    assert_field,
    assert_fields,
    assert_health_tier_matches_snapshot,
    assert_null,
    assert_scores,
    assert_sweep_counts,
    assign_coverage,
    create_account,
    create_csm,
    data_of,
    draft_save_play,
    drive_lifecycle,
    factories,
    propose_commitment,
    raise_escalation,
    read_account,
    read_assignment,
    read_case,
    read_commitment,
    read_csm,
    read_milestone,
    read_save_play,
    release_coverage,
    run_sweep,
    segment_account,
    set_clock,
    transition_commitment,
    transition_escalation,
    transition_save_play,
)

# ---------------------------------------------------------------------------
# Local composition helpers
# ---------------------------------------------------------------------------

# A second account on the same manager, commercially identical to Northwind but
# banded MIDMARKET so that its weighted coverage cost differs.
CONTOSO = {
    "name": "Contoso Retail",
    "arr_cents": 30_000_000,
    "segment_band": SEGMENT_MIDMARKET,
    "contract_start_date": "2026-01-01",
    "contract_end_date": "2026-12-31",
}

# The four-step onboarding plan, every step already past due when the clock is
# moved to 2026-05-01.
ONBOARDING_PLAN = (
    (1, CODE_KICKOFF, "2026-01-15"),
    (2, CODE_DATA_INTEGRATION, "2026-02-15"),
    (3, CODE_FIRST_VALUE, "2026-03-01"),
    (4, CODE_GO_LIVE, "2026-03-15"),
)


def _add_milestone_as_ops(
    api: ApiClient, account_id: str, sequence_index: int, code: str, due_date: str
) -> dict:
    """Add one onboarding milestone as CS operations."""
    return data_of(
        api.create_milestone(
            account_id,
            factories.milestone(sequence_index, due_date, code),
            OPS_ADMIN_HEADERS,
        )
    )


def _build_committed_case(api: ApiClient) -> dict:
    """A GREEN, ADOPTING account whose case rests in COMMITTED with one credit due.

    The only milestone is waived so the account leaves onboarding, which keeps
    the segment time-to-value comparison out of the sweep under test; the save
    play is activated while the account is still AMBER, and the CXO economic
    buyer is registered afterwards so the stored scores settle at 77.60 and
    70.95 with a GREEN tier.
    """
    csm = create_csm(
        api, coverage_specialty=TIER_HIGH_TOUCH, capacity_units_total=40
    )
    account = create_account(api, **NORTHWIND)
    for row in RISING_USAGE_ROWS:
        add_usage_signal(
            api,
            account["id"],
            csm["id"],
            row["period_end_date"],
            row["weekly_active_users"],
            row["licensed_seats"],
            row["feature_depth_pct"],
        )
    kickoff = _add_milestone_as_ops(api, account["id"], 1, CODE_KICKOFF, "2026-08-15")
    data_of(
        api.transition_milestone(
            kickoff["id"],
            factories.milestone_transition(MILESTONE_ACTION_WAIVE),
            OPS_ADMIN_HEADERS,
        )
    )
    play = draft_save_play(
        api,
        account["id"],
        csm["id"],
        "2026-08-01",
        "2026-10-31",
        risk_code=RISK_SUPPORT_ESCALATION,
        play_type=PLAY_TYPE_TECHNICAL_REMEDIATION,
    )
    transition_save_play(api, play["id"], csm["id"], PLAY_ACTION_ACTIVATE)
    add_sponsor(api, account["id"], csm["id"])
    case = raise_escalation(api, account["id"], play["id"], SEVERITY_HIGH)
    commitment = propose_commitment(
        api, case["id"], 600_000, "2026-09-15", case["version"]
    )
    transition_commitment(api, commitment["id"], COMMITMENT_ACTION_ACCEPT)
    case = transition_escalation(api, case["id"], CASE_ACTION_COMMIT)
    return {
        "csm_id": csm["id"],
        "account_id": account["id"],
        "play_id": play["id"],
        "case_id": case["id"],
        "commitment_id": commitment["id"],
    }


def _build_saturated_manager(api: ApiClient) -> dict:
    """One 17-unit manager filled by account A, with account B's 12 units waiting."""
    csm = create_csm(
        api, coverage_specialty=TIER_HIGH_TOUCH, capacity_units_total=17
    )
    account_a = create_account(api, **NORTHWIND)
    account_b = create_account(api, **CONTOSO)
    for account in (account_a, account_b):
        add_usage_signal(
            api,
            account["id"],
            csm["id"],
            NEWEST_USAGE_ROW["period_end_date"],
            NEWEST_USAGE_ROW["weekly_active_users"],
            NEWEST_USAGE_ROW["licensed_seats"],
            NEWEST_USAGE_ROW["feature_depth_pct"],
        )
    segmented_a = segment_account(api, account_a["id"])
    assignment_a = assign_coverage(
        api, account_a["id"], segmented_a["version"], csm_id=csm["id"]
    )
    segmented_b = segment_account(api, account_b["id"])
    assignment_b = assign_coverage(
        api, account_b["id"], segmented_b["version"], csm_id=csm["id"]
    )
    return {
        "csm_id": csm["id"],
        "account_a_id": account_a["id"],
        "account_b_id": account_b["id"],
        "assignment_a_id": assignment_a["id"],
        "assignment_b_id": assignment_b["id"],
    }


def _build_stalled_onboarding(api: ApiClient) -> dict:
    """An ENTERPRISE account still onboarding, with all four milestones past due."""
    account = create_account(api, **NORTHWIND)
    milestones = [
        _add_milestone_as_ops(api, account["id"], index, code, due_date)
        for index, code, due_date in ONBOARDING_PLAN
    ]
    return {
        "account_id": account["id"],
        "milestone_ids": [milestone["id"] for milestone in milestones],
    }


class TestReleaseCascade:
    """Releasing one account's coverage promotes another account's queued row."""

    def test_release_frees_the_row_and_the_managers_committed_units(
        self, api: ApiClient, clock: str
    ) -> None:
        """The first two links act on the released row and its manager.

        PRD §3.4: "A successful release runs a four-link cascade inside the one request."
        PRD §3.4: "First, the assignment moves `COMMITTED → RELEASED`, its `released_at` is stamped with the logical clock and its `release_reason` recorded."
        PRD §3.4: "Second, because the assignment left `COMMITTED`, its manager's `capacity_units_committed` falls by that assignment's `load_units` and `capacity_units_available` is recomputed."
        PRD §2.10: "A CSM's `capacity_units_committed` must always equal the sum of `load_units` over that CSM's coverage assignments in state `COMMITTED`; assignments in `QUEUED`, `RELEASED` or `PREEMPTED` contribute nothing."

        Design: Difficulty/transitive_cascade/release_cascade_promotes_a_queued_assignment_four_links_deep
        """
        state = _build_saturated_manager(api)

        released = release_coverage(
            api,
            state["assignment_a_id"],
            release_reason="Account moved to a named pod",
        )

        assert_fields(
            released,
            {
                "state": ASSIGNMENT_RELEASED,
                "release_reason": "Account moved to a named pod",
                "load_units": 17,
            },
        )
        assert released["released_at"] is not None, "released_at is not stamped"
        manager = read_csm(api, state["csm_id"])
        assert_fields(
            manager, {"capacity_units_committed": 12, "capacity_units_available": 5}
        )
        assert_capacity_conserved(manager)

    def test_the_freed_capacity_promotes_the_queued_row_and_opens_its_account(
        self, api: ApiClient, clock: str
    ) -> None:
        """The last two links reach an account the release never named.

        PRD §3.4: "Third, because that manager's `capacity_units_available` has risen, the server promotes at most one waiting assignment: among that same manager's `QUEUED` assignments whose `load_units` are less than or equal to the newly available capacity, the one with the lowest `created_at` moves `QUEUED → COMMITTED`, taking the same admission side effects (committed units up, `committed_at` stamped)."
        PRD §3.4: "Fourth, because that promoted assignment entered `COMMITTED`, **its** account — which is generally a different account from the one being released — has its `assigned_csm_id` set to the manager and its `coverage_posture` re-derived, which can move that second account from `RESTRICTED` to `OPEN` in a request that never mentioned it."

        Design: Difficulty/transitive_cascade/release_cascade_promotes_a_queued_assignment_four_links_deep
        """
        state = _build_saturated_manager(api)
        waiting = read_assignment(api, state["assignment_b_id"])
        assert_field(waiting, "state", ASSIGNMENT_QUEUED)

        release_coverage(api, state["assignment_a_id"])

        promoted = read_assignment(api, state["assignment_b_id"])
        assert_fields(promoted, {"state": ASSIGNMENT_COMMITTED, "load_units": 12})
        assert promoted["committed_at"] is not None, "committed_at is not stamped"
        account_b = read_account(api, state["account_b_id"])
        assert_fields(
            account_b,
            {
                "assigned_csm_id": state["csm_id"],
                "coverage_posture": POSTURE_OPEN,
            },
        )

    def test_the_released_account_loses_its_manager_and_reverts_to_restricted(
        self, api: ApiClient, clock: str
    ) -> None:
        """The release closes by re-deriving the released account's own condition.

        PRD §3.4: "Finally the released assignment's own account has `assigned_csm_id` cleared to null and its `coverage_posture` re-derived, yielding `RESTRICTED` because no `COMMITTED` assignment remains."
        PRD §2.8: "Otherwise, if `open_save_play_count` is greater than zero, **or** at least one escalation case of the account is in state `OPEN`, `COMMITTED` or `DISPUTED`, **or** the account has no coverage assignment in state `COMMITTED`, the posture is `RESTRICTED`."

        Design: Difficulty/transitive_cascade/release_cascade_promotes_a_queued_assignment_four_links_deep
        """
        state = _build_saturated_manager(api)
        before = read_account(api, state["account_a_id"])
        assert_fields(
            before,
            {
                "assigned_csm_id": state["csm_id"],
                "coverage_posture": POSTURE_OPEN,
            },
        )

        release_coverage(api, state["assignment_a_id"])

        account_a = read_account(api, state["account_a_id"])
        assert_null(account_a, "assigned_csm_id")
        assert_field(account_a, "coverage_posture", POSTURE_RESTRICTED)
        assert_capacity_conserved(read_csm(api, state["csm_id"]))


class TestCommitmentBreachCascade:
    """One overdue credit reverses the ledger, the case, the play and the health."""

    def test_breach_reverses_the_credit_and_disputes_the_case(
        self, api: ApiClient, clock: str
    ) -> None:
        """Links one and two act on the commitment and its case.

        PRD §3.5: "During the nightly sweep, any commitment in state `ACCEPTED` whose `due_date` is strictly earlier than the logical clock date, and whose case is in state `COMMITTED`, breaches — and the breach fans out through four links inside that one sweep."
        PRD §3.5: "First, the commitment moves `ACCEPTED → BREACHED` and the account's `remediation_credit_outstanding_cents` falls by that commitment's `credit_cents`, reversing exactly what acceptance added."
        PRD §3.5: "Second, because the commitment breached, the owning case moves `COMMITTED → DISPUTED` and its `remediation_round` is incremented by 1 — which is why a fresh commitment must be proposed and accepted before the case can be committed again."
        PRD §3.9: "The sweep returns four counters describing what it did: `milestones_marked_overdue` counts the milestones it moved from `PENDING` to `OVERDUE`; `commitments_breached` counts the commitments it moved from `ACCEPTED` to `BREACHED`; `opportunities_expired` counts the opportunities it moved from `IDENTIFIED` to `EXPIRED`; and `accounts_repostured` counts the accounts whose `coverage_posture` value differs after the sweep from the value it held before, whether the change came from the flag evaluation or from a breach cascade."

        Design: Difficulty/transitive_cascade/commitment_breach_cascade_fails_the_save_play_and_debits_health
        """
        state = _build_committed_case(api)
        before = read_account(api, state["account_id"])
        assert_credit_ledger(before, 600_000, 0)
        assert_fields(
            read_case(api, state["case_id"]),
            {"state": CASE_COMMITTED, "remediation_round": 1},
        )

        set_clock(api, "2026-09-20T00:00:00Z")
        sweep = run_sweep(api)

        assert_sweep_counts(sweep, commitments_breached=1)
        breached = read_commitment(api, state["case_id"], state["commitment_id"])
        assert_field(breached, "state", COMMITMENT_BREACHED)
        after = read_account(api, state["account_id"])
        assert_credit_ledger(after, 0, 0)
        case = read_case(api, state["case_id"])
        assert_fields(case, {"state": CASE_DISPUTED, "remediation_round": 2})

    def test_the_disputed_case_fails_the_referenced_save_play(
        self, api: ApiClient, clock: str
    ) -> None:
        """Link three reaches the play named by the case.

        PRD §3.5: "Third, because the case entered `DISPUTED`, the referenced save play is driven from `ACTIVE` to `FAILED`."
        PRD §3.5: "Fourth, because the play entered `FAILED`, the account's `open_save_play_count` falls by 1, the save-failure penalty of 5.00 is subtracted from both stored health scores with a floor of 0.00, `health_tier` is re-derived and `coverage_posture` recomputed."

        Design: Difficulty/transitive_cascade/commitment_breach_cascade_fails_the_save_play_and_debits_health
        """
        state = _build_committed_case(api)
        assert_field(read_save_play(api, state["play_id"]), "state", PLAY_ACTIVE)
        assert_field(read_account(api, state["account_id"]), "open_save_play_count", 1)

        set_clock(api, "2026-09-20T00:00:00Z")
        run_sweep(api)

        assert_field(read_save_play(api, state["play_id"]), "state", PLAY_FAILED)
        assert_field(read_account(api, state["account_id"]), "open_save_play_count", 0)

    def test_the_failed_play_debits_both_stored_health_scores(
        self, api: ApiClient, clock: str
    ) -> None:
        """Link four moves the account's own figures, four links from the due date.

        PRD §3.5: "Fourth, because the play entered `FAILED`, the account's `open_save_play_count` falls by 1, the save-failure penalty of 5.00 is subtracted from both stored health scores with a floor of 0.00, `health_tier` is re-derived and `coverage_posture` recomputed."
        PRD §3.2: "`health_tier` is derived from `snapshot_health_score` **only**: the tier is `RED` when `snapshot_health_score` is below 50.00, `AMBER` when it is at least 50.00 and below 75.00, and `GREEN` when it is at least 75.00."
        PRD §2.8: "Otherwise, if `open_save_play_count` is greater than zero, **or** at least one escalation case of the account is in state `OPEN`, `COMMITTED` or `DISPUTED`, **or** the account has no coverage assignment in state `COMMITTED`, the posture is `RESTRICTED`."

        Design: Difficulty/transitive_cascade/commitment_breach_cascade_fails_the_save_play_and_debits_health
        """
        state = _build_committed_case(api)
        before = read_account(api, state["account_id"])
        assert_scores(
            before,
            {"snapshot_health_score": 77.60, "trended_health_score": 70.95},
        )
        assert_field(before, "health_tier", HEALTH_GREEN)

        set_clock(api, "2026-09-20T00:00:00Z")
        run_sweep(api)

        after = read_account(api, state["account_id"])
        assert_scores(
            after,
            {"snapshot_health_score": 72.60, "trended_health_score": 65.95},
        )
        assert_field(after, "health_tier", HEALTH_AMBER)
        assert_health_tier_matches_snapshot(after)
        assert_field(after, "coverage_posture", POSTURE_RESTRICTED)


class TestTimeToValueBreachCascade:
    """The last sweep step freezes a stalled onboarding and halts its plan."""

    def test_the_sweep_marks_the_plan_overdue_then_raises_the_breach_flag(
        self, api: ApiClient, clock: str
    ) -> None:
        """The overdue pass runs first and the segment comparison last.

        PRD §3.9: "First, every onboarding milestone in state `PENDING` whose `due_date` is strictly earlier than the logical clock date moves to `OVERDUE`; nothing on the milestone changes but its state, `updated_at` and `version`."
        PRD §3.1: "During the nightly sweep the server computes the elapsed number of whole days from `contract_start_date` to the logical clock date and compares it against the segment's target: 90 days for `ENTERPRISE`, 60 days for `MIDMARKET`, 30 days for `SMB`."
        PRD §3.1: "If the account is still in `lifecycle_state` `ONBOARDING` and the elapsed figure is strictly greater than its target, `ttv_breach_flag` is raised to true; if the account is no longer `ONBOARDING`, the flag is set to false."
        PRD §2.8: "If the account's `lifecycle_state` is `CHURNED`, `WIN_BACK_TARGETED` or `ARCHIVED`, **or** the `lifecycle_state` is `ONBOARDING` and `ttv_breach_flag` is true, the posture is `FROZEN`."

        Design: Difficulty/transitive_cascade/ttv_breach_sweep_freezes_posture_and_blocks_onboarding_milestones
        """
        state = _build_stalled_onboarding(api)
        before = read_account(api, state["account_id"])
        assert_fields(
            before,
            {
                "lifecycle_state": LIFECYCLE_ONBOARDING,
                "ttv_breach_flag": False,
                "coverage_posture": POSTURE_RESTRICTED,
            },
        )

        set_clock(api, "2026-05-01T00:00:00Z")
        sweep = run_sweep(api)

        assert_sweep_counts(
            sweep, milestones_marked_overdue=4, accounts_repostured=1
        )
        after = read_account(api, state["account_id"])
        assert_fields(
            after,
            {
                "lifecycle_state": LIFECYCLE_ONBOARDING,
                "ttv_breach_flag": True,
                "coverage_posture": POSTURE_FROZEN,
            },
        )

    def test_the_frozen_posture_blocks_every_milestone_of_the_plan(
        self, api: ApiClient, clock: str
    ) -> None:
        """The propagation step reaches rows the flag evaluation never touched.

        PRD §3.1: "A raised flag drives `coverage_posture` to `FROZEN` through the first derivation clause, which in turn drives every `PENDING` or `OVERDUE` milestone of that account to `BLOCKED` — onboarding work is deliberately halted until CS operations intervenes."
        PRD §2.8: "If the posture has just become `FROZEN` while the account's `lifecycle_state` is `ONBOARDING`, every onboarding milestone of that account in state `PENDING` or `OVERDUE` moves to `BLOCKED`."

        Design: Difficulty/transitive_cascade/ttv_breach_sweep_freezes_posture_and_blocks_onboarding_milestones
        """
        state = _build_stalled_onboarding(api)

        set_clock(api, "2026-05-01T00:00:00Z")
        run_sweep(api)

        for milestone_id in state["milestone_ids"]:
            milestone = read_milestone(api, state["account_id"], milestone_id)
            assert_field(milestone, "state", MILESTONE_BLOCKED)

    def test_waiving_the_breach_unwinds_the_freeze_and_the_block(
        self, api: ApiClient, clock: str
    ) -> None:
        """Clearing the flag by hand runs the same propagation in reverse.

        PRD §3.1: "It leaves the account in `ONBOARDING`, sets `ttv_breach_flag` to false, and re-derives the posture; because the posture then leaves `FROZEN`, every `BLOCKED` milestone of that account returns to `PENDING`."
        PRD §2.8: "If the posture has just left `FROZEN`, every onboarding milestone of that account in state `BLOCKED` moves back to `PENDING`."

        Design: Difficulty/transitive_cascade/ttv_breach_sweep_freezes_posture_and_blocks_onboarding_milestones
        """
        state = _build_stalled_onboarding(api)
        set_clock(api, "2026-05-01T00:00:00Z")
        run_sweep(api)

        waived = drive_lifecycle(
            api, state["account_id"], LIFECYCLE_ACTION_WAIVE_TTV_BREACH
        )

        assert_fields(
            waived,
            {
                "lifecycle_state": LIFECYCLE_ONBOARDING,
                "ttv_breach_flag": False,
                "coverage_posture": POSTURE_RESTRICTED,
            },
        )
        for milestone_id in state["milestone_ids"]:
            milestone = read_milestone(api, state["account_id"], milestone_id)
            assert_field(milestone, "state", MILESTONE_PENDING)
