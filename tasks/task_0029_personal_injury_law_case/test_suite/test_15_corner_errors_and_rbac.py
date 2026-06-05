"""Corner-design coverage — errors and rbac sections."""
import pytest

from test_helpers import (
    validate_error,
    validate_success,
    set_clock,
    register_client,
    sign_retainer,
    create_case,
    activate_case,
    register_provider,
    create_records_request,
    walk_records_request_to_reviewed,
    create_included_damages,
    create_demand_letter,
    send_demand_letter,
    create_lien,
    create_offer,
    accept_offer,
    get_case_version,
    ApiErrorId,
    api_client,
    accept_offer_payload,
    release_disbursement_payload,
    create_demand_letter_payload,
    make_attorney_headers,
    make_managing_partner_headers,
    make_paralegal_headers,
    setup_active_case_with_reviewed_records,
)


# ─── forbidden_role_on_demand_send_paralegal ────────────────────────


def test_paralegal_sending_demand_letter_returns_forbidden_role(api):
    """PRD §2.1: "A request that carries a role not authorized to invoke the
    requested endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD §3.4: "The active path is for a `ManagingPartner` to send it,
    advancing `DRAFT → SENT`."

    Design: Corner/errors/forbidden_role_on_demand_send_paralegal
    """
    set_clock("2026-01-01T00:00:00Z")
    client, case, provider, mrr = setup_active_case_with_reviewed_records()
    dl = create_demand_letter(case["id"], pain_multiplier=1.5,
                               drafter_user_id="drafter-fr")
    # Try sending as Paralegal.
    res = api_client.send_demand_letter(dl["id"], make_paralegal_headers())
    validate_error(res, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


# ─── missing_auth_header_returns_401 ────────────────────────────────


def test_get_cases_without_user_role_header_returns_missing_auth(api):
    """PRD §2.1: "A request that omits `X-User-Role` on any non-public
    endpoint is rejected with `ERR_MISSING_AUTH` (HTTP 401)."
    PRD §2.1: "Two endpoints — client self-registration and the
    test-driving clock setter — are public in the sense that they do not
    require `X-User-Role`; every other endpoint does."

    Design: Corner/errors/missing_auth_header_returns_401
    """
    set_clock("2026-01-01T00:00:00Z")
    # No headers at all.
    res = api.list_cases({}, params=None)
    validate_error(res, ApiErrorId.ERR_MISSING_AUTH.value)


# ─── attorney_cannot_release_disbursement ───────────────────────────


def test_attorney_releasing_disbursement_returns_forbidden_role(api):
    """PRD §2.1: "A request that carries a role not authorized to invoke the
    requested endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD §3.7: "A pending disbursement waits for the `ManagingPartner` to
    release it."

    Design: Corner/rbac/attorney_cannot_release_disbursement
    """
    from test_helpers import TEST_USERS, get_disbursement_for_case
    set_clock("2026-01-01T00:00:00Z")
    client, case, provider, mrr = setup_active_case_with_reviewed_records()
    create_included_damages(case["id"], "MEDICAL_BILLS", 1_000_000)
    dl = create_demand_letter(case["id"], pain_multiplier=1.5,
                               drafter_user_id="drafter-dr")
    send_demand_letter(dl["id"], partner_user_id="partner-dr")
    create_lien(case["id"], provider["id"], 500_000)
    offer = create_offer(case["id"], 6_000_000, "CARRIER")
    case_v = get_case_version(case["id"])
    accept_offer(offer["id"], case_v, partner_user_id="partner-dr")
    disb = get_disbursement_for_case(case["id"])
    case_v2 = get_case_version(case["id"])
    # Try release as Attorney (only ManagingPartner is permitted).
    res = api_client.release_disbursement(
        disb["id"], release_disbursement_payload(case_v2),
        make_attorney_headers(),
    )
    validate_error(res, ApiErrorId.ERR_FORBIDDEN_ROLE.value)
    disb_after = validate_success(
        api.get_disbursement(disb["id"], TEST_USERS["attorney_headers"]), 200
    )
    assert disb_after["status"] == "PENDING"


# ─── paralegal_cannot_activate_case ─────────────────────────────────


def test_paralegal_activating_case_returns_forbidden_role(api):
    """PRD §2.1: "A request that carries a role not authorized to invoke the
    requested endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD §3.1: "The case sits in `INTAKE` until an `Attorney` activates it,
    at which point it moves `INTAKE → ACTIVE`."

    Design: Corner/rbac/paralegal_cannot_activate_case
    """
    set_clock("2026-01-01T00:00:00Z")
    client = register_client()
    sign_retainer(client["id"])
    case = create_case(client["id"], accident_date="2024-06-15",
                        jurisdiction="CA")
    res = api_client.activate_case(case["id"], make_paralegal_headers())
    validate_error(res, ApiErrorId.ERR_FORBIDDEN_ROLE.value)
    from test_helpers import get_case
    case_after = get_case(case["id"])
    assert case_after["status"] == "INTAKE"
