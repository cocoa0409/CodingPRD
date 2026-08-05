"""Routes: attachments, unauthorized findings, invoices, disputes."""

from flask import request

import constants as C
from clock import LOGICAL_CLOCK
from store import DB, touch
from errors import ApiError
from response import object_response, array_response
import serializers as S
import domain
import common as X

READ_ALL = ["JointUseCoordinator", "Engineer", "PermitOfficer", "FieldAuditor", "Attacher"]
FINDING_READ = ["JointUseCoordinator", "FieldAuditor", "Attacher"]
INVOICE_READ = ["JointUseCoordinator", "Attacher"]
DISPUTE_READ = ["JointUseCoordinator", "Attacher"]

DISPUTE_TARGET_STATES = {
    "UNDER_REVIEW", "INFO_REQUESTED", "RESOLVED_UPHELD", "RESOLVED_ADJUSTED", "WITHDRAWN",
}


def _page(records, serializer):
    limit, offset = X.paginate()
    ordered = X.apply_pagination(records)
    total = len(ordered)
    window = ordered[offset:offset + limit]
    return array_response([serializer(r) for r in window], limit, offset, total)


def register(app):

    # ======================= ATTACHMENTS ====================================
    @app.route("/joint-use/attachments", methods=["GET"])
    def list_attachments():
        _, role = X.current_actor()
        X.authorize(role, READ_ALL)
        pole_id = request.args.get("pole_id")
        attacher_id = request.args.get("attacher_id")
        application_id = request.args.get("application_id")
        recs = [a for a in DB.attachments.values()
                if (pole_id is None or a["pole_id"] == pole_id)
                and (attacher_id is None or a["attacher_id"] == attacher_id)
                and (application_id is None or a["application_id"] == application_id)]
        return _page(recs, S.attachment_json)

    @app.route("/joint-use/attachments/<att_id>", methods=["GET"])
    def get_attachment(att_id):
        _, role = X.current_actor()
        X.authorize(role, READ_ALL)
        rec = X.get_attachment(att_id)
        return object_response(S.attachment_json(rec), 200)

    @app.route("/joint-use/attachments/<att_id>/transfer", methods=["POST"])
    def transfer_attachment(att_id):
        user_id, role = X.current_actor()
        X.authorize(role, ["Attacher"])
        att = X.get_attachment(att_id)
        X.require_owner(att["attacher_id"], user_id)
        body = X.get_body()
        new_attacher = X.get_attacher(X.req_str(body, "new_attacher_id"))
        if att["status"] != "ACTIVE":
            raise ApiError("ERR_INVALID_STATE", "Attachment is not ACTIVE.")
        att["status"] = "TRANSFERRED"
        touch(att)
        new_att = DB.new_record({
            "pole_id": att["pole_id"],
            "attacher_id": new_attacher["id"],
            "application_id": att["application_id"],
            "allotted_space_inches": att["allotted_space_inches"],
            "position_inches": att["position_inches"],
            "authorized": True,
            "transferred_from_attacher_id": att["attacher_id"],
            "status": "ACTIVE",
        })
        DB.attachments[new_att["id"]] = new_att
        pole = DB.poles.get(att["pole_id"])
        if pole is not None:
            domain.recompute_pole(pole)
        return object_response(S.attachment_json(att), 200)

    @app.route("/joint-use/attachments/<att_id>/abandon", methods=["POST"])
    def abandon_attachment(att_id):
        user_id, role = X.current_actor()
        X.authorize(role, ["Attacher"])
        att = X.get_attachment(att_id)
        X.require_owner(att["attacher_id"], user_id)
        if att["status"] != "ACTIVE":
            raise ApiError("ERR_INVALID_STATE", "Attachment is not ACTIVE.")
        att["status"] = "ABANDONED"
        touch(att)
        pole = DB.poles.get(att["pole_id"])
        if pole is not None:
            domain.recompute_pole(pole)
        return object_response(S.attachment_json(att), 200)

    # ======================= FINDINGS =======================================
    @app.route("/joint-use/findings", methods=["POST"])
    def create_finding():
        user_id, role = X.current_actor()
        X.authorize(role, ["FieldAuditor"])
        body = X.get_body()
        pole = X.get_pole(X.req_str(body, "pole_id"))
        attacher = X.get_attacher(X.req_str(body, "attacher_id"))
        space = X.req_int_positive(body, "discovered_space_inches")
        position = X.req_int_positive(body, "discovered_position_inches")
        good_faith = X.req_bool(body, "good_faith")
        years_ago = X.req_int_min(body, "estimated_install_years_ago", 1)
        owner = DB.pole_owners[pole["pole_owner_id"]]
        finding = DB.new_record({
            "pole_id": pole["id"],
            "attacher_id": attacher["id"],
            "auditor_user_id": user_id,
            "audited_at": LOGICAL_CLOCK.now(),
            "discovered_space_inches": space,
            "discovered_position_inches": position,
            "good_faith": good_faith,
            "estimated_install_years_ago": years_ago,
            "penalty_cents": None,
            "back_rental_cents": None,
            "penalty_invoice_id": None,
            "resulting_attachment_id": None,
            "status": "FLAGGED",
        })
        penalty, back_rental = domain.penalty_and_back_rental(owner, finding)
        finding["penalty_cents"] = penalty
        finding["back_rental_cents"] = back_rental
        DB.findings[finding["id"]] = finding
        inv = domain.issue_invoice(attacher, "UNAUTHORIZED", penalty + back_rental, [],
                                   finding_id=finding["id"])
        finding["penalty_invoice_id"] = inv["id"]
        return object_response(S.finding_json(finding), 201)

    @app.route("/joint-use/findings", methods=["GET"])
    def list_findings():
        _, role = X.current_actor()
        X.authorize(role, FINDING_READ)
        pole_id = request.args.get("pole_id")
        attacher_id = request.args.get("attacher_id")
        recs = [f for f in DB.findings.values()
                if (pole_id is None or f["pole_id"] == pole_id)
                and (attacher_id is None or f["attacher_id"] == attacher_id)]
        return _page(recs, S.finding_json)

    @app.route("/joint-use/findings/<finding_id>", methods=["GET"])
    def get_finding(finding_id):
        _, role = X.current_actor()
        X.authorize(role, FINDING_READ)
        rec = X.get_finding(finding_id)
        return object_response(S.finding_json(rec), 200)

    @app.route("/joint-use/findings/<finding_id>/resolve", methods=["POST"])
    def resolve_finding(finding_id):
        _, role = X.current_actor()
        X.authorize(role, ["JointUseCoordinator"])
        finding = X.get_finding(finding_id)
        body = X.get_body()
        resolution = X.req_enum(body, "resolution", {"LEGALIZE", "REMOVE"})
        if finding["status"] not in ("FLAGGED", "DISPUTED"):
            raise ApiError("ERR_INVALID_STATE", "Finding is terminal.")
        if resolution == "REMOVE":
            finding["status"] = "REMOVED"
            touch(finding)
            return object_response(S.finding_json(finding), 200)
        # LEGALIZE
        pole = DB.poles[finding["pole_id"]]
        if pole["status"] != "ACTIVE":
            raise ApiError("ERR_POLE_NOT_ACTIVE", "Pole is not ACTIVE.")
        available = (pole["usable_communication_space_inches"]
                     - pole["occupied_space_inches"] - pole["reserved_space_inches"])
        if finding["discovered_space_inches"] > available:
            raise ApiError("ERR_INSUFFICIENT_POLE_SPACE", "Not enough communication space.")
        attachment = DB.new_record({
            "pole_id": pole["id"],
            "attacher_id": finding["attacher_id"],
            "application_id": None,
            "allotted_space_inches": finding["discovered_space_inches"],
            "position_inches": finding["discovered_position_inches"],
            "authorized": False,
            "transferred_from_attacher_id": None,
            "status": "ACTIVE",
        })
        DB.attachments[attachment["id"]] = attachment
        finding["resulting_attachment_id"] = attachment["id"]
        finding["status"] = "LEGALIZED"
        touch(finding)
        domain.recompute_pole(pole)
        return object_response(S.finding_json(finding), 200)

    # ======================= INVOICES =======================================
    @app.route("/joint-use/invoices", methods=["POST"])
    def create_invoice():
        _, role = X.current_actor()
        X.authorize(role, ["JointUseCoordinator"])
        body = X.get_body()
        attacher = X.get_attacher(X.req_str(body, "attacher_id"))
        owner = X.get_pole_owner(X.req_str(body, "pole_owner_id"))
        invoice_type = X.req_enum(body, "invoice_type", C.INVOICE_TYPES)
        amount, line_items = domain.annual_rental_true_up(owner, attacher["id"], owner["id"])
        inv = domain.issue_invoice(attacher, invoice_type, amount, line_items,
                                   pole_owner_id=owner["id"])
        return object_response(S.invoice_json(inv), 201)

    @app.route("/joint-use/invoices", methods=["GET"])
    def list_invoices():
        _, role = X.current_actor()
        X.authorize(role, INVOICE_READ)
        attacher_id = request.args.get("attacher_id")
        pole_owner_id = request.args.get("pole_owner_id")
        application_id = request.args.get("application_id")
        finding_id = request.args.get("finding_id")
        recs = [i for i in DB.invoices.values()
                if (attacher_id is None or i["attacher_id"] == attacher_id)
                and (pole_owner_id is None or i["pole_owner_id"] == pole_owner_id)
                and (application_id is None or i["application_id"] == application_id)
                and (finding_id is None or i["finding_id"] == finding_id)]
        return _page(recs, S.invoice_json)

    @app.route("/joint-use/invoices/<invoice_id>", methods=["GET"])
    def get_invoice(invoice_id):
        _, role = X.current_actor()
        X.authorize(role, INVOICE_READ)
        rec = X.get_invoice(invoice_id)
        return object_response(S.invoice_json(rec), 200)

    @app.route("/joint-use/invoices/<invoice_id>/pay", methods=["POST"])
    def pay_invoice(invoice_id):
        user_id, role = X.current_actor()
        X.authorize(role, ["Attacher"])
        inv = X.get_invoice(invoice_id)
        X.require_owner(inv["attacher_id"], user_id)
        if inv["status"] in ("PAID", "VOID"):
            raise ApiError("ERR_INVOICE_ALREADY_TERMINAL", "Invoice is already terminal.")
        if inv["status"] not in ("ISSUED", "OVERDUE"):
            raise ApiError("ERR_INVALID_STATE", "Invoice cannot be paid.")
        for d in DB.disputes.values():
            if d["invoice_id"] == inv["id"] and d["status"] in ("OPEN", "UNDER_REVIEW", "INFO_REQUESTED"):
                raise ApiError("ERR_INVOICE_UNDER_DISPUTE", "Invoice is under dispute.")
        inv["status"] = "PAID"
        touch(inv)
        attacher = DB.attachers.get(inv["attacher_id"])
        if attacher is not None:
            domain.recompute_balance(attacher)
        return object_response(S.invoice_json(inv), 200)

    @app.route("/joint-use/invoices/<invoice_id>/void", methods=["POST"])
    def void_invoice_route(invoice_id):
        _, role = X.current_actor()
        X.authorize(role, ["JointUseCoordinator"])
        inv = X.get_invoice(invoice_id)
        if inv["status"] in ("PAID", "VOID"):
            raise ApiError("ERR_INVOICE_ALREADY_TERMINAL", "Invoice is already terminal.")
        if inv["status"] not in ("ISSUED", "OVERDUE"):
            raise ApiError("ERR_INVALID_STATE", "Invoice cannot be voided.")
        domain.void_invoice(inv)
        return object_response(S.invoice_json(inv), 200)

    # ======================= DISPUTES =======================================
    @app.route("/joint-use/disputes", methods=["POST"])
    def open_dispute():
        user_id, role = X.current_actor()
        X.authorize(role, ["Attacher"])
        body = X.get_body()
        aid = body.get("attacher_id")
        if isinstance(aid, str) and aid != user_id:
            raise ApiError("ERR_UNAUTHORIZED", "Attacher may only open its own disputes.")
        attacher = X.get_attacher(X.req_str(body, "attacher_id"))
        X.require_owner(attacher["id"], user_id)
        invoice_id = body.get("invoice_id")
        finding_id = body.get("finding_id")
        if invoice_id is not None:
            X.get_invoice(invoice_id)
        if finding_id is not None:
            X.get_finding(finding_id)
        if (invoice_id is not None) == (finding_id is not None):
            raise ApiError("ERR_DISPUTE_SUBJECT_INVALID",
                           "Exactly one of invoice_id / finding_id must be set.")
        reason = X.req_str(body, "reason")
        rec = DB.new_record({
            "attacher_id": attacher["id"],
            "invoice_id": invoice_id,
            "finding_id": finding_id,
            "reason": reason,
            "round_count": 0,
            "resolution": None,
            "adjusted_amount_cents": None,
            "status": "OPEN",
        })
        DB.disputes[rec["id"]] = rec
        if finding_id is not None:
            finding = DB.findings[finding_id]
            if finding["status"] == "FLAGGED":
                finding["status"] = "DISPUTED"
                touch(finding)
        return object_response(S.dispute_json(rec), 201)

    @app.route("/joint-use/disputes", methods=["GET"])
    def list_disputes():
        _, role = X.current_actor()
        X.authorize(role, DISPUTE_READ)
        attacher_id = request.args.get("attacher_id")
        invoice_id = request.args.get("invoice_id")
        finding_id = request.args.get("finding_id")
        recs = [d for d in DB.disputes.values()
                if (attacher_id is None or d["attacher_id"] == attacher_id)
                and (invoice_id is None or d["invoice_id"] == invoice_id)
                and (finding_id is None or d["finding_id"] == finding_id)]
        return _page(recs, S.dispute_json)

    @app.route("/joint-use/disputes/<dispute_id>", methods=["GET"])
    def get_dispute(dispute_id):
        _, role = X.current_actor()
        X.authorize(role, DISPUTE_READ)
        rec = X.get_dispute(dispute_id)
        return object_response(S.dispute_json(rec), 200)

    @app.route("/joint-use/disputes/<dispute_id>/transition", methods=["POST"])
    def transition_dispute(dispute_id):
        user_id, role = X.current_actor()
        X.authorize(role, ["Attacher", "JointUseCoordinator"])
        dispute = X.get_dispute(dispute_id)
        body = X.get_body()
        to_state = X.req_enum(body, "to_state", DISPUTE_TARGET_STATES)
        current = dispute["status"]

        def need_juc():
            X.authorize(role, ["JointUseCoordinator"])

        def need_owner():
            X.authorize(role, ["Attacher"])
            X.require_owner(dispute["attacher_id"], user_id)

        if current == "OPEN" and to_state == "UNDER_REVIEW":
            need_juc()
            dispute["status"] = "UNDER_REVIEW"
        elif current == "UNDER_REVIEW" and to_state == "INFO_REQUESTED":
            need_juc()
            dispute["status"] = "INFO_REQUESTED"
        elif current == "INFO_REQUESTED" and to_state == "UNDER_REVIEW":
            need_owner()
            dispute["round_count"] += 1
            dispute["status"] = "UNDER_REVIEW"
        elif current == "UNDER_REVIEW" and to_state == "RESOLVED_UPHELD":
            need_juc()
            dispute["resolution"] = "UPHELD"
            dispute["status"] = "RESOLVED_UPHELD"
        elif current == "UNDER_REVIEW" and to_state == "RESOLVED_ADJUSTED":
            need_juc()
            adj = body.get("adjusted_amount_cents")
            if isinstance(adj, bool) or not isinstance(adj, int) or adj < 0:
                raise ApiError("ERR_VALIDATION", "adjusted_amount_cents must be a non-negative integer.")
            inv = DB.invoices.get(dispute["invoice_id"]) if dispute["invoice_id"] else None
            if inv is None or inv["status"] not in ("ISSUED", "OVERDUE"):
                raise ApiError("ERR_INVALID_STATE", "Dispute must reference an ISSUED/OVERDUE invoice.")
            dispute["resolution"] = "ADJUSTED"
            dispute["adjusted_amount_cents"] = adj
            inv["amount_cents"] = adj
            touch(inv)
            attacher = DB.attachers.get(inv["attacher_id"])
            if attacher is not None:
                domain.recompute_balance(attacher)
            dispute["status"] = "RESOLVED_ADJUSTED"
        elif to_state == "WITHDRAWN" and current in ("OPEN", "UNDER_REVIEW", "INFO_REQUESTED"):
            need_owner()
            dispute["status"] = "WITHDRAWN"
        else:
            raise ApiError("ERR_INVALID_STATE", "Invalid dispute transition.")
        touch(dispute)
        return object_response(S.dispute_json(dispute), 200)
