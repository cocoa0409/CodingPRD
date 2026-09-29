"""Requests that violate two ordered guards at once surface only the earlier code."""

from test_helpers import (
    ADMIN,
    ApiErrorId,
    allocate,
    api_client,
    assert_fields,
    assert_pact_conservation,
    commit_aid,
    commitment_payload,
    create_asset,
    create_harbor,
    create_pact,
    create_ridge,
    make_jurisdiction_delegate_headers,
    pact_version,
    read_capital_program,
    read_pact,
    read_project,
    two_certified_retrofit_projects,
    validate_error,
)


class TestAllocationStateBeatsFunds:
    """Guard 1 (already programmed) outranks guard 7 (funds exceeded)."""

    @staticmethod
    def _program_with_one_allocation_and_a_thin_balance():
        context = two_certified_retrofit_projects(
            authorized_cents=40000000, equity_target_bps=4000
        )
        allocate(context["program"]["id"], context["project_a"]["id"], 30000000)
        return context

    def test_double_allocation_reports_the_state_guard_not_the_fiscal_guard(self):
        """Re-funding the funded project reports guard 1 although guard 7 also fails.

        PRD 3.7 fixes the order: "Seven conditions guard it, and they are evaluated
        in exactly this order", opening with "1. The project's `program_status` must
        be `UNPROGRAMMED`; allocating twice to the same project yields
        `ERR_PROJECT_ALREADY_PROGRAMMED`." and closing with "7. `allocated_cents`
        may not exceed the program's current `available_cents`, or
        `ERR_PROGRAM_FUNDS_EXCEEDED`."  The repeat request breaches both, so only
        the first code may surface.

        Design: Difficulty/priority_pair_validation_conflict/allocation_state_error_precedes_funds_exceeded
        """
        context = self._program_with_one_allocation_and_a_thin_balance()
        program = read_capital_program(context["program"]["id"])
        assert_fields(
            program,
            {"committed_cents": 30000000, "available_cents": 10000000, "version": 2},
            "the program before the rejected retry",
        )

        response = api_client.allocate(
            program["id"],
            {
                "project_id": context["project_a"]["id"],
                "allocated_cents": 30000000,
                "expected_capital_program_version": program["version"],
            },
            ADMIN(),
        )

        validate_error(response, ApiErrorId.ERR_PROJECT_ALREADY_PROGRAMMED.value, 409)
        assert_fields(
            read_capital_program(program["id"]),
            {"committed_cents": 30000000, "available_cents": 10000000, "version": 2},
            "the program a rejected allocation must leave untouched",
        )

    def test_fresh_project_over_the_balance_reaches_the_fiscal_guard(self):
        """The control call proves guard 7 is reachable once guard 1 is satisfied.

        PRD 3.7: "7. `allocated_cents` may not exceed the program's current
        `available_cents`, or `ERR_PROGRAM_FUNDS_EXCEEDED`."  The sibling project is
        still `UNPROGRAMMED`, so the earlier guards pass and the fiscal ceiling is
        the one that bites; PRD 3.7 also holds that a rejected allocation leaves the
        project alone, since allocation "is the act that moves a project's
        `program_status` `UNPROGRAMMED → PROGRAMMED`".

        Design: Difficulty/priority_pair_validation_conflict/allocation_state_error_precedes_funds_exceeded
        """
        context = self._program_with_one_allocation_and_a_thin_balance()
        program = read_capital_program(context["program"]["id"])

        response = api_client.allocate(
            program["id"],
            {
                "project_id": context["project_b"]["id"],
                "allocated_cents": 30000000,
                "expected_capital_program_version": program["version"],
            },
            ADMIN(),
        )

        validate_error(response, ApiErrorId.ERR_PROGRAM_FUNDS_EXCEEDED.value, 409)
        assert_fields(
            read_capital_program(program["id"]),
            {"committed_cents": 30000000, "available_cents": 10000000, "version": 2},
            "the program after the fiscal rejection",
        )
        assert_fields(
            read_project(context["project_b"]["id"]),
            {"program_status": "UNPROGRAMMED", "allocated_cents": 0},
            "the project the rejected allocation must not touch",
        )


class TestAidSharingBeatsConcurrency:
    """Guard 5 (asset not shared) outranks guard 8 (concurrency limit)."""

    @staticmethod
    def _pact_holding_two_overlapping_commitments():
        harbor = create_harbor()
        ridge = create_ridge()
        shared_asset = create_asset(harbor["id"], is_shared=True)
        local_asset = create_asset(
            harbor["id"],
            name="Harbor Depot Backup Feeder",
            asset_class="POWER",
            replacement_value_cents=400000000,
            service_population=40000,
            redundancy_factor=0.10,
            is_shared=False,
        )
        pact = create_pact(harbor["id"], pledged_units=10, max_concurrent_commitments=3)
        commit_aid(
            pact["id"], ridge["id"], shared_asset["id"], 1,
            "2026-09-05T00:00:00Z", "2026-09-15T00:00:00Z",
        )
        commit_aid(
            pact["id"], ridge["id"], shared_asset["id"], 1,
            "2026-09-10T00:00:00Z", "2026-09-20T00:00:00Z",
        )
        return {
            "harbor": harbor,
            "ridge": ridge,
            "shared_asset": shared_asset,
            "local_asset": local_asset,
            "pact": pact,
        }

    def test_unshared_asset_reports_the_sharing_guard_not_the_concurrency_guard(self):
        """A third window on a private asset reports guard 5 although guard 8 also fails.

        PRD 3.9 fixes the order: "Nine conditions guard the commitment, and they are
        evaluated in exactly this order", with "5. The named lifeline asset's
        `is_shared` must be true, because only shared assets may be supported across
        jurisdictional lines; otherwise `ERR_ASSET_NOT_SHARED`." ahead of "8. The
        maximum **count** of overlapping commitments at any window-start instant must
        remain strictly below the pact's `max_concurrent_commitments`, or
        `ERR_AID_CONCURRENCY_LIMIT`."

        Design: Difficulty/priority_pair_validation_conflict/aid_commitment_asset_not_shared_precedes_concurrency_limit
        """
        context = self._pact_holding_two_overlapping_commitments()
        pact_id = context["pact"]["id"]

        response = api_client.create_commitment(
            pact_id,
            commitment_payload(
                context["ridge"]["id"],
                context["local_asset"]["id"],
                1,
                "2026-09-12T00:00:00Z",
                "2026-09-14T00:00:00Z",
                pact_version(pact_id),
            ),
            make_jurisdiction_delegate_headers(context["ridge"]["id"]),
        )

        validate_error(response, ApiErrorId.ERR_ASSET_NOT_SHARED.value, 409)
        pact = read_pact(pact_id)
        assert_fields(
            pact,
            {"reserved_units": 2, "free_units": 8, "status": "OPEN", "version": 3},
            "the pact a rejected commitment must leave untouched",
        )
        assert_pact_conservation(pact)

    def test_shared_asset_on_the_same_window_reaches_the_concurrency_guard(self):
        """The control call swaps only the asset and now reports guard 8.

        PRD 3.9: "This limit is about how many simultaneous engagements a host can
        coordinate, not about units: a fourth window covering the same instant as
        three others is rejected on a pact whose limit is 3 even when the unit total
        would fit comfortably."  The peak unit load here is 3 against
        `pledged_units` 10, and PRD 3.9 admits that load — "9. The peak **unit
        load** must be less than or equal to the pact's `pledged_units`" — so the
        count gate is the only one that can fire.

        Design: Difficulty/priority_pair_validation_conflict/aid_commitment_asset_not_shared_precedes_concurrency_limit
        """
        context = self._pact_holding_two_overlapping_commitments()
        pact_id = context["pact"]["id"]

        response = api_client.create_commitment(
            pact_id,
            commitment_payload(
                context["ridge"]["id"],
                context["shared_asset"]["id"],
                1,
                "2026-09-12T00:00:00Z",
                "2026-09-14T00:00:00Z",
                pact_version(pact_id),
            ),
            make_jurisdiction_delegate_headers(context["ridge"]["id"]),
        )

        validate_error(response, ApiErrorId.ERR_AID_CONCURRENCY_LIMIT.value, 409)
        pact = read_pact(pact_id)
        assert_fields(
            pact,
            {"reserved_units": 2, "free_units": 8, "status": "OPEN", "version": 3},
            "the pact after the concurrency rejection",
        )
        assert_pact_conservation(pact)
