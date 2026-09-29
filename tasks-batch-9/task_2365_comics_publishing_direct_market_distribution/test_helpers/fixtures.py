"""Composite state builders.

The harness restarts the server before every test, so every test begins against
an empty database and must build the state it needs through the API. These
helpers do exactly that, using only endpoints the PRD declares.

Each helper uses `get_success_data`, which accepts any 2xx and raises a clear
setup-failure message otherwise, so a broken setup step never masquerades as a
failed assertion.

Identity is threaded explicitly: helpers that act on behalf of a creator or a
retailer take that entity's `id` and build per-instance headers from it, because
`X-User-ID` for those two roles is the entity's own identifier.
"""

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import api_client
from .constants import DEFAULT_CLOCK, REQUIRED_CRAFTS
from .test_users import TEST_USERS, make_creator_headers, make_retailer_headers

EIC = TEST_USERS["editor_in_chief_headers"]
ME = TEST_USERS["managing_editor_headers"]
SD = TEST_USERS["sales_director_headers"]
RA = TEST_USERS["royalty_accountant_headers"]
RA2 = TEST_USERS["royalty_accountant_2_headers"]


# ─── Logical clock ────────────────────────────────────

def set_clock(to_iso8601: str = DEFAULT_CLOCK, headers=None) -> dict:
    """Set the logical UTC clock that every temporal rule reads."""
    return get_success_data(
        api_client.set_current_utc(f.clock_payload(to_iso8601), headers or SD)
    )


# ─── Reads ────────────────────────────────────────────

def read_creator(creator_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_creator(creator_id, headers or EIC))


def read_title(title_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_title(title_id, headers or EIC))


def read_assignment(assignment_id: str, headers=None) -> dict:
    return get_success_data(
        api_client.get_creative_assignment(assignment_id, headers or EIC)
    )


def read_issue(issue_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_issue(issue_id, headers or ME))


def read_stage(stage_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_production_stage(stage_id, headers or ME))


def read_catalog(catalog_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_catalog(catalog_id, headers or SD))


def read_solicitation(solicitation_id: str, headers=None) -> dict:
    return get_success_data(
        api_client.get_solicitation(solicitation_id, headers or SD)
    )


def read_retailer(retailer_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_retailer(retailer_id, headers or SD))


def read_order(order_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_retailer_order(order_id, headers or SD))


def read_print_run(print_run_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_print_run(print_run_id, headers or ME))


def read_statement(statement_id: str, headers=None) -> dict:
    return get_success_data(
        api_client.get_royalty_statement(statement_id, headers or RA)
    )


def title_version(title_id: str) -> int:
    """The title's current `version`, for the `expected_title_version` field."""
    return read_title(title_id)["version"]


def issue_version(issue_id: str) -> int:
    """The issue's current `version`, for the `expected_issue_version` field."""
    return read_issue(issue_id)["version"]


# ─── Creators ─────────────────────────────────────────

def register_creator(**overrides) -> dict:
    return get_success_data(
        api_client.create_creator(f.creator_payload(**overrides), EIC)
    )


def register_all_craft_creator(full_name: str = "Ada Allrounder", **overrides) -> dict:
    """A creator who declares every craft, so one person can fill a whole board."""
    payload = {
        "full_name": full_name,
        "crafts": list(REQUIRED_CRAFTS) + ["COVER"],
        "default_page_rate_cents": 10000,
    }
    payload.update(overrides)
    return register_creator(**payload)


# ─── Titles ───────────────────────────────────────────

def pitch_title(**overrides) -> dict:
    return get_success_data(api_client.create_title(f.title_payload(**overrides), EIC))


def greenlight(title_id: str) -> dict:
    return get_success_data(api_client.greenlight_title(title_id, EIC))


def pitch_and_greenlight_title(**overrides) -> dict:
    title = pitch_title(**overrides)
    return greenlight(title["id"])


# ─── Creative assignments ─────────────────────────────

def offer_assignment(title_id: str, creator_id: str, craft: str = "SCRIPT", **overrides) -> dict:
    """Offer an assignment, reading the title's live `version` for §2.9."""
    payload = f.assignment_payload(
        creator_id, title_version(title_id), craft=craft, **overrides
    )
    return get_success_data(
        api_client.create_creative_assignment(title_id, payload, EIC)
    )


def accept_assignment(assignment_id: str, creator_id: str) -> dict:
    """Acceptance is the named creator's own act."""
    return get_success_data(
        api_client.accept_creative_assignment(
            assignment_id, make_creator_headers(creator_id)
        )
    )


def offer_and_accept_assignment(
    title_id: str, creator_id: str, craft: str = "SCRIPT", **overrides
) -> dict:
    assignment = offer_assignment(title_id, creator_id, craft=craft, **overrides)
    return accept_assignment(assignment["id"], creator_id)


def counter_assignment(assignment_id: str, creator_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.counter_creative_assignment(
            assignment_id, f.counter_payload(**overrides), make_creator_headers(creator_id)
        )
    )


def repropose_assignment(assignment_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.repropose_creative_assignment(
            assignment_id, f.repropose_payload(**overrides), EIC
        )
    )


def terminate_assignment(assignment_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.terminate_creative_assignment(
            assignment_id, f.terminate_payload(**overrides), EIC
        )
    )


# ─── Issues ───────────────────────────────────────────

def schedule_issue(title_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_issue(title_id, f.issue_payload(**overrides), ME)
    )


# ─── Production stages ────────────────────────────────

def book_stage(issue_id: str, assignment_id: str, craft: str = "SCRIPT", **overrides) -> dict:
    payload = f.stage_payload(assignment_id, craft=craft, **overrides)
    return get_success_data(
        api_client.create_production_stage(issue_id, payload, ME)
    )


def start_stage(stage_id: str, creator_id: str) -> dict:
    return get_success_data(
        api_client.start_production_stage(stage_id, make_creator_headers(creator_id))
    )


def deliver_stage(stage_id: str, creator_id: str, delivered_pages: int = None) -> dict:
    payload = f.deliver_payload(
        **({} if delivered_pages is None else {"delivered_pages": delivered_pages})
    )
    return get_success_data(
        api_client.deliver_production_stage(
            stage_id, payload, make_creator_headers(creator_id)
        )
    )


def kick_back_stage(stage_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.kick_back_production_stage(stage_id, f.kick_back_payload(**overrides), ME)
    )


def approve_stage(stage_id: str) -> dict:
    return get_success_data(api_client.approve_production_stage(stage_id, ME))


def run_stage_to_approved(
    issue_id: str,
    assignment_id: str,
    creator_id: str,
    craft: str = "SCRIPT",
    delivered_pages: int = None,
    **stage_overrides,
) -> dict:
    """Book, start, deliver and approve one stage; returns the approved stage."""
    stage = book_stage(issue_id, assignment_id, craft=craft, **stage_overrides)
    start_stage(stage["id"], creator_id)
    deliver_stage(stage["id"], creator_id, delivered_pages)
    return approve_stage(stage["id"])


# ─── Variant covers ───────────────────────────────────

DEFAULT_COVER_SPECS = (
    {"code": "A", "kind": "STANDARD", "cover_price_cents": 399},
    {"code": "B", "kind": "RATIO_INCENTIVE", "incentive_ratio": 10, "cover_price_cents": 399},
    {
        "code": "C",
        "kind": "RATIO_INCENTIVE",
        "incentive_ratio": 25,
        "cover_price_cents": 599,
        "allocation_cap": 4,
    },
)

EXCLUSIVE_COVER_SPEC = {
    "code": "D",
    "kind": "RETAILER_EXCLUSIVE",
    "cover_price_cents": 999,
    "allocation_cap": 2,
}


def add_cover(issue_id: str, **payload) -> dict:
    return get_success_data(api_client.create_variant_cover(issue_id, payload, SD))


def add_covers(issue_id: str, specs=DEFAULT_COVER_SPECS) -> dict:
    """Add several covers; returns them keyed by their `code`."""
    return {spec["code"]: add_cover(issue_id, **dict(spec)) for spec in specs}


# ─── Catalogs and solicitations ───────────────────────

def open_catalog(**overrides) -> dict:
    return get_success_data(api_client.create_catalog(f.catalog_payload(**overrides), SD))


def draft_solicitation(catalog_id: str, issue_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_solicitation(
            catalog_id, f.solicitation_payload(issue_id, **overrides), ME
        )
    )


def submit_solicitation(solicitation_id: str) -> dict:
    return get_success_data(api_client.submit_solicitation(solicitation_id, ME))


def lock_catalog(catalog_id: str) -> dict:
    return get_success_data(api_client.lock_catalog(catalog_id, SD))


def accept_solicitation(solicitation_id: str) -> dict:
    return get_success_data(api_client.accept_solicitation(solicitation_id, SD))


def withdraw_solicitation(solicitation_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.withdraw_solicitation(solicitation_id, f.withdraw_payload(**overrides), SD)
    )


def publish_catalog(catalog_id: str) -> dict:
    return get_success_data(api_client.publish_catalog(catalog_id, SD))


# ─── Retailers ────────────────────────────────────────

def open_retailer(**overrides) -> dict:
    return get_success_data(api_client.create_retailer(f.retailer_payload(**overrides), SD))


def suspend_retailer(retailer_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.suspend_retailer(retailer_id, f.suspend_payload(**overrides), SD)
    )


def reinstate_retailer(retailer_id: str) -> dict:
    return get_success_data(api_client.reinstate_retailer(retailer_id, SD))


# ─── Retailer orders ──────────────────────────────────

def draft_order(retailer_id: str, issue_id: str, **overrides) -> dict:
    """A retailer drafts an order for itself, so `retailer_id` is also its identity."""
    return get_success_data(
        api_client.create_retailer_order(
            f.order_payload(retailer_id, issue_id, **overrides),
            make_retailer_headers(retailer_id),
        )
    )


def submit_order(order_id: str, retailer_id: str) -> dict:
    return get_success_data(
        api_client.submit_retailer_order(order_id, make_retailer_headers(retailer_id))
    )


def draft_and_submit_order(retailer_id: str, issue_id: str, **overrides) -> dict:
    order = draft_order(retailer_id, issue_id, **overrides)
    return submit_order(order["id"], retailer_id)


def adjust_order(order_id: str, retailer_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.adjust_retailer_order(
            order_id, f.adjust_payload(**overrides), make_retailer_headers(retailer_id)
        )
    )


def foc_lock(issue_id: str) -> dict:
    return get_success_data(api_client.foc_lock_issue(issue_id, SD))


def invoice_order(order_id: str) -> dict:
    return get_success_data(api_client.invoice_retailer_order(order_id, SD))


def ship_order(order_id: str) -> dict:
    return get_success_data(api_client.ship_retailer_order(order_id, SD))


def cancel_order(order_id: str, headers=None, **overrides) -> dict:
    return get_success_data(
        api_client.cancel_retailer_order(order_id, f.order_cancel_payload(**overrides), headers or SD)
    )


# ─── Print runs, release and downstream windows ───────

def plan_print_run(issue_id: str, basis: str = "ORDER_DRIVEN", **overrides) -> dict:
    """Plan a printing, reading the issue's live `version` for §2.9."""
    payload = f.print_run_payload(issue_version(issue_id), basis=basis, **overrides)
    return get_success_data(api_client.create_print_run(issue_id, payload, ME))


def complete_print_run(print_run_id: str) -> dict:
    return get_success_data(api_client.complete_print_run(print_run_id, ME))


def plan_and_complete_print_run(issue_id: str, basis: str = "ORDER_DRIVEN", **overrides) -> dict:
    run = plan_print_run(issue_id, basis=basis, **overrides)
    return complete_print_run(run["id"])


def release_issue(issue_id: str) -> dict:
    return get_success_data(api_client.release_issue(issue_id, SD))


def add_release_window(issue_id: str, channel: str, release_date: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_release_window(
            issue_id, f.release_window_payload(channel, release_date, **overrides), SD
        )
    )


# ─── Revenue and royalty ──────────────────────────────

def post_revenue_event(issue_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_revenue_event(f.revenue_event_payload(issue_id, **overrides), RA)
    )


def create_statement(title_id: str, creator_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_royalty_statement(
            f.statement_payload(title_id, creator_id, **overrides), RA
        )
    )


def issue_statement(statement_id: str, headers=None) -> dict:
    return get_success_data(api_client.issue_royalty_statement(statement_id, headers or RA))


def pay_statement(statement_id: str, headers=None, **overrides) -> dict:
    return get_success_data(
        api_client.pay_royalty_statement(statement_id, f.pay_payload(**overrides), headers or RA2)
    )


def reverse_statement(statement_id: str, headers=None, **overrides) -> dict:
    return get_success_data(
        api_client.reverse_royalty_statement(
            statement_id, f.reverse_payload(**overrides), headers or RA
        )
    )


# ═══════════════════════════════════════════════════════
# Composite state builders
# ═══════════════════════════════════════════════════════

def setup_greenlit_title_with_script_assignment(
    accept: bool = True,
    creator_overrides: dict = None,
    title_overrides: dict = None,
    assignment_overrides: dict = None,
) -> dict:
    """A greenlit title staffed with one `SCRIPT` assignment.

    Returns `creator`, `title` (as read after staffing) and `assignment`.
    """
    set_clock()
    creator = register_creator(**(creator_overrides or {}))
    title = pitch_and_greenlight_title(**(title_overrides or {}))
    assignment = offer_assignment(
        title["id"], creator["id"], "SCRIPT", **(assignment_overrides or {})
    )
    if accept:
        assignment = accept_assignment(assignment["id"], creator["id"])
    return {
        "creator": creator,
        "creator_headers": make_creator_headers(creator["id"]),
        "title": read_title(title["id"]),
        "assignment": assignment,
    }


def setup_issue_in_scripting(
    start_stage_work: bool = True,
    creator_overrides: dict = None,
    title_overrides: dict = None,
    assignment_overrides: dict = None,
    issue_overrides: dict = None,
    stage_overrides: dict = None,
) -> dict:
    """A greenlit title with one issue carrying one booked `SCRIPT` stage.

    With `start_stage_work` the stage is `IN_PROGRESS`, so the issue's
    production dimension is `SCRIPTING` and it is solicitable.
    """
    state = setup_greenlit_title_with_script_assignment(
        creator_overrides=creator_overrides,
        title_overrides=title_overrides,
        assignment_overrides=assignment_overrides,
    )
    issue = schedule_issue(state["title"]["id"], **(issue_overrides or {}))
    stage = book_stage(
        issue["id"], state["assignment"]["id"], "SCRIPT", **(stage_overrides or {})
    )
    if start_stage_work:
        stage = start_stage(stage["id"], state["creator"]["id"])
    state.update({"issue": read_issue(issue["id"]), "stage": stage})
    return state


ADJACENT_BOOKINGS = {
    "SCRIPT": ("2026-08-01", "2026-08-05"),
    "PENCILS": ("2026-08-05", "2026-08-10"),
    "INKS": ("2026-08-10", "2026-08-15"),
    "COLORS": ("2026-08-15", "2026-08-20"),
    "LETTERS": ("2026-08-20", "2026-08-25"),
}


CAMERA_READY_SHARES = {
    "SCRIPT": 5000,
    "PENCILS": 1500,
    "INKS": 800,
    "COLORS": 700,
    "LETTERS": 500,
}


def setup_camera_ready_issue(
    title_overrides: dict = None,
    issue_overrides: dict = None,
    assignment_overrides: dict = None,
    royalty_shares: dict = None,
    planned_due_date: str = "2026-08-21",
    delivery_clock: str = "2026-08-19T00:00:00Z",
) -> dict:
    """One issue whose five required-craft stages are all `APPROVED`.

    One creator declaring every craft holds five back-to-back bookings, whose
    half-open windows merely touch and so never intersect. The five shares sum
    to 8500 bps, exactly the pool budget a default title leaves once its 1500
    bps of cover participation is reserved.
    """
    shares = dict(royalty_shares or CAMERA_READY_SHARES)
    set_clock()
    creator = register_all_craft_creator()
    title = pitch_and_greenlight_title(**(title_overrides or {}))
    assignments = {}
    for craft, (start, end) in ADJACENT_BOOKINGS.items():
        overrides = {
            "booking_start_date": start,
            "booking_end_date": end,
            "royalty_share_bps": shares[craft],
        }
        overrides.update(assignment_overrides or {})
        assignments[craft] = offer_and_accept_assignment(
            title["id"],
            creator["id"],
            craft,
            **overrides,
        )
    issue = schedule_issue(title["id"], **(issue_overrides or {}))
    set_clock(delivery_clock)
    stages = {}
    for craft in REQUIRED_CRAFTS:
        stages[craft] = run_stage_to_approved(
            issue["id"],
            assignments[craft]["id"],
            creator["id"],
            craft=craft,
            planned_start_date="2026-08-01",
            planned_due_date=planned_due_date,
        )
    return {
        "creator": creator,
        "creator_headers": make_creator_headers(creator["id"]),
        "title": read_title(title["id"]),
        "assignments": assignments,
        "issue": read_issue(issue["id"]),
        "stages": stages,
    }


def solicit_issue(
    issue_id: str,
    cover_specs=DEFAULT_COVER_SPECS,
    catalog_overrides: dict = None,
    solicitation_overrides: dict = None,
    lock_clock: str = "2026-08-21T12:00:00Z",
    accept: bool = True,
    publish: bool = True,
) -> dict:
    """Take an issue through covers, catalog listing, lock, acceptance and publication.

    Stops early where asked, so a test can observe an unlocked catalog or an
    unpublished one.
    """
    covers = add_covers(issue_id, cover_specs) if cover_specs else {}
    catalog = open_catalog(**(catalog_overrides or {}))
    solicitation = draft_solicitation(
        catalog["id"], issue_id, **(solicitation_overrides or {})
    )
    solicitation = submit_solicitation(solicitation["id"])
    set_clock(lock_clock)
    if not accept:
        return {"covers": covers, "catalog": catalog, "solicitation": solicitation}
    catalog = lock_catalog(catalog["id"])
    solicitation = accept_solicitation(solicitation["id"])
    if publish:
        catalog = publish_catalog(catalog["id"])
    return {
        "covers": covers,
        "catalog": read_catalog(catalog["id"]),
        "solicitation": read_solicitation(solicitation["id"]),
    }


def setup_solicited_issue_in_scripting(
    cover_specs=DEFAULT_COVER_SPECS,
    catalog_overrides: dict = None,
    issue_overrides: dict = None,
    **kwargs,
) -> dict:
    """An issue in `SCRIPTING` whose listing has been published to the market."""
    state = setup_issue_in_scripting(issue_overrides=issue_overrides, **kwargs)
    state.update(
        solicit_issue(
            state["issue"]["id"],
            cover_specs=cover_specs,
            catalog_overrides=catalog_overrides,
        )
    )
    state["issue"] = read_issue(state["issue"]["id"])
    return state


def setup_solicited_camera_ready_issue(
    cover_specs=DEFAULT_COVER_SPECS,
    catalog_overrides: dict = None,
    issue_overrides: dict = None,
    title_overrides: dict = None,
    assignment_overrides: dict = None,
) -> dict:
    """A camera-ready issue whose listing has been published to the market."""
    state = setup_camera_ready_issue(
        title_overrides=title_overrides,
        issue_overrides=issue_overrides,
        assignment_overrides=assignment_overrides,
    )
    state.update(
        solicit_issue(
            state["issue"]["id"],
            cover_specs=cover_specs,
            catalog_overrides=catalog_overrides,
        )
    )
    state["issue"] = read_issue(state["issue"]["id"])
    return state


def setup_locked_order_book(
    camera_ready: bool = False,
    retailer_overrides: dict = None,
    order_overrides: dict = None,
    extra_orders=(),
    cover_specs=DEFAULT_COVER_SPECS,
    catalog_overrides: dict = None,
    issue_overrides: dict = None,
    title_overrides: dict = None,
    assignment_overrides: dict = None,
    foc_clock: str = "2026-09-23T00:00:00Z",
) -> dict:
    """A solicited issue with a submitted order book frozen at the cut-off.

    `extra_orders` is a sequence of `(retailer_overrides, order_overrides)`
    pairs, each opening a further account and submitting a further order.
    """
    if camera_ready:
        state = setup_solicited_camera_ready_issue(
            cover_specs=cover_specs,
            catalog_overrides=catalog_overrides,
            issue_overrides=issue_overrides,
            title_overrides=title_overrides,
            assignment_overrides=assignment_overrides,
        )
    else:
        state = setup_solicited_issue_in_scripting(
            cover_specs=cover_specs,
            catalog_overrides=catalog_overrides,
            issue_overrides=issue_overrides,
            title_overrides=title_overrides,
            assignment_overrides=assignment_overrides,
        )
    issue_id = state["issue"]["id"]

    retailers = []
    orders = []
    specs = [(retailer_overrides or {}, order_overrides or {})] + [
        (dict(r or {}), dict(o or {})) for r, o in extra_orders
    ]
    for r_overrides, o_overrides in specs:
        retailer = open_retailer(**r_overrides)
        order = draft_and_submit_order(retailer["id"], issue_id, **o_overrides)
        retailers.append(retailer)
        orders.append(order)

    set_clock(foc_clock)
    issue = foc_lock(issue_id)

    state.update(
        {
            "retailers": retailers,
            "retailer": retailers[0],
            "orders": [read_order(order["id"]) for order in orders],
            "order": read_order(orders[0]["id"]),
            "issue": read_issue(issue["id"]),
        }
    )
    return state


def setup_printed_issue(**kwargs) -> dict:
    """A camera-ready issue whose first `ORDER_DRIVEN` printing has been run."""
    kwargs.setdefault("camera_ready", True)
    state = setup_locked_order_book(**kwargs)
    print_run = plan_and_complete_print_run(state["issue"]["id"])
    state["print_runs"] = [print_run]
    state["print_run"] = print_run
    state["issue"] = read_issue(state["issue"]["id"])
    return state


def setup_on_sale_issue(release_clock: str = "2026-10-14T00:00:00Z", **kwargs) -> dict:
    """A printed issue that has been put on sale."""
    state = setup_printed_issue(**kwargs)
    set_clock(release_clock)
    state["issue"] = release_issue(state["issue"]["id"])
    return state


def setup_catalog_with_slots(
    issue_count: int = 3,
    max_slots: int = 2,
    accept_count: int = 2,
    on_sale_dates=("2026-10-14", "2026-11-04", "2026-12-02"),
) -> dict:
    """One catalog holding several submitted listings, some of them accepted.

    Each listing belongs to its own issue of one title, and each issue keeps
    the twenty-one-day on-sale cadence its siblings require.
    """
    state = setup_greenlit_title_with_script_assignment()
    title_id = state["title"]["id"]
    catalog = open_catalog(max_slots=max_slots)

    issues, stages, solicitations, covers = [], [], [], []
    for index in range(issue_count):
        issue = schedule_issue(
            title_id,
            issue_number=index + 1,
            target_on_sale_date=on_sale_dates[index],
        )
        stage = book_stage(issue["id"], state["assignment"]["id"], "SCRIPT")
        stage = start_stage(stage["id"], state["creator"]["id"])
        covers.append(add_covers(issue["id"], (DEFAULT_COVER_SPECS[0],)))
        solicitation = draft_solicitation(catalog["id"], issue["id"])
        solicitation = submit_solicitation(solicitation["id"])
        issues.append(issue)
        stages.append(stage)
        solicitations.append(solicitation)

    set_clock("2026-08-21T12:00:00Z")
    catalog = lock_catalog(catalog["id"])
    for solicitation in solicitations[:accept_count]:
        accept_solicitation(solicitation["id"])

    state.update(
        {
            "catalog": read_catalog(catalog["id"]),
            "issues": [read_issue(issue["id"]) for issue in issues],
            "stages": stages,
            "covers": covers,
            "solicitations": [read_solicitation(s["id"]) for s in solicitations],
        }
    )
    return state


ROYALTY_TEAM = (
    ("Wanda Writer", "SCRIPT", 12000, 5000),
    ("Pablo Penciller", "PENCILS", 9000, 3000),
    ("Cora Coverartist", "COVER", 15000, 1500),
)

ESTIMATED_AND_ACTUAL_RECEIPTS = (
    {"channel": "PRINT_DM", "basis_status": "ACTUAL", "gross_receipts_cents": 400000,
     "net_receipts_cents": 328500, "units": 1108},
    {"channel": "PRINT_DM", "basis_status": "ESTIMATED", "gross_receipts_cents": 80000,
     "net_receipts_cents": 66000, "units": 220},
    {"channel": "DIGITAL", "basis_status": "ACTUAL", "gross_receipts_cents": 80000,
     "net_receipts_cents": 56000, "units": 400},
    {"channel": "COLLECTED", "basis_status": "ESTIMATED", "gross_receipts_cents": 120000,
     "net_receipts_cents": 90000, "units": 150},
    {"channel": "SUBSIDIARY", "basis_status": "ACTUAL", "gross_receipts_cents": 250000,
     "net_receipts_cents": 200000, "units": 0},
)

ACTUAL_ONLY_RECEIPTS = tuple(
    row for row in ESTIMATED_AND_ACTUAL_RECEIPTS if row["basis_status"] == "ACTUAL"
)


def setup_royalty_revenue_ledger(
    receipts=ESTIMATED_AND_ACTUAL_RECEIPTS,
    period: str = "2026-12",
    script_advance_cents: int = 25000,
    title_overrides: dict = None,
    issue_overrides: dict = None,
) -> dict:
    """A title staffed with a script, pencil and cover participant, plus receipts.

    Returns `creators` and `assignments` keyed by craft, the `title`, the
    `issue` and the posted `revenue_events`.
    """
    set_clock()
    creators, assignments = {}, {}
    title = pitch_and_greenlight_title(**(title_overrides or {}))
    for full_name, craft, page_rate, share_bps in ROYALTY_TEAM:
        creator = register_creator(
            full_name=full_name, crafts=[craft], default_page_rate_cents=page_rate
        )
        advance = script_advance_cents if craft == "SCRIPT" else 0
        assignments[craft] = offer_and_accept_assignment(
            title["id"],
            creator["id"],
            craft,
            page_rate_cents=page_rate,
            royalty_share_bps=share_bps,
            advance_cents=advance,
        )
        creators[craft] = creator
    issue = schedule_issue(title["id"], **(issue_overrides or {}))
    revenue_events = [
        post_revenue_event(issue["id"], period=period, **dict(row)) for row in receipts
    ]
    return {
        "creators": creators,
        "title": read_title(title["id"]),
        "assignments": assignments,
        "issue": read_issue(issue["id"]),
        "revenue_events": revenue_events,
        "period": period,
    }
