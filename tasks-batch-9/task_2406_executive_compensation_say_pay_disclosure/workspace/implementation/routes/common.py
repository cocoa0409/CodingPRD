"""Route helpers shared by every blueprint."""

from db import store
from errors import ApiError
from middleware import pagination, window
from response import list_response

NOT_FOUND = {
    "companies": "ERR_COMPANY_NOT_FOUND",
    "executives": "ERR_EXECUTIVE_NOT_FOUND",
    "peer_groups": "ERR_PEER_GROUP_NOT_FOUND",
    "peer_group_members": "ERR_PEER_GROUP_MEMBER_NOT_FOUND",
    "pay_programs": "ERR_PAY_PROGRAM_NOT_FOUND",
    "incentive_metrics": "ERR_INCENTIVE_METRIC_NOT_FOUND",
    "payout_awards": "ERR_PAYOUT_AWARD_NOT_FOUND",
    "cda_drafts": "ERR_CDA_DRAFT_NOT_FOUND",
    "proxy_advisor_screens": "ERR_SCREEN_NOT_FOUND",
    "outreach_engagements": "ERR_ENGAGEMENT_NOT_FOUND",
    "restatement_events": "ERR_RESTATEMENT_EVENT_NOT_FOUND",
    "clawback_determinations": "ERR_DETERMINATION_NOT_FOUND",
}


def fetch(table_name, row_id):
    table = getattr(store, table_name)
    row = table.get(row_id) if isinstance(row_id, str) else None
    if row is None:
        raise ApiError(NOT_FOUND[table_name])
    return row


def body_fk(body, key, table_name):
    """Ladder step 4: resolve a body foreign key.

    An absent reference is left to step 6 (ERR_INVALID_REQUEST); a present but
    unresolvable one raises the not-found error of the entity it points at.
    """
    if key not in body.raw or body.raw[key] is None:
        return None
    value = body.raw[key]
    table = getattr(store, table_name)
    if not isinstance(value, str) or value not in table:
        raise ApiError(NOT_FOUND[table_name])
    return table[value]


def paginated(rows):
    limit, offset = pagination()
    total = len(rows)
    return list_response(window(rows, limit, offset), limit, offset, total)
