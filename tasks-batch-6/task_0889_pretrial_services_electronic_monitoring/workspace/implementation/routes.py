"""All API endpoints (45) for the Pretrial Services & EM platform."""

from flask import g, request

import domain
from auth import authenticate, authorize
from clock import (LOGICAL_CLOCK, add_days, add_hours, add_minutes,
                   render_datetime)
from errors import ApiError
from helpers import get_or_404, matches, matches_int, paged_list
from response import object_response
from serializers import (assessment_json, check_in_json, court_event_json,
                         curfew_window_json, defendant_json, drug_test_json,
                         em_device_json, em_enrollment_json, ledger_entry_json,
                         level_adjustment_json, location_ping_json,
                         release_order_json, testing_site_json, violation_json)
from store import DB, base_record, touch
from validation import (bad, json_body, opt_bool, opt_int, qs, req_bool,
                        req_date_str, req_datetime, req_enum, req_enum_list,
                        req_int, req_string, opt_string)

# ---- roles ------------------------------------------------------------------
INTAKE = "IntakeOfficer"
SUPER = "SupervisingOfficer"
JUDGE = "JudicialOfficer"
ADMIN = "ProgramAdmin"
DEF = "Defendant"
ALL_READ = (INTAKE, SUPER, JUDGE, ADMIN)

# ---- enum sets --------------------------------------------------------------
INSTRUMENTS = {"SCREENING", "FULL"}
EMPLOYMENT = {"EMPLOYED", "UNEMPLOYED"}
RESIDENCE = {"STABLE", "UNSTABLE"}
DECISIONS = {"RELEASE", "DETAIN"}
CONDITIONS = {"CURFEW", "NO_CONTACT", "GPS_MONITORING", "DRUG_TESTING", "CHECK_IN"}
VIOLATION_TYPES = {"CURFEW", "MISSED_CHECK_IN", "POSITIVE_TEST", "FTA",
                   "NEW_ARREST", "OTHER"}
SEVERITIES = {"MINOR", "MODERATE", "MAJOR"}
TEST_KINDS = {"DRUG", "ALCOHOL"}
LEDGER_TYPES = {"CHARGE", "PAYMENT", "WAIVER", "REVERSAL"}
LEVELS = {"MINIMUM", "MEDIUM", "MAXIMUM"}


# ---- transition prelude -----------------------------------------------------
def _transition_prelude(collection, res_id, role_map, union):
    raw = request.get_json(silent=True)
    to_status = raw.get("to_status") if isinstance(raw, dict) else None
    if isinstance(to_status, str) and to_status in role_map:
        allowed = role_map[to_status]
    else:
        allowed = union
    if g.role not in allowed:
        raise ApiError("ERR_UNAUTHORIZED",
                       "Role %s may not perform this transition." % g.role)
    rec = get_or_404(collection, res_id)
    return rec, to_status


def _require_status(to_status, transitions, current):
    if not isinstance(to_status, str):
        bad("Field 'to_status' is required.")
    legal_targets = transitions.get(current, {})
    if to_status not in legal_targets:
        raise ApiError("ERR_INVALID_STATE",
                       "Cannot transition from %s to %s." % (current, to_status))


def register(app):
    # =========================================================================
    # Clock / configuration
    # =========================================================================
    @app.route("/_clock/set_current_utc", methods=["POST"])
    def set_clock():
        authenticate()
        authorize(ADMIN)
        body = json_body()
        moment = req_datetime(body, "to_iso8601")
        LOGICAL_CLOCK.set(moment)
        return object_response({"current_utc": render_datetime(LOGICAL_CLOCK.now())})

    # ---- testing sites ------------------------------------------------------
    @app.route("/testing-sites", methods=["POST"])
    def create_testing_site():
        authenticate()
        authorize(ADMIN)
        body = json_body()
        name = req_string(body, "name")
        slot_capacity = req_int(body, "slot_capacity", minimum=1)
        rec = base_record()
        rec.update({"name": name, "slot_capacity": slot_capacity})
        DB.testing_sites[rec["id"]] = rec
        return object_response(testing_site_json(rec), 201)

    @app.route("/testing-sites/<sid>", methods=["GET"])
    def get_testing_site(sid):
        authenticate()
        authorize(*ALL_READ)
        rec = get_or_404(DB.testing_sites, sid)
        return object_response(testing_site_json(rec))

    @app.route("/testing-sites/<sid>/drug-tests", methods=["GET"])
    def list_site_drug_tests(sid):
        authenticate()
        authorize(*ALL_READ)
        get_or_404(DB.testing_sites, sid)
        f_status = qs("status")
        rows = [t for t in DB.drug_tests.values()
                if t["site_id"] == sid and matches(t["status"], f_status)]
        return paged_list(rows, drug_test_json)

    # ---- EM devices ---------------------------------------------------------
    @app.route("/em-devices", methods=["POST"])
    def create_em_device():
        authenticate()
        authorize(ADMIN)
        body = json_body()
        model_name = req_string(body, "model_name")
        total_units = req_int(body, "total_units", minimum=0)
        rec = base_record()
        rec.update({"model_name": model_name, "total_units": total_units,
                    "available_units": total_units})
        DB.em_devices[rec["id"]] = rec
        return object_response(em_device_json(rec), 201)

    @app.route("/em-devices/<did>", methods=["GET"])
    def get_em_device(did):
        authenticate()
        authorize(*ALL_READ)
        rec = get_or_404(DB.em_devices, did)
        return object_response(em_device_json(rec))

    @app.route("/em-devices/<did>/enrollments", methods=["GET"])
    def list_device_enrollments(did):
        authenticate()
        authorize(*ALL_READ)
        get_or_404(DB.em_devices, did)
        f_status = qs("status")
        rows = [e for e in DB.em_enrollments.values()
                if e["device_id"] == did and matches(e["status"], f_status)]
        return paged_list(rows, em_enrollment_json)

    # =========================================================================
    # Defendant
    # =========================================================================
    @app.route("/defendants", methods=["POST"])
    def create_defendant():
        authenticate()
        authorize(INTAKE)
        body = json_body()
        case_number = req_string(body, "case_number")
        full_name = req_string(body, "full_name")
        date_of_birth = req_date_str(body, "date_of_birth")
        indigent = opt_bool(body, "indigent", default=False)
        for d in DB.defendants.values():
            if d["case_number"] == case_number:
                bad("case_number must be unique across defendants.")
        rec = base_record()
        rec.update({
            "case_number": case_number,
            "full_name": full_name,
            "date_of_birth": date_of_birth,
            "indigent": indigent,
            "supervision_status": "PRETRIAL_PENDING",
            "supervision_level": None,
            "risk_tier": None,
            "cumulative_violation_score": 0,
            "balance_owed_cents": 0,
        })
        DB.defendants[rec["id"]] = rec
        return object_response(defendant_json(rec), 201)

    @app.route("/defendants/<did>", methods=["GET"])
    def get_defendant(did):
        authenticate()
        authorize(INTAKE, SUPER, JUDGE, ADMIN, DEF)
        rec = get_or_404(DB.defendants, did)
        if g.role == DEF and g.user_id != did:
            raise ApiError("ERR_UNAUTHORIZED", "Defendants may only view their own record.")
        return object_response(defendant_json(rec))

    @app.route("/defendants", methods=["GET"])
    def list_defendants():
        authenticate()
        authorize(*ALL_READ)
        f_status = qs("supervision_status")
        f_level = qs("supervision_level")
        rows = [d for d in DB.defendants.values()
                if matches(d["supervision_status"], f_status)
                and matches(d["supervision_level"], f_level)]
        return paged_list(rows, defendant_json)

    @app.route("/defendants/<did>/transition", methods=["POST"])
    def transition_defendant(did):
        authenticate()
        role_map = {"DISCHARGED": {JUDGE, SUPER}, "TERMINATED": {JUDGE, SUPER}}
        rec, to_status = _transition_prelude(DB.defendants, did, role_map,
                                             {JUDGE, SUPER})
        transitions = {"ACTIVE": {"DISCHARGED": 1, "TERMINATED": 1}}
        _require_status(to_status, transitions, rec["supervision_status"])
        rec["supervision_status"] = to_status
        touch(rec)
        return object_response(defendant_json(rec))

    @app.route("/defendants/<did>/level-adjustments", methods=["POST"])
    def create_level_adjustment(did):
        authenticate()
        authorize(SUPER, JUDGE)
        defendant = get_or_404(DB.defendants, did)
        body = json_body()
        expected = req_int(body, "expected_defendant_version")
        if expected != defendant["version"]:
            raise ApiError("ERR_STALE_VERSION",
                           "expected_defendant_version does not match.")
        to_level = req_enum(body, "to_level", LEVELS)
        reason = opt_string(body, "reason")
        prior = defendant["supervision_level"]
        defendant["supervision_level"] = to_level
        touch(defendant)
        adj = base_record(versioned=False)
        adj.update({
            "defendant_id": did,
            "from_level": prior,
            "to_level": to_level,
            "source": "MANUAL",
            "reason": reason,
            "adjusted_by_user_id": g.user_id,
        })
        DB.level_adjustments[adj["id"]] = adj
        return object_response(level_adjustment_json(adj), 201)

    @app.route("/defendants/<did>/level-adjustments", methods=["GET"])
    def list_level_adjustments(did):
        authenticate()
        authorize(*ALL_READ)
        get_or_404(DB.defendants, did)
        f_source = qs("source")
        rows = [a for a in DB.level_adjustments.values()
                if a["defendant_id"] == did and matches(a["source"], f_source)]
        return paged_list(rows, level_adjustment_json)

    @app.route("/defendants/<did>/fees", methods=["POST"])
    def assess_fee(did):
        authenticate()
        authorize(SUPER, ADMIN)
        defendant = get_or_404(DB.defendants, did)
        body = json_body()
        supervision_days = req_int(body, "supervision_days", minimum=0)
        em_days = req_int(body, "em_days", minimum=0)
        scheduled_test_count = req_int(body, "scheduled_test_count", minimum=0)
        charge = domain.supervision_fee(defendant["indigent"], supervision_days,
                                        em_days, scheduled_test_count)
        entry = base_record(versioned=False)
        entry.update({
            "defendant_id": did,
            "entry_type": "CHARGE",
            "amount_cents": charge,
            "reverses_entry_id": None,
            "source": "SUPERVISION_FEE",
        })
        DB.ledger_entries[entry["id"]] = entry
        domain.recompute_balance(defendant)
        touch(defendant)
        return object_response(ledger_entry_json(entry), 201)

    @app.route("/defendants/<did>/ledger-entries", methods=["POST"])
    def post_ledger_entry(did):
        authenticate()
        authorize(SUPER, ADMIN)
        defendant = get_or_404(DB.defendants, did)
        body = json_body()
        entry_type = req_enum(body, "entry_type", LEDGER_TYPES)
        if entry_type == "CHARGE":
            bad("CHARGE entries are created via the fee endpoint.")
        reverses_entry_id = None
        if entry_type == "REVERSAL":
            reverses_entry_id = req_string(body, "reverses_entry_id")
            ref = DB.ledger_entries.get(reverses_entry_id)
            if ref is None or ref["defendant_id"] != did:
                bad("reverses_entry_id does not reference a known ledger entry.")
            amount = -ref["amount_cents"]
        else:  # PAYMENT or WAIVER
            magnitude = req_int(body, "amount_cents")
            amount = -abs(magnitude)
        entry = base_record(versioned=False)
        entry.update({
            "defendant_id": did,
            "entry_type": entry_type,
            "amount_cents": amount,
            "reverses_entry_id": reverses_entry_id,
            "source": "MANUAL",
        })
        DB.ledger_entries[entry["id"]] = entry
        domain.recompute_balance(defendant)
        touch(defendant)
        return object_response(ledger_entry_json(entry), 201)

    @app.route("/defendants/<did>/ledger", methods=["GET"])
    def list_ledger(did):
        authenticate()
        authorize(*ALL_READ)
        get_or_404(DB.defendants, did)
        f_type = qs("entry_type")
        rows = [e for e in DB.ledger_entries.values()
                if e["defendant_id"] == did and matches(e["entry_type"], f_type)]
        return paged_list(rows, ledger_entry_json)

    # =========================================================================
    # RiskAssessment
    # =========================================================================
    @app.route("/assessments", methods=["POST"])
    def create_assessment():
        authenticate()
        authorize(INTAKE)
        body = json_body()
        defendant_id = req_string(body, "defendant_id")
        get_or_404(DB.defendants, defendant_id)
        instrument_type = req_enum(body, "instrument_type", INSTRUMENTS)
        prior_failures = req_int(body, "prior_failures", minimum=0)
        pending_charges_count = req_int(body, "pending_charges_count", minimum=0)
        pending_violent_charge = opt_bool(body, "pending_violent_charge", default=False)
        employment_status = req_enum(body, "employment_status", EMPLOYMENT)
        residence_stability = req_enum(body, "residence_stability", RESIDENCE)
        substance_flag = opt_bool(body, "substance_flag", default=False)
        rec = base_record()
        rec.update({
            "defendant_id": defendant_id,
            "instrument_type": instrument_type,
            "prior_failures": prior_failures,
            "pending_charges_count": pending_charges_count,
            "pending_violent_charge": pending_violent_charge,
            "employment_status": employment_status,
            "residence_stability": residence_stability,
            "substance_flag": substance_flag,
            "status": "DRAFT",
            "raw_score": None,
            "recommended_level": None,
            "submitted_by_user_id": None,
        })
        DB.assessments[rec["id"]] = rec
        return object_response(assessment_json(rec), 201)

    @app.route("/assessments/<aid>/transition", methods=["POST"])
    def transition_assessment(aid):
        authenticate()
        role_map = {"SUBMITTED": {INTAKE}, "DRAFT": {JUDGE},
                    "APPROVED": {JUDGE}, "REJECTED": {JUDGE}}
        rec, to_status = _transition_prelude(DB.assessments, aid, role_map,
                                             {INTAKE, JUDGE})
        transitions = {
            "DRAFT": {"SUBMITTED": 1},
            "SUBMITTED": {"DRAFT": 1, "APPROVED": 1, "REJECTED": 1},
        }
        _require_status(to_status, transitions, rec["status"])
        if to_status == "SUBMITTED":
            raw = domain.risk_score(rec)
            rec["raw_score"] = raw
            rec["recommended_level"] = domain.recommended_level(rec, raw)
            rec["submitted_by_user_id"] = g.user_id
            rec["status"] = "SUBMITTED"
            touch(rec)
        elif to_status == "DRAFT":
            rec["submitted_by_user_id"] = None
            rec["status"] = "DRAFT"
            touch(rec)
        elif to_status in ("APPROVED", "REJECTED"):
            if g.user_id == rec["submitted_by_user_id"]:
                raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                               "Approver/rejecter must differ from submitter.")
            rec["status"] = to_status
            touch(rec)
            if to_status == "APPROVED":
                defendant = DB.defendants.get(rec["defendant_id"])
                if defendant is not None:
                    defendant["risk_tier"] = domain.LEVEL_TO_TIER.get(
                        rec["recommended_level"])
                    touch(defendant)
        return object_response(assessment_json(rec))

    @app.route("/assessments/<aid>", methods=["GET"])
    def get_assessment(aid):
        authenticate()
        authorize(*ALL_READ)
        rec = get_or_404(DB.assessments, aid)
        return object_response(assessment_json(rec))

    @app.route("/defendants/<did>/assessments", methods=["GET"])
    def list_defendant_assessments(did):
        authenticate()
        authorize(*ALL_READ)
        get_or_404(DB.defendants, did)
        f_status = qs("status")
        rows = [a for a in DB.assessments.values()
                if a["defendant_id"] == did and matches(a["status"], f_status)]
        return paged_list(rows, assessment_json)

    # =========================================================================
    # ReleaseOrder
    # =========================================================================
    @app.route("/release-orders", methods=["POST"])
    def create_release_order():
        authenticate()
        authorize(JUDGE)
        body = json_body()
        defendant_id = req_string(body, "defendant_id")
        get_or_404(DB.defendants, defendant_id)
        assessment_id = req_string(body, "assessment_id")
        get_or_404(DB.assessments, assessment_id)
        decision = req_enum(body, "decision", DECISIONS)
        ordered_conditions = req_enum_list(body, "ordered_conditions", CONDITIONS)
        rec = base_record()
        rec.update({
            "defendant_id": defendant_id,
            "assessment_id": assessment_id,
            "decision": decision,
            "ordered_conditions": ordered_conditions,
            "status": "PROPOSED",
        })
        DB.release_orders[rec["id"]] = rec
        return object_response(release_order_json(rec), 201)

    @app.route("/release-orders/<oid>/transition", methods=["POST"])
    def transition_release_order(oid):
        authenticate()
        role_map = {"ORDERED": {JUDGE}, "DENIED": {JUDGE}, "VACATED": {JUDGE}}
        rec, to_status = _transition_prelude(DB.release_orders, oid, role_map, {JUDGE})
        transitions = {
            "PROPOSED": {"ORDERED": 1, "DENIED": 1},
            "ORDERED": {"VACATED": 1},
        }
        _require_status(to_status, transitions, rec["status"])
        if to_status == "ORDERED":
            assessment = DB.assessments.get(rec["assessment_id"])
            if assessment is None or assessment["status"] != "APPROVED":
                raise ApiError("ERR_ASSESSMENT_NOT_APPROVED",
                               "Linked assessment is not APPROVED.")
            rec["status"] = "ORDERED"
            touch(rec)
            if rec["decision"] == "RELEASE":
                defendant = DB.defendants.get(rec["defendant_id"])
                if defendant is not None:
                    defendant["supervision_status"] = "ACTIVE"
                    defendant["supervision_level"] = assessment["recommended_level"]
                    touch(defendant)
        elif to_status == "DENIED":
            rec["status"] = "DENIED"
            touch(rec)
        elif to_status == "VACATED":
            rec["status"] = "VACATED"
            touch(rec)
            defendant = DB.defendants.get(rec["defendant_id"])
            if defendant is not None:
                defendant["supervision_status"] = "TERMINATED"
                touch(defendant)
        return object_response(release_order_json(rec))

    @app.route("/defendants/<did>/release-orders", methods=["GET"])
    def list_defendant_release_orders(did):
        authenticate()
        authorize(*ALL_READ)
        get_or_404(DB.defendants, did)
        f_status = qs("status")
        rows = [o for o in DB.release_orders.values()
                if o["defendant_id"] == did and matches(o["status"], f_status)]
        return paged_list(rows, release_order_json)

    @app.route("/assessments/<aid>/release-orders", methods=["GET"])
    def list_assessment_release_orders(aid):
        authenticate()
        authorize(*ALL_READ)
        get_or_404(DB.assessments, aid)
        rows = [o for o in DB.release_orders.values() if o["assessment_id"] == aid]
        return paged_list(rows, release_order_json)

    # =========================================================================
    # CheckIn
    # =========================================================================
    @app.route("/check-ins", methods=["POST"])
    def create_check_in():
        authenticate()
        authorize(SUPER)
        body = json_body()
        defendant_id = req_string(body, "defendant_id")
        get_or_404(DB.defendants, defendant_id)
        due_at = req_datetime(body, "due_at")
        rec = base_record()
        rec.update({
            "defendant_id": defendant_id,
            "due_at": due_at,
            "completed_at": None,
            "origin": "MANUAL",
            "status": "SCHEDULED",
        })
        DB.check_ins[rec["id"]] = rec
        return object_response(check_in_json(rec), 201)

    @app.route("/check-ins/<cid>/transition", methods=["POST"])
    def transition_check_in(cid):
        authenticate()
        role_map = {"COMPLETED": {DEF, SUPER}, "MISSED": {SUPER}}
        rec, to_status = _transition_prelude(DB.check_ins, cid, role_map, {DEF, SUPER})
        if g.role == DEF and rec["defendant_id"] != g.user_id:
            raise ApiError("ERR_UNAUTHORIZED",
                           "Defendants may only act on their own check-in.")
        transitions = {"SCHEDULED": {"COMPLETED": 1, "MISSED": 1}}
        _require_status(to_status, transitions, rec["status"])
        if to_status == "COMPLETED":
            rec["completed_at"] = LOGICAL_CLOCK.now()
            rec["status"] = "COMPLETED"
            touch(rec)
        elif to_status == "MISSED":
            if not (LOGICAL_CLOCK.now() > rec["due_at"]):
                raise ApiError("ERR_PRECONDITION_TIME_NOT_REACHED",
                               "Check-in is not yet past due.")
            rec["status"] = "MISSED"
            touch(rec)
            domain.create_cascade_violation(rec["defendant_id"], "MISSED_CHECK_IN",
                                            "MODERATE", rec["id"])
        return object_response(check_in_json(rec))

    @app.route("/defendants/<did>/check-ins", methods=["GET"])
    def list_defendant_check_ins(did):
        authenticate()
        authorize(INTAKE, SUPER, JUDGE, ADMIN, DEF)
        get_or_404(DB.defendants, did)
        if g.role == DEF and g.user_id != did:
            raise ApiError("ERR_UNAUTHORIZED", "Defendants may only view their own check-ins.")
        f_status = qs("status")
        f_origin = qs("origin")
        rows = [c for c in DB.check_ins.values()
                if c["defendant_id"] == did and matches(c["status"], f_status)
                and matches(c["origin"], f_origin)]
        return paged_list(rows, check_in_json)

    # =========================================================================
    # EMEnrollment
    # =========================================================================
    @app.route("/em-enrollments", methods=["POST"])
    def create_em_enrollment():
        authenticate()
        authorize(SUPER)
        body = json_body()
        defendant_id = req_string(body, "defendant_id")
        get_or_404(DB.defendants, defendant_id)
        device_id = req_string(body, "device_id")
        get_or_404(DB.em_devices, device_id)
        rec = base_record()
        rec.update({
            "defendant_id": defendant_id,
            "device_id": device_id,
            "status": "PENDING",
            "activated_at": None,
        })
        DB.em_enrollments[rec["id"]] = rec
        return object_response(em_enrollment_json(rec), 201)

    @app.route("/em-enrollments/<eid>/transition", methods=["POST"])
    def transition_em_enrollment(eid):
        authenticate()
        role_map = {"ACTIVE": {SUPER}, "SUSPENDED": {SUPER}, "TERMINATED": {SUPER}}
        rec, to_status = _transition_prelude(DB.em_enrollments, eid, role_map, {SUPER})
        transitions = {
            "PENDING": {"ACTIVE": 1},
            "ACTIVE": {"SUSPENDED": 1, "TERMINATED": 1},
            "SUSPENDED": {"ACTIVE": 1, "TERMINATED": 1},
        }
        current = rec["status"]
        _require_status(to_status, transitions, current)
        if to_status == "ACTIVE" and current == "PENDING":
            defendant = DB.defendants.get(rec["defendant_id"])
            if defendant is None or defendant["supervision_status"] != "ACTIVE":
                raise ApiError("ERR_DEFENDANT_NOT_ACTIVE",
                               "Defendant is not in ACTIVE supervision.")
            if not domain.defendant_has_ordered_condition(rec["defendant_id"],
                                                          "GPS_MONITORING"):
                raise ApiError("ERR_CONDITION_NOT_ORDERED",
                               "GPS_MONITORING is not an ordered condition.")
            device = DB.em_devices.get(rec["device_id"])
            if device is None or device["available_units"] < 1:
                raise ApiError("ERR_NO_DEVICE_AVAILABLE",
                               "No device unit available.")
            domain.bump_device_units(device, -1)
            rec["activated_at"] = LOGICAL_CLOCK.now()
            rec["status"] = "ACTIVE"
            touch(rec)
        elif to_status == "ACTIVE" and current == "SUSPENDED":
            rec["status"] = "ACTIVE"
            touch(rec)
        elif to_status == "SUSPENDED":
            rec["status"] = "SUSPENDED"
            touch(rec)
        elif to_status == "TERMINATED":
            device = DB.em_devices.get(rec["device_id"])
            if device is not None:
                domain.bump_device_units(device, 1)
            rec["status"] = "TERMINATED"
            touch(rec)
        return object_response(em_enrollment_json(rec))

    @app.route("/em-enrollments/<eid>", methods=["GET"])
    def get_em_enrollment(eid):
        authenticate()
        authorize(*ALL_READ)
        rec = get_or_404(DB.em_enrollments, eid)
        return object_response(em_enrollment_json(rec))

    @app.route("/defendants/<did>/em-enrollments", methods=["GET"])
    def list_defendant_enrollments(did):
        authenticate()
        authorize(*ALL_READ)
        get_or_404(DB.defendants, did)
        f_status = qs("status")
        rows = [e for e in DB.em_enrollments.values()
                if e["defendant_id"] == did and matches(e["status"], f_status)]
        return paged_list(rows, em_enrollment_json)

    @app.route("/em-enrollments/<eid>/curfew-windows", methods=["POST"])
    def create_curfew_window(eid):
        authenticate()
        authorize(SUPER)
        enrollment = get_or_404(DB.em_enrollments, eid)
        body = json_body()
        day_of_week = req_int(body, "day_of_week", minimum=0, maximum=6)
        start_minute = req_int(body, "start_minute", minimum=0, maximum=1439)
        end_minute = req_int(body, "end_minute", minimum=1, maximum=1440)
        if end_minute <= start_minute:
            bad("end_minute must be strictly greater than start_minute.")
        for w in DB.curfew_windows.values():
            if (w["enrollment_id"] == eid and w["day_of_week"] == day_of_week
                    and start_minute < w["end_minute"]
                    and w["start_minute"] < end_minute):
                raise ApiError("ERR_CURFEW_WINDOW_OVERLAP",
                               "Curfew window overlaps an existing window.")
        expected = req_int(body, "expected_enrollment_version")
        if expected != enrollment["version"]:
            raise ApiError("ERR_STALE_VERSION",
                           "expected_enrollment_version does not match.")
        rec = base_record(versioned=False)
        rec.update({
            "enrollment_id": eid,
            "day_of_week": day_of_week,
            "start_minute": start_minute,
            "end_minute": end_minute,
        })
        DB.curfew_windows[rec["id"]] = rec
        touch(enrollment)
        return object_response(curfew_window_json(rec), 201)

    @app.route("/em-enrollments/<eid>/curfew-windows", methods=["GET"])
    def list_curfew_windows(eid):
        authenticate()
        authorize(*ALL_READ)
        get_or_404(DB.em_enrollments, eid)
        f_dow = qs("day_of_week")
        rows = [w for w in DB.curfew_windows.values()
                if w["enrollment_id"] == eid and matches_int(w["day_of_week"], f_dow)]
        return paged_list(rows, curfew_window_json)

    @app.route("/em-enrollments/<eid>/pings", methods=["POST"])
    def create_ping(eid):
        authenticate()
        authorize(SUPER, ADMIN)
        enrollment = get_or_404(DB.em_enrollments, eid)
        body = json_body()
        pinged_at = req_datetime(body, "pinged_at")
        at_home = req_bool(body, "at_home")
        m = pinged_at.hour * 60 + pinged_at.minute
        d = pinged_at.weekday()  # Monday=0
        in_window = any(
            w["enrollment_id"] == eid and w["day_of_week"] == d
            and w["start_minute"] <= m < w["end_minute"]
            for w in DB.curfew_windows.values())
        is_violation = (at_home is False) and in_window
        rec = base_record(versioned=False)
        rec.update({
            "enrollment_id": eid,
            "pinged_at": pinged_at,
            "at_home": at_home,
            "is_curfew_violation": is_violation,
        })
        DB.location_pings[rec["id"]] = rec
        if is_violation:
            domain.create_cascade_violation(enrollment["defendant_id"], "CURFEW",
                                            "MINOR", rec["id"])
        return object_response(location_ping_json(rec), 201)

    @app.route("/em-enrollments/<eid>/pings", methods=["GET"])
    def list_pings(eid):
        authenticate()
        authorize(*ALL_READ)
        get_or_404(DB.em_enrollments, eid)
        rows = [p for p in DB.location_pings.values() if p["enrollment_id"] == eid]
        return paged_list(rows, location_ping_json)

    # =========================================================================
    # ViolationEvent
    # =========================================================================
    @app.route("/violations", methods=["POST"])
    def create_violation():
        authenticate()
        authorize(SUPER)
        body = json_body()
        defendant_id = req_string(body, "defendant_id")
        get_or_404(DB.defendants, defendant_id)
        violation_type = req_enum(body, "violation_type", VIOLATION_TYPES)
        severity = req_enum(body, "severity", SEVERITIES)
        rec = base_record()
        rec.update({
            "defendant_id": defendant_id,
            "violation_type": violation_type,
            "severity": severity,
            "severity_points": 0,
            "status": "REPORTED",
            "reported_by_user_id": g.user_id,
            "adjudicated_by_user_id": None,
            "adjudicated_at": None,
            "source_ref": None,
        })
        DB.violations[rec["id"]] = rec
        return object_response(violation_json(rec), 201)

    @app.route("/violations/<vid>/transition", methods=["POST"])
    def transition_violation(vid):
        authenticate()
        role_map = {"UNDER_REVIEW": {JUDGE}, "ADJUDICATED_SANCTION": {JUDGE},
                    "ADJUDICATED_DISMISS": {JUDGE}}
        rec, to_status = _transition_prelude(DB.violations, vid, role_map, {JUDGE})
        transitions = {
            "REPORTED": {"UNDER_REVIEW": 1},
            "UNDER_REVIEW": {"ADJUDICATED_SANCTION": 1, "ADJUDICATED_DISMISS": 1},
        }
        _require_status(to_status, transitions, rec["status"])
        if to_status == "UNDER_REVIEW":
            rec["status"] = "UNDER_REVIEW"
            touch(rec)
        else:  # adjudication branches
            if g.user_id == rec["reported_by_user_id"]:
                raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                               "Adjudicator must differ from reporter.")
            rec["adjudicated_by_user_id"] = g.user_id
            rec["adjudicated_at"] = LOGICAL_CLOCK.now()
            if to_status == "ADJUDICATED_SANCTION":
                rec["severity_points"] = domain.SEVERITY_POINTS[rec["severity"]]
                rec["status"] = "ADJUDICATED_SANCTION"
                touch(rec)
                defendant = DB.defendants.get(rec["defendant_id"])
                if defendant is not None:
                    score = domain.recompute_cumulative_score(defendant)
                    domain.escalate_if_needed(defendant, score)
                    touch(defendant)
            else:  # ADJUDICATED_DISMISS
                rec["status"] = "ADJUDICATED_DISMISS"
                touch(rec)
        return object_response(violation_json(rec))

    @app.route("/violations/<vid>", methods=["GET"])
    def get_violation(vid):
        authenticate()
        authorize(*ALL_READ)
        rec = get_or_404(DB.violations, vid)
        return object_response(violation_json(rec))

    @app.route("/defendants/<did>/violations", methods=["GET"])
    def list_defendant_violations(did):
        authenticate()
        authorize(*ALL_READ)
        get_or_404(DB.defendants, did)
        f_status = qs("status")
        f_type = qs("violation_type")
        rows = [v for v in DB.violations.values()
                if v["defendant_id"] == did and matches(v["status"], f_status)
                and matches(v["violation_type"], f_type)]
        return paged_list(rows, violation_json)

    # =========================================================================
    # CourtEvent
    # =========================================================================
    @app.route("/court-events", methods=["POST"])
    def create_court_event():
        authenticate()
        authorize(INTAKE, SUPER)
        body = json_body()
        defendant_id = req_string(body, "defendant_id")
        get_or_404(DB.defendants, defendant_id)
        hearing_at = req_datetime(body, "hearing_at")
        reminder_lead_days = opt_int(body, "reminder_lead_days", default=3, minimum=0)
        reminder_due_at = add_days(hearing_at, -reminder_lead_days)
        rec = base_record()
        rec.update({
            "defendant_id": defendant_id,
            "hearing_at": hearing_at,
            "reminder_lead_days": reminder_lead_days,
            "reminder_due_at": reminder_due_at,
            "status": "SCHEDULED",
        })
        DB.court_events[rec["id"]] = rec
        return object_response(court_event_json(rec), 201)

    @app.route("/court-events/<cid>/transition", methods=["POST"])
    def transition_court_event(cid):
        authenticate()
        role_map = {"APPEARED": {SUPER}, "FTA": {SUPER}, "CONTINUED": {SUPER}}
        rec, to_status = _transition_prelude(DB.court_events, cid, role_map, {SUPER})
        transitions = {"SCHEDULED": {"APPEARED": 1, "FTA": 1, "CONTINUED": 1}}
        _require_status(to_status, transitions, rec["status"])
        if to_status == "FTA":
            deadline = add_hours(rec["hearing_at"], domain.FTA_GRACE_HOURS)
            if not (LOGICAL_CLOCK.now() > deadline):
                raise ApiError("ERR_PRECONDITION_TIME_NOT_REACHED",
                               "FTA grace period has not elapsed.")
            rec["status"] = "FTA"
            touch(rec)
            domain.create_cascade_violation(rec["defendant_id"], "FTA", "MAJOR",
                                            rec["id"])
        else:
            rec["status"] = to_status
            touch(rec)
        return object_response(court_event_json(rec))

    @app.route("/defendants/<did>/court-events", methods=["GET"])
    def list_defendant_court_events(did):
        authenticate()
        authorize(INTAKE, SUPER, JUDGE, ADMIN, DEF)
        get_or_404(DB.defendants, did)
        if g.role == DEF and g.user_id != did:
            raise ApiError("ERR_UNAUTHORIZED", "Defendants may only view their own court events.")
        f_status = qs("status")
        rows = [c for c in DB.court_events.values()
                if c["defendant_id"] == did and matches(c["status"], f_status)]
        return paged_list(rows, court_event_json)

    # =========================================================================
    # DrugTest
    # =========================================================================
    @app.route("/drug-tests", methods=["POST"])
    def create_drug_test():
        authenticate()
        authorize(SUPER)
        body = json_body()
        defendant_id = req_string(body, "defendant_id")
        get_or_404(DB.defendants, defendant_id)
        site_id = req_string(body, "site_id")
        site = get_or_404(DB.testing_sites, site_id)
        if not domain.defendant_has_ordered_condition(defendant_id, "DRUG_TESTING"):
            raise ApiError("ERR_CONDITION_NOT_ORDERED",
                           "DRUG_TESTING is not an ordered condition.")
        test_kind = req_enum(body, "test_kind", TEST_KINDS)
        slot_start = req_datetime(body, "slot_start")
        slot_end = add_minutes(slot_start, domain.TEST_SLOT_MINUTES)
        overlap = 0
        for t in DB.drug_tests.values():
            if (t["site_id"] == site_id and t["status"] in ("SCHEDULED", "COLLECTED")
                    and slot_start < t["slot_end"] and t["slot_start"] < slot_end):
                overlap += 1
        if overlap >= site["slot_capacity"]:
            raise ApiError("ERR_SLOT_CAPACITY_EXCEEDED",
                           "Site slot capacity exceeded for this slot.")
        rec = base_record()
        rec.update({
            "defendant_id": defendant_id,
            "site_id": site_id,
            "test_kind": test_kind,
            "slot_start": slot_start,
            "slot_end": slot_end,
            "status": "SCHEDULED",
            "result_recorded_at": None,
        })
        DB.drug_tests[rec["id"]] = rec
        return object_response(drug_test_json(rec), 201)

    @app.route("/drug-tests/<tid>/transition", methods=["POST"])
    def transition_drug_test(tid):
        authenticate()
        role_map = {"COLLECTED": {SUPER}, "RESULT_POSITIVE": {SUPER},
                    "RESULT_NEGATIVE": {SUPER}, "MISSED": {SUPER}}
        rec, to_status = _transition_prelude(DB.drug_tests, tid, role_map, {SUPER})
        transitions = {
            "SCHEDULED": {"COLLECTED": 1, "MISSED": 1},
            "COLLECTED": {"RESULT_POSITIVE": 1, "RESULT_NEGATIVE": 1},
        }
        _require_status(to_status, transitions, rec["status"])
        if to_status == "COLLECTED":
            rec["status"] = "COLLECTED"
            touch(rec)
        elif to_status == "RESULT_NEGATIVE":
            rec["result_recorded_at"] = LOGICAL_CLOCK.now()
            rec["status"] = "RESULT_NEGATIVE"
            touch(rec)
        elif to_status == "RESULT_POSITIVE":
            rec["result_recorded_at"] = LOGICAL_CLOCK.now()
            rec["status"] = "RESULT_POSITIVE"
            touch(rec)
            domain.create_cascade_violation(rec["defendant_id"], "POSITIVE_TEST",
                                            "MODERATE", rec["id"])
        elif to_status == "MISSED":
            if not (LOGICAL_CLOCK.now() > rec["slot_end"]):
                raise ApiError("ERR_PRECONDITION_TIME_NOT_REACHED",
                               "Test slot has not yet elapsed.")
            rec["status"] = "MISSED"
            touch(rec)
        return object_response(drug_test_json(rec))

    @app.route("/defendants/<did>/drug-tests", methods=["GET"])
    def list_defendant_drug_tests(did):
        authenticate()
        authorize(*ALL_READ)
        get_or_404(DB.defendants, did)
        f_status = qs("status")
        rows = [t for t in DB.drug_tests.values()
                if t["defendant_id"] == did and matches(t["status"], f_status)]
        return paged_list(rows, drug_test_json)
