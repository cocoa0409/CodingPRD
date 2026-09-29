"""The three compensating cascades, each proved by re-consuming what the void gave back.

A void is only correct if the released quantity is usable again, so none of these tests stops
at reading the ledger: the restored budget headroom is spent down to exactly zero, the
restored crew day is re-dispatched onto the same saturated date, and the released home is
re-reserved by a second applicant whose lease must not see the voided row.
"""

from prd_bench_local_runner.testing import get_success_data

from test_helpers import factories as f
from test_helpers import fixtures as x
from test_helpers.api_errors import ERR_PROJECT_BUDGET_EXCEEDED
from test_helpers.assertions import assert_fields, assert_money_group, created, failed, ok
from test_helpers.constants import (
    APP_APPROVED,
    APP_CONDITIONAL_APPROVED,
    ASSET_STABILIZED,
    CLOCK_AUG_01,
    LEASE_DRAFT,
    LEASE_VOIDED,
    OCC_RESERVED,
    OCC_VACANT,
    PROJECT_SCOPING,
    WO_DISPATCHED,
    WO_PENDING_DISPATCH,
    WO_VOIDED,
)


def test_voiding_a_work_order_restores_exactly_its_quote_to_the_budget_ledger(api):
    """570000 comes back, a 700000 quote is still refused and a 660000 quote lands on zero.

    PRD SS3.5: "Money is always restored: if the work order named a `project_id`, that
    project's `committed_cost_cents` decreases by `quoted_cost_cents` and its
    `budget_remaining_cents` increases by the same amount, which is what makes the conserved
    money identity hold across voids."  PRD SS3.3 is what makes the restored headroom
    measurable: "when a `project_id` is supplied, the quote is added to the project's
    `committed_cost_cents` and subtracted from `budget_remaining_cents`; if the resulting
    committed total would be **strictly greater** than the project's `approved_budget_cents`
    the work order is refused with `ERR_PROJECT_BUDGET_EXCEEDED`, while landing exactly on the
    approved budget is allowed."

    Design: Difficulty/compensating_invariant/work_order_void_restores_project_budget_ledger_exactly
    """
    ctx = x.three_order_scope(api)
    before = ok(api.get_renovation_project(ctx.project_id, x.OPS))
    assert_money_group(before, committed_cost_cents=1510000, budget_remaining_cents=90000)

    voided = ok(
        api.void_work_order(
            ctx.floor_b_order_id,
            f.void_work_order_payload("flooring deferred to the resident turn"),
            x.OPS,
        )
    )
    assert_fields(voided, status=WO_VOIDED)
    restored = ok(api.get_renovation_project(ctx.project_id, x.OPS))
    assert_money_group(restored, committed_cost_cents=940000, budget_remaining_cents=660000)

    over_budget = f.work_order_payload(
        ctx.home_id,
        ctx.templates.floor["id"],
        quantity=1500,
        crew_size=2,
        scheduled_start_date="2026-08-13",
        scheduled_end_date="2026-08-15",
        quoted_cost_cents=700000,
        project_id=ctx.project_id,
    )
    failed(api.create_work_order(over_budget, x.OPS), ERR_PROJECT_BUDGET_EXCEEDED)
    assert_money_group(
        ok(api.get_renovation_project(ctx.project_id, x.OPS)), committed_cost_cents=940000
    )

    exact = created(
        api.create_work_order(dict(over_budget, quoted_cost_cents=660000), x.OPS)
    )
    assert_money_group(exact, benchmark_total_cents=730313, quoted_cost_cents=660000)
    assert_fields(exact, variance_bps=-963, status=WO_PENDING_DISPATCH)

    settled = ok(api.get_renovation_project(ctx.project_id, x.OPS))
    assert_money_group(settled, committed_cost_cents=1600000, budget_remaining_cents=0)
    assert_fields(settled, status=PROJECT_SCOPING)


def test_voiding_a_dispatched_order_frees_the_shared_date_not_just_the_counter(api):
    """committed_crew_days returns 12 -> 9 and the 12th accepts one crew again.

    PRD SS3.5: "Crew days are restored only if they were ever taken -- that is, only when the
    void happens from `DISPATCHED` or `ACCEPTED`, in which case the assigned vendor's
    `committed_crew_days` decreases by `crew_days`."  PRD SS3.4 fixes the per-date reading of
    that release: a `daily_crew_capacity` of 4 already carrying a three-crew job from the 10th
    through the 12th takes a one-crew job on the 12th through the 14th because it "fits exactly
    at 4 and succeeds, taking `committed_crew_days` from 9 to 12; voiding it returns
    `committed_crew_days` to 9."

    Design: Difficulty/compensating_invariant/work_order_void_restores_vendor_committed_crew_days_exactly
    """
    x.set_clock(api, CLOCK_AUG_01)
    market = x.create_market(api)
    paint = x.create_scope_template(api, f.scope_template_paint())
    home = x.create_home(api, market["id"])
    vendor = x.create_vendor(
        api, market["id"], legal_name="Peachtree Painting LLC", daily_crew_capacity=4
    )
    x.certify_vendor(api, vendor["id"], "PAINT", expires_on="2027-01-31")

    def one_crew_order(crew_size, start, end):
        return get_success_data(
            api.create_work_order(
                f.work_order_payload(
                    home["id"],
                    paint["id"],
                    work_type="RESIDENT_MAINTENANCE",
                    crew_size=crew_size,
                    scheduled_start_date=start,
                    scheduled_end_date=end,
                    fulfillment_channel="VENDOR",
                ),
                x.OPS,
            )
        )

    order_a = one_crew_order(3, "2026-08-10", "2026-08-12")
    get_success_data(api.dispatch_work_order(order_a["id"], {"vendor_id": vendor["id"]}, x.OPS))
    order_c = one_crew_order(1, "2026-08-12", "2026-08-14")
    get_success_data(api.dispatch_work_order(order_c["id"], {"vendor_id": vendor["id"]}, x.OPS))
    order_d = one_crew_order(1, "2026-08-12", "2026-08-14")
    saturated = ok(api.get_vendor(vendor["id"], x.VENDOR_MANAGER))
    assert_fields(saturated, committed_crew_days=12)

    voided = ok(
        api.void_work_order(
            order_c["id"],
            f.void_work_order_payload("resident rescheduled the appointment"),
            x.OPS,
        )
    )
    assert_fields(
        voided, status=WO_VOIDED, void_reason="resident rescheduled the appointment"
    )
    assert_fields(ok(api.get_vendor(vendor["id"], x.VENDOR_MANAGER)), committed_crew_days=9)

    dispatched = ok(api.dispatch_work_order(order_d["id"], {"vendor_id": vendor["id"]}, x.OPS))
    assert_fields(dispatched, status=WO_DISPATCHED, vendor_id=vendor["id"])
    assert_fields(ok(api.get_vendor(vendor["id"], x.VENDOR_MANAGER)), committed_crew_days=12)
    assert_fields(ok(api.get_work_order(order_a["id"], x.OPS)), status=WO_DISPATCHED)


def test_voiding_a_draft_lease_releases_the_home_for_a_second_applicant(api):
    """The home goes back to VACANT, is re-reserved, and the voided lease blocks nothing.

    PRD SS3.8: "**Voiding a draft.** A `LeasingAgent` or a `RegionalDirector` may void a lease
    that is still in `DRAFT` by supplying a `reason`, which is stored in `void_reason` and moves
    the lease to `VOIDED`. That is the transition `DRAFT` -> `VOIDED`, and its compensating
    cascade returns the home's `occupancy_status` `RESERVED` -> `VACANT`, so the home can be
    re-reserved by another application."  PRD SS3.8 on drafting is what makes the second lease
    legal: "the application's home must not already carry a lease whose `status` is `DRAFT` or
    `EXECUTED`, otherwise `ERR_LEASE_ALREADY_EXISTS`."  PRD SS3.6 fixes the second applicant's
    score: a prospect "verified with a document score of 9600, liveness true, a verified income
    of 800000, credit `A`, no evictions, a device reputation of 9200 and 5 km, has identity 400,
    income 0 (clamped up from a raw negative), history 500 and device 800, for 360 basis
    points."

    Design: Difficulty/compensating_invariant/lease_void_returns_home_occupancy_to_vacant_for_reuse
    """
    ctx = x.reserved_home(api, general_template=False)
    assert_fields(ctx.screened, status=APP_CONDITIONAL_APPROVED)
    assert_money_group(ctx.screened, total_move_in_deposit_cents=352500)
    first_lease = x.draft_lease(api, ctx.application_id)
    second = x.verified_prospect(
        api,
        ctx.market_id,
        prospect_overrides={
            "email": "p4@example.com",
            "full_name": "Priya Four",
            "phone": "+1-404-555-0104",
            "declared_monthly_income_cents": 800000,
            "credit_tier": "A",
        },
        verification_overrides={
            "document_type": "PASSPORT",
            "document_match_score_bps": 9600,
            "verified_monthly_income_cents": 800000,
            "device_reputation_bps": 9200,
            "ip_geo_distance_km": 5,
        },
    )
    assert_fields(second.verified, fraud_risk_score_bps=360)

    voided = ok(
        api.void_lease(
            first_lease["id"],
            f.void_lease_payload("applicant withdrew before funding"),
            x.AGENT,
        )
    )
    assert_fields(voided, status=LEASE_VOIDED)
    assert_fields(ok(api.get_home(ctx.home_id, x.ANALYST)), occupancy_status=OCC_VACANT)

    second_app = created(
        api.create_rental_application(
            f.rental_application_payload(
                ctx.home_id,
                second.prospect_id,
                requested_move_in_date="2026-09-25",
                pet_count=0,
                pet_breeds=[],
            ),
            second.headers,
        )
    )
    screened = ok(api.screen_rental_application(second_app["id"], {}, x.AGENT))
    assert_fields(
        screened, status=APP_APPROVED, rent_to_income_bps=2688, risk_multiplier_bps=10000
    )
    assert_money_group(
        screened, security_deposit_cents=215000, total_move_in_deposit_cents=215000
    )
    assert_fields(ok(api.get_home(ctx.home_id, x.ANALYST)), occupancy_status=OCC_RESERVED)

    second_lease = created(
        api.create_lease(
            f.lease_payload(
                second_app["id"], start_date="2026-09-25", monthly_rent_cents=215000
            ),
            x.AGENT,
        )
    )
    assert_fields(second_lease, status=LEASE_DRAFT)
    assert_money_group(second_lease, required_deposit_cents=215000)

    home = ok(api.get_home(ctx.home_id, x.ANALYST))
    assert_fields(home, asset_status=ASSET_STABILIZED, occupancy_status=OCC_RESERVED)
