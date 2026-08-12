"""Instrument assignment gates and the repair-or-replace economic cycle:
send-time tray demotion, the adjusted-ratio recommendation ladder, override
justification, and the repair round-trip's conserved quantities.
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    make_technician_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import factories as f
from test_helpers import fixtures as fx

ADMIN = TEST_USERS["facility_admin_headers"]


def test_instrument_assignment_constraint_gates(api):
    """PRD §3.3: "The instrument must be `IN_SERVICE` (else
    `ERR_INSTRUMENT_NOT_IN_SERVICE`), currently unassigned —
    `assigned_tray_id` null — (else `ERR_INSTRUMENT_ALREADY_ASSIGNED`), and
    below its lifecycle limit: assignment is blocked when `usage_cycles` has
    reached `max_cycles`, equality included (else `ERR_INSTRUMENT_CYCLE_LIMIT`)."

    Design: Corner/state_machines/instrument_assignment_constraint_gates
    """
    tpl = fx.create_template(
        api,
        instrument_requirements=[{"instrument_type": "SCALPEL", "quantity": 9}],
    )
    tech = fx.create_technician(api)
    tm = fx.create_tray(api, tpl["id"], tech["id"], label="TM")
    fx.decontaminate(api, tm["id"], tech["id"])
    h = make_technician_headers(tech["id"])
    validate_success(api.start_assembly(tm["id"], h))

    ia = fx.create_instrument(api, serial_number="SN-A1", max_cycles=50, usage_cycles=0)
    ib = fx.create_instrument(api, serial_number="SN-A2", max_cycles=5, usage_cycles=5)
    ic = fx.create_instrument(api, serial_number="SN-A3", max_cycles=50)
    validate_success(api.flag_instrument_for_repair(ic["id"], h), 201)

    a1 = validate_success(api.assign_instrument(ia["id"], {"tray_id": tm["id"]}, h))
    assert a1["assigned_tray_id"] == tm["id"]

    e1 = api.assign_instrument(ia["id"], {"tray_id": tm["id"]}, h)
    validate_error(e1, ApiErrorId.ERR_INSTRUMENT_ALREADY_ASSIGNED)

    e2 = api.assign_instrument(ib["id"], {"tray_id": tm["id"]}, h)
    validate_error(e2, ApiErrorId.ERR_INSTRUMENT_CYCLE_LIMIT)

    e3 = api.assign_instrument(ic["id"], {"tray_id": tm["id"]}, h)
    validate_error(e3, ApiErrorId.ERR_INSTRUMENT_NOT_IN_SERVICE)

    e4 = api.flag_instrument_for_repair(ic["id"], h)
    validate_error(e4, ApiErrorId.ERR_INSTRUMENT_NOT_IN_SERVICE)


def test_repair_order_state_gates_and_retire_rejection(api):
    """PRD §3.3: "it must be `SENT` (else `ERR_REPAIR_ORDER_NOT_SENT`)"; "the
    order, which must be `OPEN` (else `ERR_REPAIR_ORDER_NOT_OPEN`)"; "A
    `FacilityAdmin` may also retire an instrument outright from `IN_SERVICE`
    or `FLAGGED_FOR_REPAIR` (any other status draws
    `ERR_INSTRUMENT_NOT_RETIRABLE`)."

    Design: Corner/state_machines/repair_order_state_gates_and_retire_rejection
    """
    tech = fx.create_technician(api)
    ir = fx.create_instrument(api, serial_number="SN-R9", max_cycles=50)
    ro = validate_success(
        api.flag_instrument_for_repair(ir["id"], make_technician_headers(tech["id"])),
        201,
    )

    e1 = api.receive_repair_order(
        ro["id"], f.receive_repair_order_payload(actual_cost_cents=1000, outcome="FIXED"),
        ADMIN,
    )
    validate_error(e1, ApiErrorId.ERR_REPAIR_ORDER_NOT_SENT)

    validate_success(
        api.send_repair_order(ro["id"], f.send_repair_order_payload(), ADMIN)
    )
    e2 = api.send_repair_order(ro["id"], f.send_repair_order_payload(), ADMIN)
    validate_error(e2, ApiErrorId.ERR_REPAIR_ORDER_NOT_OPEN)

    e3 = api.retire_instrument(ir["id"], ADMIN)
    validate_error(e3, ApiErrorId.ERR_INSTRUMENT_NOT_RETIRABLE)


def test_repair_override_requires_justification_then_succeeds(api):
    """PRD §3.3: "If the applied `outcome` differs from the computed
    `recommended_outcome`, the receive is accepted only with an
    `override_justification` of at least 20 characters (else
    `ERR_OUTCOME_OVERRIDE_JUSTIFICATION_REQUIRED`, 400), and the order records
    `outcome_overridden` as true."

    Design: Corner/validations/repair_override_requires_justification_then_succeeds
    """
    s = fx.setup_repair_ratio_scenario(api)
    # RO2's recommendation is CONDEMNED (adjusted ratio 0.625 >= 0.6).
    e1 = api.receive_repair_order(
        s.ro2["id"],
        f.receive_repair_order_payload(actual_cost_cents=50000, outcome="FIXED"),
        ADMIN,
    )
    validate_error(e1, ApiErrorId.ERR_OUTCOME_OVERRIDE_JUSTIFICATION_REQUIRED)

    ok = validate_success(
        api.receive_repair_order(
            s.ro2["id"],
            f.receive_repair_order_payload(
                actual_cost_cents=50000, outcome="FIXED",
                override_justification="Surgeon-critical set; replacement backordered",
            ),
            ADMIN,
        ),
    )
    assert ok["status"] == "CLOSED_FIXED", (
        "the rejected attempt did not close the order, so the retry is legal"
    )
    assert ok["outcome_overridden"] is True


class TestRepairReplaceAdjustedRatioBranching:
    """Identical cost inputs diverge solely through the repair_count branch
    (two tests, one design instance)."""

    def test_first_repair_recommends_fixed(self, api):
        """PRD §3.3: "Otherwise compute the base ratio of `actual_cost_cents`
        to `replacement_cost_cents`, adjust it upward by 25 percent for each
        prior completed repair (that is, multiply by one plus 0.25 times
        `repair_count`) ... An adjusted ratio of 0.6 or higher recommends
        `CONDEMNED`; below 0.6 recommends `FIXED`."

        Design: Difficulty/combinatorial_formula/repair_replace_adjusted_ratio_branching
        """
        s = fx.setup_repair_ratio_scenario(api)
        # Drive RO2 to its recommendation so the instrument cycle completes.
        validate_success(api.receive_repair_order(
            s.ro2["id"],
            f.receive_repair_order_payload(actual_cost_cents=50000, outcome="CONDEMNED"),
            ADMIN,
        ))
        ro1 = validate_success(api.get_repair_order(s.ro1["id"], ADMIN))
        assert ro1["recommended_outcome"] == "FIXED", (
            "ratio 50000/100000 = 0.5, repair_count 0 -> adjusted 0.5 < 0.6"
        )
        assert ro1["outcome_overridden"] is False
        assert ro1["status"] == "CLOSED_FIXED"

    def test_second_repair_same_costs_recommends_condemned(self, api):
        """PRD §3.3: "An adjusted ratio of 0.6 or higher recommends
        `CONDEMNED`; below 0.6 recommends `FIXED`. A ratio landing exactly on
        0.6 condemns, and no rounding is applied before the comparison."
        "Receiving with `CONDEMNED` closes the order `SENT → CLOSED_CONDEMNED`
        and moves the instrument `OUT_FOR_REPAIR → RETIRED`."

        Design: Difficulty/combinatorial_formula/repair_replace_adjusted_ratio_branching
        """
        s = fx.setup_repair_ratio_scenario(api)
        received = validate_success(api.receive_repair_order(
            s.ro2["id"],
            f.receive_repair_order_payload(actual_cost_cents=50000, outcome="CONDEMNED"),
            ADMIN,
        ))
        assert received["recommended_outcome"] == "CONDEMNED", (
            "same costs, repair_count 1 -> 0.5 x 1.25 = 0.625 >= 0.6"
        )
        assert received["outcome_overridden"] is False
        instrument = validate_success(api.get_instrument(s.i1["id"], ADMIN))
        assert instrument["status"] == "RETIRED"


class TestRepairSendUnassignDemotesTray:
    """The OPEN -> SENT cascade into the owning tray (two tests, one design
    instance)."""

    def test_send_moves_order_and_unassigns_instrument(self, api):
        """PRD §3.3: "Sending moves the order `OPEN → SENT` and the instrument
        `FLAGGED_FOR_REPAIR → OUT_FOR_REPAIR` ... The instrument's
        `assigned_tray_id` then clears to null."

        Design: Difficulty/transitive_cascade/repair_send_unassign_demotes_tray
        """
        s = fx.setup_repair_send_scenario(api)
        sent = validate_success(
            api.send_repair_order(s.ro1["id"], f.send_repair_order_payload(), ADMIN)
        )
        assert sent["status"] == "SENT"
        i1 = validate_success(api.get_instrument(s.i1["id"], ADMIN))
        assert i1["status"] == "OUT_FOR_REPAIR"
        assert i1["assigned_tray_id"] is None

    def test_send_demotes_tray_and_leaves_siblings(self, api):
        """PRD §3.3: "triggers the tray demotion cascade: if the instrument
        still had an `assigned_tray_id`, the owning tray — when it sits in
        `IN_ASSEMBLY`, `ASSEMBLED`, or `IN_LOAD` — demotes to `IN_ASSEMBLY`".

        Design: Difficulty/transitive_cascade/repair_send_unassign_demotes_tray
        """
        s = fx.setup_repair_send_scenario(api)
        validate_success(
            api.send_repair_order(s.ro1["id"], f.send_repair_order_payload(), ADMIN)
        )
        tm = validate_success(api.get_tray(s.tm["id"], ADMIN))
        assert tm["status"] == "IN_ASSEMBLY", (
            "the ASSEMBLED tray demotes so the count sheet must be re-verified"
        )
        i2 = validate_success(api.get_instrument(s.i2["id"], ADMIN))
        assert i2["status"] == "IN_SERVICE"
        assert i2["assigned_tray_id"] == s.tm["id"]


class TestRepairCycleConservesInstrumentAssignment:
    """Flag -> send -> receive FIXED -> reassign -> re-verify restores the
    tray's assigned multiset (two tests, one design instance)."""

    def _run_cycle(self, api, s):
        h = make_technician_headers(s.tech_a["id"])
        ro = validate_success(api.flag_instrument_for_repair(s.i1["id"], h), 201)
        validate_success(
            api.send_repair_order(
                ro["id"], f.send_repair_order_payload(quoted_cost_cents=10000), ADMIN)
        )
        validate_success(api.receive_repair_order(
            ro["id"],
            f.receive_repair_order_payload(actual_cost_cents=10000, outcome="FIXED"),
            ADMIN,
        ))
        validate_success(api.assign_instrument(s.i1["id"], {"tray_id": s.tm["id"]}, h))
        return validate_success(api.submit_assembly_verification(
            s.tm["id"], f.assembly_verification_payload(), h
        ), 201)

    def test_inventory_and_assignment_multiset_restored(self, api):
        """PRD §3.3: "Receiving with `FIXED` closes the order `SENT →
        CLOSED_FIXED` and returns the instrument `OUT_FOR_REPAIR → IN_SERVICE`
        with `repair_count` incremented by 1."

        Design: Difficulty/compensating_invariant/repair_cycle_conserves_instrument_assignment
        """
        s = fx.setup_repair_cycle_scenario(api)
        _, before = validate_paginated(
            api.list_instruments(ADMIN, params={"assigned_tray_id": s.tm["id"]})
        )
        assert before["total_count"] == 2

        self._run_cycle(api, s)

        _, all_meta = validate_paginated(api.list_instruments(ADMIN))
        assert all_meta["total_count"] == 2, "repair never creates inventory"
        _, assigned = validate_paginated(
            api.list_instruments(ADMIN, params={"assigned_tray_id": s.tm["id"]})
        )
        assert assigned["total_count"] == 2, "the assigned multiset is restored"

    def test_repair_count_is_the_only_drift(self, api):
        """PRD §3.3: "returns the instrument `OUT_FOR_REPAIR → IN_SERVICE`
        with `repair_count` incremented by 1." PRD §3.2: "A `PASS`
        verification persists the record (with `mismatch_count` 0) and
        advances the tray to `ASSEMBLED`."

        Design: Difficulty/compensating_invariant/repair_cycle_conserves_instrument_assignment
        """
        s = fx.setup_repair_cycle_scenario(api)
        v2 = self._run_cycle(api, s)
        assert v2["result"] == "PASS"
        i1 = validate_success(api.get_instrument(s.i1["id"], ADMIN))
        assert i1["status"] == "IN_SERVICE"
        assert i1["repair_count"] == 1, "the only permitted drift"
        tm = validate_success(api.get_tray(s.tm["id"], ADMIN))
        assert tm["status"] == "ASSEMBLED", "the demotion is healed by re-verification"
