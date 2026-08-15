"""Prior authorization cycle: decision rules, uniqueness, expiry/quantity edits,
PA consumption and its compensating restoration."""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data,
    make_plan, make_drug, make_member, make_adjudication_scenario,
    make_pending_pa, make_approved_pa, get_pa,
    submit_claim, create_paid_claim, get_only_rejected_claim, get_claim,
    make_pharmacist_headers, make_member_headers,
)


def test_pa_approve_from_denied_rejected(api, clinical_reviewer_headers):
    """PRD §3.3: "Approval is permitted only from `PENDING` — otherwise
    `ERR_PA_NOT_PENDING`"
    PRD §3.3: "`DENIED` is terminal; so is `CANCELLED`, which an authorization reaches
    only through the plan-retirement cascade of §3.1, from either `PENDING` or
    `APPROVED`."

    Design: Corner/state_machines/pa_approve_from_denied_rejected
    """
    plan = make_plan(name="P-DNY")
    drug = make_drug(ndc="00000-9008", name="Denyon", unit_cost_cents=500,
                     max_daily_dose_units=10)
    member = make_member(plan["id"], external_ref="M-DNY", full_name="Pat Deny")
    pa = make_pending_pa(member["id"], drug["id"], requested_quantity=30)
    validate_success(
        api.deny_prior_authorization(
            pa["id"], {"denial_reason": "insufficient documentation"},
            clinical_reviewer_headers,
        ),
        200,
    )

    res = api.approve_prior_authorization(
        pa["id"], {"approved_quantity": 30, "expires_at": "2026-12-31"},
        clinical_reviewer_headers,
    )
    validate_error(res, "ERR_PA_NOT_PENDING", expected_status=409)
    after = get_pa(pa["id"], clinical_reviewer_headers)
    assert after["status"] == "DENIED"
    assert after["denial_reason"] == "insufficient documentation"
    assert after["approved_quantity"] is None


def test_duplicate_active_pa_rejected(api):
    """PRD §3.3: "At most one live authorization may exist per member-drug pair: if a
    `PENDING` or `APPROVED` authorization already exists for the same `member_id` and
    `drug_id`, the request is rejected with `ERR_DUPLICATE_ACTIVE_PA` (HTTP 409);
    `DENIED` and `CANCELLED` authorizations do not block a fresh request."

    Design: Corner/validations/duplicate_active_pa_rejected
    """
    plan = make_plan(name="P-DPA")
    drug = make_drug(ndc="00000-9022", name="Dupepa", unit_cost_cents=500,
                     max_daily_dose_units=10)
    member = make_member(plan["id"], external_ref="M-DPA", full_name="Pat Duppa")
    pa = make_pending_pa(member["id"], drug["id"], requested_quantity=30)

    res = api.create_prior_authorization(
        {"member_id": member["id"], "drug_id": drug["id"], "requested_quantity": 60},
        make_member_headers(member["id"]),
    )
    validate_error(res, "ERR_DUPLICATE_ACTIVE_PA", expected_status=409)
    after = get_pa(pa["id"])
    assert after["status"] == "PENDING"


class TestPaExpiryBoundary:
    def _expiry_scenario(self):
        scenario = make_adjudication_scenario(
            drug_overrides={"ndc": "00000-9023", "name": "Expirex",
                            "therapeutic_class": "ANTIVIRAL", "unit_cost_cents": 1000,
                            "max_daily_dose_units": 100},
            entry_overrides={"tier": 2, "copay_flat_cents": 500, "pa_required": True},
        )
        pa = make_approved_pa(
            scenario["member"]["id"], scenario["drug"]["id"],
            approved_quantity=60, expires_at="2026-03-01", requested_quantity=60,
        )
        return scenario, pa

    def test_fill_exactly_on_expiry_date_pays(self, api):
        """PRD §3.4: "Sixth, authorization currency: the selected authorization must
        still be usable on the fill date — `expires_at` on or after `fill_date`, with
        equality counting as usable — and if every approved authorization has expired
        before the fill date the edit fails with `ERR_PA_EXPIRED`."

        Design: Corner/validations/pa_expiry_boundary_and_expired_edit
        """
        scenario, pa = self._expiry_scenario()
        claim = validate_success(
            submit_claim(
                scenario["member"]["id"], scenario["drug"]["id"],
                scenario["pharmacy"]["id"], fill_date="2026-03-01",
                quantity=30, days_supply=30,
            ),
            201,
        )
        assert claim["status"] == "PAID", "fill_date == expires_at is inclusive-usable"
        assert claim["pa_id"] == pa["id"]
        pa_after = get_pa(pa["id"])
        assert pa_after["quantity_consumed"] == 30

    def test_fill_after_expiry_rejected_pa_expired(self, api):
        """PRD §3.4: "Sixth, authorization currency: the selected authorization must
        still be usable on the fill date — `expires_at` on or after `fill_date`, with
        equality counting as usable — and if every approved authorization has expired
        before the fill date the edit fails with `ERR_PA_EXPIRED`."
        PRD §3.4: "When any edit fails, the claim is still persisted — now with `status`
        `REJECTED` — and the response is HTTP 422 whose `error_id` is the first failed
        edit in the pinned order; the claim's `reject_reasons` array records every failed
        edit's error identifier, in that same pinned order."

        Design: Corner/validations/pa_expiry_boundary_and_expired_edit
        """
        scenario, pa = self._expiry_scenario()
        member_id, drug_id, pharmacy_id = (
            scenario["member"]["id"], scenario["drug"]["id"], scenario["pharmacy"]["id"],
        )
        # Consume 30 of the 60 approved units on the expiry boundary itself.
        validate_success(
            submit_claim(member_id, drug_id, pharmacy_id, fill_date="2026-03-01",
                         quantity=30, days_supply=30),
            201,
        )
        res = submit_claim(member_id, drug_id, pharmacy_id, fill_date="2026-03-02",
                           quantity=30, days_supply=30)
        validate_error(res, "ERR_PA_EXPIRED", expected_status=422)
        claim = get_only_rejected_claim(member_id)
        assert claim["status"] == "REJECTED"
        assert claim["reject_reasons"] == ["ERR_PA_EXPIRED"]


def test_pa_quantity_exceeded_edit(api):
    """PRD §3.4: "Seventh, authorization quantity: the claim's `quantity` must not exceed
    the selected authorization's remaining quantity (its `approved_quantity` minus its
    `quantity_consumed`), else `ERR_PA_QUANTITY_EXCEEDED`."

    Design: Corner/validations/pa_quantity_exceeded_edit
    """
    scenario = make_adjudication_scenario(
        drug_overrides={"ndc": "00000-9024", "name": "Quantpa",
                        "therapeutic_class": "ANTIVIRAL", "unit_cost_cents": 1000,
                        "max_daily_dose_units": 100},
        entry_overrides={"tier": 2, "copay_flat_cents": 500, "pa_required": True},
    )
    member_id, drug_id, pharmacy_id = (
        scenario["member"]["id"], scenario["drug"]["id"], scenario["pharmacy"]["id"],
    )
    pa = make_approved_pa(member_id, drug_id, approved_quantity=30,
                          expires_at="2026-12-31", requested_quantity=30)

    res = submit_claim(member_id, drug_id, pharmacy_id, fill_date="2026-03-01",
                       quantity=31, days_supply=31)
    validate_error(res, "ERR_PA_QUANTITY_EXCEEDED", expected_status=422)
    claim = get_only_rejected_claim(member_id)
    assert claim["status"] == "REJECTED"
    assert claim["reject_reasons"] == ["ERR_PA_QUANTITY_EXCEEDED"]
    pa_after = get_pa(pa["id"])
    assert pa_after["quantity_consumed"] == 0, "A rejected claim consumes nothing"


class TestClaimRequiresApprovedPa:
    def _pa_scenario(self):
        return make_adjudication_scenario(
            drug_overrides={"ndc": "99999-0001", "name": "Authorex",
                            "therapeutic_class": "BIOLOGIC", "unit_cost_cents": 1000,
                            "max_daily_dose_units": 100},
            entry_overrides={"tier": 3, "copay_flat_cents": 500, "pa_required": True},
        )

    def test_claim_rejected_without_approved_pa(self, api):
        """PRD §3.4: "Fifth, prior authorization presence: if the entry's `pa_required`
        is true, an `APPROVED` authorization must exist for this member and drug, else
        `ERR_PRIOR_AUTH_REQUIRED`"
        PRD §3.4: "When any edit fails, the claim is still persisted — now with `status`
        `REJECTED` — and the response is HTTP 422 whose `error_id` is the first failed
        edit in the pinned order; the claim's `reject_reasons` array records every failed
        edit's error identifier, in that same pinned order."

        Design: Difficulty/cross_entity_state_dependency/claim_payment_requires_approved_pa
        """
        scenario = self._pa_scenario()
        member_id, drug_id, pharmacy_id = (
            scenario["member"]["id"], scenario["drug"]["id"], scenario["pharmacy"]["id"],
        )
        res = submit_claim(member_id, drug_id, pharmacy_id, fill_date="2026-03-01",
                           quantity=30, days_supply=30)
        validate_error(res, "ERR_PRIOR_AUTH_REQUIRED", expected_status=422)
        claim = get_only_rejected_claim(member_id)
        assert claim["status"] == "REJECTED"
        assert claim["reject_reasons"] == ["ERR_PRIOR_AUTH_REQUIRED"]
        assert claim["plan_paid_cents"] == 0

    def test_claim_resubmit_pays_and_consumes_pa(self, api, clinical_reviewer_headers):
        """PRD §3.3: "When a paid claim consumed an authorization — visible as the
        claim's `pa_id` — the claim's `quantity` is added to the authorization's
        `quantity_consumed`, and reversal of that claim subtracts the same quantity back
        out, returning consumption to its pre-claim value."
        PRD §3.7: "When the edits now pass, `reject_reasons` is cleared, the response is
        200, and the same payment cascade as a fresh adjudication posts — accumulators,
        card debit, authorization consumption, pharmacy ledger, and rebate tag — moving
        the claim to `PAID`."

        Design: Difficulty/cross_entity_state_dependency/claim_payment_requires_approved_pa
        """
        scenario = self._pa_scenario()
        member_id, drug_id, pharmacy_id = (
            scenario["member"]["id"], scenario["drug"]["id"], scenario["pharmacy"]["id"],
        )
        res = submit_claim(member_id, drug_id, pharmacy_id, fill_date="2026-03-01",
                           quantity=30, days_supply=30)
        validate_error(res, "ERR_PRIOR_AUTH_REQUIRED", expected_status=422)
        rejected = get_only_rejected_claim(member_id)

        pa = make_approved_pa(member_id, drug_id, approved_quantity=60,
                              expires_at="2026-12-31", requested_quantity=60,
                              note="please approve")
        paid = validate_success(
            api.resubmit_claim(rejected["id"], {}, scenario["pharmacist_headers"]), 200
        )
        assert paid["status"] == "PAID"
        assert paid["pa_id"] == pa["id"], "The consumed APPROVED PA must be stamped"
        assert paid["member_pays_cents"] == 500
        assert paid["plan_paid_cents"] == 29500
        assert paid["resubmit_count"] == 1
        pa_after = get_pa(pa["id"], clinical_reviewer_headers)
        assert pa_after["quantity_consumed"] == 30, "60 approved minus 30 consumed"


class TestPaConsumptionCompensation:
    def _consumption_scenario(self):
        scenario = make_adjudication_scenario(
            drug_overrides={"ndc": "99999-0002", "name": "Authorex-B",
                            "therapeutic_class": "BIOLOGIC", "unit_cost_cents": 1000,
                            "max_daily_dose_units": 100},
            entry_overrides={"tier": 3, "copay_flat_cents": 500, "pa_required": True},
        )
        pa = make_approved_pa(
            scenario["member"]["id"], scenario["drug"]["id"],
            approved_quantity=60, expires_at="2026-12-31", requested_quantity=60,
        )
        return scenario, pa

    def test_pa_consumption_after_payment(self, api, clinical_reviewer_headers):
        """PRD §3.3: "When a paid claim consumed an authorization — visible as the
        claim's `pa_id` — the claim's `quantity` is added to the authorization's
        `quantity_consumed`, and reversal of that claim subtracts the same quantity back
        out, returning consumption to its pre-claim value."

        Design: Difficulty/compensating_invariant/pa_quantity_consumption_restored_on_reversal
        """
        scenario, pa = self._consumption_scenario()
        claim = create_paid_claim(
            scenario["member"]["id"], scenario["drug"]["id"],
            scenario["pharmacy"]["id"], fill_date="2026-03-01",
            quantity=30, days_supply=30,
        )
        assert claim["pa_id"] == pa["id"]
        pa_after = get_pa(pa["id"], clinical_reviewer_headers)
        assert pa_after["quantity_consumed"] == 30
        assert pa_after["approved_quantity"] == 60

    def test_pa_consumption_restored_after_reversal(self, api, clinical_reviewer_headers):
        """PRD §3.3: "When a paid claim consumed an authorization — visible as the
        claim's `pa_id` — the claim's `quantity` is added to the authorization's
        `quantity_consumed`, and reversal of that claim subtracts the same quantity back
        out, returning consumption to its pre-claim value."
        PRD §3.7: "if `pa_id` names an authorization, the claim's `quantity` is
        subtracted from its `quantity_consumed`"

        Design: Difficulty/compensating_invariant/pa_quantity_consumption_restored_on_reversal
        """
        scenario, pa = self._consumption_scenario()
        claim = create_paid_claim(
            scenario["member"]["id"], scenario["drug"]["id"],
            scenario["pharmacy"]["id"], fill_date="2026-03-01",
            quantity=30, days_supply=30,
        )
        validate_success(
            api.reverse_claim(claim["id"], {"reversal_reason": "not picked up"},
                              scenario["pharmacist_headers"]),
            200,
        )
        pa_after = get_pa(pa["id"], clinical_reviewer_headers)
        assert pa_after["quantity_consumed"] == 0, (
            f"Compensating invariant: consumption returns to the pre-claim value 0, "
            f"got {pa_after['quantity_consumed']}"
        )
        assert pa_after["approved_quantity"] == 60
        claim_after = get_claim(claim["id"], scenario["pharmacist_headers"])
        assert claim_after["status"] == "REVERSED"
