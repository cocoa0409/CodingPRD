"""Terminations and retro-effective recoupment: gross vs net variants,
per-claim fee rounding, provider balance compensation, and the depth-3
provider cascade (PRD §3.8)."""
from test_helpers import (
    ApiErrorId,
    assert_claim,
    assert_enrollment_record,
    create_approved_application,
    create_claim,
    create_draft_application,
    create_payer_config,
    create_submitted_application,
    find_record,
    get_claim,
    get_provider_balance,
    recoupment_fee,
    set_clock,
    setup_group_provider_payer,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

SPECIALIST = TEST_USERS["enrollment_specialist_headers"]
PAYER_REP = TEST_USERS["payer_representative_headers"]
OFFICER = TEST_USERS["compliance_officer_headers"]


def _terminate_record(api, record_id, termination_date):
    return api.terminate_enrollment_record(
        record_id, {"termination_effective_date": termination_date}, OFFICER
    )


class TestGrossVsNetRecoupmentVariants:
    def test_one_termination_scored_two_ways(self, api):
        """PRD §3.8: "`gross_impacted_cents` sums the principal —
        `amount_cents` only, fees excluded — over both the `HELD`-to-`DENIED`
        claims and the `RELEASED`-to-`RECOUPED` claims of the cascade,
        capturing total claims impact."
        PRD §3.8: "`net_recouped_cents` sums principal plus fee over only the
        recouped claims, capturing money actually clawed back; with identical
        termination data the two figures diverge whenever any held claim is
        denied or any fee is nonzero."

        Design: Difficulty/dual_variant_calc/gross_vs_net_recoupment_variants
        """
        _, provider, _, payer = setup_group_provider_payer()
        # c1 is uncovered at intake (no record yet) -> HELD; after approval
        # (effective 2026-08-01) its service date 2026-07-15 stays HELD.
        c1 = create_claim(
            provider["id"], payer["id"], service_date="2026-07-15", amount_cents=5000,
        )
        _, record = create_approved_application(provider["id"], payer["id"])
        assert get_claim(c1["id"])["status"] == "HELD"

        set_clock("2026-08-10T00:00:00Z")
        c2 = create_claim(
            provider["id"], payer["id"], service_date="2026-08-05", amount_cents=8000,
        )
        assert c2["status"] == "RELEASED"

        terminated = validate_success(_terminate_record(api, record["id"], "2026-08-03"), 200)
        assert terminated["status"] == "TERMINATED"
        assert terminated["termination_date"] == "2026-08-03"
        # gross = 5000 (denied-held principal) + 8000 (recouped principal).
        assert terminated["gross_impacted_cents"] == 13000
        # net = 8000 + round_half_up(8000 * 2%) = 8000 + 160.
        assert terminated["net_recouped_cents"] == 8160
        assert terminated["gross_impacted_cents"] != terminated["net_recouped_cents"]

        c1_after = get_claim(c1["id"])
        assert c1_after["status"] == "DENIED"
        assert c1_after["denial_reason"] == "ENROLLMENT_TERMINATED"
        c2_after = get_claim(c2["id"])
        assert c2_after["status"] == "RECOUPED"
        assert c2_after["recoupment_fee_cents"] == 160
        assert get_provider_balance(provider["id"]) == 8160

    def test_held_only_cascade_yields_zero_net(self, api):
        """PRD §3.8: "`net_recouped_cents` sums principal plus fee over only
        the recouped claims, capturing money actually clawed back; with
        identical termination data the two figures diverge whenever any held
        claim is denied or any fee is nonzero."
        PRD §3.8: "The provider's `recoupment_balance_cents` increases by the
        cascade's net figure, and at all times that balance equals the sum of
        principal plus fee over the provider's claims currently in `RECOUPED`."

        Design: Difficulty/dual_variant_calc/gross_vs_net_recoupment_variants
        """
        _, provider, _, payer = setup_group_provider_payer()
        c1 = create_claim(
            provider["id"], payer["id"], service_date="2026-07-15", amount_cents=5000,
        )
        _, record = create_approved_application(provider["id"], payer["id"])
        assert get_claim(c1["id"])["status"] == "HELD"

        terminated = validate_success(_terminate_record(api, record["id"], "2026-08-03"), 200)
        # Only a HELD claim was denied: gross measures its principal, net is 0.
        assert terminated["gross_impacted_cents"] == 5000
        assert terminated["net_recouped_cents"] == 0
        assert get_claim(c1["id"])["status"] == "DENIED"
        assert get_provider_balance(provider["id"]) == 0


class TestRecoupmentFeeRounding:
    def test_per_claim_rounding_pinned_over_sum_then_round(self, api):
        """PRD §3.8: "The fee's rounding order is pinned: the fee is computed
        per claim and only then summed, never computed once over the summed
        principals. Two claims of 3,333 cents each therefore yield fees of 67
        cents apiece — 134 cents in total — whereas applying the percentage to
        the combined 6,666 cents and rounding once would yield 133 cents; the
        per-claim order is the prescribed behavior."

        Design: Difficulty/combinatorial_formula/recoupment_fee_per_claim_rounding
        """
        _, provider, _, payer = setup_group_provider_payer()
        _, record = create_approved_application(provider["id"], payer["id"])
        set_clock("2026-08-10T00:00:00Z")
        c1 = create_claim(
            provider["id"], payer["id"], service_date="2026-08-05", amount_cents=3333,
        )
        c2 = create_claim(
            provider["id"], payer["id"], service_date="2026-08-05", amount_cents=3333,
        )
        assert c1["status"] == "RELEASED" and c2["status"] == "RELEASED"

        terminated = validate_success(_terminate_record(api, record["id"], "2026-08-01"), 200)
        assert get_claim(c1["id"])["recoupment_fee_cents"] == 67
        assert get_claim(c2["id"])["recoupment_fee_cents"] == 67
        # Per-claim order: 67 + 67 = 134 (sum-then-round would give 133).
        assert terminated["net_recouped_cents"] == 6800  # 6666 + 134
        assert terminated["gross_impacted_cents"] == 6666
        assert get_provider_balance(provider["id"]) == 6800

    def test_round_half_up_at_exact_half_cent(self, api):
        """PRD §3.8: "Every `RELEASED` claim whose `service_date` is on or
        after the termination date becomes `RECOUPED`, and each recouped claim
        is charged a recovery fee of two percent of its `amount_cents`, rounded
        half up to whole cents and stored as `recoupment_fee_cents`."

        Design: Difficulty/combinatorial_formula/recoupment_fee_per_claim_rounding
        """
        _, provider, _, payer = setup_group_provider_payer()
        _, record = create_approved_application(provider["id"], payer["id"])
        set_clock("2026-08-10T00:00:00Z")
        # 325 * 2% = 6.50 -> half up to 7; 100 * 2% = 2 exactly.
        c1 = create_claim(
            provider["id"], payer["id"], service_date="2026-08-05", amount_cents=325,
        )
        c2 = create_claim(
            provider["id"], payer["id"], service_date="2026-08-06", amount_cents=100,
        )

        terminated = validate_success(_terminate_record(api, record["id"], "2026-08-03"), 200)
        assert get_claim(c1["id"])["recoupment_fee_cents"] == 7
        assert get_claim(c2["id"])["recoupment_fee_cents"] == 2
        assert terminated["net_recouped_cents"] == 325 + 7 + 100 + 2
        assert terminated["gross_impacted_cents"] == 425
        assert get_provider_balance(provider["id"]) == 434


class TestRecoupmentBalanceCompensation:
    def test_reverse_recoupment_restores_balance_and_zeroes_fee(self, api):
        """PRD §3.8: "A `ComplianceOfficer` may reverse a claim that is
        `RECOUPED`, returning it `RECOUPED → RELEASED`; the provider's
        `recoupment_balance_cents` is decremented by that claim's principal
        plus fee, and the claim's `recoupment_fee_cents` is reset to zero."

        Design: Difficulty/compensating_invariant/recoupment_balance_compensation
        """
        _, provider, _, payer = setup_group_provider_payer()
        _, record = create_approved_application(provider["id"], payer["id"])
        set_clock("2026-08-10T00:00:00Z")
        claim = create_claim(
            provider["id"], payer["id"], service_date="2026-08-05", amount_cents=8000,
        )

        _terminate_record(api, record["id"], "2026-08-03")
        assert get_provider_balance(provider["id"]) == 8160  # 8000 + 160 fee

        reversed_claim = validate_success(api.reverse_recoupment(claim["id"], OFFICER), 200)
        assert reversed_claim["status"] == "RELEASED"
        assert reversed_claim["recoupment_fee_cents"] == 0
        assert get_provider_balance(provider["id"]) == 0, (
            "forward + compensating pair leaves the conserved quantity unchanged"
        )

    def test_balance_equals_sum_over_currently_recouped_claims(self, api):
        """PRD §3.8: "The provider's `recoupment_balance_cents` increases by
        the cascade's net figure, and at all times that balance equals the sum
        of principal plus fee over the provider's claims currently in
        `RECOUPED`."

        Design: Difficulty/compensating_invariant/recoupment_balance_compensation
        """
        _, provider, _, payer = setup_group_provider_payer()
        _, record = create_approved_application(provider["id"], payer["id"])
        set_clock("2026-08-10T00:00:00Z")
        c1 = create_claim(
            provider["id"], payer["id"], service_date="2026-08-05", amount_cents=8000,
        )
        c2 = create_claim(
            provider["id"], payer["id"], service_date="2026-08-06", amount_cents=2000,
        )

        _terminate_record(api, record["id"], "2026-08-03")
        # Both recouped: fees 160 and 40 -> balance 8000+160 + 2000+40 = 10200.
        assert get_provider_balance(provider["id"]) == 10200

        validate_success(api.reverse_recoupment(c1["id"], OFFICER), 200)
        assert get_provider_balance(provider["id"]) == 2040, (
            "after reversing c1, the balance tracks the claims still RECOUPED"
        )
        c1_after = get_claim(c1["id"])
        assert c1_after["status"] == "RELEASED"
        assert c1_after["recoupment_fee_cents"] == 0
        c2_after = get_claim(c2["id"])
        assert c2_after["status"] == "RECOUPED"
        assert c2_after["recoupment_fee_cents"] == 40


class TestProviderRetroTerminationCascade:
    def test_depth3_cascade_recoups_denies_and_withdraws(self, api):
        """PRD §3.8: "The cascade then runs three levels deep: each of those
        records is terminated with the same termination date, and each record
        termination fires the full record-termination cascade above — held
        claims denied, released claims on or after the date recouped with
        their per-claim fees, and each recoupment lifting the provider's
        `recoupment_balance_cents` by principal plus fee."
        PRD §3.8: "After the records, any remaining `HELD` claim of the
        provider with no covering record is denied with `ENROLLMENT_TERMINATED`,
        and every in-flight application of the provider — `DRAFT`, `SUBMITTED`,
        or `PENDING_INFO` — is moved to `WITHDRAWN` by the system."

        Design: Difficulty/transitive_cascade/provider_retro_termination_cascade
        """
        _, provider, _, payer_a = setup_group_provider_payer()
        payer_b = create_payer_config(
            payer_code="PB", name="Payer B", effective_date_policy="RETRO_90",
        )
        # c1 HELD before the record exists; stays HELD after approval because
        # its service date precedes the effective date 2026-08-01.
        c1 = create_claim(
            provider["id"], payer_a["id"], service_date="2026-07-15", amount_cents=5000,
        )
        _, record = create_approved_application(provider["id"], payer_a["id"])

        set_clock("2026-08-10T00:00:00Z")
        c2 = create_claim(
            provider["id"], payer_a["id"], service_date="2026-08-05", amount_cents=8000,
        )
        assert c2["status"] == "RELEASED"
        app_b = create_draft_application(
            provider["id"], payer_b["id"], requested_effective_date="2026-08-10",
        )

        terminated_provider = validate_success(
            api.terminate_provider(
                provider["id"],
                {"termination_effective_date": "2026-08-03", "reason": "left group"},
                OFFICER,
            ),
            200,
        )
        assert terminated_provider["status"] == "TERMINATED"
        assert terminated_provider["termination_date"] == "2026-08-03"
        assert terminated_provider["termination_reason"] == "left group"
        # Hop 3: balance lifted by recouped principal + fee.
        assert terminated_provider["recoupment_balance_cents"] == 8160

        # Hop 1: the enrollment record terminated with the same date.
        record_after = validate_success(
            api.get_enrollment_record(record["id"], OFFICER), 200
        )
        assert record_after["status"] == "TERMINATED"
        assert record_after["termination_date"] == "2026-08-03"
        assert record_after["gross_impacted_cents"] == 13000

        # Hop 2: claims denied / recouped.
        assert get_claim(c1["id"])["status"] == "DENIED"
        assert get_claim(c1["id"])["denial_reason"] == "ENROLLMENT_TERMINATED"
        c2_after = get_claim(c2["id"])
        assert c2_after["status"] == "RECOUPED"
        assert c2_after["recoupment_fee_cents"] == 160

        # The in-flight DRAFT application on the other payer is swept.
        app_b_after = validate_success(
            api.get_enrollment_application(app_b["id"], OFFICER), 200
        )
        assert app_b_after["status"] == "WITHDRAWN"

    def test_uncovered_held_claims_denied_by_provider_termination(self, api):
        """PRD §3.8: "After the records, any remaining `HELD` claim of the
        provider with no covering record is denied with `ENROLLMENT_TERMINATED`,
        and every in-flight application of the provider — `DRAFT`, `SUBMITTED`,
        or `PENDING_INFO` — is moved to `WITHDRAWN` by the system."

        Design: Difficulty/transitive_cascade/provider_retro_termination_cascade
        """
        _, provider, _, payer_x = setup_group_provider_payer()
        payer_y = create_payer_config(payer_code="PY", name="Payer Y")
        payer_z = create_payer_config(payer_code="PZ", name="Payer Z")

        # Payer X has no enrollment record at all: the claim is parked HELD.
        cx = create_claim(
            provider["id"], payer_x["id"], service_date="2026-07-15", amount_cents=5000,
        )
        assert cx["status"] == "HELD"
        _, record_y = create_approved_application(provider["id"], payer_y["id"])
        app_z = create_draft_application(provider["id"], payer_z["id"])

        validate_success(
            api.terminate_provider(
                provider["id"],
                {"termination_effective_date": "2026-08-05", "reason": "departed"},
                OFFICER,
            ),
            200,
        )

        record_y_after = validate_success(
            api.get_enrollment_record(record_y["id"], OFFICER), 200
        )
        assert record_y_after["status"] == "TERMINATED"
        assert record_y_after["termination_date"] == "2026-08-05"

        cx_after = get_claim(cx["id"])
        assert cx_after["status"] == "DENIED"
        assert cx_after["denial_reason"] == "ENROLLMENT_TERMINATED"

        app_z_after = validate_success(
            api.get_enrollment_application(app_z["id"], OFFICER), 200
        )
        assert app_z_after["status"] == "WITHDRAWN"
        # Nothing was recouped anywhere in this scenario.
        assert get_provider_balance(provider["id"]) == 0


class TestTerminationValidation:
    def test_termination_before_effective_date_rejected(self, api):
        """PRD §3.8: "The date must be on or after the record's
        `effective_date`, else `ERR_TERMINATION_DATE_INVALID`; retro-effective
        dates squarely in the past are explicitly allowed, which is where the
        money moves."

        Design: Corner/validations/termination_before_effective_date_rejected
        """
        _, provider, _, payer = setup_group_provider_payer()
        _, record = create_approved_application(provider["id"], payer["id"])
        assert record["effective_date"] == "2026-08-01"

        res = _terminate_record(api, record["id"], "2026-07-01")
        validate_error(res, ApiErrorId.ERR_TERMINATION_DATE_INVALID)

        after = validate_success(api.get_enrollment_record(record["id"], OFFICER), 200)
        assert after["status"] == "ACTIVE"
        assert after["termination_date"] is None

    def test_reverse_recoupment_rejected_when_not_recouped(self, api):
        """PRD §3.8: "Reversal on a claim in any other state is rejected with
        `ERR_CLAIM_NOT_RECOUPED`."

        Design: Corner/state_machines/reverse_recoupment_rejected_when_not_recouped
        """
        _, provider, _, payer = setup_group_provider_payer()
        create_approved_application(provider["id"], payer["id"])
        claim = create_claim(
            provider["id"], payer["id"], service_date="2026-08-01", amount_cents=2000,
        )
        assert claim["status"] == "RELEASED"

        res = api.reverse_recoupment(claim["id"], OFFICER)
        validate_error(res, ApiErrorId.ERR_CLAIM_NOT_RECOUPED)
        assert get_claim(claim["id"])["status"] == "RELEASED"
