"""Trust ledger reads (PRD 2.11)."""
from flask import Blueprint

import constants as C
import db
from routes._common import listing, read_one

bp = Blueprint("ledger", __name__)


@bp.get("/ledger-entries/<ledger_entry_id>")
def get_ledger_entry(ledger_entry_id):
    return read_one("ledger_entry", C.READ_TENANT_SIDE, ledger_entry_id)


@bp.get("/ledger-entries")
def list_ledger_entries():
    return listing(db.ledger_entries, C.READ_TENANT_SIDE,
                   str_filters=("trust_id", "reversal_of_entry_id", "entry_type",
                                "bucket", "source_kind"))
