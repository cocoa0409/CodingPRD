"""The assessment pipeline's composition rules: the nested clamp, the
round-then-sum discipline of the batch total, and the pinned tier resolution.
"""
from test_helpers.fixtures import (
    add_record,
    board_merchant,
    canonical_environment,
    create_fx_rate,
    create_incentive_program,
    enrol_merchant,
    evaluate_enrollment,
    finalize_batch,
    open_batch,
    read_batch,
    read_merchant,
    read_record,
    set_clock,
    submit_batch,
)


def _cross_border_fx_record():
    """A 5000-cent Canadian sale settled in USD, carrying only `AUTH_CODE`, so
    only the fallback tier can price it and both conditional limbs of the
    pipeline are engaged."""
    env = canonical_environment("2026-09-03T00:00:00Z")
    create_fx_rate(
        "CAD", "USD", "2026-08-01T00:00:00Z", rate=0.74, markup_bps=100
    )
    merchant = board_merchant(
        env["acquirer"]["id"],
        "GROCERY",
        headers=env["acquirer_headers"],
        legal_name="Maple Grocer",
        home_country_code="CA",
    )
    batch = open_batch(
        env["acquirer"]["id"], "2026-09-02", "USD", headers=env["acquirer_headers"]
    )
    record = add_record(
        batch["id"],
        merchant["id"],
        5000,
        env["acquirer"]["id"],
        expected_batch_version=batch["version"],
        headers=env["acquirer_headers"],
        auth_code="A00020",
        auth_timestamp="2026-09-01T00:00:00Z",
        clearing_timestamp="2026-09-02T00:00:00Z",
        data_elements=["AUTH_CODE"],
        transaction_currency="CAD",
    )
    submit_batch(batch["id"], headers=env["acquirer_headers"])
    env["merchant"] = merchant
    env["batch"] = batch
    env["record"] = record
    return env


class TestNestedCapThenFloorClamp:
    def test_the_raw_amount_is_capped_at_350_bps_and_the_components_survive_the_clamp(
        self,
    ):
        """137 cents of ad-valorem plus a 20-cent cross-border surcharge plus a
        50-cent conversion markup raise the raw amount to 207, above the 175-cent
        ceiling, so the assessment clamps down to 175 while both component fields
        keep their pre-clamp values.

        PRD 3.6: "Cap that raw amount at the record's `amount_cents` multiplied
        by the assessment ceiling of 350 basis points, divided by ten thousand
        and rounded half up — meaning the assessment takes the smaller of the raw
        amount and that ceiling."

        Design: Difficulty/combinatorial_formula/combinatorial_mode_a_nested_cap_then_floor_clamp_with_cross_border_and_fx
        """
        env = _cross_border_fx_record()
        finalize_batch(env["batch"]["id"])

        record = read_record(env["record"]["id"])
        assert record["cross_border"] is True
        assert record["cross_border_surcharge_cents"] == 20
        assert record["fx_markup_cents"] == 50
        assert record["assessed_interchange_cents"] == 175

    def test_the_components_sit_inside_the_total_and_the_batch_agrees_with_the_record(
        self,
    ):
        """The surcharge and the markup are components inside the assessment, not
        additions on top of it, so neither the record nor the batch shows the
        207-cent raw sum.

        PRD 3.6: "The result is the record's `assessed_interchange_cents` at
        finalization, or its `provisional_assessed_cents` at intake, and both
        `cross_border_surcharge_cents` and `fx_markup_cents` are retained on the
        record as components *inside* that total rather than as additions on top
        of it."

        Design: Difficulty/combinatorial_formula/combinatorial_mode_a_nested_cap_then_floor_clamp_with_cross_border_and_fx
        """
        env = _cross_border_fx_record()
        finalize_batch(env["batch"]["id"])

        record = read_record(env["record"]["id"])
        assert record["qualification_status"] == "DOWNGRADED"
        assert record["qualified_rate_program_id"] == env["programs"]["STANDARD"]["id"]
        assert record["downgrade_reason"] == "MISSING_DATA_ELEMENTS"
        assert record["assessed_interchange_cents"] != 207

        batch = read_batch(env["batch"]["id"])
        assert batch["total_assessed_cents"] == 175


def _two_identical_small_records():
    """Two 1200-cent records with no clearing data elements at all, so both land
    on the 254 bps plus 10 cent fallback tier."""
    env = canonical_environment("2026-09-03T00:00:00Z")
    merchant = board_merchant(
        env["acquirer"]["id"], "GROCERY", headers=env["acquirer_headers"]
    )
    batch = open_batch(
        env["acquirer"]["id"], "2026-09-02", "USD", headers=env["acquirer_headers"]
    )
    records = []
    for auth_code in ("A00030", "A00031"):
        records.append(
            add_record(
                batch["id"],
                merchant["id"],
                1200,
                env["acquirer"]["id"],
                headers=env["acquirer_headers"],
                auth_code=auth_code,
                auth_timestamp="2026-09-01T00:00:00Z",
                clearing_timestamp="2026-09-01T02:00:00Z",
                data_elements=[],
            )
        )
    submit_batch(batch["id"], headers=env["acquirer_headers"])
    env["merchant"] = merchant
    env["batch"] = batch
    env["records"] = records
    return env


class TestRoundPerRecordThenSumTheBatchTotal:
    def test_each_record_rounds_to_forty_cents_on_the_fallback_tier(self):
        """1200 cents at 254 basis points is 30.48, which rounds to 30 before the
        10-cent flat fee is added, giving 40 cents per record.

        PRD 3.6: "Step one is the ad-valorem component: multiply the record's
        `amount_cents` by the program's `base_rate_bps`, divide by ten thousand,
        round half up to whole cents, and then add the program's
        `per_item_fee_cents`."

        Design: Difficulty/combinatorial_formula/combinatorial_mode_b_round_per_record_then_sum_batch_total
        """
        env = _two_identical_small_records()
        finalize_batch(env["batch"]["id"])

        for record in env["records"]:
            reread = read_record(record["id"])
            assert reread["assessed_interchange_cents"] == 40
            assert (
                reread["qualified_rate_program_id"]
                == env["programs"]["STANDARD"]["id"]
            )

    def test_the_batch_total_sums_the_rounded_addends_and_is_eighty_not_eighty_one(self):
        """Summing the two already-rounded 40-cent figures gives 80; accumulating
        the unrounded 30.48 products and rounding once would give 81.

        PRD 3.6: "Each addend is already a whole-cent figure rounded by the
        assessment pipeline — this is the round-then-sum discipline of Section 2.7,
        and accumulating unrounded products instead is forbidden."

        Design: Difficulty/combinatorial_formula/combinatorial_mode_b_round_per_record_then_sum_batch_total
        """
        env = _two_identical_small_records()
        finalize_batch(env["batch"]["id"])

        batch = read_batch(env["batch"]["id"])
        assert batch["record_count"] == 2
        assert batch["total_assessed_cents"] == 80
        assert batch["total_assessed_cents"] != 81

        merchant = read_merchant(env["merchant"]["id"])
        assert merchant["lifetime_net_assessed_cents"] == 80
        assert merchant["downgrade_count_current_quarter"] == 2


def _tier_two_enrollment():
    """One finalized record assessed at exactly 20000005 cents — five cents above
    the TIER_2 floor — behind an enrollment committed to 5000000 cents."""
    env = canonical_environment("2026-04-01T00:00:00Z")
    program = create_incentive_program(
        program_name="Tier Ladder 2026",
        eligible_mcc_codes=["5411"],
        total_capacity_cents=1000000000,
        min_commitment_cents=5000000,
        reopen_threshold_cents=5000000,
        performance_threshold_pct=1.00,
    )
    merchant = board_merchant(
        env["acquirer"]["id"],
        "GROCERY",
        headers=env["acquirer_headers"],
        legal_name="Volume Grocer",
    )
    set_clock("2026-05-01T00:00:00Z")
    enrollment = enrol_merchant(
        program["id"],
        merchant["id"],
        5000000,
        env["acquirer"]["id"],
        expected_incentive_program_version=program["version"],
        headers=env["acquirer_headers"],
    )
    batch = open_batch(
        env["acquirer"]["id"], "2026-05-15", "USD", headers=env["acquirer_headers"]
    )
    record = add_record(
        batch["id"],
        merchant["id"],
        787401378,
        env["acquirer"]["id"],
        expected_batch_version=batch["version"],
        headers=env["acquirer_headers"],
        auth_code="A00040",
        auth_timestamp="2026-05-15T00:00:00Z",
        clearing_timestamp="2026-05-15T01:00:00Z",
        data_elements=[],
    )
    submit_batch(batch["id"], headers=env["acquirer_headers"])
    finalize_batch(batch["id"])
    set_clock("2026-08-16T00:00:00Z")
    env["program"] = program
    env["merchant"] = merchant
    env["enrollment"] = enrollment
    env["batch"] = batch
    env["record"] = record
    return env


class TestIncentiveTierResolvedFromGross:
    def test_the_tier_and_the_credit_are_resolved_from_the_gross_figure(self):
        """A gross of 20000005 cents reaches the TIER_2 floor of 20000000, so the
        60 basis point discount grants a credit of 120000 and leaves a net of
        19880005.

        PRD 3.8: "Third, `incentive_credit_cents` is the gross multiplied by the
        tier's discount in basis points — 0 for `TIER_0`, 25 for `TIER_1`, 60 for
        `TIER_2` and 100 for `TIER_3` — divided by ten thousand and rounded half
        up to whole cents."

        Design: Difficulty/combinatorial_formula/combinatorial_mode_c_incentive_tier_resolved_from_gross_never_from_net
        """
        env = _tier_two_enrollment()
        assert read_record(env["record"]["id"])["assessed_interchange_cents"] == 20000005

        scored = evaluate_enrollment(env["enrollment"]["id"], "TRAILING")
        assert scored["gross_assessed_volume_cents"] == 20000005
        assert scored["tier_code"] == "TIER_2"
        assert scored["incentive_credit_cents"] == 120000
        assert scored["net_assessed_volume_cents"] == 19880005

    def test_the_tier_is_not_recomputed_from_the_net_figure(self):
        """The net of 19880005 falls below the TIER_2 floor it was derived from,
        and the enrollment still reports TIER_2 with a 120000-cent credit rather
        than the 49700 a second pass over the net would have produced.

        PRD 3.8: "There is no second pass and no fixed-point iteration: the tier
        is **never** recomputed from the net figure."

        Design: Difficulty/combinatorial_formula/combinatorial_mode_c_incentive_tier_resolved_from_gross_never_from_net
        """
        env = _tier_two_enrollment()

        scored = evaluate_enrollment(env["enrollment"]["id"], "TRAILING")
        assert scored["net_assessed_volume_cents"] < 20000000
        assert scored["tier_code"] == "TIER_2"
        assert scored["incentive_credit_cents"] != 49700
        assert float(scored["performance_score_pct"]) == 15748.03
        assert scored["status"] == "ENROLLED"
