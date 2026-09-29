"""Service-partner authority: training gates, claim authority derivation and the claim-time checks."""

import pytest

from test_helpers import (
    ApiErrorId,
    adjudicate_claim,
    coverage_action,
    create_connected_unit,
    create_equipment_model,
    create_service_partner,
    enrol_technician,
    file_warranty_claim,
    grade_technician,
    make_service_partner_headers,
    partner_authorization,
    partner_authorization_payload,
    read_connected_unit,
    read_service_partner,
    read_technician_certification,
    read_warranty_claim,
    set_clock,
    setup_certified_technicians,
    setup_listed_model,
    setup_warranty_environment,
    technician_grade_payload,
    validate_error,
    validate_paginated,
    validate_success,
    warranty_claim_payload,
)

CERT_EXPIRY_FROM_DEFAULT_CLOCK = "2028-07-31T00:00:00"


def _file_attempt(api, unit_id, partner_id, certification_id, claim_code, **overrides):
    """File a claim as the partner itself without asserting the outcome."""
    return api.create_warranty_claim(
        warranty_claim_payload(
            unit_id, partner_id, certification_id, claim_code, **overrides
        ),
        make_service_partner_headers(partner_id),
    )


def _claim_codes(api, headers):
    data, _ = validate_paginated(api.list_warranty_claims(headers, {"limit": 100}))
    return [claim["claim_code"] for claim in data]


class TestCoverageStateOutranksPartnerAuthority:
    def test_dormant_coverage_is_reported_before_the_partners_missing_authority(
        self, api, warranty_adjudicator
    ):
        """With both gates live the filing returns the coverage error, then the authority one.

        PRD §2.9: "Beyond path resolution, the checks a request undergoes are strictly
        ordered, and the first failing check determines the response. Two checks that
        would both fail must produce the earlier one's error, which is why the ordering
        below is normative rather than descriptive:"

        Design: Difficulty/priority_pair_validation_conflict/coverage_state_check_23_outranks_partner_authorization_check_32_on_claim_filing
        """
        set_clock()
        listed = setup_listed_model()
        model_id = listed["model"]["id"]
        unit = create_connected_unit(model_id, "SN-1")
        partner = create_service_partner()
        certifications = setup_certified_technicians(partner["id"], model_id)
        provisional = partner_authorization(partner["id"], "PROVISION")

        assert unit["service_program_status"] == "PENDING_INSTALL", (
            "coverage was never activated, so the unit still awaits install, got "
            f"{unit['service_program_status']}"
        )
        assert provisional["status"] == "PROVISIONAL", (
            "one PASSED certification is enough for PROVISION but not for AUTHORIZE, "
            f"got {provisional['status']}"
        )

        both_violated = _file_attempt(
            api, unit["id"], partner["id"], certifications[0]["id"], "CLM-1"
        )
        validate_error(both_violated, ApiErrorId.ERR_UNIT_COVERAGE_NOT_ACTIVE.value, 409)

        activated = coverage_action(unit["id"], "ACTIVATE")
        assert activated["service_program_status"] == "ACTIVE", (
            "activating coverage remediates only the higher-priority violation, got "
            f"{activated['service_program_status']}"
        )
        assert read_service_partner(partner["id"])["status"] == "PROVISIONAL", (
            "the partner is deliberately left short of AUTHORIZED"
        )

        still_unauthorized = _file_attempt(
            api, unit["id"], partner["id"], certifications[0]["id"], "CLM-1"
        )
        validate_error(
            still_unauthorized,
            ApiErrorId.ERR_PARTNER_NOT_AUTHORIZED_FOR_CLAIMS.value,
            422,
        )

        unit_after = read_connected_unit(unit["id"])
        assert unit_after["service_program_status"] == "ACTIVE", (
            "the refused filings leave coverage where the activation put it, got "
            f"{unit_after['service_program_status']}"
        )
        assert unit_after["claims_paid_cents"] == 0, (
            f"no claim was ever accepted, got {unit_after['claims_paid_cents']}"
        )
        assert _claim_codes(api, warranty_adjudicator) == [], (
            "neither refused filing may leave a claim row behind"
        )

    def test_authorizing_the_partner_first_leaves_the_coverage_error_in_front(
        self, api
    ):
        """Fixing only the lower-priority gate still yields the coverage error until activation.

        PRD §3.9: "Three business gates apply after the ownership and existence checks.
        The unit's coverage must be live — `service_program_status` `ACTIVE` or
        `EXTENDED`, evaluated after the lazy expiry re-evaluation above — otherwise
        `ERR_UNIT_COVERAGE_NOT_ACTIVE`."

        Design: Difficulty/priority_pair_validation_conflict/coverage_state_check_23_outranks_partner_authorization_check_32_on_claim_filing
        """
        set_clock()
        listed = setup_listed_model()
        model_id = listed["model"]["id"]
        unit = create_connected_unit(model_id, "SN-1")
        partner = create_service_partner()
        certifications = setup_certified_technicians(partner["id"], model_id)
        partner_authorization(partner["id"], "PROVISION")
        authorized = partner_authorization(partner["id"], "AUTHORIZE")

        assert authorized["status"] == "AUTHORIZED", (
            f"two PASSED certifications and FULL stocking authorise the partner, got "
            f"{authorized['status']}"
        )
        assert authorized["authorized_model_ids"] == [model_id], (
            "the model has reached the two-technician bar, got "
            f"{authorized['authorized_model_ids']}"
        )

        coverage_still_dormant = _file_attempt(
            api, unit["id"], partner["id"], certifications[0]["id"], "CLM-1"
        )
        validate_error(
            coverage_still_dormant, ApiErrorId.ERR_UNIT_COVERAGE_NOT_ACTIVE.value, 409
        )

        coverage_action(unit["id"], "ACTIVATE")
        accepted = validate_success(
            _file_attempt(
                api, unit["id"], partner["id"], certifications[0]["id"], "CLM-1"
            ),
            201,
        )
        assert accepted["status"] == "SUBMITTED", (
            "with both gates satisfied the same filing is accepted, which shows neither "
            f"earlier refusal was a false positive, got {accepted['status']}"
        )
        assert accepted["adjudicated_amount_cents"] is None, (
            "a filed claim carries no payout yet, got "
            f"{accepted['adjudicated_amount_cents']}"
        )


class TestAdjudicationFollowsPartnerAuthorization:
    def test_suspension_makes_an_open_claim_unapprovable_until_reinstatement(
        self, api, warranty_adjudicator
    ):
        """A legitimately filed claim is refused while its partner is SUSPENDED, then pays 150000.

        PRD §3.9: "`SUSPEND` takes it `AUTHORIZED → SUSPENDED`; claim children already in
        `SUBMITTED` stay `SUBMITTED` but become unapprovable while the partner is
        suspended."

        Design: Difficulty/cross_entity_state_dependency/claim_adjudication_follows_service_partner_authorization_state_across_suspend_and_reinstate
        """
        state = setup_warranty_environment()
        claim = file_warranty_claim(
            state["unit"]["id"],
            state["partner"]["id"],
            state["certifications"][0]["id"],
            "CLM-1",
        )
        assert claim["status"] == "SUBMITTED", (
            f"the claim is filed while the partner is AUTHORIZED, got {claim['status']}"
        )

        suspended = partner_authorization(state["partner"]["id"], "SUSPEND")
        assert suspended["status"] == "SUSPENDED", (
            f"the partner is suspended after filing, got {suspended['status']}"
        )

        refused = api.adjudicate_warranty_claim(
            claim["id"], {"decision": "APPROVE"}, warranty_adjudicator
        )
        validate_error(
            refused, ApiErrorId.ERR_PARTNER_NOT_AUTHORIZED_FOR_CLAIMS.value, 422
        )

        held = read_warranty_claim(claim["id"])
        assert held["status"] == "SUBMITTED", (
            f"the suspension does not move the claim itself, got {held['status']}"
        )
        assert held["adjudicated_amount_cents"] is None, (
            f"the refused approval stamps no payout, got "
            f"{held['adjudicated_amount_cents']}"
        )
        assert read_connected_unit(state["unit"]["id"])["reserve_balance_cents"] == 250000, (
            "the reserve is untouched while the claim waits"
        )

        reinstated = partner_authorization(state["partner"]["id"], "REINSTATE")
        assert reinstated["status"] == "AUTHORIZED", (
            f"reinstatement restores the partner, got {reinstated['status']}"
        )

        approved = adjudicate_claim(claim["id"], "APPROVE")
        assert approved["status"] == "APPROVED", (
            f"the same claim is now approvable, got {approved['status']}"
        )
        assert approved["coinsurance_pct"] == pytest.approx(0.00, abs=0.001), (
            "nothing has been paid on the unit yet, got "
            f"{approved['coinsurance_pct']}"
        )
        assert approved["adjudicated_amount_cents"] == 150000, (
            "the payout is unchanged by the suspension detour at 123000 parts plus "
            f"27000 labour, got {approved['adjudicated_amount_cents']}"
        )
        assert read_connected_unit(state["unit"]["id"])["reserve_balance_cents"] == 100000, (
            "only the approval moves the ledger"
        )

    def test_every_adjudication_rereads_live_partner_state(
        self, api, warranty_adjudicator
    ):
        """Two open claims each follow the partner's current status through two suspensions.

        PRD §3.9: "Approval also requires, at the moment of decision, that the filing
        partner still be `AUTHORIZED` for the model and that the unit's coverage still be
        `ACTIVE` or `EXTENDED` — a partner suspended between filing and adjudication makes
        its open claims unapprovable, reported as
        `ERR_PARTNER_NOT_AUTHORIZED_FOR_CLAIMS`, and a unit whose coverage lapsed in
        between is reported as `ERR_UNIT_COVERAGE_NOT_ACTIVE`."

        Design: Difficulty/cross_entity_state_dependency/claim_adjudication_follows_service_partner_authorization_state_across_suspend_and_reinstate
        """
        state = setup_warranty_environment()
        partner_id = state["partner"]["id"]
        first = file_warranty_claim(
            state["unit"]["id"], partner_id, state["certifications"][0]["id"], "CLM-1"
        )
        second = file_warranty_claim(
            state["unit"]["id"],
            partner_id,
            state["certifications"][1]["id"],
            "CLM-2",
            parts_cost_cents=40000,
            labor_hours=3.0,
        )

        partner_authorization(partner_id, "SUSPEND")
        for claim_id in (first["id"], second["id"]):
            refused = api.adjudicate_warranty_claim(
                claim_id, {"decision": "APPROVE"}, warranty_adjudicator
            )
            validate_error(
                refused, ApiErrorId.ERR_PARTNER_NOT_AUTHORIZED_FOR_CLAIMS.value, 422
            )

        partner_authorization(partner_id, "REINSTATE")
        approved_first = adjudicate_claim(first["id"], "APPROVE")
        assert approved_first["adjudicated_amount_cents"] == 150000, (
            f"the first claim pays 150000, got "
            f"{approved_first['adjudicated_amount_cents']}"
        )

        partner_authorization(partner_id, "SUSPEND")
        refused_again = api.adjudicate_warranty_claim(
            second["id"], {"decision": "APPROVE"}, warranty_adjudicator
        )
        validate_error(
            refused_again, ApiErrorId.ERR_PARTNER_NOT_AUTHORIZED_FOR_CLAIMS.value, 422
        )
        assert read_warranty_claim(second["id"])["status"] == "SUBMITTED", (
            "the second suspension leaves the remaining claim open"
        )

        partner_authorization(partner_id, "REINSTATE")
        approved_second = adjudicate_claim(second["id"], "APPROVE")
        assert approved_second["coinsurance_pct"] == pytest.approx(0.10, abs=0.001), (
            "the first payout took utilisation to exactly 0.60, got "
            f"{approved_second['coinsurance_pct']}"
        )
        assert approved_second["adjudicated_amount_cents"] == 60300, (
            "a gross of 67000 less ten percent is 60300, got "
            f"{approved_second['adjudicated_amount_cents']}"
        )

        unit = read_connected_unit(state["unit"]["id"])
        assert unit["reserve_balance_cents"] == 39700, (
            f"250000 less 150000 less 60300 leaves 39700, got "
            f"{unit['reserve_balance_cents']}"
        )
        assert unit["claims_paid_cents"] == 210300, (
            f"both payouts are booked, got {unit['claims_paid_cents']}"
        )


class TestCertificationOwnership:
    def test_a_claim_naming_another_partners_certification_is_refused(
        self, api, warranty_adjudicator
    ):
        """A PASSED certification held by SP-2 cannot support SP-1's claim.

        PRD §3.9: "And the named certification must belong to the filing partner, be
        `PASSED` with an `expires_on` still strictly later than the clock, and be held
        for the same `equipment_model_id` as the unit, otherwise
        `ERR_TECHNICIAN_NOT_CERTIFIED`."

        Design: Corner/entities/claim_referencing_another_partners_technician_certification_is_rejected
        """
        state = setup_warranty_environment()
        model_id = state["model"]["id"]
        other_partner = create_service_partner(partner_code="SP-2", name="Harbour Service")
        foreign = setup_certified_technicians(
            other_partner["id"], model_id, [("TX", 40, 90)]
        )[0]

        assert foreign["status"] == "PASSED", (
            "the borrowed certification is genuinely PASSED, got "
            f"{foreign['status']}"
        )
        assert read_service_partner(other_partner["id"])["status"] == "APPLIED", (
            "its owner has not even been provisioned"
        )
        assert read_service_partner(state["partner"]["id"])["status"] == "AUTHORIZED", (
            "while the filing partner is fully authorised"
        )

        borrowed = _file_attempt(
            api, state["unit"]["id"], state["partner"]["id"], foreign["id"], "CLM-X"
        )
        validate_error(borrowed, ApiErrorId.ERR_TECHNICIAN_NOT_CERTIFIED.value, 422)

        assert "CLM-X" not in _claim_codes(api, warranty_adjudicator), (
            "the refused filing must not persist a claim row"
        )
        assert read_connected_unit(state["unit"]["id"])["claims_paid_cents"] == 0, (
            "and it must not touch the unit's ledger"
        )


class TestGradeRederivesClaimAuthority:
    def test_the_second_pass_on_a_model_flips_authorized_model_ids(self):
        """One PASSED certification leaves authority empty; the second adds the model.

        PRD §3.9: "A model qualifies once that count reaches two, and
        `authorized_model_ids` lists every qualifying model identifier ordered by the
        equipment model's own `created_at` ascending."

        Design: Corner/state_machines/passing_a_technician_grade_rederives_the_partners_authorized_model_ids
        """
        set_clock()
        model = create_equipment_model()
        partner = create_service_partner()
        first_certification = enrol_technician(partner["id"], model["id"], "T1", 40)
        second_certification = enrol_technician(partner["id"], model["id"], "T2", 40)
        assert first_certification["status"] == "ENROLLED", (
            f"a new certification starts ENROLLED, got {first_certification['status']}"
        )
        assert partner["authorized_model_ids"] == [], (
            "a new partner has no claim authority, got "
            f"{partner['authorized_model_ids']}"
        )

        graded_first = grade_technician(first_certification["id"], 88)
        assert graded_first["status"] == "PASSED", (
            f"a score of 88 passes, got {graded_first['status']}"
        )
        assert graded_first["certified_on"].startswith("2026-08-01T00:00:00"), (
            "certified_on is stamped from the logical clock, got "
            f"{graded_first['certified_on']}"
        )
        assert graded_first["expires_on"].startswith(CERT_EXPIRY_FROM_DEFAULT_CLOCK), (
            "expires_on is certified_on plus a 730 day term, got "
            f"{graded_first['expires_on']}"
        )

        after_one = read_service_partner(partner["id"])
        assert after_one["authorized_model_ids"] == [], (
            "one PASSED certification is short of the two-technician bar, got "
            f"{after_one['authorized_model_ids']}"
        )
        assert after_one["status"] == "APPLIED", (
            "grading does not advance the partner's own network status, got "
            f"{after_one['status']}"
        )

        graded_second = grade_technician(second_certification["id"], 91)
        assert graded_second["status"] == "PASSED", (
            f"a score of 91 passes as well, got {graded_second['status']}"
        )

        after_two = read_service_partner(partner["id"])
        assert after_two["authorized_model_ids"] == [model["id"]], (
            "the second pass on the same model flips the partner's authority, got "
            f"{after_two['authorized_model_ids']}"
        )
        assert after_two["status"] == "APPLIED", (
            "the partner is still only APPLIED even though it now has authority, got "
            f"{after_two['status']}"
        )


class TestCertificationExpiryIsStrict:
    def test_authority_empties_at_the_instant_the_certifications_expire(
        self, api, warranty_adjudicator
    ):
        """A filing one second before expiry is accepted and one at expiry is refused.

        PRD §3.9: "For each distinct `equipment_model_id` appearing among the partner's
        technician certifications, count the certifications for that model whose `status`
        is `PASSED` and whose `expires_on` is strictly later than the logical clock;
        certifications in `ENROLLED` or `FAILED` never count, and a passed certification
        stops counting the instant the clock reaches its `expires_on`."

        Design: Corner/calculations/technician_certification_expiry_is_strict_and_drops_the_model_from_claim_authority
        """
        state = setup_warranty_environment(service_tier="EXTENDED_PLUS")
        extended = coverage_action(state["unit"]["id"], "EXTEND")
        assert extended["service_program_status"] == "EXTENDED", (
            f"an EXTENDED_PLUS unit can be extended, got "
            f"{extended['service_program_status']}"
        )
        assert extended["coverage_end_date"].startswith("2029-07-31T00:00:00"), (
            "the extension pushes coverage out by another 365 days, got "
            f"{extended['coverage_end_date']}"
        )
        assert extended["reserve_initial_cents"] == 900000, (
            "600000 plus the 300000 the extension adds, got "
            f"{extended['reserve_initial_cents']}"
        )
        assert extended["reserve_balance_cents"] == 900000, (
            f"nothing has been claimed yet, got {extended['reserve_balance_cents']}"
        )
        assert state["certifications"][0]["expires_on"].startswith(
            CERT_EXPIRY_FROM_DEFAULT_CLOCK
        ), (
            "both certifications were graded at 2026-08-01, so they run to "
            f"2028-07-31T00:00:00Z, got {state['certifications'][0]['expires_on']}"
        )

        set_clock("2028-07-30T23:59:59Z")
        in_time = validate_success(
            _file_attempt(
                api,
                state["unit"]["id"],
                state["partner"]["id"],
                state["certifications"][0]["id"],
                "CLM-A",
            ),
            201,
        )
        assert in_time["status"] == "SUBMITTED", (
            "one second before expiry the certifications still count, got "
            f"{in_time['status']}"
        )

        set_clock("2028-07-31T00:00:00Z")
        lapsed_partner = read_service_partner(state["partner"]["id"])
        assert lapsed_partner["authorized_model_ids"] == [], (
            "at the expiry instant neither certification counts, so authority empties, "
            f"got {lapsed_partner['authorized_model_ids']}"
        )
        assert lapsed_partner["status"] == "AUTHORIZED", (
            "the partner's own network status is unaffected by the ageing, got "
            f"{lapsed_partner['status']}"
        )

        lapsed = _file_attempt(
            api,
            state["unit"]["id"],
            state["partner"]["id"],
            state["certifications"][0]["id"],
            "CLM-B",
        )
        validate_error(
            lapsed, ApiErrorId.ERR_PARTNER_NOT_AUTHORIZED_FOR_CLAIMS.value, 422
        )
        assert "CLM-B" not in _claim_codes(api, warranty_adjudicator), (
            "the refused filing leaves no claim row"
        )


class TestMinimumCertifiedTechnicians:
    def test_authorize_needs_two_passed_certifications_on_one_model(
        self, api, channel_manager
    ):
        """AUTHORIZE fails at one PASSED certification and succeeds at exactly two.

        PRD §3.9: "`AUTHORIZE` takes it `PROVISIONAL → AUTHORIZED` and requires two
        things: a non-empty `authorized_model_ids`, meaning at least one model has reached
        the two-certified-technician bar, and a `parts_stocking_level` of `FULL`, since an
        authorised partner must carry the full parts distribution kit — the stocking
        failure is reported as `ERR_PARTS_STOCKING_INSUFFICIENT`, while the technician
        shortfall on either `PROVISION`, `AUTHORIZE` or `REINSTATE` is reported as
        `ERR_INSUFFICIENT_CERTIFIED_TECHNICIANS`."

        Design: Corner/calculations/minimum_certified_technicians_threshold_is_inclusive_at_two
        """
        set_clock()
        model = create_equipment_model()
        partner = create_service_partner()
        passed = grade_technician(
            enrol_technician(partner["id"], model["id"], "T1", 40)["id"], 88
        )
        pending = enrol_technician(partner["id"], model["id"], "T2", 40)
        provisional = partner_authorization(partner["id"], "PROVISION")

        assert provisional["status"] == "PROVISIONAL", (
            "one PASSED certification satisfies PROVISION, got "
            f"{provisional['status']}"
        )
        assert provisional["authorized_model_ids"] == [], (
            "but a single certification does not qualify the model, got "
            f"{provisional['authorized_model_ids']}"
        )
        assert pending["status"] == "ENROLLED", (
            f"the second technician has not sat the exam, got {pending['status']}"
        )

        short = api.partner_authorization(
            partner["id"], partner_authorization_payload("AUTHORIZE"), channel_manager
        )
        validate_error(
            short, ApiErrorId.ERR_INSUFFICIENT_CERTIFIED_TECHNICIANS.value, 422
        )
        assert read_service_partner(partner["id"])["status"] == "PROVISIONAL", (
            "the refused authorisation leaves the partner PROVISIONAL"
        )
        assert passed["status"] == "PASSED", (
            f"the first certification is genuinely PASSED, got {passed['status']}"
        )

        assert grade_technician(pending["id"], 91)["status"] == "PASSED", (
            "grading the second technician passes them"
        )
        authorized = partner_authorization(partner["id"], "AUTHORIZE")
        assert authorized["status"] == "AUTHORIZED", (
            "exactly two PASSED certifications meet the inclusive bar, got "
            f"{authorized['status']}"
        )
        assert authorized["authorized_model_ids"] == [model["id"]], (
            f"and the model now qualifies, got {authorized['authorized_model_ids']}"
        )


class TestTrainingHoursGate:
    def test_twenty_three_hours_blocks_the_exam_and_twenty_four_passes(
        self, api, channel_manager
    ):
        """23 documented hours is refused; exactly 24 hours is graded and a score of 80 passes.

        PRD §3.9: "It is permitted only while the certification is `ENROLLED`, and only
        once the technician has logged at least twenty-four documented `training_hours`; a
        grade recorded against an under-trained technician is rejected with
        `ERR_TRAINING_HOURS_NOT_MET`."

        Design: Corner/validations/training_hours_gate_is_inclusive_at_twenty_four_hours
        """
        set_clock()
        model = create_equipment_model()
        partner = create_service_partner()
        short = enrol_technician(partner["id"], model["id"], "T-SHORT", 23)
        exact = enrol_technician(partner["id"], model["id"], "T-EXACT", 24)

        assert short["status"] == "ENROLLED", (
            f"both technicians start ENROLLED, got {short['status']}"
        )

        refused = api.grade_technician_certification(
            short["id"], technician_grade_payload(80), channel_manager
        )
        validate_error(refused, ApiErrorId.ERR_TRAINING_HOURS_NOT_MET.value, 422)

        untouched = read_technician_certification(short["id"])
        assert untouched["status"] == "ENROLLED", (
            "an under-trained technician stays ENROLLED and can still log hours, got "
            f"{untouched['status']}"
        )
        assert untouched["exam_score"] is None, (
            f"the refused grade records no score, got {untouched['exam_score']}"
        )
        assert untouched["certified_on"] is None, (
            f"nor any certification date, got {untouched['certified_on']}"
        )

        graded = validate_success(
            api.grade_technician_certification(
                exact["id"], technician_grade_payload(80), channel_manager
            )
        )
        assert graded["status"] == "PASSED", (
            "exactly twenty-four hours clears the gate and a score of exactly eighty "
            f"passes, got {graded['status']}"
        )
        assert graded["exam_score"] == pytest.approx(80, abs=0.01), (
            f"the score is stored as given, got {graded['exam_score']}"
        )
        assert graded["expires_on"].startswith(CERT_EXPIRY_FROM_DEFAULT_CLOCK), (
            f"the term runs 730 days from the grade, got {graded['expires_on']}"
        )


class TestAuthorizationGateOrdering:
    def test_the_state_gate_is_reported_before_the_stocking_gate(
        self, api, channel_manager
    ):
        """AUTHORIZE from APPLIED reports the state error; from PROVISIONAL the stocking one.

        PRD §2.9: "Beyond path resolution, the checks a request undergoes are strictly
        ordered, and the first failing check determines the response. Two checks that
        would both fail must produce the earlier one's error, which is why the ordering
        below is normative rather than descriptive:"

        Design: Corner/validations/authorization_state_gate_precedes_the_parts_stocking_gate
        """
        set_clock()
        model = create_equipment_model()
        partner = create_service_partner(parts_stocking_level="BASIC")
        setup_certified_technicians(partner["id"], model["id"])

        assert read_service_partner(partner["id"])["status"] == "APPLIED", (
            "the partner has not been provisioned yet"
        )

        wrong_state = api.partner_authorization(
            partner["id"], partner_authorization_payload("AUTHORIZE"), channel_manager
        )
        validate_error(wrong_state, ApiErrorId.ERR_CHANNEL_STATE_INVALID.value, 409)

        provisional = partner_authorization(partner["id"], "PROVISION")
        assert provisional["status"] == "PROVISIONAL", (
            f"PROVISION is the transition APPLIED admits, got {provisional['status']}"
        )
        assert provisional["authorized_model_ids"] == [model["id"]], (
            "the technician bar is already met, so only stocking can fail next, got "
            f"{provisional['authorized_model_ids']}"
        )

        wrong_stocking = api.partner_authorization(
            partner["id"], partner_authorization_payload("AUTHORIZE"), channel_manager
        )
        validate_error(
            wrong_stocking, ApiErrorId.ERR_PARTS_STOCKING_INSUFFICIENT.value, 422
        )

        final = read_service_partner(partner["id"])
        assert final["status"] == "PROVISIONAL", (
            f"a partner that cannot stock parts stays PROVISIONAL, got {final['status']}"
        )
        assert final["parts_stocking_level"] == "BASIC", (
            "the refusal does not rewrite the stocking commitment, got "
            f"{final['parts_stocking_level']}"
        )
