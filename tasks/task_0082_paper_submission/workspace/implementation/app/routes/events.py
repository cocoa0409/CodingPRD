"""Test-driving event ingestion and clock endpoints.

Only PlatformAdmin can invoke these.
"""
from __future__ import annotations

from decimal import Decimal
from datetime import timedelta

from flask import Blueprint, g

from ..auth import require_auth
from ..calculations import plagiarism_result, round_half_up_1
from ..clock import clock
from ..errors import api_error
from ..response import success_envelope
from ..store import fmt_ts, store
from ..utils import (
    get_json_body,
    parse_iso_datetime,
    require_str,
)


events_bp = Blueprint("events", __name__)


# --------- /_clock/advance ---------

@events_bp.route("/_clock/advance", methods=["POST"])
@require_auth(["PlatformAdmin"])
def clock_advance():
    body = get_json_body()
    to_str = require_str(body, "to")
    target = parse_iso_datetime(to_str)
    clock.advance_to(target)
    return success_envelope({"now": fmt_ts(clock.now())}, status=200, response_type="object")


# --------- /_sweep/run ---------

@events_bp.route("/_sweep/run", methods=["POST"])
@require_auth(["PlatformAdmin"])
def sweep_run():
    with store.lock:
        now = clock.now()
        # 1) expire PENDING invitations whose deadline has passed
        for inv in list(store.reviewer_invitations.values()):
            if inv["status"] == "PENDING":
                deadline = parse_iso_datetime(inv["response_deadline_at"])
                if now > deadline:
                    prev = inv["status"]
                    inv["status"] = "EXPIRED"
                    store.stamp_update(inv)
                    store.append_audit(
                        actor_role=g.user_role, actor_id=g.user_id,
                        entity="ReviewerInvitation", entity_id=inv["id"],
                        action="INVITATION_EXPIRED", from_state=prev, to_state="EXPIRED",
                    )
        # 2) auto-withdraw REVISION_REQUIRED manuscripts past deadline
        for m in list(store.manuscripts.values()):
            if m["status"] == "REVISION_REQUIRED" and m.get("revision_deadline_at"):
                dt = parse_iso_datetime(m["revision_deadline_at"])
                if now > dt:
                    prev = m["status"]
                    m["status"] = "WITHDRAWN"
                    store.stamp_update(m)
                    store.append_audit(
                        actor_role=g.user_role, actor_id=g.user_id,
                        entity="Manuscript", entity_id=m["id"],
                        action="REVISION_TIMEOUT_AUTO_WITHDRAW",
                        from_state=prev, to_state="WITHDRAWN",
                    )
    return success_envelope({"swept_at": fmt_ts(clock.now())}, status=200, response_type="object")


# --------- /_events/orcid-verified ---------

@events_bp.route("/_events/orcid-verified", methods=["POST"])
@require_auth(["PlatformAdmin"])
def event_orcid_verified():
    body = get_json_body()
    author_id = require_str(body, "author_id")
    orcid_id = require_str(body, "orcid_id")
    with store.lock:
        author = store.authors.get(author_id)
        if not author:
            raise api_error("ERR_NOT_FOUND", "Author not found")
        if author.get("orcid_id") == orcid_id:
            author["orcid_verified"] = True
            store.stamp_update(author)
        return success_envelope(author, status=200, response_type="object")


# --------- /_events/plagiarism-result ---------

@events_bp.route("/_events/plagiarism-result", methods=["POST"])
@require_auth(["PlatformAdmin"])
def event_plagiarism_result():
    body = get_json_body()
    manuscript_id = require_str(body, "manuscript_id")
    if "similarity_percent" not in body:
        raise api_error("ERR_VALIDATION", "similarity_percent required")
    raw = body["similarity_percent"]
    try:
        sim = Decimal(str(raw))
    except Exception:
        raise api_error("ERR_VALIDATION", "similarity_percent must be numeric")
    if sim < 0 or sim > 100:
        raise api_error("ERR_VALIDATION", "similarity_percent must be in [0, 100]")
    sim = round_half_up_1(sim)
    report_uri = require_str(body, "report_uri")
    with store.lock:
        m = store.manuscripts.get(manuscript_id)
        if not m:
            raise api_error("ERR_NOT_FOUND", "Manuscript not found")
        result = plagiarism_result(sim)
        row = {
            "manuscript_id": manuscript_id,
            "revision_round": m["revision_round"],
            "similarity_percent": float(str(sim)),
            "report_uri": report_uri,
            "result": result,
        }
        store.stamp_event(row)
        store.plagiarism_checks[row["id"]] = row
        m["plagiarism_similarity"] = float(str(sim))
        store.stamp_update(m)
        return success_envelope(row, status=200, response_type="object")


# --------- /_events/doi-mint ---------

@events_bp.route("/_events/doi-mint", methods=["POST"])
@require_auth(["PlatformAdmin"])
def event_doi_mint():
    body = get_json_body()
    publication_id = require_str(body, "publication_id")
    doi = require_str(body, "doi")
    with store.lock:
        pub = store.publications.get(publication_id)
        if not pub:
            raise api_error("ERR_NOT_FOUND", "Publication not found")
        pub["doi"] = doi
        store.stamp_update(pub)
        return success_envelope(pub, status=200, response_type="object")


# --------- /_events/indexing-ack ---------

_INDEXING_TARGETS = {"PUBMED", "WEB_OF_SCIENCE", "SCOPUS"}
_INDEXING_STATUSES = {"ACK", "FAILED"}


@events_bp.route("/_events/indexing-ack", methods=["POST"])
@require_auth(["PlatformAdmin"])
def event_indexing_ack():
    body = get_json_body()
    publication_id = require_str(body, "publication_id")
    target = require_str(body, "target")
    status_val = require_str(body, "status")
    if target not in _INDEXING_TARGETS:
        raise api_error("ERR_VALIDATION", "target must be one of PUBMED, WEB_OF_SCIENCE, SCOPUS")
    if status_val not in _INDEXING_STATUSES:
        raise api_error("ERR_VALIDATION", "status must be ACK or FAILED")
    with store.lock:
        pub = store.publications.get(publication_id)
        if not pub:
            raise api_error("ERR_NOT_FOUND", "Publication not found")
        if target not in (pub.get("indexing_targets") or []):
            raise api_error("ERR_VALIDATION", "target is not in publication's indexing_targets")
        pub.setdefault("indexing_status", {})[target] = status_val
        store.stamp_update(pub)
        return success_envelope(pub, status=200, response_type="object")
