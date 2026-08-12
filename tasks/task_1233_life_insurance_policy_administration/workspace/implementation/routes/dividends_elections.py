"""DividendDeclaration and NonforfeitureElection endpoints (PRD §3.7, §3.8)."""
from flask import Blueprint

import domain
import errors
from db import store
from middleware import require_auth, json_body, require_int, ALL_ROLES
from response import ok_object
from routes.policies import get_policy_or_404, check_policyholder_ownership, _paged
from services import engine
from util import age_years
from util import dec, round_half_up

bp = Blueprint("dividends_elections", __name__)


# ---------------------------------------------------------------------------
# Dividend declarations
# ---------------------------------------------------------------------------
@bp.route("/policies/<policy_id>/dividend-declarations", methods=["POST"])
def declare_dividend(policy_id):
    require_auth(["PlatformAdmin"])
    policy = get_policy_or_404(policy_id)
    if policy["form_status"] in domain.POLICY_FORM_TERMINAL:
        raise errors.already_terminal("Policy is in a terminal form state")
    template = domain.template_of(policy)
    if not template["participating"]:
        raise errors.product_not_participating()
    body = json_body(required=True)
    year = require_int(body, "policy_year", minimum=1)
    declared = require_int(body, "declared_amount_cents", minimum=1)
    if year != domain.policy_year_of(policy):
        raise errors.invalid_request("policy_year must equal the policy's current policy_year")

    declaration = domain.stamp_new({
        "policy_id": policy["id"],
        "policy_year": year,
        "declared_amount_cents": declared,
        "applied_amount_cents": 0,
        "status": "DECLARED",
    })
    store.dividend_declarations[declaration["id"]] = declaration

    eligible_forms = {"IN_FORCE", "REDUCED_PAID_UP", "EXTENDED_TERM"}
    if (policy["form_status"] in eligible_forms
            and policy["premium_payment_status"] != "LAPSED"):
        option = policy["dividend_option"]
        if option == "CASH":
            declaration["applied_amount_cents"] = declared
        elif option == "PREMIUM_REDUCTION":
            open_cycles = [c for c in engine.policy_cycles(policy)
                           if c["status"] == "OPEN"]
            next_due = open_cycles[0]["due_amount_cents"] if open_cycles else 0
            applied = min(declared, next_due)
            declaration["applied_amount_cents"] = applied
            if open_cycles and applied > 0:
                cycle = open_cycles[0]
                cycle["due_amount_cents"] -= applied
                if cycle["paid_amount_cents"] >= cycle["due_amount_cents"]:
                    cycle["status"] = "PAID"
                domain.touch(cycle)
                paid_ends = [c["period_end_date"] for c in engine.policy_cycles(policy)
                             if c["status"] == "PAID"]
                if paid_ends:
                    policy["paid_to_date"] = max(paid_ends)
            if applied > 0:
                builds = domain.policy_builds_cash_value(policy)
                engine.post_ledger(policy, domain.ENTRY_PREMIUM_CREDIT, applied,
                                   change_cents=(applied if builds else 0))
        elif option == "ACCUMULATE_AT_INTEREST":
            declaration["applied_amount_cents"] = declared
            engine.post_ledger(policy, domain.ENTRY_DIVIDEND_CREDIT, declared)
            policy["dividend_accumulation_cents"] += declared
        elif option == "PAID_UP_ADDITIONS":
            insured = domain.insured_of(policy)
            age = age_years(insured["date_of_birth"], store.current_date())
            if age < 40:
                rate = dec("0.30")
            elif age < 50:
                rate = dec("0.40")
            elif age < 60:
                rate = dec("0.50")
            else:
                rate = dec("0.65")
            rate = rate + dec(policy.get("_substandard_extra_pct_bps", 0)) / dec(10000) * dec("0.10")
            face_addition = round_half_up(dec(declared) / rate)
            declaration["applied_amount_cents"] = declared
            policy["dividend_accumulation_cents"] += declared
            policy["face_amount_cents"] += face_addition
        declaration["status"] = "APPLIED"
        domain.touch(declaration)
        domain.touch_policy(policy)
    else:
        # Policy lapsed before the dividend could be applied -> forfeited
        declaration["status"] = "FORFEITED"
        domain.touch(declaration)

    return ok_object(domain.serialize_dividend(declaration), status=201)


@bp.route("/policies/<policy_id>/dividend-declarations", methods=["GET"])
def list_policy_dividends(policy_id):
    require_auth(ALL_ROLES)
    policy = get_policy_or_404(policy_id)
    return _paged([d for d in store.dividend_declarations.values()
                   if d["policy_id"] == policy["id"]], domain.serialize_dividend)


# ---------------------------------------------------------------------------
# Non-forfeiture elections
# ---------------------------------------------------------------------------
@bp.route("/policies/<policy_id>/nonforfeiture-elections", methods=["POST"])
def create_election(policy_id):
    ctx = require_auth(["Policyholder"])
    policy = get_policy_or_404(policy_id)
    if policy["form_status"] in domain.POLICY_FORM_TERMINAL:
        raise errors.already_terminal("Policy is in a terminal form state")
    if policy["form_status"] != "IN_FORCE":
        raise errors.invalid_state("Elections require form_status IN_FORCE")
    check_policyholder_ownership(ctx, policy)
    body = json_body(required=True)
    election_type = body.get("election_type")
    if election_type not in domain.ELECTION_TYPES:
        raise errors.invalid_request(
            "election_type must be CASH_SURRENDER | REDUCED_PAID_UP | EXTENDED_TERM")

    if election_type == "REDUCED_PAID_UP":
        if policy["premium_payment_status"] not in ("CURRENT", "GRACE", "LAPSED"):
            raise errors.invalid_state(
                "Reduced paid-up requires premium_payment_status CURRENT, GRACE, or LAPSED")
        existing = [e for e in store.nonforfeiture_elections.values()
                    if e["policy_id"] == policy["id"]]
        if existing:
            raise errors.invalid_state(
                "A non-forfeiture election already exists on this policy")

    # Eligibility (priority 11): positive cash value and positive net available
    if policy["cash_value_cents"] <= 0:
        raise errors.insufficient_cash_value("Policy has no cash value")
    loan_offset = (policy["outstanding_loan_principal_cents"]
                   + policy["accrued_loan_interest_cents"])
    charge = engine.compute_surrender_charge(policy)
    if policy["cash_value_cents"] - loan_offset - charge <= 0:
        raise errors.insufficient_cash_value("Net available value is not positive")

    election = engine.apply_nonforfeiture(policy, election_type)
    return ok_object(domain.serialize_election(election), status=201)


@bp.route("/policies/<policy_id>/nonforfeiture-elections", methods=["GET"])
def list_policy_elections(policy_id):
    require_auth(ALL_ROLES)
    policy = get_policy_or_404(policy_id)
    return _paged([e for e in store.nonforfeiture_elections.values()
                   if e["policy_id"] == policy["id"]], domain.serialize_election)


# ---------------------------------------------------------------------------
# Flat filtered listings
# ---------------------------------------------------------------------------
@bp.route("/dividend-declarations", methods=["GET"])
def list_all_dividends():
    require_auth(ALL_ROLES)
    from flask import request
    records = list(store.dividend_declarations.values())
    policy_id = request.args.get("policy_id")
    if policy_id is not None:
        records = [d for d in records if d["policy_id"] == policy_id]
    return _paged(records, domain.serialize_dividend)


@bp.route("/dividend-declarations/<row_id>", methods=["GET"])
def get_dividend_flat(row_id):
    require_auth(ALL_ROLES)
    row = store.dividend_declarations.get(row_id)
    if row is None:
        raise errors.not_found(errors.ERR_NOT_FOUND, "dividend declaration")
    return ok_object(domain.serialize_dividend(row))


@bp.route("/nonforfeiture-elections", methods=["GET"])
def list_all_elections():
    require_auth(ALL_ROLES)
    from flask import request
    records = list(store.nonforfeiture_elections.values())
    policy_id = request.args.get("policy_id")
    if policy_id is not None:
        records = [e for e in records if e["policy_id"] == policy_id]
    return _paged(records, domain.serialize_election)


@bp.route("/nonforfeiture-elections/<row_id>", methods=["GET"])
def get_election_flat(row_id):
    require_auth(ALL_ROLES)
    row = store.nonforfeiture_elections.get(row_id)
    if row is None:
        raise errors.not_found(errors.ERR_NOT_FOUND, "non-forfeiture election")
    return ok_object(domain.serialize_election(row))
