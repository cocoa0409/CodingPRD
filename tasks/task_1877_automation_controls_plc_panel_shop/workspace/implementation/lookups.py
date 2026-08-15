"""Path-parameter lookups with left-to-right existence and nesting checks."""

from core import err_not_found
from store import db


def get_customer(customer_id):
    c = db.customers.get(customer_id)
    if c is None:
        raise err_not_found("Customer not found.")
    return c


def get_job(job_id):
    j = db.jobs.get(job_id)
    if j is None:
        raise err_not_found("Job not found.")
    return j


def get_panel(panel_id, job_id=None):
    p = db.panels.get(panel_id)
    if p is None or (job_id is not None and p["job_id"] != job_id):
        raise err_not_found("Panel not found.")
    return p


def get_component(component_id):
    c = db.components.get(component_id)
    if c is None:
        raise err_not_found("Component not found.")
    return c


def get_line(line_id, panel_id=None):
    l = db.panel_components.get(line_id)
    if l is None or (panel_id is not None and l["panel_id"] != panel_id):
        raise err_not_found("PanelComponent not found.")
    return l


def get_subreq(sub_id, panel_id=None):
    s = db.substitution_requests.get(sub_id)
    if s is None or (panel_id is not None and s["panel_id"] != panel_id):
        raise err_not_found("SubstitutionRequest not found.")
    return s


def get_testpoint(tp_id, panel_id=None):
    t = db.test_points.get(tp_id)
    if t is None or (panel_id is not None and t["panel_id"] != panel_id):
        raise err_not_found("TestPoint not found.")
    return t


def get_testsession(ts_id, panel_id=None):
    s = db.test_sessions.get(ts_id)
    if s is None or (panel_id is not None and s["panel_id"] != panel_id):
        raise err_not_found("TestSession not found.")
    return s


def get_program_version(pv_id, panel_id=None):
    v = db.program_versions.get(pv_id)
    if v is None or (panel_id is not None and v["panel_id"] != panel_id):
        raise err_not_found("ProgramVersion not found.")
    return v


def get_startup(ss_id, panel_id=None):
    s = db.startup_sessions.get(ss_id)
    if s is None or (panel_id is not None and s["panel_id"] != panel_id):
        raise err_not_found("StartupSession not found.")
    return s


def get_change_order(co_id, job_id=None):
    o = db.change_orders.get(co_id)
    if o is None or (job_id is not None and o["job_id"] != job_id):
        raise err_not_found("ChangeOrder not found.")
    return o


def get_claim(wc_id, job_id=None):
    w = db.warranty_claims.get(wc_id)
    if w is None or (job_id is not None and w["job_id"] != job_id):
        raise err_not_found("WarrantyClaim not found.")
    return w


def get_asbuilt(pkg_id, panel_id=None):
    q = db.as_built_packages.get(pkg_id)
    if q is None or (panel_id is not None and q["panel_id"] != panel_id):
        raise err_not_found("AsBuiltPackage not found.")
    return q


def job_of_panel(panel):
    return db.jobs[panel["job_id"]]


def asbuilt_of_panel(panel_id):
    return next((q for q in db.as_built_packages.values() if q["panel_id"] == panel_id), None)


def sweep_no_show(session=None):
    """NO_SHOW sweep: sessions still SCHEDULED with logical clock past
    scheduled_end auto-transition to NO_SHOW. Evaluated on any read/write of
    the affected session (PRD 2.5)."""
    from core import bump, now_dt

    def _sweep(s):
        if s["status"] == "SCHEDULED" and now_dt() > s["_end_dt"]:
            s["status"] = "NO_SHOW"
            bump(s)

    if session is not None:
        _sweep(session)
    else:
        for s in db.startup_sessions.values():
            _sweep(s)
