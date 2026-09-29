"""Settlement parties, settlements and signatures."""
from flask import Blueprint, g

import auth
import clock
import constants as C
import listing
import payload
import response
import serializers as S
import services as SV
from db import db, sorted_rows
from errors import ApiError
from numeric import q2

bp = Blueprint("settlement", __name__)


# ---------------------------------------------------------------------------
# settlement parties
# ---------------------------------------------------------------------------


@bp.post("/relicensing/parties")
def create_party():
    auth.authenticate(["Regulator"])
    data = payload.body()

    project_id = payload.req_string(data, "project_id")
    project = SV.fetch("projects", project_id)

    party_name = payload.req_string(data, "party_name")
    party_type = payload.req_enum(data, "party_type", C.PARTY_TYPES)
    conditioning = payload.opt_bool(data, "has_conditioning_authority", False)
    vote_weight = payload.opt_int(data, "vote_weight", 1, minimum=1)
    contact_user_id = payload.opt_string(data, "contact_user_id")

    if conditioning and party_type != "AGENCY":
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "has_conditioning_authority may be true only for an AGENCY party.",
        )

    SV.require_not_frozen(project)

    party = SV.base_row()
    party.update(
        {
            "project_id": project_id,
            "party_name": party_name,
            "party_type": party_type,
            "has_conditioning_authority": conditioning,
            "vote_weight": vote_weight,
            "contact_user_id": contact_user_id,
        }
    )
    db.parties[party["id"]] = party

    SV.finalize_project(project)
    return response.object_response(S.party(party), 201)


@bp.get("/relicensing/parties")
def list_parties():
    auth.authenticate(C.ALL_ROLES)
    return listing.respond(
        sorted_rows(db.parties),
        S.party,
        ("project_id", "party_type", "has_conditioning_authority"),
    )


@bp.get("/relicensing/parties/<party_id>")
def get_party(party_id):
    auth.authenticate(C.ALL_ROLES)
    return response.object_response(S.party(SV.fetch("parties", party_id)))


# ---------------------------------------------------------------------------
# settlements
# ---------------------------------------------------------------------------


@bp.post("/relicensing/settlements")
def create_settlement():
    auth.authenticate(["Licensee"])
    data = payload.body()

    project_id = payload.req_string(data, "project_id")
    project = SV.fetch("projects", project_id)
    title = payload.req_string(data, "title")
    expected_version = payload.req_int(data, "expected_project_version")

    if expected_version != project["version"]:
        raise ApiError(
            "ERR_STALE_PROJECT_VERSION",
            "expected_project_version does not match the project's current version.",
        )

    SV.require_not_frozen(project)

    priors = sorted_rows(db.settlements, lambda s: s["project_id"] == project_id)
    if any(s["status"] == "EXECUTED" for s in priors):
        raise ApiError(
            "ERR_SETTLEMENT_STATE_INVALID",
            "The project already has an EXECUTED settlement.",
        )

    for prior in priors:
        if prior["status"] in ("NEGOTIATING", "CIRCULATED"):
            prior["status"] = "SUPERSEDED"
            for measure in sorted_rows(
                db.measures,
                lambda m, sid=prior["id"]: m["settlement_id"] == sid and m["status"] == "PROPOSED",
            ):
                measure["status"] = "SUPERSEDED"
                SV.touch(measure)
            SV.touch(prior)

    settlement = SV.base_row()
    settlement.update(
        {
            "project_id": project_id,
            "title": title,
            "status": "NEGOTIATING",
            "round_number": 1,
            "circulated_at": None,
            "executed_at": None,
            "withdrawn_at": None,
            "support_pct": q2(0),
            "total_vote_weight": 0,
            "included_measure_count": 0,
        }
    )
    db.settlements[settlement["id"]] = settlement

    SV.finalize_project(project)
    SV.touch(project)
    return response.object_response(S.settlement(settlement), 201)


@bp.get("/relicensing/settlements")
def list_settlements():
    auth.authenticate(C.ALL_ROLES)
    return listing.respond(sorted_rows(db.settlements), S.settlement, ("project_id", "status"))


@bp.get("/relicensing/settlements/<settlement_id>")
def get_settlement(settlement_id):
    auth.authenticate(C.ALL_ROLES)
    return response.object_response(S.settlement(SV.fetch("settlements", settlement_id)))


@bp.post("/relicensing/settlements/<settlement_id>/circulate")
def circulate_settlement(settlement_id):
    auth.authenticate(["Licensee"])
    settlement = SV.fetch("settlements", settlement_id)
    data = payload.body()
    payload.opt_string(data, "circulation_note")

    project = SV.project_of_settlement(settlement)
    SV.require_not_frozen(project)

    if settlement["status"] != "NEGOTIATING":
        raise ApiError(
            "ERR_SETTLEMENT_STATE_INVALID",
            "Only a NEGOTIATING settlement can be circulated.",
        )

    parties = SV.project_parties(project)
    if len(parties) < 2:
        raise ApiError(
            "ERR_SETTLEMENT_STATE_INVALID",
            "A settlement requires at least two registered parties.",
        )

    settlement["status"] = "CIRCULATED"
    settlement["circulated_at"] = clock.now_iso()
    settlement["total_vote_weight"] = sum(int(p["vote_weight"]) for p in parties)
    SV.touch(settlement)

    SV.finalize_project(project)
    return response.object_response(S.settlement(settlement))


@bp.post("/relicensing/settlements/<settlement_id>/tally")
def tally_settlement(settlement_id):
    auth.authenticate(["Licensee"])
    settlement = SV.fetch("settlements", settlement_id)
    data = payload.body()
    outcome = payload.req_enum(data, "intended_outcome", C.TALLY_OUTCOMES)
    payload.opt_string(data, "tally_note")

    project = SV.project_of_settlement(settlement)
    SV.require_not_frozen(project)

    if settlement["status"] != "CIRCULATED":
        raise ApiError(
            "ERR_SETTLEMENT_STATE_INVALID",
            "Only a CIRCULATED settlement round can be tallied.",
        )

    tally = SV.compute_tally(settlement, project)

    if outcome == "EXECUTE":
        if not SV.project_has_approved_plan(project):
            raise ApiError(
                "ERR_STUDY_PLAN_NOT_APPROVED",
                "Settlement execution requires an APPROVED study plan.",
            )
        if tally["support_pct"] < C.SUPPORT_THRESHOLD_PCT:
            raise ApiError(
                "ERR_SUPPORT_THRESHOLD_NOT_MET",
                "Tallied support of %s does not reach the execution threshold."
                % tally["support_pct"],
            )
        if SV.conditioning_party_opposes(settlement):
            raise ApiError(
                "ERR_CONDITIONING_PARTY_VETO",
                "A party holding conditioning authority opposed in this round.",
            )

        SV.persist_tally(settlement, tally)
        settlement["status"] = "EXECUTED"
        settlement["executed_at"] = clock.now_iso()

        included = 0
        for measure in sorted_rows(
            db.measures,
            lambda m: m["settlement_id"] == settlement["id"] and m["status"] == "PROPOSED",
        ):
            measure["status"] = "INCLUDED"
            SV.touch(measure)
            included += 1
        settlement["included_measure_count"] = included
    else:
        SV.persist_tally(settlement, tally)
        if settlement["round_number"] < C.MAX_NEGOTIATION_ROUNDS:
            settlement["status"] = "NEGOTIATING"
            settlement["round_number"] = settlement["round_number"] + 1
            settlement["circulated_at"] = None
        else:
            settlement["status"] = "FAILED"
            for measure in sorted_rows(
                db.measures,
                lambda m: m["settlement_id"] == settlement["id"] and m["status"] == "PROPOSED",
            ):
                measure["status"] = "SUPERSEDED"
                SV.touch(measure)

    SV.touch(settlement)
    SV.finalize_project(project)
    return response.object_response(S.settlement(settlement))


@bp.post("/relicensing/settlements/<settlement_id>/withdraw")
def withdraw_settlement(settlement_id):
    auth.authenticate(["Licensee"])
    settlement = SV.fetch("settlements", settlement_id)
    data = payload.body()
    payload.req_string(data, "withdrawal_reason")

    project = SV.project_of_settlement(settlement)
    SV.require_not_frozen(project)

    if settlement["status"] != "EXECUTED":
        raise ApiError(
            "ERR_SETTLEMENT_STATE_INVALID",
            "Only an EXECUTED settlement can be withdrawn.",
        )

    for order in sorted_rows(db.orders):
        if SV.project_of_order(order)["id"] != project["id"]:
            continue
        if order["compliance_state"] in ("EFFECTIVE", "COMPLIANCE_FLAGGED"):
            raise ApiError(
                "ERR_ORDER_STATE_INVALID",
                "A settlement cannot be withdrawn while a license order is live.",
            )

    settlement["status"] = "WITHDRAWN"
    settlement["withdrawn_at"] = clock.now_iso()
    settlement["included_measure_count"] = 0

    withdrawn_ids = []
    for measure in sorted_rows(
        db.measures,
        lambda m: m["settlement_id"] == settlement["id"]
        and m["source"] == "SETTLEMENT"
        and m["status"] == "INCLUDED",
    ):
        measure["status"] = "WITHDRAWN"
        SV.touch(measure)
        withdrawn_ids.append(measure["id"])

    affected_orders = set()
    for obligation in sorted_rows(
        db.obligations, lambda o: o["pme_measure_id"] in withdrawn_ids
    ):
        if obligation["status"] in ("PENDING", "SCHEDULED", "OVERDUE"):
            obligation["status"] = "WAIVED"
            SV.touch(obligation)
            affected_orders.add(obligation["order_id"])
    for order_id in affected_orders:
        SV.refresh_order_violations(db.orders[order_id])

    SV.touch(settlement)
    SV.finalize_project(project)
    return response.object_response(S.settlement(settlement))


# ---------------------------------------------------------------------------
# signatures
# ---------------------------------------------------------------------------


@bp.post("/relicensing/signatures")
def create_signature():
    auth.authenticate(["AgencyReviewer", "Stakeholder"])
    data = payload.body()

    settlement_id = payload.req_string(data, "settlement_id")
    settlement = SV.fetch("settlements", settlement_id)
    auth.require_project_scope(settlement["project_id"])

    party_id = payload.req_string(data, "party_id")
    party = SV.fetch("parties", party_id)

    acting = auth.acting_party()
    if party["id"] != acting["id"] and party_id != g.user_id:
        raise ApiError(
            "ERR_ROLE_NOT_PERMITTED",
            "A signature must be recorded by the signing party itself.",
        )

    if settlement["project_id"] != party["project_id"]:
        raise ApiError(
            "ERR_CROSS_PROJECT_REFERENCE",
            "The settlement and the signing party belong to different projects.",
        )

    position = payload.req_enum(data, "position", C.POSITIONS)

    project = SV.project_of_settlement(settlement)
    SV.require_not_frozen(project)

    if settlement["status"] != "CIRCULATED":
        raise ApiError(
            "ERR_SIGNATURE_ROUND_CLOSED",
            "Signatures are accepted only while the settlement is CIRCULATED.",
        )

    for existing in db.signatures.values():
        if (
            existing["settlement_id"] == settlement["id"]
            and existing["party_id"] == party["id"]
            and existing["round_number"] == settlement["round_number"]
        ):
            raise ApiError(
                "ERR_DUPLICATE_SIGNATURE",
                "The party has already signed the current round.",
            )

    signature = SV.base_row(versioned=False)
    signature.update(
        {
            "settlement_id": settlement["id"],
            "party_id": party["id"],
            "round_number": settlement["round_number"],
            "position": position,
            "share_pct": None,
            "signed_at": clock.now_iso(),
        }
    )
    db.signatures[signature["id"]] = signature

    SV.finalize_project(project)
    return response.object_response(S.signature(signature), 201)


@bp.get("/relicensing/signatures")
def list_signatures():
    auth.authenticate(C.ALL_ROLES)
    return listing.respond(
        sorted_rows(db.signatures),
        S.signature,
        ("settlement_id", "party_id", "round_number", "position"),
    )


@bp.get("/relicensing/signatures/<signature_id>")
def get_signature(signature_id):
    auth.authenticate(C.ALL_ROLES)
    return response.object_response(S.signature(SV.fetch("signatures", signature_id)))
