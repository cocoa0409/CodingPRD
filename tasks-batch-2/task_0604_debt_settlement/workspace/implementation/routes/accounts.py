from flask import Blueprint, g, request

from db import store
from errors import fail, ERR_NOT_PROGRAM_OWNER
from middleware import require_roles
from response import success
from routes.helpers import lookup, paginate, sort_by_created
from services.serialize import account_out

bp = Blueprint("accounts", __name__)


def _scope_program_for_client(program_id):
    p = store.programs.get(program_id)
    if g.role == "Client" and (p is None or p["client_id"] != g.user_id):
        fail(ERR_NOT_PROGRAM_OWNER, "Client may only read their own program's account")


@bp.get("/accounts/<aid>")
@require_roles("ProgramAdmin", "NegotiationAgent", "Client")
def get_account(aid):
    a = lookup(store.accounts, aid)
    _scope_program_for_client(a["program_id"])
    return success(account_out(a))


@bp.get("/accounts")
@require_roles("ProgramAdmin", "NegotiationAgent", "Client")
def list_accounts():
    items = list(store.accounts.values())
    program_id = request.args.get("program_id")
    if program_id is not None:
        items = [a for a in items if a["program_id"] == program_id]
    if g.role == "Client":
        items = [a for a in items
                 if store.programs.get(a["program_id"], {}).get("client_id") == g.user_id]
    items = sort_by_created(items)
    page, pagination = paginate(items)
    return success([account_out(a) for a in page], pagination=pagination)
