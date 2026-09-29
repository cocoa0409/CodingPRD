"""Solicitation catalogs and their listings (PRD 3.4)."""

from flask import Blueprint

from core import (
    CATALOG_STATUSES,
    SOLICITATION_STATUSES,
    ApiError,
    apply_fields,
    auth,
    bad,
    created_row,
    db,
    fmt_dt,
    get_body,
    ok_list,
    ok_row,
    ordered,
    page,
    q_enum,
    q_month,
    v_datetime,
    v_id_list,
    v_int,
    v_month,
    v_str,
)
import services as svc

catalogs_bp = Blueprint("catalogs", __name__, url_prefix="/comics/catalogs")
solicitations_bp = Blueprint("solicitations", __name__, url_prefix="/comics/solicitations")

SOLICITABLE_PRODUCTION_STATUSES = ("SCRIPTING", "ART", "PREPRESS", "CAMERA_READY")


# ---------------------------------------------------------------------------
# Catalogs
# ---------------------------------------------------------------------------


@catalogs_bp.post("")
def create_catalog():
    auth(("SalesDirector",))
    body = get_body()
    solicitation_month = v_month(body, "solicitation_month", required=True)
    submission_deadline = v_datetime(body, "submission_deadline", required=True)
    on_sale_month = v_month(body, "on_sale_month", required=True)
    max_slots = v_int(body, "max_slots", required=True, minimum=1)
    if on_sale_month <= solicitation_month:
        bad("Field 'on_sale_month' must be strictly after 'solicitation_month'.")
    if any(c["solicitation_month"] == solicitation_month for c in db.catalogs.values()):
        bad("A catalog for solicitation month %s already exists." % solicitation_month)

    row = db.new_row(
        solicitation_month=solicitation_month,
        submission_deadline=fmt_dt(submission_deadline),
        on_sale_month=on_sale_month,
        max_slots=max_slots,
        status="OPEN",
        accepted_slot_count=0,
        published_at=None,
    )
    db.catalogs[row["id"]] = row
    return created_row(svc.catalog_json, row)


@catalogs_bp.get("")
def list_catalogs():
    auth(("EditorInChief", "ManagingEditor", "SalesDirector"))
    status = q_enum("status", CATALOG_STATUSES)
    solicitation_month = q_month("solicitation_month")
    rows = ordered(db.catalogs)
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if solicitation_month is not None:
        rows = [r for r in rows if r["solicitation_month"] == solicitation_month]
    window, meta = page(rows)
    return ok_list(svc.catalog_json, window, meta)


@catalogs_bp.get("/<catalog_id>")
def read_catalog(catalog_id):
    auth(("EditorInChief", "ManagingEditor", "SalesDirector"))
    return ok_row(svc.catalog_json, svc.get_catalog(catalog_id))


@catalogs_bp.post("/<catalog_id>/lock")
def lock_catalog(catalog_id):
    auth(("SalesDirector",))
    catalog = svc.get_catalog(catalog_id)
    if catalog["status"] != "OPEN":
        raise ApiError(
            "ERR_INVALID_STATE",
            "A catalog locks from OPEN, not %s." % catalog["status"],
        )
    if db.now() <= catalog["submission_deadline"]:
        raise ApiError(
            "ERR_CATALOG_DEADLINE_NOT_PASSED",
            "The submission deadline has not yet lapsed.",
        )
    apply_fields(catalog, status="LOCKED")
    return ok_row(svc.catalog_json, catalog)


@catalogs_bp.post("/<catalog_id>/publish")
def publish_catalog(catalog_id):
    auth(("SalesDirector",))
    catalog = svc.get_catalog(catalog_id)
    if catalog["status"] != "LOCKED":
        raise ApiError(
            "ERR_INVALID_STATE",
            "A catalog publishes from LOCKED, not %s." % catalog["status"],
        )
    if catalog["accepted_slot_count"] == 0:
        raise ApiError(
            "ERR_NO_ACCEPTED_SOLICITATIONS",
            "The catalog carries no accepted listing to announce.",
        )
    apply_fields(catalog, status="PUBLISHED", published_at=db.now())
    for solicitation in svc.catalog_solicitations(catalog["id"]):
        if solicitation["status"] != "ACCEPTED":
            continue
        issue = db.issues.get(solicitation["issue_id"])
        if issue is not None and issue["commercial_status"] == "UNSOLICITED":
            apply_fields(issue, commercial_status="SOLICITED")
    return ok_row(svc.catalog_json, catalog)


# ---------------------------------------------------------------------------
# Solicitations
# ---------------------------------------------------------------------------


@catalogs_bp.post("/<catalog_id>/solicitations")
def draft_solicitation(catalog_id):
    auth(("ManagingEditor",))
    body = get_body()
    issue_id = v_str(body, "issue_id", required=True, min_len=1)
    cover_image_url = v_str(body, "cover_image_url", required=True, min_len=1, max_len=500)
    copy_text = v_str(body, "copy_text", required=True, min_len=40, max_len=1200)
    variant_cover_ids = v_id_list(body, "variant_cover_ids", default=[])
    if not cover_image_url.startswith("https://"):
        bad("Field 'cover_image_url' must begin with https://.")

    catalog = svc.get_catalog(catalog_id)
    issue = svc.get_issue(issue_id)
    for cover_id in variant_cover_ids:
        cover = db.variant_covers.get(cover_id)
        if cover is None or cover["issue_id"] != issue["id"]:
            raise ApiError(
                "ERR_VARIANT_COVER_NOT_FOUND",
                "Variant cover %s does not belong to the solicited issue." % cover_id,
            )

    if catalog["status"] == "PUBLISHED":
        raise ApiError(
            "ERR_INVALID_STATE", "A published catalog can take no further listings."
        )
    if issue["commercial_status"] == "CANCELLED" or issue["production_status"] == "CANCELLED":
        raise ApiError("ERR_INVALID_STATE", "A cancelled issue cannot be solicited.")

    for other in svc.catalog_solicitations(catalog["id"]):
        if other["issue_id"] == issue["id"] and other["status"] in (
            "DRAFT",
            "SUBMITTED",
            "ACCEPTED",
        ):
            raise ApiError(
                "ERR_DUPLICATE_SOLICITATION",
                "This issue already holds a listing in this catalog.",
            )

    row = db.new_row(
        catalog_id=catalog["id"],
        issue_id=issue["id"],
        cover_image_url=cover_image_url,
        copy_text=copy_text,
        variant_cover_ids=list(variant_cover_ids),
        status="DRAFT",
        submitted_at=None,
        withdrawn_reason=None,
    )
    db.solicitations[row["id"]] = row
    return created_row(svc.solicitation_json, row)


@catalogs_bp.get("/<catalog_id>/solicitations")
def list_catalog_solicitations(catalog_id):
    auth(("EditorInChief", "ManagingEditor", "SalesDirector"))
    status = q_enum("status", SOLICITATION_STATUSES)
    catalog = svc.get_catalog(catalog_id)
    rows = svc.catalog_solicitations(catalog["id"])
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    window, meta = page(rows)
    return ok_list(svc.solicitation_json, window, meta)


@solicitations_bp.get("/<solicitation_id>")
def read_solicitation(solicitation_id):
    auth(("EditorInChief", "ManagingEditor", "SalesDirector"))
    return ok_row(svc.solicitation_json, svc.get_solicitation(solicitation_id))


@solicitations_bp.post("/<solicitation_id>/submit")
def submit_solicitation(solicitation_id):
    auth(("ManagingEditor",))
    solicitation = svc.get_solicitation(solicitation_id)
    catalog = svc.get_catalog(solicitation["catalog_id"])
    issue = svc.get_issue(solicitation["issue_id"])

    if solicitation["status"] != "DRAFT":
        raise ApiError(
            "ERR_INVALID_STATE",
            "A listing submits from DRAFT, not %s." % solicitation["status"],
        )
    if catalog["status"] != "OPEN":
        raise ApiError(
            "ERR_INVALID_STATE",
            "The catalog is %s and no longer accepts submissions." % catalog["status"],
        )
    if issue["production_status"] not in SOLICITABLE_PRODUCTION_STATUSES:
        raise ApiError(
            "ERR_INVALID_STATE",
            "An issue in production status %s has nothing to solicit."
            % issue["production_status"],
        )
    if db.now() > catalog["submission_deadline"]:
        raise ApiError(
            "ERR_SOLICITATION_WINDOW_CLOSED",
            "The catalog's submission window has closed.",
        )
    if svc.standard_cover(issue["id"]) is None:
        raise ApiError(
            "ERR_STANDARD_COVER_REQUIRED",
            "The issue carries no STANDARD cover for the catalog to print.",
        )

    apply_fields(solicitation, status="SUBMITTED", submitted_at=db.now())
    return ok_row(svc.solicitation_json, solicitation)


@solicitations_bp.post("/<solicitation_id>/accept")
def accept_solicitation(solicitation_id):
    auth(("SalesDirector",))
    solicitation = svc.get_solicitation(solicitation_id)
    catalog = svc.get_catalog(solicitation["catalog_id"])
    if solicitation["status"] != "SUBMITTED":
        raise ApiError(
            "ERR_INVALID_STATE",
            "A listing is accepted from SUBMITTED, not %s." % solicitation["status"],
        )
    if catalog["status"] != "LOCKED":
        raise ApiError(
            "ERR_CATALOG_NOT_LOCKED",
            "The catalog must be LOCKED before its slate is chosen.",
        )
    if catalog["accepted_slot_count"] >= catalog["max_slots"]:
        raise ApiError(
            "ERR_CATALOG_SLOTS_EXHAUSTED",
            "The catalog's %d slots are all taken." % catalog["max_slots"],
        )
    apply_fields(solicitation, status="ACCEPTED")
    svc.recompute_catalog_slots(catalog)
    return ok_row(svc.solicitation_json, solicitation)


@solicitations_bp.post("/<solicitation_id>/withdraw")
def withdraw_solicitation(solicitation_id):
    auth(("SalesDirector",))
    body = get_body()
    reason = v_str(body, "reason", required=True, min_len=1, max_len=500)
    solicitation = svc.get_solicitation(solicitation_id)
    catalog = svc.get_catalog(solicitation["catalog_id"])
    if solicitation["status"] not in ("SUBMITTED", "ACCEPTED"):
        raise ApiError(
            "ERR_INVALID_STATE",
            "A %s listing cannot be withdrawn." % solicitation["status"],
        )
    if catalog["status"] == "PUBLISHED":
        raise ApiError(
            "ERR_INVALID_STATE",
            "A listing in a published catalog cannot be withdrawn by an operator.",
        )
    apply_fields(solicitation, status="WITHDRAWN", withdrawn_reason=reason)
    svc.recompute_catalog_slots(catalog)
    return ok_row(svc.solicitation_json, solicitation)
