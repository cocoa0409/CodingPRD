"""Facility safety posture: incident-count thresholds, the SUSPENDED cascade
into active transfers, the resume cascade, and posture-versus-credit
priority."""
from test_helpers import (
    ApiErrorId,
    get_success_data,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import (
    ADMIN,
    OPERATOR,
    SAFETY,
    YARD,
    create_customer,
    create_equipment,
    create_facility,
    create_incident,
    create_lot,
    create_product,
    create_transfer_for,
    get_equipment,
    get_railcar,
    get_transfer_order,
    setup_active_transfer,
    setup_spotted_car,
)


class TestPostureThresholds:
    def test_posture_threshold_aggregation(self, api):
        """PRD §2.6: "Its value is `SUSPENDED` when any open incident has
        `severity` `CRITICAL` or when the count of open incidents is at least
        3; otherwise `ELEVATED` when at least one incident is open; otherwise
        `NORMAL`. So exactly one open `CRITICAL` incident suspends the
        facility, exactly three open `MINOR`/`MAJOR` incidents suspend it, and
        two open incidents elevate it. `open_incident_count` mirrors the count
        of incidents with status `OPEN`."

        Design: Corner/calculations/posture_threshold_aggregation
        """
        fac = create_facility(name="FT-C3")

        def posture():
            f = validate_success(api.get_facility(fac["id"], SAFETY))
            return f["safety_posture"], f["open_incident_count"]

        i1 = create_incident(severity="MINOR", description="a")
        assert posture() == ("ELEVATED", 1)

        i2 = create_incident(severity="MAJOR", description="b")
        assert posture() == ("ELEVATED", 2)

        i3 = create_incident(severity="MINOR", description="c")
        assert posture() == ("SUSPENDED", 3), "count >= 3 suspends"

        get_success_data(api.resolve_incident(i1["id"], SAFETY))
        assert posture() == ("ELEVATED", 2)

        get_success_data(api.resolve_incident(i2["id"], SAFETY))
        get_success_data(api.resolve_incident(i3["id"], SAFETY))
        assert posture() == ("NORMAL", 0)


class TestIncidentCascade:
    def test_incident_suspends_active_transfer_cascade(self, api):
        """PRD §2.6: "Entering `SUSPENDED` cascades: every `ACTIVE` transfer
        order moves to `SUSPENDED`, each releasing its equipment (`IN_USE`
        back to `AVAILABLE`, bumping the equipment's `version`) and pausing
        its railcar (`IN_TRANSFER` back to `SPOTTED`, bumping the car's
        `version`)."
        PRD §2.6: "Its value is `SUSPENDED` when any open incident has
        `severity` `CRITICAL` or when the count of open incidents is at least
        3"

        Design: Difficulty/transitive_cascade/incident_suspend_cascade_depth3
        """
        ctx = setup_active_transfer(quantity_planned_tons=20.0,
                                    quantity_loaded_tons=40.0,
                                    car_number="70001")

        create_incident(severity="CRITICAL", description="Derail on lead")

        fac = validate_success(api.get_facility(ctx["facility"]["id"], SAFETY))
        assert fac["safety_posture"] == "SUSPENDED"
        assert fac["open_incident_count"] == 1

        assert get_transfer_order(ctx["transfer"]["id"])["status"] == "SUSPENDED"
        assert get_equipment(ctx["equipment"]["id"])["status"] == "AVAILABLE"
        assert get_railcar(ctx["car"]["id"])["placement_status"] == "SPOTTED"

    def test_resolve_resumes_suspended_transfer_cascade(self, api):
        """PRD §2.6: "When the posture later leaves `SUSPENDED` — returns to
        `NORMAL` or `ELEVATED` — every `SUSPENDED` transfer order automatically
        moves back to `ACTIVE`, each re-acquiring its equipment (which flips
        back to `IN_USE` and re-stamps its `last_product_id` from the car's
        lading product) and resuming its railcar (`SPOTTED` back to
        `IN_TRANSFER`, again bumping versions)."

        Design: Difficulty/transitive_cascade/incident_suspend_cascade_depth3
        """
        ctx = setup_active_transfer(quantity_planned_tons=20.0,
                                    quantity_loaded_tons=40.0,
                                    car_number="70001")
        inc = create_incident(severity="CRITICAL", description="Derail on lead")

        get_success_data(api.resolve_incident(inc["id"], SAFETY))

        fac = validate_success(api.get_facility(ctx["facility"]["id"], SAFETY))
        assert fac["safety_posture"] == "NORMAL"
        assert fac["open_incident_count"] == 0

        assert get_transfer_order(ctx["transfer"]["id"])["status"] == "ACTIVE"
        eq = get_equipment(ctx["equipment"]["id"])
        assert eq["status"] == "IN_USE"
        assert eq["last_product_id"] == ctx["product"]["id"]
        assert get_railcar(ctx["car"]["id"])["placement_status"] == "IN_TRANSFER"


class TestSafetyBeatsCredit:
    def _suspended_and_credit_hold_setup(self, api):
        """SPOTTED car + PLANNED transfer, posture SUSPENDED (CRITICAL
        incident) and customer on CREDIT_HOLD at the same time."""
        ctx = setup_spotted_car(quantity_loaded_tons=40.0, car_number="80002")
        eq = create_equipment(name="PUMP-1", equipment_type="PUMP")
        to = create_transfer_for(ctx["car"]["id"], eq["id"], 10.0)
        create_incident(severity="CRITICAL", description="Derail")
        get_success_data(
            api.patch_customer(ctx["customer"]["id"],
                               {"credit_standing": "CREDIT_HOLD"}, ADMIN)
        )
        ctx["equipment"] = eq
        ctx["transfer"] = to
        return ctx

    def test_activate_suspended_reports_facility_suspended_not_credit(self, api):
        """PRD §2.9: "Every endpoint evaluates its checks in a fixed priority
        order, and when several checks fail the earliest one wins:" with
        "7. Facility posture and derail gates (`ERR_FACILITY_SUSPENDED`,
        `ERR_POSTURE_ELEVATED_HAZMAT`, `ERR_DERAIL_ENGAGED`)." listed ahead of
        "12. Credit hold on spot scheduling and transfer activation
        (`ERR_CREDIT_HOLD`)."

        Design: Difficulty/priority_pair_validation_conflict/safety_beats_credit_on_activate
        """
        ctx = self._suspended_and_credit_hold_setup(api)
        validate_error(api.activate_transfer_order(ctx["transfer"]["id"], OPERATOR),
                       ApiErrorId.ERR_FACILITY_SUSPENDED)

    def test_activate_suspended_leaves_order_planned(self, api):
        """PRD §2.6: "The posture gates operations facility-wide: while
        `SUSPENDED`, spot-order scheduling and execution, transfer activation,
        and railcar release are all blocked with `ERR_FACILITY_SUSPENDED`."
        PRD §3.5: "On successful activation the equipment moves from
        `AVAILABLE` to `IN_USE`" — a rejected activation performs none of it.

        Design: Difficulty/priority_pair_validation_conflict/safety_beats_credit_on_activate
        """
        ctx = self._suspended_and_credit_hold_setup(api)
        validate_error(api.activate_transfer_order(ctx["transfer"]["id"], OPERATOR),
                       ApiErrorId.ERR_FACILITY_SUSPENDED)
        assert get_transfer_order(ctx["transfer"]["id"])["status"] == "PLANNED"
        assert get_equipment(ctx["equipment"]["id"])["status"] == "AVAILABLE"
