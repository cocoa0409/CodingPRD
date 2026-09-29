"""Two live violations at once: the declared ladder decides which one is reported."""

from test_helpers import (
    ApiClient,
    ApiErrorId,
    AppointmentState,
    BoothStatus,
    ExhibitorStatus,
    ShowStatus,
    SpaceContractStatus,
    factories as f,
    fixtures as fx,
    make_floor_manager_headers,
    validate_error,
    validate_paginated,
)

CLOCK = "2026-08-15T00:00:00Z"

A100 = f.booth_payload("A100", 20, 20, location_class="CORNER",
                       premium_zone="MAIN_AISLE", max_height_ft=16)
C050 = f.inline_booth_payload("C050", 10, 20)


def _offered_env(client: ApiClient) -> dict:
    """An OFFERED 400 sqft contract whose minimum deposit is 389070 cents."""
    fx.set_clock(client, CLOCK)
    env = fx.published_show(client, [A100, C050])
    exhibitor = fx.exhibitor(client, "Nordic Furnishings", consecutive_years=6)
    env["exhibitor"] = exhibitor
    env["exhibitor_headers"] = fx.make_exhibitor_headers(exhibitor["id"])
    env["contract"] = fx.offered_contract(
        client, env["show"]["id"], exhibitor["id"], 400,
        [env["booth_by_number"]["A100"]["id"]], premium_placement_requested=True,
    )
    return env


def _underfunded_sign(client: ApiClient, env: dict):
    return client.sign_space_contract(
        env["contract"]["id"],
        f.sign_payload(fx.show_version(client, env["show"]["id"]), 1000),
        env["exhibitor_headers"],
    )


def test_an_underfunded_sign_while_selling_is_open_reports_the_money_rule(
    client: ApiClient,
):
    """
    A one-thousand-cent deposit against a contract needing 389070, on a show that
    is still `SPACE_SELECTION` — only the fiscal rule is violated.

    "**Money last**, in this order: discount approval authority
    (`ERR_DISCOUNT_APPROVAL_REQUIRED`), discount cap (`ERR_DISCOUNT_EXCEEDS_CAP`),
    sponsorship price floor (`ERR_SPONSORSHIP_PRICE_BELOW_FLOOR`), deposit minimum
    at signing (`ERR_DEPOSIT_BELOW_MINIMUM`), deposit ceiling
    (`ERR_DEPOSIT_EXCEEDS_INVOICE`)."

    Design: Difficulty/priority_pair_validation_conflict/sign_on_onsite_show_reports_show_status_not_deposit_shortfall
    """
    env = _offered_env(client)
    assert env["contract"]["min_deposit_cents"] == 389070

    validate_error(
        _underfunded_sign(client, env),
        ApiErrorId.DEPOSIT_BELOW_MINIMUM,
        422,
    )
    contract = fx.read_contract(client, env["contract"]["id"])
    assert contract["status"] == SpaceContractStatus.OFFERED
    assert contract["deposit_paid_cents"] == 0


def test_the_same_underfunded_sign_on_an_onsite_show_reports_the_status_rule(
    client: ApiClient,
):
    """
    The identical request once the edition has reached `ON_SITE`: the state rule
    sits above the money rule and pre-empts it.

    "A sign request against an `ON_SITE` show whose deposit is also below the
    minimum reports `ERR_INVALID_SHOW_STATUS`, not `ERR_DEPOSIT_BELOW_MINIMUM`: the
    show being past selling closes the door before the money is even counted."

    Design: Difficulty/priority_pair_validation_conflict/sign_on_onsite_show_reports_show_status_not_deposit_shortfall
    """
    env = _offered_env(client)
    fx.transition(client, env["show"]["id"], ShowStatus.SELLING)
    fx.transition(client, env["show"]["id"], ShowStatus.ON_SITE)

    validate_error(
        _underfunded_sign(client, env),
        ApiErrorId.INVALID_SHOW_STATUS,
        409,
    )
    contract = fx.read_contract(client, env["contract"]["id"])
    assert contract["status"] == SpaceContractStatus.OFFERED
    assert contract["deposit_paid_cents"] == 0
    booth = fx.read_booth(client, env["booth_by_number"]["A100"]["id"])
    assert booth["status"] == BoothStatus.HELD


HALL_B = {
    "hall_code": "HALL_B",
    "hall_gross_sqft": 120000,
    "committed_net_sqft_per_year": 400,
    "attrition_allowance_pct": 10,
    "advance_order_discount_pct": 15,
    "labor_rate_cents_per_hour": 9000,
    "electrical_rate_cents_per_amp": 4000,
    "material_handling_rate_cents_per_cwt": 8000,
}
X100 = f.inline_booth_payload("X100", 20, 20)


def _two_hall_env(client: ApiClient) -> dict:
    """Two published editions in two halls; the second hall's booth is already HELD."""
    fx.set_clock(client, CLOCK)
    home = fx.published_show(client, [A100, C050])
    away = fx.published_show(
        client, [X100], vc_overrides=HALL_B, name="Regional Buyers Expo",
        gross_sqft=40000, aisle_ratio_pct=35, base_rate_cents_per_sqft=2100,
        selection_desk_capacity=1,
    )
    holder = fx.exhibitor(client, "Harbor Ceramics", consecutive_years=2)
    away["contract"] = fx.offered_contract(
        client, away["show"]["id"], holder["id"], 400,
        [away["booth_by_number"]["X100"]["id"]],
    )
    return {
        "home": home,
        "away": away,
        "holder": holder,
        "newcomer": fx.exhibitor(client, "Nordic Furnishings", consecutive_years=6),
    }


def _claim_the_foreign_booth(client: ApiClient, env: dict):
    home = env["home"]
    return client.create_space_contract(
        f.space_contract_payload(
            home["show"]["id"], env["newcomer"]["id"],
            fx.show_version(client, home["show"]["id"]), 400,
            booth_ids=[env["away"]["booth_by_number"]["X100"]["id"]],
        ),
        fx.SALES_REP_HEADERS,
    )


def test_a_foreign_booth_that_is_also_held_reports_the_broken_reference(
    client: ApiClient,
):
    """
    The named booth violates both the membership rule and the availability rule.

    "A booth reference that belongs to another show *and* is already held there
    reports `ERR_BOOTH_NOT_IN_SHOW`, not `ERR_BOOTH_NOT_AVAILABLE`: a cross-show
    reference is a broken relationship, not an inventory shortage."

    Design: Difficulty/priority_pair_validation_conflict/holding_a_foreign_shows_booth_reports_not_in_show_not_unavailable
    """
    env = _two_hall_env(client)
    foreign = fx.read_booth(client, env["away"]["booth_by_number"]["X100"]["id"])
    assert foreign["show_id"] == env["away"]["show"]["id"]
    assert foreign["status"] == BoothStatus.HELD

    validate_error(
        _claim_the_foreign_booth(client, env),
        ApiErrorId.BOOTH_NOT_IN_SHOW,
        422,
    )


def test_the_rejected_cross_show_claim_writes_nothing_on_either_floor(
    client: ApiClient,
):
    """
    Nothing is created and the foreign hold is left pointing where it was.

    "**Referential coherence**, in this order: appointment ownership
    (`ERR_APPOINTMENT_EXHIBITOR_MISMATCH`), booth-to-show membership
    (`ERR_BOOTH_NOT_IN_SHOW`), registration-to-show membership
    (`ERR_REGISTRATION_SHOW_MISMATCH`), rebook target validity
    (`ERR_REBOOK_TARGET_INVALID`), combine-set validity
    (`ERR_INVALID_COMBINE_SET`)."

    Design: Difficulty/priority_pair_validation_conflict/holding_a_foreign_shows_booth_reports_not_in_show_not_unavailable
    """
    env = _two_hall_env(client)
    _claim_the_foreign_booth(client, env)

    rows, meta = validate_paginated(
        client.list_space_contracts(
            fx.DIRECTOR_HEADERS, {"show_id": env["home"]["show"]["id"]}
        )
    )
    assert rows == []
    assert meta["total_count"] == 0

    foreign = fx.read_booth(client, env["away"]["booth_by_number"]["X100"]["id"])
    assert foreign["space_contract_id"] == env["away"]["contract"]["id"]
    assert foreign["status"] == BoothStatus.HELD

    home_show = fx.read_show(client, env["home"]["show"]["id"])
    assert home_show["held_net_sqft"] == 0
    assert home_show["available_net_sqft"] == 600


A200 = f.booth_payload("A200", 20, 20, location_class="CORNER",
                       premium_zone="MAIN_AISLE", max_height_ft=16)
C060 = f.inline_booth_payload("C060", 10, 20)
LATE_CLOCK = "2028-01-10T11:30:00Z"


def _suspended_with_active_slot(client: ApiClient) -> dict:
    """
    A suspended exhibitor still holding an `ACTIVE` desk slot on next year's
    edition, whose window the clock has already run past.
    """
    fx.set_clock(client, CLOCK)
    this_year = fx.published_show(client, [A100, C050])
    exhibitor = fx.exhibitor(client, "Nordic Furnishings", consecutive_years=6)
    exhibitor_headers = fx.make_exhibitor_headers(exhibitor["id"])
    contract = fx.signed_contract(
        client, this_year["show"]["id"], exhibitor["id"], 400,
        [this_year["booth_by_number"]["A100"]["id"]], 400000,
        premium_placement_requested=True,
    )

    next_year = fx.published_show(
        client, [A200, C060], venue_contract=this_year["venue_contract"],
        edition_year=2028, move_in_start="2028-03-01", event_start="2028-03-05",
        event_end="2028-03-07", move_out_end="2028-03-09",
        base_rate_cents_per_sqft=3400,
    )
    appointment = fx.active_appointment(
        client, next_year["show"]["id"], exhibitor["id"], 1,
        "2028-01-10T09:00:00Z", "2028-01-10T11:00:00Z",
    )

    fx.transition(client, this_year["show"]["id"], ShowStatus.SELLING)
    fx.transition(client, this_year["show"]["id"], ShowStatus.ON_SITE)
    for notes in ("Cash sales taken from the booth on preview day",
                  "Repeat offence recorded by the aisle marshal"):
        fx.upheld_citation(
            client, contract["id"], make_floor_manager_headers("u_floor_1"),
            fx.make_director_headers("u_dir_1"),
            violation_type="SALES_CONDUCT", notes=notes,
        )

    fx.set_clock(client, LATE_CLOCK)
    return {
        "this_year": this_year,
        "next_year": next_year,
        "exhibitor": exhibitor,
        "exhibitor_headers": exhibitor_headers,
        "appointment": appointment,
    }


def _late_exercise(client: ApiClient, env: dict):
    show_id = env["next_year"]["show"]["id"]
    return client.exercise_appointment(
        env["appointment"]["id"],
        f.exercise_payload(fx.show_version(client, show_id), 200),
        env["exhibitor_headers"],
    )


def test_a_suspended_exhibitor_at_a_closed_window_reports_the_standing_gate(
    client: ApiClient,
):
    """
    Both the compliance gate and the schedule gate are violated by one exercise.

    "An exercise by a suspended exhibitor whose appointment window has also already
    shut reports `ERR_EXHIBITOR_SUSPENDED`, not `ERR_APPOINTMENT_WINDOW_CLOSED`:
    standing is a compliance gate, while a window is only a schedule."

    Design: Difficulty/priority_pair_validation_conflict/suspended_exhibitor_after_window_close_reports_suspension_not_window
    """
    env = _suspended_with_active_slot(client)
    slot = fx.get_success_data(
        client.get_selection_appointment(env["appointment"]["id"],
                                        fx.DIRECTOR_HEADERS)
    )
    assert slot["state"] == AppointmentState.ACTIVE
    assert slot["rank"] == 1
    exhibitor = fx.read_exhibitor(client, env["exhibitor"]["id"])
    assert exhibitor["penalty_points"] == 30
    assert exhibitor["status"] == ExhibitorStatus.SUSPENDED

    validate_error(
        _late_exercise(client, env),
        ApiErrorId.EXHIBITOR_SUSPENDED,
        422,
    )


def test_the_refused_exercise_leaves_the_slot_and_the_floor_alone(client: ApiClient):
    """
    A rejected exercise consumes neither the appointment nor any inventory.

    "A `SUSPENDED` exhibitor may not acquire new space at all: opening a space
    contract, signing one, rebooking one, exercising a selection appointment, being
    booked a selection appointment, having a sponsorship deal proposed, and having a
    sponsorship deal signed are all refused with `ERR_EXHIBITOR_SUSPENDED`."

    Design: Difficulty/priority_pair_validation_conflict/suspended_exhibitor_after_window_close_reports_suspension_not_window
    """
    env = _suspended_with_active_slot(client)
    _late_exercise(client, env)

    slot = fx.get_success_data(
        client.get_selection_appointment(env["appointment"]["id"],
                                        fx.DIRECTOR_HEADERS)
    )
    assert slot["state"] == AppointmentState.ACTIVE

    booth = fx.read_booth(client, env["next_year"]["booth_by_number"]["C060"]["id"])
    assert booth["status"] == BoothStatus.AVAILABLE

    rows, _ = validate_paginated(
        client.list_space_contracts(
            fx.DIRECTOR_HEADERS, {"show_id": env["next_year"]["show"]["id"]}
        )
    )
    assert rows == []
