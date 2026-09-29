"""Transitions gated on the state of a different row entirely.

A Part 2 submission is legal only if the property has been certified, which is a
fact about the property and not about the application. A master-lease filing is
legal only if the lessee's election has been made, which is a fact about the
investor interest and not about the claim.
"""

from test_helpers import (
    ApiErrorId,
    assertions,
    fixtures,
    get_success_data,
    validate_error,
)


def test_part_two_cannot_enter_review_while_the_property_is_unevaluated(api):
    """A CONDITIONAL Part 1 leaves the building uncertified, so Part 2 cannot submit.

    Part 1 was determined CONDITIONAL over one unresolved condition, which mutates
    only the application: the property's evaluation status is still UNEVALUATED and
    the project is still PRE_CERTIFICATION. Part 2 could be created against that
    merely conditional predecessor, but submitting it is refused, because only an
    approved Part 1 certifies the building.

    PRD: "For a Part 2 or Part 3 application, the property's `evaluation_status` must already read `CERTIFIED_HISTORIC`, else `ERR_PROPERTY_NOT_CERTIFIED_HISTORIC`; Part 1 submissions are exempt, since they are what produce the certification."
    PRD: "Creation is deliberately permitted on a merely `CONDITIONAL` predecessor so that the developer can prepare the next part while conditions are being cleared by amendment — but that next part cannot enter review until the building itself is certified, which only an `APPROVED` Part 1 produces."
    PRD: "The project's certification dimension is expressly **not** advanced, and neither the property nor any cost line item is touched — the only row mutated is the application itself."

    Design: Difficulty/cross_entity_state_dependency/part2_submission_blocked_by_property_evaluation_status
    """
    cast = fixtures.seed_cast(api)
    project = fixtures.open_project(
        api, cast, structure_type="SINGLE_TIER", adjusted_basis_cents=60_000_000
    )
    part1 = fixtures.create_part_application(api, cast, project["id"], 1)
    fixtures.submit_part_application(api, cast, part1["id"])
    fixtures.shpo_recommend(api, cast, part1["id"])
    fixtures.add_finding(
        api, cast, part1["id"], headers=cast.nps_headers, severity="CONDITION"
    )
    conditional = fixtures.nps_determine(
        api, cast, part1["id"], determination="CONDITIONAL"
    )
    part2 = fixtures.create_part_application(api, cast, project["id"], 2)
    stored_property = get_success_data(
        api.get_property(cast.property_id, cast.developer_headers)
    )
    assertions.assert_fields(
        stored_property, "property", evaluation_status="UNEVALUATED"
    )
    assertions.assert_fields(conditional, "part 1", status="CONDITIONAL")

    response = api.submit_part_application(
        part2["id"], cast.developer_headers, shpo_reviewer_id=cast.shpo_reviewer_id
    )

    validate_error(response, ApiErrorId.PROPERTY_NOT_CERTIFIED_HISTORIC.value, 422)


def test_the_refused_part_two_submission_stays_in_draft_and_moves_no_project(api):
    """The blocked submission leaves the application unstamped and the project alone.

    Part 2 is still DRAFT with no submitted timestamp, no review window and no
    reviewer written onto it, because none of that happens until submission
    succeeds. The project's certification dimension is still PRE_CERTIFICATION,
    which is where the CONDITIONAL determination on Part 1 left it.

    PRD: "Submission moves an application from `DRAFT` to `SHPO_REVIEW` and is the point at which the state preservation office reviewer is chosen: the developer supplies `shpo_reviewer_id`, which is written onto the application."
    PRD: "A new application begins in `DRAFT` with `review_round` at 1, `shpo_reviewer_id` and `nps_reviewer_id` null, `submitted_at`, `review_window_end` and `decision_at` null, `shpo_recommendation` and `determination` both `NONE`, and both `unresolved_condition_count` and `unresolved_violation_count` at zero."

    Design: Difficulty/cross_entity_state_dependency/part2_submission_blocked_by_property_evaluation_status
    """
    cast = fixtures.seed_cast(api)
    project = fixtures.open_project(
        api, cast, structure_type="SINGLE_TIER", adjusted_basis_cents=60_000_000
    )
    part1 = fixtures.create_part_application(api, cast, project["id"], 1)
    fixtures.submit_part_application(api, cast, part1["id"])
    fixtures.shpo_recommend(api, cast, part1["id"])
    fixtures.add_finding(
        api, cast, part1["id"], headers=cast.nps_headers, severity="CONDITION"
    )
    fixtures.nps_determine(api, cast, part1["id"], determination="CONDITIONAL")
    part2 = fixtures.create_part_application(api, cast, project["id"], 2)

    validate_error(
        api.submit_part_application(
            part2["id"], cast.developer_headers, shpo_reviewer_id=cast.shpo_reviewer_id
        ),
        ApiErrorId.PROPERTY_NOT_CERTIFIED_HISTORIC.value,
        422,
    )

    stored = get_success_data(
        api.get_part_application(part2["id"], cast.developer_headers)
    )
    assertions.assert_fields(
        stored,
        "part 2 after the refused submission",
        status="DRAFT",
        submitted_at=None,
        review_window_end=None,
        shpo_reviewer_id=None,
        review_round=1,
    )
    assertions.assert_project_state(
        fixtures.read_project(api, cast, project["id"]),
        certification_status="PRE_CERTIFICATION",
        compliance_status="NOT_MONITORED",
    )


def test_a_master_lease_claim_cannot_be_filed_while_the_election_is_pending(api):
    """The filing is gated on the lessee's election, not on the claim's own state.

    A master-lease lessee is admitted without electing, so its election reads
    PENDING and its admission score carries the 12-point pending-election penalty on
    top of 10 base, 10 for PARTNERSHIP status and 22 for a 23-year lease: 54, which
    is well below the disqualification threshold. The 2029 claim is a clean DRAFT on
    a fully certified project, and it is still refused, because without the election
    the credit stays with the lessor.

    PRD: "On a project whose `structure_type` is `MASTER_LEASE`, the master-lease lessee's `pass_through_election` must read `ELECTED`, because without the election the credit stays with the lessor and the lessee has nothing to claim; the shortfall is refused with `ERR_PASS_THROUGH_ELECTION_REQUIRED`."
    PRD: "A successfully admitted interest has `status` of `ADMITTED`, `election_at` null, and `pass_through_election` of `PENDING` when its `kind` is `MASTER_LEASE_LESSEE` or `NOT_APPLICABLE` when it is `DIRECT_PARTNER`."
    PRD: "Finally, an interest whose `pass_through_election` is still `PENDING` adds 12 points, and adds nothing once it is `ELECTED` or `NOT_APPLICABLE`."

    Design: Difficulty/cross_entity_state_dependency/claim_filing_blocked_by_master_lease_pass_through_election_state
    """
    scenario = fixtures.part3_certified_project(
        api,
        structure_type="MASTER_LEASE",
        adjusted_basis_cents=60_000_000,
        qre_cents=62_500_013,
    )
    cast = scenario["cast"]
    project_id = scenario["project"]["id"]
    interest = fixtures.admit_master_lease_lessee(
        api,
        cast,
        project_id,
        elect=False,
        party_tax_status="PARTNERSHIP",
        lease_term_years=23,
    )
    claim = fixtures.create_claim(api, interest, project_id, tax_year=2029)
    assertions.assert_fields(
        interest,
        "unelected lessee",
        pass_through_election="PENDING",
        election_at=None,
        status="ADMITTED",
    )
    assertions.assert_risk_score(interest, 54, "ADMISSION")

    response = api.file_credit_claim(claim["id"], fixtures.investor_headers(interest))

    validate_error(response, ApiErrorId.PASS_THROUGH_ELECTION_REQUIRED.value, 422)


def test_the_refused_filing_leaves_the_draft_claim_and_the_ledger_untouched(api):
    """Nothing is claimed, so the whole five-year credit is still unclaimed.

    The claim stays DRAFT with its offset and net figures at zero and no filing
    timestamp, since those are only written at filing; its gross figure is the
    2500001 snapshotted when it was opened. The project's claimed-to-date remains
    zero and its unclaimed column still holds the entire 12500005 that the frozen
    schedule promises.

    PRD: "The claim opens with `status` of `DRAFT`, `recapture_offset_cents` and `net_claim_cents` at zero, and `filed_at` and `filed_by_user_id` null."
    PRD: "A new claim snapshots the project's per-year credit: `gross_credit_cents` is set to the project's `annual_credit_cents` as it stands at claim creation, and it is deliberately **not** re-read at filing time."
    PRD: "`credit_unclaimed_cents` is then `total_claimable_credit_cents` less `credit_claimed_to_date_cents` less `credit_recaptured_cents`."

    Design: Difficulty/cross_entity_state_dependency/claim_filing_blocked_by_master_lease_pass_through_election_state
    """
    scenario = fixtures.part3_certified_project(
        api,
        structure_type="MASTER_LEASE",
        adjusted_basis_cents=60_000_000,
        qre_cents=62_500_013,
    )
    cast = scenario["cast"]
    project_id = scenario["project"]["id"]
    interest = fixtures.admit_master_lease_lessee(
        api,
        cast,
        project_id,
        elect=False,
        party_tax_status="PARTNERSHIP",
        lease_term_years=23,
    )
    claim = fixtures.create_claim(api, interest, project_id, tax_year=2029)

    validate_error(
        api.file_credit_claim(claim["id"], fixtures.investor_headers(interest)),
        ApiErrorId.PASS_THROUGH_ELECTION_REQUIRED.value,
        422,
    )

    stored = get_success_data(
        api.get_credit_claim(claim["id"], cast.developer_headers)
    )
    assertions.assert_fields(
        stored,
        "claim after the refused filing",
        status="DRAFT",
        net_claim_cents=0,
        gross_credit_cents=2_500_001,
        recapture_offset_cents=0,
        filed_at=None,
    )
    project = fixtures.read_project(api, cast, project_id)
    assertions.assert_ledger(
        project,
        credit_claimed_to_date_cents=0,
        credit_recaptured_cents=0,
        credit_unclaimed_cents=12_500_005,
        total_claimable_credit_cents=12_500_005,
    )
    assertions.assert_credit_conservation(project)
