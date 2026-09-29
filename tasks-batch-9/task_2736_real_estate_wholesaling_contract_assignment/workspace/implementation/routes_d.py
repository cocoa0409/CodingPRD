"""Assignment agreements, title orders, compliance reviews, disputes, clock."""
from datetime import timedelta

import calc
import services as svc
from common import (
    ALL_ROLES,
    authenticate,
    base_record,
    db,
    fail,
    get_body,
    iso_ms,
    list_response,
    now,
    opt_id,
    req_dt,
    req_enum,
    req_int,
    req_str,
    respond_object,
    respond_raw,
    touch,
)

STRUCTURES = ("ASSIGNMENT", "DOUBLE_CLOSE")
REVIEW_TYPES = ("LICENSURE_BOUNDARY", "MARKETING_COMPLIANCE", "EQUITY_SKIMMING")
FINDINGS = (
    "NO_VIOLATION",
    "UNLICENSED_BROKERAGE_ACTIVITY",
    "DISCLOSURE_FAILURE",
    "EQUITY_SKIMMING",
)
DECISIONS = ("CLEAR", "ADVERSE")
DISPUTE_BASES = (
    "EARNEST_MONEY_FORFEITURE",
    "UNDISCLOSED_ASSIGNMENT",
    "EQUITY_SKIMMING",
    "FAILURE_TO_CLOSE",
)
AWARDS = ("SELLER_KEEPS_EARNEST_MONEY", "REFUND_TO_WHOLESALER", "SPLIT_50_50")


def register(app):
    # -- AssignmentAgreement ------------------------------------------------
    @app.post("/assignment-agreements")
    def execute_agreement():
        _role, user_id = authenticate(["Wholesaler"])
        body = get_body()
        offer_id = req_str(body, "assignment_offer_id")
        structure = req_enum(body, "structure", STRUCTURES)
        offer = svc.load("assignment_offers", offer_id)
        contract = svc.contract_of_offer(offer)
        svc.guard_owner(svc.wholesaler_id_of_contract(contract) == user_id)
        svc.guard_contract_terminal(contract)
        if svc.agreement_for_offer(offer["id"]) is not None:
            fail("ERR_INVALID_STATE", "This offer has already been papered.")
        if offer["status"] != "ACCEPTED":
            fail("ERR_OFFER_NOT_ACCEPTED", "The referenced offer is not accepted.")
        wholesaler = svc.wholesaler_of_contract(contract)
        lead = svc.lead_of_contract(contract)
        svc.guard_compliance_hold(wholesaler)
        svc.guard_cooling_off(lead)
        if (
            structure == "ASSIGNMENT"
            and wholesaler is not None
            and wholesaler["licensure_status"] == "UNLICENSED"
            and not contract["assignment_rights_granted"]
        ):
            fail(
                "ERR_UNLICENSED_BROKERAGE_ACTIVITY",
                "An unlicensed wholesaler may not assign a non-assignable contract.",
            )
        svc.guard_assignment_deadline(contract)
        election = contract["structure_election"]
        if (structure == "ASSIGNMENT" and election != "ASSIGNMENT_ELECTED") or (
            structure == "DOUBLE_CLOSE" and election != "DOUBLE_CLOSE_ELECTED"
        ):
            fail(
                "ERR_STRUCTURE_MISMATCH",
                "The papered structure does not match the contract's election.",
            )
        svc.guard_fee_cap(offer["buyer_price_cents"], contract, lead)

        rec = base_record()
        rec.update(
            {
                "assignment_offer_id": offer["id"],
                "structure": structure,
                "assignment_fee_cents": offer["assignment_fee_cents"],
                "title_holdback_cents": 0,
                "state_transfer_surcharge_cents": 0,
                "marketing_cost_recovery_cents": 0,
                "wholesaler_net_cents": 0,
                "settlement_status": "PENDING_SETTLEMENT",
                "settlement_reference": None,
                "settled_at": None,
                "executed_at": now(),
            }
        )
        svc.store("assignment_agreements", rec)

        offer["status"] = "CONSUMED"
        touch(offer)
        contract["assignment_status"] = "ASSIGNED"
        svc.recompute_spread(contract)
        touch(contract)
        buyer = svc.buyer_of_offer(offer)
        if buyer is not None:
            svc.recompute_buyer(buyer)
        svc.recompute_executed_count(wholesaler)
        return respond_object(rec, 201)

    @app.get("/assignment-agreements/<assignment_agreement_id>")
    def read_agreement(assignment_agreement_id):
        authenticate(ALL_ROLES, require_user_id=False)
        return respond_object(
            svc.load("assignment_agreements", assignment_agreement_id)
        )

    @app.get("/assignment-agreements")
    def list_agreements():
        authenticate(ALL_ROLES, require_user_id=False)
        return list_response(
            svc.all_of("assignment_agreements"),
            [
                ("assignment_offer_id", "assignment_offer_id"),
                ("settlement_status", "settlement_status"),
            ],
        )

    @app.post("/assignment-agreements/<assignment_agreement_id>/settle")
    def settle_agreement(assignment_agreement_id):
        authenticate(["TitleAgent"])
        body = get_body()
        reference = req_str(body, "settlement_reference", max_len=200)
        agreement = svc.load("assignment_agreements", assignment_agreement_id)
        contract = svc.contract_of_agreement(agreement)
        if contract is not None:
            svc.guard_contract_terminal(contract)
        if agreement["settlement_status"] != "PENDING_SETTLEMENT":
            fail("ERR_INVALID_STATE", "This agreement is no longer pending settlement.")
        holdback, surcharge, recovery, net = calc.assignment_fee_settlement(
            agreement["assignment_fee_cents"]
        )
        agreement["title_holdback_cents"] = holdback
        agreement["state_transfer_surcharge_cents"] = surcharge
        agreement["marketing_cost_recovery_cents"] = recovery
        agreement["wholesaler_net_cents"] = net
        agreement["settlement_status"] = "SETTLED"
        agreement["settlement_reference"] = reference
        agreement["settled_at"] = now()
        touch(agreement)
        return respond_object(agreement)

    # -- TitleOrder ---------------------------------------------------------
    @app.post("/title-orders")
    def create_title_order():
        authenticate(["Wholesaler"])
        body = get_body()
        contract_id = req_str(body, "purchase_contract_id")
        company = req_str(body, "title_company_name", max_len=200)
        officer_ref = req_str(body, "escrow_officer_ref", max_len=120)
        window_start = req_dt(body, "funding_window_start_at")
        window_end = req_dt(body, "funding_window_end_at")
        if window_end <= window_start:
            fail(
                "ERR_INVALID_REQUEST",
                "funding_window_end_at must be strictly after funding_window_start_at.",
            )
        contract = svc.load("purchase_contracts", contract_id)
        svc.guard_contract_terminal(contract)
        if contract["contract_status"] == "DRAFT":
            fail("ERR_CONTRACT_NOT_SIGNED", "The seller has not signed the contract.")
        structure = (
            "DOUBLE_CLOSE"
            if contract["structure_election"] == "DOUBLE_CLOSE_ELECTED"
            else "ASSIGNMENT"
        )
        buffered_end = None
        if structure == "DOUBLE_CLOSE":
            buffered_end = window_end + timedelta(hours=calc.DOUBLE_CLOSE_BUFFER_HOURS)
            wholesaler = svc.wholesaler_of_contract(contract)
            capacity = int(wholesaler["funding_window_capacity"]) if wholesaler else 1
            conflicts = svc.funding_window_conflicts(
                wholesaler["id"] if wholesaler else None, window_start, buffered_end
            )
            if conflicts >= capacity:
                fail(
                    "ERR_FUNDING_WINDOW_CONFLICT",
                    "The transactional-lender line has no free funding window.",
                )
        rec = base_record()
        rec.update(
            {
                "purchase_contract_id": contract["id"],
                "title_company_name": company,
                "escrow_officer_ref": officer_ref,
                "funding_window_start_at": window_start,
                "funding_window_end_at": window_end,
                "status": "OPENED",
                "structure": structure,
                "cleared_by_user_id": None,
                "funded_by_user_id": None,
                "buffered_window_end_at": buffered_end,
            }
        )
        svc.store("title_orders", rec)
        return respond_object(rec, 201)

    @app.get("/title-orders/<title_order_id>")
    def read_title_order(title_order_id):
        authenticate(ALL_ROLES, require_user_id=False)
        return respond_object(svc.load("title_orders", title_order_id))

    @app.get("/title-orders")
    def list_title_orders():
        authenticate(ALL_ROLES, require_user_id=False)
        return list_response(
            svc.all_of("title_orders"),
            [
                ("purchase_contract_id", "purchase_contract_id"),
                ("status", "status"),
                ("structure", "structure"),
            ],
        )

    @app.post("/title-orders/<title_order_id>/clear-to-fund")
    def clear_to_fund(title_order_id):
        _role, user_id = authenticate(["TitleAgent"])
        order = svc.load("title_orders", title_order_id)
        contract = svc.collection("purchase_contracts").get(
            order["purchase_contract_id"]
        )
        if contract is not None:
            svc.guard_contract_terminal(contract)
        if order["status"] != "OPENED":
            fail("ERR_INVALID_STATE", "Only an OPENED title order may be cleared.")
        if order["structure"] == "DOUBLE_CLOSE":
            if contract["structure_election"] != "DOUBLE_CLOSE_ELECTED":
                fail(
                    "ERR_INVALID_STATE",
                    "The contract no longer elects a double close.",
                )
        else:
            if contract["assignment_status"] != "ASSIGNED":
                fail(
                    "ERR_CONTRACT_NOT_ASSIGNED",
                    "The contract has not been assigned yet.",
                )
        order["status"] = "CLEARED_TO_FUND"
        order["cleared_by_user_id"] = user_id
        touch(order)
        if contract["contract_status"] == "SIGNED":
            contract["contract_status"] = "PENDING_CLOSE"
            touch(contract)
        return respond_object(order)

    @app.post("/title-orders/<title_order_id>/fund-and-close")
    def fund_and_close(title_order_id):
        _role, user_id = authenticate(["TitleAgent"])
        order = svc.load("title_orders", title_order_id)
        if (
            order.get("cleared_by_user_id") is not None
            and order["cleared_by_user_id"] == user_id
        ):
            fail(
                "ERR_DUAL_CONTROL_REQUIRED",
                "The clearing agent may not also fund and close.",
            )
        contract = svc.collection("purchase_contracts").get(
            order["purchase_contract_id"]
        )
        if contract is not None:
            svc.guard_contract_terminal(contract)
        if order["status"] != "CLEARED_TO_FUND":
            fail("ERR_INVALID_STATE", "The title order is not cleared to fund.")
        order["status"] = "FUNDED_AND_CLOSED"
        order["funded_by_user_id"] = user_id
        touch(order)
        contract["contract_status"] = "CLOSED"
        touch(contract)
        lead = svc.lead_of_contract(contract)
        if lead is not None:
            svc.set_fields(lead, {"status": "CLOSED"})
        deposit = svc.deposit_of_contract(contract)
        if deposit is not None and deposit["status"] == "HELD":
            calc.apply_disposition(deposit, "APPLY_AT_CLOSING")
            touch(deposit)
        return respond_object(order)

    # -- ComplianceReview ---------------------------------------------------
    @app.post("/compliance-reviews")
    def open_review():
        _role, user_id = authenticate(["ComplianceOfficer"])
        body = get_body()
        wholesaler_id = req_str(body, "wholesaler_id")
        review_type = req_enum(body, "review_type", REVIEW_TYPES)
        allegation_note = req_str(body, "allegation_note", max_len=1000)
        subject_lead_id = opt_id(body, "subject_seller_lead_id")
        wholesaler = svc.load("wholesalers", wholesaler_id)
        subject_lead = None
        if subject_lead_id is not None:
            subject_lead = svc.load("seller_leads", subject_lead_id)
        rec = base_record()
        rec.update(
            {
                "wholesaler_id": wholesaler["id"],
                "subject_seller_lead_id": subject_lead["id"] if subject_lead else None,
                "review_type": review_type,
                "allegation_note": allegation_note,
                "status": "OPENED",
                "finding": None,
                "opened_by_user_id": user_id,
                "adjudicated_by_user_id": None,
                "adjudicated_at": None,
            }
        )
        svc.store("compliance_reviews", rec)
        return respond_object(rec, 201)

    @app.get("/compliance-reviews/<compliance_review_id>")
    def read_review(compliance_review_id):
        authenticate(
            ["Wholesaler", "ComplianceOfficer", "PlatformAdmin"], require_user_id=False
        )
        return respond_object(svc.load("compliance_reviews", compliance_review_id))

    @app.get("/compliance-reviews")
    def list_reviews():
        authenticate(
            ["Wholesaler", "ComplianceOfficer", "PlatformAdmin"], require_user_id=False
        )
        return list_response(
            svc.all_of("compliance_reviews"),
            [
                ("wholesaler_id", "wholesaler_id"),
                ("subject_seller_lead_id", "subject_seller_lead_id"),
                ("status", "status"),
                ("review_type", "review_type"),
            ],
        )

    @app.post("/compliance-reviews/<compliance_review_id>/adjudicate")
    def adjudicate_review(compliance_review_id):
        _role, user_id = authenticate(["ComplianceOfficer"])
        body = get_body()
        decision = req_enum(body, "decision", DECISIONS)
        finding = req_enum(body, "finding", FINDINGS)
        req_str(body, "rationale")
        review = svc.load("compliance_reviews", compliance_review_id)
        if review["opened_by_user_id"] == user_id:
            fail(
                "ERR_SEGREGATION_OF_DUTIES",
                "The opening officer may not adjudicate their own review.",
            )
        if review["status"] != "OPENED":
            fail("ERR_INVALID_STATE", "This review has already been adjudicated.")
        if (decision == "CLEAR") != (finding == "NO_VIOLATION"):
            fail(
                "ERR_INVALID_STATE",
                "The decision and the finding are inconsistent.",
            )
        review["finding"] = finding
        review["adjudicated_by_user_id"] = user_id
        review["adjudicated_at"] = now()
        review["status"] = (
            "ADJUDICATED_CLEARED" if decision == "CLEAR" else "ADJUDICATED_ADVERSE"
        )
        touch(review)
        wholesaler = svc.collection("wholesalers").get(review["wholesaler_id"])
        if wholesaler is not None:
            svc.recompute_wholesaler(wholesaler)
            svc.hold_cascade(wholesaler)
        return respond_object(review)

    # -- DisputeCase --------------------------------------------------------
    @app.post("/dispute-cases")
    def open_dispute():
        _role, user_id = authenticate(["Seller"])
        body = get_body()
        contract_id = req_str(body, "purchase_contract_id")
        basis = req_enum(body, "dispute_basis", DISPUTE_BASES)
        claimed = req_int(body, "claimed_amount_cents", minimum=1)
        contract = svc.load("purchase_contracts", contract_id)
        svc.guard_owner(contract["seller_lead_id"] == user_id)
        rec = base_record()
        rec.update(
            {
                "purchase_contract_id": contract["id"],
                "dispute_basis": basis,
                "claimed_amount_cents": claimed,
                "status": "OPENED",
                "seller_evidence_ref": None,
                "wholesaler_evidence_ref": None,
                "award": None,
                "award_seller_cents": None,
                "award_wholesaler_cents": None,
                "adjudicated_by_user_id": None,
            }
        )
        svc.store("dispute_cases", rec)
        return respond_object(rec, 201)

    @app.get("/dispute-cases/<dispute_case_id>")
    def read_dispute(dispute_case_id):
        authenticate(
            ["Wholesaler", "Seller", "ComplianceOfficer", "PlatformAdmin"],
            require_user_id=False,
        )
        return respond_object(svc.load("dispute_cases", dispute_case_id))

    @app.get("/dispute-cases")
    def list_disputes():
        authenticate(
            ["Wholesaler", "Seller", "ComplianceOfficer", "PlatformAdmin"],
            require_user_id=False,
        )
        return list_response(
            svc.all_of("dispute_cases"),
            [
                ("purchase_contract_id", "purchase_contract_id"),
                ("status", "status"),
                ("dispute_basis", "dispute_basis"),
            ],
        )

    @app.post("/dispute-cases/<dispute_case_id>/submit-evidence")
    def submit_evidence(dispute_case_id):
        role, user_id = authenticate(["Seller", "Wholesaler"])
        body = get_body()
        evidence_ref = req_str(body, "evidence_ref", max_len=200)
        dispute = svc.load("dispute_cases", dispute_case_id)
        contract = svc.collection("purchase_contracts").get(
            dispute["purchase_contract_id"]
        )
        if role == "Seller":
            svc.guard_owner(
                contract is not None and contract["seller_lead_id"] == user_id
            )
            field = "seller_evidence_ref"
        else:
            svc.guard_owner(
                contract is not None
                and svc.wholesaler_id_of_contract(contract) == user_id
            )
            field = "wholesaler_evidence_ref"
        if dispute["status"] == "ADJUDICATED":
            fail("ERR_INVALID_STATE", "This dispute has already been adjudicated.")
        if dispute.get(field) is not None:
            fail("ERR_INVALID_STATE", "This party has already filed its evidence.")
        dispute[field] = evidence_ref
        if (
            dispute["seller_evidence_ref"] is not None
            and dispute["wholesaler_evidence_ref"] is not None
        ):
            dispute["status"] = "EVIDENCE_COMPLETE"
        else:
            dispute["status"] = "EVIDENCE_PARTIAL"
        touch(dispute)
        return respond_object(dispute)

    @app.post("/dispute-cases/<dispute_case_id>/adjudicate")
    def adjudicate_dispute(dispute_case_id):
        _role, user_id = authenticate(["ComplianceOfficer"])
        body = get_body()
        award = req_enum(body, "award", AWARDS)
        req_str(body, "rationale")
        dispute = svc.load("dispute_cases", dispute_case_id)
        if dispute["status"] == "ADJUDICATED":
            fail("ERR_INVALID_STATE", "This dispute has already been adjudicated.")
        contract = svc.collection("purchase_contracts").get(
            dispute["purchase_contract_id"]
        )
        deposit = svc.deposit_of_contract(contract) if contract else None
        if deposit is None or deposit["status"] in ("HELD", "APPLIED_AT_CLOSING"):
            fail(
                "ERR_DEPOSIT_NOT_HELD",
                "There is no forfeited escrow to redistribute.",
            )
        if (
            dispute["seller_evidence_ref"] is None
            or dispute["wholesaler_evidence_ref"] is None
        ):
            fail("ERR_EVIDENCE_INCOMPLETE", "Both parties must file evidence first.")
        award_seller, award_wholesaler = calc.apply_dispute_award(deposit, award)
        touch(deposit)
        dispute["award"] = award
        dispute["award_seller_cents"] = award_seller
        dispute["award_wholesaler_cents"] = award_wholesaler
        dispute["adjudicated_by_user_id"] = user_id
        dispute["status"] = "ADJUDICATED"
        touch(dispute)
        return respond_object(dispute)

    # -- Logical clock ------------------------------------------------------
    @app.post("/_clock/set_current_utc")
    def set_clock():
        authenticate(["PlatformAdmin"])
        body = get_body()
        target = req_dt(body, "to_iso8601")
        db.current_utc = target
        svc.recompute_all_buyers()
        return respond_raw({"current_utc": iso_ms(db.current_utc)})
