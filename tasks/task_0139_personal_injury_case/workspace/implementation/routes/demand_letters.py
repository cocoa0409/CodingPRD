"""DemandLetter endpoints (PRD §3.5)."""
from __future__ import annotations

from datetime import timedelta

from flask import Blueprint

from config import DEMAND_RESPONSE_DUE_DAYS, ROLE_ATTORNEY
from db import store
from errors import raise_error
from middleware import require_auth
from response import success
from routes._helpers import get_json_body, require_field
from services.calculations import is_sol_expired
from services.case_engine import (
    assert_case_not_closed,
    check_version_match,
    find_active_demand_letter,
    get_case_or_404,
    now,
    touch,
)
from services.serializers import demand_letter_to_dict
from utils import new_uuid


bp = Blueprint("demand_letters", __name__)


def _get_letter_or_404(cid: str, lid: str) -> dict:
    get_case_or_404(cid)
    letter = store.demand_letters.get(lid)
    if not letter or letter["case_id"] != cid:
        raise_error("ERR_NOT_FOUND", f"DemandLetter {lid} not found on case {cid}.")
    return letter


@bp.post("/pi-cases/<cid>/demand-letters")
@require_auth([ROLE_ATTORNEY])
def draft_letter(cid):
    body = get_json_body()
    case_row = get_case_or_404(cid)
    assert_case_not_closed(case_row)

    if case_row["status"] != "READY_FOR_DEMAND":
        raise_error(
            "ERR_INVALID_STATE",
            f"Case must be READY_FOR_DEMAND (was {case_row['status']}).",
        )

    if "demanded_amount_cents" not in body:
        raise_error("ERR_VALIDATION", "demanded_amount_cents is required.")
    demanded = body["demanded_amount_cents"]
    if not isinstance(demanded, int) or isinstance(demanded, bool) or demanded <= 0:
        raise_error("ERR_VALIDATION", "demanded_amount_cents must be a positive integer.")

    # At-most-one ACTIVE letter per case.
    if find_active_demand_letter(cid):
        raise_error(
            "ERR_ACTIVE_DEMAND_EXISTS",
            "An active demand letter (DRAFT or SENT) already exists on this case.",
        )

    # Demanded amount must cover current total damages.
    damages_id = store.damages_by_case.get(cid)
    if not damages_id:
        raise_error(
            "ERR_INVALID_STATE",
            "Cannot draft demand letter without Damages row.",
        )
    damages = store.damages[damages_id]
    if int(demanded) < int(damages["total_damages_cents"]):
        raise_error(
            "ERR_DEMAND_BELOW_DAMAGES",
            "demanded_amount_cents must be >= Damages.total_damages_cents.",
        )

    with store.lock:
        row = {
            "id": new_uuid(),
            "case_id": cid,
            "created_at": now(),
            "updated_at": now(),
            "version": 1,
            "demanded_amount_cents": int(demanded),
            "snapshot_total_damages_cents": 0,
            "snapshot_damages_version": 0,
            "status": "DRAFT",
            "sent_at": None,
            "response_due_at": None,
        }
        store.demand_letters[row["id"]] = row

    return success(demand_letter_to_dict(row), 201)


@bp.post("/pi-cases/<cid>/demand-letters/<lid>/send")
@require_auth([ROLE_ATTORNEY])
def send_letter(cid, lid):
    body = get_json_body()
    case_row = get_case_or_404(cid)
    letter = _get_letter_or_404(cid, lid)
    assert_case_not_closed(case_row)

    check_version_match(letter, body.get("version"))

    if letter["status"] != "DRAFT":
        raise_error("ERR_DEMAND_NOT_DRAFT", f"DemandLetter is not DRAFT (was {letter['status']}).")
    if case_row["status"] != "READY_FOR_DEMAND":
        raise_error(
            "ERR_INVALID_STATE",
            f"Case must be READY_FOR_DEMAND (was {case_row['status']}).",
        )

    # SoL must not be expired.
    if is_sol_expired(case_row, now()):
        raise_error("ERR_STATUTE_OF_LIMITATIONS_EXPIRED", "Case is out of statute.")

    damages_id = store.damages_by_case.get(cid)
    if not damages_id:
        raise_error("ERR_INVALID_STATE", "Damages row not found.")
    damages = store.damages[damages_id]

    # Optional damages-version assertion (PRD §3.5 stale-damages snapshot).
    if "expected_damages_version" in body:
        expected = body["expected_damages_version"]
        if not isinstance(expected, int):
            raise_error("ERR_VALIDATION", "expected_damages_version must be integer.")
        if int(expected) != int(damages["version"]):
            raise_error(
                "ERR_STALE_DAMAGES_SNAPSHOT",
                "expected_damages_version does not match current Damages.version.",
            )

    if int(letter["demanded_amount_cents"]) < int(damages["total_damages_cents"]):
        raise_error(
            "ERR_DEMAND_BELOW_DAMAGES",
            "demanded_amount_cents no longer covers current Damages.total_damages_cents.",
        )

    with store.lock:
        ts = now()
        letter["sent_at"] = ts
        letter["response_due_at"] = ts + timedelta(days=DEMAND_RESPONSE_DUE_DAYS)
        letter["snapshot_total_damages_cents"] = int(damages["total_damages_cents"])
        letter["snapshot_damages_version"] = int(damages["version"])
        letter["status"] = "SENT"
        touch(letter)

        case_row["status"] = "DEMAND_SENT"
        touch(case_row)

    return success(demand_letter_to_dict(letter), 200)


@bp.post("/pi-cases/<cid>/demand-letters/<lid>/withdraw")
@require_auth([ROLE_ATTORNEY])
def withdraw_letter(cid, lid):
    body = get_json_body()
    case_row = get_case_or_404(cid)
    letter = _get_letter_or_404(cid, lid)
    assert_case_not_closed(case_row)

    check_version_match(letter, body.get("version"))

    if letter["status"] != "DRAFT":
        raise_error("ERR_DEMAND_NOT_DRAFT", f"DemandLetter is not DRAFT (was {letter['status']}).")

    with store.lock:
        letter["status"] = "WITHDRAWN"
        touch(letter)

    return success(demand_letter_to_dict(letter), 200)
