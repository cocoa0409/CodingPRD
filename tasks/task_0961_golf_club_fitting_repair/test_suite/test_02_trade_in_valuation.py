"""Trade-in valuation: dual offer bases, pinned per-line rounding, the
decline/re-offer cycle, OCC on offers, and the offer-expiry sweep."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, api_client,
    set_clock, create_customer, create_specialist, create_manager,
    submit_appraisal, issue_offer, accept_appraisal, get_appraisal,
    customer_headers, staff_headers, list_ledger, get_listing_for_appraisal,
)


def _setup_submitted_appraisal(clubs):
    set_clock("2026-05-10T09:00:00Z")
    customer = create_customer()
    specialist = create_specialist()
    appraisal = submit_appraisal(customer, clubs)
    return {"customer": customer, "specialist": specialist, "appraisal": appraisal}


def test_grade_matrix_offer_values_clubs_by_book_and_grade(api):
    """PRD §3.6: "Under `GRADE_MATRIX`, each club's line is its book value
    multiplied by its grade multiplier: book values are 29,999 cents for a
    driver, 21,999 for a fairway wood, 17,999 for a hybrid, 44,999 for an
    iron set, 8,999 for a wedge, and 14,999 for a putter; multipliers are
    sixty percent for grade `A`, forty-five for `B`, thirty for `C`, and
    fifteen for `D`."

    Design: Difficulty/dual_variant_calc/tradein_offer_grade_matrix_vs_market_comp
    """
    ctx = _setup_submitted_appraisal(
        [{"club_type": "DRIVER", "condition_grade": "A"},
         {"club_type": "WEDGE", "condition_grade": "C"}]
    )
    offer = issue_offer(ctx["appraisal"], ctx["specialist"], "GRADE_MATRIX")
    # round(29999*0.60)=17999 + round(8999*0.30)=2700 = 20699.
    assert offer["offered_value_cents"] == 20_699, (
        f"expected GRADE_MATRIX offer 20699, got {offer['offered_value_cents']}"
    )
    assert offer["status"] == "OFFERED"
    assert offer["offer_basis"] == "GRADE_MATRIX"


def test_market_comp_offer_supersedes_grade_matrix(api):
    """PRD §3.6: "Under `MARKET_COMP`, each club's line is its supplied
    comparable multiplied by eighty percent." and "each new offer supersedes
    whatever came before."

    Design: Difficulty/dual_variant_calc/tradein_offer_grade_matrix_vs_market_comp
    """
    ctx = _setup_submitted_appraisal(
        [{"club_type": "DRIVER", "condition_grade": "A"},
         {"club_type": "WEDGE", "condition_grade": "C"}]
    )
    offer1 = issue_offer(ctx["appraisal"], ctx["specialist"], "GRADE_MATRIX")
    assert offer1["offered_value_cents"] == 20_699
    offer2 = issue_offer(offer1, ctx["specialist"], "MARKET_COMP",
                         market_comps_cents=[25_000, 4_000])
    # round(25000*0.8)=20000 + round(4000*0.8)=3200 = 23200.
    assert offer2["offered_value_cents"] == 23_200, (
        f"expected MARKET_COMP offer 23200, got {offer2['offered_value_cents']}"
    )
    assert offer2["status"] == "OFFERED", "second offer supersedes the first"
    assert offer2["offer_basis"] == "MARKET_COMP"


def test_per_line_round_then_sum_pinned_grade_matrix(api):
    """PRD §2.6: "trade-in valuations round each club's line individually
    before summing, so that per-line round-then-sum is the pinned behavior and
    sum-then-round of the same inputs — which can differ by cents — is
    explicitly not the specified behavior."

    Design: Difficulty/combinatorial_formula/tradein_per_line_rounding_pinned
    """
    ctx = _setup_submitted_appraisal(
        [{"club_type": "DRIVER", "condition_grade": "B"},
         {"club_type": "WEDGE", "condition_grade": "D"}]
    )
    offer = issue_offer(ctx["appraisal"], ctx["specialist"], "GRADE_MATRIX")
    # Per-line: round(29999*0.45)=13500 + round(8999*0.15)=1350 = 14850.
    # Forbidden sum-then-round: round(13499.55 + 1349.85) = round(14849.40) = 14849.
    assert offer["offered_value_cents"] == 14_850, (
        f"expected per-line round-then-sum 14850, got {offer['offered_value_cents']}"
    )
    assert offer["offered_value_cents"] != 14_849


def test_per_line_round_then_sum_pinned_market_comp(api):
    """PRD §3.6: "Valuation differs by basis but shares one pinned rounding
    order: every club's line is rounded half-up to integer cents individually,
    and the rounded lines are then summed — never the reverse."

    Design: Difficulty/combinatorial_formula/tradein_per_line_rounding_pinned
    """
    ctx = _setup_submitted_appraisal(
        [{"club_type": "DRIVER", "condition_grade": "A"},
         {"club_type": "WEDGE", "condition_grade": "A"}]
    )
    offer = issue_offer(ctx["appraisal"], ctx["specialist"], "MARKET_COMP",
                        market_comps_cents=[13, 14])
    # Per-line: round(13*0.8)=10 + round(14*0.8)=11 = 21.
    # Forbidden sum-then-round: round(27*0.8) = round(21.6) = 22.
    assert offer["offered_value_cents"] == 21, (
        f"expected per-line round-then-sum 21, got {offer['offered_value_cents']}"
    )
    assert offer["offered_value_cents"] != 22


def test_declined_appraisal_accepts_reoffer(api):
    """PRD §3.6: "an offer may be issued while the appraisal is `SUBMITTED`,
    `OFFERED`, or even `DECLINED`, and each new offer supersedes whatever came
    before."

    Design: Difficulty/non_linear_state_machine/appraisal_decline_reoffer_cycle
    """
    ctx = _setup_submitted_appraisal([{"club_type": "PUTTER", "condition_grade": "B"}])
    offer = issue_offer(ctx["appraisal"], ctx["specialist"], "GRADE_MATRIX")
    declined = get_success_data(
        api_client.decline_appraisal(offer["id"], customer_headers(ctx["customer"]))
    )
    assert declined["status"] == "DECLINED"
    reoffer = issue_offer(declined, ctx["specialist"], "MARKET_COMP",
                          market_comps_cents=[12_000])
    assert reoffer["status"] == "OFFERED", "cycle DECLINED -> OFFERED must succeed"
    # round(12000*0.8) = 9600.
    assert reoffer["offered_value_cents"] == 9_600, (
        f"expected re-offer value 9600, got {reoffer['offered_value_cents']}"
    )


def test_decline_reoffer_cycle_increments_version(api):
    """PRD §2.4: "The `version` of an entity increments by exactly one on every
    mutation of that entity, including mutations caused by state transitions".
    PRD §3.6: "the appraisal moves to `OFFERED` with its `version` incremented."

    Design: Difficulty/non_linear_state_machine/appraisal_decline_reoffer_cycle
    """
    ctx = _setup_submitted_appraisal([{"club_type": "PUTTER", "condition_grade": "B"}])
    offer = issue_offer(ctx["appraisal"], ctx["specialist"], "GRADE_MATRIX")
    declined = get_success_data(
        api_client.decline_appraisal(offer["id"], customer_headers(ctx["customer"]))
    )
    reoffer = issue_offer(declined, ctx["specialist"], "MARKET_COMP",
                          market_comps_cents=[12_000])
    assert reoffer["version"] == declined["version"] + 1, (
        f"re-offer must increment version from {declined['version']} to "
        f"{declined['version'] + 1}, got {reoffer['version']}"
    )


def test_occ_stale_offer_version_rejected(api):
    """PRD §2.7: "issuing an offer requires `expected_appraisal_version`
    matching the appraisal's current `version`, and a mismatch is rejected
    with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/complexity_layers/occ_stale_offer_version_rejected
    """
    ctx = _setup_submitted_appraisal([{"club_type": "DRIVER", "condition_grade": "B"}])
    offer = issue_offer(ctx["appraisal"], ctx["specialist"], "GRADE_MATRIX")
    stale_version = ctx["appraisal"]["version"]  # pre-offer version

    resp = api_client.create_offer(
        ctx["appraisal"]["id"],
        {"basis": "MARKET_COMP", "market_comps_cents": [20_000],
         "expected_appraisal_version": stale_version},
        staff_headers(ctx["specialist"]),
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

    surviving = get_appraisal(ctx["appraisal"]["id"], staff_headers(ctx["specialist"]))
    assert surviving["version"] == offer["version"], "stale offer must not mutate"
    # Surviving first offer: round(29999*0.45) = 13500.
    assert surviving["offered_value_cents"] == 13_500, (
        f"expected surviving offer 13500, got {surviving['offered_value_cents']}"
    )


def test_offer_expiry_sweep_then_accept_rejected(api):
    """PRD §3.6: "An offer left unanswered past `offer_expires_at` is swept by
    the clock to `EXPIRED`." and "The customer answers from `OFFERED` — accept
    or decline attempted in any other state earns `ERR_APPRAISAL_NOT_OFFERED`."
    PRD §2.5: "`offer_expires_at` is set to the offer instant plus 168 hours" (§3.6).

    Design: Corner/state_machines/offer_expiry_sweep_via_clock
    """
    ctx = _setup_submitted_appraisal([{"club_type": "DRIVER", "condition_grade": "A"}])
    offer = issue_offer(ctx["appraisal"], ctx["specialist"], "GRADE_MATRIX")
    assert offer["status"] == "OFFERED"

    # Offer made at 2026-05-10T09:00:00Z expires at 2026-05-17T09:00:00Z.
    set_clock("2026-05-18T09:00:00Z")
    swept = get_appraisal(offer["id"], staff_headers(ctx["specialist"]))
    assert swept["status"] == "EXPIRED", (
        f"expected EXPIRED after the clock passed offer_expires_at, got {swept['status']}"
    )

    resp = api_client.accept_appraisal(offer["id"], customer_headers(ctx["customer"]))
    validate_error(resp, ApiErrorId.ERR_APPRAISAL_NOT_OFFERED)

    # No credit was granted and no listing was created for this appraisal.
    ledger = list_ledger(ctx["customer"]["id"])
    assert ledger == [], f"expected no ledger entries, got {ledger}"
    manager = create_manager()
    listings = get_success_data(
        api_client.list_listings(staff_headers(manager),
                                 params={"appraisal_id": offer["id"]})
    )
    assert listings == [], f"expected no listings, got {listings}"
