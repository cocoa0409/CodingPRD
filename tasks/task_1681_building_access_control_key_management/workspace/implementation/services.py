from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from db import STORE, CLOCK, next_seq, new_id, bump, parse_hhmm

LEVEL_DEPTH = {"GRAND_MASTER": 0, "MASTER": 1, "SUB_MASTER": 2, "CHANGE": 3}
LEVELS = list(LEVEL_DEPTH.keys())
TYPE_FEE = {"METAL_KEY": 1500, "FOB": 4500, "CARD": 1501}
ADMIN_SURCHARGE_PCT = 25
TRAILING_LOSS_WINDOW_DAYS = 30
DAYS = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]


# ---------------------------------------------------------------- hierarchy
def subtree_ids(root_id):
    """All node ids in the subtree rooted at root_id (inclusive)."""
    children = {}
    for n in STORE["key_nodes"].values():
        if n["parent_id"] is not None:
            children.setdefault(n["parent_id"], []).append(n["id"])
    out = []
    stack = [root_id]
    seen = set()
    while stack:
        nid = stack.pop()
        if nid in seen:
            continue
        seen.add(nid)
        out.append(nid)
        stack.extend(children.get(nid, []))
    return out


# ---------------------------------------------------------------- charges
def create_charge(building_id, person_id, campaign_id, kind, amount_cents,
                  deposit_cents=None, provisional_refund_cents=None,
                  line_items=None, moved_out_at=None):
    now = CLOCK.now()
    ch = {
        "id": new_id(),
        "building_id": building_id,
        "person_id": person_id,
        "campaign_id": campaign_id,
        "kind": kind,
        "amount_cents": amount_cents,
        "deposit_cents": deposit_cents,
        "provisional_refund_cents": provisional_refund_cents,
        "final_forfeit_total_cents": None,
        "final_refund_cents": None,
        "line_items": line_items,
        "moved_out_at": moved_out_at,
        "status": "DRAFT",
        "seq": next_seq(building_id, "charges"),
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    STORE["charges"][ch["id"]] = ch
    return ch


def forfeiture_line(cred):
    """round_half_up(TYPE_FEE * 1.25), rounded per line before any summing."""
    fee = Decimal(TYPE_FEE[cred["type"]]) * (
        Decimal(100 + ADMIN_SURCHARGE_PCT) / Decimal(100))
    fee = int(fee.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return {"credential_id": cred["id"], "type": cred["type"],
            "fee_cents": fee}


def cred_sort_key(c):
    return (c["created_at"], c["serial_no"])


def line_sort_key(c):
    """Forfeiture-line ordering: (created_at ASC, seq ASC) — the per-building
    minting counter breaks same-instant created_at ties in minting order."""
    return (c["created_at"], c["seq"])


def deactivate_credential(cred, reason, campaign=None):
    """System-driven deactivation. Retains holder_person_id and lost_at.
    REKEY from ISSUED spawns a KEY_REISSUE draft charge."""
    was_issued = cred["status"] == "ISSUED"
    cred["status"] = "DEACTIVATED"
    cred["deactivated_reason"] = reason
    bump(cred)
    if reason == "REKEY" and was_issued and campaign is not None:
        building = STORE["buildings"][campaign["building_id"]]
        person_id = (campaign["bill_person_id"]
                     if campaign["bill_to"] == "PERSON" else None)
        create_charge(campaign["building_id"], person_id, campaign["id"],
                      "KEY_REISSUE", building["per_key_reissue_fee_cents"])


# ---------------------------------------------------------------- incidents
def create_incident(building_id, type_, credential_id=None, door_id=None,
                    alert_id=None, responsible_person_id=None):
    now = CLOCK.now()
    inc = {
        "id": new_id(),
        "building_id": building_id,
        "type": type_,
        "status": "OPEN",
        "credential_id": credential_id,
        "door_id": door_id,
        "alert_id": alert_id,
        "responsible_person_id": responsible_person_id,
        "resolution_action": None,
        "resolution_note": None,
        "campaign_id": None,
        "seq": next_seq(building_id, "incidents"),
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    STORE["incidents"][inc["id"]] = inc
    return inc


def report_lost_cascade(cred):
    """Three-hop cascade: node COMPROMISED -> subtree doors REKEY_REQUIRED,
    LOST_CREDENTIAL incident opened."""
    now = CLOCK.now()
    cred["lost_at"] = now
    cred["status"] = "LOST"
    bump(cred)
    node = STORE["key_nodes"].get(cred["key_node_id"])
    if node is not None and node["status"] == "ACTIVE":
        node["status"] = "COMPROMISED"
        bump(node)
    if node is not None:
        ids = set(subtree_ids(node["id"]))
        for d in STORE["doors"].values():
            if d["key_node_id"] in ids and d["core_status"] != "REKEY_REQUIRED":
                d["core_status"] = "REKEY_REQUIRED"
                bump(d)
    create_incident(cred["building_id"], "LOST_CREDENTIAL",
                    credential_id=cred["id"],
                    responsible_person_id=cred["holder_person_id"])


# ---------------------------------------------------------------- campaigns
def compute_scope(campaign):
    """Estimate variant: current scope counts at standard rates."""
    building = STORE["buildings"][campaign["building_id"]]
    ids = set(subtree_ids(campaign["key_node_id"]))
    doors = [d for d in STORE["doors"].values()
             if d["key_node_id"] in ids
             and d["core_status"] in ("ACTIVE", "REKEY_REQUIRED")]
    creds = [c for c in STORE["credentials"].values()
             if c["key_node_id"] in ids and c["status"] == "ISSUED"]
    door_count = len(doors)
    cred_count = len(creds)
    estimate = (building["base_fee_cents"]
                + building["per_door_fee_cents"] * door_count
                + building["per_key_reissue_fee_cents"] * cred_count)
    return door_count, cred_count, estimate


def create_campaign(building, key_node_id, incident_id, bill_to,
                    bill_person_id):
    now = CLOCK.now()
    c = {
        "id": new_id(),
        "building_id": building["id"],
        "key_node_id": key_node_id,
        "incident_id": incident_id,
        "status": "PROPOSED",
        "bill_to": bill_to,
        "bill_person_id": bill_person_id,
        "rekey_seq": next_seq(building["id"], "rekey"),
        "affected_door_count": 0,
        "affected_credential_count": 0,
        "estimated_cost_cents": 0,
        "final_cost_cents": None,
        "completed_at": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    STORE["campaigns"][c["id"]] = c
    dc, cc, est = compute_scope(c)
    c["affected_door_count"] = dc
    c["affected_credential_count"] = cc
    c["estimated_cost_cents"] = est
    return c


def approve_campaign_effects(campaign):
    """Mint successor subtree + one REKEY work order per affected door.
    Counts/estimate must already be refreshed by the caller."""
    ids = subtree_ids(campaign["key_node_id"])
    nodes = [STORE["key_nodes"][i] for i in ids if i in STORE["key_nodes"]]
    nodes.sort(key=lambda n: (LEVEL_DEPTH[n["level"]], n["label"], n["seq"]))
    now = CLOCK.now()
    succ = {}
    for n in nodes:
        if n["id"] == campaign["key_node_id"]:
            parent_succ = None
        else:
            parent_succ = succ.get(n["parent_id"])
        node = {
            "id": new_id(),
            "building_id": n["building_id"],
            "parent_id": parent_succ,
            "level": n["level"],
            "label": "%s-R%d" % (n["label"], campaign["rekey_seq"]),
            "status": "ACTIVE",
            "supersedes_node_id": n["id"],
            "seq": next_seq(n["building_id"], "key_nodes"),
            "created_at": now,
            "updated_at": now,
            "version": 1,
        }
        STORE["key_nodes"][node["id"]] = node
        succ[n["id"]] = node["id"]
    idset = set(ids)
    doors = [d for d in STORE["doors"].values()
             if d["key_node_id"] in idset
             and d["core_status"] in ("ACTIVE", "REKEY_REQUIRED")]
    doors.sort(key=lambda d: d["door_code"])
    for d in doors:
        wo = {
            "id": new_id(),
            "building_id": campaign["building_id"],
            "door_id": d["id"],
            "campaign_id": campaign["id"],
            "target_key_node_id": succ.get(d["key_node_id"]),
            "type": "REKEY",
            "status": "OPEN",
            "scheduled_start": None,
            "scheduled_end": None,
            "actual_cost_cents": None,
            "bill_person_id": None,
            "seq": next_seq(campaign["building_id"], "work_orders"),
            "created_at": now,
            "updated_at": now,
            "version": 1,
        }
        STORE["work_orders"][wo["id"]] = wo
    campaign["status"] = "APPROVED"
    bump(campaign)


def maybe_complete_campaign(campaign):
    if campaign is None:
        return
    if campaign["status"] not in ("APPROVED", "IN_PROGRESS"):
        return
    wos = [w for w in STORE["work_orders"].values()
           if w["campaign_id"] == campaign["id"]]
    if not wos:
        return
    if (all(w["status"] in ("COMPLETED", "CANCELLED") for w in wos)
            and any(w["status"] == "COMPLETED" for w in wos)):
        complete_campaign(campaign)


def complete_campaign(campaign):
    now = CLOCK.now()
    building = STORE["buildings"][campaign["building_id"]]
    campaign["status"] = "COMPLETED"
    campaign["completed_at"] = now
    for nid in subtree_ids(campaign["key_node_id"]):
        node = STORE["key_nodes"].get(nid)
        if node is not None and node["status"] in ("ACTIVE", "COMPROMISED"):
            node["status"] = "RETIRED"
            bump(node)
    completed = [w for w in STORE["work_orders"].values()
                 if w["campaign_id"] == campaign["id"]
                 and w["status"] == "COMPLETED"]
    actual = sum(w["actual_cost_cents"] or 0 for w in completed)
    door_sub = building["base_fee_cents"] + actual
    t = now.hour * 60 + now.minute
    open_m = parse_hhmm(building["business_open_utc"])
    close_m = parse_hhmm(building["business_close_utc"])
    if open_m is not None and close_m is not None and open_m <= t < close_m:
        door_portion = door_sub
    else:
        door_portion = Decimal(door_sub) * (
            Decimal(100 + building["emergency_surcharge_pct"]) / Decimal(100))
        door_portion = int(door_portion.quantize(Decimal("1"),
                                                 rounding=ROUND_HALF_UP))
    key_portion = sum(ch["amount_cents"] for ch in STORE["charges"].values()
                      if ch["campaign_id"] == campaign["id"]
                      and ch["kind"] == "KEY_REISSUE")
    campaign["final_cost_cents"] = door_portion + key_portion
    person_id = (campaign["bill_person_id"]
                 if campaign["bill_to"] == "PERSON" else None)
    create_charge(campaign["building_id"], person_id, campaign["id"],
                  "REKEY_CAMPAIGN", door_portion)
    bump(campaign)


# ---------------------------------------------------------- access decision
def schedule_contains(group, now):
    """Minute-precision containment; day membership vs UTC weekday of now."""
    if DAYS[now.weekday()] not in group["days_of_week"]:
        return False
    s = parse_hhmm(group["window_start_utc"])
    e = parse_hhmm(group["window_end_utc"])
    if s is None or e is None:
        return False
    t = now.hour * 60 + now.minute  # seconds component ignored
    if s < e:
        return s <= t < e
    if s > e:
        return t >= s or t < e
    return False  # s == e rejected at write time; unreachable


def access_decision(cred, door, now):
    """Ordered rule chain; first failure wins."""
    if cred["status"] != "ISSUED":
        return "DENIED_CREDENTIAL_NOT_ISSUED"
    if cred["expires_at"] is not None and now >= cred["expires_at"]:
        return "DENIED_CREDENTIAL_EXPIRED"
    covering = [g for g in STORE["access_groups"].values()
                if g["building_id"] == door["building_id"]
                and cred["holder_person_id"] in g["person_ids"]
                and door["id"] in g["door_ids"]]
    if not covering:
        return "DENIED_NOT_AUTHORIZED"
    if not any(schedule_contains(g, now) for g in covering):
        return "DENIED_OUTSIDE_WINDOW"
    return "GRANTED"
