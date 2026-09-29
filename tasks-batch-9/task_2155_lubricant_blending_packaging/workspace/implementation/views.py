"""Serialization entry point: refresh derived fields, then render."""
import calc
import cascades
import core

STAFF_ALL = ["PlatformAdmin", "ProductManager", "BlendOperator", "QCTechnician",
             "QualityManager", "ComplianceOfficer", "SalesRep"]
STAFF_OPS = ["PlatformAdmin", "ProductManager", "BlendOperator", "QCTechnician",
             "QualityManager", "ComplianceOfficer"]


def _refresh(record):
    entity = record.get("_entity")
    if entity == "ComponentLot":
        calc.refresh_lot(record)
    elif entity == "PackagingLine":
        cascades.refresh_scheduled_run_count(record)
    elif entity == "BlendBatch":
        cascades.refresh_retain_count(record)
    return record


def dump(record):
    if record is None:
        return None
    return core.to_json(_refresh(record))


def dump_all(records):
    return [dump(r) for r in records]


def one(record, status=200):
    return core.ok(dump(record), status)


def listing(rows, limit, offset):
    page, total = core.paginate(rows, limit, offset)
    return core.ok_list(dump_all(page), limit, offset, total)


def by_created_asc(rows):
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


def by_created_desc(rows):
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]), reverse=True)
