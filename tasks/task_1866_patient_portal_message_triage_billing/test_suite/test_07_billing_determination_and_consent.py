"""E-visit determination: tier schedule, consent pinning, dedupe window."""
from test_helpers import (
    ApiErrorId,
    FEE_99421_CENTS,
    FEE_99422_CENTS,
    assert_consent_record,
    assert_evisit_claim,
    chargeable_message,
    determine_billing_payload,
    message_in_review_with_minutes,
    patient_headers,
    provider_pool_practice,
    resolved_chargeable_message,
    staff_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestTierCodeFeeSelection:
    def test_evisit_claim_tier_code_and_fee(self, api):
        """PRD §3.6: "Eleven through twenty minutes, again inclusive at both
        ends, selects `CPT_99422` at 8000 cents."
        PRD §3.6: "Under `COPAY`, `patient_responsibility_cents` is the lesser
        of the patient's `copay_cents` and the claim's `fee_cents`."

        Twelve provider clinical minutes select CPT_99422 at 8000 cents; the
        COPAY patient's responsibility is min(2500, 8000) = 2500.

        Design: Difficulty/combinatorial_formula/evisit_tier_code_fee_selection
        """
        ctx = provider_pool_practice()
        scn = ctx["scn"]
        msg, _consent = resolved_chargeable_message(ctx, minutes=12)
        assert msg["billing_disposition"] == "CHARGEABLE"
        assert msg["status"] == "RESOLVED"

        claim = scn.create_claim(msg["id"], ctx["provider"]["id"],
                                 ctx["biller"])
        assert_evisit_claim(claim)
        assert claim["code"] == "CPT_99422", (
            f"12 minutes falls in the [11, 20] tier, got {claim['code']}"
        )
        assert claim["fee_cents"] == 8000
        assert claim["patient_responsibility_cents"] == 2500, (
            "COPAY responsibility is the lesser of copay_cents and fee_cents"
        )
        assert claim["status"] == "DRAFT"

    def test_evisit_consent_pins_disclosed_code_and_fee(self, api):
        """PRD §3.6: "On success, the message moves to `PENDING_CONSENT`,
        `billing_disposition` becomes `BILLABLE_CANDIDATE`, any prior `GRANTED`
        or `DECLINED` consent is superseded, and a fresh `ConsentRecord` is
        created in `REQUESTED` status with `patient_id` copied from the message,
        `requested_at` stamped from the logical clock, and — crucially —
        `disclosed_code` and `disclosed_fee_cents` pinned to the e-visit tier at
        the current `clinical_minutes_total`."

        Twelve minutes at determination time pin CPT_99422 / 8000 on the
        consent.

        Design: Difficulty/combinatorial_formula/evisit_tier_code_fee_selection
        """
        ctx = provider_pool_practice()
        scn = ctx["scn"]
        msg = message_in_review_with_minutes(ctx, minutes=12)
        scn.determine_billing(msg["id"], ctx["provider"], "BILLABLE_CANDIDATE")
        consent = scn.find_consent(msg["id"], status="REQUESTED")
        assert_consent_record(consent)
        assert consent["disclosed_code"] == "CPT_99422"
        assert consent["disclosed_fee_cents"] == 8000
        assert consent["patient_id"] == ctx["patient"]["id"]

        pending = scn.get_message(msg["id"])
        assert pending["status"] == "PENDING_CONSENT"
        assert pending["billing_disposition"] == "BILLABLE_CANDIDATE"

        scn.respond_consent(consent["id"], ctx["patient"], "GRANTED")
        after = scn.get_message(msg["id"])
        assert after["status"] == "IN_REVIEW"
        assert after["billing_disposition"] == "CHARGEABLE"


class TestTierBoundary:
    def test_tier_boundary_10_minutes_selects_99421(self, api):
        """PRD §3.6: "Five through ten minutes — both bounds inclusive —
        selects `CPT_99421` with a 5000-cent fee."
        PRD §3.6: "Boundary values belong to the band containing them: ten
        minutes yields `CPT_99421`, eleven yields `CPT_99422`, twenty stays
        `CPT_99422`, and twenty-one moves to `CPT_99423`."

        Ten provider minutes (6 + 4) is the inclusive top of the first tier.

        Design: Difficulty/boundary_precision_check/evisit_tier_boundary_10_vs_11_minutes
        """
        ctx = provider_pool_practice()
        scn = ctx["scn"]
        msg = message_in_review_with_minutes(ctx, minutes=0, urgency="ROUTINE")
        scn.log_time(msg["id"], ctx["provider"], 6, entry_kind="CLINICAL_REVIEW")
        scn.log_time(msg["id"], ctx["provider"], 4, entry_kind="CLINICAL_REVIEW")
        assert scn.get_message(msg["id"])["clinical_minutes_total"] == 10
        scn.determine_billing(msg["id"], ctx["provider"], "BILLABLE_CANDIDATE")
        consent = scn.find_consent(msg["id"], status="REQUESTED")
        scn.respond_consent(consent["id"], ctx["patient"], "GRANTED")
        scn.complete(msg["id"], ctx["provider"], summary="done A")
        claim = scn.create_claim(msg["id"], ctx["provider"]["id"],
                                 ctx["biller"])
        assert claim["code"] == "CPT_99421"
        assert claim["fee_cents"] == 5000

    def test_tier_boundary_11_minutes_selects_99422(self, api):
        """PRD §3.6: "Eleven through twenty minutes, again inclusive at both
        ends, selects `CPT_99422` at 8000 cents."
        PRD §3.6: "Boundary values belong to the band containing them: ten
        minutes yields `CPT_99421`, eleven yields `CPT_99422`, twenty stays
        `CPT_99422`, and twenty-one moves to `CPT_99423`."

        Eleven provider minutes (6 + 5) is the inclusive bottom of the second
        tier — one minute above the ten-minute case moves the code.

        Design: Difficulty/boundary_precision_check/evisit_tier_boundary_10_vs_11_minutes
        """
        ctx = provider_pool_practice()
        scn = ctx["scn"]
        msg = message_in_review_with_minutes(ctx, minutes=0, urgency="ROUTINE")
        scn.log_time(msg["id"], ctx["provider"], 6, entry_kind="CLINICAL_REVIEW")
        scn.log_time(msg["id"], ctx["provider"], 5, entry_kind="CLINICAL_REVIEW")
        assert scn.get_message(msg["id"])["clinical_minutes_total"] == 11
        scn.determine_billing(msg["id"], ctx["provider"], "BILLABLE_CANDIDATE")
        consent = scn.find_consent(msg["id"], status="REQUESTED")
        scn.respond_consent(consent["id"], ctx["patient"], "GRANTED")
        scn.complete(msg["id"], ctx["provider"], summary="done B")
        claim = scn.create_claim(msg["id"], ctx["provider"]["id"],
                                 ctx["biller"])
        assert claim["code"] == "CPT_99422"
        assert claim["fee_cents"] == 8000


class TestClinicalMinutesInputSet:
    def test_clinical_minutes_input_set_filtering(self, api):
        """PRD §3.4: "Each new entry recomputes the message's
        `clinical_minutes_total`, which sums `minutes` over the message's
        `CLINICAL_REVIEW` entries whose author has `staff_type` `PROVIDER`;
        `ADMINISTRATIVE` entries and clinical-review entries by non-providers
        are excluded, with no time window."

        A nurse's 6-minute clinical entry and the provider's 3-minute
        administrative entry are both excluded; only the provider's 6-minute
        clinical entry counts.

        Design: Corner/calculations/clinical_minutes_input_set_filtering
        """
        ctx = provider_pool_practice(with_biller=False)
        scn = ctx["scn"]
        msg = message_in_review_with_minutes(ctx, minutes=0, urgency="ROUTINE")
        scn.log_time(msg["id"], ctx["provider"], 6,
                     entry_kind="CLINICAL_REVIEW")
        scn.log_time(msg["id"], ctx["nurse"], 4, entry_kind="CLINICAL_REVIEW")
        scn.log_time(msg["id"], ctx["provider"], 3, entry_kind="ADMINISTRATIVE")

        after = scn.get_message(msg["id"])
        assert after["clinical_minutes_total"] == 6, (
            "only the provider's CLINICAL_REVIEW minutes count, got "
            f"{after['clinical_minutes_total']}"
        )
        entries, meta = validate_paginated(
            api_list_time_entries(api, scn, msg["id"]))
        assert meta["total_count"] == 3, "all three entries must exist"


class TestConsentLifecycle:
    def test_consent_respond_twice_rejected(self, api):
        """PRD §3.6: "Responding to their own `REQUESTED` consent — another
        patient's consent fails with `ERR_PATIENT_OWNERSHIP_MISMATCH`, and an
        already-answered record with `ERR_CONSENT_ALREADY_RESPONDED` — carries a
        `decision` of `GRANTED` or `DECLINED`."

        Design: Corner/state_machines/consent_respond_twice_rejected
        """
        ctx = provider_pool_practice()
        scn = ctx["scn"]
        msg, consent = chargeable_message(ctx, minutes=8)
        assert consent["status"] == "GRANTED"
        assert consent.get("responded_at") is not None, (
            "granting stamps responded_at"
        )
        assert msg["status"] == "IN_REVIEW"
        assert msg["billing_disposition"] == "CHARGEABLE"

        resp = api.respond_consent(consent["id"], {"decision": "DECLINED"},
                                   patient_headers(ctx["patient"]))
        validate_error(resp, ApiErrorId.ERR_CONSENT_ALREADY_RESPONDED)
        after = scn.find_consent(msg["id"])
        assert after["status"] == "GRANTED", (
            "a rejected second response must not change the consent"
        )

    def test_consent_reverse_lookup_by_message(self, api):
        """PRD §3.6: "a fresh `ConsentRecord` is created in `REQUESTED` status
        with `patient_id` copied from the message, `requested_at` stamped from
        the logical clock, and — crucially — `disclosed_code` and
        `disclosed_fee_cents` pinned to the e-visit tier at the current
        `clinical_minutes_total`."
        PRD §3.6: "Consent lists support filtering by `message_id`,
        `patient_id`, and `status`."

        Design: Corner/endpoints/consent_reverse_lookup_by_message
        """
        ctx = provider_pool_practice(with_biller=False)
        scn = ctx["scn"]
        msg = message_in_review_with_minutes(ctx, minutes=8)
        scn.determine_billing(msg["id"], ctx["provider"], "BILLABLE_CANDIDATE")

        data, meta = validate_paginated(
            api.list_consent_records(scn.admin,
                                     params={"message_id": msg["id"]}))
        assert meta["total_count"] == 1
        consent = data[0]
        assert_consent_record(consent)
        assert consent["status"] == "REQUESTED"
        assert consent["disclosed_code"] == "CPT_99421"
        assert consent["disclosed_fee_cents"] == FEE_99421_CENTS
        assert consent["patient_id"] == ctx["patient"]["id"]

        after = scn.get_message(msg["id"])
        assert after["status"] == "PENDING_CONSENT"
        assert after["billing_disposition"] == "BILLABLE_CANDIDATE"


class TestEvisitDedupeWindow:
    def test_evisit_dedupe_168h_window_boundary(self, api):
        """PRD §3.6: "no other message of the same patient may hold
        `billing_disposition` `CHARGEABLE` with a `received_at` inside the
        trailing 168-hour window ending at this message's `received_at` — the
        lower bound is exclusive, so another chargeable message received exactly
        168 hours earlier does not block, while one received any time after that
        moment, up to and including this message's own receipt instant, does —
        else `ERR_EVISIT_DUPLICATE_WITHIN_7_DAYS`".

        M1 became CHARGEABLE at 2026-08-03T10:00:00Z. M2, received exactly 168
        hours later, determines successfully; M3, received one second inside the
        window, is rejected.

        Design: Corner/calculations/evisit_dedupe_168h_window_boundary
        """
        ctx = provider_pool_practice(with_biller=False)
        scn = ctx["scn"]

        # M1: received 2026-08-03T10:00:00Z, driven to CHARGEABLE (stays
        # IN_REVIEW; only the disposition matters to the dedupe rule).
        m1, _consent = chargeable_message(ctx, minutes=6)

        # M3: received one second inside M1's trailing window.
        scn.set_clock("2026-08-10T09:59:59Z")
        m3 = message_in_review_with_minutes(ctx, minutes=5, urgency="ROUTINE",
                                            subject="M3")
        # M2: received exactly 168 hours after M1 — the exclusive lower bound.
        scn.set_clock("2026-08-10T10:00:00Z")
        m2 = message_in_review_with_minutes(ctx, minutes=5, urgency="ROUTINE",
                                            subject="M2")

        resp_ok = api.determine_billing(
            m2["id"],
            determine_billing_payload("BILLABLE_CANDIDATE",
                                      scn.get_message(m2["id"])["version"]),
            staff_headers(ctx["provider"]))
        ok = validate_success(resp_ok, 200)
        assert ok["status"] == "PENDING_CONSENT", (
            "exactly 168 hours earlier is outside the exclusive lower bound"
        )

        resp_blocked = api.determine_billing(
            m3["id"],
            determine_billing_payload("BILLABLE_CANDIDATE",
                                      scn.get_message(m3["id"])["version"]),
            staff_headers(ctx["provider"]))
        validate_error(resp_blocked,
                       ApiErrorId.ERR_EVISIT_DUPLICATE_WITHIN_7_DAYS)


class TestDisclosedFeeCeiling:
    def test_disclosed_fee_ceiling_and_requote_recovery(self, api):
        """PRD §3.6: "Those disclosed values are version-pinned: later minute
        accrual does not rewrite what the patient was told, though it constrains
        the claim at submit time."
        PRD §3.6: "the computed `fee_cents` must not exceed the
        `disclosed_fee_cents` on the message's granted, non-superseded consent,
        else `ERR_DISCLOSED_FEE_EXCEEDED`."
        PRD §3.6: "On success, the message moves to `PENDING_CONSENT`,
        `billing_disposition` becomes `BILLABLE_CANDIDATE`, any prior `GRANTED`
        or `DECLINED` consent is superseded, and a fresh `ConsentRecord` is
        created in `REQUESTED` status".

        Consent pins 5000 cents at 8 minutes; 10 more minutes make the computed
        fee 8000, so claim creation fails until a re-determination supersedes
        the old consent and re-discloses 8000.

        Design: Corner/calculations/disclosed_fee_ceiling_and_requote_recovery
        """
        ctx = provider_pool_practice()
        scn = ctx["scn"]
        provider = ctx["provider"]

        msg = message_in_review_with_minutes(ctx, minutes=8)
        scn.determine_billing(msg["id"], provider, "BILLABLE_CANDIDATE")
        consent1 = scn.find_consent(msg["id"], status="REQUESTED")
        assert consent1["disclosed_fee_cents"] == FEE_99421_CENTS
        scn.respond_consent(consent1["id"], ctx["patient"], "GRANTED")

        # Ten more provider minutes while the message is back IN_REVIEW.
        scn.log_time(msg["id"], provider, 10, entry_kind="CLINICAL_REVIEW")
        scn.complete(msg["id"], provider, summary="extended review")

        resp_blocked = api.create_evisit_claim(
            {"message_id": msg["id"],
             "rendering_provider_id": provider["id"]},
            staff_headers(ctx["biller"]))
        validate_error(resp_blocked, ApiErrorId.ERR_DISCLOSED_FEE_EXCEEDED)

        # Recovery: patient reply reopens; re-triage, re-claim, re-determine.
        scn.reply(msg["id"], patient_headers(ctx["patient"]),
                  body="one more symptom")
        scn.triage(msg["id"], ctx["nurse"], "URGENT", "CLINICAL",
                   ctx["pool"]["id"])
        scn.assign(msg["id"], ctx["nurse"], staff_id=provider["id"])
        scn.start_review(msg["id"], provider)
        scn.determine_billing(msg["id"], provider, "BILLABLE_CANDIDATE")

        consent1_after = validate_success(
            api.get_consent_record(consent1["id"], scn.admin), 200)
        assert consent1_after["status"] == "SUPERSEDED", (
            "re-determination must supersede the previously GRANTED consent"
        )
        consent2 = scn.find_consent(msg["id"], status="REQUESTED")
        assert consent2["disclosed_code"] == "CPT_99422"
        assert consent2["disclosed_fee_cents"] == FEE_99422_CENTS, (
            "the re-quote must disclose the tier at the current 18 minutes"
        )

        scn.respond_consent(consent2["id"], ctx["patient"], "GRANTED")
        scn.complete(msg["id"], provider, summary="re-reviewed")
        claim = scn.create_claim(msg["id"], provider["id"], ctx["biller"])
        assert claim["code"] == "CPT_99422"
        assert claim["fee_cents"] == 8000


def api_list_time_entries(api, scn, message_id):
    return api.list_time_entries(scn.admin, params={"message_id": message_id})
