"""AccountApplication endpoints: create, decision (approve/decline), report-closure."""

from datetime import timedelta

import db
from errors import (
    err_not_found, err_invalid_state, err_validation, err_unauthorized, raise_err,
    ERR_DOCS_INCOMPLETE, ERR_ALT_ID_NOT_ACCEPTED, ERR_BARRIER_UNRESOLVED,
    ERR_EDUCATION_REQUIRED, ERR_INSTITUTION_NOT_CERTIFIED, ERR_REFERRAL_MISMATCH,
)
from middleware import require_roles, get_json_body, require_fields, check_string, check_enum
from response import success_object, success_list, parse_pagination
from services.common import new_entity, touch, recompute_pipeline
from flask import request

ID_TYPES = {"STATE_ID", "MATRICULA_CONSULAR", "MUNICIPAL_ID", "FOREIGN_PASSPORT"}
DECLINE_REASONS = {"CHEX", "INSUFFICIENT_ID", "OTHER"}
M6_OFFSET_DAYS = 183
M12_OFFSET_DAYS = 365
EVAL_WINDOW_DAYS = 30


def _serialize(a):
    return dict(a)


def _close_linked_referral(app, outcome):
    """Push the linked referral to CLOSED_CONVERTED / CLOSED_LOST."""
    rid = app.get("referral_id")
    if not rid:
        return
    ref = db.referrals.get(rid)
    if ref is None:
        return
    ref["status"] = outcome
    touch(ref)
    if outcome == "CLOSED_CONVERTED" and ref.get("campaign_id"):
        campaign = db.outreach_campaigns.get(ref["campaign_id"])
        if campaign is not None:
            campaign["spent_cents"] = campaign.get("spent_cents", 0) + campaign["per_conversion_cents"]
            touch(campaign)


def _create_checkpoints(app):
    opened_date = db.parse_dt(app["opened_at"]).date()
    for kind, offset in (("M6", M6_OFFSET_DAYS), ("M12", M12_OFFSET_DAYS)):
        due = opened_date + timedelta(days=offset)
        cp = new_entity()
        cp.update({
            "application_id": app["id"],
            "kind": kind,
            "due_date": due.isoformat(),
            "window_end": (due + timedelta(days=EVAL_WINDOW_DAYS)).isoformat(),
            "status": "PENDING",
            "evaluated_at": None,
        })
        db.retention_checkpoints[cp["id"]] = cp


def register(bp):
    @bp.route("/account-applications", methods=["POST"])
    def create_application():
        user_id, _ = require_roles("InstitutionOfficer")
        body = get_json_body()
        require_fields(body, ["participant_id", "institution_id", "id_type_presented"])
        check_string(body["participant_id"], "participant_id")
        check_string(body["institution_id"], "institution_id")
        check_enum(body["id_type_presented"], ID_TYPES, "id_type_presented")
        referral_id = body.get("referral_id")
        event_id = body.get("event_id")
        if referral_id is not None:
            check_string(referral_id, "referral_id")
        if event_id is not None:
            check_string(event_id, "event_id")
        if referral_id is None and event_id is None:
            err_validation("referral_id is required when event_id is not present")

        # ownership: officer identity equals institution_id
        if user_id != body["institution_id"]:
            err_unauthorized("InstitutionOfficer identity must equal institution_id")

        # existence: body FKs in input order
        participant = db.participants.get(body["participant_id"])
        if participant is None:
            err_not_found("Participant not found")
        institution = db.partner_institutions.get(body["institution_id"])
        if institution is None:
            err_not_found("PartnerInstitution not found")
        referral = None
        if referral_id is not None:
            referral = db.referrals.get(referral_id)
            if referral is None:
                err_not_found("Referral not found")
        event = None
        if event_id is not None:
            event = db.account_opening_events.get(event_id)
            if event is None:
                err_not_found("AccountOpeningEvent not found")

        # compliance gates
        if not participant.get("docs_complete"):
            raise_err(ERR_DOCS_INCOMPLETE, "Participant documentation is not complete")

        id_type = body["id_type_presented"]
        verified_docs = {d["doc_type"] for d in (participant.get("id_documents") or []) if d.get("status") == "VERIFIED"}
        if id_type not in verified_docs:
            raise_err(ERR_ALT_ID_NOT_ACCEPTED, "id_type_presented is not a VERIFIED participant document")

        # referral linkage rules
        if referral is not None:
            if referral["participant_id"] != participant["id"]:
                raise_err(ERR_REFERRAL_MISMATCH, "referral_id belongs to another participant")
            if referral["status"] not in ("DOCS_COMPLETE", "BOOKED"):
                raise_err(ERR_REFERRAL_MISMATCH, "Referral is not in DOCS_COMPLETE or BOOKED")
            if event_id is not None and referral.get("booked_event_id") != event_id:
                raise_err(ERR_REFERRAL_MISMATCH, "event_id must equal referral.booked_event_id")

        # cross-entity state: institution must be CERTIFIED
        if institution["certification_status"] != "CERTIFIED":
            raise_err(ERR_INSTITUTION_NOT_CERTIFIED, "Institution must be CERTIFIED")

        # alt-id acceptance leg (needs certified standard)
        if id_type != "STATE_ID":
            std = db.account_standards.get(institution.get("certified_standard_id"))
            accepted = (std or {}).get("accepted_alt_id_types") or []
            if id_type not in accepted:
                raise_err(ERR_ALT_ID_NOT_ACCEPTED, "id_type_presented not permitted by the certified standard")

        app = new_entity()
        app.update({
            "participant_id": participant["id"],
            "institution_id": institution["id"],
            "referral_id": referral_id,
            "event_id": event_id,
            "id_type_presented": id_type,
            "status": "SUBMITTED",
            "decline_reason": None,
            "account_number": None,
            "opened_at": None,
            "closed_at": None,
            "decided_by_user_id": None,
        })
        db.account_applications[app["id"]] = app

        # referral -> APPLIED; release seat if BOOKED
        if referral is not None:
            was_booked = referral["status"] == "BOOKED"
            booked_event_id = referral.get("booked_event_id")
            referral["status"] = "APPLIED"
            referral["booked_event_id"] = None
            touch(referral)
            if was_booked and booked_event_id:
                ev = db.account_opening_events.get(booked_event_id)
                if ev is not None and ev["booked_count"] > 0:
                    ev["booked_count"] -= 1
                    touch(ev)

        recompute_pipeline(participant["id"])
        return success_object(_serialize(app), status=201)

    @bp.route("/account-applications", methods=["GET"])
    def list_applications():
        require_roles("CoalitionAdmin", "InstitutionOfficer", "AgencyNavigator")
        limit, offset = parse_pagination(request.args)
        items = sorted(db.account_applications.values(), key=lambda x: db.parse_dt(x["created_at"]))
        pid = request.args.get("participant_id")
        iid = request.args.get("institution_id")
        rid = request.args.get("referral_id")
        eid = request.args.get("event_id")
        st = request.args.get("status")
        if pid is not None:
            items = [a for a in items if a["participant_id"] == pid]
        if iid is not None:
            items = [a for a in items if a["institution_id"] == iid]
        if rid is not None:
            items = [a for a in items if a.get("referral_id") == rid]
        if eid is not None:
            items = [a for a in items if a.get("event_id") == eid]
        if st is not None:
            items = [a for a in items if a["status"] == st]
        total = len(items)
        page = items[offset:offset + limit]
        return success_list([_serialize(a) for a in page], limit, offset, total)

    @bp.route("/account-applications/<aid>", methods=["GET"])
    def get_application(aid):
        require_roles("CoalitionAdmin", "InstitutionOfficer", "AgencyNavigator")
        app = db.account_applications.get(aid)
        if app is None:
            err_not_found("AccountApplication not found")
        return success_object(_serialize(app))

    @bp.route("/account-applications/<aid>/decision", methods=["POST"])
    def decide_application(aid):
        user_id, _ = require_roles("InstitutionOfficer")
        app = db.account_applications.get(aid)
        if app is None:
            err_not_found("AccountApplication not found")
        body = get_json_body()
        require_fields(body, ["outcome"])
        outcome = check_enum(body["outcome"], {"APPROVE", "DECLINE"}, "outcome")
        decline_reason = body.get("decline_reason")
        chex_flagged = body.get("chex_flagged", False)
        if decline_reason is not None:
            check_enum(decline_reason, DECLINE_REASONS, "decline_reason")
        if not isinstance(chex_flagged, bool):
            err_validation("chex_flagged must be a boolean")
        if outcome == "DECLINE" and decline_reason is None:
            err_validation("decline_reason is required when outcome=DECLINE")

        if user_id != app["institution_id"]:
            err_unauthorized("Officer must belong to the application's institution")

        if app["status"] not in ("SUBMITTED", "REINSTATED"):
            err_invalid_state("Application must be SUBMITTED or REINSTATED to decide")

        institution = db.partner_institutions.get(app["institution_id"])
        participant = db.participants.get(app["participant_id"])

        if outcome == "APPROVE":
            # institution must still be CERTIFIED
            if institution is None or institution["certification_status"] != "CERTIFIED":
                raise_err(ERR_INSTITUTION_NOT_CERTIFIED, "Institution must be CERTIFIED to approve")
            # barrier gate
            flagged = participant.get("prior_banking_record") == "FLAGGED" or chex_flagged
            if flagged:
                resolved = any(
                    c["application_id"] == app["id"] and c["status"] == "RESOLVED"
                    for c in db.barrier_cases.values()
                )
                if not resolved:
                    raise_err(ERR_BARRIER_UNRESOLVED, "A RESOLVED barrier case is required to approve")
            # education gate
            std = db.account_standards.get(institution.get("certified_standard_id"))
            if std is not None and std.get("requires_financial_education"):
                has_pairing = any(
                    p["participant_id"] == participant["id"]
                    and p["status"] in ("COMPLETED", "FOLLOW_UP_DUE", "FOLLOW_UP_DONE")
                    for p in db.education_pairings.values()
                )
                if not has_pairing:
                    raise_err(ERR_EDUCATION_REQUIRED, "Participant must hold a completed education pairing")

            # OPENED transition
            app["status"] = "OPENED"
            app["account_number"] = "acct_" + db.new_id().replace("-", "")[:12]
            app["opened_at"] = db.now_iso()
            app["decided_by_user_id"] = user_id
            touch(app)
            _create_checkpoints(app)
            _close_linked_referral(app, "CLOSED_CONVERTED")
            institution["accounts_opened_total"] = institution.get("accounts_opened_total", 0) + 1
            touch(institution)
            recompute_pipeline(participant["id"])
        else:
            # DECLINE paths
            app["decline_reason"] = decline_reason
            app["decided_by_user_id"] = user_id
            if decline_reason == "CHEX":
                app["status"] = "DECLINED_CHEX"
                touch(app)
                case = new_entity()
                case.update({
                    "application_id": app["id"],
                    "participant_id": app["participant_id"],
                    "institution_id": app["institution_id"],
                    "status": "OPEN",
                    "negotiation_rounds": 0,
                    "proposed_settlement_cents": None,
                    "final_settlement_cents": None,
                    "resolution_note": None,
                })
                db.barrier_cases[case["id"]] = case
                recompute_pipeline(participant["id"])
            elif decline_reason == "INSUFFICIENT_ID":
                app["status"] = "DECLINED_ID"
                touch(app)
                _close_linked_referral(app, "CLOSED_LOST")
                recompute_pipeline(participant["id"])
            else:  # OTHER
                app["status"] = "DECLINED_FINAL"
                touch(app)
                _close_linked_referral(app, "CLOSED_LOST")
                recompute_pipeline(participant["id"])

        return success_object(_serialize(app))

    @bp.route("/account-applications/<aid>/report-closure", methods=["POST"])
    def report_closure(aid):
        user_id, _ = require_roles("InstitutionOfficer")
        app = db.account_applications.get(aid)
        if app is None:
            err_not_found("AccountApplication not found")
        body = get_json_body()
        require_fields(body, ["closed_at"])
        check_string(body["closed_at"], "closed_at")
        if not db.is_valid_iso_datetime(body["closed_at"]):
            err_validation("closed_at must be an ISO 8601 timestamp")
        if user_id != app["institution_id"]:
            err_unauthorized("Officer must belong to the application's institution")
        if app["status"] != "OPENED":
            err_invalid_state("Application must be OPENED to report closure")
        if db.parse_dt(body["closed_at"]) < db.parse_dt(app["opened_at"]):
            err_validation("closed_at must not be earlier than opened_at")
        app["status"] = "CLOSED_EARLY"
        app["closed_at"] = body["closed_at"]
        touch(app)
        return success_object(_serialize(app))
