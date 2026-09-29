"""Response shapes for every entity."""
from core import clock_date_str, db
import pricing


def _common(record, out):
    out["id"] = record["id"]
    out["created_at"] = record["created_at"]
    out["updated_at"] = record["updated_at"]
    out["version"] = record["version"]
    return out


def station_counters(station):
    station_id = station["id"]
    pending = 0
    overdue = 0
    late = 0
    for entry in db.tables["file_entry"].values():
        if entry["station_id"] != station_id:
            continue
        if entry["posting_status"] == "PENDING":
            pending += 1
        elif entry["posting_status"] == "OVERDUE":
            overdue += 1
        elif entry["posting_status"] == "LATE_POSTED":
            late += 1
    open_complaints = 0
    for complaint in db.tables["complaint"].values():
        if complaint["station_id"] == station_id and complaint["status"] in ("OPEN", "REOPENED"):
            open_complaints += 1
    return pending, overdue, late, open_complaints


def station_posture(station):
    _pending, overdue, _late, open_complaints = station_counters(station)
    return pricing.compliance_posture(overdue, open_complaints)


def serialize_station(station):
    pending, overdue, late, open_complaints = station_counters(station)
    out = {
        "call_sign": station["call_sign"],
        "licensee_name": station["licensee_name"],
        "market_code": station["market_code"],
        "political_file_posting_deadline_hours": station["political_file_posting_deadline_hours"],
        "daily_political_seconds_cap": station["daily_political_seconds_cap"],
        "eo_parity_basis": station["eo_parity_basis"],
        "pending_file_entry_count": pending,
        "overdue_file_entry_count": overdue,
        "late_posting_count": late,
        "open_complaint_count": open_complaints,
        "compliance_posture": pricing.compliance_posture(overdue, open_complaints),
        "last_sweep_at": station["last_sweep_at"],
    }
    return _common(station, out)


def election_status(election):
    today = clock_date_str()
    if today < election["window_start_date"]:
        return "SCHEDULED"
    if today <= election["window_end_date"]:
        return "WINDOW_OPEN"
    return "CLOSED"


def serialize_election(election):
    out = {
        "station_id": election["station_id"],
        "office_sought": election["office_sought"],
        "election_type": election["election_type"],
        "election_date": election["election_date"],
        "luc_window_days": election["luc_window_days"],
        "window_start_date": election["window_start_date"],
        "window_end_date": election["window_end_date"],
        "status": election_status(election),
    }
    return _common(election, out)


def serialize_advertiser(advertiser):
    out = {
        "station_id": advertiser["station_id"],
        "election_id": advertiser["election_id"],
        "legal_name": advertiser["legal_name"],
        "requested_class": advertiser["requested_class"],
        "candidate_name": advertiser["candidate_name"],
        "office_sought": advertiser["office_sought"],
        "qualification_evidence_ref": advertiser["qualification_evidence_ref"],
        "status": advertiser["status"],
        "review_round": advertiser["review_round"],
        "entitled_to_luc": advertiser["status"] == "CLASSIFIED_CANDIDATE",
        "classified_by_user_id": advertiser["classified_by_user_id"],
        "classification_reason": advertiser["classification_reason"],
    }
    return _common(advertiser, out)


def serialize_rate_class(rate_class):
    out = {
        "station_id": rate_class["station_id"],
        "class_code": rate_class["class_code"],
        "daypart": rate_class["daypart"],
        "preemptible": rate_class["preemptible"],
        "preemption_priority": rate_class["preemption_priority"],
        "posted_rate_cents": rate_class["posted_rate_cents"],
        "status": rate_class["status"],
    }
    return _common(rate_class, out)


def serialize_order(order):
    out = {
        "station_id": order["station_id"],
        "advertiser_id": order["advertiser_id"],
        "election_id": order["election_id"],
        "rate_class_id": order["rate_class_id"],
        "payment_terms": order["payment_terms"],
        "agency_placed": order["agency_placed"],
        "sponsorship_disclosure_text": order["sponsorship_disclosure_text"],
        "disclosure_duration_seconds": order["disclosure_duration_seconds"],
        "disclosure_status": order["disclosure_status"],
        "status": order["status"],
        "payment_status": order["payment_status"],
        "spot_count": order["spot_count"],
        "gross_charge_cents": order["gross_charge_cents"],
        "agency_commission_cents": order["agency_commission_cents"],
        "net_due_cents": order["net_due_cents"],
        "rebate_total_cents": order["rebate_total_cents"],
        "paid_cents": order["paid_cents"],
        "refunded_cents": order["refunded_cents"],
        "accepted_at": order["accepted_at"],
        "accepted_by_user_id": order["accepted_by_user_id"],
        "payment_due_at": order["payment_due_at"],
        "first_air_at": order["first_air_at"],
        "rejection_reason": order["rejection_reason"],
    }
    return _common(order, out)


def serialize_spot(spot):
    out = {
        "order_id": spot["order_id"],
        "rate_class_id": spot["rate_class_id"],
        "air_date": spot["air_date"],
        "start_offset_seconds": spot["start_offset_seconds"],
        "duration_seconds": spot["duration_seconds"],
        "program_code": spot["program_code"],
        "status": spot["status"],
        "charged_rate_cents": spot["charged_rate_cents"],
        "unit_equivalent_rate_cents": spot["unit_equivalent_rate_cents"],
        "luc_capped": spot["luc_capped"],
        "luc_cap_cents": spot["luc_cap_cents"],
        "aired_at": spot["aired_at"],
        "preemption_reason": spot["preemption_reason"],
    }
    return _common(spot, out)


def serialize_file_entry(entry):
    out = {
        "station_id": entry["station_id"],
        "order_id": entry["order_id"],
        "event_type": entry["event_type"],
        "event_occurred_at": entry["event_occurred_at"],
        "due_at": entry["due_at"],
        "posted_at": entry["posted_at"],
        "posting_status": entry["posting_status"],
        "late_by_seconds": entry["late_by_seconds"],
        "public_file_url": entry["public_file_url"],
        "disclosure_snapshot": entry["disclosure_snapshot"],
    }
    return _common(entry, out)


def serialize_eo_request(eo):
    out = {
        "station_id": eo["station_id"],
        "election_id": eo["election_id"],
        "requesting_advertiser_id": eo["requesting_advertiser_id"],
        "trigger_order_id": eo["trigger_order_id"],
        "granted_order_id": eo["granted_order_id"],
        "received_at": eo["received_at"],
        "response_due_at": eo["response_due_at"],
        "status": eo["status"],
        "owed_units": eo["owed_units"],
        "fulfilled_units": eo["fulfilled_units"],
        "parity_basis_applied": eo["parity_basis_applied"],
        "denial_reason": eo["denial_reason"],
        "responded_at": eo["responded_at"],
    }
    return _common(eo, out)


def serialize_luc_determination(det):
    out = {
        "station_id": det["station_id"],
        "election_id": det["election_id"],
        "rate_class_id": det["rate_class_id"],
        "basis_spot_id": det["basis_spot_id"],
        "variant": det["variant"],
        "luc_cents": det["luc_cents"],
        "basis": det["basis"],
        "qualifying_spot_count": det["qualifying_spot_count"],
        "window_start_date": det["window_start_date"],
        "window_end_date": det["window_end_date"],
        "status": det["status"],
        "computed_at": det["computed_at"],
        "repriced_spot_count": det["repriced_spot_count"],
        "rebate_total_cents": det["rebate_total_cents"],
    }
    return _common(det, out)


def serialize_rebate(rebate):
    return {
        "id": rebate["id"],
        "order_id": rebate["order_id"],
        "luc_determination_id": rebate["luc_determination_id"],
        "amount_cents": rebate["amount_cents"],
        "reason": rebate["reason"],
        "occurred_at": rebate["occurred_at"],
        "created_at": rebate["created_at"],
    }


def serialize_complaint(complaint):
    out = {
        "station_id": complaint["station_id"],
        "order_id": complaint["order_id"],
        "complainant_name": complaint["complainant_name"],
        "allegation_code": complaint["allegation_code"],
        "narrative": complaint["narrative"],
        "filed_at": complaint["filed_at"],
        "response_due_at": complaint["response_due_at"],
        "status": complaint["status"],
        "remedy_code": complaint["remedy_code"],
        "cure_due_at": complaint["cure_due_at"],
        "responded_at": complaint["responded_at"],
        "response_text": complaint["response_text"],
        "late_response": complaint["late_response"],
        "responded_by_user_id": complaint["responded_by_user_id"],
    }
    return _common(complaint, out)
