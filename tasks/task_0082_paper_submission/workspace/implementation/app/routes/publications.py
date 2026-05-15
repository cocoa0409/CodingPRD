"""Publication endpoints."""
from __future__ import annotations

from flask import Blueprint, g

from ..auth import require_auth
from ..clock import clock
from ..errors import api_error
from ..response import success_envelope
from ..store import fmt_ts, store
from ..utils import (
    check_version,
    get_json_body,
    optional_list,
    optional_str,
    require_str,
)


publications_bp = Blueprint("publications", __name__)

_INDEXING_TARGETS = {"PUBMED", "WEB_OF_SCIENCE", "SCOPUS"}


@publications_bp.route("/manuscripts/<mid>/publications", methods=["POST"])
@require_auth(["PlatformAdmin"])
def create_publication(mid: str):
    body = get_json_body()
    copy_edit_uri = require_str(body, "copy_edit_uri")
    proof_uri = require_str(body, "proof_uri")
    issue_label = require_str(body, "issue_label")
    indexing_targets = optional_list(body, "indexing_targets")
    for t in indexing_targets:
        if t not in _INDEXING_TARGETS:
            raise api_error("ERR_VALIDATION",
                            "indexing_targets must be a subset of {PUBMED, WEB_OF_SCIENCE, SCOPUS}")
    with store.lock:
        m = store.manuscripts.get(mid)
        if not m:
            raise api_error("ERR_NOT_FOUND", "Manuscript not found")
        if m["status"] != "ACCEPTED":
            raise api_error("ERR_INVALID_STATE", "Manuscript not in ACCEPTED state")
        # Uniqueness: at most one Publication per Manuscript
        for p in store.publications.values():
            if p["manuscript_id"] == mid:
                raise api_error("ERR_PUBLICATION_ALREADY_EXISTS",
                                "Publication already exists for this manuscript")
        pub = {
            "manuscript_id": mid,
            "copy_edit_uri": copy_edit_uri,
            "proof_uri": proof_uri,
            "doi": None,
            "issue_label": issue_label,
            "indexing_targets": list(indexing_targets),
            "indexing_status": {},
            "status": "COPY_EDITING",
            "published_at": None,
        }
        store.stamp_create(pub)
        store.publications[pub["id"]] = pub
        prev = m["status"]
        m["status"] = "IN_PRODUCTION"
        store.stamp_update(m)
        store.append_audit(
            actor_role=g.user_role, actor_id=g.user_id,
            entity="Publication", entity_id=pub["id"],
            action="PRODUCTION_STARTED", from_state=None, to_state="COPY_EDITING",
        )
        store.append_audit(
            actor_role=g.user_role, actor_id=g.user_id,
            entity="Manuscript", entity_id=m["id"],
            action="PRODUCTION_STARTED", from_state=prev, to_state="IN_PRODUCTION",
        )
        return success_envelope(pub, status=201, response_type="object")


def _require_publication(pid: str) -> dict:
    pub = store.publications.get(pid)
    if not pub:
        raise api_error("ERR_NOT_FOUND", "Publication not found")
    return pub


@publications_bp.route("/publications/<pid>/send-proof", methods=["POST"])
@require_auth(["PlatformAdmin"])
def send_proof(pid: str):
    body = get_json_body()
    with store.lock:
        pub = _require_publication(pid)
        if pub["status"] != "COPY_EDITING":
            raise api_error("ERR_INVALID_STATE", "Publication not in COPY_EDITING state")
        check_version(body, pub)
        if not pub.get("copy_edit_uri") or not pub.get("proof_uri"):
            raise api_error("ERR_VALIDATION", "copy_edit_uri and proof_uri must be non-empty")
        prev = pub["status"]
        pub["status"] = "PROOF_REVIEW"
        store.stamp_update(pub)
        store.append_audit(
            actor_role=g.user_role, actor_id=g.user_id,
            entity="Publication", entity_id=pub["id"],
            action="PROOF_SENT", from_state=prev, to_state="PROOF_REVIEW",
        )
        return success_envelope(pub, status=200, response_type="object")


@publications_bp.route("/publications/<pid>/approve-proof", methods=["POST"])
@require_auth(["Author"])
def approve_proof(pid: str):
    body = get_json_body()
    with store.lock:
        pub = _require_publication(pid)
        m = store.manuscripts.get(pub["manuscript_id"])
        if not m:
            raise api_error("ERR_NOT_FOUND", "Parent manuscript not found")
        if g.user_id != m["corresponding_author_id"]:
            raise api_error("ERR_FORBIDDEN", "Caller is not the corresponding author")
        if pub["status"] != "PROOF_REVIEW":
            raise api_error("ERR_INVALID_STATE", "Publication not in PROOF_REVIEW state")
        check_version(body, pub)
        prev = pub["status"]
        pub["status"] = "ONLINE_FIRST"
        store.stamp_update(pub)
        store.append_audit(
            actor_role=g.user_role, actor_id=g.user_id,
            entity="Publication", entity_id=pub["id"],
            action="ONLINE_FIRST", from_state=prev, to_state="ONLINE_FIRST",
        )
        return success_envelope(pub, status=200, response_type="object")


@publications_bp.route("/publications/<pid>/publish-issue", methods=["POST"])
@require_auth(["PlatformAdmin"])
def publish_issue(pid: str):
    body = get_json_body()
    with store.lock:
        pub = _require_publication(pid)
        if pub["status"] != "ONLINE_FIRST":
            raise api_error("ERR_INVALID_STATE", "Publication not in ONLINE_FIRST state")
        check_version(body, pub)
        if not pub.get("doi") or not pub.get("issue_label"):
            raise api_error("ERR_PUBLICATION_NOT_READY",
                            "Publication missing doi or issue_label")
        prev = pub["status"]
        pub["status"] = "PUBLISHED"
        pub["published_at"] = fmt_ts(clock.now())
        # initialize indexing_status: each target -> PENDING
        pub["indexing_status"] = {t: "PENDING" for t in (pub.get("indexing_targets") or [])}
        store.stamp_update(pub)
        # Cascade manuscript: IN_PRODUCTION -> PUBLISHED, copying doi + issue_label
        m = store.manuscripts.get(pub["manuscript_id"])
        if m and m["status"] == "IN_PRODUCTION":
            prev_m = m["status"]
            m["status"] = "PUBLISHED"
            m["doi"] = pub["doi"]
            m["issue_label"] = pub["issue_label"]
            store.stamp_update(m)
            store.append_audit(
                actor_role=g.user_role, actor_id=g.user_id,
                entity="Manuscript", entity_id=m["id"],
                action="MANUSCRIPT_PUBLISHED", from_state=prev_m, to_state="PUBLISHED",
            )
        store.append_audit(
            actor_role=g.user_role, actor_id=g.user_id,
            entity="Publication", entity_id=pub["id"],
            action="PUBLICATION_PUBLISHED", from_state=prev, to_state="PUBLISHED",
        )
        return success_envelope(pub, status=200, response_type="object")
