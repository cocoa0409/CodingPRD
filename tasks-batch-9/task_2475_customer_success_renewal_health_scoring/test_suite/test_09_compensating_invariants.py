"""Round trips over the two conserved counters of PRD §2.10.

Each counter is driven out and back again: a coverage assignment is committed,
released and re-committed, and a remediation credit is proposed, accepted and
then withdrawn. Both the intermediate leg and the closed loop are checked, so a
counter that drifts by even one unit in either direction is caught.
"""

from typing import Any, Dict, List

from test_helpers import (
    ASSIGNMENT_COMMITTED,
    ASSIGNMENT_RELEASED,
    CASE_ACTION_WITHDRAW,
    CASE_OPEN,
    CASE_WITHDRAWN,
    COMMITMENT_ACCEPTED,
    COMMITMENT_ACTION_ACCEPT,
    COMMITMENT_PROPOSED,
    COMMITMENT_WITHDRAWN,
    OPS_ADMIN_HEADERS,
    POSTURE_OPEN,
    POSTURE_RESTRICTED,
    ApiClient,
    assert_capacity_conserved,
    assert_credit_ledger,
    assert_field,
    assert_fields,
    assert_null,
    assign_coverage,
    build_escalated_account,
    build_open_account,
    list_rows,
    propose_commitment,
    read_account,
    read_case,
    read_commitment,
    read_csm,
    release_coverage,
    transition_commitment,
    transition_escalation,
)

# The escalated account carries 30,000,000 cents of revenue, so PRD §2.9 rule 29
# allows each commitment up to 3,000,000 cents of credit.
FIRST_CREDIT_CENTS = 600_000
SECOND_CREDIT_CENTS = 250_000
BOTH_CREDITS_CENTS = FIRST_CREDIT_CENTS + SECOND_CREDIT_CENTS


def _committed_assignments_of(api: ApiClient, csm_id: str) -> List[Dict[str, Any]]:
    """Every `COMMITTED` coverage assignment held by one manager."""
    return list_rows(
        api.list_coverage_assignments(
            OPS_ADMIN_HEADERS,
            {"csm_id": csm_id, "state": ASSIGNMENT_COMMITTED, "limit": 100},
        )
    )


class TestCsmCapacityRoundTrip:
    """Releasing and re-committing coverage restores the capacity ledger exactly."""

    def test_release_hands_every_committed_unit_back_to_the_manager(
        self, api: ApiClient
    ):
        """The intermediate leg: after release the manager holds nothing at all.

        PRD §3.4: "First, the assignment moves `COMMITTED → RELEASED`, its `released_at` is stamped with the logical clock and its `release_reason` recorded."
        PRD §3.4: "Second, because the assignment left `COMMITTED`, its manager's `capacity_units_committed` falls by that assignment's `load_units` and `capacity_units_available` is recomputed."
        PRD §3.4: "Finally the released assignment's own account has `assigned_csm_id` cleared to null and its `coverage_posture` re-derived, yielding `RESTRICTED` because no `COMMITTED` assignment remains."
        PRD §2.10: "A CSM's `capacity_units_committed` must always equal the sum of `load_units` over that CSM's coverage assignments in state `COMMITTED`; assignments in `QUEUED`, `RELEASED` or `PREEMPTED` contribute nothing."

        Design: Difficulty/compensating_invariant/csm_capacity_units_return_to_the_same_value_after_release_and_recommit
        """
        state = build_open_account(api)
        csm_id = state["csm_id"]
        first_assignment_id = state["assignment_id"]

        assert_field(state["assignment"], "load_units", 17)
        assert_fields(
            read_csm(api, csm_id),
            {"capacity_units_committed": 17, "capacity_units_available": 23},
        )

        released = release_coverage(api, first_assignment_id)
        assert_field(released, "state", ASSIGNMENT_RELEASED)

        csm = read_csm(api, csm_id)
        assert_fields(
            csm,
            {
                "capacity_units_total": 40,
                "capacity_units_committed": 0,
                "capacity_units_available": 40,
            },
        )
        assert_capacity_conserved(csm)
        assert not _committed_assignments_of(api, csm_id), (
            "no assignment should remain COMMITTED after the release"
        )

        account = read_account(api, state["account_id"])
        assert_null(account, "assigned_csm_id")
        assert_field(account, "coverage_posture", POSTURE_RESTRICTED)

    def test_recommitting_the_same_load_returns_the_counters_to_their_prior_value(
        self, api: ApiClient
    ):
        """The closed loop: commit, release, re-commit lands back on 17 and 23.

        PRD §3.4: "On admission the manager's `capacity_units_committed` rises by the assignment's `load_units`, `capacity_units_available` is recomputed, the assignment's `committed_at` is stamped with the logical clock, the account's `assigned_csm_id` is set to the assignment's `csm_id`, and `coverage_posture` is re-derived — which is how an otherwise clean account finally reaches `OPEN`."
        PRD §3.4: "Second, because the assignment left `COMMITTED`, its manager's `capacity_units_committed` falls by that assignment's `load_units` and `capacity_units_available` is recomputed."
        PRD §2.10: "A CSM's `capacity_units_committed` must always equal the sum of `load_units` over that CSM's coverage assignments in state `COMMITTED`; assignments in `QUEUED`, `RELEASED` or `PREEMPTED` contribute nothing."
        PRD §2.10: "`capacity_units_available` must always equal `capacity_units_total` minus `capacity_units_committed`."

        Design: Difficulty/compensating_invariant/csm_capacity_units_return_to_the_same_value_after_release_and_recommit
        """
        state = build_open_account(api)
        csm_id = state["csm_id"]
        account_id = state["account_id"]
        first_assignment_id = state["assignment_id"]

        before = read_csm(api, csm_id)
        assert_fields(
            before,
            {"capacity_units_committed": 17, "capacity_units_available": 23},
        )

        release_coverage(api, first_assignment_id)

        account = read_account(api, account_id)
        second = assign_coverage(api, account_id, account["version"], csm_id=csm_id)

        assert_fields(
            second, {"state": ASSIGNMENT_COMMITTED, "load_units": 17, "csm_id": csm_id}
        )
        assert second["id"] != first_assignment_id

        after = read_csm(api, csm_id)
        assert_fields(
            after,
            {
                "capacity_units_total": before["capacity_units_total"],
                "capacity_units_committed": before["capacity_units_committed"],
                "capacity_units_available": before["capacity_units_available"],
            },
        )
        assert_capacity_conserved(after)

        # The restored figure is the sum over the manager's COMMITTED rows only:
        # the released row must contribute nothing to it.
        committed = _committed_assignments_of(api, csm_id)
        assert len(committed) == 1, (
            f"expected exactly one COMMITTED assignment, got {len(committed)}"
        )
        assert committed[0]["id"] == second["id"]
        assert sum(row["load_units"] for row in committed) == 17

        assert_field(
            list_rows(
                api.list_coverage_assignments(
                    OPS_ADMIN_HEADERS,
                    {"account_id": account_id, "state": ASSIGNMENT_RELEASED},
                )
            )[0],
            "id",
            first_assignment_id,
        )

        account = read_account(api, account_id)
        assert_fields(
            account,
            {"assigned_csm_id": csm_id, "coverage_posture": POSTURE_OPEN},
        )


class TestRemediationCreditRoundTrip:
    """Withdrawing a case reverses exactly the credit its acceptances added."""

    def test_acceptance_is_what_moves_the_outstanding_counter(self, api: ApiClient):
        """The intermediate leg: proposing moves nothing, accepting moves the credit.

        PRD §3.5: "The commitment is created in state `PROPOSED` with its `round_index` snapshotted from the case's current `remediation_round`, and it moves no credit counter yet."
        PRD §3.5: "Acceptance stamps `accepted_by_user_id` with the acting `X-User-ID` and increments the account's `remediation_credit_outstanding_cents` by the commitment's `credit_cents`."
        PRD §2.10: "`remediation_credit_outstanding_cents` must always equal the sum of `credit_cents` over that account's remediation commitments whose own state is `ACCEPTED` or `DELIVERED` and whose owning escalation case is in state `OPEN`, `COMMITTED` or `DISPUTED`."

        Design: Difficulty/compensating_invariant/remediation_credit_outstanding_returns_to_zero_after_case_withdrawal
        """
        state = build_escalated_account(api)
        account_id = state["account_id"]
        case_id = state["case_id"]

        assert_field(state["case"], "state", CASE_OPEN)
        assert_credit_ledger(read_account(api, account_id), 0, 0)

        first = propose_commitment(
            api,
            case_id,
            FIRST_CREDIT_CENTS,
            "2026-09-30",
            read_case(api, case_id)["version"],
        )
        assert_field(first, "state", COMMITMENT_PROPOSED)
        assert_credit_ledger(read_account(api, account_id), 0, 0)

        first = transition_commitment(api, first["id"], COMMITMENT_ACTION_ACCEPT)
        assert_field(first, "state", COMMITMENT_ACCEPTED)
        assert_credit_ledger(read_account(api, account_id), FIRST_CREDIT_CENTS, 0)

        second = propose_commitment(
            api,
            case_id,
            SECOND_CREDIT_CENTS,
            "2026-10-15",
            read_case(api, case_id)["version"],
        )
        assert_field(second, "state", COMMITMENT_PROPOSED)
        assert_credit_ledger(read_account(api, account_id), FIRST_CREDIT_CENTS, 0)

        second = transition_commitment(api, second["id"], COMMITMENT_ACTION_ACCEPT)
        assert_field(second, "state", COMMITMENT_ACCEPTED)
        assert_credit_ledger(read_account(api, account_id), BOTH_CREDITS_CENTS, 0)

    def test_withdrawal_returns_the_outstanding_counter_to_zero(self, api: ApiClient):
        """The closed loop: propose, accept, withdraw leaves no residue behind.

        PRD §3.5: "It sets every commitment of the case whose state is `PROPOSED` or `ACCEPTED` to `WITHDRAWN`, decrements the account's `remediation_credit_outstanding_cents` by the sum of `credit_cents` over exactly those commitments that left `ACCEPTED` — proposed commitments were never counted and contribute nothing to the reversal — and re-derives `coverage_posture`."
        PRD §3.5: "On the alternative branch where the case is withdrawn instead, outstanding returns to 0, settled stays at 0, and no residue is left behind — a propose, accept and withdraw round trip returns the ledger to exactly its prior value."
        PRD §2.10: "The practical consequence is that withdrawing a case or breaching a commitment must reverse exactly the amount that was added when the commitment was accepted: a propose-accept-withdraw round trip returns `remediation_credit_outstanding_cents` to precisely the value it held before, and settlement moves value from the outstanding counter into the settled counter rather than double-counting it."
        PRD §2.10: "`remediation_credit_settled_cents` must always equal the sum of `final_credit_cents` over that account's escalation cases in state `RESOLVED`."

        Design: Difficulty/compensating_invariant/remediation_credit_outstanding_returns_to_zero_after_case_withdrawal
        """
        state = build_escalated_account(api)
        account_id = state["account_id"]
        case_id = state["case_id"]

        assert_credit_ledger(read_account(api, account_id), 0, 0)

        commitment_ids = []
        for credit_cents, due_date in (
            (FIRST_CREDIT_CENTS, "2026-09-30"),
            (SECOND_CREDIT_CENTS, "2026-10-15"),
        ):
            commitment = propose_commitment(
                api,
                case_id,
                credit_cents,
                due_date,
                read_case(api, case_id)["version"],
            )
            transition_commitment(api, commitment["id"], COMMITMENT_ACTION_ACCEPT)
            commitment_ids.append(commitment["id"])

        assert_credit_ledger(read_account(api, account_id), BOTH_CREDITS_CENTS, 0)

        case = transition_escalation(api, case_id, CASE_ACTION_WITHDRAW)
        assert_field(case, "state", CASE_WITHDRAWN)
        assert_null(case, "final_credit_cents")

        for commitment_id in commitment_ids:
            assert_field(
                read_commitment(api, case_id, commitment_id),
                "state",
                COMMITMENT_WITHDRAWN,
            )

        # Both counters are back where registration left them, and the active save
        # play still holds the posture at RESTRICTED.
        account = read_account(api, account_id)
        assert_credit_ledger(account, 0, 0)
        assert_field(account, "coverage_posture", POSTURE_RESTRICTED)
