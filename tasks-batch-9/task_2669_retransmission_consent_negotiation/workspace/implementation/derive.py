"""Derived counters, lookups and resource serializers (PRD 2.9)."""
import calc
from errors import ApiError
from store import (
    RIGHTS_CREDIT_BP,
    RIGHTS_TERM_ORDER,
    clock,
    db,
    parse_iso,
    sort_rows,
    touch,
)


# --- lookups ----------------------------------------------------------------
def _find(table, row_id, error_id):
    row = table.get(row_id)
    if row is None:
        raise ApiError(error_id)
    return row


def get_station(station_id):
    return _find(db.stations, station_id, "ERR_STATION_NOT_FOUND")


def get_distributor(distributor_id):
    return _find(db.distributors, distributor_id, "ERR_DISTRIBUTOR_NOT_FOUND")


def get_election(election_id):
    return _find(db.elections, election_id, "ERR_ELECTION_NOT_FOUND")


def get_negotiation(negotiation_id):
    return _find(db.negotiations, negotiation_id, "ERR_NEGOTIATION_NOT_FOUND")


def get_offer(offer_id):
    return _find(db.offers, offer_id, "ERR_OFFER_NOT_FOUND")


def get_report(report_id):
    return _find(db.reports, report_id, "ERR_REPORT_NOT_FOUND")


def get_finding(finding_id):
    return _find(db.findings, finding_id, "ERR_AUDIT_FINDING_NOT_FOUND")


def get_agreement(agreement_id):
    return _find(db.agreements, agreement_id, "ERR_AGREEMENT_NOT_FOUND")


def get_dispute(dispute_id):
    return _find(db.disputes, dispute_id, "ERR_DISPUTE_NOT_FOUND")


def get_settlement(settlement_id):
    return _find(db.settlements, settlement_id, "ERR_SETTLEMENT_NOT_FOUND")


def rows_of(table, **filters):
    out = []
    for row in table.values():
        keep = True
        for key, value in filters.items():
            if row.get(key) != value:
                keep = False
                break
        if keep:
            out.append(row)
    return sort_rows(out)


# --- graph navigation ------------------------------------------------------
def election_of_negotiation(negotiation):
    return db.elections.get(negotiation["election_id"])


def negotiation_of_election(election_id):
    """Filing a RETRANS_CONSENT election creates exactly one negotiation."""
    for row in sort_rows(list(db.negotiations.values())):
        if row["election_id"] == election_id:
            return row
    return None


def negotiation_of_agreement(agreement):
    return db.negotiations.get(agreement["negotiation_id"])


def election_of_agreement(agreement):
    negotiation = negotiation_of_agreement(agreement)
    if negotiation is None:
        return None
    return election_of_negotiation(negotiation)


def slot_of_agreement(agreement):
    """(station_id, distributor_id) of the agreement's election."""
    election = election_of_agreement(agreement)
    if election is None:
        return (None, None)
    return (election["station_id"], election["distributor_id"])


def affiliations_of(station_id):
    return rows_of(db.affiliations, station_id=station_id)


def active_affiliation(station_id):
    for row in affiliations_of(station_id):
        if row["status"] == "ACTIVE":
            return row
    return None


def settlement_affiliation(station_id):
    """The affiliation consulted by the split: ACTIVE or EXPIRED, never SUSPENDED."""
    for row in affiliations_of(station_id):
        if row["status"] in ("ACTIVE", "EXPIRED"):
            return row
    return None


# --- derived counters -----------------------------------------------------
def filed_election_count(station_id):
    total = 0
    for row in db.elections.values():
        if row["station_id"] == station_id and row["status"] in (
            "NEGOTIATING", "ELECTION_EFFECTIVE", "CONSENT_GRANTED",
        ):
            total += 1
    return total


def open_true_up_count(distributor_id):
    total = 0
    for settlement in db.settlements.values():
        if not settlement.get("true_up_required"):
            continue
        if settlement["status"] != "ISSUED":
            continue
        agreement = db.agreements.get(settlement["agreement_id"])
        if agreement is None:
            continue
        if slot_of_agreement(agreement)[1] == distributor_id:
            total += 1
    return total


def offers_of(negotiation_id):
    return rows_of(db.offers, negotiation_id=negotiation_id)


def round_number(negotiation_id):
    return len(offers_of(negotiation_id))


def side_offer_count(negotiation_id, side):
    return len([o for o in offers_of(negotiation_id) if o["offered_by"] == side])


def good_faith_meeting_count(negotiation_id):
    return len([
        e for e in db.good_faith.values()
        if e["negotiation_id"] == negotiation_id and e["event_type"] == "MEETING_HELD"
    ])


def notices_of(negotiation_id):
    return rows_of(db.notices, negotiation_id=negotiation_id)


def notice_compliance_status(negotiation):
    served = [n for n in notices_of(negotiation["id"]) if n["status"] == "SERVED"]
    if served:
        return "NOTICE_SERVED"
    if negotiation["status"] != "IMPASSE":
        return "NOT_REQUIRED"
    deadline = parse_iso(negotiation.get("blackout_notice_deadline_utc"))
    if deadline is not None and clock() <= deadline:
        return "NOTICE_PENDING"
    return "NOTICE_DEFICIENT"


def findings_of(report_id):
    return rows_of(db.findings, subscriber_report_id=report_id)


def audit_adjustment_subscribers(report_id):
    total = 0
    for finding in findings_of(report_id):
        if finding["status"] == "SUBSTANTIATED":
            total += finding["adjustment_subscribers"]
    return total


def report_basis(report, include_adjustment):
    adjustment = audit_adjustment_subscribers(report["id"]) if include_adjustment else 0
    adjusted = (
        report["reported_subscriber_count"]
        - report["excluded_free_trial_count"]
        + adjustment
    )
    return adjusted, calc.subscriber_basis(adjusted, report["measurement_method_snapshot"])


def extensions_of(agreement_id):
    return rows_of(db.extensions, agreement_id=agreement_id)


def consumed_extension_days(agreement_id):
    total = 0
    for row in extensions_of(agreement_id):
        if row["status"] in ("ACTIVE", "LAPSED"):
            total += row["extension_days"]
    return total


def disputes_of(agreement_id):
    return rows_of(db.disputes, agreement_id=agreement_id)


def excluded_dispute_terms(agreement_id):
    return [
        d["disputed_term"] for d in disputes_of(agreement_id)
        if d["status"] == "RESOLVED_EXCLUDED"
    ]


def rights_credit_bp_total(agreement_id):
    total = 0
    for dispute in disputes_of(agreement_id):
        if dispute["status"] == "RESOLVED_EXCLUDED":
            total += dispute["credit_bp_applied"]
    return total


def settlements_of(agreement_id):
    return rows_of(db.settlements, agreement_id=agreement_id)


def lifetime_totals(agreement_id):
    gross = 0
    net = 0
    for row in settlements_of(agreement_id):
        if row["status"] in ("ISSUED", "TRUED_UP"):
            gross += row["gross_fee_cents"]
            net += row["net_retained_cents"]
    return gross, net


# --- settlement recomputation (calculation reverse_compensation_split) -----
def recompute_settlement(settlement):
    agreement = db.agreements.get(settlement["agreement_id"])
    election = election_of_agreement(agreement) if agreement else None
    station_id = election["station_id"] if election else None
    distributor = db.distributors.get(election["distributor_id"]) if election else None
    offer = db.offers.get(agreement["accepted_offer_id"]) if agreement else None
    affiliation = settlement_affiliation(station_id) if station_id else None

    premium_bp = affiliation["split_premium_bp"] if affiliation else 0
    floor_cents = affiliation["reverse_comp_floor_per_sub_cents"] if affiliation else 0
    video_households = distributor["video_household_count"] if distributor else 1
    commitment_bp = offer["penetration_commitment_bp"] if offer else 0

    amounts = calc.reverse_compensation_split(
        settlement["rate_per_sub_cents"],
        settlement["billable_subscriber_basis_snapshot"],
        excluded_dispute_terms(settlement["agreement_id"]),
        premium_bp,
        floor_cents,
        video_households,
        commitment_bp,
    )
    settlement.update(amounts)
    return settlement


# --- serializers ----------------------------------------------------------
def _public(row, keys):
    return {key: row.get(key) for key in keys}


STATION_KEYS = [
    "id", "created_at", "updated_at", "version", "call_sign", "market_code",
    "dma_rank", "market_tv_households", "network_affiliation",
]


def station_json(row):
    out = _public(row, STATION_KEYS)
    out["filed_election_count"] = filed_election_count(row["id"])
    return out


AFFILIATION_KEYS = [
    "id", "created_at", "updated_at", "version", "station_id", "network_name",
    "term_end_utc", "reverse_comp_floor_per_sub_cents", "split_premium_bp",
    "digital_rights_grantable", "ooh_rights_grantable", "streaming_rights_grantable",
    "permitted_tiers", "status",
]


def affiliation_json(row):
    return _public(row, AFFILIATION_KEYS)


DISTRIBUTOR_KEYS = [
    "id", "created_at", "updated_at", "version", "name", "distributor_type",
    "subscriber_measurement_method", "video_household_count",
    "required_blackout_notice_days",
]


def distributor_json(row):
    out = _public(row, DISTRIBUTOR_KEYS)
    out["open_true_up_count"] = open_true_up_count(row["id"])
    return out


ELECTION_KEYS = [
    "id", "created_at", "updated_at", "version", "station_id", "distributor_id",
    "cycle_label", "election_type", "requested_tier", "incumbent_expiry_utc",
    "incumbent_rate_per_sub_cents", "status", "filed_at_utc", "withdrawal_reason",
]


def election_json(row):
    return _public(row, ELECTION_KEYS)


NEGOTIATION_KEYS = [
    "id", "created_at", "updated_at", "version", "election_id", "status",
    "impasse_declared_at_utc", "blackout_notice_deadline_utc",
]


def negotiation_json(row):
    out = _public(row, NEGOTIATION_KEYS)
    out["round_number"] = round_number(row["id"])
    out["station_offer_count"] = side_offer_count(row["id"], "STATION_GROUP")
    out["distributor_offer_count"] = side_offer_count(row["id"], "DISTRIBUTOR")
    out["good_faith_meeting_count"] = good_faith_meeting_count(row["id"])
    out["notice_compliance_status"] = notice_compliance_status(row)
    return out


OFFER_KEYS = [
    "id", "created_at", "updated_at", "version", "negotiation_id", "offered_by",
    "round_number", "base_rate_per_sub_cents", "escalator_bp_per_year",
    "term_months", "tier", "penetration_commitment_bp", "includes_digital_rights",
    "includes_ooh_rights", "includes_streaming_rights", "subscriber_report_id",
    "projection_basis_subscribers", "year_rate_schedule_compound_cents",
    "projected_total_fee_cents", "status", "rejection_reason",
]


def offer_json(row):
    return _public(row, OFFER_KEYS)


GOOD_FAITH_KEYS = [
    "id", "created_at", "negotiation_id", "event_type", "occurred_at_utc",
    "summary", "actor_role", "sequence_index",
]


def good_faith_json(row):
    return _public(row, GOOD_FAITH_KEYS)


REPORT_KEYS = [
    "id", "created_at", "updated_at", "version", "station_id", "distributor_id",
    "period_label", "period_start_utc", "period_end_utc",
    "reported_subscriber_count", "excluded_free_trial_count",
    "measurement_method_snapshot", "status",
]


def report_json(row):
    out = _public(row, REPORT_KEYS)
    adjustment = audit_adjustment_subscribers(row["id"])
    adjusted, audited_basis = report_basis(row, True)
    _, as_reported = report_basis(row, False)
    out["audit_adjustment_subscribers"] = adjustment
    out["adjusted_subscriber_count"] = adjusted
    out["billable_subscriber_basis"] = audited_basis
    out["as_reported_basis"] = as_reported
    return out


FINDING_KEYS = [
    "id", "created_at", "updated_at", "version", "subscriber_report_id",
    "adjustment_subscribers", "basis_note", "status", "resolution_note",
    "opened_at_utc",
]


def finding_json(row):
    return _public(row, FINDING_KEYS)


AGREEMENT_KEYS = [
    "id", "created_at", "updated_at", "version", "negotiation_id",
    "accepted_offer_id", "effective_start_utc", "effective_end_utc",
    "execution_status", "network_approval_status", "accepted_by_user_id",
    "executed_by_user_id", "granted_rights_scope",
    "contract_year_rate_schedule_cents", "decision_note",
]


def agreement_json(row):
    out = _public(row, AGREEMENT_KEYS)
    out["rights_credit_bp_total"] = rights_credit_bp_total(row["id"])
    out["consumed_extension_days"] = consumed_extension_days(row["id"])
    gross, net = lifetime_totals(row["id"])
    out["lifetime_gross_fee_cents"] = gross
    out["lifetime_net_retained_cents"] = net
    ladder = row.get("contract_year_rate_schedule_cents") or []
    start = parse_iso(row.get("effective_start_utc"))
    current = None
    if ladder and start is not None:
        index = calc.contract_year_index(clock(), start)
        index = max(1, min(index, len(ladder)))
        current = ladder[index - 1]
    out["current_year_rate_per_sub_cents"] = current
    return out


EXTENSION_KEYS = [
    "id", "created_at", "updated_at", "version", "agreement_id", "extension_days",
    "extension_start_utc", "extension_end_utc", "extension_rate_basis",
    "effective_rate_per_sub_cents", "status",
]


def extension_json(row):
    return _public(row, EXTENSION_KEYS)


DISPUTE_KEYS = [
    "id", "created_at", "updated_at", "version", "agreement_id", "disputed_term",
    "claimed_definition", "raised_by", "status", "credit_bp_applied",
    "resolution_note",
]


def dispute_json(row):
    return _public(row, DISPUTE_KEYS)


NOTICE_KEYS = [
    "id", "created_at", "updated_at", "version", "negotiation_id",
    "subscriber_notice_count", "notice_channel", "served_at_utc",
    "required_notice_days_snapshot", "status",
]


def notice_json(row):
    return _public(row, NOTICE_KEYS)


SETTLEMENT_KEYS = [
    "id", "created_at", "updated_at", "version", "agreement_id",
    "subscriber_report_id", "period_label", "period_start_utc", "period_end_utc",
    "contract_year_index", "rate_per_sub_cents", "basis_variant",
    "billable_subscriber_basis_snapshot", "gross_fee_cents", "rights_credit_cents",
    "reverse_comp_split_bp", "reverse_comp_cents", "actual_penetration_bp",
    "penetration_shortfall_bp", "penetration_penalty_cents", "net_retained_cents",
    "true_up_required", "issued_by_user_id", "status",
]


def settlement_json(row):
    return _public(row, SETTLEMENT_KEYS)
