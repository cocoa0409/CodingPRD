"""Container cyclic return loop, invalid-transition guards, and the conserved
deposit float.

Difficulty-queue instances for the cyclic reuse loop and the deposit-float
invariant; two Corner/state_machines instances for invalid container transitions.
"""
from test_helpers import fixtures, validate_success, validate_error, ApiErrorId
from test_helpers.test_users import TEST_USERS

CLERK = TEST_USERS["store_clerk_headers"]


def _cycle_container_to_available(api, container_id):
    """IN_USE container -> return (RETURNED) -> inspect CLEAN (AVAILABLE)."""
    validate_success(api.return_container(container_id, CLERK), 200)
    return validate_success(
        api.inspect_container(container_id, {"result": "CLEAN"}, CLERK), 200)


class TestContainerCyclicReuse:
    """A deposit container issued -> IN_USE -> RETURNED -> (inspect CLEAN) cycles
    back to AVAILABLE — a genuine A->...->A loop, not a linear pipeline."""

    def test_container_returns_to_available_after_clean_inspect(self, api):
        """PRD §3.3: "A `CLEAN` result on a `RETURNED` container clears its
        `allergen_hold` to `NONE`, wipes its `measured_tare_g` back to empty,
        releases its `member_id` to unowned, and moves it `RETURNED → AVAILABLE`,
        re-entering the loop."

        Design: Difficulty/non_linear_state_machine/container_cyclic_reuse_loop
        """
        s = fixtures.setup_committed_deposit_order(api)  # IN_STORE, container IN_USE
        final = _cycle_container_to_available(api, s["container"]["id"])
        assert final["status"] == "AVAILABLE"

    def test_clean_inspect_clears_hold_and_owner(self, api):
        """PRD §3.3: "A `CLEAN` result on a `RETURNED` container clears its
        `allergen_hold` to `NONE`, wipes its `measured_tare_g` back to empty,
        releases its `member_id` to unowned, and moves it `RETURNED → AVAILABLE`,
        re-entering the loop."

        Design: Difficulty/non_linear_state_machine/container_cyclic_reuse_loop
        """
        s = fixtures.setup_committed_deposit_order(api)
        final = _cycle_container_to_available(api, s["container"]["id"])
        assert final["allergen_hold"] == "NONE"
        assert final["member_id"] is None, "CLEAN inspect releases member_id to unowned"


def test_issue_already_issued_container_rejected(api):
    """PRD §3.3: "Attempting to issue a container that is not `AVAILABLE` is an
    `ERR_INVALID_CONTAINER_STATE`."

    Design: Corner/state_machines/corner_issue_container_already_issued_rejected
    """
    member = fixtures.create_member(api)
    container = fixtures.create_container(api, container_type="GLASS_500", declared_tare_g=250)
    fixtures.issue_container(api, container_id=container["id"], member_id=member["id"])
    resp = api.issue_container(container["id"], {"member_id": member["id"]}, CLERK)
    validate_error(resp, ApiErrorId.ERR_INVALID_CONTAINER_STATE.value)


def test_inspect_available_container_rejected(api):
    """PRD §3.3: "Inspecting a container that is neither `RETURNED` nor
    `QUARANTINED` is an `ERR_INVALID_CONTAINER_STATE`."

    Design: Corner/state_machines/corner_inspect_available_container_rejected
    """
    container = fixtures.create_container(api, container_type="GLASS_500", declared_tare_g=250)
    resp = api.inspect_container(container["id"], {"result": "CLEAN"}, CLERK)
    validate_error(resp, ApiErrorId.ERR_INVALID_CONTAINER_STATE.value)


class TestDepositFloatConserved:
    """Checkout commits +150 to deposit_liability; the compensating return refunds
    -150 liability and +150 wallet, making the member whole."""

    def test_checkout_commits_deposit_liability(self, api):
        """PRD §3.6: "Each `ISSUED` container referenced by a `FINAL` line on the
        order moves `ISSUED → IN_USE`, and for each such container a
        `DEPOSIT_COMMIT` ledger entry is appended raising `liability_delta_cents`
        by the container's `deposit_cents`."
        PRD §2.6: "`deposit_liability_cents` is the sum of all
        `liability_delta_cents`".

        Design: Difficulty/compensating_invariant/deposit_float_conserved_commit_then_refund
        """
        s = fixtures.setup_committed_deposit_order(api)  # GLASS_500, deposit 150
        member = validate_success(api.get_member(s["member"]["id"], CLERK), 200)
        assert member["deposit_liability_cents"] == 150
        assert member["wallet_balance_cents"] == 0

    def test_return_refunds_and_makes_member_whole(self, api):
        """PRD §3.3: "Either path appends a `DEPOSIT_REFUND` ledger entry for the
        member that adds the deposit to `wallet_delta_cents` and subtracts it from
        `liability_delta_cents`."
        PRD §2.6: "`wallet_balance_cents` is the sum of all `wallet_delta_cents`
        for the member, `deposit_liability_cents` is the sum of all
        `liability_delta_cents`".

        Design: Difficulty/compensating_invariant/deposit_float_conserved_commit_then_refund
        """
        s = fixtures.setup_committed_deposit_order(api)
        returned = validate_success(api.return_container(s["container"]["id"], CLERK), 200)
        assert returned["status"] == "RETURNED"
        member = validate_success(api.get_member(s["member"]["id"], CLERK), 200)
        assert member["wallet_balance_cents"] == 150
        assert member["deposit_liability_cents"] == 0
