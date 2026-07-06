"""Composite setup helpers for the Estate Sale API.

Every helper builds its preconditions from scratch against an empty database using
only PRD-declared endpoints, and uses get_success_data() so setup failures surface
as clear "Setup step failed" errors. Ownership-gated Client transitions thread the
real Client.id through make_client_headers().
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import (
    TEST_USERS,
    make_client_headers,
    make_appraiser_headers,
    make_sale_manager_headers,
)

ADMIN = TEST_USERS["platform_admin_headers"]
MANAGER = TEST_USERS["sale_manager_headers"]
APPRAISER = TEST_USERS["appraiser_headers"]
CASHIER = TEST_USERS["cashier_headers"]

_counter = {"n": 0}


def _uniq(prefix):
    _counter["n"] += 1
    return f"{prefix}-{_counter['n']}"


# --------------------------------------------------------------- clock ---
def set_clock(iso, api=api_client):
    return get_success_data(api.set_clock({"to_iso8601": iso}, ADMIN))


# ----------------------------------------------------- primitive builders ---
def new_client(api=api_client, name=None, phone="555-0100", email=None):
    payload = {"name": name or _uniq("Owner"), "phone": phone}
    if email is not None:
        payload["email"] = email
    return get_success_data(api.create_client(payload, ADMIN))


def new_project(client_id, api=api_client, address=None, estimated_total_value_cents=100000,
                minimum_commission_cents=None):
    payload = {
        "client_id": client_id,
        "address": address or _uniq("Addr"),
        "estimated_total_value_cents": estimated_total_value_cents,
    }
    if minimum_commission_cents is not None:
        payload["minimum_commission_cents"] = minimum_commission_cents
    return get_success_data(api.create_project(payload, ADMIN))


def patch_project(project_id, payload, headers, api=api_client):
    return get_success_data(api.patch_project(project_id, payload, headers))


def contract_project(project_id, client_id, api=api_client):
    """Drive LEAD -> ASSESSED -> PROPOSED (manager) -> CONTRACTED (client, ownership-gated)."""
    patch_project(project_id, {"status": "ASSESSED"}, MANAGER, api)
    patch_project(project_id, {"status": "PROPOSED"}, MANAGER, api)
    return patch_project(project_id, {"status": "CONTRACTED"}, make_client_headers(client_id), api)


def new_lot(project_id, api=api_client, researcher_headers=None, **fields):
    payload = {"project_id": project_id, "title": fields.pop("title", None) or _uniq("Lot")}
    payload.update(fields)
    return get_success_data(api.create_lot(payload, researcher_headers or APPRAISER))


def research_and_price(lot_id, api=api_client, list_price_cents=None, research_notes="comps ok",
                       researcher_headers=None):
    hdrs = researcher_headers or APPRAISER
    get_success_data(api.patch_lot(lot_id, {"status": "RESEARCHED", "research_notes": research_notes}, hdrs))
    price_payload = {"status": "PRICED"}
    if list_price_cents is not None:
        price_payload["list_price_cents"] = list_price_cents
    return get_success_data(api.patch_lot(lot_id, price_payload, hdrs))


def stage_tag_list(lot_id, api=api_client):
    """Walk PRICED -> STAGED -> TAGGED -> LISTED (project must be SALE_SETUP or SALE_LIVE)."""
    get_success_data(api.patch_lot(lot_id, {"status": "STAGED"}, APPRAISER))
    get_success_data(api.patch_lot(lot_id, {"status": "TAGGED"}, APPRAISER))
    return get_success_data(api.patch_lot(lot_id, {"status": "LISTED"}, APPRAISER))


def new_crew(api=api_client, name=None):
    return get_success_data(api.create_crew({"name": name or _uniq("Crew")}, ADMIN))


def new_sale_event(project_id, crew_id, start_at, end_at, api=api_client, **markdown):
    payload = {"project_id": project_id, "crew_id": crew_id, "start_at": start_at, "end_at": end_at}
    payload.update(markdown)
    return get_success_data(api.create_sale_event(payload, MANAGER))


def open_event(sale_event_id, api=api_client):
    return get_success_data(api.patch_sale_event(sale_event_id, {"status": "OPEN"}, MANAGER))


def new_transaction(sale_event_id, lot_id, payment_method="CASH", api=api_client, buyer_name=None):
    payload = {"sale_event_id": sale_event_id, "lot_id": lot_id, "payment_method": payment_method}
    if buyer_name is not None:
        payload["buyer_name"] = buyer_name
    return get_success_data(api.create_transaction(payload, CASHIER))


def new_bid(lot_id, amount_cents, bidder_name="bidder", api=api_client):
    return get_success_data(
        api.create_bid({"lot_id": lot_id, "amount_cents": amount_cents, "bidder_name": bidder_name}, CASHIER)
    )


def new_truck(api=api_client, name=None):
    return get_success_data(api.create_truck({"name": name or _uniq("Truck")}, ADMIN))


# ------------------------------------------------------- composite helpers ---
def contracted_project(api=api_client, minimum_commission_cents=None,
                       estimated_total_value_cents=100000):
    """Client + project driven to CONTRACTED. Returns (client, project)."""
    client = new_client(api)
    project = new_project(client["id"], api, minimum_commission_cents=minimum_commission_cents,
                          estimated_total_value_cents=estimated_total_value_cents)
    contract_project(project["id"], client["id"], api)
    project = get_success_data(api.get_project(project["id"], MANAGER))
    return client, project


def listed_fixed_lot(api=api_client, list_price_cents=5000, reserve_price_cents=100,
                     sale_start="2026-06-01T00:00:00Z", sale_end="2026-06-04T00:00:00Z",
                     open_now=True, start_clock="2026-06-01T00:00:00Z"):
    """Project driven to SALE_LIVE with one LISTED fixed-price lot on an OPEN sale event.

    Returns dict: client, project, lot, crew, sale_event (ids under *_id keys too).
    """
    if start_clock is not None:
        set_clock(start_clock, api)
    client, project = contracted_project(api)
    pid = project["id"]
    lot = new_lot(pid, api, title="Fixed lot", list_price_cents=list_price_cents,
                  reserve_price_cents=reserve_price_cents)
    research_and_price(lot["id"], api)
    patch_project(pid, {"status": "SALE_SETUP"}, MANAGER, api)
    stage_tag_list(lot["id"], api)
    crew = new_crew(api)
    se = new_sale_event(pid, crew["id"], sale_start, sale_end, api)
    patch_project(pid, {"status": "SALE_LIVE"}, MANAGER, api)
    if open_now:
        open_event(se["id"], api)
    return {"client": client, "project": project, "project_id": pid,
            "lot": lot, "lot_id": lot["id"], "crew": crew, "crew_id": crew["id"],
            "sale_event": se, "sale_event_id": se["id"]}


def listed_bid_lot(api=api_client, bid_mode="FIRST_PRICE", reserve_price_cents=10000,
                   min_increment_cents=1000, list_price_cents=20000, to_sale_live=False):
    """Project in SALE_SETUP (or SALE_LIVE) with one LISTED bid lot. Returns dict."""
    client, project = contracted_project(api)
    pid = project["id"]
    lot = new_lot(pid, api, title="Bid lot", is_bid_lot=True, bid_mode=bid_mode,
                  list_price_cents=list_price_cents, reserve_price_cents=reserve_price_cents,
                  min_increment_cents=min_increment_cents)
    research_and_price(lot["id"], api)
    patch_project(pid, {"status": "SALE_SETUP"}, MANAGER, api)
    stage_tag_list(lot["id"], api)
    if to_sale_live:
        patch_project(pid, {"status": "SALE_LIVE"}, MANAGER, api)
    return {"client": client, "project": project, "project_id": pid,
            "lot": lot, "lot_id": lot["id"]}


def settled_ready_consignment_sale(lots, payment_method, sell_clock, api=api_client,
                                   sale_start="2026-06-01T00:00:00Z",
                                   sale_end="2026-06-03T00:00:00Z",
                                   start_clock="2026-06-01T00:00:00Z",
                                   minimum_commission_cents=None):
    """Full consignment sale driven to SETTLING, ready for settlement create.

    `lots` is a list of dicts, each {list_price_cents, reserve_price_cents, title?}. All lots
    are priced BEFORE the SALE_SETUP snapshot (so they populate the estimate), then listed,
    then sold at `sell_clock` with `payment_method`, the event closed, and the project moved to
    SETTLING. Returns dict incl. `project`, `lots` (list), `sale_event`, `crew`, and
    `settling_version` (Project.version observed at SETTLING).
    """
    set_clock(start_clock, api)
    client, project = contracted_project(api, minimum_commission_cents=minimum_commission_cents,
                                         estimated_total_value_cents=2000000)
    pid = project["id"]
    lot_objs = []
    for spec in lots:
        lot = new_lot(pid, api, title=spec.get("title", _uniq("Lot")),
                      handling_type="CONSIGNMENT",
                      list_price_cents=spec["list_price_cents"],
                      reserve_price_cents=spec.get("reserve_price_cents", 1000))
        research_and_price(lot["id"], api, list_price_cents=spec["list_price_cents"])
        lot_objs.append(lot)
    patch_project(pid, {"status": "SALE_SETUP"}, MANAGER, api)
    for lot in lot_objs:
        stage_tag_list(lot["id"], api)
    crew = new_crew(api)
    se = new_sale_event(pid, crew["id"], sale_start, sale_end, api)
    patch_project(pid, {"status": "SALE_LIVE"}, MANAGER, api)
    open_event(se["id"], api)
    set_clock(sell_clock, api)
    txns = []
    for lot in lot_objs:
        txns.append(new_transaction(se["id"], lot["id"], payment_method, api))
    get_success_data(api.close_sale_event(se["id"], MANAGER))
    settling = patch_project(pid, {"status": "SETTLING"}, MANAGER, api)
    return {"client": client, "project": settling, "project_id": pid,
            "lots": lot_objs, "crew": crew, "crew_id": crew["id"],
            "sale_event": se, "sale_event_id": se["id"], "transactions": txns,
            "settling_version": settling["version"]}


def project_in_settling_no_lots(api=api_client):
    """Empty project driven straight to SETTLING. Returns (project, version)."""
    client = new_client(api)
    project = new_project(client["id"], api, estimated_total_value_cents=1000)
    pid = project["id"]
    contract_project(pid, client["id"], api)
    patch_project(pid, {"status": "SALE_SETUP"}, MANAGER, api)
    patch_project(pid, {"status": "SALE_LIVE"}, MANAGER, api)
    settling = patch_project(pid, {"status": "SETTLING"}, MANAGER, api)
    return settling, settling["version"]


def crew_booked_event(api=api_client, start_at="2026-06-01T09:00:00Z",
                      end_at="2026-06-01T17:00:00Z"):
    """A project + crew booked by one SCHEDULED sale event. Returns dict."""
    client = new_client(api)
    project = new_project(client["id"], api)
    crew = new_crew(api)
    se = new_sale_event(project["id"], crew["id"], start_at, end_at, api)
    return {"project": project, "project_id": project["id"], "crew": crew,
            "crew_id": crew["id"], "sale_event": se, "sale_event_id": se["id"]}
