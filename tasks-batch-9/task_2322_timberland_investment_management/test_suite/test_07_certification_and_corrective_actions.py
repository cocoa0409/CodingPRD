"""Certification: the corrective-action review cycle, the posture threshold and the suspension cascade."""

from test_helpers import (
    assert_fund_cash,
    assert_property_dimensions,
    assert_stand_partition,
    assert_tons,
)
from test_helpers.fixtures import (
    advance_audit,
    commit_block,
    owned_tract,
    raise_finding,
    read_audit,
    read_block,
    read_finding,
    read_fund,
    read_property,
    read_stand,
    reject_car,
    reserve_block,
    schedule_audit,
    submit_car,
    verify_close_car,
)


def _audit_in_field_work(api, property_id, auditor="ca-1"):
    audit = schedule_audit(api, property_id, auditor)
    return advance_audit(api, audit["id"], "START_FIELD_WORK", auditor)


class TestCorrectiveActionReviewCycle:
    """A rejected corrective action revisits the same pair of states before closing conforming."""

    def test_a_rejected_corrective_action_returns_the_finding_and_the_audit(self, api):
        """Rejection reopens the finding, counts the rejection and drags the audit back.

        PRD: "Rejecting it requires the finding to be in `CAR_SUBMITTED`, returns the finding to `OPEN`, increments its `rejection_count` by one, and drags the parent audit back from `CAR_REVIEW` to `FINDINGS_ISSUED`."

        Design: Difficulty/non_linear_state_machine/audit_findings_car_review_cycle_then_closes_conforming
        """
        ctx = owned_tract(api)
        audit = _audit_in_field_work(api, ctx.property_id)
        finding = raise_finding(api, audit["id"], severity="MINOR", finding_code="SFI-2.1")
        advance_audit(api, audit["id"], "ISSUE_FINDINGS")

        submit_car(api, finding["id"], manager="fm-1")
        assert read_audit(api, audit["id"])["status"] == "CAR_REVIEW"

        rejected = reject_car(api, finding["id"], auditor="ca-1")

        assert rejected["status"] == "OPEN"
        assert rejected["rejection_count"] == 1
        assert read_audit(api, audit["id"])["status"] == "FINDINGS_ISSUED"

    def test_the_resubmitted_corrective_action_is_verified_and_closed(self, api):
        """The second submission bubbles the audit back to review and then closes the finding.

        PRD: "Verifying and closing moves the finding from `CAR_SUBMITTED` to the terminal `CLOSED`, requires the caller's `X-User-ID` to differ from `car_submitted_by_user_id` (§2.10), stamps `closed_by_user_id` with the caller's `X-User-ID`, and recomputes the audit's open counts and then the property's posture"

        Design: Difficulty/non_linear_state_machine/audit_findings_car_review_cycle_then_closes_conforming
        """
        ctx = owned_tract(api)
        audit = _audit_in_field_work(api, ctx.property_id)
        finding = raise_finding(api, audit["id"], severity="MINOR", finding_code="SFI-2.1")
        advance_audit(api, audit["id"], "ISSUE_FINDINGS")

        submit_car(api, finding["id"], manager="fm-1")
        reject_car(api, finding["id"], auditor="ca-1")
        submit_car(api, finding["id"], manager="fm-1")

        closed = verify_close_car(api, finding["id"], auditor="ca-2")

        assert closed["status"] == "CLOSED"
        assert closed["rejection_count"] == 1
        assert closed["car_submitted_by_user_id"] == "fm-1"
        assert closed["closed_by_user_id"] == "ca-2"

    def test_the_audit_closes_conforming_and_the_tract_reads_certified_again(self, api):
        """With no open finding left the audit reaches its terminal state and the posture recovers.

        PRD: "Closure moves the audit to the terminal `CLOSED_CONFORMING` and is reachable from `FINDINGS_ISSUED` and from `CAR_REVIEW`; both branches require `open_major_count` and `open_minor_count` to be exactly zero"

        Design: Difficulty/non_linear_state_machine/audit_findings_car_review_cycle_then_closes_conforming
        """
        ctx = owned_tract(api)
        audit = _audit_in_field_work(api, ctx.property_id)
        finding = raise_finding(api, audit["id"], severity="MINOR", finding_code="SFI-2.1")
        advance_audit(api, audit["id"], "ISSUE_FINDINGS")
        submit_car(api, finding["id"], manager="fm-1")
        reject_car(api, finding["id"], auditor="ca-1")
        submit_car(api, finding["id"], manager="fm-1")
        verify_close_car(api, finding["id"], auditor="ca-2")

        advance_audit(api, audit["id"], "CLOSE", auditor="ca-2")

        closed_audit = read_audit(api, audit["id"])
        assert closed_audit["status"] == "CLOSED_CONFORMING"
        assert closed_audit["open_minor_count"] == 0
        assert closed_audit["major_finding_count"] == 0
        assert_property_dimensions(
            read_property(api, ctx.property_id),
            status="OWNED",
            certification_posture="CERTIFIED",
        )
        assert_fund_cash(read_fund(api, ctx.fund_id), cash_balance_usd=300000.00)


class TestOpenMajorPostureThreshold:
    """One open major is a conditional posture; the second one suspends the tract."""

    def test_the_first_open_major_only_makes_the_tract_conditional(self, api):
        """A single open major finding does not reach the suspension threshold.

        PRD: "otherwise, if the open major count is exactly one or the open minor count is at least one, the posture is `CONDITIONAL`; otherwise the posture is `CERTIFIED`"

        Design: Difficulty/boundary_precision_check/open_major_finding_threshold_one_conditional_two_suspended
        """
        ctx = owned_tract(api)
        assert_property_dimensions(
            read_property(api, ctx.property_id), certification_posture="CERTIFIED"
        )
        audit = _audit_in_field_work(api, ctx.property_id)

        raise_finding(
            api,
            audit["id"],
            severity="MAJOR",
            finding_code="SFI-4.1",
            indicator_ref="4.1.2",
        )

        assert_property_dimensions(
            read_property(api, ctx.property_id),
            status="OWNED",
            certification_posture="CONDITIONAL",
        )
        assert read_audit(api, audit["id"])["status"] == "FIELD_WORK"

    def test_the_second_open_major_carries_the_tract_to_suspended(self, api):
        """Crossing to two open majors flips the posture to suspended.

        PRD: "otherwise, if the open major count is at least two, the posture is `SUSPENDED` — the threshold is two, not one"

        Design: Difficulty/boundary_precision_check/open_major_finding_threshold_one_conditional_two_suspended
        """
        ctx = owned_tract(api)
        audit = _audit_in_field_work(api, ctx.property_id)
        first = raise_finding(
            api, audit["id"], severity="MAJOR", finding_code="SFI-4.1", indicator_ref="4.1.2"
        )

        second = raise_finding(
            api, audit["id"], severity="MAJOR", finding_code="SFI-6.3", indicator_ref="6.3.1"
        )

        assert_property_dimensions(
            read_property(api, ctx.property_id), certification_posture="SUSPENDED"
        )
        counted = read_audit(api, audit["id"])
        assert counted["open_major_count"] == 2
        assert counted["open_minor_count"] == 0
        assert read_finding(api, first["id"])["status"] == "OPEN"
        assert read_finding(api, second["id"])["status"] == "OPEN"


class TestSuspensionCascadesToCommittedBlocks:
    """Suspension unwinds commitments without cutting any planned tonnage."""

    def test_the_second_open_major_reverts_the_committed_block_to_reserved(self, api):
        """The committed 1000.00 tons move back out of committed and into reserved.

        PRD: "every harvest block on the property's stands whose `status` is `COMMITTED` reverts to `RESERVED`, with its `planned_tons` moving from the stand's `committed_tons` back to `reserved_tons`"

        Design: Difficulty/transitive_cascade/certification_suspension_cascades_committed_blocks_back_to_reserved
        """
        ctx = owned_tract(api)
        block = reserve_block(api, ctx.stand_id, planned_tons=1000.00)
        commit_block(api, block["id"])
        assert_stand_partition(
            read_stand(api, ctx.stand_id),
            committed_tons=1000.00,
            reserved_tons=0.00,
            available_tons=3647.12,
        )
        audit = _audit_in_field_work(api, ctx.property_id)
        raise_finding(
            api, audit["id"], severity="MAJOR", finding_code="SFI-4.1", indicator_ref="4.1.2"
        )

        raise_finding(
            api, audit["id"], severity="MAJOR", finding_code="SFI-6.3", indicator_ref="6.3.1"
        )

        reverted = read_block(api, block["id"])
        assert reverted["status"] == "RESERVED"
        assert_tons(reverted["planned_tons"], 1000.00, "planned_tons")
        assert_property_dimensions(
            read_property(api, ctx.property_id), certification_posture="SUSPENDED"
        )

    def test_the_revert_leaves_available_tons_and_the_plan_flag_alone(self, api):
        """No tonnage was cut, so headroom and the planning flag are exactly as before.

        PRD: "`available_tons` and `planned_tons` are untouched by that revert, and so is the property's `harvest_plan_status` — a suspension does not create a replanning obligation, it only unwinds commitments."

        Design: Difficulty/transitive_cascade/certification_suspension_cascades_committed_blocks_back_to_reserved
        """
        ctx = owned_tract(api)
        block = reserve_block(api, ctx.stand_id, planned_tons=1000.00)
        commit_block(api, block["id"])
        audit = _audit_in_field_work(api, ctx.property_id)
        raise_finding(
            api, audit["id"], severity="MAJOR", finding_code="SFI-4.1", indicator_ref="4.1.2"
        )

        raise_finding(
            api, audit["id"], severity="MAJOR", finding_code="SFI-6.3", indicator_ref="6.3.1"
        )

        assert_stand_partition(
            read_stand(api, ctx.stand_id),
            net_merch_tons=4647.12,
            reserved_tons=1000.00,
            committed_tons=0.00,
            available_tons=3647.12,
        )
        assert_property_dimensions(
            read_property(api, ctx.property_id), harvest_plan_status="ALIGNED"
        )

    def test_the_audit_counts_every_major_finding_in_any_status(self, api):
        """Both majors are counted, so the audit reports two of each.

        PRD: "`major_finding_count` counts the audit's findings whose `severity` is `MAJOR`, in any status."

        Design: Difficulty/transitive_cascade/certification_suspension_cascades_committed_blocks_back_to_reserved
        """
        ctx = owned_tract(api)
        block = reserve_block(api, ctx.stand_id, planned_tons=1000.00)
        commit_block(api, block["id"])
        audit = _audit_in_field_work(api, ctx.property_id)
        raise_finding(
            api, audit["id"], severity="MAJOR", finding_code="SFI-4.1", indicator_ref="4.1.2"
        )

        raise_finding(
            api, audit["id"], severity="MAJOR", finding_code="SFI-6.3", indicator_ref="6.3.1"
        )

        counted = read_audit(api, audit["id"])
        assert counted["major_finding_count"] == 2
        assert counted["open_major_count"] == 2
