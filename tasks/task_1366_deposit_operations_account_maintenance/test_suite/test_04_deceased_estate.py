"""Deceased-account handling: death verification gates and snapshots, the
deceased-hold cascade, and estate release variants with their conservation
invariant."""
from test_helpers import (
    MANAGER,
    MANAGER_2,
    OFFICER,
    OFFICER_1,
    ApiErrorId,
    add_active_signer,
    add_verified_document,
    api_client,
    assert_deceased_case,
    deceased_case_payload,
    file_title_change,
    get_account,
    initiate_release,
    initiate_release_payload,
    open_account,
    post_federal_benefit,
    report_deceased_case,
    set_clock,
    setup_verified_estate,
    submit_document,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestDeceasedCaseValidation:

    def test_err_documents_incomplete_on_deceased_verify(self):
        """PRD section 3.4: "An `OpsManager` verifies a case still in
        `REPORTED` — any other status fails with `ERR_INVALID_STATE` — and
        only when the account holds a `VERIFIED` `DEATH_CERTIFICATE`
        document (`ERR_DOCUMENTS_INCOMPLETE` otherwise)."

        Design: Corner/errors/err_documents_incomplete_on_deceased_verify
        """
        acct = open_account(opening_deposit_cents=5000,
                            primary_owner_name="DInc D", owner_tax_id="E6")
        # A SUBMITTED-but-unverified certificate does not count.
        submit_document(acct["id"], "DEATH_CERTIFICATE", "DC-X")
        case = report_deceased_case(acct["id"], "2026-08-01",
                                    decedent_name="DInc D",
                                    reported_by="Kin D")

        resp = api_client.verify_deceased_case(case["id"], MANAGER)
        validate_error(resp, ApiErrorId.ERR_DOCUMENTS_INCOMPLETE)

    def test_date_of_death_in_future_rejected(self):
        """PRD section 3.4: "The date of death may not lie in the future
        relative to the logical clock (`ERR_DATE_RANGE_INVALID`)".

        Design: Corner/validations/date_of_death_in_future_rejected
        """
        acct = open_account(opening_deposit_cents=5000,
                            primary_owner_name="Fut F", owner_tax_id="C19")
        resp = api_client.report_deceased_case(
            acct["id"],
            deceased_case_payload("2026-09-01", decedent_name="Fut F",
                                  reported_by="Kin F"),
            OFFICER,
        )
        validate_error(resp, ApiErrorId.ERR_DATE_RANGE_INVALID)

    def test_deceased_initiate_release_from_reported_rejected(self):
        """PRD section 3.4: "Initiation requires the case to be `VERIFIED`
        (`ERR_INVALID_STATE` otherwise), a `VERIFIED` `LETTERS_TESTAMENTARY`
        document on the account (`ERR_DOCUMENTS_INCOMPLETE` otherwise), and
        no garnishment order still holding funds on the account
        (`ERR_CLOSURE_BLOCKED` otherwise)".

        Design: Corner/state_machines/deceased_initiate_release_from_reported_rejected
        """
        acct = open_account(opening_deposit_cents=5000,
                            primary_owner_name="Skip S", owner_tax_id="C7")
        case = report_deceased_case(acct["id"], "2026-08-01",
                                    decedent_name="Skip S",
                                    reported_by="Kin S")
        assert case["status"] == "REPORTED"

        resp = api_client.initiate_release(
            case["id"],
            initiate_release_payload("DATE_OF_DEATH",
                                     estate_representative_name="Exec S"),
            OFFICER,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestEstateReleaseDualVariant:
    """Identical transaction history; the release_variant selects the
    measurement basis and changes the released cents."""

    def _setup_verified_pair_with_post_death_credit(self):
        acct_a, case_a = setup_verified_estate(
            opening_deposit_cents=100000, primary_owner_name="Dec A",
            owner_tax_id="T3", reported_by="Kin A", doc_prefix="A-")
        acct_b, case_b = setup_verified_estate(
            opening_deposit_cents=100000, primary_owner_name="Dec B",
            owner_tax_id="T4", reported_by="Kin B", doc_prefix="B-")
        set_clock("2026-08-10T00:00:00Z")
        # Post-death credits land on each account (credits post under any
        # restriction posture).
        post_federal_benefit(acct_a["id"], 50000, "2026-08-05")
        post_federal_benefit(acct_b["id"], 50000, "2026-08-05")
        return case_a, case_b

    def test_estate_release_date_of_death_variant_uses_snapshot(self):
        """PRD section 3.4: "Under `DATE_OF_DEATH`, funds are quarantined at
        death: `release_amount_cents` is the sum of `balance_at_death_cents`
        and `accrued_interest_at_death_cents`, excluding post-death deposits
        and later interest."

        Design: Difficulty/dual_variant_calc/estate_release_date_of_death_vs_date_of_release
        """
        case_a, _ = self._setup_verified_pair_with_post_death_credit()
        case = initiate_release(case_a["id"], "DATE_OF_DEATH",
                                estate_representative_name="Exec A")
        assert_deceased_case(case)
        assert case["status"] == "RELEASE_PENDING"
        # Frozen snapshot: 100000 + 0 interest; the post-death 50000 credit
        # and later interest are excluded.
        assert case["release_amount_cents"] == 100000
        assert case["initiated_by_user_id"] == "u-off-1"

    def test_estate_release_date_of_release_variant_uses_live_balance(self):
        """PRD section 3.4: "Under `DATE_OF_RELEASE`, the estate receives
        everything through the release: `release_amount_cents` is the
        account's current `balance_cents` plus interest accrued under the
        STANDARD variant over the half-open window from `accrual_start_date`
        to the current logical clock date."

        Design: Difficulty/dual_variant_calc/estate_release_date_of_death_vs_date_of_release
        """
        case_a, case_b = self._setup_verified_pair_with_post_death_credit()
        rel_a = initiate_release(case_a["id"], "DATE_OF_DEATH",
                                 estate_representative_name="Exec A")
        rel_b = initiate_release(case_b["id"], "DATE_OF_RELEASE",
                                 estate_representative_name="Exec B")
        # Live balance includes the post-death 50000 credit; rate is 0.
        assert rel_b["release_amount_cents"] == 150000
        assert rel_a["release_amount_cents"] == 100000
        assert rel_a["release_amount_cents"] != rel_b["release_amount_cents"]


class TestDeceasedVerifyCascade:

    def _setup_reported_case_with_signer_and_title(self):
        acct = open_account(opening_deposit_cents=100000,
                            primary_owner_name="Dec C", owner_tax_id="T11")
        req = file_title_change(acct["id"], "JOINT", acct["version"],
                                headers=OFFICER_1)
        add_verified_document(acct["id"], "DEATH_CERTIFICATE", "DC-C")
        signer = add_active_signer(acct["id"], reference_number="SC-2",
                                   full_name="Sig T", tax_id="TS2")
        case = report_deceased_case(acct["id"], "2026-08-01",
                                    decedent_name="Dec C",
                                    reported_by="Kin C")
        return acct, req, signer, case

    def test_deceased_verify_snapshots_and_restricts_account(self):
        """PRD section 3.4: "Verification freezes the estate's basis:
        `balance_at_death_cents` snapshots the account's `balance_cents`,
        and `accrued_interest_at_death_cents` snapshots the interest accrued
        over the half-open window from `accrual_start_date` up to the
        `date_of_death`, computed with the STANDARD rounding variant
        regardless of the account's product; both stay null until this
        moment."
        PRD section 3.4: "The same act hardens the account:
        `restriction_status` moves from `NONE` to `DECEASED_HOLD`".

        Design: Difficulty/transitive_cascade/deceased_verify_signer_suspension_chain
        """
        acct, _req, _signer, case = \
            self._setup_reported_case_with_signer_and_title()

        verified = validate_success(
            api_client.verify_deceased_case(case["id"], MANAGER),
            expected_status=200,
        )
        assert verified["status"] == "VERIFIED"
        assert verified["balance_at_death_cents"] == 100000
        # Window [accrual_start_date, date_of_death) is empty here.
        assert verified["accrued_interest_at_death_cents"] == 0

        acct_after = get_account(acct["id"])
        assert acct_after["restriction_status"] == "DECEASED_HOLD"
        assert acct_after["statement_suppression"] == "DECEASED"
        assert acct_after["version"] > acct["version"]

    def test_deceased_verify_suspends_signers_and_rejects_title_changes(self):
        """PRD section 3.4: "The same act hardens the account:
        `restriction_status` moves from `NONE` to `DECEASED_HOLD`, every
        `ACTIVE` signer is suspended, every `SUBMITTED` title change is
        auto-rejected with `decision_reason` `DECEASED_ACCOUNT`, and
        `statement_suppression` recomputes to `DECEASED` — one mutation that
        increments the account's `version`."

        Design: Difficulty/transitive_cascade/deceased_verify_signer_suspension_chain
        """
        acct, req, signer, case = \
            self._setup_reported_case_with_signer_and_title()
        validate_success(api_client.verify_deceased_case(case["id"], MANAGER),
                         expected_status=200)

        signers, _ = validate_paginated(
            api_client.list_signers(acct["id"], MANAGER))
        by_id = {s["id"]: s for s in signers}
        assert by_id[signer["id"]]["status"] == "SUSPENDED"

        requests, _ = validate_paginated(
            api_client.list_title_changes(acct["id"], MANAGER))
        by_req = {r["id"]: r for r in requests}
        assert by_req[req["id"]]["status"] == "REJECTED"
        assert by_req[req["id"]]["decision_reason"] == "DECEASED_ACCOUNT"


class TestEstateReleaseConservation:

    def _setup_release_pending(self):
        acct, case = setup_verified_estate(
            opening_deposit_cents=100000, primary_owner_name="Est E",
            owner_tax_id="T21", reported_by="Kin E", doc_prefix="E-")
        set_clock("2026-08-10T00:00:00Z")
        post_federal_benefit(acct["id"], 50000, "2026-08-05")
        case = initiate_release(case["id"], "DATE_OF_DEATH",
                                estate_representative_name="Exec E")
        assert case["release_amount_cents"] == 100000
        return acct, case

    def test_estate_release_conservation_invariant(self):
        """PRD section 3.4: "The conservation invariant holds through the
        whole act — the balance immediately before approval equals the
        release amount plus the residual, and the final balance is exactly
        zero."
        PRD section 3.4: "The account closes in the same atomic act: the
        `DECEASED_HOLD` restriction clears to `NONE` only as part of this
        estate-release closure, the lifecycle proceeds to `CLOSED`,
        `closure_payout_cents` is the release amount plus the residual
        swept, and `closure_payout_destination` is `ESTATE`."

        Design: Difficulty/compensating_invariant/estate_release_conservation_invariant
        """
        acct, case = self._setup_release_pending()
        balance_before = 150000  # 100000 opening + 50000 post-death credit

        approved = validate_success(
            api_client.approve_release(case["id"], MANAGER_2),
            expected_status=200,
        )
        assert approved["status"] == "RELEASED"
        assert approved["approved_by_user_id"] == "u-mgr-2"

        acct_after = get_account(acct["id"])
        assert acct_after["lifecycle_status"] == "CLOSED"
        assert acct_after["balance_cents"] == 0
        # release 100000 + residual 50000 == balance before == payout
        assert acct_after["closure_payout_cents"] == 100000 + 50000
        assert acct_after["closure_payout_cents"] == balance_before
        assert acct_after["closure_payout_destination"] == "ESTATE"

    def test_estate_release_posts_estate_release_then_closure_payout(self):
        """PRD section 3.4: "Approval posts an `ESTATE_RELEASE` transaction
        debiting `release_amount_cents`, then sweeps any residual: if the
        balance remains above zero — as it can when post-death credits
        landed under the `DATE_OF_DEATH` variant — a `CLOSURE_PAYOUT`
        transaction of the remaining balance posts."

        Design: Difficulty/compensating_invariant/estate_release_conservation_invariant
        """
        acct, case = self._setup_release_pending()
        validate_success(api_client.approve_release(case["id"], MANAGER_2),
                         expected_status=200)

        txns, _ = validate_paginated(
            api_client.list_transactions(acct["id"], MANAGER))
        types = [t["txn_type"] for t in txns]
        assert types[0] == "DEPOSIT"
        assert types[1] == "FEDERAL_BENEFIT_DEPOSIT"
        assert types[2] == "ESTATE_RELEASE"
        assert txns[2]["amount_cents"] == 100000
        assert txns[3]["txn_type"] == "CLOSURE_PAYOUT"
        assert txns[3]["amount_cents"] == 50000
        assert txns[3]["balance_after_cents"] == 0
