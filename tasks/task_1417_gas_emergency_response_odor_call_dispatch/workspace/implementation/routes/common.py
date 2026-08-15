"""Shared helpers for routes: existence lookups and read/act scoping rules (PRD §2.1)."""
import db
import domain
from errors import ApiError


def not_found(error_id, what):
    return ApiError(error_id, "%s not found" % what, 404)


def load_territory(tid):
    t = db.territories.get(tid)
    if t is None:
        raise not_found("ERR_TERRITORY_NOT_FOUND", "Territory")
    return t


def load_technician(tid):
    t = db.technicians.get(tid)
    if t is None:
        raise not_found("ERR_TECHNICIAN_NOT_FOUND", "Technician")
    return t


def load_crew(cid):
    c = db.crews.get(cid)
    if c is None:
        raise not_found("ERR_CREW_NOT_FOUND", "Repair crew")
    return c


def load_incident(iid):
    i = db.incidents.get(iid)
    if i is None:
        raise not_found("ERR_INCIDENT_NOT_FOUND", "Incident")
    return i


def load_assignment(aid):
    a = db.assignments.get(aid)
    if a is None:
        raise not_found("ERR_DISPATCH_NOT_FOUND", "Dispatch assignment")
    return a


def load_pause(pid):
    p = db.pauses.get(pid)
    if p is None:
        raise not_found("ERR_PAUSE_NOT_FOUND", "Response-clock pause")
    return p


def load_shutoff(sid):
    s = db.shutoffs.get(sid)
    if s is None:
        raise not_found("ERR_SHUTOFF_NOT_FOUND", "Shutoff order")
    return s


def load_determination(did):
    d = db.determinations.get(did)
    if d is None:
        raise not_found("ERR_DETERMINATION_NOT_FOUND", "Responsibility determination")
    return d


def load_work_order(wid):
    w = db.work_orders.get(wid)
    if w is None:
        raise not_found("ERR_WORK_ORDER_NOT_FOUND", "Repair work order")
    return w


def load_report(rid):
    r = db.reports.get(rid)
    if r is None:
        raise not_found("ERR_REPORT_NOT_FOUND", "Regulatory report")
    return r


def load_notification(nid):
    n = db.notifications.get(nid)
    if n is None:
        raise not_found("ERR_NOTIFICATION_NOT_FOUND", "Public notification")
    return n


# ---------------------------------------------------------------------------
# Read scoping (validation cascade priority 4)
# ---------------------------------------------------------------------------
def check_incident_read_scope(incident, role, user_id):
    """Regulator: only CLOSED/MERGED incidents. FieldTechnician: only incidents where
    it holds or held a dispatch assignment. Others: unrestricted."""
    if role == "Regulator":
        if incident["lifecycle_status"] not in ("CLOSED", "MERGED"):
            raise ApiError("ERR_REGULATOR_SCOPE_RESTRICTED",
                           "Regulator may read only CLOSED or MERGED incidents", 403)
    elif role == "FieldTechnician":
        if not domain.ever_assigned(incident["id"], user_id):
            raise ApiError("ERR_NOT_ASSIGNED_TO_INCIDENT",
                           "Technician has no assignment on this incident", 403)


def incident_visible(incident, role, user_id):
    try:
        check_incident_read_scope(incident, role, user_id)
        return True
    except ApiError:
        return False


def check_technician_active_assignment(incident_id, user_id):
    """Action guard: caller (FieldTechnician) must hold an active assignment on the incident."""
    if domain.active_assignment_on(incident_id, user_id) is None:
        raise ApiError("ERR_NOT_ASSIGNED_TO_INCIDENT",
                       "Technician does not hold an active assignment on this incident", 403)


def check_technician_ever_assigned(incident_id, user_id):
    if not domain.ever_assigned(incident_id, user_id):
        raise ApiError("ERR_NOT_ASSIGNED_TO_INCIDENT",
                       "Technician has no assignment on this incident", 403)


def check_report_read_scope(report, role):
    if role == "Regulator" and report["status"] == "DRAFT":
        raise ApiError("ERR_REGULATOR_SCOPE_RESTRICTED",
                       "Regulator may read only non-DRAFT reports", 403)
