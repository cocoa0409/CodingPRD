"""Parcel lifecycle: deposit, confirm, retry, wrong-deposit correction,
pickup workflow (initiate/confirm/cancel), recall, return, dispose, waive-fee."""

import random
from datetime import timedelta

from clock import iso, now, parse_iso
from constants import (
    MAX_RETRY,
    WRONG_DEPOSIT_GRACE_SECONDS,
    PICKUP_PENDING_TIMEOUT_SECONDS,
    LONG_STAY_THRESHOLD_HOURS,
    RECALL_WINDOW_HOURS,
    DISPOSE_THRESHOLD_HOURS,
)
from db import DB, new_id
from errors import (
    APIError,
    invalid_request,
    not_found,
    state_changed,
    forbidden,
)
from services.audit import append_audit, append_compartment_event
from services.courier import (
    get_courier,
    maybe_auto_restrict,
    maybe_auto_blacklist,
)
from services.fee import (
    compute_fee_cents,
    create_fee_record,
    latest_provisional,
    latest_fee,
    serialize_fee,
)
from services.machine import (
    get_machine,
    is_degraded,
    machine_warning_level,
    per_size_level,
    per_size_ratio,
)
from services.util import (
    stamp_create,
    stamp_update,
    require_field,
    opt_field,
    check_version,
)


SIZE_RANK = {"SMALL": 0, "MEDIUM": 1, "LARGE": 2}


def get_parcel(parcel_id: str):
    p = DB.parcels.get(parcel_id)
    if not p:
        raise not_found(f"Parcel not found: {parcel_id}")
    return p


def serialize_parcel(p: dict) -> dict:
    pf = latest_provisional(p["id"])
    ff = latest_fee(p["id"])
    final_ff = None
    # final variant if exists
    for fid in DB.parcel_fees.get(p["id"], []):
        rec = DB.fee_records[fid]
        if rec.get("variant") == "FINAL":
            if final_ff is None or (rec.get("created_at") or "") > (final_ff.get("created_at") or ""):
                final_ff = rec

    return {
        "id": p["id"],
        "tracking_no": p.get("tracking_no"),
        "courier_id": p.get("courier_id"),
        "locker_machine_id": p.get("locker_machine_id"),
        "compartment_id": p.get("compartment_id"),
        "recipient_phone": p.get("recipient_phone"),
        "required_size": p.get("required_size"),
        "pickup_code": p.get("pickup_code"),
        "deposited_at": p.get("deposited_at"),
        "picked_up_at": p.get("picked_up_at"),
        "status": p.get("status"),
        "failed_open_attempts": p.get("failed_open_attempts", 0),
        "replaces_parcel_id": p.get("replaces_parcel_id"),
        "correction_origin": p.get("correction_origin", "NONE"),
        "provisional_overtime_fee": (pf["amount_cents"] if pf else None),
        "final_overtime_fee": (final_ff["amount_cents"] if final_ff else None),
        "fee_waived": p.get("fee_waived", False),
        "fee_waiver_reason": p.get("fee_waiver_reason", "NONE"),
        "created_at": p.get("created_at"),
        "updated_at": p.get("updated_at"),
        "version": p.get("version", 0),
    }


def _gen_pickup_code() -> str:
    return f"{random.randint(0, 999999):06d}"


def _select_compartment(machine_id: str, required_size: str):
    """Among AVAILABLE compartments with size >= required, lowest occupancy ratio for that
    compartment's size class, ties broken by slot_label asc."""
    candidates = [
        c for c in DB.compartments.values()
        if c["locker_machine_id"] == machine_id
        and c.get("status") == "AVAILABLE"
        and SIZE_RANK[c.get("size")] >= SIZE_RANK[required_size]
    ]
    if not candidates:
        return None
    # Compute occupancy ratio per candidate's size class
    def keyfn(c):
        ratio = per_size_ratio(machine_id, c["size"])
        return (ratio, c.get("slot_label") or "")
    candidates.sort(key=keyfn)
    return candidates[0]


# --- Deposit flow -----------------------------------------------------------


def begin_deposit(payload: dict, actor_user_id: str) -> dict:
    """POST /parcels — Courier."""
    tracking_no = require_field(payload, "tracking_no")
    machine_id = require_field(payload, "locker_machine_id")
    recipient_phone = require_field(payload, "recipient_phone")
    required_size = require_field(payload, "required_size")
    if required_size not in ("SMALL", "MEDIUM", "LARGE"):
        raise invalid_request("required_size must be SMALL|MEDIUM|LARGE")

    # tracking_no live-uniqueness check (excludes WRONG_DEPOSIT_VOID)
    for existing in DB.parcels.values():
        if (
            existing.get("tracking_no") == tracking_no
            and existing.get("status") != "WRONG_DEPOSIT_VOID"
        ):
            raise APIError(
                "ERR_DUPLICATE_PAYMENT_EVENT",
                f"tracking_no '{tracking_no}' already exists on a live parcel",
                409,
            )

    machine = get_machine(machine_id)

    # priority 4: degraded mode
    if is_degraded(machine):
        raise APIError("ERR_MACHINE_OFFLINE_DEGRADED",
                       "Machine is offline or below firmware baseline", 409)

    # priority 6: courier blacklist gating
    courier = get_courier(actor_user_id)
    bs = courier.get("blacklist_status")
    warn_level = machine_warning_level(machine_id)
    if bs == "BLACKLISTED":
        raise APIError("ERR_COURIER_BLACKLISTED",
                       "Courier is BLACKLISTED; deposits rejected", 403)
    if bs == "RESTRICTED":
        # If size is SMALL -> ERR_COURIER_BLACKLISTED
        if required_size == "SMALL":
            raise APIError("ERR_COURIER_BLACKLISTED",
                           "RESTRICTED couriers cannot deposit SMALL parcels", 403)
        # If machine non-NORMAL -> ERR_COURIER_RESTRICTED
        if warn_level != "NORMAL":
            raise APIError("ERR_COURIER_RESTRICTED",
                           "RESTRICTED couriers cannot deposit at non-NORMAL machines", 403)

    # priority 9: at least one compartment fits (size match exists AT ALL among non-DECOMMISSIONED)
    has_size_fit = any(
        c["locker_machine_id"] == machine_id
        and c.get("status") != "DECOMMISSIONED"
        and SIZE_RANK[c.get("size")] >= SIZE_RANK[required_size]
        for c in DB.compartments.values()
    )
    if not has_size_fit:
        raise APIError("ERR_NO_COMPARTMENT_FITS",
                       "No compartment with sufficient size for this deposit", 409)

    # priority 10: capacity gating per the requested size
    size_level = per_size_level(machine_id, required_size)
    if size_level == "FULL_BLOCK_DEPOSITS":
        raise APIError("ERR_CAPACITY_BLOCKED",
                       f"Capacity for size {required_size} is at full-block threshold", 409)

    # Now attempt to select a compartment (deterministic)
    chosen = _select_compartment(machine_id, required_size)
    if chosen is None:
        # All available compartments are not AVAILABLE (race) -> 409 already-reserved
        raise APIError("ERR_COMPARTMENT_ALREADY_RESERVED",
                       "No AVAILABLE compartment for the selected size at this moment", 409)

    # Create parcel in DRAFT
    pid = new_id()
    base = stamp_create()
    parcel = {
        "id": pid,
        "tracking_no": tracking_no,
        "courier_id": actor_user_id,
        "locker_machine_id": machine_id,
        "compartment_id": chosen["id"],
        "recipient_phone": recipient_phone,
        "required_size": required_size,
        "pickup_code": None,
        "deposited_at": None,
        "picked_up_at": None,
        "status": "DRAFT",
        "failed_open_attempts": 0,
        "replaces_parcel_id": None,
        "correction_origin": "NONE",
        "fee_waived": False,
        "fee_waiver_reason": "NONE",
        **base,
    }
    DB.parcels[pid] = parcel

    # Reserve compartment
    chosen["status"] = "RESERVED"
    chosen["current_parcel_id"] = pid
    stamp_update(chosen)

    return parcel


def confirm_deposit(parcel_id: str, payload: dict, actor_user_id: str) -> dict:
    p = get_parcel(parcel_id)
    check_version(p, opt_field(payload, "version"))

    # Ownership
    if p.get("courier_id") != actor_user_id:
        raise APIError("ERR_NOT_COURIER_OWNER",
                       "Only the originating courier may confirm deposit", 403)
    courier = get_courier(actor_user_id)
    if courier.get("blacklist_status") == "BLACKLISTED":
        raise APIError("ERR_COURIER_BLACKLISTED",
                       "Courier is BLACKLISTED", 403)

    if p.get("status") != "DRAFT":
        raise state_changed(f"Parcel must be DRAFT (currently {p.get('status')})")

    if p.get("failed_open_attempts", 0) >= MAX_RETRY:
        raise APIError("ERR_RETRY_EXHAUSTED",
                       f"Retry exhausted: {p['failed_open_attempts']} >= {MAX_RETRY}", 409)

    compartment = DB.compartments.get(p.get("compartment_id"))
    if not compartment:
        raise state_changed("Compartment missing on parcel")
    if compartment.get("status") != "RESERVED":
        raise APIError("ERR_COMPARTMENT_ALREADY_RESERVED",
                       "Compartment is no longer reserved", 409)

    # Advance
    n = iso(now())
    p["status"] = "DEPOSITED"
    p["deposited_at"] = n
    p["pickup_code"] = _gen_pickup_code()
    stamp_update(p)

    compartment["status"] = "OCCUPIED"
    stamp_update(compartment)

    append_compartment_event(compartment["id"], p["id"], "Courier", actor_user_id,
                             "DEPOSIT_OPEN_OK")
    append_audit("Courier", actor_user_id, "COMPARTMENT_OPEN", "Parcel", p["id"],
                 {"event": "DEPOSIT_OPEN_OK",
                  "compartment_id": compartment["id"]})
    return p


def retry_open(parcel_id: str, payload: dict, actor_user_id: str) -> dict:
    p = get_parcel(parcel_id)
    check_version(p, opt_field(payload, "version"))
    if p.get("courier_id") != actor_user_id:
        raise APIError("ERR_NOT_COURIER_OWNER",
                       "Only the originating courier may retry-open", 403)
    if p.get("status") != "DRAFT":
        raise state_changed(f"retry-open only valid in DRAFT (currently {p.get('status')})")
    p["failed_open_attempts"] = p.get("failed_open_attempts", 0) + 1
    stamp_update(p)
    compartment = DB.compartments.get(p.get("compartment_id"))
    if compartment:
        append_compartment_event(compartment["id"], p["id"], "Courier", actor_user_id,
                                 "DEPOSIT_OPEN_FAILED")
    return p


def cancel_deposit(parcel_id: str, payload: dict, actor_user_id: str) -> dict:
    p = get_parcel(parcel_id)
    check_version(p, opt_field(payload, "version"))
    if p.get("courier_id") != actor_user_id:
        raise APIError("ERR_NOT_COURIER_OWNER",
                       "Only the originating courier may cancel deposit", 403)
    if p.get("status") != "DRAFT":
        raise state_changed(f"cancel-deposit only valid in DRAFT (currently {p.get('status')})")
    if p.get("failed_open_attempts", 0) < MAX_RETRY:
        raise APIError("ERR_INVALID_REQUEST",
                       f"cancel-deposit requires retry exhaustion "
                       f"(failed_open_attempts >= {MAX_RETRY})", 400)

    compartment = DB.compartments.get(p.get("compartment_id"))
    if compartment and compartment.get("status") == "RESERVED":
        compartment["status"] = "AVAILABLE"
        compartment["current_parcel_id"] = None
        stamp_update(compartment)
        append_compartment_event(compartment["id"], p["id"], "Courier", actor_user_id,
                                 "DEPOSIT_OPEN_FAILED")

    # Mark parcel terminal-cancelled — keep status as DRAFT but compartment_id null,
    # so it does not count toward courier deposits.
    p["compartment_id"] = None
    stamp_update(p)
    return p


def correct_wrong_deposit(parcel_id: str, payload: dict, actor_user_id: str) -> dict:
    p = get_parcel(parcel_id)
    check_version(p, opt_field(payload, "version"))

    # priority 7: ownership check
    if p.get("courier_id") != actor_user_id:
        raise APIError("ERR_NOT_COURIER_OWNER",
                       "Only the originating courier may correct a wrong deposit", 403)

    # priority 5: state must be DEPOSITED
    if p.get("status") != "DEPOSITED":
        raise APIError("ERR_PARCEL_STATE_CHANGED",
                       f"Parcel has advanced past DEPOSITED (currently {p.get('status')})", 409)

    # priority 8: grace window
    deposited_at = parse_iso(p.get("deposited_at"))
    if deposited_at is None:
        raise state_changed("Parcel has no deposited_at; cannot correct")
    elapsed = (now() - deposited_at).total_seconds()
    if elapsed >= WRONG_DEPOSIT_GRACE_SECONDS:
        raise APIError("ERR_WRONG_DEPOSIT_GRACE_EXPIRED",
                       f"Grace window expired ({elapsed:.0f}s >= {WRONG_DEPOSIT_GRACE_SECONDS}s)", 409)

    new_tracking = require_field(payload, "new_tracking_no")
    new_phone = require_field(payload, "new_recipient_phone")
    new_size = require_field(payload, "new_required_size")
    if new_size not in ("SMALL", "MEDIUM", "LARGE"):
        raise invalid_request("new_required_size must be SMALL|MEDIUM|LARGE")

    # Mark old parcel WRONG_DEPOSIT_VOID
    p["status"] = "WRONG_DEPOSIT_VOID"
    p["fee_waived"] = True
    p["fee_waiver_reason"] = "COURIER_WRONG_DEPOSIT"
    stamp_update(p)

    # Mark provisional fee record (if any) as WAIVED
    pf = latest_provisional(p["id"])
    if pf and pf.get("payment_status") == "UNPAID":
        pf["payment_status"] = "WAIVED"
        stamp_update(pf)
        append_audit("Courier", actor_user_id, "FEE_ADJUSTMENT", "OvertimeFeeRecord", pf["id"],
                     {"reason": "COURIER_WRONG_DEPOSIT", "to_status": "WAIVED"})

    # Successor parcel; same compartment, fresh draft? PRD: compartment stays OCCUPIED
    # current_parcel_id rebound to successor; successor inherits a fresh deposit state.
    compartment = DB.compartments.get(p.get("compartment_id"))
    if not compartment:
        raise state_changed("Compartment missing on parcel during correction")

    sid = new_id()
    base = stamp_create()
    successor = {
        "id": sid,
        "tracking_no": new_tracking,
        "courier_id": actor_user_id,
        "locker_machine_id": p["locker_machine_id"],
        "compartment_id": compartment["id"],
        "recipient_phone": new_phone,
        "required_size": new_size,
        "pickup_code": _gen_pickup_code(),
        # Successor inherits deposited_at = now() (the correction is a fresh deposit visible to recipient)
        "deposited_at": iso(now()),
        "picked_up_at": None,
        "status": "DEPOSITED",
        "failed_open_attempts": 0,
        "replaces_parcel_id": p["id"],
        "correction_origin": "WRONG_DEPOSIT",
        "fee_waived": False,
        "fee_waiver_reason": "NONE",
        **base,
    }
    DB.parcels[sid] = successor

    # Compartment: stays OCCUPIED, current_parcel_id rebound
    compartment["current_parcel_id"] = sid
    stamp_update(compartment)

    append_compartment_event(compartment["id"], sid, "Courier", actor_user_id,
                             "DEPOSIT_OPEN_OK")
    append_audit("Courier", actor_user_id, "COMPARTMENT_OPEN", "Parcel", sid,
                 {"event": "DEPOSIT_OPEN_OK",
                  "correction_origin": "WRONG_DEPOSIT",
                  "replaces_parcel_id": p["id"]})

    # Cascade hop 3: maybe auto-restrict
    maybe_auto_restrict(actor_user_id, "system", "system")

    return successor


# --- Pickup flow ------------------------------------------------------------


def initiate_pickup(parcel_id: str, payload: dict, actor_user_id: str) -> dict:
    p = get_parcel(parcel_id)
    check_version(p, opt_field(payload, "version"))

    method = require_field(payload, "method")
    if method not in ("CODE", "SMS_LINK", "FACE"):
        raise invalid_request("method must be CODE|SMS_LINK|FACE")

    # state check: must be DEPOSITED
    if p.get("status") != "DEPOSITED":
        raise APIError("ERR_PARCEL_STATE_CHANGED",
                       f"Parcel must be DEPOSITED to initiate pickup (currently {p.get('status')})",
                       409)

    # validate compartment
    compartment = DB.compartments.get(p.get("compartment_id"))
    if not compartment or compartment.get("status") != "OCCUPIED":
        raise APIError("ERR_PARCEL_STATE_CHANGED",
                       "Compartment not OCCUPIED", 409)

    # check authentication for CODE method
    success = False
    failure_reason = "NONE"
    if method == "CODE":
        code = payload.get("code")
        if code is None:
            raise invalid_request("code required for CODE method")
        if str(code) == str(p.get("pickup_code")):
            success = True
        else:
            failure_reason = "WRONG_CODE"
    elif method == "SMS_LINK":
        # Simple model: if `link_expired` is explicitly true -> reject; otherwise success.
        if bool(payload.get("link_expired")):
            failure_reason = "EXPIRED_LINK"
        else:
            success = True
    elif method == "FACE":
        # Simple model: success unless `face_match` explicitly False.
        face_match = payload.get("face_match")
        if face_match is False:
            failure_reason = "FACE_MISMATCH"
        else:
            success = True

    # Append PickupCodeAttempt
    aid = new_id()
    DB.pickup_attempts[aid] = {
        "id": aid,
        "created_at": iso(now()),
        "parcel_id": parcel_id,
        "method": method,
        "success": success,
        "failure_reason": failure_reason,
    }

    if not success:
        raise APIError("ERR_INVALID_PICKUP_CODE",
                       f"Authentication failed: {failure_reason}", 409)

    # Successful auth — advance to PICKUP_PENDING, freeze provisional fee
    p["status"] = "PICKUP_PENDING"
    stamp_update(p)
    cutoff_iso = iso(now())
    DB.parcel_pickup_pending_at[p["id"]] = cutoff_iso
    amt = compute_fee_cents(p["deposited_at"], cutoff_iso, p.get("fee_waived", False))
    create_fee_record(p["id"], "PROVISIONAL", cutoff_iso, amt, "UNPAID")
    return p


def cancel_pickup(parcel_id: str, payload: dict, actor_user_id: str) -> dict:
    p = get_parcel(parcel_id)
    check_version(p, opt_field(payload, "version"))
    if p.get("status") != "PICKUP_PENDING":
        raise state_changed(
            f"cancel-pickup only valid in PICKUP_PENDING (currently {p.get('status')})"
        )
    p["status"] = "DEPOSITED"
    stamp_update(p)
    DB.parcel_pickup_pending_at.pop(p["id"], None)
    return p


def pickup_confirm(parcel_id: str, payload: dict, actor_user_id: str) -> dict:
    p = get_parcel(parcel_id)
    check_version(p, opt_field(payload, "version"))
    if p.get("status") != "PICKUP_PENDING":
        raise APIError("ERR_PARCEL_STATE_CHANGED",
                       f"Parcel must be PICKUP_PENDING (currently {p.get('status')})", 409)

    # Fee gate priority 12
    if not p.get("fee_waived", False):
        pf = latest_provisional(p["id"])
        if pf and pf.get("amount_cents", 0) > 0 and pf.get("payment_status") != "PAID":
            raise APIError("ERR_FEE_PAYMENT_REQUIRED",
                           "Provisional overtime fee unpaid", 402)

    compartment = DB.compartments.get(p.get("compartment_id"))
    if not compartment or compartment.get("status") != "OCCUPIED":
        raise APIError("ERR_PARCEL_STATE_CHANGED",
                       "Compartment not OCCUPIED", 409)

    n_iso = iso(now())
    p["status"] = "PICKED_UP"
    p["picked_up_at"] = n_iso
    stamp_update(p)

    # Final fee record (variant=FINAL)
    final_amt = compute_fee_cents(p["deposited_at"], n_iso, p.get("fee_waived", False))
    pf = latest_provisional(p["id"])

    if p.get("fee_waived", False):
        # Waived parcel — final record is created and immediately WAIVED.
        ff = create_fee_record(p["id"], "FINAL", n_iso, final_amt, "WAIVED")
    elif final_amt == 0:
        # No fee due — final marked PAID (no money to collect)
        ff = create_fee_record(p["id"], "FINAL", n_iso, 0, "PAID")
    elif pf and pf.get("payment_status") == "PAID" and final_amt == pf.get("amount_cents", 0):
        # No tier boundary crossed — provisional payment already covers final amount.
        ff = create_fee_record(p["id"], "FINAL", n_iso, final_amt, "PAID")
        ff["payment_external_id"] = pf.get("payment_external_id")
        stamp_update(ff)
    else:
        # Tier boundary crossed: delta needs to be paid; FINAL is created UNPAID with the
        # full final amount. The delta = final - provisional (if any). PRD documents this
        # as 'top-up record with its own UNPAID→PAID flow'.
        ff = create_fee_record(p["id"], "FINAL", n_iso, final_amt, "UNPAID")

    # Compartment release
    compartment["status"] = "AVAILABLE"
    compartment["current_parcel_id"] = None
    stamp_update(compartment)

    append_compartment_event(compartment["id"], p["id"], "Recipient", actor_user_id,
                             "PICKUP_OPEN_OK")
    append_audit("Recipient", actor_user_id, "COMPARTMENT_OPEN", "Parcel", p["id"],
                 {"event": "PICKUP_OPEN_OK"})
    return p


# --- Long-stay / recall / return / dispose ----------------------------------


def recall_parcel(parcel_id: str, payload: dict, actor_user_id: str) -> dict:
    p = get_parcel(parcel_id)
    check_version(p, opt_field(payload, "version"))
    if p.get("courier_id") != actor_user_id:
        raise APIError("ERR_NOT_COURIER_OWNER",
                       "Only the originating courier may recall", 403)
    if p.get("status") != "LONG_STAY":
        raise APIError("ERR_PARCEL_STATE_CHANGED",
                       f"Parcel must be LONG_STAY (currently {p.get('status')})", 409)
    long_stay_at = DB.parcel_long_stay_at.get(p["id"])
    if not long_stay_at:
        raise state_changed("Parcel missing long_stay_at marker")
    elapsed = (now() - parse_iso(long_stay_at)).total_seconds()
    if elapsed >= RECALL_WINDOW_HOURS * 3600:
        raise APIError("ERR_PARCEL_STATE_CHANGED",
                       "Recall window has expired", 409)
    p["status"] = "RECALLED"
    stamp_update(p)
    compartment = DB.compartments.get(p.get("compartment_id"))
    if compartment:
        compartment["status"] = "AVAILABLE"
        compartment["current_parcel_id"] = None
        stamp_update(compartment)
        append_compartment_event(compartment["id"], p["id"], "Courier", actor_user_id,
                                 "RECALL_OPEN_OK")
        append_audit("Courier", actor_user_id, "COMPARTMENT_OPEN", "Parcel", p["id"],
                     {"event": "RECALL_OPEN_OK"})
    p["compartment_id"] = None
    return p


def return_to_sender(parcel_id: str, payload: dict, actor_user_id: str) -> dict:
    p = get_parcel(parcel_id)
    check_version(p, opt_field(payload, "version"))
    if p.get("status") != "LONG_STAY":
        raise APIError("ERR_PARCEL_STATE_CHANGED",
                       f"Parcel must be LONG_STAY (currently {p.get('status')})", 409)
    long_stay_at = DB.parcel_long_stay_at.get(p["id"])
    if not long_stay_at:
        raise state_changed("Parcel missing long_stay_at marker")
    elapsed = (now() - parse_iso(long_stay_at)).total_seconds()
    if elapsed < RECALL_WINDOW_HOURS * 3600:
        raise APIError("ERR_PARCEL_STATE_CHANGED",
                       "Recall window has not yet expired", 409)
    p["status"] = "RETURNED"
    stamp_update(p)
    compartment = DB.compartments.get(p.get("compartment_id"))
    if compartment:
        compartment["status"] = "AVAILABLE"
        compartment["current_parcel_id"] = None
        stamp_update(compartment)
        append_compartment_event(compartment["id"], p["id"], "OperationsAdmin", actor_user_id,
                                 "PICKUP_OPEN_OK")  # not specified explicitly; using PICKUP_OPEN_OK as release
    p["compartment_id"] = None
    return p


def dispose_parcel(parcel_id: str, payload: dict, actor_user_id: str) -> dict:
    p = get_parcel(parcel_id)
    check_version(p, opt_field(payload, "version"))
    if p.get("status") != "LONG_STAY":
        raise APIError("ERR_PARCEL_STATE_CHANGED",
                       f"Parcel must be LONG_STAY (currently {p.get('status')})", 409)
    long_stay_at = DB.parcel_long_stay_at.get(p["id"])
    if not long_stay_at:
        raise state_changed("Parcel missing long_stay_at marker")
    elapsed = (now() - parse_iso(long_stay_at)).total_seconds()
    if elapsed < DISPOSE_THRESHOLD_HOURS * 3600:
        raise APIError("ERR_PARCEL_STATE_CHANGED",
                       "Dispose threshold has not been reached", 409)
    reason = payload.get("reason") or "operations disposal"
    p["status"] = "DISPOSED"
    stamp_update(p)
    compartment = DB.compartments.get(p.get("compartment_id"))
    if compartment:
        compartment["status"] = "AVAILABLE"
        compartment["current_parcel_id"] = None
        stamp_update(compartment)
        append_compartment_event(compartment["id"], p["id"], "OperationsAdmin", actor_user_id,
                                 "DISPOSAL_OPEN_OK")
    append_audit("OperationsAdmin", actor_user_id, "COMPARTMENT_OPEN", "Parcel", p["id"],
                 {"event": "DISPOSAL_OPEN_OK", "reason": reason})
    p["compartment_id"] = None
    return p


# --- Manual fee waiver ------------------------------------------------------


def waive_fee(parcel_id: str, payload: dict, actor_user_id: str):
    p = get_parcel(parcel_id)
    check_version(p, opt_field(payload, "version"))
    reason = payload.get("reason")
    if reason not in ("SYSTEM_FAULT", "COURIER_WRONG_DEPOSIT", "MANUAL_DISPUTE"):
        raise invalid_request("reason must be SYSTEM_FAULT|COURIER_WRONG_DEPOSIT|MANUAL_DISPUTE")
    fee = latest_fee(p["id"])
    if fee is None:
        raise APIError("ERR_INVALID_REQUEST",
                       "No fee record on this parcel to waive", 400)
    if fee.get("payment_status") != "UNPAID":
        raise APIError("ERR_INVALID_REQUEST",
                       f"Fee record is in {fee.get('payment_status')}; only UNPAID records can be waived",
                       400)
    fee["payment_status"] = "WAIVED"
    stamp_update(fee)
    p["fee_waived"] = True
    p["fee_waiver_reason"] = reason
    stamp_update(p)
    append_audit("OperationsAdmin", actor_user_id, "FEE_ADJUSTMENT",
                 "OvertimeFeeRecord", fee["id"],
                 {"reason": reason, "to_status": "WAIVED"})
    return fee


# --- List/get parcels -------------------------------------------------------


def list_parcels(args):
    out = list(DB.parcels.values())
    st = args.get("status")
    cid = args.get("courier_id")
    mid = args.get("locker_machine_id")
    if st:
        out = [p for p in out if p.get("status") == st]
    if cid:
        out = [p for p in out if p.get("courier_id") == cid]
    if mid:
        out = [p for p in out if p.get("locker_machine_id") == mid]
    out.sort(key=lambda r: (r.get("created_at") or "", r["id"]))
    return out
