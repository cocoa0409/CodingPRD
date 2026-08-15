"""Deal negotiation, activation, fee pinning, and exclusivity (PRD §3.4)."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_deal,
    assert_instant_equals,
    get_deal,
    make_accepted_deal,
    make_active_creator,
    make_active_deal,
    make_brand,
    make_brand_headers,
    make_creator_headers,
    make_open_brief,
    make_pending_brand_deal,
    make_pitch,
    propose_terms,
    propose_terms_payload,
    set_clock,
    shortlist_pitch,
    accept_pitch,
    validate_error,
    validate_success,
)

TM = TEST_USERS["talent_manager_headers"]
BM = TEST_USERS["brand_manager_headers"]


class TestDealNegotiationCycle:
    def test_counter_cycle_reaches_active_with_counters_intact(self, api):
        """PRD §3.4: "A `COUNTER`, carrying `counter_fee_cents`, returns the
        deal to `DRAFT` and consumes one of four allowed deal-negotiation
        rounds — a counter beyond that cap is rejected with
        `ERR_NEGOTIATION_LIMIT_EXCEEDED` — leaving the next proposal to set
        the new `fee_base_cents`."
        PRD §3.4: "A brand `COUNTER` from `PENDING_BRAND` likewise returns
        the deal to `DRAFT` under the same four-round cap"
        PRD §3.4: "The proposal moves the deal from `DRAFT` to
        `PENDING_CREATOR`, records the fee, and increments `terms_version`"

        After one creator counter and one brand counter the cyclic deal still
        reaches ACTIVE with negotiation_rounds == 2, terms_version == 3, and
        the last proposed fee_base_cents == 110000.

        Design: Difficulty/non_linear_state_machine/deal_negotiation_counter_cycle
        """
        ns = make_accepted_deal(proposed_fee_cents=100000)
        deal_id = ns.deal_id
        c_id, b_id = ns.creator["id"], ns.brand["id"]

        propose_terms(deal_id, 100000)  # terms_version 1
        validate_success(api.creator_respond(
            deal_id, {"action": "COUNTER", "counter_fee_cents": 120000},
            make_creator_headers(c_id)))
        propose_terms(deal_id, 120000)  # terms_version 2
        validate_success(api.creator_respond(
            deal_id, {"action": "ACCEPT"}, make_creator_headers(c_id)))
        validate_success(api.brand_respond(
            deal_id, {"action": "COUNTER"}, make_brand_headers(b_id)))
        propose_terms(deal_id, 110000)  # terms_version 3
        validate_success(api.creator_respond(
            deal_id, {"action": "ACCEPT"}, make_creator_headers(c_id)))
        validate_success(api.brand_respond(
            deal_id, {"action": "ACCEPT"}, make_brand_headers(b_id)))

        deal = validate_success(api.get_deal(deal_id, BM))
        assert_deal(deal)
        assert deal["status"] == "ACTIVE", "deal reached ACTIVE after two loops"
        assert deal["negotiation_rounds"] == 2
        assert deal["terms_version"] == 3
        assert deal["fee_base_cents"] == 110000

    def test_counter_returns_deal_to_draft_each_time(self, api):
        """PRD §3.4: "A `COUNTER`, carrying `counter_fee_cents`, returns the
        deal to `DRAFT` and consumes one of four allowed deal-negotiation
        rounds"
        PRD §3.4: "The proposal moves the deal from `DRAFT` to
        `PENDING_CREATOR`, records the fee, and increments `terms_version` —
        the counter that pins exactly which generation of terms each party
        later accepted, since every proposal bumps it."

        Each COUNTER loops the deal back to DRAFT; each fresh proposal bumps
        terms_version without touching negotiation_rounds.

        Design: Difficulty/non_linear_state_machine/deal_negotiation_counter_cycle
        """
        ns = make_accepted_deal(proposed_fee_cents=100000)
        deal_id = ns.deal_id
        c_id, b_id = ns.creator["id"], ns.brand["id"]

        proposed = propose_terms(deal_id, 100000)
        assert proposed["status"] == "PENDING_CREATOR"
        assert proposed["terms_version"] == 1
        assert proposed["negotiation_rounds"] == 0

        countered = validate_success(api.creator_respond(
            deal_id, {"action": "COUNTER", "counter_fee_cents": 120000},
            make_creator_headers(c_id)))
        assert countered["status"] == "DRAFT", "creator counter loops to DRAFT"
        assert countered["negotiation_rounds"] == 1

        proposed2 = propose_terms(deal_id, 120000)
        assert proposed2["terms_version"] == 2, "every proposal bumps terms_version"
        validate_success(api.creator_respond(
            deal_id, {"action": "ACCEPT"}, make_creator_headers(c_id)))
        countered2 = validate_success(api.brand_respond(
            deal_id, {"action": "COUNTER"}, make_brand_headers(b_id)))
        assert countered2["status"] == "DRAFT", "brand counter loops to DRAFT"
        assert countered2["negotiation_rounds"] == 2


class TestDealFeeComputation:
    def _setup_pending_brand_big_deal(self):
        """TECH creator 250k followers / 450bps / 80k views (flat 331,200);
        brief dps=3, usage 120d, whitelisting, exclusivity SOFTWARE 30d."""
        return make_pending_brand_deal(
            creator_overrides={
                "handle": "crb3", "niche": "TECH", "followers": 250000,
                "avg_views_30d": 80000, "engagement_rate_bps": 450,
            },
            brief_overrides={
                "niche": "TECH", "deliverables_per_slot": 3,
                "usage_rights_days": 120, "exclusivity_category": "SOFTWARE",
                "exclusivity_days": 30, "whitelisting_required": True,
            },
            fee_base_cents=100000,
        )

    def test_fee_total_pinned_by_fixed_sequence(self, api):
        """PRD §3.4: "First, the base sum is the creator's current
        `rate_card_flat_cents` multiplied by the brief's
        `deliverables_per_slot`. Second, when `deliverables_per_slot` is three
        or more, a ten-percent multi-deliverable discount applies ... Third,
        the usage add-on tiers on `usage_rights_days` ... Fourth, when the
        deal's `whitelisting` is set, a whitelisting add-on of 75,000 cents
        per deliverable applies ... Sixth, the exclusivity uplift: zero when
        `exclusivity_category` is `NONE`; otherwise five percent when the
        subtotal is below 500,000 cents, twelve percent when it is below
        2,000,000 cents, and twenty percent at 2,000,000 cents or more — the
        tier keyed on the subtotal that already includes both add-ons ...
        Finally, `fee_total_cents` is the subtotal multiplied by one plus the
        uplift percentage, rounded half up to whole cents."

        331,200x3 = 993,600; x0.90 = 894,240; usage +25% = 223,560;
        whitelisting +225,000; S = 1,342,800; uplift 12% -> 1,503,936.

        Design: Difficulty/combinatorial_formula/deal_fee_exclusivity_uplift_order
        """
        ns = self._setup_pending_brand_big_deal()
        res = api.brand_respond(ns.deal_id, {"action": "ACCEPT"},
                                make_brand_headers(ns.brand["id"]))
        deal = validate_success(res, 200)
        assert deal["status"] == "ACTIVE"
        assert deal["fee_total_cents"] == 1503936, (
            f"pinned fee_total must follow the fixed sequence; got "
            f"{deal['fee_total_cents']}"
        )
        assert deal["fee_base_cents"] == 100000, (
            "the negotiated fee_base_cents remains recorded as the audit "
            "reference"
        )

    def test_activation_stamps_exclusivity_window(self, api):
        """PRD §3.4: "Activation also stamps `activated_at` from the logical
        clock, sets `exclusive_window_start` to that same instant, and sets
        `exclusive_window_end` to `activated_at` plus `exclusivity_days` —
        both window fields remaining null when the category is `NONE`."
        PRD §2.5: "At startup the logical clock reads exactly
        2026-08-01T00:00:00Z"

        Design: Difficulty/combinatorial_formula/deal_fee_exclusivity_uplift_order
        """
        ns = self._setup_pending_brand_big_deal()
        res = api.brand_respond(ns.deal_id, {"action": "ACCEPT"},
                                make_brand_headers(ns.brand["id"]))
        deal = validate_success(res, 200)
        assert_instant_equals(deal["activated_at"], "2026-08-01T00:00:00Z")
        assert_instant_equals(
            deal["exclusive_window_start"], "2026-08-01T00:00:00Z"
        )
        assert_instant_equals(
            deal["exclusive_window_end"], "2026-08-31T00:00:00Z"
        )


class TestExclusivityOverlap:
    def _setup_two_fintech_deals(self):
        """One ACTIVE creator; two brands each with an OPEN FINTECH brief
        (exclusivity 30 days); both deals negotiated to PENDING_BRAND."""
        creator = make_active_creator(handle="cro1", niche="FINANCE")
        brand_a = make_brand(name="BA", industry="FINANCE")
        brand_b = make_brand(name="BB", industry="FINANCE")
        brief_kw = {
            "niche": "FINANCE", "usage_rights_days": 30,
            "exclusivity_category": "FINTECH", "exclusivity_days": 30,
            "content_window_end": "2026-10-31T23:59:59Z",
        }
        brief_a = make_open_brief(brand_a["id"], title="A", **brief_kw)
        brief_b = make_open_brief(brand_b["id"], title="B", **brief_kw)
        p1 = make_pitch(brief_a.brief["id"], creator["id"],
                        proposed_fee_cents=100000, concept_note="a",
                        expected_brief_version=brief_a.version)
        p2 = make_pitch(brief_b.brief["id"], creator["id"],
                        proposed_fee_cents=100000, concept_note="b",
                        expected_brief_version=brief_b.version)
        shortlist_pitch(p1["id"])
        d1 = accept_pitch(p1["id"])["deal_id"]
        shortlist_pitch(p2["id"])
        d2 = accept_pitch(p2["id"])["deal_id"]
        propose_terms(d1, 100000)
        propose_terms(d2, 100000)
        return creator, brand_a, brand_b, d1, d2

    def test_overlapping_activation_rejected(self, api):
        """PRD §3.4: "Activation is rejected with `ERR_EXCLUSIVITY_CONFLICT`
        when any other deal with the same `creator_id` is `ACTIVE` in the
        same non-`NONE` `exclusivity_category` and its exclusivity window
        overlaps the candidate window this activation would open."

        Deal A activated at 2026-08-05 occupies [2026-08-05, 2026-09-04);
        deal B's activation at 2026-09-01 overlaps and is rejected.

        Design: Difficulty/resource_temporal_overlap/exclusivity_half_open_overlap
        """
        creator, brand_a, brand_b, d1, d2 = self._setup_two_fintech_deals()
        validate_success(api.creator_respond(
            d1, {"action": "ACCEPT"}, make_creator_headers(creator["id"])))
        validate_success(api.creator_respond(
            d2, {"action": "ACCEPT"}, make_creator_headers(creator["id"])))

        set_clock("2026-08-05T00:00:00Z")
        deal_a = validate_success(api.brand_respond(
            d1, {"action": "ACCEPT"}, make_brand_headers(brand_a["id"])))
        assert deal_a["status"] == "ACTIVE"
        assert_instant_equals(
            deal_a["exclusive_window_start"], "2026-08-05T00:00:00Z"
        )
        assert_instant_equals(
            deal_a["exclusive_window_end"], "2026-09-04T00:00:00Z"
        )

        set_clock("2026-09-01T00:00:00Z")
        res = api.brand_respond(d2, {"action": "ACCEPT"},
                                make_brand_headers(brand_b["id"]))
        validate_error(res, ApiErrorId.ERR_EXCLUSIVITY_CONFLICT, 409)
        deal_b = get_deal(d2)
        assert deal_b["status"] == "PENDING_BRAND", (
            "rejected activation leaves the deal PENDING_BRAND"
        )

    def test_adjacent_activation_at_window_end_allowed(self, api):
        """PRD §3.4: "Every exclusivity window is a half-open interval that
        includes its `exclusive_window_start` instant and excludes its
        `exclusive_window_end` instant, so two windows that merely touch —
        one ending exactly when the other begins — do not conflict."

        Activating deal B at exactly 2026-09-04 (deal A's window end) is
        allowed.

        Design: Difficulty/resource_temporal_overlap/exclusivity_half_open_overlap
        """
        creator, brand_a, brand_b, d1, d2 = self._setup_two_fintech_deals()
        validate_success(api.creator_respond(
            d1, {"action": "ACCEPT"}, make_creator_headers(creator["id"])))
        validate_success(api.creator_respond(
            d2, {"action": "ACCEPT"}, make_creator_headers(creator["id"])))

        set_clock("2026-08-05T00:00:00Z")
        validate_success(api.brand_respond(
            d1, {"action": "ACCEPT"}, make_brand_headers(brand_a["id"])))
        set_clock("2026-09-04T00:00:00Z")
        deal_b = validate_success(api.brand_respond(
            d2, {"action": "ACCEPT"}, make_brand_headers(brand_b["id"])))
        assert deal_b["status"] == "ACTIVE", (
            "half-open adjacency (end == start) is not a conflict"
        )
        assert_instant_equals(
            deal_b["exclusive_window_start"], "2026-09-04T00:00:00Z"
        )


class TestActivationGates:
    def test_brand_credit_hold_blocks_activation(self, api):
        """PRD §3.2: "When `credit_hold` is true — it starts false — two
        operations are blocked with `ERR_BRAND_CREDIT_HOLD` (HTTP 402):
        publishing a brief and activating a deal."
        PRD §3.4: "then the credit-hold check, which rejects with
        `ERR_BRAND_CREDIT_HOLD` when the brand's `credit_hold` is true."

        Design: Corner/validations/brand_credit_hold_blocks_activation
        """
        ns = make_pending_brand_deal(fee_base_cents=90000)
        validate_success(
            api.patch_brand(ns.brand["id"], {"credit_hold": True}, BM)
        )
        res = api.brand_respond(ns.deal_id, {"action": "ACCEPT"},
                                make_brand_headers(ns.brand["id"]))
        validate_error(res, ApiErrorId.ERR_BRAND_CREDIT_HOLD, 402)
        deal = get_deal(ns.deal_id)
        assert deal["status"] == "PENDING_BRAND"

    def test_deal_respond_forbidden_for_non_owner_creator(self, api):
        """PRD §2.1: "When `X-User-Role` is `Creator`, the `X-User-ID` value
        is the `id` of the acting Creator record; ownership checks on any
        resource that references a creator compare the resource's
        `creator_id` field against `X-User-ID`."
        PRD §2.1: "An entity-backed caller that attempts to act on a resource
        it does not own is rejected with `ERR_FORBIDDEN`."
        PRD §3.4: "The creator answers first through an `action` of `ACCEPT`,
        `COUNTER`, or `DECLINE`, and must be the deal's own creator: the
        acting `X-User-ID` must equal the deal's `creator_id`."

        Design: Corner/rbac/deal_respond_forbidden_for_non_owner_creator
        """
        ns = make_accepted_deal(proposed_fee_cents=90000)
        intruder = make_active_creator(handle="cr2-intruder")
        propose_terms(ns.deal_id, 90000)
        res = api.creator_respond(
            ns.deal_id, {"action": "ACCEPT"},
            make_creator_headers(intruder["id"]),
        )
        validate_error(res, ApiErrorId.ERR_FORBIDDEN, 403)
        deal = get_deal(ns.deal_id)
        assert deal["status"] == "PENDING_CREATOR"

    def test_deal_propose_terms_stale_version_rejected(self, api):
        """PRD §2.7: "Proposing deal terms requires `expected_deal_version`,
        carrying the deal's current `version` as last observed by the caller.
        A new proposal supersedes the prior draft terms, so a stale writer
        would overwrite terms the counterparty may already have read. A
        mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412)."
        PRD §2.8: "6. Optimistic concurrency: the `expected_brief_version` or
        `expected_deal_version` matches the parent's current `version` (else
        `ERR_STALE_VERSION`)."

        The stale proposal is rejected even though the deal also left DRAFT
        (concurrency is checked before state preconditions).

        Design: Corner/cross_cutting_layers/deal_propose_terms_stale_version_rejected
        """
        ns = make_accepted_deal(proposed_fee_cents=90000)
        deal = get_deal(ns.deal_id)
        stale_version = deal["version"]
        propose_terms(ns.deal_id, 90000)  # bumps deal.version
        res = api.propose_terms(
            ns.deal_id,
            propose_terms_payload(95000, stale_version),
            BM,
        )
        validate_error(res, ApiErrorId.ERR_STALE_VERSION, 412)
        after = get_deal(ns.deal_id)
        assert after["terms_version"] == 1, "stale proposal did not apply"
        assert after["fee_base_cents"] == 90000
