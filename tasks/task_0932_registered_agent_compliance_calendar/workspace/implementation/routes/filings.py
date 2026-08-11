"""Filings, fees and the capped refile cycle (PRD 3.7)."""

import envelope
import listing
import lookup
import serializers
import timeutil
from constants import EXPEDITE_TIERS, FILING_KINDS, MAX_REFILE_ATTEMPTS, OUTCOMES, REFILE_WINDOW_DAYS
from dispatch import endpoint
from errors import ApiError
from services import filings as filing_service
from services import obligations as obligation_service
from services import payments as payment_service
from services import rollups, rules
from store import DB, new_row, touch

READ_ROLES = ["PlatformAdmin", "ComplianceOfficer", "FilingAgent", "ClientContact"]


def _new_filing(registration_id, obligation_id, certificate_id, kind, tier, fees, prepared_by,
                attempt_number, rule_id, case_id):
    row = new_row(
        DB.filings,
        {
            "registration_id": registration_id,
            "compliance_obligation_id": obligation_id,
            "good_standing_certificate_id": certificate_id,
            "filing_kind": kind,
            "expedite_tier": tier,
            "status": "DRAFT",
            "attempt_number": attempt_number,
            "prepared_by_user_id": prepared_by,
            "submitted_by_user_id": None,
            "submitted_on": None,
            "outcome_recorded_on": None,
            "rejection_reason": None,
            "refile_window_end": None,
            "state_fee_cents": fees["state_fee_cents"],
            "service_fee_cents": fees["service_fee_cents"],
            "expedite_fee_cents": fees["expedite_fee_cents"],
            "state_portion_cents": fees["state_portion_cents"],
            "service_portion_cents": fees["service_portion_cents"],
            "total_fee_cents": fees["total_fee_cents"],
            "paid_amount_cents": 0,
            # internal, never serialised: which rule version priced this row and
            # which reinstatement case the caller named (the Filing entity
            # declares no field for either).
            "_rule_id": rule_id,
            "_reinstatement_case_id": case_id,
        },
    )
    return row


@endpoint(
    "POST",
    "/compliance-obligations/{id}/filings",
    roles=["ComplianceOfficer"],
    success_code=201,
)
def draft_obligation_filing(context):
    obligation = context.row
    body = context.body
    kind = body.enum("filing_kind", FILING_KINDS, required=True)
    tier = body.enum("expedite_tier", EXPEDITE_TIERS, default="NONE")
    expected = body.integer("expected_compliance_obligation_version", required=True)
    body.check_enums()  # rung 14
    if expected != obligation["version"]:  # rung 15
        raise ApiError("ERR_STALE_VERSION")

    # ADJUDICATION OF FRICTION 9 -- filing_kind versus the parent obligation's
    # obligation_type.  Reading: UNCONSTRAINED.  No rung of the ladder, no
    # state-machine precondition and no error identifier in the catalogue
    # covers a mismatch, so imposing one would manufacture an undeclared
    # failure mode and would make every kind other than the obligation's own
    # type unreachable on this endpoint.  Leaving it unconstrained keeps all
    # seven declared filing kinds reachable from an obligation-backed draft.

    # The obligation is re-priced at the current clock date first; its version
    # moves, which is exactly why the caller had to prove a current view.
    obligation_service.reprice_late_fee(obligation, timeutil.today())
    touch(obligation)
    rollups.cascade_from_obligation(obligation)

    rule = DB.state_rules[obligation["governing_rule_id"]]
    fees = filing_service.obligation_backed_breakdown(obligation, tier, rule)
    row = _new_filing(
        obligation["registration_id"],
        obligation["id"],
        None,
        kind,
        tier,
        fees,
        context.user_id,
        1,
        rule["id"],
        None,
    )
    return envelope.object_response(serializers.filing(row), 201)


@endpoint("POST", "/registrations/{id}/filings", roles=["ComplianceOfficer"], success_code=201)
def draft_standalone_filing(context):
    registration = context.row
    body = context.body
    kind = body.enum("filing_kind", FILING_KINDS, required=True)
    tier = body.enum("expedite_tier", EXPEDITE_TIERS, default="NONE")
    body.identifier("good_standing_certificate_id", default=None)
    body.identifier("reinstatement_case_id", default=None)
    body.check_enums()  # rung 14

    rule = rules.select(registration["state_code"], timeutil.today())  # rung 18
    certificate = context.refs.get("good_standing_certificate_id")
    case = context.refs.get("reinstatement_case_id")
    if kind == "REINSTATEMENT" and case is None:
        cases = lookup.cases_of_registration(registration["id"])
        assessed = [c for c in cases if c["assessment_date"] is not None]
        assessed.sort(key=lambda c: (c["created_at"], c["_seq"]))
        case = assessed[-1] if assessed else None
    state_fee = filing_service.standalone_state_fee(kind, rule, case)
    fees = filing_service.breakdown(state_fee, filing_service.base_service_fee(), tier, rule)
    row = _new_filing(
        registration["id"],
        None,
        certificate["id"] if certificate else None,
        kind,
        tier,
        fees,
        context.user_id,
        1,
        rule["id"],
        case["id"] if case else None,
    )
    return envelope.object_response(serializers.filing(row), 201)


@endpoint("GET", "/filings", roles=READ_ROLES, success_code=200)
def list_filings(context):
    rows = list(DB.filings.values())
    if context.is_client_contact:
        allowed = {r["id"] for r in lookup.registrations_of_client(context.user_id)}
        rows = [f for f in rows if f["registration_id"] in allowed]
    rows = listing.apply_filters(
        rows,
        [
            ("registration_id", "registration_id"),
            ("compliance_obligation_id", "compliance_obligation_id"),
            ("good_standing_certificate_id", "good_standing_certificate_id"),
            ("status", "status"),
            ("filing_kind", "filing_kind"),
        ],
    )
    return listing.respond(rows, serializers.filing)


@endpoint("GET", "/filings/{id}", roles=READ_ROLES, success_code=200)
def read_filing(context):
    return envelope.object_response(serializers.filing(context.row))


@endpoint("POST", "/filings/{id}/submit", roles=["FilingAgent"], success_code=200)
def submit_filing(context):
    filing = context.row
    registration = DB.registrations.get(filing["registration_id"])
    # declared gate order (PRD 2.9.1): 16, then 32, then 37
    if filing["status"] != "DRAFT" or registration is None or registration["status"] not in (
        "PENDING",
        "ACTIVE",
        "DELINQUENT",
        "ADMIN_DISSOLVED",
    ):  # rung 16
        raise ApiError("ERR_INVALID_STATE")
    if context.user_id == filing["prepared_by_user_id"]:  # rung 32
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    if filing["paid_amount_cents"] < filing["total_fee_cents"]:  # rung 37
        raise ApiError("ERR_INSUFFICIENT_CAPTURED_FUNDS")

    filing["status"] = "SUBMITTED"
    filing["submitted_on"] = timeutil.today()
    filing["submitted_by_user_id"] = context.user_id
    touch(filing)
    if filing["filing_kind"] == "REINSTATEMENT":
        for case in filing_service.cases_in_status(filing, "PAID"):
            case["status"] = "FILED"
            touch(case)
    return envelope.object_response(serializers.filing(filing))


@endpoint("POST", "/filings/{id}/record-outcome", roles=["FilingAgent"], success_code=200)
def record_outcome(context):
    filing = context.row
    body = context.body
    outcome = body.enum("outcome", OUTCOMES, required=True)
    rejection_reason = body.string("rejection_reason", default=None, non_empty=False)
    body.check_enums()  # rung 14
    if filing["status"] != "SUBMITTED":  # rung 16
        raise ApiError("ERR_INVALID_STATE")

    clock_date = timeutil.today()
    if outcome == "ACCEPTED":
        # hop 1
        filing["status"] = "ACCEPTED"
        filing["outcome_recorded_on"] = clock_date
        touch(filing)
        # hops 2-5, each condition checked independently
        obligation_id = filing["compliance_obligation_id"]
        if obligation_id:
            obligation = DB.obligations.get(obligation_id)
            if obligation is not None:
                obligation_service.satisfy(obligation)
    else:
        filing["status"] = "REJECTED"
        filing["outcome_recorded_on"] = clock_date
        filing["rejection_reason"] = rejection_reason
        filing["refile_window_end"] = timeutil.add_days(clock_date, REFILE_WINDOW_DAYS)
        touch(filing)
        # No obligation is touched by a rejection.
    return envelope.object_response(serializers.filing(filing))


@endpoint("POST", "/filings/{id}/refile", roles=["ComplianceOfficer"], success_code=201)
def refile(context):
    filing = context.row
    body = context.body
    tier = body.enum("expedite_tier", EXPEDITE_TIERS, default="NONE")
    body.check_enums()  # rung 14
    # declared gate order (PRD 2.9.1): 16, then 33, then 34
    if filing["status"] != "REJECTED":  # rung 16
        raise ApiError("ERR_INVALID_STATE")
    if filing["refile_window_end"] is None or timeutil.today() > filing["refile_window_end"]:
        raise ApiError("ERR_REFILE_WINDOW_CLOSED")  # rung 33
    if filing["attempt_number"] >= MAX_REFILE_ATTEMPTS:  # rung 34
        raise ApiError("ERR_REFILE_LIMIT_REACHED")

    # ADJUDICATION OF FRICTION 7 -- the refund-on-refile branch.  Reading:
    # DEAD PATH.  PRD 3.7 says it outright: "Because those two gates reject
    # every out-of-window and over-cap attempt outright, no refund is ever
    # produced by a refile -- the refund path is reached only by abandoning."
    # No reversal allocation is written here and credit_balance_cents does not
    # move; the refund machinery lives only on /abandon, where it stays fully
    # reachable.

    filing["status"] = "ABANDONED"
    touch(filing)

    # ADJUDICATION OF FRICTION 6 -- how the successor is priced.  Reading:
    # REUSE THE PREDECESSOR'S STORED state_fee_cents (its late fee is NOT
    # re-priced at the refile date) and re-derive only the expedite halves from
    # the successor's own tier, under the same rule version that priced the
    # predecessor.  PRD 3.7's refile paragraph enumerates exactly what the
    # successor carries and what changes -- attempt_number, prepared_by_user_id,
    # paid_amount_cents, expedite_tier, and a service_fee_cents of 0 -- and
    # never mentions the obligation being re-priced or its version moving.
    # Re-pricing would bump the obligation's version as an undeclared side
    # effect of an endpoint that takes no version field, which would make the
    # declared post-refile obligation state unreachable; reusing the stored
    # components keeps every declared figure derivable.
    rule = DB.state_rules.get(filing["_rule_id"])
    if rule is None:  # pragma: no cover - defensive
        rule = rules.select(
            DB.registrations[filing["registration_id"]]["state_code"], timeutil.today()
        )
    fees = filing_service.breakdown(filing["state_fee_cents"], 0, tier, rule)
    successor = _new_filing(
        filing["registration_id"],
        filing["compliance_obligation_id"],
        filing["good_standing_certificate_id"],
        filing["filing_kind"],
        tier,
        fees,
        context.user_id,
        filing["attempt_number"] + 1,
        rule["id"],
        filing.get("_reinstatement_case_id"),
    )
    # ADJUDICATION OF FRICTION 8 -- what the refile returns.  Reading: THE
    # SUCCESSOR DRAFT, with HTTP 201, exactly as PRD 3.7 states ("It is the
    # successor filing that is returned in the response, with HTTP 201").
    return envelope.object_response(serializers.filing(successor), 201)


@endpoint("POST", "/filings/{id}/abandon", roles=["ComplianceOfficer"], success_code=200)
def abandon(context):
    filing = context.row
    if filing["status"] != "REJECTED":  # rung 16
        raise ApiError("ERR_INVALID_STATE")
    filing["status"] = "ABANDONED"
    touch(filing)
    payment_service.compensate_abandon(filing)
    return envelope.object_response(serializers.filing(filing))


@endpoint(
    "GET",
    "/filings/{id}/payment-allocations",
    roles=["PlatformAdmin", "ComplianceOfficer", "ClientContact"],
    success_code=200,
)
def list_filing_allocations(context):
    rows = lookup.allocations_of_filing(context.row["id"])
    return listing.respond(rows, serializers.allocation)
