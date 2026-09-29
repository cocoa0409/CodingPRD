"""Narrative and comparable-selection bias screening."""

import db
from validate import bps_of, rhu
from services import constants as C
from services.appraisal import eligible_comps


def matched_terms(narrative):
    """Case insensitive substring match; a term repeated many times counts
    once.  Ordered by the declared term order."""
    lowered = (narrative or "").lower()
    hits = []
    for index, term in enumerate(C.PROHIBITED_TERMS, start=1):
        if term in lowered:
            hits.append((index, term))
    return hits


def comp_skew_bps(appraisal):
    comps = eligible_comps(appraisal["id"])
    if not comps:
        return 0
    off_band = sum(1 for c in comps
                   if c["census_tract_band"] != appraisal["subject_census_tract_band"])
    return bps_of(off_band, len(comps))


def run_bias_screen(appraisal):
    """Replace the OPEN flag set with a fresh emission and restate the index."""
    for key in [k for k, v in db.bias_flags.items()
                if v["appraisal_id"] == appraisal["id"] and v["status"] == "OPEN"]:
        del db.bias_flags[key]

    hits = matched_terms(appraisal["narrative_text"])
    skew = comp_skew_bps(appraisal)
    index = min(C.BIAS_RISK_INDEX_CAP,
                C.NARRATIVE_TERM_WEIGHT * len(hits) + rhu(skew, 200))

    flags = []
    for term_index, term in hits:
        flags.append(_flag(appraisal, "NARRATIVE", "TERM_%d" % term_index, term,
                           C.NARRATIVE_TERM_WEIGHT))
    if skew >= C.COMP_SKEW_FLAG_THRESHOLD_BPS:
        flags.append(_flag(appraisal, "COMP_SELECTION", "COMP_BAND_SKEW", None,
                           rhu(skew, 200)))

    appraisal["bias_risk_index"] = index
    appraisal["bias_screen_status"] = ("INDICATED" if index >= C.BIAS_INDICATED_THRESHOLD
                                      else "CLEAR")
    return flags


def _flag(appraisal, source, code, matched_text, weight):
    rec = db.make_record({
        "appraisal_id": appraisal["id"],
        "source": source,
        "indicator_code": code,
        "matched_text": matched_text,
        "severity_weight": weight,
        "status": "OPEN",
        "adjudicated_by_user_id": None,
        "rationale": None,
    })
    db.bias_flags[rec["id"]] = rec
    return rec
