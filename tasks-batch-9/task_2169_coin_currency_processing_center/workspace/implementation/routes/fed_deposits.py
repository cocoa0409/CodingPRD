"""FedDeposit (Federal Reserve cash letter) routes."""

from flask import Blueprint

from core import (
    FED_STATUSES,
    LOT_STATUSES,
    ROLE_FED_AGENT,
    ROLE_VAULT_MANAGER,
    authorize,
    body_json,
    clock_now,
    db,
    fail,
    fmt_dt,
    get_fed_deposit,
    get_lot,
    get_pagination,
    get_vault,
    make_row,
    ordered,
    paginate,
    query_enum,
    query_str,
    req_date,
    req_int,
    req_list,
    req_str,
    respond,
    touch,
)
from serializers import fed_deposit_out, lot_out

bp = Blueprint("fed_deposits", __name__)


@bp.post("/fed-deposits")
def create_fed_deposit():
    authorize(ROLE_VAULT_MANAGER)
    body = body_json()
    vault_id = req_str(body, "vault_id")
    cash_letter_number = req_str(body, "cash_letter_number")
    deposit_date = req_date(body, "deposit_date")
    lot_ids = req_list(body, "fitness_lot_ids", allow_empty=True)
    for index, value in enumerate(lot_ids):
        if not isinstance(value, str) or not value.strip():
            fail("ERR_INVALID_REQUEST", "fitness_lot_ids[%d] must be a string id." % index)

    # ladder 6 - body references in declared field order
    get_vault(vault_id)
    seen = []
    lots = []
    for lot_id in lot_ids:
        lot = get_lot(lot_id)
        if lot_id not in seen:
            seen.append(lot_id)
            lots.append(lot)

    # ladder 21 - eligibility, lot by lot
    for lot in lots:
        if lot["category"] not in ("FIT", "UNFIT") or lot["status"] != "PENDING_DEPOSIT":
            fail("ERR_LOT_NOT_ELIGIBLE", "Lot %s is not eligible for a cash letter." % lot["id"])

    # ladder 22 - the lot must have been counted on this vault's own floor
    for lot in lots:
        session = db.sessions.get(lot["count_session_id"])
        machine = db.machines.get(session["counting_machine_id"]) if session else None
        if machine is None or machine["vault_id"] != vault_id:
            fail("ERR_LOT_VAULT_MISMATCH", "Lot %s was counted at another vault." % lot["id"])

    # ladder 30 - duplicate business identifier
    for existing in db.fed_deposits.values():
        if existing["cash_letter_number"] == cash_letter_number:
            fail(
                "ERR_DUPLICATE_IDENTIFIER",
                "cash_letter_number '%s' already exists." % cash_letter_number,
            )

    # ladder 32 - an empty lot list is a business outcome, not a shape error
    if not lots:
        fail("ERR_NO_ELIGIBLE_LOTS", "No eligible fitness lots were named.")

    row = make_row()
    row.update({
        "vault_id": vault_id,
        "cash_letter_number": cash_letter_number,
        "deposit_date": deposit_date,
        "status": "PREPARED",
        "declared_total_cents": sum(l["face_value_cents"] for l in lots),
        "credited_total_cents": 0,
        "adjustment_cents": 0,
        "attached_lot_count": len(lots),
        "submitted_at": None,
        "confirmed_at": None,
    })
    db.fed_deposits[row["id"]] = row

    for lot in lots:
        lot["fed_deposit_id"] = row["id"]
        lot["status"] = "ATTACHED"
        touch(lot)

    return respond(fed_deposit_out(row), 201)


@bp.get("/fed-deposits/<fed_id>")
def read_fed_deposit(fed_id):
    authorize(ROLE_VAULT_MANAGER, ROLE_FED_AGENT)
    return respond(fed_deposit_out(get_fed_deposit(fed_id)))


@bp.get("/fed-deposits")
def list_fed_deposits():
    authorize(ROLE_VAULT_MANAGER, ROLE_FED_AGENT)
    limit, offset = get_pagination()
    vault_id = query_str("vault_id")
    status = query_enum("status", FED_STATUSES)

    rows = ordered(db.fed_deposits.values())
    if vault_id is not None:
        rows = [r for r in rows if r["vault_id"] == vault_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return paginate(rows, limit, offset, fed_deposit_out)


def _attached_lots(fed_id):
    return ordered([l for l in db.lots.values() if l["fed_deposit_id"] == fed_id])


@bp.post("/fed-deposits/<fed_id>/submit")
def submit_fed_deposit(fed_id):
    authorize(ROLE_VAULT_MANAGER)
    deposit = get_fed_deposit(fed_id)

    if deposit["status"] != "PREPARED":
        fail("ERR_INVALID_STATE", "Cash letter is not in PREPARED.")

    # ladder 13 - the shipping vault must not be frozen
    vault = db.vaults.get(deposit["vault_id"])
    if vault is not None and vault["posture"] == "FROZEN":
        fail("ERR_VAULT_FROZEN", "The shipping vault is FROZEN.")

    # ladder 18 - no DRAFT counterfeit report on a lot sharing a counting session
    lots = _attached_lots(fed_id)
    session_ids = {l["count_session_id"] for l in lots}
    for report in db.reports.values():
        if report["status"] != "DRAFT":
            continue
        lot = db.lots.get(report["fitness_lot_id"])
        if lot is not None and lot["count_session_id"] in session_ids:
            fail(
                "ERR_COUNTERFEIT_REPORT_PENDING",
                "A DRAFT counterfeit report is still open on this shipment's counting session.",
            )

    deposit["status"] = "SUBMITTED"
    deposit["submitted_at"] = fmt_dt(clock_now())
    touch(deposit)

    for lot in lots:
        if lot["status"] == "ATTACHED":
            lot["status"] = "DEPOSITED"
            touch(lot)
    return respond(fed_deposit_out(deposit))


@bp.post("/fed-deposits/<fed_id>/confirm")
def confirm_fed_deposit(fed_id):
    authorize(ROLE_FED_AGENT)
    body = body_json()
    credited_total_cents = req_int(body, "credited_total_cents")
    deposit = get_fed_deposit(fed_id)

    if deposit["status"] != "SUBMITTED":
        fail("ERR_INVALID_STATE", "Cash letter is not in SUBMITTED.")

    adjustment = credited_total_cents - deposit["declared_total_cents"]
    deposit["credited_total_cents"] = credited_total_cents
    deposit["adjustment_cents"] = adjustment
    deposit["confirmed_at"] = fmt_dt(clock_now())

    if adjustment == 0:
        deposit["status"] = "CONFIRMED"
    else:
        deposit["status"] = "CONFIRMED_WITH_ADJUSTMENT"
        vault = db.vaults.get(deposit["vault_id"])
        if vault is not None:
            vault["cash_letter_adjustment_cents"] += adjustment
            touch(vault)
    touch(deposit)
    return respond(fed_deposit_out(deposit))


@bp.get("/fed-deposits/<fed_id>/fitness-lots")
def list_fed_deposit_lots(fed_id):
    authorize(ROLE_VAULT_MANAGER, ROLE_FED_AGENT)
    limit, offset = get_pagination()
    status = query_enum("status", LOT_STATUSES)
    get_fed_deposit(fed_id)

    rows = _attached_lots(fed_id)
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return paginate(rows, limit, offset, lot_out)
