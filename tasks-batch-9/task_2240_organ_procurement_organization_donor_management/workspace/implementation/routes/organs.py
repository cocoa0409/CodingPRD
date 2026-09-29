"""Organ evaluation, match-run generation, transport dispatch and disposition."""

from flask import Blueprint, request

from constants import (
    DEFAULT_ACCEPTANCE_CLOCK_MINUTES,
    DEFAULT_NONTRANSPLANTABLE_REASON,
    DEFAULT_PRIMARY_OFFER_SLOTS,
    DISPOSITIONS,
    NONTRANSPLANTABLE_REASONS,
    ORGAN_EVALUATION_DECISIONS,
    ORGAN_STATUSES,
    ORGAN_TERMINAL,
    THORACIC_TYPES,
    TRANSPORT_MODES,
)
from db import base_record, clock_now, db, lock, ordered
from errors import ApiError
from middleware import authenticate
from response import ok, paginated
from services.calculations import cold_ischemic_projection
from services.domain import (
    organs_of_case,
    promotion_selector,
    refresh_asset_legs,
    refresh_organ_counters,
    runs_of_organ,
    set_allocation_status,
    supersede_open_runs,
    touch,
)
from validation import Body, json_body, page, pagination

bp = Blueprint("organs", __name__)


def resolve_organ(organ_id):
    record = db.organs.get(organ_id)
    if record is None:
        raise ApiError("ERR_ORGAN_NOT_FOUND")
    return record


def case_of(organ):
    return db.donor_cases.get(organ["donor_case_id"])


@bp.get("/opo/organs/<organ_id>")
def read_organ(organ_id):
    authenticate(
        "OpoAdmin", "DonorCoordinator", "MedicalDirector", "AllocationSpecialist", "RecoveryLogistics"
    )
    with lock:
        return ok(resolve_organ(organ_id))


@bp.get("/opo/organs")
def list_organs():
    authenticate(
        "OpoAdmin", "DonorCoordinator", "MedicalDirector", "AllocationSpecialist", "RecoveryLogistics"
    )
    with lock:
        limit, offset = pagination()
        case_id = request.args.get("donor_case_id")
        offer_id = request.args.get("accepted_offer_id")
        asset_id = request.args.get("transport_asset_id")
        status = request.args.get("status")
        rows = list(db.organs.values())
        if case_id is not None:
            rows = [r for r in rows if r["donor_case_id"] == case_id]
        if offer_id is not None:
            rows = [r for r in rows if r["accepted_offer_id"] == offer_id]
        if asset_id is not None:
            rows = [r for r in rows if r["transport_asset_id"] == asset_id]
        if status is not None:
            rows = [r for r in rows if r["status"] == status and status in ORGAN_STATUSES]
        rows = ordered(rows)
        return paginated(page(rows, limit, offset), limit, offset, len(rows))


@bp.post("/opo/organs/<organ_id>/evaluation")
def evaluate_organ(organ_id):
    authenticate("MedicalDirector")
    with lock:
        organ = resolve_organ(organ_id)
        body = Body()
        decision = body.enum("decision", ORGAN_EVALUATION_DECISIONS, required=True)
        reason = body.enum("nontransplantable_reason", NONTRANSPLANTABLE_REASONS)

        if organ["status"] != "PENDING_EVAL":
            raise ApiError("ERR_ORGAN_NOT_EVALUABLE")

        case = case_of(organ)
        if case is not None and case["case_posture"] == "FROZEN":
            raise ApiError("ERR_CASE_FROZEN")
        if decision == "ALLOCATABLE":
            if organ["viability_hold"]:
                raise ApiError("ERR_VIABILITY_HOLD_ACTIVE")
            if (
                case is not None
                and case["case_posture"] == "RESTRICTED"
                and organ["organ_type"] in THORACIC_TYPES
            ):
                raise ApiError("ERR_POSTURE_RESTRICTED")

        if decision == "ALLOCATABLE":
            organ["status"] = "ALLOCATABLE"
        else:
            organ["status"] = "NON_TRANSPLANTABLE"
            organ["nontransplantable_reason"] = reason or DEFAULT_NONTRANSPLANTABLE_REASON
        touch(organ)
        if case is not None:
            refresh_organ_counters(case)
        return ok(organ)


@bp.post("/opo/organs/<organ_id>/match-runs")
def generate_match_run(organ_id):
    authenticate("AllocationSpecialist")
    with lock:
        organ = resolve_organ(organ_id)
        body = Body()
        expected = body.integer("expected_organ_version", required=True)
        raw_candidates = body.raw_value("candidates")
        if raw_candidates is None or not isinstance(raw_candidates, list):
            raise ApiError("ERR_INVALID_REQUEST", "Field 'candidates' must be an array.")
        slots = body.integer(
            "primary_offer_slots", default=DEFAULT_PRIMARY_OFFER_SLOTS, minimum=1, maximum=3
        )

        candidates = []
        for entry in raw_candidates:
            if not isinstance(entry, dict):
                raise ApiError("ERR_INVALID_REQUEST", "Each candidate must be an object.")
            candidate = Body(entry)
            candidates.append(
                {
                    "sequence_position": candidate.integer(
                        "sequence_position", required=True, minimum=1
                    ),
                    "center_code": candidate.string("center_code", required=True, min_len=1),
                    "candidate_code": candidate.string("candidate_code", required=True, min_len=1),
                    "acceptance_clock_minutes": candidate.integer(
                        "acceptance_clock_minutes",
                        default=DEFAULT_ACCEPTANCE_CLOCK_MINUTES,
                        minimum=5,
                        maximum=240,
                    ),
                }
            )

        if organ["status"] not in ("ALLOCATABLE", "OFFERING"):
            raise ApiError("ERR_ORGAN_NOT_ALLOCATABLE")
        if expected != organ["version"]:
            raise ApiError("ERR_STALE_VERSION")

        case = case_of(organ)
        if case is not None and case["case_posture"] == "FROZEN":
            raise ApiError("ERR_CASE_FROZEN")
        if (
            case is not None
            and case["case_posture"] == "RESTRICTED"
            and organ["organ_type"] in THORACIC_TYPES
        ):
            raise ApiError("ERR_POSTURE_RESTRICTED")

        if not candidates:
            raise ApiError("ERR_EMPTY_MATCH_RUN")
        positions = sorted(c["sequence_position"] for c in candidates)
        if positions != list(range(1, len(positions) + 1)):
            raise ApiError("ERR_INVALID_SEQUENCE")

        supersede_open_runs(organ)

        highest = 0
        for existing in runs_of_organ(organ_id):
            highest = max(highest, existing["run_number"])

        run = base_record()
        run.update(
            {
                "organ_id": organ_id,
                "run_number": highest + 1,
                "status": "OPEN",
                "primary_offer_slots": slots,
                "candidate_count": len(candidates),
                "pending_offer_count": 0,
                "slots_free": slots,
                "generated_at": clock_now(),
                "closed_reason": None,
            }
        )
        db.match_runs[run["id"]] = run

        for candidate in candidates:
            offer = base_record()
            offer.update(
                {
                    "match_run_id": run["id"],
                    "sequence_position": candidate["sequence_position"],
                    "center_code": candidate["center_code"],
                    "candidate_code": candidate["candidate_code"],
                    "acceptance_clock_minutes": candidate["acceptance_clock_minutes"],
                    "status": "QUEUED",
                    "offered_at": None,
                    "expires_at": None,
                    "responded_at": None,
                    "decline_reason": None,
                    "increased_risk_ack": False,
                    "bypass_reason": None,
                    "responded_by_user_id": None,
                }
            )
            db.organ_offers[offer["id"]] = offer

        touch(organ)
        if case is not None and case["allocation_status"] == "NOT_STARTED":
            set_allocation_status(case, "MATCH_RUN_OPEN")

        promoted = promotion_selector(run)
        if promoted > 0:
            if organ["status"] == "ALLOCATABLE":
                organ["status"] = "OFFERING"
                touch(organ)
            if case is not None and case["allocation_status"] in ("NOT_STARTED", "MATCH_RUN_OPEN"):
                set_allocation_status(case, "OFFERS_IN_FLIGHT")

        payload = dict(run)
        payload["promoted_count"] = promoted
        return ok(payload, 201)


@bp.get("/opo/organs/<organ_id>/match-runs")
def list_match_runs(organ_id):
    authenticate("OpoAdmin", "AllocationSpecialist", "MedicalDirector")
    with lock:
        resolve_organ(organ_id)
        limit, offset = pagination()
        rows = runs_of_organ(organ_id)
        return paginated(page(rows, limit, offset), limit, offset, len(rows))


@bp.post("/opo/organs/<organ_id>/transport")
def dispatch_transport(organ_id):
    authenticate("RecoveryLogistics")
    with lock:
        organ = resolve_organ(organ_id)
        raw = json_body()
        if not isinstance(raw, dict):
            raise ApiError("ERR_INVALID_REQUEST", "The request body must be a JSON object.")

        supplied_asset = raw.get("transport_asset_id")
        if supplied_asset is not None:
            if not isinstance(supplied_asset, str) or supplied_asset not in db.transport_assets:
                raise ApiError("ERR_ASSET_NOT_FOUND")

        body = Body(raw)
        asset_id = body.string("transport_asset_id", required=True)
        mode = body.enum("transport_mode", TRANSPORT_MODES, required=True)
        depart_at = body.instant("transport_depart_at", required=True)
        arrive_at = body.instant("transport_arrive_at", required=True)

        if organ["status"] != "RECOVERED":
            raise ApiError("ERR_ORGAN_NOT_RECOVERED")

        case = case_of(organ)
        if case is not None and case["case_posture"] == "FROZEN":
            raise ApiError("ERR_CASE_FROZEN")

        if arrive_at <= depart_at:
            raise ApiError("ERR_INVALID_TIME_WINDOW")
        if organ["cross_clamp_at"] is not None and depart_at < organ["cross_clamp_at"]:
            raise ApiError("ERR_INVALID_TIME_WINDOW")

        asset = db.transport_assets[asset_id]
        transit, prep, projected, margin = cold_ischemic_projection(
            organ["cross_clamp_at"], depart_at, arrive_at, organ["cit_limit_minutes"]
        )
        if projected > organ["cit_limit_minutes"]:
            raise ApiError("ERR_COLD_ISCHEMIC_LIMIT_EXCEEDED")

        overlapping = 0
        for other in db.organs.values():
            if other["id"] == organ_id:
                continue
            if other["transport_asset_id"] != asset_id:
                continue
            if other["status"] not in ("RECOVERED", "TRANSPLANTED"):
                continue
            if other["transport_depart_at"] is None or other["transport_arrive_at"] is None:
                continue
            # Closed intervals: legs that merely touch at an endpoint do collide.
            if depart_at <= other["transport_arrive_at"] and other["transport_depart_at"] <= arrive_at:
                overlapping += 1
        if overlapping >= asset["concurrent_leg_capacity"]:
            raise ApiError("ERR_ASSET_CAPACITY_EXCEEDED")

        organ["transport_asset_id"] = asset_id
        organ["transport_mode"] = mode
        organ["transport_depart_at"] = depart_at
        organ["transport_arrive_at"] = arrive_at
        organ["transit_minutes"] = transit
        organ["implant_prep_minutes"] = prep
        organ["projected_cold_ischemic_minutes"] = projected
        organ["projected_cit_margin_minutes"] = margin
        touch(organ)
        refresh_asset_legs(asset)
        return ok(organ)


@bp.post("/opo/organs/<organ_id>/disposition")
def record_disposition(organ_id):
    authenticate("MedicalDirector")
    with lock:
        organ = resolve_organ(organ_id)
        body = Body()
        disposition = body.enum("disposition", DISPOSITIONS, required=True)
        research_code = body.string("research_protocol_code", min_len=1)
        tissue_code = body.string("tissue_processor_code", min_len=1)

        status = organ["status"]
        if status == "RECOVERED":
            if disposition not in ("TRANSPLANTED", "DISCARDED"):
                raise ApiError("ERR_DISPOSITION_NOT_ALLOWED")
        elif status == "NON_TRANSPLANTABLE":
            if disposition not in ("RESEARCH_REFERRED", "TISSUE_REFERRED"):
                raise ApiError("ERR_DISPOSITION_NOT_ALLOWED")
            if organ["nontransplantable_reason"] == "AUTHORIZATION_RESCINDED":
                raise ApiError("ERR_DISPOSITION_NOT_ALLOWED")
            if disposition == "RESEARCH_REFERRED" and research_code is None:
                raise ApiError("ERR_DISPOSITION_NOT_ALLOWED")
            if disposition == "TISSUE_REFERRED" and tissue_code is None:
                raise ApiError("ERR_DISPOSITION_NOT_ALLOWED")
        else:
            raise ApiError("ERR_DISPOSITION_NOT_ALLOWED")

        organ["status"] = disposition
        if disposition == "RESEARCH_REFERRED":
            organ["research_protocol_code"] = research_code
        elif disposition == "TISSUE_REFERRED":
            organ["tissue_processor_code"] = tissue_code
        touch(organ)

        case = case_of(organ)
        if case is not None:
            refresh_organ_counters(case)
            siblings = organs_of_case(case["id"])
            if siblings and all(o["status"] in ORGAN_TERMINAL for o in siblings):
                if case["allocation_status"] == "RECOVERED":
                    set_allocation_status(case, "CLOSED", "RECOVERY_COMPLETE")
        return ok(organ)
