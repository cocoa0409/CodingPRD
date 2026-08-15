"""The clinical packet and imaging exchange (PRD 3.5)."""

from flask import Blueprint, g

from core import domain as D
from core import schema as S
from core.envelope import object_response, paginate, filter_exact
from core.errors import fail
from core.store import db, new_row, bump

bp = Blueprint("packets", __name__)

_ERR = "ERR_INVALID_REQUEST"


def _packet_or_404(packet_id):
    packet = db.clinical_packets.get(packet_id)
    if packet is None:
        fail("ERR_PACKET_NOT_FOUND", "ClinicalPacket id does not exist.", 404)
    return packet


def _require_packet_sending_physician(packet):
    case = D.get_case(packet["transfer_case_id"])
    if case is None or g.user_id != case["sending_physician_id"]:
        fail("ERR_NOT_CASE_PHYSICIAN",
             "X-User-ID is not the packet case's sending physician.", 403)


@bp.post("/transfer-cases/<id>/clinical-packet")
def create_packet(id):
    b = S.body()
    required_documents = S.need_enum_list(b, "required_documents", D.DOCUMENT_CODES)
    if len(required_documents) == 0:
        fail(_ERR, "required_documents must be a non-empty array.", 400)
    imaging_studies = b.get("imaging_studies")
    if imaging_studies is None:
        imaging_studies = []
    if not isinstance(imaging_studies, list):
        fail(_ERR, "imaging_studies must be an array.", 400)
    studies = []
    for item in imaging_studies:
        if (not isinstance(item, dict)
                or not isinstance(item.get("study_ref"), str)
                or not isinstance(item.get("modality"), str)):
            fail(_ERR, "Each imaging study needs a study_ref and a modality.", 400)
        studies.append({"study_ref": item["study_ref"], "modality": item["modality"]})
    case = D.get_case(id)
    if case is None:
        fail("ERR_CASE_NOT_FOUND", "TransferCase id does not exist.", 404)
    if g.user_id != case["sending_physician_id"]:
        fail("ERR_NOT_CASE_PHYSICIAN",
             "X-User-ID is not the case's sending physician.", 403)
    if D.packet_of(id) is not None:
        fail("ERR_DUPLICATE_PACKET", "The case already has a ClinicalPacket.", 409)
    row = new_row("clinical_packets", {
        "transfer_case_id": id,
        "required_documents": list(required_documents),
        "received_documents": [],
        "imaging_studies": studies,
        "exchanged_study_refs": [],
    })
    return object_response(D.serialize_packet(row), 201)


@bp.get("/clinical-packets")
def list_packets():
    rows = db.ordered("clinical_packets")
    rows = filter_exact(rows, "transfer_case_id")
    return paginate(rows, D.serialize_packet)


@bp.get("/clinical-packets/<id>")
def get_packet(id):
    return object_response(D.serialize_packet(_packet_or_404(id)), 200)


@bp.post("/clinical-packets/<id>/documents")
def append_documents(id):
    b = S.body()
    documents = S.need_enum_list(b, "documents", D.DOCUMENT_CODES)
    expected_version = S.need_int(b, "expected_clinical_packet_version")
    packet = _packet_or_404(id)
    _require_packet_sending_physician(packet)
    if expected_version != packet["version"]:
        fail("ERR_STALE_VERSION",
             "expected_clinical_packet_version does not match the packet's current version.",
             412)
    received = list(packet["received_documents"])
    seen = set(received)
    for doc in documents:
        if doc not in seen:
            received.append(doc)
            seen.add(doc)
    packet["received_documents"] = received
    bump(packet)
    return object_response(D.serialize_packet(packet), 200)


@bp.post("/clinical-packets/<id>/imaging-exchange")
def imaging_exchange(id):
    b = S.body()
    refs = S.need_str_list(b, "exchanged_study_refs")
    packet = _packet_or_404(id)
    _require_packet_sending_physician(packet)
    exchanged = list(packet["exchanged_study_refs"])
    seen = set(exchanged)
    for ref in refs:
        if ref not in seen:
            exchanged.append(ref)
            seen.add(ref)
    packet["exchanged_study_refs"] = exchanged
    bump(packet)
    return object_response(D.serialize_packet(packet), 200)
