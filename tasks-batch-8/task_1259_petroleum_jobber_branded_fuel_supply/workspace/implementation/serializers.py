"""Entity serializers — declared fields only; internal keys never leak."""
import db
from db import fmt_clock
from services import calc


def _common(rec):
    return {
        'id': rec['id'],
        'created_at': rec['created_at'],
        'updated_at': rec['updated_at'],
        'version': rec['version'],
    }


def product(p):
    d = {
        'product_code': p['product_code'],
        'display_name': p['display_name'],
        'category': p['category'],
        'federal_excise_tc_per_gal': p['federal_excise_tc_per_gal'],
        'temp_coeff': p['temp_coeff'],
    }
    d.update(_common(p))
    return d


def station(s):
    d = {
        'station_name': s['station_name'],
        'state_code': s['state_code'],
        'home_terminal_code': s['home_terminal_code'],
        'state_excise_tc_per_gal': s['state_excise_tc_per_gal'],
        'local_option_tc_per_gal': s['local_option_tc_per_gal'],
        'credit_limit_cents': s['credit_limit_cents'],
        'credit_terms_days': s['credit_terms_days'],
        'current_exposure_cents': s['current_exposure_cents'],
        'operating_status': s['operating_status'],
        'credit_status': s['credit_status'],
        'compliance_status': s['compliance_status'],
        'cure_started_at': (fmt_clock(s['cure_started_at'])
                            if s['cure_started_at'] is not None else None),
    }
    d.update(_common(s))
    return d


def agreement(a):
    d = {
        'station_id': a['station_id'],
        'term_start_date': a['term_start_date'],
        'term_end_date': a['term_end_date'],
        'committed_gallons': a['committed_gallons'],
        'fulfilled_gallons': calc.fulfilled_gallons(a),
        'imaging_allowance_cents': a['imaging_allowance_cents'],
        'margin_tc_per_gal': a['margin_tc_per_gal'],
        'shortfall_penalty_tc_per_gal': a['shortfall_penalty_tc_per_gal'],
        'buyout_method': a['buyout_method'],
        'renewal_count': a['renewal_count'],
        'renewal_credit_cents': a['renewal_credit_cents'],
        'buyout_settlement_cents': a['buyout_settlement_cents'],
        'status': a['status'],
    }
    d.update(_common(a))
    return d


def posting(p):
    d = {
        'terminal_code': p['terminal_code'],
        'product_id': p['product_id'],
        'effective_date': p['effective_date'],
        'price_tc_per_gal': p['price_tc_per_gal'],
        'status': p['status'],
    }
    d.update(_common(p))
    return d


def tank(t):
    d = {
        'station_id': t['station_id'],
        'product_id': t['product_id'],
        'capacity_gallons': t['capacity_gallons'],
        'safe_fill_pct': t['safe_fill_pct'],
        'opening_physical_gallons': t['opening_physical_gallons'],
        'physical_gallons': t['physical_gallons'],
        'physical_temp_f': t['physical_temp_f'],
        'book_inventory_gallons': t['book_inventory_gallons'],
    }
    d.update(_common(t))
    return d


def truck(t):
    d = {
        'truck_code': t['truck_code'],
        'capacity_gallons': t['capacity_gallons'],
    }
    d.update(_common(t))
    return d


def drop(x):
    d = {
        'station_id': x['station_id'],
        'tank_id': x['tank_id'],
        'truck_id': x['truck_id'],
        'product_id': x['product_id'],
        'planned_gallons': x['planned_gallons'],
        'window_start': fmt_clock(x['window_start']),
        'window_end': fmt_clock(x['window_end']),
        'delivered_gallons': x['delivered_gallons'],
        'delivered_at': (fmt_clock(x['delivered_at'])
                         if x['delivered_at'] is not None else None),
        'estimated_amount_cents': x['estimated_amount_cents'],
        'invoice_id': x['invoice_id'],
        'failure_count': x['failure_count'],
        'failure_reason': x['failure_reason'],
        'status': x['status'],
    }
    d.update(_common(x))
    return d


def meter(m):
    # Meter readings are lean: id + created_at only (no updated_at/version).
    return {
        'id': m['id'],
        'created_at': m['created_at'],
        'tank_id': m['tank_id'],
        'reading_at': fmt_clock(m['reading_at']),
        'totalizer_gallons': m['totalizer_gallons'],
        'metered_gallons': m['metered_gallons'],
    }


def loss(le):
    d = {
        'station_id': le['station_id'],
        'tank_id': le['tank_id'],
        'reconciliation_id': le['reconciliation_id'],
        'loss_type': le['loss_type'],
        'gallons': le['gallons'],
        'occurred_at': fmt_clock(le['occurred_at']),
        'auto_generated': le['auto_generated'],
        'status': le['status'],
    }
    d.update(_common(le))
    return d


def recon(r):
    d = {
        'station_id': r['station_id'],
        'period_start': r['period_start'],
        'period_end': r['period_end'],
        'threshold_gallons': r['threshold_gallons'],
        'book_gallons': r['book_gallons'],
        'physical_gross_gallons': r['physical_gross_gallons'],
        'variance_gross_gallons': r['variance_gross_gallons'],
        'variance_net_gallons': r['variance_net_gallons'],
        'status': r['status'],
        'opener_user_id': r['opener_user_id'],
        'resolver_user_id': r['resolver_user_id'],
        'resolution_note': r['resolution_note'],
    }
    d.update(_common(r))
    return d


def invoice(i):
    d = {
        'station_id': i['station_id'],
        'drop_id': i['drop_id'],
        'product_id': i['product_id'],
        'gallons_delivered': i['gallons_delivered'],
        'price_tc_per_gal': i['price_tc_per_gal'],
        'fuel_amount_cents': i['fuel_amount_cents'],
        'freight_amount_cents': i['freight_amount_cents'],
        'tax_amount_cents': i['tax_amount_cents'],
        'total_cents': i['total_cents'],
        'invoice_date': i['invoice_date'],
        'due_date': i['due_date'],
        'status': i['status'],
    }
    d.update(_common(i))
    return d


def draft(x):
    d = {
        'invoice_id': x['invoice_id'],
        'station_id': x['station_id'],
        'scheduled_date': x['scheduled_date'],
        'amount_cents': x['amount_cents'],
        'attempts': x['attempts'],
        'status': x['status'],
    }
    d.update(_common(x))
    return d


def tax_remittance(t):
    d = {
        'state_code': t['state_code'],
        'period_start': t['period_start'],
        'period_end': t['period_end'],
        'due_date': t['due_date'],
        'gasoline_gallons': t['gasoline_gallons'],
        'diesel_gallons': t['diesel_gallons'],
        'tax_amount_cents': t['tax_amount_cents'],
        'late_penalty_cents': t['late_penalty_cents'],
        'total_due_cents': t['total_due_cents'],
        'filed_at': (fmt_clock(t['filed_at'])
                     if t['filed_at'] is not None else None),
        'status': t['status'],
    }
    d.update(_common(t))
    return d


def audit(a):
    # Brand audits are lean: id + created_at only.
    return {
        'id': a['id'],
        'created_at': a['created_at'],
        'station_id': a['station_id'],
        'audit_date': a['audit_date'],
        'score': a['score'],
        'deficiencies': a['deficiencies'],
        'result': a['result'],
    }
