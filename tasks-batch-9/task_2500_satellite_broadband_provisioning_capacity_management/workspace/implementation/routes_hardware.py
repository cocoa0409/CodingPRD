"""Terminal logistics and self-installation (PRD 3.4)."""

from flask import Blueprint

import accounts
import capacity
import serialize
from auth import own_terminal, roles
from clock import clock
from constants import (
    API_PREFIX,
    RETURN_CONDITIONS,
    RETURN_EVENTS,
    SLOT_OCCUPYING_STATES,
    TERMINAL_DAMAGE_FEE_CENTS,
    TERMINAL_STATES,
)
from db import db, new_record, touch
from errors import fail
from numeric import dec, q
from response import list_response, object_response
from validators import (
    body_dict,
    filter_enum,
    filter_value,
    opt_enum,
    pagination,
    paginate,
    req_dt,
    req_enum,
    req_int,
    req_str,
)

bp = Blueprint("hardware", __name__, url_prefix=API_PREFIX)


def find_terminal(terminal_id):
    record = db.terminals.get(terminal_id)
    if record is None:
        fail("ERR_TERMINAL_NOT_FOUND", "Terminal not found.")
    return record


def _assert_serial_free(serial_number):
    for existing in db.terminals.values():
        if existing["serial_number"] == serial_number:
            fail("ERR_DUPLICATE_TERMINAL_SERIAL", "serial_number is already recorded.")


# --------------------------------------------------------------- shipments ----

@bp.post("/terminals")
@roles("LogisticsCoordinator")
def ship_terminal():
    body = body_dict()
    serial_number = req_str(body, "serial_number", 1, 40)
    subscriber_id = req_str(body, "subscriber_id", 1, 100)
    warranty_expires_at = req_dt(body, "warranty_expires_at")

    if subscriber_id not in db.subscribers:
        fail("ERR_SUBSCRIBER_NOT_FOUND", "Subscriber not found.")
    _assert_serial_free(serial_number)

    record = new_record()
    record.update(
        {
            "serial_number": serial_number,
            "subscriber_id": subscriber_id,
            "replaces_terminal_id": None,
            "warranty_expires_at": warranty_expires_at,
            "terminal_state": "SHIPPED",
            "installed_at": None,
            "ownership_changed_at": None,
            "return_condition": None,
        }
    )
    db.terminals[record["id"]] = record
    return object_response(serialize.terminal(record), 201)


@bp.get("/terminals/<terminal_id>")
@roles("LogisticsCoordinator", "ProvisioningAgent", "NetworkOpsEngineer", "Subscriber")
def read_terminal(terminal_id):
    own_terminal(terminal_id)
    return object_response(serialize.terminal(find_terminal(terminal_id)))


@bp.get("/terminals")
@roles("LogisticsCoordinator", "ProvisioningAgent", "NetworkOpsEngineer", "Subscriber")
def list_terminals():
    limit, offset = pagination()
    subscriber_id = filter_value("subscriber_id")
    replaces_terminal_id = filter_value("replaces_terminal_id")
    state = filter_enum("terminal_state", TERMINAL_STATES)

    records = serialize.default_order(list(db.terminals.values()))
    if subscriber_id is not None:
        records = [r for r in records if r["subscriber_id"] == subscriber_id]
    if replaces_terminal_id is not None:
        records = [r for r in records if r["replaces_terminal_id"] == replaces_terminal_id]
    if state is not None:
        records = [r for r in records if r["terminal_state"] == state]

    page = paginate(records, limit, offset)
    return list_response(
        serialize.collection(page, serialize.terminal), limit, offset, len(records)
    )


@bp.post("/terminals/<terminal_id>/deliver")
@roles("LogisticsCoordinator")
def deliver_terminal(terminal_id):
    record = find_terminal(terminal_id)
    if record["terminal_state"] != "SHIPPED":
        fail("ERR_TERMINAL_STATE_INVALID", "Delivery is only legal from SHIPPED.")
    record["terminal_state"] = "DELIVERED"
    touch(record)
    return object_response(serialize.terminal(record))


# ------------------------------------------------------------- sky surveys ----

@bp.post("/terminals/<terminal_id>/obstruction-scans")
@roles("Subscriber", "ProvisioningAgent")
def record_scan(terminal_id):
    own_terminal(terminal_id)
    body = body_dict()
    obstructed = req_int(body, "obstructed_sample_count", minimum=0)
    total = req_int(body, "total_sample_count", minimum=1)
    if obstructed > total:
        fail(
            "ERR_INVALID_REQUEST",
            "'obstructed_sample_count' may not exceed 'total_sample_count'.",
        )

    terminal = find_terminal(terminal_id)
    if terminal["terminal_state"] in ("RETURNED", "REPLACED"):
        fail(
            "ERR_TERMINAL_STATE_INVALID",
            "A survey cannot be recorded on a RETURNED or REPLACED terminal.",
        )

    pct = q(dec(100) * dec(obstructed) / dec(total), 2)
    if pct <= dec("2.00"):
        verdict = "PASS"
    elif pct <= dec("8.00"):
        verdict = "MARGINAL"
    else:
        verdict = "FAIL"

    record = new_record(with_common_fields=False)
    record.update(
        {
            "terminal_id": terminal["id"],
            "obstructed_sample_count": obstructed,
            "total_sample_count": total,
            "obstruction_pct": pct,
            "scan_verdict": verdict,
            "scanned_at": clock.now(),
        }
    )
    db.scans[record["id"]] = record

    # The terminal's latest qualifying verdict has moved.
    touch(terminal)
    return object_response(serialize.obstruction_scan(record), 201)


@bp.get("/terminals/<terminal_id>/obstruction-scans")
@roles("Subscriber", "ProvisioningAgent", "LogisticsCoordinator", "NetworkOpsEngineer")
def list_scans(terminal_id):
    own_terminal(terminal_id)
    limit, offset = pagination()
    terminal = find_terminal(terminal_id)

    records = [s for s in db.scans.values() if s["terminal_id"] == terminal["id"]]
    records.sort(key=lambda s: (s["scanned_at"], s["created_at"], s["_seq"]), reverse=True)

    page = paginate(records, limit, offset)
    return list_response(
        serialize.collection(page, serialize.obstruction_scan),
        limit,
        offset,
        len(records),
    )


# ---------------------------------------------------------- installation ------

@bp.post("/terminals/<terminal_id>/install")
@roles("Subscriber", "ProvisioningAgent")
def install_terminal(terminal_id):
    own_terminal(terminal_id)
    record = find_terminal(terminal_id)
    source_state = record["terminal_state"]
    if source_state not in ("DELIVERED", "TRANSFER_PENDING"):
        fail(
            "ERR_TERMINAL_STATE_INVALID",
            "Installation is only legal from DELIVERED or TRANSFER_PENDING.",
        )

    verdict = serialize.last_scan_verdict(record)
    if verdict is None:
        fail("ERR_OBSTRUCTION_SCAN_REQUIRED", "A qualifying obstruction scan is required.")
    if verdict == "FAIL":
        fail("ERR_OBSTRUCTION_VERDICT_FAIL", "The qualifying obstruction scan failed.")

    record["terminal_state"] = "INSTALLED"
    record["installed_at"] = clock.now()
    touch(record)

    if source_state == "DELIVERED":
        _close_out_rma(record)

    return object_response(serialize.terminal(record))


def _close_out_rma(replacement):
    """The warranty-replacement close-out cascade (PRD 3.4)."""
    replaced_id = replacement["replaces_terminal_id"]
    if replaced_id is None:
        return
    replaced = db.terminals.get(replaced_id)
    if replaced is None or replaced["terminal_state"] != "RMA_PENDING":
        return

    # hop 1 — the faulty unit retires
    replaced["terminal_state"] = "REPLACED"
    touch(replaced)

    # hop 2 — its suspended subscription resumes on the new hardware
    for subscription in capacity.ordered_subscriptions_on_terminal(replaced["id"]):
        if subscription["service_state"] != "SUSPENDED":
            continue
        subscription["terminal_id"] = replacement["id"]
        subscription["service_state"] = "ACTIVE"
        subscription["suspension_reason"] = None
        touch(subscription)
        accounts.settle_after_resumption(db.subscribers.get(subscription["subscriber_id"]))

        # hops 3 and 4 — the beam re-absorbs the megabits, its cells recompute
        beam = capacity.beam_of_subscription(subscription)
        capacity.recompute_beam(beam)
        capacity.recompute_cells_of_beam(beam)


# ------------------------------------------------------------------ returns ---

@bp.post("/terminals/<terminal_id>/return")
@roles("LogisticsCoordinator")
def return_terminal(terminal_id):
    body = body_dict()
    event = req_enum(body, "event", RETURN_EVENTS)
    condition = opt_enum(body, "condition", RETURN_CONDITIONS)
    if event == "RECEIVE" and condition is None:
        fail("ERR_INVALID_REQUEST", "'condition' is required when event is RECEIVE.")

    record = find_terminal(terminal_id)

    if event == "INITIATE":
        if record["terminal_state"] not in ("DELIVERED", "INSTALLED", "RMA_PENDING"):
            fail(
                "ERR_TERMINAL_STATE_INVALID",
                "A return can only be initiated from DELIVERED, INSTALLED or RMA_PENDING.",
            )
        record["terminal_state"] = "RETURN_INITIATED"
        touch(record)
    else:
        if record["terminal_state"] != "RETURN_INITIATED":
            fail(
                "ERR_TERMINAL_STATE_INVALID",
                "Receipt is only legal from RETURN_INITIATED.",
            )
        record["terminal_state"] = "RETURNED"
        record["return_condition"] = condition
        touch(record)
        if condition == "DAMAGED":
            subscriber = db.subscribers.get(record["subscriber_id"])
            if subscriber is not None:
                subscriber["pending_charge_cents"] += TERMINAL_DAMAGE_FEE_CENTS
                touch(subscriber)

    return object_response(serialize.terminal(record))


# ------------------------------------------------------ warranty replacement ---

@bp.post("/terminals/<terminal_id>/warranty-replacement")
@roles("LogisticsCoordinator")
def warranty_replacement(terminal_id):
    body = body_dict()
    serial_number = req_str(body, "replacement_serial_number", 1, 40)
    warranty_expires_at = req_dt(body, "replacement_warranty_expires_at")

    faulty = find_terminal(terminal_id)
    source_state = faulty["terminal_state"]
    if source_state not in ("DELIVERED", "INSTALLED"):
        fail(
            "ERR_TERMINAL_STATE_INVALID",
            "A warranty replacement is only legal from DELIVERED or INSTALLED.",
        )
    if faulty["warranty_expires_at"] <= clock.now():
        fail("ERR_WARRANTY_EXPIRED", "The terminal's warranty has expired.")
    _assert_serial_free(serial_number)

    replacement = new_record()
    replacement.update(
        {
            "serial_number": serial_number,
            "subscriber_id": faulty["subscriber_id"],
            "replaces_terminal_id": faulty["id"],
            "warranty_expires_at": warranty_expires_at,
            "terminal_state": "SHIPPED",
            "installed_at": None,
            "ownership_changed_at": None,
            "return_condition": None,
        }
    )
    db.terminals[replacement["id"]] = replacement

    faulty["terminal_state"] = "RMA_PENDING"
    touch(faulty)

    if source_state == "INSTALLED":
        for subscription in capacity.ordered_subscriptions_on_terminal(faulty["id"]):
            if subscription["service_state"] not in ("PENDING_ACTIVATION", "ACTIVE"):
                continue
            subscription["service_state"] = "SUSPENDED"
            subscription["suspension_reason"] = "RMA_IN_FLIGHT"
            touch(subscription)
            beam = capacity.beam_of_subscription(subscription)
            capacity.recompute_beam(beam)
            capacity.recompute_cells_of_beam(beam)
            accounts.settle_after_suspension(
                db.subscribers.get(subscription["subscriber_id"])
            )

    return object_response(serialize.terminal(replacement), 201)


# ----------------------------------------------------------------- transfer ---

@bp.post("/terminals/<terminal_id>/transfer")
@roles("ProvisioningAgent")
def transfer_terminal(terminal_id):
    body = body_dict()
    new_subscriber_id = req_str(body, "new_subscriber_id", 1, 100)

    if new_subscriber_id not in db.subscribers:
        fail("ERR_SUBSCRIBER_NOT_FOUND", "Subscriber not found.")

    record = find_terminal(terminal_id)
    if record["terminal_state"] != "INSTALLED":
        fail("ERR_TERMINAL_STATE_INVALID", "Transfer is only legal from INSTALLED.")
    for subscription in capacity.ordered_subscriptions_on_terminal(record["id"]):
        if subscription["service_state"] in SLOT_OCCUPYING_STATES:
            fail(
                "ERR_TERMINAL_STATE_INVALID",
                "The terminal is still carrying an active service.",
            )
    if new_subscriber_id == record["subscriber_id"]:
        fail(
            "ERR_TERMINAL_SUBSCRIBER_MISMATCH",
            "new_subscriber_id must differ from the current custodian.",
        )

    record["terminal_state"] = "TRANSFER_PENDING"
    record["subscriber_id"] = new_subscriber_id
    record["ownership_changed_at"] = clock.now()
    touch(record)
    return object_response(serialize.terminal(record))
