"""Platform-wide conventions: envelope, pagination, auth, RBAC, 404 routing,
append-only ledger rows, the logical clock, and OCC on commitment execute."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    api_client,
    assert_ledger_entry,
    commitment_for_proposal,
    contribute,
    create_approved_vehicle,
    create_ic_approved_proposal,
    create_manager,
    create_open_program,
    create_program_only,
    create_recommended_proposal,
    create_vehicle,
    get_latest_review,
    issue_call,
    make_analyst_headers,
    make_cio_headers,
    make_compliance_headers,
    make_ic_headers,
    make_ops_headers,
    make_staff_trio,
    program_version,
    register_staff,
    setup_open_program_with_plan,
    setup_with_executed_commitment,
    advance_clock,
    get_program,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestEnvelopeAndPagination:
    def test_response_envelope_and_pagination(self):
        """PRD §2.3: "`limit` specifies the maximum number of items returned;
        it defaults to 10, accepts a minimum of 1, and is capped at 100.
        `offset` specifies the number of items to skip and defaults to 0.
        Unless otherwise specified, list endpoints sort by `created_at`
        ascending. The `meta` object of every list response carries `limit`,
        `offset`, `total_count`, and `has_more`."
        PRD §2.2: "The `api_request_id` is a server-generated unique
        identifier for the request that starts with `req_`."

        Design: Corner/endpoints/response_envelope_and_pagination
        """
        ana_h, _, _, _ = make_staff_trio("e1")
        for i, name in enumerate(["PgCap1", "PgCap2", "PgCap3"], start=2010):
            validate_success(
                api_client.create_manager(
                    {"legal_name": name, "domicile_country": "US", "relationship_since_year": i},
                    ana_h,
                ),
                expected_status=201,
            )
        page1 = api_client.list_managers(ana_h, params={"limit": 1, "offset": 0})
        rows1, meta1 = validate_paginated(page1)
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True
        assert len(rows1) == 1
        body1 = page1.json()
        assert body1["response_type"] == "array"
        assert body1["meta"]["api_request_id"].startswith("req_")

        page3 = api_client.list_managers(ana_h, params={"limit": 1, "offset": 2})
        rows3, meta3 = validate_paginated(page3)
        assert meta3["has_more"] is False
        assert len(rows3) == 1
        assert rows3[0]["legal_name"] == "PgCap3", "created_at ascending order"

    def test_list_filter_by_status(self):
        """PRD §4 (list contract): commitment lists accept a `status` filter
        and the list response envelope carries the pagination fields required
        by §2.3 ("The `meta` object of every list response carries `limit`,
        `offset`, `total_count`, and `has_more`.").

        Design: Corner/endpoints/list_filter_by_status
        """
        ctx = setup_with_executed_commitment(
            cash=20_000_000, proposed_amount=5_000_000, staff_prefix="e2",
            program_name="PE2", strategy_cap_pct=0.95, manager_cap_pct=0.95,
            plan_overrides={"target_strategy_mix": [{"strategy": "BUYOUT", "weight": 1.0}]},
        )
        ana_h, ic_h, ops_h = ctx.analyst_headers, ctx.ic_headers, ctx.ops_headers
        # Second proposal approved but NOT executed -> PENDING_DOCS commitment.
        prop_b = create_ic_approved_proposal(
            ctx.vehicle["id"], ctx.program["id"], ctx.plan["id"], ana_h, ic_h, 3_000_000
        )
        com_b = commitment_for_proposal(prop_b["id"], ops_h)

        rows_ex, meta_ex = validate_paginated(
            api_client.list_program_commitments(ctx.program["id"], ops_h, params={"status": "EXECUTED"})
        )
        assert meta_ex["total_count"] == 1
        assert rows_ex[0]["id"] == ctx.commitment["id"]

        rows_pd, meta_pd = validate_paginated(
            api_client.list_program_commitments(ctx.program["id"], ops_h, params={"status": "PENDING_DOCS"})
        )
        assert meta_pd["total_count"] == 1
        assert rows_pd[0]["id"] == com_b["id"]

        _, meta_all = validate_paginated(
            api_client.list_program_commitments(ctx.program["id"], ops_h)
        )
        assert meta_all["total_count"] == 2


class TestNotFoundAndAuth:
    def test_entity_not_found_returns_404(self):
        """PRD §2.8: "Requests that target nested resources validate path
        identifiers left-to-right: the program first, then the mid-level
        resource (pacing plan, vehicle, commitment, secondary bid, valuation
        report), then the leaf resource (call, distribution, snapshot,
        review). The first identifier that does not resolve produces
        `ERR_NOT_FOUND` (HTTP 404) and validation stops there"

        Design: Corner/entities/entity_not_found_returns_404
        """
        program = create_program_only(program_name="PNF", total_nav_budget=50_000_000)
        resp = api_client.get_program_commitment(
            program["id"], NON_EXISTENT_UUID, make_cio_headers()
        )
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_error_unauthenticated_missing_headers(self):
        """PRD §2.1: "A missing `X-User-Role`, an unrecognised role value, or
        a missing `X-User-ID` for an entity-backed role is rejected with
        `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/errors/error_unauthenticated_missing_headers
        """
        resp = api_client.get_program(NON_EXISTENT_UUID, headers={})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


class TestRbac:
    def test_analyst_cannot_open_program(self):
        """PRD §2.1: "A role that is recognised but not permitted for the
        endpoint per the role matrix is rejected with `ERR_UNAUTHORIZED`
        (HTTP 403)."
        PRD §4: POST `/fof/programs/{id}/open` is authorized for `CIO` only.

        Design: Corner/roles/analyst_cannot_open_program
        """
        ana_h, _, ops_h, _ = make_staff_trio("r1")
        prog = create_program_only(program_name="PR1", total_nav_budget=50_000_000)
        contribute(prog["id"], 5_000_000, ops_h)
        resp = api_client.open_program(prog["id"], ana_h)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
        after = get_program(prog["id"], make_cio_headers())
        assert after["status"] == "DRAFT"

    def test_ops_cannot_approve_proposal(self):
        """PRD §2.1: "A role that is recognised but not permitted for the
        endpoint per the role matrix is rejected with `ERR_UNAUTHORIZED`
        (HTTP 403)."
        PRD §4: POST `/fof/proposals/{id}/ic-approve` is authorized for
        `InvestmentCommittee` only; POST
        `/fof/vehicles/{id}/dd-reviews/{reviewId}/submit` is authorized for
        `Analyst` only.

        Design: Corner/roles/ops_cannot_approve_proposal
        """
        ana_h, ic_h, ops_h, _ = make_staff_trio("r2")
        ctx = setup_open_program_with_plan(
            cash=20_000_000, staff_prefix="r2p", program_name="PR2",
            plan_overrides={"target_strategy_mix": [{"strategy": "BUYOUT", "weight": 1.0}]},
        )
        ana_h, ic_h, ops_h = ctx.analyst_headers, ctx.ic_headers, ctx.ops_headers
        manager = create_manager(ana_h, legal_name="RbacCap")
        vehicle = create_vehicle(manager["id"], ana_h, fund_name="Rbac I")
        validate_success(api_client.begin_diligence(manager["id"], vehicle["id"], ana_h))
        review = get_latest_review(vehicle["id"], ana_h)
        # CIO (not an entity-backed Analyst) cannot submit a DD review.
        api_client.update_dd_review(
            vehicle["id"], review["id"],
            {"score_strategy_fit": 80, "score_track_record": 80,
             "score_operations": 80, "score_compliance": 80},
            ana_h,
        )
        resp_submit = api_client.submit_dd_review(vehicle["id"], review["id"], make_cio_headers())
        validate_error(resp_submit, ApiErrorId.ERR_UNAUTHORIZED)

        validate_success(api_client.submit_dd_review(vehicle["id"], review["id"], ana_h))
        validate_success(api_client.complete_dd_review(vehicle["id"], review["id"], ic_h))
        validate_success(api_client.approve_vehicle(manager["id"], vehicle["id"], ic_h))
        proposal = create_recommended_proposal(
            vehicle["id"], ctx.program["id"], ctx.plan["id"], ana_h, 5_000_000
        )
        resp = api_client.ic_approve_proposal(proposal["id"], ops_h)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
        after = validate_success(api_client.get_proposal(proposal["id"], ana_h))
        assert after["status"] == "RECOMMENDED"

    def test_compliance_officer_cannot_suspend_program(self):
        """PRD §2.1: "A role that is recognised but not permitted for the
        endpoint per the role matrix is rejected with `ERR_UNAUTHORIZED`
        (HTTP 403)."
        PRD §4: POST `/fof/programs/{id}/suspend` is authorized for `CIO`
        only.

        Design: Corner/roles/compliance_officer_cannot_suspend_program
        """
        _, _, ops_h, _ = make_staff_trio("r3")
        program = create_open_program(
            program_name="PR3", cash=5_000_000, ops_headers=ops_h, total_nav_budget=50_000_000
        )
        resp = api_client.suspend_program(program["id"], make_compliance_headers())
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
        after = get_program(program["id"], make_compliance_headers())
        assert after["status"] == "OPEN"


class TestLedgerImmutability:
    def test_immutable_ledger_entry_has_no_update_or_version(self):
        """PRD §2.7: "Two collection resources — `CashLedgerEntry` and
        `LookThroughLine` — are append-only audit children and carry only `id`
        and `created_at`; `updated_at` and `version` are absent on those
        rows."
        PRD §2.6: "`ref_id` is null for `CONTRIBUTION` and
        `MANUAL_ADJUSTMENT`"

        Design: Corner/entities/immutable_ledger_entry_has_no_update_or_version
        """
        _, _, ops_h, _ = make_staff_trio("c2")
        program = create_program_only(program_name="PIM", total_nav_budget=50_000_000)
        contribute(program["id"], 5_000_000, ops_h)
        entries, meta = validate_paginated(api_client.list_ledger_entries(program["id"], ops_h))
        assert meta["total_count"] == 1
        entry = entries[0]
        assert_ledger_entry(entry)
        assert entry["balance_after"] == pytest.approx(5_000_000.00, abs=0.005)
        assert entry["entry_kind"] == "CONTRIBUTION"
        assert entry["ref_id"] is None


class TestLogicalClock:
    def test_logical_clock_default_and_overdue_noop_before_set(self):
        """PRD §2.9: "The server maintains a logical clock seeded at exactly
        `2026-08-01T00:00:00Z` on startup; the clock never falls back to
        wall-clock time, and an `OperationsAnalyst` can advance it via a
        test-driving capability that takes a `to_iso8601` instant, runs the
        overdue sweep, and recomputes postures for affected programs."
        PRD §3.5: "A clock sweep — driven by advancing the logical clock —
        moves any `ISSUED` call whose `due_date` plus the program's
        `overdue_grace_days` has passed into `OVERDUE`"

        Design: Corner/cross_cutting_layers/logical_clock_default_and_overdue_noop_before_set
        """
        ctx = setup_with_executed_commitment(
            cash=20_000_000, proposed_amount=5_000_000, staff_prefix="x4",
            program_name="PX4", strategy_cap_pct=0.95, manager_cap_pct=0.95,
            plan_overrides={"target_strategy_mix": [{"strategy": "BUYOUT", "weight": 1.0}]},
        )
        call = issue_call(ctx, amount=1_000_000, purpose="FEES", due_date="2026-08-05T00:00:00Z")
        before = validate_success(api_client.get_call(call["id"], ctx.ops_headers))
        assert before["issued_on"].startswith("2026-08-01T00:00:00"), (
            "default clock stamps issuance at 2026-08-01T00:00:00Z"
        )
        assert before["status"] == "ISSUED"

        advance_clock(ctx, "2026-08-16T00:00:00Z")
        after = validate_success(api_client.get_call(call["id"], ctx.ops_headers))
        # due 2026-08-05 + grace 10 days -> overdue once clock passes 2026-08-15
        assert after["status"] == "OVERDUE"


class TestOccOnExecute:
    def test_occ_stale_version_on_commitment_execute(self):
        """PRD §2.5: "Each such request must carry a non-optional
        `expected_program_version` field carrying the client's last observed
        `version` of the parent `FoFProgram`. If the supplied value does not
        match the program's current `version`, the request is rejected with
        `ERR_STALE_VERSION` (HTTP 412), forcing the client to re-read the
        program before retrying."
        PRD §3.4: "Execution takes two inputs: the final `sized_amount` and
        `expected_program_version` matching the program's current `version`
        (mismatch is `ERR_STALE_VERSION`)."

        Design: Corner/cross_cutting_layers/occ_stale_version_on_commitment_execute
        """
        ctx = setup_open_program_with_plan(
            cash=30_000_000, staff_prefix="x1", program_name="PX1",
            strategy_cap_pct=0.95, manager_cap_pct=0.95,
            plan_overrides={"target_strategy_mix": [{"strategy": "VENTURE", "weight": 1.0}]},
        )
        ana_h, ic_h, ops_h = ctx.analyst_headers, ctx.ic_headers, ctx.ops_headers
        manager, veh1 = create_approved_vehicle(ana_h, ic_h, strategy="VENTURE")
        prop1 = create_ic_approved_proposal(veh1["id"], ctx.program["id"], ctx.plan["id"], ana_h, ic_h, 5_000_000)
        com1 = commitment_for_proposal(prop1["id"], ops_h)
        veh2 = create_approved_vehicle(ana_h, ic_h, strategy="VENTURE")[1]
        prop2 = create_ic_approved_proposal(veh2["id"], ctx.program["id"], ctx.plan["id"], ana_h, ic_h, 5_000_000)
        com2 = commitment_for_proposal(prop2["id"], ops_h)

        pv_stale = program_version(ctx.program["id"], ops_h)
        ok1 = validate_success(
            api_client.execute_commitment(
                ctx.program["id"], com1["id"],
                {"sized_amount": 5_000_000, "expected_program_version": pv_stale}, ops_h,
            )
        )
        assert ok1["status"] == "EXECUTED"

        resp = api_client.execute_commitment(
            ctx.program["id"], com2["id"],
            {"sized_amount": 5_000_000, "expected_program_version": pv_stale}, ops_h,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

        pv_fresh = program_version(ctx.program["id"], ops_h)
        ok2 = validate_success(
            api_client.execute_commitment(
                ctx.program["id"], com2["id"],
                {"sized_amount": 5_000_000, "expected_program_version": pv_fresh}, ops_h,
            )
        )
        assert ok2["status"] == "EXECUTED"
        program = get_program(ctx.program["id"], ops_h)
        assert program["committed_total"] == pytest.approx(10_000_000.00, abs=0.005)
