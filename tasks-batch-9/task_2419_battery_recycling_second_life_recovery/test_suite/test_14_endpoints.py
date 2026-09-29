"""Endpoint round trips: creation, action, single read, list and filter."""
from test_helpers import (
    assert_battery_passport,
    assert_discharge_event,
    assert_permit_allotment,
    assert_settlement_line_breakdown,
    assert_supplier,
    factories as f,
    fixtures as fx,
    make_supplier_rep_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.constants import CLOCK_INTAKE, CLOCK_PROCESS

_JULY_NICKEL = [
    {"metal": "NI", "effective_date": "2026-07-01T00:00:00.000Z", "price_cents_per_kg": 1600}
]
_FOUR_METALS_JULY = [
    {"metal": "NI", "effective_date": "2026-07-01T00:00:00.000Z", "price_cents_per_kg": 1600},
    {"metal": "CO", "effective_date": "2026-07-01T00:00:00.000Z", "price_cents_per_kg": 4000},
    {"metal": "LI", "effective_date": "2026-07-01T00:00:00.000Z", "price_cents_per_kg": 8000},
    {"metal": "CU", "effective_date": "2026-07-01T00:00:00.000Z", "price_cents_per_kg": 900},
]
_HUNDRED_KG_HOUR_LINE = {
    "line_code": "HYD-1",
    "line_type": "HYDROMET",
    "chemistry_family": "NICKEL_RICH",
    "throughput_kg_per_hour": 100.0,
}
_ONE_DAY_WINDOW = {
    "window_start": "2026-08-20T00:00:00.000Z",
    "window_end": "2026-08-21T00:00:00.000Z",
    "planned_input_kg": 1000.0,
}
_AUGUST_PERMIT = {
    "valid_from": "2026-08-01T00:00:00.000Z",
    "valid_to": "2026-08-31T23:59:59.999Z",
}
_UNKNOWN_ALLOTMENT = "77777777-7777-4777-8777-777777777777"


# --------------------------------------------------------------------------
# Permits and the compliance register
# --------------------------------------------------------------------------

def test_a_permit_allotment_round_trips_through_create_read_list_and_filter(api):
    """Two allotments on one campus are created with their declared defaults, read back
    field for field, paged, narrowed by medium, and narrowed again by status once one of
    them is suspended.

    PRD §3.8: "A new allotment starts with `status` `ACTIVE`, `consumed_kg` 0.0 and
    `suspend_reason` null."; "Allotments can be listed and filtered by `facility_id`,
    `medium` and `status`."

    Design: Corner/endpoints/permit_allotment_create_read_list_and_filter_round_trip
    """
    fx.move_clock(api, CLOCK_INTAKE)
    facility = fx.create_facility(api)

    water = validate_success(
        api.create_permit_allotment(
            f.create_permit_allotment_payload(
                facility["id"],
                medium="WATER",
                permit_no="NV-W-001",
                valid_from="2026-07-01T00:00:00.000Z",
                valid_to="2026-12-31T23:59:59.999Z",
                daily_cap_kg=500.0,
            ),
            fx.SUBMITTER,
        ),
        expected_status=201,
    )
    assert_permit_allotment(water)
    assert water["facility_id"] == facility["id"]
    assert water["status"] == "ACTIVE"
    assert float(water["consumed_kg"]) == 0.0
    assert water["suspend_reason"] is None
    assert water["version"] == 1
    assert water["created_at"] == CLOCK_INTAKE

    air = fx.create_allotment(
        api,
        facility["id"],
        medium="AIR",
        permit_no="NV-A-002",
        valid_from="2026-07-01T00:00:00.000Z",
        valid_to="2026-12-31T23:59:59.999Z",
        daily_cap_kg=250.0,
    )

    read = validate_success(api.get_permit_allotment(water["id"], fx.SUBMITTER))
    assert read["permit_no"] == "NV-W-001"
    assert read["medium"] == "WATER"
    assert float(read["daily_cap_kg"]) == 500.0
    assert read["valid_to"] == "2026-12-31T23:59:59.999Z"

    by_medium, medium_meta = validate_paginated(
        api.list_permit_allotments(fx.SUBMITTER, params={"medium": "AIR"})
    )
    assert medium_meta["total_count"] == 1
    assert by_medium[0]["id"] == air["id"]
    assert float(by_medium[0]["daily_cap_kg"]) == 250.0

    page, page_meta = validate_paginated(
        api.list_permit_allotments(fx.SUBMITTER, params={"limit": 1, "offset": 1})
    )
    assert page_meta["total_count"] == 2
    assert page_meta["has_more"] is False
    assert len(page) == 1

    suspended = validate_success(
        api.suspend_permit_allotment(
            air["id"], f.suspend_permit_payload("Stack test overdue"), fx.SUBMITTER
        )
    )
    assert suspended["status"] == "SUSPENDED"
    assert suspended["suspend_reason"] == "Stack test overdue"
    assert suspended["version"] == 2

    active, active_meta = validate_paginated(
        api.list_permit_allotments(fx.SUBMITTER, params={"status": "ACTIVE"})
    )
    assert active_meta["total_count"] == 1
    assert active[0]["id"] == water["id"]


def test_logging_incidents_walks_the_counterparty_strike_register_upward(api):
    """Three incidents against one counterparty each return the updated counterparty with
    its strike count and version one higher, and the payable ledger untouched.

    PRD §3.1: "Logging an incident against a counterparty takes an `incident_code`
    naming the incident, increases the counterparty's `quality_strike_count` by exactly
    1, advances the supplier's `version` by 1, and returns the updated supplier record."

    Design: Corner/endpoints/quality_strike_action_increments_the_supplier_register
    """
    fx.move_clock(api, CLOCK_INTAKE)
    supplier = fx.create_supplier(api)
    assert supplier["quality_strike_count"] == 0
    assert supplier["version"] == 1

    for expected_count, incident_code in enumerate(("QA-001", "QA-002", "QA-003"), start=1):
        updated = validate_success(
            api.create_quality_strike(
                supplier["id"], f.create_quality_strike_payload(incident_code), fx.SUBMITTER
            )
        )
        assert_supplier(updated)
        assert updated["id"] == supplier["id"]
        assert updated["quality_strike_count"] == expected_count
        assert updated["version"] == expected_count + 1
        assert updated["credit_hold"] is False
        assert updated["payable_balance_cents"] == 0
        assert updated["paid_to_date_cents"] == 0

    durable = fx.read_supplier(api, supplier["id"], headers=fx.ACCOUNTANT)
    assert durable["quality_strike_count"] == 3
    assert durable["version"] == 4


# --------------------------------------------------------------------------
# Charging, discharge events and the provisional settlement read
# --------------------------------------------------------------------------

def _three_module_shipment_ready_to_charge(api):
    """A released three-hundred-kilogramme shipment whose two grade-D modules wait in
    the recovery queue and whose grade-A module waits in the refurbishment queue, plus
    a running campaign with one open lot."""
    ctx = fx.bootstrap_network(api, clock=CLOCK_PROCESS, quotes=_JULY_NICKEL)
    walked = fx.advance_intake(
        ctx,
        stop_after="released",
        intake={"gross_mass_kg": 310.0, "packaging_tare_kg": 10.0},
        modules=(
            {
                "serial_code": "M-D1",
                "min_cell_capacity_pct": 58.0,
                "mean_cell_capacity_pct": 62.0,
                "cycle_count": 1200,
            },
            {
                "serial_code": "M-D2",
                "min_cell_capacity_pct": 58.0,
                "mean_cell_capacity_pct": 62.0,
                "cycle_count": 1200,
            },
            {
                "serial_code": "M-A",
                "min_cell_capacity_pct": 88.0,
                "mean_cell_capacity_pct": 92.0,
                "cycle_count": 400,
            },
        ),
    )
    modules = walked["modules"]
    fx.triage_module(api, modules[0]["id"], scoring_variant="CONSERVATIVE")
    fx.triage_module(api, modules[1]["id"], scoring_variant="CONSERVATIVE")
    fx.triage_module(api, modules[2]["id"], scoring_variant="FLEET_AVERAGE")

    ctx["line"] = fx.create_line(api, ctx["facility"]["id"], **_HUNDRED_KG_HOUR_LINE)
    ctx["campaign"] = fx.create_campaign(api, ctx["line"]["id"], **_ONE_DAY_WINDOW)
    ctx["campaign"] = fx.start_campaign(api, ctx["campaign"]["id"])
    ctx["lot"] = fx.open_lot(api, ctx["campaign"]["id"], lot_code="LOT-1")
    ctx["walked"] = walked
    return ctx


def test_a_charge_naming_one_ineligible_module_commits_none_of_them(api):
    """The refurbishment-queue module poisons the whole array, an empty array is
    malformed, and only the all-eligible array moves any mass.

    PRD §3.7: "A `PlantOperator` charges a lot by supplying `module_ids`, a non-empty
    array of module identifiers, together with the `expected_lot_version` described in
    §2.8."; "A successful charge moves the lot `OPEN → CHARGED` and moves every named
    module `RECOVERY_QUEUE → CHARGED` with its `lot_id` set to that lot."

    Design: Corner/endpoints/charge_of_a_module_list_commits_all_or_nothing
    """
    ctx = _three_module_shipment_ready_to_charge(api)
    lot_id = ctx["lot"]["id"]
    intake_id = ctx["walked"]["intake"]["id"]
    d1, d2, a = [module["id"] for module in ctx["walked"]["modules"]]

    assert validate_success(api.get_module(d1, fx.OPERATOR))["status"] == "RECOVERY_QUEUE"
    assert validate_success(api.get_module(a, fx.OPERATOR))["status"] == "REFURB_QUEUE"
    assert ctx["lot"]["version"] == 1

    validate_error(
        api.charge_lot(lot_id, f.charge_lot_payload([a, d1], 1), fx.OPERATOR),
        "ERR_MODULE_NOT_IN_RECOVERY_QUEUE",
        409,
    )
    rejected_lot = fx.read_lot(api, lot_id)
    assert rejected_lot["status"] == "OPEN"
    assert float(rejected_lot["charged_mass_kg"]) == 0.0
    assert rejected_lot["version"] == 1
    assert validate_success(api.get_module(d1, fx.OPERATOR))["lot_id"] is None
    assert validate_success(api.get_module(a, fx.OPERATOR))["status"] == "REFURB_QUEUE"
    assert float(fx.read_intake(api, intake_id)["assigned_mass_kg"]) == 0.0
    assert float(
        validate_success(api.get_campaign(ctx["campaign"]["id"], fx.OPERATOR))[
            "committed_input_kg"
        ]
    ) == 0.0

    validate_error(
        api.charge_lot(lot_id, f.charge_lot_payload([], 1), fx.OPERATOR),
        "ERR_INVALID_REQUEST",
        400,
    )
    assert fx.read_lot(api, lot_id)["version"] == 1

    charged = validate_success(
        api.charge_lot(lot_id, f.charge_lot_payload([d1, d2], 1), fx.OPERATOR)
    )
    assert charged["status"] == "CHARGED"
    assert float(charged["charged_mass_kg"]) == 200.000
    assert charged["version"] == 2
    for module_id in (d1, d2):
        module = validate_success(api.get_module(module_id, fx.OPERATOR))
        assert module["status"] == "CHARGED"
        assert module["lot_id"] == lot_id

    intake = fx.read_intake(api, intake_id)
    assert float(intake["module_mass_total_kg"]) == 300.0
    assert float(intake["assigned_mass_kg"]) == 200.0
    assert float(intake["unassigned_mass_kg"]) == 100.0
    campaign = validate_success(api.get_campaign(ctx["campaign"]["id"], fx.OPERATOR))
    assert float(campaign["committed_input_kg"]) == 200.000


def test_a_discharge_event_binds_a_lot_to_the_permit_it_is_charged_against(api):
    """An unknown permit is a 404 that creates nothing, while the accepted booking is
    reachable from either side of the link and draws down the permit's allowance.

    PRD §3.8: "On success the event is created with `status` `POSTED` and `void_reason`
    null, the allotment's `consumed_kg` increases by the event's `mass_kg` rounded half
    up to three decimals, and the allotment's `version` increments by 1."; "Discharge
    events can be listed and filtered by `allotment_id`, `lot_id` and `status`."

    Design: Corner/endpoints/discharge_event_links_a_lot_to_a_permit_allotment
    """
    ctx = fx.bootstrap_network(api, clock=CLOCK_PROCESS, quotes=None)
    allotment = fx.create_allotment(
        api, ctx["facility"]["id"], daily_cap_kg=500.0, **_AUGUST_PERMIT
    )
    assert allotment["version"] == 1
    assert float(allotment["consumed_kg"]) == 0.0

    line = fx.create_line(api, ctx["facility"]["id"], **_HUNDRED_KG_HOUR_LINE)
    campaign = fx.start_campaign(
        api, fx.create_campaign(api, line["id"], **_ONE_DAY_WINDOW)["id"]
    )
    lot = fx.open_lot(api, campaign["id"], lot_code="LOT-1")
    assert lot["status"] == "OPEN"

    validate_error(
        api.create_discharge_event(
            lot["id"],
            f.create_discharge_event_payload(
                _UNKNOWN_ALLOTMENT, "2026-08-20T06:00:00.000Z", 10.0
            ),
            fx.SUBMITTER,
        ),
        "ERR_PERMIT_NOT_FOUND",
        404,
    )
    _, empty_meta = validate_paginated(api.list_discharge_events(fx.SUBMITTER))
    assert empty_meta["total_count"] == 0

    event = validate_success(
        api.create_discharge_event(
            lot["id"],
            f.create_discharge_event_payload(
                allotment["id"], "2026-08-20T06:00:00.000Z", 10.0, analyte="NICKEL_DISSOLVED"
            ),
            fx.SUBMITTER,
        ),
        expected_status=201,
    )
    assert_discharge_event(event)
    assert event["status"] == "POSTED"
    assert event["void_reason"] is None
    assert event["lot_id"] == lot["id"]
    assert event["allotment_id"] == allotment["id"]
    assert event["version"] == 1

    drawn = fx.read_allotment(api, allotment["id"])
    assert float(drawn["consumed_kg"]) == 10.0
    assert drawn["version"] == 2

    for filters in ({"allotment_id": allotment["id"]}, {"lot_id": lot["id"]}):
        rows, meta = validate_paginated(api.list_discharge_events(fx.SUBMITTER, params=filters))
        assert meta["total_count"] == 1, f"{filters} must find the one booked event"
        assert rows[0]["id"] == event["id"]

    read = validate_success(api.get_discharge_event(event["id"], fx.SUBMITTER))
    assert float(read["mass_kg"]) == 10.0
    assert read["analyte"] == "NICKEL_DISSOLVED"
    assert read["event_date"] == "2026-08-20T06:00:00.000Z"


def test_the_provisional_settlement_read_shows_every_payable_metal_line(api):
    """The settlement cut at release is found only through the list, and its four lines
    walk NI, CO, LI, CU with their own prices, shares and already-rounded cents.

    PRD §3.5: "Each metal contributes one entry to the settlement's `line_breakdown`
    array, and each entry carries `metal`, `contained_kg`, `unit_price_cents_per_kg`,
    `payable_share` and `line_cents`. The settlement's `gross_cents` is the sum of the
    `line_cents` values, each already rounded to whole cents at its own line before the
    sum is taken."

    Design: Corner/endpoints/provisional_settlement_read_exposes_the_per_metal_line_breakdown
    """
    ctx = fx.bootstrap_network(api, clock=CLOCK_INTAKE, quotes=_FOUR_METALS_JULY)
    walked = fx.advance_intake(
        ctx,
        stop_after="manifest_closed",
        intake={
            "gross_mass_kg": 110.0,
            "packaging_tare_kg": 10.0,
            "declared_ni_pct": 12.0,
            "declared_co_pct": 6.0,
            "declared_li_pct": 2.0,
            "declared_cu_pct": 5.0,
            "moisture_pct": 0.0,
            "foreign_material_pct": 0.0,
        },
        modules=(),
    )
    intake_id = walked["intake"]["id"]

    released = fx.release(api, intake_id)
    assert released["custody_state"] == "RELEASED"
    assert released["released_at"] == CLOCK_INTAKE
    assert "settlement" not in released, (
        "the settlement is a cascade-created child and never rides the release response"
    )

    listed, meta = validate_paginated(
        api.list_settlements(fx.ACCOUNTANT, params={"intake_id": intake_id})
    )
    assert meta["total_count"] == 1
    settlement = listed[0]
    assert settlement["variant"] == "PROVISIONAL"
    assert settlement["state"] == "DRAFT"
    assert settlement["price_basis_date"] == CLOCK_INTAKE
    assert settlement["max_variance_pp"] is None
    assert settlement["gross_cents"] == 37388

    read = validate_success(
        api.get_settlement(settlement["id"], make_supplier_rep_headers(ctx["supplier"]["id"]))
    )
    assert_settlement_line_breakdown(read)
    expected = (
        ("NI", 12.000, 1600, 0.70, 12768),
        ("CO", 6.000, 4000, 0.70, 15960),
        ("LI", 2.000, 8000, 0.55, 7040),
        ("CU", 5.000, 900, 0.40, 1620),
    )
    lines = read["line_breakdown"]
    assert len(lines) == 4
    for line, (metal, contained, price, share, cents) in zip(lines, expected):
        assert line["metal"] == metal
        assert float(line["contained_kg"]) == contained
        assert line["unit_price_cents_per_kg"] == price
        assert float(line["payable_share"]) == share
        assert line["line_cents"] == cents, f"{metal} line must round at its own line"

    assert read["gross_cents"] == 37388
    assert float(read["processing_fee_pct"]) == 0.12
    assert read["processing_fee_cents"] == 4487
    assert float(read["quality_deduction_pct"]) == 0.0
    assert read["quality_deduction_cents"] == 0
    assert read["pre_surcharge_net_cents"] == 32901
    assert read["hazmat_surcharge_cents"] == 1645
    assert read["net_payable_cents"] == 31256


# --------------------------------------------------------------------------
# Battery passports
# --------------------------------------------------------------------------

def _two_finalized_lots_at_thirty_and_forty_percent(api):
    """Two lots off the same running campaign, one recovering thirty percent of its
    charge and one recovering forty, each finalized at the tolerance floor."""
    ctx = fx.bootstrap_network(api, clock=CLOCK_PROCESS, quotes=_JULY_NICKEL)
    first = fx.advance_intake(ctx, stop_after="released", modules=({"serial_code": "M-A"},))
    second = fx.advance_intake(ctx, stop_after="released", modules=({"serial_code": "M-B"},))
    for walked in (first, second):
        fx.triage_module(api, walked["modules"][0]["id"])

    line = fx.create_line(api, ctx["facility"]["id"], **_HUNDRED_KG_HOUR_LINE)
    campaign = fx.start_campaign(
        api, fx.create_campaign(api, line["id"], **_ONE_DAY_WINDOW)["id"]
    )

    lean = fx.open_lot(api, campaign["id"], lot_code="LOT-A")
    rich = fx.open_lot(api, campaign["id"], lot_code="LOT-B")
    fx.charge_lot(api, lean["id"], [first["modules"][0]["id"]])
    fx.charge_lot(api, rich["id"], [second["modules"][0]["id"]])

    fx.book_output(api, lean["id"], "NI", 30.0, 99.0)
    lean = fx.finalize_lot(api, lean["id"], 67.0)
    fx.book_output(api, rich["id"], "NI", 30.0, 99.0)
    fx.book_output(api, rich["id"], "MN", 10.0, 96.0)
    rich = fx.finalize_lot(api, rich["id"], 57.0)

    assert float(lean["mass_balance_pct"]) == 97.00
    assert float(lean["recycled_content_pct"]) == 30.00
    assert float(rich["mass_balance_pct"]) == 97.00
    assert float(rich["recycled_content_pct"]) == 40.00
    return lean, rich


def test_a_certificate_is_refused_below_the_recycled_content_floor_and_never_duplicated(api):
    """The thirty-percent lot cannot be certified at all, the forty-percent lot certifies
    once with its assay ledger copied onto the certificate, and a second code is refused.

    PRD §3.8: "Issuance is refused with `ERR_RECYCLED_CONTENT_BELOW_MINIMUM` when the
    lot's `recycled_content_pct` is below 35.00, and refused with
    `ERR_PASSPORT_ALREADY_ISSUED` when the lot already has a passport whose `status` is
    `ISSUED`."

    Design: Corner/endpoints/passport_issue_requires_the_lot_to_clear_the_recycled_content_floor
    """
    lean, rich = _two_finalized_lots_at_thirty_and_forty_percent(api)

    validate_error(
        api.issue_passport(
            lean["id"], f.issue_passport_payload("BP-A-1", "Aurora Cathode"), fx.CERTIFIER
        ),
        "ERR_RECYCLED_CONTENT_BELOW_MINIMUM",
        422,
    )
    _, lean_meta = validate_paginated(
        api.list_passports(fx.CERTIFIER, params={"lot_id": lean["id"]})
    )
    assert lean_meta["total_count"] == 0

    passport = validate_success(
        api.issue_passport(
            rich["id"], f.issue_passport_payload("BP-B-1", "Aurora Cathode"), fx.CERTIFIER
        ),
        expected_status=201,
    )
    assert_battery_passport(passport)
    assert passport["lot_id"] == rich["id"]
    assert passport["status"] == "ISSUED"
    assert passport["revoked_reason"] is None
    assert float(passport["recycled_content_pct"]) == 40.00
    assert passport["issued_at"] == CLOCK_PROCESS
    assert passport["version"] == 1
    assert [
        (entry["metal"], float(entry["recovered_mass_kg"]), float(entry["assay_purity_pct"]))
        for entry in passport["metal_content"]
    ] == [("NI", 30.000, 99.0), ("MN", 10.000, 96.0)]

    validate_error(
        api.issue_passport(
            rich["id"], f.issue_passport_payload("BP-B-2", "Aurora Cathode"), fx.CERTIFIER
        ),
        "ERR_PASSPORT_ALREADY_ISSUED",
        409,
    )
    still_one, rich_meta = validate_paginated(
        api.list_passports(fx.CERTIFIER, params={"lot_id": rich["id"]})
    )
    assert rich_meta["total_count"] == 1
    assert still_one[0]["passport_code"] == "BP-B-1"


def test_revoking_a_certificate_is_a_one_way_door(api):
    """The first revocation carries its reason onto the record, the second is refused,
    and the status filter stops finding the row while the lot filter still does.

    PRD §3.8: "Revoking a certificate carries a `revoked_reason`, requires `status` to
    be `ISSUED` — otherwise `ERR_PASSPORT_NOT_ISSUED` — moves it `ISSUED → REVOKED`, and
    increments its `version` by 1."

    Design: Corner/endpoints/passport_revocation_locks_the_certificate
    """
    ctx = fx.finalized_lot(
        api,
        processing={"outputs": (("NI", 30.0, 99.0), ("MN", 10.0, 96.0)), "residue_mass_kg": 57.0},
    )
    lot_id = ctx["lot"]["id"]
    assert float(ctx["lot"]["recycled_content_pct"]) == 40.00

    passport = fx.issue_passport(api, lot_id, passport_code="BP-1")
    assert passport["status"] == "ISSUED"
    assert passport["version"] == 1

    revoked = validate_success(
        api.revoke_passport(
            passport["id"],
            f.revoke_passport_payload("Customer audit found a chain-of-custody gap"),
            fx.CERTIFIER,
        )
    )
    assert revoked["status"] == "REVOKED"
    assert revoked["revoked_reason"] == "Customer audit found a chain-of-custody gap"
    assert revoked["version"] == 2

    validate_error(
        api.revoke_passport(
            passport["id"], f.revoke_passport_payload("Duplicate revocation"), fx.CERTIFIER
        ),
        "ERR_PASSPORT_NOT_ISSUED",
        409,
    )
    durable = validate_success(api.get_passport(passport["id"], fx.CERTIFIER))
    assert durable["status"] == "REVOKED"
    assert durable["revoked_reason"] == "Customer audit found a chain-of-custody gap"
    assert durable["version"] == 2

    _, issued_meta = validate_paginated(
        api.list_passports(fx.CERTIFIER, params={"lot_id": lot_id, "status": "ISSUED"})
    )
    assert issued_meta["total_count"] == 0
    _, all_meta = validate_paginated(
        api.list_passports(fx.CERTIFIER, params={"lot_id": lot_id})
    )
    assert all_meta["total_count"] == 1


# --------------------------------------------------------------------------
# Line re-plumbing and campus suspension
# --------------------------------------------------------------------------

def test_a_line_is_re_plumbed_freely_until_a_campaign_is_actually_running(api):
    """Two re-plumbing calls land while the campaign is only scheduled, and the third is
    refused the moment the campaign starts, leaving the family and the version alone.

    PRD §3.1: "It is refused with `ERR_LINE_HAS_RUNNING_CAMPAIGN` while any campaign on
    that line has status `RUNNING`, and it advances the line's `version` by 1 on
    success."

    Design: Corner/endpoints/replumbing_a_line_is_blocked_while_a_campaign_runs_on_it
    """
    ctx = fx.bootstrap_network(api, clock=CLOCK_PROCESS, quotes=None)
    line = fx.create_line(api, ctx["facility"]["id"], **_HUNDRED_KG_HOUR_LINE)
    assert line["chemistry_family"] == "NICKEL_RICH"
    assert line["version"] == 1

    campaign = fx.create_campaign(api, line["id"], **_ONE_DAY_WINDOW)
    assert campaign["status"] == "SCHEDULED"

    switched = validate_success(
        api.replumb_processing_line(line["id"], f.replumb_payload("IRON_PHOSPHATE"), fx.ADMIN)
    )
    assert switched["chemistry_family"] == "IRON_PHOSPHATE"
    assert switched["version"] == 2

    switched_back = validate_success(
        api.replumb_processing_line(line["id"], f.replumb_payload("NICKEL_RICH"), fx.ADMIN)
    )
    assert switched_back["chemistry_family"] == "NICKEL_RICH"
    assert switched_back["version"] == 3

    running = fx.start_campaign(api, campaign["id"])
    assert running["status"] == "RUNNING"

    validate_error(
        api.replumb_processing_line(line["id"], f.replumb_payload("IRON_PHOSPHATE"), fx.ADMIN),
        "ERR_LINE_HAS_RUNNING_CAMPAIGN",
        409,
    )
    blocked = validate_success(api.get_processing_line(line["id"], fx.ADMIN))
    assert blocked["chemistry_family"] == "NICKEL_RICH"
    assert blocked["version"] == 3


def test_a_suspended_campus_takes_no_arriving_shipment_while_its_neighbour_does(api):
    """The same booking body is refused at the suspended campus and accepted at the
    active one, so nothing lands on the closed site.

    PRD §3.1: "A `SUSPENDED` campus is closed to new business: any attempt to book an
    arriving shipment into it is rejected with `ERR_FACILITY_SUSPENDED`."

    Design: Corner/endpoints/intake_booking_is_refused_at_a_suspended_campus
    """
    fx.move_clock(api, CLOCK_INTAKE)
    closed = fx.create_facility(
        api,
        name="Sparks Annex",
        status="SUSPENDED",
        mech_capacity_kg_per_day=1000.0,
        hydro_capacity_kg_per_day=500.0,
    )
    assert closed["status"] == "SUSPENDED"
    open_campus = fx.create_facility(api)
    assert open_campus["status"] == "ACTIVE"
    supplier = fx.create_supplier(api)

    validate_error(
        api.create_intake(
            f.create_intake_payload(supplier["id"], closed["id"]), fx.CLERK
        ),
        "ERR_FACILITY_SUSPENDED",
        422,
    )
    _, closed_meta = validate_paginated(
        api.list_intakes(fx.CLERK, params={"facility_id": closed["id"]})
    )
    assert closed_meta["total_count"] == 0

    booked = validate_success(
        api.create_intake(
            f.create_intake_payload(supplier["id"], open_campus["id"]), fx.CLERK
        ),
        expected_status=201,
    )
    assert booked["custody_state"] == "RECEIVED"
    assert float(booked["net_mass_kg"]) == 100.0
    assert booked["facility_id"] == open_campus["id"]

    listed, open_meta = validate_paginated(
        api.list_intakes(fx.CLERK, params={"facility_id": open_campus["id"]})
    )
    assert open_meta["total_count"] == 1
    assert listed[0]["id"] == booked["id"]
