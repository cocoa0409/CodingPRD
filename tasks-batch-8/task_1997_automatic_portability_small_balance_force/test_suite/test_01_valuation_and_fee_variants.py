"""Queue A difficulty tests: dual-variant calculations (valuation basis, fee day-count)."""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    make_participant_headers,
    make_provider_ops_headers,
    setup_established_ira,
    create_active_recordkeeper,
    create_plan,
    create_participant,
    create_open_batch,
    create_case,
    setup_ira_with_fee_disclosure,
)

OPS = TEST_USERS["provider_ops_headers"]
SPONSOR = TEST_USERS["plan_sponsor_headers"]


class TestValuationBasisDivergence:
    def test_valuation_basis_flips_band(self):
        """PRD §3.3: "the case's `vested_balance_cents` is the selected balance times
        `vesting_percent` divided by one hundred, rounded half-up to integer cents — where
        the selected balance is `separation_date_balance_cents` when the plan's
        `valuation_basis` is `SEPARATION_DATE`, or `processing_date_balance_cents` when it
        is `PROCESSING_DATE`."
        PRD §3.3: "a `vested_balance_cents` at or below the plan's `cash_out_threshold_cents`
        takes the `CASH_OUT` path; a balance above the cash-out threshold but at or below the
        `rollover_threshold_cents` takes `SAFE_HARBOR_IRA`"

        Design: Difficulty/dual_variant_calc/vested_balance_valuation_basis_divergence
        """
        rk = create_active_recordkeeper()
        plan_sep = create_plan(rk["id"], plan_name="Plan SEP", sponsor_ein="11-1111111",
                               valuation_basis="SEPARATION_DATE")
        plan_proc = create_plan(rk["id"], plan_name="Plan PROC", sponsor_ein="22-2222222",
                                valuation_basis="PROCESSING_DATE")
        p_a = create_participant(ssn_hash="hash-a")
        p_b = create_participant(ssn_hash="hash-b", full_name="Bob B")
        b_sep = create_open_batch(plan_sep["id"])
        b_proc = create_open_batch(plan_proc["id"])
        c_sep = create_case(b_sep["id"], plan_sep["id"], p_a["id"],
                            separation_date_balance_cents=90000,
                            processing_date_balance_cents=120000)
        c_proc = create_case(b_proc["id"], plan_proc["id"], p_b["id"],
                             separation_date_balance_cents=90000,
                             processing_date_balance_cents=120000)

        # Provisional quote is always the separation-date variant.
        assert c_sep["quoted_balance_cents"] == 90000
        assert c_proc["quoted_balance_cents"] == 90000

        get_success_data(api_client.lock_distribution_batch(b_sep["id"], SPONSOR))
        get_success_data(api_client.lock_distribution_batch(b_proc["id"], SPONSOR))

        c_sep = get_success_data(api_client.get_distribution_case(c_sep["id"], OPS))
        c_proc = get_success_data(api_client.get_distribution_case(c_proc["id"], OPS))
        assert c_sep["vested_balance_cents"] == 90000
        assert c_sep["force_out_path"] == "CASH_OUT"
        assert c_proc["vested_balance_cents"] == 120000
        assert c_proc["force_out_path"] == "SAFE_HARBOR_IRA"

    def test_valuation_basis_provisional_quote_independent_of_basis(self):
        """PRD §3.3: "At creation each case computes a provisional `quoted_balance_cents`:
        the separation-date balance times the vesting percent divided by one hundred,
        rounded half-up to integer cents."
        PRD §3.3: "the processing-date variant — the default — uses the balance at lock, so
        for identical inputs with drifted balances the two variants can produce different
        vested balances, possibly landing the case in a different force-out band."

        Design: Difficulty/dual_variant_calc/vested_balance_valuation_basis_divergence
        """
        rk = create_active_recordkeeper()
        plan_sep = create_plan(rk["id"], plan_name="Plan SEP", sponsor_ein="11-1111111",
                               valuation_basis="SEPARATION_DATE")
        plan_proc = create_plan(rk["id"], plan_name="Plan PROC", sponsor_ein="22-2222222",
                                valuation_basis="PROCESSING_DATE")
        p_a = create_participant(ssn_hash="hash-a")
        p_b = create_participant(ssn_hash="hash-b", full_name="Bob B")
        b_sep = create_open_batch(plan_sep["id"])
        b_proc = create_open_batch(plan_proc["id"])
        c_sep = create_case(b_sep["id"], plan_sep["id"], p_a["id"],
                            separation_date_balance_cents=90000,
                            processing_date_balance_cents=120000)
        c_proc = create_case(b_proc["id"], plan_proc["id"], p_b["id"],
                             separation_date_balance_cents=90000,
                             processing_date_balance_cents=120000)
        # Identical provisional quotes at creation, divergent vested balances after lock.
        assert c_sep["quoted_balance_cents"] == 90000
        assert c_proc["quoted_balance_cents"] == 90000
        get_success_data(api_client.lock_distribution_batch(b_sep["id"], SPONSOR))
        get_success_data(api_client.lock_distribution_batch(b_proc["id"], SPONSOR))
        c_sep = get_success_data(api_client.get_distribution_case(c_sep["id"], OPS))
        c_proc = get_success_data(api_client.get_distribution_case(c_proc["id"], OPS))
        assert c_sep["vested_balance_cents"] != c_proc["vested_balance_cents"]


class TestIraFeeDayCountConventionDivergence:
    def _setup_two_iras(self):
        """Two IRAs (ACTUAL_365 / THIRTY_360) funded 300000, FEE_DISCLOSURE delivered,
        clock at 2026-09-01T00:00:00Z."""
        rk = create_active_recordkeeper()
        plan = create_plan(rk["id"])
        p_a = create_participant(ssn_hash="hash-a")
        p_b = create_participant(ssn_hash="hash-b", full_name="Bob B")
        batch = create_open_batch(plan["id"])
        c_a = create_case(batch["id"], plan["id"], p_a["id"],
                          separation_date_balance_cents=300000,
                          processing_date_balance_cents=300000)
        c_b = create_case(batch["id"], plan["id"], p_b["id"],
                          separation_date_balance_cents=300000,
                          processing_date_balance_cents=300000)
        get_success_data(api_client.lock_distribution_batch(batch["id"], SPONSOR))
        for c, p in ((c_a, p_a), (c_b, p_b)):
            notice = get_success_data(api_client.create_notice(
                c["id"], {"notice_type": "FORCE_OUT_ELECTION"}, OPS))
            get_success_data(api_client.record_notice_delivery(
                notice["id"], {"outcome": "DELIVERED"}, OPS))
            fresh = get_success_data(api_client.get_distribution_case(c["id"], OPS))
            get_success_data(api_client.create_election(
                c["id"],
                {"election_type": "SAFE_HARBOR_IRA",
                 "expected_case_version": fresh["version"]},
                make_participant_headers(p["id"]),
            ))
        get_success_data(api_client.execute_distribution_batch(
            batch["id"], make_provider_ops_headers("ops_exec_1")))
        ira_a = get_success_data(api_client.create_safe_harbor_ira(
            {"distribution_case_id": c_a["id"],
             "fee_day_count_convention": "ACTUAL_365"}, OPS))
        ira_b = get_success_data(api_client.create_safe_harbor_ira(
            {"distribution_case_id": c_b["id"],
             "fee_day_count_convention": "THIRTY_360"}, OPS))
        for c in (c_a, c_b):
            fd = get_success_data(api_client.create_notice(
                c["id"], {"notice_type": "FEE_DISCLOSURE"}, OPS))
            get_success_data(api_client.record_notice_delivery(
                fd["id"], {"outcome": "DELIVERED"}, OPS))
        get_success_data(api_client.set_clock("2026-09-01T00:00:00Z", OPS))
        return ira_a, ira_b

    def test_fee_day_count_divergence_amounts(self):
        """PRD §3.6: "Either way the fee is rounded half-up to integer cents: an
        August-1-to-September-1 period bills 510 cents under `ACTUAL_365` (thirty-one days)
        and 500 cents under `THIRTY_360` (thirty days)."

        Design: Difficulty/dual_variant_calc/ira_fee_day_count_convention_divergence
        """
        ira_a, ira_b = self._setup_two_iras()
        fee_a = validate_success(api_client.assess_ira_fee(ira_a["id"], OPS), 201)
        fee_b = validate_success(api_client.assess_ira_fee(ira_b["id"], OPS), 201)
        assert fee_a["amount_cents"] == 510
        assert fee_a["days_in_period"] == 31
        assert fee_b["amount_cents"] == 500
        assert fee_b["days_in_period"] == 30

    def test_fee_day_count_divergence_balances(self):
        """PRD §3.6: "in the same stroke the IRA's `balance_cents` drops by the amount,
        `total_fees_cents` rises by the same"

        Design: Difficulty/dual_variant_calc/ira_fee_day_count_convention_divergence
        """
        ira_a, ira_b = self._setup_two_iras()
        validate_success(api_client.assess_ira_fee(ira_a["id"], OPS), 201)
        validate_success(api_client.assess_ira_fee(ira_b["id"], OPS), 201)
        fresh_a = get_success_data(api_client.get_safe_harbor_ira(ira_a["id"], OPS))
        fresh_b = get_success_data(api_client.get_safe_harbor_ira(ira_b["id"], OPS))
        assert fresh_a["balance_cents"] == 299490
        assert fresh_a["total_fees_cents"] == 510
        assert fresh_b["balance_cents"] == 299500
        assert fresh_b["total_fees_cents"] == 500
