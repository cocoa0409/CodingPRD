"""Barns, owners, horses and hooves — the reference data every visit stands on."""

from test_helpers import *  # noqa: F401,F403


def test_barn_creation_returns_every_declared_field(api, admin):
    """PRD §3.1: "A barn is described by a `name`, a travel `zone` that is one of
    `A`, `B` or `C`, a set of `served_weekdays` drawn from `MON`, `TUE`, `WED`,
    `THU`, `FRI`, `SAT` and `SUN`, an `access_open_minute` and an
    `access_close_minute` bounding the hours the gate is unlocked, and an optional
    list of `blackout_dates` on which the yard is shut regardless of the weekday
    pattern."
    PRD §2.4: "Every persisted resource carries a server-minted `id`: a UUID string
    with no type prefix and no embedded meaning."

    Design: Corner/entities/corner_barn_creation_returns_every_declared_field
    """
    payload = barn_payload(
        name="Ridgeview",
        zone="A",
        served_weekdays=["MON", "WED", "FRI"],
        access_open_minute=420,
        access_close_minute=1020,
        blackout_dates=["2026-05-06"],
    )
    data = validate_success(api.create_barn(payload, admin), 201)

    assert_barn(data)
    assert data["name"] == "Ridgeview"
    assert data["zone"] == "A"
    assert data["served_weekdays"] == ["MON", "WED", "FRI"]
    assert data["access_open_minute"] == 420
    assert data["access_close_minute"] == 1020
    assert data["blackout_dates"] == ["2026-05-06"]
    assert data["version"] == 1, "a freshly minted row starts at version 1"
    assert is_valid_uuid(data["id"]), "the id is a bare UUID with no type prefix"


def test_unknown_barn_id_returns_barn_not_found(api, admin):
    """PRD §2.7: "(4) `Barn` — `ERR_BARN_NOT_FOUND`, on barn read, client creation,
    horse creation and stop insertion."

    Design: Corner/entities/corner_barn_not_found_returns_barn_not_found
    """
    response = api.get_barn(NON_EXISTENT_UUID, admin)

    validate_error(response, ApiErrorId.ERR_BARN_NOT_FOUND.value)
    assert response.status_code == 404


def test_client_defaults_are_active_zero_and_not_exempt(api, admin):
    """PRD §3.1: "`tax_exempt` defaults to false and selects which tax treatment
    the owner's invoices receive."
    PRD §3.1: "Everything else on a client is derived and starts at a known value —
    `billing_standing` starts `ACTIVE`, `deposit_balance_cents` starts 0,
    `credit_balance_cents` starts 0 and `no_show_count_rolling` starts 0."
    PRD §3.1: "`opening_completed_visit_count` defaults to 0 and exists because
    this business is migrating off a paper diary: whatever number is supplied is
    the starting value of the client's `completed_visit_count`, and every visit
    the system itself completes is added on top of it."

    Design: Corner/entities/corner_client_defaults_are_active_zero_and_not_exempt
    """
    barn = create_barn()

    data = validate_success(
        api.create_client(
            {"display_name": "Aoi Tanaka", "home_barn_id": barn["id"]}, admin
        ),
        201,
    )

    assert_client(data)
    assert data["tax_exempt"] is False
    assert data["billing_standing"] == "ACTIVE"
    assert data["deposit_balance_cents"] == 0
    assert data["credit_balance_cents"] == 0
    assert data["completed_visit_count"] == 0
    assert data["no_show_count_rolling"] == 0


def test_horse_creation_mints_four_barefoot_limb_states_in_order(api, admin):
    """PRD §3.1: "Creating a horse mints four (`LIMB_COUNT_PER_HORSE`) `LimbState`
    rows in exactly the order `LF`, `RF`, `LH`, `RH`, each starting `BAREFOOT` with
    a null `current_sku_code`, a null `last_serviced_on` and a
    `consecutive_reset_count` of 0."
    PRD §3.1: "`requires_sedation` defaults to false; when true it changes the
    arithmetic of the visit in two separate places — the chair minutes and the
    labour price — and forces a veterinarian's attendance."
    PRD §3.1: "A horse's `active_prescription_id`, `next_due_on` and
    `last_completed_on` are all derived and start null."

    Design: Corner/entities/corner_horse_creation_mints_four_barefoot_limb_states_in_order
    """
    barn = create_barn()
    client = create_client(barn["id"])

    horse = validate_success(
        api.create_horse(
            {
                "client_id": client["id"],
                "barn_id": barn["id"],
                "name": "Comet",
                "routine_cycle_weeks": 7,
                "shoe_size_code": "1",
            },
            admin,
        ),
        201,
    )
    assert_horse(horse)
    assert horse["requires_sedation"] is False
    assert horse["hold_status"] == "CLEAR"
    assert horse["next_due_on"] is None
    assert horse["last_completed_on"] is None
    assert horse["active_prescription_id"] is None

    rows = validate_success(api.list_limb_states(horse["id"], admin))
    assert len(rows) == LIMB_COUNT_PER_HORSE, "a horse has exactly four limb rows"
    assert [row["limb"] for row in rows] == LIMB_ORDER
    for row in rows:
        assert_limb_state(row)
        assert row["shoeing_state"] == "BAREFOOT"
        assert row["current_sku_code"] is None
        assert row["last_serviced_on"] is None
        assert row["consecutive_reset_count"] == 0


def test_horse_creation_without_routine_cycle_weeks_is_rejected(api, admin):
    """PRD §2.7: "(21) Every field the endpoint declares as required is present and
    correctly typed; the `lines` array of a service-line addition is non-empty; and
    the declared field-combination rules hold"
    PRD §2.7: "Any breach is `ERR_VALIDATION` (HTTP 400). This rung applies to every
    write endpoint."

    Design: Corner/entities/corner_horse_missing_required_field_is_rejected
    """
    barn = create_barn()
    client = create_client(barn["id"])

    response = api.create_horse(
        {
            "client_id": client["id"],
            "barn_id": barn["id"],
            "name": "Comet",
            "shoe_size_code": "1",
        },
        admin,
    )

    validate_error(response, ApiErrorId.ERR_VALIDATION.value)
    assert response.status_code == 400
    rows, _meta = validate_paginated(
        api.list_horses(admin, params={"client_id": client["id"]})
    )
    assert rows == [], "a refused creation writes no horse"


def test_horse_routine_cycle_weeks_below_the_minimum_is_out_of_range(api, admin):
    """PRD §3.1: "It also carries a `name`, a `shoe_size_code` giving the nominal
    size its shoes are ordered in, and a `routine_cycle_weeks` between 6
    (`MIN_ROUTINE_CYCLE_WEEKS`) and 8 (`MAX_ROUTINE_CYCLE_WEEKS`) inclusive that
    says how often it is normally due."
    PRD §2.7: "(23) Numeric and date ranges hold, else `ERR_VALUE_OUT_OF_RANGE`
    (HTTP 422) — `routine_cycle_weeks` between 6 and 8 inclusive"

    Design: Corner/entities/corner_horse_cycle_weeks_below_minimum_is_out_of_range
    """
    barn = create_barn()
    client = create_client(barn["id"])

    refused = api.create_horse(
        horse_payload(client["id"], barn["id"], routine_cycle_weeks=5), admin
    )
    validate_error(refused, ApiErrorId.ERR_VALUE_OUT_OF_RANGE.value)
    assert refused.status_code == 422

    admitted = validate_success(
        api.create_horse(
            horse_payload(
                client["id"], barn["id"], name="Dusty", routine_cycle_weeks=6
            ),
            admin,
        ),
        201,
    )
    assert admitted["routine_cycle_weeks"] == MIN_ROUTINE_CYCLE_WEEKS


def test_appointment_listing_is_paginated_with_total_count_and_has_more(
    api, admin, dispatcher
):
    """PRD §2.3: "`total_count` is the number of rows matching the filters
    **before** `limit` and `offset` are applied, and `has_more` is true exactly
    when the sum of `offset` and the number of rows actually returned is strictly
    less than `total_count`."
    PRD §2.3: "Ordering is uniform: every list endpoint returns its rows ordered by
    `created_at` ascending, and rows minted inside a single request tie-break in
    the order they were minted."

    Design: Corner/entities/corner_appointment_listing_is_paginated_with_total_count_and_has_more
    """
    barn = create_barn()
    client = create_client(barn["id"])
    horses = [
        create_horse(client["id"], barn["id"], name=name)
        for name in ("Comet", "Dusty", "Echo")
    ]
    made = [create_appointment(horse["id"], "2026-05-06") for horse in horses]

    rows, meta = validate_paginated(
        api.list_appointments(dispatcher, params={"limit": 2, "offset": 1})
    )

    assert len(rows) == 2, "limit 2 returns at most two rows"
    assert meta["total_count"] == 3, "total_count counts rows before limit and offset"
    assert meta["limit"] == 2
    assert meta["offset"] == 1
    assert meta["has_more"] is False, "offset 1 plus 2 rows returned is not below 3"
    assert rows[0]["id"] == made[1]["id"], "listing order is created_at ascending"
    assert rows[1]["id"] == made[2]["id"]


def test_client_supplied_system_fields_are_ignored(api, admin):
    """PRD §2.4: "Clients never supply an `id`; a client-supplied `id` in a request
    body is ignored."
    PRD §2.4: "All but one entity additionally carry `updated_at` (same format as
    `created_at`, refreshed on every mutation of that row) and `version`, an
    integer that starts at 1 when the row is minted and increases by exactly 1 on
    every mutation of that row."
    PRD §3.1: "`blackout_dates` defaults to the empty list when it is not supplied."

    Design: Corner/entities/corner_system_fields_are_server_minted_and_client_values_ignored
    """
    supplied_id = "11111111-2222-3333-4444-555555555555"

    data = validate_success(
        api.create_barn(
            {
                "name": "Ridgeview",
                "zone": "B",
                "served_weekdays": ["MON"],
                "access_open_minute": 420,
                "access_close_minute": 1020,
                "id": supplied_id,
                "version": 99,
            },
            admin,
        ),
        201,
    )

    assert_barn(data)
    assert data["id"] != supplied_id, "a client-supplied id is ignored"
    assert data["version"] == 1, "version starts at 1 when the row is minted"
    assert is_iso8601_timestamp(data["created_at"])
    assert data["blackout_dates"] == [], "blackout_dates defaults to the empty list"


def test_appointment_creation_with_unknown_horse_returns_horse_not_found(
    api, dispatcher
):
    """PRD §2.7: "(6) `Horse` — `ERR_HORSE_NOT_FOUND`, on horse read, horse patch,
    retire, reinstate, limb-state listing, appointment creation and lameness-case
    creation."
    PRD §2.7: "These run in a fixed sequence, and they run **before** any
    payload-shape check, so a request that names a nonexistent id and also omits a
    required field reports the existence code."

    Design: Corner/entities/corner_appointment_create_with_unknown_horse_returns_horse_not_found
    """
    response = api.create_appointment(
        {"horse_id": NON_EXISTENT_UUID, "scheduled_date": "2026-05-06"}, dispatcher
    )

    validate_error(response, ApiErrorId.ERR_HORSE_NOT_FOUND.value)
    assert response.status_code == 404
