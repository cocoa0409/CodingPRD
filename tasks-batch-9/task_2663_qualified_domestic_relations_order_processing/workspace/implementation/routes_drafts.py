"""Draft-order receipt, deficiency notices, resubmission, qualification and denial."""
from flask import Blueprint

import auth
import calc
import enums
import errors
import services
import validation as v
from auth import endpoint
from envelope import object_response, paginate
from routes_cases import find_case
from store import db, public, public_list
from timeutil import add_days, fmt_date, fmt_domain_instant, parse_instant

bp = Blueprint("drafts", __name__)


def find_draft(draft_id):
    draft = db.draft_orders.get(draft_id)
    if draft is None:
        errors.fail(errors.ERR_DRAFT_ORDER_NOT_FOUND, "No draft order with that id.")
    return draft


def case_of_draft(draft):
    return db.qdro_cases[draft["qdro_case_id"]]


def plan_of_case(case):
    return db.plans[db.participants[case["participant_id"]]["plan_id"]]


def draft_terms(data):
    """Rung 3 for the substantive terms shared by receipt and resubmission."""
    terms = {
        "document_reference": v.req_string(data, "document_reference", 1, 64),
        "uses_model_language": v.req_bool(data, "uses_model_language"),
        "proposed_approach": v.req_enum(data, "proposed_approach", enums.APPROACHES),
        "proposed_formula_code": v.req_enum(data, "proposed_formula_code", enums.FORMULA_CODES),
        "provisions": v.opt_enum_array(data, "provisions", enums.PROVISIONS, False, []),
        "proposed_percentage_bps": v.opt_int(data, "proposed_percentage_bps", 1, 10000),
        "proposed_flat_amount_cents": v.opt_int(data, "proposed_flat_amount_cents", 1, None),
    }
    end_date = v.opt_date(data, "proposed_shared_payment_end_date")
    if terms["proposed_formula_code"] != "FLAT_DOLLAR" \
            and terms["proposed_percentage_bps"] is None:
        errors.bad_request("'proposed_percentage_bps' is required unless the formula is FLAT_DOLLAR.")
    if terms["proposed_formula_code"] == "FLAT_DOLLAR" \
            and terms["proposed_flat_amount_cents"] is None:
        errors.bad_request("'proposed_flat_amount_cents' is required for a FLAT_DOLLAR formula.")
    if terms["proposed_approach"] == "SHARED_PAYMENT":
        if end_date is None:
            errors.bad_request("'proposed_shared_payment_end_date' is required for a "
                               "SHARED_PAYMENT proposal.")
        if not end_date > db.today():
            errors.bad_request("'proposed_shared_payment_end_date' must be strictly later than "
                               "today.")
    terms["proposed_shared_payment_end_date"] = fmt_date(end_date) if end_date else None
    return terms


def candidate_case(case, terms):
    """The case as it would stand with these terms operative, for sizing only."""
    probe = dict(case)
    probe["approach"] = terms["proposed_approach"]
    probe["formula_code"] = terms["proposed_formula_code"]
    probe["assigned_percentage_bps"] = terms["proposed_percentage_bps"]
    probe["assigned_flat_amount_cents"] = terms["proposed_flat_amount_cents"]
    probe["shared_payment_end_date"] = terms["proposed_shared_payment_end_date"]
    return probe


def size_and_guard(case, terms):
    """Rungs 17 and 18 for a receipt or a resubmission; returns the gross amount."""
    probe = candidate_case(case, terms)
    plan, participant, account, sources, base, capped = services.sized_assignment(probe)
    if capped <= 0:
        errors.fail(errors.ERR_ASSIGNED_AMOUNT_ZERO,
                    "The computed gross assigned amount is zero.")
    services.hold_capacity_check(case, account, capped)
    return account, capped


@bp.route("/draft-orders", methods=["POST"])
@endpoint("PlanAdministrator", "QdroAnalyst", "Participant", "Attorney")
def receive_draft_order(caller):
    data = v.body()
    case_id = v.req_string(data, "qdro_case_id", 1, 200)
    expected_case_version = v.req_int(data, "expected_case_version", 0, None)
    terms = draft_terms(data)
    authorization_id = v.opt_string(data, "attorney_authorization_id", 1, 200)
    # Rung 5 - body foreign keys.
    case = db.qdro_cases.get(case_id)
    if case is None:
        errors.fail(errors.ERR_QDRO_CASE_NOT_FOUND, "No QDRO case with that id.")
    if authorization_id is not None and authorization_id not in db.attorney_authorizations:
        errors.fail(errors.ERR_AUTHORIZATION_NOT_FOUND, "No attorney authorization with that id.")
    auth.own_case(caller, case)
    auth.attorney_standing(caller, authorization_id)
    plan = plan_of_case(case)
    # The operative plan account must exist before any money can be sized (PRD 2.6).
    services.operative_plan_account(case)
    # Rung 10 - optimistic concurrency on the case.
    if expected_case_version != case["version"]:
        errors.fail(errors.ERR_STALE_CASE_VERSION,
                    "expected_case_version does not match the case's current version.")
    account, capped = size_and_guard(case, terms)

    first_receipt = not services.drafts_of_case(case["id"])
    # Any earlier non-terminal draft is superseded, and its live notices expire.
    for existing in services.drafts_of_case(case["id"]):
        if existing["status"] in ("UNDER_REVIEW", "DEFICIENT"):
            existing["status"] = "SUPERSEDED"
            db.touch(existing)
            services.expire_issued_notices(existing["id"])

    now = db.now()
    fields = dict(terms)
    fields.update({
        "qdro_case_id": case["id"],
        "attorney_authorization_id": authorization_id,
        "revision_number": 1,
        "status": "UNDER_REVIEW",
        "deficiency_codes": [],
        "reviewed_by_user_id": None,
        "received_at": db.now_iso(),
        "denial_reason": None,
    })
    fields["review_deadline_at"] = fmt_domain_instant(add_days(now, plan["review_period_days"]))
    draft = db.new_row("DraftOrder", fields)
    services.copy_operative_terms(case, draft)
    draft["deficiency_codes"] = calc.deficiency_codes(plan, case, draft)
    db.draft_orders[draft["id"]] = draft

    if first_receipt:
        case["review_status"] = "UNDER_REVIEW"
        case["segregation_status"] = "HELD"
        hold = db.new_row("SegregationHold", {
            "qdro_case_id": case["id"],
            "plan_account_id": account["id"],
            "hold_amount_cents": capped,
            "placed_at": db.now_iso(),
            "expires_at": fmt_domain_instant(add_days(now, plan["segregation_period_days"])),
            "valuation_date": case["valuation_date"],
            "segregation_date": None,
            "earnings_growth_bps": 0,
            "earnings_adjustment_cents": 0,
            "status": "HELD",
        })
        db.segregation_holds[hold["id"]] = hold
    else:
        if case["review_status"] == "DEFICIENT":
            case["review_status"] = "UNDER_REVIEW"
        hold = services.hold_for_case(case["id"])
        if hold is not None and hold["status"] == "HELD":
            hold["hold_amount_cents"] = capped
            db.touch(hold)
    services.recompute_plan_account(account)
    services.append_communication(case, "PARTICIPANT", "RECEIPT_ACKNOWLEDGMENT",
                                  "LIMITED", "SYSTEM")
    db.touch(case)
    return object_response(public(draft), 201)


@bp.route("/draft-orders/<id>", methods=["GET"])
@endpoint("PlanAdministrator", "QdroAnalyst", "Participant", "Attorney")
def read_draft_order(caller, id):
    draft = find_draft(id)
    case = case_of_draft(draft)
    auth.own_case(caller, case)
    auth.attorney_standing(caller)
    return object_response(public(draft))


@bp.route("/draft-orders", methods=["GET"])
@endpoint("PlanAdministrator", "QdroAnalyst", "Participant", "Attorney")
def list_draft_orders(caller):
    case_id = v.query_string("qdro_case_id")
    authorization_id = v.query_string("attorney_authorization_id")
    status = v.query_enum("status", enums.DRAFT_STATUSES)
    auth.attorney_standing(caller)
    rows = []
    for draft in services.order_by(list(db.draft_orders.values()), "received_at"):
        rows.append(draft)
    if case_id is not None:
        rows = [r for r in rows if r["qdro_case_id"] == case_id]
    if authorization_id is not None:
        rows = [r for r in rows if r["attorney_authorization_id"] == authorization_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if caller.role in auth.ENTITY_BACKED:
        rows = [r for r in rows if _visible(caller, r)]
    return paginate(public_list(rows))


def _visible(caller, draft):
    case = db.qdro_cases.get(draft["qdro_case_id"])
    if case is None:
        return False
    if caller.is_participant:
        return case["participant_id"] == caller.user_id
    if caller.is_attorney:
        authorization = auth.acting_authorization(caller)
        return authorization is not None and authorization["qdro_case_id"] == case["id"]
    account = db.ap_accounts.get(caller.user_id)
    return account is not None and account["qdro_case_id"] == case["id"]


def hold_window_open(case):
    """Rung 13 - the case's segregation hold is HELD and the clock is inside it."""
    hold = services.hold_for_case(case["id"])
    if hold is None or hold["status"] != "HELD" \
            or db.now() > parse_instant(hold["expires_at"]):
        errors.fail(errors.ERR_SEGREGATION_WINDOW_EXPIRED,
                    "The case's segregation window is no longer open.")
    return hold


@bp.route("/draft-orders/<id>/deficiency-notices", methods=["POST"])
@endpoint("QdroAnalyst")
def issue_deficiency_notice(caller, id):
    data = v.body()
    reviewer_notes = v.opt_string(data, "reviewer_notes", 1, 2000)
    draft = find_draft(id)
    if draft["status"] != "UNDER_REVIEW":
        errors.fail(errors.ERR_DRAFT_ORDER_NOT_UNDER_REVIEW,
                    "The draft order is not UNDER_REVIEW.")
    case = case_of_draft(draft)
    plan = plan_of_case(case)
    hold_window_open(case)
    codes = calc.deficiency_codes(plan, case, draft)
    draft["deficiency_codes"] = codes
    if not codes:
        errors.fail(errors.ERR_NO_DEFICIENCIES_TO_REPORT,
                    "The draft order carries no deficiencies.")
    now = db.now()
    notice = db.new_row("DeficiencyNotice", {
        "draft_order_id": draft["id"],
        "notice_sequence": len(services.notices_of_draft(draft["id"])) + 1,
        "deficiency_codes": list(codes),
        "reviewer_notes": reviewer_notes,
        "issued_at": db.now_iso(),
        "resubmission_deadline_at": fmt_domain_instant(
            add_days(now, plan["resubmission_window_days"])),
        "status": "ISSUED",
    })
    db.deficiency_notices[notice["id"]] = notice
    draft["status"] = "DEFICIENT"
    draft["reviewed_by_user_id"] = caller.user_id
    db.touch(draft)
    case["review_status"] = "DEFICIENT"
    services.append_party_pair(case, "DEFICIENCY_NOTICE", "LIMITED")
    db.touch(case)
    return object_response(public(notice), 201)


@bp.route("/draft-orders/<id>/deficiency-notices", methods=["GET"])
@endpoint("PlanAdministrator", "QdroAnalyst", "Participant", "Attorney")
def list_deficiency_notices(caller, id):
    status = v.query_enum("status", enums.NOTICE_STATUSES)
    draft = find_draft(id)
    case = case_of_draft(draft)
    auth.own_case(caller, case)
    auth.attorney_standing(caller)
    rows = services.notices_of_draft(draft["id"])
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return paginate(public_list(rows))


@bp.route("/draft-orders/<id>/resubmit", methods=["POST"])
@endpoint("PlanAdministrator", "Participant", "Attorney")
def resubmit_draft_order(caller, id):
    data = v.body()
    terms = draft_terms(data)
    draft = find_draft(id)
    case = case_of_draft(draft)
    auth.own_case(caller, case)
    auth.attorney_standing(caller)
    plan = plan_of_case(case)
    if draft["status"] != "DEFICIENT":
        errors.fail(errors.ERR_DRAFT_ORDER_NOT_DEFICIENT,
                    "The draft order is not DEFICIENT.")
    notice = services.latest_notice(draft["id"])
    if notice is None or notice["status"] != "ISSUED" \
            or db.now() > parse_instant(notice["resubmission_deadline_at"]):
        errors.fail(errors.ERR_RESUBMISSION_WINDOW_CLOSED,
                    "The resubmission window on the outstanding notice is closed.")
    hold = hold_window_open(case)
    if not draft["revision_number"] < plan["max_revisions"]:
        errors.fail(errors.ERR_MAX_REVISIONS_EXCEEDED,
                    "The draft order has exhausted the plan's revision allowance.")
    account, capped = size_and_guard(case, terms)

    draft.update(terms)
    draft["revision_number"] += 1
    draft["review_deadline_at"] = fmt_domain_instant(add_days(db.now(), plan["review_period_days"]))
    services.copy_operative_terms(case, draft)
    draft["deficiency_codes"] = calc.deficiency_codes(plan, case, draft)
    draft["status"] = "UNDER_REVIEW"
    db.touch(draft)
    notice["status"] = "CURED"
    db.touch(notice)
    hold["hold_amount_cents"] = capped
    db.touch(hold)
    services.recompute_plan_account(account)
    case["review_status"] = "UNDER_REVIEW"
    db.touch(case)
    return object_response(public(draft))


@bp.route("/draft-orders/<id>/qualify", methods=["POST"])
@endpoint("PlanAdministrator")
def qualify_draft_order(caller, id):
    draft = find_draft(id)
    case = case_of_draft(draft)
    participant = db.participants[case["participant_id"]]
    plan = db.plans[participant["plan_id"]]
    # Rung 8 - segregation of duties.
    if draft["reviewed_by_user_id"] is not None \
            and draft["reviewed_by_user_id"] == caller.user_id:
        errors.fail(errors.ERR_SEGREGATION_OF_DUTIES,
                    "The reviewer of this draft order may not determine it.")
    if draft["status"] != "UNDER_REVIEW":
        errors.fail(errors.ERR_DRAFT_ORDER_NOT_UNDER_REVIEW,
                    "The draft order is not UNDER_REVIEW.")
    if plan["procedures_status"] != "PUBLISHED":
        errors.fail(errors.ERR_PLAN_PROCEDURES_NOT_PUBLISHED,
                    "The plan's written QDRO procedures are not PUBLISHED.")
    hold = hold_window_open(case)
    account = services.operative_plan_account(case)
    codes = calc.deficiency_codes(plan, case, draft)
    draft["deficiency_codes"] = codes
    if codes:
        errors.fail(errors.ERR_QUALIFICATION_DEFICIENCIES_PRESENT,
                    "The draft order still carries deficiencies.")
    if services.baseline_snapshot(account["id"], case["valuation_date"]) is None:
        errors.fail(errors.ERR_VALUATION_SNAPSHOT_MISSING,
                    "No valuation snapshot matches the case's valuation_date.")
    approach = case["approach"]
    permitted = approach in (plan["allowed_approaches"] or [])
    if approach == "SHARED_PAYMENT":
        permitted = permitted and participant["benefit_commenced"] \
            and (account["monthly_payment_cents"] or 0) > 0
    elif approach == "SEPARATE_INTEREST":
        permitted = permitted and not participant["benefit_commenced"]
    if not permitted:
        errors.fail(errors.ERR_APPROACH_NOT_PERMITTED,
                    "The operative approach is not permitted for this plan or posture.")

    sources = services.assignable_sources_of(account["id"])
    base = sum(s["balance_cents"] for s in sources)
    allocations = calc.per_source_allocation(hold["hold_amount_cents"], sources, base)
    # L1 / L2.
    draft["status"] = "QUALIFIED"
    db.touch(draft)
    case["review_status"] = "QUALIFIED"
    # L3 / L4 / L5.
    ap_fields = {
        "qdro_case_id": case["id"],
        "payment_mode": approach,
        "balance_cents": 0,
        "after_tax_basis_cents": 0,
        "per_period_amount_cents": 0,
        "shared_payment_end_date": None,
        "total_distributed_gross_cents": 0,
        "established_at": db.now_iso(),
        "status": "ESTABLISHED",
    }
    if approach == "SEPARATE_INTEREST":
        segregation_date = db.today()
        growth, per_source, earnings = services.earnings_figures(
            plan, case, account, allocations, segregation_date)
        hold["status"] = "CONVERTED"
        hold["segregation_date"] = fmt_date(segregation_date)
        hold["earnings_growth_bps"] = growth
        hold["earnings_adjustment_cents"] = earnings
        db.touch(hold)
        ap_fields["balance_cents"] = hold["hold_amount_cents"] + earnings
        per_basis = calc.per_source_basis(sources, allocations)
        ap_fields["after_tax_basis_cents"] = sum(per_basis)
        # "After-tax basis follows the principal it belongs to" (PRD 3.5): the
        # basis that leaves with the assigned share leaves the bucket too, which
        # is why PRD 3.7 Level 5 names after_tax_basis_cents among the figures
        # this debit forces the account to recompute.
        for index, source in enumerate(sources):
            source["balance_cents"] -= allocations[index] + per_source[index]
            source["basis_cents"] -= per_basis[index]
            db.touch(source)
        case["segregation_status"] = "CONVERTED"
    else:
        hold["status"] = "RELEASED"
        db.touch(hold)
        ap_fields["per_period_amount_cents"] = calc.shared_payment_per_period(account, case)
        ap_fields["shared_payment_end_date"] = case["shared_payment_end_date"]
        case["segregation_status"] = "RELEASED_TO_PARTICIPANT"
    ap_fields["_established_balance_cents"] = ap_fields["balance_cents"]
    ap_fields["_established_basis_cents"] = ap_fields["after_tax_basis_cents"]
    ap_account = db.new_row("AlternatePayeeAccount", ap_fields)
    db.ap_accounts[ap_account["id"]] = ap_account
    services.recompute_plan_account(account, force=True)
    # L6 / L7.
    services.append_party_pair(case, "DETERMINATION_QUALIFIED", "FULL")
    db.touch(case)
    return object_response(public(draft))


@bp.route("/draft-orders/<id>/deny", methods=["POST"])
@endpoint("PlanAdministrator")
def deny_draft_order(caller, id):
    data = v.body()
    reason = v.req_enum(data, "denial_reason", enums.DENIAL_REASONS)
    draft = find_draft(id)
    case = case_of_draft(draft)
    plan = plan_of_case(case)
    if draft["status"] not in ("UNDER_REVIEW", "DEFICIENT"):
        errors.fail(errors.ERR_DRAFT_ORDER_NOT_UNDER_REVIEW,
                    "The draft order is not open for a determination.")
    if not _denial_supported(plan, case, draft, reason):
        errors.fail(errors.ERR_DENIAL_NOT_PERMITTED,
                    "The supplied denial_reason does not match the observable facts.")
    draft["status"] = "DENIED"
    draft["denial_reason"] = reason
    db.touch(draft)
    services.expire_issued_notices(draft["id"])
    case["review_status"] = "DENIED"
    services.append_party_pair(case, "DETERMINATION_DENIED", "LIMITED")
    db.touch(case)
    return object_response(public(draft))


def _denial_supported(plan, case, draft, reason):
    if reason == "ORDER_NOT_QUALIFIABLE":
        return (draft["status"] == "UNDER_REVIEW"
                and bool(calc.deficiency_codes(plan, case, draft)))
    if reason == "MAX_REVISIONS_EXCEEDED":
        return (draft["status"] == "DEFICIENT"
                and draft["revision_number"] >= plan["max_revisions"])
    if reason == "RESUBMISSION_WINDOW_CLOSED":
        notice = services.latest_notice(draft["id"])
        return (draft["status"] == "DEFICIENT" and notice is not None
                and db.now() > parse_instant(notice["resubmission_deadline_at"]))
    return False
