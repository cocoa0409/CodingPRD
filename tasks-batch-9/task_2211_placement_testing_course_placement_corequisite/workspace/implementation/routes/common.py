"""Shared route helpers: path resolution (band 5), filtering and listing."""

from db import db, sort_rows
from errors import fail
from response import ok_list
from validators import paginate

NOT_FOUND_CODE = {
    "students": "ERR_STUDENT_NOT_FOUND",
    "courses": "ERR_COURSE_NOT_FOUND",
    "requisites": "ERR_REQUISITE_NOT_FOUND",
    "rules": "ERR_RULE_NOT_FOUND",
    "administrations": "ERR_ADMINISTRATION_NOT_FOUND",
    "attempts": "ERR_ATTEMPT_NOT_FOUND",
    "determinations": "ERR_DETERMINATION_NOT_FOUND",
    "appeals": "ERR_APPEAL_NOT_FOUND",
    "sections": "ERR_SECTION_NOT_FOUND",
    "registrations": "ERR_REGISTRATION_NOT_FOUND",
    "overrides": "ERR_OVERRIDE_NOT_FOUND",
    "studies": "ERR_STUDY_NOT_FOUND",
}


def find(collection, row_id):
    """Resolve an identifier or raise that resource type's own 404 code."""
    if not isinstance(row_id, str) or row_id == "":
        fail(NOT_FOUND_CODE[collection], "%s is not a known identifier" % row_id)
    row = getattr(db, collection).get(row_id)
    if row is None:
        fail(NOT_FOUND_CODE[collection], "%s is not a known identifier" % row_id)
    return row


def eq(field):
    return lambda row, value: row.get(field) == value


def filter_rows(rows, query, rules):
    out = []
    for row in rows:
        keep = True
        for name, predicate in rules.items():
            if name in query and not predicate(row, query[name]):
                keep = False
                break
        if keep:
            out.append(row)
    return out


def listing(rows, query, serializer, presorted=False):
    ordered = rows if presorted else sort_rows(rows)
    page, limit, offset, total = paginate(ordered, query)
    return ok_list([serializer(r) for r in page], limit, offset, total)
