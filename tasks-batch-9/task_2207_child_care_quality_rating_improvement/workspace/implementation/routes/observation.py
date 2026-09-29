"""Observers, on-site observation visits and subscale scores (PRD §3.4)."""

from datetime import timedelta

from flask import Blueprint, request

import calculations as calc
import lookups
import response
import serializers
import store
import validation as v
from auth import require
from errors import fail
from validation import as_date, as_dt, body

bp = Blueprint("observation", __name__)

DECISIONS = ["CERTIFY", "LAPSE", "RETIRE"]

# A visit occupying an observer's calendar (PRD §3.4); CANCELLED never conflicts.
OCCUPYING_STATES = ("SCHEDULED", "IN_PROGRESS", "SCORES_ENTERED",
                    "RELIABILITY_CHECK", "FINALIZED")
SCORING_STATES = ("SCHEDULED", "IN_PROGRESS", "SCORES_ENTERED", "RELIABILITY_CHECK")
FINALIZE_ORIGINS = ("RELIABILITY_CHECK", "SCORES_ENTERED")

SAME_PROVIDER_BUFFER = timedelta(hours=48)


# ----------------------------------------------------------------- helpers


def _self_assessment_of(cycle_id):
    for sa in store.sort_created(list(store.DB.self_assessments.values())):
        if sa["rating_cycle_id"] == cycle_id:
            return sa
    return None


def _visits_of_observer(observer_id):
    out = []
    for visit in store.DB.observation_visits.values():
        if observer_id in (visit.get("lead_observer_id"),
                           visit.get("secondary_observer_id")):
            out.append(visit)
    return store.sort_created(out)


def _provider_of_visit(visit):
    cycle = store.DB.rating_cycles.get(visit["rating_cycle_id"])
    return cycle["provider_id"] if cycle else None


def _named_observers(visit):
    """The lead observer, plus the secondary observer when the visit names one."""
    ids = [visit.get("lead_observer_id")]
    if visit.get("secondary_observer_id"):
        ids.append(visit["secondary_observer_id"])
    out = []
    for observer_id in ids:
        observer = store.DB.observers.get(observer_id)
        if observer is not None:
            out.append(observer)
    return out


def _require_reliable(visit):
    """The reliability rule — every observer named on the visit, not just the actor."""
    window_date = as_date(visit.get("window_start"))
    for observer in _named_observers(visit):
        if observer["status"] != "RELIABLE":
            fail("ERR_OBSERVER_NOT_RELIABLE",
                 "observer %s is in %s standing" % (observer["id"], observer["status"]))
        until = as_date(observer.get("reliability_certified_until"))
        if until is None or (window_date is not None and until < window_date):
            fail("ERR_OBSERVER_NOT_RELIABLE",
                 "observer %s is not certified through the visit window" % observer["id"])


def _provisional_determination(cycle):
    """The provisional tier-determination run (PRD §3.5), compliance refreshed first."""
    provider = store.DB.providers.get(cycle["provider_id"])
    sa = _self_assessment_of(cycle["id"])
    if provider is not None:
        calc.refresh_credential_compliance(provider)
    points = calc.compute_domain_points(cycle, "PROVISIONAL", provider or {}, sa)
    return calc.compute_tier_determination(cycle, points, "PROVISIONAL")


def _bool_arg(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    text = str(raw).strip().lower()
    if text in ("true", "1"):
        return True
    if text in ("false", "0"):
        return False
    fail("ERR_VALIDATION", "%s must be true or false" % name)


# ----------------------------------------------------------------- observers


@bp.post("/observers")
def create_observer():
    require("StateAdministrator")
    data = body()
    full_name = v.req_str(data, "full_name")
    tool_code = v.req_enum(data, "tool_code", v.TOOL_CODES)

    rec = store.base_record(
        full_name=full_name,
        tool_code=tool_code,
        anchor_agreement_pct=None,
        reliability_certified_until=None,
        status="PROVISIONAL",
    )
    store.DB.observers[rec["id"]] = rec
    return response.created(serializers.dump("observer", rec))


@bp.get("/observers")
def list_observers():
    require("StateAdministrator", "Observer")
    records = store.sort_created(list(store.DB.observers.values()))
    for field in ("status", "tool_code"):
        value = request.args.get(field)
        if value:
            records = [r for r in records if r.get(field) == value]
    return response.paginate(records, serializers.maker("observer"))


@bp.post("/observers/<observer_id>/reliability-certifications")
def reliability_certification(observer_id):
    require("StateAdministrator")
    observer = lookups.get_observer(observer_id)
    data = body()
    decision = v.req_enum(data, "decision", DECISIONS)
    agreement = v.opt_decimal(data, "anchor_agreement_pct", minimum=0, maximum=100,
                              max_places=2)
    certified_until = v.opt_instant(data, "certified_until")

    if decision == "CERTIFY":
        if agreement is None:
            fail("ERR_VALIDATION", "a certify decision requires anchor_agreement_pct")
        if agreement >= calc.ANCHOR_AGREEMENT_THRESHOLD:
            if certified_until is None:
                fail("ERR_VALIDATION",
                     "a certify decision at or above 85.00 requires certified_until")
            observer["anchor_agreement_pct"] = agreement
            observer["reliability_certified_until"] = certified_until
            observer["status"] = "RELIABLE"
        else:
            observer["anchor_agreement_pct"] = agreement
            observer["reliability_certified_until"] = None
            observer["status"] = "LAPSED"
    elif decision == "LAPSE":
        if agreement is not None:
            observer["anchor_agreement_pct"] = agreement
        observer["status"] = "LAPSED"
    else:
        observer["status"] = "RETIRED"

    store.touch(observer)
    return response.ok(serializers.dump("observer", observer))


# ---------------------------------------------------------- visit scheduling


def _conflicts(observer_id, cycle, window_start, window_end):
    """Half-open overlap across providers, plus the same-provider 48-hour buffer."""
    new_start = as_dt(window_start)
    new_end = as_dt(window_end)
    provider_id = cycle["provider_id"]
    for visit in _visits_of_observer(observer_id):
        if visit["status"] not in OCCUPYING_STATES:
            continue
        existing_start = as_dt(visit.get("window_start"))
        existing_end = as_dt(visit.get("window_end"))
        if existing_start is None or existing_end is None:
            continue
        if new_start < existing_end and existing_start < new_end:
            return True
        if _provider_of_visit(visit) == provider_id and \
                new_start < existing_end + SAME_PROVIDER_BUFFER:
            return True
    return False


@bp.post("/rating-cycles/<rating_cycle_id>/observation-visits")
def schedule_visit(rating_cycle_id):
    require("StateAdministrator")
    cycle = lookups.get_cycle(rating_cycle_id)
    data = body()
    lead_observer_id = v.req_str(data, "lead_observer_id")
    secondary_observer_id = v.opt_str(data, "secondary_observer_id")
    if secondary_observer_id is not None and secondary_observer_id.strip() == "":
        secondary_observer_id = None
    window_start = v.req_instant(data, "window_start")
    window_end = v.req_instant(data, "window_end")
    if secondary_observer_id is not None and secondary_observer_id == lead_observer_id:
        fail("ERR_VALIDATION", "secondary_observer_id must differ from lead_observer_id")

    # Body foreign keys (PRD §2.6): both observer references resolve.
    lookups.get_observer(lead_observer_id)
    if secondary_observer_id is not None:
        lookups.get_observer(secondary_observer_id)

    if cycle["status"] != "DOCS_VERIFIED":
        fail("ERR_CYCLE_STATE_INVALID",
             "an observation may be scheduled only from DOCS_VERIFIED")

    draft = {
        "lead_observer_id": lead_observer_id,
        "secondary_observer_id": secondary_observer_id,
        "window_start": window_start,
    }
    # Safety rule 1: reliability of every observer named on the visit.
    _require_reliable(draft)

    # Safety rule 2: the occupation rule, checked per observer independently.
    for observer_id in [lead_observer_id, secondary_observer_id]:
        if observer_id is None:
            continue
        if _conflicts(observer_id, cycle, window_start, window_end):
            fail("ERR_OBSERVER_SCHEDULE_CONFLICT",
                 "observer %s is already occupied across this window" % observer_id)

    rec = store.base_record(
        rating_cycle_id=cycle["id"],
        lead_observer_id=lead_observer_id,
        secondary_observer_id=secondary_observer_id,
        window_start=window_start,
        window_end=window_end,
        status="SCHEDULED",
        composite=None,
        reliability_pct=None,
        rescore_count=0,
        finalized_on=None,
    )
    store.DB.observation_visits[rec["id"]] = rec
    cycle["status"] = "OBSERVATION_SCHEDULED"
    store.touch(cycle)
    return response.created(serializers.dump("observation_visit", rec))


@bp.get("/observation-visits")
def list_visits():
    require("StateAdministrator", "Observer", "Provider", "AppealReviewer")
    records = store.sort_created(list(store.DB.observation_visits.values()))
    for field in ("rating_cycle_id", "lead_observer_id", "secondary_observer_id", "status"):
        value = request.args.get(field)
        if value:
            records = [r for r in records if r.get(field) == value]
    return response.paginate(records, serializers.maker("observation_visit"))


@bp.get("/observation-visits/<observation_visit_id>")
def read_visit(observation_visit_id):
    principal = require("StateAdministrator", "Observer", "Provider", "AppealReviewer")
    visit = lookups.get_visit(observation_visit_id)
    lookups.own_via_cycle(principal, visit["rating_cycle_id"])
    return response.ok(serializers.dump("observation_visit", visit))


# --------------------------------------------------------------------- scores


def _rows_for(visit_id, observer_id, subscale_code):
    return [r for r in store.DB.observation_scores.values()
            if r["observation_visit_id"] == visit_id
            and r["observer_id"] == observer_id
            and r["subscale_code"] == subscale_code]


def _refresh_composite(visit):
    if calc.has_full_set(visit["id"], visit["lead_observer_id"]):
        visit["composite"] = calc.compute_composite(visit)


def _refresh_reliability(visit):
    secondary = visit.get("secondary_observer_id")
    if secondary and calc.has_full_set(visit["id"], visit["lead_observer_id"]) \
            and calc.has_full_set(visit["id"], secondary):
        visit["reliability_pct"] = calc.compute_reliability(visit)


@bp.post("/observation-visits/<observation_visit_id>/scores")
def submit_score(observation_visit_id):
    principal = require("Observer")
    visit = lookups.get_visit(observation_visit_id)
    lookups.own_observer_on_visit(principal, visit)
    data = body()
    subscale_code = v.req_enum(data, "subscale_code", v.SUBSCALE_CODES)
    raw_score = v.req_subscale_score(data, "raw_score")

    # Gate 1: the visit's own state (PRD §2.7 step 10).
    if visit["status"] not in SCORING_STATES:
        fail("ERR_VISIT_STATE_INVALID",
             "a score may not be recorded against a visit in %s" % visit["status"])
    if visit["status"] == "SCHEDULED" and store.now() < as_dt(visit["window_start"]):
        fail("ERR_VISIT_STATE_INVALID",
             "the first score is admissible only once the observation window has opened")

    # Gate 2: the reliability rule, re-checked at score submission (PRD §3.4).
    _require_reliable(visit)

    # Gate 3: the bounded rescore loop.
    rescoring = visit["status"] == "RELIABILITY_CHECK"
    if rescoring and int(visit["rescore_count"]) >= 2:
        fail("ERR_RESCORE_LIMIT_EXCEEDED",
             "this visit has already been rescored twice")

    prior = _rows_for(visit["id"], principal.user_id, subscale_code)
    attempt_no = 1
    for row in prior:
        if int(row["attempt_no"]) >= attempt_no:
            attempt_no = int(row["attempt_no"]) + 1
        if row.get("is_current"):
            row["is_current"] = False

    rec = store.base_record(
        observation_visit_id=visit["id"],
        observer_id=principal.user_id,
        subscale_code=subscale_code,
        raw_score=raw_score,
        attempt_no=attempt_no,
        is_current=True,
    )
    store.DB.observation_scores[rec["id"]] = rec

    before = (visit["status"], visit.get("composite"), visit.get("reliability_pct"),
              visit.get("rescore_count"))

    if rescoring:
        # RELIABILITY_CHECK -> SCORES_ENTERED: the rescore loop.
        visit["status"] = "SCORES_ENTERED"
        visit["rescore_count"] = int(visit["rescore_count"]) + 1
        _refresh_composite(visit)
        _refresh_reliability(visit)
    else:
        if visit["status"] == "SCHEDULED":
            visit["status"] = "IN_PROGRESS"
        if visit["status"] == "IN_PROGRESS" and \
                calc.has_full_set(visit["id"], visit["lead_observer_id"]):
            visit["status"] = "SCORES_ENTERED"
            visit["composite"] = calc.compute_composite(visit)
        secondary = visit.get("secondary_observer_id")
        if visit["status"] == "SCORES_ENTERED" and secondary and \
                calc.has_full_set(visit["id"], secondary) and \
                calc.has_full_set(visit["id"], visit["lead_observer_id"]):
            visit["status"] = "RELIABILITY_CHECK"
            visit["reliability_pct"] = calc.compute_reliability(visit)
        if visit["status"] in ("SCORES_ENTERED", "RELIABILITY_CHECK"):
            _refresh_composite(visit)

    after = (visit["status"], visit.get("composite"), visit.get("reliability_pct"),
             visit.get("rescore_count"))
    if after != before:
        store.touch(visit)

    return response.created(serializers.dump("observation_score", rec))


@bp.get("/observation-scores")
def list_scores():
    require("StateAdministrator", "Observer", "AppealReviewer")
    records = store.sort_created(list(store.DB.observation_scores.values()))
    for field in ("observation_visit_id", "observer_id", "subscale_code"):
        value = request.args.get(field)
        if value:
            records = [r for r in records if r.get(field) == value]
    is_current = _bool_arg("is_current")
    if is_current is not None:
        records = [r for r in records if bool(r.get("is_current")) == is_current]
    return response.paginate(records, serializers.maker("observation_score"))


@bp.get("/observation-scores/<observation_score_id>")
def read_score(observation_score_id):
    require("StateAdministrator", "Observer", "AppealReviewer")
    score = lookups.get_score(observation_score_id)
    return response.ok(serializers.dump("observation_score", score))


# --------------------------------------------------------- finalize / cancel


@bp.post("/observation-visits/<observation_visit_id>/finalize")
def finalize_visit(observation_visit_id):
    require("StateAdministrator")
    visit = lookups.get_visit(observation_visit_id)
    cycle = lookups.get_cycle(visit["rating_cycle_id"])
    body()

    if cycle["status"] != "OBSERVATION_SCHEDULED":
        fail("ERR_CYCLE_STATE_INVALID",
             "finalization requires the cycle in OBSERVATION_SCHEDULED")
    if visit["status"] not in FINALIZE_ORIGINS:
        fail("ERR_VISIT_STATE_INVALID",
             "a visit in %s may not be finalized" % visit["status"])

    secondary = visit.get("secondary_observer_id")

    # Check 1: the observer reliability rule.
    _require_reliable(visit)

    # Check 2: the secondary-observer requirement.
    if not secondary:
        determination = _provisional_determination(cycle)
        if int(determination["awarded_tier"]) >= 4:
            fail("ERR_SECONDARY_OBSERVER_REQUIRED",
                 "a provisional tier of 4 or higher requires a reliability-checked visit")

    # Check 3: the reliability threshold, when a secondary observer participated.
    if secondary and visit.get("reliability_pct") is not None and \
            calc.dec(visit["reliability_pct"]) < calc.RELIABILITY_THRESHOLD:
        fail("ERR_RELIABILITY_BELOW_THRESHOLD",
             "inter-rater reliability is below 83.33")

    # Check 4: the score-completeness rule.
    if not calc.has_full_set(visit["id"], visit["lead_observer_id"]):
        fail("ERR_OBSERVATION_SCORES_INCOMPLETE",
             "the lead observer has not scored all six subscales")
    if secondary and not calc.has_full_set(visit["id"], secondary):
        fail("ERR_OBSERVATION_SCORES_INCOMPLETE",
             "the secondary observer has not scored all six subscales")

    composite = calc.compute_composite(visit)
    reliability = None
    if secondary:
        reliability = calc.compute_reliability(visit)
        if reliability < calc.RELIABILITY_THRESHOLD:
            fail("ERR_RELIABILITY_BELOW_THRESHOLD",
                 "inter-rater reliability is below 83.33")

    visit["composite"] = composite
    visit["reliability_pct"] = reliability
    visit["status"] = "FINALIZED"
    visit["finalized_on"] = store.now()
    store.touch(visit)

    provider = store.DB.providers.get(cycle["provider_id"])
    sa = _self_assessment_of(cycle["id"])
    if provider is not None:
        calc.refresh_credential_compliance(provider)
    cycle["observation_composite"] = composite
    cycle["reliability_pct"] = reliability
    cycle["status"] = "OBSERVATION_FINALIZED"
    cycle["domain_points"] = calc.compute_domain_points(cycle, "FINAL", provider or {}, sa)
    store.touch(cycle)

    return response.ok(serializers.dump("observation_visit", visit))


@bp.post("/observation-visits/<observation_visit_id>/cancel")
def cancel_visit(observation_visit_id):
    require("StateAdministrator")
    visit = lookups.get_visit(observation_visit_id)
    cycle = lookups.get_cycle(visit["rating_cycle_id"])
    data = body()
    v.opt_str(data, "reason")

    if visit["status"] not in ("SCHEDULED", "IN_PROGRESS"):
        fail("ERR_VISIT_STATE_INVALID",
             "a visit in %s may not be cancelled" % visit["status"])

    visit["status"] = "CANCELLED"
    store.touch(visit)
    for row in store.DB.observation_scores.values():
        if row["observation_visit_id"] == visit["id"] and row.get("is_current"):
            row["is_current"] = False
    if cycle["status"] == "OBSERVATION_SCHEDULED":
        cycle["status"] = "DOCS_VERIFIED"
        store.touch(cycle)

    return response.ok(serializers.dump("observation_visit", visit))
