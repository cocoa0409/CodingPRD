"""Catalog creation, lead/appointment CRUD, listing, and pagination.

Corner-design breadth over entity creation, system-managed fields, existence
and validation errors, list pagination, and simple appointment state rules.
"""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    assert_product,
    create_appointment,
    create_lead,
    create_lead_payload,
    create_product_payload,
    create_quote_payload,
    create_sales_rep,
    create_crew,
    complete_appointment,
    get_lead_version,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_product_creation_returns_201_and_echoes_fields(api, admin_headers):
    """PRD §3.1: "It carries a `name`, a `category` that is one of `GUTTER`,
    `LEAF_GUARD`, or `DOWNSPOUT`, and a `base_rate_cents_per_foot` giving the
    base install price per linear foot in whole cents."
    PRD §2.4: "`id` — a server-minted UUID with no type prefix, unique across
    all resources. Clients never supply it."

    Design: Corner/entities/product_creation_returns_201_and_echoes_fields
    """
    resp = api.create_product(
        create_product_payload(
            name="MicroMesh", category="LEAF_GUARD", base_rate_cents_per_foot=3000,
            available_colors=["WHITE", "COPPER"], premium_colors=["COPPER"],
            color_surcharge_cents_per_foot=500,
        ),
        admin_headers,
    )
    data = validate_success(resp, expected_status=201)
    assert data["base_rate_cents_per_foot"] == 3000
    assert data["category"] == "LEAF_GUARD"
    assert is_valid_uuid(data["id"]), "id must be a server-minted UUID"
    assert_product(data)


def test_product_category_bad_enum_returns_400(api, admin_headers):
    """PRD §2.6: "A malformed request body — missing a required field, or
    carrying a value of the wrong type or an unrecognized enum member — is
    rejected up front with `ERR_VALIDATION` (HTTP 400)."

    Design: Corner/entities/product_category_bad_enum_returns_400
    """
    resp = api.create_product(
        create_product_payload(
            name="X", category="SIDING", base_rate_cents_per_foot=3000,
            available_colors=["WHITE"], premium_colors=[],
        ),
        admin_headers,
    )
    validate_error(resp, ApiErrorId.ERR_VALIDATION)


def test_lead_system_fields_generated_status_new(api, admin_headers):
    """PRD §3.2: "A new lead begins with `status` of `NEW`, `no_show_strikes` of
    0, and `credit_balance_cents` of 0."

    Design: Corner/entities/lead_system_fields_generated_status_new
    """
    rep = create_sales_rep()
    resp = api.create_lead(
        create_lead_payload(rep["id"], full_name="HO", address="1 St", phone="555-0001"),
        admin_headers,
    )
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "NEW"
    assert data["no_show_strikes"] == 0
    assert data["credit_balance_cents"] == 0


def test_lead_initial_state_is_new(api, admin_headers):
    """PRD §3.2: "A new lead begins with `status` of `NEW`, `no_show_strikes` of
    0, and `credit_balance_cents` of 0."

    Design: Corner/state_machines/lead_initial_state_is_new
    """
    rep = create_sales_rep()
    lead = create_lead(rep["id"], full_name="HO", address="5 St", phone="555-0005")
    data = validate_success(api.get_lead(lead["id"], admin_headers))
    assert data["status"] == "NEW"


def test_quote_missing_required_color_returns_validation(api, admin_headers):
    """PRD §2.6: "A malformed request body — missing a required field, or
    carrying a value of the wrong type or an unrecognized enum member — is
    rejected up front with `ERR_VALIDATION` (HTTP 400)."

    Design: Corner/entities/quote_missing_required_color_returns_validation
    """
    rep = create_sales_rep()
    product = validate_success(
        api.create_product(create_product_payload(), admin_headers), expected_status=201
    )
    lead = create_lead(rep["id"], full_name="HO", address="3 St", phone="555-0003")
    appt = create_appointment(lead["id"], rep["id"])
    lv = get_lead_version(lead["id"])
    # Deliberately omit the required `color` field.
    payload = {
        "lead_id": lead["id"], "appointment_id": appt["id"], "sales_rep_id": rep["id"],
        "product_id": product["id"], "estimated_linear_feet": 100,
        "expected_lead_version": lv,
    }
    validate_error(api.create_quote(payload, admin_headers), ApiErrorId.ERR_VALIDATION)


def test_quote_appointment_fk_not_found_returns_404(api, admin_headers):
    """PRD §2.6: "Every referenced resource must exist. The resource named in the
    URL path is checked first, then the foreign-key fields carried in the body,
    evaluated left to right in the order they are listed. The first missing
    reference produces the corresponding not-found error (for example
    `ERR_LEAD_NOT_FOUND`, `ERR_APPOINTMENT_NOT_FOUND`, `ERR_PRODUCT_NOT_FOUND`,
    and so on), each HTTP 404."

    Design: Corner/entities/quote_appointment_fk_not_found_returns_404
    """
    rep = create_sales_rep()
    product = validate_success(
        api.create_product(create_product_payload(), admin_headers), expected_status=201
    )
    lead = create_lead(rep["id"], full_name="HO", address="4 St", phone="555-0004")
    lv = get_lead_version(lead["id"])
    payload = create_quote_payload(
        lead["id"], NON_EXISTENT_UUID, rep["id"], product["id"], "WHITE", 100, lv,
    )
    validate_error(api.create_quote(payload, admin_headers), ApiErrorId.ERR_APPOINTMENT_NOT_FOUND)


def test_crew_fk_reverse_reachable_jobs_by_crew(api, admin_headers):
    """PRD §3.7: "Jobs may be listed with optional filters on `quote_id`,
    `lead_id`, `crew_id`, and `status`, and a missing job reference yields
    `ERR_JOB_NOT_FOUND`."

    Design: Corner/entities/crew_fk_reverse_reachable_jobs_by_crew
    """
    crew = create_crew()
    resp = api.list_jobs(admin_headers, params={"crew_id": crew["id"]})
    data, meta = validate_paginated(resp)
    assert data == [], "a crew with no jobs must reverse-resolve to an empty list"
    assert meta["total_count"] == 0


def test_get_crew_returns_computed_booked_days(api, admin_headers):
    """PRD §3.1: "A crew also exposes a computed `booked_days`, which is
    initialized to 0 at creation and thereafter reflects the crew's reserved
    install days as defined in Section 2.8."

    Design: Corner/endpoints/get_crew_returns_computed_booked_days
    """
    crew = create_crew()
    data = validate_success(api.get_crew(crew["id"], admin_headers))
    assert data["booked_days"] == 0


def test_leads_list_pagination_and_total_count(api, admin_headers):
    """PRD §2.3: "Each list response echoes `limit`, `offset`, `total_count`, and
    `has_more` inside the `meta` object of the envelope, where `total_count` is
    the number of records matching the query before paging and `has_more`
    indicates whether records remain beyond the current page."

    Design: Corner/endpoints/leads_list_pagination_and_total_count
    """
    rep = create_sales_rep()
    for name in ("HO A", "HO B", "HO C"):
        create_lead(rep["id"], full_name=name, address="a", phone="555-1")
    resp = api.list_leads(admin_headers, params={"sales_rep_id": rep["id"], "limit": 2, "offset": 0})
    data, meta = validate_paginated(resp)
    assert len(data) == 2
    assert meta["total_count"] == 3
    assert meta["has_more"] is True
    assert meta["limit"] == 2
    assert meta["offset"] == 0


def test_pagination_limit_zero_returns_error(api, admin_headers):
    """PRD §2.3: "A `limit` outside the inclusive range of 1 through 100, or a
    negative `offset`, is rejected with `ERR_PAGINATION_INVALID`."

    Design: Corner/validations/pagination_limit_zero_returns_error
    """
    validate_error(
        api.list_leads(admin_headers, params={"limit": 0}), ApiErrorId.ERR_PAGINATION_INVALID
    )


def test_cancel_appointment_from_completed_is_invalid_state(api, admin_headers):
    """PRD §3.3: "`COMPLETED`, `CANCELED`, and `NO_SHOW` are terminal appointment
    states."
    PRD §2.6: "`ERR_INVALID_STATE` for a plain illegal transition"

    Design: Corner/state_machines/cancel_appointment_from_completed_is_invalid_state
    """
    rep = create_sales_rep()
    lead = create_lead(rep["id"], full_name="HO", address="6 St", phone="555-0006")
    appt = create_appointment(lead["id"], rep["id"])
    complete_appointment(appt["id"], 150)
    resp = api.transition_appointment(appt["id"], {"to_status": "CANCELED"}, admin_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    still = validate_success(api.get_appointment(appt["id"], admin_headers))
    assert still["status"] == "COMPLETED"


def test_appointment_measured_zero_returns_invalid_measurement(api, admin_headers):
    """PRD §3.3: "Completing an appointment requires the surveyor's
    `measured_linear_feet` — the actual measured gutter run — to be supplied and
    to be greater than 0; a missing or non-positive measurement is rejected with
    `ERR_INVALID_MEASUREMENT`, and on success the measurement is persisted on the
    appointment."

    Design: Corner/validations/appointment_measured_zero_returns_invalid_measurement
    """
    rep = create_sales_rep()
    lead = create_lead(rep["id"], full_name="HO", address="17 St", phone="555-0017")
    appt = create_appointment(lead["id"], rep["id"])
    api.transition_appointment(appt["id"], {"to_status": "CONFIRMED"}, admin_headers)
    resp = api.transition_appointment(
        appt["id"], {"to_status": "COMPLETED", "measured_linear_feet": 0}, admin_headers
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_MEASUREMENT)
