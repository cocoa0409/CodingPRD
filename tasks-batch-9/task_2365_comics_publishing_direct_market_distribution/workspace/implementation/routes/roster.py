"""Creators, titles and creative assignments (PRD 3.1, 3.9)."""

from flask import Blueprint

from core import (
    ASSIGNMENT_STATUSES,
    CRAFTS,
    MAX_NEGOTIATION_ROUNDS,
    TITLE_STATUSES,
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
    touch,
    v_craft_list,
    v_datetime,
    v_enum,
    v_int,
    v_str,
)
import services as svc

creators_bp = Blueprint("creators", __name__, url_prefix="/comics/creators")
titles_bp = Blueprint("titles", __name__, url_prefix="/comics/titles")
assignments_bp = Blueprint(
    "assignments", __name__, url_prefix="/comics/creative-assignments"
)

STAFFABLE_TITLE_STATUSES = ("GREENLIT", "IN_PRODUCTION", "PUBLISHING")


# ---------------------------------------------------------------------------
# Creators
# ---------------------------------------------------------------------------


@creators_bp.post("")
def create_creator():
    auth(("EditorInChief", "ManagingEditor"))
    body = get_body()
    full_name = v_str(body, "full_name", required=True, min_len=1, max_len=120)
    crafts = v_craft_list(body, "crafts", required=True)
    page_rate = v_int(body, "default_page_rate_cents", required=True, minimum=0)

    row = db.new_row(
        full_name=full_name,
        crafts=list(crafts),
        default_page_rate_cents=page_rate,
        active_assignment_count=0,
    )
    db.creators[row["id"]] = row
    return created_row(svc.creator_json, row)


@creators_bp.get("")
def list_creators():
    auth(("EditorInChief", "ManagingEditor", "RoyaltyAccountant"))
    craft = q_enum("craft", CRAFTS)
    rows = ordered(db.creators)
    if craft is not None:
        rows = [r for r in rows if craft in r["crafts"]]
    window, meta = page(rows)
    return ok_list(svc.creator_json, window, meta)


@creators_bp.get("/<creator_id>")
def read_creator(creator_id):
    auth(("EditorInChief", "ManagingEditor", "RoyaltyAccountant", "Creator"))
    return ok_row(svc.creator_json, svc.get_creator(creator_id))


@creators_bp.get("/<creator_id>/creative-assignments")
def list_creator_assignments(creator_id):
    auth(("EditorInChief", "ManagingEditor", "RoyaltyAccountant", "Creator"))
    status = q_enum("status", ASSIGNMENT_STATUSES)
    creator = svc.get_creator(creator_id)
    rows = svc.creator_assignments(creator["id"])
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    window, meta = page(rows)
    return ok_list(svc.assignment_json, window, meta)


# ---------------------------------------------------------------------------
# Titles
# ---------------------------------------------------------------------------


@titles_bp.post("")
def create_title():
    auth(("EditorInChief",))
    body = get_body()
    name = v_str(body, "name", required=True, min_len=1, max_len=160)
    planned_issue_count = v_int(
        body, "planned_issue_count", required=True, minimum=1, maximum=24
    )
    royalty_pool_bps = v_int(body, "royalty_pool_bps", required=True, minimum=1, maximum=3000)
    cover_participation_bps = v_int(
        body, "cover_participation_bps", required=True, minimum=0, maximum=3000
    )
    if any(t["name"] == name for t in db.titles.values()):
        bad("A title with name '%s' already exists." % name)

    row = db.new_row(
        name=name,
        planned_issue_count=planned_issue_count,
        royalty_pool_bps=royalty_pool_bps,
        cover_participation_bps=cover_participation_bps,
        status="PITCHED",
        greenlit_at=None,
        committed_share_bps=0,
        production_cost_cents=0,
        royalty_accrued_cents=0,
        cancel_reason=None,
    )
    db.titles[row["id"]] = row
    return created_row(svc.title_json, row)


@titles_bp.get("")
def list_titles():
    auth(("EditorInChief", "ManagingEditor", "SalesDirector", "RoyaltyAccountant"))
    status = q_enum("status", TITLE_STATUSES)
    rows = ordered(db.titles)
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    window, meta = page(rows)
    return ok_list(svc.title_json, window, meta)


@titles_bp.get("/<title_id>")
def read_title(title_id):
    auth((
        "EditorInChief",
        "ManagingEditor",
        "SalesDirector",
        "RoyaltyAccountant",
        "Creator",
    ))
    return ok_row(svc.title_json, svc.get_title(title_id))


@titles_bp.post("/<title_id>/greenlight")
def greenlight_title(title_id):
    auth(("EditorInChief",))
    title = svc.get_title(title_id)
    if title["status"] != "PITCHED":
        raise ApiError(
            "ERR_INVALID_STATE",
            "A title may only be greenlit from PITCHED, not %s." % title["status"],
        )
    apply_fields(title, status="GREENLIT", greenlit_at=db.now())
    return ok_row(svc.title_json, title)


@titles_bp.post("/<title_id>/cancel")
def cancel_title(title_id):
    auth(("EditorInChief",))
    body = get_body()
    reason = v_str(body, "reason", required=True, min_len=1, max_len=500)
    title = svc.get_title(title_id)
    if title["status"] not in ("PITCHED", "GREENLIT", "IN_PRODUCTION", "PUBLISHING"):
        raise ApiError(
            "ERR_INVALID_STATE",
            "A %s title cannot be cancelled." % title["status"],
        )
    apply_fields(title, status="CANCELLED", cancel_reason=reason)
    svc.title_cancel_cascade(title)
    return ok_row(svc.title_json, title)


@titles_bp.post("/<title_id>/creative-assignments")
def create_assignment(title_id):
    auth(("EditorInChief",))
    body = get_body()
    creator_id = v_str(body, "creator_id", required=True, min_len=1)
    craft = v_enum(body, "craft", CRAFTS, required=True)
    page_rate_cents = v_int(body, "page_rate_cents", required=True, minimum=0)
    royalty_share_bps = v_int(
        body, "royalty_share_bps", required=True, minimum=0, maximum=10000
    )
    booking_start = v_datetime(body, "booking_start_date", required=True)
    booking_end = v_datetime(body, "booking_end_date", required=True)
    advance_cents = v_int(body, "advance_cents", minimum=0, default=0)
    expected_title_version = v_int(body, "expected_title_version", required=True)
    if booking_end <= booking_start:
        bad("Field 'booking_end_date' must be strictly after 'booking_start_date'.")

    title = svc.get_title(title_id)
    creator = svc.get_creator(creator_id)

    if expected_title_version != title["version"]:
        raise ApiError(
            "ERR_STALE_TITLE_VERSION",
            "Expected title version %s but the title is at version %s."
            % (expected_title_version, title["version"]),
        )
    if title["status"] not in STAFFABLE_TITLE_STATUSES:
        raise ApiError(
            "ERR_TITLE_NOT_GREENLIT",
            "A %s title cannot be staffed." % title["status"],
        )

    for other in svc.creator_assignments(creator["id"]):
        if other["status"] not in svc.ACTIVE_ASSIGNMENT_STATUSES:
            continue
        other_start = other["booking_start_date"]
        other_end = other["booking_end_date"]
        if fmt_dt(booking_start) < other_end and other_start < fmt_dt(booking_end):
            raise ApiError(
                "ERR_CREATOR_DOUBLE_BOOKED",
                "The creator's studio time already carries an overlapping booking.",
            )

    if craft not in creator["crafts"]:
        raise ApiError(
            "ERR_CRAFT_NOT_SUPPORTED",
            "Creator does not declare the craft %s." % craft,
        )

    row = db.new_row(
        title_id=title["id"],
        creator_id=creator["id"],
        craft=craft,
        page_rate_cents=page_rate_cents,
        royalty_share_bps=royalty_share_bps,
        booking_start_date=fmt_dt(booking_start),
        booking_end_date=fmt_dt(booking_end),
        advance_cents=advance_cents,
        unrecouped_advance_cents=advance_cents,
        status="PROPOSED",
        negotiation_round=1,
        counter_page_rate_cents=None,
        counter_royalty_share_bps=None,
        terminated_reason=None,
    )
    db.assignments[row["id"]] = row
    svc.recompute_creator_active_count(creator)
    touch(title)
    return created_row(svc.assignment_json, row)


@titles_bp.get("/<title_id>/creative-assignments")
def list_title_assignments(title_id):
    auth(("EditorInChief", "ManagingEditor", "RoyaltyAccountant"))
    craft = q_enum("craft", CRAFTS)
    status = q_enum("status", ASSIGNMENT_STATUSES)
    title = svc.get_title(title_id)
    rows = svc.title_assignments(title["id"])
    if craft is not None:
        rows = [r for r in rows if r["craft"] == craft]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    window, meta = page(rows)
    return ok_list(svc.assignment_json, window, meta)


# ---------------------------------------------------------------------------
# Creative assignments
# ---------------------------------------------------------------------------


@assignments_bp.get("/<assignment_id>")
def read_assignment(assignment_id):
    auth(("EditorInChief", "ManagingEditor", "RoyaltyAccountant", "Creator"))
    return ok_row(svc.assignment_json, svc.get_assignment(assignment_id))


def _own_assignment(assignment, user_id):
    if assignment["creator_id"] != user_id:
        raise ApiError(
            "ERR_FORBIDDEN_RESOURCE",
            "This assignment belongs to another creator.",
        )


@assignments_bp.post("/<assignment_id>/counter")
def counter_assignment(assignment_id):
    user_id, _role = auth(("Creator",))
    body = get_body()
    counter_page_rate = v_int(body, "counter_page_rate_cents", required=True, minimum=0)
    counter_share = v_int(
        body, "counter_royalty_share_bps", required=True, minimum=0, maximum=10000
    )
    assignment = svc.get_assignment(assignment_id)
    _own_assignment(assignment, user_id)
    if assignment["status"] != "PROPOSED":
        raise ApiError(
            "ERR_INVALID_STATE",
            "Only a PROPOSED assignment may be countered, not %s." % assignment["status"],
        )
    apply_fields(
        assignment,
        status="COUNTERED",
        counter_page_rate_cents=counter_page_rate,
        counter_royalty_share_bps=counter_share,
    )
    return ok_row(svc.assignment_json, assignment)


@assignments_bp.post("/<assignment_id>/repropose")
def repropose_assignment(assignment_id):
    auth(("EditorInChief",))
    body = get_body()
    page_rate_cents = v_int(body, "page_rate_cents", required=True, minimum=0)
    royalty_share_bps = v_int(
        body, "royalty_share_bps", required=True, minimum=0, maximum=10000
    )
    assignment = svc.get_assignment(assignment_id)
    if assignment["status"] != "COUNTERED":
        raise ApiError(
            "ERR_INVALID_STATE",
            "Only a COUNTERED assignment may be reproposed, not %s."
            % assignment["status"],
        )
    if assignment["negotiation_round"] >= MAX_NEGOTIATION_ROUNDS:
        raise ApiError(
            "ERR_NEGOTIATION_ROUNDS_EXHAUSTED",
            "The three permitted negotiation rounds are exhausted.",
        )
    apply_fields(
        assignment,
        status="PROPOSED",
        page_rate_cents=page_rate_cents,
        royalty_share_bps=royalty_share_bps,
        counter_page_rate_cents=None,
        counter_royalty_share_bps=None,
        negotiation_round=assignment["negotiation_round"] + 1,
    )
    return ok_row(svc.assignment_json, assignment)


@assignments_bp.post("/<assignment_id>/accept")
def accept_assignment(assignment_id):
    user_id, _role = auth(("Creator",))
    assignment = svc.get_assignment(assignment_id)
    _own_assignment(assignment, user_id)
    if assignment["status"] != "PROPOSED":
        raise ApiError(
            "ERR_INVALID_STATE",
            "Only a PROPOSED assignment may be accepted, not %s." % assignment["status"],
        )
    title = svc.get_title(assignment["title_id"])
    if title["status"] not in STAFFABLE_TITLE_STATUSES:
        raise ApiError(
            "ERR_INVALID_STATE",
            "The title is %s, so its roster can no longer be committed." % title["status"],
        )
    if assignment["craft"] != "COVER":
        ceiling = 10000 - title["cover_participation_bps"]
        if title["committed_share_bps"] + assignment["royalty_share_bps"] > ceiling:
            raise ApiError(
                "ERR_ROYALTY_SHARE_POOL_EXCEEDED",
                "Accepting this assignment would push the committed share past %d bps."
                % ceiling,
            )
    apply_fields(assignment, status="ACCEPTED")
    svc.recompute_title_committed_share(title)
    return ok_row(svc.assignment_json, assignment)


@assignments_bp.post("/<assignment_id>/terminate")
def terminate_assignment(assignment_id):
    auth(("EditorInChief",))
    body = get_body()
    reason = v_str(body, "reason", required=True, min_len=1, max_len=500)
    assignment = svc.get_assignment(assignment_id)
    if assignment["status"] not in ("PROPOSED", "COUNTERED", "ACCEPTED", "ACTIVE"):
        raise ApiError(
            "ERR_INVALID_STATE",
            "A %s assignment cannot be terminated." % assignment["status"],
        )
    if any(
        s["status"] in ("IN_PROGRESS", "DELIVERED")
        for s in svc.assignment_stages(assignment["id"])
    ):
        raise ApiError(
            "ERR_INVALID_STATE",
            "Work in flight on this assignment must be resolved before termination.",
        )
    apply_fields(assignment, status="TERMINATED", terminated_reason=reason)
    svc.recompute_title_committed_share(svc.get_title(assignment["title_id"]))
    creator = db.creators.get(assignment["creator_id"])
    if creator is not None:
        svc.recompute_creator_active_count(creator)
    return ok_row(svc.assignment_json, assignment)


@assignments_bp.get("/<assignment_id>/production-stages")
def list_assignment_stages(assignment_id):
    auth(("EditorInChief", "ManagingEditor", "Creator"))
    from core import STAGE_STATUSES

    status = q_enum("status", STAGE_STATUSES)
    assignment = svc.get_assignment(assignment_id)
    rows = svc.assignment_stages(assignment["id"])
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    window, meta = page(rows)
    return ok_list(svc.stage_json, window, meta)
