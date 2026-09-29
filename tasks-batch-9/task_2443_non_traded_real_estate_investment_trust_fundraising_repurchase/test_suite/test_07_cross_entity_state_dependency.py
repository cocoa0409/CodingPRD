"""Rules whose legality lives on a *different* row than the one being written.

Two of them are pinned here. A subscription's move to ``ACCEPTED`` is legal only
when the share class it names carries its own ``PUBLISHED`` valuation, so a
sibling class's published record unlocks nothing (PRD §3.5). And whether a tender
may be filed at all is decided by the grandparent offering's repurchase-plan
axis, not by the period the tender names (PRD §3.8).
"""

from __future__ import annotations

from typing import Any, Dict

from test_helpers import (
    ADVISOR,
    COMPLIANCE,
    SPONSOR,
    TRANSFER_AGENT,
    ApiErrorId,
    assert_created,
    assert_error,
    assert_fields,
    assert_ok,
    make_investor_user_headers,
    nav_record_payload,
    repurchase_request_payload,
)
from test_helpers.fixtures import ReitWorld

ZERO_LOAD = {
    "upfront_selling_commission_bps": 0,
    "dealer_manager_fee_bps": 0,
    "annual_distribution_fee_bps": 0,
    "distribution_fee_cap_bps": 0,
}


# ─── Ironwood: two classes, only class I priced ───────────────────────


def _ironwood(world: ReitWorld) -> Dict[str, Any]:
    """Two zero-load classes funded through an escrow break, class I priced.

    Class I holds 300,000,000 e4 and class T 5,000,000 e4 after the break; the
    August valuation is published for class I alone, and a further 500,000-cent
    class T subscription is left ``PENDING`` for the acceptance under test.
    """
    off = world.offering(
        name="Ironwood Balanced REIT",
        minimum_offering_amount_cents=30000000,
        maximum_offering_amount_cents=50000000000,
        escrow_deadline_date="2026-12-31",
        initial_offering_price_cents=1000,
        rescission_window_days=5,
    )
    sc_i = world.share_class(off["id"], class_code="I", **ZERO_LOAD)
    sc_t = world.share_class(off["id"], class_code="T", **ZERO_LOAD)
    firm = world.broker_dealer(
        firm_name="Ironwood Selling Group", crd_number="CRD-140001"
    )
    agreement = world.selling_agreement(
        off["id"],
        firm["id"],
        max_commission_bps=100,
        suitability_documentation_required=True,
    )
    world.declare_effective(off["id"])
    world.activate_agreement(agreement["id"])

    anchor = world.investor(
        legal_name="Grove Institutional Trust",
        email="grove.trust@example.com",
        state_code="TX",
        net_worth_cents=5000000000,
        annual_income_cents=1000000000,
    )
    world.document_suitability(anchor["id"], "SUIT-GROVE-2026-08")
    tomas = world.investor(
        legal_name="Tomas Alderete",
        email="tomas.alderete@example.com",
        state_code="TX",
        net_worth_cents=500000000,
        annual_income_cents=100000000,
    )
    world.document_suitability(tomas["id"], "SUIT-T-2026-08")

    sub_i = world.subscription(off["id"], sc_i["id"], anchor["id"], agreement["id"], 30000000)
    world.escrow_subscription(sub_i["id"])
    sub_t1 = world.subscription(off["id"], sc_t["id"], tomas["id"], agreement["id"], 500000)
    world.escrow_subscription(sub_t1["id"])
    world.break_escrow(off["id"])

    world.set_clock("2026-09-02T00:00:00Z", SPONSOR)
    world.published_nav(
        sc_i["id"], "2026-08-01", "2026-08-31", 30000000, 0, "IVA-2026-08-IW-I"
    )

    sub_t2 = world.subscription(off["id"], sc_t["id"], anchor["id"], agreement["id"], 500000)
    return {
        "offering_id": off["id"],
        "share_class_i_id": sc_i["id"],
        "share_class_t_id": sc_t["id"],
        "anchor_id": anchor["id"],
        "pending_class_t_subscription_id": sub_t2["id"],
    }


def _publish_class_t_august_valuation(world: ReitWorld, share_class_t_id: str) -> Dict[str, Any]:
    """Walk the class T August record all the way to ``PUBLISHED``."""
    version = world.share_class_version(share_class_t_id)
    record = assert_created(
        world.api.create_nav_record(
            nav_record_payload(
                share_class_t_id,
                version,
                period_start_date="2026-08-01",
                period_end_date="2026-08-31",
                gross_asset_value_cents=500000,
                other_liabilities_cents=0,
            ),
            SPONSOR,
        )
    )
    assert_ok(
        world.api.set_nav_record_status(record["id"], {"to_status": "ADVISOR_REVIEW"}, SPONSOR)
    )
    assert_ok(
        world.api.set_nav_record_status(
            record["id"],
            {"to_status": "ADVISOR_CONFIRMED", "advisor_opinion_reference": "IVA-2026-08-IW-T"},
            ADVISOR,
        )
    )
    return assert_ok(
        world.api.set_nav_record_status(record["id"], {"to_status": "PUBLISHED"}, SPONSOR)
    )


class TestAcceptanceRequiresPublishedNavForItsOwnClass:
    """PRD §3.5's ``ERR_NO_PUBLISHED_NAV`` gate is scoped to the tendered class."""

    def test_acceptance_refused_while_only_the_sibling_class_is_priced(self, api, world):
        """A class T acceptance is refused although class I already publishes a valuation.

        PRD §3.5: "Four preconditions apply: `escrow_status` must be `BROKEN`,
        `registration_status` must be `EFFECTIVE` — otherwise
        `ERR_OFFERING_NOT_EFFECTIVE` — a `PUBLISHED` valuation record must exist
        for the target share class — without one the acceptance is refused with
        `ERR_NO_PUBLISHED_NAV` — and the offering's `gross_proceeds_cents` plus
        the subscription's `gross_investment_cents` must not exceed
        `maximum_offering_amount_cents`, or the acceptance reports
        `ERR_OFFERING_MAXIMUM_EXCEEDED`."

        Design: Difficulty/cross_entity_state_dependency/subscription_acceptance_requires_published_nav_for_its_own_class
        """
        scene = _ironwood(world)

        response = api.set_subscription_status(
            scene["pending_class_t_subscription_id"], {"to_status": "ACCEPTED"}, SPONSOR
        )

        assert_error(response, ApiErrorId.NO_PUBLISHED_NAV, 409)

    def test_class_t_valuation_snapshots_only_its_own_outstanding_shares(self, world):
        """The class T record prices 500,000 cents over class T's own 5,000,000 e4.

        PRD §3.6: "The record snapshots `shares_outstanding_e4_snapshot` from the
        class's `shares_outstanding_e4` at the instant of creation, and computes
        `accrued_distribution_payable_cents` as the sum of `total_declared_cents`
        across every declaration of the class's offering that is currently
        `DECLARED` and whose `record_date` falls on or before this record's
        `period_end_date`."
        PRD §3.6: "Otherwise `nav_per_share_pre_accrual_cents` is the pre-accrual
        net assets multiplied by 10,000, divided by the snapshotted share count
        and rounded half up to a whole cent, while `nav_per_share_cents` is the
        post-accrual net assets multiplied by 10,000, divided by the same
        snapshotted share count and rounded half up."

        Design: Difficulty/cross_entity_state_dependency/subscription_acceptance_requires_published_nav_for_its_own_class
        """
        scene = _ironwood(world)

        published = _publish_class_t_august_valuation(world, scene["share_class_t_id"])

        assert_fields(
            published,
            shares_outstanding_e4_snapshot=5000000,
            accrued_distribution_payable_cents=0,
            nav_per_share_cents=1000,
            nav_per_share_pre_accrual_cents=1000,
            status="PUBLISHED",
        )

    def test_acceptance_after_own_class_is_priced_uses_the_price_pinned_at_authoring(
        self, api, world
    ):
        """Publishing class T unlocks the identical acceptance at its authored price of 1000.

        PRD §3.4: "If there are none, the price is the offering's
        `initial_offering_price_cents`."
        PRD §3.4: "`shares_issued_e4` is the net invested amount multiplied by
        10,000 and divided by the pinned transaction price, floored to a whole
        share unit — a stockholder is never issued a fraction of a
        ten-thousandth of a share."

        Design: Difficulty/cross_entity_state_dependency/subscription_acceptance_requires_published_nav_for_its_own_class
        """
        scene = _ironwood(world)
        assert_error(
            api.set_subscription_status(
                scene["pending_class_t_subscription_id"], {"to_status": "ACCEPTED"}, SPONSOR
            ),
            ApiErrorId.NO_PUBLISHED_NAV,
            409,
        )
        _publish_class_t_august_valuation(world, scene["share_class_t_id"])

        accepted = assert_ok(
            api.set_subscription_status(
                scene["pending_class_t_subscription_id"], {"to_status": "ACCEPTED"}, SPONSOR
            )
        )

        assert_fields(
            accepted,
            status="ACCEPTED",
            transaction_price_cents=1000,
            shares_issued_e4=5000000,
            unapplied_cash_cents=0,
        )

    def test_acceptance_recomputes_only_the_tendered_class_and_the_offering_totals(
        self, api, world
    ):
        """Class T rises to 10,000,000 e4 while class I stays at 300,000,000 e4.

        PRD §3.5: "Acceptance also adds `gross_investment_cents` to the
        offering's `gross_proceeds_cents` and to the stockholder's
        `cumulative_invested_cents`; recomputes the class's
        `shares_outstanding_e4`, the stockholder's `total_shares_e4` and the
        offering's `aggregate_nav_cents`; sets `suitability_status` to `FLAGGED`
        when `cumulative_invested_cents` now exceeds `concentration_limit_cents`;
        and returns `account_status` to `ACTIVE` if the stockholder had been
        sitting at `CLOSED_NO_POSITION`."
        PRD §3.6: "`aggregate_nav_cents` is the sum, taken over every share class
        of the offering, of each class's transaction price multiplied by that
        class's `shares_outstanding_e4`, divided by 10,000 and rounded half up —
        each class's contribution rounded to a whole cent on its own before the
        contributions are added."

        Design: Difficulty/cross_entity_state_dependency/subscription_acceptance_requires_published_nav_for_its_own_class
        """
        scene = _ironwood(world)
        _publish_class_t_august_valuation(world, scene["share_class_t_id"])
        assert_ok(
            api.set_subscription_status(
                scene["pending_class_t_subscription_id"], {"to_status": "ACCEPTED"}, SPONSOR
            )
        )

        assert_fields(
            world.read_share_class(scene["share_class_t_id"]), shares_outstanding_e4=10000000
        )
        assert_fields(
            world.read_share_class(scene["share_class_i_id"]),
            shares_outstanding_e4=300000000,
        )
        assert_fields(
            world.read_offering(scene["offering_id"]),
            gross_proceeds_cents=31000000,
            aggregate_nav_cents=31000000,
        )
        assert_fields(world.read_investor(scene["anchor_id"]), total_shares_e4=305000000)


# ─── Fairhaven: the plan axis gates the tender ────────────────────────


def _fairhaven_with_queued_tender(world: ReitWorld) -> Dict[str, Any]:
    """A priced offering with an open September period and one queued tender.

    The anchor holding funds the break; Dana Pike's 300,050-cent ticket leaves
    her 3,000,500 e4, of which 1,000,000 e4 is tendered while the clock sits at
    2026-09-05, inside the window ``[2026-09-03, 2026-09-25)``.
    """
    off = world.offering(
        name="Fairhaven Growth REIT",
        minimum_offering_amount_cents=30000000,
        maximum_offering_amount_cents=50000000000,
        escrow_deadline_date="2026-12-31",
        initial_offering_price_cents=1000,
        rescission_window_days=5,
    )
    sc_i = world.share_class(off["id"], class_code="I", **ZERO_LOAD)
    firm = world.broker_dealer(
        firm_name="Fairhaven Distributors LLC", crd_number="CRD-800001"
    )
    agreement = world.selling_agreement(
        off["id"],
        firm["id"],
        max_commission_bps=100,
        suitability_documentation_required=True,
    )
    world.declare_effective(off["id"])
    world.activate_agreement(agreement["id"])

    anchor = world.investor(
        legal_name="Grove Institutional Trust",
        email="grove.trust@example.com",
        state_code="TX",
        net_worth_cents=5000000000,
        annual_income_cents=1000000000,
    )
    world.document_suitability(anchor["id"], "SUIT-GROVE-2026-08")
    dana = world.investor(
        legal_name="Dana Pike",
        email="dana.pike@example.com",
        state_code="TX",
        net_worth_cents=100000000,
        annual_income_cents=40000000,
    )
    world.document_suitability(dana["id"], "SUIT-D-2026-08")

    sub_anchor = world.subscription(
        off["id"], sc_i["id"], anchor["id"], agreement["id"], 30000000
    )
    world.escrow_subscription(sub_anchor["id"])
    sub_dana = world.subscription(off["id"], sc_i["id"], dana["id"], agreement["id"], 300050)
    world.escrow_subscription(sub_dana["id"])
    world.break_escrow(off["id"])

    world.set_clock("2026-09-02T00:00:00Z", SPONSOR)
    world.published_nav(
        sc_i["id"], "2026-08-01", "2026-08-31", 31200050, 900000, "IVA-2026-08-FH"
    )

    period = world.repurchase_period(
        off["id"],
        period_month="2026-09",
        opens_at="2026-09-03T00:00:00Z",
        request_cutoff_at="2026-09-25T00:00:00Z",
        settlement_date="2026-09-30",
    )
    world.set_clock("2026-09-05T00:00:00Z", TRANSFER_AGENT)
    first = world.tender(period["id"], sc_i["id"], 1000000, dana["id"], hardship_type="NONE")
    return {
        "offering_id": off["id"],
        "share_class_i_id": sc_i["id"],
        "dana_id": dana["id"],
        "period_id": period["id"],
        "first_request_id": first["id"],
    }


class TestTenderGatedByOfferingRepurchasePlanAxis:
    """PRD §3.8: the grandparent offering's plan axis decides tender legality."""

    def test_suspending_the_plan_freezes_the_period_and_its_queued_tender(self, api, world):
        """A compliance suspension drives the OPEN period to SUSPENDED and the tender to HELD.

        PRD §3.8: "`SUSPEND` moves `repurchase_plan_status` from `ACTIVE` to
        `SUSPENDED`, increments the offering's `version`, records the supplied
        text in `repurchase_plan_suspension_reason`, drives every `OPEN`
        repurchase period of the offering to `SUSPENDED`, and drives every
        `QUEUED` tender inside those periods to `HELD`, where it is excluded from
        any allocation."

        Design: Difficulty/cross_entity_state_dependency/repurchase_request_gated_by_offering_repurchase_plan_axis
        """
        scene = _fairhaven_with_queued_tender(world)

        assert_ok(
            api.drive_repurchase_plan(
                scene["offering_id"], {"action": "SUSPEND", "reason": "SEC_INQUIRY"}, COMPLIANCE
            )
        )

        assert_fields(
            world.read_offering(scene["offering_id"]),
            repurchase_plan_status="SUSPENDED",
            repurchase_plan_suspension_reason="SEC_INQUIRY",
        )
        assert_fields(world.read_period(scene["period_id"]), status="SUSPENDED")
        assert_fields(world.read_request(scene["first_request_id"]), status="HELD")

    def test_new_tender_refused_while_the_plan_is_suspended(self, api, world):
        """A fresh tender inside a live window still fails on the grandparent's plan axis.

        PRD §3.8: "While the plan is `SUSPENDED` or `TERMINATED`, opening a
        period, filing a tender and processing a period all fail with
        `ERR_REPURCHASE_PLAN_SUSPENDED`."

        Design: Difficulty/cross_entity_state_dependency/repurchase_request_gated_by_offering_repurchase_plan_axis
        """
        scene = _fairhaven_with_queued_tender(world)
        assert_ok(
            api.drive_repurchase_plan(
                scene["offering_id"], {"action": "SUSPEND", "reason": "SEC_INQUIRY"}, COMPLIANCE
            )
        )

        response = api.create_repurchase_request(
            repurchase_request_payload(
                scene["period_id"], scene["share_class_i_id"], 500000, hardship_type="NONE"
            ),
            make_investor_user_headers(scene["dana_id"]),
        )

        assert_error(response, ApiErrorId.REPURCHASE_PLAN_SUSPENDED, 409)

    def test_resume_restores_the_plan_the_period_and_the_held_tender(self, api, world):
        """RESUME clears the reason, reopens the period and requeues the frozen tender.

        PRD §3.8: "`RESUME` reverses all of that — it returns `SUSPENDED` to
        `ACTIVE`, increments `version`, clears
        `repurchase_plan_suspension_reason`, returns every `SUSPENDED` period of
        the offering to `OPEN` and every `HELD` tender in those periods to
        `QUEUED` — but it is permitted only while the offering's `escrow_status`
        is `BROKEN`."

        Design: Difficulty/cross_entity_state_dependency/repurchase_request_gated_by_offering_repurchase_plan_axis
        """
        scene = _fairhaven_with_queued_tender(world)
        assert_ok(
            api.drive_repurchase_plan(
                scene["offering_id"], {"action": "SUSPEND", "reason": "SEC_INQUIRY"}, COMPLIANCE
            )
        )

        assert_ok(
            api.drive_repurchase_plan(scene["offering_id"], {"action": "RESUME"}, COMPLIANCE)
        )

        assert_fields(
            world.read_offering(scene["offering_id"]),
            repurchase_plan_status="ACTIVE",
            repurchase_plan_suspension_reason=None,
        )
        assert_fields(world.read_period(scene["period_id"]), status="OPEN")
        assert_fields(world.read_request(scene["first_request_id"]), status="QUEUED")

    def test_tender_accepted_again_once_the_plan_is_active(self, api, world):
        """After RESUME the same 500,000 e4 tender is queued, and holdings are untouched.

        PRD §3.8: "A filed tender sits in `QUEUED` with `requested_value_cents`,
        `approved_value_cents`, `approved_shares_e4`,
        `early_repurchase_deduction_cents` and `net_proceeds_cents` all at zero
        until the period is processed."

        Design: Difficulty/cross_entity_state_dependency/repurchase_request_gated_by_offering_repurchase_plan_axis
        """
        scene = _fairhaven_with_queued_tender(world)
        assert_ok(
            api.drive_repurchase_plan(
                scene["offering_id"], {"action": "SUSPEND", "reason": "SEC_INQUIRY"}, COMPLIANCE
            )
        )
        assert_ok(
            api.drive_repurchase_plan(scene["offering_id"], {"action": "RESUME"}, COMPLIANCE)
        )

        second = assert_created(
            api.create_repurchase_request(
                repurchase_request_payload(
                    scene["period_id"], scene["share_class_i_id"], 500000, hardship_type="NONE"
                ),
                make_investor_user_headers(scene["dana_id"]),
            )
        )

        assert_fields(
            second,
            status="QUEUED",
            shares_requested_e4=500000,
            requested_value_cents=0,
            approved_value_cents=0,
            approved_shares_e4=0,
            early_repurchase_deduction_cents=0,
            net_proceeds_cents=0,
        )
        assert_fields(world.read_request(scene["first_request_id"]), status="QUEUED")
        assert_fields(world.read_investor(scene["dana_id"]), total_shares_e4=3000500)
