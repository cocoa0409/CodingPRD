"""Parts ledger: compensating invariant (queue A), priority-pair state-vs-fiscal
(queue A), and parts corner cases (queue B)."""
from test_helpers import (
    api_client, validate_success, validate_error,
    make_donor, make_bike, triage_bike, make_part, restock_part,
    make_apprentice, log_usage,
    TEST_USERS, make_volunteer_headers, make_volunteer, attend_sessions,
    ApiErrorId,
)

COORD = TEST_USERS["coordinator_headers"]
DIRECTOR = TEST_USERS["director_headers"]


def _refurb_bike(lead):
    donor = make_donor()
    bike = make_bike(donor["id"])
    triage_bike(bike["id"], "B", False)
    validate_success(
        api_client.route_bike(
            bike["id"],
            {"destination": "REFURBISH", "refurb_lead_volunteer_id": lead["id"]},
            COORD,
        )
    )
    return bike


class TestPartStockUsageVoidConservation:
    def test_forward_usage_then_void_conserves_stock(self):
        """PRD §3.3: "A successful usage snapshots the part's current
        `unit_cost_cents` onto the row — that frozen cost survives all later
        restocks — decrements `quantity_on_hand`" and "A void flips the row to
        `VOIDED`, records the optional `reason` as `void_reason`, adds the
        quantity back to the part's `quantity_on_hand`, bumps the part's
        `version`, decrements the bike's `parts_cost_cents` by the voided row's
        quantity times its snapshot cost, and recomputes `low_stock`."

        Design: Difficulty/compensating_invariant/part_stock_usage_void_conservation
        """
        lead = make_apprentice()
        bike = _refurb_bike(lead)
        part = make_part(name="Pedal", category="DRIVETRAIN", unit_cost_cents=100)
        part = restock_part(part["id"], 10)
        assert part["quantity_on_hand"] == 10

        u1 = log_usage(bike["id"], part["id"], 3, part["version"], lead["id"])
        mid_part = validate_success(api_client.get_part(part["id"], COORD))
        assert mid_part["quantity_on_hand"] == 7
        mid_bike = validate_success(api_client.get_bike(bike["id"], COORD))
        assert mid_bike["parts_cost_cents"] == 300

        voided = validate_success(
            api_client.void_usage_log(u1["id"], {"reason": "wrong bike"}, DIRECTOR)
        )
        assert voided["status"] == "VOIDED"
        end_part = validate_success(api_client.get_part(part["id"], COORD))
        assert end_part["quantity_on_hand"] == 10
        end_bike = validate_success(api_client.get_bike(bike["id"], COORD))
        assert end_bike["parts_cost_cents"] == 0

    def test_void_restores_stock_exactly_once(self):
        """PRD §3.3: "A void flips the row to `VOIDED`, records the optional
        `reason` as `void_reason`, adds the quantity back to the part's
        `quantity_on_hand`, bumps the part's `version`, decrements the bike's
        `parts_cost_cents` by the voided row's quantity times its snapshot cost,
        and recomputes `low_stock`." and "Voiding requires the row to still be
        `COMMITTED`; voiding an already-voided row is rejected with
        `ERR_USAGE_NOT_COMMITTED`."

        Design: Difficulty/compensating_invariant/part_stock_usage_void_conservation
        """
        lead = make_apprentice()
        bike = _refurb_bike(lead)
        part = make_part(name="Pedal2", category="DRIVETRAIN", unit_cost_cents=100)
        part = restock_part(part["id"], 10)
        u1 = log_usage(bike["id"], part["id"], 3, part["version"], lead["id"])
        validate_success(
            api_client.void_usage_log(u1["id"], {"reason": "wrong bike"}, DIRECTOR)
        )
        # stock restored exactly once even in the face of the void round trip
        final_part = validate_success(api_client.get_part(part["id"], COORD))
        assert final_part["quantity_on_hand"] == 10


class TestUsageValidationCorners:
    def test_state_beats_fiscal_on_usage(self):
        """PRD §2.7: "Only after all of that does state checking begin." and
        "Fiscal checks (`ERR_INSUFFICIENT_STOCK`, `ERR_HELMET_OUT_OF_STOCK`,
        `ERR_GIVEAWAY_QUOTA_EXCEEDED`, `ERR_WEIGHT_INVALID`) come after
        temporal, and referential checks (`ERR_RECIPIENT_REFERENCE_MISMATCH`,
        `ERR_NOT_A_HELMET_SKU`, `ERR_SHIFT_NOT_CREDITABLE`) run last."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_usage
        """
        donor = make_donor(display_name="D PP", donor_type="INDIVIDUAL", email="dpp@x.org")
        bike = make_bike(donor["id"], serial_number="SN-PP", bike_type="ROAD",
                         wheel_size_inches=27)
        triage_bike(bike["id"], "A", False)  # never routed -> TRIAGED
        v = make_apprentice()  # skill/suspension gates pass
        part = make_part(name="Rare derailleur", category="DRIVETRAIN",
                         unit_cost_cents=5000)  # never restocked -> on_hand 0
        r = api_client.create_usage_log(
            bike["id"],
            {"part_id": part["id"], "quantity": 1,
             "expected_part_version": part["version"]},
            make_volunteer_headers(v["id"]),
        )
        validate_error(r, ApiErrorId.ERR_INVALID_STATE)
        part_after = validate_success(api_client.get_part(part["id"], COORD))
        assert part_after["quantity_on_hand"] == 0
        bike_after = validate_success(api_client.get_bike(bike["id"], COORD))
        assert bike_after["status"] == "TRIAGED"

    def test_state_rejection_leaves_no_trace(self):
        """PRD §2.7: "Only after all of that does state checking begin. The
        optimistic-concurrency comparison runs first among the state checks
        (`ERR_STALE_VERSION`, HTTP 412). Then come the state-machine from-state
        guards and their specialized siblings: `ERR_INVALID_STATE` when no more
        specific code applies" — a rejected usage neither decrements stock nor
        appears in the usage listing.

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_usage
        """
        from test_helpers import validate_paginated
        donor = make_donor(display_name="D PP2", donor_type="INDIVIDUAL",
                           email="dpp2@x.org")
        bike = make_bike(donor["id"], serial_number="SN-PP2", bike_type="ROAD",
                         wheel_size_inches=27)
        triage_bike(bike["id"], "A", False)
        v = make_apprentice()
        part = make_part(name="Rare derailleur 2", category="DRIVETRAIN",
                         unit_cost_cents=5000)
        r = api_client.create_usage_log(
            bike["id"],
            {"part_id": part["id"], "quantity": 1,
             "expected_part_version": part["version"]},
            make_volunteer_headers(v["id"]),
        )
        validate_error(r, ApiErrorId.ERR_INVALID_STATE)
        _, meta = validate_paginated(
            api_client.list_usage_logs(COORD, params={"bike_id": bike["id"]})
        )
        assert meta["total_count"] == 0

    def test_usage_exceeds_stock_returns_insufficient_stock(self):
        """PRD §3.3: "no more than the part's current `quantity_on_hand` (an
        overdraw is rejected with `ERR_INSUFFICIENT_STOCK`)".

        Design: Corner/validations/usage_exceeds_stock_returns_insufficient_stock
        """
        lead = make_apprentice()
        bike = _refurb_bike(lead)
        part = make_part(name="Cable", category="BRAKES", unit_cost_cents=100)
        part = restock_part(part["id"], 2)
        r = api_client.create_usage_log(
            bike["id"],
            {"part_id": part["id"], "quantity": 5,
             "expected_part_version": part["version"]},
            make_volunteer_headers(lead["id"]),
        )
        validate_error(r, ApiErrorId.ERR_INSUFFICIENT_STOCK)
        part_after = validate_success(api_client.get_part(part["id"], COORD))
        assert part_after["quantity_on_hand"] == 2

    def test_usage_void_twice_returns_usage_not_committed(self):
        """PRD §3.3: "Voiding requires the row to still be `COMMITTED`; voiding
        an already-voided row is rejected with `ERR_USAGE_NOT_COMMITTED`."

        Design: Corner/validations/usage_void_twice_returns_usage_not_committed
        """
        lead = make_apprentice()
        bike = _refurb_bike(lead)
        part = make_part(name="Grip pair", category="COCKPIT", unit_cost_cents=80)
        part = restock_part(part["id"], 5)
        u1 = log_usage(bike["id"], part["id"], 2, part["version"], lead["id"])
        validate_success(
            api_client.void_usage_log(u1["id"], {"reason": "wrong part"}, DIRECTOR)
        )
        r = api_client.void_usage_log(u1["id"], {"reason": "again"}, DIRECTOR)
        validate_error(r, ApiErrorId.ERR_USAGE_NOT_COMMITTED)
        part_after = validate_success(api_client.get_part(part["id"], COORD))
        assert part_after["quantity_on_hand"] == 5

    def test_existence_before_state_on_usage(self):
        """PRD §2.7: "Existence comes next: path identifiers are resolved left
        to right, then body foreign keys (`donor_id`, `part_id`, `bike_id`,
        `volunteer_id`, `buyer_membership_id`, `helmet_part_id`, the helmet
        recipient references, `shift_id`), and any missing record yields
        `ERR_NOT_FOUND` (HTTP 404)."

        Design: Corner/validations/existence_before_state_on_usage
        """
        part = make_part(name="Solo part", category="MISC", unit_cost_cents=10)
        v = make_volunteer(full_name="V X", email="vx@x.org")
        r = api_client.create_usage_log(
            "00000000-0000-4000-8000-000000000000",
            {"part_id": part["id"], "quantity": 1,
             "expected_part_version": part["version"]},
            make_volunteer_headers(v["id"]),
        )
        validate_error(r, ApiErrorId.ERR_NOT_FOUND)

    def test_uniqueness_constraints(self):
        """PRD §3.1: "a `serial_number` that must be unique across every bike
        the shop has ever taken in (a duplicate is rejected with
        `ERR_SERIAL_NUMBER_CONFLICT`)" and PRD §3.3: "Creating a SKU requires a
        globally unique `name` (a duplicate is rejected with
        `ERR_PART_NAME_CONFLICT`)".

        Design: Corner/validations/uniqueness_constraints
        """
        donor = make_donor(display_name="D UQ", donor_type="INDIVIDUAL", email="duq@x.org")
        make_bike(donor["id"], serial_number="SN-UQ", bike_type="ROAD",
                  wheel_size_inches=27)
        make_part(name="Bell", category="MISC")
        r1 = api_client.create_bike(
            {"donor_id": donor["id"], "serial_number": "SN-UQ",
             "bike_type": "MTB", "wheel_size_inches": 26},
            COORD,
        )
        validate_error(r1, ApiErrorId.ERR_SERIAL_NUMBER_CONFLICT)
        r2 = api_client.create_part({"name": "Bell", "category": "COCKPIT"}, COORD)
        validate_error(r2, ApiErrorId.ERR_PART_NAME_CONFLICT)

    def test_usage_skill_gate_and_lead_ineligible(self):
        """PRD §3.2: "that volunteer must hold a `skill_level` of at least
        `APPRENTICE` — `APPRENTICE`, `JOURNEYMAN`, or `LEAD_MECHANIC` — with
        `engagement_status` `ACTIVE`; otherwise the routing fails with
        `ERR_LEAD_INELIGIBLE`." and PRD §3.3: "The logging volunteer must be
        `ACTIVE` (else `ERR_VOLUNTEER_SUSPENDED`) and hold at least `APPRENTICE`
        skill; a `TRAINEE`'s usage log is rejected with
        `ERR_USAGE_SKILL_INSUFFICIENT`."

        Design: Corner/validations/usage_skill_gate_and_lead_ineligible
        """
        donor = make_donor(display_name="D SK", donor_type="INDIVIDUAL", email="dsk@x.org")
        trainee = make_volunteer(full_name="V T", email="vt@x.org")
        apprentice = make_apprentice()
        bike = make_bike(donor["id"], serial_number="SN-SK", bike_type="ROAD",
                         wheel_size_inches=27)
        triage_bike(bike["id"], "B", False)
        r_lead = api_client.route_bike(
            bike["id"],
            {"destination": "REFURBISH", "refurb_lead_volunteer_id": trainee["id"]},
            COORD,
        )
        validate_error(r_lead, ApiErrorId.ERR_LEAD_INELIGIBLE)
        ok = validate_success(
            api_client.route_bike(
                bike["id"],
                {"destination": "REFURBISH",
                 "refurb_lead_volunteer_id": apprentice["id"]},
                COORD,
            )
        )
        assert ok["status"] == "IN_REFURBISHMENT"
        part = make_part(name="Nut", category="MISC", unit_cost_cents=50)
        part = restock_part(part["id"], 5)
        r_skill = api_client.create_usage_log(
            bike["id"],
            {"part_id": part["id"], "quantity": 1,
             "expected_part_version": part["version"]},
            make_volunteer_headers(trainee["id"]),
        )
        validate_error(r_skill, ApiErrorId.ERR_USAGE_SKILL_INSUFFICIENT)
        part_after = validate_success(api_client.get_part(part["id"], COORD))
        assert part_after["quantity_on_hand"] == 5
