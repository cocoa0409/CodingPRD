"""Quota availability: committed vs conservative variants, conservation across
propose/withdraw, and fiscal/constraint gates on transfer creation
(PRD §3.2, §3.7)."""
from test_helpers import (
    TEST_USERS,
    api_client,
    create_quota_transfer_payload,
    get_availability,
    make_vessel_owner_headers,
    propose_transfer,
    setup_transfer_pair,
    setup_vessel_ready,
    validate_error,
    validate_success,
)

REG = TEST_USERS["regulator_headers"]


class TestDualVariantAvailability:
    def test_open_offer_diverges_availability_variants(self):
        """PRD §3.2: "The **committed** figure, `available_committed_pounds`, is the
        holding's `initial_pounds` minus its `landed_pounds`, plus pounds leased in,
        minus pounds leased out — where leased amounts count only transfers in
        `ACCEPTED` or `SETTLED` status matching the holding's vessel side,
        `fishery_code`, and `season_year`. The **conservative** figure,
        `available_conservative_pounds`, additionally subtracts the vessel's outgoing
        offers still in negotiation — transfers in `PROPOSED` or `COUNTERED` for the
        same fishery and year".

        Design: Difficulty/dual_variant_calc/quota_committed_vs_conservative_divergence
        """
        ctx = setup_transfer_pair(holding1_pounds=20000, holding2_pounds=5000)
        propose_transfer(ctx["v1"]["id"], ctx["v2"]["id"], pounds=5000,
                         price_per_lb_cents=400)
        availability = get_availability(ctx["h1"]["id"])
        assert availability["available_committed_pounds"] == 20000, (
            f"committed must ignore the open PROPOSED offer, got "
            f"{availability['available_committed_pounds']}")
        assert availability["available_conservative_pounds"] == 15000, (
            f"conservative must subtract the 5000-lb open offer, got "
            f"{availability['available_conservative_pounds']}")
        assert (availability["available_committed_pounds"]
                - availability["available_conservative_pounds"]) == 5000

    def test_accepted_offer_converges_availability_variants(self):
        """PRD §3.2: "with identical inputs the conservative figure is lower than the
        committed figure whenever open offers exist" — once the offer is ACCEPTED it
        counts in both variants, so the divergence closes. PRD §3.7: "Acceptance moves
        the transfer to `ACCEPTED` and posts the reservation: the from-side holding's
        leased-out total increases by `pounds`".

        Design: Difficulty/dual_variant_calc/quota_committed_vs_conservative_divergence
        """
        ctx = setup_transfer_pair(holding1_pounds=20000, holding2_pounds=5000)
        transfer = propose_transfer(ctx["v1"]["id"], ctx["v2"]["id"], pounds=5000,
                                    price_per_lb_cents=400)
        accepted = validate_success(api_client.accept_quota_transfer(
            transfer["id"], make_vessel_owner_headers(ctx["v2"]["id"])), 200)
        assert accepted["status"] == "ACCEPTED"
        availability = get_availability(ctx["h1"]["id"])
        assert availability["available_committed_pounds"] == 15000
        assert availability["available_conservative_pounds"] == 15000, (
            "with no open offers the two variants must agree")
        assert availability["leased_out_pounds"] == 5000
        to_side = get_availability(ctx["h2"]["id"])
        assert to_side["leased_in_pounds"] == 5000
        assert to_side["available_committed_pounds"] == 10000


class TestConservationAcrossProposeWithdraw:
    def test_propose_drops_only_conservative_availability(self):
        """PRD §3.2: the conservative figure "additionally subtracts the vessel's
        outgoing offers still in negotiation — transfers in `PROPOSED` or `COUNTERED`
        for the same fishery and year — so a vessel cannot over-commit while offers
        are open", while the committed figure counts "only transfers in `ACCEPTED` or
        `SETTLED` status".

        Design: Difficulty/compensating_invariant/quota_conserved_across_propose_withdraw
        """
        ctx = setup_transfer_pair(holding1_pounds=20000, holding2_pounds=5000)
        before = get_availability(ctx["h1"]["id"])
        assert before["available_committed_pounds"] == 20000
        assert before["available_conservative_pounds"] == 20000
        propose_transfer(ctx["v1"]["id"], ctx["v2"]["id"], pounds=5000)
        mid = get_availability(ctx["h1"]["id"])
        assert mid["available_committed_pounds"] == 20000, (
            "an open offer must not move the committed figure")
        assert mid["available_conservative_pounds"] == 15000

    def test_withdraw_restores_conservative_availability(self):
        """PRD §3.7: "Withdrawing is the mirror image: available only to the side
        that tabled the current offer — the `last_offered_by` side — from the same
        two statuses, moving the transfer to `WITHDRAWN`; either move by the wrong
        side is `ERR_TRANSFER_OWN_OFFER`, and either from a closed status is
        `ERR_TRANSFER_NOT_OPEN`." Once no offer is open, the §3.2 conservative
        subtraction no longer applies.

        Design: Difficulty/compensating_invariant/quota_conserved_across_propose_withdraw
        """
        ctx = setup_transfer_pair(holding1_pounds=20000, holding2_pounds=5000)
        transfer = propose_transfer(ctx["v1"]["id"], ctx["v2"]["id"], pounds=5000)
        withdrawn = validate_success(api_client.withdraw_quota_transfer(
            transfer["id"], make_vessel_owner_headers(ctx["v1"]["id"])), 200)
        assert withdrawn["status"] == "WITHDRAWN"
        after = get_availability(ctx["h1"]["id"])
        assert after["available_committed_pounds"] == 20000
        assert after["available_conservative_pounds"] == 20000, (
            "withdrawing the only open offer must restore conservative availability")


class TestTransferCreationGates:
    def test_transfer_aggregate_overcommit_rejected(self):
        """PRD §3.7: "the leasing-out vessel's `available_conservative_pounds` must
        cover `pounds` (`ERR_QUOTA_EXCEEDED`)"; PRD §3.2: the conservative figure
        subtracts outgoing offers still in negotiation, "so a vessel cannot
        over-commit while offers are open".

        Design: Corner/validations/transfer_aggregate_overcommit_rejected
        """
        ctx = setup_transfer_pair(holding1_pounds=10000, holding2_pounds=5000)
        propose_transfer(ctx["v1"]["id"], ctx["v2"]["id"], pounds=6000)
        resp = api_client.create_quota_transfer(
            create_quota_transfer_payload(
                from_vessel_id=ctx["v1"]["id"], to_vessel_id=ctx["v2"]["id"],
                pounds=6000, price_per_lb_cents=400),
            make_vessel_owner_headers(ctx["v1"]["id"]))
        validate_error(resp, "ERR_QUOTA_EXCEEDED", 402)
        # Committed still shows 10000: only the conservative variant gates creation.
        assert get_availability(ctx["h1"]["id"])["available_committed_pounds"] == 10000

    def test_self_transfer_rejected(self):
        """PRD §3.7: "A lease from a vessel to itself is rejected with
        `ERR_SELF_TRANSFER` (HTTP 422)."

        Design: Corner/validations/self_transfer_rejected
        """
        ctx = setup_vessel_ready(holding_pounds=20000)
        vessel_id = ctx["vessel"]["id"]
        resp = api_client.create_quota_transfer(
            create_quota_transfer_payload(
                from_vessel_id=vessel_id, to_vessel_id=vessel_id,
                pounds=100, price_per_lb_cents=100),
            make_vessel_owner_headers(vessel_id))
        validate_error(resp, "ERR_SELF_TRANSFER", 422)
