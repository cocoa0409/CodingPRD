"""Recording, pricing and disposing of member usage (PRD 3.6)."""

from flask import Blueprint

import calc
import services
from calc import num
from db import (create_row, db, get_dt, logical_now, ordered, serialize, set_dt)
from errors import fail
from middleware import (ROLE_AUDITOR, ROLE_COOP_ADMIN, ROLE_LEAD_AGENCY,
                        ROLE_MEMBER, ROLE_SUPPLIER, actor_id, commit,
                        require_roles, touch)
from response import created_response, object_response
from routes.common import USAGE_STATUS, fetch, list_endpoint
from validation import bad, json_body, read_id, read_int, read_list, read_str

bp = Blueprint("contract_usages", __name__)

READ_ROLES = (ROLE_COOP_ADMIN, ROLE_LEAD_AGENCY, ROLE_SUPPLIER, ROLE_MEMBER,
              ROLE_AUDITOR)
DISPOSITION_ACTIONS = ("CONFIRM", "RETRACT")
AUTHORISING_DETERMINATIONS = ("AUTHORIZED", "CONDITIONAL")
RETRACTABLE_REPORT_STATUSES = ("DRAFT", "SUBMITTED", "REJECTED")


@bp.route("/coop/contract-usages", methods=["POST"])
@require_roles(ROLE_MEMBER)
def create_usage():
    body = json_body(
        allowed=("contract_id", "member_agency_id", "line_item_id",
                 "piggyback_analysis_id", "quantity", "add_on_codes"),
        required=("contract_id", "member_agency_id", "line_item_id",
                  "piggyback_analysis_id", "quantity"),
    )
    contract_id = read_id(body, "contract_id", required=True)
    member_id = read_id(body, "member_agency_id", required=True)
    line_item_id = read_id(body, "line_item_id", required=True)
    analysis_id = read_id(body, "piggyback_analysis_id", required=True)
    quantity = read_int(body, "quantity", required=True, minimum=1)
    raw_codes = read_list(body, "add_on_codes", default=None)
    codes = []
    if raw_codes is not None:
        for value in raw_codes:
            if not isinstance(value, str):
                bad("each 'add_on_codes' entry must be a string")
            codes.append(value)

    # 5. body foreign keys in entity field order
    contract = fetch(db.contracts, contract_id, "ERR_CONTRACT_NOT_FOUND")
    member = fetch(db.members, member_id, "ERR_MEMBER_NOT_FOUND")
    line = fetch(db.line_items, line_item_id, "ERR_LINE_ITEM_NOT_FOUND")
    analysis = fetch(db.analyses, analysis_id, "ERR_ANALYSIS_NOT_FOUND")

    # 7. the acting member must own the order
    if actor_id() != member_id:
        fail("ERR_ACTOR_SCOPE_MISMATCH",
             "X-User-ID must be the member_agency_id named in the body")

    # 10. the contract must be ACTIVE
    if contract["status"] != "ACTIVE":
        fail("ERR_CONTRACT_NOT_ACTIVE", "the master contract is not ACTIVE")

    # 18. the member must be ACTIVE
    if member["registration_status"] != "ACTIVE":
        fail("ERR_MEMBER_NOT_ACTIVE", "the member agency is not ACTIVE")

    # 20. the line must be live
    if line["status"] != "ACTIVE":
        fail("ERR_LINE_ITEM_NOT_ACTIVE", "the price-sheet line is not ACTIVE")

    # 30. the cited opinion must authorise the purchase
    if analysis["status"] != "DETERMINED" or analysis[
            "determination"] not in AUTHORISING_DETERMINATIONS:
        fail("ERR_PIGGYBACK_NOT_AUTHORIZED",
             "the cited authority opinion does not authorise this order")

    # 31. and must not have expired
    now = logical_now()
    expires_on = get_dt(analysis, "expires_on")
    if expires_on is None or not now < expires_on:
        fail("ERR_PIGGYBACK_EXPIRED", "the cited authority opinion has expired")

    # 32. the remittance-health dimension must permit new orders
    if contract["compliance_posture"] not in ("COMPLIANT", "WATCH"):
        fail("ERR_CONTRACT_POSTURE_DELINQUENT",
             "the contract's compliance posture is DELINQUENT")

    # 34. the line must belong to the named contract
    if line["contract_id"] != contract_id:
        fail("ERR_LINE_ITEM_CONTRACT_MISMATCH",
             "the line item does not belong to this contract")

    # 35. the opinion must cover exactly this member and contract
    if analysis["member_agency_id"] != member_id or analysis[
            "contract_id"] != contract_id:
        fail("ERR_ANALYSIS_PAIR_MISMATCH",
             "the cited opinion does not cover this member and contract")

    # 38. every elected add-on must be in the catalogue
    _check_add_ons(contract, codes)

    # 47. ordered_at must fall inside the half-open contract term
    base_start = get_dt(contract, "base_term_start")
    term_end = get_dt(contract, "current_term_end")
    if base_start is None or term_end is None or now < base_start or now >= term_end:
        fail("ERR_OUTSIDE_CONTRACT_TERM",
             "the order instant falls outside the contract term")

    # Steps one through eight of the pricing ladder.
    spend_basis = int(member["committed_spend_cents"])
    priced = calc.member_usage_total(contract, line, member, quantity, codes,
                                    spend_basis)

    # 61. the member's board-approved ceiling
    if spend_basis + priced["total_cents"] > int(
            member["annual_spend_ceiling_cents"]):
        fail("ERR_MEMBER_CEILING_EXCEEDED",
             "the order would push committed spend past the member's ceiling")

    row = create_row(
        db.usages,
        contract_id=contract_id,
        member_agency_id=member_id,
        line_item_id=line_item_id,
        piggyback_analysis_id=analysis_id,
        quantity=quantity,
        add_on_codes=codes,
        status="RECORDED",
        spend_basis_cents=priced["spend_basis_cents"],
        discount_tier_index=priced["discount_tier_index"],
        total_discount_pct=num(priced["total_discount_pct"]),
        net_unit_price_cents=priced["net_unit_price_cents"],
        subtotal_cents=priced["subtotal_cents"],
        add_on_detail=priced["add_on_detail"],
        add_on_charges_cents=priced["add_on_charges_cents"],
        chargeable_base_cents=priced["chargeable_base_cents"],
        effective_fee_rate_bps=priced["effective_fee_rate_bps"],
        admin_fee_cents=priced["admin_fee_cents"],
        total_cents=priced["total_cents"],
        usage_report_id=None,
        ordered_at=None,
        retracted_at=None,
    )
    set_dt(row, "ordered_at", now)
    set_dt(row, "retracted_at", None)

    # Step nine, the debits.
    services.recompute_member_committed_spend(member)
    services.recompute_contract_usage_total(contract)
    commit()
    return created_response(serialize(row))


def _check_add_ons(contract, codes):
    permitted = set(entry["code"] for entry in contract["permitted_add_ons"])
    seen = set()
    for code in codes:
        if code not in permitted:
            fail("ERR_ADD_ON_NOT_PERMITTED",
                 "add-on code %s is not in the contract's catalogue" % code)
        if code in seen:
            fail("ERR_ADD_ON_NOT_PERMITTED",
                 "add-on code %s is elected more than once" % code)
        seen.add(code)


@bp.route("/coop/contract-usages", methods=["GET"])
@require_roles(*READ_ROLES)
def list_usages():
    return list_endpoint(
        lambda: ordered(db.usages),
        {"contract_id": ("contract_id", None),
         "member_agency_id": ("member_agency_id", None),
         "line_item_id": ("line_item_id", None),
         "piggyback_analysis_id": ("piggyback_analysis_id", None),
         "usage_report_id": ("usage_report_id", None),
         "status": ("status", USAGE_STATUS)},
    )


@bp.route("/coop/contract-usages/<usage_id>", methods=["GET"])
@require_roles(*READ_ROLES)
def read_usage(usage_id):
    row = fetch(db.usages, usage_id, "ERR_USAGE_NOT_FOUND")
    return object_response(serialize(row))


@bp.route("/coop/contract-usages/<usage_id>/disposition", methods=["POST"])
@require_roles(ROLE_MEMBER)
def disposition(usage_id):
    body = json_body(allowed=("action", "note"), required=("action",))
    action = read_str(body, "action", required=True, enum=DISPOSITION_ACTIONS)
    read_str(body, "note")

    usage = fetch(db.usages, usage_id, "ERR_USAGE_NOT_FOUND")

    # 7. the acting member must own the order
    if actor_id() != usage["member_agency_id"]:
        fail("ERR_ACTOR_SCOPE_MISMATCH",
             "X-User-ID must be the order's member_agency_id")

    # 16. from-state on the order's dimension
    status = usage["status"]
    expected = {"CONFIRM": ("RECORDED",),
                "RETRACT": ("RECORDED", "CONFIRMED")}[action]
    if status not in expected:
        fail("ERR_USAGE_INVALID_STATE",
             "%s is not a declared transition out of %s" % (action, status))

    # 17. a settled order can no longer be unwound
    report = None
    if usage["usage_report_id"] is not None:
        report = db.reports.get(usage["usage_report_id"])
    if action == "RETRACT" and report is not None:
        if report["status"] not in RETRACTABLE_REPORT_STATUSES:
            fail("ERR_USAGE_ALREADY_SETTLED",
                 "the sweeping report has already settled the fee ledger")

    contract = db.contracts[usage["contract_id"]]
    member = db.members[usage["member_agency_id"]]

    if action == "CONFIRM":
        usage["status"] = "CONFIRMED"
        touch(usage)
    else:
        usage["status"] = "RETRACTED"
        set_dt(usage, "retracted_at", logical_now())
        usage["usage_report_id"] = None
        touch(usage)
        # hop one: release the committed spend and the chargeable total
        services.recompute_member_committed_spend(member)
        services.recompute_contract_usage_total(contract)
        # hop two: re-run the sweep of the report that had covered the order
        if report is not None:
            services.sweep_report(report, contract)
            touch(report)
        # hop three: the recomputed figures re-run the compliance posture
        services.recompute_compliance_posture(contract)

    commit()
    return object_response(serialize(usage))
