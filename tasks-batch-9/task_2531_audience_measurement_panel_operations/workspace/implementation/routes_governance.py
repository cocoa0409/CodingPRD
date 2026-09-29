"""Methodology change governance, client notifications and accreditation audits."""
from datetime import timedelta

from flask import Blueprint

from auth import (ACCREDITATION_AUDITOR, ALL_ROLES, CLIENT_USER,
                  GOVERNANCE_DIRECTOR, actor_id, roles)
from calculations import AUDIT_OUTCOMES, impact_delta
from common import check_expected_version, must, unique_str_list
from errors import ApiError
from response import apply_filters, created, listing, ok
from services import (delete_weight_rows, hold_deliverables_of_runs,
                      recompute_market)
from store import created_key, db
from util import (D, bad_request, format_iso, get_body, parse_iso,
                  require_fields, want_enum, want_str, want_str_list)

bp = Blueprint("governance", __name__)

OPEN_CHANGE_STATES = ("DRAFT", "IMPACT_ASSESSED", "NOTIFIED")


# --------------------------------------------------------- methodology changes
@bp.post("/methodology-changes")
@roles(GOVERNANCE_DIRECTOR)
def draft_change():
    body = get_body()
    target = proposed = superseded = None
    if body.get("target_edit_rule_set_id") is not None:
        target = must("edit_rule_sets", body["target_edit_rule_set_id"])
    if body.get("proposed_edit_rule_set_id") is not None:
        proposed = must("edit_rule_sets", body["proposed_edit_rule_set_id"])
    if body.get("supersedes_change_id") is not None:
        superseded = must("methodology_changes", body["supersedes_change_id"])
    require_fields(body, ["title", "target_edit_rule_set_id",
                          "proposed_edit_rule_set_id", "affected_market_ids"])
    title = want_str(body, "title", min_len=1, max_len=160)
    markets = unique_str_list(body, "affected_market_ids",
                              want_str_list(body, "affected_market_ids"),
                              min_items=1, max_items=10)
    if superseded is not None and superseded["state"] not in OPEN_CHANGE_STATES:
        raise bad_request("supersedes_change_id must name a change in DRAFT, "
                          "IMPACT_ASSESSED or NOTIFIED")
    if (proposed["id"] == target["id"] or target["status"] != "PUBLISHED"):
        raise ApiError("ERR_RULE_SET_NOT_DISTINCT",
                       "the target must be the currently PUBLISHED rule set "
                       "and must differ from the proposal")
    change = db.insert("methodology_changes", {
        "title": title,
        "target_edit_rule_set_id": target["id"],
        "proposed_edit_rule_set_id": proposed["id"],
        "supersedes_change_id": superseded["id"] if superseded else None,
        "affected_market_ids": list(markets),
        "state": "DRAFT",
        "baseline_processing_run_id": None,
        "baseline_projected_average_audience": None,
        "impact_delta_pct": D("0.0000"),
        "impact_tier": None,
        "notification_lead_hours": None,
        "notification_deadline_at": None,
        "notified_client_count": 0,
        "acknowledged_client_count": 0,
        "revision_count": 0,
        "created_by_user_id": actor_id(),
        "activated_at": None,
    })
    return created(change)


@bp.post("/methodology-changes/<methodology_change_id>/impact-analyses")
@roles(GOVERNANCE_DIRECTOR)
def assess_change(methodology_change_id):
    change = must("methodology_changes", methodology_change_id)
    body = get_body()
    baseline = None
    if body.get("baseline_processing_run_id") is not None:
        baseline = must("processing_runs", body["baseline_processing_run_id"])
    require_fields(body, ["baseline_processing_run_id",
                          "expected_methodology_change_version"])
    check_expected_version(body, "expected_methodology_change_version", change,
                           "ERR_STALE_METHODOLOGY_CHANGE_VERSION")
    if baseline["state"] != "PUBLISHED":
        raise ApiError("ERR_RUN_NOT_PUBLISHED",
                       "the baseline run must be PUBLISHED")
    if change["state"] != "DRAFT":
        raise ApiError("ERR_CHANGE_NOT_DRAFT",
                       "only a DRAFT change is assessed")
    if (baseline["edit_rule_set_id"] != change["target_edit_rule_set_id"]
            or baseline["market_id"] not in change["affected_market_ids"]):
        raise ApiError("ERR_BASELINE_RUN_INVALID",
                       "the baseline run does not match the change's scope")
    target = db.get("edit_rule_sets", change["target_edit_rule_set_id"])
    proposed = db.get("edit_rule_sets", change["proposed_edit_rule_set_id"])
    if target is None or target["status"] != "PUBLISHED":
        raise ApiError("ERR_RULE_SET_NOT_PUBLISHED",
                       "the target rule set must still be PUBLISHED")
    if proposed is None or proposed["status"] != "DRAFT":
        raise ApiError("ERR_RULE_SET_NOT_DRAFT",
                       "the proposed rule set must still be DRAFT")
    pct, tier, lead_hours = impact_delta(target, proposed)
    change["impact_delta_pct"] = pct
    change["impact_tier"] = tier
    change["notification_lead_hours"] = lead_hours
    change["baseline_processing_run_id"] = baseline["id"]
    change["baseline_projected_average_audience"] = \
        baseline["projected_average_audience"]
    change["state"] = "IMPACT_ASSESSED"
    db.touch(change)
    return ok(change)


@bp.post("/methodology-changes/<methodology_change_id>/notify")
@roles(GOVERNANCE_DIRECTOR)
def notify_change(methodology_change_id):
    change = must("methodology_changes", methodology_change_id)
    if change["state"] != "IMPACT_ASSESSED":
        raise ApiError("ERR_CHANGE_NOT_ASSESSED",
                       "only an IMPACT_ASSESSED change is disclosed")
    affected = [c for c in db.all("clients")
                if set(c["contract_market_ids"]) & set(change["affected_market_ids"])]
    if not affected:
        raise ApiError("ERR_NO_AFFECTED_CLIENTS",
                       "a change never becomes effective with nobody informed")
    affected.sort(key=created_key)
    count = 0
    for client in affected:
        db.insert("client_notifications", {
            "methodology_change_id": change["id"],
            "client_id": client["id"],
            "impact_tier": change["impact_tier"],
            "disclosed_delta_pct": change["impact_delta_pct"],
            "state": "SENT",
            "sent_at": db.now_iso(),
            "acknowledged_at": None,
        })
        count += 1
    change["state"] = "NOTIFIED"
    change["notified_client_count"] = count
    change["acknowledged_client_count"] = 0
    change["notification_deadline_at"] = format_iso(
        db.clock + timedelta(hours=change["notification_lead_hours"]))
    db.touch(change)
    return ok(change)


@bp.post("/methodology-changes/<methodology_change_id>/request-revision")
@roles(GOVERNANCE_DIRECTOR)
def revise_change(methodology_change_id):
    change = must("methodology_changes", methodology_change_id)
    body = get_body()
    require_fields(body, ["reason"])
    want_str(body, "reason", min_len=1)
    if change["state"] not in ("IMPACT_ASSESSED", "NOTIFIED"):
        raise ApiError("ERR_CHANGE_NOT_DRAFT",
                       "only an IMPACT_ASSESSED or NOTIFIED change is revised")
    change["state"] = "DRAFT"
    change["revision_count"] = change["revision_count"] + 1
    change["impact_delta_pct"] = None
    change["impact_tier"] = None
    change["notification_lead_hours"] = None
    change["notification_deadline_at"] = None
    change["baseline_processing_run_id"] = None
    change["baseline_projected_average_audience"] = None
    rows = db.where("client_notifications", methodology_change_id=change["id"])
    for row in sorted(rows, key=created_key):
        if row["state"] == "SENT":
            row["state"] = "CANCELLED"
            db.touch(row)
    surviving = [r for r in db.where("client_notifications",
                                     methodology_change_id=change["id"])
                 if r["state"] != "CANCELLED"]
    change["notified_client_count"] = len(surviving)
    change["acknowledged_client_count"] = len(
        [r for r in surviving if r["state"] == "ACKNOWLEDGED"])
    db.touch(change)
    return ok(change)


@bp.post("/methodology-changes/<methodology_change_id>/activate")
@roles(GOVERNANCE_DIRECTOR)
def activate_change(methodology_change_id):
    change = must("methodology_changes", methodology_change_id)
    if actor_id() == change["created_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "the director who drafted a change may not activate it")
    if change["state"] != "NOTIFIED":
        raise ApiError("ERR_CHANGE_NOT_NOTIFIED",
                       "only a NOTIFIED change is activated")
    if change["acknowledged_client_count"] != change["notified_client_count"]:
        raise ApiError("ERR_ACKNOWLEDGEMENTS_MISSING",
                       "every notified client must have acknowledged")
    deadline = change["notification_deadline_at"]
    if deadline is not None and db.clock < parse_iso(deadline):
        raise ApiError("ERR_NOTIFICATION_PERIOD_OPEN",
                       "the tier's lead time has not fully elapsed")
    proposed = db.get("edit_rule_sets", change["proposed_edit_rule_set_id"])
    if proposed is None or proposed["status"] != "DRAFT":
        raise ApiError("ERR_RULE_SET_NOT_DRAFT",
                       "the proposed rule set must still be DRAFT")
    target = db.get("edit_rule_sets", change["target_edit_rule_set_id"])
    # Link 1
    change["state"] = "EFFECTIVE"
    change["activated_at"] = db.now_iso()
    db.touch(change)
    proposed["status"] = "PUBLISHED"
    proposed["published_at"] = db.now_iso()
    db.touch(proposed)
    if target is not None:
        target["status"] = "SUPERSEDED"
        db.touch(target)
    # Link 2
    runs = [r for r in db.all("processing_runs")
            if target is not None and r["edit_rule_set_id"] == target["id"]
            and r["state"] in ("OPEN", "EDITED")]
    runs.sort(key=created_key)
    for run in runs:
        if run["state"] == "EDITED":
            delete_weight_rows(run)
            run["total_weight_mass"] = D("0.0000")
            run["projected_average_audience"] = None
        run["state"] = "PENDING_REPIN"
        run["repin_required_reason"] = "RULE_SET_SUPERSEDED"
        db.touch(run)
    # Links 3 and 4
    if runs:
        hold_deliverables_of_runs([r["id"] for r in runs],
                                  states=("SCHEDULED", "REQUESTED",
                                          "IN_PROGRESS"))
    return ok(change)


@bp.get("/methodology-changes/<methodology_change_id>")
@roles(*ALL_ROLES)
def read_change(methodology_change_id):
    return ok(must("methodology_changes", methodology_change_id))


@bp.get("/methodology-changes")
@roles(*ALL_ROLES)
def list_changes():
    rows = apply_filters(db.all("methodology_changes"), {
        "state": ("state", "str"),
        "target_edit_rule_set_id": ("target_edit_rule_set_id", "str"),
        "proposed_edit_rule_set_id": ("proposed_edit_rule_set_id", "str"),
        "supersedes_change_id": ("supersedes_change_id", "str"),
    })
    return listing("methodology_changes", rows)


# ----------------------------------------------------------- notifications
@bp.post("/client-notifications/<client_notification_id>/acknowledge")
@roles(CLIENT_USER)
def acknowledge_notification(client_notification_id):
    row = must("client_notifications", client_notification_id)
    if actor_id() != row["client_id"]:
        raise ApiError("ERR_UNAUTHORIZED",
                       "a ClientUser acknowledges only its own notification")
    if row["state"] != "SENT":
        raise ApiError("ERR_NOTIFICATION_NOT_SENT",
                       "only a SENT notification is acknowledged")
    change = db.get("methodology_changes", row["methodology_change_id"])
    if change is None or change["state"] != "NOTIFIED":
        raise ApiError("ERR_CHANGE_NOT_NOTIFIED",
                       "the owning change must still be NOTIFIED")
    row["state"] = "ACKNOWLEDGED"
    row["acknowledged_at"] = db.now_iso()
    db.touch(row)
    change["acknowledged_client_count"] = change["acknowledged_client_count"] + 1
    db.touch(change)
    return ok(row)


@bp.get("/client-notifications/<client_notification_id>")
@roles(*ALL_ROLES)
def read_notification(client_notification_id):
    return ok(must("client_notifications", client_notification_id))


@bp.get("/client-notifications")
@roles(*ALL_ROLES)
def list_notifications():
    rows = apply_filters(db.all("client_notifications"), {
        "methodology_change_id": ("methodology_change_id", "str"),
        "client_id": ("client_id", "str"),
        "state": ("state", "str"),
        "impact_tier": ("impact_tier", "str"),
    })
    return listing("client_notifications", rows)


# ------------------------------------------------------- accreditation audits
@bp.post("/accreditation-audits")
@roles(ACCREDITATION_AUDITOR)
def open_audit():
    body = get_body()
    market = rule_set = None
    if body.get("market_id") is not None:
        market = must("markets", body["market_id"])
    if body.get("scope_edit_rule_set_id") is not None:
        rule_set = must("edit_rule_sets", body["scope_edit_rule_set_id"])
    require_fields(body, ["market_id", "scope_edit_rule_set_id", "auditor_note"])
    note = want_str(body, "auditor_note", min_len=1, max_len=400)
    if rule_set["status"] != "PUBLISHED":
        raise ApiError("ERR_RULE_SET_NOT_PUBLISHED",
                       "the scoped rule set must be PUBLISHED")
    for other in db.where("accreditation_audits", market_id=market["id"]):
        if other["state"] == "OPEN":
            raise ApiError("ERR_AUDIT_ALREADY_OPEN",
                           "the market already holds an OPEN audit")
    audit = db.insert("accreditation_audits", {
        "market_id": market["id"],
        "scope_edit_rule_set_id": rule_set["id"],
        "auditor_note": note,
        "state": "OPEN",
        "outcome": None,
        "limitation_disclosures": [],
        "opened_by_user_id": actor_id(),
        "finalized_by_user_id": None,
        "finalized_at": None,
    })
    recompute_market(market)
    return created(audit)


@bp.post("/accreditation-audits/<accreditation_audit_id>/finalize")
@roles(ACCREDITATION_AUDITOR)
def finalize_audit(accreditation_audit_id):
    audit = must("accreditation_audits", accreditation_audit_id)
    body = get_body()
    require_fields(body, ["outcome", "limitation_disclosures"])
    outcome = want_enum(body, "outcome", AUDIT_OUTCOMES)
    disclosures = want_str_list(body, "limitation_disclosures", min_items=0)
    if actor_id() == audit["opened_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "the auditor who opened an audit may not sign it off")
    if audit["state"] != "OPEN":
        raise ApiError("ERR_AUDIT_NOT_OPEN", "only an OPEN audit is finalized")
    if outcome in ("QUALIFIED", "DENIED") and len(disclosures) < 1:
        raise ApiError("ERR_DISCLOSURE_REQUIRED",
                       "a qualified or denied methodology must say what is wrong")
    audit["state"] = "FINALIZED"
    audit["outcome"] = outcome
    audit["limitation_disclosures"] = list(disclosures)
    audit["finalized_by_user_id"] = actor_id()
    audit["finalized_at"] = db.now_iso()
    db.touch(audit)
    market = db.get("markets", audit["market_id"])
    if market is not None:
        market["accreditation_status"] = outcome
        market["publication_blocked"] = (outcome == "DENIED")
        if outcome in ("QUALIFIED", "DENIED"):
            market["limitation_disclosures"] = (
                list(market["limitation_disclosures"]) + list(disclosures))
        db.touch(market)
        recompute_market(market)
    return ok(audit)


@bp.get("/accreditation-audits/<accreditation_audit_id>")
@roles(*ALL_ROLES)
def read_audit(accreditation_audit_id):
    return ok(must("accreditation_audits", accreditation_audit_id))


@bp.get("/accreditation-audits")
@roles(*ALL_ROLES)
def list_audits():
    rows = apply_filters(db.all("accreditation_audits"), {
        "market_id": ("market_id", "str"),
        "scope_edit_rule_set_id": ("scope_edit_rule_set_id", "str"),
        "state": ("state", "str"),
        "outcome": ("outcome", "str"),
    })
    return listing("accreditation_audits", rows)
