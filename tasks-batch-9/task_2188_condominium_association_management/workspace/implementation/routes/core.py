"""Associations, owners, units and the reserve adequacy report."""
from flask import request

import clock
import db
import money
import response
import serialize
import validation as V
from auth import authenticate
from errors import ApiError
from services import ledger

TUNABLE_DEFAULTS = {
    "master_policy_deductible_cents": 2500000,
    "association_deductible_cap_cents": 1000000,
    "late_fee_grace_days": 10,
    "late_fee_percent_bp": 1000,
    "late_fee_min_cents": 2500,
    "late_fee_cap_cents": 10000,
    "lien_threshold_cents": 180000,
    "budget_veto_bp": 5000,
    "special_assessment_approval_bp": 6667,
    "board_quorum_seats": 3,
    "hearing_docket_capacity": 6,
    "element_window_buffer_hours": 24,
    "reserve_adequacy_threshold_bp": 7000,
    "reserve_contribution_min_bp": 1000,
    "fine_tier_1_cents": 5000,
    "fine_tier_2_cents": 10000,
    "fine_tier_3_daily_cents": 25000,
    "fine_cap_cents": 250000,
    "repeat_lookback_days": 365,
    "cure_period_days": 14,
    "appeal_window_days": 30,
    "budget_notice_days": 30,
    "certificate_validity_days": 30,
    "resale_cert_fee_cents": 35000,
}

# PRD 2.10: the revision endpoint accepts exactly these twenty-one fields.
PATCHABLE = (
    "master_policy_deductible_cents",
    "association_deductible_cap_cents",
    "late_fee_grace_days",
    "late_fee_percent_bp",
    "late_fee_min_cents",
    "late_fee_cap_cents",
    "lien_threshold_cents",
    "budget_veto_bp",
    "special_assessment_approval_bp",
    "board_quorum_seats",
    "hearing_docket_capacity",
    "element_window_buffer_hours",
    "reserve_adequacy_threshold_bp",
    "reserve_contribution_min_bp",
    "fine_cap_cents",
    "cure_period_days",
    "appeal_window_days",
    "budget_notice_days",
    "resale_cert_fee_cents",
    "operating_cash_cents",
    "reserve_balance_cents",
)

BOARD_ROLES = ("NONE", "DIRECTOR", "PRESIDENT", "TREASURER")

HORIZON_YEARS = 30


def recompute_total_interest(assoc):
    assoc["total_interest_bp"] = sum(
        u["interest_bp"] for u in db.store["units"].values()
        if u["association_id"] == assoc["id"])


def register(app):

    # ------------------------------------------------------------ associations

    @app.post("/associations")
    def create_association():
        authenticate(("CommunityManager",))
        body = V.body_of()
        legal_name = V.require_str(body, "legal_name", min_len=1, max_len=200)
        fiscal_year_start_month = V.require_int(
            body, "fiscal_year_start_month", minimum=1, maximum=12, required=False,
            default=1)
        row = db.base_fields()
        row.update({
            "legal_name": legal_name,
            "fiscal_year_start_month": fiscal_year_start_month,
            "total_interest_bp": 0,
            "operating_cash_cents": 0,
            "reserve_balance_cents": 0,
            "reserve_designated_cents": 0,
            "restricted_sa_cash_cents": 0,
        })
        for name, default in TUNABLE_DEFAULTS.items():
            row[name] = V.require_int(body, name, minimum=0, required=False,
                                      default=default)
        db.insert("associations", row)
        return response.created(serialize.view(row))

    @app.get("/associations/<association_id>")
    def read_association(association_id):
        authenticate(("CommunityManager", "BoardDirector", "BoardTreasurer",
                      "AssociationAttorney"))
        found = V.resolve_path(association_id=association_id)
        return response.ok(serialize.view(found["association_id"]))

    @app.patch("/associations/<association_id>")
    def patch_association(association_id):
        authenticate(("CommunityManager", "BoardTreasurer"))
        found = V.resolve_path(association_id=association_id)
        assoc = found["association_id"]
        body = V.body_of()
        for key in body:
            if key not in PATCHABLE:
                V.fail("Field '%s' may not be revised." % key)
        updates = {}
        for name in PATCHABLE:
            if name in body:
                updates[name] = V.require_int(body, name, minimum=0)
        assoc.update(updates)
        db.touch(assoc)
        return response.ok(serialize.view(assoc))

    @app.get("/associations/<association_id>/reserve-adequacy")
    def reserve_adequacy(association_id):
        authenticate(("CommunityManager", "BoardDirector", "BoardTreasurer",
                      "TitleAgent"))
        found = V.resolve_path(association_id=association_id)
        assoc = found["association_id"]
        method = request.args.get("method") or "STRAIGHT_LINE"
        if method not in ("STRAIGHT_LINE", "COMPONENT"):
            V.fail("Query parameter 'method' must be STRAIGHT_LINE or COMPONENT.")
        components = [c for c in db.store["common_elements"].values()
                      if c["association_id"] == association_id
                      and c["status"] != "DECOMMISSIONED"]
        fully_funded = 0
        for c in components:
            if method == "COMPONENT":
                remaining = max(c["useful_life_years"] - c["effective_age_years"], 0)
                if remaining > HORIZON_YEARS:
                    ffb = 0
                else:
                    ffb = money.round_half_up(
                        c["replacement_cost_cents"] * (HORIZON_YEARS - remaining),
                        HORIZON_YEARS)
            else:
                aged = min(c["effective_age_years"], c["useful_life_years"])
                ffb = money.round_half_up(
                    c["replacement_cost_cents"] * aged, c["useful_life_years"])
            fully_funded += ffb
        spendable = assoc["reserve_balance_cents"] - assoc["reserve_designated_cents"]
        if fully_funded == 0:
            percent = 10000
        else:
            percent = money.floor_div(spendable * 10000, fully_funded)
        posture = ("ADEQUATE" if percent >= assoc["reserve_adequacy_threshold_bp"]
                   else "DEFICIENT")
        return response.ok({
            "association_id": association_id,
            "method": method,
            "fully_funded_cents": fully_funded,
            "spendable_cents": spendable,
            "percent_funded_bp": percent,
            "posture": posture,
        })

    # ------------------------------------------------------------------ owners

    @app.post("/associations/<association_id>/owners")
    def create_owner(association_id):
        authenticate(("CommunityManager",))
        found = V.resolve_path(association_id=association_id)
        body = V.body_of()
        full_name = V.require_str(body, "full_name", min_len=1)
        email = V.require_str(body, "email", min_len=1)
        board_role = V.require_enum(body, "board_role", BOARD_ROLES, required=False,
                                    default="NONE")
        is_seated = V.require_bool(body, "is_seated", default=False)
        row = db.base_fields()
        row.update({
            "association_id": association_id,
            "full_name": full_name,
            "email": email,
            "board_role": board_role,
            "is_seated": bool(is_seated),
            "owned_unit_count": 0,
        })
        db.insert("owners", row)
        return response.created(serialize.view(row))

    @app.get("/owners")
    def list_owners():
        authenticate(("CommunityManager", "BoardDirector", "BoardTreasurer",
                      "AssociationAttorney"))
        limit, offset = V.pagination()
        association_id = request.args.get("association_id")
        board_role = request.args.get("board_role")
        if board_role is not None and board_role not in BOARD_ROLES:
            V.fail("Query parameter 'board_role' is not a recognized board role.")

        def keep(r):
            if association_id and r["association_id"] != association_id:
                return False
            if board_role and r["board_role"] != board_role:
                return False
            return True

        rows = db.sorted_rows("owners", keep)
        page, total = V.paginate(rows, limit, offset)
        return response.listing(serialize.views(page), limit, offset, total)

    # ------------------------------------------------------------------- units

    @app.post("/associations/<association_id>/units")
    def create_unit(association_id):
        authenticate(("CommunityManager",))
        found = V.resolve_path(association_id=association_id)
        assoc = found["association_id"]
        body = V.body_of()
        fk = V.resolve_body_fk(body, "current_owner_id")
        owner = fk["current_owner_id"]
        if owner is None:
            V.fail("Field 'current_owner_id' is required.")
        unit_label = V.require_str(body, "unit_label", min_len=1)
        interest_bp = V.require_int(body, "interest_bp", minimum=1, maximum=10000)
        heated_sqft = V.require_int(body, "heated_sqft", minimum=1)
        V.scope_match(association_id, owner)
        # Rung 36 -- unit_label unique within the association.
        for u in db.store["units"].values():
            if u["association_id"] == association_id and u["unit_label"] == unit_label:
                raise ApiError("ERR_UNIT_LABEL_DUPLICATE")

        row = db.base_fields()
        row.update({
            "association_id": association_id,
            "current_owner_id": owner["id"],
            "unit_label": unit_label,
            "interest_bp": interest_bp,
            "heated_sqft": heated_sqft,
            "monthly_assessment_cents": 0,
            "balance_due_cents": 0,
            "credit_balance_cents": 0,
            "oldest_unpaid_age_days": 0,
            "delinquency_stage": "CURRENT",
            "voting_eligible": True,
            "lien_recorded_at": None,
            "transfer_blocked": True,
        })
        db.insert("units", row)
        recompute_total_interest(assoc)
        db.touch(assoc)
        owner["owned_unit_count"] += 1
        db.touch(owner)
        return response.created(serialize.view(row))

    @app.get("/units")
    def list_units():
        authenticate(("CommunityManager", "BoardDirector", "BoardTreasurer",
                      "TitleAgent", "AssociationAttorney"))
        limit, offset = V.pagination()
        association_id = request.args.get("association_id")
        current_owner_id = request.args.get("current_owner_id")
        stage = request.args.get("delinquency_stage")
        if stage is not None and stage not in ledger.STAGES:
            V.fail("Query parameter 'delinquency_stage' is not a recognized stage.")

        def keep(r):
            if association_id and r["association_id"] != association_id:
                return False
            if current_owner_id and r["current_owner_id"] != current_owner_id:
                return False
            if stage and r["delinquency_stage"] != stage:
                return False
            return True

        rows = db.sorted_rows("units", keep)
        page, total = V.paginate(rows, limit, offset)
        return response.listing(serialize.views(page), limit, offset, total)

    @app.get("/units/<unit_id>")
    def read_unit(unit_id):
        authenticate(("CommunityManager", "BoardDirector", "BoardTreasurer",
                      "UnitOwner", "TitleAgent"))
        found = V.resolve_path(unit_id=unit_id)
        return response.ok(serialize.view(found["unit_id"]))

    # ------------------------------------------------------- the logical clock

    @app.post("/_clock/set_current_utc")
    def set_clock():
        authenticate(("CommunityManager",))
        body = V.body_of()
        current_utc = V.require_dt(body, "current_utc")
        clock.set_now(current_utc)
        return response.ok({})
