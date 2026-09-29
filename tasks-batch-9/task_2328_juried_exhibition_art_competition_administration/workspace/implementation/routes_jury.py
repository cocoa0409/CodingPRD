"""Jurors, conflicts, rounds, sessions and scores."""

from flask import Blueprint

from core import *  # noqa: F401,F403
from errors import ApiError

bp = Blueprint("jury", __name__)


# ---------------------------------------------------------------------------
# Jurors
# ---------------------------------------------------------------------------


@bp.post("/jurors")
def create_juror():
    authenticate()
    require_roles("JuryChair")
    payload = body()
    display_name = v_str(payload, "display_name")
    email = v_str(payload, "email")
    expertise = v_list(payload, "expertise_categories", MEDIA_CATEGORIES)
    honorarium = v_int(payload, "honorarium_cents", minimum=0)
    for existing in db.jurors.values():
        if existing["email"] == email:
            bad("email must be unique across jurors.")
    record = new_record(
        {
            "display_name": display_name,
            "email": email,
            "expertise_categories": expertise,
            "honorarium_cents": honorarium,
            "status": "INVITED",
            "honorarium_committed_cents": 0,
            "honorarium_paid_cents": 0,
            "conflict_count": 0,
            "assignment_count": 0,
        }
    )
    db.jurors[record["id"]] = record
    return created(record)


@bp.get("/jurors/<juror_id>")
def read_juror(juror_id):
    authenticate()
    require_roles("JuryChair", "Juror", "FinanceOfficer")
    return ok(find("jurors", juror_id))


@bp.post("/jurors/<juror_id>/confirm")
def confirm_juror(juror_id):
    authenticate()
    require_roles("Juror", "JuryChair")
    juror = find("jurors", juror_id)
    if role() == "Juror":
        own(user_id() == juror["id"])
    if juror["status"] != "INVITED":
        raise ApiError(
            "ERR_JUROR_NOT_CONFIRMED",
            "Only an INVITED juror may accept the invitation.",
        )
    setv(juror, "status", "CONFIRMED")
    return ok(juror)


@bp.post("/jurors/<juror_id>/resign")
def resign_juror(juror_id):
    authenticate()
    require_roles("Juror", "JuryChair")
    juror = find("jurors", juror_id)
    if role() == "Juror":
        own(user_id() == juror["id"])
    if juror["status"] not in ("INVITED", "CONFIRMED"):
        raise ApiError(
            "ERR_JUROR_NOT_CONFIRMED", "A resigned juror may not resign again."
        )

    affected_rounds = []
    for assignment in assignments_of_juror(juror["id"]):
        if assignment.get("status") != "BOOKED":
            continue
        setv(assignment, "status", "CANCELLED")
        setv(assignment, "honorarium_share_cents", 0)
        jury_round = db.jury_rounds.get(assignment.get("jury_round_id"))
        if jury_round is not None and jury_round not in affected_rounds:
            affected_rounds.append(jury_round)

    setv(juror, "status", "RESIGNED")
    prorate_honorarium(juror)
    recompute_jury_cost_for_juror(juror)
    for jury_round in affected_rounds:
        recompute_round(jury_round)
    return ok(juror)


@bp.post("/jurors/<juror_id>/honorarium-payment")
def honorarium_payment(juror_id):
    authenticate()
    require_roles("FinanceOfficer")
    juror = find("jurors", juror_id)
    payload = body()
    amount = v_int(payload, "amount_cents", minimum=0)
    committed = int(juror["honorarium_committed_cents"])
    paid = int(juror["honorarium_paid_cents"])
    setv(juror, "honorarium_paid_cents", min(committed, paid + amount))
    return ok(juror)


# ---------------------------------------------------------------------------
# Conflict declarations
# ---------------------------------------------------------------------------


@bp.post("/jurors/<juror_id>/conflict-declarations")
def declare_conflict(juror_id):
    authenticate()
    require_roles("Juror", "JuryChair")
    juror = find("jurors", juror_id)
    payload = body()
    artist = fk(payload, "artist_id", "artists")
    if role() == "Juror":
        own(user_id() == juror["id"])
    if artist is None:
        req(payload, "artist_id")
    relation = v_enum(payload, "relation_type", RELATION_TYPES)

    voided = 0
    touched_artworks = []
    touched_rounds = []
    for score in all_of("scores"):
        if score.get("juror_id") != juror["id"] or score.get("voided_by_conflict"):
            continue
        artwork = db.artworks.get(score.get("artwork_id"))
        if artwork is None:
            continue
        entry = entry_of(artwork)
        if entry is None or entry.get("artist_id") != artist["id"]:
            continue
        score["voided_by_conflict"] = True
        voided += 1
        if artwork not in touched_artworks:
            touched_artworks.append(artwork)
        jury_round = db.jury_rounds.get(score.get("jury_round_id"))
        if jury_round is not None and jury_round not in touched_rounds:
            touched_rounds.append(jury_round)

    record = new_record(
        {
            "juror_id": juror["id"],
            "artist_id": artist["id"],
            "relation_type": relation,
            "voided_score_count": voided,
        },
        versioned=False,
    )
    db.conflict_declarations[record["id"]] = record

    setv(
        juror,
        "conflict_count",
        sum(
            1
            for c in all_of("conflict_declarations")
            if c.get("juror_id") == juror["id"]
        ),
    )
    for artwork in touched_artworks:
        for jury_round in touched_rounds:
            recompute_artwork_scores(artwork, jury_round)
        recompute_artwork_scores(artwork)
    for jury_round in touched_rounds:
        recompute_round(jury_round)
    return created(record)


@bp.get("/jurors/<juror_id>/conflict-declarations")
def list_juror_conflicts(juror_id):
    authenticate()
    require_roles("Juror", "JuryChair")
    juror = find("jurors", juror_id)
    items = [
        c for c in all_of("conflict_declarations") if c.get("juror_id") == juror["id"]
    ]
    return listing(items)


# ---------------------------------------------------------------------------
# Jury rounds
# ---------------------------------------------------------------------------


@bp.post("/jury-rounds")
def create_round():
    authenticate()
    require_roles("JuryChair")
    payload = body()
    exhibition = fk(payload, "exhibition_id", "exhibitions")
    if exhibition is None:
        req(payload, "exhibition_id")
    round_number = v_int(payload, "round_number", minimum=1)
    round_type = v_enum(payload, "round_type", ROUND_TYPES)
    opens_at = v_dt(payload, "opens_at")
    closes_at = v_dt(payload, "closes_at")
    quorum = v_int(payload, "quorum_required", required=False, minimum=0)
    if quorum is None:
        quorum = int(exhibition["jury_quorum"])

    for existing in rounds_of_exhibition(exhibition["id"]):
        if int(existing["round_number"]) == round_number:
            raise ApiError("ERR_DUPLICATE_ROUND_NUMBER")

    shortfall = 0
    if quorum > 0:
        shortfall = sum(
            1
            for a in artworks_of_exhibition(exhibition["id"])
            if a.get("status") == "SUBMITTED"
        )
    record = new_record(
        {
            "exhibition_id": exhibition["id"],
            "round_number": round_number,
            "round_type": round_type,
            "opens_at": opens_at,
            "closes_at": closes_at,
            "quorum_required": quorum,
            "status": "PENDING",
            "reopen_count": 0,
            "scored_artwork_count": 0,
            "quorum_shortfall_count": shortfall,
        }
    )
    db.jury_rounds[record["id"]] = record
    if round_number == 1:
        for artwork in artworks_of_exhibition(exhibition["id"]):
            recompute_artwork_scores(artwork)
    return created(record)


@bp.get("/jury-rounds")
def list_rounds():
    authenticate()
    require_roles("CallManager", "JuryChair", "Juror")
    items = all_of("jury_rounds")
    for field in ("exhibition_id", "status"):
        value = qs(field)
        if value is not None:
            items = [r for r in items if r.get(field) == value]
    return listing(items)


@bp.get("/jury-rounds/<round_id>")
def read_round(round_id):
    authenticate()
    require_roles("CallManager", "JuryChair", "Juror")
    return ok(find("jury_rounds", round_id))


ROUND_TRANSITIONS = (
    ("PENDING", "OPEN"),
    ("OPEN", "SCORING_COMPLETE"),
    ("SCORING_COMPLETE", "OPEN"),
    ("SCORING_COMPLETE", "CLOSED"),
)


def _complete_round(jury_round, exhibition):
    quorum = int(jury_round["quorum_required"])
    threshold = D(exhibition["advance_score_threshold"])
    for artwork in artworks_of_exhibition(exhibition["id"]):
        if artwork.get("status") != "SUBMITTED":
            continue
        scores = valid_scores_for(artwork["id"], jury_round["id"])
        certified = mean_of(scores[:quorum]) if quorum > 0 else mean_of(scores)
        setv(artwork, "certified_mean_score", certified)
        recompute_artwork_scores(artwork, jury_round)
        if certified is None:
            continue
        if len(scores) >= quorum and D(certified) >= threshold:
            set_artwork_status(artwork, "SHORTLISTED")
        elif D(certified) < threshold:
            set_artwork_status(artwork, "DECLINED")
    for entry in entries_of_exhibition(exhibition["id"]):
        recompute_entry_counts(entry)
    recompute_exhibition_counts(exhibition)


def _reopen_round(jury_round, exhibition):
    setv(jury_round, "reopen_count", int(jury_round["reopen_count"]) + 1)
    for artwork in artworks_of_exhibition(exhibition["id"]):
        if artwork.get("status") in ("SHORTLISTED", "DECLINED"):
            set_artwork_status(artwork, "SUBMITTED")
            setv(artwork, "certified_mean_score", None)
    for entry in entries_of_exhibition(exhibition["id"]):
        recompute_entry_counts(entry)
    recompute_exhibition_counts(exhibition)


@bp.post("/jury-rounds/<round_id>/status")
def round_status(round_id):
    authenticate()
    require_roles("JuryChair")
    jury_round = find("jury_rounds", round_id)
    exhibition = db.exhibitions.get(jury_round["exhibition_id"])
    payload = body()
    target = v_enum(payload, "target_status", ROUND_STATUSES)

    current = jury_round["status"]
    if (current, target) not in ROUND_TRANSITIONS:
        raise ApiError("ERR_JURY_ROUND_STATE_INVALID")

    if target == "OPEN" and current == "PENDING":
        if exhibition["status"] != "JURYING":
            raise ApiError("ERR_EXHIBITION_PHASE_INVALID")
        booked = [
            a
            for a in assignments_of_round(jury_round["id"])
            if a.get("status") == "BOOKED"
        ]
        if not booked:
            raise ApiError(
                "ERR_JURY_ROUND_STATE_INVALID",
                "A round with no booked juror cannot open.",
            )
        setv(jury_round, "status", "OPEN")
    elif target == "OPEN":
        if exhibition["status"] != "JURYING":
            raise ApiError("ERR_EXHIBITION_PHASE_INVALID")
        if int(jury_round["reopen_count"]) >= 2:
            raise ApiError("ERR_ROUND_REOPEN_LIMIT")
        setv(jury_round, "status", "OPEN")
        _reopen_round(jury_round, exhibition)
    elif target == "SCORING_COMPLETE":
        recompute_round(jury_round)
        if int(jury_round["quorum_shortfall_count"]) != 0:
            raise ApiError("ERR_QUORUM_NOT_MET")
        setv(jury_round, "status", "SCORING_COMPLETE")
        _complete_round(jury_round, exhibition)
    else:  # CLOSED
        setv(jury_round, "status", "CLOSED")
        jurors = []
        for assignment in assignments_of_round(jury_round["id"]):
            if assignment.get("status") == "BOOKED":
                setv(assignment, "status", "COMPLETED")
                juror = db.jurors.get(assignment.get("juror_id"))
                if juror is not None and juror not in jurors:
                    jurors.append(juror)
        for juror in jurors:
            prorate_honorarium(juror)
        recompute_jury_cost(exhibition)

    recompute_round(jury_round)
    touch(jury_round)
    return ok(jury_round)


# ---------------------------------------------------------------------------
# Juror assignments
# ---------------------------------------------------------------------------


@bp.post("/jury-rounds/<round_id>/assignments")
def create_assignment(round_id):
    authenticate()
    require_roles("JuryChair")
    jury_round = find("jury_rounds", round_id)
    exhibition = db.exhibitions.get(jury_round["exhibition_id"])
    payload = body()
    juror = fk(payload, "juror_id", "jurors")
    if juror is None:
        req(payload, "juror_id")
    start_raw = v_dt(payload, "session_start_at")
    end_raw = v_dt(payload, "session_end_at")
    expected = v_int(payload, "expected_jury_round_version")
    start = parse_dt(start_raw)
    end = parse_dt(end_raw)
    if end <= start:
        bad("session_end_at must be after session_start_at.")

    if juror["status"] != "CONFIRMED":
        raise ApiError("ERR_JUROR_NOT_CONFIRMED")

    if start < ts(jury_round, "opens_at") or end > ts(jury_round, "closes_at"):
        raise ApiError("ERR_SESSION_OUTSIDE_ROUND_WINDOW")

    for other in assignments_of_juror(juror["id"]):
        if other.get("status") not in ("BOOKED", "COMPLETED"):
            continue
        o_start = ts(other, "session_start_at")
        o_end = ts(other, "session_end_at")
        if start < o_end and end > o_start:
            raise ApiError("ERR_JUROR_SESSION_OVERLAP")

    if expected != jury_round["version"]:
        raise ApiError("ERR_STALE_VERSION")

    minutes = int((end - start).total_seconds() // 60)
    record = new_record(
        {
            "juror_id": juror["id"],
            "jury_round_id": jury_round["id"],
            "session_start_at": start_raw,
            "session_end_at": end_raw,
            "status": "BOOKED",
            "session_minutes": minutes,
            "honorarium_share_cents": 0,
            "scores_submitted_count": 0,
        }
    )
    db.juror_assignments[record["id"]] = record
    prorate_honorarium(juror)
    recompute_jury_cost_for_juror(juror)
    touch(jury_round)
    return created(record)


@bp.get("/juror-assignments")
def list_assignments():
    authenticate()
    require_roles("JuryChair", "Juror", "FinanceOfficer")
    items = all_of("juror_assignments")
    for field in ("juror_id", "jury_round_id", "status"):
        value = qs(field)
        if value is not None:
            items = [a for a in items if a.get(field) == value]
    return listing(items)


@bp.get("/juror-assignments/<assignment_id>")
def read_assignment(assignment_id):
    authenticate()
    require_roles("JuryChair", "Juror", "FinanceOfficer")
    return ok(find("juror_assignments", assignment_id))


@bp.post("/juror-assignments/<assignment_id>/cancel")
def cancel_assignment(assignment_id):
    authenticate()
    require_roles("JuryChair")
    assignment = find("juror_assignments", assignment_id)
    jury_round = db.jury_rounds.get(assignment["jury_round_id"])
    if jury_round is not None and jury_round.get("status") == "CLOSED":
        raise ApiError("ERR_JURY_ROUND_STATE_INVALID")
    if assignment["status"] != "BOOKED":
        raise ApiError("ERR_ASSIGNMENT_STATE_INVALID")

    juror = db.jurors.get(assignment["juror_id"])
    setv(assignment, "status", "CANCELLED")
    setv(assignment, "honorarium_share_cents", 0)
    prorate_honorarium(juror)
    recompute_jury_cost_for_juror(juror)
    recompute_round(jury_round)
    return ok(assignment)


# ---------------------------------------------------------------------------
# Scores
# ---------------------------------------------------------------------------


@bp.post("/jury-rounds/<round_id>/scores")
def submit_score(round_id):
    authenticate()
    require_roles("Juror")
    jury_round = find("jury_rounds", round_id)
    exhibition = db.exhibitions.get(jury_round["exhibition_id"])
    payload = body()
    artwork = fk(payload, "artwork_id", "artworks")
    if artwork is None:
        req(payload, "artwork_id")
    technique = v_int(payload, "technique", minimum=1, maximum=10)
    originality = v_int(payload, "originality", minimum=1, maximum=10)
    relevance = v_int(payload, "relevance", minimum=1, maximum=10)

    if jury_round["status"] != "OPEN":
        raise ApiError("ERR_JURY_ROUND_STATE_INVALID")

    juror = db.jurors.get(user_id())
    if juror is None or juror.get("status") != "CONFIRMED":
        raise ApiError("ERR_JUROR_NOT_CONFIRMED")

    artwork_exhibition = exhibition_of_artwork(artwork)
    if artwork_exhibition is None or artwork_exhibition["id"] != exhibition["id"]:
        raise ApiError("ERR_EXHIBITION_SCOPE_MISMATCH")

    entry = entry_of(artwork)
    for declaration in all_of("conflict_declarations"):
        if (
            declaration.get("juror_id") == juror["id"]
            and entry is not None
            and declaration.get("artist_id") == entry.get("artist_id")
        ):
            raise ApiError("ERR_JUROR_CONFLICT_DECLARED")

    clock = now()
    if clock < ts(jury_round, "opens_at") or clock > ts(jury_round, "closes_at"):
        raise ApiError("ERR_SCORING_WINDOW_CLOSED")

    for existing in scores_of_round(jury_round["id"]):
        if (
            existing.get("artwork_id") == artwork["id"]
            and existing.get("juror_id") == juror["id"]
        ):
            raise ApiError("ERR_DUPLICATE_SCORE")

    match, composite = calc_composite(
        exhibition, juror, artwork, technique, originality, relevance
    )
    record = new_record(
        {
            "jury_round_id": jury_round["id"],
            "artwork_id": artwork["id"],
            "juror_id": juror["id"],
            "technique": technique,
            "originality": originality,
            "relevance": relevance,
            "expertise_match": match,
            "composite_score": composite,
            "voided_by_conflict": False,
            "submitted_at": iso(clock),
        },
        versioned=False,
    )
    db.scores[record["id"]] = record

    recompute_artwork_scores(artwork, jury_round)
    recompute_round(jury_round)
    for assignment in assignments_of_round(jury_round["id"]):
        if assignment.get("juror_id") == juror["id"]:
            recompute_assignment_counts(assignment)
    return created(record)


@bp.get("/scores")
def list_scores():
    authenticate()
    require_roles("JuryChair", "Juror")
    items = all_of("scores")
    for field in ("jury_round_id", "artwork_id", "juror_id"):
        value = qs(field)
        if value is not None:
            items = [s for s in items if s.get(field) == value]
    return listing(items)


@bp.get("/scores/<score_id>")
def read_score(score_id):
    authenticate()
    require_roles("JuryChair", "Juror")
    return ok(find("scores", score_id))
