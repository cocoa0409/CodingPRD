"""Routes: gap-closure evidence, exclusion requests, workloads, payouts,
performance reports, and flat filtered list endpoints."""

import re
from datetime import timedelta

import db
import errors as E
import domain as D
import util as U
from errors import ApiError
from routes_registry import PA, PM, QR, TC, DRB, ALL_ROLES, READ4, _get

EVIDENCE_TYPES = {"CHART_REVIEW", "CLAIMS_FEED", "MEMBER_ATTESTATION", "LAB_RESULT"}
EXCLUSION_KINDS = {"MEDICAL_CONTRAINDICATION", "MEMBER_REFUSAL", "HOSPICE", "DECEASED"}
PERIOD_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def register_routes(app):

    # ---------------------------------------------------------------- evidence
    @app.route("/population-health/care-gaps/<gid>/gap-closure-evidence", methods=["POST"])
    def submit_evidence(gid):
        body = U.get_body()
        evidence_type = U.req_enum(body, "evidence_type", EVIDENCE_TYPES)
        service_date = U.req_dt(body, "service_date")
        document_uri = U.req_str(body, "document_uri")
        uid, role = U.authenticate()
        U.authorize(role, [PM, QR])
        gap = _get(db.care_gaps, gid, "CareGap")
        if gap["status"] not in ("OPEN", "OUTREACH_IN_PROGRESS"):
            raise ApiError(
                E.ERR_INVALID_STATE,
                "Evidence submission requires the care gap to be OPEN or OUTREACH_IN_PROGRESS",
                409,
            )
        now = D.clock_of(D.registry_of_gap(gap))
        ev = {
            "care_gap_id": gid,
            "member_id": gap["member_id"],
            "evidence_type": evidence_type,
            "service_date": service_date,
            "document_uri": document_uri,
            "submitted_by_role": role,
            "status": "SUBMITTED",
            "_submitted_by_user_id": uid,
            "_auto_from_appointment": False,
        }
        D.stamp_new(ev, now)
        db.evidences[ev["id"]] = ev
        gap["status"] = "PENDING_EVIDENCE"
        D.bump(gap, now)
        return U.success_object(D.ser_evidence(ev), 201)

    @app.route("/population-health/gap-closure-evidence/<eid>/approve", methods=["POST"])
    def approve_evidence(eid):
        U.get_body()  # optional notes
        uid, role = U.authenticate()
        U.authorize(role, [QR])
        ev = _get(db.evidences, eid, "GapClosureEvidence")
        if ev["status"] != "SUBMITTED":
            raise ApiError(
                E.ERR_INVALID_STATE, "Only SUBMITTED evidence can be approved", 409
            )
        # Segregation of duties (priority 16) before the window check (17).
        if uid == ev.get("_submitted_by_user_id"):
            raise ApiError(
                E.ERR_SOD_VIOLATION,
                "The approver must differ from the evidence submitter",
                403,
            )
        gap = db.care_gaps[ev["care_gap_id"]]
        measure = db.measures[gap["measure_id"]]
        now = D.clock_of(D.registry_of_evidence(ev))
        if ev["service_date"] < now - timedelta(days=measure["lookback_days"]):
            raise ApiError(
                E.ERR_EVIDENCE_OUT_OF_WINDOW,
                "service_date is older than the measure's lookback window",
                409,
            )
        ev["status"] = "APPROVED"
        D.bump(ev, now)
        if gap["status"] == "PENDING_EVIDENCE":
            if ev.get("_auto_from_appointment"):
                gap["closure_source"] = "APPOINTMENT_COMPLETED"
            elif ev["evidence_type"] == "CLAIMS_FEED":
                gap["closure_source"] = "CLAIMS_FEED"
            else:
                gap["closure_source"] = "EVIDENCE"
            gap["status"] = "CLOSED"
            gap["_last_closed_at"] = now
            D.bump(gap, now)
            D.gap_closed_cascade(gap, now)
        return U.success_object(D.ser_evidence(ev), 200)

    @app.route("/population-health/gap-closure-evidence/<eid>/reject", methods=["POST"])
    def reject_evidence(eid):
        body = U.get_body()
        U.req_str(body, "rejection_reason")
        uid, role = U.authenticate()
        U.authorize(role, [QR])
        ev = _get(db.evidences, eid, "GapClosureEvidence")
        if ev["status"] != "SUBMITTED":
            raise ApiError(
                E.ERR_INVALID_STATE, "Only SUBMITTED evidence can be rejected", 409
            )
        if uid == ev.get("_submitted_by_user_id"):
            raise ApiError(
                E.ERR_SOD_VIOLATION,
                "The rejector must differ from the evidence submitter",
                403,
            )
        now = D.clock_of(D.registry_of_evidence(ev))
        ev["status"] = "REJECTED"
        D.bump(ev, now)
        gap = db.care_gaps[ev["care_gap_id"]]
        if gap["status"] == "PENDING_EVIDENCE":
            gap["status"] = "OUTREACH_IN_PROGRESS"
            gap["closure_source"] = None
            D.bump(gap, now)
        return U.success_object(D.ser_evidence(ev), 200)

    @app.route("/population-health/care-gaps/<gid>/gap-closure-evidence", methods=["GET"])
    def list_evidence_for_gap(gid):
        _, role = U.authenticate()
        U.authorize(role, READ4)
        _get(db.care_gaps, gid, "CareGap")
        limit, offset = U.pagination_params()
        items = [e for e in db.evidences.values() if e["care_gap_id"] == gid]
        items = U.apply_filters(items, [("status", "status")])
        page, total = U.paginate(items, limit, offset)
        return U.success_list([D.ser_evidence(e) for e in page], total, limit, offset)

    @app.route("/population-health/gap-closure-evidence/<eid>", methods=["GET"])
    def get_evidence(eid):
        _, role = U.authenticate()
        U.authorize(role, READ4)
        ev = _get(db.evidences, eid, "GapClosureEvidence")
        return U.success_object(D.ser_evidence(ev), 200)

    # -------------------------------------------------------------- exclusions
    @app.route("/population-health/members/<mid>/exclusion-requests", methods=["POST"])
    def submit_exclusion(mid):
        body = U.get_body()
        measure_id = U.opt_str(body, "measure_id")
        exclusion_kind = U.req_enum(body, "exclusion_kind", EXCLUSION_KINDS)
        justification = U.req_str(body, "justification")
        effective_from = U.req_dt(body, "effective_from")
        effective_until = U.opt_dt(body, "effective_until")
        if measure_id is not None and measure_id not in db.measures:
            raise ApiError(
                E.ERR_INVALID_REQUEST, "measure_id does not reference a measure", 400
            )
        uid, role = U.authenticate()
        U.authorize(role, [PM, PA])
        member = _get(db.members, mid, "Member")
        if exclusion_kind == "MEDICAL_CONTRAINDICATION" and len(justification) < 20:
            raise ApiError(
                E.ERR_INSUFFICIENT_JUSTIFICATION,
                "MEDICAL_CONTRAINDICATION requires justification of at least 20 characters",
                400,
            )
        now = D.clock_of(D.registry_of_member(member))
        x = {
            "member_id": mid,
            "measure_id": measure_id,
            "exclusion_kind": exclusion_kind,
            "justification": justification,
            "effective_from": effective_from,
            "effective_until": effective_until,
            "status": "SUBMITTED",
            "_submitted_by_user_id": uid,
            "_excluded_gap_ids": [],
            "_approved_at": None,
            "_revoked_at": None,
        }
        D.stamp_new(x, now)
        db.exclusions[x["id"]] = x
        return U.success_object(D.ser_exclusion(x), 201)

    @app.route("/population-health/exclusion-requests/<eid>/start-review", methods=["POST"])
    def start_review_exclusion(eid):
        U.get_body()
        _, role = U.authenticate()
        U.authorize(role, [QR])
        x = _get(db.exclusions, eid, "ExclusionRequest")
        if x["status"] != "SUBMITTED":
            raise ApiError(
                E.ERR_INVALID_STATE, "Only a SUBMITTED exclusion can move to UNDER_REVIEW", 409
            )
        now = D.clock_of(D.registry_of_exclusion(x))
        x["status"] = "UNDER_REVIEW"
        D.bump(x, now)
        return U.success_object(D.ser_exclusion(x), 200)

    @app.route("/population-health/exclusion-requests/<eid>/approve", methods=["POST"])
    def approve_exclusion(eid):
        U.get_body()  # optional notes
        uid, role = U.authenticate()
        U.authorize(role, [QR])
        x = _get(db.exclusions, eid, "ExclusionRequest")
        if x["status"] != "UNDER_REVIEW":
            raise ApiError(
                E.ERR_INVALID_STATE, "Only an UNDER_REVIEW exclusion can be approved", 409
            )
        if uid == x.get("_submitted_by_user_id"):
            raise ApiError(
                E.ERR_SOD_VIOLATION,
                "The approver must differ from the exclusion submitter",
                403,
            )
        # The member must have no active appointment for the measure in question.
        member_id = x["member_id"]
        for a in db.appointments.values():
            if a["status"] not in ("SCHEDULED", "CONFIRMED"):
                continue
            gap = db.care_gaps.get(a["care_gap_id"])
            if gap is None or gap["member_id"] != member_id:
                continue
            if x["measure_id"] is None or gap["measure_id"] == x["measure_id"]:
                raise ApiError(
                    E.ERR_EXCLUSION_BLOCKED_BY_APPOINTMENT,
                    "The member has a SCHEDULED or CONFIRMED appointment for this measure",
                    409,
                )
        now = D.clock_of(D.registry_of_exclusion(x))
        member = db.members[member_id]
        x["status"] = "APPROVED"
        x["_approved_at"] = now
        transitioned = 0
        for g in db.care_gaps.values():
            if g["member_id"] != member_id:
                continue
            if x["measure_id"] is not None and g["measure_id"] != x["measure_id"]:
                continue
            if g["status"] in ("OPEN", "OUTREACH_IN_PROGRESS"):
                g["status"] = "EXCLUDED"
                D.bump(g, now)
                x["_excluded_gap_ids"].append(g["id"])
                D.cancel_active_appointments_for_gap(g, now)
                transitioned += 1
        member["open_gap_count"] = max(0, member["open_gap_count"] - transitioned)
        D.bump(member, now)
        D.bump(x, now)
        affected_measures = (
            {x["measure_id"]}
            if x["measure_id"] is not None
            else {g["measure_id"] for g in db.care_gaps.values() if g["member_id"] == member_id}
        )
        D.recompute_provisional_reports(member["registry_id"], affected_measures or None)
        return U.success_object(D.ser_exclusion(x), 200)

    @app.route("/population-health/exclusion-requests/<eid>/deny", methods=["POST"])
    def deny_exclusion(eid):
        body = U.get_body()
        U.req_str(body, "rejection_reason")
        uid, role = U.authenticate()
        U.authorize(role, [QR])
        x = _get(db.exclusions, eid, "ExclusionRequest")
        if x["status"] != "UNDER_REVIEW":
            raise ApiError(
                E.ERR_INVALID_STATE, "Only an UNDER_REVIEW exclusion can be denied", 409
            )
        if uid == x.get("_submitted_by_user_id"):
            raise ApiError(
                E.ERR_SOD_VIOLATION,
                "The denier must differ from the exclusion submitter",
                403,
            )
        now = D.clock_of(D.registry_of_exclusion(x))
        x["status"] = "DENIED"
        D.bump(x, now)
        return U.success_object(D.ser_exclusion(x), 200)

    @app.route("/population-health/exclusion-requests/<eid>/revoke", methods=["POST"])
    def revoke_exclusion(eid):
        U.get_body()  # optional reason
        uid, role = U.authenticate()
        U.authorize(role, [QR])
        x = _get(db.exclusions, eid, "ExclusionRequest")
        if x["status"] != "APPROVED":
            raise ApiError(
                E.ERR_INVALID_STATE, "Only an APPROVED exclusion can be revoked", 409
            )
        now = D.clock_of(D.registry_of_exclusion(x))
        member = db.members[x["member_id"]]
        x["status"] = "REVOKED"
        x["_revoked_at"] = now
        restored = 0
        for gid in x["_excluded_gap_ids"]:
            g = db.care_gaps.get(gid)
            if g is not None and g["status"] == "EXCLUDED":
                g["status"] = "OPEN"
                D.recompute_gap_priority(g)
                D.bump(g, now)
                restored += 1
        member["open_gap_count"] += restored
        D.bump(member, now)
        D.bump(x, now)
        affected_measures = (
            {x["measure_id"]}
            if x["measure_id"] is not None
            else {g["measure_id"] for g in db.care_gaps.values() if g["member_id"] == member["id"]}
        )
        D.recompute_provisional_reports(member["registry_id"], affected_measures or None)
        return U.success_object(D.ser_exclusion(x), 200)

    @app.route("/population-health/members/<mid>/exclusion-requests", methods=["GET"])
    def list_exclusions_for_member(mid):
        _, role = U.authenticate()
        U.authorize(role, [PA, PM, QR])
        _get(db.members, mid, "Member")
        limit, offset = U.pagination_params()
        items = [x for x in db.exclusions.values() if x["member_id"] == mid]
        items = U.apply_filters(items, [("status", "status")])
        page, total = U.paginate(items, limit, offset)
        return U.success_list([D.ser_exclusion(x) for x in page], total, limit, offset)

    @app.route("/population-health/exclusion-requests/<eid>", methods=["GET"])
    def get_exclusion(eid):
        _, role = U.authenticate()
        U.authorize(role, [PA, PM, QR])
        x = _get(db.exclusions, eid, "ExclusionRequest")
        return U.success_object(D.ser_exclusion(x), 200)

    # ---------------------------------------------------------------- workloads
    @app.route("/population-health/registries/<rid>/panel-manager-workloads", methods=["POST"])
    def create_workload(rid):
        body = U.get_body()
        panel_manager_id = U.req_str(body, "panel_manager_id")
        period_key = U.req_str(body, "period_key")
        if not PERIOD_RE.match(period_key):
            raise ApiError(
                E.ERR_INVALID_REQUEST, "period_key must be in YYYY-MM form", 400
            )
        _, role = U.authenticate()
        U.authorize(role, [PA])
        registry = _get(db.registries, rid, "PopulationRegistry")
        now = D.clock_of(registry)
        w = {
            "registry_id": rid,
            "panel_manager_id": panel_manager_id,
            "assigned_member_count": 0,
            "closed_gap_count_period": 0,
            "utilization_ratio": 0.0,
            "period_key": period_key,
        }
        D.stamp_new(w, now)
        db.workloads[w["id"]] = w
        # Initialize from the current panel assignments, then re-stamp so the
        # initialization itself does not consume a version bump.
        total = sum(
            p["member_count"]
            for p in db.panels.values()
            if p["registry_id"] == rid
            and p["panel_manager_id"] == panel_manager_id
            and p["status"] == "ACTIVE"
        )
        w["assigned_member_count"] = total
        w["utilization_ratio"] = float(D._utilization_decimal(total))
        return U.success_object(D.ser_workload(w), 201)

    @app.route("/population-health/registries/<rid>/panel-manager-workloads", methods=["GET"])
    def list_workloads(rid):
        _, role = U.authenticate()
        U.authorize(role, [PA, PM])
        _get(db.registries, rid, "PopulationRegistry")
        limit, offset = U.pagination_params()
        items = [w for w in db.workloads.values() if w["registry_id"] == rid]
        items = U.apply_filters(
            items, [("panel_manager_id", "panel_manager_id"), ("period_key", "period_key")]
        )
        page, total = U.paginate(items, limit, offset)
        return U.success_list([D.ser_workload(w) for w in page], total, limit, offset)

    @app.route("/population-health/panel-manager-workloads/<wid>", methods=["GET"])
    def get_workload(wid):
        _, role = U.authenticate()
        U.authorize(role, [PA, PM])
        w = _get(db.workloads, wid, "PanelManagerWorkload")
        return U.success_object(D.ser_workload(w), 200)

    # ------------------------------------------------------------------ payouts
    @app.route("/population-health/panel-manager-workloads/<wid>/incentive-payouts", methods=["GET"])
    def list_payouts_for_workload(wid):
        _, role = U.authenticate()
        U.authorize(role, [PA, PM])
        _get(db.workloads, wid, "PanelManagerWorkload")
        limit, offset = U.pagination_params()
        items = [p for p in db.payouts.values() if p["workload_id"] == wid]
        page, total = U.paginate(items, limit, offset)
        return U.success_list([D.ser_payout(p) for p in page], total, limit, offset)

    @app.route(
        "/population-health/panel-manager-workloads/<wid>/incentive-payouts/projection",
        methods=["POST"],
    )
    def project_payout(wid):
        U.get_body()
        _, role = U.authenticate()
        U.authorize(role, [PA])
        w = _get(db.workloads, wid, "PanelManagerWorkload")
        now = D.clock_of(db.registries[w["registry_id"]])
        amounts = D.compute_payout_amounts(w)
        existing = next(
            (
                p
                for p in db.payouts.values()
                if p["workload_id"] == wid and p["status"] == "PROJECTED"
            ),
            None,
        )
        if existing is not None:
            existing.update(amounts)
            D.bump(existing, now)
            return U.success_object(D.ser_payout(existing), 201)
        p = {
            "workload_id": wid,
            "panel_manager_id": w["panel_manager_id"],
            "period_key": w["period_key"],
            "status": "PROJECTED",
        }
        p.update(amounts)
        D.stamp_new(p, now)
        db.payouts[p["id"]] = p
        return U.success_object(D.ser_payout(p), 201)

    @app.route("/population-health/incentive-payouts/<pid>/approve", methods=["POST"])
    def approve_payout(pid):
        U.get_body()
        _, role = U.authenticate()
        U.authorize(role, [PA])
        p = _get(db.payouts, pid, "IncentivePayout")
        if p["status"] != "PROJECTED":
            raise ApiError(
                E.ERR_INVALID_STATE, "Only a PROJECTED payout can be approved", 409
            )
        now = D.clock_of(D.registry_of_payout(p))
        p["status"] = "APPROVED"
        D.bump(p, now)
        return U.success_object(D.ser_payout(p), 200)

    @app.route("/population-health/incentive-payouts/<pid>", methods=["GET"])
    def get_payout(pid):
        _, role = U.authenticate()
        U.authorize(role, [PA, PM])
        p = _get(db.payouts, pid, "IncentivePayout")
        return U.success_object(D.ser_payout(p), 200)

    # ------------------------------------------------------------------ reports
    @app.route(
        "/population-health/measure-definitions/<mid>/measure-performance-reports",
        methods=["POST"],
    )
    def create_report(mid):
        body = U.get_body()
        period_key = U.req_str(body, "period_key")
        if not PERIOD_RE.match(period_key):
            raise ApiError(
                E.ERR_INVALID_REQUEST, "period_key must be in YYYY-MM form", 400
            )
        _, role = U.authenticate()
        U.authorize(role, [PA])
        measure = _get(db.measures, mid, "MeasureDefinition")
        now = D.clock_of(db.registries[measure["registry_id"]])
        r = {
            "measure_id": mid,
            "registry_id": measure["registry_id"],
            "period_key": period_key,
            "denominator_count": 0,
            "numerator_count": 0,
            "closure_rate_bps": None,
            "variant": "PROVISIONAL",
            "reconciled_at": None,
        }
        D.stamp_new(r, now)
        D.recompute_report(r, "PROVISIONAL")
        db.reports[r["id"]] = r
        return U.success_object(D.ser_report(r), 201)

    @app.route(
        "/population-health/measure-performance-reports/<rid>/finalize", methods=["POST"]
    )
    def finalize_report(rid):
        U.get_body()
        _, role = U.authenticate()
        U.authorize(role, [PA])
        r = _get(db.reports, rid, "MeasurePerformanceReport")
        if r["variant"] != "PROVISIONAL":
            raise ApiError(
                E.ERR_INVALID_STATE, "Only a PROVISIONAL report can be finalized", 409
            )
        measure = db.measures[r["measure_id"]]
        registry = db.registries[r["registry_id"]]
        now = D.clock_of(registry)
        _, pend = D.period_window(r["period_key"])
        if now < pend + timedelta(days=measure["reporting_lag_days"]):
            raise ApiError(
                E.ERR_RECONCILIATION_WINDOW_OPEN,
                "The reporting lag has not yet elapsed for this period",
                409,
            )
        r["variant"] = "FINAL"
        r["reconciled_at"] = now
        D.recompute_report(r, "FINAL")
        D.bump(r, now)
        return U.success_object(D.ser_report(r), 200)

    @app.route(
        "/population-health/measure-definitions/<mid>/measure-performance-reports",
        methods=["GET"],
    )
    def list_reports_for_measure(mid):
        _, role = U.authenticate()
        U.authorize(role, READ4)
        _get(db.measures, mid, "MeasureDefinition")
        limit, offset = U.pagination_params()
        items = [r for r in db.reports.values() if r["measure_id"] == mid]
        items = U.apply_filters(
            items, [("period_key", "period_key"), ("variant", "variant")]
        )
        page, total = U.paginate(items, limit, offset)
        return U.success_list([D.ser_report(r) for r in page], total, limit, offset)

    @app.route("/population-health/measure-performance-reports/<rid>", methods=["GET"])
    def get_report(rid):
        _, role = U.authenticate()
        U.authorize(role, READ4)
        r = _get(db.reports, rid, "MeasurePerformanceReport")
        return U.success_object(D.ser_report(r), 200)

    # ------------------------------------------------- flat filtered list APIs
    @app.route("/population-health/registry-panels", methods=["GET"])
    def list_panels_flat():
        _, role = U.authenticate()
        U.authorize(role, READ4)
        limit, offset = U.pagination_params()
        items = U.apply_filters(
            list(db.panels.values()),
            [
                ("cohort_id", "cohort_id"),
                ("measure_id", "measure_id"),
                ("panel_manager_id", "panel_manager_id"),
            ],
        )
        page, total = U.paginate(items, limit, offset)
        return U.success_list([D.ser_panel(p) for p in page], total, limit, offset)

    @app.route("/population-health/care-gaps", methods=["GET"])
    def list_gaps_flat():
        _, role = U.authenticate()
        U.authorize(role, READ4)
        limit, offset = U.pagination_params()
        items = U.apply_filters(
            list(db.care_gaps.values()),
            [
                ("panel_id", "panel_id"),
                ("member_id", "member_id"),
                ("measure_id", "measure_id"),
                ("status", "status"),
                ("priority_band", "priority_band"),
            ],
        )
        page, total = U.paginate(items, limit, offset)
        return U.success_list([D.ser_gap(g) for g in page], total, limit, offset)

    @app.route("/population-health/outreach-campaigns", methods=["GET"])
    def list_campaigns_flat():
        _, role = U.authenticate()
        U.authorize(role, READ4)
        limit, offset = U.pagination_params()
        items = U.apply_filters(
            list(db.campaigns.values()),
            [("panel_id", "panel_id"), ("measure_id", "measure_id"), ("status", "status")],
        )
        page, total = U.paginate(items, limit, offset)
        return U.success_list([D.ser_campaign(c) for c in page], total, limit, offset)

    @app.route("/population-health/outreach-attempts", methods=["GET"])
    def list_attempts_flat():
        _, role = U.authenticate()
        U.authorize(role, READ4)
        limit, offset = U.pagination_params()
        items = U.apply_filters(
            list(db.attempts.values()),
            [
                ("care_gap_id", "care_gap_id"),
                ("campaign_id", "campaign_id"),
                ("member_id", "member_id"),
            ],
        )
        page, total = U.paginate(items, limit, offset)
        return U.success_list([D.ser_attempt(a) for a in page], total, limit, offset)

    @app.route("/population-health/outreach-attempts/<aid>", methods=["GET"])
    def get_attempt(aid):
        _, role = U.authenticate()
        U.authorize(role, READ4)
        a = _get(db.attempts, aid, "OutreachAttempt")
        return U.success_object(D.ser_attempt(a), 200)

    @app.route("/population-health/appointments", methods=["GET"])
    def list_appointments_flat():
        _, role = U.authenticate()
        U.authorize(role, ALL_ROLES)
        limit, offset = U.pagination_params()
        items = U.apply_filters(
            list(db.appointments.values()),
            [
                ("care_gap_id", "care_gap_id"),
                ("member_id", "member_id"),
                ("provider_id", "provider_id"),
                ("status", "status"),
            ],
        )
        page, total = U.paginate(items, limit, offset)
        return U.success_list([D.ser_appointment(a) for a in page], total, limit, offset)

    @app.route("/population-health/transportation-assists", methods=["GET"])
    def list_transports_flat():
        _, role = U.authenticate()
        U.authorize(role, [PA, PM, TC, QR])
        limit, offset = U.pagination_params()
        items = U.apply_filters(
            list(db.transports.values()),
            [
                ("appointment_id", "appointment_id"),
                ("member_id", "member_id"),
                ("status", "status"),
            ],
        )
        page, total = U.paginate(items, limit, offset)
        return U.success_list([D.ser_transport(t) for t in page], total, limit, offset)

    @app.route("/population-health/gap-closure-evidence", methods=["GET"])
    def list_evidence_flat():
        _, role = U.authenticate()
        U.authorize(role, READ4)
        limit, offset = U.pagination_params()
        items = U.apply_filters(
            list(db.evidences.values()),
            [
                ("care_gap_id", "care_gap_id"),
                ("member_id", "member_id"),
                ("status", "status"),
            ],
        )
        page, total = U.paginate(items, limit, offset)
        return U.success_list([D.ser_evidence(e) for e in page], total, limit, offset)

    @app.route("/population-health/exclusion-requests", methods=["GET"])
    def list_exclusions_flat():
        _, role = U.authenticate()
        U.authorize(role, [PA, PM, QR])
        limit, offset = U.pagination_params()
        items = U.apply_filters(
            list(db.exclusions.values()),
            [
                ("member_id", "member_id"),
                ("measure_id", "measure_id"),
                ("status", "status"),
            ],
        )
        page, total = U.paginate(items, limit, offset)
        return U.success_list([D.ser_exclusion(x) for x in page], total, limit, offset)

    @app.route("/population-health/measure-performance-reports", methods=["GET"])
    def list_reports_flat():
        _, role = U.authenticate()
        U.authorize(role, READ4)
        limit, offset = U.pagination_params()
        items = U.apply_filters(
            list(db.reports.values()),
            [
                ("measure_id", "measure_id"),
                ("registry_id", "registry_id"),
                ("period_key", "period_key"),
                ("variant", "variant"),
            ],
        )
        page, total = U.paginate(items, limit, offset)
        return U.success_list([D.ser_report(r) for r in page], total, limit, offset)
