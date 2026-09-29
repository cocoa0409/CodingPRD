"""Artworks: reads, images, condition reports, placement and returns."""

from flask import Blueprint

from core import *  # noqa: F401,F403
from errors import ApiError

bp = Blueprint("artworks", __name__)


# ---------------------------------------------------------------------------
# Identity masking
# ---------------------------------------------------------------------------


def artwork_view(artwork):
    data = public(artwork)
    if role() != "Juror":
        return data
    exhibition = exhibition_of_artwork(artwork)
    if exhibition is None:
        return data
    for jury_round in rounds_of_exhibition(exhibition["id"]):
        if (
            jury_round.get("round_type") == "BLIND_SCORING"
            and jury_round.get("status") == "OPEN"
        ):
            data["entry_id"] = None
            break
    return data


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------


@bp.get("/artworks")
def list_artworks():
    authenticate()
    require_roles(ALL_ROLES)
    items = all_of("artworks")
    entry_id = qs("entry_id")
    if entry_id is not None:
        items = [a for a in items if a.get("entry_id") == entry_id]
    exhibition_id = qs("exhibition_id")
    if exhibition_id is not None:
        keep = []
        for artwork in items:
            entry = entry_of(artwork)
            if entry is not None and entry.get("exhibition_id") == exhibition_id:
                keep.append(artwork)
        items = keep
    wall_segment_id = qs("wall_segment_id")
    if wall_segment_id is not None:
        items = [a for a in items if a.get("wall_segment_id") == wall_segment_id]
    status = qs("status")
    if status is not None:
        items = [a for a in items if a.get("status") == status]
    placement = qs("placement_status")
    if placement is not None:
        items = [a for a in items if a.get("placement_status") == placement]
    return listing(items, transform=artwork_view)


@bp.get("/artworks/<artwork_id>")
def read_artwork(artwork_id):
    authenticate()
    require_roles(ALL_ROLES)
    artwork = find("artworks", artwork_id)
    flush()
    return ok(artwork_view(artwork))


# ---------------------------------------------------------------------------
# Images
# ---------------------------------------------------------------------------


@bp.post("/artworks/<artwork_id>/images")
def upload_image(artwork_id):
    authenticate()
    require_roles("Artist")
    artwork = find("artworks", artwork_id)
    entry = entry_of(artwork)
    own(entry is not None and user_id() == entry.get("artist_id"))
    payload = body()

    image_role = v_enum(payload, "role", IMAGE_ROLES)
    image_format = v_enum(payload, "format", IMAGE_FORMATS)
    pixel_long = v_int(payload, "pixel_long_edge", minimum=0)
    pixel_short = v_int(payload, "pixel_short_edge", minimum=0)
    file_bytes = v_int(payload, "file_bytes", minimum=0)
    color_profile = v_enum(payload, "color_profile", COLOR_PROFILES)
    checksum = v_str(payload, "checksum_sha256")
    capture_date = payload.get("capture_date")
    credit_line = payload.get("credit_line")

    # (33) digital image standard
    if image_format not in ("JPEG", "PNG"):
        raise ApiError("ERR_IMAGE_STANDARD_VIOLATION")
    if pixel_long < 1200:
        raise ApiError("ERR_IMAGE_STANDARD_VIOLATION")
    if pixel_short < 800:
        raise ApiError("ERR_IMAGE_STANDARD_VIOLATION")
    if file_bytes > 8388608:
        raise ApiError("ERR_IMAGE_STANDARD_VIOLATION")
    if color_profile != "SRGB":
        raise ApiError("ERR_IMAGE_STANDARD_VIOLATION")

    # (34) metadata completeness
    if not isinstance(credit_line, str) or not credit_line.strip():
        raise ApiError("ERR_IMAGE_METADATA_INCOMPLETE")
    captured = parse_dt(capture_date) if isinstance(capture_date, str) else None
    if captured is None:
        raise ApiError("ERR_IMAGE_METADATA_INCOMPLETE")
    if captured > now():
        raise ApiError("ERR_IMAGE_METADATA_INCOMPLETE")

    # (35) at most one PRIMARY image per work
    if image_role == "PRIMARY":
        for existing in images_of_artwork(artwork["id"]):
            if existing.get("role") == "PRIMARY":
                raise ApiError("ERR_PRIMARY_IMAGE_REQUIRED")

    record = new_record(
        {
            "artwork_id": artwork["id"],
            "role": image_role,
            "format": image_format,
            "pixel_long_edge": pixel_long,
            "pixel_short_edge": pixel_short,
            "file_bytes": file_bytes,
            "color_profile": color_profile,
            "capture_date": capture_date,
            "credit_line": credit_line,
            "checksum_sha256": checksum,
            "standard_ok": True,
        },
        versioned=False,
    )
    db.artwork_images[record["id"]] = record
    setv(
        artwork,
        "primary_image_count",
        sum(1 for i in images_of_artwork(artwork["id"]) if i.get("role") == "PRIMARY"),
    )
    return created(record)


@bp.get("/artworks/<artwork_id>/images")
def list_images(artwork_id):
    authenticate()
    require_roles("CallManager", "JuryChair", "Juror", "Artist")
    artwork = find("artworks", artwork_id)
    return listing(images_of_artwork(artwork["id"]))


# ---------------------------------------------------------------------------
# Condition reports
# ---------------------------------------------------------------------------


@bp.post("/artworks/<artwork_id>/condition-reports")
def file_condition_report(artwork_id):
    authenticate()
    require_roles("Registrar")
    artwork = find("artworks", artwork_id)
    exhibition = exhibition_of_artwork(artwork)
    payload = body()

    stage = v_enum(payload, "stage", CONDITION_STAGES)
    grade = v_enum(payload, "condition_grade", CONDITION_GRADES)
    photo_count = v_int(payload, "photo_count", minimum=1)
    damage_notes = v_str(payload, "damage_notes", required=False)
    if grade == "DAMAGED" and not damage_notes:
        bad("damage_notes is required when condition_grade is DAMAGED.")

    if stage == "INTAKE":
        # A re-inspection is legal: it supersedes the earlier INTAKE grade, so a
        # work that is already DELIVERED may be inspected again.
        if artwork["status"] not in ("ACCEPTED", "DELIVERED"):
            raise ApiError("ERR_ARTWORK_STATE_INVALID")
        if exhibition["status"] != "INSTALLATION":
            raise ApiError("ERR_EXHIBITION_PHASE_INVALID")
        clock = now()
        if clock < ts(exhibition, "delivery_window_start_at") or clock > ts(
            exhibition, "delivery_window_end_at"
        ):
            raise ApiError("ERR_DELIVERY_WINDOW_INVALID")

    record = new_record(
        {
            "artwork_id": artwork["id"],
            "stage": stage,
            "condition_grade": grade,
            "photo_count": photo_count,
            "damage_notes": damage_notes,
            "reported_by_user_id": user_id(),
        },
        versioned=False,
    )
    db.condition_reports[record["id"]] = record

    if stage == "INTAKE":
        if artwork["status"] == "ACCEPTED":
            set_artwork_status(artwork, "DELIVERED")
        latest = None
        for report in reports_of_artwork(artwork["id"]):
            if report.get("stage") == "INTAKE":
                latest = report
        setv(artwork, "intake_condition_grade", latest["condition_grade"])
        recompute_insurance(exhibition)
    return created(record)


@bp.get("/artworks/<artwork_id>/condition-reports")
def list_condition_reports(artwork_id):
    authenticate()
    require_roles("CallManager", "Registrar", "FinanceOfficer", "Artist")
    artwork = find("artworks", artwork_id)
    items = reports_of_artwork(artwork["id"])
    stage = qs("stage")
    if stage is not None:
        items = [r for r in items if r.get("stage") == stage]
    return listing(items)


# ---------------------------------------------------------------------------
# Waitlist promotion
# ---------------------------------------------------------------------------


@bp.post("/artworks/<artwork_id>/promotion")
def promote_artwork(artwork_id):
    authenticate()
    require_roles("JuryChair")
    artwork = find("artworks", artwork_id)
    exhibition = exhibition_of_artwork(artwork)
    payload = body()
    expected = v_int(payload, "expected_exhibition_version")

    if artwork["status"] != "WAITLISTED":
        raise ApiError("ERR_ARTWORK_STATE_INVALID")
    if exhibition["status"] not in ("RESULTS_PUBLISHED", "INSTALLATION"):
        raise ApiError("ERR_EXHIBITION_PHASE_INVALID")
    if int(exhibition["accepted_count"]) >= int(exhibition["acceptance_capacity"]):
        raise ApiError("ERR_ACCEPTANCE_CAPACITY_REACHED")
    if expected != exhibition["version"]:
        raise ApiError("ERR_STALE_VERSION")

    set_artwork_status(artwork, "ACCEPTED")
    recompute_entry_counts(entry_of(artwork))
    recompute_exhibition_counts(exhibition)
    touch(exhibition)
    flush()
    return ok(artwork_view(artwork))


# ---------------------------------------------------------------------------
# Installation plan / install / deinstall
# ---------------------------------------------------------------------------


@bp.post("/artworks/<artwork_id>/installation-plan")
def installation_plan(artwork_id):
    authenticate()
    require_roles("Registrar")
    artwork = find("artworks", artwork_id)
    exhibition = exhibition_of_artwork(artwork)
    payload = body()
    wall = fk(payload, "wall_segment_id", "wall_segments")
    if wall is None:
        req(payload, "wall_segment_id")
    span_start = v_num(payload, "span_start_cm")
    span_end = v_num(payload, "span_end_cm")
    expected = v_int(payload, "expected_wall_segment_version")
    if span_start >= span_end:
        bad("span_start_cm must be strictly less than span_end_cm.")

    if artwork["placement_status"] != "UNPLACED" or artwork["status"] != "DELIVERED":
        raise ApiError("ERR_ARTWORK_STATE_INVALID")
    if exhibition["status"] != "INSTALLATION":
        raise ApiError("ERR_EXHIBITION_PHASE_INVALID")
    if wall["exhibition_id"] != exhibition["id"]:
        raise ApiError("ERR_EXHIBITION_SCOPE_MISMATCH")
    if artwork.get("intake_condition_grade") == "DAMAGED":
        raise ApiError("ERR_ARTWORK_CONDITION_BLOCKED")
    if int(artwork["declared_value_cents"]) > int(
        exhibition["per_work_insurance_cap_cents"]
    ):
        raise ApiError("ERR_INSURANCE_COVERAGE_MISSING")
    if span_start < 0 or span_end > float(wall["length_cm"]):
        raise ApiError("ERR_WALL_SPAN_OUT_OF_BOUNDS")

    for neighbour in artworks_on_wall(wall["id"]):
        if neighbour["id"] == artwork["id"]:
            continue
        if neighbour.get("placement_status") not in ("PLANNED", "INSTALLED"):
            continue
        n_start = float(neighbour["span_start_cm"])
        n_end = float(neighbour["span_end_cm"])
        if (span_start - WALL_BUFFER_CM) < n_end and (
            span_end + WALL_BUFFER_CM
        ) > n_start:
            raise ApiError("ERR_WALL_SPAN_CONFLICT")

    if float(wall["loaded_weight_kg"]) + float(artwork["weight_kg"]) > float(
        wall["max_weight_kg"]
    ):
        raise ApiError("ERR_WALL_WEIGHT_EXCEEDED")

    if expected != wall["version"]:
        raise ApiError("ERR_STALE_VERSION")

    setv(artwork, "wall_segment_id", wall["id"])
    setv(artwork, "span_start_cm", num(span_start))
    setv(artwork, "span_end_cm", num(span_end))
    setv(artwork, "placement_status", "PLANNED")
    recompute_wall(wall)
    touch(wall)
    touch(artwork)
    flush()
    return ok(artwork_view(artwork))


@bp.post("/artworks/<artwork_id>/install")
def install_artwork(artwork_id):
    authenticate()
    require_roles("Registrar")
    artwork = find("artworks", artwork_id)
    exhibition = exhibition_of_artwork(artwork)
    if artwork["placement_status"] != "PLANNED":
        raise ApiError("ERR_ARTWORK_STATE_INVALID")
    if exhibition["status"] != "INSTALLATION":
        raise ApiError("ERR_EXHIBITION_PHASE_INVALID")
    set_placement(artwork, "INSTALLED")
    flush()
    return ok(artwork_view(artwork))


@bp.post("/artworks/<artwork_id>/deinstall")
def deinstall_artwork(artwork_id):
    authenticate()
    require_roles("Registrar")
    artwork = find("artworks", artwork_id)
    if artwork["placement_status"] not in ("PLANNED", "INSTALLED"):
        raise ApiError("ERR_ARTWORK_STATE_INVALID")
    if artwork["status"] in ("ON_VIEW", "RETURN_PENDING"):
        has_report = any(
            r.get("stage") == "DEINSTALL" for r in reports_of_artwork(artwork["id"])
        )
        if not has_report:
            raise ApiError("ERR_CONDITION_REPORT_REQUIRED")
    set_placement(artwork, "DEINSTALLED")
    flush()
    return ok(artwork_view(artwork))


# ---------------------------------------------------------------------------
# Returns
# ---------------------------------------------------------------------------


@bp.post("/artworks/<artwork_id>/return-shipment")
def return_shipment(artwork_id):
    authenticate()
    require_roles("Registrar")
    artwork = find("artworks", artwork_id)
    payload = body()
    method = v_enum(payload, "return_method", RETURN_METHODS)
    carrier = v_str(payload, "carrier", required=False)
    tracking = v_str(payload, "tracking_number", required=False)
    if method == "COURIER" and (not carrier or not tracking):
        bad("carrier and tracking_number are required for a COURIER return.")

    if artwork["status"] != "RETURN_PENDING":
        raise ApiError("ERR_ARTWORK_STATE_INVALID")
    has_report = any(
        r.get("stage") == "DEINSTALL" for r in reports_of_artwork(artwork["id"])
    )
    if not has_report:
        raise ApiError("ERR_CONDITION_REPORT_REQUIRED")

    setv(artwork, "return_method", method)
    setv(artwork, "return_carrier", carrier if method == "COURIER" else None)
    setv(artwork, "return_tracking_number", tracking if method == "COURIER" else None)
    set_artwork_status(artwork, "RETURN_SCHEDULED")
    flush()
    return ok(artwork_view(artwork))


@bp.post("/artworks/<artwork_id>/return-completion")
def return_completion(artwork_id):
    authenticate()
    require_roles("Registrar")
    artwork = find("artworks", artwork_id)
    if artwork["status"] != "RETURN_SCHEDULED":
        raise ApiError("ERR_ARTWORK_STATE_INVALID")
    set_artwork_status(artwork, "RETURNED")
    flush()
    return ok(artwork_view(artwork))
