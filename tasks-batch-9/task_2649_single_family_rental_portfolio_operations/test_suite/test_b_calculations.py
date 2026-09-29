"""Arithmetic under observation: ranking, clause order, contingency fees and one rounding.

Every number asserted here is one the PRD works out itself, and each test is arranged so a
plausible wrong implementation lands on a *different* number rather than on an error --
price beaten by quality, a clause read in the wrong order, a fee taken off the assessment
reduction instead of off the savings, or a fraud factor rounded before it is weighted.
"""

from test_helpers import factories as f
from test_helpers import fixtures as x
from test_helpers.assertions import (
    assert_fields,
    assert_money_group,
    created,
    ok,
)
from test_helpers.constants import (
    CLOCK_AUG_01,
    FRAUD_VARIANT_POST,
    IDENTITY_VERIFIED,
    OBLIGATION_RESOLVED,
    POSTURE_FROZEN,
    POSTURE_RESTRICTED,
    WO_DISPATCHED,
)
from test_helpers.test_users import make_prospect_headers


def test_the_cheaper_vendor_wins_the_dispatch_and_absorbs_all_nine_crew_days(api):
    """Price beats quality, and only the winner's labour ledger moves.

    PRD SS3.4: "When the payload omits `vendor_id`, the system builds the eligible set from
    every vendor in the home's market that passes all of the clauses above, then prices each
    one: the bid is this work order's `benchmark_total_cents` multiplied by that vendor's
    `cost_index_bps`, divided by 10,000, rounded half up. Ranking is applied in exactly this
    order -- ascending bid first, then descending `quality_score_bps`, then ascending
    `created_at` -- and the first row wins. Price beats quality here: a cheaper vendor with a
    worse quality score is selected over a pricier vendor with a better one. Take a paint work
    order whose `benchmark_total_cents` is 292176: a vendor with `cost_index_bps` 9800 and
    `quality_score_bps` 8600 bids 286332, while a vendor with `cost_index_bps` 10100 and
    `quality_score_bps` 9400 bids 295098, and the first wins despite scoring 800 basis points
    worse on quality."  PRD SS3.4 on the branch: "the work order moves `PENDING_DISPATCH ->
    DISPATCHED`, its `vendor_id` is set to the selected vendor, and that vendor's
    `committed_crew_days` increases by this work order's `crew_days`."  PRD SS2.9: "For every
    vendor, `committed_crew_days` always equals the sum of `crew_days` over that vendor's work
    orders whose `status` is `DISPATCHED` or `ACCEPTED`. ... In-house work never touches this
    figure."  PRD SS3.3 fixes the three computed figures: `crew_days` "equals `crew_size`
    multiplied by the number of whole days in the window counted inclusively at both ends", and
    "a quote of 300000 gives 268 basis points and is accepted against a tolerance of 1000".

    Design: Corner/calculations/dispatch_selects_the_cheapest_bid_over_the_higher_quality_score
    """
    x.set_clock(api, CLOCK_AUG_01)
    market = x.create_market(api)
    paint = x.create_scope_template(api, f.scope_template_paint())
    home = x.create_home(api, market["id"])
    vendors = x.two_certified_vendors(api, market["id"], "PAINT")

    order = created(
        api.create_work_order(
            f.work_order_payload(
                home["id"],
                paint["id"],
                work_type="RESIDENT_MAINTENANCE",
                fulfillment_channel="VENDOR",
            ),
            x.OPS,
        )
    )
    assert_fields(order, crew_days=9, variance_bps=268)
    assert_money_group(order, benchmark_total_cents=292176)

    dispatched = ok(api.dispatch_work_order(order["id"], {}, x.OPS))
    assert_fields(
        dispatched,
        status=WO_DISPATCHED,
        vendor_id=vendors.cheap.vendor_id,
        crew_days=9,
        variance_bps=268,
    )
    assert_money_group(dispatched, benchmark_total_cents=292176)

    assert_fields(
        ok(api.get_vendor(vendors.cheap.vendor_id, x.VENDOR_MANAGER)),
        committed_crew_days=9,
    )
    assert_fields(
        ok(api.get_vendor(vendors.pricey.vendor_id, x.VENDOR_MANAGER)),
        committed_crew_days=0,
    )


def test_the_posture_clauses_report_five_then_four_then_three_and_fall_back(api):
    """The clause number is observable one obligation at a time, and clause 3 falls back to 4.

    PRD SS2.8 fixes the order: "3. Otherwise, if the home has at least one compliance
    obligation whose `severity` is `CRITICAL` and whose `status` is one of `OPEN`, `PLANNED`,
    `RESOLUTION_SUBMITTED` or `RESOLUTION_REJECTED`, the posture is `FROZEN`. 4. Otherwise, if
    the home has at least one compliance obligation whose `severity` is `MAJOR` and whose
    `status` is one of `OPEN`, `PLANNED`, `RESOLUTION_SUBMITTED` or `RESOLUTION_REJECTED`, the
    posture is `RESTRICTED`. 5. Otherwise, if `asset_status` is `PIPELINE` or `ACQUIRED`, the
    posture is `RESTRICTED`."  PRD SS2.8 also fixes what never contributes: "Obligations whose
    `severity` is `MINOR` never affect posture, in any status. Obligations whose `status` is
    `RESOLVED` or `WAIVED` never affect posture, at any severity."  The read is the one
    described as returning "`deciding_clause` as the integer number (1 through 6) of the clause
    that produced it, `blocking_obligation_ids` as the identifiers of the obligations that
    contributed to the decision, and `binder_expired` as a boolean stating whether the second
    clause's condition currently holds", and it "is re-derived at read time".

    Design: Corner/calculations/posture_clause_order_reads_back_as_five_then_four_then_three
    """
    x.set_clock(api, CLOCK_AUG_01)
    market = x.create_market(api)
    home = x.create_home(api, market["id"])

    minor = x.open_obligation(api, home["id"], severity="MINOR")
    only_minor = ok(api.get_leasing_posture(home["id"], x.COMPLIANCE))
    assert_fields(
        only_minor,
        leasing_posture=POSTURE_RESTRICTED,
        deciding_clause=5,
        blocking_obligation_ids=[],
        binder_expired=False,
    )

    major = x.open_obligation(
        api,
        home["id"],
        obligation_type="INSURANCE_DEFICIENCY",
        severity="MAJOR",
        description="Wind deductible too high",
        due_on="2026-11-30",
    )
    with_major = ok(api.get_leasing_posture(home["id"], x.COMPLIANCE))
    assert_fields(
        with_major, leasing_posture=POSTURE_RESTRICTED, deciding_clause=4, binder_expired=False
    )
    assert major["id"] in with_major["blocking_obligation_ids"]
    assert minor["id"] not in with_major["blocking_obligation_ids"]

    critical = x.open_obligation(
        api, home["id"], severity="CRITICAL", description="Structural deck failure"
    )
    with_critical = ok(api.get_leasing_posture(home["id"], x.COMPLIANCE))
    assert_fields(
        with_critical, leasing_posture=POSTURE_FROZEN, deciding_clause=3, binder_expired=False
    )
    # Whether the still-open MAJOR row is also listed while clause 3 decides is not
    # uniquely derivable from PRD SS2.8, so only the two rows the PRD does settle are
    # asserted: the CRITICAL one contributed, and the MINOR one never can.
    assert critical["id"] in with_critical["blocking_obligation_ids"]
    assert minor["id"] not in with_critical["blocking_obligation_ids"]

    ok(api.plan_obligation(critical["id"], f.plan_obligation_payload("2026-08-25"), x.COMPLIANCE))
    ok(
        api.submit_obligation_resolution(
            critical["id"], f.submit_resolution_payload(evidence_ref="deck-permit-901"),
            x.COMPLIANCE,
        )
    )
    assert_fields(
        ok(api.get_leasing_posture(home["id"], x.COMPLIANCE)),
        leasing_posture=POSTURE_FROZEN,
        deciding_clause=3,
    )

    resolved = ok(
        api.review_obligation_resolution(
            critical["id"],
            f.review_resolution_payload("ACCEPT", review_note="Deck rebuilt and inspected"),
            x.DIRECTOR,
        )
    )
    assert_fields(resolved, status=OBLIGATION_RESOLVED)

    fallback = ok(api.get_leasing_posture(home["id"], x.COMPLIANCE))
    assert_fields(
        fallback, leasing_posture=POSTURE_RESTRICTED, deciding_clause=4, binder_expired=False
    )
    assert major["id"] in fallback["blocking_obligation_ids"]
    assert critical["id"] not in fallback["blocking_obligation_ids"]


def test_the_appeal_fee_is_a_share_of_the_savings_not_of_the_reduction(api):
    """40000 of savings, a 12000 fee and a 28000 net -- not the 960000 the reduction implies.

    PRD SS3.9: "`annual_tax_savings_cents` is the home's `assessed_value_cents` **as it stands
    at the moment of acceptance** less the obligation's `settled_value_cents`, multiplied by the
    market's `millage_bps`, divided by 10,000, rounded half up. `consultant_fee_cents` is
    `annual_tax_savings_cents` multiplied by `consultant_fee_bps`, divided by 10,000, rounded
    half up -- the fee is a share of the **savings**, not of the assessment reduction.
    `net_tax_benefit_cents` is `annual_tax_savings_cents` less `consultant_fee_cents`."  And the
    second hop: "The home's `assessed_value_cents` is overwritten with the obligation's
    `settled_value_cents`, and its `property_tax_annual_cents` is recomputed as the new
    `assessed_value_cents` multiplied by `millage_bps`, divided by 10,000, rounded half up."
    Worked through in PRD SS3.9: "a home assessed at 28000000 in a market whose `millage_bps` is
    125 carries a `property_tax_annual_cents` of 350000. The appeal settles at 24800000 with a
    `consultant_fee_bps` of 3000, so the reduction is 3200000, the `annual_tax_savings_cents` is
    40000, the `consultant_fee_cents` is 12000 and the `net_tax_benefit_cents` is 28000. The
    home's `assessed_value_cents` becomes 24800000 and its `property_tax_annual_cents` becomes
    310000."

    Design: Corner/calculations/tax_appeal_money_group_rounds_half_up_at_every_step
    """
    x.set_clock(api, CLOCK_AUG_01)
    market = x.create_market(api)
    home = x.create_home(api, market["id"])
    assert_money_group(
        home, assessed_value_cents=28000000, property_tax_annual_cents=350000
    )

    obligation = x.planned_obligation(
        api,
        home["id"],
        obligation_type="PROPERTY_TAX_APPEAL",
        severity="MINOR",
        planned_resolution_on="2026-10-15",
        description="2026 assessment appeal",
        assessed_value_cents=28000000,
        target_value_cents=24000000,
        consultant_fee_bps=3000,
    )
    ok(
        api.submit_obligation_resolution(
            obligation["id"],
            f.submit_resolution_payload(settled_value_cents=24800000),
            x.COMPLIANCE,
        )
    )

    accepted = ok(
        api.review_obligation_resolution(
            obligation["id"],
            f.review_resolution_payload(
                "ACCEPT", review_note="Board of equalization settled at 24800000"
            ),
            x.DIRECTOR,
        )
    )
    assert_fields(accepted, status=OBLIGATION_RESOLVED)
    assert_money_group(
        accepted,
        settled_value_cents=24800000,
        annual_tax_savings_cents=40000,
        consultant_fee_cents=12000,
        net_tax_benefit_cents=28000,
    )

    # The design index also expects ``hold_sell_score_bps`` to read as null on this home,
    # since it has no APPROVED case; PRD SS3.1 instead says the field starts at 0 while PRD
    # SS3.2 says "it is null while the home has no `APPROVED` case at all", so that one
    # field is left unasserted.
    updated = ok(api.get_home(home["id"], x.COMPLIANCE))
    assert_money_group(
        updated, assessed_value_cents=24800000, property_tax_annual_cents=310000
    )
    assert_fields(updated, leasing_posture=POSTURE_RESTRICTED)


def test_the_fraud_score_is_divided_and_rounded_exactly_once_at_the_end(api):
    """54008000 of weighted products gives 5401, where a per-factor round gives 5400.

    PRD SS3.6: "`fraud_risk_score_bps` is a weighted score in which higher means riskier, built
    from four factors whose weights sum to exactly 10,000: identity at 3500, income at 3000,
    history at 2000 and device at 1500. Every factor is clamped into the range 0 through 10,000
    **before** it is weighted, the four weighted products are summed as raw integers, and the
    sum is divided by 10,000 and rounded half up exactly **once** at the very end -- never per
    factor."  The four factors are the post-verification ones: "The income coverage denominator
    is the market's `rent_index_cents` multiplied by 3, and the income factor is 10,000 less the
    quantity (income multiplied by 10,000, divided by that denominator, rounded half up),
    floored at zero"; "The history factor is the credit-tier risk points -- 500 for `A`, 1500 for
    `B`, 3000 for `C`, 5000 for `D` -- plus `prior_eviction_count` multiplied by 2500, capped at
    10,000"; the post-verification variant "uses `verified_monthly_income_cents` as the income",
    its identity factor "is 10,000 less `document_match_score_bps`, floored at zero", and "Its
    device factor is 10,000 less `device_reputation_bps`, floored at zero, plus a penalty of
    2000 when `ip_geo_distance_km` is **strictly greater** than 100, the whole sum capped at
    10,000."  PRD SS3.6 on the outcome and the stamp: "`identity_status` becomes `VERIFIED` when
    `selfie_liveness_pass` is true **and** `document_match_score_bps` is at or above 5000", and
    "Every one of those attempts rescores the prospect with the post-verification variant and
    stamps `fraud_score_variant` `POST_VERIFICATION`", with "`verification_attempt_count`
    increases by 1".

    Design: Corner/calculations/fraud_score_rounds_once_at_the_end_not_per_factor
    """
    x.set_clock(api, CLOCK_AUG_01)
    market = x.create_market(api)
    prospect = x.create_prospect(
        api,
        market["id"],
        email="p5@example.com",
        full_name="Pia Five",
        phone="+1-404-555-0105",
        declared_monthly_income_cents=157437,
        credit_tier="D",
        prior_eviction_count=0,
    )

    # PRD SS4: an identity-verification attempt modifies the existing prospect row, so the
    # endpoint answers HTTP 200 with the rescored prospect, not 201.
    verified = ok(
        api.verify_identity(
            prospect["id"],
            f.identity_verification_payload(
                prospect["version"],
                document_type="STATE_ID",
                document_match_score_bps=5999,
                selfie_liveness_pass=True,
                verified_monthly_income_cents=157437,
                device_reputation_bps=6999,
                ip_geo_distance_km=400,
            ),
            make_prospect_headers(prospect["id"]),
        )
    )
    assert_fields(
        verified,
        identity_status=IDENTITY_VERIFIED,
        fraud_score_variant=FRAUD_VARIANT_POST,
        fraud_risk_score_bps=5401,
        verification_attempt_count=1,
    )
    assert verified["fraud_risk_score_bps"] != 5400
    assert_money_group(verified, verified_monthly_income_cents=157437)

    stored = ok(api.get_prospect(prospect["id"], x.AGENT))
    assert_fields(
        stored,
        identity_status=IDENTITY_VERIFIED,
        fraud_score_variant=FRAUD_VARIANT_POST,
        fraud_risk_score_bps=5401,
        verification_attempt_count=1,
    )
