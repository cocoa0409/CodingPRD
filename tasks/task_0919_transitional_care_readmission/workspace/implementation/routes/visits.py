"""The face-to-face TCM visit and its two independent axes (PRD 3.4)."""
from flask import Blueprint

import constants as C
import domain
import envelope
import guards as G
import store
from errors import ApiError
from store import DB, serialize

bp = Blueprint("visits", __name__)


def _achieved_complexity(elements):
    if set(C.HIGH_REQUIRED_ELEMENTS).issubset(set(elements)):
        return "HIGH_COMPLEXITY"
    return "MODERATE_COMPLEXITY"


def _interval(data):
    start = G.req_instant(data, "scheduled_start")
    end = G.req_instant(data, "scheduled_end")
    if not end > start:
        raise ApiError(
            "ERR_VALIDATION", "Field 'scheduled_end' must be strictly after 'scheduled_start'."
        )
    return start, end


# --------------------------------------------------------------------- book
@bp.post("/tcm/episodes/<episode_id>/visits")
def book_visit(episode_id):
    user_id, role = G.auth(["CareNavigator"])
    data = G.body()
    navigator_id = G.req_string(data, "navigator_id")
    start, end = _interval(data)

    episode = G.get_episode(episode_id)
    G.get_row("navigators", navigator_id)
    G.require_episode_owner(episode, user_id, role)
    G.require_open_records(episode)

    if domain.slot_conflict(navigator_id, start, end):
        raise ApiError("ERR_SCHEDULE_CONFLICT")

    row = store.new_row(
        "visits",
        {
            "episode_id": episode["id"],
            "navigator_id": navigator_id,
            "scheduled_start": start,
            "scheduled_end": end,
            "encounter_status": "SCHEDULED",
            "documentation_status": "DRAFT",
            "confirmation_status": "UNCONFIRMED",
            "required_complexity": episode["required_visit_complexity"],
            "achieved_complexity": None,
            "visit_due_date": episode["visit_due_date"],
            "deadline_status": "SCHEDULED_IN_WINDOW",
            "completed_at": None,
            "documented_elements": [],
            "attested_by_user_id": None,
            "attested_at": None,
            "amendment_count": 0,
        },
    )
    row["deadline_status"] = domain.visit_deadline_status(row)
    return envelope.created(serialize(row))


@bp.get("/tcm/visits/<visit_id>")
def read_visit(visit_id):
    G.auth(C.ALL_ROLES)
    return envelope.ok(serialize(G.get_row("visits", visit_id)))


@bp.get("/tcm/visits")
def list_visits():
    G.auth(C.ALL_ROLES)
    limit, offset = G.pagination()
    f = G.filters("episode_id", "navigator_id", "encounter_status", "documentation_status")

    def keep(row):
        return all(row.get(key) == value for key, value in f.items())

    rows = store.sorted_rows("visits", keep)
    page = rows[offset : offset + limit]
    return envelope.listing([serialize(r) for r in page], limit, offset, len(rows))


# ------------------------------------------------------------------ confirm
@bp.post("/tcm/visits/<visit_id>/confirm")
def confirm_visit(visit_id):
    user_id, role = G.auth(["CareNavigator"])
    visit = G.get_row("visits", visit_id)
    episode = DB["episodes"][visit["episode_id"]]
    G.require_episode_owner(episode, user_id, role)
    G.require_open_records(episode)

    if visit["encounter_status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", "Only a SCHEDULED appointment may be confirmed.")
    if domain.has_open_blocking_barrier(episode):
        raise ApiError("ERR_BLOCKING_BARRIER_OPEN")

    visit["confirmation_status"] = "CONFIRMED"
    store.touch(visit)
    return envelope.ok(serialize(visit))


# ----------------------------------------------------------------- complete
@bp.post("/tcm/visits/<visit_id>/complete")
def complete_visit(visit_id):
    G.auth(["Clinician"])
    data = G.body()
    elements = G.req_array(data, "documented_elements")
    G.enum_members(elements, C.DOCUMENTED_ELEMENT_MEMBERS, "documented_elements")

    visit = G.get_row("visits", visit_id)
    episode = DB["episodes"][visit["episode_id"]]
    G.require_open_records(episode)

    if visit["encounter_status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", "Only a SCHEDULED encounter may be completed.")
    if visit["confirmation_status"] != "CONFIRMED":
        raise ApiError("ERR_INVALID_STATE", "The appointment has not been confirmed.")
    if episode["contact_status"] != "SUCCESSFUL":
        raise ApiError("ERR_INVALID_STATE", "Interactive contact has not yet succeeded.")

    visit["encounter_status"] = "COMPLETED"
    visit["completed_at"] = store.now()
    visit["documented_elements"] = list(elements)
    visit["deadline_status"] = domain.visit_deadline_status(visit)
    store.touch(visit)

    episode["visit_completed_at"] = store.now()
    store.touch(episode)
    domain.recompute_visit_timely(episode)

    return envelope.ok(serialize(visit))


# ---------------------------------------------------------- close encounter
@bp.post("/tcm/visits/<visit_id>/close-encounter")
def close_encounter(visit_id):
    user_id, role = G.auth(["CareNavigator"])
    data = G.body()
    outcome = G.req_string(data, "outcome")
    G.enum(outcome, C.VISIT_CLOSE_OUTCOMES, "outcome")

    visit = G.get_row("visits", visit_id)
    episode = DB["episodes"][visit["episode_id"]]
    G.require_episode_owner(episode, user_id, role)
    G.require_open_records(episode)

    if outcome == "NO_SHOW":
        if visit["encounter_status"] != "SCHEDULED":
            raise ApiError("ERR_INVALID_STATE", "Only a SCHEDULED encounter may be a no-show.")
    else:
        if visit["encounter_status"] not in ("SCHEDULED", "NO_SHOW"):
            raise ApiError("ERR_INVALID_STATE", "The encounter cannot be cancelled from here.")

    visit["encounter_status"] = outcome
    visit["deadline_status"] = domain.visit_deadline_status(visit)
    store.touch(visit)
    return envelope.ok(serialize(visit))


# --------------------------------------------------------------- reschedule
@bp.post("/tcm/visits/<visit_id>/reschedule")
def reschedule_visit(visit_id):
    user_id, role = G.auth(["CareNavigator"])
    data = G.body()
    start, end = _interval(data)

    visit = G.get_row("visits", visit_id)
    episode = DB["episodes"][visit["episode_id"]]
    G.require_episode_owner(episode, user_id, role)
    G.require_open_records(episode)

    if visit["encounter_status"] != "NO_SHOW":
        raise ApiError("ERR_INVALID_STATE", "Only a NO_SHOW visit may be rescheduled.")
    if domain.slot_conflict(visit["navigator_id"], start, end, exclude_visit_id=visit["id"]):
        raise ApiError("ERR_SCHEDULE_CONFLICT")

    visit["scheduled_start"] = start
    visit["scheduled_end"] = end
    visit["encounter_status"] = "SCHEDULED"
    visit["confirmation_status"] = "UNCONFIRMED"
    visit["deadline_status"] = domain.visit_deadline_status(visit)
    store.touch(visit)
    return envelope.ok(serialize(visit))


# ------------------------------------------------------------------- attest
@bp.post("/tcm/visits/<visit_id>/attest")
def attest_visit(visit_id):
    user_id, _role = G.auth(["Clinician"])
    visit = G.get_row("visits", visit_id)
    episode = DB["episodes"][visit["episode_id"]]
    G.require_open_records(episode)

    if visit["encounter_status"] != "COMPLETED":
        raise ApiError("ERR_INVALID_STATE", "The encounter has not been completed.")
    if visit["documentation_status"] not in ("DRAFT", "AMENDED"):
        raise ApiError("ERR_INVALID_STATE", "The documentation is already attested.")

    recon = domain.episode_medrec(episode)
    if (
        recon is None
        or recon["status"] != "COMPLETED"
        or recon["completed_at"] is None
        or recon["completed_at"] > visit["completed_at"]
    ):
        raise ApiError("ERR_MEDREC_NOT_COMPLETE")
    if recon["blocking_unresolved_count"] != 0:
        raise ApiError("ERR_BLOCKING_DISCREPANCY_UNRESOLVED")
    if not set(C.MODERATE_REQUIRED_ELEMENTS).issubset(set(visit["documented_elements"])):
        raise ApiError("ERR_REQUIRED_ELEMENTS_INCOMPLETE")

    visit["documentation_status"] = "ATTESTED"
    visit["attested_by_user_id"] = user_id
    visit["attested_at"] = store.now()
    visit["achieved_complexity"] = _achieved_complexity(visit["documented_elements"])
    store.touch(visit)
    return envelope.ok(serialize(visit))


# -------------------------------------------------------------------- amend
@bp.post("/tcm/visits/<visit_id>/amend")
def amend_visit(visit_id):
    G.auth(["Clinician"])
    data = G.body()
    elements = G.req_array(data, "documented_elements")
    expected_version = G.req_int(data, "expected_visit_version")
    G.enum_members(elements, C.DOCUMENTED_ELEMENT_MEMBERS, "documented_elements")

    visit = G.get_row("visits", visit_id)
    episode = DB["episodes"][visit["episode_id"]]
    G.require_open_records(episode)

    if visit["documentation_status"] not in ("ATTESTED", "AMENDED"):
        raise ApiError("ERR_INVALID_STATE", "Only attested documentation may be amended.")
    if expected_version != visit["version"]:
        raise ApiError("ERR_STALE_VERSION")

    visit["documented_elements"] = list(elements)
    visit["documentation_status"] = "AMENDED"
    visit["amendment_count"] += 1
    visit["achieved_complexity"] = _achieved_complexity(elements)
    store.touch(visit)
    return envelope.ok(serialize(visit))
