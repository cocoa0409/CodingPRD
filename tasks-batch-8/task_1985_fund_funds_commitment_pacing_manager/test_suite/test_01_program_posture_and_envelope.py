"""Program creation, derived posture envelope, gating, and terminal lockdown."""
import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_program,
    contribute,
    create_funded_program,
    create_open_program,
    create_program_only,
    get_program,
    make_cio_headers,
    make_ops_headers,
    make_staff_trio,
    register_staff,
    validate_error,
    validate_success,
)


class TestProgramCreation:
    def test_program_create_returns_201_with_computed_defaults(self):
        """PRD §3.1: "On creation the program's `status` is `DRAFT`, all
        aggregates are initialised to zero, and posture is computed — but a
        `DRAFT` program is not yet a candidate for `NORMAL` because it cannot
        be opened until its cash is funded."
        PRD §2.4: "Otherwise, if `unrestricted_cash` is strictly below
        `liquidity_buffer_min` multiplied by 1.10, posture is `RESTRICTED`; a
        cash balance exactly equal to the buffer times 1.10 is `NORMAL`."

        Design: Corner/entities/program_create_returns_201_with_computed_defaults
        """
        resp = api_client.create_program(
            {
                "program_name": "PC",
                "base_currency": "USD",
                "total_nav_budget": 50_000_000,
                "strategy_cap_pct": 0.30,
                "manager_cap_pct": 0.25,
                "max_vintage_band_years": 4,
                "liquidity_buffer_min": 1_000_000,
                "overdue_grace_days": 10,
                "secondary_premium_cap_pct": 0.05,
                "secondary_discount_cap_pct": 0.10,
            },
            make_cio_headers(),
        )
        data = validate_success(resp, expected_status=201)
        assert_program(data)
        assert data["status"] == "DRAFT"
        assert data["unrestricted_cash"] == pytest.approx(0, abs=0.005)
        # cash 0 < 1.10 * 1,000,000 buffer -> RESTRICTED
        assert data["posture"] == "RESTRICTED"
        assert data["version"] == 1
        assert data["committed_total"] == pytest.approx(0, abs=0.005)
        assert data["deployed_total"] == pytest.approx(0, abs=0.005)
        assert data["returned_total"] == pytest.approx(0, abs=0.005)
        assert data["unfunded_total"] == pytest.approx(0, abs=0.005)

    def test_program_create_missing_required_field_returns_invalid_request(self):
        """PRD §3.1: "A `CIO` establishes a program by supplying its
        `program_name`, a `base_currency` (one of `USD`, `EUR`, `GBP`) used for
        all aggregates, a `total_nav_budget` that must be greater than zero, and
        a set of governance knobs"
        PRD §2.1-adjacent error rule (§5): malformed or incomplete bodies are
        rejected with `ERR_INVALID_REQUEST` (HTTP 400).

        Design: Corner/entities/program_create_missing_required_field_returns_invalid_request
        """
        payload = {
            # total_nav_budget omitted
            "program_name": "PC2",
            "base_currency": "USD",
            "strategy_cap_pct": 0.30,
            "manager_cap_pct": 0.25,
            "max_vintage_band_years": 4,
            "liquidity_buffer_min": 1_000_000,
            "overdue_grace_days": 10,
            "secondary_premium_cap_pct": 0.05,
            "secondary_discount_cap_pct": 0.10,
        }
        resp = api_client.create_program(payload, make_cio_headers())
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

        # Invalid enum on base_currency is also ERR_INVALID_REQUEST.
        bad_enum = dict(payload)
        bad_enum["total_nav_budget"] = 50_000_000
        bad_enum["base_currency"] = "JPY"
        resp2 = api_client.create_program(bad_enum, make_cio_headers())
        validate_error(resp2, ApiErrorId.ERR_INVALID_REQUEST)

    def test_system_fields_client_input_ignored(self):
        """PRD §2.7: "Primary resources carry a standard system-managed field
        set: `id` (a server-minted UUID with no type prefix), `created_at` (an
        ISO 8601 UTC timestamp with three fractional digits), `updated_at` (an
        ISO 8601 UTC timestamp refreshed on every mutation), and `version` (an
        integer that increments on every mutation, including mutations that only
        recompute derived fields)."
        PRD §3.1: "On creation the program's `status` is `DRAFT`, all aggregates
        are initialised to zero"

        Design: Corner/entities/system_fields_client_input_ignored
        """
        resp = api_client.create_program(
            {
                "program_name": "PSF",
                "base_currency": "USD",
                "total_nav_budget": 50_000_000,
                "strategy_cap_pct": 0.30,
                "manager_cap_pct": 0.25,
                "max_vintage_band_years": 4,
                "liquidity_buffer_min": 1_000_000,
                "overdue_grace_days": 10,
                "secondary_premium_cap_pct": 0.05,
                "secondary_discount_cap_pct": 0.10,
                # client attempts to pre-set system/computed fields:
                "unrestricted_cash": 999_999_999,
                "posture": "NORMAL",
                "status": "OPEN",
            },
            make_cio_headers(),
        )
        data = validate_success(resp, expected_status=201)
        assert data["unrestricted_cash"] == pytest.approx(0, abs=0.005), (
            "client-supplied unrestricted_cash must be ignored"
        )
        assert data["status"] == "DRAFT", "client-supplied status must be ignored"
        assert data["posture"] == "RESTRICTED", (
            "client-supplied posture must be ignored; 0 cash is below 1.10x buffer"
        )


class TestPostureBoundaries:
    def test_posture_low_cash_band_exactly_at_110pct_is_normal(self):
        """PRD §2.4: "Otherwise, if `unrestricted_cash` is strictly below
        `liquidity_buffer_min` multiplied by 1.10, posture is `RESTRICTED`; a
        cash balance exactly equal to the buffer times 1.10 is `NORMAL`."

        Design: Difficulty/boundary_precision_check/posture_low_cash_band_exactly_at_110pct_is_normal
        """
        ops = register_staff("Ops Eleven", "OPS_ANALYST", "ops11@x.com")
        ops_h = make_ops_headers(ops["id"])
        program = create_program_only(
            program_name="P11",
            total_nav_budget=50_000_000,
            liquidity_buffer_min=1_000_000,
        )
        contribute(program["id"], 1_099_999.99, ops_h)
        opened = validate_success(api_client.open_program(program["id"], make_cio_headers()))
        assert opened["posture"] == "RESTRICTED", (
            "1,099,999.99 is strictly below 1.10 * 1,000,000"
        )

        contribute(program["id"], 0.01, ops_h)
        after = get_program(program["id"], ops_h)
        assert after["unrestricted_cash"] == pytest.approx(1_100_000.00, abs=0.005)
        assert after["posture"] == "NORMAL", (
            "cash exactly equal to buffer * 1.10 must be NORMAL"
        )

    def test_posture_low_cash_band_one_cent_below_is_restricted(self):
        """PRD §2.4: "Otherwise, if `unrestricted_cash` is strictly below
        `liquidity_buffer_min` multiplied by 1.10, posture is `RESTRICTED`; a
        cash balance exactly equal to the buffer times 1.10 is `NORMAL`."

        Second test for the same boundary: one cent below the edge stays
        RESTRICTED even after a second contribution that does not reach it.

        Design: Difficulty/boundary_precision_check/posture_low_cash_band_exactly_at_110pct_is_normal
        """
        ops = register_staff("Ops Eleven B", "OPS_ANALYST", "ops11b@x.com")
        ops_h = make_ops_headers(ops["id"])
        program = create_program_only(
            program_name="P11B",
            total_nav_budget=50_000_000,
            liquidity_buffer_min=1_000_000,
        )
        contribute(program["id"], 1_000_000.00, ops_h)
        opened = validate_success(api_client.open_program(program["id"], make_cio_headers()))
        assert opened["posture"] == "RESTRICTED"  # 1,000,000 < 1,100,000
        contribute(program["id"], 99_999.98, ops_h)
        after = get_program(program["id"], ops_h)
        assert after["unrestricted_cash"] == pytest.approx(1_099_999.98, abs=0.005)
        assert after["posture"] == "RESTRICTED"

    def test_posture_gated_frozen_blocks_all_program_writes(self):
        """PRD §2.4: "If the program's `status` is `SUSPENDED` or `CLOSED`,
        posture is `FROZEN` and every mutating write scoped to the program is
        rejected with `ERR_POSTURE_GATED` (HTTP 409)."

        Design: Corner/validations/posture_gated_frozen_blocks_all_program_writes
        """
        ops = register_staff("Ops V1", "OPS_ANALYST", "opsv1@x.com")
        ops_h = make_ops_headers(ops["id"])
        program = create_open_program(
            program_name="PV1", cash=5_000_000, ops_headers=ops_h,
            total_nav_budget=50_000_000,
        )
        validate_success(api_client.suspend_program(program["id"], make_cio_headers()))
        resp = api_client.create_ledger_entry(
            program["id"], {"entry_kind": "CONTRIBUTION", "amount": 1_000_000}, ops_h
        )
        validate_error(resp, ApiErrorId.ERR_POSTURE_GATED)
        after = get_program(program["id"], ops_h)
        assert after["unrestricted_cash"] == pytest.approx(5_000_000.00, abs=0.005)

    def test_program_terminal_close_lockdown(self):
        """PRD §3.1: "Closing a program is permitted only when no `Commitment`
        remains in `PENDING_DOCS` or in `EXECUTED` with a positive
        `unfunded_amount`, no `CapitalCall` remains in `ISSUED` or `OVERDUE`,
        and no `SecondaryBid` remains in `PROPOSED`, `COUNTERED`, or `ACCEPTED`;
        the close transition cascades every `APPROVED` pacing plan to
        `ARCHIVED`, every `DRAFT` or `RECOMMENDED` proposal to `WITHDRAWN`, and
        freezes the posture."

        Design: Corner/state_machines/program_terminal_close_lockdown
        """
        ops = register_staff("Ops C3", "OPS_ANALYST", "opsc3@x.com")
        ops_h = make_ops_headers(ops["id"])
        program = create_open_program(
            program_name="PCL", cash=5_000_000, ops_headers=ops_h,
            total_nav_budget=50_000_000,
        )
        closed = validate_success(api_client.close_program(program["id"], make_cio_headers()))
        assert closed["status"] == "CLOSED"
        assert closed["posture"] == "FROZEN"

        resp = api_client.resume_program(program["id"], make_cio_headers())
        err = validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert err["error_id"] == "ERR_INVALID_STATE"
        after = get_program(program["id"], ops_h)
        assert after["status"] == "CLOSED"
        assert after["posture"] == "FROZEN"
