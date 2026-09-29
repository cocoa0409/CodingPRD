"""Insurance claims: review, the four adjustment branches, the deductible
waterfall, appeals, litigation and settlement (PRD 3.7)."""
from flask import request

import clock
import db
import money
import response
import serialize
import validation as V
from auth import authenticate
from errors import ApiError
from services import assessment, certificate, ledger

LOSS_TYPES = ("WATER", "FIRE", "WIND", "CONSTRUCTION_DEFECT", "LIABILITY")
ADJUSTMENT_STATUSES = ("REPORTED", "UNDER_REVIEW", "ADJUSTED_ASSOCIATION",
                       "ADJUSTED_OWNER", "ADJUSTED_SPLIT", "DENIED", "SETTLED",
                       "APPEALED")
LITIGATION_STATUSES = ("NONE", "TENDERED", "IN_LITIGATION", "RESOLVED")
RESPONSIBILITIES = ("ASSOCIATION", "OWNER", "SPLIT", "DENY")
STAGES = ("TENDERED", "IN_LITIGATION", "RESOLVED")
TERMINAL_ORDER_STATUSES = ("INVOICED", "CANCELLED")


def deductible_waterfall(assoc, claim, units):
    """PRD 3.7: tier on gross_damage_cents only, one half-up rounding on the raw
    association slice, then a FLOOR-then-single-pass-topup residue split."""
    basis = claim["gross_damage_cents"]
    if basis < 5000000:
        share_bp = 10000
    elif basis < 25000000:
        share_bp = 6000
    else:
        share_bp = 3000
    raw = money.round_half_up(assoc["master_policy_deductible_cents"] * share_bp, 10000)
    absorbed = min(raw, assoc["association_deductible_cap_cents"])
    residue = assoc["master_policy_deductible_cents"] - absorbed
    ordered = sorted(units, key=lambda u: (-u["heated_sqft"], u["created_at"],
                                           u["_seq"]))
    allocs, _drift = money.floor_then_topup(
        residue, [(u["id"], u["heated_sqft"]) for u in ordered])
    rows = [{"unit_id": u["id"], "heated_sqft": u["heated_sqft"],
             "allocated_cents": a} for u, a in zip(ordered, allocs)]
    return absorbed, sum(allocs), rows, ordered


def element_orders_terminal(element_id):
    for w in db.store["work_orders"].values():
        if w["element_id"] == element_id and w["status"] not in TERMINAL_ORDER_STATUSES:
            return False
    return True


def register(app):

    @app.post("/insurance-claims")
    def report_claim():
        authenticate(("CommunityManager",))
        body = V.body_of()
        association_id = body.get("association_id")
        assoc = db.get("associations", association_id) if association_id else None
        if association_id is not None and assoc is None:
            raise ApiError("ERR_REFERENCED_ENTITY_NOT_FOUND")
        fk = V.resolve_body_fk(body, "unit_id", "element_id", "affected_unit_ids")
        unit = fk["unit_id"]
        element = fk["element_id"]
        affected = fk["affected_unit_ids"] or []
        if assoc is None:
            V.fail("Field 'association_id' is required.")
        loss_type = V.require_enum(body, "loss_type", LOSS_TYPES)
        loss_at = V.require_dt(body, "loss_at")
        gross = V.require_int(body, "gross_damage_cents", minimum=1)
        within = V.require_int(body, "within_unit_boundary_cents", minimum=0)
        V.scope_match(assoc["id"], unit, element, affected)
        # Rung 59.
        if unit is None and element is None:
            raise ApiError("ERR_CLAIM_SCOPE_INVALID")
        if within > gross:
            raise ApiError("ERR_CLAIM_SCOPE_INVALID")

        row = db.base_fields()
        row.update({
            "association_id": assoc["id"],
            "unit_id": unit["id"] if unit else None,
            "element_id": element["id"] if element else None,
            "loss_type": loss_type,
            "loss_at": loss_at,
            "gross_damage_cents": gross,
            "within_unit_boundary_cents": within,
            "common_element_damage_cents": 0,
            "affected_unit_ids": [u["id"] for u in affected],
            "adjustment_status": "REPORTED",
            "litigation_status": "NONE",
            "deductible_allocation": [],
            "association_absorbed_cents": 0,
            "owner_chargeback_cents": 0,
            "appeal_round": 0,
            "disclosure_required": False,
            "reported_at": clock.now(),
        })
        db.insert("insurance_claims", row)
        return response.created(serialize.view(row))

    @app.get("/insurance-claims")
    def list_claims():
        authenticate(("CommunityManager", "BoardDirector", "BoardTreasurer",
                      "InsuranceAdjuster", "AssociationAttorney", "TitleAgent"))
        limit, offset = V.pagination()
        args = request.args
        adjustment_status = args.get("adjustment_status")
        if adjustment_status is not None and adjustment_status not in ADJUSTMENT_STATUSES:
            V.fail("Query parameter 'adjustment_status' is not recognized.")
        litigation_status = args.get("litigation_status")
        if litigation_status is not None and litigation_status not in LITIGATION_STATUSES:
            V.fail("Query parameter 'litigation_status' is not recognized.")

        def keep(c):
            for name in ("association_id", "unit_id", "element_id"):
                want = args.get(name)
                if want and c.get(name) != want:
                    return False
            if adjustment_status and c["adjustment_status"] != adjustment_status:
                return False
            if litigation_status and c["litigation_status"] != litigation_status:
                return False
            return True

        rows = db.sorted_rows("insurance_claims", keep)
        page, total = V.paginate(rows, limit, offset)
        return response.listing(serialize.views(page), limit, offset, total)

    @app.post("/insurance-claims/<insurance_claim_id>/assign-adjuster")
    def assign_adjuster(insurance_claim_id):
        authenticate(("InsuranceAdjuster",))
        found = V.resolve_path(insurance_claim_id=insurance_claim_id)
        claim = found["insurance_claim_id"]
        V.body_of()
        # Rung 12.
        if claim["adjustment_status"] not in ("REPORTED", "APPEALED"):
            raise ApiError("ERR_INVALID_CLAIM_STATE")
        if claim["adjustment_status"] == "REPORTED":
            # Rung 59.
            if not claim.get("unit_id") and not claim.get("element_id"):
                raise ApiError("ERR_CLAIM_SCOPE_INVALID")
            claim["common_element_damage_cents"] = (
                claim["gross_damage_cents"] - claim["within_unit_boundary_cents"])
        # The re-review leg deliberately does NOT recompute the damage split.
        claim["adjustment_status"] = "UNDER_REVIEW"
        db.touch(claim)
        return response.ok(serialize.view(claim))

    @app.post("/insurance-claims/<insurance_claim_id>/adjust")
    def adjust_claim(insurance_claim_id):
        authenticate(("InsuranceAdjuster",))
        found = V.resolve_path(insurance_claim_id=insurance_claim_id)
        claim = found["insurance_claim_id"]
        assoc = db.get("associations", claim["association_id"])
        body = V.body_of()
        responsibility = V.require_enum(body, "responsibility", RESPONSIBILITIES)
        # Rung 12.
        if claim["adjustment_status"] != "UNDER_REVIEW":
            raise ApiError("ERR_INVALID_CLAIM_STATE")

        element = db.get("common_elements", claim.get("element_id"))

        if responsibility == "ASSOCIATION":
            # Rung 57.
            if claim["common_element_damage_cents"] <= 0:
                raise ApiError("ERR_RESPONSIBILITY_MISMATCH")
            absorbed = min(assoc["master_policy_deductible_cents"],
                           assoc["association_deductible_cap_cents"])
            claim["association_absorbed_cents"] = absorbed
            claim["owner_chargeback_cents"] = 0
            claim["deductible_allocation"] = []
            claim["adjustment_status"] = "ADJUSTED_ASSOCIATION"
            assoc["operating_cash_cents"] -= absorbed
            db.touch(assoc)
            if element is not None and element["status"] == "SERVICEABLE":
                element["status"] = "IMPAIRED"
                db.touch(element)

        elif responsibility == "OWNER":
            unit = db.get("units", claim.get("unit_id"))
            # Rung 57.
            if unit is None:
                raise ApiError("ERR_RESPONSIBILITY_MISMATCH")
            if claim["within_unit_boundary_cents"] != claim["gross_damage_cents"]:
                raise ApiError("ERR_RESPONSIBILITY_MISMATCH")
            chargeback = assoc["master_policy_deductible_cents"]
            claim["association_absorbed_cents"] = 0
            claim["owner_chargeback_cents"] = chargeback
            claim["deductible_allocation"] = [{
                "unit_id": unit["id"],
                "heated_sqft": unit["heated_sqft"],
                "allocated_cents": chargeback,
            }]
            claim["adjustment_status"] = "ADJUSTED_OWNER"
            ledger.post_entry(unit, "INSURANCE_DEDUCTIBLE_CHARGEBACK", chargeback,
                              _period(clock.now()),
                              due_on=clock.add_days(clock.now(), 30),
                              source_claim_id=claim["id"])
            ledger.recompute_unit(unit)

        elif responsibility == "SPLIT":
            # Rung 41 precedes rung 57.
            if not claim["affected_unit_ids"]:
                raise ApiError("ERR_NO_AFFECTED_UNITS")
            # Rung 57.
            if (claim["within_unit_boundary_cents"] <= 0
                    or claim["common_element_damage_cents"] <= 0):
                raise ApiError("ERR_RESPONSIBILITY_MISMATCH")
            units = [db.get("units", uid) for uid in claim["affected_unit_ids"]]
            units = [u for u in units if u is not None]
            absorbed, chargeback, rows, ordered = deductible_waterfall(
                assoc, claim, units)
            claim["association_absorbed_cents"] = absorbed
            claim["owner_chargeback_cents"] = chargeback
            claim["deductible_allocation"] = rows
            claim["adjustment_status"] = "ADJUSTED_SPLIT"
            period = _period(clock.now())
            due_on = clock.add_days(clock.now(), 30)
            for line in rows:
                unit = db.get("units", line["unit_id"])
                ledger.post_entry(unit, "INSURANCE_DEDUCTIBLE_CHARGEBACK",
                                  line["allocated_cents"], period, due_on=due_on,
                                  source_claim_id=claim["id"])
            for unit in ordered:
                ledger.recompute_unit(unit)
            assoc["operating_cash_cents"] -= absorbed
            db.touch(assoc)

        else:  # DENY
            claim["deductible_allocation"] = []
            claim["adjustment_status"] = "DENIED"

        db.touch(claim)
        return response.ok(serialize.view(claim))

    @app.post("/insurance-claims/<insurance_claim_id>/appeal")
    def appeal_claim(insurance_claim_id):
        authenticate(("CommunityManager", "UnitOwner"))
        found = V.resolve_path(insurance_claim_id=insurance_claim_id)
        claim = found["insurance_claim_id"]
        body = V.body_of()
        V.require_str(body, "reason", required=False, default=None)
        # Rung 12.
        if claim["adjustment_status"] != "DENIED":
            raise ApiError("ERR_INVALID_CLAIM_STATE")
        # Rung 58.
        if claim["appeal_round"] >= 2:
            raise ApiError("ERR_APPEAL_LIMIT_REACHED")
        claim["appeal_round"] += 1
        claim["adjustment_status"] = "APPEALED"
        db.touch(claim)
        return response.ok(serialize.view(claim))

    @app.post("/insurance-claims/<insurance_claim_id>/litigation-stage")
    def litigation_stage(insurance_claim_id):
        authenticate(("AssociationAttorney",))
        found = V.resolve_path(insurance_claim_id=insurance_claim_id)
        claim = found["insurance_claim_id"]
        body = V.body_of()
        stage = V.require_enum(body, "stage", STAGES)

        if stage == "TENDERED":
            # Rung 12.
            if claim["litigation_status"] != "NONE":
                raise ApiError("ERR_INVALID_CLAIM_STATE")
            if claim["loss_type"] != "CONSTRUCTION_DEFECT":
                raise ApiError("ERR_INVALID_CLAIM_STATE",
                               "Only a construction-defect loss may be tendered.")
            if claim["adjustment_status"] not in ("DENIED", "ADJUSTED_ASSOCIATION",
                                                  "ADJUSTED_SPLIT"):
                raise ApiError("ERR_INVALID_CLAIM_STATE")
            claim["litigation_status"] = "TENDERED"
            claim["disclosure_required"] = True
            affected = set(claim["affected_unit_ids"] or [])
            for cert in db.sorted_rows(
                    "resale_certificates",
                    lambda c: c["status"] == "ISSUED" and c["unit_id"] in affected):
                certificate.cascade_void(cert, db.get("units", cert["unit_id"]))
            for sa in db.store["special_assessments"].values():
                if sa["association_id"] == claim["association_id"]:
                    assessment.refresh_money(sa)
            assessment.refresh_restricted_cash(claim["association_id"])

        elif stage == "IN_LITIGATION":
            # Rung 12.
            if claim["litigation_status"] != "TENDERED":
                raise ApiError("ERR_INVALID_CLAIM_STATE")
            # Rung 21.
            funded = any(
                s["funding_claim_id"] == claim["id"]
                and s["approval_status"] == "APPROVED"
                for s in db.store["special_assessments"].values())
            if not funded:
                raise ApiError("ERR_LITIGATION_FUNDING_MISSING")
            claim["litigation_status"] = "IN_LITIGATION"
            claim["disclosure_required"] = True

        else:  # RESOLVED
            # Rung 12.
            if claim["litigation_status"] != "IN_LITIGATION":
                raise ApiError("ERR_INVALID_CLAIM_STATE")
            claim["litigation_status"] = "RESOLVED"
            claim["disclosure_required"] = False

        db.touch(claim)
        return response.ok(serialize.view(claim))

    @app.post("/insurance-claims/<insurance_claim_id>/settle")
    def settle_claim(insurance_claim_id):
        authenticate(("InsuranceAdjuster",))
        found = V.resolve_path(insurance_claim_id=insurance_claim_id)
        claim = found["insurance_claim_id"]
        V.body_of()
        # Rung 12.
        if claim["adjustment_status"] not in ("ADJUSTED_ASSOCIATION", "ADJUSTED_OWNER",
                                              "ADJUSTED_SPLIT"):
            raise ApiError("ERR_INVALID_CLAIM_STATE")
        owner_leg = claim["adjustment_status"] == "ADJUSTED_OWNER"
        # Rung 22 -- applies to all three legs.
        for w in db.store["work_orders"].values():
            if (w.get("claim_id") == claim["id"]
                    and w["status"] not in TERMINAL_ORDER_STATUSES):
                raise ApiError("ERR_CLAIM_WORK_OPEN")
        # Rung 60 -- the ADJUSTED_OWNER leg carries neither extra.
        if not owner_leg and claim["litigation_status"] == "IN_LITIGATION":
            raise ApiError("ERR_LITIGATION_ACTIVE")

        claim["adjustment_status"] = "SETTLED"
        if not owner_leg and claim.get("element_id"):
            element = db.get("common_elements", claim["element_id"])
            if element is not None and element_orders_terminal(element["id"]):
                element["status"] = "SERVICEABLE"
                db.touch(element)
        db.touch(claim)
        return response.ok(serialize.view(claim))


def _period(dt):
    return "%04d-%02d" % (dt.year, dt.month)
