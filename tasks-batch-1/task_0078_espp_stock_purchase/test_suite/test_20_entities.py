"""Corner section: entities (PRD §2.3, §2.4, §3.1, §3.2).

Creation, retrieval, listing/pagination, not-found, required-field, defaults,
computed end_date, system fields, contribution immutability, and parent existence.
"""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    is_iso8601_timestamp,
    assert_participant,
    create_participant_payload,
    create_offering_payload,
    create_plan_payload,
    NON_EXISTENT_UUID,
    setup_enrolled_participant,
    contribute,
)


def test_create_participant_returns_201_with_fields(api, admin_headers):
    """PRD §3.1: "Registration captures the employee's email ... An optional
    is_five_percent_owner flag marks an employee who owns at least five percent of
    company stock; when omitted it defaults to false. Every participant carries a
    status that begins as ACTIVE".

    Design: Corner/entities/create_participant_returns_201_with_fields
    """
    resp = api.create_participant(create_participant_payload(), admin_headers)
    data = validate_success(resp, expected_status=201)
    assert_participant(data)
    assert data["status"] == "ACTIVE", data
    assert data["is_five_percent_owner"] is False, data


def test_get_participant_returns_stored_entity(api, admin_headers):
    """PRD §3.1: "Registration captures the employee's email, which serves as the login
    identity and must be unique and non-empty across participants".

    GET returns the same entity with the email that was stored.

    Design: Corner/entities/get_participant_returns_stored_entity
    """
    payload = create_participant_payload()
    created = get_success_data(api.create_participant(payload, admin_headers))
    fetched = validate_success(api.get_participant(created["id"], admin_headers))
    assert fetched["email"] == payload["email"], fetched


def test_list_offering_periods_paginated(api, admin_headers):
    """PRD §2.3: "The response meta object for a list carries the pagination fields
    limit, offset, total_count (the total number of records matching the filter before
    pagination), and has_more (a boolean that is true when records remain beyond the
    returned page)."

    Design: Corner/entities/list_offering_periods_paginated
    """
    plan = get_success_data(api.create_plan(create_plan_payload(), admin_headers))
    get_success_data(
        api.create_offering_period(create_offering_payload(plan["id"]), admin_headers)
    )
    data, meta = validate_paginated(
        api.list_offering_periods(plan["id"], admin_headers, params={"limit": 10, "offset": 0})
    )
    assert meta["total_count"] == 1, meta
    assert meta["has_more"] is False, meta


def test_get_participant_not_found(api, admin_headers):
    """PRD §2.7: "If any referenced resource in the path or body does not exist, the
    request is rejected with ERR_NOT_FOUND (HTTP 404)."

    Design: Corner/entities/get_participant_not_found
    """
    resp = api.get_participant(NON_EXISTENT_UUID, admin_headers)
    validate_error(resp, "ERR_NOT_FOUND")


def test_create_offering_missing_grant_fmv_returns_validation(api, admin_headers):
    """PRD §3.9: "when a request body is missing a required field, carries a field of
    the wrong type, or is otherwise malformed, the request is rejected with
    ERR_VALIDATION (HTTP 400)."
    PRD §3.2: "the grant_date_fmv_cents (the per-share fair market value in cents on
    the grant date, which must be greater than zero)".

    Omitting required grant_date_fmv_cents => ERR_VALIDATION (400).

    Design: Corner/entities/create_offering_missing_grant_fmv_returns_validation
    """
    plan = get_success_data(api.create_plan(create_plan_payload(), admin_headers))
    payload = create_offering_payload(plan["id"])
    payload.pop("grant_date_fmv_cents")
    resp = api.create_offering_period(payload, admin_headers)
    validate_error(resp, "ERR_VALIDATION")


def test_plan_defaults_applied_when_omitted(api, admin_headers):
    """PRD §3.1: "A Plan carries the issuer's company_name, a max_contribution_rate_pct
    capping the per-paycheck withholding rate (defaulting to 15 ...), a discount_pct
    giving the purchase discount off the applicable fair market value (defaulting to
    15 ...), a lookback_enabled flag (defaulting to true) ... and an
    annual_purchase_limit_usd (defaulting to 25000 ...)."

    Design: Corner/entities/plan_defaults_applied_when_omitted
    """
    plan = validate_success(
        api.create_plan(create_plan_payload(), admin_headers), expected_status=201
    )
    assert plan["max_contribution_rate_pct"] == 15, plan
    assert plan["discount_pct"] == 15, plan
    assert plan["annual_purchase_limit_usd"] == 25000, plan
    assert plan["lookback_enabled"] is True, plan


def test_offering_end_date_computed_from_duration(api, admin_headers):
    """PRD §3.2: "The system computes end_date by adding duration_months calendar
    months to grant_date; the offering closes at that point."

    grant 2024-01-01 + 12 months => end_date 2025-01-01.

    Design: Corner/entities/offering_end_date_computed_from_duration
    """
    plan = get_success_data(api.create_plan(create_plan_payload(), admin_headers))
    off = validate_success(
        api.create_offering_period(
            create_offering_payload(
                plan["id"], grant_date="2024-01-01T00:00:00.000Z", duration_months=12,
            ),
            admin_headers,
        ),
        expected_status=201,
    )
    assert off["end_date"].startswith("2025-01-01"), off


def test_participant_system_fields_generated(api, admin_headers):
    """PRD §2.4: "Every resource carries a server-minted id — a UUID with no type
    prefix — and a created_at timestamp expressed in ISO 8601 UTC with three
    fractional-second digits ... an integer version that begins at 1 and increments by
    one on every mutation."
    PRD §3.1: "Every participant carries a status that begins as ACTIVE".

    Design: Corner/entities/participant_system_fields_generated
    """
    created = validate_success(
        api.create_participant(create_participant_payload(), admin_headers),
        expected_status=201,
    )
    assert created["version"] == 1, created
    assert is_iso8601_timestamp(created["created_at"]), created


def test_contribution_immutable_no_version_field(api, admin_headers):
    """PRD §2.4: "The one exception is the Contribution resource, which carries only id
    and created_at; it has neither an updated_at nor a version field, because a
    contribution is an immutable ledger line".
    PRD §3.3: "The system computes the withheld amount_cents by multiplying
    gross_pay_cents by the enrollment's contribution_rate_pct, dividing by 100, and
    taking the floor of the result."

    gross 500000 at 10% => amount_cents 50000; the read carries no version field.

    Design: Corner/entities/contribution_immutable_no_version_field
    """
    _, _, _, enrollment = setup_enrolled_participant(rate_pct=10)
    contribution = contribute(enrollment["id"], gross_pay_cents=500000)
    assert contribution["amount_cents"] == 50000, contribution
    assert "version" not in contribution, contribution


def test_offering_requires_existing_plan_parent(api, admin_headers):
    """PRD §2.7: "The same left-to-right existence rule governs body-referenced foreign
    keys on creation."
    PRD §2.7: "If any referenced resource in the path or body does not exist, the
    request is rejected with ERR_NOT_FOUND (HTTP 404)."

    Creating an offering with a non-existent plan_id => ERR_NOT_FOUND.

    Design: Corner/entities/offering_requires_existing_plan_parent
    """
    resp = api.create_offering_period(
        create_offering_payload(NON_EXISTENT_UUID), admin_headers
    )
    validate_error(resp, "ERR_NOT_FOUND")
