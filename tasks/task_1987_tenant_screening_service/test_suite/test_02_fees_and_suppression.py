"""Difficulty queue A tests: screening-fee rounding and suppression boundaries."""
from test_helpers import (
    TEST_USERS,
    api_client,
    consent_application,
    create_applicant,
    create_application,
    create_jurisdiction_rule,
    get_application,
    get_landlord,
    get_record,
    get_report,
    list_records,
    make_landlord_headers,
    run_record_searches,
    setup_landlord_with_criteria,
    setup_submitted_application,
    submit_application,
    verify_identity,
)

SCREENER = TEST_USERS["screener_headers"]


class TestScreeningFeeRoundPerComponentThenSum:
    def test_three_search_types_round_each_surcharge_first(self):
        """PRD §3.4: "The rounding order is normative: each per-type surcharge
        is rounded half-up to integer cents first — 313 cents per type — then
        the base and the rounded surcharges are summed, and only then is any cap
        applied. Summing the raw fractional surcharges and rounding once at the
        end is non-conformant: for a full three-type search that shortcut yields
        3438 cents, while the pinned order yields 3439."

        Design: Difficulty/combinatorial_formula/screening_fee_round_per_component_then_sum
        """
        create_jurisdiction_rule(state_code="CA", criminal_lookback_years=7, eviction_lookback_years=7)
        landlord, _ = setup_landlord_with_criteria()
        # landlord fixture created the landlord after the rule; the rule setup is fine.
        app, applicant = setup_submitted_application(
            landlord, unit_state_code="CA", monthly_rent_cents=200000
        )
        run_record_searches(app, credit_score=700)
        app_after = get_application(app["id"])
        assert app_after["fee_charged_cents"] == 3439, "2500 + 313*3; per-component rounding, NOT 3438"
        assert get_landlord(landlord["id"])["fee_balance_cents"] == 3439

    def test_criminal_prohibited_state_skips_surcharge(self):
        """PRD §3.4: "The executed search types are credit (always), eviction
        (always), and criminal (only when the covering rule's
        `criminal_lookback_years` is above zero — a prohibited criminal search
        is not executed and is not charged)."

        Design: Difficulty/combinatorial_formula/screening_fee_round_per_component_then_sum
        """
        create_jurisdiction_rule(
            state_code="NY",
            criminal_lookback_years=0,
            eviction_lookback_years=5,
            max_screening_fee_cents=3200,
        )
        landlord, _ = setup_landlord_with_criteria()
        app, applicant = setup_submitted_application(
            landlord, unit_state_code="NY", monthly_rent_cents=200000
        )
        run_record_searches(app, credit_score=700)
        app_after = get_application(app["id"])
        assert app_after["fee_charged_cents"] == 3126, (
            "2500 + 313*2; criminal search prohibited, cap 3200 not binding"
        )
        assert get_landlord(landlord["id"])["fee_balance_cents"] == 3126


class TestRecordExactlyAtLookbackCutoffIncluded:
    def _setup(self):
        create_jurisdiction_rule(
            state_code="CA", criminal_lookback_years=7, eviction_lookback_years=7,
            portable_report_acceptance_required=True,
        )
        landlord, _ = setup_landlord_with_criteria()
        return landlord

    def test_record_dated_exactly_on_cutoff_stays_included(self):
        """PRD §3.4: "The boundary is pinned as strictly-older-than: a record
        dated exactly on its cutoff date stays `INCLUDED`."

        Design: Difficulty/boundary_precision_check/record_exactly_at_lookback_cutoff_included
        """
        landlord = self._setup()
        app, applicant = setup_submitted_application(
            landlord, unit_state_code="CA", monthly_rent_cents=200000
        )
        report = run_record_searches(
            app,
            credit_score=700,
            records=[
                {"record_type": "EVICTION", "jurisdiction_state_code": "CA",
                 "record_date": "2019-08-01T00:00:00Z", "description": "exactly at cutoff"},
                {"record_type": "EVICTION", "jurisdiction_state_code": "CA",
                 "record_date": "2019-07-31T00:00:00Z", "description": "one day before cutoff"},
            ],
        )
        recs = list_records(report["id"])
        assert recs[0]["status"] == "INCLUDED", "record_date == cutoff 2019-08-01 is not strictly older"
        assert recs[1]["status"] == "SUPPRESSED"
        assert recs[1]["suppression_reason"] == "LOOKBACK_EXPIRED"

    def test_cutoff_boundary_updates_included_count_and_fee(self):
        """PRD §3.4: "Throughout the report's life, `included_record_count` is
        an invariant equal to the number of its records in `INCLUDED` status,
        recomputed whenever record statuses change."

        Design: Difficulty/boundary_precision_check/record_exactly_at_lookback_cutoff_included
        """
        landlord = self._setup()
        app, applicant = setup_submitted_application(
            landlord, unit_state_code="CA", monthly_rent_cents=200000
        )
        report = run_record_searches(
            app,
            credit_score=700,
            records=[
                {"record_type": "EVICTION", "jurisdiction_state_code": "CA",
                 "record_date": "2019-08-01T00:00:00Z", "description": "exactly at cutoff"},
                {"record_type": "EVICTION", "jurisdiction_state_code": "CA",
                 "record_date": "2019-07-31T00:00:00Z", "description": "one day before cutoff"},
            ],
        )
        report_after = get_report(report["id"])
        assert report_after["included_record_count"] == 1
        assert get_application(app["id"])["fee_charged_cents"] == 3439, (
            "all three search types execute under the CA rule regardless of record contents"
        )
