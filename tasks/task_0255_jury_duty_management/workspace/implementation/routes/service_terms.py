"""ServiceTerm endpoints + term-scoped collections (jurors, summonses, trials,
panels) and the draw / pool-projection operations.

Validation order at each endpoint (PRD §4): auth -> RBAC -> existence -> state ->
business/temporal -> OCC -> body validation (ERR_INVALID_REQUEST is last).
"""
from flask import Blueprint

import db
import errors
import helpers
import serializers
from middleware import get_identity, require_roles
from response import success
from services import core

bp = Blueprint("service_terms", __name__)


# ---------------------------------------------------------------------------
# POST /service-terms
# ---------------------------------------------------------------------------
@bp.route("/service-terms", methods=["POST"])
def create_service_term():
    _, role = get_identity()
    require_roles(role, {"JuryAdministrator"})

    body = helpers.get_body()
    name = helpers.require_string(body, "name")
    report_date_raw = helpers.require_string(body, "report_date")
    report_date_dt = helpers.parse_iso8601(report_date_raw, "report_date")
    daily_pay_cents = helpers.require_int(body, "daily_pay_cents", minimum=0)
    half_day_pay_cents = helpers.require_int(body, "half_day_pay_cents", minimum=0)
    full_day_hours = helpers.require_number(body, "full_day_hours", gt=0)
    mileage_rate_cents = helpers.require_int(body, "mileage_rate_cents", minimum=0)
    pay_day_cap = helpers.require_int(body, "pay_day_cap", minimum=1)
    fta_threshold = helpers.optional_int(body, "fta_disqualify_threshold", default=3, minimum=1)

    # report_date_dt validated above; store the canonical ISO string.
    _ = report_date_dt
    rec = core.create_service_term(
        name=name,
        report_date=report_date_raw,
        daily_pay_cents=daily_pay_cents,
        half_day_pay_cents=half_day_pay_cents,
        full_day_hours=full_day_hours,
        mileage_rate_cents=mileage_rate_cents,
        pay_day_cap=pay_day_cap,
        fta_disqualify_threshold=fta_threshold,
    )
    return success(serializers.service_term(rec), status=201)


# ---------------------------------------------------------------------------
# GET /service-terms
# ---------------------------------------------------------------------------
@bp.route("/service-terms", methods=["GET"])
def list_service_terms():
    _, role = get_identity()
    require_roles(role, {"JuryAdministrator", "CourtClerk", "Judge"})

    from flask import request
    status = request.args.get("status")
    rows = [t for t in db.service_terms.values() if status is None or t["status"] == status]
    data, meta = helpers.paginate(rows, serializers.service_term)
    return success(data, status=200, pagination=meta)


# ---------------------------------------------------------------------------
# GET /service-terms/{id}
# ---------------------------------------------------------------------------
@bp.route("/service-terms/<term_id>", methods=["GET"])
def get_service_term(term_id):
    _, role = get_identity()
    require_roles(role, {"JuryAdministrator", "CourtClerk", "Judge"})

    term = core.get_term(term_id)
    if term is None:
        raise errors.err("ERR_NOT_FOUND", "Service term not found")
    return success(serializers.service_term(term), status=200)


# ---------------------------------------------------------------------------
# POST /service-terms/{id}/open
# ---------------------------------------------------------------------------
@bp.route("/service-terms/<term_id>/open", methods=["POST"])
def open_service_term(term_id):
    _, role = get_identity()
    require_roles(role, {"JuryAdministrator"})

    term = core.get_term(term_id)
    if term is None:
        raise errors.err("ERR_NOT_FOUND", "Service term not found")

    if term["status"] != "DRAFT":
        raise errors.err("ERR_INVALID_STATE", "Term must be DRAFT to open")

    has_qualified = any(
        j["service_term_id"] == term_id
        and j["qualification_status"] == "QUALIFIED"
        and j["disqualified"] is False
        for j in db.jurors.values()
    )
    if not has_qualified:
        raise errors.err("ERR_INVALID_STATE", "Term needs at least one qualified, non-disqualified juror to open")

    term["status"] = "OPEN"
    core.touch(term)
    return success(serializers.service_term(term), status=200)


# ---------------------------------------------------------------------------
# POST /service-terms/{id}/close
# ---------------------------------------------------------------------------
@bp.route("/service-terms/<term_id>/close", methods=["POST"])
def close_service_term(term_id):
    _, role = get_identity()
    require_roles(role, {"JuryAdministrator"})

    term = core.get_term(term_id)
    if term is None:
        raise errors.err("ERR_NOT_FOUND", "Service term not found")

    if term["status"] != "OPEN":
        raise errors.err("ERR_INVALID_STATE", "Term must be OPEN to close")

    blocking_summons = any(
        s["service_term_id"] == term_id and s["status"] in ("REPORTING", "SERVING")
        for s in db.summonses.values()
    )
    if blocking_summons:
        raise errors.err("ERR_INVALID_STATE", "Cannot close: a summons is still REPORTING or SERVING")

    forming_panel = any(
        p["service_term_id"] == term_id and p["status"] == "FORMING"
        for p in db.panels.values()
    )
    if forming_panel:
        raise errors.err("ERR_INVALID_STATE", "Cannot close: a panel is still FORMING")

    term["status"] = "CLOSED"
    core.touch(term)
    return success(serializers.service_term(term), status=200)


# ---------------------------------------------------------------------------
# POST /service-terms/{id}/draw
# ---------------------------------------------------------------------------
@bp.route("/service-terms/<term_id>/draw", methods=["POST"])
def draw(term_id):
    _, role = get_identity()
    require_roles(role, {"JuryAdministrator"})

    term = core.get_term(term_id)
    if term is None:
        raise errors.err("ERR_NOT_FOUND", "Service term not found")

    # Business: term must be OPEN (priority 30) — beats pool-exhausted (60).
    if term["status"] != "OPEN":
        raise errors.err("ERR_TERM_NOT_OPEN", "Term must be OPEN to draw")

    body = helpers.get_body()
    count = helpers.require_int(body, "count", minimum=1)
    expected_version = helpers.require_int(body, "expected_service_term_version")

    # OCC (priority 71): expected_service_term_version must equal term.version.
    if expected_version != term["version"]:
        raise errors.err("ERR_STALE_TERM_VERSION", "Stale service term version")

    # Eligible pool: QUALIFIED, not disqualified, no non-cancelled summons in this
    # term. Rank by (last_drawn_seq ASC, fta_strike_count ASC, created_at ASC,
    # insertion-seq ASC) — never by id.
    summoned_juror_ids = {
        s["juror_id"] for s in db.summonses.values() if s["service_term_id"] == term_id
    }
    eligible = [
        j
        for j in db.jurors.values()
        if j["service_term_id"] == term_id
        and j["qualification_status"] == "QUALIFIED"
        and j["disqualified"] is False
        and j["id"] not in summoned_juror_ids
    ]
    eligible.sort(key=lambda j: (
        j["last_drawn_seq"],
        core.juror_fta_strike_count(j["id"]),
        j["created_at"],
        j["_seq"],
    ))

    # Pool boundary (priority 60): need at least `count` eligible jurors.
    if len(eligible) < count:
        raise errors.err("ERR_POOL_EXHAUSTED", "Eligible qualified pool is smaller than the requested count")

    chosen = eligible[:count]

    # Commit: bump draw_seq, stamp last_drawn_seq, bump term version, create
    # one SUMMONED summons per drawn juror.
    term["draw_seq"] += 1
    new_seq = term["draw_seq"]
    created = []
    for j in chosen:
        j["last_drawn_seq"] = new_seq
        core.touch(j)
        s = core.create_summons(term_id, j["id"], deferral_count=0)
        created.append(s)
    core.touch(term)  # version increments by one for the draw (PRD §2.6/§3.2)

    return success([serializers.summons(s) for s in created], status=201)


# ---------------------------------------------------------------------------
# GET /service-terms/{id}/pool-projection
# ---------------------------------------------------------------------------
@bp.route("/service-terms/<term_id>/pool-projection", methods=["GET"])
def pool_projection(term_id):
    _, role = get_identity()
    require_roles(role, {"JuryAdministrator"})

    term = core.get_term(term_id)
    if term is None:
        raise errors.err("ERR_NOT_FOUND", "Service term not found")

    projected, pool_size = core.pool_projection(term)
    return success({"projected_mileage_cents": projected, "pool_size": pool_size}, status=200)


# ---------------------------------------------------------------------------
# POST /service-terms/{id}/jurors
# ---------------------------------------------------------------------------
@bp.route("/service-terms/<term_id>/jurors", methods=["POST"])
def add_juror(term_id):
    _, role = get_identity()
    require_roles(role, {"JuryAdministrator"})

    term = core.get_term(term_id)
    if term is None:
        raise errors.err("ERR_NOT_FOUND", "Service term not found")

    body = helpers.get_body()
    full_name = helpers.require_string(body, "full_name")
    birth_year = helpers.require_int(body, "birth_year", minimum=1900, maximum=2010)
    round_trip_miles = helpers.require_number(body, "round_trip_miles", minimum=0)

    rec = core.create_juror(term_id, full_name, birth_year, round_trip_miles)
    return success(serializers.juror(rec), status=201)


# ---------------------------------------------------------------------------
# GET /service-terms/{id}/jurors
# ---------------------------------------------------------------------------
@bp.route("/service-terms/<term_id>/jurors", methods=["GET"])
def list_jurors(term_id):
    _, role = get_identity()
    require_roles(role, {"JuryAdministrator", "CourtClerk"})

    term = core.get_term(term_id)
    if term is None:
        raise errors.err("ERR_NOT_FOUND", "Service term not found")

    from flask import request
    q_status = request.args.get("qualification_status")
    disqualified = request.args.get("disqualified")

    rows = [j for j in db.jurors.values() if j["service_term_id"] == term_id]
    if q_status is not None:
        rows = [j for j in rows if j["qualification_status"] == q_status]
    if disqualified is not None:
        want = disqualified.lower() in ("true", "1")
        rows = [j for j in rows if j["disqualified"] == want]

    data, meta = helpers.paginate(rows, serializers.juror)
    return success(data, status=200, pagination=meta)


# ---------------------------------------------------------------------------
# GET /service-terms/{id}/summonses
# ---------------------------------------------------------------------------
@bp.route("/service-terms/<term_id>/summonses", methods=["GET"])
def list_term_summonses(term_id):
    _, role = get_identity()
    require_roles(role, {"JuryAdministrator", "CourtClerk"})

    term = core.get_term(term_id)
    if term is None:
        raise errors.err("ERR_NOT_FOUND", "Service term not found")

    from flask import request
    status = request.args.get("status")
    juror_id = request.args.get("juror_id")
    deferred_to = request.args.get("deferred_to_term_id")

    rows = [s for s in db.summonses.values() if s["service_term_id"] == term_id]
    if status is not None:
        rows = [s for s in rows if s["status"] == status]
    if juror_id is not None:
        rows = [s for s in rows if s["juror_id"] == juror_id]
    if deferred_to is not None:
        rows = [s for s in rows if s["deferred_to_term_id"] == deferred_to]

    data, meta = helpers.paginate(rows, serializers.summons)
    return success(data, status=200, pagination=meta)


# ---------------------------------------------------------------------------
# POST /service-terms/{id}/trials
# ---------------------------------------------------------------------------
@bp.route("/service-terms/<term_id>/trials", methods=["POST"])
def create_trial(term_id):
    _, role = get_identity()
    require_roles(role, {"JuryAdministrator", "Judge"})

    term = core.get_term(term_id)
    if term is None:
        raise errors.err("ERR_NOT_FOUND", "Service term not found")

    body = helpers.get_body()
    caption = helpers.require_string(body, "caption")
    required_jurors = helpers.require_int(body, "required_jurors", minimum=1)

    rec = core.create_trial(term_id, caption, required_jurors)
    return success(serializers.trial(rec), status=201)


# ---------------------------------------------------------------------------
# GET /service-terms/{id}/trials
# ---------------------------------------------------------------------------
@bp.route("/service-terms/<term_id>/trials", methods=["GET"])
def list_term_trials(term_id):
    _, role = get_identity()
    require_roles(role, {"JuryAdministrator", "CourtClerk", "Judge"})

    term = core.get_term(term_id)
    if term is None:
        raise errors.err("ERR_NOT_FOUND", "Service term not found")

    from flask import request
    status = request.args.get("status")
    rows = [t for t in db.trials.values() if t["service_term_id"] == term_id]
    if status is not None:
        rows = [t for t in rows if t["status"] == status]

    data, meta = helpers.paginate(rows, serializers.trial)
    return success(data, status=200, pagination=meta)


# ---------------------------------------------------------------------------
# GET /service-terms/{id}/panels
# ---------------------------------------------------------------------------
@bp.route("/service-terms/<term_id>/panels", methods=["GET"])
def list_term_panels(term_id):
    _, role = get_identity()
    require_roles(role, {"JuryAdministrator", "CourtClerk", "Judge"})

    term = core.get_term(term_id)
    if term is None:
        raise errors.err("ERR_NOT_FOUND", "Service term not found")

    from flask import request
    status = request.args.get("status")
    rows = [p for p in db.panels.values() if p["service_term_id"] == term_id]
    if status is not None:
        rows = [p for p in rows if p["status"] == status]

    data, meta = helpers.paginate(rows, serializers.panel)
    return success(data, status=200, pagination=meta)
