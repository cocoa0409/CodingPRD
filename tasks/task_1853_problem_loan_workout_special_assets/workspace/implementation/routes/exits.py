"""Exit strategy decisions, case close, portfolio report (PRD §3.9)."""
from flask import Blueprint, request

import db
from auth import (
    ROLE_CREDIT_COMMITTEE, ROLE_LOAN_ACCOUNTING, ROLE_PORTFOLIO_ANALYST,
    ROLE_SPECIAL_ASSETS_MANAGER, ROLE_SYSTEM_ADMIN, ROLE_WORKOUT_OFFICER,
    require_roles,
)
from db import STORE
from errors import (
    ApiError, ERR_BUSINESS_CONSTRAINT, ERR_CASE_NOT_LEGAL,
    ERR_CASE_NOT_RESOLUTION, ERR_CURE_NOT_ESTABLISHED,
    ERR_NO_ACTIVE_REFERRAL, ERR_NOT_FOUND, ERR_OPEN_REFERRALS_EXIST,
    ERR_PATH_REQUIRES_LEGAL,
)
from response import ok, ok_report, paginate, pagination_params
from services import (
    case_out, cases_of_loan, exit_argmax, exit_decision_out, get_borrower,
    get_loan, loans_of_borrower, proposals_of_case, recompute_nonaccrual,
    referrals_of_case, sorted_rows,
)
from validate import as_enum, as_int, as_str, field, get_body, no_unknown

bp = Blueprint("exits", __name__)

CHOSEN_PATHS = ("FORECLOSURE", "DEED_IN_LIEU", "NOTE_SALE", "RETURN_TO_PERFORMING")
EXIT_READERS = (
    ROLE_WORKOUT_OFFICER, ROLE_SPECIAL_ASSETS_MANAGER, ROLE_CREDIT_COMMITTEE,
    ROLE_LOAN_ACCOUNTING, ROLE_PORTFOLIO_ANALYST, ROLE_SYSTEM_ADMIN,
)


def resolve(loanId, caseId):
    loan = get_loan(loanId)
    if loan is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Loan not found")
    case = STORE["cases"].get(caseId)
    if case is None or case["loan_id"] != loanId:
        raise ApiError(ERR_NOT_FOUND, 404, "Workout case not found")
    return loan, case


@bp.route("/loans/<loanId>/workout-cases/<caseId>/exit-decision", methods=["POST"])
def record_exit_decision(loanId, caseId):
    require_roles(ROLE_SPECIAL_ASSETS_MANAGER)
    loan, case = resolve(loanId, caseId)
    data = get_body()
    no_unknown(data, {
        "chosen_path", "npv_foreclosure_cents", "npv_deed_in_lieu_cents",
        "override_justification",
    })
    chosen = as_enum(field(data, "chosen_path"), "chosen_path", CHOSEN_PATHS)
    npv_f = as_int(field(data, "npv_foreclosure_cents"), "npv_foreclosure_cents")
    npv_d = as_int(field(data, "npv_deed_in_lieu_cents"), "npv_deed_in_lieu_cents")
    override = as_str(
        field(data, "override_justification", ""), "override_justification"
    )

    # state (priority 4): posture determines which rules apply
    from_legal = False
    if case["status"] == "LEGAL":
        from_legal = True
        if not any(
            r["status"] in ("ACTIVE", "SETTLED") for r in referrals_of_case(caseId)
        ):
            raise ApiError(
                ERR_NO_ACTIVE_REFERRAL, 409,
                "Exit from LEGAL requires an ACTIVE or SETTLED referral",
            )
    elif case["status"] == "NEGOTIATION":
        if not any(
            p["status"] == "CONSUMMATED" for p in proposals_of_case(caseId)
        ):
            raise ApiError(
                ERR_CASE_NOT_LEGAL, 409,
                "Exit from NEGOTIATION requires a CONSUMMATED proposal",
            )
    else:
        raise ApiError(
            ERR_CASE_NOT_LEGAL, 409,
            "Exit decision requires the case in LEGAL or NEGOTIATION",
        )

    # structural (priority 8): foreclosure-type paths are legal-posture only
    if not from_legal and chosen in ("FORECLOSURE", "DEED_IN_LIEU"):
        raise ApiError(
            ERR_PATH_REQUIRES_LEGAL, 422,
            "FORECLOSURE or DEED_IN_LIEU from NEGOTIATION requires LEGAL",
        )

    # NPV argmax with ties resolving to DEED_IN_LIEU; override must be documented
    winner = exit_argmax(npv_f, npv_d)
    tie = npv_f == npv_d
    if chosen != winner and override == "":
        raise ApiError(
            ERR_BUSINESS_CONSTRAINT, 422,
            "chosen_path differs from the computed NPV argmax without override",
        )
    if chosen == winner:
        outcome = (
            f"chosen_path {chosen} matches computed argmax "
            f"(npv_foreclosure_cents={npv_f}, npv_deed_in_lieu_cents={npv_d})"
        )
        if tie:
            outcome += "; exact tie resolved to DEED_IN_LIEU"
    else:
        outcome = (
            f"override: chosen_path {chosen} deviates from computed argmax "
            f"{winner} (npv_foreclosure_cents={npv_f}, "
            f"npv_deed_in_lieu_cents={npv_d}); override_justification recorded"
        )

    decision = db.stamp_ledger({
        "id": db.new_id(),
        "case_id": caseId,
        "chosen_path": chosen,
        "npv_foreclosure_cents": npv_f,
        "npv_deed_in_lieu_cents": npv_d,
        "decision_rule_outcome": outcome,
        "override_justification": override,
        "decided_at": db.fmt_clock(db.logical_now()),
    })
    STORE["exit_decisions"][decision["id"]] = decision

    case["status"] = "RESOLUTION"
    case["resolution_path"] = chosen
    db.touch(case)
    if chosen in ("FORECLOSURE", "DEED_IN_LIEU"):
        loan["status"] = "FORECLOSURE"
        loan["nonaccrual"] = True
        db.touch(loan)
    else:
        recompute_nonaccrual(loan)
    return ok(exit_decision_out(decision), 201)


@bp.route("/loans/<loanId>/workout-cases/<caseId>/exit-decisions", methods=["GET"])
def list_exit_decisions(loanId, caseId):
    require_roles(*EXIT_READERS)
    resolve(loanId, caseId)
    rows = [
        exit_decision_out(d)
        for d in sorted_rows(
            [d for d in STORE["exit_decisions"].values() if d["case_id"] == caseId]
        )
    ]
    return paginate(rows)


@bp.route("/loans/<loanId>/workout-cases/<caseId>/close", methods=["POST"])
def close_case(loanId, caseId):
    require_roles(ROLE_SPECIAL_ASSETS_MANAGER)
    loan, case = resolve(loanId, caseId)
    if case["status"] != "RESOLUTION":
        raise ApiError(ERR_CASE_NOT_RESOLUTION, 409, "Case is not RESOLUTION")
    if any(
        r["status"] not in ("SETTLED", "DISMISSED") for r in referrals_of_case(caseId)
    ):
        raise ApiError(
            ERR_OPEN_REFERRALS_EXIST, 409,
            "All legal referrals must be SETTLED or DISMISSED before close",
        )
    if case["resolution_path"] == "RETURN_TO_PERFORMING":
        if loan["days_past_due"] >= 60 or loan["current_principal_cents"] <= 0:
            raise ApiError(
                ERR_CURE_NOT_ESTABLISHED, 422,
                "RETURN_TO_PERFORMING requires days_past_due < 60 and "
                "current_principal_cents > 0",
            )
    case["status"] = "CLOSED"
    db.touch(case)
    loan["status"] = (
        "PERFORMING"
        if case["resolution_path"] == "RETURN_TO_PERFORMING"
        else "RESOLVED"
    )
    db.touch(loan)
    # borrower exits when every case on every one of its loans has closed
    borrower = get_borrower(loan["borrower_id"])
    if borrower is not None and borrower["status"] == "ACTIVE":
        still_open = any(
            c["status"] != "CLOSED"
            for l in loans_of_borrower(borrower["id"])
            for c in cases_of_loan(l["id"])
        )
        if not still_open:
            borrower["status"] = "EXITED"
            db.touch(borrower)
    return ok(case_out(case))


# --------------------------------------------------------------------------
# Portfolio classified-exposure report (computed read)
# --------------------------------------------------------------------------

@bp.route("/portfolio-report", methods=["GET"])
def portfolio_report():
    require_roles(
        ROLE_PORTFOLIO_ANALYST, ROLE_SPECIAL_ASSETS_MANAGER, ROLE_SYSTEM_ADMIN
    )
    # as_of is accepted for forward compatibility; the store is current-state
    if "as_of" in request.args:
        as_str(request.args["as_of"], "as_of")
    limit, offset = pagination_params()

    included = sorted_rows(
        [
            l for l in STORE["loans"].values()
            if l["status"] in ("WATCHLIST", "WORKOUT", "FORECLOSURE")
        ]
    )
    gross_total = 0
    net_total = 0
    rows = []
    for loan in included:
        open_case = next(
            (
                c for c in sorted_rows(cases_of_loan(loan["id"]))
                if c["status"] != "CLOSED"
            ),
            None,
        )
        reserve = open_case["impairment_reserve_cents"] if open_case else 0
        gross = loan["current_principal_cents"] + loan["charged_off_principal_cents"]
        net = gross - reserve if open_case else 0
        if open_case is None:
            gross = 0
        gross_total += gross
        net_total += net
        rows.append({
            "loan_id": loan["id"],
            "loan_number": loan["loan_number"],
            "status": loan["status"],
            "current_principal_cents": loan["current_principal_cents"],
            "charged_off_principal_cents": loan["charged_off_principal_cents"],
            "impairment_reserve_cents": reserve,
            "gross_classified_cents": gross,
            "net_classified_cents": net,
        })
    total = len(rows)
    window = rows[offset:offset + limit]
    return ok_report(
        {
            "gross_classified_cents": gross_total,
            "net_classified_cents": net_total,
            "loan_rows": window,
        },
        limit, offset, total,
    )
