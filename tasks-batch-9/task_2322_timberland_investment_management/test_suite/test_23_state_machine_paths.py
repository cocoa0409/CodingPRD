"""Lifecycle paths: declared advances, initial states, terminal states and the bubbling audit."""

from test_helpers import (
    ApiErrorId,
    assert_acres,
    assert_bps,
    assert_fund_cash,
    assert_money,
    assert_pagination_meta,
    assert_property_dimensions,
    assert_stand_partition,
    assert_tons,
    assert_tons_per_acre,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.factories import (
    carbon_project_payload,
    certification_audit_payload,
    cruise_plot_payload,
    hazard_event_payload,
)
from test_helpers.fixtures import (
    advance_audit,
    advance_parcel,
    audit_with_open_findings,
    commit_block,
    complete_block,
    create_lease,
    cruised_stand,
    identify_parcel,
    owned_tract,
    read_audit,
    read_block,
    read_carbon_project,
    read_dedication,
    read_finding,
    read_fund,
    read_hazard_event,
    read_parcel,
    read_property,
    read_stand,
    registered_carbon_project,
    report_hazard,
    reserve_block,
    schedule_audit,
    settle_hazard,
    stand_version,
    submit_car,
    verify_close_car,
)
from test_helpers.test_users import (
    make_auditor_headers,
    make_carbon_developer_headers,
    make_forest_manager_headers,
    make_fund_admin_headers,
)

PARCEL_A = {"parcel_code": "PC-01-A", "acres": 30.00, "ask_price_usd": 90000.00}
PARCEL_B = {"parcel_code": "PC-01-B", "acres": 40.00, "ask_price_usd": 120000.00}
BIG_PARCEL = {"parcel_code": "PC-01-A", "acres": 110.00, "ask_price_usd": 300000.00}
SMALL_PARCEL = {"parcel_code": "PC-01-A", "acres": 40.00, "ask_price_usd": 120000.00}


def _two_open_majors(api, property_id):
    """An audit in FINDINGS_ISSUED carrying two open major nonconformances."""
    return audit_with_open_findings(api, property_id, ("MAJOR", "MAJOR"))


def _completed_block(api):
    """A cruise-closed stand whose thousand-ton block has been harvested out."""
    ctx = cruised_stand(api)
    block = reserve_block(api, ctx.stand_id, planned_tons=1000.00)
    commit_block(api, block["id"])
    completed = complete_block(api, block["id"], 940.50, 0.92)
    return ctx, completed


class TestAuditAdvancesThroughItsDeclaredPath:
    """Scheduling, field work and issuance are the audit's opening moves."""

    def test_the_audit_walks_scheduled_to_field_work_to_findings_issued(self, api):
        """A clean audit advances twice and leaves the tract certified.

        PRD: "Starting field work moves the audit from `SCHEDULED` to `FIELD_WORK` and requires the property's `certification_scheme` to be something other than `NONE`; a tract enrolled in no scheme cannot be audited, and the attempt is refused as an undeclared transition with `ERR_INVALID_STATE_TRANSITION`."

        Design: Corner/state_machines/audit_scheduled_to_field_work_to_findings_issued_advances
        """
        ctx = owned_tract(api)
        audit = schedule_audit(api, ctx.property_id)
        assert audit["status"] == "SCHEDULED"
        assert audit["major_finding_count"] == 0
        assert audit["open_major_count"] == 0
        assert audit["open_minor_count"] == 0

        field_work = advance_audit(api, audit["id"], "START_FIELD_WORK")
        issued = advance_audit(api, audit["id"], "ISSUE_FINDINGS")

        assert field_work["status"] == "FIELD_WORK"
        assert issued["status"] == "FINDINGS_ISSUED"
        assert_property_dimensions(
            read_property(api, ctx.property_id),
            status="OWNED",
            certification_posture="CERTIFIED",
            harvest_plan_status="ALIGNED",
        )
        assert_fund_cash(
            read_fund(api, ctx.fund_id),
            cash_balance_usd=300000.00,
            net_operating_cash_usd=0.00,
        )


class TestSuspensionAndReinstatement:
    """Two open majors suspend the tract; closing one lets it be reinstated."""

    def test_reinstatement_after_one_major_closes_restores_the_conditional_posture(
        self, api
    ):
        """Suspension needs two open majors and reinstatement needs at most one.

        PRD: "An auditor may also suspend an audit explicitly, moving it from `FINDINGS_ISSUED` to `SUSPENDED`; that action requires `open_major_count` of at least two and drives the property's posture to `SUSPENDED` with the same committed-block revert."

        Design: Corner/state_machines/audit_suspend_then_reinstate_restores_conditional_posture
        """
        ctx = owned_tract(api)
        audit = _two_open_majors(api, ctx.property_id)
        first = audit.findings[0]

        suspended = advance_audit(api, audit.audit_id, "SUSPEND")

        assert suspended["status"] == "SUSPENDED"
        assert suspended["open_major_count"] == 2
        assert_property_dimensions(
            read_property(api, ctx.property_id), certification_posture="SUSPENDED"
        )

        submit_car(api, first["id"], manager="fm-1")
        verify_close_car(api, first["id"], auditor="ca-1")
        assert read_audit(api, audit.audit_id)["open_major_count"] == 1

        reinstated = advance_audit(api, audit.audit_id, "REINSTATE")

        assert reinstated["status"] == "FINDINGS_ISSUED"
        assert_property_dimensions(
            read_property(api, ctx.property_id), certification_posture="CONDITIONAL"
        )


class TestActiveDedicationsArePermanenceLocked:
    """A registered pledge cannot be walked back before its permanence date."""

    def test_an_early_release_of_an_active_dedication_is_locked(self, api):
        """A thirty-year permanence term runs to 2056 and blocks release today.

        PRD: "An `ACTIVE` dedication is locked: it may be released only once the logical clock date has reached or passed its `permanence_end_date`, and an earlier attempt is refused with `ERR_CARBON_PERMANENCE_LOCK`; on release its tonnage returns to `available_tons` and the stand's `version` is incremented."

        Design: Corner/state_machines/dedication_release_before_permanence_end_is_locked
        """
        ctx = owned_tract(api)
        carbon = registered_carbon_project(api, ctx.property_id, ctx.stand_id)
        assert carbon.dedications[0]["permanence_end_date"] == "2056-08-01"
        assert_tons(carbon.project["buffer_pool_tons"], 90.00, "buffer_pool_tons")

        response = api.release_carbon_dedication(
            carbon.dedication_id, None, make_carbon_developer_headers()
        )

        validate_error(response, ApiErrorId.CARBON_PERMANENCE_LOCK.value, 409)
        locked = read_dedication(api, carbon.dedication_id)
        assert locked["status"] == "ACTIVE"
        assert_tons(locked["reduced_tons"], 0.00, "reduced_tons")
        assert_stand_partition(
            read_stand(api, ctx.stand_id),
            dedicated_tons=500.00,
            available_tons=4147.12,
        )
        project = read_carbon_project(api, carbon.project_id)
        assert_tons(project["dedicated_tons_total"], 500.00, "dedicated_tons_total")
        assert_tons(project["buffer_deficit_tons"], 0.00, "buffer_deficit_tons")


class TestListingOpensTheDispositionPipeline:
    """Listing a parcel puts the whole tract on the market."""

    def test_listing_a_parcel_flips_the_tract_to_hbu_marketed(self, api):
        """The parcel goes to listed and the tract follows it onto the market.

        PRD: "Listing also drives the property's `status` from `OWNED` to `HBU_MARKETED`."

        Design: Corner/state_machines/hbu_listing_flips_property_to_hbu_marketed
        """
        ctx = owned_tract(api)
        parcel = identify_parcel(api, ctx.stand_id, **BIG_PARCEL)

        listed = advance_parcel(api, parcel["id"], "LIST")

        assert listed["status"] == "LISTED"
        assert_tons(listed["withdrawn_tons"], 0.00, "withdrawn_tons")
        assert listed["commission_usd"] is None
        assert listed["net_proceeds_usd"] is None
        assert_property_dimensions(
            read_property(api, ctx.property_id), status="HBU_MARKETED"
        )
        stand = read_stand(api, ctx.stand_id)
        assert stand["status"] == "INVENTORIED"
        assert_acres(stand["acres"], 120.00, "acres")
        assert_stand_partition(
            stand, net_merch_tons=4647.12, hbu_withdrawn_tons=0.00
        )
        assert_fund_cash(
            read_fund(api, ctx.fund_id),
            cash_balance_usd=300000.00,
            net_operating_cash_usd=0.00,
        )
        derived, meta = validate_paginated(
            api.list_stand_derived_stands(ctx.stand_id, make_forest_manager_headers())
        )
        assert derived == [], "nothing has been split off the parent stand yet"
        assert_pagination_meta(meta, total_count=0)


class TestCompletedBlocksAreTerminal:
    """A harvested block cannot be committed again."""

    def test_a_completed_block_refuses_a_second_commit(self, api):
        """The replayed commit is an undeclared transition and moves no cash.

        PRD: "Committing a reserved block advances it from `RESERVED` to `COMMITTED`."

        Design: Corner/state_machines/commit_on_a_completed_block_cannot_repeat
        """
        ctx, completed = _completed_block(api)
        assert completed["status"] == "COMPLETED"
        assert_money(
            completed["final_net_revenue_usd"], 15858.07, "final_net_revenue_usd"
        )

        response = api.commit_harvest_block(
            completed["id"], None, make_forest_manager_headers()
        )

        validate_error(response, ApiErrorId.INVALID_STATE_TRANSITION.value, 409)
        assert read_block(api, completed["id"])["status"] == "COMPLETED"
        assert_tons(
            read_stand(api, ctx.stand_id)["net_merch_tons"], 3706.62, "net_merch_tons"
        )
        assert_fund_cash(
            read_fund(api, ctx.fund_id),
            cash_balance_usd=415858.07,
            net_operating_cash_usd=15858.07,
        )


class TestNewlyCreatedEntitiesStartInTheirInitialState:
    """Every lifecycle resource is born in the state its section declares."""

    def test_each_new_lifecycle_resource_lands_in_its_declared_initial_state(self, api):
        """Audit, lease, parcel, project and hazard event all start where the contract says.

        PRD: "A new audit is `SCHEDULED` with `major_finding_count`, `open_major_count` and `open_minor_count` all 0, and scheduling recomputes the property's `certification_posture`."

        Design: Corner/state_machines/newly_created_lifecycle_entities_start_in_initial_state
        """
        ctx = owned_tract(api)

        audit = validate_success(
            api.create_certification_audit(
                certification_audit_payload(
                    ctx.property_id, scheduled_date="2026-09-15"
                ),
                make_auditor_headers(),
            ),
            201,
        )
        lease = create_lease(api, ctx.property_id)
        parcel = identify_parcel(api, ctx.stand_id, **SMALL_PARCEL)
        project = validate_success(
            api.create_carbon_project(
                carbon_project_payload(ctx.property_id), make_carbon_developer_headers()
            ),
            201,
        )

        assert audit["status"] == "SCHEDULED"
        assert audit["major_finding_count"] == 0
        assert audit["open_major_count"] == 0
        assert audit["open_minor_count"] == 0
        assert lease["status"] == "PENDING"
        assert_money(lease["annual_rent_usd"], 13500.00, "annual_rent_usd")
        assert lease["term_days"] == 365
        assert lease["first_year_prorated_rent_usd"] is None
        assert parcel["status"] == "IDENTIFIED"
        assert_tons(parcel["withdrawn_tons"], 0.00, "withdrawn_tons")
        assert project["status"] == "DRAFT"
        assert_tons(project["dedicated_tons_total"], 0.00, "dedicated_tons_total")
        assert_tons(project["buffer_pool_tons"], 0.00, "buffer_pool_tons")
        assert_tons(project["buffer_deficit_tons"], 0.00, "buffer_deficit_tons")

    def test_a_new_hazard_event_starts_reported_with_an_empty_log(self, api):
        """A wind storm is priced on arrival but settles nothing and moves no cash.

        PRD: "A new event is `REPORTED`, with `settled_claim_usd` and `salvage_sold_tons` unset, `inventory_shortfall_tons` 0.00 and an empty `reallocation_log`."

        Design: Corner/state_machines/newly_created_lifecycle_entities_start_in_initial_state
        """
        ctx = owned_tract(api)

        event = validate_success(
            api.create_hazard_event(
                hazard_event_payload(
                    ctx.stand_id,
                    event_type="WIND_STORM",
                    occurred_at="2026-07-20T00:00:00Z",
                    damaged_tons=1000.00,
                ),
                make_forest_manager_headers(),
            ),
            201,
        )

        assert event["status"] == "REPORTED"
        assert_tons(event["salvageable_tons"], 700.00, "salvageable_tons")
        assert_money(event["insurance_claim_usd"], 13500.00, "insurance_claim_usd")
        assert event["settled_claim_usd"] is None
        assert event["salvage_sold_tons"] is None
        assert_tons(
            event["inventory_shortfall_tons"], 0.00, "inventory_shortfall_tons"
        )
        assert event["reallocation_log"] == []
        stand = read_stand(api, ctx.stand_id)
        assert stand["status"] == "SALVAGE_PENDING"
        assert_tons(stand["net_merch_tons"], 3647.12, "net_merch_tons")
        assert_property_dimensions(
            read_property(api, ctx.property_id), harvest_plan_status="ALIGNED"
        )
        assert_fund_cash(read_fund(api, ctx.fund_id), cash_balance_usd=300000.00)


class TestSettledHazardEventsAreTerminal:
    """A carrier pays once."""

    def test_a_settled_event_refuses_a_second_settlement(self, api):
        """The replayed settlement is refused and the claim is credited exactly once.

        PRD: "On success the event moves from `REPORTED` to the terminal `SETTLED`, the stand moves back from `SALVAGE_PENDING` to `INVENTORIED`"

        Design: Corner/state_machines/settled_hazard_event_rejects_a_second_salvage_settlement
        """
        ctx = cruised_stand(api)
        event = report_hazard(api, ctx.stand_id, damaged_tons=1000.00)
        settle_hazard(api, event["id"], 13500.00, 350.00)

        response = api.settle_hazard_event(
            event["id"],
            {"settled_claim_usd": 13500.00, "salvage_sold_tons": 350.00},
            make_fund_admin_headers(),
        )

        validate_error(response, ApiErrorId.INVALID_STATE_TRANSITION.value, 409)
        assert read_hazard_event(api, event["id"])["status"] == "SETTLED"
        stand = read_stand(api, ctx.stand_id)
        assert stand["status"] == "INVENTORIED"
        assert_tons(stand["net_merch_tons"], 3647.12, "net_merch_tons")
        fund = read_fund(api, ctx.fund_id)
        assert_fund_cash(
            fund, cash_balance_usd=413500.00, net_operating_cash_usd=13500.00
        )
        assert_bps(fund["cash_yield_bps"], 270, "cash_yield_bps")


class TestClosedCruisesAreFrozen:
    """Neither a second closure nor a late plot is admitted."""

    def test_a_second_closure_and_a_late_plot_are_both_refused(self, api):
        """The frozen sample keeps its five plots and its expanded tonnage.

        PRD: "The stand must still be `CRUISE_OPEN`, or the request fails with `ERR_CRUISE_ALREADY_CLOSED`, and it must have at least one recorded plot, or the request fails with `ERR_NO_CRUISE_PLOTS`."

        Design: Corner/state_machines/second_cruise_close_is_rejected_as_already_closed
        """
        ctx = cruised_stand(api)
        version = stand_version(api, ctx.stand_id)

        second_close = api.close_cruise(
            ctx.stand_id, None, make_forest_manager_headers()
        )
        late_plot = api.create_cruise_plot(
            cruise_plot_payload(
                ctx.stand_id,
                plot_number=6,
                tons_per_acre=40.00,
                defect_pct=5.0,
                measured_at="2026-07-20T00:00:00Z",
            ),
            make_forest_manager_headers(),
        )

        validate_error(second_close, ApiErrorId.CRUISE_ALREADY_CLOSED.value, 409)
        validate_error(late_plot, ApiErrorId.CRUISE_ALREADY_CLOSED.value, 409)
        stand = read_stand(api, ctx.stand_id)
        assert stand["status"] == "INVENTORIED"
        assert stand["plot_count"] == 5
        assert stand["cruise_confidence"] == "NORMAL"
        assert_tons_per_acre(
            stand["mean_net_tons_per_acre"], 38.726, "mean_net_tons_per_acre"
        )
        assert_tons(stand["net_merch_tons"], 4647.12, "net_merch_tons")
        assert stand["version"] == version
        _plots, meta = validate_paginated(
            api.list_stand_cruise_plots(ctx.stand_id, make_forest_manager_headers())
        )
        assert_pagination_meta(meta, total_count=5)


class TestAuditBubblesOnlyWhenNothingRemainsOpen:
    """The audit advances to review once every finding carries a corrective action."""

    def test_the_audit_bubbles_to_car_review_on_the_second_submission(self, api):
        """One corrective action leaves the audit where it was; the second moves it.

        PRD: "When that submission leaves no finding of the audit in `OPEN`, and the audit has at least one open major or minor finding in total, the audit itself advances from `FINDINGS_ISSUED` to `CAR_REVIEW`."

        Design: Corner/state_machines/audit_bubbles_to_car_review_only_when_every_finding_has_a_car
        """
        ctx = owned_tract(api)
        audit = audit_with_open_findings(api, ctx.property_id, ("MINOR", "MINOR"))

        submit_car(api, audit.findings[0]["id"], manager="fm-1")
        assert read_audit(api, audit.audit_id)["status"] == "FINDINGS_ISSUED"

        submit_car(api, audit.findings[1]["id"], manager="fm-1")

        bubbled = read_audit(api, audit.audit_id)
        assert bubbled["status"] == "CAR_REVIEW"
        assert bubbled["open_minor_count"] == 2
        assert bubbled["open_major_count"] == 0
        for finding in audit.findings:
            row = read_finding(api, finding["id"])
            assert row["status"] == "CAR_SUBMITTED"
            assert row["car_submitted_by_user_id"] == "fm-1"
            assert row["rejection_count"] == 0
        assert_property_dimensions(
            read_property(api, ctx.property_id), certification_posture="CONDITIONAL"
        )


class TestCommitmentIsABucketTransfer:
    """Commitment moves tons between buckets without touching the residue."""

    def test_commitment_leaves_the_available_pool_exactly_where_it_was(self, api):
        """A thousand tons cross from reserved to committed and available stays 3647.12.

        PRD: "Moving tons between the reserved and committed buckets does not change `available_tons`."

        Design: Corner/state_machines/commit_moves_reserved_tons_to_committed_without_changing_available
        """
        ctx = cruised_stand(api)
        block = reserve_block(api, ctx.stand_id, planned_tons=1000.00)
        before = read_stand(api, ctx.stand_id)
        assert_stand_partition(
            before,
            reserved_tons=1000.00,
            committed_tons=0.00,
            available_tons=3647.12,
        )

        committed = commit_block(api, block["id"])

        assert committed["status"] == "COMMITTED"
        assert_tons(committed["planned_tons"], 1000.00, "planned_tons")
        assert_money(
            committed["provisional_net_revenue_usd"],
            22889.55,
            "provisional_net_revenue_usd",
        )
        after = read_stand(api, ctx.stand_id)
        assert_stand_partition(
            after,
            net_merch_tons=4647.12,
            reserved_tons=0.00,
            committed_tons=1000.00,
            available_tons=3647.12,
        )
        assert after["version"] == before["version"] + 1


class TestTheTractLeavesTheMarketOnlyWhenThePipelineEmpties:
    """One withdrawal is not enough while another parcel is still listed."""

    def test_the_property_returns_to_owned_only_after_the_last_parcel_withdraws(self, api):
        """Withdrawing the first parcel keeps the tract marketed; the second releases it.

        PRD: "Withdrawing a `LISTED` or an `UNDER_CONTRACT` parcel returns the property's `status` from `HBU_MARKETED` to `OWNED`"

        Design: Corner/state_machines/property_returns_to_owned_only_when_the_last_parcel_leaves_listed
        """
        ctx = owned_tract(api)
        first = identify_parcel(api, ctx.stand_id, **PARCEL_A)
        second = identify_parcel(api, ctx.stand_id, **PARCEL_B)
        advance_parcel(api, first["id"], "LIST")
        advance_parcel(api, second["id"], "LIST")
        assert_property_dimensions(
            read_property(api, ctx.property_id), status="HBU_MARKETED"
        )

        advance_parcel(api, first["id"], "WITHDRAW")
        assert_property_dimensions(
            read_property(api, ctx.property_id), status="HBU_MARKETED"
        )

        advance_parcel(api, second["id"], "WITHDRAW")

        assert_property_dimensions(read_property(api, ctx.property_id), status="OWNED")
        for parcel in (first, second):
            row = read_parcel(api, parcel["id"])
            assert row["status"] == "WITHDRAWN"
            assert_tons(row["withdrawn_tons"], 0.00, "withdrawn_tons")
            assert row["net_proceeds_usd"] is None
        stand = read_stand(api, ctx.stand_id)
        assert stand["status"] == "INVENTORIED"
        assert_acres(stand["acres"], 120.00, "acres")
        assert_stand_partition(stand, hbu_withdrawn_tons=0.00)
        assert_fund_cash(
            read_fund(api, ctx.fund_id),
            cash_balance_usd=300000.00,
            net_operating_cash_usd=0.00,
        )


class TestAuditClosureRequiresAClearRegister:
    """Closure is blocked while any major or minor finding is outstanding."""

    def test_closure_is_blocked_until_the_open_finding_is_verified_closed(self, api):
        """The blocked closure succeeds once the corrective action is verified.

        PRD: "both branches require `open_major_count` and `open_minor_count` to be exactly zero, and a closure attempted with any open major or minor finding outstanding is refused with `ERR_OPEN_FINDINGS_BLOCK_CLOSURE`."

        Design: Corner/endpoints/audit_close_is_blocked_while_a_finding_remains_open
        """
        ctx = owned_tract(api)
        audit = audit_with_open_findings(api, ctx.property_id, ("MINOR",))

        response = api.advance_certification_audit(
            audit.audit_id, {"action": "CLOSE"}, make_auditor_headers()
        )

        validate_error(response, ApiErrorId.OPEN_FINDINGS_BLOCK_CLOSURE.value, 409)
        assert read_audit(api, audit.audit_id)["status"] == "FINDINGS_ISSUED"

        submit_car(api, audit.finding_id, manager="manager-1")
        assert read_audit(api, audit.audit_id)["status"] == "CAR_REVIEW"
        closed_finding = verify_close_car(api, audit.finding_id, auditor="auditor-2")
        assert closed_finding["status"] == "CLOSED"
        assert closed_finding["closed_by_user_id"] == "auditor-2"
        assert closed_finding["car_submitted_by_user_id"] == "manager-1"
        assert closed_finding["rejection_count"] == 0

        closed = validate_success(
            api.advance_certification_audit(
                audit.audit_id, {"action": "CLOSE"}, make_auditor_headers()
            ),
            200,
        )

        assert closed["status"] == "CLOSED_CONFORMING"
        assert closed["open_minor_count"] == 0
        assert closed["open_major_count"] == 0
        assert_property_dimensions(
            read_property(api, ctx.property_id), certification_posture="CERTIFIED"
        )
