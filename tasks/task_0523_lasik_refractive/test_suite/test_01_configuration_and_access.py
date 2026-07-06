"""Configuration creation, defaults, validation, listing, and access control.

Translates queue-B corner instances in the entities / endpoints / rbac sections.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS, NONEXISTENT_UUID,
    make_patient_headers, make_optometrist_headers,
    create_package_payload, create_suite_payload, create_patient_payload,
    create_screening_payload,
    assert_package,
)
from test_helpers import fixtures as fx

COORD = TEST_USERS["coordinator_headers"]
ANON = TEST_USERS["anonymous_headers"]


def test_create_package_returns_201_with_echoed_fields(api):
    """PRD §3.1: "It is created with a `tier` — one of `STANDARD`, `PREMIUM`, or
    `LIFETIME` — a `base_price_cents` (the sticker price before any deposit or
    financing, at least zero), a `deposit_cents` ... and an
    `enhancement_window_days` value ... The package also declares
    `outcome_guarantee_uncorrected_va` ... and a `refund_mode` of either
    `PRO_RATA` or `DEPOSIT_FORFEIT`".
    PRD §4: "Operations that create a new resource return `201 Created`."

    Design: Corner/entities/create_package_returns_201_all_fields
    """
    resp = api.create_package(create_package_payload(
        tier="PREMIUM", base_price_cents=700000, deposit_cents=70000,
        enhancement_window_days=730, outcome_guarantee_uncorrected_va=1.0,
        refund_mode="DEPOSIT_FORFEIT",
    ), COORD)
    data = validate_success(resp, expected_status=201)
    assert_package(data)
    assert data["tier"] == "PREMIUM"
    assert data["base_price_cents"] == 700000
    assert data["refund_mode"] == "DEPOSIT_FORFEIT"


def test_package_active_defaults_true(api):
    """PRD §3.1: "A package is created with `active` defaulting to true; only an
    active package may back new surgery cases."

    Design: Corner/entities/package_active_defaults_true
    """
    payload = create_package_payload()
    payload.pop("active", None)
    data = validate_success(api.create_package(payload, COORD), expected_status=201)
    assert data["active"] is True


def test_suite_status_defaults_open(api):
    """PRD §3.1: "A suite's `status` defaults to `OPEN` and may be `MAINTENANCE`."

    Design: Corner/entities/suite_status_defaults_open
    """
    payload = create_suite_payload(daily_case_cap=3)
    payload.pop("status", None)
    data = validate_success(api.create_suite(payload, COORD), expected_status=201)
    assert data["status"] == "OPEN"


def test_patient_registration_initializes_status_prospect(api):
    """PRD §3.2: "A newly registered patient begins with `status` set to
    `PROSPECT`; over their journey this derived standing moves to `CANDIDATE`,
    `INELIGIBLE`, or `OPERATED`."

    Design: Corner/entities/patient_status_system_initialized_prospect
    """
    data = validate_success(api.create_patient(create_patient_payload(), ANON), expected_status=201)
    assert data["status"] == "PROSPECT"


def test_draft_screening_has_no_computed_ablation_value(api):
    """PRD §3.2: "Two further values, `ablation_depth_um` and
    `residual_stromal_bed_um`, are not supplied at creation; they are computed
    when the screening is submitted."

    Design: Corner/entities/screening_computed_fields_ignore_input
    """
    od = fx.create_optometrist()
    pat = fx.create_patient()
    resp = api.create_screening(
        create_screening_payload(pat["id"], od["id"]),
        make_optometrist_headers(od["id"]),
    )
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "DRAFT"
    # Not computed until submit: either absent or null — never a real value.
    assert data.get("ablation_depth_um") is None


def test_get_patient_unknown_id_returns_not_found(api):
    """PRD §2.9: "the server validates the referenced identifiers left to right
    and rejects the request with `ERR_NOT_FOUND` (HTTP 404) at the first
    identifier in the path that does not resolve to an existing resource."

    Design: Corner/entities/get_patient_not_found_returns_404
    """
    resp = api.get_patient(NONEXISTENT_UUID, COORD)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_create_screening_missing_required_field_rejected(api):
    """PRD §2.9: "then request well-formedness — valid JSON with all required
    fields present and correctly typed, failing which the request is rejected
    with `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/create_screening_missing_required_field
    """
    od = fx.create_optometrist()
    pat = fx.create_patient()
    payload = create_screening_payload(pat["id"], od["id"])
    payload.pop("topography_k_max")
    resp = api.create_screening(payload, make_optometrist_headers(od["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_create_package_invalid_tier_enum_rejected(api):
    """PRD §2.9: "valid JSON with all required fields present and correctly
    typed, failing which the request is rejected with `ERR_INVALID_REQUEST`
    (HTTP 400)."
    PRD §3.1: "It is created with a `tier` — one of `STANDARD`, `PREMIUM`, or
    `LIFETIME`".

    Design: Corner/entities/create_package_invalid_enum_tier
    """
    resp = api.create_package(create_package_payload(tier="GOLD"), COORD)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_list_packages_returns_paginated_envelope(api):
    """PRD §2.3: "Each list response carries `limit`, `offset`, `total_count`,
    and `has_more` inside the `meta` object of the envelope."

    Design: Corner/endpoints/list_packages_pagination_envelope
    """
    fx.create_package(tier="STANDARD")
    fx.create_package(tier="PREMIUM", base_price_cents=700000, deposit_cents=70000,
                      enhancement_window_days=730, refund_mode="DEPOSIT_FORFEIT")
    data, meta = validate_paginated(api.list_packages(COORD, params={"limit": 1, "offset": 0}))
    assert len(data) == 1
    assert meta["total_count"] == 2
    assert meta["has_more"] is True


def test_patient_cannot_create_package_forbidden(api):
    """PRD §2.1: "When the headers are present but the role is not permitted to
    perform the requested operation, the request is rejected with `ERR_FORBIDDEN`
    (HTTP 403)."
    PRD §4: "POST | `/refractive/packages` | Create a treatment package |
    Coordinator".

    Design: Corner/rbac/patient_cannot_create_package_forbidden
    """
    pat = fx.create_patient()
    resp = api.create_package(create_package_payload(), make_patient_headers(pat["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


def test_optometrist_cannot_adjudicate_screening_forbidden(api):
    """PRD §2.1: "When the headers are present but the role is not permitted to
    perform the requested operation, the request is rejected with `ERR_FORBIDDEN`
    (HTTP 403)."
    PRD §4: "POST | `/refractive/screenings/{id}/adjudicate` | Approve or reject
    a screening | Surgeon".

    Design: Corner/rbac/optometrist_cannot_adjudicate_screening_forbidden
    """
    od = fx.create_optometrist()
    pat = fx.create_patient()
    scr = fx.create_submitted_screening(od["id"], pat["id"])
    resp = api.adjudicate_screening(
        scr["id"], {"decision": "APPROVE"}, make_optometrist_headers(od["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


def test_missing_auth_headers_unauthenticated(api):
    """PRD §2.1: "When either header is missing on a protected endpoint, the
    request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/rbac/missing_auth_headers_unauthenticated
    """
    resp = api.list_packages({})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)
