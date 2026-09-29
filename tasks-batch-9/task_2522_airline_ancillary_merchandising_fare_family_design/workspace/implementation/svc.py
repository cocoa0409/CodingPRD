"""Business logic: derived-field recomputation, cascades and state transitions.

Every entity a cascade touches is itself mutated -- updated_at refreshed and
version incremented by 1 (PRD 2.10).  Derived counters are always recomputed
from the rows they summarise, never incrementally patched.
"""
import calc
from store import (accounting_period, by_created, common_fields, db, minutes,
                   new_id, now, seq, touch)

ANCILLARY_ENTRY_TYPES = ('SALE', 'REFUND', 'WAIVER_CREDIT', 'WAIVER_REVERSAL')


# --------------------------------------------------------------------------
# row lookups
# --------------------------------------------------------------------------
def attributes_of(family_id):
    return by_created([a for a in db.attributes.values()
                       if a['fare_family_id'] == family_id])


def publications_of_family(family_id):
    return by_created([p for p in db.publications.values()
                       if p['fare_family_id'] == family_id])


def publications_of_channel(channel_id):
    return by_created([p for p in db.publications.values()
                       if p['distribution_channel_id'] == channel_id])


def bookings_of_family(family_id):
    return by_created([b for b in db.bookings.values()
                       if b['fare_family_id'] == family_id])


def bookings_of_flight(flight_id):
    return by_created([b for b in db.bookings.values()
                       if b['flight_id'] == flight_id])


def segments_of_flight(flight_id):
    return by_created([s for s in db.segments.values()
                       if s['flight_id'] == flight_id])


def waivers_of_flight(flight_id):
    return by_created([w for w in db.waivers.values()
                       if w['flight_id'] == flight_id])


def assignments_of_booking(booking_id):
    return by_created([a for a in db.assignments.values()
                       if a['booking_id'] == booking_id])


def assignments_of_segment(segment_id):
    return by_created([a for a in db.assignments.values()
                       if a['seat_inventory_segment_id'] == segment_id])


def offers_of_booking(booking_id):
    return by_created([o for o in db.offers.values()
                       if o['booking_id'] == booking_id])


def entries_of_booking(booking_id):
    return by_created([e for e in db.revenue.values()
                       if e['booking_id'] == booking_id])


def product_by_sku(sku):
    for product in db.products.values():
        if product['sku'] == sku:
            return product
    return None


# --------------------------------------------------------------------------
# the append-only ledger
# --------------------------------------------------------------------------
def post_entry(booking, category, entry_type, gross_cents, tax_treatment,
               revenue_class, revenue_account_code, product_sku, source_ref,
               tax_cents=None):
    if tax_cents is None:
        tax_cents = calc.tax_cents(gross_cents, tax_treatment)
    entry = {
        'id': new_id(), 'created_at': now(), '_seq': seq(),
        'booking_id': booking['id'], 'product_sku': product_sku,
        'category': category, 'entry_type': entry_type,
        'gross_cents': gross_cents, 'tax_cents': tax_cents,
        'net_cents': gross_cents - tax_cents,
        'tax_treatment': tax_treatment, 'revenue_class': revenue_class,
        'revenue_account_code': revenue_account_code,
        'accounting_period': accounting_period(), 'source_ref': source_ref,
    }
    db.revenue[entry['id']] = entry
    return entry


def mirror_entry(booking, source, entry_type, source_ref=None):
    """Post a sign-flipped copy of an existing entry."""
    return post_entry(booking, source['category'], entry_type,
                      -source['gross_cents'], source['tax_treatment'],
                      source['revenue_class'], source['revenue_account_code'],
                      source['product_sku'],
                      source['source_ref'] if source_ref is None else source_ref,
                      tax_cents=-source['tax_cents'])


def recompute_booking_money(booking):
    """PRD 3.9: the pinned seven-step settlement sequence, always read whole."""
    entries = entries_of_booking(booking['id'])
    ancillary_gross = sum(e['gross_cents'] for e in entries
                          if e['entry_type'] in ANCILLARY_ENTRY_TYPES)
    recognized_net = sum(e['net_cents'] for e in entries
                         if e['category'] != 'AIR_TRANSPORT')
    channel = db.channels[booking['distribution_channel_id']]
    commission, incentive, total = calc.settlement(
        booking['fare_component_cents'], ancillary_gross,
        channel['commission_bp'])
    booking['ancillary_gross_cents'] = ancillary_gross
    booking['recognized_ancillary_net_cents'] = recognized_net
    booking['commission_cents'] = commission
    booking['incentive_credit_cents'] = incentive
    booking['channel_settlement_total_cents'] = total


# --------------------------------------------------------------------------
# fare-family derived fields
# --------------------------------------------------------------------------
def recompute_family_valuation(family):
    """Override-basis valuation: one rounding per attribute, then the sum."""
    unbundled, per_attr = calc.bundle_valuation(family, 'override_basis')
    for attr in attributes_of(family['id']):
        attr['effective_unit_cents'] = calc.effective_unit_cents(attr)
        if attr['id'] in per_attr:
            attr['attr_value_cents'] = per_attr[attr['id']]
        else:
            attr['attr_value_cents'] = calc.attr_value(
                attr['effective_unit_cents'], attr['included_quantity'],
                family['cabin_class'])
    a_la_carte = family['base_fare_cents'] + unbundled
    family['unbundled_value_cents'] = unbundled
    family['a_la_carte_total_cents'] = a_la_carte
    family['bundle_discount_bp'] = calc.bundle_discount_bp(
        a_la_carte, family['bundle_price_cents'], unbundled)
    family['included_attribute_count'] = len(
        [a for a in calc.active_attributes(family['id'])
         if a['inclusion'] == 'INCLUDED'])


def rebuild_fingerprint(family):
    """Returns True when the fingerprint actually drifted."""
    previous = family.get('fee_fingerprint')
    family['fee_fingerprint'] = calc.fee_fingerprint(family)
    return previous != family['fee_fingerprint']


def recompute_publication_count(family):
    family['publication_count'] = len(
        [p for p in publications_of_family(family['id'])
         if p['parity_state'] in ('PENDING', 'IN_PARITY', 'OUT_OF_PARITY')])


# --------------------------------------------------------------------------
# content parity
# --------------------------------------------------------------------------
def channel_parity_status(channel):
    if channel['parity_required'] and any(
            p['parity_state'] == 'OUT_OF_PARITY'
            for p in publications_of_channel(channel['id'])):
        return 'BREACHED'
    return 'COMPLIANT'


def apply_channel_parity(channel, force_touch=False):
    derived = channel_parity_status(channel)
    changed = derived != channel['content_parity_status']
    channel['content_parity_status'] = derived
    if changed or force_touch:
        touch(channel)
    return changed


def supersede_offer(offer):
    offer['offer_status'] = 'SUPERSEDED'
    touch(offer)


def expire_offer(offer):
    offer['offer_status'] = 'EXPIRED'
    touch(offer)


def drift_publications(family, drift_reason, force=False):
    """IN_PARITY -> OUT_OF_PARITY for every publication the drift reached."""
    for publication in publications_of_family(family['id']):
        if publication['parity_state'] != 'IN_PARITY':
            continue
        if not force and publication['published_fee_fingerprint'] == family['fee_fingerprint']:
            continue
        publication['parity_state'] = 'OUT_OF_PARITY'
        publication['drift_reason'] = drift_reason
        touch(publication)
        channel = db.channels[publication['distribution_channel_id']]
        channel['parity_breach_count'] = channel['parity_breach_count'] + 1
        apply_channel_parity(channel, force_touch=True)
        for booking in bookings_of_family(family['id']):
            if booking['distribution_channel_id'] != channel['id']:
                continue
            for offer in offers_of_booking(booking['id']):
                if offer['offer_status'] == 'PRESENTED':
                    supersede_offer(offer)


def stale_bookings(family, supersede=True):
    """A fingerprint drift makes a still-HELD booking's disclosure dishonest."""
    for booking in bookings_of_family(family['id']):
        if booking['booking_status'] != 'HELD':
            continue
        if booking['disclosure_state'] not in ('PENDING_ACK', 'ACKNOWLEDGED'):
            continue
        booking['disclosure_state'] = 'STALE'
        touch(booking)
        if supersede:
            for offer in offers_of_booking(booking['id']):
                if offer['offer_status'] == 'PRESENTED':
                    supersede_offer(offer)


def withdraw_publications(family):
    """Retirement withdraws the family's content everywhere."""
    channels = []
    for publication in publications_of_family(family['id']):
        if publication['parity_state'] not in ('PENDING', 'IN_PARITY', 'OUT_OF_PARITY'):
            continue
        publication['parity_state'] = 'WITHDRAWN'
        touch(publication)
        channel = db.channels[publication['distribution_channel_id']]
        if channel['id'] not in [c['id'] for c in channels]:
            channels.append(channel)
    for channel in channels:
        apply_channel_parity(channel)


# --------------------------------------------------------------------------
# flights, segments and the demand feed
# --------------------------------------------------------------------------
def recompute_segment_inventory(segment):
    """Seat inventory conservation (PRD 2.10)."""
    segment['available_seats'] = (segment['total_seats'] - segment['held_seats']
                                 - segment['sold_seats'])


def price_segment(segment, flight):
    segment['zone_multiplier_bp'] = calc.ZONE_MULTIPLIER_BP[segment['zone']]
    segment['effective_price_cents'] = calc.seat_segment_effective_price(
        segment, flight['demand_tier'])


def reprice_flight_segments(flight):
    for segment in segments_of_flight(flight['id']):
        price_segment(segment, flight)
        touch(segment)


def recompute_flight_counters(flight):
    waiver_count = len([w for w in waivers_of_flight(flight['id'])
                        if w['waiver_state'] == 'ACTIVE'])
    ticketed = len([b for b in bookings_of_flight(flight['id'])
                    if b['booking_status'] in ('TICKETED', 'CHANGE_PENDING')])
    changed = (waiver_count != flight['active_waiver_count']
               or ticketed != flight['ticketed_booking_count'])
    flight['active_waiver_count'] = waiver_count
    flight['ticketed_booking_count'] = ticketed
    if changed:
        touch(flight)
    return changed


# --------------------------------------------------------------------------
# seat assignments
# --------------------------------------------------------------------------
def seat_sale_entry(assignment):
    """The SALE entry that a confirmed assignment posted, if any."""
    reference = 'seat:' + assignment['id']
    rows = [e for e in entries_of_booking(assignment['booking_id'])
            if e['source_ref'] == reference and e['entry_type'] == 'SALE']
    return by_created(rows)[-1] if rows else None


def post_seat_sale(assignment, segment, booking):
    if assignment['price_charged_cents'] <= 0:
        return None
    product = db.products[segment['ancillary_product_id']]
    return post_entry(booking, 'SEAT', 'SALE', assignment['price_charged_cents'],
                      product['tax_treatment'], product['revenue_class'],
                      product['revenue_account_code'], product['sku'],
                      'seat:' + assignment['id'])


def confirm_assignment(assignment, booking):
    """Confirmation from the ticketing path: the seat was counted as held."""
    segment = db.segments[assignment['seat_inventory_segment_id']]
    assignment['assignment_state'] = 'CONFIRMED'
    touch(assignment)
    segment['held_seats'] = segment['held_seats'] - 1
    segment['sold_seats'] = segment['sold_seats'] + 1
    recompute_segment_inventory(segment)
    touch(segment)
    post_seat_sale(assignment, segment, booking)


def release_assignment(assignment, released_reason, skip_refund=False):
    """Returns True when a REFUND entry was posted."""
    segment = db.segments[assignment['seat_inventory_segment_id']]
    booking = db.bookings[assignment['booking_id']]
    previous = assignment['assignment_state']
    assignment['assignment_state'] = 'RELEASED'
    assignment['released_reason'] = released_reason
    touch(assignment)
    if previous == 'HELD':
        segment['held_seats'] = segment['held_seats'] - 1
    else:
        segment['sold_seats'] = segment['sold_seats'] - 1
    recompute_segment_inventory(segment)
    touch(segment)
    if previous != 'CONFIRMED' or assignment['price_charged_cents'] <= 0 or skip_refund:
        return False
    sale = seat_sale_entry(assignment)
    if sale is not None:
        mirror_entry(booking, sale, 'REFUND')
    else:
        product = db.products[segment['ancillary_product_id']]
        post_entry(booking, 'SEAT', 'REFUND', -assignment['price_charged_cents'],
                   product['tax_treatment'], product['revenue_class'],
                   product['revenue_account_code'], product['sku'],
                   'seat:' + assignment['id'])
    return True


# --------------------------------------------------------------------------
# ticketing and the allocation
# --------------------------------------------------------------------------
AIR_TRANSPORT_META = ('TAXABLE_TRANSPORT', 'AIR_TRANSPORT_RELATED', '3000',
                      'AIR_TRANSPORT')


def post_allocation(booking, family):
    for bucket in calc.allocation_buckets(family, booking['fare_component_cents']):
        if bucket['category'] == 'AIR_TRANSPORT':
            treatment, revenue_class, account, sku = AIR_TRANSPORT_META
        else:
            product = db.products[bucket['attr']['ancillary_product_id']]
            treatment = product['tax_treatment']
            revenue_class = product['revenue_class']
            account = product['revenue_account_code']
            sku = product['sku']
        post_entry(booking, bucket['category'], 'ALLOCATION',
                   bucket['gross_cents'], treatment, revenue_class, account,
                   sku, 'ticket:' + booking['id'])


def ticket_booking(booking, family, flight):
    booking['fare_component_cents'] = family['bundle_price_cents']
    booking['booking_status'] = 'TICKETED'
    post_allocation(booking, family)
    for assignment in assignments_of_booking(booking['id']):
        if assignment['assignment_state'] == 'HELD':
            confirm_assignment(assignment, booking)
    recompute_booking_money(booking)
    touch(booking)
    recompute_flight_counters(flight)


# --------------------------------------------------------------------------
# cancellation
# --------------------------------------------------------------------------
def cancel_booking(booking, family, flight):
    previous = booking['booking_status']
    booking['booking_status'] = 'CANCELLED'
    for assignment in assignments_of_booking(booking['id']):
        if assignment['assignment_state'] in ('HELD', 'CONFIRMED'):
            release_assignment(assignment, 'BOOKING_CANCELLED')
    for offer in offers_of_booking(booking['id']):
        if offer['offer_status'] == 'PRESENTED':
            supersede_offer(offer)
    for sale in [e for e in entries_of_booking(booking['id'])
                 if e['entry_type'] == 'SALE']:
        product = product_by_sku(sale['product_sku'])
        if product is not None and product['refundable']:
            mirror_entry(booking, sale, 'REFUND')
    if previous in ('TICKETED', 'CHANGE_PENDING'):
        if family['refundability'] == 'FULLY_REFUNDABLE':
            for allocation in [e for e in entries_of_booking(booking['id'])
                               if e['entry_type'] == 'ALLOCATION']:
                mirror_entry(booking, allocation, 'REFUND')
    if previous == 'CHANGE_PENDING':
        booking['pending_change_fee_cents'] = None
    recompute_booking_money(booking)
    touch(booking)
    if previous in ('TICKETED', 'CHANGE_PENDING'):
        recompute_flight_counters(flight)


# --------------------------------------------------------------------------
# the logical clock sweep and the phase-advance cascades
# --------------------------------------------------------------------------
def sweep_expired_offers():
    swept = 0
    for offer in by_created(list(db.offers.values())):
        if offer['offer_status'] == 'PRESENTED' and offer['valid_until'] <= db.clock:
            expire_offer(offer)
            swept += 1
    return swept


def expire_flight_offers(flight, touchpoints):
    for booking in bookings_of_flight(flight['id']):
        for offer in offers_of_booking(booking['id']):
            if offer['offer_status'] != 'PRESENTED':
                continue
            if touchpoints is None or offer['touchpoint'] in touchpoints:
                expire_offer(offer)


def depart_flight(flight):
    expire_flight_offers(flight, None)
    for segment in segments_of_flight(flight['id']):
        if segment['segment_state'] == 'OPEN':
            segment['segment_state'] = 'CLOSED'
            touch(segment)
    for waiver in waivers_of_flight(flight['id']):
        if waiver['waiver_state'] == 'ACTIVE':
            waiver['waiver_state'] = 'EXPIRED'
            touch(waiver)
    for booking in bookings_of_flight(flight['id']):
        if booking['booking_status'] == 'TICKETED':
            booking['booking_status'] = 'FLOWN'
            touch(booking)
    waiver_count = len([w for w in waivers_of_flight(flight['id'])
                        if w['waiver_state'] == 'ACTIVE'])
    flight['active_waiver_count'] = waiver_count
    flight['ticketed_booking_count'] = len(
        [b for b in bookings_of_flight(flight['id'])
         if b['booking_status'] in ('TICKETED', 'CHANGE_PENDING')])


# --------------------------------------------------------------------------
# offer_sequencing_selection (PRD 3.6)
# --------------------------------------------------------------------------
def open_segments_for_product(flight_id, product_id):
    return [s for s in segments_of_flight(flight_id)
            if s['ancillary_product_id'] == product_id
            and s['segment_state'] == 'OPEN']


def declined_cooloff_active(booking_id, product_id):
    for offer in offers_of_booking(booking_id):
        if offer['ancillary_product_id'] != product_id:
            continue
        if offer['offer_status'] != 'DECLINED':
            continue
        if offer['updated_at'] + minutes(calc.OFFER_COOLOFF_MINUTES) > db.clock:
            return True
    return False


def waived_categories(flight_id):
    scoped = set()
    for waiver in waivers_of_flight(flight_id):
        if waiver['waiver_state'] == 'ACTIVE':
            scoped.update(waiver['waiver_scope'])
    return scoped


def candidate_products(booking, family, flight, channel, touchpoint, requested):
    """The eight-predicate eligibility test of PRD 3.6."""
    included_product_ids = set(
        a['ancillary_product_id'] for a in calc.active_attributes(family['id'])
        if a['inclusion'] == 'INCLUDED')
    offers = offers_of_booking(booking['id'])
    accepted = set(o['ancillary_product_id'] for o in offers
                   if o['offer_status'] == 'ACCEPTED')
    presented = set(o['ancillary_product_id'] for o in offers
                    if o['offer_status'] == 'PRESENTED')
    waived = waived_categories(flight['id'])
    pool = []
    for product in by_created(list(db.products.values())):
        if product['product_state'] != 'ACTIVE':
            continue
        if product['category'] not in channel['supported_categories']:
            continue
        if requested is not None and product['id'] not in requested:
            continue
        if product['id'] in included_product_ids:
            continue
        if product['id'] in accepted or product['id'] in presented:
            continue
        if declined_cooloff_active(booking['id'], product['id']):
            continue
        if product['category'] == 'CHANGE' and touchpoint == 'BOOKING':
            continue
        if product['category'] in waived:
            continue
        pool.append(product)
    return pool


def price_candidate(product, flight, channel, touchpoint):
    """Returns (pricing_variant, wtp_score_bp, offered_price_cents,
    expected_value_cents)."""
    open_segments = open_segments_for_product(flight['id'], product['id'])
    if product['category'] == 'SEAT' and open_segments:
        variant = 'RESIDUAL_INVENTORY'
        raw = calc.wtp_residual_inventory(open_segments)
    else:
        variant = 'WTP_ELASTIC'
        raw = calc.wtp_elastic(flight)
    score = calc.clamp_wtp(raw)
    offered = calc.dynamic_price(product['list_price_cents'], score, touchpoint,
                                 channel['markup_bp'])
    return variant, score, offered, calc.expected_value(offered, score)


def run_offer_session(booking, family, flight, channel, touchpoint, requested):
    pool = candidate_products(booking, family, flight, channel, touchpoint,
                              requested)
    priced = []
    for product in pool:
        variant, score, offered, value = price_candidate(product, flight,
                                                         channel, touchpoint)
        priced.append({'product': product, 'pricing_variant': variant,
                       'wtp_score_bp': score, 'offered_price_cents': offered,
                       'expected_value_cents': value})
    priced.sort(key=lambda c: (
        -c['expected_value_cents'],
        calc.CATEGORY_PRIORITY_ORDER.index(c['product']['category']),
        c['product']['created_at'], c['product'].get('_seq', 0)))
    candidate_count = len(priced)
    presented_ids = []
    valid_from = now()
    valid_until = valid_from + minutes(calc.OFFER_TTL_MINUTES)
    for rank, candidate in enumerate(priced[:calc.MAX_OFFERS_PER_SESSION], 1):
        offer = common_fields()
        offer.update({
            'booking_id': booking['id'],
            'ancillary_product_id': candidate['product']['id'],
            'touchpoint': touchpoint, 'sequence_rank': rank,
            'pricing_variant': candidate['pricing_variant'],
            'wtp_score_bp': candidate['wtp_score_bp'],
            'offered_price_cents': candidate['offered_price_cents'],
            'expected_value_cents': candidate['expected_value_cents'],
            'valid_from': valid_from, 'valid_until': valid_until,
            'offer_status': 'PRESENTED', 'accepted_price_cents': None,
        })
        db.offers[offer['id']] = offer
        presented_ids.append(offer['id'])
    return {
        'touchpoint': touchpoint,
        'candidate_count': candidate_count,
        'presented_offer_ids': presented_ids,
        'suppression_reason': '' if presented_ids else 'NO_ELIGIBLE_CANDIDATES',
    }


# --------------------------------------------------------------------------
# irregular-operations waivers (PRD 3.8)
# --------------------------------------------------------------------------
def declare_waiver(flight, waiver):
    scope = waiver['waiver_scope']
    flight['irops_state'] = 'IRREGULAR'
    credited_ids = []
    credited_amount = 0
    credited_sale_ids = set()
    waived_deltas = {}
    applied = []
    for booking in bookings_of_flight(flight['id']):
        if booking['booking_status'] not in ('TICKETED', 'CHANGE_PENDING'):
            continue
        family = db.families[booking['fare_family_id']]
        sales = [e for e in entries_of_booking(booking['id'])
                 if e['entry_type'] == 'SALE' and e['category'] in scope]
        for sale in sales:
            mirror_entry(booking, sale, 'WAIVER_CREDIT',
                         source_ref='waiver:' + waiver['id'])
            credited_sale_ids.add(sale['id'])
            credited_amount += abs(sale['gross_cents'])
            if booking['id'] not in credited_ids:
                credited_ids.append(booking['id'])
        booking['waiver_applied'] = True
        applied.append(booking['id'])
        if 'CHANGE' in scope:
            room = family['change_fee_cents'] - booking['change_fee_waived_cents']
            delta = room if room > 0 else 0
            booking['change_fee_waived_cents'] += delta
            waived_deltas[booking['id']] = delta
        for offer in offers_of_booking(booking['id']):
            if offer['offer_status'] != 'PRESENTED':
                continue
            product = db.products[offer['ancillary_product_id']]
            if product['category'] in scope:
                supersede_offer(offer)
    if waiver['event_type'] == 'DIVERSION' and 'SEAT' in scope:
        for segment in segments_of_flight(flight['id']):
            for assignment in assignments_of_segment(segment['id']):
                if assignment['assignment_state'] not in ('HELD', 'CONFIRMED'):
                    continue
                sale = seat_sale_entry(assignment)
                skip = sale is not None and sale['id'] in credited_sale_ids
                release_assignment(assignment, 'IROPS_REACCOMMODATION',
                                   skip_refund=skip)
                if assignment['booking_id'] not in applied:
                    applied.append(assignment['booking_id'])
    waiver['_credited_sale_ids'] = credited_sale_ids
    waiver['_waived_deltas'] = waived_deltas
    waiver['_applied_bookings'] = applied
    waiver['credited_bookings_count'] = len(credited_ids)
    waiver['credited_amount_cents'] = credited_amount
    for booking_id in applied:
        booking = db.bookings[booking_id]
        recompute_booking_money(booking)
        touch(booking)
    if not recompute_flight_counters(flight):
        touch(flight)


def rescind_waiver(flight, waiver):
    credits = [e for e in by_created(list(db.revenue.values()))
               if e['entry_type'] == 'WAIVER_CREDIT'
               and e['source_ref'] == 'waiver:' + waiver['id']]
    for credit in credits:
        booking = db.bookings[credit['booking_id']]
        mirror_entry(booking, credit, 'WAIVER_REVERSAL',
                     source_ref='waiver:' + waiver['id'])
    waiver['waiver_state'] = 'RESCINDED'
    others_active = any(w['waiver_state'] == 'ACTIVE'
                        for w in waivers_of_flight(flight['id'])
                        if w['id'] != waiver['id'])
    for booking_id in waiver.get('_applied_bookings', []):
        booking = db.bookings.get(booking_id)
        if booking is None:
            continue
        delta = waiver.get('_waived_deltas', {}).get(booking_id, 0)
        if delta:
            booking['change_fee_waived_cents'] -= delta
        if not others_active:
            booking['waiver_applied'] = False
        recompute_booking_money(booking)
        touch(booking)
    touch(waiver)
    changed = recompute_flight_counters(flight)
    if flight['active_waiver_count'] == 0 and flight['irops_state'] == 'IRREGULAR':
        flight['irops_state'] = 'RECOVERED'
        if not changed:
            touch(flight)


# --------------------------------------------------------------------------
# path / body reference resolution (PRD 2.7 steps 4 and 5)
# --------------------------------------------------------------------------
def resolve(table, key, error_id):
    from errors import fail as _fail
    record = table.get(key) if isinstance(key, str) else None
    if record is None:
        _fail(error_id)
    return record


def product_or_404(key):
    return resolve(db.products, key, 'ERR_ANCILLARY_PRODUCT_NOT_FOUND')


def family_or_404(key):
    return resolve(db.families, key, 'ERR_FARE_FAMILY_NOT_FOUND')


def attribute_or_404(key):
    return resolve(db.attributes, key, 'ERR_FAMILY_ATTRIBUTE_NOT_FOUND')


def flight_or_404(key):
    return resolve(db.flights, key, 'ERR_FLIGHT_NOT_FOUND')


def segment_or_404(key):
    return resolve(db.segments, key, 'ERR_SEAT_SEGMENT_NOT_FOUND')


def channel_or_404(key):
    return resolve(db.channels, key, 'ERR_DISTRIBUTION_CHANNEL_NOT_FOUND')


def publication_or_404(key):
    return resolve(db.publications, key, 'ERR_CHANNEL_PUBLICATION_NOT_FOUND')


def booking_or_404(key):
    return resolve(db.bookings, key, 'ERR_BOOKING_NOT_FOUND')


def offer_or_404(key):
    return resolve(db.offers, key, 'ERR_ANCILLARY_OFFER_NOT_FOUND')


def assignment_or_404(key):
    return resolve(db.assignments, key, 'ERR_SEAT_ASSIGNMENT_NOT_FOUND')


def waiver_or_404(key):
    return resolve(db.waivers, key, 'ERR_IROPS_WAIVER_NOT_FOUND')
