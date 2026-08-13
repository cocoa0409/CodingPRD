"""Facility onboarding, CMS attestation lifecycle, and civil monetary penalty."""
from test_helpers import (
    ApiErrorId,
    create_facility,
    get_success_data,
    is_iso8601_timestamp,
    is_valid_uuid,
    setup_rejected_attestation,
    setup_submitted_attestation,
    validate_error,
    validate_paginated,
)
from test_helpers.fixtures import ADMIN, AUDITOR


class TestFacilityCreate:
    def test_facility_create_applies_defaults(self, api):
        """PRD section 3.1: "A `PlatformAdmin` begins by registering each hospital facility, supplying its `name`, its CMS Certification Number in `cms_certification_number`, its licensed `bed_count`, and optionally its enforcement and certification posture: `penalty_policy` (`SIMPLE` or `TIERED`, defaulting to `SIMPLE`), `min_records_per_cycle` (defaulting to 1), `shoppable_min_entries` (defaulting to the CMS-required 300), `mandated_min_entries` (defaulting to the CMS-specified 70), and the consumer-display feature flag `shoppable_display_enabled` (defaulting to true)."
        PRD section 3.1: "A new facility's `attestation_status` is `NONE`, its `attestation_year`, `attestation_cycle_id`, `rejected_at`, and `plan_due_date` are all null, and `penalty_accrued_cents` is zero."

        Design: Corner/entities/facility_create_applies_defaults_and_system_fields
        """
        data = create_facility(name="F", cms_certification_number="CCN-E1",
                               bed_count=50)
        assert data["penalty_policy"] == "SIMPLE"
        assert data["shoppable_min_entries"] == 300
        assert data["mandated_min_entries"] == 70
        assert data["min_records_per_cycle"] == 1
        assert data["shoppable_display_enabled"] is True
        assert data["attestation_status"] == "NONE"
        assert data["attestation_year"] is None
        assert data["attestation_cycle_id"] is None
        assert data["rejected_at"] is None
        assert data["plan_due_date"] is None
        assert data["penalty_accrued_cents"] == 0
        assert is_valid_uuid(data["id"])
        assert is_iso8601_timestamp(data["created_at"])
        assert is_iso8601_timestamp(data["updated_at"])
        assert isinstance(data["version"], int) and data["version"] >= 1

    def test_facility_create_duplicate_ccn_rejected(self, api):
        """PRD section 3.1: "The certification number is unique across the platform; a duplicate registration is rejected with `ERR_DUPLICATE_CCN`."

        Design: Corner/entities/facility_create_duplicate_ccn_rejected
        """
        create_facility(name="F", cms_certification_number="CCN-E2",
                        bed_count=50)
        resp = api.create_facility(
            {"name": "G", "cms_certification_number": "CCN-E2",
             "bed_count": 75}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_CCN)


class TestAttestationGuards:
    def test_attestation_year_must_match_logical_clock_year(self, api):
        """PRD section 3.6: "The supplied year must equal the calendar year of the current logical clock (`ERR_ATTESTATION_YEAR_MISMATCH`), and a resubmission from `CLOSED` must name a year different from the facility's previous `attestation_year`."
        PRD section 2.9: "Requests are validated against a fixed priority ladder, and a request that fails several rungs is rejected with the error from the earliest failing rung."

        Design: Corner/validations/attestation_year_must_match_logical_clock_year
        """
        fac = create_facility(name="F", cms_certification_number="CCN-H10",
                              bed_count=50)
        resp = api.submit_attestation(fac["id"], {"attestation_year": 2025},
                                      AUDITOR)
        # The logical clock reads 2026-08-01 at startup (year 2026); the
        # regulatory-safety rung fires before the containment rung even
        # though this facility also has no containing ANNUAL cycle.
        validate_error(resp, ApiErrorId.ERR_ATTESTATION_YEAR_MISMATCH)

    def test_attestation_without_containing_annual_cycle(self, api):
        """PRD section 3.6: "The attestation must rest on evidence: the facility must have an `ANNUAL` cycle in `PUBLISHED` status whose half-open coverage window fully contains the attestation calendar year — from January 1 through December 31 of `attestation_year` — or submission is rejected with `ERR_NO_CONTAINING_ANNUAL_CYCLE`."

        Design: Corner/validations/attestation_without_containing_annual_cycle
        """
        fac = create_facility(name="F", cms_certification_number="CCN-H11",
                              bed_count=50)
        resp = api.submit_attestation(fac["id"], {"attestation_year": 2026},
                                      AUDITOR)
        validate_error(resp, ApiErrorId.ERR_NO_CONTAINING_ANNUAL_CYCLE)

    def test_attestation_decision_from_wrong_state_rejected(self, api):
        """PRD section 3.6: "`ACCEPT_ATTESTATION` applies from `SUBMITTED` and moves the facility to `ACCEPTED`; penalty accrual stops, and `rejected_at` remains null."
        PRD section 3.6: "Each decision is defined only from one attestation status, and any other pairing is rejected with `ERR_ATTESTATION_INVALID_STATE`."

        Design: Corner/state_machines/attestation_decision_from_wrong_state_rejected
        """
        fac = create_facility(name="F", cms_certification_number="CCN-SM12",
                              bed_count=50)
        resp = api.cms_decision(fac["id"], {"decision": "ACCEPT_ATTESTATION"},
                                ADMIN)
        validate_error(resp, ApiErrorId.ERR_ATTESTATION_INVALID_STATE)


class TestAttestationEnforcement:
    def test_attestation_escalation_after_plan_deadline_then_late_plan(
            self, api):
        """PRD section 3.6: "If the logical clock advances strictly past `plan_due_date` before a plan arrives, the system moves the facility `REJECTED → ESCALATED`, where penalties keep accruing."
        PRD section 3.6: "Independently, a `ComplianceAuditor` may submit a corrective-action plan carrying its `plan_text`, moving the facility from `REJECTED` or `ESCALATED` to `PLAN_SUBMITTED` (any other attestation status is again `ERR_ATTESTATION_INVALID_STATE`)."

        Design: Corner/state_machines/attestation_escalation_after_plan_deadline_then_late_plan
        """
        ctx = setup_rejected_attestation(
            facility_overrides={"name": "FS",
                                "cms_certification_number": "CCN-SM6",
                                "bed_count": 25, "penalty_policy": "SIMPLE"})
        fid = ctx["facility"]["id"]
        # 2026-09-05 is strictly past plan_due_date 2026-09-01 -> escalate.
        get_success_data(api.set_clock(
            {"to_iso8601": "2026-09-05T00:00:00Z"}, ADMIN))
        fac = get_success_data(api.get_facility(fid, AUDITOR))
        assert fac["attestation_status"] == "ESCALATED"
        # 35 whole days from rejected_at 2026-08-01 through 2026-09-05,
        # 30000 cents/day under SIMPLE; accrual continues from the original
        # rejection through escalation.
        assert fac["penalty_accrued_cents"] == 35 * 30000
        # A late plan still submits from ESCALATED.
        fac = get_success_data(api.submit_plan(
            fid, {"plan_text": "Corrective action: republish within 30 days"},
            AUDITOR))
        assert fac["attestation_status"] == "PLAN_SUBMITTED"

    def test_file_retracted_when_attestation_rejected(self, api):
        """PRD section 3.6: "`REJECT_ATTESTATION` also applies from `SUBMITTED` and moves the facility to `REJECTED`, stamping `rejected_at` with the current logical clock and storing the supplied `plan_due_date`; in the same request, every `PUBLISHED` machine-readable file of the pinned `attestation_cycle_id` cycle is retracted, moving `PUBLISHED → RETRACTED` on its generation dimension."

        Design: Corner/state_machines/file_retracted_when_attestation_rejected
        """
        ctx = setup_submitted_attestation(
            facility_overrides={"name": "F",
                                "cms_certification_number": "CCN-SM8",
                                "bed_count": 120})
        fac = get_success_data(api.cms_decision(
            ctx["facility"]["id"],
            {"decision": "REJECT_ATTESTATION",
             "plan_due_date": "2026-09-01T00:00:00Z"}, ADMIN))
        assert fac["attestation_status"] == "REJECTED"
        files, _meta = validate_paginated(
            api.list_machine_files(ctx["cycle"]["id"], AUDITOR))
        assert len(files) == 1
        assert files[0]["generation_status"] == "RETRACTED"


class TestPenaltyAccrualVariants:
    def test_penalty_simple_variant_three_days(self, api):
        """PRD section 3.6: "Under the `SIMPLE` penalty policy the accrual is a flat 30000 cents (300 dollars) per elapsed day regardless of size."
        PRD section 3.6: "The variants diverge materially: a 25-bed facility three days into rejection accrues 30000 cents under `TIERED` but 90000 cents under `SIMPLE`."

        Design: Difficulty/dual_variant_calc/penalty_accrual_simple_vs_tiered
        """
        ctx = setup_rejected_attestation(
            facility_overrides={"name": "FS",
                                "cms_certification_number": "CCN-FS",
                                "bed_count": 25, "penalty_policy": "SIMPLE"})
        get_success_data(api.set_clock(
            {"to_iso8601": "2026-08-04T00:00:00Z"}, ADMIN))
        fac = get_success_data(
            api.get_facility(ctx["facility"]["id"], AUDITOR))
        assert fac["penalty_accrued_cents"] == 90000  # 3 days x 30000
        # 2026-08-04 is still before plan_due_date 2026-09-01: no escalation.
        assert fac["attestation_status"] == "REJECTED"

    def test_penalty_tiered_variant_three_days(self, api):
        """PRD section 3.6: "Under the `TIERED` policy the daily rate is bracketed by `bed_count`: 10000 cents (100 dollars) per day at 30 beds or fewer, 20000 cents (200 dollars) per day from 31 through 199 beds, and 40000 cents (400 dollars) per day at 200 beds or more."
        PRD section 3.6: "The variants diverge materially: a 25-bed facility three days into rejection accrues 30000 cents under `TIERED` but 90000 cents under `SIMPLE`."

        Design: Difficulty/dual_variant_calc/penalty_accrual_simple_vs_tiered
        """
        ctx = setup_rejected_attestation(
            facility_overrides={"name": "FT",
                                "cms_certification_number": "CCN-FT",
                                "bed_count": 25, "penalty_policy": "TIERED"})
        get_success_data(api.set_clock(
            {"to_iso8601": "2026-08-04T00:00:00Z"}, ADMIN))
        fac = get_success_data(
            api.get_facility(ctx["facility"]["id"], AUDITOR))
        # Identical dates and bed_count as the SIMPLE case, but the TIERED
        # variant selects the 30-beds-or-fewer bracket: 3 days x 10000.
        assert fac["penalty_accrued_cents"] == 30000
        assert fac["attestation_status"] == "REJECTED"

    def test_penalty_day_zero_at_rejection(self, api):
        """PRD section 3.6: "The elapsed time is the number of whole days between `rejected_at` and the current logical clock — the elapsed seconds divided by the 86,400 seconds of a full day, truncated down, and never negative."
        PRD section 3.6: "Under the `SIMPLE` penalty policy the accrual is a flat 30000 cents (300 dollars) per elapsed day regardless of size."

        Design: Difficulty/boundary_precision_check/penalty_accrual_day_zero_and_day_one_boundary
        """
        ctx = setup_rejected_attestation(
            facility_overrides={"name": "FS",
                                "cms_certification_number": "CCN-B2",
                                "bed_count": 25, "penalty_policy": "SIMPLE"})
        # The clock still reads 2026-08-01T00:00:00Z — exactly rejected_at —
        # so zero whole days have elapsed.
        fac = get_success_data(
            api.get_facility(ctx["facility"]["id"], AUDITOR))
        assert fac["penalty_accrued_cents"] == 0
        assert fac["attestation_status"] == "REJECTED"

    def test_penalty_day_one_boundary(self, api):
        """PRD section 3.6: "The elapsed time is the number of whole days between `rejected_at` and the current logical clock — the elapsed seconds divided by the 86,400 seconds of a full day, truncated down, and never negative."
        PRD section 3.6: "Under the `SIMPLE` penalty policy the accrual is a flat 30000 cents (300 dollars) per elapsed day regardless of size."

        Design: Difficulty/boundary_precision_check/penalty_accrual_day_zero_and_day_one_boundary
        """
        ctx = setup_rejected_attestation(
            facility_overrides={"name": "FS",
                                "cms_certification_number": "CCN-B2",
                                "bed_count": 25, "penalty_policy": "SIMPLE"})
        # Exactly 86400 seconds after rejected_at 2026-08-01T00:00:00Z.
        get_success_data(api.set_clock(
            {"to_iso8601": "2026-08-02T00:00:00Z"}, ADMIN))
        fac = get_success_data(
            api.get_facility(ctx["facility"]["id"], AUDITOR))
        assert fac["penalty_accrued_cents"] == 30000  # exactly 1 day
        # 2026-08-02 < plan_due_date 2026-09-01: no escalation yet.
        assert fac["attestation_status"] == "REJECTED"

    def test_penalty_tiered_top_bracket_bed_200(self, api):
        """PRD section 3.6: "Under the `TIERED` policy the daily rate is bracketed by `bed_count`: 10000 cents (100 dollars) per day at 30 beds or fewer, 20000 cents (200 dollars) per day from 31 through 199 beds, and 40000 cents (400 dollars) per day at 200 beds or more."

        Design: Corner/calculations/penalty_tiered_top_bracket_bed_200
        """
        ctx = setup_rejected_attestation(
            facility_overrides={"name": "FZ",
                                "cms_certification_number": "CCN-K8",
                                "bed_count": 200, "penalty_policy": "TIERED"})
        get_success_data(api.set_clock(
            {"to_iso8601": "2026-08-02T00:00:00Z"}, ADMIN))
        fac = get_success_data(
            api.get_facility(ctx["facility"]["id"], AUDITOR))
        # 200 beds selects the 200-beds-or-more bracket: 1 day x 40000.
        assert fac["penalty_accrued_cents"] == 40000
