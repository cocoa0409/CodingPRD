"""Two calls whose outcome is decided entirely by state on entities they never name.

Lease execution reads a compliance obligation through the derived posture, and a work-order
dispatch reads both the vendor's status row and its certification row; in each case the
subject entity is byte-identical across the failing and the succeeding attempt.
"""

from prd_bench_local_runner.testing import get_success_data

from test_helpers import factories as f
from test_helpers import fixtures as x
from test_helpers.api_errors import (
    ERR_HOME_LEASING_FROZEN,
    ERR_VENDOR_INACTIVE,
    ERR_VENDOR_NOT_CERTIFIED,
)
from test_helpers.assertions import assert_fields, assert_money_group, created, failed, ok
from test_helpers.constants import (
    CLOCK_AUG_01,
    LEASE_DRAFT,
    LEASE_EXECUTED,
    OBLIGATION_RESOLVED,
    OBLIGATION_TYPE_INSURANCE,
    OCC_OCCUPIED,
    POSTURE_OPEN,
    POSTURE_RESTRICTED,
    REVIEW_ACCEPT,
    SEVERITY_MAJOR,
    VENDOR_ACTIVE,
    VENDOR_SUSPENDED,
    WO_DISPATCHED,
    WO_PENDING_DISPATCH,
)


def test_a_restricted_home_refuses_execution_until_the_obligation_resolves(api):
    """The same fully funded lease is refused at RESTRICTED and accepted at OPEN.

    PRD SS2.8: "A lease may be executed **only** when the posture is exactly `OPEN` --
    `RESTRICTED` is not sufficient. ... an execution attempt against a home whose posture is
    anything other than `OPEN` is refused with `ERR_HOME_LEASING_FROZEN`."  PRD SS2.8 clause 4:
    "Otherwise, if the home has at least one compliance obligation whose `severity` is `MAJOR`
    and whose `status` is one of `OPEN`, `PLANNED`, `RESOLUTION_SUBMITTED` or
    `RESOLUTION_REJECTED`, the posture is `RESTRICTED`."  PRD SS2.8: "Obligations whose `status`
    is `RESOLVED` or `WAIVED` never affect posture, at any severity."

    Design: Difficulty/cross_entity_state_dependency/lease_execution_requires_home_posture_open_not_restricted
    """
    ctx = x.reserved_home(api, general_template=False)
    lease = x.draft_lease(api, ctx.application_id)
    funded = get_success_data(
        api.pay_deposit(lease["id"], f.deposit_payment_payload(352500), x.AGENT)
    )
    assert_money_group(funded, deposit_paid_cents=352500, required_deposit_cents=352500)
    obligation = get_success_data(
        api.create_compliance_obligation(
            f.obligation_payload(
                ctx.home_id,
                OBLIGATION_TYPE_INSURANCE,
                SEVERITY_MAJOR,
                description="carrier flagged missing wind mitigation endorsement",
                due_on="2026-11-30",
            ),
            x.COMPLIANCE,
        )
    )
    posture = ok(api.get_leasing_posture(ctx.home_id, x.AGENT))
    assert_fields(posture, leasing_posture=POSTURE_RESTRICTED)

    failed(
        api.execute_lease(lease["id"], f.execute_lease_payload(), x.AGENT),
        ERR_HOME_LEASING_FROZEN,
    )
    assert_fields(ok(api.get_lease(lease["id"], x.AGENT)), status=LEASE_DRAFT)

    get_success_data(
        api.plan_obligation(obligation["id"], f.plan_obligation_payload("2026-09-20"), x.COMPLIANCE)
    )
    get_success_data(
        api.submit_obligation_resolution(
            obligation["id"],
            f.submit_resolution_payload(evidence_ref="BINDER-2026-09"),
            x.COMPLIANCE,
        )
    )
    get_success_data(
        api.review_obligation_resolution(
            obligation["id"],
            f.review_resolution_payload(REVIEW_ACCEPT, review_note="endorsement received"),
            x.DIRECTOR,
        )
    )
    assert_fields(
        ok(api.get_compliance_obligation(obligation["id"], x.COMPLIANCE)),
        status=OBLIGATION_RESOLVED,
    )
    assert_fields(ok(api.get_home(ctx.home_id, x.ANALYST)), leasing_posture=POSTURE_OPEN)

    executed = ok(api.execute_lease(lease["id"], f.execute_lease_payload(), x.AGENT))
    assert_fields(executed, status=LEASE_EXECUTED, signed_on="2026-09-06")
    assert_fields(ok(api.get_home(ctx.home_id, x.ANALYST)), occupancy_status=OCC_OCCUPIED)
    assert_fields(
        ok(api.get_underwriting_case(ctx.case_id, x.ANALYST)), realized_yield_on_cost_bps=556
    )


def test_dispatch_reads_the_certification_row_then_the_vendor_status_row(api):
    """The same order fails uncertified, fails suspended, then dispatches for 9 crew days.

    PRD SS3.4: the vendor "must satisfy every eligibility clause: its `status` must be `ACTIVE`,
    or the dispatch fails with `ERR_VENDOR_INACTIVE`; ... it must hold a certification whose
    `certification_code` equals the work order's scope template `certification_code`, whose
    `status` is `ACTIVE`, whose `effective_on` is on or before the clock date and whose
    `expires_on` is on or after the clock date, or `ERR_VENDOR_NOT_CERTIFIED`".  PRD SS3.4 on the
    successful branch: "On the `VENDOR` branch the work order moves `PENDING_DISPATCH ->
    DISPATCHED`, its `vendor_id` is set to the selected vendor, and that vendor's
    `committed_crew_days` increases by this work order's `crew_days`."

    Design: Difficulty/cross_entity_state_dependency/dispatch_requires_current_vendor_certification_and_active_status
    """
    x.set_clock(api, CLOCK_AUG_01)
    market = x.create_market(api)
    hvac = x.create_scope_template(api, f.scope_template_hvac())
    home = x.create_home(api, market["id"])
    vendor = x.create_vendor(api, market["id"])
    order = created(
        api.create_work_order(
            f.work_order_payload(
                home["id"],
                hvac["id"],
                work_type="RESIDENT_MAINTENANCE",
                fulfillment_channel="VENDOR",
                quoted_cost_cents=640000,
            ),
            x.OPS,
        )
    )
    assert_fields(order, crew_days=9, variance_bps=195)

    failed(
        api.dispatch_work_order(order["id"], {"vendor_id": vendor["id"]}, x.OPS),
        ERR_VENDOR_NOT_CERTIFIED,
    )
    assert_fields(ok(api.get_work_order(order["id"], x.OPS)), status=WO_PENDING_DISPATCH)
    assert_fields(ok(api.get_vendor(vendor["id"], x.VENDOR_MANAGER)), committed_crew_days=0)

    x.certify_vendor(api, vendor["id"], "HVAC", expires_on="2027-01-31")
    get_success_data(
        api.set_vendor_status(
            vendor["id"],
            f.vendor_status_payload(VENDOR_SUSPENDED, suspension_reason="pending safety audit"),
            x.VENDOR_MANAGER,
        )
    )

    body = failed(
        api.dispatch_work_order(order["id"], {"vendor_id": vendor["id"]}, x.OPS),
        ERR_VENDOR_INACTIVE,
    )
    assert body.get("error_id") != ERR_VENDOR_NOT_CERTIFIED

    get_success_data(
        api.set_vendor_status(vendor["id"], f.vendor_status_payload(VENDOR_ACTIVE), x.VENDOR_MANAGER)
    )

    dispatched = ok(api.dispatch_work_order(order["id"], {"vendor_id": vendor["id"]}, x.OPS))
    assert_fields(dispatched, status=WO_DISPATCHED, vendor_id=vendor["id"])
    assert_fields(
        ok(api.get_vendor(vendor["id"], x.VENDOR_MANAGER)),
        committed_crew_days=9,
        status=VENDOR_ACTIVE,
    )
