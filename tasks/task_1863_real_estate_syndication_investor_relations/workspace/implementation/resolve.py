"""Path-parameter resolution, left to right (PRD 2.5).

A child id that exists but not beneath the named parent is treated as not found.
"""
from db import db
from errors import raise_error


def syndication(sid):
    o = db["syndications"].get(sid)
    if o is None:
        raise_error("ERR_SYNDICATION_NOT_FOUND", f"syndication not found: {sid}")
    return o


def investor(iid):
    o = db["investors"].get(iid)
    if o is None:
        raise_error("ERR_INVESTOR_NOT_FOUND", f"investor not found: {iid}")
    return o


def property_(pid):
    o = db["properties"].get(pid)
    if o is None:
        raise_error("ERR_PROPERTY_NOT_FOUND", f"property not found: {pid}")
    return o


def offering(sid, oid):
    syndication(sid)
    o = db["offerings"].get(oid)
    if o is None or o["syndication_id"] != sid:
        raise_error("ERR_OFFERING_NOT_FOUND", f"offering not found: {oid}")
    return o


def subscription(sid, oid, subid):
    offering(sid, oid)
    o = db["subscriptions"].get(subid)
    if o is None or o["offering_id"] != oid:
        raise_error("ERR_SUBSCRIPTION_NOT_FOUND", f"subscription not found: {subid}")
    return o


def document(sid, oid, subid, did):
    subscription(sid, oid, subid)
    o = db["documents"].get(did)
    if o is None or o["subscription_id"] != subid:
        raise_error("ERR_DOCUMENT_NOT_FOUND", f"document not found: {did}")
    return o


def capital_call(sid, oid, cid):
    offering(sid, oid)
    o = db["capital_calls"].get(cid)
    if o is None or o["offering_id"] != oid:
        raise_error("ERR_CAPITAL_CALL_NOT_FOUND", f"capital call not found: {cid}")
    return o


def contribution(sid, oid, ccid, cid):
    capital_call(sid, oid, ccid)
    o = db["contributions"].get(cid)
    if o is None or o["capital_call_id"] != ccid:
        raise_error("ERR_CONTRIBUTION_NOT_FOUND", f"contribution not found: {cid}")
    return o


def quarterly_report(sid, oid, rid):
    offering(sid, oid)
    o = db["quarterly_reports"].get(rid)
    if o is None or o["offering_id"] != oid:
        raise_error("ERR_QUARTERLY_REPORT_NOT_FOUND", f"quarterly report not found: {rid}")
    return o


def distribution(sid, oid, did):
    offering(sid, oid)
    o = db["distributions"].get(did)
    if o is None or o["offering_id"] != oid:
        raise_error("ERR_DISTRIBUTION_NOT_FOUND", f"distribution not found: {did}")
    return o


def distribution_line(sid, oid, did, lid):
    distribution(sid, oid, did)
    o = db["distribution_lines"].get(lid)
    if o is None or o["distribution_id"] != did:
        raise_error("ERR_NOT_FOUND", f"distribution line not found: {lid}")
    return o


def capital_event(sid, pid, eid):
    syndication(sid)
    property_(pid)
    o = db["capital_events"].get(eid)
    if o is None or o["property_id"] != pid:
        raise_error("ERR_CAPITAL_EVENT_NOT_FOUND", f"capital event not found: {eid}")
    return o


def k1_package(sid, oid, kid):
    offering(sid, oid)
    o = db["k1_packages"].get(kid)
    if o is None or o["offering_id"] != oid:
        raise_error("ERR_K1_PACKAGE_NOT_FOUND", f"K-1 package not found: {kid}")
    return o


def transfer_request(sid, oid, subid, tid):
    subscription(sid, oid, subid)
    o = db["transfer_requests"].get(tid)
    if o is None or o["from_subscription_id"] != subid:
        raise_error("ERR_TRANSFER_REQUEST_NOT_FOUND", f"transfer request not found: {tid}")
    return o


def portal_session(session_id):
    o = db["portal_sessions"].get(session_id)
    if o is None:
        raise_error("ERR_NOT_FOUND", f"portal session not found: {session_id}")
    return o
