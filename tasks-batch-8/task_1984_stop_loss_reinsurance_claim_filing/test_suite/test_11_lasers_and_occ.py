"""Lasered member terms: half-open interval overlap, ordered intake checks,
and optimistic concurrency on the contract version."""
from test_helpers import (
    ADMIN,
    ApiErrorId,
    activate_contract,
    create_and_pay_claim,
    create_contract,
    create_laser,
    create_member,
    create_plan,
    get_contract_version,
    setup_plan_contract_member,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import api_client as _api_client
from test_helpers.factories import (
    create_filing_payload,
    create_lasered_term_payload,
)
from test_helpers.fixtures import ANALYST


class TestLaserIntervalOverlap:
    def test_adjacent_laser_intervals_allowed(self, api):
        """PRD §3.3: "Then the laser-specific rules:
        `lasered_specific_deductible_cents` must be strictly greater than the
        contract's `specific_deductible_cents`, and no two `ACTIVE` lasers
        for the same contract and member may have overlapping half-open
        effective windows — both violations surface as `ERR_LASER_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/laser_interval_overlap_half_open
        """
        ctx = setup_plan_contract_member(plan_name="Omicron")
        contract_id = ctx["contract"]["id"]
        member_id = ctx["member"]["id"]
        # L1 covers [2026-01-01, 2026-07-01).
        create_laser(contract_id, member_id, 15_000_000,
                     "2026-01-01T00:00:00Z", "2026-07-01T00:00:00Z")
        # Half-open semantics: L2 starting exactly at L1's effective_to does
        # not overlap.
        resp = _api_client.create_lasered_term(
            create_lasered_term_payload(
                contract_id, member_id, 16_000_000,
                "2026-07-01T00:00:00Z", "2027-01-01T00:00:00Z",
                get_contract_version(contract_id)), ADMIN)
        laser2 = validate_success(resp, 201)
        assert laser2["status"] == "ACTIVE"

        data, meta = validate_paginated(_api_client.list_lasered_terms(ADMIN))
        mine = [l for l in data if l["contract_id"] == contract_id
                and l["member_id"] == member_id and l["status"] == "ACTIVE"]
        assert len(mine) == 2, (
            f"Expected 2 ACTIVE adjacent lasers, got {len(mine)}")

    def test_overlapping_laser_interval_rejected(self, api):
        """PRD §3.3: "no two `ACTIVE` lasers for the same contract and member
        may have overlapping half-open effective windows — both violations
        surface as `ERR_LASER_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/laser_interval_overlap_half_open
        """
        ctx = setup_plan_contract_member(plan_name="Omicron")
        contract_id = ctx["contract"]["id"]
        member_id = ctx["member"]["id"]
        create_laser(contract_id, member_id, 15_000_000,
                     "2026-01-01T00:00:00Z", "2026-07-01T00:00:00Z")
        # Starts one day before L1's effective_to: the intervals intersect.
        resp = _api_client.create_lasered_term(
            create_lasered_term_payload(
                contract_id, member_id, 16_000_000,
                "2026-06-30T00:00:00Z", "2026-12-01T00:00:00Z",
                get_contract_version(contract_id)), ADMIN)
        validate_error(resp, ApiErrorId.ERR_LASER_CONFLICT)


class TestLaserOrderedChecks:
    def _two_plans(self):
        p1 = create_plan(plan_name="Kappa1", sponsor_tax_id="88-8888881")
        p2 = create_plan(plan_name="Kappa2", sponsor_tax_id="88-8888882")
        c1 = activate_contract(create_contract(p1["id"])["id"])
        m2 = create_member(p2["id"], "M2")
        return p1, p2, c1, m2

    def test_cross_plan_member_rejected_before_laser_rules(self, api):
        """PRD §3.3: "Creation runs its checks in a fixed order. First the
        member must belong to the plan the contract insures, else
        `ERR_CROSS_PLAN_REFERENCE`. Next the window must be well-formed, with
        `effective_from` strictly earlier than `effective_to`, else
        `ERR_INVALID_DATE_RANGE`. Then the laser-specific rules:
        `lasered_specific_deductible_cents` must be strictly greater than the
        contract's `specific_deductible_cents`, and no two `ACTIVE` lasers
        for the same contract and member may have overlapping half-open
        effective windows — both violations surface as `ERR_LASER_CONFLICT`."

        Design: Difficulty/priority_pair_validation_conflict/business_referential_vs_business_constraint_on_laser_create
        """
        _, _, c1, m2 = self._two_plans()
        # Member belongs to a different plan AND the deductible (50000_00) is
        # below the contract base (100000_00): the referential check runs
        # first.
        resp = _api_client.create_lasered_term(
            create_lasered_term_payload(
                c1["id"], m2["id"], 5_000_000,
                "2026-01-01T00:00:00Z", "2027-01-01T00:00:00Z",
                get_contract_version(c1["id"])), ADMIN)
        validate_error(resp, ApiErrorId.ERR_CROSS_PLAN_REFERENCE)

    def test_laser_deductible_not_above_base_rejected(self, api):
        """PRD §3.3: "Then the laser-specific rules:
        `lasered_specific_deductible_cents` must be strictly greater than the
        contract's `specific_deductible_cents`, and no two `ACTIVE` lasers
        for the same contract and member may have overlapping half-open
        effective windows — both violations surface as `ERR_LASER_CONFLICT`."

        Design: Difficulty/priority_pair_validation_conflict/business_referential_vs_business_constraint_on_laser_create
        """
        ctx = setup_plan_contract_member(plan_name="Kappa1")
        contract_id = ctx["contract"]["id"]
        # Same-plan member, well-formed window, no existing laser: only the
        # below-base deductible rule can fail.
        resp = _api_client.create_lasered_term(
            create_lasered_term_payload(
                contract_id, ctx["member"]["id"], 5_000_000,
                "2026-01-01T00:00:00Z", "2027-01-01T00:00:00Z",
                get_contract_version(contract_id)), ADMIN)
        validate_error(resp, ApiErrorId.ERR_LASER_CONFLICT)


class TestOptimisticConcurrency:
    def test_stale_version_on_filing_create(self, api):
        """PRD §2.8: "Each of these requests must carry
        `expected_contract_version`, a non-optional field holding the
        contract `version` the client last observed. If the value does not
        match the contract's current `version` — because activation, renewal,
        another laser creation, or another filing creation has advanced it
        since the client last read the contract — the request is rejected
        with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/validations/stale_version_on_filing_create
        """
        ctx = setup_plan_contract_member(plan_name="P")
        contract_id = ctx["contract"]["id"]
        stale_version = ctx["contract"]["version"]  # observed post-activation
        # A laser creation advances the contract version past what the
        # analyst observed.
        create_laser(contract_id, ctx["member"]["id"], 15_000_000,
                     "2026-01-01T00:00:00Z", "2027-01-01T00:00:00Z")
        claim = create_and_pay_claim(ctx["plan"]["id"], ctx["member"]["id"],
                                     15_000_000)
        resp = _api_client.create_filing(
            create_filing_payload(contract_id, "SPECIFIC", [claim["id"]],
                                  stale_version,
                                  member_id=ctx["member"]["id"]),
            ANALYST)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

    def test_stale_version_on_laser_create(self, api):
        """PRD §2.8: "If the value does not match the contract's current
        `version` — because activation, renewal, another laser creation, or
        another filing creation has advanced it since the client last read
        the contract — the request is rejected with `ERR_STALE_VERSION`
        (HTTP 412)."
        PRD §3.3: "Finally the optimistic-concurrency check of §2.8 applies,
        so a stale `expected_contract_version` is rejected with
        `ERR_STALE_VERSION` only after the earlier checks have passed."

        Design: Corner/cross_cutting_layers/occ_stale_version_on_laser_create
        """
        ctx = setup_plan_contract_member(plan_name="P", member_external_id="A")
        contract_id = ctx["contract"]["id"]
        member_b = create_member(ctx["plan"]["id"], "B")
        stale_version = ctx["contract"]["version"]  # observed post-activation
        # First laser create succeeds against the observed version and
        # advances the contract version.
        create_laser(contract_id, ctx["member"]["id"], 15_000_000,
                     "2026-01-01T00:00:00Z", "2027-01-01T00:00:00Z")
        # Second laser create (different member, valid terms) with the stale
        # observed version is rejected by the OCC check.
        resp = _api_client.create_lasered_term(
            create_lasered_term_payload(
                contract_id, member_b["id"], 16_000_000,
                "2026-01-01T00:00:00Z", "2027-01-01T00:00:00Z",
                stale_version), ADMIN)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
