"""Assignments, preferential purchase rights and closings (PRD 3.9)."""
from flask import Blueprint

from calc import (PPR_NOTICE_DAYS, active_position, bond_requirement, db,
                  get_owner, get_transfer, get_well, guard_terminal,
                  recompute_consent_wi, recompute_required_bond,
                  well_interests)
from common import add_days, dec, ok, ok_list, q6, today, touch
from errors import fail
from store import by_created, insert, out_transfer, rows
from validate import (READ_ALL, ROLE_LAND, ROLE_PARTNER, acting_user,
                      authenticate, authorize, body, filt, pagination, require,
                      v_cents, v_date, v_enum, v_id, v_pct, window)

bp = Blueprint("transfers", __name__)

ELECTION_VALUES = ("EXERCISE", "WAIVE")


def eligible_holders(well_id, assignor_owner_id, assignee_owner_id):
    holders = []
    for position in well_interests(well_id, "ACTIVE"):
        if not position.get("preferential_right"):
            continue
        if position["owner_id"] in (assignor_owner_id, assignee_owner_id):
            continue
        if position["owner_id"] not in holders:
            holders.append(position["owner_id"])
    return holders


def prospective_grantee_id(transfer):
    if transfer["transfer_status"] == "PPR_EXERCISED" and transfer["ppr_holder_owner_id"]:
        return transfer["ppr_holder_owner_id"]
    return transfer["assignee_owner_id"]


def recompute_bond_check(transfer):
    grantee_id = prospective_grantee_id(transfer)
    value = bond_requirement(grantee_id,
                             [(transfer["well_id"], transfer["transfer_wi_pct"])])
    transfer["bond_check_required_cents"] = value


@bp.route("/wells/<well_id>/assignment-transfers", methods=["POST"])
def serve_notice(well_id):
    authenticate()
    authorize(ROLE_LAND)
    data = body()
    require(data, ["assignor_owner_id", "assignee_owner_id", "transfer_wi_pct",
                   "transfer_nri_pct", "sale_price_cents", "notice_date",
                   "effective_date"])
    assignor_owner_id = v_id(data, "assignor_owner_id")
    assignee_owner_id = v_id(data, "assignee_owner_id")
    transfer_wi_pct = v_pct(data, "transfer_wi_pct", min_exclusive=True)
    transfer_nri_pct = v_pct(data, "transfer_nri_pct", min_exclusive=True)
    sale_price_cents = v_cents(data, "sale_price_cents", strictly_positive=True)
    notice_date = v_date(data, "notice_date")
    effective_date = v_date(data, "effective_date")

    well = get_well(well_id)
    guard_terminal("well", well)
    assignor = get_owner(assignor_owner_id)
    assignee = get_owner(assignee_owner_id)

    if notice_date > effective_date:
        fail("ERR_EFFECTIVE_DATE_OUT_OF_RANGE")
    if assignor["owner_type"] != "WORKING_INTEREST_PARTNER":
        fail("ERR_OWNER_TYPE_INVALID")
    if assignee["owner_type"] != "WORKING_INTEREST_PARTNER":
        fail("ERR_OWNER_TYPE_INVALID")
    position = active_position(well["id"], assignor["id"])
    if position is None:
        fail("ERR_NOT_AN_INTEREST_HOLDER")
    if transfer_wi_pct > dec(position["working_interest_pct"]):
        fail("ERR_TRANSFER_EXCEEDS_HOLDING")
    if transfer_nri_pct > transfer_wi_pct:
        fail("ERR_TRANSFER_EXCEEDS_HOLDING")
    if transfer_nri_pct > dec(position["net_revenue_interest_pct"]):
        fail("ERR_TRANSFER_EXCEEDS_HOLDING")

    holders = eligible_holders(well["id"], assignor["id"], assignee["id"])
    transfer = insert("transfers", {
        "well_id": well["id"],
        "assignor_owner_id": assignor["id"],
        "assignee_owner_id": assignee["id"],
        "ppr_holder_owner_id": None,
        "transfer_wi_pct": transfer_wi_pct,
        "transfer_nri_pct": transfer_nri_pct,
        "sale_price_cents": sale_price_cents,
        "notice_date": notice_date,
        "effective_date": effective_date,
        "ppr_deadline_date": add_days(notice_date, PPR_NOTICE_DAYS),
        "ppr_eligible_count": len(holders),
        "ppr_waiver_count": 0,
        "bond_check_required_cents": 0,
        "transfer_status": "PPR_WAIVED" if not holders else "NOTICED",
    })
    recompute_bond_check(transfer)
    db.ppr_elections[transfer["id"]] = {}
    return ok(out_transfer(transfer), 201)


@bp.route("/assignment-transfers", methods=["GET"])
def list_transfers():
    authenticate()
    authorize(*READ_ALL)
    limit, offset = pagination()
    found = rows("transfers")
    for name in ("well_id", "assignor_owner_id", "assignee_owner_id",
                 "ppr_holder_owner_id", "transfer_status"):
        value = filt(name)
        if value is not None:
            found = [t for t in found if t[name] == value]
    found = by_created(found)
    page, total = window(found, limit, offset)
    return ok_list([out_transfer(t) for t in page], limit, offset, total)


@bp.route("/assignment-transfers/<transfer_id>", methods=["GET"])
def read_transfer(transfer_id):
    authenticate()
    authorize(*READ_ALL)
    return ok(out_transfer(get_transfer(transfer_id)))


@bp.route("/assignment-transfers/<transfer_id>/ppr-elections", methods=["POST"])
def ppr_election(transfer_id):
    authenticate()
    authorize(ROLE_PARTNER)
    data = body()
    require(data, ["election"])
    election = v_enum(data, "election", ELECTION_VALUES)

    transfer = get_transfer(transfer_id)
    guard_terminal("transfer", transfer)
    if transfer["transfer_status"] != "NOTICED":
        fail("ERR_TRANSFER_NOT_PENDING")
    me = acting_user()
    cast = db.ppr_elections.setdefault(transfer["id"], {})
    if me in cast:
        fail("ERR_PPR_ELECTION_ALREADY_SUBMITTED")
    if today() > transfer["ppr_deadline_date"]:
        fail("ERR_PPR_WINDOW_EXPIRED")
    holders = eligible_holders(transfer["well_id"], transfer["assignor_owner_id"],
                              transfer["assignee_owner_id"])
    if me not in holders:
        fail("ERR_PPR_HOLDER_INVALID")

    cast[me] = election
    if election == "EXERCISE":
        transfer["transfer_status"] = "PPR_EXERCISED"
        transfer["ppr_holder_owner_id"] = me
    else:
        transfer["ppr_waiver_count"] = transfer["ppr_waiver_count"] + 1
        if transfer["ppr_waiver_count"] == transfer["ppr_eligible_count"]:
            transfer["transfer_status"] = "PPR_WAIVED"
        recompute_bond_check(transfer)
    touch(transfer)
    return ok(out_transfer(transfer))


@bp.route("/assignment-transfers/<transfer_id>/closing", methods=["POST"])
def close_transfer(transfer_id):
    authenticate()
    authorize(ROLE_LAND)
    data = body()
    require(data, ["closing_date"])
    closing_date = v_date(data, "closing_date")

    transfer = get_transfer(transfer_id)
    guard_terminal("transfer", transfer)
    if transfer["transfer_status"] not in ("PPR_WAIVED", "PPR_EXERCISED"):
        fail("ERR_TRANSFER_NOT_CLOSEABLE")
    window_shut = (transfer["ppr_waiver_count"] == transfer["ppr_eligible_count"]
                   or today() > transfer["ppr_deadline_date"])
    if not window_shut:
        fail("ERR_PPR_WINDOW_OPEN")

    grantee_id = prospective_grantee_id(transfer)
    grantee = db.owners.get(grantee_id)
    if grantee is None:
        fail("ERR_INTEREST_OWNER_NOT_FOUND")
    if not grantee["tax_id_on_file"]:
        fail("ERR_OWNER_NOT_COMPLIANT")
    if grantee["bond_posted_cents"] < transfer["bond_check_required_cents"]:
        fail("ERR_INSUFFICIENT_BOND")

    well = db.wells[transfer["well_id"]]
    assignor = db.owners[transfer["assignor_owner_id"]]
    assignor_row = active_position(well["id"], assignor["id"])
    if assignor_row is None:
        fail("ERR_NOT_AN_INTEREST_HOLDER")

    transfer_wi = dec(transfer["transfer_wi_pct"])
    transfer_nri = dec(transfer["transfer_nri_pct"])
    retained_wi = q6(dec(assignor_row["working_interest_pct"]) - transfer_wi)
    retained_nri = q6(dec(assignor_row["net_revenue_interest_pct"]) - transfer_nri)
    carried_balance = 0

    # --- assignor side -------------------------------------------------
    assignor_row["effective_to"] = closing_date
    if retained_wi == 0:
        # Full conveyance: no replacement row; the non-consent receivable
        # runs with the interest onto the grantee's new row.
        assignor_row["interest_status"] = "TERMINATED"
        carried_balance = assignor_row["non_consent_recoverable_balance_cents"]
        touch(assignor_row)
    else:
        assignor_row["interest_status"] = "SUPERSEDED"
        touch(assignor_row)
        insert("interests", {
            "well_id": well["id"],
            "owner_id": assignor["id"],
            "working_interest_pct": retained_wi,
            "net_revenue_interest_pct": retained_nri,
            "effective_from": closing_date,
            "effective_to": None,
            "is_operator": assignor_row["is_operator"],
            "preferential_right": assignor_row["preferential_right"],
            "interest_status": "ACTIVE",
            "non_consent_flag": assignor_row["non_consent_flag"],
            "non_consent_recoverable_balance_cents":
                assignor_row["non_consent_recoverable_balance_cents"],
        })

    # --- grantee side --------------------------------------------------
    grantee_row = active_position(well["id"], grantee["id"])
    if grantee_row is not None:
        grantee_row["effective_to"] = closing_date
        grantee_row["interest_status"] = "SUPERSEDED"
        touch(grantee_row)
        insert("interests", {
            "well_id": well["id"],
            "owner_id": grantee["id"],
            "working_interest_pct": q6(dec(grantee_row["working_interest_pct"])
                                       + transfer_wi),
            "net_revenue_interest_pct": q6(dec(grantee_row["net_revenue_interest_pct"])
                                           + transfer_nri),
            "effective_from": closing_date,
            "effective_to": None,
            "is_operator": grantee_row["is_operator"],
            "preferential_right": grantee_row["preferential_right"],
            "interest_status": "ACTIVE",
            "non_consent_flag": grantee_row["non_consent_flag"],
            "non_consent_recoverable_balance_cents":
                grantee_row["non_consent_recoverable_balance_cents"] + carried_balance,
        })
    else:
        insert("interests", {
            "well_id": well["id"],
            "owner_id": grantee["id"],
            "working_interest_pct": q6(transfer_wi),
            "net_revenue_interest_pct": q6(transfer_nri),
            "effective_from": closing_date,
            "effective_to": None,
            "is_operator": False,
            "preferential_right": False,
            "interest_status": "ACTIVE",
            "non_consent_flag": False,
            "non_consent_recoverable_balance_cents": carried_balance,
        })

    transfer["transfer_status"] = "CLOSED"
    transfer["effective_date"] = closing_date
    touch(transfer)

    recompute_required_bond(assignor)
    recompute_required_bond(grantee)
    recompute_consent_wi(well)
    touch(well)
    return ok(out_transfer(transfer))
