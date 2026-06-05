"""RenewalCycle endpoints (PRD §3.3, §3.8) including renew + certificate issuance."""

from flask import Blueprint, g, request

import clock
import errors
import serialize
import services.cycle as cycle_service
from common import (
    get_json_body,
    require_string,
    require_number,
    require_field,
    optional_field,
    parse_pagination,
    paginate,
)
from db import db
from middleware import require_roles
from models import new_full_record, new_lightweight_record, bump
from response import success_object, success_list
from routes.license_boards import get_board_or_404
from routes.licensees import get_licensee_or_404
from util import parse_iso, add_months, round_half_up_1, as_decimal

bp = Blueprint("renewal_cycles", __name__)


def get_cycle_or_404(cycle_id):
    c = db.renewal_cycles.get(cycle_id)
    if c is None:
        raise errors.not_found(f"RenewalCycle '{cycle_id}' not found.")
    return c


def _has_nonterminal_audit(cycle_id):
    for a in db.audits.values():
        if a["cycle_id"] == cycle_id and a["status"] not in ("PASSED", "FAILED"):
            return True
    return False


@bp.route("/renewal-cycles", methods=["POST"])
@require_roles("BoardAdmin", "Licensee")
def create_renewal_cycle():
    body = get_json_body()
    licensee_id = require_string(body, "licensee_id")
    board_id = require_string(body, "board_id")
    cycle_start_raw = require_field(body, "cycle_start")
    cycle_start = parse_iso(cycle_start_raw, field="cycle_start")

    carryover_in_hours = optional_field(body, "carryover_in_hours", default=0, types=(int, float))
    if carryover_in_hours is None:
        carryover_in_hours = 0
    if isinstance(carryover_in_hours, bool) or not isinstance(carryover_in_hours, (int, float)):
        raise errors.invalid_request("carryover_in_hours must be a number.")
    if carryover_in_hours < 0:
        raise errors.validation_range("carryover_in_hours must be >= 0.")
    carryover_in_hours = round_half_up_1(carryover_in_hours)

    # Existence (404) before ownership (403).
    licensee = get_licensee_or_404(licensee_id)
    board = get_board_or_404(board_id)

    # Ownership: a Licensee may only open a cycle for its own licensee_id.
    if g.user_role == "Licensee" and g.user_id != licensee_id:
        raise errors.not_resource_owner(
            "Licensee may only open renewal cycles for its own licensee_id."
        )

    cycle_end = add_months(cycle_start, board["cycle_length_months"])

    with db.lock:
        # Overlap check (closed-open): adjacency allowed (new start == prior end).
        siblings = [
            c for c in db.renewal_cycles.values()
            if c["licensee_id"] == licensee_id and c["board_id"] == board_id
        ]
        for other in siblings:
            # New start lands strictly inside [other.start, other.end) -> overlap.
            if other["cycle_start"] <= cycle_start < other["cycle_end"]:
                raise errors.cycle_overlap(
                    "New cycle overlaps an existing cycle for this licensee+board."
                )
            # New interval [start,end) contains the other's start strictly inside.
            if cycle_start <= other["cycle_start"] < cycle_end:
                raise errors.cycle_overlap(
                    "New cycle overlaps an existing cycle for this licensee+board."
                )

        # Carryover conservation + cap (PRD §3.3). carryover_in must not exceed the
        # immediately prior cycle's carryover_out_hours, nor the board cap.
        if carryover_in_hours > 0:
            if carryover_in_hours > board["carryover_cap_hours"]:
                raise errors.carryover_exceeds_cap(
                    "carryover_in_hours exceeds the board carryover cap."
                )
            # Prior cycle = the sibling whose cycle_end is the latest <= cycle_start.
            prior = None
            for other in siblings:
                if other["cycle_end"] <= cycle_start:
                    if prior is None or other["cycle_end"] > prior["cycle_end"]:
                        prior = other
            prior_out = prior["carryover_out_hours"] if prior is not None else 0
            if as_decimal(carryover_in_hours) > as_decimal(prior_out):
                raise errors.carryover_exceeds_cap(
                    "carryover_in_hours exceeds the prior cycle's carryover_out_hours."
                )

        rec = new_full_record()
        rec.update({
            "licensee_id": licensee_id,
            "board_id": board_id,
            "cycle_start": cycle_start,
            "cycle_end": cycle_end,
            "status": "OPEN",
            "carryover_in_hours": carryover_in_hours,
            "carryover_out_hours": 0,
            "provisional_earned_hours": 0,
            "final_earned_hours": 0,
            "reciprocity_hours": 0,
        })
        # Seed earned-hour fields from carryover_in_hours.
        cycle_service.recompute_credit_tally(rec)
        db.renewal_cycles[rec["id"]] = rec

    return success_object(serialize.renewal_cycle(rec), status=201)


@bp.route("/renewal-cycles/<cycle_id>", methods=["GET"])
@require_roles("BoardAdmin", "Licensee", "Auditor")
def get_renewal_cycle(cycle_id):
    c = get_cycle_or_404(cycle_id)
    return success_object(serialize.renewal_cycle(c), status=200)


@bp.route("/renewal-cycles", methods=["GET"])
@require_roles("BoardAdmin", "Auditor")
def list_renewal_cycles():
    limit, offset = parse_pagination()
    board_id = request.args.get("board_id")
    licensee_id = request.args.get("licensee_id")
    items = list(db.renewal_cycles.values())
    if board_id is not None:
        items = [c for c in items if c["board_id"] == board_id]
    if licensee_id is not None:
        items = [c for c in items if c["licensee_id"] == licensee_id]
    items.sort(key=lambda r: r["created_at"])
    total = len(items)
    page = paginate(items, limit, offset)
    return success_list(
        [serialize.renewal_cycle(c) for c in page], limit, offset, total, status=200,
    )


@bp.route("/licensees/<licensee_id>/renewal-cycles", methods=["GET"])
@require_roles("BoardAdmin", "Licensee", "Auditor")
def list_licensee_renewal_cycles(licensee_id):
    get_licensee_or_404(licensee_id)
    limit, offset = parse_pagination()
    items = [c for c in db.renewal_cycles.values() if c["licensee_id"] == licensee_id]
    items.sort(key=lambda r: r["created_at"])
    total = len(items)
    page = paginate(items, limit, offset)
    return success_list(
        [serialize.renewal_cycle(c) for c in page], limit, offset, total, status=200,
    )


@bp.route("/renewal-cycles/<cycle_id>/reminder", methods=["GET"])
@require_roles("BoardAdmin", "Licensee", "Auditor")
def get_reminder(cycle_id):
    c = get_cycle_or_404(cycle_id)
    return success_object(serialize.renewal_cycle(c), status=200)


@bp.route("/renewal-cycles/<cycle_id>/renew", methods=["POST"])
@require_roles("Licensee")
def renew_cycle(cycle_id):
    c = get_cycle_or_404(cycle_id)
    body = get_json_body()
    expected_version = require_field(body, "expected_renewal_cycle_version")
    if isinstance(expected_version, bool) or not isinstance(expected_version, int):
        raise errors.invalid_request("expected_renewal_cycle_version must be an integer.")

    # Ownership: a Licensee may only renew its own cycle (priority 4, before state).
    if g.user_role == "Licensee" and g.user_id != c["licensee_id"]:
        raise errors.not_resource_owner(
            "Licensee may only renew its own renewal cycles."
        )

    with db.lock:
        # State gate (priority 5): must be REQUIREMENTS_MET to renew.
        if c["status"] != "REQUIREMENTS_MET":
            raise errors.invalid_state(
                "RenewalCycle must be REQUIREMENTS_MET to renew."
            )

        # No non-terminal audit may exist for this cycle.
        if _has_nonterminal_audit(cycle_id):
            raise errors.invalid_state(
                "Cannot renew while an audit for this cycle is non-terminal."
            )

        # Requirements-met gate on VERIFIED hours (priority 13).
        if not cycle_service.requirement_met(c):
            raise errors.requirements_not_met(
                "Verified hours do not satisfy the cycle requirement."
            )

        # OCC check (priority 15): expected version must match current.
        if expected_version != c["version"]:
            raise errors.stale_version(
                "expected_renewal_cycle_version does not match the cycle's version."
            )

        # Issue certificate, finalize carryover, advance to RENEWED.
        c["carryover_out_hours"] = cycle_service.compute_carryover_out(c)
        c["status"] = "RENEWED"
        bump(c)

        board = db.license_boards[c["board_id"]]
        seq = db.cert_serial_counters.get(board["id"], 0) + 1
        db.cert_serial_counters[board["id"]] = seq
        serial = f"{board['jurisdiction_code']}-{seq:06d}"

        cert = new_lightweight_record()
        cert.update({
            "cycle_id": c["id"],
            "serial_number": serial,
            "total_hours_certified": c["final_earned_hours"],
            "issued_at": cert["created_at"],
        })
        db.certificates[cert["id"]] = cert

    return success_object(serialize.renewal_cycle(c), status=200)
