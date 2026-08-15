"""Revenue reports, royalty runs, and royalty statements."""

from flask import Blueprint

from db import db, new_id, now_iso
from errors import raise_err
from helpers import (
    get_body, make_entity, touch, serialize, get_or_404, list_page,
    apply_filters, v_str, v_int, v_enum, v_period,
)
from middleware import auth, check_ownership
from response import ok, ok_list
from services.calc import (
    compute_statement_lines, compute_net_payable, waterfall_total, waterfall_apply,
    recompute_account_totals,
)
from services.domain import account_of_contract, artist_of_contract

bp = Blueprint("royalties", __name__)

REVENUE_CHANNELS = ["STREAMING", "DOWNLOAD", "PHYSICAL", "SYNC"]
LIVE_RELEASE_STATES = ("DELIVERED", "LIVE", "TAKEN_DOWN")
RUN_CONTRACT_STATES = ("ACTIVE", "OPTION_WINDOW", "EXTENDED")


# ---------------------------------------------------------------------------
# Revenue reports (append-only: id + created_at, no updated_at/version)
# ---------------------------------------------------------------------------

@bp.post("/api/revenue-reports")
def create_revenue_report():
    auth(["FinanceController"])
    body = get_body()
    label_id = v_str(body, "label_id")
    distributor_id = v_str(body, "distributor_id")
    release_id = v_str(body, "release_id")
    period = v_period(body, "period")
    channel = v_enum(body, "channel", REVENUE_CHANNELS)
    units = v_int(body, "units", min_v=1)
    gross = v_int(body, "gross_revenue_cents", min_v=1)
    note = v_str(body, "note", required=False, allow_null=True)

    if label_id not in db.labels:
        raise_err("ERR_NOT_FOUND", "label_id does not reference an existing label")
    distributor = db.distributors.get(distributor_id)
    if distributor is None or distributor["label_id"] != label_id:
        raise_err("ERR_NOT_FOUND", "distributor_id does not reference a distributor of this label")
    release = db.releases.get(release_id)
    if release is None:
        raise_err("ERR_NOT_FOUND", "release_id does not reference an existing release")
    contract = db.contracts.get(release["contract_id"])
    artist = artist_of_contract(contract) if contract else None
    if artist is None or artist["label_id"] != label_id:
        raise_err("ERR_NOT_FOUND", "release_id references a release of another label")

    for rep in db.revenue_reports.values():
        if (rep["label_id"] == label_id and rep["distributor_id"] == distributor_id
                and rep["release_id"] == release_id and rep["period"] == period
                and rep["channel"] == channel):
            raise_err("ERR_DUPLICATE_REVENUE_REPORT",
                      "A report already exists for this (label, distributor, release, period, channel)")
    if release["distribution_status"] not in LIVE_RELEASE_STATES:
        raise_err("ERR_RELEASE_NOT_LIVE",
                  "Release distribution_status must be DELIVERED, LIVE, or TAKEN_DOWN")

    report = {
        "id": new_id(),
        "label_id": label_id,
        "distributor_id": distributor_id,
        "release_id": release_id,
        "period": period,
        "channel": channel,
        "units": units,
        "gross_revenue_cents": gross,
        "note": note,
        "created_at": now_iso(),
        "_seq": db.next_seq(),
        "_counted": False,
    }
    db.revenue_reports[report["id"]] = report
    return ok(serialize(report), code=201)


@bp.get("/api/revenue-reports/<rid>")
def get_revenue_report(rid):
    auth(["LabelAdmin", "AnRManager", "FinanceController"])
    report = get_or_404(db.revenue_reports, rid)
    return ok(serialize(report))


@bp.get("/api/revenue-reports")
def list_revenue_reports():
    auth(["LabelAdmin", "AnRManager", "FinanceController"])
    items = apply_filters(db.revenue_reports.values(), [
        ("label_id", lambda r: r["label_id"]),
        ("distributor_id", lambda r: r["distributor_id"]),
        ("release_id", lambda r: r["release_id"]),
        ("period", lambda r: r["period"]),
        ("channel", lambda r: r["channel"]),
    ])
    data, pagination = list_page(items)
    return ok_list(data, pagination)


# ---------------------------------------------------------------------------
# Royalty runs
# ---------------------------------------------------------------------------

@bp.post("/api/royalty-runs")
def create_run():
    auth(["FinanceController"])
    body = get_body()
    label_id = v_str(body, "label_id")
    period = v_period(body, "period")
    if label_id not in db.labels:
        raise_err("ERR_NOT_FOUND", "label_id does not reference an existing label")
    for run in db.royalty_runs.values():
        if run["label_id"] == label_id and run["period"] == period:
            raise_err("ERR_RUN_PERIOD_CONFLICT", "A royalty run already exists for this label and period")
    run = make_entity({
        "label_id": label_id,
        "period": period,
        "status": "OPEN",
    })
    db.royalty_runs[run["id"]] = run
    return ok(serialize(run), code=201)


@bp.get("/api/royalty-runs/<rid>")
def get_run(rid):
    auth(["LabelAdmin", "FinanceController"])
    run = get_or_404(db.royalty_runs, rid)
    return ok(serialize(run))


@bp.get("/api/royalty-runs")
def list_runs():
    auth(["LabelAdmin", "FinanceController"])
    items = apply_filters(db.royalty_runs.values(), [
        ("label_id", lambda r: r["label_id"]),
        ("status", lambda r: r["status"]),
    ])
    data, pagination = list_page(items)
    return ok_list(data, pagination)


@bp.post("/api/royalty-runs/<rid>/close")
def close_run(rid):
    auth(["FinanceController"])
    run = get_or_404(db.royalty_runs, rid)
    get_body()
    if run["status"] != "OPEN":
        raise_err("ERR_INVALID_STATE", "Only an OPEN run may be closed")
    run["status"] = "CLOSED"
    touch(run)
    return ok(serialize(run))


@bp.post("/api/royalty-runs/<rid>/calculate")
def calculate_run(rid):
    auth(["FinanceController"])
    run = get_or_404(db.royalty_runs, rid)
    get_body()
    if run["status"] != "CLOSED":
        raise_err("ERR_INVALID_STATE", "Only a CLOSED run may be calculated")
    label = db.labels.get(run["label_id"])
    label_artist_ids = {a["id"] for a in db.artists.values() if a["label_id"] == run["label_id"]}
    contracts = [
        c for c in sorted(db.contracts.values(), key=lambda c: c["_seq"])
        if c["artist_id"] in label_artist_ids and c["status"] in RUN_CONTRACT_STATES
    ]
    for contract in contracts:
        result = compute_statement_lines(contract, run)
        if result is None:
            continue
        account = account_of_contract(contract["id"])
        projected = waterfall_total(account, contract["recoupment_scope"], result["earned"]) if account else 0
        statement = make_entity({
            "run_id": run["id"],
            "contract_id": contract["id"],
            "period": run["period"],
            "gross_revenue_cents": result["gross"],
            "net_revenue_cents": result["net"],
            "royalty_earned_cents": result["earned"],
            "projected_recoupment_cents": projected,
            "recoupment_applied_cents": 0,
            "reserve_held_cents": 0,
            "adjustment_cents": 0,
            "net_payable_cents": 0,
            "dispute_note": None,
            "status": "PROVISIONAL",
        })
        compute_net_payable(statement, label["reserve_rate_bps"])
        db.royalty_statements[statement["id"]] = statement
        for report_id in result["counted_report_ids"]:
            db.revenue_reports[report_id]["_counted"] = True
    run["status"] = "CALCULATED"
    touch(run)
    return ok(serialize(run))


@bp.post("/api/royalty-runs/<rid>/finalize")
def finalize_run(rid):
    auth(["FinanceController"])
    run = get_or_404(db.royalty_runs, rid)
    get_body()
    if run["status"] != "CALCULATED":
        raise_err("ERR_INVALID_STATE", "Only a CALCULATED run may be finalized")
    label = db.labels.get(run["label_id"])
    statements = [
        s for s in sorted(db.royalty_statements.values(), key=lambda s: s["_seq"])
        if s["run_id"] == rid and s["status"] == "PROVISIONAL"
    ]
    for statement in statements:
        contract = db.contracts.get(statement["contract_id"])
        account = account_of_contract(contract["id"])
        applied = waterfall_apply(
            account, contract["recoupment_scope"], statement["royalty_earned_cents"]
        )
        account["total_recouped_cents"] += applied
        if account["total_unrecouped_cents"] == 0 and account["payout_status"] == "RECOUPING":
            account["payout_status"] = "EARNING"
        touch(account)
        statement["recoupment_applied_cents"] = applied
        statement["status"] = "FINAL"
        compute_net_payable(statement, label["reserve_rate_bps"])
        touch(statement)
    run["status"] = "FINALIZED"
    touch(run)
    return ok(serialize(run))


@bp.post("/api/royalty-runs/<rid>/mark-paid")
def mark_paid_run(rid):
    auth(["FinanceController"])
    run = get_or_404(db.royalty_runs, rid)
    get_body()
    if run["status"] != "FINALIZED":
        raise_err("ERR_INVALID_STATE", "Only a FINALIZED run may be marked paid")
    for statement in db.royalty_statements.values():
        if statement["run_id"] == rid and statement["status"] != "PAID":
            raise_err("ERR_RUN_HAS_UNPAID_STATEMENTS", "Every statement of the run must be PAID")
    run["status"] = "PAID"
    touch(run)
    return ok(serialize(run))


@bp.get("/api/royalty-runs/<rid>/statements")
def list_run_statements(rid):
    auth(["LabelAdmin", "FinanceController"])
    get_or_404(db.royalty_runs, rid)
    items = [s for s in db.royalty_statements.values() if s["run_id"] == rid]
    items = apply_filters(items, [("status", lambda s: s["status"])])
    data, pagination = list_page(items)
    return ok_list(data, pagination)


# ---------------------------------------------------------------------------
# Royalty statements
# ---------------------------------------------------------------------------

def _statement_artist(statement):
    contract = db.contracts.get(statement["contract_id"])
    return artist_of_contract(contract) if contract else None


@bp.get("/api/royalty-statements/<sid>")
def get_statement(sid):
    uid, role = auth(["LabelAdmin", "FinanceController", "ArtistPortal"])
    statement = get_or_404(db.royalty_statements, sid)
    artist = _statement_artist(statement)
    check_ownership(role, uid, artist["id"] if artist else None)
    return ok(serialize(statement))


@bp.get("/api/royalty-statements")
def list_statements():
    uid, role = auth(["LabelAdmin", "FinanceController", "ArtistPortal"])
    items = list(db.royalty_statements.values())
    if role == "ArtistPortal":
        # Artist portal reads only its own statements.
        items = [s for s in items
                 if (_statement_artist(s) is not None and _statement_artist(s)["id"] == uid)]
    def _artist_id(s):
        artist = _statement_artist(s)
        return artist["id"] if artist else ""
    items = apply_filters(items, [
        ("run_id", lambda s: s["run_id"]),
        ("contract_id", lambda s: s["contract_id"]),
        ("artist_id", _artist_id),
        ("status", lambda s: s["status"]),
    ])
    data, pagination = list_page(items)
    return ok_list(data, pagination)


@bp.post("/api/royalty-statements/<sid>/dispute")
def dispute_statement(sid):
    uid, role = auth(["ArtistPortal"])
    statement = get_or_404(db.royalty_statements, sid)
    artist = _statement_artist(statement)
    check_ownership(role, uid, artist["id"] if artist else None)
    body = get_body()
    dispute_note = v_str(body, "dispute_note")
    if statement["status"] != "FINAL":
        raise_err("ERR_INVALID_STATE", "Only a FINAL statement may be disputed")
    statement["status"] = "DISPUTED"
    statement["dispute_note"] = dispute_note
    touch(statement)
    return ok(serialize(statement))


@bp.post("/api/royalty-statements/<sid>/adjust")
def adjust_statement(sid):
    auth(["FinanceController"])
    statement = get_or_404(db.royalty_statements, sid)
    body = get_body()
    expected = v_int(body, "expected_royalty_statement_version")
    delta = v_int(body, "adjustment_delta_cents")
    if expected != statement["version"]:
        raise_err("ERR_STALE_VERSION", "Royalty statement version mismatch")
    if statement["status"] not in ("PROVISIONAL", "DISPUTED"):
        raise_err("ERR_INVALID_STATE", "Statement in %s cannot be adjusted" % statement["status"])
    run = db.royalty_runs.get(statement["run_id"])
    label = db.labels.get(run["label_id"]) if run else None
    statement["adjustment_cents"] += delta
    compute_net_payable(statement, label["reserve_rate_bps"] if label else 0)
    touch(statement)
    return ok(serialize(statement))


@bp.post("/api/royalty-statements/<sid>/resolve-dispute")
def resolve_dispute(sid):
    auth(["FinanceController"])
    statement = get_or_404(db.royalty_statements, sid)
    get_body()
    if statement["status"] != "DISPUTED":
        raise_err("ERR_INVALID_STATE", "Only a DISPUTED statement may be resolved")
    statement["status"] = "FINAL"
    touch(statement)
    return ok(serialize(statement))


@bp.post("/api/royalty-statements/<sid>/pay")
def pay_statement(sid):
    auth(["FinanceController"])
    statement = get_or_404(db.royalty_statements, sid)
    get_body()
    if statement["status"] != "FINAL":
        raise_err("ERR_INVALID_STATE", "Only a FINAL statement may be paid")
    run = db.royalty_runs.get(statement["run_id"])
    if run is None or run["status"] != "FINALIZED":
        raise_err("ERR_INVALID_STATE", "The statement's run must be FINALIZED")
    if statement["net_payable_cents"] < 0:
        raise_err("ERR_NEGATIVE_PAYABLE", "net_payable_cents is negative")
    statement["status"] = "PAID"
    touch(statement)
    return ok(serialize(statement))
