"""Corner-design coverage — entities section."""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    set_clock,
    register_client,
    sign_retainer,
    create_case,
    activate_case,
    register_provider,
    create_records_request,
    walk_records_request_to_reviewed,
    create_included_damages,
    get_case,
    ApiErrorId,
    NON_EXISTENT_UUID,
    api_client,
    create_case_payload,
    create_damages_item_payload,
    make_paralegal_headers,
    make_attorney_headers,
    setup_active_case,
)


# ─── client_register_returns_201_with_all_fields ────────────────────


def test_client_register_returns_201_with_required_shape(api):
    """PRD §3.1: "A new matter begins with a `Paralegal` registering the
    potential client on the public intake endpoint. The new record carries
    the client's `full_name`, `email`, and `phone`, with `email` being unique
    across all clients in the system. The retainer is not signed at
    registration: `retainer_signed` starts at `false` and `retainer_signed_at`
    is null."

    Design: Corner/entities/client_register_returns_201_with_all_fields
    """
    set_clock("2026-01-01T00:00:00Z")
    res = api_client.register_client(
        {"full_name": "Alpha Client", "email": "alpha@example.com",
         "phone": "555-2000"},
        {},  # public endpoint — no auth header.
    )
    body = validate_success(res, 201)
    assert body["full_name"] == "Alpha Client"
    assert body["email"] == "alpha@example.com"
    assert body["retainer_signed"] is False
    assert body["retainer_signed_at"] is None
    assert body["version"] == 1


# ─── case_get_with_unknown_id_returns_not_found ─────────────────────


def test_case_get_with_unknown_id_returns_resource_not_found(api):
    """PRD §2.5: "If it does not — for example, when a settlement-offer
    action is invoked with an id that belongs to no settlement offer at all
    — the request is rejected with `ERR_RESOURCE_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/case_get_with_unknown_id_returns_not_found
    """
    from test_helpers import TEST_USERS
    set_clock("2026-01-01T00:00:00Z")
    res = api.get_case(NON_EXISTENT_UUID, TEST_USERS["attorney_headers"])
    validate_error(res, ApiErrorId.ERR_RESOURCE_NOT_FOUND.value)


# ─── case_create_missing_required_field_rejected ────────────────────


def test_case_create_without_jurisdiction_returns_invalid_request(api):
    """PRD §2.5: "Missing or malformed inputs that fail no other guard fall
    to `ERR_INVALID_REQUEST` (HTTP 400), the lowest-priority validation in
    the system, which fires only when none of the prior checks would have
    matched."
    PRD §3.1: "With the client in place, the paralegal opens the matter by
    creating the case, supplying the `client_id`, the `accident_date` on
    which the injury occurred, the `jurisdiction` in which the case will
    sit, and optionally an integer `sol_tolled_days` to add for tolling
    reasons such as a minor claimant or fraudulent concealment."

    Design: Corner/entities/case_create_missing_required_field_rejected
    """
    set_clock("2026-01-01T00:00:00Z")
    client = register_client()
    sign_retainer(client["id"])
    # Omit jurisdiction.
    res = api_client.create_case(
        {"client_id": client["id"], "accident_date": "2024-06-15"},
        make_paralegal_headers(),
    )
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST.value)


# ─── case_create_bad_jurisdiction_enum_rejected ─────────────────────


def test_case_create_with_bad_jurisdiction_returns_invalid_request(api):
    """PRD §3.1: "The case is opened in `INTAKE` status; its
    `statute_of_limitations_date` is computed from the accident date plus
    the jurisdictional statute years (California, New York, Texas, and
    Illinois each give two years; Florida gives four), and that statute
    date is effectively immutable because `accident_date` and `jurisdiction`
    cannot be changed after creation."
    PRD §2.5: "Missing or malformed inputs that fail no other guard fall to
    `ERR_INVALID_REQUEST` (HTTP 400), the lowest-priority validation in the
    system, which fires only when none of the prior checks would have
    matched."

    Design: Corner/entities/case_create_bad_jurisdiction_enum_rejected
    """
    set_clock("2026-01-01T00:00:00Z")
    client = register_client()
    sign_retainer(client["id"])
    res = api_client.create_case(
        {"client_id": client["id"], "accident_date": "2024-06-15",
         "jurisdiction": "WA"},
        make_paralegal_headers(),
    )
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST.value)


# ─── case_create_with_fk_unknown_client_rejected ────────────────────


def test_case_create_with_unknown_client_id_returns_fk_not_found(api):
    """PRD §2.5: "Foreign-key references in request bodies (such as the
    `client_id` on a new case, the `case_id` and `provider_id` on a new
    records request or lien, or a `counter_to_offer_id` on a counter-offer)
    are checked separately: a body field that names a non-existent entity
    is rejected with `ERR_FK_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/case_create_with_fk_unknown_client_rejected
    """
    set_clock("2026-01-01T00:00:00Z")
    res = api_client.create_case(
        {"client_id": NON_EXISTENT_UUID, "accident_date": "2024-06-15",
         "jurisdiction": "CA"},
        make_paralegal_headers(),
    )
    validate_error(res, ApiErrorId.ERR_FK_NOT_FOUND.value)


# ─── case_sol_default_zero_tolling ──────────────────────────────────


def test_case_sol_with_omitted_tolling_uses_jurisdiction_years_only(api):
    """PRD §3.1: "with the client in place, the paralegal opens the matter
    by creating the case, supplying the `client_id`, the `accident_date` on
    which the injury occurred, the `jurisdiction` in which the case will
    sit, and optionally an integer `sol_tolled_days` to add for tolling
    reasons such as a minor claimant or fraudulent concealment."
    PRD §3.1: "its `statute_of_limitations_date` is computed from the
    accident date plus the jurisdictional statute years (California, New
    York, Texas, and Illinois each give two years; Florida gives four), and
    that statute date is effectively immutable because `accident_date` and
    `jurisdiction` cannot be changed after creation. The tolling number is
    added on top in days."

    Design: Corner/entities/case_sol_default_zero_tolling
    """
    set_clock("2026-01-01T00:00:00Z")
    client = register_client()
    sign_retainer(client["id"])
    # Omit sol_tolled_days entirely — PRD §3.1 says it is optional.
    case = create_case(client["id"], accident_date="2024-01-15",
                        jurisdiction="CA")
    # CA = 2 years per PRD §3.1; with no tolling added, SOL = 2026-01-15.
    sol = case["statute_of_limitations_date"]
    assert sol.startswith("2026-01-15"), (
        f"With no tolling and CA jurisdiction (2 years), SOL must start "
        f"with 2026-01-15, got {sol!r}"
    )


# ─── case_included_damages_total_is_computed ────────────────────────


def test_case_included_damages_total_reflects_sum_of_included_items(api):
    """PRD §3.3: "On inclusion the system recomputes
    `Case.included_damages_total_cents` as the sum of `amount_cents`
    across every `INCLUDED` item on the case (a depth-two cascade off the
    include action) and increments `Case.version` by one."

    Design: Corner/entities/case_included_damages_total_is_computed
    """
    set_clock("2026-01-01T00:00:00Z")
    from test_helpers import (
        setup_active_case_with_reviewed_records as _setup_arr,
    )
    client, case, provider, mrr = _setup_arr()
    create_included_damages(case["id"], "MEDICAL_BILLS", 200_000)
    create_included_damages(case["id"], "LOST_WAGES", 250_000)
    create_included_damages(case["id"], "PROPERTY", 150_000)
    case_after = get_case(case["id"])
    assert case_after["included_damages_total_cents"] == 600_000


# ─── damages_pain_suffering_cap_exceeded_ca ─────────────────────────


def test_pain_suffering_over_cap_in_california_returns_over_cap(api):
    """PRD §3.3: "A jurisdictional damages cap applies: in California and
    Florida, a `PAIN_SUFFERING` item with `amount_cents` exceeding $250,000
    (25,000,000 cents) is rejected with `ERR_DAMAGES_OVER_CAP`; other
    categories and other jurisdictions are uncapped at this layer."

    Design: Corner/entities/damages_pain_suffering_cap_exceeded_ca
    """
    set_clock("2026-01-01T00:00:00Z")
    client, case = setup_active_case(jurisdiction="CA")
    # 25_000_001 = one cent over the CA cap of $250,000.
    res = api_client.create_damages_item(
        create_damages_item_payload(case["id"], "PAIN_SUFFERING", 25_000_001),
        make_paralegal_headers(),
    )
    validate_error(res, ApiErrorId.ERR_DAMAGES_OVER_CAP.value)
