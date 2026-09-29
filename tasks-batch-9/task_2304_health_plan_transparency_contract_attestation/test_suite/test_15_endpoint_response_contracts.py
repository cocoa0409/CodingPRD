"""What each endpoint hands back, and what it refuses to touch on the way.

Three of these endpoints are unusual in the service: the compliance run and the
penalty projection answer with summary objects of their own rather than with the
plan year, and the clock capability decides what every other endpoint will stamp.
The remaining two pin the ledger's chronological ordering and the two independent
foreign keys a vendor data package is built from.
"""

from __future__ import annotations

from test_helpers import (
    COMPLIANCE_OFFICER_HEADERS,
    EXTERNAL_AUDITOR_HEADERS,
    PLATFORM_OPERATOR_HEADERS,
    SPONSOR_ADMIN_HEADERS,
    ApiClient,
    ApiErrorId,
    DEFICIENCY_GAG_CLAUSE,
    ENTRY_ABATEMENT,
    ENTRY_ACCRUAL,
    NON_EXISTENT_UUID,
    PACKAGE_EXPECTED,
    POSTURE_COMPLIANT,
    POSTURE_FROZEN,
    SECTION_D6_RX_TOTALS,
    VENDOR_TYPE_PBM,
    assert_instant_equals,
    factories as f,
    fixtures as fx,
    validate_error,
    validate_paginated,
    validate_success,
)

RUN_CLOCK = "2027-03-15T10:30:00Z"
ONSET_CLOCK = "2027-07-10T09:00:00Z"
PROJECTION_CLOCK = "2027-07-20T09:00:00Z"
STAMPING_CLOCK = "2027-09-09T08:07:06Z"
FIRST_ESCALATION_CLOCK = "2027-05-01T09:00:00Z"
SECOND_ESCALATION_CLOCK = "2027-05-10T09:00:00Z"
REVERSAL_CLOCK = "2027-05-15T09:00:00Z"
PACKAGE_CLOCK = "2027-08-01T09:00:00Z"

PLAN_YEAR_ONLY_FIELDS = ("lifecycle_status", "sponsor_name")


class TestRunAndProjectionSummaries:
    """Two endpoints that answer with their own object instead of a resource."""

    def test_a_clean_compliance_run_answers_with_counters_not_the_plan_year(
        self, api: ApiClient
    ) -> None:
        """Nothing to sweep still produces a run record and a stamped plan year.

        PRD 3.9: "The run's response is not the plan year but a summary object: a
        `run_id` identifying the run, `cycles_missed_count` and
        `amendments_lapsed_count` reporting what the two sweeps touched,
        `accruals_posted_count` reporting how many ledger entries the run
        appended, `posture_before` and `posture_after` naming the posture on
        either side of the recomputation, and the resulting `deficiency_points`
        and `penalty_exposure_cents`."

        PRD 3.9: "The run also stamps `last_compliance_run_at` with the logical
        clock."

        Design: Corner/endpoints/compliance_run_returns_a_run_summary_object
        """
        fx.set_clock(api, RUN_CLOCK)
        setup = fx.activated_plan_year(api, covered_lives=6000)
        plan_year_id = setup["plan_year"]["id"]

        summary = validate_success(
            api.run_compliance(plan_year_id, COMPLIANCE_OFFICER_HEADERS)
        )
        assert isinstance(summary["run_id"], str)
        assert summary["run_id"]
        assert summary["cycles_missed_count"] == 0
        assert summary["amendments_lapsed_count"] == 0
        assert summary["accruals_posted_count"] == 0
        assert summary["posture_before"] == POSTURE_COMPLIANT
        assert summary["posture_after"] == POSTURE_COMPLIANT
        assert summary["deficiency_points"] == 0
        assert summary["penalty_exposure_cents"] == 0
        for plan_year_field in PLAN_YEAR_ONLY_FIELDS:
            assert plan_year_field not in summary

        plan_year = fx.read_plan_year(api, plan_year_id)
        assert_instant_equals(plan_year["last_compliance_run_at"], RUN_CLOCK)
        assert plan_year["deficiency_points"] == 0

        entries = fx.list_ledger_entries(api, plan_year_id)
        assert entries == []

    def test_reading_the_projection_twice_moves_neither_ledger_nor_version(
        self, api: ApiClient
    ) -> None:
        """Eleven days of projected exposure against one day on the ledger.

        PRD 3.9: "For a plan year with 6,000 covered lives — multiplier 2.0 — an
        `end_date` of 2027-12-31, and a single gag-clause deficiency whose onset
        is 2027-07-10, a projection as of 2027-07-20 reports
        `accrued_to_date_cents` of 330,000, being 15,000 cents times 11 days
        times 2.0, and `statutory_maximum_cents` of 5,250,000, being 15,000 cents
        times 175 days times 2.0."

        PRD 3.9: "The projection deliberately disagrees with
        `penalty_exposure_cents`, and that disagreement is the feature: a
        deficiency open for eleven days projects eleven days of exposure while
        the ledger still holds only the single one-day accrual posted when it
        opened."

        Design: Corner/endpoints/penalty_projection_is_read_only
        """
        fx.set_clock(api, ONSET_CLOCK)
        setup = fx.activated_plan_year(api, covered_lives=6000)
        plan_year_id = setup["plan_year"]["id"]
        fx.gag_non_compliant_contract(
            api, setup["tpa_contract"]["id"], prohibited_clause_count=2
        )

        fx.set_clock(api, PROJECTION_CLOCK)
        version_before = fx.current_plan_year_version(api, plan_year_id)

        first = validate_success(
            api.get_penalty_projection(plan_year_id, EXTERNAL_AUDITOR_HEADERS)
        )
        second = validate_success(
            api.get_penalty_projection(plan_year_id, EXTERNAL_AUDITOR_HEADERS)
        )
        assert first == second
        assert first["accrued_to_date_cents"] == 330_000
        assert first["statutory_maximum_cents"] == 5_250_000
        assert first["open_deficiency_count"] == 1
        assert first["size_multiplier"] == 2.0

        after = fx.read_plan_year(api, plan_year_id)
        assert after["version"] == version_before
        assert after["penalty_exposure_cents"] == 30_000

        rows, meta = validate_paginated(
            api.list_ledger_entries(
                EXTERNAL_AUDITOR_HEADERS, params={"plan_year_id": plan_year_id}
            )
        )
        assert meta["total_count"] == 1
        assert rows[0]["days_open"] == 1
        assert rows[0]["signed_amount_cents"] == 30_000


class TestLogicalClockStamping:
    """Whatever the operator sets is what the next write records."""

    def test_a_row_created_after_a_clock_move_carries_that_exact_instant(
        self, api: ApiClient
    ) -> None:
        """And reading it back returns the stored value rather than a fresh one.

        PRD 2.4: "Every resource also carries a `created_at` timestamp, an ISO
        8601 UTC instant with exactly three fractional digits, read from the
        logical clock at the moment of creation."

        PRD 2.5: "A single server-side logical clock supplies every timestamp
        written to a resource, every day count, every month boundary and every
        deadline comparison."

        Design: Corner/endpoints/clock_set_endpoint_stamps_subsequent_writes
        """
        held = validate_success(
            api.set_clock(f.clock_payload(STAMPING_CLOCK), PLATFORM_OPERATOR_HEADERS)
        )
        assert_instant_equals(held["current_utc"], STAMPING_CLOCK)

        created = validate_success(
            api.create_plan_year(
                f.plan_year_payload(covered_lives=6000), SPONSOR_ADMIN_HEADERS
            ),
            expected_status=201,
        )
        assert_instant_equals(created["created_at"], STAMPING_CLOCK)
        assert_instant_equals(created["updated_at"], STAMPING_CLOCK)
        assert created["version"] == 1

        stored = fx.read_plan_year(api, created["id"])
        assert_instant_equals(stored["created_at"], STAMPING_CLOCK)
        assert_instant_equals(stored["updated_at"], STAMPING_CLOCK)
        assert stored["version"] == 1


class TestLedgerListingOrder:
    """Posting order, not amount order and not identifier order."""

    def test_the_newest_row_comes_last_even_though_its_amount_is_smallest(
        self, api: ApiClient
    ) -> None:
        """Two accruals nine days apart, then a reversal five days later still.

        PRD 2.3: "Results are ordered by `created_at` ascending — oldest row
        first — on every list endpoint, including the penalty ledger, whose
        chronological ordering is load-bearing rather than cosmetic."

        PRD 2.4: "Identifiers are bare UUIDs with no type prefix and no embedded
        semantics; in particular a penalty ledger entry's `id` must never decide
        a business outcome, because ledger ordering is by `created_at` alone."

        Design: Corner/endpoints/ledger_list_is_ordered_created_at_ascending
        """
        fx.set_clock(api, FIRST_ESCALATION_CLOCK)
        setup = fx.activated_plan_year(api, covered_lives=6000)
        plan_year_id = setup["plan_year"]["id"]
        pbm = fx.add_contract_for_vendor_type(
            api, plan_year_id, VENDOR_TYPE_PBM, annual_fee_cents=12_000_000
        )
        fx.gag_non_compliant_contract(
            api, setup["tpa_contract"]["id"], prohibited_clause_count=2
        )
        first_accrual = fx.list_ledger_entries(api, plan_year_id)[0]

        fx.set_clock(api, SECOND_ESCALATION_CLOCK)
        fx.gag_non_compliant_contract(
            api, pbm["contract"]["id"], prohibited_clause_count=3
        )

        fx.set_clock(api, REVERSAL_CLOCK)
        validate_success(
            api.reverse_ledger_entry(
                first_accrual["id"],
                f.reverse_entry_payload(reason="TPA accrual posted in error."),
                EXTERNAL_AUDITOR_HEADERS,
            ),
        )

        rows, meta = validate_paginated(
            api.list_ledger_entries(
                EXTERNAL_AUDITOR_HEADERS, params={"plan_year_id": plan_year_id}
            )
        )
        assert meta["total_count"] == 3
        assert meta["has_more"] is False
        assert_instant_equals(rows[0]["created_at"], FIRST_ESCALATION_CLOCK)
        assert_instant_equals(rows[1]["created_at"], SECOND_ESCALATION_CLOCK)
        assert_instant_equals(rows[2]["created_at"], REVERSAL_CLOCK)

        assert rows[0]["id"] == first_accrual["id"]
        assert rows[0]["entry_type"] == ENTRY_ACCRUAL
        assert rows[1]["entry_type"] == ENTRY_ACCRUAL
        assert rows[1]["signed_amount_cents"] == 30_000
        assert rows[2]["entry_type"] == ENTRY_ABATEMENT
        assert rows[2]["signed_amount_cents"] == -30_000
        assert rows[2]["reverses_entry_id"] == first_accrual["id"]
        assert [row["deficiency_type"] for row in rows] == [DEFICIENCY_GAG_CLAUSE] * 3

        plan_year = fx.read_plan_year(api, plan_year_id)
        assert plan_year["penalty_exposure_cents"] == 30_000
        assert plan_year["deficiency_points"] == 12
        assert plan_year["compliance_posture"] == POSTURE_FROZEN


class TestPackageForeignKeys:
    """A package is meaningless unless both of its parents resolve."""

    def test_each_parent_is_checked_on_its_own_before_the_row_exists(
        self, api: ApiClient
    ) -> None:
        """An unknown filing and an unknown vendor fail differently, then both hold.

        PRD 2.9: "Every foreign key supplied in a request body or as a list
        filter — `plan_year_id`, `vendor_id`, `contract_id`, `rx_submission_id`,
        `reverses_entry_id`, `remediation_plan_id` — resolves to an existing row,
        on every create endpoint and every list endpoint that filters on a
        foreign key."

        PRD 3.6: "A registered package sits in `EXPECTED` with `record_count`,
        `plan_paid_cents`, `member_paid_cents`, `rebate_cents`,
        `rejection_reason` and `validated_at` all null and `delivery_round` at
        0."

        Design: Corner/endpoints/vendor_data_package_links_submission_and_vendor
        """
        fx.set_clock(api, PACKAGE_CLOCK)
        setup = fx.activated_plan_year(api, covered_lives=6000)
        plan_year_id = setup["plan_year"]["id"]
        pbm_vendor = fx.create_pbm_vendor(api)
        submission = fx.open_rx_submission(api, plan_year_id, reference_year=2026)

        validate_error(
            api.create_vendor_data_package(
                f.vendor_data_package_payload(
                    NON_EXISTENT_UUID,
                    pbm_vendor["id"],
                    data_section=SECTION_D6_RX_TOTALS,
                ),
                COMPLIANCE_OFFICER_HEADERS,
            ),
            ApiErrorId.RX_SUBMISSION_NOT_FOUND,
            expected_status=404,
        )
        validate_error(
            api.create_vendor_data_package(
                f.vendor_data_package_payload(
                    submission["id"],
                    NON_EXISTENT_UUID,
                    data_section=SECTION_D6_RX_TOTALS,
                ),
                COMPLIANCE_OFFICER_HEADERS,
            ),
            ApiErrorId.VENDOR_NOT_FOUND,
            expected_status=404,
        )

        created = validate_success(
            api.create_vendor_data_package(
                f.vendor_data_package_payload(
                    submission["id"],
                    pbm_vendor["id"],
                    data_section=SECTION_D6_RX_TOTALS,
                    expected_record_count=1200,
                ),
                COMPLIANCE_OFFICER_HEADERS,
            ),
            expected_status=201,
        )
        assert created["rx_submission_id"] == submission["id"]
        assert created["vendor_id"] == pbm_vendor["id"]
        assert created["status"] == PACKAGE_EXPECTED
        assert created["delivery_round"] == 0
        assert created["record_count"] is None
        assert created["plan_paid_cents"] is None
        assert created["member_paid_cents"] is None
        assert created["rebate_cents"] is None
        assert created["rejection_reason"] is None
        assert created["validated_at"] is None

        by_submission, submission_meta = validate_paginated(
            api.list_vendor_data_packages(
                COMPLIANCE_OFFICER_HEADERS,
                params={"rx_submission_id": submission["id"]},
            )
        )
        assert submission_meta["total_count"] == 1
        assert by_submission[0]["id"] == created["id"]

        by_vendor, vendor_meta = validate_paginated(
            api.list_vendor_data_packages(
                COMPLIANCE_OFFICER_HEADERS, params={"vendor_id": pbm_vendor["id"]}
            )
        )
        assert vendor_meta["total_count"] == 1
        assert by_vendor[0]["id"] == created["id"]
