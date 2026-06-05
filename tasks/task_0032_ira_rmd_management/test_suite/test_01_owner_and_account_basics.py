"""Owner registration, identity, and account basics (PRD §3.1, §3.2)."""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    set_clock,
    create_owner,
)


def test_register_owner_returns_201_with_default_rmd_posture(api):
    """PRD §3.1: "The owner is created with `rmd_posture` of `NOT_REQUIRED`
    and a null `deceased_at`."
    PRD §2.4: "an integer `version` that starts at 1 on creation and is
    incremented by 1 on every server-side mutation of that row."

    Design: Corner/entities/account_owner_creation_returns_201_and_initializes_rmd_posture
    """
    set_clock("2026-06-01T00:00:00Z")
    res = api.create_owner(
        {
            "full_name": "Aaron",
            "date_of_birth": "1980-01-01",
            "tax_id_last4": "1111",
            "filing_status": "SINGLE",
        },
        TEST_USERS["plan_admin_headers"],
    )
    owner = validate_success(res, expected_status=201)
    assert owner["rmd_posture"] == "NOT_REQUIRED", (
        f"newly-registered owner must start at NOT_REQUIRED, got {owner['rmd_posture']!r}"
    )
    assert owner["version"] == 1, (
        f"version must start at 1, got {owner['version']!r}"
    )
    assert owner.get("created_at"), "created_at must be set on creation"


def test_get_nonexistent_owner_returns_404(api):
    """PRD §2.5: "The first segment whose templated id does not resolve to an
    existing entity yields `ERR_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/account_owner_not_found_returns_404
    """
    set_clock("2026-06-01T00:00:00Z")
    res = api.get_owner(NON_EXISTENT_UUID, TEST_USERS["plan_admin_headers"])
    validate_error(res, ApiErrorId.ERR_NOT_FOUND.value)


def test_create_contribution_missing_kind_returns_invalid_request(api):
    """PRD §2.6: "Malformed payloads — a required field missing, an enum value
    out of range, or a type mismatch — surface as `ERR_INVALID_REQUEST`
    (HTTP 400) during request parsing, before any of the above evaluate."
    PRD §3.3: "An `AccountOwner` creates a contribution against one of their
    accounts by supplying an `account_id`, a four-digit `tax_year`, a positive
    integer `amount_cents`, and a `contribution_kind` of `PRETAX`, `AFTERTAX`,
    or `ROTH`."

    Design: Corner/entities/contribution_missing_required_field_returns_invalid_request
    """
    from test_helpers import make_account_owner_headers
    set_clock("2026-06-01T00:00:00Z")
    owner = create_owner(full_name="Aaron")
    from test_helpers import create_account
    account = create_account(owner["id"], "TRADITIONAL")

    payload = {
        "account_id": account["id"],
        "tax_year": 2026,
        "amount_cents": 100_000,
        # contribution_kind intentionally omitted
    }
    res = api.create_contribution(payload, make_account_owner_headers(owner["id"]))
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST.value)
