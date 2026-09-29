"""Fund assets, operating businesses, business tests and asset tests."""

from flask import Blueprint, g

import calc
import derive
from core import (
    API_PREFIX, ROLE_COMPLIANCE_OFFICER, ROLE_FUND_MANAGER, ROLE_PLATFORM_ADMIN,
    ZERO2, ZERO4, authenticate, fail, get, insert, must_get, must_ref,
    now_logical, pagination, rows, touch,
)
from schema import F, parse_body
from support import (
    guard_state, investor_scope, listing, manager_scope, one, segregation,
)

bp = Blueprint("asset_routes", __name__, url_prefix=API_PREFIX)

ASSET_CLASSES = ("QOZ_BUSINESS_PROPERTY", "QOZB_EQUITY",
                 "NONQUALIFIED_FINANCIAL_PROPERTY", "CASH")
SAFE_HARBORS = ("FIFTY_PCT_HOURS", "FIFTY_PCT_AMOUNTS_PAID",
                "MANAGEMENT_AND_TANGIBLE", "GROSS_INCOME_ACTUAL")


def _fund_of(asset):
    return get("funds", asset["fund_id"])


# ---------------------------------------------------------------------------
# Fund assets
# ---------------------------------------------------------------------------

@bp.post("/fund-assets")
def create_asset():
    authenticate((ROLE_FUND_MANAGER, ROLE_PLATFORM_ADMIN))
    body = parse_body([
        F("fund_id", "string", non_blank=True),
        F("asset_class", "enum", enum=ASSET_CLASSES),
        F("acquisition_date", "datetime"),
        F("unadjusted_cost_basis", "money", gte="0.00"),
        F("afs_fair_value", "money", gte="0.00"),
        F("qoz_business_id", "string", required=False, non_blank=True),
        F("acquired_from_related_party", "boolean", required=False,
          default=False),
        F("original_use_in_zone", "boolean", required=False, default=False),
    ])
    fund = must_ref("funds", body["fund_id"])
    business = None
    if body["qoz_business_id"] is not None:
        business = must_ref("qoz_businesses", body["qoz_business_id"])
    manager_scope(fund)
    if fund["certification_status"] == "DECERTIFIED":
        fail("ERR_FUND_DECERTIFIED", "Fund is decertified")
    if fund["certification_status"] != "SELF_CERTIFIED":
        fail("ERR_FUND_NOT_CERTIFIED", "Fund is not self-certified")
    if (body["acquired_from_related_party"]
            and body["asset_class"] == "QOZ_BUSINESS_PROPERTY"):
        fail("ERR_RELATED_PARTY_ACQUISITION",
             "Related-party property may not be recorded as QOZ_BUSINESS_PROPERTY")
    if body["asset_class"] == "QOZB_EQUITY":
        if business is None:
            fail("ERR_QOZB_LINK_REQUIRED",
                 "QOZB_EQUITY requires a qoz_business_id")
        if business["fund_id"] != fund["id"]:
            fail("ERR_QOZB_LINK_REQUIRED",
                 "The linked business belongs to another fund")
    elif business is not None:
        fail("ERR_QOZB_LINK_REQUIRED",
             "qoz_business_id is only legal on QOZB_EQUITY")
    asset = insert("fund_assets", {
        "fund_id": fund["id"],
        "qoz_business_id": body["qoz_business_id"],
        "asset_class": body["asset_class"],
        "acquisition_date": body["acquisition_date"],
        "acquired_from_related_party": body["acquired_from_related_party"],
        "original_use_in_zone": body["original_use_in_zone"],
        "unadjusted_cost_basis": body["unadjusted_cost_basis"],
        "afs_fair_value": body["afs_fair_value"],
        "adjusted_basis": body["unadjusted_cost_basis"],
        "qualification": derive.initial_qualification(
            body["asset_class"], body["original_use_in_zone"], business),
        "status": "HELD",
        "disposed_at": None,
        "disposition_sequence_index": None,
        "proceeds_amount": ZERO2,
    })
    derive.recompute_fund_aggregates(fund)
    return one(asset, 201)


@bp.get("/fund-assets/<asset_id>")
def read_asset(asset_id):
    authenticate((ROLE_FUND_MANAGER, ROLE_COMPLIANCE_OFFICER,
                  ROLE_PLATFORM_ADMIN))
    return one(must_get("fund_assets", asset_id))


@bp.get("/fund-assets")
def list_assets():
    authenticate((ROLE_FUND_MANAGER, ROLE_COMPLIANCE_OFFICER,
                  ROLE_PLATFORM_ADMIN))
    page = pagination()
    return listing("fund_assets", [("fund_id", "fund_id"),
                                   ("qoz_business_id", "qoz_business_id"),
                                   ("status", "status"),
                                   ("qualification", "qualification")], page)


@bp.post("/fund-assets/<asset_id>/dispose")
def dispose_asset(asset_id):
    authenticate((ROLE_FUND_MANAGER, ROLE_PLATFORM_ADMIN))
    body = parse_body([F("proceeds_amount", "money", gte="0.00")])
    asset = must_get("fund_assets", asset_id)
    fund = _fund_of(asset)
    if fund is not None:
        manager_scope(fund)
    guard_state(asset["status"], ("HELD",), ("DISPOSED",))
    index = asset["disposition_sequence_index"]
    if index is not None:
        for other in rows("fund_assets", lambda a: (
                a["fund_id"] == asset["fund_id"]
                and a["disposition_sequence_index"] is not None
                and a["disposition_sequence_index"] < index)):
            if other["status"] != "DISPOSED":
                fail("ERR_DISPOSITION_ORDER_VIOLATION",
                     "Asset at disposition position %d is not yet disposed"
                     % other["disposition_sequence_index"])
    asset["status"] = "DISPOSED"
    asset["disposed_at"] = now_logical()
    asset["proceeds_amount"] = body["proceeds_amount"]
    touch(asset)
    if fund is not None:
        derive.recompute_fund_aggregates(fund)
    return one(asset)


# ---------------------------------------------------------------------------
# QOZ businesses
# ---------------------------------------------------------------------------

@bp.post("/qoz-businesses")
def create_business():
    authenticate((ROLE_FUND_MANAGER, ROLE_PLATFORM_ADMIN))
    body = parse_body([
        F("fund_id", "string", non_blank=True),
        F("legal_name", "string", min_len=1, max_len=200, non_blank=True),
        F("zone_tract_code", "string", exact_len=11, non_blank=True),
        F("declared_nqfp_amount", "money", gte="0.00"),
        F("total_asset_value", "money", gt="0.00"),
        F("total_tangible_property_basis", "money", gte="0.00"),
    ])
    fund = must_ref("funds", body["fund_id"])
    manager_scope(fund)
    if fund["certification_status"] != "SELF_CERTIFIED":
        fail("ERR_FUND_NOT_CERTIFIED", "Fund is not self-certified")
    business = insert("qoz_businesses", {
        "fund_id": fund["id"],
        "legal_name": body["legal_name"],
        "zone_tract_code": body["zone_tract_code"],
        "declared_nqfp_amount": body["declared_nqfp_amount"],
        "total_asset_value": body["total_asset_value"],
        "total_tangible_property_basis": body["total_tangible_property_basis"],
        "wcsh_protected_amount": ZERO2,
        "blown_unspent_amount": ZERO2,
        "nqfp_amount": body["declared_nqfp_amount"],
        "qualification_status": "UNTESTED",
        "consecutive_failed_business_tests": 0,
    })
    return one(business, 201)


@bp.get("/qoz-businesses/<business_id>")
def read_business(business_id):
    authenticate((ROLE_FUND_MANAGER, ROLE_COMPLIANCE_OFFICER,
                  ROLE_PLATFORM_ADMIN))
    return one(must_get("qoz_businesses", business_id))


@bp.get("/qoz-businesses")
def list_businesses():
    authenticate((ROLE_FUND_MANAGER, ROLE_COMPLIANCE_OFFICER,
                  ROLE_PLATFORM_ADMIN))
    page = pagination()
    return listing("qoz_businesses",
                   [("fund_id", "fund_id"),
                    ("qualification_status", "qualification_status")], page)


@bp.patch("/qoz-businesses/<business_id>/reported-figures")
def patch_reported_figures(business_id):
    authenticate((ROLE_FUND_MANAGER, ROLE_PLATFORM_ADMIN))
    body = parse_body([
        F("declared_nqfp_amount", "money", required=False, gte="0.00"),
        F("total_asset_value", "money", required=False, gt="0.00"),
        F("total_tangible_property_basis", "money", required=False, gte="0.00"),
    ])
    business = must_get("qoz_businesses", business_id)
    for field in ("declared_nqfp_amount", "total_asset_value",
                  "total_tangible_property_basis"):
        if field in body["_present"]:
            business[field] = body[field]
    touch(business)
    derive.recompute_business_nqfp(business)
    return one(business)


@bp.post("/qoz-businesses/<business_id>/business-tests")
def create_business_test(business_id):
    authenticate((ROLE_FUND_MANAGER, ROLE_COMPLIANCE_OFFICER))
    body = parse_body([F("testing_date", "datetime")])
    must_get("qoz_businesses", business_id)
    test = insert("business_tests", {
        "qoz_business_id": business_id,
        "testing_date": body["testing_date"],
        "safe_harbor_used": None,
        "hours_zone_pct": None,
        "amounts_paid_zone_pct": None,
        "gross_income_zone_amount": None,
        "gross_income_total_amount": None,
        "intangibles_zone_use_amount": None,
        "intangibles_total_amount": None,
        "total_asset_value_measured": None,
        "nqfp_amount_measured": ZERO2,
        "gross_income_pct": ZERO4,
        "intangibles_pct": ZERO4,
        "nqfp_pct": ZERO4,
        "gross_income_prong": "PENDING",
        "intangibles_prong": "PENDING",
        "nqfp_prong": "PENDING",
        "status": "DRAFT",
        "measured_by_user_id": None,
        "certified_by_user_id": None,
    })
    return one(test, 201)


@bp.get("/qoz-businesses/<business_id>/business-tests")
def list_business_tests(business_id):
    authenticate((ROLE_FUND_MANAGER, ROLE_COMPLIANCE_OFFICER,
                  ROLE_PLATFORM_ADMIN))
    page = pagination()
    must_get("qoz_businesses", business_id)
    return listing("business_tests", [("status", "status")], page,
                   extra=lambda r: r["qoz_business_id"] == business_id)


# ---------------------------------------------------------------------------
# Business tests
# ---------------------------------------------------------------------------

@bp.get("/business-tests/<test_id>")
def read_business_test(test_id):
    authenticate((ROLE_FUND_MANAGER, ROLE_COMPLIANCE_OFFICER,
                  ROLE_PLATFORM_ADMIN))
    return one(must_get("business_tests", test_id))


@bp.post("/business-tests/<test_id>/measure")
def measure_business_test(test_id):
    authenticate((ROLE_FUND_MANAGER, ROLE_COMPLIANCE_OFFICER))
    body = parse_body([
        F("safe_harbor_used", "enum", enum=SAFE_HARBORS),
        F("gross_income_zone_amount", "money", gte="0.00"),
        F("gross_income_total_amount", "money", gte="0.00"),
        F("intangibles_zone_use_amount", "money", gte="0.00"),
        F("intangibles_total_amount", "money", gte="0.00"),
        F("total_asset_value_measured", "money", gt="0.00"),
        F("hours_zone_pct", "pct", required=False, gte="0.0000",
          lte="100.0000"),
        F("amounts_paid_zone_pct", "pct", required=False, gte="0.0000",
          lte="100.0000"),
    ])
    test = must_get("business_tests", test_id)
    guard_state(test["status"], ("DRAFT",), ("PASSED", "FAILED"))
    harbor = body["safe_harbor_used"]
    has_hours = "hours_zone_pct" in body["_present"]
    has_amounts = "amounts_paid_zone_pct" in body["_present"]
    if harbor == "FIFTY_PCT_HOURS":
        if not has_hours:
            fail("ERR_SAFE_HARBOR_INPUT_MISSING",
                 "FIFTY_PCT_HOURS requires hours_zone_pct")
    elif harbor == "FIFTY_PCT_AMOUNTS_PAID":
        if not has_amounts:
            fail("ERR_SAFE_HARBOR_INPUT_MISSING",
                 "FIFTY_PCT_AMOUNTS_PAID requires amounts_paid_zone_pct")
    elif has_hours or has_amounts:
        fail("ERR_SAFE_HARBOR_INPUT_MISSING",
             "%s accepts neither hours_zone_pct nor amounts_paid_zone_pct"
             % harbor)
    business = must_get("qoz_businesses", test["qoz_business_id"])
    for field in ("safe_harbor_used", "gross_income_zone_amount",
                  "gross_income_total_amount", "intangibles_zone_use_amount",
                  "intangibles_total_amount", "total_asset_value_measured",
                  "hours_zone_pct", "amounts_paid_zone_pct"):
        test[field] = body[field]
    test.update(calc.prong_evaluation(test, business["nqfp_amount"]))
    test["status"] = "MEASURED"
    test["measured_by_user_id"] = g.user_id
    touch(test)
    return one(test)


@bp.post("/business-tests/<test_id>/certify")
def certify_business_test(test_id):
    authenticate((ROLE_COMPLIANCE_OFFICER,))
    parse_body([])
    test = must_get("business_tests", test_id)
    segregation(test["measured_by_user_id"])
    guard_state(test["status"], ("MEASURED",), ("PASSED", "FAILED"))
    business = must_get("qoz_businesses", test["qoz_business_id"])
    fund = get("funds", business["fund_id"])
    test["certified_by_user_id"] = g.user_id
    derive.business_test_certified(test, business, fund)
    touch(test)
    return one(test)


# ---------------------------------------------------------------------------
# Asset tests
# ---------------------------------------------------------------------------

@bp.get("/asset-tests/<test_id>")
def read_asset_test(test_id):
    authenticate((ROLE_FUND_MANAGER, ROLE_COMPLIANCE_OFFICER,
                  ROLE_PLATFORM_ADMIN))
    return one(must_get("asset_tests", test_id))


@bp.post("/asset-tests/<test_id>/measure")
def measure_asset_test(test_id):
    authenticate((ROLE_FUND_MANAGER, ROLE_COMPLIANCE_OFFICER))
    parse_body([])
    test = must_get("asset_tests", test_id)
    fund = must_get("funds", test["fund_id"])
    if fund["certification_status"] != "SELF_CERTIFIED":
        fail("ERR_FUND_NOT_CERTIFIED", "Fund is not self-certified")
    guard_state(test["status"], ("DRAFT",),
                ("CERTIFIED_PASS", "CERTIFIED_FAIL"))
    test.update(calc.asset_test_ratio(test))
    test["status"] = "MEASURED"
    test["measured_by_user_id"] = g.user_id
    touch(test)
    fund["last_test_measurement_date"] = test["measurement_date"]
    touch(fund)
    return one(test)


@bp.post("/asset-tests/<test_id>/certify")
def certify_asset_test(test_id):
    authenticate((ROLE_COMPLIANCE_OFFICER,))
    parse_body([])
    test = must_get("asset_tests", test_id)
    segregation(test["measured_by_user_id"])
    guard_state(test["status"], ("MEASURED",),
                ("CERTIFIED_PASS", "CERTIFIED_FAIL"))
    fund = must_get("funds", test["fund_id"])
    test["certified_by_user_id"] = g.user_id
    if test["result"] == "PASS":
        test["status"] = "CERTIFIED_PASS"
        touch(test)
        derive.asset_test_certified_pass(fund)
    else:
        test["status"] = "CERTIFIED_FAIL"
        touch(test)
        derive.asset_test_certified_fail(fund, test, g.user_id)
    return one(test)
