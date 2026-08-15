"""Optimistic-concurrency corner tests (queue B cross_cutting) and the
derived-field reconciliation corner."""
from test_helpers import (
    api_client, validate_success, validate_error,
    make_donor, make_bike, triage_bike, make_part, restock_part,
    make_volunteer, attend_sessions, log_usage, set_clock,
    make_participant, log_hours,
    TEST_USERS, make_volunteer_headers, make_coordinator_headers,
    ApiErrorId,
)

COORD = TEST_USERS["coordinator_headers"]
DIRECTOR = TEST_USERS["director_headers"]


def _refurb_bike_with_part(part_unit_cost_cents: int = 100, restock_qty: int = 10):
    """Bike IN_REFURBISHMENT under an APPRENTICE lead; part restocked.

    Returns (bike, part, lead).
    """
    from test_helpers import make_apprentice
    donor = make_donor()
    lead = make_apprentice()
    bike = make_bike(donor["id"])
    triage_bike(bike["id"], "B", False)
    validate_success(
        api_client.route_bike(
            bike["id"],
            {"destination": "REFURBISH", "refurb_lead_volunteer_id": lead["id"]},
            COORD,
        )
    )
    part = make_part(unit_cost_cents=part_unit_cost_cents)
    part = restock_part(part["id"], restock_qty)
    return bike, part, lead


def test_occ_stale_part_version_on_usage():
    """PRD §2.6: "Logging a part usage requires the request to carry
    `expected_part_version`, equal to the `Part` record's `version` the caller
    last observed. If the part's current `version` has advanced past that value
    — because an earlier usage, restock, harvest, helmet distribution, or usage
    void has already moved `quantity_on_hand` — the create is rejected with
    `ERR_STALE_VERSION` (HTTP 412). The caller must re-read the part and
    resubmit against the fresh version."

    Design: Corner/cross_cutting/occ_stale_part_version_on_usage
    """
    bike, part, lead = _refurb_bike_with_part(part_unit_cost_cents=20, restock_qty=10)
    stale_version = part["version"]
    first = log_usage(bike["id"], part["id"], 1, stale_version, lead["id"])
    r = api_client.create_usage_log(
        bike["id"],
        {"part_id": part["id"], "quantity": 1,
         "expected_part_version": stale_version},
        make_volunteer_headers(lead["id"]),
    )
    validate_error(r, ApiErrorId.ERR_STALE_VERSION)
    fresh = validate_success(api_client.get_part(part["id"], COORD))
    second = log_usage(bike["id"], part["id"], 1, fresh["version"], lead["id"])
    assert second["id"] != first["id"]
    final = validate_success(api_client.get_part(part["id"], COORD))
    assert final["quantity_on_hand"] == 8


def test_occ_stale_participant_version_on_approve():
    """PRD §2.6: "Approving an hour log requires the request to carry
    `expected_participant_version`, equal to the `EarnABikeParticipant`
    record's `version` the caller last observed. If the participant's `version`
    has advanced — through a prior approval, a void, a quiz update, a
    reservation, or a cascaded demotion — the approval is rejected with
    `ERR_STALE_VERSION` (HTTP 412), since the caller's view of `hours_earned` is
    no longer current."

    Design: Corner/cross_cutting/occ_stale_participant_version_on_approve
    """
    p = make_participant(full_name="P OCC", contact_email="pocc@x.org",
                         age_group="ADULT")
    set_clock("2026-08-07T00:00:00Z")
    h1 = log_hours(p["id"], "2026-08-02", 2, "SHOP_HELP")
    h2 = log_hours(p["id"], "2026-08-03", 2, "SHOP_HELP")
    v1 = validate_success(api_client.get_participant(p["id"], COORD))["version"]
    validate_success(
        api_client.approve_hour_log(
            h1["id"], {"expected_participant_version": v1},
            make_coordinator_headers("sc-approver-1"),
        )
    )
    r = api_client.approve_hour_log(
        h2["id"], {"expected_participant_version": v1},
        make_coordinator_headers("sc-approver-1"),
    )
    validate_error(r, ApiErrorId.ERR_STALE_VERSION)
    v2 = validate_success(api_client.get_participant(p["id"], COORD))["version"]
    ok = validate_success(
        api_client.approve_hour_log(
            h2["id"], {"expected_participant_version": v2},
            make_coordinator_headers("sc-approver-1"),
        )
    )
    assert ok["status"] == "APPROVED"
    after = validate_success(api_client.get_participant(p["id"], COORD))
    assert after["hours_earned"] == 4


def test_unit_cost_snapshot_reconciliation():
    """PRD §2.8: "when a usage is logged, the part's current `unit_cost_cents`
    is frozen onto the usage row, and later restocks that replace the part's
    `unit_cost_cents` never rewrite existing usage rows." and PRD §3.3: "A
    successful usage snapshots the part's current `unit_cost_cents` onto the row
    — that frozen cost survives all later restocks — decrements
    `quantity_on_hand`, bumps the part's `version`, recomputes the bike's
    `parts_cost_cents` as the sum over its committed usages of each row's
    quantity times its snapshot cost, and recomputes `low_stock`."

    Design: Corner/cross_cutting/unit_cost_snapshot_reconciliation
    """
    bike, part, lead = _refurb_bike_with_part(part_unit_cost_cents=100, restock_qty=10)
    u1 = log_usage(bike["id"], part["id"], 2, part["version"], lead["id"])
    assert u1["unit_cost_cents"] == 100
    part = restock_part(part["id"], 5, unit_cost_cents=250)
    u2 = log_usage(bike["id"], part["id"], 1, part["version"], lead["id"])
    assert u2["unit_cost_cents"] == 250

    u1_after = validate_success(api_client.get_usage_log(u1["id"], COORD))
    assert u1_after["unit_cost_cents"] == 100
    bike_after = validate_success(api_client.get_bike(bike["id"], COORD))
    assert bike_after["parts_cost_cents"] == 450
