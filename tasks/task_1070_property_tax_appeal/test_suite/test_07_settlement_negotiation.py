"""Settlement offers: cyclic negotiation, accept precedence (SoD vs expiry), expiry, and OCC."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId, make_analyst_headers,
)
from test_helpers import fixtures as fx

_COMP_30M = [{"comp_address": "x", "sale_price_cents": 30000000,
              "comp_assessed_value_cents": 27000000, "adjustment_pct": 0.00}]


class TestCyclicSettlementRounds:
    """PROPOSED -> COUNTERED -> PROPOSED loop; round_number reaches 2 after one re-propose.
    Design: Difficulty/non_linear_state_machine/ni_settlement_offer_cyclic_rounds
    """

    def _filed_with_offer(self, api):
        ctx = fx.setup_filed_appeal(api, comps=_COMP_30M)
        offer = fx.add_offer(api, ctx["analyst_id"], ctx["appeal_id"], 25000000, proposed_by="FIRM")
        ctx["offer_id"] = offer["id"]
        return ctx

    def test_first_counter_moves_to_countered(self, api):
        """PRD §3.6: "Countering a `PROPOSED` offer records the supplied `offer_value_cents` as the new
        offer value and flips the `proposed_by` party between `FIRM` and `JURISDICTION`, moving the
        offer from `PROPOSED` to `COUNTERED`".

        Design: Difficulty/non_linear_state_machine/ni_settlement_offer_cyclic_rounds
        """
        ctx = self._filed_with_offer(api)
        offer = validate_success(api.counter_settlement_offer(
            ctx["offer_id"], {"offer_value_cents": 27000000}, make_analyst_headers(ctx["analyst_id"])))
        assert offer["status"] == "COUNTERED"

    def test_second_counter_reproposes_and_bumps_round(self, api):
        """PRD §3.6: "Countering a `COUNTERED` offer re-proposes the next round, moving it back from
        `COUNTERED` to `PROPOSED` and incrementing its `round_number` by 1".

        Design: Difficulty/non_linear_state_machine/ni_settlement_offer_cyclic_rounds
        """
        ctx = self._filed_with_offer(api)
        api.counter_settlement_offer(ctx["offer_id"], {"offer_value_cents": 27000000},
                                     make_analyst_headers(ctx["analyst_id"]))
        offer = validate_success(api.counter_settlement_offer(
            ctx["offer_id"], {"offer_value_cents": 26000000}, make_analyst_headers(ctx["analyst_id"])))
        assert offer["status"] == "PROPOSED"
        assert offer["round_number"] == 2


class TestAcceptSodBeatsExpiry:
    """Creator-accepts (SoD) AND expired -> ERR_SEGREGATION_OF_DUTIES (SoD checked before expiry).
    Design: Difficulty/priority_pair_validation_conflict/pp_sod_safety_beats_offer_expired_temporal
    """

    def _setup(self, api):
        ctx = fx.setup_filed_appeal(api, comps=_COMP_30M, two_analysts=True)
        offer = fx.add_offer(api, ctx["analyst_id"], ctx["appeal_id"], 26000000, proposed_by="FIRM",
                             expires_at="2026-07-05T00:00:00Z")
        ctx["offer_id"] = offer["id"]
        fx.set_clock(api, "2026-07-10T00:00:00Z")
        return ctx

    def test_creator_accept_expired_offer_returns_sod(self, api):
        """PRD §3.6: "the accepting analyst's `X-User-ID` must differ from the offer's
        `created_by_analyst_id`, enforcing segregation of duties — an attempt by the offer's own creator
        is rejected with `ERR_SEGREGATION_OF_DUTIES`; and the current logical clock must not be past the
        offer's `expires_at`, or the acceptance is rejected with `ERR_OFFER_EXPIRED`."

        Design: Difficulty/priority_pair_validation_conflict/pp_sod_safety_beats_offer_expired_temporal
        """
        ctx = self._setup(api)
        resp = api.accept_settlement_offer(ctx["offer_id"], make_analyst_headers(ctx["analyst_id"]))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)

    def test_offer_stays_proposed_after_rejected_accept(self, api):
        """PRD §3.6: "On acceptance the offer moves from `PROPOSED` to `ACCEPTED`". A rejected accept
        leaves the offer in `PROPOSED`.

        Design: Difficulty/priority_pair_validation_conflict/pp_sod_safety_beats_offer_expired_temporal
        """
        ctx = self._setup(api)
        api.accept_settlement_offer(ctx["offer_id"], make_analyst_headers(ctx["analyst_id"]))
        offer = validate_success(api.get_settlement_offer(ctx["offer_id"], make_analyst_headers(ctx["analyst_id"])))
        assert offer["status"] == "PROPOSED"


def test_accept_expired_offer_by_other_analyst_returns_offer_expired(api):
    """PRD §3.6: "the current logical clock must not be past the offer's `expires_at`, or the
    acceptance is rejected with `ERR_OFFER_EXPIRED`." A DIFFERENT analyst accepts (SoD passes), so the
    expiry check is the one that fires.

    Design: Corner/errors/corner_err_offer_expired_stub
    """
    ctx = fx.setup_filed_appeal(api, comps=_COMP_30M, two_analysts=True)
    offer = fx.add_offer(api, ctx["analyst_id"], ctx["appeal_id"], 26000000, proposed_by="FIRM",
                         expires_at="2026-07-05T00:00:00Z")
    fx.set_clock(api, "2026-07-10T00:00:00Z")
    resp = api.accept_settlement_offer(offer["id"], make_analyst_headers(ctx["analyst2_id"]))
    validate_error(resp, ApiErrorId.ERR_OFFER_EXPIRED.value)


def test_stale_expected_appeal_version_on_offer_create_rejected(api):
    """PRD §2.7: "If `expected_appeal_version` does not equal the appeal's current `version`, the
    request is rejected with `ERR_STALE_APPEAL_VERSION` (HTTP 412). Because each successful offer
    creation itself increments the parent appeal's `version` by 1 ... a second create that still carries
    the earlier, now-stale `expected_appeal_version` is refused".

    Design: Corner/cross_cutting_complexity_layers/corner_occ_stale_appeal_version_conflict
    """
    ctx = fx.setup_filed_appeal(api, comps=_COMP_30M)
    av = fx.appeal_version(api, ctx["analyst_id"], ctx["appeal_id"])
    fx.add_offer(api, ctx["analyst_id"], ctx["appeal_id"], 26000000, expected_version=av)  # bumps version
    from test_helpers import create_settlement_offer_payload
    resp = api.create_settlement_offer(
        ctx["appeal_id"], create_settlement_offer_payload(25000000, av, "FIRM"),
        make_analyst_headers(ctx["analyst_id"]))
    validate_error(resp, ApiErrorId.ERR_STALE_APPEAL_VERSION.value)


def test_offer_create_increments_appeal_version(api):
    """PRD §2.7: "a successful create increments the parent appeal's `version` by 1."

    Design: Corner/cross_cutting_complexity_layers/corner_occ_version_increments_on_offer_create
    """
    ctx = fx.setup_filed_appeal(api, comps=_COMP_30M)
    av = fx.appeal_version(api, ctx["analyst_id"], ctx["appeal_id"])
    offer = fx.add_offer(api, ctx["analyst_id"], ctx["appeal_id"], 26000000, expected_version=av)
    assert offer["status"] == "PROPOSED"
    new_version = fx.appeal_version(api, ctx["analyst_id"], ctx["appeal_id"])
    assert new_version == av + 1
