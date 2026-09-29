"""Unit ledger: statements, payments, manual charges, reversals, and closing."""
from flask import g, request

import clock
import db
import response
import serialize
import validation as V
from auth import authenticate
from errors import ApiError
from services import assessment, ledger

APPLICATION_MODES = ("STATUTORY", "OWNER_DIRECTED")


def register(app):

    @app.get("/units/<unit_id>/statement")
    def unit_statement(unit_id):
        authenticate(("CommunityManager", "BoardTreasurer", "UnitOwner"))
        found = V.resolve_path(unit_id=unit_id)
        unit = found["unit_id"]
        V.owner_scope(unit)
        buckets = {b: 0 for b in ledger.BUCKETS}
        for e in ledger.open_charges(unit_id):
            buckets[e["bucket"]] += e["amount_cents"] - e["applied_cents"]
        return response.ok({
            "unit_id": unit_id,
            "association_id": unit["association_id"],
            "open_balances": buckets,
            "oldest_unpaid_age_days": unit["oldest_unpaid_age_days"],
            "balance_due_cents": unit["balance_due_cents"],
            "credit_balance_cents": unit["credit_balance_cents"],
            "delinquency_stage": unit["delinquency_stage"],
        })

    @app.post("/units/<unit_id>/payments")
    def record_payment(unit_id):
        authenticate(("CommunityManager", "BoardTreasurer", "UnitOwner"))
        found = V.resolve_path(unit_id=unit_id)
        unit = found["unit_id"]
        body = V.body_of()
        amount = V.require_int(body, "amount_cents", minimum=1)
        effective_period = V.require_period(body, "effective_period")
        application_mode = V.require_enum(body, "application_mode", APPLICATION_MODES,
                                          required=False, default=None)
        directed_bucket = V.require_enum(
            body, "directed_bucket",
            tuple(b for b in ledger.BUCKETS if b != "NONE"),
            required=False, default=None)
        memo = V.require_str(body, "memo", required=False, default=None)

        payment = ledger.post_entry(unit, "PAYMENT", -amount, effective_period,
                                    due_on=None, memo=memo)
        allocations = ledger.apply_payment(unit, payment, amount,
                                           application_mode=application_mode,
                                           directed_bucket=directed_bucket)
        ledger.recompute_unit(unit)
        assessment.on_payment_collection(unit, allocations)
        return response.created(serialize.view(payment))

    @app.post("/units/<unit_id>/charges")
    def post_charge(unit_id):
        authenticate(("CommunityManager", "BoardTreasurer"))
        found = V.resolve_path(unit_id=unit_id)
        unit = found["unit_id"]
        body = V.body_of()
        entry_type = V.require_enum(body, "entry_type", ledger.MANUAL_CHARGE_TYPES)
        amount = V.require_int(body, "amount_cents", allow_zero=False)
        due_on = V.require_dt(body, "due_on")
        effective_period = V.require_period(body, "effective_period")
        memo = V.require_str(body, "memo", required=False, default=None)

        entry = ledger.post_entry(unit, entry_type, amount, effective_period,
                                  due_on=due_on, memo=memo)
        ledger.recompute_unit(unit)
        return response.created(serialize.view(entry))

    @app.post("/ledger-entries/<ledger_entry_id>/reverse")
    def reverse_ledger_entry(ledger_entry_id):
        authenticate(("BoardTreasurer",))
        found = V.resolve_path(ledger_entry_id=ledger_entry_id)
        original = found["ledger_entry_id"]
        body = V.body_of()
        memo = V.require_str(body, "memo", required=False, default=None)
        # Rung 48.
        if original["status"] != "POSTED" or original["amount_cents"] <= 0:
            raise ApiError("ERR_ENTRY_ALREADY_REVERSED")
        unit = db.get("units", original["unit_id"])
        rev = ledger.reverse_entry(unit, original, memo=memo)
        ledger.recompute_unit(unit)
        for sa in db.store["special_assessments"].values():
            if sa["association_id"] == unit["association_id"]:
                assessment.refresh_money(sa)
        assessment.refresh_restricted_cash(unit["association_id"])
        return response.created(serialize.view(rev))

    @app.get("/ledger-entries")
    def list_ledger_entries():
        authenticate(("CommunityManager", "BoardTreasurer", "UnitOwner", "TitleAgent"))
        limit, offset = V.pagination()
        args = request.args
        entry_type = args.get("entry_type")
        if entry_type is not None and entry_type not in ledger.ENTRY_TYPES:
            V.fail("Query parameter 'entry_type' is not a recognized entry type.")
        bucket = args.get("bucket")
        if bucket is not None and bucket not in ledger.BUCKETS:
            V.fail("Query parameter 'bucket' is not a recognized bucket.")
        status = args.get("status")
        if status is not None and status not in ("POSTED", "REVERSED"):
            V.fail("Query parameter 'status' is not a recognized status.")

        simple = ("unit_id", "billing_run_id", "source_case_id",
                  "special_assessment_id", "source_claim_id", "reverses_entry_id")

        def keep(r):
            for name in simple:
                want = args.get(name)
                if want and r.get(name) != want:
                    return False
            if entry_type and r["entry_type"] != entry_type:
                return False
            if bucket and r["bucket"] != bucket:
                return False
            if status and r["status"] != status:
                return False
            return True

        rows = db.sorted_rows("ledger_entries", keep)
        page, total = V.paginate(rows, limit, offset)
        return response.listing(serialize.views(page), limit, offset, total)

    @app.post("/units/<unit_id>/transfer-ownership")
    def transfer_ownership(unit_id):
        authenticate(("CommunityManager",))
        found = V.resolve_path(unit_id=unit_id)
        unit = found["unit_id"]
        body = V.body_of()
        fk = V.resolve_body_fk(body, "new_owner_id", "certificate_id")
        new_owner = fk["new_owner_id"]
        cert = fk["certificate_id"]
        if new_owner is None:
            V.fail("Field 'new_owner_id' is required.")
        if cert is None:
            V.fail("Field 'certificate_id' is required.")
        V.scope_match(unit["association_id"], new_owner, cert)

        # Rung 23.
        now = clock.now()
        if (cert["unit_id"] != unit_id or cert["status"] != "ISSUED"
                or cert["expires_at"] is None or not now < cert["expires_at"]):
            raise ApiError("ERR_NO_VALID_CERTIFICATE")
        # Rung 24.
        if unit["version"] != cert.get("pinned_unit_version"):
            raise ApiError("ERR_CERTIFICATE_STALE")

        outgoing = db.get("owners", unit["current_owner_id"])
        cert["status"] = "EXPIRED"
        db.touch(cert)

        unit["current_owner_id"] = new_owner["id"]
        unit["transfer_blocked"] = True
        db.touch(unit)

        if outgoing is not None:
            outgoing["owned_unit_count"] = max(0, outgoing["owned_unit_count"] - 1)
            db.touch(outgoing)
        new_owner["owned_unit_count"] += 1
        db.touch(new_owner)
        return response.ok(serialize.view(unit))
