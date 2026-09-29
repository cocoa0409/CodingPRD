"""Carriage agreements, network approval, execution and the fee projection
(PRD 3.7)."""
from flask import Blueprint

import calc
import derive
from common import (
    authenticate,
    body_json,
    pagination,
    paginate,
    query_enum,
    query_str,
    take_dt,
    take_enum,
    take_int,
    take_str,
)
from envelope import array_response, object_response
from errors import ApiError
from store import (
    ALL_ROLES,
    MAX_CUMULATIVE_EXTENSION_DAYS,
    NO_DISTRIBUTOR_ROLES,
    RIGHTS_CREDIT_BP,
    add_days,
    base_row,
    clock,
    db,
    fmt_dt,
    now_iso,
    parse_iso,
    sort_rows,
    touch,
)

bp = Blueprint("agreements", __name__)

EXECUTION_STATUSES = ["PENDING_EXECUTION", "EXECUTED", "EXPIRED"]
NETWORK_STATUSES = ["NOT_REQUIRED", "PENDING_NETWORK", "NETWORK_APPROVED", "NETWORK_REJECTED"]

GRANTABLE_FLAG = {
    "DIGITAL": "digital_rights_grantable",
    "OUT_OF_HOME": "ooh_rights_grantable",
    "STREAMING": "streaming_rights_grantable",
}


@bp.get("/retrans/agreements")
def list_agreements():
    authenticate(ALL_ROLES)
    limit, offset = pagination()
    negotiation_id = query_str("negotiation_id")
    accepted_offer_id = query_str("accepted_offer_id")
    execution_status = query_enum("execution_status", EXECUTION_STATUSES)
    network_status = query_enum("network_approval_status", NETWORK_STATUSES)
    rows = derive.rows_of(db.agreements)
    if negotiation_id is not None:
        rows = [r for r in rows if r["negotiation_id"] == negotiation_id]
    if accepted_offer_id is not None:
        rows = [r for r in rows if r["accepted_offer_id"] == accepted_offer_id]
    if execution_status is not None:
        rows = [r for r in rows if r["execution_status"] == execution_status]
    if network_status is not None:
        rows = [r for r in rows if r["network_approval_status"] == network_status]
    items, total = paginate(rows, limit, offset, derive.agreement_json)
    return array_response(items, limit, offset, total)


@bp.get("/retrans/agreements/<agreement_id>")
def read_agreement(agreement_id):
    authenticate(ALL_ROLES)
    agreement = derive.get_agreement(agreement_id)
    return object_response(derive.agreement_json(agreement))


@bp.post("/retrans/agreements/<agreement_id>/network-approval")
def network_approval(agreement_id):
    authenticate(["NetworkRepresentative"])
    body = body_json()
    decision = take_enum(body, "decision", ["APPROVE", "REJECT"])
    note = take_str(body, "decision_note", min_len=1)
    agreement = derive.get_agreement(agreement_id)
    # Priority 12 -- the network decision needs PENDING_EXECUTION and a
    # network dimension still sitting at PENDING_NETWORK.
    if (agreement["execution_status"] != "PENDING_EXECUTION"
            or agreement["network_approval_status"] != "PENDING_NETWORK"):
        raise ApiError("ERR_AGREEMENT_NOT_PENDING_EXECUTION")

    if decision == "APPROVE":
        affiliation = derive.active_affiliation(derive.slot_of_agreement(agreement)[0])
        # Priority 25 -- the granted scope must be a subset of what is grantable.
        for term in agreement["granted_rights_scope"]:
            if affiliation is None or not affiliation[GRANTABLE_FLAG[term]]:
                raise ApiError("ERR_RIGHTS_NOT_GRANTABLE")
        # Priority 26 -- the station must hold an ACTIVE affiliation.
        if affiliation is None:
            raise ApiError("ERR_AFFILIATION_NOT_ACTIVE")
        agreement["network_approval_status"] = "NETWORK_APPROVED"
    else:
        agreement["network_approval_status"] = "NETWORK_REJECTED"
    agreement["decision_note"] = note
    touch(agreement)
    return object_response(derive.agreement_json(agreement))


@bp.post("/retrans/agreements/<agreement_id>/execute")
def execute_agreement(agreement_id):
    user_id, _role = authenticate(["GroupCounsel"])
    body = body_json()
    take_str(body, "execution_note", min_len=1)
    agreement = derive.get_agreement(agreement_id)
    # Priority 7 -- the counsel who bound the group may not also sign for it.
    if user_id == agreement["accepted_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    # Priority 12 -- execution requires PENDING_EXECUTION.
    if agreement["execution_status"] != "PENDING_EXECUTION":
        raise ApiError("ERR_AGREEMENT_NOT_PENDING_EXECUTION")
    station_id, distributor_id = derive.slot_of_agreement(agreement)
    # Priority 26 -- the station must hold an ACTIVE affiliation right now.
    if derive.active_affiliation(station_id) is None:
        raise ApiError("ERR_AFFILIATION_NOT_ACTIVE")
    # Priority 27 -- PENDING_NETWORK and NETWORK_REJECTED both block execution.
    if agreement["network_approval_status"] not in ("NOT_REQUIRED", "NETWORK_APPROVED"):
        raise ApiError("ERR_NETWORK_APPROVAL_PENDING")

    agreement["execution_status"] = "EXECUTED"
    agreement["executed_by_user_id"] = user_id
    touch(agreement)

    # Cascade: ACTIVE extensions on OTHER agreements of the same slot whose
    # closed window intersects this half-open term move to SUPERSEDED.
    term_start = parse_iso(agreement["effective_start_utc"])
    term_end = parse_iso(agreement["effective_end_utc"])
    affected = []
    for other in sort_rows(list(db.agreements.values())):
        if other["id"] == agreement["id"]:
            continue
        if derive.slot_of_agreement(other) != (station_id, distributor_id):
            continue
        superseded_any = False
        for extension in derive.extensions_of(other["id"]):
            if extension["status"] != "ACTIVE":
                continue
            ext_start = parse_iso(extension["extension_start_utc"])
            ext_end = parse_iso(extension["extension_end_utc"])
            if ext_start is None or ext_end is None:
                continue
            if ext_start < term_end and ext_end >= term_start:
                extension["status"] = "SUPERSEDED"
                touch(extension)
                superseded_any = True
        if superseded_any:
            affected.append(other)
    for other in affected:
        # consumed_extension_days is re-derived; the row still records the write.
        touch(other)
    return object_response(derive.agreement_json(agreement))


@bp.get("/retrans/agreements/<agreement_id>/fee-projection")
def fee_projection(agreement_id):
    authenticate(ALL_ROLES)
    agreement = derive.get_agreement(agreement_id)
    offer = db.offers.get(agreement["accepted_offer_id"])
    base_rate = offer["base_rate_per_sub_cents"]
    escalator = offer["escalator_bp_per_year"]
    term_months = offer["term_months"]
    basis = offer["projection_basis_subscribers"]
    compound = calc.compound_annual_ladder(base_rate, escalator, term_months)
    simple = calc.simple_annual_ladder(base_rate, escalator, term_months)
    compound_total = calc.whole_term_total_fee(compound, basis, term_months)
    simple_total = calc.whole_term_total_fee(simple, basis, term_months)
    return object_response({
        "compound_total_fee_cents": compound_total,
        "simple_total_fee_cents": simple_total,
        "divergence_cents": compound_total - simple_total,
        "year_rate_schedule_compound_cents": compound,
        "year_rate_schedule_simple_cents": simple,
    })


def _last_station_offer_rate(negotiation_id):
    """Every station offer ever tabled, ranked by round_number desc then
    creation timestamp desc; None when the candidate set is empty."""
    candidates = [
        offer for offer in derive.offers_of(negotiation_id)
        if offer["offered_by"] == "STATION_GROUP"
        and offer["status"] in ("SUBMITTED", "ACCEPTED", "REJECTED", "EXPIRED")
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda row: (row["round_number"], row["_seq"]), reverse=True)
    return candidates[0]["base_rate_per_sub_cents"]


@bp.post("/retrans/agreements/<agreement_id>/interim-extensions")
def create_extension(agreement_id):
    user_id, _role = authenticate(["StationGroupNegotiator"])
    body = body_json()
    expected_version = take_int(body, "expected_agreement_version")
    extension_days = take_int(body, "extension_days", minimum=1, maximum=90)
    extension_start = take_dt(body, "extension_start_utc")
    basis_kind = take_enum(body, "extension_rate_basis",
                           ["PRIOR_RATE", "LAST_STATION_OFFER", "MIDPOINT"])
    agreement = derive.get_agreement(agreement_id)
    station_id, _distributor_id = derive.slot_of_agreement(agreement)
    # Priority 6 -- the negotiator must be the station on the agreement's slot.
    if user_id != station_id:
        raise ApiError("ERR_NOT_COUNTERPARTY")
    # Priority 12 -- an extension only hangs off an EXECUTED agreement.
    if agreement["execution_status"] != "EXECUTED":
        raise ApiError("ERR_AGREEMENT_NOT_PENDING_EXECUTION")

    negotiation = derive.negotiation_of_agreement(agreement)
    election = derive.election_of_agreement(agreement)
    prior_rate = election["incumbent_rate_per_sub_cents"]
    last_rate = _last_station_offer_rate(negotiation["id"])
    # Priority 18 -- PRIOR_RATE never touches the offer pool.
    if basis_kind in ("LAST_STATION_OFFER", "MIDPOINT") and last_rate is None:
        raise ApiError("ERR_NO_STATION_OFFER_ON_RECORD")

    extension_end = add_days(extension_start, extension_days)
    # Priority 32 -- extension windows are CLOSED at both endpoints.
    for other in derive.extensions_of(agreement_id):
        if other["status"] not in ("ACTIVE", "LAPSED"):
            continue
        other_start = parse_iso(other["extension_start_utc"])
        other_end = parse_iso(other["extension_end_utc"])
        if other_start is None or other_end is None:
            continue
        if extension_start <= other_end and other_start <= extension_end:
            raise ApiError("ERR_EXTENSION_WINDOW_OVERLAP")

    # Priority 34 -- landing exactly on 90 days is permitted.
    if derive.consumed_extension_days(agreement_id) + extension_days > MAX_CUMULATIVE_EXTENSION_DAYS:
        raise ApiError("ERR_EXTENSION_BUDGET_EXCEEDED")

    # Priority 39 -- the staleness guard sits last.
    if expected_version != agreement["version"]:
        raise ApiError("ERR_STALE_AGREEMENT_VERSION")

    row = base_row()
    row.update({
        "agreement_id": agreement_id,
        "extension_days": extension_days,
        "extension_start_utc": fmt_dt(extension_start),
        "extension_end_utc": fmt_dt(extension_end),
        "extension_rate_basis": basis_kind,
        "effective_rate_per_sub_cents": calc.interim_extension_rate(
            basis_kind, prior_rate, last_rate if last_rate is not None else 0
        ),
        "status": "ACTIVE",
    })
    db.extensions[row["id"]] = row
    # Creating an extension pushes the agreement's effective term end forward.
    current_end = parse_iso(agreement["effective_end_utc"])
    agreement["effective_end_utc"] = fmt_dt(add_days(current_end, extension_days))
    touch(agreement)
    return object_response(derive.extension_json(row), 201)


@bp.get("/retrans/agreements/<agreement_id>/interim-extensions")
def list_extensions(agreement_id):
    authenticate(ALL_ROLES)
    limit, offset = pagination()
    status = query_enum("status", ["ACTIVE", "LAPSED", "SUPERSEDED"])
    derive.get_agreement(agreement_id)
    rows = derive.extensions_of(agreement_id)
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    items, total = paginate(rows, limit, offset, derive.extension_json)
    return array_response(items, limit, offset, total)


DISPUTE_TERMS = ["DIGITAL", "OUT_OF_HOME", "STREAMING"]
DISPUTE_STATUSES = ["RAISED", "IN_MEDIATION", "RESOLVED_INCLUDED", "RESOLVED_EXCLUDED"]


@bp.post("/retrans/agreements/<agreement_id>/rights-disputes")
def create_dispute(agreement_id):
    user_id, role = authenticate(["StationGroupNegotiator", "DistributorRep"])
    body = body_json()
    disputed_term = take_enum(body, "disputed_term", DISPUTE_TERMS)
    claimed = take_str(body, "claimed_definition", min_len=1, max_len=500)
    agreement = derive.get_agreement(agreement_id)
    station_id, distributor_id = derive.slot_of_agreement(agreement)
    # Priority 6 -- the raising party must be the counterparty it claims to be.
    if role == "StationGroupNegotiator":
        raised_by = "STATION_GROUP"
        if user_id != station_id:
            raise ApiError("ERR_NOT_COUNTERPARTY")
    else:
        raised_by = "DISTRIBUTOR"
        if user_id != distributor_id:
            raise ApiError("ERR_NOT_COUNTERPARTY")
    # Priority 12 -- only an EXECUTED agreement can come apart on rights.
    if agreement["execution_status"] != "EXECUTED":
        raise ApiError("ERR_AGREEMENT_NOT_PENDING_EXECUTION")
    # Priority 37 -- a dispute may only contest a right that was granted.
    if disputed_term not in (agreement["granted_rights_scope"] or []):
        raise ApiError("ERR_TERM_NOT_IN_GRANT")

    row = base_row()
    row.update({
        "agreement_id": agreement_id,
        "disputed_term": disputed_term,
        "claimed_definition": claimed,
        "raised_by": raised_by,
        "status": "RAISED",
        "credit_bp_applied": 0,
        "resolution_note": None,
    })
    db.disputes[row["id"]] = row
    return object_response(derive.dispute_json(row), 201)


@bp.get("/retrans/agreements/<agreement_id>/rights-disputes")
def list_disputes(agreement_id):
    authenticate(ALL_ROLES)
    limit, offset = pagination()
    status = query_enum("status", DISPUTE_STATUSES)
    disputed_term = query_enum("disputed_term", DISPUTE_TERMS)
    derive.get_agreement(agreement_id)
    rows = derive.disputes_of(agreement_id)
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if disputed_term is not None:
        rows = [r for r in rows if r["disputed_term"] == disputed_term]
    items, total = paginate(rows, limit, offset, derive.dispute_json)
    return array_response(items, limit, offset, total)


@bp.post("/retrans/rights-disputes/<dispute_id>/resolve")
def resolve_dispute(dispute_id):
    authenticate(["ComplianceOfficer"])
    body = body_json()
    resolution = take_enum(body, "resolution", ["MEDIATION", "INCLUDED", "EXCLUDED"])
    note = take_str(body, "resolution_note", min_len=1)
    dispute = derive.get_dispute(dispute_id)
    # Priority 15 -- an already-resolved dispute accepts nothing further.
    if dispute["status"] not in ("RAISED", "IN_MEDIATION"):
        raise ApiError("ERR_DISPUTE_NOT_PENDING")

    dispute["resolution_note"] = note
    if resolution == "MEDIATION":
        dispute["status"] = "IN_MEDIATION"
        touch(dispute)
        return object_response(derive.dispute_json(dispute))
    if resolution == "INCLUDED":
        dispute["status"] = "RESOLVED_INCLUDED"
        touch(dispute)
        return object_response(derive.dispute_json(dispute))

    # EXCLUDED -- four levels of cascade.
    agreement = db.agreements[dispute["agreement_id"]]
    dispute["status"] = "RESOLVED_EXCLUDED"
    dispute["credit_bp_applied"] = RIGHTS_CREDIT_BP[dispute["disputed_term"]]
    touch(dispute)
    # Level 2 -- the term leaves the grant and rights_credit_bp_total re-derives.
    agreement["granted_rights_scope"] = [
        term for term in (agreement["granted_rights_scope"] or [])
        if term != dispute["disputed_term"]
    ]
    touch(agreement)
    # Level 3 -- ISSUED settlements re-price in creation-timestamp ASC order.
    for settlement in derive.settlements_of(agreement["id"]):
        if settlement["status"] != "ISSUED":
            continue
        derive.recompute_settlement(settlement)
        touch(settlement)
    # Level 4 -- the agreement's lifetime ledger re-derives from those rows on
    # read; the agreement's own version moved once, at level 2.
    return object_response(derive.dispute_json(dispute))


SETTLEMENT_STATUSES = ["ISSUED", "TRUED_UP", "VOIDED"]
BASIS_VARIANTS = ["AS_REPORTED", "AUDITED"]
PRICEABLE_STATUSES = ("REPORTED", "UNDER_AUDIT", "ADJUSTED", "ACCEPTED")


@bp.post("/retrans/agreements/<agreement_id>/fee-settlements")
def issue_settlement(agreement_id):
    user_id, _role = authenticate(["GroupCounsel"])
    body = body_json()
    period_label = take_str(body, "period_label", min_len=1, max_len=20)
    period_start = take_dt(body, "period_start_utc")
    period_end = take_dt(body, "period_end_utc")
    if period_end <= period_start:
        raise ApiError("ERR_INVALID_REQUEST",
                       "Field 'period_end_utc' must be strictly after 'period_start_utc'.")
    report_id = take_str(body, "subscriber_report_id")
    agreement = derive.get_agreement(agreement_id)
    report = derive.get_report(report_id)
    # Priority 12 -- money only moves under an EXECUTED agreement.
    if agreement["execution_status"] != "EXECUTED":
        raise ApiError("ERR_AGREEMENT_NOT_PENDING_EXECUTION")
    # Priority 30 -- period_label is unique per agreement.
    for other in derive.settlements_of(agreement_id):
        if other["period_label"] == period_label:
            raise ApiError("ERR_REPORT_PERIOD_DUPLICATE")
    station_id, distributor_id = derive.slot_of_agreement(agreement)
    # Priority 35 -- the report must be this pair's and priceable.
    if (report["station_id"] != station_id
            or report["distributor_id"] != distributor_id
            or report["status"] not in PRICEABLE_STATUSES):
        raise ApiError("ERR_REPORT_NOT_PRICEABLE")

    ladder = agreement["contract_year_rate_schedule_cents"] or []
    year_index = calc.contract_year_index(period_start, parse_iso(agreement["effective_start_utc"]))
    clamped = max(1, min(year_index, len(ladder))) if ladder else 1
    rate = ladder[clamped - 1] if ladder else 0
    _adjusted, as_reported = derive.report_basis(report, False)

    row = base_row()
    row.update({
        "agreement_id": agreement_id,
        "subscriber_report_id": report_id,
        "period_label": period_label,
        "period_start_utc": fmt_dt(period_start),
        "period_end_utc": fmt_dt(period_end),
        "contract_year_index": year_index,
        "rate_per_sub_cents": rate,
        "basis_variant": "AS_REPORTED",
        "billable_subscriber_basis_snapshot": as_reported,
        "true_up_required": False,
        "issued_by_user_id": user_id,
        "status": "ISSUED",
    })
    db.settlements[row["id"]] = row
    derive.recompute_settlement(row)
    # Issuance adds the amounts into the parent agreement's ledger.
    touch(agreement)
    return object_response(derive.settlement_json(row), 201)


@bp.get("/retrans/agreements/<agreement_id>/fee-settlements")
def list_agreement_settlements(agreement_id):
    authenticate(NO_DISTRIBUTOR_ROLES)
    limit, offset = pagination()
    status = query_enum("status", SETTLEMENT_STATUSES)
    basis_variant = query_enum("basis_variant", BASIS_VARIANTS)
    period_label = query_str("period_label")
    derive.get_agreement(agreement_id)
    rows = derive.settlements_of(agreement_id)
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if basis_variant is not None:
        rows = [r for r in rows if r["basis_variant"] == basis_variant]
    if period_label is not None:
        rows = [r for r in rows if r["period_label"] == period_label]
    items, total = paginate(rows, limit, offset, derive.settlement_json)
    return array_response(items, limit, offset, total)


@bp.post("/retrans/fee-settlements/<settlement_id>/true-up")
def true_up_settlement(settlement_id):
    authenticate(["GroupCounsel"])
    body = body_json()
    take_str(body, "true_up_note", min_len=1)
    settlement = derive.get_settlement(settlement_id)
    # Priority 16 -- true-up requires ISSUED and happens at most once.
    if settlement["status"] != "ISSUED":
        raise ApiError("ERR_SETTLEMENT_NOT_ISSUED")
    report = db.reports.get(settlement["subscriber_report_id"])
    # Priority 19 -- an unadjusted report has nothing to true up.
    if report is None or derive.audit_adjustment_subscribers(report["id"]) == 0:
        raise ApiError("ERR_TRUE_UP_NOT_REQUIRED")

    _adjusted, audited = derive.report_basis(report, True)
    settlement["status"] = "TRUED_UP"
    settlement["basis_variant"] = "AUDITED"
    settlement["billable_subscriber_basis_snapshot"] = audited
    derive.recompute_settlement(settlement)
    settlement["true_up_required"] = False
    touch(settlement)
    agreement = db.agreements.get(settlement["agreement_id"])
    if agreement is not None:
        touch(agreement)
    distributor = db.distributors.get(report["distributor_id"])
    if distributor is not None:
        touch(distributor)
    return object_response(derive.settlement_json(settlement))


@bp.post("/retrans/fee-settlements/<settlement_id>/void")
def void_settlement(settlement_id):
    user_id, _role = authenticate(["GroupCounsel"])
    body = body_json()
    take_str(body, "void_reason", min_len=1)
    settlement = derive.get_settlement(settlement_id)
    # Priority 7 -- the issuing counsel may not void its own settlement.
    if user_id == settlement["issued_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    # Priority 16 -- a VOIDED settlement accepts neither true-up nor a second void.
    if settlement["status"] not in ("ISSUED", "TRUED_UP"):
        raise ApiError("ERR_SETTLEMENT_NOT_ISSUED")

    settlement["status"] = "VOIDED"
    touch(settlement)
    agreement = db.agreements.get(settlement["agreement_id"])
    if agreement is not None:
        touch(agreement)
    report = db.reports.get(settlement["subscriber_report_id"])
    if report is not None:
        distributor = db.distributors.get(report["distributor_id"])
        if distributor is not None:
            touch(distributor)
    return object_response(derive.settlement_json(settlement))
