"""PipItem scoping, revision and execution (PRD section 3.2, 3.6)."""

import calc
import domain
import guards
import repo
import validation as v
from db import clock_date
from errors import ApiError
from middleware import ANY_ROLE, BRAND_MANAGER, FRANCHISEE_OWNER
from routing import route

ITEM_STATUSES = (
    "SCOPED",
    "DEFERRED_PENDING_EXTENSION",
    "IN_PROGRESS",
    "WORK_COMPLETE",
    "PUNCH_FAIL",
    "ACCEPTED",
    "REMOVED_BY_DISPUTE",
    "VOIDED",
)

PREDECESSOR_SATISFIED = ("WORK_COMPLETE", "ACCEPTED", "REMOVED_BY_DISPUTE")


def _check_room_impact(room_impacting, rooms_affected_count):
    if room_impacting and rooms_affected_count < 1:
        raise ApiError(
            "ERR_ROOM_IMPACT_MISMATCH",
            "rooms_affected_count must be at least 1 when room_impacting is true",
        )
    if not room_impacting and rooms_affected_count != 0:
        raise ApiError(
            "ERR_ROOM_IMPACT_MISMATCH",
            "rooms_affected_count must be 0 when room_impacting is false",
        )


def _check_predecessor(item_id, plan_id, predecessor):
    """Band 8: same-plan rule, then the cycle rule."""
    if predecessor is None:
        return
    if predecessor["plan_id"] != plan_id:
        raise ApiError(
            "ERR_PREDECESSOR_PLAN_MISMATCH",
            "predecessor_item_id must reference an item of the same plan",
        )
    if item_id is not None and predecessor["id"] == item_id:
        raise ApiError("ERR_PREDECESSOR_CYCLE", "an item may not precede itself")

    seen = set()
    cursor = predecessor
    while cursor is not None:
        if cursor["id"] in seen:
            break
        seen.add(cursor["id"])
        if item_id is not None and cursor["id"] == item_id:
            raise ApiError(
                "ERR_PREDECESSOR_CYCLE",
                "predecessor_item_id closes a cycle in the sequencing chain",
            )
        nxt = cursor.get("predecessor_item_id")
        cursor = repo.find("items", nxt) if nxt else None


@route("/pip/items", ["POST"], (BRAND_MANAGER,))
def create_item():
    body = v.body_json()
    plan = guards.resolve_body_fk(body, "plan_id", "plans")
    predecessor = guards.resolve_body_fk(body, "predecessor_item_id", "items")

    v.require(
        body,
        "plan_id",
        "category",
        "standards_reference",
        "brand_estimated_cost_cents",
        "room_impacting",
    )
    category = v.get_enum(body, "category", calc.CATEGORIES)
    standards_reference = v.get_str(body, "standards_reference", min_len=1, max_len=40)
    estimate = v.get_int(body, "brand_estimated_cost_cents", minimum=0)
    room_impacting = v.get_bool(body, "room_impacting")
    rooms_affected = v.get_int(
        body, "rooms_affected_count", required=False, minimum=0, default=0
    )
    _check_room_impact(room_impacting, rooms_affected)

    guards.require_plan_draft(plan)
    guards.require_franchise_not_terminated(domain.property_of_plan(plan))

    _check_predecessor(None, plan["id"], predecessor)

    row = repo.new_row(
        {
            "plan_id": plan["id"],
            "predecessor_item_id": predecessor["id"] if predecessor else None,
            "category": category,
            "standards_reference": standards_reference,
            "brand_estimated_cost_cents": estimate,
            "owner_claimed_cost_cents": None,
            "approved_cost_cents": estimate,
            "item_funding_cents": 0,
            "status": "SCOPED",
            "room_impacting": room_impacting,
            "rooms_affected_count": rooms_affected,
            "extension_days_granted": 0,
            "deadline_date": None,
            "priority_rank": None,
            "is_overdue": False,
        }
    )
    repo.insert("items", row)

    domain.recompute_plan_costs(plan)
    repo.touch(plan)
    return repo.single(row, 201)


@route("/pip/items/<row_id>", ["GET"], ANY_ROLE)
def get_item(row_id):
    return repo.single(repo.must_find("items", row_id))


@route("/pip/items", ["GET"], ANY_ROLE)
def list_items():
    limit, offset = v.pagination()
    rows = repo.rows("items")
    for field in ("plan_id", "predecessor_item_id", "category", "status"):
        value = v.query_str(field)
        if value is not None:
            rows = [r for r in rows if r[field] == value]
    overdue = v.query_bool("is_overdue")
    if overdue is not None:
        if overdue == "__unresolvable__":
            rows = []
        else:
            rows = [r for r in rows if bool(r["is_overdue"]) is overdue]
    return repo.page(rows, limit, offset)


@route("/pip/items/<row_id>", ["PATCH"], (BRAND_MANAGER,))
def patch_item(row_id):
    item = repo.must_find("items", row_id)
    body = v.body_json()
    predecessor = guards.resolve_body_fk(body, "predecessor_item_id", "items")
    plan = repo.find("plans", item["plan_id"])

    v.require(body, "expected_plan_version")
    expected = v.get_int(body, "expected_plan_version")

    new_estimate = item["brand_estimated_cost_cents"]
    if v.present(body, "brand_estimated_cost_cents"):
        new_estimate = v.get_int(body, "brand_estimated_cost_cents", minimum=0)
    new_reference = item["standards_reference"]
    if v.present(body, "standards_reference"):
        new_reference = v.get_str(body, "standards_reference", min_len=1, max_len=40)
    new_category = item["category"]
    if v.present(body, "category"):
        new_category = v.get_enum(body, "category", calc.CATEGORIES)
    new_impacting = item["room_impacting"]
    if v.present(body, "room_impacting"):
        new_impacting = v.get_bool(body, "room_impacting")
    new_rooms = item["rooms_affected_count"]
    if v.present(body, "rooms_affected_count"):
        new_rooms = v.get_int(body, "rooms_affected_count", minimum=0)
    _check_room_impact(new_impacting, new_rooms)

    guards.require_plan_draft(plan)

    if expected != plan["version"]:
        raise ApiError(
            "ERR_STALE_PLAN_VERSION",
            "expected_plan_version does not match the plan's current version",
        )

    _check_predecessor(item["id"], item["plan_id"], predecessor)

    item["brand_estimated_cost_cents"] = new_estimate
    item["standards_reference"] = new_reference
    item["category"] = new_category
    item["room_impacting"] = new_impacting
    item["rooms_affected_count"] = new_rooms
    if "predecessor_item_id" in body:
        item["predecessor_item_id"] = predecessor["id"] if predecessor else None
    item["_cost_revised"] = False
    item["approved_cost_cents"] = new_estimate
    domain.recompute_item_deadline(item, plan)
    domain.recompute_item_overdue(item)
    repo.touch(item)

    domain.recompute_plan_costs(plan)
    domain.recompute_plan_funding(plan)
    domain.assign_priority_ranks(plan)
    domain.recompute_plan_overdue(plan)
    repo.touch(plan)
    return repo.single(item)


@route("/pip/items/<row_id>/start", ["POST"], (FRANCHISEE_OWNER,))
def start_item(row_id):
    item = repo.must_find("items", row_id)
    plan = repo.find("plans", item["plan_id"])
    prop = domain.property_of_plan(plan)

    # band 4
    if item["status"] != "SCOPED":
        raise ApiError("ERR_ITEM_NOT_STARTABLE", "only a SCOPED item may be started")
    guards.require_execution_window(plan)

    # band 6
    if item["category"] != "LIFE_SAFETY":
        for other in domain.plan_items(plan["id"]):
            if other["category"] == "LIFE_SAFETY" and other.get("is_overdue"):
                raise ApiError(
                    "ERR_LIFE_SAFETY_PRIORITY_VIOLATION",
                    "a life-safety item of this plan is past its deadline",
                )
    if item["room_impacting"]:
        today = clock_date()
        covered = False
        for phase in domain.phases_of_plan(plan["id"]):
            if phase["status"] != "ACTIVE":
                continue
            start = calc.parse_date(phase["start_date"])
            end = calc.parse_date(phase["end_date"])
            if (
                start is not None
                and end is not None
                and start <= today <= end
                and phase["rooms_out_of_service"] >= item["rooms_affected_count"]
            ):
                covered = True
                break
        if not covered:
            raise ApiError(
                "ERR_NO_ACTIVE_PHASE_FOR_ROOM_WORK",
                "no active renovation phase covers this room-impacting work",
            )

    # band 8
    if item["predecessor_item_id"]:
        predecessor = repo.find("items", item["predecessor_item_id"])
        if predecessor is None or predecessor["status"] not in PREDECESSOR_SATISFIED:
            raise ApiError(
                "ERR_PREDECESSOR_NOT_SATISFIED",
                "the sequencing predecessor is not finished",
            )
    guards.require_owner(prop)

    # band 10
    budget = domain.active_budget(plan["id"])
    if budget is None or budget["status"] != "LOCKED":
        raise ApiError(
            "ERR_BUDGET_NOT_LOCKED",
            "the plan has no locked active capital budget",
        )

    item["status"] = "IN_PROGRESS"
    domain.recompute_item_overdue(item)
    repo.touch(item)

    if plan["status"] == "OWNER_ACKNOWLEDGED":
        plan["status"] = "IN_EXECUTION"
        repo.touch(plan)
    domain.recompute_plan_overdue(plan)
    domain.recompute_property(prop)
    return repo.single(item)


@route("/pip/items/<row_id>/complete-work", ["POST"], (FRANCHISEE_OWNER,))
def complete_item_work(row_id):
    item = repo.must_find("items", row_id)
    plan = repo.find("plans", item["plan_id"])

    if item["status"] != "IN_PROGRESS":
        raise ApiError(
            "ERR_ITEM_NOT_IN_PROGRESS", "only an IN_PROGRESS item may be completed"
        )
    guards.require_owner(domain.property_of_plan(plan))

    item["status"] = "WORK_COMPLETE"
    domain.recompute_item_overdue(item)
    repo.touch(item)

    domain.reevaluate_plan_readiness(plan)
    domain.recompute_plan_overdue(plan)
    domain.recompute_property(domain.property_of_plan(plan))
    return repo.single(item)
