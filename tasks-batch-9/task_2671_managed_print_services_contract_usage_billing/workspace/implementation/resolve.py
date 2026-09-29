"""Path- and body-supplied identifier resolution (PRD 2.7)."""
from errors import fail
from store import db

_SPECS = (
    ("contract", "contracts", "ERR_CONTRACT_NOT_FOUND", "Contract"),
    ("site", "sites", "ERR_SITE_NOT_FOUND", "Site"),
    ("device", "devices", "ERR_DEVICE_NOT_FOUND", "Device"),
    ("technician", "technicians", "ERR_TECHNICIAN_NOT_FOUND", "Technician"),
    ("read", "meter_reads", "ERR_METER_READ_NOT_FOUND", "Meter read"),
    ("period", "periods", "ERR_PERIOD_NOT_FOUND", "Billing period"),
    ("statement", "statements", "ERR_STATEMENT_NOT_FOUND", "Billing statement"),
    ("order", "orders", "ERR_ORDER_NOT_FOUND", "Consumable order"),
    ("ticket", "tickets", "ERR_TICKET_NOT_FOUND", "Service ticket"),
    ("review", "reviews", "ERR_REVIEW_NOT_FOUND", "Quarterly review"),
    ("removal", "removals", "ERR_REMOVAL_ORDER_NOT_FOUND", "Removal order"),
)


def _make(collection, error_id, label):
    def getter(row_id):
        row = getattr(db, collection).get(row_id)
        if row is None:
            fail(error_id, "%s '%s' was not found." % (label, row_id))
        return row
    return getter


get_contract = _make("contracts", "ERR_CONTRACT_NOT_FOUND", "Contract")
get_site = _make("sites", "ERR_SITE_NOT_FOUND", "Site")
get_device = _make("devices", "ERR_DEVICE_NOT_FOUND", "Device")
get_technician = _make("technicians", "ERR_TECHNICIAN_NOT_FOUND", "Technician")
get_read = _make("meter_reads", "ERR_METER_READ_NOT_FOUND", "Meter read")
get_period = _make("periods", "ERR_PERIOD_NOT_FOUND", "Billing period")
get_statement = _make("statements", "ERR_STATEMENT_NOT_FOUND", "Billing statement")
get_order = _make("orders", "ERR_ORDER_NOT_FOUND", "Consumable order")
get_ticket = _make("tickets", "ERR_TICKET_NOT_FOUND", "Service ticket")
get_review = _make("reviews", "ERR_REVIEW_NOT_FOUND", "Quarterly review")
get_removal = _make("removals", "ERR_REMOVAL_ORDER_NOT_FOUND", "Removal order")
