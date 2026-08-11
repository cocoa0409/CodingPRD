"""Claims: creation defaults, parallel state dimensions, settlement cascades,
per-occurrence boundary, OCC on settle, and immediate consistency."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_claim,
    create_claim,
    create_operating_unit,
    get_captive,
    get_captive_version,
    settle_claim,
    setup_active_captive_with_program,
    setup_reserved_claim,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestClaimCreation:

    def test_claim_computed_fields_on_creation(self, api, claims_adjuster_headers):
        """PRD §3.6: "On creation, the claim is stamped with a system-generated
        `claim_number` of the form `CLM-YYYYMMDD-NNNN`, lands in `REPORTED`
        status with `payment_status` set to `UNPAID` and `litigation_status` set
        to `NOT_LITIGATED`, and the system computes `coverage_confirmed` (true
        when the loss date falls within the policy period and the claimed amount
        does not exceed the applicable limits)."

        Design: Corner/entities/claim_computed_fields_on_creation
        """
        captive, program, _fronting = setup_active_captive_with_program()
        unit = create_operating_unit(captive["id"])
        claim = create_claim(captive["id"], program["id"], unit["id"],
                             claimant_name="Test Claimant", claimed_amount_cents=50000)
        assert_claim(claim)
        assert claim["claim_number"].startswith("CLM-"), (
            f"claim_number must be of the form CLM-YYYYMMDD-NNNN, got {claim['claim_number']!r}"
        )
        assert claim["claim_status"] == "REPORTED"
        assert claim["payment_status"] == "UNPAID"
        assert claim["litigation_status"] == "NOT_LITIGATED"
        assert claim["paid_amount_cents"] == 0
        # Loss 2026-07-15 is inside the 2026-06-01..2027-05-31 policy period and
        # 50000 does not exceed the 250000 per-occurrence limit.
        assert claim["coverage_confirmed"] is True


class TestClaimParallelDimensions:

    def test_reserved_claim_dimensions(self, api, claims_adjuster_headers):
        """PRD §3.6: "Setting the reserve by an `Actuary` moves the claim
        `UNDER_INVESTIGATION → RESERVED`; the body carries `reserve_amount_cents`
        which becomes the new `reserved_amount_cents`."
        PRD §3.6: the claim "lands in `REPORTED` status with `payment_status` set
        to `UNPAID` and `litigation_status` set to `NOT_LITIGATED`" — reserving
        moves neither parallel dimension.

        Design: Difficulty/non_linear_state_machine/claim_parallel_dimensions_payment_and_litigation
        """
        ctx = setup_reserved_claim(reserve_amount_cents=45000)
        claim = ctx["claim"]
        assert claim["claim_status"] == "RESERVED"
        assert claim["reserved_amount_cents"] == 45000
        assert claim["payment_status"] == "UNPAID"
        assert claim["litigation_status"] == "NOT_LITIGATED"

    def test_settle_flips_payment_dimension_only(self, api, claims_adjuster_headers):
        """PRD §3.6: "On success the claim transitions to `SETTLED`,
        `paid_amount_cents` is set to `settlement_amount_cents`,
        `reserved_amount_cents` is reset to zero, and `payment_status` flips to
        `FULLY_PAID` when the settlement is at least the previously reserved
        amount, or to `PARTIALLY_PAID` otherwise."

        Design: Difficulty/non_linear_state_machine/claim_parallel_dimensions_payment_and_litigation
        """
        ctx = setup_reserved_claim(reserve_amount_cents=45000)
        settled = validate_success(settle_claim(ctx, 45000))
        assert settled["claim_status"] == "SETTLED"
        assert settled["paid_amount_cents"] == 45000
        assert settled["reserved_amount_cents"] == 0
        assert settled["payment_status"] == "FULLY_PAID"
        assert settled["litigation_status"] == "NOT_LITIGATED"


class TestSettlementCascade:

    def test_settlement_updates_claim_fields(self, api, claims_adjuster_headers):
        """PRD §3.6: "On success the claim transitions to `SETTLED`,
        `paid_amount_cents` is set to `settlement_amount_cents`,
        `reserved_amount_cents` is reset to zero, and `payment_status` flips to
        `FULLY_PAID` when the settlement is at least the previously reserved
        amount, or to `PARTIALLY_PAID` otherwise."

        Design: Difficulty/transitive_cascade/claim_settlement_cascades_to_captive_solvency
        """
        ctx = setup_reserved_claim(reserve_amount_cents=45000)
        settled = validate_success(settle_claim(ctx, 45000))
        assert settled["claim_status"] == "SETTLED"
        assert settled["paid_amount_cents"] == 45000
        assert settled["payment_status"] == "FULLY_PAID"
        assert settled["reserved_amount_cents"] == 0

    def test_settlement_cascades_to_captive_ledger(self, api, claims_adjuster_headers):
        """PRD §3.6: "The captive's `admitted_assets` is reduced by the
        settlement, the program's `claims_paid_cents` is updated, the captive's
        `total_reserves_held` is reduced, and the captive's `version` is
        incremented."
        PRD §2.8: the ratio and status "are recomputed on every event that could
        move `admitted_assets` or the required capital — a claim settlement, a
        collateral posting or release, a premium allocation finalization, or a
        reserve certification."

        Design: Difficulty/transitive_cascade/claim_settlement_cascades_to_captive_solvency
        """
        ctx = setup_reserved_claim(reserve_amount_cents=45000)
        captive_id = ctx["captive"]["id"]
        before = get_captive(captive_id)
        validate_success(settle_claim(ctx, 45000))
        after = get_captive(captive_id)
        assert after["admitted_assets"] == before["admitted_assets"] - 45000, (
            f"admitted_assets must drop by the 45000-cent settlement: "
            f"{before['admitted_assets']} -> {after['admitted_assets']}"
        )
        assert after["total_reserves_held"] == before["total_reserves_held"] - 45000, (
            f"total_reserves_held must drop by the released 45000-cent reserve: "
            f"{before['total_reserves_held']} -> {after['total_reserves_held']}"
        )
        assert after["version"] == before["version"] + 1, (
            f"Captive version must increment on settlement: "
            f"{before['version']} -> {after['version']}"
        )
        program = validate_success(
            api.get_program(captive_id, ctx["program"]["id"], claims_adjuster_headers)
        )
        assert program["claims_paid_cents"] == 45000


class TestSettlementBoundary:

    def test_settlement_exactly_at_per_occurrence_limit_succeeds(self, api):
        """PRD §3.6: "Settlement requires `RESERVED` (else
        `ERR_CLAIM_NOT_RESERVED`), requires the settlement to be no more than the
        program's `per_occurrence_limit_cents` (else `ERR_SETTLEMENT_EXCEEDS_LIMIT`,
        HTTP 400)" — a settlement exactly equal to the limit is "no more than"
        the limit and therefore succeeds.

        Design: Difficulty/boundary_precision_check/claim_settlement_exactly_at_per_occurrence_limit
        """
        ctx = setup_reserved_claim(reserve_amount_cents=250000,
                                   claimed_amount_cents=250000,
                                   per_occurrence_limit_cents=250000)
        settled = validate_success(settle_claim(ctx, 250000))
        assert settled["claim_status"] == "SETTLED"
        assert settled["paid_amount_cents"] == 250000

    def test_settlement_one_cent_over_per_occurrence_limit_rejected(self, api):
        """PRD §3.6: "requires the settlement to be no more than the program's
        `per_occurrence_limit_cents` (else `ERR_SETTLEMENT_EXCEEDS_LIMIT`,
        HTTP 400)" — one cent above the limit exceeds it and is rejected.

        Design: Difficulty/boundary_precision_check/claim_settlement_exactly_at_per_occurrence_limit
        """
        ctx = setup_reserved_claim(reserve_amount_cents=250000,
                                   claimed_amount_cents=250000,
                                   per_occurrence_limit_cents=250000)
        resp = settle_claim(ctx, 250001)
        validate_error(resp, ApiErrorId.ERR_SETTLEMENT_EXCEEDS_LIMIT)

    def test_claim_settlement_exceeds_per_occurrence_limit(self, api):
        """PRD §3.6: "Settlement requires `RESERVED` (else
        `ERR_CLAIM_NOT_RESERVED`), requires the settlement to be no more than the
        program's `per_occurrence_limit_cents` (else `ERR_SETTLEMENT_EXCEEDS_LIMIT`,
        HTTP 400)".

        Design: Corner/validations/claim_settlement_exceeds_per_occurrence_limit
        """
        ctx = setup_reserved_claim(reserve_amount_cents=100000,
                                   claimed_amount_cents=100000,
                                   per_occurrence_limit_cents=100000)
        resp = settle_claim(ctx, 150000)
        validate_error(resp, ApiErrorId.ERR_SETTLEMENT_EXCEEDS_LIMIT)


class TestSettlementConcurrency:

    def test_error_stale_version_on_claim_settle(self, api, claims_adjuster_headers,
                                                 captive_manager_headers):
        """PRD §2.4: "Settling a claim is likewise guarded: the settle request
        body must carry `expected_captive_version` matching the captive's current
        `version`, and a mismatch is rejected with `ERR_STALE_VERSION`
        (HTTP 412)."

        Design: Corner/errors/error_stale_version_on_claim_settle
        """
        ctx = setup_reserved_claim(reserve_amount_cents=45000)
        stale_version = get_captive_version(ctx["captive"]["id"]) - 1
        resp = settle_claim(ctx, 45000, expected_captive_version=stale_version)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

    def test_immediate_consistency_on_claim_settlement(self, api):
        """PRD §2.2: "Unless otherwise noted, operations that create or modify a
        resource will return the created or updated resource object in the data
        field."
        PRD §3.6: "On success the claim transitions to `SETTLED`,
        `paid_amount_cents` is set to `settlement_amount_cents`,
        `reserved_amount_cents` is reset to zero, and `payment_status` flips to
        `FULLY_PAID` when the settlement is at least the previously reserved
        amount, or to `PARTIALLY_PAID` otherwise." — all of these are visible in
        the settle response itself.

        Design: Corner/consistency_model/immediate_consistency_on_claim_settlement
        """
        ctx = setup_reserved_claim(reserve_amount_cents=45000)
        data = validate_success(settle_claim(ctx, 45000))
        assert data["claim_status"] == "SETTLED"
        assert data["paid_amount_cents"] == 45000
        assert data["payment_status"] == "FULLY_PAID"
        assert data["reserved_amount_cents"] == 0


class TestClaimFiltering:

    def test_claims_filtered_by_operating_unit(self, api, claims_adjuster_headers):
        """PRD §4: "GET | /api/claims | List claims (filtered by `program_id`,
        `operating_unit_id`, `captive_id`, `tpa_assigned_id`)" — the claims
        collection filters by `operating_unit_id`, reaching back from an
        operating unit to its claims.

        Design: Corner/endpoints/claims_filtered_by_operating_unit
        """
        captive, program, _fronting = setup_active_captive_with_program()
        unit = create_operating_unit(captive["id"], unit_name="Unit FK2", unit_code="UFK2")
        claim = create_claim(captive["id"], program["id"], unit["id"],
                             claimant_name="Claimant FK2")
        resp = api.list_claims_flat(claims_adjuster_headers,
                                    params={"operating_unit_id": unit["id"]})
        data, meta = validate_paginated(resp)
        assert len(data) == 1, f"Expected exactly 1 claim for the unit, got {len(data)}"
        assert data[0]["id"] == claim["id"]
