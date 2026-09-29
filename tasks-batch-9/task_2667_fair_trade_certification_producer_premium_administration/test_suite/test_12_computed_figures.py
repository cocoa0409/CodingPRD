"""The arithmetic the service owns: licence fees, compliance scores, premium rounding and the
fund's three compartments."""

from test_helpers import (
    CHAIR,
    OFFICER,
    assert_clock_stamp,
    assert_created_at_ascending,
    assert_fund_conservation,
    assert_fund_partition,
    assert_instant,
    assert_ledger_entry,
    assert_money,
    assert_node_position,
    assert_pct,
    assert_score,
    assert_volume,
    factories as f,
    make_brand_licensee_headers,
    validate_paginated,
    validate_success,
)


def _certified_brand(api, legal_name="Nordic Roasters", country_code="SE"):
    """A CERTIFIED brand holding one chain-origin ACTIVE brand node."""
    brand = f.register_holder(
        api, legal_name=legal_name, holder_type="BRAND", country_code=country_code
    )
    headers = make_brand_licensee_headers(brand["id"])
    f.register_node(api, headers, holder_id=brand["id"], node_role="BRAND_NODE")
    f.certify(api, brand["id"])
    return brand["id"], headers


class TestLabelLicenceFees:
    """The marginal-rate schedule and the settlement test applied to what has been paid."""

    def test_a_600000_kg_licence_is_priced_across_all_three_marginal_bands(self, api, clock):
        """The first 100000 kilograms are billed at 1.20, the next 400000 at 0.80 and the last
        100000 at 0.45, and the fee only settles once the final cent arrives.

        Design: Corner/calculations/license_fee_straddles_all_three_marginal_tiers_at_600000_kg
        """
        brand_id, brand_headers = _certified_brand(api)

        licensed = f.issue_license(api, brand_id, 600000)

        assert_money(licensed["license_fee_cents"], 760725, "license_fee_cents")
        assert licensed["license_tier"] == "TIER_3"
        assert licensed["label_license_status"] == "ACTIVE"
        assert licensed["license_year"] == 2026
        assert_volume(licensed["licensed_volume_kg"], 600000, "licensed_volume_kg")
        assert_money(licensed["license_fee_paid_cents"], 0, "license_fee_paid_cents")

        almost = validate_success(
            api.pay_license_fee(brand_id, f.payment_payload(760724), brand_headers), 201
        )
        assert_money(almost["license_fee_paid_cents"], 760724, "license_fee_paid_cents")
        assert almost["license_fee_settled"] is False

        final = validate_success(
            api.pay_license_fee(brand_id, f.payment_payload(1), brand_headers), 201
        )
        assert_money(final["license_fee_paid_cents"], 760725, "license_fee_paid_cents")
        assert final["license_fee_settled"] is True

    def test_a_tier_one_fee_settles_only_after_the_second_instalment(self, api, clock):
        """Two part payments against a 100000 kilogram licence leave the priced fee alone and
        flip the settlement flag exactly once the total is reached.

        Design: Corner/endpoints/license_fee_payments_settle_the_fee_only_once_the_full_amount_is_paid
        """
        brand_id, brand_headers = _certified_brand(api)
        licensed = f.issue_license(api, brand_id, 100000)
        assert licensed["license_tier"] == "TIER_1"
        assert_money(licensed["license_fee_cents"], 382950, "license_fee_cents")
        assert_money(licensed["license_fee_paid_cents"], 0, "license_fee_paid_cents")
        assert licensed["license_fee_settled"] is False

        first = validate_success(
            api.pay_license_fee(brand_id, f.payment_payload(200000), brand_headers), 201
        )
        second = validate_success(
            api.pay_license_fee(brand_id, f.payment_payload(182950), brand_headers), 201
        )

        assert_money(first["license_fee_paid_cents"], 200000, "license_fee_paid_cents")
        assert first["license_fee_settled"] is False
        assert first["version"] == licensed["version"] + 1
        assert_money(second["license_fee_paid_cents"], 382950, "license_fee_paid_cents")
        assert second["license_fee_settled"] is True
        assert second["version"] == licensed["version"] + 2
        assert_money(second["license_fee_cents"], 382950, "license_fee_cents")
        assert second["label_license_status"] == "ACTIVE"


class TestComplianceScoring:
    """Only open, graded findings move a holder's score."""

    def test_a_closed_major_and_an_open_observation_both_leave_the_score_at_100(
        self, api, clock
    ):
        """A corrected finding drops out of the count, and an observation never counted, so the
        next finding is still priced against a perfect record.

        Design: Corner/calculations/compliance_score_excludes_closed_findings_and_observation_grade
        """
        producer = f.build_certified_producer(api)
        audit = f.build_started_audit(api, producer["holder_id"])
        major = f.raise_finding(api, audit["id"], "MAJOR")
        assert_instant(major["deadline_at"], "2026-09-15T00:00:00Z", "deadline_at")
        assert_score(major["compliance_score_at_raise"], 100, "compliance_score_at_raise")
        assert major["escalation_grace_days"] == 14
        validate_success(
            api.submit_cap(major["id"], f.cap_payload(), producer["holder_headers"]), 201
        )
        closed = validate_success(
            api.review_cap(major["id"], f.cap_review_payload("ACCEPT"), OFFICER), 200
        )
        assert closed["status"] == "CLOSED"

        observation = f.raise_finding(
            api, audit["id"], "OBSERVATION", "6.1.0", "Signage faded"
        )

        assert_score(
            observation["compliance_score_at_raise"], 100, "compliance_score_at_raise"
        )
        assert_instant(observation["deadline_at"], "2027-04-28T00:00:00Z", "deadline_at")
        assert observation["escalation_grace_days"] == 14
        assert observation["status"] == "OPEN"
        holder = f.read_holder(api, producer["holder_id"])
        assert_score(holder["compliance_score"], 100)
        assert holder["open_critical_count"] == 0
        assert holder["open_major_count"] == 0
        assert holder["open_minor_count"] == 0
        assert holder["next_audit_due_at"] is None, "no audit of this holder is closed yet"
        after = f.read_audit(api, audit["id"])
        assert after["nonconformity_count"] == 2
        assert after["open_nonconformity_count"] == 1


class TestPremiumRounding:
    """A three-decimal shipment exercises the half-up rule on both money fields."""

    def test_a_fractional_tonnage_rounds_the_premium_and_the_contract_total_half_up(
        self, api, clock
    ):
        """An organic lot of 1234.567 kilograms lands on a half cent in both the contract total
        and the premium, and both round away from zero.

        Design: Corner/calculations/premium_and_gross_value_round_half_up_on_a_three_decimal_volume
        """
        chain = f.build_certified_chain(api, harvest_kg=50000)

        trade = f.record_trade(
            api, chain, 1234.567, declared_unit_price_cents_per_kg=500, is_organic=True
        )

        assert_money(trade["applied_floor_cents_per_kg"], 400, "applied_floor_cents_per_kg")
        assert_money(
            trade["settled_unit_price_cents_per_kg"], 500, "settled_unit_price_cents_per_kg"
        )
        assert_money(trade["floor_topup_cents"], 0, "floor_topup_cents")
        assert_money(trade["gross_value_cents"], 617284, "gross_value_cents")
        assert_money(trade["premium_cents"], 123457, "premium_cents")
        assert_volume(trade["premium_volume_kg"], "1234.567", "premium_volume_kg")
        assert trade["premium_basis"] == "PHYSICAL_TRACEABILITY"
        assert_node_position(
            f.read_node(api, chain["seller_node_id"]),
            reserved_output_kg="1234.567", available_credit_kg="48765.433",
        )


class TestFundCompartments:
    """Accrual, commitment and disbursement move money between compartments without creating it."""

    def test_a_disbursed_proposal_leaves_the_fund_and_the_ledger_in_agreement(self, api, clock):
        """Three ledger rows tell the whole story of 2400000 accrued cents, of which 500000 have
        been paid out, and the fund's compartments still add up to what came in.

        Design: Corner/calculations/fund_conservation_holds_across_accrual_commitment_and_disbursement
        """
        chain = f.build_funded_committee(api, volume_kg=30000)
        proposal = f.draft_proposal(api, chain, 500000)
        validate_success(api.open_vote(proposal["id"], CHAIR), 200)
        f.cast_ballots(api, proposal["id"], ["APPROVE", "APPROVE", "APPROVE", "APPROVE"])
        approved = validate_success(api.close_vote(proposal["id"], CHAIR), 200)
        assert approved["status"] == "APPROVED"

        disbursed = validate_success(api.disburse_proposal(proposal["id"], OFFICER), 200)

        assert disbursed["status"] == "DISBURSED"
        assert_pct(disbursed["turnout_pct"], "80.00", "turnout_pct")
        assert_pct(disbursed["approval_pct"], "100.00", "approval_pct")
        fund = f.read_fund(api, chain["producer_id"])
        assert_fund_partition(
            fund,
            total_accrued_cents=2400000,
            balance_cents=1900000,
            committed_cents=0,
            disbursed_cents=500000,
        )
        assert fund["pending_proposal_count"] == 0

        rows, meta = validate_paginated(
            api.list_ledger_entries(OFFICER, {"fund_id": fund["id"]})
        )
        assert meta["total_count"] == 3
        assert_created_at_ascending(rows)
        assert [row["entry_type"] for row in rows] == ["ACCRUAL", "COMMITMENT", "DISBURSEMENT"]
        assert_ledger_entry(rows[0], "ACCRUAL", 2400000, balance_after_cents=2400000)
        assert_ledger_entry(
            rows[1], "COMMITMENT", 500000, balance_after_cents=1900000,
            proposal_id=proposal["id"],
        )
        assert_ledger_entry(
            rows[2], "DISBURSEMENT", 500000, balance_after_cents=1900000,
            proposal_id=proposal["id"],
        )
        assert_fund_conservation(fund, rows)
        committee = f.read_committee(api, chain["committee_id"])
        assert committee["status"] == "ACTIVE"
        assert committee["open_proposal_count"] == 0


class TestReadsAfterAWrite:
    """Every consequence of a settlement is already true on the first read that follows it."""

    def test_settlement_effects_are_visible_immediately_on_every_touched_resource(
        self, api, clock
    ):
        """The settle response, the two node reads, the fund and the ledger all agree without
        any second look, including the buyer's half-yield conversion.

        Design: Corner/consistency_model/settlement_effects_are_all_visible_without_any_re_read_delay
        """
        chain = f.build_certified_chain(api, conversion_ratio=0.5, harvest_kg=50000)
        trade = f.record_trade(api, chain, 10000)
        f.verify_trade(api, trade["id"])

        settled = validate_success(api.settle_trade(trade["id"], OFFICER), 200)

        assert settled["settlement_status"] == "SETTLED"
        assert_clock_stamp(settled["settled_at"], clock, "settled_at")
        assert_node_position(
            f.read_node(api, chain["seller_node_id"]),
            claimed_output_kg="10000.000",
            reserved_output_kg="0.000",
            available_credit_kg="40000.000",
        )
        assert_volume(
            f.read_node(api, chain["buyer_node_id"])["certified_input_kg"],
            "5000.000",
            "buyer certified_input_kg",
        )
        assert_fund_partition(
            f.read_fund(api, chain["producer_id"]),
            total_accrued_cents=800000, balance_cents=800000,
            committed_cents=0, disbursed_cents=0,
        )
        rows, meta = validate_paginated(
            api.list_ledger_entries(OFFICER, {"trade_transaction_id": trade["id"]})
        )
        assert meta["total_count"] == 1
        assert_ledger_entry(rows[0], "ACCRUAL", 800000, balance_after_cents=800000)
