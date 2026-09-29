"""The two conservation identities of PRD §2.11, exercised through compensating pairs.

Severed development rights are conserved in whole units: a split moves units down
a lineage, a redemption allocation commits them, and a release un-commits them,
and not one of the three may change the total the source easement has issued or
still has outstanding.  Only confirmation and retirement may move that total.

Program cash is conserved in whole cents: the program has no external source or
sink of money, so a settlement's three legs sum to zero and a reversal negates
all three exactly, leaving no rounding residue anywhere.
"""
from test_helpers import (
    TEST_USERS,
    allocate_redemption,
    api_client,
    ApiErrorId,
    assert_certificate,
    assert_certificate_redemption,
    assert_certificate_units_conserved,
    assert_conservation_easement,
    assert_easement_units_conserved,
    assert_market_transaction,
    assert_program_cash_conserved,
    assert_same_instant,
    create_active_receiving_area,
    fetch_certificate,
    fetch_easement,
    fetch_party,
    fetch_receiving_area,
    fetch_receiving_site_application,
    fetch_redemption,
    fetch_transaction,
    file_receiving_site_application,
    make_developer_headers,
    program_cash_total,
    program_cash_total_now,
    program_parties,
    release_redemption,
    setup_developer_holding_certificate,
    split_certificate,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
CLOCK = "2026-08-10T00:00:00Z"

# The canonical scenario: a 22-unit root certificate, sold whole to the developer
# in a PRIVATE deal for 30,000,000 cents out of an UNDERSERVED sending area.
ISSUED_UNITS = 22
GROSS_PRICE_CENTS = 30_000_000
# A gross above 25,000,000 cents attracts 200 bps: 30,000,000 x 200 / 10,000.
EXPECTED_PROGRAM_FEE_CENTS = 600_000
# UNDERSERVED carries no surcharge at all.
EXPECTED_EQUITY_SURCHARGE_CENTS = 0
EXPECTED_NET_TO_SELLER_CENTS = 29_400_000


def _developer_holding_certificate_with_open_application():
    """A developer holding the whole 22-unit root certificate, an `ACTIVE`
    receiving area and a `DESIGN_APPROVED` receiving-site application on it."""
    scenario = setup_developer_holding_certificate()
    receiving_area = create_active_receiving_area(
        code="RA-CORE",
        name="Core Receiving Area",
        neighborhood_code="NB-CORE",
        base_density_units_per_acre=4.00,
        max_bonus_pct=0.35,
        absorption_cap_units=500,
        design_review_required=False,
        eligible_sending_area_codes=[],
    )
    rsa = file_receiving_site_application(
        scenario["developer"]["id"], receiving_area["id"],
        site_acres=12.00, requested_bonus_units=20,
    )
    scenario.update({
        "receiving_area": fetch_receiving_area(receiving_area["id"]),
        "rsa": rsa,
        "certificate": fetch_certificate(scenario["certificate"]["id"]),
        "easement": fetch_easement(scenario["easement"]["id"]),
    })
    return scenario


class TestSeveredRightsConservedAcrossSplitAllocateAndRelease:
    """Three unit-moving operations that must leave the easement's issued and
    outstanding totals exactly where they started."""

    def test_split_allocate_and_release_leave_the_easement_totals_unchanged(self):
        """`units_issued_total` and `units_outstanding` survive all three operations.

        PRD §2.11: "Splitting a certificate, allocating a redemption and releasing
        a redemption must each leave both `units_issued_total` and
        `units_outstanding` completely unchanged; only confirmation of a redemption
        and retirement of units may move `units_outstanding`, and each moves it
        downward by exactly the units involved."
        PRD §2.11: "For any single easement, `units_issued_total` equals
        `units_redeemed_confirmed` plus `units_retired` plus `units_outstanding` —
        equivalently, `units_outstanding` is the total face value of the root
        issuances backed by that easement, less everything redeemed and everything
        retired across the easement's entire certificate lineage including every
        split child."
        PRD §3.6: "The source easement's `units_issued_total` and
        `units_outstanding` are completely unchanged by a split — the rights have
        moved, not multiplied."
        PRD §3.8: "The source easement's `units_outstanding` is deliberately
        unchanged: allocation and release move rights between commitment states
        without ever creating or destroying them, so an allocate-then-release pair
        returns every counter to its starting value."

        Design: Difficulty/compensating_invariant/severed_rights_conserved_across_split_allocate_and_release
        """
        scenario = _developer_holding_certificate_with_open_application()
        cert, easement = scenario["certificate"], scenario["easement"]
        developer, rsa = scenario["developer"], scenario["rsa"]

        def check(stage: str) -> None:
            row = fetch_easement(easement["id"])
            assert_conservation_easement(row)
            assert_easement_units_conserved(row)
            assert row["units_issued_total"] == ISSUED_UNITS, (
                f"{stage}: units_issued_total must stay at {ISSUED_UNITS}, "
                f"got {row['units_issued_total']}"
            )
            assert row["units_outstanding"] == ISSUED_UNITS, (
                f"{stage}: units_outstanding is the conserved quantity and must stay at "
                f"{ISSUED_UNITS}, got {row['units_outstanding']}"
            )
            assert row["units_redeemed_confirmed"] == 0, (
                f"{stage}: nothing has been confirmed, so units_redeemed_confirmed stays 0"
            )
            assert row["units_retired"] == 0, (
                f"{stage}: nothing has been retired, so units_retired stays 0"
            )

        check("at issuance")

        split_certificate(
            cert["id"], 8,
            actor_headers=make_developer_headers(developer["id"]),
            expected_certificate_version=fetch_certificate(cert["id"])["version"],
        )
        check("after the split")

        redemption = allocate_redemption(rsa["id"], developer["id"], cert["id"], 5)
        check("after the allocation")

        release_redemption(
            redemption["id"], actor_headers=make_developer_headers(developer["id"]),
            reason="site plan withdrawn",
        )
        check("after the release")

    def test_release_returns_every_committed_counter_to_its_starting_value(self):
        """The release is the compensating operation: encumbrance and reserve return
        to zero while the split child keeps its units.

        PRD §2.11: "For any single certificate, `units_remaining` equals
        `units_face` less `units_split_out` less `units_redeemed` less
        `units_retired`, and `units_encumbered` never exceeds `units_remaining`."
        PRD §2.11: "For any single party, `units_held` is the sum of
        `units_remaining` across the certificates it holds whose `lifecycle_status`
        is `ISSUED` or `PARTIALLY_REDEEMED`, and `certificates_held_count` is the
        count of those same certificates."
        PRD §3.6: "The child certificate is minted with `parent_certificate_id`
        pointing at the parent, with `conservation_easement_id`,
        `origin_sending_area_id` and `origin_neighborhood_code` copied down the
        lineage unchanged, with `holder_party_id` equal to the parent's holder,
        with `units_face` and `units_remaining` both equal to the requested
        `units`, with `generation` one higher than the parent's `generation`, with
        `split_count` at 0, with `lifecycle_status` of `ISSUED` and `market_status`
        of `HELD`, and with `issued_at` at the current logical clock."
        PRD §3.6: "On the parent, `units_split_out` grows by `units` and
        `units_remaining` is recomputed, but `lifecycle_status` and `market_status`
        are both left exactly where they were: a split is a lineage mutation, not a
        lifecycle advance, which is why the parent's rights dimension can stay
        `ISSUED` across an arbitrary number of splits."
        PRD §3.6: "The parent's `split_count` is incremented by one, and the
        child's `serial_number` is the parent's `serial_number` followed by `-S`
        and the parent's `split_count` after that increment — so the second child
        of `TDR-SND-01-00001` is serialized `TDR-SND-01-00001-S2`."
        PRD §3.8: "Release sets `released_at`, reduces the certificate's
        `units_encumbered` by `units` and the area's `reserved_units` by `units`,
        recomputes `pending_backed_units`, and increments the redemption's
        `version`."
        PRD §2.11: "Rows in status `RELEASED` contribute nothing to any of these
        totals, and rows in status `HELD_PENDING_COMPLIANCE` contribute to
        `units_encumbered` but never to `units_redeemed_confirmed`."

        Design: Difficulty/compensating_invariant/severed_rights_conserved_across_split_allocate_and_release
        """
        scenario = _developer_holding_certificate_with_open_application()
        cert, easement = scenario["certificate"], scenario["easement"]
        developer, rsa = scenario["developer"], scenario["rsa"]

        child = split_certificate(
            cert["id"], 8,
            actor_headers=make_developer_headers(developer["id"]),
            expected_certificate_version=fetch_certificate(cert["id"])["version"],
        )
        redemption = allocate_redemption(rsa["id"], developer["id"], cert["id"], 5)
        release_redemption(
            redemption["id"], actor_headers=make_developer_headers(developer["id"]),
            reason="site plan withdrawn",
        )

        parent = fetch_certificate(cert["id"])
        assert_certificate(parent)
        assert_certificate_units_conserved(parent)
        assert parent["units_face"] == ISSUED_UNITS, "units_face is what the certificate was minted with"
        assert parent["units_split_out"] == 8, "the split moved 8 units out to the child"
        assert parent["units_remaining"] == 14, (
            "units_remaining is units_face less units_split_out less units_redeemed "
            f"less units_retired: expected 14, got {parent['units_remaining']}"
        )
        assert parent["split_count"] == 1, "the parent's split_count is incremented by one"
        assert parent["units_encumbered"] == 0, (
            "the release returns the parent's units_encumbered to its starting value"
        )
        assert parent["units_redeemed"] == 0, "no redemption was ever confirmed"
        assert parent["units_retired"] == 0, "nothing was retired"
        assert parent["lifecycle_status"] == "ISSUED", (
            "a split is a lineage mutation, so the parent's lifecycle_status stays ISSUED"
        )

        child_row = fetch_certificate(child["id"])
        assert_certificate(child_row)
        assert child_row["parent_certificate_id"] == cert["id"], (
            "the child's parent_certificate_id points at the parent"
        )
        assert child_row["generation"] == parent["generation"] + 1 == 2, (
            "the child's generation is one higher than the parent's"
        )
        assert child_row["units_face"] == 8 and child_row["units_remaining"] == 8, (
            "the child is minted with units_face and units_remaining equal to the "
            f"requested units: got {child_row['units_face']}/{child_row['units_remaining']}"
        )
        assert child_row["units_encumbered"] == 0, "nothing was ever committed on the child"
        assert child_row["conservation_easement_id"] == easement["id"], (
            "conservation_easement_id is copied down the lineage unchanged"
        )
        assert child_row["holder_party_id"] == developer["id"], (
            "the child's holder_party_id equals the parent's holder"
        )
        assert parent["units_remaining"] + child_row["units_remaining"] == ISSUED_UNITS, (
            "the lineage sum must still equal the issuance: "
            f"{parent['units_remaining']} + {child_row['units_remaining']} != {ISSUED_UNITS}"
        )

        released = fetch_redemption(redemption["id"])
        assert_certificate_redemption(released)
        assert released["status"] == "RELEASED", "the released redemption sits in RELEASED"
        assert_same_instant(released["released_at"], CLOCK, "CertificateRedemption.released_at")

        rsa_after = fetch_receiving_site_application(rsa["id"])
        assert rsa_after["pending_backed_units"] == 0, (
            "a RELEASED row contributes nothing to pending_backed_units"
        )
        assert rsa_after["backed_units"] == 0, (
            "a RELEASED row contributes nothing to backed_units"
        )
        area_after = fetch_receiving_area(scenario["receiving_area"]["id"])
        assert area_after["reserved_units"] == 0, (
            "the release reduces the area's reserved_units by the released units"
        )
        assert area_after["absorbed_units"] == 0, "nothing was confirmed, so nothing was absorbed"

        holder = fetch_party(developer["id"])
        assert holder["units_held"] == ISSUED_UNITS, (
            "units_held is the sum of units_remaining across the held ISSUED certificates: "
            f"expected {ISSUED_UNITS}, got {holder['units_held']}"
        )
        assert holder["certificates_held_count"] == 2, (
            "the developer holds both the parent and the split child"
        )


class TestProgramCashConservedAcrossSettlementAndReversal:
    """The reversal is the compensating operation for a settlement, and the
    program-wide money total is a constant across the pair."""

    def test_reversal_negates_all_three_settlement_cash_legs(self):
        """Buyer debit, seller credit and bank fee revenue all return to their
        pre-settlement values, with no rounding residue in the program total.

        PRD §2.11: "**Cash is conserved.** The program has no external source or
        sink of money. Summed across every `Party`, `cash_balance_cents` plus
        `fee_revenue_cents` is a constant."
        PRD §2.11: "A reversal applies the exact negation of all three movements,
        so the program-wide total after a settlement followed by its reversal is
        identical to the total before the settlement, with no rounding residue left
        behind anywhere."
        PRD §3.7: "First, a fee rate is selected by tier from `gross_price_cents`
        itself, never from any post-surcharge figure: a gross of at most 5,000,000
        cents — fifty thousand dollars — attracts 350 basis points; a gross above
        that but at most 25,000,000 cents — two hundred fifty thousand dollars —
        attracts 275 basis points; anything above that attracts 200 basis points."
        PRD §3.7: "Third, `equity_surcharge_cents` is `gross_price_cents`
        multiplied by a surcharge rate divided by ten thousand, rounded half up to
        whole cents, where the surcharge rate comes from the `equity_tier` of the
        sending area named by the certificate's `origin_sending_area_id`: 150 basis
        points for `HIGH_VALUE`, 75 basis points for `MODERATE`, and 0 basis points
        for `UNDERSERVED`, so preserving land in an underserved neighborhood carries
        no surcharge at all."
        PRD §3.7: "Fourth, `net_to_seller_cents` is `gross_price_cents` less
        `program_fee_cents` less `equity_surcharge_cents`. Each cents figure is
        rounded independently."
        PRD §3.7: "A permitted reversal applies the exact inverse of all three
        settlement legs: the buyer's `cash_balance_cents` is increased by
        `gross_price_cents`, the seller's `cash_balance_cents` is reduced by
        `net_to_seller_cents`, and the bank's `fee_revenue_cents` is reduced by
        `program_fee_cents` plus `equity_surcharge_cents`."
        PRD §3.7: "Both parties' `units_held` and `certificates_held_count` are
        recomputed, `reversed_at` is set to the current logical clock,
        `reversal_reason` is recorded from the request, the transaction moves
        `SETTLED → REVERSED`, and its `version` is incremented."

        Design: Difficulty/compensating_invariant/program_cash_conserved_across_settlement_and_reversal
        """
        scenario = setup_developer_holding_certificate()
        landowner, developer, bank = (
            scenario["landowner"], scenario["developer"], scenario["bank"],
        )
        settled = fetch_transaction(scenario["transaction"]["id"])
        assert_market_transaction(settled)
        assert settled["status"] == "SETTLED", "the setup must leave the deal SETTLED"
        assert settled["gross_price_cents"] == GROSS_PRICE_CENTS, (
            "a PRIVATE gross price is the agreed_price_cents taken exactly as supplied"
        )
        assert settled["program_fee_cents"] == EXPECTED_PROGRAM_FEE_CENTS, (
            f"a gross of {GROSS_PRICE_CENTS} cents sits above 25,000,000 and attracts "
            f"200 bps: expected {EXPECTED_PROGRAM_FEE_CENTS}, got {settled['program_fee_cents']}"
        )
        assert settled["equity_surcharge_cents"] == EXPECTED_EQUITY_SURCHARGE_CENTS, (
            "an UNDERSERVED origin area carries no equity surcharge"
        )
        assert settled["net_to_seller_cents"] == EXPECTED_NET_TO_SELLER_CENTS, (
            "net_to_seller_cents is the gross less the fee less the surcharge"
        )

        total_after_settlement = program_cash_total_now()
        assert total_after_settlement == GROSS_PRICE_CENTS, (
            "the only money ever introduced was the buyer's credit, so the program-wide "
            f"total must be {GROSS_PRICE_CENTS}, got {total_after_settlement}"
        )

        reversed_tx = validate_success(
            api_client.reverse_market_transaction(
                settled["id"], {"reversal_reason": "TITLE_DEFECT"}, ADMIN,
            )
        )
        assert_market_transaction(reversed_tx)
        assert reversed_tx["status"] == "REVERSED", "the transaction moves SETTLED -> REVERSED"
        assert_same_instant(reversed_tx["reversed_at"], CLOCK, "MarketTransaction.reversed_at")
        assert reversed_tx["reversal_reason"] == "TITLE_DEFECT", (
            "reversal_reason is recorded from the request"
        )

        buyer, seller, bank_row = (
            fetch_party(developer["id"]), fetch_party(landowner["id"]), fetch_party(bank["id"]),
        )
        assert buyer["cash_balance_cents"] == GROSS_PRICE_CENTS, (
            "the buyer's gross debit is undone exactly: expected "
            f"{GROSS_PRICE_CENTS}, got {buyer['cash_balance_cents']}"
        )
        assert seller["cash_balance_cents"] == 0, (
            "the seller's net credit is undone exactly: expected 0, got "
            f"{seller['cash_balance_cents']}"
        )
        assert bank_row["fee_revenue_cents"] == 0, (
            "the bank's fee-plus-surcharge leg is undone exactly: expected 0, got "
            f"{bank_row['fee_revenue_cents']}"
        )

        assert_program_cash_conserved(
            total_after_settlement, program_cash_total(program_parties()),
            "across the settlement and its reversal",
        )

        retained = fetch_transaction(settled["id"])
        assert retained["gross_price_cents"] == GROSS_PRICE_CENTS, (
            "the reversal leaves the historical gross price on the record"
        )
        assert retained["program_fee_cents"] == EXPECTED_PROGRAM_FEE_CENTS, (
            "the reversal does not zero the recorded program fee"
        )
        assert retained["net_to_seller_cents"] == EXPECTED_NET_TO_SELLER_CENTS, (
            "the reversal does not zero the recorded seller proceeds"
        )

    def test_reversal_returns_title_to_the_seller_and_recomputes_both_holdings(self):
        """The compensating operation restores the register as well as the cash.

        PRD §3.7: "A permitted reversal applies the exact inverse of all three
        settlement legs: the buyer's `cash_balance_cents` is increased by
        `gross_price_cents`, the seller's `cash_balance_cents` is reduced by
        `net_to_seller_cents`, and the bank's `fee_revenue_cents` is reduced by
        `program_fee_cents` plus `equity_surcharge_cents`. The conveyed certificate's
        `holder_party_id` returns to `seller_party_id` and its `market_status`
        returns to `HELD`."
        PRD §2.11: "For any single certificate, `units_remaining` equals
        `units_face` less `units_split_out` less `units_redeemed` less
        `units_retired`, and `units_encumbered` never exceeds `units_remaining`."
        PRD §2.11: "For any single party, `units_held` is the sum of
        `units_remaining` across the certificates it holds whose `lifecycle_status`
        is `ISSUED` or `PARTIALLY_REDEEMED`, and `certificates_held_count` is the
        count of those same certificates."
        PRD §3.7: "When the traded `units` equal the certificate's
        `units_remaining`, `conveyance_mode` is pinned to `WHOLE`: the certificate
        itself changes hands, its `holder_party_id` becomes `buyer_party_id`, and
        `conveyed_certificate_id` is set to the traded `certificate_id`."

        Design: Difficulty/compensating_invariant/program_cash_conserved_across_settlement_and_reversal
        """
        scenario = setup_developer_holding_certificate()
        landowner, developer = scenario["landowner"], scenario["developer"]
        certificate_id = scenario["certificate"]["id"]

        assert scenario["transaction"]["conveyance_mode"] == "WHOLE", (
            "trading the whole remaining balance pins the conveyance to WHOLE"
        )
        assert fetch_certificate(certificate_id)["holder_party_id"] == developer["id"], (
            "a WHOLE conveyance moves the certificate itself to the buyer"
        )

        validate_success(
            api_client.reverse_market_transaction(
                scenario["transaction"]["id"], {"reversal_reason": "TITLE_DEFECT"}, ADMIN,
            )
        )

        cert = fetch_certificate(certificate_id)
        assert_certificate(cert)
        assert_certificate_units_conserved(cert)
        assert cert["holder_party_id"] == landowner["id"], (
            "the conveyed certificate's holder_party_id returns to the seller"
        )
        assert cert["market_status"] == "HELD", "the certificate's market_status returns to HELD"
        assert cert["units_encumbered"] == 0, "the reversal leaves nothing encumbered"
        assert cert["units_remaining"] == ISSUED_UNITS, (
            f"the whole {ISSUED_UNITS}-unit balance is intact, got {cert['units_remaining']}"
        )
        assert cert["units_redeemed"] == 0, "no units were ever redeemed"
        assert cert["lifecycle_status"] == "ISSUED", "the rights dimension stays ISSUED"

        seller, buyer = fetch_party(landowner["id"]), fetch_party(developer["id"])
        assert seller["units_held"] == ISSUED_UNITS, (
            f"the seller holds the returned units again, got {seller['units_held']}"
        )
        assert seller["certificates_held_count"] == 1, "the seller holds the one certificate again"
        assert buyer["units_held"] == 0, (
            f"the buyer holds nothing after the reversal, got {buyer['units_held']}"
        )
        assert buyer["certificates_held_count"] == 0, (
            "the buyer holds no certificate after the reversal"
        )

    def test_second_reversal_is_refused_as_not_settled_and_moves_no_cash(self):
        """`REVERSED` is terminal, the state rung outranks the constraint rung, and the
        refused second attempt leaves every balance where it was.

        PRD §2.10 rung 19: "The market transaction is `SETTLED` before reversal;
        otherwise `ERR_TRANSACTION_NOT_SETTLED` (409)."
        PRD §2.10 rung 42: "The settled transaction is still cleanly reversible;
        otherwise `ERR_REVERSAL_NOT_PERMITTED` (409)."
        PRD §5: "When more than one condition holds, the identifier returned is the
        one belonging to the lowest-numbered rung of the evaluation ladder in §2.10."
        PRD §3.7: "`REVERSED` and `CANCELLED` are both terminal."
        PRD §2.11: "**Cash is conserved.** The program has no external source or
        sink of money. Summed across every `Party`, `cash_balance_cents` plus
        `fee_revenue_cents` is a constant."

        Design: Difficulty/compensating_invariant/program_cash_conserved_across_settlement_and_reversal
        """
        scenario = setup_developer_holding_certificate()
        tx_id = scenario["transaction"]["id"]

        validate_success(
            api_client.reverse_market_transaction(tx_id, {"reversal_reason": "TITLE_DEFECT"}, ADMIN)
        )
        before_parties = {p["id"]: p for p in program_parties()}
        total_before = program_cash_total(list(before_parties.values()))

        validate_error(
            api_client.reverse_market_transaction(
                tx_id, {"reversal_reason": "SECOND_ATTEMPT"}, ADMIN,
            ),
            ApiErrorId.ERR_TRANSACTION_NOT_SETTLED.value,
        )

        assert fetch_transaction(tx_id)["status"] == "REVERSED", (
            "a refused second reversal leaves the transaction in its terminal REVERSED state"
        )
        after_parties = {p["id"]: p for p in program_parties()}
        assert_program_cash_conserved(
            total_before, program_cash_total(list(after_parties.values())),
            "across the refused second reversal",
        )
        assert total_before == GROSS_PRICE_CENTS, (
            f"the program-wide total must still be {GROSS_PRICE_CENTS}, got {total_before}"
        )
        for party_id, before in before_parties.items():
            after = after_parties[party_id]
            assert after["cash_balance_cents"] == before["cash_balance_cents"], (
                f"party {party_id}: the refused attempt must move no cash_balance_cents"
            )
            assert after["fee_revenue_cents"] == before["fee_revenue_cents"], (
                f"party {party_id}: the refused attempt must move no fee_revenue_cents"
            )
