"""Repetition detection and TM-leverage classification."""
from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

TM_LEVERAGE_THRESHOLD = 95
FUZZY_THRESHOLD = 75


_PUNCT_RE = re.compile(r"[^\w\s]", re.UNICODE)


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "")
    text = text.lower()
    text = _PUNCT_RE.sub("", text)
    # Collapse whitespace
    text = re.sub(r"\s+", " ", text).strip()
    return text


def fuzzy_pct(a: str, b: str) -> int:
    """Integer 0..100 fuzzy similarity using Python's difflib SequenceMatcher."""
    if not a and not b:
        return 100
    if not a or not b:
        return 0
    ratio = SequenceMatcher(a=a, b=b).ratio()
    # Convert to integer 0..100 (round half-up)
    pct = int(round(ratio * 100 + 1e-9))
    if pct < 0:
        pct = 0
    if pct > 100:
        pct = 100
    return pct


def classify_segment(new_seg: dict, candidate_pool: list[dict]):
    """Given new_seg and a list of (already-classified) candidates with normalized
    source text, classify new_seg in place — set repetition_class and tm_leverage_pct.

    candidate_pool: list of segments whose document is not ARCHIVED, ordered by
    (document_id, ordinal). Each candidate has 'source_text', '_normalized'.
    """
    norm = normalize(new_seg["source_text"])
    new_seg["_normalized"] = norm

    exact_count = 0
    best_pct = 0
    for p in candidate_pool:
        p_norm = p.get("_normalized")
        if p_norm is None:
            p_norm = normalize(p["source_text"])
            p["_normalized"] = p_norm
        if p_norm == norm:
            exact_count += 1
        pct = fuzzy_pct(norm, p_norm)
        if pct > best_pct:
            best_pct = pct
        # Tie-break handled naturally by iteration order (earliest first)

    if exact_count >= 1 and best_pct == 100:
        new_seg["repetition_class"] = "EXACT_REPEAT"
        new_seg["tm_leverage_pct"] = 100
    elif best_pct >= TM_LEVERAGE_THRESHOLD:
        new_seg["repetition_class"] = "TM_LEVERAGE"
        new_seg["tm_leverage_pct"] = best_pct
    elif best_pct >= FUZZY_THRESHOLD:
        new_seg["repetition_class"] = "FUZZY"
        new_seg["tm_leverage_pct"] = best_pct
    else:
        new_seg["repetition_class"] = "NEW"
        new_seg["tm_leverage_pct"] = 0
