"""Row lookup helpers over the in-memory store."""
from db import by_created, db
from errors import ApiError

NOT_FOUND = {
    "participants": "ERR_PARTICIPANT_NOT_FOUND",
    "conformance_tests": "ERR_CONFORMANCE_TEST_NOT_FOUND",
    "consent_policies": "ERR_CONSENT_POLICY_NOT_FOUND",
    "threshold_configs": "ERR_THRESHOLD_CONFIG_NOT_FOUND",
    "patient_records": "ERR_PATIENT_RECORD_NOT_FOUND",
    "clusters": "ERR_CLUSTER_NOT_FOUND",
    "match_links": "ERR_MATCH_LINK_NOT_FOUND",
    "directives": "ERR_DIRECTIVE_NOT_FOUND",
    "queries": "ERR_QUERY_NOT_FOUND",
    "audit_entries": "ERR_AUDIT_ENTRY_NOT_FOUND",
    "break_glass": "ERR_BREAK_GLASS_NOT_FOUND",
    "subscriptions": "ERR_SUBSCRIPTION_NOT_FOUND",
    "data_feeds": "ERR_DATA_FEED_NOT_FOUND",
    "samples": "ERR_DATA_FEED_NOT_FOUND",
    "invoices": "ERR_INVOICE_NOT_FOUND",
}


def table(name):
    return getattr(db, name)


def get(name, row_id):
    if not isinstance(row_id, str):
        return None
    return table(name).get(row_id)


def must(name, row_id):
    row = get(name, row_id)
    if row is None:
        raise ApiError(NOT_FOUND[name])
    return row


def all_rows(name):
    return by_created(list(table(name).values()))


def where(name, **filters):
    rows = []
    for row in table(name).values():
        keep = True
        for key, value in filters.items():
            if row.get(key) != value:
                keep = False
                break
        if keep:
            rows.append(row)
    return by_created(rows)


def where_in(name, field, values):
    values = tuple(values)
    return by_created([r for r in table(name).values() if r.get(field) in values])


def first(rows):
    return rows[0] if rows else None


# ------------------------------------------------------------ domain shortcuts
def participant(participant_id):
    return get("participants", participant_id)


def cluster_members(cluster_id):
    """Records whose cluster_id points at this cluster and that are CLUSTERED."""
    return by_created(
        [
            r
            for r in db.patient_records.values()
            if r["cluster_id"] == cluster_id and r["match_state"] == "CLUSTERED"
        ]
    )


def cluster_records(cluster_id):
    """Every record currently pointing at the cluster, whatever its match_state."""
    return by_created(
        [r for r in db.patient_records.values() if r["cluster_id"] == cluster_id]
    )


def active_threshold_config():
    rows = where("threshold_configs", status="ACTIVE")
    return rows[-1] if rows else None


def active_policy_at(moment):
    from db import parse_iso

    candidates = []
    for row in where("consent_policies", status="ACTIVE"):
        start = parse_iso(row["effective_from"])
        until = parse_iso(row["effective_until"]) if row["effective_until"] else None
        if start is not None and start <= moment and (until is None or moment < until):
            candidates.append(row)
    return candidates[-1] if candidates else None


def participant_feeds(participant_id):
    return where("data_feeds", participant_id=participant_id)


def feed_samples(feed_id):
    return where("samples", data_feed_id=feed_id)


def participant_invoices(participant_id):
    return where("invoices", participant_id=participant_id)


def has_delinquent_invoice(participant_id):
    for row in db.invoices.values():
        if row["participant_id"] == participant_id and row["status"] == "DELINQUENT":
            return True
    return False


def participant_subscriptions(participant_id):
    return where("subscriptions", subscriber_participant_id=participant_id)


def queries_citing(session_id):
    return where("queries", break_glass_id=session_id)


def audit_for_query(query_id):
    return where("audit_entries", query_id=query_id)
