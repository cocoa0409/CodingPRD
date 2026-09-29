"""Wells, pooled units and committed acreage (PRD 3.2)."""
from flask import Blueprint

from calc import (SHUT_IN_FIRST_PAYMENT_DAYS, bond_requirement, db, get_allocation,
                  get_lease, get_well, guard_terminal, lease_allocations,
                  operator_interest, plugging_liability, recompute_allocation_factors,
                  recompute_lease_acres, recompute_consent_wi, well_allocations,
                  well_interests, well_statements)
from common import ZERO6, add_days, dec, ok, ok_list, q2, today, touch
from errors import fail
from store import by_created, insert, out_allocation, out_well, rows
from validate import (READ_ALL, READ_INTERNAL, ROLE_LAND, authenticate,
                      authorize, body, filt, pagination, present, require,
                      v_date, v_enum, v_id, v_int, v_number, window)

bp = Blueprint("wells", __name__)

WELL_STATUSES = ("PROPOSED", "DRILLING", "PRODUCING", "SHUT_IN",
                 "TEMPORARILY_ABANDONED", "PLUGGED")
POOLING_STATUSES = ("UNPOOLED", "POOLED_FORMING", "POOLED_EFFECTIVE",
                    "POOLED_TERMINATED")
PRODUCT_TYPES = ("OIL", "GAS")

DECLARED_TRANSITIONS = {
    ("PROPOSED", "DRILLING"),
    ("DRILLING", "PRODUCING"),
    ("PRODUCING", "SHUT_IN"),
    ("SHUT_IN", "PRODUCING"),
    ("PRODUCING", "TEMPORARILY_ABANDONED"),
    ("SHUT_IN", "TEMPORARILY_ABANDONED"),
    ("TEMPORARILY_ABANDONED", "PLUGGED"),
}


def check_well_version(well, payload, field="expected_well_version"):
    if not present(payload, field):
        return
    expected = v_int(payload, field)
    if expected != well["version"]:
        fail("ERR_STALE_WELL_VERSION")


@bp.route("/wells", methods=["POST"])
def create_well():
    authenticate()
    authorize(ROLE_LAND)
    data = body()
    require(data, ["well_name", "api_number", "product_type", "total_depth_ft"])
    from validate import v_str
    well_name = v_str(data, "well_name", 1, 32)
    api_number = v_str(data, "api_number", 1)
    product_type = v_enum(data, "product_type", PRODUCT_TYPES)
    total_depth_ft = v_int(data, "total_depth_ft", 1, 30000)
    spud_date = v_date(data, "spud_date")

    for existing in rows("wells"):
        if existing["api_number"] == api_number:
            fail("ERR_DUPLICATE_API_NUMBER")

    well = insert("wells", {
        "well_name": well_name,
        "api_number": api_number,
        "product_type": product_type,
        "total_depth_ft": total_depth_ft,
        "spud_date": spud_date,
        "first_production_date": None,
        "shut_in_since": None,
        "well_status": "PROPOSED",
        "pooling_status": "UNPOOLED",
        "allocation_factor_total": ZERO6,
        "consent_working_interest_pct": ZERO6,
        "plugging_liability_cents": plugging_liability(total_depth_ft),
        "billed_to_date_cents": 0,
    })
    return ok(out_well(well), 201)


@bp.route("/wells", methods=["GET"])
def list_wells():
    authenticate()
    authorize(*READ_ALL)
    limit, offset = pagination()
    found = rows("wells")
    for name in ("well_status", "pooling_status", "product_type"):
        value = filt(name)
        if value is not None:
            found = [w for w in found if w[name] == value]
    found = by_created(found)
    page, total = window(found, limit, offset)
    return ok_list([out_well(w) for w in page], limit, offset, total)


@bp.route("/wells/<well_id>", methods=["GET"])
def read_well(well_id):
    authenticate()
    authorize(*READ_ALL)
    return ok(out_well(get_well(well_id)))


@bp.route("/wells/<well_id>/lease-allocations", methods=["POST"])
def commit_acreage(well_id):
    authenticate()
    authorize(ROLE_LAND)
    data = body()
    require(data, ["lease_id", "committed_acres"])
    lease_id = v_id(data, "lease_id")
    committed_acres = v_number(data, "committed_acres", places=2)
    well = get_well(well_id)
    lease = get_lease(lease_id)
    guard_terminal("well", well)

    if well["pooling_status"] not in ("UNPOOLED", "POOLED_FORMING"):
        fail("ERR_POOLING_NOT_FORMING")
    if lease["tenure_status"] == "EXPIRED":
        fail("ERR_LEASE_NOT_ACTIVE")
    for existing in well_allocations(well["id"], committed_only=True):
        if existing["lease_id"] == lease["id"]:
            fail("ERR_DUPLICATE_ALLOCATION")
    remaining = dec(lease["gross_acres"]) - dec(lease["committed_acres_total"])
    if committed_acres <= 0 or committed_acres > remaining:
        fail("ERR_ALLOCATION_EXCEEDS_LEASE")

    allocation = insert("allocations", {
        "well_id": well["id"],
        "lease_id": lease["id"],
        "committed_acres": committed_acres,
        "allocation_factor": ZERO6,
        "allocation_status": "COMMITTED",
        "withdrawn_reason": None,
    })
    if well["pooling_status"] == "UNPOOLED":
        well["pooling_status"] = "POOLED_FORMING"
    touch(well)
    touch(lease)
    recompute_allocation_factors(well)
    recompute_lease_acres(lease)
    return ok(out_allocation(allocation), 201)


@bp.route("/lease-allocations", methods=["GET"])
def list_allocations():
    authenticate()
    authorize(*READ_INTERNAL)
    limit, offset = pagination()
    found = rows("allocations")
    for name in ("well_id", "lease_id", "allocation_status"):
        value = filt(name)
        if value is not None:
            found = [a for a in found if a[name] == value]
    found = by_created(found)
    page, total = window(found, limit, offset)
    return ok_list([out_allocation(a) for a in page], limit, offset, total)


@bp.route("/lease-allocations/<allocation_id>", methods=["GET"])
def read_allocation(allocation_id):
    authenticate()
    authorize(*READ_INTERNAL)
    return ok(out_allocation(get_allocation(allocation_id)))


@bp.route("/wells/<well_id>/pooling-effectuation", methods=["POST"])
def effectuate_pooling(well_id):
    authenticate()
    authorize(ROLE_LAND)
    data = body()
    require(data, ["effective_date"])
    v_date(data, "effective_date")
    well = get_well(well_id)
    guard_terminal("well", well)

    if well["pooling_status"] != "POOLED_FORMING":
        fail("ERR_POOLING_NOT_FORMING")
    committed = well_allocations(well["id"], committed_only=True)
    for alloc in committed:
        lease = db.leases.get(alloc["lease_id"])
        if lease is None or lease["tenure_status"] == "EXPIRED":
            fail("ERR_LEASE_NOT_HELD")
    if len(committed) < 2:
        fail("ERR_POOLING_MINIMUM_NOT_MET")
    recompute_allocation_factors(well)
    if well["allocation_factor_total"] != dec("1.000000"):
        fail("ERR_POOLING_MINIMUM_NOT_MET")

    well["pooling_status"] = "POOLED_EFFECTIVE"
    touch(well)
    return ok(out_well(well))


@bp.route("/wells/<well_id>/status-changes", methods=["POST"])
def change_well_status(well_id):
    authenticate()
    authorize(ROLE_LAND)
    data = body()
    require(data, ["to_status", "effective_date"])
    to_status = v_enum(data, "to_status", WELL_STATUSES)
    v_date(data, "effective_date")
    well = get_well(well_id)
    check_well_version(well, data)
    guard_terminal("well", well)

    current = well["well_status"]
    if (current, to_status) not in DECLARED_TRANSITIONS:
        fail("ERR_WELL_INVALID_STATUS")

    now_date = today()

    if to_status == "DRILLING":
        if well["pooling_status"] != "POOLED_EFFECTIVE":
            fail("ERR_WELL_NOT_POOLED")
        well["spud_date"] = now_date
    elif to_status == "PRODUCING":
        if current == "DRILLING":
            operator = operator_interest(well["id"])
            if operator is None:
                fail("ERR_NO_OPERATOR_INTEREST")
            if well["first_production_date"] is None:
                well["first_production_date"] = now_date
        else:
            # SHUT_IN -> PRODUCING reverses the shut-in bookkeeping.
            well["shut_in_since"] = None
            for alloc in well_allocations(well["id"], committed_only=True):
                lease = db.leases.get(alloc["lease_id"])
                if lease is None:
                    continue
                lease["shut_in_start_date"] = None
                lease["shut_in_payments_made"] = 0
                lease["shut_in_next_due_date"] = None
                touch(lease)
    elif to_status == "SHUT_IN":
        well["shut_in_since"] = now_date
        for alloc in well_allocations(well["id"], committed_only=True):
            lease = db.leases.get(alloc["lease_id"])
            if lease is None:
                continue
            lease["shut_in_start_date"] = now_date
            lease["shut_in_payments_made"] = 0
            lease["shut_in_next_due_date"] = add_days(now_date, SHUT_IN_FIRST_PAYMENT_DAYS)
            touch(lease)
    elif to_status == "PLUGGED":
        for statement in well_statements(well["id"]):
            if statement["statement_status"] in ("ISSUED", "DISPUTED"):
                fail("ERR_UNSETTLED_STATEMENTS")
        well["plugging_liability_cents"] = plugging_liability(well["total_depth_ft"])
        for position in well_interests(well["id"], "ACTIVE"):
            owner = db.owners.get(position["owner_id"])
            if owner is None:
                continue
            if owner["bond_posted_cents"] < bond_requirement(owner["id"]):
                fail("ERR_PLUGGING_BOND_SHORTFALL")

    well["well_status"] = to_status
    touch(well)
    return ok(out_well(well))
