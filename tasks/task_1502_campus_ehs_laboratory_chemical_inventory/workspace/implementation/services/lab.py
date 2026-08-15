"""Lab lifecycle: create, closeout, decommission (PRD §3.1, §3.8)."""
import db
from errors import ApiError, ERR_LAB_STATE, ERR_DECOMMISSION_BLOCKED, forbidden_ownership
from services.common import touch, refresh_posture


def create_lab(body):
    from services.common import require_fields, require_string
    require_fields(body, ["name", "department", "building", "room"])
    lab = {
        "id": db.new_id(),
        "name": require_string(body, "name"),
        "department": require_string(body, "department"),
        "building": require_string(body, "building"),
        "room": require_string(body, "room"),
        "pi_worker_id": None,
        "status": "ACTIVE",
        "posture": "NORMAL",
        "created_at": db.now(),
        "updated_at": db.now(),
        "version": 1,
        "_seq": db.next_seq(),
    }
    db.labs[lab["id"]] = lab
    return lab


def closeout(lab, user_id, role):
    """ACTIVE -> CLOSING; cancels SCHEDULED inspections; posture recompute."""
    if role == "PrincipalInvestigator" and user_id != lab["pi_worker_id"]:
        raise forbidden_ownership("PrincipalInvestigator may only close out their own lab")
    if lab["status"] != "ACTIVE":
        raise ApiError(ERR_LAB_STATE, "Lab must be ACTIVE to initiate closeout", 409)
    lab["status"] = "CLOSING"
    touch(lab)
    for insp in db.inspections.values():
        if insp["lab_id"] == lab["id"] and insp["status"] == "SCHEDULED":
            insp["status"] = "CANCELLED"
            touch(insp)
    refresh_posture(lab)
    return lab


def decommission(lab):
    """CLOSING -> DECOMMISSIONED with five aggregate cleanliness checks."""
    if lab["status"] != "CLOSING":
        raise ApiError(ERR_LAB_STATE, "Lab must be CLOSING to decommission", 409)
    lab_id = lab["id"]
    if any(c["lab_id"] == lab_id and c["state"] != "PICKED_UP"
           for c in db.containers.values()):
        raise ApiError(ERR_DECOMMISSION_BLOCKED,
                       "Lab has containers not yet PICKED_UP", 409)
    if any(r["lab_id"] == lab_id and r["status"] in ("DRAFT", "SUBMITTED", "REJECTED", "SCHEDULED")
           for r in db.waste_pickup_requests.values()):
        raise ApiError(ERR_DECOMMISSION_BLOCKED,
                       "Lab has open waste pickup requests", 409)
    if any(ca["lab_id"] == lab_id and ca["status"] in ("OPEN", "SUBMITTED", "REOPENED")
           for ca in db.corrective_actions.values()):
        raise ApiError(ERR_DECOMMISSION_BLOCKED,
                       "Lab has open corrective actions", 409)
    if any(r["lab_id"] == lab_id and r["status"] in ("PENDING", "ACTIVE", "SUSPENDED")
           for r in db.registrations.values()):
        raise ApiError(ERR_DECOMMISSION_BLOCKED,
                       "Lab has open registrations", 409)
    if any(i["lab_id"] == lab_id and i["status"] == "REPORTED"
           for i in db.incidents.values()):
        raise ApiError(ERR_DECOMMISSION_BLOCKED,
                       "Lab has open incidents", 409)
    lab["status"] = "DECOMMISSIONED"
    touch(lab)
    refresh_posture(lab)  # derivation rule 1 -> FROZEN
    return lab
