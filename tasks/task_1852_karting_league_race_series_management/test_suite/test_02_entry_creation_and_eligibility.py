"""Entry creation: fee snapshot, body well-formedness, class and equipment
eligibility, duplicate-entry uniqueness, and the registration-open gate."""
from test_helpers import (
    ApiErrorId,
    add_kart,
    assert_entry,
    create_entry_payload,
    create_event,
    enter_driver,
    register_active_driver,
    setup_active_season,
    setup_open_event,
    validate_error,
    validate_success,
    withdraw_entry,
)


def test_entry_creation_snapshots_class_fee(api, league_admin_headers):
    """PRD 3.3: "A created entry starts `ENTERED`, with its `entry_fee_cents`
    snapshotted from the class and its `fee_status` `UNPAID`."
    PRD 3.3: "Each entry carries its `event_id` for addressability, and its derived
    `tech_fail_count` and `event_points` track inspection failures (§3.4) and sporting
    yield (§3.5)."

    Design: Corner/entities/entry_fee_snapshot_and_computed_fields
    """
    ctx = setup_open_event()
    driver = register_active_driver(full_name="Snapshot")

    response = api.create_entry(
        ctx["event"]["id"],
        create_entry_payload(driver["id"], ctx["race_class"]["id"]),
        league_admin_headers,
    )
    entry = validate_success(response, 201)
    assert_entry(entry)
    assert entry["status"] == "ENTERED"
    assert entry["entry_fee_cents"] == 5000, (
        "entry_fee_cents is the snapshot of the class's 5000-cent fee"
    )
    assert entry["fee_status"] == "UNPAID"
    assert entry["event_points"] == 0
    assert entry["tech_fail_count"] == 0
    assert entry["event_id"] == ctx["event"]["id"]


def test_entry_with_invalid_entry_type_rejected(api, league_admin_headers):
    """PRD 2.8: "3. **Body well-formedness** — required fields are present, enum values
    are valid, `end_time` is strictly after `start_time`, a `RENTAL` entry carries
    `kart_id` while an `OWNER_DRIVER` entry omits it, and `penalty_seconds` is present
    and positive exactly when `penalty_kind` is `TIME_SECONDS` (`ERR_INVALID_REQUEST`)."

    Design: Corner/entities/entry_invalid_entry_type_enum_rejected
    """
    ctx = setup_open_event()
    driver = register_active_driver(full_name="Enum")

    response = api.create_entry(
        ctx["event"]["id"],
        create_entry_payload(driver["id"], ctx["race_class"]["id"], entry_type="BORROWED"),
        league_admin_headers,
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 400)


def test_owner_driver_entry_with_kart_id_rejected(api, league_admin_headers):
    """PRD 3.3: "Body rules come first: a `RENTAL` entry must carry `kart_id` and an
    `OWNER_DRIVER` entry must omit it, with violations answered by
    `ERR_INVALID_REQUEST`."

    Design: Corner/validations/owner_entry_with_kart_id_rejected
    """
    ctx = setup_open_event()
    driver = register_active_driver(full_name="Owner")
    kart = add_kart(fleet_number="K-30")

    response = api.create_entry(
        ctx["event"]["id"],
        create_entry_payload(
            driver["id"],
            ctx["race_class"]["id"],
            entry_type="OWNER_DRIVER",
            kart_id=kart["id"],
        ),
        league_admin_headers,
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 400)


def test_rental_entry_without_kart_id_rejected(api, league_admin_headers):
    """PRD 3.3: "Body rules come first: a `RENTAL` entry must carry `kart_id` and an
    `OWNER_DRIVER` entry must omit it, with violations answered by
    `ERR_INVALID_REQUEST`."

    Design: Corner/validations/rental_entry_requires_kart_id
    """
    ctx = setup_open_event()
    driver = register_active_driver(full_name="Renter", license_type="RENTAL")

    response = api.create_entry(
        ctx["event"]["id"],
        create_entry_payload(driver["id"], ctx["race_class"]["id"], entry_type="RENTAL"),
        league_admin_headers,
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 400)


def test_rental_entry_into_no_rental_class_rejected(api, league_admin_headers):
    """PRD 3.3: "A `RENTAL` entry into a class whose `rental_kart_allowed` is false is
    refused with `ERR_RENTAL_NOT_ALLOWED`, and the chosen kart's `eligible_class_codes`
    must contain the entry's class code, else `ERR_KART_CLASS_INELIGIBLE`."

    Design: Corner/validations/rental_entry_in_no_rental_class_rejected
    """
    ctx = setup_open_event(
        class_overrides={
            "code": "CADET",
            "min_age": 7,
            "max_age": 12,
            "min_combined_weight_kg": 110.0,
            "entry_fee_cents": 3000,
            "rental_kart_allowed": False,
        }
    )
    # Age 10 at the event date: inside the CADET 7-12 window, so only the
    # rental-permission rule can fail.
    driver = register_active_driver(
        full_name="Kid", date_of_birth="2016-01-01", body_weight_kg=40.0,
        license_type="RENTAL",
    )
    kart = add_kart(fleet_number="K-40", eligible_class_codes=["CADET"])

    response = api.create_entry(
        ctx["event"]["id"],
        create_entry_payload(
            driver["id"], ctx["race_class"]["id"], entry_type="RENTAL",
            kart_id=kart["id"],
        ),
        league_admin_headers,
    )
    validate_error(response, ApiErrorId.ERR_RENTAL_NOT_ALLOWED.value, 422)


def test_rental_entry_with_class_ineligible_kart_rejected(api, league_admin_headers):
    """PRD 3.3: "A `RENTAL` entry into a class whose `rental_kart_allowed` is false is
    refused with `ERR_RENTAL_NOT_ALLOWED`, and the chosen kart's `eligible_class_codes`
    must contain the entry's class code, else `ERR_KART_CLASS_INELIGIBLE`."

    Design: Corner/validations/kart_class_ineligible_rejected
    """
    ctx = setup_open_event()
    driver = register_active_driver(full_name="Renter", license_type="RENTAL")
    kart = add_kart(fleet_number="K-41", eligible_class_codes=["CADET"])

    response = api.create_entry(
        ctx["event"]["id"],
        create_entry_payload(
            driver["id"], ctx["race_class"]["id"], entry_type="RENTAL",
            kart_id=kart["id"],
        ),
        league_admin_headers,
    )
    validate_error(response, ApiErrorId.ERR_KART_CLASS_INELIGIBLE.value, 422)


def test_duplicate_entry_rejected_but_reentry_after_withdrawal_allowed(
    api, league_admin_headers
):
    """PRD 3.3: "The kart must be `AVAILABLE` and not already assigned to another
    non-`WITHDRAWN` entry of the same event (`ERR_KART_UNAVAILABLE`), the driver must
    be `ACTIVE` (`ERR_DRIVER_NOT_ACTIVE`), and a driver may hold at most one
    non-`WITHDRAWN` entry per event (`ERR_DUPLICATE_ENTRY`)."

    Design: Corner/validations/duplicate_entry_rejected
    """
    ctx = setup_open_event()
    driver = register_active_driver(full_name="Twice")
    first = enter_driver(ctx["event"]["id"], driver["id"], ctx["race_class"]["id"])

    duplicate = api.create_entry(
        ctx["event"]["id"],
        create_entry_payload(driver["id"], ctx["race_class"]["id"]),
        league_admin_headers,
    )
    validate_error(duplicate, ApiErrorId.ERR_DUPLICATE_ENTRY.value, 409)

    withdrawn = withdraw_entry(first["id"])
    assert withdrawn["status"] == "WITHDRAWN"

    reentry = api.create_entry(
        ctx["event"]["id"],
        create_entry_payload(driver["id"], ctx["race_class"]["id"]),
        league_admin_headers,
    )
    second = validate_success(reentry, 201)
    assert_entry(second)
    assert second["status"] == "ENTERED", (
        "uniqueness counts only non-WITHDRAWN entries, so re-entry succeeds"
    )


def test_class_age_window_inclusive_boundaries(api, league_admin_headers):
    """PRD 3.3: "The driver's age in whole years at the `event_date` — the span from
    `date_of_birth` to `event_date`, reckoned at 365.25 days per year and rounded down —
    must fall within the class's inclusive window from `min_age` to `max_age`, else
    `ERR_CLASS_MISMATCH`."

    Design: Corner/calculations/class_age_boundary_inclusive
    """
    ctx = setup_open_event(event_overrides={"event_date": "2026-09-05T00:00:00Z"})
    # Exactly 16 on the event date: inside the inclusive 16-44 SENIOR window.
    exact = register_active_driver(full_name="E16", date_of_birth="2010-09-05")
    # One day younger: 15 whole years at the event date, below the window.
    younger = register_active_driver(full_name="Y15", date_of_birth="2010-09-06")

    accepted = api.create_entry(
        ctx["event"]["id"],
        create_entry_payload(exact["id"], ctx["race_class"]["id"]),
        league_admin_headers,
    )
    entry = validate_success(accepted, 201)
    assert entry["status"] == "ENTERED"

    rejected = api.create_entry(
        ctx["event"]["id"],
        create_entry_payload(younger["id"], ctx["race_class"]["id"]),
        league_admin_headers,
    )
    validate_error(rejected, ApiErrorId.ERR_CLASS_MISMATCH.value, 422)


def test_entry_creation_blocked_until_registration_opens(api, league_admin_headers):
    """PRD 2.8: "6. **State preconditions** — the target resources sit in states that
    permit the operation: the season `ACTIVE` for event creation and registration
    opening (`ERR_SEASON_NOT_ACTIVE`); the event `REGISTRATION_OPEN` for entry creation
    (`ERR_EVENT_REGISTRATION_CLOSED`); the driver `ACTIVE` for entries and practice
    bookings (`ERR_DRIVER_NOT_ACTIVE`); the kart `AVAILABLE` for entries and bookings
    (`ERR_KART_UNAVAILABLE`); no open incidents at event finalization
    (`ERR_OPEN_INCIDENTS`); no prior appeal on the incident (`ERR_APPEAL_LIMIT`); the
    session `CLOSED` for result submission and for scoring, with scoring from a
    non-closed session surfaced as `ERR_SESSION_NOT_CLOSED`; every `GRID_LOCKED` entry
    holding a result at scoring time (`ERR_RESULTS_INCOMPLETE`); every non-`WITHDRAWN`
    entry in `TECH_PASSED` at grid lock (`ERR_TECH_NOT_PASSED`); and any other invalid
    from-state for a requested transition (`ERR_INVALID_STATE`)."

    Design: Difficulty/cross_entity_state_dependency/entry_requires_event_registration_open
    """
    ctx = setup_active_season()
    event = create_event(ctx["season"]["id"])
    driver = register_active_driver(full_name="Early")

    blocked = api.create_entry(
        event["id"],
        create_entry_payload(driver["id"], ctx["race_class"]["id"]),
        league_admin_headers,
    )
    validate_error(blocked, ApiErrorId.ERR_EVENT_REGISTRATION_CLOSED.value, 409)


def test_entry_creation_succeeds_once_registration_open(api, league_admin_headers):
    """PRD 3.3: "Entries are created while registration is open, by a `LeagueAdmin` or
    by a `Driver` for themselves, with a payload naming the `driver_id`, the `class_id`
    of a class in the event's season, the `entry_type` — `RENTAL` or `OWNER_DRIVER` —
    and, for rentals, the `kart_id`."
    PRD 3.3: "A created entry starts `ENTERED`, with its `entry_fee_cents` snapshotted
    from the class and its `fee_status` `UNPAID`."

    Design: Difficulty/cross_entity_state_dependency/entry_requires_event_registration_open
    """
    ctx = setup_open_event()
    driver = register_active_driver(full_name="On Time")

    response = api.create_entry(
        ctx["event"]["id"],
        create_entry_payload(driver["id"], ctx["race_class"]["id"]),
        league_admin_headers,
    )
    entry = validate_success(response, 201)
    assert_entry(entry)
    assert entry["status"] == "ENTERED"
    assert entry["fee_status"] == "UNPAID"


def test_closed_registration_shadows_class_mismatch(api, league_admin_headers):
    """PRD 2.8: "When several checks could fail on the same request, the server
    evaluates them in a fixed order and answers with the first failing tier:"
    PRD 2.8: "6. **State preconditions** — the target resources sit in states that
    permit the operation: the season `ACTIVE` for event creation and registration
    opening (`ERR_SEASON_NOT_ACTIVE`); the event `REGISTRATION_OPEN` for entry creation
    (`ERR_EVENT_REGISTRATION_CLOSED`); the driver `ACTIVE` for entries and practice
    bookings (`ERR_DRIVER_NOT_ACTIVE`); the kart `AVAILABLE` for entries and bookings
    (`ERR_KART_UNAVAILABLE`); no open incidents at event finalization
    (`ERR_OPEN_INCIDENTS`); no prior appeal on the incident (`ERR_APPEAL_LIMIT`); the
    session `CLOSED` for result submission and for scoring, with scoring from a
    non-closed session surfaced as `ERR_SESSION_NOT_CLOSED`; every `GRID_LOCKED` entry
    holding a result at scoring time (`ERR_RESULTS_INCOMPLETE`); every non-`WITHDRAWN`
    entry in `TECH_PASSED` at grid lock (`ERR_TECH_NOT_PASSED`); and any other invalid
    from-state for a requested transition (`ERR_INVALID_STATE`)."
    PRD 2.8: "7. **Class and equipment eligibility** — age window and license
    consistency (`ERR_CLASS_MISMATCH`), rental permission (`ERR_RENTAL_NOT_ALLOWED`),
    kart class eligibility (`ERR_KART_CLASS_INELIGIBLE`). Applies only to entry creation."

    Design: Difficulty/priority_pair_validation_conflict/entry_closed_registration_shadows_class_mismatch
    """
    ctx = setup_active_season()
    # Event stays SCHEDULED (registration never opened): the state tier fails.
    event = create_event(ctx["season"]["id"])
    # Age 10 at the event date: outside the SENIOR 16-44 window, so the
    # eligibility tier would fail too — but it must stay masked.
    driver = register_active_driver(
        full_name="Junior", date_of_birth="2016-01-01", body_weight_kg=40.0
    )

    response = api.create_entry(
        event["id"],
        create_entry_payload(driver["id"], ctx["race_class"]["id"]),
        league_admin_headers,
    )
    validate_error(response, ApiErrorId.ERR_EVENT_REGISTRATION_CLOSED.value, 409)


def test_age_ineligible_driver_rejected_when_registration_open(
    api, league_admin_headers
):
    """PRD 3.3: "The driver's age in whole years at the `event_date` — the span from
    `date_of_birth` to `event_date`, reckoned at 365.25 days per year and rounded down —
    must fall within the class's inclusive window from `min_age` to `max_age`, else
    `ERR_CLASS_MISMATCH`."

    Design: Difficulty/priority_pair_validation_conflict/entry_closed_registration_shadows_class_mismatch
    """
    ctx = setup_open_event()
    driver = register_active_driver(
        full_name="Junior", date_of_birth="2016-01-01", body_weight_kg=40.0
    )

    response = api.create_entry(
        ctx["event"]["id"],
        create_entry_payload(driver["id"], ctx["race_class"]["id"]),
        league_admin_headers,
    )
    validate_error(response, ApiErrorId.ERR_CLASS_MISMATCH.value, 422)
