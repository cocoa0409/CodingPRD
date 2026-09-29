"""Statutory validation corners: one unit outside every declared bound gives
that bound its own error code, the same bounds at their inclusive extremes are
all accepted in one chain, the lifetime late-fee cap survives successive sweeps
and a waiver, a per-state flag switches the licensing gate on and off, and the
down-payment ratio cannot fire until the premium basis behind it exists.
"""

from datetime import datetime

from test_helpers import (
    ApiErrorId,
    add_on_finance_charge_cents,
    assert_installments_sum,
    factories,
    fixtures,
    late_fee_cents,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.test_users import (
    ANALYST_ORIGIN,
    COMPLIANCE,
    COMPLIANCE_WAIVER,
    make_producer_agent_headers,
)


def _as_instant(stamp: str) -> datetime:
    """Parse an ISO 8601 UTC stamp with or without fractional seconds."""
    return datetime.strptime(
        stamp.replace("Z", "+0000"),
        "%Y-%m-%dT%H:%M:%S.%f%z" if "." in stamp else "%Y-%m-%dT%H:%M:%S%z",
    )


def _tx_regime_context(api):
    """Clock at 2026-08-15, the canonical TX regime with an effective licence
    and the three counterparties.

    At that clock the first-installment window is 2026-08-16 through 2026-10-14
    inclusive, which is what makes the one-unit probes on either side legible.
    """
    fixtures.set_clock(api, "2026-08-15T00:00:00Z")
    ctx = fixtures.create_state_regime(
        api,
        rule_payload=factories.tx_state_rate_rule(),
        license_payload=factories.license_payload(license_number="PFC-TX-001"),
    )
    ctx.update(
        fixtures.create_parties(
            api,
            insured_payload=factories.insured(
                legal_name="Cascade Logistics Inc", email="ap@cascade.example"
            ),
        )
    )
    return ctx


class TestEachStatutoryGateMapsToItsOwnCode:
    """Seven bounds violated one at a time, each from an otherwise legal
    request, each answering with its own code."""

    def _submitted(self, api):
        """One legal note awaiting attestations, plus the regime it lives under."""
        ctx = _tx_regime_context(api)
        bundle = fixtures.draft_agreement(
            api,
            ctx,
            policies=[
                factories.financed_policy(
                    ctx["insurer_id"], policy_number="MC-VE-1"
                )
            ],
            first_installment_due_date="2026-10-14",
        )
        bundle["submitted"] = validate_success(
            api.submit_agreement(bundle["agreement_id"], ANALYST_ORIGIN), 200
        )
        return bundle

    def _drafted(self, api):
        """One legal note still in DRAFT, so further attachments are admissible."""
        ctx = _tx_regime_context(api)
        return fixtures.draft_agreement(
            api,
            ctx,
            policies=[
                factories.financed_policy(
                    ctx["insurer_id"], policy_number="MC-VE-1"
                )
            ],
            first_installment_due_date="2026-10-14",
        )

    def _legal_agreement_payload(self, bundle, **overrides):
        # The legal due date is a default the caller may override, not a fixed
        # keyword, so a test perturbing that one field does not collide with it.
        terms = {"first_installment_due_date": "2026-10-14"}
        terms.update(overrides)
        return factories.agreement(
            bundle["insured_id"],
            bundle["agent_id"],
            bundle["rule_id"],
            **terms,
        )

    def test_a_second_regime_for_the_same_state_is_a_conflict(self, api):
        """Every other field of the second regime differs and it still collides.

        The PRD states: "A second attempt to register the same `state_code` is
        refused with `ERR_DUPLICATE_STATE_RULE` (HTTP 409), because a state has
        exactly one rate regime."

        Design: Corner/validations/violation_to_error_each_statutory_and_temporal_gate_maps_to_its_own_code
        """
        bundle = self._submitted(api)
        assert bundle["submitted"]["status"] == "PENDING_VERIFICATION"

        validate_error(
            api.create_state_rate_rule(
                factories.state_rate_rule(
                    "TX",
                    finance_charge_method="SIMPLE_INTEREST",
                    max_annual_rate_bps=1200,
                    max_service_fee_cents=1000,
                    min_down_payment_bps=2000,
                    max_term_months=8,
                    late_fee_bps=400,
                    late_fee_min_cents=400,
                    late_fee_max_cents=8000,
                    grace_period_days=7,
                    noic_notice_days=15,
                    unearned_premium_method="SHORT_RATE",
                    short_rate_penalty_bps=500,
                    rebate_method="ACTUARIAL",
                    max_late_fees_per_agreement=2,
                ),
                COMPLIANCE,
            ),
            ApiErrorId.DUPLICATE_STATE_RULE.value,
            409,
        )

    def test_one_month_past_the_statutory_term_has_its_own_code(self, api):
        """installment_count 11 against max_term_months 10.

        The PRD states: "The regime must be licensed if it demands a license;
        the named agency must be `ACTIVE`; `installment_count` must not exceed
        the regime's `max_term_months`, or the request fails with
        `ERR_TERM_EXCEEDS_STATE_MAXIMUM` (HTTP 422); and `service_fee_cents`
        must not exceed the regime's `max_service_fee_cents`, or the request
        fails with `ERR_SERVICE_FEE_ABOVE_CAP` (HTTP 422)."

        Design: Corner/validations/violation_to_error_each_statutory_and_temporal_gate_maps_to_its_own_code
        """
        bundle = self._submitted(api)
        assert bundle["rule"]["max_term_months"] == 10

        validate_error(
            api.create_agreement(
                self._legal_agreement_payload(bundle, installment_count=11),
                ANALYST_ORIGIN,
            ),
            ApiErrorId.TERM_EXCEEDS_STATE_MAXIMUM.value,
            422,
        )

    def test_one_cent_past_the_service_fee_cap_has_its_own_code(self, api):
        """service_fee_cents 2001 against a 2000 ceiling.

        The PRD states: "The regime must be licensed if it demands a license;
        the named agency must be `ACTIVE`; `installment_count` must not exceed
        the regime's `max_term_months`, or the request fails with
        `ERR_TERM_EXCEEDS_STATE_MAXIMUM` (HTTP 422); and `service_fee_cents`
        must not exceed the regime's `max_service_fee_cents`, or the request
        fails with `ERR_SERVICE_FEE_ABOVE_CAP` (HTTP 422)."

        Design: Corner/validations/violation_to_error_each_statutory_and_temporal_gate_maps_to_its_own_code
        """
        bundle = self._submitted(api)
        assert bundle["rule"]["max_service_fee_cents"] == 2000

        validate_error(
            api.create_agreement(
                self._legal_agreement_payload(bundle, service_fee_cents=2001),
                ANALYST_ORIGIN,
            ),
            ApiErrorId.SERVICE_FEE_ABOVE_CAP.value,
            422,
        )

    def test_both_ends_of_the_first_due_window_share_one_code(self, api):
        """One day past clock plus 60, and the clock date itself.

        The PRD states: "A date on the clock date itself, or 61 days out, is
        refused with `ERR_INVALID_FIRST_DUE_DATE` (HTTP 422); a date exactly 60
        days out is accepted."

        Design: Corner/validations/violation_to_error_each_statutory_and_temporal_gate_maps_to_its_own_code
        """
        bundle = self._submitted(api)

        validate_error(
            api.create_agreement(
                self._legal_agreement_payload(
                    bundle, first_installment_due_date="2026-10-15"
                ),
                ANALYST_ORIGIN,
            ),
            ApiErrorId.INVALID_FIRST_DUE_DATE.value,
            422,
        )
        validate_error(
            api.create_agreement(
                self._legal_agreement_payload(
                    bundle, first_installment_due_date="2026-08-15"
                ),
                ANALYST_ORIGIN,
            ),
            ApiErrorId.INVALID_FIRST_DUE_DATE.value,
            422,
        )

    def test_both_malformed_policy_terms_share_one_code(self, api):
        """A minimum earned window longer than the term, and a backwards term.

        The PRD states: "The coverage interval is half-open — the effective date
        is inside the term and the expiration date is the exclusive upper bound
        — the expiration date must be strictly after the effective date and no
        more than 730 days after it, and `min_earned_days` must not exceed the
        term length in days; a violation of the term shape yields
        `ERR_INVALID_POLICY_TERM` (HTTP 422)."

        Design: Corner/validations/violation_to_error_each_statutory_and_temporal_gate_maps_to_its_own_code
        """
        # The note stays in DRAFT: §2.10 ranks the agreement-status gate (11)
        # ahead of the policy-term gate (31), so attaching onto an already
        # submitted note would report ERR_AGREEMENT_STATE_INVALID instead.
        bundle = self._drafted(api)

        validate_error(
            api.attach_policy(
                bundle["agreement_id"],
                factories.financed_policy(
                    bundle["insurer_id"],
                    policy_number="MC-VE-2",
                    gross_premium_cents=400000,
                    min_earned_days=400,
                ),
                ANALYST_ORIGIN,
            ),
            ApiErrorId.INVALID_POLICY_TERM.value,
            422,
        )
        validate_error(
            api.attach_policy(
                bundle["agreement_id"],
                factories.financed_policy(
                    bundle["insurer_id"],
                    policy_number="MC-VE-3",
                    gross_premium_cents=400000,
                    expiration_date="2026-08-01",
                ),
                ANALYST_ORIGIN,
            ),
            ApiErrorId.INVALID_POLICY_TERM.value,
            422,
        )

    def test_one_cent_past_the_variance_tolerance_has_its_own_code(self, api):
        """750001 against a quote of 600000 overshoots the quarter by one cent.

        The PRD states: "Equality is accepted, so a correction of exactly one
        quarter above or below the quote passes and one cent further out is
        refused with `ERR_PREMIUM_VARIANCE_EXCEEDED` (HTTP 422)."

        Design: Corner/validations/violation_to_error_each_statutory_and_temporal_gate_maps_to_its_own_code
        """
        bundle = self._submitted(api)
        assert abs(750001 - 600000) * 10000 > 600000 * 2500, (
            "the corrected premium sits exactly one cent outside the tolerance"
        )

        validate_error(
            api.create_verification(
                bundle["policy_id"],
                factories.corrected_verification(
                    750001, note="endorsed upward at bind"
                ),
                bundle["insurer_headers"],
            ),
            ApiErrorId.PREMIUM_VARIANCE_EXCEEDED.value,
            422,
        )

    def test_one_day_of_clock_rewind_has_its_own_code(self, api):
        """The logical clock refuses to go backwards at all.

        The PRD states: "The clock is monotonic: a supplied instant earlier than
        the current value is refused with `ERR_CLOCK_REWIND` (HTTP 422), while
        an instant equal to the current value is accepted."

        Design: Corner/validations/violation_to_error_each_statutory_and_temporal_gate_maps_to_its_own_code
        """
        self._submitted(api)

        validate_error(
            api.set_clock("2026-08-14T00:00:00Z", ANALYST_ORIGIN),
            ApiErrorId.CLOCK_REWIND.value,
            422,
        )
        echoed = validate_success(
            api.set_clock("2026-08-15T00:00:00Z", ANALYST_ORIGIN), 200
        )
        # Compared as an instant rather than as a byte string: the PRD fixes the
        # instant that must be echoed, but not whether `current_utc` carries the
        # fractional-second digits, so the digits are not asserted here.
        assert _as_instant(echoed["current_utc"]) == _as_instant(
            "2026-08-15T00:00:00Z"
        ), "an instant equal to the current value is still accepted"

    def test_none_of_the_nine_refusals_wrote_anything(self, api):
        """Only the legal setup rows survive the whole violation sweep.

        The PRD states: "A successful attachment stamps the policy
        `PENDING_VERIFICATION`, sets `carried_over` to false, provisionally sets
        `financed_premium_cents` equal to `gross_premium_cents`, increments the
        agreement's `policy_count` and advances the agreement's `version`."

        Design: Corner/validations/violation_to_error_each_statutory_and_temporal_gate_maps_to_its_own_code
        """
        bundle = self._submitted(api)

        for payload in (
            self._legal_agreement_payload(bundle, installment_count=11),
            self._legal_agreement_payload(bundle, service_fee_cents=2001),
            self._legal_agreement_payload(
                bundle, first_installment_due_date="2026-10-15"
            ),
        ):
            api.create_agreement(payload, ANALYST_ORIGIN)
        api.attach_policy(
            bundle["agreement_id"],
            factories.financed_policy(
                bundle["insurer_id"], policy_number="MC-VE-2", min_earned_days=400
            ),
            ANALYST_ORIGIN,
        )
        api.create_verification(
            bundle["policy_id"],
            factories.corrected_verification(750001),
            bundle["insurer_headers"],
        )

        _, agreement_meta = validate_paginated(
            api.list_agreements(
                COMPLIANCE, {"state_rule_id": bundle["rule_id"], "limit": 50}
            )
        )
        assert agreement_meta["total_count"] == 1, (
            "only the legal setup note exists under this regime"
        )
        _, policy_meta = validate_paginated(
            api.list_policies(
                COMPLIANCE, {"agreement_id": bundle["agreement_id"], "limit": 50}
            )
        )
        assert policy_meta["total_count"] == 1
        _, verification_meta = validate_paginated(
            api.list_verifications(bundle["policy_id"], COMPLIANCE, {"limit": 50})
        )
        assert verification_meta["total_count"] == 0


class TestEveryStatutoryLimitAtItsLegalExtremeIsAccepted:
    """The mirror image: five inclusive bounds all sitting exactly on their
    limit in one chain that must run to ACTIVE."""

    def _created(self, api):
        """A note at the extreme of both creation caps and of the due window."""
        ctx = _tx_regime_context(api)
        bundle = dict(ctx)
        bundle["agreement"] = validate_success(
            api.create_agreement(
                factories.agreement(
                    ctx["insured_id"],
                    ctx["agent_id"],
                    ctx["rule_id"],
                    down_payment_cents=150000,
                    service_fee_cents=2000,
                    installment_count=10,
                    first_installment_due_date="2026-10-14",
                ),
                ANALYST_ORIGIN,
            ),
            201,
        )
        bundle["agreement_id"] = bundle["agreement"]["id"]
        return bundle

    def _with_policy(self, api):
        """The extreme note carrying a policy whose earned window equals its term."""
        bundle = self._created(api)
        bundle["policy"] = validate_success(
            api.attach_policy(
                bundle["agreement_id"],
                factories.financed_policy(
                    bundle["insurer_id"],
                    policy_number="MC-SP-1",
                    min_earned_days=365,
                ),
                ANALYST_ORIGIN,
            ),
            201,
        )
        bundle["policy_id"] = bundle["policy"]["id"]
        return bundle

    def _submitted(self, api):
        bundle = self._with_policy(api)
        bundle["submitted"] = validate_success(
            api.submit_agreement(bundle["agreement_id"], ANALYST_ORIGIN), 200
        )
        return bundle

    def _attested(self, api):
        """Both parties correct the premium to exactly the tolerance limit."""
        bundle = self._submitted(api)
        payload = factories.corrected_verification(
            750000, note="audited payroll exposure raised the premium"
        )
        bundle["insurer_verification"] = validate_success(
            api.create_verification(
                bundle["policy_id"], payload, bundle["insurer_headers"]
            ),
            201,
        )
        bundle["agent_verification"] = validate_success(
            api.create_verification(
                bundle["policy_id"],
                factories.corrected_verification(
                    750000, note="agency agrees with the audited figure"
                ),
                bundle["agent_headers"],
            ),
            201,
        )
        return bundle

    def _activated(self, api):
        bundle = self._attested(api)
        bundle["activated"] = validate_success(
            api.activate_agreement(bundle["agreement_id"], ANALYST_ORIGIN), 200
        )
        return bundle

    def test_both_creation_caps_are_inclusive(self, api):
        """A term equal to the maximum and a fee equal to the ceiling are legal.

        The PRD states: "The regime must be licensed if it demands a license;
        the named agency must be `ACTIVE`; `installment_count` must not exceed
        the regime's `max_term_months`, or the request fails with
        `ERR_TERM_EXCEEDS_STATE_MAXIMUM` (HTTP 422); and `service_fee_cents`
        must not exceed the regime's `max_service_fee_cents`, or the request
        fails with `ERR_SERVICE_FEE_ABOVE_CAP` (HTTP 422)."

        Design: Corner/validations/satisfaction_to_pass_every_statutory_limit_at_its_legal_extreme_is_accepted
        """
        bundle = self._created(api)

        assert bundle["agreement"]["status"] == "DRAFT"
        assert (
            bundle["agreement"]["installment_count"]
            == bundle["rule"]["max_term_months"]
            == 10
        )
        assert (
            bundle["agreement"]["service_fee_cents"]
            == bundle["rule"]["max_service_fee_cents"]
            == 2000
        )

    def test_a_first_due_date_exactly_sixty_days_out_is_accepted(self, api):
        """The upper bound of the window closes on the sixtieth day, inclusive.

        The PRD states: "A date on the clock date itself, or 61 days out, is
        refused with `ERR_INVALID_FIRST_DUE_DATE` (HTTP 422); a date exactly 60
        days out is accepted."

        Design: Corner/validations/satisfaction_to_pass_every_statutory_limit_at_its_legal_extreme_is_accepted
        """
        bundle = self._created(api)

        assert bundle["agreement"]["first_installment_due_date"] == "2026-10-14", (
            "2026-08-15 advanced by sixty whole days lands on 2026-10-14"
        )

    def test_a_minimum_earned_window_equal_to_the_term_is_accepted(self, api):
        """365 earned days against a 365-day term is not an excess.

        The PRD states: "The coverage interval is half-open — the effective date
        is inside the term and the expiration date is the exclusive upper bound
        — the expiration date must be strictly after the effective date and no
        more than 730 days after it, and `min_earned_days` must not exceed the
        term length in days; a violation of the term shape yields
        `ERR_INVALID_POLICY_TERM` (HTTP 422)."

        Design: Corner/validations/satisfaction_to_pass_every_statutory_limit_at_its_legal_extreme_is_accepted
        """
        bundle = self._with_policy(api)

        assert bundle["policy"]["min_earned_days"] == 365
        assert bundle["policy"]["effective_date"] == "2026-09-01"
        assert bundle["policy"]["expiration_date"] == "2027-09-01"
        assert bundle["policy"]["status"] == "PENDING_VERIFICATION"

    def test_the_provisional_quote_prices_the_extreme_note_in_tier_one(self, api):
        """452000 financed over ten months at the tier-one rate.

        The PRD states: "Third, a volume tier is selected from the amount
        financed: an amount financed of 5,000 dollars or less takes a tier rate
        of 1800 basis points, an amount above 5,000 dollars but not above 20,000
        dollars takes 1500 basis points, and anything above 20,000 dollars takes
        1200 basis points — the larger the loan, the cheaper the money."

        Design: Corner/validations/satisfaction_to_pass_every_statutory_limit_at_its_legal_extreme_is_accepted
        """
        bundle = self._submitted(api)
        submitted = bundle["submitted"]

        assert submitted["status"] == "PENDING_VERIFICATION"
        assert submitted["amount_financed_cents"] == 452000 == 600000 - 150000 + 2000
        assert submitted["effective_annual_rate_bps"] == 1800, (
            "452000 does not exceed the 500000 cent tier-one ceiling"
        )
        assert submitted["finance_charge_cents"] == add_on_finance_charge_cents(
            452000, 1800, 10
        ) == 67800

    def test_the_down_payment_ratio_passes_on_the_quoted_basis(self, api):
        """150000 against a 600000 quote clears a 1500 bps minimum.

        The PRD states: "The minimum-down-payment test is a basis-point
        comparison and equality passes it: the down payment multiplied by 10000
        must be greater than or equal to the premium basis multiplied by the
        regime's `min_down_payment_bps`, where the premium basis at submission is
        the sum of the agency-quoted `gross_premium_cents` across the note's
        policies."

        Design: Corner/validations/satisfaction_to_pass_every_statutory_limit_at_its_legal_extreme_is_accepted
        """
        bundle = self._submitted(api)

        assert 150000 * 10000 >= 600000 * bundle["rule"]["min_down_payment_bps"]
        assert bundle["submitted"]["total_premium_cents"] == 600000
        assert bundle["submitted"]["quote_basis"] == "PROVISIONAL"

    def test_a_correction_exactly_on_the_tolerance_is_recorded(self, api):
        """Equality with the quarter-of-the-quote limit passes for both parties.

        The PRD states: "A `corrected_premium_cents` must stay within 2500 basis
        points — a quarter — of the agency-quoted `gross_premium_cents`: the
        absolute difference between the corrected premium and the quoted premium,
        multiplied by 10000, must be less than or equal to the quoted premium
        multiplied by 2500."

        Design: Corner/validations/satisfaction_to_pass_every_statutory_limit_at_its_legal_extreme_is_accepted
        """
        bundle = self._attested(api)

        assert abs(750000 - 600000) * 10000 == 600000 * 2500
        assert bundle["insurer_verification"]["party"] == "INSURER"
        assert bundle["agent_verification"]["party"] == "PRODUCER_AGENT"
        assert (
            bundle["insurer_verification"]["effective_premium_cents"]
            == bundle["agent_verification"]["effective_premium_cents"]
            == 750000
        )

    def test_the_agreed_correction_verifies_the_policy(self, api):
        """Both records agree on premium and effective date, so the policy forks
        to VERIFIED.

        The PRD states: "In that case the agreed figures are stamped as
        `verified_premium_cents` and `verified_effective_date`,
        `financed_premium_cents` is recomputed as `verified_premium_cents` plus
        `endorsed_premium_cents`, the agreement's `verified_policy_count`
        increases by 1, and the policy's `version` advances."

        Design: Corner/validations/satisfaction_to_pass_every_statutory_limit_at_its_legal_extreme_is_accepted
        """
        bundle = self._attested(api)

        policy = fixtures.read_policy(api, bundle["policy_id"])
        assert policy["status"] == "VERIFIED"
        assert policy["verified_premium_cents"] == 750000
        assert policy["financed_premium_cents"] == 750000

    def test_activation_reprices_the_note_into_the_cheaper_tier(self, api):
        """The accepted correction carries the amount financed over 500000.

        The PRD states: "Because every corrected premium moves
        `total_premium_cents`, it can also move `amount_financed_cents` across a
        tier boundary and therefore change `effective_annual_rate_bps`; a note
        quoted provisionally at 1800 basis points can activate at 1500."

        Design: Corner/validations/satisfaction_to_pass_every_statutory_limit_at_its_legal_extreme_is_accepted
        """
        bundle = self._activated(api)
        activated = bundle["activated"]

        assert activated["status"] == "ACTIVE"
        assert activated["total_premium_cents"] == 750000
        assert activated["amount_financed_cents"] == 602000 == 750000 - 150000 + 2000
        assert activated["effective_annual_rate_bps"] == 1500
        assert activated["finance_charge_cents"] == add_on_finance_charge_cents(
            602000, 1500, 10
        ) == 75250
        assert activated["total_of_payments_cents"] == 677250

    def test_the_activation_re_check_of_the_ratio_passes_on_the_attested_basis(
        self, api
    ):
        """150000 still clears 1500 bps of the higher attested premium.

        The PRD states: "The minimum-down-payment test is re-run, this time
        against the *attested* premium basis: `down_payment_cents` multiplied by
        10000 must be at least the sum of `financed_premium_cents` over the
        note's policies multiplied by `min_down_payment_bps`, and a failure is
        `ERR_DOWN_PAYMENT_BELOW_MINIMUM`."

        Design: Corner/validations/satisfaction_to_pass_every_statutory_limit_at_its_legal_extreme_is_accepted
        """
        bundle = self._activated(api)

        assert 150000 * 10000 >= 750000 * 1500
        assert bundle["activated"]["status"] == "ACTIVE"
        assert bundle["activated"]["service_fee_cents"] == 2000
        assert bundle["activated"]["quote_basis"] == "FINAL"

    def test_the_ten_installment_schedule_divides_with_no_remainder(self, api):
        """677250 over ten months leaves nothing for the last installment to
        absorb.

        The PRD states: "Under `ADD_ON` the note pays level installments: the
        base amount is `total_of_payments_cents` divided by `installment_count`
        and truncated down to whole cents, every installment except the last
        takes that base amount, and the last installment takes
        `total_of_payments_cents` minus the base amount multiplied by one less
        than the installment count."

        Design: Corner/validations/satisfaction_to_pass_every_statutory_limit_at_its_legal_extreme_is_accepted
        """
        bundle = self._activated(api)

        rows, meta = validate_paginated(
            api.list_installments(
                bundle["agreement_id"], ANALYST_ORIGIN, {"limit": 100}
            )
        )
        assert meta["total_count"] == 10
        rows.sort(key=lambda row: row["installment_number"])
        for row in rows:
            assert row["amount_cents"] == 67725
            assert row["finance_charge_component_cents"] == 7525
            assert row["principal_component_cents"] == 60200
        assert_installments_sum(rows, 677250, 75250)

    def test_the_due_dates_walk_ten_whole_months_from_the_extreme_date(self, api):
        """The fourteenth of the month survives every step of the walk.

        The PRD states: "Due dates walk forward by whole calendar months from
        `first_installment_due_date`: installment number 1 falls on that date,
        and installment *k* falls one month later than installment *k* minus
        one."

        Design: Corner/validations/satisfaction_to_pass_every_statutory_limit_at_its_legal_extreme_is_accepted
        """
        bundle = self._activated(api)

        rows = fixtures.read_installments(api, bundle["agreement_id"])
        rows.sort(key=lambda row: row["installment_number"])
        assert [row["due_date"] for row in rows] == [
            "2026-10-14",
            "2026-11-14",
            "2026-12-14",
            "2027-01-14",
            "2027-02-14",
            "2027-03-14",
            "2027-04-14",
            "2027-05-14",
            "2027-06-14",
            "2027-07-14",
        ]


class TestLateFeeCountCapHoldsAcrossSuccessiveSweeps:
    """Five installments go delinquent in turn, yet only three fees are ever
    assessed — and waiving one does not buy back headroom."""

    def _three_sweeps(self, api):
        """The 600k note swept once past each of its first three grace expiries."""
        bundle = fixtures.canonical_600k_note(api, policy_number="MC-AG-1")
        assert bundle["activated"]["total_of_payments_cents"] == 539650
        bundle["sweeps"] = [
            fixtures.advance_and_service(api, "2026-10-12T00:00:00Z"),
            fixtures.advance_and_service(api, "2026-11-12T00:00:00Z"),
            fixtures.advance_and_service(api, "2026-12-12T00:00:00Z"),
        ]
        return bundle

    def _fourth_sweep(self, api):
        bundle = self._three_sweeps(api)
        bundle["sweeps"].append(
            fixtures.advance_and_service(api, "2027-01-12T00:00:00Z")
        )
        return bundle

    def _waived(self, api):
        """The fee on installment 1 waived after the cap has already bound."""
        bundle = self._fourth_sweep(api)
        fees = fixtures.read_late_fees(api, bundle["agreement_id"])
        first = [fee for fee in fees if fee["installment_number"] == 1][0]
        bundle["fees"] = fees
        bundle["waived"] = validate_success(
            api.waive_late_fee(
                first["id"],
                factories.waiver(
                    justification="goodwill concession on the first delinquency"
                ),
                COMPLIANCE_WAIVER,
            ),
            200,
        )
        return bundle

    def _fifth_sweep(self, api):
        bundle = self._waived(api)
        bundle["sweeps"].append(
            fixtures.advance_and_service(api, "2027-02-12T00:00:00Z")
        )
        return bundle

    def test_each_of_the_first_three_sweeps_assesses_exactly_one_fee(self, api):
        """One newly past-due installment and one new fee per pass.

        The PRD states: "Then, if an installment is `PAST_DUE` and the clock date
        is *strictly after* its `due_date` advanced by the regime's
        `grace_period_days`, a late fee may be assessed against it."

        Design: Corner/validations/aggregate_validation_late_fee_count_cap_holds_across_successive_sweeps
        """
        bundle = self._three_sweeps(api)
        assert bundle["rule"]["max_late_fees_per_agreement"] == 3
        assert bundle["rule"]["grace_period_days"] == 10

        for sweep in bundle["sweeps"]:
            assert sweep["past_due_marked"] == 1
            assert sweep["late_fees_assessed"] == 1

    def test_the_note_advances_into_late_only_once(self, api):
        """The delinquency stage is entered on the first pass and then held.

        The PRD states: "An agreement that acquires a newly past-due installment
        while `CURRENT` advances `CURRENT` → `LATE` in the same pass."

        Design: Corner/validations/aggregate_validation_late_fee_count_cap_holds_across_successive_sweeps
        """
        bundle = self._three_sweeps(api)

        assert bundle["sweeps"][0]["agreements_advanced_to_late"] == 1
        assert bundle["sweeps"][1]["agreements_advanced_to_late"] == 0
        assert bundle["sweeps"][2]["agreements_advanced_to_late"] == 0
        assert (
            fixtures.read_agreement(api, bundle["agreement_id"])["delinquency_stage"]
            == "LATE"
        )

    def test_three_sweeps_leave_three_fees_and_their_summed_balance(self, api):
        """Each fee is 4497 and the note carries all three.

        The PRD states: "The note's `late_fee_count` increases by 1, its
        `late_fee_balance_cents` increases by the fee, and its `version`
        advances."

        Design: Corner/validations/aggregate_validation_late_fee_count_cap_holds_across_successive_sweeps
        """
        bundle = self._three_sweeps(api)

        assert late_fee_cents(89941, 500, 500, 10000) == 4497
        agreement = fixtures.read_agreement(api, bundle["agreement_id"])
        assert agreement["late_fee_count"] == 3
        assert agreement["late_fee_balance_cents"] == 13491 == 4497 * 3

    def test_the_fourth_sweep_marks_the_installment_but_assesses_nothing(self, api):
        """The lifetime counter has reached the cap and closes it for good.

        The PRD states: "The note's lifetime `late_fee_count` must be strictly
        less than the regime's `max_late_fees_per_agreement`, so a regime capping
        fees at three refuses a fourth for the rest of the note's life."

        Design: Corner/validations/aggregate_validation_late_fee_count_cap_holds_across_successive_sweeps
        """
        bundle = self._fourth_sweep(api)

        assert bundle["sweeps"][3]["past_due_marked"] == 1, (
            "installment 4 is still carried into PAST_DUE"
        )
        assert bundle["sweeps"][3]["late_fees_assessed"] == 0
        assert (
            fixtures.read_agreement(api, bundle["agreement_id"])["late_fee_count"] == 3
        )

    def test_the_three_fees_sit_on_three_distinct_installments(self, api):
        """Assessment order is installment order, one fee per position.

        The PRD states: "And no late fee may already exist for that agreement and
        that `installment_number` unless the existing one is `REVERSED`, so a
        single installment is charged once no matter how many passes run over it,
        while a fee reversed by a restructure does not block a fresh assessment
        on the successor note."

        Design: Corner/validations/aggregate_validation_late_fee_count_cap_holds_across_successive_sweeps
        """
        bundle = self._fourth_sweep(api)

        rows, meta = validate_paginated(
            api.list_late_fees(bundle["agreement_id"], COMPLIANCE, {"limit": 50})
        )
        assert meta["total_count"] == 3
        assert [row["installment_number"] for row in rows] == [1, 2, 3]
        assert [row["assessed_date"] for row in rows] == [
            "2026-10-12",
            "2026-11-12",
            "2026-12-12",
        ]

    def test_the_waiver_moves_the_balance_but_never_the_lifetime_counter(self, api):
        """The freed 4497 leaves the balance and the count stays at three.

        The PRD states: "What a waiver does *not* do is refresh the statutory
        cap: `late_fee_count` is never decremented, so waiving two fees under a
        three-fee cap still leaves room for only one more."

        Design: Corner/validations/aggregate_validation_late_fee_count_cap_holds_across_successive_sweeps
        """
        bundle = self._waived(api)

        assert bundle["waived"]["status"] == "WAIVED"
        agreement = fixtures.read_agreement(api, bundle["agreement_id"])
        assert agreement["late_fee_balance_cents"] == 8994 == 13491 - 4497
        assert agreement["late_fee_count"] == 3

    def test_the_waiver_does_not_cure_a_note_still_carrying_arrears(self, api):
        """Two outstanding fees and four past-due installments keep it LATE.

        The PRD states: "And a waiver can cure a delinquency — if, after the
        waiver, the note carries no `OUTSTANDING` fee and no `PAST_DUE`
        installment, its `delinquency_stage` advances to `CURRENT` and any notice
        of intent to cancel still in `ISSUED` moves to `CURED`, exactly as a
        payment would have cured it."

        Design: Corner/validations/aggregate_validation_late_fee_count_cap_holds_across_successive_sweeps
        """
        bundle = self._waived(api)

        assert (
            fixtures.read_agreement(api, bundle["agreement_id"])["delinquency_stage"]
            == "LATE"
        )
        _, outstanding = validate_paginated(
            api.list_late_fees(
                bundle["agreement_id"],
                COMPLIANCE,
                {"status": "OUTSTANDING", "limit": 50},
            )
        )
        assert outstanding["total_count"] == 2
        _, past_due = validate_paginated(
            api.list_installments(
                bundle["agreement_id"], COMPLIANCE, {"status": "PAST_DUE", "limit": 100}
            )
        )
        assert past_due["total_count"] == 4

    def test_the_sweep_after_the_waiver_still_assesses_nothing(self, api):
        """Freed balance is not freed cap headroom.

        The PRD states: "One counter is deliberately excluded from this identity:
        `late_fee_count` is a lifetime counter that never moves backwards, so
        neither a waiver nor a reversal restores it."

        Design: Corner/validations/aggregate_validation_late_fee_count_cap_holds_across_successive_sweeps
        """
        bundle = self._fifth_sweep(api)

        assert bundle["sweeps"][4]["past_due_marked"] == 1
        assert bundle["sweeps"][4]["late_fees_assessed"] == 0
        agreement = fixtures.read_agreement(api, bundle["agreement_id"])
        assert agreement["late_fee_count"] == 3
        assert agreement["late_fee_balance_cents"] == 8994

    def test_five_delinquent_installments_against_three_lifetime_fees(self, api):
        """The collections tell the whole story at the end of the run.

        The PRD states: "Fees can be listed per note and filtered by `status`,
        which is one of `OUTSTANDING`, `PAID`, `WAIVED` or `REVERSED`."

        Design: Corner/validations/aggregate_validation_late_fee_count_cap_holds_across_successive_sweeps
        """
        bundle = self._fifth_sweep(api)

        _, all_fees = validate_paginated(
            api.list_late_fees(bundle["agreement_id"], COMPLIANCE, {"limit": 50})
        )
        assert all_fees["total_count"] == 3
        _, outstanding = validate_paginated(
            api.list_late_fees(
                bundle["agreement_id"],
                COMPLIANCE,
                {"status": "OUTSTANDING", "limit": 50},
            )
        )
        assert outstanding["total_count"] == 2
        _, waived = validate_paginated(
            api.list_late_fees(
                bundle["agreement_id"], COMPLIANCE, {"status": "WAIVED", "limit": 50}
            )
        )
        assert waived["total_count"] == 1
        _, past_due = validate_paginated(
            api.list_installments(
                bundle["agreement_id"], COMPLIANCE, {"status": "PAST_DUE", "limit": 100}
            )
        )
        assert past_due["total_count"] == 5


class TestLicenseRequiredFlagTogglesTheLicensingGate:
    """The same origination request is legal or illegal depending only on the
    flag carried by the regime it points at."""

    def _two_regimes(self, api):
        """A TX regime demanding a licence and an AZ regime that does not."""
        fixtures.set_clock(api, "2026-08-15T00:00:00Z")
        tx_rule = validate_success(
            api.create_state_rate_rule(factories.tx_state_rate_rule(), COMPLIANCE), 201
        )
        az_rule = validate_success(
            api.create_state_rate_rule(
                factories.state_rate_rule("AZ", license_required=False), COMPLIANCE
            ),
            201,
        )
        ctx = fixtures.create_parties(
            api,
            insured_payload=factories.insured(
                legal_name="Cascade Logistics Inc", email="ap@cascade.example"
            ),
        )
        az_agent = validate_success(
            api.create_agent(
                factories.producer_agent(
                    agency_name="Sonoran Brokers", state_code="AZ"
                ),
                COMPLIANCE,
            ),
            201,
        )
        ctx.update(
            {
                "tx_rule": tx_rule,
                "az_rule": az_rule,
                "az_agent": az_agent,
                "az_agent_headers": make_producer_agent_headers(az_agent["id"]),
            }
        )
        return ctx

    def _tx_payload(self, ctx):
        return factories.agreement(
            ctx["insured_id"], ctx["agent_id"], ctx["tx_rule"]["id"]
        )

    def _az_payload(self, ctx):
        return factories.agreement(
            ctx["insured_id"], ctx["az_agent"]["id"], ctx["az_rule"]["id"]
        )

    def _az_active(self, api):
        """The unlicensed AZ regime carried all the way to a live receivable."""
        ctx = self._two_regimes(api)
        agreement = validate_success(
            api.create_agreement(self._az_payload(ctx), ANALYST_ORIGIN), 201
        )
        policy = validate_success(
            api.attach_policy(
                agreement["id"],
                factories.financed_policy(
                    ctx["insurer_id"], policy_number="MC-CV-AZ"
                ),
                ANALYST_ORIGIN,
            ),
            201,
        )
        ctx["az_agreement"] = agreement
        ctx["az_submitted"] = validate_success(
            api.submit_agreement(agreement["id"], ANALYST_ORIGIN), 200
        )
        validate_success(
            api.create_verification(
                policy["id"],
                factories.confirmed_verification(),
                ctx["insurer_headers"],
            ),
            201,
        )
        validate_success(
            api.create_verification(
                policy["id"],
                factories.confirmed_verification(),
                ctx["az_agent_headers"],
            ),
            201,
        )
        ctx["az_activated"] = validate_success(
            api.activate_agreement(agreement["id"], ANALYST_ORIGIN), 200
        )
        return ctx

    def _tx_licensed(self, api):
        """The refused TX request retried after a licence is put on file."""
        ctx = self._two_regimes(api)
        validate_error(
            api.create_agreement(self._tx_payload(ctx), ANALYST_ORIGIN),
            ApiErrorId.STATE_NOT_LICENSED.value,
            422,
        )
        ctx["tx_license"] = validate_success(
            api.create_license(
                ctx["tx_rule"]["id"],
                factories.license_payload(license_number="PFC-TX-001"),
                COMPLIANCE,
            ),
            201,
        )
        ctx["tx_agreement"] = validate_success(
            api.create_agreement(self._tx_payload(ctx), ANALYST_ORIGIN), 201
        )
        return ctx

    def _az_suspended(self, api):
        """The flagless AZ regime holding an ineffective licence."""
        ctx = self._two_regimes(api)
        created = validate_success(
            api.create_license(
                ctx["az_rule"]["id"],
                factories.license_payload(license_number="PFC-AZ-001"),
                COMPLIANCE,
            ),
            201,
        )
        ctx["az_license"] = validate_success(
            api.suspend_license(created["id"], COMPLIANCE), 200
        )
        ctx["az_agreement_2"] = validate_success(
            api.create_agreement(self._az_payload(ctx), ANALYST_ORIGIN), 201
        )
        return ctx

    def test_the_two_regimes_differ_only_in_the_flag(self, api):
        """One demands a licence, the other does not, and neither has one yet.

        The PRD states: "Finally, `license_required` is a boolean that defaults
        to true and states whether an effective premium finance license is needed
        to originate in that state, and `active_agreement_count` is a derived
        counter, starting at 0, holding the number of agreements referencing this
        regime whose financing status is either `PENDING_VERIFICATION` or
        `ACTIVE`."

        Design: Corner/validations/conditional_validation_license_required_flag_toggles_the_licensing_gate
        """
        ctx = self._two_regimes(api)

        assert ctx["tx_rule"]["license_required"] is True
        assert ctx["az_rule"]["license_required"] is False
        assert ctx["tx_rule"]["finance_charge_method"] == (
            ctx["az_rule"]["finance_charge_method"]
        )
        _, meta = validate_paginated(
            api.list_licenses(ctx["tx_rule"]["id"], COMPLIANCE, {"limit": 50})
        )
        assert meta["total_count"] == 0

    def test_the_flag_on_with_no_licence_refuses_origination(self, api):
        """Leg 1: the gate is closed because nothing is effective.

        The PRD states: "At each, if the governing regime has `license_required`
        set to true and no license of that regime is effective at the clock date,
        the operation fails with `ERR_STATE_NOT_LICENSED` (HTTP 422)."

        Design: Corner/validations/conditional_validation_license_required_flag_toggles_the_licensing_gate
        """
        ctx = self._two_regimes(api)

        validate_error(
            api.create_agreement(self._tx_payload(ctx), ANALYST_ORIGIN),
            ApiErrorId.STATE_NOT_LICENSED.value,
            422,
        )

    def test_the_flag_off_with_no_licence_accepts_the_same_request(self, api):
        """Leg 2: the byte-identical terms are legal under the flagless regime.

        The PRD states: "When `license_required` is false the check is skipped
        entirely, and a regime with an expired or suspended licence still permits
        origination."

        Design: Corner/validations/conditional_validation_license_required_flag_toggles_the_licensing_gate
        """
        ctx = self._two_regimes(api)
        tx_payload = self._tx_payload(ctx)
        az_payload = self._az_payload(ctx)
        assert [tx_payload[key] for key in ("down_payment_cents", "service_fee_cents",
                                            "installment_count",
                                            "first_installment_due_date")] == [
            az_payload[key]
            for key in (
                "down_payment_cents",
                "service_fee_cents",
                "installment_count",
                "first_installment_due_date",
            )
        ]

        agreement = validate_success(
            api.create_agreement(az_payload, ANALYST_ORIGIN), 201
        )
        assert agreement["status"] == "DRAFT"

    def test_the_whole_lifecycle_runs_unlicensed_under_a_false_flag(self, api):
        """Leg 2 continued: submission and activation are both skipped gates.

        The PRD states: "Licensing is enforced at four points in a note's life:
        when an agreement is created, when it is submitted, when it is activated,
        and when it is restructured."

        Design: Corner/validations/conditional_validation_license_required_flag_toggles_the_licensing_gate
        """
        ctx = self._az_active(api)

        assert ctx["az_agreement"]["status"] == "DRAFT"
        assert ctx["az_submitted"]["status"] == "PENDING_VERIFICATION"
        assert ctx["az_activated"]["status"] == "ACTIVE"
        assert ctx["az_activated"]["total_of_payments_cents"] == 539650
        _, meta = validate_paginated(
            api.list_licenses(ctx["az_rule"]["id"], COMPLIANCE, {"limit": 50})
        )
        assert meta["total_count"] == 0, (
            "the note reached ACTIVE without a licence ever existing"
        )

    def test_putting_an_effective_licence_on_file_opens_the_gate(self, api):
        """Leg 3: the previously refused request now succeeds unchanged.

        The PRD states: "The derived flag `is_effective` is true when, and only
        when, `status` is `ACTIVE` and the clock date falls inside the window with
        both bounds inclusive — that is, the clock date is on or after
        `effective_date` and on or before `expiration_date`."

        Design: Corner/validations/conditional_validation_license_required_flag_toggles_the_licensing_gate
        """
        ctx = self._tx_licensed(api)

        assert ctx["tx_license"]["status"] == "ACTIVE"
        assert ctx["tx_license"]["is_effective"] is True
        assert ctx["tx_license"]["effective_date"] == "2026-01-01"
        assert ctx["tx_license"]["expiration_date"] == "2027-12-31"
        assert ctx["tx_agreement"]["status"] == "DRAFT"

    def test_the_flag_is_consulted_before_any_licence_row_is_examined(self, api):
        """Leg 4: an ineffective licence on a flagless regime changes nothing.

        The PRD states: "Suspension sets `is_effective` to false immediately."

        Design: Corner/validations/conditional_validation_license_required_flag_toggles_the_licensing_gate
        """
        ctx = self._az_suspended(api)

        assert ctx["az_license"]["status"] == "SUSPENDED"
        assert ctx["az_license"]["is_effective"] is False
        assert ctx["az_agreement_2"]["status"] == "DRAFT", (
            "an ineffective licence does not close a gate the flag has switched off"
        )

    def test_the_ineffective_licence_really_was_on_file(self, api):
        """The suspended row is discoverable through the status filter.

        The PRD states: "Licenses of one regime can be listed and filtered by
        `status`."

        Design: Corner/validations/conditional_validation_license_required_flag_toggles_the_licensing_gate
        """
        ctx = self._az_suspended(api)

        _, meta = validate_paginated(
            api.list_licenses(
                ctx["az_rule"]["id"],
                COMPLIANCE,
                {"status": "SUSPENDED", "limit": 50},
            )
        )
        assert meta["total_count"] == 1


class TestDownPaymentRatioNeedsThePremiumBasisFirst:
    """The earlier of two checks passes vacuously on an empty premium basis, so
    the later one decides the code — and the same zero tender then fails the
    earlier check once a policy exists."""

    def _two_drafts(self, api):
        """Two identical zero-down notes, one with a policy and one without."""
        ctx = _tx_regime_context(api)
        payload = factories.agreement(
            ctx["insured_id"],
            ctx["agent_id"],
            ctx["rule_id"],
            down_payment_cents=0,
        )
        ctx["agreement_x"] = validate_success(
            api.create_agreement(dict(payload), ANALYST_ORIGIN), 201
        )
        ctx["agreement_y"] = validate_success(
            api.create_agreement(dict(payload), ANALYST_ORIGIN), 201
        )
        ctx["policy_y"] = validate_success(
            api.attach_policy(
                ctx["agreement_y"]["id"],
                factories.financed_policy(
                    ctx["insurer_id"], policy_number="MC-CD-Y"
                ),
                ANALYST_ORIGIN,
            ),
            201,
        )
        return ctx

    def test_a_zero_down_payment_is_legal_at_creation(self, api):
        """The ratio check is not one of the gates that runs when a note opens.

        The PRD states: "The down payment meets the statutory minimum —
        otherwise `ERR_DOWN_PAYMENT_BELOW_MINIMUM`, on submission and
        restructuring."

        Design: Corner/validations/cascading_validation_down_payment_ratio_needs_the_premium_basis_first
        """
        ctx = self._two_drafts(api)

        assert ctx["agreement_x"]["down_payment_cents"] == 0
        assert ctx["agreement_y"]["down_payment_cents"] == 0
        assert ctx["agreement_x"]["status"] == "DRAFT"
        assert ctx["agreement_y"]["status"] == "DRAFT"
        assert ctx["agreement_x"]["policy_count"] == 0
        assert ctx["rule"]["min_down_payment_bps"] == 1500

    def test_the_note_with_no_policies_reports_the_missing_policy_set(self, api):
        """The later check surfaces even though the earlier one is listed first.

        The PRD states: "Eight preconditions must hold, and each maps to a
        specific rejection: at least one non-cancelled policy must be attached, or
        `ERR_NO_FINANCED_POLICIES` (HTTP 422); every policy of the note must still
        be `PENDING_VERIFICATION`, or the policy-state gate refuses the
        submission; the regime must be licensed, or `ERR_STATE_NOT_LICENSED`; the
        producing agency must be `ACTIVE`, or `ERR_AGENT_SUSPENDED`; the down
        payment must meet the statutory minimum, or
        `ERR_DOWN_PAYMENT_BELOW_MINIMUM` (HTTP 422); `service_fee_cents` must sit
        within the regime's `max_service_fee_cents`, or within
        `approved_service_fee_cap_cents` when a rate exception has been approved,
        or `ERR_SERVICE_FEE_ABOVE_CAP`; `installment_count` must be at least 2 and
        no greater than `max_term_months`, or `ERR_TERM_EXCEEDS_STATE_MAXIMUM`;
        and the first-due-date window must still hold against the current clock
        date, or `ERR_INVALID_FIRST_DUE_DATE`."

        Design: Corner/validations/cascading_validation_down_payment_ratio_needs_the_premium_basis_first
        """
        ctx = self._two_drafts(api)

        validate_error(
            api.submit_agreement(ctx["agreement_x"]["id"], ANALYST_ORIGIN),
            ApiErrorId.NO_FINANCED_POLICIES.value,
            422,
        )

    def test_the_ratio_test_is_satisfied_vacuously_on_an_empty_basis(self, api):
        """With no policies the comparison reads zero against zero and holds.

        The PRD states: "The minimum-down-payment test is a basis-point
        comparison and equality passes it: the down payment multiplied by 10000
        must be greater than or equal to the premium basis multiplied by the
        regime's `min_down_payment_bps`, where the premium basis at submission is
        the sum of the agency-quoted `gross_premium_cents` across the note's
        policies."

        Design: Corner/validations/cascading_validation_down_payment_ratio_needs_the_premium_basis_first
        """
        ctx = self._two_drafts(api)
        empty_basis = 0

        assert 0 * 10000 >= empty_basis * ctx["rule"]["min_down_payment_bps"], (
            "an empty policy set makes the premium basis zero, and equality passes"
        )
        validate_error(
            api.submit_agreement(ctx["agreement_x"]["id"], ANALYST_ORIGIN),
            ApiErrorId.NO_FINANCED_POLICIES.value,
            422,
        )

    def test_one_policy_gives_the_ratio_test_something_to_fail_against(self, api):
        """A basis of 600000 makes the untendered minimum 90000.

        The PRD states: "A regime demanding 2000 basis points — one fifth of the
        premium — therefore accepts a down payment of exactly one fifth and
        refuses one cent less."

        Design: Corner/validations/cascading_validation_down_payment_ratio_needs_the_premium_basis_first
        """
        ctx = self._two_drafts(api)
        assert 0 * 10000 < 600000 * 1500

        validate_error(
            api.submit_agreement(ctx["agreement_y"]["id"], ANALYST_ORIGIN),
            ApiErrorId.DOWN_PAYMENT_BELOW_MINIMUM.value,
            422,
        )

    def test_the_same_tender_produces_two_different_codes(self, api):
        """Only the presence of the policy set decides which rule reports.

        The PRD states: "Checks are therefore strictly ordered, and the first
        violated check decides the response."

        Design: Corner/validations/cascading_validation_down_payment_ratio_needs_the_premium_basis_first
        """
        ctx = self._two_drafts(api)
        assert (
            ctx["agreement_x"]["down_payment_cents"]
            == ctx["agreement_y"]["down_payment_cents"]
            == 0
        )

        validate_error(
            api.submit_agreement(ctx["agreement_x"]["id"], ANALYST_ORIGIN),
            ApiErrorId.NO_FINANCED_POLICIES.value,
            422,
        )
        validate_error(
            api.submit_agreement(ctx["agreement_y"]["id"], ANALYST_ORIGIN),
            ApiErrorId.DOWN_PAYMENT_BELOW_MINIMUM.value,
            422,
        )

    def test_neither_refused_submission_stamped_a_quote(self, api):
        """Both notes are still drafts with their money fields untouched.

        The PRD states: "The new note is stamped `DRAFT` in its financing
        `status` and `CURRENT` in its `delinquency_stage`, its
        `originated_by_user_id` is frozen from `X-User-ID` for the later
        two-person control, and every balance, derived money field and counter is
        zeroed — including `total_premium_cents`, `amount_financed_cents`,
        `effective_annual_rate_bps`, `finance_charge_cents`,
        `total_of_payments_cents`, `principal_balance_cents`,
        `unpaid_finance_charge_cents`, `late_fee_balance_cents`, `late_fee_count`,
        `unapplied_credit_cents`, `unearned_premium_received_cents`,
        `deficiency_balance_cents`, `refund_due_cents`, `agent_chargeback_cents`,
        `policy_count`, `verified_policy_count` and `carried_over_balance_cents` —
        while `quote_basis`, `activated_at`, `restructured_from_agreement_id`,
        `approved_service_fee_cap_cents` and `approved_annual_rate_bps` are all
        null and `rate_exception_approved` is false."

        Design: Corner/validations/cascading_validation_down_payment_ratio_needs_the_premium_basis_first
        """
        ctx = self._two_drafts(api)
        api.submit_agreement(ctx["agreement_x"]["id"], ANALYST_ORIGIN)
        api.submit_agreement(ctx["agreement_y"]["id"], ANALYST_ORIGIN)

        for key in ("agreement_x", "agreement_y"):
            agreement = fixtures.read_agreement(api, ctx[key]["id"])
            assert agreement["status"] == "DRAFT"
            assert agreement["quote_basis"] is None
            assert agreement["total_premium_cents"] == 0
            assert agreement["amount_financed_cents"] == 0
            assert agreement["total_of_payments_cents"] == 0

    def test_no_submission_succeeded_so_the_regime_counter_never_moved(self, api):
        """The exposure counter belongs to submission and nothing submitted.

        The PRD states: "The state regime's `active_agreement_count` is
        deliberately *not* touched at creation; submission owns that increment."

        Design: Corner/validations/cascading_validation_down_payment_ratio_needs_the_premium_basis_first
        """
        ctx = self._two_drafts(api)
        api.submit_agreement(ctx["agreement_x"]["id"], ANALYST_ORIGIN)
        api.submit_agreement(ctx["agreement_y"]["id"], ANALYST_ORIGIN)

        assert (
            fixtures.read_agreement(api, ctx["agreement_y"]["id"])["policy_count"] == 1
        )
        rule = validate_success(
            api.get_state_rate_rule(ctx["rule_id"], COMPLIANCE), 200
        )
        assert rule["active_agreement_count"] == 0
