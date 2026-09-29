"""Partial updates, the two-step sale, and a cure plan whose link is queryable.

Each of these endpoints is checked for what it does *not* do as much as for what it does: PATCH
leaves the unnamed fields and the two unreachable ones alone, the sale refuses and then accepts
the identical payload, and planning stores an association rather than an opaque string.
"""

from test_helpers import factories as f
from test_helpers import fixtures as x
from test_helpers.api_errors import (
    ERR_DISPOSITION_NOT_ELIGIBLE,
    ERR_INVALID_STATE,
)
from test_helpers.assertions import (
    assert_absent_or_empty,
    assert_fields,
    assert_ids,
    assert_money_group,
    assert_page_meta,
    assert_version,
    created,
    failed,
    ok,
    page,
)
from test_helpers.constants import (
    ASSET_DISPOSED,
    ASSET_DISPOSITION_APPROVED,
    ASSET_STABILIZED,
    CLOCK_AUG_01,
    DISPOSITION_INDIVIDUAL,
    DISPOSITION_NONE,
    LEASE_VOIDED,
    OBLIGATION_PLANNED,
    OCC_RESERVED,
    OCC_VACANT,
    POSTURE_FROZEN,
    POSTURE_OPEN,
    VENDOR_ACTIVE,
    VENDOR_SUSPENDED,
    WO_PENDING_DISPATCH,
)


def test_patching_one_commercial_field_leaves_the_other_three_and_the_status_alone(api):
    """Version 1 to 4 across two patches and one status change, with nothing else drifting.

    PRD SS3.4: "A vendor is created with `status` `ACTIVE`, `committed_crew_days` 0 and
    `suspension_reason` the empty string."  And on revision: "Commercial terms move over time, so
    `daily_crew_capacity`, `cost_index_bps`, `quality_score_bps` and `insurance_expires_on` are each
    individually revisable by the `VendorManager`; only supplied fields are overwritten,
    `committed_crew_days` and `status` are never writable through that path, and the vendor's
    `version` increments by 1. ... Suspension and reactivation are a separate capability that sets
    `status` to `ACTIVE` or `SUSPENDED` and stores a `suspension_reason`. ... Vendors are readable
    individually -- the read exposes the live `committed_crew_days` -- and as a list filterable by
    `market_id` and `status`."  The counter is PRD SS2.4's: "`version`, an integer that starts at 1
    when the row is created and increments by exactly 1 on every mutation of that row, including
    mutations reached as a cascade side effect of an operation on a different resource."

    Design: Corner/endpoints/vendor_patch_updates_only_supplied_fields_and_bumps_version
    """
    x.set_clock(api, CLOCK_AUG_01)
    market = x.create_market(api)
    vendor = x.create_vendor(
        api,
        market["id"],
        legal_name="Peachtree Painters",
        daily_crew_capacity=10,
        insurance_expires_on="2027-06-30",
    )

    fresh = ok(api.get_vendor(vendor["id"], x.VENDOR_MANAGER))
    assert fresh["id"] == vendor["id"]
    assert_fields(fresh, status=VENDOR_ACTIVE, committed_crew_days=0)
    assert_version(fresh, 1)

    one_field = ok(api.patch_vendor(vendor["id"], {"cost_index_bps": 9500}, x.VENDOR_MANAGER))
    assert_fields(
        one_field,
        cost_index_bps=9500,
        daily_crew_capacity=10,
        quality_score_bps=8600,
        insurance_expires_on="2027-06-30",
        status=VENDOR_ACTIVE,
    )
    assert_version(one_field, 2)

    two_fields = ok(
        api.patch_vendor(
            vendor["id"],
            {"daily_crew_capacity": 4, "insurance_expires_on": "2027-12-31"},
            x.VENDOR_MANAGER,
        )
    )
    assert_fields(
        two_fields,
        daily_crew_capacity=4,
        insurance_expires_on="2027-12-31",
        cost_index_bps=9500,
        quality_score_bps=8600,
        status=VENDOR_ACTIVE,
        committed_crew_days=0,
    )
    assert_version(two_fields, 3)

    rows, meta = page(api.list_vendors(x.VENDOR_MANAGER, {"market_id": market["id"]}))
    assert_page_meta(meta, total_count=1)
    assert_ids(rows, [vendor["id"]])

    suspended = ok(
        api.set_vendor_status(
            vendor["id"],
            f.vendor_status_payload("SUSPENDED", suspension_reason="Workmanship complaints"),
            x.VENDOR_MANAGER,
        )
    )
    assert_fields(
        suspended,
        status=VENDOR_SUSPENDED,
        suspension_reason="Workmanship complaints",
        daily_crew_capacity=4,
        cost_index_bps=9500,
    )
    assert_version(suspended, 4)


def test_the_individual_sale_waits_for_vacancy_then_prices_against_the_realized_basis(api):
    """One payload, refused while RESERVED and accepted once the void frees the home.

    PRD SS3.9: "`APPROVE_SALE` moves the home `STABILIZED -> DISPOSITION_APPROVED` and stores the
    payload's `disposition_mode` (`NONE`, `INDIVIDUAL` or `PORTFOLIO_LOT`), `bpo_value_cents` and
    `lot_code`, the last being the empty string for an `INDIVIDUAL` sale. It requires the home's
    `leasing_posture` not to be `FROZEN`. Its occupancy requirement depends on the mode and is the
    clearest expression of the two dimensions being independent: an `INDIVIDUAL` sale requires the
    home's `occupancy_status` to be `VACANT`, and anything else is refused with
    `ERR_DISPOSITION_NOT_ELIGIBLE`".  PRD SS3.9 on the second step: "`CLOSE_SALE` moves the home
    `DISPOSITION_APPROVED -> DISPOSED` and requires `net_sale_proceeds_cents` to be present in the
    payload. It stores that figure and computes `realized_gain_cents` as `net_sale_proceeds_cents`
    less the basis, where the basis is the `APPROVED` underwriting case's
    `realized_all_in_basis_cents` when that field is non-null and its `underwritten_all_in_basis_cents`
    otherwise ... `DISPOSED` is a freezing asset state, so the home's `leasing_posture` becomes
    `FROZEN` ... `PASSED` and `DISPOSED` are both terminal on the asset dimension: no further asset
    transition is accepted from either, and an attempt is refused with `ERR_INVALID_STATE`."  The
    void is the release -- PRD SS3.8: "Voiding a lease requires a `reason`, moves it `DRAFT` or
    `EXECUTED` -> `VOIDED`", returning the home to `VACANT`.

    Design: Corner/endpoints/individual_sale_is_conditional_on_vacancy_then_closes_with_realized_gain
    """
    ctx = x.renovated_home(api)
    case = ok(api.get_underwriting_case(ctx.case_id, x.ANALYST))
    assert_money_group(case, realized_all_in_basis_cents=26050000)
    assert_fields(case, realized_yield_on_cost_bps=584)

    prospect = x.verified_prospect(api, ctx.market_id)
    approved = x.screened_application(api, ctx.home_id, prospect.prospect_id)
    lease = x.draft_lease(api, approved.application_id)
    reserved = ok(api.get_home(ctx.home_id, x.COMMITTEE))
    assert_fields(
        reserved,
        asset_status=ASSET_STABILIZED,
        occupancy_status=OCC_RESERVED,
        leasing_posture=POSTURE_OPEN,
    )

    failed(
        api.disposition_decision(ctx.home_id, f.approve_sale_payload(), x.COMMITTEE),
        ERR_DISPOSITION_NOT_ELIGIBLE,
    )
    refused = ok(api.get_home(ctx.home_id, x.COMMITTEE))
    assert_fields(
        refused, asset_status=ASSET_STABILIZED, disposition_mode=DISPOSITION_NONE
    )

    voided = ok(api.void_lease(lease["id"], f.void_lease_payload(), x.AGENT))
    assert_fields(voided, status=LEASE_VOIDED)
    assert_fields(ok(api.get_home(ctx.home_id, x.COMMITTEE)), occupancy_status=OCC_VACANT)

    listed = ok(api.disposition_decision(ctx.home_id, f.approve_sale_payload(), x.COMMITTEE))
    assert_fields(
        listed,
        asset_status=ASSET_DISPOSITION_APPROVED,
        disposition_mode=DISPOSITION_INDIVIDUAL,
        leasing_posture=POSTURE_OPEN,
    )
    assert_money_group(listed, bpo_value_cents=30000000)
    assert_absent_or_empty(listed, "lot_code")

    closed = ok(api.disposition_decision(ctx.home_id, f.close_sale_payload(), x.COMMITTEE))
    assert_fields(
        closed, asset_status=ASSET_DISPOSED, leasing_posture=POSTURE_FROZEN
    )
    assert_money_group(
        closed, net_sale_proceeds_cents=30000000, realized_gain_cents=3950000
    )

    failed(
        api.disposition_decision(ctx.home_id, f.close_sale_payload(), x.COMMITTEE),
        ERR_INVALID_STATE,
    )
    terminal = ok(api.get_home(ctx.home_id, x.COMMITTEE))
    assert_fields(terminal, asset_status=ASSET_DISPOSED)
    assert_money_group(terminal, realized_gain_cents=3950000)


def test_two_obligations_may_share_one_remediation_order_and_the_filter_finds_both(api):
    """The stored link is a real reference: filtering by it returns two of the three rows.

    PRD SS3.9: "A `ComplianceOfficer` commits a cure plan by supplying `planned_resolution_on` and
    optionally `work_order_id`, the remediation work order that will do the field work; it stays the
    empty string when the cure needs none. Planning moves the obligation `OPEN -> PLANNED`, or
    `RESOLUTION_REJECTED -> PLANNED` with `resolution_round` increased by 1".  The query side is PRD
    SS3.9's: "Obligations are readable individually -- the read exposes the tax-appeal economics --
    and as a list filterable by `home_id`, `supersedes_obligation_id`, `work_order_id`,
    `obligation_type`, `severity` and `status`."  The envelope's arithmetic is PRD SS2.3's:
    "`total_count` (the number of rows matching the filters before pagination)".  Planning is not a
    dispatch -- PRD SS3.4: "A work order is created in `PENDING_DISPATCH` with `vendor_id` ... the
    empty string", and only dispatch "moves `PENDING_DISPATCH -> DISPATCHED`".

    Design: Corner/endpoints/obligation_plan_links_a_work_order_and_the_link_is_queryable
    """
    x.set_clock(api, CLOCK_AUG_01)
    market = x.create_market(api)
    paint = x.create_scope_template(api, f.scope_template_paint())
    home = x.create_home(api, market["id"])
    order = created(
        api.create_work_order(
            f.work_order_payload(home["id"], paint["id"], work_type="TURN"), x.OPS
        )
    )

    trim = x.open_obligation(
        api,
        home["id"],
        severity="MAJOR",
        description="Peeling exterior trim",
        due_on="2026-10-31",
    )
    shutters = x.open_obligation(
        api,
        home["id"],
        severity="MAJOR",
        description="Faded shutters",
        due_on="2026-10-31",
    )
    paperwork = x.open_obligation(
        api,
        home["id"],
        obligation_type="INSURANCE_DEFICIENCY",
        description="Roof age documentation",
        due_on="2026-10-31",
    )

    linked = ok(
        api.plan_obligation(
            trim["id"],
            f.plan_obligation_payload("2026-08-20", work_order_id=order["id"]),
            x.COMPLIANCE,
        )
    )
    assert_fields(
        linked,
        status=OBLIGATION_PLANNED,
        work_order_id=order["id"],
        planned_resolution_on="2026-08-20",
    )

    shared = ok(
        api.plan_obligation(
            shutters["id"],
            f.plan_obligation_payload("2026-08-20", work_order_id=order["id"]),
            x.COMPLIANCE,
        )
    )
    assert_fields(shared, status=OBLIGATION_PLANNED, work_order_id=order["id"])

    unlinked = ok(
        api.plan_obligation(
            paperwork["id"], f.plan_obligation_payload("2026-08-25"), x.COMPLIANCE
        )
    )
    assert_fields(unlinked, status=OBLIGATION_PLANNED)
    assert_absent_or_empty(unlinked, "work_order_id")

    by_order, order_meta = page(
        api.list_compliance_obligations(x.COMPLIANCE, {"work_order_id": order["id"]})
    )
    assert_page_meta(order_meta, total_count=2)
    assert_ids(by_order, [trim["id"], shutters["id"]])

    by_home, home_meta = page(
        api.list_compliance_obligations(x.COMPLIANCE, {"home_id": home["id"]})
    )
    assert_page_meta(home_meta, total_count=3)
    assert_ids(by_home, [trim["id"], shutters["id"], paperwork["id"]])

    assert_fields(
        ok(api.get_work_order(order["id"], x.OPS)), status=WO_PENDING_DISPATCH
    )
