"""Interest owners, working-interest positions and bonding (PRD 3.3)."""
from datetime import date

from flask import Blueprint

from calc import (db, get_interest, get_owner, get_well, guard_terminal,
                  owner_disbursements, owner_interests, recompute_consent_wi,
                  recompute_required_bond, recompute_suspense_balance,
                  well_interests)
from common import ZERO6, dec, ok, ok_list, q6, touch
from errors import fail
from store import by_created, insert, out_interest, out_line_item, out_owner, rows
from validate import (READ_ALL, READ_INTERNAL, ROLE_AUDIT, ROLE_COMPLIANCE,
                      ROLE_JIA, ROLE_LAND, ROLE_PARTNER, authenticate,
                      authorize, body, filt, pagination, present, require,
                      v_bool, v_cents, v_date, v_enum, v_id, v_int, v_pct,
                      v_str, window)

bp = Blueprint("owners", __name__)

OWNER_TYPES = ("WORKING_INTEREST_PARTNER", "ROYALTY_OWNER",
               "OVERRIDING_ROYALTY_OWNER")
INTEREST_STATUSES = ("ACTIVE", "SUPERSEDED", "TERMINATED")

OPEN_ENDED = date(9999, 12, 31)


def half_open_overlap(from_a, to_a, from_b, to_b):
    end_a = to_a or OPEN_ENDED
    end_b = to_b or OPEN_ENDED
    return from_a < end_b and from_b < end_a


@bp.route("/interest-owners", methods=["POST"])
def register_owner():
    authenticate()
    authorize(ROLE_LAND)
    data = body()
    require(data, ["owner_name", "owner_type", "contact_email"])
    owner_name = v_str(data, "owner_name", 1)
    owner_type = v_enum(data, "owner_type", OWNER_TYPES)
    contact_email = v_str(data, "contact_email", 1)
    tax_id_on_file = v_bool(data, "tax_id_on_file", False)
    bond_posted_cents = v_cents(data, "bond_posted_cents", 0)
    audit_window_days = v_int(data, "audit_window_days", 90, 1460, 730)

    owner = insert("owners", {
        "owner_name": owner_name,
        "owner_type": owner_type,
        "contact_email": contact_email,
        "tax_id_on_file": tax_id_on_file,
        "bond_posted_cents": bond_posted_cents,
        "required_bond_cents": 0,
        "suspense_balance_cents": 0,
        "audit_window_days": audit_window_days,
    })
    return ok(out_owner(owner), 201)


@bp.route("/interest-owners", methods=["GET"])
def list_owners():
    authenticate()
    authorize(*READ_INTERNAL)
    limit, offset = pagination()
    found = rows("owners")
    owner_type = filt("owner_type")
    if owner_type is not None:
        found = [o for o in found if o["owner_type"] == owner_type]
    found = by_created(found)
    page, total = window(found, limit, offset)
    return ok_list([out_owner(o) for o in page], limit, offset, total)


@bp.route("/interest-owners/<owner_id>", methods=["GET"])
def read_owner(owner_id):
    authenticate()
    authorize(*READ_ALL)
    return ok(out_owner(get_owner(owner_id)))


@bp.route("/interest-owners/<owner_id>/compliance-updates", methods=["POST"])
def update_compliance(owner_id):
    authenticate()
    authorize(ROLE_COMPLIANCE)
    data = body()
    tax_id_on_file = v_bool(data, "tax_id_on_file")
    bond_posted_cents = v_cents(data, "bond_posted_cents")
    audit_window_days = v_int(data, "audit_window_days", 90, 1460)
    owner = get_owner(owner_id)

    if tax_id_on_file is not None:
        owner["tax_id_on_file"] = tax_id_on_file
    if bond_posted_cents is not None:
        owner["bond_posted_cents"] = bond_posted_cents
    if audit_window_days is not None:
        owner["audit_window_days"] = audit_window_days
    touch(owner)
    recompute_required_bond(owner)

    if tax_id_on_file is True:
        for disb in owner_disbursements(owner["id"]):
            if disb["disbursement_status"] == "SUSPENDED" \
                    and disb["suspense_reason"] == "MISSING_TAX_ID":
                disb["disbursement_status"] = "ACCRUED"
                disb["suspense_reason"] = None
                touch(disb)
        recompute_suspense_balance(owner)
    return ok(out_owner(owner))


@bp.route("/interest-owners/<owner_key>/jib-line-items", methods=["GET"])
def list_owner_line_items(owner_key):
    authenticate()
    authorize(ROLE_LAND, ROLE_JIA, ROLE_AUDIT, ROLE_PARTNER)
    limit, offset = pagination()
    owner = get_owner(owner_key)
    found = [l for l in rows("line_items") if l["owner_id"] == owner["id"]]
    statement_status = filt("statement_status")
    if statement_status is not None:
        keep = []
        for line in found:
            statement = db.statements.get(line["statement_id"])
            if statement is not None and statement["statement_status"] == statement_status:
                keep.append(line)
        found = keep
    found = by_created(found)
    page, total = window(found, limit, offset)
    return ok_list([out_line_item(l) for l in page], limit, offset, total)


@bp.route("/wells/<well_id>/interests", methods=["POST"])
def record_interest(well_id):
    authenticate()
    authorize(ROLE_LAND)
    data = body()
    require(data, ["owner_id", "working_interest_pct", "net_revenue_interest_pct",
                   "effective_from", "expected_well_version"])
    owner_id = v_id(data, "owner_id")
    working_interest_pct = v_pct(data, "working_interest_pct", min_exclusive=True)
    net_revenue_interest_pct = v_pct(data, "net_revenue_interest_pct", min_exclusive=True)
    effective_from = v_date(data, "effective_from")
    effective_to = v_date(data, "effective_to")
    is_operator = v_bool(data, "is_operator", False)
    preferential_right = v_bool(data, "preferential_right", False)
    expected_version = v_int(data, "expected_well_version")

    well = get_well(well_id)
    owner = get_owner(owner_id)
    if expected_version != well["version"]:
        fail("ERR_STALE_WELL_VERSION")
    guard_terminal("well", well)

    if owner["owner_type"] != "WORKING_INTEREST_PARTNER":
        fail("ERR_OWNER_TYPE_INVALID")

    for existing in well_interests(well["id"]):
        if existing["owner_id"] != owner["id"]:
            continue
        if existing["interest_status"] == "TERMINATED":
            continue
        if half_open_overlap(effective_from, effective_to,
                             existing["effective_from"], existing["effective_to"]):
            fail("ERR_INTEREST_PERIOD_OVERLAP")

    active_sum = dec(0)
    for existing in well_interests(well["id"], "ACTIVE"):
        active_sum += existing["working_interest_pct"]
    if q6(active_sum + working_interest_pct) > dec("1.000000"):
        fail("ERR_WI_SUM_EXCEEDED")

    if net_revenue_interest_pct > working_interest_pct:
        fail("ERR_NRI_EXCEEDS_WI")

    interest = insert("interests", {
        "well_id": well["id"],
        "owner_id": owner["id"],
        "working_interest_pct": working_interest_pct,
        "net_revenue_interest_pct": net_revenue_interest_pct,
        "effective_from": effective_from,
        "effective_to": effective_to,
        "is_operator": is_operator,
        "preferential_right": preferential_right,
        "interest_status": "ACTIVE",
        "non_consent_flag": False,
        "non_consent_recoverable_balance_cents": 0,
    })
    recompute_required_bond(owner)
    recompute_consent_wi(well)
    touch(well)
    return ok(out_interest(interest), 201)


@bp.route("/well-interests", methods=["GET"])
def list_interests():
    authenticate()
    authorize(*READ_ALL)
    limit, offset = pagination()
    found = rows("interests")
    for name in ("well_id", "owner_id", "interest_status"):
        value = filt(name)
        if value is not None:
            found = [i for i in found if i[name] == value]
    flag = filt("non_consent_flag")
    if flag is not None:
        wanted = flag.strip().lower() in ("true", "1", "yes")
        found = [i for i in found if bool(i["non_consent_flag"]) == wanted]
    found = by_created(found)
    page, total = window(found, limit, offset)
    return ok_list([out_interest(i) for i in page], limit, offset, total)


@bp.route("/well-interests/<interest_id>", methods=["GET"])
def read_interest(interest_id):
    authenticate()
    authorize(*READ_ALL)
    return ok(out_interest(get_interest(interest_id)))


@bp.route("/well-interests/<interest_id>/termination", methods=["POST"])
def terminate_interest(interest_id):
    authenticate()
    authorize(ROLE_LAND)
    data = body()
    require(data, ["effective_to"])
    effective_to = v_date(data, "effective_to")
    interest = get_interest(interest_id)
    guard_terminal("interest", interest)
    if interest["interest_status"] != "ACTIVE":
        fail("ERR_INTEREST_NOT_ACTIVE")

    owner = db.owners.get(interest["owner_id"])
    remaining = [i for i in owner_interests(interest["owner_id"], "ACTIVE")
                 if i["id"] != interest["id"]]
    if not remaining and owner is not None and owner["suspense_balance_cents"] != 0:
        fail("ERR_SUSPENSE_BALANCE_NONZERO")

    interest["interest_status"] = "TERMINATED"
    interest["effective_to"] = effective_to
    touch(interest)
    well = db.wells.get(interest["well_id"])
    if owner is not None:
        recompute_required_bond(owner)
    if well is not None:
        recompute_consent_wi(well)
        touch(well)
    return ok(out_interest(interest))
