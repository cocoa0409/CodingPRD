"""Authentication/authorization gates and optimistic-concurrency (OCC) version
checks."""
from test_helpers import (
    validate_success, validate_error, build_user_headers, fixtures,
)
from test_helpers.api_errors import ApiErrorId
from test_helpers.fixtures import LP, AD, PC


# --------------------------------------------------------------------------- #
# Corner/rbac/missing_headers_returns_unauthenticated
# --------------------------------------------------------------------------- #
def test_missing_headers_returns_unauthenticated(api):
    """PRD 2.1: "Every request to the API must carry two mandatory headers:
    X-User-ID, identifying the acting user, and X-User-Role, declaring the
    capacity in which they act. If either header is missing, or if X-User-Role is
    not one of the recognized roles, the request is rejected with
    ERR_UNAUTHENTICATED."

    Design: Corner/rbac/missing_headers_returns_unauthenticated
    """
    resp = api.create_production(
        {"title": "P", "production_type": "FEATURE", "total_budget_cents": 1_000_000}, {})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


# --------------------------------------------------------------------------- #
# Corner/rbac/firstad_cannot_create_production
# --------------------------------------------------------------------------- #
def test_firstad_cannot_create_production(api):
    """PRD 2.1: "When the headers are valid but the named role is not permitted to
    perform the requested operation under the access matrix, the request is
    rejected with ERR_FORBIDDEN." PRD 4: POST /productions is authorized for
    LineProducer only.

    Design: Corner/rbac/firstad_cannot_create_production
    """
    resp = api.create_production(
        {"title": "P", "production_type": "FEATURE", "total_budget_cents": 1_000_000}, AD)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


# --------------------------------------------------------------------------- #
# Corner/rbac/payroll_cannot_create_shooting_day
# --------------------------------------------------------------------------- #
def test_payroll_cannot_create_shooting_day(api):
    """PRD 2.1: "When the headers are valid but the named role is not permitted to
    perform the requested operation under the access matrix, the request is
    rejected with ERR_FORBIDDEN." PRD 4: POST /shooting-days is authorized for
    FirstAD only.

    Design: Corner/rbac/payroll_cannot_create_shooting_day
    """
    prod = fixtures.production_in_pre_production(total_budget_cents=1_000_000)
    resp = api.create_shooting_day(
        {"production_id": prod["id"], "shoot_date": "2026-10-08", "day_number": 1}, PC)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


# --------------------------------------------------------------------------- #
# Corner/rbac/unionrep_can_read_but_cannot_write
# --------------------------------------------------------------------------- #
def test_unionrep_cannot_write_residual_events(api):
    """PRD 2.1: "The UnionRep is a read-only audit role for union compliance and
    holds no mutating capability of any kind." PRD 4: POST /residual-events is
    authorized for PayrollCoordinator only.

    Design: Corner/rbac/unionrep_can_read_but_cannot_write
    """
    prod = fixtures.create_production(total_budget_cents=1_000_000)
    resp = api.create_residual_event(
        {"production_id": prod["id"], "market": "SVOD",
         "gross_receipts_cents": 1_000_000, "event_date": "2026-10-08"},
        fixtures.UR)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


# --------------------------------------------------------------------------- #
# Corner/cross_cutting_complexity_layers/occ_stale_shooting_day_version_on_assignment_create
# --------------------------------------------------------------------------- #
def test_occ_stale_shooting_day_version_on_assignment_create(api):
    """PRD 2.6: "if the supplied expected_shooting_day_version does not equal the
    day's current version, the booking is rejected with ERR_STALE_VERSION
    (HTTP 412)". PRD 3.4: "Creating it ... increments the shooting day's version."

    First create bumped the day version; a second create for a different crew
    member still carrying the pre-bump version => ERR_STALE_VERSION.

    Design: Corner/cross_cutting_complexity_layers/occ_stale_shooting_day_version_on_assignment_create
    """
    prod = fixtures.create_production(total_budget_cents=2_000_000)
    fixtures.create_budget_line(prod["id"], estimated_cents=1_000_000)
    c1 = fixtures.create_crew(prod["id"], full_name="C1", role_title="Grip",
                              daily_rate_cents=100_000, is_sag_aftra=False, union_code="NONE")
    c2 = fixtures.create_crew(prod["id"], full_name="C2", role_title="Grip",
                              daily_rate_cents=100_000, is_sag_aftra=False, union_code="NONE")
    fixtures.advance_production(prod["id"])
    day = fixtures.create_shooting_day(prod["id"], shoot_date="2026-10-10", day_number=1)
    fixtures.advance_production(prod["id"])
    observed_version = day["version"]
    fixtures.book_assignment(day["id"], c1["id"], observed_version,
                             call_time="2026-10-10T06:00:00.000Z")
    resp = api.create_assignment(
        {"shooting_day_id": day["id"], "crew_member_id": c2["id"],
         "call_time": "2026-10-10T06:00:00.000Z",
         "expected_shooting_day_version": observed_version}, AD)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)


# --------------------------------------------------------------------------- #
# Corner/cross_cutting_complexity_layers/occ_stale_production_version_on_post_actual
# --------------------------------------------------------------------------- #
def test_occ_stale_production_version_on_post_actual(api):
    """PRD 2.6: "a posting whose expected_production_version no longer equals the
    production's current version is rejected with ERR_STALE_VERSION (HTTP 412)".
    PRD 3.5: "Marking paid settles the money: the production's actual_cost_cents
    is increased".

    A mark-paid cascade bumps the production version; a post-actual carrying the
    stale early version => ERR_STALE_VERSION.

    Design: Corner/cross_cutting_complexity_layers/occ_stale_production_version_on_post_actual
    """
    prod = fixtures.create_production(total_budget_cents=2_000_000)
    prod_v_early = prod["version"]
    fixtures.create_budget_line(prod["id"], category="BELOW_THE_LINE_LABOR", estimated_cents=500_000)
    loc_line = fixtures.create_budget_line(prod["id"], category="LOCATIONS", estimated_cents=100_000)
    crew = fixtures.create_crew(prod["id"], daily_rate_cents=100_000,
                                is_sag_aftra=False, union_code="NONE")
    fixtures.advance_production(prod["id"])
    day = fixtures.create_shooting_day(prod["id"], shoot_date="2026-10-12", day_number=1)
    fixtures.advance_production(prod["id"])
    asg = fixtures.book_assignment(day["id"], crew["id"], day["version"],
                                   call_time="2026-10-12T06:00:00.000Z")
    cs = fixtures.create_call_sheet(day["id"], general_call_time="2026-10-12T06:00:00.000Z")
    validate_success(api.publish_call_sheet(cs["id"], AD))
    validate_success(api.start_shooting_day(day["id"], AD))
    validate_success(api.check_in_assignment(asg["id"], AD))
    validate_success(api.check_out_assignment(
        asg["id"], {"wrap_time": "2026-10-12T18:00:00.000Z", "meal_breaks_taken": 2}, AD))
    validate_success(api.approve_pay_assignment(asg["id"], PC))
    validate_success(api.mark_paid_assignment(asg["id"], PC))
    resp = api.post_actual(
        loc_line["id"], {"amount_cents": 5_000, "expected_production_version": prod_v_early}, LP)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)


# --------------------------------------------------------------------------- #
# Corner/cross_cutting_complexity_layers/post_actual_correct_production_version_succeeds
# --------------------------------------------------------------------------- #
def test_post_actual_correct_production_version_succeeds(api):
    """PRD 3.2: "A manual posting adds an amount_cents to a chosen budget line's
    actual_cents and recomputes that line's variance_cents". PRD 2.6: "Posting a
    manual actual to a budget line requires expected_production_version, which
    must carry the version of the owning production that the client last
    observed."

    A post-actual carrying the CURRENT production version succeeds (200) and sets
    actual_cents to 25000.

    Design: Corner/cross_cutting_complexity_layers/post_actual_correct_production_version_succeeds
    """
    prod = fixtures.create_production(total_budget_cents=1_000_000)
    prod_v = prod["version"]
    line = fixtures.create_budget_line(prod["id"], category="LOCATIONS", estimated_cents=100_000)
    updated = validate_success(api.post_actual(
        line["id"], {"amount_cents": 25_000, "expected_production_version": prod_v}, LP))
    assert updated["actual_cents"] == 25000, f"expected actual 25000, got {updated['actual_cents']}"


# Deleted test: test_committed_cost_reflects_actual_after_approve
# PRD-silence/contradiction category: NON-UNIQUE DERIVABILITY (formula contradiction).
# The test asserted that after approve-pay an APPROVED assignment contributes its
# paid_cost_cents (278500) to committed_cost_cents. PRD 3.5 (line 164) explicitly
# defines committed_cost_cents = sum(estimated_cost_cents for UNPAID|APPROVED) +
# sum(paid_cost_cents for PAID); an APPROVED assignment contributes its
# estimated_cost_cents (251000), not paid_cost_cents. A faithful PRD-only
# implementer following the explicit formula yields 251000, making this test fail.
# The test even quotes that formula in its own docstring while asserting the
# opposite. Scaffold rule:
# Corner/cross_cutting_complexity_layers/estimate_to_actual_reconciliation_delta_on_approve
