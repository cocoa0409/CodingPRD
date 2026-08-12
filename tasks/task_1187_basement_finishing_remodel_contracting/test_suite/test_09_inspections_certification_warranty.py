"""Inspections, certification cascade, project completion, and warranty claims."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_inspection_payload,
    create_warranty_claim_payload,
    get_success_data,
    make_contractor_headers,
    make_homeowner_headers,
    make_subcontractor_headers,
    set_logical_clock,
    setup_completed_project,
    setup_in_progress_project,
    validate_error,
    validate_success,
)

INSPECTOR = TEST_USERS["inspector_headers"]


class TestFinalPassCertificationCascade:
    def test_final_pass_issues_certificate_with_warranty_window(self, api):
        """PRD §3.8: "A passing final fires the certification cascade: a Certificate
        is created with `issued_at` set to the current logical clock,
        `warranty_start` equal to the issue date, and `warranty_end` 730 days later"

        Design: Difficulty/transitive_cascade/final_pass_certification_cascade
        """
        ctx = setup_completed_project(clock_iso="2026-06-10T00:00:00Z")
        assert ctx["inspection"]["status"] == "PASSED"
        cert = ctx["certificate"]
        assert cert["warranty_start"] == "2026-06-10"
        assert cert["warranty_end"] == "2028-06-09", "warranty_end is 730 days later"
        assert cert["status"] == "ACTIVE"

    def test_final_pass_completes_project_and_closes_permit(self, api):
        """PRD §3.8: "the project's `ISSUED` permit moves to `CLOSED`; and the project
        itself moves from `IN_PROGRESS` to `COMPLETED`, incrementing its `version`."

        Design: Difficulty/transitive_cascade/final_pass_certification_cascade
        """
        ctx = setup_completed_project(clock_iso="2026-06-10T00:00:00Z")
        ctr_h = make_contractor_headers(ctx["contractor"]["id"])
        assert ctx["project"]["status"] == "COMPLETED"
        permits = api.list_permits(ctx["project"]["id"], ctr_h).json()["data"]
        assert permits[0]["status"] == "CLOSED"


class TestExpiredWarrantyClaim:
    def _setup_expired_certificate(self, api):
        """COMPLETED project; clock advanced past the certificate's warranty_end."""
        ctx = setup_completed_project(address="11 K St", basement_sqft=650,
                                      base_contract_cents=3200000,
                                      clock_iso="2026-06-10T00:00:00Z")
        set_logical_clock("2028-07-01T00:00:00Z")
        return ctx

    def test_expired_certificate_claim_temporal_error_wins(self, api):
        """PRD §2.6: "the warranty window before claim amounts"
        PRD §3.9: "the claim's creation date must be on or before the certificate's
        `warranty_end` and the certificate must still be `ACTIVE`, otherwise filing
        is rejected with `ERR_WARRANTY_EXPIRED`."

        Design: Difficulty/priority_pair_validation_conflict/expired_warranty_temporal_beats_claim_amount
        """
        ctx = self._setup_expired_certificate(api)
        ho_h = make_homeowner_headers(ctx["homeowner"]["id"])
        # claimed_cents == 0 also breaches the fiscal floor, but the warranty-window
        # check is earlier in the fixed validation order.
        res = api.create_warranty_claim(
            ctx["project"]["id"],
            create_warranty_claim_payload(
                ctx["certificate"]["id"],
                description="musty smell returns",
                claimed_cents=0,
                fresh_slab_moisture_lbs=4.5,
                fresh_interior_rh_pct=68,
            ),
            ho_h,
        )
        validate_error(res, ApiErrorId.ERR_WARRANTY_EXPIRED)

    def test_certificate_expires_on_clock_sweep(self, api):
        """PRD §2.5: "A certificate still `ACTIVE` whose `warranty_end` is before the
        new current date moves to `EXPIRED`."

        Design: Difficulty/priority_pair_validation_conflict/expired_warranty_temporal_beats_claim_amount
        """
        ctx = self._setup_expired_certificate(api)
        ctr_h = make_contractor_headers(ctx["contractor"]["id"])
        cert = get_success_data(
            api.get_certificate(ctx["certificate"]["id"], ctr_h)
        )
        assert cert["status"] == "EXPIRED"
        assert cert["warranty_end"] == "2028-06-09"


class TestWarrantyAwardCalculation:
    def _setup_proration_project(self, api, clock_iso):
        """COMPLETED project with certificate issued 2026-06-10 (baseline slab 2.0);
        clock advanced to the claim date."""
        ctx = setup_completed_project(clock_iso="2026-06-10T00:00:00Z")
        set_logical_clock(clock_iso)
        return ctx

    def test_proration_at_day_370_and_award_cap(self, api):
        """PRD §3.9: "A confirmed recurrence is covered at 100 percent regardless of
        elapsed time; otherwise coverage is 100 percent within the first 365 days and
        50 percent through day 730."
        PRD §3.9: "On approval, `awarded_cents` is the claimed amount capped at
        200000 cents — a two-thousand-dollar ceiling — multiplied by the coverage
        percentage divided by 100 and rounded half up to whole cents"

        Design: Corner/calculations/warranty_proration_cap_and_invalid_amount
        """
        ctx = self._setup_proration_project(api, "2027-06-15T00:00:00Z")
        ctr_h = make_contractor_headers(ctx["contractor"]["id"])
        ho_h = make_homeowner_headers(ctx["homeowner"]["id"])
        cert_id = ctx["certificate"]["id"]

        # Claim A: 180000 at 50% coverage -> 90000.
        wc_a = get_success_data(
            api.create_warranty_claim(
                ctx["project"]["id"],
                create_warranty_claim_payload(
                    cert_id, description="paint peeling", claimed_cents=180000,
                    fresh_slab_moisture_lbs=2.5, fresh_interior_rh_pct=55,
                ),
                ho_h,
            )
        )
        assert wc_a["coverage_pct"] == 50, "preview at filing shows the 50% tier"
        decided_a = validate_success(
            api.decide_warranty_claim(
                wc_a["id"], {"outcome": "APPROVED", "notes": "valid"}, ctr_h
            ),
            200,
        )
        assert decided_a["awarded_cents"] == 90000

        # Claim B: 250000 hits the 200000 ceiling first -> 100000.
        wc_b = get_success_data(
            api.create_warranty_claim(
                ctx["project"]["id"],
                create_warranty_claim_payload(
                    cert_id, description="floor replacement", claimed_cents=250000,
                    fresh_slab_moisture_lbs=2.4, fresh_interior_rh_pct=52,
                ),
                ho_h,
            )
        )
        decided_b = validate_success(
            api.decide_warranty_claim(wc_b["id"], {"outcome": "APPROVED"}, ctr_h), 200
        )
        assert decided_b["awarded_cents"] == 100000

    def test_zero_amount_claim_rejected_inside_window(self, api):
        """PRD §3.9: "the `claimed_cents` amount — which must be greater than zero, or
        filing is rejected with `ERR_INVALID_CLAIM_AMOUNT`"
        PRD §3.9: "Claims are listable per project — filterable by `status` — and per
        certificate."

        Design: Corner/calculations/warranty_proration_cap_and_invalid_amount
        """
        ctx = self._setup_proration_project(api, "2027-06-15T00:00:00Z")
        ctr_h = make_contractor_headers(ctx["contractor"]["id"])
        ho_h = make_homeowner_headers(ctx["homeowner"]["id"])
        cert_id = ctx["certificate"]["id"]
        for desc, amount in (("paint peeling", 180000), ("floor replacement", 250000)):
            wc = get_success_data(
                api.create_warranty_claim(
                    ctx["project"]["id"],
                    create_warranty_claim_payload(
                        cert_id, description=desc, claimed_cents=amount,
                        fresh_slab_moisture_lbs=2.4, fresh_interior_rh_pct=52,
                    ),
                    ho_h,
                )
            )
            validate_success(
                api.decide_warranty_claim(wc["id"], {"outcome": "APPROVED"}, ctr_h),
                200,
            )
        res = api.create_warranty_claim(
            ctx["project"]["id"],
            create_warranty_claim_payload(
                cert_id, description="zero claim", claimed_cents=0,
                fresh_slab_moisture_lbs=2.4, fresh_interior_rh_pct=52,
            ),
            ho_h,
        )
        validate_error(res, ApiErrorId.ERR_INVALID_CLAIM_AMOUNT)
        claims = api.list_certificate_claims(cert_id, ctr_h).json()["data"]
        assert len(claims) == 2, "only the two persisted claims are listed"

    def test_moisture_recurrence_override_full_coverage(self, api):
        """PRD §3.9: "`moisture_recurrence_confirmed` is true exactly when
        `fresh_slab_moisture_lbs` is at least the baseline plus 1.5 pounds."
        PRD §3.9: "A confirmed recurrence is covered at 100 percent regardless of
        elapsed time; otherwise coverage is 100 percent within the first 365 days and
        50 percent through day 730."

        Design: Corner/calculations/moisture_recurrence_override_full_coverage
        """
        ctx = self._setup_proration_project(api, "2027-07-15T00:00:00Z")
        ctr_h = make_contractor_headers(ctx["contractor"]["id"])
        ho_h = make_homeowner_headers(ctx["homeowner"]["id"])
        # Baseline ACCEPTED assessment slab is 2.0; fresh 4.0 >= 2.0 + 1.5.
        wc = get_success_data(
            api.create_warranty_claim(
                ctx["project"]["id"],
                create_warranty_claim_payload(
                    ctx["certificate"]["id"],
                    description="moisture returned behind drywall",
                    claimed_cents=180000,
                    fresh_slab_moisture_lbs=4.0,
                    fresh_interior_rh_pct=66,
                ),
                ho_h,
            )
        )
        decided = validate_success(
            api.decide_warranty_claim(
                wc["id"], {"outcome": "APPROVED", "notes": "recurrence confirmed"},
                ctr_h,
            ),
            200,
        )
        assert decided["moisture_recurrence_confirmed"] is True
        assert decided["coverage_pct"] == 100
        assert decided["awarded_cents"] == 180000


class TestFinalInspectionTargeting:
    def test_final_inspection_requires_all_phases_finished(self, api):
        """PRD §3.8: "a `ROUGH_IN` request must name the `work_phase_id` of a phase of
        this project currently `IN_PROGRESS`, and a `FINAL` request requires every
        work phase of the project to be `COMPLETED` or `CANCELLED`; a breach of
        either rule is rejected with `ERR_PHASES_INCOMPLETE`."

        Design: Corner/validations/final_inspection_requires_phases_completed
        """
        ctx = setup_in_progress_project(
            trade="GENERAL", zone="REC", address="V10 St",
            phase_overrides={"start_date": "2026-06-01", "end_date": "2026-06-08"},
        )
        ctr_h = make_contractor_headers(ctx["contractor"]["id"])
        res = api.create_inspection(
            ctx["project"]["id"], create_inspection_payload(type="FINAL"), ctr_h
        )
        validate_error(res, ApiErrorId.ERR_PHASES_INCOMPLETE)

        validate_success(
            api.complete_work_phase(
                ctx["phase"]["id"],
                make_subcontractor_headers(ctx["subcontractor"]["id"]),
            ),
            200,
        )
        insp = validate_success(
            api.create_inspection(
                ctx["project"]["id"], create_inspection_payload(type="FINAL"), ctr_h
            ),
            201,
        )
        assert insp["status"] == "REQUESTED"
