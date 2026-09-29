"""Read-your-writes: the transition response already carries the derived
figures, and the very next read — of the same entity or of the entity the
write reached across to — agrees with it to the cent.
"""

from test_helpers import (
    COMPLIANCE_OFFICER_HEADERS,
    COMPLIANCE_OFFICER_USER_ID,
    INTERNATIONAL_SCOUT_HEADERS,
    ApiClient,
    assert_integer,
    assert_money,
    assert_status,
    fixtures,
    make_affiliate_operator_headers,
    validate_paginated,
)


# ---------------------------------------------------------------------------
# Instance 1 — the SUBMIT response already carries the provisional settlement
# ---------------------------------------------------------------------------


def test_the_submit_response_already_carries_the_provisional_obligation(api: ApiClient):
    """No follow-up read is needed, and the follow-up read adds nothing.

    PRD 3.2: "A newly drafted licence sits in status `DRAFT` with `posture`
    `FROZEN`, `provisional_club_obligation_cents` and `affiliate_overflow_cents`
    at 0, `final_club_obligation_cents` null, `settlement_status` `NOT_SETTLED`,
    and `submitted_by_user_id` null."  The figure is bound to the submission and
    to nothing earlier: "Submission records `submitted_by_user_id` from the
    acting `X-User-ID`, runs the provisional expense allocation described in
    Section 3.3 — writing `provisional_club_obligation_cents` and
    `affiliate_overflow_cents` — and recomputes `posture`, which stays `FROZEN`
    because the licence is not yet `ACTIVE`."  PRD 3.3 fixes the four lines —
    "the club funds three quarters of housing, sixty per cent of meals, all of
    team travel, and one quarter of facility upkeep" — so 150000, 120000, 100000
    and 20000 drain a 900000 aggregate bucket that never runs out and the
    obligation is 390000 with no overflow.

    Design: Corner/consistency_model/submit_response_already_carries_the_provisional_settlement_figures
    """
    fixtures.set_clock(api, "2026-04-01T00:00:00Z")
    affiliate = fixtures.create_affiliate(
        api,
        COMPLIANCE_OFFICER_HEADERS,
        name="Immediate Club",
        level="HIGH_A",
        market_city="Rome",
        meal_stipend_cents_per_day=2800,
    )
    drafted = fixtures.create_agreement(
        api,
        affiliate["id"],
        term_start_date="2026-01-01",
        term_end_date="2026-12-31",
        facility_standard_tier="TIER_2",
        club_reimbursement_cap_cents=900000,
        minimum_active_players=0,
        housing_expense_cents=200000,
        meal_expense_cents=200000,
        travel_expense_cents=100000,
        upkeep_expense_cents=80000,
    )
    assert_status(drafted, "DRAFT", "AffiliationAgreement")
    assert_money(
        drafted["provisional_club_obligation_cents"], 0, "provisional_club_obligation_cents"
    )
    assert_money(drafted["affiliate_overflow_cents"], 0, "affiliate_overflow_cents")
    assert drafted["final_club_obligation_cents"] is None, (
        f"a draft carries no final obligation, got {drafted['final_club_obligation_cents']!r}"
    )

    submitted = fixtures.submit_agreement(api, drafted["id"], affiliate["id"])
    assert_status(submitted, "SUBMITTED", "AffiliationAgreement")
    assert_money(
        submitted["provisional_club_obligation_cents"],
        390000,
        "provisional_club_obligation_cents",
    )
    assert_money(submitted["affiliate_overflow_cents"], 0, "affiliate_overflow_cents")
    assert submitted["settlement_status"] == "NOT_SETTLED", (
        f"submission does not settle the licence, got {submitted['settlement_status']}"
    )
    assert submitted["final_club_obligation_cents"] is None, (
        f"the final obligation waits for settlement, got {submitted['final_club_obligation_cents']!r}"
    )

    rows, meta = validate_paginated(
        api.list_agreements(
            affiliate["id"],
            make_affiliate_operator_headers(affiliate["id"]),
            {"status": "SUBMITTED"},
        )
    )
    assert_integer(meta["total_count"], 1, "agreement total_count")
    echoed = rows[0]
    assert_money(
        echoed["provisional_club_obligation_cents"],
        390000,
        "provisional_club_obligation_cents",
    )
    assert_money(echoed["affiliate_overflow_cents"], 0, "affiliate_overflow_cents")
    assert_integer(echoed["version"], submitted["version"], "AffiliationAgreement.version")
    assert echoed["settlement_status"] == "NOT_SETTLED", (
        f"the read must agree with the write, got {echoed['settlement_status']}"
    )
    assert echoed["final_club_obligation_cents"] is None, (
        f"the read must agree with the write, got {echoed['final_club_obligation_cents']!r}"
    )
    assert echoed["submitted_by_user_id"] == affiliate["id"], (
        f"the submitting operator's id is the club id, got {echoed['submitted_by_user_id']!r}"
    )


# ---------------------------------------------------------------------------
# Instance 2 — the approval response and the next pool read agree on the ledger
# ---------------------------------------------------------------------------


def test_the_approval_response_and_the_next_pool_read_agree_on_the_new_ledger(api: ApiClient):
    """A cross-entity write is visible on the other entity in the very next call.

    PRD 3.9: "The signing's `overage_tax_cents` is the tax on the total overage
    minus the tax on the prior overage, rounded half-up to whole cents once, at
    that subtraction; its `pool_charge_cents` is simply its `bonus_cents`."  A
    single 1200000 bonus against a 1000000 pool leaves a total overage of 200000
    and no prior overage, and PRD 3.9 taxes that first band at "seventy-five
    hundredths of the first five thousand dollars of overage — the portion up to
    500000 cents", which is 150000.  No forfeit applies, because "`tier3_breach`
    is set true when the total overage is strictly above 1000000 cents *and* the
    prior overage was at most 1000000 cents".  The ledger then follows in the
    same transition: "`effective_pool_cents` becomes the base allotment plus the
    trade adjustment minus the now-updated `forfeited_cents`; `allocated_cents`
    becomes the new allocated figure; `remaining_cents` becomes the effective
    pool minus the allocated amount, which may be negative; and the pool's status
    becomes `HARD_CAPPED` when the allocated amount is strictly greater than the
    effective pool, or stays `OPEN` otherwise."

    Design: Corner/consistency_model/approval_response_and_the_next_pool_read_agree_on_the_new_ledger
    """
    fixtures.set_clock(api, "2026-04-01T00:00:00Z")
    academy = fixtures.licensed_academy(
        api,
        affiliate_overrides={
            "name": "Immediate Academy",
            "market_city": "Santiago",
            "meal_stipend_cents_per_day": 2500,
        },
        agreement_overrides={
            "facility_standard_tier": "TIER_2",
            "club_reimbursement_cap_cents": 900000,
            "minimum_active_players": 0,
        },
    )
    pool = fixtures.create_pool(api, season_year=2026, base_pool_cents=1000000)
    assert_status(pool, "OPEN", "SigningPool")
    assert_money(pool["allocated_cents"], 0, "allocated_cents")
    assert_money(pool["effective_pool_cents"], 1000000, "effective_pool_cents")

    player = fixtures.create_player(
        api,
        INTERNATIONAL_SCOUT_HEADERS,
        full_name="Immediate Signing",
        origin="INTERNATIONAL_FA",
        signed_date="2026-01-15",
    )
    signing = fixtures.create_signing(
        api, pool["id"], player["id"], academy["affiliate_id"], bonus_cents=1200000
    )
    assert_status(signing, "SUBMITTED", "InternationalSigning")
    assert_money(signing["pool_charge_cents"], 0, "pool_charge_cents")
    assert_money(signing["overage_tax_cents"], 0, "overage_tax_cents")

    approved = fixtures.dispose_signing(api, signing["id"], "APPROVE")
    assert_status(approved, "APPROVED", "InternationalSigning")
    assert_money(approved["pool_charge_cents"], 1200000, "pool_charge_cents")
    assert_money(approved["overage_tax_cents"], 150000, "overage_tax_cents")
    assert approved["tier3_breach"] is False, (
        f"an overage of 200000 never reaches the third tier, got {approved!r}"
    )
    assert approved["approved_by_user_id"] == COMPLIANCE_OFFICER_USER_ID, (
        f"the approving officer is recorded on the signing, got {approved['approved_by_user_id']!r}"
    )

    ledger = fixtures.read_pool(api, pool["id"])
    assert_money(ledger["allocated_cents"], 1200000, "allocated_cents")
    assert_money(ledger["overage_tax_accrued_cents"], 150000, "overage_tax_accrued_cents")
    assert_money(ledger["effective_pool_cents"], 1000000, "effective_pool_cents")
    assert_money(ledger["remaining_cents"], -200000, "remaining_cents")
    assert_money(ledger["forfeited_cents"], 0, "forfeited_cents")
    assert_status(ledger, "HARD_CAPPED", "SigningPool")

    reread = fixtures.read_signing(api, signing["id"])
    assert_money(reread["pool_charge_cents"], 1200000, "pool_charge_cents")
    assert_money(reread["overage_tax_cents"], 150000, "overage_tax_cents")
    assert reread["tier3_breach"] is False, (
        f"the read path must not recompute the breach flag, got {reread!r}"
    )
    assert_status(reread, "APPROVED", "InternationalSigning")
