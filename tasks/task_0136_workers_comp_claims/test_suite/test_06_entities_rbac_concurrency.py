"""Entity CRUD corners, RBAC, separation of duties, and optimistic-concurrency:
the remaining breadth-coverage instances.
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    is_valid_uuid,
    setup_employer,
    setup_policy,
    setup_reported_claim,
    setup_lost_time_claim,
    setup_wage_statement,
    setup_reserve,
    setup_scheduled_ime,
    set_clock,
    make_employer_headers,
    make_claims_adjuster_headers,
    make_medical_reviewer_headers,
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
)
from test_helpers import factories as f

ADMIN = TEST_USERS["platform_admin_headers"]
ADJUSTER = TEST_USERS["claims_adjuster_headers"]
REVIEWER = TEST_USERS["medical_reviewer_headers"]


# ─── Entity corners ──────────────────────────────────

def test_create_employer_returns_201_with_defaults(api):
    """PRD §3.1: "A newly registered employer starts with open_claim_count at 0 and
    current_emr at 1.00; both are computed figures the employer never sets directly."
    PRD §2.4: "The id is a server-minted UUID with no type prefix ... The version field is an
    integer that begins at 1 on creation."

    Design: Corner/entities/create_employer_returns_201_with_defaults
    """
    emp = validate_success(api.create_employer(f.create_employer_payload(state_code="TX"), ADMIN), 201)
    assert emp["open_claim_count"] == 0
    assert emp["current_emr"] == 1.00
    assert is_valid_uuid(emp["id"]) and not emp["id"].startswith("emp_")
    assert emp["version"] == 1


def test_get_employer_not_found(api):
    """PRD §2.10: "a path whose parent does not exist is rejected with ERR_NOT_FOUND
    referencing that parent."

    Design: Corner/entities/get_employer_not_found_returns_404
    """
    resp = api.get_employer(NON_EXISTENT_UUID, ADMIN)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_create_worker_missing_required_field(api):
    """PRD §3.1: "A worker carries its employer_id, a full_name, the total gross_wages_cents
    earned over a wage base window, and the weeks_worked count over which those wages were
    earned (at least 1 and no more than 52)."

    Design: Corner/entities/create_worker_missing_required_field_returns_400
    """
    emp = setup_employer()
    resp = api.create_worker(
        {"employer_id": emp["id"], "full_name": "No Wage", "weeks_worked": 52}, ADMIN
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_worker_aww_computed_server_side(api):
    """PRD §3.1: "The moment a worker is created, the system computes its average weekly wage:
    average_weekly_wage_cents is the gross wages divided by the weeks worked, rounded half-up
    to whole cents."

    Design: Corner/entities/worker_aww_computed_input_ignored
    """
    emp = setup_employer()
    worker = validate_success(
        api.create_worker(f.create_worker_payload(emp["id"], gross_wages_cents=7_800_000, weeks_worked=52), ADMIN),
        201,
    )
    assert worker["average_weekly_wage_cents"] == 150000, "7800000/52"


def test_wage_statement_is_append_only_no_version(api):
    """PRD §2.4: "A wage statement is an append-only, immutable record: once filed it is never
    mutated, so it carries only id and created_at — it has no updated_at and no version field."
    PRD §3.5: "Filing computes the statement's ttd_weekly_rate_cents, the
    temporary-total-disability weekly compensation rate, through a capped-then-floored
    calculation."

    Design: Corner/entities/wage_statement_is_immutable_no_version_field
    """
    ctx = setup_reported_claim()
    ws, _ = setup_wage_statement(ctx["claim"]["id"], ctx["claim_version"], average_weekly_wage_cents=150_000)
    assert ws["ttd_weekly_rate_cents"] == 100005
    assert "created_at" in ws
    assert "version" not in ws, "WageStatement exposes no version field"


def test_policy_list_for_employer_returns_array(api):
    """PRD §2.3: "The meta object of a list response carries limit, offset, total_count, and
    has_more, where total_count is the full size of the underlying collection before paging
    and has_more indicates whether items remain beyond the current page."
    PRD §2.10: "an employer's policies, workers, and experience-mod entries are listed under
    the employer."

    Design: Corner/entities/policy_list_for_employer_returns_array
    """
    emp = setup_employer()
    policy = setup_policy(emp["id"])
    data, meta = validate_paginated(api.list_employer_policies(emp["id"], ADMIN))
    assert len(data) == 1 and data[0]["id"] == policy["id"]
    assert meta["total_count"] == 1
    assert meta["has_more"] is False


# ─── RBAC / SoD ──────────────────────────────────────

def test_employer_cannot_post_benefit_payment(api):
    """PRD §2.1: "A syntactically valid request whose role is not permitted to perform the
    requested operation under the access matrix in Section 4 is rejected with ERR_UNAUTHORIZED."

    Design: Corner/rbac/employer_cannot_post_benefit_payment
    """
    ctx = setup_lost_time_claim(disability_days=10, projected_weeks=12, average_weekly_wage_cents=150_000)
    employer_headers = make_employer_headers(ctx["employer"]["id"])
    resp = api.create_benefit_payment(f.create_benefit_payment_payload(ctx["claim"]["id"], "TTD"), employer_headers)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


def test_segregation_same_user_reserve_then_complete_ime(api):
    """PRD §2.9: "The system records the ClaimsAdjuster X-User-ID that created a claim's
    reserve. On that same claim, that recorded identifier may not be the MedicalReviewer who
    finalizes an impairment rating, and it may not be the operator who completes the IME order.
    Either collision is rejected with ERR_SEGREGATION_OF_DUTIES."

    Design: Corner/rbac/segregation_same_user_set_reserve_then_complete_ime
    """
    ctx = setup_reported_claim(disability_days=10)
    claim_id = ctx["claim"]["id"]
    # Same operator id "user-U" sets the reserve and later completes the IME.
    user_u_adjuster = make_claims_adjuster_headers("user-U")
    get_success_data(
        api.create_reserve(f.create_reserve_payload(claim_id, severity_tier="MODERATE", projected_weeks=12), user_u_adjuster)
    )
    ime = get_success_data(
        api.create_ime_order(
            f.create_ime_order_payload(claim_id, "2026-03-10T10:00:00Z", "2026-03-10T11:00:00Z", "Dr A"),
            user_u_adjuster,
        )
    )
    set_clock("2026-03-10T10:30:00Z")

    user_u_reviewer = make_medical_reviewer_headers("user-U")
    resp = api.complete_ime_order(ime["id"], user_u_reviewer)
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)


# ─── Optimistic concurrency ──────────────────────────

def test_stale_claim_version_on_wage_statement_rejected(api):
    """PRD §2.8: "If that value does not match the claim's current version — meaning another
    writer has advanced the claim since the client read it — the create is rejected with
    ERR_STALE_CLAIM_VERSION at HTTP 412, forcing the client to re-read before it overwrites a
    benefit basis it has not seen. A successful wage-statement filing itself increments the
    claim's version by one."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_claim_version_on_wage_statement_returns_412
    """
    ctx = setup_reported_claim()
    claim_id = ctx["claim"]["id"]
    v0 = ctx["claim_version"]
    # First wage statement at v0 advances the claim past v0.
    get_success_data(
        api.create_wage_statement(f.create_wage_statement_payload(claim_id, v0, average_weekly_wage_cents=150_000), ADJUSTER)
    )
    # Second wage statement re-using the now-stale v0 must be rejected.
    resp = api.create_wage_statement(
        f.create_wage_statement_payload(claim_id, v0, average_weekly_wage_cents=160_000), ADJUSTER
    )
    validate_error(resp, ApiErrorId.ERR_STALE_CLAIM_VERSION.value)


# ─── Authentication ──────────────────────────────────

def test_missing_auth_headers_returns_unauthenticated(api):
    """PRD §2.1: "A request that omits either header, or whose X-User-Role is not one of these
    four exact strings, is rejected with ERR_UNAUTHENTICATED."

    Design: Corner/errors/unauthenticated_missing_headers_returns_401
    """
    resp = api._request("POST", "/employers", f.create_employer_payload(), headers={"Content-Type": "application/json"})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)
