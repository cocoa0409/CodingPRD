"""Routes: clock, registries, measures, cohorts, members, panels, care gaps."""

from datetime import timedelta

import db
import errors as E
import domain as D
import util as U
from errors import ApiError

PA = "ProgramAdministrator"
PM = "PanelManager"
QR = "QualityReviewer"
TC = "TransportationCoordinator"
DRB = "DataReconciliationBot"

ALL_ROLES = [PA, PM, QR, TC, DRB]
READ4 = [PA, PM, QR, DRB]  # read set used by most clinical resources


def _get(store, rid, label="Resource"):
    obj = store.get(rid)
    if obj is None:
        raise ApiError(E.ERR_NOT_FOUND, f"{label} '{rid}' not found", 404)
    return obj


def register_routes(app):

    # ------------------------------------------------------------------ clock
    @app.route("/population-health/_clock/set_current_utc", methods=["POST"])
    def set_clock():
        body = U.get_body()
        registry_id = U.req_str(body, "registry_id")
        to_dt = U.req_dt(body, "to_iso8601")
        _, role = U.authenticate()
        U.authorize(role, [PA])
        registry = _get(db.registries, registry_id, "PopulationRegistry")
        if to_dt < registry["current_business_date"]:
            raise ApiError(
                E.ERR_INVALID_REQUEST,
                "to_iso8601 must not move the registry clock backward",
                400,
            )
        registry["current_business_date"] = to_dt
        D.bump(registry, to_dt)
        D.run_clock_sweeps(registry)
        return U.success_object(D.ser_registry(registry), 200)

    # ------------------------------------------------------------- registries
    @app.route("/population-health/registries", methods=["POST"])
    def create_registry():
        body = U.get_body()
        name = U.req_str(body, "name")
        description = U.opt_str(body, "description")
        program_year = U.req_int(body, "program_year")
        _, role = U.authenticate()
        U.authorize(role, [PA])
        now = D.DEFAULT_CLOCK
        reg = {
            "name": name,
            "description": description,
            "program_year": program_year,
            "current_business_date": now,
            "status": "ACTIVE",
        }
        D.stamp_new(reg, now)
        db.registries[reg["id"]] = reg
        return U.success_object(D.ser_registry(reg), 201)

    @app.route("/population-health/registries", methods=["GET"])
    def list_registries():
        U.authenticate()
        limit, offset = U.pagination_params()
        page, total = U.paginate(list(db.registries.values()), limit, offset)
        return U.success_list([D.ser_registry(r) for r in page], total, limit, offset)

    @app.route("/population-health/registries/<rid>", methods=["GET"])
    def get_registry(rid):
        U.authenticate()
        reg = _get(db.registries, rid, "PopulationRegistry")
        return U.success_object(D.ser_registry(reg), 200)

    # ---------------------------------------------------------------- measures
    @app.route("/population-health/registries/<rid>/measure-definitions", methods=["POST"])
    def create_measure(rid):
        body = U.get_body()
        measure_code = U.req_str(body, "measure_code")
        measure_domain = U.req_enum(body, "measure_domain", {"SCREENING", "MED_ADHERENCE"})
        lookback_days = U.req_int(body, "lookback_days")
        exclusion_window_days = U.opt_int(body, "exclusion_window_days", 90)
        reporting_lag_days = U.opt_int(body, "reporting_lag_days", 30)
        _, role = U.authenticate()
        U.authorize(role, [PA])
        registry = _get(db.registries, rid, "PopulationRegistry")
        if any(
            m["registry_id"] == rid and m["measure_code"] == measure_code
            for m in db.measures.values()
        ):
            raise ApiError(
                E.ERR_INVALID_REQUEST,
                f"measure_code '{measure_code}' already exists in this registry",
                400,
            )
        now = D.clock_of(registry)
        m = {
            "registry_id": rid,
            "measure_code": measure_code,
            "measure_domain": measure_domain,
            "lookback_days": lookback_days,
            "exclusion_window_days": exclusion_window_days,
            "reporting_lag_days": reporting_lag_days,
            "status": "DRAFT",
        }
        D.stamp_new(m, now)
        db.measures[m["id"]] = m
        return U.success_object(D.ser_measure(m), 201)

    @app.route("/population-health/measure-definitions/<mid>/publish", methods=["POST"])
    def publish_measure(mid):
        _, role = U.authenticate()
        U.authorize(role, [PA])
        m = _get(db.measures, mid, "MeasureDefinition")
        if m["status"] != "DRAFT":
            raise ApiError(E.ERR_INVALID_STATE, "Only a DRAFT measure can be published", 409)
        now = D.clock_of(db.registries[m["registry_id"]])
        m["status"] = "PUBLISHED"
        D.bump(m, now)
        return U.success_object(D.ser_measure(m), 200)

    @app.route("/population-health/registries/<rid>/measure-definitions", methods=["GET"])
    def list_measures(rid):
        _, role = U.authenticate()
        U.authorize(role, READ4)
        _get(db.registries, rid, "PopulationRegistry")
        limit, offset = U.pagination_params()
        items = [m for m in db.measures.values() if m["registry_id"] == rid]
        page, total = U.paginate(items, limit, offset)
        return U.success_list([D.ser_measure(m) for m in page], total, limit, offset)

    @app.route("/population-health/measure-definitions/<mid>", methods=["GET"])
    def get_measure(mid):
        _, role = U.authenticate()
        U.authorize(role, READ4)
        m = _get(db.measures, mid, "MeasureDefinition")
        return U.success_object(D.ser_measure(m), 200)

    # ----------------------------------------------------------------- cohorts
    @app.route("/population-health/registries/<rid>/cohort-definitions", methods=["POST"])
    def create_cohort(rid):
        body = U.get_body()
        cohort_code = U.req_str(body, "cohort_code")
        min_age = U.req_int(body, "min_age")
        max_age = U.req_int(body, "max_age")
        risk_tier_filter = U.req_enum(body, "risk_tier_filter", {"ANY", "LOW", "MEDIUM", "HIGH"})
        requires_active_enrollment = U.opt_bool(body, "requires_active_enrollment", True)
        _, role = U.authenticate()
        U.authorize(role, [PA])
        registry = _get(db.registries, rid, "PopulationRegistry")
        if any(
            c["registry_id"] == rid and c["cohort_code"] == cohort_code
            for c in db.cohorts.values()
        ):
            raise ApiError(
                E.ERR_INVALID_REQUEST,
                f"cohort_code '{cohort_code}' already exists in this registry",
                400,
            )
        now = D.clock_of(registry)
        c = {
            "registry_id": rid,
            "cohort_code": cohort_code,
            "min_age": min_age,
            "max_age": max_age,
            "risk_tier_filter": risk_tier_filter,
            "requires_active_enrollment": requires_active_enrollment,
            "status": "DRAFT",
        }
        D.stamp_new(c, now)
        db.cohorts[c["id"]] = c
        return U.success_object(D.ser_cohort(c), 201)

    @app.route("/population-health/cohort-definitions/<cid>/activate", methods=["POST"])
    def activate_cohort(cid):
        _, role = U.authenticate()
        U.authorize(role, [PA])
        c = _get(db.cohorts, cid, "CohortDefinition")
        if c["status"] != "DRAFT":
            raise ApiError(E.ERR_INVALID_STATE, "Only a DRAFT cohort can be activated", 409)
        now = D.clock_of(db.registries[c["registry_id"]])
        c["status"] = "ACTIVE"
        D.bump(c, now)
        return U.success_object(D.ser_cohort(c), 200)

    @app.route("/population-health/registries/<rid>/cohort-definitions", methods=["GET"])
    def list_cohorts(rid):
        _, role = U.authenticate()
        U.authorize(role, READ4)
        _get(db.registries, rid, "PopulationRegistry")
        limit, offset = U.pagination_params()
        items = [c for c in db.cohorts.values() if c["registry_id"] == rid]
        page, total = U.paginate(items, limit, offset)
        return U.success_list([D.ser_cohort(c) for c in page], total, limit, offset)

    # ----------------------------------------------------------------- members
    @app.route("/population-health/registries/<rid>/members", methods=["POST"])
    def create_member(rid):
        body = U.get_body()
        mrn = U.req_str(body, "mrn")
        date_of_birth = U.req_dt(body, "date_of_birth")
        risk_tier = U.req_enum(body, "risk_tier", {"LOW", "MEDIUM", "HIGH"})
        phone_ok = U.opt_bool(body, "phone_ok", True)
        mail_ok = U.opt_bool(body, "mail_ok", True)
        _, role = U.authenticate()
        U.authorize(role, [PA])
        registry = _get(db.registries, rid, "PopulationRegistry")
        if any(m["registry_id"] == rid and m["mrn"] == mrn for m in db.members.values()):
            raise ApiError(
                E.ERR_INVALID_REQUEST,
                f"mrn '{mrn}' already exists in this registry",
                400,
            )
        now = D.clock_of(registry)
        m = {
            "registry_id": rid,
            "mrn": mrn,
            "date_of_birth": date_of_birth,
            "risk_tier": risk_tier,
            "phone_ok": phone_ok,
            "mail_ok": mail_ok,
            "enrollment_status": "ENROLLED",
            "open_gap_count": 0,
        }
        D.stamp_new(m, now)
        db.members[m["id"]] = m
        return U.success_object(D.ser_member(m), 201)

    @app.route("/population-health/registries/<rid>/members", methods=["GET"])
    def list_members(rid):
        _, role = U.authenticate()
        U.authorize(role, ALL_ROLES)
        _get(db.registries, rid, "PopulationRegistry")
        limit, offset = U.pagination_params()
        items = [m for m in db.members.values() if m["registry_id"] == rid]
        items = U.apply_filters(items, [("risk_tier", "risk_tier"), ("enrollment_status", "enrollment_status")])
        page, total = U.paginate(items, limit, offset)
        return U.success_list([D.ser_member(m) for m in page], total, limit, offset)

    @app.route("/population-health/members/<mid>", methods=["GET"])
    def get_member(mid):
        _, role = U.authenticate()
        U.authorize(role, ALL_ROLES)
        m = _get(db.members, mid, "Member")
        return U.success_object(D.ser_member(m), 200)

    @app.route("/population-health/members/<mid>/disenroll", methods=["POST"])
    def disenroll_member(mid):
        U.get_body()
        _, role = U.authenticate()
        U.authorize(role, [PA])
        m = _get(db.members, mid, "Member")
        if m["enrollment_status"] != "ENROLLED":
            raise ApiError(
                E.ERR_INVALID_STATE, "Only an ENROLLED member can be disenrolled", 409
            )
        now = D.clock_of(db.registries[m["registry_id"]])
        m["enrollment_status"] = "DISENROLLED"
        for g in db.care_gaps.values():
            if g["member_id"] == mid and g["status"] in D.EXPIRABLE_STATUSES:
                g["status"] = "EXPIRED"
                D.bump(g, now)
        m["open_gap_count"] = 0
        D.bump(m, now)
        D.recompute_provisional_reports(m["registry_id"])
        return U.success_object(D.ser_member(m), 200)

    # ------------------------------------------------------------------ panels
    @app.route("/population-health/registries/<rid>/registry-panels", methods=["POST"])
    def create_panel(rid):
        body = U.get_body()
        cohort_id = U.req_str(body, "cohort_id")
        measure_id = U.req_str(body, "measure_id")
        panel_manager_id = U.req_str(body, "panel_manager_id")
        _, role = U.authenticate()
        U.authorize(role, [PA])
        registry = _get(db.registries, rid, "PopulationRegistry")
        cohort = db.cohorts.get(cohort_id)
        if cohort is None or cohort["registry_id"] != rid:
            raise ApiError(E.ERR_INVALID_REQUEST, "cohort_id does not reference a cohort in this registry", 400)
        measure = db.measures.get(measure_id)
        if measure is None or measure["registry_id"] != rid:
            raise ApiError(E.ERR_INVALID_REQUEST, "measure_id does not reference a measure in this registry", 400)
        now = D.clock_of(registry)
        p = {
            "registry_id": rid,
            "cohort_id": cohort_id,
            "measure_id": measure_id,
            "panel_manager_id": panel_manager_id,
            "member_count": 0,
            "status": "BUILDING",
        }
        D.stamp_new(p, now)
        db.panels[p["id"]] = p
        return U.success_object(D.ser_panel(p), 201)

    @app.route("/population-health/registry-panels/<pid>/activate", methods=["POST"])
    def activate_panel(pid):
        _, role = U.authenticate()
        U.authorize(role, [PA])
        p = _get(db.panels, pid, "RegistryPanel")
        if p["status"] != "BUILDING":
            raise ApiError(E.ERR_INVALID_STATE, "Only a BUILDING panel can be activated", 409)
        cohort = db.cohorts[p["cohort_id"]]
        measure = db.measures[p["measure_id"]]
        if cohort["status"] != "ACTIVE" or measure["status"] != "PUBLISHED":
            raise ApiError(
                E.ERR_INVALID_STATE,
                "Cohort must be ACTIVE and measure must be PUBLISHED to activate a panel",
                409,
            )
        now = D.clock_of(db.registries[p["registry_id"]])
        D.materialize_panel_gaps(p, now)
        p["status"] = "ACTIVE"
        D.bump(p, now)
        D.refresh_workloads_for_manager(p["registry_id"], p["panel_manager_id"], now)
        return U.success_object(D.ser_panel(p), 200)

    @app.route("/population-health/registry-panels/<pid>/rebuild", methods=["POST"])
    def rebuild_panel(pid):
        body = U.get_body()
        expected = U.req_int(body, "expected_panel_version")
        _, role = U.authenticate()
        U.authorize(role, [PA])
        p = _get(db.panels, pid, "RegistryPanel")
        if p["status"] != "ACTIVE":
            raise ApiError(E.ERR_INVALID_STATE, "Only an ACTIVE panel can be rebuilt", 409)
        if expected != p["version"]:
            raise ApiError(
                E.ERR_STALE_VERSION,
                "expected_panel_version does not match the panel's current version",
                412,
            )
        now = D.clock_of(db.registries[p["registry_id"]])
        p["status"] = "REBUILDING"
        D.materialize_panel_gaps(p, now)
        D.bump(p, now)  # version incremented by exactly one
        return U.success_object(D.ser_panel(p), 200)

    @app.route("/population-health/registry-panels/<pid>/finalize-rebuild", methods=["POST"])
    def finalize_rebuild_panel(pid):
        _, role = U.authenticate()
        U.authorize(role, [PA])
        p = _get(db.panels, pid, "RegistryPanel")
        if p["status"] != "REBUILDING":
            raise ApiError(E.ERR_INVALID_STATE, "Only a REBUILDING panel can be finalized", 409)
        now = D.clock_of(db.registries[p["registry_id"]])
        p["status"] = "ACTIVE"
        D.bump(p, now)
        D.refresh_workloads_for_manager(p["registry_id"], p["panel_manager_id"], now)
        return U.success_object(D.ser_panel(p), 200)

    @app.route("/population-health/registry-panels/<pid>/retire", methods=["POST"])
    def retire_panel(pid):
        _, role = U.authenticate()
        U.authorize(role, [PA])
        p = _get(db.panels, pid, "RegistryPanel")
        if p["status"] not in ("ACTIVE", "REBUILDING"):
            raise ApiError(E.ERR_INVALID_STATE, "Only an ACTIVE or REBUILDING panel can be retired", 409)
        now = D.clock_of(db.registries[p["registry_id"]])
        p["status"] = "RETIRED"
        D.bump(p, now)
        D.refresh_workloads_for_manager(p["registry_id"], p["panel_manager_id"], now)
        return U.success_object(D.ser_panel(p), 200)

    @app.route("/population-health/registries/<rid>/registry-panels", methods=["GET"])
    def list_panels_in_registry(rid):
        _, role = U.authenticate()
        U.authorize(role, READ4)
        _get(db.registries, rid, "PopulationRegistry")
        limit, offset = U.pagination_params()
        items = [p for p in db.panels.values() if p["registry_id"] == rid]
        items = U.apply_filters(items, [("panel_manager_id", "panel_manager_id")])
        page, total = U.paginate(items, limit, offset)
        return U.success_list([D.ser_panel(p) for p in page], total, limit, offset)

    @app.route("/population-health/registry-panels/<pid>", methods=["GET"])
    def get_panel(pid):
        _, role = U.authenticate()
        U.authorize(role, READ4)
        p = _get(db.panels, pid, "RegistryPanel")
        return U.success_object(D.ser_panel(p), 200)

    @app.route("/population-health/registry-panels/<pid>/care-gaps", methods=["GET"])
    def list_panel_gaps(pid):
        _, role = U.authenticate()
        U.authorize(role, READ4)
        _get(db.panels, pid, "RegistryPanel")
        limit, offset = U.pagination_params()
        items = [g for g in db.care_gaps.values() if g["panel_id"] == pid]
        items = U.apply_filters(items, [("status", "status"), ("priority_band", "priority_band")])
        page, total = U.paginate(items, limit, offset)
        return U.success_list([D.ser_gap(g) for g in page], total, limit, offset)

    # --------------------------------------------------------------- care gaps
    @app.route("/population-health/care-gaps/<gid>", methods=["GET"])
    def get_gap(gid):
        _, role = U.authenticate()
        U.authorize(role, READ4)
        g = _get(db.care_gaps, gid, "CareGap")
        return U.success_object(D.ser_gap(g), 200)

    @app.route("/population-health/members/<mid>/care-gaps", methods=["GET"])
    def list_member_gaps(mid):
        _, role = U.authenticate()
        U.authorize(role, READ4)
        _get(db.members, mid, "Member")
        limit, offset = U.pagination_params()
        items = [g for g in db.care_gaps.values() if g["member_id"] == mid]
        items = U.apply_filters(items, [("status", "status")])
        page, total = U.paginate(items, limit, offset)
        return U.success_list([D.ser_gap(g) for g in page], total, limit, offset)

    @app.route("/population-health/care-gaps/<gid>/reopen", methods=["POST"])
    def reopen_gap(gid):
        U.get_body()  # optional reason
        _, role = U.authenticate()
        U.authorize(role, [DRB])
        g = _get(db.care_gaps, gid, "CareGap")
        if g["status"] != "CLOSED" or g["closure_source"] != "CLAIMS_FEED":
            raise ApiError(
                E.ERR_INVALID_STATE,
                "Only a CLOSED gap with closure_source CLAIMS_FEED can be reopened",
                409,
            )
        reg = D.registry_of_gap(g)
        now = D.clock_of(reg)
        measure = db.measures[g["measure_id"]]
        if now >= g["due_date"] + timedelta(days=measure["reporting_lag_days"]):
            raise ApiError(
                E.ERR_RECONCILIATION_WINDOW_CLOSED,
                "The reconciliation window for this care gap has closed",
                409,
            )
        g["status"] = "REOPENED"
        g["closure_source"] = None
        g["_was_reopened"] = True
        D.recompute_gap_priority(g)
        D.bump(g, now)
        D.gap_reopened_cascade(g, now)
        return U.success_object(D.ser_gap(g), 200)
