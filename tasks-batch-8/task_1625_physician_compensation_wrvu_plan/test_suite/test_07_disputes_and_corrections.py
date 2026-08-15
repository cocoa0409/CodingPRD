"""Dispute workflow: review loop, corrections, resolution cascades, reversals."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    accept_dispute,
    assert_wrvu,
    create_dispute_under_review,
    create_validated_capture,
    file_capture_dispute,
    generate_statement,
    get_success_data,
    make_committee_headers,
    post_capture,
    reject_dispute,
    setup_active_plan_with_effective_agreement,
    setup_supervision_scenario,
    validate_capture,
    validate_error,
    validate_paginated,
    validate_success,
)

ANALYST = TEST_USERS["analyst_headers"]
COMMITTEE_9 = TEST_USERS["committee_9_headers"]


def _capture_with_dispute(api, npi="1000000031", plan_name="Cyc Plan", units=10):
    """EFFECTIVE agreement + validated capture + FILED dispute from the physician."""
    scenario = setup_active_plan_with_effective_agreement(npi=npi, plan_name=plan_name)
    capture = create_validated_capture(scenario["agreement"]["id"], units=units)
    dispute = file_capture_dispute(scenario["physician"]["id"], capture["id"],
                                   "wrong units")
    return {**scenario, "capture": capture, "dispute": dispute}


class TestCorrectionCycle:
    def test_cycle_back_clears_recorded_correction(self, api):
        """PRD §3.8: "The loop is revisable: starting review again from `DATA_CORRECTION` cycles the dispute back to `UNDER_REVIEW` and clears the recorded `corrected_units` and `corrected_cpt_code`, so a correction request can be walked back and re-issued any number of times before resolution."
        PRD §3.8: "During review of a capture dispute, the analyst may request a data correction, recording `corrected_units` and/or `corrected_cpt_code` on the dispute and moving it `UNDER_REVIEW → DATA_CORRECTION`"

        Design: Difficulty/non_linear_state_machine/dispute_correction_cycle
        """
        scenario = _capture_with_dispute(api)
        dispute_id = scenario["dispute"]["id"]
        get_success_data(api.start_dispute_review(dispute_id, ANALYST))
        in_correction = validate_success(
            api.request_correction(dispute_id, {"corrected_units": 8}, ANALYST), 200
        )
        assert in_correction["status"] == "DATA_CORRECTION"
        assert in_correction["corrected_units"] == 8
        cycled = validate_success(api.start_dispute_review(dispute_id, ANALYST), 200)
        assert cycled["status"] == "UNDER_REVIEW", "cycle-back returns to review"
        assert cycled["corrected_units"] is None, "the recorded correction is cleared"
        assert cycled["corrected_cpt_code"] is None

    def test_resolution_applies_only_latest_correction(self, api):
        """PRD §3.8: "When the accepted dispute carries a recorded correction, resolution additionally creates a replacement `CLINICAL` capture: born `VALIDATED` and `CREDITED` with the corrected units and code, the original `service_date` and `posting_date`, and `reversal_of_capture_id` pointing at the reversed original; the replacement recomputes the agreement's year-to-date ledger"
        PRD §3.8: "Acceptance flips the subject capture `CREDITED → REVERSED`"

        Design: Difficulty/non_linear_state_machine/dispute_correction_cycle
        """
        scenario = _capture_with_dispute(api)
        dispute_id = scenario["dispute"]["id"]
        cap_id = scenario["capture"]["id"]
        get_success_data(api.start_dispute_review(dispute_id, ANALYST))
        get_success_data(api.request_correction(dispute_id, {"corrected_units": 8}, ANALYST))
        get_success_data(api.start_dispute_review(dispute_id, ANALYST))  # walk back the 8
        reissued = validate_success(
            api.request_correction(dispute_id, {"corrected_units": 9}, ANALYST), 200
        )
        assert reissued["status"] == "DATA_CORRECTION"
        assert reissued["corrected_units"] == 9
        resolved = accept_dispute(dispute_id)
        assert resolved["status"] == "RESOLVED_ACCEPTED"
        original = get_success_data(api.get_capture(cap_id, ANALYST))
        assert original["credit_status"] == "REVERSED"
        corrections, meta = validate_paginated(api.list_capture_corrections(cap_id, ANALYST))
        assert meta["total_count"] == 1, "exactly one replacement capture"
        replacement = corrections[0]
        assert replacement["units"] == 9, "only the latest correction applies (9, not 8)"
        assert_wrvu(replacement["credited_wrvu"], 8.73)  # 9 x 0.97
        assert replacement["reversal_of_capture_id"] == cap_id
        assert replacement["capture_status"] == "VALIDATED"
        assert replacement["credit_status"] == "CREDITED"
        agreement = get_success_data(
            api.get_agreement(scenario["agreement"]["id"], ANALYST)
        )
        assert_wrvu(agreement["ytd_wrvu_credited"], 8.73)


class TestResolutionCascade:
    def test_correction_accept_reverses_supervision_children(self, api):
        """PRD §3.8: "Acceptance flips the subject capture `CREDITED → REVERSED`, records a `reversed_reason` drawn from the resolving dispute, recomputes the owning agreement's `ytd_wrvu_credited`, and — when the reversed capture is a `CLINICAL` capture with supervision children — flips each `SUPERVISION_CREDIT` child from `CREDITED` to `REVERSED` and recomputes each supervisor agreement's `ytd_wrvu_credited` in turn."

        Design: Difficulty/transitive_cascade/dispute_accept_correction_cascade
        """
        scenario = setup_supervision_scenario(
            supervisor_count=1, credit_pcts=(0.5,), npi_base=1000000041
        )
        capture = post_capture(scenario["agr_app"]["id"], units=10,
                               service_date="2026-02-10", posting_date="2026-02-10")
        validate_capture(capture["id"])
        dispute = create_dispute_under_review(scenario["app"]["id"], capture["id"],
                                              "units overstated")
        get_success_data(
            api.request_correction(dispute["id"], {"corrected_units": 4}, ANALYST)
        )
        accept_dispute(dispute["id"])
        original = get_success_data(api.get_capture(capture["id"], ANALYST))
        assert original["credit_status"] == "REVERSED", "hop 1: subject capture reversed"
        credits, _ = validate_paginated(api.list_supervision_credits(capture["id"], ANALYST))
        assert len(credits) == 1
        assert_wrvu(credits[0]["credited_wrvu"], 4.85)
        assert credits[0]["credit_status"] == "REVERSED", (
            "hop 2: the supervision child reverses with its source"
        )
        sup_agr = get_success_data(
            api.get_agreement(scenario["agr_sups"][0]["id"], ANALYST)
        )
        assert_wrvu(sup_agr["ytd_wrvu_credited"], 1.94)
        # hop 3: 4.85 reversed, then round_half_up(3.88 x 0.5, 2) = 1.94 re-allocated
        app_agr = get_success_data(api.get_agreement(scenario["agr_app"]["id"], ANALYST))
        assert_wrvu(app_agr["ytd_wrvu_credited"], 3.88)  # replacement 4 x 0.97

    def test_correction_accept_recomputes_draft_statement(self, api):
        """PRD §3.8: "Any `DRAFT` statement on the owning agreement whose period matches the reversed capture's `credited_period` is recomputed to reflect the reversal."
        PRD §3.4: "one lists the replacement captures whose `reversal_of_capture_id` points at a given capture (the correction trail built by dispute resolution)"

        Design: Difficulty/transitive_cascade/dispute_accept_correction_cascade
        """
        scenario = setup_supervision_scenario(
            supervisor_count=1, credit_pcts=(0.5,), npi_base=1000000041
        )
        capture = post_capture(scenario["agr_app"]["id"], units=10,
                               service_date="2026-02-10", posting_date="2026-02-10")
        validate_capture(capture["id"])
        stmt = generate_statement(scenario["agr_app"]["id"], 2026, 2)  # DRAFT, 9.70
        dispute = create_dispute_under_review(scenario["app"]["id"], capture["id"],
                                              "units overstated")
        get_success_data(
            api.request_correction(dispute["id"], {"corrected_units": 4}, ANALYST)
        )
        accept_dispute(dispute["id"])
        corrections, _ = validate_paginated(api.list_capture_corrections(capture["id"], ANALYST))
        assert len(corrections) == 1
        replacement = corrections[0]
        assert replacement["units"] == 4
        assert_wrvu(replacement["credited_wrvu"], 3.88)
        stmt_after = get_success_data(api.get_statement(stmt["id"], ANALYST))
        assert stmt_after["status"] == "DRAFT"
        assert_wrvu(stmt_after["period_wrvu"], 3.88)
        assert stmt_after["productivity_earned_ytd_cents"] == 17460  # 3.88 x 4500
        assert replacement["id"] in stmt_after["capture_ids"]
        assert capture["id"] not in stmt_after["capture_ids"]


class TestReversalConservation:
    def test_validate_credits_the_ledger(self, api):
        """PRD §3.4: "Validation moves the capture `POSTED → VALIDATED` and `UNCREDITED → CREDITED`, increments the capture's `version`, recomputes the owning agreement's `ytd_wrvu_credited` (the running sum of `credited_wrvu` over the agreement's `CREDITED` captures, kept at 2 decimal places), and increments the agreement's `version` as well."

        Design: Difficulty/compensating_invariant/capture_reversal_wrvu_conservation
        """
        scenario = setup_active_plan_with_effective_agreement(
            npi="1000000100", plan_name="Cons Plan"
        )
        agreement = scenario["agreement"]
        assert_wrvu(agreement["ytd_wrvu_credited"], 0.00)  # empty CREDITED set
        create_validated_capture(agreement["id"], units=10)
        after = get_success_data(api.get_agreement(agreement["id"], ANALYST))
        assert_wrvu(after["ytd_wrvu_credited"], 9.70)

    def test_reversal_returns_ledger_to_zero(self, api):
        """PRD §3.8: "Acceptance flips the subject capture `CREDITED → REVERSED`, records a `reversed_reason` drawn from the resolving dispute, recomputes the owning agreement's `ytd_wrvu_credited`"
        PRD §3.4: "the running sum of `credited_wrvu` over the agreement's `CREDITED` captures"
        PRD §3.4: "The agreement's capture listing accepts an optional `credit_status` filter."

        Design: Difficulty/compensating_invariant/capture_reversal_wrvu_conservation
        """
        scenario = setup_active_plan_with_effective_agreement(
            npi="1000000100", plan_name="Cons Plan"
        )
        agr_id = scenario["agreement"]["id"]
        capture = create_validated_capture(agr_id, units=10)
        dispute = create_dispute_under_review(scenario["physician"]["id"], capture["id"],
                                              "duplicate entry")
        accept_dispute(dispute["id"])
        agreement = get_success_data(api.get_agreement(agr_id, ANALYST))
        assert agreement["ytd_wrvu_credited"] == 0.00, (
            "forward validate (+9.70) paired with the compensating reversal is the identity"
        )
        credited, meta = validate_paginated(
            api.list_captures(agr_id, ANALYST, params={"credit_status": "CREDITED"})
        )
        assert credited == [] and meta["total_count"] == 0


class TestResolutionRules:
    def test_resolved_dispute_is_terminal(self, api):
        """PRD §3.8: "Resolution belongs to the committee and takes a `resolution` of `ACCEPTED` or `REJECTED` from either `UNDER_REVIEW` or `DATA_CORRECTION`, moving the dispute to its terminal state `RESOLVED_ACCEPTED` or `RESOLVED_REJECTED` respectively."
        PRD §2.9: "Next is the generic state-machine guard (`ERR_INVALID_STATE`)"

        Design: Corner/state_machines/dispute_resolve_terminal_lockdown
        """
        scenario = _capture_with_dispute(api, npi="1000000212", plan_name="Term Plan",
                                         units=5)
        dispute_id = scenario["dispute"]["id"]
        get_success_data(api.start_dispute_review(dispute_id, ANALYST))
        rejected = reject_dispute(dispute_id)
        assert rejected["status"] == "RESOLVED_REJECTED"
        resp = api.resolve_dispute(dispute_id, {"resolution": "ACCEPTED"}, COMMITTEE_9)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        rows, _ = validate_paginated(
            api.list_disputes(ANALYST, params={"agreement_id": scenario["agreement"]["id"]})
        )
        assert rows[0]["status"] == "RESOLVED_REJECTED", "terminal state does not move"
        capture = get_success_data(api.get_capture(scenario["capture"]["id"], ANALYST))
        assert capture["credit_status"] == "CREDITED", (
            "rejection carries no compensation side effects"
        )

    def test_accept_resolver_must_differ_from_capture_creator(self, api):
        """PRD §3.8: "For a capture subject, the resolver must differ from the subject capture's `created_by_user_id` (`ERR_SEGREGATION_OF_DUTIES`)"
        PRD §2.8: "the committee member who accepts a capture dispute must not be the analyst recorded as the subject capture's `created_by_user_id`."

        Design: Corner/validations/dispute_resolve_segregation_rejected
        """
        scenario = _capture_with_dispute(api, npi="1000000244", plan_name="Res Plan",
                                         units=5)
        dispute_id = scenario["dispute"]["id"]
        get_success_data(api.start_dispute_review(dispute_id, ANALYST))
        resp = api.resolve_dispute(
            dispute_id, {"resolution": "ACCEPTED"},
            make_committee_headers("an_1"),  # same id as the analyst who posted the capture
        )
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        rows, _ = validate_paginated(
            api.list_disputes(ANALYST, params={"agreement_id": scenario["agreement"]["id"]})
        )
        assert rows[0]["status"] == "UNDER_REVIEW", "a rejected resolve changes nothing"
