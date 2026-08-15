"""Emissions inspections and campaigns: FAIL cascade, retest gate, cert-expiry
grounding, scope freezing, progress accounting, and auto-completion."""
from test_helpers import (
    ApiErrorId,
    activate_campaign,
    add_labor,
    assert_campaign,
    assert_emissions_inspection,
    bus_version,
    campaign_event,
    create_campaign_payload,
    create_inspection_payload,
    create_work_order_payload,
    get_success_data,
    grant_cert,
    make_mechanic_headers,
    new_bus,
    new_campaign,
    new_mechanic,
    new_part,
    new_qa_mechanic,
    new_work_order,
    record_inspection,
    run_epoch,
    schedule_wo,
    start_wo,
    validate_error,
    validate_success,
    wo_event,
)
from test_helpers import fixtures as fx


class TestEmissionsFailCascade:
    """Depth chain: FAIL -> bus HELD -> auto WO -> part reserve -> backorder
    -> campaign suspend."""

    def _setup(self):
        buses = fx.new_buses(
            5, model_year=2021, fleet_prefix="E",
            base_warranty_expiry_miles=200_000,
            base_warranty_expiry_date="2028-01-01",
        )
        part = new_part(sku="P-EM", description="DPF sensor",
                        unit_cost_cents=5_000, initial_on_hand=1)
        campaign = new_campaign(code="CMP-EM-1", title="DPF sensor recall",
                                required_part_id=part["id"])
        campaign = activate_campaign(campaign["id"])
        assert len(campaign["scope_bus_ids"]) == 5
        return buses, part, campaign

    def test_fail_holds_bus_and_spawns_scheduled_emergency_wo(self, api):
        """PRD §3.9: "A `FAIL` result triggers a compliance cascade. The bus is
        placed in `HELD` with `EMISSIONS` added to `hold_reasons`. The system
        automatically creates an `EMISSIONS` work order for the bus in
        `SCHEDULED` status at `EMERGENCY` priority, with a planned window
        running from the clock date to seven days after, an estimated 8 labor
        hours and 0 estimated cost cents, and `emissions_inspection_id` set to
        the inspection that spawned it; if `failed_component_part_id` was
        supplied, a part line reserving that part is created on the work
        order."
        PRD §3.6: "The derived `stock_status` classifies the part: `NORMAL`
        when the available quantity is strictly greater than `reorder_point`;
        `LOW_STOCK` when it is between zero and `reorder_point` inclusive; and
        `BACKORDERED` when it is negative."

        Design: Difficulty/transitive_cascade/emissions_fail_cascade_reaches_campaign_suspend
        """
        buses, part, _ = self._setup()
        inspection = record_inspection(buses[0]["id"], result="FAIL",
                                       failed_component_part_id=part["id"])
        assert_emissions_inspection(inspection)

        bus = get_success_data(api.get_bus(buses[0]["id"], fx.FM))
        assert bus["availability_status"] == "HELD"
        assert "EMISSIONS" in bus["hold_reasons"]

        auto_wo = fx.get_inspection_auto_wo(inspection["id"])
        assert auto_wo["wo_type"] == "EMISSIONS"
        assert auto_wo["status"] == "SCHEDULED"
        assert auto_wo["priority"] == "EMERGENCY"
        assert auto_wo["emissions_inspection_id"] == inspection["id"]
        assert auto_wo["planned_start_date"] == "2026-08-01"
        assert auto_wo["planned_end_date"] == "2026-08-08", "clock date + 7 days"
        assert auto_wo["estimated_labor_hours"] == 8
        assert auto_wo["estimated_cost_cents"] == 0

        part_after = get_success_data(api.get_part(part["id"], fx.PC))
        assert part_after["quantity_reserved"] == 1, (
            "the auto work order reserves the failed component"
        )
        assert part_after["stock_status"] == "LOW_STOCK", (
            "available 0 <= reorder_point 0"
        )

    def test_backorder_of_required_part_auto_suspends_campaign(self, api):
        """PRD §3.6: "the on-hand quantity may not drop below zero, but a
        write-down may push the available quantity below the reserved quantity,
        transitioning `stock_status` to `BACKORDERED` and triggering the
        campaign-suspension cascade described in §3.9."
        PRD §3.9: "A campaign may also be suspended explicitly by a
        `FleetManager`, or automatically whenever its required part's
        `stock_status` becomes `BACKORDERED`."

        Design: Difficulty/transitive_cascade/emissions_fail_cascade_reaches_campaign_suspend
        """
        buses, part, campaign = self._setup()
        record_inspection(buses[0]["id"], result="FAIL",
                          failed_component_part_id=part["id"])

        adjusted = validate_success(
            api.create_stock_adjustment(
                part["id"], {"delta": -1, "reason": "cycle count write-down"},
                fx.PC,
            )
        )
        assert adjusted["stock_status"] == "BACKORDERED", (
            "on_hand 0 with reserved 1 gives available -1"
        )

        campaign_after = get_success_data(api.get_campaign(campaign["id"], fx.FM))
        assert campaign_after["status"] == "SUSPENDED", (
            "BACKORDERED required part must auto-suspend the ACTIVE campaign "
            "with no direct campaign call"
        )


class TestEmissionsRetestGate:
    """An EMISSIONS work order cannot submit for QA without a PASS retest."""

    def _setup(self):
        bus = new_bus(fleet_number="X1", vin="VINX1", model_year=2021,
                      base_warranty_expiry_miles=5_000,
                      base_warranty_expiry_date="2024-01-01")
        lead = new_mechanic(name="Emissions Tech", employee_ref="E80")
        grant_cert(lead["id"], "EMISSIONS")
        qa = new_qa_mechanic()
        inspection = record_inspection(bus["id"], result="FAIL")
        wo = fx.get_inspection_auto_wo(inspection["id"])
        fx.assign_lead(wo["id"], lead["id"])
        start_wo(wo["id"])
        add_labor(wo["id"], lead, work_date="2026-08-01", hours=1)
        return bus, lead, qa, wo

    def test_submit_qa_without_passing_retest_rejected(self, api):
        """PRD §3.4: "And for an `EMISSIONS` work order specifically, a passing
        retest is required: a `PASS` emissions inspection for the bus must
        exist whose `created_at` is at or after the work order's most recent
        entry into `IN_PROGRESS`; without one the transition is rejected with
        `ERR_EMISSIONS_RETEST_REQUIRED`."

        Design: Difficulty/cross_entity_state_dependency/emissions_wo_blocked_until_passing_retest
        """
        _, lead, _, wo = self._setup()
        res = wo_event(wo["id"], "SUBMIT_QA",
                       headers=make_mechanic_headers(lead["id"]))
        validate_error(res, ApiErrorId.ERR_EMISSIONS_RETEST_REQUIRED)
        after = get_success_data(api.get_work_order(wo["id"], fx.SUP))
        assert after["status"] == "IN_PROGRESS"

    def test_passing_retest_unblocks_submit_and_close(self, api):
        """PRD §3.4: "And for an `EMISSIONS` work order specifically, a passing
        retest is required: a `PASS` emissions inspection for the bus must
        exist whose `created_at` is at or after the work order's most recent
        entry into `IN_PROGRESS`; without one the transition is rejected with
        `ERR_EMISSIONS_RETEST_REQUIRED`."
        PRD §3.9: "A subsequent `PASS` retest sets the bus's
        `emissions_cert_expiry_date` to the new certificate expiry and clears
        the `EMISSIONS` hold."

        Design: Difficulty/cross_entity_state_dependency/emissions_wo_blocked_until_passing_retest
        """
        bus, lead, qa, wo = self._setup()
        record_inspection(bus["id"], result="PASS",
                          certificate_expiry_date="2027-08-01")

        pending = validate_success(
            wo_event(wo["id"], "SUBMIT_QA",
                     headers=make_mechanic_headers(lead["id"]))
        )
        assert pending["status"] == "PENDING_QA"
        closed = validate_success(
            wo_event(wo["id"], "QA_CERTIFY",
                     headers=make_mechanic_headers(qa["id"]))
        )
        assert closed["status"] == "CLOSED"

        bus_after = get_success_data(api.get_bus(bus["id"], fx.FM))
        assert bus_after["emissions_cert_expiry_date"] == "2027-08-01"
        assert bus_after["availability_status"] == "AVAILABLE", (
            "hold cleared and the closed work order frees the bus"
        )


class TestCampaignProgressAndCompletion:
    """Progress derives from CLOSED work orders of the frozen scope."""

    def _setup(self):
        buses = fx.new_buses(
            2, model_year=2021, fleet_prefix="C",
            base_warranty_expiry_miles=5_000,
            base_warranty_expiry_date="2024-01-01",
        )
        lead = new_mechanic(name="Lead", employee_ref="E90")
        qa = new_qa_mechanic()
        campaign = new_campaign(code="CMP-50", title="Mirror retrofit")
        campaign = activate_campaign(campaign["id"])
        assert campaign["status"] == "ACTIVE"
        assert len(campaign["scope_bus_ids"]) == 2
        return buses, lead, qa, campaign

    def test_first_close_reports_half_progress_and_stays_active(self, api):
        """PRD §3.9: "`buses_completed_count` is the number of buses in
        `scope_bus_ids` that have a `CLOSED` work order citing this campaign.
        `progress_pct` is one hundred times that count divided by the size of
        `scope_bus_ids`, rounded half-up to 2 decimal places. When
        `progress_pct` reaches 100, the campaign automatically transitions from
        `ACTIVE` to `COMPLETED`."

        Design: Difficulty/cross_entity_state_dependency/campaign_auto_completes_when_last_scope_wo_closes
        """
        buses, lead, qa, campaign = self._setup()
        fx.close_campaign_wo(buses[0]["id"], campaign["id"], lead, qa)

        after = get_success_data(api.get_campaign(campaign["id"], fx.FM))
        assert_campaign(after)
        assert after["buses_completed_count"] == 1
        assert after["progress_pct"] == 50.0
        assert after["status"] == "ACTIVE", "below 100% the campaign stays ACTIVE"

    def test_last_scope_close_auto_completes_campaign(self, api):
        """PRD §3.9: "`buses_completed_count` is the number of buses in
        `scope_bus_ids` that have a `CLOSED` work order citing this campaign.
        `progress_pct` is one hundred times that count divided by the size of
        `scope_bus_ids`, rounded half-up to 2 decimal places. When
        `progress_pct` reaches 100, the campaign automatically transitions from
        `ACTIVE` to `COMPLETED`."

        Design: Difficulty/cross_entity_state_dependency/campaign_auto_completes_when_last_scope_wo_closes
        """
        buses, lead, qa, campaign = self._setup()
        fx.close_campaign_wo(buses[0]["id"], campaign["id"], lead, qa)
        fx.close_campaign_wo(buses[1]["id"], campaign["id"], lead, qa)

        after = get_success_data(api.get_campaign(campaign["id"], fx.FM))
        assert after["buses_completed_count"] == 2
        assert after["progress_pct"] == 100.0
        assert after["status"] == "COMPLETED", (
            "the final scope close auto-completes the campaign with no "
            "campaign event call"
        )


def test_emissions_cert_expiry_epoch_grounds_bus(api):
    """PRD §3.9: "The epoch sweep additionally grounds any bus whose
    certificate has expired, adding an `EMISSIONS` hold even without a fresh
    inspection. The bus's `emissions_compliance` derived field reports
    `COMPLIANT`, `CERT_EXPIRED`, or `NON_COMPLIANT` (the latter when an
    emissions hold is active)."
    PRD §2.5: "The sweep returns a summary including `epoch_index`, the
    resulting `posture`, and counters `defects_reopened`, `cores_aged`,
    `certifications_expired`, and `buses_grounded`."

    Certificate 2026-07-15 is strictly before the clock date 2026-08-01.

    Design: Corner/validations/emissions_cert_expiry_epoch_grounds_bus
    """
    bus = new_bus(fleet_number="Y35", vin="VINY35", model_year=2021,
                  base_warranty_expiry_miles=5_000,
                  base_warranty_expiry_date="2024-01-01")
    record_inspection(bus["id"], test_type="OPACITY", test_date="2026-07-01",
                      result="PASS", certificate_expiry_date="2026-07-15")

    summary = run_epoch()
    assert summary["buses_grounded"] == 1, (
        f"exactly one bus has an expired certificate; summary: {summary}"
    )
    bus_after = get_success_data(api.get_bus(bus["id"], fx.FM))
    assert bus_after["availability_status"] == "HELD"
    assert "EMISSIONS" in bus_after["hold_reasons"]
    assert bus_after["emissions_compliance"] == "NON_COMPLIANT"


def test_pass_inspection_missing_cert_expiry_invalid(api):
    """PRD §3.9: "A `PASS` requires a `certificate_expiry_date` (otherwise
    `ERR_VALIDATION`), which is then set as the bus's
    `emissions_cert_expiry_date`."

    Design: Corner/validations/pass_inspection_missing_cert_expiry_invalid
    """
    bus = new_bus(fleet_number="Y32", vin="VINY32", model_year=2021,
                  base_warranty_expiry_miles=5_000,
                  base_warranty_expiry_date="2024-01-01")
    payload = create_inspection_payload(bus["id"], result="PASS")
    payload.pop("certificate_expiry_date")
    res = api.create_emissions_inspection(payload, fx.SUP)
    validate_error(res, ApiErrorId.ERR_VALIDATION)
    inspections = get_success_data(
        api.list_bus_emissions_inspections(bus["id"], fx.FM)
    )
    assert inspections == [], "no inspection may be persisted"


def test_campaign_activate_empty_scope_rejected(api):
    """PRD §3.9: "Activating a campaign freezes its scope: the set of buses
    whose `model_year` is within the closed range from `model_year_from` to
    `model_year_to` and whose `service_status` is `ACTIVE` at that instant,
    sorted by `fleet_number` ascending with ties broken by `created_at`
    ascending, is stored as `scope_bus_ids`. An activation whose scope is empty
    is rejected with `ERR_CAMPAIGN_SCOPE_EMPTY`."

    Design: Corner/validations/campaign_activate_empty_scope_rejected
    """
    new_bus(fleet_number="Y16", vin="VINY16", model_year=2023,
            base_warranty_expiry_miles=5_000,
            base_warranty_expiry_date="2024-01-01")
    campaign = new_campaign(code="CMP-OLD", title="Legacy buses",
                            model_year_from=2015, model_year_to=2016)

    res = campaign_event(campaign["id"], "ACTIVATE")
    validate_error(res, ApiErrorId.ERR_CAMPAIGN_SCOPE_EMPTY)
    after = get_success_data(api.get_campaign(campaign["id"], fx.FM))
    assert after["status"] == "DRAFT", "a rejected activation stores no scope"


def test_campaign_wo_rejected_when_campaign_not_active(api):
    """PRD §3.3: "If the work order cites a `campaign_id`, that campaign must
    currently be `ACTIVE` (otherwise `ERR_CAMPAIGN_NOT_ACTIVE`)."

    The rejection must surface before the citing work order can be scheduled:
    an implementation may enforce the gate at create or at schedule; both paths
    must yield ERR_CAMPAIGN_NOT_ACTIVE.

    Design: Corner/validations/campaign_wo_create_when_campaign_not_active_rejected
    """
    bus = new_bus(fleet_number="Y17", vin="VINY17", model_year=2021,
                  base_warranty_expiry_miles=5_000,
                  base_warranty_expiry_date="2024-01-01")
    campaign = new_campaign(code="CMP-DR", title="Draft campaign")
    assert campaign["status"] == "DRAFT"

    created = api.create_work_order(
        create_work_order_payload(
            bus["id"], bus_version(bus["id"]), wo_type="CAMPAIGN",
            campaign_id=campaign["id"], planned_start_date="2026-08-10",
            planned_end_date="2026-08-11", estimated_labor_hours=2,
            estimated_cost_cents=13_000,
        ),
        fx.SUP,
    )
    if created.status_code >= 400:
        validate_error(created, ApiErrorId.ERR_CAMPAIGN_NOT_ACTIVE)
        return
    wo = validate_success(created, 201)
    res = wo_event(wo["id"], "SCHEDULE")
    validate_error(res, ApiErrorId.ERR_CAMPAIGN_NOT_ACTIVE)


def test_campaign_scope_frozen_at_activation_keeps_retired_bus(api):
    """PRD §3.9: "Buses that retire after activation remain in scope — the
    denominator does not shrink — so progress can stall below 100% if a scoped
    bus is retired before its campaign work order closes."

    Design: Corner/calculations/campaign_scope_frozen_at_activation_keeps_retired_bus
    """
    buses = fx.new_buses(
        2, model_year=2021, fleet_prefix="CF",
        base_warranty_expiry_miles=5_000,
        base_warranty_expiry_date="2024-01-01",
    )
    lead = new_mechanic(name="Lead", employee_ref="CF1A")
    qa = new_qa_mechanic()
    campaign = activate_campaign(new_campaign(code="CMP-FR",
                                              title="Frozen scope demo")["id"])
    fx.close_campaign_wo(buses[0]["id"], campaign["id"], lead, qa)

    validate_success(
        api.retire_bus(buses[1]["id"], {"retirement_reason": "collision damage"},
                       fx.FM)
    )

    after = get_success_data(api.get_campaign(campaign["id"], fx.FM))
    assert len(after["scope_bus_ids"]) == 2, (
        "the retired bus stays in the frozen scope"
    )
    assert buses[1]["id"] in after["scope_bus_ids"]
    assert after["progress_pct"] == 50.0, (
        "the denominator does not shrink on retirement"
    )
    assert after["status"] == "ACTIVE"
