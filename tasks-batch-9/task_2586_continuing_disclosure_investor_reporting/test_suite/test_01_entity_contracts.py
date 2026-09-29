"""Entity contracts: creation echoes, seeded system fields, reads, listing and shape refusals.

Every test in this module translates exactly one instance of the `entities`
section of SCAFFOLD_CORNER_DESIGN.yaml.  Each test starts against an empty
database whose logical clock reads its startup value of 2026-08-01T00:00:00Z.
"""

import re

import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_annual_report_cycle,
    assert_bond_issue,
    assert_content_requirement,
    assert_cycle_content_item,
    assert_dissemination_engagement,
    assert_filing,
    assert_material_event_notice,
    assert_official_statement,
    assert_two_decimals,
    assert_undertaking,
    assemble,
    attest_item,
    create_bond_issue,
    create_content_requirement,
    create_cycle,
    create_notice,
    create_undertaking,
    is_valid_uuid,
    list_content_items,
    prepare_item,
    read_bond_issue,
    setup_issue_with_undertaking,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import TEST_USERS

FD = TEST_USERS["finance_director_headers"]
OFFICER = TEST_USERS["disclosure_officer_headers"]
REVIEWER = TEST_USERS["compliance_reviewer_headers"]

# A well-formed UUID that no endpoint in the service ever mints, so the request
# shape check of rule 5 passes and the existence rules are what fire.
PROBE_UUID = "00000000-0000-4000-8000-000000000000"

_MILLIS_TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")


def assert_millisecond_timestamp(value, label: str = "timestamp"):
    """PRD §2.4 pins the housekeeping timestamps to three fractional digits."""
    assert _MILLIS_TIMESTAMP_RE.match(str(value)), (
        f"{label} must be an ISO 8601 UTC timestamp with three fractional digits, got {value!r}"
    )


def read_page(response):
    """Validate a list envelope and return its (rows, meta) pair."""
    rows, meta = validate_paginated(response)
    body = response.json()
    assert body["response_type"] == "array", (
        f"a list endpoint must answer with response_type 'array', got {body['response_type']!r}"
    )
    assert isinstance(body["meta"].get("api_request_id"), str), "meta.api_request_id must be present"
    assert isinstance(body["meta"].get("api_request_timestamp"), str), (
        "meta.api_request_timestamp must be present"
    )
    return rows, meta


class TestBondIssueCreation:
    """POST /disclosure/bond-issues — echoed inputs, seeded system fields, shape refusals."""

    def test_bond_issue_creation_returns_every_declared_field(self):
        """Registering an issue echoes all six inputs and seeds all eight system fields.

        PRD §3.1: "A freshly registered issue opens in `status` `OUTSTANDING` with `version` 1."
        PRD §3.1: "Its `outstanding_par_amount_cents` is initialised to the value of `original_par_amount_cents`; `open_material_event_count` is 0; and `current_rating`, `current_rating_agency`, `defeasance_type`, and `defeased_at` are all null, while `escrow_deposit_cents` starts at 0."
        PRD §2.4: "Every stored resource carries a server-minted `id`, which is a UUID with no type prefix of any kind."
        PRD §2.4: "`created_at` is the ISO 8601 UTC timestamp, with three fractional digits, at which the row was first written."
        Design: Corner/entities/bond_issue_creation_returns_every_declared_field
        """
        payload = {
            "issuer_program_code": "CIVICCENTER",
            "series_designation": "2026A",
            "security_type": "SPECIAL_ASSESSMENT",
            "dated_date": "2026-04-01",
            "final_maturity_date": "2056-04-01",
            "original_par_amount_cents": 75000000,
        }
        issue = validate_success(api_client.create_bond_issue(payload, FD), 201)
        assert_bond_issue(issue)

        # The six declared inputs are echoed verbatim.
        assert issue["issuer_program_code"] == "CIVICCENTER"
        assert issue["series_designation"] == "2026A"
        assert issue["security_type"] == "SPECIAL_ASSESSMENT"
        assert issue["dated_date"] == "2026-04-01"
        assert issue["final_maturity_date"] == "2056-04-01"
        assert issue["original_par_amount_cents"] == 75000000

        # outstanding par is seeded FROM original par, not from zero.
        assert issue["outstanding_par_amount_cents"] == 75000000

        assert issue["status"] == "OUTSTANDING"
        assert issue["escrow_deposit_cents"] == 0
        assert issue["open_material_event_count"] == 0
        assert issue["version"] == 1

        assert issue["current_rating"] is None
        assert issue["current_rating_agency"] is None
        assert issue["defeasance_type"] is None
        assert issue["defeased_at"] is None

        assert is_valid_uuid(issue["id"]), "id must be a bare UUID"
        assert "_" not in issue["id"], "id must carry no type prefix"
        assert_millisecond_timestamp(issue["created_at"], "BondIssue.created_at")
        assert_millisecond_timestamp(issue["updated_at"], "BondIssue.updated_at")

    @pytest.mark.parametrize(
        "field_overrides, why",
        [
            ({"security_type": "MORAL_OBLIGATION"}, "enum value outside the declared set"),
            ({"final_maturity_date": "2026-04-01"}, "final maturity equal to the dated date"),
            ({"original_par_amount_cents": 0}, "par amount below the declared floor of 1"),
        ],
    )
    def test_bond_issue_creation_rejects_unknown_enum_and_inverted_dates(self, field_overrides, why):
        """Three shape failures on the same endpoint all collapse to ERR_INVALID_REQUEST.

        PRD §3.1: "`security_type` records the pledge class and is one of `GENERAL_OBLIGATION`, `REVENUE`, or `SPECIAL_ASSESSMENT`."
        PRD §3.1: "Both dates are ISO 8601 calendar dates and `final_maturity_date` must fall strictly after `dated_date`."
        PRD §3.1: "`original_par_amount_cents` is an integer of at least 1."
        PRD §2.10: "Request shape — every required input present; every enum value inside its declared set; integers non-negative where declared; dates in ISO 8601 form; `period_start_date` strictly before `period_end_date`; `weight_bp` between 1 and 10000 inclusive; `retainer_cents` at least 0; `disclosed_event_ids` a possibly empty array of distinct ids → `ERR_INVALID_REQUEST` (422)."
        Design: Corner/entities/bond_issue_creation_rejects_unknown_enum_and_inverted_dates
        """
        payload = {
            "issuer_program_code": "CIVICCENTER",
            "series_designation": "2026A",
            "security_type": "REVENUE",
            "dated_date": "2026-04-01",
            "final_maturity_date": "2056-04-01",
            "original_par_amount_cents": 75000000,
        }
        payload.update(field_overrides)

        validate_error(
            api_client.create_bond_issue(payload, FD),
            ApiErrorId.ERR_INVALID_REQUEST.value,
        )

        # The refused request created nothing.
        rows, meta = read_page(api_client.list_bond_issues(FD))
        assert meta["total_count"] == 0, f"a request refused for a {why} must write no row"
        assert rows == []


class TestUndertakingContract:
    """POST + GET /disclosure/undertakings — stored inputs, declared defaults, side-effect-free reads."""

    def test_undertaking_retrieval_returns_the_stored_row_unchanged(self):
        """A GET right after creation returns the same field values and leaves version at 1.

        PRD §2.4: "`version` is an integer that starts at 1 when the row is created and increases by exactly 1 on every mutation of that row, again including cascaded mutations."
        PRD §2.1: "Every single-resource read and every list endpoint under `/disclosure` is available to all four roles; the write surface is partitioned exactly as described above and enumerated in §4."
        PRD §3.2: "A new undertaking opens with `status` `ACTIVE`, `compliance_posture` `COMPLIANT`, `remediation_tier` `TIER_0`, `disclosure_risk_score` 0.00, `version` 1, and null `suspended_reason` and `termination_cause`."
        Design: Corner/entities/undertaking_retrieval_returns_the_stored_row_unchanged
        """
        issue = create_bond_issue()
        created = validate_success(
            api_client.create_undertaking(
                {
                    "issue_id": issue["id"],
                    "fiscal_year_end_month_day": "09-30",
                    "filing_window_days": 180,
                    "timeliness_basis": "CONFIRMATION_BASIS",
                },
                FD,
            ),
            201,
        )
        assert created["version"] == 1

        # A ComplianceReviewer may read a row a FinanceDirector created.
        fetched = validate_success(api_client.get_undertaking(created["id"], REVIEWER), 200)
        assert_undertaking(fetched)

        assert fetched["id"] == created["id"]
        assert fetched["issue_id"] == issue["id"]
        assert fetched["fiscal_year_end_month_day"] == "09-30"
        assert fetched["filing_window_days"] == 180
        assert fetched["timeliness_basis"] == "CONFIRMATION_BASIS"
        assert fetched["status"] == "ACTIVE"

        # The read did not bump version.
        assert fetched["version"] == created["version"] == 1
        assert fetched["created_at"] == created["created_at"]
        assert fetched["updated_at"] == created["updated_at"]

    def test_undertaking_omitted_optional_inputs_take_their_declared_defaults(self):
        """The two omitted optional inputs default to 210 / SUBMISSION_BASIS, and the window shows up downstream.

        PRD §3.2: "`filing_window_days` is the number of calendar days after a reporting period ends by which the annual report is due; it accepts any integer from 1 through 365 and defaults to 210 when omitted."
        PRD §3.2: "`timeliness_basis` is one of `SUBMISSION_BASIS` or `CONFIRMATION_BASIS`, defaults to `SUBMISSION_BASIS`, and is the single most consequential choice on the row: it selects, once and for every reporting cycle the undertaking will ever own, which instant the timeliness verdict of §3.7 measures."
        PRD §3.2: "All four counters — `late_filing_count`, `missed_event_count`, `delinquent_cycle_count`, and `open_obligation_count` — start at 0, and so does `content_weight_bp_total`."
        PRD §3.3: "Take the cycle's own `period_end_date`, advance it by the owning undertaking's `filing_window_days` in **calendar** days, then roll the result forward — never backward — to the first business day at or after it, using the calendar of §2.6."
        Design: Corner/entities/undertaking_omitted_optional_inputs_take_their_declared_defaults
        """
        issue = create_bond_issue()
        undertaking = validate_success(
            api_client.create_undertaking(
                {"issue_id": issue["id"], "fiscal_year_end_month_day": "06-30"}, FD
            ),
            201,
        )
        assert_undertaking(undertaking)

        assert undertaking["filing_window_days"] == 210
        assert undertaking["timeliness_basis"] == "SUBMISSION_BASIS"

        assert undertaking["status"] == "ACTIVE"
        assert undertaking["suspended_reason"] is None
        assert undertaking["termination_cause"] is None

        assert undertaking["compliance_posture"] == "COMPLIANT"
        assert_two_decimals(undertaking["disclosure_risk_score"], "disclosure_risk_score")
        assert float(undertaking["disclosure_risk_score"]) == pytest.approx(0.00, abs=0.01)
        assert undertaking["remediation_tier"] == "TIER_0"

        assert undertaking["late_filing_count"] == 0
        assert undertaking["missed_event_count"] == 0
        assert undertaking["delinquent_cycle_count"] == 0
        assert undertaking["open_obligation_count"] == 0
        assert undertaking["content_weight_bp_total"] == 0

        # The default window is observable downstream as the cycle's derived due date.
        create_content_requirement(
            undertaking["id"],
            kind="OPERATING_DATA_TABLE",
            label="Operating Data Tables",
            weight_bp=10000,
        )
        cycle = create_cycle(
            undertaking["id"],
            fiscal_year_label="FY2026",
            period_start_date="2025-07-01",
            period_end_date="2026-06-30",
        )
        assert cycle["due_date"] == "2027-01-26"


class TestListingAndNotFound:
    """Pagination fields and the eleven entity-specific not-found codes."""

    def test_material_event_notice_listing_paginates_with_total_count_and_has_more(self):
        """Three notices against limit 2 pin all four pagination fields and the default limit of 10.

        PRD §2.3: "`limit` is an integer with a minimum of 1, a maximum of 100, and a default of 10 when omitted."
        PRD §2.3: "List responses carry `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object, where `total_count` is the size of the full filtered result set before the window is applied and `has_more` indicates whether any row remains beyond the returned window."
        PRD §2.3: "Rows are returned in ascending `created_at` order, with `id` ascending as the tie-breaker."
        Design: Corner/entities/material_event_notice_listing_paginates_with_total_count_and_has_more
        """
        issue = create_bond_issue()
        first = create_notice(
            issue["id"], event_type="TRUSTEE_SUBSTITUTION", occurrence_date="2026-07-20"
        )
        second = create_notice(
            issue["id"], event_type="UNSCHEDULED_DRAW_ON_RESERVE", occurrence_date="2026-07-21"
        )
        third = create_notice(
            issue["id"], event_type="MERGER_OR_SALE", occurrence_date="2026-07-22"
        )

        page_one, meta_one = read_page(
            api_client.list_material_event_notices(
                FD, params={"issue_id": issue["id"], "limit": 2, "offset": 0}
            )
        )
        assert len(page_one) == 2
        assert page_one[0]["id"] == first["id"]
        assert page_one[1]["id"] == second["id"]
        assert meta_one["total_count"] == 3
        assert meta_one["has_more"] is True
        assert meta_one["limit"] == 2
        assert meta_one["offset"] == 0

        page_two, meta_two = read_page(
            api_client.list_material_event_notices(
                FD, params={"issue_id": issue["id"], "limit": 2, "offset": 2}
            )
        )
        assert len(page_two) == 1
        assert page_two[0]["id"] == third["id"]
        assert meta_two["total_count"] == 3
        assert meta_two["has_more"] is False
        assert meta_two["offset"] == 2

        unparameterised, meta_three = read_page(
            api_client.list_material_event_notices(FD, params={"issue_id": issue["id"]})
        )
        assert meta_three["limit"] == 10, "the declared default limit is 10, not 50"
        assert meta_three["offset"] == 0
        assert meta_three["total_count"] == 3
        assert meta_three["has_more"] is False
        assert len(unparameterised) == 3
        assert [row["id"] for row in unparameterised] == [
            first["id"],
            second["id"],
            third["id"],
        ]

    @pytest.mark.parametrize(
        "endpoint, expected_error",
        [
            ("get_bond_issue", ApiErrorId.ERR_ISSUE_NOT_FOUND),
            ("get_undertaking", ApiErrorId.ERR_UNDERTAKING_NOT_FOUND),
            ("get_content_requirement", ApiErrorId.ERR_REQUIREMENT_NOT_FOUND),
            ("get_annual_report_cycle", ApiErrorId.ERR_CYCLE_NOT_FOUND),
            ("get_content_item", ApiErrorId.ERR_CONTENT_ITEM_NOT_FOUND),
            ("get_material_event_notice", ApiErrorId.ERR_EVENT_NOTICE_NOT_FOUND),
            ("get_filing", ApiErrorId.ERR_FILING_NOT_FOUND),
            ("get_failure_event", ApiErrorId.ERR_FAILURE_EVENT_NOT_FOUND),
            ("get_direct_placement", ApiErrorId.ERR_PLACEMENT_NOT_FOUND),
            ("get_official_statement", ApiErrorId.ERR_OFFICIAL_STATEMENT_NOT_FOUND),
            ("get_engagement", ApiErrorId.ERR_ENGAGEMENT_NOT_FOUND),
        ],
    )
    def test_single_resource_get_with_unknown_id_returns_the_entity_specific_not_found(
        self, endpoint, expected_error
    ):
        """Each single-resource read answers with its own entity's not-found code, never one shared 404.

        PRD §2.9: "Every `{id}` segment must resolve to a stored row of the endpoint's own entity; the first segment that fails yields that entity's own not-found error with HTTP 404."
        PRD §2.10: "Path existence — every `{id}` path segment resolves, left to right → the entity-specific not-found error (404). Applies to every endpoint with an `{id}` path parameter."
        Design: Corner/entities/single_resource_get_with_unknown_id_returns_the_entity_specific_not_found
        """
        response = getattr(api_client, endpoint)(PROBE_UUID, FD)
        validate_error(response, expected_error.value, 404)
        assert response.json()["response_type"] == "error"


class TestContentRequirementContract:
    """POST + GET /disclosure/content-requirements — the required weight, and immutability."""

    def test_content_requirement_creation_missing_required_weight_bp_returns_invalid_request(self):
        """weight_bp is required and range-checked at 1..10000, and only the valid create persists.

        PRD §3.2: "Each declaration is one **`ContentRequirement`** naming its `undertaking_id`, a `kind` drawn from `AUDITED_FINANCIALS`, `OPERATING_DATA_TABLE`, `BUDGET_SUMMARY`, `DEBT_SERVICE_SCHEDULE`, or `ENTERPRISE_STATISTICS`, a human `label` of 1 to 120 characters for the annual report's table of contents, and a `weight_bp` between 1 and 10000 giving that item's share of the completeness score in basis points."
        PRD §2.10: "Request shape — every required input present; every enum value inside its declared set; integers non-negative where declared; dates in ISO 8601 form; `period_start_date` strictly before `period_end_date`; `weight_bp` between 1 and 10000 inclusive; `retainer_cents` at least 0; `disclosed_event_ids` a possibly empty array of distinct ids → `ERR_INVALID_REQUEST` (422)."
        PRD §3.2: "An optional `waivable` flag, false when omitted, records whether a `ComplianceReviewer` is permitted to waive the item on a cycle."
        PRD §3.2: "One further field, `requires_audit_opinion`, is derived rather than supplied: it is true when and only when `kind` is `AUDITED_FINANCIALS`, and any value a client sends for it is discarded."
        Design: Corner/entities/content_requirement_creation_missing_required_weight_bp_returns_invalid_request
        """
        context = setup_issue_with_undertaking()
        undertaking_id = context["undertaking"]["id"]
        base = {
            "undertaking_id": undertaking_id,
            "kind": "AUDITED_FINANCIALS",
            "label": "Audited Financial Statements",
        }

        # weight_bp omitted entirely: a shape violation, not a silent zero.
        validate_error(
            api_client.create_content_requirement(dict(base), OFFICER),
            ApiErrorId.ERR_INVALID_REQUEST.value,
        )
        # 0 is below the declared range.
        validate_error(
            api_client.create_content_requirement(dict(base, weight_bp=0), OFFICER),
            ApiErrorId.ERR_INVALID_REQUEST.value,
        )
        # 10001 is above it.
        validate_error(
            api_client.create_content_requirement(dict(base, weight_bp=10001), OFFICER),
            ApiErrorId.ERR_INVALID_REQUEST.value,
        )

        accepted = validate_success(
            api_client.create_content_requirement(dict(base, weight_bp=10000), OFFICER), 201
        )
        assert_content_requirement(accepted)
        assert accepted["weight_bp"] == 10000
        assert accepted["waivable"] is False
        assert accepted["requires_audit_opinion"] is True

        rows, meta = read_page(
            api_client.list_content_requirements(FD, params={"undertaking_id": undertaking_id})
        )
        assert meta["total_count"] == 1, "the three refused requests created nothing"
        assert len(rows) == 1
        assert rows[0]["id"] == accepted["id"]

    def test_content_requirement_is_immutable_with_no_version_and_no_update_endpoint(self):
        """A content requirement carries id and created_at but neither updated_at nor version.

        PRD §2.4: "A content requirement is immutable configuration — there is no endpoint that modifies one — and it therefore carries only `id` and `created_at`."
        PRD §2.4: "A `ContentRequirement` has no `updated_at` field and no `version` field at all."
        PRD §3.2: "Requirements are immutable configuration: nothing in the service modifies one once written, which is why a `ContentRequirement` carries neither `updated_at` nor `version`."
        Design: Corner/entities/content_requirement_is_immutable_with_no_version_and_no_update_endpoint
        """
        context = setup_issue_with_undertaking()
        created = create_content_requirement(
            context["undertaking"]["id"],
            kind="OPERATING_DATA_TABLE",
            label="Operating Data Tables",
            weight_bp=10000,
        )

        fetched = validate_success(
            api_client.get_content_requirement(created["id"], FD), 200
        )
        assert_content_requirement(fetched)

        assert fetched["id"] == created["id"]
        assert fetched["created_at"] == created["created_at"]
        assert "version" not in fetched, "ContentRequirement carries no version field"
        assert "updated_at" not in fetched, "ContentRequirement carries no updated_at field"

        assert fetched["kind"] == "OPERATING_DATA_TABLE"
        assert fetched["weight_bp"] == 10000
        assert fetched["waivable"] is False
        assert fetched["requires_audit_opinion"] is False


class TestComputedAndSystemFields:
    """Client-supplied values for computed or system fields are discarded and re-derived."""

    def test_material_event_notice_computed_fields_recomputed_and_extra_input_ignored(self):
        """per_se_material and filing_deadline_date are derived from the event type and occurrence date.

        PRD §3.5: "`per_se_material` is true if and only if `event_type` is one of the four per-se listed events — `PRINCIPAL_PAYMENT_DELINQUENCY`, `RATING_CHANGE`, `DEFEASANCE`, `BOND_CALL` — and false for the other four."
        PRD §3.5: "And `filing_deadline_date` is the **tenth business day strictly after** `occurrence_date`, computed with the add-business-days rule of §2.6: the occurrence date itself is never counted whether or not it is a business day, and the result is the tenth business day encountered walking forward."
        PRD §3.5: "The notice opens in `status` `DETERMINATION_PENDING`, `version` 1, `days_late` 0, and records `created_by_user_id` from `X-User-ID`; `determination_note`, `determined_by_user_id`, `determined_at`, `rating_agency`, `prior_rating`, `new_rating`, and `filed_filing_id` all start null."
        Design: Corner/entities/material_event_notice_computed_fields_recomputed_and_extra_input_ignored
        """
        issue = create_bond_issue()

        per_se = validate_success(
            api_client.create_material_event_notice(
                {
                    "issue_id": issue["id"],
                    "event_type": "BOND_CALL",
                    "occurrence_date": "2026-08-01",
                    "per_se_material": False,
                    "filing_deadline_date": "2026-12-31",
                    "status": "FILED_TIMELY",
                    "days_late": 99,
                },
                OFFICER,
            ),
            201,
        )
        assert_material_event_notice(per_se)

        assert per_se["per_se_material"] is True, "BOND_CALL is per se material whatever the client claims"
        assert per_se["filing_deadline_date"] == "2026-08-14"
        assert per_se["status"] == "DETERMINATION_PENDING"
        assert per_se["days_late"] == 0
        assert per_se["version"] == 1
        assert per_se["created_by_user_id"] == "off-prep"

        # The deadline is a pure function of occurrence_date, identical for a non-per-se type.
        ordinary = validate_success(
            api_client.create_material_event_notice(
                {
                    "issue_id": issue["id"],
                    "event_type": "MERGER_OR_SALE",
                    "occurrence_date": "2026-08-01",
                },
                OFFICER,
            ),
            201,
        )
        assert_material_event_notice(ordinary)
        assert ordinary["per_se_material"] is False
        assert ordinary["filing_deadline_date"] == "2026-08-14"

    def test_annual_report_cycle_system_fields_are_server_minted_and_extra_input_ignored(self):
        """Cycle creation mints its own system fields and snapshots one item per requirement.

        PRD §3.3: "The cycle itself opens in `status` `DRAFTING` with `version` 1, `completeness_score_pct` 0.00, `days_late` 0, and null `assembled_by_user_id`, `assembled_at`, `filed_filing_id`, `filed_at`, `timeliness_basis_applied`, and `withdrawal_reason`."
        PRD §3.3: "One **`CycleContentItem`** is minted for each `ContentRequirement` of the undertaking, each carrying the `cycle_id` of the new cycle, the `content_requirement_id` of its source requirement, `status` `NOT_STARTED`, `readiness_factor` 0.0, and a `weight_bp_snapshot` copied from the requirement's `weight_bp` at that instant."
        PRD §3.3: "Take the cycle's own `period_end_date`, advance it by the owning undertaking's `filing_window_days` in **calendar** days, then roll the result forward — never backward — to the first business day at or after it, using the calendar of §2.6."
        Design: Corner/entities/annual_report_cycle_system_fields_are_server_minted_and_extra_input_ignored
        """
        context = setup_issue_with_undertaking()
        undertaking_id = context["undertaking"]["id"]
        heavy = create_content_requirement(
            undertaking_id,
            kind="OPERATING_DATA_TABLE",
            label="Operating Data Tables",
            weight_bp=7000,
        )
        light = create_content_requirement(
            undertaking_id,
            kind="DEBT_SERVICE_SCHEDULE",
            label="Debt Service Schedule",
            weight_bp=3000,
        )

        cycle = validate_success(
            api_client.create_annual_report_cycle(
                {
                    "undertaking_id": undertaking_id,
                    "fiscal_year_label": "FY2026",
                    "period_start_date": "2025-07-01",
                    "period_end_date": "2026-06-30",
                    "status": "READY_TO_FILE",
                    "due_date": "2026-01-01",
                    "completeness_score_pct": 88.88,
                    "days_late": 42,
                    "assembled_by_user_id": "off-prep",
                    "filed_filing_id": PROBE_UUID,
                },
                OFFICER,
            ),
            201,
        )
        assert_annual_report_cycle(cycle)

        assert cycle["status"] == "DRAFTING", "the client's READY_TO_FILE is ignored"
        assert cycle["due_date"] == "2027-01-26", "the due date is recomputed, not taken from the body"
        assert float(cycle["completeness_score_pct"]) == pytest.approx(0.00, abs=0.01)
        assert cycle["days_late"] == 0
        assert cycle["assembled_by_user_id"] is None
        assert cycle["assembled_at"] is None
        assert cycle["filed_filing_id"] is None
        assert cycle["timeliness_basis_applied"] is None
        assert cycle["filed_at"] is None
        assert cycle["withdrawal_reason"] is None
        assert cycle["version"] == 1

        all_items, all_meta = read_page(
            api_client.list_content_items(OFFICER, params={"cycle_id": cycle["id"]})
        )
        assert all_meta["total_count"] == 2, "one item per ContentRequirement, cascade-created"
        assert len(all_items) == 2

        heavy_items, _ = read_page(
            api_client.list_content_items(
                OFFICER,
                params={"cycle_id": cycle["id"], "content_requirement_id": heavy["id"]},
            )
        )
        assert len(heavy_items) == 1
        heavy_item = heavy_items[0]
        assert_cycle_content_item(heavy_item)
        assert heavy_item["status"] == "NOT_STARTED"
        assert heavy_item["weight_bp_snapshot"] == 7000
        assert float(heavy_item["readiness_factor"]) == pytest.approx(0.0, abs=0.01)
        assert heavy_item["attested_by_user_id"] is None
        assert heavy_item["version"] == 1
        assert heavy_item["cycle_id"] == cycle["id"]

        light_items, _ = read_page(
            api_client.list_content_items(
                OFFICER,
                params={"cycle_id": cycle["id"], "content_requirement_id": light["id"]},
            )
        )
        assert len(light_items) == 1
        assert light_items[0]["status"] == "NOT_STARTED"
        assert light_items[0]["weight_bp_snapshot"] == 3000


class TestForeignKeyAndCrossReferenceIntegrity:
    """Body foreign keys are resolved before the concurrency and integrity rungs."""

    def test_dissemination_engagement_creation_with_unknown_undertaking_id_returns_not_found(self):
        """A non-existent undertaking_id is a 404 even when the version supplied is a real one.

        PRD §2.10: "Body foreign-key existence — every foreign-key field in the body resolves, in declared input order → the entity-specific not-found error (404). Applies to every create and update endpoint carrying a foreign key."
        PRD §2.10: "Optimistic concurrency — the supplied `expected_issue_version` or `expected_undertaking_version` equals the parent's current `version` → `ERR_ISSUE_VERSION_STALE` or `ERR_UNDERTAKING_VERSION_STALE` (412). Applies to `POST /disclosure/filings`, `POST /disclosure/bond-issues/{id}/rating-actions`, and `POST /disclosure/dissemination-engagements`."
        PRD §3.10: "The engagement opens at `status` `ACTIVE`, `version` 1, `billable_filing_count` 0, with `superseded_by_engagement_id` and `termination_reason` null."
        PRD §3.10: "`monitoring_lapse_days` is the whole calendar days from the later-of-nothing baseline — `last_calendar_ack_date` when it is set, and `effective_date` when it is null — to the logical clock's date, floored at 0."
        PRD §3.10: "The cap and the floor then apply in this exact nested order: the subtotal plus surcharge is first capped at 12,000 dollars (1200000 cents), and that capped figure is then raised to the minimum annual fee of 3,000 dollars (300000 cents) if it falls below it."
        Design: Corner/entities/dissemination_engagement_creation_with_unknown_undertaking_id_returns_not_found
        """
        context = setup_issue_with_undertaking()
        undertaking = context["undertaking"]
        assert undertaking["version"] == 1

        ghost = {
            "undertaking_id": PROBE_UUID,
            "agent_name": "Ghost Agent LLC",
            "effective_date": "2026-08-01",
            "expiration_date": "2027-12-31",
            "retainer_cents": 250000,
            "expected_undertaking_version": undertaking["version"],
        }
        validate_error(
            api_client.create_engagement(ghost, FD),
            ApiErrorId.ERR_UNDERTAKING_NOT_FOUND.value,
            404,
        )

        engagement = validate_success(
            api_client.create_engagement(
                {
                    "undertaking_id": undertaking["id"],
                    "agent_name": "Real Agent LLC",
                    "effective_date": "2026-08-01",
                    "expiration_date": "2027-12-31",
                    "retainer_cents": 250000,
                    "expected_undertaking_version": undertaking["version"],
                },
                FD,
            ),
            201,
        )
        assert_dissemination_engagement(engagement)

        assert engagement["undertaking_id"] == undertaking["id"]
        assert engagement["status"] == "ACTIVE"
        assert engagement["last_calendar_ack_date"] is None
        # With no acknowledgement the baseline is effective_date 2026-08-01, the clock's own date.
        assert engagement["monitoring_lapse_days"] == 0
        assert engagement["billable_filing_count"] == 0
        # No confirmed filing, so the subtotal is the retainer alone and the annual floor binds.
        assert engagement["invoice_total_cents"] == 300000
        assert engagement["superseded_by_engagement_id"] is None
        assert engagement["termination_reason"] is None

        rows, meta = read_page(
            api_client.list_engagements(FD, params={"undertaking_id": undertaking["id"]})
        )
        assert meta["total_count"] == 1, "only the valid creation persisted"
        assert rows[0]["id"] == engagement["id"]

    def test_filing_creation_rejects_a_cycle_owned_by_a_different_bond_issue(self):
        """A filing whose issue_id is not the subject cycle's owner is refused as a subject mismatch.

        PRD §3.7: "The `issue_id` in the body must equal the subject's own owning issue."
        PRD §3.7: "Any breach of any part of this returns `ERR_FILING_SUBJECT_MISMATCH`."
        PRD §2.10: "Body foreign-key existence — every foreign-key field in the body resolves, in declared input order → the entity-specific not-found error (404). Applies to every create and update endpoint carrying a foreign key."
        PRD §3.7: "The draft opens at `status` `DRAFT`, `version` 1, `submission_attempt_count` 0, with `submitted_at`, `submitted_by_user_id`, `submitting_engagement_id`, `repository_receipt_id`, `repository_confirmed_at`, `rejection_reason`, and `superseded_by_filing_id` all null."
        Design: Corner/entities/filing_creation_rejects_a_cycle_owned_by_a_different_bond_issue
        """
        issue_a = create_bond_issue()
        issue_b = create_bond_issue(
            series_designation="2026B", original_par_amount_cents=25000000
        )
        undertaking_a = create_undertaking(issue_a["id"])
        create_undertaking(issue_b["id"])
        create_content_requirement(
            undertaking_a["id"],
            kind="OPERATING_DATA_TABLE",
            label="Operating Data Tables",
            weight_bp=10000,
        )
        cycle_a = create_cycle(
            undertaking_a["id"],
            fiscal_year_label="FY2026",
            period_start_date="2025-07-01",
            period_end_date="2026-06-30",
        )
        item_a = list_content_items(cycle_a["id"])[0]
        prepare_item(item_a["id"])
        attest_item(item_a["id"])
        assembled = assemble(cycle_a["id"])
        assert assembled["status"] == "READY_TO_FILE", "the subject really is fileable"

        version_b = read_bond_issue(issue_b["id"])["version"]
        version_a = read_bond_issue(issue_a["id"])["version"]

        # Issue B paired with issue A's cycle: both ids exist, the pairing does not.
        validate_error(
            api_client.create_filing(
                {
                    "issue_id": issue_b["id"],
                    "filing_type": "ANNUAL_REPORT",
                    "cycle_id": cycle_a["id"],
                    "expected_issue_version": version_b,
                },
                OFFICER,
            ),
            ApiErrorId.ERR_FILING_SUBJECT_MISMATCH.value,
            422,
        )

        # Two subject fields, one of them a non-existent notice: the FK rung fires first.
        validate_error(
            api_client.create_filing(
                {
                    "issue_id": issue_a["id"],
                    "filing_type": "ANNUAL_REPORT",
                    "cycle_id": cycle_a["id"],
                    "material_event_id": PROBE_UUID,
                    "expected_issue_version": version_a,
                },
                OFFICER,
            ),
            ApiErrorId.ERR_EVENT_NOTICE_NOT_FOUND.value,
            404,
        )

        filing = validate_success(
            api_client.create_filing(
                {
                    "issue_id": issue_a["id"],
                    "filing_type": "ANNUAL_REPORT",
                    "cycle_id": cycle_a["id"],
                    "expected_issue_version": version_a,
                },
                OFFICER,
            ),
            201,
        )
        assert_filing(filing)
        assert filing["status"] == "DRAFT"
        assert filing["issue_id"] == issue_a["id"]
        assert filing["cycle_id"] == cycle_a["id"]
        assert filing["submission_attempt_count"] == 0
        assert filing["version"] == 1


class TestOfficialStatementContract:
    """POST /disclosure/official-statements — drafting does not run the lookback."""

    def test_official_statement_creation_defaults_to_strict_five_year_and_unknown_adequacy(self):
        """A drafted statement takes STRICT_FIVE_YEAR, an empty disclosed set, and UNKNOWN adequacy.

        PRD §3.9: "A `DisclosureOfficer` drafts one against the new `issue_id`, naming its `dated_date` and optionally a `lookback_policy` (default `STRICT_FIVE_YEAR`) and an initial `disclosed_event_ids` array (default empty)."
        PRD §3.9: "The draft opens at `status` `DRAFT`, `version` 1, `disclosure_adequacy` `UNKNOWN`, `required_disclosure_event_ids` empty, and `required_disclosure_event_count` 0, with `reviewed_by_user_id`, `reviewed_at`, `posted_by_user_id`, and `posted_at` all null."
        PRD §3.9: "The lookback does not run at drafting; it runs first at compliance review."
        Design: Corner/entities/official_statement_creation_defaults_to_strict_five_year_and_unknown_adequacy
        """
        issue = create_bond_issue()

        statement = validate_success(
            api_client.create_official_statement(
                {"issue_id": issue["id"], "dated_date": "2027-03-01"}, OFFICER
            ),
            201,
        )
        assert_official_statement(statement)

        assert statement["lookback_policy"] == "STRICT_FIVE_YEAR"
        assert statement["disclosed_event_ids"] == []
        assert statement["required_disclosure_event_ids"] == []
        assert statement["required_disclosure_event_count"] == 0
        # UNKNOWN, not ADEQUATE: the lookback has not been run yet.
        assert statement["disclosure_adequacy"] == "UNKNOWN"
        assert statement["status"] == "DRAFT"
        assert statement["reviewed_by_user_id"] is None
        assert statement["reviewed_at"] is None
        assert statement["posted_by_user_id"] is None
        assert statement["posted_at"] is None
        assert statement["version"] == 1
        assert statement["issue_id"] == issue["id"]
        assert statement["dated_date"] == "2027-03-01"
