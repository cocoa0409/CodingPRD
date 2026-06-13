"""Composite setup helpers for multi-step test prerequisites.

The harness restarts the API server (empty database) before every test, and the
bidding window is gated on a server-controlled logical clock. Every fixture
therefore (a) pins the clock to a known instant so the deadline is in the future,
and (b) builds every precondition from scratch using only PRD-declared endpoints.

Fixtures use get_success_data() (lenient validator) internally so setup failures
surface as clear "Setup failed" errors rather than confusing assertion failures.

Identity threading: after registering a Homeowner or Contractor, every
ownership-gated call uses make_homeowner_headers(homeowner["id"]) /
make_contractor_headers(contractor["id"]) — never the shared TEST_USERS constant.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .constants import (
    NOW_ISO,
    DEFAULT_BID_DEADLINE,
    DEFAULT_LICENSE_EXPIRY,
    TEST_DEFAULTS,
)
from .factories import (
    create_homeowner_payload,
    create_contractor_payload,
    create_project_payload,
    create_scope_line_item_payload,
    create_milestone_payload,
    create_bid_payload,
    create_bid_line_item_payload,
    fund_escrow_payload,
    create_draw_payload,
    create_lien_waiver_payload,
    create_change_order_payload,
    approve_change_order_payload,
    award_project_payload,
    create_dispute_payload,
    resolve_dispute_payload,
    set_clock_payload,
)
from .test_users import (
    TEST_USERS,
    make_homeowner_headers,
    make_contractor_headers,
)

_ADMIN = TEST_USERS["platform_admin_headers"]
_ESCROW = TEST_USERS["escrow_agent_headers"]
_ANON = TEST_USERS["anonymous_headers"]


# ─── Tier 0: Clock + actor registration ───────────────────────────────────
def set_clock(to_iso8601: str = NOW_ISO):
    """Pin the server's logical clock so deadline/expiry comparisons are
    deterministic. Returns the clock payload data."""
    return get_success_data(api_client.set_clock(set_clock_payload(to_iso8601), _ADMIN))


def create_homeowner(**overrides):
    """Register a Homeowner. Returns the created entity."""
    return get_success_data(api_client.create_homeowner(
        create_homeowner_payload(**overrides), _ANON))


def create_contractor(**overrides):
    """Register a Contractor (starts PENDING). Returns the created entity."""
    return get_success_data(api_client.create_contractor(
        create_contractor_payload(**overrides), _ANON))


def create_qualified_contractor(**overrides):
    """Register a contractor and qualify it (PENDING -> QUALIFIED)."""
    contractor = create_contractor(**overrides)
    return get_success_data(api_client.qualify_contractor(contractor["id"], _ADMIN))


# ─── Tier 1: DRAFT project with scope + milestones ─────────────────────────
def create_draft_project(homeowner, scope_lines=None, milestones=None, **project_overrides):
    """Create a DRAFT project owned by `homeowner`, then add scope lines and
    milestones. Returns (project, scope_line_items, milestone_records).

    scope_lines: list of payload-override dicts (defaults to one LUMP whole-job line).
    milestones:  list of payload-override dicts (defaults to one release_pct 1.0).
    """
    ho_headers = make_homeowner_headers(homeowner["id"])
    project = get_success_data(api_client.create_project(
        create_project_payload(homeowner["id"], **project_overrides), ho_headers))

    if scope_lines is None:
        scope_lines = [{}]
    if milestones is None:
        milestones = [{"sequence": 1, "release_pct": 1.0}]

    scope_records = []
    for spec in scope_lines:
        scope_records.append(get_success_data(api_client.create_scope_line_item(
            project["id"], create_scope_line_item_payload(**spec), ho_headers)))

    milestone_records = []
    for spec in milestones:
        seq = spec.get("sequence", len(milestone_records) + 1)
        pct = spec.get("release_pct", 1.0)
        extra = {k: v for k, v in spec.items() if k not in ("sequence", "release_pct")}
        milestone_records.append(get_success_data(api_client.create_milestone(
            project["id"], create_milestone_payload(sequence=seq, release_pct=pct, **extra),
            ho_headers)))

    return project, scope_records, milestone_records


def open_project(project, homeowner):
    """Open a DRAFT project for bids. Returns the opened project (carries the
    post-open version, the value award expects as expected_project_version)."""
    return get_success_data(api_client.open_project(
        project["id"], make_homeowner_headers(homeowner["id"])))


# ─── Tier 2: bids ──────────────────────────────────────────────────────────
def create_submitted_bid(project, contractor, line_specs, duration_days=None):
    """Create a bid for `project` by `contractor`, add the given priced lines,
    and submit it. Returns the submitted bid.

    line_specs: list of (scope_line_item_id, quantity, unit_price_cents) tuples.
    """
    c_headers = make_contractor_headers(contractor["id"])
    bid_payload = create_bid_payload(project["id"], contractor["id"])
    if duration_days is not None:
        bid_payload["duration_days"] = duration_days
    bid = get_success_data(api_client.create_bid(bid_payload, c_headers))
    for scope_id, qty, price in line_specs:
        api_client.create_bid_line_item(
            bid["id"],
            create_bid_line_item_payload(scope_id, quantity=qty, unit_price_cents=price),
            c_headers)
    return get_success_data(api_client.submit_bid(bid["id"], c_headers))


def create_draft_bid_with_lines(project, contractor, line_specs, duration_days=None):
    """Create a bid + priced lines but DO NOT submit. Returns the DRAFT bid."""
    c_headers = make_contractor_headers(contractor["id"])
    bid_payload = create_bid_payload(project["id"], contractor["id"])
    if duration_days is not None:
        bid_payload["duration_days"] = duration_days
    bid = get_success_data(api_client.create_bid(bid_payload, c_headers))
    for scope_id, qty, price in line_specs:
        api_client.create_bid_line_item(
            bid["id"],
            create_bid_line_item_payload(scope_id, quantity=qty, unit_price_cents=price),
            c_headers)
    return get_success_data(api_client.get_bid(bid["id"], c_headers))


# ─── Tier 3: award + escrow funding (reach IN_PROGRESS) ────────────────────
def get_project_escrow(project, homeowner):
    """Fetch the escrow created for a project at award time."""
    data, _meta = _list(api_client.list_escrows(
        make_homeowner_headers(homeowner["id"]), params={"project_id": project["id"]}))
    assert data, "Setup failed: no escrow found for awarded project"
    return data[0]


def _list(response):
    """Unwrap a paginated list response into (data, meta) leniently."""
    body = response.json()
    return body["data"], body.get("meta", {})


def award_bid(project, homeowner, winning_bid, expected_project_version):
    """Award `winning_bid` on `project`. Returns the awarded project."""
    return get_success_data(api_client.award_project(
        project["id"],
        award_project_payload(winning_bid["id"], expected_project_version),
        make_homeowner_headers(homeowner["id"])))


def fund_escrow(escrow, deposit_cents):
    """Fund escrow with the exact deposit (EscrowAgent). Returns funded escrow."""
    return get_success_data(api_client.fund_escrow(
        escrow["id"], fund_escrow_payload(deposit_cents), _ESCROW))


def setup_in_progress_project(
    contract_value_cents=600_000,
    milestones=None,
    budget_cap_cents=None,
    scope_unit_cost=None,
):
    """Full setup through IN_PROGRESS for a single-contractor project.

    Sequence: clock -> homeowner -> qualified contractor -> project (scope +
    milestones) -> open -> submit one full-coverage bid priced at
    contract_value_cents -> award -> fund escrow with contract_value_cents.

    milestones: list of {sequence, release_pct} dicts; defaults to a single
    final milestone (release_pct 1.0). The bid prices the single whole-job scope
    line at contract_value_cents so the awarded total == contract_value_cents.

    Returns a dict with keys: homeowner, contractor, project (IN_PROGRESS),
    scope (list), milestones (list), bid, escrow (FUNDED).
    """
    set_clock(NOW_ISO)
    homeowner = create_homeowner()
    contractor = create_qualified_contractor()

    if milestones is None:
        milestones = [{"sequence": 1, "release_pct": 1.0}]
    if budget_cap_cents is None:
        budget_cap_cents = max(TEST_DEFAULTS["BUDGET_CAP_CENTS"], contract_value_cents)
    unit_cost = scope_unit_cost if scope_unit_cost is not None else contract_value_cents

    project, scope, milestone_records = create_draft_project(
        homeowner,
        scope_lines=[{"description": "Whole job", "quantity": 1, "unit": "LUMP",
                      "estimated_unit_cost_cents": unit_cost}],
        milestones=milestones,
        budget_cap_cents=budget_cap_cents,
    )
    opened = open_project(project, homeowner)
    bid = create_submitted_bid(
        opened, contractor,
        line_specs=[(scope[0]["id"], 1, contract_value_cents)],
    )
    award_bid(opened, homeowner, bid, opened["version"])
    escrow = get_project_escrow(opened, homeowner)
    funded = fund_escrow(escrow, contract_value_cents)
    in_progress = get_success_data(api_client.get_project(
        opened["id"], make_homeowner_headers(homeowner["id"])))

    return {
        "homeowner": homeowner,
        "contractor": contractor,
        "project": in_progress,
        "scope": scope,
        "milestones": milestone_records,
        "bid": bid,
        "escrow": funded,
    }


# ─── Tier 4: draw pipeline shortcuts ───────────────────────────────────────
def request_draw(ctx, milestone, conditional_waiver_amount_cents):
    """Contractor requests a draw against `milestone`. Returns the REQUESTED draw."""
    c_headers = make_contractor_headers(ctx["contractor"]["id"])
    return get_success_data(api_client.create_draw(
        create_draw_payload(ctx["project"]["id"], milestone["id"],
                            conditional_waiver_amount_cents),
        c_headers))


def approve_draw(ctx, draw):
    """Homeowner approves a requested draw. Returns the APPROVED draw."""
    return get_success_data(api_client.approve_draw(
        draw["id"], make_homeowner_headers(ctx["homeowner"]["id"])))


def file_unconditional_waiver(ctx, draw, amount_cents):
    """Contractor files an UNCONDITIONAL lien waiver for a draw."""
    c_headers = make_contractor_headers(ctx["contractor"]["id"])
    return get_success_data(api_client.create_lien_waiver(
        create_lien_waiver_payload(ctx["project"]["id"], ctx["contractor"]["id"],
                                   draw["id"], amount_cents,
                                   waiver_type="UNCONDITIONAL"),
        c_headers))


def pay_draw(ctx, draw):
    """EscrowAgent pays an approved draw (after unconditional waiver). Returns PAID draw."""
    return get_success_data(api_client.pay_draw(draw["id"], _ESCROW))


def request_approve_pay_draw(ctx, milestone, net_release_cents):
    """Full draw lifecycle: request -> approve -> file unconditional waiver -> pay.
    Returns the PAID draw."""
    draw = request_draw(ctx, milestone, net_release_cents)
    approve_draw(ctx, draw)
    file_unconditional_waiver(ctx, draw, net_release_cents)
    return pay_draw(ctx, draw)


def setup_approved_draw(milestones=None, contract_value_cents=600_000):
    """IN_PROGRESS project with the first milestone's draw APPROVED (retainage
    moved to retained_cents). Returns (ctx, draw).

    Defaults to a two-milestone schedule (0.40 / 0.60) so the first draw is a
    non-final draw with non-zero retainage.
    """
    if milestones is None:
        milestones = [{"sequence": 1, "release_pct": 0.40},
                      {"sequence": 2, "release_pct": 0.60}]
    ctx = setup_in_progress_project(
        contract_value_cents=contract_value_cents, milestones=milestones)
    m1 = ctx["milestones"][0]
    gross = round_half_up(contract_value_cents * m1["release_pct"])
    retainage = round_half_up(gross * 0.10)
    net = gross - retainage
    draw = request_draw(ctx, m1, net)
    approved = approve_draw(ctx, draw)
    return ctx, approved


def setup_disputed_draw(contract_value_cents=600_000):
    """IN_PROGRESS project, first (non-final) draw APPROVED then disputed (OPEN).
    Returns (ctx, draw, dispute). Project is DISPUTED, draw DISPUTED."""
    ctx, draw = setup_approved_draw(contract_value_cents=contract_value_cents)
    dispute = get_success_data(api_client.create_dispute(
        create_dispute_payload(ctx["project"]["id"], draw["id"], raised_by="HOMEOWNER"),
        make_homeowner_headers(ctx["homeowner"]["id"])))
    return ctx, draw, dispute


# ─── Tier 5: change orders ─────────────────────────────────────────────────
def propose_change_order(ctx, delta_cents):
    """Homeowner proposes a change order against the awarded bid. Returns it."""
    return get_success_data(api_client.create_change_order(
        create_change_order_payload(ctx["project"]["id"], ctx["bid"]["id"], delta_cents),
        make_homeowner_headers(ctx["homeowner"]["id"])))


def current_bid_version(ctx):
    """Read the awarded bid's current version (for OCC change-order approval)."""
    bid = get_success_data(api_client.get_bid(
        ctx["bid"]["id"], make_homeowner_headers(ctx["homeowner"]["id"])))
    return bid["version"]


def approve_change_order(ctx, change_order, expected_bid_version):
    """Homeowner approves a change order with an OCC bid version. Returns it."""
    return get_success_data(api_client.approve_change_order(
        change_order["id"], approve_change_order_payload(expected_bid_version),
        make_homeowner_headers(ctx["homeowner"]["id"])))


# ─── Numeric helper (mirrors PRD round-half-up) ────────────────────────────
def round_half_up(value) -> int:
    """Round a (possibly fractional) cent product to whole cents, half-up.

    Mirrors PRD 2.5: a value whose fractional part is exactly one half is rounded
    up to the next whole cent. Implemented via Decimal to avoid float error at
    the .5 boundary.
    """
    from decimal import Decimal, ROUND_HALF_UP
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
