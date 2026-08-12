"""Relationship helpers used by the calculations and the cascades."""
import store


def _latest(rows):
    if not rows:
        return None
    return store.sort_created(rows)[-1]


def project_pulls(project):
    return store.where("pulls", project_id=project["id"])


def active_pull(project):
    rows = [p for p in project_pulls(project) if p["state"] != "CANCELLED"]
    return _latest(rows) or _latest(project_pulls(project))


def pull_lines(pull):
    if pull is None:
        return []
    return store.sort_created(store.where("pull_lines", pull_id=pull["id"]))


def project_lines(project):
    return pull_lines(active_pull(project))


def project_orders(project):
    return store.sort_created(store.where("orders", project_id=project["id"]))


def project_installs(project):
    return store.sort_created(store.where("installs", project_id=project["id"]))


def complete_install(project):
    rows = [i for i in project_installs(project) if i["state"] == "COMPLETE"]
    return _latest(rows)


def project_visits(project):
    return sorted(store.where("visits", project_id=project["id"]),
                  key=lambda v: (v.get("visit_index") or 0, v["created_at"], v["_seq"]))


def project_leases(project):
    return store.sort_created(store.where("leases", project_id=project["id"]))


def active_lease(project):
    rows = [l for l in project_leases(project) if l["state"] != "CANCELLED"]
    return _latest(rows) or _latest(project_leases(project))


def project_pickups(project):
    return store.sort_created(store.where("pickups", project_id=project["id"]))


def latest_pickup(project):
    return _latest(project_pickups(project))


def active_pickup(project):
    rows = [p for p in project_pickups(project) if p["state"] != "CANCELLED"]
    return _latest(rows) or _latest(project_pickups(project))


def scheduled_pickup(project):
    rows = [p for p in project_pickups(project) if p["state"] == "SCHEDULED"]
    return _latest(rows)


def project_shoots(project):
    return store.sort_created(store.where("shoots", project_id=project["id"]))


def project_invoice(project):
    return _latest(store.where("invoices", project_id=project["id"]))


def project_deposit(project):
    return _latest(store.where("deposits", project_id=project["id"]))


def lease_extensions(lease):
    return store.sort_created(store.where("extensions", lease_id=lease["id"]))


def pickup_assessments(pickup):
    return store.sort_created(store.where("assessments", pickup_id=pickup["id"]))


def consultation_scope_items(consultation):
    rows = store.where("scope_items", consultation_id=consultation["id"])
    return sorted(rows, key=lambda s: (s.get("sequence_index") or 0, s["_seq"]))


def property_listings(prop):
    return store.sort_created(store.where("listings", property_id=prop["id"]))


def tier_of(project):
    return store.get("tiers", project.get("package_tier_id"))


def property_of(project):
    return store.get("properties", project.get("property_id"))


def listing_of(project):
    return store.get("listings", project.get("listing_id"))


def consultation_of(project):
    return store.get("consultations", project.get("consultation_id"))


def project_of_pull(pull):
    return store.get("projects", pull.get("project_id"))


def live_consultations(prop, exclude_id=None):
    live = {"SCHEDULED", "HELD", "SCOPE_DRAFTED", "SCOPE_SUBMITTED"}
    out = []
    for c in store.where("consultations", property_id=prop["id"]):
        if exclude_id is not None and c["id"] == exclude_id:
            continue
        if c["state"] in live:
            out.append(c)
    return out
