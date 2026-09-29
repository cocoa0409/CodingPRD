"""Cash buyers, proof of funds and the assignment-offer negotiation."""
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
    opt_id,
    opt_int,
    opt_str,
    req_dt,
    req_int,
    req_str,
    respond_object,
    touch,
)

APPROVE_DECISIONS = ("VERIFIED", "VERIFY", "APPROVE", "APPROVED")
REJECT_DECISIONS = ("REJECTED", "REJECT", "DENY", "DENIED")


def register(app):
    # -- CashBuyer ----------------------------------------------------------
    @app.post("/cash-buyers")
    def create_buyer():
        authenticate(["Wholesaler"])
        body = get_body()
        wholesaler_id = req_str(body, "wholesaler_id")
        legal_name = req_str(body, "legal_name", max_len=200)
        contact_email = req_str(body, "contact_email", max_len=200)
        if "@" not in contact_email:
            fail("ERR_INVALID_REQUEST", "contact_email must contain an at-sign.")
        wholesaler = svc.load("wholesalers", wholesaler_id)
        rec = base_record()
        rec.update(
            {
                "wholesaler_id": wholesaler["id"],
                "legal_name": legal_name,
                "contact_email": contact_email,
                "verified_funds_cents": 0,
                "committed_deposit_cents": 0,
                "available_funds_cents": 0,
                "buyer_tier": "SUSPENDED",
                "active_offer_count": 0,
            }
        )
        svc.store("cash_buyers", rec)
        return respond_object(rec, 201)

    @app.get("/cash-buyers/<cash_buyer_id>")
    def read_buyer(cash_buyer_id):
        authenticate(ALL_ROLES, require_user_id=False)
        return respond_object(svc.load("cash_buyers", cash_buyer_id))

    @app.get("/cash-buyers")
    def list_buyers():
        authenticate(
            ["Wholesaler", "ComplianceOfficer", "PlatformAdmin"], require_user_id=False
        )
        return list_response(
            svc.all_of("cash_buyers"),
            [("wholesaler_id", "wholesaler_id"), ("buyer_tier", "buyer_tier")],
        )

    # -- ProofOfFunds -------------------------------------------------------
    @app.post("/proof-of-funds")
    def create_proof():
        _role, user_id = authenticate(["CashBuyer"])
        body = get_body()
        buyer_id = req_str(body, "cash_buyer_id")
        stated = req_int(body, "stated_funds_cents", minimum=1)
        document_ref = req_str(body, "document_ref", max_len=120)
        expires_at = req_dt(body, "expires_at")
        buyer = svc.load("cash_buyers", buyer_id)
        svc.guard_owner(buyer["id"] == user_id)
        rec = base_record()
        rec.update(
            {
                "cash_buyer_id": buyer["id"],
                "stated_funds_cents": stated,
                "document_ref": document_ref,
                "expires_at": expires_at,
                "verification_status": "SUBMITTED",
                "verified_funds_cents": None,
                "verified_at": None,
                "verified_by_user_id": None,
            }
        )
        svc.store("proof_of_funds", rec)
        return respond_object(rec, 201)

    @app.get("/proof-of-funds/<proof_of_funds_id>")
    def read_proof(proof_of_funds_id):
        authenticate(ALL_ROLES, require_user_id=False)
        return respond_object(svc.load("proof_of_funds", proof_of_funds_id))

    @app.get("/proof-of-funds")
    def list_proofs():
        authenticate(
            ["Wholesaler", "CashBuyer", "ComplianceOfficer", "PlatformAdmin"],
            require_user_id=False,
        )
        return list_response(
            svc.all_of("proof_of_funds"),
            [
                ("cash_buyer_id", "cash_buyer_id"),
                ("verification_status", "verification_status"),
            ],
        )

    @app.post("/proof-of-funds/<proof_of_funds_id>/verify")
    def verify_proof(proof_of_funds_id):
        _role, user_id = authenticate(["Wholesaler"])
        body = get_body()
        decision = req_str(body, "verification_decision")
        override = opt_int(body, "verified_funds_cents", minimum=0)
        opt_str(body, "verification_note")
        normalized = decision.strip().upper()
        if normalized in APPROVE_DECISIONS:
            approve = True
        elif normalized in REJECT_DECISIONS:
            approve = False
        else:
            fail(
                "ERR_INVALID_REQUEST",
                "verification_decision must record an approval or a rejection.",
            )
        proof = svc.load("proof_of_funds", proof_of_funds_id)
        buyer = svc.collection("cash_buyers").get(proof["cash_buyer_id"])
        svc.guard_owner(buyer is not None and buyer["wholesaler_id"] == user_id)
        if proof["verification_status"] != "SUBMITTED":
            fail("ERR_INVALID_STATE", "This proof of funds has already been decided.")
        if approve:
            if proof["expires_at"] <= now():
                fail(
                    "ERR_PROOF_OF_FUNDS_EXPIRED",
                    "The proof of funds is already stale.",
                )
            proof["verification_status"] = "VERIFIED"
            proof["verified_funds_cents"] = (
                override if override is not None else proof["stated_funds_cents"]
            )
        else:
            proof["verification_status"] = "REJECTED"
            proof["verified_funds_cents"] = None
        proof["verified_at"] = now()
        proof["verified_by_user_id"] = user_id
        touch(proof)
        svc.recompute_buyer(buyer)
        return respond_object(proof)

    # -- AssignmentOffer ----------------------------------------------------
    @app.post("/assignment-offers")
    def create_offer():
        _role, user_id = authenticate(["CashBuyer"])
        body = get_body()
        contract_id = req_str(body, "purchase_contract_id")
        buyer_id = req_str(body, "cash_buyer_id")
        buyer_price = req_int(body, "buyer_price_cents", minimum=1)
        buyer_deposit = req_int(body, "buyer_deposit_cents", minimum=1)
        expected_version = req_int(body, "expected_purchase_contract_version")
        supersedes_id = opt_id(body, "supersedes_offer_id")

        contract = svc.load("purchase_contracts", contract_id)
        buyer = svc.load("cash_buyers", buyer_id)
        superseded = None
        if supersedes_id is not None:
            superseded = svc.load("assignment_offers", supersedes_id)

        svc.guard_owner(buyer["id"] == user_id)
        svc.guard_owner(
            buyer["wholesaler_id"] == svc.wholesaler_id_of_contract(contract),
            "The buyer and the contract sit under different wholesalers.",
        )
        if superseded is not None:
            svc.guard_owner(
                superseded["cash_buyer_id"] == buyer["id"],
                "The superseded offer belongs to another buyer.",
            )

        if expected_version != contract["version"]:
            fail(
                "ERR_STALE_CONTRACT_VERSION",
                "The contract has moved on since it was read.",
            )

        if superseded is not None and (
            superseded["purchase_contract_id"] != contract["id"]
        ):
            fail(
                "ERR_INVALID_STATE",
                "The superseded offer sits on a different contract.",
            )
        if not contract["assignment_rights_granted"] and (
            contract["structure_election"] != "DOUBLE_CLOSE_ELECTED"
        ):
            fail(
                "ERR_INVALID_STATE",
                "This contract has no marketing path: no assignment rights and no "
                "double-close election.",
            )
        svc.guard_contract_terminal(contract)
        if contract["contract_status"] == "DRAFT":
            fail("ERR_CONTRACT_NOT_SIGNED", "The seller has not signed the contract.")

        live_offers = [
            o
            for o in svc.offers_of_contract(contract)
            if o["cash_buyer_id"] == buyer["id"]
            and o["status"] in calc.LIVE_OFFER_STATUSES
        ]
        released = 0
        remaining = []
        for offer in live_offers:
            if superseded is not None and offer["id"] == superseded["id"]:
                released = int(offer["buyer_deposit_cents"])
            else:
                remaining.append(offer)
        if remaining:
            fail(
                "ERR_DUPLICATE_ACTIVE_OFFER",
                "This buyer already has a live offer on the contract.",
            )
        if buyer_price < contract["purchase_price_cents"]:
            fail(
                "ERR_OFFER_BELOW_CONTRACT_PRICE",
                "The bid is below the contract price owed to the seller.",
            )
        available = int(buyer["available_funds_cents"]) + released
        if (
            buyer_deposit > available
            or buyer_price > int(buyer["verified_funds_cents"])
        ):
            fail(
                "ERR_INSUFFICIENT_VERIFIED_FUNDS",
                "The bid exceeds the buyer's verified liquidity.",
            )

        if superseded is not None and superseded["status"] in calc.LIVE_OFFER_STATUSES:
            superseded["status"] = "WITHDRAWN"
            touch(superseded)

        rec = base_record()
        rec.update(
            {
                "purchase_contract_id": contract["id"],
                "cash_buyer_id": buyer["id"],
                "supersedes_offer_id": superseded["id"] if superseded else None,
                "buyer_price_cents": buyer_price,
                "buyer_deposit_cents": buyer_deposit,
                "status": "SUBMITTED",
                "negotiation_round": 1,
                "countered_price_cents": None,
                "accepted_at": None,
                "assignment_fee_cents": None,
            }
        )
        svc.store("assignment_offers", rec)
        svc.recompute_buyer(buyer)
        if contract["assignment_status"] == "NOT_MARKETED":
            contract["assignment_status"] = "MARKETED"
        touch(contract)
        return respond_object(rec, 201)

    @app.get("/assignment-offers/<assignment_offer_id>")
    def read_offer(assignment_offer_id):
        authenticate(ALL_ROLES, require_user_id=False)
        return respond_object(svc.load("assignment_offers", assignment_offer_id))

    @app.get("/assignment-offers")
    def list_offers():
        authenticate(ALL_ROLES, require_user_id=False)
        return list_response(
            svc.all_of("assignment_offers"),
            [
                ("purchase_contract_id", "purchase_contract_id"),
                ("cash_buyer_id", "cash_buyer_id"),
                ("supersedes_offer_id", "supersedes_offer_id"),
                ("status", "status"),
            ],
        )

    @app.post("/assignment-offers/<assignment_offer_id>/counter")
    def counter_offer(assignment_offer_id):
        _role, user_id = authenticate(["Wholesaler"])
        body = get_body()
        countered_price = req_int(body, "countered_price_cents", minimum=1)
        offer = svc.load("assignment_offers", assignment_offer_id)
        contract = svc.contract_of_offer(offer)
        svc.guard_owner(svc.wholesaler_id_of_contract(contract) == user_id)
        svc.guard_contract_terminal(contract)
        if offer["status"] not in ("SUBMITTED", "REVISED_BY_BUYER"):
            fail("ERR_INVALID_STATE", "This offer cannot be countered.")
        wholesaler = svc.wholesaler_of_contract(contract)
        if (
            wholesaler is not None
            and wholesaler["licensure_status"] == "UNLICENSED"
            and not contract["assignment_rights_granted"]
        ):
            fail(
                "ERR_UNLICENSED_BROKERAGE_ACTIVITY",
                "An unlicensed wholesaler may not negotiate a non-assignable resale.",
            )
        if offer["negotiation_round"] >= calc.MAX_NEGOTIATION_ROUNDS:
            fail("ERR_NEGOTIATION_ROUND_LIMIT", "The negotiation round cap is reached.")
        offer["status"] = "COUNTERED_BY_WHOLESALER"
        offer["countered_price_cents"] = countered_price
        offer["negotiation_round"] = offer["negotiation_round"] + 1
        touch(offer)
        touch(contract)
        return respond_object(offer)

    @app.post("/assignment-offers/<assignment_offer_id>/revise")
    def revise_offer(assignment_offer_id):
        _role, user_id = authenticate(["CashBuyer"])
        body = get_body()
        buyer_price = req_int(body, "buyer_price_cents", minimum=1)
        buyer_deposit = req_int(body, "buyer_deposit_cents", minimum=1)
        offer = svc.load("assignment_offers", assignment_offer_id)
        svc.guard_owner(offer["cash_buyer_id"] == user_id)
        contract = svc.contract_of_offer(offer)
        svc.guard_contract_terminal(contract)
        if offer["status"] != "COUNTERED_BY_WHOLESALER":
            fail("ERR_INVALID_STATE", "Only a countered offer may be revised.")
        if offer["negotiation_round"] >= calc.MAX_NEGOTIATION_ROUNDS:
            fail("ERR_NEGOTIATION_ROUND_LIMIT", "The negotiation round cap is reached.")
        if buyer_price < contract["purchase_price_cents"]:
            fail(
                "ERR_OFFER_BELOW_CONTRACT_PRICE",
                "The revised bid is below the contract price.",
            )
        buyer = svc.buyer_of_offer(offer)
        if buyer_deposit > int(buyer["available_funds_cents"]) or buyer_price > int(
            buyer["verified_funds_cents"]
        ):
            fail(
                "ERR_INSUFFICIENT_VERIFIED_FUNDS",
                "The revised bid exceeds the buyer's verified liquidity.",
            )
        offer["buyer_price_cents"] = buyer_price
        offer["buyer_deposit_cents"] = buyer_deposit
        offer["status"] = "REVISED_BY_BUYER"
        offer["negotiation_round"] = offer["negotiation_round"] + 1
        touch(offer)
        svc.recompute_buyer(buyer)
        return respond_object(offer)

    @app.post("/assignment-offers/<assignment_offer_id>/accept")
    def accept_offer(assignment_offer_id):
        _role, user_id = authenticate(["Wholesaler"])
        offer = svc.load("assignment_offers", assignment_offer_id)
        contract = svc.contract_of_offer(offer)
        svc.guard_owner(svc.wholesaler_id_of_contract(contract) == user_id)
        svc.guard_contract_terminal(contract)
        if offer["status"] not in (
            "SUBMITTED",
            "COUNTERED_BY_WHOLESALER",
            "REVISED_BY_BUYER",
        ):
            fail("ERR_INVALID_STATE", "This offer is no longer acceptable.")
        buyer = svc.buyer_of_offer(offer)
        proofs = svc.guard_proof_of_funds(buyer)
        lead = svc.lead_of_contract(contract)
        svc.guard_compliance_hold(svc.wholesaler_of_contract(contract))
        svc.guard_cooling_off(lead)
        svc.guard_assignment_deadline(contract)
        svc.guard_proofs_unexpired(proofs)
        svc.guard_fee_cap(offer["buyer_price_cents"], contract, lead)

        offer["status"] = "ACCEPTED"
        offer["accepted_at"] = now()
        offer["assignment_fee_cents"] = int(offer["buyer_price_cents"]) - int(
            contract["purchase_price_cents"]
        )
        touch(offer)

        affected = [offer["cash_buyer_id"]]
        for sibling in svc.offers_of_contract(contract):
            if sibling["id"] == offer["id"]:
                continue
            if sibling["status"] in calc.LIVE_OFFER_STATUSES:
                sibling["status"] = "LAPSED"
                touch(sibling)
                affected.append(sibling["cash_buyer_id"])
        svc.recompute_buyers(affected)
        svc.recompute_spread(contract)
        touch(contract)
        return respond_object(offer)
