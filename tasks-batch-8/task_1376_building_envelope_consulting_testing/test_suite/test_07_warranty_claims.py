"""Warranty claims: anomaly gate, escalation window, decision cycle, RBAC."""
from datetime import datetime, timedelta

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    create_active_engagement,
    create_anomaly,
    create_assembly,
    create_completed_survey,
    create_warranty_claim,
    get_engagement,
    make_manufacturer_rep_headers,
    manufacturer_acknowledge,
    manufacturer_decide,
    set_clock,
    setup_verified_anomaly,
    validate_error,
    validate_paginated,
    validate_success,
    verify_anomaly,
)

P = TEST_USERS["principal_headers"]
C = TEST_USERS["consultant_headers"]
MR = TEST_USERS["manufacturer_rep_headers"]


def _parse_ts(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


class TestClaimCreateRequiresAnomalyVerified:

    def test_claim_against_open_anomaly_rejected(self):
        """PRD §3.8: "A `Consultant` files a claim by naming the `anomaly_id`
        it pursues — the referenced anomaly must be `VERIFIED`, otherwise
        `ERR_ANOMALY_NOT_VERIFIED`..."
        PRD §3.8: "Claim lists can be filtered by `anomaly_id`."

        Design: Difficulty/cross_entity_state_dependency/claim_create_requires_anomaly_verified
        """
        eng = create_active_engagement(name="E14")
        asm = create_assembly(eng["id"], tag="W14", assembly_type="ROOFING",
                              design_u_factor=0.8,
                              required_airtightness_lps_m2=3.0)
        srv = create_completed_survey(eng["id"], asm["id"])
        an = create_anomaly(eng["id"], anomaly_type="WATER_INGRESS",
                            severity="HIGH", description="leak",
                            survey_id=srv["id"])
        assert an["status"] == "OPEN"
        resp = api_client.create_warranty_claim(
            eng["id"],
            {"anomaly_id": an["id"], "manufacturer_name": "ACME",
             "claimed_amount_cents": 100000},
            C,
        )
        validate_error(resp, ApiErrorId.ERR_ANOMALY_NOT_VERIFIED)
        claims, meta = validate_paginated(api_client.list_warranty_claims(
            eng["id"], C, params={"anomaly_id": an["id"]}))
        assert meta["total_count"] == 0
        assert claims == []

    def test_claim_against_verified_anomaly_succeeds_with_response_window(self):
        """PRD §3.8: "Filing stamps `filed_at` with the current reading of the
        logical clock, computes `response_due_at` as exactly thirty days after
        `filed_at`, sets `recovered_amount_cents` to 0 while the claim is
        pending, and opens the claim with its `claim_status` at `FILED`."
        PRD §2.4: "At server startup, before any clock-setting call has been
        made, the logical clock reads exactly `2026-08-01T00:00:00Z`..."

        Design: Difficulty/cross_entity_state_dependency/claim_create_requires_anomaly_verified
        """
        eng, asm, srv, an = setup_verified_anomaly(
            severity="HIGH", name="E14B", anomaly_type="WATER_INGRESS")
        claim = create_warranty_claim(eng["id"], an["id"],
                                      manufacturer_name="ACME",
                                      claimed_amount_cents=100000)
        assert claim["claim_status"] == "FILED"
        assert claim["recovered_amount_cents"] == 0
        filed_at = _parse_ts(claim["filed_at"])
        due_at = _parse_ts(claim["response_due_at"])
        assert filed_at == _parse_ts("2026-08-01T00:00:00Z")
        assert due_at - filed_at == timedelta(days=30)


class TestEscalationWindowPriority:

    def _setup_two_claims(self):
        """C1 DENIED (window not yet elapsed); C2 UNDER_MANUFACTURER_REVIEW."""
        eng = create_active_engagement(name="E10")
        asm = create_assembly(eng["id"], tag="W10", assembly_type="MASONRY",
                              design_u_factor=1.1,
                              required_airtightness_lps_m2=2.5)
        srv = create_completed_survey(eng["id"], asm["id"],
                                      survey_date="2026-08-20")
        an1 = create_anomaly(eng["id"], anomaly_type="WATER_INGRESS",
                             severity="HIGH", description="leak",
                             survey_id=srv["id"])
        an2 = create_anomaly(eng["id"], anomaly_type="AIR_LEAKAGE",
                             severity="MEDIUM", description="draft",
                             survey_id=srv["id"])
        verify_anomaly(eng["id"], an1["id"])
        verify_anomaly(eng["id"], an2["id"])
        set_clock("2026-09-01T00:00:00Z")
        c1 = create_warranty_claim(eng["id"], an1["id"],
                                   claimed_amount_cents=100000)
        c2 = create_warranty_claim(eng["id"], an2["id"],
                                   claimed_amount_cents=200000)
        manufacturer_acknowledge(eng["id"], c1["id"])
        manufacturer_decide(eng["id"], c1["id"], "DENIED")
        manufacturer_acknowledge(eng["id"], c2["id"])
        return eng, c1, c2

    def test_denied_claim_escalate_before_window_elapsed_rejected(self):
        """PRD §3.8: "A `Consultant` may escalate a claim from `DENIED` to
        `ESCALATED`, but only after the manufacturer's response window has
        fully elapsed: the logical clock must have reached the claim's
        `response_due_at` — the thirtieth day after filing — or the escalation
        is rejected with `ERR_ESCALATION_WINDOW_NOT_ELAPSED` (HTTP 409)."

        Design: Difficulty/priority_pair_validation_conflict/temporal_beats_referential_on_late_escalate_of_unacknowledged_claim
        """
        eng, c1, _ = self._setup_two_claims()
        # Filed at 2026-09-01, due 2026-10-01; clock still at 2026-09-01.
        resp = api_client.escalate_claim(eng["id"], c1["id"], C)
        validate_error(resp, ApiErrorId.ERR_ESCALATION_WINDOW_NOT_ELAPSED)
        after = validate_success(
            api_client.get_warranty_claim(eng["id"], c1["id"], C), 200)
        assert after["claim_status"] == "DENIED"

    def test_escalate_in_wrong_state_fails_before_window_check(self):
        """PRD §2.11: "When a request violates more than one rule, the error it
        receives is determined by a fixed evaluation order rather than by
        whichever check happens to run first." — tier 7 lists
        "`ERR_CLAIM_NOT_ACTIONABLE`" among the target-entity state
        preconditions, ahead of tier 9's temporal window conditions, which
        include `ERR_ESCALATION_WINDOW_NOT_ELAPSED`.
        PRD §3.8: "A `Consultant` may escalate a claim from `DENIED` to
        `ESCALATED`..."

        Design: Difficulty/priority_pair_validation_conflict/temporal_beats_referential_on_late_escalate_of_unacknowledged_claim
        """
        eng, _, c2 = self._setup_two_claims()
        # Past the 30-day window, but the claim is UNDER_MANUFACTURER_REVIEW.
        set_clock("2026-10-02T00:00:00Z")
        resp = api_client.escalate_claim(eng["id"], c2["id"], C)
        validate_error(resp, ApiErrorId.ERR_CLAIM_NOT_ACTIONABLE)
        after = validate_success(
            api_client.get_warranty_claim(eng["id"], c2["id"], C), 200)
        assert after["claim_status"] == "UNDER_MANUFACTURER_REVIEW"


class TestWarrantyClaimCycleAndDecisionErrors:

    def _setup_denied_claim_window_elapsed(self):
        eng, asm, srv, an = setup_verified_anomaly(
            severity="LOW", name="EW", anomaly_type="WATER_INGRESS")
        set_clock("2026-09-01T00:00:00Z")
        claim = create_warranty_claim(eng["id"], an["id"],
                                      claimed_amount_cents=500000)
        manufacturer_acknowledge(eng["id"], claim["id"])
        manufacturer_decide(eng["id"], claim["id"], "DENIED")
        set_clock("2026-10-02T00:00:00Z")
        return eng, claim

    def test_warranty_claim_cycle_denied_escalated_denied_again(self):
        """PRD §3.8: "After escalation the manufacturer decides again by the
        same decision action, and the cycle from `DENIED` to `ESCALATED` and
        back to `DENIED` may repeat."

        Design: Corner/state_machines/warranty_claim_cycle_denied_escalated_denied_again
        """
        eng, claim = self._setup_denied_claim_window_elapsed()
        resp = api_client.escalate_claim(eng["id"], claim["id"], C)
        data = validate_success(resp, 200)
        assert data["claim_status"] == "ESCALATED"

        resp = api_client.manufacturer_decide(eng["id"], claim["id"],
                                              {"decision": "DENIED"}, MR)
        data = validate_success(resp, 200)
        assert data["claim_status"] == "DENIED"

        # The window has already elapsed, so a second escalation succeeds.
        resp = api_client.escalate_claim(eng["id"], claim["id"], C)
        data = validate_success(resp, 200)
        assert data["claim_status"] == "ESCALATED"

    def test_claim_decide_invalid_payload_and_state(self):
        """PRD §3.8: "The decision action carries a `decision` payload of
        either `ACCEPTED` or `DENIED` and moves the claim accordingly, and it
        is valid from either `UNDER_MANUFACTURER_REVIEW` or `ESCALATED`; a
        decision attempted from any other state, or carrying any other
        `decision` value, is rejected with `ERR_CLAIM_NOT_ACTIONABLE`
        (HTTP 409)."

        Design: Corner/errors/claim_decide_invalid_payload_and_state
        """
        eng = create_active_engagement(name="ECD")
        asm = create_assembly(eng["id"], tag="ACD", assembly_type="MASONRY",
                              design_u_factor=1.0,
                              required_airtightness_lps_m2=2.0)
        srv = create_completed_survey(eng["id"], asm["id"])
        an1 = create_anomaly(eng["id"], anomaly_type="MOISTURE_TRAP",
                             severity="LOW", description="a",
                             survey_id=srv["id"])
        an2 = create_anomaly(eng["id"], anomaly_type="MOISTURE_TRAP",
                             severity="LOW", description="b",
                             survey_id=srv["id"])
        verify_anomaly(eng["id"], an1["id"])
        verify_anomaly(eng["id"], an2["id"])
        c1 = create_warranty_claim(eng["id"], an1["id"])
        c2 = create_warranty_claim(eng["id"], an2["id"])
        manufacturer_acknowledge(eng["id"], c1["id"])

        resp = api_client.manufacturer_decide(eng["id"], c1["id"],
                                              {"decision": "MAYBE"}, MR)
        validate_error(resp, ApiErrorId.ERR_CLAIM_NOT_ACTIONABLE)
        resp = api_client.manufacturer_decide(eng["id"], c2["id"],
                                              {"decision": "ACCEPTED"}, MR)
        validate_error(resp, ApiErrorId.ERR_CLAIM_NOT_ACTIONABLE)
        after = validate_success(
            api_client.get_warranty_claim(eng["id"], c1["id"], C), 200)
        assert after["claim_status"] == "UNDER_MANUFACTURER_REVIEW"

    def test_manufacturer_rep_cannot_escalate(self):
        """PRD §2.1: "An attempt to perform an operation outside the caller's
        role is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
        PRD §4: the escalate endpoint row lists `Consultant` as its only
        authorized role.
        PRD §2.11: "Role permission for the invoked endpoint — otherwise
        `ERR_FORBIDDEN_ROLE`." precedes state and temporal checks.

        Design: Corner/rbac/manufacturer_rep_cannot_escalate
        """
        eng, claim = self._setup_denied_claim_window_elapsed()
        resp = api_client.escalate_claim(
            eng["id"], claim["id"],
            make_manufacturer_rep_headers("mfr-user-1"))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
        after = validate_success(
            api_client.get_warranty_claim(eng["id"], claim["id"], C), 200)
        assert after["claim_status"] == "DENIED"
