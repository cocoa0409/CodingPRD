"""Claim filing, bar-date gate, determination, reconsideration, class buckets."""
from test_helpers import (
    COURT,
    CREDITOR,
    RECEIVER,
    ApiErrorId,
    WAGE_PRIORITY_CAP_CENTS,
    assert_claim,
    create_asset,
    create_case,
    create_claim,
    determine_claim,
    disallow_claim,
    get_case,
    liquidate_asset,
    reconsider_claim,
    set_clock,
    setup_case_with_cash,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestClaimFiling:
    def test_claim_invalid_creditor_type_returns_400(self, api):
        """PRD §2.10: "Request shape: required fields are present, types are
        valid, enum values are in range, and conditional requirements are
        satisfied"
        PRD §2.10: "Any failure here is `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/entities/claim_invalid_creditor_type_returns_400
        """
        case = create_case()
        resp = api.create_claim(
            {
                "case_id": case["id"],
                "creditor_name": "Odd Creditor",
                "creditor_type": "BANKER",
                "filed_amount_cents": 10000,
            },
            CREDITOR,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_claim_with_missing_collateral_asset_returns_404(self, api):
        """PRD §3.4: "The referenced asset must exist within the same case
        (otherwise `ERR_NOT_FOUND`) and must not be `ABANDONED` (otherwise
        `ERR_COLLATERAL_NOT_ELIGIBLE`)."

        Design: Corner/entities/claim_with_missing_collateral_asset_returns_404
        """
        case = create_case()
        resp = api.create_claim(
            {
                "case_id": case["id"],
                "creditor_name": "Secured Bank",
                "creditor_type": "SECURED",
                "filed_amount_cents": 100000,
                "collateral_asset_id": "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2",
            },
            CREDITOR,
        )
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_secured_claim_on_abandoned_asset_rejected(self, api):
        """PRD §3.4: "The referenced asset must exist within the same case
        (otherwise `ERR_NOT_FOUND`) and must not be `ABANDONED` (otherwise
        `ERR_COLLATERAL_NOT_ELIGIBLE`)."

        Design: Corner/errors/secured_claim_on_abandoned_asset_rejected
        """
        case = create_case()
        asset = create_asset(case["id"], description="Scrap metal",
                             asset_class="EQUIPMENT", estimated_value_cents=100)
        api.abandon_asset(asset["id"], {}, RECEIVER)

        resp = api.create_claim(
            {
                "case_id": case["id"],
                "creditor_name": "Secured Bank",
                "creditor_type": "SECURED",
                "filed_amount_cents": 50000,
                "collateral_asset_id": asset["id"],
            },
            CREDITOR,
        )
        validate_error(resp, ApiErrorId.ERR_COLLATERAL_NOT_ELIGIBLE)

    def test_claim_create_in_distributing_case_rejected(self, api):
        """PRD §3.4: "The case must be `ACTIVE` at filing, failing with
        `ERR_CASE_NOT_ACTIVE` otherwise."

        Design: Corner/errors/claim_create_in_distributing_case_rejected
        """
        estate = setup_estate_for_distributing_case(api)
        resp = api.create_claim(
            {
                "case_id": estate["case"]["id"],
                "creditor_name": "Late New Creditor",
                "creditor_type": "GENERAL_UNSECURED",
                "filed_amount_cents": 1000,
            },
            CREDITOR,
        )
        validate_error(resp, ApiErrorId.ERR_CASE_NOT_ACTIVE)


class TestBarDate:
    def test_bar_date_exact_timestamp_accepted(self, api):
        """PRD §3.4: "a claim whose `filed_at` falls strictly after the
        case's `bar_date` is rejected with `ERR_CLAIM_BARRED` (HTTP 422),
        while a filing landing exactly on the bar date is timely."

        Design: Difficulty/boundary_precision_check/bar_date_exact_timestamp_accepted
        """
        case = create_case(bar_date="2026-09-01T00:00:00Z")
        set_clock("2026-09-01T00:00:00Z")

        resp1 = api.create_claim(
            {
                "case_id": case["id"],
                "creditor_name": "Timely Creditor",
                "creditor_type": "GENERAL_UNSECURED",
                "filed_amount_cents": 10000,
            },
            CREDITOR,
        )
        data1 = validate_success(resp1, 201)
        assert data1["status"] == "FILED"
        assert data1["filed_at"] == "2026-09-01T00:00:00Z"

        set_clock("2026-09-01T00:00:01Z")
        resp2 = api.create_claim(
            {
                "case_id": case["id"],
                "creditor_name": "Late Creditor",
                "creditor_type": "GENERAL_UNSECURED",
                "filed_amount_cents": 10000,
            },
            CREDITOR,
        )
        validate_error(resp2, ApiErrorId.ERR_CLAIM_BARRED)

    def test_bar_date_one_second_after_rejected(self, api):
        """PRD §3.4: "a claim whose `filed_at` falls strictly after the
        case's `bar_date` is rejected with `ERR_CLAIM_BARRED` (HTTP 422),
        while a filing landing exactly on the bar date is timely."

        Design: Difficulty/boundary_precision_check/bar_date_exact_timestamp_accepted
        """
        case = create_case(bar_date="2026-09-01T00:00:00Z")
        # Exactly at the bar date is timely.
        set_clock("2026-09-01T00:00:00Z")
        resp_ok = api.create_claim(
            {
                "case_id": case["id"],
                "creditor_name": "On Time",
                "creditor_type": "GENERAL_UNSECURED",
                "filed_amount_cents": 5000,
            },
            CREDITOR,
        )
        assert validate_success(resp_ok, 201)["filed_at"] == "2026-09-01T00:00:00Z"

        # One second later is strictly after, hence barred.
        set_clock("2026-09-01T00:00:01Z")
        resp_late = api.create_claim(
            {
                "case_id": case["id"],
                "creditor_name": "Too Late",
                "creditor_type": "GENERAL_UNSECURED",
                "filed_amount_cents": 5000,
            },
            CREDITOR,
        )
        validate_error(resp_late, ApiErrorId.ERR_CLAIM_BARRED)


class TestClaimBuckets:
    def test_secured_claim_estimated_vs_realized_collateral(self, api):
        """PRD §3.4: "For a `SECURED` claim, the collateral basis is zero
        when the collateral asset is `ABANDONED`, the asset's
        `liquidation_value_cents` when it is `LIQUIDATED` at determination
        time, or its `estimated_value_cents` when it is still `IDENTIFIED`;
        the `secured_allowed_cents` bucket is the smaller of the allowed
        amount and that basis, and whatever remains of the allowed amount
        spills into `general_allowed_cents` as a deficiency claim"

        Design: Difficulty/dual_variant_calc/secured_claim_estimated_vs_realized_collateral
        """
        case = create_case()
        ax = create_asset(case["id"], description="Warehouse X",
                          asset_class="REAL_PROPERTY", estimated_value_cents=80000)
        ay = create_asset(case["id"], description="Warehouse Y",
                          asset_class="REAL_PROPERTY", estimated_value_cents=80000)
        cx = create_claim(case["id"], creditor_name="Bank X", creditor_type="SECURED",
                          filed_amount_cents=100000, collateral_asset_id=ax["id"])
        cy = create_claim(case["id"], creditor_name="Bank Y", creditor_type="SECURED",
                          filed_amount_cents=100000, collateral_asset_id=ay["id"])

        # Claim X determined while collateral is IDENTIFIED (estimated variant).
        determine_claim(cx["id"], "ALLOWED", 100000)
        # Collateral for claim Y then liquidates below estimate (realized variant).
        liquidate_asset(ay["id"], 60000)
        determine_claim(cy["id"], "ALLOWED", 100000)

        x = validate_success(api.get_claim(cx["id"], RECEIVER), 200)
        y = validate_success(api.get_claim(cy["id"], RECEIVER), 200)
        assert x["secured_allowed_cents"] == 80000
        assert x["general_allowed_cents"] == 20000
        assert y["secured_allowed_cents"] == 60000
        assert y["general_allowed_cents"] == 40000
        assert x["secured_allowed_cents"] != y["secured_allowed_cents"]
        for claim in (x, y):
            assert (
                claim["secured_allowed_cents"] + claim["general_allowed_cents"] == 100000
            )

    def test_secured_claim_estimated_variant_collateral(self, api):
        """PRD §3.4: "or its `estimated_value_cents` when it is still
        `IDENTIFIED`; the `secured_allowed_cents` bucket is the smaller of
        the allowed amount and that basis"

        Design: Difficulty/dual_variant_calc/secured_claim_estimated_vs_realized_collateral
        """
        case = create_case()
        asset = create_asset(case["id"], estimated_value_cents=80000)
        claim = create_claim(case["id"], creditor_type="SECURED",
                             filed_amount_cents=100000, collateral_asset_id=asset["id"])
        determine_claim(claim["id"], "ALLOWED", 100000)

        data = validate_success(api.get_claim(claim["id"], RECEIVER), 200)
        assert data["secured_allowed_cents"] == 80000
        assert data["general_allowed_cents"] == 20000

    def test_wage_priority_cap_splits_buckets(self, api):
        """PRD §3.4: "For a `PRIORITY_WAGE` claim, `priority_allowed_cents`
        is the smaller of the allowed amount and the statutory wage-priority
        cap of $15,150.00 — that is, 1,515,000 cents — and any excess over
        the cap lands in `general_allowed_cents`, with the secured and
        investor buckets zero."

        Design: Corner/calculations/wage_priority_cap_splits_buckets
        """
        case = create_case()
        claim = create_claim(case["id"], creditor_name="Wage Claimant",
                             creditor_type="PRIORITY_WAGE", filed_amount_cents=2000000)
        data = determine_claim(claim["id"], "ALLOWED", 2000000)

        assert data["priority_allowed_cents"] == WAGE_PRIORITY_CAP_CENTS == 1515000
        assert data["general_allowed_cents"] == 485000
        assert data["priority_allowed_cents"] + data["general_allowed_cents"] == 2000000


class TestClaimDeterminationAndReconsideration:
    def test_determine_allowed_exceeds_filed_rejected(self, api):
        """PRD §3.4: "requires `allowed_amount_cents` to be present (else
        `ERR_INVALID_REQUEST`) and no greater than `filed_amount_cents`
        (else `ERR_ALLOWED_EXCEEDS_FILED`, HTTP 422)."

        Design: Corner/validations/determine_allowed_exceeds_filed_rejected
        """
        case = create_case()
        claim = create_claim(case["id"], creditor_type="GENERAL_UNSECURED",
                             filed_amount_cents=100000)
        resp = api.determine_claim(
            claim["id"],
            {"determination": "ALLOWED", "allowed_amount_cents": 150000},
            RECEIVER,
        )
        validate_error(resp, ApiErrorId.ERR_ALLOWED_EXCEEDS_FILED)

    def test_determine_from_allowed_returns_invalid_state(self, api):
        """PRD §2.10: "From-state validity of the requested transition —
        liquidation requires an `IDENTIFIED` asset, a decision requires the
        instrument's pending state, a fee payment requires an `APPROVED`
        application, a distribution payment requires a `SCHEDULED` payment,
        discharge requires a `DISTRIBUTING` case — else `ERR_INVALID_STATE`
        (HTTP 409)."

        Design: Corner/state_machines/determine_from_allowed_returns_invalid_state
        """
        case = create_case()
        claim = create_claim(case["id"], creditor_type="GENERAL_UNSECURED",
                             filed_amount_cents=40000)
        determine_claim(claim["id"], "ALLOWED", 40000)

        resp = api.determine_claim(
            claim["id"],
            {"determination": "ALLOWED", "allowed_amount_cents": 39000},
            RECEIVER,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_claim_reconsideration_cycle(self, api):
        """PRD §3.4: "A `Court`-ordered reconsideration returns an `ALLOWED`
        or `DISALLOWED` claim to `FILED`, provided the case is `ACTIVE` or
        `DISTRIBUTING`."
        PRD §3.4: "Reconsidering an allowed claim clears
        `allowed_amount_cents` and all four class buckets to null, resets
        `determined_at` to null"

        Design: Difficulty/non_linear_state_machine/claim_reconsideration_cycle
        """
        case = create_case()
        claim = create_claim(case["id"], creditor_name="Cycle Creditor",
                             creditor_type="GENERAL_UNSECURED", filed_amount_cents=40000)

        d1 = determine_claim(claim["id"], "ALLOWED", 40000)
        assert d1["status"] == "ALLOWED"
        assert d1["general_allowed_cents"] == 40000

        r1 = reconsider_claim(claim["id"])
        assert r1["status"] == "FILED"
        assert r1["allowed_amount_cents"] is None
        assert r1["general_allowed_cents"] is None
        assert r1["determined_at"] is None

        d2 = determine_claim(claim["id"], "DISALLOWED")
        assert d2["status"] == "DISALLOWED"

        r2 = reconsider_claim(claim["id"])
        assert r2["status"] == "FILED"

        d3 = determine_claim(claim["id"], "ALLOWED", 30000)
        assert d3["status"] == "ALLOWED"
        assert d3["general_allowed_cents"] == 30000, (
            "re-determination recomputes buckets from current values"
        )

    def test_claim_reconsider_disallowed_returns_to_filed(self, api):
        """PRD §3.4: "Reconsidering a disallowed claim simply resets
        `determined_at` to null."

        Design: Difficulty/non_linear_state_machine/claim_reconsideration_cycle
        """
        case = create_case()
        claim = create_claim(case["id"], creditor_type="GENERAL_UNSECURED",
                             filed_amount_cents=40000)
        disallowed = disallow_claim(claim["id"])
        assert disallowed["status"] == "DISALLOWED"
        assert disallowed["determined_at"] is not None

        reconsidered = reconsider_claim(claim["id"])
        assert reconsidered["status"] == "FILED"
        assert reconsidered["determined_at"] is None


class TestClaimsListing:
    def test_claims_list_pagination_and_status_filter(self, api):
        """PRD §2.3: "The `limit` parameter sets the maximum number of items
        returned: it defaults to 10 when omitted, with a minimum of 1 and a
        maximum of 100. The `offset` parameter sets the number of items
        skipped and defaults to 0. Every list response carries `limit`,
        `offset`, `total_count`, and `has_more` in the `meta` object of the
        envelope."

        Design: Corner/entities/claims_list_pagination_and_status_filter
        """
        case = create_case()
        a = create_claim(case["id"], creditor_name="Creditor A", filed_amount_cents=10000)
        create_claim(case["id"], creditor_name="Creditor B", filed_amount_cents=20000)
        create_claim(case["id"], creditor_name="Creditor C", filed_amount_cents=30000)
        determine_claim(a["id"], "ALLOWED", 10000)

        rows, meta = validate_paginated(
            api.list_claims(RECEIVER, {"case_id": case["id"], "status": "FILED"})
        )
        assert len(rows) == 2
        assert meta["total_count"] == 2

        rows2, meta2 = validate_paginated(
            api.list_claims(RECEIVER, {"case_id": case["id"], "limit": 2, "offset": 0})
        )
        assert len(rows2) == 2
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is True


class TestSharedOperationGrant:
    def test_creditor_can_file_claim_and_read_it(self, api):
        """PRD §2.1: "When `X-User-Role` is `Creditor`, `X-User-ID` is an
        opaque claimant account identifier that is never an entity `id`; no
        ownership scoping is enforced — a creditor may read the public
        estate record without restriction to their own claims."

        Design: Corner/rbac/creditor_can_file_claim_and_read_it
        """
        case = create_case()
        resp = api.create_claim(
            {
                "case_id": case["id"],
                "creditor_name": "Self Filer",
                "creditor_type": "GENERAL_UNSECURED",
                "filed_amount_cents": 12345,
            },
            CREDITOR,
        )
        data = validate_success(resp, 201)
        assert data["status"] == "FILED"

        fetched = validate_success(api.get_claim(data["id"], CREDITOR), 200)
        assert fetched["filed_amount_cents"] == 12345


# ---------------------------------------------------------------------------
# helpers local to this module
# ---------------------------------------------------------------------------

def setup_estate_for_distributing_case(api):
    """Build a case that has entered DISTRIBUTING via an approved plan."""
    from test_helpers import create_distribution_plan, decide_distribution_plan

    case, asset = setup_case_with_cash(50000)
    claim = create_claim(case["id"], creditor_type="GENERAL_UNSECURED",
                         filed_amount_cents=50000)
    determine_claim(claim["id"], "ALLOWED", 50000)
    plan = create_distribution_plan(case["id"], reserve_cents=0)
    decide_distribution_plan(plan["id"], "APPROVE")
    return {"case": get_case(case["id"]), "plan": plan, "claim": claim}
