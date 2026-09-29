"""Rejection corners: authentication, role authority, actor resolution and the
delivery-window gate on closing a commitment week.

Every test builds its own world from scratch against an empty database and drives
the API exactly as an operator would.
"""

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_commitment_week,
    create_fertigation_batch_payload,
    create_retail_program,
    create_scout_worker,
    create_scouting_observation_payload,
    create_zone_payload,
    headers_without_user_id,
    make_ipm_scout_headers,
    read_program,
    read_week,
    read_zone,
    set_clock,
    setup_transplanted_cycle,
    validate_error,
    validate_paginated,
    validate_success,
)

GM = TEST_USERS["grower_manager_headers"]
IT = TEST_USERS["irrigation_tech_headers"]


def test_zone_registration_with_an_empty_user_id_header_is_unauthenticated(api):
    """PRD §2.1: "If either header is absent or present but empty, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/errors/zone_create_missing_x_user_id_header_is_unauthenticated
    """
    payload = create_zone_payload(code="ZC-60")

    response = api.create_zone(payload, headers_without_user_id("GrowerManager"))

    validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED.value)

    # The payload is otherwise perfect, so nothing may have been written.
    rows, meta = validate_paginated(api.list_zones(GM))
    assert meta["total_count"] == 0, (
        f"no compartment may be registered by an unauthenticated call, got {meta['total_count']}"
    )
    assert rows == [], f"expected no compartment rows, got {rows}"


def test_mixing_a_fertigation_batch_as_grower_manager_is_unauthorized(api):
    """PRD §2.1: "A request whose `X-User-Role` is not one of these six strings, or is one of them but is not listed among the roles authorised for the endpoint being called, is rejected with `ERR_UNAUTHORIZED` (HTTP 403); an unrecognised role string is treated as an unauthorised role rather than as a malformed body."

    Design: Corner/errors/fertigation_create_by_the_grower_manager_is_unauthorized
    """
    state = setup_transplanted_cycle(clock="2026-08-06T00:00:00Z")
    payload = create_fertigation_batch_payload(
        state["zone"]["id"], state["cycle"]["id"]
    )

    response = api.create_fertigation_batch(payload, GM)

    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED.value)

    rows, meta = validate_paginated(api.list_fertigation_batches(GM))
    assert meta["total_count"] == 0, (
        f"no batch may be mixed by an unauthorised role, got {meta['total_count']}"
    )

    # The identical payload mixed by the irrigation technician is accepted, which
    # proves the rejection was about the acting role and not about the body.
    accepted = validate_success(api.create_fertigation_batch(payload, IT), 201)
    assert accepted["status"] == "MIXED", (
        f"a freshly mixed batch sits in MIXED, got {accepted['status']}"
    )


def test_scouting_observation_from_an_unresolvable_scout_id_is_rejected(api):
    """PRD §2.1: "When it does not resolve — no such `Worker`, or a `Worker` with the wrong `skill` — the request is rejected with `ERR_ACTOR_NOT_RECOGNIZED` (HTTP 403)."

    Design: Corner/errors/scouting_observation_with_an_unknown_x_user_id_is_rejected
    """
    state = setup_transplanted_cycle(clock="2026-08-06T00:00:00Z")
    scout = create_scout_worker()
    payload = create_scouting_observation_payload(
        state["zone"]["id"], state["cycle"]["id"]
    )

    # The acting identifier matches no worker row at all.
    response = api.create_scouting_observation(payload, TEST_USERS["ipm_scout_headers"])

    validate_error(response, ApiErrorId.ERR_ACTOR_NOT_RECOGNIZED.value)

    rows, meta = validate_paginated(api.list_scouting_observations(GM))
    assert meta["total_count"] == 0, (
        f"no observation may be filed by an unresolvable scout, got {meta['total_count']}"
    )
    zone = read_zone(state["zone"]["id"])
    assert zone["open_pest_alert_count"] == 0, (
        f"the pest gate must be untouched, got {zone['open_pest_alert_count']}"
    )

    # The same call sent by the registered SCOUT worker is accepted.
    accepted = validate_success(
        api.create_scouting_observation(payload, make_ipm_scout_headers(scout["id"])),
        201,
    )
    assert accepted["observed_by_worker_id"] == scout["id"], (
        "observed_by_worker_id is taken from the filing scout's X-User-ID, got "
        f"{accepted['observed_by_worker_id']}"
    )


def test_closing_a_week_before_its_delivery_window_elapses_is_rejected(api):
    """PRD §3.10: "A week may also be closed straight from `OPEN` to `CLOSED_SHORT`, which is how a week nobody could fill gets written off, but only once the delivery window has elapsed: the current logical clock date must be at or after `week_start_date` plus 7 days, and an early attempt is rejected with `ERR_WEEK_STILL_OPEN`."

    Design: Corner/errors/closing_a_week_before_its_delivery_window_elapses_is_rejected
    """
    set_clock("2026-08-31T06:00:00Z")
    program = create_retail_program(program_code="TW-1")
    week = create_commitment_week(
        program["id"], iso_week="2026-W36", week_start_date="2026-08-31"
    )
    assert week["status"] == "OPEN", f"a new week opens in OPEN, got {week['status']}"

    # 2026-09-06 is one day short of 2026-08-31 plus seven days.
    set_clock("2026-09-06T06:00:00Z")
    response = api.transition_commitment_week(
        week["id"], {"to_status": "CLOSED_SHORT"}, GM
    )

    validate_error(response, ApiErrorId.ERR_WEEK_STILL_OPEN.value)

    unchanged = read_week(week["id"])
    assert unchanged["status"] == "OPEN", (
        f"the rejected close leaves the week OPEN, got {unchanged['status']}"
    )
    assert unchanged["final_shortfall_lbs"] is None, (
        f"final_shortfall_lbs stays null until closing, got {unchanged['final_shortfall_lbs']}"
    )
    assert unchanged["final_penalty_usd"] is None, (
        f"final_penalty_usd stays null until closing, got {unchanged['final_penalty_usd']}"
    )
    assert read_program(program["id"])["penalty_accrued_usd"] == 0.00, (
        "no penalty may be posted to the program by a rejected close"
    )
