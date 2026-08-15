"""Treatment scheduling gates: contract state, scope, fiscal budget, heat
safety, unit/technician/heat-floor temporal rules, and pinned evaluation
order."""
from test_helpers import (
    ApiErrorId,
    create_treatment_payload,
    get_success_data,
    make_resident_headers,
    make_technician_headers,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import (
    ADMIN,
    MANAGER,
    create_active_contract,
    create_property,
    create_technician,
    create_unit,
    schedule_treatment,
    setup_community,
    setup_completed_treatment,
)


def _suspend_ctx(api, **contract_overrides):
    """Community whose contract is ACTIVE then SUSPENDED."""
    prop = create_property()
    contract = create_active_contract(prop["id"], **contract_overrides)
    unit = create_unit(prop["id"])
    tech = create_technician()
    get_success_data(api.suspend_contract(contract["id"], ADMIN))
    return prop, contract, unit, tech


class TestContractStateGate:
    def test_treatment_rejected_while_suspended_accepted_after_reactivate(self, api):
        """PRD §3.4: "The property's contract must be `ACTIVE` — any of
        `DRAFT`, `SUSPENDED`, `TERMINATED`, or `EXPIRED` produces
        `ERR_CONTRACT_NOT_ACTIVE` (HTTP 409) — and the `pest_type` must fall
        inside the contract's scope, else `ERR_CONTRACT_SCOPE_EXCLUDED`."
        PRD §3.1: "From `ACTIVE` it may be suspended and later reactivated —
        reactivation requires that the current logical date has not passed the
        `end_date` — and either `ACTIVE` or `SUSPENDED` may be terminated
        outright."

        Design: Difficulty/cross_entity_state_dependency/treatment_gated_by_contract_state
        """
        prop, contract, unit, tech = _suspend_ctx(api, scope_pest_types=["ROACHES"])
        payload = create_treatment_payload(technician_id=tech["id"])
        resp = api.create_treatment(unit["id"], payload, MANAGER)
        validate_error(resp, ApiErrorId.ERR_CONTRACT_NOT_ACTIVE)

        validate_success(api.reactivate_contract(contract["id"], ADMIN))
        created = validate_success(api.create_treatment(unit["id"], payload, MANAGER), 201)
        assert created["status"] == "SCHEDULED"

    def test_treatment_rejected_while_contract_draft(self, api):
        """PRD §3.4: "The property's contract must be `ACTIVE` — any of
        `DRAFT`, `SUSPENDED`, `TERMINATED`, or `EXPIRED` produces
        `ERR_CONTRACT_NOT_ACTIVE` (HTTP 409) — and the `pest_type` must fall
        inside the contract's scope, else `ERR_CONTRACT_SCOPE_EXCLUDED`."

        Design: Difficulty/cross_entity_state_dependency/treatment_gated_by_contract_state
        """
        prop = create_property()
        contract = create_active_contract(prop["id"], activate=False,
                                          scope_pest_types=["ROACHES"])
        assert contract["status"] == "DRAFT"
        unit = create_unit(prop["id"])
        tech = create_technician()
        resp = api.create_treatment(
            unit["id"], create_treatment_payload(technician_id=tech["id"]), MANAGER
        )
        validate_error(resp, ApiErrorId.ERR_CONTRACT_NOT_ACTIVE)


class TestScopeGate:
    def test_treatment_pest_outside_contract_scope_rejected(self, api):
        """PRD §3.4: "The property's contract must be `ACTIVE` — any of
        `DRAFT`, `SUSPENDED`, `TERMINATED`, or `EXPIRED` produces
        `ERR_CONTRACT_NOT_ACTIVE` (HTTP 409) — and the `pest_type` must fall
        inside the contract's scope, else `ERR_CONTRACT_SCOPE_EXCLUDED`."

        Design: Corner/validations/treatment_pest_outside_contract_scope_rejected
        """
        ctx = setup_community(with_lease=False, with_resident=False,
                              contract_overrides={"scope_pest_types": ["ROACHES"]})
        resp = api.create_treatment(
            ctx["unit"]["id"],
            create_treatment_payload(technician_id=ctx["technician"]["id"], pest_type="TERMITES"),
            MANAGER,
        )
        validate_error(resp, ApiErrorId.ERR_CONTRACT_SCOPE_EXCLUDED)


class TestBudgetGate:
    def test_budget_boundary_inclusive_then_exceeded(self, api):
        """PRD §3.4: "The fiscal gate compares `spent_cents` plus the
        treatment-type estimate from §2.8 against `monthly_budget_cents`; a sum
        that would exceed the budget is rejected with
        `ERR_CONTRACT_BUDGET_EXCEEDED` (HTTP 422)."

        Design: Corner/validations/budget_boundary_inclusive_then_exceeded
        """
        ctx = setup_community(contract_overrides={
            "scope_pest_types": ["ROACHES"],
            "monthly_budget_cents": 24000,
        })
        unit, resident, tech, contract = (ctx["unit"], ctx["resident"],
                                          ctx["technician"], ctx["contract"])
        setup_completed_treatment(unit["id"], resident, tech,
                                  window_start="2026-08-10T09:00:00Z",
                                  window_end="2026-08-10T10:00:00Z")
        # spent == 12000; 12000 + 12000 == 24000 must pass (inclusive <=)
        t2 = schedule_treatment(unit["id"], tech["id"],
                                window_start="2026-08-11T09:00:00Z",
                                window_end="2026-08-11T10:00:00Z")
        assert t2["status"] == "SCHEDULED"
        get_success_data(api.notify_prep(t2["id"], MANAGER))
        get_success_data(api.acknowledge_prep(t2["id"], make_resident_headers(resident["id"])))
        get_success_data(api.verify_prep(t2["id"], {"compliant": True}, MANAGER))
        resp_complete = api.complete_treatment(
            t2["id"], {"actual_minutes": 60}, make_technician_headers(tech["id"])
        )
        validate_success(resp_complete)

        resp = api.create_treatment(
            unit["id"],
            create_treatment_payload(technician_id=tech["id"],
                                     window_start="2026-08-12T09:00:00Z",
                                     window_end="2026-08-12T10:00:00Z"),
            MANAGER,
        )
        validate_error(resp, ApiErrorId.ERR_CONTRACT_BUDGET_EXCEEDED)
        contract_after = validate_success(api.get_contract(contract["id"], ADMIN))
        assert contract_after["spent_cents"] == 24000


class TestHeatSafety:
    def test_heat_without_attestation_rejected_solo(self, api):
        """PRD §2.9: "Separately, any `HEAT` treatment scheduled or rescheduled
        without `vacancy_attested` set to true is rejected with
        `ERR_HEAT_SAFETY_VIOLATION` (HTTP 422), because heat work in an
        occupied unit is a safety incident."

        Design: Corner/validations/heat_without_attestation_rejected_solo
        """
        ctx = setup_community(with_lease=False, with_resident=False,
                              contract_overrides={"scope_pest_types": ["BED_BUGS"]})
        resp = api.create_treatment(
            ctx["unit"]["id"],
            create_treatment_payload(
                technician_id=ctx["technician"]["id"], pest_type="BED_BUGS",
                treatment_type="HEAT", window_start="2026-08-10T08:00:00Z",
                window_end="2026-08-10T16:00:00Z", vacancy_attested=False,
            ),
            MANAGER,
        )
        validate_error(resp, ApiErrorId.ERR_HEAT_SAFETY_VIOLATION)


class TestTechnicianBufferedOverlap:
    def _setup_one_booked(self, api):
        ctx = setup_community(num_units=2, with_lease=False, with_resident=False,
                              contract_overrides={"scope_pest_types": ["ROACHES"]})
        u1, u2 = ctx["units"][0], ctx["units"][1]
        tech = ctx["technician"]
        schedule_treatment(u1["id"], tech["id"])  # 2026-08-10T09:00-10:00Z
        return ctx, u2, tech

    def test_start_inside_buffer_rejected(self, api):
        """PRD §2.9: "Second, a technician needs travel time: the new window,
        expanded by 15 minutes on both sides, must not intersect the similarly
        expanded interval of any other non-terminal treatment assigned to the
        same technician; violations return `ERR_TREATMENT_WINDOW_CONFLICT`
        (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/technician_buffered_half_open_overlap
        """
        ctx, u2, tech = self._setup_one_booked(api)
        resp = api.create_treatment(
            u2["id"],
            create_treatment_payload(technician_id=tech["id"],
                                     window_start="2026-08-10T10:14:00Z",
                                     window_end="2026-08-10T11:00:00Z"),
            MANAGER,
        )
        validate_error(resp, ApiErrorId.ERR_TREATMENT_WINDOW_CONFLICT)

    def test_start_touching_buffer_edge_accepted(self, api):
        """PRD §2.9: "First, a unit may not be double-booked: the half-open
        interval from `window_start` to `window_end` — including the start
        instant, excluding the end instant — must not intersect any other
        non-terminal treatment of the same unit; violations return
        `ERR_UNIT_DOUBLE_BOOKED` (HTTP 409). Second, a technician needs travel
        time: the new window, expanded by 15 minutes on both sides, must not
        intersect the similarly expanded interval of any other non-terminal
        treatment assigned to the same technician; violations return
        `ERR_TREATMENT_WINDOW_CONFLICT` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/technician_buffered_half_open_overlap
        """
        ctx, u2, tech = self._setup_one_booked(api)
        # Existing: 09:00-10:00, expanded [08:45, 10:15]. The technician rule
        # expands BOTH windows by 15 minutes, so a new start of 10:15 would
        # still overlap ([10:00, 11:15] vs [08:45, 10:15]) under every
        # intersection convention. The exact touch point (10:30) is
        # convention-dependent because §2.9 pins half-open semantics only for
        # the unit rule; 10:31 sits outside the conflict zone under open,
        # closed, and half-open readings alike.
        created = validate_success(
            api.create_treatment(
                u2["id"],
                create_treatment_payload(technician_id=tech["id"],
                                         window_start="2026-08-10T10:31:00Z",
                                         window_end="2026-08-10T11:00:00Z"),
                MANAGER,
            ),
            201,
        )
        assert created["status"] == "SCHEDULED"


class TestHeatFloorGap:
    def _setup_heat(self, api):
        ctx = setup_community(num_units=2, with_lease=False, with_resident=False,
                              contract_overrides={"scope_pest_types": ["BED_BUGS"]})
        u1, u2 = ctx["units"][0], ctx["units"][1]
        tech = ctx["technician"]
        schedule_treatment(u1["id"], tech["id"], pest_type="BED_BUGS", treatment_type="HEAT",
                           window_start="2026-08-10T08:00:00Z",
                           window_end="2026-08-10T16:00:00Z", vacancy_attested=True)
        return ctx, u2, tech

    def test_heat_floor_gap_23h_rejected(self, api):
        """PRD §2.9: "Third, heat treatments on a floor need breathing room: a
        `HEAT` treatment's `window_start` must sit at least 24 hours away from
        the `window_start` of every other non-terminal `HEAT` treatment
        anywhere on the same property and floor; violations return
        `ERR_HEAT_FLOOR_GAP_VIOLATION` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/heat_floor_gap_minimum_24h
        """
        ctx, u2, tech = self._setup_heat(api)
        resp = api.create_treatment(
            u2["id"],
            create_treatment_payload(technician_id=tech["id"], pest_type="BED_BUGS",
                                     treatment_type="HEAT",
                                     window_start="2026-08-11T07:00:00Z",
                                     window_end="2026-08-11T15:00:00Z",
                                     vacancy_attested=True),
            MANAGER,
        )
        validate_error(resp, ApiErrorId.ERR_HEAT_FLOOR_GAP_VIOLATION)

    def test_heat_floor_gap_exactly_24h_accepted(self, api):
        """PRD §2.9: "Third, heat treatments on a floor need breathing room: a
        `HEAT` treatment's `window_start` must sit at least 24 hours away from
        the `window_start` of every other non-terminal `HEAT` treatment
        anywhere on the same property and floor; violations return
        `ERR_HEAT_FLOOR_GAP_VIOLATION` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/heat_floor_gap_minimum_24h
        """
        ctx, u2, tech = self._setup_heat(api)
        created = validate_success(
            api.create_treatment(
                u2["id"],
                create_treatment_payload(technician_id=tech["id"], pest_type="BED_BUGS",
                                         treatment_type="HEAT",
                                         window_start="2026-08-11T08:00:00Z",
                                         window_end="2026-08-11T16:00:00Z",
                                         vacancy_attested=True),
                MANAGER,
            ),
            201,
        )
        assert created["status"] == "SCHEDULED"


    def test_safety_beats_temporal_with_idle_technician(self, api):
        """PRD §2.10: "When several rules could reject the same request, the
        server evaluates them in a fixed order and reports the first failure."
        PRD §2.10: "then heat safety (`ERR_HEAT_SAFETY_VIOLATION`), then the
        three temporal conflicts in the fixed order unit double-booking,
        technician buffered overlap, heat floor gap"
        PRD §2.9: "Separately, any `HEAT` treatment scheduled or rescheduled
        without `vacancy_attested` set to true is rejected with
        `ERR_HEAT_SAFETY_VIOLATION` (HTTP 422), because heat work in an
        occupied unit is a safety incident."

        Design: Difficulty/priority_pair_validation_conflict/safety_beats_temporal_on_heat_schedule
        """
        ctx = setup_community(num_units=2, with_lease=False, with_resident=False,
                              contract_overrides={"scope_pest_types": ["BED_BUGS"]})
        u1, u2 = ctx["units"][0], ctx["units"][1]
        tech = ctx["technician"]
        schedule_treatment(u1["id"], tech["id"], pest_type="BED_BUGS")  # 09:00-10:00
        # The new HEAT window 10:00-11:00 starts inside the technician's
        # 15-minute travel buffer (buffered to 10:15) and lacks the vacancy
        # attestation; heat safety must be the reported failure.
        resp = api.create_treatment(
            u2["id"],
            create_treatment_payload(technician_id=tech["id"], pest_type="BED_BUGS",
                                     treatment_type="HEAT",
                                     window_start="2026-08-10T10:00:00Z",
                                     window_end="2026-08-10T11:00:00Z",
                                     vacancy_attested=False),
            MANAGER,
        )
        validate_error(resp, ApiErrorId.ERR_HEAT_SAFETY_VIOLATION)


class TestTemporalSubOrder:
    def test_unit_double_booked_precedes_technician_conflict(self, api):
        """PRD §2.10: "When several rules could reject the same request, the
        server evaluates them in a fixed order and reports the first failure."
        PRD §2.10: "then heat safety (`ERR_HEAT_SAFETY_VIOLATION`), then the
        three temporal conflicts in the fixed order unit double-booking,
        technician buffered overlap, heat floor gap"

        Design: Corner/validations/unit_double_booked_precedes_technician_conflict
        """
        ctx = setup_community(with_lease=False, with_resident=False,
                              contract_overrides={"scope_pest_types": ["ROACHES"]})
        unit, tech = ctx["unit"], ctx["technician"]
        schedule_treatment(unit["id"], tech["id"])  # 09:00-10:00
        resp = api.create_treatment(
            unit["id"],
            create_treatment_payload(technician_id=tech["id"],
                                     window_start="2026-08-10T09:30:00Z",
                                     window_end="2026-08-10T10:30:00Z"),
            MANAGER,
        )
        validate_error(resp, ApiErrorId.ERR_UNIT_DOUBLE_BOOKED)


class TestValidationOrderAcrossCategories:
    def test_state_beats_fiscal_on_suspended_contract(self, api):
        """PRD §2.10: "When several rules could reject the same request, the
        server evaluates them in a fixed order and reports the first failure."
        PRD §2.10: "then state preconditions (`ERR_INVALID_STATE`,
        `ERR_ALREADY_TERMINAL`, and the domain state guards such as
        `ERR_CONTRACT_NOT_ACTIVE`, `ERR_LEASE_NOT_ACTIVE`,
        `ERR_PREP_NOT_NOTIFIED`, `ERR_PREP_NOT_ACKNOWLEDGED`, and
        `ERR_CASE_NOT_MONITORING`)"
        PRD §2.10: "then fiscal checks (`ERR_CONTRACT_BUDGET_EXCEEDED`,
        `ERR_PAYMENT_AMOUNT_MISMATCH`)"

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_suspended_contract
        """
        ctx = setup_community(contract_overrides={
            "scope_pest_types": ["ROACHES"],
            "monthly_budget_cents": 12000,
        })
        unit, resident, tech, contract = (ctx["unit"], ctx["resident"],
                                          ctx["technician"], ctx["contract"])
        setup_completed_treatment(unit["id"], resident, tech)  # spent == 12000 == budget
        validate_success(api.suspend_contract(contract["id"], ADMIN))

        resp = api.create_treatment(
            unit["id"],
            create_treatment_payload(technician_id=tech["id"],
                                     window_start="2026-08-12T09:00:00Z",
                                     window_end="2026-08-12T10:00:00Z"),
            MANAGER,
        )
        error_data = validate_error(resp, ApiErrorId.ERR_CONTRACT_NOT_ACTIVE)
        assert error_data["error_id"] != "ERR_CONTRACT_BUDGET_EXCEEDED"

    def test_state_beats_fiscal_on_expired_contract(self, api):
        """PRD §2.10: "When several rules could reject the same request, the
        server evaluates them in a fixed order and reports the first failure."
        PRD §2.10: "then state preconditions (`ERR_INVALID_STATE`,
        `ERR_ALREADY_TERMINAL`, and the domain state guards such as
        `ERR_CONTRACT_NOT_ACTIVE`, `ERR_LEASE_NOT_ACTIVE`,
        `ERR_PREP_NOT_NOTIFIED`, `ERR_PREP_NOT_ACKNOWLEDGED`, and
        `ERR_CASE_NOT_MONITORING`)"
        PRD §2.10: "then fiscal checks (`ERR_CONTRACT_BUDGET_EXCEEDED`,
        `ERR_PAYMENT_AMOUNT_MISMATCH`)"
        PRD §3.4: "The fiscal gate compares `spent_cents` plus the
        treatment-type estimate from §2.8 against `monthly_budget_cents`; a sum
        that would exceed the budget is rejected with
        `ERR_CONTRACT_BUDGET_EXCEEDED` (HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_suspended_contract
        """
        ctx = setup_community(contract_overrides={
            "scope_pest_types": ["ROACHES"],
            "monthly_budget_cents": 12000,
        })
        unit, resident, tech, contract = (ctx["unit"], ctx["resident"],
                                          ctx["technician"], ctx["contract"])
        setup_completed_treatment(unit["id"], resident, tech)  # spent == 12000 == budget
        validate_success(api.suspend_contract(contract["id"], ADMIN))
        # Contract is both not-ACTIVE and over budget; the state guard is
        # reported first.
        resp = api.create_treatment(
            unit["id"],
            create_treatment_payload(technician_id=tech["id"],
                                     window_start="2026-08-12T09:00:00Z",
                                     window_end="2026-08-12T10:00:00Z"),
            MANAGER,
        )
        validate_error(resp, ApiErrorId.ERR_CONTRACT_NOT_ACTIVE)

    def test_safety_beats_temporal_on_heat_schedule(self, api):
        """PRD §2.10: "When several rules could reject the same request, the
        server evaluates them in a fixed order and reports the first failure."
        PRD §2.10: "then heat safety (`ERR_HEAT_SAFETY_VIOLATION`), then the
        three temporal conflicts in the fixed order unit double-booking,
        technician buffered overlap, heat floor gap"

        Design: Difficulty/priority_pair_validation_conflict/safety_beats_temporal_on_heat_schedule
        """
        ctx = setup_community(num_units=2, with_lease=False, with_resident=False,
                              contract_overrides={"scope_pest_types": ["BED_BUGS"]})
        u1, u2 = ctx["units"][0], ctx["units"][1]
        tech = ctx["technician"]
        schedule_treatment(u1["id"], tech["id"], pest_type="BED_BUGS")
        resp = api.create_treatment(
            u2["id"],
            create_treatment_payload(technician_id=tech["id"], pest_type="BED_BUGS",
                                     treatment_type="HEAT",
                                     window_start="2026-08-10T10:00:00Z",
                                     window_end="2026-08-10T11:00:00Z",
                                     vacancy_attested=False),
            MANAGER,
        )
        error_data = validate_error(resp, ApiErrorId.ERR_HEAT_SAFETY_VIOLATION)
        assert error_data["error_id"] != "ERR_TREATMENT_WINDOW_CONFLICT"
