"""Warranty fault adjudication and the six-link remake cascade, including the
ceiling that mutates before it rejects."""

from test_helpers import (
    ApiErrorId,
    CLINICAL_DIRECTOR_USER_ID,
    PROSTHODONTIST_USER_ID,
    assert_lab_credit_conserved,
    assert_money,
    assert_payment_plan_conserved,
    assert_remake_request,
    assert_warranty_claim,
    create_remake_request_payload,
    fixtures as fx,
    make_clinical_director_headers,
    validate_error,
    validate_success,
)


class TestRemakeCascade:
    def test_approval_flips_the_request_the_arch_and_the_superseded_appliance(self, api):
        """PRD §3.7: "- **Link 1** sets `authorization_status` to `APPROVED`, records
        `approved_by_user_id` and `decided_at`, and increments the request's `version`
        by 1."
        PRD §3.7: "- **Link 2**, caused by link 1, moves the parent arch to
        `REMAKE_PENDING` — from `DELIVERED` when the appliance was already handed
        over, or from `MILESTONE_PENDING` when a try-in was rejected before any
        delivery ever happened — increases the arch's `remake_count` by one, and
        increments the arch's `version` by 1."
        PRD §3.7: "- **Link 3**, caused by link 2, sets the arch's most recent
        appliance to `warranty_status` `WARRANTY_VOIDED` and `recall_status`
        `RECALL_CLOSED_SUPERSEDED`, and moves every lab case of that arch whose
        `lab_status` is `DRAFT`, `DISPATCHED`, `RETURNED`, `QC_FAILED`, or `RESENT` to
        `CANCELLED`."

        Design: Difficulty/transitive_cascade/remake_approval_six_link_cascade_to_paid_off_plan
        """
        ctx = fx.setup_lab_credit_ready_remake(lab_invoice_amount=1600.00)

        approved = validate_success(
            api.approve_remake_request(
                ctx["remake_request"]["id"],
                make_clinical_director_headers(CLINICAL_DIRECTOR_USER_ID),
            ),
            200,
        )

        assert_remake_request(approved)
        assert approved["authorization_status"] == "APPROVED"
        assert approved["approved_by_user_id"] == CLINICAL_DIRECTOR_USER_ID
        assert approved["charge_basis"] == "NO_CHARGE"

        arch = fx.read_arch(ctx["arch"]["id"])
        assert arch["arch_status"] == "REMAKE_PENDING"
        assert arch["remake_count"] == 1

        prosthesis = fx.read_prosthesis(ctx["prosthesis"]["id"])
        assert prosthesis["warranty_status"] == "WARRANTY_VOIDED"
        assert prosthesis["recall_status"] == "RECALL_CLOSED_SUPERSEDED"

    def test_approval_applies_the_lab_credit_and_drives_the_plan_to_paid_off(self, api):
        """PRD §3.7: "- **Link 4**, caused by link 3, moves laboratory credit — but
        only when the request's `charge_basis` is `NO_CHARGE` and the cited warranty
        claim is in `LAB_FAULT`. The amount applied is the lesser of the claim's
        `lab_credit_amount` and the attributed laboratory's `credit_available_balance`.
        The laboratory's `credit_applied_total` rises by that amount and its
        `credit_available_balance` falls by the same, with `credit_issued_total`
        untouched — the conservation of §2.13 holding across the move."
        PRD §3.7: "- **Link 5**, caused by link 4, applies that credit to the case's
        payment plan whose `plan_status` is `ACTIVE` or `DELINQUENT`: the plan's
        `principal_amount` falls by the applied amount, its `applied_lab_credit_amount`
        rises by it, and its still-open installments are re-struck as described in
        §3.9."
        PRD §3.7: "- **Link 6**, caused by link 5, moves the re-struck plan to
        `PAID_OFF` when its `outstanding_amount` reaches 0.00 — which, when it is the
        patient's only delinquent plan, lowers the global write gate."
        PRD §3.9: "Each row absorbs the lesser of its own `amount` and whatever credit
        remains: its `amount` falls by that much, rounded half up to two decimal
        places, the remaining credit falls by the same, and a row driven to 0.00 moves
        to `WAIVED`."
        PRD §3.7: "Alongside those six, approval moves the parent case back from
        `DELIVERED` to `IN_FABRICATION` when the case was in `DELIVERED`, clearing the
        case's `delivered_at` back to null and incrementing the case's `version` by 1."

        Design: Difficulty/transitive_cascade/remake_approval_six_link_cascade_to_paid_off_plan
        """
        ctx = fx.setup_lab_credit_ready_remake(lab_invoice_amount=1600.00)
        assert_money(
            ctx["warranty_claim"]["lab_credit_amount"], 960.00, "WarrantyClaim.lab_credit_amount"
        )

        validate_success(
            api.approve_remake_request(
                ctx["remake_request"]["id"],
                make_clinical_director_headers(CLINICAL_DIRECTOR_USER_ID),
            ),
            200,
        )

        lab = fx.read_lab(ctx["lab"]["id"])
        assert_money(lab["credit_issued_total"], 960.00, "DentalLab.credit_issued_total")
        assert_money(lab["credit_applied_total"], 960.00, "DentalLab.credit_applied_total")
        assert_money(lab["credit_available_balance"], 0.00, "DentalLab.credit_available_balance")
        assert_lab_credit_conserved(lab)

        plan = fx.read_payment_plan(ctx["plan"]["id"])
        assert_money(plan["principal_amount"], 0.00, "PaymentPlan.principal_amount")
        assert_money(
            plan["applied_lab_credit_amount"], 960.00, "PaymentPlan.applied_lab_credit_amount"
        )
        assert_money(plan["outstanding_amount"], 0.00, "PaymentPlan.outstanding_amount")
        assert plan["plan_status"] == "PAID_OFF"
        assert_payment_plan_conserved(plan)

        rows = fx.installments_of(ctx["plan"]["id"])
        assert len(rows) == 3
        for row in rows:
            assert row["installment_status"] == "WAIVED"
            assert_money(row["amount"], 0.00, "Installment.amount after the credit re-strike")

        assert fx.read_case(ctx["case"]["id"])["case_status"] == "IN_FABRICATION"

    def test_approval_is_refused_when_the_cited_claim_landed_on_patient_fault(self, api):
        """PRD §3.7: "**Approval** requires, beyond segregation of duties, that the
        parent arch is in `DELIVERED` or `MILESTONE_PENDING`, and — when the request
        cites a `warranty_claim_id` — that the cited claim's `claim_status` is
        `CLINIC_FAULT` or `LAB_FAULT`, failing which the approval is refused with
        `ERR_CROSS_ENTITY_STATE`."
        PRD §2.10: "- `POST /prosthetics/remake-requests/{remake_request_id}/approve`
        — when the request cites a `warranty_claim_id`, that claim's `claim_status`
        must be `CLINIC_FAULT` or `LAB_FAULT`."

        Design: Difficulty/cross_entity_state_dependency/remake_approve_requires_cited_warranty_claim_to_be_clinic_or_lab_fault
        """
        ctx = fx.setup_delivered_prosthesis(
            patient_overrides={
                "full_name": "Rupert Ncube", "date_of_birth": "1942-04-04", "phone": "555-0399"
            }
        )
        claim = fx.open_warranty_claim(
            ctx["prosthesis"]["id"], "Denture dropped on a tiled floor"
        )
        fx.adjudicate_warranty_claim(claim["id"], "PATIENT_FAULT")
        remake = fx.request_remake(
            ctx["arch"]["id"], reason_code="FIT_FAILURE", warranty_claim_id=claim["id"]
        )
        assert remake["charge_basis"] == "CHARGEABLE"

        response = api.approve_remake_request(
            remake["id"], make_clinical_director_headers(CLINICAL_DIRECTOR_USER_ID)
        )
        validate_error(response, ApiErrorId.ERR_CROSS_ENTITY_STATE.value, 409)

        after = fx.read_remake_request(remake["id"])
        assert after["authorization_status"] == "PENDING_APPROVAL"
        assert after["charge_basis"] == "CHARGEABLE"

    def test_the_refused_approval_leaves_the_arch_the_warranty_and_the_balance_alone(self, api):
        """PRD §3.7: "- **`PATIENT_FAULT`** sets `warranty_consumed` to **false** — the
        warranty is deliberately *not* consumed — leaves `lab_credit_amount` at 0.00,
        sets `patient_charge_amount` to 180.00, adds that amount to the case's
        `billed_amount` and recomputes the case's patient responsibility, stamps
        `adjudicated_at`, and leaves the appliance in `IN_WARRANTY`."
        PRD §3.9: "3. The **service total** is the sum of `charge_amount` over the
        case's post-delivery services whose `service_status` is `COMPLETED`, plus the
        sum of `patient_charge_amount` over the case's warranty claims whose
        `claim_status` is `PATIENT_FAULT`."

        Design: Difficulty/cross_entity_state_dependency/remake_approve_requires_cited_warranty_claim_to_be_clinic_or_lab_fault
        """
        ctx = fx.setup_delivered_prosthesis(
            patient_overrides={
                "full_name": "Rupert Ncube", "date_of_birth": "1942-04-04", "phone": "555-0399"
            }
        )
        claim = fx.open_warranty_claim(
            ctx["prosthesis"]["id"], "Denture dropped on a tiled floor"
        )
        adjudicated = fx.adjudicate_warranty_claim(claim["id"], "PATIENT_FAULT")
        remake = fx.request_remake(
            ctx["arch"]["id"], reason_code="FIT_FAILURE", warranty_claim_id=claim["id"]
        )

        validate_error(
            api.approve_remake_request(
                remake["id"], make_clinical_director_headers(CLINICAL_DIRECTOR_USER_ID)
            ),
            ApiErrorId.ERR_CROSS_ENTITY_STATE.value,
            409,
        )

        arch = fx.read_arch(ctx["arch"]["id"])
        assert arch["arch_status"] == "DELIVERED"
        assert arch["remake_count"] == 0
        assert fx.read_prosthesis(ctx["prosthesis"]["id"])["warranty_status"] == "IN_WARRANTY", (
            "a patient-fault verdict does not consume the warranty"
        )
        assert adjudicated["warranty_consumed"] is False
        assert_money(
            adjudicated["patient_charge_amount"], 180.00, "WarrantyClaim.patient_charge_amount"
        )
        assert_money(
            fx.read_case(ctx["case"]["id"])["billed_amount"],
            1380.00,
            "ProsthesisCase.billed_amount",
        )


class TestWarrantyGuards:
    def test_a_second_no_charge_adjudication_is_blocked_once_the_warranty_is_spent(self, api):
        """PRD §2.10: "**Rung 23 — warranty already spent.** The prosthesis a warranty
        claim is adjudicated against does not have `warranty_status` of
        `WARRANTY_CONSUMED` or `WARRANTY_VOIDED`. An appliance whose warranty is
        already consumed or voided cannot fund a second no-charge remedy.
        `WARRANTY_EXPIRED` deliberately **passes** this rung, so that rung 24 stays
        reachable. Failure: `ERR_WARRANTY_CONSUMED`, HTTP 409."

        Design: Corner/errors/warranty_consumed_blocks_a_second_no_charge_adjudication
        """
        ctx = fx.setup_delivered_prosthesis(
            patient_overrides={
                "full_name": "Mira Antonova", "date_of_birth": "1947-05-09", "phone": "555-1037"
            }
        )
        first = fx.open_warranty_claim(
            ctx["prosthesis"]["id"], "Midline fracture within two weeks of delivery"
        )
        first = fx.adjudicate_warranty_claim(first["id"], "CLINIC_FAULT")
        second = fx.open_warranty_claim(ctx["prosthesis"]["id"], "Second reported fracture")

        assert fx.read_prosthesis(ctx["prosthesis"]["id"])["warranty_status"] == "WARRANTY_CONSUMED"

        response = api.adjudicate_warranty_claim(
            second["id"],
            {"fault_verdict": "CLINIC_FAULT"},
            make_clinical_director_headers(CLINICAL_DIRECTOR_USER_ID),
        )
        validate_error(response, ApiErrorId.ERR_WARRANTY_CONSUMED.value, 409)

        blocked = fx.read_warranty_claim(second["id"])
        assert blocked["claim_status"] == "SUBMITTED"
        assert blocked["fault_verdict"] is None
        assert first["warranty_consumed"] is True
        assert_money(first["lab_credit_amount"], 0.00, "WarrantyClaim.lab_credit_amount")

    def test_after_the_window_a_clinic_fault_verdict_is_refused_but_patient_fault_is_not(self, api):
        """PRD §2.10: "**Rung 24 — warranty window.** The logical clock is at or before
        the prosthesis's `warranty_expires_at` **when the verdict is `CLINIC_FAULT` or
        `LAB_FAULT`**. This rung is deliberately not applied when the verdict is
        `PATIENT_FAULT` or `INDETERMINATE`, because a chargeable verdict does not
        depend on the warranty window. Failure: `ERR_WARRANTY_EXPIRED`, HTTP 422."
        PRD §3.7: "- **`PATIENT_FAULT`** sets `warranty_consumed` to **false** — the
        warranty is deliberately *not* consumed — leaves `lab_credit_amount` at 0.00,
        sets `patient_charge_amount` to 180.00, adds that amount to the case's
        `billed_amount` and recomputes the case's patient responsibility, stamps
        `adjudicated_at`, and leaves the appliance in `IN_WARRANTY`."

        Design: Corner/errors/warranty_expired_blocks_a_clinic_fault_verdict_after_the_window
        """
        ctx = fx.setup_delivered_prosthesis(
            patient_overrides={
                "full_name": "Niko Salminen", "date_of_birth": "1954-06-10", "phone": "555-1038"
            }
        )
        fx.set_clock("2027-05-02T00:00:00Z")
        assert fx.read_prosthesis(ctx["prosthesis"]["id"])["warranty_status"] == "WARRANTY_EXPIRED"
        claim = fx.open_warranty_claim(
            ctx["prosthesis"]["id"], "Clasp fatigue reported a year after delivery"
        )

        refused = api.adjudicate_warranty_claim(
            claim["id"],
            {"fault_verdict": "CLINIC_FAULT"},
            make_clinical_director_headers(CLINICAL_DIRECTOR_USER_ID),
        )
        validate_error(refused, ApiErrorId.ERR_WARRANTY_EXPIRED.value, 422)

        accepted = validate_success(
            api.adjudicate_warranty_claim(
                claim["id"],
                {"fault_verdict": "PATIENT_FAULT"},
                make_clinical_director_headers(CLINICAL_DIRECTOR_USER_ID),
            ),
            200,
        )
        assert_warranty_claim(accepted)
        assert accepted["claim_status"] == "PATIENT_FAULT"
        assert_money(
            accepted["patient_charge_amount"], 180.00, "WarrantyClaim.patient_charge_amount"
        )
        assert_money(
            fx.read_case(ctx["case"]["id"])["billed_amount"],
            1380.00,
            "ProsthesisCase.billed_amount",
        )

    def test_an_indeterminate_verdict_parks_the_claim_and_the_review_applies_the_money(self, api):
        """PRD §3.7: "- **`INDETERMINATE`** moves the claim to `CLINICAL_REVIEW` rather
        than to any terminal verdict, records `INDETERMINATE` in `fault_verdict`, and
        leaves `lab_credit_amount`, `patient_charge_amount`, and `warranty_consumed` at
        their defaults. No money moves and the appliance is untouched."
        PRD §3.7: "A claim parked in `CLINICAL_REVIEW` is resolved by the same role
        through a second decision carrying a `resolved_verdict` of `CLINIC_FAULT`,
        `LAB_FAULT`, or `PATIENT_FAULT`. Each resolution applies **exactly** the
        side-effect set of the corresponding adjudication leg above — the same money
        fields, the same warranty movement, the same credit arithmetic on a lab-fault
        resolution, the same `adjudicated_at` stamp — and increments the claim's
        `version` by 1."

        Design: Corner/errors/indeterminate_verdict_routes_to_clinical_review_and_resolves_there
        """
        ctx = fx.setup_delivered_prosthesis(
            patient_overrides={
                "full_name": "Oona Virtanen", "date_of_birth": "1950-07-11", "phone": "555-1039"
            }
        )
        claim = fx.open_warranty_claim(
            ctx["prosthesis"]["id"], "Cause of the crack could not be established chairside"
        )

        parked = validate_success(
            api.adjudicate_warranty_claim(
                claim["id"],
                {"fault_verdict": "INDETERMINATE"},
                make_clinical_director_headers(CLINICAL_DIRECTOR_USER_ID),
            ),
            200,
        )
        assert parked["claim_status"] == "CLINICAL_REVIEW"
        assert parked["fault_verdict"] == "INDETERMINATE"
        assert_money(parked["patient_charge_amount"], 0.00, "patient_charge_amount")
        assert_money(parked["lab_credit_amount"], 0.00, "lab_credit_amount")
        assert parked["warranty_consumed"] is False
        assert fx.read_prosthesis(ctx["prosthesis"]["id"])["warranty_status"] == "IN_WARRANTY"

        resolved = validate_success(
            api.clinical_review_warranty_claim(
                claim["id"],
                {"resolved_verdict": "PATIENT_FAULT"},
                make_clinical_director_headers(CLINICAL_DIRECTOR_USER_ID),
            ),
            200,
        )
        assert resolved["claim_status"] == "PATIENT_FAULT"
        assert_money(
            resolved["patient_charge_amount"], 180.00, "WarrantyClaim.patient_charge_amount"
        )
        assert fx.read_prosthesis(ctx["prosthesis"]["id"])["warranty_status"] == "IN_WARRANTY", (
            "a patient-fault resolution still does not consume the warranty"
        )
        assert_money(
            fx.read_case(ctx["case"]["id"])["billed_amount"],
            1380.00,
            "ProsthesisCase.billed_amount",
        )


class TestRemakeAuthorisationGuards:
    def test_the_third_request_commits_a_final_denied_row_and_the_fourth_is_pre_empted(self, api, prosthodontist_headers):
        """PRD §2.12: "**Rung 22 — requesting a remake past the ceiling.** When a
        remake is requested on an arch whose `remake_request_count` is already at or
        above 2, the server first creates the remake request row in
        `PENDING_APPROVAL`, immediately moves it to `FINAL_DENIED` with `decided_at`
        stamped, flips the arch's `remake_eligibility` to `FINAL_DENIED`, and
        increments the arch's `version` by 1. That write is committed — the denied
        request row is a real, persisted row and is discoverable by listing remake
        requests filtered on `case_arch_id`. Only then does the call fail with
        `ERR_REMAKE_LIMIT_EXCEEDED` and HTTP 409."
        PRD §2.12: "*On a subsequent remake request against that same arch*, the arch's
        `remake_eligibility` is now `FINAL_DENIED`, so rung 11 fires first, the call
        returns **`ERR_REMAKE_FINAL_DENIED` with HTTP 409 — not
        `ERR_REMAKE_LIMIT_EXCEEDED`** — and **no second `FINAL_DENIED` request row is
        minted.** The arch accumulates exactly one final-denied row no matter how many
        times the request is repeated."
        PRD §3.7: "Rows in `FINAL_DENIED` are deliberately excluded from it, so the
        counter cannot run away once the ceiling has been hit."

        Design: Corner/state_machines/remake_attempt_ceiling_mutate_then_reject_then_final_denied_pre_emption
        """
        ctx = fx.setup_delivered_prosthesis(
            patient_overrides={
                "full_name": "Tova Ekwueme", "date_of_birth": "1957-09-21", "phone": "555-1018"
            }
        )
        arch_id = ctx["arch"]["id"]
        fx.request_remake(arch_id, reason_code="FIT_FAILURE")
        fx.request_remake(arch_id, reason_code="PATIENT_DISSATISFACTION")

        third = api.create_remake_request(
            create_remake_request_payload(arch_id, "FIT_FAILURE"), prosthodontist_headers
        )
        validate_error(third, ApiErrorId.ERR_REMAKE_LIMIT_EXCEEDED.value, 409)

        assert fx.read_arch(arch_id)["remake_eligibility"] == "FINAL_DENIED"
        rows = fx.remake_requests_of(arch_id)
        assert len(rows) == 3
        final_denied = [row for row in rows if row["authorization_status"] == "FINAL_DENIED"]
        assert len(final_denied) == 1
        assert final_denied[0]["attempt_number"] == 3

        fourth = api.create_remake_request(
            create_remake_request_payload(arch_id, "FIT_FAILURE"), prosthodontist_headers
        )
        validate_error(fourth, ApiErrorId.ERR_REMAKE_FINAL_DENIED.value, 409)

        assert len(fx.remake_requests_of(arch_id)) == 3, "no second FINAL_DENIED row is minted"
        assert fx.read_arch(arch_id)["remake_request_count"] == 2, (
            "FINAL_DENIED rows are excluded from the counter"
        )

    def test_the_requester_cannot_approve_their_own_remake(self, api):
        """PRD §2.1: "Segregation of duties is enforced on identity, not on role. Two
        different people may both hold `ClinicalDirector`; what the system forbids is
        the same `X-User-ID` both requesting and deciding the same remake."
        PRD §3.7: "Both decisions are subject to segregation of duties: the deciding
        `X-User-ID` must differ from the request's `requested_by_user_id`, and a
        self-decision is refused with `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/validations/segregation_of_duties_blocks_the_requester_from_approving_their_own_remake
        """
        ctx = fx.setup_delivered_prosthesis(
            patient_overrides={
                "full_name": "Eero Hagen", "date_of_birth": "1956-09-01", "phone": "555-1029"
            }
        )
        remake = fx.request_remake(
            ctx["arch"]["id"], reason_code="FIT_FAILURE",
            requester_user_id=PROSTHODONTIST_USER_ID,
        )
        assert remake["requested_by_user_id"] == PROSTHODONTIST_USER_ID

        self_decision = api.approve_remake_request(
            remake["id"], make_clinical_director_headers(PROSTHODONTIST_USER_ID)
        )
        validate_error(self_decision, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403)

        still_pending = fx.read_remake_request(remake["id"])
        assert still_pending["authorization_status"] == "PENDING_APPROVAL"
        assert still_pending["approved_by_user_id"] is None

        approved = validate_success(
            api.approve_remake_request(
                remake["id"], make_clinical_director_headers(CLINICAL_DIRECTOR_USER_ID)
            ),
            200,
        )
        assert approved["approved_by_user_id"] == CLINICAL_DIRECTOR_USER_ID
        arch = fx.read_arch(ctx["arch"]["id"])
        assert arch["arch_status"] == "REMAKE_PENDING"
        assert arch["remake_count"] == 1
