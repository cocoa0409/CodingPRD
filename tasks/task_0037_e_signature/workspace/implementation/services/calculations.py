"""Calculation rules from SCAFFOLD §1.3."""

import hashlib
import json
from decimal import Decimal, ROUND_HALF_UP

from db import DB


# Constants
W_IDENTITY = Decimal("0.30")
W_TIMESTAMP = Decimal("0.30")
W_HASH = Decimal("0.20")
W_NOTARY = Decimal("0.20")
DRIFT_TIGHT_SECONDS = 5
DRIFT_LOOSE_SECONDS = 30
TIER_SILVER_MIN = Decimal("40")
TIER_GOLD_MIN = Decimal("70")
TIER_NOTARIZED_MIN = Decimal("90")
NOTARIZED_BONUS = Decimal("10")

WEIGHT_PER_PARTY = 1
AUTH_TTL_MINUTES = 30
MAX_TSA_DRIFT_SECONDS = 60
MIN_FACTORS_FOR_LEGAL_REP = 2


def round_half_up_2(value: Decimal) -> Decimal:
    """Round a Decimal to 2 decimal places using ROUND_HALF_UP."""
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


# -------------------------------------------------------------------------
# Document fingerprint hash (Contract.document_fingerprint_sha256)
# -------------------------------------------------------------------------

def _utf8_canonical_json(obj) -> bytes:
    return json.dumps(
        obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def compute_document_fingerprint(template_version: dict, variable_values: dict) -> str:
    """Per PRD §3.3 — per-page first, concat-then-hash second.

    Maps each variable-value key to the page it belongs to. The PRD references
    "keys' associated signature_positions" but the test recipe places page info
    on variable_fields (e.g. `{'name':'date', 'page':1}`). We accept both: a
    variable_field with a page attribute mapping key->page, OR a signature_position
    whose role_key matches the variable name. If neither is present, that key
    is included on every page (fallback for older shapes).
    """
    page_count = template_version["page_count"]
    blob_sha = template_version["document_blob_sha256"]
    sig_positions = template_version.get("signature_positions") or []
    var_fields = template_version.get("variable_fields") or []

    # Build mapping: variable key -> set of pages
    key_to_pages = {}
    # First, look at variable_fields[].page (preferred when supplied)
    for vf in var_fields:
        if not isinstance(vf, dict):
            continue
        name = vf.get("name")
        page = vf.get("page")
        if name and page is not None:
            try:
                key_to_pages.setdefault(name, set()).add(int(page))
            except (TypeError, ValueError):
                continue
    # Fall back to signature_positions where role_key matches a variable name
    for pos in sig_positions:
        if not isinstance(pos, dict):
            continue
        rk = pos.get("role_key")
        page = pos.get("page")
        if rk is None or page is None:
            continue
        if rk not in key_to_pages:
            try:
                key_to_pages.setdefault(rk, set()).add(int(page))
            except (TypeError, ValueError):
                continue

    page_hashes = []
    for i in range(1, int(page_count) + 1):
        on_page = {}
        for k, v in (variable_values or {}).items():
            if k in key_to_pages:
                if i in key_to_pages[k]:
                    on_page[k] = v
            else:
                # Unknown mapping: include key on every page
                on_page[k] = v
        # sort by key ascending — json sort_keys handles it
        canonical = {
            "page_index": i,
            "blob_sha256": blob_sha,
            "variable_values_on_page": on_page,
        }
        h = hashlib.sha256(_utf8_canonical_json(canonical)).hexdigest()
        page_hashes.append(h)

    concat = "".join(page_hashes).encode("ascii")
    return hashlib.sha256(concat).hexdigest()


# -------------------------------------------------------------------------
# Identity strength banding
# -------------------------------------------------------------------------

def compute_identity_strength(factors_attempted: list, real_name_match: bool):
    """Returns (factors_passed_list, identity_strength, result)."""
    if not isinstance(factors_attempted, list):
        factors_attempted = []
    seen = set()
    passed_ordered = []
    for fa in factors_attempted:
        if not isinstance(fa, dict):
            continue
        factor = fa.get("factor")
        outcome = fa.get("outcome")
        if outcome == "PASS" and factor and factor not in seen:
            seen.add(factor)
            passed_ordered.append(factor)
    passed = passed_ordered
    n = len(passed)
    if n == 0:
        return passed, "WEAK", "FAILED"
    if n == 1:
        result = "VERIFIED" if real_name_match else "FAILED"
        return passed, "WEAK", result
    # n >= 2
    has_ca = "CA_CERT" in passed
    has_bank = "BANK_CARD" in passed
    if has_ca and has_bank:
        strength = "EXTRA_STRONG"
    elif has_ca:
        strength = "STRONG"
    else:
        strength = "STRONG"
    result = "VERIFIED" if real_name_match else "FAILED"
    return passed, strength, result


# -------------------------------------------------------------------------
# Signing progress
# -------------------------------------------------------------------------

def compute_signing_progress(contract_id: str, variant: str = "chronological"):
    """Returns (progress_percent: float, breakdown: list[dict])."""
    # Find all SigningSteps for this contract
    steps = [s for s in DB.signing_steps.values() if s["contract_id"] == contract_id]
    steps.sort(key=lambda s: s["step_index"])

    if variant == "forward_looking":
        included_step_statuses = {"PENDING", "ACTIVE", "SIGNED", "REJECTED"}
    else:
        included_step_statuses = {"ACTIVE", "SIGNED", "REJECTED"}

    breakdown = []
    eligible_count = 0
    signed_count = 0
    for step in steps:
        if step["status"] not in included_step_statuses:
            # Not included: still report in breakdown for transparency
            continue
        parties = [
            p for p in DB.signing_parties.values()
            if p["signing_step_id"] == step["id"]
        ]
        for p in parties:
            eligible_count += WEIGHT_PER_PARTY
            if p["status"] == "SIGNED":
                signed_count += WEIGHT_PER_PARTY
            breakdown.append({
                "signing_step_id": step["id"],
                "step_index": step["step_index"],
                "step_status": step["status"],
                "signing_party_id": p["id"],
                "role_key": p["role_key"],
                "party_status": p["status"],
                "weight": WEIGHT_PER_PARTY,
            })

    if eligible_count == 0:
        return 0.00, breakdown
    pct = (Decimal(signed_count) * Decimal(100)) / Decimal(eligible_count)
    pct = round_half_up_2(pct)
    return float(pct), breakdown


# -------------------------------------------------------------------------
# Evidence strength score
# -------------------------------------------------------------------------

def _identity_tier_for_party(party: dict) -> Decimal:
    iv_id = party.get("identity_verification_id")
    if not iv_id:
        return Decimal("0")
    iv = DB.identity_verifications.get(iv_id)
    if not iv:
        return Decimal("0")
    fp = iv.get("factors_passed") or []
    has_ca = "CA_CERT" in fp
    has_bank = "BANK_CARD" in fp
    n = len(fp)
    if has_ca and has_bank:
        return Decimal("100")
    if has_ca:
        return Decimal("90")
    if n >= 2:
        return Decimal("70")
    if n == 1:
        return Decimal("50")
    return Decimal("0")


def _timestamp_tier_for_party(party: dict) -> Decimal:
    tt_id = party.get("timestamp_token_id")
    if not tt_id:
        return Decimal("0")
    token = DB.timestamp_tokens.get(tt_id)
    if not token:
        return Decimal("0")
    if token["verification_status"] != "VALID":
        return Decimal("0")
    drift = token.get("drift_seconds", 0)
    try:
        drift = Decimal(str(drift))
    except Exception:
        drift = Decimal("0")
    if drift <= DRIFT_TIGHT_SECONDS:
        return Decimal("100")
    if drift <= DRIFT_LOOSE_SECONDS:
        return Decimal("60")
    return Decimal("0")


def _hash_score(contract: dict) -> Decimal:
    """100 if pinned fingerprint matches recomputed; default 100 while not COMPLETED."""
    if contract["status"] != "COMPLETED":
        return Decimal("100")
    pinned = contract.get("document_fingerprint_sha256")
    tv = DB.template_versions.get(contract["template_version_id"])
    if pinned and tv:
        recomputed = compute_document_fingerprint(tv, contract.get("variable_values") or {})
        return Decimal("100") if recomputed == pinned else Decimal("0")
    return Decimal("100") if pinned else Decimal("0")


def _notary_score(notary_provider: str) -> Decimal:
    if notary_provider == "NOTARY_PUBLIC":
        return Decimal("60")
    if notary_provider == "BLOCKCHAIN":
        return Decimal("90")
    return Decimal("0")


def _tier_for(raw: Decimal, notary_provider: str) -> str:
    if raw < TIER_SILVER_MIN:
        return "BRONZE"
    if raw < TIER_GOLD_MIN:
        return "SILVER"
    if raw < TIER_NOTARIZED_MIN:
        return "GOLD"
    # raw >= 90
    if notary_provider != "NONE":
        return "NOTARIZED"
    return "GOLD"


def _scores_inner(contract: dict, notary_provider_for_score: str, override_notary_score=None):
    """Compute (I, T, H, N) inputs for the contract."""
    parties = [
        p for p in DB.signing_parties.values()
        if p["contract_id"] == contract["id"] and p["status"] == "SIGNED"
    ]
    if parties:
        i_total = sum((_identity_tier_for_party(p) for p in parties), Decimal("0"))
        identity_score = i_total / Decimal(len(parties))
        t_total = sum((_timestamp_tier_for_party(p) for p in parties), Decimal("0"))
        timestamp_score = t_total / Decimal(len(parties))
    else:
        identity_score = Decimal("0")
        timestamp_score = Decimal("0")
    hash_score = _hash_score(contract)
    if override_notary_score is not None:
        notary_score = Decimal(str(override_notary_score))
    else:
        notary_score = _notary_score(notary_provider_for_score)
    return identity_score, timestamp_score, hash_score, notary_score


def compute_evidence_strength(contract: dict, *, notary_provider: str,
                              apply_notary_bonus: bool = False,
                              override_notary_score=None):
    """Returns (final_score: float, tier: str, raw_first_pass: float).

    apply_notary_bonus is True at sealing time (post-seal); the bonus only
    applies if the first-pass tier resolves to NOTARIZED.
    """
    I, T, H, N = _scores_inner(contract, notary_provider, override_notary_score=override_notary_score)
    raw = (W_IDENTITY * I) + (W_TIMESTAMP * T) + (W_HASH * H) + (W_NOTARY * N)
    raw = round_half_up_2(raw)
    tier = _tier_for(raw, notary_provider)
    if apply_notary_bonus and tier == "NOTARIZED":
        N_final = min(Decimal("100"), N + NOTARIZED_BONUS)
        final_raw = (W_IDENTITY * I) + (W_TIMESTAMP * T) + (W_HASH * H) + (W_NOTARY * N_final)
        final_score = round_half_up_2(final_raw)
        return float(final_score), tier, float(raw)
    return float(raw), tier, float(raw)


def compute_evidence_provisional(contract: dict):
    """Pre-seal preview: notary_score forced to 0 regardless of provider."""
    pkg = None
    for e in DB.evidence_packages.values():
        if e["contract_id"] == contract["id"]:
            pkg = e
            break
    notary_provider = pkg["notary_provider"] if pkg else "NONE"
    I, T, H, _ = _scores_inner(contract, notary_provider, override_notary_score=Decimal("0"))
    raw = (W_IDENTITY * I) + (W_TIMESTAMP * T) + (W_HASH * H) + (W_NOTARY * Decimal("0"))
    raw = round_half_up_2(raw)
    tier = _tier_for(raw, notary_provider)
    return float(raw), tier
