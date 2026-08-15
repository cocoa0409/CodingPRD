"""Estoppel certificates: the deficiency negotiation loop, from-state
enforcement, and the 50-basis-point rent-tolerance boundary."""
from test_helpers import (
    ApiErrorId,
    create_estoppel_payload,
    setup_psa_executed,
    validate_error,
    validate_success,
)


def _setup_cycle_deal(deal_name="CycleDeal"):
    """Deal at PSA_EXECUTED with one VERIFIED lease at rent 1,200,000."""
    return setup_psa_executed(
        deal_name=deal_name, purchase_price_cents=20000000,
        earnest_money_cents=300000, lease_rent_cents=1200000,
        lease_expiration="2034-01-01T00:00:00Z",
        dd_period_days=45, financing_contingency_days=30,
        property_overrides={"address": "1 Cycle Way", "rentable_sqft": 10000,
                            "year_built": 2012},
        tenant_overrides={"legal_name": "CycleTenant", "credit_score": 750,
                          "annual_revenue_cents": 50000000})


class TestEstoppelNegotiationCycle:
    def test_failed_certify_marks_deficient_and_returns_lease_to_verified(
            self, api, dd_officer_headers):
        """PRD §3.8: "A wider deviation is rejected with
        `ERR_ESTOPPEL_RENT_MISMATCH` (HTTP 422)."
        PRD §3.8: "A failed certification attempt does not vanish: the
        certificate is recorded `DEFICIENT` with its `deficiency_reason`
        populated for audit, and the lease falls back from
        `ESTOPPEL_PENDING` to `VERIFIED` so a new certificate can be
        requested."

        Design: Difficulty/non_linear_state_machine/lease_estoppel_negotiation_cycle_on_lease_entity
        """
        ctx = _setup_cycle_deal()
        deal_id = ctx["deal"]["id"]
        lease_id = ctx["lease"]["id"]
        prop_id = ctx["property"]["id"]

        # Rent 1,300,000 vs lease 1,200,000: ~833 bps, far over tolerance.
        est1 = validate_success(api.create_estoppel(
            deal_id,
            create_estoppel_payload(lease_id, ctx["tenant"]["id"],
                                    rent_confirmed_cents=1300000),
            dd_officer_headers), 201)
        validate_success(api.receive_estoppel(deal_id, est1["id"],
                                              dd_officer_headers))
        lease_mid = validate_success(api.get_lease(
            deal_id, prop_id, lease_id, dd_officer_headers))
        assert lease_mid["status"] == "ESTOPPEL_PENDING", (
            "Receipt of the certificate pulls the lease into "
            "ESTOPPEL_PENDING")

        failed = api.certify_estoppel(deal_id, est1["id"], dd_officer_headers)
        validate_error(failed, ApiErrorId.ERR_ESTOPPEL_RENT_MISMATCH)

        est1_after = validate_success(api.get_estoppel(deal_id, est1["id"],
                                                       dd_officer_headers))
        assert est1_after["status"] == "DEFICIENT"
        assert isinstance(est1_after.get("deficiency_reason"), str) \
            and est1_after["deficiency_reason"], (
                "The failed certification is recorded with a reason")

        lease_after = validate_success(api.get_lease(
            deal_id, prop_id, lease_id, dd_officer_headers))
        assert lease_after["status"] == "VERIFIED", (
            "The lease falls back to VERIFIED for a fresh request round")

    def test_second_estoppel_after_deficiency_certifies_and_estoppels_lease(
            self, api, dd_officer_headers):
        """PRD §3.2: "a deficient certificate returns it to `VERIFIED` so a
        fresh certificate can be requested"
        PRD §3.8: "Successful certification moves the certificate to
        `CERTIFIED`, the lease to `ESTOPPELED`, and rechecks the
        `ESTOPPEL_COLLECTION` milestone"

        Design: Difficulty/non_linear_state_machine/lease_estoppel_negotiation_cycle_on_lease_entity
        """
        ctx = _setup_cycle_deal()
        deal_id = ctx["deal"]["id"]
        lease_id = ctx["lease"]["id"]
        prop_id = ctx["property"]["id"]

        # Round 1: out-of-tolerance rent -> DEFICIENT, lease back to VERIFIED.
        est1 = validate_success(api.create_estoppel(
            deal_id,
            create_estoppel_payload(lease_id, ctx["tenant"]["id"],
                                    rent_confirmed_cents=1300000),
            dd_officer_headers), 201)
        validate_success(api.receive_estoppel(deal_id, est1["id"],
                                              dd_officer_headers))
        validate_error(api.certify_estoppel(deal_id, est1["id"],
                                            dd_officer_headers),
                       ApiErrorId.ERR_ESTOPPEL_RENT_MISMATCH)

        # Round 2: matching rent -> CERTIFIED, lease ESTOPPELED.
        est2 = validate_success(api.create_estoppel(
            deal_id,
            create_estoppel_payload(lease_id, ctx["tenant"]["id"],
                                    rent_confirmed_cents=1200000),
            dd_officer_headers), 201)
        validate_success(api.receive_estoppel(deal_id, est2["id"],
                                              dd_officer_headers))
        certified = validate_success(api.certify_estoppel(deal_id, est2["id"],
                                                          dd_officer_headers))
        assert certified["status"] == "CERTIFIED"

        lease_final = validate_success(api.get_lease(
            deal_id, prop_id, lease_id, dd_officer_headers))
        assert lease_final["status"] == "ESTOPPELED", (
            "The negotiation cycle ends with the lease ESTOPPELED")


class TestEstoppelFromState:
    def test_estoppel_certify_invalid_from_requested(
            self, api, dd_officer_headers):
        """PRD §3.8: "The certificate starts `REQUESTED`. Receipt by the
        officer moves it to `RECEIVED`"
        PRD §3.8: "Wrong-state transitions are `ERR_ESTOPPEL_INVALID_STATE`."

        Design: Corner/state_machines/estoppel_certify_invalid_from_requested
        """
        ctx = setup_psa_executed(deal_name="EstStateDeal")
        deal_id = ctx["deal"]["id"]
        estoppel = validate_success(api.create_estoppel(
            deal_id,
            create_estoppel_payload(ctx["lease"]["id"], ctx["tenant"]["id"],
                                    rent_confirmed_cents=1000000),
            dd_officer_headers), 201)
        assert estoppel["status"] == "REQUESTED"

        resp = api.certify_estoppel(deal_id, estoppel["id"],
                                    dd_officer_headers)
        validate_error(resp, ApiErrorId.ERR_ESTOPPEL_INVALID_STATE)


class TestEstoppelRentToleranceBoundary:
    def _setup_tolerance_deal(self):
        return setup_psa_executed(
            deal_name="TolDeal", lease_rent_cents=1200000,
            dd_period_days=45, financing_contingency_days=0,
            property_overrides={"address": "1 Tol St"},
            tenant_overrides={"legal_name": "TolT"})

    def test_certify_at_exactly_50_bps_passes(self, api,
                                              dd_officer_headers):
        """PRD §3.8: "the absolute difference between `rent_confirmed_cents`
        and the lease rent, multiplied by ten thousand and divided by the
        lease rent, must be no more than fifty basis points — the boundary is
        inclusive, so a deviation of exactly 50 basis points passes"

        Design: Corner/endpoints/estoppel_certify_conditional_action_rent_within_tolerance
        """
        ctx = self._setup_tolerance_deal()
        deal_id = ctx["deal"]["id"]
        # 6,000 / 1,200,000 = exactly 50 bps.
        estoppel = validate_success(api.create_estoppel(
            deal_id,
            create_estoppel_payload(ctx["lease"]["id"], ctx["tenant"]["id"],
                                    rent_confirmed_cents=1206000),
            dd_officer_headers), 201)
        validate_success(api.receive_estoppel(deal_id, estoppel["id"],
                                              dd_officer_headers))
        certified = validate_success(api.certify_estoppel(
            deal_id, estoppel["id"], dd_officer_headers))
        assert certified["status"] == "CERTIFIED", (
            "A deviation of exactly 50 basis points passes (inclusive)")

    def test_certify_one_cent_past_50_bps_fails(self, api,
                                                dd_officer_headers):
        """PRD §3.8: "A wider deviation is rejected with
        `ERR_ESTOPPEL_RENT_MISMATCH` (HTTP 422)."

        Design: Corner/endpoints/estoppel_certify_conditional_action_rent_within_tolerance
        """
        ctx = self._setup_tolerance_deal()
        deal_id = ctx["deal"]["id"]
        # 6,001 / 1,200,000 = 50.0083 bps — over the tolerance.
        estoppel = validate_success(api.create_estoppel(
            deal_id,
            create_estoppel_payload(ctx["lease"]["id"], ctx["tenant"]["id"],
                                    rent_confirmed_cents=1206001),
            dd_officer_headers), 201)
        validate_success(api.receive_estoppel(deal_id, estoppel["id"],
                                              dd_officer_headers))
        resp = api.certify_estoppel(deal_id, estoppel["id"],
                                    dd_officer_headers)
        validate_error(resp, ApiErrorId.ERR_ESTOPPEL_RENT_MISMATCH)
