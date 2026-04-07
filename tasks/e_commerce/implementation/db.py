"""In-memory database: dict-of-lists with query helpers."""

import uuid
from datetime import datetime, timezone

_tables: dict[str, list[dict]] = {
    "shops": [],
    "products": [],
    "promotions": [],
    "orders": [],
    "order_items": [],
    "payments": [],
    "refunds": [],
    "settlements": [],
}


def _now():
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def insert(table: str, data: dict) -> dict:
    """Insert a record with auto-generated id and timestamps."""
    record = {
        "id": str(uuid.uuid4()),
        "created_at": _now(),
        **data,
    }
    # Mutable entities get updated_at and version
    if table not in ("payments",):
        record.setdefault("updated_at", record["created_at"])
        record.setdefault("version", 1)
    _tables[table].append(record)
    return record


def find_one(table: str, **filters) -> dict | None:
    """Find first record matching all filters."""
    for row in _tables[table]:
        if all(row.get(k) == v for k, v in filters.items()):
            return row
    return None


def find(table: str, filters: dict = None, sort_key="created_at",
         limit: int = None, offset: int = 0) -> tuple[list[dict], int]:
    """Find records with optional filters, pagination. Returns (items, total_count)."""
    results = _tables[table]
    if filters:
        results = [
            r for r in results
            if all(r.get(k) == v for k, v in filters.items() if v is not None)
        ]
    results = sorted(results, key=lambda r: r.get(sort_key, ""))
    total = len(results)
    if offset:
        results = results[offset:]
    if limit:
        results = results[:limit]
    return results, total


def find_many(table: str, **filters) -> list[dict]:
    """Find all records matching filters (no pagination)."""
    return [
        r for r in _tables[table]
        if all(r.get(k) == v for k, v in filters.items())
    ]


def update(table: str, record_id: str, updates: dict) -> dict | None:
    """Update a record by ID. Bumps version and updated_at."""
    for row in _tables[table]:
        if row["id"] == record_id:
            row.update(updates)
            if table not in ("payments",):
                row["updated_at"] = _now()
                row["version"] = row.get("version", 0) + 1
            return row
    return None


def count(table: str, **filters) -> int:
    """Count records matching filters."""
    return len(find_many(table, **filters))
