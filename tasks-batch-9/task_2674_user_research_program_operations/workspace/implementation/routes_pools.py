"""Participant pools, panel enrollment and incentive settlement (PRD 3.2, 3.9)."""
from flask import Blueprint

import serializers
from auth import ALL_ROLES, require_roles
from calc import SCREENOUT_STIPEND_CENTS, recompute_pool, set_field
from envelope import created, ok, paged_listing
from errors import ApiError
from store import by_created, db
from validators import (
    body,
    filter_str,
    filter_enum,
    opt_bool,
    participant_or_404,
    pool_or_404,
    ref,
    req_enum,
    req_int,
    req_str,
    study_or_404,
)

bp = Blueprint("pools", __name__)

POOL_TYPES = ("CUSTOMER_LIST", "EXTERNAL_PANEL", "INTERNAL_DOGFOOD")
PARTICIPANT_STATUSES = ("ELIGIBLE", "COOLDOWN", "SUPPRESSED")
SETTLEMENT_MODES = ("FORWARD_ESTIMATE", "CHRONOLOGICAL_ACTUAL")
ESTIMATE_STATUSES = ("INVITED", "SCREENED_IN", "SCHEDULED", "COMPLETED")


@bp.post("/participant-pools")
@require_roles("ResearchOpsAdmin")
def create_pool():
    data = body()
    name = req_str(data, "name")
    pool_type = req_enum(data, "pool_type", POOL_TYPES)
    cap = req_int(data, "contact_cap_per_window", minimum=1)
    window = req_int(data, "contact_window_days", minimum=1)
    budget = req_int(data, "incentive_budget_cents", minimum=0)
    if any(p["name"] == name for p in db.pools.values()):
        raise ApiError("ERR_DUPLICATE_LABEL", "A pool with that name already exists.")
    row = db.new("pools", {
        "name": name,
        "pool_type": pool_type,
        "contact_cap_per_window": cap,
        "contact_window_days": window,
        "incentive_budget_cents": budget,
        "incentive_reserved_cents": 0,
        "incentive_paid_cents": 0,
        "incentive_available_cents": budget,
        "last_estimate_cents": None,
        "settled_study_ids": [],
        "status": "OPEN",
        "participant_count": 0,
        "suppressed_participant_count": 0,
    })
    return created(serializers.pool(row))


@bp.post("/participant-pools/<pool_id>/participants")
@require_roles("ResearchOpsAdmin")
def enroll_participant(pool_id):
    pool = pool_or_404(pool_id)
    data = body()
    external_ref = req_str(data, "external_ref")
    segment = req_str(data, "segment")
    locale = req_str(data, "locale")
    pii_on_file = opt_bool(data, "pii_on_file", True)
    for person in db.participants.values():
        if person["pool_id"] == pool["id"] and person["external_ref"] == external_ref:
            raise ApiError(
                "ERR_DUPLICATE_EXTERNAL_REF",
                "That external_ref is already enrolled in this pool.",
            )
    row = db.new("participants", {
        "pool_id": pool["id"],
        "external_ref": external_ref,
        "segment": segment,
        "locale": locale,
        "pii_on_file": pii_on_file,
        "last_contacted_at": None,
        "contacts_in_window": 0,
        "no_show_strikes": 0,
        "status": "ELIGIBLE",
    })
    recompute_pool(pool)
    return created(serializers.participant(row))


@bp.get("/participant-pools/<pool_id>")
@require_roles(*ALL_ROLES)
def read_pool(pool_id):
    return ok(serializers.pool(pool_or_404(pool_id)))


@bp.get("/participant-pools/<pool_id>/participants")
@require_roles(*ALL_ROLES)
def list_pool_participants(pool_id):
    pool = pool_or_404(pool_id)
    status = filter_enum("status", PARTICIPANT_STATUSES)
    segment = filter_str("segment")
    rows = [p for p in db.participants.values() if p["pool_id"] == pool["id"]]
    if status is not None:
        rows = [p for p in rows if p["status"] == status]
    if segment is not None:
        rows = [p for p in rows if p["segment"] == segment]
    return paged_listing(by_created(rows), serializers.participant)


@bp.get("/participants/<participant_id>")
@require_roles(*ALL_ROLES)
def read_participant(participant_id):
    return ok(serializers.participant(participant_or_404(participant_id)))


@bp.post("/participant-pools/<pool_id>/incentive-settlements")
@require_roles("ResearchOpsAdmin")
def settle_incentives(pool_id):
    pool = pool_or_404(pool_id)
    data = body()
    study = study_or_404(ref(data, "study_id"))
    req_str(data, "study_id")
    mode = req_enum(data, "mode", SETTLEMENT_MODES)
    expected = req_int(data, "expected_pool_version")
    if mode == "CHRONOLOGICAL_ACTUAL":
        if study["execution_status"] not in ("ANALYSIS", "REPORTED", "CLOSED"):
            raise ApiError(
                "ERR_SETTLEMENT_NOT_PERMITTED",
                "A binding settlement requires the study to have closed fielding.",
            )
        if study["id"] in pool["settled_study_ids"]:
            raise ApiError("ERR_ALREADY_SETTLED", "That study has already been settled bindingly.")
    if expected != pool["version"]:
        raise ApiError("ERR_STALE_POOL_VERSION", "The supplied expected_pool_version is stale.")

    rows = _pool_study_recruitments(pool, study)
    if mode == "FORWARD_ESTIMATE":
        estimate = sum(
            r["reserved_cents"] for r in rows
            if r["incentive_state"] == "RESERVED" and r["status"] in ESTIMATE_STATUSES
        )
        set_field(pool, "last_estimate_cents", estimate)
    else:
        _chronological_actual(pool, study, rows)
    recompute_pool(pool)
    db.mark(pool)
    return ok(serializers.pool(pool))


def _pool_study_recruitments(pool, study):
    out = []
    for row in db.recruitments.values():
        if row["study_id"] != study["id"]:
            continue
        person = db.participants.get(row["participant_id"])
        if person is None or person["pool_id"] != pool["id"]:
            continue
        out.append(row)
    return out


def _chronological_actual(pool, study, rows):
    """Release first, then pay the lesser of entitlement and money on hand, so
    the ledger partition holds at every step of the walk."""
    candidates = [r for r in rows if r["incentive_state"] == "RESERVED"]
    candidates.sort(key=lambda r: (
        r["created_at"],
        db.participants[r["participant_id"]]["external_ref"],
        r["_seq"],
    ))
    for row in candidates:
        set_field(pool, "incentive_reserved_cents", pool["incentive_reserved_cents"] - row["reserved_cents"])
        recompute_pool(pool)
        if row["status"] == "COMPLETED":
            entitlement = row["reserved_cents"]
        elif row["status"] == "SCREENED_OUT":
            entitlement = SCREENOUT_STIPEND_CENTS
        else:
            entitlement = 0
        payment = min(entitlement, pool["incentive_available_cents"])
        if payment > 0:
            set_field(row, "paid_cents", payment)
            set_field(row, "incentive_state", "PAID")
            set_field(pool, "incentive_paid_cents", pool["incentive_paid_cents"] + payment)
        else:
            set_field(row, "incentive_state", "RELEASED")
        recompute_pool(pool)
    set_field(pool, "settled_study_ids", list(pool["settled_study_ids"]) + [study["id"]])
