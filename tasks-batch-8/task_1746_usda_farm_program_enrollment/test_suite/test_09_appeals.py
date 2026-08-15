"""Appeals: filing side effect, the remand-recertify cycle, and reversal
payment-split conservation (PRD §3.10, §3.8)."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_appeal,
    setup_appeal_at_committee,
    setup_certified_enrollment,
    setup_payment_computed_enrollment,
    validate_success,
)


@pytest.fixture
def specialist(county_specialist_headers):
    return county_specialist_headers


class TestAppealFilingSideEffect:
    def test_appeal_filed_transitions_enrollment_on_appeal(self, api, specialist):
        """PRD §3.10: "A producer files an appeal against an enrollment
        determination by supplying the `farm_id`, the `enrollment_id` being
        appealed, a `ground_code` of `FACTUAL_ERROR`, `PROCEDURAL_ERROR`,
        `MISAPPLICATION_OF_RULE`, or `NEW_EVIDENCE`, and the
        `filed_by_producer_id` of the appellant. The enrollment must be in
        `CERTIFIED` or `PAYMENT_COMPUTED`; filing moves it to `ON_APPEAL`."

        Design: Corner/state_machines/appeal_filed_transitions_enrollment_on_appeal
        """
        ctx = setup_certified_enrollment()
        resp = api.file_appeal(
            {
                "farm_id": ctx["farm"]["id"],
                "enrollment_id": ctx["enrollment"]["id"],
                "ground_code": "NEW_EVIDENCE",
                "filed_by_producer_id": ctx["producer"]["id"],
            },
            ctx["producer_headers"],
        )
        appeal = validate_success(resp, 201)
        assert_appeal(appeal)
        assert appeal["appeal_status"] == "FILED"
        enrollment = validate_success(
            api.get_enrollment(ctx["enrollment"]["id"], specialist), 200
        )
        assert enrollment["enrollment_status"] == "ON_APPEAL", (
            f"filing an appeal must move the enrollment to ON_APPEAL, got "
            f"{enrollment['enrollment_status']}"
        )


class TestRemandRecertifyCycle:
    def _remanded(self, api):
        ctx = setup_payment_computed_enrollment(
            compute_inputs={"national_my_price": 3.50}
        )
        appeal = setup_appeal_at_committee(ctx, ground_code="FACTUAL_ERROR")
        remanded = api.remand_appeal(
            appeal["id"],
            {"remand_instructions": "Re-verify yield evidence"},
            ctx["committee_headers"],
        )
        validate_success(remanded, 200)
        return ctx, appeal

    def test_remand_moves_enrollment_to_remanded(self, api, specialist):
        """PRD §3.10: "Remanding moves the appeal to `REMANDED` and the
        enrollment to `REMANDED`; the remand request carries
        `remand_instructions`."

        Design: Difficulty/non_linear_state_machine/enrollment_remand_recertify_cycle
        """
        ctx, appeal = self._remanded(api)
        appeal_after = validate_success(api.get_appeal(appeal["id"], specialist), 200)
        assert appeal_after["appeal_status"] == "REMANDED"
        enrollment = validate_success(
            api.get_enrollment(ctx["enrollment"]["id"], specialist), 200
        )
        assert enrollment["enrollment_status"] == "REMANDED", (
            f"remand must move the enrollment to REMANDED, got "
            f"{enrollment['enrollment_status']}"
        )

    def test_recertify_returns_remanded_enrollment_to_certified(self, api, specialist):
        """PRD §3.10: "A `REMANDED` enrollment may be recertified by the
        committee — the request carries corrected election or yield data —
        moving it back to `CERTIFIED` with its pins re-evaluated. From there
        the cycle can repeat: a later appeal re-opens the previously remanded
        case, and its `remands_appeal_id` records which earlier appeal it
        follows."

        The enrollment traverses CERTIFIED -> ON_APPEAL -> REMANDED ->
        CERTIFIED, a true revision cycle.

        Design: Difficulty/non_linear_state_machine/enrollment_remand_recertify_cycle
        """
        ctx, _appeal = self._remanded(api)
        resp = api.recertify_enrollment(
            ctx["enrollment"]["id"], ctx["committee_headers"]
        )
        enrollment = validate_success(resp, 200)
        assert enrollment["enrollment_status"] == "CERTIFIED", (
            f"recertify must return the enrollment to CERTIFIED, got "
            f"{enrollment['enrollment_status']}"
        )


class TestReversalPaymentSplitConservation:
    def test_original_payment_split_conserves_post_limitation_gross(
        self, api, specialist
    ):
        """PRD §3.8: "The `sequestration_cents` amount is the post-limitation
        payment multiplied by 5.7 percent, rounded half-up to two decimal
        places. The net `computed_payment_cents` is the post-limitation payment
        minus the sequestration, rounded half-up to two decimal places."

        PLC base 0.60 x 180.0 x 100 x 0.85 = 9180.00 (below the $125,000 cap):
        sequestration round(9180 x 0.057, 2) = 523.26 -> 52326; net 8656.74 ->
        865674; the split conserves the post-limitation gross:
        865674 + 52326 = 918000.

        Design: Difficulty/compensating_invariant/appeal_reverse_conserves_gross_minus_sequestration
        """
        ctx = setup_payment_computed_enrollment(
            compute_inputs={"national_my_price": 3.50}
        )
        enrollment = ctx["enrollment"]
        assert enrollment["computed_payment_cents"] == 865674
        assert enrollment["sequestration_cents"] == 52326
        gross_cents = (
            enrollment["computed_payment_cents"] + enrollment["sequestration_cents"]
        )
        assert gross_cents == 918000, (
            f"net + sequestration must reconstruct the 9180.00 gross, got "
            f"{gross_cents} cents"
        )

    def test_reversal_keeps_net_plus_sequestration_split_consistent(
        self, api, specialist
    ):
        """PRD §3.10: "Reversing — optionally carrying `corrected_payment_cents`
        — moves the appeal to `REVERSED` (terminal) and recomputes the
        enrollment's payment per the committee's factual correction."
        PRD §3.8: "The `sequestration_cents` amount is the post-limitation
        payment multiplied by 5.7 percent, rounded half-up to two decimal
        places. The net `computed_payment_cents` is the post-limitation payment
        minus the sequestration, rounded half-up to two decimal places. Both
        fields are set on the enrollment by the computation."

        With no corrected payment supplied, the reversal cannot introduce new
        facts; the split computed earlier (865674 + 52326 = 918000) must remain
        the conserved outcome.

        Design: Difficulty/compensating_invariant/appeal_reverse_conserves_gross_minus_sequestration
        """
        ctx = setup_payment_computed_enrollment(
            compute_inputs={"national_my_price": 3.50}
        )
        appeal = setup_appeal_at_committee(ctx, ground_code="MISAPPLICATION_OF_RULE")
        resp = api.reverse_appeal(appeal["id"], {}, ctx["committee_headers"])
        reversed_appeal = validate_success(resp, 200)
        assert reversed_appeal["appeal_status"] == "REVERSED", (
            f"reversal must move the appeal to REVERSED, got "
            f"{reversed_appeal['appeal_status']}"
        )
        enrollment = validate_success(
            api.get_enrollment(ctx["enrollment"]["id"], specialist), 200
        )
        gross_cents = (
            enrollment["computed_payment_cents"] + enrollment["sequestration_cents"]
        )
        assert gross_cents == 918000, (
            f"the gross = net + sequestration identity must survive reversal "
            f"without drift, got {gross_cents} cents"
        )
