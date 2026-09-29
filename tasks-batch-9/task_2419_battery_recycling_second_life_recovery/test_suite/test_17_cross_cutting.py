"""Cross-cutting layers: the shipment's version guard and its three derived mass fields."""
from test_helpers import (
    assert_intake_mass_conservation,
    factories as f,
    fixtures as fx,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.constants import CLOCK_INTAKE, CLOCK_PROCESS

_JULY_NICKEL = [
    {"metal": "NI", "effective_date": "2026-07-01T00:00:00.000Z", "price_cents_per_kg": 1600}
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
_THREE_HUNDRED_KG = {
    "gross_mass_kg": 310.0,
    "packaging_tare_kg": 10.0,
    "declared_ni_pct": 12.0,
}


def test_replaying_a_consumed_shipment_version_loses_the_second_module_write(api):
    """The first module bumps its parent, so the version captured before it is already
    stale, and only a freshly read version lets the same body through.

    PRD §2.8: "If that value does not equal the shipment's current `version`, the request
    is rejected with `ERR_STALE_INTAKE_VERSION` and HTTP 412."; "Module creation is
    legitimately repeatable — a dismantler books one module row per module pulled from the
    pack, and each insertion recomputes the shipment's total and unassigned module mass —
    so a second insertion carrying a fresh version succeeds on its own merits."

    PRD §2.7: "4. **Request shape** — required fields present, enum values within range,
    numbers inside their declared constraints, arrays non-empty, and the three uniqueness
    constraints satisfied: a module's `serial_code` is unique within its shipment, a
    recovery output is unique per lot-and-metal pair, and a passport's `passport_code` is
    globally unique. `ERR_INVALID_REQUEST`, 400. Applies to every endpoint."

    Design: Corner/cross_cutting_complexity_layers/stale_expected_intake_version_blocks_the_second_module_write
    """
    ctx = fx.bootstrap_network(api, clock=CLOCK_INTAKE, quotes=None)
    booked = fx.book_intake(
        api, ctx["supplier"]["id"], ctx["facility"]["id"], **_THREE_HUNDRED_KG
    )
    intake_id = booked["id"]
    assert booked["version"] == 1
    identified = fx.identify_chemistry(api, intake_id, "NMC622")
    assert identified["version"] == 2, "no module exists yet"

    first = validate_success(
        api.create_module(intake_id, f.create_module_payload("M-1", 2), fx.CLERK),
        expected_status=201,
    )
    assert first["version"] == 1
    assert fx.read_intake(api, intake_id)["version"] == 3, "the child write bumped the parent"

    validate_error(
        api.create_module(intake_id, f.create_module_payload("M-2", 2), fx.CLERK),
        "ERR_STALE_INTAKE_VERSION",
        412,
    )
    validate_error(
        api.create_module(intake_id, f.create_module_payload("M-1", 1), fx.CLERK),
        "ERR_INVALID_REQUEST",
        400,
    )

    after_failures = fx.read_intake(api, intake_id)
    assert after_failures["version"] == 3, "neither refusal mutated the shipment"
    assert float(after_failures["module_mass_total_kg"]) == 100.0
    assert float(after_failures["unassigned_mass_kg"]) == 100.0
    _, meta = validate_paginated(api.list_modules(fx.CLERK, params={"intake_id": intake_id}))
    assert meta["total_count"] == 1, "exactly one module survived the three attempts"

    retried = validate_success(
        api.create_module(
            intake_id, f.create_module_payload("M-2", after_failures["version"]), fx.CLERK
        ),
        expected_status=201,
    )
    assert retried["serial_code"] == "M-2"

    reconciled = fx.read_intake(api, intake_id)
    assert reconciled["version"] == 4
    assert float(reconciled["module_mass_total_kg"]) == 200.0
    assert float(reconciled["unassigned_mass_kg"]) == 200.0
    assert_intake_mass_conservation(reconciled)


def test_the_three_derived_mass_fields_are_recomputed_at_every_source_change(api):
    """A booking, three dismantled modules and two charges out of one shipment: each of
    the three mass fields is re-derived from the module rows, and the invariant never slips.

    PRD §3.4: "Each accepted insertion recomputes the shipment's `module_mass_total_kg` as
    the sum of module masses, rounded half up to three decimals, and recomputes
    `unassigned_mass_kg` accordingly, and it increments the shipment's `version` by 1."

    PRD §3.7: "Four aggregates are then recomputed: the lot's `charged_mass_kg` as the sum
    of `mass_kg` over modules whose `lot_id` is this lot and whose `status` is `CHARGED` or
    `CONSUMED`, rounded half up to three decimals; each contributing shipment's
    `assigned_mass_kg` as the sum of `mass_kg` over its modules in `CHARGED` or `CONSUMED`,
    likewise to three decimals; each contributing shipment's `unassigned_mass_kg` as its
    `module_mass_total_kg` less its `assigned_mass_kg`; and the campaign's
    `committed_input_kg`."

    Design: Corner/cross_cutting_complexity_layers/intake_mass_derived_fields_reconcile_after_every_source_change
    """
    ctx = fx.bootstrap_network(api, clock=CLOCK_PROCESS, quotes=_JULY_NICKEL)
    booked = fx.book_intake(
        api, ctx["supplier"]["id"], ctx["facility"]["id"], **_THREE_HUNDRED_KG
    )
    intake_id = booked["id"]
    assert float(booked["net_mass_kg"]) == 300.0
    assert float(booked["module_mass_total_kg"]) == 0.0
    assert float(booked["assigned_mass_kg"]) == 0.0
    assert float(booked["unassigned_mass_kg"]) == 0.0, (
        "the derived fields start empty, not at the weighbridge mass"
    )
    assert_intake_mass_conservation(booked)

    fx.identify_chemistry(api, intake_id, "NMC622")
    first_module = fx.add_module(api, intake_id, "M-1")
    after_first = fx.read_intake(api, intake_id)
    assert float(after_first["module_mass_total_kg"]) == 100.0
    assert float(after_first["unassigned_mass_kg"]) == 100.0
    assert float(after_first["assigned_mass_kg"]) == 0.0
    assert_intake_mass_conservation(after_first)

    second_module = fx.add_module(api, intake_id, "M-2")
    third_module = fx.add_module(api, intake_id, "M-3")

    fx.discharge(api, intake_id, soc_pct=12.0)
    fx.package(api, intake_id)
    for module in (first_module, second_module, third_module):
        decision = fx.triage_module(api, module["id"], scoring_variant="CONSERVATIVE")
        assert decision["disposition"] == "MATERIAL_RECOVERY"
    manifest = fx.submit_manifest(api, intake_id)
    fx.close_manifest(api, intake_id, manifest["id"])
    fx.release(api, intake_id)

    line = fx.create_line(api, ctx["facility"]["id"], **_HUNDRED_KG_HOUR_LINE)
    campaign = fx.create_campaign(api, line["id"], **dict(_ONE_DAY_WINDOW))
    fx.start_campaign(api, campaign["id"])
    first_lot = fx.open_lot(api, campaign["id"], lot_code="LOT-1")
    second_lot = fx.open_lot(api, campaign["id"], lot_code="LOT-2")

    charged_first = fx.charge_lot(api, first_lot["id"], [first_module["id"]])
    assert float(charged_first["charged_mass_kg"]) == 100.0
    after_first_charge = fx.read_intake(api, intake_id)
    assert float(after_first_charge["module_mass_total_kg"]) == 300.0
    assert float(after_first_charge["assigned_mass_kg"]) == 100.0
    assert float(after_first_charge["unassigned_mass_kg"]) == 200.0
    assert_intake_mass_conservation(after_first_charge)

    charged_second = fx.charge_lot(
        api, second_lot["id"], [second_module["id"], third_module["id"]]
    )
    assert float(charged_second["charged_mass_kg"]) == 200.0
    after_second_charge = fx.read_intake(api, intake_id)
    assert float(after_second_charge["module_mass_total_kg"]) == 300.0
    assert float(after_second_charge["assigned_mass_kg"]) == 300.0
    assert float(after_second_charge["unassigned_mass_kg"]) == 0.0
    assert_intake_mass_conservation(after_second_charge)

    assert float(charged_first["charged_mass_kg"]) + float(charged_second["charged_mass_kg"]) == (
        float(after_second_charge["module_mass_total_kg"])
    ), "the same hundred kilogrammes are never claimed by both lots"
