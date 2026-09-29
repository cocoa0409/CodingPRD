"""Operations whose admissibility is decided by a field on some *other* entity.

In each case the row being written is itself perfectly well formed, and only the
state of a parent, a sibling or a second dimension of the same row refuses it.
"""
from test_helpers import (
    BILLING,
    CASE_OPENER,
    CONSULTANT,
    PRINCIPAL,
    api_client,
    add_onboarded_household,
    attest_handoff,
    attest_handoff_payload,
    countersign_agreement_payload,
    create_household,
    create_requisition_payload,
    create_trial_engagement_payload,
    find_milestone,
    finalize_scope,
    invoice_milestone,
    make_client_headers,
    open_requisition,
    prepare_payroll_handoff,
    publish_fee_schedule,
    read_candidate,
    read_client,
    read_handoff,
    read_milestone,
    read_milestones,
    read_requisition,
    run_scoping_round,
    setup_senior_scenario,
    sign_agreement_payload,
    update_handoff_ein,
    validate_error,
    validate_paginated,
)

MARCHMONT = {
    "household_name": "Marchmont Row",
    "primary_contact_email": "ops@marchmont.example",
    "region_code": "NY",
}
MARCHMONT_REQUISITION = {
    "role_type": "CHEF",
    "first_year_compensation_cents": 9_000_000,
    "schedule_pattern": "FIVE_TWO",
    "live_in_required": False,
}
NORBURY = {
    "household_name": "Norbury Hall",
    "primary_contact_email": "ops@norbury.example",
    "region_code": "NY",
}


def _signed_but_not_countersigned():
    """A household that has signed the agreement and is waiting on the agency."""
    client = create_household(**MARCHMONT)
    signed = api_client.confidentiality_agreement(
        client["id"],
        sign_agreement_payload(signatory_name="W. Marchmont"),
        make_client_headers(client["id"]),
    )
    assert signed.status_code == 200, signed.text
    body = signed.json()["data"]
    assert body["confidentiality_agreement_status"] == "SIGNED"
    assert body["status"] == "PROSPECT"
    publish_fee_schedule(
        role_type="CHEF",
        comp_band_floor_cents=0,
        comp_band_ceiling_cents=15_000_000,
        fee_percent_bps=2000,
        guarantee_window_days=120,
        effective_from="2026-01-01",
    )
    return body


class TestRequisitionDependsOnTheAgreement:
    def test_01_a_signed_but_uncountersigned_household_cannot_open_a_search(self):
        """The refusal is decided by a field on the parent household.

        PRD §3.1: "Two household gates apply before the row is written: a
        household whose `confidentiality_agreement_status` is anything other than
        `COUNTERSIGNED` is refused with `ERR_NDA_NOT_COUNTERSIGNED` (HTTP 409) —
        the child's admissibility is decided by a field on its parent — and a
        household whose `status` is `SUSPENDED` is refused with
        `ERR_CLIENT_SUSPENDED` (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/requisition_creation_depends_on_the_client_nda_being_countersigned
        """
        client = _signed_but_not_countersigned()

        response = api_client.create_requisition(
            create_requisition_payload(client["id"], **MARCHMONT_REQUISITION),
            CONSULTANT,
        )
        validate_error(response, "ERR_NDA_NOT_COUNTERSIGNED")

        rows, meta = validate_paginated(
            api_client.list_requisitions(CONSULTANT, {"client_id": client["id"]})
        )
        assert rows == []
        assert meta["total_count"] == 0

    def test_02_the_countersignature_admits_the_identical_body(self):
        """Nothing about the request changed; only the parent moved.

        PRD §3.1: "Countersignature advances that field from `SIGNED` to
        `COUNTERSIGNED`, stamps `countersigned_at` with the current logical-clock
        instant, and drives the household lifecycle `PROSPECT → ONBOARDED` — the
        only path by which a household becomes eligible for role scoping —
        incrementing `Client.version` by 1."

        Design: Difficulty/cross_entity_state_dependency/requisition_creation_depends_on_the_client_nda_being_countersigned
        """
        client = _signed_but_not_countersigned()
        payload = create_requisition_payload(client["id"], **MARCHMONT_REQUISITION)
        validate_error(
            api_client.create_requisition(payload, CONSULTANT),
            "ERR_NDA_NOT_COUNTERSIGNED",
        )

        countersigned = api_client.confidentiality_agreement(
            client["id"], countersign_agreement_payload(), PRINCIPAL
        )
        assert countersigned.status_code == 200, countersigned.text
        parent = countersigned.json()["data"]
        assert parent["confidentiality_agreement_status"] == "COUNTERSIGNED"
        assert parent["status"] == "ONBOARDED"
        assert parent["countersigned_at"] is not None
        assert parent["version"] == client["version"] + 1

        accepted = api_client.create_requisition(payload, CONSULTANT)
        assert accepted.status_code == 201, accepted.text
        requisition = accepted.json()["data"]
        assert requisition["status"] == "DRAFT"
        assert requisition["scoping_round"] == 0
        assert requisition["resolved_fee_schedule_id"] is None

        rows, _ = validate_paginated(
            api_client.list_requisitions(CONSULTANT, {"client_id": client["id"]})
        )
        assert len(rows) == 1
        assert rows[0]["id"] == requisition["id"]


class TestStartDateMilestoneDependsOnTheHandoff:
    def _placement_with_a_prepared_handoff(self):
        scenario = setup_senior_scenario(stage="placement_active")
        milestones = read_milestones(scenario["placement"])
        scenario["engagement"] = invoice_milestone(
            find_milestone(milestones, "ENGAGEMENT")
        )
        scenario["start_date_milestone"] = find_milestone(milestones, "START_DATE")
        scenario["handoff"] = prepare_payroll_handoff(
            scenario["placement"],
            provider_name="HomePay Bureau",
            guidance_packet_version="v2026.3",
            ein_status="APPLIED",
        )
        return scenario

    def test_03_the_dependency_is_specific_to_the_start_date_milestone(self):
        """The engagement fee bills with the handoff still PREPARED.

        PRD §3.7: "Additionally, for a `START_DATE` milestone, a `PayrollHandoff`
        of that placement must have reached `status` `ATTESTED`, or the invoice is
        refused with `ERR_PAYROLL_HANDOFF_NOT_ATTESTED` (HTTP 409) — a cross-arm
        gate in which the compliance desk blocks the billing desk."

        Design: Difficulty/cross_entity_state_dependency/start_date_milestone_invoice_depends_on_an_attested_payroll_handoff
        """
        scenario = self._placement_with_a_prepared_handoff()
        assert scenario["engagement"]["invoice_status"] == "INVOICED"
        assert scenario["engagement"]["amount_cents"] == 1_004_850
        assert scenario["handoff"]["status"] == "PREPARED"

        response = api_client.invoice_fee_milestone(
            scenario["start_date_milestone"]["id"],
            {"note": "Attempted before attestation."},
            BILLING,
        )
        validate_error(response, "ERR_PAYROLL_HANDOFF_NOT_ATTESTED")

        unchanged = read_milestone(scenario["start_date_milestone"])
        assert unchanged["invoice_status"] == "PENDING"
        assert unchanged["due_date"] is None
        assert read_client(scenario["client"])["outstanding_balance_cents"] == 1_004_850

    def test_04_attestation_itself_depends_on_the_ein_having_been_issued(self):
        """A second cross-field gate stands between PREPARED and ATTESTED.

        PRD §3.7: "The handoff must be `PREPARED`, or the request is refused with
        `ERR_ENTITY_TERMINAL`, and its `ein_status` must be exactly `ISSUED`, or it
        is refused with `ERR_EIN_NOT_ISSUED` (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/start_date_milestone_invoice_depends_on_an_attested_payroll_handoff
        """
        scenario = self._placement_with_a_prepared_handoff()
        handoff = scenario["handoff"]
        assert handoff["ein_status"] == "APPLIED"

        response = api_client.attest_payroll_handoff(
            handoff["id"],
            attest_handoff_payload(attested_by_name="M. Ashford"),
            scenario["client_headers"],
        )
        validate_error(response, "ERR_EIN_NOT_ISSUED")
        assert read_handoff(handoff)["status"] == "PREPARED"

        issued = update_handoff_ein(handoff, "ISSUED")
        assert issued["ein_status"] == "ISSUED"
        assert issued["status"] == "PREPARED"

        attested = attest_handoff(
            issued, scenario["client_headers"], attested_by_name="M. Ashford"
        )
        assert attested["status"] == "ATTESTED"
        assert attested["attested_by_name"] == "M. Ashford"
        assert attested["attested_at"] is not None

    def test_05_attestation_unblocks_the_previously_refused_invoice(self):
        """The same invoice call is accepted once the sibling row is ATTESTED.

        PRD §3.7: "Attestation moves the handoff `PREPARED → ATTESTED`, stamps
        `attested_by_name` and `attested_at` from the logical clock, increments
        `PayrollHandoff.version`, and is the single act that unblocks the
        `START_DATE` milestone for invoicing."

        Design: Difficulty/cross_entity_state_dependency/start_date_milestone_invoice_depends_on_an_attested_payroll_handoff
        """
        scenario = self._placement_with_a_prepared_handoff()
        validate_error(
            api_client.invoice_fee_milestone(
                scenario["start_date_milestone"]["id"], None, BILLING
            ),
            "ERR_PAYROLL_HANDOFF_NOT_ATTESTED",
        )
        attest_handoff(
            update_handoff_ein(scenario["handoff"], "ISSUED"),
            scenario["client_headers"],
            attested_by_name="M. Ashford",
        )

        invoiced = invoice_milestone(scenario["start_date_milestone"])
        assert invoiced["invoice_status"] == "INVOICED"
        assert invoiced["amount_cents"] == 1_339_799
        assert invoiced["invoiced_on"] == "2026-09-01"
        assert invoiced["due_date"] == "2026-09-15"
        assert read_client(scenario["client"])["outstanding_balance_cents"] == 2_344_649

    def test_06_only_one_handoff_may_exist_per_placement(self):
        """The gate reads a single sibling row, and there is only ever one.

        PRD §3.7: "Only one handoff may exist per placement, and a second attempt
        is refused with `ERR_PAYROLL_HANDOFF_EXISTS` (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/start_date_milestone_invoice_depends_on_an_attested_payroll_handoff
        """
        scenario = self._placement_with_a_prepared_handoff()

        response = api_client.create_payroll_handoff(
            scenario["placement"]["id"],
            {"provider_name": "Second Bureau", "guidance_packet_version": "v2026.4"},
            CASE_OPENER,
        )
        validate_error(response, "ERR_PAYROLL_HANDOFF_EXISTS")

        rows, _ = validate_paginated(
            api_client.list_placement_payroll_handoffs(
                scenario["placement"]["id"], CASE_OPENER
            )
        )
        assert len(rows) == 1
        assert rows[0]["id"] == scenario["handoff"]["id"]


class TestBookingReadsBothCandidateDimensions:
    def _placed_candidate_and_a_rival_search(self):
        scenario = setup_senior_scenario(stage="placement_active")
        rival = add_onboarded_household(
            household_name=NORBURY["household_name"],
            primary_contact_email=NORBURY["primary_contact_email"],
            region_code=NORBURY["region_code"],
        )
        requisition = open_requisition(
            rival,
            role_type="ESTATE_MANAGER",
            first_year_compensation_cents=16_000_000,
            schedule_pattern="FIVE_TWO",
            live_in_required=True,
        )
        requisition = run_scoping_round(
            requisition, scope_note="Rival household seeking the same profile."
        )
        scenario["rival"] = rival
        scenario["rival_requisition"] = finalize_scope(requisition)
        return scenario

    def test_07_a_placed_candidate_is_refused_on_the_availability_axis(self):
        """Vetting says CLEARED and the score is 74; availability still refuses.

        PRD §3.4: "The candidate's `availability_status` must be exactly
        `AVAILABLE`, and any other value, including `ON_TRIAL` for a different
        household, is refused with `ERR_CANDIDATE_UNAVAILABLE`."

        Design: Difficulty/cross_entity_state_dependency/trial_booking_depends_on_both_candidate_dimensions_at_once
        """
        scenario = self._placed_candidate_and_a_rival_search()
        candidate = read_candidate(scenario["candidate"])
        assert candidate["vetting_status"] == "CLEARED"
        assert candidate["screening_score"] == 74
        assert candidate["availability_status"] == "PLACED"

        response = api_client.create_trial_engagement(
            scenario["rival_requisition"]["id"],
            create_trial_engagement_payload(
                candidate["id"],
                engagement_type="TRIAL_DAY",
                day_rate_cents=45_000,
                start_at="2026-09-27T09:00:00Z",
                end_at="2026-09-27T17:00:00Z",
            ),
            CONSULTANT,
        )
        error = validate_error(response, "ERR_CANDIDATE_UNAVAILABLE")
        assert error["error_id"] != "ERR_CANDIDATE_NOT_VETTED"

        rows, _ = validate_paginated(
            api_client.list_trial_engagements(
                CONSULTANT, {"requisition_id": scenario["rival_requisition"]["id"]}
            )
        )
        assert rows == []
        assert read_candidate(candidate)["availability_status"] == "PLACED"

    def test_08_nothing_on_the_rival_household_side_is_at_fault(self):
        """The second search is onboarded, scoped and priced, and stays empty.

        PRD §3.4: "The candidate's `vetting_status` must be one of
        `REFERENCES_VERIFIED`, `BACKGROUND_PENDING` or `CLEARED` — a trial may
        deliberately be run while the background screen is still outstanding — and
        anything else, including `UNVETTED`, `SCREENING` and `REJECTED`, is
        refused with `ERR_CANDIDATE_NOT_VETTED`."

        Design: Difficulty/cross_entity_state_dependency/trial_booking_depends_on_both_candidate_dimensions_at_once
        """
        scenario = self._placed_candidate_and_a_rival_search()
        rival = read_client(scenario["rival"])
        assert rival["status"] == "ONBOARDED"
        assert rival["confidentiality_agreement_status"] == "COUNTERSIGNED"

        requisition = scenario["rival_requisition"]
        assert requisition["status"] == "SOURCING"
        assert requisition["fee_percent_bps"] == 2233
        assert requisition["provisional_fee_cents"] == 3_572_800

        validate_error(
            api_client.create_trial_engagement(
                requisition["id"],
                create_trial_engagement_payload(
                    scenario["candidate"]["id"],
                    engagement_type="TRIAL_DAY",
                    day_rate_cents=45_000,
                    start_at="2026-09-27T09:00:00Z",
                    end_at="2026-09-27T17:00:00Z",
                ),
                CONSULTANT,
            ),
            "ERR_CANDIDATE_UNAVAILABLE",
        )

        after = read_requisition(requisition)
        assert after["status"] == "SOURCING"
        assert after["active_trial_count"] == 0
        assert after["version"] == requisition["version"]
