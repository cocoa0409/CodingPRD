"""Loss assessment: scheduling buffers, evidence gates, drying-day variants.

Covers the per-assignee 30-minute travel buffer, the photo/moisture evidence
gate on completion, terminal-state lockdown of completed inspections, and the
two sanctioned drying-day classifications computed from the same readings.
"""
from test_helpers import (
    validate_success, validate_error, is_valid_uuid, ApiErrorId,
    make_claim_ctx, claim_to_assessing, schedule_inspection, add_photo,
    add_evidence_photos, add_reading, complete_inspection, TEST_USERS,
)

ADMIN = TEST_USERS["contractor_admin_headers"]
TECH = TEST_USERS["field_technician_headers"]


class TestDryingDayVariants:
    def test_drying_days_mean_vs_worst_reading(self, api):
        """PRD §3.3: "The **worst variant**, stored as `drying_days_worst_variant`,
        takes the single largest exceedance over all readings (zero when there are
        none): an exceedance of 8 or less classifies 1 drying day, greater than 8
        and at most 20 classifies 3, and greater than 20 classifies 5."
        PRD §3.3: "The **mean variant**, stored as `drying_days_mean_variant`,
        averages the exceedances over only the wet readings (zero when none are
        wet): a mean of 8 or less classifies 1 day, greater than 8 and at most 20
        classifies 2, and greater than 20 classifies 4."

        Design: Difficulty/dual_variant_calc/drying_days_mean_vs_worst_reading
        """
        ctx = make_claim_ctx(
            cause_of_loss="WATER",
            carrier_overrides={"name": "Acme Mutual", "tax_rate": 0.07},
            policy_overrides={"coverage_a_limit_cents": 100000000,
                              "flat_deductible_cents": 100000})
        claim_to_assessing(ctx)
        claim_id = ctx["claim"]["id"]
        insp = schedule_inspection(claim_id)
        add_evidence_photos(claim_id, insp["id"], tags=("AREA", "AREA", "MOISTURE_PROOF"))
        # exceedances 16 and 10, both wet (> 12 + 2)
        add_reading(insp["id"], reading_value=28, dry_standard=12,
                    recorded_at="2026-05-02T09:10:00Z")
        add_reading(insp["id"], reading_value=22, dry_standard=12,
                    recorded_at="2026-05-02T09:11:00Z")
        completed = complete_inspection(insp["id"])
        assert completed["drying_days_worst_variant"] == 3, \
            "max exceedance 16 -> band (8,20] -> 3 days"
        assert completed["drying_days_mean_variant"] == 2, \
            "mean exceedance 13 -> band (8,20] -> 2 days"
        assert completed["drying_days_worst_variant"] != completed["drying_days_mean_variant"]

    def test_drying_days_band_boundaries(self, api):
        """PRD §3.3: "an exceedance of 8 or less classifies 1 drying day, greater
        than 8 and at most 20 classifies 3, and greater than 20 classifies 5."
        PRD §3.3: "a mean of 8 or less classifies 1 day, greater than 8 and at most
        20 classifies 2, and greater than 20 classifies 4."

        Design: Difficulty/dual_variant_calc/drying_days_mean_vs_worst_reading
        """
        ctx = make_claim_ctx(
            cause_of_loss="WATER",
            carrier_overrides={"name": "Acme Mutual", "tax_rate": 0.07},
            policy_overrides={"coverage_a_limit_cents": 100000000,
                              "flat_deductible_cents": 100000})
        claim_to_assessing(ctx)
        claim_id = ctx["claim"]["id"]
        # one single-reading inspection per band edge: exceedance 8 / 20 / 21
        cases = [(20, (1, 1)), (32, (3, 2)), (33, (5, 4))]
        for i, (reading, (worst, mean)) in enumerate(cases):
            insp = schedule_inspection(claim_id, assignee_id=f"tech-b{i}")
            add_evidence_photos(claim_id, insp["id"])
            add_reading(insp["id"], reading_value=reading, dry_standard=12)
            completed = complete_inspection(insp["id"])
            assert completed["drying_days_worst_variant"] == worst, \
                f"exceedance {reading - 12} -> worst {worst}"
            assert completed["drying_days_mean_variant"] == mean, \
                f"mean exceedance {reading - 12} -> mean {mean}"


class TestSchedulingTravelBuffer:
    def test_exact_30_minute_gap_allowed_15_minute_gap_rejected(self, api):
        """PRD §3.3: "Scheduling also enforces a per-assignee travel buffer: for
        the same `assignee_id`, a new window conflicts with an existing scheduled
        window when the new start falls before the existing window's end plus 30
        minutes and the new end falls after the existing window's start minus 30
        minutes — the conflict is rejected with `ERR_INSPECTION_SCHEDULE_CONFLICT`
        (HTTP 409)."
        PRD §3.3: "A gap of exactly 30 minutes between windows is allowed."

        Design: Difficulty/resource_temporal_overlap/inspection_schedule_travel_buffer_conflict
        """
        ctx = make_claim_ctx(cause_of_loss="WATER",
                             carrier_overrides={"name": "Acme Mutual",
                                                "tax_rate": 0.07},
                             policy_overrides={"coverage_a_limit_cents": 100000000,
                                               "flat_deductible_cents": 100000})
        claim_to_assessing(ctx)
        claim_id = ctx["claim"]["id"]
        schedule_inspection(claim_id, assignee_id="tech-X",
                            start="2026-05-02T09:00:00Z",
                            end="2026-05-02T10:00:00Z")
        # exactly 30-minute gap after the existing window -> allowed
        i2 = validate_success(api.create_inspection(
            claim_id,
            {"type": "VERIFICATION", "assignee_id": "tech-X",
             "scheduled_start": "2026-05-02T10:30:00Z",
             "scheduled_end": "2026-05-02T11:30:00Z"}, TECH), 201)
        assert is_valid_uuid(i2["id"])
        # 15-minute gap: 10:15 < 10:00 + 30min -> conflict
        res = api.create_inspection(
            claim_id,
            {"type": "VERIFICATION", "assignee_id": "tech-X",
             "scheduled_start": "2026-05-02T10:15:00Z",
             "scheduled_end": "2026-05-02T11:00:00Z"}, TECH)
        validate_error(res, ApiErrorId.ERR_INSPECTION_SCHEDULE_CONFLICT)
        # different assignee: fully overlapping window is fine
        i3 = validate_success(api.create_inspection(
            claim_id,
            {"type": "VERIFICATION", "assignee_id": "tech-Y",
             "scheduled_start": "2026-05-02T09:30:00Z",
             "scheduled_end": "2026-05-02T10:30:00Z"}, TECH), 201)
        assert is_valid_uuid(i3["id"])

    def test_buffer_applies_on_the_before_side(self, api):
        """PRD §3.3: "a new window conflicts with an existing scheduled window when
        the new start falls before the existing window's end plus 30 minutes and
        the new end falls after the existing window's start minus 30 minutes"
        PRD §3.3: "A gap of exactly 30 minutes between windows is allowed."

        Design: Difficulty/resource_temporal_overlap/inspection_schedule_travel_buffer_conflict
        """
        ctx = make_claim_ctx(cause_of_loss="WATER")
        claim_to_assessing(ctx)
        claim_id = ctx["claim"]["id"]
        schedule_inspection(claim_id, assignee_id="tech-X",
                            start="2026-05-02T09:00:00Z",
                            end="2026-05-02T10:00:00Z")
        # ends exactly 30 minutes before the existing start -> allowed
        before_ok = validate_success(api.create_inspection(
            claim_id,
            {"type": "VERIFICATION", "assignee_id": "tech-X",
             "scheduled_start": "2026-05-02T07:30:00Z",
             "scheduled_end": "2026-05-02T08:30:00Z"}, TECH), 201)
        assert is_valid_uuid(before_ok["id"])
        # ends 15 minutes before the existing start (08:45 > 09:00 - 30min) -> conflict
        res = api.create_inspection(
            claim_id,
            {"type": "VERIFICATION", "assignee_id": "tech-X",
             "scheduled_start": "2026-05-02T08:00:00Z",
             "scheduled_end": "2026-05-02T08:45:00Z"}, TECH)
        validate_error(res, ApiErrorId.ERR_INSPECTION_SCHEDULE_CONFLICT)


class TestCompletionEvidenceGate:
    def test_inspection_evidence_gate_returns_422(self, api):
        """PRD §3.3: "At least 3 photos attached to this inspection with a tag of
        `LOSS_OVERVIEW`, `AREA`, or `MOISTURE_PROOF` must exist, and when the
        claim's `cause_of_loss` is `WATER` or `MOLD`, at least one moisture reading
        must exist on the inspection; failing either requirement rejects the
        completion with `ERR_INSPECTION_EVIDENCE_INSUFFICIENT` (HTTP 422)."

        Design: Corner/state_machines/inspection_evidence_gate_returns_422
        """
        ctx = make_claim_ctx(cause_of_loss="WATER",
                             carrier_overrides={"name": "Acme Mutual",
                                                "tax_rate": 0.07},
                             policy_overrides={"coverage_a_limit_cents": 100000000,
                                               "flat_deductible_cents": 100000})
        claim_to_assessing(ctx)
        claim_id = ctx["claim"]["id"]
        i1 = schedule_inspection(claim_id, assignee_id="tech-1")
        i2 = schedule_inspection(claim_id, assignee_id="tech-2")
        # I1: only 2 photos (photo count clause fails)
        add_photo(claim_id, inspection_id=i1["id"], tag="AREA", file_ref="a.jpg")
        add_photo(claim_id, inspection_id=i1["id"], tag="AREA", file_ref="b.jpg",
                  captured_at="2026-05-02T09:06:00Z")
        # I2: 3 photos but zero moisture readings on a WATER claim
        add_evidence_photos(claim_id, i2["id"], tags=("AREA", "AREA", "LOSS_OVERVIEW"))
        validate_error(api.complete_inspection(i1["id"], TECH),
                       ApiErrorId.ERR_INSPECTION_EVIDENCE_INSUFFICIENT)
        validate_error(api.complete_inspection(i2["id"], TECH),
                       ApiErrorId.ERR_INSPECTION_EVIDENCE_INSUFFICIENT)

    def test_inspection_complete_twice_returns_invalid_state(self, api):
        """PRD §3.3: "On completion the system stamps `completed_at` from the
        logical clock and computes two sanctioned drying-day classifications from
        the inspection's readings."
        PRD §2.7: "**State-machine legality** — the requested transition or action
        exists from the resource's current state, and child-creation state gates
        are satisfied (`ERR_INVALID_STATE_TRANSITION`, `ERR_CLAIM_NOT_PAYABLE`,
        `ERR_SUPPLEMENT_NOT_PERMITTED`, `ERR_ESTIMATE_NOT_EDITABLE`,
        `ERR_INVOICE_NOT_ISSUABLE`, `ERR_ROUND_NOT_OPEN`)."

        Design: Corner/state_machines/inspection_complete_twice_returns_invalid_state
        """
        ctx = make_claim_ctx(cause_of_loss="WATER",
                             carrier_overrides={"name": "Acme Mutual",
                                                "tax_rate": 0.07},
                             policy_overrides={"coverage_a_limit_cents": 100000000,
                                               "flat_deductible_cents": 100000})
        claim_to_assessing(ctx)
        insp = schedule_inspection(ctx["claim"]["id"])
        add_evidence_photos(ctx["claim"]["id"], insp["id"],
                            tags=("AREA", "AREA", "MOISTURE_PROOF"))
        add_reading(insp["id"], reading_value=20, dry_standard=12)
        completed = complete_inspection(insp["id"])
        assert completed["status"] == "COMPLETED"
        validate_error(api.complete_inspection(insp["id"], TECH),
                       ApiErrorId.ERR_INVALID_STATE_TRANSITION)
