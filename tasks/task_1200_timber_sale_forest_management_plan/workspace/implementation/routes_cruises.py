"""Inventory cruises: tally -> reconcile -> certify lifecycle."""
import statistics
from decimal import Decimal

from flask import Blueprint

from core import (
    db, new_common, bump, pub, success, require_roles, get_body, check_known,
    f_str, f_date, f_array, f_int, bad_request, err, paginate, get_stand,
    get_cruise, is_int, is_num, D, rhu, rhu2, check_transition, now_iso,
)

bp = Blueprint("cruises", __name__)

READ_ROLES = ("PlatformAdmin", "Forester", "Landowner", "Buyer", "Contractor",
              "AgencyInspector")

PLOT_SIZE_ACRES = Decimal("0.2")
MIN_RECONCILED_PLOTS = 5
MAX_SAMPLING_ERROR_PCT = Decimal("10.00")

CRUISE_TERMINAL = {"CERTIFIED", "SUPERSEDED", "VOID"}


def _validate_plots(plots):
    for row in plots:
        if not isinstance(row, dict):
            bad_request("each plot row must be an object")
        check_known(row, {"plot_number", "species", "volume_bf"})
        if not is_int(row.get("plot_number")):
            bad_request("plot_number must be an integer")
        if not isinstance(row.get("species"), str):
            bad_request("species must be a string")
        if not is_num(row.get("volume_bf")):
            bad_request("volume_bf must be a number")


def _n_plots(plots):
    return len({r["plot_number"] for r in plots})


def _expansion_factor(stand, n_plots):
    if n_plots < 1:
        return None
    return D(stand["acres"]) / (PLOT_SIZE_ACRES * D(n_plots))


def _plot_totals(plots):
    totals = {}
    for r in plots:
        totals[r["plot_number"]] = totals.get(r["plot_number"], D(0)) + D(r["volume_bf"])
    return totals


def _provisional_volume(plots, ef):
    if ef is None:
        return 0
    total = sum((D(r["volume_bf"]) for r in plots), D(0))
    return rhu(total * ef)


def compute_cruise_derived(cruise):
    """(Re)compute n_plots, expansion_factor, provisional_volume_bf."""
    stand = db["stands"][cruise["stand_id"]]
    plots = cruise["plots"]
    n = _n_plots(plots)
    ef = _expansion_factor(stand, n)
    cruise["n_plots"] = n
    cruise["expansion_factor"] = float(ef) if ef is not None else None
    cruise["provisional_volume_bf"] = _provisional_volume(plots, ef)


def run_reconcile(cruise):
    """Compute certified volume model over reconciled plots."""
    stand = db["stands"][cruise["stand_id"]]
    plots = cruise["plots"]
    totals = _plot_totals(plots)
    rnums = cruise["reconciled_plot_numbers"]
    ef = _expansion_factor(stand, cruise["n_plots"])
    # provisional: all tallied rows, no sampling deduction
    compute_cruise_derived(cruise)
    # certified: reconciled plots only
    rec_totals = [totals[p] for p in rnums]
    n = len(rec_totals)
    mean = sum(rec_totals, D(0)) / D(n)
    if mean == 0:
        se = Decimal("0.00")
    else:
        pstdev = statistics.pstdev([float(x) for x in rec_totals])
        se_float = pstdev / float(mean) / (n ** 0.5) * 100.0
        se = Decimal(str(se_float)).quantize(Decimal("0.01"),
                                             rounding="ROUND_HALF_UP")
    base = sum(rec_totals, D(0)) * ef
    adj = Decimal("1") - se / Decimal("100")
    cruise["sampling_error_pct"] = float(se)
    cruise["certified_volume_bf"] = rhu(base * adj)
    by_species = {}
    for r in plots:
        if r["plot_number"] in set(rnums):
            by_species[r["species"]] = by_species.get(r["species"], D(0)) + D(r["volume_bf"])
    cruise["certified_volume_by_species"] = [
        {"species": s, "volume_bf": rhu(v * ef * adj)}
        for s, v in sorted(by_species.items())
    ]


@bp.route("/forestry/cruises", methods=["POST"])
@require_roles("Forester")
def create_cruise():
    body = get_body()
    st = body.get("stand_id")
    if isinstance(st, str):
        get_stand(st)
    check_known(body, {"stand_id", "cruise_date", "plots"})
    stand_id = f_str(body, "stand_id")
    get_stand(stand_id)
    cruise_date = f_date(body, "cruise_date")
    plots = f_array(body, "plots")
    _validate_plots(plots)
    ent = new_common({
        "stand_id": stand_id,
        "cruise_date": cruise_date,
        "plots": plots,
        "status": "DRAFT",
        "reconciled_plot_numbers": None,
        "certified_volume_bf": None,
        "certified_volume_by_species": None,
        "sampling_error_pct": None,
        "certified_at": None,
    })
    compute_cruise_derived(ent)
    db["cruises"][ent["id"]] = ent
    return success(pub(ent), 201)


@bp.route("/forestry/cruises/<cid>", methods=["GET"])
@require_roles(*READ_ROLES)
def get_cruise_ep(cid):
    return success(pub(get_cruise(cid)), 200)


@bp.route("/forestry/cruises", methods=["GET"])
@require_roles(*READ_ROLES)
def list_cruises():
    page, meta = paginate(db["cruises"].values(), {
        "stand_id": "stand_id",
        "status": "status",
    })
    return success([pub(c) for c in page], 200, is_array=True, page_meta=meta)


@bp.route("/forestry/cruises/<cid>/finalize-tally", methods=["POST"])
@require_roles("Forester")
def finalize_tally(cid):
    c = get_cruise(cid)
    body = get_body()
    check_known(body, set())
    check_transition(c, {"DRAFT"}, CRUISE_TERMINAL, "cruise")
    if c["n_plots"] < 1:
        err("ERR_INVALID_TRANSITION", 409, "cruise has no plots")
    c["status"] = "TALLIED"
    bump(c)
    return success(pub(c), 200)


@bp.route("/forestry/cruises/<cid>/reconcile", methods=["POST"])
@require_roles("Forester")
def reconcile(cid):
    c = get_cruise(cid)
    body = get_body()
    check_known(body, {"reconciled_plot_numbers"})
    rnums = f_array(body, "reconciled_plot_numbers")
    if not rnums:
        bad_request("reconciled_plot_numbers must be non-empty")
    tallied = {r["plot_number"] for r in c["plots"]}
    for p in rnums:
        if not is_int(p):
            bad_request("reconciled plot numbers must be integers")
        if p not in tallied:
            bad_request("reconciled plot %s is not in the tally" % p)
    check_transition(c, {"TALLIED"}, CRUISE_TERMINAL, "cruise")
    c["reconciled_plot_numbers"] = list(rnums)
    run_reconcile(c)
    c["status"] = "RECONCILED"
    bump(c)
    return success(pub(c), 200)


@bp.route("/forestry/cruises/<cid>/reopen", methods=["POST"])
@require_roles("Forester")
def reopen(cid):
    c = get_cruise(cid)
    body = get_body()
    check_known(body, set())
    check_transition(c, {"RECONCILED"}, CRUISE_TERMINAL, "cruise")
    c["reconciled_plot_numbers"] = None
    c["certified_volume_bf"] = None
    c["certified_volume_by_species"] = None
    c["sampling_error_pct"] = None
    c["status"] = "TALLIED"
    bump(c)
    return success(pub(c), 200)


@bp.route("/forestry/cruises/<cid>/certify", methods=["POST"])
@require_roles("Forester")
def certify(cid):
    c = get_cruise(cid)
    body = get_body()
    check_known(body, {"expected_stand_version"})
    expected = f_int(body, "expected_stand_version")
    check_transition(c, {"RECONCILED"}, CRUISE_TERMINAL, "cruise")
    # minimum reconciled plots before sampling-error check (PRD order)
    if len(c["reconciled_plot_numbers"]) < MIN_RECONCILED_PLOTS:
        err("ERR_MIN_PLOTS_NOT_MET", 422,
            "fewer than %d reconciled plots" % MIN_RECONCILED_PLOTS)
    if D(str(c["sampling_error_pct"])) > MAX_SAMPLING_ERROR_PCT:
        err("ERR_SAMPLING_ERROR_TOO_HIGH", 422,
            "sampling error exceeds 10.00 percent")
    stand = db["stands"][c["stand_id"]]
    if expected != stand["version"]:
        err("ERR_STALE_VERSION", 412,
            "expected_stand_version does not match stand version")
    prior_id = stand.get("certified_cruise_id")
    if prior_id and prior_id in db["cruises"]:
        prior = db["cruises"][prior_id]
        if prior["status"] == "CERTIFIED":
            prior["status"] = "SUPERSEDED"
    c["status"] = "CERTIFIED"
    c["certified_at"] = now_iso()
    bump(c)
    stand["certified_cruise_id"] = c["id"]
    bump(stand)
    return success(pub(c), 200)


@bp.route("/forestry/cruises/<cid>/void", methods=["POST"])
@require_roles("Forester")
def void_cruise(cid):
    c = get_cruise(cid)
    body = get_body()
    check_known(body, set())
    check_transition(c, {"DRAFT", "TALLIED"}, CRUISE_TERMINAL, "cruise")
    c["status"] = "VOID"
    bump(c)
    return success(pub(c), 200)
