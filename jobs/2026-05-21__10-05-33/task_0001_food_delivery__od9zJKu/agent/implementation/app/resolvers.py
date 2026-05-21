"""Path-id resolution helpers (left-to-right ERR_NOT_FOUND ordering)."""
from __future__ import annotations

from .envelope import err_not_found
from .store import store


def restaurant(rid: str) -> dict:
    r = store.restaurants.get(rid)
    if not r:
        raise err_not_found(f"Restaurant '{rid}' not found")
    return r


def menu_item(mid: str) -> dict:
    m = store.menu_items.get(mid)
    if not m:
        raise err_not_found(f"MenuItem '{mid}' not found")
    return m


def rider(rid: str) -> dict:
    r = store.riders.get(rid)
    if not r:
        raise err_not_found(f"Rider '{rid}' not found")
    return r


def customer(cid: str) -> dict:
    c = store.customers.get(cid)
    if not c:
        raise err_not_found(f"Customer '{cid}' not found")
    return c


def order(oid: str) -> dict:
    o = store.orders.get(oid)
    if not o:
        raise err_not_found(f"Order '{oid}' not found")
    return o


def assignment(aid: str) -> dict:
    a = store.assignments.get(aid)
    if not a:
        raise err_not_found(f"Assignment '{aid}' not found")
    return a


def route_group(gid: str) -> dict:
    g = store.route_groups.get(gid)
    if not g:
        raise err_not_found(f"RouteGroup '{gid}' not found")
    return g


def ret(rid: str) -> dict:
    r = store.returns.get(rid)
    if not r:
        raise err_not_found(f"Return '{rid}' not found")
    return r


def fine(fid: str) -> dict:
    f = store.fines.get(fid)
    if not f:
        raise err_not_found(f"Fine '{fid}' not found")
    return f


def work_order(wid: str) -> dict:
    w = store.work_orders.get(wid)
    if not w:
        raise err_not_found(f"WorkOrder '{wid}' not found")
    return w
