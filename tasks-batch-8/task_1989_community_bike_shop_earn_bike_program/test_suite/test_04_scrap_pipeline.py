"""Scrap pipeline: per-ticket rounding statement (queue A) and scrap corner
cases (queue B)."""
from test_helpers import (
    api_client, validate_success, validate_error,
    make_donor, make_bike, triage_bike, make_scrap_pending_bike, make_scrapped_bike,
    TEST_USERS, ApiErrorId,
)

COORD = TEST_USERS["coordinator_headers"]
DIRECTOR = TEST_USERS["director_headers"]


def _aluminum_scrapped_bike(donor_id: str, serial: str, bike_type: str,
                            wheel: float, weight: float):
    bike, ticket = make_scrap_pending_bike(
        donor_id, material="ALUMINUM", weight_kg=weight, recycler_name="RecCo"
    )
    # recreate with specific serial/type: build manually for serial control
    return bike, ticket


class TestScrapStatementPerTicketRounding:
    def test_three_aluminum_tickets_sum_already_rounded(self):
        """PRD §3.13: "Because each ticket's payout was rounded at creation, the
        statement sums already-rounded values — never re-rounding a month of raw
        weights." and "The payout is fixed per ticket: weight times the material
        rate — 15 cents per kilogram for steel, 85 for aluminum, 10 for mixed —
        rounded half up to whole cents at creation."

        Design: Difficulty/combinatorial_formula/scrap_statement_per_ticket_rounding_mode_b
        """
        donor = make_donor(display_name="D S", donor_type="ORGANIZATION", email="ds@x.org")
        payouts = []
        tickets = []
        for serial, btype, wheel in (
            ("SN-S1", "ROAD", 27), ("SN-S2", "MTB", 26), ("SN-S3", "HYBRID", 28)
        ):
            bike = make_bike(donor["id"], serial_number=serial, bike_type=btype,
                             wheel_size_inches=wheel)
            triage_bike(bike["id"], "D", True)
            validate_success(
                api_client.route_bike(bike["id"], {"destination": "SCRAP"}, COORD)
            )
            t = validate_success(
                api_client.create_scrap_ticket(
                    bike["id"],
                    {"material": "ALUMINUM", "weight_kg": 2.5, "recycler_name": "RecCo"},
                    COORD,
                ),
                expected_status=201,
            )
            tickets.append(t)
            payouts.append(t["payout_cents"])
            validate_success(api_client.pickup_scrap_ticket(t["id"], DIRECTOR))
        assert payouts == [213, 213, 213]

        stmt = validate_success(
            api_client.get_scrap_statement(DIRECTOR, params={"month": "2026-08"})
        )
        assert stmt["ticket_count"] == 3
        assert stmt["total_payout_cents"] == 639

    def test_scrapped_bikes_terminal_after_pickup(self):
        """PRD §3.13: "Confirming pickup is a director's action against an `OPEN`
        ticket (anything else is rejected with `ERR_TICKET_NOT_OPEN`): the
        ticket moves to `PICKED_UP` with `picked_up_at` stamped from the clock,
        the bike moves `SCRAP_PENDING → SCRAPPED`, and both records' versions
        bump."

        Design: Difficulty/combinatorial_formula/scrap_statement_per_ticket_rounding_mode_b
        """
        donor = make_donor(display_name="D S2", donor_type="ORGANIZATION", email="ds2@x.org")
        bike, ticket = make_scrapped_bike(donor["id"], material="ALUMINUM", weight_kg=2.5)
        assert ticket["payout_cents"] == 213
        assert ticket["status"] == "PICKED_UP"
        assert bike["status"] == "SCRAPPED"


class TestScrapCorners:
    def test_scrapped_bike_terminal_lockdown(self):
        """PRD §3.13: "Confirming pickup is a director's action against an
        `OPEN` ticket (anything else is rejected with `ERR_TICKET_NOT_OPEN`)"
        and PRD §2.7: "`ERR_INVALID_STATE` when no more specific code applies".

        Design: Corner/state_machines/scrapped_bike_terminal_lockdown
        """
        donor = make_donor(display_name="D TL", donor_type="INDIVIDUAL", email="dtl@x.org")
        bike, ticket = make_scrapped_bike(donor["id"], material="STEEL", weight_kg=9.0)
        # payout round(9.0 * 15) == 135
        assert ticket["payout_cents"] == 135

        r1 = api_client.triage_bike(bike["id"], {"condition_grade": "B", "frame_damage": False}, COORD)
        validate_error(r1, ApiErrorId.ERR_INVALID_STATE)
        r2 = api_client.route_bike(bike["id"], {"destination": "REFURBISH"}, COORD)
        validate_error(r2, ApiErrorId.ERR_INVALID_STATE)
        r3 = api_client.create_scrap_ticket(
            bike["id"], {"material": "STEEL", "weight_kg": 5.0, "recycler_name": "RecCo"}, COORD
        )
        validate_error(r3, ApiErrorId.ERR_INVALID_STATE)
        bike_after = validate_success(api_client.get_bike(bike["id"], COORD))
        assert bike_after["status"] == "SCRAPPED"

    def test_scrap_pickup_twice_returns_ticket_not_open(self):
        """PRD §3.13: "Confirming pickup is a director's action against an
        `OPEN` ticket (anything else is rejected with `ERR_TICKET_NOT_OPEN`)"
        and "The recycler statement aggregates a calendar month: the sum of
        `payout_cents` over tickets picked up within that month."

        Design: Corner/validations/scrap_pickup_twice_returns_ticket_not_open
        """
        donor = make_donor(display_name="D PT", donor_type="INDIVIDUAL", email="dpt@x.org")
        bike, ticket = make_scrapped_bike(donor["id"], material="STEEL", weight_kg=2.0)
        assert ticket["payout_cents"] == 30

        r = api_client.pickup_scrap_ticket(ticket["id"], DIRECTOR)
        validate_error(r, ApiErrorId.ERR_TICKET_NOT_OPEN)

        stmt = validate_success(
            api_client.get_scrap_statement(DIRECTOR, params={"month": "2026-08"})
        )
        assert stmt["ticket_count"] == 1
        assert stmt["total_payout_cents"] == 30

    def test_scrap_ticket_open_conflict_and_second_sale_pending(self):
        """PRD §3.13: "Opening a scrap ticket — against a bike that is
        `HARVESTED` or already `SCRAP_PENDING` — requires that no other open
        ticket exist for the bike, else `ERR_SCRAP_TICKET_OPEN`."

        Design: Corner/validations/scrap_ticket_open_conflict_and_second_sale_pending
        """
        donor = make_donor(display_name="D OC", donor_type="INDIVIDUAL", email="doc@x.org")
        bike, ticket = make_scrap_pending_bike(donor["id"], material="STEEL", weight_kg=8.0)
        r = api_client.create_scrap_ticket(
            bike["id"], {"material": "MIXED", "weight_kg": 3.0, "recycler_name": "RecCo"},
            COORD,
        )
        validate_error(r, ApiErrorId.ERR_SCRAP_TICKET_OPEN)
        from test_helpers import validate_paginated
        data, meta = validate_paginated(
            api_client.list_scrap_tickets(COORD, params={"bike_id": bike["id"]})
        )
        assert meta["total_count"] == 1

    def test_weight_and_quantity_bounds(self):
        """PRD §3.13: "the `weight_kg` (greater than 0 and at most 100, else
        `ERR_WEIGHT_INVALID`)" and PRD §3.3: "a `quantity` of at least 1 (else
        `ERR_QUANTITY_INVALID`)".

        Design: Corner/validations/weight_and_quantity_bounds
        """
        donor = make_donor(display_name="D WB", donor_type="INDIVIDUAL", email="dwb@x.org")
        # SCRAP_PENDING bike for the weight probes
        bike = make_bike(donor["id"], serial_number="SN-W1", bike_type="ROAD", wheel_size_inches=27)
        triage_bike(bike["id"], "D", True)
        validate_success(api_client.route_bike(bike["id"], {"destination": "SCRAP"}, COORD))

        r0 = api_client.create_scrap_ticket(
            bike["id"], {"material": "ALUMINUM", "weight_kg": 0, "recycler_name": "R"}, COORD
        )
        validate_error(r0, ApiErrorId.ERR_WEIGHT_INVALID)
        r1005 = api_client.create_scrap_ticket(
            bike["id"], {"material": "ALUMINUM", "weight_kg": 100.5, "recycler_name": "R"}, COORD
        )
        validate_error(r1005, ApiErrorId.ERR_WEIGHT_INVALID)
        ok = validate_success(
            api_client.create_scrap_ticket(
                bike["id"], {"material": "ALUMINUM", "weight_kg": 100, "recycler_name": "R"}, COORD
            ),
            expected_status=201,
        )
        assert ok["payout_cents"] == 8500

        # harvest quantity 0
        bike2 = make_bike(donor["id"], serial_number="SN-W2", bike_type="MTB", wheel_size_inches=26)
        triage_bike(bike2["id"], "D", False)
        validate_success(api_client.route_bike(bike2["id"], {"destination": "HARVEST"}, COORD))
        from test_helpers import make_volunteer, make_part, make_volunteer_headers
        v = make_volunteer(full_name="V H", email="vh@x.org")
        p = make_part(name="Wheel", category="WHEELS", unit_cost_cents=500)
        rq = api_client.create_harvest_log(
            bike2["id"], {"part_id": p["id"], "quantity": 0},
            make_volunteer_headers(v["id"]),
        )
        validate_error(rq, ApiErrorId.ERR_QUANTITY_INVALID)
