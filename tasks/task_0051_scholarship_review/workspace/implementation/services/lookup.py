"""Resource resolution helpers — enforce left-to-right path-existence checks (§2.5)."""
import db
from errors import err


def get_scholarship_or_404(scholarship_id: str) -> dict:
    s = db.scholarships.get(scholarship_id)
    if s is None:
        raise err("ERR_NOT_FOUND", f"Scholarship {scholarship_id} not found")
    return s


def get_application_or_404(scholarship_id: str, application_id: str) -> dict:
    # Caller is expected to have validated the parent already.
    a = db.applications.get(application_id)
    if a is None:
        raise err("ERR_NOT_FOUND", f"Application {application_id} not found")
    if a.get("scholarship_id") != scholarship_id:
        raise err("ERR_NOT_FOUND", f"Application {application_id} not under scholarship {scholarship_id}")
    return a


def get_objection_or_404(scholarship_id: str, objection_id: str) -> dict:
    o = db.objections.get(objection_id)
    if o is None:
        raise err("ERR_NOT_FOUND", f"Objection {objection_id} not found")
    # An objection is keyed under an application; verify scholarship via app.
    app = db.applications.get(o.get("application_id"))
    if app is None or app.get("scholarship_id") != scholarship_id:
        raise err("ERR_NOT_FOUND", f"Objection {objection_id} not under scholarship {scholarship_id}")
    return o


def get_plan_or_404(scholarship_id: str, plan_id: str) -> dict:
    p = db.disbursement_plans.get(plan_id)
    if p is None:
        raise err("ERR_NOT_FOUND", f"DisbursementPlan {plan_id} not found")
    if p.get("scholarship_id") != scholarship_id:
        raise err("ERR_NOT_FOUND", f"DisbursementPlan {plan_id} not under scholarship {scholarship_id}")
    return p


def get_reviewer_or_404(reviewer_id: str) -> dict:
    r = db.reviewers.get(reviewer_id)
    if r is None:
        raise err("ERR_NOT_FOUND", f"Reviewer {reviewer_id} not found")
    return r


def check_version(entity: dict, body: dict, *, required: bool = False) -> None:
    """Optimistic concurrency check (§2.4).

    If body contains 'version', compare to entity['version']; mismatch -> ERR_VERSION_MISMATCH.
    """
    if body is None:
        return
    if "version" in body and body["version"] is not None:
        try:
            v = int(body["version"])
        except (TypeError, ValueError):
            raise err("ERR_BAD_REQUEST", "version must be an integer")
        if v != entity.get("version"):
            raise err("ERR_VERSION_MISMATCH", "version does not match current entity version")
    elif required:
        raise err("ERR_BAD_REQUEST", "version is required")
