"""Consult lifecycle: state machine, OCC-guarded writes, clarification cycle."""
from datetime import datetime, timezone

from test_helpers import (
    ApiErrorId, TEST_USERS, create_consult, create_membership, create_specialist,
    create_window, document_response, finalize_response, get_consult, get_response,
    get_summary, make_provider_headers, make_specialist_headers,
    setup_answered_consult, setup_assigned_consult, setup_finalized_consult,
    setup_panel_scenario, setup_queued_consult_scenario,
    validate_error, validate_paginated, validate_success,
)

COORD = TEST_USERS["coordinator_headers"]
BILLING = TEST_USERS["billing_headers"]


def _parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


class TestConsultLifecycle:
    def test_close_from_assigned_returns_invalid_state(self, api):
        """PRD §3.6: "Closing requires the consult to be `ANSWERED`
        (`ERR_CONSULT_NOT_ANSWERED`), the caller to be the owner
        (`ERR_NOT_CONSULT_OWNER`), and — a cross-entity dependency — the consult's
        response to be `FINALIZED` (`ERR_RESPONSE_NOT_FINALIZED`)."

        Design: Corner/state_machines/close_from_assigned_returns_invalid_state
        """
        scenario = setup_assigned_consult(
            patient_ref="PAT-S1", provider_npi="1000002001",
            specialist_npi="2000002001",
            consult_overrides={
                "question_text": "Stable chest pain on therapy; asks whether any medication adjustment is warranted now.",
                "icd10_primary": "I20",
            },
        )
        consult = scenario["consult"]
        res = api.close_consult(
            consult["id"], make_provider_headers(scenario["provider"]["id"])
        )
        validate_error(res, ApiErrorId.ERR_CONSULT_NOT_ANSWERED, expected_status=409)
        assert get_consult(consult["id"])["status"] == "ASSIGNED"

    def test_respond_after_cancel_returns_invalid_state(self, api):
        """PRD §3.5: "Submission requires the consult to be `ASSIGNED`: a consult in
        any other non-terminal state yields `ERR_CONSULT_NOT_ASSIGNED`, and a terminal
        consult yields `ERR_CONSULT_ALREADY_TERMINAL`."

        Design: Corner/state_machines/respond_after_cancel_returns_invalid_state
        """
        scenario = setup_assigned_consult(
            patient_ref="PAT-S2", provider_npi="1000002002",
            specialist_npi="2000002002",
            consult_overrides={
                "question_text": "Palpitations, holter pending; asks if caffeine restriction alone is reasonable interim.",
                "icd10_primary": "R00",
            },
        )
        consult = scenario["consult"]
        cancelled = validate_success(api.cancel_consult(
            consult["id"], make_provider_headers(scenario["provider"]["id"])
        ), 200)
        assert cancelled["status"] == "CANCELLED"
        res = api.create_response(
            consult["id"],
            {"disposition": "MANAGE_IN_PRIMARY_CARE",
             "recommendation_text": "Caffeine restriction and electrolytes are reasonable; await holter before further changes."},
            make_specialist_headers(scenario["specialist"]["id"]),
        )
        validate_error(res, ApiErrorId.ERR_CONSULT_ALREADY_TERMINAL,
                       expected_status=409)
        responses, _meta = validate_paginated(
            api.list_consult_responses(consult["id"], COORD)
        )
        assert responses == [], "no ConsultResponse may be created on a cancelled consult"

    def test_cancel_after_answer_returns_invalid_state(self, api):
        """PRD §3.3: "Cancellation is not available once a consult is `ANSWERED` or in
        any terminal state; such attempts are rejected with
        `ERR_CONSULT_ALREADY_TERMINAL`"

        Design: Corner/state_machines/cancel_after_answer_returns_invalid_state
        """
        scenario = setup_answered_consult(
            patient_ref="PAT-S3", provider_npi="1000002003",
            specialist_npi="2000002003",
            consult_overrides={
                "question_text": "Hypertension with ankle swelling on amlodipine; asks about switching class versus dose split.",
                "icd10_primary": "I10",
            },
            response_overrides={
                "recommendation_text": "Switch to losartan 50mg daily; expect swelling resolution over 2 to 4 weeks.",
            },
        )
        res = api.cancel_consult(
            scenario["consult"]["id"],
            make_provider_headers(scenario["provider"]["id"]),
        )
        validate_error(res, ApiErrorId.ERR_CONSULT_ALREADY_TERMINAL,
                       expected_status=409)
        consult_after = get_consult(scenario["consult"]["id"])
        assert consult_after["status"] == "ANSWERED"
        assert get_response(scenario["response"]["id"])["status"] == "SUBMITTED"

    def test_clarification_cycle_sequences_messages(self, api):
        """PRD §3.4: "A successful request appends a `ClarificationMessage` whose
        `author_role` is `SPECIALIST` and whose `sequence_no` is one greater than the
        count of prior messages on the consult, increments `clarification_rounds`,
        moves the consult from `ASSIGNED` to `CLARIFICATION_REQUESTED`, and increments
        the consult's `version`."
        PRD §3.4: "The reply appends a message with `author_role` set to
        `REFERRING_PROVIDER` and the next `sequence_no`, moves the consult back from
        `CLARIFICATION_REQUESTED` to `ASSIGNED`, and — because answering a
        clarification is compensable work — appends a `CLARIFICATION_FEE` compensation
        entry at the track's `clarification_fee_cents` with posture `PROVISIONAL`,
        adding the same amount to the membership's `provisional_balance_cents`."

        Design: Corner/state_machines/clarification_cycle_sequences_messages
        """
        scenario = setup_assigned_consult(
            patient_ref="PAT-S4", provider_npi="1000002004",
            specialist_npi="2000002004",
            consult_overrides={
                "question_text": "Statin intolerance with CK elevation history; asks about ezetimibe monotherapy for LDL goal.",
                "icd10_primary": "E78",
            },
        )
        consult = scenario["consult"]
        spec_h = make_specialist_headers(scenario["specialist"]["id"])
        prov_h = make_provider_headers(scenario["provider"]["id"])

        first = validate_success(api.create_clarification(
            consult["id"], {"body": "What was the peak CK and which statin at what dose?"}, spec_h
        ), 201)
        assert first["sequence_no"] == 1
        assert first["author_role"] == "SPECIALIST"
        mid = get_consult(consult["id"])
        assert mid["status"] == "CLARIFICATION_REQUESTED"
        assert mid["clarification_rounds"] == 1

        second = validate_success(api.create_clarification(
            consult["id"],
            {"body": "Peak CK 1200 on atorvastatin 40mg, resolved on discontinuation."},
            prov_h,
        ), 201)
        assert second["sequence_no"] == 2
        assert second["author_role"] == "REFERRING_PROVIDER"
        assert get_consult(consult["id"])["status"] == "ASSIGNED"

        # The provider's answer posts one PROVISIONAL CLARIFICATION_FEE (2500).
        summary = get_summary(scenario["membership"]["id"])
        assert summary["provisional_balance_cents"] == 2500

    def test_third_clarification_request_returns_max_rounds(self, api):
        """PRD §3.4: "The program allows at most 2 specialist-initiated clarification
        rounds per consult; when `clarification_rounds` has already reached that
        ceiling, the request is rejected with `ERR_MAX_CLARIFICATION_ROUNDS_REACHED`."

        Design: Corner/state_machines/third_clarification_request_returns_max_rounds
        """
        scenario = setup_assigned_consult(
            patient_ref="PAT-S5", provider_npi="1000002005",
            specialist_npi="2000002005",
            consult_overrides={
                "question_text": "Resistant hypertension on three agents; asks about spironolactone addition and potassium monitoring.",
                "icd10_primary": "I10",
            },
        )
        consult = scenario["consult"]
        spec_h = make_specialist_headers(scenario["specialist"]["id"])
        prov_h = make_provider_headers(scenario["provider"]["id"])
        # Two complete clarification cycles (specialist asks, provider answers).
        for q, a in (
            ("Current doses and latest potassium and creatinine?",
             "Amlodipine 10, lisinopril 40, HCTZ 25; K 4.1, Cr 1.0 last week."),
            ("Any history of hyperkalemia or eGFR below 45?",
             "No hyperkalemia; eGFR 78. Home BP log attached to chart."),
        ):
            validate_success(api.create_clarification(consult["id"], {"body": q}, spec_h), 201)
            validate_success(api.create_clarification(consult["id"], {"body": a}, prov_h), 201)

        res = api.create_clarification(
            consult["id"],
            {"body": "One more detail: is the patient on any NSAID regularly?"},
            spec_h,
        )
        validate_error(res, ApiErrorId.ERR_MAX_CLARIFICATION_ROUNDS_REACHED,
                       expected_status=409)
        after = get_consult(consult["id"])
        assert after["clarification_rounds"] == 2
        assert after["status"] == "ASSIGNED"

    def test_response_then_finalize_moves_only_billing_axis(self, api):
        """PRD §3.5: "The consult itself moves from `ASSIGNED` to `ANSWERED`, its
        `billing_status` moves from `UNBILLABLE` to `PENDING_DOCUMENTATION`, and its
        `version` increments."
        PRD §3.6: "The consult's `billing_status` moves from `PENDING_DOCUMENTATION`
        to `CHARGEABLE`."

        Design: Difficulty/non_linear_state_machine/consult_parallel_status_and_billing_dimensions
        """
        scenario = setup_answered_consult(
            patient_ref="PAT-NL1", provider_npi="1000000041",
            specialist_npi="2000000041",
            consult_overrides={
                "question_text": "Stable angina, asks whether to switch from atenolol to amlodipine monotherapy given fatigue.",
                "icd10_primary": "I20",
            },
            response_overrides={
                "recommendation_text": "Trial amlodipine 5mg with atenolol taper over 2 weeks; monitor for rebound tachycardia.",
            },
        )
        consult = scenario["consult"]
        after_answer = get_consult(consult["id"])
        assert after_answer["status"] == "ANSWERED"
        assert after_answer["billing_status"] == "PENDING_DOCUMENTATION"

        document_response(scenario["response"]["id"], scenario["provider"]["id"],
                          scenario["specialist"]["id"])
        finalize_response(scenario["response"]["id"], scenario["specialist"]["id"])
        after_finalize = get_consult(consult["id"])
        # Finalize advances ONLY the billing axis; the workflow axis stays ANSWERED.
        assert after_finalize["status"] == "ANSWERED"
        assert after_finalize["billing_status"] == "CHARGEABLE"

    def test_claim_submit_then_close_moves_disjoint_axes(self, api):
        """PRD §3.9: "A successful submission moves the claim to `SUBMITTED` and
        advances the consult's `billing_status` from `CHARGEABLE` to `CLAIMED`."
        PRD §3.6: "Only after finalization may the owning provider close the consult,
        moving it from `ANSWERED` to `CLOSED`."

        Design: Difficulty/non_linear_state_machine/consult_parallel_status_and_billing_dimensions
        """
        scenario = setup_finalized_consult(
            patient_ref="PAT-NL1", provider_npi="1000000041",
            specialist_npi="2000000041",
        )
        consult = scenario["consult"]
        claim = validate_success(api.create_billing_claim(consult["id"], BILLING), 201)
        validate_success(api.submit_claim(claim["id"], BILLING), 200)
        after_submit = get_consult(consult["id"])
        # Claim submission advances ONLY the billing axis.
        assert after_submit["status"] == "ANSWERED"
        assert after_submit["billing_status"] == "CLAIMED"

        closed = validate_success(api.close_consult(
            consult["id"], make_provider_headers(scenario["provider"]["id"])
        ), 200)
        # Close advances ONLY the workflow axis.
        assert closed["status"] == "CLOSED"
        assert closed["billing_status"] == "CLAIMED"

    def test_close_blocked_until_response_finalized(self, api):
        """PRD §3.6: "Closing requires the consult to be `ANSWERED`
        (`ERR_CONSULT_NOT_ANSWERED`), the caller to be the owner
        (`ERR_NOT_CONSULT_OWNER`), and — a cross-entity dependency — the consult's
        response to be `FINALIZED` (`ERR_RESPONSE_NOT_FINALIZED`)."

        Design: Difficulty/cross_entity_state_dependency/consult_close_gated_by_response_finalized
        """
        scenario = setup_answered_consult(
            patient_ref="PAT-CE1", provider_npi="1000000121",
            specialist_npi="2000000121",
            consult_overrides={
                "question_text": "Wants to discontinue amiodarone due to thyroid concerns; asks for alternative antiarrhythmic strategy.",
                "icd10_primary": "I48",
            },
        )
        # Response is merely SUBMITTED: the cross-entity gate must reject the close.
        res = api.close_consult(
            scenario["consult"]["id"],
            make_provider_headers(scenario["provider"]["id"]),
        )
        validate_error(res, ApiErrorId.ERR_RESPONSE_NOT_FINALIZED, expected_status=409)
        assert get_consult(scenario["consult"]["id"])["status"] == "ANSWERED"

    def test_close_succeeds_after_response_finalized(self, api):
        """PRD §3.6: "Only after finalization may the owning provider close the
        consult, moving it from `ANSWERED` to `CLOSED`. Closing requires the consult
        to be `ANSWERED` (`ERR_CONSULT_NOT_ANSWERED`), the caller to be the owner
        (`ERR_NOT_CONSULT_OWNER`), and — a cross-entity dependency — the consult's
        response to be `FINALIZED` (`ERR_RESPONSE_NOT_FINALIZED`)."

        Design: Difficulty/cross_entity_state_dependency/consult_close_gated_by_response_finalized
        """
        scenario = setup_answered_consult(
            patient_ref="PAT-CE1", provider_npi="1000000121",
            specialist_npi="2000000121",
        )
        document_response(scenario["response"]["id"], scenario["provider"]["id"],
                          scenario["specialist"]["id"])
        finalized = finalize_response(scenario["response"]["id"],
                                      scenario["specialist"]["id"])
        assert finalized["status"] == "FINALIZED"
        closed = validate_success(api.close_consult(
            scenario["consult"]["id"],
            make_provider_headers(scenario["provider"]["id"]),
        ), 200)
        assert closed["status"] == "CLOSED"

    def test_stale_version_on_patch_rejected(self, api):
        """PRD §2.7: "Amending a consult's structured question requires the client to
        present `expected_consult_version` carrying the consult's `version` it last
        observed; if any intervening mutation — a prior amendment, a routing event, a
        clarification, a response, or a cascade — has advanced the version, the
        amendment is stale and is rejected with `ERR_STALE_CONSULT_VERSION`
        (HTTP 412)."
        PRD §2.4: "The `version` field is a system-managed integer that starts at its
        initial value on creation and increments by one on every modification to the
        resource"

        Design: Corner/validations/stale_version_on_patch_rejected
        """
        scenario = setup_assigned_consult(
            patient_ref="PAT-V1", provider_npi="1000004002",
            specialist_npi="2000004002",
            consult_overrides={
                "question_text": "Anticoagulation choice in AF with CKD stage 3; asks about apixaban dosing thresholds.",
                "icd10_primary": "I48",
            },
        )
        consult = scenario["consult"]
        prov_h = make_provider_headers(scenario["provider"]["id"])
        stale_version = consult["version"]
        patched = validate_success(api.patch_consult_request(
            consult["id"],
            {"question_text": "Anticoagulation choice in AF with CKD stage 3b; asks about apixaban dose reduction criteria.",
             "expected_consult_version": stale_version},
            prov_h,
        ), 200)
        assert patched["version"] == stale_version + 1

        res = api.patch_consult_request(
            consult["id"],
            {"question_text": "Anticoagulation choice in AF with CKD stage 3b and prior GI bleed; safest agent selection?",
             "expected_consult_version": stale_version},
            prov_h,
        )
        validate_error(res, ApiErrorId.ERR_STALE_CONSULT_VERSION, expected_status=412)
        # The consult reflects the first amendment only.
        after = get_consult(consult["id"])
        assert after["question_text"].endswith("dose reduction criteria.")

    def test_stale_version_on_reroute_rejected(self, api):
        """PRD §2.7: "Re-running the routing selector for a queued consult is guarded
        the same way: the request must carry `expected_consult_version` matching the
        consult's current `version`, and a mismatch is rejected with
        `ERR_STALE_CONSULT_VERSION` (HTTP 412)."

        Design: Corner/validations/stale_version_on_reroute_rejected
        """
        scenario = setup_queued_consult_scenario(
            specialty_code="NEUROLOGY", provider_npi="1000004003",
            patient_ref="PAT-V2",
            consult_overrides={
                "question_text": "Essential tremor on propranolol; asks about primidone addition and driving restrictions.",
                "icd10_primary": "G25",
            },
        )
        consult = scenario["consult"]
        assert consult["status"] == "QUEUED"
        stale_version = consult["version"]
        # An intervening amendment advances the version.
        patched = validate_success(api.patch_consult_request(
            consult["id"],
            {"urgency": "URGENT", "expected_consult_version": stale_version},
            make_provider_headers(scenario["provider"]["id"]),
        ), 200)
        current_version = patched["version"]
        assert current_version == stale_version + 1
        # A panel seat appears: rerouting is now otherwise legitimate.
        spec = create_specialist(npi="2000004003", full_name="Dr. Nora Neurologist")
        membership = create_membership(spec["id"], scenario["track"]["id"])
        create_window(membership["id"], spec["id"])

        res = api.reroute_consult(
            consult["id"], {"expected_consult_version": stale_version}, COORD
        )
        validate_error(res, ApiErrorId.ERR_STALE_CONSULT_VERSION, expected_status=412)
        # With the fresh version the same reroute succeeds.
        rerouted = validate_success(api.reroute_consult(
            consult["id"], {"expected_consult_version": current_version}, COORD
        ), 200)
        assert rerouted["status"] == "ASSIGNED"
        assert rerouted["assigned_membership_id"] == membership["id"]

    def test_create_then_get_reflects_writes_immediately(self, api):
        """PRD §3.2: "The winning membership is recorded on the consult through
        `assigned_specialist_id` and `assigned_membership_id`, its
        `open_consult_count` increases by one (which refreshes the membership's
        `updated_at` and increments its `version`), and the consult lands in
        `ASSIGNED`."
        PRD §2.4: "The `version` field is a system-managed integer that starts at its
        initial value on creation and increments by one on every modification to the
        resource"

        Design: Corner/consistency_model/create_then_get_reflects_writes_immediately
        """
        scenario = setup_assigned_consult(
            patient_ref="PAT-IM1", provider_npi="1000008001",
            specialist_npi="2000008001",
            consult_overrides={
                "question_text": "Routine question about ambulatory blood pressure monitoring interpretation thresholds.",
                "icd10_primary": "R03",
            },
        )
        consult = scenario["consult"]
        # The very next read reflects the create's outcome: ASSIGNED and the
        # 48-hour routine SLA computed from the logical clock.
        fetched = validate_success(api.get_consult_request(consult["id"], COORD), 200)
        assert fetched["status"] == "ASSIGNED"
        assert _parse(fetched["sla_due_at"]) == datetime(2026, 6, 3, tzinfo=timezone.utc)
        assert fetched["version"] == consult["version"]

        # A PATCH is visible immediately afterwards: version +1, new icd10_primary.
        validate_success(api.patch_consult_request(
            consult["id"],
            {"icd10_primary": "R04", "expected_consult_version": consult["version"]},
            make_provider_headers(scenario["provider"]["id"]),
        ), 200)
        after = validate_success(api.get_consult_request(consult["id"], COORD), 200)
        assert after["version"] == consult["version"] + 1
        assert after["icd10_primary"] == "R04"

    def test_consult_list_pagination_envelope(self, api):
        """PRD §2.3: "The `limit` parameter caps the number of items returned: it
        defaults to 10, with a minimum of 1 and a maximum of 100. The `offset`
        parameter specifies how many items to skip and defaults to 0."
        PRD §2.3: "Unless otherwise specified, every list endpoint returns resources
        sorted by `created_at` in ascending order, and the `meta` object of a list
        response carries the four pagination fields `limit`, `offset`, `total_count`,
        and `has_more`."

        Design: Corner/endpoints/consult_list_pagination_envelope
        """
        scenario = setup_panel_scenario(provider_npi="1000005001",
                                        specialist_npi="2000005001")
        track_id = scenario["track"]["id"]
        prov_id = scenario["provider"]["id"]
        for patient_ref, question, icd in (
            ("PAT-PG1", "Question one about anticoagulation duration after provoked deep vein thrombosis.", "I82"),
            ("PAT-PG2", "Question two about beta blocker selection in a patient with mild intermittent asthma.", "I10"),
            ("PAT-PG3", "Question three about statin intensity targets after a non-ST elevation infarction.", "I21"),
        ):
            create_consult(track_id, prov_id, patient_ref=patient_ref,
                           question_text=question, icd10_primary=icd)

        page1, meta1 = validate_paginated(api.list_consult_requests(
            COORD, params={"referring_provider_id": prov_id, "limit": 2, "offset": 0}
        ))
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True
        assert meta1["limit"] == 2
        assert meta1["offset"] == 0

        page2, meta2 = validate_paginated(api.list_consult_requests(
            COORD, params={"referring_provider_id": prov_id, "limit": 2, "offset": 2}
        ))
        assert len(page2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False
