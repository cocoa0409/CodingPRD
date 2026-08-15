from flask import Blueprint

from constants import ALL_ROLES
from db import store, pub
from middleware import authenticate
from response import success
from services.domain import get_or_404, list_response

bp = Blueprint("ledger", __name__)


@bp.route("/endowment/ledger-entries", methods=["GET"])
def list_ledger_entries():
    authenticate(ALL_ROLES)
    return list_response(
        store.ledger,
        [
            ("fund_id", "fund_id", "str"),
            ("entry_type", "entry_type", "str"),
            ("quarter_index", "quarter_index", "int"),
        ],
    )


@bp.route("/endowment/ledger-entries/<entry_id>", methods=["GET"])
def get_ledger_entry(entry_id):
    authenticate(ALL_ROLES)
    return success(pub(get_or_404(store.ledger, entry_id, "UnitLedgerEntry")))
