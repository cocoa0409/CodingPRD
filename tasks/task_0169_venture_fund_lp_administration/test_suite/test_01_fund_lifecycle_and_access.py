"""Fund creation, lifecycle steering, listing, access control, and existence
guards. Covers corner queue entities/state_machines/errors/rbac instances plus
the cross-entity fund-activation dependency from the difficulty queue.
"""
import pytest

from test_helpers import (
    api_client as _ac,  # noqa: F401
    validate_success, validate_error, validate_paginated,
    TEST_USERS, make_limited_partner_headers,
    create_fund_payload, create_limited_partner_payload, create_commitment_payload,
    assert_fund,
)
from test_helpers import fixtures as fx

FM = TEST_USERS["fund_manager_headers"]
FA = TEST_USERS["fund_administrator_headers"]
CO = TEST_USERS["compliance_officer_headers"]
NONEXISTENT = "00000000-0000-4000-8000-000000000000"


# ---------------------------------------------------------------------------
# Fund creation
# ---------------------------------------------------------------------------

def test_create_fund_returns_201_forming_version_1(api):
    """PRD §3.1: "The newly created fund begins in `FORMING` status with `version` `1`."

    Design: Corner/entities/create_fund_returns_201_with_system_fields
    """
    resp = api.create_fund(create_fund_payload(name="Greenfield Fund"), FM)
    data = validate_success(resp, 201)
    assert_fund(data)
    assert data["status"] == "FORMING"
    assert data["version"] == 1


def test_create_fund_default_gp_catchup_applied(api):
    """PRD §3.1: "`gp_catchup_rate_bps`, the GP's catch-up share applied in the waterfall and defaulting to `10000` (a full one-hundred-percent catch-up)".

    Design: Corner/entities/create_fund_default_gp_catchup_applied
    """
    payload = create_fund_payload(name="Default Catchup Fund")
    assert "gp_catchup_rate_bps" not in payload
    data = validate_success(api.create_fund(payload, FM), 201)
    assert data["gp_catchup_rate_bps"] == 10000


def test_create_fund_missing_required_field_rejected(api):
    """PRD §2.8: "the request body checked for the presence of required fields, correct types, and valid enum members, with a violation yielding `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/create_fund_missing_required_field_returns_invalid_request
    """
    payload = create_fund_payload(name="Incomplete Fund")
    payload.pop("carry_rate_bps")
    validate_error(api.create_fund(payload, FM), "ERR_INVALID_REQUEST", 400)


def test_create_fund_carry_rate_out_of_range_rejected(api):
    """PRD §2.8: "A numeric input that is present and well-typed but outside its declared range — for example a `carry_rate_bps` above `5000`, an `ownership_pct_bps` above `10000`, or any negative cents amount — is rejected with `ERR_VALIDATION_LIMIT` (HTTP 422)."

    Design: Corner/entities/create_fund_invalid_enum_carry_out_of_range
    """
    payload = create_fund_payload(name="BadCarry Fund", carry_rate_bps=6000)
    validate_error(api.create_fund(payload, FM), "ERR_VALIDATION_LIMIT", 422)


def test_fund_total_committed_is_computed_from_active_commitments(api):
    """PRD §2.6: "`total_committed_cents` is the sum of `committed_cents` across every `Commitment` on the fund whose `status` is `ACTIVE` or `DEFAULTED`."

    Design: Corner/entities/fund_computed_totals_ignore_input
    """
    fund = fx.create_fund(name="Totals Fund", target_size_cents=6_000_000)
    lp = fx.create_lp(legal_name="LP CF", tax_id_last4="1212")
    fx.create_accepted_commitment(fund["id"], lp["id"], 6_000_000)
    data = validate_success(api.get_fund(fund["id"], FM), 200)
    assert data["total_committed_cents"] == 6_000_000


# ---------------------------------------------------------------------------
# Listing / pagination
# ---------------------------------------------------------------------------

def test_list_funds_paginated_envelope(api):
    """PRD §2.3: "List responses surface `limit`, `offset`, `total_count`, and `has_more` in the `meta` block, where `total_count` is the number of records matching the query before the page window is applied and `has_more` indicates whether records remain beyond the current window."

    Design: Corner/entities/list_funds_pagination_envelope
    """
    fx.create_fund(name="Page Fund A", target_size_cents=1_000_000)
    fx.create_fund(name="Page Fund B", target_size_cents=1_000_000)
    data, meta = validate_paginated(api.list_funds(FM, params={"limit": 1, "offset": 0}))
    assert len(data) == 1
    assert meta["total_count"] == 2
    assert meta["has_more"] is True


def test_pagination_invalid_limit_rejected(api):
    """PRD §2.3: "A request whose `limit` or `offset` falls outside these bounds is rejected with `ERR_PAGINATION_INVALID` (HTTP 400)."

    Design: Corner/errors/pagination_invalid_limit_rejected
    """
    validate_error(api.list_funds(FM, params={"limit": 500, "offset": 0}),
                   "ERR_PAGINATION_INVALID", 400)


# ---------------------------------------------------------------------------
# Existence / reference guards
# ---------------------------------------------------------------------------

def test_get_fund_not_found(api):
    """PRD §2.8: "every resource named in the path and every foreign key referenced in the body is resolved left-to-right; if any does not exist, the request fails with `ERR_RESOURCE_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/get_fund_not_found_returns_404
    """
    validate_error(api.get_fund(NONEXISTENT, FM), "ERR_RESOURCE_NOT_FOUND", 404)


# ---------------------------------------------------------------------------
# Fund lifecycle transitions
# ---------------------------------------------------------------------------

def test_activate_requires_active_commitment_then_succeeds(api):
    """PRD §3.1: "Activation moves the fund from `FORMING` to `INVESTING`, but only once at least one `Commitment` on the fund has reached `ACTIVE` status; an attempt to activate a fund with no accepted commitment is rejected with `ERR_COMMITMENT_NOT_ACCEPTED` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/fund_activate_requires_active_commitment
    """
    fund = fx.create_fund(name="Activate Fund", target_size_cents=6_000_000)
    lp = fx.create_lp(legal_name="LP S", tax_id_last4="9013")
    commitment = fx.create_pending_commitment(fund["id"], lp["id"], 6_000_000)
    # PENDING commitment -> activation blocked.
    validate_error(api.activate_fund(fund["id"], FM), "ERR_COMMITMENT_NOT_ACCEPTED", 409)
    # Accept the commitment, then activation succeeds.
    api.accept_commitment(commitment["id"], FM)
    data = validate_success(api.activate_fund(fund["id"], FM), 200)
    assert data["status"] == "INVESTING"


def test_activate_fund_with_only_pending_commitment_blocked(api):
    """PRD §3.1: "an attempt to activate a fund with no accepted commitment is rejected with `ERR_COMMITMENT_NOT_ACCEPTED` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/fund_activate_requires_active_commitment
    """
    fund = fx.create_fund(name="Pending Only Fund", target_size_cents=6_000_000)
    lp = fx.create_lp(legal_name="LP S2", tax_id_last4="9023")
    fx.create_pending_commitment(fund["id"], lp["id"], 6_000_000)
    validate_error(api.activate_fund(fund["id"], FM), "ERR_COMMITMENT_NOT_ACCEPTED", 409)


def test_wind_down_blocked_by_active_investment(api):
    """PRD §3.1: "it is permitted only when no `CapitalCall` on the fund is still in `ISSUED` status and no `Investment` on the fund is still `ACTIVE`. If either condition fails — an outstanding issued call or a still-active investment — the wind-down is blocked with `ERR_WIND_DOWN_BLOCKED` (HTTP 409)."

    Design: Corner/state_machines/wind_down_blocked_by_active_investment
    """
    fund = fx.create_fund(name="WindDown Fund", target_size_cents=5_000_000)
    lp = fx.create_lp(legal_name="LP WD", tax_id_last4="1515")
    fx.create_accepted_commitment(fund["id"], lp["id"], 5_000_000)
    api.activate_fund(fund["id"], FM)
    fx.create_investment(fund["id"], cost_basis_cents=3_000_000, company_name="Kappa", sector="Logistics")
    api.begin_harvest_fund(fund["id"], FM)
    validate_error(api.wind_down_fund(fund["id"], FM), "ERR_WIND_DOWN_BLOCKED", 409)


def test_wind_down_cascade_closes_active_commitments(api):
    """PRD §3.1: "When wind-down does succeed, every `Commitment` on the fund still in `ACTIVE` status is cascaded to `CLOSED`, and the fund's `version` increments by one."

    Design: Corner/state_machines/wind_down_cascade_closes_active_commitments
    """
    fund = fx.create_fund(name="Cascade Close Fund", target_size_cents=5_000_000)
    lp = fx.create_lp(legal_name="LP WC", tax_id_last4="1717")
    commitment = fx.create_accepted_commitment(fund["id"], lp["id"], 5_000_000)
    api.activate_fund(fund["id"], FM)
    api.begin_harvest_fund(fund["id"], FM)
    data = validate_success(api.wind_down_fund(fund["id"], FM), 200)
    assert data["status"] == "WOUND_DOWN"
    closed = validate_success(api.get_commitment(commitment["id"], FM), 200)
    assert closed["status"] == "CLOSED"


def test_terminal_wound_down_fund_rejects_activate(api):
    """PRD §2.8: "For any operation that drives a state machine, the target resource must currently be in a state from which the requested transition is defined; otherwise the request fails with `ERR_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/terminal_wound_down_fund_rejects_activate
    """
    fund = fx.create_fund(name="Terminal Fund", target_size_cents=5_000_000)
    lp = fx.create_lp(legal_name="LP TM", tax_id_last4="1616")
    fx.create_accepted_commitment(fund["id"], lp["id"], 5_000_000)
    api.activate_fund(fund["id"], FM)
    api.begin_harvest_fund(fund["id"], FM)
    api.wind_down_fund(fund["id"], FM)
    validate_error(api.activate_fund(fund["id"], FM), "ERR_INVALID_STATE", 409)


# ---------------------------------------------------------------------------
# Commitment lifecycle
# ---------------------------------------------------------------------------

def test_new_commitment_starts_pending(api):
    """PRD §3.2: "A commitment is born in `PENDING` status."

    Design: Corner/state_machines/commitment_starts_pending
    """
    fund = fx.create_fund(name="Init Fund", target_size_cents=5_000_000)
    lp = fx.create_lp(legal_name="LP IS", tax_id_last4="1313")
    data = validate_success(
        api.create_commitment(
            create_commitment_payload(fund["id"], lp["id"], committed_cents=5_000_000), FM), 201)
    assert data["status"] == "PENDING"


def test_accept_already_active_commitment_rejected(api):
    """PRD §2.8: "For any operation that drives a state machine, the target resource must currently be in a state from which the requested transition is defined; otherwise the request fails with `ERR_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/accept_already_active_commitment_returns_invalid_state
    """
    fund = fx.create_fund(name="AA Fund", target_size_cents=5_000_000)
    lp = fx.create_lp(legal_name="LP AA", tax_id_last4="1414")
    commitment = fx.create_accepted_commitment(fund["id"], lp["id"], 5_000_000)
    validate_error(api.accept_commitment(commitment["id"], FM), "ERR_INVALID_STATE", 409)


# ---------------------------------------------------------------------------
# RBAC
# ---------------------------------------------------------------------------

def test_limited_partner_cannot_create_fund(api):
    """PRD §2.1: "If the headers are well-formed but the named role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Design: Corner/rbac/limited_partner_cannot_create_fund
    """
    lp = fx.create_lp(legal_name="LP RB", tax_id_last4="3737")
    headers = make_limited_partner_headers(lp["id"])
    validate_error(api.create_fund(create_fund_payload(name="Forbidden Fund"), headers),
                   "ERR_FORBIDDEN_ROLE", 403)


def test_missing_auth_headers_rejected(api):
    """PRD §2.1: "If either header is missing or malformed, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401) before any other processing occurs."

    Design: Corner/rbac/missing_auth_headers_rejected
    """
    resp = api.list_funds({"Content-Type": "application/json"})
    validate_error(resp, "ERR_UNAUTHENTICATED", 401)


def test_compliance_officer_cannot_finalize_mark(api):
    """PRD §2.1: "If the headers are well-formed but the named role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Design: Corner/rbac/compliance_officer_cannot_finalize_mark
    """
    fund = fx.create_fund(name="ComplianceMark Fund", target_size_cents=5_000_000)
    inv, _ = fx.create_investment(fund["id"], cost_basis_cents=3_000_000,
                                  company_name="Pi", sector="Telco")
    draft = validate_success(
        api.create_valuation_mark(
            {"investment_id": inv["id"], "as_of_date": "2024-06-30T00:00:00Z",
             "fair_value_cents": 3_500_000, "methodology": "DCF"}, FA), 201)
    validate_error(api.finalize_valuation_mark(draft["id"], CO), "ERR_FORBIDDEN_ROLE", 403)


def test_lp_cannot_read_other_lp_statement(api):
    """PRD §2.1: "when a `LimitedPartnerUser` requests a commitment's statement or funds a capital-call allocation, the system resolves the targeted `Commitment` (directly, or through the allocation's `commitment_id`) and confirms that the commitment's `lp_id` equals the caller's `X-User-ID`. If it does not, the request is rejected with `ERR_NOT_COMMITMENT_OWNER` (HTTP 403)."

    Design: Corner/rbac/lp_cannot_read_other_lp_statement
    """
    fund = fx.create_fund(name="Owner Fund", target_size_cents=10_000_000)
    lp1 = fx.create_lp(legal_name="LP OW1", tax_id_last4="3838")
    lp2 = fx.create_lp(legal_name="LP OW2", tax_id_last4="3939")
    commitment2 = fx.create_accepted_commitment(fund["id"], lp2["id"], 4_000_000)
    headers_lp1 = make_limited_partner_headers(lp1["id"])
    validate_error(api.get_commitment_statement(commitment2["id"], headers_lp1),
                   "ERR_NOT_COMMITMENT_OWNER", 403)
