"""Capacity tests and the degradation model (PRD 3.9)."""

from flask import Blueprint

import db
import errors
import middleware
import response
import validators as v
from errors import ApiError
from numeric import D, r3
from services import calc, core

bp = Blueprint("captests", __name__)

STATUSES = ("SCHEDULED", "IN_PROGRESS", "COMPLETED")
REMEDY_OUTAGE_BUFFER_DAYS = 2


def _outage_conflict(asset_id, scheduled_date):
    """The closed inclusive augmentation outage window of every APPROVED or
    REMEDIED claim, extended by the trailing buffer."""
    for claim in core.claims_of(asset_id):
        if claim["status"] not in ("APPROVED", "REMEDIED"):
            continue
        if claim["remedy_install_date"] is None or claim["remedy_outage_days"] is None:
            continue
        start = db.parse_dt(claim["remedy_install_date"])
        if start is None:
            continue
        end = db.add_days(start, float(claim["remedy_outage_days"])
                          + REMEDY_OUTAGE_BUFFER_DAYS)
        if start <= scheduled_date <= end:
            return True
    return False


@bp.post("/capacity-tests")
def schedule_test():
    middleware.authorize("AssetManager")
    body = v.json_body()

    asset_id = v.ident(body, "asset_id")
    scheduled_raw, scheduled = v.timestamp(body, "scheduled_date")
    baseline_id = v.ident(body, "baseline_test_id", required=False, default=None)

    asset = core.get_asset(asset_id)
    baseline = None
    if baseline_id is not None:
        baseline = core.get_test(baseline_id)
        if baseline["asset_id"] != asset_id:
            raise ApiError(errors.ERR_ASSET_SCOPE_MISMATCH, 409,
                           "The baseline test belongs to a different asset.")

    core.gate_lockout(asset)

    if baseline is not None:
        baseline_date = db.parse_dt(baseline["scheduled_date"])
        if baseline["status"] != "COMPLETED" or not baseline_date < scheduled:
            raise ApiError(errors.ERR_BASELINE_TEST_INVALID, 422,
                           "The baseline test reference is not valid.")

    if _outage_conflict(asset_id, scheduled):
        raise ApiError(errors.ERR_REMEDY_OUTAGE_CONFLICT, 409,
                       "The test falls inside an augmentation outage window.")

    test = db.new_row()
    test.update({
        "asset_id": asset_id,
        "baseline_test_id": baseline_id,
        "scheduled_date": scheduled_raw,
        "status": "SCHEDULED",
        "measured_capacity_mwh": None,
        "measured_soh_pct": None,
        "expected_soh_pct": None,
        "soh_deficit_pct": None,
        "warranty_claim_triggered": False,
        "test_energy_throughput_mwh": 0.0,
    })
    db.capacity_tests[test["id"]] = test
    return response.created(db.serialize(test))


@bp.get("/capacity-tests/<test_id>")
def read_test(test_id):
    middleware.any_role()
    return response.ok(db.serialize(core.get_test(test_id)))


@bp.get("/capacity-tests")
def list_tests():
    middleware.any_role()
    limit, offset = v.pagination()
    asset_id = v.query_str("asset_id")
    baseline_test_id = v.query_str("baseline_test_id")
    status = v.query_enum("status", STATUSES)

    rows = list(db.capacity_tests.values())
    if asset_id is not None:
        rows = [r for r in rows if r["asset_id"] == asset_id]
    if baseline_test_id is not None:
        rows = [r for r in rows if r["baseline_test_id"] == baseline_test_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    rows = core.newest_first(rows)
    page, total = core.paginate(rows, limit, offset)
    return response.ok_list([db.serialize(r) for r in page], limit, offset, total)


@bp.post("/capacity-tests/<test_id>/start")
def start_test(test_id):
    user_id, role = middleware.authorize("SiteController")
    test = core.get_test(test_id)
    middleware.check_asset_ownership(user_id, role, test["asset_id"])
    asset = core.get_asset(test["asset_id"])

    if test["status"] != "SCHEDULED":
        raise ApiError(errors.ERR_TEST_NOT_SCHEDULED, 409,
                       "The test is not SCHEDULED.")
    running = [t for t in core.tests_of(test["asset_id"])
               if t["status"] == "IN_PROGRESS"]
    if running:
        raise ApiError(errors.ERR_TEST_NOT_SCHEDULED, 409,
                       "Another capacity test of this asset is already running.")
    core.gate_lockout(asset)

    if _outage_conflict(test["asset_id"], db.parse_dt(test["scheduled_date"])):
        raise ApiError(errors.ERR_REMEDY_OUTAGE_CONFLICT, 409,
                       "The test falls inside an augmentation outage window.")

    test["status"] = "IN_PROGRESS"
    db.touch(test)
    return response.ok(db.serialize(test))


@bp.post("/capacity-tests/<test_id>/complete")
def complete_test(test_id):
    user_id, role = middleware.authorize("SiteController")
    body = v.json_body()
    measured_capacity = v.num(body, "measured_capacity_mwh", gt=0)

    test = core.get_test(test_id)
    middleware.check_asset_ownership(user_id, role, test["asset_id"])
    asset = core.get_asset(test["asset_id"])

    if test["status"] != "IN_PROGRESS":
        raise ApiError(errors.ERR_TEST_NOT_IN_PROGRESS, 409,
                       "The test is not IN_PROGRESS.")
    core.gate_lockout(asset)

    # the pinned evaluation order of the degradation model
    throughput_before = asset["cumulative_throughput_mwh"]
    rated = core.rated_energy(asset)                                  # step 1
    years = calc.elapsed_years(db.parse_dt(asset["commercial_operation_date"]),
                               db.parse_dt(test["scheduled_date"]))
    expected = calc.expected_soh(asset, years, throughput_before)     # step 2
    measured = calc.measured_soh(measured_capacity, rated)            # step 3
    deficit = calc.soh_deficit(expected, measured)                    # step 4
    credit = r3(measured_capacity)                                    # step 7

    # cascade link one — the test's own figures, in the pinned order
    test["status"] = "COMPLETED"
    test["measured_capacity_mwh"] = measured_capacity
    test["expected_soh_pct"] = expected
    test["measured_soh_pct"] = measured
    test["soh_deficit_pct"] = deficit
    test["warranty_claim_triggered"] = calc.claim_triggered(deficit)
    test["test_energy_throughput_mwh"] = credit
    db.touch(test)

    # cascade link two — the asset's state of health and throughput ledger
    asset["soh_pct"] = measured
    asset["cumulative_throughput_mwh"] = r3(D(throughput_before) + D(credit))
    core.recompute_rated(asset)
    core.recompute_available(asset)
    core.recompute_efc(asset)

    core.rederate_obligations(asset)   # cascade link three
    core.reprice_draft_bids(asset)     # cascade link four

    core.recompute_free(asset)         # recomputed last of all
    db.touch(asset)
    return response.ok(db.serialize(test))
