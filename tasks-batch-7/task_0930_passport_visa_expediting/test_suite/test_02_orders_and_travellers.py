"""Opening orders, enrolling travellers and the derived requirement set."""

import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_applicant,
    assert_custody_event,
    assert_order,
    build_scenario,
    list_custody_events,
    new_applicant,
    new_catalog_item,
    new_document_requirement,
    new_order,
    read_applicant,
    read_order,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import ADMIN, CASE_MANAGER


def test_open_order_returns_the_declared_defaults(api):
    """PRD §3.4: "A newly opened order starts in `workflow_status` `DRAFT`,
    `payment_status` `UNPAID`, `custody_holder` `APPLICANT`, `feasibility_status`
    `UNKNOWN` and `furthest_stage_reached` `DRAFT`, with `applicant_count`, every money
    roll-up field and `rfe_round_count` at 0, `discount_pct_applied` at 0,
    `handling_fee_waived` false, and `parent_order_id`, `quoted_by_user_id`,
    `submitted_by_user_id`, `acknowledged_by_user_id`, `quoted_at`, `submitted_at`,
    `tendered_at`, `decided_at`, `effective_submission_date` and
    `projected_completion_date` all null."
    PRD §3.4: "`return_date` must be on or after `travel_date`. `service_level` is optional
    and defaults to `STANDARD`."
    PRD §2.4: "`version` is an integer that is **1 on creation** and increases by exactly 1
    each time a request mutates the row; `updated_at` is set to the logical clock at the
    same moment and equals `created_at` until the first mutation."

    Design: Corner/entities/corner_create_order_returns_declared_fields_with_declared_defaults
    """
    set_clock()
    catalog = new_catalog_item()

    order = validate_success(
        api.create_order(
            {
                "catalog_item_id": catalog["id"],
                "travel_date": "2026-09-01",
                "return_date": "2026-09-20",
                "delivery_region_code": "CA",
            },
            CASE_MANAGER,
        ),
        expected_status=201,
    )
    assert_order(order)
    assert order["workflow_status"] == "DRAFT"
    assert order["payment_status"] == "UNPAID"
    assert order["custody_holder"] == "APPLICANT"
    assert order["feasibility_status"] == "UNKNOWN"
    assert order["furthest_stage_reached"] == "DRAFT"
    assert order["service_level"] == "STANDARD", "service_level defaults to STANDARD"
    assert order["version"] == 1
    assert order["applicant_count"] == 0
    assert order["total_quoted_cents"] == 0

    events = list_custody_events(order["id"])
    assert len(events) == 1, f"order creation opens the chain of custody, got {len(events)} rows"
    assert_custody_event(events[0])
    assert events[0]["holder_type"] == "APPLICANT"
    assert events[0]["released_at"] is None
    assert events[0]["reason"] == "ORDER_CREATED"


def test_client_supplied_system_fields_are_ignored_on_order_creation(api):
    """PRD §2.4: "Every stored row carries an `id` that is a server-minted UUID string.
    Identifiers never carry a type prefix and are never supplied by the client."
    PRD §3.4: "A newly opened order starts in `workflow_status` `DRAFT`, `payment_status`
    `UNPAID`, `custody_holder` `APPLICANT`, `feasibility_status` `UNKNOWN` and
    `furthest_stage_reached` `DRAFT`, with `applicant_count`, every money roll-up field
    and `rfe_round_count` at 0, `discount_pct_applied` at 0, `handling_fee_waived` false,
    and `parent_order_id`, `quoted_by_user_id`, `submitted_by_user_id`,
    `acknowledged_by_user_id`, `quoted_at`, `submitted_at`, `tendered_at`, `decided_at`,
    `effective_submission_date` and `projected_completion_date` all null."

    Design: Corner/entities/corner_order_system_fields_input_ignored
    """
    set_clock()
    catalog = new_catalog_item()
    planted_id = "11111111-1111-4111-8111-111111111111"

    order = validate_success(
        api.create_order(
            {
                "catalog_item_id": catalog["id"],
                "travel_date": "2026-09-01",
                "return_date": "2026-09-20",
                "delivery_region_code": "CA",
                "id": planted_id,
                "version": 99,
                "workflow_status": "AT_AGENCY",
                "collected_cents": 500000,
            },
            CASE_MANAGER,
        ),
        expected_status=201,
    )
    assert order["id"] != planted_id, "the server mints its own identifier"
    assert order["version"] == 1
    assert order["workflow_status"] == "DRAFT"
    assert order["collected_cents"] == 0


def test_applicant_age_is_pinned_against_the_travel_date(api):
    """PRD §3.4: "`age_years` is the number of whole years from `date_of_birth` to the
    order's `travel_date` as `travel_date` stands at that instant, floored — the birthday
    must have fallen on or before the travel date in that year for the year to count."
    PRD §3.4: "Third, it moves the order's `applicant_count`, which counts travellers whose
    `readiness_status` is `PENDING` or `COMPLETE`."

    Design: Corner/entities/corner_applicant_age_years_computed_against_travel_date
    """
    set_clock()
    catalog = new_catalog_item()
    order = new_order(catalog["id"], travel_date="2026-09-01", return_date="2026-09-20")

    day_after = validate_success(
        api.create_applicant(
            order["id"],
            {
                "full_name": "Minor Edge",
                "date_of_birth": "2010-09-02",
                "nationality_code": "US",
                "residence_region_code": "CA",
            },
            CASE_MANAGER,
        ),
        expected_status=201,
    )
    on_the_day = validate_success(
        api.create_applicant(
            order["id"],
            {
                "full_name": "Adult Edge",
                "date_of_birth": "2010-09-01",
                "nationality_code": "US",
                "residence_region_code": "CA",
            },
            CASE_MANAGER,
        ),
        expected_status=201,
    )

    assert_applicant(day_after)
    assert day_after["age_years"] == 15, (
        "a birthday one day after the travel date does not count the year, "
        f"got {day_after['age_years']}"
    )
    assert on_the_day["age_years"] == 16, (
        f"a birthday on the travel date counts, got {on_the_day['age_years']}"
    )
    assert day_after["readiness_status"] == "PENDING"
    assert read_order(order["id"])["applicant_count"] == 2


def test_order_list_reports_the_pagination_envelope(api):
    """PRD §2.3: "Every list endpoint accepts `limit` and `offset` as query parameters.
    `limit` defaults to 10, has a minimum of 1 and a maximum of 100."
    PRD §2.3: "List responses populate `limit`, `offset`, `total_count` and `has_more` in
    `meta`; `total_count` is the number of rows matching the filters before pagination is
    applied, and `has_more` is true exactly when the sum of `offset` and the number of rows
    returned is strictly less than `total_count`."

    Design: Corner/entities/corner_list_orders_pagination_envelope
    """
    set_clock()
    catalog = new_catalog_item()
    for travel, ret in (
        ("2026-09-01", "2026-09-20"),
        ("2026-09-02", "2026-09-21"),
        ("2026-09-03", "2026-09-22"),
    ):
        new_order(catalog["id"], travel_date=travel, return_date=ret)

    resp = api.list_orders(ADMIN, {"limit": 2, "offset": 0})
    rows, meta = validate_paginated(resp)
    assert len(rows) == 2, f"limit 2 returns 2 rows, got {len(rows)}"
    assert meta["total_count"] == 3, f"total_count counts every matching row, got {meta['total_count']}"
    assert meta["has_more"] is True, "0 + 2 is strictly less than 3, so has_more is true"
    assert resp.json()["response_type"] == "array"


def test_unknown_order_id_is_the_order_specific_not_found(api):
    """PRD §2.4: "On any path rooted at an order, the order identifier is resolved first;
    a miss there is `ERR_ORDER_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/corner_get_order_with_unknown_id_not_found
    """
    set_clock()
    resp = api.get_order("00000000-0000-4000-8000-000000000000", CASE_MANAGER)
    validate_error(resp, ApiErrorId.ERR_ORDER_NOT_FOUND.value)
    assert resp.json()["response_type"] == "error"


def test_return_date_before_travel_date_is_a_validation_failure(api):
    """PRD §3.4: "A missing or malformed field on this payload is refused with
    `ERR_VALIDATION`, including a `return_date` that precedes `travel_date`."

    Design: Corner/validations/corner_return_date_before_travel_date_returns_validation
    """
    set_clock()
    catalog = new_catalog_item()

    resp = api.create_order(
        {
            "catalog_item_id": catalog["id"],
            "travel_date": "2026-09-01",
            "return_date": "2026-08-01",
            "delivery_region_code": "CA",
        },
        CASE_MANAGER,
    )
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)

    _rows, meta = validate_paginated(api.list_orders(ADMIN))
    assert meta["total_count"] == 0, "a refused creation writes no Order row"


def test_off_enum_service_level_routes_to_invalid_enum(api):
    """PRD §2.9.1: "- `service_level` on order creation and on a service-level change —
    `STANDARD`, `EXPEDITED`, `RUSH`."
    PRD §2.9.1: "**No other field routes to `ERR_INVALID_ENUM`.** Every other malformed
    value — of any type, on any endpoint — routes to `ERR_VALIDATION` at rung 6."

    Design: Corner/validations/corner_invalid_service_level_enum_rejected
    """
    set_clock()
    catalog = new_catalog_item()

    resp = api.create_order(
        {
            "catalog_item_id": catalog["id"],
            "travel_date": "2026-09-01",
            "return_date": "2026-09-20",
            "delivery_region_code": "CA",
            "service_level": "PRIORITY",
        },
        CASE_MANAGER,
    )
    error = validate_error(resp, ApiErrorId.ERR_INVALID_ENUM.value)
    assert error["error_id"] != ApiErrorId.ERR_VALIDATION.value


def test_applicant_nationality_must_match_the_catalog_item(api):
    """PRD §3.4: "The citizenship check is strict and is its own failure: an applicant
    whose `nationality_code` differs from the `nationality_code` on the order's catalog
    item is refused with `ERR_NATIONALITY_MISMATCH`."

    Design: Corner/validations/corner_nationality_mismatch_rejected_on_applicant_create
    """
    set_clock()
    catalog = new_catalog_item(nationality_code="US")
    order = new_order(catalog["id"])

    resp = api.create_applicant(
        order["id"],
        {
            "full_name": "Wrong Nationality",
            "date_of_birth": "1990-03-04",
            "nationality_code": "CA",
            "residence_region_code": "CA",
        },
        CASE_MANAGER,
    )
    validate_error(resp, ApiErrorId.ERR_NATIONALITY_MISMATCH.value)

    assert read_order(order["id"])["applicant_count"] == 0
    _rows, meta = validate_paginated(api.list_order_applicants(order["id"], CASE_MANAGER))
    assert meta["total_count"] == 0, "a refused enrolment writes no Applicant row"


def test_required_document_read_applies_the_age_gate(api):
    """PRD §3.4: "Starting from the requirement lines of the order's catalog item, a line
    applies to this traveller when its `applies_max_age_years` is null, or when the
    traveller's `age_years` is strictly less than that number."
    PRD §3.4: "One document slot is created for each applying line, in `review_status`
    `MISSING`, copying `doc_type`, `is_required`, `validity_rule` and `validity_param` from
    the line — optional lines produce slots too."

    Design: Corner/endpoints/corner_required_documents_read_applies_the_age_gate
    """
    set_clock()
    catalog = new_catalog_item()
    new_document_requirement(
        catalog["id"],
        doc_type="PASSPORT_BOOK",
        is_required=True,
        validity_rule="VALID_BEYOND_RETURN_MONTHS",
        validity_param=6,
    )
    new_document_requirement(
        catalog["id"],
        doc_type="PARENTAL_CONSENT",
        is_required=True,
        validity_rule="NONE",
        validity_param=None,
        applies_max_age_years=16,
    )
    order = new_order(catalog["id"], travel_date="2026-09-01", return_date="2026-09-20")
    minor = new_applicant(order["id"], full_name="Young One", date_of_birth="2010-09-02")
    adult = new_applicant(order["id"], full_name="Older One", date_of_birth="1990-03-04")

    minor_read = validate_success(api.get_required_documents(minor["id"], CASE_MANAGER))
    adult_read = validate_success(api.get_required_documents(adult["id"], CASE_MANAGER))

    assert minor_read["required_doc_count"] == 2, (
        f"a 15-year-old picks up the PARENTAL_CONSENT line, got {minor_read['required_doc_count']}"
    )
    assert adult_read["required_doc_count"] == 1, (
        f"a 36-year-old does not, got {adult_read['required_doc_count']}"
    )

    minor_slots, minor_meta = validate_paginated(
        api.list_applicant_documents(minor["id"], CASE_MANAGER)
    )
    adult_slots, adult_meta = validate_paginated(
        api.list_applicant_documents(adult["id"], CASE_MANAGER)
    )
    assert minor_meta["total_count"] == 2
    assert adult_meta["total_count"] == 1
    assert all(s["review_status"] == "MISSING" for s in minor_slots + adult_slots)


def test_accept_quote_from_draft_is_an_invalid_state(api):
    """PRD §2.9.2: "- **Accept quote:** `workflow_status` is `QUOTED`, `payment_status` is
    `COLLECTED`, and `total_quoted_cents` is strictly greater than 0."
    PRD §3.6: "An acceptance attempted while money is still owed is refused as an invalid
    state with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/corner_accept_quote_from_draft_returns_invalid_state
    """
    set_clock()
    catalog = new_catalog_item()
    order = new_order(catalog["id"])
    new_applicant(order["id"], full_name="Draft Only")

    resp = api.accept_quote(order["id"], CASE_MANAGER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    stored = read_order(order["id"])
    assert stored["workflow_status"] == "DRAFT"
    assert stored["payment_status"] == "UNPAID"


def test_cancelled_order_refuses_every_further_mutation(api):
    """PRD §2.9: "| 9 | `ERR_ORDER_TERMINAL` | 409 | The targeted order's
    `workflow_status` is not one of `COMPLETED`, `CANCELLED`, `ABANDONED`. Applies to every
    mutating endpoint touching an order or any of its descendants. |"
    PRD §3.12: "Every cancellation runs refund adjudication in the variant selected by
    `government_tendered_cents`, and sets every traveller of the order to
    `readiness_status` `WITHDRAWN`, which in turn moves each of their `BOOKED`
    appointments to `CANCELLED` and releases the corresponding slot capacity"

    Design: Corner/state_machines/corner_cancelled_order_rejects_further_mutation
    """
    set_clock()
    catalog = new_catalog_item()
    order = new_order(catalog["id"])
    applicant = new_applicant(order["id"], full_name="Gone Soon")
    validate_success(api.cancel_order(order["id"], CASE_MANAGER))

    resp = api.quote_order(order["id"], {}, CASE_MANAGER)
    validate_error(resp, ApiErrorId.ERR_ORDER_TERMINAL.value)

    stored = read_order(order["id"])
    assert stored["workflow_status"] == "CANCELLED"
    assert stored["total_quoted_cents"] == 0, "the refused quote priced nothing"
    assert read_applicant(applicant["id"])["readiness_status"] == "WITHDRAWN"
