"""The emergency pipeline: triage, dispatch, diagnosis and the dispatch charge."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_instant_equals,
    assert_money,
    fixtures,
    ids_of,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]


def _premier_pair_world():
    """Two on-site tickets on a PREMIER account, one either side of severity 60."""
    fixtures.set_clock("2026-06-01T09:00:00Z")
    world = fixtures.base_world(
        account_name="Bluewater Estates",
        email="ap@bluewater.example",
        membership_tier="PREMIER",
        address_line="77 Bluewater Ln",
        distance_miles=20.0,
        household_size=5,
        has_vulnerable_occupant=False,
        depth_feet=300.0,
        drawdown=8.0,
        technician_name="Ali Nakamura",
    )
    ticket_a = fixtures.ticket_on_site(
        world["property_id"],
        world["well_id"],
        world["account_id"],
        world["technician_id"],
        8.0,
    )
    ticket_b = fixtures.ticket_on_site(
        world["property_id"],
        world["well_id"],
        world["account_id"],
        world["technician_id"],
        5.0,
    )
    world["ticket_a_id"] = ticket_a["id"]
    world["ticket_b_id"] = ticket_b["id"]
    return world


def test_a_premier_account_earns_no_credit_below_severity_sixty(api):
    """PRD 3.8: "Cause points are 45 for `WELL_DRY`, 40 for `PUMP_FAILURE`, 30 for
    `PRESSURE_TANK_FAILURE`, 25 for `CONTROL_FAILURE`, 20 for `TREATMENT_FAILURE` and 5
    for `NON_WELL_CAUSE`. Outage points are the whole hours of `reported_outage_hours`,
    discarding any fractional hour, multiplied by 3, and then capped at 30. Household
    points are the property's `household_size` multiplied by 3, capped at 15."
    PRD 3.8: "A `PREMIER` account earns a credit of the lesser of the surcharge and 20000
    cents, **but only when the severity score is at least 60** — exactly 60 unlocks it —
    and 0 below that."
    PRD 3.8: "The **pre-authorisation ceiling** is read from `membership_tier_at_intake`
    as well: 75000 cents for `NONE`, 100000 for `SELECT` and 150000 for `PREMIER`, stored
    as `preauth_cap_cents`."

    Design: Difficulty/combinatorial_formula/net_dispatch_charge_mode_a_four_input_nonlinear_premier_inversion
    """
    world = _premier_pair_world()
    ticket = validate_success(
        api.diagnose_ticket(
            world["ticket_a_id"],
            {"cause_class": "TREATMENT_FAILURE", "onsite_estimate_cents": 50000},
            world["technician_headers"],
        )
    )
    assert ticket["severity_score"] == 59
    assert_money(
        ticket["dispatch_surcharge_cents"], 14000, "EmergencyTicket.dispatch_surcharge_cents"
    )
    assert_money(
        ticket["membership_credit_cents"], 0, "EmergencyTicket.membership_credit_cents"
    )
    assert_money(
        ticket["net_dispatch_charge_cents"],
        14000,
        "EmergencyTicket.net_dispatch_charge_cents",
    )
    assert_money(ticket["preauth_cap_cents"], 150000, "EmergencyTicket.preauth_cap_cents")
    assert ticket["authorization_status"] == "PRE_AUTHORIZED"


def test_the_net_dispatch_charge_falls_as_severity_crosses_sixty(api):
    """PRD 3.8: "The **gross dispatch surcharge** is banded from that score with inclusive
    upper bounds: a score of at most 29 carries 7000 cents, a score from 30 through 59
    carries 14000 cents, and a score of 60 or above carries 24000 cents."
    PRD 3.8: "Composed end to end, this chain is **not monotone in severity for a
    `PREMIER` account**: a score of 29 nets 7000, a score of 30 nets 14000, a score of 59
    still nets 14000, and a score of 60 nets only 4000 because the credit unlocks. A more
    severe emergency can bill *less* than a moderate one."

    Design: Difficulty/combinatorial_formula/net_dispatch_charge_mode_a_four_input_nonlinear_premier_inversion
    """
    world = _premier_pair_world()
    ticket_a = validate_success(
        api.diagnose_ticket(
            world["ticket_a_id"],
            {"cause_class": "TREATMENT_FAILURE", "onsite_estimate_cents": 50000},
            world["technician_headers"],
        )
    )
    ticket_b = validate_success(
        api.diagnose_ticket(
            world["ticket_b_id"],
            {"cause_class": "PRESSURE_TANK_FAILURE", "onsite_estimate_cents": 50000},
            world["technician_headers"],
        )
    )
    assert ticket_b["severity_score"] == 60
    assert_money(
        ticket_b["dispatch_surcharge_cents"],
        24000,
        "EmergencyTicket.dispatch_surcharge_cents",
    )
    assert_money(
        ticket_b["membership_credit_cents"],
        20000,
        "EmergencyTicket.membership_credit_cents",
    )
    assert_money(
        ticket_b["net_dispatch_charge_cents"],
        4000,
        "EmergencyTicket.net_dispatch_charge_cents",
    )
    assert (
        ticket_b["net_dispatch_charge_cents"] < ticket_a["net_dispatch_charge_cents"]
    ), "A severity-60 PREMIER ticket must net less than a severity-59 one"


def _two_axis_world():
    fixtures.set_clock("2026-06-01T09:00:00Z")
    world = fixtures.base_world(
        account_name="Two Pines Holdings",
        email="ap@twopines.example",
        membership_tier="NONE",
        account_jurisdiction="JUR_BRAVO",
        property_jurisdiction="JUR_BRAVO",
        well_jurisdiction="JUR_BRAVO",
        address_line="2 Two Pines",
        drawdown=8.0,
        technician_name="Jo Vance",
    )
    ticket = fixtures.diagnosed_ticket(
        world["property_id"],
        world["well_id"],
        world["account_id"],
        world["technician_id"],
        "PUMP_FAILURE",
        120000,
        2.0,
    )
    world["ticket_id"] = ticket["id"]
    return world


def test_the_authorisation_axis_moves_without_touching_the_dispatch_axis(api):
    """PRD 3.8: "An emergency ticket carries **two independent axes on the same row**.
    `dispatch_status` is the fulfilment axis and `authorization_status` is the money axis,
    and neither constrains the other except where a precondition names the other
    explicitly."
    PRD 3.8: "**Authorising** takes `PENDING → AUTHORIZED`; it may only be performed by
    the account named on the ticket, and the account's `credit_hold` must be false or the
    answer is `ERR_ACCOUNT_ON_CREDIT_HOLD`."

    Design: Difficulty/non_linear_state_machine/emergency_ticket_two_axes_evolve_independently
    """
    world = _two_axis_world()
    before = fixtures.get_ticket(world["ticket_id"])
    assert before["dispatch_status"] == "DIAGNOSED"
    assert before["authorization_status"] == "PENDING"

    authorised = validate_success(
        api.authorize_ticket(world["ticket_id"], world["customer_headers"])
    )
    assert authorised["dispatch_status"] == "DIAGNOSED"
    assert authorised["authorization_status"] == "AUTHORIZED"


def test_the_diagnosis_figures_survive_the_authorisation_transition(api):
    """PRD 3.8: "Finally, the **authorisation axis moves as a side effect of the
    diagnosis**: when `onsite_estimate_cents` is **strictly greater** than
    `preauth_cap_cents` the axis moves `NOT_REQUIRED → PENDING`, and otherwise it moves
    `NOT_REQUIRED → PRE_AUTHORIZED`."
    PRD 3.8: "The **gross dispatch surcharge** is banded from that score with inclusive
    upper bounds: a score of at most 29 carries 7000 cents, a score from 30 through 59
    carries 14000 cents, and a score of 60 or above carries 24000 cents."
    PRD 3.8: "A `NONE` account never earns a credit."

    Design: Difficulty/non_linear_state_machine/emergency_ticket_two_axes_evolve_independently
    """
    world = _two_axis_world()
    validate_success(api.authorize_ticket(world["ticket_id"], world["customer_headers"]))
    ticket = fixtures.get_ticket(world["ticket_id"])
    assert_money(ticket["preauth_cap_cents"], 75000, "EmergencyTicket.preauth_cap_cents")
    assert ticket["severity_score"] == 55
    assert_money(
        ticket["dispatch_surcharge_cents"],
        14000,
        "EmergencyTicket.dispatch_surcharge_cents",
    )
    assert_money(
        ticket["net_dispatch_charge_cents"],
        14000,
        "EmergencyTicket.net_dispatch_charge_cents",
    )


def test_severity_component_caps_and_the_overall_ceiling_all_bind(api):
    """PRD 3.8: "Outage points are the whole hours of `reported_outage_hours`, discarding
    any fractional hour, multiplied by 3, and then capped at 30. Household points are the
    property's `household_size` multiplied by 3, capped at 15. A vulnerable occupant adds
    a flat 10 points, and adds nothing when `has_vulnerable_occupant` is false."
    PRD 3.8: "A control failure with 3.9 hours of outage, a household of 5 and a
    vulnerable occupant scores 25 plus 9 plus 15 plus 10, or 59."
    PRD 3.8: "A dry well with 40.0 hours, a household of 12 and a vulnerable occupant
    scores 45 plus 30 plus 15 plus 10, capped to 100."

    Design: Corner/calculations/corner_calc_severity_band_edges_at_59_60_and_the_hundred_point_cap
    """
    fixtures.set_clock("2026-06-01T09:00:00Z")
    account = fixtures.new_account(
        "Severity Band Co", "JUR_ALPHA", "sb@corner.example", "NONE"
    )
    technician = fixtures.new_technician("Severity Tech", "MASTER", "JUR_ALPHA")

    cases = [
        ("59 Severity", 5, True, 3.9, "CONTROL_FAILURE", 59, 14000),
        ("60 Severity", 5, False, 5.0, "PRESSURE_TANK_FAILURE", 60, 24000),
        ("100 Severity", 12, True, 40.0, "WELL_DRY", 100, 24000),
    ]
    first = None
    for address, household, vulnerable, hours, cause, score, surcharge in cases:
        prop = fixtures.new_property(
            account["id"], address, "JUR_ALPHA", 10.0, household, vulnerable
        )
        well = fixtures.new_well(prop["id"], "JUR_ALPHA", "DRILLED", 200.0)
        on_site = fixtures.ticket_on_site(
            prop["id"], well["id"], account["id"], technician["id"], hours
        )
        diagnosed = fixtures.diagnose_ticket(
            on_site["id"], technician["id"], cause, 20000
        )
        assert diagnosed["severity_score"] == score
        assert_money(
            diagnosed["dispatch_surcharge_cents"],
            surcharge,
            "EmergencyTicket.dispatch_surcharge_cents",
        )
        assert_money(
            diagnosed["membership_credit_cents"],
            0,
            "EmergencyTicket.membership_credit_cents",
        )
        assert_money(
            diagnosed["net_dispatch_charge_cents"],
            surcharge,
            "EmergencyTicket.net_dispatch_charge_cents",
        )
        if first is None:
            first = diagnosed

    assert_money(first["preauth_cap_cents"], 75000, "EmergencyTicket.preauth_cap_cents")
    assert first["authorization_status"] == "PRE_AUTHORIZED"


def test_an_out_of_area_property_cannot_be_triaged(api):
    """PRD 3.8: "**Triage** takes `INTAKE → TRIAGED` and refuses a property whose
    `service_zone` is `OUT_OF_AREA` with `ERR_OUT_OF_SERVICE_AREA` — beyond 60.0 miles the
    company simply does not go."
    PRD 3.8: "Intake stamps `intake_at` from the logical clock, copies the account's
    current `membership_tier` into `membership_tier_at_intake` — where it is frozen — and
    opens the ticket at `dispatch_status` `INTAKE` and `authorization_status`
    `NOT_REQUIRED`."

    Design: Corner/endpoints/corner_out_of_service_area_blocks_triage
    """
    fixtures.set_clock("2026-06-01T09:00:00Z")
    account = fixtures.new_account("Faraway Co", "JUR_DELTA", "fa@corner.example")
    prop = fixtures.new_property(account["id"], "61 Faraway", "JUR_DELTA", 61.0, 3)
    well = fixtures.new_well(prop["id"], "JUR_DELTA", "DUG", 40.0)
    ticket = fixtures.new_emergency_ticket(prop["id"], well["id"], account["id"], 4.0)

    assert fixtures.get_property(prop["id"])["service_zone"] == "OUT_OF_AREA"
    validate_error(
        api.triage_ticket(ticket["id"], DISPATCHER),
        ApiErrorId.ERR_OUT_OF_SERVICE_AREA.value,
        422,
    )
    stored = fixtures.get_ticket(ticket["id"])
    assert stored["dispatch_status"] == "INTAKE"
    assert stored["membership_tier_at_intake"] == "NONE"


def test_a_diagnosed_ticket_cancels_only_once_authorisation_is_declined(api):
    """PRD 3.8: "A `DECLINED` ticket is the only way a diagnosed ticket closes without a
    work order: a dispatcher may then cancel it, taking `DIAGNOSED → CANCELLED`.
    Cancellation is otherwise available from `INTAKE` and from `TRIAGED` without further
    condition."
    PRD 3.8: "A movement attempted from the wrong dispatch state is
    `ERR_EMERGENCY_DISPATCH_INVALID_STATE`; one attempted on the authorisation axis when
    it is not `PENDING` is `ERR_EMERGENCY_AUTH_INVALID_STATE`."

    Design: Corner/state_machines/corner_emergency_cancel_from_diagnosed_requires_declined_authorization
    """
    fixtures.set_clock("2026-06-01T09:00:00Z")
    world = fixtures.base_world(
        account_name="Decline Co",
        email="dc@corner.example",
        account_jurisdiction="JUR_BRAVO",
        property_jurisdiction="JUR_BRAVO",
        well_jurisdiction="JUR_BRAVO",
        address_line="14 Decline",
        technician_name="Dec Tech",
    )
    ticket = fixtures.diagnosed_ticket(
        world["property_id"],
        world["well_id"],
        world["account_id"],
        world["technician_id"],
        "PUMP_FAILURE",
        200000,
        2.0,
    )
    validate_error(
        api.cancel_ticket(ticket["id"], DISPATCHER),
        ApiErrorId.ERR_EMERGENCY_DISPATCH_INVALID_STATE.value,
        409,
    )
    declined = validate_success(
        api.decline_ticket_authorization(ticket["id"], world["customer_headers"])
    )
    assert declined["authorization_status"] == "DECLINED"

    cancelled = validate_success(api.cancel_ticket(ticket["id"], DISPATCHER))
    assert cancelled["dispatch_status"] == "CANCELLED"


def test_the_two_ticket_axes_filter_independently_on_the_list_endpoint(api):
    """PRD 3.8: "The ticket stores `assigned_technician_id`, stamps `dispatched_at` and
    computes `response_minutes` as the whole minutes from `intake_at` to `dispatched_at`,
    taking the floor of the elapsed seconds divided by sixty."
    PRD 4.13: "Request: optional filters `property_id`, `well_profile_id`, `account_id`,
    `assigned_technician_id`, `dispatch_status`, `authorization_status`, plus `limit` and
    `offset`."

    Design: Corner/endpoints/corner_endpoint_emergency_ticket_list_filters_both_axes_independently
    """
    fixtures.set_clock("2026-06-01T09:00:00Z")
    account = fixtures.new_account("Ticket Filter Co", "JUR_ALPHA", "tf@corner.example")
    prop = fixtures.new_property(account["id"], "3 Filters", "JUR_ALPHA", 10.0, 3)
    well_a = fixtures.new_well(prop["id"], "JUR_ALPHA", "DRILLED", 200.0)
    well_b = fixtures.new_well(prop["id"], "JUR_ALPHA", "DRILLED", 200.0)
    well_c = fixtures.new_well(prop["id"], "JUR_ALPHA", "DRILLED", 200.0)
    technician = fixtures.new_technician("Filter Tech", "MASTER", "JUR_ALPHA")

    ticket_a = fixtures.new_emergency_ticket(prop["id"], well_a["id"], account["id"], 1.0)
    ticket_b = fixtures.new_emergency_ticket(prop["id"], well_b["id"], account["id"], 2.0)
    validate_success(api.triage_ticket(ticket_b["id"], DISPATCHER))
    fixtures.set_clock("2026-06-01T09:37:00Z")
    validate_success(
        api.dispatch_ticket(
            ticket_b["id"], {"technician_id": technician["id"]}, DISPATCHER
        )
    )
    validate_success(
        api.arrive_ticket(ticket_b["id"], fixtures.make_technician_headers(technician["id"]))
    )
    fixtures.diagnose_ticket(ticket_b["id"], technician["id"], "PUMP_FAILURE", 20000)

    ticket_c = fixtures.new_emergency_ticket(prop["id"], well_c["id"], account["id"], 2.0)
    validate_success(api.triage_ticket(ticket_c["id"], DISPATCHER))
    fixtures.set_clock("2026-06-01T10:15:00Z")
    validate_success(
        api.dispatch_ticket(
            ticket_c["id"], {"technician_id": technician["id"]}, DISPATCHER
        )
    )
    validate_success(
        api.arrive_ticket(ticket_c["id"], fixtures.make_technician_headers(technician["id"]))
    )
    fixtures.diagnose_ticket(ticket_c["id"], technician["id"], "PUMP_FAILURE", 200000)

    row_a = fixtures.get_ticket(ticket_a["id"])
    assert row_a["dispatch_status"] == "INTAKE"
    assert row_a["authorization_status"] == "NOT_REQUIRED"
    assert row_a["response_minutes"] is None
    assert row_a["dispatched_at"] is None

    row_b = fixtures.get_ticket(ticket_b["id"])
    assert_instant_equals(
        row_b["intake_at"], "2026-06-01T09:00:00Z", "EmergencyTicket.intake_at"
    )
    assert_instant_equals(
        row_b["dispatched_at"], "2026-06-01T09:37:00Z", "EmergencyTicket.dispatched_at"
    )
    assert row_b["response_minutes"] == 37
    assert row_b["dispatch_status"] == "DIAGNOSED"
    assert row_b["authorization_status"] == "PRE_AUTHORIZED"

    row_c = fixtures.get_ticket(ticket_c["id"])
    assert_instant_equals(
        row_c["intake_at"], "2026-06-01T09:37:00Z", "EmergencyTicket.intake_at"
    )
    assert_instant_equals(
        row_c["dispatched_at"], "2026-06-01T10:15:00Z", "EmergencyTicket.dispatched_at"
    )
    assert row_c["response_minutes"] == 38
    assert row_c["dispatch_status"] == "DIAGNOSED"
    assert row_c["authorization_status"] == "PENDING"

    by_account, meta = validate_paginated(
        api.list_emergency_tickets(DISPATCHER, params={"account_id": account["id"]})
    )
    assert ids_of(by_account) == [ticket_a["id"], ticket_b["id"], ticket_c["id"]]
    assert meta["total_count"] == 3

    diagnosed, _ = validate_paginated(
        api.list_emergency_tickets(DISPATCHER, params={"dispatch_status": "DIAGNOSED"})
    )
    assert ids_of(diagnosed) == [ticket_b["id"], ticket_c["id"]]

    pending, _ = validate_paginated(
        api.list_emergency_tickets(DISPATCHER, params={"authorization_status": "PENDING"})
    )
    assert ids_of(pending) == [ticket_c["id"]]

    combined, _ = validate_paginated(
        api.list_emergency_tickets(
            DISPATCHER,
            params={
                "dispatch_status": "DIAGNOSED",
                "authorization_status": "PRE_AUTHORIZED",
            },
        )
    )
    assert ids_of(combined) == [ticket_b["id"]]

    assigned, _ = validate_paginated(
        api.list_emergency_tickets(
            DISPATCHER, params={"assigned_technician_id": technician["id"]}
        )
    )
    assert ids_of(assigned) == [ticket_b["id"], ticket_c["id"]]
