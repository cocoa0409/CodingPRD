"""Path / body identifier resolution (PRD 2.5, precedence steps 3 and 4)."""
import db
from errors import fail


def path_record(table, key, error_id):
    record = table.get(key)
    if record is None:
        fail(error_id)
    return record


def season(season_id):
    return path_record(db.db.seasons, season_id, "ERR_SEASON_NOT_FOUND")


def episode(episode_id):
    return path_record(db.db.episodes, episode_id, "ERR_EPISODE_NOT_FOUND")


def cluster(cluster_id):
    return path_record(db.db.clusters, cluster_id, "ERR_CLUSTER_NOT_FOUND")


def live_event(event_id):
    return path_record(db.db.live_events, event_id, "ERR_LIVE_EVENT_NOT_FOUND")


def player(player_id):
    return path_record(db.db.players, player_id, "ERR_PLAYER_NOT_FOUND")


def account(account_id):
    return path_record(db.db.accounts, account_id, "ERR_CURRENCY_ACCOUNT_NOT_FOUND")


def ledger_entry(entry_id):
    return path_record(db.db.ledger, entry_id, "ERR_LEDGER_ENTRY_NOT_FOUND")


def offer(offer_id):
    return path_record(db.db.offers, offer_id, "ERR_OFFER_NOT_FOUND")


def disclosure(offer_record, disclosure_id):
    record = db.db.disclosures.get(disclosure_id)
    if record is None or record["offer_id"] != offer_record["id"]:
        fail("ERR_DISCLOSURE_NOT_FOUND")
    return record


def purchase(purchase_id):
    return path_record(db.db.purchases, purchase_id, "ERR_PURCHASE_NOT_FOUND")


def refund_request(request_id):
    return path_record(db.db.refunds, request_id, "ERR_REFUND_REQUEST_NOT_FOUND")


def balance_change(change_id):
    return path_record(db.db.balance_changes, change_id, "ERR_BALANCE_CHANGE_NOT_FOUND")


def comms_notice(change, notice_id):
    record = db.db.notices.get(notice_id)
    if record is None or record["balance_change_id"] != change["id"]:
        fail("ERR_COMMS_NOTICE_NOT_FOUND")
    return record


def monitoring_run(run_id):
    return path_record(db.db.monitoring_runs, run_id, "ERR_MONITORING_RUN_NOT_FOUND")


def account_of_player(player_record, account_id):
    record = db.db.accounts.get(account_id)
    if record is None or record["player_id"] != player_record["id"]:
        fail("ERR_CURRENCY_ACCOUNT_NOT_FOUND")
    return record


def body_fk(payload, name, table, error_id):
    """Step 4 runs before step 5, so a well-formed identifier is resolved first.

    A missing or non-string value is left to the schema pass, which answers
    ERR_INVALID_REQUEST.
    """
    value = payload.get(name)
    if isinstance(value, str) and value:
        record = table.get(value)
        if record is None:
            fail(error_id)
        return record
    return None
