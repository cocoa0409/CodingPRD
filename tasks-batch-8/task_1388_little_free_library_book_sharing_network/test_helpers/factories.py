"""Payload factories — one per entity, input fields only."""
import itertools

_counter = itertools.count(1)

DEFAULTS = {
    "STEWARD_REGION": "OR",
    "BOX_NAME": "Test Box",
    "BOX_LATITUDE": 45.52,
    "BOX_LONGITUDE": -122.68,
    "BOX_CAPACITY": 10,
    "MODULE_LEVEL": 1,
    "SCHOOL_REGION": "OR",
    "DRIVE_GOAL_BOOKS": 10,
    "DRIVE_STARTS_AT": "2026-09-01T00:00:00Z",
    "DRIVE_ENDS_AT": "2026-10-01T00:00:00Z",
    "BATCH_REGION": "OR",
}


def unique_email(prefix: str = "steward") -> str:
    return f"{prefix}-{next(_counter)}@example.org"


def create_steward_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Steward",
        "email": unique_email("steward"),
        "region_code": DEFAULTS["STEWARD_REGION"],
    }
    defaults.update(overrides)
    return defaults


def create_training_module_payload(**overrides) -> dict:
    defaults = {
        "code": f"MOD-{next(_counter)}",
        "title": "Training Module",
        "level": DEFAULTS["MODULE_LEVEL"],
    }
    defaults.update(overrides)
    return defaults


def create_training_completion_payload(module_id: str, score: int, **overrides) -> dict:
    defaults = {"module_id": module_id, "score": score}
    defaults.update(overrides)
    return defaults


def create_box_payload(steward_id: str, **overrides) -> dict:
    defaults = {
        "steward_id": steward_id,
        "name": DEFAULTS["BOX_NAME"],
        "latitude": DEFAULTS["BOX_LATITUDE"],
        "longitude": DEFAULTS["BOX_LONGITUDE"],
        "capacity_books": DEFAULTS["BOX_CAPACITY"],
        "region_code": DEFAULTS["STEWARD_REGION"],
    }
    defaults.update(overrides)
    return defaults


def create_inspection_payload(result: str = "CONFIRMED", **overrides) -> dict:
    defaults = {"result": result}
    defaults.update(overrides)
    return defaults


def create_maintenance_request_payload(box_id: str, **overrides) -> dict:
    defaults = {
        "box_id": box_id,
        "category": "WEAR",
        "description": "Routine wear observed",
    }
    defaults.update(overrides)
    return defaults


def create_triage_payload(severity: str = "LOW",
                          scheduled_date: str = "2026-08-02",
                          **overrides) -> dict:
    defaults = {"severity": severity, "scheduled_date": scheduled_date}
    defaults.update(overrides)
    return defaults


def create_resolve_payload(outcome: str = "RESOLVED", **overrides) -> dict:
    defaults = {"outcome": outcome}
    defaults.update(overrides)
    return defaults


def create_complaint_payload(box_id: str, **overrides) -> dict:
    defaults = {
        "box_id": box_id,
        "category": "OTHER",
        "description": "Something needs attention",
    }
    defaults.update(overrides)
    return defaults


def create_school_payload(**overrides) -> dict:
    defaults = {
        "name": "Test School",
        "district_code": f"D-{next(_counter)}",
        "contact_email": unique_email("school"),
        "region_code": DEFAULTS["SCHOOL_REGION"],
        "restricted_categories": [],
    }
    defaults.update(overrides)
    return defaults


def create_drive_payload(school_id: str, **overrides) -> dict:
    defaults = {
        "school_id": school_id,
        "goal_books": DEFAULTS["DRIVE_GOAL_BOOKS"],
        "starts_at": DEFAULTS["DRIVE_STARTS_AT"],
        "ends_at": DEFAULTS["DRIVE_ENDS_AT"],
    }
    defaults.update(overrides)
    return defaults


def create_batch_payload(**overrides) -> dict:
    defaults = {
        "source_type": "PUBLIC_DROP",
        "region_code": DEFAULTS["BATCH_REGION"],
    }
    defaults.update(overrides)
    return defaults


def create_book_item_payload(**overrides) -> dict:
    defaults = {
        "title": f"Book {next(_counter)}",
        "category": "FICTION",
        "condition_grade": "A",
    }
    defaults.update(overrides)
    return defaults


def create_book_items(count: int, category: str = "FICTION",
                      graded: bool = True, grade: str = "A",
                      title_prefix: str = "Book") -> list:
    """Build a homogeneous items array for bulk intake."""
    items = []
    for i in range(count):
        item = {"title": f"{title_prefix}{i + 1}", "category": category}
        if graded:
            item["condition_grade"] = grade
        items.append(item)
    return items
