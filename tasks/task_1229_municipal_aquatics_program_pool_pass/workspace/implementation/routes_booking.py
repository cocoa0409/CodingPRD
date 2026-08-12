"""Routes: lane allocations and facility rentals."""
import domain
import store
from auth import authenticate
from envelope import get_body, list_response, serialize, sort_created, success
from errors import (err_already_checked_in, err_facility_at_capacity,
                    err_facility_closed, err_forbidden, err_holder_banned,
                    err_invalid_request, err_invalid_state, err_lane_capacity,
                    err_not_found, err_rental_capacity, err_rental_overlap,
                    err_stale_version)
from util import is_int, req_int

AM = ["AquaticsManager"]


def register(app):
    # --------------------------------------------------------- lane allocations
    @app.route("/lane-allocations", methods=["POST"])
    def create_lane_allocation():
        authenticate(AM)
        body = get_body()
        fid = body.get("facility_id")
        # priority 5: FKs
        if isinstance(fid, str) and fid not in store.facilities:
            raise err_not_found("facility_id does not resolve")
        owning = body.get("owning_lesson_session_id")
        if owning is not None and isinstance(owning, str) and owning not in store.lesson_sessions:
            raise err_not_found("owning_lesson_session_id does not resolve")
        purpose = body.get("purpose")
        start = store.parse_datetime(body.get("start_datetime"))
        end = store.parse_datetime(body.get("end_datetime"))
        # priority 12: lane capacity (evaluable only when fields parse)
        if isinstance(fid, str) and fid in store.facilities and start is not None and end is not None:
            lanes = body.get("lane_count")
            if is_int(lanes) and end > start:
                fac = store.facilities[fid]
                worst = domain.max_reserved_lanes(fid, start, end)
                if worst + lanes > fac["lap_lane_count"]:
                    raise err_lane_capacity()
        # priority 22: shape
        if not isinstance(fid, str) or not fid:
            raise err_invalid_request("Field 'facility_id' is required")
        if purpose not in ("LAP_SWIM", "SWIM_TEAM", "LESSON"):
            raise err_invalid_request("Field 'purpose' must be one of LAP_SWIM, SWIM_TEAM, LESSON")
        if purpose == "LESSON":
            raise err_invalid_request(
                "LESSON lane allocations are auto-created by lesson session scheduling")
        if owning is not None:
            raise err_invalid_request(
                "owning_lesson_session_id applies only to purpose=LESSON allocations")
        if start is None:
            raise err_invalid_request("Field 'start_datetime' must be an ISO 8601 timestamp")
        if end is None:
            raise err_invalid_request("Field 'end_datetime' must be an ISO 8601 timestamp")
        if end <= start:
            raise err_invalid_request("end_datetime must be after start_datetime")
        lane_count = req_int(body, "lane_count", minimum=1)

        alloc = store.base_fields()
        alloc.update({
            "facility_id": fid,
            "purpose": purpose,
            "start_datetime": store.iso(start),
            "end_datetime": store.iso(end),
            "lane_count": lane_count,
            "owning_lesson_session_id": None,
            "status": "RESERVED",
            "_start": start,
            "_end": end,
            "_seq": store.next_seq(),
        })
        store.lane_allocations[alloc["id"]] = alloc
        return success(serialize(alloc), 201)

    @app.route("/lane-allocations/<aid>", methods=["GET"])
    def get_lane_allocation(aid):
        authenticate(["AquaticsManager", "Lifeguard", "GateAttendant"])
        a = store.lane_allocations.get(aid)
        if not a:
            raise err_not_found("LaneAllocation not found")
        return success(serialize(a), 200)

    @app.route("/lane-allocations", methods=["GET"])
    def list_lane_allocations():
        authenticate(["AquaticsManager", "Lifeguard", "GateAttendant"])
        from flask import request
        items = list(store.lane_allocations.values())
        for param, field in (("facility_id", "facility_id"),
                             ("purpose", "purpose"), ("status", "status")):
            v = request.args.get(param)
            if v is not None:
                items = [a for a in items if a[field] == v]
        return list_response([serialize(a) for a in sort_created(items)])

    @app.route("/lane-allocations/<aid>/release", methods=["POST"])
    def release_lane_allocation(aid):
        authenticate(AM)
        a = store.lane_allocations.get(aid)
        if not a:
            raise err_not_found("LaneAllocation not found")
        if a["status"] != "RESERVED":
            raise err_invalid_state("Only a RESERVED allocation can be released")
        a["status"] = "RELEASED"
        store.touch(a)
        return success(serialize(a), 200)

    # ------------------------------------------------------------------ rentals
    @app.route("/rentals", methods=["POST"])
    def create_rental():
        authenticate(["PassHolder", "GateAttendant", "AquaticsManager"])
        body = get_body()
        fid = body.get("facility_id")
        hid = body.get("pass_holder_id")
        # priority 5: FKs
        if isinstance(fid, str) and fid not in store.facilities:
            raise err_not_found("facility_id does not resolve")
        if isinstance(hid, str) and hid not in store.pass_holders:
            raise err_not_found("pass_holder_id does not resolve")
        # priority 9: banned patron
        now = store.now()
        holder = store.pass_holders.get(hid) if isinstance(hid, str) else None
        if holder and domain.is_banned(holder, now):
            raise err_holder_banned()
        # priority 22: shape
        if not isinstance(fid, str) or not fid:
            raise err_invalid_request("Field 'facility_id' is required")
        if not isinstance(hid, str) or not hid:
            raise err_invalid_request("Field 'pass_holder_id' is required")
        party_size = req_int(body, "party_size", minimum=1)
        start = store.parse_datetime(body.get("start_datetime"))
        end = store.parse_datetime(body.get("end_datetime"))
        if start is None:
            raise err_invalid_request("Field 'start_datetime' must be an ISO 8601 timestamp")
        if end is None:
            raise err_invalid_request("Field 'end_datetime' must be an ISO 8601 timestamp")
        if end <= start:
            raise err_invalid_request("end_datetime must be after start_datetime")

        quote = domain.rental_quote(holder, party_size, start, end)
        r = store.base_fields()
        r.update({
            "facility_id": fid,
            "pass_holder_id": hid,
            "party_size": party_size,
            "start_datetime": store.iso(start),
            "end_datetime": store.iso(end),
            "quoted_price_cents": quote,
            "final_price_cents": None,
            "status": "REQUESTED",
            "_start": start,
            "_end": end,
            "_seq": store.next_seq(),
        })
        store.rentals[r["id"]] = r
        return success(serialize(r), 201)

    @app.route("/rentals/<rid>", methods=["GET"])
    def get_rental(rid):
        role, uid = authenticate(["PassHolder", "GateAttendant", "AquaticsManager"])
        r = store.rentals.get(rid)
        if not r:
            raise err_not_found("FacilityRental not found")
        if role == "PassHolder" and r["pass_holder_id"] != uid:
            raise err_forbidden("PassHolder may only access their own rentals")
        return success(serialize(r), 200)

    @app.route("/rentals", methods=["GET"])
    def list_rentals():
        authenticate(["GateAttendant", "AquaticsManager"])
        from flask import request
        items = list(store.rentals.values())
        for param, field in (("facility_id", "facility_id"),
                             ("pass_holder_id", "pass_holder_id"), ("status", "status")):
            v = request.args.get(param)
            if v is not None:
                items = [r for r in items if r[field] == v]
        return list_response([serialize(r) for r in sort_created(items)])

    @app.route("/rentals/<rid>/approve", methods=["POST"])
    def approve_rental(rid):
        authenticate(AM)
        r = store.rentals.get(rid)
        if not r:
            raise err_not_found("FacilityRental not found")
        # priority 6: state
        if r["status"] != "REQUESTED":
            raise err_invalid_state("Only a REQUESTED rental can be approved")
        body = get_body()
        fac = store.facilities[r["facility_id"]]
        # priority 7: OCC on the parent facility
        expected = body.get("expected_facility_version")
        if is_int(expected) and expected != fac["version"]:
            raise err_stale_version()
        # priority 8: facility must be OPEN or RESTRICTED
        if fac["operational_status"] in domain.CLOSED_STATUSES:
            raise err_facility_closed()
        # priority 9: patron must not be banned (PRD §2.10 example)
        holder = store.pass_holders.get(r["pass_holder_id"])
        if holder and domain.is_banned(holder, store.now()):
            raise err_holder_banned()
        # priority 11: whole-facility exclusivity vs other rentals (half-open)
        for other in store.rentals.values():
            if other["id"] == rid or other["facility_id"] != fac["id"]:
                continue
            if other["status"] in ("APPROVED", "CHECKED_IN"):
                if other["_start"] < r["_end"] and other["_end"] > r["_start"]:
                    raise err_rental_overlap()
        # priority 19: party size within capacity and exclusive lane use
        if r["party_size"] > fac["max_bather_capacity"]:
            raise err_rental_capacity("party_size exceeds facility max_bather_capacity")
        if domain.any_reserved_overlap(fac["id"], r["_start"], r["_end"]):
            raise err_rental_capacity("RESERVED lane allocations overlap the rental window")
        # priority 22: OCC field required by PRD §2.7
        if not is_int(expected):
            raise err_invalid_request("Field 'expected_facility_version' is required and must be an integer")

        r["status"] = "APPROVED"  # quoted_price_cents locked
        store.touch(r)
        store.touch(fac)  # approval increments Facility.version
        return success(serialize(r), 200)

    @app.route("/rentals/<rid>/reject", methods=["POST"])
    def reject_rental(rid):
        authenticate(AM)
        r = store.rentals.get(rid)
        if not r:
            raise err_not_found("FacilityRental not found")
        if r["status"] != "REQUESTED":
            raise err_invalid_state("Only a REQUESTED rental can be rejected")
        r["status"] = "REJECTED"
        store.touch(r)
        return success(serialize(r), 200)

    @app.route("/rentals/<rid>/check-in", methods=["POST"])
    def check_in_rental(rid):
        authenticate(["GateAttendant"])
        r = store.rentals.get(rid)
        if not r:
            raise err_not_found("FacilityRental not found")
        # priority 6: state
        if r["status"] == "CHECKED_IN":
            raise err_already_checked_in("Rental is already checked in")
        if r["status"] != "APPROVED":
            raise err_invalid_state("Only an APPROVED rental can be checked in")
        fac = store.facilities[r["facility_id"]]
        # priority 8: facility posture
        if fac["operational_status"] not in ("OPEN", "RESTRICTED"):
            raise err_facility_closed()
        # clock must be within the rental window
        now = store.now()
        if not (r["_start"] <= now <= r["_end"]):
            raise err_invalid_state("Current clock is outside the rental window")
        # priority 21: capacity
        if fac["current_bather_count"] + r["party_size"] > fac["max_bather_capacity"]:
            raise err_facility_at_capacity()
        r["status"] = "CHECKED_IN"
        store.touch(r)
        domain.change_bather_count(fac, r["party_size"])
        return success(serialize(r), 200)

    @app.route("/rentals/<rid>/check-out", methods=["POST"])
    def check_out_rental(rid):
        authenticate(["GateAttendant"])
        r = store.rentals.get(rid)
        if not r:
            raise err_not_found("FacilityRental not found")
        if r["status"] != "CHECKED_IN":
            raise err_invalid_state("Only a CHECKED_IN rental can be checked out")
        now = store.now()
        overtime = domain.rental_overtime_cents(r["_end"], now)
        r["status"] = "COMPLETED"
        r["final_price_cents"] = r["quoted_price_cents"] + overtime
        store.touch(r)
        fac = store.facilities[r["facility_id"]]
        domain.change_bather_count(fac, -r["party_size"])
        return success(serialize(r), 200)

    @app.route("/rentals/<rid>/cancel", methods=["POST"])
    def cancel_rental(rid):
        role, uid = authenticate(["PassHolder", "AquaticsManager"])
        r = store.rentals.get(rid)
        if not r:
            raise err_not_found("FacilityRental not found")
        if role == "PassHolder" and r["pass_holder_id"] != uid:
            raise err_forbidden("PassHolder may only cancel their own rentals")
        if r["status"] not in ("REQUESTED", "APPROVED"):
            raise err_invalid_state("Only a REQUESTED or APPROVED rental can be cancelled")
        if r["status"] == "APPROVED":
            # 25% fee when cancelled strictly inside 72h of start (fee not persisted)
            domain.rental_cancellation_fee(r, store.now())
        r["status"] = "CANCELLED"
        store.touch(r)
        return success(serialize(r), 200)
