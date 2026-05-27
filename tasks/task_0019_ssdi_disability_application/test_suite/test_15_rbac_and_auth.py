"""Role-based access control and authentication: missing-headers 401, role
denial 403, peer-role boundary."""
import pytest
from test_helpers import (
    validate_error, get_success_data, api_client, TEST_USERS,
    set_clock,
    create_claimant,
    setup_hearing_in_requested,
    create_claimant_payload, create_work_credit_payload,
    schedule_hearing_payload,
    make_headers, make_claimant_headers, make_unauthenticated_headers,
)


# =========================================================================
# Instance: error_unauthenticated_missing_headers
# =========================================================================

def test_request_without_headers_returns_unauthenticated(api):
    """PRD §2.1: "Every request to the API must carry two mandatory
    headers: `X-User-ID` identifies the acting user, and `X-User-Role`
    declares the role under which the call is being made. A request
    missing either header is rejected with `ERR_UNAUTHENTICATED` (401)."

    Design: Corner/errors/error_unauthenticated_missing_headers
    """
    set_clock("2026-01-15T00:00:00Z")
    res = api_client.list_claimants(make_unauthenticated_headers())
    validate_error(res, "ERR_UNAUTHENTICATED", expected_status=401)


# =========================================================================
# Instance: error_forbidden_role_not_permitted
# =========================================================================

def test_claimant_cannot_post_work_credits_returns_forbidden(api):
    """PRD §2.1: "A request whose declared role is not authorised for the
    requested endpoint (per the per-endpoint allow-list in §4) is rejected
    with `ERR_FORBIDDEN` (403)."
    PRD §4: "`POST /ssdi/work-credits` | Post a year's work credits for a
    claimant | `SSAAdmin`"

    Design: Corner/errors/error_forbidden_role_not_permitted
    """
    set_clock("2026-01-15T00:00:00Z")
    c = create_claimant(ssn_last4="5001", full_name="Forbid",
                        date_of_birth="1980-01-01T00:00:00Z", filing_state="TX")
    # Claimant tries to post a WorkCreditRecord (SSAAdmin-only).
    payload = create_work_credit_payload(c["id"], 2020, credits_earned=4,
                                          earnings_cents=4_800_000)
    res = api_client.create_work_credit(payload, make_claimant_headers(c["id"]))
    validate_error(res, "ERR_FORBIDDEN", expected_status=403)


# =========================================================================
# Instance: alj_cannot_create_claimant
# =========================================================================

def test_alj_cannot_create_claimant_returns_forbidden(api, alj_headers):
    """PRD §4: "`POST /ssdi/claimants` | Register a new claimant |
    `Claimant, SSAAdmin`"
    PRD §2.1: "A request whose declared role is not authorised for the
    requested endpoint (per the per-endpoint allow-list in §4) is rejected
    with `ERR_FORBIDDEN` (403)."

    Design: Corner/rbac/alj_cannot_create_claimant
    """
    set_clock("2026-01-15T00:00:00Z")
    payload = create_claimant_payload(
        ssn_last4="6001",
        full_name="ALJ Try",
        date_of_birth="1980-01-01T00:00:00Z",
        filing_state="TX",
    )
    res = api_client.create_claimant(payload, alj_headers)
    validate_error(res, "ERR_FORBIDDEN", expected_status=403)


# =========================================================================
# Instance: ddsexaminer_cannot_schedule_hearing
# =========================================================================

def test_dds_examiner_cannot_schedule_hearing_returns_forbidden(api):
    """PRD §4: "`POST /ssdi/hearings/{id}/schedule` | ALJ schedules a
    requested hearing | `ALJ`"
    PRD §2.1: "The five roles are peers: the system does not arrange them
    into a strict hierarchy, and an operation that is exclusive to one
    role is not implicitly inherited by any other."

    Design: Corner/rbac/ddsexaminer_cannot_schedule_hearing
    """
    set_clock("2026-01-15T00:00:00Z")
    ctx = setup_hearing_in_requested(
        claimant_overrides={
            "ssn_last4": "6002",
            "full_name": "Dds Try",
            "date_of_birth": "1980-01-01T00:00:00Z",
            "filing_state": "TX",
        },
    )
    hearing = ctx["hearing"]
    payload = schedule_hearing_payload("2026-06-01T00:00:00Z")
    res = api_client.schedule_hearing(hearing["id"], payload, TEST_USERS["dds_examiner_headers"])
    validate_error(res, "ERR_FORBIDDEN", expected_status=403)
