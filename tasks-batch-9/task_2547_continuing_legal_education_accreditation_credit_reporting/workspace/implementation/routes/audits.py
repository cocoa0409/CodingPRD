"""Provider audit engagements: opening, sampling, findings and closure (PRD 3.9)."""
from flask import Blueprint

import calc
import constants as C
import db
import listing
import middleware
import response
import util
from errors import fail
from routes.providers import load_provider
from services import cascades

bp = Blueprint("audits", __name__)

TRIGGER_TYPES = ["RISK_BASED", "COMPLAINT_ESCALATION", "RANDOM"]
AUDIT_ACTIONS = ["DRAW_SAMPLE", "ISSUE_FINDINGS", "CLOSE_CLEARED", "CLOSE_SANCTIONED"]
SANCTION_TYPES = ["PROBATION", "SUSPENSION"]
LIVE_AUDIT_STATUSES = ("OPENED", "SAMPLED", "FINDINGS_ISSUED")


def load_audit(audit_id):
    audit = db.get("provider_audits", audit_id)
    if audit is None:
        fail("ERR_AUDIT_NOT_FOUND", "No audit matches that identifier.")
    return audit


def _complaint_provider_id(complaint):
    if complaint.get("subject_type") == "PROVIDER":
        return complaint.get("subject_id")
    course = db.get("courses", complaint.get("subject_id"))
    return course.get("provider_id") if course is not None else None


@bp.route("/cle/provider-audits", methods=["POST"])
def open_audit():
    middleware.require_roles([C.ROLE_BOARD_ADMIN])
    body = middleware.body_json()

    # Step 4: body foreign-key existence, provider_id before originating_complaint_id.
    provider = load_provider(body.get("provider_id")) if middleware.present(body, "provider_id") else None
    complaint = None
    if middleware.present(body, "originating_complaint_id"):
        complaint = db.get("complaints", body.get("originating_complaint_id"))
        if complaint is None:
            fail("ERR_COMPLAINT_NOT_FOUND", "No complaint matches that identifier.")

    # Step 6: request shape.
    if provider is None:
        fail("ERR_INVALID_REQUEST", "provider_id is required.")
    period_start = middleware.req_instant(body, "audit_period_start")
    period_end = middleware.req_instant(body, "audit_period_end")
    trigger_type = middleware.req_enum(body, "trigger_type", TRIGGER_TYPES)
    if complaint is not None and trigger_type != "COMPLAINT_ESCALATION":
        fail(
            "ERR_INVALID_REQUEST",
            "originating_complaint_id requires a trigger_type of COMPLAINT_ESCALATION.",
        )

    # Step 14: referential coherence between the complaint and the audited provider.
    if complaint is not None and _complaint_provider_id(complaint) != provider["id"]:
        fail("ERR_COURSE_PROVIDER_MISMATCH", "That complaint does not resolve to the audited provider.")

    # Step 15: temporal coherence — closed windows may neither overlap nor abut.
    for other in db.all_rows("provider_audits"):
        if other.get("provider_id") != provider["id"]:
            continue
        other_start = util.parse_dt(other.get("audit_period_start"))
        other_end = util.parse_dt(other.get("audit_period_end"))
        if other_start is None or other_end is None:
            continue
        if period_start <= other_end and other_start <= period_end:
            fail("ERR_AUDIT_PERIOD_OVERLAP", "That window overlaps or abuts an existing audit window.")
    for other in db.all_rows("provider_audits"):
        if other.get("provider_id") != provider["id"]:
            continue
        if other.get("status") in LIVE_AUDIT_STATUSES:
            fail("ERR_AUDIT_ENGAGEMENT_ACTIVE", "That provider already holds a live engagement.")

    # Step 16: a complaint seeds at most one audit.
    if complaint is not None and complaint.get("escalated"):
        fail("ERR_COMPLAINT_ALREADY_ESCALATED", "That complaint has already escalated into an audit.")

    score, _variant = calc.compute_risk_score(provider)
    audit = db.insert(
        "provider_audits",
        {
            "provider_id": provider["id"],
            "originating_complaint_id": complaint["id"] if complaint is not None else None,
            "audit_period_start": util.iso(period_start),
            "audit_period_end": util.iso(period_end),
            "trigger_type": trigger_type,
            "risk_score_at_open": float(score),
            "sample_size": 0,
            "sampled_course_ids": [],
            "findings_count": 0,
            "status": "OPENED",
            "sanction_type": "NONE",
            "closed_at": None,
        },
    )
    if complaint is not None:
        cascades.set_fields(complaint, {"escalated": True})
    return response.success(db.serialize(audit), 201)


@bp.route("/cle/provider-audits/<audit_id>", methods=["GET"])
def read_audit(audit_id):
    middleware.require_roles([C.ROLE_BOARD_ADMIN, C.ROLE_REVIEWER, C.ROLE_PROVIDER_ADMIN])
    return response.success(db.serialize(load_audit(audit_id)), 200)


@bp.route("/cle/provider-audits", methods=["GET"])
def list_audits():
    middleware.require_roles([C.ROLE_BOARD_ADMIN, C.ROLE_REVIEWER, C.ROLE_PROVIDER_ADMIN])
    rows = listing.apply_filters(
        db.all_rows("provider_audits"),
        ["provider_id", "originating_complaint_id", "status", "trigger_type"],
    )
    return listing.page(listing.sort_by(rows, "audit_period_start"))


def _record_closure(provider, audit, closed_at):
    """last_audit_closed_at is the latest closing instant (PRD 2.12)."""
    if provider is None:
        return
    current = provider.get("last_audit_closed_at")
    if current is None or closed_at >= current:
        cascades.set_fields(provider, {"last_audit_closed_at": closed_at})


@bp.route("/cle/provider-audits/<audit_id>/audit-actions", methods=["POST"])
def audit_action(audit_id):
    middleware.require_roles([C.ROLE_BOARD_ADMIN])
    audit = load_audit(audit_id)
    body = middleware.body_json()

    # Step 6: request shape.
    action = middleware.req_enum(body, "action", AUDIT_ACTIONS)
    expected = middleware.req_int(body, "expected_audit_version")
    findings_count = middleware.opt_int(body, "findings_count", 0, None, None)
    sanction_type = middleware.opt_enum(body, "sanction_type", SANCTION_TYPES, None)
    if action == "ISSUE_FINDINGS" and findings_count is None:
        fail("ERR_INVALID_REQUEST", "findings_count is required with ISSUE_FINDINGS.")
    if action == "CLOSE_SANCTIONED" and sanction_type is None:
        fail("ERR_INVALID_REQUEST", "sanction_type is required with CLOSE_SANCTIONED.")

    # Step 7: optimistic concurrency.
    if expected != audit.get("version"):
        fail("ERR_STALE_VERSION", "expected_audit_version does not match the audit's version.")

    status = audit.get("status")
    provider = db.get("providers", audit.get("provider_id"))

    if action == "DRAW_SAMPLE":
        if status not in ("OPENED", "SAMPLED"):
            fail("ERR_INVALID_STATE_TRANSITION", "DRAW_SAMPLE is not declared from %s." % status)
        pool = calc.audit_sample_pool(audit)
        # Step 16: an empty pool writes nothing at all.
        if len(pool) == 0:
            fail("ERR_NO_SAMPLE_POPULATION", "No course of that provider falls inside the audit window.")
        target = calc.sample_target(audit.get("risk_score_at_open"))
        size = min(target, len(pool))
        prior = int(audit.get("sample_size") or 0)
        cascades.set_fields(
            audit,
            {
                "status": "SAMPLED",
                "sample_size": size,
                "sampled_course_ids": [course["id"] for course in pool[:size]],
            },
        )
        if provider is not None:
            cascades.set_fields(
                provider,
                {
                    "courses_sampled_lifetime": int(provider.get("courses_sampled_lifetime") or 0)
                    + (size - prior)
                },
            )
    elif action == "ISSUE_FINDINGS":
        if status != "SAMPLED":
            fail("ERR_INVALID_STATE_TRANSITION", "ISSUE_FINDINGS is not declared from %s." % status)
        # Step 16: more findings than courses examined.
        if findings_count > int(audit.get("sample_size") or 0):
            fail("ERR_FINDINGS_EXCEED_SAMPLE", "findings_count exceeds the audit's sample_size.")
        cascades.set_fields(audit, {"status": "FINDINGS_ISSUED", "findings_count": findings_count})
        if provider is not None:
            cascades.set_fields(
                provider,
                {"audit_findings_count": int(provider.get("audit_findings_count") or 0) + findings_count},
            )
            cascades.refresh_risk(provider)
    elif action == "CLOSE_CLEARED":
        if status != "FINDINGS_ISSUED":
            fail("ERR_INVALID_STATE_TRANSITION", "CLOSE_CLEARED is not declared from %s." % status)
        if int(audit.get("findings_count") or 0) > C.AUDIT_CLEAR_MAX_FINDINGS:
            fail("ERR_INVALID_STATE_TRANSITION", "A cleared closure allows at most one finding.")
        closed_at = util.now_iso()
        cascades.set_fields(
            audit, {"status": "CLEARED", "closed_at": closed_at, "sanction_type": "NONE"}
        )
        _record_closure(provider, audit, closed_at)
        if provider is not None:
            cascades.refresh_risk(provider)
    else:  # CLOSE_SANCTIONED
        if status != "FINDINGS_ISSUED":
            fail("ERR_INVALID_STATE_TRANSITION", "CLOSE_SANCTIONED is not declared from %s." % status)
        if int(audit.get("findings_count") or 0) < 1:
            fail("ERR_INVALID_STATE_TRANSITION", "A sanctioned closure requires at least one finding.")
        closed_at = util.now_iso()
        cascades.set_fields(
            audit, {"status": "SANCTIONED", "closed_at": closed_at, "sanction_type": sanction_type}
        )
        _record_closure(provider, audit, closed_at)
        if provider is not None:
            cascades.assess_fee("AUDIT_SANCTION", C.AUDIT_SANCTION_FEE_CENTS, provider=provider)
            standing = provider.get("accreditation_status")
            if sanction_type == "PROBATION":
                if standing == "ACCREDITED":
                    cascades.move_provider_status(provider, "PROBATIONARY")
                    # probation_reason records the audit that caused the reversion (PRD 3.1).
                    cascades.set_fields(
                        provider,
                        {"probation_reason": "Audit sanction %s" % audit["id"]},
                    )
            else:
                if standing in ("ACCREDITED", "PROBATIONARY"):
                    cascades.move_provider_status(provider, "SUSPENDED")
                    cascades.suspend_self_certified_courses(provider)
            # The variant reflects the provider's post-cascade standing (PRD 3.9).
            cascades.refresh_risk(provider)
    # A successful audit action mutates the audit row, so its version rises by
    # exactly one even when a repeated redraw recomputes the identical sample.
    db.touch(audit)
    return response.success(db.serialize(audit), 200)
