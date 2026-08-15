"""Prize pool distribution, payout record lifecycle, withholding, and OCC."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    adjudicate_dispute,
    advance_tournament,
    api_client,
    approve_payout,
    assert_logical_clock_instant,
    ban_player_with_strikes,
    compute_payout_records,
    create_dispute,
    create_integrity_case,
    create_sponsor_deal,
    get_integrity_case,
    get_payout_record,
    get_player,
    get_registration,
    get_tournament_version,
    list_payout_records,
    make_payout_officer_headers,
    make_player_headers,
    pay_payout,
    play_match_to_completed,
    record_for_registration,
    resolve_case,
    setup_completed_2team,
    setup_completed_4team,
    setup_in_progress_2team,
    submit_payout_docs,
    transition_sponsor_deal,
    activate_sponsor_deal,
    validate_error,
    verify_payout_docs,
)

PAYOUT = TEST_USERS["payout_officer_headers"]
TD = TEST_USERS["tournament_director_headers"]


def _records_by_reg(tournament_id):
    return list_payout_records(tournament_id)


class TestProvisionalVsFinal:

    def test_prize_provisional_vs_final_amounts_after_dq(self):
        """PRD §3.7: "The `PROVISIONAL` variant ignores integrity cases
        entirely — accused players are treated as cleared — and produces
        records with `compute_run_mode` `PROVISIONAL` that cannot be approved
        (approval is rejected with `ERR_PAYOUT_NOT_FINAL`)."
        PRD §3.7: "Step 4 applies only to the `FINAL` variant: if any placed
        registration was excluded because it is `FORFEITED`, its base
        percentage is redistributed to the remaining placed registrations in
        proportion to their own base percentages."
        PRD §3.7: "Step 5b is the residual sweep: after the last record, any
        positive remaining pool (unallocated percentage, as happens in a
        2-team bracket where shares sum to 75%) is added to the placement-1
        record's exact gross before rounding"
        PRD §3.7: "The supersede rule voids every prior payout record of the
        tournament whose `disbursement_status` is `COMPUTED` before the new
        records persist; voided records carry `disbursement_status` `VOID`."

        Design: Difficulty/dual_variant_calc/prize_provisional_vs_final_after_dq
        """
        ctx = setup_completed_2team("DualVar Cup",
                                    prize_pool_target_cents=1000000)
        tournament_id = ctx["tournament"]["id"]
        r1, r2 = ctx["registrations"]
        p2 = ctx["players"][1]

        provisional = compute_payout_records(tournament_id, "PROVISIONAL")
        prov_r1 = record_for_registration(provisional, r1["id"])
        prov_r2 = record_for_registration(provisional, r2["id"])
        assert prov_r1["gross_amount_cents"] == 750000, \
            "50% share 500000 plus the 250000 residual sweep"
        assert prov_r2["gross_amount_cents"] == 250000
        assert prov_r1["compute_run_mode"] == "PROVISIONAL"

        # The runner-up's player accumulates three strikes and is banned;
        # the DQ cascade forfeits the runner-up registration.
        ban_player_with_strikes(p2["id"], 3)
        assert get_player(p2["id"])["eligibility_status"] == "BANNED"
        assert get_registration(r2["id"])["status"] == "FORFEITED"

        final = compute_payout_records(tournament_id, "FINAL")
        assert len(final) == 1, "the FORFEITED runner-up is excluded"
        fin_r1 = final[0]
        assert fin_r1["registration_id"] == r1["id"]
        assert fin_r1["gross_amount_cents"] == 1000000, \
            "the runner-up's 25% redistributes pro-rata and the residual sweeps"
        assert fin_r1["compute_run_mode"] == "FINAL"

        assert get_payout_record(prov_r1["id"])["disbursement_status"] == "VOID"
        assert get_payout_record(prov_r2["id"])["disbursement_status"] == "VOID"

    def test_prize_provisional_then_final_identical_without_dq(self):
        """PRD §3.7: "Step 2 selects the eligible set: registrations of the
        tournament whose `placement` is in {1, 2, 3} and whose status is not
        `FORFEITED`; placements greater than 3 pay zero."
        PRD §3.7: "Step 4 applies only to the `FINAL` variant: if any placed
        registration was excluded because it is `FORFEITED`, its base
        percentage is redistributed to the remaining placed registrations in
        proportion to their own base percentages."
        PRD §3.7: "The supersede rule voids every prior payout record of the
        tournament whose `disbursement_status` is `COMPUTED` before the new
        records persist; voided records carry `disbursement_status` `VOID`."

        Design: Difficulty/dual_variant_calc/prize_provisional_vs_final_after_dq
        """
        ctx = setup_completed_2team("DualVar2 Cup",
                                    prize_pool_target_cents=1000000)
        tournament_id = ctx["tournament"]["id"]
        r1, r2 = ctx["registrations"]

        provisional = compute_payout_records(tournament_id, "PROVISIONAL")
        final = compute_payout_records(tournament_id, "FINAL")
        fin_r1 = record_for_registration(final, r1["id"])
        fin_r2 = record_for_registration(final, r2["id"])
        # With no open cases and no FORFEITED registrations the two variants
        # see identical inputs and must produce identical gross amounts.
        assert fin_r1["gross_amount_cents"] == 750000
        assert fin_r2["gross_amount_cents"] == 250000
        assert fin_r1["compute_run_mode"] == "FINAL"

        for prov in provisional:
            assert get_payout_record(prov["id"])[
                "disbursement_status"] == "VOID", \
                "the FINAL run supersedes and voids the PROVISIONAL records"


class TestWaterfallAndRounding:

    def test_prize_waterfall_floor_binds_runner_up(self):
        """PRD §3.7: "Step 3 sets the base percentage per placement: 50% for
        first place, 25% for second place, 12.5% for third place; each tied
        third-place team receives its own 12.5%."
        PRD §3.7: "Each record's exact gross is the smaller of two values:
        the larger of 100000 cents (the minimum placement payout) or the pool
        total multiplied by the record's percentage divided by 100, on one
        hand; and the remaining pool on the other. The remaining pool starts
        at the pool total and decrements by each record's exact gross."

        Design: Difficulty/combinatorial_formula/prize_waterfall_floor_binding
        """
        ctx = setup_completed_4team("Floor Cup",
                                    prize_pool_target_cents=250000)
        tournament_id = ctx["tournament"]["id"]
        r1, r2, r3, r4 = ctx["registrations"]

        records = compute_payout_records(tournament_id, "FINAL")
        assert len(records) == 4
        assert record_for_registration(records, r1["id"])[
            "gross_amount_cents"] == 125000, "50% of 250000, above the floor"
        assert record_for_registration(records, r2["id"])[
            "gross_amount_cents"] == 100000, \
            "raw 25% share 62500 is floored up to the 100000-cent minimum"
        assert record_for_registration(records, r3["id"])[
            "gross_amount_cents"] == 25000, \
            "the remaining pool binds for the first third-place team"
        assert record_for_registration(records, r4["id"])[
            "gross_amount_cents"] == 0, "the pool is exhausted"
        total = sum(r["gross_amount_cents"] for r in records)
        assert total == 250000, "the waterfall conserves the pool"

    def test_prize_waterfall_placements_and_third_place_order(self):
        """PRD §3.6: "The champion, defined as the winner of the final match,
        takes placement 1. A registration eliminated in a match at bracket
        round `r` takes placement equal to 2 raised to the power (`R` minus
        `r`), plus 1"
        PRD §3.7: "Placements are processed in ascending order — first place,
        then second place, then third places ordered by the registration's
        `created_at` ascending, with a final fallback on `seed_position`
        ascending."

        Design: Difficulty/combinatorial_formula/prize_waterfall_floor_binding
        """
        ctx = setup_completed_4team("FloorOrder Cup",
                                    prize_pool_target_cents=250000)
        tournament_id = ctx["tournament"]["id"]
        r1, r2, r3, r4 = ctx["registrations"]
        for reg, expected in ((r1, 1), (r2, 2), (r3, 3), (r4, 3)):
            assert get_registration(reg["id"])["placement"] == expected

        records = compute_payout_records(tournament_id, "FINAL")
        # The third-place tie processes the earlier-seeded (and
        # earlier-created) registration first: r3 takes the remaining 25000
        # and r4 is starved to 0.
        assert record_for_registration(records, r3["id"])[
            "gross_amount_cents"] == 25000
        assert record_for_registration(records, r4["id"])[
            "gross_amount_cents"] == 0
        placements = [r["placement"] for r in records]
        assert placements == sorted(placements), \
            "records come back ordered by placement ascending"

    def test_prize_rounding_delta_lands_on_earliest_created(self):
        """PRD §3.7: "each record's exact gross is rounded half-up to integer
        cents first, then the rounded values are summed; the delta — pool
        total minus the sum of rounded grosses, which may be negative — is
        added to the record with the lowest placement number (placement
        ascending, then the registration's `created_at` ascending, with a
        final fallback on `seed_position` ascending; never `id`)."
        PRD §3.7: "Step 4 applies only to the `FINAL` variant: if any placed
        registration was excluded because it is `FORFEITED`, its base
        percentage is redistributed to the remaining placed registrations in
        proportion to their own base percentages."

        Design: Difficulty/combinatorial_formula/prize_rounding_delta_tiebreak
        """
        ctx = setup_completed_4team("Rounding Cup",
                                    prize_pool_target_cents=999999)
        tournament_id = ctx["tournament"]["id"]
        r1, r2, r3, r4 = ctx["registrations"]
        p1, p2 = ctx["players"][0], ctx["players"][1]
        ban_player_with_strikes(p1["id"], 3)
        ban_player_with_strikes(p2["id"], 3)
        assert get_registration(r1["id"])["status"] == "FORFEITED"
        assert get_registration(r2["id"])["status"] == "FORFEITED"

        records = compute_payout_records(tournament_id, "FINAL")
        assert len(records) == 2, "the FORFEITED champion and runner-up are excluded"
        # Each tied third-place team carries an effective 50% after pro-rata
        # redistribution: exact 499999.5 each; per-record round-half-up gives
        # 500000 each; the negative reconciliation delta lands on the
        # earlier-created (and earlier-seeded) tied record r3.
        assert record_for_registration(records, r3["id"])[
            "gross_amount_cents"] == 499999
        assert record_for_registration(records, r4["id"])[
            "gross_amount_cents"] == 500000
        assert sum(r["gross_amount_cents"] for r in records) == 999999

    def test_prize_forfeited_registrations_receive_no_records(self):
        """PRD §3.7: "Step 2 selects the eligible set: registrations of the
        tournament whose `placement` is in {1, 2, 3} and whose status is not
        `FORFEITED`; placements greater than 3 pay zero."
        PRD §3.6: "Registrations whose status is `FORFEITED` keep `placement`
        null and receive no payout record in either compute mode."

        Design: Difficulty/combinatorial_formula/prize_rounding_delta_tiebreak
        """
        ctx = setup_completed_4team("Exclude Cup",
                                    prize_pool_target_cents=999999)
        tournament_id = ctx["tournament"]["id"]
        r1, r2, r3, r4 = ctx["registrations"]
        ban_player_with_strikes(ctx["players"][0]["id"], 3)
        ban_player_with_strikes(ctx["players"][1]["id"], 3)

        records = compute_payout_records(tournament_id, "FINAL")
        registration_ids = {r["registration_id"] for r in records}
        assert len(records) == 2
        assert r1["id"] not in registration_ids
        assert r2["id"] not in registration_ids
        assert registration_ids == {r3["id"], r4["id"]}
        for record in records:
            assert record["placement"] == 3
            assert record["compute_run_mode"] == "FINAL"
            assert record["payee_player_id"] in {
                ctx["players"][2]["id"], ctx["players"][3]["id"]}


class TestPayoutRecordLifecycle:

    def test_doc_cycle_independent_of_disbursement(self):
        """PRD §3.8: "The documentation dimension flows `PENDING → SUBMITTED
        → VERIFIED` or `PENDING → SUBMITTED → REJECTED`, with `REJECTED →
        SUBMITTED` as a resubmission cycle. The dimensions evolve
        independently except where approval gates on documentation."
        PRD §3.8: "A verified `W9` withholds 0%."
        PRD §3.8: "Payment moves `APPROVED → PAID`, sets `paid_at` to the
        logical clock, and is performed by a `PayoutOfficer` with no further
        preconditions."

        Design: Difficulty/non_linear_state_machine/payout_parallel_doc_and_disbursement_dimensions
        """
        ctx = setup_completed_2team("Parallel Cup",
                                    prize_pool_target_cents=1000000)
        tournament_id = ctx["tournament"]["id"]
        r1 = ctx["registrations"][0]
        p1 = ctx["players"][0]
        records = compute_payout_records(tournament_id, "FINAL")
        pr1 = record_for_registration(records, r1["id"])
        assert pr1["gross_amount_cents"] == 750000

        submitted = submit_payout_docs(pr1["id"], p1["id"], "W9")
        assert submitted["doc_status"] == "SUBMITTED"
        assert submitted["disbursement_status"] == "COMPUTED"

        rejected = verify_payout_docs(pr1["id"], "REJECT", "po-1")
        assert rejected["doc_status"] == "REJECTED"
        assert rejected["disbursement_status"] == "COMPUTED", \
            "the doc dimension evolves independently of disbursement"

        resubmitted = submit_payout_docs(pr1["id"], p1["id"], "W9")
        assert resubmitted["doc_status"] == "SUBMITTED", \
            "REJECTED -> SUBMITTED resubmission cycle"
        verified = verify_payout_docs(pr1["id"], "VERIFY", "po-1")
        assert verified["doc_status"] == "VERIFIED"
        assert verified["doc_verified_by_user_id"] == "po-1"
        assert verified["disbursement_status"] == "COMPUTED"

        approved = approve_payout(pr1["id"], "po-2")
        assert approved["disbursement_status"] == "APPROVED"
        assert approved["withholding_cents"] == 0, "verified W9 withholds 0%"
        assert approved["net_amount_cents"] == 750000
        assert approved["doc_status"] == "VERIFIED"
        assert approved["approved_by_user_id"] == "po-2"

        paid = pay_payout(pr1["id"], "po-1")
        assert paid["disbursement_status"] == "PAID"
        assert_logical_clock_instant(paid["paid_at"], "2026-08-10T00:00:00Z")

    def test_docs_immutable_after_approval(self):
        """PRD §3.8: "Documents cannot change after approval — the record's
        `disbursement_status` must be `COMPUTED` at submit time, else
        `ERR_INVALID_PAYOUT_STATUS`."

        Design: Difficulty/non_linear_state_machine/payout_parallel_doc_and_disbursement_dimensions
        """
        ctx = setup_completed_2team("Immutable Cup",
                                    prize_pool_target_cents=1000000)
        tournament_id = ctx["tournament"]["id"]
        r1 = ctx["registrations"][0]
        p1 = ctx["players"][0]
        records = compute_payout_records(tournament_id, "FINAL")
        pr1 = record_for_registration(records, r1["id"])
        submit_payout_docs(pr1["id"], p1["id"], "W9")
        verify_payout_docs(pr1["id"], "VERIFY", "po-1")
        approve_payout(pr1["id"], "po-2")

        resp = api_client.submit_payout_docs(
            pr1["id"], {"doc_type": "W8BEN"}, make_player_headers(p1["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_PAYOUT_STATUS)
        after = get_payout_record(pr1["id"])
        assert after["disbursement_status"] == "APPROVED"
        assert after["doc_status"] == "VERIFIED"
        assert after["doc_type"] == "W9"


class TestRecomputeConservation:

    def test_pool_conserved_across_provisional_final_supersede(self):
        """PRD §3.7: "The supersede rule voids every prior payout record of
        the tournament whose `disbursement_status` is `COMPUTED` before the
        new records persist; voided records carry `disbursement_status`
        `VOID`."
        PRD §3.7: "Step 5b is the residual sweep: after the last record, any
        positive remaining pool (unallocated percentage, as happens in a
        2-team bracket where shares sum to 75%) is added to the placement-1
        record's exact gross before rounding"

        Design: Difficulty/compensating_invariant/prize_pool_conserved_across_recompute
        """
        ctx = setup_completed_2team("Conserve Cup",
                                    prize_pool_target_cents=1000000)
        tournament_id = ctx["tournament"]["id"]
        r1, r2 = ctx["registrations"]

        provisional = compute_payout_records(tournament_id, "PROVISIONAL")
        prov_total = sum(r["gross_amount_cents"] for r in provisional)
        assert prov_total == 1000000, \
            "750000 + 250000 conserves the funded pool"

        final = compute_payout_records(tournament_id, "FINAL")
        for prov in provisional:
            assert get_payout_record(prov["id"])[
                "disbursement_status"] == "VOID"

        fin_total = sum(r["gross_amount_cents"] for r in final)
        assert fin_total == 1000000, \
            "the pool is exactly conserved across compute + supersede"
        assert record_for_registration(final, r1["id"])[
            "gross_amount_cents"] == 750000
        assert record_for_registration(final, r2["id"])[
            "gross_amount_cents"] == 250000

        all_records = _records_by_reg(tournament_id)
        assert len(all_records) == 4, \
            "2 VOID PROVISIONAL + 2 COMPUTED FINAL records"

    def test_new_records_carry_fresh_fields_after_supersede(self):
        """PRD §3.7: "Every record created carries the requesting
        `compute_run_mode`, the tournament's `bracket_version` at compute
        time, the computed `gross_amount_cents`, `withholding_cents` zero,
        `net_amount_cents` equal to `gross_amount_cents` (finalized at
        approve), `payee_is_minor` copied from the payee roster slot's
        `is_minor` at compute time, `doc_status` `PENDING`, and
        `disbursement_status` `COMPUTED`."

        Design: Difficulty/compensating_invariant/prize_pool_conserved_across_recompute
        """
        ctx = setup_completed_2team("FreshFields Cup",
                                    prize_pool_target_cents=1000000)
        tournament_id = ctx["tournament"]["id"]
        bracket_version = ctx["tournament"]["bracket_version"]

        provisional = compute_payout_records(tournament_id, "PROVISIONAL")
        final = compute_payout_records(tournament_id, "FINAL")

        for record in final:
            assert record["compute_run_mode"] == "FINAL"
            assert record["bracket_version"] == bracket_version
            assert record["withholding_cents"] == 0
            assert record["net_amount_cents"] == record["gross_amount_cents"]
            assert record["doc_status"] == "PENDING"
            assert record["disbursement_status"] == "COMPUTED"
            assert record["payee_is_minor"] is False

        voided = [get_payout_record(r["id"]) for r in provisional]
        assert {r["gross_amount_cents"] for r in voided} == {750000, 250000}, \
            "voided records retain their original gross amounts"
        assert all(r["disbursement_status"] == "VOID" for r in voided)


class TestFinalComputeIntegrityGate:

    def test_final_compute_blocked_provisional_allowed(self):
        """PRD §3.7: "The `FINAL` variant requires that no integrity case in
        `OPEN` or `INVESTIGATING` exists for any player on any eligible
        registration; if such a case exists the compute is rejected with
        `ERR_INTEGRITY_CASES_PENDING`."
        PRD §3.7: "The `PROVISIONAL` variant ignores integrity cases entirely
        — accused players are treated as cleared"

        Design: Difficulty/cross_entity_state_dependency/final_compute_blocked_by_open_integrity_case
        """
        ctx = setup_completed_2team("Gate Cup",
                                    prize_pool_target_cents=1000000)
        tournament_id = ctx["tournament"]["id"]
        r1 = ctx["registrations"][0]
        p1 = ctx["players"][0]
        case = create_integrity_case(
            p1["id"], "suspicious flick, finals round 12")

        version = get_tournament_version(tournament_id)
        resp = api_client.compute_payout_records(
            tournament_id, {"mode": "FINAL",
                            "expected_tournament_version": version}, PAYOUT)
        validate_error(resp, ApiErrorId.ERR_INTEGRITY_CASES_PENDING)

        provisional = compute_payout_records(tournament_id, "PROVISIONAL",
                                             expected_version=version)
        prov_r1 = record_for_registration(provisional, r1["id"])
        assert prov_r1["compute_run_mode"] == "PROVISIONAL"
        assert prov_r1["gross_amount_cents"] == 750000
        assert get_integrity_case(case["id"])["status"] == "OPEN", \
            "the rejected FINAL compute caused no state change"

    def test_final_compute_allowed_after_case_cleared(self):
        """PRD §3.7: "The `FINAL` variant requires that no integrity case in
        `OPEN` or `INVESTIGATING` exists for any player on any eligible
        registration; if such a case exists the compute is rejected with
        `ERR_INTEGRITY_CASES_PENDING`."
        PRD §3.9: "A `CLEARED` outcome records `resolved_by_user_id` and
        `resolved_at` and moves the case to `RESOLVED_CLEARED`."

        Design: Difficulty/cross_entity_state_dependency/final_compute_blocked_by_open_integrity_case
        """
        ctx = setup_completed_2team("Gate2 Cup",
                                    prize_pool_target_cents=1000000)
        tournament_id = ctx["tournament"]["id"]
        r1, r2 = ctx["registrations"]
        p1 = ctx["players"][0]
        case = create_integrity_case(p1["id"], "suspicious flick")

        resp = api_client.compute_payout_records(
            tournament_id,
            {"mode": "FINAL",
             "expected_tournament_version":
             get_tournament_version(tournament_id)},
            PAYOUT)
        validate_error(resp, ApiErrorId.ERR_INTEGRITY_CASES_PENDING)

        resolve_case(case["id"], {"action": "BEGIN_INVESTIGATION"})
        cleared = resolve_case(case["id"],
                               {"action": "RESOLVE", "outcome": "CLEARED"})
        assert cleared["status"] == "RESOLVED_CLEARED"

        records = compute_payout_records(tournament_id, "FINAL")
        assert len(records) == 2
        assert record_for_registration(records, r1["id"])[
            "gross_amount_cents"] == 750000
        assert record_for_registration(records, r2["id"])[
            "gross_amount_cents"] == 250000


class TestWithholding:

    def test_withholding_backup_rate_sub_threshold(self):
        """PRD §3.8: "A record with no verified document, which is reachable
        only when gross is below 60000 cents and the payee is not a minor,
        withholds 24%."
        PRD §3.8: "The `withholding_cents` is the gross multiplied by the
        applicable rate divided by 100, rounded half-up to integer cents;
        `net_amount_cents` is the gross minus the withholding."

        Design: Corner/calculations/withholding_backup_rate_sub_threshold
        """
        ctx = setup_completed_2team("Backup Cup",
                                    prize_pool_target_cents=110000)
        tournament_id = ctx["tournament"]["id"]
        r2 = ctx["registrations"][1]
        records = compute_payout_records(tournament_id, "FINAL")
        pr2 = record_for_registration(records, r2["id"])
        assert pr2["gross_amount_cents"] == 10000, \
            "the champion floor-binds at 100000, leaving 10000"
        assert pr2["doc_status"] == "PENDING"

        approved = approve_payout(pr2["id"], "po-1")
        assert approved["disbursement_status"] == "APPROVED", \
            "gross 10000 is below the 60000-cent doc threshold"
        assert approved["withholding_cents"] == 2400, "24% backup rate"
        assert approved["net_amount_cents"] == 7600

    def test_withholding_w8ben_thirty_percent(self):
        """PRD §3.8: "A verified `W8BEN` withholds 30%."
        PRD §3.8: "when `gross_amount_cents` is at least 60000 cents
        (inclusive, so exactly 60000 requires it), `doc_status` must be
        `VERIFIED`, else `ERR_TAX_DOCS_REQUIRED`."

        Design: Corner/calculations/withholding_w8ben_thirty_percent
        """
        ctx = setup_completed_2team("Foreign Cup",
                                    prize_pool_target_cents=200000)
        tournament_id = ctx["tournament"]["id"]
        r1 = ctx["registrations"][0]
        p1 = ctx["players"][0]
        records = compute_payout_records(tournament_id, "FINAL")
        pr1 = record_for_registration(records, r1["id"])
        assert pr1["gross_amount_cents"] == 100000

        submit_payout_docs(pr1["id"], p1["id"], "W8BEN")
        verify_payout_docs(pr1["id"], "VERIFY", "po-1")
        approved = approve_payout(pr1["id"], "po-2")
        assert approved["withholding_cents"] == 30000
        assert approved["net_amount_cents"] == 70000
        assert approved["doc_verified_by_user_id"] == "po-1"
        assert approved["approved_by_user_id"] == "po-2"

    def test_sod_verifier_cannot_approve_own_docs(self):
        """PRD §2.10: "A payout record cannot be approved by the officer
        whose `X-User-ID` was recorded as `doc_verified_by_user_id` on the
        same record (the check applies only when `doc_verified_by_user_id` is
        non-null)."
        PRD §2.10: "Violations are rejected with `ERR_SEGREGATION_OF_DUTIES`
        (HTTP 422)."

        Design: Corner/rbac/sod_verifier_cannot_approve_own_docs
        """
        ctx = setup_completed_2team("SoD2 Cup",
                                    prize_pool_target_cents=200000)
        tournament_id = ctx["tournament"]["id"]
        r1 = ctx["registrations"][0]
        p1 = ctx["players"][0]
        records = compute_payout_records(tournament_id, "FINAL")
        pr1 = record_for_registration(records, r1["id"])
        submit_payout_docs(pr1["id"], p1["id"], "W9")
        verify_payout_docs(pr1["id"], "VERIFY", "po-1")

        resp = api_client.approve_payout(
            pr1["id"], make_payout_officer_headers("po-1"))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

        approved = approve_payout(pr1["id"], "po-2")
        assert approved["disbursement_status"] == "APPROVED"
        assert approved["approved_by_user_id"] == "po-2"
        assert approved["doc_verified_by_user_id"] == "po-1"


class TestMinorPayout:

    def test_minor_payout_requires_guardian_docs(self):
        """PRD §3.8: "A minor payee must submit with `doc_type`
        `GUARDIAN_W9` and both guardian fields present; violation is rejected
        with `ERR_VALIDATION`."
        PRD §3.8: "when `payee_is_minor` is true, `doc_status` must be
        `VERIFIED` and `doc_type` must be `GUARDIAN_W9`, else
        `ERR_GUARDIAN_DOCS_REQUIRED`."
        PRD §3.8: "A verified `GUARDIAN_W9` withholds 0%."
        PRD §3.7: "`payee_is_minor` copied from the payee roster slot's
        `is_minor` at compute time"

        Design: Corner/validations/minor_payout_requires_guardian_docs
        """
        specs = [
            {"handle": "p1", "dob": "2010-06-15", "team_name": "Alpha",
             "rank": 100},
            {"handle": "p2", "dob": "2000-02-02", "team_name": "Beta",
             "rank": 80},
        ]
        ctx = setup_completed_2team("Minor Cup",
                                    prize_pool_target_cents=200000,
                                    team_specs=specs)
        tournament_id = ctx["tournament"]["id"]
        r1 = ctx["registrations"][0]
        p1 = ctx["players"][0]
        records = compute_payout_records(tournament_id, "FINAL")
        pr1 = record_for_registration(records, r1["id"])
        assert pr1["payee_is_minor"] is True
        assert pr1["gross_amount_cents"] == 100000

        resp = api_client.submit_payout_docs(
            pr1["id"], {"doc_type": "W9"}, make_player_headers(p1["id"]))
        validate_error(resp, ApiErrorId.ERR_VALIDATION)

        submitted = submit_payout_docs(
            pr1["id"], p1["id"], "GUARDIAN_W9", guardian_name="Pat Parent",
            guardian_email="pat@x.gg")
        assert submitted["doc_status"] == "SUBMITTED"
        verify_payout_docs(pr1["id"], "VERIFY", "po-1")
        approved = approve_payout(pr1["id"], "po-2")
        assert approved["disbursement_status"] == "APPROVED"
        assert approved["withholding_cents"] == 0, \
            "verified GUARDIAN_W9 withholds 0%"
        assert approved["net_amount_cents"] == 100000


class TestSponsorBonusInPool:

    def test_sponsor_bonus_counted_only_when_activated(self):
        """PRD §3.7: "Step 1 computes the pool total: `funded_pool_cents`
        plus the sponsor bonus, where the sponsor bonus is the sum of
        `bonus_cents` over all sponsor deals of the tournament whose status
        is `ACTIVATED` at compute time."
        PRD §3.11: "Only deals `ACTIVATED` at compute time contribute
        `bonus_cents` to the pool total in the prize-pool waterfall."

        Design: Corner/calculations/sponsor_bonus_counted_only_when_activated
        """
        ctx = setup_completed_2team("Sponsor Pool Cup",
                                    prize_pool_target_cents=1000000)
        tournament_id = ctx["tournament"]["id"]
        r1, r2 = ctx["registrations"]
        sd1 = create_sponsor_deal(tournament_id, "Acme", "sm-1", "TITLE",
                                  200000, ["VOD"])
        sd2 = create_sponsor_deal(tournament_id, "BigCola", "sm-2",
                                  "PRESENTING", 500000, ["CLIPS"])
        transition_sponsor_deal(sd1["id"], "CONTRACT")
        activate_sponsor_deal(sd1["id"], "sm-1")
        transition_sponsor_deal(sd2["id"], "CONTRACT")

        records = compute_payout_records(tournament_id, "FINAL")
        # pool total is 1200000: 1000000 funded + 200000 ACTIVATED bonus;
        # the merely CONTRACTED 500000 deal contributes nothing.
        assert record_for_registration(records, r1["id"])[
            "gross_amount_cents"] == 900000, \
            "50% share 600000 plus the 300000 residual sweep"
        assert record_for_registration(records, r2["id"])[
            "gross_amount_cents"] == 300000, "25% of 1200000"


class TestPayoutErrorChain:

    def test_dispute_payout_and_tax_state_errors_end_to_end(self):
        """PRD §3.5: "`START_REVIEW` moves a `FILED` or `APPEALED` dispute to
        `UNDER_REVIEW`."
        PRD §3.8: "The record's `compute_run_mode` must be `FINAL` — a
        `PROVISIONAL` record is rejected with `ERR_PAYOUT_NOT_FINAL`."
        PRD §3.8: "Payment moves `APPROVED → PAID`"
        PRD §3.8: "when `gross_amount_cents` is at least 60000 cents
        (inclusive, so exactly 60000 requires it), `doc_status` must be
        `VERIFIED`, else `ERR_TAX_DOCS_REQUIRED`."
        PRD §2.7: "requesting a transition from a state that does not permit
        it is rejected with the machine's specific invalid-status error
        (HTTP 409)."

        Design: Corner/errors/dispute_payout_and_tax_state_errors_end_to_end
        """
        ctx = setup_in_progress_2team("ErrChain Cup")
        tournament_id = ctx["tournament"]["id"]
        r1, r2 = ctx["registrations"]
        match_id = ctx["match"]["id"]
        play_match_to_completed(match_id, 13, 7)

        dispute = create_dispute(match_id, r2["id"], "CONDUCT",
                                 "taunting pause abuse")
        adjudicate_dispute(dispute["id"], {"action": "START_REVIEW"})
        resp = api_client.adjudicate_dispute(
            dispute["id"], {"action": "START_REVIEW"}, TD)
        validate_error(resp, ApiErrorId.ERR_INVALID_DISPUTE_STATUS)
        adjudicate_dispute(dispute["id"], {"action": "RULE_UPHELD"})

        advance_tournament(tournament_id, "COMPLETED")
        provisional = compute_payout_records(tournament_id, "PROVISIONAL")
        prv1 = record_for_registration(provisional, r1["id"])

        resp = api_client.approve_payout(prv1["id"], PAYOUT)
        validate_error(resp, ApiErrorId.ERR_PAYOUT_NOT_FINAL)

        resp = api_client.pay_payout(prv1["id"], PAYOUT)
        validate_error(resp, ApiErrorId.ERR_INVALID_PAYOUT_STATUS)

        final = compute_payout_records(tournament_id, "FINAL")
        fin1 = record_for_registration(final, r1["id"])
        assert fin1["gross_amount_cents"] == 100000
        resp = api_client.approve_payout(fin1["id"], PAYOUT)
        validate_error(resp, ApiErrorId.ERR_TAX_DOCS_REQUIRED)

        assert get_payout_record(prv1["id"])["disbursement_status"] == "VOID"
        assert get_payout_record(fin1["id"])["disbursement_status"] == \
            "COMPUTED"


class TestPayoutComputeOCC:

    def test_occ_stale_version_on_payout_compute(self):
        """PRD §2.6: "Two write endpoints are guarded by optimistic
        concurrency control: bracket generation (initial and regeneration)
        and payout computation."
        PRD §2.6: "If the tournament's current `version` has advanced since
        the client last read it — for example because another operator just
        funded the pool or locked the roster — the request is rejected with
        `ERR_STALE_VERSION` (HTTP 412) and no state change occurs."

        Design: Corner/cross_cutting_layers/occ_stale_version_on_payout_compute
        """
        ctx = setup_completed_2team("OCC2 Cup",
                                    prize_pool_target_cents=100000)
        tournament_id = ctx["tournament"]["id"]
        stale_version = get_tournament_version(tournament_id)
        compute_payout_records(tournament_id, "PROVISIONAL",
                               expected_version=stale_version)

        resp = api_client.compute_payout_records(
            tournament_id, {"mode": "FINAL",
                            "expected_tournament_version": stale_version},
            PAYOUT)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

        records = _records_by_reg(tournament_id)
        assert len(records) == 2, "the stale FINAL attempt creates nothing"
        assert all(r["disbursement_status"] == "COMPUTED" for r in records)
        assert all(r["compute_run_mode"] == "PROVISIONAL" for r in records)
