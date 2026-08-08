"""Delivery: the four-link cascade, and the warranty and replacement clocks that
are deliberately built to disagree on a remake."""

from test_helpers import (
    assert_prosthesis,
    assert_same_instant,
    create_prosthesis_payload,
    fixtures as fx,
    validate_paginated,
    validate_success,
)


class TestDeliveryCascade:
    def test_delivery_moves_the_prosthesis_the_arch_and_the_case_in_one_request(self, api, prosthodontist_headers):
        """PRD §3.6: "**Link 1** creates the prosthesis row itself, in
        `warranty_status` `IN_WARRANTY` and `recall_status` `RECALL_SCHEDULED`, with
        `adjustments_used` at zero, `adjustments_remaining` at 4,
        `in_patient_possession` true, and `delivered_at` stamped with the logical
        clock."
        PRD §3.6: "**Link 2**, caused by link 1, moves the parent arch
        `READY_FOR_DELIVERY → DELIVERED` and increments the arch's `version` by 1."
        PRD §3.6: "**Link 3**, caused by link 2, bubbles the parent case
        `IN_FABRICATION → DELIVERED` once every arch of that case is either
        `DELIVERED` or `ARCH_ABANDONED` and at least one of them is `DELIVERED`;
        while any arch of the case is still in `PLANNED`, `IMPRESSION_PENDING`,
        `MILESTONE_PENDING`, `LAB_FABRICATION`, `READY_FOR_DELIVERY`, or
        `REMAKE_PENDING`, the case stays in `IN_FABRICATION`."

        Design: Difficulty/transitive_cascade/delivery_four_link_cascade_mints_a_draft_claim
        """
        ctx = fx.setup_arch_ready_for_delivery(
            quality_score=94,
            patient_overrides={
                "full_name": "Kirra Delacroix", "date_of_birth": "1948-02-02", "phone": "555-0322"
            },
            coverage_overrides={
                "carrier_name": "Meridian Dental",
                "rank": "PRIMARY",
                "effective_date": "2024-01-01T00:00:00Z",
                "annual_maximum_amount": 1500.00,
                "coinsurance_major_rate": 0.50,
            },
        )

        prosthesis = validate_success(
            api.create_prosthesis(
                create_prosthesis_payload(ctx["arch"]["id"]), prosthodontist_headers
            ),
            201,
        )

        assert_prosthesis(prosthesis)
        assert prosthesis["warranty_status"] == "IN_WARRANTY"
        assert prosthesis["recall_status"] == "RECALL_SCHEDULED"
        assert prosthesis["adjustments_remaining"] == 4
        assert fx.read_arch(ctx["arch"]["id"])["arch_status"] == "DELIVERED"
        case = fx.read_case(ctx["case"]["id"])
        assert case["case_status"] == "DELIVERED"
        assert_same_instant(
            case["delivered_at"], "2026-05-01T00:00:00.000Z", "ProsthesisCase.delivered_at"
        )

    def test_the_case_level_hop_mints_one_draft_claim_against_the_primary_coverage(self, api, front_office_headers):
        """PRD §3.6: "**Link 4**, caused by link 3, auto-creates exactly one claim for
        the case, in `DRAFT`, with its `coverage_id` set to the coverage of the case's
        patient whose `rank` is `PRIMARY` — but only when exactly one such coverage
        exists."
        PRD §3.6: "This leg fires only on the case-level transition to `DELIVERED`; a
        delivery that leaves the case in `IN_FABRICATION` mints no claim."
        PRD §3.6: "Its first due date is computed from the appliance type: 365 days
        after delivery for a `COMPLETE_DENTURE`, a `CAST_PARTIAL`, or a
        `FLEXIBLE_PARTIAL`; 180 days for an `OVERDENTURE` or an
        `IMPLANT_RETAINED_OVERDENTURE`; and only 90 days for an `IMMEDIATE_DENTURE`,
        which needs watching soonest."
        PRD §3.6: "`adjustment_window_ends_at` is `delivered_at` plus 90 calendar
        days, and it bounds the included-adjustment allowance of §3.7."

        Design: Difficulty/transitive_cascade/delivery_four_link_cascade_mints_a_draft_claim
        """
        ctx = fx.setup_arch_ready_for_delivery(
            quality_score=94,
            patient_overrides={
                "full_name": "Kirra Delacroix", "date_of_birth": "1948-02-02", "phone": "555-0322"
            },
            coverage_overrides={
                "carrier_name": "Meridian Dental",
                "rank": "PRIMARY",
                "effective_date": "2024-01-01T00:00:00Z",
                "annual_maximum_amount": 1500.00,
                "coinsurance_major_rate": 0.50,
            },
        )
        rows_before, meta_before = validate_paginated(
            api.list_claims(
                front_office_headers,
                params={"case_id": ctx["case"]["id"], "limit": 10, "offset": 0},
            )
        )
        assert meta_before["total_count"] == 0 and rows_before == []

        prosthesis = fx.deliver_prosthesis(ctx["arch"]["id"])

        rows, meta = validate_paginated(
            api.list_claims(
                front_office_headers,
                params={"case_id": ctx["case"]["id"], "limit": 10, "offset": 0},
            )
        )
        assert meta["total_count"] == 1
        claim = rows[0]
        assert claim["adjudication_status"] == "DRAFT"
        assert claim["coverage_id"] == ctx["coverage"]["id"]
        assert claim["submission_target"] == "PRIMARY"

        assert_same_instant(
            prosthesis["recall_due_at"], "2027-05-01T00:00:00.000Z", "Prosthesis.recall_due_at"
        )
        assert_same_instant(
            prosthesis["adjustment_window_ends_at"],
            "2026-07-30T00:00:00.000Z",
            "Prosthesis.adjustment_window_ends_at",
        )

    def test_the_delivery_response_already_carries_every_cascaded_field(self, api, prosthodontist_headers):
        """PRD §2.4: "Response projection is post-commit. The body a mutating call
        returns is the state of the resource *after* the write has been applied,
        including the already-incremented `version` and the already-refreshed
        `updated_at`."
        PRD §3.6: "`mandatory_reline_due_at` is `delivered_at` plus 180 calendar days
        **when the `prosthesis_type` is `IMMEDIATE_DENTURE`, and null for every other
        type**"
        PRD §3.6: "Finally, the patient's own counters move:
        `delivered_prosthesis_count` rises by one for a non-remake delivery, and
        `last_frequency_anchor_at` becomes the greatest `frequency_anchor_at` across
        the patient's appliances."

        Design: Corner/consistency_model/delivery_response_already_reflects_every_cascaded_field
        """
        ctx = fx.setup_arch_ready_for_delivery(
            patient_overrides={
                "full_name": "Vaino Laine", "date_of_birth": "1942-01-17", "phone": "555-1045"
            }
        )

        body = validate_success(
            api.create_prosthesis(
                create_prosthesis_payload(ctx["arch"]["id"]), prosthodontist_headers
            ),
            201,
        )

        assert_same_instant(body["delivered_at"], "2026-05-01T00:00:00.000Z", "delivered_at")
        assert_same_instant(
            body["warranty_expires_at"], "2027-05-01T00:00:00.000Z", "warranty_expires_at"
        )
        assert_same_instant(
            body["frequency_anchor_at"], "2026-05-01T00:00:00.000Z", "frequency_anchor_at"
        )
        assert_same_instant(
            body["replacement_eligible_date"],
            "2031-05-01T00:00:00.000Z",
            "replacement_eligible_date",
        )
        assert_same_instant(body["recall_due_at"], "2027-05-01T00:00:00.000Z", "recall_due_at")
        assert_same_instant(
            body["adjustment_window_ends_at"],
            "2026-07-30T00:00:00.000Z",
            "adjustment_window_ends_at",
        )
        assert body["warranty_status"] == "IN_WARRANTY"
        assert body["recall_status"] == "RECALL_SCHEDULED"
        assert body["adjustments_used"] == 0
        assert body["adjustments_remaining"] == 4
        assert body["in_patient_possession"] is True
        assert body["is_remake"] is False
        assert body["mandatory_reline_due_at"] is None, (
            "the type is not IMMEDIATE_DENTURE, so no mandatory reline is scheduled"
        )

        assert fx.read_arch(ctx["arch"]["id"])["arch_status"] == "DELIVERED"
        case = fx.read_case(ctx["case"]["id"])
        assert case["case_status"] == "DELIVERED"
        assert_same_instant(
            case["delivered_at"], "2026-05-01T00:00:00.000Z", "ProsthesisCase.delivered_at"
        )
        patient = fx.read_patient(ctx["patient"]["id"])
        assert patient["delivered_prosthesis_count"] == 1
        assert_same_instant(
            patient["last_frequency_anchor_at"],
            "2026-05-01T00:00:00.000Z",
            "Patient.last_frequency_anchor_at",
        )


class TestTheTwoClocks:
    def test_an_original_delivery_anchors_both_clocks_on_its_own_delivered_at(self, api):
        """PRD §3.6: "`warranty_expires_at` is always `delivered_at` plus 365 calendar
        days — **this** delivery's `delivered_at`, whether the appliance is an
        original or a remake. A remake therefore buys a full fresh year of warranty."
        PRD §3.6: "On an original delivery, where `superseded_prosthesis_id` is null,
        `frequency_anchor_at` equals this appliance's `delivered_at`."
        PRD §3.6: "`replacement_eligible_date` is `frequency_anchor_at` plus 60
        calendar months, keeping the day-of-month and clamping to the last day of a
        shorter target month."

        Design: Difficulty/dual_variant_calc/warranty_clock_restarts_while_replacement_clock_does_not
        """
        ctx = fx.setup_delivered_prosthesis(
            prosthesis_type="IMMEDIATE_DENTURE",
            patient_overrides={
                "full_name": "Cato Ilves", "date_of_birth": "1946-08-30", "phone": "555-0233"
            },
        )
        original = ctx["prosthesis"]

        assert original["is_remake"] is False
        assert_same_instant(
            original["delivered_at"], "2026-05-01T00:00:00.000Z", "Prosthesis.delivered_at"
        )
        assert_same_instant(
            original["warranty_expires_at"],
            "2027-05-01T00:00:00.000Z",
            "Prosthesis.warranty_expires_at",
        )
        assert_same_instant(
            original["frequency_anchor_at"],
            "2026-05-01T00:00:00.000Z",
            "Prosthesis.frequency_anchor_at",
        )
        assert_same_instant(
            original["replacement_eligible_date"],
            "2031-05-01T00:00:00.000Z",
            "Prosthesis.replacement_eligible_date",
        )

    def test_a_remake_restarts_the_warranty_but_never_the_replacement_clock(self, api):
        """PRD §3.6: "On a remake delivery, where `superseded_prosthesis_id` is set,
        `frequency_anchor_at` is copied verbatim from the superseded appliance's
        `frequency_anchor_at`. A remake therefore buys **no** new frequency
        eligibility at all."
        PRD §3.6: "On a remake delivery there is one further effect: the superseded
        appliance named by `superseded_prosthesis_id` has its `warranty_status` set to
        `WARRANTY_VOIDED` and its `recall_status` set to `RECALL_CLOSED_SUPERSEDED`,
        with its own `version` increment."
        PRD §3.6: "The consequence is worth stating plainly: an appliance remade three
        years after its original delivery is under warranty for a year from the remake,
        but its `replacement_eligible_date` still counts from the original delivery
        five years earlier, so the carrier's replacement window is untouched by the
        clinic's own rework."

        Design: Difficulty/dual_variant_calc/warranty_clock_restarts_while_replacement_clock_does_not
        """
        ctx = fx.setup_delivered_prosthesis(
            prosthesis_type="IMMEDIATE_DENTURE",
            patient_overrides={
                "full_name": "Cato Ilves", "date_of_birth": "1946-08-30", "phone": "555-0233"
            },
        )
        original = ctx["prosthesis"]
        arch_id = ctx["arch"]["id"]

        remake = fx.request_remake(arch_id, reason_code="FIT_FAILURE")
        fx.approve_remake(remake["id"])

        fx.set_clock("2026-09-01T00:00:00Z")
        fx.start_fabrication(arch_id)
        fx.accepted_impression(arch_id, "PHYSICAL_IMPRESSION", 91)
        fx.run_lab_round_trip(arch_id, ctx["lab"]["id"], "PASS", purpose="REMAKE")
        replacement = fx.deliver_prosthesis(arch_id, superseded_prosthesis_id=original["id"])

        assert replacement["is_remake"] is True
        assert_same_instant(
            replacement["delivered_at"], "2026-09-01T00:00:00.000Z", "remake delivered_at"
        )
        assert_same_instant(
            replacement["warranty_expires_at"],
            "2027-09-01T00:00:00.000Z",
            "remake warranty_expires_at",
        )
        assert_same_instant(
            replacement["frequency_anchor_at"],
            "2026-05-01T00:00:00.000Z",
            "remake frequency_anchor_at is copied from the superseded appliance",
        )
        assert_same_instant(
            replacement["replacement_eligible_date"],
            "2031-05-01T00:00:00.000Z",
            "remake replacement_eligible_date",
        )

        superseded = fx.read_prosthesis(original["id"])
        assert superseded["warranty_status"] == "WARRANTY_VOIDED"
        assert superseded["recall_status"] == "RECALL_CLOSED_SUPERSEDED"
        assert fx.read_arch(arch_id)["remake_count"] == 1
