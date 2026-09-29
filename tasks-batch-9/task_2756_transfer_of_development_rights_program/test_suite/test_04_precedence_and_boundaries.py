"""Evaluation-ladder precedence and inclusive/exclusive boundary behaviour.

Two competing-rejection scenarios pin the §2.10 ladder where the PRD fixes the
winner: a state precondition must outrank a fiscal check on a double settlement,
and the certificate-compliance safety check must outrank the unit-availability
constraint on a proposal that is both frozen and oversized.  Two boundary
scenarios probe the exact edge of a limit: the inclusive absorption cap at
finalization, measured in whole development-right units, and the exclusive upper
edge of an appraisal window, measured on the logical clock to the second.

Every test builds its own registry state from scratch through the API.
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    assert_certificate_units_conserved,
    assert_market_transaction,
    assert_same_instant,
    allocate_redemption,
    cancel_transaction,
    create_active_receiving_area,
    create_market_transaction_payload,
    credit_party,
    fetch_certificate,
    fetch_easement,
    fetch_party,
    fetch_receiving_area,
    fetch_receiving_site_application,
    fetch_redemption,
    fetch_transaction,
    file_receiving_site_application,
    finalize_application,
    get_success_data,
    make_developer_headers,
    make_landowner_headers,
    publish_appraisal_schedule,
    register_bank,
    register_developer,
    set_clock,
    setup_certified_severance,
    setup_developer_holding_certificate,
    setup_frozen_certificate,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]

CLOCK = "2026-08-10T00:00:00Z"
CERTIFICATE_UNITS = 22
AGREED_PRICE_CENTS = 30_000_000
# 1,234,567 cents per unit lifted by 250 bps rounds half up to 1,265,431 cents.
EXPECTED_PER_UNIT_CENTS = 1_265_431
EXPECTED_REFERENCE_CENTS = 27_839_482
EXPECTED_DEVIATION_BPS = 776
# A 30,000,000 cent gross sits above the 25,000,000 cent tier boundary, so the
# program fee is 200 bps; an UNDERSERVED origin tier carries no surcharge.
EXPECTED_PROGRAM_FEE_CENTS = 600_000
EXPECTED_SURCHARGE_CENTS = 0
EXPECTED_NET_TO_SELLER_CENTS = 29_400_000


class TestSettlementStatePrecedesFundsCheck:
    """A second settlement of an already-SETTLED deal trips two rules at once."""

    def test_second_settlement_reports_the_state_error_not_the_funds_error(self):
        """The buyer was credited exactly the gross price, so the first settlement
        drained the balance to zero and the fiscal check would also fail — but the
        transaction is no longer PROPOSED, and that rung sits far higher.

        PRD §2.10: "The checks below form one global ladder, evaluated strictly from the top; the first check that fails decides the response, and no later check is consulted."
        PRD §2.10 rung 18: "The market transaction is `PROPOSED` before settlement or cancellation; otherwise `ERR_TRANSACTION_NOT_PROPOSED` (409)."
        PRD §2.10 rung 45: "**Funds** — at settlement the buyer's `cash_balance_cents` is at least `gross_price_cents`; at reversal the seller's `cash_balance_cents` is at least `net_to_seller_cents` and the municipal bank's `fee_revenue_cents` is at least `program_fee_cents` plus `equity_surcharge_cents`; and a debit account action may not drive a balance below zero. A failure is `ERR_INSUFFICIENT_FUNDS` (402). Applies to settlement, reversal, and party account actions."
        PRD §5: "When more than one condition holds, the identifier returned is the one belonging to the lowest-numbered rung of the evaluation ladder in §2.10."

        Design: Difficulty/priority_pair_validation_conflict/state_error_precedes_fiscal_error_on_double_settlement
        """
        scenario = setup_developer_holding_certificate()
        buyer = fetch_party(scenario["developer"]["id"])
        assert buyer["cash_balance_cents"] == 0, (
            "setup expects the buyer drained to exactly zero by the first settlement, got "
            f"{buyer['cash_balance_cents']}"
        )

        resp = api_client.settle_market_transaction(scenario["transaction"]["id"], ADMIN, {})

        validate_error(resp, ApiErrorId.ERR_TRANSACTION_NOT_PROPOSED.value)
        assert resp.json()["data"]["error_id"] != ApiErrorId.ERR_INSUFFICIENT_FUNDS.value, (
            "the state precondition at rung 18 must decide the response, not the funds "
            "check at rung 45"
        )

    def test_rejected_second_settlement_moves_no_cash_and_leaves_the_first_intact(self):
        """The rejected retry is a no-op: the settled split stands, each of the three
        cash legs ran exactly once, and title stays where the first settlement put it.

        PRD §3.7: "First, a fee rate is selected by tier from `gross_price_cents` itself, never from any post-surcharge figure: a gross of at most 5,000,000 cents — fifty thousand dollars — attracts 350 basis points; a gross above that but at most 25,000,000 cents — two hundred fifty thousand dollars — attracts 275 basis points; anything above that attracts 200 basis points."
        PRD §3.7: "Third, `equity_surcharge_cents` is `gross_price_cents` multiplied by a surcharge rate divided by ten thousand, rounded half up to whole cents, where the surcharge rate comes from the `equity_tier` of the sending area named by the certificate's `origin_sending_area_id`: 150 basis points for `HIGH_VALUE`, 75 basis points for `MODERATE`, and 0 basis points for `UNDERSERVED`, so preserving land in an underserved neighborhood carries no surcharge at all."
        PRD §3.7: "Fourth, `net_to_seller_cents` is `gross_price_cents` less `program_fee_cents` less `equity_surcharge_cents`."
        PRD §3.7: "Cash then moves in three legs that sum to zero, as §2.11 requires: the buyer's `cash_balance_cents` is reduced by `gross_price_cents`, the seller's `cash_balance_cents` is increased by `net_to_seller_cents`, and the `MUNICIPAL_BANK` party's `fee_revenue_cents` is increased by `program_fee_cents` plus `equity_surcharge_cents`."
        PRD §3.7: "When the traded `units` equal the certificate's `units_remaining`, `conveyance_mode` is pinned to `WHOLE`: the certificate itself changes hands, its `holder_party_id` becomes `buyer_party_id`, and `conveyed_certificate_id` is set to the traded `certificate_id`."

        Design: Difficulty/priority_pair_validation_conflict/state_error_precedes_fiscal_error_on_double_settlement
        """
        scenario = setup_developer_holding_certificate()

        api_client.settle_market_transaction(scenario["transaction"]["id"], ADMIN, {})

        transaction = fetch_transaction(scenario["transaction"]["id"])
        assert_market_transaction(transaction)
        assert transaction["status"] == "SETTLED", (
            f"the transaction must still be SETTLED, got {transaction['status']}"
        )
        assert transaction["gross_price_cents"] == AGREED_PRICE_CENTS, (
            f"gross_price_cents must be the agreed price, got {transaction['gross_price_cents']}"
        )
        assert transaction["program_fee_cents"] == EXPECTED_PROGRAM_FEE_CENTS, (
            "a 30,000,000 cent gross attracts 200 bps, so the fee is 600,000 cents, got "
            f"{transaction['program_fee_cents']}"
        )
        assert transaction["equity_surcharge_cents"] == EXPECTED_SURCHARGE_CENTS, (
            "an UNDERSERVED origin tier carries no surcharge, got "
            f"{transaction['equity_surcharge_cents']}"
        )
        assert transaction["net_to_seller_cents"] == EXPECTED_NET_TO_SELLER_CENTS, (
            "net_to_seller_cents must be 30,000,000 less 600,000 less 0, got "
            f"{transaction['net_to_seller_cents']}"
        )

        buyer = fetch_party(scenario["developer"]["id"])
        seller = fetch_party(scenario["landowner"]["id"])
        bank = fetch_party(scenario["bank"]["id"])
        assert buyer["cash_balance_cents"] == 0, (
            f"the buyer must not be debited twice, got {buyer['cash_balance_cents']}"
        )
        assert seller["cash_balance_cents"] == EXPECTED_NET_TO_SELLER_CENTS, (
            f"the seller must not be credited twice, got {seller['cash_balance_cents']}"
        )
        assert bank["fee_revenue_cents"] == EXPECTED_PROGRAM_FEE_CENTS, (
            f"the bank must not accrue the fee twice, got {bank['fee_revenue_cents']}"
        )

        certificate = fetch_certificate(scenario["certificate"]["id"])
        assert certificate["holder_party_id"] == scenario["developer"]["id"], (
            "the whole-conveyance certificate must still be held by the buyer"
        )
        assert certificate["market_status"] == "HELD", (
            f"the certificate's market_status must be HELD, got {certificate['market_status']}"
        )


def _frozen_certificate_with_funded_buyer() -> dict:
    """A landowner holding a 22-unit certificate whose source easement has been
    driven to VIOLATION_NOTICED by a MAJOR_VIOLATION inspection, plus a developer
    funded well past the asking price and an appraisal schedule covering the clock.

    Funds and pricing are therefore never the binding constraint on the proposal
    the tests below file.
    """
    scenario = setup_frozen_certificate()
    developer = register_developer(neighborhood_code="NB-CORE")
    bank = register_bank(neighborhood_code="NB-CORE")
    schedule = publish_appraisal_schedule(
        neighborhood_code=scenario["area"]["neighborhood_code"],
        per_unit_value_cents=1_234_567,
        equity_adjustment_bps=250,
        effective_from="2026-01-01",
        effective_to="2027-01-01",
    )
    credit_party(developer["id"], 40_000_000)
    assert scenario["certificate"]["market_status"] == "FROZEN", (
        "setup expects a FROZEN certificate, got "
        f"{scenario['certificate']['market_status']}"
    )
    assert scenario["certificate"]["units_remaining"] == CERTIFICATE_UNITS, (
        f"setup expects 22 remaining units, got {scenario['certificate']['units_remaining']}"
    )
    scenario.update({"developer": developer, "bank": bank, "schedule": schedule})
    return scenario


def _propose_oversized_deal_on(scenario: dict):
    """Propose 25 units of the scenario's 22-unit certificate, filed by the selling
    landowner, so the frozen-rights check and the unit-availability check both fail."""
    payload = create_market_transaction_payload(
        scenario["certificate"]["id"],
        scenario["landowner"]["id"],
        scenario["developer"]["id"],
        units=25,
        channel="PRIVATE",
        conveyance_mode="PARTIAL",
        agreed_price_cents=AGREED_PRICE_CENTS,
    )
    return api_client.create_market_transaction(
        payload, make_landowner_headers(scenario["landowner"]["id"])
    )


class TestFrozenRightsPrecedeUnitAvailability:
    """A proposal that is both frozen and oversized reports the safety error."""

    def test_frozen_certificate_outranks_insufficient_units_and_transferability(self):
        """25 units are asked of a 22-unit certificate whose easement is out of
        compliance.  The compliance check decides, and the transferability rung above
        it deliberately lets a FROZEN certificate through.

        PRD §2.10: "Authentication precedes authorization, existence precedes ownership, safety precedes constraint, and fiscal checks always come last."
        PRD §2.10 rung 20: "The certificate's `lifecycle_status` is `ISSUED` or `PARTIALLY_REDEEMED` and its `market_status` is not `UNDER_CONTRACT`; otherwise `ERR_CERTIFICATE_NOT_TRANSFERABLE` (409). Applies to transaction proposal, certificate split, certificate retirement, and redemption allocation. A `FROZEN` certificate is deliberately **not** caught here: it passes this rung and is stopped by the compliance check at rung 24, so the safety error is the one the caller sees."
        PRD §2.10 rung 24: "**Certificate compliance** — the certificate's source `ConservationEasement` has `compliance_status` of either `COMPLIANT` or `CURED`; a `VIOLATION_NOTICED`, `UNDER_CURE` or `ESCALATED` easement freezes its rights and the request is rejected with `ERR_CERTIFICATE_FROZEN` (409). Applies to transaction proposal, certificate split, and redemption allocation."
        PRD §2.10 rung 39: "The requested units are available on the certificate; otherwise `ERR_INSUFFICIENT_CERTIFICATE_UNITS` (422). Applies to transaction proposal, redemption allocation, and certificate retirement."

        Design: Difficulty/priority_pair_validation_conflict/safety_error_precedes_constraint_error_on_frozen_oversized_proposal
        """
        scenario = _frozen_certificate_with_funded_buyer()

        resp = _propose_oversized_deal_on(scenario)

        validate_error(resp, ApiErrorId.ERR_CERTIFICATE_FROZEN.value)
        error_id = resp.json()["data"]["error_id"]
        assert error_id != ApiErrorId.ERR_INSUFFICIENT_CERTIFICATE_UNITS.value, (
            "the safety check at rung 24 must outrank the unit-availability constraint "
            "at rung 39 even though 25 units exceed the 22 available"
        )
        assert error_id != ApiErrorId.ERR_CERTIFICATE_NOT_TRANSFERABLE.value, (
            "a FROZEN certificate is not caught by the transferability rung"
        )

    def test_rejected_frozen_proposal_leaves_the_registry_and_the_buyer_untouched(self):
        """The rejection commits nothing: no transaction row exists on the certificate,
        its rights stay unencumbered and frozen, and no cash moved.

        PRD §2.7: "A single request in this program routinely rewrites several entities. When it does, the whole cascade is part of that request: it is applied before the response is returned, in the order the workflow narrative gives, and every entity it touches has its `version` incremented by one and its `updated_at` refreshed."
        PRD §3.7: "An accepted proposal opens in `status` `PROPOSED`, moves the certificate `HELD → UNDER_CONTRACT`, grows the certificate's `units_encumbered` by the traded `units`, and increments the certificate's `version`."
        PRD §2.10 rung 24: "**Certificate compliance** — the certificate's source `ConservationEasement` has `compliance_status` of either `COMPLIANT` or `CURED`; a `VIOLATION_NOTICED`, `UNDER_CURE` or `ESCALATED` easement freezes its rights and the request is rejected with `ERR_CERTIFICATE_FROZEN` (409). Applies to transaction proposal, certificate split, and redemption allocation."

        Design: Difficulty/priority_pair_validation_conflict/safety_error_precedes_constraint_error_on_frozen_oversized_proposal
        """
        scenario = _frozen_certificate_with_funded_buyer()

        _propose_oversized_deal_on(scenario)

        listing = api_client.list_market_transactions(
            ADMIN, params={"certificate_id": scenario["certificate"]["id"],
                           "limit": 100, "offset": 0},
        )
        validate_paginated(listing)
        assert listing.json()["meta"]["total_count"] == 0, (
            "a rejected proposal must create no MarketTransaction row, listing reported "
            f"{listing.json()['meta']['total_count']}"
        )

        certificate = fetch_certificate(scenario["certificate"]["id"])
        assert_certificate_units_conserved(certificate)
        assert certificate["market_status"] == "FROZEN", (
            f"the certificate must stay FROZEN, got {certificate['market_status']}"
        )
        assert certificate["units_encumbered"] == 0, (
            f"no units may be encumbered by a rejected proposal, got {certificate['units_encumbered']}"
        )
        assert certificate["units_remaining"] == CERTIFICATE_UNITS, (
            f"units_remaining must stay at 22, got {certificate['units_remaining']}"
        )

        easement = fetch_easement(scenario["easement"]["id"])
        assert easement["compliance_status"] == "VIOLATION_NOTICED", (
            f"the easement must stay VIOLATION_NOTICED, got {easement['compliance_status']}"
        )
        buyer = fetch_party(scenario["developer"]["id"])
        assert buyer["cash_balance_cents"] == 40_000_000, (
            f"the buyer's balance must be untouched, got {buyer['cash_balance_cents']}"
        )


CONFIRMED_UNITS = 5


def _two_capped_receiving_areas() -> dict:
    """One developer-held 22-unit certificate backing two identical 4.00-acre
    receiving-site applications, each in its own ACTIVE receiving area: RA-EXACT
    caps absorption at 5 units and RA-TIGHT at 4.

    4.00 acres takes the 0.90 site tier factor, so `base_units` is floor(4.00 x 4.00)
    = 16 and `max_bonus_units` is floor(16 x 0.35 x 0.90) = 5, which is also
    `required_backing_units` for a 5-unit request.  Each application carries one
    5-unit redemption drawn from the same certificate.
    """
    scenario = setup_developer_holding_certificate()
    developer_id = scenario["developer"]["id"]
    area_kwargs = {
        "neighborhood_code": "NB-CORE",
        "base_density_units_per_acre": 4.00,
        "max_bonus_pct": 0.35,
        "design_review_required": False,
        "eligible_sending_area_codes": [],
    }
    area_exact = create_active_receiving_area(
        code="RA-EXACT", name="Exact Cap Area", absorption_cap_units=5, **area_kwargs
    )
    area_tight = create_active_receiving_area(
        code="RA-TIGHT", name="Tight Cap Area", absorption_cap_units=4, **area_kwargs
    )

    rsa_exact = file_receiving_site_application(developer_id, area_exact["id"], 4.00, 5)
    redemption_exact = allocate_redemption(
        rsa_exact["id"], developer_id, scenario["certificate"]["id"], CONFIRMED_UNITS
    )
    rsa_tight = file_receiving_site_application(developer_id, area_tight["id"], 4.00, 5)
    redemption_tight = allocate_redemption(
        rsa_tight["id"], developer_id, scenario["certificate"]["id"], CONFIRMED_UNITS
    )

    for rsa in (rsa_exact, rsa_tight):
        assert rsa["base_units"] == 16, f"setup expects base_units 16, got {rsa['base_units']}"
        assert rsa["max_bonus_units"] == 5, (
            f"setup expects max_bonus_units 5, got {rsa['max_bonus_units']}"
        )
        assert rsa["required_backing_units"] == 5, (
            f"setup expects required_backing_units 5, got {rsa['required_backing_units']}"
        )
        assert rsa["status"] == "DESIGN_APPROVED", (
            f"setup expects a DESIGN_APPROVED application, got {rsa['status']}"
        )
    scenario.update({
        "area_exact": area_exact,
        "area_tight": area_tight,
        "rsa_exact": rsa_exact,
        "rsa_tight": rsa_tight,
        "redemption_exact": redemption_exact,
        "redemption_tight": redemption_tight,
    })
    return scenario


class TestAbsorptionCapUnitBoundary:
    """Five confirmed units against a cap of five, then against a cap of four."""

    def test_finalization_landing_exactly_on_the_cap_succeeds_and_suspends_the_area(self):
        """Absorbing 5 units into an area capped at 5 is inside the inclusive boundary,
        and the area is suspended by landing on it.

        PRD §3.8: "Capacity is checked last: the area's `absorbed_units` plus the units about to be confirmed must not exceed `absorption_cap_units`, otherwise `ERR_ABSORPTION_CAP_EXCEEDED`. That boundary is inclusive — landing exactly on the cap succeeds, one unit beyond it fails."
        PRD §3.8: "Each confirmation moves its units out of the certificate's `units_encumbered` and into `units_redeemed`, moves the same units out of the area's `reserved_units` and into `absorbed_units`, increases the source easement's `units_redeemed_confirmed` and decreases its `units_outstanding` by the same amount, appends a `REDEMPTION` chain-of-title row, and advances the certificate's `lifecycle_status` — `ISSUED → PARTIALLY_REDEEMED` when part of the certificate survives, or straight to `REDEEMED` when the confirmation consumes everything that remained."
        PRD §3.8: "The final variant, used only at finalization, drops the half-release cap and writes `allocated_bonus_units` as the smallest of `requested_bonus_units`, `max_bonus_units`, and `backed_units`."
        PRD §3.8: "When the recomputed `absorbed_units` has reached `absorption_cap_units`, the area itself takes `ACTIVE → SUSPENDED` in the same request, after which further filings against it are refused with `ERR_RECEIVING_AREA_NOT_ACTIVE` while applications already in flight keep their status."
        PRD §3.8: "every redemption still in `ALLOCATED` moves `ALLOCATED → CONFIRMED` in ascending `allocated_at` order with ties broken by ascending `created_at`, each taking `confirmed_at` from the current logical clock."

        Design: Difficulty/boundary_precision_check/absorption_cap_inclusive_unit_boundary_at_finalization
        """
        scenario = _two_capped_receiving_areas()

        finalized = finalize_application(
            scenario["rsa_exact"]["id"], scenario["developer"]["id"]
        )

        assert finalized["status"] == "FINALIZED", (
            f"finalizing onto the exact cap must succeed, got {finalized['status']}"
        )
        assert finalized["allocated_bonus_units"] == 5, (
            "allocated_bonus_units is the smallest of 5 requested, 5 max and 5 backed, got "
            f"{finalized['allocated_bonus_units']}"
        )
        assert finalized["backed_units"] == 5, (
            f"the confirmed redemption must count as backing, got {finalized['backed_units']}"
        )
        assert finalized["pending_backed_units"] == 0, (
            f"no redemption remains pending, got {finalized['pending_backed_units']}"
        )

        redemption = fetch_redemption(scenario["redemption_exact"]["id"])
        assert redemption["status"] == "CONFIRMED", (
            f"the ALLOCATED redemption must be confirmed, got {redemption['status']}"
        )
        assert_same_instant(
            redemption["confirmed_at"], CLOCK, "CertificateRedemption.confirmed_at"
        )

        area = fetch_receiving_area(scenario["area_exact"]["id"])
        assert area["absorbed_units"] == 5, (
            f"absorbed_units must reach the cap of 5, got {area['absorbed_units']}"
        )
        assert area["reserved_units"] == 0, (
            f"the confirmed units leave reserved_units, got {area['reserved_units']}"
        )
        assert area["status"] == "SUSPENDED", (
            "landing exactly on the absorption cap must suspend the area, got "
            f"{area['status']}"
        )

    def test_finalization_one_unit_beyond_the_cap_is_rejected(self):
        """The same 5 confirmed units against a cap of 4 sit one unit past the
        boundary, and nothing about the second application or its area moves.

        PRD §3.8: "Capacity is checked last: the area's `absorbed_units` plus the units about to be confirmed must not exceed `absorption_cap_units`, otherwise `ERR_ABSORPTION_CAP_EXCEEDED`. That boundary is inclusive — landing exactly on the cap succeeds, one unit beyond it fails."
        PRD §3.8: "Sufficiency is checked second: `backed_units` plus `pending_backed_units` must be at least `required_backing_units`, otherwise `ERR_BACKING_INSUFFICIENT`."
        PRD §3.8: "`FINALIZED` and `DENIED` are both terminal."

        Design: Difficulty/boundary_precision_check/absorption_cap_inclusive_unit_boundary_at_finalization
        """
        scenario = _two_capped_receiving_areas()
        finalize_application(scenario["rsa_exact"]["id"], scenario["developer"]["id"])

        resp = api_client.finalize_receiving_site_application(
            scenario["rsa_tight"]["id"],
            make_developer_headers(scenario["developer"]["id"]), {},
        )

        validate_error(resp, ApiErrorId.ERR_ABSORPTION_CAP_EXCEEDED.value)

        rsa = fetch_receiving_site_application(scenario["rsa_tight"]["id"])
        assert rsa["status"] == "DESIGN_APPROVED", (
            f"the rejected application must stay DESIGN_APPROVED, got {rsa['status']}"
        )
        assert rsa["allocated_bonus_units"] == 0, (
            f"no bonus may be granted by a rejected finalization, got {rsa['allocated_bonus_units']}"
        )

        redemption = fetch_redemption(scenario["redemption_tight"]["id"])
        assert redemption["status"] == "ALLOCATED", (
            f"the redemption must stay ALLOCATED, got {redemption['status']}"
        )

        area = fetch_receiving_area(scenario["area_tight"]["id"])
        assert area["absorbed_units"] == 0, (
            f"nothing may be absorbed, got {area['absorbed_units']}"
        )
        assert area["reserved_units"] == 5, (
            f"the 5 committed units stay reserved, got {area['reserved_units']}"
        )
        assert area["status"] == "ACTIVE", (
            f"an area that absorbed nothing stays ACTIVE, got {area['status']}"
        )

    def test_only_the_admitted_finalization_moves_the_certificate_and_easement_ledgers(self):
        """Across both finalizations exactly 5 of the certificate's 22 units are
        consumed, 5 stay committed to the rejected application, and the easement's
        conservation identity still holds.

        PRD §3.8: "Each confirmation moves its units out of the certificate's `units_encumbered` and into `units_redeemed`, moves the same units out of the area's `reserved_units` and into `absorbed_units`, increases the source easement's `units_redeemed_confirmed` and decreases its `units_outstanding` by the same amount, appends a `REDEMPTION` chain-of-title row, and advances the certificate's `lifecycle_status` — `ISSUED → PARTIALLY_REDEEMED` when part of the certificate survives, or straight to `REDEEMED` when the confirmation consumes everything that remained."
        PRD §2.11: "For any single certificate, `units_remaining` equals `units_face` less `units_split_out` less `units_redeemed` less `units_retired`, and `units_encumbered` never exceeds `units_remaining`."
        PRD §2.11: "For any single easement, `units_issued_total` equals `units_redeemed_confirmed` plus `units_retired` plus `units_outstanding` — equivalently, `units_outstanding` is the total face value of the root issuances backed by that easement, less everything redeemed and everything retired across the easement's entire certificate lineage including every split child."

        Design: Difficulty/boundary_precision_check/absorption_cap_inclusive_unit_boundary_at_finalization
        """
        scenario = _two_capped_receiving_areas()

        finalize_application(scenario["rsa_exact"]["id"], scenario["developer"]["id"])
        api_client.finalize_receiving_site_application(
            scenario["rsa_tight"]["id"],
            make_developer_headers(scenario["developer"]["id"]), {},
        )

        certificate = fetch_certificate(scenario["certificate"]["id"])
        assert_certificate_units_conserved(certificate)
        assert certificate["units_redeemed"] == 5, (
            f"only the admitted finalization consumed units, got {certificate['units_redeemed']}"
        )
        assert certificate["units_encumbered"] == 5, (
            "the rejected application's 5 units stay encumbered, got "
            f"{certificate['units_encumbered']}"
        )
        assert certificate["units_remaining"] == 17, (
            f"units_remaining must be 22 less the 5 redeemed, got {certificate['units_remaining']}"
        )
        assert certificate["lifecycle_status"] == "PARTIALLY_REDEEMED", (
            "part of the certificate survives the confirmation, got "
            f"{certificate['lifecycle_status']}"
        )

        easement = fetch_easement(scenario["easement"]["id"])
        assert easement["units_redeemed_confirmed"] == 5, (
            f"units_redeemed_confirmed must be 5, got {easement['units_redeemed_confirmed']}"
        )
        assert easement["units_outstanding"] == 17, (
            f"units_outstanding must fall to 17, got {easement['units_outstanding']}"
        )


WINDOW_END_DATE = "2026-09-01"
ONE_SECOND_INSIDE = "2026-08-31T23:59:59Z"
WINDOW_END_INSTANT = "2026-09-01T00:00:00Z"


def _certificate_with_a_lapsing_schedule() -> dict:
    """A landowner-held 22-unit certificate whose origin neighborhood is covered by
    a single ACTIVE appraisal schedule running [2026-01-01, 2026-09-01).

    The schedule prices a right at 1,234,567 cents with a +250 bps equity
    adjustment, so the equity-adjusted per-unit figure is 1,265,431 cents and the
    22-unit appraised reference is 27,839,482 cents.  A 30,000,000 cent private
    deal sits 776 bps above that reference, well inside the band, so the only
    thing that can decide the proposal is whether the clock still falls inside the
    schedule's window.
    """
    scenario = setup_certified_severance()
    developer = register_developer(neighborhood_code="NB-CORE")
    register_bank(neighborhood_code="NB-CORE")
    credit_party(developer["id"], 40_000_000)
    schedule = publish_appraisal_schedule(
        neighborhood_code=scenario["area"]["neighborhood_code"],
        per_unit_value_cents=1_234_567,
        equity_adjustment_bps=250,
        effective_from="2026-01-01",
        effective_to=WINDOW_END_DATE,
    )
    assert schedule["status"] == "ACTIVE", (
        f"setup expects a freshly published ACTIVE schedule, got {schedule['status']}"
    )
    certificate = fetch_certificate(scenario["certificate"]["id"])
    assert certificate["units_remaining"] == CERTIFICATE_UNITS, (
        f"setup expects 22 tradable units, got {certificate['units_remaining']}"
    )
    scenario.update({"developer": developer, "schedule": schedule})
    return scenario


def _propose_whole_certificate(scenario: dict):
    """File the 22-unit, 30,000,000 cent PRIVATE deal as the selling landowner."""
    payload = create_market_transaction_payload(
        scenario["certificate"]["id"],
        scenario["landowner"]["id"],
        scenario["developer"]["id"],
        units=CERTIFICATE_UNITS,
        channel="PRIVATE",
        agreed_price_cents=AGREED_PRICE_CENTS,
    )
    return api_client.create_market_transaction(
        payload, make_landowner_headers(scenario["landowner"]["id"])
    )


class TestAppraisalWindowHalfOpenUpperBound:
    """One second before `effective_to` the schedule still prices a deal; at
    `effective_to` exactly, no schedule qualifies at all."""

    def test_proposal_one_second_before_the_window_end_is_priced_by_the_schedule(self):
        """At 2026-08-31T23:59:59Z the clock is still strictly before the exclusive
        2026-09-01 end, so the schedule applies and the deal prices normally.

        PRD §3.4: "The applicable schedules are those whose `neighborhood_code` equals the certificate's `origin_neighborhood_code` — the neighborhood the **rights** came from, never the buyer's neighborhood and never the receiving area's — whose `status` is `ACTIVE`, and whose window covers the current logical clock, meaning the clock is at or after `effective_from` and strictly before `effective_to`."
        PRD §3.4: "`applied_neighborhood_code` records the certificate's `origin_neighborhood_code`. `applied_per_unit_value_cents` is the selected schedule's `per_unit_value_cents` multiplied by one plus its `equity_adjustment_bps` divided by ten thousand, rounded half up to a whole number of cents — the rounding happens on the per-unit figure, before any multiplication by units. `appraised_reference_cents` is then `applied_per_unit_value_cents` multiplied by `units`."
        PRD §3.4: "`price_deviation_bps` is the difference between `gross_price_cents` and `appraised_reference_cents`, divided by `appraised_reference_cents`, multiplied by ten thousand, and rounded half up to a whole number of basis points; it is signed, so a below-appraisal deal reports a negative figure."
        PRD §3.4: "An accepted proposal opens in `status` `PROPOSED`, moves the certificate `HELD → UNDER_CONTRACT`, grows the certificate's `units_encumbered` by the traded `units`, and increments the certificate's `version`."

        Design: Difficulty/boundary_precision_check/appraisal_window_half_open_upper_bound_at_one_second_precision
        """
        scenario = _certificate_with_a_lapsing_schedule()
        set_clock(ONE_SECOND_INSIDE)

        resp = _propose_whole_certificate(scenario)

        transaction = validate_success(resp, 201)
        assert transaction["status"] == "PROPOSED", (
            f"a proposal inside the window must open PROPOSED, got {transaction['status']}"
        )
        assert transaction["applied_neighborhood_code"] == "NB-EAST", (
            "the certificate's origin neighborhood must be recorded, got "
            f"{transaction['applied_neighborhood_code']}"
        )
        assert transaction["applied_per_unit_value_cents"] == EXPECTED_PER_UNIT_CENTS, (
            "1,234,567 marked up by 250 bps and rounded half up is 1,265,431, got "
            f"{transaction['applied_per_unit_value_cents']}"
        )
        assert transaction["appraised_reference_cents"] == EXPECTED_REFERENCE_CENTS, (
            "1,265,431 times 22 units is 27,839,482, got "
            f"{transaction['appraised_reference_cents']}"
        )
        assert transaction["price_deviation_bps"] == EXPECTED_DEVIATION_BPS, (
            "30,000,000 against a 27,839,482 reference is +776 bps, got "
            f"{transaction['price_deviation_bps']}"
        )

        certificate = fetch_certificate(scenario["certificate"]["id"])
        assert certificate["market_status"] == "UNDER_CONTRACT", (
            f"the proposal must put the certificate under contract, got {certificate['market_status']}"
        )
        assert certificate["units_encumbered"] == CERTIFICATE_UNITS, (
            f"all 22 traded units become encumbered, got {certificate['units_encumbered']}"
        )

    def test_proposal_exactly_at_the_window_end_finds_no_schedule(self):
        """At 2026-09-01T00:00:00Z the clock has reached the exclusive end, so the
        same deal that priced one second earlier now has no applicable schedule.

        PRD §3.4: "The applicable schedules are those whose `neighborhood_code` equals the certificate's `origin_neighborhood_code` — the neighborhood the **rights** came from, never the buyer's neighborhood and never the receiving area's — whose `status` is `ACTIVE`, and whose window covers the current logical clock, meaning the clock is at or after `effective_from` and strictly before `effective_to`."
        PRD §3.4: "If no schedule qualifies, the proposal is rejected with `ERR_NO_ACTIVE_APPRAISAL_SCHEDULE`."
        PRD §3.7: "An administrator publishes an **AppraisalSchedule** for a neighborhood, supplying `neighborhood_code`, the `per_unit_value_cents` appraised value of one development right there (greater than zero), the signed `equity_adjustment_bps` correction for historic under-appraisal (defaulting to 0 and constrained to lie between negative 5000 and positive 5000 inclusive), the inclusive `effective_from` start of its window, and the exclusive `effective_to` end, where an unset `effective_to` means the window is open-ended."

        Design: Difficulty/boundary_precision_check/appraisal_window_half_open_upper_bound_at_one_second_precision
        """
        scenario = _certificate_with_a_lapsing_schedule()
        set_clock(WINDOW_END_INSTANT)

        resp = _propose_whole_certificate(scenario)

        validate_error(resp, ApiErrorId.ERR_NO_ACTIVE_APPRAISAL_SCHEDULE.value)

        certificate = fetch_certificate(scenario["certificate"]["id"])
        assert certificate["market_status"] == "HELD", (
            f"a rejected proposal must not encumber the certificate, got {certificate['market_status']}"
        )
        assert certificate["units_encumbered"] == 0, (
            f"units_encumbered must stay 0, got {certificate['units_encumbered']}"
        )

    def test_the_lapsed_window_leaves_only_the_cancelled_deal_and_an_active_schedule(self):
        """Proposing inside the window, cancelling, then re-proposing at the window
        end leaves exactly one CANCELLED row, an unencumbered certificate, and the
        schedule still ACTIVE — lapsing is not a status change.

        PRD §3.4: "Cancellation moves it `PROPOSED → CANCELLED`, reduces the certificate's `units_encumbered` by the traded `units`, returns the certificate's `market_status` to `HELD` — or leaves it `FROZEN` when the cancellation was itself produced by a compliance freeze rather than requested — moves no cash whatsoever, and increments the transaction's `version`."
        PRD §3.4: "If no schedule qualifies, the proposal is rejected with `ERR_NO_ACTIVE_APPRAISAL_SCHEDULE`."
        PRD §3.4: "Transactions can be listed with `certificate_id`, `seller_party_id`, `buyer_party_id`, `conveyed_certificate_id`, `channel`, and `status` filters plus `limit` and `offset`, and the detail read exposes the whole pricing breakdown"
        PRD §3.7: "A schedule opens in `status` `ACTIVE`; the only other value is `SUPERSEDED`, which is set on an existing row when a new schedule for the same `neighborhood_code` declares an `effective_from` equal to that row's `effective_from`."

        Design: Difficulty/boundary_precision_check/appraisal_window_half_open_upper_bound_at_one_second_precision
        """
        scenario = _certificate_with_a_lapsing_schedule()
        set_clock(ONE_SECOND_INSIDE)
        proposed = validate_success(_propose_whole_certificate(scenario), 201)
        cancelled = cancel_transaction(
            proposed["id"],
            make_landowner_headers(scenario["landowner"]["id"]),
            reason="boundary probe",
        )
        assert cancelled["status"] == "CANCELLED", (
            f"the seller's withdrawal must cancel the deal, got {cancelled['status']}"
        )

        set_clock(WINDOW_END_INSTANT)
        validate_error(
            _propose_whole_certificate(scenario),
            ApiErrorId.ERR_NO_ACTIVE_APPRAISAL_SCHEDULE.value,
        )

        listing = api_client.list_market_transactions(
            ADMIN, params={"certificate_id": scenario["certificate"]["id"], "limit": 50, "offset": 0}
        )
        rows, meta = validate_paginated(listing)
        assert meta["total_count"] == 1, (
            f"only the cancelled deal may exist on this certificate, got {meta['total_count']}"
        )
        assert rows[0]["status"] == "CANCELLED", (
            f"the single surviving row must be CANCELLED, got {rows[0]['status']}"
        )

        certificate = fetch_certificate(scenario["certificate"]["id"])
        assert_certificate_units_conserved(certificate)
        assert certificate["market_status"] == "HELD", (
            f"the cancellation returns the certificate to HELD, got {certificate['market_status']}"
        )
        assert certificate["units_encumbered"] == 0, (
            f"the cancelled units are released, got {certificate['units_encumbered']}"
        )

        schedule = get_success_data(
            api_client.get_appraisal_schedule(scenario["schedule"]["id"], ADMIN)
        )
        assert schedule["status"] == "ACTIVE", (
            "a window that has merely lapsed stays ACTIVE, since only a same-start "
            f"republication supersedes it, got {schedule['status']}"
        )
