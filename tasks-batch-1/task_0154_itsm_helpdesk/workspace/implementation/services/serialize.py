"""Entity serializers — produce the exact output field set per entity.

Counters that the PRD declares "recomputed" (queue_depth, linked_ticket_count,
open_incident_count, approve_count, reject_count) are recomputed at read time so
the response always reflects the true current set (PRD §2.6).
"""
from db import iso, store
from services.common import (
    recompute_queue_depth,
    recompute_linked_ticket_count,
    recompute_open_incident_count,
    recompute_change_tally,
)


def _common(rec, with_version=True):
    out = {"id": rec["id"], "created_at": iso(rec["created_at"])}
    if with_version:
        out["updated_at"] = iso(rec.get("updated_at"))
        out["version"] = rec.get("version")
    return out


def category(rec):
    out = _common(rec)
    out.update(
        {
            "name": rec["name"],
            "default_priority": rec["default_priority"],
            "sla_policy_id": rec["sla_policy_id"],
            "default_assignment_group_id": rec["default_assignment_group_id"],
            "active": rec["active"],
        }
    )
    return out


def sla_policy(rec):
    out = _common(rec)
    out.update(
        {
            "name": rec["name"],
            "response_target_minutes": rec["response_target_minutes"],
            "resolve_target_minutes": rec["resolve_target_minutes"],
            "ola_target_minutes": rec["ola_target_minutes"],
            "priority_multipliers": rec["priority_multipliers"],
        }
    )
    return out


def assignment_group(rec):
    recompute_queue_depth(rec["id"])
    out = _common(rec)
    out.update(
        {
            "name": rec["name"],
            "is_fulfilment_group": rec["is_fulfilment_group"],
            "queue_depth": rec["queue_depth"],
        }
    )
    return out


def ticket(rec):
    out = _common(rec)
    out.update(
        {
            "short_description": rec["short_description"],
            "requester_id": rec.get("requester_id"),
            "category_id": rec["category_id"],
            "priority": rec["priority"],
            "assignment_group_id": rec.get("assignment_group_id"),
            "assignee_user_id": rec.get("assignee_user_id"),
            "lifecycle_state": rec["lifecycle_state"],
            "sla_state": rec.get("sla_state"),
            "problem_id": rec.get("problem_id"),
            "deflected": rec.get("deflected", False),
            "reopen_count": rec.get("reopen_count", 0),
            "opened_at": iso(rec.get("opened_at")),
            "response_due_at": iso(rec.get("response_due_at")),
            "resolve_due_at": iso(rec.get("resolve_due_at")),
            "paused_total_minutes": rec.get("paused_total_minutes", 0),
            "change_request_id": rec.get("change_request_id"),
            "asset_id": rec.get("asset_id"),
            "resolved_at": iso(rec.get("resolved_at")),
        }
    )
    return out


def problem(rec):
    recompute_linked_ticket_count(rec["id"])
    out = _common(rec)
    out.update(
        {
            "title": rec["title"],
            "owner_user_id": rec["owner_user_id"],
            "state": rec["state"],
            "linked_ticket_count": rec["linked_ticket_count"],
            "asset_id": rec.get("asset_id"),
        }
    )
    return out


def known_error(rec):
    out = _common(rec)
    out.update(
        {
            "problem_id": rec["problem_id"],
            "symptom": rec["symptom"],
            "workaround": rec["workaround"],
            "published": rec["published"],
        }
    )
    return out


def kb_article(rec):
    out = _common(rec)
    out.update(
        {
            "title": rec["title"],
            "category_id": rec["category_id"],
            "body": rec["body"],
            "view_count": rec.get("view_count", 0),
            "deflection_count": rec.get("deflection_count", 0),
        }
    )
    return out


def change_request(rec):
    recompute_change_tally(rec)
    out = _common(rec)
    out.update(
        {
            "title": rec["title"],
            "ticket_id": rec["ticket_id"],
            "raised_by_user_id": rec["raised_by_user_id"],
            "risk": rec["risk"],
            "state": rec["state"],
            "required_approvals": rec.get("required_approvals"),
            "approve_count": rec.get("approve_count", 0),
            "reject_count": rec.get("reject_count", 0),
        }
    )
    return out


def cab_vote(rec):
    # Append-only event: only id + created_at (PRD §2.4).
    out = {"id": rec["id"], "created_at": iso(rec["created_at"])}
    out.update(
        {
            "change_request_id": rec["change_request_id"],
            "voter_user_id": rec["voter_user_id"],
            "decision": rec["decision"],
        }
    )
    return out


def csat_survey(rec):
    out = _common(rec)
    out.update(
        {
            "ticket_id": rec["ticket_id"],
            "score": rec["score"],
            "comment": rec.get("comment"),
            "counts_toward_index": rec["counts_toward_index"],
        }
    )
    return out


def asset(rec):
    recompute_open_incident_count(rec["id"])
    out = _common(rec)
    out.update(
        {
            "asset_tag": rec["asset_tag"],
            "kind": rec["kind"],
            "status": rec["status"],
            "open_incident_count": rec["open_incident_count"],
        }
    )
    return out
