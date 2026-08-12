"""Customer choice documentation, shop routing, selector policy, claim OCC."""
from test_helpers import (
    TEST_USERS, validate_success, validate_error, validate_paginated,
    ApiErrorId,
    assert_choice_disclosure_record, assert_work_order,
    create_choice_disclosure_payload,
    make_policyholder_headers, make_shop,
    make_claim, add_disclosure, verify_claim, route_claim, get_claim,
    get_work_order, setup_network, setup_claim_verified,
)

ADMIN = TEST_USERS["admin_headers"]
ADJUSTER = TEST_USERS["adjuster_headers"]


class TestChoiceDisclosure:
    def test_choice_disclosure_record_immutable(self, api):
        """PRD §2.5: "The ChoiceDisclosureRecord is the sole exception. It is
        append-only and immutable once created, so it carries only `id` and
        `created_at`; both `updated_at` and `version` are absent from it."

        Design: Corner/entities/choice_disclosure_record_immutable
        """
        net = setup_network(with_shop=False, with_part=False)
        claim = make_claim(net["policyholder"], net["policy"],
                           estimated_repair_cost_cents=80000)
        resp = api.create_choice_disclosure(
            claim["id"], create_choice_disclosure_payload(),
            make_policyholder_headers(net["policyholder"]["id"]))
        record = validate_success(resp, 201)
        assert_choice_disclosure_record(record)
        data, _meta = validate_paginated(
            api.list_choice_disclosures(claim["id"], ADMIN))
        assert len(data) == 1
        assert data[0]["claim_id"] == claim["id"]


class TestSelectorPolicy:
    def test_shop_selector_tier_ranking_and_tiebreak(self, api):
        """PRD §3.3: "Absent a requested shop, the eligible pool is ranked by the
        shop's agreement-tier multiplier in ascending order — `PLATINUM` (0.75)
        before `PREFERRED` (0.85) before `STANDARD` (0.95) — with ties broken by
        the shop's `created_at` in ascending order, so the cheapest agreement
        tier wins."

        Design: Corner/calculations/shop_selector_tier_ranking_and_tiebreak
        """
        net = setup_network(with_shop=False, with_part=False)
        make_shop(shop_name="Std First", agreement_tier="STANDARD")
        plat = make_shop(shop_name="Plat Second", agreement_tier="PLATINUM")
        make_shop(shop_name="Pref Third", agreement_tier="PREFERRED")
        ctx = setup_claim_verified(net)
        wo = route_claim(ctx["claim"]["id"])
        assert_work_order(wo)
        assert wo["shop_id"] == plat["id"]
        claim = get_claim(ctx["claim"]["id"])
        assert claim["assigned_shop_id"] == plat["id"]

    def test_shop_selector_zip_prefix_eligibility(self, api):
        """PRD §3.3: "The eligibility filter admits a shop only when its
        `network_status` is `ACTIVE`, when at least one of its
        `service_zip_prefixes` is a prefix of the claim's `service_zip_code`..."
        PRD §3.3: "An empty pool is rejected with `ERR_NO_ELIGIBLE_SHOP`
        (HTTP 422)."

        Design: Corner/calculations/shop_selector_zip_prefix_eligibility
        """
        net = setup_network(with_shop=False, with_part=False)
        make_shop(shop_name="Wrong Zip", service_zip_prefixes=["337"],
                  agreement_tier="PLATINUM")
        ctx = setup_claim_verified(net)
        resp = api.create_routing_decision(
            ctx["claim"]["id"],
            {"expected_claim_version": ctx["claim"]["version"]}, ADJUSTER)
        validate_error(resp, ApiErrorId.ERR_NO_ELIGIBLE_SHOP)
        assert get_claim(ctx["claim"]["id"])["status"] == "COVERAGE_VERIFIED"


class TestRoutingGates:
    def test_adas_routing_to_non_certified_shop_rejected(self, api):
        """PRD §3.3: "The eligibility filter admits a shop only when ... the
        claim either does not require ADAS calibration or the shop is
        `adas_certified`."
        PRD §3.3: "one that fails the eligibility filter is rejected with
        `ERR_SHOP_NOT_ELIGIBLE` (HTTP 422)."

        Design: Corner/validations/adas_routing_to_non_certified_shop_rejected
        """
        net = setup_network(with_shop=False, with_part=False)
        shop_a = make_shop(shop_name="NoAdas", agreement_tier="PLATINUM",
                           adas_certified=False)
        shop_b = make_shop(shop_name="YesAdas", agreement_tier="STANDARD",
                           adas_certified=True)
        ctx = setup_claim_verified(
            net, claim_overrides={"requires_adas_calibration": True,
                                  "estimated_repair_cost_cents": 150000})
        resp = api.create_routing_decision(
            ctx["claim"]["id"],
            {"expected_claim_version": ctx["claim"]["version"],
             "requested_shop_id": shop_a["id"]}, ADJUSTER)
        validate_error(resp, ApiErrorId.ERR_SHOP_NOT_ELIGIBLE)
        wo = route_claim(ctx["claim"]["id"])
        assert wo["shop_id"] == shop_b["id"]

    def test_active_work_order_blocks_rerouting(self, api):
        """PRD §3.3: "no linked work order may currently be in `ACCEPTED` or
        `SCHEDULED` (else `ERR_ACTIVE_WORK_ORDER_EXISTS`, HTTP 409)."

        Design: Corner/validations/active_work_order_blocks_rerouting
        """
        net = setup_network(with_shop=False, with_part=False)
        shop_1 = make_shop(shop_name="AW Shop 1", agreement_tier="PLATINUM")
        shop_2 = make_shop(shop_name="AW Shop 2", agreement_tier="STANDARD")
        ctx = setup_claim_verified(net)
        wo = route_claim(ctx["claim"]["id"], requested_shop_id=shop_1["id"])
        from test_helpers import accept_work_order
        accept_work_order(wo["id"], shop_1["id"])
        current = get_claim(ctx["claim"]["id"])
        resp = api.create_routing_decision(
            ctx["claim"]["id"],
            {"expected_claim_version": current["version"],
             "requested_shop_id": shop_2["id"]}, ADJUSTER)
        validate_error(resp, ApiErrorId.ERR_ACTIVE_WORK_ORDER_EXISTS)
        assert get_work_order(wo["id"])["status"] == "ACCEPTED"

    def test_rerouting_supersedes_offered_work_order(self, api):
        """PRD §3.3: "Every existing linked work order in `OFFERED` or `NO_SHOW`
        is moved to `SUPERSEDED`, each with its own `version` increment. A new
        work order is created for the selected shop with `status` `OFFERED` and
        a null `warranty_claim_id`."

        Design: Corner/validations/rerouting_supersedes_offered_work_order
        """
        net = setup_network(with_shop=False, with_part=False)
        shop_1 = make_shop(shop_name="RR Shop 1", agreement_tier="PLATINUM")
        shop_2 = make_shop(shop_name="RR Shop 2", agreement_tier="STANDARD")
        ctx = setup_claim_verified(net)
        wo_1 = route_claim(ctx["claim"]["id"], requested_shop_id=shop_1["id"])
        current = get_claim(ctx["claim"]["id"])
        wo_2 = route_claim(ctx["claim"]["id"], requested_shop_id=shop_2["id"],
                           expected_claim_version=current["version"])
        assert get_work_order(wo_1["id"])["status"] == "SUPERSEDED"
        assert wo_2["status"] == "OFFERED"
        assert wo_2["shop_id"] == shop_2["id"]
        claim = get_claim(ctx["claim"]["id"])
        assert claim["assigned_shop_id"] == shop_2["id"]
        assert claim["status"] == "WORK_AUTHORIZED"


class TestRoutingOcc:
    def test_occ_stale_claim_version_on_routing(self, api):
        """PRD §2.7: "A routing decision against a claim must carry
        `expected_claim_version`, holding the claim `version` the client last
        observed. If the claim's current `version` has advanced past that value
        — because a supplement, a cancellation cascade, or an earlier routing
        decision mutated the claim in between — the request is rejected with
        `ERR_STALE_CLAIM_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_stale_claim_version_on_routing
        """
        net = setup_network(with_part=False)
        claim = make_claim(net["policyholder"], net["policy"])
        add_disclosure(claim["id"], net["policyholder"]["id"])
        v1 = claim["version"]
        verified = verify_claim(claim["id"])
        v2 = verified["version"]
        stale = api.create_routing_decision(
            claim["id"], {"expected_claim_version": v1}, ADJUSTER)
        validate_error(stale, ApiErrorId.ERR_STALE_CLAIM_VERSION)
        assert get_claim(claim["id"])["status"] == "COVERAGE_VERIFIED"
        wo = route_claim(claim["id"], expected_claim_version=v2)
        assert wo["status"] == "OFFERED"
        assert get_claim(claim["id"])["version"] == v2 + 1


# ---------------------------------------------------------------------------
# Difficulty: routing depends on disclosure existence
# ---------------------------------------------------------------------------

class TestRoutingDependsOnDisclosure:
    def _setup_verified_no_disclosure(self):
        net = setup_network(with_part=False)
        claim = make_claim(net["policyholder"], net["policy"],
                           estimated_repair_cost_cents=80000)
        verified = verify_claim(claim["id"])
        return net, claim, verified

    def test_routing_without_disclosure_rejected(self, api):
        """PRD §3.3: "Two gates protect customer choice and workflow integrity:
        at least one ChoiceDisclosureRecord must already exist for the claim
        (else `ERR_CHOICE_DISCLOSURE_REQUIRED`, HTTP 422)..."

        Design: Difficulty/cross_entity_state_dependency/routing_decision_depends_on_disclosure_existence
        """
        _net, claim, verified = self._setup_verified_no_disclosure()
        resp = api.create_routing_decision(
            claim["id"], {"expected_claim_version": verified["version"]}, ADJUSTER)
        validate_error(resp, ApiErrorId.ERR_CHOICE_DISCLOSURE_REQUIRED)
        assert get_claim(claim["id"])["status"] == "COVERAGE_VERIFIED"

    def test_routing_succeeds_after_disclosure_recorded(self, api):
        """PRD §3.3: "The claim itself moves `COVERAGE_VERIFIED` →
        `WORK_AUTHORIZED`, its `assigned_shop_id` is set to the selected shop,
        and its `version` increments."

        Design: Difficulty/cross_entity_state_dependency/routing_decision_depends_on_disclosure_existence
        """
        net, claim, verified = self._setup_verified_no_disclosure()
        add_disclosure(claim["id"], net["policyholder"]["id"])
        wo = route_claim(claim["id"],
                         expected_claim_version=verified["version"])
        assert wo["status"] == "OFFERED"
        assert get_claim(claim["id"])["status"] == "WORK_AUTHORIZED"
