"""Registry and configuration: facilities, clinicians, credentials, listings,
and the entity-level creation / validation / not-found claims.

Every test translates exactly one Corner-design instance from the `entities`
section.
"""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    TEST_USERS,
    make_scheduler_headers,
    make_clinician_headers,
    fixtures as fx,
)

ADMIN = TEST_USERS["platform_admin_headers"]
OFFICER = TEST_USERS["compliance_officer_headers"]


def test_create_facility_initialises_money_counters_to_zero(api):
    """PRD 3.1: "On registration the three money counters `pending_pay_cents`,
    `outstanding_balance_cents`, and `lifetime_billed_cents` all start at 0."

    Design: Corner/entities/create_facility_returns_201_with_initialised_money_counters
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    resp = api.create_facility(
        {"name": "Alder Bay", "unit_name": "ICU", "unit_capacity": 3,
         "required_credential_types": ["RN_LICENSE", "BLS"]},
        ADMIN,
    )
    data = validate_success(resp, 201)
    assert data["name"] == "Alder Bay"
    assert data["unit_name"] == "ICU"
    assert data["unit_capacity"] == 3
    assert data["required_credential_types"] == ["RN_LICENSE", "BLS"]
    assert data["pending_pay_cents"] == 0
    assert data["outstanding_balance_cents"] == 0
    assert data["lifetime_billed_cents"] == 0
    assert data["version"] == 1


def test_system_fields_use_logical_clock_default(api):
    """PRD 2.4: "Before the clock is ever set it reads exactly
    `2026-05-01T00:00:00Z`."
    PRD 3.2: "A new clinician begins with `status` `ACTIVE`, a `reliability_score`
    of 100, and a `provisional_reliability_score` of 100; the derived
    `no_show_count` and `completed_shift_count` both start at 0."

    Design: Corner/entities/system_fields_use_logical_clock_default_of_2026_05_01
    """
    # Deliberately do NOT set the clock — it must read the default instant.
    fac = validate_success(
        api.create_facility(
            {"name": "Clockless General", "unit_name": "ICU", "unit_capacity": 2,
             "required_credential_types": ["RN_LICENSE"]},
            ADMIN,
        ),
        201,
    )
    cl = validate_success(
        api.create_clinician(
            {"full_name": "Rae Sandoval", "email": "rae.sandoval@example.com", "specialty": "RN"},
            ADMIN,
        ),
        201,
    )
    assert cl["created_at"] == "2026-05-01T00:00:00.000Z"
    assert cl["version"] == 1
    assert cl["status"] == "ACTIVE"
    assert cl["reliability_score"] == 100 and cl["provisional_reliability_score"] == 100
    assert cl["no_show_count"] == 0 and cl["completed_shift_count"] == 0
    assert fac["created_at"] == "2026-05-01T00:00:00.000Z"


def test_get_clinician_returns_stored_entity(api):
    """PRD 3.2: "A new clinician begins with `status` `ACTIVE`, a `reliability_score`
    of 100, and a `provisional_reliability_score` of 100; the derived
    `no_show_count` and `completed_shift_count` both start at 0."

    Design: Corner/entities/get_clinician_returns_stored_entity
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    cl = fx.new_clinician(full_name="Sol Ibarra", email="sol.ibarra@example.com", specialty="LPN")
    resp = api.get_clinician(cl["id"], OFFICER)
    data = validate_success(resp, 200)
    assert resp.json()["response_type"] == "object"
    assert data["specialty"] == "LPN"
    assert data["provisional_reliability_score"] == 100
    assert data["full_name"] == "Sol Ibarra"


def test_list_facility_orders_paginates(api):
    """PRD 2.3: "Each list response carries `limit`, `offset`, `total_count` (the
    number of records matching the query before the page window is applied), and
    `has_more` (true when records remain beyond the current page) inside `meta`."

    Design: Corner/entities/list_facility_orders_paginates_with_total_count_and_has_more
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    fac = fx.new_facility(name="Three Orders Medical", unit_capacity=4)
    fac_id = fac["id"]
    fx.new_order(fac_id, window_start="2026-06-08T00:00:00Z", window_end="2026-06-15T00:00:00Z")
    fx.new_order(fac_id, window_start="2026-06-15T00:00:00Z", window_end="2026-06-22T00:00:00Z")
    fx.new_order(fac_id, urgency="CRISIS", window_start="2026-06-22T00:00:00Z", window_end="2026-06-29T00:00:00Z")

    sched = make_scheduler_headers(fac_id)
    page1, meta1 = validate_paginated(api.list_facility_orders(fac_id, sched, params={"limit": 2, "offset": 0}))
    assert len(page1) == 2
    assert meta1["total_count"] == 3 and meta1["has_more"] is True
    assert meta1["limit"] == 2 and meta1["offset"] == 0

    page2, meta2 = validate_paginated(api.list_facility_orders(fac_id, sched, params={"limit": 2, "offset": 2}))
    assert len(page2) == 1
    assert meta2["total_count"] == 3 and meta2["has_more"] is False
    assert meta2["offset"] == 2


def test_get_unknown_shift_returns_not_found(api):
    """PRD 2.7: "existence of every `id` named in the path, resolved left to right
    (the not-found errors for facility, clinician, credential, order, shift, claim,
    assignment, timesheet, invoice, and reliability event)".

    Design: Corner/entities/get_shift_with_unknown_id_returns_shift_not_found
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    fac = fx.new_facility(name="Empty Shifts")
    resp = api.get_shift("11111111-2222-3333-4444-555555555555", make_scheduler_headers(fac["id"]))
    validate_error(resp, ApiErrorId.ERR_SHIFT_NOT_FOUND.value, 404)
    assert resp.json()["response_type"] == "error"


def test_create_order_missing_headcount_returns_validation(api):
    """PRD 2.8: "A missing required field, a value of the wrong type, an invalid
    enum member, or an out-of-range number all raise `ERR_VALIDATION` (HTTP 400)."

    Design: Corner/entities/create_order_missing_required_headcount_returns_validation
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    fac = fx.new_facility(name="Missing Field Health")
    fac_id = fac["id"]
    resp = api.create_order(
        {"facility_id": fac_id, "specialty": "RN", "urgency": "STANDARD",
         "window_start": "2026-06-08T00:00:00Z", "window_end": "2026-06-15T00:00:00Z"},
        make_scheduler_headers(fac_id),
    )
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value, 400)
    orders, meta = validate_paginated(api.list_facility_orders(fac_id, make_scheduler_headers(fac_id)))
    assert meta["total_count"] == 0


def test_create_clinician_invalid_specialty_returns_validation(api):
    """PRD 2.8: "A missing required field, a value of the wrong type, an invalid
    enum member, or an out-of-range number all raise `ERR_VALIDATION` (HTTP 400)."

    Design: Corner/entities/create_clinician_with_invalid_specialty_enum_returns_validation
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    resp = api.create_clinician(
        {"full_name": "Bad Enum", "email": "bad.enum@example.com", "specialty": "SURGEON"},
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value, 400)


def test_duplicate_clinician_email_returns_validation(api):
    """PRD 2.8: "A clinician's `email` must be unique across all clinicians, and a
    `(clinician_id, credential_type)` pair must be unique among that clinician's
    credentials that are not in the `REVOKED` state; a duplicate of either kind also
    raises `ERR_VALIDATION`."

    Design: Corner/entities/duplicate_clinician_email_returns_validation
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    first = fx.new_clinician(full_name="Tess Oyelaran", email="tess.oyelaran@example.com", specialty="RN")
    resp = api.create_clinician(
        {"full_name": "Tess Duplicate", "email": "tess.oyelaran@example.com", "specialty": "CNA"},
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value, 400)
    stored = validate_success(api.get_clinician(first["id"], ADMIN), 200)
    assert stored["specialty"] == "RN"


def test_create_credential_defaults_to_pending_verification(api):
    """PRD 3.2: "A newly attached credential enters `PENDING_VERIFICATION` and
    confers no eligibility; its `status`, `verified_at`, `verified_by_user_id`, and
    `decision_note` remain at their initial values (the last three null) until a
    `ComplianceOfficer` acts."

    Design: Corner/entities/create_credential_defaults_to_pending_verification
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    cl = fx.new_clinician(full_name="Uma Feld", email="uma.feld@example.com", specialty="RN")
    resp = api.create_credential(
        cl["id"],
        {"credential_type": "BLS", "license_number": "BLS-0001",
         "issued_on": "2025-06-01T00:00:00Z", "expires_on": "2027-06-01T00:00:00Z"},
        make_clinician_headers(cl["id"]),
    )
    data = validate_success(resp, 201)
    assert data["status"] == "PENDING_VERIFICATION"
    assert data["verified_at"] is None and data["verified_by_user_id"] is None
    assert data["clinician_id"] == cl["id"]
    creds, meta = validate_paginated(api.list_credentials(cl["id"], make_clinician_headers(cl["id"])))
    assert meta["total_count"] == 1


def test_shift_estimated_pay_and_effective_rate_computed_at_creation(api):
    """PRD 3.3: "when the order's urgency is `CRISIS`, the effective rate is the base
    rate multiplied by 1.25 and rounded half-up to whole cents once; otherwise the
    effective rate equals the base rate."
    PRD 3.3: "Its `estimated_hours` is the scheduled hours minus the deemed unpaid
    break. Its `estimated_pay_cents` is the estimated pay computed over the scheduled
    interval (described in 3.6 as the estimated variant, with no overtime)."

    Design: Corner/entities/shift_estimated_pay_and_effective_rate_are_computed_at_creation
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    fac = fx.new_facility(name="Estimate Health")
    fx.add_rate_card(fac["id"], base_pay_rate_cents_per_hour=7500)
    order = fx.new_order(fac["id"], urgency="STANDARD")
    resp = api.create_shift(
        order["id"],
        {"scheduled_start": "2026-06-08T07:00:00Z", "scheduled_end": "2026-06-08T19:00:00Z"},
        make_scheduler_headers(fac["id"]),
    )
    data = validate_success(resp, 201)
    assert data["scheduled_hours"] == 12.00
    assert data["estimated_hours"] == 11.50
    assert data["base_pay_rate_cents_per_hour"] == 7500
    assert data["effective_rate_cents_per_hour"] == 7500
    assert data["estimated_pay_cents"] == 86250
    assert data["status"] == "OPEN" and data["claim_count"] == 0
    order_after = validate_success(api.get_order(order["id"], make_scheduler_headers(fac["id"])), 200)
    assert order_after["shift_count"] == 1 and order_after["open_count"] == 1


def test_create_shift_under_unknown_order_returns_order_not_found(api):
    """PRD 2.7: "existence of every `id` named in the path, resolved left to right
    (the not-found errors for facility, clinician, credential, order, shift, claim,
    assignment, timesheet, invoice, and reliability event)".

    Design: Corner/entities/create_shift_under_unknown_order_returns_order_not_found
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    fac = fx.new_facility(name="Orphan Shift Health")
    resp = api.create_shift(
        "99999999-8888-7777-6666-555555555555",
        {"scheduled_start": "2026-06-08T07:00:00Z", "scheduled_end": "2026-06-08T08:00:00Z"},
        make_scheduler_headers(fac["id"]),
    )
    err = validate_error(resp, ApiErrorId.ERR_ORDER_NOT_FOUND.value, 404)
    assert err["error_id"] != ApiErrorId.ERR_SHIFT_DURATION_INVALID.value
