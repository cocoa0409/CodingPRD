"""Entity CRUD, defaults, computed fields, type constraints, FK integrity.

Translates SCAFFOLD_CORNER_DESIGN.yaml §1.9 `entities` non-stub instances.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId,
    create_account_payload, create_site_payload, create_crew_payload,
    create_visit_payload, create_inspection_payload,
    fixtures,
)
from test_helpers.test_users import TEST_USERS

AM = TEST_USERS["account_manager_headers"]
FS = TEST_USERS["field_supervisor_headers"]


def test_create_account_returns_201_with_system_defaults(api):
    """PRD §3.1: "A freshly created account opens in `ACTIVE` `status`, with its
    derived `open_complaint_count` initialized to 0 and `version` at 1."

    Design: Corner/entities/create_account_returns_201_with_system_defaults
    """
    resp = api.create_account(create_account_payload(), AM)
    data = validate_success(resp, 201)
    assert data["status"] == "ACTIVE"
    assert data["open_complaint_count"] == 0
    assert data["version"] == 1


def test_get_account_returns_stored_entity(api):
    """PRD §2.2: "Unless otherwise noted, operations that create or modify a
    resource will return the created or updated resource object in the data field."

    Design: Corner/entities/get_account_returns_stored_entity
    """
    created = validate_success(
        api.create_account(create_account_payload(name="Acme", billing_email="ap@acme.test"), AM), 201)
    resp = api.get_account(created["id"], AM)
    data = validate_success(resp, 200)
    assert data["name"] == "Acme"
    assert data["billing_email"] == "ap@acme.test"


def test_list_accounts_paginated_envelope(api):
    """PRD §2.3: "Each list response carries `limit`, `offset`, `total_count` (the
    number of resources matching the filter before pagination), and `has_more`
    (true when more resources remain beyond the current page) inside its `meta` object."

    Design: Corner/entities/list_accounts_paginated_envelope
    """
    validate_success(api.create_account(create_account_payload(name="Acme", billing_email="a@acme.test"), AM), 201)
    validate_success(api.create_account(create_account_payload(name="Beta", billing_email="b@beta.test"), AM), 201)
    resp = api.list_accounts(AM, params={"limit": 1, "offset": 0})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    assert len(data) == 1


def test_get_account_nonexistent_returns_not_found(api):
    """PRD §2.5: "if any path-referenced resource does not exist, the request
    fails with `ERR_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/get_account_nonexistent_returns_not_found
    """
    resp = api.get_account("acct_does_not_exist", AM)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_create_site_missing_required_field_returns_invalid_request(api):
    """PRD §3.1: "the `cleanable_sqft` (which must be greater than 0 and drives
    labor-hour estimation)". PRD §2.6: "well-formedness of the request body —
    required fields present, enum values valid, and numeric ranges respected —
    yielding `ERR_INVALID_REQUEST` (HTTP 422)."

    Design: Corner/entities/create_site_missing_required_field_returns_invalid_request
    """
    acct = fixtures.create_account()
    payload = create_site_payload(acct["id"])
    del payload["cleanable_sqft"]
    resp = api.create_site(payload, AM)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_create_site_omits_quality_target_applies_default_85(api):
    """PRD §3.1: "The optional `quality_target` is the minimum acceptable
    inspection score in the range 0 to 100; if omitted it defaults to 85."

    Design: Corner/entities/create_site_omits_quality_target_applies_default_85
    """
    acct = fixtures.create_account()
    payload = create_site_payload(acct["id"])
    payload.pop("quality_target", None)
    resp = api.create_site(payload, AM)
    data = validate_success(resp, 201)
    assert data["quality_target"] == 85


def test_create_crew_omits_shift_capacity_applies_default_480(api):
    """PRD §3.2: "Each crew member carries a `shift_capacity_min` ... which must
    be greater than 0 and defaults to 480 when not supplied. A crew member opens
    in `AVAILABLE` status."

    Design: Corner/entities/create_crew_omits_shift_capacity_applies_default_480
    """
    payload = create_crew_payload()
    payload.pop("shift_capacity_min", None)
    resp = api.create_crew(payload, FS)
    data = validate_success(resp, 201)
    assert data["shift_capacity_min"] == 480
    assert data["status"] == "AVAILABLE"


def test_inspection_deficient_computed_below_target(api):
    """PRD §3.8: "On creation the system computes `deficient` as true when the
    `score` is below the site's `quality_target` at the time of inspection, and
    false otherwise."

    Design: Corner/entities/inspection_deficient_computed_below_target
    """
    _, site, crew = fixtures.setup_account_site_crew(site_overrides={"quality_target": 85})
    visit = fixtures.create_started_visit(site["id"], crew["id"])
    resp = api.create_inspection(create_inspection_payload(visit["id"], 80), FS)
    data = validate_success(resp, 201)
    assert data["deficient"] is True


def test_create_site_bad_floor_type_enum_returns_invalid_request(api):
    """PRD §2.6: "Body well-formedness covers, among others ... enum values valid".
    PRD §3.1: "a `floor_type` of `CARPET`, `VCT`, `TERRAZZO`, or `CONCRETE`."

    Design: Corner/entities/create_site_bad_floor_type_enum_returns_invalid_request
    """
    acct = fixtures.create_account()
    resp = api.create_site(create_site_payload(acct["id"], floor_type="MARBLE"), AM)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_create_site_nonpositive_sqft_returns_invalid_request(api):
    """PRD §2.6: "Body well-formedness covers, among others: `cleanable_sqft` must
    be greater than 0". Any violation of these well-formedness rules yields
    `ERR_INVALID_REQUEST`.

    Design: Corner/entities/create_site_nonpositive_sqft_returns_invalid_request
    """
    acct = fixtures.create_account()
    resp = api.create_site(create_site_payload(acct["id"], cleanable_sqft=0), AM)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_create_schedule_window_end_le_start_returns_invalid_request(api):
    """PRD §2.6: "a schedule's `window_end_min` must be greater than its
    `window_start_min`". Any violation of these well-formedness rules yields
    `ERR_INVALID_REQUEST`.

    Design: Corner/entities/create_schedule_window_end_le_start_returns_invalid_request
    """
    _, site, crew = fixtures.setup_account_site_crew()
    resp = api.create_schedule(
        {"site_id": site["id"], "weekday": 0, "window_start_min": 660,
         "window_end_min": 660, "assigned_crew_id": crew["id"]}, FS)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_invoice_line_immutable_no_version_field(api):
    """PRD §2.4: "an `InvoiceLine` carries only `id` and `created_at` — it has no
    `updated_at` and no `version`, because once written it is never modified."
    PRD §3.9: "emits the immutable invoice-line ledger for the period — a `BASE`
    line, one `PERIODIC` line for the summed captured periodic charges, one
    `CALLBACK_CREDIT` line, and one `HOLDBACK` line".

    Design: Corner/entities/invoice_line_immutable_no_version_field
    """
    bundle = fixtures.setup_closed_period()
    resp = api.list_invoice_lines(bundle["period"]["id"], AM)
    data, _meta = validate_paginated(resp)
    base_lines = [ln for ln in data if ln["line_type"] == "BASE"]
    assert len(base_lines) == 1
    base = base_lines[0]
    assert base["amount_cents"] == 300000
    for ln in data:
        assert "version" not in ln, "InvoiceLine must not carry version"
        assert "updated_at" not in ln, "InvoiceLine must not carry updated_at"
        assert "id" in ln and "created_at" in ln


def test_create_site_unknown_account_fk_returns_fk_not_found(api):
    """PRD §2.5: "when a request body carries a foreign key — for example
    `account_id` ... — and that key points at a row that does not exist, the
    request fails with `ERR_FK_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/create_site_unknown_account_fk_returns_fk_not_found
    """
    resp = api.create_site(create_site_payload("acct_missing"), AM)
    validate_error(resp, ApiErrorId.ERR_FK_NOT_FOUND.value)
