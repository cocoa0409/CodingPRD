"""Entity serializers: internal records hold datetimes; wire format is ISO strings."""
import db
from services.calc import projected_fields


def household(h):
    return {
        'id': h['id'],
        'street_address': h['street_address'],
        'service_zone': h['service_zone'],
        'status': h['status'],
        'annual_allowance_items': h['annual_allowance_items'],
        'suspension_reason': h['suspension_reason'],
        'created_at': db.fmt_ts3(h['created_at']),
        'updated_at': db.fmt_ts3(h['updated_at']),
        'version': h['version'],
    }


def allowance(a):
    return {
        'id': a['id'],
        'household_id': a['household_id'],
        'calendar_year': a['calendar_year'],
        'items_consumed': a['items_consumed'],
        'items_released': a['items_released'],
        'over_allowance_items': a['over_allowance_items'],
        'created_at': db.fmt_ts3(a['created_at']),
        'updated_at': db.fmt_ts3(a['updated_at']),
        'version': a['version'],
    }


def amnesty_window(w):
    return {
        'id': w['id'],
        'label': w['label'],
        'starts_at': db.fmt_instant(w['starts_at']),
        'ends_at': db.fmt_instant(w['ends_at']),
        'status': w['status'],
        'created_at': db.fmt_ts3(w['created_at']),
        'updated_at': db.fmt_ts3(w['updated_at']),
        'version': w['version'],
    }


def route_day(r):
    proj_load, proj_pct = projected_fields(r)
    return {
        'id': r['id'],
        'service_zone': r['service_zone'],
        'route_date': r['route_date'],
        'max_load_units': r['max_load_units'],
        'max_stops': r['max_stops'],
        'committed_load_units': r['committed_load_units'],
        'committed_stops': r['committed_stops'],
        'projected_load_units': proj_load,
        'projected_fullness_pct': proj_pct,
        'status': r['status'],
        'created_at': db.fmt_ts3(r['created_at']),
        'updated_at': db.fmt_ts3(r['updated_at']),
        'version': r['version'],
    }


def pickup_request(r):
    return {
        'id': r['id'],
        'household_id': r['household_id'],
        'route_day_id': r['route_day_id'],
        'status': r['status'],
        'scheduled_date': r['scheduled_date'],
        'load_units': r['load_units'],
        'provisional_total_cents': r['provisional_total_cents'],
        'final_total_cents': r['final_total_cents'],
        'amnesty_applied': r['amnesty_applied'],
        'refusal_reason_code': r['refusal_reason_code'],
        'missed_reason_code': r['missed_reason_code'],
        'setout_classification': r['setout_classification'],
        'created_at': db.fmt_ts3(r['created_at']),
        'updated_at': db.fmt_ts3(r['updated_at']),
        'version': r['version'],
    }


def pickup_item(it):
    return {
        'id': it['id'],
        'pickup_request_id': it['pickup_request_id'],
        'sequence_no': it['sequence_no'],
        'category': it['category'],
        'is_oversize': it['is_oversize'],
        'preparation_ack': it['preparation_ack'],
        'item_fee_cents': it['item_fee_cents'],
        'within_allowance': it['within_allowance'],
        'disposition_route': it['disposition_route'],
        'created_at': db.fmt_ts3(it['created_at']),
        'updated_at': db.fmt_ts3(it['updated_at']),
        'version': it['version'],
    }


def fee_assessment(a):
    return {
        'id': a['id'],
        'pickup_request_id': a['pickup_request_id'],
        'household_id': a['household_id'],
        'kind': a['kind'],
        'amount_cents': a['amount_cents'],
        'status': a['status'],
        'settled_at': db.fmt_instant(a['settled_at']),
        'created_at': db.fmt_ts3(a['created_at']),
        'updated_at': db.fmt_ts3(a['updated_at']),
        'version': a['version'],
    }


def dumping_report(r):
    return {
        'id': r['id'],
        'household_id': r['household_id'],
        'pickup_request_id': r['pickup_request_id'],
        'reported_at': db.fmt_instant(r['reported_at']),
        'status': r['status'],
        'determination_notes': r['determination_notes'],
        'created_at': db.fmt_ts3(r['created_at']),
        'updated_at': db.fmt_ts3(r['updated_at']),
        'version': r['version'],
    }


def notification(n):
    # Notifications carry only id and created_at besides their payload (PRD 2.5).
    return {
        'id': n['id'],
        'pickup_request_id': n['pickup_request_id'],
        'kind': n['kind'],
        'reason_code': n['reason_code'],
        'message': n['message'],
        'created_at': db.fmt_ts3(n['created_at']),
    }
