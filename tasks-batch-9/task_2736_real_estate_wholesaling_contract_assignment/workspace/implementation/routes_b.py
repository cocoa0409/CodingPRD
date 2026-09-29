"""Deal analyses, purchase contracts, disclosure acknowledgements and escrow."""
from datetime import timedelta

import calc
import services as svc
from common import (
    ALL_ROLES,
    authenticate,
    base_record,
    fail,
    get_body,
    list_response,
    now,
    opt_bool,
    req_bool,
    req_dt,
    req_enum,
    req_int,
    req_number,
    req_str,
    respond_object,
    touch,
)

VALUATION_VARIANTS = ("CONSERVATIVE", "AGGRESSIVE")
STRUCTURE_ELECTIONS = ("UNDECIDED", "ASSIGNMENT_ELECTED", "DOUBLE_CLOSE_ELECTED")


def _validate_comparables(body):
    value = body.get("comparables")
    if value is None or not isinstance(value, list):
        fail("ERR_INVALID_REQUEST", "comparables must be an array.")
    if len(value) > 20:
        fail("ERR_INVALID_REQUEST", "comparables holds at most 20 elements.")
    out = []
    for element in value:
        if not isinstance(element, dict):
            fail("ERR_INVALID_REQUEST", "each comparable must be an object.")
        comp = {
            "sale_price_cents": req_int(element, "sale_price_cents", minimum=1),
            "distance_miles": req_number(
                element.get("distance_miles"), "distance_miles", minimum=0
            ),
            "closed_days_ago": req_int(element, "closed_days_ago", minimum=0),
            "gla_sqft": req_int(element, "gla_sqft", minimum=1),
            "adjustment_cents": req_int(element, "adjustment_cents"),
        }
        if element.get("distance_miles") is None:
            fail("ERR_INVALID_REQUEST", "distance_miles is required.")
        out.append(comp)
    return out


def _validate_repair_items(body):
    value = body.get("repair_scope_items")
    if value is None or not isinstance(value, list):
        fail("ERR_INVALID_REQUEST", "repair_scope_items must be an array.")
    if len(value) > 40:
        fail("ERR_INVALID_REQUEST", "repair_scope_items holds at most 40 elements.")
    out = []
    for element in value:
        if not isinstance(element, dict):
            fail("ERR_INVALID_REQUEST", "each repair scope item must be an object.")
        item = {
            "code": req_str(element, "code"),
            "low_cents": req_int(element, "low_cents", minimum=0),
            "high_cents": req_int(element, "high_cents", minimum=0),
        }
        if item["high_cents"] < item["low_cents"]:
            fail("ERR_INVALID_REQUEST", "high_cents may not be below low_cents.")
        out.append(item)
    return out


def register(app):
    # -- DealAnalysis -------------------------------------------------------
    @app.post("/deal-analyses")
    def create_analysis():
        _role, user_id = authenticate(["Wholesaler"])
        body = get_body()
        lead_id = req_str(body, "seller_lead_id")
        subject_gla = req_int(body, "subject_gla_sqft", minimum=1)
        comparables = _validate_comparables(body)
        repair_items = _validate_repair_items(body)
        expected_version = req_int(body, "expected_seller_lead_version")

        lead = svc.load("seller_leads", lead_id)
        svc.guard_owner(lead["wholesaler_id"] == user_id)
        if expected_version != lead["version"]:
            fail(
                "ERR_STALE_LEAD_VERSION",
                "The lead has moved on since it was read.",
            )

        priors = [
            a
            for a in svc.all_of("deal_analyses")
            if a["seller_lead_id"] == lead["id"] and a["status"] != "SUPERSEDED"
        ]
        for prior in priors:
            if prior["status"] != "FINALIZED":
                continue
            for contract in svc.all_of("purchase_contracts"):
                if contract["deal_analysis_id"] != prior["id"]:
                    continue
                if contract["contract_status"] not in ("CLOSED", "CANCELLED"):
                    fail(
                        "ERR_INVALID_STATE",
                        "A live contract cites the analysis being superseded.",
                    )
        for prior in priors:
            prior["status"] = "SUPERSEDED"
            touch(prior)

        rec = base_record()
        rec.update(
            {
                "seller_lead_id": lead["id"],
                "subject_gla_sqft": subject_gla,
                "comparables": comparables,
                "repair_scope_items": repair_items,
                "valuation_variant": None,
                "qualifying_comp_count": calc.count_qualifying_comps(
                    comparables, subject_gla
                ),
                "arv_cents": None,
                "repair_estimate_cents": None,
                "max_allowable_offer_cents": None,
                "status": "DRAFT",
                "finalized_at": None,
            }
        )
        svc.store("deal_analyses", rec)
        return respond_object(rec, 201)

    @app.get("/deal-analyses/<deal_analysis_id>")
    def read_analysis(deal_analysis_id):
        authenticate(ALL_ROLES, require_user_id=False)
        return respond_object(svc.load("deal_analyses", deal_analysis_id))

    @app.get("/deal-analyses")
    def list_analyses():
        authenticate(ALL_ROLES, require_user_id=False)
        return list_response(
            svc.all_of("deal_analyses"),
            [("seller_lead_id", "seller_lead_id"), ("status", "status")],
        )

    @app.post("/deal-analyses/<deal_analysis_id>/finalize")
    def finalize_analysis(deal_analysis_id):
        _role, user_id = authenticate(["Wholesaler"])
        body = get_body()
        variant = req_enum(body, "valuation_variant", VALUATION_VARIANTS)
        analysis = svc.load("deal_analyses", deal_analysis_id)
        lead = svc.collection("seller_leads").get(analysis["seller_lead_id"])
        svc.guard_owner(lead is not None and lead["wholesaler_id"] == user_id)
        if analysis["status"] != "DRAFT":
            fail("ERR_INVALID_STATE", "Only a DRAFT analysis may be finalized.")
        qualifying = calc.count_qualifying_comps(
            analysis["comparables"], analysis["subject_gla_sqft"]
        )
        analysis["qualifying_comp_count"] = qualifying
        if qualifying < calc.MIN_QUALIFYING_COMPS:
            fail(
                "ERR_INSUFFICIENT_QUALIFYING_COMPS",
                "At least three qualifying comparables are required.",
            )
        arv, repairs, mao = calc.arv_and_mao(
            analysis["comparables"],
            analysis["repair_scope_items"],
            analysis["subject_gla_sqft"],
            variant,
        )
        analysis["valuation_variant"] = variant
        analysis["arv_cents"] = arv
        analysis["repair_estimate_cents"] = repairs
        analysis["max_allowable_offer_cents"] = mao
        analysis["finalized_at"] = now()
        analysis["status"] = "FINALIZED"
        touch(analysis)
        return respond_object(analysis)

    # -- PurchaseContract ---------------------------------------------------
    @app.post("/purchase-contracts")
    def create_contract():
        _role, user_id = authenticate(["Wholesaler"])
        body = get_body()
        lead_id = req_str(body, "seller_lead_id")
        analysis_id = req_str(body, "deal_analysis_id")
        purchase_price = req_int(body, "purchase_price_cents", minimum=1)
        earnest_money = req_int(body, "earnest_money_cents", minimum=1)
        inspection_days = req_int(body, "inspection_period_days", minimum=1, maximum=30)
        option_start = req_dt(body, "option_start_at")
        closing_start = req_dt(body, "closing_window_start_at")
        closing_end = req_dt(body, "closing_window_end_at")
        rights = opt_bool(body, "assignment_rights_granted", default=True)
        if closing_start <= option_start:
            fail(
                "ERR_INVALID_REQUEST",
                "closing_window_start_at must be strictly after option_start_at.",
            )
        if closing_end <= closing_start:
            fail(
                "ERR_INVALID_REQUEST",
                "closing_window_end_at must be strictly after closing_window_start_at.",
            )

        lead = svc.load("seller_leads", lead_id)
        analysis = svc.load("deal_analyses", analysis_id)
        svc.guard_owner(lead["wholesaler_id"] == user_id)
        if lead["status"] in ("PROSPECT", "CLOSED"):
            fail("ERR_LEAD_NOT_SCREENED", "The lead has not been screened.")
        if (
            analysis["status"] != "FINALIZED"
            or analysis["seller_lead_id"] != lead["id"]
        ):
            fail(
                "ERR_DEAL_ANALYSIS_NOT_FINALIZED",
                "The analysis is not finalized for this lead.",
            )
        wholesaler = svc.wholesaler_of_lead(lead)
        svc.guard_compliance_hold(wholesaler)
        if lead.get("protection_tier") in ("ELEVATED", "PROTECTED"):
            if purchase_price < calc.equity_floor_cents(lead):
                fail(
                    "ERR_EQUITY_SKIMMING_PROHIBITED",
                    "The price sits below the statutory equity floor.",
                )
        if svc.occupancy_conflict(lead["id"], option_start, closing_end):
            fail(
                "ERR_PROPERTY_OCCUPANCY_CONFLICT",
                "A live contract already occupies this property interval.",
            )
        if purchase_price > analysis["max_allowable_offer_cents"]:
            fail(
                "ERR_MAO_EXCEEDED",
                "The price exceeds the analysis's maximum allowable offer.",
            )

        rec = base_record()
        rec.update(
            {
                "seller_lead_id": lead["id"],
                "deal_analysis_id": analysis["id"],
                "purchase_price_cents": purchase_price,
                "earnest_money_cents": earnest_money,
                "inspection_period_days": inspection_days,
                "assignment_rights_granted": rights,
                "option_start_at": option_start,
                "closing_window_start_at": closing_start,
                "closing_window_end_at": closing_end,
                "contract_status": "DRAFT",
                "assignment_status": "NOT_MARKETED",
                "structure_election": "UNDECIDED",
                "signed_at": None,
                "inspection_deadline_at": None,
                "assignment_deadline_at": closing_start
                - timedelta(hours=calc.ASSIGNMENT_CUTOFF_HOURS),
                "funding_base_cents": None,
                "transactional_lender_fee_cents": None,
                "total_funding_required_cents": None,
                "double_close_spread_cents": None,
                "cancellation_reason": None,
                "cancelled_at": None,
            }
        )
        svc.store("purchase_contracts", rec)
        svc.set_fields(lead, {"status": "UNDER_CONTRACT"})
        return respond_object(rec, 201)

    @app.get("/purchase-contracts/<purchase_contract_id>")
    def read_contract(purchase_contract_id):
        authenticate(ALL_ROLES, require_user_id=False)
        return respond_object(svc.load("purchase_contracts", purchase_contract_id))

    @app.get("/purchase-contracts")
    def list_contracts():
        authenticate(ALL_ROLES, require_user_id=False)
        return list_response(
            svc.all_of("purchase_contracts"),
            [
                ("seller_lead_id", "seller_lead_id"),
                ("deal_analysis_id", "deal_analysis_id"),
                ("contract_status", "contract_status"),
                ("assignment_status", "assignment_status"),
                ("structure_election", "structure_election"),
            ],
        )

    @app.post("/purchase-contracts/<purchase_contract_id>/sign")
    def sign_contract(purchase_contract_id):
        _role, user_id = authenticate(["Seller"])
        contract = svc.load("purchase_contracts", purchase_contract_id)
        svc.guard_owner(contract["seller_lead_id"] == user_id)
        svc.guard_contract_terminal(contract)
        if contract["contract_status"] != "DRAFT":
            fail("ERR_INVALID_STATE", "Only a DRAFT contract may be signed.")
        wholesaler = svc.wholesaler_of_contract(contract)
        template = wholesaler["disclosure_template_version"] if wholesaler else None
        acks = [
            a
            for a in svc.acknowledgements_of_contract(contract)
            if a["disclosure_template_version"] == template
        ]
        if not any(a["acknowledged_intent_to_assign"] for a in acks):
            fail(
                "ERR_DISCLOSURE_ACKNOWLEDGEMENT_MISSING",
                "No current acknowledgement of the intent to assign is on file.",
            )
        if wholesaler is not None and wholesaler["licensure_status"] == "UNLICENSED":
            if not any(a["acknowledged_unlicensed_status"] for a in acks):
                fail(
                    "ERR_DISCLOSURE_ACKNOWLEDGEMENT_MISSING",
                    "No current acknowledgement of the unlicensed status is on file.",
                )

        signed_at = now()
        contract["contract_status"] = "SIGNED"
        contract["signed_at"] = signed_at
        contract["inspection_deadline_at"] = signed_at + timedelta(
            hours=24 * int(contract["inspection_period_days"])
        )
        touch(contract)

        deposit = base_record()
        amount = int(contract["earnest_money_cents"])
        deposit.update(
            {
                "purchase_contract_id": contract["id"],
                "amount_cents": amount,
                "status": "HELD",
                "held_cents": amount,
                "refunded_to_wholesaler_cents": 0,
                "forfeited_to_seller_cents": 0,
                "applied_at_closing_cents": 0,
                "disposition_event_count": 0,
            }
        )
        svc.store("earnest_money_deposits", deposit)
        return respond_object(contract)

    @app.post("/purchase-contracts/<purchase_contract_id>/elect-structure")
    def elect_structure(purchase_contract_id):
        _role, user_id = authenticate(["Wholesaler"])
        body = get_body()
        target = req_enum(body, "structure_election", STRUCTURE_ELECTIONS)
        contract = svc.load("purchase_contracts", purchase_contract_id)
        svc.guard_owner(svc.wholesaler_id_of_contract(contract) == user_id)
        svc.guard_contract_terminal(contract)
        current = contract["structure_election"]
        if target == "UNDECIDED" or target == current:
            fail("ERR_INVALID_STATE", "That structure election has no transition.")
        if target == "ASSIGNMENT_ELECTED":
            if not contract["assignment_rights_granted"]:
                fail(
                    "ERR_INVALID_STATE",
                    "The seller never granted assignment rights.",
                )
            if contract["assignment_status"] == "ASSIGNED":
                fail(
                    "ERR_INVALID_STATE",
                    "The contract has already been assigned.",
                )
            if current == "DOUBLE_CLOSE_ELECTED":
                for order in svc.title_orders_of_contract(contract):
                    if order["structure"] == "DOUBLE_CLOSE" and order["status"] in (
                        "OPENED",
                        "CLEARED_TO_FUND",
                    ):
                        fail(
                            "ERR_INVALID_STATE",
                            "A reserved double-close funding window is still live.",
                        )
            contract["structure_election"] = "ASSIGNMENT_ELECTED"
            svc.clear_funding_schedule(contract)
        else:
            if contract["assignment_status"] == "ASSIGNED":
                fail(
                    "ERR_INVALID_STATE",
                    "The contract has already been assigned.",
                )
            contract["structure_election"] = "DOUBLE_CLOSE_ELECTED"
            svc.apply_funding_schedule(contract)
        touch(contract)
        return respond_object(contract)

    @app.post("/purchase-contracts/<purchase_contract_id>/cancel")
    def cancel_contract(purchase_contract_id):
        role, user_id = authenticate(["Wholesaler", "Seller", "ComplianceOfficer"])
        body = get_body()
        reason = req_str(body, "reason")
        contract = svc.load("purchase_contracts", purchase_contract_id)
        if role == "Wholesaler":
            svc.guard_owner(svc.wholesaler_id_of_contract(contract) == user_id)
        elif role == "Seller":
            svc.guard_owner(contract["seller_lead_id"] == user_id)
        if contract["contract_status"] in ("CLOSED", "CANCELLED"):
            fail("ERR_INVALID_STATE", "The contract is already terminal.")
        if role == "Wholesaler":
            deadline = contract.get("inspection_deadline_at")
            if deadline is not None and now() >= deadline:
                fail(
                    "ERR_INSPECTION_PERIOD_EXPIRED",
                    "The inspection period has expired.",
                )
        svc.cancellation_cascade(contract, reason)
        return respond_object(contract)

    # -- DisclosureAcknowledgement -----------------------------------------
    @app.post("/disclosure-acknowledgements")
    def create_acknowledgement():
        _role, user_id = authenticate(["Seller"])
        body = get_body()
        contract_id = req_str(body, "purchase_contract_id")
        template = req_str(body, "disclosure_template_version", max_len=32)
        intent = req_bool(body, "acknowledged_intent_to_assign")
        unlicensed = req_bool(body, "acknowledged_unlicensed_status")
        signature_ref = req_str(body, "signature_ref", max_len=120)
        contract = svc.load("purchase_contracts", contract_id)
        svc.guard_owner(contract["seller_lead_id"] == user_id)
        svc.guard_contract_terminal(contract)
        rec = base_record(versioned=False)
        rec.update(
            {
                "purchase_contract_id": contract["id"],
                "disclosure_template_version": template,
                "acknowledged_intent_to_assign": intent,
                "acknowledged_unlicensed_status": unlicensed,
                "signature_ref": signature_ref,
                "acknowledged_at": now(),
            }
        )
        svc.store("disclosure_acknowledgements", rec)
        return respond_object(rec, 201)

    @app.get("/disclosure-acknowledgements/<disclosure_acknowledgement_id>")
    def read_acknowledgement(disclosure_acknowledgement_id):
        authenticate(ALL_ROLES, require_user_id=False)
        return respond_object(
            svc.load("disclosure_acknowledgements", disclosure_acknowledgement_id)
        )

    @app.get("/disclosure-acknowledgements")
    def list_acknowledgements():
        authenticate(ALL_ROLES, require_user_id=False)
        return list_response(
            svc.all_of("disclosure_acknowledgements"),
            [("purchase_contract_id", "purchase_contract_id")],
        )

    # -- EarnestMoneyDeposit ------------------------------------------------
    @app.get("/earnest-money-deposits/<earnest_money_deposit_id>")
    def read_deposit(earnest_money_deposit_id):
        authenticate(ALL_ROLES, require_user_id=False)
        return respond_object(
            svc.load("earnest_money_deposits", earnest_money_deposit_id)
        )

    @app.get("/earnest-money-deposits")
    def list_deposits():
        authenticate(ALL_ROLES, require_user_id=False)
        return list_response(
            svc.all_of("earnest_money_deposits"),
            [("purchase_contract_id", "purchase_contract_id"), ("status", "status")],
        )

    @app.post("/earnest-money-deposits/<earnest_money_deposit_id>/forfeit")
    def forfeit_deposit(earnest_money_deposit_id):
        authenticate(["TitleAgent"])
        body = get_body()
        req_str(body, "forfeiture_reason")
        deposit = svc.load("earnest_money_deposits", earnest_money_deposit_id)
        contract = svc.collection("purchase_contracts").get(
            deposit["purchase_contract_id"]
        )
        if contract is None or contract.get("signed_at") is None:
            fail("ERR_CONTRACT_NOT_SIGNED", "The governing contract was never signed.")
        if deposit["status"] != "HELD":
            fail("ERR_DEPOSIT_NOT_HELD", "The deposit has already left HELD.")
        deadline = contract.get("inspection_deadline_at")
        if deadline is not None and now() < deadline:
            fail(
                "ERR_INSPECTION_PERIOD_EXPIRED",
                "Forfeiture opens only once the inspection period has run.",
            )
        calc.apply_disposition(deposit, "FORFEIT")
        touch(deposit)
        return respond_object(deposit)
