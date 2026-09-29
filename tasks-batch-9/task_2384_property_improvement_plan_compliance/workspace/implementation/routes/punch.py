"""PunchListItem defects, the remediation loop and verification (PRD 3.7)."""

import calc
import domain
import guards
import repo
import validation as v
from db import clock_date
from errors import ApiError
from middleware import ANY_ROLE, BRAND_INSPECTOR, FRANCHISEE_OWNER
from routing import route

OUTCOMES = ("CLOSE", "REOPEN", "WAIVE")
KNOCKBACK_SEVERITIES = ("MAJOR", "CRITICAL")
SETTLED_DEFECT_STATUSES = ("VERIFIED_CLOSED", "WAIVED")


def _settle_item(item):
    """When every defect of the item is settled, PUNCH_FAIL returns to WORK_COMPLETE."""
    if item is None or item["status"] != "PUNCH_FAIL":
        return
    defects = domain.punch_items_of_item(item["id"])
    if all(d["status"] in SETTLED_DEFECT_STATUSES for d in defects):
        item["status"] = "WORK_COMPLETE"
        domain.recompute_item_overdue(item)
        repo.touch(item)
        plan = repo.find("plans", item["plan_id"])
        if plan is not None:
            domain.reevaluate_plan_readiness(plan)
            domain.recompute_plan_overdue(plan)


@route("/pip/punch-list-items", ["POST"], (BRAND_INSPECTOR,))
def create_punch_item():
    body = v.body_json()
    # Canonical foreign-key order: the charged item, then the raising inspection.
    item = guards.resolve_body_fk(body, "pip_item_id", "items")
    inspection = guards.resolve_body_fk(body, "inspection_id", "inspections")

    v.require(body, "inspection_id", "pip_item_id", "defect_note", "severity")
    note = v.get_str(body, "defect_note", min_len=1, max_len=500)
    severity = v.get_enum(body, "severity", calc.SEVERITIES)

    # band 8
    if item["plan_id"] != inspection["plan_id"]:
        raise ApiError(
            "ERR_ITEM_PLAN_MISMATCH",
            "pip_item_id must belong to the plan the inspection covers",
        )

    row = repo.new_row(
        {
            "inspection_id": inspection["id"],
            "pip_item_id": item["id"],
            "defect_note": note,
            "severity": severity,
            "cure_deadline_date": calc.fmt_date(
                calc.add_days(clock_date(), calc.PUNCH_CURE_DAYS)
            ),
            "status": "OPEN",
            "verification_note": None,
        }
    )
    repo.insert("punch_items", row)

    domain.recompute_inspection_punch_count(inspection)
    repo.touch(inspection)

    plan = repo.find("plans", item["plan_id"])
    if severity in KNOCKBACK_SEVERITIES and item["status"] == "WORK_COMPLETE":
        item["status"] = "PUNCH_FAIL"
        domain.recompute_item_overdue(item)
        repo.touch(item)
        if plan is not None:
            domain.reevaluate_plan_readiness(plan)
            domain.recompute_plan_overdue(plan)

    if plan is not None:
        domain.recompute_property_of_plan(plan)
    return repo.single(row, 201)


@route("/pip/punch-list-items/<row_id>", ["GET"], ANY_ROLE)
def get_punch_item(row_id):
    return repo.single(repo.must_find("punch_items", row_id))


@route("/pip/punch-list-items", ["GET"], ANY_ROLE)
def list_punch_items():
    limit, offset = v.pagination()
    rows = repo.rows("punch_items")
    for field in ("inspection_id", "pip_item_id", "severity", "status"):
        value = v.query_str(field)
        if value is not None:
            rows = [r for r in rows if r[field] == value]
    return repo.page(rows, limit, offset)


@route("/pip/punch-list-items/<row_id>/remediate", ["POST"], (FRANCHISEE_OWNER,))
def remediate_punch_item(row_id):
    punch = repo.must_find("punch_items", row_id)
    item = repo.find("items", punch["pip_item_id"])

    if punch["status"] != "OPEN":
        raise ApiError(
            "ERR_PUNCH_NOT_REMEDIABLE", "only an OPEN defect may be remediated"
        )

    # band 8
    if item is not None:
        guards.require_owner(domain.property_of_item(item))

    punch["status"] = "REMEDIATED"
    repo.touch(punch)

    inspection = repo.find("inspections", punch["inspection_id"])
    if inspection is not None:
        domain.recompute_inspection_punch_count(inspection)
    return repo.single(punch)


@route("/pip/punch-list-items/<row_id>/verify", ["POST"], (BRAND_INSPECTOR,))
def verify_punch_item(row_id):
    punch = repo.must_find("punch_items", row_id)
    inspection = repo.find("inspections", punch["inspection_id"])
    item = repo.find("items", punch["pip_item_id"])

    body = v.body_json()
    v.require(body, "outcome")
    outcome = v.get_enum(body, "outcome", OUTCOMES)
    note = v.get_str(body, "verification_note", required=False, max_len=500)

    # band 4
    if outcome == "WAIVE":
        if punch["status"] not in calc.OPEN_DEFECT_STATUSES:
            raise ApiError(
                "ERR_PUNCH_NOT_VERIFIABLE",
                "only an OPEN or REMEDIATED defect may be waived",
            )
    elif punch["status"] != "REMEDIATED":
        raise ApiError(
            "ERR_PUNCH_NOT_VERIFIABLE",
            "only a REMEDIATED defect may be closed or reopened",
        )

    # band 6
    if outcome == "WAIVE" and punch["severity"] == "CRITICAL":
        raise ApiError(
            "ERR_CRITICAL_DEFECT_NOT_WAIVABLE",
            "a CRITICAL defect may never be waived",
        )

    # band 8
    guards.require_assigned_inspector(inspection)

    if outcome == "CLOSE":
        punch["status"] = "VERIFIED_CLOSED"
    elif outcome == "REOPEN":
        punch["status"] = "OPEN"
    else:
        punch["status"] = "WAIVED"
    if note is not None:
        punch["verification_note"] = note
    repo.touch(punch)

    if inspection is not None:
        domain.recompute_inspection_punch_count(inspection)

    if outcome == "WAIVE":
        domain.append_ledger(
            inspection["plan_id"],
            punch["pip_item_id"],
            "PUNCH_WAIVED",
            0,
            "punch-list defect %s waived" % punch["id"],
        )

    if outcome in ("CLOSE", "WAIVE"):
        _settle_item(item)

    if item is not None:
        domain.recompute_property(domain.property_of_item(item))
    return repo.single(punch)
