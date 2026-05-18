"""Logical clock endpoint."""
from __future__ import annotations

from flask import Blueprint, jsonify

from ..auth import require_roles
from ..envelope import success_object
from ..errors import err_time_travel
from ..services.clock_sweep import run_sweep
from ..store import reset_store, store
from ..util import format_iso8601, parse_iso8601
from ._helpers import get_json_body, require_field

bp = Blueprint("clock", __name__)


@bp.route("/hoa/_clock/advance", methods=["POST"])
@require_roles(["PresidentRole"])
def advance_clock():
    body = get_json_body()
    target = parse_iso8601(require_field(body, "target_timestamp"))

    s = store()
    if target < s.now():
        raise err_time_travel()

    s.set_now(target)
    run_sweep()

    body_out = {"now": format_iso8601(s.now())}
    return jsonify(success_object(body_out)), 200


# Test-only helper: reset all in-memory state so tests are isolated.
# Not declared by PRD; tests call it via conftest with try/except so its
# presence is optional, but supplying it makes the suite deterministic.
#
# Pre-seeds the four well-known bootstrap board members so the shared
# *_role_headers constants resolve to real Member rows with the
# corresponding board_role set — this is what PRD §2.1's identity check
# expects ("X-User-ID is the id of the Member who currently holds that
# board seat"). Without this seeding, every fixture that issues
# board-role calls under the shared headers would fail the seat check.
BOOTSTRAP_MEMBERS = [
    ("president-bootstrap-0001", "PRESIDENT", "President Bootstrap"),
    ("treasurer-bootstrap-0001", "TREASURER", "Treasurer Bootstrap"),
    ("secretary-bootstrap-0001", "SECRETARY", "Secretary Bootstrap"),
    ("director-bootstrap-0001",  "DIRECTOR",  "Director Bootstrap"),
]


def _seed_bootstrap_board() -> None:
    s = store()
    now = s.now()
    for mid, seat, name in BOOTSTRAP_MEMBERS:
        m = {
            "id": mid,
            "full_name": name,
            "email": f"{seat.lower()}@bootstrap.invalid",
            "board_role": seat,
            "total_overdue_amount_cents": 0,
            "eligible_to_vote": False,
            "created_at": now,
            "updated_at": now,
            "version": 1,
        }
        s.insert("members", m)


@bp.route("/hoa/__test__/reset", methods=["POST"])
def __test_reset():
    reset_store()
    _seed_bootstrap_board()
    s = store()
    return jsonify(success_object({
        "reset": True,
        "now": format_iso8601(s.now()),
    })), 200
