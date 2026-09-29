"""Persisted shapes: required inputs, declared defaults, computed fields and parent guards."""

from test_helpers import (
    AGREEMENT_DEFAULTS,
    ADMIN_HEADERS,
    AgreementStatus,
    ApiErrorId,
    ApprovalLevel,
    ASSET_HEADERS,
    BenchmarkSource,
    BenchmarkStatus,
    BudgetDecision,
    ClaimStatus,
    EmployerOfRecord,
    FinancialStatus,
    LedgerEntryType,
    LedgerSourceKind,
    MANAGER_ALT_HEADERS,
    MANAGER_ALT_USER_ID,
    MANAGER_HEADERS,
    NON_EXISTENT_UUID,
    OWNER_HEADERS,
    PackageStatus,
    PositionClass,
    ReviewDecision,
    ReviewDimension,
    VarianceCategory,
    VarianceStatus,
    agreement_payload,
    assert_append_only_row,
    assert_array_envelope,
    assert_common_fields,
    assert_error_envelope,
    assert_object_envelope,
    assert_page,
    assert_variance_pct,
    benchmark_payload,
    employment_claim_payload,
    package_payload,
)


# ---------------------------------------------------------------------------
# Registration: what is persisted, and what is defaulted
# ---------------------------------------------------------------------------


class TestAgreementCreation:
    def test_creation_persists_every_supplied_configuration_value(self, scenario):
        """PRD §3.1: "A `PlatformAdmin` registers one by supplying the hotel's trading name as
        `hotel_name`, the legal name of the owner entity as `owner_entity_name`, the base
        management fee rate as `base_fee_pct`, the tier-one incentive fee rate as
        `incentive_fee_pct`, and the annual owner priority return as `owner_priority_cents`."
        And: "A newly registered agreement is persisted with `status` `DRAFT` and with every
        computed aggregate at its opening value: `working_capital_balance_cents` at 0,
        `ffe_reserve_balance_cents` at 0, `manager_liability_accrued_cents` at 0,
        `performance_failure_streak` at 0, `distribution_hold` false, and
        `termination_effective_utc` null."

        Design: Corner/entities/agreement_creation_returns_persisted_configuration
        """
        response = scenario.api.create_agreement(
            agreement_payload(
                hotel_name="Corner Creation Hotel",
                owner_entity_name="Creation Owner LLC",
                base_fee_pct=0.0325,
                incentive_fee_pct=0.10,
                owner_priority_cents=12000000,
                ffe_reserve_pct=0.04,
                centralized_services_cap_pct=0.015,
            ),
            ADMIN_HEADERS,
        )

        agreement = assert_object_envelope(response, 201)
        assert_common_fields(agreement)
        assert agreement["version"] == 1
        assert agreement["hotel_name"] == "Corner Creation Hotel"
        assert agreement["owner_entity_name"] == "Creation Owner LLC"
        assert agreement["base_fee_pct"] == 0.0325
        assert agreement["incentive_fee_pct"] == 0.10
        assert agreement["owner_priority_cents"] == 12000000
        assert agreement["ffe_reserve_pct"] == 0.04
        assert agreement["centralized_services_cap_pct"] == 0.015
        assert agreement["status"] == AgreementStatus.DRAFT
        assert agreement["working_capital_balance_cents"] == 0
        assert agreement["ffe_reserve_balance_cents"] == 0
        assert agreement["manager_liability_accrued_cents"] == 0
        assert agreement["performance_failure_streak"] == 0
        assert agreement["distribution_hold"] is False
        assert agreement["termination_effective_utc"] is None

    def test_the_omitted_configuration_takes_the_contractual_defaults(self, scenario):
        """PRD §3.1: "The tier-two incentive rate `incentive_tier2_pct` defaults to 0.15 and may
        never be set below `incentive_fee_pct`; the annual excess-over-priority amount at which
        that second tier starts, `incentive_tier2_threshold_cents`, defaults to 5,000,000 cents"
        and "Governance timings default as follows: `owner_review_window_days` of 30,
        `max_revision_rounds` of 2, `cure_window_days` of 60 — two months for the manager to
        elect and pay a cure — `dispute_standstill_days` of 45, `max_dispute_rounds` of 2,
        `funding_due_days` of 15 and `termination_notice_days` of 90, a full quarter of notice."
        And: "Performance covenants default to a `gop_test_threshold_pct` of 0.85, an
        `rpi_test_threshold` of 90.0, a `min_benchmark_months` of 10, a `test_periods_expected`
        of 12 and a `consecutive_failure_limit` of 2."

        Design: Corner/entities/agreement_omitted_configuration_takes_declared_defaults
        """
        agreement = scenario.register(
            hotel_name="Defaults Only Hotel",
            owner_entity_name="Default Owner LP",
            base_fee_pct=0.03,
            incentive_fee_pct=0.10,
            owner_priority_cents=12000000,
        )

        for field, expected in AGREEMENT_DEFAULTS.items():
            assert agreement[field] == expected, field
        assert agreement["distribution_hold"] is False
        assert agreement["termination_effective_utc"] is None


# ---------------------------------------------------------------------------
# The reporting package: stored inputs, derived figures, and paging
# ---------------------------------------------------------------------------


def _retrieval_hotel(scenario):
    """One freshly opened (2026, 9) period on an active agreement."""
    agreement = scenario.register(
        hotel_name="Retrieval Hotel",
        owner_entity_name="Read Owner LLC",
        base_fee_pct=0.0325,
        incentive_fee_pct=0.10,
        owner_priority_cents=12000000,
    )
    scenario.activate(agreement["id"])
    package = scenario.expert_package(agreement["id"], fiscal_year=2026, period_month=9)
    return {"agreement_id": agreement["id"], "package_id": package["id"]}


class TestReportPackageRetrieval:
    def test_the_read_returns_the_stored_inputs_and_the_two_derived_figures(self, scenario):
        """PRD §3.4: "The `gross_revenue_cents` is the sum of the rooms, food-and-beverage and
        other revenue lines." And: "A freshly opened package sits at `financial_status`
        `PENDING`, `benchmark_status` `PENDING` and `package_status` `INCOMPLETE`, with
        `submitted_at` null, `submitted_late` false, `resubmission_count` at 0, `reported_rpi`
        null, and `allocated_centralized_cents`, `base_fee_cents`, `agop_cents` and
        `incentive_fee_provisional_cents` all at 0."

        Design: Corner/entities/report_package_retrieval_returns_stored_inputs
        """
        state = _retrieval_hotel(scenario)

        package = assert_object_envelope(
            scenario.api.get_report_package(state["package_id"], ASSET_HEADERS), 200
        )

        assert package["agreement_id"] == state["agreement_id"]
        assert package["rooms_revenue_cents"] == 40000015
        assert package["fnb_revenue_cents"] == 12000005
        assert package["other_revenue_cents"] == 3000005
        assert package["gross_revenue_cents"] == 55000025
        assert package["due_date_utc"].startswith("2026-10-25T00:00:00")
        assert package["financial_status"] == FinancialStatus.PENDING
        assert package["benchmark_status"] == BenchmarkStatus.PENDING
        assert package["package_status"] == PackageStatus.INCOMPLETE
        assert package["submitted_at"] is None
        assert package["submitted_late"] is False
        assert package["resubmission_count"] == 0
        assert package["reported_rpi"] is None
        assert package["allocated_centralized_cents"] == 0
        assert package["base_fee_cents"] == 0
        assert package["agop_cents"] == 0
        assert package["incentive_fee_provisional_cents"] == 0


def _pagination_hotel(scenario):
    """Three consecutive periods opened in month order."""
    agreement = scenario.register(
        hotel_name="Pagination Hotel",
        owner_entity_name="Page Owner LLC",
    )
    scenario.activate(agreement["id"])
    for month, rooms, opex in ((9, 20000000, 5000000), (10, 21000000, 6000000), (11, 22000000, 6000000)):
        scenario.api.create_report_package(
            agreement["id"],
            package_payload(
                fiscal_year=2026,
                period_month=month,
                rooms_revenue_cents=rooms,
                operating_expenses_cents=opex,
            ),
            MANAGER_HEADERS,
        )
    return {"agreement_id": agreement["id"]}


class TestReportPackageListing:
    def test_the_first_window_reports_the_pre_paging_total_and_more_to_come(self, scenario):
        """PRD §2.3: "List responses populate `limit`, `offset`, `total_count` and `has_more` in
        the `meta` object of the envelope, where `total_count` counts every row matching the
        filters before paging is applied and `has_more` is true whenever rows remain beyond the
        current window."

        Design: Corner/entities/report_package_listing_paginates_with_total_count_and_has_more
        """
        state = _pagination_hotel(scenario)

        rows, meta = assert_array_envelope(
            scenario.api.list_report_packages(
                state["agreement_id"], OWNER_HEADERS, {"limit": 2, "offset": 0}
            )
        )

        assert len(rows) == 2
        assert meta["total_count"] == 3
        assert meta["limit"] == 2
        assert meta["offset"] == 0
        assert meta["has_more"] is True

    def test_the_last_window_returns_the_remainder_with_no_more_to_come(self, scenario):
        """PRD §2.3: "`offset` sets how many rows to skip and defaults to 0; it may not be
        negative." And §2.3: "Unless a specific operation says otherwise, every list is ordered
        by `created_at` ascending."

        Design: Corner/entities/report_package_listing_paginates_with_total_count_and_has_more
        """
        state = _pagination_hotel(scenario)

        rows, meta = assert_array_envelope(
            scenario.api.list_report_packages(
                state["agreement_id"], OWNER_HEADERS, {"limit": 2, "offset": 2}
            )
        )

        assert len(rows) == 1
        assert meta["total_count"] == 3
        assert meta["offset"] == 2
        assert meta["has_more"] is False
        # created_at ascending, so the third row is the November period.
        assert rows[0]["period_month"] == 11

    def test_the_period_month_filter_narrows_the_pre_paging_total(self, scenario):
        """PRD §3.4: "Packages can be read individually and listed per agreement, filterable by
        `fiscal_year`, `period_month` and `financial_status`."

        Design: Corner/entities/report_package_listing_paginates_with_total_count_and_has_more
        """
        state = _pagination_hotel(scenario)

        rows, meta = assert_array_envelope(
            scenario.api.list_report_packages(
                state["agreement_id"], OWNER_HEADERS, {"period_month": 10}
            )
        )

        assert len(rows) == 1
        assert rows[0]["period_month"] == 10
        assert meta["total_count"] == 1


# ---------------------------------------------------------------------------
# Guards on identity, required fields, enums and parent references
# ---------------------------------------------------------------------------


class TestUnknownIdentityGuards:
    def test_an_unknown_agreement_id_on_the_read_is_not_found(self, scenario):
        """PRD §2.8 rule 6: "The agreement named in the path exists; otherwise
        `ERR_AGREEMENT_NOT_FOUND` (404). Applies to every endpoint beneath
        `/hotel-management/agreements/{id}`."

        Design: Corner/entities/agreement_read_with_unknown_id_returns_not_found
        """
        response = scenario.api.get_agreement(NON_EXISTENT_UUID, ADMIN_HEADERS)

        assert_error_envelope(response, ApiErrorId.AGREEMENT_NOT_FOUND)
        assert response.status_code == 404

    def test_a_benchmark_posted_to_an_unknown_period_is_not_found(self, scenario):
        """PRD §2.8 rule 8: "The report package named in the path exists; otherwise
        `ERR_PACKAGE_NOT_FOUND` (404). Applies to every endpoint beneath
        `/hotel-management/report-packages/{id}`."

        Design: Corner/entities/benchmark_post_to_unknown_report_package_returns_not_found
        """
        agreement = scenario.register(
            hotel_name="FK Guard Hotel", owner_entity_name="FK Owner LLC"
        )
        scenario.activate(agreement["id"])
        package = scenario.package(agreement["id"], fiscal_year=2026, period_month=9)

        response = scenario.api.create_benchmark(
            NON_EXISTENT_UUID, benchmark_payload(), MANAGER_HEADERS
        )

        assert_error_envelope(response, ApiErrorId.PACKAGE_NOT_FOUND)
        assert response.status_code == 404
        assert_page(
            scenario.api.list_benchmarks(package["id"], MANAGER_HEADERS),
            expected_rows=0,
            total_count=0,
            has_more=False,
        )
        sitting = scenario.read_package(package["id"])
        assert sitting["benchmark_status"] == BenchmarkStatus.PENDING
        assert sitting["reported_rpi"] is None

    def test_a_budget_body_missing_a_required_amount_is_rejected(self, scenario):
        """PRD §3.2: "A `HotelManagerOps` actor opens a revision by naming the `fiscal_year`,
        the total budgeted gross revenue as `budgeted_revenue_cents`, the total budgeted
        operating expenses as `budgeted_operating_expenses_cents` — expenses excluding
        management fees and centralized services — and the agreement's version as
        `expected_agreement_version`." PRD §2.8 rule 3: "The body carries every required field
        with its declared type; otherwise `ERR_INVALID_REQUEST` (400)."

        Design: Corner/entities/budget_create_missing_required_fields_rejected
        """
        agreement = scenario.register(
            hotel_name="Required Fields Hotel", owner_entity_name="Required Owner LLC"
        )
        activated = scenario.activate(agreement["id"])
        version_before = activated["version"]

        response = scenario.api.create_budget(
            agreement["id"],
            {
                "fiscal_year": 2026,
                "budgeted_revenue_cents": 600000000,
                "expected_agreement_version": version_before,
            },
            MANAGER_HEADERS,
        )

        assert_error_envelope(response, ApiErrorId.INVALID_REQUEST)
        assert response.status_code == 400
        assert_page(
            scenario.api.list_budgets(MANAGER_HEADERS, {"agreement_id": agreement["id"]}),
            expected_rows=0,
            total_count=0,
            has_more=False,
        )
        # PRD §3.2: creating a revision increments the agreement's version by one; the
        # rejected create created nothing, so the parent still reads its activation version.
        assert scenario.agreement_version(agreement["id"]) == version_before

    def test_a_position_class_outside_the_declared_set_is_rejected(self, scenario):
        """PRD §2.8 rule 4: "Every enum-typed field value is a member of its declared set;
        otherwise `ERR_INVALID_ENUM` (400)." PRD §3.9: "Filing copies the agreement's
        `employee_model` into the claim's `employer_of_record`, so the claim carries the
        employment arrangement that was in force when it was filed — either `OWNER` or
        `MANAGER` — and persists the claim in `FILED` with both `owner_share_cents` and
        `manager_share_cents` at zero."

        Design: Corner/entities/employment_claim_invalid_enum_position_class_rejected
        """
        agreement = scenario.register(
            hotel_name="Enum Guard Hotel",
            owner_entity_name="Enum Owner LLC",
            manager_indemnity_cap_cents=2000000,
        )
        scenario.activate(agreement["id"])

        rejected = scenario.api.create_employment_claim(
            agreement["id"],
            employment_claim_payload(position_class="HOUSEKEEPING", claim_amount_cents=3000001),
            MANAGER_HEADERS,
        )
        assert_error_envelope(rejected, ApiErrorId.INVALID_ENUM)
        assert rejected.status_code == 400

        accepted = assert_object_envelope(
            scenario.api.create_employment_claim(
                agreement["id"],
                employment_claim_payload(
                    position_class=PositionClass.GM, claim_amount_cents=3000001
                ),
                MANAGER_HEADERS,
            ),
            201,
        )
        assert accepted["position_class"] == PositionClass.GM
        assert accepted["status"] == ClaimStatus.FILED
        assert accepted["employer_of_record"] == EmployerOfRecord.MANAGER
        assert accepted["owner_share_cents"] == 0
        assert accepted["manager_share_cents"] == 0
        assert_page(
            scenario.api.list_employment_claims(agreement["id"], ASSET_HEADERS),
            expected_rows=1,
            total_count=1,
            has_more=False,
        )


# ---------------------------------------------------------------------------
# Computed and system-stamped fields
# ---------------------------------------------------------------------------


class TestComputedAndStampedFields:
    def test_the_benchmark_index_is_computed_and_not_taken_from_the_body(self, scenario):
        """PRD §3.4: "The row's index `rpi` is the hotel's revenue per available room divided by
        the competitive set's, multiplied by 100, rounded to two decimal places. Each new
        benchmark also carries `superseded` false" And: "Posting is admissible from
        `benchmark_status` `PENDING → SUBMITTED`, which sets the package's `reported_rpi` to the
        new row's `rpi`"

        Design: Corner/entities/benchmark_rpi_computed_and_extra_field_in_payload_ignored
        """
        agreement = scenario.register(
            hotel_name="Computed Field Hotel", owner_entity_name="Computed Owner LLC"
        )
        scenario.activate(agreement["id"])
        package = scenario.package(agreement["id"], fiscal_year=2026, period_month=9)

        benchmark = assert_object_envelope(
            scenario.api.create_benchmark(
                package["id"],
                benchmark_payload(
                    hotel_revpar_cents=10000,
                    comp_set_revpar_cents=12000,
                    rooms_available=3000,
                    source=BenchmarkSource.STR_REPORT,
                    rpi=199.99,
                    superseded=True,
                ),
                MANAGER_HEADERS,
            ),
            201,
        )

        # 10000 / 12000 * 100 rounded to two places, not the 199.99 in the body.
        assert benchmark["rpi"] == 83.33
        assert benchmark["superseded"] is False
        reread = scenario.read_package(package["id"])
        assert reread["reported_rpi"] == 83.33
        assert reread["benchmark_status"] == BenchmarkStatus.SUBMITTED
        assert reread["package_status"] == PackageStatus.INCOMPLETE

    def test_the_variance_row_is_stamped_from_the_header_and_routed_at_creation(self, scenario):
        """PRD §3.3: "The acting `X-User-ID` is stamped onto the row as `requested_by_user_id`."
        And: "Otherwise `variance_pct` is the requested amount divided by the effective
        baseline, rounded to six decimal places." And: "A `MANAGER_DISCRETION` request needs no
        decision: it is persisted directly in `status` `AUTO_APPROVED`, `decided_by_user_id`
        stays null, and `PENDING` is never observable for it."

        Design: Corner/entities/variance_request_stamps_requested_by_user_id_and_system_fields
        """
        agreement = scenario.register(
            hotel_name="System Fields Hotel", owner_entity_name="System Owner LLC"
        )
        scenario.activate(agreement["id"])
        budget = scenario.budget(
            agreement["id"],
            fiscal_year=2026,
            budgeted_revenue_cents=600000000,
            budgeted_operating_expenses_cents=400000000,
        )
        scenario.submit_budget(budget["id"], MANAGER_HEADERS)
        scenario.decide_budget(budget["id"], BudgetDecision.APPROVE, OWNER_HEADERS)

        variance = scenario.variance(
            budget["id"],
            MANAGER_ALT_HEADERS,
            category=VarianceCategory.OPERATING,
            requested_amount_cents=2000000,
            justification="storm damage cleanup",
        )

        assert variance["requested_by_user_id"] == MANAGER_ALT_USER_ID
        assert_common_fields(variance)
        assert variance["version"] == 1
        assert variance["effective_baseline_cents"] == 400000000
        assert_variance_pct(variance["variance_pct"], 0.005000)
        assert variance["approval_level"] == ApprovalLevel.MANAGER_DISCRETION
        assert variance["status"] == VarianceStatus.AUTO_APPROVED
        assert variance["decided_by_user_id"] is None
        assert variance["denied_by_cascade"] is False


def _append_only_hotel(scenario):
    """A period whose executed distribution contributed 1040000 to the reserve."""
    agreement = scenario.register(
        hotel_name="Append Only Hotel",
        owner_entity_name="Ledger Only Owner LLC",
        base_fee_pct=0.03,
        incentive_fee_pct=0.10,
        owner_priority_cents=12000000,
        ffe_reserve_pct=0.04,
        working_capital_floor_cents=0,
        initial_working_capital_cents=0,
    )
    scenario.activate(agreement["id"])
    budget = scenario.budget(
        agreement["id"],
        fiscal_year=2026,
        budgeted_revenue_cents=300000000,
        budgeted_operating_expenses_cents=200000000,
    )
    scenario.submit_budget(budget["id"])
    scenario.decide_budget(budget["id"], BudgetDecision.APPROVE)

    package = scenario.package(
        agreement["id"],
        fiscal_year=2026,
        period_month=9,
        closing_cash_available_cents=5000000,
    )
    scenario.submit_package(package["id"])
    scenario.review_package(package["id"], ReviewDimension.FINANCIAL, ReviewDecision.ACCEPT)
    scenario.execute_distribution(scenario.only_distribution(package["id"])["id"])
    return {"agreement_id": agreement["id"], "package_id": package["id"]}


class TestReserveLedgerRowShape:
    def test_the_appended_row_carries_no_version_and_no_updated_at(self, scenario):
        """PRD §2.4: "The one exception is the reserve-for-replacement ledger. A
        `ReserveLedgerEntry` is append-only and is never modified after it is written, so it
        carries only `id` and `created_at`: it has no `updated_at` field and no `version` field
        at all."

        Design: Corner/entities/reserve_ledger_entry_is_append_only_without_version_field
        """
        state = _append_only_hotel(scenario)

        rows = assert_page(
            scenario.api.list_reserve_ledger(state["agreement_id"], ASSET_HEADERS),
            expected_rows=1,
            total_count=1,
            has_more=False,
        )

        assert_append_only_row(rows[0])
        assert rows[0]["entry_type"] == LedgerEntryType.CONTRIBUTION
        # Four percent of the 26000000 gross revenue of the period.
        assert rows[0]["amount_cents"] == 1040000
        assert rows[0]["balance_after_cents"] == 1040000
        assert rows[0]["source_kind"] == LedgerSourceKind.DISTRIBUTION_EXECUTION
        # PRD §2.9: the agreement's balance equals the signed sum of its ledger entries.
        assert scenario.read_agreement(state["agreement_id"])["ffe_reserve_balance_cents"] == 1040000
