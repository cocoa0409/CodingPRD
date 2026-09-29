"""The batch reporting run: the sole producer of delinquency, suspension, late
fees, course expiry and provider lapse (PRD 3.9)."""
from flask import Blueprint

import calc
import constants as C
import db
import middleware
import response
import util
from services import cascades

bp = Blueprint("sweeps", __name__)

ENFORCEABLE_CREDIT_STATUSES = ("OPEN", "DEFICIENT")


def _next_sweep_number():
    highest = 0
    for sweep in db.all_rows("reporting_sweeps"):
        number = int(sweep.get("sweep_number") or 0)
        if number > highest:
            highest = number
    return highest + 1


def _deny_submitted_claims(attorney):
    for claim in db.all_rows("reciprocity_claims"):
        if claim.get("attorney_id") != attorney["id"]:
            continue
        if claim.get("status") != "SUBMITTED":
            continue
        cascades.set_fields(
            claim, {"status": "DENIED", "determination_reason": "ATTORNEY_ADMIN_SUSPENDED"}
        )


@bp.route("/cle/reporting-sweeps", methods=["POST"])
def run_sweep():
    middleware.require_roles([C.ROLE_BOARD_ADMIN])
    as_of = util.now_dt()
    as_of_iso = util.iso(as_of)

    sweep = db.insert(
        "reporting_sweeps",
        {
            "sweep_number": _next_sweep_number(),
            "as_of": as_of_iso,
            "cycles_examined": 0,
            "delinquencies_issued": 0,
            "suspensions_issued": 0,
            "late_fees_assessed_cents": 0,
            "courses_expired": 0,
            "providers_lapsed": 0,
        },
    )

    cycles = db.all_rows("compliance_cycles")
    cycles.sort(
        key=lambda c: (c.get("filing_deadline") or "", c.get("created_at") or "", c.get("_seq") or 0)
    )

    examined = 0
    delinquencies = 0
    suspensions = 0
    money = 0

    for cycle in cycles:
        deadline = util.parse_dt(cycle.get("filing_deadline"))
        # Every cycle in that order is considered; the deadline test belongs to
        # the enforcement step, not to the examination itself (PRD 3.9).
        examined += 1
        attorney = db.get("attorneys", cycle.get("attorney_id"))

        # Enforcement step one: the delinquency notice and its late fee.
        if (
            cycle.get("administrative_status") == "GOOD_STANDING"
            and cycle.get("credit_status") in ENFORCEABLE_CREDIT_STATUSES
            and deadline is not None
            and deadline <= as_of
        ):
            amount = calc.late_fee_cents(cycle)
            cascades.set_fields(
                cycle, {"administrative_status": "DELINQUENT", "delinquent_since": as_of_iso}
            )
            cascades.assess_fee(
                "LATE_COMPLIANCE",
                amount,
                attorney=attorney,
                cycle=cycle,
                sweep_id=sweep["id"],
            )
            delinquencies += 1
            money += amount

        # Enforcement step two: administrative suspension after sixty days.
        if (
            cycle.get("administrative_status") == "DELINQUENT"
            and cycle.get("credit_status") in ENFORCEABLE_CREDIT_STATUSES
        ):
            since = util.parse_dt(cycle.get("delinquent_since"))
            if since is not None and util.add_days(since, C.DELINQUENCY_TO_SUSPENSION_DAYS) <= as_of:
                cascades.set_fields(cycle, {"administrative_status": "ADMIN_SUSPENDED"})
                if attorney is not None:
                    if attorney.get("status") == "ACTIVE":
                        cascades.set_fields(attorney, {"status": "ADMIN_SUSPENDED"})
                    _deny_submitted_claims(attorney)
                cascades.assess_fee(
                    "REINSTATEMENT",
                    C.REINSTATEMENT_FEE_CENTS,
                    attorney=attorney,
                    cycle=cycle,
                    sweep_id=sweep["id"],
                )
                suspensions += 1
                money += C.REINSTATEMENT_FEE_CENTS

    # Course expiry.
    expired = 0
    for course in db.all_rows("courses"):
        if course.get("status") != "APPROVED":
            continue
        expires = util.parse_dt(course.get("expires_at"))
        if expires is not None and expires <= as_of:
            cascades.set_fields(course, {"status": "EXPIRED"})
            expired += 1

    # Provider lapse, with the course cascade on the ACCREDITED branch only.
    lapsed = 0
    touched_providers = []
    for provider in db.all_rows("providers"):
        if provider.get("accreditation_status") not in ("ACCREDITED", "PROBATIONARY"):
            continue
        term_end = util.parse_dt(provider.get("accreditation_term_end"))
        if term_end is None or term_end > as_of:
            continue
        was_accredited = provider.get("accreditation_status") == "ACCREDITED"
        cascades.move_provider_status(provider, "LAPSED")
        if was_accredited:
            cascades.suspend_self_certified_courses(provider)
        lapsed += 1
        touched_providers.append(provider)

    for provider in touched_providers:
        cascades.refresh_risk(provider)

    cascades.set_fields(
        sweep,
        {
            "cycles_examined": examined,
            "delinquencies_issued": delinquencies,
            "suspensions_issued": suspensions,
            "late_fees_assessed_cents": money,
            "courses_expired": expired,
            "providers_lapsed": lapsed,
        },
    )
    return response.success(db.serialize(sweep), 201)
