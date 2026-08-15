"""Derived counters, eligibility flags, and the cross-aggregate cascade
(PRD 2.8, 3.4, 3.5).

A direct field write plus the derived-field recomputation it triggers count as
ONE mutation of the owning entity: at most one version increment per entity per
request (PRD 2.5). The automatic project advance is a separate mutation with
its own increment (PRD 2.8: "that automatic transition increments the project's
version like any other").
"""
from db import store
from store_ops import touch

BLOCKING = ("OPEN", "READY_FOR_REVIEW")
MINOR_OPEN_ALLOWANCE = 5


def project_trades(project_id):
    return [t for t in store.trade_packages.values() if t["project_id"] == project_id]


def trade_derived(t):
    """Current values of a TradePackage's computed fields (SCAFFOLD 1.1)."""
    tid = t["id"]
    open_ct = sum(
        1 for i in store.punch_items.values()
        if i["trade_package_id"] == tid and i["status"] in BLOCKING
    )
    approved = [d for d in store.closeout_documents.values()
                if d["trade_package_id"] == tid and d["status"] == "APPROVED"]
    om = any(d["doc_type"] == "OM_MANUAL" for d in approved)
    wd = any(d["doc_type"] == "WARRANTY_DOC" for d in approved)
    ab = any(d["doc_type"] == "AS_BUILT" for d in approved)
    trained = any(s["trade_package_id"] == tid and s["status"] == "CONDUCTED"
                  for s in store.training_sessions.values())
    walked = any(w["trade_package_id"] == tid and w["status"] == "COMPLETED"
                 for w in store.punch_walks.values())
    ready = (
        open_ct == 0
        and om and wd and ab
        and trained
        and t["lien_waiver_status"] == "ACCEPTED"
        and t["lien_waiver_type"] == "UNCONDITIONAL"
    )
    return {
        "open_item_count": open_ct,
        "om_doc_approved": om,
        "warranty_doc_approved": wd,
        "asbuilt_doc_approved": ab,
        "has_conducted_training": trained,
        "has_completed_walk": walked,
        "closeout_ready": ready,
    }


def project_derived(p):
    """Current values of a Project's blocking counters and sc_eligible
    (calculations open_blocking_counts / sc_eligibility)."""
    pid = p["id"]
    ls = mj = mn = 0
    for i in store.punch_items.values():
        if i["project_id"] != pid or i["status"] not in BLOCKING:
            continue
        if i["severity"] == "LIFE_SAFETY":
            ls += 1
        elif i["severity"] == "MAJOR":
            mj += 1
        elif i["severity"] == "MINOR":
            mn += 1
    trades = project_trades(pid)
    eligible = (
        ls == 0
        and mj == 0
        and mn <= MINOR_OPEN_ALLOWANCE
        and all(t["has_completed_walk"] for t in trades)
    )
    return {
        "open_life_safety_count": ls,
        "open_major_count": mj,
        "open_minor_count": mn,
        "sc_eligible": eligible,
    }


def apply_changes(entity, direct, derive):
    """Apply direct writes first, then derive computed fields from the NEW
    state, then touch at most once. `derive` is a zero-arg callable so the
    recomputation always observes the direct writes (e.g. a lien-waiver status
    flip feeds closeout_ready in the same mutation)."""
    changed = False
    for k, v in (direct or {}).items():
        if entity.get(k) != v:
            entity[k] = v
            changed = True
    for k, v in (derive() or {}).items():
        if entity.get(k) != v:
            entity[k] = v
            changed = True
    if changed:
        touch(entity)


def recompute_trade(t, direct=None):
    apply_changes(t, direct, lambda: trade_derived(t))


def recompute_project(p, direct=None):
    apply_changes(p, direct, lambda: project_derived(p))


def maybe_advance_project(p):
    """CLOSEOUT_IN_PROGRESS -> FINAL_RELEASE_PENDING cascade: fires when the
    last unready trade's closeout_ready has flipped to true (PRD 2.8, 3.5)."""
    if p["status"] != "CLOSEOUT_IN_PROGRESS":
        return
    trades = project_trades(p["id"])
    if trades and all(t["closeout_ready"] for t in trades):
        p["status"] = "FINAL_RELEASE_PENDING"
        touch(p)
