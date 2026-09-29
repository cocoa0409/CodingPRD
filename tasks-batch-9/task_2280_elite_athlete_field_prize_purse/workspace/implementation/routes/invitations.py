"""Invitations: creation, the negotiation cycle, response, withdrawal and the
bib service (PRD 3.3, 3.4, 3.5)."""
from flask import Blueprint, g

from clock import add_days, clock, fmt_dt, now_iso
from constants import (
    AIR_CLASSES,
    DIVISIONS,
    INVITATION_STATUSES,
    NEGOTIATION_SIDES,
    SLOT_STATUSES,
)
from db import db, new_record, touch
from errors import err
from middleware import authenticate
from response import list_response, object_response, paginate
from services import cascade, gates, lookup, serializers, valuation
from validators import (
    enum_filter,
    get_body,
    number_filter,
    oint,
    ostr,
    pagination_args,
    renum,
    rint,
    rbool,
    rstr,
    str_filter,
)

bp = Blueprint("invitations", __name__)

_ACTIVE_NEGOTIATION = ("OFFERED", "COUNTERED")


def _require_status(invitation, allowed):
    if invitation["status"] not in allowed:
        raise err(
            "ERR_INVALID_INVITATION_STATE",
            "The invitation status %s does not permit this operation"
            % invitation["status"],
        )


def _require_own_invitation(invitation):
    """Priority 5 — agent ownership on invitation-scoped writes."""
    if g.user_role == "AthleteAgent" and g.user_id != invitation["agent_id"]:
        raise err(
            "ERR_NOT_INVITATION_AGENT",
            "The acting agent does not represent this invitation",
        )


def _require_turn(invitation):
    """Priority 9 — turn-taking derived from the invitation's own state."""
    expected = "AthleteAgent" if invitation["status"] == "OFFERED" else "ElitesDirector"
    if g.user_role != expected:
        raise err(
            "ERR_ROLE_NOT_PERMITTED_FROM_STATE",
            "Only a %s may act while the invitation is %s"
            % (expected, invitation["status"]),
        )


def _read_terms(body):
    return {
        "appearance_fee_cents": rint(body, "appearance_fee_cents", minimum=0),
        "air_class": renum(body, "air_class", AIR_CLASSES),
        "hotel_nights": rint(body, "hotel_nights", minimum=0, maximum=14),
        "ground_transport": rbool(body, "ground_transport"),
        "note": ostr(body, "note"),
    }


def _apply_terms(invitation, terms):
    invitation["current_appearance_fee_cents"] = terms["appearance_fee_cents"]
    invitation["current_air_class"] = terms["air_class"]
    invitation["current_hotel_nights"] = terms["hotel_nights"]
    invitation["current_ground_transport"] = terms["ground_transport"]


def _write_round(invitation, side, round_number, terms):
    rnd = new_record(
        with_version=False,
        invitation_id=invitation["id"],
        round_number=round_number,
        side=side,
        appearance_fee_cents=terms["appearance_fee_cents"],
        air_class=terms["air_class"],
        hotel_nights=terms["hotel_nights"],
        ground_transport=terms["ground_transport"],
        note=terms["note"],
    )
    db.negotiation_rounds[rnd["id"]] = rnd
    return rnd


def _push_deadline(invitation, edition):
    invitation["response_deadline_at"] = _deadline(edition)


def _deadline(edition):
    return fmt_dt(add_days(clock.now(), edition["offer_response_days"]))


@bp.post("/invitations")
def create_invitation():
    authenticate(("ElitesDirector",))
    body = get_body()
    edition_id = rstr(body, "race_edition_id")
    athlete_id = rstr(body, "athlete_id")
    agent_id = rstr(body, "agent_id")
    performance_id = rstr(body, "qualifying_performance_id")
    edition = lookup.get_edition(edition_id)
    lookup.get_athlete(athlete_id)
    lookup.get_agent(agent_id)
    lookup.get_performance(performance_id)
    division = renum(body, "division", DIVISIONS)

    gates.gate_edition(edition, ("FIELD_OPEN",))

    invitation = new_record(
        race_edition_id=edition_id,
        athlete_id=athlete_id,
        agent_id=agent_id,
        qualifying_performance_id=performance_id,
        division=division,
        status="DRAFT",
        current_appearance_fee_cents=None,
        current_air_class=None,
        current_hotel_nights=None,
        current_ground_transport=None,
        offer_sent_at=None,
        response_deadline_at=None,
        guaranteed_commitment_cents=0,
        full_exposure_cents=0,
        bib_number=None,
        negotiated_by_user_id=None,
    )
    db.invitations[invitation["id"]] = invitation
    return object_response(serializers.ser_invitation(invitation), 201)


@bp.get("/invitations/<invitation_id>")
def read_invitation(invitation_id):
    authenticate((
        "ElitesDirector",
        "FinanceOfficer",
        "TechnicalOfficial",
        "AthleteAgent",
        "AntiDopingLiaison",
    ))
    invitation = lookup.get_invitation(invitation_id)
    return object_response(serializers.ser_invitation(invitation))


@bp.get("/invitations")
def list_invitations():
    authenticate(("ElitesDirector", "FinanceOfficer", "TechnicalOfficial", "AthleteAgent"))
    limit, offset = pagination_args()
    filters = {}
    for name in ("race_edition_id", "athlete_id", "agent_id", "qualifying_performance_id"):
        value = str_filter(name)
        if value is not None:
            filters[name] = value
    status = enum_filter("status", INVITATION_STATUSES)
    division = enum_filter("division", DIVISIONS)
    if status is not None:
        filters["status"] = status
    if division is not None:
        filters["division"] = division
    rows = lookup.rows("invitations", **filters)
    window, total = paginate(rows, limit, offset)
    return list_response(
        [serializers.ser_invitation(r) for r in window], limit, offset, total
    )


@bp.post("/invitations/<invitation_id>/offer")
def send_offer(invitation_id):
    role, user_id = authenticate(("ElitesDirector",))
    invitation = lookup.get_invitation(invitation_id)
    body = get_body()
    terms = _read_terms(body)

    edition = lookup.soft_get("race_editions", invitation["race_edition_id"])
    gates.gate_edition(edition, ("FIELD_OPEN",))
    _require_status(invitation, ("DRAFT",))

    agent = lookup.soft_get("rep_agents", invitation["agent_id"])
    if agent is not None:
        gates.require_agent_active(agent)

    athlete = lookup.soft_get("athletes", invitation["athlete_id"])
    performance = lookup.soft_get(
        "performance_records", invitation["qualifying_performance_id"]
    )
    gates.check_qualifying_standard(edition, invitation, athlete, performance)
    gates.check_performance_coherence(invitation, performance)

    _apply_terms(invitation, terms)
    invitation["offer_sent_at"] = now_iso()
    _push_deadline(invitation, edition)
    invitation["negotiated_by_user_id"] = user_id
    invitation["status"] = "OFFERED"
    _write_round(invitation, "COMMITTEE", 1, terms)
    touch(invitation)
    return object_response(serializers.ser_invitation(invitation))


@bp.post("/invitations/<invitation_id>/negotiation-rounds")
def append_round(invitation_id):
    role, user_id = authenticate(("AthleteAgent", "ElitesDirector"))
    invitation = lookup.get_invitation(invitation_id)
    body = get_body()
    terms = _read_terms(body)
    expected = rint(body, "expected_invitation_version")

    _require_own_invitation(invitation)

    edition = lookup.soft_get("race_editions", invitation["race_edition_id"])
    gates.gate_edition(edition, ("FIELD_OPEN",))
    _require_status(invitation, _ACTIVE_NEGOTIATION)
    _require_turn(invitation)

    if expected != invitation["version"]:
        raise err(
            "ERR_STALE_INVITATION_VERSION",
            "expected_invitation_version does not match the invitation version",
        )

    agent = lookup.soft_get("rep_agents", invitation["agent_id"])
    if agent is not None:
        gates.require_agent_active(agent)

    gates.require_deadline_not_passed(invitation)

    round_count = len(lookup.invitation_rounds(invitation_id))
    if round_count >= 2 * edition["max_negotiation_rounds"]:
        raise err(
            "ERR_NEGOTIATION_ROUNDS_EXHAUSTED",
            "The negotiation round allowance is exhausted",
        )

    side = "AGENT" if role == "AthleteAgent" else "COMMITTEE"
    rnd = _write_round(invitation, side, round_count + 1, terms)
    _apply_terms(invitation, terms)
    _push_deadline(invitation, edition)
    invitation["status"] = "COUNTERED" if invitation["status"] == "OFFERED" else "OFFERED"
    touch(invitation)
    return object_response(serializers.ser_round(rnd), 201)


@bp.get("/invitations/<invitation_id>/negotiation-rounds")
def list_rounds(invitation_id):
    authenticate(("ElitesDirector", "AthleteAgent", "FinanceOfficer"))
    lookup.get_invitation(invitation_id)
    limit, offset = pagination_args()
    side = enum_filter("side", NEGOTIATION_SIDES)
    rows = lookup.invitation_rounds(invitation_id)
    if side is not None:
        rows = [r for r in rows if r["side"] == side]
    total = len(rows)
    window = rows[offset:offset + limit]
    return list_response(
        [serializers.ser_round(r) for r in window], limit, offset, total
    )


@bp.post("/invitations/<invitation_id>/respond")
def respond(invitation_id):
    role, user_id = authenticate(("AthleteAgent", "ElitesDirector"))
    invitation = lookup.get_invitation(invitation_id)
    body = get_body()
    decision = renum(body, "decision", ("ACCEPT", "DECLINE"))

    _require_own_invitation(invitation)

    edition = lookup.soft_get("race_editions", invitation["race_edition_id"])
    gates.gate_edition(edition, ("FIELD_OPEN",))
    _require_status(invitation, _ACTIVE_NEGOTIATION)
    _require_turn(invitation)

    agent = lookup.soft_get("rep_agents", invitation["agent_id"])
    if agent is not None:
        gates.require_agent_active(agent)

    gates.require_deadline_not_passed(invitation)

    if decision == "DECLINE":
        invitation["status"] = "DECLINED"
        touch(invitation)
        return object_response(serializers.ser_invitation(invitation))

    guaranteed = valuation.guaranteed_valuation(invitation)
    uncommitted = serializers.edition_ledger(edition)["appearance_uncommitted_cents"]
    if uncommitted < guaranteed:
        raise err(
            "ERR_APPEARANCE_BUDGET_EXCEEDED",
            "The remaining appearance budget cannot absorb this package",
        )
    invitation["guaranteed_commitment_cents"] = guaranteed
    invitation["status"] = "ACCEPTED"
    touch(invitation)
    touch(edition)
    return object_response(serializers.ser_invitation(invitation))


@bp.post("/invitations/<invitation_id>/withdraw")
def withdraw(invitation_id):
    authenticate(("ElitesDirector",))
    invitation = lookup.get_invitation(invitation_id)
    body = get_body()
    ostr(body, "reason")

    edition = lookup.soft_get("race_editions", invitation["race_edition_id"])
    gates.gate_edition(edition, ("FIELD_OPEN", "FIELD_LOCKED"))
    _require_status(invitation, ("DRAFT", "OFFERED", "COUNTERED", "ACCEPTED"))

    was_accepted = invitation["status"] == "ACCEPTED"
    if was_accepted and lookup.rows("race_results", invitation_id=invitation_id):
        raise err(
            "ERR_INVALID_INVITATION_STATE",
            "A race result already exists for this invitation",
        )

    invitation["status"] = "WITHDRAWN"
    if was_accepted:
        invitation["guaranteed_commitment_cents"] = 0
        invitation["bib_number"] = None
    touch(invitation)
    if was_accepted:
        cascade.release_fluid_slots(invitation)
        touch(edition)
    return object_response(serializers.ser_invitation(invitation))


@bp.post("/invitations/<invitation_id>/assign-bib")
def assign_bib(invitation_id):
    authenticate(("ElitesDirector",))
    invitation = lookup.get_invitation(invitation_id)
    get_body()

    edition = lookup.soft_get("race_editions", invitation["race_edition_id"])
    gates.gate_edition(edition, ("FIELD_OPEN", "FIELD_LOCKED"))
    _require_status(invitation, ("ACCEPTED",))

    athlete = lookup.soft_get("athletes", invitation["athlete_id"])
    gates.require_doping_compliant(athlete, edition)

    if invitation["bib_number"] is not None:
        raise err("ERR_BIB_ALREADY_ASSIGNED", "The invitation already holds a bib number")

    standard = lookup.find_standard(
        edition["id"], invitation["division"], athlete["gender"]
    )
    taken = set()
    for peer in lookup.edition_invitations(edition["id"]):
        if peer["status"] == "ACCEPTED" and peer["bib_number"] is not None:
            taken.add(peer["bib_number"])
    chosen = None
    if standard is not None:
        for bib in range(standard["bib_range_start"], standard["bib_range_end"] + 1):
            if bib not in taken:
                chosen = bib
                break
    if chosen is None:
        raise err("ERR_BIB_POOL_EXHAUSTED", "No bib remains in the division pool")

    invitation["bib_number"] = chosen
    touch(invitation)
    return object_response(serializers.ser_invitation(invitation))


@bp.get("/invitations/<invitation_id>/fluid-station-slots")
def list_slots(invitation_id):
    authenticate(("ElitesDirector", "TechnicalOfficial", "AthleteAgent"))
    lookup.get_invitation(invitation_id)
    limit, offset = pagination_args()
    status = enum_filter("status", SLOT_STATUSES)
    station_km = number_filter("station_km")
    rows = lookup.invitation_slots(invitation_id)
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if station_km is not None:
        rows = [r for r in rows if abs(r["station_km"] - station_km) < 1e-9]
    window, total = paginate(rows, limit, offset)
    return list_response(
        [serializers.ser_slot(r) for r in window], limit, offset, total
    )
