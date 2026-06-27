"""Entity -> public JSON serialization.

Each serializer projects exactly the fields the PRD/scaffold declare for that
entity, plus the common system fields. Internal bookkeeping (_seq) is stripped.
Vault and ATM derived fields are recomputed at serialization time so reads
always reflect the current ledger (PRD §2.5).
"""
import services.vault as vault_svc
import services.atm as atm_svc


def _common(entity, with_common=True):
    out = {"id": entity["id"], "created_at": entity["created_at"]}
    if with_common:
        out["updated_at"] = entity["updated_at"]
        out["version"] = entity["version"]
    return out


def site_merchant(e):
    out = _common(e)
    out.update({
        "legal_name": e["legal_name"],
        "commission_pct_bps": e["commission_pct_bps"],
        "commission_flat_per_wd_cents": e["commission_flat_per_wd_cents"],
        "commission_monthly_ceiling_cents": e["commission_monthly_ceiling_cents"],
        "commission_basis": e["commission_basis"],
        "payout_status": e["payout_status"],
    })
    return out


def vault(store, e):
    out = _common(e)
    pos = vault_svc.position(store, e)
    out.update({
        "name": e["name"],
        "provisioned_cents": e["provisioned_cents"],
        "balance_cents": pos["balance_cents"],
        "in_transit_cents": pos["in_transit_cents"],
        "in_machine_cents": pos["in_machine_cents"],
    })
    return out


def route(e):
    out = _common(e)
    out.update({
        "carrier_name": e["carrier_name"],
        "vault_id": e["vault_id"],
        "status": e["status"],
    })
    return out


def location(e):
    out = _common(e)
    out.update({
        "name": e["name"],
        "jurisdiction_code": e["jurisdiction_code"],
        "site_merchant_id": e["site_merchant_id"],
        "route_id": e["route_id"],
        "address": e["address"],
    })
    return out


def atm(store, e):
    out = _common(e)
    derived = atm_svc.derived(store, e)
    out.update({
        "serial_no": e["serial_no"],
        "location_id": e["location_id"],
        "note_denomination_cents": e["note_denomination_cents"],
        "surcharge_cents": e["surcharge_cents"],
        "operational_status": e["operational_status"],
        "cash_status": e["cash_status"],
        "monthly_wd_count": e["monthly_wd_count"],
        "loaded_cents": derived["loaded_cents"],
        "dispensed_cents_since_load": e["dispensed_cents_since_load"],
        "fee_disclosure_id": e["fee_disclosure_id"],
    })
    return out


def cassette(e):
    out = _common(e)
    out.update({
        "atm_id": e["atm_id"],
        "position": e["position"],
        "loaded_cents": e["loaded_cents"],
        "dispensed_cents": e["dispensed_cents"],
        "balance_status": e["balance_status"],
    })
    return out


def replenishment_order(e):
    out = _common(e)
    out.update({
        "atm_id": e["atm_id"],
        "route_id": e["route_id"],
        "vault_id": e["vault_id"],
        "order_amount_cents": e["order_amount_cents"],
        "forecast_basis": e["forecast_basis"],
        "service_window_start": e["service_window_start"],
        "service_window_end": e["service_window_end"],
        "status": e["status"],
        "expected_vault_version": e["expected_vault_version"],
    })
    return out


def transaction(e):
    out = _common(e, with_common=False)
    out.update({
        "atm_id": e["atm_id"],
        "cassette_id": e["cassette_id"],
        "kind": e["kind"],
        "amount_cents": e["amount_cents"],
        "surcharge_cents": e["surcharge_cents"],
        "settlement_run_id": e["settlement_run_id"],
        "monthly_seq": e["monthly_seq"],
    })
    return out


def cash_count(e):
    out = _common(e)
    out.update({
        "atm_id": e["atm_id"],
        "counted_cents": e["counted_cents"],
        "expected_remaining_cents": e["expected_remaining_cents"],
        "variance_cents": e["variance_cents"],
        "outcome": e["outcome"],
        "tolerance_cents": e["tolerance_cents"],
    })
    return out


def service_ticket(e):
    out = _common(e)
    out.update({
        "atm_id": e["atm_id"],
        "fault_kind": e["fault_kind"],
        "severity": e["severity"],
        "status": e["status"],
        "reopen_count": e["reopen_count"],
        "assigned_tech_id": e["assigned_tech_id"],
    })
    return out


def settlement_run(e):
    out = _common(e)
    out.update({
        "atm_id": e["atm_id"],
        "window_start": e["window_start"],
        "window_end": e["window_end"],
        "withdrawal_count": e["withdrawal_count"],
        "surcharge_revenue_cents": e["surcharge_revenue_cents"],
        "interchange_revenue_cents": e["interchange_revenue_cents"],
        "network_fee_cents": e["network_fee_cents"],
        "net_operator_revenue_cents": e["net_operator_revenue_cents"],
        "status": e["status"],
    })
    return out


def commission_statement(e):
    out = _common(e)
    out.update({
        "settlement_run_id": e["settlement_run_id"],
        "site_merchant_id": e["site_merchant_id"],
        "pct_amount_cents": e["pct_amount_cents"],
        "flat_amount_cents": e["flat_amount_cents"],
        "commission_cents": e["commission_cents"],
        "operator_keeps_cents": e["operator_keeps_cents"],
        "status": e["status"],
    })
    return out


def fee_disclosure(e):
    out = _common(e)
    out.update({
        "atm_id": e["atm_id"],
        "disclosed_surcharge_cents": e["disclosed_surcharge_cents"],
        "jurisdiction_code": e["jurisdiction_code"],
        "regulatory_cap_cents": e["regulatory_cap_cents"],
        "ack_text_present": e["ack_text_present"],
        "status": e["status"],
    })
    return out
