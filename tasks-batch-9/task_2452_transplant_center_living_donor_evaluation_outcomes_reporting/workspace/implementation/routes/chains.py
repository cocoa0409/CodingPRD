"""Exchange chains, chain segments, organ offers and transplant completion."""

from flask import Blueprint, g

import calc
import domain
import serialize
from db import db, new_entity, now, touch
from errors import ApiError
from middleware import ALL_ROLES, authenticate
from response import list_response, object_response
from routes.programs import find_program
from validation import (
    get_body,
    opt_str,
    pagination,
    q_enum,
    q_str,
    req_dt,
    req_enum,
    req_int,
    req_str,
)
from util import add_days

bp = Blueprint("chains", __name__)

CHAIN_TERMINAL_STATUSES = ("COMPLETED", "BROKEN")
COMMITTED_CHAIN_STATUSES = ("COMMITTED", "EXECUTING")
OFFERED_SEGMENT_STATUSES = ("OFFER_SENT", "ACCEPTED", "TRANSPLANTED")
OFFERABLE_SEGMENT_STATUSES = ("PLANNED", "DECLINED")


def find_chain(chain_id):
    chain = db.chains.get(chain_id)
    if chain is None:
        raise ApiError("ERR_CHAIN_NOT_FOUND", "no ExchangeChain with id %s" % chain_id)
    return chain


def find_segment(segment_id):
    segment = db.segments.get(segment_id)
    if segment is None:
        raise ApiError("ERR_SEGMENT_NOT_FOUND", "no ChainSegment with id %s" % segment_id)
    return segment


# --------------------------------------------------------------------------- #
# chains
# --------------------------------------------------------------------------- #


@bp.post("/exchange-chains")
def create_chain():
    authenticate(["TransplantCoordinator"])
    body = get_body()
    program_id = req_str(body, "program_id")
    chain_type = req_enum(body, "chain_type", calc.CHAIN_TYPES)

    program = find_program(program_id)

    # priority 15 -- single-program containment
    domain.require_same_program(
        [program["id"], g.staff["program_id"] if g.staff is not None else None]
    )

    row = new_entity(
        "ExchangeChain",
        {
            "program_id": program["id"],
            "chain_type": chain_type,
            "status": "DRAFT",
            "validated_at": None,
            "committed_at": None,
            "break_reason_code": None,
        },
    )
    db.chains[row["id"]] = row
    return object_response(serialize.exchange_chain(row), 201)


@bp.get("/exchange-chains")
def list_chains():
    authenticate(ALL_ROLES)
    program_id = q_str("program_id")
    chain_type = q_enum("chain_type", calc.CHAIN_TYPES)
    status = q_enum("status", calc.CHAIN_STATUSES)
    limit, offset = pagination()

    rows = list(db.chains.values())
    if program_id is not None:
        rows = [r for r in rows if r["program_id"] == program_id]
    if chain_type is not None:
        rows = [r for r in rows if r["chain_type"] == chain_type]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    rows = sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(rows)
    page = rows[offset : offset + limit]
    return list_response([serialize.exchange_chain(r) for r in page], limit, offset, total)


@bp.get("/exchange-chains/<chain_id>")
def get_chain(chain_id):
    authenticate(ALL_ROLES)
    chain = find_chain(chain_id)
    return object_response(serialize.exchange_chain(chain))


# --------------------------------------------------------------------------- #
# segment insertion
# --------------------------------------------------------------------------- #


@bp.post("/exchange-chains/<chain_id>/segments")
def create_segment(chain_id):
    authenticate(["TransplantCoordinator"])
    chain = find_chain(chain_id)

    body = get_body()
    expected_chain_version = req_int(body, "expected_chain_version", minimum=0)
    position = req_int(body, "position", minimum=1)
    donor_candidate_id = req_str(body, "donor_candidate_id")
    recipient_candidate_id = req_str(body, "recipient_candidate_id")
    predecessor_segment_id = opt_str(body, "predecessor_segment_id")

    # priority 5 -- body FK existence
    donor = db.donors.get(donor_candidate_id)
    if donor is None:
        raise ApiError("ERR_DONOR_NOT_FOUND", "no DonorCandidate with id %s" % donor_candidate_id)
    recipient = db.recipients.get(recipient_candidate_id)
    if recipient is None:
        raise ApiError(
            "ERR_RECIPIENT_NOT_FOUND",
            "no RecipientCandidate with id %s" % recipient_candidate_id,
        )
    predecessor = None
    if predecessor_segment_id is not None:
        predecessor = find_segment(predecessor_segment_id)

    # priority 6 -- optimistic concurrency on the parent chain
    if expected_chain_version != chain["version"]:
        raise ApiError(
            "ERR_STALE_CHAIN_VERSION",
            "expected_chain_version %s does not match the chain's current version %s"
            % (expected_chain_version, chain["version"]),
        )

    # priority 8 -- a terminal chain accepts no further insertion
    if chain["status"] in CHAIN_TERMINAL_STATUSES:
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION",
            "a chain in %s accepts no further segments" % chain["status"],
        )

    # priority 15 -- single-program containment
    program_ids = [
        chain["program_id"],
        donor["program_id"],
        recipient["program_id"],
        g.staff["program_id"] if g.staff is not None else None,
    ]
    if predecessor is not None:
        predecessor_chain = domain.chain_of_segment(predecessor)
        if predecessor_chain is not None:
            program_ids.append(predecessor_chain["program_id"])
    domain.require_same_program(program_ids)

    # priority 17 -- at most one non-WITHDRAWN segment per position
    for existing in domain.segments_of_chain(chain):
        if existing["status"] != "WITHDRAWN" and existing["position"] == position:
            raise ApiError(
                "ERR_POSITION_TAKEN",
                "position %s is already taken in this chain" % position,
            )

    row = new_entity(
        "ChainSegment",
        {
            "exchange_chain_id": chain["id"],
            "position": position,
            "donor_candidate_id": donor["id"],
            "recipient_candidate_id": recipient["id"],
            "predecessor_segment_id": predecessor["id"] if predecessor is not None else None,
            "status": "PLANNED",
            "planned_cross_clamp_at": None,
            "planned_reperfusion_at": None,
            "planned_transport_minutes": None,
            "offer_sent_at": None,
            "offer_response_deadline_at": None,
            "offer_responded_at": None,
            "decline_reason_code": None,
            "planned_cit_minutes": None,
            "actual_cross_clamp_at": None,
            "actual_reperfusion_at": None,
            "actual_cit_minutes": None,
            "cit_breach": False,
        },
    )
    db.segments[row["id"]] = row

    # the chain's derived shape changed, so any holder of the old version is stale
    touch(chain)
    return object_response(serialize.chain_segment(row), 201)


# --------------------------------------------------------------------------- #
# validation
# --------------------------------------------------------------------------- #


def _check_participants(segments):
    """Priority 14 -- participant eligibility, donors first then recipients."""
    for segment in segments:
        donor = db.donors.get(segment["donor_candidate_id"])
        if donor is None or donor["overall_status"] != "APPROVED":
            raise ApiError(
                "ERR_DONOR_NOT_APPROVED",
                "segment at position %s has a donor that is not APPROVED" % segment["position"],
            )
    for segment in segments:
        recipient = db.recipients.get(segment["recipient_candidate_id"])
        if recipient is None or recipient["listing_status"] != "ACTIVE":
            raise ApiError(
                "ERR_RECIPIENT_NOT_ACTIVE",
                "segment at position %s has a recipient that is not ACTIVE"
                % segment["position"],
            )


def _check_topology(chain, segments):
    """Priority 16 -- the whole topology judged once, as a set."""
    if len(segments) < 2:
        raise ApiError(
            "ERR_CHAIN_TOO_SHORT", "a chain needs at least two non-withdrawn segments"
        )

    positions = [segment["position"] for segment in segments]
    if sorted(positions) != list(range(1, len(segments) + 1)):
        raise ApiError(
            "ERR_CHAIN_POSITIONS_NOT_CONTIGUOUS",
            "positions must be the consecutive whole numbers 1..%s" % len(segments),
        )

    if segments[0]["predecessor_segment_id"] is not None:
        raise ApiError(
            "ERR_CHAIN_LINKAGE_BROKEN", "the position-1 segment may not declare a predecessor"
        )
    for index in range(1, len(segments)):
        if segments[index]["predecessor_segment_id"] != segments[index - 1]["id"]:
            raise ApiError(
                "ERR_CHAIN_LINKAGE_BROKEN",
                "the segment at position %s must follow the segment before it"
                % segments[index]["position"],
            )

    donor_ids = [segment["donor_candidate_id"] for segment in segments]
    recipient_ids = [segment["recipient_candidate_id"] for segment in segments]
    if len(set(donor_ids)) != len(donor_ids) or len(set(recipient_ids)) != len(recipient_ids):
        raise ApiError(
            "ERR_DUPLICATE_PARTICIPANT", "no donor and no recipient may appear twice in a chain"
        )

    for segment in segments:
        donor = db.donors[segment["donor_candidate_id"]]
        recipient = db.recipients[segment["recipient_candidate_id"]]
        allowed = calc.ABO_COMPATIBILITY.get(donor["abo_blood_type"], set())
        if recipient["abo_blood_type"] not in allowed:
            raise ApiError(
                "ERR_ABO_INCOMPATIBLE",
                "donor type %s may not give to recipient type %s"
                % (donor["abo_blood_type"], recipient["abo_blood_type"]),
            )

    closed = domain.chain_is_closed_loop(chain)
    if chain["chain_type"] == "PAIRED_LOOP":
        if not closed:
            raise ApiError("ERR_LOOP_NOT_CLOSED", "a PAIRED_LOOP must close on itself")
    else:
        first_donor = db.donors[segments[0]["donor_candidate_id"]]
        if closed or first_donor["intended_recipient_id"] is not None:
            raise ApiError(
                "ERR_NDD_START_INVALID",
                "an NDD_CHAIN must start at a non-directed donor and must not close",
            )


@bp.post("/exchange-chains/<chain_id>/validation")
def validate_chain(chain_id):
    authenticate(["TransplantCoordinator"])
    chain = find_chain(chain_id)
    get_body()

    # priority 8 -- validation is only reachable from DRAFT
    if chain["status"] != "DRAFT":
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION",
            "a chain in %s may not be validated" % chain["status"],
        )

    segments = domain.ordered_segments(chain)
    _check_participants(segments)
    _check_topology(chain, segments)

    chain["status"] = "VALIDATED"
    chain["validated_at"] = now()
    touch(chain)
    return object_response(serialize.exchange_chain(chain))


# --------------------------------------------------------------------------- #
# commitment
# --------------------------------------------------------------------------- #


@bp.post("/exchange-chains/<chain_id>/commitment")
def commit_chain(chain_id):
    authenticate(["TransplantCoordinator"])
    chain = find_chain(chain_id)
    get_body()

    # priority 8 -- commitment is only reachable from VALIDATED
    if chain["status"] != "VALIDATED":
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION",
            "a chain in %s may not be committed" % chain["status"],
        )

    program = domain.program_of(chain)
    segments = domain.ordered_segments(chain)

    # priority 13 -- compliance posture gate
    if program["compliance_posture"] == "FROZEN":
        raise ApiError("ERR_PROGRAM_FROZEN", "a FROZEN program may not commit a chain")
    if program["compliance_posture"] == "RESTRICTED" and len(segments) > 2:
        raise ApiError(
            "ERR_PROGRAM_RESTRICTED",
            "a RESTRICTED program may only commit a chain of at most two segments",
        )

    # priority 14 -- participant eligibility
    _check_participants(segments)

    # the chain-wide ischemia budget only binds once a segment has been offered
    if any(segment["status"] in OFFERED_SEGMENT_STATUSES for segment in segments):
        if domain.chain_total_planned_cit(chain) > calc.CHAIN_CIT_BUDGET_MINUTES:
            raise ApiError(
                "ERR_CHAIN_CIT_BUDGET_EXCEEDED",
                "the chain's total planned cold-ischemia time exceeds %d minutes"
                % calc.CHAIN_CIT_BUDGET_MINUTES,
            )

    chain["status"] = "COMMITTED"
    chain["committed_at"] = now()
    touch(chain)

    for segment in segments:
        donor = db.donors.get(segment["donor_candidate_id"])
        if donor is not None:
            domain.refresh_donor_status(donor)

    return object_response(serialize.exchange_chain(chain))


# --------------------------------------------------------------------------- #
# break
# --------------------------------------------------------------------------- #


@bp.post("/exchange-chains/<chain_id>/break")
def break_chain(chain_id):
    authenticate(["TransplantCoordinator"])
    chain = find_chain(chain_id)

    body = get_body()
    break_reason_code = req_str(body, "break_reason_code")

    # priority 8
    if chain["status"] not in domain.BREAKABLE_CHAIN_STATUSES:
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION",
            "a chain in %s may not be broken" % chain["status"],
        )

    domain.break_chain(chain, break_reason_code)
    return object_response(serialize.exchange_chain(chain))


# --------------------------------------------------------------------------- #
# segments -- reads
# --------------------------------------------------------------------------- #


@bp.get("/chain-segments")
def list_segments():
    authenticate(ALL_ROLES)
    exchange_chain_id = q_str("exchange_chain_id")
    donor_candidate_id = q_str("donor_candidate_id")
    recipient_candidate_id = q_str("recipient_candidate_id")
    predecessor_segment_id = q_str("predecessor_segment_id")
    status = q_enum("status", calc.SEGMENT_STATUSES)
    limit, offset = pagination()

    rows = list(db.segments.values())
    if exchange_chain_id is not None:
        rows = [r for r in rows if r["exchange_chain_id"] == exchange_chain_id]
    if donor_candidate_id is not None:
        rows = [r for r in rows if r["donor_candidate_id"] == donor_candidate_id]
    if recipient_candidate_id is not None:
        rows = [r for r in rows if r["recipient_candidate_id"] == recipient_candidate_id]
    if predecessor_segment_id is not None:
        rows = [r for r in rows if r["predecessor_segment_id"] == predecessor_segment_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    rows = sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(rows)
    page = rows[offset : offset + limit]
    return list_response([serialize.chain_segment(r) for r in page], limit, offset, total)


@bp.get("/chain-segments/<segment_id>")
def get_segment(segment_id):
    authenticate(ALL_ROLES)
    segment = find_segment(segment_id)
    return object_response(serialize.chain_segment(segment))


# --------------------------------------------------------------------------- #
# the organ offer
# --------------------------------------------------------------------------- #


@bp.post("/chain-segments/<segment_id>/offer")
def send_offer(segment_id):
    authenticate(["TransplantCoordinator"])
    segment = find_segment(segment_id)

    body = get_body()
    planned_cross_clamp_at = req_dt(body, "planned_cross_clamp_at")
    planned_reperfusion_at = req_dt(body, "planned_reperfusion_at")
    planned_transport_minutes = req_int(body, "planned_transport_minutes", minimum=0)
    if planned_reperfusion_at <= planned_cross_clamp_at:
        raise ApiError(
            "ERR_VALIDATION",
            "planned_reperfusion_at must be strictly later than planned_cross_clamp_at",
        )

    # priority 8 -- reachable from PLANNED and, as a re-offer, from DECLINED
    if segment["status"] not in OFFERABLE_SEGMENT_STATUSES:
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION",
            "a segment in %s may not be offered" % segment["status"],
        )

    chain = domain.chain_of_segment(segment)

    # priority 9 -- the parent chain must be committed
    if chain["status"] not in COMMITTED_CHAIN_STATUSES:
        raise ApiError(
            "ERR_CHAIN_NOT_COMMITTED",
            "the parent chain is %s, not COMMITTED or EXECUTING" % chain["status"],
        )

    # priority 14 -- participant eligibility
    recipient = db.recipients[segment["recipient_candidate_id"]]
    if recipient["listing_status"] != "ACTIVE":
        raise ApiError(
            "ERR_RECIPIENT_NOT_ACTIVE", "the segment's recipient is not ACTIVE"
        )
    donor = db.donors[segment["donor_candidate_id"]]
    if donor["overall_status"] != "CHAIN_COMMITTED":
        raise ApiError(
            "ERR_DONOR_NOT_COMMITTED", "the segment's donor is not CHAIN_COMMITTED"
        )

    # priority 20 -- cold-ischemia planning prerequisites
    if segment["predecessor_segment_id"] is not None:
        predecessor = db.segments.get(segment["predecessor_segment_id"])
        if predecessor is not None and predecessor["planned_reperfusion_at"] is not None:
            if planned_cross_clamp_at < predecessor["planned_reperfusion_at"]:
                raise ApiError(
                    "ERR_PREDECESSOR_TIMING_INVALID",
                    "planned_cross_clamp_at precedes the predecessor's planned_reperfusion_at",
                )

    covered = False
    for booking in domain.bookings_of_segment(segment):
        if booking["status"] != "ACTIVE" or booking["booking_role"] != "DONOR_RECOVERY":
            continue
        if booking["start_at"] <= planned_cross_clamp_at < booking["end_at"]:
            covered = True
            break
    if not covered:
        raise ApiError(
            "ERR_DONOR_BOOKING_MISSING",
            "no ACTIVE DONOR_RECOVERY booking covers planned_cross_clamp_at",
        )

    # priority 22 -- per-segment ceiling first, then the chain-wide budget
    planned_cit = calc.planned_cit_minutes(planned_cross_clamp_at, planned_reperfusion_at)
    if planned_cit > calc.MAX_CIT_MINUTES:
        raise ApiError(
            "ERR_CIT_LIMIT_EXCEEDED",
            "planned_cit_minutes %d exceeds the %d minute ceiling"
            % (planned_cit, calc.MAX_CIT_MINUTES),
        )

    others = 0
    for other in domain.ordered_segments(chain):
        if other["id"] == segment["id"]:
            continue
        if other["status"] in OFFERED_SEGMENT_STATUSES:
            others += other["planned_cit_minutes"] or 0
    if others + planned_cit > calc.CHAIN_CIT_BUDGET_MINUTES:
        raise ApiError(
            "ERR_CHAIN_CIT_BUDGET_EXCEEDED",
            "the chain's total planned cold-ischemia time would exceed %d minutes"
            % calc.CHAIN_CIT_BUDGET_MINUTES,
        )

    clock = now()
    segment["status"] = "OFFER_SENT"
    segment["planned_cross_clamp_at"] = planned_cross_clamp_at
    segment["planned_reperfusion_at"] = planned_reperfusion_at
    segment["planned_transport_minutes"] = planned_transport_minutes
    segment["planned_cit_minutes"] = planned_cit
    segment["offer_sent_at"] = clock
    segment["offer_response_deadline_at"] = clock + _offer_window()
    segment["decline_reason_code"] = None
    segment["offer_responded_at"] = None
    touch(segment)
    return object_response(serialize.chain_segment(segment))


def _offer_window():
    from datetime import timedelta

    return timedelta(hours=calc.OFFER_RESPONSE_WINDOW_HOURS)


@bp.post("/chain-segments/<segment_id>/offer-response")
def respond_to_offer(segment_id):
    authenticate(["TransplantCoordinator"])
    segment = find_segment(segment_id)

    body = get_body()
    response = req_enum(body, "response", calc.OFFER_RESPONSES)
    decline_reason_code = opt_str(body, "decline_reason_code")
    if response == "DECLINE" and decline_reason_code is None:
        raise ApiError("ERR_VALIDATION", "decline_reason_code is required for a decline")

    # priority 8
    if segment["status"] != "OFFER_SENT":
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION",
            "a segment in %s has no outstanding offer" % segment["status"],
        )

    # priority 21 -- the response window
    clock = now()
    deadline = segment["offer_response_deadline_at"]
    if deadline is not None and clock > deadline:
        raise ApiError(
            "ERR_OFFER_WINDOW_EXPIRED", "the offer response window has already closed"
        )

    if response == "ACCEPT":
        segment["status"] = "ACCEPTED"
        segment["offer_responded_at"] = clock
        touch(segment)
        return object_response(serialize.chain_segment(segment))

    segment["status"] = "DECLINED"
    segment["offer_responded_at"] = clock
    segment["decline_reason_code"] = decline_reason_code
    touch(segment)

    if decline_reason_code == "DONOR_ORGAN_QUALITY":
        chain = domain.chain_of_segment(segment)
        if chain is not None and chain["status"] in domain.BREAKABLE_CHAIN_STATUSES:
            domain.break_chain(chain, "OFFER_DECLINED_ORGAN_QUALITY")

    return object_response(serialize.chain_segment(segment))


# --------------------------------------------------------------------------- #
# transplant completion -- the cascade-heaviest operation in the system
# --------------------------------------------------------------------------- #


@bp.post("/chain-segments/<segment_id>/transplant-completion")
def complete_transplant(segment_id):
    authenticate(["TransplantCoordinator"])
    segment = find_segment(segment_id)

    body = get_body()
    actual_cross_clamp_at = req_dt(body, "actual_cross_clamp_at")
    actual_reperfusion_at = req_dt(body, "actual_reperfusion_at")
    if actual_reperfusion_at <= actual_cross_clamp_at:
        raise ApiError(
            "ERR_VALIDATION",
            "actual_reperfusion_at must be strictly later than actual_cross_clamp_at",
        )

    # priority 8 -- only an ACCEPTED segment may be completed
    if segment["status"] != "ACCEPTED":
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION",
            "a segment in %s may not be completed" % segment["status"],
        )

    chain = domain.chain_of_segment(segment)

    # priority 9
    if chain["status"] not in COMMITTED_CHAIN_STATUSES:
        raise ApiError(
            "ERR_CHAIN_NOT_COMMITTED",
            "the parent chain is %s, not COMMITTED or EXECUTING" % chain["status"],
        )

    # priority 20 -- an ACTIVE RECIPIENT_IMPLANT booking must exist
    has_implant = any(
        booking["status"] == "ACTIVE" and booking["booking_role"] == "RECIPIENT_IMPLANT"
        for booking in domain.bookings_of_segment(segment)
    )
    if not has_implant:
        raise ApiError(
            "ERR_IMPLANT_BOOKING_MISSING",
            "no ACTIVE RECIPIENT_IMPLANT booking exists for this segment",
        )

    clock = now()
    actual_cit = calc.actual_cit_minutes(actual_cross_clamp_at, actual_reperfusion_at)
    segment["status"] = "TRANSPLANTED"
    segment["actual_cross_clamp_at"] = actual_cross_clamp_at
    segment["actual_reperfusion_at"] = actual_reperfusion_at
    segment["actual_cit_minutes"] = actual_cit
    segment["cit_breach"] = actual_cit > calc.MAX_CIT_MINUTES
    touch(segment)

    # hop 1 -- this segment's ACTIVE bookings complete; room minutes stay reserved
    for booking in domain.bookings_of_segment(segment):
        if booking["status"] == "ACTIVE":
            booking["status"] = "COMPLETED"
            touch(booking)

    program = domain.program_of(chain)

    # hop 2 -- the donor donates, which creates its three follow-up obligations
    donor = db.donors.get(segment["donor_candidate_id"])
    if donor is not None:
        donor["donated_at"] = clock
        touch(donor)
        domain.refresh_donor_status(donor)
        if not domain.follow_ups_of_donor(donor):
            domain.create_follow_ups(donor)
        domain.refresh_posture(program)

    # hop 3 -- the recipient is transplanted, with a waitlist event appended
    recipient = db.recipients.get(segment["recipient_candidate_id"])
    if recipient is not None and recipient["listing_status"] == "ACTIVE":
        recipient["listing_status"] = "TRANSPLANTED"
        touch(recipient)
        domain.record_waitlist_event(
            recipient, "ACTIVE", "TRANSPLANTED", "TRANSPLANT_COMPLETED", clock, g.user_id
        )

    # hop 4 -- a cold-ischemia breach can restrict the program
    if segment["cit_breach"]:
        domain.refresh_posture(program)

    # hop 5 -- the chain advances
    if chain["status"] == "COMMITTED":
        chain["status"] = "EXECUTING"
        touch(chain)
    live = domain.ordered_segments(chain)
    if live and all(other["status"] == "TRANSPLANTED" for other in live):
        chain["status"] = "COMPLETED"
        touch(chain)

    return object_response(serialize.chain_segment(segment))
