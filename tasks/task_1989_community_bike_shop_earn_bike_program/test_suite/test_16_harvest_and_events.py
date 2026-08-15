"""Harvest flow and append-only event entities (queue B entities), plus
no-work/no-harvest preconditions (queue B)."""
from test_helpers import (
    api_client, validate_success, validate_error,
    make_donor, make_bike, triage_bike, make_part, make_volunteer,
    make_harvest_queue_bike, make_apprentice,
    TEST_USERS, make_volunteer_headers,
    assert_part_harvest, is_valid_uuid, is_iso8601_timestamp,
    ApiErrorId,
)

COORD = TEST_USERS["coordinator_headers"]
DIRECTOR = TEST_USERS["director_headers"]


def test_harvest_event_entity_immutability():
    """PRD §2.4: "Four event-style resources — `PartHarvest`, `PartUsage`,
    `SafetyInspection`, and `HelmetDistribution` — are immutable once recorded
    and therefore carry only `id` and `created_at`; both `updated_at` and
    `version` are absent on those four entities."

    Design: Corner/entities/harvest_event_entity_immutability
    """
    donor = make_donor(display_name="D IM", donor_type="INDIVIDUAL", email="dim@x.org")
    bike = make_harvest_queue_bike(donor["id"])
    v = make_volunteer(full_name="V H", email="vh@x.org")
    p = make_part(name="Wheel 26", category="WHEELS", unit_cost_cents=800)
    hl = validate_success(
        api_client.create_harvest_log(
            bike["id"], {"part_id": p["id"], "quantity": 2},
            make_volunteer_headers(v["id"]),
        ),
        expected_status=201,
    )
    assert_part_harvest(hl)
    fetched = validate_success(api_client.get_harvest_log(hl["id"], COORD))
    assert_part_harvest(fetched)
    part_after = validate_success(api_client.get_part(p["id"], COORD))
    assert part_after["quantity_on_hand"] == 2


def test_no_work_recorded_and_no_harvest_recorded():
    """PRD §3.4: "only if at least one committed usage row exists against the
    bike, since a submission with no recorded work is rejected with
    `ERR_NO_WORK_RECORDED`" and PRD §3.3: "When at least one harvest row exists
    for a queued bike — attempting harvest-completion without one is rejected
    with `ERR_NO_HARVEST_RECORDED`".

    Design: Corner/validations/no_work_recorded_and_no_harvest_recorded
    """
    donor = make_donor(display_name="D NW", donor_type="INDIVIDUAL", email="dnw@x.org")
    lead = make_apprentice()
    # refurb bike with no usage yet
    b1 = make_bike(donor["id"], serial_number="SN-N1", bike_type="ROAD",
                   wheel_size_inches=27)
    triage_bike(b1["id"], "A", False)
    validate_success(
        api_client.route_bike(
            b1["id"],
            {"destination": "REFURBISH", "refurb_lead_volunteer_id": lead["id"]},
            COORD,
        )
    )
    # harvest-queue bike with no logs
    b2 = make_bike(donor["id"], serial_number="SN-N2", bike_type="MTB",
                   wheel_size_inches=26)
    triage_bike(b2["id"], "D", False)
    validate_success(
        api_client.route_bike(b2["id"], {"destination": "HARVEST"}, COORD)
    )

    r1 = api_client.submit_safety(b1["id"], make_volunteer_headers(lead["id"]))
    validate_error(r1, ApiErrorId.ERR_NO_WORK_RECORDED)
    r2 = api_client.harvest_complete(b2["id"], COORD)
    validate_error(r2, ApiErrorId.ERR_NO_HARVEST_RECORDED)
    b1_after = validate_success(api_client.get_bike(b1["id"], COORD))
    b2_after = validate_success(api_client.get_bike(b2["id"], COORD))
    assert b1_after["status"] == "IN_REFURBISHMENT"
    assert b2_after["status"] == "HARVEST_QUEUE"


def test_not_harvestable_category():
    """PRD §3.3: "helmets are purchased stock only, never stripped from donor
    bikes, so harvesting a `HELMET` SKU is rejected with
    `ERR_NOT_HARVESTABLE_CATEGORY`."

    Design: Corner/validations/not_harvestable_category
    """
    donor = make_donor(display_name="D HC", donor_type="INDIVIDUAL", email="dhc@x.org")
    bike = make_harvest_queue_bike(donor["id"])
    v = make_volunteer(full_name="V H", email="vh@x.org")
    hp = validate_success(
        api_client.create_part(
            {"name": "Helmet H", "category": "HELMET", "helmet_size": "L",
             "unit_cost_cents": 1500},
            COORD,
        ),
        expected_status=201,
    )
    r = api_client.create_harvest_log(
        bike["id"], {"part_id": hp["id"], "quantity": 1},
        make_volunteer_headers(v["id"]),
    )
    validate_error(r, ApiErrorId.ERR_NOT_HARVESTABLE_CATEGORY)
    part_after = validate_success(api_client.get_part(hp["id"], COORD))
    assert part_after["quantity_on_hand"] == 0
