"""Path / foreign-key resolution (ladder steps 3-4)."""

import store
from errors import ApiError


def _get(collection, ident, error_id, label):
    if not isinstance(ident, str) or not ident:
        raise ApiError(error_id, "%s not found" % label)
    row = collection.get(ident)
    if row is None:
        raise ApiError(error_id, "%s not found: %s" % (label, ident))
    return row


def product(ident):
    return _get(store.db.products, ident, "ERR_PRODUCT_NOT_FOUND", "product")


def design_revision(ident):
    return _get(
        store.db.design_revisions, ident, "ERR_DESIGN_REVISION_NOT_FOUND", "design revision"
    )


def product_document(ident):
    return _get(
        store.db.product_documents, ident, "ERR_PRODUCT_DOCUMENT_NOT_FOUND", "product document"
    )


def test_bench(ident):
    return _get(store.db.test_benches, ident, "ERR_TEST_BENCH_NOT_FOUND", "test bench")


def bench_reservation(ident):
    return _get(
        store.db.bench_reservations,
        ident,
        "ERR_BENCH_RESERVATION_NOT_FOUND",
        "bench reservation",
    )


def test_campaign(ident):
    return _get(store.db.test_campaigns, ident, "ERR_TEST_CAMPAIGN_NOT_FOUND", "test campaign")


def production_lot(ident):
    return _get(
        store.db.production_lots, ident, "ERR_PRODUCTION_LOT_NOT_FOUND", "production lot"
    )


def listing_body(ident):
    return _get(store.db.listing_bodies, ident, "ERR_LISTING_BODY_NOT_FOUND", "listing body")


def listing_record(ident):
    return _get(
        store.db.listing_records, ident, "ERR_LISTING_RECORD_NOT_FOUND", "listing record"
    )


def consumer_registration(ident):
    return _get(
        store.db.consumer_registrations,
        ident,
        "ERR_CONSUMER_REGISTRATION_NOT_FOUND",
        "consumer registration",
    )


def field_incident(ident):
    return _get(store.db.field_incidents, ident, "ERR_FIELD_INCIDENT_NOT_FOUND", "field incident")


def corrective_action(ident):
    return _get(
        store.db.corrective_actions,
        ident,
        "ERR_CORRECTIVE_ACTION_NOT_FOUND",
        "corrective action",
    )


def recall_event(ident):
    return _get(store.db.recall_events, ident, "ERR_RECALL_EVENT_NOT_FOUND", "recall event")


# --------------------------------------------------------------------------
# collection scans
# --------------------------------------------------------------------------
def rows(collection):
    return list(collection.values())


def where(collection, **criteria):
    result = []
    for row in collection.values():
        keep = True
        for field, wanted in criteria.items():
            if row.get(field) != wanted:
                keep = False
                break
        if keep:
            result.append(row)
    return result


def lots_of_product(product_id):
    return where(store.db.production_lots, product_id=product_id)


def listings_of_product(product_id):
    return where(store.db.listing_records, product_id=product_id)


def registrations_of_lot(lot_id):
    return where(store.db.consumer_registrations, production_lot_id=lot_id)


def registrations_of_product(product_id):
    lot_ids = set(lot["id"] for lot in lots_of_product(product_id))
    return [
        row
        for row in store.db.consumer_registrations.values()
        if row["production_lot_id"] in lot_ids
    ]


def incidents_of_product(product_id):
    return where(store.db.field_incidents, product_id=product_id)


def campaigns_of_product(product_id):
    return where(store.db.test_campaigns, product_id=product_id)


def load_tests_of_campaign(campaign_id):
    return where(store.db.load_tests, test_campaign_id=campaign_id)


def samples_of_lot(lot_id):
    return where(store.db.joint_samples, production_lot_id=lot_id)


def revisions_of_product(product_id):
    return where(store.db.design_revisions, product_id=product_id)


def documents_of_product(product_id):
    return where(store.db.product_documents, product_id=product_id)


def actions_of_incident(incident_id):
    return where(store.db.corrective_actions, field_incident_id=incident_id)
