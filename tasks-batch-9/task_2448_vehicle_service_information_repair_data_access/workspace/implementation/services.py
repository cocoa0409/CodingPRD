"""Shared domain services: audit trail, listing, and the cascade machinery.

PRD 2.10: cascades run immediately and synchronously inside the originating
request, in numbered hops, each hop caused by the one before it.  The audit row
of the row the operation acts on directly is appended first (PRD 3.2, 3.5, 3.6),
then each hop's rows in hop order.
"""

from calc import (
    gateway_access_fee,
    recompute_seat_ledger,
    stamp_shop_coverage,
)
from errors import err
from store import store

# -- audit trail ----------------------------------------------------------


def append_audit(actor_role, actor_user_id, subject_entity, subject_id, event_type, detail=None):
    row = store.base_row(common=False)
    row["actor_role"] = actor_role
    row["actor_user_id"] = actor_user_id
    row["subject_entity"] = subject_entity
    row["subject_id"] = subject_id
    row["event_type"] = event_type
    row["detail"] = detail
    row["occurred_at"] = store.now_iso()
    store.audit_events[row["id"]] = row
    return row


# -- listing --------------------------------------------------------------


def sorted_rows(rows):
    """Default ordering for list endpoints is created_at ascending (PRD 2.3)."""
    return sorted(rows, key=lambda row: (row["created_at"], row["_seq"]))


def paginate(rows, limit, offset):
    total = len(rows)
    return rows[offset : offset + limit], total


# -- lookups --------------------------------------------------------------


def find(collection, row_id, error_id):
    if not isinstance(row_id, str):
        raise err(error_id)
    row = collection.get(row_id)
    if row is None:
        raise err(error_id)
    return row


def shop_of_session(session):
    seat = store.seat_assignments.get(session["seat_assignment_id"])
    if seat is None:
        return None
    entitlement = store.entitlements.get(seat["entitlement_id"])
    if entitlement is None:
        return None
    return store.shops.get(entitlement["shop_id"])


def technician_of_session(session):
    seat = store.seat_assignments.get(session["seat_assignment_id"])
    if seat is None:
        return None
    return store.technicians.get(seat["technician_id"])


def jobs_of_session(session):
    return sorted_rows(
        [job for job in store.jobs.values() if job["session_id"] == session["id"]]
    )


def sessions_of_seat(seat):
    return sorted_rows(
        [
            session
            for session in store.gateway_sessions.values()
            if session["seat_assignment_id"] == seat["id"]
        ]
    )


def seats_of_entitlement(entitlement):
    return sorted_rows(
        [
            seat
            for seat in store.seat_assignments.values()
            if seat["entitlement_id"] == entitlement["id"]
        ]
    )


# -- pin counts -----------------------------------------------------------


def increment_pin_count(version_id):
    version = store.publication_versions.get(version_id)
    if version is not None:
        version["active_pin_count"] = version["active_pin_count"] + 1


def decrement_pin_count(version_id):
    version = store.publication_versions.get(version_id)
    if version is not None:
        version["active_pin_count"] = version["active_pin_count"] - 1


# -- job cascade ----------------------------------------------------------


def abort_job(job, abort_reason, decrement_pin, actor_role, actor_user_id):
    job["status"] = "ABORTED"
    job["abort_reason"] = abort_reason
    store.touch(job)
    if decrement_pin:
        decrement_pin_count(job["pinned_publication_version_id"])
    append_audit(
        actor_role,
        actor_user_id,
        "ModuleProgrammingJob",
        job["id"],
        "JOB_ABORTED",
        "reason=%s" % abort_reason,
    )


def abort_session_jobs(session, abort_reason, abort_from, decrement_from, actor_role, actor_user_id):
    for job in jobs_of_session(session):
        if job["status"] in abort_from:
            abort_job(job, abort_reason, job["status"] in decrement_from, actor_role, actor_user_id)


# -- session cascade ------------------------------------------------------


def release_tool(session):
    tool = store.diagnostic_tools.get(session["diagnostic_tool_id"])
    if tool is not None and tool.get("occupied_by_session_id") == session["id"]:
        tool["status"] = "IDLE"
        tool["occupied_by_session_id"] = None
        store.touch(tool)


def price_and_close_session(
    session,
    new_status,
    termination_reason,
    actor_role,
    actor_user_id,
    audit_event_type,
    audit_detail=None,
):
    """Every exit from ACTIVE prices the session (PRD 3.7) and releases the tool."""
    base, discount, surcharge, total = gateway_access_fee(session)
    session["status"] = new_status
    session["base_subtotal_cents"] = base
    session["discount_cents"] = discount
    session["surcharge_cents"] = surcharge
    session["total_access_fee_cents"] = total
    if termination_reason is not None:
        session["termination_reason"] = termination_reason
    store.touch(session)

    shop = shop_of_session(session)
    if shop is not None:
        shop["gateway_fee_accrued_cents"] = shop["gateway_fee_accrued_cents"] + total
        store.touch(shop)

    release_tool(session)
    append_audit(
        actor_role, actor_user_id, "GatewaySession", session["id"], audit_event_type, audit_detail
    )


# -- seat cascade ---------------------------------------------------------


def cascade_revoke_seats(
    seats, revocation_reason, termination_reason, actor_role, actor_user_id
):
    """Revoke seats, then terminate their ACTIVE sessions, then abort those jobs.

    `actor_role`/`actor_user_id` label the SEAT_REVOKED rows -- they are the
    operator on an explicit revoke and `SYSTEM` when the revocation itself
    cascaded.  Everything deeper than the seat is always a cascade, so those
    rows are written with `SYSTEM` and a null actor (PRD 2.10).

    The three hops run breadth-first so that every session is priced before any
    job the cascade is about to abort has left its billable status.
    """
    revoked = []
    for seat in seats:
        if seat["status"] != "ACTIVE":
            continue
        seat["status"] = "REVOKED"
        seat["revocation_reason"] = revocation_reason
        store.touch(seat)
        entitlement = store.entitlements.get(seat["entitlement_id"])
        if entitlement is not None:
            recompute_seat_ledger(entitlement)
            store.touch(entitlement)
        append_audit(
            actor_role,
            actor_user_id,
            "SeatAssignment",
            seat["id"],
            "SEAT_REVOKED",
            "reason=%s" % revocation_reason,
        )
        revoked.append(seat)

    terminated = []
    for seat in revoked:
        for session in sessions_of_seat(seat):
            if session["status"] == "ACTIVE":
                terminated.append(session)
    for session in terminated:
        price_and_close_session(
            session,
            "TERMINATED",
            termination_reason,
            "SYSTEM",
            None,
            "SESSION_TERMINATED",
            "reason=%s" % termination_reason,
        )
    for session in terminated:
        abort_session_jobs(
            session,
            "SESSION_TERMINATED",
            ("QUEUED", "IN_PROGRESS", "REVALIDATION_REQUIRED"),
            ("QUEUED", "IN_PROGRESS"),
            "SYSTEM",
            None,
        )
    return revoked


# -- entitlement settlement ----------------------------------------------


def settle_entitlement(entitlement, new_status, actor_role, actor_user_id):
    """The FINAL variant of the entitlement charge plus the refund credit."""
    from calc import final_charge

    shop = store.shops.get(entitlement["shop_id"])
    license_row = store.licenses.get(entitlement["license_id"])
    settled = final_charge(entitlement, shop, license_row)

    entitlement["status"] = new_status
    entitlement["settled_cents"] = settled
    entitlement["settlement_status"] = "SETTLED"
    store.touch(entitlement)

    refund = entitlement["charged_cents"] - settled
    if shop is not None:
        shop["data_credit_balance_cents"] = shop["data_credit_balance_cents"] + refund
        store.touch(shop)

    append_audit(
        actor_role, actor_user_id, "ShopEntitlement", entitlement["id"], "ENTITLEMENT_SETTLED"
    )
    if shop is not None:
        stamp_shop_coverage(shop)


# -- publication version job cascade -------------------------------------


def cascade_versions_departure(version, abort_reason, actor_role, actor_user_id):
    """Jobs pinned to a version leaving PUBLISHED (supersession or recall)."""
    jobs = sorted_rows(
        [
            job
            for job in store.jobs.values()
            if job["pinned_publication_version_id"] == version["id"]
        ]
    )
    for job in jobs:
        if job["status"] == "IN_PROGRESS":
            job["status"] = "REVALIDATION_REQUIRED"
            store.touch(job)
            decrement_pin_count(version["id"])
            append_audit(
                actor_role,
                actor_user_id,
                "ModuleProgrammingJob",
                job["id"],
                "JOB_REVALIDATION_REQUIRED",
            )
        elif job["status"] == "QUEUED":
            abort_job(job, abort_reason, True, actor_role, actor_user_id)
