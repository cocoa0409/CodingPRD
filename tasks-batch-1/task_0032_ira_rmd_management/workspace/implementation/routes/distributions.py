"""Distribution endpoints."""

from flask import Blueprint, request

import db
from calculations import (
    age_at_instant,
    compute_taxable_distribution,
    distribution_basis_split,
    map_distribution_code,
)
from errors import (
    ERR_INSUFFICIENT_BALANCE,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_SECURE_DEADLINE_PASSED,
    ERR_STALE_VERSION,
    raise_api,
)
from helpers import (
    append_audit_event,
    get_account_or_404,
    get_distribution_or_404,
    get_json_body,
    get_pagination_params,
    optional_int,
    paginate,
    recompute_rmd_posture,
    require_enum,
    require_int,
    require_str,
    void_form_1099r_for_distribution,
)
from middleware import g, parse_auth_headers, require_owner_match, require_roles
from response import success_array, success_object
from serializers import distribution_to_json


bp = Blueprint("distributions", __name__, url_prefix="/ira/distributions")


DISTRIBUTION_REASONS = {"NORMAL", "EARLY", "RMD", "INHERITED", "ROLLOVER", "RETURN_OF_CONTRIBUTION"}
DISTRIBUTION_STATUSES = {"PENDING", "CONFIRMED", "REVERSED"}


@bp.route("", methods=["POST"])
def create_distribution():
    parse_auth_headers()
    require_roles("AccountOwner")
    body = get_json_body()
    account_id = require_str(body, "account_id")
    amount_cents = require_int(body, "amount_cents")
    if amount_cents <= 0:
        raise_api(ERR_INVALID_REQUEST, "amount_cents must be > 0.")
    distribution_reason = require_enum(body, "distribution_reason", DISTRIBUTION_REASONS)
    tax_year = require_int(body, "tax_year")
    federal_withholding_cents = optional_int(body, "federal_withholding_cents", default=0)
    if federal_withholding_cents < 0:
        raise_api(ERR_INVALID_REQUEST, "federal_withholding_cents must be >= 0.")

    acct = get_account_or_404(account_id)
    require_owner_match(acct["owner_id"])

    now = db.now_utc()
    d = {
        "id": db.new_id(),
        "account_id": account_id,
        "amount_cents": amount_cents,
        "distribution_reason": distribution_reason,
        "tax_year": tax_year,
        "federal_withholding_cents": federal_withholding_cents,
        "status": "PENDING",
        "confirmed_at": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.distributions[d["id"]] = d
    return success_object(distribution_to_json(d), status_code=201)


@bp.route("/<dist_id>", methods=["GET"])
def get_distribution(dist_id):
    parse_auth_headers()
    require_roles("PlanAdministrator", "AccountOwner", "IRSAuditor")
    d = get_distribution_or_404(dist_id)
    if g.role == "AccountOwner":
        acct = db.accounts.get(d["account_id"])
        if acct is None:
            from errors import ERR_NOT_FOUND
            raise_api(ERR_NOT_FOUND)
        require_owner_match(acct["owner_id"])
    return success_object(distribution_to_json(d))


@bp.route("", methods=["GET"])
def list_distributions():
    parse_auth_headers()
    require_roles("PlanAdministrator", "AccountOwner", "IRSAuditor")
    limit, offset = get_pagination_params()
    account_id = request.args.get("account_id")
    tax_year_str = request.args.get("tax_year")
    distribution_reason = request.args.get("distribution_reason")
    status = request.args.get("status")
    rows = list(db.distributions.values())
    if account_id is not None:
        rows = [d for d in rows if d["account_id"] == account_id]
    if tax_year_str is not None:
        try:
            ty = int(tax_year_str)
        except ValueError:
            raise_api(ERR_INVALID_REQUEST, "tax_year filter must be an integer.")
        rows = [d for d in rows if d["tax_year"] == ty]
    if distribution_reason is not None:
        if distribution_reason not in DISTRIBUTION_REASONS:
            raise_api(ERR_INVALID_REQUEST, "distribution_reason filter is not a recognized value.")
        rows = [d for d in rows if d["distribution_reason"] == distribution_reason]
    if status is not None:
        if status not in DISTRIBUTION_STATUSES:
            raise_api(ERR_INVALID_REQUEST, "status filter is not a recognized value.")
        rows = [d for d in rows if d["status"] == status]
    if g.role == "AccountOwner":
        owned_accounts = {a["id"] for a in db.accounts.values() if a["owner_id"] == g.user_id}
        rows = [d for d in rows if d["account_id"] in owned_accounts]
    page, total = paginate(rows, limit, offset)
    return success_array([distribution_to_json(d) for d in page], limit, offset, total)


def _make_1099r_for_distribution(d, acct, owner, clock_utc):
    """Generate the Form1099R row for a distribution at confirm time.

    Reads bases on the account as of BEFORE the basis decrement, since taxable
    calculation uses pre-distribution basis. Caller must invoke this BEFORE
    applying the basis split decrement.
    """
    gross = d["amount_cents"]
    taxable = compute_taxable_distribution(acct, gross)
    age = age_at_instant(clock_utc, owner["date_of_birth"])
    code = map_distribution_code(d["distribution_reason"], age)
    now = db.now_utc()
    f = {
        "id": db.new_id(),
        "distribution_id": d["id"],
        "conversion_id": None,
        "tax_year": d["tax_year"],
        "gross_distribution_cents": gross,
        "taxable_amount_cents": taxable,
        "federal_withholding_cents": d["federal_withholding_cents"],
        "distribution_code": code,
        "ira_sep_simple_flag": True,
        "created_at": now,
    }
    db.forms_1099r[f["id"]] = f
    return f


@bp.route("/<dist_id>/confirm", methods=["POST"])
def confirm_distribution(dist_id):
    parse_auth_headers()
    require_roles("AccountOwner")
    d = get_distribution_or_404(dist_id)
    acct = get_account_or_404(d["account_id"])
    require_owner_match(acct["owner_id"])

    # State precondition: PENDING
    if d["status"] != "PENDING":
        raise_api(ERR_INVALID_STATE, "Distribution is not PENDING.")

    body = get_json_body()
    expected = require_int(body, "expected_account_version")
    if expected != acct["version"]:
        raise_api(ERR_STALE_VERSION)

    # Account must be ACTIVE or INHERITED.
    if acct["status"] not in ("ACTIVE", "INHERITED"):
        raise_api(ERR_INVALID_STATE, "Account is not ACTIVE or INHERITED.")

    # Insufficient balance check (priority 12)
    if d["amount_cents"] > acct["cash_balance_cents"]:
        raise_api(ERR_INSUFFICIENT_BALANCE)
    if d["federal_withholding_cents"] > d["amount_cents"]:
        raise_api(ERR_INSUFFICIENT_BALANCE)

    owner = db.owners.get(acct["owner_id"])
    if owner is None:
        from errors import ERR_NOT_FOUND
        raise_api(ERR_NOT_FOUND)

    # RMD-reason precondition: an OPEN or DELINQUENT RMDSchedule must exist for
    # (owner_id, tax_year). PRD §3.4 + §3.7 (late cure).
    if d["distribution_reason"] == "RMD":
        matching_schedule = None
        for s in db.rmd_schedules.values():
            if s["owner_id"] == acct["owner_id"] and s["tax_year"] == d["tax_year"]:
                if s["status"] in ("OPEN", "DELINQUENT"):
                    matching_schedule = s
                    break
        if matching_schedule is None:
            raise_api(ERR_INVALID_STATE, "No OPEN or DELINQUENT RMDSchedule for this owner and tax_year.")

    # SECURE Act deadline check (priority 13)
    if acct["status"] == "INHERITED" and acct["account_type"] == "TRADITIONAL":
        # Find the active inherited beneficiary with NON_ELIGIBLE_INDIVIDUAL relationship.
        nei_beneficiary = None
        for b in db.beneficiary_designations.values():
            if (
                b["account_id"] == acct["id"]
                and b["status"] == "INHERITED"
                and b["relationship"] == "NON_ELIGIBLE_INDIVIDUAL"
            ):
                nei_beneficiary = b
                break
        if nei_beneficiary is not None and nei_beneficiary["secure_deadline_at"] is not None:
            clock = db.system_clock["current_utc"]
            remaining_after_confirm = acct["cash_balance_cents"] - d["amount_cents"]
            # PRD §2.6 + §3.4: a confirm that would leave a nonzero balance past
            # the deadline is rejected. We compare the clock's instant to the
            # deadline; if the clock is at or past the deadline, any leftover
            # balance is forbidden.
            if clock >= nei_beneficiary["secure_deadline_at"] and remaining_after_confirm > 0:
                raise_api(ERR_SECURE_DEADLINE_PASSED)

    # Side effects -- order: stamp distribution; balance decrement; basis split;
    # generate 1099-R (must read pre-decrement bases); RMD schedule update;
    # audit; rmd posture recompute; version bump.
    now = db.now_utc()

    # Generate 1099-R FIRST so the taxable computation reads pre-decrement bases.
    _make_1099r_for_distribution(d, acct, owner, db.system_clock["current_utc"])

    d["status"] = "CONFIRMED"
    d["confirmed_at"] = now
    d["updated_at"] = now
    d["version"] += 1

    acct["cash_balance_cents"] -= d["amount_cents"]
    if acct["account_type"] == "TRADITIONAL":
        pre_drop, aft_drop = distribution_basis_split(acct, d["amount_cents"])
        # Note: distribution_basis_split already returns (pre_drop, aft_drop)
        # where pre_drop absorbs the remainder. The function reads bases that
        # were not yet decremented (we're operating on the same dict but the
        # function uses pre/aft fields directly which haven't changed yet).
        # Apply decrements, clamping at 0 to handle the edge where total < amount
        # (shouldn't happen, but defensive).
        acct["pretax_basis_cents"] = max(0, acct["pretax_basis_cents"] - pre_drop)
        acct["aftertax_basis_cents"] = max(0, acct["aftertax_basis_cents"] - aft_drop)

    if d["distribution_reason"] == "RMD":
        for s in db.rmd_schedules.values():
            if s["owner_id"] == acct["owner_id"] and s["tax_year"] == d["tax_year"]:
                if s["status"] in ("OPEN", "DELINQUENT"):
                    s["satisfied_amount_cents"] += d["amount_cents"]
                    if s["satisfied_amount_cents"] >= s["required_amount_cents"]:
                        s["status"] = "SATISFIED"
                    s["updated_at"] = now
                    s["version"] += 1

    append_audit_event(
        owner_id=acct["owner_id"],
        account_id=acct["id"],
        event_kind="DISTRIBUTION_CONFIRMED",
        tax_year=d["tax_year"],
        amount_cents=d["amount_cents"],
    )

    acct["updated_at"] = now
    acct["version"] += 1

    # Recompute rmd_posture after the schedule mutations.
    recompute_rmd_posture(acct["owner_id"])

    return success_object(distribution_to_json(d))


@bp.route("/<dist_id>/reverse", methods=["POST"])
def reverse_distribution(dist_id):
    parse_auth_headers()
    require_roles("PlanAdministrator")
    d = get_distribution_or_404(dist_id)
    acct = get_account_or_404(d["account_id"])
    body = get_json_body()
    expected = require_int(body, "expected_account_version")

    if d["status"] != "CONFIRMED":
        raise_api(ERR_INVALID_STATE, "Distribution is not CONFIRMED.")
    if expected != acct["version"]:
        raise_api(ERR_STALE_VERSION)

    # Same tax year check: distribution.tax_year must equal account.tax_year_marker
    # AND the matching Form1099R must also belong to the current tax year.
    if d["tax_year"] != acct["tax_year_marker"]:
        raise_api(ERR_INVALID_STATE, "Distribution is not in the current tax year.")
    # Find form
    form = None
    for f in db.forms_1099r.values():
        if f["distribution_id"] == d["id"]:
            form = f
            break
    if form is not None and form["tax_year"] != db.system_clock["current_tax_year"]:
        raise_api(ERR_INVALID_STATE, "Form 1099-R is not in the current tax year.")

    now = db.now_utc()
    d["status"] = "REVERSED"
    d["updated_at"] = now
    d["version"] += 1

    acct["cash_balance_cents"] += d["amount_cents"]
    # PRD does not specify reversing the basis split decrement; the form is
    # voided rather than fully unwound. The cash balance is restored, but
    # the pretax/aftertax bases stay where they were post-split because the
    # form voiding is the documented compensating action.

    void_form_1099r_for_distribution(d["id"])

    if d["distribution_reason"] == "RMD":
        for s in db.rmd_schedules.values():
            if s["owner_id"] == acct["owner_id"] and s["tax_year"] == d["tax_year"]:
                s["satisfied_amount_cents"] = max(0, s["satisfied_amount_cents"] - d["amount_cents"])
                if s["satisfied_amount_cents"] < s["required_amount_cents"] and s["status"] == "SATISFIED":
                    s["status"] = "OPEN"
                s["updated_at"] = now
                s["version"] += 1

    acct["updated_at"] = now
    acct["version"] += 1
    recompute_rmd_posture(acct["owner_id"])
    return success_object(distribution_to_json(d))
