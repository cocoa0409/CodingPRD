"""Validation pipeline precedence pairs (PRD §2.8)."""
from test_helpers import (
    ADMIN,
    BILLING,
    SCHED,
    ApiErrorId,
    all_tefra_steps_false,
    all_tefra_steps_true,
    create_case,
    create_crna,
    create_fee_schedule,
    create_physician,
    create_published_roster,
    create_roster,
    create_site,
    get_success_data,
    make_crna_headers,
    make_physician_headers,
    propose_and_confirm,
    run_case_clock,
    setup_completed_solo_case,
    setup_site_fee_roster,
    validate_error,
    api_client,
)


class TestDuplicateClaimBeatsChargeMax:
    def _setup_two_draft_claims_over_max(self, api):
        """Two DRAFT claims for the same (case, provider); first marked READY;
        contracted max amended below both claims' charge."""
        site, fee, roster = setup_site_fee_roster(
            procedure_code="P500", base_units=5, scheduled_day_end_minute=1200)
        physician = create_physician("Dr. Avery")
        case = create_case(roster["id"], procedure_code="P500",
                           scheduled_start_minute=540, scheduled_end_minute=600)
        propose_and_confirm(case["id"], physician["id"], "ANESTHESIOLOGIST")
        run_case_clock(case["id"], "2026-08-10T09:00:00Z",
                       "2026-08-10T10:00:00Z")
        get_success_data(api.complete_case(case["id"], SCHED))
        claims = get_success_data(api.list_claims(SCHED, params={"case_id": case["id"]}))
        claims = claims if isinstance(claims, list) else claims["data"]
        first = claims[0]
        # 60 actual min -> 9.0 units x 8000 = 72000 charge on the auto claim.
        assert first["charge_cents"] == 72000
        # Manual duplicate DRAFT (tolerated at creation).
        second = get_success_data(api.create_claim(
            {"case_id": case["id"], "provider_id": physician["id"]}, BILLING))
        get_success_data(api.mark_claim_ready(first["id"], BILLING))
        # Amend the contracted max below 72000 so BOTH violations now hold for
        # the second claim's mark-ready.
        get_success_data(api.update_fee_schedule(
            fee["id"], {"contracted_max_cents": 50000}, ADMIN))
        return first, second

    def test_referential_duplicate_check_precedes_fiscal_check(self, api):
        """PRD §3.7: "first checks that no *other* claim for the same
        `case_id` and `provider_id` already sits in `READY`, `SUBMITTED`, or
        `PAID` (violations are `ERR_DUPLICATE_CLAIM`) and then that
        `charge_cents` does not exceed the procedure's `contracted_max_cents`
        (violations are `ERR_CHARGE_EXCEEDS_MAX`, HTTP 402) — the referential
        duplicate check deliberately precedes the fiscal check."

        Design: Difficulty/priority_pair_validation_conflict/duplicate_claim_beats_charge_max
        """
        first, second = self._setup_two_draft_claims_over_max(api)
        resp = api.mark_claim_ready(second["id"], BILLING)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_CLAIM)
        after = get_success_data(api.get_claim(second["id"], BILLING))
        assert after["status"] == "DRAFT", "rejected mark-ready leaves the claim DRAFT"

    def test_duplicate_error_is_409_not_402(self, api):
        """PRD §5: `ERR_DUPLICATE_CLAIM` maps to HTTP 409 while
        `ERR_CHARGE_EXCEEDS_MAX` maps to HTTP 402; PRD §3.7: "the referential
        duplicate check deliberately precedes the fiscal check."

        Design: Difficulty/priority_pair_validation_conflict/duplicate_claim_beats_charge_max
        """
        first, second = self._setup_two_draft_claims_over_max(api)
        resp = api.mark_claim_ready(second["id"], BILLING)
        assert resp.status_code == 409, (
            f"duplicate guard must surface 409, not the fiscal 402; got "
            f"{resp.status_code}: {resp.text}")
        body = resp.json()
        assert body["data"]["error_id"] == "ERR_DUPLICATE_CLAIM"


class TestOwnershipMismatchBeatsTefraIncomplete:
    def test_non_owner_submit_gets_ownership_error(self, api):
        """PRD §2.8: "**TEFRA completeness** — the seven-step check,
        `ERR_TEFRA_STEPS_INCOMPLETE` (HTTP 422), evaluated after ownership and
        state: a non-owner submitting an incomplete attestation receives
        `ERR_OWNERSHIP_MISMATCH`, not the TEFRA error."

        Design: Difficulty/priority_pair_validation_conflict/ownership_mismatch_beats_tefra_incomplete
        """
        site, fee, roster = setup_site_fee_roster(required_primary_slots=0,
                                                  scheduled_day_end_minute=1020)
        director = create_physician("Dr. Direct")
        peer = create_physician("Dr. Peer")
        case = create_case(roster["id"], scheduled_start_minute=540,
                           scheduled_end_minute=600)
        att = get_success_data(api.create_attestation(
            {"case_id": case["id"], "physician_id": director["id"]}, SCHED))
        resp = api.submit_attestation(att["id"], all_tefra_steps_false(),
                                      make_physician_headers(peer["id"]))
        validate_error(resp, ApiErrorId.ERR_OWNERSHIP_MISMATCH)
        after = get_success_data(api.get_attestation(att["id"], SCHED))
        assert after["status"] == "IN_PROGRESS"
        assert after["submitted_count"] == 0

    def test_non_owner_submit_is_403_not_422(self, api):
        """PRD §2.1: "For entity-backed roles, a mismatch between `X-User-ID`
        and the resource's owning provider reference is rejected with
        `ERR_OWNERSHIP_MISMATCH` (HTTP 403)."
        PRD §2.8: "a non-owner submitting an incomplete attestation receives
        `ERR_OWNERSHIP_MISMATCH`, not the TEFRA error."

        Design: Difficulty/priority_pair_validation_conflict/ownership_mismatch_beats_tefra_incomplete
        """
        site, fee, roster = setup_site_fee_roster(required_primary_slots=0,
                                                  scheduled_day_end_minute=1020)
        director = create_physician("Dr. Direct")
        peer = create_physician("Dr. Peer")
        case = create_case(roster["id"], scheduled_start_minute=540,
                           scheduled_end_minute=600)
        att = get_success_data(api.create_attestation(
            {"case_id": case["id"], "physician_id": director["id"]}, SCHED))
        resp = api.submit_attestation(att["id"], all_tefra_steps_false(),
                                      make_physician_headers(peer["id"]))
        assert resp.status_code == 403, (
            f"ownership layer (403) must fire before TEFRA completeness "
            f"(422); got {resp.status_code}: {resp.text}")
        # Control: the owner submitting with a false step DOES hit the TEFRA
        # error, proving both checks are live.
        owner_resp = api.submit_attestation(att["id"], all_tefra_steps_false(),
                                            make_physician_headers(director["id"]))
        validate_error(owner_resp, ApiErrorId.ERR_TEFRA_STEPS_INCOMPLETE)


class TestRosterLifecycleGateBeatsCredentialCheck:
    def test_assignment_on_draft_roster_surfaces_lifecycle_error(self, api):
        """PRD §2.8: "**State gates** — evaluated in the sub-order: (6a)
        roster lifecycle first, then (6b) the target resource's own state
        precondition, then (6c) clock-date and actual-time consistency."
        (state layer 6 precedes provider-safety layer 7's `ERR_CREDENTIAL_EXPIRED`.)
        PRD §3.3: "Proposals are accepted only while the case's roster is
        `PUBLISHED` (otherwise `ERR_ROSTER_NOT_PUBLISHED`".

        Design: Corner/validations/roster_lifecycle_gate_beats_credential_check
        """
        site, fee, roster = setup_site_fee_roster(
            publish=False, scheduled_day_end_minute=1200)
        expired = create_crna("Crna One", expiry="2026-08-05")
        case = create_case(roster["id"], scheduled_start_minute=540,
                           scheduled_end_minute=600)
        resp = api.create_case_assignment(
            case["id"], {"provider_id": expired["id"],
                         "assignment_role": "CASE_PRIMARY",
                         "expected_case_version": case["version"]}, SCHED)
        validate_error(resp, ApiErrorId.ERR_ROSTER_NOT_PUBLISHED)
        assert resp.json()["data"]["error_id"] != "ERR_CREDENTIAL_EXPIRED"
