"""Difficulty Rule 6 — boundary_precision_check.

Boundary tests on two distinct metrics:

  • datetime threshold: SOL boundary closed-on-expired-side at the exact instant (PRD §2.6, §3.6)
  • count/cardinality: empty INCLUDED damages set produces demand_amount_cents=0 (PRD §3.4)
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    set_clock,
    register_client,
    sign_retainer,
    create_case,
    activate_case,
    register_provider,
    create_records_request,
    walk_records_request_to_reviewed,
    create_included_damages,
    create_demand_letter,
    send_demand_letter,
    create_offer,
    accept_offer,
    get_case_version,
    ApiErrorId,
    api_client,
    accept_offer_payload,
    make_managing_partner_headers,
    setup_active_case_with_reviewed_records,
)


# =============================================================================
# Instance: sol_exact_instant_is_expired_on_accept
# =============================================================================


class TestSolExactInstantIsExpiredOnAccept:
    """The statute-of-limitations boundary is closed on the EXPIRED side: at
    the exact instant the clock equals effective_sol_date, the statute has
    run, and ERR_STATUTE_EXPIRED fires."""

    def _build_case_with_pending_offer_at_sol_minus_n(self):
        """Active CA case (accident 2024-01-15, SOL 2026-01-15),
        INCLUDED MEDICAL_BILLS, demand SENT, CARRIER PENDING offer at 1_000_000.

        The clock is set within 30 days of SOL so that the subsequent clock
        advance to the SOL instant does not auto-expire the PENDING offer
        (PRD §3.5 30-day expiry sweep)."""
        set_clock("2026-01-14T00:00:00Z")
        c = register_client(email="solbnd@example.com")
        sign_retainer(c["id"])
        case = create_case(c["id"], accident_date="2024-01-15",
                            jurisdiction="CA")
        activate_case(case["id"])
        provider = register_provider()
        mrr = create_records_request(case["id"], provider["id"])
        walk_records_request_to_reviewed(mrr["id"])
        create_included_damages(case["id"], "MEDICAL_BILLS", 100_000)
        dl = create_demand_letter(case["id"], pain_multiplier=1.5,
                                   drafter_user_id="drafter-6a")
        send_demand_letter(dl["id"], partner_user_id="partner-6a")
        offer = create_offer(case["id"], 1_000_000, "CARRIER")
        return case["id"], offer["id"]

    def test_accept_at_exact_sol_instant_returns_statute_expired(self, api):
        """PRD §2.6: "Boundary inclusivity matters: the statute-of-limitations
        comparison is closed on the expired side — at the exact moment the
        clock equals the effective statute date, the statute has already run."
        PRD §3.6: "The statute of limitations must not have expired
        (`ERR_STATUTE_EXPIRED`)."

        Design: Difficulty/boundary_precision_check/sol_exact_instant_is_expired_on_accept
        """
        case_id, offer_id = self._build_case_with_pending_offer_at_sol_minus_n()
        # Advance clock to the exact SOL instant (CA 2y from accident 2024-01-15).
        set_clock("2026-01-15T00:00:00Z")
        case_v = get_case_version(case_id)
        headers = make_managing_partner_headers("partner-6a")
        res = api_client.accept_offer(
            offer_id, accept_offer_payload(case_v), headers
        )
        validate_error(res, ApiErrorId.ERR_STATUTE_EXPIRED.value)

    def test_accept_one_second_before_sol_succeeds(self, api):
        """PRD §2.6: "Boundary inclusivity matters: the statute-of-limitations
        comparison is closed on the expired side — at the exact moment the
        clock equals the effective statute date, the statute has already run."
        PRD §3.6: "When all guards pass, the offer transitions `PENDING →
        ACCEPTED`, its `responded_at` is stamped, and the parent case
        auto-transitions to `SETTLED` (as a depth-two cascade from either
        `IN_NEGOTIATION → SETTLED` or `LITIGATION → SETTLED` depending on
        where the case was)."

        Design: Difficulty/boundary_precision_check/sol_exact_instant_is_expired_on_accept
        """
        case_id, offer_id = self._build_case_with_pending_offer_at_sol_minus_n()
        # One second before SOL instant must still be valid.
        set_clock("2026-01-14T23:59:59Z")
        case_v = get_case_version(case_id)
        headers = make_managing_partner_headers("partner-6a")
        res = api_client.accept_offer(
            offer_id, accept_offer_payload(case_v), headers
        )
        body = validate_success(res, 200)
        assert body["status"] == "ACCEPTED"


# =============================================================================
# Instance: demand_letter_with_zero_included_damages_yields_zero
# =============================================================================


class TestDemandLetterWithZeroIncludedDamagesYieldsZero:
    """Empty-collection edge: a case with NO INCLUDED DamagesItems must still
    accept a demand letter draft, and demand_amount_cents must be 0."""

    def test_zero_included_damages_yields_zero_demand_amount(self, api):
        """PRD §3.4: "Once the case is `ACTIVE` and at least one medical
        records request on it is `REVIEWED`, an `Attorney` drafts a demand
        letter, supplying the `case_id` and a `pain_multiplier`."
        PRD §3.4: "the medical line is the sum of `amount_cents` over
        `INCLUDED` items with `category == MEDICAL_BILLS` multiplied by one
        (so it is just the sum), the wages line is the same construction over
        `LOST_WAGES`, the property line is the same construction over
        `PROPERTY`, and the future-medical line is the sum of `amount_cents`
        over `INCLUDED` items in `FUTURE_MEDICAL` multiplied by the
        present-value discount factor `0.85` and rounded half-up."
        PRD §3.4: "The final `demand_amount_cents` is the subtotal plus the
        buffer, taken as a pure integer-cent sum with no additional rounding
        step."

        Design: Difficulty/boundary_precision_check/demand_letter_with_zero_included_damages_yields_zero
        """
        set_clock("2026-01-01T00:00:00Z")
        client, case, provider, mrr = setup_active_case_with_reviewed_records()
        # Deliberately do NOT include any damages.
        dl = create_demand_letter(case["id"], pain_multiplier=2.0,
                                   drafter_user_id="drafter-6b")
        # All per-line sums are 0; subtotal=0; buffer_rate=0.20 (since 0<5_000_00);
        # buffer = round_half_up(0 * 0.20) = 0; demand = 0+0 = 0.
        assert dl["demand_amount_cents"] == 0
        assert dl["status"] == "DRAFT"

    def test_zero_damages_draft_is_in_draft_status_with_zero_amount(self, api):
        """PRD §3.4: "The draft is created in `DRAFT` status, the system stamps
        `drafted_by_user_id` with the acting `X-User-ID`, and the
        `demand_amount_cents` is computed at draft creation time and is
        immutable thereafter."

        Design: Difficulty/boundary_precision_check/demand_letter_with_zero_included_damages_yields_zero
        """
        set_clock("2026-01-01T00:00:00Z")
        client, case, provider, mrr = setup_active_case_with_reviewed_records()
        dl = create_demand_letter(case["id"], pain_multiplier=1.0,
                                   drafter_user_id="drafter-6c")
        assert dl["status"] == "DRAFT"
        assert dl["demand_amount_cents"] == 0
        assert dl["drafted_by_user_id"] == "drafter-6c"
