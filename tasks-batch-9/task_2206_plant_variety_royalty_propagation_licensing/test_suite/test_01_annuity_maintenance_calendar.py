"""The maintenance calendar: annuity amounts, the repeating lap, and lapse."""

from test_helpers import (
    BREEDER,
    OFFICER,
    ApiErrorId,
    active_agreement,
    active_sublicense,
    advance_clock,
    create_variety,
    granted_filing,
    pay_annuity_payload,
    released_variety,
    schedule_annuity_payload,
    validate_error,
    validate_success,
)


class TestAnnuityAmountDue:
    """POST /protection-filings/{filing_id}/pay-annuity."""

    def _filing_five_days_late(self, api):
        variety = create_variety(
            api, denomination="Glacier Blush", species="Malus domestica", breeder_code="GB",
            royalty_basis_default="PER_PLANT", base_royalty_cents_per_plant=35,
            base_royalty_cents_per_acre=1200,
        )
        filing = granted_filing(
            api, variety["id"], instrument_type="PLANT_PATENT", jurisdiction_code="US",
            term_years=20, annuity_base_cents=481000,
        )
        validate_success(
            api.schedule_annuity(
                filing["id"],
                schedule_annuity_payload(
                    annuity_due_date="2026-09-01T00:00:00Z", annuity_grace_days=30
                ),
                BREEDER,
            )
        )
        advance_clock(api, "2026-09-06T00:00:00Z")
        return variety, filing

    def test_volume_credit_band_is_read_off_the_pre_credit_total(self, api):
        """A credit percentage is chosen by looking up the pre-credit total from
        step three, not the final amount payable.

        A base of 481000 cents plus a 5-percent late surcharge of 24050 cents
        reaches a pre-credit total of 505050 cents, which sits in the 6-percent
        band, so the credit is 30303 cents and the amount payable is 474747.

        PRD 3.2: "A credit percentage is chosen by looking up **the pre-credit total from step three**, not the final amount payable."

        Design: Difficulty/combinatorial_formula/annuity_volume_credit_tier_keyed_on_pre_credit_total
        """
        _variety, filing = self._filing_five_days_late(api)

        paid = validate_success(
            api.pay_annuity(filing["id"], pay_annuity_payload(474747), BREEDER)
        )

        assert paid["annuity_days_late"] == 5
        assert paid["annuity_surcharge_cents"] == 24050
        assert paid["annuity_volume_credit_cents"] == 30303
        assert paid["annuity_total_due_cents"] == 474747
        assert paid["status"] == "GRANTED"
        assert paid["installments_paid_count"] == 1

    def test_payment_keyed_on_the_post_credit_figure_is_rejected(self, api):
        """The post-credit keying would land the filing in the 3-percent band and
        ask for 489898 cents, which the server refuses outright.

        PRD 3.2: "If `paid_amount_cents` differs from that figure in either direction, the payment is rejected with `ERR_ANNUITY_AMOUNT_MISMATCH` (HTTP 422)."

        Design: Difficulty/combinatorial_formula/annuity_volume_credit_tier_keyed_on_pre_credit_total
        """
        _variety, filing = self._filing_five_days_late(api)

        validate_error(
            api.pay_annuity(filing["id"], pay_annuity_payload(489898), BREEDER),
            ApiErrorId.ERR_ANNUITY_AMOUNT_MISMATCH.value,
            422,
        )

        unchanged = validate_success(api.get_protection_filing(filing["id"], BREEDER))
        assert unchanged["status"] == "MAINTENANCE_DUE"
        assert unchanged["installments_paid_count"] == 0

    def test_surcharge_is_assessed_on_the_base_amount_for_the_floored_day_count(self, api):
        """Five whole days late attracts the 1-to-30-day band, five percent of the
        base amount, and nothing more.

        PRD 3.2: "From 1 through 30 days late inclusive the surcharge is 5 percent of `annuity_base_cents`."

        Design: Difficulty/combinatorial_formula/annuity_volume_credit_tier_keyed_on_pre_credit_total
        """
        _variety, filing = self._filing_five_days_late(api)

        paid = validate_success(
            api.pay_annuity(filing["id"], pay_annuity_payload(474747), BREEDER)
        )

        assert paid["annuity_surcharge_cents"] == 24050
        assert paid["annuity_base_cents"] == 481000
        assert paid["annuity_days_late"] == 5


class TestMaintenanceCycleLaps:
    """The GRANTED -> MAINTENANCE_DUE -> GRANTED cycle of one filing."""

    def _granted_filing(self, api):
        variety = create_variety(
            api, denomination="Frostline Sweet", species="Prunus avium", breeder_code="FS",
            royalty_basis_default="PER_PLANT", base_royalty_cents_per_plant=35,
            base_royalty_cents_per_acre=1200,
        )
        filing = granted_filing(
            api, variety["id"], instrument_type="PLANT_PATENT", jurisdiction_code="US",
            term_years=20, annuity_base_cents=481000,
        )
        return variety, filing

    def test_scheduling_an_annuity_opens_a_lap_without_dropping_the_posture(self, api):
        """Posting the instalment lifts the filing into MAINTENANCE_DUE and
        advances the lap ordinal, while the variety stays PROTECTED because
        MAINTENANCE_DUE is still in force.

        PRD 3.2: "The variety's `protection_posture` is deliberately unchanged, because `MAINTENANCE_DUE` is still in force."

        Design: Difficulty/non_linear_state_machine/protection_filing_maintenance_cycle_relaps_without_a_terminal_stop
        """
        variety, filing = self._granted_filing(api)

        scheduled = validate_success(
            api.schedule_annuity(
                filing["id"],
                schedule_annuity_payload(
                    annuity_due_date="2026-09-01T00:00:00Z", annuity_grace_days=30
                ),
                BREEDER,
            )
        )

        assert scheduled["status"] == "MAINTENANCE_DUE"
        assert scheduled["annuity_sequence_no"] == 1
        assert scheduled["installments_paid_count"] == 0

        parent = validate_success(api.get_variety(variety["id"], BREEDER))
        assert parent["protection_posture"] == "PROTECTED"
        assert parent["protected_jurisdictions"] == ["US"]

    def test_second_lap_advances_the_ordinal_and_resets_the_per_lap_money(self, api):
        """Closing the first lap counts one instalment; opening the second lap
        overwrites rather than accumulates the annuity figures, and the posture
        is flat across the whole cycle.

        PRD 3.2: "The figures from an earlier lap are overwritten, never accumulated — the filing always describes the obligation currently outstanding."

        Design: Difficulty/non_linear_state_machine/protection_filing_maintenance_cycle_relaps_without_a_terminal_stop
        """
        variety, filing = self._granted_filing(api)
        validate_success(
            api.schedule_annuity(
                filing["id"],
                schedule_annuity_payload(
                    annuity_due_date="2026-09-01T00:00:00Z", annuity_grace_days=30
                ),
                BREEDER,
            )
        )
        advance_clock(api, "2026-09-06T00:00:00Z")
        first_lap = validate_success(
            api.pay_annuity(filing["id"], pay_annuity_payload(474747), BREEDER)
        )
        assert first_lap["status"] == "GRANTED"
        assert first_lap["installments_paid_count"] == 1
        assert first_lap["annuity_days_late"] == 5
        assert first_lap["annuity_total_due_cents"] == 474747

        second_lap = validate_success(
            api.schedule_annuity(
                filing["id"],
                schedule_annuity_payload(
                    annuity_due_date="2027-09-01T00:00:00Z", annuity_grace_days=30
                ),
                BREEDER,
            )
        )

        assert second_lap["status"] == "MAINTENANCE_DUE"
        assert second_lap["annuity_sequence_no"] == 2
        assert second_lap["installments_paid_count"] == 1
        assert second_lap["annuity_days_late"] == 0
        assert second_lap["annuity_surcharge_cents"] == 0
        assert second_lap["annuity_volume_credit_cents"] == 0
        assert second_lap["annuity_total_due_cents"] == 0

        parent = validate_success(api.get_variety(variety["id"], BREEDER))
        assert parent["protection_posture"] == "PROTECTED"

    def test_paying_an_annuity_while_the_filing_is_granted_is_rejected(self, api):
        """There is no outstanding instalment on a GRANTED filing, so the payment
        endpoint finds the record outside its origin state.

        PRD 2.8: "Generic transition legality — `ERR_INVALID_STATE_TRANSITION` (HTTP 409), raised when the target's current state is not a declared origin state for the action being attempted."

        Design: Difficulty/non_linear_state_machine/protection_filing_maintenance_cycle_relaps_without_a_terminal_stop
        """
        _variety, filing = self._granted_filing(api)

        validate_error(
            api.pay_annuity(filing["id"], pay_annuity_payload(474747), BREEDER),
            ApiErrorId.ERR_INVALID_STATE_TRANSITION.value,
            409,
        )


class TestGraceExpiryCascade:
    """Advancing the clock past the grace boundary of a maintained filing."""

    def _released_variety_with_active_sublicense(self, api):
        bundle = released_variety(
            api, denomination="Meridian Snow", species="Malus domestica", breeder_code="MS",
            royalty_basis_default="PER_PLANT", base_royalty_cents_per_plant=35,
            base_royalty_cents_per_acre=1200,
        )
        chain = active_agreement(
            api, quality_tier="TIER_A", territory_codes=["US-WA"],
            propagator_name="Cascade Retail Nurseries",
        )
        grant = active_sublicense(
            api, chain, bundle["variety"]["id"],
            sublicensee_name="Greenline Garden Centers",
            territory_code="US-WA", jurisdiction_code="US", exclusivity="EXCLUSIVE",
            effective_date="2026-10-01T00:00:00Z", expiry_date="2027-06-01T00:00:00Z",
        )
        validate_success(
            api.schedule_annuity(
                bundle["filing"]["id"],
                schedule_annuity_payload(
                    annuity_due_date="2026-10-01T00:00:00Z", annuity_grace_days=30
                ),
                BREEDER,
            )
        )
        return bundle, chain, grant

    def test_grace_expiry_lapses_the_filing_and_strips_the_jurisdiction(self, api):
        """The clock advance alone lapses the filing with GRACE_EXPIRED and
        re-derives the variety down to LAPSED_PROTECTION with an empty
        jurisdiction list.

        PRD 3.2: "The first is the clock sweep: a filing still in `MAINTENANCE_DUE` when the logical clock passes strictly beyond `annuity_due_date` plus `annuity_grace_days` days is moved to `LAPSED` with `lapse_reason` set to `GRACE_EXPIRED`."

        Design: Difficulty/transitive_cascade/annuity_grace_expiry_lapses_filing_then_strips_jurisdiction_then_revokes_sublicense_then_decrements_count
        """
        bundle, _chain, _grant = self._released_variety_with_active_sublicense(api)
        variety_id = bundle["variety"]["id"]
        filing_id = bundle["filing"]["id"]

        before = validate_success(api.get_variety(variety_id, BREEDER))
        assert before["lifecycle_state"] == "RELEASED"
        assert before["protection_posture"] == "PROTECTED"
        assert before["protected_jurisdictions"] == ["US"]
        assert before["active_sublicense_count"] == 1

        advance_clock(api, "2026-11-01T00:00:00Z")

        lapsed = validate_success(api.get_protection_filing(filing_id, BREEDER))
        assert lapsed["status"] == "LAPSED"
        assert lapsed["lapse_reason"] == "GRACE_EXPIRED"

        after = validate_success(api.get_variety(variety_id, BREEDER))
        assert after["protection_posture"] == "LAPSED_PROTECTION"
        assert after["protected_jurisdictions"] == []
        assert after["lifecycle_state"] == "RELEASED"

    def test_grace_expiry_revokes_the_active_grant_and_decrements_the_count(self, api):
        """The jurisdiction dropping out revokes the grant with
        PROTECTION_LAPSED, and that revocation decrements the variety's active
        sublicense count.

        PRD 3.2: "Level two, caused by that jurisdiction dropping out, revokes every sublicense grant of the same variety and the same `jurisdiction_code` that is currently `ACTIVE`, setting each one's `revocation_reason` to `PROTECTION_LAPSED`; those grants are processed by `created_at` ascending, ties broken by `territory_code` ascending and then by `sublicensee_name` ascending."

        Design: Difficulty/transitive_cascade/annuity_grace_expiry_lapses_filing_then_strips_jurisdiction_then_revokes_sublicense_then_decrements_count
        """
        bundle, _chain, grant = self._released_variety_with_active_sublicense(api)

        advance_clock(api, "2026-11-01T00:00:00Z")

        revoked = validate_success(api.get_sublicense_grant(grant["id"], OFFICER))
        assert revoked["status"] == "REVOKED"
        assert revoked["revocation_reason"] == "PROTECTION_LAPSED"

        variety = validate_success(api.get_variety(bundle["variety"]["id"], BREEDER))
        assert variety["active_sublicense_count"] == 0

        validate_error(
            api.activate_sublicense_grant(grant["id"], OFFICER),
            ApiErrorId.ERR_TERMINAL_STATE.value,
            409,
        )

    def test_sweep_counters_report_the_lapse_and_not_an_expiry(self, api):
        """The grant left ACTIVE by revocation, not by expiry, so the sweep
        counts one lapsed filing and no expired grant.

        PRD 2.5: "The clock capability answers with the resulting `current_utc` plus four counters describing what the sweep did: `lapsed_filing_count`, `brand_renewal_due_count`, `expired_grant_count` and `compliance_recompute_count`."

        Design: Difficulty/transitive_cascade/annuity_grace_expiry_lapses_filing_then_strips_jurisdiction_then_revokes_sublicense_then_decrements_count
        """
        self._released_variety_with_active_sublicense(api)

        sweep = validate_success(
            api.set_current_utc({"current_utc": "2026-11-01T00:00:00Z"}, BREEDER)
        )

        assert sweep["lapsed_filing_count"] == 1
        assert sweep["expired_grant_count"] == 0
