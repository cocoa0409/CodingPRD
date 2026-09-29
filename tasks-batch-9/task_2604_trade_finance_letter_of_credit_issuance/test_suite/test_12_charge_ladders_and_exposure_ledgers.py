"""Charge ladders, exposure variants and the aggregate ledgers they feed.

The commission floor where it bites and where it is inert, the flat-rate tier ladder at both
of its edges, the provisional-versus-committed reconciliation on one credit, the facility
ledger's open-row-only input set, the collateral running total and its non-negativity guard,
and the amendment recharge that prices only the delta.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import (
    api_client,
    approved_credit,
    assert_chargeable_sum,
    assert_facility_ledger,
    assert_fields_equal,
    assert_instant_with_milliseconds,
    assert_issuance_charges,
    assert_ledger_identity,
    cancel_credit,
    credit_officer_headers,
    draft_amendment,
    draft_credit,
    factories,
    issue_amendment,
    issue_credit,
    issued_credit,
    list_credit_allocation_rows,
    list_facility_allocation_rows,
    post_collateral,
    set_clock,
    setup_parties,
)

CONSENT_REFERENCE = "BEN-CONSENT-2026-0117"

# The design's counterparty triangle: a Norwegian applicant and advising bank against a
# Latvian beneficiary. None of the three codes is sanctioned, so every `CREDIT_PARTIES`
# screening created by issuance scores zero.
_BANK = {"country_code": "NO", "country_risk_score": 12, "credit_rating": "AA"}
_BENEFICIARY = {"country_code": "LV"}

SHORT_DATED = {
    "latest_shipment_date": "2026-09-10",
    "expiry_date": "2026-09-30",
    "presentation_period_days": 20,
}


def _parties(limit_cents=50000000, **facility_overrides):
    facility = {"limit_cents": limit_cents, "collateral_required_pct": 0}
    facility.update(facility_overrides)
    return setup_parties(facility=facility, bank=_BANK, beneficiary=_BENEFICIARY)


def _read_facility(facility_id):
    return validate_success(api_client.get_facility(facility_id, credit_officer_headers()))


def _allocation_page(facility_id, **params):
    return validate_paginated(
        api_client.list_facility_allocations(
            facility_id, credit_officer_headers(), params or None
        )
    )


class TestMinimumCommissionFloorIsAFloorAndNotAnAlternative:
    """The 25,000-cent floor decides one credit's commission and leaves the next alone."""

    def test_a_small_short_dated_credit_prices_at_the_floor_not_at_its_computed_rate(
        self, clock
    ):
        """3,000,000 for one quarter at 15 bps computes 4,500 and stores the 25,000 floor.

        PRD 3.3: "Third, `base_commission_cents` is the larger of a 25,000-cent floor and
        the result of multiplying `gross_exposure_cents` by `commission_bps_applied` and by
        the quarter count, dividing by 10,000 and rounding half up."

        PRD 3.3: "Second, the commission tier is selected from `gross_exposure_cents`
        **alone** and is recorded in `commission_bps_applied`: 15 basis points when
        `gross_exposure_cents` is at most 5,000,000 cents, 10 basis points when it is above
        that but at most 50,000,000 cents, and 7 basis points above that."

        Design: Corner/calculations/issuance_charges_minimum_commission_floor_applies
        """
        parties = _parties()
        f1 = approved_credit(parties, amount_cents=3000000, **SHORT_DATED)

        credit = issue_credit(f1.credit_id)

        assert_issuance_charges(
            credit,
            gross_exposure_cents=3000000,
            commission_bps_applied=15,
            base_commission_cents=25000,
            confirmation_charge_cents=0,
            total_charge_cents=25000,
            committed_allocation_cents=3000000,
            chargeable_utilisation_cents=3025000,
        )
        assert credit["base_commission_cents"] != 4500
        assert_chargeable_sum(credit)
        assert_facility_ledger(
            parties.refresh_facility(),
            allocated_cents=3025000,
            available_cents=46975000,
            utilisation_posture="OPEN",
        )

    def test_a_larger_credit_over_two_quarters_keeps_its_computed_commission(self, clock):
        """20,000,000 at 10 bps over two quarters computes 40,000, well above the floor.

        PRD 3.3: "First, the validity of the credit in days is the number of days from
        `issue_date` to `expiry_date` counting **both ends inclusive** — that is, the day
        difference plus one."

        PRD 3.3: "Third, `base_commission_cents` is the larger of a 25,000-cent floor and
        the result of multiplying `gross_exposure_cents` by `commission_bps_applied` and by
        the quarter count, dividing by 10,000 and rounding half up."

        Design: Corner/calculations/issuance_charges_minimum_commission_floor_applies
        """
        parties = _parties()
        f1 = approved_credit(parties, amount_cents=3000000, **SHORT_DATED)
        f2 = approved_credit(parties, amount_cents=20000000)

        issue_credit(f1.credit_id)
        credit = issue_credit(f2.credit_id)

        assert_issuance_charges(
            credit,
            gross_exposure_cents=20000000,
            commission_bps_applied=10,
            base_commission_cents=40000,
            total_charge_cents=40000,
            chargeable_utilisation_cents=20040000,
        )
        assert credit["base_commission_cents"] != 25000
        assert_facility_ledger(
            parties.refresh_facility(),
            allocated_cents=23065000,
            available_cents=26935000,
            utilisation_posture="OPEN",
        )


class TestCommissionTierLadderIsFlatRateAndNotMarginal:
    """Four credits issued the same day straddle both tier edges by a single cent."""

    def test_one_cent_across_the_lower_edge_switches_the_rate_under_a_shared_floor(
        self, clock
    ):
        """5,000,000 takes 15 bps and 5,000,001 takes 10 bps, yet both land on the floor.

        PRD 3.3: "Second, the commission tier is selected from `gross_exposure_cents`
        **alone** and is recorded in `commission_bps_applied`: 15 basis points when
        `gross_exposure_cents` is at most 5,000,000 cents, 10 basis points when it is above
        that but at most 50,000,000 cents, and 7 basis points above that."

        PRD 3.3: "Third, `base_commission_cents` is the larger of a 25,000-cent floor and
        the result of multiplying `gross_exposure_cents` by `commission_bps_applied` and by
        the quarter count, dividing by 10,000 and rounding half up."

        Design: Corner/calculations/issuance_charges_tier_ladder_is_not_marginal_at_either_boundary
        """
        parties = _parties(limit_cents=500000000)
        t1 = approved_credit(parties, amount_cents=5000000)
        t2 = approved_credit(parties, amount_cents=5000001)

        first = issue_credit(t1.credit_id)
        second = issue_credit(t2.credit_id)

        assert_issuance_charges(
            first,
            gross_exposure_cents=5000000,
            commission_bps_applied=15,
            base_commission_cents=25000,
            total_charge_cents=25000,
            chargeable_utilisation_cents=5025000,
        )
        assert first["base_commission_cents"] != 15000
        assert_issuance_charges(
            second,
            gross_exposure_cents=5000001,
            commission_bps_applied=10,
            base_commission_cents=25000,
            total_charge_cents=25000,
            chargeable_utilisation_cents=5025001,
        )
        assert second["base_commission_cents"] != 10000
        assert_facility_ledger(
            parties.refresh_facility(),
            allocated_cents=10050001,
            available_cents=489949999,
            restrict_threshold_cents=475000000,
            utilisation_posture="OPEN",
        )

    def test_one_cent_across_the_upper_edge_makes_the_bigger_credit_strictly_cheaper(
        self, clock
    ):
        """50,000,000 pays 100,000 while 50,000,001 pays 70,000 — the rate applies to the whole.

        PRD 3.3: "Second, the commission tier is selected from `gross_exposure_cents`
        **alone** and is recorded in `commission_bps_applied`: 15 basis points when
        `gross_exposure_cents` is at most 5,000,000 cents, 10 basis points when it is above
        that but at most 50,000,000 cents, and 7 basis points above that."

        PRD 3.3: "Fifth and last, `total_charge_cents` is `base_commission_cents` plus
        `confirmation_charge_cents`, and `chargeable_utilisation_cents` is
        `committed_allocation_cents` plus `total_charge_cents`."

        Design: Corner/calculations/issuance_charges_tier_ladder_is_not_marginal_at_either_boundary
        """
        parties = _parties(limit_cents=500000000)
        ladder = [
            approved_credit(parties, amount_cents=amount)
            for amount in (5000000, 5000001, 50000000, 50000001)
        ]

        issued = [issue_credit(ctx.credit_id) for ctx in ladder]

        assert_issuance_charges(
            issued[2],
            gross_exposure_cents=50000000,
            commission_bps_applied=10,
            base_commission_cents=100000,
            total_charge_cents=100000,
            chargeable_utilisation_cents=50100000,
        )
        assert_issuance_charges(
            issued[3],
            gross_exposure_cents=50000001,
            commission_bps_applied=7,
            base_commission_cents=70000,
            total_charge_cents=70000,
            chargeable_utilisation_cents=50070001,
        )
        assert issued[3]["base_commission_cents"] != 100000
        assert issued[3]["base_commission_cents"] < issued[2]["base_commission_cents"]
        facility = parties.refresh_facility()
        assert_facility_ledger(
            facility,
            allocated_cents=110220002,
            available_cents=389779998,
            restrict_threshold_cents=475000000,
            utilisation_posture="OPEN",
        )
        assert_ledger_identity(facility)


class TestProvisionalAndCommittedExposureMeasureTheSameCreditTwice:
    """An ACCEPTANCE credit of 20,000,000 with a 5 percent tolerance and a 60-day tenor."""

    ACCEPTANCE_TERMS = {
        "amount_cents": 20000000,
        "available_by": "ACCEPTANCE",
        "tenor_days": 60,
        "tolerance_pct": 5,
    }

    def test_the_draft_estimate_suppresses_tolerance_and_tenor_and_occupies_nothing(
        self, clock
    ):
        """The provisional run forces both to zero, so the estimate is the face amount.

        PRD 3.2: "The provisional estimate is computed by the same five-step exposure rule
        the bank uses at issuance, but run with the tolerance and the tenor deliberately
        forced to zero, because a draft is not yet an undertaking."

        PRD 3.2: "And a **provisional exposure estimate** is written to
        `provisional_allocation_cents`, which is important to understand for what it is not:
        it never debits the facility, no allocation row is created, and the facility's
        `allocated_cents` is untouched."

        Design: Corner/calculations/credit_allocation_reconciles_provisional_draft_against_committed_issuance
        """
        parties = _parties()

        ctx = draft_credit(parties, **self.ACCEPTANCE_TERMS)

        assert ctx.credit["provisional_allocation_cents"] == 20000000
        assert_facility_ledger(
            parties.refresh_facility(),
            allocated_cents=0,
            available_cents=50000000,
            utilisation_posture="OPEN",
            status="ACTIVE",
        )
        assert list_credit_allocation_rows(ctx.credit_id) == []

    def test_issuance_switches_variants_and_the_delta_is_the_tolerance_plus_the_tenor(
        self, clock
    ):
        """Committed exposure admits the 5 percent tolerance and the two-month add-on.

        PRD 3.3: "The **committed exposure** is the same five-step rule that produced the
        provisional estimate, now run in earnest: the tolerance and the tenor both count."

        PRD 3.3: "Step two prices the usance risk add-on in whole months rounded **up**: for
        a credit available by `SIGHT_PAYMENT` the month count is zero, and otherwise it is
        `tenor_days` divided by 30 and rounded up to the next whole number; the add-on is
        then `max_drawable_cents` multiplied by 25, multiplied by that month count, divided
        by 10,000 with the remainder discarded — twenty-five basis points of the drawable
        ceiling for every whole or part month of usance."

        Design: Corner/calculations/credit_allocation_reconciles_provisional_draft_against_committed_issuance
        """
        parties = _parties()
        ctx = approved_credit(parties, **self.ACCEPTANCE_TERMS)
        provisional = ctx.credit["provisional_allocation_cents"]

        credit = issue_credit(ctx.credit_id)

        assert provisional == 20000000
        assert_issuance_charges(
            credit,
            max_drawable_cents=21000000,
            gross_exposure_cents=21105000,
            committed_allocation_cents=21105000,
            commission_bps_applied=10,
            base_commission_cents=42210,
            chargeable_utilisation_cents=21147210,
        )
        assert credit["committed_allocation_cents"] != 20000000
        assert credit["committed_allocation_cents"] - provisional == 1105000
        assert_facility_ledger(
            parties.refresh_facility(),
            allocated_cents=21147210,
            available_cents=28852790,
            utilisation_posture="OPEN",
        )


class TestFacilityExposureSumsOpenAllocationRowsOnly:
    """Two issuances and one cancellation leave two rows but only one in the sum."""

    def test_the_released_row_survives_as_history_and_leaves_the_sum(self, clock):
        """`allocated_cents` falls back to one row's worth while the released row remains.

        PRD 3.1: "Whenever an allocation row is inserted, has its charges changed, or is
        released, `allocated_cents` is recomputed as the sum, over every allocation row on
        this facility whose `status` is `OPEN`, of that row's `allocated_cents` plus its
        `charge_cents`; released rows are excluded from the sum entirely and their
        `released_cents` is a historical record only."

        PRD 3.3: "Every `OPEN` allocation row of the credit flips to `RELEASED` with
        `released_cents` set to that row's own `allocated_cents` plus its `charge_cents` and
        `released_at` set to the clock instant, and the row's `version` increments."

        Design: Corner/calculations/facility_exposure_ledger_counts_only_open_allocation_rows
        """
        parties = _parties()
        g1 = issued_credit(parties)
        g2 = issued_credit(parties)
        assert_facility_ledger(parties.refresh_facility(), allocated_cents=20050000)

        cancel_credit(
            g1.credit_id,
            reason="Underlying contract terminated",
            beneficiary_consent_reference=CONSENT_REFERENCE,
        )

        rows, meta = _allocation_page(parties.facility_id, status="RELEASED")
        assert meta["total_count"] == 1
        assert len(rows) == 1
        assert rows[0]["credit_id"] == g1.credit_id
        assert rows[0]["status"] == "RELEASED"
        assert rows[0]["released_cents"] == 10025000
        assert_instant_with_milliseconds(rows[0]["released_at"], "released_at")
        facility = parties.refresh_facility()
        assert facility["allocated_cents"] == 10025000
        assert facility["allocated_cents"] != 20050000
        assert_facility_ledger(facility, available_cents=39975000, utilisation_posture="OPEN")
        assert g2.refresh()["status"] == "ISSUED"

    def test_both_rows_are_still_listed_and_only_the_open_one_carries_exposure(self, clock):
        """The unfiltered listing returns both rows; the `OPEN` filter returns the survivor.

        PRD 3.1: "Whenever an allocation row is inserted, has its charges changed, or is
        released, `allocated_cents` is recomputed as the sum, over every allocation row on
        this facility whose `status` is `OPEN`, of that row's `allocated_cents` plus its
        `charge_cents`; released rows are excluded from the sum entirely and their
        `released_cents` is a historical record only."

        Design: Corner/calculations/facility_exposure_ledger_counts_only_open_allocation_rows
        """
        parties = _parties()
        g1 = issued_credit(parties)
        g2 = issued_credit(parties)

        cancel_credit(
            g1.credit_id,
            reason="Underlying contract terminated",
            beneficiary_consent_reference=CONSENT_REFERENCE,
        )

        open_rows, open_meta = _allocation_page(parties.facility_id, status="OPEN")
        assert open_meta["total_count"] == 1
        assert len(open_rows) == 1
        assert open_rows[0]["credit_id"] == g2.credit_id
        assert open_rows[0]["allocated_cents"] == 10000000
        assert open_rows[0]["charge_cents"] == 25000
        every_row, every_meta = _allocation_page(parties.facility_id)
        assert every_meta["total_count"] == 2
        assert len(every_row) == 2
        assert {row["status"] for row in every_row} == {"OPEN", "RELEASED"}
        assert len(list_facility_allocation_rows(parties.facility_id)) == 2


class TestCollateralPostedIsARunningTotalWithANonNegativityGuard:
    """A facility requiring 50 percent collateral and holding no credits at all."""

    @staticmethod
    def _post_ladder(facility_id, opening_version):
        first = post_collateral(facility_id, 5000000, opening_version, posting_note="first cash margin")
        second = post_collateral(facility_id, 3000000, first["version"], posting_note="top up")
        third = post_collateral(
            facility_id, -2000000, second["version"], posting_note="partial release"
        )
        return first, second, third

    def test_each_posting_adds_to_the_previous_total_rather_than_replacing_it(self, clock):
        """5,000,000 then 3,000,000 reads 8,000,000, and a 2,000,000 release reads 6,000,000.

        PRD 3.1: "The facility's `collateral_posted_cents` becomes its previous value plus
        the supplied `amount_cents`, postings being applied in arrival order, and the
        facility's `version` increments."

        PRD 3.1: "A `CreditOfficer` posts collateral by supplying an `amount_cents`, which is
        the one money field in this service that may legitimately be negative: a positive
        value posts collateral, a negative value releases it."

        Design: Corner/calculations/collateral_posted_ledger_is_a_running_total_that_cannot_go_negative
        """
        parties = _parties(collateral_required_pct=50)
        opening = parties.refresh_facility()
        assert opening["collateral_posted_cents"] == 0

        first, second, third = self._post_ladder(parties.facility_id, opening["version"])

        assert first["collateral_posted_cents"] == 5000000
        assert second["collateral_posted_cents"] == 8000000
        assert second["collateral_posted_cents"] != 3000000
        assert third["collateral_posted_cents"] == 6000000
        assert third["version"] == opening["version"] + 3
        assert_facility_ledger(
            _read_facility(parties.facility_id),
            allocated_cents=0,
            available_cents=50000000,
            utilisation_posture="OPEN",
            status="ACTIVE",
        )

    def test_a_release_deeper_than_the_total_is_refused_and_writes_nothing(self, clock):
        """Releasing 7,000,000 out of 6,000,000 is rejected and the total does not clamp to zero.

        PRD 3.1: "A release that would drive `collateral_posted_cents` below zero is rejected
        with `ERR_COLLATERAL_RELEASE_EXCEEDS_POSTED` (422)."

        PRD 3.1: "The facility's `collateral_posted_cents` becomes its previous value plus
        the supplied `amount_cents`, postings being applied in arrival order, and the
        facility's `version` increments."

        Design: Corner/calculations/collateral_posted_ledger_is_a_running_total_that_cannot_go_negative
        """
        parties = _parties(collateral_required_pct=50)
        opening = parties.refresh_facility()
        _first, _second, third = self._post_ladder(parties.facility_id, opening["version"])

        response = api_client.create_collateral_posting(
            parties.facility_id,
            factories.collateral_posting_payload(
                -7000000, third["version"], posting_note="release more than is there"
            ),
            credit_officer_headers(),
        )

        validate_error(response, "ERR_COLLATERAL_RELEASE_EXCEEDS_POSTED", 422)
        facility = _read_facility(parties.facility_id)
        assert facility["collateral_posted_cents"] == 6000000
        assert facility["collateral_posted_cents"] != 0
        assert facility["version"] == third["version"]
        assert_facility_ledger(facility, allocated_cents=0, utilisation_posture="OPEN")


class TestAmendmentConsentAndRechargePriceOnlyWhatActuallyChanged:
    """One favourable amendment carrying a restated no-op key, then one that cuts a right."""

    FAVOURABLE = {"amount_cents": 12000000, "tolerance_pct": 0}

    def test_a_key_restated_at_its_current_value_neither_binds_consent_nor_widens_the_recharge(
        self, clock
    ):
        """`tolerance_pct` restated at 0 is discarded, so only the 2,000,000 delta is priced.

        PRD 3.5: "Before the set is judged, every key whose new value equals the credit's
        current value is discarded as a no-op; if the surviving set is empty, or if any key
        names a field outside the amendable set, the draft is refused with
        `ERR_EMPTY_CHANGE_SET` (422)."

        PRD 3.5: "When it is positive, `amendment_fee_cents` is 7,500 cents plus
        `exposure_delta_cents` multiplied by a recharge rate in basis points, multiplied by
        the remaining quarter count, divided by 10,000 and rounded half up."

        Design: Corner/calculations/amendment_consent_requirement_propagates_to_a_fixed_point
        """
        parties = _parties()
        ctx = issued_credit(parties)

        drafted = draft_amendment(ctx, dict(self.FAVOURABLE))
        issued = issue_amendment(drafted["id"])

        assert drafted["requires_beneficiary_consent"] is False
        assert drafted["seq"] == 1
        assert_fields_equal(
            issued,
            status="ACCEPTED",
            exposure_delta_cents=2000000,
            amendment_fee_cents=11500,
            window_end_effective="2026-08-10",
        )
        assert issued["amendment_fee_cents"] != 31500

    def test_the_recharge_rate_is_local_and_the_credit_keeps_its_issuance_commission(
        self, clock
    ):
        """The credit re-derives its exposure, keeps `total_charge_cents`, and re-cuts one row.

        PRD 3.5: "That recharge rate is a purely local value used to price this one fee; it
        is never written back to the credit's `commission_bps_applied`, which keeps the tier
        chosen at issuance for the life of the credit."

        PRD 3.5: "Hop two re-cuts the allocation rather than editing it in place. The
        credit's existing `OPEN` FacilityAllocation row flips to `RELEASED`, with
        `released_cents` set to that row's own `allocated_cents` plus its `charge_cents` and
        `released_at` set to the clock instant, and exactly one new row is opened whose
        `allocated_cents` is the credit's new `committed_allocation_cents` and whose
        `charge_cents` is the released row's `charge_cents` plus the amendment's
        `amendment_fee_cents`."

        Design: Corner/calculations/amendment_consent_requirement_propagates_to_a_fixed_point
        """
        parties = _parties()
        ctx = issued_credit(parties)

        issue_amendment(draft_amendment(ctx, dict(self.FAVOURABLE))["id"])

        credit = ctx.refresh()
        assert_fields_equal(
            credit,
            amount_cents=12000000,
            committed_allocation_cents=12000000,
            commission_bps_applied=10,
            total_charge_cents=25000,
            chargeable_utilisation_cents=12025000,
            amendment_seq=1,
            status="ISSUED",
        )
        rows = list_credit_allocation_rows(ctx.credit_id)
        assert len(rows) == 2
        released = [row for row in rows if row["status"] == "RELEASED"]
        opened = [row for row in rows if row["status"] == "OPEN"]
        assert len(released) == 1
        assert len(opened) == 1
        assert released[0]["released_cents"] == 10025000
        assert_fields_equal(
            opened[0],
            allocated_cents=12000000,
            charge_cents=36500,
            basis="AMENDED_INCREASE",
        )
        assert_facility_ledger(
            parties.refresh_facility(),
            allocated_cents=12036500,
            available_cents=37963500,
            utilisation_posture="OPEN",
        )

    def test_cutting_the_presentation_period_holds_the_change_for_consent_at_a_flat_fee(
        self, clock
    ):
        """A shorter presentation period reduces a right, so nothing is applied and the fee is flat.

        PRD 3.5: "When `requires_beneficiary_consent` is true, the amendment traverses
        `DRAFT → ISSUED → PENDING_CONSENT`, `window_end_effective` stays at
        `consent_deadline_date`, the credit moves `ISSUED → AMENDMENT_PENDING`, and the
        `change_set` is **not** applied."

        PRD 3.5: "When `exposure_delta_cents` is zero or negative, `amendment_fee_cents` is
        the flat 7,500 cents."

        Design: Corner/calculations/amendment_consent_requirement_propagates_to_a_fixed_point
        """
        parties = _parties()
        ctx = issued_credit(parties)
        issue_amendment(draft_amendment(ctx, dict(self.FAVOURABLE))["id"])
        set_clock("2026-08-13T09:00:00Z")

        drafted = draft_amendment(ctx, {"presentation_period_days": 15})
        issued = issue_amendment(drafted["id"])

        assert drafted["requires_beneficiary_consent"] is True
        assert drafted["seq"] == 2
        assert_fields_equal(
            issued,
            status="PENDING_CONSENT",
            exposure_delta_cents=0,
            amendment_fee_cents=7500,
            consent_deadline_date="2026-08-23",
            window_end_effective="2026-08-23",
        )
        assert_fields_equal(
            ctx.refresh(),
            status="AMENDMENT_PENDING",
            presentation_period_days=21,
            amendment_seq=1,
        )
