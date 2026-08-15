"""Name normalization, American Soundex, token overlap (PRD 2.6, 3.4;
scaffold calculations.name_normalization / conflict_match_score)."""

import math
import re

SUFFIX_TOKENS = {
    "inc", "incorporated", "corp", "corporation", "co", "company",
    "llc", "llp", "lp", "ltd", "pc", "pllc",
}

TOKEN_OVERLAP_MIN = 80
PHONETIC_SCORE = 70
AFFILIATE_DEPTH_DISCOUNT = 10
AFFILIATE_MAX_DEPTH = 3
DEFAULT_MATCH_THRESHOLD = 60

_NON_NAME_CHARS = re.compile(r"[^a-z0-9 ]")
_WS = re.compile(r"\s+")

_SOUNDEX_CODES = {}
for _letters, _code in (
    ("BFPV", "1"), ("CGJKQSXZ", "2"), ("DT", "3"),
    ("L", "4"), ("MN", "5"), ("R", "6"),
):
    for _ch in _letters:
        _SOUNDEX_CODES[_ch] = _code


def normalize(s):
    """Three-step transform (PRD 2.6):
    1. lowercase; every char not in [a-z0-9 ] -> single space; collapse; trim
    2. repeatedly drop trailing corporate-suffix tokens
    3. join remaining tokens with single spaces"""
    if not isinstance(s, str):
        return ""
    t = _NON_NAME_CHARS.sub(" ", s.lower())
    t = _WS.sub(" ", t).strip()
    if not t:
        return ""
    tokens = t.split(" ")
    while tokens and tokens[-1] in SUFFIX_TOKENS:
        tokens.pop()
    return " ".join(tokens)


def soundex(normalized):
    """Four-character American Soundex of the normalized form with spaces
    removed, letters uppercased (PRD 2.6). First letter kept; subsequent
    letters mapped; vowels and H/W/Y dropped; adjacent letters of the same
    code in the original string collapse into a single code; pad right with
    '0' / truncate to length 4."""
    if not isinstance(normalized, str):
        normalized = ""
    s = normalized.replace(" ", "").upper()
    if not s:
        return "0000"
    first = s[0]
    digits = []
    prev = first
    for ch in s[1:]:
        code = _SOUNDEX_CODES.get(ch)
        if code is None:
            prev = ch
            continue
        if _SOUNDEX_CODES.get(prev) == code:
            prev = ch
            continue
        digits.append(code)
        prev = ch
    return (first + "".join(digits) + "000")[:4]


def token_overlap(a_norm, b_norm):
    """floor(100 * |tokens(A) ∩ tokens(B)| / max(|tokens(A)|, |tokens(B)|));
    counted only when >= TOKEN_OVERLAP_MIN, else 0."""
    ta = set(a_norm.split()) if a_norm else set()
    tb = set(b_norm.split()) if b_norm else set()
    if not ta or not tb:
        return 0
    shared = len(ta & tb)
    value = math.floor(100 * shared / max(len(ta), len(tb)))
    return value if value >= TOKEN_OVERLAP_MIN else 0
