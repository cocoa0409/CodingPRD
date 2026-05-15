"""Contribution endpoints."""

from flask import Blueprint, g, request
from core.auth import require_roles
from core.envelope import success_object, success_array
from core.errors import raise_error
from core.store import STORE, lock
from core.clock import CLOCK
from core.validation import (
    require_body, require_field, require_enum, parse_pagination,
)
from core.models import (
    contribution_create, contribution_view, touch,
)
from services.calculations import (
    compute_state_credit, ANNUAL_GIFT_EXCLUSION_CENTS,
)
from services.calendar import ensure_donor_year, year_from_iso


bp = Blueprint("contributions", __name__)


def _check_donor_owns_account(account):
    if g.user_role == "Donor" and account["primary_donor_id"] != g.user_id:
        raise_error("ERR_FORBIDDEN", "Donor does not own this account")


def _check_donor_can_read_account(account):
    if g.user_role == "Donor" and account["primary_donor_id"] != g.user_id:
        raise_error("ERR_FORBIDDEN", "Donor does not own this account")
    if g.user_role == "Beneficiary" and account["beneficiary_id"] != g.user_id:
        raise_error("ERR_FORBIDDEN", "Beneficiary may only read accounts they benefit from")


@bp.post("/accounts/<aid>/contributions")
@require_roles("Donor")
def create_contribution(aid):
    body = require_body(request)
    donor_id = require_field(body, "donor_id", kind="string")
    amount_cents = require_field(body, "amount_cents", kind="positive_int")
    contribution_kind = require_enum(body, "contribution_kind", {"LUMP_SUM", "RECURRING"})
    recurring_plan_id = body.get("recurring_plan_id")
    if contribution_kind == "RECURRING":
        if not isinstance(recurring_plan_id, str):
            raise_error("ERR_VALIDATION_FAILED",
                        "recurring_plan_id required when contribution_kind=RECURRING")
    else:
        if recurring_plan_id is not None:
            raise_error("ERR_VALIDATION_FAILED",
                        "recurring_plan_id must be null for LUMP_SUM contributions")

    with lock():
        a = STORE.accounts.get(aid)
        if not a:
            raise_error("ERR_NOT_FOUND", f"Account {aid} not found")
        # PRD §3.3: "the donor in the payload need not equal the account's
        # primary_donor_id, because third-party gifts (a grandparent funding
        # a parent's account) are explicitly supported." So we do NOT check
        # ownership on this endpoint — any Donor caller may contribute.
        if not STORE.donors.get(donor_id):
            raise_error("ERR_NOT_FOUND", f"Donor {donor_id} not found")
        if recurring_plan_id is not None and recurring_plan_id not in STORE.recurring_plans:
            raise_error("ERR_NOT_FOUND", f"RecurringPlan {recurring_plan_id} not found")
        if a["status"] != "OPEN":
            raise_error("ERR_ACCOUNT_RESTRICTED",
                        f"Account is {a['status']}; cannot create contribution")
        c = contribution_create(aid, donor_id, amount_cents, contribution_kind, recurring_plan_id)
    return success_object(contribution_view(c), 201)


@bp.post("/contributions/<cid>/settle")
@require_roles("PlanAdministrator")
def settle_contribution(cid):
    with lock():
        c = STORE.contributions.get(cid)
        if not c:
            raise_error("ERR_NOT_FOUND", f"Contribution {cid} not found")
        a = STORE.accounts.get(c["account_id"])
        if not a:
            raise_error("ERR_NOT_FOUND", "Account missing for this contribution")
        # State priority: account restricted -> ERR_ACCOUNT_RESTRICTED before invalid_state.
        if a["status"] != "OPEN":
            raise_error("ERR_ACCOUNT_RESTRICTED",
                        f"Account is {a['status']}; cannot settle contribution")
        if c["status"] != "PENDING":
            raise_error("ERR_INVALID_STATE",
                        f"Contribution is {c['status']}; only PENDING may settle")

        donor = STORE.donors.get(c["donor_id"])
        if not donor:
            raise_error("ERR_NOT_FOUND", "Donor missing for this contribution")

        # Annual reset bookkeeping for donor: tied to the CURRENT clock year.
        now_iso = CLOCK.now_iso()
        current_year = year_from_iso(now_iso)
        ensure_donor_year(donor, current_year)

        # Business fiscal: gift exclusion (priority 14) then lifetime cap (priority 15).
        if donor["ytd_contribution_total_cents"] + c["amount_cents"] > ANNUAL_GIFT_EXCLUSION_CENTS:
            raise_error("ERR_GIFT_EXCLUSION_EXCEEDED",
                        "Donor would exceed annual gift exclusion")
        if a["total_balance_cents"] + c["amount_cents"] > a["lifetime_contribution_cap_cents"]:
            raise_error("ERR_LIFETIME_CAP_WOULD_EXCEED",
                        "Account would exceed its lifetime contribution cap")

        # Commit balance changes.
        a["basis_balance_cents"] += c["amount_cents"]
        a["total_balance_cents"] += c["amount_cents"]
        # earnings_balance_cents stays unchanged on contribution.
        touch(a)

        donor["ytd_contribution_total_cents"] += c["amount_cents"]

        # State tax benefit credit (against donor's residence-state rule).
        residence_rule = STORE.state_rules.get(donor["state_of_residence"])
        if residence_rule is not None:
            credit = compute_state_credit(c["amount_cents"], donor, a, residence_rule)
            donor["ytd_state_deduction_used_cents"] += credit
        touch(donor)

        c["status"] = "SETTLED"
        c["settled_at"] = now_iso
    return success_object(contribution_view(c))


@bp.post("/contributions/<cid>/reverse")
@require_roles("PlanAdministrator")
def reverse_contribution(cid):
    with lock():
        c = STORE.contributions.get(cid)
        if not c:
            raise_error("ERR_NOT_FOUND", f"Contribution {cid} not found")
        if c["status"] != "PENDING":
            raise_error("ERR_INVALID_STATE",
                        f"Cannot reverse contribution in status {c['status']}")
        c["status"] = "REVERSED"
    return success_object(contribution_view(c))


@bp.get("/contributions/<cid>")
@require_roles("PlanAdministrator", "Donor")
def get_contribution(cid):
    c = STORE.contributions.get(cid)
    if not c:
        raise_error("ERR_NOT_FOUND", f"Contribution {cid} not found")
    if g.user_role == "Donor":
        a = STORE.accounts.get(c["account_id"])
        if not a or a["primary_donor_id"] != g.user_id:
            raise_error("ERR_FORBIDDEN", "Donor may only read contributions on their own accounts")
    return success_object(contribution_view(c))


@bp.get("/accounts/<aid>/contributions")
@require_roles("PlanAdministrator", "Donor", "Beneficiary")
def list_contributions(aid):
    a = STORE.accounts.get(aid)
    if not a:
        raise_error("ERR_NOT_FOUND", f"Account {aid} not found")
    _check_donor_can_read_account(a)
    limit, offset = parse_pagination(request)
    status = request.args.get("status")
    kind = request.args.get("contribution_kind")
    rows = [c for c in STORE.contributions.values() if c["account_id"] == aid]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if kind is not None:
        rows = [r for r in rows if r["contribution_kind"] == kind]
    rows.sort(key=lambda r: (r["_created_seq"], r["id"]))
    total = len(rows)
    page = [contribution_view(r) for r in rows[offset:offset + limit]]
    return success_array(page, limit, offset, total)
