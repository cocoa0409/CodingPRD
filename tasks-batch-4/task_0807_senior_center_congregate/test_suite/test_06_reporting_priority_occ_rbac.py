"""OAA units-of-service reporting, cross-category validation precedence, optimistic
concurrency on finite pools, and role-based access control.

Translates queue A instances bp_oaa_report_zero_units_no_division,
pp_state_vs_fiscal_meal_closed_and_full, pp_temporal_vs_constraint_signup_closed_and_full,
plus queue B corner instances for the OAA split report, OCC stale versions, and RBAC.
"""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    make_participant_headers,
    fixtures,
    factories as F,
)

ADMIN = TEST_USERS["center_admin_headers"]
COORD = TEST_USERS["coordinator_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


# ---------------------------------------------------------------------------
# Queue B — calculations: OAA report grant/donation split + cost per unit
# ---------------------------------------------------------------------------
def test_oaa_report_splits_grant_and_donation_and_cost_per_unit(api):
    """PRD 3.8: "It returns `total_units` (the sum of those rows' `quantity`), `total_billable_cents` (the sum of their `billable_cents`), `grant_funded_cents` (the sum of their `grant_amount_cents`), `donation_funded_cents` (the sum of their `donation_amount_cents`), `unfunded_cents` (the sum of their `unfunded_amount_cents`), and `cost_per_unit_cents`. The cost per unit is the `total_billable_cents` divided by `total_units`, rounded half up to a whole cent".

    Design: Corner/calculations/corner_oaa_report_grant_and_donation_split_and_cost_per_unit
    """
    participant = fixtures.create_participant()
    grant = fixtures.create_active_grant(category="WELLNESS", authorized_cents=1000)
    donation = fixtures.create_donation(category="WELLNESS", amount_cents=5000)
    fixtures.fund_service(
        participant["id"], grant["id"], category="WELLNESS", quantity=2,
        donation_id=donation["id"], service_date="2026-03-06T00:00:00Z",
    )
    data = validate_success(
        api.oaa_units_report(
            AUDITOR,
            params={"category": "WELLNESS", "from": "2026-03-01T00:00:00Z", "to": "2026-03-31T23:59:59Z"},
        )
    )
    assert data["total_units"] == 2, f"expected 2, got {data['total_units']}"
    assert data["total_billable_cents"] == 3000, f"expected 3000, got {data['total_billable_cents']}"
    assert data["grant_funded_cents"] == 1000, f"expected 1000, got {data['grant_funded_cents']}"
    assert data["donation_funded_cents"] == 2000, f"expected 2000, got {data['donation_funded_cents']}"
    assert data["unfunded_cents"] == 0, f"expected 0, got {data['unfunded_cents']}"
    assert data["cost_per_unit_cents"] == 1500, f"round(3000/2)=1500, got {data['cost_per_unit_cents']}"


# ---------------------------------------------------------------------------
# Queue A — boundary_precision_check/bp_oaa_report_zero_units_no_division
# ---------------------------------------------------------------------------
def test_oaa_report_empty_set_no_division_by_zero(api):
    """PRD 3.8: "The cost per unit is the `total_billable_cents` divided by `total_units`, rounded half up to a whole cent; when `total_units` is 0 (an empty result set), `cost_per_unit_cents` is reported as 0 rather than dividing by zero."

    Design: Difficulty/boundary_precision_check/bp_oaa_report_zero_units_no_division
    """
    data = validate_success(
        api.oaa_units_report(
            AUDITOR,
            params={"category": "TRANSPORTATION", "from": "2026-03-01T00:00:00Z", "to": "2026-03-31T23:59:59Z"},
        )
    )
    assert data["total_units"] == 0, f"expected 0, got {data['total_units']}"
    assert data["total_billable_cents"] == 0, f"expected 0, got {data['total_billable_cents']}"
    assert data["cost_per_unit_cents"] == 0, f"empty set guards division, got {data['cost_per_unit_cents']}"


def test_oaa_report_empty_set_all_fund_totals_zero(api):
    """PRD 3.8: "It aggregates the funded-service rows in that `category` whose `status` is `APPLIED` and whose `service_date` falls within the window from `from` to `to` inclusive on both ends; reversed rows are excluded. It returns `total_units` (the sum of those rows' `quantity`), `total_billable_cents` (the sum of their `billable_cents`), `grant_funded_cents` (the sum of their `grant_amount_cents`), `donation_funded_cents` (the sum of their `donation_amount_cents`), `unfunded_cents` (the sum of their `unfunded_amount_cents`), and `cost_per_unit_cents`."

    Design: Difficulty/boundary_precision_check/bp_oaa_report_zero_units_no_division
    """
    data = validate_success(
        api.oaa_units_report(
            AUDITOR,
            params={"category": "TRANSPORTATION", "from": "2026-03-01T00:00:00Z", "to": "2026-03-31T23:59:59Z"},
        )
    )
    assert data["grant_funded_cents"] == 0, f"expected 0, got {data['grant_funded_cents']}"
    assert data["donation_funded_cents"] == 0, f"expected 0, got {data['donation_funded_cents']}"
    assert data["unfunded_cents"] == 0, f"expected 0, got {data['unfunded_cents']}"
    assert data["category"] == "TRANSPORTATION", f"report echoes the category, got {data['category']}"


# ---------------------------------------------------------------------------
# Queue A — priority_pair_validation_conflict/pp_state_vs_fiscal_meal_closed_and_full
# ---------------------------------------------------------------------------
def test_reserve_closed_and_full_day_returns_closed_over_capacity(api):
    """PRD 2.6: "5. **State** — the target resource is in a state that permits the transition (for example, a grant is `ACTIVE` before it can fund, a meal day is `OPEN` before it can take reservations, a participant is `ACTIVE` for self-service writes), else the applicable state error (HTTP 409)." PRD 3.6: "once a day is `CLOSED`, an attempt to reserve a seat on it is rejected with `ERR_SERVICE_DAY_CLOSED` (409)."

    Design: Difficulty/priority_pair_validation_conflict/pp_state_vs_fiscal_meal_closed_and_full
    """
    p1 = fixtures.create_participant()
    p2 = fixtures.create_participant()
    day = fixtures.create_meal_day(capacity=1)
    fixtures.reserve_meal(day["id"], p1["id"])  # day now full
    fixtures.close_meal_day(day["id"])  # and closed
    version = fixtures.day_version(day["id"])
    resp = api.create_reservation(
        F.create_reservation_payload(
            service_day_id=day["id"], participant_id=p2["id"],
            expected_service_day_version=version,
        ),
        COORD,
    )
    validate_error(resp, ApiErrorId.ERR_SERVICE_DAY_CLOSED.value)


def test_reserve_open_but_full_day_returns_capacity_exceeded(api):
    """PRD 3.6: "The day must have a free seat: if its `reserved_count` is already at or above its `capacity`, the reservation is rejected with `ERR_MEAL_CAPACITY_EXCEEDED` (409)."

    Design: Difficulty/priority_pair_validation_conflict/pp_state_vs_fiscal_meal_closed_and_full
    """
    p1 = fixtures.create_participant()
    p2 = fixtures.create_participant()
    day = fixtures.create_meal_day(capacity=1)
    fixtures.reserve_meal(day["id"], p1["id"])  # full but still OPEN
    version = fixtures.day_version(day["id"])
    resp = api.create_reservation(
        F.create_reservation_payload(
            service_day_id=day["id"], participant_id=p2["id"],
            expected_service_day_version=version,
        ),
        COORD,
    )
    validate_error(resp, ApiErrorId.ERR_MEAL_CAPACITY_EXCEEDED.value)


# ---------------------------------------------------------------------------
# Queue A — priority_pair_validation_conflict/pp_temporal_vs_constraint_signup_closed_and_full
# ---------------------------------------------------------------------------
def test_signup_past_start_and_full_returns_signup_closed(api):
    """PRD 2.6: "6. **Temporal validity** — time-window rules (HTTP 422). 7. **Business constraints** — capacity, overlap, and uniqueness rules (HTTP 409)". PRD 3.4: "a signup attempted at or after the session's `starts_at`, measured against the logical clock, is rejected with `ERR_SIGNUP_CLOSED` (422)."

    Design: Difficulty/priority_pair_validation_conflict/pp_temporal_vs_constraint_signup_closed_and_full
    """
    fixtures.set_clock("2026-03-01T00:00:00Z")
    p1 = fixtures.create_participant()
    p2 = fixtures.create_participant()
    room = fixtures.create_room(capacity=20)
    session = fixtures.create_session(
        room["id"], title="Tai Chi", starts_at="2026-03-10T10:00:00Z",
        ends_at="2026-03-10T11:00:00Z", capacity=1,
    )
    fixtures.create_signup(session["id"], p1["id"])  # session now full
    fixtures.set_clock("2026-03-10T10:30:00Z")  # clock past the session start
    resp = api.create_signup(
        F.create_signup_payload(session_id=session["id"], participant_id=p2["id"]),
        COORD,
    )
    validate_error(resp, ApiErrorId.ERR_SIGNUP_CLOSED.value)


def test_signup_full_before_start_returns_session_full(api):
    """PRD 3.4: "The session must have room: if its `enrolled_count` is already at or above its `capacity`, the signup is rejected with `ERR_SESSION_FULL` (409)."

    Design: Difficulty/priority_pair_validation_conflict/pp_temporal_vs_constraint_signup_closed_and_full
    """
    fixtures.set_clock("2026-03-01T00:00:00Z")
    p1 = fixtures.create_participant()
    p2 = fixtures.create_participant()
    room = fixtures.create_room(capacity=20)
    session = fixtures.create_session(
        room["id"], title="Tai Chi", starts_at="2026-03-10T10:00:00Z",
        ends_at="2026-03-10T11:00:00Z", capacity=1,
    )
    fixtures.create_signup(session["id"], p1["id"])  # full, but clock is still before start
    resp = api.create_signup(
        F.create_signup_payload(session_id=session["id"], participant_id=p2["id"]),
        COORD,
    )
    validate_error(resp, ApiErrorId.ERR_SESSION_FULL.value)


# ---------------------------------------------------------------------------
# Queue B — cross_cutting_complexity_layers: OCC stale versions
# ---------------------------------------------------------------------------
def test_funded_service_stale_grant_version_rejected(api):
    """PRD 2.5: "The create request must carry `expected_grant_award_version` equal to the target grant award's current `version`. If another funded-service creation has already drawn on the same grant and advanced its `version` since the client last read it, the client's view is stale and the create is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/corner_occ_stale_grant_version_conflict
    """
    participant = fixtures.create_participant()
    grant = fixtures.create_grant(category="WELLNESS", authorized_cents=2000)
    stale_version = grant["version"]  # captured at DRAFT creation
    fixtures.activate_grant(grant["id"])  # advances the version
    resp = api.create_funded_service(
        F.create_funded_service_payload(
            participant_id=participant["id"], category="WELLNESS", quantity=1,
            grant_award_id=grant["id"], expected_grant_award_version=stale_version,
        ),
        COORD,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)


def test_meal_reservation_stale_service_day_version_rejected(api):
    """PRD 2.5: "The create request must carry `expected_service_day_version` equal to the target meal service day's current `version`. If another reservation has already taken a seat and advanced the day's `version` since the client last read it, the create is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/corner_occ_stale_service_day_version_conflict
    """
    p1 = fixtures.create_participant()
    p2 = fixtures.create_participant()
    day = fixtures.create_meal_day(capacity=10)
    stale_version = day["version"]  # captured at create
    fixtures.reserve_meal(day["id"], p1["id"], expected_version=stale_version)  # advances the version
    resp = api.create_reservation(
        F.create_reservation_payload(
            service_day_id=day["id"], participant_id=p2["id"],
            expected_service_day_version=stale_version,
        ),
        COORD,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)


# ---------------------------------------------------------------------------
# Queue B — rbac
# ---------------------------------------------------------------------------
def test_participant_cannot_create_grant(api):
    """PRD 2.1: "When both headers are present and the role is recognized but that role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/corner_rbac_participant_cannot_create_grant
    """
    participant = fixtures.create_participant()
    resp = api.create_grant(
        F.create_grant_payload(title="Sneaky", oaa_title="IIIB", category="TRANSPORTATION", authorized_cents=100),
        make_participant_headers(participant["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


def test_missing_auth_headers_unauthenticated(api):
    """PRD 2.1: "If either header is missing, or if `X-User-Role` is not one of the four recognized roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/rbac/corner_rbac_missing_headers_unauthenticated
    """
    resp = api.create_participant(
        F.create_participant_payload(
            full_name="Anon", birth_date="1950-06-06T00:00:00Z", gender="MALE",
            ethnicity="NON_HISPANIC", race="BLACK", poverty_status="BELOW",
            lives_alone=False, rural=False, veteran=False,
        ),
        headers={},
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


def test_participant_cannot_reserve_for_another(api):
    """PRD 2.1: "For any self-service write — signing up for or cancelling an activity, reserving or cancelling a meal, or requesting a ride — the `participant_id` named in the request must equal `X-User-ID`; ownership checks compare the resource's participant foreign key to `X-User-ID`, and a mismatch is an `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/corner_rbac_participant_cannot_reserve_for_another
    """
    p1 = fixtures.create_participant()
    p2 = fixtures.create_participant()
    day = fixtures.create_meal_day(capacity=10)
    resp = api.create_reservation(
        F.create_reservation_payload(
            service_day_id=day["id"], participant_id=p2["id"],
            expected_service_day_version=day["version"],
        ),
        make_participant_headers(p1["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)
