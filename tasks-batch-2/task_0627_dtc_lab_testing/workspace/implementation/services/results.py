"""Clinical result flagging and telehealth referral minting
(PRD §3.8, calculations result_provisional_flag / result_final_flag)."""
import db

DELTA_CHECK_ABS = 50

_SEVERITY = {"NORMAL": 0, "ABNORMAL": 1, "CRITICAL": 2}
_SEVERITY_REV = {0: "NORMAL", 1: "ABNORMAL", 2: "CRITICAL"}


def provisional_flag(analyzer_value, offering):
    """Bounds-only flag, no history (PRD §3.8).

    Critical bounds inclusive (<= / >=); reference bounds strict (< / >).
    """
    v = analyzer_value
    cl = offering.get("critical_low")
    ch = offering.get("critical_high")
    rl = offering.get("ref_low")
    rh = offering.get("ref_high")
    if (cl is not None and v <= cl) or (ch is not None and v >= ch):
        return "CRITICAL"
    if (rl is not None and v < rl) or (rh is not None and v > rh):
        return "ABNORMAL"
    return "NORMAL"


def _escalate(flag):
    return _SEVERITY_REV[min(2, _SEVERITY[flag] + 1)]


def final_flag(result, offering):
    """Delta-checked flag at release/amend (PRD §3.8).

    base = provisional_flag(this analyzer_value). The prior is the patient's
    most-recent strictly-prior RELEASED result for the same test_code (latest
    created_at earlier than this result's created_at). A swing >= DELTA_CHECK_ABS
    escalates one severity step.
    """
    base = provisional_flag(result["analyzer_value"], offering)
    prior = _most_recent_prior_released(result)
    if prior is not None:
        if abs(result["analyzer_value"] - prior["analyzer_value"]) >= DELTA_CHECK_ABS:
            return _escalate(base)
    return base


def _most_recent_prior_released(result):
    candidates = [
        r for r in db.all_rows("lab_results")
        if r["id"] != result["id"]
        and r["patient_id"] == result["patient_id"]
        and r["test_code"] == result["test_code"]
        and r["status"] == "RELEASED"
        and (r.get("created_at", ""), r.get("_seq", 0)) < (result.get("created_at", ""), result.get("_seq", 0))
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda r: (r.get("created_at", ""), r.get("_seq", 0)))
    return candidates[-1]


def open_referral_for_result(lab_result_id):
    for ref in db.all_rows("telehealth_referrals"):
        if ref["lab_result_id"] == lab_result_id and ref["status"] != "CLOSED":
            return ref
    return None


def mint_referral(result):
    """Mint an OPEN TelehealthReferral mirroring the result's final_flag."""
    ref = db.new_record({
        "lab_result_id": result["id"],
        "patient_id": result["patient_id"],
        "referral_reason": result["final_flag"],
        "status": "OPEN",
    })
    db.insert("telehealth_referrals", ref)
    return ref
