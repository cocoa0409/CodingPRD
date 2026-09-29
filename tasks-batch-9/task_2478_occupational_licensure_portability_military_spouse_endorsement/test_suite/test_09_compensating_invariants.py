"""Two compensating actions that must restore an exact prior value rather than
approximate it: revoking a permit returns the fee balance to its pre-issuance figure
through an appended reversal, and revoking a credit award returns the hours pair to its
one-award reading with the conserved total intact."""

import pytest

from test_helpers import (
    ANALYST_HEADERS,
    APP_SUBMITTED,
    APP_UNDER_REVIEW,
    AWARD_AWARDED,
    AWARD_REVOKED,
    ENTRY_ASSESSMENT,
    ENTRY_PAYMENT,
    ENTRY_PERMIT_FEE,
    ENTRY_PERMIT_FEE_REVERSAL,
    ENTRY_WAIVER_CREDIT,
    MILITARY_VETERAN,
    PERMIT_ACTIVE,
    PERMIT_REVOKED,
    assert_application_fields,
    assert_hours_conserved,
    assert_instant_equals,
    assert_ledger_signature,
    assert_permit_fields,
    ledger_sum,
    validate_paginated,
)

WITHDRAWAL = "APPLICANT_WITHDREW"


@pytest.fixture
def bridged_and_fully_paid(setup):
    """A settled RN file under review whose only outstanding charge is the 6000-cent
    fee for the ACTIVE permit bridging its review."""
    profession = setup.profession()
    applicant = setup.applicant(full_name="Greta Lund", state_code="TX", residency_months=24)
    credential = setup.credential(
        applicant["id"],
        license_number="OK-70111",
        scope_elements=["ASSESS", "TREAT", "SUPERVISE"],
        practice_hours=1200,
        issued_at="2020-05-01T00:00:00Z",
    )
    application = setup.application(applicant["id"], profession["id"], credential["id"])
    setup.submit(application["id"], applicant["id"])
    setup.pay(application["id"], applicant["id"], 48000)
    setup.evaluation(application["id"], credential["id"])
    permit = setup.permit(application["id"], "2026-08-01T00:00:00Z")
    return {
        "ap_id": applicant["id"],
        "app_id": application["id"],
        "permit": permit,
    }


@pytest.fixture
def two_awards_off_one_service_record_pair(setup):
    """A veteran's submitted RN file carrying two AWARDED credit awards, one per
    verified MOS training record of 133 and 137 documented hours."""
    profession = setup.profession()
    applicant = setup.applicant(
        full_name="Sana Qureshi",
        state_code="TX",
        residency_months=24,
        military_status=MILITARY_VETERAN,
    )
    credential = setup.credential(
        applicant["id"],
        license_number="OK-70121",
        scope_elements=["ASSESS", "TREAT", "SUPERVISE"],
        practice_hours=1200,
        issued_at="2020-05-01T00:00:00Z",
    )
    first_record = setup.training_record(
        applicant["id"], documented_hours=133, source_document="JST-RN-133"
    )
    second_record = setup.training_record(
        applicant["id"], documented_hours=137, source_document="JST-RN-137"
    )
    application = setup.application(applicant["id"], profession["id"], credential["id"])
    setup.submit(application["id"], applicant["id"])
    first_award = setup.credit_award(application["id"], first_record["id"])
    second_award = setup.credit_award(application["id"], second_record["id"])
    return {
        "ap_id": applicant["id"],
        "app_id": application["id"],
        "tr2_id": second_record["id"],
        "aw1_id": first_award["id"],
        "aw2_id": second_award["id"],
    }


class TestPermitRevocationCompensation:
    def test_the_deputys_reason_code_is_copied_onto_the_permit_and_the_window_pulled_back(
        self, bridged_and_fully_paid, setup
    ):
        """PRD §3.8: "A `BoardDeputy` may revoke an `ACTIVE` permit directly, supplying
        a `reason_code` that is copied verbatim into the permit's
        `revocation_reason_code`; the same `ACTIVE → REVOKED` transition also fires
        automatically when the application leaves the reviewable set, in which case the
        reason is the literal `DISCIPLINARY_ACTION` for a good-standing cascade and the
        literal `APPLICATION_DENIED` for a denial cascade."  PRD §3.8: "However it is
        triggered, revocation sets `status` to `REVOKED`, sets `revoked_at` to the
        logical clock, truncates `expires_at` down to `revoked_at`, appends a
        `PERMIT_FEE_REVERSAL` entry whose `amount_cents` is the exact negative of the
        permit's frozen `permit_fee_cents`, recomputes the application's
        `fee_balance_cents` and increments both the permit's `version` and the
        application's `version`."

        Design: Difficulty/compensating_invariant/permit_revocation_restores_fee_balance_cents_exactly
        """
        env = bridged_and_fully_paid
        assert_permit_fields(
            env["permit"],
            status=PERMIT_ACTIVE,
            expires_at="2026-10-30T00:00:00Z",
            permit_fee_cents=6000,
            revoked_at=None,
            revocation_reason_code=None,
        )

        revoked = setup.revoke_permit(env["permit"]["id"], WITHDRAWAL)

        assert_permit_fields(
            revoked,
            status=PERMIT_REVOKED,
            revocation_reason_code=WITHDRAWAL,
            revoked_at="2026-08-01T00:00:00Z",
            expires_at="2026-08-01T00:00:00Z",
        )

    def test_the_reversal_returns_the_balance_to_its_pre_issuance_value(
        self, bridged_and_fully_paid, setup
    ):
        """PRD §2.10: "A `PERMIT_FEE` of some amount followed by a
        `PERMIT_FEE_REVERSAL` of exactly the negative of that amount returns
        `fee_balance_cents` to precisely its pre-issuance value, for any amount — the
        reversal is full, never prorated."

        Design: Difficulty/compensating_invariant/permit_revocation_restores_fee_balance_cents_exactly
        """
        env = bridged_and_fully_paid
        assert_application_fields(setup.read_application(env["app_id"]), fee_balance_cents=6000)

        setup.revoke_permit(env["permit"]["id"], WITHDRAWAL)

        assert_application_fields(setup.read_application(env["app_id"]), fee_balance_cents=0)

    def test_the_original_permit_fee_row_survives_the_reversal_untouched(
        self, bridged_and_fully_paid, setup
    ):
        """PRD §2.10: "There is no status filter on the sum and no notion of a voided
        entry, because entries are immutable; the read order of `created_at` ascending
        pins the audit trail but does not change the total."

        Design: Difficulty/compensating_invariant/permit_revocation_restores_fee_balance_cents_exactly
        """
        env = bridged_and_fully_paid
        setup.revoke_permit(env["permit"]["id"], WITHDRAWAL)

        ledger = setup.read_ledger(env["app_id"])
        assert_ledger_signature(
            ledger,
            [
                (ENTRY_ASSESSMENT, 48000),
                (ENTRY_WAIVER_CREDIT, 0),
                (ENTRY_PAYMENT, -48000),
                (ENTRY_PERMIT_FEE, 6000),
                (ENTRY_PERMIT_FEE_REVERSAL, -6000),
            ],
        )
        assert ledger[3]["amount_cents"] == 6000, "the charge was compensated, not edited away"
        assert ledger_sum(ledger) == 0

    def test_revoking_the_permit_does_not_push_the_application_out_of_review(
        self, bridged_and_fully_paid, setup
    ):
        """PRD §2.9: "Two events push an application out of that set involuntarily — a
        disciplinary record that destroys the applicant's good standing, and a denial —
        and both carry the same two-part cascade: every temporary permit of that
        application whose `status` is `ACTIVE` moves to `REVOKED`, and every review
        assignment of that application whose `status` is `ASSIGNED` moves to
        `RELEASED`."

        Design: Difficulty/compensating_invariant/permit_revocation_restores_fee_balance_cents_exactly
        """
        env = bridged_and_fully_paid
        setup.revoke_permit(env["permit"]["id"], WITHDRAWAL)

        assert_application_fields(
            setup.read_application(env["app_id"]),
            status=APP_UNDER_REVIEW,
            decided_at=None,
            decided_by_user_id=None,
        )


class TestCreditAwardRevocationCompensation:
    def test_each_service_record_is_rounded_before_it_enters_the_hours_sum(
        self, two_awards_off_one_service_record_pair, setup
    ):
        """PRD §3.7: "Each award's `awarded_hours` is the training record's
        `documented_hours` multiplied by the factor for its `category` — 0.75 for
        `MOS_TRAINING`, 0.40 for `FIELD_EXPERIENCE`, and 0.90 for
        `JOINT_SERVICE_TRANSCRIPT` — with the product rounded half up to one decimal
        place, and that already-rounded value is what the award stores."  PRD §3.7:
        "Summing the raw unrounded products and rounding once at the end is a different
        answer and is not permitted."

        Design: Difficulty/compensating_invariant/credit_award_revocation_conserves_requirement_hours_total
        """
        env = two_awards_off_one_service_record_pair

        assert setup.read_credit_award(env["aw1_id"])["awarded_hours"] == 99.8
        assert setup.read_credit_award(env["aw2_id"])["awarded_hours"] == 102.8
        assert_application_fields(
            setup.read_application(env["app_id"]),
            status=APP_SUBMITTED,
            requirement_hours_satisfied=202.6,
            requirement_hours_remaining=37.4,
        )

    def test_the_hours_pair_stays_conserved_across_the_revocation(
        self, two_awards_off_one_service_record_pair, setup
    ):
        """PRD §3.7: "`requirement_hours_remaining` is then the profession's
        `requirement_hours_total` less `requirement_hours_satisfied`, and the pair is a
        conserved quantity: satisfied plus remaining always equals the profession's
        total exactly, and remaining is never negative."

        Design: Difficulty/compensating_invariant/credit_award_revocation_conserves_requirement_hours_total
        """
        env = two_awards_off_one_service_record_pair
        assert_hours_conserved(setup.read_application(env["app_id"]), 240.0)

        setup.revoke_credit_award(env["aw2_id"])

        assert_hours_conserved(setup.read_application(env["app_id"]), 240.0)

    def test_a_revoked_award_leaves_the_sum_and_the_surviving_award_alone(
        self, two_awards_off_one_service_record_pair, setup
    ):
        """PRD §3.7: "It drives `AWARDED → REVOKED`, sets `revoked_at` to the logical
        clock, and recomputes `requirement_hours_satisfied` and
        `requirement_hours_remaining` over the remaining `AWARDED` rows only —
        `REVOKED` rows leave the sum entirely — incrementing both the award's `version`
        and the application's `version`."

        Design: Difficulty/compensating_invariant/credit_award_revocation_conserves_requirement_hours_total
        """
        env = two_awards_off_one_service_record_pair
        revoked = setup.revoke_credit_award(env["aw2_id"])

        assert revoked["status"] == AWARD_REVOKED
        assert_instant_equals(
            revoked["revoked_at"], "2026-08-01T00:00:00Z", "credit award.revoked_at"
        )
        survivor = setup.read_credit_award(env["aw1_id"])
        assert survivor["status"] == AWARD_AWARDED
        assert survivor["awarded_hours"] == 99.8
        assert_application_fields(
            setup.read_application(env["app_id"]),
            requirement_hours_satisfied=99.8,
            requirement_hours_remaining=140.2,
        )

    def test_the_revocation_touches_neither_the_service_record_nor_the_money(
        self, api, two_awards_off_one_service_record_pair, setup
    ):
        """PRD §3.7: "Revocation is the compensating action, available to a
        `LicensingAnalyst` while the award is still `AWARDED` and the application is in
        `SUBMITTED`, `UNDER_REVIEW` or `DEFICIENT`."  PRD §2.10: "Money moves only by
        appending a `FeeLedgerEntry`."

        Design: Difficulty/compensating_invariant/credit_award_revocation_conserves_requirement_hours_total
        """
        env = two_awards_off_one_service_record_pair
        assert_application_fields(setup.read_application(env["app_id"]), fee_balance_cents=24000)

        setup.revoke_credit_award(env["aw2_id"])

        records, _meta = validate_paginated(
            api.list_training_records(env["ap_id"], ANALYST_HEADERS, {"limit": 100})
        )
        second = next(row for row in records if row["id"] == env["tr2_id"])
        assert second["documented_hours"] == 137
        assert second["verified"] is True
        assert_application_fields(setup.read_application(env["app_id"]), fee_balance_cents=24000)
