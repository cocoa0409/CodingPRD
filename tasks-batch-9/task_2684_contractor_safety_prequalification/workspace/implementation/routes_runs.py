"""The two periodic runs (PRD 3.11)."""
from decimal import Decimal

from flask import Blueprint

import auth
import calc
import cascade
import derive
import response
import validators as V
from store import S, now, sort_created, touch

bp = Blueprint("runs", __name__)


@bp.route("/clients/<client_id>/requalification-runs", methods=["POST"])
def requalification_run(client_id):
    user_id, role = auth.authenticate([auth.ROLE_CLIENT_SAFETY_MANAGER])
    V.no_body()
    client = V.get_client(client_id)
    auth.check_owner(role, user_id, client_id=client["id"])
    clock = now()

    population = derive.preqs_of_client(client["id"])

    # --- Step 1: cure deadlines -------------------------------------------------
    step1 = []
    for preq in population:
        if preq["status"] != "CONDITIONAL":
            continue
        if preq["conditional_expires_at"] is None or preq["conditional_expires_at"] > clock:
            continue
        if any(p["status"] == "ACCEPTED" for p in derive.plans_of(preq["id"])):
            continue
        step1.append(preq)
    step1.sort(key=lambda r: (r["conditional_expires_at"], r["created_at"], r["_seq"]))
    conditional_rejected_ids = []
    for preq in step1:
        cascade.reject_prequal_uncured(preq)
        conditional_rejected_ids.append(preq["id"])

    # --- Step 2: annual expiry --------------------------------------------------
    step2 = []
    for preq in population:
        if preq["status"] not in ("APPROVED", "CONDITIONAL", "SUSPENDED"):
            continue
        if preq["expires_at"] is None or preq["expires_at"] > clock:
            continue
        step2.append(preq)
    step2.sort(key=lambda r: (r["expires_at"], r["created_at"], r["_seq"]))
    expired_ids = []
    for preq in step2:
        cascade.expire_prequal(preq)
        expired_ids.append(preq["id"])

    client_preq_ids = set(p["id"] for p in population)
    stale_grants = [
        g
        for g in S.site_access_grants.values()
        if g["prequalification_id"] in client_preq_ids
        and g["status"] == "GRANTED"
        and g["expires_at"] < clock
    ]
    for grant in sort_created(stale_grants):
        cascade.expire_grant(grant)

    # --- Step 3: overdue plans --------------------------------------------------
    overdue_plan_count = 0
    plans = []
    for preq in population:
        plans.extend(derive.plans_of(preq["id"]))
    for plan in sort_created(plans):
        if plan["status"] in ("OPEN", "SUBMITTED") and plan["due_date"] <= clock:
            plan["status"] = "OVERDUE"
            plan["closed_at"] = clock
            touch(plan)
            overdue_plan_count += 1

    # --- Step 4: insurance refresh ---------------------------------------------
    lapsed_certificate_count = 0
    contractor_ids = []
    for preq in population:
        if preq["contractor_id"] not in contractor_ids:
            contractor_ids.append(preq["contractor_id"])
    for contractor_id in contractor_ids:
        contractor = S.contractors[contractor_id]
        for cert in derive.certs_of(contractor_id):
            before = cert["lifecycle_status"]
            after = calc.lifecycle_status(cert, clock)
            if after == "LAPSED" and before != "LAPSED":
                lapsed_certificate_count += 1
        derive.rematerialize_certificates(contractor)
        derive.recompute_verified_coverage_types(contractor)

    return response.ok(
        {
            "expired_count": len(expired_ids),
            "expired_prequalification_ids": expired_ids,
            "conditional_rejected_count": len(conditional_rejected_ids),
            "conditional_rejected_prequalification_ids": conditional_rejected_ids,
            "overdue_plan_count": overdue_plan_count,
            "lapsed_certificate_count": lapsed_certificate_count,
        }
    )


@bp.route("/clients/<client_id>/audit-sampling-runs", methods=["POST"])
def audit_sampling_run(client_id):
    user_id, role = auth.authenticate([auth.ROLE_CLIENT_SAFETY_MANAGER])
    V.no_body()
    client = V.get_client(client_id)
    auth.check_owner(role, user_id, client_id=client["id"])

    pool = [
        p
        for p in derive.preqs_of_client(client["id"])
        if p["status"] in ("APPROVED", "CONDITIONAL") and p["audit_state"] == "NOT_SELECTED"
    ]

    def rank_key(row):
        score = row["final_composite_score"]
        return (
            Decimal(score) if score is not None else Decimal("-1"),
            row["created_at"],
            row["_seq"],
        )

    pool.sort(key=rank_key)
    draw = calc.audit_draw_size(len(pool), client["audit_sample_rate_pct"])
    selected = pool[:draw]
    selected_ids = []
    for preq in selected:
        preq["audit_state"] = "SELECTED"
        preq["audit_selected_at"] = now()
        touch(preq)
        selected_ids.append(preq["id"])

    return response.ok(
        {"selected_count": len(selected_ids), "selected_prequalification_ids": selected_ids}
    )
