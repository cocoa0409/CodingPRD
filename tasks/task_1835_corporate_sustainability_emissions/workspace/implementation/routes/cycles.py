"""Reporting cycles, their gates, and inventory recalculation (PRD 3.2, 3.7)."""
from flask import Blueprint, request

import calc
import domain
from envelope import ok, ok_list
from errors import err, invalid_state, not_found
from http_util import (
    ASSURANCE,
    MANAGER,
    READ_ROLES,
    get_body,
    parse_pagination,
    require_roles,
    require_target_role,
    v_enum,
    v_int,
    v_str,
    v_version,
)
from store import db, new_entity, touch

bp = Blueprint("cycles", __name__, url_prefix="/sustainability")

CYCLE_STATUSES = {
    "DRAFT",
    "DATA_COLLECTION",
    "UNDER_REVIEW",
    "LOCKED",
    "UNDER_ASSURANCE",
    "ASSURED",
    "DISCLOSED",
}

# The single permitted actor per transition target (PRD 2.1 / §1.2 actor column).
CYCLE_TARGET_ROLE = {
    "DRAFT": MANAGER,
    "DATA_COLLECTION": MANAGER,
    "UNDER_REVIEW": MANAGER,
    "LOCKED": MANAGER,
    "UNDER_ASSURANCE": MANAGER,
    "DISCLOSED": MANAGER,
    "ASSURED": ASSURANCE,
}

LEGAL_EDGES = {
    ("DRAFT", "DATA_COLLECTION"),
    ("DATA_COLLECTION", "UNDER_REVIEW"),
    ("UNDER_REVIEW", "LOCKED"),
    ("LOCKED", "UNDER_ASSURANCE"),
    ("UNDER_ASSURANCE", "ASSURED"),
    ("ASSURED", "DISCLOSED"),
    ("LOCKED", "UNDER_REVIEW"),          # reopen for restatement
    ("UNDER_ASSURANCE", "UNDER_REVIEW"),  # assurance findings sent back
}

COLLECTING = ("DATA_COLLECTION", "UNDER_REVIEW")


def load_cycle(cycle_id):
    cycle = db.cycles.get(cycle_id)
    if cycle is None:
        raise not_found(f"ReportingCycle {cycle_id} not found")
    return cycle


@bp.route("/cycles", methods=["POST"])
@require_roles(MANAGER)
def create_cycle():
    body = get_body()
    name = v_str(body, "name")
    reporting_year = v_int(body, "reporting_year")
    cycle = new_entity(
        {
            "name": name,
            "reporting_year": reporting_year,
            "status": "DRAFT",
            "readiness_pct": 0.0,
            "pinned_library_version": None,
            "assurance_statement": None,
        }
    )
    db.cycles[cycle["id"]] = cycle
    # Singleton InventoryResult created with the cycle: STALE, zero totals.
    inv = new_entity(
        {
            "cycle_id": cycle["id"],
            "status": "STALE",
            "scope1_tco2e": 0.0,
            "scope2_location_tco2e": 0.0,
            "scope2_market_tco2e": 0.0,
            "scope3_tco2e": 0.0,
            "scope3_provisional_tco2e": 0.0,
            "total_tco2e": 0.0,
            "computed_at": None,
        }
    )
    db.inventories[inv["id"]] = inv
    return ok(domain.ser_cycle(cycle), status=201)


@bp.route("/cycles/<cycle_id>", methods=["GET"])
@require_roles(*READ_ROLES)
def get_cycle(cycle_id):
    return ok(domain.ser_cycle(load_cycle(cycle_id)))


@bp.route("/cycles/<cycle_id>/transition", methods=["POST"])
@require_roles(MANAGER, ASSURANCE)
def cycle_transition(cycle_id):
    body = get_body()
    # Priority 2: authorization for the specific transition target.
    require_target_role(body, CYCLE_TARGET_ROLE)
    # Priority 3: path existence.
    cycle = load_cycle(cycle_id)
    # Priority 4: request shape.
    to_state = v_enum(body, "to_state", CYCLE_STATUSES)
    statement = None
    if to_state == "ASSURED":
        statement = v_str(body, "assurance_statement")
    # Priority 6: state gate — to_state must be a legal successor.
    current = cycle["status"]
    if (current, to_state) not in LEGAL_EDGES:
        raise invalid_state(
            f"ReportingCycle in status {current} cannot transition to {to_state}"
        )

    if to_state == "LOCKED":
        # Priority 14 lock gates, in the PRD-pinned order.
        if any(
            r["cycle_id"] == cycle_id and r["status"] in ("SUBMITTED", "UNDER_REVIEW")
            for r in db.records.values()
        ):
            raise err(
                "ERR_OPEN_RECORDS_REMAIN",
                409,
                "Activity records still in SUBMITTED or UNDER_REVIEW",
            )
        if any(
            e["cycle_id"] == cycle_id
            and e["status"] not in ("ACCEPTED", "CLOSED_NO_DATA")
            for e in db.engagements.values()
        ):
            raise err(
                "ERR_OPEN_ENGAGEMENTS_REMAIN",
                409,
                "Supplier engagements not yet ACCEPTED or CLOSED_NO_DATA",
            )
        inv = calc.inventory_for_cycle(cycle_id)
        if inv["status"] != "CURRENT":
            raise err(
                "ERR_INVENTORY_STALE", 409, "InventoryResult is not CURRENT"
            )
        published_versions = [
            f["library_version"]
            for f in db.factors.values()
            if f["status"] == "PUBLISHED"
        ]
        cycle["pinned_library_version"] = (
            max(published_versions) if published_versions else 0
        )
        inv["status"] = "FROZEN"
        touch(inv)
    elif to_state == "UNDER_ASSURANCE":
        # Priority 15 aggregate gate.
        if calc.dec(cycle["readiness_pct"]) < calc.READINESS_THRESHOLD:
            raise err(
                "ERR_READINESS_BELOW_THRESHOLD",
                422,
                "readiness_pct is below 80.0",
            )
    elif to_state == "ASSURED":
        # Priority 14 freeze gate.
        inv = calc.inventory_for_cycle(cycle_id)
        if inv["status"] != "FROZEN":
            raise err(
                "ERR_INVENTORY_STALE", 409, "InventoryResult is not FROZEN"
            )
        cycle["assurance_statement"] = statement
    elif to_state == "DISCLOSED":
        # Priority 15 aggregate gate.
        if not any(
            q["cycle_id"] == cycle_id and q["status"] == "SUBMITTED"
            for q in db.questionnaires.values()
        ):
            raise err(
                "ERR_NO_SUBMITTED_QUESTIONNAIRE",
                409,
                "No SUBMITTED QuestionnaireResponse exists for this cycle",
            )
    elif to_state == "UNDER_REVIEW" and current in ("LOCKED", "UNDER_ASSURANCE"):
        # Cyclic reopen edges only (LOCKED / UNDER_ASSURANCE -> UNDER_REVIEW):
        # full staleness cascade; the assurance-findings edge also clears the
        # stored statement. pinned_library_version is retained for audit. The
        # forward DATA_COLLECTION -> UNDER_REVIEW edge has no side effects.
        calc.cascade_staleness(cycle)
        if current == "UNDER_ASSURANCE":
            cycle["assurance_statement"] = None

    cycle["status"] = to_state
    touch(cycle)
    return ok(domain.ser_cycle(cycle))


@bp.route("/cycles/<cycle_id>/inventory/recalculate", methods=["POST"])
@require_roles(MANAGER)
def recalculate(cycle_id):
    body = get_body()
    cycle = load_cycle(cycle_id)
    # Priority 4: the OCC field is non-optional (PRD 2.8).
    expected = v_version(body, "expected_cycle_version")
    # Priority 5: OCC fires before the cycle-state check (PRD 3.7 note).
    if expected != cycle["version"]:
        raise err(
            "ERR_STALE_VERSION",
            412,
            "expected_cycle_version does not match the cycle's current version",
        )
    # Priority 6: cycle gate.
    if cycle["status"] not in COLLECTING:
        raise err(
            "ERR_CYCLE_NOT_COLLECTING",
            409,
            f"Cycle in status {cycle['status']} does not permit recalculation",
        )
    inv = calc.recalc_inventory(cycle)
    calc.evaluate_targets_for_cycle(cycle, inv)
    touch(cycle)
    return ok(domain.ser_inventory(inv))


@bp.route("/inventory-results/<inv_id>", methods=["GET"])
@require_roles(*READ_ROLES)
def get_inventory(inv_id):
    inv = db.inventories.get(inv_id)
    if inv is None:
        raise not_found(f"InventoryResult {inv_id} not found")
    return ok(domain.ser_inventory(inv))


@bp.route("/inventory-results", methods=["GET"])
@require_roles(*READ_ROLES)
def list_inventories():
    limit, offset = parse_pagination()
    cycle_id = request.args.get("cycle_id")
    items = sorted(db.inventories.values(), key=lambda x: x["_seq"])
    if cycle_id is not None:
        items = [i for i in items if i["cycle_id"] == cycle_id]
    total = len(items)
    page = items[offset : offset + limit]
    return ok_list([domain.ser_inventory(i) for i in page], limit, offset, total)
