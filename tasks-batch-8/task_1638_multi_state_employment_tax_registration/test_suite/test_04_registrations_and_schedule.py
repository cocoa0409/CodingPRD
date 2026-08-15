"""Registration lifecycle: nexus gate, reject/resubmit cycle, schedule variants,
closure settlement, computed reads, and OCC on the Employer version."""
from test_helpers import (
    ANALYST,
    ApiErrorId,
    create_employee,
    create_employer,
    create_registration,
    create_state_withholding_agency,
    create_work_location,
    get_employer,
    get_obligations,
    get_success_data,
    make_payroll_compliance_lead_headers,
    open_nexus_case,
    recompute_nexus_case,
    confirm_nexus_case,
    set_clock,
    setup_confirmed_nexus,
    setup_withholding_registration_active,
    submit_registration,
    validate_error,
    validate_success,
)


class TestProvisionalVsLookback:
    def test_activation_assigns_provisional_semiweekly(self, api):
        """PRD §3.4: "For withholding registrations at activation, the provisional
        variant reads `projected_annual_withholding_cents`: below 250,000 cents ($2,500)
        the frequency is `QUARTERLY`; at least 250,000 cents and at most 5,000,000 cents
        it is `MONTHLY`; above 5,000,000 cents it is `SEMIWEEKLY`."
        PRD §3.4: "Activation records `frequency_basis` as `PROVISIONAL`."

        Design: Difficulty/dual_variant_calc/deposit_frequency_provisional_vs_lookback_diverge
        """
        out = setup_withholding_registration_active(
            projected=100_000_000, account_number="OR-00000001",
            employee_wages=(1_000_000,),
        )
        assert out["registration"]["filing_frequency"] == "SEMIWEEKLY", (
            "projected 100,000,000 cents is above 5,000,000"
        )
        assert out["registration"]["frequency_basis"] == "PROVISIONAL"

    def test_lookback_recompute_overrides_provisional_to_quarterly(self, api, nexus_analyst_headers):
        """PRD §3.4: "A `NexusAnalyst` can trigger schedule recomputation, which applies
        the lookback variant: `lookback_liability_cents` sums `amount_due_cents` over the
        registration's `WITHHOLDING_DEPOSIT` and `WITHHOLDING_RETURN` obligations whose
        `period_end` lies within the trailing four closed calendar quarters and whose
        status is `DUE`, `LATE`, `FILED`, `CONFIRMED`, or `WAIVED`; the same three
        thresholds classify that sum into a frequency, and `frequency_basis` becomes
        `LOOKBACK`."
        PRD §3.4: "Provisional and lookback bases can legitimately disagree for
        identical registration data — one reads an input estimate, the other trailing
        actuals."

        Design: Difficulty/dual_variant_calc/deposit_frequency_provisional_vs_lookback_diverge
        """
        out = setup_withholding_registration_active(
            projected=100_000_000, account_number="OR-00000001",
            employee_wages=(1_000_000,),
        )
        registration = out["registration"]
        assert registration["filing_frequency"] == "SEMIWEEKLY"
        res = api.recompute_registration_schedule(registration["id"], nexus_analyst_headers)
        recomputed = validate_success(res, 200)
        assert recomputed["filing_frequency"] == "QUARTERLY", (
            "no closed-quarter obligations exist, so lookback liability is 0 (< 250,000)"
        )
        assert recomputed["frequency_basis"] == "LOOKBACK"
        assert recomputed["filing_frequency"] != registration["filing_frequency"]


class TestProvisionalFrequencyBoundary:
    def _setup_two_registrations(self):
        """OR-WH and NJ-WH agencies; OR + NJ employees; both cases CONFIRMED; one
        DRAFT registration per agency (OR projected 5,000,000; NJ 5,000,001)."""
        employer = create_employer()
        ag_or = create_state_withholding_agency(
            state_code="OR", agency_name="Oregon DOR", withholding_rate_bp=500,
        )
        ag_nj = create_state_withholding_agency(
            state_code="NJ", agency_name="NJ Div Tax", withholding_rate_bp=600,
        )
        wl_or = create_work_location("OR")
        wl_nj = create_work_location("NJ")
        create_employee(wl_or["id"], employee_ref="E-1021", full_name="V One",
                        resident_state_code="OR", annual_wage_cents=3_000_000)
        create_employee(wl_nj["id"], employee_ref="E-1022", full_name="V Two",
                        resident_state_code="NJ", annual_wage_cents=3_000_000)
        nc_or = open_nexus_case("OR")
        nc_nj = open_nexus_case("NJ")
        set_clock("2026-08-20T00:00:00Z")
        recompute_nexus_case(nc_or["id"])
        confirm_nexus_case(nc_or["id"])
        recompute_nexus_case(nc_nj["id"])
        confirm_nexus_case(nc_nj["id"])
        employer = get_employer(employer["id"])
        reg_or = create_registration(ag_or["id"], 5_000_000, employer["version"])
        submit_registration(reg_or["id"])
        employer = get_employer(employer["id"])
        reg_nj = create_registration(ag_nj["id"], 5_000_001, employer["version"])
        submit_registration(reg_nj["id"])
        return reg_or, reg_nj

    def test_projected_exactly_5000000_is_monthly(self, api):
        """PRD §3.4: "at least 250,000 cents and at most 5,000,000 cents it is
        `MONTHLY`; above 5,000,000 cents it is `SEMIWEEKLY`. The boundary values land
        as written — exactly 250,000 cents and exactly 5,000,000 cents are both
        `MONTHLY`."

        Design: Difficulty/boundary_precision_check/provisional_frequency_50k_boundary
        """
        reg_or, _reg_nj = self._setup_two_registrations()
        res = api.activate_registration(
            reg_or["id"], {"account_number": "OR-00000005"}, ANALYST
        )
        activated = validate_success(res, 200)
        assert activated["filing_frequency"] == "MONTHLY", (
            "projected exactly 5,000,000 cents is inside the MONTHLY band"
        )

    def test_projected_5000001_is_semiweekly(self, api):
        """PRD §3.4: "above 5,000,000 cents it is `SEMIWEEKLY`. The boundary values
        land as written — exactly 250,000 cents and exactly 5,000,000 cents are both
        `MONTHLY`."

        Design: Difficulty/boundary_precision_check/provisional_frequency_50k_boundary
        """
        _reg_or, reg_nj = self._setup_two_registrations()
        res = api.activate_registration(
            reg_nj["id"], {"account_number": "NJ-00000001"}, ANALYST
        )
        activated = validate_success(res, 200)
        assert activated["filing_frequency"] == "SEMIWEEKLY", (
            "projected 5,000,001 cents is strictly above the MONTHLY ceiling"
        )


class TestRejectResubmitCycle:
    def _setup_draft_or_registration(self):
        out = setup_confirmed_nexus(state_code="OR", employee_wages=(3_000_000,))
        agency = create_state_withholding_agency(
            state_code="OR", agency_name="Oregon DOR", withholding_rate_bp=500,
        )
        employer = get_employer(out["employer"]["id"])
        registration = create_registration(agency["id"], 1_000_000, employer["version"])
        out.update(agency=agency, registration=registration)
        return out

    def test_submit_reject_resubmit_status_sequence(self, api, nexus_analyst_headers):
        """PRD §3.4: "Submission moves the registration to `SUBMITTED` from either
        `DRAFT` or `REJECTED` (any other state draws `ERR_INVALID_STATE_TRANSITION`)"
        PRD §3.4: "An agency rejection — recorded by a `NexusAnalyst` with a
        `rejection_reason` copied onto the record — moves `SUBMITTED` to `REJECTED`,
        and the submit-reject-resubmit loop can repeat as often as the agency requires."

        Design: Difficulty/non_linear_state_machine/registration_reject_resubmit_cycle
        """
        registration = self._setup_draft_or_registration()["registration"]
        first = validate_success(
            api.submit_registration(registration["id"], nexus_analyst_headers), 200
        )
        assert first["status"] == "SUBMITTED"
        rejected = validate_success(
            api.reject_registration(
                registration["id"],
                {"rejection_reason": "Agency requested corrected FEIN"},
                nexus_analyst_headers,
            ),
            200,
        )
        assert rejected["status"] == "REJECTED"
        third = validate_success(
            api.submit_registration(registration["id"], nexus_analyst_headers), 200
        )
        assert third["status"] == "SUBMITTED", "resubmission from REJECTED is allowed"

    def test_resubmitted_registration_activates(self, api, nexus_analyst_headers):
        """PRD §3.4: "the submit-reject-resubmit loop can repeat as often as the agency
        requires."
        PRD §3.4: "a `NexusAnalyst` activates a `SUBMITTED` registration by supplying
        the agency-assigned `account_number`."

        Design: Difficulty/non_linear_state_machine/registration_reject_resubmit_cycle
        """
        registration = self._setup_draft_or_registration()["registration"]
        submit_registration(registration["id"])
        get_success_data(api.reject_registration(
            registration["id"],
            {"rejection_reason": "Agency requested corrected FEIN"},
            nexus_analyst_headers,
        ))
        submit_registration(registration["id"])
        activated = validate_success(
            api.activate_registration(
                registration["id"], {"account_number": "OR-00000003"},
                nexus_analyst_headers,
            ),
            200,
        )
        assert activated["status"] == "ACTIVE"
        assert activated["account_number"] == "OR-00000003"


class TestSubmitRequiresConfirmedNexus:
    def _setup_threshold_met_not_confirmed(self):
        """OR case at THRESHOLD_MET (20 days) but never confirmed; DRAFT registration."""
        employer = create_employer()
        agency = create_state_withholding_agency(
            state_code="OR", agency_name="Oregon DOR", withholding_rate_bp=500,
        )
        location = create_work_location("OR")
        create_employee(location["id"], employee_ref="E-1101", full_name="W One",
                        resident_state_code="OR", annual_wage_cents=3_000_000)
        case = open_nexus_case("OR")
        set_clock("2026-08-20T00:00:00Z")
        case = recompute_nexus_case(case["id"])
        assert case["status"] == "THRESHOLD_MET", "setup expects THRESHOLD_MET"
        # The WATCH->THRESHOLD_MET transition recomputed the Employer posture
        # (GOOD_STANDING -> WATCH), a mutation that bumped Employer.version
        # (PRD §2.7 + §2.5). Re-fetch so the OCC token below is current.
        employer = get_employer(employer["id"])
        registration = create_registration(agency["id"], 1_000_000, employer["version"])
        return case, registration

    def test_submit_at_threshold_met_rejected(self, api, nexus_analyst_headers):
        """PRD §3.4: "it is gated on nexus: the NexusCase for the registration's state
        must be `CONFIRMED`, else `ERR_NEXUS_NOT_CONFIRMED`."

        Design: Difficulty/cross_entity_state_dependency/registration_submit_requires_confirmed_nexus
        """
        _case, registration = self._setup_threshold_met_not_confirmed()
        res = api.submit_registration(registration["id"], nexus_analyst_headers)
        validate_error(res, ApiErrorId.ERR_NEXUS_NOT_CONFIRMED)

    def test_submit_after_confirm_succeeds(self, api, nexus_analyst_headers):
        """PRD §3.4: "Submission moves the registration to `SUBMITTED` from either
        `DRAFT` or `REJECTED` (any other state draws `ERR_INVALID_STATE_TRANSITION`),
        and it is gated on nexus: the NexusCase for the registration's state must be
        `CONFIRMED`, else `ERR_NEXUS_NOT_CONFIRMED`."

        Design: Difficulty/cross_entity_state_dependency/registration_submit_requires_confirmed_nexus
        """
        case, registration = self._setup_threshold_met_not_confirmed()
        err = api.submit_registration(registration["id"], nexus_analyst_headers)
        validate_error(err, ApiErrorId.ERR_NEXUS_NOT_CONFIRMED)
        confirm_nexus_case(case["id"])
        res = api.submit_registration(registration["id"], nexus_analyst_headers)
        assert validate_success(res, 200)["status"] == "SUBMITTED"


class TestRegistrationClosure:
    def test_close_with_scheduled_obligations_rejected(self, api, tax_director_headers):
        """PRD §3.4: "A `TaxDirector` closes an `ACTIVE` registration only when no
        obligation remains in `SCHEDULED`, `DUE`, or `LATE` and no linked notice is
        `RECEIVED`, `TRIAGED`, `RESPONSE_IN_PROGRESS`, or `ESCALATED`; otherwise the
        close is rejected with `ERR_REGISTRATION_NOT_SETTLED`."

        Design: Corner/validations/registration_close_with_open_obligations_rejected
        """
        out = setup_withholding_registration_active(
            projected=200_000, account_number="OR-00000013",
            employee_wages=(3_000_000,),
        )
        res = api.close_registration(out["registration"]["id"], tax_director_headers)
        validate_error(res, ApiErrorId.ERR_REGISTRATION_NOT_SETTLED)

    def test_close_then_activate_rejected_terminal_lockdown(self, api, nexus_analyst_headers,
                                                            tax_director_headers):
        """PRD §3.4: "A successful close stamps `closed_at`, recomputes
        `registered_state_count`, and lands the registration in terminal `CLOSED`."
        PRD §2.9: "The target resource is in a state from which the requested
        transition is allowed (terminal states are locked down, and a voluntary
        contribution may be created only against an `EFFECTIVE` rate), else
        `ERR_INVALID_STATE_TRANSITION` (HTTP 409)."

        Design: Corner/state_machines/registration_close_then_activate_rejected
        """
        out = setup_withholding_registration_active(
            projected=200_000, account_number="OR-00000007",
            employee_wages=(9_125_000,),
        )
        registration = out["registration"]
        set_clock("2026-10-01T00:00:00Z")
        deposits = get_obligations(registration["id"], obligation_kind="WITHHOLDING_DEPOSIT")
        returns = get_obligations(registration["id"], obligation_kind="WITHHOLDING_RETURN")
        assert len(deposits) == 1 and len(returns) == 1
        assert deposits[0]["status"] == "DUE", (
            "period_end 2026-09-30 has passed at clock 2026-10-01"
        )
        filer = make_payroll_compliance_lead_headers("pcl-1")
        confirmer = make_payroll_compliance_lead_headers("pcl-2")
        for row in (deposits[0], returns[0]):
            get_success_data(api.file_obligation(
                row["id"], {"filed_at": "2026-10-01T00:00:00Z"}, filer,
            ))
            get_success_data(api.confirm_obligation(row["id"], confirmer))
        closed = validate_success(
            api.close_registration(registration["id"], tax_director_headers), 200
        )
        assert closed["status"] == "CLOSED"
        res = api.activate_registration(
            registration["id"], {"account_number": "OR-XXXXXXXX"}, nexus_analyst_headers
        )
        validate_error(res, ApiErrorId.ERR_INVALID_STATE_TRANSITION)


class TestRegistrationReads:
    def test_registration_get_exposes_computed_fields(self, api, auditor_headers):
        """PRD §3.4: "The new record starts `DRAFT`; its `registration_kind` and
        `state_code` are copied from the agency."
        PRD §3.4: "Activation records `frequency_basis` as `PROVISIONAL`."
        PRD §3.4: "The `deposit_tier` is `NEXT_DAY` when any withholding-deposit
        obligation of the registration carries an `amount_due_cents` of at least
        1,000,000,000 cents (ten million dollars); otherwise `ACCELERATED` when the
        frequency is `SEMIWEEKLY`; otherwise `STANDARD`."

        Design: Corner/endpoints/registration_get_exposes_computed_fields
        """
        out = setup_withholding_registration_active(
            projected=200_000, account_number="OR-00000019",
            employee_wages=(3_000_000,),
        )
        res = api.get_registration(out["registration"]["id"], auditor_headers)
        data = validate_success(res, 200)
        assert data["account_number"] == "OR-00000019"
        assert data["filing_frequency"] == "QUARTERLY", (
            "projected 200,000 cents is below the 250,000-cent QUARTERLY cap"
        )
        assert data["frequency_basis"] == "PROVISIONAL"
        assert data["deposit_tier"] == "STANDARD"
        assert data["registration_kind"] == "STATE_WITHHOLDING"
        assert data["state_code"] == "OR"

    def test_registrations_filtered_list_by_agency(self, api, auditor_headers):
        """PRD §2.3: "List endpoints additionally accept the filter query parameters
        implied by their resource's field names (for example, filtering employees by
        `status` or `resident_state_code`, or registrations by `agency_id`)."

        Design: Corner/endpoints/registrations_filtered_list_by_agency
        """
        employer = create_employer()
        ag_or = create_state_withholding_agency(
            state_code="OR", agency_name="Oregon DOR", withholding_rate_bp=500,
        )
        ag_nj = create_state_withholding_agency(
            state_code="NJ", agency_name="NJ Div Tax", withholding_rate_bp=600,
        )
        reg_or = create_registration(ag_or["id"], 1_000_000, employer["version"])
        employer = get_employer(employer["id"])
        reg_nj = create_registration(ag_nj["id"], 1_000_000, employer["version"])
        res = api.list_registrations(auditor_headers, params={"agency_id": ag_or["id"]})
        data = validate_success(res, 200)
        assert len(data) == 1, f"expected exactly the OR row, got {len(data)}"
        assert data[0]["id"] == reg_or["id"]
        assert data[0]["agency_id"] == ag_or["id"]
        assert data[0]["status"] == "DRAFT"
        assert data[0]["id"] != reg_nj["id"]

    def test_duplicate_registration_same_agency_rejected(self, api, nexus_analyst_headers):
        """PRD §3.4: "Only one non-`CLOSED` registration may exist per agency — a second
        is `ERR_DUPLICATE_REGISTRATION` — and creation increments the Employer's
        `version` by one."

        Design: Corner/validations/duplicate_registration_same_agency_rejected
        """
        employer = create_employer()
        agency = create_state_withholding_agency(
            state_code="OR", agency_name="Oregon DOR", withholding_rate_bp=500,
        )
        create_registration(agency["id"], 1_000_000, employer["version"])
        employer = get_employer(employer["id"])
        res = api.create_registration(
            {
                "agency_id": agency["id"],
                "projected_annual_withholding_cents": 2_000_000,
                "expected_employer_version": employer["version"],
            },
            nexus_analyst_headers,
        )
        validate_error(res, ApiErrorId.ERR_DUPLICATE_REGISTRATION)


class TestRegistrationCreateOcc:
    def test_occ_registration_create_stale_employer(self, api, nexus_analyst_headers):
        """PRD §2.8: "Creating a Registration (`POST /etax/registrations`) requires
        `expected_employer_version` matching the Employer's current `version`, because
        creating a registration legitimately extends the employer's registration
        portfolio and a writer who has not observed that extension must not proceed."
        PRD §2.8: "if that value does not match the parent entity's current `version`,
        the write is rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_registration_create_stale_employer
        """
        employer = create_employer()
        observed_version = employer["version"]
        ag_or = create_state_withholding_agency(
            state_code="OR", agency_name="Oregon DOR", withholding_rate_bp=500,
        )
        ag_nj = create_state_withholding_agency(
            state_code="NJ", agency_name="NJ Div Tax", withholding_rate_bp=600,
        )
        first = api.create_registration(
            {
                "agency_id": ag_or["id"],
                "projected_annual_withholding_cents": 1_000_000,
                "expected_employer_version": observed_version,
            },
            nexus_analyst_headers,
        )
        validate_success(first, 201)
        employer = get_employer(employer["id"])
        assert employer["version"] == observed_version + 1, (
            "PRD §3.4: registration creation 'increments the Employer's `version` by one'"
        )
        stale = api.create_registration(
            {
                "agency_id": ag_nj["id"],
                "projected_annual_withholding_cents": 1_000_000,
                "expected_employer_version": observed_version,
            },
            nexus_analyst_headers,
        )
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION)
