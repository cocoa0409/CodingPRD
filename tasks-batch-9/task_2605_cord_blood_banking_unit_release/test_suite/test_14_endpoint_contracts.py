"""Read surfaces, degenerate sweeps, derived projections and one-cent action boundaries."""

import pytest

from test_helpers import (
    NIGHTLY_COUNTERS,
    ApiErrorId,
    api_client,
    assert_registry_code_sequence,
    build_listed_public_scenario,
    expected_pre_cryo_dose,
    issue_invoice,
    make_billing_admin_headers,
    make_facilities_engineer_headers,
    make_platform_admin_headers,
    make_technologist_headers,
    make_transplant_center_headers,
    open_storage_account,
    read_account,
    read_invoice,
    register_enrollment,
    set_clock,
    sign_consent,
    validate_error,
    validate_paginated,
    validate_success,
)

PREMIUM_TANK_REQUEST = {
    "tank_code": "TANK-P",
    "tank_class": "PREMIUM",
    "capacity_slots": 6,
    "maintenance_window_start": "2026-09-01T00:00:00Z",
    "maintenance_window_end": "2026-09-02T00:00:00Z",
}


def _commissioned_premium_tank():
    set_clock("2026-08-01T00:00:00Z")
    return validate_success(
        api_client.create_storage_tank(
            PREMIUM_TANK_REQUEST, make_facilities_engineer_headers("fe-001")
        ),
        201,
    )


class TestStorageTankSurface:
    def test_a_new_tank_carries_its_declared_fields_and_the_system_defaults(self):
        """Occupancy and the rolling excursion budget both open at zero.

        "A new tank begins in `status` of `ONLINE`, with `occupied_slots` at 0 and
        `cumulative_excursion_minutes_30d` at 0; `last_temperature_c` and `last_reading_at` are
        null until the first reading arrives."

        Design: Corner/endpoints/corner_storage_tank_create_read_and_list_round_trip
        """
        tank = _commissioned_premium_tank()

        assert tank["tank_code"] == "TANK-P"
        assert tank["tank_class"] == "PREMIUM"
        assert tank["capacity_slots"] == 6
        assert tank["maintenance_window_start"].startswith("2026-09-01T00:00:00")
        assert tank["maintenance_window_end"].startswith("2026-09-02T00:00:00")
        assert tank["status"] == "ONLINE"
        assert tank["occupied_slots"] == 0
        assert tank["cumulative_excursion_minutes_30d"] == 0
        assert tank["last_temperature_c"] is None
        assert tank["last_reading_at"] is None
        assert tank["version"] == 1

    def test_the_tank_reads_back_exactly_as_it_was_commissioned(self):
        """Nothing between creation and the read is capable of altering the row.

        "`version` (integer) — a counter that starts at 1 on creation and increments by exactly 1
        on every mutation of the row. Recomputing a derived value such as `balance_cents`,
        `occupied_slots` or `quality_acceptance_score` is a mutation for this purpose."

        Design: Corner/endpoints/corner_storage_tank_create_read_and_list_round_trip
        """
        tank = _commissioned_premium_tank()

        fetched = validate_success(
            api_client.get_storage_tank(tank["id"], make_facilities_engineer_headers("fe-001"))
        )

        assert fetched == tank

    def test_the_status_and_class_filters_both_select_and_exclude(self):
        """A filter that were ignored would return the premium tank in the standard window.

        "Tanks may also be browsed by `status` or `tank_class`."

        Design: Corner/endpoints/corner_storage_tank_create_read_and_list_round_trip
        """
        tank = _commissioned_premium_tank()

        matching, meta = validate_paginated(
            api_client.list_storage_tanks(
                make_technologist_headers("tech-001"),
                {"status": "ONLINE", "tank_class": "PREMIUM", "limit": 10, "offset": 0},
            )
        )
        assert meta["total_count"] == 1
        assert meta["has_more"] is False
        assert len(matching) == 1
        assert matching[0]["id"] == tank["id"]

        excluded, excluded_meta = validate_paginated(
            api_client.list_storage_tanks(
                make_technologist_headers("tech-001"), {"tank_class": "STANDARD"}
            )
        )
        assert excluded_meta["total_count"] == 0
        assert excluded == []


class TestTheNightlySweepOnAnEmptyBank:
    def test_an_empty_bank_reports_all_ten_counters_at_zero(self):
        """Nothing is due because nothing exists, and that is a success, not an error.

        "The run reports what it did as ten integer counters: `kits_expired`,
        `screenings_expired`, `reservations_expired`, `excursions_escalated`,
        `tanks_entered_maintenance`, `tanks_exited_maintenance`, `invoices_advanced_past_due`,
        `invoices_advanced_delinquent`, `accounts_advanced` and
        `units_flagged_pending_abandonment`."

        Design: Corner/endpoints/corner_nightly_run_on_an_empty_database_reports_all_zero_counters
        """
        set_clock("2027-01-01T00:00:00Z")

        counters = validate_success(
            api_client.run_nightly_batch({}, make_platform_admin_headers())
        )

        assert counters["kits_expired"] == 0
        assert counters["screenings_expired"] == 0
        assert counters["reservations_expired"] == 0
        assert counters["excursions_escalated"] == 0
        assert counters["tanks_entered_maintenance"] == 0
        assert counters["tanks_exited_maintenance"] == 0
        assert counters["invoices_advanced_past_due"] == 0
        assert counters["invoices_advanced_delinquent"] == 0
        assert counters["accounts_advanced"] == 0
        assert counters["units_flagged_pending_abandonment"] == 0

    def test_a_second_sweep_without_clock_movement_changes_nothing(self):
        """Re-running the batch is a no-op rather than a second pass.

        "A run over a system with nothing due returns all ten counters at 0, and running the
        batch twice with no clock movement in between leaves the second run's counters at 0 as
        well."

        Design: Corner/endpoints/corner_nightly_run_on_an_empty_database_reports_all_zero_counters
        """
        set_clock("2027-01-01T00:00:00Z")
        first = validate_success(api_client.run_nightly_batch({}, make_platform_admin_headers()))

        second = validate_success(api_client.run_nightly_batch({}, make_platform_admin_headers()))

        assert second == first
        for name in NIGHTLY_COUNTERS:
            assert second[name] == 0, name


def _listed_public_unit_of_fifteen_hundred_millions():
    """The canonical public unit: 1500 million cells, grade A, frozen in an online tank."""
    return build_listed_public_scenario(
        tank_code="TANK-A",
        capacity_slots=4,
        primary_parent_name="Dana Ruiz",
        collection_site_code="SITE-02",
        research_use_authorized=True,
        consent_document_hash="hash-search-v1",
        kit_lot_code="LOT-2026-S9",
        courier_tracking_code="TRK-0900",
        post_tnc_millions=1500,
        quality_tnc_millions=1500,
        quality_cd34_thousands=3000,
        quality_viability_pct=92.0,
        slot_code="A-01",
        registry_code="NMDP",
        hla_a="A*01:01",
        hla_b="B*07:02",
        hla_drb1="DRB1*15:01",
    )


class TestRankedUnitSearch:
    def test_the_search_row_projects_the_dose_it_computes_for_the_patient(self):
        """Every projected field is recomputed for the supplied patient weight.

        "Each result row projects `unit_id`, `unit_registry_code`, `program_type`,
        `potency_grade`, `post_processing_tnc_millions`, `post_processing_cd34_thousands`,
        `post_processing_viability_pct`, `pre_cryo_dose_x1e7_per_kg` and the `tank_code` of the
        holding tank."

        Design: Corner/endpoints/corner_unit_search_projects_the_derived_dose_and_returns_empty_sets_cleanly
        """
        scenario = _listed_public_unit_of_fifteen_hundred_millions()

        rows, meta = validate_paginated(
            api_client.search_units(
                make_transplant_center_headers("tc-001"),
                {
                    "program_scope": "PUBLIC",
                    "patient_weight_kg": 35.0,
                    "required_hla_match_count": 6,
                    "limit": 10,
                    "offset": 0,
                },
            )
        )

        assert meta["total_count"] == 1
        assert meta["has_more"] is False
        assert len(rows) == 1

        row = rows[0]
        assert row["unit_id"] == scenario["unit"]["id"]
        assert_registry_code_sequence(row, 1)
        assert row["program_type"] == "PUBLIC_DONATION"
        assert row["potency_grade"] == "A"
        assert row["tank_code"] == "TANK-A"
        assert row["post_processing_tnc_millions"] == 1500
        assert row["post_processing_cd34_thousands"] == 3000
        assert row["post_processing_viability_pct"] == pytest.approx(92.0, abs=0.01)
        assert row["pre_cryo_dose_x1e7_per_kg"] == pytest.approx(4.29, abs=0.01)
        assert row["pre_cryo_dose_x1e7_per_kg"] == pytest.approx(
            expected_pre_cryo_dose(1500, 35.0), abs=0.01
        )

    def test_a_dose_floor_above_the_units_dose_yields_a_clean_empty_set(self):
        """A floor of 5.0 excludes a dose of 4.29 without raising anything.

        "When `min_dose_x1e7_per_kg` is supplied, a unit qualifies only when its pre-freeze dose
        for the supplied `patient_weight_kg` is at least that floor."

        Design: Corner/endpoints/corner_unit_search_projects_the_derived_dose_and_returns_empty_sets_cleanly
        """
        _listed_public_unit_of_fifteen_hundred_millions()

        rows, meta = validate_paginated(
            api_client.search_units(
                make_transplant_center_headers("tc-001"),
                {
                    "program_scope": "PUBLIC",
                    "patient_weight_kg": 35.0,
                    "min_dose_x1e7_per_kg": 5.0,
                },
            )
        )

        assert rows == []
        assert meta["total_count"] == 0
        assert meta["has_more"] is False

    def test_a_listed_public_unit_is_absent_from_the_private_directed_scope(self):
        """The two scopes demand different availability values and share no unit here.

        "A `program_scope` of `PUBLIC` additionally requires `availability_status` equal to
        `LISTED` and the existence of a registry listing in `ACTIVE`; a `program_scope` of
        `PRIVATE_DIRECTED` instead requires `availability_status` equal to `PRIVATE_STORED`."

        Design: Corner/endpoints/corner_unit_search_projects_the_derived_dose_and_returns_empty_sets_cleanly
        """
        _listed_public_unit_of_fifteen_hundred_millions()

        rows, meta = validate_paginated(
            api_client.search_units(
                make_transplant_center_headers("tc-001"),
                {"program_scope": "PRIVATE_DIRECTED", "patient_weight_kg": 35.0},
            )
        )

        assert rows == []
        assert meta["total_count"] == 0


def _account_carrying_one_issued_invoice():
    """A five-year account whose only invoice asks for 18225 cents."""
    set_clock("2026-08-01T00:00:00Z")
    enrollment = register_enrollment(
        program_type="PRIVATE_FAMILY",
        primary_parent_name="Avery Lin",
        collection_site_code="SITE-01",
    )
    sign_consent(enrollment["id"], consent_document_hash="hash-pay-v1")
    account = open_storage_account(
        enrollment["id"],
        billing_contact_email="avery@example.test",
        plan_term_years=5,
        prepaid_through_date="2027-08-01",
    )
    invoice = issue_invoice(
        account["id"],
        billing_period_start="2026-08-01",
        billing_period_end="2027-08-01",
        prorated_days=365,
    )
    return account, invoice


class TestPaymentResidualBoundary:
    def test_a_payment_one_cent_above_the_residual_is_refused(self):
        """The invoice can never be paid beyond its face value.

        "The amount must not exceed the invoice's residual — `amount_due_cents` minus
        `amount_paid_cents` — and an overpayment is refused with `ERR_PAYMENT_EXCEEDS_BALANCE`,
        which means partial payments are permitted but the invoice can never be paid beyond its
        face value."

        Design: Corner/endpoints/corner_payment_above_the_residual_is_refused_then_the_exact_residual_pays_the_invoice
        """
        _, invoice = _account_carrying_one_issued_invoice()
        assert invoice["status"] == "ISSUED"
        assert invoice["amount_due_cents"] == 18225
        assert invoice["amount_paid_cents"] == 0
        assert invoice["late_fee_line_cents"] == 0

        response = api_client.pay_storage_invoice(
            invoice["id"],
            {"amount_cents": 18226, "payment_reference": "PAY-OVER"},
            make_billing_admin_headers(),
        )

        validate_error(response, ApiErrorId.ERR_PAYMENT_EXCEEDS_BALANCE.value, 422)

        after = read_invoice(invoice["id"])
        assert after["status"] == "ISSUED"
        assert after["amount_paid_cents"] == 0

    def test_the_exact_residual_settles_the_invoice_and_the_account(self):
        """One cent lower than the refused amount closes the invoice outright.

        "When the payment brings `amount_paid_cents` exactly up to `amount_due_cents`, the
        invoice moves to the terminal `PAID` from whichever of `ISSUED`, `PAST_DUE` or
        `DELINQUENT` it was in, and the account's `paid_through_date` is advanced to the later of
        its current value and the invoice's `billing_period_end` — never backwards."

        Design: Corner/endpoints/corner_payment_above_the_residual_is_refused_then_the_exact_residual_pays_the_invoice
        """
        account, invoice = _account_carrying_one_issued_invoice()
        api_client.pay_storage_invoice(
            invoice["id"],
            {"amount_cents": 18226, "payment_reference": "PAY-OVER"},
            make_billing_admin_headers(),
        )

        paid = validate_success(
            api_client.pay_storage_invoice(
                invoice["id"],
                {"amount_cents": 18225, "payment_reference": "PAY-EXACT"},
                make_billing_admin_headers(),
            )
        )

        assert paid["status"] == "PAID"
        assert paid["amount_paid_cents"] == 18225
        assert read_account(account["id"])["paid_through_date"].startswith("2027-08-01")

    def test_the_refused_payment_never_entered_the_lifetime_total(self):
        """The monotonic total counts accepted payments only.

        "An accepted payment adds `amount_cents` to the invoice's `amount_paid_cents` and to the
        account's `lifetime_paid_cents`, then triggers reconciliation of `balance_cents`."

        Design: Corner/endpoints/corner_payment_above_the_residual_is_refused_then_the_exact_residual_pays_the_invoice
        """
        account, invoice = _account_carrying_one_issued_invoice()
        api_client.pay_storage_invoice(
            invoice["id"],
            {"amount_cents": 18226, "payment_reference": "PAY-OVER"},
            make_billing_admin_headers(),
        )
        validate_success(
            api_client.pay_storage_invoice(
                invoice["id"],
                {"amount_cents": 18225, "payment_reference": "PAY-EXACT"},
                make_billing_admin_headers(),
            )
        )

        settled = read_account(account["id"])
        assert settled["balance_cents"] == 0
        assert settled["lifetime_paid_cents"] == 18225
        assert settled["status"] == "ACTIVE"
