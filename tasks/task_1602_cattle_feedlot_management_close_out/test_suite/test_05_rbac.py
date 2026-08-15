"""Role-based access control: exclusive-operation denial, peer-role isolation,
and claim-payment segregation of duties."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_lot,
    create_owner,
    decide_claim,
    file_claim,
    make_claims_adjuster_headers,
    make_claims_treasurer_headers,
    record_death_loss,
    validate_error,
    validate_success,
)

FYM = TEST_USERS["feedyard_manager_headers"]
FM = TEST_USERS["feed_manager_headers"]
CHT = TEST_USERS["cattle_health_tech_headers"]


class TestExclusiveOperationDenial:
    def test_feed_manager_cannot_ship_lot(self, api):
        """PRD §2.1: "An attempt to perform an action outside the caller's
        designated role is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."
        PRD §4 endpoint table: "POST | `/feedlot/lots/{lotId}/ship` | Ship a
        marketed lot to the packer | FeedyardManager"
        PRD §2.8: the role authorization check (priority 2) is evaluated before
        state guards (priority 7).

        Design: Corner/rbac/feed_manager_cannot_ship_lot
        """
        owner = create_owner(owner_name="O-RB1", billing_email="rb1@x.com")
        lot = create_lot(owner["id"], lot_number="L-RB1", head_count_in=5,
                         in_weight_total_lbs=3500, purchase_cost_cents=700000)
        resp = api.ship_lot(
            lot["id"],
            {"ship_date": "2026-08-01", "out_weight_total_lbs": 3700},
            FM,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)

    def test_health_tech_cannot_create_ration(self, api):
        """PRD §2.1: "`FeedManager` (nutritionist and feed-truck dispatcher:
        rations, ration windows, daily feed calls)"
        PRD §2.1: "An attempt to perform an action outside the caller's
        designated role is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."

        Design: Corner/rbac/health_tech_cannot_create_ration
        """
        resp = api.create_ration(
            {"ration_name": "R-RB2", "step_level": 1,
             "cost_per_ton_cents": 20000},
            CHT,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)


class TestSegregationOfDuties:
    def test_sod_same_adjuster_cannot_pay_own_decision(self, api):
        """PRD §3.5: "Paying is open to both `ClaimsTreasurer` and
        `ClaimsAdjuster`, but the paying operator's `X-User-ID` must differ from
        the claim's `decided_by_user_id`; a payer who decided the claim is
        rejected with `ERR_SEGREGATION_OF_DUTIES_VIOLATION` (HTTP 403)."

        Design: Corner/rbac/sod_same_adjuster_cannot_pay_own_decision
        """
        owner = create_owner(owner_name="O-RB3", billing_email="rb3@x.com")
        lot = create_lot(owner["id"], lot_number="L-RB3", head_count_in=5,
                         in_weight_total_lbs=3500, purchase_cost_cents=700000)
        death_loss = record_death_loss(lot["id"], loss_date="2026-08-01",
                                       head_count=1, insured=True)
        claim = file_claim(death_loss["id"], 100000)
        decide_claim(claim["id"], "APPROVE", decider_user_id="adj-7")

        resp = api.pay_claim(claim["id"], make_claims_adjuster_headers("adj-7"))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES_VIOLATION)

        paid = validate_success(api.pay_claim(
            claim["id"], make_claims_treasurer_headers("tre-9")))
        assert paid["status"] == "PAID", (
            "A payer whose user id differs from the decider's satisfies the rule"
        )
