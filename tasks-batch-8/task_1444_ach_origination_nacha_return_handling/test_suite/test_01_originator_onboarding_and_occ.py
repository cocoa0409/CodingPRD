"""Originator registration defaults, underwriting terminal state, OCC, and auth."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_originator,
    assert_version_incremented,
    create_active_originator,
    create_originator_payload,
    create_pending_originator,
    make_underwriter_headers,
    patch_originator_payload,
    read_originator,
    validate_error,
    validate_success,
)


def test_originator_registered_with_zeroed_defaults(api, underwriter_headers):
    """PRD 3.1: "The record is born in `PENDING_UNDERWRITING` status with
    `exposure_limit_cents` at its default of 0 and `fee_discount_bps` at its
    default of 0."
    PRD 3.1: "Its computed fields also start at zero: `unauth_rate_bps_trailing`,
    `unauth_rate_bps_mtd`, `outstanding_exposure_gross_cents`, and
    `outstanding_exposure_debit_cents` all begin at 0 until business activity
    refreshes them."

    Design: Corner/entities/originator_creation_defaults_applied
    """
    res = api.create_originator(
        create_originator_payload("Defaults Co", ["PPD"]), underwriter_headers)
    org = validate_success(res, 201)
    assert_originator(org)
    assert org["status"] == "PENDING_UNDERWRITING"
    assert org["exposure_limit_cents"] == 0
    assert org["fee_discount_bps"] == 0
    assert org["unauth_rate_bps_trailing"] == 0
    assert org["unauth_rate_bps_mtd"] == 0
    assert org["outstanding_exposure_gross_cents"] == 0
    assert org["outstanding_exposure_debit_cents"] == 0
    assert isinstance(org["version"], int) and org["version"] >= 1


def test_get_unknown_originator_returns_not_found(api, operations_headers):
    """PRD 2.6: "The request is rejected with `ERR_NOT_FOUND` at the first
    identifier that does not resolve."

    Design: Corner/entities/get_originator_not_found_returns_404
    """
    res = api.get_originator(NON_EXISTENT_UUID, operations_headers)
    validate_error(res, ApiErrorId.ERR_NOT_FOUND, expected_status=404)


def test_patch_terminated_originator_rejected(api, underwriter_headers):
    """PRD 3.1: "Presenting a `decision` for an originator no longer in
    `PENDING_UNDERWRITING`, or submitting any update of any kind for a
    `TERMINATED` originator, is rejected with `ERR_ORIGINATOR_STATUS_TERMINAL`."

    Design: Corner/state_machines/patch_terminated_originator_returns_invalid_state
    """
    org = create_pending_originator("Term Co", ["PPD"])
    declined = validate_success(api.patch_originator(
        org["id"],
        patch_originator_payload(org["version"], decision="DECLINE"),
        underwriter_headers), 200)
    assert declined["status"] == "TERMINATED"

    res = api.patch_originator(
        org["id"],
        patch_originator_payload(declined["version"],
                                 exposure_limit_cents=9_000_000),
        underwriter_headers)
    validate_error(res, ApiErrorId.ERR_ORIGINATOR_STATUS_TERMINAL,
                   expected_status=409)

    after = read_originator(org["id"])
    assert after["status"] == "TERMINATED"
    assert after["exposure_limit_cents"] == 0, \
        "rejected update must not persist a new exposure limit"


def test_stale_originator_version_rejected_then_fresh_succeeds(
        api, underwriter_headers):
    """PRD 2.7: "If the originator's current `version` has advanced since then —
    because another underwriting update or a risk-case resolution mutated the
    originator in between — the request is rejected with `ERR_STALE_VERSION`
    (HTTP 412), preventing the client from overwriting an originator record it
    has not observed."

    Design: Corner/complexity_layers/stale_originator_version_on_patch_returns_412
    """
    org = create_pending_originator("Occ Co", ["PPD"])
    stale_version = org["version"]

    approved = validate_success(api.patch_originator(
        org["id"],
        patch_originator_payload(stale_version, decision="APPROVE",
                                 exposure_limit_cents=5_000_000,
                                 fee_discount_bps=0),
        underwriter_headers), 200)
    assert_version_incremented(approved["version"], stale_version)

    res = api.patch_originator(
        org["id"],
        patch_originator_payload(stale_version, exposure_limit_cents=9_000_000),
        underwriter_headers)
    validate_error(res, ApiErrorId.ERR_STALE_VERSION, expected_status=412)

    current = read_originator(org["id"])
    updated = validate_success(api.patch_originator(
        org["id"],
        patch_originator_payload(current["version"],
                                 exposure_limit_cents=9_000_000),
        underwriter_headers), 200)
    assert updated["exposure_limit_cents"] == 9_000_000
    assert_version_incremented(updated["version"], current["version"])


def test_missing_auth_headers_rejected(api):
    """PRD 2.1: "A request whose headers are missing or malformed, or whose
    `X-User-Role` value is not one of these five declared roles, is rejected
    with `ERR_UNAUTHENTICATED`."

    Design: Corner/validations/missing_auth_headers_returns_unauthenticated
    """
    res = api.get_originator(NON_EXISTENT_UUID, headers={})
    validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401)
