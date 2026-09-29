"""Special assessments (balloting, collection, rescission, refund) and the vote
register."""
from flask import g, request

import clock
import db
import money
import response
import serialize
import validation as V
from auth import authenticate
from errors import ApiError
from services import alloc, assessment, ledger

APPROVAL_STATUSES = ("DRAFT", "BALLOTING", "APPROVED", "FAILED", "RESCINDED")
FUNDING_STATUSES = ("UNFUNDED", "PARTIALLY_COLLECTED", "FULLY_COLLECTED", "REFUNDING",
                    "REFUNDED")
SUBJECT_TYPES = ("BUDGET", "SPECIAL_ASSESSMENT", "VENDOR_CONTRACT", "VIOLATION_FINE")
SUBJECT_COLLECTIONS = {
    "BUDGET": "budgets",
    "SPECIAL_ASSESSMENT": "special_assessments",
    "VENDOR_CONTRACT": "vendor_contracts",
    "VIOLATION_FINE": "violation_cases",
}
CHOICES = ("YES", "NO", "ABSTAIN")


def recompute_contract_yes_count(contract):
    contract["approval_yes_count"] = sum(
        1 for v in db.store["votes"].values()
        if v["subject_type"] == "VENDOR_CONTRACT" and v["subject_id"] == contract["id"]
        and v["voter_kind"] == "BOARD_DIRECTOR" and v["choice"] == "YES"
        and v["counted"])
    return contract


def register(app):

    # ------------------------------------------------------ special assessments

    @app.post("/associations/<association_id>/special-assessments")
    def create_special_assessment(association_id):
        authenticate(("BoardTreasurer",))
        found = V.resolve_path(association_id=association_id)
        assoc = found["association_id"]
        body = V.body_of()
        fk = V.resolve_body_fk(body, "funding_claim_id")
        claim = fk["funding_claim_id"]
        purpose = V.require_str(body, "purpose", min_len=1)
        total_amount = V.require_int(body, "total_amount_cents", minimum=1)
        installment_count = V.require_int(body, "installment_count", minimum=1,
                                          maximum=24)
        V.require_int(body, "expected_association_version", minimum=0)
        if claim is not None:
            V.scope_match(association_id, claim)
        V.occ(body, "expected_association_version", assoc,
              "ERR_STALE_ASSOCIATION_VERSION")

        row = db.base_fields()
        row.update({
            "association_id": association_id,
            "funding_claim_id": claim["id"] if claim else None,
            "purpose": purpose,
            "total_amount_cents": total_amount,
            "installment_count": installment_count,
            "approval_status": "DRAFT",
            "funding_status": "UNFUNDED",
            "ballot_opened_at": None,
            "ballot_closed_at": None,
            "eligible_weight_bp": 0,
            "yes_weight_bp": 0,
            "installments_posted": 0,
            "charged_cents": 0,
            "collected_cents": 0,
            "refunded_cents": 0,
            "requires_supermajority_disclosure": False,
        })
        db.insert("special_assessments", row)
        db.touch(assoc)
        return response.created(serialize.view(row))

    @app.get("/special-assessments")
    def list_special_assessments():
        authenticate(("CommunityManager", "BoardDirector", "BoardTreasurer",
                      "TitleAgent", "AssociationAttorney"))
        limit, offset = V.pagination()
        args = request.args
        approval_status = args.get("approval_status")
        if approval_status is not None and approval_status not in APPROVAL_STATUSES:
            V.fail("Query parameter 'approval_status' is not recognized.")
        funding_status = args.get("funding_status")
        if funding_status is not None and funding_status not in FUNDING_STATUSES:
            V.fail("Query parameter 'funding_status' is not recognized.")

        def keep(s):
            for name in ("association_id", "funding_claim_id"):
                want = args.get(name)
                if want and s.get(name) != want:
                    return False
            if approval_status and s["approval_status"] != approval_status:
                return False
            if funding_status and s["funding_status"] != funding_status:
                return False
            return True

        rows = db.sorted_rows("special_assessments", keep)
        page, total = V.paginate(rows, limit, offset)
        return response.listing(serialize.views(page), limit, offset, total)

    @app.post("/special-assessments/<special_assessment_id>/open-ballot")
    def open_ballot(special_assessment_id):
        authenticate(("BoardDirector",))
        found = V.resolve_path(special_assessment_id=special_assessment_id)
        sa = found["special_assessment_id"]
        assoc = db.get("associations", sa["association_id"])
        V.body_of()
        # Rung 12.
        if sa["approval_status"] != "DRAFT":
            raise ApiError("ERR_INVALID_BALLOT_STATE")
        if sa.get("funding_claim_id"):
            claim = db.get("insurance_claims", sa["funding_claim_id"])
            if claim is None or claim["litigation_status"] not in ("TENDERED",
                                                                  "IN_LITIGATION"):
                raise ApiError("ERR_INVALID_CLAIM_STATE")
        # Rung 35.
        if assoc["total_interest_bp"] != 10000:
            raise ApiError("ERR_INTEREST_SUM_INVALID")
        # Rung 39.
        for other in db.store["special_assessments"].values():
            if (other["association_id"] == sa["association_id"]
                    and other["id"] != sa["id"]
                    and other["approval_status"] == "BALLOTING"):
                raise ApiError("ERR_BALLOT_ALREADY_OPEN")

        sa["approval_status"] = "BALLOTING"
        sa["ballot_opened_at"] = clock.now()
        sa["requires_supermajority_disclosure"] = bool(sa.get("funding_claim_id"))
        sa["eligible_weight_bp"] = assessment.eligible_weight(sa["association_id"])
        db.touch(sa)
        return response.ok(serialize.view(sa))

    @app.post("/special-assessments/<special_assessment_id>/close-ballot")
    def close_ballot(special_assessment_id):
        authenticate(("BoardDirector",))
        found = V.resolve_path(special_assessment_id=special_assessment_id)
        sa = found["special_assessment_id"]
        assoc = db.get("associations", sa["association_id"])
        V.body_of()
        # Rung 12.
        if sa["approval_status"] != "BALLOTING":
            raise ApiError("ERR_INVALID_BALLOT_STATE")

        surviving = assessment.rederive_counted(sa)
        eligible = assessment.eligible_weight(sa["association_id"])
        # Rung 40 -- an all-ineligible roster is rejected, not failed.
        if eligible == 0:
            raise ApiError("ERR_NO_ELIGIBLE_VOTERS")
        yes_weight = sum(v["weight_bp"] for v in surviving
                         if v["counted"] and v["choice"] == "YES")
        yes_share = money.floor_div(yes_weight * 10000, eligible)
        approved = yes_share >= assoc["special_assessment_approval_bp"]

        sa["eligible_weight_bp"] = eligible
        sa["yes_weight_bp"] = yes_weight
        sa["ballot_closed_at"] = clock.now()
        if approved:
            sa["approval_status"] = "APPROVED"
            assoc["reserve_designated_cents"] += sa["total_amount_cents"]
            db.touch(assoc)
        else:
            sa["approval_status"] = "FAILED"
        db.touch(sa)
        return response.ok(serialize.view(sa))

    @app.post("/special-assessments/<special_assessment_id>/installments")
    def post_installment(special_assessment_id):
        authenticate(("BoardTreasurer",))
        found = V.resolve_path(special_assessment_id=special_assessment_id)
        sa = found["special_assessment_id"]
        body = V.body_of()
        due_on = V.require_dt(body, "due_on")
        effective_period = V.require_period(body, "effective_period")
        # Rung 12.
        if sa["approval_status"] != "APPROVED":
            raise ApiError("ERR_INVALID_BALLOT_STATE")
        # Rung 42.
        if sa["installments_posted"] >= sa["installment_count"]:
            raise ApiError("ERR_INSTALLMENTS_EXHAUSTED")

        units = alloc.participants(sa["association_id"])
        pool = alloc.sa_round_pool(sa, sa["installments_posted"])
        shares, _base, _drift = alloc.allocate(pool, units)
        for unit, share in zip(units, shares):
            ledger.post_entry(unit, "SPECIAL_ASSESSMENT_INSTALLMENT", share,
                              effective_period, due_on=due_on,
                              special_assessment_id=sa["id"])
        sa["installments_posted"] += 1
        for unit in units:
            ledger.recompute_unit(unit)
        assessment.refresh_money(sa)
        assessment.refresh_restricted_cash(sa["association_id"])
        db.touch(sa)
        return response.ok(serialize.view(sa))

    @app.post("/special-assessments/<special_assessment_id>/rescind")
    def rescind_special_assessment(special_assessment_id):
        authenticate(("BoardDirector",))
        found = V.resolve_path(special_assessment_id=special_assessment_id)
        sa = found["special_assessment_id"]
        assoc = db.get("associations", sa["association_id"])
        body = V.body_of()
        V.require_str(body, "reason", required=False, default=None)
        # Rung 12.
        if sa["approval_status"] != "APPROVED":
            raise ApiError("ERR_INVALID_BALLOT_STATE")
        # Rung 60 -- a live suit cannot be defunded.
        if sa.get("funding_claim_id"):
            claim = db.get("insurance_claims", sa["funding_claim_id"])
            if claim is not None and claim["litigation_status"] == "IN_LITIGATION":
                raise ApiError("ERR_LITIGATION_ACTIVE")

        sa["approval_status"] = "RESCINDED"
        assoc["reserve_designated_cents"] -= sa["total_amount_cents"]
        db.touch(assoc)

        affected = {}
        for e in db.sorted_rows(
                "ledger_entries",
                lambda x: x["entry_type"] == "SPECIAL_ASSESSMENT_INSTALLMENT"
                and x.get("special_assessment_id") == sa["id"]
                and x["status"] == "POSTED"):
            unit = db.get("units", e["unit_id"])
            if unit is None:
                continue
            ledger.reverse_entry(unit, e, memo="Special assessment rescinded")
            affected[unit["id"]] = unit
        for unit in affected.values():
            ledger.recompute_unit(unit)

        assessment.refresh_money(sa)
        sa["funding_status"] = ("REFUNDING" if sa["collected_cents"] > 0
                               else "REFUNDED")
        assessment.refresh_restricted_cash(sa["association_id"])
        db.touch(sa)
        return response.ok(serialize.view(sa))

    @app.post("/special-assessments/<special_assessment_id>/refund")
    def refund_special_assessment(special_assessment_id):
        authenticate(("BoardTreasurer",))
        found = V.resolve_path(special_assessment_id=special_assessment_id)
        sa = found["special_assessment_id"]
        assoc = db.get("associations", sa["association_id"])
        body = V.body_of()
        fk = V.resolve_body_fk(body, "unit_id")
        unit = fk["unit_id"]
        if unit is None:
            V.fail("Field 'unit_id' is required.")
        amount = V.require_int(body, "amount_cents", minimum=1)
        effective_period = V.require_period(body, "effective_period")
        memo = V.require_str(body, "memo", required=False, default=None)
        V.scope_match(sa["association_id"], unit)
        # Rung 12.
        if sa["funding_status"] != "REFUNDING":
            raise ApiError("ERR_INVALID_BALLOT_STATE")
        # Rung 47.
        assessment.refresh_money(sa)
        if amount > sa["collected_cents"] - sa["refunded_cents"]:
            raise ApiError("ERR_REFUND_EXCEEDS_COLLECTED")

        ledger.post_entry(unit, "CREDIT_REFUND", -amount, effective_period,
                          due_on=None, memo=memo, special_assessment_id=sa["id"])
        ledger.recompute_unit(unit)
        assessment.refresh_money(sa)
        if sa["refunded_cents"] >= sa["collected_cents"]:
            sa["funding_status"] = "REFUNDED"
            db.touch(assoc)
        assessment.refresh_restricted_cash(sa["association_id"])
        db.touch(sa)
        return response.ok(serialize.view(sa))

    # -------------------------------------------------------- the vote register

    @app.post("/votes")
    def cast_vote():
        authenticate(("BoardDirector", "BoardTreasurer", "UnitOwner"))
        body = V.body_of()
        # Rung 5 -- body foreign keys, left to right.
        association_id = body.get("association_id")
        assoc = db.get("associations", association_id) if association_id else None
        if association_id is not None and assoc is None:
            raise ApiError("ERR_REFERENCED_ENTITY_NOT_FOUND")
        subject_type = body.get("subject_type")
        subject = None
        if isinstance(subject_type, str) and subject_type in SUBJECT_TYPES:
            subject_id = body.get("subject_id")
            if subject_id is not None:
                subject = db.get(SUBJECT_COLLECTIONS[subject_type], subject_id)
                if subject is None:
                    raise ApiError("ERR_REFERENCED_ENTITY_NOT_FOUND")
        fk = V.resolve_body_fk(body, "voter_owner_id", "meeting_id", "unit_id")
        voter = fk["voter_owner_id"]
        meeting = fk["meeting_id"]
        unit = fk["unit_id"]

        # Rung 6.
        if assoc is None:
            V.fail("Field 'association_id' is required.")
        V.require_enum(body, "subject_type", SUBJECT_TYPES)
        V.require_id(body, "subject_id")
        choice = V.require_enum(body, "choice", CHOICES)
        if voter is None:
            V.fail("Field 'voter_owner_id' is required.")
        if (meeting is None) == (unit is None):
            V.fail("Exactly one of 'meeting_id' or 'unit_id' must be supplied.")

        # Rung 8.
        V.scope_match(assoc["id"], subject, voter, meeting, unit)
        # Rung 7.
        if unit is not None:
            V.owner_scope(unit)

        row = db.base_fields(versioned=False)
        row.update({
            "association_id": assoc["id"],
            "subject_type": subject_type,
            "subject_id": subject["id"],
            "meeting_id": meeting["id"] if meeting else None,
            "unit_id": unit["id"] if unit else None,
            "voter_owner_id": voter["id"],
            "voter_kind": "BOARD_DIRECTOR" if meeting is not None else "UNIT_OWNER",
            "choice": choice,
            "weight_bp": unit["interest_bp"] if unit is not None else 0,
            "counted": bool(unit["voting_eligible"]) if unit is not None else True,
            "cast_at": clock.now(),
        })
        db.insert("votes", row)

        if subject_type == "VENDOR_CONTRACT":
            recompute_contract_yes_count(subject)
            db.touch(subject)
        return response.created(serialize.view(row))

    @app.get("/votes")
    def list_votes():
        authenticate(("CommunityManager", "BoardDirector", "BoardTreasurer",
                      "AssociationAttorney"))
        limit, offset = V.pagination()
        args = request.args
        subject_type = args.get("subject_type")
        if subject_type is not None and subject_type not in SUBJECT_TYPES:
            V.fail("Query parameter 'subject_type' is not recognized.")

        def keep(v):
            for name in ("association_id", "meeting_id", "unit_id", "voter_owner_id",
                         "subject_id"):
                want = args.get(name)
                if want and v.get(name) != want:
                    return False
            if subject_type and v["subject_type"] != subject_type:
                return False
            return True

        rows = db.sorted_rows("votes", keep)
        page, total = V.paginate(rows, limit, offset)
        return response.listing(serialize.views(page), limit, offset, total)
