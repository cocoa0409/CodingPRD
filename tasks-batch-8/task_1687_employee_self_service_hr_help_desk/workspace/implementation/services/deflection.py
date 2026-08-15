"""Deflection link (ticket intake) and deflection rate (metrics)."""
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

import db

DEFLECTION_WINDOW_MINUTES = 60
DEFLECTION_WINDOW_DAYS = 30


def link_deflection(ticket):
    """Scan the requester's recent unconsumed article views in the ticket's
    category (viewed no earlier than 60 minutes before creation, boundary
    inclusive); consume the latest one. Returns the chosen view or None."""
    created = ticket['created_at']
    cutoff = created - timedelta(minutes=DEFLECTION_WINDOW_MINUTES)
    candidates = []
    for v in db.article_views.values():
        if v['employee_id'] != ticket['employee_id']:
            continue
        if v['deflection_outcome'] != 'NONE':
            continue
        if v['viewed_at'] < cutoff or v['viewed_at'] > created:
            continue
        article = db.articles.get(v['article_id'])
        if article is None or article['category_id'] != ticket['category_id']:
            continue
        candidates.append(v)
    if not candidates:
        return None
    # Latest viewed_at; ties broken by later created_at (== insertion order,
    # since viewed_at == created_at and the logical clock may tie).
    chosen = max(candidates, key=lambda v: (v['viewed_at'], v['_seq']))
    chosen['deflection_outcome'] = 'TICKET_CREATED'
    ticket['source_article_id'] = chosen['article_id']
    return chosen


def deflection_rate(category_id, now=None):
    """Return (view_count, ticket_created_count, deflection_rate Decimal 4dp).

    Views of the category's articles with viewed_at inside the trailing 30
    days, both ends inclusive; rate == 1 - created/views; 0.0 on empty set.
    """
    now = now or db.now()
    lo = now - timedelta(days=DEFLECTION_WINDOW_DAYS)
    views = 0
    created = 0
    for v in db.article_views.values():
        article = db.articles.get(v['article_id'])
        if article is None or article['category_id'] != category_id:
            continue
        if not (lo <= v['viewed_at'] <= now):
            continue
        views += 1
        if v['deflection_outcome'] == 'TICKET_CREATED':
            created += 1
    if views == 0:
        return 0, 0, Decimal('0.0')
    rate = (Decimal(1) - Decimal(created) / Decimal(views)).quantize(
        Decimal('0.0001'), rounding=ROUND_HALF_UP)
    return views, created, rate
