"""Settlement cycles, cutoff fee assessment, reconciliation runs and closure."""

from flask import Blueprint

from db import bump, db, new_record, now, order_key
from errors import ApiError
from middleware import authorize, require_scope, scope_filter_value
from response import created, list_response, object_response
from routes.helpers import query_value
from timeutils import date_str, parse_business_date, utc_date
from validation import payload, req_enum, req_id, req_int, req_string
from services import fees, lookup, reconciliation, serializers
from services.constants import RECON_VARIANTS, VARIANCE_TOLERANCE_CENTS

bp = Blueprint("settlement", __name__)


@bp.route("/settlement-cycles", methods=["POST"])
def open_cycle():
    authorize(["NetworkOperator"])
    body = payload()
    business_date = parse_business_date(req_string(body, "business_date"))
    if business_date > utc_date(now()):
        raise ApiError(
            "ERR_BUSINESS_DATE_NOT_REACHED",
            "A settlement cycle cannot be opened for a future business date.",
        )
    text = business_date.isoformat()
    if lookup.cycle_for_business_date(text) is not None:
        raise ApiError(
            "ERR_DUPLICATE_SETTLEMENT_CYCLE",
            "A settlement cycle already exists for that business date.",
        )
    cycle = new_record()
    cycle.update({
        "business_date": text,
        "status": "OPEN",
        "cutoff_at": None,
        "assessed_fee_total_cents": 0,
        "closed_at": None,
    })
    db.settlement_cycles[cycle["id"]] = cycle
    return created(serializers.settlement_cycle(cycle))


@bp.route("/settlement-cycles/<cycle_id>", methods=["GET"])
def get_cycle(cycle_id):
    authorize(["NetworkOperator", "LiquidityOfficer", "CoreBankingSystem", "ParticipantAdmin"])
    cycle = lookup.settlement_cycle(cycle_id)
    return object_response(serializers.settlement_cycle(cycle))


@bp.route("/settlement-cycles/<cycle_id>/cutoff", methods=["POST"])
def cut_off_cycle(cycle_id):
    authorize(["NetworkOperator"])
    cycle = lookup.settlement_cycle(cycle_id)
    if cycle["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", "Only an OPEN cycle may be cut off.")
    for transfer in db.credit_transfers.values():
        if transfer["clearing_status"] != "ACCEPTED":
            continue
        if transfer["accepted_at"] is None:
            continue
        if date_str(transfer["accepted_at"]) == cycle["business_date"]:
            raise ApiError(
                "ERR_INVALID_STATE_TRANSITION",
                "Accepted-but-unsettled traffic remains for that business date.",
            )
    if utc_date(now()) < parse_business_date(cycle["business_date"]):
        raise ApiError(
            "ERR_BUSINESS_DATE_NOT_REACHED",
            "The cycle's business date has not been reached.",
        )
    cycle["cutoff_at"] = now()
    cycle["status"] = "CUTOFF"
    cycle["assessed_fee_total_cents"] = fees.assess_cycle(cycle)
    bump(cycle)
    return object_response(serializers.settlement_cycle(cycle))


@bp.route("/settlement-cycles/<cycle_id>/reconciliation-closure", methods=["POST"])
def close_cycle(cycle_id):
    authorize(["NetworkOperator"])
    cycle = lookup.settlement_cycle(cycle_id)
    if cycle["status"] != "RECONCILING":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", "Only a RECONCILING cycle may be closed.")
    if not reconciliation.all_live_balanced(cycle["id"]):
        raise ApiError(
            "ERR_VARIANCE_UNRESOLVED",
            "Every LIVE participant needs a balanced highest-revision FINAL run.",
        )
    cycle["closed_at"] = now()
    cycle["status"] = "RECONCILED"
    bump(cycle)
    return object_response(serializers.settlement_cycle(cycle))


@bp.route("/reconciliation-runs", methods=["POST"])
def submit_run():
    authorize(["CoreBankingSystem"])
    body = payload()

    raw_participant = body.get("participant_id")
    participant = None
    if isinstance(raw_participant, str) and raw_participant.strip():
        participant = lookup.participant(raw_participant)
    raw_cycle = body.get("settlement_cycle_id")
    cycle = None
    if isinstance(raw_cycle, str) and raw_cycle.strip():
        cycle = lookup.settlement_cycle(raw_cycle)

    cycle_id = req_id(body, "settlement_cycle_id")
    participant_id = req_id(body, "participant_id")
    variant = req_enum(body, "variant", RECON_VARIANTS)
    core_total = req_int(body, "core_deposit_total_cents")
    assert cycle_id and participant_id

    allowed = ("OPEN", "CUTOFF", "RECONCILING", "OUT_OF_BALANCE")
    if variant == "FINAL":
        allowed = ("CUTOFF", "RECONCILING", "OUT_OF_BALANCE")
    if cycle["status"] not in allowed:
        raise ApiError(
            "ERR_CYCLE_NOT_RECONCILABLE",
            "The cycle status does not admit a %s reconciliation run." % variant,
        )

    account = lookup.account_of_participant(participant_id)
    if account is None:
        raise ApiError(
            "ERR_POSITION_ACCOUNT_NOT_FOUND",
            "The participant has no prefunded position account.",
        )

    figures = reconciliation.compute(participant, cycle, variant, core_total, account)
    run = new_record()
    run.update({
        "settlement_cycle_id": cycle_id,
        "participant_id": participant_id,
        "variant": variant,
        "revision": reconciliation.next_revision(cycle_id, participant_id, variant),
        "core_deposit_total_cents": core_total,
    })
    run.update(figures)
    db.reconciliation_runs[run["id"]] = run

    if variant == "FINAL":
        status = cycle["status"]
        if status == "CUTOFF":
            if reconciliation.any_live_out_of_balance(cycle["id"]):
                cycle["status"] = "OUT_OF_BALANCE"
            else:
                cycle["status"] = "RECONCILING"
            bump(cycle)
        elif status == "RECONCILING":
            if abs(run["variance_cents"]) > VARIANCE_TOLERANCE_CENTS:
                cycle["status"] = "OUT_OF_BALANCE"
                bump(cycle)
        elif status == "OUT_OF_BALANCE":
            if not reconciliation.any_live_out_of_balance(cycle["id"]):
                cycle["status"] = "RECONCILING"
                bump(cycle)
    return created(serializers.reconciliation_run(run))


@bp.route("/reconciliation-runs/<run_id>", methods=["GET"])
def get_run(run_id):
    user_id, role = authorize(
        ["NetworkOperator", "CoreBankingSystem", "LiquidityOfficer", "ParticipantAdmin"]
    )
    run = lookup.reconciliation_run(run_id)
    require_scope(user_id, role, run["participant_id"])
    return object_response(serializers.reconciliation_run(run))


@bp.route("/reconciliation-runs", methods=["GET"])
def list_runs():
    user_id, role = authorize(
        ["NetworkOperator", "CoreBankingSystem", "LiquidityOfficer", "ParticipantAdmin"]
    )
    participant_id = scope_filter_value(user_id, role, query_value("participant_id"))
    cycle_id = query_value("settlement_cycle_id")
    variant = query_value("variant")
    outcome = query_value("outcome")
    rows = []
    for row in db.reconciliation_runs.values():
        if participant_id is not None and row["participant_id"] != participant_id:
            continue
        if cycle_id is not None and row["settlement_cycle_id"] != cycle_id:
            continue
        if variant is not None and row["variant"] != variant:
            continue
        if outcome is not None and row["outcome"] != outcome:
            continue
        rows.append(row)
    rows.sort(key=order_key)
    return list_response(rows, serializers.reconciliation_run)
