"""Gift & hospitality registry: FX rounding, rolling window, caps, void repair."""
import pytest

from test_helpers import (
    ApiErrorId,
    advance_to_dd_review,
    approve_gift,
    create_approved_gift,
    create_draft_third_party,
    create_gift,
    get_third_party,
    officer_headers,
    set_clock,
    setup_risk_basis,
    setup_third_party_in_state,
    sponsor_headers,
    validate_error,
    validate_success,
)


class TestPerEntryRounding:
    """Per-entry round-half-up before summation: 3333 x 1.005 rounds to 3350 per
    entry; two entries sum to 6700 (sum-then-round would give 6699)."""

    def _setup_two_entries(self, api):
        ctx = setup_third_party_in_state("DD_REVIEW", "CH", 80, "LOGISTICS", "INDIRECT",
                                         legal_name="CH Logistics SA")
        tp_id = ctx["third_party"]["id"]
        g1 = create_gift(tp_id, entry_type="GIFT", value_cents=3333,
                         fx_rate_to_usd=1.005, event_date="2026-05-10")
        g2 = create_gift(tp_id, entry_type="HOSPITALITY", value_cents=3333,
                         fx_rate_to_usd=1.005, event_date="2026-05-10")
        return tp_id, g1, g2

    def test_per_entry_value_rounded_half_up(self, api):
        """PRD §3.8: "Each entry's `value_usd_cents` is computed individually at
        creation as the local value multiplied by the FX rate, rounded half-up to
        whole cents; aggregations always sum these per-entry rounded figures,
        never a sum-then-round of raw values."

        Design: Difficulty/combinatorial_formula/gift_rolling_total_per_entry_rounding
        """
        _, g1, g2 = self._setup_two_entries(api)
        assert g1["value_usd_cents"] == 3350, "round_half_up(3333 x 1.005) == 3350"
        assert g2["value_usd_cents"] == 3350

    def test_rolling_total_sums_rounded_entries(self, api, officer_headers):
        """PRD §3.8: "Each entry's `value_usd_cents` is computed individually at
        creation as the local value multiplied by the FX rate, rounded half-up to
        whole cents; aggregations always sum these per-entry rounded figures,
        never a sum-then-round of raw values."
        PRD §3.8: "Approval moves the entry to `APPROVED` and recomputes the
        party's `gov_gift_rolling_12m_cents` — the rolling 365-day sum over the
        party's approved government-official entries — now including this entry."

        Design: Difficulty/combinatorial_formula/gift_rolling_total_per_entry_rounding
        """
        tp_id, g1, g2 = self._setup_two_entries(api)
        approve_gift(g1["id"])
        approve_gift(g2["id"])

        tp = get_third_party(tp_id)
        assert tp["gov_gift_rolling_12m_cents"] == 6700, (
            "round-per-entry-then-sum: 3350 + 3350 == 6700"
        )


class TestEnhancedApprovalThreshold:
    """prospective 24999 does not require enhanced approval; exactly 25000 does
    (>= inclusive)."""

    def _setup_two_parties_with_20000_approved(self, api):
        setup_risk_basis("CH", 80)
        parties = {}
        for name in ("TP-A", "TP-B"):
            tp = create_draft_third_party("CH", "TECHNOLOGY", "NONE", legal_name=name)
            advance_to_dd_review(tp["id"])
            create_approved_gift(tp["id"], value_cents=20000, fx_rate_to_usd=1.0,
                                 event_date="2026-05-05")
            parties[name] = tp["id"]
        return parties["TP-A"], parties["TP-B"]

    def test_24999_does_not_require_enhanced_approval(self, api, officer_headers):
        """PRD §3.8: "Two thresholds hang off the prospective total with
        deliberately different operators: at or above 25000 cents — inclusive —
        the entry's computed `requires_enhanced_approval` becomes true, while
        strictly above 50000 cents is the hard cap."

        Design: Difficulty/boundary_precision_check/gift_enhanced_threshold_24999_vs_25000
        """
        tpa, _ = self._setup_two_parties_with_20000_approved(api)
        entry = create_gift(tpa, value_cents=4999, fx_rate_to_usd=1.0,
                            event_date="2026-05-06")
        # 20000 + 4999 = 24999 < 25000.
        assert entry["requires_enhanced_approval"] is False

        approved = validate_success(api.approve_gift_entry(entry["id"], {},
                                                           officer_headers), 200)
        assert approved["entry_status"] == "APPROVED"

    def test_25000_requires_enhanced_approval(self, api, officer_headers):
        """PRD §3.8: "Two thresholds hang off the prospective total with
        deliberately different operators: at or above 25000 cents — inclusive —
        the entry's computed `requires_enhanced_approval` becomes true, while
        strictly above 50000 cents is the hard cap."
        PRD §3.8: "Approval by a `ComplianceOfficer` re-tests both conditions
        against the world as it now stands: if `requires_enhanced_approval` is
        true, the approval payload's `enhanced_review_evidence` must be true
        (`ERR_ENHANCED_REVIEW_REQUIRED`)"

        Design: Difficulty/boundary_precision_check/gift_enhanced_threshold_24999_vs_25000
        """
        _, tpb = self._setup_two_parties_with_20000_approved(api)
        entry = create_gift(tpb, value_cents=5000, fx_rate_to_usd=1.0,
                            event_date="2026-05-06")
        # 20000 + 5000 = 25000 >= 25000 — inclusive boundary.
        assert entry["requires_enhanced_approval"] is True

        resp = api.approve_gift_entry(entry["id"], {}, officer_headers)
        validate_error(resp, ApiErrorId.ERR_ENHANCED_REVIEW_REQUIRED)


class TestRollingWindowLowerBound:
    """The window (event_date - 365d, event_date] is open at the lower bound: an
    entry dated exactly 365 days earlier is excluded."""

    def _setup_entries_one_year_apart(self, api):
        ctx = setup_third_party_in_state("DD_REVIEW", "CH", 80, clock="2025-05-31T00:00:00Z")
        tp_id = ctx["third_party"]["id"]
        e1 = create_gift(tp_id, entry_type="HOSPITALITY", value_cents=30000,
                         fx_rate_to_usd=1.0, event_date="2025-05-31")
        approve_gift(e1["id"], evidence=True)  # prospective 30000 >= 25000
        set_clock("2026-05-31T00:00:00Z")
        return tp_id

    def test_entry_on_open_lower_bound_excluded_from_cap(self, api, officer_headers):
        """PRD §3.8: "The rolling window belongs to each entry: it opens 365 days
        before the entry's `event_date` (exclusive) and closes on the
        `event_date` itself (inclusive)."
        PRD §3.8: "The fiscal cap last: the prospective government-official
        rolling total — defined below — strictly above 50000 cents rejects the
        create with `ERR_GIFT_CAP_EXCEEDED`, while a prospective total of exactly
        50000 is allowed."
        PRD §2.5: "A `ComplianceAdmin` may set the clock to any ISO-8601 instant
        — there is no monotonicity constraint, so the clock may move backward as
        freely as forward — by supplying `to_iso8601`; the capability answers
        with the new `current_utc`."

        Design: Difficulty/resource_temporal_overlap/gift_rolling_window_lower_bound_exclusive
        """
        tp_id = self._setup_entries_one_year_apart(api)
        e2 = create_gift(tp_id, entry_type="GIFT", value_cents=25000,
                         fx_rate_to_usd=1.0, event_date="2026-05-31")
        # E1 (2025-05-31) sits on the open lower bound of (2025-05-31,
        # 2026-05-31] and is excluded: prospective == 25000, not 55000.
        assert e2["requires_enhanced_approval"] is True

        approved = validate_success(
            api.approve_gift_entry(e2["id"], {"enhanced_review_evidence": True},
                                   officer_headers), 200)
        assert approved["entry_status"] == "APPROVED"

    def test_rolling_total_reflects_excluded_lower_bound(self, api, officer_headers):
        """PRD §3.8: "The rolling window belongs to each entry: it opens 365 days
        before the entry's `event_date` (exclusive) and closes on the
        `event_date` itself (inclusive). The rolling total sums `value_usd_cents`
        over the same party's entries that have `recipient_is_government_official`
        true, `entry_status` `APPROVED`, and an `event_date` inside the window"

        Design: Difficulty/resource_temporal_overlap/gift_rolling_window_lower_bound_exclusive
        """
        tp_id = self._setup_entries_one_year_apart(api)
        e2 = create_gift(tp_id, entry_type="GIFT", value_cents=25000,
                         fx_rate_to_usd=1.0, event_date="2026-05-31")
        approve_gift(e2["id"], evidence=True)

        tp = get_third_party(tp_id)
        assert tp["gov_gift_rolling_12m_cents"] == 25000, (
            "had the lower bound been inclusive the total would be 55000"
        )


class TestVoidRestoresRollingTotal:
    def _setup_two_approved_entries(self, api):
        ctx = setup_third_party_in_state("DD_REVIEW", "CH", 80)
        tp_id = ctx["third_party"]["id"]
        e1 = create_approved_gift(tp_id, value_cents=20000, fx_rate_to_usd=1.0,
                                  event_date="2026-05-05")
        e2 = create_gift(tp_id, value_cents=8000, fx_rate_to_usd=1.0,
                         event_date="2026-05-06")
        approve_gift(e2["id"], evidence=True)  # prospective 28000 >= 25000
        return tp_id, e1, e2

    def test_void_compensates_aggregate_exactly(self, api, officer_headers):
        """PRD §3.8: "Voiding with an optional `reason` moves an `APPROVED` entry
        to `VOIDED` and recomputes the aggregate excluding exactly this entry —
        the registry's compensating invariant."

        Design: Difficulty/compensating_invariant/gift_void_restores_rolling_total
        """
        tp_id, _, e2 = self._setup_two_approved_entries(api)
        before = get_third_party(tp_id)
        assert before["gov_gift_rolling_12m_cents"] == 28000

        validate_success(
            api.void_gift_entry(e2["id"], {"reason": "reported in error"},
                                officer_headers), 200)
        after = get_third_party(tp_id)
        assert after["gov_gift_rolling_12m_cents"] == 20000, (
            "void removes exactly the voided entry's value: zero drift"
        )

    def test_void_moves_entry_to_voided(self, api, officer_headers):
        """PRD §3.8: "Voiding with an optional `reason` moves an `APPROVED` entry
        to `VOIDED` and recomputes the aggregate excluding exactly this entry —
        the registry's compensating invariant."

        Design: Difficulty/compensating_invariant/gift_void_restores_rolling_total
        """
        tp_id, e1, e2 = self._setup_two_approved_entries(api)
        voided = validate_success(
            api.void_gift_entry(e2["id"], {"reason": "reported in error"},
                                officer_headers), 200)
        assert voided["entry_status"] == "VOIDED"

        entries = validate_success(api.list_gift_entries(tp_id, officer_headers), 200)
        by_id = {g["id"]: g for g in entries}
        assert by_id[e2["id"]]["entry_status"] == "VOIDED"
        assert by_id[e1["id"]]["entry_status"] == "APPROVED"


class TestCreationRefusals:
    def _setup_sanctioned_party_in_dd_review(self, api):
        ctx = setup_third_party_in_state("DD_REVIEW", "IR", 36, "CONSULTING", "DIRECT",
                                         sanctioned=True, legal_name="IR Consulting")
        return ctx["third_party"]["id"]

    def test_sanctioned_safety_beats_event_in_past(self, api, sponsor_headers,
                                                   officer_headers):
        """PRD §3.8: "Three refusal rules guard creation, surfacing in §2.9's
        order. Sanctions first: an entry with `recipient_is_government_official`
        set to true on a party whose country profile is `sanctioned` is refused
        with `ERR_COUNTRY_SANCTIONED`. Temporal second: pre-approval requires the
        `event_date` to fall on or after the current date, and a past date is
        `ERR_EVENT_IN_PAST`."
        PRD §2.9: "Sixth, sanctions safety: a government-official gift tied to a
        sanctioned country yields `ERR_COUNTRY_SANCTIONED`. Seventh, temporal
        rules: `ERR_EVENT_IN_PAST`, `ERR_AUDIT_NOTICE_TOO_SHORT`, and
        `ERR_AUDIT_WINDOW_OVERLAP`."

        Design: Difficulty/priority_pair_validation_conflict/gift_sanctioned_safety_beats_event_in_past
        """
        tp_id = self._setup_sanctioned_party_in_dd_review(api)
        resp = api.create_gift_entry(
            tp_id,
            {"entry_type": "HOSPITALITY", "recipient_is_government_official": True,
             "value_cents": 5000, "fx_rate_to_usd": 1.0, "event_date": "2026-04-01"},
            sponsor_headers,
        )
        # Both rules are violated (sanctioned country; event in the past); the
        # safety tier surfaces first.
        validate_error(resp, ApiErrorId.ERR_COUNTRY_SANCTIONED)

        entries = validate_success(api.list_gift_entries(tp_id, officer_headers), 200)
        assert entries == [], "no entry may be persisted on refusal"

    def test_non_government_recipient_surfaces_temporal_rule(self, api, sponsor_headers):
        """PRD §3.8: "Temporal second: pre-approval requires the `event_date` to
        fall on or after the current date, and a past date is
        `ERR_EVENT_IN_PAST`."
        PRD §3.8: "Entries for non-government recipients are excluded from the
        aggregate and from both caps."

        Design: Difficulty/priority_pair_validation_conflict/gift_sanctioned_safety_beats_event_in_past
        """
        tp_id = self._setup_sanctioned_party_in_dd_review(api)
        resp = api.create_gift_entry(
            tp_id,
            {"entry_type": "HOSPITALITY", "recipient_is_government_official": False,
             "value_cents": 5000, "fx_rate_to_usd": 1.0, "event_date": "2026-04-01"},
            sponsor_headers,
        )
        # The sanctions rule keys on recipient_is_government_official=true, so
        # for a non-government recipient the temporal rule is the one that fires.
        validate_error(resp, ApiErrorId.ERR_EVENT_IN_PAST)

    def test_gift_event_in_past_rejected(self, api, sponsor_headers):
        """PRD §3.8: "Temporal second: pre-approval requires the `event_date` to
        fall on or after the current date, and a past date is
        `ERR_EVENT_IN_PAST`."

        Design: Corner/validations/gift_event_in_past_rejected
        """
        ctx = setup_third_party_in_state("DD_REVIEW", "CH", 80)
        tp_id = ctx["third_party"]["id"]
        resp = api.create_gift_entry(
            tp_id,
            {"entry_type": "GIFT", "recipient_is_government_official": False,
             "value_cents": 5000, "fx_rate_to_usd": 1.0, "event_date": "2026-04-30"},
            sponsor_headers,
        )
        validate_error(resp, ApiErrorId.ERR_EVENT_IN_PAST)


class TestHardCapBoundary:
    def test_gift_hard_cap_50000_allowed_50001_rejected(self, api, sponsor_headers,
                                                        officer_headers):
        """PRD §3.8: "The fiscal cap last: the prospective government-official
        rolling total — defined below — strictly above 50000 cents rejects the
        create with `ERR_GIFT_CAP_EXCEEDED`, while a prospective total of exactly
        50000 is allowed."
        PRD §3.8: "Two thresholds hang off the prospective total with
        deliberately different operators: at or above 25000 cents — inclusive —
        the entry's computed `requires_enhanced_approval` becomes true, while
        strictly above 50000 cents is the hard cap."

        Design: Corner/validations/gift_hard_cap_50000_allowed_50001_rejected
        """
        ctx = setup_third_party_in_state("DD_REVIEW", "CH", 80)
        tp_id = ctx["third_party"]["id"]
        create_approved_gift(tp_id, value_cents=24000, fx_rate_to_usd=1.0,
                             event_date="2026-05-05")
        g2 = create_gift(tp_id, value_cents=24000, fx_rate_to_usd=1.0,
                         event_date="2026-05-06")
        assert g2["requires_enhanced_approval"] is True  # prospective 48000
        approve_gift(g2["id"], evidence=True)

        g3 = create_gift(tp_id, value_cents=2000, fx_rate_to_usd=1.0,
                         event_date="2026-05-07")
        # Prospective exactly 50000 is NOT > 50000 — the create is allowed.
        approved = validate_success(
            api.approve_gift_entry(g3["id"], {"enhanced_review_evidence": True},
                                   officer_headers), 200)
        assert approved["entry_status"] == "APPROVED"

        resp = api.create_gift_entry(
            tp_id,
            {"entry_type": "GIFT", "recipient_is_government_official": True,
             "value_cents": 1, "fx_rate_to_usd": 1.0, "event_date": "2026-05-08"},
            sponsor_headers,
        )
        # Prospective 50001 > 50000 — the strict hard cap rejects the create.
        validate_error(resp, ApiErrorId.ERR_GIFT_CAP_EXCEEDED)

        tp = get_third_party(tp_id)
        assert tp["gov_gift_rolling_12m_cents"] == 50000
