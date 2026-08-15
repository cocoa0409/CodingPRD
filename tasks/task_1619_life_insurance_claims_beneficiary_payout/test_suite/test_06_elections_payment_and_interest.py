"""Settlement elections, payment execution, and statutory delay interest:
election OCC and supersede semantics, the thirty-day election window, the
retained-asset minimum, execute-payment gating and cascades, the interest
grace-day boundary, and the two accrual-basis variants."""
from test_helpers import (
    ApiErrorId,
    approve_claim,
    begin_review,
    create_designation,
    create_policy,
    create_policy_with_statute,
    create_statute,
    execute_payment,
    file_beneficiary_claim,
    file_claim,
    file_claim_with_verified_docs,
    get_beneficiary_claim,
    get_claim,
    list_accounts,
    list_elections,
    review_document,
    set_clock,
    setup_approved_claim,
    setup_election,
    setup_paid_claim_with_raa,
    upload_document,
    validate_beneficiary_claim,
    validate_error,
    validate_success,
)


class TestStatutoryInterestBasisVariants:
    def test_date_of_death_basis_il(self, api, claims_approver_headers):
        """PRD §3.6: "The claim's statute is resolved by its `state_code`, and
        the accrual basis date is chosen by the statute's `interest_basis`: the
        claim's `date_of_death` when the basis is `DATE_OF_DEATH`, or the
        claim's `proof_complete_date` when the basis is `PROOF_OF_LOSS_COMPLETE`
        — if proof is incomplete there is no basis date and accrual cannot
        start."
        PRD §3.6: "The days elapsed are counted from the basis date to the
        as-of date, and the accrual days are the days elapsed beyond the
        statute's `grace_days`, floored at zero: on the day the elapsed count
        exactly equals the grace period, accrual is still zero."
        PRD §3.6: "The interest is then the claim's `face_amount_cents`
        multiplied by the statute's `annual_interest_rate_bp`, divided by ten
        thousand, multiplied by the accrual days, and divided by 365, with the
        result rounded half-up to whole cents."

        IL leg: basis date_of_death 2026-03-01, approve 2026-04-10 -> 40
        elapsed - 30 grace = 10 accrual days; 25000000 x 10% x 10/365 = 68493
        (half-up of 68493.15).

        Design: Difficulty/dual_variant_calc/statutory_interest_basis_date_of_death_vs_proof_complete
        """
        create_statute("IL")
        policy = create_policy(state_code="IL", policy_number="P-IL-1",
                               face_amount_cents=25000000,
                               contestability_months=24)
        claim, _docs = file_claim_with_verified_docs(
            policy["id"], "2026-03-01", filing_clock="2026-03-05T00:00:00Z",
            review_clock="2026-03-11T00:00:00Z")
        set_clock("2026-04-10T00:00:00Z")
        approved = validate_success(api.approve_claim(claim["id"],
                                                      claims_approver_headers))
        assert approved["accrued_interest_cents"] == 68493
        assert approved["total_payable_cents"] == 25068493

    def test_proof_of_loss_basis_diverges_ny(self, api, claims_approver_headers):
        """PRD §3.6: "The claim's statute is resolved by its `state_code`, and
        the accrual basis date is chosen by the statute's `interest_basis`: the
        claim's `date_of_death` when the basis is `DATE_OF_DEATH`, or the
        claim's `proof_complete_date` when the basis is `PROOF_OF_LOSS_COMPLETE`
        — if proof is incomplete there is no basis date and accrual cannot
        start."
        PRD §3.6: "Because the two basis variants start the clock on different
        dates, identical claim data yields more interest under the death basis
        than under the proof basis whenever death precedes proof completion."

        NY leg (with the IL leg rebuilt alongside for the divergence check):
        basis proof_complete_date 2026-03-11, approve 2026-04-10 -> 30 elapsed
        - 15 grace = 15 accrual days; 25000000 x 9% x 15/365 = 92466 (half-up
        of 92465.75).

        Design: Difficulty/dual_variant_calc/statutory_interest_basis_date_of_death_vs_proof_complete
        """
        create_statute("IL")
        create_statute("NY")
        policy_il = create_policy(state_code="IL", policy_number="P-IL-1",
                                  face_amount_cents=25000000,
                                  contestability_months=24)
        policy_ny = create_policy(state_code="NY", policy_number="P-NY-1",
                                  face_amount_cents=25000000,
                                  contestability_months=24)
        claim_il, _ = file_claim_with_verified_docs(
            policy_il["id"], "2026-03-01", filing_clock="2026-03-05T00:00:00Z",
            review_clock="2026-03-11T00:00:00Z")
        claim_ny, _ = file_claim_with_verified_docs(
            policy_ny["id"], "2026-03-01", filing_clock="2026-03-05T00:00:00Z",
            review_clock="2026-03-11T00:00:00Z")
        assert get_claim(claim_ny["id"])["proof_complete_date"] == "2026-03-11"

        set_clock("2026-04-10T00:00:00Z")
        approved_il = validate_success(api.approve_claim(claim_il["id"],
                                                         claims_approver_headers))
        approved_ny = validate_success(api.approve_claim(claim_ny["id"],
                                                         claims_approver_headers))
        assert approved_ny["accrued_interest_cents"] == 92466
        assert approved_ny["total_payable_cents"] == 25092466
        assert approved_il["accrued_interest_cents"] == 68493
        assert approved_il["accrued_interest_cents"] != approved_ny["accrued_interest_cents"], (
            "Identical claim data must diverge purely from the accrual-basis variant")


class TestElectionLifecycle:
    def test_election_supersede_replaces_prior(self, api,
                                               claims_examiner_headers):
        """PRD §3.8: "A created election stands in `ELECTED` status with
        `elected_at` stamped from the logical clock, and creating it supersedes
        the beneficiary's prior election: every previous election of that
        beneficiary claim not already `SUPERSEDED` moves to `SUPERSEDED`."

        Design: Corner/state_machines/c_election_supersede_replaces_prior
        """
        ctx = setup_approved_claim(state="TX", policy_overrides={
            "policy_number": "P-SM-7"})
        bc = ctx["beneficiary_claims"][0]
        e1 = setup_election(ctx, option="LUMP_SUM", confirm=False)
        assert e1["status"] == "ELECTED"

        # The first creation bumped the claim version; fetch the fresh one.
        e2 = create_election_via(api, bc["id"], ctx["claim"]["id"],
                                 "RETAINED_ASSET_ACCOUNT",
                                 claims_examiner_headers)
        assert e2["status"] == "ELECTED"

        elections = list_elections(bc["id"])
        by_id = {e["id"]: e for e in elections}
        assert by_id[e1["id"]]["status"] == "SUPERSEDED"
        assert by_id[e2["id"]]["status"] == "ELECTED"
        assert len(elections) == 2

    def test_election_confirm_twice_rejected(self, api, claims_examiner_headers):
        """PRD §3.8: "Confirming an election requires it to still be `ELECTED`
        — else `ERR_ELECTION_NOT_CONFIRMABLE` — and the same thirty-day window
        applies at confirmation, with a closed window rejected as
        `ERR_ELECTION_WINDOW_CLOSED`."
        PRD §3.8: "Confirmation stamps `confirmed_at` and moves the election to
        `CONFIRMED`."

        Design: Corner/state_machines/c_election_confirm_twice_rejected
        """
        ctx = setup_approved_claim(state="TX", policy_overrides={
            "policy_number": "P-SM-8"})
        election = setup_election(ctx, option="LUMP_SUM", confirm=True)
        assert election["status"] == "CONFIRMED"
        confirmed_at = election["confirmed_at"]

        resp = api.confirm_payout_election(election["id"], claims_examiner_headers)
        validate_error(resp, ApiErrorId.ERR_ELECTION_NOT_CONFIRMABLE)

        elections = list_elections(ctx["beneficiary_claims"][0]["id"])
        assert elections[0]["status"] == "CONFIRMED"
        assert elections[0]["confirmed_at"] == confirmed_at, (
            "A rejected confirmation must not re-stamp confirmed_at")

    def test_occ_stale_claim_version_rejected(self, api,
                                              claims_examiner_headers):
        """PRD §2.8: "recording a settlement election for a beneficiary claim
        requires the request to carry `expected_claim_version`, holding the
        claim `version` the client last observed. Because creating an election
        legitimately supersedes the beneficiary's prior election, a writer
        holding a stale claim version would supersede a choice it never saw; if
        `expected_claim_version` does not match the claim's current `version`,
        the request is rejected with `ERR_STALE_CLAIM_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/c_occ_stale_claim_version_rejected
        """
        ctx = setup_approved_claim(state="TX", policy_overrides={
            "policy_number": "P-OCC-1"})
        claim_id = ctx["claim"]["id"]
        bc = ctx["beneficiary_claims"][0]
        stale_version = ctx["claim"]["version"]
        setup_election(ctx, option="LUMP_SUM", confirm=False,
                       beneficiary_index=0)  # bumps the claim version

        resp = api.create_payout_election(
            bc["id"], {"option": "RETAINED_ASSET_ACCOUNT",
                       "expected_claim_version": stale_version},
            claims_examiner_headers)
        validate_error(resp, ApiErrorId.ERR_STALE_CLAIM_VERSION)

        elections = list_elections(bc["id"])
        assert len(elections) == 1
        assert elections[0]["status"] == "ELECTED"
        assert elections[0]["option"] == "LUMP_SUM"


class TestExecutePaymentGates:
    def test_execute_payment_requires_approved_and_confirmed_election(
        self, api, claims_approver_headers, claims_examiner_headers
    ):
        """PRD §3.8: "The claim must be `APPROVED` — a claim under legal hold
        rejects the execution with `ERR_CLAIM_IN_LEGAL_HOLD`, and any other
        non-approved state with `ERR_CLAIM_NOT_APPROVED`."
        PRD §3.8: "There must be at least one beneficiary claim in `PAYABLE`
        holding a `CONFIRMED` election, else the execution is rejected with
        `ERR_NO_PAYABLE_BENEFICIARIES`."

        Design: Corner/state_machines/c_execute_payment_requires_approved_and_confirmed_election
        """
        # Claim 1: never approved (UNDER_REVIEW).
        policy1 = create_policy_with_statute("TX", policy_number="P-SM-11A")
        set_clock("2026-03-05T00:00:00Z")
        claim1 = file_claim(policy1["id"], "2026-03-01")
        begin_review(claim1["id"])

        resp1 = api.execute_payment(claim1["id"], claims_approver_headers)
        validate_error(resp1, ApiErrorId.ERR_CLAIM_NOT_APPROVED)

        # Claim 2: APPROVED with a PAYABLE beneficiary whose election is only
        # ELECTED (never confirmed).
        ctx = setup_approved_claim(state="TX", policy_overrides={
            "policy_number": "P-SM-11B"})
        bc = ctx["beneficiary_claims"][0]
        setup_election(ctx, option="LUMP_SUM", confirm=False)

        resp2 = api.execute_payment(ctx["claim"]["id"], claims_approver_headers)
        validate_error(resp2, ApiErrorId.ERR_NO_PAYABLE_BENEFICIARIES)
        assert get_claim(ctx["claim"]["id"])["status"] == "APPROVED"
        assert get_beneficiary_claim(bc["id"])["status"] == "PAYABLE"


class TestElectionWindowAndRaaMinimum:
    def test_election_window_closed_beats_raa_minimum(
        self, api, claims_examiner_headers
    ):
        """PRD §2.10: "When several checks could reject the same request, the
        server applies them in a fixed priority order so that the surfaced
        error is deterministic."
        PRD §2.10: "9. Temporal rules (`ERR_INVALID_DEATH_DATE`,
        `ERR_ELECTION_WINDOW_CLOSED`, `ERR_ESCHEATMENT_NOT_DUE`,
        `ERR_DESIGNATION_FROZEN_AFTER_CLAIM`)." precedes "12. Fiscal floors and
        balances (`ERR_BELOW_RAA_MINIMUM`, `ERR_INSUFFICIENT_ACCOUNT_BALANCE`,
        `ERR_NO_PAYABLE_BENEFICIARIES`)."
        PRD §3.8: "The election window is thirty days: the logical clock date
        must be on or before the claim's `approved_at` plus 30 days, and a late
        election is rejected with `ERR_ELECTION_WINDOW_CLOSED`."

        Approved 2026-03-05 -> window closes after 2026-04-04; at 2026-04-05 a
        retained-asset election that is ALSO below the 100000-cent minimum
        surfaces the temporal error.

        Design: Difficulty/priority_pair_validation_conflict/election_window_closed_beats_raa_minimum
        """
        ctx = setup_approved_claim(
            state="TX", face_amount_cents=50000,
            beneficiaries=[{"name": "Alice Poe", "type": "PRIMARY", "share": 100}],
            policy_overrides={"policy_number": "P-PRI-2",
                              "insured_name": "Jim Poe",
                              "insured_dob": "1965-02-02"})
        bc = ctx["beneficiary_claims"][0]
        assert get_beneficiary_claim(bc["id"])["allocated_amount_cents"] == 50000

        set_clock("2026-04-05T00:00:00Z")
        resp = api.create_payout_election(
            bc["id"], {"option": "RETAINED_ASSET_ACCOUNT",
                       "expected_claim_version": ctx["claim"]["version"]},
            claims_examiner_headers)
        validate_error(resp, ApiErrorId.ERR_ELECTION_WINDOW_CLOSED)
        assert list_elections(bc["id"]) == [], "No election may be persisted"

    def test_election_window_last_day_raa_minimum_fires(
        self, api, claims_examiner_headers
    ):
        """PRD §3.8: "The election window is thirty days: the logical clock
        date must be on or before the claim's `approved_at` plus 30 days, and a
        late election is rejected with `ERR_ELECTION_WINDOW_CLOSED`."
        PRD §3.8: "Choosing the retained-asset option additionally requires the
        beneficiary claim's `allocated_amount_cents` to be at least the
        statute's `raa_minimum_cents`, else the election is rejected with
        `ERR_BELOW_RAA_MINIMUM`."

        Boundary leg: on 2026-04-04 (exactly approved_at + 30 days) the window
        is still open, so the fiscal floor surfaces instead.

        Design: Difficulty/priority_pair_validation_conflict/election_window_closed_beats_raa_minimum
        """
        ctx = setup_approved_claim(
            state="TX", face_amount_cents=50000,
            beneficiaries=[{"name": "Alice Poe", "type": "PRIMARY", "share": 100}],
            policy_overrides={"policy_number": "P-PRI-2",
                              "insured_name": "Jim Poe",
                              "insured_dob": "1965-02-02"})
        bc = ctx["beneficiary_claims"][0]

        set_clock("2026-04-04T00:00:00Z")
        resp = api.create_payout_election(
            bc["id"], {"option": "RETAINED_ASSET_ACCOUNT",
                       "expected_claim_version": ctx["claim"]["version"]},
            claims_examiner_headers)
        validate_error(resp, ApiErrorId.ERR_BELOW_RAA_MINIMUM)

    def test_raa_minimum_pure_fiscal_rejected(self, api,
                                              claims_examiner_headers):
        """PRD §3.8: "Choosing the retained-asset option additionally requires
        the beneficiary claim's `allocated_amount_cents` to be at least the
        statute's `raa_minimum_cents`, else the election is rejected with
        `ERR_BELOW_RAA_MINIMUM`."

        Same-day election inside the window: the pure fiscal path.

        Design: Corner/validations/c_raa_minimum_pure_fiscal_rejected
        """
        ctx = setup_approved_claim(
            state="TX", face_amount_cents=50000,
            beneficiaries=[{"name": "Alice Poe", "type": "PRIMARY", "share": 100}],
            policy_overrides={"policy_number": "P-VAL-7",
                              "insured_name": "Jim Poe",
                              "insured_dob": "1965-02-02"})
        bc = ctx["beneficiary_claims"][0]

        resp = api.create_payout_election(
            bc["id"], {"option": "RETAINED_ASSET_ACCOUNT",
                       "expected_claim_version": ctx["claim"]["version"]},
            claims_examiner_headers)
        validate_error(resp, ApiErrorId.ERR_BELOW_RAA_MINIMUM)
        assert list_elections(bc["id"]) == []


class TestGraceDayBoundaryAtPayment:
    def test_payment_at_exactly_grace_days_accrues_zero(
        self, api, claims_approver_headers
    ):
        """PRD §3.6: "The days elapsed are counted from the basis date to the
        as-of date, and the accrual days are the days elapsed beyond the
        statute's `grace_days`, floored at zero: on the day the elapsed count
        exactly equals the grace period, accrual is still zero."
        PRD §3.8: "Execution first recomputes the statutory interest of §3.6 as
        of the payment date, refreshes `total_payable_cents` to the face amount
        plus the recomputed interest, and re-runs the allocation waterfall so
        every pool member's `allocated_amount_cents` reflects the final total."

        X leg: payment at 2026-03-31, exactly 30 days after the 2026-03-01
        death under a 30-day grace, accrues nothing.

        Design: Difficulty/boundary_precision_check/interest_grace_day_exact_zero_vs_plus_one
        """
        ctx = _setup_approved_with_confirmed_lump_sum("P-GR-1")
        paid = validate_success(api.execute_payment(ctx["claim"]["id"],
                                                    claims_approver_headers))
        assert paid["status"] == "PAID"
        assert paid["accrued_interest_cents"] == 0
        assert paid["total_payable_cents"] == 25000000

    def test_payment_one_day_past_grace_accrues_one_day(
        self, api, claims_approver_headers
    ):
        """PRD §3.6: "The interest is then the claim's `face_amount_cents`
        multiplied by the statute's `annual_interest_rate_bp`, divided by ten
        thousand, multiplied by the accrual days, and divided by 365, with the
        result rounded half-up to whole cents."
        PRD §3.8: "Either way the beneficiary claim's `paid_amount_cents` is
        set to its final, post-recompute `allocated_amount_cents` and it moves
        to `PAID`, its `version` incrementing."

        X+1 leg: payment at 2026-04-01, 31 days after the death, accrues
        exactly one day (25000000 x 10% x 1/365 = 6849, half-up of 6849.32),
        and the re-run allocation carries the refreshed total into the payout.

        Design: Difficulty/boundary_precision_check/interest_grace_day_exact_zero_vs_plus_one
        """
        ctx = _setup_approved_with_confirmed_lump_sum("P-GR-2")
        set_clock("2026-04-01T00:00:00Z")
        paid = validate_success(api.execute_payment(ctx["claim"]["id"],
                                                    claims_approver_headers))
        assert paid["accrued_interest_cents"] == 6849
        assert paid["total_payable_cents"] == 25006849

        bc = get_beneficiary_claim(ctx["beneficiary_claims"][0]["id"])
        assert bc["status"] == "PAID"
        assert bc["paid_amount_cents"] == 25006849, (
            "The allocation is re-run against the refreshed total at payment")


class TestExecutePaymentRaaCascade:
    def test_execute_payment_pays_beneficiary_and_completes_claim(
        self, api
    ):
        """PRD §3.8: "Either way the beneficiary claim's `paid_amount_cents` is
        set to its final, post-recompute `allocated_amount_cents` and it moves
        to `PAID`, its `version` incrementing."
        PRD §3.8: "When every beneficiary claim in `PAYABLE` standing has
        reached `PAID` and the sum of the disbursed amounts equals the claim's
        `total_payable_cents`, the claim itself bubbles up to `PAID`, stamping
        `paid_at` from the logical clock and incrementing the claim's
        `version`."

        Cascade links 1 and 3: the PAYABLE beneficiary claim is paid its full
        allocation and the claim bubbles to PAID.

        Design: Difficulty/transitive_cascade/execute_payment_raa_cascade
        """
        ctx = setup_paid_claim_with_raa(
            payment_clock="2026-04-01T00:00:00Z",
            state="TX", policy_overrides={"policy_number": "P-CAS-2"})
        bc = get_beneficiary_claim(ctx["beneficiary_claims"][0]["id"])
        assert bc["status"] == "PAID"
        assert bc["paid_amount_cents"] == 10000000

        claim = ctx["claim"]
        assert claim["status"] == "PAID"
        assert claim["paid_at"] == "2026-04-01"
        assert claim["total_payable_cents"] == 10000000

    def test_execute_payment_funds_open_retained_asset_account(
        self, api
    ):
        """PRD §3.8: "a `RETAINED_ASSET_ACCOUNT` election funds a new retained
        asset account that opens in `OPEN` status with its `deposited_cents`
        and `balance_cents` both set to the disbursed amount,
        `withdrawn_total_cents` at zero, and `last_activity_at` stamped from
        the logical clock."

        Cascade link 2: exactly one account is created by the payment, fully
        funded by the disbursed allocation.

        Design: Difficulty/transitive_cascade/execute_payment_raa_cascade
        """
        ctx = setup_paid_claim_with_raa(
            payment_clock="2026-04-01T00:00:00Z",
            state="TX", policy_overrides={"policy_number": "P-CAS-2"})
        account = ctx["account"]
        assert account["status"] == "OPEN"
        assert account["deposited_cents"] == 10000000
        assert account["balance_cents"] == 10000000
        assert account["withdrawn_total_cents"] == 0
        assert account["last_activity_at"].startswith("2026-04-01")
        assert account["claim_id"] == ctx["claim"]["id"]
        assert account["beneficiary_claim_id"] == ctx["beneficiary_claims"][0]["id"]


# ---------------------------------------------------------------------------
# Shared scenario builders
# ---------------------------------------------------------------------------

def create_election_via(api, beneficiary_claim_id, claim_id, option, headers):
    """Create an election against the freshly observed claim version."""
    current_version = get_claim(claim_id)["version"]
    resp = api.create_payout_election(
        beneficiary_claim_id,
        {"option": option, "expected_claim_version": current_version},
        headers)
    return validate_success(resp, expected_status=201)


def _setup_approved_with_confirmed_lump_sum(policy_number):
    """IL policy face 25000000, Alice PRIMARY 100%; claim approved at the
    2026-03-31 logical clock (exactly 30 days after the 2026-03-01 death, so
    provisional interest is zero) with a CONFIRMED LUMP_SUM election."""
    ctx = setup_approved_claim(
        state="IL",
        face_amount_cents=25000000,
        approve_clock="2026-03-31T00:00:00Z",
        policy_overrides={"policy_number": policy_number},
    )
    assert ctx["claim"]["accrued_interest_cents"] == 0
    assert ctx["claim"]["total_payable_cents"] == 25000000
    setup_election(ctx, option="LUMP_SUM", confirm=True)
    return ctx
