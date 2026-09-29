"""Consistency: every accepted write, cascade included, is visible to the next read."""
from test_helpers import (
    factories as f,
    fixtures as fx,
    validate_paginated,
    validate_success,
)
from test_helpers.constants import CLOCK_PROCESS

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


def test_every_write_including_the_cascade_created_settlement_reads_back_at_once(api):
    """A booking, a child insertion, a triage, a release and a four-row charge are each
    followed immediately by a read, and no read ever needs a retry or a second attempt.

    PRD §2.11: "First, cascades are applied immediately and synchronously within the
    triggering request — there is no deferred or eventual settling."; "Third, a
    cascade-created child does **not** appear in the triggering response body; the response
    body of a mutation always contains the resource the endpoint nominally addresses."

    Design: Corner/consistency_model/every_write_is_visible_to_the_immediately_following_read
    """
    ctx = fx.bootstrap_network(api, clock=CLOCK_PROCESS, quotes=_JULY_NICKEL)
    facility_id = ctx["facility"]["id"]
    line = fx.create_line(api, facility_id, **_HUNDRED_KG_HOUR_LINE)

    booked = fx.book_intake(
        api,
        ctx["supplier"]["id"],
        facility_id,
        gross_mass_kg=110.0,
        packaging_tare_kg=10.0,
        declared_ni_pct=30.0,
    )
    intake_id = booked["id"]

    listed, listed_meta = validate_paginated(
        api.list_intakes(
            fx.OPERATOR, params={"facility_id": facility_id, "custody_state": "RECEIVED"}
        )
    )
    assert listed_meta["total_count"] == 1
    assert listed[0]["id"] == intake_id, "the booking is visible to the next filtered list"

    fx.identify_chemistry(api, intake_id, "NMC622")
    module = fx.add_module(api, intake_id, "M-1")
    assert float(fx.read_intake(api, intake_id)["module_mass_total_kg"]) == 100.0, (
        "the parent's derived field is updated inside the request that wrote the child"
    )

    fx.discharge(api, intake_id, soc_pct=12.0)
    fx.package(api, intake_id)
    fx.triage_module(api, module["id"], scoring_variant="CONSERVATIVE")
    graded = validate_success(api.get_module(module["id"], fx.ENGINEER))
    assert graded["status"] == "RECOVERY_QUEUE"
    assert float(graded["second_life_score"]) == 48.80
    assert graded["grade"] == "D"

    manifest = fx.submit_manifest(api, intake_id)
    fx.close_manifest(api, intake_id, manifest["id"])

    release_response = api.release_intake(intake_id, fx.OPERATOR)
    released = validate_success(release_response)
    assert released["custody_state"] == "RELEASED"
    envelope = release_response.json()
    assert envelope["response_type"] == "object"
    assert "settlement" not in envelope["data"], "the cascade-created child is not returned"

    settlements, settlement_meta = validate_paginated(
        api.list_settlements(fx.ACCOUNTANT, params={"intake_id": intake_id})
    )
    assert settlement_meta["total_count"] == 1, "yet the very next read discovers it"
    assert settlements[0]["state"] == "DRAFT"
    assert settlements[0]["variant"] == "PROVISIONAL"
    assert settlements[0]["net_payable_cents"] == 26685

    campaign = fx.create_campaign(api, line["id"], **dict(_ONE_DAY_WINDOW))
    fx.start_campaign(api, campaign["id"])
    lot = fx.open_lot(api, campaign["id"], lot_code="LOT-1")
    charged = validate_success(
        api.charge_lot(lot["id"], f.charge_lot_payload([module["id"]], lot["version"]), fx.OPERATOR)
    )
    assert float(charged["charged_mass_kg"]) == 100.0

    assert float(
        validate_success(api.get_campaign(campaign["id"], fx.OPERATOR))["committed_input_kg"]
    ) == 100.0
    charged_modules, charged_meta = validate_paginated(
        api.list_modules(fx.OPERATOR, params={"lot_id": lot["id"], "status": "CHARGED"})
    )
    assert charged_meta["total_count"] == 1
    assert charged_modules[0]["id"] == module["id"]
    assert float(fx.read_intake(api, intake_id)["assigned_mass_kg"]) == 100.0, (
        "all four rows the charge touched are consistent on the next read"
    )
