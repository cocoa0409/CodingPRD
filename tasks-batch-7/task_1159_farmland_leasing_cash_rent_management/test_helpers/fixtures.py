"""Composite setup helpers for multi-step test prerequisites.

Almost every interesting rule in this domain lives behind the same pipeline:
landlord -> tenant (approved) -> field -> offering -> bid -> shortlist ->
close -> award -> lease -> activate. The helpers below build that chain once
per test so tests can focus on assertions. All setup calls go through
get_success_data() so a broken precondition reports as a clear setup failure.

Every test runs against a freshly restarted server (empty database, logical
clock at the 2026-05-01T00:00:00Z default per PRD §2.5); fixtures never rely
on state from other tests.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_bid_payload,
    create_expense_payload,
    create_field_payload,
    create_improvement_payload,
    create_landlord_payload,
    create_lease_payload,
    create_notice_payload,
    create_offering_payload,
    create_report_payload,
    create_settlement_payload,
    create_tenant_payload,
    evidence_payload,
)
from .test_users import (
    TEST_USERS,
    make_farm_manager_headers,
    make_landlord_headers,
    make_tenant_headers,
)

MGR = TEST_USERS["farm_manager_headers"]
MGR_1 = TEST_USERS["mgr_1_headers"]
MGR_2 = TEST_USERS["mgr_2_headers"]
MGR_3 = TEST_USERS["mgr_3_headers"]

DEFAULT_TERM_START = "2027-03-01T00:00:00Z"
DEFAULT_TERM_END = "2028-03-01T00:00:00Z"


# ---------------------------------------------------------------------------
# Tier 0: primitive creators and readers
# ---------------------------------------------------------------------------

def _ok(resp):
    return get_success_data(resp)


def set_clock(iso_timestamp: str) -> dict:
    """Advance the logical clock; runs the sweep pipeline (PRD §2.5)."""
    return _ok(api_client.set_clock({"to_iso8601": iso_timestamp}, MGR))


def setup_landlord(**overrides) -> dict:
    return _ok(api_client.create_landlord(create_landlord_payload(**overrides), MGR))


def setup_tenant(approve: bool = True, **overrides) -> dict:
    tenant = _ok(api_client.create_tenant(create_tenant_payload(**overrides), MGR))
    if approve:
        tenant = _ok(api_client.approve_tenant(tenant["id"], MGR))
    return tenant


def setup_field(landlord_id: str, **overrides) -> dict:
    return _ok(api_client.create_field(create_field_payload(landlord_id, **overrides), MGR))


def setup_offering(field_id: str, **overrides) -> dict:
    return _ok(api_client.create_offering(create_offering_payload(field_id, **overrides), MGR))


def setup_bid(offering_id: str, tenant_id: str, lease_type: str = "CASH", **overrides) -> dict:
    """Submit a bid as the given tenant (tenant_id comes from X-User-ID)."""
    return _ok(
        api_client.create_bid(
            create_bid_payload(offering_id, lease_type, **overrides),
            make_tenant_headers(tenant_id),
        )
    )


def get_lease(lease_id: str) -> dict:
    return _ok(api_client.get_lease(lease_id, MGR))


def get_tenant(tenant_id: str) -> dict:
    return _ok(api_client.get_tenant(tenant_id, MGR))


def get_landlord(landlord_id: str) -> dict:
    return _ok(api_client.get_landlord(landlord_id, MGR))


def get_offering(offering_id: str) -> dict:
    return _ok(api_client.get_offering(offering_id, MGR))


def get_bid(bid_id: str) -> dict:
    return _ok(api_client.get_bid(bid_id, MGR))


def get_field(field_id: str) -> dict:
    return _ok(api_client.get_field(field_id, MGR))


def get_improvement(improvement_id: str) -> dict:
    return _ok(api_client.get_improvement(improvement_id, MGR))


def get_notice(notice_id: str) -> dict:
    return _ok(api_client.get_notice(notice_id, MGR))


def get_report(report_id: str) -> dict:
    return _ok(api_client.get_report(report_id, MGR))


def get_settlement(settlement_id: str) -> dict:
    return _ok(api_client.get_settlement(settlement_id, MGR))


def get_compliance_record(record_id: str) -> dict:
    return _ok(api_client.get_compliance_record(record_id, MGR))


def get_installment(installment_id: str) -> dict:
    return _ok(api_client.get_installment(installment_id, MGR))


def list_lease_installments(lease_id: str) -> list:
    """Installments of a lease in the endpoint's due-date ordering (PRD §2.3)."""
    return _ok(api_client.list_installments(MGR, params={"lease_id": lease_id}))


def list_lease_compliance_records(lease_id: str) -> list:
    return _ok(api_client.list_compliance_records(MGR, params={"lease_id": lease_id}))


def list_landlord_reports(landlord_id: str) -> list:
    return _ok(api_client.list_reports(MGR, params={"landlord_id": landlord_id}))


def list_offering_bids(offering_id: str, **filters) -> list:
    params = {"offering_id": offering_id}
    params.update(filters)
    return _ok(api_client.list_bids(MGR, params=params))


# ---------------------------------------------------------------------------
# Tier 1/2: award pipeline and lease creation
# ---------------------------------------------------------------------------

def shortlist_close_award(offering_id: str, bid_id: str, landlord_id: str) -> dict:
    """Manager shortlists + closes; owning landlord awards. Returns the
    refreshed (ACCEPTED) bid."""
    _ok(api_client.shortlist_bid(bid_id, MGR))
    _ok(api_client.close_offering(offering_id, MGR))
    _ok(
        api_client.award_offering(
            offering_id, {"bid_id": bid_id}, make_landlord_headers(landlord_id)
        )
    )
    return get_bid(bid_id)


def setup_draft_lease(bid_id: str, **overrides) -> dict:
    return _ok(api_client.create_lease(create_lease_payload(bid_id, **overrides), MGR))


def setup_active_lease(
    lease_type: str = "CASH",
    *,
    acres: int = 100,
    soil_csr2: int = 80,
    cash_bid_cents: int = 25000,
    ce_bid_cents: int | None = None,
    flex_base_cents: int = 20000,
    flex_bonus_pct: float = 0.2,
    flex_cap_cents: int = 500000,
    revenue_trigger_cents: int = 9000000,
    landlord_share_pct: float = 0.4,
    input_share_pct: float = 0.5,
    min_bid_cents: int | None = None,
    term_years: int = 1,
    term_start: str = DEFAULT_TERM_START,
    term_end: str = DEFAULT_TERM_END,
    payment_pattern: str | None = None,
    escalation_type: str = "NONE",
    escalation_pct: float | None = None,
    notice_lead_days: int | None = None,
    conservation_practices: list | None = None,
    tenant_experience: int = 5,
    landlord_overrides: dict | None = None,
    activate: bool = True,
) -> dict:
    """Full award pipeline ending in a DRAFT or ACTIVE lease.

    Returns a context dict with landlord / tenant / field / offering / bid /
    lease. Bid and lease economics follow the lease_type branch rules of the
    PRD: CASH bids carry a cash rate, FLEX bids carry base/bonus/cap/trigger,
    SHARE bids carry landlord and input shares.
    """
    landlord = setup_landlord(**(landlord_overrides or {}))
    tenant = setup_tenant(years_experience=tenant_experience)
    field = setup_field(landlord["id"], acres=acres, soil_csr2=soil_csr2)
    offering = setup_offering(
        field["id"],
        term_years=term_years,
        term_start_date=term_start,
        min_bid_per_acre_cents=(
            min_bid_cents if min_bid_cents is not None else 20000
        ),
    )

    bid_kwargs: dict = {}
    if lease_type == "CASH":
        bid_kwargs["cash_bid_per_acre_cents"] = cash_bid_cents
        bid_kwargs["cash_equivalent_bid_cents_per_acre"] = (
            ce_bid_cents if ce_bid_cents is not None else cash_bid_cents
        )
    elif lease_type == "FLEX":
        bid_kwargs.update(
            flex_base_per_acre_cents=flex_base_cents,
            flex_bonus_pct=flex_bonus_pct,
            flex_cap_cents=flex_cap_cents,
            revenue_trigger_cents=revenue_trigger_cents,
            cash_equivalent_bid_cents_per_acre=(
                ce_bid_cents if ce_bid_cents is not None else 22000
            ),
        )
    elif lease_type == "SHARE":
        bid_kwargs.update(
            landlord_share_pct=landlord_share_pct,
            input_share_pct=input_share_pct,
            cash_equivalent_bid_cents_per_acre=(
                ce_bid_cents if ce_bid_cents is not None else 25000
            ),
        )
    bid = setup_bid(offering["id"], tenant["id"], lease_type, **bid_kwargs)
    bid = shortlist_close_award(offering["id"], bid["id"], landlord["id"])

    lease_kwargs: dict = {
        "term_start_date": term_start,
        "term_end_date": term_end,
        "payment_pattern": payment_pattern
        or ("NONE" if lease_type == "SHARE" else "MAR_NOV_50_50"),
        "escalation_type": escalation_type,
    }
    if escalation_pct is not None:
        lease_kwargs["escalation_pct"] = escalation_pct
    if notice_lead_days is not None:
        lease_kwargs["notice_lead_days"] = notice_lead_days
    if conservation_practices is not None:
        lease_kwargs["conservation_practices"] = conservation_practices
    lease = setup_draft_lease(bid["id"], **lease_kwargs)

    if activate:
        _ok(api_client.activate_lease(lease["id"], MGR))
        lease = get_lease(lease["id"])

    return {
        "landlord": landlord,
        "tenant": tenant,
        "field": get_field(field["id"]),
        "offering": get_offering(offering["id"]),
        "bid": bid,
        "lease": lease,
    }


# ---------------------------------------------------------------------------
# Tier 3: installment states (clock-driven)
# ---------------------------------------------------------------------------

def setup_open_installment_scenario(**lease_kwargs) -> dict:
    """Active CASH lease (default 25000 cents/acre on 100 acres -> two
    installments of 1250000 due Mar 1 / Nov 1) with the clock at the first
    due date, so the March installment is OPEN and the November one is still
    SCHEDULED. Returns ctx + ctx['installments']."""
    ctx = setup_active_lease("CASH", **lease_kwargs)
    set_clock("2027-03-01T00:00:00Z")
    ctx["installments"] = list_lease_installments(ctx["lease"]["id"])
    return ctx


def setup_late_installment_scenario(**lease_kwargs) -> dict:
    """Active CASH lease with the clock eleven days past the March due date:
    the March installment is LATE and carries its one-time 5% late fee."""
    ctx = setup_active_lease("CASH", **lease_kwargs)
    set_clock("2027-03-12T00:00:00Z")
    ctx["installments"] = list_lease_installments(ctx["lease"]["id"])
    return ctx


def setup_paid_installment_scenario(payer_headers=None, **lease_kwargs) -> dict:
    """Open-installment scenario, then the March installment paid in full by
    the given manager (default mgr-1). Returns ctx with ctx['installments']
    taken before payment and ctx['paid_installment'] after payment."""
    ctx = setup_open_installment_scenario(**lease_kwargs)
    first = ctx["installments"][0]
    ctx["paid_installment"] = _ok(
        api_client.record_payment(
            first["id"],
            {"amount_cents": first["amount_cents"]},
            payer_headers or MGR_1,
        )
    )
    return ctx


# ---------------------------------------------------------------------------
# Tier 3/4: settlements and expenses
# ---------------------------------------------------------------------------

def create_settlement(ctx: dict, manager_headers=None, **overrides) -> dict:
    """Create a settlement against the context lease, carrying the lease's
    freshly observed version for the optimistic-concurrency check (PRD §2.7)."""
    lease = get_lease(ctx["lease"]["id"])
    payload = create_settlement_payload(
        lease["id"], expected_lease_version=lease["version"], **overrides
    )
    return _ok(api_client.create_settlement(payload, manager_headers or MGR))


def setup_settlement_scenario(
    lease_type: str = "FLEX",
    price_source: str = "ACTUAL",
    yield_bu_per_acre: int = 200,
    harvest_price_cents_per_bu: int = 500,
    crop_year: int = 2027,
    clock: str | None = None,
    **lease_kwargs,
) -> dict:
    """Active FLEX/SHARE lease plus one PROVISIONAL settlement for crop_year.
    Returns ctx + ctx['settlement']."""
    ctx = setup_active_lease(lease_type, **lease_kwargs)
    if clock is not None:
        set_clock(clock)
    ctx["settlement"] = create_settlement(
        ctx,
        price_source=price_source,
        yield_bu_per_acre=yield_bu_per_acre,
        harvest_price_cents_per_bu=harvest_price_cents_per_bu,
        crop_year=crop_year,
    )
    return ctx


def setup_finalized_settlement_scenario(
    finalizer_headers=None, **settlement_kwargs
) -> dict:
    """Settlement scenario with the settlement FINALIZED by the given manager
    (default mgr-1). Returns ctx + ctx['settlement']."""
    ctx = setup_settlement_scenario(**settlement_kwargs)
    ctx["settlement"] = _ok(
        api_client.finalize_settlement(
            ctx["settlement"]["id"], finalizer_headers or MGR_1
        )
    )
    return ctx


def submit_expense(ctx: dict, tenant_id: str | None = None, **overrides) -> dict:
    """Tenant-submitted input-cost record on the context lease."""
    tid = tenant_id or ctx["tenant"]["id"]
    return _ok(
        api_client.create_expense(
            create_expense_payload(ctx["lease"]["id"], **overrides),
            make_tenant_headers(tid),
        )
    )


def setup_share_lease_with_approved_expenses(
    expense_amounts=(100001, 100001), crop_year: int = 2027, **lease_kwargs
) -> dict:
    """Active SHARE lease with the given expenses submitted by the tenant and
    approved by a manager. Returns ctx + ctx['expenses']."""
    ctx = setup_active_lease("SHARE", **lease_kwargs)
    expenses = []
    for i, amount in enumerate(expense_amounts):
        exp = submit_expense(
            ctx,
            total_cost_cents=amount,
            incurred_date=f"2027-04-{10 + i:02d}T00:00:00Z",
            crop_year=crop_year,
        )
        expenses.append(_ok(api_client.approve_expense(exp["id"], MGR)))
    ctx["expenses"] = expenses
    return ctx


# ---------------------------------------------------------------------------
# Tier 3/4: conservation compliance
# ---------------------------------------------------------------------------

def setup_lease_with_practices_scenario(practices: list, **lease_kwargs) -> dict:
    """Active lease carrying the given conservation practices; activation has
    created one PENDING compliance record per entry. Returns ctx +
    ctx['records'] (creation order)."""
    ctx = setup_active_lease("CASH", conservation_practices=practices, **lease_kwargs)
    ctx["records"] = list_lease_compliance_records(ctx["lease"]["id"])
    return ctx


def flip_records_to_noncompliant(ctx: dict, clock: str = "2027-07-02T00:00:00Z") -> dict:
    """Advance the clock past the records' cure deadlines so the sweep flips
    them NON_COMPLIANT, then refresh tenant and records into the context."""
    set_clock(clock)
    ctx["tenant"] = get_tenant(ctx["tenant"]["id"])
    ctx["records"] = list_lease_compliance_records(ctx["lease"]["id"])
    return ctx


def setup_noncompliant_tenant_scenario(num_practices: int = 1, **lease_kwargs) -> dict:
    """Active lease whose tenant has `num_practices` NON_COMPLIANT records
    after the cure-deadline sweep (score 100 - 15*num_practices)."""
    practice_types = ["COVER_CROP", "NO_TILL", "BUFFER_STRIP", "NUTRIENT_PLAN"]
    practices = [
        {"practice_type": practice_types[i % 4], "due_date": "2027-06-01T00:00:00Z"}
        for i in range(num_practices)
    ]
    ctx = setup_lease_with_practices_scenario(practices, **lease_kwargs)
    return flip_records_to_noncompliant(ctx)


def setup_noncompliance_cascade_scenario() -> dict:
    """Depth-3 cascade setup: an active lease carrying four conservation
    practices (all with cure deadline 2027-07-01) plus a second OPEN offering
    on another field holding a live SUBMITTED bid by the same tenant. The
    clock is then advanced past the cure deadline so the non-compliance
    cascade fires: score drop -> suspension -> bid withdrawal -> offering
    recount. Returns ctx with 'records', 'offering_b', 'bid_b'."""
    practice_types = ["COVER_CROP", "NO_TILL", "BUFFER_STRIP", "NUTRIENT_PLAN"]
    practices = [
        {"practice_type": p, "due_date": "2027-06-01T00:00:00Z"} for p in practice_types
    ]
    ctx = setup_lease_with_practices_scenario(practices)
    field_b = setup_field(ctx["landlord"]["id"], name="Field B", acres=80, soil_csr2=79)
    offering_b = setup_offering(
        field_b["id"],
        term_start_date="2028-03-01T00:00:00Z",
        bid_deadline="2027-12-15T00:00:00Z",
    )
    bid_b = setup_bid(
        offering_b["id"],
        ctx["tenant"]["id"],
        "CASH",
        cash_bid_per_acre_cents=26000,
        cash_equivalent_bid_cents_per_acre=26000,
    )
    ctx["field_b"] = field_b
    ctx["offering_b"] = offering_b
    ctx["bid_b"] = bid_b
    set_clock("2027-07-02T00:00:00Z")
    ctx["tenant"] = get_tenant(ctx["tenant"]["id"])
    ctx["records"] = list_lease_compliance_records(ctx["lease"]["id"])
    ctx["bid_b"] = get_bid(bid_b["id"])
    ctx["offering_b"] = get_offering(offering_b["id"])
    return ctx


# ---------------------------------------------------------------------------
# Tier 2: second lease for the same tenant (compliance-gate scenarios)
# ---------------------------------------------------------------------------

def setup_second_draft_lease(
    ctx: dict,
    term_start: str = "2028-03-01T00:00:00Z",
    term_end: str = "2029-03-01T00:00:00Z",
    bid_deadline: str = "2027-12-15T00:00:00Z",
    cash_bid_cents: int = 24000,
    **lease_kwargs,
) -> dict:
    """Award a second bid by the context tenant on a fresh field and create a
    DRAFT lease from it. Returns the DRAFT lease."""
    field2 = setup_field(ctx["landlord"]["id"], name="Field 2", acres=60, soil_csr2=78)
    offering2 = setup_offering(
        field2["id"], term_start_date=term_start, bid_deadline=bid_deadline
    )
    bid2 = setup_bid(
        offering2["id"],
        ctx["tenant"]["id"],
        "CASH",
        cash_bid_per_acre_cents=cash_bid_cents,
        cash_equivalent_bid_cents_per_acre=cash_bid_cents,
    )
    bid2 = shortlist_close_award(offering2["id"], bid2["id"], ctx["landlord"]["id"])
    lease2 = setup_draft_lease(
        bid2["id"], term_start_date=term_start, term_end_date=term_end, **lease_kwargs
    )
    ctx["field2"] = field2
    ctx["offering2"] = get_offering(offering2["id"])
    ctx["bid2"] = bid2
    ctx["lease2"] = lease2
    return lease2


# ---------------------------------------------------------------------------
# Tier 5: termination and improvements
# ---------------------------------------------------------------------------

def serve_notice(ctx: dict, served_by: str = "LANDLORD") -> dict:
    """Serve a termination notice as the named lease party."""
    if served_by == "LANDLORD":
        headers = make_landlord_headers(ctx["landlord"]["id"])
    else:
        headers = make_tenant_headers(ctx["tenant"]["id"])
    return _ok(
        api_client.create_notice(
            create_notice_payload(ctx["lease"]["id"], served_by), headers
        )
    )


def setup_terminated_lease_with_improvements(
    methods=("STRAIGHT_LINE", "AGREED_VALUE"),
    project_types=("TILE_DRAINAGE", "IRRIGATION"),
    total_cost_cents: int = 2000000,
    tenant_share_pct: float = 0.5,
    amortization_years: int = 5,
    complete_clock: str = "2027-03-01T00:00:00Z",
    notice_clock: str = "2027-08-15T00:00:00Z",
    final_clock: str = "2028-03-01T00:00:00Z",
    landlord_overrides: dict | None = None,
    **lease_kwargs,
) -> dict:
    """Full wind-down setup: active CASH lease, one COMPLETED improvement per
    (method, project_type) pair linked to the lease, an on-time landlord
    notice, then the clock advanced to the effective date so the lease
    terminates and reimbursements are computed.

    Returns ctx with 'improvements' (refreshed), 'notice', 'lease'."""
    ctx = setup_active_lease(
        "CASH", landlord_overrides=landlord_overrides, **lease_kwargs
    )
    set_clock(complete_clock)
    improvements = []
    for method, ptype in zip(methods, project_types):
        imp = _ok(
            api_client.create_improvement(
                create_improvement_payload(
                    ctx["field"]["id"],
                    lease_id=ctx["lease"]["id"],
                    project_type=ptype,
                    total_cost_cents=total_cost_cents,
                    landlord_share_pct=1.0 - tenant_share_pct,
                    tenant_share_pct=tenant_share_pct,
                    reimbursement_method=method,
                    amortization_years=amortization_years,
                ),
                MGR,
            )
        )
        _ok(
            api_client.approve_improvement(
                imp["id"], make_landlord_headers(ctx["landlord"]["id"])
            )
        )
        imp = _ok(api_client.complete_improvement(imp["id"], MGR))
        improvements.append(imp)
    set_clock(notice_clock)
    notice = serve_notice(ctx, "LANDLORD")
    set_clock(final_clock)
    ctx["improvements"] = [get_improvement(i["id"]) for i in improvements]
    ctx["notice"] = get_notice(notice["id"])
    ctx["lease"] = get_lease(ctx["lease"]["id"])
    ctx["field"] = get_field(ctx["field"]["id"])
    return ctx


# ---------------------------------------------------------------------------
# Tier 2: owner reports
# ---------------------------------------------------------------------------

def setup_report_scenario(
    landlord_overrides: dict | None = None,
    send: bool = False,
    **report_overrides,
) -> dict:
    """Landlord plus one DRAFT report (optionally already SENT)."""
    landlord = setup_landlord(**(landlord_overrides or {}))
    report = _ok(
        api_client.create_report(
            create_report_payload(landlord["id"], **report_overrides), MGR
        )
    )
    if send:
        report = _ok(api_client.send_report(report["id"], MGR))
    return {"landlord": landlord, "report": report}


# ---------------------------------------------------------------------------
# Tier 2: multi-tenant bidding
# ---------------------------------------------------------------------------

def setup_two_tenant_bidding_scenario(
    experience_a: int = 10, experience_b: int = 20, **offering_overrides
) -> dict:
    """One OPEN offering plus two APPROVED tenants. Returns a context with
    landlord / field / offering / tenant_a / tenant_b."""
    landlord = setup_landlord()
    tenant_a = setup_tenant(name="Tenant A", years_experience=experience_a)
    tenant_b = setup_tenant(name="Tenant B", years_experience=experience_b)
    field = setup_field(landlord["id"])
    offering = setup_offering(field["id"], **offering_overrides)
    return {
        "landlord": landlord,
        "tenant_a": tenant_a,
        "tenant_b": tenant_b,
        "field": field,
        "offering": offering,
    }
