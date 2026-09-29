"""Conserved ledgers checked across an action and its compensating action.

Pages change custody without being created or destroyed, and cents move between
collected, waived and outstanding without ever altering the assessment.
"""
from test_helpers import (
    CLERK,
    OFFICER_1,
    api_client,
    assert_cumulative_file,
    assert_fee_custody_identity,
    assert_file_component,
    assert_inspection_request,
    assert_page_custody_identity,
    certify_component,
    collect_component,
    create_district,
    create_inspection_request,
    create_state_rule,
    create_student,
    exclude_component,
    fee_transaction_payload,
    get_components,
    get_cumulative_file_id,
    get_file,
    get_inspection_request,
    make_parent_headers,
    pay_fee,
    reinstate_component,
    validate_error,
)

CA_RULE = dict(
    transfer_response_days=10,
    discipline_inclusion_mode="SUSPENSIONS_AND_EXPULSIONS",
    discipline_min_days_removed=10,
    include_pending_investigations=False,
    sped_requires_consent=True,
    amendment_hearing_days=30,
    destruction_min_age_years=5,
    directory_optout_grace_days=14,
    notification_wait_days=7,
)


def _file_with_the_discipline_component_excluded():
    """172 pages sit in three certified components; the 18-page DISCIPLINE
    component is then excluded, moving those pages into the excluded bucket."""
    create_state_rule("CA", **CA_RULE)
    district = create_district("SEND01", state_code="CA", name="Sending Unified")
    student = create_student(
        district["id"],
        first_name="Vera",
        last_name="Nakashima",
        dob="2012-01-20",
        grade_level=8,
        has_iep=False,
        guardian_user_id="guardian-vera",
    )
    file_id = get_cumulative_file_id(student["id"])
    components = get_components(file_id)
    for component_type, pages, redactions in (
        ("ACADEMIC", 120, 0),
        ("HEALTH", 34, 4),
        ("DISCIPLINE", 18, 2),
    ):
        component_id = components[component_type]["id"]
        collect_component(file_id, component_id, pages, redactions)
        certify_component(file_id, component_id)

    intact = get_file(file_id)
    assert intact["total_page_count"] == 172
    assert intact["included_page_count"] == 172
    assert intact["excluded_page_count"] == 0
    assert intact["disclosable_page_count"] == 166

    discipline_id = components["DISCIPLINE"]["id"]
    exclude_component(file_id, discipline_id, "OTHER_STUDENT_INFO", headers=OFFICER_1)
    return file_id, discipline_id


class TestPageCustodyAcrossExclusionAndReinstatement:
    def test_exclusion_moves_pages_between_buckets_without_changing_the_total(self):
        """While the component is excluded the file still carries all 172 pages,
        with 18 of them sitting in the excluded bucket and the disclosable count
        down to 150.

        PRD: "The **page-custody identity** holds on every cumulative file after every component mutation: `total_page_count` always equals `included_page_count` plus `excluded_page_count`."

        Design: Difficulty/compensating_invariant/page_custody_preserved_by_exclusion_reinstatement
        """
        file_id, _discipline_id = _file_with_the_discipline_component_excluded()

        held_back = get_file(file_id)

        assert_cumulative_file(held_back)
        assert_page_custody_identity(held_back)
        assert held_back["total_page_count"] == 172
        assert held_back["included_page_count"] == 154
        assert held_back["excluded_page_count"] == 18
        assert held_back["disclosable_page_count"] == 150
        assert held_back["certified_component_count"] == 2
        assert held_back["completeness_pct"] == 66.7

    def test_reinstatement_restores_the_exact_pre_exclusion_split(self):
        """Reinstating the component returns the 18 pages to the included bucket
        and reproduces the 172 / 172 / 0 / 166 figures the file held before the
        exclusion, with the reason and the certification both cleared.

        PRD: "Reinstatement is the compensating action, and it is exact."

        Design: Difficulty/compensating_invariant/page_custody_preserved_by_exclusion_reinstatement
        """
        file_id, discipline_id = _file_with_the_discipline_component_excluded()

        reinstated = reinstate_component(file_id, discipline_id, headers=CLERK)

        assert_file_component(reinstated)
        assert reinstated["status"] == "COLLECTED"
        assert reinstated["page_count"] == 18
        assert reinstated["redacted_page_count"] == 2
        assert reinstated["exclusion_reason"] is None
        assert reinstated["certified_at"] is None

        restored = get_file(file_id)
        assert_page_custody_identity(restored)
        assert restored["total_page_count"] == 172
        assert restored["included_page_count"] == 172
        assert restored["excluded_page_count"] == 0
        assert restored["disclosable_page_count"] == 166
        assert restored["assembly_status"] == "IN_ASSEMBLY"
        assert restored["completeness_pct"] == 66.7


def _fully_retired_fee_ledger():
    """A 3878-cent assessment retired by a 1000-cent payment and a 2878-cent
    hardship waiver, in that order."""
    create_state_rule("CA", **CA_RULE)
    district = create_district("SEND01", state_code="CA", name="Sending Unified")
    student = create_student(
        district["id"],
        first_name="Wren",
        last_name="Alvarado",
        dob="2011-09-30",
        grade_level=9,
        has_iep=True,
        guardian_user_id="guardian-wren",
    )
    file_id = get_cumulative_file_id(student["id"])
    components = get_components(file_id)
    for component_type, pages, redactions in (
        ("ACADEMIC", 120, 0),
        ("HEALTH", 34, 4),
        ("DISCIPLINE", 18, 2),
        ("SPECIAL_EDUCATION", 260, 10),
    ):
        collect_component(file_id, components[component_type]["id"], pages, redactions)

    request = create_inspection_request(
        student["id"],
        make_parent_headers("guardian-wren"),
        categories=["ACADEMIC", "HEALTH", "DISCIPLINE", "SPECIAL_EDUCATION"],
        copies_requested=True,
    )
    assert request["fee_assessed_cents"] == 3878
    after_payment = pay_fee(request["id"], 1000, "PAYMENT", headers=CLERK)
    after_waiver = pay_fee(request["id"], 2878, "WAIVER", headers=OFFICER_1)
    return request, after_payment, after_waiver


class TestFeeCustodyAcrossPaymentAndWaiver:
    def test_the_three_way_split_moves_while_the_assessment_never_does(self):
        """The 1000-cent payment leaves 2878 outstanding and the waiver retires
        exactly that remainder, so the assessment stays at 3878 throughout while
        collected, waived and outstanding always sum to it.

        PRD: "The **fee-custody identity** holds on every inspection request after every fee transaction: `fee_assessed_cents` always equals `fee_collected_cents` plus `fee_waived_cents` plus `fee_outstanding_cents`."

        Design: Difficulty/compensating_invariant/fee_custody_preserved_by_payment_and_waiver
        """
        request, after_payment, after_waiver = _fully_retired_fee_ledger()

        assert after_payment["fee_assessed_cents"] == 3878
        assert after_payment["fee_collected_cents"] == 1000
        assert after_payment["fee_waived_cents"] == 0
        assert after_payment["fee_outstanding_cents"] == 2878
        assert_fee_custody_identity(after_payment)

        assert after_waiver["fee_assessed_cents"] == 3878
        assert after_waiver["fee_collected_cents"] == 1000
        assert after_waiver["fee_waived_cents"] == 2878
        assert after_waiver["fee_outstanding_cents"] == 0
        assert_fee_custody_identity(after_waiver)

        final = get_inspection_request(request["id"])
        assert_inspection_request(final)
        assert final["fee_assessed_cents"] == 3878
        assert final["status"] == "SUBMITTED"

    def test_one_further_cent_is_refused_rather_than_breaking_the_ledger(self):
        """With nothing outstanding, a single further cent cannot be absorbed
        anywhere without either driving the outstanding balance negative or
        inflating the assessment, so it is refused outright.

        PRD: "No payment or waiver may exceed the current `fee_outstanding_cents`; one that would is refused with `ERR_FEE_OVERPAYMENT`, which is what keeps the fee-custody identity of §2.11 true at every instant."

        Design: Difficulty/compensating_invariant/fee_custody_preserved_by_payment_and_waiver
        """
        request, _after_payment, _after_waiver = _fully_retired_fee_ledger()

        response = api_client.create_fee_transaction(
            request["id"], fee_transaction_payload("PAYMENT", 1), CLERK
        )

        validate_error(response, "ERR_FEE_OVERPAYMENT", 422)

        unchanged = get_inspection_request(request["id"])
        assert_fee_custody_identity(unchanged)
        assert unchanged["fee_assessed_cents"] == 3878
        assert unchanged["fee_collected_cents"] == 1000
        assert unchanged["fee_waived_cents"] == 2878
        assert unchanged["fee_outstanding_cents"] == 0
        assert unchanged["status"] == "SUBMITTED"
