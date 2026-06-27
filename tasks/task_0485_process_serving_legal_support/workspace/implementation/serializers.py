"""Public JSON serializers. Each returns only the fields the PRD declares for
the entity, omitting internal bookkeeping keys (e.g. request_terminal,
stakeout_id)."""


def _common(e):
    return {
        "id": e["id"],
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


def client_view(e):
    out = _common(e)
    out.update({
        "firm_name": e["firm_name"],
        "email": e["email"],
        "prepaid_balance_cents": e["prepaid_balance_cents"],
        "status": e["status"],
    })
    return out


def county_view(e):
    out = _common(e)
    out.update({
        "name": e["name"],
        "state_code": e["state_code"],
        "e_file_enabled": e["e_file_enabled"],
        "min_diligent_attempts": e["min_diligent_attempts"],
        "filing_fee_cents": e["filing_fee_cents"],
        "max_concurrent_filings": e["max_concurrent_filings"],
    })
    return out


def server_view(e):
    out = _common(e)
    out.update({
        "full_name": e["full_name"],
        "license_no": e["license_no"],
        "max_active_assignments": e["max_active_assignments"],
        "active_assignment_count": e["active_assignment_count"],
        "completed_count": e["completed_count"],
        "reliability_score": e["reliability_score"],
        "status": e["status"],
    })
    return out


def territory_view(e):
    # ServerTerritory is immutable: id + created_at only (PRD 2.4).
    return {
        "id": e["id"],
        "created_at": e["created_at"],
        "server_id": e["server_id"],
        "county_id": e["county_id"],
    }


def service_request_view(e):
    out = _common(e)
    out.update({
        "client_id": e["client_id"],
        "county_id": e["county_id"],
        "recipient_name": e["recipient_name"],
        "service_address": e["service_address"],
        "service_lat": e["service_lat"],
        "service_lng": e["service_lng"],
        "rush": e["rush"],
        "deadline_utc": e["deadline_utc"],
        "skip_trace_requested": e["skip_trace_requested"],
        "assignment_id": e["assignment_id"],
        "service_type": e["service_type"],
        "distinct_attempt_days": e["distinct_attempt_days"],
        "quoted_fee_cents": e["quoted_fee_cents"],
        "final_fee_cents": e["final_fee_cents"],
        "status": e["status"],
    })
    return out


def document_view(e):
    out = _common(e)
    out.update({
        "service_request_id": e["service_request_id"],
        "doc_type": e["doc_type"],
        "page_count": e["page_count"],
    })
    return out


def assignment_view(e):
    out = _common(e)
    out.update({
        "service_request_id": e["service_request_id"],
        "server_id": e["server_id"],
        "superseded": e["superseded"],
        "status": e["status"],
    })
    return out


def attempt_view(e):
    out = _common(e)
    out.update({
        "assignment_id": e["assignment_id"],
        "service_request_id": e["service_request_id"],
        "attempted_at_utc": e["attempted_at_utc"],
        "gps_lat": e["gps_lat"],
        "gps_lng": e["gps_lng"],
        "outcome": e["outcome"],
        "superseded": e["superseded"],
    })
    return out


def service_view(e):
    out = _common(e)
    out.update({
        "service_request_id": e["service_request_id"],
        "assignment_id": e["assignment_id"],
        "service_type": e["service_type"],
        "recipient_relation": e["recipient_relation"],
        "served_at_utc": e["served_at_utc"],
    })
    return out


def affidavit_view(e):
    out = _common(e)
    out.update({
        "service_request_id": e["service_request_id"],
        "service_id": e["service_id"],
        "declarant_server_id": e["declarant_server_id"],
        "notary_user_id": e["notary_user_id"],
        "status": e["status"],
    })
    return out


def skip_trace_view(e):
    out = _common(e)
    out.update({
        "service_request_id": e["service_request_id"],
        "candidate_addresses": e["candidate_addresses"],
        "located_address": e["located_address"],
        "status": e["status"],
    })
    return out


def stakeout_view(e):
    out = _common(e)
    out.update({
        "assignment_id": e["assignment_id"],
        "service_request_id": e["service_request_id"],
        "server_id": e["server_id"],
        "window_start_utc": e["window_start_utc"],
        "window_end_utc": e["window_end_utc"],
        "status": e["status"],
    })
    return out


def filing_view(e):
    out = _common(e)
    out.update({
        "service_request_id": e["service_request_id"],
        "county_id": e["county_id"],
        "affidavit_id": e["affidavit_id"],
        "window_start_utc": e["window_start_utc"],
        "window_end_utc": e["window_end_utc"],
        "reject_count": e["reject_count"],
        "status": e["status"],
    })
    return out


def invoice_line_view(e):
    out = _common(e)
    out.update({
        "service_request_id": e["service_request_id"],
        "kind": e["kind"],
        "amount_cents": e["amount_cents"],
        "voided": e["voided"],
    })
    return out
