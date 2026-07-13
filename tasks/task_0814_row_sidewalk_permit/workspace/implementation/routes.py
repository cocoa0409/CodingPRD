from flask import request

import store
import calc
from errors import ApiError
from auth import authenticate, require_role
from envelope import success_object, success_array
from store import touch, serialize, sorted_by_created


# ===========================================================================
# Small request helpers
# ===========================================================================
def get_body():
    body = request.get_json(silent=True)
    return body if isinstance(body, dict) else {}


def paginate(items):
    try:
        limit = int(request.args.get("limit", 10))
    except (TypeError, ValueError):
        limit = 10
    try:
        offset = int(request.args.get("offset", 0))
    except (TypeError, ValueError):
        offset = 0
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    total = len(items)
    page = items[offset:offset + limit]
    return page, limit, offset, total


def require_fields(body, fields):
    for f in fields:
        if body.get(f) is None:
            raise ApiError("ERR_INVALID_REQUEST", 400, "Missing required field: %s" % f)


def require_enum(value, allowed, field):
    if value not in allowed:
        raise ApiError("ERR_INVALID_REQUEST", 400, "Invalid value for %s" % field)


def require_int(body, field):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError("ERR_INVALID_REQUEST", 400, "Field %s must be an integer" % field)


def require_bool(body, field):
    if not isinstance(body.get(field), bool):
        raise ApiError("ERR_INVALID_REQUEST", 400, "Field %s must be a boolean" % field)


def valid_date(s):
    if not isinstance(s, str):
        return False
    try:
        calc.parse_date(s)
        return True
    except (TypeError, ValueError):
        return False


def check_date_range(start, end):
    """Priority-4 date-range check; deferred to ERR_INVALID_REQUEST if unparsable."""
    if not valid_date(start) or not valid_date(end):
        return
    if not (calc.parse_date(end) > calc.parse_date(start)):
        raise ApiError("ERR_INVALID_DATE_RANGE", 422, "end date must be after start date")


# ===========================================================================
# Existence + ownership helpers
# ===========================================================================
def get_permit_or_404(pid):
    p = store.permits.get(pid)
    if p is None:
        raise ApiError("ERR_PERMIT_NOT_FOUND", 404, "Permit not found")
    return p


def get_segment_or_404(sid):
    s = store.street_segments.get(sid)
    if s is None:
        raise ApiError("ERR_SEGMENT_NOT_FOUND", 404, "Street segment not found")
    return s


def get_span_or_404(sid):
    s = store.sidewalk_spans.get(sid)
    if s is None:
        raise ApiError("ERR_SPAN_NOT_FOUND", 404, "Sidewalk span not found")
    return s


def get_closure_or_404(cid):
    c = store.lane_closures.get(cid)
    if c is None:
        raise ApiError("ERR_CLOSURE_NOT_FOUND", 404, "Lane closure not found")
    return c


def get_bond_or_404(bid):
    b = store.bonds.get(bid)
    if b is None:
        raise ApiError("ERR_CLOSURE_NOT_FOUND", 404, "Bond not found")
    return b


def get_tcp_or_404(tid):
    t = store.tcps.get(tid)
    if t is None:
        raise ApiError("ERR_CLOSURE_NOT_FOUND", 404, "Traffic-control plan not found")
    return t


def get_agreement_or_404(aid):
    a = store.encroachment_agreements.get(aid)
    if a is None:
        raise ApiError("ERR_CLOSURE_NOT_FOUND", 404, "Encroachment agreement not found")
    return a


def get_obstruction_or_404(oid):
    o = store.sidewalk_obstructions.get(oid)
    if o is None:
        raise ApiError("ERR_CLOSURE_NOT_FOUND", 404, "Sidewalk obstruction not found")
    return o


def check_owner(permit, uid, role):
    if role == "Applicant" and permit["applicant_id"] != uid:
        raise ApiError("ERR_UNAUTHORIZED", 403, "Applicant does not own this permit")


# ===========================================================================
# Cascade helpers
# ===========================================================================
def permit_lane_closures(pid):
    return [c for c in store.lane_closures.values() if c["permit_id"] == pid]


def permit_obstructions(pid):
    return [o for o in store.sidewalk_obstructions.values() if o["permit_id"] == pid]


def recompute_provisional_refund(permit):
    bond = store.bonds.get(permit.get("bond_id"))
    if bond is None or bond["status"] != "POSTED":
        return
    deficiency = sum(c["estimated_deficiency_cents"]
                     for c in permit_lane_closures(permit["id"])
                     if c["status"] == "RESTORATION_PENDING")
    refund, _ = calc.bond_refund(bond["posted_cents"], deficiency,
                                 permit["cumulative_penalty_cents"])
    bond["provisional_refund_cents"] = refund
    touch(bond)


def revoke_permit(permit):
    permit["status"] = "REVOKED"
    touch(permit)
    voided_non_restored = False
    for closure in permit_lane_closures(permit["id"]):
        if closure["status"] in ("PLANNED", "ACTIVE", "RESTORATION_PENDING"):
            was_counted = closure["status"] in ("ACTIVE", "RESTORATION_PENDING")
            closure["status"] = "VOIDED"
            touch(closure)
            voided_non_restored = True
            if was_counted:
                seg = store.street_segments.get(closure["street_segment_id"])
                if seg is not None and seg["active_lane_closure_count"] > 0:
                    seg["active_lane_closure_count"] -= 1
                    touch(seg)
    for obs in permit_obstructions(permit["id"]):
        if obs["status"] == "ACTIVE":
            obs["status"] = "VOIDED"
            touch(obs)
    if voided_non_restored:
        bond = store.bonds.get(permit.get("bond_id"))
        if bond is not None and bond["status"] == "POSTED":
            bond["forfeited_cents"] = bond["held_cents"]
            bond["held_cents"] = 0
            bond["refunded_cents"] = 0
            bond["status"] = "FORFEITED"
            touch(bond)


def estimated_occupancy_for_permit(permit):
    seg = store.street_segments[permit["street_segment_id"]]
    return calc.occupancy_fee(seg["zone_class"], permit["primary_obstruction_type"],
                              permit["requested_start_date"], permit["requested_end_date"])


# ===========================================================================
# Route registration
# ===========================================================================
def register_routes(app):

    # ------------------------------------------------------------------ Applicant
    @app.route("/applicants", methods=["POST"])
    def create_applicant():
        uid, role = authenticate()
        require_role(role, {"PlatformAdmin"})
        body = get_body()
        require_fields(body, ["company_name", "license_number", "contact_email"])
        rec = store.base_fields()
        rec.update({
            "company_name": body["company_name"],
            "license_number": body["license_number"],
            "contact_email": body["contact_email"],
        })
        store.applicants[rec["id"]] = rec
        return success_object(rec, 201)

    @app.route("/applicants/<aid>", methods=["GET"])
    def get_applicant(aid):
        uid, role = authenticate()
        require_role(role, {"PlatformAdmin", "Applicant"})
        rec = store.applicants.get(aid)
        if rec is None:
            raise ApiError("ERR_APPLICANT_NOT_FOUND", 404, "Applicant not found")
        return success_object(rec, 200)

    # ------------------------------------------------------------ StreetSegment
    @app.route("/street-segments", methods=["POST"])
    def create_segment():
        uid, role = authenticate()
        require_role(role, {"PlatformAdmin"})
        body = get_body()
        require_fields(body, ["block_label", "zone_class", "last_repaved_date",
                              "roadway_lane_count"])
        require_enum(body["zone_class"], calc.ZONE_CLASSES, "zone_class")
        if not valid_date(body["last_repaved_date"]):
            raise ApiError("ERR_INVALID_REQUEST", 400, "last_repaved_date must be YYYY-MM-DD")
        waived = body.get("moratorium_waived", False)
        if not isinstance(waived, bool):
            raise ApiError("ERR_INVALID_REQUEST", 400, "moratorium_waived must be a boolean")
        rec = store.base_fields()
        rec.update({
            "block_label": body["block_label"],
            "zone_class": body["zone_class"],
            "last_repaved_date": body["last_repaved_date"],
            "roadway_lane_count": body["roadway_lane_count"],
            "moratorium_waived": waived,
            "moratorium_end_date": calc.moratorium_end_date(body["last_repaved_date"],
                                                            body["zone_class"]),
            "active_lane_closure_count": 0,
        })
        store.street_segments[rec["id"]] = rec
        return success_object(rec, 201)

    @app.route("/street-segments/<sid>", methods=["GET"])
    def get_segment(sid):
        uid, role = authenticate()
        require_role(role, {"PlatformAdmin", "Applicant", "PermitReviewer"})
        return success_object(get_segment_or_404(sid), 200)

    @app.route("/street-segments/<sid>/lane-closures", methods=["GET"])
    def list_segment_closures(sid):
        uid, role = authenticate()
        require_role(role, {"PlatformAdmin", "Applicant", "PermitReviewer"})
        get_segment_or_404(sid)
        items = sorted_by_created(
            [c for c in store.lane_closures.values() if c["street_segment_id"] == sid])
        page, limit, offset, total = paginate(items)
        return success_array(page, limit, offset, total)

    # ------------------------------------------------------------- SidewalkSpan
    @app.route("/sidewalk-spans", methods=["POST"])
    def create_span():
        uid, role = authenticate()
        require_role(role, {"PlatformAdmin"})
        body = get_body()
        require_fields(body, ["block_label", "side", "width_ft"])
        require_enum(body["side"], {"NORTH", "SOUTH", "EAST", "WEST"}, "side")
        ada = body.get("ada_min_clearance_ft", 4.0)
        rec = store.base_fields()
        rec.update({
            "block_label": body["block_label"],
            "side": body["side"],
            "width_ft": body["width_ft"],
            "ada_min_clearance_ft": ada,
        })
        store.sidewalk_spans[rec["id"]] = rec
        return success_object(rec, 201)

    @app.route("/sidewalk-spans/<sid>", methods=["GET"])
    def get_span(sid):
        uid, role = authenticate()
        require_role(role, {"PlatformAdmin", "Applicant", "PermitReviewer"})
        return success_object(get_span_or_404(sid), 200)

    @app.route("/sidewalk-spans/<sid>/obstructions", methods=["GET"])
    def list_span_obstructions(sid):
        uid, role = authenticate()
        require_role(role, {"PlatformAdmin", "Applicant", "PermitReviewer"})
        get_span_or_404(sid)
        items = sorted_by_created(
            [o for o in store.sidewalk_obstructions.values() if o["sidewalk_span_id"] == sid])
        page, limit, offset, total = paginate(items)
        return success_array(page, limit, offset, total)

    # ------------------------------------------------------------ Permit CRUD
    @app.route("/permits", methods=["POST"])
    def create_permit():
        uid, role = authenticate()
        require_role(role, {"Applicant"})
        body = get_body()
        # Ownership: submitted applicant_id must equal X-User-ID (only when present).
        if body.get("applicant_id") is not None and body["applicant_id"] != uid:
            raise ApiError("ERR_UNAUTHORIZED", 403,
                           "applicant_id must equal the acting applicant")
        # Existence of referenced resources.
        if body.get("applicant_id") is not None and body["applicant_id"] not in store.applicants:
            raise ApiError("ERR_APPLICANT_NOT_FOUND", 404, "Applicant not found")
        if body.get("street_segment_id") is not None \
                and body["street_segment_id"] not in store.street_segments:
            raise ApiError("ERR_SEGMENT_NOT_FOUND", 404, "Street segment not found")
        # Date range.
        check_date_range(body.get("requested_start_date"), body.get("requested_end_date"))
        # Final well-formedness.
        require_fields(body, ["applicant_id", "street_segment_id", "primary_obstruction_type",
                              "requested_start_date", "requested_end_date"])
        require_enum(body["primary_obstruction_type"], {"LANE", "FULL_ROAD", "SIDEWALK"},
                     "primary_obstruction_type")
        if not valid_date(body["requested_start_date"]) or not valid_date(body["requested_end_date"]):
            raise ApiError("ERR_INVALID_REQUEST", 400, "requested dates must be YYYY-MM-DD")
        ruc = body.get("requires_utility_cut", False)
        if not isinstance(ruc, bool):
            raise ApiError("ERR_INVALID_REQUEST", 400, "requires_utility_cut must be a boolean")
        rec = store.base_fields()
        rec.update({
            "applicant_id": body["applicant_id"],
            "street_segment_id": body["street_segment_id"],
            "primary_obstruction_type": body["primary_obstruction_type"],
            "requested_start_date": body["requested_start_date"],
            "requested_end_date": body["requested_end_date"],
            "requires_utility_cut": ruc,
            "status": "DRAFT",
            "assigned_reviewer_user_id": None,
            "actual_start_date": None,
            "actual_end_date": None,
            "estimated_fee_cents": None,
            "final_fee_cents": None,
            "surcharge_cents": None,
            "total_charge_cents": None,
            "cumulative_penalty_cents": 0,
            "valid_until": None,
            "issued_at": None,
            "bond_id": None,
        })
        store.permits[rec["id"]] = rec
        return success_object(rec, 201)

    @app.route("/permits/<pid>", methods=["GET"])
    def get_permit(pid):
        uid, role = authenticate()
        require_role(role, {"Applicant", "PermitReviewer", "Inspector",
                            "EnforcementOfficer", "PlatformAdmin"})
        return success_object(get_permit_or_404(pid), 200)

    @app.route("/permits", methods=["GET"])
    def list_permits():
        uid, role = authenticate()
        require_role(role, {"PlatformAdmin", "PermitReviewer", "Applicant"})
        items = list(store.permits.values())
        f_app = request.args.get("applicant_id")
        f_seg = request.args.get("street_segment_id")
        f_status = request.args.get("status")
        if f_app is not None:
            items = [p for p in items if p["applicant_id"] == f_app]
        if f_seg is not None:
            items = [p for p in items if p["street_segment_id"] == f_seg]
        if f_status is not None:
            items = [p for p in items if p["status"] == f_status]
        items = sorted_by_created(items)
        page, limit, offset, total = paginate(items)
        return success_array(page, limit, offset, total)

    # -------------------------------------------------------- Permit lifecycle
    @app.route("/permits/<pid>/submit", methods=["POST"])
    def submit_permit(pid):
        uid, role = authenticate()
        require_role(role, {"Applicant"})
        permit = get_permit_or_404(pid)
        check_owner(permit, uid, role)
        if permit["status"] not in ("DRAFT", "RETURNED_FOR_REVISION"):
            raise ApiError("ERR_INVALID_PERMIT_STATE", 409, "Permit cannot be submitted")
        permit["status"] = "UNDER_REVIEW"
        touch(permit)
        return success_object(permit, 200)

    @app.route("/permits/<pid>/decision", methods=["POST"])
    def decide_permit(pid):
        uid, role = authenticate()
        require_role(role, {"PermitReviewer"})
        permit = get_permit_or_404(pid)
        if permit["status"] != "UNDER_REVIEW":
            raise ApiError("ERR_INVALID_PERMIT_STATE", 409, "Permit is not under review")
        body = get_body()
        require_fields(body, ["outcome"])
        require_enum(body["outcome"], {"APPROVED", "RETURNED"}, "outcome")
        if body["outcome"] == "APPROVED":
            permit["status"] = "APPROVED"
            permit["assigned_reviewer_user_id"] = uid
        else:
            permit["status"] = "RETURNED_FOR_REVISION"
        touch(permit)
        return success_object(permit, 200)

    @app.route("/permits/<pid>/issue", methods=["POST"])
    def issue_permit(pid):
        uid, role = authenticate()
        require_role(role, {"PermitReviewer"})
        permit = get_permit_or_404(pid)
        # Segregation of duties (authorization phase, per PRD 2.9).
        if permit.get("assigned_reviewer_user_id") is not None \
                and permit["assigned_reviewer_user_id"] == uid:
            raise ApiError("ERR_SEGREGATION_OF_DUTIES", 403,
                           "Issuer must differ from the approving reviewer")
        if permit["status"] != "APPROVED":
            raise ApiError("ERR_INVALID_PERMIT_STATE", 409, "Permit is not approved")
        # Safety gate: an APPROVED traffic-control plan must exist.
        has_approved_tcp = any(t["permit_id"] == pid and t["status"] == "APPROVED"
                               for t in store.tcps.values())
        if not has_approved_tcp:
            raise ApiError("ERR_TCP_NOT_APPROVED", 409,
                           "An approved traffic-control plan is required")
        # Fiscal gate: a POSTED bond with sufficient funds must exist.
        bond = store.bonds.get(permit.get("bond_id"))
        if bond is None or bond["status"] != "POSTED" \
                or bond["posted_cents"] < bond["required_cents"]:
            raise ApiError("ERR_BOND_INSUFFICIENT", 422,
                           "A sufficient posted restoration bond is required")
        # Transition + calculations.
        est = estimated_occupancy_for_permit(permit)
        surcharge, total = calc.surcharge_and_total(est)
        permit["status"] = "ISSUED"
        permit["estimated_fee_cents"] = est
        permit["surcharge_cents"] = surcharge
        permit["total_charge_cents"] = total
        permit["valid_until"] = permit["requested_end_date"]
        permit["issued_at"] = store.clock_iso()
        touch(permit)
        return success_object(permit, 200)

    @app.route("/permits/<pid>/close-out", methods=["POST"])
    def close_out_permit(pid):
        uid, role = authenticate()
        require_role(role, {"PermitReviewer", "Inspector"})
        permit = get_permit_or_404(pid)
        if permit["status"] != "ISSUED":
            raise ApiError("ERR_INVALID_PERMIT_STATE", 409, "Permit is not issued")
        outstanding = any(c["status"] not in ("RESTORED", "VOIDED")
                          for c in permit_lane_closures(pid))
        outstanding = outstanding or any(o["status"] not in ("RESTORED", "VOIDED")
                                         for o in permit_obstructions(pid))
        if outstanding:
            raise ApiError("ERR_CLOSURES_OUTSTANDING", 409,
                           "All occupancy must be terminal before close-out")
        permit["status"] = "CLOSED_OUT"
        permit["actual_end_date"] = store.clock_date_str()
        if permit["actual_start_date"] is None:
            permit["final_fee_cents"] = permit["estimated_fee_cents"]
        else:
            seg = store.street_segments[permit["street_segment_id"]]
            permit["final_fee_cents"] = calc.occupancy_fee(
                seg["zone_class"], permit["primary_obstruction_type"],
                permit["actual_start_date"], permit["actual_end_date"])
        touch(permit)
        return success_object(permit, 200)

    @app.route("/permits/<pid>/expire", methods=["POST"])
    def expire_permit(pid):
        uid, role = authenticate()
        require_role(role, {"PlatformAdmin"})
        permit = get_permit_or_404(pid)
        if permit["status"] != "ISSUED":
            raise ApiError("ERR_INVALID_PERMIT_STATE", 409, "Permit is not issued")
        if not (store.clock_date_str() > permit["valid_until"]):
            raise ApiError("ERR_NOT_YET_EXPIRED", 409, "Permit validity has not lapsed")
        permit["status"] = "EXPIRED"
        touch(permit)
        return success_object(permit, 200)

    # ------------------------------------------------------ TrafficControlPlan
    @app.route("/permits/<pid>/traffic-control-plan", methods=["POST"])
    def create_tcp(pid):
        uid, role = authenticate()
        require_role(role, {"Applicant"})
        permit = get_permit_or_404(pid)
        check_owner(permit, uid, role)
        body = get_body()
        require_fields(body, ["device_list", "requires_flaggers", "setback_ft"])
        require_bool(body, "requires_flaggers")
        rec = store.base_fields()
        rec.update({
            "permit_id": pid,
            "device_list": body["device_list"],
            "requires_flaggers": body["requires_flaggers"],
            "flagger_count": body.get("flagger_count", 0),
            "setback_ft": body["setback_ft"],
            "status": "SUBMITTED",
            "review_notes": None,
        })
        store.tcps[rec["id"]] = rec
        return success_object(rec, 201)

    @app.route("/permits/<pid>/traffic-control-plans", methods=["GET"])
    def list_tcps(pid):
        uid, role = authenticate()
        require_role(role, {"Applicant", "PermitReviewer", "PlatformAdmin"})
        get_permit_or_404(pid)
        items = sorted_by_created([t for t in store.tcps.values() if t["permit_id"] == pid])
        page, limit, offset, total = paginate(items)
        return success_array(page, limit, offset, total)

    @app.route("/traffic-control-plans/<tid>/decision", methods=["POST"])
    def decide_tcp(tid):
        uid, role = authenticate()
        require_role(role, {"PermitReviewer"})
        tcp = get_tcp_or_404(tid)
        if tcp["status"] != "SUBMITTED":
            raise ApiError("ERR_INVALID_STATE", 409, "Plan is not submitted")
        body = get_body()
        require_fields(body, ["outcome"])
        require_enum(body["outcome"], {"APPROVED", "REJECTED"}, "outcome")
        if body["outcome"] == "APPROVED":
            if tcp["requires_flaggers"] and tcp.get("flagger_count", 0) < 1:
                raise ApiError("ERR_FLAGGERS_REQUIRED", 422,
                               "At least one flagger is required")
            tcp["status"] = "APPROVED"
        else:
            tcp["status"] = "REJECTED"
        tcp["review_notes"] = body.get("review_notes")
        touch(tcp)
        return success_object(tcp, 200)

    # ------------------------------------------------------- RestorationBond
    @app.route("/permits/<pid>/bond", methods=["POST"])
    def post_bond(pid):
        uid, role = authenticate()
        require_role(role, {"Applicant"})
        permit = get_permit_or_404(pid)
        check_owner(permit, uid, role)
        body = get_body()
        # OCC check (only when the field is provided).
        ev = body.get("expected_permit_version")
        if ev is not None and ev != permit["version"]:
            raise ApiError("ERR_STALE_PERMIT_VERSION", 412,
                           "expected_permit_version does not match the permit version")
        # Fiscal sufficiency.
        est = estimated_occupancy_for_permit(permit)
        required = calc.bond_required(est)
        posted = body.get("posted_cents")
        if isinstance(posted, int) and not isinstance(posted, bool) and posted < required:
            raise ApiError("ERR_BOND_INSUFFICIENT", 422,
                           "posted_cents is below the required bond amount")
        # Well-formedness.
        require_fields(body, ["posted_cents", "expected_permit_version"])
        require_int(body, "posted_cents")
        require_int(body, "expected_permit_version")
        rec = store.base_fields()
        rec.update({
            "permit_id": pid,
            "posted_cents": posted,
            "required_cents": required,
            "held_cents": posted,
            "refunded_cents": 0,
            "forfeited_cents": 0,
            "provisional_refund_cents": posted,
            "status": "POSTED",
        })
        store.bonds[rec["id"]] = rec
        permit["bond_id"] = rec["id"]
        touch(permit)  # advances permit.version by one
        return success_object(rec, 201)

    @app.route("/permits/<pid>/bond", methods=["GET"])
    def list_bond(pid):
        uid, role = authenticate()
        require_role(role, {"Applicant", "PermitReviewer", "PlatformAdmin"})
        permit = get_permit_or_404(pid)
        bond = store.bonds.get(permit.get("bond_id"))
        items = [bond] if bond is not None else []
        page, limit, offset, total = paginate(items)
        return success_array(page, limit, offset, total)

    @app.route("/bonds/<bid>/release", methods=["POST"])
    def release_bond(bid):
        uid, role = authenticate()
        require_role(role, {"PermitReviewer", "PlatformAdmin"})
        bond = get_bond_or_404(bid)
        if bond["status"] != "POSTED":
            raise ApiError("ERR_INVALID_STATE", 409, "Bond is not posted")
        permit = store.permits[bond["permit_id"]]
        if any(c["status"] not in ("RESTORED", "VOIDED") for c in permit_lane_closures(permit["id"])):
            raise ApiError("ERR_CLOSURES_OUTSTANDING", 409,
                           "All lane closures must be terminal before release")
        deficiency = sum(c["assessed_deficiency_cents"]
                         for c in permit_lane_closures(permit["id"])
                         if c["status"] == "RESTORED")
        refund, forfeit = calc.bond_refund(bond["posted_cents"], deficiency,
                                           permit["cumulative_penalty_cents"])
        bond["refunded_cents"] = refund
        bond["forfeited_cents"] = forfeit
        bond["held_cents"] = 0
        bond["status"] = "RELEASED"
        touch(bond)
        return success_object(bond, 200)

    # ------------------------------------------------------------ LaneClosure
    @app.route("/permits/<pid>/lane-closures", methods=["POST"])
    def create_closure(pid):
        uid, role = authenticate()
        require_role(role, {"Applicant"})
        permit = get_permit_or_404(pid)
        check_owner(permit, uid, role)
        body = get_body()
        seg = None
        if body.get("street_segment_id") is not None:
            seg = get_segment_or_404(body["street_segment_id"])
        check_date_range(body.get("start_date"), body.get("end_date"))
        if permit["status"] != "ISSUED":
            raise ApiError("ERR_PERMIT_NOT_ISSUED", 409, "Parent permit is not issued")
        # Half-open overlap check against PLANNED/ACTIVE closures on the segment.
        if seg is not None and valid_date(body.get("start_date")) and valid_date(body.get("end_date")):
            ns = calc.parse_date(body["start_date"])
            ne = calc.parse_date(body["end_date"])
            for other in store.lane_closures.values():
                if other["street_segment_id"] != seg["id"]:
                    continue
                if other["status"] not in ("PLANNED", "ACTIVE"):
                    continue
                os_ = calc.parse_date(other["start_date"])
                oe = calc.parse_date(other["end_date"])
                if ns < oe and os_ < ne:  # true overlap (adjacency allowed)
                    raise ApiError("ERR_CLOSURE_CONFLICT", 409,
                                   "Lane closure overlaps an existing closure")
            # Utility-cut moratorium.
            ruc = body.get("requires_utility_cut", False)
            if ruc and not seg["moratorium_waived"]:
                if calc.parse_date(body["start_date"]) < calc.parse_date(seg["moratorium_end_date"]):
                    raise ApiError("ERR_UTILITY_CUT_MORATORIUM", 409,
                                   "Utility-cut closure violates the repaving moratorium")
        require_fields(body, ["street_segment_id", "obstruction_type", "start_date", "end_date"])
        require_enum(body["obstruction_type"], {"LANE", "FULL_ROAD"}, "obstruction_type")
        if not valid_date(body["start_date"]) or not valid_date(body["end_date"]):
            raise ApiError("ERR_INVALID_REQUEST", 400, "closure dates must be YYYY-MM-DD")
        ruc = body.get("requires_utility_cut", False)
        if not isinstance(ruc, bool):
            raise ApiError("ERR_INVALID_REQUEST", 400, "requires_utility_cut must be a boolean")
        rec = store.base_fields()
        rec.update({
            "permit_id": pid,
            "street_segment_id": body["street_segment_id"],
            "obstruction_type": body["obstruction_type"],
            "start_date": body["start_date"],
            "end_date": body["end_date"],
            "requires_utility_cut": ruc,
            "estimated_deficiency_cents": 0,
            "assessed_deficiency_cents": 0,
            "inspector_user_id": None,
            "status": "PLANNED",
        })
        store.lane_closures[rec["id"]] = rec
        return success_object(rec, 201)

    @app.route("/permits/<pid>/lane-closures", methods=["GET"])
    def list_closures(pid):
        uid, role = authenticate()
        require_role(role, {"Applicant", "PermitReviewer", "Inspector", "PlatformAdmin"})
        get_permit_or_404(pid)
        items = sorted_by_created(permit_lane_closures(pid))
        page, limit, offset, total = paginate(items)
        return success_array(page, limit, offset, total)

    @app.route("/lane-closures/<cid>/activate", methods=["POST"])
    def activate_closure(cid):
        uid, role = authenticate()
        require_role(role, {"Applicant"})
        closure = get_closure_or_404(cid)
        permit = store.permits[closure["permit_id"]]
        check_owner(permit, uid, role)
        if permit["status"] != "ISSUED":
            raise ApiError("ERR_PERMIT_NOT_ISSUED", 409, "Parent permit is not issued")
        if closure["status"] != "PLANNED":
            raise ApiError("ERR_INVALID_CLOSURE_STATE", 409, "Closure is not planned")
        closure["status"] = "ACTIVE"
        touch(closure)
        seg = store.street_segments.get(closure["street_segment_id"])
        if seg is not None:
            seg["active_lane_closure_count"] += 1
            touch(seg)
        if permit["actual_start_date"] is None:
            permit["actual_start_date"] = store.clock_date_str()
            touch(permit)
        return success_object(closure, 200)

    @app.route("/lane-closures/<cid>/request-restoration", methods=["POST"])
    def request_restoration(cid):
        uid, role = authenticate()
        require_role(role, {"Applicant"})
        closure = get_closure_or_404(cid)
        permit = store.permits[closure["permit_id"]]
        check_owner(permit, uid, role)
        if closure["status"] not in ("ACTIVE", "RESTORATION_REJECTED"):
            raise ApiError("ERR_INVALID_CLOSURE_STATE", 409,
                           "Closure cannot request restoration")
        body = get_body()
        edc = body.get("estimated_deficiency_cents", 0)
        if edc is None:
            edc = 0
        closure["estimated_deficiency_cents"] = edc
        closure["status"] = "RESTORATION_PENDING"
        touch(closure)
        recompute_provisional_refund(permit)
        return success_object(closure, 200)

    @app.route("/lane-closures/<cid>/sign-off", methods=["POST"])
    def sign_off_closure(cid):
        uid, role = authenticate()
        require_role(role, {"Inspector"})
        closure = get_closure_or_404(cid)
        if closure["status"] != "RESTORATION_PENDING":
            raise ApiError("ERR_INVALID_CLOSURE_STATE", 409,
                           "Closure is not pending restoration")
        body = get_body()
        require_fields(body, ["result"])
        require_enum(body["result"], {"PASS", "FAIL"}, "result")
        adc = body.get("assessed_deficiency_cents")
        if adc is not None:
            closure["assessed_deficiency_cents"] = adc
        closure["inspector_user_id"] = uid
        if body["result"] == "PASS":
            closure["status"] = "RESTORED"
            touch(closure)
            seg = store.street_segments.get(closure["street_segment_id"])
            if seg is not None and seg["active_lane_closure_count"] > 0:
                seg["active_lane_closure_count"] -= 1
                touch(seg)
        else:
            closure["status"] = "RESTORATION_REJECTED"
            touch(closure)
        return success_object(closure, 200)

    # ----------------------------------------------------- SidewalkObstruction
    @app.route("/permits/<pid>/sidewalk-obstructions", methods=["POST"])
    def create_obstruction(pid):
        uid, role = authenticate()
        require_role(role, {"Applicant"})
        permit = get_permit_or_404(pid)
        check_owner(permit, uid, role)
        body = get_body()
        span = None
        if body.get("sidewalk_span_id") is not None:
            span = get_span_or_404(body["sidewalk_span_id"])
        check_date_range(body.get("start_date"), body.get("end_date"))
        if permit["status"] != "ISSUED":
            raise ApiError("ERR_PERMIT_NOT_ISSUED", 409, "Parent permit is not issued")
        if span is not None and valid_date(body.get("start_date")) and valid_date(body.get("end_date")):
            ns = calc.parse_date(body["start_date"])
            ne = calc.parse_date(body["end_date"])
            for other in store.sidewalk_obstructions.values():
                if other["sidewalk_span_id"] != span["id"] or other["status"] != "ACTIVE":
                    continue
                os_ = calc.parse_date(other["start_date"])
                oe = calc.parse_date(other["end_date"])
                if ns >= oe:
                    gap = (ns - oe).days
                elif ne <= os_:
                    gap = (os_ - ne).days
                else:
                    gap = -1  # overlapping
                if gap < calc.SIDEWALK_BUFFER_DAYS:
                    raise ApiError("ERR_SIDEWALK_BUFFER_CONFLICT", 409,
                                   "Obstruction violates the 3-day clearance buffer")
            mc = body.get("maintained_clearance_ft")
            if isinstance(mc, (int, float)) and not isinstance(mc, bool) \
                    and mc < span["ada_min_clearance_ft"]:
                raise ApiError("ERR_ADA_CLEARANCE", 422,
                               "maintained_clearance_ft is below the ADA minimum")
        require_fields(body, ["sidewalk_span_id", "start_date", "end_date",
                              "maintained_clearance_ft"])
        if not valid_date(body["start_date"]) or not valid_date(body["end_date"]):
            raise ApiError("ERR_INVALID_REQUEST", 400, "obstruction dates must be YYYY-MM-DD")
        rec = store.base_fields()
        rec.update({
            "permit_id": pid,
            "sidewalk_span_id": body["sidewalk_span_id"],
            "start_date": body["start_date"],
            "end_date": body["end_date"],
            "maintained_clearance_ft": body["maintained_clearance_ft"],
            "status": "ACTIVE",
        })
        store.sidewalk_obstructions[rec["id"]] = rec
        return success_object(rec, 201)

    @app.route("/permits/<pid>/sidewalk-obstructions", methods=["GET"])
    def list_obstructions(pid):
        uid, role = authenticate()
        require_role(role, {"Applicant", "PermitReviewer", "Inspector", "PlatformAdmin"})
        get_permit_or_404(pid)
        items = sorted_by_created(permit_obstructions(pid))
        page, limit, offset, total = paginate(items)
        return success_array(page, limit, offset, total)

    @app.route("/sidewalk-obstructions/<oid>/complete-restoration", methods=["POST"])
    def complete_obstruction(oid):
        uid, role = authenticate()
        require_role(role, {"Applicant", "Inspector"})
        obs = get_obstruction_or_404(oid)
        permit = store.permits[obs["permit_id"]]
        check_owner(permit, uid, role)
        if obs["status"] != "ACTIVE":
            raise ApiError("ERR_INVALID_STATE", 409, "Obstruction is not active")
        obs["status"] = "RESTORED"
        touch(obs)
        return success_object(obs, 200)

    # --------------------------------------------------- EncroachmentAgreement
    @app.route("/permits/<pid>/encroachment-agreement", methods=["POST"])
    def create_agreement(pid):
        uid, role = authenticate()
        require_role(role, {"Applicant"})
        permit = get_permit_or_404(pid)
        check_owner(permit, uid, role)
        body = get_body()
        require_fields(body, ["term_months", "proposed_fee_cents"])
        require_int(body, "term_months")
        require_int(body, "proposed_fee_cents")
        rec = store.base_fields()
        rec.update({
            "permit_id": pid,
            "term_months": body["term_months"],
            "proposed_fee_cents": body["proposed_fee_cents"],
            "agreed_fee_cents": None,
            "status": "PROPOSED",
        })
        store.encroachment_agreements[rec["id"]] = rec
        return success_object(rec, 201)

    @app.route("/permits/<pid>/encroachment-agreements", methods=["GET"])
    def list_agreements(pid):
        uid, role = authenticate()
        require_role(role, {"Applicant", "PermitReviewer", "PlatformAdmin"})
        get_permit_or_404(pid)
        items = sorted_by_created(
            [a for a in store.encroachment_agreements.values() if a["permit_id"] == pid])
        page, limit, offset, total = paginate(items)
        return success_array(page, limit, offset, total)

    @app.route("/encroachment-agreements/<aid>/execute", methods=["POST"])
    def execute_agreement(aid):
        uid, role = authenticate()
        require_role(role, {"PermitReviewer"})
        agreement = get_agreement_or_404(aid)
        permit = store.permits[agreement["permit_id"]]
        if permit["status"] != "ISSUED":
            raise ApiError("ERR_PERMIT_NOT_ISSUED", 409, "Parent permit is not issued")
        if agreement["status"] != "PROPOSED":
            raise ApiError("ERR_INVALID_STATE", 409, "Agreement is not proposed")
        agreement["status"] = "EXECUTED"
        agreement["agreed_fee_cents"] = agreement["proposed_fee_cents"]
        touch(agreement)
        return success_object(agreement, 200)

    # ---------------------------------------------------------- ViolationNotice
    @app.route("/permits/<pid>/violations", methods=["POST"])
    def create_violation(pid):
        uid, role = authenticate()
        require_role(role, {"EnforcementOfficer"})
        permit = get_permit_or_404(pid)
        body = get_body()
        require_fields(body, ["violation_type"])
        require_enum(body["violation_type"],
                     {"UNPERMITTED_WORK", "TCP_VIOLATION", "OVERSTAY", "RESTORATION_FAILURE"},
                     "violation_type")
        prior_count = sum(1 for v in store.violations.values() if v["permit_id"] == pid)
        penalty = calc.penalty_for(prior_count)
        rec = store.immutable_base_fields()
        rec.update({
            "permit_id": pid,
            "violation_type": body["violation_type"],
            "penalty_cents": penalty,
            "note": body.get("note"),
        })
        store.violations[rec["id"]] = rec
        permit["cumulative_penalty_cents"] += penalty
        touch(permit)
        if permit["cumulative_penalty_cents"] >= calc.PENALTY_REVOKE_THRESHOLD_CENTS \
                and permit["status"] == "ISSUED":
            revoke_permit(permit)
        return success_object(rec, 201)

    @app.route("/permits/<pid>/violations", methods=["GET"])
    def list_violations(pid):
        uid, role = authenticate()
        require_role(role, {"PermitReviewer", "EnforcementOfficer", "PlatformAdmin", "Applicant"})
        get_permit_or_404(pid)
        items = sorted_by_created(
            [v for v in store.violations.values() if v["permit_id"] == pid])
        page, limit, offset, total = paginate(items)
        return success_array(page, limit, offset, total)

    # ------------------------------------------------------------- Logical clock
    @app.route("/_clock/set_current_utc", methods=["POST"])
    def set_clock():
        uid, role = authenticate()
        require_role(role, {"PlatformAdmin"})
        body = get_body()
        require_fields(body, ["to_iso8601"])
        try:
            dt = calc.parse_iso_datetime(body["to_iso8601"])
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", 400, "to_iso8601 must be an ISO 8601 instant")
        store.set_clock(dt)
        return success_object({}, 200)
