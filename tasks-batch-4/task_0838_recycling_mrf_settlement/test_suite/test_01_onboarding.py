"""Municipality onboarding, reference-data creation, auth, and RBAC."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId, TEST_USERS,
    assert_municipality, assert_municipality_balance_invariant,
    create_municipality_payload,
)
from test_helpers.fixtures import setup_audited_load

CLERK = TEST_USERS["settlement_clerk_headers"]
SCALE = TEST_USERS["scale_operator_headers"]

NON_EXISTENT = "00000000-0000-4000-8000-000000000000"


def test_create_municipality_returns_active_with_zeroed_ledger(api):
    """PRD §3.1: "A new municipality begins with `status` of `ACTIVE` (the
    alternative operational value is `SUSPENDED`) and with all four ledger
    counters — `revenue_share_accrued_cents`, `lifetime_rebate_cents`,
    `lifetime_penalty_cents`, and the derived `balance_cents` — initialized to 0,
    as described in §2.6."
    PRD §4: "Operations that create a brand-new, standalone resource return
    `201 Created`."

    Design: Corner/entities/corner_create_municipality_success
    """
    resp = api.create_municipality(
        create_municipality_payload(name="City A", contact_email="a@x.gov",
                                    revenue_share_pct=0.55), CLERK)
    data = validate_success(resp, 201)
    assert_municipality(data)
    assert data["status"] == "ACTIVE"
    assert data["balance_cents"] == 0
    assert data["revenue_share_accrued_cents"] == 0
    assert data["lifetime_rebate_cents"] == 0
    assert data["lifetime_penalty_cents"] == 0


def test_create_municipality_version_starts_at_one(api):
    """PRD §2.4: "a `version` — an integer that starts at 1 on creation and
    increments by one on every mutation of that resource."

    Design: Corner/entities/corner_create_municipality_success
    """
    resp = api.create_municipality(
        create_municipality_payload(revenue_share_pct=0.55), CLERK)
    data = validate_success(resp, 201)
    assert data["version"] == 1


def test_get_municipality_not_found(api):
    """PRD §2.8: "the server validates their existence left-to-right and rejects
    at the first id that does not resolve, returning the not-found error specific
    to that resource type: `ERR_MUNICIPALITY_NOT_FOUND`".

    Design: Corner/entities/corner_get_municipality_not_found
    """
    resp = api.get_municipality(NON_EXISTENT, CLERK)
    validate_error(resp, ApiErrorId.ERR_MUNICIPALITY_NOT_FOUND.value)


def test_create_municipality_missing_revenue_share_pct_invalid_request(api):
    """PRD §2.10: "A malformed body, a missing required field, or a type mismatch
    surfaces as `ERR_INVALID_REQUEST` (400)."

    Design: Corner/entities/corner_create_municipality_missing_required_returns_invalid_request
    """
    resp = api.create_municipality({"name": "City A"}, CLERK)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_revenue_share_pct_out_of_range_rejected(api):
    """PRD §3.1: "That fraction must lie between 0 and 1 inclusive; a value below
    0 or above 1 is rejected with `ERR_REVENUE_SHARE_PCT_OUT_OF_RANGE`."

    Design: Corner/entities/corner_revenue_share_pct_out_of_range_rejected
    """
    resp = api.create_municipality(
        {"name": "City A", "revenue_share_pct": 1.5}, CLERK)
    validate_error(resp, ApiErrorId.ERR_REVENUE_SHARE_PCT_OUT_OF_RANGE.value)


def test_missing_user_context_header_rejected(api):
    """PRD §2.1: "A request missing either header, or carrying an unrecognized
    value, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`."

    Design: Corner/validations/corner_missing_auth_header_rejected
    """
    resp = api.create_municipality(
        {"name": "City A", "revenue_share_pct": 0.5}, {})
    validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.value)


def test_scale_operator_cannot_create_bale(api):
    """PRD §2.1: "When the header pair is present and valid but the role is not
    permitted to perform the requested operation, the request is rejected with
    `ERR_INSUFFICIENT_PERMISSIONS`."

    Design: Corner/rbac/corner_scaleoperator_cannot_create_bale
    """
    # Build an audited OCC load; POST /mrf/bales is exclusive to SortManager.
    from test_helpers.fixtures import set_clock, create_and_publish_index
    set_clock(api, "2026-03-10T00:00:00Z")
    ctx = setup_audited_load(api)  # sampled 3.0, composition OCC
    create_and_publish_index(api, "OCC", 8000)
    resp = api.create_bale(
        {"source_load_id": ctx["load_id"], "commodity": "OCC", "net_tons": 5,
         "moisture_pct": 0, "quality_grade": "A"}, SCALE)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value)
