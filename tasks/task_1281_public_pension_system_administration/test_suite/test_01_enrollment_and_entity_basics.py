"""Enrollment, entity field rules, listings, and the logical clock default."""
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    add_line,
    assert_contribution_line,
    assert_member,
    assert_pension_fund,
    create_disability_app,
    create_employer,
    create_fund,
    create_member,
    create_member_payload,
    create_purchase,
    create_report,
    create_retirement_app,
    make_employer_clerk_headers,
    make_member_headers,
    quote_purchase,
    reconcile_member_history,
    setup_fund_and_employer,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import ADMIN, ANALYST


class TestMemberEnrollment:
    def test_create_member_missing_employer_id_rejected(self, api):
        """PRD §3.1: "Enrollment captures the member's `full_name`,
        `date_of_birth` as an ISO date, and `hire_date` — the pension system
        entry date that later decides which service-purchase pricing window
        applies — along with the `employer_id` of the employing unit."

        Design: Corner/entities/create_member_missing_employer_id_returns_invalid_request
        """
        fund, employer = setup_fund_and_employer()
        payload = {
            "full_name": "No Employer Ned",
            "date_of_birth": "1990-01-01",
            "hire_date": "2020-01-01",
        }
        res = api.create_member(payload, ANALYST)
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)

    def test_create_member_ignores_computed_and_system_field_input(self, api):
        """PRD §3.1: "A newly enrolled member starts in `ACTIVE` status with
        `total_service_years` at zero and `current_annual_salary_cents` null,
        because no contribution has yet been credited."

        Design: Corner/entities/create_member_computed_and_system_fields_input_ignored
        """
        fund, employer = setup_fund_and_employer()
        payload = create_member_payload(
            employer["id"], full_name="Sneaky Sam",
            date_of_birth="1990-01-01", hire_date="2020-01-01")
        payload["total_service_years"] = 99
        payload["status"] = "RETIRED"
        member = validate_success(api.create_member(payload, ANALYST), 201)
        assert_member(member)
        assert member["status"] == "ACTIVE", (
            f"new member must start ACTIVE regardless of input, "
            f"got {member['status']}")
        assert member["total_service_years"] == 0, (
            f"new member must start at 0 service years regardless of input, "
            f"got {member['total_service_years']}")
        assert member["current_annual_salary_cents"] is None

    def test_get_member_not_found_returns_error_envelope(self, api):
        """PRD §2.8: "4. **Existence** — every path id exists, validated left
        to right, and every foreign-key reference in the body resolves
        (`ERR_NOT_FOUND`)."

        Design: Corner/entities/get_member_not_found_returns_error_envelope
        """
        fund, employer = setup_fund_and_employer()
        res = api.get_member(NON_EXISTENT_UUID, ANALYST)
        validate_error(res, ApiErrorId.ERR_NOT_FOUND)


class TestContributionLineDefaults:
    def test_service_months_defaults_to_twelve_and_line_starts_pending(self, api):
        """PRD §3.2: "each accepted line contributes its `service_months` — an
        integer from 1 to 12, defaulting to 12 when not supplied — divided by
        twelve months per year."
        PRD §3.3: "Every line begins life in `PENDING`."

        Design: Corner/entities/create_contribution_line_default_service_months_applied
        """
        fund, employer = setup_fund_and_employer()
        member = create_member(employer["id"], full_name="Default Dee",
                               date_of_birth="1990-01-01",
                               hire_date="2020-01-01")
        report = create_report(employer["id"], "2023-01-01", "2024-01-01",
                               480_000)
        line = validate_success(api.create_contribution_line(
            report["id"],
            {"member_id": member["id"], "fiscal_year": 2023,
             "period_salary_cents": 6_000_000,
             "contribution_amount_cents": 480_000},
            make_employer_clerk_headers(employer["id"])), 201)
        assert_contribution_line(line)
        assert line["service_months"] == 12, (
            f"omitted service_months must default to 12, "
            f"got {line['service_months']}")
        assert line["status"] == "PENDING"


class TestListingsAndPagination:
    def test_lines_pagination_limit_offset_interaction(self, api):
        """PRD §2.3: "The `meta` block of a list response carries `limit`,
        `offset`, `total_count`, and `has_more`, so a client can page
        deterministically through an employer's reports or a member's
        contribution history without holding the collection in memory."

        Design: Corner/entities/list_lines_pagination_limit_offset_interaction
        """
        fund, employer = setup_fund_and_employer()
        member = create_member(employer["id"], full_name="Page Polly",
                               date_of_birth="1990-01-01",
                               hire_date="2020-01-01")
        report = create_report(employer["id"], "2018-01-01", "2024-01-01",
                               2_400_000)
        for fy in range(2018, 2024):
            add_line(report["id"], employer["id"], member["id"], fy,
                     5_000_000, 400_000)
        data, meta = validate_paginated(api.list_contribution_lines(
            report["id"], ANALYST, params={"limit": 4, "offset": 4}))
        assert len(data) == 2, f"expected last 2 of 6 lines, got {len(data)}"
        assert meta["total_count"] == 6
        assert meta["has_more"] is False
        assert meta["limit"] == 4
        assert meta["offset"] == 4

    def test_child_lists_return_exactly_the_named_parents_children(self, api):
        """PRD §2.9: "Paths that nest one resource under another — an
        employer's contribution reports, a member's retirement applications,
        a report's lines — validate their path identifiers from left to right"
        PRD §2.3: "so a client can page deterministically through an
        employer's reports or a member's contribution history without holding
        the collection in memory."

        Design: Corner/entities/fk_reverse_reachability_lists_children
        """
        fund = create_fund()
        e1 = create_employer(name="E1", employer_code="E1")
        e2 = create_employer(name="E2", employer_code="E2")
        r1 = create_report(e1["id"], "2022-01-01", "2023-01-01", 100)
        r2 = create_report(e1["id"], "2023-01-01", "2024-01-01", 100)
        create_report(e2["id"], "2023-01-01", "2024-01-01", 100)
        member = create_member(e1["id"], full_name="Child Chuck",
                               date_of_birth="1990-01-01",
                               hire_date="2020-01-01")
        line = add_line(r1["id"], e1["id"], member["id"], 2022, 1_250, 100)

        reports, meta_r = validate_paginated(
            api.list_employer_contribution_reports(e1["id"], ANALYST))
        assert meta_r["total_count"] == 2, (
            f"E1 must see exactly its own 2 reports, got {meta_r['total_count']}")
        assert {r["id"] for r in reports} == {r1["id"], r2["id"]}

        lines, meta_l = validate_paginated(
            api.list_contribution_lines(r1["id"], ANALYST))
        assert meta_l["total_count"] == 1
        assert [l["id"] for l in lines] == [line["id"]]


class TestServicePurchaseCreation:
    def test_create_purchase_invalid_enum_rejected(self, api):
        """PRD §3.4: "The member — or an analyst filing on the member's behalf
        — requests a service purchase by supplying the `purchase_type`
        (`MILITARY` or `PRIOR_SERVICE`), the `service_period_start` and
        `service_period_end` of the period being purchased, and the
        `years_purchased` to two decimal places."

        Design: Corner/entities/create_purchase_invalid_enum_returns_invalid_request
        """
        fund, employer = setup_fund_and_employer()
        member = create_member(employer["id"], full_name="Enum Ed",
                               date_of_birth="1990-01-01",
                               hire_date="2020-01-01")
        res = api.create_service_purchase(
            member["id"],
            {"purchase_type": "SPACE_TRAVEL",
             "service_period_start": "2005-01-01",
             "service_period_end": "2006-12-31",
             "years_purchased": 2.0},
            make_member_headers(member["id"]))
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)


class TestInitialStatesOnCreation:
    def test_new_resources_start_in_their_initial_states(self, api):
        """PRD §3.3: "The report is born in `DRAFT` with `accepted_total_cents`
        at zero."
        PRD §3.4: "The new purchase is born in `REQUESTED`"
        PRD §3.5: "A retirement application is created in `DRAFT`"
        PRD §3.6: "The application enters `UNDER_MEDICAL_REVIEW` immediately
        upon creation"

        Design: Corner/state_machines/initial_states_on_creation
        """
        fund, employer = setup_fund_and_employer()
        member = create_member(employer["id"], full_name="Initial Irene")
        report = create_report(employer["id"], "2023-01-01", "2024-01-01", 100)
        assert report["status"] == "DRAFT"
        assert report["accepted_total_cents"] == 0

        purchase = create_purchase(member["id"])
        assert purchase["status"] == "REQUESTED"

        app = create_retirement_app(member["id"], "SINGLE_LIFE")
        assert app["status"] == "DRAFT"

        disability = create_disability_app(member["id"], "DUTY")
        assert disability["status"] == "UNDER_MEDICAL_REVIEW"


class TestLogicalClockDefault:
    def test_quote_expiry_derives_from_fixed_startup_clock(self, api):
        """PRD §2.5: "At server startup the logical clock reads exactly
        `2026-08-01T00:00:00Z` and holds that fixed instant until a FundAdmin
        sets it via the test-driving capability"
        PRD §3.4: "Every quote carries a shelf life: `quote_expires_at` is the
        quote datetime plus 90 days, after which the offer lapses."

        Design: Corner/endpoints/clock_default_is_fixed_2026_08_01
        """
        # Deliberately NO clock-set call: the startup default must hold.
        fund = create_fund()
        employer = create_employer()
        member = create_member(employer["id"], full_name="Clock Chloe",
                               date_of_birth="1980-01-01",
                               hire_date="2010-01-01")
        reconcile_member_history(employer["id"], [{
            "member_id": member["id"], "fiscal_year": 2023,
            "salary_cents": 6_000_000}])
        purchase = create_purchase(member["id"])
        quoted = quote_purchase(purchase["id"])
        assert quoted["quote_expires_at"] == "2026-10-30T00:00:00Z", (
            f"default clock 2026-08-01 + 90 days must be 2026-10-30T00:00:00Z, "
            f"got {quoted['quote_expires_at']}")


class TestErrorCatalogSmoke:
    def test_fund_read_smoke_for_error_catalog_sweep(self, api):
        """PRD §3.1: "A FundAdmin creates the fund with a display `fund_name`,
        the annual `cola_rate_pct` expressed as a decimal fraction, and the
        `earnings_limit_annual_cents` that governs return-to-work retirees."

        Design: Corner/errors/error_catalog_residual_coverage
        """
        fund = create_fund(fund_name="State Retirement")
        read = validate_success(api.get_pension_fund(fund["id"], ADMIN), 200)
        assert_pension_fund(read)
        assert read["id"] == fund["id"]
        assert read["fund_name"] == "State Retirement"
        assert read["cola_rate_pct"] == pytest.approx(0.025)
        assert read["earnings_limit_annual_cents"] == 3_000_000
