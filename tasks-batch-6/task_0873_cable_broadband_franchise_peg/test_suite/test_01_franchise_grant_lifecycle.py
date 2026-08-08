"""Franchise grant creation and lifecycle transitions."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId, NON_EXISTENT_UUID,
    assert_franchise,
    TEST_USERS, make_operator_headers,
    create_franchise_payload, create_row_permit_payload,
)
from test_helpers import create_active_franchise, create_row_segment

AUTHORITY = TEST_USERS["authority_headers"]


def test_create_franchise_success_defaults(api):
    """PRD 3.1: "A new grant is created at `lifecycle_status` `DRAFT` and
    `compliance_status` `COMPLIANT`, with `version` 1, `unresolved_complaint_count`
    0, and `homes_passed` 0."
    PRD 3.1: "An optional `peg_fee_per_sub_cents` captures a per-subscriber
    PEG/I-Net capital support fee in cents (at least 0, defaulting to 0)."

    Design: Corner/entities/create_franchise_success_defaults
    """
    resp = api.create_franchise(create_franchise_payload(), AUTHORITY)
    data = validate_success(resp, 201)
    assert_franchise(data)
    assert data["lifecycle_status"] == "DRAFT"
    assert data["compliance_status"] == "COMPLIANT"
    assert data["version"] == 1
    assert data["peg_fee_per_sub_cents"] == 0


def test_create_franchise_missing_fee_rate_returns_invalid_request(api):
    """PRD 2.8: "on every write, required fields present, enum values legal,
    numeric types and ranges valid, else `ERR_INVALID_REQUEST` (400)."

    Design: Corner/entities/create_franchise_missing_required_returns_invalid_request
    """
    payload = create_franchise_payload()
    del payload["fee_rate_pct"]
    resp = api.create_franchise(payload, AUTHORITY)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value, 400)


def test_get_unknown_franchise_returns_not_found(api):
    """PRD 2.8: "every path `id` and every body foreign key resolves to an
    existing resource, validated left-to-right, else `ERR_NOT_FOUND` (404)."

    Design: Corner/entities/get_franchise_not_found_returns_404
    """
    resp = api.get_franchise(NON_EXISTENT_UUID, AUTHORITY)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value, 404)


def test_activate_already_active_returns_invalid_state(api):
    """PRD 3.1: "Activating a grant advances it from `DRAFT` to `ACTIVE`; it is
    defined only from `DRAFT`."
    PRD 3.1: "Any transition attempted from a state where it is not defined is
    rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/activate_already_active_returns_invalid_state
    """
    fr = create_active_franchise(api)
    resp = api.activate_franchise(fr["id"], AUTHORITY)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)


def test_revoked_franchise_row_permit_create_blocked(api):
    """PRD 3.2: "First, the target franchise's `lifecycle_status` must be
    `ACTIVE`; otherwise the request is rejected with `ERR_FRANCHISE_NOT_ACTIVE`."
    PRD 3.1: "Revoking a grant advances it from `ACTIVE` to `REVOKED`, a terminal
    lifecycle state; it is defined only from `ACTIVE`."

    Design: Corner/state_machines/revoked_franchise_row_permit_create_from_terminal_blocked
    """
    fr = create_active_franchise(api)
    seg = create_row_segment(api, name="Pine St", length_miles=0.2, homes_along=40)
    validate_success(api.revoke_franchise(fr["id"], AUTHORITY), 200)

    op = make_operator_headers(fr["id"])
    payload = create_row_permit_payload(fr["id"], seg["id"], purpose="conduit")
    resp = api.create_row_permit(payload, op)
    validate_error(resp, ApiErrorId.ERR_FRANCHISE_NOT_ACTIVE.value, 409)
