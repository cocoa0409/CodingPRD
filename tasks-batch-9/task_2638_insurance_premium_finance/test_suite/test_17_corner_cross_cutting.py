"""Cross-cutting corners: the version guard on endorsement financing must refuse a
stale number without consuming one, the unearned-premium estimate rounds twice
under a short-rate statute and once per policy before it is summed, and every
derived field in the ledger is already correct in the response of the write that
caused it.
"""

from test_helpers import (
    ApiErrorId,
    add_on_finance_charge_cents,
    assert_installments_sum,
    factories,
    fixtures,
    is_iso8601_timestamp,
    late_fee_cents,
    level_components,
    level_installment_amounts,
    pro_rata_unearned_premium_cents,
    round_half_up,
    rule_of_78_rebate_cents,
    short_rate_unearned_premium_cents,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.test_users import (
    ANALYST_NOTICE,
    ANALYST_ORIGIN,
    COMPLIANCE,
    make_analyst_headers,
)

ANALYST_EXECUTE = make_analyst_headers("analyst-execute")


class TestStaleAgreementVersionOnEndorsementFinancing:
    """Folding endorsements in is legitimately repeatable, so the only thing
    standing between two clients is the note's `version`."""

    def _endorsed(self, api):
        """The canonical note, ACTIVE, with one PENDING 60000 endorsement and the
        version observed at each step along the way."""
        ctx = fixtures.origination_context(
            api,
            insured_payload=factories.insured(
                legal_name="Cascade Logistics Inc", email="ap@cascade.example"
            ),
        )
        bundle = fixtures.draft_agreement(
            api,
            ctx,
            policies=[
                factories.financed_policy(
                    ctx["insurer_id"], policy_number="MC-OCC-1"
                )
            ],
        )
        bundle["v_create"] = bundle["agreement"]["version"]
        bundle["v_policy"] = fixtures.agreement_version(api, bundle["agreement_id"])
        bundle["submitted"] = validate_success(
            api.submit_agreement(bundle["agreement_id"], ANALYST_ORIGIN), 200
        )
        validate_success(
            api.create_verification(
                bundle["policy_id"],
                factories.confirmed_verification(),
                bundle["insurer_headers"],
            ),
            201,
        )
        validate_success(
            api.create_verification(
                bundle["policy_id"],
                factories.confirmed_verification(),
                bundle["agent_headers"],
            ),
            201,
        )
        bundle["v_verified"] = fixtures.agreement_version(api, bundle["agreement_id"])
        bundle["activated"] = validate_success(
            api.activate_agreement(bundle["agreement_id"], ANALYST_ORIGIN), 200
        )
        bundle["endorsement1"] = validate_success(
            api.create_endorsement(
                bundle["policy_id"],
                factories.endorsement(60000, effective_date="2026-09-15"),
                bundle["agent_headers"],
            ),
            201,
        )
        return bundle

    def _financed_once(self, api):
        """The same note with that endorsement folded in at the correct version."""
        bundle = self._endorsed(api)
        bundle["financing1"] = validate_success(
            api.finance_endorsements(
                bundle["agreement_id"],
                {"expected_agreement_version": bundle["activated"]["version"]},
                ANALYST_ORIGIN,
            ),
            200,
        )
        return bundle

    def test_the_note_counts_one_version_per_mutation_of_its_own_row(self, api):
        """Creation, attachment, submission and activation are four writes to the
        note; the two attestations are writes to the policy.

        The PRD states: "`version` starts at 1 when the row is created and increases
        by exactly 1 on every mutation of that row; `updated_at` is refreshed to the
        logical-clock instant on the same mutation."

        Design: Corner/cross_cutting_complexity_layers/optimistic_concurrency_stale_agreement_version_on_endorsement_financing
        """
        bundle = self._endorsed(api)

        assert bundle["v_create"] == 1
        assert bundle["v_policy"] == 2, "attaching a policy mutates the note"
        assert bundle["submitted"]["version"] == 3
        assert bundle["activated"]["version"] == bundle["v_verified"] + 1
        assert bundle["activated"]["total_of_payments_cents"] == 539650
        assert bundle["endorsement1"]["signed_amount_cents"] == 60000, (
            "an ADDITIONAL_PREMIUM signs positive"
        )
        assert bundle["endorsement1"]["status"] == "PENDING"

    def test_a_version_that_has_been_overtaken_is_refused(self, api):
        """The number read at submission is stale by the time the note is active.

        The PRD states: "Folding endorsements in rebuilds the remaining installment
        schedule from the agreement's current money fields, so if the stored
        `version` has moved on since that read, the schedule the request intends to
        supersede is not the schedule the server holds; the request is rejected with
        `ERR_STALE_AGREEMENT_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/optimistic_concurrency_stale_agreement_version_on_endorsement_financing
        """
        bundle = self._endorsed(api)

        assert bundle["submitted"]["version"] < bundle["activated"]["version"]
        validate_error(
            api.finance_endorsements(
                bundle["agreement_id"],
                {"expected_agreement_version": bundle["submitted"]["version"]},
                ANALYST_ORIGIN,
            ),
            ApiErrorId.STALE_AGREEMENT_VERSION,
            412,
        )

    def test_the_refused_request_does_not_consume_a_version(self, api):
        """A 412 that advanced the version would make the account unfinanceable.

        The PRD states: "A single request frequently mutates several rows, and each
        mutated row bumps its own `version` independently."

        Design: Corner/cross_cutting_complexity_layers/optimistic_concurrency_stale_agreement_version_on_endorsement_financing
        """
        bundle = self._endorsed(api)

        validate_error(
            api.finance_endorsements(
                bundle["agreement_id"],
                {"expected_agreement_version": bundle["submitted"]["version"]},
                ANALYST_ORIGIN,
            ),
            ApiErrorId.STALE_AGREEMENT_VERSION,
            412,
        )

        note = fixtures.read_agreement(api, bundle["agreement_id"])
        assert note["version"] == bundle["activated"]["version"], (
            "the version the client just read is still the version to retry with"
        )
        assert note["total_of_payments_cents"] == 539650
        assert note["principal_balance_cents"] == 502000
        rows, meta = validate_paginated(
            api.list_endorsements(
                bundle["policy_id"], ANALYST_ORIGIN, {"status": "PENDING", "limit": 50}
            )
        )
        assert meta["total_count"] == 1
        assert rows[0]["status"] == "PENDING", "nothing was folded in"

    def test_the_expected_version_is_mandatory_rather_than_optional(self, api):
        """Omitting the field is a request-shape failure, not a licence to skip the
        check.

        The PRD states: "Financing the pending endorsements of an agreement requires
        `expected_agreement_version` as a mandatory input field, carrying the
        `version` of the `PremiumFinanceAgreement` the client last observed."

        Design: Corner/cross_cutting_complexity_layers/optimistic_concurrency_stale_agreement_version_on_endorsement_financing
        """
        bundle = self._endorsed(api)

        validate_error(
            api.finance_endorsements(bundle["agreement_id"], {}, ANALYST_ORIGIN),
            ApiErrorId.INVALID_REQUEST.value,
            400,
        )

        assert (
            fixtures.read_agreement(api, bundle["agreement_id"])["version"]
            == bundle["activated"]["version"]
        )

    def test_the_current_version_reprices_the_note_over_the_new_basis(self, api):
        """The endorsement enters the financed premium and the whole quote moves.

        The PRD states: "The note is then repriced in the pricing engine's final
        variant over that new basis, which can move `total_premium_cents`,
        `amount_financed_cents`, the volume tier, `effective_annual_rate_bps`,
        `finance_charge_cents` and `total_of_payments_cents`, and the schedule is
        rebuilt over the unpaid tail only."

        Design: Corner/cross_cutting_complexity_layers/optimistic_concurrency_stale_agreement_version_on_endorsement_financing
        """
        bundle = self._financed_once(api)
        financed = bundle["financing1"]

        assert financed["version"] == bundle["activated"]["version"] + 1
        assert financed["quote_basis"] == "FINAL"
        assert financed["total_premium_cents"] == 660000 == 600000 + 60000
        assert financed["amount_financed_cents"] == 660000 - 100000 + 2000 == 562000
        assert financed["effective_annual_rate_bps"] == 1500
        assert financed["finance_charge_cents"] == add_on_finance_charge_cents(
            562000, 1500, 6
        ) == 42150
        assert financed["total_of_payments_cents"] == 562000 + 42150 == 604150
        assert financed["principal_balance_cents"] == 562000
        assert financed["unpaid_finance_charge_cents"] == 42150

    def test_the_schedule_is_rebuilt_rather_than_patched(self, api):
        """Six untouched installments are recut over the new total of payments.

        The PRD states: "Under `ADD_ON` the note pays level installments: the base
        amount is `total_of_payments_cents` divided by `installment_count` and
        truncated down to whole cents, every installment except the last takes that
        base amount, and the last installment takes `total_of_payments_cents` minus
        the base amount multiplied by one less than the installment count."

        Design: Corner/cross_cutting_complexity_layers/optimistic_concurrency_stale_agreement_version_on_endorsement_financing
        """
        bundle = self._financed_once(api)

        rows = sorted(
            fixtures.read_installments(api, bundle["agreement_id"]),
            key=lambda row: row["installment_number"],
        )
        amounts = level_installment_amounts(604150, 6)
        components = level_components(42150, 6)

        assert len(rows) == 6
        assert amounts[0] == 100691 == 604150 // 6
        assert amounts[-1] == 100695 == 604150 - 100691 * 5
        assert components[0] == 7025 == round_half_up(42150, 6)
        for row, amount, component in zip(rows, amounts, components):
            assert row["amount_cents"] == amount
            assert row["finance_charge_component_cents"] == component
            assert row["principal_component_cents"] == amount - component
        assert_installments_sum(rows, 604150, 42150)

    def test_replaying_a_previously_accepted_version_is_refused(self, api):
        """The check is against the stored version, not against numbers once
        accepted.

        The PRD states: "Two write operations are legitimately repeatable and
        therefore cannot be protected by a state precondition: folding endorsements
        into a note (each new endorsement is financed by its own call) and offsetting
        a chargeback against an agency's reserve (partial offsets may recur until the
        remainder is settled)."

        Design: Corner/cross_cutting_complexity_layers/optimistic_concurrency_stale_agreement_version_on_endorsement_financing
        """
        bundle = self._financed_once(api)
        second = validate_success(
            api.create_endorsement(
                bundle["policy_id"],
                factories.endorsement(30000, effective_date="2026-09-20"),
                bundle["agent_headers"],
            ),
            201,
        )

        assert second["status"] == "PENDING", (
            "a financeable endorsement exists, so a 422 is not available"
        )
        validate_error(
            api.finance_endorsements(
                bundle["agreement_id"],
                {"expected_agreement_version": bundle["activated"]["version"]},
                ANALYST_ORIGIN,
            ),
            ApiErrorId.STALE_AGREEMENT_VERSION,
            412,
        )

    def test_the_freshly_read_version_finances_the_second_endorsement(self, api):
        """Repeatable means repeatable: the same endpoint runs twice on one note.

        The PRD states: "Every qualifying endorsement then moves `PENDING` →
        `FINANCED` and has its `financed_at` stamped from the logical clock." and
        "Each affected policy's `endorsed_premium_cents` becomes the sum of
        `signed_amount_cents` over its `FINANCED` endorsements — so a return premium
        reduces it — and its `financed_premium_cents` is re-derived as
        `verified_premium_cents` plus `endorsed_premium_cents`."

        Design: Corner/cross_cutting_complexity_layers/optimistic_concurrency_stale_agreement_version_on_endorsement_financing
        """
        bundle = self._financed_once(api)
        validate_success(
            api.create_endorsement(
                bundle["policy_id"],
                factories.endorsement(30000, effective_date="2026-09-20"),
                bundle["agent_headers"],
            ),
            201,
        )

        again = validate_success(
            api.finance_endorsements(
                bundle["agreement_id"],
                {"expected_agreement_version": bundle["financing1"]["version"]},
                ANALYST_ORIGIN,
            ),
            200,
        )

        assert again["version"] == bundle["financing1"]["version"] + 1
        assert again["total_premium_cents"] == 690000
        assert again["amount_financed_cents"] == 690000 - 100000 + 2000 == 592000
        assert again["finance_charge_cents"] == add_on_finance_charge_cents(
            592000, 1500, 6
        ) == 44400
        assert again["total_of_payments_cents"] == 592000 + 44400 == 636400
        assert again["principal_balance_cents"] == 592000
        assert again["unpaid_finance_charge_cents"] == 44400

        policy = fixtures.read_policy(api, bundle["policy_id"])
        assert policy["endorsed_premium_cents"] == 60000 + 30000 == 90000
        assert policy["financed_premium_cents"] == 600000 + 90000 == 690000
        rows = fixtures.read_endorsements(api, bundle["policy_id"])
        assert [row["status"] for row in rows] == ["FINANCED", "FINANCED"]
        assert all(is_iso8601_timestamp(row["financed_at"]) for row in rows)


class TestProRataVersusShortRateUnearnedPremiumReturn:
    """Two regimes that differ in one statutory word send the same exposure back
    at two different amounts, and the short-rate variant rounds a second time."""

    T_TERM_DAYS = 365
    T_UNEARNED_DAYS = 314

    def _two_books(self, api):
        """One TX (`PRO_RATA`) note over a single policy and one OK (`SHORT_RATE`)
        note over three, both ACTIVE at the same clock."""
        fixtures.set_clock(api, fixtures.CLOCK_ORIGINATION)
        tx = fixtures.create_state_regime(
            api,
            rule_payload=factories.tx_state_rate_rule(),
            license_payload=factories.license_payload(license_number="PFC-TX-001"),
        )
        ok = fixtures.create_state_regime(
            api,
            rule_payload=factories.state_rate_rule(
                "OK", unearned_premium_method="SHORT_RATE", short_rate_penalty_bps=1000
            ),
            license_payload=factories.license_payload(license_number="PFC-OK-001"),
        )
        parties = fixtures.create_parties(
            api,
            insured_payload=factories.insured(
                legal_name="Cascade Logistics Inc", email="ap@cascade.example"
            ),
        )
        book = {"tx": tx, "ok": ok}
        book.update(parties)

        note_t = validate_success(
            api.create_agreement(
                factories.agreement(
                    book["insured_id"], book["agent_id"], tx["rule_id"]
                ),
                ANALYST_ORIGIN,
            ),
            201,
        )
        t600 = validate_success(
            api.attach_policy(
                note_t["id"],
                factories.financed_policy(
                    book["insurer_id"],
                    policy_number="MC-DV-T600",
                    gross_premium_cents=600000,
                ),
                ANALYST_ORIGIN,
            ),
            201,
        )
        note_k = validate_success(
            api.create_agreement(
                factories.agreement(
                    book["insured_id"],
                    book["agent_id"],
                    ok["rule_id"],
                    down_payment_cents=200000,
                ),
                ANALYST_ORIGIN,
            ),
            201,
        )
        k_ids = {}
        for number, premium in (
            ("MC-DV-K302", 302000),
            ("MC-DV-K305", 305000),
            ("MC-DV-K600", 600000),
        ):
            row = validate_success(
                api.attach_policy(
                    note_k["id"],
                    factories.financed_policy(
                        book["insurer_id"],
                        policy_number=number,
                        gross_premium_cents=premium,
                    ),
                    ANALYST_ORIGIN,
                ),
                201,
            )
            k_ids[number] = row["id"]

        for agreement_id in (note_t["id"], note_k["id"]):
            validate_success(api.submit_agreement(agreement_id, ANALYST_ORIGIN), 200)
        for policy_id in [t600["id"]] + list(k_ids.values()):
            for headers in (book["insurer_headers"], book["agent_headers"]):
                validate_success(
                    api.create_verification(
                        policy_id, factories.confirmed_verification(), headers
                    ),
                    201,
                )

        book["note_t"] = validate_success(
            api.activate_agreement(note_t["id"], ANALYST_ORIGIN), 200
        )
        book["note_k"] = validate_success(
            api.activate_agreement(note_k["id"], ANALYST_ORIGIN), 200
        )
        book["t_id"] = note_t["id"]
        book["k_id"] = note_k["id"]
        book["t600_id"] = t600["id"]
        book["k_ids"] = k_ids
        return book

    def _noticed(self, api):
        """Both notes swept into `LATE` and served with a notice on the same day."""
        book = self._two_books(api)
        fixtures.set_clock(api, "2026-10-12T00:00:00Z")
        book["sweep"] = validate_success(api.run_servicing(COMPLIANCE), 200)
        book["notice_t"] = validate_success(
            api.issue_cancellation_notice(book["t_id"], ANALYST_NOTICE), 201
        )
        book["notice_k"] = validate_success(
            api.issue_cancellation_notice(book["k_id"], ANALYST_NOTICE), 201
        )
        return book

    def _cancelled(self, api):
        """Both powers of attorney exercised on the statutory date."""
        book = self._noticed(api)
        fixtures.set_clock(api, "2026-10-22T00:00:00Z")
        book["exec_t"] = validate_success(
            api.execute_cancellation(book["t_id"], ANALYST_EXECUTE), 200
        )
        book["exec_k"] = validate_success(
            api.execute_cancellation(book["k_id"], ANALYST_EXECUTE), 200
        )
        return book

    def test_the_two_regimes_differ_in_one_statutory_word(self, api):
        """Everything else about the two statutes is identical, so the return
        method is the only free variable in this experiment.

        The PRD states: "Under a `PRO_RATA` regime that pro-rata figure *is* the
        estimate." and "`unearned_premium_method` is either `PRO_RATA` or `SHORT_RATE`
        and selects how the platform estimates a carrier's return"

        Design: Corner/cross_cutting_complexity_layers/dual_variant_calculation_pro_rata_versus_short_rate_unearned_premium_return
        """
        book = self._two_books(api)
        tx_rule, ok_rule = book["tx"]["rule"], book["ok"]["rule"]

        assert tx_rule["unearned_premium_method"] == "PRO_RATA"
        assert ok_rule["unearned_premium_method"] == "SHORT_RATE"
        assert ok_rule["short_rate_penalty_bps"] == 1000
        for field in (
            "finance_charge_method",
            "max_annual_rate_bps",
            "max_service_fee_cents",
            "min_down_payment_bps",
            "max_term_months",
            "late_fee_bps",
            "late_fee_min_cents",
            "late_fee_max_cents",
            "grace_period_days",
            "noic_notice_days",
            "rebate_method",
        ):
            assert tx_rule[field] == ok_rule[field], (
                f"{field} must not vary between the two regimes"
            )
        assert tx_rule["state_code"] == "TX"
        assert ok_rule["state_code"] == "OK"

    def test_both_notes_price_under_the_same_add_on_engine(self, api):
        """The unearned-premium method is a cancellation-time parameter and touches
        nothing at origination.

        The PRD states: "Under `ADD_ON`, the whole finance charge is computed once:
        multiply `amount_financed_cents` by `effective_annual_rate_bps`, multiply by
        `installment_count`, divide by 10000 to convert basis points and by 12 to
        convert an annual rate to monthly, and round the single result half up to
        whole cents — that figure becomes `finance_charge_cents`."

        Design: Corner/cross_cutting_complexity_layers/dual_variant_calculation_pro_rata_versus_short_rate_unearned_premium_return
        """
        book = self._two_books(api)
        note_t, note_k = book["note_t"], book["note_k"]

        assert note_t["total_premium_cents"] == 600000
        assert note_t["amount_financed_cents"] == 502000
        assert note_t["effective_annual_rate_bps"] == 1500
        assert note_t["finance_charge_cents"] == 37650
        assert note_t["total_of_payments_cents"] == 539650

        assert note_k["total_premium_cents"] == 302000 + 305000 + 600000 == 1207000
        assert 200000 * 10000 >= 1207000 * 1500, "the down payment clears 1500 bps"
        assert note_k["amount_financed_cents"] == 1207000 - 200000 + 2000 == 1009000
        assert note_k["effective_annual_rate_bps"] == 1500, (
            "1009000 sits in the same volume tier as 502000"
        )
        assert note_k["finance_charge_cents"] == add_on_finance_charge_cents(
            1009000, 1500, 6
        ) == 75675
        assert note_k["total_of_payments_cents"] == 1009000 + 75675 == 1084675
        assert note_k["principal_balance_cents"] == 1009000
        assert note_k["unpaid_finance_charge_cents"] == 75675

    def test_the_sweep_delinquences_both_books_on_the_same_pass(self, api):
        """One pass over the whole book, two notes, two statutory fee bands that
        happen to be identical.

        The PRD states: "The pass reports three counts: `past_due_marked`,
        `late_fees_assessed` and `agreements_advanced_to_late`."

        Design: Corner/cross_cutting_complexity_layers/dual_variant_calculation_pro_rata_versus_short_rate_unearned_premium_return
        """
        book = self._noticed(api)
        sweep = book["sweep"]

        assert sweep["past_due_marked"] == 2
        assert sweep["late_fees_assessed"] == 2
        assert sweep["agreements_advanced_to_late"] == 2

        fees_t = fixtures.read_late_fees(api, book["t_id"])
        fees_k = fixtures.read_late_fees(api, book["k_id"])
        assert [row["amount_cents"] for row in fees_t] == [
            late_fee_cents(89941, 500, 500, 10000)
        ] == [4497]
        assert [row["amount_cents"] for row in fees_k] == [
            late_fee_cents(180779, 500, 500, 10000)
        ] == [9039]

    def test_the_schedules_are_level_under_both_statutes(self, api):
        """The installment the late fee was struck against is the level amount of
        each note.

        The PRD states: "every installment except the last takes that base amount,
        and the last installment takes `total_of_payments_cents` minus the base
        amount multiplied by one less than the installment count."

        Design: Corner/cross_cutting_complexity_layers/dual_variant_calculation_pro_rata_versus_short_rate_unearned_premium_return
        """
        book = self._two_books(api)

        rows_t = sorted(
            fixtures.read_installments(api, book["t_id"]),
            key=lambda row: row["installment_number"],
        )
        rows_k = sorted(
            fixtures.read_installments(api, book["k_id"]),
            key=lambda row: row["installment_number"],
        )
        assert [row["amount_cents"] for row in rows_t] == level_installment_amounts(
            539650, 6
        ) == [89941, 89941, 89941, 89941, 89941, 89945]
        assert [row["amount_cents"] for row in rows_k] == level_installment_amounts(
            1084675, 6
        ) == [180779, 180779, 180779, 180779, 180779, 180780]
        assert [
            row["finance_charge_component_cents"] for row in rows_k
        ] == level_components(75675, 6)
        assert_installments_sum(rows_t, 539650, 37650)
        assert_installments_sum(rows_k, 1084675, 75675)

    def test_both_notices_run_the_same_statutory_timeline(self, api):
        """The variant under test must not be confused with a difference in dates.

        The PRD states: "`notice_days` snapshotted from the regime's
        `noic_notice_days` at that moment, and `effective_cancel_date` set to
        `issued_date` advanced by `notice_days` calendar days."

        Design: Corner/cross_cutting_complexity_layers/dual_variant_calculation_pro_rata_versus_short_rate_unearned_premium_return
        """
        book = self._noticed(api)

        for notice in (book["notice_t"], book["notice_k"]):
            assert notice["status"] == "ISSUED"
            assert notice["issued_date"] == "2026-10-12"
            assert notice["notice_days"] == 10
            assert notice["effective_cancel_date"] == "2026-10-22"

    def test_the_pro_rata_regime_returns_the_whole_unearned_share(self, api):
        """The rounded quotient is the estimate and nothing is deducted from it.

        The PRD states: "Otherwise the pro-rata figure is the policy's
        `financed_premium_cents` multiplied by the unearned days, divided by the term
        length in days, rounded half up."

        Design: Corner/cross_cutting_complexity_layers/dual_variant_calculation_pro_rata_versus_short_rate_unearned_premium_return
        """
        book = self._cancelled(api)

        policy = fixtures.read_policy(api, book["t600_id"])
        assert policy["cancellation_effective_date"] == "2026-10-22"
        assert policy["earned_days"] == 51
        assert self.T_TERM_DAYS - policy["earned_days"] == self.T_UNEARNED_DAYS
        assert policy["unearned_premium_estimate_cents"] == (
            pro_rata_unearned_premium_cents(600000, 314, 365)
        ) == 516164
        assert book["exec_t"]["estimated_unearned_premium_cents"] == 516164

        rows, meta = validate_paginated(
            api.list_carrier_cancellation_requests(
                ANALYST_EXECUTE, {"agreement_id": book["t_id"], "limit": 50}
            )
        )
        assert meta["total_count"] == 1
        assert rows[0]["estimate_method"] == "PRO_RATA"
        assert rows[0]["computed_unearned_premium_cents"] == 516164

    def test_the_short_rate_regime_keeps_a_penalty_on_the_same_exposure(self, api):
        """An identical policy cancelled on an identical date returns strictly less.

        The PRD states: "the estimate is the already-rounded pro-rata figure
        multiplied by 10000 minus the regime's `short_rate_penalty_bps`, divided by
        10000, and rounded half up again." and "Because the same policy cancelled on
        the same date yields a strictly smaller return under `SHORT_RATE`, it also
        yields a strictly larger deficiency downstream."

        Design: Corner/cross_cutting_complexity_layers/dual_variant_calculation_pro_rata_versus_short_rate_unearned_premium_return
        """
        book = self._cancelled(api)

        twin = fixtures.read_policy(api, book["k_ids"]["MC-DV-K600"])
        assert twin["earned_days"] == 51, "the same elapsed window as its TX twin"
        assert twin["unearned_premium_estimate_cents"] == (
            short_rate_unearned_premium_cents(516164, 1000)
        ) == 464548
        assert 464548 < 516164
        assert 516164 - 464548 == 51616, "a tenth of the rounded pro-rata figure"

        rows, _ = validate_paginated(
            api.list_carrier_cancellation_requests(
                ANALYST_EXECUTE,
                {"policy_id": book["k_ids"]["MC-DV-K600"], "limit": 50},
            )
        )
        assert rows[0]["estimate_method"] == "SHORT_RATE"
        assert rows[0]["computed_unearned_premium_cents"] == 464548

    def test_each_estimate_is_rounded_twice_and_before_the_sum(self, api):
        """Rounding the pro-rata quotient, then the penalty, then summing, is a
        different number from any single-rounding shortcut.

        The PRD states: "The penalty is applied to the rounded pro-rata figure, not
        to an exact quotient." and "The aggregate the operation reports is the sum of
        the per-policy estimates, each rounded before the summation."

        Design: Corner/cross_cutting_complexity_layers/dual_variant_calculation_pro_rata_versus_short_rate_unearned_premium_return
        """
        book = self._cancelled(api)

        small = fixtures.read_policy(api, book["k_ids"]["MC-DV-K302"])
        middle = fixtures.read_policy(api, book["k_ids"]["MC-DV-K305"])
        assert pro_rata_unearned_premium_cents(302000, 314, 365) == 259803
        assert small["unearned_premium_estimate_cents"] == (
            short_rate_unearned_premium_cents(259803, 1000)
        ) == 233823, "233822 would be the single-rounding answer"
        assert pro_rata_unearned_premium_cents(305000, 314, 365) == 262384
        assert middle["unearned_premium_estimate_cents"] == (
            short_rate_unearned_premium_cents(262384, 1000)
        ) == 236146

        assert book["exec_k"]["estimated_unearned_premium_cents"] == (
            233823 + 236146 + 464548
        ) == 934517, "each policy rounds before the aggregate is taken"
        assert round_half_up((259803 + 262384 + 516164) * 9000, 10000) == 934516, (
            "penalising the summed pro-rata figure once would lose a cent"
        )

    def test_one_carrier_request_is_raised_per_cancelled_policy(self, api):
        """Three policies on one note means three carriers to chase, each carrying
        its own estimate under the same snapshotted method.

        The PRD states: "One carrier cancellation request is created per cancelled
        policy, in `REQUESTED` status, carrying the `agreement_id` and `policy_id` it
        concerns, a `requested_date` of the clock date, the same
        `cancellation_effective_date`, the acting analyst as `requested_by_user_id`,
        the estimate as `computed_unearned_premium_cents`, and the regime's
        `unearned_premium_method` snapshotted as `estimate_method`."

        Design: Corner/cross_cutting_complexity_layers/dual_variant_calculation_pro_rata_versus_short_rate_unearned_premium_return
        """
        book = self._cancelled(api)

        assert book["exec_t"]["requests_created"] == 1
        assert book["exec_k"]["requests_created"] == 3
        rows, meta = validate_paginated(
            api.list_carrier_cancellation_requests(
                ANALYST_EXECUTE, {"agreement_id": book["k_id"], "limit": 50}
            )
        )
        assert meta["total_count"] == 3
        assert {row["status"] for row in rows} == {"REQUESTED"}
        assert {row["estimate_method"] for row in rows} == {"SHORT_RATE"}
        assert {row["requested_date"] for row in rows} == {"2026-10-22"}
        assert {row["cancellation_effective_date"] for row in rows} == {"2026-10-22"}
        assert {row["requested_by_user_id"] for row in rows} == {"analyst-execute"}
        assert sum(row["computed_unearned_premium_cents"] for row in rows) == 934517
        assert {
            fixtures.read_policy(api, policy_id)["status"]
            for policy_id in book["k_ids"].values()
        } == {"CANCELLED"}

    def test_the_gross_balance_is_principal_plus_the_post_rebate_charge(self, api):
        """Neither note paid an installment, so the whole finance charge is rebated
        and the reported balance is bare principal under both statutes.

        The PRD states: "and the `gross_balance_cents` of the note — its
        `principal_balance_cents` plus its post-rebate `unpaid_finance_charge_cents`."

        Design: Corner/cross_cutting_complexity_layers/dual_variant_calculation_pro_rata_versus_short_rate_unearned_premium_return
        """
        book = self._cancelled(api)

        assert book["exec_t"]["rebate_applied_cents"] == (
            rule_of_78_rebate_cents(37650, 6, 6)
        ) == 37650
        assert book["exec_t"]["gross_balance_cents"] == 502000, (
            "the 4497 late fee is not part of this figure"
        )
        assert book["exec_k"]["rebate_applied_cents"] == (
            rule_of_78_rebate_cents(75675, 6, 6)
        ) == 75675
        assert book["exec_k"]["gross_balance_cents"] == 1009000
        assert fixtures.read_agreement(api, book["k_id"])[
            "unpaid_finance_charge_cents"
        ] == 0


class TestEveryDerivedFieldIsCorrectInTheCausingResponse:
    """Derived state here is spread across four entities, and every write must
    return its own post-write truth with no settling delay behind it."""

    def _walk(self, api):
        """One linear origination, each write's response and the read that follows
        it captured exactly once — no retry, no sleep, no second read."""
        ctx = fixtures.origination_context(
            api,
            insured_payload=factories.insured(
                legal_name="Cascade Logistics Inc", email="ap@cascade.example"
            ),
        )
        walk = dict(ctx)

        walk["w_note"] = validate_success(
            api.create_agreement(
                factories.agreement(
                    ctx["insured_id"], ctx["agent_id"], ctx["rule_id"]
                ),
                ANALYST_ORIGIN,
            ),
            201,
        )
        agreement_id = walk["w_note"]["id"]
        walk["agreement_id"] = agreement_id
        walk["r_note"] = validate_success(
            api.get_agreement(agreement_id, ANALYST_ORIGIN), 200
        )
        walk["w_policy"] = validate_success(
            api.attach_policy(
                agreement_id,
                factories.financed_policy(
                    ctx["insurer_id"], policy_number="MC-IC-1"
                ),
                ANALYST_ORIGIN,
            ),
            201,
        )
        policy_id = walk["w_policy"]["id"]
        walk["policy_id"] = policy_id
        walk["r_note2"] = validate_success(
            api.get_agreement(agreement_id, ANALYST_ORIGIN), 200
        )
        walk["w_submit"] = validate_success(
            api.submit_agreement(agreement_id, ANALYST_ORIGIN), 200
        )
        validate_success(
            api.create_verification(
                policy_id, factories.confirmed_verification(), ctx["insurer_headers"]
            ),
            201,
        )
        walk["r_policy_half"] = validate_success(
            api.get_policy(policy_id, ANALYST_ORIGIN), 200
        )
        validate_success(
            api.create_verification(
                policy_id, factories.confirmed_verification(), ctx["agent_headers"]
            ),
            201,
        )
        walk["r_policy_full"] = validate_success(
            api.get_policy(policy_id, ANALYST_ORIGIN), 200
        )
        walk["r_note3"] = validate_success(
            api.get_agreement(agreement_id, ANALYST_ORIGIN), 200
        )
        walk["w_activate"] = validate_success(
            api.activate_agreement(agreement_id, ANALYST_ORIGIN), 200
        )
        walk["r_schedule"] = validate_paginated(
            api.list_installments(agreement_id, ANALYST_ORIGIN, {"limit": 50})
        )
        walk["w_payment"] = validate_success(
            api.create_payment(
                agreement_id, factories.payment(89941, "2026-08-15"), ANALYST_ORIGIN
            ),
            201,
        )
        walk["r_note4"] = validate_success(
            api.get_agreement(agreement_id, ANALYST_ORIGIN), 200
        )
        walk["r_paid"] = validate_paginated(
            api.list_installments(
                agreement_id, ANALYST_ORIGIN, {"status": "PAID", "limit": 50}
            )
        )
        walk["r_payments"] = validate_paginated(
            api.list_payments(agreement_id, ANALYST_ORIGIN, {"limit": 50})
        )
        walk["r_quote"] = validate_success(
            api.get_payoff_quote(agreement_id, ANALYST_ORIGIN), 200
        )
        return walk

    def test_the_create_response_is_already_the_full_row(self, api):
        """The write returns the representation, not an acknowledgement stub, and the
        read that follows agrees field for field.

        The PRD states: "Unless otherwise noted, operations that create or modify a
        resource will return the created or updated resource object in the data
        field." and "The new note is stamped `DRAFT` in its financing `status` and
        `CURRENT` in its `delinquency_stage`".

        Design: Corner/consistency_model/immediate_consistency_every_derived_field_is_correct_in_the_causing_response
        """
        walk = self._walk(api)
        written, read = walk["w_note"], walk["r_note"]

        assert written["status"] == "DRAFT"
        assert written["delinquency_stage"] == "CURRENT"
        assert written["policy_count"] == 0
        for field in ("id", "status", "delinquency_stage", "policy_count", "version"):
            assert read[field] == written[field], (
                f"the immediate read disagrees with the create response on {field}"
            )

    def test_a_cross_entity_counter_moves_inside_the_same_request(self, api):
        """Attaching a policy writes the policy and the note's counter at once.

        The PRD states: "A successful attachment stamps the policy
        `PENDING_VERIFICATION`, sets `carried_over` to false, provisionally sets
        `financed_premium_cents` equal to `gross_premium_cents`, increments the
        agreement's `policy_count` and advances the agreement's `version`."

        Design: Corner/consistency_model/immediate_consistency_every_derived_field_is_correct_in_the_causing_response
        """
        walk = self._walk(api)

        assert walk["w_policy"]["status"] == "PENDING_VERIFICATION"
        assert walk["w_policy"]["financed_premium_cents"] == 600000
        assert walk["w_policy"]["carried_over"] is False
        assert walk["r_note2"]["policy_count"] == 1, (
            "policy_count is not a nightly rollup"
        )
        assert walk["r_note2"]["version"] == walk["w_note"]["version"] + 1

    def test_the_submit_response_itself_carries_the_recomputed_quote(self, api):
        """No follow-up read is needed to learn what the note now costs.

        The PRD states: "A successful submission runs the pricing engine in its
        **provisional** variant, stamps `quote_basis` as `PROVISIONAL`, increments the
        regime's `active_agreement_count` by 1 and advances the note's `version`."

        Design: Corner/consistency_model/immediate_consistency_every_derived_field_is_correct_in_the_causing_response
        """
        walk = self._walk(api)
        submitted = walk["w_submit"]

        assert submitted["status"] == "PENDING_VERIFICATION"
        assert submitted["quote_basis"] == "PROVISIONAL"
        assert submitted["total_premium_cents"] == 600000
        assert submitted["amount_financed_cents"] == 502000
        assert submitted["effective_annual_rate_bps"] == 1500
        assert submitted["finance_charge_cents"] == 37650
        assert submitted["total_of_payments_cents"] == 539650

    def test_a_half_attested_policy_reads_as_half_attested(self, api):
        """One voice on file is one voice on file — the platform does not guess the
        second.

        The PRD states: "Nothing happens to the policy while only one side has spoken;
        the policy stays `PENDING_VERIFICATION` until both parties hold a
        non-superseded record." and "In that case the agreed figures are stamped as
        `verified_premium_cents` and `verified_effective_date`,
        `financed_premium_cents` is recomputed as `verified_premium_cents` plus
        `endorsed_premium_cents`, the agreement's `verified_policy_count` increases by
        1, and the policy's `version` advances."

        Design: Corner/consistency_model/immediate_consistency_every_derived_field_is_correct_in_the_causing_response
        """
        walk = self._walk(api)

        assert walk["r_policy_half"]["status"] == "PENDING_VERIFICATION"
        assert walk["r_policy_half"]["verified_premium_cents"] is None
        assert walk["r_policy_full"]["status"] == "VERIFIED"
        assert walk["r_policy_full"]["verified_premium_cents"] == 600000
        assert walk["r_policy_full"]["verified_effective_date"] == "2026-09-01"
        assert walk["r_policy_full"]["financed_premium_cents"] == 600000
        assert walk["r_note3"]["verified_policy_count"] == 1
        assert walk["r_note3"]["policy_count"] == 1

    def test_activation_is_complete_when_it_returns(self, api):
        """The receivable and its whole schedule exist by the time the caller reads
        the response.

        The PRD states: "The note's `principal_balance_cents` is set to
        `amount_financed_cents`, its `unpaid_finance_charge_cents` to
        `finance_charge_cents`, its `activated_at` to the current logical-clock
        instant, its financing status to `ACTIVE`, and its `version` advances."

        Design: Corner/consistency_model/immediate_consistency_every_derived_field_is_correct_in_the_causing_response
        """
        walk = self._walk(api)
        activated = walk["w_activate"]
        rows, meta = walk["r_schedule"]

        assert activated["status"] == "ACTIVE"
        assert activated["quote_basis"] == "FINAL"
        assert activated["principal_balance_cents"] == 502000
        assert activated["unpaid_finance_charge_cents"] == 37650
        assert activated["activated_at"] == "2026-08-15T00:00:00.000Z"
        assert is_iso8601_timestamp(activated["activated_at"])

        assert meta["total_count"] == 6, "the schedule is queryable at once"
        first = min(rows, key=lambda row: row["installment_number"])
        assert first["amount_cents"] == level_installment_amounts(539650, 6)[0] == 89941
        assert first["status"] == "SCHEDULED"
        assert first["paid_cents"] == 0

    def test_the_payment_response_carries_its_own_allocation(self, api):
        """The posting reports the four buckets it just ran rather than deferring
        them.

        The PRD states: "and `applied_late_fee_cents`, `applied_finance_charge_cents`
        and `applied_principal_cents` record the three totals." and "the payment runs
        as the `PAYOFF` variant when the tendered `amount_cents` is greater than or
        equal to the net payoff computed as of `received_date`, and as the `STANDARD`
        variant otherwise."

        Design: Corner/consistency_model/immediate_consistency_every_derived_field_is_correct_in_the_causing_response
        """
        walk = self._walk(api)
        posted = walk["w_payment"]

        assert posted["status"] == "POSTED"
        assert posted["allocation_variant"] == "STANDARD", (
            "89941 is far below the net payoff of this note"
        )
        assert posted["applied_late_fee_cents"] == 0
        assert posted["applied_finance_charge_cents"] == 6275
        assert posted["applied_principal_cents"] == 83666
        assert posted["applied_unapplied_cents"] == 0
        assert posted["rebate_applied_cents"] == 0
        assert (
            posted["applied_finance_charge_cents"]
            + posted["applied_principal_cents"]
            == 89941
        )

    def test_every_consequence_of_that_payment_is_already_visible(self, api):
        """Balances, the installment's status and the list that must count the new
        row are all correct on the very next read.

        The PRD states: "the note's `principal_balance_cents`,
        `unpaid_finance_charge_cents` and `late_fee_balance_cents` are decremented by
        exactly the amounts absorbed in buckets one to three" and "an installment
        whose `paid_cents` reaches its `amount_cents` moves to `PAID`".

        Design: Corner/consistency_model/immediate_consistency_every_derived_field_is_correct_in_the_causing_response
        """
        walk = self._walk(api)

        assert walk["r_note4"]["principal_balance_cents"] == 502000 - 83666 == 418334
        assert walk["r_note4"]["unpaid_finance_charge_cents"] == 37650 - 6275 == 31375
        assert walk["r_note4"]["late_fee_balance_cents"] == 0

        paid_rows, paid_meta = walk["r_paid"]
        assert paid_meta["total_count"] == 1
        assert paid_rows[0]["status"] == "PAID"
        assert paid_rows[0]["installment_number"] == 1
        assert paid_rows[0]["paid_cents"] == 89941

        pay_rows, pay_meta = walk["r_payments"]
        assert pay_meta["total_count"] == 1
        assert pay_rows[0]["id"] == walk["w_payment"]["id"], (
            "the list already carries the id the POST returned"
        )

    def test_even_the_recomputed_derived_read_follows_immediately(self, api):
        """The payoff quote is computed from state the previous request wrote, so it
        must move in the same instant.

        The PRD states: "Let *r* be the number of installments not yet retired:
        `installment_count` minus the count of the note's installments whose `status`
        is `PAID`." and "The net payoff is then `principal_balance_cents` plus
        `unpaid_finance_charge_cents`, minus the rebate, plus `late_fee_balance_cents`,
        minus `unapplied_credit_cents`."

        Design: Corner/consistency_model/immediate_consistency_every_derived_field_is_correct_in_the_causing_response
        """
        walk = self._walk(api)
        quote = walk["r_quote"]

        assert quote["as_of_date"] == "2026-08-15"
        assert quote["rebate_method"] == "RULE_OF_78"
        assert quote["gross_balance_cents"] == 418334 + 31375 == 449709
        assert quote["unearned_finance_charge_rebate_cents"] == (
            rule_of_78_rebate_cents(37650, 5, 6)
        ) == 26893, "r is 5 once exactly one installment has reached PAID"
        assert quote["outstanding_late_fee_cents"] == 0
        assert quote["unapplied_credit_cents"] == 0
        assert quote["net_payoff_cents"] == 418334 + 31375 - 26893 == 422816
