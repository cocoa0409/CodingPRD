"""Resale certificates: request, issuance pinning, operator void and the
recomputed lender questionnaire (PRD 3.9)."""
from flask import request

import clock
import db
import response
import serialize
import validation as V
from auth import authenticate
from errors import ApiError
from services import certificate, ledger

CERT_STATUSES = ("REQUESTED", "ISSUED", "VOIDED", "EXPIRED")
PAYOFF_BASES = ("LEDGER_BALANCE", "ESTIMATED_PAYOFF")


def register(app):

    @app.post("/units/<unit_id>/resale-certificates")
    def request_certificate(unit_id):
        authenticate(("TitleAgent", "CommunityManager"))
        found = V.resolve_path(unit_id=unit_id)
        unit = found["unit_id"]
        body = V.body_of()
        closing_date = V.require_dt(body, "closing_date")
        payoff_basis = V.require_enum(body, "payoff_basis", PAYOFF_BASES,
                                      required=False, default="LEDGER_BALANCE")
        requesting_agent_id = V.require_str(body, "requesting_agent_id", min_len=1)
        V.require_int(body, "expected_unit_version", minimum=0)
        # Rung 9.
        V.occ(body, "expected_unit_version", unit, "ERR_STALE_UNIT_VERSION")

        # A newer request supersedes every other still-REQUESTED certificate of the
        # unit.  This is an operator-style void: requires_reissue stays false and no
        # fee is involved because a REQUESTED certificate never posted one.
        for other in db.sorted_rows(
                "resale_certificates",
                lambda c: c["unit_id"] == unit["id"] and c["status"] == "REQUESTED"):
            other["status"] = "VOIDED"
            other["requires_reissue"] = False
            db.touch(other)

        row = db.base_fields()
        row.update({
            "unit_id": unit["id"],
            "pinned_budget_id": None,
            "requesting_agent_id": requesting_agent_id,
            "closing_date": closing_date,
            "payoff_basis": payoff_basis,
            "status": "REQUESTED",
            "pinned_unit_version": None,
            "pinned_budget_version": None,
            "ledger_balance_cents": 0,
            "projected_payoff_cents": 0,
            "proration_credit_cents": 0,
            "open_violation_count": 0,
            "special_assessment_disclosure_cents": 0,
            "disclosed_claim_ids": [],
            "cert_fee_entry_id": None,
            "requires_reissue": False,
            "issued_at": None,
            "expires_at": None,
        })
        db.insert("resale_certificates", row)
        db.touch(unit)
        return response.created(serialize.view(row))

    @app.get("/resale-certificates")
    def list_certificates():
        authenticate(("CommunityManager", "TitleAgent", "BoardTreasurer", "UnitOwner"))
        limit, offset = V.pagination()
        args = request.args
        status = args.get("status")
        if status is not None and status not in CERT_STATUSES:
            V.fail("Query parameter 'status' is not a recognized certificate status.")

        def keep(c):
            for name in ("unit_id", "pinned_budget_id", "cert_fee_entry_id"):
                want = args.get(name)
                if want and c.get(name) != want:
                    return False
            if status and c["status"] != status:
                return False
            return True

        rows = db.sorted_rows("resale_certificates", keep)
        page, total = V.paginate(rows, limit, offset)
        return response.listing(serialize.views(page), limit, offset, total)

    @app.post("/resale-certificates/<resale_certificate_id>/issue")
    def issue_certificate(resale_certificate_id):
        authenticate(("CommunityManager",))
        found = V.resolve_path(resale_certificate_id=resale_certificate_id)
        cert = found["resale_certificate_id"]
        unit = db.get("units", cert["unit_id"])
        if unit is None:
            raise ApiError("ERR_UNIT_NOT_FOUND")
        assoc = db.get("associations", unit["association_id"])
        V.body_of()
        # Rung 12.
        if cert["status"] != "REQUESTED":
            raise ApiError("ERR_INVALID_CERTIFICATE_STATE")
        # Rung 17.
        if unit["delinquency_stage"] == "FORECLOSURE_REFERRAL":
            raise ApiError("ERR_CERT_BLOCKED_BY_FORECLOSURE")
        # Rung 38 -- the fiscal year containing closing_date must be adopted.
        budget = certificate.adopted_budget_for(assoc, cert["closing_date"])
        if budget is None:
            raise ApiError("ERR_BUDGET_NOT_ADOPTED")
        # Rung 56 -- the closing instant itself is still in time.
        now = clock.now()
        if cert["closing_date"] < now:
            raise ApiError("ERR_CERT_CLOSING_DATE_PAST")

        # The effect order is load bearing: the fee lands FIRST so that the pinned
        # unit version and the payoff figures already include it.
        fee = ledger.post_entry(unit, "RESALE_FEE", assoc["resale_cert_fee_cents"],
                                _period(now), due_on=clock.add_days(now, 30))
        cert["cert_fee_entry_id"] = fee["id"]
        ledger.recompute_unit(unit)

        figures = certificate.payoff(unit, cert["closing_date"], cert["payoff_basis"])
        cert["pinned_unit_version"] = unit["version"]
        cert["pinned_budget_id"] = budget["id"]
        cert["pinned_budget_version"] = budget["version"]
        cert.update(figures)
        cert["issued_at"] = now
        cert["expires_at"] = clock.add_days(now, assoc["certificate_validity_days"])
        cert["status"] = "ISSUED"
        # An ISSUED, unexpired certificate is exactly what unblocks the transfer.
        unit["transfer_blocked"] = False
        db.touch(cert)
        return response.ok(serialize.view(cert))

    @app.post("/resale-certificates/<resale_certificate_id>/void")
    def void_certificate(resale_certificate_id):
        authenticate(("CommunityManager",))
        found = V.resolve_path(resale_certificate_id=resale_certificate_id)
        cert = found["resale_certificate_id"]
        body = V.body_of()
        V.require_str(body, "reason", required=False, default=None)
        # Rung 12.
        if cert["status"] != "ISSUED":
            raise ApiError("ERR_INVALID_CERTIFICATE_STATE")

        # An operator void diverges from the cascade void: requires_reissue stays
        # false and the RESALE_FEE entry is NOT refunded.
        cert["status"] = "VOIDED"
        cert["requires_reissue"] = False
        unit = db.get("units", cert["unit_id"])
        if unit is not None:
            unit["transfer_blocked"] = ledger.transfer_blocked_of(unit["id"])
            db.touch(unit)
        db.touch(cert)
        return response.ok(serialize.view(cert))

    @app.get("/resale-certificates/<resale_certificate_id>/lender-questionnaire")
    def lender_questionnaire(resale_certificate_id):
        authenticate(("TitleAgent", "CommunityManager", "BoardTreasurer"))
        found = V.resolve_path(resale_certificate_id=resale_certificate_id)
        cert = found["resale_certificate_id"]
        unit = db.get("units", cert["unit_id"])
        if unit is None:
            raise ApiError("ERR_UNIT_NOT_FOUND")

        # A pure read: the stored certificate is never mutated.
        view = serialize.view(cert)
        figures = certificate.payoff(unit, cert["closing_date"], cert["payoff_basis"])
        view.update(figures)
        view["requires_reissue"] = bool(
            cert.get("requires_reissue")
            or cert.get("pinned_unit_version") != unit["version"])
        view["delinquency_stage"] = unit["delinquency_stage"]
        view["balance_due_cents"] = unit["balance_due_cents"]
        view["oldest_unpaid_age_days"] = unit.get("oldest_unpaid_age_days", 0)
        return response.ok(view)


def _period(dt):
    return "%04d-%02d" % (dt.year, dt.month)
