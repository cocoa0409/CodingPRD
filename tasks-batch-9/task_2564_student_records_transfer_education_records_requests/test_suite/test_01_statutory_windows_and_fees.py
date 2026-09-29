"""Statutory response windows and copy-fee arithmetic.

Every window and every fee in this domain is derived by the server from
statutory reference data plus the logical clock, so these tests pin the exact
branch, the exact day budget, and the exact rounding order.
"""
from test_helpers import (
    api_client,
    assert_fee_custody_identity,
    assert_inspection_request,
    assert_records_request,
    create_district,
    create_inspection_request,
    create_state_rule,
    create_student,
    collect_component,
    get_components,
    get_cumulative_file_id,
    make_parent_headers,
    make_receiving_registrar_headers,
    records_request_payload,
    set_clock,
    validate_success,
)

MONDAY_ANCHOR = "2026-08-03T00:00:00Z"
MONDAY_ANCHOR_MS = "2026-08-03T00:00:00.000Z"


def _sending_district_with_two_receivers():
    """CA responds with a ten-day window; TX and NY each hold a receiving
    district so two requests may co-exist on one student."""
    create_state_rule("CA")
    create_state_rule("TX")
    create_state_rule(
        "NY",
        transfer_response_days=45,
        destruction_min_age_years=6,
        directory_optout_grace_days=30,
        notification_wait_days=10,
    )
    sending = create_district("SEND01", "CA", name="Sending Unified")
    receiving_tx = create_district("RECV01", "TX", name="Receiving Unified")
    receiving_ny = create_district("RECV02", "NY", name="Harbor Central")
    student = create_student(
        sending["id"],
        first_name="Cleo",
        last_name="Barros",
        dob="2010-11-02",
        grade_level=10,
        has_iep=True,
        guardian_user_id="guardian-cleo",
    )
    return sending, receiving_tx, receiving_ny, student


def _file_request(student_id, requesting_district_id, responding_district_id, **overrides):
    return api_client.create_records_request(
        records_request_payload(
            student_id, requesting_district_id, responding_district_id, **overrides
        ),
        make_receiving_registrar_headers(requesting_district_id),
    )


class TestStatutoryResponseWindow:
    def test_unaccompanied_youth_budget_caps_at_five_days(self):
        """An UNACCOMPANIED_YOUTH request against a ten-day state that also
        demands the special-education component is capped at five business days
        rather than extended to twenty.

        PRD: "For an `UNACCOMPANIED_YOUTH` request the budget is the smaller of the responding state's `transfer_response_days` and five days, and the special-education extension is suppressed entirely — an unaccompanied-youth request against a ten-day state that demands the special-education component gets five days, not twenty."

        Design: Difficulty/combinatorial_formula/records_request_due_at_expedited_cap_vs_sped_extension
        """
        sending, receiving_tx, _, student = _sending_district_with_two_receivers()
        set_clock(MONDAY_ANCHOR)

        response = _file_request(
            student["id"],
            receiving_tx["id"],
            sending["id"],
            request_priority="UNACCOMPANIED_YOUTH",
            includes_special_education=True,
            sped_consent_on_file=True,
            authorization_reference="ENR-2026-0002",
        )
        data = validate_success(response, 201)

        assert_records_request(data)
        assert data["received_at"] == MONDAY_ANCHOR_MS
        assert data["statutory_days_allowed"] == 5
        assert data["statutory_due_at"] == "2026-08-10T23:59:59.999Z"
        assert data["is_overdue"] is False
        assert data["status"] == "RECEIVED"

    def test_standard_request_takes_the_ten_day_special_education_extension(self):
        """A STANDARD request on the same student, in the same second, against
        the same ten-day responding state gets twenty days because both the
        request's special-education flag and the state's consent flag are true.

        PRD: "For a `STANDARD` request the budget starts at the responding state's `transfer_response_days` and is extended by a further ten days when both `includes_special_education` on the request and `sped_requires_consent` on the responding state's rule are true."

        Design: Difficulty/combinatorial_formula/records_request_due_at_expedited_cap_vs_sped_extension
        """
        sending, _, receiving_ny, student = _sending_district_with_two_receivers()
        set_clock(MONDAY_ANCHOR)

        response = _file_request(
            student["id"],
            receiving_ny["id"],
            sending["id"],
            request_priority="STANDARD",
            includes_special_education=True,
            sped_consent_on_file=True,
            authorization_reference="ENR-2026-0003",
        )
        data = validate_success(response, 201)

        assert data["received_at"] == MONDAY_ANCHOR_MS
        assert data["statutory_days_allowed"] == 20
        assert data["statutory_due_at"] == "2026-08-31T23:59:59.999Z"

    def test_the_two_branches_diverge_on_one_student_at_one_instant(self):
        """The cap and the extension are read off the same responding state
        rule at the same received_at instant, so the only thing that separates
        five days from twenty is the priority branch; the business-day walk
        skips only Saturday and Sunday.

        PRD: "**Business-day offsets** advance a cursor one calendar day at a time from an anchor instant, counting only days that fall on Monday, Tuesday, Wednesday, Thursday, or Friday, until the required number of business days has been counted; the anchor's own calendar day is never counted even when it is itself a business day, and no holiday calendar exists, so Saturday and Sunday are the only skipped weekdays."

        Design: Difficulty/combinatorial_formula/records_request_due_at_expedited_cap_vs_sped_extension
        """
        sending, receiving_tx, receiving_ny, student = _sending_district_with_two_receivers()
        set_clock(MONDAY_ANCHOR)

        expedited = validate_success(
            _file_request(
                student["id"],
                receiving_tx["id"],
                sending["id"],
                request_priority="UNACCOMPANIED_YOUTH",
                includes_special_education=True,
                sped_consent_on_file=True,
                authorization_reference="ENR-2026-0002",
            ),
            201,
        )
        standard = validate_success(
            _file_request(
                student["id"],
                receiving_ny["id"],
                sending["id"],
                request_priority="STANDARD",
                includes_special_education=True,
                sped_consent_on_file=True,
                authorization_reference="ENR-2026-0003",
            ),
            201,
        )

        assert expedited["received_at"] == standard["received_at"] == MONDAY_ANCHOR_MS
        assert expedited["statutory_days_allowed"] == 5
        assert standard["statutory_days_allowed"] == 20
        assert expedited["statutory_due_at"] == "2026-08-10T23:59:59.999Z"
        assert standard["statutory_due_at"] == "2026-08-31T23:59:59.999Z"


def _priced_file(pages, has_iep, first_name, last_name, dob, guardian_user_id):
    """Collect the given component page figures on one student's file and hand
    back the student plus the guardian's headers."""
    create_state_rule("CA")
    sending = create_district("SEND01", "CA", name="Sending Unified")
    student = create_student(
        sending["id"],
        first_name=first_name,
        last_name=last_name,
        dob=dob,
        grade_level=8,
        has_iep=has_iep,
        guardian_user_id=guardian_user_id,
    )
    file_id = get_cumulative_file_id(student["id"])
    components = get_components(file_id)
    for ctype, (page_count, redacted) in pages.items():
        collect_component(file_id, components[ctype]["id"], page_count, redacted)
    return student, make_parent_headers(guardian_user_id)


class TestCopyFeeRounding:
    def test_copy_fee_rounds_twice_per_component_before_summing(self):
        """Four components at 120, 30, 16 and 250 chargeable pages price to
        974 + 244 + 130 + 2030 = 3378 cents; summing the raw page charges first
        and rounding once at the end would give 3377.

        PRD: "For each qualifying component, take its `page_count` minus its `redacted_page_count` as the chargeable page figure, multiply that by seven and a half cents per page, and round half up to a whole number of cents; then apply the 8.25 percent copy surcharge by multiplying that whole-cent figure by one plus the surcharge rate and rounding half up again to whole cents."

        Design: Difficulty/combinatorial_formula/inspection_copy_fee_round_per_component
        """
        student, parent_headers = _priced_file(
            {
                "ACADEMIC": (120, 0),
                "HEALTH": (34, 4),
                "DISCIPLINE": (18, 2),
                "SPECIAL_EDUCATION": (260, 10),
            },
            has_iep=True,
            first_name="Dev",
            last_name="Iyer",
            dob="2013-01-09",
            guardian_user_id="guardian-dev",
        )

        response = api_client.create_inspection_request(
            student["id"],
            {
                "requested_categories": [
                    "ACADEMIC",
                    "HEALTH",
                    "DISCIPLINE",
                    "SPECIAL_EDUCATION",
                ],
                "copies_requested": True,
            },
            parent_headers,
        )
        data = validate_success(response, 201)

        assert_inspection_request(data)
        assert data["base_copy_fee_cents"] == 3378
        assert data["base_copy_fee_cents"] != 3377
        assert data["certification_fee_cents"] == 500
        assert data["fee_assessed_cents"] == 3878

    def test_freshly_priced_request_owes_the_whole_assessment(self):
        """The three-way fee split starts entirely in the outstanding bucket, so
        the fee-custody identity holds from the first instant of the request.

        PRD: "The request is created with `fee_collected_cents` and `fee_waived_cents` at 0 and `fee_outstanding_cents` equal to `fee_assessed_cents`."

        Design: Difficulty/combinatorial_formula/inspection_copy_fee_round_per_component
        """
        student, parent_headers = _priced_file(
            {
                "ACADEMIC": (120, 0),
                "HEALTH": (34, 4),
                "DISCIPLINE": (18, 2),
                "SPECIAL_EDUCATION": (260, 10),
            },
            has_iep=True,
            first_name="Dev",
            last_name="Iyer",
            dob="2013-01-09",
            guardian_user_id="guardian-dev",
        )

        data = create_inspection_request(
            student["id"],
            parent_headers,
            categories=["ACADEMIC", "HEALTH", "DISCIPLINE", "SPECIAL_EDUCATION"],
            copies_requested=True,
        )

        assert data["fee_collected_cents"] == 0
        assert data["fee_waived_cents"] == 0
        assert data["fee_outstanding_cents"] == 3878
        assert data["status"] == "SUBMITTED"
        assert_fee_custody_identity(data)


class TestCertificationFeeTier:
    def test_certification_tier_is_keyed_on_the_copy_fee_alone(self):
        """A 9800-cent copy fee sits below the 10000-cent floor, so
        certification is 500 cents and the 10300-cent total is never re-tiered
        up to 1500.

        PRD: "`fee_assessed_cents` is then `base_copy_fee_cents` plus `certification_fee_cents`, and the tier is never re-evaluated against that total — even when adding the certification fee pushes the total across a tier boundary, the tier stays the one the copy fee alone selected."

        Design: Difficulty/combinatorial_formula/inspection_fee_tier_keyed_on_base_only
        """
        student, parent_headers = _priced_file(
            {"ACADEMIC": (1207, 0)},
            has_iep=False,
            first_name="Elif",
            last_name="Kaya",
            dob="2012-06-18",
            guardian_user_id="guardian-elif",
        )

        data = create_inspection_request(
            student["id"], parent_headers, categories=["ACADEMIC"], copies_requested=True
        )

        assert data["base_copy_fee_cents"] == 9800
        assert data["certification_fee_cents"] == 500
        assert data["fee_assessed_cents"] == 10300
        assert data["fee_assessed_cents"] != 11300

    def test_middle_tier_floor_is_inclusive_and_the_balance_matches(self):
        """9800 cents is at least 2000 and below 10000, which is exactly the
        middle certification tier, and the whole 10300-cent assessment is
        outstanding.

        PRD: "When it is at least 2000 cents but below 10000 cents, `certification_fee_cents` is 500 cents."

        Design: Difficulty/combinatorial_formula/inspection_fee_tier_keyed_on_base_only
        """
        student, parent_headers = _priced_file(
            {"ACADEMIC": (1207, 0)},
            has_iep=False,
            first_name="Elif",
            last_name="Kaya",
            dob="2012-06-18",
            guardian_user_id="guardian-elif",
        )

        data = create_inspection_request(
            student["id"], parent_headers, categories=["ACADEMIC"], copies_requested=True
        )

        assert 2000 <= data["base_copy_fee_cents"] < 10000
        assert data["certification_fee_cents"] == 500
        assert data["fee_outstanding_cents"] == 10300
        assert_fee_custody_identity(data)
