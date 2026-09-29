"""Patent disclosures, licensing commitments and the call for patents (PRD 3.7)."""

from flask import Blueprint

from core import auth, envelope
from core.enums import COMMITMENT_ACTION, ESSENTIALITY
from core.errors import fail
from core.store import db, insert, now_iso, public, rows, touch
from core.validation import Body, apply_filters, load_fk, load_path
from services import ip

bp = Blueprint("patents", __name__)

FILTERS = ("work_item_id", "disclosing_participant_id", "essentiality", "status")

COMMITMENT_STATUS = {
    "RAND": "RAND_COMMITTED",
    "RAND_ZERO": "RAND_ZERO_COMMITTED",
    "REFUSE": "REFUSED",
    "WITHDRAW": "WITHDRAWN",
}
LETTER_REQUIRED = ("RAND", "RAND_ZERO")

PARTICIPATING_ROLES = (auth.COMMITTEE_MEMBER, auth.COMMITTEE_CHAIR,
                       auth.PUBLIC_COMMENTER, auth.PROPOSER)


@bp.post("/sdo/patent-disclosures")
def record_disclosure():
    auth.authenticate(PARTICIPATING_ROLES)
    body = Body(("work_item_id", "disclosing_participant_id", "patent_number",
                 "essentiality", "expected_work_item_version"))
    work_item_id = body.id_ref("work_item_id", required=True)
    discloser_id = body.id_ref("disclosing_participant_id", required=True)
    patent_number = body.string("patent_number", required=True, min_len=1, max_len=40)
    essentiality = body.enum("essentiality", ESSENTIALITY, required=True)
    expected_version = body.integer("expected_work_item_version", required=True,
                                    minimum=0)

    work_item = load_fk("work_items", work_item_id, optional=False)
    load_fk("participants", discloser_id, optional=False)
    auth.require_actor_identity(discloser_id)

    if expected_version != work_item["version"]:
        fail("ERR_STALE_WORK_ITEM_VERSION",
             "expected_work_item_version %d does not match the work item's version %d."
             % (expected_version, work_item["version"]))

    row = insert("patent_disclosures", {
        "work_item_id": work_item["id"],
        "disclosing_participant_id": discloser_id,
        "patent_number": patent_number,
        "essentiality": essentiality,
        "status": "DISCLOSED_NO_COMMITMENT",
        "commitment_letter_ref": None,
        "disclosed_at": now_iso(),
        "committed_at": None,
        "blocks_publication": False,
    })
    row["blocks_publication"] = ip.blocks_publication(row)

    ip.recompute(work_item)
    touch(work_item)
    return envelope.created(public(row))


@bp.get("/sdo/patent-disclosures")
def list_disclosures():
    auth.authenticate(auth.READ_ROLES)
    return envelope.list_response(apply_filters(rows("patent_disclosures"), FILTERS))


@bp.get("/sdo/patent-disclosures/<patent_disclosure_id>")
def get_disclosure(patent_disclosure_id):
    auth.authenticate(auth.READ_ROLES)
    return envelope.object_response(
        public(load_path("patent_disclosures", patent_disclosure_id)))


@bp.post("/sdo/patent-disclosures/<patent_disclosure_id>/commitment")
def record_commitment(patent_disclosure_id):
    auth.authenticate(PARTICIPATING_ROLES)
    disclosure = load_path("patent_disclosures", patent_disclosure_id)
    body = Body(("commitment", "commitment_letter_ref"))
    commitment = body.enum("commitment", COMMITMENT_ACTION, required=True)
    letter_ref = body.string("commitment_letter_ref",
                             required=(commitment in LETTER_REQUIRED),
                             min_len=1, max_len=80, nullable=True, default=None)

    disclosure["status"] = COMMITMENT_STATUS[commitment]
    if commitment in LETTER_REQUIRED:
        disclosure["commitment_letter_ref"] = letter_ref
        disclosure["committed_at"] = now_iso()
    disclosure["blocks_publication"] = ip.blocks_publication(disclosure)
    touch(disclosure)

    work_item = db.work_items.get(disclosure["work_item_id"])
    if work_item is not None:
        ip.recompute(work_item)
        touch(work_item)
    return envelope.object_response(public(disclosure))
