"""Settlement negotiation: OCC on the case version, supersession, the customer
cap, segregation of duties on acceptance, and case closure (PRD §2.9, §3.7)."""
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    advance_case,
    assert_offer,
    get_case,
    get_license_position,
    make_legal_counsel_headers,
    make_vendor_auditor_headers,
    setup_case_in_evidence_collection,
    setup_case_in_settlement_negotiation,
    setup_product_with_gap,
    setup_released_submission,
    tender_offer,
    tender_offer_ok,
    validate_error,
    validate_success,
)


def _setup_settlement_case():
    """Product unit 5000, support 0.20, entitled 50, deployed 60 CONFIRMED
    (gap 10; vendor-list 60000; finding 70000). Full flow to
    SETTLEMENT_NEGOTIATION with the finding recorded; ctx["case"]["version"] is
    fresh for tendering."""
    product_ctx = setup_product_with_gap(entitled=50, deployed=60,
                                         unit_list_price_cents=5000,
                                         support_rate_pct=0.2,
                                         license_metric="PER_USER")
    return setup_case_in_settlement_negotiation(product_ctx)


class TestOfferValidationOrdering:
    def _setup_evidence_case(self):
        """Same product shape as the settlement fixture, but the case stops in
        EVIDENCE_COLLECTION so an offer tender violates the state gate."""
        product_ctx = setup_product_with_gap(entitled=50, deployed=60,
                                             unit_list_price_cents=5000,
                                             support_rate_pct=0.2,
                                             license_metric="PER_USER")
        ctx = setup_case_in_evidence_collection(product_ctx)
        ctx["submission"] = setup_released_submission(ctx)
        ctx["case"] = get_case(ctx["case"]["id"])
        return ctx

    def test_offer_in_wrong_case_state_reports_state_error(
            self, api, procurement_lead_headers):
        """PRD §2.10: "Every request is validated against a fixed, prioritized
        chain; the first failing check produces the error response and later checks
        are not evaluated."
        PRD §2.10: "6. State legality — first the target resource's own status is
        checked against the requested transition (`ERR_ENTITLEMENT_INVALID_STATE`,
        `ERR_DEPLOYMENT_INVALID_STATE`, `ERR_SCOPE_ITEM_INVALID_STATE`,
        `ERR_SUBMISSION_INVALID_STATE`, `ERR_OFFER_INVALID_STATE`,
        `ERR_REMEDIATION_INVALID_STATE`, or `ERR_ALERT_INVALID_STATE`), then the
        cross-entity state gates in a pinned order: the parent audit case's status
        for scope-item, submission, and offer operations
        (`ERR_AUDIT_CASE_INVALID_STATE`)"
        PRD §3.7: "Offers can be tendered only while the parent case is in
        `SETTLEMENT_NEGOTIATION`, failing with `ERR_AUDIT_CASE_INVALID_STATE`
        otherwise."

        Design: Difficulty/priority_pair_validation_conflict/offer_wrong_state_and_over_cap_state_wins
        """
        ctx = self._setup_evidence_case()
        case = ctx["case"]
        assert case["status"] == "EVIDENCE_COLLECTION"
        assert case["worst_case_exposure_cents"] == 60000

        # Amount 99999999 simultaneously violates the fiscal cap (60000); the
        # earlier state check must win per the fixed validation chain.
        resp = tender_offer(case["id"], "CUSTOMER", 99999999, case["version"],
                            tenderer_user_id="proc-1")
        validate_error(resp, ApiErrorId.ERR_AUDIT_CASE_INVALID_STATE)

    def test_offer_rejected_in_wrong_state_leaves_no_pending_offer(
            self, api, procurement_lead_headers, legal_counsel_headers):
        """PRD §2.10: "Every request is validated against a fixed, prioritized
        chain; the first failing check produces the error response and later checks
        are not evaluated."
        PRD §3.7: "Offers can be tendered only while the parent case is in
        `SETTLEMENT_NEGOTIATION`, failing with `ERR_AUDIT_CASE_INVALID_STATE`
        otherwise."

        Design: Difficulty/priority_pair_validation_conflict/offer_wrong_state_and_over_cap_state_wins
        """
        ctx = self._setup_evidence_case()
        case = ctx["case"]

        resp = tender_offer(case["id"], "CUSTOMER", 99999999, case["version"],
                            tenderer_user_id="proc-1")
        validate_error(resp, ApiErrorId.ERR_AUDIT_CASE_INVALID_STATE)

        offers = validate_success(
            api.list_settlement_offers(legal_counsel_headers,
                                       params={"audit_case_id": case["id"]}), 200)
        assert offers == [], "a rejected tender persists no offer"
        after = get_case(case["id"])
        assert after["version"] == case["version"], \
            "a rejected tender does not advance the case version"
        assert after["status"] == "EVIDENCE_COLLECTION"


class TestOfferSupersession:
    def test_superseded_offer_cannot_be_accepted(self, api, vendor_auditor_headers):
        """PRD §3.7: "Every offer is created directly in `TENDERED` status, its
        `tendered_by_user_id` stamped from `X-User-ID`, and tendering supersedes
        whatever offer was previously pending for the case: the prior `TENDERED`
        offer moves to `SUPERSEDED`, the new offer's `supersedes_offer_id` points at
        that prior offer (null when none existed), and the case's
        `last_tendered_offer_id` is updated to the new offer while the case
        `version` increments by one."
        PRD §3.7: "Acceptance belongs to the counterparty: a `VENDOR` offer is
        accepted by `LegalCounsel`, and a `CUSTOMER` offer is accepted by the
        `VendorAuditor` — a role that does not match the offer's party is rejected
        with `ERR_INSUFFICIENT_PERMISSIONS` — and only a `TENDERED` offer can be
        accepted (`ERR_OFFER_INVALID_STATE` otherwise)."

        Design: Corner/state_machines/superseded_offer_cannot_be_accepted
        """
        ctx = _setup_settlement_case()
        case_id = ctx["case"]["id"]
        cv1 = ctx["case"]["version"]

        o1 = tender_offer_ok(case_id, "CUSTOMER", 50000, cv1,
                             tenderer_user_id="proc-1")
        assert_offer(o1)
        assert o1["status"] == "TENDERED"
        assert o1["supersedes_offer_id"] is None

        cv2 = get_case(case_id)["version"]
        o2 = tender_offer_ok(case_id, "VENDOR", 65000, cv2,
                             tenderer_user_id="aud-1")
        assert o2["supersedes_offer_id"] == o1["id"], \
            "the newer offer records the chain link"

        # The acceptor role (VendorAuditor) matches the CUSTOMER offer's
        # counterparty and is not the tenderer, so the state error is what fires.
        resp = api.accept_offer(o1["id"], make_vendor_auditor_headers("aud-9"))
        validate_error(resp, ApiErrorId.ERR_OFFER_INVALID_STATE)


class TestOptimisticConcurrency:
    def test_offer_create_stale_version_returns_412(self, api, legal_counsel_headers):
        """PRD §2.9: "Tendering a settlement offer is the system's single write
        operation guarded by optimistic concurrency control. The request must carry
        `expected_audit_case_version`, a non-optional field holding the AuditCase
        `version` the client last observed. If the supplied value does not equal the
        case's current `version` — because, for example, another offer has been
        tendered since the client last read the case (an event that legitimately
        supersedes the previously pending offer and advances the case version), or a
        scope item was confirmed, or evidence was released — the request is rejected
        with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/offer_create_stale_version_returns_412
        """
        ctx = _setup_settlement_case()
        case_id = ctx["case"]["id"]
        stale_version = ctx["case"]["version"]

        o1 = tender_offer_ok(case_id, "CUSTOMER", 50000, stale_version,
                             tenderer_user_id="proc-1")
        assert o1["status"] == "TENDERED"

        # The tender advanced the case version, so the same version is now stale.
        resp = tender_offer(case_id, "VENDOR", 65000, stale_version,
                            tenderer_user_id="aud-1")
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, expected_status=412)

        o1_after = validate_success(
            api.get_settlement_offer(o1["id"], legal_counsel_headers), 200)
        assert o1_after["status"] == "TENDERED", \
            "the rejected create did not supersede the pending offer"


class TestCustomerOfferCap:
    def test_customer_offer_capped_at_worst_case(self, api, procurement_lead_headers):
        """PRD §3.7: "A customer offer is capped at the case's current
        `worst_case_exposure_cents`: an amount above the cap is rejected with
        `ERR_OFFER_EXCEEDS_WORST_CASE_CAP`, while an amount exactly equal to the cap
        is allowed."

        Design: Corner/validations/customer_offer_capped_at_worst_case
        """
        ctx = _setup_settlement_case()
        case = get_case(ctx["case"]["id"])
        assert case["worst_case_exposure_cents"] == 70000, \
            "the recorded 70000-cent finding drives the cap"
        cv = case["version"]

        over = tender_offer(case["id"], "CUSTOMER", 70001, cv,
                            tenderer_user_id="proc-1")
        validate_error(over, ApiErrorId.ERR_OFFER_EXCEEDS_WORST_CASE_CAP)

        at_cap = tender_offer(case["id"], "CUSTOMER", 70000, cv,
                              tenderer_user_id="proc-1")
        offer = validate_success(at_cap, 201)
        assert_offer(offer)
        assert offer["status"] == "TENDERED", "an amount exactly equal to the cap is allowed"
        assert offer["amount_cents"] == 70000


class TestOfferAcceptance:
    def test_offer_acceptance_closes_case_settled(self, api, legal_counsel_headers):
        """PRD §3.7: "Acceptance closes the case as `CLOSED_SETTLED`, copying the
        accepted offer's `amount_cents` into the case's `settled_amount_cents` and
        its `future_license_discount_pct` into `accepted_future_discount_pct`; every
        product with a `CONFIRMED` scope item in the case has its `position_basis`
        advanced to `AGREED`; and the case `version` increments by one."
        PRD §3.7: "Acceptance belongs to the counterparty: a `VENDOR` offer is
        accepted by `LegalCounsel`, and a `CUSTOMER` offer is accepted by the
        `VendorAuditor`"

        Design: Corner/endpoints/offer_acceptance_closes_case_settled
        """
        ctx = _setup_settlement_case()
        case_id = ctx["case"]["id"]

        offer = tender_offer_ok(case_id, "VENDOR", 65000, ctx["case"]["version"],
                                tenderer_user_id="aud-1",
                                future_license_discount_pct=0.15)
        assert offer["future_license_discount_pct"] == pytest.approx(0.15)

        accepted = validate_success(
            api.accept_offer(offer["id"], legal_counsel_headers), 200)
        assert accepted["status"] == "ACCEPTED"

        case = get_case(case_id)
        assert case["status"] == "CLOSED_SETTLED"
        assert case["settled_amount_cents"] == 65000
        assert case["accepted_future_discount_pct"] == pytest.approx(0.15)

        position = get_license_position(ctx["product"]["id"])
        assert position["position_basis"] == "AGREED", \
            "the scoped product's basis advances to AGREED on acceptance"

    def test_sod_offer_accept_by_tenderer_rejected(self, api):
        """PRD §3.7: "The acceptor's `X-User-ID` must differ from the
        `tendered_by_user_id` stamped at tender time, otherwise acceptance fails
        with `ERR_SEGREGATION_OF_DUTIES_VIOLATION`."

        Design: Corner/validations/sod_offer_accept_by_tenderer_rejected
        """
        ctx = _setup_settlement_case()
        case_id = ctx["case"]["id"]
        offer = tender_offer_ok(case_id, "CUSTOMER", 50000, ctx["case"]["version"],
                                tenderer_user_id="proc-shared")

        # Correct counterparty role (VendorAuditor) but the same user id.
        resp = api.accept_offer(offer["id"],
                                make_vendor_auditor_headers("proc-shared"))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES_VIOLATION)

        still = validate_success(
            api.get_settlement_offer(offer["id"],
                                     make_legal_counsel_headers("counsel-1")), 200)
        assert still["status"] == "TENDERED", "the rejected accept does not move the offer"


class TestOfferReadErrors:
    def test_offer_not_found_on_accept(self, api, legal_counsel_headers):
        """PRD §3.7: "Offers may be browsed as a list filtered by `audit_case_id`,
        `supersedes_offer_id`, or `status`, or fetched individually, with unknown
        identifiers surfacing as `ERR_OFFER_NOT_FOUND`."

        Design: Corner/errors/offer_not_found_on_accept
        """
        resp = api.accept_offer(NON_EXISTENT_UUID, legal_counsel_headers)
        validate_error(resp, ApiErrorId.ERR_OFFER_NOT_FOUND)
