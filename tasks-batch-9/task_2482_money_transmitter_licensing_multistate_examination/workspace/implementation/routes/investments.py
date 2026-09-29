"""Permissible investments, coverage testing and posture (§3.7)."""

from flask import Blueprint

import calculations as calc
from db import base_row, days, db, now, serialize, set_dt, set_input_dt, touch
from errors import ApiError
from middleware import authorize
from response import created, ok
from routes.common import filter_rows, get_holding, get_licensee, get_test, paginate
from services import engine
from validators import bad, get_body, pagination, q_enum, q_str, v_dt, v_enum, v_int, v_str

bp = Blueprint("investments", __name__)

TEST_STATUSES = ("DRAFT", "PREPARED", "CERTIFIED", "SUPERSEDED")


def _recompute_and_cascade(licensee, force_park=False):
    old_posture = engine.recompute_coverage(licensee)
    touch(licensee)
    engine.propagate_posture(licensee, old_posture, force_park=force_park)


@bp.post("/investment-holdings")
def create_holding():
    authorize("ComplianceOfficer", "ChiefComplianceOfficer")
    body = get_body()
    licensee_id = v_str(body, "licensee_id")
    asset_class = v_enum(body, "asset_class", calc.ASSET_CLASSES)
    counterparty = v_str(body, "counterparty_name")
    book_value = v_int(body, "book_value_cents", minimum=0)
    market_value = v_int(body, "market_value_cents", minimum=0)
    age_days = v_int(body, "age_days", required=False, minimum=0, default=0)

    licensee = get_licensee(licensee_id)

    row = base_row()
    row.update(
        {
            "licensee_id": licensee_id,
            "asset_class": asset_class,
            "counterparty_name": counterparty,
            "book_value_cents": book_value,
            "market_value_cents": market_value,
            "age_days": age_days,
            "status": "HELD",
        }
    )
    db.holdings[row["id"]] = row
    _recompute_and_cascade(licensee)
    return created(serialize(row))


@bp.post("/investment-holdings/<holding_id>/dispose")
def dispose_holding(holding_id):
    authorize("ComplianceOfficer", "ChiefComplianceOfficer")
    get_body()
    row = get_holding(holding_id)
    licensee = get_licensee(row["licensee_id"])
    row["status"] = "DISPOSED"
    touch(row)
    _recompute_and_cascade(licensee)
    return ok(serialize(row))


@bp.post("/permissible-investment-tests")
def create_test():
    authorize("ComplianceOfficer", "ChiefComplianceOfficer")
    body = get_body()
    licensee_id = v_str(body, "licensee_id")
    raw_start, start = v_dt(body, "coverage_period_start", required=True)
    raw_end, end = v_dt(body, "coverage_period_end", required=True)
    method = v_enum(body, "method", ("BOOK_VALUE", "ELIGIBLE_MARKET"))
    expected_version = v_int(body, "expected_licensee_version", minimum=0)
    if end <= start:
        bad("coverage_period_end must be strictly later than coverage_period_start")

    licensee = get_licensee(licensee_id)
    if expected_version != licensee["version"]:
        raise ApiError(
            "ERR_STALE_LICENSEE_VERSION",
            "Licensee %s is at version %d" % (licensee_id, licensee["version"]),
        )

    for existing in db.tests.values():
        if existing["licensee_id"] == licensee_id and existing["status"] in ("DRAFT", "PREPARED"):
            existing["status"] = "SUPERSEDED"
            touch(existing)

    row = base_row()
    row.update(
        {
            "licensee_id": licensee_id,
            "method": method,
            "status": "DRAFT",
            "prepared_by_user_id": None,
            "certified_by_user_id": None,
            "obligations_cents": 0,
            "investment_value_cents": 0,
            "coverage_ratio_bps": 0,
            "shortfall_cents": 0,
            "result": None,
            "certified_at": None,
        }
    )
    set_input_dt(row, "coverage_period_start", raw_start, start)
    set_input_dt(row, "coverage_period_end", raw_end, end)
    db.tests[row["id"]] = row
    touch(licensee)
    return created(serialize(row))


@bp.post("/permissible-investment-tests/<test_id>/prepare")
def prepare_test(test_id):
    user_id, _ = authorize("ComplianceOfficer", "ChiefComplianceOfficer")
    get_body()
    row = get_test(test_id)
    licensee = get_licensee(row["licensee_id"])

    if row["status"] != "DRAFT":
        raise ApiError(
            "ERR_TEST_INVALID_STATE", "Test %s is %s, not DRAFT" % (test_id, row["status"])
        )

    obligations = calc.licensee_obligation_aggregate(engine.licenses_of(licensee["id"]))
    holdings = engine.holdings_of(licensee["id"])
    value = calc.investment_value_for_method(holdings, obligations, row["method"])
    ratio = calc.ratio_bps(value, obligations)

    row["status"] = "PREPARED"
    row["obligations_cents"] = obligations
    row["investment_value_cents"] = value
    row["coverage_ratio_bps"] = ratio
    row["shortfall_cents"] = max(0, obligations - value)
    row["result"] = "PASS" if ratio >= calc.COVERAGE_PASS_BPS else "SHORTFALL"
    row["prepared_by_user_id"] = user_id
    touch(row)
    return ok(serialize(row))


@bp.post("/permissible-investment-tests/<test_id>/certify")
def certify_test(test_id):
    user_id, _ = authorize("ChiefComplianceOfficer")
    body = get_body()
    v_str(body, "attestation_note", required=False, allow_empty=True, default=None)

    row = get_test(test_id)
    licensee = get_licensee(row["licensee_id"])

    if row["status"] != "PREPARED":
        raise ApiError(
            "ERR_TEST_INVALID_STATE", "Test %s is %s, not PREPARED" % (test_id, row["status"])
        )
    if user_id == row["prepared_by_user_id"]:
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES",
            "The certifying identity must differ from the preparing identity",
        )
    deadline = row["_coverage_period_end"] + days(45)
    if now() > deadline:
        raise ApiError(
            "ERR_CERTIFICATION_WINDOW_CLOSED",
            "The certification window closed forty-five days after the coverage period end",
        )

    row["status"] = "CERTIFIED"
    row["certified_by_user_id"] = user_id
    set_dt(row, "certified_at", now())
    touch(row)

    if row["result"] == "SHORTFALL":
        licensee["consecutive_failed_test_count"] += 1
    else:
        licensee["consecutive_failed_test_count"] = 0
    _recompute_and_cascade(licensee, force_park=True)
    return ok(serialize(row))


@bp.get("/permissible-investment-tests/<test_id>")
def get_one(test_id):
    authorize(
        "LicensingManager", "ComplianceOfficer", "ChiefComplianceOfficer", "StateRegulator"
    )
    return ok(serialize(get_test(test_id)))


@bp.get("/permissible-investment-tests")
def list_all():
    authorize(
        "LicensingManager", "ComplianceOfficer", "ChiefComplianceOfficer", "StateRegulator"
    )
    limit, offset = pagination()
    filters = {
        "licensee_id": q_str("licensee_id"),
        "status": q_enum("status", TEST_STATUSES),
        "method": q_enum("method", ("BOOK_VALUE", "ELIGIBLE_MARKET")),
        "result": q_enum("result", ("PASS", "SHORTFALL")),
    }
    return paginate(filter_rows(db.tests.values(), filters), limit, offset)
