"""Composite setup helpers for the Translation Collab test suite.

Most interesting test claims require the system to be in a specific
state reached through 5–20 API calls (client → translator → project →
upload → split → quote → activate → dispatch → accept → translate →
review → final-approve → publish). These helpers encapsulate those
preambles so test bodies stay focused on assertions.

Identity threading (PRD §2.1):
- Translator is ENTITY-BACKED: 'When X-User-Role is Translator,
  X-User-ID is the id of the acting Translator record.' Every
  ownership-gated call by a Translator principal MUST use
  make_translator_headers(translator['id']), never a shared
  fallback string.
- ProjectManager is OPAQUE.

Setup helpers use get_success_data (lenient), so a broken precondition
surfaces as a clear setup error rather than a confusing assertion
failure inside the test body.
"""
from __future__ import annotations
from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_paginated,
)

from .api_client import api_client
from .factories import (
    clock_payload,
    create_client_payload,
    create_project_payload,
    create_project_template_payload,
    create_quality_score_payload,
    create_terminology_payload,
    create_translator_payload,
    dispatch_assignment_payload,
    future_iso,
    future_iso_hours,
    language_pair,
    make_error_item,
    reject_assignment_payload,
    reject_segment_payload,
    resolve_terminology_payload,
    submit_review_payload,
    submit_translation_payload,
    upload_document_payload,
)
from .test_users import (
    TEST_USERS,
    make_translator_headers,
)


# ===========================================================================
# Shared role-header constants
# ===========================================================================
PM = TEST_USERS["project_manager_headers"]
PM_ALT = TEST_USERS["project_manager_headers_alt"]


# ===========================================================================
# Clock helpers (PRD §2.10, §4)
# ===========================================================================
def advance_clock(seconds: int,
                  headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """PRD §2.10: 'the platform clock advances only via the test-driving
    /_clock/advance endpoint.'"""
    return get_success_data(api_client.advance_clock(
        clock_payload(seconds), headers or PM,
    ))


def run_sweep(headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """PRD §2.10: '_sweep/run forces the same re-evaluation idempotently.'"""
    return get_success_data(api_client.run_sweep(headers or PM))


# ===========================================================================
# Client
# ===========================================================================
def create_client(**overrides: Any) -> Dict[str, Any]:
    """PRD §3.1: 'A ProjectManager opens a project lifecycle by first
    registering the customer that will pay for it.'"""
    return get_success_data(api_client.create_client(
        create_client_payload(**overrides), PM,
    ))


def get_client(client_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_client(client_id, PM))


# ===========================================================================
# Translator
# ===========================================================================
def create_translator(**overrides: Any) -> Dict[str, Any]:
    """PRD §3.1: 'Registering a translator captures the translator's
    public display_name, the set of source/target language pairs...'"""
    return get_success_data(api_client.create_translator(
        create_translator_payload(**overrides), PM,
    ))


def pass_translator_test(translator_id: str) -> Dict[str, Any]:
    """PRD §3.1: 'A separate operation by the project manager clears the
    test gate by setting test_translation_passed to true.'"""
    return get_success_data(api_client.pass_test_translator(translator_id, PM))


def create_passed_translator(**overrides: Any) -> Dict[str, Any]:
    """Create a translator and immediately pass the test gate. Returns
    the refreshed translator row."""
    t = create_translator(**overrides)
    return pass_translator_test(t["id"])


def get_translator(translator_id: str,
                   headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(api_client.get_translator(
        translator_id, headers or PM,
    ))


# ===========================================================================
# Project & Document
# ===========================================================================
def create_project(client_id: str, **overrides: Any) -> Dict[str, Any]:
    """PRD §3.2: 'When a project manager creates a project...'"""
    return get_success_data(api_client.create_project(
        create_project_payload(client_id, **overrides), PM,
    ))


def get_project(project_id: str,
                headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(api_client.get_project(
        project_id, headers or PM,
    ))


def upload_document(project_id: str, raw_text: str,
                    **overrides: Any) -> Dict[str, Any]:
    """PRD §3.2: 'Uploading a document captures the original filename...'"""
    return get_success_data(api_client.upload_document(
        project_id, upload_document_payload(raw_text=raw_text, **overrides),
        PM,
    ))


def split_document(document_id: str) -> Dict[str, Any]:
    """PRD §3.2: 'Splitting the document — permitted only while the parent
    project is in DRAFT — parses the raw text...'"""
    return get_success_data(api_client.split_document(document_id, PM))


def extract_segments_from(*candidates: Any) -> List[Dict[str, Any]]:
    """Try multiple response shapes to find segment rows.

    Implementations may surface the segment array under
    `segments`, `data.segments`, or as part of the GET-document
    response. This helper inspects each candidate dict and returns
    the first list of segment-like dicts it finds (each having an
    'id' key).
    """
    for cand in candidates:
        if not isinstance(cand, dict):
            continue
        segs = cand.get("segments")
        if isinstance(segs, list) and all(
            isinstance(s, dict) and "id" in s for s in segs
        ) and segs:
            return list(segs)
    return []


def fetch_segments_for_document(document_id: str,
                                split_response: Optional[Dict[str, Any]] = None,
                                ) -> List[Dict[str, Any]]:
    """Collect the segments produced by a document split. Tries the split
    response first; if that does not include them, no fallback exists
    (the API does not list segments by document)."""
    if split_response is not None:
        segs = extract_segments_from(split_response)
        if segs:
            return segs
    return []


def quote_project(project_id: str) -> Dict[str, Any]:
    """PRD §3.2: 'they request a quote, which is the gateway transition
    from DRAFT to QUOTED.'"""
    return get_success_data(api_client.quote_project(project_id, PM))


def activate_project(project_id: str) -> Dict[str, Any]:
    """PRD §3.3: 'After at least one translator assignment exists for the
    project, the project manager can move the project from QUOTED to
    ACTIVE.'"""
    return get_success_data(api_client.activate_project(project_id, PM))


def publish_project(project_id: str) -> Dict[str, Any]:
    """PRD §3.7: 'Publishing is the project manager's final action.'"""
    return get_success_data(api_client.publish_project(project_id, PM))


def cancel_project(project_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.cancel_project(project_id, PM))


# ===========================================================================
# Assignment
# ===========================================================================
def dispatch_assignment(project_id: str, translator_id: str,
                       role: str, segment_ids: List[str],
                       headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """PRD §3.3: 'Each dispatch nominates one translator, the pipeline
    role for the assignment, and the segment package.'"""
    return get_success_data(api_client.dispatch_assignment(
        project_id,
        dispatch_assignment_payload(translator_id, role, segment_ids),
        headers or PM,
    ))


def accept_assignment(assignment_id: str, translator_id: str) -> Dict[str, Any]:
    """PRD §3.3: 'A translator accepts a pending assignment they hold.'

    Uses make_translator_headers(translator_id) — required because PRD
    §2.1 binds X-User-ID to the acting Translator.id."""
    return get_success_data(api_client.accept_assignment(
        assignment_id, make_translator_headers(translator_id),
    ))


def reject_assignment(assignment_id: str, translator_id: str,
                     reason: str = "unavailable") -> Dict[str, Any]:
    """PRD §3.3: 'A translator may also decline a pending assignment they
    hold (supplying a reason).'"""
    return get_success_data(api_client.reject_assignment(
        assignment_id, reject_assignment_payload(reason=reason),
        make_translator_headers(translator_id),
    ))


def get_assignment(assignment_id: str,
                   headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(api_client.get_assignment(
        assignment_id, headers or PM,
    ))


# ===========================================================================
# Segment workflow
# ===========================================================================
def submit_translation(segment_id: str, translator_id: str,
                       translated_text: str = "Texte traduit.") -> Dict[str, Any]:
    """PRD §3.4: 'The translator who has accepted a TRANSLATOR-role
    assignment submits the translation of each covered segment.'"""
    return get_success_data(api_client.submit_translation(
        segment_id, submit_translation_payload(translated_text=translated_text),
        make_translator_headers(translator_id),
    ))


def submit_review(segment_id: str, translator_id: str,
                  reviewed_text: str = "Texte revu.") -> Dict[str, Any]:
    """PRD §3.4: 'The translator who holds the REVIEWER-role assignment
    covering the segment submits review by supplying the revised text.'"""
    return get_success_data(api_client.submit_review(
        segment_id, submit_review_payload(reviewed_text=reviewed_text),
        make_translator_headers(translator_id),
    ))


def final_approve_segment(segment_id: str, translator_id: str) -> Dict[str, Any]:
    """PRD §3.4: 'The translator who holds the FINAL_REVIEWER-role
    assignment performs final approval.'"""
    return get_success_data(api_client.final_approve_segment(
        segment_id, make_translator_headers(translator_id),
    ))


def reject_segment(segment_id: str, translator_id: str,
                  reason: str = "rework",
                  errors: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """PRD §3.4: 'A reviewer may reject a TRANSLATED segment by supplying
    a reason' / 'A final reviewer may reject a REVIEWED segment by
    supplying a reason and, optionally, an errors array.'"""
    return get_success_data(api_client.reject_segment(
        segment_id,
        reject_segment_payload(reason=reason, errors=errors),
        make_translator_headers(translator_id),
    ))


def get_segment(segment_id: str,
                headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(api_client.get_segment(
        segment_id, headers or PM,
    ))


# ===========================================================================
# Terminology
# ===========================================================================
def create_terminology(scope_type: str, scope_id: str,
                       source_term: str, target_term: str,
                       source_lang: str = "en", target_lang: str = "fr",
                       headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(api_client.create_terminology(
        create_terminology_payload(
            scope_type=scope_type, scope_id=scope_id,
            source_term=source_term, target_term=target_term,
            source_lang=source_lang, target_lang=target_lang,
        ),
        headers or PM,
    ))


def approve_terminology(term_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.approve_terminology(term_id, PM))


def resolve_terminology(term_id: str, loser_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.resolve_terminology(
        term_id, resolve_terminology_payload(loser_id=loser_id), PM,
    ))


def delete_terminology(term_id: str) -> None:
    api_client.delete_terminology(term_id, PM)


# ===========================================================================
# Quality Score
# ===========================================================================
def create_quality_score(segment_id: str,
                         errors: Optional[List[Dict[str, Any]]] = None,
                         headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(api_client.create_quality_score(
        create_quality_score_payload(
            segment_id=segment_id,
            errors=errors if errors is not None else [],
        ),
        headers or PM,
    ))


def finalize_quality_score(score_id: str, translator_id: str) -> Dict[str, Any]:
    """PRD §3.6: 'Finalization is a separate operation invoked by a
    Translator.'"""
    return get_success_data(api_client.finalize_quality_score(
        score_id, make_translator_headers(translator_id),
    ))


def void_quality_score(score_id: str) -> Dict[str, Any]:
    """PRD §3.6: 'A project manager may instead void a DRAFT score.'"""
    return get_success_data(api_client.void_quality_score(score_id, PM))


# ===========================================================================
# Audit/Sync list helpers — page through all rows
# ===========================================================================
def list_all_audit_entries(*,
                           subject_type: Optional[str] = None,
                           subject_id: Optional[str] = None) -> List[Dict[str, Any]]:
    params: Dict[str, Any] = {"limit": 100, "offset": 0}
    if subject_type is not None:
        params["subject_type"] = subject_type
    if subject_id is not None:
        params["subject_id"] = subject_id
    out: List[Dict[str, Any]] = []
    while True:
        resp = api_client.list_audit_entries(PM, params=params)
        data, meta = validate_paginated(resp)
        out.extend(data)
        if not meta.get("has_more"):
            break
        params["offset"] = params["offset"] + len(data)
    return out


def list_all_sync_records(*,
                          project_id: Optional[str] = None,
                          target_system: Optional[str] = None) -> List[Dict[str, Any]]:
    params: Dict[str, Any] = {"limit": 100, "offset": 0}
    if project_id is not None:
        params["project_id"] = project_id
    if target_system is not None:
        params["target_system"] = target_system
    out: List[Dict[str, Any]] = []
    while True:
        resp = api_client.list_external_sync_records(PM, params=params)
        data, meta = validate_paginated(resp)
        out.extend(data)
        if not meta.get("has_more"):
            break
        params["offset"] = params["offset"] + len(data)
    return out


# ===========================================================================
# High-level composite scenarios
# ===========================================================================
def setup_client_and_project_in_draft(
    *,
    project_overrides: Optional[Dict[str, Any]] = None,
    client_overrides: Optional[Dict[str, Any]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Create a client (tax 0, cycle 0 by default) and a fresh DRAFT project.

    PRD §3.2: 'When a project manager creates a project, they supply the
    owning client_id...'

    Returns: (client, project)."""
    client = create_client(**(client_overrides or {}))
    project = create_project(client["id"], **(project_overrides or {}))
    return client, project


def setup_project_with_segments(
    *,
    sentences: Optional[List[str]] = None,
    raw_text: Optional[str] = None,
    project_overrides: Optional[Dict[str, Any]] = None,
    client_overrides: Optional[Dict[str, Any]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], List[Dict[str, Any]]]:
    """Build a DRAFT project + one document + split → segments.

    Returns: (client, project, document, segments_in_ordinal_order)
    """
    client, project = setup_client_and_project_in_draft(
        project_overrides=project_overrides,
        client_overrides=client_overrides,
    )
    if sentences is not None:
        # SENTENCE split — join sentences with periods.
        text = " ".join(s.rstrip(".") + "." for s in sentences)
    elif raw_text is not None:
        text = raw_text
    else:
        # Default: one sentence of 10 words.
        text = " ".join(f"word{i}" for i in range(1, 11)) + "."
    doc = upload_document(project["id"], raw_text=text)
    doc_split = split_document(doc["id"])
    # Harvest segments from the split response (preferred) or the upload
    # response. Implementations vary in which response carries the array;
    # both are PRD-faithful sources for the same data.
    segments = extract_segments_from(doc_split, doc)
    return client, project, doc_split, segments


def build_words_text(n_words: int) -> str:
    """Construct a single-sentence raw_text of exactly n_words words."""
    return " ".join(f"word{i}" for i in range(1, n_words + 1)) + "."


def build_multi_sentence_text(per_sentence_words: List[int]) -> str:
    """Construct raw_text composed of len(per_sentence_words) sentences,
    each sentence holding the indicated number of distinct words.

    All words across sentences are unique so repetition_detection
    classifies every segment as NEW unless the caller deliberately
    repeats a sentence."""
    pieces: List[str] = []
    counter = 1
    for n in per_sentence_words:
        words = [f"w{counter + i}" for i in range(n)]
        counter += n
        pieces.append(" ".join(words) + ".")
    return " ".join(pieces)


def build_repeated_sentence_text(
    repeated_sentence_words: int,
    repetitions: int,
    distinct_extras: Optional[List[int]] = None,
) -> str:
    """Construct raw_text where ONE sentence (its word string) is
    repeated `repetitions` times, with additional distinct sentences
    appended. Used to drive repetition_class=EXACT_REPEAT in tests
    that need a known exact-repeat ratio (PRD §3.2)."""
    repeated_words = " ".join(f"r{i}" for i in range(repeated_sentence_words))
    sentences = [repeated_words + "."] * repetitions
    counter = 1000
    for n in (distinct_extras or []):
        sentences.append(" ".join(f"d{counter + i}" for i in range(n)) + ".")
        counter += n
    return " ".join(sentences)


# ===========================================================================
# Difficulty-design dedicated composite fixtures
# ===========================================================================
def setup_quoted_project_with_one_word_segment(
    *,
    base_unit_price_cents: int = 100,
    word_count: int = 100,
    deadline_hours_ahead: int = 24 * 30,  # STANDARD by default
    domain: str = "GENERAL",
    unit_pricing_mode: str = "PER_WORD",
    package_size_segments: int = 50,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], List[Dict[str, Any]]]:
    """One client, one DRAFT→QUOTED project with a single document of
    `word_count` words (one sentence). Returns (client, project, doc, segments)
    where project.state == 'QUOTED'."""
    client, project = setup_client_and_project_in_draft(
        project_overrides={
            "domain": domain,
            "unit_pricing_mode": unit_pricing_mode,
            "base_unit_price_cents": base_unit_price_cents,
            "package_size_segments": package_size_segments,
            "deadline_at": future_iso_hours(deadline_hours_ahead),
        },
    )
    text = build_words_text(word_count)
    doc = upload_document(project["id"], raw_text=text)
    doc_split = split_document(doc["id"])
    segments = extract_segments_from(doc_split, doc)
    project = quote_project(project["id"])
    return client, project, doc_split, segments


def setup_translator_passed(
    *,
    grade: str = "JUNIOR",
    source_lang: str = "en",
    target_lang: str = "fr",
    domains: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Single translator with profile suited to the canonical project
    (en→fr GENERAL), pass-test cleared, returned in its refreshed state."""
    t = create_translator(
        grade=grade,
        language_pairs=[language_pair(source_lang, target_lang)],
        domains=domains or ["GENERAL"],
    )
    return pass_translator_test(t["id"])


def setup_full_pipeline_one_segment(
    *,
    translator_grade: str = "SENIOR",
    base_unit_price_cents: int = 100,
    word_count: int = 100,
    deadline_hours_ahead: int = 24 * 30,
    quality_errors: Optional[List[Dict[str, Any]]] = None,
    finalize_quality: bool = False,
) -> Dict[str, Any]:
    """Drive a one-segment project all the way from create through
    FINAL_APPROVED so a publish call is one step away. Returns a dict
    with handles every test layer needs.

    'project' is in state ALL_REVIEWED after this fixture (every segment
    FINAL_APPROVED). The caller may then call publish_project."""
    client, project, doc, segments = setup_quoted_project_with_one_word_segment(
        base_unit_price_cents=base_unit_price_cents,
        word_count=word_count,
        deadline_hours_ahead=deadline_hours_ahead,
    )
    # Three translators: T (with the configured grade), reviewer, final reviewer.
    t = setup_translator_passed(grade=translator_grade)
    rev = setup_translator_passed(grade="SENIOR")
    final = setup_translator_passed(grade="SENIOR")
    # We need at least one TRANSLATOR assignment to activate.
    seg_ids = [s["id"] for s in segments]
    a_t = dispatch_assignment(project["id"], t["id"], "TRANSLATOR", seg_ids)
    project = activate_project(project["id"])
    a_t = accept_assignment(a_t["id"], t["id"])
    for sid in seg_ids:
        submit_translation(sid, t["id"])
    a_r = dispatch_assignment(project["id"], rev["id"], "REVIEWER", seg_ids)
    a_r = accept_assignment(a_r["id"], rev["id"])
    for sid in seg_ids:
        submit_review(sid, rev["id"])
    a_f = dispatch_assignment(project["id"], final["id"], "FINAL_REVIEWER", seg_ids)
    a_f = accept_assignment(a_f["id"], final["id"])
    for sid in seg_ids:
        final_approve_segment(sid, final["id"])
    # Optional: attach a DRAFT QualityScore (or finalize it).
    qs = None
    if quality_errors is not None:
        qs = create_quality_score(seg_ids[0], errors=quality_errors)
        if finalize_quality:
            qs = finalize_quality_score(qs["id"], final["id"])
    return {
        "client": client,
        "project": get_project(project["id"]),
        "document": doc,
        "segments": segments,
        "translator": t,
        "reviewer": rev,
        "final_reviewer": final,
        "translator_assignment": get_assignment(a_t["id"]),
        "reviewer_assignment": get_assignment(a_r["id"]),
        "final_reviewer_assignment": get_assignment(a_f["id"]),
        "quality_score": qs,
    }


def setup_two_passed_translators(
    *,
    source_lang: str = "en", target_lang: str = "fr",
    grade_a: str = "SENIOR", grade_b: str = "SENIOR",
    rolling_a: Optional[float] = None,
    rolling_b: Optional[float] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Create two passed translators (en→fr, GENERAL). Returns (t1, t2)."""
    return (
        setup_translator_passed(
            grade=grade_a, source_lang=source_lang, target_lang=target_lang,
        ),
        setup_translator_passed(
            grade=grade_b, source_lang=source_lang, target_lang=target_lang,
        ),
    )


def setup_segment_at_translated(
    *,
    translator_grade: str = "JUNIOR",
    word_count: int = 100,
) -> Dict[str, Any]:
    """Drive a one-segment project to Segment.state=TRANSLATED.

    Returns: dict with client, project (state=ACTIVE or ALL_TRANSLATED),
    document, segment, translator (T_translator), assignment_t."""
    client, project, doc, segments = setup_quoted_project_with_one_word_segment(
        word_count=word_count,
    )
    t = setup_translator_passed(grade=translator_grade)
    seg_ids = [s["id"] for s in segments]
    a_t = dispatch_assignment(project["id"], t["id"], "TRANSLATOR", seg_ids)
    project = activate_project(project["id"])
    a_t = accept_assignment(a_t["id"], t["id"])
    for sid in seg_ids:
        submit_translation(sid, t["id"])
    return {
        "client": client,
        "project": get_project(project["id"]),
        "document": doc,
        "segments": segments,
        "translator": t,
        "translator_assignment": get_assignment(a_t["id"]),
    }


def setup_segment_at_reviewed(*, word_count: int = 100) -> Dict[str, Any]:
    """Drive a one-segment project to Segment.state=REVIEWED."""
    base = setup_segment_at_translated(word_count=word_count)
    rev = setup_translator_passed(grade="SENIOR")
    seg_ids = [s["id"] for s in base["segments"]]
    a_r = dispatch_assignment(base["project"]["id"], rev["id"],
                              "REVIEWER", seg_ids)
    a_r = accept_assignment(a_r["id"], rev["id"])
    for sid in seg_ids:
        submit_review(sid, rev["id"])
    base["reviewer"] = rev
    base["reviewer_assignment"] = get_assignment(a_r["id"])
    base["project"] = get_project(base["project"]["id"])
    return base


def setup_segment_at_all_reviewed_with_final_pending(
    *, word_count: int = 100,
) -> Dict[str, Any]:
    """Drive a project to Project.state=ALL_REVIEWED with a FINAL_REVIEWER
    Assignment dispatched and accepted, but final-approve not yet called.

    Useful for the depth-3 cascade test (final reviewer rejects -> project
    demotes to ALL_TRANSLATED -> publish becomes invalid)."""
    base = setup_segment_at_reviewed(word_count=word_count)
    final = setup_translator_passed(grade="SENIOR")
    seg_ids = [s["id"] for s in base["segments"]]
    a_f = dispatch_assignment(base["project"]["id"], final["id"],
                              "FINAL_REVIEWER", seg_ids)
    a_f = accept_assignment(a_f["id"], final["id"])
    base["final_reviewer"] = final
    base["final_reviewer_assignment"] = get_assignment(a_f["id"])
    base["project"] = get_project(base["project"]["id"])
    return base


def setup_repetition_project(
    *,
    repeated_word_count: int,
    repetitions: int,
    distinct_sentences_words: Optional[List[int]] = None,
    base_unit_price_cents: int = 100,
    deadline_hours_ahead: int = 24 * 30,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], List[Dict[str, Any]]]:
    """Create a DRAFT project + one document whose split produces:
    - `repetitions` sentences with identical word string (first one
      NEW, the rest EXACT_REPEAT per PRD §2.9), each of
      repeated_word_count words.
    - len(distinct_sentences_words) additional sentences, each with a
      unique word string of the indicated size (all NEW).
    Returns (client, project, doc, segments)."""
    client, project = setup_client_and_project_in_draft(
        project_overrides={
            "base_unit_price_cents": base_unit_price_cents,
            "deadline_at": future_iso_hours(deadline_hours_ahead),
        },
    )
    text = build_repeated_sentence_text(
        repeated_word_count, repetitions, distinct_sentences_words,
    )
    doc = upload_document(project["id"], raw_text=text)
    doc_split = split_document(doc["id"])
    segments = extract_segments_from(doc_split, doc)
    project = get_project(project["id"])
    return client, project, doc_split, segments


def setup_translator_with_open_workload(
    *,
    initial_open_segments: int,
    grade: str = "SENIOR",
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Create a translator, then build a project of `initial_open_segments`
    segments, dispatch+accept ONE TRANSLATOR assignment covering all of
    them so the translator's workload_segments_open reaches
    initial_open_segments.

    Returns: (translator_refreshed, project_with_segments_dict)
    where project_with_segments_dict has keys 'project', 'segments'."""
    client, project = setup_client_and_project_in_draft(
        project_overrides={
            "package_size_segments": max(initial_open_segments + 60, 50),
        },
    )
    text = build_multi_sentence_text([3] * initial_open_segments)
    doc = upload_document(project["id"], raw_text=text)
    doc_split = split_document(doc["id"])
    segments = extract_segments_from(doc_split, doc)
    project = quote_project(project["id"])
    t = setup_translator_passed(grade=grade)
    seg_ids = [s["id"] for s in segments]
    a = dispatch_assignment(project["id"], t["id"], "TRANSLATOR", seg_ids)
    project = activate_project(project["id"])
    accept_assignment(a["id"], t["id"])
    return get_translator(t["id"]), {
        "project": get_project(project["id"]),
        "segments": segments,
    }


__all__ = [
    "PM", "PM_ALT",
    "advance_clock", "run_sweep",
    "create_client", "get_client",
    "create_translator", "pass_translator_test", "create_passed_translator",
    "get_translator",
    "create_project", "get_project",
    "upload_document", "split_document",
    "quote_project", "activate_project",
    "publish_project", "cancel_project",
    "dispatch_assignment", "accept_assignment", "reject_assignment",
    "get_assignment",
    "submit_translation", "submit_review",
    "final_approve_segment", "reject_segment", "get_segment",
    "create_terminology", "approve_terminology",
    "resolve_terminology", "delete_terminology",
    "create_quality_score", "finalize_quality_score",
    "void_quality_score",
    "list_all_audit_entries", "list_all_sync_records",
    "setup_client_and_project_in_draft",
    "setup_project_with_segments",
    "fetch_segments_for_document", "extract_segments_from",
    "build_words_text", "build_multi_sentence_text",
    "build_repeated_sentence_text",
    "setup_quoted_project_with_one_word_segment",
    "setup_translator_passed",
    "setup_two_passed_translators",
    "setup_full_pipeline_one_segment",
    "setup_segment_at_translated",
    "setup_segment_at_reviewed",
    "setup_segment_at_all_reviewed_with_final_pending",
    "setup_repetition_project",
    "setup_translator_with_open_workload",
]
