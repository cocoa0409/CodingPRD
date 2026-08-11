"""Composite setup helpers.

Every helper builds preconditions from scratch using only PRD-declared
endpoints (the harness restarts the server before every test, so each test
starts against an empty database). Setup calls use the lenient
get_success_data() validator so failures surface as clear setup errors.

Identity threading: GCVendor calls always carry the acting Contractor.id via
make_gc_vendor_headers(); change-order proposals pin proposed_by_user_id via
make_site_superintendent_headers(proposer_user_id); approvals pin the approver
identity explicitly.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import CLOCK_START_ISO
from .factories import (
    create_bid_package_payload,
    create_bid_payload,
    create_change_order_payload,
    create_contractor_payload,
    create_drawing_set_payload,
    create_market_payload,
    create_municipality_profile_payload,
    create_permit_payload,
    create_program_payload,
    create_punch_item_payload,
    create_site_payload,
    create_turnover_payload,
    create_vendor_mobilization_payload,
)
from .test_users import (
    TEST_USERS,
    make_finance_controller_headers,
    make_gc_vendor_headers,
    make_operations_lead_headers,
    make_program_director_headers,
    make_site_superintendent_headers,
)

DIRECTOR = TEST_USERS["program_director_headers"]
DESIGN = TEST_USERS["design_manager_headers"]
PERMIT = TEST_USERS["permit_coordinator_headers"]
PROCUREMENT = TEST_USERS["procurement_lead_headers"]
SUPER = TEST_USERS["site_superintendent_headers"]
OPS = TEST_USERS["operations_lead_headers"]
FINANCE = TEST_USERS["finance_controller_headers"]


# ---------------------------------------------------------------------------
# Primitive steps (each validates success and returns the resource dict)
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str = CLOCK_START_ISO) -> None:
    resp = api_client.set_clock(to_iso8601, headers=DIRECTOR)
    get_success_data(resp)


def create_program(activate: bool = False, **overrides) -> dict:
    program = get_success_data(
        api_client.create_program(create_program_payload(**overrides), headers=DIRECTOR))
    if activate:
        program = get_success_data(api_client.activate_program(program["id"], headers=DIRECTOR))
    return program


def create_market(program_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_market(create_market_payload(program_id, **overrides), headers=DIRECTOR))


def create_municipality_profile(**overrides) -> dict:
    return get_success_data(
        api_client.create_municipality_profile(
            create_municipality_profile_payload(**overrides), headers=PERMIT))


def create_site(program_id: str, market_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_site(create_site_payload(program_id, market_id, **overrides),
                               headers=DIRECTOR))


def create_drawing_set(program_id: str, submit: bool = False, approve: bool = False,
                       **overrides) -> dict:
    ds = get_success_data(
        api_client.create_drawing_set(create_drawing_set_payload(program_id, **overrides),
                                      headers=DESIGN))
    if submit or approve:
        ds = get_success_data(api_client.submit_drawing_set(ds["id"], headers=DESIGN))
    if approve:
        ds = get_success_data(api_client.approve_drawing_set(ds["id"], headers=DESIGN))
    return ds


def create_approved_drawing_set(program_id: str, **overrides) -> dict:
    return create_drawing_set(program_id, approve=True, **overrides)


def advance_site_to_design(site_id: str) -> dict:
    return get_success_data(api_client.advance_site_design(site_id, headers=DESIGN))


def submit_site_design(site_id: str) -> dict:
    return get_success_data(api_client.submit_site_design(site_id, headers=DESIGN))


def create_permit(site_id: str, drawing_set_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_permit(create_permit_payload(site_id, drawing_set_id, **overrides),
                                 headers=PERMIT))


def file_permit(permit_id: str) -> dict:
    return get_success_data(api_client.file_permit(permit_id, headers=PERMIT))


def start_permit_review(permit_id: str) -> dict:
    return get_success_data(api_client.start_permit_review(permit_id, headers=PERMIT))


def issue_permit(permit_id: str) -> dict:
    return get_success_data(api_client.issue_permit(permit_id, headers=PERMIT))


def create_issued_permit(site_id: str, drawing_set_id: str, **overrides) -> dict:
    permit = create_permit(site_id, drawing_set_id, **overrides)
    permit = file_permit(permit["id"])
    permit = start_permit_review(permit["id"])
    permit = issue_permit(permit["id"])
    return permit


def mark_site_permitted(site_id: str) -> dict:
    return get_success_data(api_client.mark_site_permitted(site_id, headers=PERMIT))


def open_market_bidding(market_id: str) -> dict:
    return get_success_data(api_client.open_market_bidding(market_id, headers=PROCUREMENT))


def create_bid_package(market_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_bid_package(create_bid_package_payload(market_id, **overrides),
                                      headers=PROCUREMENT))


def open_bid_package(bid_package_id: str) -> dict:
    return get_success_data(api_client.open_bid_package(bid_package_id, headers=PROCUREMENT))


def create_contractor(**overrides) -> dict:
    return get_success_data(
        api_client.create_contractor(create_contractor_payload(**overrides), headers=PROCUREMENT))


def submit_bid(bid_package_id: str, contractor_id: str, **overrides):
    """Raw response: bid submission is ownership-gated, so the GCVendor header
    always carries the acting contractor's id."""
    return api_client.create_bid(
        create_bid_payload(bid_package_id, contractor_id, **overrides),
        headers=make_gc_vendor_headers(contractor_id))


def submit_bid_ok(bid_package_id: str, contractor_id: str, **overrides) -> dict:
    return get_success_data(submit_bid(bid_package_id, contractor_id, **overrides))


def award_open_package(bid_package_id: str,
                       close_clock: str = "2026-05-10T00:00:00Z") -> dict:
    """Advance the clock to the close instant, close, and award. Returns the
    awarded package."""
    set_clock(close_clock)
    get_success_data(api_client.close_bid_package(bid_package_id, headers=PROCUREMENT))
    return get_success_data(api_client.award_bid_package(bid_package_id, headers=PROCUREMENT))


def propose_change_order(site_id: str, amount_cents: int, cost_category: str = "SCOPE",
                         description: str = "Change order",
                         proposer_user_id: str = "sup-1") -> dict:
    return get_success_data(
        api_client.create_change_order(
            create_change_order_payload(site_id, amount_cents=amount_cents,
                                        cost_category=cost_category, description=description),
            headers=make_site_superintendent_headers(proposer_user_id)))


def approve_change_order_now(change_order_id: str, site_id: str,
                             role: str = "FinanceController",
                             approver_user_id: str = "fin-1"):
    """Raw response: reads the site's current version and submits the approval
    against it. Caller decides success/error validation."""
    version = read_site(site_id)["version"]
    if role == "ProgramDirector":
        headers = make_program_director_headers(approver_user_id)
    else:
        headers = make_finance_controller_headers(approver_user_id)
    return api_client.approve_change_order(
        change_order_id, {"expected_site_version": version}, headers=headers)


def create_vendor_mobilization(site_id: str, vendor_type: str = "FIXTURE",
                               vendor_name: str = "Fixtures R Us",
                               planned_start_on: str = "2026-06-01",
                               planned_end_on: str = "2026-06-21") -> dict:
    return get_success_data(
        api_client.create_vendor_mobilization(
            create_vendor_mobilization_payload(
                site_id, vendor_type=vendor_type, vendor_name=vendor_name,
                planned_start_on=planned_start_on, planned_end_on=planned_end_on),
            headers=SUPER))


def schedule_mobilization_ok(mobilization_id: str) -> dict:
    return get_success_data(api_client.schedule_mobilization(mobilization_id, headers=SUPER))


def complete_vendor_window(site_id: str, vendor_type: str, planned_start_on: str,
                           planned_end_on: str, arrive_on: str,
                           vendor_name: str = None) -> dict:
    """Create + schedule + arrive + complete one vendor window. Clock is moved
    to arrive_on before arrival. Returns the COMPLETE mobilization."""
    mob = create_vendor_mobilization(
        site_id, vendor_type=vendor_type, vendor_name=vendor_name or f"{vendor_type} Co",
        planned_start_on=planned_start_on, planned_end_on=planned_end_on)
    schedule_mobilization_ok(mob["id"])
    set_clock(f"{arrive_on}T00:00:00Z")
    get_success_data(api_client.arrive_mobilization(mob["id"], headers=SUPER))
    return get_success_data(api_client.complete_mobilization(mob["id"], headers=SUPER))


def create_punch_item(site_id: str, severity: str = "MINOR",
                      description: str = "Deficiency") -> dict:
    return get_success_data(
        api_client.create_punch_item(
            create_punch_item_payload(site_id, severity=severity, description=description),
            headers=SUPER))


def request_turnover_ok(site_id: str) -> dict:
    return get_success_data(
        api_client.create_turnover(create_turnover_payload(site_id), headers=SUPER))


def accept_turnover_now(turnover_id: str, site_id: str, waive_open_minor=None):
    """Raw response: reads the site's current version and accepts against it."""
    version = read_site(site_id)["version"]
    payload = {"expected_site_version": version}
    if waive_open_minor is not None:
        payload["waive_open_minor"] = waive_open_minor
    return api_client.accept_turnover(turnover_id, payload, headers=OPS)


def open_site_ok(site_id: str) -> dict:
    return get_success_data(api_client.open_site(site_id, headers=OPS))


# ---------------------------------------------------------------------------
# Readers (lenient; for fixtures and assertions)
# ---------------------------------------------------------------------------

def read_site(site_id: str) -> dict:
    return get_success_data(api_client.get_site(site_id, headers=DIRECTOR))


def read_program(program_id: str) -> dict:
    return get_success_data(api_client.get_program(program_id, headers=DIRECTOR))


def read_market(market_id: str) -> dict:
    return get_success_data(api_client.get_market(market_id, headers=DIRECTOR))


def read_permit(permit_id: str) -> dict:
    return get_success_data(api_client.get_permit(permit_id, headers=DIRECTOR))


def read_change_order(change_order_id: str) -> dict:
    return get_success_data(api_client.get_change_order(change_order_id, headers=DIRECTOR))


def read_punch_item(punch_item_id: str) -> dict:
    return get_success_data(api_client.get_punch_item(punch_item_id, headers=DIRECTOR))


def read_turnover(turnover_id: str) -> dict:
    return get_success_data(api_client.get_turnover(turnover_id, headers=DIRECTOR))


def read_mobilization(mobilization_id: str) -> dict:
    return get_success_data(
        api_client.get_vendor_mobilization(mobilization_id, headers=DIRECTOR))


def read_bid(bid_id: str) -> dict:
    return get_success_data(api_client.get_bid(bid_id, headers=DIRECTOR))


def read_bid_package(bid_package_id: str) -> dict:
    return get_success_data(api_client.get_bid_package(bid_package_id, headers=DIRECTOR))


def read_commitment_for_site(site_id: str) -> dict:
    """Return the site's single opening commitment (exactly one per site)."""
    data = get_success_data(
        api_client.list_opening_commitments(headers=DIRECTOR, params={"site_id": site_id}))
    assert isinstance(data, list) and len(data) == 1, (
        f"expected exactly one opening commitment for site {site_id}, got {data}")
    return data[0]


def recalculate_commitment(commitment_id: str) -> dict:
    return get_success_data(
        api_client.recalculate_opening_commitment(commitment_id, headers=DIRECTOR))


# ---------------------------------------------------------------------------
# Composite scenario builders
# ---------------------------------------------------------------------------

def setup_program_with_market(activate: bool = True, pool: int = 5_000_000,
                              crews: int = 2, market_name: str = "DFW") -> dict:
    """Program (ACTIVE by default) + one market. Returns ctx dict."""
    set_clock()
    program = create_program(activate=activate, contingency_pool_cents=pool)
    market = create_market(program["id"], name=market_name,
                           max_concurrent_vendor_crews=crews)
    return {"program": program, "market": market}


def setup_site_in_design(with_drawing_submitted: bool = False,
                         jurisdiction_code: str = "TX-DAL",
                         pool: int = 5_000_000, crews: int = 2,
                         **site_overrides) -> dict:
    """Program ACTIVE + market + site advanced to DESIGN. Optionally a drawing
    set left in SUBMITTED for the given jurisdiction."""
    ctx = setup_program_with_market(pool=pool, crews=crews)
    site = create_site(ctx["program"]["id"], ctx["market"]["id"],
                       municipality_code=jurisdiction_code, **site_overrides)
    ctx["site"] = site
    if with_drawing_submitted:
        ctx["ds"] = create_drawing_set(ctx["program"]["id"],
                                       jurisdiction_code=jurisdiction_code, submit=True)
    advance_site_to_design(site["id"])
    ctx["site"] = read_site(site["id"])
    return ctx


def setup_site_in_permitting(profile: bool = True, approved_drawing: bool = True,
                             municipality_code: str = "TX-DAL",
                             profile_overrides: dict = None,
                             pool: int = 5_000_000, crews: int = 2,
                             **site_overrides) -> dict:
    """Site walked to PERMITTING (approved drawing for the site municipality)."""
    ctx = setup_program_with_market(pool=pool, crews=crews)
    if profile:
        ctx["profile"] = create_municipality_profile(
            municipality_code=municipality_code, **(profile_overrides or {}))
    site = create_site(ctx["program"]["id"], ctx["market"]["id"],
                       municipality_code=municipality_code, **site_overrides)
    ctx["site"] = site
    if approved_drawing:
        ctx["ds"] = create_approved_drawing_set(ctx["program"]["id"],
                                                jurisdiction_code=municipality_code)
        advance_site_to_design(site["id"])
        submit_site_design(site["id"])
        ctx["site"] = read_site(site["id"])
    return ctx


def setup_site_mobilized(pool: int = 5_000_000, crews: int = 2,
                         **kwargs) -> dict:
    """Site walked to MOBILIZED (ISSUED BUILDING permit + mark-permitted)."""
    ctx = setup_site_in_permitting(pool=pool, crews=crews, **kwargs)
    permit = create_issued_permit(ctx["site"]["id"], ctx["ds"]["id"])
    ctx["permit"] = permit
    mark_site_permitted(ctx["site"]["id"])
    ctx["site"] = read_site(ctx["site"]["id"])
    return ctx


def setup_awarded_site(bid_amount_cents: int = 9_000_000,
                       evaluation_mode: str = "LOWEST_PRICE",
                       crews: int = 2, pool: int = 5_000_000,
                       **site_overrides) -> dict:
    """Full chain: site MOBILIZED, then market BIDDING -> package OPEN -> one
    contractor bid -> close -> award. Site gains base_contract_cents from the
    award; market ends AWARDED. Site remains MOBILIZED (build not started)."""
    ctx = setup_site_mobilized(pool=pool, crews=crews, **site_overrides)
    ctx["program"] = read_program(ctx["program"]["id"])
    open_market_bidding(ctx["market"]["id"])
    ctx["market"] = read_market(ctx["market"]["id"])
    pkg = create_bid_package(ctx["market"]["id"], evaluation_mode=evaluation_mode)
    open_bid_package(pkg["id"])
    contractor = create_contractor()
    bid = submit_bid_ok(pkg["id"], contractor["id"], amount_cents=bid_amount_cents)
    pkg = award_open_package(pkg["id"])
    ctx.update({"pkg": pkg, "contractor": contractor, "bid": bid})
    ctx["market"] = read_market(ctx["market"]["id"])
    ctx["site"] = read_site(ctx["site"]["id"])
    ctx["program"] = read_program(ctx["program"]["id"])
    return ctx


def setup_site_in_build(**kwargs) -> dict:
    """Awarded site walked into IN_BUILD."""
    ctx = setup_awarded_site(**kwargs)
    get_success_data(api_client.start_site_build(ctx["site"]["id"], headers=SUPER))
    ctx["site"] = read_site(ctx["site"]["id"])
    return ctx


def setup_site_in_punch(**kwargs) -> dict:
    """Site IN_BUILD with all three vendor types COMPLETE -> auto PUNCH.
    Uses adjacent one-day windows so half-open semantics and crew capacity
    never interfere. Clock ends at 2026-05-13."""
    ctx = setup_site_in_build(**kwargs)
    site_id = ctx["site"]["id"]
    ctx["vfix"] = complete_vendor_window(site_id, "FIXTURE", "2026-05-11", "2026-05-12",
                                         "2026-05-11", vendor_name="Fixtures R Us")
    ctx["vit"] = complete_vendor_window(site_id, "IT", "2026-05-12", "2026-05-13",
                                        "2026-05-12", vendor_name="NetCabling Co")
    ctx["vsig"] = complete_vendor_window(site_id, "SIGNAGE", "2026-05-13", "2026-05-14",
                                         "2026-05-13", vendor_name="SignPros")
    ctx["site"] = read_site(site_id)
    return ctx


def setup_site_in_turnover(**kwargs) -> dict:
    """Site in TURNOVER with a REQUESTED turnover (no open punch items)."""
    ctx = setup_site_in_punch(**kwargs)
    turnover = request_turnover_ok(ctx["site"]["id"])
    ctx["turnover"] = turnover
    ctx["site"] = read_site(ctx["site"]["id"])
    return ctx


def setup_site_open(**kwargs) -> dict:
    """Full lifecycle through OPEN: turnover accepted then site opened."""
    ctx = setup_site_in_turnover(**kwargs)
    resp = accept_turnover_now(ctx["turnover"]["id"], ctx["site"]["id"])
    ctx["turnover"] = get_success_data(resp)
    open_site_ok(ctx["site"]["id"])
    ctx["site"] = read_site(ctx["site"]["id"])
    return ctx


# ---------------------------------------------------------------------------
# Multi-site scenario builders (market crew-day capacity scenarios)
# ---------------------------------------------------------------------------

def walk_site_to_mobilized(site_id: str, drawing_set_id: str) -> dict:
    """advance-design -> submit-design -> issue BUILDING permit ->
    mark-permitted. Assumes an APPROVED drawing set for the site's
    municipality and a registered municipality profile already exist."""
    advance_site_to_design(site_id)
    submit_site_design(site_id)
    create_issued_permit(site_id, drawing_set_id)
    mark_site_permitted(site_id)
    return read_site(site_id)


def award_market(market_id: str, phase_wave: int = 1,
                 amount_cents: int = 9_000_000,
                 evaluation_mode: str = "LOWEST_PRICE") -> dict:
    """open-bidding + package + open + one contractor bid + close/award."""
    open_market_bidding(market_id)
    pkg = create_bid_package(market_id, phase_wave=phase_wave,
                             evaluation_mode=evaluation_mode)
    open_bid_package(pkg["id"])
    contractor = create_contractor()
    bid = submit_bid_ok(pkg["id"], contractor["id"], amount_cents=amount_cents)
    pkg = award_open_package(pkg["id"])
    return {"pkg": pkg, "contractor": contractor, "bid": bid}


def setup_multi_sites_in_build(site_count: int = 2, crews: int = 2,
                               pool: int = 5_000_000, **site_overrides) -> dict:
    """One ACTIVE program, one market, N sites all walked to IN_BUILD through
    a single wave-1 award. Returns ctx with a `sites` list."""
    set_clock()
    program = create_program(activate=True, contingency_pool_cents=pool)
    market = create_market(program["id"], max_concurrent_vendor_crews=crews)
    profile = create_municipality_profile()
    ds = create_approved_drawing_set(program["id"], jurisdiction_code="TX-DAL")
    sites = []
    for i in range(site_count):
        site = create_site(program["id"], market["id"],
                           address=f"{100 + i * 100} Site Rd", **site_overrides)
        walk_site_to_mobilized(site["id"], ds["id"])
        sites.append(site["id"])
    award = award_market(market["id"])
    for site_id in sites:
        get_success_data(api_client.start_site_build(site_id, headers=SUPER))
    sites = [read_site(site_id) for site_id in sites]
    ctx = {"program": read_program(program["id"]),
           "market": read_market(market["id"]),
           "profile": profile, "ds": ds, "sites": sites}
    ctx.update(award)
    return ctx

