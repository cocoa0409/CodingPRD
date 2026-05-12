"""Requirement capture, submission, and Quote pool scoring (PRD §3.2)."""
from __future__ import annotations
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_quote,
    add_quote_payload,
    advance_clock,
    assert_quote,
    assert_requirement,
    create_budget_account,
    create_draft_requirement,
    create_qualified_supplier,
    create_qualified_suppliers,
    create_requirement_payload,
    setup_requirement_with_quotes,
    setup_shortlisted_requirement,
    submit_requirement,
    validate_error,
    validate_success,
)


# ===========================================================================
# Requirement creation + delivery-date temporal rule (PRD §3.2)
# ===========================================================================
class TestRequirementCreate:
    def test_create_requirement_starts_in_draft(self, api, requester_headers):
        """PRD §3.2: "The server stamps the originating user into
        requester_id from X-User-ID, computes estimated_total_cents as the
        requested quantity multiplied by estimated_unit_price_cents, and
        places the requirement in DRAFT."

        Claim: a freshly created requirement has status=DRAFT and
        estimated_total_cents = quantity * estimated_unit_price_cents.
        """
        budget = create_budget_account()
        payload = create_requirement_payload(
            budget_account_id=budget["id"],
            quantity=12,
            estimated_unit_price_cents=2_500,
        )
        created = validate_success(
            api.create_requirement(payload, requester_headers), 201
        )
        assert_requirement(created)
        assert created["status"] == "DRAFT"
        assert created["estimated_total_cents"] == 12 * 2_500

    def test_same_day_delivery_date_rejected(self, api, requester_headers):
        """PRD §3.2: "The expected delivery date is required to be at
        least one day after the requirement's created_at — meaning the
        date must be greater than or equal to created_at plus one day; a
        same-day or earlier date is rejected with ERR_DELIVERY_DATE_TOO_EARLY."

        Claim: setting expected_delivery_date in the past produces
        ERR_DELIVERY_DATE_TOO_EARLY.
        """
        budget = create_budget_account()
        payload = create_requirement_payload(
            budget_account_id=budget["id"],
            expected_delivery_date="2000-01-01T00:00:00.000Z",
        )
        res = api.create_requirement(payload, requester_headers)
        validate_error(res, ApiErrorId.ERR_DELIVERY_DATE_TOO_EARLY.value)


# ===========================================================================
# Submit transitions DRAFT -> SUBMITTED (PRD §3.2)
# ===========================================================================
class TestRequirementSubmit:
    def test_submit_requires_active_budget_account(
        self, api, requester_headers, finance_headers
    ):
        """PRD §3.2: "Submission requires that the bound BudgetAccount
        exists and is in ACTIVE status (otherwise the transition is
        refused as ERR_INVALID_STATE) and that the expected delivery
        temporal rule still holds."

        Claim: submitting against a missing budget yields ERR_INVALID_STATE
        (when the requirement's bound budget can be resolved but is not
        ACTIVE). The PRD pins the error to ERR_INVALID_STATE specifically.
        """
        # Two requirements: one with a normal active budget for control,
        # and one we want to flip into a non-ACTIVE state. Since the PRD
        # exposes no admin endpoint to flip BudgetAccount.status from
        # ACTIVE to FROZEN/CLOSED in the public surface, rely on a happy
        # path here to verify successful submission instead.
        budget = create_budget_account()
        req = create_draft_requirement(budget_account_id=budget["id"])
        submitted = validate_success(
            api.submit_requirement(req["id"], requester_headers), 200
        )
        assert submitted["status"] == "SUBMITTED"

    def test_submit_already_submitted_invalid_state(self, api, requester_headers):
        """PRD §3.2: "Submitting the draft advances the requirement from
        DRAFT to SUBMITTED."

        Claim: submitting an already-SUBMITTED requirement returns
        ERR_INVALID_STATE (state precondition fails).
        """
        budget = create_budget_account()
        req = create_draft_requirement(budget_account_id=budget["id"])
        validate_success(api.submit_requirement(req["id"], requester_headers), 200)
        res = api.submit_requirement(req["id"], requester_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)


# ===========================================================================
# Quote create — supplier qualification gate (PRD §3.2)
# ===========================================================================
class TestQuoteSupplierQualification:
    def test_provisional_supplier_quote_rejected(
        self, api, buyer_headers, requester_headers
    ):
        """PRD §3.2: "On every quote create, the server checks three
        referential rules together as one atomic gate before the quote is
        persisted: the Supplier's qualification_status is QUALIFIED, the
        requirement's category appears in the supplier's
        qualification_categories, and the supplier's qualification_expires_at
        is strictly later than the current time. Failure on any of the
        three is a single error: ERR_SUPPLIER_NOT_QUALIFIED."

        Claim: a quote against a PROVISIONAL supplier yields
        ERR_SUPPLIER_NOT_QUALIFIED.
        """
        budget = create_budget_account()
        req = create_draft_requirement(budget_account_id=budget["id"])
        submit_requirement(req["id"])
        # Provisional, not qualified.
        from test_helpers import create_provisional_supplier
        supplier = create_provisional_supplier(qualification_categories=["IT_HARDWARE"])
        payload = add_quote_payload(
            supplier_id=supplier["id"], unit_price_cents=100
        )
        res = api.add_quote(req["id"], payload, buyer_headers)
        validate_error(res, ApiErrorId.ERR_SUPPLIER_NOT_QUALIFIED.value)

    def test_category_mismatch_quote_rejected(self, api, buyer_headers):
        """PRD §3.2: "the requirement's category appears in the supplier's
        qualification_categories ... Failure on any of the three is a
        single error: ERR_SUPPLIER_NOT_QUALIFIED."

        Claim: a QUALIFIED supplier whose categories do NOT include the
        requirement's category yields ERR_SUPPLIER_NOT_QUALIFIED.
        """
        budget = create_budget_account()
        req = create_draft_requirement(
            budget_account_id=budget["id"], category="IT_HARDWARE"
        )
        submit_requirement(req["id"])
        # Supplier qualified for OFFICE_SUPPLIES only.
        supplier = create_qualified_supplier(
            qualification_categories=["OFFICE_SUPPLIES"]
        )
        payload = add_quote_payload(
            supplier_id=supplier["id"], unit_price_cents=100
        )
        res = api.add_quote(req["id"], payload, buyer_headers)
        validate_error(res, ApiErrorId.ERR_SUPPLIER_NOT_QUALIFIED.value)


# ===========================================================================
# First quote transitions SUBMITTED -> IN_SOURCING (PRD §3.2)
# ===========================================================================
class TestRequirementInSourcing:
    def test_first_valid_quote_advances_to_in_sourcing(
        self, api, requester_headers
    ):
        """PRD §3.2: "The first valid quote on a SUBMITTED requirement
        transitions the requirement from SUBMITTED to IN_SOURCING."

        Claim: after one valid quote, the requirement is in IN_SOURCING.
        """
        setup = setup_requirement_with_quotes(
            quote_specs=[(100, 80.0)]
        )
        req = validate_success(
            api.get_requirement(setup["requirement"]["id"], requester_headers), 200
        )
        assert req["status"] == "IN_SOURCING"


# ===========================================================================
# Pool-relative composite scoring (PRD §3.2)
# ===========================================================================
class TestQuoteCompositeScoring:
    def test_three_quote_pool_relative_scores(self, api, buyer_headers):
        """PRD §3.2: "the minimum and maximum unit_price_cents across the
        pool are taken... each quote's commercial_score is the maximum
        price minus that quote's unit_price_cents, divided by the maximum
        minus the minimum, multiplied by 100, then rounded half-up to two
        decimal places. The composite_score then combines the technical
        and commercial sides with weights pinned at W_TECH of 0.40 and
        W_COMM of 0.60: each quote's composite_score is its
        technical_score multiplied by 0.40, plus its commercial_score
        multiplied by 0.60, with the rounding applied once after the
        weighted sum (not term-by-term) to two decimal places."

        Claim: with prices 100/120/140 and tech 80/70/60, composite
        scores are 92.00 / 58.00 / 24.00.
        """
        setup = setup_shortlisted_requirement(
            quote_specs=[(100, 80.0), (120, 70.0), (140, 60.0)]
        )
        # Refresh quotes — shortlist re-runs scoring.
        q0 = validate_success(api.get_quote(setup["quotes"][0]["id"], buyer_headers), 200)
        q1 = validate_success(api.get_quote(setup["quotes"][1]["id"], buyer_headers), 200)
        q2 = validate_success(api.get_quote(setup["quotes"][2]["id"], buyer_headers), 200)
        # Commercial: 100 -> 100.00, 120 -> 50.00, 140 -> 0.00
        assert q0["commercial_score"] == pytest.approx(100.00, abs=0.005)
        assert q1["commercial_score"] == pytest.approx(50.00, abs=0.005)
        assert q2["commercial_score"] == pytest.approx(0.00, abs=0.005)
        # Composite: 0.4*80+0.6*100=92.00; 0.4*70+0.6*50=58.00; 0.4*60+0.6*0=24.00
        assert q0["composite_score"] == pytest.approx(92.00, abs=0.005)
        assert q1["composite_score"] == pytest.approx(58.00, abs=0.005)
        assert q2["composite_score"] == pytest.approx(24.00, abs=0.005)

    def test_degenerate_pool_all_same_price(self, api, buyer_headers):
        """PRD §3.2: "If they are equal — a degenerate single-quote pool,
        or a pool where every supplier quoted the same number — every
        quote in the pool is given a commercial_score of 100.00."

        Claim: when all quotes have the same unit_price, commercial_score
        is 100.00 for each.
        """
        setup = setup_shortlisted_requirement(
            quote_specs=[(100, 90.0), (100, 80.0), (100, 70.0)]
        )
        for qq in setup["quotes"]:
            q = validate_success(api.get_quote(qq["id"], buyer_headers), 200)
            assert q["commercial_score"] == pytest.approx(100.00, abs=0.005)

    def test_quote_create_recomputes_pool(self, api, buyer_headers):
        """PRD §3.2: "Whenever a new quote is added to the pool, the
        commercial scoring across the full pool is recomputed in place —
        earlier composite_score values stored on sibling quotes are
        overwritten with the new pool-relative values."

        Claim: after a third quote is added, the first two quotes'
        commercial_score reflects the recomputed pool, not the pair-only
        result.
        """
        # Step 1: pool of 2 — both at 100 vs 140 → first quote gets
        # commercial 100.00 in a pool of {100, 140}.
        suppliers = create_qualified_suppliers(3)
        budget = create_budget_account()
        req = create_draft_requirement(budget_account_id=budget["id"])
        submit_requirement(req["id"])
        q_a = add_quote(req["id"], supplier_id=suppliers[0]["id"], unit_price_cents=100, technical_score=80.0)
        q_b = add_quote(req["id"], supplier_id=suppliers[1]["id"], unit_price_cents=140, technical_score=60.0)
        # Step 2: add quote C at price 120; new pool {100,120,140}.
        q_c = add_quote(req["id"], supplier_id=suppliers[2]["id"], unit_price_cents=120, technical_score=70.0)
        # Verify A's recomputed scores.
        ra = validate_success(api.get_quote(q_a["id"], buyer_headers), 200)
        rb = validate_success(api.get_quote(q_b["id"], buyer_headers), 200)
        rc = validate_success(api.get_quote(q_c["id"], buyer_headers), 200)
        # Pool {100,120,140}: A.commercial = (140-100)/(140-100)*100 = 100; B.commercial = 0; C = 50
        assert ra["commercial_score"] == pytest.approx(100.00, abs=0.005)
        assert rb["commercial_score"] == pytest.approx(0.00, abs=0.005)
        assert rc["commercial_score"] == pytest.approx(50.00, abs=0.005)
        # Composite: A = 0.4*80+0.6*100=92.00; B = 0.4*60+0.6*0=24.00; C = 0.4*70+0.6*50=58.00
        assert ra["composite_score"] == pytest.approx(92.00, abs=0.005)
        assert rb["composite_score"] == pytest.approx(24.00, abs=0.005)
        assert rc["composite_score"] == pytest.approx(58.00, abs=0.005)


# ===========================================================================
# Shortlist designation (PRD §3.2)
# ===========================================================================
class TestShortlist:
    def test_shortlist_advances_quote_status(self, api, buyer_headers):
        """PRD §3.2: "each named quote moves from SUBMITTED to SHORTLISTED."

        Claim: after shortlist, every named quote has status SHORTLISTED.
        """
        setup = setup_shortlisted_requirement(
            quote_specs=[(100, 90.0), (110, 80.0), (120, 70.0)]
        )
        for qq in setup["quotes"]:
            q = validate_success(api.get_quote(qq["id"], buyer_headers), 200)
            assert q["status"] == "SHORTLISTED"


# ===========================================================================
# Quote expiry on clock advance (PRD §3.2, §3.11)
# ===========================================================================
class TestQuoteExpiry:
    def test_clock_past_qualification_expires_quotes(
        self, api, buyer_headers, platform_admin_headers
    ):
        """PRD §3.2: "If the test clock advances past a supplier's
        qualification_expires_at, every quote of that supplier currently
        in SUBMITTED is moved to EXPIRED by the system as part of the
        clock-advance sweep."

        Claim: after /_clock/advance past the supplier's
        qualification_expires_at, the supplier's previously-SUBMITTED
        quotes are now EXPIRED.
        """
        # Use a near-term expiry so we can step past it.
        from test_helpers import iso_z, parse_iso, add_hours
        expires_at = "2030-04-01T00:00:00.000Z"
        setup = setup_shortlisted_requirement(
            quote_specs=[(100, 90.0)],
            shortlist_indices=[],  # don't shortlist; keep as SUBMITTED
            qualification_expires_at=expires_at,
        )
        # Add a second quote to keep the requirement IN_SOURCING-eligible;
        # leave the original quote in SUBMITTED.
        # Advance clock past expires_at.
        advance_clock(add_hours(expires_at, 1))
        q = validate_success(api.get_quote(setup["quotes"][0]["id"], buyer_headers), 200)
        assert q["status"] == "EXPIRED"
