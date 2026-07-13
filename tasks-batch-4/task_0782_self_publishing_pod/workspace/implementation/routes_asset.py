"""Assets: upload + validate + reads. ISBN reads."""
from decimal import Decimal
from flask import Blueprint, request

from auth import identity, require_roles, require_ownership
from envelope import ApiError, success
from helpers import resolve, get_body, require_fields, require_enum, paginate_list
from store import db, base_record, touch
import calc
import models
import queries

bp = Blueprint("asset", __name__)

ASSET_TYPES = {"INTERIOR", "COVER"}
FILE_FORMATS = {"PDF", "EPUB", "DOCX", "AAX", "JPG", "TIFF"}
PAPER_TYPES = {"WHITE", "CREAM", "COLOR"}
INTERIOR_OK_FORMATS = {"PDF", "EPUB", "DOCX"}
COVER_OK_FORMATS = {"JPG", "TIFF", "PDF"}


@bp.route("/formats/<fid>/assets", methods=["POST"])
def upload_asset(fid):
    uid, role = identity()
    require_roles(role, {"Publisher"})
    fmt = resolve("format", fid)
    require_ownership(role, uid, "format", fmt)
    body = get_body()
    require_fields(body, ["asset_type", "file_ref", "file_format"])
    asset_type = body["asset_type"]
    require_enum(asset_type, ASSET_TYPES, "asset_type")
    require_enum(body["file_format"], FILE_FORMATS, "file_format")
    paper_type = body.get("paper_type")
    if paper_type is not None:
        require_enum(paper_type, PAPER_TYPES, "paper_type")

    spine = None
    if asset_type == "COVER" and paper_type is not None and fmt.get("page_count") is not None:
        spine = calc.cover_spine_width(fmt["page_count"], paper_type)

    rec = base_record()
    rec.update({
        "format_id": fmt["id"],
        "asset_type": asset_type,
        "file_ref": body["file_ref"],
        "file_format": body["file_format"],
        "declared_page_count": body.get("declared_page_count"),
        "paper_type": paper_type,
        "declared_spine_mm": body.get("declared_spine_mm"),
        "spine_width_mm": spine,
        "status": "PENDING",
        "rejection_reason": None,
    })
    db.assets[rec["id"]] = rec
    return success(models.ser_asset(rec), status=201)


@bp.route("/assets/<aid>/validate", methods=["POST"])
def validate_asset(aid):
    uid, role = identity()
    require_roles(role, {"PlatformAdmin"})
    asset = resolve("asset", aid)
    if asset["status"] != "PENDING":
        raise ApiError("ERR_ASSET_INVALID_STATE", "Asset must be PENDING to validate")

    if asset["asset_type"] == "INTERIOR":
        pages = asset.get("declared_page_count")
        if pages is None or pages < calc.MIN_PAGE_COUNT:
            asset["status"] = "REJECTED"
            asset["rejection_reason"] = "ERR_PAGE_COUNT_TOO_LOW"
        elif asset["file_format"] not in INTERIOR_OK_FORMATS:
            asset["status"] = "REJECTED"
            asset["rejection_reason"] = "ERR_PAGE_COUNT_TOO_LOW"
        else:
            asset["status"] = "VALIDATED"
            asset["rejection_reason"] = None
    else:  # COVER
        fmt = db.formats.get(asset["format_id"])
        paper = asset.get("paper_type")
        page_count = fmt.get("page_count") if fmt else None
        if paper is not None and page_count is not None:
            asset["spine_width_mm"] = calc.cover_spine_width(page_count, paper)
        declared = asset.get("declared_spine_mm")
        computed = asset.get("spine_width_mm")
        within = False
        if declared is not None and computed is not None:
            diff = abs(Decimal(str(declared)) - Decimal(str(computed)))
            within = diff <= calc.SPINE_TOLERANCE_MM
        if asset["file_format"] in COVER_OK_FORMATS and within:
            asset["status"] = "VALIDATED"
            asset["rejection_reason"] = None
        else:
            asset["status"] = "REJECTED"
            asset["rejection_reason"] = "ERR_SPINE_MISMATCH"
    touch(asset)
    return success(models.ser_asset(asset))


@bp.route("/assets/<aid>", methods=["GET"])
def get_asset(aid):
    uid, role = identity()
    require_roles(role, {"Publisher", "PlatformAdmin"})
    rec = resolve("asset", aid)
    require_ownership(role, uid, "asset", rec)
    return success(models.ser_asset(rec))


@bp.route("/assets", methods=["GET"])
def list_assets():
    uid, role = identity()
    require_roles(role, {"Publisher", "PlatformAdmin"})
    records = list(db.assets.values())
    if role == "Publisher":
        records = [a for a in records
                   if queries.publisher_id_of_format(db.formats.get(a["format_id"])) == uid]
    fid = request.args.get("format_id")
    if fid:
        records = [a for a in records if a.get("format_id") == fid]
    return paginate_list(records, models.ser_asset)


# ---------------- ISBN reads ----------------
@bp.route("/isbns/<iid>", methods=["GET"])
def get_isbn(iid):
    uid, role = identity()
    require_roles(role, {"Publisher", "PlatformAdmin"})
    rec = resolve("isbn", iid)
    require_ownership(role, uid, "isbn", rec)
    return success(models.ser_isbn(rec))


@bp.route("/isbns", methods=["GET"])
def list_isbns():
    uid, role = identity()
    require_roles(role, {"Publisher", "PlatformAdmin"})
    records = list(db.isbns.values())
    if role == "Publisher":
        records = [i for i in records if i.get("publisher_id") == uid]
    pub = request.args.get("publisher_id")
    afid = request.args.get("assigned_format_id")
    if pub:
        records = [i for i in records if i.get("publisher_id") == pub]
    if afid:
        records = [i for i in records if i.get("assigned_format_id") == afid]
    return paginate_list(records, models.ser_isbn)
