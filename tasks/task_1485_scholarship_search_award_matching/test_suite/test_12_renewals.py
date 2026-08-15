"""Renewal evaluations: thresholds, appeal cycle, caps, and decision gates."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_renewal_payload,
    get_award,
    get_success_data,
    make_student_headers,
    setup_pending_renewal,
    validate_error,
    validate_success,
)

COORD = TEST_USERS["coordinator_headers"]


class TestRenewalGpaThreshold:
    """Renewable program with renewal_min_gpa 250 and renewal_min_credits 12;
    the SAME evaluation walks fail -> appeal -> pass."""

    def test_one_hundredth_below_threshold_fails(self, api):
        """PRD §3.8: "The renewal threshold check is inclusive on both legs:
        the registrar GPA must be at least the program's
        `renewal_min_gpa_hundredths` and the registrar credits at least the
        program's `renewal_min_credits` — a figure exactly at the threshold
        passes, one below it fails."
        PRD §3.8: "the student or a coordinator may appeal a
        `VERIFIED_INELIGIBLE` evaluation (otherwise `ERR_INVALID_STATE`) with
        an `appeal_note` present (otherwise `ERR_VALIDATION`), moving it to
        `APPEALED` for re-verification."

        Design: Difficulty/boundary_precision_check/renewal_gpa_threshold_250_pass_249_fail
        """
        ctx = setup_pending_renewal()
        evaluation_id = ctx["evaluation"]["id"]

        failed = validate_success(
            api.verify_renewal(
                evaluation_id,
                {"registrar_gpa_hundredths": 249, "registrar_credits": 14},
                COORD,
            )
        )
        assert failed["status"] == "VERIFIED_INELIGIBLE", "249 < 250 fails"

        appealed = validate_success(
            api.appeal_renewal(
                evaluation_id,
                {"appeal_note": "Registrar issued a grade correction"},
                make_student_headers(ctx["students"][0]["id"]),
            )
        )
        assert appealed["status"] == "APPEALED"

    def test_exactly_at_threshold_passes_after_appeal(self, api):
        """PRD §3.8: "a figure exactly at the threshold passes, one below it
        fails."
        PRD §3.8: "Verification is allowed from `PENDING` and again from
        `APPEALED`, where the registrar values are overwritten with the new
        figures."
        PRD §3.8: "A pass moves the evaluation to `VERIFIED_ELIGIBLE`, a miss
        to `VERIFIED_INELIGIBLE`; either way the registrar values are stored
        and the verifier's `X-User-ID` is recorded as `verified_by_user_id`."

        Design: Difficulty/boundary_precision_check/renewal_gpa_threshold_250_pass_249_fail
        """
        ctx = setup_pending_renewal()
        evaluation_id = ctx["evaluation"]["id"]
        get_success_data(
            api.verify_renewal(
                evaluation_id,
                {"registrar_gpa_hundredths": 249, "registrar_credits": 14},
                COORD,
            )
        )
        get_success_data(
            api.appeal_renewal(
                evaluation_id,
                {"appeal_note": "Registrar issued a grade correction"},
                COORD,
            )
        )

        passed = validate_success(
            api.verify_renewal(
                evaluation_id,
                {"registrar_gpa_hundredths": 250, "registrar_credits": 14},
                COORD,
            )
        )
        assert passed["status"] == "VERIFIED_ELIGIBLE", "250 >= 250 passes"
        assert passed["registrar_gpa_hundredths"] == 250, (
            "registrar values overwritten with the new figures"
        )


class TestRenewalCapsAndDecisionGates:
    def test_max_renewals_reached(self, api):
        """PRD §3.8: "A `RENEW` decision requires the evaluation to be
        `VERIFIED_ELIGIBLE` — a mismatched decision is refused with
        `ERR_RENEWAL_NOT_ELIGIBLE` — and requires `renewal_count` still below
        `max_renewals` (otherwise `ERR_MAX_RENEWALS_REACHED`); on success the
        evaluation becomes `RENEWED`, `decided_at` is stamped, the award's
        `renewal_count` increases by one, the award's `amount_cents` grows by
        the program's `award_amount_cents` as the next-year tranche, the
        fund's reservation is recomputed, and the stacking recompute of §3.6
        runs and may auto-create adjustments."
        PRD §3.8: "the award's `renewal_count` must still be below the
        program's `max_renewals` (otherwise `ERR_MAX_RENEWALS_REACHED`)".

        Design: Corner/state_machines/renewal_max_renewals_reached
        """
        ctx = setup_pending_renewal(
            amount_cents=300000,
            program_overrides={"max_renewals": 1, "award_amount_cents": 300000},
        )
        evaluation_id = ctx["evaluation"]["id"]
        award_id = ctx["award"]["id"]
        get_success_data(
            api.verify_renewal(
                evaluation_id,
                {"registrar_gpa_hundredths": 300, "registrar_credits": 14},
                COORD,
            )
        )

        renewed = validate_success(
            api.finalize_renewal(evaluation_id, {"decision": "RENEW"}, COORD)
        )
        assert renewed["status"] == "RENEWED"
        assert renewed["decided_at"] is not None

        award = get_award(award_id)
        assert award["renewal_count"] == 1
        assert award["amount_cents"] == 600000, "300000 tranche added"

        # renewal_count 1 == max_renewals 1: a second evaluation is refused.
        resp = api.create_renewal_evaluation(
            create_renewal_payload(
                award_id, term_label="2028-SPRING",
                reported_gpa_hundredths=300, reported_credits=14,
            ),
            COORD,
        )
        validate_error(resp, ApiErrorId.ERR_MAX_RENEWALS_REACHED)

    def test_duplicate_open_evaluation_rejected(self, api):
        """PRD §3.8: "no other evaluation for the award may sit in a
        non-terminal status — anything other than `RENEWED` or `LAPSED` —
        otherwise `ERR_DUPLICATE_RENEWAL_EVALUATION`."

        Design: Corner/state_machines/renewal_duplicate_open_evaluation_rejected
        """
        ctx = setup_pending_renewal()
        award_id = ctx["award"]["id"]
        assert ctx["evaluation"]["status"] == "PENDING"

        resp = api.create_renewal_evaluation(
            create_renewal_payload(
                award_id, reported_gpa_hundredths=310, reported_credits=15
            ),
            COORD,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_RENEWAL_EVALUATION)

    def test_finalize_decision_must_match_verified_status(self, api):
        """PRD §3.8: "A `RENEW` decision requires the evaluation to be
        `VERIFIED_ELIGIBLE` — a mismatched decision is refused with
        `ERR_RENEWAL_NOT_ELIGIBLE`".
        PRD §3.8: "A `LAPSE` decision requires `VERIFIED_INELIGIBLE`
        (otherwise `ERR_RENEWAL_NOT_ELIGIBLE`); on success the evaluation
        becomes `LAPSED`, `decided_at` is stamped, and the award is not
        renewable further."

        Design: Corner/state_machines/renewal_finalize_decision_status_mismatch
        """
        ctx = setup_pending_renewal()
        evaluation_id = ctx["evaluation"]["id"]
        failed = validate_success(
            api.verify_renewal(
                evaluation_id,
                {"registrar_gpa_hundredths": 240, "registrar_credits": 14},
                COORD,
            )
        )
        assert failed["status"] == "VERIFIED_INELIGIBLE"

        # RENEW against an ineligible verdict is refused.
        resp = api.finalize_renewal(evaluation_id, {"decision": "RENEW"}, COORD)
        validate_error(resp, ApiErrorId.ERR_RENEWAL_NOT_ELIGIBLE)

        # LAPSE matches the verdict and succeeds.
        lapsed = validate_success(
            api.finalize_renewal(evaluation_id, {"decision": "LAPSE"}, COORD)
        )
        assert lapsed["status"] == "LAPSED"
        assert lapsed["decided_at"] is not None
