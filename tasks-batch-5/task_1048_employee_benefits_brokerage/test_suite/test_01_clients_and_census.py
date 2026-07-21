"""Client onboarding, the workforce census, computed headcounts, and listing."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS,
    create_client_payload, create_census_member_payload,
)
from test_helpers import fixtures as fx

CONSULTANT = TEST_USERS["consultant_headers"]


# ===========================================================================
# Corner / entities
# ===========================================================================
def test_create_client_initializes_computed_ledgers_to_zero(api):
    """PRD §3.1: "On success the client's computed figures — full_time_equivalent_count,
    employee_count, is_ale, enrolled_headcount, active_premium_total_cents, and
    ytd_commission_cents — all begin at their zero/false values."
    PRD §2.4: "version starts at 1 and increments by one on every mutation of that resource."

    Design: Corner/entities/create_client_success_and_envelope
    """
    resp = api.create_client(create_client_payload(legal_name="Envelope Co"), CONSULTANT)
    body = resp.json()
    assert body["response_type"] == "object", "single-resource create must be object envelope"
    data = validate_success(resp, 201)
    assert data["employee_count"] == 0
    assert data["full_time_equivalent_count"] == 0
    assert data["is_ale"] is False
    assert data["active_premium_total_cents"] == 0
    assert data["enrolled_headcount"] == 0
    assert data["ytd_commission_cents"] == 0
    assert data["version"] == 1


def test_get_client_unknown_id_not_found(api):
    """PRD §2.4: "if any id in the path — or any foreign-key id supplied in a request
    body — does not reference an existing row, the request is rejected with
    ERR_NOT_FOUND (HTTP 404)."

    Design: Corner/entities/get_client_not_found
    """
    resp = api.get_client("00000000-0000-0000-0000-000000000000", CONSULTANT)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_create_client_missing_ein_rejected(api):
    """PRD §2.7: "any required field being absent is itself a field-shape violation."
    PRD §2.7: "Field shape — field-shape constraints hold; otherwise ERR_INVALID_FIELD (422)."

    Design: Corner/entities/create_client_missing_required_field_rejected
    """
    payload = {"legal_name": "No EIN Co", "industry": "TECH", "fiscal_year_end_month": 12}
    resp = api.create_client(payload, CONSULTANT)
    validate_error(resp, ApiErrorId.ERR_INVALID_FIELD.value)


def test_create_client_duplicate_ein_rejected(api):
    """PRD §3.1: "A create whose ein duplicates an existing client's is rejected with
    ERR_DUPLICATE_EIN."

    Design: Corner/entities/create_client_duplicate_ein_rejected
    """
    validate_success(api.create_client(
        create_client_payload(legal_name="First Co", ein="200000002"), CONSULTANT), 201)
    resp = api.create_client(
        create_client_payload(legal_name="Dup Co", ein="200000002", industry="RETAIL",
                              fiscal_year_end_month=6), CONSULTANT)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_EIN.value)


def test_census_member_begins_active(api):
    """PRD §3.1: "Every member begins with status of ACTIVE; the only lifecycle
    transition is ACTIVE → TERMINATED, performed when the consultant terminates the member."

    Design: Corner/entities/census_system_field_input_ignored
    """
    client = fx.create_client(legal_name="Ignore Co")
    resp = api.create_census_member(
        create_census_member_payload(client["id"], full_name="New Hire",
                                      annual_salary_cents=4_000_000,
                                      monthly_contribution_cents=15_000), CONSULTANT)
    data = validate_success(resp, 201)
    assert data["status"] == "ACTIVE"


def test_fte_and_ale_below_threshold(api):
    """PRD §3.1: "employee_count is the number of that client's members whose status is
    ACTIVE. full_time_equivalent_count is the number of that client's members whose status
    is ACTIVE and whose employment_type is FULL_TIME. The client's is_ale (Applicable Large
    Employer) flag is true exactly when full_time_equivalent_count is at least 50."

    Design: Corner/entities/fte_and_ale_computed_below_threshold
    """
    client = fx.create_client(legal_name="Small Co", industry="RETAIL")
    fx.create_member(client["id"], full_name="A", annual_salary_cents=4_000_000,
                     monthly_contribution_cents=15_000, employment_type="FULL_TIME")
    fx.create_member(client["id"], full_name="B", annual_salary_cents=4_000_000,
                     monthly_contribution_cents=15_000, employment_type="FULL_TIME")
    data = validate_success(api.get_client(client["id"], CONSULTANT))
    assert data["employee_count"] == 2
    assert data["full_time_equivalent_count"] == 2
    assert data["is_ale"] is False


# ===========================================================================
# Corner / cross_cutting — census terminate recomputes counts
# ===========================================================================
def test_terminate_member_recomputes_client_counts(api):
    """PRD §3.1: "Terminating a member sets that member's status to TERMINATED, then
    decrements employee_count, recomputes full_time_equivalent_count if the terminated
    member was FULL_TIME, and recomputes is_ale from the new full-time-equivalent count."

    Design: Corner/cross_cutting_complexity_layers/census_terminate_recomputes_client_counts
    """
    client = fx.create_client(legal_name="Recompute Co")
    fx.create_member(client["id"], full_name="Keep", annual_salary_cents=4_000_000,
                     monthly_contribution_cents=15_000, employment_type="FULL_TIME")
    drop = fx.create_member(client["id"], full_name="Drop", annual_salary_cents=4_000_000,
                            monthly_contribution_cents=15_000, employment_type="FULL_TIME")
    term = validate_success(api.terminate_census_member(drop["id"], CONSULTANT))
    assert term["status"] == "TERMINATED"
    data = validate_success(api.get_client(client["id"], CONSULTANT))
    assert data["employee_count"] == 1
    assert data["full_time_equivalent_count"] == 1


# ===========================================================================
# Corner / endpoints — listing & pagination
# ===========================================================================
def test_list_clients_pagination_meta(api):
    """PRD §2.3: "The meta block of a list response carries the pagination fields limit,
    offset, total_count, and has_more, where total_count is the number of records matching
    the query before pagination is applied and has_more is true when records remain beyond
    the current page."

    Design: Corner/endpoints/list_clients_pagination
    """
    fx.create_client(legal_name="Page One")
    fx.create_client(legal_name="Page Two")
    resp = api.list_clients(CONSULTANT, params={"limit": 1, "offset": 0})
    data, meta = validate_paginated(resp)
    assert len(data) == 1
    assert meta["total_count"] == 2
    assert meta["has_more"] is True


def test_list_census_members_by_client_fk(api):
    """PRD §2.3: "Several list endpoints additionally accept reverse-reachability filters
    that narrow the result to children of a given parent. These are: client_id on the
    census-member, campaign, policy, enrollment-window, filing, and stop-loss lists".

    Design: Corner/endpoints/list_census_members_by_client_fk
    """
    client = fx.create_client(legal_name="FK Co")
    member = fx.create_member(client["id"], full_name="Only Member",
                              annual_salary_cents=4_000_000,
                              monthly_contribution_cents=15_000,
                              employment_type="PART_TIME")
    resp = api.list_census_members(CONSULTANT, params={"client_id": client["id"]})
    data, _ = validate_paginated(resp)
    assert [m["id"] for m in data] == [member["id"]]


# ===========================================================================
# Difficulty / dual_variant_calc — ACA affordability rate-of-pay vs FPL
# ===========================================================================
def test_affordability_rate_of_pay_true(api):
    """PRD §3.1: "a rate-of-pay threshold is computed as 9.12% (the affordability
    percentage, 0.0912) of one-twelfth of the member's annual_salary_cents, rounded
    half-up to whole cents; the member's affordable_rate_of_pay is true exactly when
    monthly_contribution_cents is less than or equal to that threshold."

    Design: Difficulty/dual_variant_calc/affordability_rate_of_pay_vs_fpl_on_census_member
    """
    client = fx.create_client(legal_name="Beta Co", industry="RETAIL", fiscal_year_end_month=6)
    data = validate_success(api.create_census_member(
        create_census_member_payload(client["id"], full_name="Pat Lee",
                                      annual_salary_cents=6_000_000,
                                      monthly_contribution_cents=30_000,
                                      employment_type="FULL_TIME"), CONSULTANT), 201)
    assert data["affordable_rate_of_pay"] is True


def test_affordability_fpl_false_disagrees_with_rate_of_pay(api):
    """PRD §3.1: "a federal-poverty-line threshold is computed as 9.12% of one-twelfth of
    the fixed federal-poverty-line annual figure of 1,506,000 cents (that is, $15,060 per
    year), rounded half-up to whole cents; the member's affordable_fpl is true exactly when
    monthly_contribution_cents is less than or equal to that threshold."

    Design: Difficulty/dual_variant_calc/affordability_rate_of_pay_vs_fpl_on_census_member
    """
    client = fx.create_client(legal_name="Beta Co", industry="RETAIL", fiscal_year_end_month=6)
    data = validate_success(api.create_census_member(
        create_census_member_payload(client["id"], full_name="Pat Lee",
                                      annual_salary_cents=6_000_000,
                                      monthly_contribution_cents=30_000,
                                      employment_type="FULL_TIME"), CONSULTANT), 201)
    assert data["affordable_fpl"] is False
    assert data["affordable_rate_of_pay"] != data["affordable_fpl"]
