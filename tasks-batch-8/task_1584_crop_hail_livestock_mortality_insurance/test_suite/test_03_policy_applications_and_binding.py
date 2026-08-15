"""Policy applications, coverage units, deadlines, binding, and billing
(PRD §3.4, §3.6)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_policy,
    assert_policy_invariants,
    assert_timestamp_equals,
    create_carrier,
    create_grower,
    create_policy_application,
    create_published_rate,
    add_coverage_unit,
    bind_policy,
    pay_premium,
    read_policy,
    set_clock,
    setup_bound_crop_hail_policy,
    make_policyholder_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

UW = TEST_USERS["underwriter_headers"]


def _setup_dual_rate_scenario(api):
    """Carrier on clock 2026-07-15; R1 (rate 350) PUBLISHED; policy with one
    100-acre unit created under R1; then R2 (rate 400, from 2026-08-01)
    published and R1 superseded; clock advanced to 2026-08-01 (pre-bind)."""
    carrier = create_carrier(carrier_code="CHL-A")
    cid = carrier["id"]
    set_clock(cid, "2026-07-15T00:00:00Z")
    r1 = create_published_rate(
        cid, "CROP_HAIL", rate_per_100_cents_of_liability=350,
        effective_from="2026-01-01T00:00:00Z",
    )
    grower = create_grower(cid)
    policy = create_policy_application(
        cid, grower["id"], "CROP_HAIL",
        effective_date="2026-07-20T00:00:00Z",
        expiration_date="2026-12-31T00:00:00Z",
    )
    unit = add_coverage_unit(cid, policy["id"], "CROP_HAIL", declared_acres=100)
    r2_resp = api.create_rate_table(
        cid,
        {
            "rating_kind": "CROP_HAIL", "county_code": "06001", "crop_code": "CORN",
            "rate_per_100_cents_of_liability": 400,
            "effective_from": "2026-08-01T00:00:00Z",
        },
        UW,
    )
    r2 = validate_success(r2_resp, 201)
    validate_success(api.supersede_rate_table(cid, r1["id"], UW), 200)
    validate_success(api.publish_rate_table(cid, r2["id"], UW), 200)
    set_clock(cid, "2026-08-01T00:00:00Z")
    return {"carrier_id": cid, "grower": grower, "policy": policy, "unit": unit}


class TestPremiumProvisionalVsFinalAtBind:
    def test_provisional_unit_premium_uses_create_clock_rate(self, api):
        """PRD §3.4: "This per-unit figure uses the rate in effect at the current
        clock when the unit is created, and it is recomputed against the binding
        clock time and frozen at bind."
        PRD §3.4: "Each unit's `premium_cents` is then its liability multiplied
        by the matching published row's `rate_per_100_cents_of_liability` and
        divided by 10,000, rounded half up to whole cents — a crop-hail unit
        matches a row on county and crop, while a livestock unit matches when its
        species equals the row's and its per-head value falls at or above the
        band floor and strictly below the band ceiling."
        At creation (clock 2026-07-15) rate 350 applies:
        round_half_up(100 * 40_000 * 350 / 10_000) = 140_000.

        Design: Difficulty/dual_variant_calc/policy_premium_provisional_vs_final_at_bind
        """
        ctx = _setup_dual_rate_scenario(api)
        unit = ctx["unit"]
        assert unit["liability_cents"] == 100 * 40_000
        assert unit["premium_cents"] == 140_000, (
            f"provisional unit premium must use the create-time rate: "
            f"{unit['premium_cents']}"
        )

    def test_bind_recomputes_premium_against_binding_clock(self, api):
        """PRD §3.4: "This per-unit figure uses the rate in effect at the current
        clock when the unit is created, and it is recomputed against the binding
        clock time and frozen at bind."
        PRD §3.4: "The policy moves from `APPLICATION` to `BOUND`, its billing
        becomes `BILLED`, its `premium_reserve_cents` is established at sixty
        percent of the frozen premium rounded down to a whole cent, and the
        policy's `version` increments."
        At bind (clock 2026-08-01) rate 400 applies:
        round_half_up(4_000_000 * 400 / 10_000) = 160_000; reserve =
        floor(160_000 * 0.60) = 96_000.

        Design: Difficulty/dual_variant_calc/policy_premium_provisional_vs_final_at_bind
        """
        ctx = _setup_dual_rate_scenario(api)
        res = api.bind_policy(ctx["carrier_id"], ctx["policy"]["id"], UW)
        bound = validate_success(res, 200)
        assert_policy(bound)
        assert bound["premium_cents"] == 160_000, (
            f"bind must re-rate against the binding clock: {bound['premium_cents']}"
        )
        assert bound["lifecycle_state"] == "BOUND"
        assert bound["billing_state"] == "BILLED"
        assert bound["premium_reserve_cents"] == 96_000
        assert_policy_invariants(bound)


class TestPolicyDeadlinesAndUnits:
    def test_policy_computed_deadlines_derived_from_effective_and_expiration(self, api):
        """PRD §3.4: "The server mints a unique `policy_number` of the form
        `POL-<carrier_code>-<seq>`, stamps the new policy into `APPLICATION`
        lifecycle with billing `UNBILLED` and `claims_posture` `OPEN`, and
        computes three reporting deadlines: for crop-hail policies the
        `acreage_report_deadline` falls twenty-one days after the effective date
        and the `harvest_report_deadline` fourteen days before expiration; for
        livestock policies the `head_report_deadline` falls ten days after the
        effective date."

        Design: Corner/entities/policy_computed_deadlines_derived_from_effective_and_expiration
        """
        carrier = create_carrier(carrier_code="CHL-Z4")
        grower = create_grower(carrier["id"])
        policy = create_policy_application(
            carrier["id"], grower["id"], "CROP_HAIL",
            effective_date="2026-08-10T00:00:00Z",
            expiration_date="2026-12-31T00:00:00Z",
        )
        assert_policy(policy)
        assert_timestamp_equals(
            policy["acreage_report_deadline"], "2026-08-31T00:00:00Z",
            "acreage_report_deadline",
        )
        assert_timestamp_equals(
            policy["harvest_report_deadline"], "2026-12-17T00:00:00Z",
            "harvest_report_deadline",
        )

    def test_coverage_unit_invalid_enum_species_returns_invalid_request(self, api):
        """PRD §2.9: "Independently of this pipeline, malformed payloads — a
        missing required field, a value of the wrong type, or an enum value
        outside the declared set — are rejected with `ERR_INVALID_REQUEST`
        (HTTP 400)."
        PRD §3.1: the species an adjuster may appraise are "drawn from `CATTLE`,
        `SWINE`, `POULTRY`, `EQUINE`, and `SHEEP`".

        Design: Corner/entities/coverage_unit_invalid_enum_species_returns_invalid_request
        """
        carrier = create_carrier(carrier_code="CHL-Z5")
        grower = create_grower(carrier["id"])
        policy = create_policy_application(
            carrier["id"], grower["id"], "LIVESTOCK_MORTALITY",
            effective_date="2026-08-10T00:00:00Z",
            expiration_date="2027-08-10T00:00:00Z",
        )
        res = api.create_coverage_unit(
            carrier["id"], policy["id"],
            {"species": "DRAGON", "declared_head_count": 5,
             "per_head_value_cents": 100_000},
            UW,
        )
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)


class TestBindPreconditions:
    def test_bind_already_bound_policy_returns_policy_not_in_application(self, api):
        """PRD §3.4: "The policy must still be in `APPLICATION`
        (`ERR_POLICY_NOT_IN_APPLICATION`, HTTP 409); at least one coverage unit
        must exist (`ERR_NO_COVERAGE_UNITS`, HTTP 422); every unit must match a
        `PUBLISHED` rate row whose effectiveness window contains the binding
        clock time (`ERR_NO_ACTIVE_RATE_TABLE`, HTTP 422); the grower must be
        `ACTIVE` (`ERR_GROWER_NOT_ACTIVE`, HTTP 409); and when the application
        names a `prior_policy_id`, that policy must exist and belong to the same
        grower (`ERR_INVALID_PRIOR_POLICY`)."

        Design: Corner/state_machines/bind_already_bound_policy_returns_policy_not_in_application
        """
        ctx = setup_bound_crop_hail_policy(acres_list=(1,))
        res = api.bind_policy(ctx["carrier_id"], ctx["policy_id"], UW)
        validate_error(res, ApiErrorId.ERR_POLICY_NOT_IN_APPLICATION)
        after = read_policy(ctx["carrier_id"], ctx["policy_id"])
        assert after["lifecycle_state"] == "BOUND"

    def test_bind_policy_with_no_coverage_units_returns_no_coverage_units(self, api):
        """PRD §3.4: "The policy must still be in `APPLICATION`
        (`ERR_POLICY_NOT_IN_APPLICATION`, HTTP 409); at least one coverage unit
        must exist (`ERR_NO_COVERAGE_UNITS`, HTTP 422); every unit must match a
        `PUBLISHED` rate row whose effectiveness window contains the binding
        clock time (`ERR_NO_ACTIVE_RATE_TABLE`, HTTP 422); the grower must be
        `ACTIVE` (`ERR_GROWER_NOT_ACTIVE`, HTTP 409); and when the application
        names a `prior_policy_id`, that policy must exist and belong to the same
        grower (`ERR_INVALID_PRIOR_POLICY`)."

        Design: Corner/state_machines/bind_policy_with_no_coverage_units_returns_no_coverage_units
        """
        carrier = create_carrier(carrier_code="CHL-SM2")
        grower = create_grower(carrier["id"])
        policy = create_policy_application(carrier["id"], grower["id"], "CROP_HAIL")
        res = api.bind_policy(carrier["id"], policy["id"], UW)
        validate_error(res, ApiErrorId.ERR_NO_COVERAGE_UNITS)


class TestPolicyReads:
    def test_get_policy_returns_stored_fields(self, api):
        """PRD §3.4: "The server mints a unique `policy_number` of the form
        `POL-<carrier_code>-<seq>`, stamps the new policy into `APPLICATION`
        lifecycle with billing `UNBILLED` and `claims_posture` `OPEN`, and
        computes three reporting deadlines: for crop-hail policies the
        `acreage_report_deadline` falls twenty-one days after the effective date
        and the `harvest_report_deadline` fourteen days before expiration; for
        livestock policies the `head_report_deadline` falls ten days after the
        effective date."
        PRD §2.2: "Unless otherwise noted, operations that create or modify a
        resource will return the created or updated resource object in the data
        field."

        Design: Corner/endpoints/get_policy_returns_stored_fields
        """
        carrier = create_carrier(carrier_code="CHL-E1")
        grower = create_grower(carrier["id"])
        created = create_policy_application(carrier["id"], grower["id"], "CROP_HAIL")
        fetched = validate_success(
            api.get_policy(carrier["id"], created["id"], UW), 200
        )
        assert_policy(fetched)
        assert fetched["id"] == created["id"]
        assert fetched["grower_id"] == grower["id"]
        assert fetched["policy_kind"] == "CROP_HAIL"
        assert fetched["lifecycle_state"] == "APPLICATION"
        assert fetched["billing_state"] == "UNBILLED"
        assert fetched["claims_posture"] == "OPEN"

    def test_list_policies_filtered_by_lifecycle_state(self, api):
        """PRD §2.3: "Several list endpoints additionally accept optional
        filters: `status` on growers, rate tables, and coverage units;
        `rating_kind` on rate tables; `grower_id` on policies and federal crop
        policies; `lifecycle_state` and `billing_state` on policies; and
        `claim_state` on claims."

        Design: Corner/endpoints/list_policies_filtered_by_lifecycle_state
        """
        carrier = create_carrier(carrier_code="CHL-E2")
        cid = carrier["id"]
        grower = create_grower(cid)
        create_published_rate(cid)
        p1 = create_policy_application(cid, grower["id"], "CROP_HAIL")
        p2 = create_policy_application(cid, grower["id"], "CROP_HAIL")
        add_coverage_unit(cid, p2["id"], "CROP_HAIL", declared_acres=1)
        bind_policy(cid, p2["id"])

        data, meta = validate_paginated(
            api.list_policies(cid, UW, params={"lifecycle_state": "BOUND"})
        )
        returned_ids = [p["id"] for p in data]
        assert all(p["lifecycle_state"] == "BOUND" for p in data)
        assert p2["id"] in returned_ids
        assert p1["id"] not in returned_ids


class TestBindCascadeAndBilling:
    def test_cascading_side_effects_policy_bind_sets_reserve_and_billing(self, api):
        """PRD §3.4: "The policy moves from `APPLICATION` to `BOUND`, its billing
        becomes `BILLED`, its `premium_reserve_cents` is established at sixty
        percent of the frozen premium rounded down to a whole cent, and the
        policy's `version` increments."
        Five acres at rate 333: premium round_half_up(200_000 * 333 / 10_000) =
        6_660; reserve floor(6_660 * 0.60) = 3_996.

        Design: Corner/cross_cutting_complexity_layers/cascading_side_effects_policy_bind_sets_reserve_and_billing
        """
        carrier = create_carrier(carrier_code="CHL-CC3")
        cid = carrier["id"]
        grower = create_grower(cid)
        create_published_rate(cid)
        policy = create_policy_application(cid, grower["id"], "CROP_HAIL")
        pre_version = policy["version"]
        add_coverage_unit(cid, policy["id"], "CROP_HAIL", declared_acres=5)

        res = api.bind_policy(cid, policy["id"], UW)
        bound = validate_success(res, 200)
        assert_policy(bound)
        assert bound["lifecycle_state"] == "BOUND"
        assert bound["billing_state"] == "BILLED"
        assert bound["premium_cents"] == 6_660
        assert bound["premium_reserve_cents"] == 3_996
        assert bound["version"] > pre_version, "bind increments the policy version"

    def test_overpayment_rejected(self, api):
        """PRD §3.6: "Payments are accepted only while the policy's lifecycle is
        `BOUND` or `ACTIVE` — attempts against a policy in any other lifecycle
        state are rejected with `ERR_POLICY_NOT_BILLABLE` (HTTP 409) — and a
        payment that exceeds the outstanding balance, meaning the policy's
        `premium_cents` less the `premium_paid_cents` already collected, is
        rejected with `ERR_OVERPAYMENT` (HTTP 422)."
        One acre at rate 333 bills 1_332 cents; a 2_000-cent payment exceeds the
        outstanding balance.

        Design: Corner/validations/overpayment_rejected
        """
        ctx = setup_bound_crop_hail_policy(acres_list=(1,))
        assert ctx["policy"]["premium_cents"] == 1_332
        res = api.create_premium_payment(
            ctx["carrier_id"], ctx["policy_id"], {"amount_cents": 2_000},
            make_policyholder_headers(ctx["grower_id"]),
        )
        validate_error(res, ApiErrorId.ERR_OVERPAYMENT)


class TestParallelBillingAndLifecycleAxes:
    def _setup_partially_paid_policy(self, api):
        ctx = setup_bound_crop_hail_policy(acres_list=(1,))
        pay_premium(ctx["carrier_id"], ctx["policy_id"], ctx["grower_id"], 600)
        return ctx

    def test_lifecycle_activates_while_billing_stays_partially_paid(self, api):
        """PRD §3.4: "Thereafter the policy activates automatically, moving from
        `BOUND` to `ACTIVE`, when the clock reaches the effective date — so long
        as billing has not gone delinquent."
        PRD §3.6: "A payment that falls short of the outstanding balance moves
        billing from `BILLED` to `PARTIALLY_PAID`; one that brings cumulative
        payments up to the full premium moves billing from `BILLED` to
        `PAID_IN_FULL`, or from `PARTIALLY_PAID` to `PAID_IN_FULL`."
        PRD §3.4: "The policy's `claims_posture` is derived, never set directly:
        it reads `OPEN` unless billing has gone `DELINQUENT` or the lifecycle has
        reached `EXPIRED`, `CANCELLED`, or `NON_RENEWED`, in which case it reads
        `RESTRICTED`."

        Design: Difficulty/non_linear_state_machine/policy_parallel_billing_and_lifecycle_dimensions
        """
        ctx = self._setup_partially_paid_policy(api)
        set_clock(ctx["carrier_id"], "2026-08-03T00:00:00Z")
        policy = read_policy(ctx["carrier_id"], ctx["policy_id"])
        assert policy["lifecycle_state"] == "ACTIVE"
        assert policy["billing_state"] == "PARTIALLY_PAID", (
            "billing axis is independent of lifecycle activation"
        )
        assert policy["claims_posture"] == "OPEN"

    def test_billing_goes_delinquent_while_lifecycle_stays_active(self, api):
        """PRD §3.6: "Delinquency is the clock's doing: when `current_utc` passes
        thirty days after the binding moment with the premium still underpaid, a
        policy in `BILLED` or `PARTIALLY_PAID` falls to `DELINQUENT`, its
        `claims_posture` flips to `RESTRICTED`, its grower's `status` flips to
        `SUSPENDED`, and the policy's `version` increments."
        PRD §3.4: "The policy's `claims_posture` is derived, never set directly:
        it reads `OPEN` unless billing has gone `DELINQUENT` or the lifecycle has
        reached `EXPIRED`, `CANCELLED`, or `NON_RENEWED`, in which case it reads
        `RESTRICTED`."
        Bound at the initial clock 2026-08-01; at 2026-09-03 the premium is still
        underpaid thirty days on, so billing falls DELINQUENT while lifecycle
        remains ACTIVE.

        Design: Difficulty/non_linear_state_machine/policy_parallel_billing_and_lifecycle_dimensions
        """
        ctx = self._setup_partially_paid_policy(api)
        set_clock(ctx["carrier_id"], "2026-08-03T00:00:00Z")
        set_clock(ctx["carrier_id"], "2026-09-03T00:00:00Z")
        policy = read_policy(ctx["carrier_id"], ctx["policy_id"])
        assert policy["lifecycle_state"] == "ACTIVE"
        assert policy["billing_state"] == "DELINQUENT"
        assert policy["claims_posture"] == "RESTRICTED"
        assert_policy_invariants(policy)
