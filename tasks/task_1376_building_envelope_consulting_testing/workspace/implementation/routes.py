"""API routes — part 1: shared helpers, clock, engagements, assemblies,
design reviews.

Validation order follows PRD section 2.11 exactly:
  1 auth headers -> 2 role -> 3 path existence (left-to-right) ->
  4 body shape -> 5 lifecycle (IN_PROGRESS) -> 6 posture gates ->
  7 target state -> 8 segregation of duties -> 9 temporal windows ->
  10 creation constraints -> 11 referential -> 12 fiscal -> 13 OCC.
"""
from flask import Blueprint, request

from db import STORE, clock_now, set_clock
from errors import (
    ERR_ANOMALY_NOT_OPEN,
    ERR_DUPLICATE_ASSEMBLY_TAG,
    ERR_ENGAGEMENT_NOT_CLOSING_OUT,
    ERR_ENGAGEMENT_NOT_IN_PROGRESS,
    ERR_ENGAGEMENT_NOT_IN_SETUP,
    ERR_ENGAGEMENT_FROZEN,
    ERR_INVALID_REQUEST,
    ERR_NOT_FOUND,
    ERR_OPEN_ANOMALIES_REMAIN,
    ERR_OPEN_REVIEWS_REMAIN,
    ERR_POSTURE_NOT_OPEN,
    ERR_REVIEW_NOT_ACTIONABLE,
    ERR_UNCERTIFIED_TESTS_REMAIN,
    ERR_UNPAID_INVOICES_REMAIN,
    ERR_UNRESOLVED_CLAIMS_REMAIN,
    ERR_DUTY_SEGREGATION_VIOLATION,
    raise_err,
)
from middleware import ANY_ROLE, auth, require_role
from response import fmt_dt, ok
from services import (
    apply_fee_delta,
    bump_engagement_version,
    derive_posture,
    design_review_fee,
    fee_headroom_cents,
    final_fee_accrual,
    fiscal_gate,
    new_common,
    ser_assembly,
    ser_design_review,
    ser_engagement,
    touch,
    touch_engagement,
)
from validators import (
    get_body,
    pagination_params,
    parse_iso8601_instant,
    req_enum,
    req_int,
    req_list,
    req_num,
    req_str,
)
from decimal import Decimal

bp = Blueprint("api", __name__)

ASSEMBLY_TYPES = {"CURTAIN_WALL", "WINDOW_WALL", "MASONRY", "ROOFING", "PLAZA_DECK"}
BARRIER_LAYERS = {"AIR", "WATER", "THERMAL"}


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------
def get_engagement(engagement_id):
    eng = STORE["engagements"].get(engagement_id)
    if eng is None:
        raise_err(ERR_NOT_FOUND, "Engagement not found")
    return eng


def get_child(collection, child_id, engagement_id, what):
    child = STORE[collection].get(child_id)
    if child is None or child["engagement_id"] != engagement_id:
        raise_err(ERR_NOT_FOUND, f"{what} not found")
    return child


def require_in_progress(eng):
    """Tier 5: child creation/transition operations require IN_PROGRESS."""
    if eng["status"] != "IN_PROGRESS":
        raise_err(
            ERR_ENGAGEMENT_NOT_IN_PROGRESS,
            "Operation requires engagement.status == IN_PROGRESS",
        )


def require_not_frozen(eng):
    """Tier 6a: FROZEN posture blocks operational mutations."""
    if derive_posture(eng) == "FROZEN":
        raise_err(ERR_ENGAGEMENT_FROZEN, "Engagement posture is FROZEN")


def require_posture_open(eng):
    """Tier 6b: operations requiring posture exactly OPEN."""
    if derive_posture(eng) != "OPEN":
        raise_err(ERR_POSTURE_NOT_OPEN, "Operation requires posture == OPEN")


def list_response(items, serializer):
    limit, offset = pagination_params()
    ordered = sorted(items, key=lambda x: (x["_created_dt"], x["_seq"]))
    total = len(ordered)
    page = ordered[offset : offset + limit]
    return ok(
        [serializer(x) for x in page],
        pagination={
            "limit": limit,
            "offset": offset,
            "total_count": total,
            "has_more": (offset + len(page)) < total,
        },
    )


# ---------------------------------------------------------------------------
# Clock (test-driving)
# ---------------------------------------------------------------------------
@bp.route("/_clock/set_current_utc", methods=["POST"], strict_slashes=False)
def set_current_utc():
    _, role = auth()
    require_role(role, {"Principal"})
    body = get_body()
    to = parse_iso8601_instant(body.get("to_iso8601"))
    set_clock(to)
    return ok({"current_utc": fmt_dt(clock_now())})


# ---------------------------------------------------------------------------
# Engagement
# ---------------------------------------------------------------------------
@bp.route("/engagements", methods=["POST"], strict_slashes=False)
def create_engagement():
    _, role = auth()
    require_role(role, {"Principal"})
    body = get_body()
    name = req_str(body, "name")
    client_name = req_str(body, "client_name")
    fee_cap_cents = req_int(body, "fee_cap_cents", lo=1)
    labor_rate = req_int(body, "labor_rate_cents_per_hour", lo=1)
    eng = new_common()
    eng.update(
        {
            "name": name,
            "client_name": client_name,
            "fee_cap_cents": fee_cap_cents,
            "labor_rate_cents_per_hour": labor_rate,
            "recognized_fees_cents": 0,
            "risk_score": 100,
            "status": "SETUP",
            "litigation_hold_active": False,
        }
    )
    STORE["engagements"][eng["id"]] = eng
    return ok(ser_engagement(eng), status=201)


@bp.route("/engagements", methods=["GET"], strict_slashes=False)
def list_engagements():
    _, role = auth()
    require_role(role, ANY_ROLE)
    return list_response(list(STORE["engagements"].values()), ser_engagement)


@bp.route("/engagements/<engagement_id>", methods=["GET"], strict_slashes=False)
def get_engagement_route(engagement_id):
    _, role = auth()
    require_role(role, ANY_ROLE)
    return ok(ser_engagement(get_engagement(engagement_id)))


@bp.route("/engagements/<engagement_id>/activate", methods=["POST"], strict_slashes=False)
def activate_engagement(engagement_id):
    _, role = auth()
    require_role(role, {"Principal"})
    eng = get_engagement(engagement_id)
    if eng["status"] != "SETUP":
        raise_err(ERR_ENGAGEMENT_NOT_IN_SETUP, "activate requires status == SETUP")
    eng["status"] = "IN_PROGRESS"
    bump_engagement_version(eng)
    return ok(ser_engagement(eng))


@bp.route("/engagements/<engagement_id>/begin-close-out", methods=["POST"], strict_slashes=False)
def begin_close_out(engagement_id):
    _, role = auth()
    require_role(role, {"Principal"})
    eng = get_engagement(engagement_id)
    if eng["status"] != "IN_PROGRESS":
        raise_err(
            ERR_ENGAGEMENT_NOT_IN_PROGRESS,
            "begin-close-out requires status == IN_PROGRESS",
        )
    if any(
        a["status"] in ("OPEN", "VERIFIED")
        for a in STORE["anomalies"].values()
        if a["engagement_id"] == eng["id"]
    ):
        raise_err(
            ERR_OPEN_ANOMALIES_REMAIN,
            "Anomalies in OPEN or VERIFIED status remain",
        )
    if any(
        t["execution_status"] != "CERTIFIED"
        for t in STORE["field_tests"].values()
        if t["engagement_id"] == eng["id"]
    ):
        raise_err(
            ERR_UNCERTIFIED_TESTS_REMAIN,
            "Field tests not yet CERTIFIED remain",
        )
    if any(
        r["status"] in ("SUBMITTED", "UNDER_REVIEW", "COMMENTS_ISSUED", "REVISED")
        for r in STORE["design_reviews"].values()
        if r["engagement_id"] == eng["id"]
    ):
        raise_err(
            ERR_OPEN_REVIEWS_REMAIN,
            "Design reviews in non-terminal states remain",
        )
    # FINAL fee accrual: chronological replay of positive fee events only,
    # warranty recoveries excluded, no floor. Sole moment headroom may go negative.
    eng["recognized_fees_cents"] = final_fee_accrual(eng["id"])
    eng["status"] = "CLOSE_OUT"
    bump_engagement_version(eng)
    return ok(ser_engagement(eng))


@bp.route("/engagements/<engagement_id>/close", methods=["POST"], strict_slashes=False)
def close_engagement(engagement_id):
    _, role = auth()
    require_role(role, {"Principal"})
    eng = get_engagement(engagement_id)
    if eng["status"] != "CLOSE_OUT":
        raise_err(ERR_ENGAGEMENT_NOT_CLOSING_OUT, "close requires status == CLOSE_OUT")
    if any(
        inv["invoice_status"] not in ("PAID", "VOID")
        for inv in STORE["invoices"].values()
        if inv["engagement_id"] == eng["id"]
    ):
        raise_err(ERR_UNPAID_INVOICES_REMAIN, "Invoices in DRAFT or ISSUED remain")
    if any(
        c["claim_status"] != "RESOLVED"
        for c in STORE["warranty_claims"].values()
        if c["engagement_id"] == eng["id"]
    ):
        raise_err(ERR_UNRESOLVED_CLAIMS_REMAIN, "Warranty claims not RESOLVED remain")
    eng["status"] = "CLOSED"
    bump_engagement_version(eng)
    return ok(ser_engagement(eng))


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------
@bp.route("/engagements/<engagement_id>/assemblies", methods=["POST"], strict_slashes=False)
def create_assembly(engagement_id):
    _, role = auth()
    require_role(role, {"Consultant"})
    eng = get_engagement(engagement_id)
    body = get_body()
    tag = req_str(body, "tag")
    assembly_type = req_enum(body, "assembly_type", ASSEMBLY_TYPES)
    design_u = req_num(body, "design_u_factor", lo=Decimal(0), lo_exclusive=True, hi=Decimal("6.0"))
    req_air = req_num(
        body, "required_airtightness_lps_m2", lo=Decimal(0), lo_exclusive=True, hi=Decimal("3.0")
    )
    require_in_progress(eng)
    for a in STORE["assemblies"].values():
        if a["engagement_id"] == eng["id"] and a["tag"] == tag:
            raise_err(
                ERR_DUPLICATE_ASSEMBLY_TAG,
                "Assembly tag already used within this engagement",
            )
    asm = new_common()
    asm.update(
        {
            "engagement_id": eng["id"],
            "tag": tag,
            "assembly_type": assembly_type,
            "design_u_factor": design_u,
            "required_airtightness_lps_m2": req_air,
            "review_status": "NONE",
        }
    )
    STORE["assemblies"][asm["id"]] = asm
    return ok(ser_assembly(asm), status=201)


@bp.route("/engagements/<engagement_id>/assemblies", methods=["GET"], strict_slashes=False)
def list_assemblies(engagement_id):
    _, role = auth()
    require_role(role, ANY_ROLE)
    eng = get_engagement(engagement_id)
    return list_response(
        [a for a in STORE["assemblies"].values() if a["engagement_id"] == eng["id"]],
        ser_assembly,
    )


@bp.route("/engagements/<engagement_id>/assemblies/<assembly_id>", methods=["GET"], strict_slashes=False)
def get_assembly_route(engagement_id, assembly_id):
    _, role = auth()
    require_role(role, ANY_ROLE)
    eng = get_engagement(engagement_id)
    asm = get_child("assemblies", assembly_id, eng["id"], "Assembly")
    return ok(ser_assembly(asm))


# ---------------------------------------------------------------------------
# DesignReview
# ---------------------------------------------------------------------------
@bp.route("/engagements/<engagement_id>/design-reviews", methods=["POST"], strict_slashes=False)
def create_design_review(engagement_id):
    _, role = auth()
    require_role(role, {"Consultant"})
    eng = get_engagement(engagement_id)
    body = get_body()
    assembly_id = req_str(body, "assembly_id")
    barrier_scope = req_list(body, "barrier_scope")
    for layer in barrier_scope:
        if not isinstance(layer, str) or layer not in BARRIER_LAYERS:
            raise_err(
                ERR_INVALID_REQUEST,
                "barrier_scope must be a non-empty array of AIR | WATER | THERMAL",
            )
    if len(set(barrier_scope)) != len(barrier_scope):
        raise_err(ERR_INVALID_REQUEST, "barrier_scope must not contain duplicates")
    drawing_count = req_int(body, "drawing_count", lo=1)
    require_in_progress(eng)
    get_child("assemblies", assembly_id, eng["id"], "Assembly")
    review = new_common()
    review.update(
        {
            "engagement_id": eng["id"],
            "assembly_id": assembly_id,
            "barrier_scope": list(barrier_scope),
            "drawing_count": drawing_count,
            "revision_round": 0,
            "reviewer_id": None,
            "review_fee_cents": None,
            "status": "SUBMITTED",
        }
    )
    STORE["design_reviews"][review["id"]] = review
    return ok(ser_design_review(review), status=201)


@bp.route("/engagements/<engagement_id>/design-reviews", methods=["GET"], strict_slashes=False)
def list_design_reviews(engagement_id):
    _, role = auth()
    require_role(role, ANY_ROLE)
    eng = get_engagement(engagement_id)
    items = [
        r for r in STORE["design_reviews"].values() if r["engagement_id"] == eng["id"]
    ]
    assembly_id = request.args.get("assembly_id")
    if assembly_id is not None:
        items = [r for r in items if r["assembly_id"] == assembly_id]
    return list_response(items, ser_design_review)


@bp.route("/engagements/<engagement_id>/design-reviews/<review_id>", methods=["GET"], strict_slashes=False)
def get_design_review_route(engagement_id, review_id):
    _, role = auth()
    require_role(role, ANY_ROLE)
    eng = get_engagement(engagement_id)
    review = get_child("design_reviews", review_id, eng["id"], "DesignReview")
    return ok(ser_design_review(review))


def _review_transition(engagement_id, review_id, allowed_roles):
    uid, role = auth()
    require_role(role, allowed_roles)
    eng = get_engagement(engagement_id)
    review = get_child("design_reviews", review_id, eng["id"], "DesignReview")
    require_in_progress(eng)
    return uid, eng, review


def _set_assembly_review_status(eng, assembly_id, status):
    asm = get_child("assemblies", assembly_id, eng["id"], "Assembly")
    asm["review_status"] = status
    touch(asm)


@bp.route(
    "/engagements/<engagement_id>/design-reviews/<review_id>/start-review",
    methods=["POST"],
    strict_slashes=False,
)
def start_review(engagement_id, review_id):
    _, eng, review = _review_transition(engagement_id, review_id, {"Reviewer"})
    require_not_frozen(eng)
    if review["status"] not in ("SUBMITTED", "REVISED"):
        raise_err(
            ERR_REVIEW_NOT_ACTIONABLE,
            "start-review requires status SUBMITTED or REVISED",
        )
    review["status"] = "UNDER_REVIEW"
    touch(review)
    _set_assembly_review_status(eng, review["assembly_id"], "IN_REVIEW")
    return ok(ser_design_review(review))


@bp.route(
    "/engagements/<engagement_id>/design-reviews/<review_id>/issue-comments",
    methods=["POST"],
    strict_slashes=False,
)
def issue_comments(engagement_id, review_id):
    uid, eng, review = _review_transition(engagement_id, review_id, {"Reviewer"})
    if review["status"] != "UNDER_REVIEW":
        raise_err(ERR_REVIEW_NOT_ACTIONABLE, "issue-comments requires UNDER_REVIEW")
    review["status"] = "COMMENTS_ISSUED"
    review["reviewer_id"] = uid
    touch(review)
    return ok(ser_design_review(review))


@bp.route(
    "/engagements/<engagement_id>/design-reviews/<review_id>/submit-revision",
    methods=["POST"],
    strict_slashes=False,
)
def submit_revision(engagement_id, review_id):
    _, eng, review = _review_transition(engagement_id, review_id, {"Consultant"})
    if review["status"] != "COMMENTS_ISSUED":
        raise_err(ERR_REVIEW_NOT_ACTIONABLE, "submit-revision requires COMMENTS_ISSUED")
    review["status"] = "REVISED"
    review["revision_round"] += 1
    touch(review)
    return ok(ser_design_review(review))


@bp.route(
    "/engagements/<engagement_id>/design-reviews/<review_id>/approve",
    methods=["POST"],
    strict_slashes=False,
)
def approve_review(engagement_id, review_id):
    uid, eng, review = _review_transition(engagement_id, review_id, {"Reviewer"})
    require_posture_open(eng)
    if review["status"] != "UNDER_REVIEW":
        raise_err(ERR_REVIEW_NOT_ACTIONABLE, "approve requires UNDER_REVIEW")
    if review["revision_round"] >= 1 and uid == review["reviewer_id"]:
        raise_err(
            ERR_DUTY_SEGREGATION_VIOLATION,
            "The reviewer who issued comments on a round may not approve that round",
        )
    fee = design_review_fee(review)
    fiscal_gate(eng, fee)
    review["status"] = "APPROVED"
    review["review_fee_cents"] = fee
    touch(review)
    _set_assembly_review_status(eng, review["assembly_id"], "APPROVED")
    apply_fee_delta(eng, fee, "design_review_fee")
    return ok(ser_design_review(review))


@bp.route(
    "/engagements/<engagement_id>/design-reviews/<review_id>/reject",
    methods=["POST"],
    strict_slashes=False,
)
def reject_review(engagement_id, review_id):
    _, eng, review = _review_transition(engagement_id, review_id, {"Reviewer"})
    if review["status"] != "UNDER_REVIEW":
        raise_err(ERR_REVIEW_NOT_ACTIONABLE, "reject requires UNDER_REVIEW")
    fee = design_review_fee(review)
    fiscal_gate(eng, fee)
    review["status"] = "REJECTED"
    review["review_fee_cents"] = fee
    touch(review)
    _set_assembly_review_status(eng, review["assembly_id"], "REJECTED")
    apply_fee_delta(eng, fee, "design_review_fee")
    return ok(ser_design_review(review))
