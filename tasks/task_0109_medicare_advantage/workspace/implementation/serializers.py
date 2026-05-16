"""Project internal rows into external JSON-friendly dicts."""
from utils import iso_string


COMMON_FIELDS = ("id", "created_at", "updated_at", "version")


def _strip_internal(d: dict) -> dict:
    """Return a copy with internal underscore-prefixed keys removed."""
    return {k: v for k, v in d.items() if not k.startswith("_")}


def serialize_beneficiary(b: dict) -> dict:
    out = _strip_internal(b)
    out["date_of_birth"] = iso_string(b["_dob_dt"])
    out["ssdi_start_date"] = iso_string(b.get("_ssdi_dt")) if b.get("_ssdi_dt") else None
    out["medicare_eligibility_date"] = iso_string(b["_elig_dt"])
    out["iep_start_date"] = iso_string(b["_iep_start_dt"])
    out["iep_end_date"] = iso_string(b["_iep_end_dt"])
    out["deceased_at"] = iso_string(b.get("_deceased_dt")) if b.get("_deceased_dt") else None
    # Drop internal datetimes
    for k in list(out.keys()):
        if k.startswith("_"):
            del out[k]
    return out


def serialize_plan(p: dict) -> dict:
    return _strip_internal(p)


def serialize_enrollment_period(ep: dict) -> dict:
    out = _strip_internal(ep)
    out["window_start"] = iso_string(ep["_window_start_dt"])
    out["window_end"] = iso_string(ep["_window_end_dt"])
    for k in list(out.keys()):
        if k.startswith("_"):
            del out[k]
    return out


def serialize_enrollment(e: dict) -> dict:
    out = _strip_internal(e)
    out["effective_date"] = iso_string(e["_effective_dt"])
    out["termination_date"] = iso_string(e.get("_termination_dt")) if e.get("_termination_dt") else None
    for k in list(out.keys()):
        if k.startswith("_"):
            del out[k]
    return out


def serialize_late_enrollment_penalty(lep: dict) -> dict:
    return _strip_internal(lep)


def serialize_medigap_policy(m: dict) -> dict:
    out = _strip_internal(m)
    out["applied_at"] = iso_string(m["_applied_dt"]) if m.get("_applied_dt") else None
    out["issued_at"] = iso_string(m.get("_issued_dt")) if m.get("_issued_dt") else None
    for k in list(out.keys()):
        if k.startswith("_"):
            del out[k]
    return out


def serialize_drug_claim(c: dict) -> dict:
    out = _strip_internal(c)
    out["fill_date"] = iso_string(c["_fill_dt"])
    out["adjudicated_at"] = iso_string(c.get("_adjudicated_dt")) if c.get("_adjudicated_dt") else None
    for k in list(out.keys()):
        if k.startswith("_"):
            del out[k]
    return out


def serialize_drug_phase_ledger(l: dict) -> dict:
    return _strip_internal(l)


def serialize_star_rating_snapshot(s: dict) -> dict:
    out = _strip_internal(s)
    out["published_at"] = iso_string(s["_published_dt"])
    for k in list(out.keys()):
        if k.startswith("_"):
            del out[k]
    return out
