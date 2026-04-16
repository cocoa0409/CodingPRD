"""Vaccination compliance contract."""

from db import store, now_dt, new_id

REQUIRED = {
    "DOG": ["RABIES", "DISTEMPER", "PARVO", "BORDETELLA"],
    "CAT": ["RABIES", "DISTEMPER", "FELV"],
    "RABBIT": ["RABIES"],
    "OTHER": ["RABIES"],
}


def latest_per_vaccine(animal_id):
    per = {}
    for vr in store.vaccinations.values():
        if vr["animal_id"] != animal_id:
            continue
        vt = vr["vaccine_type"]
        if vt not in per or vr["administered_date"] > per[vt]["administered_date"]:
            per[vt] = vr
    return per


def compute_compliance(animal_id):
    animal = store.animals.get(animal_id)
    if not animal:
        return {"status": "NON_COMPLIANT", "missing": [], "expired": []}
    species = animal["species"]
    required = REQUIRED.get(species, REQUIRED["OTHER"])
    latest = latest_per_vaccine(animal_id)
    now = now_dt()
    missing = []
    expired = []
    for v in required:
        rec = latest.get(v)
        if rec is None:
            missing.append(v)
        elif rec["expires_date"] <= now:
            expired.append(v)
    if missing or expired:
        return {"status": "NON_COMPLIANT", "missing": missing, "expired": expired}
    return {"status": "COMPLIANT", "missing": [], "expired": []}


def write_incident(animal_id, incident_type, triggered_by, detail):
    from db import now_dt as _now
    iid = new_id()
    rec = {
        "id": iid,
        "animal_id": animal_id,
        "incident_type": incident_type,
        "triggered_by": triggered_by,
        "detail": detail,
        "created_at": _now(),
    }
    store.incidents[iid] = rec
    return rec


def snapshot_compliance(animal_id):
    latest = latest_per_vaccine(animal_id)
    snap = []
    for v, rec in latest.items():
        snap.append({
            "vaccine_type": v,
            "administered_date": rec["administered_date"].isoformat() if hasattr(rec["administered_date"], "isoformat") else rec["administered_date"],
            "expires_date": rec["expires_date"].isoformat() if hasattr(rec["expires_date"], "isoformat") else rec["expires_date"],
            "lot_number": rec["lot_number"],
        })
    return snap
