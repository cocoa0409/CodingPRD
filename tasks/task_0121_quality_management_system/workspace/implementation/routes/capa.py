"""CAPA routes: open, steps, transition state machine (PRD 3.4)."""
from flask import Blueprint, request

from common import (require_enum, require_fields, require_non_negative_int,
                    require_string, stamp_create, touch)
from db import db
from errors import (ERR_EFFECTIVENESS_TOO_LOW, ERR_FK_NOT_FOUND,
                    ERR_INVALID_REQUEST, ERR_INVALID_STATE,
                    ERR_SEGREGATION_OF_DUTIES, err)
from middleware import (ROLE_QUALITY_ENGINEER, ROLE_QUALITY_MANAGER,
                        authenticate, require_role)
from response import list_success, success
from services.calculations import final_effectiveness, provisional_effectiveness
from services.helpers import (get_or_404, paginate, paginate_args,
                              recompute_supplier_rating)
from services.serializers import capa_out, eightd_step_out

bp = Blueprint("capa", __name__)

DISCIPLINES = {"D1", "D2", "D3", "D4", "D5", "D6", "D7", "D8"}
CAPA_ACTIONS = {"ADVANCE", "REJECT_VERIFICATION", "VERIFY",
                "CLOSE_EFFECTIVE", "CLOSE_INEFFECTIVE"}

from decimal import Decimal


@bp.route("/capas", methods=["POST"])
def create_capa():
    auth = authenticate()
    require_role(auth, {ROLE_QUALITY_ENGINEER})
    body = request.get_json(silent=True) or {}

    # FK resolution (priority 4).
    ncr_id = body.get("ncr_id")
    if ncr_id is not None and ncr_id not in db.nonconformance_reports:
        raise err(ERR_FK_NOT_FOUND, "ncr_id does not resolve")

    # Well-formedness (priority 5).
    require_fields(body, ["ncr_id", "title"])
    require_string(body["title"], "title")

    ncr = db.nonconformance_reports[ncr_id]
    # State precondition: NCR must be DISPOSITIONED (PRD 3.4).
    if ncr["status"] != "DISPOSITIONED":
        raise err(ERR_INVALID_STATE, "NCR is not DISPOSITIONED")

    rec = {
        "ncr_id": ncr_id,
        "title": body["title"],
        "current_step": "D1",
        "status": "OPEN",
        "rework_loops": 0,
        "provisional_effectiveness": None,
        "final_effectiveness": None,
        "authored_by_personnel_id": auth.user_id,
        "verified_by_personnel_id": None,
    }
    stamp_create(rec)
    db.capas[rec["id"]] = rec

    # First CAPA opened against the NCR advances it to CAPA_IN_PROGRESS (PRD 3.4).
    # This create is the first CAPA because the NCR was still DISPOSITIONED.
    ncr["status"] = "CAPA_IN_PROGRESS"
    touch(ncr)

    return success(capa_out(rec), status=201)


@bp.route("/capas/<rid>", methods=["GET"])
def get_capa(rid):
    auth = authenticate()
    require_role(auth, {ROLE_QUALITY_MANAGER, ROLE_QUALITY_ENGINEER})
    rec = get_or_404(db.capas, rid)
    return success(capa_out(rec))


@bp.route("/capas/<rid>/steps", methods=["POST"])
def record_step(rid):
    auth = authenticate()
    require_role(auth, {ROLE_QUALITY_ENGINEER, ROLE_QUALITY_MANAGER})
    capa = get_or_404(db.capas, rid)
    body = request.get_json(silent=True) or {}

    require_fields(body, ["discipline", "narrative"])
    require_enum(body["discipline"], DISCIPLINES, "discipline")
    require_string(body["narrative"], "narrative")

    containment_count = body.get("containment_count", 0)
    if containment_count is None:
        containment_count = 0
    require_non_negative_int(containment_count, "containment_count", minimum=0)

    recurred_defects = body.get("recurred_defects", 0)
    if recurred_defects is None:
        recurred_defects = 0
    require_non_negative_int(recurred_defects, "recurred_defects", minimum=0)

    rec = {
        "capa_id": capa["id"],
        "discipline": body["discipline"],
        "narrative": body["narrative"],
        "containment_count": containment_count,
        "recurred_defects": recurred_defects,
        "recorded_by_personnel_id": auth.user_id,
    }
    # 8D step is append-only: id + created_at only (no updated_at/version).
    stamp_create(rec, with_version=False)
    db.eightd_steps[rec["id"]] = rec
    return success(eightd_step_out(rec), status=201)


@bp.route("/capas/<rid>/steps", methods=["GET"])
def list_steps(rid):
    auth = authenticate()
    require_role(auth, {ROLE_QUALITY_MANAGER, ROLE_QUALITY_ENGINEER})
    capa = get_or_404(db.capas, rid)
    limit, offset = paginate_args()
    matches = [s for s in db.eightd_steps.values() if s["capa_id"] == capa["id"]]
    page, total = paginate(matches, limit, offset)
    return list_success([eightd_step_out(s) for s in page], limit, offset, total)


def _steps_for(capa_id):
    return [s for s in db.eightd_steps.values() if s["capa_id"] == capa_id]


@bp.route("/capas/<rid>/transition", methods=["POST"])
def transition_capa(rid):
    auth = authenticate()
    require_role(auth, {ROLE_QUALITY_ENGINEER, ROLE_QUALITY_MANAGER})
    capa = get_or_404(db.capas, rid)
    body = request.get_json(silent=True) or {}

    require_fields(body, ["action"])
    action = body["action"]
    require_enum(action, CAPA_ACTIONS, "action")

    ncr = db.nonconformance_reports.get(capa["ncr_id"])
    defect_qty = ncr["defect_qty"] if ncr else 0
    steps = _steps_for(capa["id"])

    if action == "ADVANCE":
        # QualityEngineer-driven advances (PRD 3.4).
        if capa["status"] == "OPEN":
            if not any(s["discipline"] in {"D1", "D2", "D3"} for s in steps):
                raise err(ERR_INVALID_STATE, "Requires a D1/D2/D3 step before advancing")
            capa["status"] = "ROOT_CAUSE"
            capa["current_step"] = "D4"
            touch(capa)
            return success(capa_out(capa))
        if capa["status"] == "ROOT_CAUSE":
            if not any(s["discipline"] in {"D4", "D5"} and s["containment_count"] >= 1
                       for s in steps):
                raise err(ERR_INVALID_STATE,
                          "Requires a D4/D5 step with containment_count>=1")
            total_containment = sum(
                s["containment_count"] for s in steps if s["discipline"] in {"D4", "D5"})
            capa["status"] = "VERIFICATION"
            capa["current_step"] = "D6"
            capa["provisional_effectiveness"] = provisional_effectiveness(
                total_containment, defect_qty)
            touch(capa)
            return success(capa_out(capa))
        raise err(ERR_INVALID_STATE, "ADVANCE not defined from current state")

    # Remaining actions belong to the QualityManager and require SoD.
    if action == "REJECT_VERIFICATION":
        if capa["status"] != "VERIFICATION":
            raise err(ERR_INVALID_STATE, "REJECT_VERIFICATION requires VERIFICATION")
        if auth.user_id == capa["authored_by_personnel_id"]:
            raise err(ERR_SEGREGATION_OF_DUTIES, "Author may not reject verification")
        capa["rework_loops"] += 1
        capa["current_step"] = "D4"
        capa["provisional_effectiveness"] = None
        capa["status"] = "ROOT_CAUSE"
        touch(capa)
        return success(capa_out(capa))

    if action == "VERIFY":
        if capa["status"] != "VERIFICATION":
            raise err(ERR_INVALID_STATE, "VERIFY requires VERIFICATION")
        if auth.user_id == capa["authored_by_personnel_id"]:
            raise err(ERR_SEGREGATION_OF_DUTIES, "Author may not verify")
        prov = capa["provisional_effectiveness"]
        if prov is None or prov < Decimal("0.50"):
            raise err(ERR_EFFECTIVENESS_TOO_LOW, "provisional_effectiveness < 0.50")
        capa["current_step"] = "D7"
        capa["verified_by_personnel_id"] = auth.user_id
        capa["status"] = "EFFECTIVENESS_CHECK"
        touch(capa)
        return success(capa_out(capa))

    if action in {"CLOSE_EFFECTIVE", "CLOSE_INEFFECTIVE"}:
        if capa["status"] != "EFFECTIVENESS_CHECK":
            raise err(ERR_INVALID_STATE, "Close requires EFFECTIVENESS_CHECK")
        d8_steps = [s for s in steps if s["discipline"] == "D8"]
        if not d8_steps:
            raise err(ERR_INVALID_STATE, "Requires a D8 step")
        if auth.user_id == capa["authored_by_personnel_id"]:
            raise err(ERR_SEGREGATION_OF_DUTIES, "Author may not close")

        # final_effectiveness uses the D8 step's recurred_defects. Multiple D8
        # steps may exist; use the latest-created one.
        d8 = sorted(d8_steps, key=lambda s: (s["created_at"], s["id"]))[-1]
        final = final_effectiveness(d8["recurred_defects"], defect_qty)

        if action == "CLOSE_EFFECTIVE":
            if final < Decimal("0.80"):
                raise err(ERR_EFFECTIVENESS_TOO_LOW, "final_effectiveness < 0.80")
            capa["current_step"] = "D8"
            capa["final_effectiveness"] = final
            capa["status"] = "CLOSED_EFFECTIVE"
            touch(capa)
            _cascade_ncr_closed(ncr)
            return success(capa_out(capa))

        # CLOSE_INEFFECTIVE: compute final, no NCR cascade.
        capa["current_step"] = "D8"
        capa["final_effectiveness"] = final
        capa["status"] = "CLOSED_INEFFECTIVE"
        touch(capa)
        return success(capa_out(capa))

    raise err(ERR_INVALID_STATE, "Unsupported action")


def _cascade_ncr_closed(ncr):
    """Cascade: NCR CAPA_IN_PROGRESS -> CLOSED (PRD 3.4)."""
    if ncr is None or ncr["status"] != "CAPA_IN_PROGRESS":
        return
    ncr["status"] = "CLOSED"
    ncr["budget_reserved_cents"] = 0
    touch(ncr)
    # Further cascade: source=SUPPLIER + a SCAR in ACCEPTED_RESPONSE -> RESOLVED.
    if ncr["source"] == "SUPPLIER":
        for scar in db.scars.values():
            if scar["ncr_id"] == ncr["id"] and scar["status"] == "ACCEPTED_RESPONSE":
                scar["status"] = "RESOLVED"
                touch(scar)
                supplier = db.suppliers.get(scar["supplier_id"])
                if supplier is not None:
                    supplier["open_scar_count"] -= 1
                    recompute_supplier_rating(supplier)
