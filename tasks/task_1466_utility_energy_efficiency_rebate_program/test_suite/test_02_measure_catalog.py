"""Measure catalog: creation defaults, not-found, uniqueness, and the
inactive-measure submission gate."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    add_line_item,
    add_measure,
    assert_measure,
    create_active_ally,
    create_draft_application,
    create_measure_payload,
    create_open_program,
    create_program_year,
    make_trade_ally_headers,
    validate_error,
    validate_success,
)


class TestMeasureCatalog:
    def test_measure_creation_returns_defaults(self, api, admin_headers):
        """PRD §3.1: "A measure flagged `requires_post_inspection` (default
        `false`) marks installations that are expected to undergo a
        post-installation inspection before verification; `is_active` (default
        `true`) controls whether the measure may appear on new applications."

        Design: Corner/entities/measure_creation_returns_defaults
        """
        py = create_program_year()
        res = api.create_measure(
            create_measure_payload(
                py["id"], measure_code="M1", measure_name="Measure 1",
                base_rate_cents=5_000, deemed_kwh_per_unit=200,
            ),
            admin_headers,
        )
        measure = validate_success(res, 201)
        assert_measure(measure)
        assert measure["is_active"] is True
        assert measure["requires_post_inspection"] is False

    def test_measure_not_found_returns_404(self, api, admin_headers):
        """PRD §2.9: "Third, every identifier in the request path must resolve
        to an existing resource of the appropriate type, yielding the
        resource-specific not-found error: `ERR_PROGRAM_YEAR_NOT_FOUND`,
        `ERR_APPLICATION_NOT_FOUND`, `ERR_ALLY_NOT_FOUND`, `ERR_MEASURE_NOT_FOUND`"
        PRD §2.9: "(all HTTP 404)"

        Design: Corner/entities/measure_not_found_returns_404
        """
        res = api.get_measure(NON_EXISTENT_UUID, admin_headers)
        validate_error(res, ApiErrorId.ERR_MEASURE_NOT_FOUND, expected_status=404)

    def test_measure_duplicate_code_within_program_year_returns_error(
        self, api, admin_headers
    ):
        """PRD §3.1: "Reusing a `measure_code` within the same program year is
        again `ERR_DUPLICATE_UNIQUE_FIELD`."

        Design: Corner/validations/measure_duplicate_code_within_program_year_returns_error
        """
        py = create_program_year()
        add_measure(py["id"], measure_code="M1")
        res = api.create_measure(
            create_measure_payload(py["id"], measure_code="M1"), admin_headers
        )
        validate_error(res, ApiErrorId.ERR_DUPLICATE_UNIQUE_FIELD, expected_status=409)

    def test_measure_inactive_blocks_submit(self, api, admin_headers):
        """PRD §3.4: "catalog currency, requiring every line item's measure to
        be active (`ERR_MEASURE_INACTIVE`, HTTP 409)"

        Design: Corner/validations/measure_inactive_blocks_submit
        """
        py = create_program_year()
        add_measure(py["id"], measure_code="M-ACTIVE")
        inactive = add_measure(py["id"], measure_code="M-INACTIVE", is_active=False)
        py = validate_success(api.open_program_year(py["id"], admin_headers), 200)

        ally = create_active_ally()
        app = create_draft_application(py, ally)
        add_line_item(app, inactive, quantity=1, ally=ally)

        res = api.submit_application(app["id"], make_trade_ally_headers(ally["id"]))
        validate_error(res, ApiErrorId.ERR_MEASURE_INACTIVE, expected_status=409)
