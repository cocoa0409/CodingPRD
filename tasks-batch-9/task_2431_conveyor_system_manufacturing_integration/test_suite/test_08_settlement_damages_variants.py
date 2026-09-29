"""Liquidated damages under the two rival bases, computed at filing."""

from test_helpers import (
    CUSTOMER_REP,
    ApiErrorId,
    assert_acceptance_certificate,
    assert_performance_dispute,
    create_performance_dispute_payload,
    make_accepted_project,
    make_disputed_certificate,
    read_certificate,
    read_project,
    validate_error,
)


class TestBothDamagesReadingsAreComputedAtFiling:
    """One claimed rate, two contractual theories, both stored."""

    def test_the_certificate_snapshots_retention_and_bottleneck_availability(self, api):
        """Five percent of 243,600,000 cents is 12,180,000, and the bottleneck ran at 95.

        PRD §3.7: "Its `retention_amount_cents` is the project's `contract_value_cents`
        multiplied by 500 basis points, that is five percent, divided by 10000 and
        rounded half up to a whole cent."

        Design: Difficulty/dual_variant_calc/liquidated_damages_nameplate_vs_observed_availability
        """
        state = make_accepted_project(api)
        certificate = state["certificate"]

        assert_acceptance_certificate(certificate)
        assert certificate["retention_amount_cents"] == 12_180_000
        assert certificate["retention_release_cents"] == 0
        assert certificate["bottleneck_availability_pct"] == 95
        assert certificate["status"] == "ISSUED"

    def test_the_nameplate_reading_charges_every_carton_of_shortfall(self, api):
        """A claimed 1150 against a required 1250 is eight points, worth 9,744,000 cents.

        PRD §3.9: "Under the `NAMEPLATE` reading — the customer's theory, that the
        contract promised the required rate at the meter — the basis rate is the observed
        rate unmodified, so every carton of measured shortfall is chargeable."

        Design: Difficulty/dual_variant_calc/liquidated_damages_nameplate_vs_observed_availability
        """
        state = make_disputed_certificate(api, claimed_cph=1150, damages_basis="NAMEPLATE")
        dispute = state["dispute"]

        assert_performance_dispute(dispute)
        assert dispute["claimed_cph"] == 1150
        assert dispute["damages_basis"] == "NAMEPLATE"
        assert dispute["provisional_nameplate_cents"] == 9_744_000

    def test_the_observed_availability_reading_grosses_the_rate_up(self, api):
        """1150 grossed up by 95 percent floors at 1210, three points, 3,654,000 cents.

        PRD §3.9: "Under the `OBSERVED_AVAILABILITY` reading — the integrator's theory,
        that the promise was capacity at the bottleneck's design availability — the basis
        rate is the observed rate multiplied by 100 and divided by the certificate's
        snapshotted `bottleneck_availability_pct`, discarding any fractional remainder;
        grossing the rate up this way shrinks, and frequently zeroes, the shortfall."

        Design: Difficulty/dual_variant_calc/liquidated_damages_nameplate_vs_observed_availability
        """
        state = make_disputed_certificate(api, claimed_cph=1150, damages_basis="NAMEPLATE")
        dispute = state["dispute"]

        assert dispute["provisional_observed_cents"] == 3_654_000
        assert dispute["provisional_observed_cents"] < dispute["provisional_nameplate_cents"]

    def test_the_declared_basis_selects_the_binding_figure(self, api):
        """Declaring NAMEPLATE binds the larger of the two readings.

        PRD §3.9: "Both readings are stored, as `provisional_nameplate_cents` and
        `provisional_observed_cents`, and `bound_provisional_cents` records whichever of
        the two the declared `damages_basis` selects."

        Design: Difficulty/dual_variant_calc/liquidated_damages_nameplate_vs_observed_availability
        """
        state = make_disputed_certificate(api, claimed_cph=1150, damages_basis="NAMEPLATE")
        dispute = state["dispute"]

        assert dispute["bound_provisional_cents"] == 9_744_000
        assert dispute["bound_provisional_cents"] == dispute["provisional_nameplate_cents"]

    def test_declaring_the_other_basis_binds_the_other_reading(self, api):
        """The same claimed rate under OBSERVED_AVAILABILITY binds 3,654,000 cents.

        PRD §3.9: "Filing computes **both** damages readings, so the record shows what
        each party's theory is worth."

        Design: Difficulty/dual_variant_calc/liquidated_damages_nameplate_vs_observed_availability
        """
        state = make_disputed_certificate(
            api, claimed_cph=1150, damages_basis="OBSERVED_AVAILABILITY"
        )
        dispute = state["dispute"]

        assert dispute["provisional_nameplate_cents"] == 9_744_000
        assert dispute["provisional_observed_cents"] == 3_654_000
        assert dispute["bound_provisional_cents"] == 3_654_000

    def test_filing_disputes_the_certificate_without_disturbing_delivery(self, api):
        """The commercial axis moves to DISPUTED while the project stays ACCEPTED.

        PRD §3.9: "And the project's `commercial_status` moves from `CLEAN` to
        `DISPUTED`, incrementing the project's `version` — a move that leaves
        `delivery_status` completely alone, so an `ACCEPTED` project stays `ACCEPTED`
        while the argument runs."

        Design: Difficulty/dual_variant_calc/liquidated_damages_nameplate_vs_observed_availability
        """
        state = make_disputed_certificate(api, claimed_cph=1150, damages_basis="NAMEPLATE")

        assert state["dispute"]["status"] == "OPEN"
        assert state["dispute"]["filed_by_user_id"] == CUSTOMER_REP["X-User-ID"]
        for field in (
            "retest_measured_cph",
            "final_damages_cents",
            "sla_credit_cents",
            "retest_by_user_id",
            "retest_recorded_at",
        ):
            assert state["dispute"][field] is None

        assert state["certificate"]["status"] == "DISPUTED"
        project = read_project(api, state["project"]["id"])
        assert project["commercial_status"] == "DISPUTED"
        assert project["delivery_status"] == "ACCEPTED"

    def test_a_second_dispute_against_the_same_certificate_is_refused(self, api):
        """A certificate already under attack cannot be disputed twice.

        PRD §3.9: "the certificate's `status` must be `ISSUED`, and one already
        `DISPUTED`, `UPHELD` or `REVISED` is rejected with
        `ERR_CERTIFICATE_ALREADY_DISPUTED`"

        Design: Difficulty/dual_variant_calc/liquidated_damages_nameplate_vs_observed_availability
        """
        state = make_disputed_certificate(api, claimed_cph=1150, damages_basis="NAMEPLATE")

        response = api.create_performance_dispute(
            create_performance_dispute_payload(
                state["certificate"]["id"], 1100, "OBSERVED_AVAILABILITY"
            ),
            CUSTOMER_REP,
        )
        validate_error(response, ApiErrorId.ERR_CERTIFICATE_ALREADY_DISPUTED.value)
        assert read_certificate(api, state["certificate"]["id"])["status"] == "DISPUTED"
