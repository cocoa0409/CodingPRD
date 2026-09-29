"""Conservation identities holding across a compensating operation."""

from test_helpers import (
    assert_fields,
    assert_pact_conservation,
    assert_program_conservation,
    allocate,
    commit_aid,
    create_asset,
    create_harbor,
    create_pact,
    create_ridge,
    fulfill_commitment,
    read_capital_program,
    read_commitment,
    read_pact,
    read_project,
    release_commitment,
    two_certified_retrofit_projects,
    withdraw_project,
)


class TestProgramLedgerReturnsToItsExactPriorState:
    """committed plus available equals authorized at every observation point."""

    def test_two_allocations_keep_the_identity_and_leave_the_posture_open(self):
        """Points 0 to 2: the ledger is recomputed from scratch and never drifts.

        PRD 3.7: "Over that set, `committed_cents` is the sum of `allocated_cents`,
        and `available_cents` is `authorized_cents` minus `committed_cents`."  The
        posture stays healthy because PRD 3.7 draws the line at a tenth: "otherwise
        `OVERSUBSCRIBED` when `available_cents` is greater than zero and the remaining
        headroom — ten thousand times `available_cents` divided by `authorized_cents`,
        floored to whole basis points — is strictly below 1000 basis points".  Ten
        million against sixty million is 1666 basis points of headroom.

        Design: Difficulty/compensating_invariant/program_authorized_cents_conserved_across_allocate_and_withdraw
        """
        context = two_certified_retrofit_projects(
            authorized_cents=60000000, equity_target_bps=4000
        )
        program_id = context["program"]["id"]

        opening = read_capital_program(program_id)
        assert_fields(
            opening,
            {
                "committed_cents": 0,
                "available_cents": 60000000,
                "equity_achieved_bps": 0,
                "funding_posture": "OPEN",
            },
            "the freshly opened capital program",
        )
        assert_program_conservation(opening)

        allocate(program_id, context["project_a"]["id"], 20000000)
        after_first = read_capital_program(program_id)
        assert_fields(
            after_first,
            {"committed_cents": 20000000, "available_cents": 40000000},
            "the program after the first allocation",
        )
        assert_program_conservation(after_first)

        allocate(program_id, context["project_b"]["id"], 30000000)
        after_second = read_capital_program(program_id)
        assert_fields(
            after_second,
            {
                "committed_cents": 50000000,
                "available_cents": 10000000,
                "funding_posture": "OPEN",
            },
            "the program after the second allocation",
        )
        assert_program_conservation(after_second)

    def test_withdrawal_restores_the_exact_pre_allocation_pair(self):
        """Point 3: the compensating act reproduces the point-1 numbers exactly.

        PRD 3.7: "`committed_cents` decreases by exactly the released amount and
        `available_cents` increases by exactly the same amount, so `committed_cents`
        plus `available_cents` still equals `authorized_cents`."  The equity side is
        recomputed too: "`equity_achieved_bps` is 0 when `committed_cents` is 0, and
        otherwise ten thousand times `equity_committed_cents` divided by
        `committed_cents`, floored."

        Design: Difficulty/compensating_invariant/program_authorized_cents_conserved_across_allocate_and_withdraw
        """
        context = two_certified_retrofit_projects(
            authorized_cents=60000000, equity_target_bps=4000
        )
        program_id = context["program"]["id"]
        allocate(program_id, context["project_a"]["id"], 20000000)
        allocate(program_id, context["project_b"]["id"], 30000000)

        withdraw_project(context["project_b"]["id"], context["harbor"]["id"])

        program = read_capital_program(program_id)
        assert_fields(
            program,
            {
                "authorized_cents": 60000000,
                "committed_cents": 20000000,
                "available_cents": 40000000,
                "equity_committed_cents": 20000000,
                "equity_achieved_bps": 10000,
                "funding_posture": "OPEN",
                "version": 4,
            },
            "the program restored to its pre-allocation ledger",
        )
        assert_program_conservation(program)
        assert_fields(
            read_project(context["project_b"]["id"]),
            {"program_status": "WITHDRAWN", "allocated_cents": 0, "grant_hold_flag": False},
            "the withdrawn project",
        )
        assert_fields(
            read_project(context["project_a"]["id"]),
            {"allocated_cents": 20000000, "grant_hold_flag": False},
            "the surviving project, never put on hold",
        )


class TestPactUnitsAreConservedAcrossBothTerminalMoves:
    """Only one of the two terminal transitions releases reserved capacity."""

    @staticmethod
    def _pact_with_two_overlapping_four_unit_commitments():
        harbor = create_harbor()
        ridge = create_ridge()
        asset = create_asset(harbor["id"], is_shared=True)
        pact = create_pact(
            harbor["id"],
            resource_class="GENERATORS",
            pledged_units=10,
            max_concurrent_commitments=4,
        )
        first = commit_aid(
            pact["id"], ridge["id"], asset["id"], 4,
            "2026-09-05T00:00:00Z", "2026-09-15T00:00:00Z",
        )
        return {
            "harbor": harbor,
            "ridge": ridge,
            "asset": asset,
            "pact": pact,
            "first": first,
        }

    def test_overlapping_commitments_reserve_the_sum_of_their_units(self):
        """Points 1 and 2: the peak rises to 8 while the pledge stays 10.

        PRD 3.9: "`reserved_units` is set to the **peak** concurrent unit load over
        the pact's `COMMITTED` and `FULFILLED` commitments — computed by exactly the
        same procedure as the admission check above, and defined as 0 when that set is
        empty — and `free_units` becomes `pledged_units` minus `reserved_units`.
        Because `reserved_units` is a peak and not a running sum, two four-unit
        commitments whose half-open windows do not overlap reserve four units between
        them, not eight; two whose windows do overlap reserve eight."

        Design: Difficulty/compensating_invariant/pact_pledged_units_conserved_across_commit_fulfil_and_release
        """
        context = self._pact_with_two_overlapping_four_unit_commitments()
        pact_id = context["pact"]["id"]

        after_first = read_pact(pact_id)
        assert_fields(
            after_first,
            {"pledged_units": 10, "reserved_units": 4, "free_units": 6, "status": "OPEN"},
            "the pact after one commitment",
        )
        assert_pact_conservation(after_first)

        commit_aid(
            pact_id, context["ridge"]["id"], context["asset"]["id"], 4,
            "2026-09-10T00:00:00Z", "2026-09-20T00:00:00Z",
        )

        after_second = read_pact(pact_id)
        assert_fields(
            after_second,
            {"pledged_units": 10, "reserved_units": 8, "free_units": 2, "status": "OPEN"},
            "the pact after the overlapping commitment",
        )
        assert_pact_conservation(after_second)

    def test_fulfilment_holds_the_ledger_and_release_restores_it(self):
        """Points 3 and 4: fulfilment reserves on, release compensates exactly.

        PRD 3.9: "fulfilment leaves `reserved_units` and `free_units` **unchanged**,
        because a fulfilled commitment stays inside the reserved set — the units were
        actually consumed, so releasing them back to the pledge would be
        double-counting. Only the commitment's `version` increments by 1."  Release is
        the compensating move: "The pact's `reserved_units` is then recomputed as the
        peak load over the *surviving* active commitments and `free_units` as
        `pledged_units` minus that peak, so the pact returns to exactly the values it
        held before this commitment was admitted, with no drift".

        Design: Difficulty/compensating_invariant/pact_pledged_units_conserved_across_commit_fulfil_and_release
        """
        context = self._pact_with_two_overlapping_four_unit_commitments()
        pact_id = context["pact"]["id"]
        second = commit_aid(
            pact_id, context["ridge"]["id"], context["asset"]["id"], 4,
            "2026-09-10T00:00:00Z", "2026-09-20T00:00:00Z",
        )

        fulfill_commitment(context["first"]["id"], context["ridge"]["id"])

        fulfilled = read_commitment(context["first"]["id"])
        assert_fields(fulfilled, {"status": "FULFILLED"}, "the fulfilled commitment")
        assert fulfilled["fulfilled_at"] is not None, (
            "PRD 3.9 stamps `fulfilled_at` from the logical clock on fulfilment, "
            f"found {fulfilled['fulfilled_at']}"
        )
        after_fulfil = read_pact(pact_id)
        assert_fields(
            after_fulfil,
            {"reserved_units": 8, "free_units": 2, "version": 3},
            "the pact fulfilment must leave alone",
        )
        assert_pact_conservation(after_fulfil)

        release_commitment(second["id"], context["ridge"]["id"])

        released = read_commitment(second["id"])
        assert_fields(released, {"status": "RELEASED"}, "the released commitment")
        assert released["released_at"] is not None, (
            "PRD 3.9 stamps `released_at` from the logical clock on release, "
            f"found {released['released_at']}"
        )
        assert_fields(
            read_commitment(context["first"]["id"]),
            {"status": "FULFILLED"},
            "the fulfilled commitment, which release must not disturb",
        )
        after_release = read_pact(pact_id)
        assert_fields(
            after_release,
            {"pledged_units": 10, "reserved_units": 4, "free_units": 6, "status": "OPEN"},
            "the pact restored to its point-one ledger",
        )
        assert_pact_conservation(after_release)
