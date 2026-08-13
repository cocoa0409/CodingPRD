"""Application intake: creation defaults, not-found paths, listing filters,
and the savings claim's append-only shape."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    add_line_item,
    assert_application,
    assert_savings_claim,
    attach_savings_claim,
    build_submitted_application,
    create_active_ally,
    create_draft_application,
    create_open_program,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestApplicationCreation:
    def test_creation_assigns_draft_and_zero_totals(self, api, admin_headers):
        """PRD §3.3: "The new application starts in `DRAFT` with
        `incentive_total_cents`, `claimed_kwh`, `final_kwh`, and `risk_score` at
        zero, `inspection_required` false, `auto_flag_status` `CLEAR`, and
        `version` 1."

        Design: Corner/entities/application_creation_assigns_draft_and_zero_totals
        """
        py, _measures = create_open_program()
        ally = create_active_ally()
        app = create_draft_application(py, ally)
        assert_application(app)
        assert app["status"] == "DRAFT"
        assert app["incentive_total_cents"] == 0
        assert app["claimed_kwh"] == 0
        assert app["final_kwh"] == 0
        assert app["inspection_required"] is False
        assert app["risk_score"] == 0
        assert app["auto_flag_status"] == "CLEAR"
        assert app["version"] == 1

    def test_application_not_found_returns_404(self, api, admin_headers):
        """PRD §2.9: "Third, every identifier in the request path must resolve
        to an existing resource of the appropriate type, yielding the
        resource-specific not-found error: `ERR_PROGRAM_YEAR_NOT_FOUND`,
        `ERR_APPLICATION_NOT_FOUND`, `ERR_ALLY_NOT_FOUND`, `ERR_MEASURE_NOT_FOUND`"
        PRD §2.9: "(all HTTP 404)"

        Design: Corner/entities/application_not_found_returns_404
        """
        res = api.get_application(NON_EXISTENT_UUID, admin_headers)
        validate_error(res, ApiErrorId.ERR_APPLICATION_NOT_FOUND, expected_status=404)

    def test_line_item_not_found_returns_404(self, api, admin_headers):
        """PRD §2.9: "`ERR_INSPECTION_NOT_FOUND`, `ERR_LINE_ITEM_NOT_FOUND`,
        `ERR_SAVINGS_CLAIM_NOT_FOUND`, or `ERR_ADJUSTMENT_NOT_FOUND` (all HTTP
        404)."

        Design: Corner/entities/line_item_not_found_returns_404
        """
        res = api.get_line_item(NON_EXISTENT_UUID, admin_headers)
        validate_error(res, ApiErrorId.ERR_LINE_ITEM_NOT_FOUND, expected_status=404)

    def test_savings_claim_not_found_returns_404(self, api, admin_headers):
        """PRD §2.9: "`ERR_INSPECTION_NOT_FOUND`, `ERR_LINE_ITEM_NOT_FOUND`,
        `ERR_SAVINGS_CLAIM_NOT_FOUND`, or `ERR_ADJUSTMENT_NOT_FOUND` (all HTTP
        404)."

        Design: Corner/entities/savings_claim_not_found_returns_404
        """
        res = api.get_savings_claim(NON_EXISTENT_UUID, admin_headers)
        validate_error(res, ApiErrorId.ERR_SAVINGS_CLAIM_NOT_FOUND, expected_status=404)


class TestApplicationListing:
    def test_list_with_filters(self, api, admin_headers):
        """PRD §3.3: "Application listings accept `program_year_id`,
        `trade_ally_id`, `status`, and `auto_flag_status` filters."

        Design: Corner/endpoints/get_applications_list_with_filters
        """
        py, measures = create_open_program()
        ally = create_active_ally()
        app1, _ = build_submitted_application(py, ally, measures[0])
        app2, _ = build_submitted_application(py, ally, measures[0])

        data, meta = validate_paginated(
            api.list_applications(
                admin_headers,
                params={"status": "SUBMITTED", "trade_ally_id": ally["id"]},
            )
        )
        assert meta["total_count"] == 2
        assert len(data) == 2
        for item in data:
            assert_application(item)
            assert item["status"] == "SUBMITTED"
            assert item["trade_ally_id"] == ally["id"]
        returned_ids = {item["id"] for item in data}
        assert returned_ids == {app1["id"], app2["id"]}


class TestSavingsClaimShape:
    def test_savings_claim_immutable_shape(self, api, admin_headers):
        """PRD §2.5: "A savings claim and a fraud flag each carry only `id` and
        `created_at`; `updated_at` and `version` are absent from both, and fraud
        flags are immutable once persisted."

        Design: Corner/entities/savings_claim_immutable_after_creation
        """
        py, measures = create_open_program()
        ally = create_active_ally()
        app = create_draft_application(py, ally)
        line = add_line_item(app, measures[0], quantity=1, ally=ally)

        claim = attach_savings_claim(line, ally, "DEEMED")
        assert_savings_claim(claim)
        assert "id" in claim and "created_at" in claim
        assert "version" not in claim
        assert "updated_at" not in claim

        fetched = validate_success(api.get_savings_claim(claim["id"], admin_headers), 200)
        assert_savings_claim(fetched)
        assert "version" not in fetched
        assert "updated_at" not in fetched
