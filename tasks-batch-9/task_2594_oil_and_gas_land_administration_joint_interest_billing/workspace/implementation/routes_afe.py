"""Authorizations for expenditure, elections and non-consent (PRD 3.4)."""
from flask import Blueprint

from calc import (active_position, afe_elections, db, get_afe, get_election,
                  get_owner, get_well, guard_terminal, operator_interest,
                  owner_disbursements, recompute_consent_wi,
                  recompute_suspense_balance, revenue_disbursements,
                  well_interests)
from common import ZERO6, dec, now_ts, ok, ok_list, q6, rhu, today, touch
from errors import fail
from store import by_created, insert, out_afe, out_election, rows
from validate import (READ_ALL, ROLE_LAND, ROLE_PARTNER, acting_user,
                      authenticate, authorize, body, filt, is_partner,
                      pagination, require, v_cents, v_date, v_enum, v_id,
                      v_multiple, v_pct, v_str, window)

bp = Blueprint("afes", __name__)

OPERATION_TYPES = ("DRILL", "COMPLETION", "WORKOVER", "RECOMPLETION")
COST_CLASSES = ("CAPITAL", "OPERATING")
ELECTION_TYPES = ("CONSENT", "NON_CONSENT")


def penalty_amount(afe, election_type, wi_snapshot):
    if election_type != "NON_CONSENT" or afe["cost_class"] != "CAPITAL":
        return 0
    return rhu(dec(afe["non_consent_penalty_multiple"])
               * dec(afe["estimated_cost_cents"]) * dec(wi_snapshot))


@bp.route("/wells/<well_id>/afes", methods=["POST"])
def create_afe(well_id):
    authenticate()
    authorize(ROLE_LAND)
    data = body()
    require(data, ["afe_number", "operation_type", "estimated_cost_cents",
                   "cost_class", "election_deadline_date"])
    afe_number = v_str(data, "afe_number", 1, 32)
    operation_type = v_enum(data, "operation_type", OPERATION_TYPES)
    estimated_cost_cents = v_cents(data, "estimated_cost_cents", strictly_positive=True)
    cost_class = v_enum(data, "cost_class", COST_CLASSES)
    election_deadline_date = v_date(data, "election_deadline_date")
    penalty_multiple = v_multiple(data, "non_consent_penalty_multiple", dec("3.0"))
    minimum_consent_pct = v_pct(data, "minimum_consent_pct", dec("0.500000"),
                                min_exclusive=True)

    well = get_well(well_id)
    guard_terminal("well", well)

    afe = insert("afes", {
        "well_id": well["id"],
        "afe_number": afe_number,
        "operation_type": operation_type,
        "estimated_cost_cents": estimated_cost_cents,
        "cost_class": cost_class,
        "election_deadline_date": election_deadline_date,
        "non_consent_penalty_multiple": penalty_multiple,
        "minimum_consent_pct": minimum_consent_pct,
        "afe_status": "ELECTIONS_OPEN",
        "consent_working_interest_pct": ZERO6,
        "non_consent_working_interest_pct": ZERO6,
        "elections_closed_at": None,
    })
    return ok(out_afe(afe), 201)


@bp.route("/afes", methods=["GET"])
def list_afes():
    authenticate()
    authorize(*READ_ALL)
    limit, offset = pagination()
    found = rows("afes")
    for name in ("well_id", "afe_status", "cost_class"):
        value = filt(name)
        if value is not None:
            found = [a for a in found if a[name] == value]
    found = by_created(found)
    page, total = window(found, limit, offset)
    return ok_list([out_afe(a) for a in page], limit, offset, total)


@bp.route("/afes/<afe_id>", methods=["GET"])
def read_afe(afe_id):
    authenticate()
    authorize(*READ_ALL)
    return ok(out_afe(get_afe(afe_id)))


@bp.route("/afe-elections", methods=["GET"])
def list_elections():
    authenticate()
    authorize(*READ_ALL)
    limit, offset = pagination()
    found = rows("elections")
    for name in ("afe_id", "owner_id", "election_status", "election_type"):
        value = filt(name)
        if value is not None:
            found = [e for e in found if e[name] == value]
    found = by_created(found)
    page, total = window(found, limit, offset)
    return ok_list([out_election(e) for e in page], limit, offset, total)


@bp.route("/afe-elections/<election_id>", methods=["GET"])
def read_election(election_id):
    authenticate()
    authorize(*READ_ALL)
    return ok(out_election(get_election(election_id)))


@bp.route("/afes/<afe_id>/elections", methods=["POST"])
def submit_election(afe_id):
    authenticate()
    authorize(ROLE_PARTNER, ROLE_LAND)
    data = body()
    require(data, ["owner_id", "election_type"])
    owner_id = v_id(data, "owner_id")
    election_type = v_enum(data, "election_type", ELECTION_TYPES)

    afe = get_afe(afe_id)
    owner = get_owner(owner_id)
    if is_partner() and acting_user() != owner["id"]:
        fail("ERR_OWNER_MISMATCH")

    if afe["afe_status"] != "ELECTIONS_OPEN":
        fail("ERR_AFE_ELECTIONS_CLOSED")
    for existing in afe_elections(afe["id"]):
        if existing["owner_id"] == owner["id"] \
                and existing["election_status"] == "SUBMITTED":
            fail("ERR_ELECTION_ALREADY_SUBMITTED")

    positions = [i for i in well_interests(afe["well_id"])
                 if i["owner_id"] == owner["id"]]
    active = active_position(afe["well_id"], owner["id"])
    if positions and active is None:
        fail("ERR_INTEREST_NOT_ACTIVE")
    if today() > afe["election_deadline_date"]:
        fail("ERR_ELECTION_DEADLINE_PASSED")
    if owner["owner_type"] != "WORKING_INTEREST_PARTNER":
        fail("ERR_OWNER_TYPE_INVALID")
    if active is None:
        fail("ERR_NOT_AN_INTEREST_HOLDER")
    if election_type == "NON_CONSENT" and active["is_operator"]:
        fail("ERR_OPERATOR_CANNOT_NON_CONSENT")

    snapshot = active["working_interest_pct"]
    election = insert("elections", {
        "afe_id": afe["id"],
        "owner_id": owner["id"],
        "election_type": election_type,
        "election_status": "SUBMITTED",
        "wi_pct_snapshot": snapshot,
        "estimated_penalty_cents": penalty_amount(afe, election_type, snapshot),
        "submitted_at": now_ts(),
    })
    touch(afe)
    return ok(out_election(election), 201)


@bp.route("/afes/<afe_id>/election-closures", methods=["POST"])
def close_elections(afe_id):
    authenticate()
    authorize(ROLE_LAND)
    afe = get_afe(afe_id)
    well = db.wells.get(afe["well_id"])

    if afe["afe_status"] != "ELECTIONS_OPEN":
        fail("ERR_AFE_ELECTIONS_CLOSED")

    positions = well_interests(afe["well_id"], "ACTIVE")
    operator = operator_interest(afe["well_id"])
    operator_owner_id = operator["owner_id"] if operator is not None else None
    existing = afe_elections(afe["id"])
    submitted_by_owner = {}
    for row in existing:
        if row["election_status"] == "SUBMITTED":
            submitted_by_owner[row["owner_id"]] = row

    everyone_elected = True
    for position in positions:
        if position["is_operator"]:
            continue
        if position["owner_id"] not in submitted_by_owner:
            everyone_elected = False
            break
    if today() <= afe["election_deadline_date"] and not everyone_elected:
        fail("ERR_ELECTION_WINDOW_OPEN")

    consent = dec(operator["working_interest_pct"]) if operator is not None else dec(0)
    for row in existing:
        if row["election_status"] != "SUBMITTED" or row["election_type"] != "CONSENT":
            continue
        if operator_owner_id is not None and row["owner_id"] == operator_owner_id:
            continue
        consent += dec(row["wi_pct_snapshot"])
    consent = q6(consent)
    if consent == dec("0.000000"):
        fail("ERR_NO_CONSENTING_INTEREST")
    non_consent = q6(dec("1.000000") - consent)

    afe["consent_working_interest_pct"] = consent
    afe["non_consent_working_interest_pct"] = non_consent
    afe["elections_closed_at"] = now_ts()

    if consent == dec("1.000000"):
        afe["afe_status"] = "FULLY_CONSENTED"
        touch(afe)
        if well is not None and recompute_consent_wi(well):
            touch(well)
        return ok(out_afe(afe))

    if consent < afe["minimum_consent_pct"]:
        afe["afe_status"] = "FAILED"
        for row in existing:
            if row["election_status"] in ("SUBMITTED", "DEEMED_NON_CONSENT"):
                row["election_status"] = "VOIDED"
                row["estimated_penalty_cents"] = 0
                touch(row)
        touch(afe)
        return ok(out_afe(afe))

    # PARTIALLY_CONSENTED: four-hop cascade.
    afe["afe_status"] = "PARTIALLY_CONSENTED"
    touch(afe)

    elected_owners = set(row["owner_id"] for row in existing)
    non_consenting_owners = []
    for position in positions:
        if position["is_operator"]:
            continue
        if position["owner_id"] in elected_owners:
            continue
        snapshot = position["working_interest_pct"]
        insert("elections", {
            "afe_id": afe["id"],
            "owner_id": position["owner_id"],
            "election_type": "NON_CONSENT",
            "election_status": "DEEMED_NON_CONSENT",
            "wi_pct_snapshot": snapshot,
            "estimated_penalty_cents": penalty_amount(afe, "NON_CONSENT", snapshot),
            "submitted_at": now_ts(),
        })
        non_consenting_owners.append(position["owner_id"])
    for row in existing:
        if row["election_status"] == "SUBMITTED" and row["election_type"] == "NON_CONSENT":
            if row["owner_id"] not in non_consenting_owners:
                non_consenting_owners.append(row["owner_id"])

    for owner_id in non_consenting_owners:
        position = active_position(afe["well_id"], owner_id)
        if position is not None and not position["non_consent_flag"]:
            position["non_consent_flag"] = True
            touch(position)

    if well is not None:
        recompute_consent_wi(well)
        touch(well)

    affected = []
    for owner_id in non_consenting_owners:
        for disb in owner_disbursements(owner_id):
            revenue = db.revenues.get(disb["revenue_id"])
            if revenue is None or revenue["well_id"] != afe["well_id"]:
                continue
            if disb["disbursement_status"] != "ACCRUED":
                continue
            disb["disbursement_status"] = "SUSPENDED"
            disb["suspense_reason"] = "NON_CONSENT_RECOVERY"
            touch(disb)
            if owner_id not in affected:
                affected.append(owner_id)
    for owner_id in affected:
        owner = db.owners.get(owner_id)
        if owner is not None:
            recompute_suspense_balance(owner)

    return ok(out_afe(afe))
