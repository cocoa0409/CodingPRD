"""Post-certification audit sampling and findings (PRD 3.10)."""
from flask import Blueprint

import calc
import cascades as cas
import enums
import helpers as h
import serializers as ser
from db import cfg, db, new_id
from errors import ApiError

bp = Blueprint("audit", __name__)

SAMPLE_READ_ROLES = ("ProgramAdministrator", "ProgramAuditor", "DealerPrincipal")


def sample_or_404(sample_id):
    row = db.audit_samples.get(sample_id)
    if row is None:
        raise ApiError("ERR_AUDIT_SAMPLE_NOT_FOUND", "No audit sample with that id.")
    return row


# --------------------------------------------------------------------------- #
# POST /cpo/audit-runs
# --------------------------------------------------------------------------- #
@bp.route("/audit-runs", methods=["POST"])
def draw_audit_run():
    h.authorize(("ProgramAuditor",))
    config = cfg()

    pool = []
    for certification in db.certifications.values():
        if certification["status"] != "ACTIVE" or certification["audit_sampled"]:
            continue
        if certification["activated_at"] is None or certification["activated_at"] > db.clock:
            continue
        dealer = db.dealers.get(certification["dealer_id"])
        if dealer is None or dealer["privilege_status"] not in ("ACTIVE", "PROBATION"):
            continue
        pool.append((dealer, certification))

    pool.sort(
        key=lambda pair: (
            -pair[0]["risk_score"],
            pair[1]["activated_at"],
            pair[1]["created_at"],
            pair[1]["_seq"],
        )
    )

    pool_size = len(pool)
    fraction = calc.ceil_mul(config["audit_sample_pct"], pool_size)
    select_count = min(pool_size, max(config["audit_sample_min_per_run"], fraction))

    db.audit_run_count += 1
    audit_run_id = "AR-%d" % db.audit_run_count

    selected_ids = []
    touched_dealers = {}
    for rank, (dealer, certification) in enumerate(pool[:select_count], start=1):
        sample = h.new_common(
            {
                "id": new_id(),
                "certification_id": certification["id"],
                "audit_run_id": audit_run_id,
                "selection_rank": rank,
                "status": "SELECTED",
                "finding_code": None,
                "reviewed_at": None,
                "reviewer_user_id": None,
            }
        )
        db.audit_samples[sample["id"]] = sample
        certification["status"] = "UNDER_AUDIT"
        certification["audit_sampled"] = True
        h.touch(certification)
        selected_ids.append(certification["id"])
        touched_dealers[dealer["id"]] = dealer

    for dealer in touched_dealers.values():
        cas.recompute_dealer_audit(dealer)
        h.touch(dealer)

    return h.object_response(
        {
            "audit_run_id": audit_run_id,
            "pool_size": pool_size,
            "selected_count": len(selected_ids),
            "selected_certification_ids": selected_ids,
        },
        201,
    )


@bp.route("/certifications/<certification_id>/audit-samples", methods=["GET"])
def list_samples(certification_id):
    user_id, role, _principal = h.authorize(SAMPLE_READ_ROLES)
    status = h.q_enum("status", enums.AUDIT_SAMPLE_STATUSES)
    audit_run_id = h.q_string("audit_run_id")
    limit, offset = h.pagination()
    if certification_id not in db.certifications:
        raise ApiError("ERR_CERTIFICATION_NOT_FOUND", "No certification with that id.")
    # 3.10: the audit-sample collection is readable by an administrator, an
    # auditor, "and the owning `DealerPrincipal`".
    h.require_dealer_scope(
        user_id, role, db.certifications[certification_id]["dealer_id"]
    )
    rows = [
        s for s in db.audit_samples.values() if s["certification_id"] == certification_id
    ]
    if status:
        rows = [r for r in rows if r["status"] == status]
    if audit_run_id:
        rows = [r for r in rows if r["audit_run_id"] == audit_run_id]
    return h.paged(rows, limit, offset, ser.audit_sample)


# --------------------------------------------------------------------------- #
# POST /cpo/audit-samples/{id}/finding
# --------------------------------------------------------------------------- #
@bp.route("/audit-samples/<sample_id>/finding", methods=["POST"])
def record_finding(sample_id):
    user_id, _role, _principal = h.authorize(("ProgramAuditor",))
    config = cfg()
    body = h.body_dict()
    finding = h.f_enum(body, "finding", enums.FINDINGS)
    finding_code = h.f_enum(body, "finding_code", enums.FINDING_CODES, required=False)
    if finding == "FAIL" and (finding_code is None or finding_code == "NONE"):
        h.bad_request("A FAIL finding requires a finding_code other than NONE.")

    sample = sample_or_404(sample_id)
    certification = db.certifications.get(sample["certification_id"])

    if sample["status"] != "SELECTED":
        raise ApiError(
            "ERR_AUDIT_SAMPLE_ALREADY_REVIEWED", "That audit sample already has a finding."
        )
    if certification is None or certification["status"] != "UNDER_AUDIT":
        raise ApiError(
            "ERR_CERTIFICATION_NOT_ACTIVE",
            "The sampled certification is no longer UNDER_AUDIT.",
        )

    dealer = db.dealers.get(certification["dealer_id"])

    if finding == "PASS":
        sample["status"] = "PASSED"
        sample["finding_code"] = finding_code or "NONE"
        sample["reviewed_at"] = db.clock
        sample["reviewer_user_id"] = user_id
        h.touch(sample)
        certification["status"] = "ACTIVE"
        h.touch(certification)
        return h.object_response(ser.audit_sample(sample))

    # hop 1 — the sample fails and the dealer's audit counters move
    sample["status"] = "FAILED"
    sample["finding_code"] = finding_code
    sample["reviewed_at"] = db.clock
    sample["reviewer_user_id"] = user_id
    h.touch(sample)
    if dealer is not None:
        cas.recompute_dealer_audit(dealer)
        h.touch(dealer)

    # hops 2 and 3 — decertification, fee credit and the listing/complaint sweep
    cas.decertify_certification(certification, "POST_AUDIT_FAIL")

    # hops 4 and 5 — the audit-failure suspension threshold
    if (
        dealer is not None
        and dealer["audit_fail_count"] >= config["audit_fail_suspension_count"]
        and dealer["privilege_status"] != "SUSPENDED"
    ):
        cas.suspend_dealer(dealer, "AUDIT_FAILURE_SUSPENSION", ("SYNDICATED",))

    return h.object_response(ser.audit_sample(sample))
