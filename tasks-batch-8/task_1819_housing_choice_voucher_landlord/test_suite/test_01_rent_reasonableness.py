"""Rent reasonableness and payment-standard windowing tests (PRD §3.2)."""
import pytest

from test_helpers import (
    validate_success,
    create_landlord, create_property, create_unit, create_voucher_family,
    create_payment_standard, create_rent_comparable,
    setup_priced_unit, create_draft_contract,
    make_landlord_headers,
)


class TestStandardVsComparableCap:
    """The two rent-reasonableness variants on identical requested rent."""

    def test_no_comparables_cap_is_payment_standard(self, api):
        """PRD §3.2: "If no comparables survive that filter, the approved rent is
        the lesser of the landlord's requested `contract_rent_cents` and the
        applicable payment standard's `amount_cents`."

        Design: Difficulty/dual_variant_calc/rent_reasonableness_standard_vs_comparable_cap
        """
        landlord, prop, unit, family = setup_priced_unit(
            zip_code="90001", bedroom_count=2, standard_cents=180_000,
            family_income_cents=2_400_000, family_code="F1",
        )
        contract = create_draft_contract(
            unit, family, landlord,
            contract_rent_cents=200_000, lease_start_date="2026-09-01",
        )
        resp = api.submit_contract(contract["id"], make_landlord_headers(landlord["id"]))
        data = validate_success(resp)
        assert data["approved_rent_cents"] == 180_000, (
            f"With zero comparables the cap is the payment standard alone: "
            f"expected 180000, got {data['approved_rent_cents']}"
        )

    def test_one_recent_comparable_cap_is_median_times_ratio(self, api):
        """PRD §3.2: "If at least one comparable survives, the median of their
        `rent_cents` values is computed — for an even number of comparables this
        is the average of the two middle values, rounded half-up to whole cents —
        and the cap becomes the lesser of the payment standard's `amount_cents`
        and the median multiplied by 1.10 (rounded half-up to cents)."

        Design: Difficulty/dual_variant_calc/rent_reasonableness_standard_vs_comparable_cap
        """
        landlord, prop, unit, family = setup_priced_unit(
            zip_code="90001", bedroom_count=2, standard_cents=180_000,
            family_income_cents=2_400_000, family_code="F1",
        )
        create_rent_comparable(
            zip_code="90001", bedroom_count=2, rent_cents=150_000,
            survey_date="2026-06-01",
        )
        contract = create_draft_contract(
            unit, family, landlord,
            contract_rent_cents=200_000, lease_start_date="2026-09-01",
        )
        resp = api.submit_contract(contract["id"], make_landlord_headers(landlord["id"]))
        data = validate_success(resp)
        # cap = min(180000, round_half_up(150000 * 1.10)) = 165000
        assert data["approved_rent_cents"] == 165_000, (
            f"With one comparable at 150000 the cap is min(180000, 165000): "
            f"expected 165000, got {data['approved_rent_cents']}"
        )

    def test_variants_diverge_on_identical_requested_rent(self, api):
        """PRD §3.2: "If no comparables survive that filter, the approved rent is
        the lesser of the landlord's requested `contract_rent_cents` and the
        applicable payment standard's `amount_cents`."
        PRD §3.3: "withdrawing the contract moves `PENDING_INSPECTION` back to
        `DRAFT`, closes the scheduled `INITIAL` inspection by moving it from
        `SCHEDULED` to `CLOSED`, resets `approved_rent_cents`,
        `hap_portion_cents`, and `tenant_portion_cents` all to 0, and bumps the
        contract's `version`."

        Design: Difficulty/dual_variant_calc/rent_reasonableness_standard_vs_comparable_cap
        """
        landlord, prop, unit, family = setup_priced_unit(
            zip_code="90001", bedroom_count=2, standard_cents=180_000,
            family_income_cents=2_400_000, family_code="F1",
        )
        headers = make_landlord_headers(landlord["id"])
        contract = create_draft_contract(
            unit, family, landlord,
            contract_rent_cents=200_000, lease_start_date="2026-09-01",
        )
        # Variant 1: no comparables -> approved == payment standard 180000.
        first = validate_success(api.submit_contract(contract["id"], headers))
        assert first["approved_rent_cents"] == 180_000
        # Withdraw resets portions to 0 and returns the contract to DRAFT.
        withdrawn = validate_success(api.withdraw_contract(contract["id"], headers))
        assert withdrawn["status"] == "DRAFT"
        # Add one recent comparable, then resubmit the same requested rent.
        create_rent_comparable(
            zip_code="90001", bedroom_count=2, rent_cents=150_000,
            survey_date="2026-06-01",
        )
        second = validate_success(api.submit_contract(contract["id"], headers))
        assert second["approved_rent_cents"] == 165_000
        assert first["approved_rent_cents"] != second["approved_rent_cents"], (
            "The two variants must diverge on identical contract_rent_cents"
        )


class TestComparableRecencyFilter:
    def test_stale_comparable_older_than_twelve_months_excluded(self, api):
        """PRD §3.2: "The procedure first gathers the comparables: every
        `RentComparable` row whose `zip_code` equals the property's `zip_code`,
        whose `bedroom_count` equals the unit's `bedroom_count`, and whose
        `survey_date` falls within the twelve months preceding the current
        logical date, with the twelve-month boundary inclusive."

        Design: Corner/calculations/rent_reasonableness_comparable_recency_filter
        """
        landlord, prop, unit, family = setup_priced_unit(
            zip_code="90303", bedroom_count=1, standard_cents=150_000,
            family_income_cents=2_400_000, family_code="CF6",
        )
        # Clock default is 2026-08-01 (PRD §2.7); 2025-01-01 is >12 months prior.
        create_rent_comparable(
            zip_code="90303", bedroom_count=1, rent_cents=100_000,
            survey_date="2025-01-01",
        )
        contract = create_draft_contract(
            unit, family, landlord,
            contract_rent_cents=200_000, lease_start_date="2026-08-01",
        )
        resp = api.submit_contract(contract["id"], make_landlord_headers(landlord["id"]))
        data = validate_success(resp)
        assert data["approved_rent_cents"] == 150_000, (
            f"Stale comparable must be excluded; cap stays the payment standard: "
            f"expected 150000, got {data['approved_rent_cents']}"
        )


class TestPaymentStandardWindowLatestWins:
    def test_latest_effective_from_governs_overlapping_windows(self, api):
        """PRD §3.2: "When more than one row matches a given ZIP, bedroom count,
        and target date, the row with the latest `effective_from` wins; a
        remaining tie is broken by `created_at` ascending."

        Design: Difficulty/resource_temporal_overlap/payment_standard_effective_window_latest_wins
        """
        landlord = create_landlord(legal_name="L 15", tax_id="T15")
        create_payment_standard(
            zip_code="90016", bedroom_count=1, amount_cents=150_000,
            effective_from="2026-01-01",
        )
        create_payment_standard(
            zip_code="90016", bedroom_count=1, amount_cents=170_000,
            effective_from="2026-06-01",
        )
        prop = create_property(landlord["id"], address="15 O St", zip_code="90016")
        unit = create_unit(prop["id"], unit_label="UF", bedroom_count=1)
        family = create_voucher_family(
            family_code="FF", voucher_bedroom_size=1, annual_income_cents=2_400_000,
        )
        contract = create_draft_contract(
            unit, family, landlord,
            contract_rent_cents=200_000, lease_start_date="2026-08-01",
        )
        resp = api.submit_contract(contract["id"], make_landlord_headers(landlord["id"]))
        data = validate_success(resp)
        assert data["approved_rent_cents"] == 170_000, (
            f"The 2026-06-01 row (170000) shadows the 2026-01-01 row (150000): "
            f"expected 170000, got {data['approved_rent_cents']}"
        )

    def test_earlier_window_row_governs_date_before_later_row(self, api):
        """PRD §3.2: "The applicable payment standard for this calculation is the
        row whose `zip_code` and `bedroom_count` match the unit and whose
        effective window contains the contract's `lease_start_date`."
        PRD §3.2: "When more than one row matches a given ZIP, bedroom count,
        and target date, the row with the latest `effective_from` wins; a
        remaining tie is broken by `created_at` ascending."

        Design: Difficulty/resource_temporal_overlap/payment_standard_effective_window_latest_wins
        """
        landlord = create_landlord(legal_name="L 15b", tax_id="T15b")
        create_payment_standard(
            zip_code="90016", bedroom_count=1, amount_cents=150_000,
            effective_from="2026-01-01",
        )
        create_payment_standard(
            zip_code="90016", bedroom_count=1, amount_cents=170_000,
            effective_from="2026-06-01",
        )
        prop = create_property(landlord["id"], address="15 O St", zip_code="90016")
        unit = create_unit(prop["id"], unit_label="UF2", bedroom_count=1)
        family = create_voucher_family(
            family_code="FF2", voucher_bedroom_size=1, annual_income_cents=2_400_000,
        )
        # Lease start 2026-03-01 falls in the first row's window only... but the
        # second row's window starts 2026-06-01, so the 150000 row governs.
        # Advance the clock so lease_start (2026-03-01) is not in the past check
        # for submission — submission has no such check; only inspection
        # scheduling checks the clock. Use a lease start matched by row 1 only.
        contract = create_draft_contract(
            unit, family, landlord,
            contract_rent_cents=200_000, lease_start_date="2026-03-01",
        )
        resp = api.submit_contract(contract["id"], make_landlord_headers(landlord["id"]))
        data = validate_success(resp)
        assert data["approved_rent_cents"] == 150_000, (
            f"Lease start 2026-03-01 is outside the 2026-06-01 row's window: "
            f"expected 150000, got {data['approved_rent_cents']}"
        )
