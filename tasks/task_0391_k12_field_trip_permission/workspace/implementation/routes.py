"""All API routes (PRD §4 endpoint table).

Validation ordering per request follows PRD §2.11:
  401 header -> 403 role (via @require_roles) -> 404 existence
  -> 403 ownership -> 422 approval-step -> 409 state -> cross-state
  -> temporal -> safety/capacity/fiscal -> 412 OCC.
"""
from flask import request

from db import db, stamp_create, touch
from errors import err
from middleware import require_roles
from response import success, list_response
from validation import (
    get_body, require_string, require_int, optional_int, require_bool,
    optional_bool, optional_string, require_enum, require_datetime,
    optional_array, paginate,
)
import calc
import serialize as S
import lookups as L


def register_routes(app):
    # =====================================================================
    # Students (PRD §3.1)
    # =====================================================================
    @app.route("/students", methods=["POST"])
    @require_roles("Teacher", "Principal", "DistrictAdmin")
    def create_student(user_id, user_role):
        body = get_body()
        full_name = require_string(body, "full_name")
        grade_level = require_int(body, "grade_level")
        if grade_level < 0 or grade_level > 12:
            raise err("ERR_VALIDATION", "grade_level must be between 0 and 12.")
        home_school_code = require_string(body, "home_school_code")
        special_needs = optional_bool(body, "special_needs", False)
        rec = stamp_create(versioned=True)
        rec.update({
            "full_name": full_name,
            "grade_level": grade_level,
            "special_needs": special_needs,
            "home_school_code": home_school_code,
        })
        db.students[rec["id"]] = rec
        return success(S.student_out(rec), 201)

    @app.route("/students", methods=["GET"])
    @require_roles("Teacher", "Principal", "DistrictAdmin")
    def list_students(user_id, user_role):
        items = list(db.students.values())
        if "home_school_code" in request.args:
            code = request.args.get("home_school_code")
            items = [s for s in items if s["home_school_code"] == code]
        window, limit, offset, total = paginate(items)
        return list_response([S.student_out(s) for s in window], limit, offset, total)

    @app.route("/students/<sid>", methods=["GET"])
    @require_roles("Teacher", "Principal", "DistrictAdmin", "Guardian")
    def get_student_ep(sid, user_id, user_role):
        s = L.get_student(sid)
        return success(S.student_out(s), 200)

    # =====================================================================
    # Guardians (PRD §3.1)
    # =====================================================================
    @app.route("/guardians", methods=["POST"])
    @require_roles("Teacher", "Principal", "DistrictAdmin")
    def create_guardian(user_id, user_role):
        body = get_body()
        full_name = require_string(body, "full_name")
        email = require_string(body, "email")
        phone = require_string(body, "phone")
        for g in db.guardians.values():
            if g["email"] == email:
                raise err("ERR_GUARDIAN_EMAIL_TAKEN", "Email already registered.")
        rec = stamp_create(versioned=True)
        rec.update({"full_name": full_name, "email": email, "phone": phone})
        db.guardians[rec["id"]] = rec
        return success(S.guardian_out(rec), 201)

    @app.route("/guardians", methods=["GET"])
    @require_roles("Teacher", "Principal", "DistrictAdmin")
    def list_guardians(user_id, user_role):
        items = list(db.guardians.values())
        if "email" in request.args:
            email = request.args.get("email")
            items = [g for g in items if g["email"] == email]
        window, limit, offset, total = paginate(items)
        return list_response([S.guardian_out(g) for g in window], limit, offset, total)

    @app.route("/guardians/<gid>", methods=["GET"])
    @require_roles("Teacher", "Principal", "DistrictAdmin", "Guardian")
    def get_guardian_ep(gid, user_id, user_role):
        g = L.get_guardian(gid)
        return success(S.guardian_out(g), 200)

    # =====================================================================
    # Vehicles (PRD §3.1, §3.6)
    # =====================================================================
    @app.route("/vehicles", methods=["POST"])
    @require_roles("DistrictAdmin")
    def create_vehicle(user_id, user_role):
        body = get_body()
        label = require_string(body, "label")
        seat_capacity = require_int(body, "seat_capacity", minimum=1)
        rec = stamp_create(versioned=True)
        rec.update({"label": label, "seat_capacity": seat_capacity, "status": "ACTIVE"})
        db.vehicles[rec["id"]] = rec
        return success(S.vehicle_out(rec), 201)

    @app.route("/vehicles", methods=["GET"])
    @require_roles("Teacher", "Principal", "DistrictAdmin")
    def list_vehicles(user_id, user_role):
        items = list(db.vehicles.values())
        if "status" in request.args:
            st = request.args.get("status")
            items = [v for v in items if v["status"] == st]
        window, limit, offset, total = paginate(items)
        return list_response([S.vehicle_out(v) for v in window], limit, offset, total)

    @app.route("/vehicles/<vid>", methods=["GET"])
    @require_roles("Teacher", "Principal", "DistrictAdmin")
    def get_vehicle_ep(vid, user_id, user_role):
        v = L.get_vehicle(vid)
        return success(S.vehicle_out(v), 200)

    @app.route("/vehicles/<vid>/retire", methods=["POST"])
    @require_roles("DistrictAdmin")
    def retire_vehicle(vid, user_id, user_role):
        v = L.get_vehicle(vid)
        v["status"] = "RETIRED"
        touch(v)
        return success(S.vehicle_out(v), 200)

    # =====================================================================
    # Scholarship pools (PRD §3.1)
    # =====================================================================
    @app.route("/scholarship-pools", methods=["POST"])
    @require_roles("DistrictAdmin")
    def create_pool(user_id, user_role):
        body = get_body()
        name = require_string(body, "name")
        total_cents = require_int(body, "total_cents", minimum=0)
        rec = stamp_create(versioned=True)
        rec.update({"name": name, "total_cents": total_cents})
        db.scholarship_pools[rec["id"]] = rec
        return success(S.pool_out(rec), 201)

    @app.route("/scholarship-pools", methods=["GET"])
    @require_roles("Teacher", "Principal", "DistrictAdmin")
    def list_pools(user_id, user_role):
        window, limit, offset, total = paginate(list(db.scholarship_pools.values()))
        return list_response([S.pool_out(p) for p in window], limit, offset, total)

    @app.route("/scholarship-pools/<pid>", methods=["GET"])
    @require_roles("Teacher", "Principal", "DistrictAdmin")
    def get_pool_ep(pid, user_id, user_role):
        p = L.get_pool(pid)
        return success(S.pool_out(p), 200)

    # =====================================================================
    # Scholarship grants (read surface; create/revoke under slip)
    # =====================================================================
    @app.route("/scholarship-grants", methods=["GET"])
    @require_roles("Teacher", "Principal", "DistrictAdmin")
    def list_grants(user_id, user_role):
        items = list(db.scholarship_grants.values())
        if "slip_id" in request.args:
            items = [g for g in items if g["slip_id"] == request.args.get("slip_id")]
        if "pool_id" in request.args:
            items = [g for g in items if g["pool_id"] == request.args.get("pool_id")]
        if "status" in request.args:
            items = [g for g in items if g["status"] == request.args.get("status")]
        window, limit, offset, total = paginate(items)
        return list_response([S.grant_out(g) for g in window], limit, offset, total)

    @app.route("/scholarship-grants/<gid>", methods=["GET"])
    @require_roles("Teacher", "Principal", "DistrictAdmin")
    def get_grant_ep(gid, user_id, user_role):
        g = db.scholarship_grants.get(gid)
        if g is None:
            raise err("ERR_GRANT_NOT_FOUND", "Scholarship grant not found.")
        return success(S.grant_out(g), 200)

    # =====================================================================
    # Field trips (PRD §3.2)
    # =====================================================================
    @app.route("/field-trips", methods=["POST"])
    @require_roles("Teacher")
    def create_trip(user_id, user_role):
        body = get_body()
        title = require_string(body, "title")
        organizer_teacher_id = require_string(body, "organizer_teacher_id")
        school_code = require_string(body, "school_code")
        grade_band = require_enum(body, "grade_band", {"ELEMENTARY", "MIDDLE", "HIGH"})
        depart_at = require_datetime(body, "depart_at")
        return_at = require_datetime(body, "return_at")
        capacity = require_int(body, "capacity", minimum=1)
        base_fee_cents = require_int(body, "base_fee_cents", minimum=0)
        transport_cost_cents = require_int(body, "transport_cost_cents", minimum=0)
        deposit_cents = optional_int(body, "deposit_cents", 0, minimum=0)
        has_water_activity = optional_bool(body, "has_water_activity", False)
        # FK existence: organizer_teacher_id -> Guardian (PRD §2.6)
        L.get_guardian(organizer_teacher_id)
        rec = stamp_create(versioned=True)
        rec.update({
            "title": title,
            "organizer_teacher_id": organizer_teacher_id,
            "school_code": school_code,
            "grade_band": grade_band,
            "depart_at": depart_at,
            "return_at": return_at,
            "has_water_activity": has_water_activity,
            "capacity": capacity,
            "base_fee_cents": base_fee_cents,
            "transport_cost_cents": transport_cost_cents,
            "deposit_cents": deposit_cents,
            "status": "DRAFT",
            "signed_count": 0,
            "confirmed_count": None,
            "per_student_final_fee_cents": None,
        })
        db.field_trips[rec["id"]] = rec
        return success(S.field_trip_out(rec), 201)

    @app.route("/field-trips", methods=["GET"])
    @require_roles("Teacher", "Principal", "DistrictAdmin")
    def list_trips(user_id, user_role):
        items = list(db.field_trips.values())
        if "organizer_teacher_id" in request.args:
            val = request.args.get("organizer_teacher_id")
            items = [t for t in items if t["organizer_teacher_id"] == val]
        if "school_code" in request.args:
            items = [t for t in items if t["school_code"] == request.args.get("school_code")]
        if "status" in request.args:
            items = [t for t in items if t["status"] == request.args.get("status")]
        window, limit, offset, total = paginate(items)
        return list_response([S.field_trip_out(t) for t in window], limit, offset, total)

    @app.route("/field-trips/<tid>", methods=["GET"])
    @require_roles("Teacher", "Principal", "DistrictAdmin", "Guardian")
    def get_trip_ep(tid, user_id, user_role):
        t = L.get_trip(tid)
        return success(S.field_trip_out(t), 200)

    @app.route("/field-trips/<tid>/submit", methods=["POST"])
    @require_roles("Teacher")
    def submit_trip(tid, user_id, user_role):
        t = L.get_trip(tid)
        if t["status"] != "DRAFT":
            raise err("ERR_TRIP_NOT_DRAFT", "Submit requires the trip in DRAFT.")
        if not (t["return_at"] > t["depart_at"]):
            raise err("ERR_INVALID_TIME_WINDOW", "return_at must be strictly after depart_at.")
        if t["capacity"] < 1:
            raise err("ERR_INVALID_CAPACITY", "capacity must be at least 1.")
        t["status"] = "PENDING_PRINCIPAL"
        touch(t)
        return success(S.field_trip_out(t), 200)

    @app.route("/field-trips/<tid>/approvals", methods=["POST"])
    @require_roles("Principal", "DistrictAdmin")
    def create_approval(tid, user_id, user_role):
        t = L.get_trip(tid)
        body = get_body()
        step = require_enum(body, "step", {"PRINCIPAL", "DISTRICT"})
        decision = require_enum(body, "decision", {"APPROVE", "REJECT"})
        comment = optional_string(body, "comment", None)
        # priority 4.5: step must match the current pending step (422) before state.
        current_step = None
        if t["status"] == "PENDING_PRINCIPAL":
            current_step = "PRINCIPAL"
        elif t["status"] == "PENDING_DISTRICT":
            current_step = "DISTRICT"
        if current_step is None or step != current_step:
            raise err("ERR_INVALID_APPROVAL_STEP", "Step does not match the trip's pending step.")
        # priority 5/6: state precondition for the named step.
        if step == "PRINCIPAL":
            if t["status"] != "PENDING_PRINCIPAL":
                raise err("ERR_TRIP_NOT_AWAITING_PRINCIPAL", "Trip not awaiting principal.")
            actor_role = "PRINCIPAL"
            t["status"] = "PENDING_DISTRICT" if decision == "APPROVE" else "DRAFT"
        else:
            if t["status"] != "PENDING_DISTRICT":
                raise err("ERR_TRIP_NOT_AWAITING_DISTRICT", "Trip not awaiting district.")
            actor_role = "DISTRICT_ADMIN"
            t["status"] = "APPROVED" if decision == "APPROVE" else "DRAFT"
        touch(t)
        rec = stamp_create(versioned=False)
        rec.update({
            "trip_id": tid,
            "step": step,
            "decision": decision,
            "actor_role": actor_role,
            "actor_user_id": user_id,
            "comment": comment,
        })
        db.trip_approvals[rec["id"]] = rec
        return success(S.approval_out(rec), 201)

    @app.route("/field-trips/<tid>/lock-roster", methods=["POST"])
    @require_roles("Teacher")
    def lock_roster(tid, user_id, user_role):
        t = L.get_trip(tid)
        body = get_body()
        expected_version = require_int(body, "expected_trip_version")
        # Preconditions in PRD §3.8 order.
        if t["status"] != "APPROVED":
            raise err("ERR_TRIP_NOT_APPROVED", "Lock requires the trip in APPROVED.")
        if expected_version != t["version"]:
            raise err("ERR_STALE_TRIP_VERSION", "expected_trip_version is stale.")
        if t["signed_count"] < 1:
            raise err("ERR_EMPTY_ROSTER", "Roster is empty.")
        required = calc.required_chaperones(t)
        cleared = sum(
            1 for c in db.chaperones.values()
            if c["trip_id"] == tid and c["status"] == "CLEARED"
        )
        if cleared < required:
            raise err("ERR_CHAPERONE_RATIO_UNMET", "Chaperone ratio unmet.")
        confirmed_seats = sum(
            b["seat_count"] for b in db.transport_bookings.values()
            if b["trip_id"] == tid and b["status"] == "CONFIRMED"
        )
        if confirmed_seats < t["signed_count"]:
            raise err("ERR_TRANSPORT_NOT_BOOKED", "Confirmed transport seats insufficient.")
        # Snapshot: SIGNED -> CONFIRMED; UNSIGNED/REVOKED -> WITHDRAWN.
        confirmed_slips = []
        for s in db.permission_slips.values():
            if s["trip_id"] != tid:
                continue
            if s["signature_status"] == "SIGNED":
                s["participation_status"] = "CONFIRMED"
                confirmed_slips.append(s)
                touch(s)
            elif s["signature_status"] in ("UNSIGNED", "REVOKED"):
                s["participation_status"] = "WITHDRAWN"
                touch(s)
        c = len(confirmed_slips)
        if c == 0:
            raise err("ERR_EMPTY_ROSTER", "Roster is empty.")
        t["confirmed_count"] = c
        shares, base_share = calc.allocate_final_transport(t, confirmed_slips)
        for s in confirmed_slips:
            s["fee_due_cents"] = calc.compute_fee_due(t, s, shares[s["id"]])
            s["_final_transport_share"] = shares[s["id"]]
            touch(s)
        t["per_student_final_fee_cents"] = t["base_fee_cents"] + base_share
        t["status"] = "ROSTER_LOCKED"
        touch(t)
        return success(S.field_trip_out(t), 200)

    @app.route("/field-trips/<tid>/start", methods=["POST"])
    @require_roles("Teacher")
    def start_trip(tid, user_id, user_role):
        t = L.get_trip(tid)
        if t["status"] != "ROSTER_LOCKED":
            raise err("ERR_TRIP_NOT_LOCKED", "Start requires the trip in ROSTER_LOCKED.")
        t["status"] = "IN_PROGRESS"
        touch(t)
        return success(S.field_trip_out(t), 200)

    @app.route("/field-trips/<tid>/complete", methods=["POST"])
    @require_roles("Teacher")
    def complete_trip(tid, user_id, user_role):
        t = L.get_trip(tid)
        if t["status"] != "IN_PROGRESS":
            raise err("ERR_TRIP_NOT_IN_PROGRESS", "Complete requires the trip in IN_PROGRESS.")
        # Every CONFIRMED slip needs at least one RETURN attendance record.
        confirmed = [
            s for s in db.permission_slips.values()
            if s["trip_id"] == tid and s["participation_status"] == "CONFIRMED"
        ]
        return_slips = {
            a["slip_id"] for a in db.attendance_records.values()
            if a["trip_id"] == tid and a["checkpoint"] == "RETURN"
        }
        for s in confirmed:
            if s["id"] not in return_slips:
                raise err("ERR_RETURN_HEADCOUNT_INCOMPLETE", "Return headcount incomplete.")
        t["status"] = "COMPLETED"
        touch(t)
        return success(S.field_trip_out(t), 200)

    @app.route("/field-trips/<tid>/cancel", methods=["POST"])
    @require_roles("Teacher", "Principal")
    def cancel_trip(tid, user_id, user_role):
        t = L.get_trip(tid)
        if t["status"] in ("COMPLETED", "CANCELLED"):
            raise err("ERR_TRIP_NOT_CANCELLABLE", "Trip already completed or cancelled.")
        cascade = t["status"] in ("APPROVED", "ROSTER_LOCKED")
        if cascade:
            _cancellation_cascade(t)
        t["status"] = "CANCELLED"
        touch(t)
        return success(S.field_trip_out(t), 200)

    # =====================================================================
    # Trip approvals read surface
    # =====================================================================
    @app.route("/trip-approvals", methods=["GET"])
    @require_roles("Teacher", "Principal", "DistrictAdmin")
    def list_approvals(user_id, user_role):
        items = list(db.trip_approvals.values())
        if "trip_id" in request.args:
            items = [a for a in items if a["trip_id"] == request.args.get("trip_id")]
        if "step" in request.args:
            items = [a for a in items if a["step"] == request.args.get("step")]
        window, limit, offset, total = paginate(items)
        return list_response([S.approval_out(a) for a in window], limit, offset, total)

    @app.route("/trip-approvals/<aid>", methods=["GET"])
    @require_roles("Teacher", "Principal", "DistrictAdmin")
    def get_approval_ep(aid, user_id, user_role):
        a = db.trip_approvals.get(aid)
        if a is None:
            raise err("ERR_VALIDATION", "Trip approval not found.")
        return success(S.approval_out(a), 200)

    # =====================================================================
    # Permission slips (PRD §3.3, §3.7, §3.10)
    # =====================================================================
    @app.route("/field-trips/<tid>/permission-slips", methods=["POST"])
    @require_roles("Teacher")
    def create_slip(tid, user_id, user_role):
        t = L.get_trip(tid)
        body = get_body()
        student_id = require_string(body, "student_id")
        guardian_id = require_string(body, "guardian_id")
        medical_notes = optional_string(body, "medical_notes", None)
        allergies = optional_array(body, "allergies", [])
        L.get_student(student_id)
        L.get_guardian(guardian_id)
        rec = stamp_create(versioned=True)
        rec.update({
            "trip_id": tid,
            "student_id": student_id,
            "guardian_id": guardian_id,
            "signature_status": "UNSIGNED",
            "payment_status": "UNPAID",
            "participation_status": "PENDING",
            "signed_at": None,
            "medical_notes": medical_notes,
            "allergies": allergies,
            "fee_due_cents": 0,
        })
        db.permission_slips[rec["id"]] = rec
        return success(S.slip_out(rec), 201)

    @app.route("/permission-slips", methods=["GET"])
    @require_roles("Teacher", "Principal", "DistrictAdmin", "Guardian")
    def list_slips(user_id, user_role):
        items = list(db.permission_slips.values())
        if "trip_id" in request.args:
            items = [s for s in items if s["trip_id"] == request.args.get("trip_id")]
        if "student_id" in request.args:
            items = [s for s in items if s["student_id"] == request.args.get("student_id")]
        if "guardian_id" in request.args:
            items = [s for s in items if s["guardian_id"] == request.args.get("guardian_id")]
        if "signature_status" in request.args:
            items = [s for s in items if s["signature_status"] == request.args.get("signature_status")]
        window, limit, offset, total = paginate(items)
        return list_response([S.slip_out(s) for s in window], limit, offset, total)

    @app.route("/permission-slips/<sid>", methods=["GET"])
    @require_roles("Teacher", "Principal", "DistrictAdmin", "Guardian")
    def get_slip_ep(sid, user_id, user_role):
        s = db.permission_slips.get(sid)
        if s is None:
            raise err("ERR_SLIP_NOT_FOUND", "Permission slip not found.")
        return success(S.slip_out(s), 200)

    @app.route("/field-trips/<tid>/permission-slips/<sid>/sign", methods=["POST"])
    @require_roles("Guardian")
    def sign_slip(tid, sid, user_id, user_role):
        t = L.get_trip(tid)
        s = L.get_slip_on_trip(tid, sid)
        if user_id != s["guardian_id"]:
            raise err("ERR_NOT_SLIP_GUARDIAN", "Acting guardian is not the slip guardian.")
        if t["status"] != "APPROVED":
            raise err("ERR_TRIP_NOT_OPEN_FOR_SIGNING", "Trip not open for signing.")
        if s["signature_status"] not in ("UNSIGNED", "REVOKED"):
            raise err("ERR_SLIP_ALREADY_SIGNED", "Slip already signed.")
        has_contact = any(
            e["slip_id"] == sid for e in db.emergency_contacts.values()
        )
        if not has_contact:
            raise err("ERR_EMERGENCY_CONTACT_REQUIRED", "Emergency contact required.")
        if t["signed_count"] >= t["capacity"]:
            raise err("ERR_TRIP_AT_CAPACITY", "Trip at capacity.")
        from response import now_iso
        s["signature_status"] = "SIGNED"
        s["signed_at"] = now_iso()
        t["signed_count"] += 1
        # The live signed_count changed: recompute every signed slip's provisional
        # transport share, not just this one (PRD §3.7).
        _recompute_all_provisional_fees(t)
        touch(s)
        touch(t)
        return success(S.slip_out(s), 200)

    @app.route("/field-trips/<tid>/permission-slips/<sid>/revoke", methods=["POST"])
    @require_roles("Guardian")
    def revoke_slip(tid, sid, user_id, user_role):
        t = L.get_trip(tid)
        s = L.get_slip_on_trip(tid, sid)
        if user_id != s["guardian_id"]:
            raise err("ERR_NOT_SLIP_GUARDIAN", "Acting guardian is not the slip guardian.")
        if t["status"] != "APPROVED":
            raise err("ERR_ROSTER_LOCKED", "Cannot revoke after the trip moves on.")
        if s["signature_status"] != "SIGNED":
            raise err("ERR_SLIP_NOT_SIGNED", "Slip is not signed.")
        s["signature_status"] = "REVOKED"
        t["signed_count"] -= 1
        # The live signed_count changed: recompute the remaining signed slips'
        # provisional transport share (PRD §3.7).
        _recompute_all_provisional_fees(t)
        touch(s)
        touch(t)
        return success(S.slip_out(s), 200)

    @app.route("/field-trips/<tid>/permission-slips/<sid>/pay", methods=["POST"])
    @require_roles("Guardian")
    def pay_slip(tid, sid, user_id, user_role):
        t = L.get_trip(tid)
        s = L.get_slip_on_trip(tid, sid)
        body = get_body()
        amount_cents = require_int(body, "amount_cents")
        if user_id != s["guardian_id"]:
            raise err("ERR_NOT_SLIP_GUARDIAN", "Acting guardian is not the slip guardian.")
        if s["signature_status"] != "SIGNED":
            raise err("ERR_SLIP_NOT_SIGNED", "Slip is not signed.")
        if s["payment_status"] != "UNPAID":
            raise err("ERR_SLIP_ALREADY_PAID", "Slip already paid.")
        if amount_cents != s["fee_due_cents"]:
            raise err("ERR_PAYMENT_AMOUNT_MISMATCH", "Payment amount does not match fee due.")
        s["payment_status"] = "PAID"
        ledger = stamp_create(versioned=False)
        ledger.update({
            "slip_id": sid,
            "trip_id": tid,
            "kind": "PAYMENT",
            "amount_cents": s["fee_due_cents"],
            "reason": "GUARDIAN_PAYMENT",
        })
        db.fee_transactions[ledger["id"]] = ledger
        touch(s)
        touch(t)
        return success(S.slip_out(s), 200)

    @app.route("/field-trips/<tid>/permission-slips/<sid>/withdraw", methods=["POST"])
    @require_roles("Guardian")
    def withdraw_slip(tid, sid, user_id, user_role):
        t = L.get_trip(tid)
        s = L.get_slip_on_trip(tid, sid)
        if user_id != s["guardian_id"]:
            raise err("ERR_NOT_SLIP_GUARDIAN", "Acting guardian is not the slip guardian.")
        if t["status"] in ("IN_PROGRESS", "COMPLETED", "CANCELLED"):
            raise err("ERR_TRIP_NOT_OPEN_FOR_WITHDRAWAL", "Trip not open for withdrawal.")
        if s["payment_status"] != "PAID":
            raise err("ERR_SLIP_NOT_PAID", "Slip is not paid.")
        was_signed = s["signature_status"] == "SIGNED"
        # committed transport share: final if locked, else provisional.
        if s.get("_final_transport_share") is not None:
            transport_share = s["_final_transport_share"]
        else:
            transport_share = calc.provisional_transport_share(t)
        refund = calc.voluntary_withdrawal_refund(t, s, transport_share)
        s["participation_status"] = "WITHDRAWN"
        if was_signed:
            s["signature_status"] = "REVOKED"
            t["signed_count"] -= 1
        s["payment_status"] = "REFUNDED"
        ledger = stamp_create(versioned=False)
        ledger.update({
            "slip_id": sid,
            "trip_id": tid,
            "kind": "REFUND",
            "amount_cents": -refund,
            "reason": "VOLUNTARY_WITHDRAWAL",
        })
        db.fee_transactions[ledger["id"]] = ledger
        touch(s)
        touch(t)
        return success(S.slip_out(s), 200)

    # =====================================================================
    # Emergency contacts (PRD §3.3)
    # =====================================================================
    @app.route("/field-trips/<tid>/permission-slips/<sid>/emergency-contacts", methods=["POST"])
    @require_roles("Teacher", "Guardian")
    def add_emergency_contact(tid, sid, user_id, user_role):
        L.get_trip(tid)
        L.get_slip_on_trip(tid, sid)
        body = get_body()
        name = require_string(body, "name")
        phone = require_string(body, "phone")
        relationship = require_string(body, "relationship")
        rec = stamp_create(versioned=False)
        rec.update({
            "slip_id": sid,
            "name": name,
            "phone": phone,
            "relationship": relationship,
        })
        db.emergency_contacts[rec["id"]] = rec
        return success(S.emergency_contact_out(rec), 201)

    @app.route("/emergency-contacts", methods=["GET"])
    @require_roles("Teacher", "Principal", "DistrictAdmin", "Guardian")
    def list_emergency_contacts(user_id, user_role):
        items = list(db.emergency_contacts.values())
        if "slip_id" in request.args:
            items = [e for e in items if e["slip_id"] == request.args.get("slip_id")]
        window, limit, offset, total = paginate(items)
        return list_response([S.emergency_contact_out(e) for e in window], limit, offset, total)

    @app.route("/emergency-contacts/<eid>", methods=["GET"])
    @require_roles("Teacher", "Principal", "DistrictAdmin", "Guardian")
    def get_emergency_contact_ep(eid, user_id, user_role):
        e = db.emergency_contacts.get(eid)
        if e is None:
            raise err("ERR_VALIDATION", "Emergency contact not found.")
        return success(S.emergency_contact_out(e), 200)

    # =====================================================================
    # Scholarship grants create/revoke (PRD §3.7)
    # =====================================================================
    @app.route("/field-trips/<tid>/permission-slips/<sid>/scholarship-grants", methods=["POST"])
    @require_roles("Teacher", "Principal")
    def create_scholarship_grant(tid, sid, user_id, user_role):
        t = L.get_trip(tid)
        s = L.get_slip_on_trip(tid, sid)
        body = get_body()
        pool_id = require_string(body, "pool_id")
        award_cents = require_int(body, "award_cents", minimum=1)
        pool = L.get_pool(pool_id)
        # fiscal bounds (priority 11)
        remaining = pool["total_cents"] - calc.pool_granted_cents(pool_id)
        if award_cents > remaining:
            raise err("ERR_SCHOLARSHIP_POOL_EXHAUSTED", "Award exceeds pool remaining.")
        # waivable = gross - deposit. gross uses the slip's current transport share.
        if s.get("_final_transport_share") is not None:
            transport_share = s["_final_transport_share"]
        else:
            transport_share = calc.provisional_transport_share(t)
        gross = t["base_fee_cents"] + transport_share
        waivable = max(gross - t["deposit_cents"], 0)
        existing = calc.slip_scholarship_award(sid)
        if existing + award_cents > waivable:
            raise err("ERR_AWARD_EXCEEDS_WAIVABLE", "Award exceeds slip waivable amount.")
        rec = stamp_create(versioned=True)
        rec.update({
            "slip_id": sid,
            "pool_id": pool_id,
            "award_cents": award_cents,
            "status": "ACTIVE",
        })
        db.scholarship_grants[rec["id"]] = rec
        touch(pool)
        _recompute_slip_fee(t, s)
        touch(s)
        return success(S.grant_out(rec), 201)

    @app.route("/field-trips/<tid>/permission-slips/<sid>/scholarship-grants/<gid>/revoke", methods=["POST"])
    @require_roles("Teacher", "Principal")
    def revoke_scholarship_grant(tid, sid, gid, user_id, user_role):
        t = L.get_trip(tid)
        s = L.get_slip_on_trip(tid, sid)
        g = L.get_grant_on_slip(sid, gid)
        if g["status"] != "ACTIVE":
            raise err("ERR_GRANT_NOT_ACTIVE", "Grant is not active.")
        g["status"] = "REVOKED"
        touch(g)
        pool = db.scholarship_pools.get(g["pool_id"])
        if pool is not None:
            touch(pool)
        _recompute_slip_fee(t, s)
        touch(s)
        return success(S.grant_out(g), 200)

    # =====================================================================
    # Chaperones (PRD §3.4, §3.5)
    # =====================================================================
    @app.route("/field-trips/<tid>/chaperones", methods=["POST"])
    @require_roles("Teacher")
    def invite_chaperone(tid, user_id, user_role):
        L.get_trip(tid)
        body = get_body()
        guardian_id = require_string(body, "guardian_id")
        assigned_student_id = optional_string(body, "assigned_student_id", None)
        background_check_ref = optional_string(body, "background_check_ref", None)
        L.get_guardian(guardian_id)
        if assigned_student_id is not None:
            L.get_student(assigned_student_id)
        rec = stamp_create(versioned=True)
        rec.update({
            "trip_id": tid,
            "guardian_id": guardian_id,
            "assigned_student_id": assigned_student_id,
            "status": "INVITED",
            "background_check_ref": background_check_ref,
        })
        db.chaperones[rec["id"]] = rec
        return success(S.chaperone_out(rec), 201)

    @app.route("/chaperones", methods=["GET"])
    @require_roles("Teacher", "Principal", "DistrictAdmin", "Guardian")
    def list_chaperones(user_id, user_role):
        items = list(db.chaperones.values())
        if "trip_id" in request.args:
            items = [c for c in items if c["trip_id"] == request.args.get("trip_id")]
        if "guardian_id" in request.args:
            items = [c for c in items if c["guardian_id"] == request.args.get("guardian_id")]
        if "assigned_student_id" in request.args:
            items = [c for c in items if c["assigned_student_id"] == request.args.get("assigned_student_id")]
        if "status" in request.args:
            items = [c for c in items if c["status"] == request.args.get("status")]
        window, limit, offset, total = paginate(items)
        return list_response([S.chaperone_out(c) for c in window], limit, offset, total)

    @app.route("/chaperones/<cid>", methods=["GET"])
    @require_roles("Teacher", "Principal", "DistrictAdmin", "Guardian")
    def get_chaperone_ep(cid, user_id, user_role):
        c = db.chaperones.get(cid)
        if c is None:
            raise err("ERR_CHAPERONE_NOT_FOUND", "Chaperone not found.")
        return success(S.chaperone_out(c), 200)

    @app.route("/field-trips/<tid>/chaperones/<cid>/confirm", methods=["POST"])
    @require_roles("Guardian")
    def confirm_chaperone(tid, cid, user_id, user_role):
        L.get_trip(tid)
        c = L.get_chaperone_on_trip(tid, cid)
        if user_id != c["guardian_id"]:
            raise err("ERR_NOT_CHAPERONE_GUARDIAN", "Acting guardian is not the chaperone guardian.")
        if c["status"] != "INVITED":
            raise err("ERR_CHAPERONE_NOT_INVITED", "Chaperone not in INVITED.")
        c["status"] = "CONFIRMED"
        touch(c)
        return success(S.chaperone_out(c), 200)

    @app.route("/field-trips/<tid>/chaperones/<cid>/clear", methods=["POST"])
    @require_roles("Principal")
    def clear_chaperone(tid, cid, user_id, user_role):
        t = L.get_trip(tid)
        c = L.get_chaperone_on_trip(tid, cid)
        if c["status"] != "CONFIRMED":
            raise err("ERR_CHAPERONE_NOT_CONFIRMED", "Chaperone not in CONFIRMED.")
        if t["status"] not in ("APPROVED", "ROSTER_LOCKED"):
            raise err("ERR_TRIP_NOT_APPROVED", "Trip not in APPROVED/ROSTER_LOCKED.")
        if not c.get("background_check_ref"):
            raise err("ERR_BACKGROUND_CHECK_MISSING", "Background check reference missing.")
        _check_chaperone_window(t, c)
        c["status"] = "CLEARED"
        touch(c)
        return success(S.chaperone_out(c), 200)

    @app.route("/field-trips/<tid>/chaperones/<cid>/withdraw", methods=["POST"])
    @require_roles("Guardian")
    def withdraw_chaperone(tid, cid, user_id, user_role):
        t = L.get_trip(tid)
        c = L.get_chaperone_on_trip(tid, cid)
        if user_id != c["guardian_id"]:
            raise err("ERR_NOT_CHAPERONE_GUARDIAN", "Acting guardian is not the chaperone guardian.")
        if c["status"] == "WITHDRAWN":
            raise err("ERR_CHAPERONE_NOT_WITHDRAWABLE", "Chaperone already withdrawn.")
        if t["status"] == "ROSTER_LOCKED":
            raise err("ERR_ROSTER_LOCKED", "Cannot withdraw after roster locks.")
        c["status"] = "WITHDRAWN"
        touch(c)
        return success(S.chaperone_out(c), 200)

    # =====================================================================
    # Transport bookings (PRD §3.6)
    # =====================================================================
    @app.route("/field-trips/<tid>/transport-bookings", methods=["POST"])
    @require_roles("Teacher")
    def request_booking(tid, user_id, user_role):
        L.get_trip(tid)
        body = get_body()
        vehicle_id = require_string(body, "vehicle_id")
        seat_count = require_int(body, "seat_count", minimum=1)
        L.get_vehicle(vehicle_id)
        rec = stamp_create(versioned=True)
        rec.update({
            "trip_id": tid,
            "vehicle_id": vehicle_id,
            "seat_count": seat_count,
            "status": "REQUESTED",
        })
        db.transport_bookings[rec["id"]] = rec
        return success(S.booking_out(rec), 201)

    @app.route("/transport-bookings", methods=["GET"])
    @require_roles("Teacher", "Principal", "DistrictAdmin")
    def list_bookings(user_id, user_role):
        items = list(db.transport_bookings.values())
        if "trip_id" in request.args:
            items = [b for b in items if b["trip_id"] == request.args.get("trip_id")]
        if "vehicle_id" in request.args:
            items = [b for b in items if b["vehicle_id"] == request.args.get("vehicle_id")]
        if "status" in request.args:
            items = [b for b in items if b["status"] == request.args.get("status")]
        window, limit, offset, total = paginate(items)
        return list_response([S.booking_out(b) for b in window], limit, offset, total)

    @app.route("/transport-bookings/<bid>", methods=["GET"])
    @require_roles("Teacher", "Principal", "DistrictAdmin")
    def get_booking_ep(bid, user_id, user_role):
        b = db.transport_bookings.get(bid)
        if b is None:
            raise err("ERR_BOOKING_NOT_FOUND", "Transport booking not found.")
        return success(S.booking_out(b), 200)

    @app.route("/field-trips/<tid>/transport-bookings/<bid>/confirm", methods=["POST"])
    @require_roles("Teacher")
    def confirm_booking(tid, bid, user_id, user_role):
        t = L.get_trip(tid)
        b = L.get_booking_on_trip(tid, bid)
        if b["status"] != "REQUESTED":
            raise err("ERR_BOOKING_NOT_REQUESTED", "Booking not in REQUESTED.")
        vehicle = db.vehicles.get(b["vehicle_id"])
        if vehicle is None:
            raise err("ERR_VEHICLE_NOT_FOUND", "Vehicle not found.")
        if vehicle["status"] != "ACTIVE":
            raise err("ERR_VEHICLE_RETIRED", "Vehicle is retired.")
        reserved = calc.vehicle_seats_reserved(vehicle["id"])
        if reserved + b["seat_count"] > vehicle["seat_capacity"]:
            raise err("ERR_VEHICLE_OVERBOOKED", "Vehicle overbooked.")
        _check_vehicle_window(t, b, vehicle)
        b["status"] = "CONFIRMED"
        touch(b)
        touch(vehicle)
        return success(S.booking_out(b), 200)

    @app.route("/field-trips/<tid>/transport-bookings/<bid>/cancel", methods=["POST"])
    @require_roles("Teacher")
    def cancel_booking(tid, bid, user_id, user_role):
        t = L.get_trip(tid)
        b = L.get_booking_on_trip(tid, bid)
        if b["status"] == "CANCELLED":
            raise err("ERR_BOOKING_NOT_CANCELLABLE", "Booking already cancelled.")
        if b["status"] == "CONFIRMED" and t["status"] == "ROSTER_LOCKED":
            raise err("ERR_ROSTER_LOCKED", "Confirmed transport is frozen at lock.")
        was_confirmed = b["status"] == "CONFIRMED"
        b["status"] = "CANCELLED"
        touch(b)
        if was_confirmed:
            vehicle = db.vehicles.get(b["vehicle_id"])
            if vehicle is not None:
                touch(vehicle)
        return success(S.booking_out(b), 200)

    # =====================================================================
    # Fee transactions read surface (PRD §3.11)
    # =====================================================================
    @app.route("/fee-transactions", methods=["GET"])
    @require_roles("Teacher", "Principal", "DistrictAdmin", "Guardian")
    def list_fee_transactions(user_id, user_role):
        items = list(db.fee_transactions.values())
        if "slip_id" in request.args:
            items = [f for f in items if f["slip_id"] == request.args.get("slip_id")]
        if "trip_id" in request.args:
            items = [f for f in items if f["trip_id"] == request.args.get("trip_id")]
        if "kind" in request.args:
            items = [f for f in items if f["kind"] == request.args.get("kind")]
        window, limit, offset, total = paginate(items)
        return list_response([S.fee_transaction_out(f) for f in window], limit, offset, total)

    @app.route("/fee-transactions/<fid>", methods=["GET"])
    @require_roles("Teacher", "Principal", "DistrictAdmin", "Guardian")
    def get_fee_transaction_ep(fid, user_id, user_role):
        f = db.fee_transactions.get(fid)
        if f is None:
            raise err("ERR_VALIDATION", "Fee transaction not found.")
        return success(S.fee_transaction_out(f), 200)

    # =====================================================================
    # Attendance (PRD §3.9)
    # =====================================================================
    @app.route("/field-trips/<tid>/attendance", methods=["POST"])
    @require_roles("Teacher")
    def record_attendance(tid, user_id, user_role):
        L.get_trip(tid)
        body = get_body()
        slip_id = require_string(body, "slip_id")
        checkpoint = require_enum(body, "checkpoint", {"DEPARTURE", "RETURN"})
        present = require_bool(body, "present")
        L.get_slip_on_trip(tid, slip_id)
        rec = stamp_create(versioned=False)
        rec.update({
            "trip_id": tid,
            "slip_id": slip_id,
            "checkpoint": checkpoint,
            "present": present,
        })
        db.attendance_records[rec["id"]] = rec
        return success(S.attendance_out(rec), 201)

    @app.route("/attendance-records", methods=["GET"])
    @require_roles("Teacher", "Principal", "DistrictAdmin")
    def list_attendance(user_id, user_role):
        items = list(db.attendance_records.values())
        if "trip_id" in request.args:
            items = [a for a in items if a["trip_id"] == request.args.get("trip_id")]
        if "slip_id" in request.args:
            items = [a for a in items if a["slip_id"] == request.args.get("slip_id")]
        if "checkpoint" in request.args:
            items = [a for a in items if a["checkpoint"] == request.args.get("checkpoint")]
        window, limit, offset, total = paginate(items)
        return list_response([S.attendance_out(a) for a in window], limit, offset, total)

    @app.route("/attendance-records/<aid>", methods=["GET"])
    @require_roles("Teacher", "Principal", "DistrictAdmin")
    def get_attendance_ep(aid, user_id, user_role):
        a = db.attendance_records.get(aid)
        if a is None:
            raise err("ERR_VALIDATION", "Attendance record not found.")
        return success(S.attendance_out(a), 200)


# =========================================================================
# Shared helpers
# =========================================================================

def _recompute_slip_fee(trip, slip):
    """Recompute slip fee in the variant appropriate to the trip state."""
    if slip.get("_final_transport_share") is not None:
        slip["fee_due_cents"] = calc.compute_fee_due(trip, slip, slip["_final_transport_share"])
    else:
        calc.recompute_provisional_fee(trip, slip)


def _recompute_all_provisional_fees(trip):
    """Recompute the provisional fee of every SIGNED, not-yet-finalized slip on
    the trip. PRD §3.7: the provisional transport share is transport_cost_cents
    divided by the live signed_count, "an estimate that shifts as other guardians
    sign and revoke" — so every signed slip's fee must follow the current
    signed_count, not just the slip that triggered the change.
    """
    tid = trip["id"]
    for s in db.permission_slips.values():
        if s["trip_id"] != tid:
            continue
        if s.get("_final_transport_share") is not None:
            continue
        if s["signature_status"] != "SIGNED":
            continue
        calc.recompute_provisional_fee(trip, s)
        touch(s)


def _check_vehicle_window(trip, booking, vehicle):
    """Closed-interval overlap, no buffer (PRD §3.5 / vehicle_window_overlap)."""
    a1 = trip["depart_at"]
    b1 = trip["return_at"]
    for other in db.transport_bookings.values():
        if other["id"] == booking["id"]:
            continue
        if other["vehicle_id"] != vehicle["id"]:
            continue
        if other["status"] != "CONFIRMED":
            continue
        other_trip = db.field_trips.get(other["trip_id"])
        if other_trip is None:
            continue
        a2 = other_trip["depart_at"]
        b2 = other_trip["return_at"]
        # closed-interval overlap: a1 <= b2 AND a2 <= b1
        if a1 <= b2 and a2 <= b1:
            raise err("ERR_VEHICLE_TIME_CONFLICT", "Vehicle time conflict.")


def _check_chaperone_window(trip, chaperone):
    """Half-open buffered overlap (PRD §3.5 / chaperone_window_overlap)."""
    from datetime import datetime, timezone

    def parse(ts):
        s = ts.replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()

    a1 = parse(trip["depart_at"])
    b1 = parse(trip["return_at"])
    buffered_start = a1 - calc.TRAVEL_BUFFER
    buffered_end = b1 + calc.TRAVEL_BUFFER
    for other in db.chaperones.values():
        if other["id"] == chaperone["id"]:
            continue
        if other["guardian_id"] != chaperone["guardian_id"]:
            continue
        if other["status"] != "CLEARED":
            continue
        other_trip = db.field_trips.get(other["trip_id"])
        if other_trip is None:
            continue
        a2 = parse(other_trip["depart_at"])
        b2 = parse(other_trip["return_at"])
        # half-open: buffered_start < b2 AND a2 < buffered_end
        if buffered_start < b2 and a2 < buffered_end:
            raise err("ERR_CHAPERONE_TIME_CONFLICT", "Chaperone time conflict.")


def _cancellation_cascade(trip):
    """TRIP_CANCELLATION cascade (PRD §3.10)."""
    tid = trip["id"]
    # 1. PAID slips -> REFUNDED + REVOKED; full refund ledger entry.
    for s in db.permission_slips.values():
        if s["trip_id"] != tid:
            continue
        if s["payment_status"] == "PAID":
            paid = calc.slip_net_paid(s["id"])
            s["payment_status"] = "REFUNDED"
            s["signature_status"] = "REVOKED"
            ledger = stamp_create(versioned=False)
            ledger.update({
                "slip_id": s["id"],
                "trip_id": tid,
                "kind": "REFUND",
                "amount_cents": -paid,
                "reason": "TRIP_CANCELLATION",
            })
            db.fee_transactions[ledger["id"]] = ledger
            touch(s)
    # 2. CONFIRMED/REQUESTED bookings -> CANCELLED; release confirmed seats.
    for b in db.transport_bookings.values():
        if b["trip_id"] != tid:
            continue
        if b["status"] in ("CONFIRMED", "REQUESTED"):
            was_confirmed = b["status"] == "CONFIRMED"
            b["status"] = "CANCELLED"
            touch(b)
            if was_confirmed:
                vehicle = db.vehicles.get(b["vehicle_id"])
                if vehicle is not None:
                    touch(vehicle)
    # 3. Non-WITHDRAWN chaperones -> WITHDRAWN.
    for c in db.chaperones.values():
        if c["trip_id"] != tid:
            continue
        if c["status"] != "WITHDRAWN":
            c["status"] = "WITHDRAWN"
            touch(c)
