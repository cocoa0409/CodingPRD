"""Explicit per-entity serializers.

Every entity carries id / created_at / updated_at / version except RevenueEntry,
which is immutable and carries only id and created_at (PRD 2.4).
"""
from store import iso


def _common(rec):
    return {'id': rec['id'], 'created_at': iso(rec['created_at']),
            'updated_at': iso(rec['updated_at']), 'version': rec['version']}


def product(rec):
    out = _common(rec)
    out.update({
        'sku': rec['sku'], 'name': rec['name'], 'category': rec['category'],
        'list_price_cents': rec['list_price_cents'],
        'tax_treatment': rec['tax_treatment'],
        'revenue_class': rec['revenue_class'],
        'revenue_account_code': rec['revenue_account_code'],
        'refundable': rec['refundable'],
        'disclosable_fee': rec['disclosable_fee'],
        'product_state': rec['product_state'],
    })
    return out


def family(rec):
    out = _common(rec)
    out.update({
        'code': rec['code'], 'name': rec['name'],
        'cabin_class': rec['cabin_class'],
        'base_fare_cents': rec['base_fare_cents'],
        'bundle_price_cents': rec['bundle_price_cents'],
        'refundability': rec['refundability'],
        'change_fee_cents': rec['change_fee_cents'],
        'boarding_priority_tier': rec['boarding_priority_tier'],
        'upsell_parent_family_id': rec['upsell_parent_family_id'],
        'design_owner_user_id': rec['design_owner_user_id'],
        'reviewer_user_id': rec['reviewer_user_id'],
        'status': rec['status'], 'revision_no': rec['revision_no'],
        'unbundled_value_cents': rec['unbundled_value_cents'],
        'a_la_carte_total_cents': rec['a_la_carte_total_cents'],
        'bundle_discount_bp': rec['bundle_discount_bp'],
        'included_attribute_count': rec['included_attribute_count'],
        'fee_fingerprint': rec['fee_fingerprint'],
        'publication_count': rec['publication_count'],
    })
    return out


def attribute(rec):
    out = _common(rec)
    out.update({
        'fare_family_id': rec['fare_family_id'],
        'ancillary_product_id': rec['ancillary_product_id'],
        'inclusion': rec['inclusion'],
        'included_quantity': rec['included_quantity'],
        'override_price_cents': rec['override_price_cents'],
        'waiver_eligible': rec['waiver_eligible'],
        'effective_unit_cents': rec['effective_unit_cents'],
        'attr_value_cents': rec['attr_value_cents'],
        'attribute_state': rec['attribute_state'],
    })
    return out


def flight(rec):
    out = _common(rec)
    out.update({
        'flight_no': rec['flight_no'], 'origin': rec['origin'],
        'destination': rec['destination'],
        'scheduled_departure_utc': rec['scheduled_departure_utc'],
        'cabin_seat_total': rec['cabin_seat_total'],
        'sales_phase': rec['sales_phase'], 'irops_state': rec['irops_state'],
        'booked_load_factor_pct': rec['booked_load_factor_pct'],
        'demand_index_bp': rec['demand_index_bp'],
        'demand_tier': rec['demand_tier'],
        'active_waiver_count': rec['active_waiver_count'],
        'ticketed_booking_count': rec['ticketed_booking_count'],
    })
    return out


def segment(rec):
    out = _common(rec)
    out.update({
        'flight_id': rec['flight_id'],
        'ancillary_product_id': rec['ancillary_product_id'],
        'zone': rec['zone'], 'row_start': rec['row_start'],
        'row_end': rec['row_end'], 'seat_letters': list(rec['seat_letters']),
        'base_price_cents': rec['base_price_cents'],
        'total_seats': rec['total_seats'],
        'available_seats': rec['available_seats'],
        'held_seats': rec['held_seats'], 'sold_seats': rec['sold_seats'],
        'zone_multiplier_bp': rec['zone_multiplier_bp'],
        'effective_price_cents': rec['effective_price_cents'],
        'segment_state': rec['segment_state'],
    })
    return out


def channel(rec):
    out = _common(rec)
    out.update({
        'channel_code': rec['channel_code'],
        'channel_type': rec['channel_type'],
        'commission_bp': rec['commission_bp'], 'markup_bp': rec['markup_bp'],
        'max_ancillary_price_cents': rec['max_ancillary_price_cents'],
        'supported_categories': list(rec['supported_categories']),
        'parity_required': rec['parity_required'],
        'content_parity_status': rec['content_parity_status'],
        'parity_breach_count': rec['parity_breach_count'],
    })
    return out


def publication(rec):
    out = _common(rec)
    out.update({
        'fare_family_id': rec['fare_family_id'],
        'distribution_channel_id': rec['distribution_channel_id'],
        'published_family_version': rec['published_family_version'],
        'published_fee_fingerprint': rec['published_fee_fingerprint'],
        'parity_state': rec['parity_state'],
        'drift_reason': rec['drift_reason'],
        'last_resync_at': iso(rec['last_resync_at']),
    })
    return out


def booking(rec):
    out = _common(rec)
    out.update({
        'record_locator': rec['record_locator'],
        'flight_id': rec['flight_id'],
        'fare_family_id': rec['fare_family_id'],
        'distribution_channel_id': rec['distribution_channel_id'],
        'passenger_name': rec['passenger_name'],
        'booking_status': rec['booking_status'],
        'disclosure_state': rec['disclosure_state'],
        'disclosed_fee_fingerprint': rec['disclosed_fee_fingerprint'],
        'disclosed_total_fee_cents': rec['disclosed_total_fee_cents'],
        'disclosed_unbundled_list_cents': rec['disclosed_unbundled_list_cents'],
        'disclosure_issued_at': iso(rec['disclosure_issued_at']),
        'disclosure_acked_at': iso(rec['disclosure_acked_at']),
        'fare_component_cents': rec['fare_component_cents'],
        'ancillary_gross_cents': rec['ancillary_gross_cents'],
        'recognized_ancillary_net_cents': rec['recognized_ancillary_net_cents'],
        'commission_cents': rec['commission_cents'],
        'incentive_credit_cents': rec['incentive_credit_cents'],
        'channel_settlement_total_cents': rec['channel_settlement_total_cents'],
        'change_fee_waived_cents': rec['change_fee_waived_cents'],
        'waiver_applied': rec['waiver_applied'],
        'pending_change_fee_cents': rec['pending_change_fee_cents'],
        'change_count': rec['change_count'],
    })
    return out


def assignment(rec):
    out = _common(rec)
    out.update({
        'booking_id': rec['booking_id'],
        'seat_inventory_segment_id': rec['seat_inventory_segment_id'],
        'row': rec['row'], 'seat_letter': rec['seat_letter'],
        'price_charged_cents': rec['price_charged_cents'],
        'assignment_state': rec['assignment_state'],
        'released_reason': rec['released_reason'],
    })
    return out


def offer(rec):
    out = _common(rec)
    out.update({
        'booking_id': rec['booking_id'],
        'ancillary_product_id': rec['ancillary_product_id'],
        'touchpoint': rec['touchpoint'],
        'sequence_rank': rec['sequence_rank'],
        'pricing_variant': rec['pricing_variant'],
        'wtp_score_bp': rec['wtp_score_bp'],
        'offered_price_cents': rec['offered_price_cents'],
        'expected_value_cents': rec['expected_value_cents'],
        'valid_from': iso(rec['valid_from']),
        'valid_until': iso(rec['valid_until']),
        'offer_status': rec['offer_status'],
        'accepted_price_cents': rec['accepted_price_cents'],
    })
    return out


def waiver(rec):
    out = _common(rec)
    out.update({
        'flight_id': rec['flight_id'], 'event_type': rec['event_type'],
        'delay_minutes': rec['delay_minutes'],
        'waiver_scope': list(rec['waiver_scope']),
        'declared_at': iso(rec['declared_at']),
        'waiver_state': rec['waiver_state'],
        'credited_bookings_count': rec['credited_bookings_count'],
        'credited_amount_cents': rec['credited_amount_cents'],
        'rescind_reason': rec['rescind_reason'],
    })
    return out


def revenue_entry(rec):
    return {
        'id': rec['id'], 'created_at': iso(rec['created_at']),
        'booking_id': rec['booking_id'], 'product_sku': rec['product_sku'],
        'category': rec['category'], 'entry_type': rec['entry_type'],
        'gross_cents': rec['gross_cents'], 'tax_cents': rec['tax_cents'],
        'net_cents': rec['net_cents'],
        'tax_treatment': rec['tax_treatment'],
        'revenue_class': rec['revenue_class'],
        'revenue_account_code': rec['revenue_account_code'],
        'accounting_period': rec['accounting_period'],
        'source_ref': rec['source_ref'],
    }
