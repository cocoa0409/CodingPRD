"""Routes: usage records (read-only) and card accuracy audits."""

import db
import domain as D
import errors as E
import util as U
from errors import ApiError

SCA = "SupplyChainAnalyst"
SURGEON = "Surgeon"


def register_routes(app):

    # --------------------------------------------------------- usage records
    @app.route("/perioperative/usage-records", methods=["GET"])
    def list_usage_records():
        U.authenticate()
        limit, offset = U.pagination_params()
        records = U.apply_filters(list(db.usage_records.values()), [
            ("case_id", "case_id"),
            ("pick_list_line_id", "pick_list_line_id"),
            ("supply_item_id", "supply_item_id"),
        ])
        page, total = U.paginate(records, limit, offset)
        return U.success_list([D.ser_usage_record(u) for u in page],
                              total, limit, offset)

    @app.route("/perioperative/usage-records/<uid>", methods=["GET"])
    def get_usage_record(uid):
        U.authenticate()
        record = D.get_or_404(db.usage_records, uid, "UsageRecord")
        return U.success_object(D.ser_usage_record(record), 200)

    # ------------------------------------------------------------ card audits
    @app.route("/perioperative/card-audits", methods=["GET"])
    def list_audits():
        U.authenticate()
        limit, offset = U.pagination_params()
        audits = U.apply_filters(list(db.audits.values()), [
            ("case_id", "case_id"),
            ("card_id", "card_id"),
            ("status", "status"),
        ])
        page, total = U.paginate(audits, limit, offset)
        return U.success_list([D.ser_audit(a) for a in page],
                              total, limit, offset)

    @app.route("/perioperative/card-audits/<aid>", methods=["GET"])
    def get_audit(aid):
        U.authenticate()
        audit = D.get_or_404(db.audits, aid, "CardAccuracyAudit")
        return U.success_object(D.ser_audit(audit), 200)

    @app.route("/perioperative/card-audits/<aid>/accept", methods=["POST"])
    def accept_audit(aid):
        _, role = U.authenticate()
        U.authorize(role, [SCA])
        audit = D.get_or_404(db.audits, aid, "CardAccuracyAudit")
        if audit["status"] not in ("GENERATED", "UNDER_REVIEW"):
            raise ApiError(E.ERR_AUDIT_NOT_ACTIONABLE,
                           "Audit is not in GENERATED or UNDER_REVIEW", 409)
        audit["status"] = "ACCEPTED"
        D.bump(audit)
        return U.success_object(D.ser_audit(audit), 200)

    @app.route("/perioperative/card-audits/<aid>/dispute", methods=["POST"])
    def dispute_audit(aid):
        uid, role = U.authenticate()
        U.authorize(role, [SURGEON])
        body = U.get_body()
        comment = U.opt_str(body, "comment")
        audit = D.get_or_404(db.audits, aid, "CardAccuracyAudit")
        # Entity-backed ownership: only the surgeon owning the audited card
        card = db.preference_cards.get(audit["card_id"])
        if card is None or card["surgeon_id"] != uid:
            raise ApiError(E.ERR_FORBIDDEN_FOR_ROLE,
                           "Only the surgeon who owns the audited card may "
                           "dispute it", 403)
        if audit["status"] not in ("GENERATED", "UNDER_REVIEW"):
            raise ApiError(E.ERR_AUDIT_NOT_ACTIONABLE,
                           "Audit is not in GENERATED or UNDER_REVIEW", 409)
        audit["status"] = "DISPUTED"
        audit["dispute_comment"] = comment
        D.bump(audit)
        return U.success_object(D.ser_audit(audit), 200)

    @app.route("/perioperative/card-audits/<aid>/reopen-review",
               methods=["POST"])
    def reopen_review(aid):
        _, role = U.authenticate()
        U.authorize(role, [SCA])
        audit = D.get_or_404(db.audits, aid, "CardAccuracyAudit")
        if audit["status"] != "DISPUTED":
            raise ApiError(E.ERR_AUDIT_NOT_DISPUTED,
                           "Audit is not DISPUTED", 409)
        audit["status"] = "UNDER_REVIEW"
        D.bump(audit)
        return U.success_object(D.ser_audit(audit), 200)
