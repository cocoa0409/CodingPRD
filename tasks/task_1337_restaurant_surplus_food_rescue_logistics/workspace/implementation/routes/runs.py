"""RescueRun endpoints: dispatch (selector assembly), driver lifecycle actions,
failure handling, agency countersignature, and sub-resource listings."""
from flask import Blueprint, request

from db import DB, new_id
from errors import ApiError
from middleware import auth
from response import ok
from services import (
    FAIL_REASONS,
    FAULT_PARTIES,
    agency_committed_lbs,
    book_window,
    capacity_field,
    clock_dt,
    clock_iso,
    cooler_is_candidate,
    create_reservation,
    create_temp_log,
    danger_zone_verdict,
    file_strike,
    get_offer,
    get_run,
    kill_screen_tripped,
    latest_arrival_log,
    pickup_log,
    quarantine_equipment,
    required_cooler_liters,
    reservation_blocked_interval,
    return_equipment_cleaning,
    checkout_equipment,
    select_agency,
    select_coolers,
    select_driver,
    select_window,
    ser_reservation,
    ser_run,
    ser_temp_log,
    stamp,
    touch,
    _decline_run,
    _release_reserved_equipment,
    _release_window,
)
from util import (
    as_bool,
    as_enum,
    as_int,
    as_iso_dt,
    as_list,
    as_num,
    body,
    paginate,
    parse_dt,
    reject_unknown,
    required,
)

bp = Blueprint("runs", __name__)


def _opt_str(data, field):
    v = data.get(field)
    if v is not None and (not isinstance(v, str) or not v):
        raise ApiError("ERR_INVALID_REQUEST", 400, f"Field {field} must be a string")
    return v


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

@bp.post("/api/rescue-runs")
def create_run():
    auth(["DispatchAdmin"])
    data = body()
    reject_unknown(
        data, {"offer_id", "expected_offer_version", "driver_id", "agency_id", "cooler_ids"}
    )
    offer_id = required(data, "offer_id")
    if not isinstance(offer_id, str) or not offer_id:
        raise ApiError("ERR_INVALID_REQUEST", 400, "Field offer_id must be a string")
    expected_offer_version = as_int(
        required(data, "expected_offer_version"), "expected_offer_version"
    )
    driver_id = _opt_str(data, "driver_id")
    agency_id = _opt_str(data, "agency_id")
    cooler_ids = None
    if "cooler_ids" in data and data["cooler_ids"] is not None:
        cooler_ids = as_list(data["cooler_ids"], "cooler_ids")
        for cid in cooler_ids:
            if not isinstance(cid, str) or not cid:
                raise ApiError(
                    "ERR_INVALID_REQUEST", 400, "cooler_ids entries must be strings"
                )

    # --- existence (tier 4): offer, then body FKs left to right ---
    offer = get_offer(offer_id)
    driver = None
    if driver_id is not None:
        driver = DB["drivers"].get(driver_id)
        if driver is None:
            raise ApiError("ERR_DRIVER_NOT_FOUND", 404, "Volunteer driver not found")
    agency = None
    if agency_id is not None:
        agency = DB["agencies"].get(agency_id)
        if agency is None:
            raise ApiError("ERR_AGENCY_NOT_FOUND", 404, "Recipient agency not found")
    pinned_coolers = []
    seen_coolers = set()
    for cid in cooler_ids or []:
        c = DB["coolers"].get(cid)
        if c is None:
            raise ApiError("ERR_COOLER_NOT_FOUND", 404, "Cooler not found")
        if cid not in seen_coolers:
            seen_coolers.add(cid)
            pinned_coolers.append(c)

    # cooler_ids on non-cold-chain work is malformed (tier-3 rule; needs offer)
    if not offer["requires_cold_chain"] and pinned_coolers:
        raise ApiError(
            "ERR_INVALID_REQUEST", 400,
            "cooler_ids must be omitted or empty for non-cold-chain offers",
        )

    # --- state (tier 6); lazy offer expiry already ran in before_request ---
    if offer["status"] != "OPEN":
        raise ApiError(
            "ERR_OFFER_NOT_OPEN", 409, "Dispatch requires an OPEN donation offer"
        )
    if driver is not None and driver["status"] != "ACTIVE":
        raise ApiError(
            "ERR_DRIVER_NOT_ACTIVE", 409, "Pinned driver must be ACTIVE"
        )

    # --- optimistic concurrency (tier 7) ---
    if expected_offer_version != offer["version"]:
        raise ApiError(
            "ERR_STALE_OFFER_VERSION", 412, "DonationOffer version has advanced"
        )

    # --- cold-chain safety (tier 8): pinned driver certification ---
    if (
        driver is not None
        and offer["requires_cold_chain"]
        and not driver["cold_chain_certified"]
    ):
        raise ApiError(
            "ERR_DRIVER_NOT_COLD_CHAIN_CERTIFIED", 409,
            "Pinned driver lacks cold-chain certification",
        )

    # --- temporal interval rules (tier 9) ---
    window = None
    if driver is not None:
        window = select_window(driver["id"], offer)
        if window is None:
            raise ApiError(
                "ERR_DRIVER_WINDOW_MISSING", 409,
                "Pinned driver has no OPEN window covering the pickup window",
            )
    blocked_start, blocked_end = reservation_blocked_interval(offer)
    for c in pinned_coolers:
        if not cooler_is_candidate(c, blocked_start, blocked_end):
            raise ApiError(
                "ERR_COOLER_UNAVAILABLE", 409,
                "Pinned cooler is not available for the blocked interval",
            )

    # --- category acceptability (tier 10): pinned agency ---
    if agency is not None and offer["food_category"] not in agency["accepts_categories"]:
        raise ApiError(
            "ERR_AGENCY_CATEGORY_NOT_ACCEPTED", 409,
            "Pinned agency does not accept this food category",
        )

    # --- capacity quotas (tier 11): pinned driver / pinned agency ---
    if driver is not None and driver["vehicle_capacity_lbs"] < offer["estimated_weight_lbs"]:
        raise ApiError(
            "ERR_DRIVER_CAPACITY_EXCEEDED", 409,
            "Pinned driver's vehicle capacity is below the estimated weight",
        )
    cat = offer["food_category"]
    if agency is not None:
        committed = agency_committed_lbs(agency["id"], cat)
        if committed + offer["estimated_weight_lbs"] > agency[capacity_field(cat)]:
            raise ApiError(
                "ERR_AGENCY_CAPACITY_EXCEEDED", 409,
                "Agency capacity would be exceeded",
            )

    # --- selector fallback (tier 12), resolution order: driver, agency, coolers ---
    if driver is None:
        picked = select_driver(offer)
        if picked is None:
            raise ApiError(
                "ERR_NO_ELIGIBLE_DRIVER", 409, "No eligible driver for this offer"
            )
        driver, window = picked
    if agency is None:
        agency = select_agency(offer)
        if agency is None:
            raise ApiError(
                "ERR_NO_ELIGIBLE_AGENCY", 409, "No eligible agency for this offer"
            )
    selected_coolers = []
    if offer["requires_cold_chain"]:
        required_liters = required_cooler_liters(offer)
        if pinned_coolers:
            if len(pinned_coolers) > driver["cooler_slot_count"] or sum(
                c["capacity_liters"] for c in pinned_coolers
            ) < required_liters:
                raise ApiError(
                    "ERR_INSUFFICIENT_COOLER_CAPACITY", 409,
                    "Pinned coolers do not meet the capacity requirement",
                )
            selected_coolers = pinned_coolers
        else:
            chosen = select_coolers(
                offer, driver["cooler_slot_count"], blocked_start, blocked_end
            )
            if chosen is None:
                raise ApiError(
                    "ERR_INSUFFICIENT_COOLER_CAPACITY", 409,
                    "Insufficient cooler capacity",
                )
            selected_coolers = chosen

    # --- atomic commit ---
    run = {
        "id": new_id(),
        "offer_id": offer["id"],
        "agency_id": agency["id"],
        "driver_id": driver["id"],
        "run_status": "PROPOSED",
        "safety_status": "UNVERIFIED",
        "estimated_weight_snapshot": offer["estimated_weight_lbs"],
        "actual_weight_lbs": None,
        "pickup_time": None,
        "arrival_time": None,
        "verified_at": None,
        "driver_attestation_signed_at": None,
        "agency_countersigned_by_user_id": None,
        "agency_countersigned_at": None,
        "fault_party": None,
        "failure_reason": None,
        "disposal_method": None,
        "disposal_notes": None,
    }
    stamp(run)
    DB["runs"][run["id"]] = run
    offer["status"] = "MATCHED"
    offer["current_run_id"] = run["id"]
    touch(offer)
    book_window(window, run["id"])
    for c in selected_coolers:
        create_reservation(c, run, offer)
    return ok(ser_run(run), status=201)


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------

@bp.get("/api/rescue-runs")
def list_runs():
    auth(["DispatchAdmin"])
    items = list(DB["runs"].values())
    for param, key in (
        ("offer_id", "offer_id"),
        ("agency_id", "agency_id"),
        ("driver_id", "driver_id"),
        ("status", "run_status"),
    ):
        v = request.args.get(param)
        if v is not None:
            items = [r for r in items if r.get(key) == v]
    return paginate(items, ser_run)


@bp.get("/api/rescue-runs/<rid>")
def get_one_run(rid):
    user_id, role = auth(["DispatchAdmin", "VolunteerDriver", "AgencyCoordinator"])
    return ok(ser_run(get_run(rid, user_id, role)))


# ---------------------------------------------------------------------------
# Driver respond
# ---------------------------------------------------------------------------

@bp.post("/api/rescue-runs/<rid>/respond")
def respond(rid):
    user_id, role = auth(["VolunteerDriver"])
    data = body()
    reject_unknown(data, {"decision"})
    decision = as_enum(required(data, "decision"), "decision", ("ACCEPT", "DECLINE"))
    run = get_run(rid, user_id, role)
    # No fresh driver-status check here by design: a suspension between
    # dispatch and respond already tore this PROPOSED run down.
    if run["run_status"] != "PROPOSED":
        raise ApiError(
            "ERR_RUN_NOT_IN_EXPECTED_STATE", 409,
            "Respond requires a PROPOSED run",
        )
    if decision == "ACCEPT":
        offer = DB["offers"][run["offer_id"]]
        agency = DB["agencies"][run["agency_id"]]
        cat = offer["food_category"]
        # The run itself is already inside the committed set; equality allowed.
        if agency_committed_lbs(agency["id"], cat) > agency[capacity_field(cat)]:
            raise ApiError(
                "ERR_AGENCY_CAPACITY_EXCEEDED", 409,
                "Agency capacity would be exceeded",
            )
        run["run_status"] = "CONFIRMED"
        touch(run)
        offer["status"] = "SCHEDULED"
        touch(offer)
    else:
        _decline_run(run)
    return ok(ser_run(run))


# ---------------------------------------------------------------------------
# Record pickup
# ---------------------------------------------------------------------------

@bp.post("/api/rescue-runs/<rid>/record-pickup")
def record_pickup(rid):
    user_id, role = auth(["VolunteerDriver"])
    data = body()
    reject_unknown(data, {"pickup_time", "pickup_temp_f", "attestation_confirmed"})
    pickup_time = as_iso_dt(required(data, "pickup_time"), "pickup_time")
    attestation = as_bool(
        required(data, "attestation_confirmed"), "attestation_confirmed"
    )
    if attestation is not True:
        raise ApiError(
            "ERR_INVALID_REQUEST", 400, "attestation_confirmed must be true"
        )
    if parse_dt(pickup_time) > clock_dt():
        raise ApiError(
            "ERR_INVALID_REQUEST", 400,
            "pickup_time must not be after the current time",
        )
    temp = None
    if "pickup_temp_f" in data and data["pickup_temp_f"] is not None:
        temp = as_num(data["pickup_temp_f"], "pickup_temp_f")
    run = get_run(rid, user_id, role)
    if run["run_status"] != "CONFIRMED":
        raise ApiError(
            "ERR_RUN_NOT_IN_EXPECTED_STATE", 409,
            "Record-pickup requires a CONFIRMED run",
        )
    offer = DB["offers"][run["offer_id"]]
    # Cold-chain kill screen (tier 8): missing or at/beyond kill temperature.
    if offer["requires_cold_chain"]:
        if temp is None or kill_screen_tripped(offer["food_category"], temp):
            raise ApiError(
                "ERR_SAFETY_VIOLATION_AT_PICKUP", 409,
                "Pickup temperature trips the kill screen",
            )
    run["pickup_time"] = pickup_time
    run["driver_attestation_signed_at"] = clock_iso()
    run["safety_status"] = "PROVISIONAL_COMPLIANT"
    run["run_status"] = "PICKED_UP"
    touch(run)
    if temp is not None:
        create_temp_log(run, "PICKUP", temp, pickup_time, user_id)
    checkout_equipment(run)
    offer["status"] = "PICKED_UP"
    touch(offer)
    return ok(ser_run(run))


# ---------------------------------------------------------------------------
# Fail (pickup stage from CONFIRMED; delivery stage from PICKED_UP)
# ---------------------------------------------------------------------------

_PICKUP_STAGE_PAIRS = {
    "SAFETY_REJECTED": "NONE",
    "DONOR_NO_SHOW": "DONOR",
    "DRIVER_NO_SHOW": "DRIVER",
}


@bp.post("/api/rescue-runs/<rid>/fail")
def fail_run(rid):
    user_id, role = auth(["VolunteerDriver", "DispatchAdmin"])
    data = body()
    reject_unknown(data, {"fault_party", "reason", "disposal_method", "disposal_notes"})
    fault_party = as_enum(required(data, "fault_party"), "fault_party", FAULT_PARTIES)
    reason = as_enum(required(data, "reason"), "reason", FAIL_REASONS)
    # Stage-independent well-formedness for SAFETY_DISPOSAL (tier 3).
    if reason == "SAFETY_DISPOSAL":
        if fault_party != "NONE":
            raise ApiError(
                "ERR_INVALID_REQUEST", 400,
                "SAFETY_DISPOSAL requires fault_party NONE",
            )
        for f in ("disposal_method", "disposal_notes"):
            v = data.get(f)
            if not isinstance(v, str) or not v.strip():
                raise ApiError(
                    "ERR_INVALID_REQUEST", 400,
                    f"{f} is required for SAFETY_DISPOSAL",
                )
    run = get_run(rid, user_id, role)
    if run["run_status"] not in ("CONFIRMED", "PICKED_UP"):
        raise ApiError(
            "ERR_RUN_NOT_IN_EXPECTED_STATE", 409,
            "Fail requires a CONFIRMED or PICKED_UP run",
        )
    offer = DB["offers"][run["offer_id"]]
    reporter_role = "DRIVER" if role == "VolunteerDriver" else "ADMIN"

    if run["run_status"] == "CONFIRMED":
        # Pickup-stage rulebook.
        required_fault = _PICKUP_STAGE_PAIRS.get(reason)
        if required_fault is not None and fault_party != required_fault:
            raise ApiError(
                "ERR_INVALID_REQUEST", 400,
                f"{reason} requires fault_party {required_fault}",
            )
        if reason == "SAFETY_DISPOSAL":
            # Requires safety_status VERIFIED_VIOLATION, impossible here.
            raise ApiError(
                "ERR_RUN_NOT_IN_EXPECTED_STATE", 409,
                "SAFETY_DISPOSAL requires a VERIFIED_VIOLATION safety status",
            )
        run["run_status"] = "FAILED_PICKUP"
        run["fault_party"] = fault_party
        run["failure_reason"] = reason
        touch(run)
        _release_window(run)
        _release_reserved_equipment(run)
        if reason == "SAFETY_REJECTED":
            # Discards the food, blames no one, files no strike.
            offer["status"] = "DISCARDED"
            touch(offer)
        else:
            offer["failed_attempts"] += 1
            offer["status"] = "OPEN" if offer["failed_attempts"] < 3 else "EXPIRED"
            touch(offer)
            if fault_party in ("DONOR", "DRIVER"):
                _file_fault_strike(run, offer, fault_party, reason, reporter_role, user_id)
    else:
        # Delivery-stage rulebook.
        if reason in ("AGENCY_CLOSED", "OVER_CAPACITY") and fault_party != "AGENCY":
            raise ApiError(
                "ERR_INVALID_REQUEST", 400,
                f"{reason} requires fault_party AGENCY",
            )
        if reason == "SAFETY_DISPOSAL" and run["safety_status"] != "VERIFIED_VIOLATION":
            raise ApiError(
                "ERR_RUN_NOT_IN_EXPECTED_STATE", 409,
                "SAFETY_DISPOSAL requires a VERIFIED_VIOLATION safety status",
            )
        run["run_status"] = "FAILED_DELIVERY"
        run["fault_party"] = fault_party
        run["failure_reason"] = reason
        if reason == "SAFETY_DISPOSAL":
            run["disposal_method"] = data["disposal_method"]
            run["disposal_notes"] = data["disposal_notes"]
            quarantine_equipment(run)
        else:
            return_equipment_cleaning(run)
        touch(run)
        _release_window(run)
        offer["status"] = "DISCARDED"
        touch(offer)
        # Strikes discipline donors and drivers only; AGENCY fault files none.
        if fault_party in ("DONOR", "DRIVER"):
            _file_fault_strike(run, offer, fault_party, reason, reporter_role, user_id)
    return ok(ser_run(run))


def _file_fault_strike(run, offer, fault_party, reason, reporter_role, user_id):
    if fault_party == "DONOR":
        subject_type, subject_id = "DONOR_SITE", offer["donor_site_id"]
    else:
        subject_type, subject_id = "DRIVER", run["driver_id"]
    file_strike(run["id"], reporter_role, user_id, subject_type, subject_id, reason)


# ---------------------------------------------------------------------------
# Record delivery
# ---------------------------------------------------------------------------

@bp.post("/api/rescue-runs/<rid>/record-delivery")
def record_delivery(rid):
    user_id, role = auth(["VolunteerDriver"])
    data = body()
    reject_unknown(data, {"arrival_time", "arrival_temp_f", "actual_weight_lbs"})
    arrival_time = as_iso_dt(required(data, "arrival_time"), "arrival_time")
    actual_weight_lbs = as_int(
        required(data, "actual_weight_lbs"), "actual_weight_lbs"
    )
    if parse_dt(arrival_time) > clock_dt():
        raise ApiError(
            "ERR_INVALID_REQUEST", 400,
            "arrival_time must not be after the current time",
        )
    temp = None
    if "arrival_temp_f" in data and data["arrival_temp_f"] is not None:
        temp = as_num(data["arrival_temp_f"], "arrival_temp_f")
    run = get_run(rid, user_id, role)
    if run["run_status"] != "PICKED_UP":
        raise ApiError(
            "ERR_RUN_NOT_IN_EXPECTED_STATE", 409,
            "Record-delivery requires a PICKED_UP run",
        )
    if parse_dt(arrival_time) < parse_dt(run["pickup_time"]):
        raise ApiError(
            "ERR_INVALID_REQUEST", 400,
            "arrival_time must not be before pickup_time",
        )
    offer = DB["offers"][run["offer_id"]]
    # An ARRIVAL log documents every delivery attempt that carries a reading.
    if temp is not None:
        create_temp_log(run, "ARRIVAL", temp, arrival_time, user_id)
    # Cold-chain final verdict (tier 8, ahead of the overage gate at tier 11).
    if offer["requires_cold_chain"]:
        plog = pickup_log(run)
        alog = latest_arrival_log(run)
        compliant = False
        if temp is not None and plog is not None and alog is not None:
            compliant = danger_zone_verdict(
                offer["food_category"],
                parse_dt(plog["recorded_at"]),
                plog["temp_f"],
                parse_dt(alog["recorded_at"]),
                alog["temp_f"],
            )
        if not compliant:
            run["safety_status"] = "VERIFIED_VIOLATION"
            touch(run)
            raise ApiError(
                "ERR_SAFETY_VERDICT_VIOLATION", 409,
                "Danger-zone verdict is VIOLATION",
            )
    # Delivery overage gate (tier 11): 1 <= actual <= ceil(snapshot * 1.25).
    snapshot = run["estimated_weight_snapshot"]
    ceiling = (snapshot * 5 + 3) // 4
    if actual_weight_lbs < 1 or actual_weight_lbs > ceiling:
        raise ApiError(
            "ERR_DELIVERY_OVERAGE_EXCEEDED", 409,
            "actual_weight_lbs outside the permitted range",
        )
    run["arrival_time"] = arrival_time
    run["actual_weight_lbs"] = actual_weight_lbs
    run["safety_status"] = "VERIFIED_COMPLIANT"
    run["run_status"] = "DELIVERED"
    touch(run)
    # Agency commitment release and received-total conversion are computed
    # dynamically from run_status/actual_weight_lbs.
    return_equipment_cleaning(run)
    offer["status"] = "DELIVERED"
    touch(offer)
    return ok(ser_run(run))


# ---------------------------------------------------------------------------
# Verify delivery (agency countersignature)
# ---------------------------------------------------------------------------

@bp.post("/api/rescue-runs/<rid>/verify-delivery")
def verify_delivery(rid):
    user_id, role = auth(["AgencyCoordinator"])
    data = body()
    reject_unknown(data, set())
    run = get_run(rid, user_id, role)
    if run["run_status"] != "DELIVERED":
        raise ApiError(
            "ERR_RUN_NOT_IN_EXPECTED_STATE", 409,
            "Verify-delivery requires a DELIVERED run",
        )
    now = clock_iso()
    run["verified_at"] = now
    run["agency_countersigned_by_user_id"] = user_id
    run["agency_countersigned_at"] = now
    run["run_status"] = "VERIFIED"
    touch(run)
    offer = DB["offers"][run["offer_id"]]
    offer["status"] = "CLOSED"
    touch(offer)
    driver = DB["drivers"].get(run["driver_id"])
    if driver is not None:
        driver["reliability_score"] = min(100, driver["reliability_score"] + 5)
        touch(driver)
    _release_window(run)
    return ok(ser_run(run))


# ---------------------------------------------------------------------------
# Sub-resource listings
# ---------------------------------------------------------------------------

@bp.get("/api/rescue-runs/<rid>/temperature-logs")
def list_temp_logs(rid):
    user_id, role = auth(["DispatchAdmin", "VolunteerDriver", "AgencyCoordinator"])
    run = get_run(rid, user_id, role)
    items = [t for t in DB["temp_logs"].values() if t["rescue_run_id"] == run["id"]]
    return paginate(items, ser_temp_log)


@bp.get("/api/rescue-runs/<rid>/cooler-reservations")
def list_run_reservations(rid):
    auth(["DispatchAdmin"])
    run = get_run(rid)
    items = [r for r in DB["reservations"].values() if r["rescue_run_id"] == run["id"]]
    status = request.args.get("status")
    if status is not None:
        items = [r for r in items if r["status"] == status]
    return paginate(items, ser_reservation)
