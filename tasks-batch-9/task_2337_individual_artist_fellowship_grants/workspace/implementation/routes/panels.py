"""Panel, Panelist, ConflictDeclaration and Review endpoints."""

from flask import Blueprint

import constants as C
import db
import middleware as mw
import response
import validation as v
from errors import ApiError
from routes import support as sup
from services import calc, cascade, derive

bp = Blueprint("panels", __name__)

PO = (mw.PROGRAM_OFFICER,)
PANELIST_ONLY = (mw.PANELIST,)
PANELIST_OR_PO = (mw.PANELIST, mw.PROGRAM_OFFICER)
ALL = sup.ALL_ROLES

ACTIVE_PANEL_STATUSES = ("CHARTERED", "SCORING", "DELIBERATING", "SLATE_SUBMITTED")


def _overlaps(a, b):
    """Half-open [start, end) intersection."""
    a_start = db.dt_of(a, "deliberation_window_start")
    a_end = db.dt_of(a, "deliberation_window_end")
    b_start = db.dt_of(b, "deliberation_window_start")
    b_end = db.dt_of(b, "deliberation_window_end")
    return a_start < b_end and b_start < a_end


# ================================================================= panels


@bp.post("/grants/panels")
def create_panel():
    mw.authorize(PO)
    data = v.body()
    cycle_id = v.req_id(data, "cycle_id")
    discipline_id = v.req_id(data, "discipline_category_id")
    required_seats = v.req_int(data, "required_seats", minimum=3)
    required_regions = v.req_code_list(data, "required_regions", C.REGIONS)
    window_start = v.req_dt(data, "deliberation_window_start")
    window_end = v.req_dt(data, "deliberation_window_end")
    if db.parse_dt(window_end) <= db.parse_dt(window_start):
        v.bad("deliberation_window_end must be after deliberation_window_start.")

    sup.resolve_fk("cycles", cycle_id)
    discipline = sup.resolve_fk("disciplines", discipline_id)
    if discipline["cycle_id"] != cycle_id:
        raise ApiError(
            "ERR_DISCIPLINE_CATEGORY_NOT_FOUND",
            "That discipline category does not belong to the named cycle.",
        )

    panel = db.insert(
        "panels",
        {
            "cycle_id": cycle_id,
            "discipline_category_id": discipline_id,
            "required_seats": required_seats,
            "required_regions": required_regions,
            "deliberation_window_start": window_start,
            "deliberation_window_end": window_end,
            "status": "FORMING",
            "round_number": 0,
            "seated_count": 0,
            "region_coverage_count": 0,
            "quorum_min_reviews": calc.quorum_min_reviews(required_seats),
            "quorum_met": False,
            "blocking_conflict_count": 0,
            "readiness_score": 0.0,
            "reopen_required": False,
            "assigned_application_count": 0,
            "chartered_by": None,
            "slate_submitted_at": None,
        },
    )
    derive.refresh_panel(panel)
    return response.obj(db.public(panel), 201)


@bp.get("/grants/panels/<panel_id>")
def read_panel(panel_id):
    mw.authorize(ALL)
    return response.obj(db.public(sup.resolve("panels", panel_id)))


@bp.get("/grants/panels")
def list_panels():
    mw.authorize(ALL)
    rows = db.rows("panels")
    rows = sup.eq(rows, "cycle_id", v.query_str("cycle_id"))
    rows = sup.eq(rows, "discipline_category_id", v.query_str("discipline_category_id"))
    rows = sup.eq(rows, "status", v.query_str("status"))
    return sup.listed(rows)


@bp.post("/grants/panels/<panel_id>/charter")
def charter_panel(panel_id):
    user_id, _ = mw.authorize(PO)
    panel = sup.resolve("panels", panel_id)
    if panel["status"] != "FORMING":
        raise ApiError("ERR_PANEL_STATE_INVALID")

    cycle = derive.cycle_of(panel)
    discipline = derive.discipline_of(panel)
    if cycle["status"] != "PANEL_REVIEW":
        raise ApiError("ERR_CYCLE_STATE_INVALID")
    if cycle["posture"] == "FROZEN":
        raise ApiError("ERR_CYCLE_POSTURE_FROZEN")

    candidates = [
        a
        for a in derive.applications_of_cycle(cycle["id"])
        if a["discipline_category_id"] == panel["discipline_category_id"]
        and a["status"] == "ELIGIBLE"
        and a["assigned_panel_id"] is None
    ]
    if any(a["anonymity_status"] == "BREACHED" for a in candidates):
        raise ApiError("ERR_ANONYMITY_BREACH_UNRESOLVED")

    derive.refresh_panel(panel)
    seated = [p for p in derive.panelists_of_panel(panel["id"]) if p["status"] == "SEATED"]
    has_expert = any(
        discipline["code"] in (p.get("expertise_codes") or []) for p in seated
    )
    if (
        calc.D(panel["readiness_score"]) < calc.CHARTER_READINESS_MIN
        or not has_expert
    ):
        raise ApiError("ERR_PANEL_NOT_READY")

    concurrent = [
        other
        for other in db.rows(
            "panels",
            lambda r, d=panel["discipline_category_id"]: r["discipline_category_id"] == d,
        )
        if other["id"] != panel["id"]
        and other["status"] in ACTIVE_PANEL_STATUSES
        and _overlaps(panel, other)
    ]
    if len(concurrent) + 1 > int(discipline["max_concurrent_panels"]):
        raise ApiError("ERR_DISCIPLINE_PANEL_CAPACITY")

    derive.set_fields(panel, status="CHARTERED", chartered_by=user_id)
    for application in candidates:
        if application["anonymity_status"] not in ("SEALED", "REDACTED"):
            continue
        derive.set_fields(
            application, status="UNDER_REVIEW", assigned_panel_id=panel["id"]
        )
    derive.refresh_panel(panel)
    derive.refresh_discipline(discipline)
    derive.refresh_cycle(cycle)
    return response.obj(db.public(panel))


@bp.post("/grants/panels/<panel_id>/open-round")
def open_round(panel_id):
    mw.authorize(PO)
    panel = sup.resolve("panels", panel_id)
    status = panel["status"]
    if status not in ("CHARTERED", "DELIBERATING"):
        raise ApiError("ERR_PANEL_STATE_INVALID")

    cycle = derive.cycle_of(panel)
    if status == "CHARTERED":
        if int(panel["assigned_application_count"]) < 1:
            raise ApiError(
                "ERR_PANEL_STATE_INVALID", "The panel has no assigned application."
            )
    else:
        if not panel["reopen_required"]:
            raise ApiError(
                "ERR_PANEL_STATE_INVALID", "No further round is required for this panel."
            )
    if int(panel["round_number"]) >= int(cycle["max_review_rounds"]):
        raise ApiError(
            "ERR_PANEL_STATE_INVALID", "The cycle permits no further review round."
        )

    new_round = int(panel["round_number"]) + 1
    derive.set_fields(
        panel, status="SCORING", round_number=new_round, reopen_required=False
    )

    assigned = db.rows(
        "applications", lambda r, p=panel["id"]: r.get("assigned_panel_id") == p
    )
    if status == "DELIBERATING":
        for application in assigned:
            for review in derive.reviews_of_application(application["id"]):
                if (
                    review["status"] in ("SUBMITTED", "INVALIDATED")
                    and int(review["round_number"]) < new_round
                ):
                    derive.set_fields(review, status="SUPERSEDED")
            derive.refresh_application_scores(application)
    derive.refresh_panel(panel)
    return response.obj(db.public(panel))


@bp.post("/grants/panels/<panel_id>/close-round")
def close_round(panel_id):
    mw.authorize(PO)
    panel = sup.resolve("panels", panel_id)
    if panel["status"] != "SCORING":
        raise ApiError("ERR_PANEL_STATE_INVALID")

    cycle = derive.cycle_of(panel)
    if cycle["status"] != "PANEL_REVIEW":
        raise ApiError("ERR_CYCLE_STATE_INVALID")

    assigned = db.rows(
        "applications", lambda r, p=panel["id"]: r.get("assigned_panel_id") == p
    )
    under_review = [a for a in assigned if a["status"] == "UNDER_REVIEW"]
    quorum = int(panel["quorum_min_reviews"])
    for application in under_review:
        if int(application["valid_review_count"]) < quorum:
            raise ApiError("ERR_INSUFFICIENT_REVIEWS")

    round_number = int(panel["round_number"])
    reopen = False
    for application in under_review:
        _, _, _, spread = derive.refresh_application_scores(
            application, include_final=True
        )
        derive.set_fields(application, review_round_number=round_number)
        if calc.spread_requires_reopen(spread):
            reopen = True

    reopen = reopen and round_number < int(cycle["max_review_rounds"])
    derive.set_fields(panel, status="DELIBERATING", reopen_required=reopen)
    if not reopen:
        for application in under_review:
            derive.set_fields(application, status="SCORED")
        derive.refresh_discipline_by_id(panel["discipline_category_id"])
    derive.refresh_panel(panel)
    return response.obj(db.public(panel))


@bp.post("/grants/panels/<panel_id>/slate")
def submit_slate(panel_id):
    user_id, _ = mw.authorize(PANELIST_ONLY, entity_backed=True)
    data = v.body()
    ranked = data.get("ranked_application_ids")
    if not isinstance(ranked, list):
        v.bad("ranked_application_ids must be an array.")
    for item in ranked:
        if not isinstance(item, str) or not item.strip():
            v.bad("ranked_application_ids entries must be strings.")
    if len(set(ranked)) != len(ranked):
        v.bad("ranked_application_ids must not contain duplicates.")
    expected_version = v.req_int(data, "expected_panel_version", minimum=0)

    panel = sup.resolve("panels", panel_id)
    listed = [sup.resolve_fk("applications", app_id) for app_id in ranked]

    panelist = db.get("panelists", user_id)
    if (
        panelist is None
        or panelist["panel_id"] != panel["id"]
        or panelist["status"] != "SEATED"
        or not panelist["is_chair"]
    ):
        raise ApiError("ERR_NOT_PANEL_CHAIR")

    if expected_version != int(panel["version"]):
        raise ApiError("ERR_STALE_PANEL_VERSION")

    if panel["status"] != "DELIBERATING":
        raise ApiError("ERR_PANEL_STATE_INVALID")

    cycle = derive.cycle_of(panel)
    if cycle["status"] != "BOARD_REVIEW":
        raise ApiError("ERR_CYCLE_STATE_INVALID")
    if panel["reopen_required"]:
        raise ApiError("ERR_SCORE_SPREAD_REQUIRES_ANOTHER_ROUND")

    scored = [
        a["id"]
        for a in db.rows(
            "applications", lambda r, p=panel["id"]: r.get("assigned_panel_id") == p
        )
        if a["status"] == "SCORED"
    ]
    if any(app_id not in ranked for app_id in scored):
        raise ApiError("ERR_INCOMPLETE_SLATE")

    for application in listed:
        if application.get("assigned_panel_id") != panel["id"]:
            raise ApiError("ERR_APPLICATION_NOT_ON_PANEL")

    for index, application in enumerate(listed):
        db.insert(
            "slots",
            {
                "panel_id": panel["id"],
                "application_id": application["id"],
                "cycle_id": panel["cycle_id"],
                "rank": index + 1,
                "status": "PROPOSED",
                "board_action_by": None,
                "struck_reason_code": None,
                "awarded_amount_cents": None,
            },
        )
    derive.set_fields(
        panel, status="SLATE_SUBMITTED", slate_submitted_at=db.iso3(db.now())
    )
    db.mark(panel)  # an accepted slate always advances Panel.version by one
    # A slate transmission is a status transition on the panel; the slots it mints
    # are not created "at the client's request" (§2.5), so §4 gives 200 here.
    return response.obj(db.public(panel))


# ============================================================== panelists


@bp.post("/grants/panelists")
def create_panelist():
    mw.authorize(PO)
    data = v.body()
    panel_id = v.req_id(data, "panel_id")
    person_email = v.req_str(data, "person_email")
    full_name = v.req_str(data, "full_name")
    region = v.req_enum(data, "region", C.REGIONS)
    expertise = v.req_code_list(data, "expertise_codes", C.DISCIPLINE_CODES)
    is_chair = v.opt_bool(data, "is_chair", False)

    panel = sup.resolve_fk("panels", panel_id)
    if panel["status"] != "FORMING":
        raise ApiError("ERR_PANEL_STATE_INVALID")

    for other in derive.panelists_of_panel(panel_id):
        if other["person_email"] == person_email:
            v.bad("person_email is already nominated to this panel.")
        if is_chair and other["is_chair"]:
            v.bad("This panel already has a chair.")

    panelist = db.insert(
        "panelists",
        {
            "panel_id": panel_id,
            "person_email": person_email,
            "full_name": full_name,
            "region": region,
            "expertise_codes": expertise,
            "is_chair": is_chair,
            "status": "NOMINATED",
            "recused_application_ids": [],
            "review_submitted_count": 0,
            "seated_at": None,
        },
    )
    return response.obj(db.public(panelist), 201)


@bp.get("/grants/panelists/<panelist_id>")
def read_panelist(panelist_id):
    mw.authorize(ALL)
    return response.obj(db.public(sup.resolve("panelists", panelist_id)))


@bp.get("/grants/panelists")
def list_panelists():
    mw.authorize(ALL)
    rows = db.rows("panelists")
    rows = sup.eq(rows, "panel_id", v.query_str("panel_id"))
    rows = sup.eq(rows, "status", v.query_str("status"))
    rows = sup.eq(rows, "region", v.query_str("region"))
    rows = sup.eq(rows, "person_email", v.query_str("person_email"))
    return sup.listed(rows)


@bp.post("/grants/panelists/<panelist_id>/seat")
def seat_panelist(panelist_id):
    mw.authorize(PO)
    panelist = sup.resolve("panelists", panelist_id)
    if panelist["status"] != "NOMINATED":
        raise ApiError("ERR_PANELIST_STATE_INVALID")

    panel = db.get("panels", panelist["panel_id"])
    if panel["status"] != "FORMING":
        raise ApiError("ERR_PANEL_STATE_INVALID")
    if not (panelist.get("expertise_codes") or []):
        v.bad("The panelist carries no expertise code.")

    for other in db.rows(
        "panelists", lambda r, e=panelist["person_email"]: r["person_email"] == e
    ):
        if other["id"] == panelist["id"] or other["status"] != "SEATED":
            continue
        other_panel = db.get("panels", other["panel_id"])
        if other_panel is None or other_panel["id"] == panel["id"]:
            continue
        if other_panel["cycle_id"] != panel["cycle_id"]:
            continue
        if _overlaps(panel, other_panel):
            raise ApiError("ERR_PANELIST_WINDOW_CONFLICT")

    derive.set_fields(panelist, status="SEATED", seated_at=db.iso3(db.now()))
    derive.refresh_panel(panel)
    return response.obj(db.public(panelist))


@bp.post("/grants/panelists/<panelist_id>/resign")
def resign_panelist(panelist_id):
    mw.authorize(PO)
    panelist = sup.resolve("panelists", panelist_id)
    if panelist["status"] == "RESIGNED":
        raise ApiError("ERR_PANELIST_STATE_INVALID")

    panel = db.get("panels", panelist["panel_id"])
    if panelist["status"] in C.OCCUPYING_PANELIST_STATUSES:
        if panel["status"] not in ("FORMING", "CHARTERED", "SCORING", "DELIBERATING"):
            raise ApiError("ERR_PANEL_STATE_INVALID")

    cascade.resign_panelist(panelist)
    return response.obj(db.public(panelist))


# ============================================================== conflicts


@bp.post("/grants/conflicts")
def create_conflict():
    mw.authorize(PANELIST_OR_PO, entity_backed=True)
    data = v.body()
    panelist_id = v.req_id(data, "panelist_id")
    application_id = v.req_id(data, "application_id")
    relationship = v.req_enum(data, "relationship_type", C.RELATIONSHIP_TYPES)
    note = v.req_str(data, "disclosure_note")

    sup.resolve_fk("panelists", panelist_id)
    sup.resolve_fk("applications", application_id)

    if derive.conflict_for(panelist_id, application_id) is not None:
        raise ApiError("ERR_DUPLICATE_CONFLICT")

    severity = (
        "MANDATORY_BLOCK"
        if relationship in C.MANDATORY_RELATIONSHIPS
        else "DISCRETIONARY"
    )
    conflict = db.insert(
        "conflicts",
        {
            "panelist_id": panelist_id,
            "application_id": application_id,
            "relationship_type": relationship,
            "disclosure_note": note,
            "severity": severity,
            "status": "DECLARED",
            "screened_by": None,
            "override_justification": None,
        },
    )
    return response.obj(db.public(conflict), 201)


@bp.get("/grants/conflicts/<conflict_declaration_id>")
def read_conflict(conflict_declaration_id):
    mw.authorize(ALL)
    return response.obj(db.public(sup.resolve("conflicts", conflict_declaration_id)))


@bp.get("/grants/conflicts")
def list_conflicts():
    mw.authorize(ALL)
    rows = db.rows("conflicts")
    rows = sup.eq(rows, "panelist_id", v.query_str("panelist_id"))
    rows = sup.eq(rows, "application_id", v.query_str("application_id"))
    rows = sup.eq(rows, "status", v.query_str("status"))
    rows = sup.eq(rows, "severity", v.query_str("severity"))
    return sup.listed(rows)


@bp.post("/grants/conflicts/<conflict_declaration_id>/screen")
def screen_conflict(conflict_declaration_id):
    user_id, _ = mw.authorize(PO)
    data = v.body()
    disposition = v.req_enum(data, "disposition", C.CONFLICT_DISPOSITIONS)
    justification = v.opt_str(data, "override_justification")

    conflict = sup.resolve("conflicts", conflict_declaration_id)
    if conflict["status"] != "DECLARED":
        raise ApiError("ERR_CONFLICT_STATE_INVALID")

    panelist = db.get("panelists", conflict["panelist_id"])
    panel = db.get("panels", panelist["panel_id"]) if panelist else None
    if panel is None or panel["status"] == "DISSOLVED":
        raise ApiError("ERR_PANEL_STATE_INVALID")

    if disposition == "WAIVED":
        if conflict["severity"] != "DISCRETIONARY":
            raise ApiError("ERR_MANDATORY_CONFLICT_NOT_WAIVABLE")
        if justification is None or len(justification.strip()) < 20:
            v.bad("override_justification must be at least 20 characters.")
        derive.set_fields(
            conflict,
            status="WAIVED",
            screened_by=user_id,
            override_justification=justification,
        )
    else:
        cascade.apply_block(conflict, user_id)
    return response.obj(db.public(conflict))


@bp.post("/grants/conflicts/<conflict_declaration_id>/waive-override")
def waive_override(conflict_declaration_id):
    user_id, _ = mw.authorize(PO)
    data = v.body()
    justification = v.req_str(data, "override_justification", min_len=20)

    conflict = sup.resolve("conflicts", conflict_declaration_id)
    if conflict["status"] != "BLOCKING":
        raise ApiError("ERR_CONFLICT_STATE_INVALID")

    panelist = db.get("panelists", conflict["panelist_id"])
    panel = db.get("panels", panelist["panel_id"]) if panelist else None
    if panel is None or panel["status"] not in (
        "CHARTERED",
        "SCORING",
        "DELIBERATING",
        "SLATE_SUBMITTED",
    ):
        raise ApiError("ERR_PANEL_STATE_INVALID")
    if conflict["severity"] != "DISCRETIONARY":
        raise ApiError("ERR_MANDATORY_CONFLICT_NOT_WAIVABLE")

    cascade.release_block(conflict, user_id, justification)
    return response.obj(db.public(conflict))


# ================================================================ reviews


@bp.post("/grants/reviews")
def create_review():
    user_id, _ = mw.authorize(PANELIST_ONLY, entity_backed=True)
    data = v.body()
    application_id = v.req_id(data, "application_id")
    panelist_id = v.req_id(data, "panelist_id")
    scores = {}
    for field in C.SCORE_FIELDS:
        scores[field] = v.req_int(data, field, minimum=0, maximum=10)
    comments = v.opt_str(data, "comments")

    application = sup.resolve_fk("applications", application_id)
    panelist = sup.resolve_fk("panelists", panelist_id)

    if panelist_id != user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")

    if derive.has_blocking_conflict(panelist_id, application_id):
        raise ApiError("ERR_CONFLICT_BLOCKS_REVIEW")

    panel = db.get("panels", application.get("assigned_panel_id"))
    if panel is not None:
        round_number = int(panel["round_number"])
        for review in derive.reviews_of_application(application_id):
            if (
                review["panelist_id"] == panelist_id
                and int(review["round_number"]) == round_number
                and review["status"] != "SUPERSEDED"
            ):
                raise ApiError("ERR_DUPLICATE_REVIEW")

    if (
        panel is None
        or panelist["panel_id"] != panel["id"]
        or panelist["status"] != "SEATED"
    ):
        raise ApiError("ERR_PANELIST_NOT_ON_PANEL")

    review = db.insert(
        "reviews",
        {
            "application_id": application_id,
            "panelist_id": panelist_id,
            "round_number": int(panel["round_number"]),
            "artistic_excellence": scores["artistic_excellence"],
            "work_sample_quality": scores["work_sample_quality"],
            "career_impact": scores["career_impact"],
            "public_value": scores["public_value"],
            "comments": comments,
            "weighted_score": None,
            "status": "DRAFT",
            "invalidation_reason": None,
            "submitted_at": None,
        },
    )
    return response.obj(db.public(review), 201)


@bp.get("/grants/reviews/<review_id>")
def read_review(review_id):
    mw.authorize(ALL)
    return response.obj(db.public(sup.resolve("reviews", review_id)))


@bp.get("/grants/reviews")
def list_reviews():
    mw.authorize(ALL)
    round_number = v.query_int("round_number")
    rows = db.rows("reviews")
    rows = sup.eq(rows, "application_id", v.query_str("application_id"))
    rows = sup.eq(rows, "panelist_id", v.query_str("panelist_id"))
    rows = sup.eq(rows, "status", v.query_str("status"))
    rows = sup.eq(rows, "round_number", round_number)
    return sup.listed(rows)


@bp.post("/grants/reviews/<review_id>/submit")
def submit_review(review_id):
    user_id, _ = mw.authorize(PANELIST_ONLY, entity_backed=True)
    review = sup.resolve("reviews", review_id)
    if review["panelist_id"] != user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")
    if review["status"] != "DRAFT":
        raise ApiError("ERR_REVIEW_STATE_INVALID")

    application = db.get("applications", review["application_id"])
    panelist = db.get("panelists", review["panelist_id"])
    panel = db.get("panels", application.get("assigned_panel_id"))
    if panel is None or panel["status"] != "SCORING":
        raise ApiError("ERR_PANEL_STATE_INVALID")

    if derive.has_blocking_conflict(review["panelist_id"], review["application_id"]):
        raise ApiError("ERR_CONFLICT_BLOCKS_REVIEW")
    if application["anonymity_status"] == "BREACHED":
        raise ApiError("ERR_ANONYMITY_BREACH_UNRESOLVED")
    if int(review["round_number"]) != int(panel["round_number"]):
        raise ApiError("ERR_REVIEW_STATE_INVALID")

    derive.set_fields(
        review,
        status="SUBMITTED",
        submitted_at=db.iso3(db.now()),
        weighted_score=calc.review_weighted_score(review),
    )
    if panelist is not None:
        derive.set_fields(
            panelist,
            review_submitted_count=int(panelist["review_submitted_count"]) + 1,
        )
    # §3.7: submission recomputes only valid_review_count and the provisional
    # composite; score_spread waits for the round to close.
    derive.refresh_application_scores(application, include_spread=False)
    return response.obj(db.public(review))
