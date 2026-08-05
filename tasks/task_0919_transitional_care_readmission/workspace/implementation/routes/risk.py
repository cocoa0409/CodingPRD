"""Risk re-assessment and its four-hop cascade (PRD 3.2)."""
from flask import Blueprint

import constants as C
import domain
import envelope
import guards as G
import store
from routes.referrals import new_risk_assessment
from store import DB, serialize

bp = Blueprint("risk", __name__)


@bp.post("/tcm/episodes/<episode_id>/risk-assessments")
def create_risk_assessment(episode_id):
    user_id, role = G.auth(["CareNavigator"])
    data = G.body()
    inputs = {
        "comorbidity_count": G.req_int(data, "comorbidity_count", minimum=0, maximum=30),
        "prior_ed_visits_6mo": G.req_int(data, "prior_ed_visits_6mo", minimum=0, maximum=30),
        "prior_admissions_6mo": G.req_int(data, "prior_admissions_6mo", minimum=0, maximum=30),
        "social_risk_flags_count": G.req_int(
            data, "social_risk_flags_count", minimum=0, maximum=12
        ),
    }
    episode = G.get_episode(episode_id)
    G.require_episode_owner(episode, user_id, role)
    G.require_open_records(episode)

    referral = DB["referrals"][episode["referral_id"]]

    # hop 1 - supersede the current assessment
    previous = DB["risk_assessments"].get(episode["current_risk_assessment_id"])
    if previous is not None:
        previous["is_current"] = False
        store.touch(previous)
    assessment = new_risk_assessment(
        episode, referral, inputs, previous["id"] if previous is not None else None
    )

    # hop 2 - rewrite every tier-driven programme parameter
    domain.apply_tier_to_episode(episode, assessment)
    store.touch(episode)

    # hop 3 - push the new figures down onto every non-terminal visit
    flipped = []
    visits = [
        v
        for v in DB["visits"].values()
        if v["episode_id"] == episode["id"]
        and v["encounter_status"] not in ("COMPLETED", "CANCELLED")
    ]
    visits.sort(key=lambda v: (v["created_at"], v["_seq"]))
    for visit in visits:
        before = visit["deadline_status"]
        visit["required_complexity"] = episode["required_visit_complexity"]
        visit["visit_due_date"] = episode["visit_due_date"]
        visit["deadline_status"] = domain.visit_deadline_status(visit)
        store.touch(visit)
        if visit["deadline_status"] == "SCHEDULED_LATE" and before != "SCHEDULED_LATE":
            flipped.append(visit)

    # hop 4 - each flipped visit spawns its own red flag
    for _visit in flipped:
        domain.create_red_flag(
            episode,
            "VISIT_WINDOW_AT_RISK",
            C.VISIT_WINDOW_AT_RISK_RED_FLAG_TIER,
            user_id,
        )

    domain.recompute_contact_timely(episode)
    domain.recompute_navigator(episode["navigator_id"])

    return envelope.created(serialize(assessment))


@bp.get("/tcm/risk-assessments/<risk_assessment_id>")
def read_risk_assessment(risk_assessment_id):
    G.auth(C.ALL_ROLES)
    return envelope.ok(serialize(G.get_row("risk_assessments", risk_assessment_id)))


@bp.get("/tcm/risk-assessments")
def list_risk_assessments():
    G.auth(C.ALL_ROLES)
    limit, offset = G.pagination()
    f = G.filters("episode_id", "supersedes_id", "is_current")

    def keep(row):
        for key, value in f.items():
            if key == "is_current":
                if row["is_current"] != G.bool_filter(value):
                    return False
            elif row.get(key) != value:
                return False
        return True

    rows = store.sorted_rows("risk_assessments", keep)
    page = rows[offset : offset + limit]
    return envelope.listing([serialize(r) for r in page], limit, offset, len(rows))
