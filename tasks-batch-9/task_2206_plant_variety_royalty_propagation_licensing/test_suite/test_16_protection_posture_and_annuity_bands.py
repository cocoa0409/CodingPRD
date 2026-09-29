"""Projecting a filing portfolio onto one posture, and pricing its instalments."""

from test_helpers import (
    BREEDER,
    ApiErrorId,
    create_filing,
    create_variety,
    pay_annuity_payload,
    schedule_annuity_payload,
    validate_error,
    validate_success,
)


class TestThePostureLadderAndTheJurisdictionOrdering:
    """Four filings in four different statuses over one variety."""

    def _four_filing_portfolio(self, api):
        variety = create_variety(
            api, denomination="Gallant Bramble", species="Rubus idaeus",
            breeder_code="GL", base_royalty_cents_per_plant=35,
            base_royalty_cents_per_acre=1200,
        )
        filings = {}
        for code, instrument in (("US", "PLANT_PATENT"),
                                 ("CA", "PLANT_VARIETY_CERTIFICATE"),
                                 ("MX", "PLANT_PATENT"),
                                 ("AU", "PLANT_PATENT")):
            filings[code] = create_filing(
                api, variety["id"], instrument_type=instrument,
                jurisdiction_code=code, annuity_base_cents=200000,
            )
            validate_success(api.file_protection_filing(filings[code]["id"], BREEDER))
        for code in ("US", "CA", "AU"):
            validate_success(api.grant_protection_filing(filings[code]["id"], BREEDER))
        validate_success(api.abandon_protection_filing(filings["MX"]["id"], BREEDER))
        validate_success(api.lapse_protection_filing(filings["AU"]["id"], BREEDER))
        scheduled = validate_success(
            api.schedule_annuity(
                filings["CA"]["id"],
                schedule_annuity_payload(annuity_due_date="2026-10-01T00:00:00Z",
                                         annuity_grace_days=90),
                BREEDER,
            )
        )
        return {"variety_id": variety["id"], "filings": filings, "scheduled": scheduled}

    def test_an_outstanding_annuity_keeps_the_protection_in_force(self, api):
        """Scheduling the Canadian instalment moves that filing off GRANTED, but the
        first branch of the ladder counts MAINTENANCE_DUE as in force, so the
        variety is still PROTECTED.

        PRD 3.1: "Note what follows from the first branch: `MAINTENANCE_DUE` keeps protection in force, so an annuity that is outstanding but still inside its grace window neither drops the posture below `PROTECTED` nor removes its jurisdiction from `protected_jurisdictions`."

        Design: Corner/calculations/protection_posture_projection_ladder_and_lexicographic_jurisdictions
        """
        portfolio = self._four_filing_portfolio(api)

        assert portfolio["scheduled"]["status"] == "MAINTENANCE_DUE"
        assert portfolio["scheduled"]["annuity_sequence_no"] == 1

        variety = validate_success(api.get_variety(portfolio["variety_id"], BREEDER))
        assert variety["protection_posture"] == "PROTECTED"

    def test_the_jurisdiction_list_is_lexicographic_and_excludes_the_dead_filings(self, api):
        """Only the granted and maintenance-due filings contribute a code, and the
        codes come back sorted rather than in the US-first creation order, so the
        abandoned MX and lapsed AU rows appear nowhere.

        PRD 3.1: "`protected_jurisdictions` is then the list of distinct `jurisdiction_code` values taken from exactly those filings whose status is `GRANTED` or `MAINTENANCE_DUE`, sorted lexicographically ascending by the code itself — never by row creation order and never by `id`."

        Design: Corner/calculations/protection_posture_projection_ladder_and_lexicographic_jurisdictions
        """
        portfolio = self._four_filing_portfolio(api)

        variety = validate_success(api.get_variety(portfolio["variety_id"], BREEDER))
        assert variety["protected_jurisdictions"] == ["CA", "US"]

    def test_losing_the_last_in_force_filing_skips_pending_entirely(self, api):
        """Lapsing the two in-force filings one at a time shows the list shrinking
        and then the posture dropping straight to LAPSED_PROTECTION, because the
        abandoned Mexican application feeds none of the four branches.

        PRD 3.1: "Filings in status `ABANDONED` contribute to none of the four branches: an abandoned application is not in force, not pending, and not lapsed."

        Design: Corner/calculations/protection_posture_projection_ladder_and_lexicographic_jurisdictions
        """
        portfolio = self._four_filing_portfolio(api)
        filings = portfolio["filings"]

        validate_success(api.lapse_protection_filing(filings["US"]["id"], BREEDER))
        midway = validate_success(api.get_variety(portfolio["variety_id"], BREEDER))
        assert midway["protection_posture"] == "PROTECTED"
        assert midway["protected_jurisdictions"] == ["CA"]

        validate_success(api.lapse_protection_filing(filings["CA"]["id"], BREEDER))
        final = validate_success(api.get_variety(portfolio["variety_id"], BREEDER))
        assert final["protection_posture"] == "LAPSED_PROTECTION"
        assert final["protected_jurisdictions"] == []


class TestTheVolumeCreditBandBoundaryAtFiveHundredThousandCents:
    """Two instalments one cent apart in base, priced across the credit edge."""

    def _two_scheduled_instalments(self, api):
        variety = create_variety(
            api, denomination="Juneberry Bramble", species="Rubus idaeus",
            breeder_code="JN", base_royalty_cents_per_plant=35,
            base_royalty_cents_per_acre=1200,
        )
        filings = {}
        for code, base in (("US", 500000), ("CA", 499999)):
            filings[code] = create_filing(
                api, variety["id"], instrument_type="PLANT_PATENT",
                jurisdiction_code=code, annuity_base_cents=base,
            )
            validate_success(api.file_protection_filing(filings[code]["id"], BREEDER))
            validate_success(api.grant_protection_filing(filings[code]["id"], BREEDER))
            validate_success(
                api.schedule_annuity(
                    filings[code]["id"],
                    schedule_annuity_payload(annuity_due_date="2026-10-01T00:00:00Z",
                                             annuity_grace_days=90),
                    BREEDER,
                )
            )
        return {"variety_id": variety["id"], "filings": filings}

    def test_a_pre_credit_total_of_exactly_five_hundred_thousand_earns_six_percent(self, api):
        """Paid on time the surcharge is nothing, so the pre-credit total is the base
        500000, which sits at the inclusive start of the six percent band and earns
        a 30000 credit against a payable of 470000.

        PRD 3.2: "When it is 500,000 cents or more the credit is 6 percent of the pre-credit total."

        Design: Corner/calculations/annuity_volume_credit_band_boundary_at_five_hundred_thousand_cents
        """
        setup = self._two_scheduled_instalments(api)

        paid = validate_success(
            api.pay_annuity(setup["filings"]["US"]["id"], pay_annuity_payload(470000),
                            BREEDER)
        )
        assert paid["status"] == "GRANTED"
        assert paid["installments_paid_count"] == 1
        assert paid["annuity_days_late"] == 0
        assert paid["annuity_surcharge_cents"] == 0
        assert paid["annuity_volume_credit_cents"] == 30000
        assert paid["annuity_total_due_cents"] == 470000

    def test_one_cent_lower_falls_into_the_three_percent_band_and_costs_more(self, api):
        """A pre-credit total of 499999 is inside the lower band, earning only 15000
        after half-up rounding, so the smaller obligation is the dearer one to
        discharge.

        PRD 3.2: "When it falls between 200,000 and 499,999 cents inclusive the credit is 3 percent of the pre-credit total."

        Design: Corner/calculations/annuity_volume_credit_band_boundary_at_five_hundred_thousand_cents
        """
        setup = self._two_scheduled_instalments(api)

        paid = validate_success(
            api.pay_annuity(setup["filings"]["CA"]["id"], pay_annuity_payload(484999),
                            BREEDER)
        )
        assert paid["status"] == "GRANTED"
        assert paid["annuity_volume_credit_cents"] == 15000
        assert paid["annuity_total_due_cents"] == 484999
        assert paid["annuity_total_due_cents"] > 470000

    def test_a_single_cent_short_of_the_computed_figure_is_refused(self, api):
        """The payment must match the server's own arithmetic exactly, so tendering
        469999 against a payable of 470000 is rejected rather than partly applied,
        and the two jurisdictions stay in force meanwhile.

        PRD 3.2: "Underpayment and overpayment are both refused outright rather than partially applied, because a partial payment would leave the filing's lapse date ambiguous."

        Design: Corner/calculations/annuity_volume_credit_band_boundary_at_five_hundred_thousand_cents
        """
        setup = self._two_scheduled_instalments(api)

        validate_error(
            api.pay_annuity(setup["filings"]["US"]["id"], pay_annuity_payload(469999),
                            BREEDER),
            ApiErrorId.ERR_ANNUITY_AMOUNT_MISMATCH.value,
            422,
        )

        variety = validate_success(api.get_variety(setup["variety_id"], BREEDER))
        assert variety["protection_posture"] == "PROTECTED"
        assert variety["protected_jurisdictions"] == ["CA", "US"]
