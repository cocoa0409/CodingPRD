"""Family-specific helpers — sibling anchor management."""
from ..store import get_store, stamp_update


def students_of_family(family_id: str) -> list:
    return [s for s in get_store().students.values() if s["family_id"] == family_id]


def applications_of_family(family_id: str) -> list:
    store = get_store()
    student_ids = {s["id"] for s in store.students.values() if s["family_id"] == family_id}
    return [a for a in store.applications.values() if a["student_id"] in student_ids]


def recompute_head_household_application_id(family_id: str) -> None:
    """Next ACCEPTED application of any sibling in this family by created_at ASC, else null."""
    family = get_store().families[family_id]
    apps = applications_of_family(family_id)
    accepted = [a for a in apps if a["status"] == "ACCEPTED"]
    accepted.sort(key=lambda a: (a["created_at"], a["id"]))
    new_anchor = accepted[0]["id"] if accepted else None
    if family.get("head_household_application_id") != new_anchor:
        family["head_household_application_id"] = new_anchor
        stamp_update(family)


def set_anchor_if_unset(family_id: str, application_id: str) -> None:
    family = get_store().families[family_id]
    if family.get("head_household_application_id") is None:
        family["head_household_application_id"] = application_id
        stamp_update(family)
