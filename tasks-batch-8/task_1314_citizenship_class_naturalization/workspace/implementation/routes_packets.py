"""Application packets: create, legal review cycle, certify, file."""
from flask import Blueprint, g, request

from auth import authenticate, require_roles, ROLES
from db import db, Rec, stamp_new, bump, now_dt, new_receipt_number
from errors import (err_not_found, err_forbidden, err_invalid_state, conflict)
from services import (ser_packet, ser_case, check_accreditation,
                      attained_readiness_score, filing_fee_cents)
from util import (json_body, success_obj, paginate, v_str)
from db import prog_param

bp = Blueprint("packets", __name__)

ACTIVE_PACKET_STATUSES = ("DRAFT", "IN_LEGAL_REVIEW", "NEEDS_REVISION", "CERTIFIED")


def _get_packet(packet_id):
    p = db.packets.get(packet_id)
    if p is None:
        raise err_not_found("Packet not found")
    return p


def _actor_legal_volunteer():
    """Resolve the acting Volunteer row and require non-lapsed LEGAL."""
    v = db.volunteers.get(g.user_id)
    if v is None:
        raise conflict("ERR_ACCREDITATION_INSUFFICIENT",
                       "Acting volunteer is not registered")
    check_accreditation(v, "LEGAL")
    return v


@bp.post("/naturalization/applicants/<applicant_id>/packets")
def create_packet(applicant_id):
    body = json_body()
    seat_id = v_str(body, "workshop_seat_id")
    prepared_by = v_str(body, "prepared_by_volunteer_id")
    waiver_id = v_str(body, "fee_waiver_request_id", required=False)
    authenticate()
    require_roles("IntakeCoordinator")
    applicant = db.applicants.get(applicant_id)
    if applicant is None:
        raise err_not_found("Applicant not found")
    seat = db.seats.get(seat_id)
    if seat is None:
        raise err_not_found("Workshop seat not found")
    preparer = db.volunteers.get(prepared_by)
    if preparer is None:
        raise err_not_found("Preparing volunteer not found")
    waiver = None
    if waiver_id is not None:
        waiver = db.fee_waivers.get(waiver_id)
        if waiver is None:
            raise err_not_found("Fee waiver request not found")
    check_accreditation(preparer, "GENERAL_OR_LEGAL")
    if seat.status != "ATTENDED":
        raise conflict("ERR_WORKSHOP_NOT_ATTENDED",
                       "Referenced workshop seat is not ATTENDED")
    if seat.applicant_id != applicant.id:
        raise conflict("ERR_REFERENTIAL_MISMATCH",
                       "Workshop seat belongs to a different applicant")
    if waiver is not None and waiver.applicant_id != applicant.id:
        raise conflict("ERR_REFERENTIAL_MISMATCH",
                       "Fee waiver request belongs to a different applicant")
    for p in db.packets.values():
        if p.applicant_id == applicant.id and p.status in ACTIVE_PACKET_STATUSES:
            raise conflict("ERR_PACKET_ALREADY_ACTIVE",
                           "Applicant already has an active packet")
    p = Rec(applicant_id=applicant.id, workshop_seat_id=seat.id,
            prepared_by_volunteer_id=prepared_by, fee_waiver_request_id=waiver_id,
            status="DRAFT", certified_by_volunteer_id=None, filing_fee_cents=None)
    stamp_new(p)
    db.packets[p.id] = p
    return success_obj(ser_packet(p), 201)


@bp.get("/naturalization/packets")
def list_packets():
    authenticate()
    require_roles(*ROLES)
    recs = list(db.packets.values())
    if g.user_role == "Applicant":
        recs = [p for p in recs if p.applicant_id == g.user_id]
    for field in ("applicant_id", "workshop_seat_id", "status",
                  "prepared_by_volunteer_id", "certified_by_volunteer_id",
                  "fee_waiver_request_id"):
        val = request.args.get(field)
        if val is not None:
            recs = [p for p in recs if getattr(p, field) == val]
    return paginate(recs, ser_packet)


@bp.get("/naturalization/packets/<packet_id>")
def get_packet(packet_id):
    authenticate()
    require_roles(*ROLES)
    p = _get_packet(packet_id)
    if g.user_role == "Applicant" and p.applicant_id != g.user_id:
        raise err_forbidden("Applicants may only read their own packets")
    return success_obj(ser_packet(p))


@bp.post("/naturalization/packets/<packet_id>/submit-review")
def submit_review(packet_id):
    json_body()
    authenticate()
    require_roles("IntakeCoordinator")
    p = _get_packet(packet_id)
    if p.status != "DRAFT":
        raise err_invalid_state("Only a DRAFT packet may be submitted for review")
    p.status = "IN_LEGAL_REVIEW"
    bump(p)
    return success_obj(ser_packet(p))


@bp.post("/naturalization/packets/<packet_id>/request-revision")
def request_revision(packet_id):
    body = json_body()
    v_str(body, "revision_notes")
    authenticate()
    require_roles("Volunteer")
    p = _get_packet(packet_id)
    if p.status != "IN_LEGAL_REVIEW":
        raise err_invalid_state("Only a packet under legal review may be revised")
    _actor_legal_volunteer()
    p.status = "NEEDS_REVISION"
    bump(p)
    return success_obj(ser_packet(p))


@bp.post("/naturalization/packets/<packet_id>/revise")
def revise(packet_id):
    json_body()
    authenticate()
    require_roles("IntakeCoordinator")
    p = _get_packet(packet_id)
    if p.status != "NEEDS_REVISION":
        raise err_invalid_state("Only a NEEDS_REVISION packet may be revised")
    p.status = "DRAFT"
    bump(p)
    return success_obj(ser_packet(p))


@bp.post("/naturalization/packets/<packet_id>/certify")
def certify(packet_id):
    json_body()
    authenticate()
    require_roles("Volunteer")
    p = _get_packet(packet_id)
    if p.status != "IN_LEGAL_REVIEW":
        raise err_invalid_state("Only a packet under legal review may be certified")
    _actor_legal_volunteer()
    if g.user_id == p.prepared_by_volunteer_id:
        raise conflict("ERR_SOD_CERTIFIER_IS_PREPARER",
                       "The certifier must differ from the preparer")
    applicant = db.applicants.get(p.applicant_id)
    screening = None
    if applicant is not None and applicant.current_screening_id:
        s = db.screenings.get(applicant.current_screening_id)
        if s is not None and s.status == "ACTIVE":
            screening = s
    if screening is None or not (screening.expires_at > now_dt()):
        raise conflict("ERR_SCREENING_EXPIRED",
                       "The applicant's ACTIVE screening has expired")
    if attained_readiness_score(applicant) < prog_param("readiness_certify_threshold"):
        raise conflict("ERR_READINESS_BELOW_THRESHOLD",
                       "Attained readiness is below the certify threshold")
    final_tier = None
    if p.fee_waiver_request_id is not None:
        waiver = db.fee_waivers.get(p.fee_waiver_request_id)
        if waiver is None or waiver.status not in ("APPROVED", "DENIED"):
            raise conflict("ERR_FEE_WAIVER_PENDING",
                           "Linked fee waiver request is not in a terminal state")
        if waiver.status == "APPROVED":
            final_tier = waiver.final_tier
    p.certified_by_volunteer_id = g.user_id
    p.filing_fee_cents = filing_fee_cents(final_tier)
    p.status = "CERTIFIED"
    bump(p)
    return success_obj(ser_packet(p))


@bp.post("/naturalization/packets/<packet_id>/file")
def file_packet(packet_id):
    json_body()
    authenticate()
    require_roles("IntakeCoordinator")
    p = _get_packet(packet_id)
    if p.status != "CERTIFIED":
        raise err_invalid_state("Only a CERTIFIED packet may be filed")
    for c in db.cases.values():
        if c.applicant_id == p.applicant_id and c.stage != "APPLICATION_DENIED":
            raise conflict("ERR_CASE_ALREADY_ACTIVE",
                           "Applicant already has an active USCIS case")
    case = Rec(applicant_id=p.applicant_id, packet_id=p.id,
               receipt_number=new_receipt_number(), stage="FILED",
               rfe_status="NONE", rfe_issued_at=None, rfe_deadline=None,
               oath_ceremony_id=None)
    stamp_new(case)
    db.cases[case.id] = case
    p.status = "FILED"
    bump(p)
    applicant = db.applicants.get(p.applicant_id)
    if applicant is not None:
        applicant.stage = "FILED"
        bump(applicant)
    return success_obj(ser_case(case), 201)
