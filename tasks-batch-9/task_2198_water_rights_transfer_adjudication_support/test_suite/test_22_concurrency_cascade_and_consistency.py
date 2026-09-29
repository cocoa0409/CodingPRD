"""Version tokens, the deepest cascade, and the absence of read-after-write lag.

PRD §2.7: "Three write operations rewrite a ledger that the caller must have read
in order to decide the write was sensible."

PRD §3.2: "When it does succeed, the declaration is the deepest cascade in the
service and `FORFEITED` is terminal and sticky."
"""
import pytest
from test_helpers import (
    ApiErrorId,
    api_client,
    assert_request_meta,
    get_success_data,
    validate_error,
    validate_paginated,
)
from test_helpers.factories import create_deposit_payload
from test_helpers.fixtures import (
    ANALYST,
    DECIDER,
    activate_right,
    add_injury_analysis,
    add_point_of_diversion,
    add_use_records_from_spec,
    conditions_of,
    create_claimant,
    create_study,
    deposit,
    draft_application,
    file_claim,
    file_protest,
    open_account,
    open_docket,
    publish_application,
    read_account,
    read_application,
    read_claimant,
    read_condition,
    read_docket,
    read_right,
    reserve_lease,
    resolve_protest,
    route_protest,
    setup_base_right,
    setup_certified_right,
    setup_documented_right,
    setup_draft_application,
    setup_protested_application,
    submit_application,
)

CLOCK = "2026-03-01T00:00:00Z"
RECORDED_PRIORITY = "1901-05-01T00:00:00Z"


def _study(right_id, method, start=2023, end=2025):
    return get_success_data(create_study(right_id, start, end, method), 201)


def _certify(study_id, expected_version, headers=ANALYST):
    return api_client.certify_hcu_study(study_id, expected_version, headers)


def _read_study(study_id):
    return get_success_data(api_client.get_hcu_study(study_id, ANALYST))


class TestRecertificationIsDistinguishedOnlyByItsToken:
    """PRD §2.7 — two `DRAFT` studies on one right, quantified two different ways.

    Certifying either one is a legal operation whatever the other has already
    done, so no state check can tell an intentional recertification apart from one
    issued against a certified volume the caller never saw.
    """

    def _two_draft_studies(self):
        bundle = setup_base_right(clock=CLOCK, use_years=(2023, 2024, 2025))
        bundle["diversion_study"] = _study(bundle["right"]["id"], "DIVERSION_BASED")
        bundle["cir_study"] = _study(bundle["right"]["id"], "CIR_BASED")
        return bundle

    def test_replaying_the_token_of_a_certification_already_made_is_refused(self):
        """PRD §2.7: "Certification legitimately supersedes whatever study was
        previously certified and overwrites the right's certified volume, so a second
        certification is a valid product operation rather than an invalid transition —
        the stale-version check is the only thing that prevents a client from replacing
        a certification it never saw."

        The first certification moves the right's ledger and therefore its `version`,
        so the token that authorised it is spent. PRD §2.7: "If it does not equal the
        right's current `version`, the certification is rejected with
        `ERR_STALE_RIGHT_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/occ_hcu_certify_stale_right_version_rejects_an_unseen_recertification
        """
        bundle = self._two_draft_studies()
        observed = read_right(bundle["right"]["id"])["version"]

        first = get_success_data(_certify(bundle["diversion_study"]["id"], observed))

        assert first["status"] == "CERTIFIED"
        after_first = read_right(bundle["right"]["id"])
        assert after_first["certified_hcu_af"] == pytest.approx(195.00, abs=0.01)
        assert after_first["transferable_af"] == pytest.approx(195.00, abs=0.01)
        assert after_first["version"] > observed
        replay = _certify(bundle["cir_study"]["id"], observed)
        validate_error(replay, ApiErrorId.ERR_STALE_RIGHT_VERSION, expected_status=412)
        assert _read_study(bundle["cir_study"]["id"])["status"] == "DRAFT"
        assert _read_study(bundle["diversion_study"]["id"])["status"] == "CERTIFIED"
        unchanged = read_right(bundle["right"]["id"])
        assert unchanged["certified_hcu_af"] == pytest.approx(195.00, abs=0.01)
        assert unchanged["version"] == after_first["version"]

    def test_the_identical_call_with_a_refreshed_token_rewrites_the_ledger(self):
        """PRD §3.3: "Whatever study was previously `CERTIFIED` on the same right, if
        any, moves to the terminal `SUPERSEDED` with its own `version` bumped — a right
        therefore has at most one certified study at any instant."

        The token is the only thing that changed, and the same request now supersedes
        the diversion-based figure with the crop-requirement figure: PRD §3.3 prices
        `CIR_BASED` on "that year's `irrigated_acres` multiplied by a crop irrigation
        requirement of 2.10 acre-feet per acre", so 100.00 acres yields 210.000 a year
        against a 260.000 face-value cap.

        Design: Corner/cross_cutting_complexity_layers/occ_hcu_certify_stale_right_version_rejects_an_unseen_recertification
        """
        bundle = self._two_draft_studies()
        get_success_data(
            _certify(
                bundle["diversion_study"]["id"],
                read_right(bundle["right"]["id"])["version"],
            )
        )

        second = get_success_data(
            _certify(
                bundle["cir_study"]["id"], read_right(bundle["right"]["id"])["version"]
            )
        )

        assert second["status"] == "CERTIFIED"
        assert second["transferable_cu_af"] == pytest.approx(210.00, abs=0.01)
        assert _read_study(bundle["diversion_study"]["id"])["status"] == "SUPERSEDED"
        right = read_right(bundle["right"]["id"])
        assert right["certified_hcu_af"] == pytest.approx(210.00, abs=0.01)
        assert right["transferable_af"] == pytest.approx(210.00, abs=0.01)
        assert right["encumbered_af"] == pytest.approx(0.00, abs=0.01)


class TestTheSecondEscrowCannotRideTheFirstEscrowsToken:
    """PRD §2.7 — two `DRAFT` applications on one right certified at 195.00 AF.

    The second request asks for 50.00 acre-feet, which still fits comfortably
    inside the 95.00 left after the first escrow, so a budget check alone would
    admit it. Only the version token knows the caller never saw that first escrow.
    """

    def _two_draft_applications(self):
        bundle = setup_certified_right(clock=CLOCK)
        bundle["first"] = draft_application(
            bundle["right"]["id"], bundle["study"]["id"], 100.00
        )
        bundle["second"] = draft_application(
            bundle["right"]["id"],
            bundle["study"]["id"],
            50.00,
            proposed_purpose_of_use="STOCKWATER",
        )
        return bundle

    def test_a_stale_token_is_refused_even_though_the_volume_would_have_fitted(self):
        """PRD §2.7: "Several applications may legitimately be pending against one right
        at once, so a repeat submission is a valid operation on identical state; the
        version check is what prevents a client from escrowing volume against a
        transferable figure that an earlier escrow already consumed."

        The refusal is `ERR_STALE_RIGHT_VERSION` and not the volume error, because PRD
        §2.11 puts the concurrency family above the fiscal one: "The concurrency checks
        sit above every state and business check, so a stale version declaration
        surfaces before the service considers whether the transition was even legal."

        Design: Corner/cross_cutting_complexity_layers/occ_application_submit_stale_right_version_protects_the_escrow_ledger
        """
        bundle = self._two_draft_applications()
        observed = read_right(bundle["right"]["id"])["version"]

        first = get_success_data(
            api_client.submit_transfer_application(
                bundle["first"]["id"], observed, ANALYST
            )
        )

        assert first["status"] == "SUBMITTED"
        assert first["escrowed_af"] == pytest.approx(100.00, abs=0.01)
        escrowed = read_right(bundle["right"]["id"])
        assert escrowed["transferable_af"] == pytest.approx(95.00, abs=0.01)
        assert escrowed["encumbered_af"] == pytest.approx(100.00, abs=0.01)
        assert escrowed["status"] == "ENCUMBERED"
        assert escrowed["version"] > observed
        stale = api_client.submit_transfer_application(
            bundle["second"]["id"], observed, ANALYST
        )
        validate_error(stale, ApiErrorId.ERR_STALE_RIGHT_VERSION, expected_status=412)
        second = read_application(bundle["second"]["id"])
        assert second["status"] == "DRAFT"
        assert second["escrowed_af"] == pytest.approx(0.00, abs=0.01)
        after = read_right(bundle["right"]["id"])
        assert after["transferable_af"] == pytest.approx(95.00, abs=0.01)
        assert after["encumbered_af"] == pytest.approx(100.00, abs=0.01)
        assert after["transferred_away_af"] == pytest.approx(0.00, abs=0.01)
        assert after["version"] == escrowed["version"]

    def test_the_refreshed_token_admits_the_second_escrow_onto_a_conserved_ledger(self):
        """PRD §3.4: "A successful submission moves the application `DRAFT → SUBMITTED`
        and sets `escrowed_af` to `requested_af`."

        Both escrows now sit on the right at once, and PRD §2.9's identity still holds
        over the three buckets: 195.00 == 45.00 + 150.00 + 0.00.

        Design: Corner/cross_cutting_complexity_layers/occ_application_submit_stale_right_version_protects_the_escrow_ledger
        """
        bundle = self._two_draft_applications()
        get_success_data(
            api_client.submit_transfer_application(
                bundle["first"]["id"], read_right(bundle["right"]["id"])["version"], ANALYST
            )
        )

        second = get_success_data(
            api_client.submit_transfer_application(
                bundle["second"]["id"],
                read_right(bundle["right"]["id"])["version"],
                ANALYST,
            )
        )

        assert second["status"] == "SUBMITTED"
        assert second["escrowed_af"] == pytest.approx(50.00, abs=0.01)
        right = read_right(bundle["right"]["id"])
        assert right["certified_hcu_af"] == pytest.approx(195.00, abs=0.01)
        assert right["transferable_af"] == pytest.approx(45.00, abs=0.01)
        assert right["encumbered_af"] == pytest.approx(150.00, abs=0.01)
        assert right["transferred_away_af"] == pytest.approx(0.00, abs=0.01)
        assert right["status"] == "ENCUMBERED"


class TestTheDepositTokenGuardsADifferentParentEntirely:
    """PRD §2.7 — the third rule names a different parent, a different field and a
    different error code.

    A bank-enrolled right certified at 195.00 funds an empty account, and the same
    10.00 acre-foot deposit is issued twice: once with the token the caller read,
    once with that same token after it has already been spent.
    """

    def _right_and_empty_account(self):
        bundle = setup_certified_right(clock=CLOCK, bank_enrolled=True)
        bundle["account"] = open_account(bundle["claimant"]["id"])
        return bundle

    def _deposit(self, bundle, deposit_af, expected_version):
        return api_client.create_deposit(
            bundle["account"]["id"],
            create_deposit_payload(bundle["right"]["id"], deposit_af, expected_version),
            ANALYST,
        )

    def test_the_replayed_deposit_is_refused_on_the_account_token_not_the_right(self):
        """PRD §2.7: "`POST /water-bank-accounts/{id}/deposits` requires
        `expected_water_bank_account_version` matching the parent
        `WaterBankAccount`'s current `version`, rejecting a mismatch with
        `ERR_STALE_ACCOUNT_VERSION` (HTTP 412). Repeated deposits are legitimate on
        identical state, so the version check is the only thing that stops a client
        committing a deposit decision made against a credit ledger it never saw."

        The first deposit moved the right's version too, but the token the endpoint
        reads is the account's, so the account's error code is the one returned. The
        refusal is total on both ledgers.

        Design: Corner/cross_cutting_complexity_layers/occ_bank_deposit_stale_account_version_rejects_a_replayed_deposit
        """
        bundle = self._right_and_empty_account()
        observed = bundle["account"]["version"]

        first = get_success_data(self._deposit(bundle, 10.00, observed))

        assert first["deposited_credit_af"] == pytest.approx(10.00, abs=0.01)
        assert first["available_credit_af"] == pytest.approx(10.00, abs=0.01)
        assert first["committed_credit_af"] == pytest.approx(0.00, abs=0.01)
        assert first["posture"] == "OPEN"
        funded_right = read_right(bundle["right"]["id"])
        assert funded_right["transferable_af"] == pytest.approx(185.00, abs=0.01)
        assert funded_right["encumbered_af"] == pytest.approx(10.00, abs=0.01)
        replay = self._deposit(bundle, 10.00, observed)
        validate_error(replay, ApiErrorId.ERR_STALE_ACCOUNT_VERSION, expected_status=412)
        account = read_account(bundle["account"]["id"])
        assert account["deposited_credit_af"] == pytest.approx(10.00, abs=0.01)
        assert account["available_credit_af"] == pytest.approx(10.00, abs=0.01)
        assert account["committed_credit_af"] == pytest.approx(0.00, abs=0.01)
        assert account["version"] == first["version"]
        held = read_right(bundle["right"]["id"])
        assert held["transferable_af"] == pytest.approx(185.00, abs=0.01)
        assert held["encumbered_af"] == pytest.approx(10.00, abs=0.01)
        assert held["version"] == funded_right["version"]

    def test_a_refreshed_token_admits_the_second_deposit_on_both_ledgers(self):
        """PRD §3.9: "On success `deposited_credit_af` and `available_credit_af` both
        increase by `deposit_af`, which conserves the credit identity because the
        deposit lands in the unencumbered bucket".

        Both conserved identities of PRD §2.9 still read true afterwards: the credit
        ledger at 15.00 == 15.00 + 0.00 + 0.00 and the right ledger at
        195.00 == 180.00 + 15.00 + 0.00.

        Design: Corner/cross_cutting_complexity_layers/occ_bank_deposit_stale_account_version_rejects_a_replayed_deposit
        """
        bundle = self._right_and_empty_account()
        get_success_data(self._deposit(bundle, 10.00, bundle["account"]["version"]))

        second = get_success_data(
            self._deposit(bundle, 5.00, read_account(bundle["account"]["id"])["version"])
        )

        assert second["deposited_credit_af"] == pytest.approx(15.00, abs=0.01)
        assert second["available_credit_af"] == pytest.approx(15.00, abs=0.01)
        assert second["committed_credit_af"] == pytest.approx(0.00, abs=0.01)
        assert second["leased_out_af"] == pytest.approx(0.00, abs=0.01)
        right = read_right(bundle["right"]["id"])
        assert right["certified_hcu_af"] == pytest.approx(195.00, abs=0.01)
        assert right["transferable_af"] == pytest.approx(180.00, abs=0.01)
        assert right["encumbered_af"] == pytest.approx(15.00, abs=0.01)
        assert right["transferred_away_af"] == pytest.approx(0.00, abs=0.01)


class TestATokenCanBeSpentByAnEntirelyDifferentEntityFamily:
    """PRD §2.7 — the right's `version` is a single sequence, whoever moves it.

    One bank-enrolled right certified at 195.00 carries both an empty bank account
    and a `DRAFT` application for 50.00 acre-feet. The deposit and the submission
    reach the right through different endpoints and different parents.
    """

    def _right_account_and_application(self):
        bundle = setup_draft_application(
            requested_af=50.00, clock=CLOCK, bank_enrolled=True
        )
        bundle["account"] = open_account(bundle["claimant"]["id"])
        return bundle

    def test_reads_never_move_the_token_but_a_deposit_does(self):
        """PRD §2.5: "`version` ... begins at 1 on creation and increments by exactly 1
        on each mutation of that row."

        Two consecutive reads by two different roles agree on everything, so nothing a
        reader does can invalidate a token. The deposit, by contrast, rewrites the
        right's buckets — PRD §3.9: "on the source right the volume moves out of
        `transferable_af` and into `encumbered_af`" — and therefore moves the right's
        version as well as the account's.

        Design: Corner/cross_cutting_complexity_layers/occ_version_token_discipline_spans_entity_families
        """
        bundle = self._right_account_and_application()

        first_read = read_right(bundle["right"]["id"])
        second_read = get_success_data(
            api_client.get_water_right(bundle["right"]["id"], DECIDER)
        )

        assert second_read == first_read
        assert second_read["version"] == first_read["version"]
        credited = deposit(bundle["account"]["id"], bundle["right"]["id"], 20.00)
        assert credited["version"] > bundle["account"]["version"]
        right = read_right(bundle["right"]["id"])
        assert right["transferable_af"] == pytest.approx(175.00, abs=0.01)
        assert right["encumbered_af"] == pytest.approx(20.00, abs=0.01)
        assert right["version"] > first_read["version"]

    def test_the_submission_is_refused_on_a_token_the_deposit_invalidated(self):
        """PRD §2.7: "`POST /transfer-applications/{id}/submit` likewise requires
        `expected_water_right_version` matching the parent `WaterRight`'s current
        `version`, rejecting a mismatch with `ERR_STALE_RIGHT_VERSION` (HTTP 412)."

        No other application exists and 50.00 acre-feet still fits inside the 175.00
        left after the bank hold, so nothing but the token objects. Re-reading is the
        only recovery, and the identical call then succeeds.

        Design: Corner/cross_cutting_complexity_layers/occ_version_token_discipline_spans_entity_families
        """
        bundle = self._right_account_and_application()
        pre_deposit_token = read_right(bundle["right"]["id"])["version"]
        deposit(bundle["account"]["id"], bundle["right"]["id"], 20.00)

        stale = api_client.submit_transfer_application(
            bundle["application"]["id"], pre_deposit_token, ANALYST
        )

        validate_error(stale, ApiErrorId.ERR_STALE_RIGHT_VERSION, expected_status=412)
        assert read_application(bundle["application"]["id"])["status"] == "DRAFT"
        assert read_right(bundle["right"]["id"])["transferable_af"] == pytest.approx(
            175.00, abs=0.01
        )
        submitted = get_success_data(
            api_client.submit_transfer_application(
                bundle["application"]["id"],
                read_right(bundle["right"]["id"])["version"],
                ANALYST,
            )
        )
        assert submitted["status"] == "SUBMITTED"
        assert submitted["escrowed_af"] == pytest.approx(50.00, abs=0.01)
        right = read_right(bundle["right"]["id"])
        assert right["transferable_af"] == pytest.approx(125.00, abs=0.01)
        assert right["encumbered_af"] == pytest.approx(70.00, abs=0.01)
        assert right["transferred_away_af"] == pytest.approx(0.00, abs=0.01)


class TestForfeitureUnwindsFourEntityFamiliesInOneCall:
    """PRD §3.2 — one declaration against a right that carries everything at once.

    A bank-enrolled right certified at 195.00 acre-feet holds a published transfer
    application escrowing 100.00, a 10.00 acre-foot bank hold committed to a
    `RESERVED` lease, and a priced mitigation condition imposed by a hearing-track
    protest resolution — which has left its holder `DELINQUENT`. Five straight
    years of non-use make it statutorily forfeitable.
    """

    CASCADE_CLOCK = "2026-06-01T00:00:00Z"
    LEASE_WINDOW = ("2026-07-01T00:00:00Z", "2026-10-01T00:00:00Z")
    CLAIMED_INJURY_AF = 20.00

    def _forfeitable_estate(self):
        bundle = setup_documented_right(self.CASCADE_CLOCK, bank_enrolled=True)
        right_id = bundle["right"]["id"]
        bundle["pod"] = add_point_of_diversion(right_id)
        spec = [(year, 300.000, 100.00, "METER") for year in (2016, 2017)]
        spec += [(year, 0.000, 0.00, "METER") for year in range(2018, 2023)]
        spec += [(year, 300.000, 100.00, "METER") for year in (2023, 2024, 2025)]
        bundle["records"] = add_use_records_from_spec(right_id, spec)
        bundle["right"] = activate_right(right_id)
        bundle["study"] = _study(right_id, "DIVERSION_BASED")
        get_success_data(
            _certify(bundle["study"]["id"], read_right(right_id)["version"])
        )
        bundle["account"] = open_account(bundle["claimant"]["id"])
        deposit(bundle["account"]["id"], right_id, 10.00)
        bundle["application"] = draft_application(right_id, bundle["study"]["id"], 100.00)
        bundle["analysis"] = add_injury_analysis(bundle["application"]["id"])
        submit_application(bundle["application"]["id"], right_id)
        bundle["application"] = publish_application(bundle["application"]["id"])
        bundle["lease"] = get_success_data(
            reserve_lease(
                bundle["account"]["id"],
                right_id,
                bundle["pod"]["id"],
                self.LEASE_WINDOW[0],
                self.LEASE_WINDOW[1],
                10.00,
            ),
            201,
        )
        bundle["protestant"] = create_claimant(
            legal_name="Bell Cattle Trust",
            contact_email="b@bell.example",
            entity_type="INDIVIDUAL",
        )
        protest = file_protest(
            bundle["application"]["id"],
            bundle["protestant"]["id"],
            self.CLAIMED_INJURY_AF,
        )
        route_protest(protest["id"], "HEARING")
        bundle["protest"] = resolve_protest(
            protest["id"], "STIPULATE", condition_type="MITIGATION_PAYMENT"
        )
        bundle["condition"] = conditions_of(bundle["application"]["id"])[0]
        # The hearing-track stipulation cleared the only protest, so PRD §3.6's
        # clearance cascade has already carried the application
        # `UNDER_PROTEST -> READY_FOR_DECISION` since it was published; the
        # snapshot has to be refreshed like the right, the account and the
        # claimant below.
        bundle["application"] = read_application(bundle["application"]["id"])
        bundle["right"] = read_right(right_id)
        bundle["account"] = read_account(bundle["account"]["id"])
        bundle["claimant"] = read_claimant(bundle["claimant"]["id"])
        return bundle

    def _declare(self, right_id):
        return api_client.declare_forfeiture(
            right_id, "Five consecutive years of non-use are of record.", ANALYST
        )

    def test_the_first_link_zeroes_every_bucket_on_an_eligible_right(self):
        """PRD §3.2: "The first link zeroes all four volume buckets —
        `certified_hcu_af`, `encumbered_af`, `transferred_away_af` and
        `transferable_af` all become 0.00 — and bumps the right's `version`."

        The right is eligible on exactly the statutory minimum. PRD §3.2: "The raw
        score is then: nine points for each consecutive non-use year, plus twenty-five
        points multiplied by the unverified ratio, plus thirty points multiplied by one
        minus utilization, plus a flat twelve-point penalty when the right's `status` is
        currently `SUSPENDED`, less a flat ten-point credit when any record in the
        window carries a `verification_source` of `METER`." Five consecutive non-use
        years carry 45.00, ten fully metered records carry no unverified component, a
        150.000 mean against an authorized 400.00 makes utilization 0.3750 and underuse
        18.75, and the meter credit takes ten back: 53.75.

        Design: Corner/cross_cutting_complexity_layers/cascade_forfeiture_declaration_unwinds_four_families_in_one_call
        """
        bundle = self._forfeitable_estate()
        assessment = get_success_data(
            api_client.get_forfeiture_assessment(bundle["right"]["id"], ANALYST)
        )
        assert assessment["consecutive_nonuse_years"] == 5
        assert assessment["nonuse_component"] == pytest.approx(45, abs=0.01)
        assert assessment["underuse_component"] == pytest.approx(18.75, abs=0.01)
        assert assessment["meter_credit"] == pytest.approx(10, abs=0.01)
        assert assessment["forfeiture_risk_score"] == pytest.approx(53.75, abs=0.01)
        assert assessment["forfeiture_risk_band"] == "ELEVATED"
        assert assessment["forfeiture_eligible"] is True
        assert bundle["right"]["encumbered_af"] == pytest.approx(110.00, abs=0.01)
        assert bundle["right"]["transferable_af"] == pytest.approx(85.00, abs=0.01)

        forfeited = get_success_data(self._declare(bundle["right"]["id"]))

        assert forfeited["status"] == "FORFEITED"
        assert forfeited["certified_hcu_af"] == pytest.approx(0.00, abs=0.01)
        assert forfeited["encumbered_af"] == pytest.approx(0.00, abs=0.01)
        assert forfeited["transferred_away_af"] == pytest.approx(0.00, abs=0.01)
        assert forfeited["transferable_af"] == pytest.approx(0.00, abs=0.01)
        assert forfeited["version"] > bundle["right"]["version"]

    def test_the_second_link_denies_the_application_and_returns_the_reservation(self):
        """PRD §3.2: "The second link reaches the right's dependents: every transfer
        application on the right in `DRAFT`, `SUBMITTED`,
        `PROTEST_PERIOD`, `UNDER_PROTEST`, `REVISION_REQUESTED` or `READY_FOR_DECISION`
        moves to `DENIED` with its `escrowed_af` released to 0.00, any still-unresolved
        protests on those applications moving to `DISMISSED` and any `DRAFT` injury
        analysis moving to `VOIDED`, with `pending_review_count` decremented
        accordingly; and every lease assignment on the right in `RESERVED`, `ACTIVE` or
        `SUSPENDED` moves to `CANCELLED`, settled by the lease settlement calculation
        with the unused portion returned to its account's available credit."

        The analysis here is already `FINALIZED`, so it leaves the pending set on its
        own terms — PRD §3.5: "`pending_review_count` on the right is the number of
        `DRAFT` injury analyses whose application sits on that right; it therefore rises
        by one for a first analysis and nets to zero when one draft replaces another,
        and the right's `version` is bumped either way." The lease settles by PRD §3.9's
        reserved leg: "`used_af` is 0.00 regardless
        of `valuation_method` because delivery never began, `settlement_credit_af` is
        the whole `requested_af`, and the credit moves out of `committed_credit_af` and
        back into `available_credit_af`".

        Design: Corner/cross_cutting_complexity_layers/cascade_forfeiture_declaration_unwinds_four_families_in_one_call
        """
        bundle = self._forfeitable_estate()
        assert bundle["application"]["status"] == "READY_FOR_DECISION"
        assert bundle["account"]["committed_credit_af"] == pytest.approx(10.00, abs=0.01)
        assert bundle["account"]["available_credit_af"] == pytest.approx(0.00, abs=0.01)

        get_success_data(self._declare(bundle["right"]["id"]))

        application = read_application(bundle["application"]["id"])
        assert application["status"] == "DENIED"
        assert application["escrowed_af"] == pytest.approx(0.00, abs=0.01)
        assert read_right(bundle["right"]["id"])["pending_review_count"] == 0
        analysis = get_success_data(
            api_client.get_injury_analysis(bundle["analysis"]["id"], ANALYST)
        )
        assert analysis["status"] == "FINALIZED"
        assert analysis["net_injury_af"] == pytest.approx(78.00, abs=0.01)
        lease = get_success_data(
            api_client.get_lease_assignment(bundle["lease"]["id"], ANALYST)
        )
        assert lease["status"] == "CANCELLED"
        assert lease["used_af"] == pytest.approx(0.00, abs=0.01)
        assert lease["settlement_credit_af"] == pytest.approx(10.00, abs=0.01)
        account = read_account(bundle["account"]["id"])
        assert account["deposited_credit_af"] == pytest.approx(10.00, abs=0.01)
        assert account["committed_credit_af"] == pytest.approx(0.00, abs=0.01)
        assert account["leased_out_af"] == pytest.approx(0.00, abs=0.01)
        assert account["available_credit_af"] == pytest.approx(10.00, abs=0.01)

    def test_the_third_link_reverses_the_fee_before_the_posture_is_recomputed(self):
        """PRD §3.2: "The third link reaches the conditions of those newly denied
        applications: every condition whose compliance dimension reads `IMPOSED` moves
        to `RELEASED`, and every condition whose fiscal dimension reads `OUTSTANDING`
        moves to `REVERSED`, decreasing the claimant's `outstanding_fee_balance_usd` by
        each reversed total fee. Exactly as after a voluntary payment, if that balance
        reaches precisely 0.00 while the claimant is `DELINQUENT`, standing returns to
        `IN_GOOD_STANDING`. Every affected water bank account then re-runs its credit
        ledger and its posture."

        The ordering is observable: the account only reads `OPEN` if the posture is
        recomputed after both the returned credit and the repaired standing.

        Nothing backs the declaration out. PRD §3.2: "When it does succeed, the
        declaration is the deepest cascade in the service and `FORFEITED` is terminal
        and sticky." And PRD §3.2: "Reinstatement is the other direction, and it closes
        the cycle `ACTIVE → SUSPENDED → ACTIVE`." A forfeited right is outside that
        cycle, and PRD §2.11 puts the state family ahead of the safety family — "then
        the domain-specific referential, uniqueness, concurrency, state, safety,
        temporal, constraint and fiscal families in that sequence" — so the illegal
        transition is reported rather than the unresolved five-year non-use run.

        Design: Corner/cross_cutting_complexity_layers/cascade_forfeiture_declaration_unwinds_four_families_in_one_call
        """
        bundle = self._forfeitable_estate()
        assert bundle["condition"]["total_fee_usd"] == pytest.approx(2600.00, abs=0.01)
        assert bundle["claimant"]["standing_status"] == "DELINQUENT"
        assert bundle["claimant"]["outstanding_fee_balance_usd"] == pytest.approx(
            2600.00, abs=0.01
        )
        assert bundle["account"]["posture"] == "RESTRICTED"

        get_success_data(self._declare(bundle["right"]["id"]))

        condition = read_condition(bundle["condition"]["id"])
        assert condition["status"] == "RELEASED"
        assert condition["payment_status"] == "REVERSED"
        claimant = read_claimant(bundle["claimant"]["id"])
        assert claimant["outstanding_fee_balance_usd"] == pytest.approx(0.00, abs=0.01)
        assert claimant["standing_status"] == "IN_GOOD_STANDING"
        account = read_account(bundle["account"]["id"])
        assert account["available_credit_af"] == pytest.approx(10.00, abs=0.01)
        assert account["suspended_lease_count"] == 0
        assert account["posture"] == "OPEN"
        protest = get_success_data(
            api_client.get_protest(bundle["protest"]["id"], ANALYST)
        )
        assert protest["status"] == "RESOLVED_STIPULATED"
        assert protest["stipulated_offset_af"] == pytest.approx(0.00, abs=0.01)
        assert (
            get_success_data(
                api_client.get_point_of_diversion(bundle["pod"]["id"], ANALYST)
            )["status"]
            == "AUTHORIZED"
        )
        validate_error(
            self._declare(bundle["right"]["id"]),
            ApiErrorId.ERR_INVALID_STATE,
            expected_status=409,
        )
        validate_error(
            api_client.reinstate_water_right(
                bundle["right"]["id"], "Owner disputes the finding.", ANALYST
            ),
            ApiErrorId.ERR_INVALID_STATE,
            expected_status=409,
        )


class TestTheWritingResponseAlreadyCarriesItsDerivedFields:
    """PRD §2.2 — a write answers with the row it just wrote, not with a promise.

    A right certified at 195.00 acre-feet holds a `DRAFT` application for 100.00, and
    an empty docket stands open beside it. The submit response, the read of the parent
    right that immediately follows it, and the docket read that immediately follows a
    claim creation are all taken with no retry and no delay between them.
    """

    DOCKET_NUMBER = "SNK-ADJ-13"
    FILING_DEADLINE = "2026-04-01T00:00:00Z"

    def _right_application_and_docket(self):
        bundle = setup_draft_application(requested_af=100.00, clock=CLOCK)
        bundle["docket"] = open_docket(
            self.FILING_DEADLINE, docket_number=self.DOCKET_NUMBER
        )
        return bundle

    def test_the_submit_response_and_the_very_next_read_agree(self):
        """PRD §2.2: "Unless otherwise noted, operations that create or modify a
        resource will return the created or updated resource object in the data field."

        PRD §3.4: "A successful submission moves the application `DRAFT → SUBMITTED`
        and sets `escrowed_af` to `requested_af`." And in the same breath: "On the
        right, `encumbered_af` increases by that same amount and `transferable_af`
        decreases by it, conserving the ledger identity; the right's status is
        re-derived, which is what carries an otherwise idle right `ACTIVE →
        ENCUMBERED`; the claimant's `open_application_count` is recomputed; and both
        the application's and the right's `version` are bumped."

        The escrow is legible in the writing response itself, and the parent right's
        derived buckets have already moved by the time the very next call reads them —
        195.00 == 95.00 + 100.00 + 0.00 on the first read, not on the second.

        Design: Corner/consistency_model/consistency_immediate_derived_fields_are_current_in_the_writing_response
        """
        bundle = self._right_application_and_docket()
        assert bundle["study"]["status"] == "CERTIFIED"
        right_id = bundle["right"]["id"]

        submitted = get_success_data(
            api_client.submit_transfer_application(
                bundle["application"]["id"], read_right(right_id)["version"], ANALYST
            )
        )

        assert submitted["status"] == "SUBMITTED"
        assert submitted["escrowed_af"] == pytest.approx(100.00, abs=0.01)
        right = read_right(right_id)
        assert right["certified_hcu_af"] == pytest.approx(195.00, abs=0.01)
        assert right["transferable_af"] == pytest.approx(95.00, abs=0.01)
        assert right["encumbered_af"] == pytest.approx(100.00, abs=0.01)
        assert right["transferred_away_af"] == pytest.approx(0.00, abs=0.01)
        assert right["status"] == "ENCUMBERED"

    def test_a_repeated_read_never_converges_over_time(self):
        """PRD §2.4: "Nothing in this service reads wall-clock time."

        A settled read is therefore idempotent: two further reads of the same right
        return the identical payload, `version` included, differing only in the
        per-request meta envelope that PRD §2.2 stamps on every response — "All
        successful API responses (those with 2xx status codes) follow this standard
        envelope format in their JSON body". Nothing converges between one call and the
        next, because nothing moves without an explicit write.

        Design: Corner/consistency_model/consistency_immediate_derived_fields_are_current_in_the_writing_response
        """
        bundle = self._right_application_and_docket()
        right_id = bundle["right"]["id"]
        get_success_data(
            api_client.submit_transfer_application(
                bundle["application"]["id"], read_right(right_id)["version"], ANALYST
            )
        )

        first_body = api_client.get_water_right(right_id, ANALYST).json()
        second_body = api_client.get_water_right(right_id, ANALYST).json()

        assert first_body["data"] == second_body["data"]
        assert first_body["data"]["transferable_af"] == pytest.approx(95.00, abs=0.01)
        assert_request_meta(first_body)
        assert_request_meta(second_body)

    def test_the_docket_counter_is_current_in_the_read_after_the_claim(self):
        """PRD §3.10: "Filing recomputes the docket's `claim_count` and bumps the
        docket's `version`."

        The counter sits on a different row from the one the write created, and it is
        nevertheless current in the very next read. `total_decreed_af` stays where the
        docket was born — PRD §3.10: "The docket opens in phase `OPEN_FOR_CLAIMS` with
        `claim_count`, `decreed_claim_count` and `total_decreed_af` all zeroed, and any
        of the five roles may read it to inspect its phase and rolled-up counters." —
        because it is "the sum of `decreed_af` over that docket's decreed claims, at 2
        decimal places" and filing decrees nothing.

        Design: Corner/consistency_model/consistency_immediate_derived_fields_are_current_in_the_writing_response
        """
        bundle = self._right_application_and_docket()
        docket_id = bundle["docket"]["id"]
        assert bundle["docket"]["claim_count"] == 0

        claim = file_claim(docket_id, bundle["right"]["id"], RECORDED_PRIORITY, 100.00)

        assert claim["filing_status"] == "FILED"
        docket = read_docket(docket_id)
        assert docket["claim_count"] == 1
        assert docket["decreed_claim_count"] == 0
        assert docket["total_decreed_af"] == pytest.approx(0.00, abs=0.01)
        assert read_docket(docket_id) == docket


class TestACascadeIsSettledBeforeTheResponseIsWritten:
    """PRD §3.6 — the resolve response is only the protest, yet three rows moved.

    One negotiation-track protest for 8.00 acre-feet stands against a published
    100.00 acre-foot application whose draft analysis reads a gross depletion of
    78.00. Resolving it is the last protest on the application, so the clearance
    cascade fires inside the same request that answers with the protest.
    """

    STIPULATED_OFFSET_AF = 8.00

    def _one_protest_under_negotiation(self):
        return setup_protested_application(
            requested_af=100.00,
            claimed_injury_af=8.00,
            clock=CLOCK,
            track="NEGOTIATION",
        )

    def test_the_parent_has_already_bubbled_up_by_the_very_next_call(self):
        """PRD §3.6: "Whichever route clears the last protest — a stipulation on either
        track, a dismissal, or a withdrawal — the same clearance cascade fires when
        `unresolved_protest_count` reaches exactly 0. The application auto-transitions
        `UNDER_PROTEST → READY_FOR_DECISION`; its `DRAFT` injury analysis moves to the
        terminal `FINALIZED`, freezing `gross_depletion_af`, `offset_af` and
        `net_injury_af`; `pending_review_count` on the right is decremented; and the
        versions of the protest, the application, the analysis and the right are all
        bumped."

        The write answers with the protest alone, so the application's transition and
        the analysis's freeze are only observable on the following reads — and they are
        observable there in full, with no intermediate state in which the counter has
        dropped while the parent still reads `UNDER_PROTEST`.

        Design: Corner/consistency_model/consistency_immediate_cascade_effects_are_visible_to_the_very_next_call
        """
        bundle = self._one_protest_under_negotiation()
        assert bundle["application"]["status"] == "UNDER_PROTEST"
        assert bundle["application"]["unresolved_protest_count"] == 1
        assert bundle["analysis"]["status"] == "DRAFT"

        protest = resolve_protest(
            bundle["protest"]["id"],
            "STIPULATE",
            stipulated_offset_af=self.STIPULATED_OFFSET_AF,
        )

        assert protest["status"] == "RESOLVED_STIPULATED"
        assert protest["stipulated_offset_af"] == pytest.approx(8.00, abs=0.01)
        application = read_application(bundle["application"]["id"])
        assert application["status"] == "READY_FOR_DECISION"
        assert application["unresolved_protest_count"] == 0
        assert application["version"] > bundle["application"]["version"]
        assert read_right(bundle["right"]["id"])["pending_review_count"] == 0

    def test_the_offset_is_already_folded_into_the_frozen_analysis(self):
        """PRD §3.6: "On the negotiation branch the protest moves `IN_NEGOTIATION →
        RESOLVED_STIPULATED`, the `stipulated_offset_af` is recorded, and the
        application's `DRAFT` injury analysis recomputes `offset_af` as the sum of
        stipulated offsets across all negotiation-track resolved protests and recomputes
        `net_injury_af` accordingly — a volumetric concession, and no condition is
        created."

        Both the recomputation and the freeze happen in that one request, so the very
        next read of the analysis — whether taken through the collection or the single
        row — already reads `FINALIZED` at 78.00 gross less 8.00 offset. PRD §3.5:
        "`net_injury_af` is then gross depletion less `offset_af` less
        `return_flow_credit_af`, floored at 0.00 by taking whichever of that difference
        and zero is larger, and rounded to 2 decimal places."

        Design: Corner/consistency_model/consistency_immediate_cascade_effects_are_visible_to_the_very_next_call
        """
        bundle = self._one_protest_under_negotiation()
        assert bundle["analysis"]["gross_depletion_af"] == pytest.approx(78.00, abs=0.01)

        resolve_protest(
            bundle["protest"]["id"],
            "STIPULATE",
            stipulated_offset_af=self.STIPULATED_OFFSET_AF,
        )

        listed, meta = validate_paginated(
            api_client.list_injury_analyses(bundle["application"]["id"], ANALYST)
        )
        assert meta["total_count"] == 1
        assert listed[0]["status"] == "FINALIZED"
        assert listed[0]["offset_af"] == pytest.approx(8.00, abs=0.01)
        assert listed[0]["net_injury_af"] == pytest.approx(70.00, abs=0.01)
        single = get_success_data(
            api_client.get_injury_analysis(bundle["analysis"]["id"], ANALYST)
        )
        assert single["status"] == "FINALIZED"
        assert single["gross_depletion_af"] == pytest.approx(78.00, abs=0.01)
        assert single["offset_af"] == pytest.approx(8.00, abs=0.01)
        assert single["net_injury_af"] == pytest.approx(70.00, abs=0.01)
        assert single["version"] > bundle["analysis"]["version"]
