"""Composite setup helpers.

Each helper builds preconditions from scratch using only PRD-declared endpoints
(every test runs against a freshly restarted server with an empty database).
"""
from prd_bench_local_runner.testing import get_success_data, validate_success

from .api_client import api_client
from .test_users import TEST_USERS, make_surgeon_headers, make_officer_headers

ANALYST = TEST_USERS["analyst_headers"]
CART = TEST_USERS["cart_tech_headers"]
NURSE = TEST_USERS["nurse_headers"]
MATERIALS = TEST_USERS["materials_headers"]
ANY = TEST_USERS["any_headers"]


# ---------------------------------------------------------------------------
# Tier 1: single-entity builders
# ---------------------------------------------------------------------------

def make_surgeon(full_name="Dr. Test", specialty="ORTHO"):
    """Create an ACTIVE surgeon. Returns surgeon dict."""
    resp = api_client.create_surgeon(
        {"full_name": full_name, "specialty": specialty}, ANALYST
    )
    return get_success_data(resp)


def make_supply_item(sku=None, name=None, unit_cost_cents=250, substitute_group=None,
                     consignment_flag=False, initial_on_hand=0):
    """Create an ACTIVE supply item. Returns item dict."""
    payload = {
        "sku": sku or ("SKU-" + unit_cost_cents.__str__() + "-" + (name or "X").replace(" ", "")[:8]),
        "name": name or "Test item",
        "unit_cost_cents": unit_cost_cents,
    }
    if substitute_group is not None:
        payload["substitute_group"] = substitute_group
    if consignment_flag:
        payload["consignment_flag"] = True
    if initial_on_hand:
        payload["initial_on_hand"] = initial_on_hand
    resp = api_client.create_supply_item(payload, ANALYST)
    return get_success_data(resp)


def make_draft_card(surgeon_id, procedure_name="TKA"):
    """Create a DRAFT preference card. Returns card dict."""
    resp = api_client.create_preference_card(
        {"surgeon_id": surgeon_id, "procedure_name": procedure_name}, ANALYST
    )
    return get_success_data(resp)


def add_card_line(card_id, supply_item_id, quantity=1, designation="OPEN",
                  pick_sequence=None, notes=None):
    """Add a line to a DRAFT card. Returns line dict."""
    payload = {
        "card_id": card_id,
        "supply_item_id": supply_item_id,
        "quantity": quantity,
        "designation": designation,
    }
    if pick_sequence is not None:
        payload["pick_sequence"] = pick_sequence
    if notes is not None:
        payload["notes"] = notes
    resp = api_client.create_preference_card_line(payload, ANALYST)
    return get_success_data(resp)


def publish_card(card_id):
    """Publish a DRAFT card at its current version. Returns published card dict."""
    card = get_success_data(api_client.get_preference_card(card_id, ANY))
    resp = api_client.publish_preference_card(
        card_id, {"expected_card_version": card["version"]}, ANALYST
    )
    return get_success_data(resp)


def make_published_card(surgeon_id, procedure_name, lines):
    """Create + line + publish a card.

    `lines` is a list of dicts: {"supply_item_id", "quantity", "designation",
    "pick_sequence" (optional)}. Returns the published card dict.
    """
    card = make_draft_card(surgeon_id, procedure_name)
    for i, line in enumerate(lines, start=1):
        add_card_line(
            card["id"],
            line["supply_item_id"],
            quantity=line.get("quantity", 1),
            designation=line.get("designation", "OPEN"),
            pick_sequence=line.get("pick_sequence", i),
        )
    return publish_card(card["id"])


def make_case(surgeon_id, card_id, scheduled_start="2026-09-05T08:00:00Z",
              expected_duration_min=60, room="OR-1", consignment_budget_cents=None):
    """Schedule a case. Returns case dict (SCHEDULED)."""
    payload = {
        "surgeon_id": surgeon_id,
        "card_id": card_id,
        "scheduled_start": scheduled_start,
        "expected_duration_min": expected_duration_min,
        "room": room,
    }
    if consignment_budget_cents is not None:
        payload["consignment_budget_cents"] = consignment_budget_cents
    resp = api_client.create_case(payload, ANALYST)
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 2: pick-list helpers
# ---------------------------------------------------------------------------

def release_pick_list(case_id):
    """Release the pick list. Returns (pick_list, lines) where lines is the
    pick_sequence-ordered list of pick list line dicts."""
    pl = get_success_data(api_client.release_pick_list(case_id, ANALYST))
    lines_resp = api_client.list_pick_list_lines(ANY, params={"pick_list_id": pl["id"]})
    lines_data = get_success_data(lines_resp)
    if isinstance(lines_data, dict) and "data" in lines_data:
        lines = lines_data["data"]
    else:
        lines = lines_data
    return pl, lines


def pick_all_lines(lines):
    """Pick every line (PENDING -> PICKED). Assumes picking already begun."""
    for line in lines:
        get_success_data(api_client.pick_line(line["id"], CART))


def return_cart(pick_list_id, return_entries=None):
    """Return a DISPATCHED cart. Returns returned pick list dict."""
    payload = {"return_entries": return_entries or []}
    return get_success_data(api_client.return_pick_list(pick_list_id, payload, CART))


def get_audit_for_case(case_id):
    """Return the single CardAccuracyAudit for a completed case."""
    resp = api_client.list_card_audits(ANY, params={"case_id": case_id})
    data = get_success_data(resp)
    rows = data["data"] if isinstance(data, dict) and "data" in data else data
    assert len(rows) >= 1, f"Expected an audit for case {case_id}"
    return rows[0]


def get_usage_records_for_case(case_id):
    resp = api_client.list_usage_records(ANY, params={"case_id": case_id})
    data = get_success_data(resp)
    return data["data"] if isinstance(data, dict) and "data" in data else data


def get_charges_for_case(case_id):
    resp = api_client.list_consignment_charges(ANY, params={"case_id": case_id})
    data = get_success_data(resp)
    return data["data"] if isinstance(data, dict) and "data" in data else data


# ---------------------------------------------------------------------------
# Tier 3: full lifecycle shortcuts
# ---------------------------------------------------------------------------

def setup_released_case(surgeon, items, lines_spec, procedure_name="TKA",
                        scheduled_start="2026-09-05T08:00:00Z",
                        expected_duration_min=60, room="OR-1",
                        consignment_budget_cents=None):
    """Published card + scheduled case + released pick list.

    `items` is a list of item dicts. `lines_spec` mirrors make_published_card's
    `lines` but `supply_item_id` may be given as an index into `items` via
    {"item_index": i, "quantity": n, "designation": "OPEN"|"HOLD"}.
    Returns dict(card=..., case=..., pick_list=..., lines=[...]).
    """
    lines = []
    for i, spec in enumerate(lines_spec, start=1):
        item_id = spec.get("supply_item_id")
        if item_id is None:
            item_id = items[spec["item_index"]]["id"]
        lines.append({
            "supply_item_id": item_id,
            "quantity": spec.get("quantity", 1),
            "designation": spec.get("designation", "OPEN"),
            "pick_sequence": spec.get("pick_sequence", i),
        })
    card = make_published_card(surgeon["id"], procedure_name, lines)
    case = make_case(
        surgeon["id"], card["id"],
        scheduled_start=scheduled_start,
        expected_duration_min=expected_duration_min,
        room=room,
        consignment_budget_cents=consignment_budget_cents,
    )
    pl, pl_lines = release_pick_list(case["id"])
    return {"card": card, "case": case, "pick_list": pl, "lines": pl_lines}


def setup_dispatched_case(surgeon, items, lines_spec, **kwargs):
    """Released case walked through: begin-picking, pick every line, dispatch.

    Returns dict(card, case, pick_list, lines).
    """
    ctx = setup_released_case(surgeon, items, lines_spec, **kwargs)
    get_success_data(api_client.begin_picking(ctx["pick_list"]["id"], CART))
    pick_all_lines(ctx["lines"])
    get_success_data(api_client.dispatch_pick_list(ctx["pick_list"]["id"], CART))
    return ctx


def setup_completed_case(surgeon, items, lines_spec, usage_by_index=None,
                         return_entries=None, **kwargs):
    """Full lifecycle through COMPLETED.

    `usage_by_index` maps line index (into the released lines list) to qty_used;
    lines missing from the map are recorded with no usage entry (qty_used 0).
    Returns dict(card, case, pick_list, lines, completed_case, audit).
    """
    ctx = setup_dispatched_case(surgeon, items, lines_spec, **kwargs)
    return_cart(ctx["pick_list"]["id"], return_entries=return_entries or [])
    usage_entries = []
    if usage_by_index:
        for idx, qty in usage_by_index.items():
            usage_entries.append({
                "pick_list_line_id": ctx["lines"][idx]["id"],
                "qty_used": qty,
            })
    completed = get_success_data(
        api_client.complete_case(ctx["case"]["id"], {"usage_entries": usage_entries}, NURSE)
    )
    audit = get_audit_for_case(ctx["case"]["id"])
    ctx["completed_case"] = completed
    ctx["audit"] = audit
    return ctx


# ---------------------------------------------------------------------------
# Tier 4: product-request helpers (segregation of duties)
# ---------------------------------------------------------------------------

def make_product_request(surgeon, **overrides):
    """Submit a product request as the given surgeon (entity-backed identity)."""
    payload = {
        "proposed_item_name": overrides.get("proposed_item_name", "Valve introducer"),
        "proposed_sku": overrides.get("proposed_sku", "SKU-" + surgeon["id"][:8].upper() + "-REQ"),
        "estimated_unit_cost_cents": overrides.get("estimated_unit_cost_cents", 4000),
        "rationale": overrides.get("rationale", "better implant tray system"),
    }
    for opt in ("substitute_group", "consignment_flag", "replaces_item_id"):
        if overrides.get(opt) is not None:
            payload[opt] = overrides[opt]
    resp = api_client.create_product_request(payload, make_surgeon_headers(surgeon["id"]))
    return get_success_data(resp)


def open_review(request_id, officer_id="officer-1"):
    resp = api_client.open_product_request_review(request_id, make_officer_headers(officer_id))
    return get_success_data(resp)


def endorse_request(request_id, officer_id):
    resp = api_client.endorse_product_request(request_id, make_officer_headers(officer_id))
    return get_success_data(resp)


def setup_request_under_review(surgeon, reviewing_officer="officer-1", **overrides):
    """Product request submitted + opened for review. Returns request dict."""
    req = make_product_request(surgeon, **overrides)
    return open_review(req["id"], reviewing_officer)


def setup_request_quorum_met(surgeon, reviewing_officer="officer-1",
                             endorsers=("officer-1", "officer-2"), **overrides):
    """Product request UNDER_REVIEW with quorum met. Returns request dict."""
    req = setup_request_under_review(surgeon, reviewing_officer=reviewing_officer, **overrides)
    for officer in endorsers:
        req = endorse_request(req["id"], officer)
    return req
