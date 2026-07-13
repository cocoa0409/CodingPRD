"""Participant registration, demographics defaults, deactivation cascade, and the
monthly voluntary-contribution statement.

Translates queue A (Difficulty) instances tc_participant_deactivate_frees_meal_seats
and cf_contribution_statement_per_meal_rounding, plus queue B (Corner) entity
instances for participant creation, required fields, and defaults.
"""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    make_participant_headers,
    assert_participant,
    assert_meal_seat_conservation,
    fixtures,
    factories as F,
)

ADMIN = TEST_USERS["center_admin_headers"]
COORD = TEST_USERS["coordinator_headers"]


# ---------------------------------------------------------------------------
# Queue B — entities: participant creation, required fields, defaults
# ---------------------------------------------------------------------------
def test_register_participant_returns_active_with_zero_funded(api):
    """PRD 3.1: "A newly registered participant is given `status` of `ACTIVE` and a `funded_cents` ledger initialized to 0."

    Design: Corner/entities/corner_create_participant_returns_201_with_fields
    """
    resp = api.create_participant(
        F.create_participant_payload(
            full_name="Ada Reg",
            birth_date="1948-01-15T00:00:00Z",
            gender="FEMALE",
            ethnicity="NON_HISPANIC",
            race="WHITE",
            poverty_status="AT_OR_ABOVE",
            lives_alone=True,
            rural=False,
            veteran=False,
        ),
        ADMIN,
    )
    data = validate_success(resp, expected_status=201)
    assert_participant(data)
    assert data["status"] == "ACTIVE", f"expected ACTIVE, got {data['status']}"
    assert data["funded_cents"] == 0, f"expected funded_cents 0, got {data['funded_cents']}"


def test_register_participant_missing_birth_date_rejected(api):
    """PRD 2.6: "Malformed input — a missing required field, a value outside an enum's allowed set, or a non-positive amount or quantity — is rejected with `ERR_VALIDATION` (HTTP 400)."

    Design: Corner/entities/corner_participant_missing_required_birth_date_returns_invalid_request
    """
    payload = {
        "full_name": "No DOB",
        "gender": "MALE",
        "ethnicity": "NON_HISPANIC",
        "race": "BLACK",
        "poverty_status": "BELOW",
        "lives_alone": False,
        "rural": False,
        "veteran": False,
    }
    resp = api.create_participant(payload, ADMIN)
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


def test_register_participant_defaults_disability_count_to_zero(api):
    """PRD 3.1: "The count of self-reported ADL/IADL limitations is given as `disability_count`; this field is optional on input and defaults to 0 when omitted."

    Design: Corner/entities/corner_participant_default_disability_count_is_zero
    """
    payload = F.create_participant_payload(
        full_name="Def Count",
        birth_date="1950-02-02T00:00:00Z",
        gender="OTHER",
        ethnicity="DECLINED",
        race="DECLINED",
        poverty_status="DECLINED",
        lives_alone=False,
        rural=True,
        veteran=False,
    )
    payload.pop("disability_count", None)
    data = validate_success(api.create_participant(payload, ADMIN), expected_status=201)
    assert data["disability_count"] == 0, f"expected default 0, got {data['disability_count']}"


# ---------------------------------------------------------------------------
# Queue A — transitive_cascade/tc_participant_deactivate_frees_meal_seats
# ---------------------------------------------------------------------------
def test_deactivate_participant_cancels_confirmed_reservation(api):
    """PRD 3.1: "Deactivation moves the participant from `ACTIVE` to `INACTIVE` and then cascades: for every meal reservation belonging to this participant whose `status` is `CONFIRMED`, that reservation is moved to `CANCELLED`, and each such cancellation decrements the reservation's meal service day `reserved_count` by 1 while incrementing that day's `available_seats` by 1."

    Design: Difficulty/transitive_cascade/tc_participant_deactivate_frees_meal_seats
    """
    ctx = fixtures.setup_meal_day_with_reservations(capacity=10, num_confirmed=1)
    participant = ctx["participants"][0]
    reservation = ctx["reservations"][0]

    updated = validate_success(api.deactivate_participant(participant["id"], ADMIN))
    assert updated["status"] == "INACTIVE", f"expected INACTIVE, got {updated['status']}"

    res_after = validate_success(api.get_reservation(reservation["id"], COORD))
    assert res_after["status"] == "CANCELLED", (
        f"cascade must cancel the CONFIRMED reservation, got {res_after['status']}"
    )


def test_deactivate_participant_restores_freed_meal_seats(api):
    """PRD 3.1: "Deactivation moves the participant from `ACTIVE` to `INACTIVE` and then cascades: for every meal reservation belonging to this participant whose `status` is `CONFIRMED`, that reservation is moved to `CANCELLED`, and each such cancellation decrements the reservation's meal service day `reserved_count` by 1 while incrementing that day's `available_seats` by 1."

    Design: Difficulty/transitive_cascade/tc_participant_deactivate_frees_meal_seats
    """
    ctx = fixtures.setup_meal_day_with_reservations(capacity=10, num_confirmed=1)
    participant = ctx["participants"][0]
    day = ctx["day"]

    validate_success(api.deactivate_participant(participant["id"], ADMIN))

    day_after = validate_success(api.get_meal_day(day["id"], ADMIN))
    assert day_after["reserved_count"] == 0, (
        f"reserved_count must drop to 0 after the cascade, got {day_after['reserved_count']}"
    )
    assert day_after["available_seats"] == 10, (
        f"available_seats must return to capacity 10, got {day_after['available_seats']}"
    )
    assert_meal_seat_conservation(day_after)


# ---------------------------------------------------------------------------
# Queue A — combinatorial_formula/cf_contribution_statement_per_meal_rounding
# ---------------------------------------------------------------------------
def test_contribution_statement_rounds_per_meal_then_sums(api):
    """PRD 3.6: "For each such meal, the per-meal suggested contribution is the congregate-meal unit cost of 850 cents multiplied by the contribution rate of fifteen percent (0.15), rounded half up to a whole number of cents. The rounding order is pinned: each meal's contribution is rounded to whole cents first, and only then are the per-meal amounts summed — summing first and rounding once would yield a different total and is not used."

    Design: Difficulty/combinatorial_formula/cf_contribution_statement_per_meal_rounding
    """
    fixtures.set_clock("2026-03-01T00:00:00Z")
    participant = fixtures.create_participant()
    for service_date in ("2026-03-05T12:00:00Z", "2026-03-12T12:00:00Z", "2026-03-19T12:00:00Z"):
        day = fixtures.create_meal_day(service_date=service_date, capacity=10)
        res = fixtures.reserve_meal(day["id"], participant["id"])
        fixtures.check_in(res["id"])

    data = validate_success(
        api.get_contribution_statement(
            participant["id"],
            make_participant_headers(participant["id"]),
            params={"month": "2026-03"},
        )
    )
    # round_half_up(850 * 0.15 = 127.5) = 128 per meal; 128 * 3 = 384 (not sum-then-round 383).
    assert data["total_suggested_contribution_cents"] == 384, (
        f"expected 384 (per-meal rounding), got {data['total_suggested_contribution_cents']}"
    )
    assert data["meal_count"] == 3, f"expected 3 meals, got {data['meal_count']}"


def test_contribution_statement_counts_only_checked_in_meals(api):
    """PRD 3.6: "For the requested `month`, the statement considers the participant's reservations whose `status` is `CHECKED_IN` and whose `service_date` falls within that calendar month in UTC — from the first day of the month at 00:00:00Z through the last day at 23:59:59Z inclusive."

    Design: Difficulty/combinatorial_formula/cf_contribution_statement_per_meal_rounding
    """
    fixtures.set_clock("2026-03-01T00:00:00Z")
    participant = fixtures.create_participant()
    # Two CHECKED_IN meals count; one CONFIRMED-but-not-checked-in meal does not.
    for service_date in ("2026-03-04T12:00:00Z", "2026-03-11T12:00:00Z"):
        day = fixtures.create_meal_day(service_date=service_date, capacity=10)
        res = fixtures.reserve_meal(day["id"], participant["id"])
        fixtures.check_in(res["id"])
    day3 = fixtures.create_meal_day(service_date="2026-03-18T12:00:00Z", capacity=10)
    fixtures.reserve_meal(day3["id"], participant["id"])  # left CONFIRMED, not checked in

    data = validate_success(
        api.get_contribution_statement(
            participant["id"], COORD, params={"month": "2026-03"}
        )
    )
    assert data["meal_count"] == 2, (
        f"only CHECKED_IN meals count; expected 2, got {data['meal_count']}"
    )
    assert data["total_suggested_contribution_cents"] == 256, (
        f"expected 128 * 2 = 256, got {data['total_suggested_contribution_cents']}"
    )
