"""ULD fleet registration, listing, return, damage, and repair lifecycle."""
from test_helpers import (
    ApiErrorId,
    assert_money,
    assert_uld_type,
    complete_uld_repair,
    create_build_up_plan,
    create_uld_payload,
    create_uld_type_payload,
    get_uld,
    list_uld_charges,
    make_open_flight,
    make_uld,
    make_uld_type,
    make_uld_type_and_unit,
    report_uld_damage,
    return_uld,
    set_clock,
    setup_departed_scenario,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestULDTypeRegistration:
    def test_uld_type_has_no_version_field(self, api, ramp_operator_headers):
        """PRD §2.4: "a ULDType and a TemperatureLog each carry only `id` and
        `created_at`; both `updated_at` and `version` are absent from them,
        since neither is ever modified after creation."

        Design: Corner/entities/uld_type_has_no_version_field
        """
        res = api.create_uld_type(
            create_uld_type_payload(
                type_code="PMC", tare_weight_kg=120,
                max_gross_weight_kg=2000, internal_volume_m3=10,
            ),
            ramp_operator_headers,
        )
        uld_type = validate_success(res, 201)
        assert_uld_type(uld_type)

    def test_duplicate_uld_code_rejected(self, api, ramp_operator_headers):
        """PRD §3.4: "Each physical unit is then registered with a serial
        `uld_code` (for example AKE12345CA), unique across all ULDs with
        duplicates likewise drawing `ERR_DUPLICATE_ULD_CODE`"

        Design: Corner/errors/duplicate_uld_code_rejected
        """
        uld_type = make_uld_type()
        validate_success(
            api.create_uld(
                create_uld_payload(uld_type["id"], uld_code="AKE00117CA"),
                ramp_operator_headers,
            ),
            201,
        )
        res = api.create_uld(
            create_uld_payload(uld_type["id"], uld_code="AKE00117CA"),
            ramp_operator_headers,
        )
        validate_error(res, ApiErrorId.ERR_DUPLICATE_ULD_CODE)
        _rows, meta = validate_paginated(api.list_ulds(ramp_operator_headers))
        assert meta["total_count"] == 1, "No duplicate unit may be persisted"


class TestULDListing:
    def test_uld_list_pagination_limit_offset(self, api, ramp_operator_headers):
        """PRD §2.3: "The `limit` parameter specifies the maximum number of
        items to return; it defaults to 10 when omitted, with a minimum of 1
        and a maximum of 100. The `offset` parameter specifies how many items
        to skip and defaults to 0."
        PRD §2.3: "Paginated list responses include `limit`, `offset`,
        `total_count`, and `has_more` in the `meta` object of the response
        envelope."

        Design: Corner/entities/uld_list_pagination_limit_offset
        """
        uld_type = make_uld_type()
        make_uld(uld_type["id"], uld_code="AKE00101CA")
        make_uld(uld_type["id"], uld_code="AKE00102CA")
        make_uld(uld_type["id"], uld_code="AKE00103CA")
        first_page, meta1 = validate_paginated(
            api.list_ulds(ramp_operator_headers, params={"limit": 2, "offset": 0})
        )
        assert len(first_page) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True
        second_page, meta2 = validate_paginated(
            api.list_ulds(ramp_operator_headers, params={"limit": 2, "offset": 2})
        )
        assert len(second_page) == 1
        assert meta2["has_more"] is False
        assert meta2["offset"] == 2


class TestULDReturnGate:
    def test_return_serviceable_uld_rejected(self, api, ramp_operator_headers):
        """PRD §3.8: "Returning requires the unit to be `DISPATCHED`
        (`ERR_ULD_INVALID_STATE` otherwise)"

        Design: Corner/errors/return_serviceable_uld_rejected
        """
        _uld_type, uld = make_uld_type_and_unit(uld_code="AKE00119CA")
        res = api.return_uld(uld["id"], ramp_operator_headers)
        validate_error(res, ApiErrorId.ERR_ULD_INVALID_STATE)
        charges = list_uld_charges(uld["id"])
        assert charges == [], "A failed return must not mint any charge"


class TestDamageRepairCycle:
    def _dispatched_then_returned_uld(self):
        scenario = setup_departed_scenario(
            flight_overrides={
                "flight_number": "CA207",
                "scheduled_departure": "2026-08-10T08:00:00Z",
                "scheduled_arrival": "2026-08-14T08:00:00Z",
            },
            booking_overrides={"shipper_ref": "SHP-U1"},
            uld_type_overrides={
                "type_code": "PMC", "tare_weight_kg": 120,
                "max_gross_weight_kg": 2000, "internal_volume_m3": 10,
            },
            uld_code="PMC00005CA",
            depart_clock="2026-08-10T08:00:00Z",
        )
        set_clock("2026-08-12T08:00:00Z")
        return_uld(scenario["uld"]["id"])
        return scenario

    def test_report_damage_creates_provisional_repair_charge(
        self, api, ramp_operator_headers
    ):
        """PRD §3.8: "the unit moves to `DAMAGE_REPORTED`, and a `ULDCharge` of
        `charge_type` `REPAIR` is created in `PROVISIONAL` status with `amount`
        set to the supplied estimate and the charge's `description` copied from
        the damage report."

        Design: Difficulty/non_linear_state_machine/uld_damage_repair_cycle
        """
        scenario = self._dispatched_then_returned_uld()
        damaged = report_uld_damage(
            scenario["uld"]["id"],
            damage_description="torn net and dented base",
            repair_cost_estimate=300,
        )
        assert damaged["status"] == "DAMAGE_REPORTED"
        repairs = list_uld_charges(
            scenario["uld"]["id"], params={"charge_type": "REPAIR"}
        )
        assert len(repairs) == 1
        assert repairs[0]["status"] == "PROVISIONAL"
        assert_money(repairs[0]["amount"], 300.00)
        assert repairs[0]["description"] == "torn net and dented base"

    def test_complete_repair_finalizes_charge_and_restores_serviceable(
        self, api, ramp_operator_headers
    ):
        """PRD §3.8: "Completing the repair requires the unit to be
        `DAMAGE_REPORTED` (`ERR_ULD_INVALID_STATE` otherwise); the operator
        supplies the `final_repair_cost`, the unit returns to `SERVICEABLE`,
        and the repair charge is finalized with `amount` set to that final
        cost, status moving to `FINALIZED`."
        PRD §3.4: "the flight must be `OPEN_FOR_BOOKING` and the unit
        `SERVICEABLE` — a unit already committed elsewhere draws
        `ERR_ULD_NOT_SERVICEABLE`"

        Design: Difficulty/non_linear_state_machine/uld_damage_repair_cycle
        """
        scenario = self._dispatched_then_returned_uld()
        report_uld_damage(
            scenario["uld"]["id"],
            damage_description="torn net and dented base",
            repair_cost_estimate=300,
        )
        repaired = complete_uld_repair(scenario["uld"]["id"], final_repair_cost=275.5)
        assert repaired["status"] == "SERVICEABLE", (
            "The damage loop closes back to SERVICEABLE"
        )
        repairs = list_uld_charges(
            scenario["uld"]["id"], params={"charge_type": "REPAIR"}
        )
        assert repairs[0]["status"] == "FINALIZED"
        assert_money(repairs[0]["amount"], 275.50)

        # The repaired unit re-enters SERVICEABLE -> ASSIGNED on a new flight.
        flight2 = make_open_flight(flight_number="CA208")
        plan2 = create_build_up_plan(
            flight2["id"], scenario["uld"]["id"],
            "2026-08-19T10:00:00Z", "2026-08-19T12:00:00Z",
        )
        assert plan2["status"] == "DRAFT"
        assert get_uld(scenario["uld"]["id"])["status"] == "ASSIGNED"
