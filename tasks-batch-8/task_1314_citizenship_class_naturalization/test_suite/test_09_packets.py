"""Application packets: legal review, certification, filing fee, filing (PRD §3.8)."""
from test_helpers import (
    FILING_FEE_NO_WAIVER_CENTS,
    FILING_FEE_PARTIAL_CENTS,
    ApiErrorId,
    TEST_USERS,
    assert_case,
    assert_packet,
    assert_version_incremented,
    certify_packet,
    complete_workshop,
    create_approved_fee_waiver,
    create_fee_waiver,
    create_general_volunteer,
    create_legal_volunteer,
    create_packet,
    create_packet_in_review,
    create_program,
    create_screened_applicant,
    create_workshop,
    decide_fee_waiver,
    get_fee_waiver,
    get_packet,
    get_workshop_seat,
    make_volunteer_headers,
    reserve_seat,
    set_clock,
    setup_certified_pipeline,
    setup_filed_case,
    setup_packet_pipeline,
    submit_fee_waiver,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["program_admin_headers"]
COORD = TEST_USERS["intake_coordinator_headers"]


class TestFilingFeeComputation:
    def test_filing_fee_partial_per_line_rounding_order(self, api):
        """PRD §3.8: "A `PARTIAL` tier halves each line individually, rounding half up
        to a whole cent per line, and then sums the discounted lines: under the
        defaults, 38000 plus 4251 plus 1501 equals 43752 cents. The order matters and
        is not negotiable — summing first and halving once would yield 43751, which is
        a different number and is not the specification."

        Design: Difficulty/combinatorial_formula/filing_fee_partial_per_line_rounding_order
        """
        pipeline = setup_packet_pipeline()
        applicant = pipeline["applicant"]
        # Income 2,800,000 cents household 1: above the 150% cap (2,347,500) but
        # within the 200% cap (3,130,000), so both variants compute PARTIAL.
        waiver = create_approved_fee_waiver(applicant["id"], household_size=1,
                                            income=2800000)
        assert waiver["final_tier"] == "PARTIAL"

        packet = create_packet_in_review(pipeline, fee_waiver_request_id=waiver["id"])
        certified = certify_packet(packet["id"], pipeline["certifier"]["id"])
        assert_packet(certified)
        assert certified["status"] == "CERTIFIED"
        assert certified["filing_fee_cents"] == FILING_FEE_PARTIAL_CENTS, (
            "per-line half-up (38000 + 4251 + 1501 = 43752), not the 43751 that "
            "sum-first rounding would yield"
        )
        assert certified["certified_by_volunteer_id"] == pipeline["certifier"]["id"]

    def test_filing_fee_denied_waiver_prices_as_no_waiver(self, api):
        """PRD §3.8: "First resolve the effective tier: the `final_tier` of the linked
        `APPROVED` fee waiver request, or no tier at all when no request is linked or
        the linked request was `DENIED` — a denial counts as no waiver for pricing."
        PRD §3.8: "No tier prices it at the raw sum of the three lines — 87502 cents
        under the defaults."

        Design: Difficulty/combinatorial_formula/filing_fee_partial_per_line_rounding_order
        """
        pipeline = setup_packet_pipeline()
        applicant = pipeline["applicant"]
        waiver = create_fee_waiver(applicant["id"], household_size=1,
                                   self_reported_income_cents=1000000)
        submit_fee_waiver(waiver["id"], waiver["required_document_count"])
        denied = decide_fee_waiver(waiver["id"], "DENIED", 1000000, False)
        assert denied["status"] == "DENIED"
        assert denied["final_tier"] is None

        packet = create_packet_in_review(pipeline, fee_waiver_request_id=waiver["id"])
        certified = certify_packet(packet["id"], pipeline["certifier"]["id"])
        assert certified["status"] == "CERTIFIED"
        assert certified["filing_fee_cents"] == FILING_FEE_NO_WAIVER_CENTS, (
            "a DENIED linked waiver counts as no tier: raw sum 76000+8501+3001"
        )

    def test_filing_fee_full_and_none_variants(self, api):
        """PRD §3.8: "A `FULL` tier prices the packet at exactly 0 cents regardless of
        the schedule. No tier prices it at the raw sum of the three lines — 87502
        cents under the defaults."

        Design: Corner/calculations/filing_fee_full_and_none_variants
        """
        create_program()
        applicant_full, _ = create_screened_applicant()
        applicant_none, _ = create_screened_applicant()
        preparer = create_general_volunteer(full_name="Prep Vol")
        supervisor = create_legal_volunteer(full_name="Sup Vol", bar_number="BAR111")
        certifier = create_legal_volunteer(full_name="Cert Vol", bar_number="BAR222")
        workshop = create_workshop(supervisor["id"], capacity=5)
        seat_full = reserve_seat(workshop["id"], applicant_full["id"])
        seat_none = reserve_seat(workshop["id"], applicant_none["id"])
        complete_workshop(workshop["id"], supervisor["id"], at="2026-08-05T10:00:00Z")

        waiver = create_approved_fee_waiver(applicant_full["id"], household_size=1,
                                            income=1000000)
        assert waiver["final_tier"] == "FULL"

        packet_full = create_packet(applicant_full["id"], seat_full["id"],
                                    preparer["id"], fee_waiver_request_id=waiver["id"])
        validate_success(api.submit_packet_review(packet_full["id"], COORD), 200)
        certified_full = certify_packet(packet_full["id"], certifier["id"])
        assert certified_full["filing_fee_cents"] == 0, (
            "FULL waiver prices the packet at exactly 0 cents"
        )

        packet_none = create_packet(applicant_none["id"], seat_none["id"],
                                    preparer["id"])
        validate_success(api.submit_packet_review(packet_none["id"], COORD), 200)
        certified_none = certify_packet(packet_none["id"], certifier["id"])
        assert certified_none["filing_fee_cents"] == FILING_FEE_NO_WAIVER_CENTS


class TestPacketRevisionCycle:
    def test_packet_revision_cycle(self, api):
        """PRD §3.8: "Legal review runs as a cycle. Submission for review by an
        `IntakeCoordinator` moves `DRAFT` → `IN_LEGAL_REVIEW`. A volunteer holding
        `LEGAL` accreditation that has not lapsed may then send the packet back with
        `revision_notes`, moving `IN_LEGAL_REVIEW` → `NEEDS_REVISION`
        (`ERR_INVALID_STATE` when the packet is not under review; accreditation
        failures surface as in §3.5). An `IntakeCoordinator` works the revision and
        returns `NEEDS_REVISION` → `DRAFT`, and the cycle may iterate as many times as
        the work demands."
        PRD §2.4: "`version` — an integer that increments by one on every mutation,
        including mutations the server applies automatically as cascading side effects
        of an operation on a related resource."

        Design: Difficulty/non_linear_state_machine/packet_revision_cycle
        """
        pipeline = setup_packet_pipeline()
        packet = create_packet(
            pipeline["applicant"]["id"], pipeline["seat"]["id"],
            pipeline["preparer"]["id"],
        )
        assert packet["status"] == "DRAFT"
        last_version = packet["version"]

        # Traverse DRAFT -> IN_LEGAL_REVIEW -> NEEDS_REVISION -> DRAFT ->
        # IN_LEGAL_REVIEW -> CERTIFIED, asserting the +1 version step at each hop.
        in_review = validate_success(
            api.submit_packet_review(packet["id"], COORD), 200
        )
        assert in_review["status"] == "IN_LEGAL_REVIEW"
        assert_version_incremented(in_review["version"], last_version)
        last_version = in_review["version"]

        needs_revision = validate_success(
            api.request_packet_revision(
                packet["id"], {"revision_notes": "fix travel dates"},
                make_volunteer_headers(pipeline["certifier"]["id"]),
            ),
            200,
        )
        assert needs_revision["status"] == "NEEDS_REVISION"
        assert_version_incremented(needs_revision["version"], last_version)
        last_version = needs_revision["version"]

        back_to_draft = validate_success(api.revise_packet(packet["id"], COORD), 200)
        assert back_to_draft["status"] == "DRAFT"
        assert_version_incremented(back_to_draft["version"], last_version)
        last_version = back_to_draft["version"]

        in_review_again = validate_success(
            api.submit_packet_review(packet["id"], COORD), 200
        )
        assert in_review_again["status"] == "IN_LEGAL_REVIEW"
        assert_version_incremented(in_review_again["version"], last_version)
        last_version = in_review_again["version"]

        certified = validate_success(
            api.certify_packet(
                packet["id"], make_volunteer_headers(pipeline["certifier"]["id"])
            ),
            200,
        )
        assert certified["status"] == "CERTIFIED"
        assert_version_incremented(certified["version"], last_version)

    def test_packet_revision_cycle_state_guards(self, api):
        """PRD §3.8: "A volunteer holding `LEGAL` accreditation that has not lapsed
        may then send the packet back with `revision_notes`, moving `IN_LEGAL_REVIEW`
        → `NEEDS_REVISION` (`ERR_INVALID_STATE` when the packet is not under review;
        accreditation failures surface as in §3.5). An `IntakeCoordinator` works the
        revision and returns `NEEDS_REVISION` → `DRAFT`, and the cycle may iterate as
        many times as the work demands."

        Design: Difficulty/non_linear_state_machine/packet_revision_cycle
        """
        pipeline = setup_packet_pipeline()
        packet = create_packet(
            pipeline["applicant"]["id"], pipeline["seat"]["id"],
            pipeline["preparer"]["id"],
        )
        assert packet["status"] == "DRAFT"

        # The packet is not under review, so request-revision must fail.
        response = api.request_packet_revision(
            packet["id"], {"revision_notes": "premature"},
            make_volunteer_headers(pipeline["certifier"]["id"]),
        )
        validate_error(response, ApiErrorId.ERR_INVALID_STATE)

        # Revise is only defined from NEEDS_REVISION, so it must fail from DRAFT.
        response = api.revise_packet(packet["id"], COORD)
        validate_error(response, ApiErrorId.ERR_INVALID_STATE)
        assert get_packet(packet["id"])["status"] == "DRAFT"


class TestPacketCreationGate:
    def test_packet_creation_gated_by_workshop_seat_state(self, api):
        """PRD §3.8: "The referenced seat must be `ATTENDED`
        (`ERR_WORKSHOP_NOT_ATTENDED` otherwise) and must belong to this applicant
        (`ERR_REFERENTIAL_MISMATCH` when it belongs to someone else)"

        Design: Difficulty/cross_entity_state_dependency/packet_creation_gated_by_workshop_seat_state
        """
        create_program()
        applicant, _ = create_screened_applicant()
        preparer = create_general_volunteer(full_name="Prep Vol")
        supervisor = create_legal_volunteer(full_name="Sup Vol", bar_number="BAR111")
        workshop = create_workshop(supervisor["id"],
                                   scheduled_start="2026-08-05T10:00:00Z")
        # The workshop is still SCHEDULED, so the seat is RESERVED, not ATTENDED.
        seat = reserve_seat(workshop["id"], applicant["id"])
        assert seat["status"] == "RESERVED"

        response = api.create_packet(
            applicant["id"],
            {"workshop_seat_id": seat["id"],
             "prepared_by_volunteer_id": preparer["id"]},
            COORD,
        )
        validate_error(response, ApiErrorId.ERR_WORKSHOP_NOT_ATTENDED)

        rows, meta = validate_paginated(
            api.list_packets(COORD, params={"applicant_id": applicant["id"]})
        )
        assert meta["total_count"] == 0, "no packet row may be created"

    def test_packet_creation_rejected_for_reversed_and_cancelled_seats(self, api):
        """PRD §3.8: "The referenced seat must be `ATTENDED`
        (`ERR_WORKSHOP_NOT_ATTENDED` otherwise) and must belong to this applicant
        (`ERR_REFERENTIAL_MISMATCH` when it belongs to someone else)"

        Design: Difficulty/cross_entity_state_dependency/packet_creation_gated_by_workshop_seat_state
        """
        create_program()
        applicant, _ = create_screened_applicant()
        preparer = create_general_volunteer(full_name="Prep Vol")
        supervisor = create_legal_volunteer(full_name="Sup Vol", bar_number="BAR111")

        # Seat that reached ATTENDED then returned to REVERSED via reversal.
        workshop_reversed = create_workshop(supervisor["id"],
                                            scheduled_start="2026-08-05T10:00:00Z")
        seat_reversed = reserve_seat(workshop_reversed["id"], applicant["id"])
        complete_workshop(workshop_reversed["id"], supervisor["id"],
                          at="2026-08-05T10:00:00Z")
        validate_success(
            api.reverse_workshop_completion(workshop_reversed["id"], ADMIN), 200
        )
        assert get_workshop_seat(seat_reversed["id"])["status"] == "REVERSED"

        response = api.create_packet(
            applicant["id"],
            {"workshop_seat_id": seat_reversed["id"],
             "prepared_by_volunteer_id": preparer["id"]},
            COORD,
        )
        validate_error(response, ApiErrorId.ERR_WORKSHOP_NOT_ATTENDED)

        # Seat cancelled directly while the workshop is still SCHEDULED.
        workshop_open = create_workshop(supervisor["id"],
                                        scheduled_start="2026-08-20T10:00:00Z",
                                        title="Open WS")
        seat_cancelled = reserve_seat(workshop_open["id"], applicant["id"])
        validate_success(api.cancel_workshop_seat(seat_cancelled["id"], COORD), 200)
        assert get_workshop_seat(seat_cancelled["id"])["status"] == "CANCELLED"

        response = api.create_packet(
            applicant["id"],
            {"workshop_seat_id": seat_cancelled["id"],
             "prepared_by_volunteer_id": preparer["id"]},
            COORD,
        )
        validate_error(response, ApiErrorId.ERR_WORKSHOP_NOT_ATTENDED)


class TestCertifyGates:
    def test_certify_state_error_beats_fee_pending_fiscal(self, api):
        """PRD §2.9: "Validations on a request execute in a fixed priority order, and
        an earlier failure masks every later check."
        PRD §2.9: "6. **State permission.** The target resource's state must permit
        the requested transition, else `ERR_INVALID_STATE` (HTTP 409)."
        PRD §2.9: "16. **Money and capacity decisions, deliberately last among
        business rules.** A pending fee waiver blocks certification
        (`ERR_FEE_WAIVER_PENDING`); an approval whose verified tier computes to denial
        rejects as `ERR_TIER_INELIGIBLE`; a full ceremony rejects as
        `ERR_CEREMONY_FULL`; a full workshop rejects as `ERR_WORKSHOP_FULL` — all HTTP
        409."

        Design: Difficulty/priority_pair_validation_conflict/certify_state_error_beats_fee_pending_fiscal
        """
        pipeline = setup_packet_pipeline()
        applicant = pipeline["applicant"]
        # Linked waiver is SUBMITTED (non-terminal) AND the packet is still DRAFT:
        # both the state guard and the fiscal guard could fire; state must win.
        waiver = create_fee_waiver(applicant["id"], household_size=1,
                                   self_reported_income_cents=2800000)
        submit_fee_waiver(waiver["id"], waiver["required_document_count"])
        packet = create_packet(
            applicant["id"], pipeline["seat"]["id"], pipeline["preparer"]["id"],
            fee_waiver_request_id=waiver["id"],
        )
        assert packet["status"] == "DRAFT"

        response = api.certify_packet(
            packet["id"], make_volunteer_headers(pipeline["supervisor"]["id"])
        )
        validate_error(response, ApiErrorId.ERR_INVALID_STATE)
        after = get_packet(packet["id"])
        assert after["status"] == "DRAFT"
        assert after["filing_fee_cents"] is None
        assert after["certified_by_volunteer_id"] is None

    def test_certify_state_error_beats_fee_pending_from_needs_revision(self, api):
        """PRD §3.8: "Certification is the pivotal gate, performed by a volunteer
        holding `LEGAL` accreditation that has not lapsed, and only from
        `IN_LEGAL_REVIEW` (`ERR_INVALID_STATE` otherwise)."
        PRD §2.9: "Validations on a request execute in a fixed priority order, and an
        earlier failure masks every later check."

        Design: Difficulty/priority_pair_validation_conflict/certify_state_error_beats_fee_pending_fiscal
        """
        pipeline = setup_packet_pipeline()
        applicant = pipeline["applicant"]
        waiver = create_fee_waiver(applicant["id"], household_size=1,
                                   self_reported_income_cents=2800000)
        submit_fee_waiver(waiver["id"], waiver["required_document_count"])
        packet = create_packet_in_review(pipeline, fee_waiver_request_id=waiver["id"])
        validate_success(
            api.request_packet_revision(
                packet["id"], {"revision_notes": "redo"},
                make_volunteer_headers(pipeline["certifier"]["id"]),
            ),
            200,
        )
        assert get_packet(packet["id"])["status"] == "NEEDS_REVISION"

        # NEEDS_REVISION is not IN_LEGAL_REVIEW: the state guard fires and the
        # pending-waiver fiscal check behind it is never reached.
        response = api.certify_packet(
            packet["id"], make_volunteer_headers(pipeline["certifier"]["id"])
        )
        validate_error(response, ApiErrorId.ERR_INVALID_STATE)
        assert get_packet(packet["id"])["status"] == "NEEDS_REVISION"

    def test_certify_readiness_below_threshold_rejected(self, api):
        """PRD §3.8: "The applicant's attained readiness score must be at least
        `readiness_certify_threshold` (`ERR_READINESS_BELOW_THRESHOLD`), and the
        applicant's `ACTIVE` screening must still be unexpired
        (`ERR_SCREENING_EXPIRED`)."

        Design: Corner/validations/certify_readiness_below_threshold_rejected
        """
        # english_level 1 / civics 0: attained = 25 + 25 + 5 + 0 + 10 = 65 < 70.
        pipeline = setup_packet_pipeline(
            screening_overrides={"english_level": 1, "civics_practice_pct": 0}
        )
        readiness = validate_success(
            api.get_readiness(pipeline["applicant"]["id"], COORD), 200
        )
        assert readiness["score"] == 65

        packet = create_packet_in_review(pipeline)
        response = api.certify_packet(
            packet["id"], make_volunteer_headers(pipeline["certifier"]["id"])
        )
        validate_error(response, ApiErrorId.ERR_READINESS_BELOW_THRESHOLD)
        assert get_packet(packet["id"])["status"] == "IN_LEGAL_REVIEW"

    def test_sod_certifier_is_preparer_rejected(self, api):
        """PRD §3.8: "Segregation of duties is enforced: the certifying volunteer's
        `X-User-ID` must differ from the packet's `prepared_by_volunteer_id`,
        rejecting with `ERR_SOD_CERTIFIER_IS_PREPARER` when the preparer attempts to
        certify their own work."

        Design: Corner/validations/sod_certifier_is_preparer_rejected
        """
        create_program()
        applicant, _ = create_screened_applicant()
        supervisor = create_legal_volunteer(full_name="Sup Vol", bar_number="BAR111")
        workshop = create_workshop(supervisor["id"],
                                   scheduled_start="2026-08-05T10:00:00Z")
        seat = reserve_seat(workshop["id"], applicant["id"])
        complete_workshop(workshop["id"], supervisor["id"], at="2026-08-05T10:00:00Z")
        # The LEGAL supervisor is also recorded as the preparing volunteer.
        packet = create_packet(applicant["id"], seat["id"], supervisor["id"])
        validate_success(api.submit_packet_review(packet["id"], COORD), 200)

        response = api.certify_packet(
            packet["id"], make_volunteer_headers(supervisor["id"])
        )
        validate_error(response, ApiErrorId.ERR_SOD_CERTIFIER_IS_PREPARER)
        after = get_packet(packet["id"])
        assert after["status"] == "IN_LEGAL_REVIEW"
        assert after["certified_by_volunteer_id"] is None

    def test_certify_with_pending_fee_waiver_rejected(self, api):
        """PRD §3.8: "When a fee waiver request is linked, it must be in a terminal
        state — `APPROVED` or `DENIED` — since the fee cannot be priced against a
        request still in `DRAFT` or `SUBMITTED` (`ERR_FEE_WAIVER_PENDING`)."

        Design: Corner/validations/certify_with_pending_fee_waiver_rejected
        """
        pipeline = setup_packet_pipeline()
        applicant = pipeline["applicant"]
        waiver = create_fee_waiver(applicant["id"], household_size=1,
                                   self_reported_income_cents=1000000)
        submit_fee_waiver(waiver["id"], waiver["required_document_count"])
        assert get_fee_waiver(waiver["id"])["status"] == "SUBMITTED"
        packet = create_packet_in_review(pipeline, fee_waiver_request_id=waiver["id"])

        response = api.certify_packet(
            packet["id"], make_volunteer_headers(pipeline["certifier"]["id"])
        )
        validate_error(response, ApiErrorId.ERR_FEE_WAIVER_PENDING)
        assert get_packet(packet["id"])["status"] == "IN_LEGAL_REVIEW"

    def test_packet_create_with_other_applicants_seat_rejected(self, api):
        """PRD §3.8: "The referenced seat must be `ATTENDED`
        (`ERR_WORKSHOP_NOT_ATTENDED` otherwise) and must belong to this applicant
        (`ERR_REFERENTIAL_MISMATCH` when it belongs to someone else)"

        Design: Corner/validations/packet_create_with_other_applicants_seat_rejected
        """
        pipeline = setup_packet_pipeline()
        owner = pipeline["applicant"]
        other, _ = create_screened_applicant()
        assert pipeline["seat"]["status"] == "ATTENDED"
        assert pipeline["seat"]["applicant_id"] == owner["id"]

        response = api.create_packet(
            other["id"],
            {"workshop_seat_id": pipeline["seat"]["id"],
             "prepared_by_volunteer_id": pipeline["preparer"]["id"]},
            COORD,
        )
        validate_error(response, ApiErrorId.ERR_REFERENTIAL_MISMATCH)
        rows, meta = validate_paginated(
            api.list_packets(COORD, params={"applicant_id": other["id"]})
        )
        assert meta["total_count"] == 0


class TestPacketUniquenessAndFiling:
    def test_packet_second_active_rejected(self, api):
        """PRD §3.8: "One active packet per applicant: an existing packet in `DRAFT`,
        `IN_LEGAL_REVIEW`, `NEEDS_REVISION`, or `CERTIFIED` blocks creation with
        `ERR_PACKET_ALREADY_ACTIVE`."

        Design: Corner/endpoints/packet_second_active_rejected
        """
        create_program()
        applicant, _ = create_screened_applicant()
        supervisor = create_legal_volunteer(full_name="Sup Vol", bar_number="BAR111")
        workshop_1 = create_workshop(supervisor["id"],
                                     scheduled_start="2026-08-05T10:00:00Z",
                                     duration_hours=2, title="WS1")
        seat_1 = reserve_seat(workshop_1["id"], applicant["id"])
        workshop_2 = create_workshop(supervisor["id"],
                                     scheduled_start="2026-08-06T10:00:00Z",
                                     duration_hours=2, title="WS2")
        seat_2 = reserve_seat(workshop_2["id"], applicant["id"])
        set_clock("2026-08-06T11:00:00Z")
        complete_workshop(workshop_1["id"], supervisor["id"])
        complete_workshop(workshop_2["id"], supervisor["id"])

        first = create_packet(applicant["id"], seat_1["id"], supervisor["id"])
        assert first["status"] == "DRAFT"

        # A second ATTENDED seat does not help: the DRAFT packet blocks creation.
        response = api.create_packet(
            applicant["id"],
            {"workshop_seat_id": seat_2["id"],
             "prepared_by_volunteer_id": supervisor["id"]},
            COORD,
        )
        validate_error(response, ApiErrorId.ERR_PACKET_ALREADY_ACTIVE)

    def test_file_packet_creates_case_with_receipt(self, api):
        """PRD §3.8: "Filing, performed by an `IntakeCoordinator`, moves `CERTIFIED` →
        `FILED` (terminal) and creates the applicant's **USCISCase**: stage `FILED`,
        `rfe_status` `NONE`, `packet_id` referencing this packet, and a
        system-generated `receipt_number` of the form NRC- followed by a zero-padded
        sequence."
        PRD §3.8: "The filing operation returns the newly created case and, as a
        cascade, advances the applicant's stage from `IN_PIPELINE` to `FILED`."

        Design: Corner/endpoints/file_packet_creates_case_with_receipt
        """
        pipeline = setup_certified_pipeline()
        packet = pipeline["packet"]
        assert packet["status"] == "CERTIFIED"

        case = validate_success(api.file_packet(packet["id"], COORD), 201)
        assert_case(case)
        assert case["stage"] == "FILED"
        assert case["rfe_status"] == "NONE"
        assert case["packet_id"] == packet["id"]
        assert case["receipt_number"].startswith("NRC-"), (
            "receipt_number is NRC- followed by a zero-padded sequence"
        )
        assert case["applicant_id"] == pipeline["applicant"]["id"]

        assert get_packet(packet["id"])["status"] == "FILED"
        applicant_after = api.get_applicant(pipeline["applicant"]["id"], COORD).json()["data"]
        assert applicant_after["stage"] == "FILED"
