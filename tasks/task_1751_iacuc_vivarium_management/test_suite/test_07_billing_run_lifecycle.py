"""Billing run lifecycle: branching void paths, transition ordering,
solvency-gated posting, OCC-guarded finalize, the posted-charge budget
invariant, and immediate read-after-write consistency (PRD §2.7, §3.7).
"""
from test_helpers import (
    BILLING,
    ApiErrorId,
    api_client,
    assert_billing_run,
    get_success_data,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import (
    add_mouse,
    compute_provisional_ok,
    create_billing_run,
    file_census,
    finalize_run,
    list_run_charges,
    setup_approved_with_cage,
    setup_posted_mouse_run,
    setup_provisional_run,
)


class TestVoidBranches:
    def test_void_from_draft_creates_no_charges(self, api):
        """PRD §3.7: "Voiding is available from `DRAFT`, where no charges were
        ever created, and from `PROVISIONAL`, where voiding deletes the
        provisional charge rows; `VOIDED` is terminal in both cases."

        Design: Difficulty/non_linear_state_machine/billing_run_branching_void_paths
        """
        run = create_billing_run("2026-08-01T00:00:00Z", "2026-08-22T00:00:00Z")
        assert run["state"] == "DRAFT"

        voided = validate_success(api_client.void_billing_run(run["id"], BILLING))
        assert_billing_run(voided)
        assert voided["state"] == "VOIDED"
        assert list_run_charges(run["id"]) == [], (
            "a run voided from DRAFT never had charges"
        )

    def test_void_from_provisional_deletes_charges_and_locks_run(self, api):
        """PRD §3.7: "from `PROVISIONAL`, where voiding deletes the
        provisional charge rows; `VOIDED` is terminal in both cases." PRD
        §2.8: "State legality — the target resource is in a state from which
        the requested transition exists (`ERR_INVALID_STATE`, 409)."

        Design: Difficulty/non_linear_state_machine/billing_run_branching_void_paths
        """
        scenario = setup_provisional_run()
        run = scenario["run"]
        assert scenario["charges"], "provisional charges exist before voiding"

        voided = validate_success(api_client.void_billing_run(run["id"], BILLING))
        assert voided["state"] == "VOIDED"
        assert list_run_charges(run["id"]) == [], (
            "voiding from PROVISIONAL deletes the provisional charge rows"
        )

        current = get_success_data(api_client.get_billing_run(run["id"], BILLING))
        resp = api_client.finalize_billing_run(
            run["id"], {"expected_billing_run_version": current["version"]},
            BILLING,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        resp = api_client.post_billing_run(run["id"], BILLING)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestTransitionOrdering:
    def test_post_from_provisional_rejected(self, api):
        """PRD §3.7: "The run's `state` begins as `DRAFT` with `hold_reason`
        null, and its lifecycle runs `DRAFT` → `PROVISIONAL` → `FINALIZED` →
        `POSTED`, with `VOIDED` reachable from either `DRAFT` or
        `PROVISIONAL`." PRD §2.8: "State legality — the target resource is in
        a state from which the requested transition exists
        (`ERR_INVALID_STATE`, 409)."

        Design: Corner/state_machines/billing_post_from_provisional_rejected
        """
        scenario = setup_provisional_run()
        run = scenario["run"]

        resp = api_client.post_billing_run(run["id"], BILLING)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        current = get_success_data(api_client.get_billing_run(run["id"], BILLING))
        assert current["state"] == "PROVISIONAL", (
            "skipping FINALIZED is refused and the run stays PROVISIONAL"
        )


class TestSolvencyGateAtPosting:
    def test_post_rejected_when_charge_exceeds_remaining_budget(self, api):
        """PRD §3.7: "Posting is solvency-gated per charge: every charge's
        `amount_cents` must fit within its grant's `budget_remaining_cents`,
        and the grant's `expires_on` must fall on or after `period_end`; any
        violation is rejected with `ERR_GRANT_INSOLVENT` (HTTP 402)."

        Design: Corner/validations/grant_insolvent_blocks_post
        """
        scenario = setup_provisional_run(budget=1000)
        run = scenario["run"]
        # 21 mouse cage-days at 125 = 2625 cents against a 1000-cent grant.
        assert scenario["charges"][0]["amount_cents"] == 2625
        run = finalize_run(run["id"], run["version"])

        resp = api_client.post_billing_run(run["id"], BILLING)
        validate_error(resp, ApiErrorId.ERR_GRANT_INSOLVENT)

        current = get_success_data(api_client.get_billing_run(run["id"], BILLING))
        assert current["state"] == "FINALIZED", (
            "a rejected posting leaves the run FINALIZED"
        )
        grant = get_success_data(
            api_client.get_grant(scenario["grant"]["id"], BILLING)
        )
        assert grant["budget_remaining_cents"] == 1000, (
            "no debit occurs when posting is rejected"
        )


class TestOccGuardedFinalize:
    def test_finalize_with_stale_version_rejected(self, api):
        """PRD §2.7: "Finalizing a billing run requires the request body to
        carry `expected_billing_run_version`, holding the run `version` the
        client last observed. If the run's current `version` has advanced
        since that observation — because another writer has already finalized
        or voided the run — the finalize is rejected with `ERR_STALE_VERSION`
        (HTTP 412), preventing the client from acting on a run whose contents
        it has not observed."

        Design: Corner/errors/stale_version_on_finalize
        """
        scenario = setup_approved_with_cage()
        cage = scenario["cage"]
        add_mouse(cage["id"], scenario["protocol"]["id"])
        file_census(cage["id"], "2026-08-01T00:00:00Z", 1)
        run = create_billing_run("2026-08-01T00:00:00Z", "2026-08-22T00:00:00Z")
        stale_version = run["version"]
        run = compute_provisional_ok(run["id"])
        assert run["version"] != stale_version, (
            "compute-provisional increments the run version (PRD §2.5)"
        )

        resp = api_client.finalize_billing_run(
            run["id"], {"expected_billing_run_version": stale_version}, BILLING,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, expected_status=412)


class TestPostedChargeBudgetInvariant:
    def test_remaining_equals_total_minus_posted_charges(self, api):
        """PRD §3.7: "Posting moves the run from `FINALIZED` to `POSTED`,
        which is terminal, and debits each grant's `budget_remaining_cents` by
        the sum of that grant's charge amounts." PRD §3.1: "At registration,
        `budget_remaining_cents` is initialized to the full
        `budget_total_cents`, and thereafter it falls only as posted per-diem
        charges debit it".

        Design: Difficulty/compensating_invariant/grant_budget_debit_equals_posted_charges
        """
        scenario = setup_posted_mouse_run(budget=500000)
        grant = get_success_data(
            api_client.get_grant(scenario["grant"]["id"], BILLING)
        )
        assert grant["budget_remaining_cents"] == 497375, (
            f"500000 - 2625 posted = 497375, got "
            f"{grant['budget_remaining_cents']}"
        )

        charges = get_success_data(
            api_client.list_grant_charges(scenario["grant"]["id"], BILLING)
        )
        assert len(charges) == 1
        assert charges[0]["billing_run_id"] == scenario["run"]["id"]
        assert charges[0]["variant"] == "FINAL"
        assert charges[0]["amount_cents"] == 2625
        assert (
            grant["budget_remaining_cents"]
            == grant["budget_total_cents"] - charges[0]["amount_cents"]
        ), "budget_remaining_cents == budget_total_cents - posted charges"

    def test_finalized_then_voided_run_debits_nothing(self, api):
        """PRD §3.7: "Voiding is available from `DRAFT`, where no charges were
        ever created, and from `PROVISIONAL`, where voiding deletes the
        provisional charge rows" — so a later run computed provisional and
        then voided leaves no surviving charge rows and the grant's remaining
        budget reflects only the earlier posted run.

        Design: Difficulty/compensating_invariant/grant_budget_debit_equals_posted_charges
        """
        scenario = setup_posted_mouse_run(budget=500000)
        cage_id = scenario["cage"]["id"]
        file_census(cage_id, "2026-08-22T00:00:00Z", 1)
        run_y = create_billing_run("2026-08-22T00:00:00Z", "2026-09-01T00:00:00Z")
        run_y = compute_provisional_ok(run_y["id"])
        assert list_run_charges(run_y["id"]), "run Y produced provisional rows"

        validate_success(api_client.void_billing_run(run_y["id"], BILLING))
        assert list_run_charges(run_y["id"]) == []

        grant = get_success_data(
            api_client.get_grant(scenario["grant"]["id"], BILLING)
        )
        assert grant["budget_remaining_cents"] == 497375, (
            "the voided run debited nothing"
        )
        charges = get_success_data(
            api_client.list_grant_charges(scenario["grant"]["id"], BILLING)
        )
        assert len(charges) == 1, (
            "only the posted run's charge rows survive for the grant"
        )


class TestImmediateConsistency:
    def test_post_immediately_reflects_grant_debit(self, api):
        """PRD §3.7: "Posting moves the run from `FINALIZED` to `POSTED`,
        which is terminal, and debits each grant's `budget_remaining_cents` by
        the sum of that grant's charge amounts." — the debit is part of the
        posting request, so the very next read already shows the reduced
        budget.

        Design: Corner/consistency_model/post_immediately_reflects_grant_debit
        """
        scenario = setup_provisional_run(budget=500000)
        run = scenario["run"]
        run = finalize_run(run["id"], run["version"])

        posted = validate_success(api_client.post_billing_run(run["id"], BILLING))
        assert posted["state"] == "POSTED"

        grant = get_success_data(
            api_client.get_grant(scenario["grant"]["id"], BILLING)
        )
        assert grant["budget_remaining_cents"] == 497375, (
            "the debit is visible in the immediately following request"
        )
