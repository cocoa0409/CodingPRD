"""Valuation runs: create DRAFT, post (actuarial revaluation cascade, PRD 3.9)."""
from flask import Blueprint, g

import store
from calc import (
    FREQ_DIVISOR,
    annual_annuity,
    annuity_factor,
    div_rhu,
    lives_factor,
    oldest_age,
    reserve_requirement,
    rhu_float,
    whole_years_between,
)
from domain import (
    active_table_covering,
    lookup,
    sort_created,
    update_reserve,
    view,
)
from envelope import success
from errors import ApiError
from security import ALL_ROLES, require_roles
from store import base_fields, iso, now, touch
from validate import get_body, parse_dt, validate_body

bp = Blueprint("valuations", __name__)


def _closed_overlap(a_start, a_end, b_start, b_end):
    """Closed intervals: sharing a single boundary date IS an overlap."""
    return a_start <= b_end and b_start <= a_end


@bp.post("/giving/valuation-runs")
@require_roles("ComplianceOfficer")
def create_valuation_run():
    body = get_body()
    validate_body(
        body,
        {
            "coverage_start": ("datetime", True, None),
            "coverage_end": ("datetime", True, None),
            "valuation_date": ("datetime", True, None),
            "corpus_updates": ("any", False, None),
        },
    )
    start = parse_dt(body["coverage_start"])
    end = parse_dt(body["coverage_end"])
    valuation_date = parse_dt(body["valuation_date"])
    # valuation_date must lie within its own (closed) coverage window
    if not (start <= valuation_date <= end):
        raise ApiError(
            "ERR_INVALID_REQUEST",
            400,
            "valuation_date must lie within the coverage window",
        )
    updates = body.get("corpus_updates") or []
    if not isinstance(updates, list):
        raise ApiError("ERR_INVALID_REQUEST", 400, "corpus_updates must be a list")
    for entry in updates:
        if not isinstance(entry, dict):
            raise ApiError(
                "ERR_INVALID_REQUEST", 400, "corpus_updates entries must be objects"
            )
        for key in entry:
            if key not in ("agreement_id", "new_corpus_cents"):
                raise ApiError(
                    "ERR_INVALID_REQUEST", 400, "Unknown field: %s" % key
                )
        aid = entry.get("agreement_id")
        if not isinstance(aid, str):
            raise ApiError(
                "ERR_INVALID_REQUEST", 400, "corpus_updates require agreement_id"
            )
        ncc = entry.get("new_corpus_cents")
        if not isinstance(ncc, int) or isinstance(ncc, bool):
            raise ApiError(
                "ERR_INVALID_REQUEST",
                400,
                "corpus_updates require new_corpus_cents",
            )
        lookup(store.agreements, aid, "GiftAgreement")

    run = base_fields()
    run.update(
        {
            "coverage_start": body["coverage_start"],
            "coverage_end": body["coverage_end"],
            "valuation_date": body["valuation_date"],
            "corpus_updates": updates,
            "status": "DRAFT",
            "created_by_user_id": g.user_id,
            "posted_by_user_id": None,
            "agreements_revalued_count": None,
            "total_liability_cents": None,
            "total_remainder_cents": None,
            "posted_at": None,
        }
    )
    store.valuation_runs[run["id"]] = run
    return success(view(run), 201)


@bp.get("/giving/valuation-runs/<valuation_run_id>")
@require_roles(*ALL_ROLES)
def get_valuation_run(valuation_run_id):
    return success(
        view(lookup(store.valuation_runs, valuation_run_id, "ValuationRun")), 200
    )


@bp.post("/giving/valuation-runs/<valuation_run_id>/post")
@require_roles("ComplianceOfficer")
def post_valuation_run(valuation_run_id):
    run = lookup(store.valuation_runs, valuation_run_id, "ValuationRun")
    validate_body(get_body(), {})  # no input fields

    # SoD (priority 3): poster differs from the run creator
    if g.user_id == run["created_by_user_id"]:
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES",
            403,
            "Poster must differ from the run creator",
        )
    # state (6)
    if run["status"] != "DRAFT":
        raise ApiError(
            "ERR_VALUATION_ALREADY_POSTED", 409, "Valuation run already POSTED"
        )
    # closed-window overlap vs other POSTED runs (19)
    start = parse_dt(run["coverage_start"])
    end = parse_dt(run["coverage_end"])
    for other in store.valuation_runs.values():
        if other["id"] == run["id"] or other["status"] != "POSTED":
            continue
        o_start = parse_dt(other["coverage_start"])
        o_end = parse_dt(other["coverage_end"])
        if _closed_overlap(start, end, o_start, o_end):
            raise ApiError(
                "ERR_VALUATION_WINDOW_OVERLAP",
                409,
                "Coverage window intersects another POSTED run",
            )
    # ACTIVE rate table covering valuation_date (20)
    valuation_date = parse_dt(run["valuation_date"])
    table = active_table_covering(valuation_date)
    if table is None:
        raise ApiError(
            "ERR_NO_ACTIVE_RATE_TABLE",
            422,
            "No ACTIVE rate table covers valuation_date",
        )
    r_now = table["discount_rate_bps"]

    corpus_updates = {
        e["agreement_id"]: e["new_corpus_cents"] for e in (run["corpus_updates"] or [])
    }

    # HOP 1: revalue in-scope agreements in created_at ASC order
    in_scope = sort_created(
        [
            a
            for a in store.agreements.values()
            if a["status"] in ("FUNDED", "ACTIVE", "SUSPENDED")
            and a["vehicle_type"] != "BEQUEST"
        ]
    )
    revalued = []
    total_liability = 0
    total_remainder = 0
    for agreement in in_scope:
        years = whole_years_between(agreement["funding_month"], valuation_date)
        age1 = agreement.get("annuitant_1_age")
        age2 = agreement.get("annuitant_2_age")
        lives = agreement.get("lives", 1)
        age1_now = age1 + years if age1 is not None else None
        age2_now = age2 + years if age2 is not None else None

        # corpus updates apply to CRT_UNITRUST before revaluation
        if (
            agreement["vehicle_type"] == "CRT_UNITRUST"
            and agreement["id"] in corpus_updates
        ):
            agreement["corpus_value_cents"] = corpus_updates[agreement["id"]]
            # unitrust annuity is annually revalued off current corpus
            agreement["annual_annuity_cents"] = annual_annuity(
                agreement["corpus_value_cents"], agreement["payout_rate_bps"]
            )

        factor = lives_factor(age1_now, age2_now, lives, r_now)
        liability = rhu_float(agreement["annual_annuity_cents"] * factor)
        agreement["actuarial_liability_cents"] = liability
        agreement["remainder_value_cents"] = max(
            0, (agreement.get("corpus_value_cents") or 0) - liability
        )
        if agreement["vehicle_type"] == "CGA":
            agreement["reserve_requirement_cents"] = reserve_requirement(
                agreement["annual_annuity_cents"], age1_now, age2_now, lives
            )
        touch(agreement)
        revalued.append(agreement)
        total_liability += liability
        total_remainder += agreement["remainder_value_cents"]

    # HOP 2: CRT_UNITRUST SCHEDULED payment amounts recompute off the new annuity
    for agreement in revalued:
        if agreement["vehicle_type"] != "CRT_UNITRUST":
            continue
        divisor = FREQ_DIVISOR[agreement.get("payment_frequency", "QUARTERLY")]
        new_amount = div_rhu(agreement["annual_annuity_cents"], divisor)
        for p in store.payments.values():
            if (
                p["gift_agreement_id"] == agreement["id"]
                and p["status"] == "SCHEDULED"
            ):
                if p["amount_cents"] != new_amount:
                    p["amount_cents"] = new_amount
                    touch(p)
    # HOP 3: total_scheduled_cents is live-computed over all payments
    # HOP 4: reserve targets / coverage / posture recompute from new requirements
    update_reserve()

    run["agreements_revalued_count"] = len(revalued)
    run["total_liability_cents"] = total_liability
    run["total_remainder_cents"] = total_remainder
    run["posted_at"] = iso(now())
    run["posted_by_user_id"] = g.user_id
    run["status"] = "POSTED"
    touch(run)
    return success(view(run), 200)
