"""Per-use royalties in both variants, their three-way splits, and the surcharge."""

from test_helpers import assertions, fixtures


def test_provisional_reads_the_projection_while_the_final_reads_the_delivery():
    """One performance projecting 6000000 impressions, licensed for 12000000.

    The PRD states: "The **final per-use royalty** is computed at issuance by the
    same formula the provisional accrual used, with two substitutions: reach is
    the license's `actual_impressions` rather than the performance's projection,
    and the territory count is the size of the license's `territory_codes`, which
    may be a strict subset of the performance's declared territories or a
    different selection within the grant's scope." The projection sits in reach
    tier two and the delivery in reach tier three, so the two variants diverge by
    123750 cents on identical scope.

    Design: Difficulty/dual_variant_calc/per_use_royalty_provisional_versus_final_divergence
    """
    scenario = fixtures.campaign_issued_license()

    performance = fixtures.refresh_performance(scenario)
    license_row = fixtures.refresh_license(scenario)

    assert performance["provisional_compensation_cents"] == 346_500
    assert license_row["per_use_final_cents"] == 470_250
    assert (
        license_row["per_use_final_cents"] - performance["provisional_compensation_cents"]
        == 123_750
    )


def test_both_accruals_survive_issuance_in_the_same_ledger():
    """Issuance appends the delivery accrual without undoing the projection one.

    The PRD states: "The provisional accrual is **not** reversed at issuance: both
    amounts coexist in the ledger and both are reflected in the grant's and the
    talent's roll-ups, because the projection accrual and the delivery accrual are
    separate obligations." The grant's roll-up is therefore the signed sum of all
    three entries.

    Design: Difficulty/dual_variant_calc/per_use_royalty_provisional_versus_final_divergence
    """
    scenario = fixtures.campaign_issued_license()

    entries = fixtures.grant_ledger(scenario)
    assertions.assert_entry_types(
        entries, ["INITIAL_CREATION", "PER_USE_PROVISIONAL", "PER_USE_FINAL"]
    )
    assert [entry["amount_cents"] for entry in entries] == [300_000, 346_500, 470_250]
    assertions.assert_ledger_sums_to(entries, 1_116_750)

    grant = fixtures.refresh_grant(scenario)
    assert grant["total_compensation_cents"] == 1_116_750
    assert fixtures.refresh_performance(scenario)["provisional_compensation_cents"] == 346_500


def test_final_royalty_split_sweeps_the_negative_remainder_into_the_talent_share():
    """The 470250-cent delivery entry splits 352687 / 94050 / 23513.

    The PRD states: "Consider an entry of 470250 cents split 0.75 / 0.20 / 0.05:
    the unrounded slices are 352687.5, 94050 and 23512.5, which round to 352688,
    94050 and 23513 and sum to 470251; the remainder of negative one cent moves
    the talent's slice to 352687, and the stored slices are 352687, 94050 and
    23513." A policy that rounded the total once instead would leave the three
    columns summing to 470251.

    Design: Difficulty/combinatorial_formula/royalty_split_per_participant_rounding_with_signed_remainder
    """
    scenario = fixtures.campaign_issued_license()

    entries = fixtures.ledger_entries(
        scenario, {"usage_license_id": scenario["license"]["id"], "limit": 100}
    )
    assertions.assert_entry_types(entries, ["PER_USE_FINAL"])
    assertions.assert_ledger_entry(entries[0], "PER_USE_FINAL", 470_250, 352_687, 94_050, 23_513)
    assertions.assert_split_reconstructs_amount(entries[0])


def test_the_other_two_entries_split_without_any_remainder_to_sweep():
    """The creation and projection entries divide exactly at the same percentages.

    The PRD states: "The talent's slice `talent_share_cents` is the entry amount
    multiplied by the grant's `talent_share_pct`, rounded half up to a whole
    cent." At 300000 and at 346500 the three products are already whole cents, so
    no remainder moves and the talent's slice is untouched by the sweep rule.

    Design: Difficulty/combinatorial_formula/royalty_split_per_participant_rounding_with_signed_remainder
    """
    scenario = fixtures.campaign_issued_license()

    entries = fixtures.grant_ledger(scenario)
    assertions.assert_ledger_entry(entries[0], "INITIAL_CREATION", 300_000, 225_000, 60_000, 15_000)
    assertions.assert_ledger_entry(
        entries[1], "PER_USE_PROVISIONAL", 346_500, 259_875, 69_300, 17_325
    )
    for entry in entries:
        assertions.assert_money_is_number(entry["amount_cents"])
        assertions.assert_split_reconstructs_amount(entry)


def test_surcharge_is_ceilinged_on_this_licenses_own_presurcharge_subtotal():
    """470250 at the advertising rate yields 8229.375, billed as 8230.

    The PRD states: "`compliance_surcharge_cents` is the subtotal multiplied by
    that rate and rounded **up** to the next whole cent — not half up, as every
    royalty is." It also states: "A second license issued under the same
    performance recomputes its surcharge from its own subtotal alone; the
    surcharge is never assessed on a running total and never on a previous
    surcharge." Half-up rounding would bill 8229 for a total of 478479, and
    assessing the rate on the grant's cumulative 1116750 would bill 19544 for a
    total of 489794.

    Design: Difficulty/combinatorial_formula/license_total_surcharge_on_presurcharge_subtotal_with_ceiling
    """
    scenario = fixtures.campaign_issued_license()

    license_row = fixtures.refresh_license(scenario)
    assert license_row["per_use_final_cents"] == 470_250
    assert license_row["compliance_surcharge_cents"] == 8_230
    assert license_row["license_total_cents"] == 478_480
    assert license_row["license_total_cents"] != 478_479
    assert license_row["license_total_cents"] != 489_794
    assert license_row["disclosure_required"] is True
    assert license_row["compliance_status"] == "PENDING_LABEL"


def test_the_surcharge_never_becomes_a_compensation_entry():
    """The 8230 cents billed to the licensee reach no participant's share.

    The PRD states: "The surcharge funds disclosure labelling and monitoring, is
    paid by the licensee to the clearance office, and is deliberately **never** a
    ledger entry — it never reaches the talent's, the agency's or the
    administrator's shares." The grant's roll-up therefore stays at the three
    royalty amounts and never reflects the licensee's total bill.

    Design: Difficulty/combinatorial_formula/license_total_surcharge_on_presurcharge_subtotal_with_ceiling
    """
    scenario = fixtures.campaign_issued_license()

    entries = fixtures.grant_ledger(scenario)
    assertions.assert_entry_types(
        entries, ["INITIAL_CREATION", "PER_USE_PROVISIONAL", "PER_USE_FINAL"]
    )
    assert all(entry["amount_cents"] != 8_230 for entry in entries)

    grant = fixtures.refresh_grant(scenario)
    assert grant["total_compensation_cents"] == 1_116_750
    assertions.assert_talent_counters(
        fixtures.read_talent(scenario), lifetime_compensation_cents=1_116_750
    )
