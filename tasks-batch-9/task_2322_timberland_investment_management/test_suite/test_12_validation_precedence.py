"""Validation precedence: the state gate, the safety gate and the referential check all outrank the fiscal check."""

from test_helpers import (
    ApiErrorId,
    assert_pagination_meta,
    assert_stand_partition,
    assert_tons,
    validate_error,
    validate_paginated,
)
from test_helpers.factories import (
    CANONICAL_CRUISE_PLOTS,
    carbon_dedication_payload,
    harvest_block_payload,
)
from test_helpers.fixtures import (
    activate_lease,
    advance_audit,
    close_cruise,
    create_carbon_project,
    create_lease,
    create_property,
    create_stand,
    open_cruise_stand,
    owned_tract,
    raise_finding,
    read_audit,
    read_block,
    read_carbon_project,
    read_property,
    read_stand,
    record_cruise_plot,
    reserve_block,
    schedule_audit,
    stand_version,
    submit_car,
    verify_close_car,
)
from test_helpers.test_users import (
    make_carbon_developer_headers,
    make_forest_manager_headers,
)

OVERSIZED_BLOCK = {
    "planned_start_date": "2027-06-01",
    "planned_end_date": "2027-09-30",
    "planned_tons": 5000.00,
    "product_mix": "MIXED",
    "expected_stumpage_price_usd_per_ton": 58.00,
    "price_index_factor": 1.05,
    "expected_haul_distance_miles": 140,
}
BEAR_HOLLOW_PROPERTY = {"name": "Bear Hollow Tract", "total_acres": 1200.00}
BEAR_HOLLOW_STAND = {"stand_code": "BH-01", "acres": 120.00}
SINGLE_PLOT = CANONICAL_CRUISE_PLOTS[0]


def _attempt_reservation(api, stand_id):
    return api.create_harvest_block(
        harvest_block_payload(stand_id, stand_version(api, stand_id), **OVERSIZED_BLOCK),
        make_forest_manager_headers(),
    )


def _attempt_dedication(api, project_id, stand_id, dedicated_tons=5000.00):
    return api.create_carbon_dedication(
        carbon_dedication_payload(
            project_id,
            stand_id,
            stand_version(api, stand_id),
            dedicated_tons=dedicated_tons,
        ),
        make_carbon_developer_headers(),
    )


class TestStateGateOutranksTheTonnageCheck:
    """An uninventoried stand is reported before the over-reservation is even weighed."""

    def test_an_open_cruise_is_reported_ahead_of_the_oversized_reservation(self, api):
        """A stand still in cruise yields the state gate, not the fiscal check.

        PRD: "The stand must be `INVENTORIED` — a stand still `CRUISE_OPEN` or sitting in `SALVAGE_PENDING` yields `ERR_STAND_NOT_INVENTORIED`."

        Design: Difficulty/priority_pair_validation_conflict/stand_not_inventoried_at_55_beats_insufficient_tons_at_80
        """
        ctx = open_cruise_stand(api)
        for plot in CANONICAL_CRUISE_PLOTS:
            record_cruise_plot(api, ctx.stand_id, **plot)
        assert read_stand(api, ctx.stand_id)["status"] == "CRUISE_OPEN"

        response = _attempt_reservation(api, ctx.stand_id)

        validate_error(response, ApiErrorId.STAND_NOT_INVENTORIED.value, 409)

    def test_closing_the_cruise_exposes_the_fiscal_check_underneath(self, api):
        """With the state gate satisfied the same request now fails on available tons.

        PRD: "`ERR_INSUFFICIENT_AVAILABLE_TONS`, `ERR_ACTUAL_TONS_EXCEED_PLANNED`, `ERR_LEASE_ACREAGE_EXCEEDED`, `ERR_FUND_CASH_INSUFFICIENT`, `ERR_BID_EXCEEDS_UNDERWRITTEN_VALUE`, `ERR_CLAIM_EXCEEDS_INDEMNITY`, `ERR_SALVAGE_EXCEEDS_RECOVERABLE`, `ERR_CARBON_NO_DEDICATIONS`, and `ERR_BUFFER_CURE_INSUFFICIENT` (all 422)."

        Design: Difficulty/priority_pair_validation_conflict/stand_not_inventoried_at_55_beats_insufficient_tons_at_80
        """
        ctx = open_cruise_stand(api)
        for plot in CANONICAL_CRUISE_PLOTS:
            record_cruise_plot(api, ctx.stand_id, **plot)
        _attempt_reservation(api, ctx.stand_id)

        close_cruise(api, ctx.stand_id)
        response = _attempt_reservation(api, ctx.stand_id)

        validate_error(response, ApiErrorId.INSUFFICIENT_AVAILABLE_TONS.value, 422)

    def test_neither_refusal_leaves_a_block_or_moves_the_inventory(self, api):
        """The stand keeps its whole pool and no block was ever filed.

        PRD: "Finally, `planned_tons` must be no greater than the stand's `available_tons`, with equality permitted; an over-reservation is refused with `ERR_INSUFFICIENT_AVAILABLE_TONS`."

        Design: Difficulty/priority_pair_validation_conflict/stand_not_inventoried_at_55_beats_insufficient_tons_at_80
        """
        ctx = open_cruise_stand(api)
        for plot in CANONICAL_CRUISE_PLOTS:
            record_cruise_plot(api, ctx.stand_id, **plot)
        _attempt_reservation(api, ctx.stand_id)
        close_cruise(api, ctx.stand_id)
        _attempt_reservation(api, ctx.stand_id)

        assert_stand_partition(
            read_stand(api, ctx.stand_id),
            net_merch_tons=4647.12,
            reserved_tons=0.00,
            available_tons=4647.12,
        )
        blocks, meta = validate_paginated(
            api.list_stand_harvest_blocks(ctx.stand_id, make_forest_manager_headers())
        )
        assert blocks == [], "no harvest block survived either refusal"
        assert_pagination_meta(meta, total_count=0)


class TestSafetyGateOutranksTheTemporalConflict:
    """A suspended tract is reported before the hunting blackout is consulted."""

    def _suspended_tract_with_a_blacked_out_block(self, api):
        ctx = owned_tract(api)
        block = reserve_block(api, ctx.stand_id, planned_tons=1000.00)
        lease = create_lease(api, ctx.property_id)
        activate_lease(api, lease["id"])
        audit = schedule_audit(api, ctx.property_id)
        advance_audit(api, audit["id"], "START_FIELD_WORK")
        first = raise_finding(
            api,
            audit["id"],
            severity="MAJOR",
            finding_code="SFI-4.1",
            indicator_ref="4.1.2",
        )
        raise_finding(
            api,
            audit["id"],
            severity="MAJOR",
            finding_code="SFI-6.3",
            indicator_ref="6.3.1",
        )
        advance_audit(api, audit["id"], "ISSUE_FINDINGS")
        return ctx, block, audit, first

    def test_the_suspension_is_reported_ahead_of_the_blackout_collision(self, api):
        """The commit fails on certification even though the window is also blacked out.

        PRD: "The property's `certification_posture` must not be `SUSPENDED`, or the commit is refused with `ERR_CERTIFICATION_SUSPENDED`"

        Design: Difficulty/priority_pair_validation_conflict/certification_suspended_at_60_beats_lease_blackout_at_64
        """
        ctx, block, _, _ = self._suspended_tract_with_a_blacked_out_block(api)
        assert read_property(api, ctx.property_id)["certification_posture"] == "SUSPENDED"

        response = api.commit_harvest_block(
            block["id"], None, make_forest_manager_headers()
        )

        validate_error(response, ApiErrorId.CERTIFICATION_SUSPENDED.value, 409)

    def test_clearing_the_suspension_exposes_the_blackout_collision(self, api):
        """Closing one major returns the posture to conditional and the blackout surfaces.

        PRD: "The harvest re-entry buffer (`ERR_REENTRY_BUFFER_CONFLICT`, 409) and the lease blackout collision (`ERR_LEASE_BLACKOUT_CONFLICT`, 409)."

        Design: Difficulty/priority_pair_validation_conflict/certification_suspended_at_60_beats_lease_blackout_at_64
        """
        ctx, block, audit, first = self._suspended_tract_with_a_blacked_out_block(api)
        api.commit_harvest_block(block["id"], None, make_forest_manager_headers())

        submit_car(api, first["id"], manager="fm-1")
        closed = verify_close_car(api, first["id"], auditor="ca-1")
        assert closed["status"] == "CLOSED"
        assert read_audit(api, audit["id"])["open_major_count"] == 1
        assert (
            read_property(api, ctx.property_id)["certification_posture"] == "CONDITIONAL"
        )

        response = api.commit_harvest_block(
            block["id"], None, make_forest_manager_headers()
        )

        validate_error(response, ApiErrorId.LEASE_BLACKOUT_CONFLICT.value, 409)

    def test_neither_refused_commit_moves_the_reserved_tonnage(self, api):
        """The block is still reserved and the stand's buckets are untouched.

        PRD: "Certification suspension (`ERR_CERTIFICATION_SUSPENDED`, 409) and the cash-yield cancellation lock (`ERR_YIELD_SHORTFALL_LOCK`, 409)."

        Design: Difficulty/priority_pair_validation_conflict/certification_suspended_at_60_beats_lease_blackout_at_64
        """
        ctx, block, _, first = self._suspended_tract_with_a_blacked_out_block(api)
        api.commit_harvest_block(block["id"], None, make_forest_manager_headers())
        submit_car(api, first["id"], manager="fm-1")
        verify_close_car(api, first["id"], auditor="ca-1")
        api.commit_harvest_block(block["id"], None, make_forest_manager_headers())

        assert read_block(api, block["id"])["status"] == "RESERVED"
        assert_stand_partition(
            read_stand(api, ctx.stand_id),
            reserved_tons=1000.00,
            committed_tons=0.00,
            available_tons=3647.12,
        )


class TestReferentialCheckOutranksTheTonnageCheck:
    """A stand on the wrong tract is reported before its headroom is examined."""

    def _two_tracts_and_a_project(self, api):
        ctx = owned_tract(api)
        neighbour = create_property(api, ctx.fund_id, **BEAR_HOLLOW_PROPERTY)
        foreign_stand = create_stand(api, neighbour["id"], **BEAR_HOLLOW_STAND)
        record_cruise_plot(api, foreign_stand["id"], **SINGLE_PLOT)
        foreign_stand = close_cruise(api, foreign_stand["id"])
        project = create_carbon_project(api, ctx.property_id)
        return ctx, foreign_stand, project

    def test_a_stand_on_another_tract_is_reported_ahead_of_the_tonnage_check(self, api):
        """The pledge fails on ownership agreement, not on available tons.

        PRD: "The stand must belong to the project's own property, or the dedication is refused with `ERR_STAND_PROPERTY_MISMATCH`."

        Design: Difficulty/priority_pair_validation_conflict/stand_property_mismatch_at_70_beats_insufficient_tons_at_80
        """
        ctx, foreign_stand, project = self._two_tracts_and_a_project(api)
        assert_tons(foreign_stand["net_merch_tons"], 4270.38, "net_merch_tons")
        assert foreign_stand["cruise_confidence"] == "LOW"

        response = _attempt_dedication(api, project["id"], foreign_stand["id"])

        validate_error(response, ApiErrorId.STAND_PROPERTY_MISMATCH.value, 422)

    def test_the_project_s_own_stand_falls_through_to_the_tonnage_check(self, api):
        """On the matching tract the same oversized pledge fails on available tons.

        PRD: "And `dedicated_tons` must be no greater than the stand's `available_tons`, equality permitted, or it is refused with `ERR_INSUFFICIENT_AVAILABLE_TONS` — the same ceiling a harvest reservation faces, drawn against the same pool."

        Design: Difficulty/priority_pair_validation_conflict/stand_property_mismatch_at_70_beats_insufficient_tons_at_80
        """
        ctx, foreign_stand, project = self._two_tracts_and_a_project(api)
        _attempt_dedication(api, project["id"], foreign_stand["id"])

        response = _attempt_dedication(api, project["id"], ctx.stand_id)

        validate_error(response, ApiErrorId.INSUFFICIENT_AVAILABLE_TONS.value, 422)

    def test_neither_refusal_pledges_a_single_ton(self, api):
        """Both stands keep their whole pool and the project total remains empty.

        PRD: "`dedicated_tons_total` is at all times the sum, over the project's dedications in `PENDING`, `ACTIVE` or `REDUCED`, of each dedication's `dedicated_tons` less its `reduced_tons`, rounded half-up to two decimals."

        Design: Difficulty/priority_pair_validation_conflict/stand_property_mismatch_at_70_beats_insufficient_tons_at_80
        """
        ctx, foreign_stand, project = self._two_tracts_and_a_project(api)
        _attempt_dedication(api, project["id"], foreign_stand["id"])
        _attempt_dedication(api, project["id"], ctx.stand_id)

        assert_stand_partition(
            read_stand(api, foreign_stand["id"]),
            dedicated_tons=0.00,
            available_tons=4270.38,
        )
        assert_stand_partition(
            read_stand(api, ctx.stand_id),
            dedicated_tons=0.00,
            available_tons=4647.12,
        )
        after = read_carbon_project(api, project["id"])
        assert_tons(after["dedicated_tons_total"], 0.00, "dedicated_tons_total")
        assert after["status"] == "DRAFT"
