"""Presumptive charity screening: dual-model eligibility, tiered FPL formula,
inclusive caps, per-account listing, and OCC-guarded creation."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_screening,
    create_account,
    create_pending_screening,
    issue_statements,
    read_account,
    validate_error,
    validate_paginated,
    validate_success,
)

COLLECTOR = TEST_USERS["collector_headers"]
COUNSELOR = TEST_USERS["counselor_headers"]


def _score_payload(account_id, version, score):
    return {
        "account_id": account_id,
        "screening_model": "SCORE_BASED",
        "third_party_score": score,
        "expected_account_version": version,
    }


def _fpl_payload(account_id, version, household_size, income_cents):
    return {
        "account_id": account_id,
        "screening_model": "FPL_TIERED",
        "household_size": household_size,
        "household_income_cents": income_cents,
        "expected_account_version": version,
    }


def _create_and_evaluate(api, payload):
    screening = validate_success(api.create_screening(payload, COUNSELOR), 201)
    return validate_success(api.evaluate_screening(screening["id"], COUNSELOR), 200)


class TestDualModelEligibility:
    def test_fpl_tiered_vs_score_based_same_account(self, api):
        """PRD §3.3: "then computes `fpl_percent` as one hundred times
        `household_income_cents` divided by that base, rounded down to a whole
        percent."
        PRD §3.3: "above 200 but at most 300 yields `PARTIAL_CHARITY` with a
        `charity_writeoff_percent` of 50"
        PRD §3.3: "For a `SCORE_BASED` screening, `fpl_percent` remains null: a
        `third_party_score` of at least 700 yields `FULL_CHARITY`, at least 550
        but below 700 yields `PARTIAL_CHARITY`, and below 550 yields
        `NOT_ELIGIBLE`, with the same 100, 50, and 0 write-off percentages."

        Household of four with 7000000 cents income: floor(7000000*100/3120000)
        = 224 -> PARTIAL_CHARITY. Score 600 -> PARTIAL_CHARITY with null
        fpl_percent: the two model variants diverge in the fpl_percent field.

        Design: Difficulty/dual_variant_calc/charity_screening_fpl_vs_score_model
        """
        account = create_account(
            balance_cents=500000, guarantor_liability_date="2026-01-15",
            patient_mrn="MRN-A1", patient_name="Alice A")

        fpl_screening = _create_and_evaluate(api, _fpl_payload(
            account["id"], read_account(account["id"])["version"], 4, 7000000))
        assert fpl_screening["eligibility_outcome"] == "PARTIAL_CHARITY"
        assert fpl_screening["fpl_percent"] == 224
        assert fpl_screening["charity_writeoff_percent"] == 50

        score_screening = _create_and_evaluate(api, _score_payload(
            account["id"], read_account(account["id"])["version"], 600))
        assert_screening(score_screening)
        assert score_screening["eligibility_outcome"] == "PARTIAL_CHARITY"
        assert score_screening["fpl_percent"] is None
        assert score_screening["charity_writeoff_percent"] == 50

        # The superseded FPL screening keeps its computed outcome fields.
        reread = validate_success(
            api.get_screening(fpl_screening["id"], COUNSELOR), 200)
        assert reread["eligibility_outcome"] == "PARTIAL_CHARITY"
        assert reread["fpl_percent"] == 224

    def test_models_reach_different_outcomes_on_same_account(self, api):
        """PRD §3.3: "Two screenings on the same account under different models
        may therefore legitimately reach different outcomes; that is
        intentional."
        PRD §3.3: "An `fpl_percent` of at most 200 yields `FULL_CHARITY` with a
        `charity_writeoff_percent` of 100"

        Household of one with 1500000 cents income: floor(1500000*100/1506000)
        = 99 -> FULL_CHARITY, while a score of 500 -> NOT_ELIGIBLE.

        Design: Difficulty/dual_variant_calc/charity_screening_fpl_vs_score_model
        """
        account = create_account(
            balance_cents=200000, guarantor_liability_date="2026-06-01",
            patient_mrn="MRN-A2", patient_name="Alice Two")

        fpl_screening = _create_and_evaluate(api, _fpl_payload(
            account["id"], read_account(account["id"])["version"], 1, 1500000))
        assert fpl_screening["eligibility_outcome"] == "FULL_CHARITY"
        assert fpl_screening["fpl_percent"] == 99
        assert fpl_screening["charity_writeoff_percent"] == 100

        score_screening = _create_and_evaluate(api, _score_payload(
            account["id"], read_account(account["id"])["version"], 500))
        assert score_screening["eligibility_outcome"] == "NOT_ELIGIBLE"
        assert score_screening["fpl_percent"] is None
        assert score_screening["charity_writeoff_percent"] == 0


class TestTieredFplFormula:
    def test_fpl_tiered_household_two_full_charity(self, api):
        """PRD §3.3: "For an `FPL_TIERED` screening, the system looks up the
        federal poverty level base for the declared household size — 1,506,000
        cents for a household of one, 2,044,000 for two, 2,582,000 for three,
        3,120,000 for four, 3,658,000 for five, 4,196,000 for six, 4,734,000 for
        seven, and 5,272,000 for eight — then computes `fpl_percent` as one
        hundred times `household_income_cents` divided by that base, rounded
        down to a whole percent."
        PRD §3.3: "Upon evaluation the screening moves from `PENDING` to
        `EVALUATED`, `screened_at` is stamped from the logical clock"

        Household of two with 4000000 cents: floor(4000000*100/2044000) = 195
        -> FULL_CHARITY.

        Design: Difficulty/combinatorial_formula/charity_eligibility_tiered_with_floor_and_branching
        """
        account = create_account(
            balance_cents=100000, guarantor_liability_date="2026-07-01",
            patient_mrn="MRN-C1", patient_name="Carol C")
        screening = _create_and_evaluate(api, _fpl_payload(
            account["id"], read_account(account["id"])["version"], 2, 4000000))
        assert_screening(screening)
        assert screening["fpl_percent"] == 195
        assert screening["eligibility_outcome"] == "FULL_CHARITY"
        assert screening["charity_writeoff_percent"] == 100
        assert screening["status"] == "EVALUATED"
        assert screening["screened_at"] is not None

    def test_fpl_tiered_household_eight_not_eligible(self, api):
        """PRD §3.3: "anything higher yields `NOT_ELIGIBLE` with a
        `charity_writeoff_percent` of 0."

        Household of eight with 16000000 cents income:
        floor(16000000*100/5272000) = 303 -> NOT_ELIGIBLE.

        Design: Difficulty/combinatorial_formula/charity_eligibility_tiered_with_floor_and_branching
        """
        account = create_account(
            balance_cents=100000, guarantor_liability_date="2026-07-01",
            patient_mrn="MRN-C9", patient_name="Carol Nine")
        screening = _create_and_evaluate(api, _fpl_payload(
            account["id"], read_account(account["id"])["version"], 8, 16000000))
        assert screening["fpl_percent"] == 303
        assert screening["eligibility_outcome"] == "NOT_ELIGIBLE"
        assert screening["charity_writeoff_percent"] == 0
        assert screening["status"] == "EVALUATED"


class TestFplCapBoundaries:
    def test_fpl_percent_200_full_charity_201_partial(self, api):
        """PRD §3.3: "The boundary is inclusive, so exactly 200 percent is full
        charity while 201 percent drops to partial."

        Household-of-one base is 1506000: income 3012000 -> fpl_percent exactly
        200; income 3027060 -> fpl_percent exactly 201.

        Design: Difficulty/boundary_precision_check/fpl_percent_exactly_at_full_charity_cap
        """
        acct_g1 = create_account(
            balance_cents=100000, guarantor_liability_date="2026-07-01",
            patient_mrn="MRN-G1", patient_name="G1")
        acct_g2 = create_account(
            balance_cents=100000, guarantor_liability_date="2026-07-01",
            patient_mrn="MRN-G2", patient_name="G2")

        scr_g1 = _create_and_evaluate(api, _fpl_payload(
            acct_g1["id"], read_account(acct_g1["id"])["version"], 1, 3012000))
        assert scr_g1["fpl_percent"] == 200
        assert scr_g1["eligibility_outcome"] == "FULL_CHARITY"
        assert scr_g1["charity_writeoff_percent"] == 100

        scr_g2 = _create_and_evaluate(api, _fpl_payload(
            acct_g2["id"], read_account(acct_g2["id"])["version"], 1, 3027060))
        assert scr_g2["fpl_percent"] == 201
        assert scr_g2["eligibility_outcome"] == "PARTIAL_CHARITY"
        assert scr_g2["charity_writeoff_percent"] == 50

    def test_fpl_percent_300_partial_301_not_eligible(self, api):
        """PRD §3.3: "An `fpl_percent` of at most 200 yields `FULL_CHARITY` with
        a `charity_writeoff_percent` of 100; above 200 but at most 300 yields
        `PARTIAL_CHARITY` with a `charity_writeoff_percent` of 50; anything
        higher yields `NOT_ELIGIBLE` with a `charity_writeoff_percent` of 0."

        Household-of-one base is 1506000: income 4518000 -> fpl_percent exactly
        300; income 4533060 -> fpl_percent exactly 301.

        Design: Difficulty/boundary_precision_check/fpl_percent_exactly_at_full_charity_cap
        """
        acct_300 = create_account(
            balance_cents=100000, guarantor_liability_date="2026-07-01",
            patient_mrn="MRN-G3", patient_name="G3")
        acct_301 = create_account(
            balance_cents=100000, guarantor_liability_date="2026-07-01",
            patient_mrn="MRN-G4", patient_name="G4")

        scr_300 = _create_and_evaluate(api, _fpl_payload(
            acct_300["id"], read_account(acct_300["id"])["version"], 1, 4518000))
        assert scr_300["fpl_percent"] == 300
        assert scr_300["eligibility_outcome"] == "PARTIAL_CHARITY"

        scr_301 = _create_and_evaluate(api, _fpl_payload(
            acct_301["id"], read_account(acct_301["id"])["version"], 1, 4533060))
        assert scr_301["fpl_percent"] == 301
        assert scr_301["eligibility_outcome"] == "NOT_ELIGIBLE"
        assert scr_301["charity_writeoff_percent"] == 0


class TestScreeningListingAndOcc:
    def test_screening_list_scoped_to_account(self, api):
        """PRD §3.3: "Screenings for an account can be listed through the
        account, and the write-off list can be filtered by `screening_id` when
        tracing which write-offs a screening supported."
        PRD §2.3: "Paginated list responses include the following fields in the
        `meta` object of the response envelope: `limit`, `offset`,
        `total_count`, and `has_more`."

        Design: Corner/entities/screening_list_filtered_by_account
        """
        acct_k4 = create_account(
            balance_cents=50000, guarantor_liability_date="2026-07-01",
            patient_mrn="MRN-K4", patient_name="K4")
        create_pending_screening(
            acct_k4["id"], household_size=1, household_income_cents=1000000)
        validate_success(api.create_screening(_score_payload(
            acct_k4["id"], read_account(acct_k4["id"])["version"], 800),
            COUNSELOR), 201)
        acct_k5 = create_account(
            balance_cents=50000, guarantor_liability_date="2026-07-01",
            patient_mrn="MRN-K5", patient_name="K5")
        create_pending_screening(
            acct_k5["id"], household_size=4, household_income_cents=9000000)

        data, meta = validate_paginated(
            api.list_account_screenings(acct_k4["id"], COUNSELOR))
        assert len(data) == 2
        assert meta["total_count"] == 2
        assert all(s["account_id"] == acct_k4["id"] for s in data)

    def test_screening_create_stale_account_version_rejected(self, api):
        """PRD §2.7: "If the account's current `version` does not equal
        `expected_account_version` at request-handling time — because another
        writer has advanced the account since the client read it — the request
        is rejected with `ERR_STALE_VERSION` (HTTP 412) and nothing is
        mutated."

        Design: Corner/validations/occ_stale_version_returns_412
        """
        account = create_account(
            balance_cents=50000, guarantor_liability_date="2026-07-01",
            patient_mrn="MRN-N1", patient_name="N1")
        stale_version = account["version"]
        issue_statements(account["id"], count=1)  # advances account.version
        assert read_account(account["id"])["version"] != stale_version

        resp = api.create_screening(_fpl_payload(
            account["id"], stale_version, 1, 1000000), COUNSELOR)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, expected_status=412)
