"""SDOH screening: weighted scoring and the anchoring fork (PRD §3.2)."""

from decimal import Decimal

from flask import Blueprint

import calc
import cascades
import store
import validate as v
from clockutil import clock, elapsed_days
from envelope import created, listing, ok
from errors import (
    ApiError, ERR_INSTRUMENT_NOT_PUBLISHED, ERR_PATIENT_NOT_FOUND,
    ERR_RESOURCE_NOT_FOUND, ERR_STALE_PATIENT_VERSION,
)
from ladder import ALL_ROLES, CHW, Endpoint, SUPERVISOR, run
from serial import dump, dump_all

bp = Blueprint("screening", __name__)

EP_SCREENING_CREATE = Endpoint("screening.create", [CHW, SUPERVISOR], gated=True)
EP_SCREENING_READ = Endpoint("screening.read", ALL_ROLES,
                             path=[("screening_id", "screening")])
EP_SCREENING_LIST = Endpoint("screening.list", ALL_ROLES)

CURRENT_STATUSES = ("SUBMITTED", "AMENDED")


def current_screening(patient_id):
    for row in store.all_rows("screening"):
        if row.get("patient_id") == patient_id and row.get("status") in CURRENT_STATUSES:
            return row
    return None


@bp.post("/chw/screenings")
def create_screening():
    def payload(ctx):
        s = ctx.state
        s["patient_id"] = v.req_str(ctx.body, "patient_id")
        s["instrument_id"] = v.req_str(ctx.body, "instrument_id")
        scores = v.req_obj(ctx.body, "domain_scores")
        s["expected_patient_version"] = v.req_int(ctx.body, "expected_patient_version")
        for key, value in scores.items():
            if not v.is_int(value):
                v.bad("domain_scores values must be integers")
            if value < calc.SCREENING_DOMAIN_SCORE_MIN or value > calc.SCREENING_DOMAIN_SCORE_MAX:
                v.bad("domain_scores values must lie between 0 and 4")
        instrument = store.get("instrument", s["instrument_id"])
        if instrument is not None:
            if set(scores.keys()) != set(instrument["domain_weights"].keys()):
                v.bad("domain_scores keys must equal the instrument's domain_weights keys")
        s["domain_scores"] = dict(scores)

    def body_refs(ctx):
        patient = store.get("patient", ctx.state["patient_id"])
        if patient is None:
            raise ApiError(ERR_PATIENT_NOT_FOUND, "patient_id does not resolve")
        instrument = store.get("instrument", ctx.state["instrument_id"])
        if instrument is None:
            raise ApiError(ERR_RESOURCE_NOT_FOUND, "instrument_id does not resolve")
        ctx.state["patient"] = patient
        ctx.state["instrument"] = instrument

    def occ(ctx):
        if ctx.state["expected_patient_version"] != ctx.state["patient"]["version"]:
            raise ApiError(ERR_STALE_PATIENT_VERSION, "expected_patient_version is stale")

    def cross_entity(ctx):
        if ctx.state["instrument"]["status"] != "PUBLISHED":
            raise ApiError(ERR_INSTRUMENT_NOT_PUBLISHED,
                           "The screening instrument is not PUBLISHED")

    ctx = run(EP_SCREENING_CREATE,
              steps={5: [payload], 6: [body_refs], 7: [occ], 9: [cross_entity]})

    patient = ctx.state["patient"]
    instrument = ctx.state["instrument"]
    scores = ctx.state["domain_scores"]
    now = clock.now_raw()

    weighted_score, risk_tier = calc.weighted_risk_score(scores, instrument["domain_weights"])

    current = current_screening(patient["id"])
    variant = "FRESH_ANCHOR"
    if current is not None and current.get("instrument_id") == instrument["id"]:
        elapsed = elapsed_days(current["anchor_screened_at"], now)
        if elapsed is not None and elapsed < Decimal(instrument["rescreen_cadence_days"]):
            variant = "AMENDMENT_ANCHOR"

    if variant == "AMENDMENT_ANCHOR":
        row = current
        row["domain_scores"] = scores
        row["latest_response_at"] = now
        row["amendment_count"] = row.get("amendment_count", 0) + 1
        row["weighted_score"] = weighted_score
        row["risk_tier"] = risk_tier
        row["status"] = "AMENDED"
        store.touch(row)
        effective_at = row["anchor_screened_at"]
    else:
        if current is not None:
            current["status"] = "SUPERSEDED"
            store.touch(current)
        row = store.insert("screening", {
            "patient_id": patient["id"],
            "instrument_id": instrument["id"],
            "domain_scores": scores,
            "anchor_screened_at": now,
            "latest_response_at": now,
            "weighted_score": weighted_score,
            "risk_tier": risk_tier,
            "amendment_count": 0,
            "status": "SUBMITTED",
        })
        effective_at = now

    patient["risk_score"] = weighted_score
    patient["risk_tier"] = risk_tier
    patient["risk_tier_effective_at"] = effective_at
    if patient["enrollment_status"] == "PROSPECTIVE" and risk_tier in ("MODERATE", "HIGH", "CRITICAL"):
        patient["enrollment_status"] = "ENROLLED"
    store.touch(patient)

    if risk_tier == "CRITICAL":
        blocking = False
        for escalation in store.all_rows("escalation"):
            if escalation.get("source_screening_id") != row["id"]:
                continue
            if escalation.get("status") in cascades.OPEN_TIERS + ("ACKNOWLEDGED",):
                blocking = True
                break
        if not blocking:
            cascades.open_escalation(patient["id"], "CRITICAL_SDOH_FINDING",
                                     cascades.SYSTEM_ACTOR, source_screening_id=row["id"])

    return created(dump(row))


@bp.get("/chw/screenings/<screening_id>")
def read_screening(screening_id):
    ctx = run(EP_SCREENING_READ, {"screening_id": screening_id})
    return ok(dump(ctx.row("screening_id")))


@bp.get("/chw/screenings")
def list_screenings():
    def pagination(ctx):
        ctx.state["page"] = v.pagination(ctx.args)

    ctx = run(EP_SCREENING_LIST, steps={5: [pagination]})
    limit, offset = ctx.state["page"]
    rows = store.all_rows("screening")
    for key in ("patient_id", "instrument_id", "status"):
        wanted = ctx.args.get(key)
        if wanted is not None:
            rows = [r for r in rows if r.get(key) == wanted]
    page, total = v.paginate(rows, limit, offset)
    return listing(dump_all(page), limit, offset, total)
