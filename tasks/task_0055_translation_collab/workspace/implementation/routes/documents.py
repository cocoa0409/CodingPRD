import re

from flask import Blueprint, request

from db import store
from errors import err
from middleware import require_roles
from response import success, no_content
from services.common import (emit_audit, serialize_document, serialize_segment, stamp_create, touch)
from services.repetition import classify_segment
from services.validation import FILE_FORMATS, SPLIT_MODES, require_enum, require_string

bp = Blueprint("documents", __name__)


def _word_count(text: str) -> int:
    if not text:
        return 0
    return len(re.findall(r"\b\w+\b", text, flags=re.UNICODE))


def _split_text(raw_text: str, mode: str) -> list[str]:
    if mode == "SENTENCE":
        # Split on sentence-ending punctuation followed by whitespace or end
        sentences = re.split(r"(?<=[.!?。！？])\s+|\n+", raw_text or "")
        return [s.strip() for s in sentences if s and s.strip()]
    else:  # PARAGRAPH
        paragraphs = re.split(r"\n\s*\n", raw_text or "")
        out = [p.strip() for p in paragraphs if p and p.strip()]
        if not out and raw_text and raw_text.strip():
            out = [raw_text.strip()]
        return out


@bp.post("/projects/<id>/documents")
@require_roles("ProjectManager")
def upload_document(id):
    project = store.projects.get(id)
    if not project:
        raise err("ERR_NOT_FOUND", "project not found")
    body = request.get_json(silent=True) or {}
    filename = require_string(body, "filename", min_len=1)
    file_format = require_enum(body, "file_format", FILE_FORMATS)
    split_mode = require_enum(body, "split_mode", SPLIT_MODES)
    raw_text = require_string(body, "raw_text", min_len=0, max_len=None)

    d = {
        "project_id": id,
        "filename": filename,
        "file_format": file_format,
        "split_mode": split_mode,
        "raw_text": raw_text,
        "word_count": 0,
        "state": "UPLOADED",
    }
    stamp_create(d)
    store.documents[d["id"]] = d
    return success(serialize_document(d), status=201)


@bp.post("/documents/<id>/split")
@require_roles("ProjectManager")
def split_document(id):
    from db import new_id
    d = store.documents.get(id)
    if not d:
        raise err("ERR_NOT_FOUND", "document not found")
    if d["state"] != "UPLOADED":
        raise err("ERR_INVALID_STATE", "document not in UPLOADED.")
    project = store.projects.get(d["project_id"])
    if not project:
        raise err("ERR_NOT_FOUND", "parent project not found")
    if project["state"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "parent project not in DRAFT.")

    chunks = _split_text(d.get("raw_text", ""), d["split_mode"])
    if not chunks:
        raise err("ERR_VALIDATION_FAILED", "document has no parseable content.")

    # Existing candidate pool — segments under this project whose document is not ARCHIVED
    candidate_pool = []
    for s in store.segments.values():
        if s["project_id"] != d["project_id"]:
            continue
        parent_doc = store.documents.get(s["document_id"])
        if parent_doc is None or parent_doc["state"] == "ARCHIVED":
            continue
        candidate_pool.append(s)
    candidate_pool.sort(key=lambda x: (x["document_id"], x["ordinal"]))

    new_segments = []
    for idx, text in enumerate(chunks, start=1):
        wc = max(1, _word_count(text))
        seg = {
            "document_id": d["id"],
            "project_id": d["project_id"],
            "ordinal": idx,
            "source_text": text,
            "word_count": wc,
            "repetition_class": "NEW",
            "tm_leverage_pct": 0,
            "translated_text": None,
            "reviewed_text": None,
            "state": "NEW",
            "assignment_id": None,
        }
        stamp_create(seg)
        new_segments.append(seg)

    # Classify each newly-created segment against the candidate pool, processing in order.
    # Earlier siblings in this same split become candidates for later siblings (the
    # earliest with a given normalized text remains NEW).
    for ns in new_segments:
        classify_segment(ns, candidate_pool)
        store.segments[ns["id"]] = ns
        # Add to pool so later segments in same split can match against it
        candidate_pool.append(ns)

    # Document transitions to SPLIT
    from_state = d["state"]
    d["state"] = "SPLIT"
    d["word_count"] = sum(s["word_count"] for s in new_segments)
    touch(d)

    # Recompute project word_count
    project["word_count"] = sum(
        s["word_count"] for s in store.segments.values()
        if s["project_id"] == project["id"] and s["state"] != "REJECTED"
    )
    touch(project)

    emit_audit(
        subject_type="Project",
        subject_id=project["id"],
        event="STATE_TRANSITION",
        from_state=project["state"],
        to_state=project["state"],
        actor_role="ProjectManager",
        actor_id=request.headers.get("X-User-ID"),
        payload={"document_id": d["id"], "split_count": len(new_segments)},
    )
    out = serialize_document(d)
    out["segments"] = [serialize_segment(s) for s in new_segments]
    return success(out)


@bp.delete("/documents/<id>")
@require_roles("ProjectManager")
def archive_document(id):
    d = store.documents.get(id)
    if not d:
        raise err("ERR_NOT_FOUND", "document not found")
    if d["state"] == "ARCHIVED":
        raise err("ERR_INVALID_STATE", "document already archived.")
    project = store.projects.get(d["project_id"])
    if project is None:
        raise err("ERR_NOT_FOUND", "parent project not found")
    if project["state"] not in ("DRAFT", "CANCELLED"):
        raise err("ERR_INVALID_STATE", "parent project not in DRAFT or CANCELLED.")

    from_state = d["state"]
    d["state"] = "ARCHIVED"
    touch(d)

    for seg in store.segments.values():
        if seg["document_id"] != id:
            continue
        if seg["state"] in ("REJECTED", "REASSIGNED"):
            continue
        prev = seg["state"]
        seg["state"] = "REJECTED"
        touch(seg)
        emit_audit(
            subject_type="Segment",
            subject_id=seg["id"],
            event="STATE_TRANSITION",
            from_state=prev,
            to_state="REJECTED",
            actor_role="ProjectManager",
            actor_id=request.headers.get("X-User-ID"),
            payload={"reason": "document_archived"},
        )

    # Recompute counts
    d["word_count"] = 0
    project["word_count"] = sum(
        s["word_count"] for s in store.segments.values()
        if s["project_id"] == project["id"] and s["state"] != "REJECTED"
    )
    touch(project)
    return no_content(status=204)
