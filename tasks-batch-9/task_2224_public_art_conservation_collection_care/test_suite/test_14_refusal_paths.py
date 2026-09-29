"""Refusal paths: the guards that stop a deaccession, a relocation, a proposal
draft, a reservation, a claim and a routine care completion — and the proof that
a refused request leaves the register exactly as it found it.
"""

from test_helpers import (
    ApiErrorId,
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.assertions import assert_no_version_change
from test_helpers.constants import DEDUCTIBLE_CENTS
from test_helpers.factories import (
    condition_assessment_payload,
    damage_incident_payload,
    funding_allocation_payload,
    maintenance_visit_payload,
    treatment_proposal_payload,
)
from test_helpers.fixtures import (
    create_artist,
    create_artwork,
    create_assessment,
    create_conservator,
    create_protocol,
    create_site,
    create_proposal_with_lines,
    current_artwork_version,
    current_pool_version,
    file_claim,
    open_case,
    open_consultation,
    read_artwork,
    read_assessment,
    read_case,
    read_consultation,
    read_incident,
    read_pool,
    read_proposal,
    read_site,
    read_visit,
    reserve_allocation,
    schedule_visit,
    set_clock,
    setup_assessment_finalized,
    setup_case_approved,
    setup_case_at_board_review,
    setup_incident_triaged,
    setup_register,
)
from test_helpers.test_users import (
    COMMISSION_MEMBER_USER_IDS,
    TEST_USERS,
    make_artist_representative_headers,
    make_commission_member_headers,
)


# --------------------------------------------------------------------------
# The deaccession process: comment period, initiator and one ballot per member
# --------------------------------------------------------------------------
def test_board_review_cannot_open_before_public_comment_closes(api):
    """PRD §3.8: "The second advance moves it `PUBLIC_COMMENT → BOARD_REVIEW` and
    requires the logical clock to be at or after `public_comment_closes_at`; an
    earlier attempt is refused with `ERR_PUBLIC_COMMENT_OPEN`."

    Design: Corner/errors/board_review_refuses_early_advance_and_irregular_ballots
    """
    register = setup_register(api)
    case = open_case(
        api,
        register["artwork"]["id"],
        disposition="SALE",
        disposition_target_ref="AUCTION-HOUSE-7",
        comment_days=7,
    )
    case = validate_success(
        api.advance_deaccession_case(
            case["id"], {"advance_note": "open the comment period"}, TEST_USERS["manager_headers"]
        )
    )
    assert case["status"] == "PUBLIC_COMMENT"

    # The clock still stands at 2026-08-01, well before the closing instant.
    validate_error(
        api.advance_deaccession_case(case["id"], {}, TEST_USERS["manager_headers"]),
        ApiErrorId.ERR_PUBLIC_COMMENT_OPEN.value,
    )

    after = read_case(api, case["id"])
    assert after["status"] == "PUBLIC_COMMENT", "a refused advance leaves the case open to comment"
    assert_no_version_change(case, after, "deaccession case")


def test_case_initiator_may_not_cast_an_approve_ballot(api):
    """PRD §3.8: "The initiator is not disenfranchised but is disarmed — where the
    acting `X-User-ID` equals `initiated_by_user_id`, an `APPROVE` or `DENY` ballot
    is refused with `ERR_INITIATOR_CANNOT_VOTE`, while `ABSTAIN` and `RECUSE`
    remain available to them."

    Design: Corner/errors/board_review_refuses_early_advance_and_irregular_ballots
    """
    register = setup_register(api)
    case = setup_case_at_board_review(api, register["artwork"]["id"], comment_days=7)
    assert case["status"] == "BOARD_REVIEW"

    # The manager who opened the case is the acting user here.
    validate_error(
        api.cast_deaccession_ballot(
            case["id"],
            {"ballot": "APPROVE", "ballot_note": "I initiated this case"},
            TEST_USERS["manager_headers"],
        ),
        ApiErrorId.ERR_INITIATOR_CANNOT_VOTE.value,
    )

    after = read_case(api, case["id"])
    assert after["approve_count"] == 0, "the refused ballot must not be tallied"
    assert after["vote_records"] == [], "the refused ballot must not be recorded"
    assert after["status"] == "BOARD_REVIEW"
    assert_no_version_change(case, after, "deaccession case")

    # A recusal from the same initiator is still available to them.
    recused = validate_success(
        api.cast_deaccession_ballot(
            case["id"], {"ballot": "RECUSE"}, TEST_USERS["manager_headers"]
        )
    )
    assert recused["recuse_count"] == 1


def test_a_commission_member_cannot_cast_a_second_ballot(api):
    """PRD §3.8: "A member may vote once: a second ballot bearing a
    `member_user_id` already present in `vote_records` is refused with
    `ERR_DUPLICATE_BALLOT`."

    Design: Corner/errors/board_review_refuses_early_advance_and_irregular_ballots
    """
    register = setup_register(api)
    case = setup_case_at_board_review(api, register["artwork"]["id"], comment_days=7)
    member_headers = make_commission_member_headers(COMMISSION_MEMBER_USER_IDS[0])

    voted = validate_success(
        api.cast_deaccession_ballot(case["id"], {"ballot": "APPROVE"}, member_headers)
    )
    assert voted["approve_count"] == 1

    validate_error(
        api.cast_deaccession_ballot(
            case["id"],
            {"ballot": "DENY", "ballot_note": "changed my mind"},
            member_headers,
        ),
        ApiErrorId.ERR_DUPLICATE_BALLOT.value,
    )

    after = read_case(api, case["id"])
    assert after["approve_count"] == 1
    assert after["deny_count"] == 0, "the duplicate ballot must not be tallied"
    assert len(after["vote_records"]) == 1
    assert after["status"] == "BOARD_REVIEW"
    assert_no_version_change(voted, after, "deaccession case")


# --------------------------------------------------------------------------
# Moral rights: the statutory notice and the protection of recognized stature
# --------------------------------------------------------------------------
def test_withdrawal_into_storage_needs_a_matured_relocation_notice(api):
    """PRD §3.7: "Withdrawal into storage counts as a removal from public view for
    moral-rights purposes: where the work's `moral_rights_status` is `ACTIVE`, a
    matured `RELOCATION` notice must exist and is consumed by the move, as
    described in §3.6."
    PRD §3.6: "A notice on that work whose `action_type` matches the action being
    taken and whose `status` is `ACKNOWLEDGED` or `WAIT_ELAPSED` must exist, and
    absent one the action is refused with `ERR_MORAL_RIGHTS_NOTICE_REQUIRED`."

    Design: Corner/errors/execution_refuses_a_work_of_recognized_stature_and_relocation_without_notice
    """
    register = setup_register(api)
    artwork = register["artwork"]
    assert artwork["moral_rights_status"] == "ACTIVE"
    assert artwork["open_notice_count"] == 0

    validate_error(
        api.relocate_artwork(
            artwork["id"],
            {"to_storage": True, "relocation_note": "move to storage pending disposal"},
            TEST_USERS["registrar_headers"],
        ),
        ApiErrorId.ERR_MORAL_RIGHTS_NOTICE_REQUIRED.value,
    )

    after = read_artwork(api, artwork["id"])
    assert after["custody_status"] == "ON_VIEW", "a refused relocation does not move the work"
    assert_no_version_change(artwork, after, "artwork")
    site = read_site(api, register["site"]["id"])
    assert site["installed_units_used"] == artwork["footprint_units"], (
        "the work still occupies its plinth"
    )


def test_destruction_of_a_work_of_recognized_stature_is_refused(api):
    """PRD §3.8: "A `DESTRUCTION` disposition may only execute when the work's
    `recognized_stature` is false; a protected work draws
    `ERR_RECOGNIZED_STATURE_PROTECTED`."
    PRD §2.8: "Checks are evaluated in the following sequence, and the first one
    that fails ends the request:" — stature protection stands at "14. Protection of
    works of recognized stature from destruction — `ERR_RECOGNIZED_STATURE_PROTECTED`."
    ahead of "18. Existence of a matching moral-rights notice —
    `ERR_MORAL_RIGHTS_NOTICE_REQUIRED`."

    Design: Corner/errors/execution_refuses_a_work_of_recognized_stature_and_relocation_without_notice
    """
    register = setup_register(api, artwork={"recognized_stature": True})
    artwork = register["artwork"]
    case = setup_case_approved(
        api, artwork["id"], disposition="DESTRUCTION", comment_days=7
    )
    assert case["status"] == "APPROVED"
    assert case["approve_count"] == 5

    # The work is protected and also carries no matured notice; the protection
    # of stature is the earlier check of the two.
    validate_error(
        api.execute_deaccession_case(
            case["id"],
            {"execution_note": "board approved destruction"},
            TEST_USERS["manager_headers"],
        ),
        ApiErrorId.ERR_RECOGNIZED_STATURE_PROTECTED.value,
    )

    case_after = read_case(api, case["id"])
    assert case_after["status"] == "APPROVED"
    assert case_after["executed_at"] is None
    assert_no_version_change(case, case_after, "deaccession case")
    artwork_after = read_artwork(api, artwork["id"])
    assert artwork_after["custody_status"] == "ON_VIEW", (
        "a refused execution is not a partial execution"
    )


# --------------------------------------------------------------------------
# A work that has left the collection is closed to every write
# --------------------------------------------------------------------------
def test_no_write_touches_a_work_that_has_left_the_collection(api):
    """PRD §2.8: "The referenced artwork is not already out of the collection —
    `ERR_ARTWORK_DEACCESSIONED`. This guards every write that references an
    artwork."
    PRD §3.7: "Either direction is refused with `ERR_ARTWORK_CUSTODY_INVALID` when
    the work's custody is not the expected origin — a work `IN_TREATMENT` cannot be
    relocated at all — and with `ERR_ARTWORK_DEACCESSIONED` when the work has
    already left the collection."

    Design: Corner/errors/every_write_against_a_deaccessioned_work_is_refused
    """
    register = setup_register(
        api,
        artist={
            "full_name": "Bo Reyes",
            "contact_email": "bo@example.gov",
            "moral_rights_waiver_on_file": True,
        },
    )
    artwork = register["artwork"]
    assert artwork["moral_rights_status"] == "WAIVED", "a waiver means no notice is needed"
    protocol = create_protocol(api)

    case = setup_case_approved(
        api,
        artwork["id"],
        disposition="SALE",
        disposition_target_ref="AUCTION-HOUSE-7",
        comment_days=7,
    )
    case = get_success_data(
        api.execute_deaccession_case(
            case["id"], {"execution_note": "sold at auction"}, TEST_USERS["manager_headers"]
        )
    )
    assert case["status"] == "EXECUTED"

    before = read_artwork(api, artwork["id"])
    assert before["custody_status"] == "DEACCESSIONED"

    validate_error(
        api.create_condition_assessment(
            condition_assessment_payload(artwork["id"], assessed_on="2026-08-08"),
            TEST_USERS["surveyor_headers"],
        ),
        ApiErrorId.ERR_ARTWORK_DEACCESSIONED.value,
    )
    validate_error(
        api.create_maintenance_visit(
            maintenance_visit_payload(
                artwork["id"],
                protocol["id"],
                window_start="2026-09-01T09:00:00Z",
                window_end="2026-09-02T17:00:00Z",
            ),
            TEST_USERS["crew_headers"],
        ),
        ApiErrorId.ERR_ARTWORK_DEACCESSIONED.value,
    )
    validate_error(
        api.create_damage_incident(
            damage_incident_payload(
                artwork["id"], damage_extent_pct=0.2, narrative="spray paint on the base"
            ),
            TEST_USERS["registrar_headers"],
        ),
        ApiErrorId.ERR_ARTWORK_DEACCESSIONED.value,
    )
    validate_error(
        api.relocate_artwork(
            artwork["id"], {"to_storage": True}, TEST_USERS["registrar_headers"]
        ),
        ApiErrorId.ERR_ARTWORK_DEACCESSIONED.value,
    )

    after = read_artwork(api, artwork["id"])
    assert after["custody_status"] == "DEACCESSIONED"
    assert_no_version_change(before, after, "artwork")
    _, assessment_meta = validate_paginated(
        api.list_condition_assessments(
            TEST_USERS["surveyor_headers"], params={"artwork_id": artwork["id"]}
        )
    )
    assert assessment_meta["total_count"] == 0, "no survey was written"
    _, incident_meta = validate_paginated(
        api.list_damage_incidents(
            TEST_USERS["registrar_headers"], params={"artwork_id": artwork["id"]}
        )
    )
    assert incident_meta["total_count"] == 0, "no incident was written"


# --------------------------------------------------------------------------
# Drafting a proposal: the cited survey on three axes
# --------------------------------------------------------------------------
def test_proposal_cannot_cite_a_survey_still_in_draft(api):
    """PRD §3.4: "The cited survey must be in `FINALIZED` and must belong to the
    same work as the proposal, failing which the draft is refused with
    `ERR_ASSESSMENT_NOT_FINALIZED`."

    Design: Corner/errors/proposal_creation_refuses_unfinalized_foreign_and_already_used_surveys
    """
    register = setup_register(api)
    artwork = register["artwork"]
    conservator = create_conservator(api)
    draft_survey = create_assessment(api, artwork["id"])
    assert draft_survey["status"] == "DRAFT"

    validate_error(
        api.create_treatment_proposal(
            treatment_proposal_payload(
                artwork["id"],
                conservator["id"],
                draft_survey["id"],
                current_artwork_version(api, artwork["id"]),
                treatment_scope="SURFACE",
            ),
            TEST_USERS["chief_conservator_headers"],
        ),
        ApiErrorId.ERR_ASSESSMENT_NOT_FINALIZED.value,
    )

    survey_after = read_assessment(api, draft_survey["id"])
    assert survey_after["status"] == "DRAFT"
    assert_no_version_change(draft_survey, survey_after, "condition survey")
    _, meta = validate_paginated(
        api.list_treatment_proposals(
            TEST_USERS["chief_conservator_headers"], params={"artwork_id": artwork["id"]}
        )
    )
    assert meta["total_count"] == 0, "no proposal was created"


def test_proposal_cannot_cite_a_finalized_survey_of_another_work(api):
    """PRD §3.4: "The cited survey must be in `FINALIZED` and must belong to the
    same work as the proposal, failing which the draft is refused with
    `ERR_ASSESSMENT_NOT_FINALIZED`."

    Design: Corner/errors/proposal_creation_refuses_unfinalized_foreign_and_already_used_surveys
    """
    artist = create_artist(api)
    site = create_site(api)
    work_a = create_artwork(api, artist["id"], site["id"])
    work_b = create_artwork(
        api,
        artist["id"],
        site["id"],
        accession_number="2024.002",
        title="Seated Figure",
        significance_tier="STANDARD",
        footprint_units=4,
    )
    conservator = create_conservator(api)
    survey_b = setup_assessment_finalized(api, work_b["id"])
    assert survey_b["status"] == "FINALIZED"

    validate_error(
        api.create_treatment_proposal(
            treatment_proposal_payload(
                work_a["id"],
                conservator["id"],
                survey_b["id"],
                current_artwork_version(api, work_a["id"]),
                treatment_scope="SURFACE",
                engagement_start="2026-10-01T00:00:00Z",
                engagement_end="2026-10-05T00:00:00Z",
            ),
            TEST_USERS["chief_conservator_headers"],
        ),
        ApiErrorId.ERR_ASSESSMENT_NOT_FINALIZED.value,
    )

    survey_after = read_assessment(api, survey_b["id"])
    assert survey_after["status"] == "FINALIZED", "the foreign survey is untouched"
    assert_no_version_change(survey_b, survey_after, "condition survey")
    _, meta = validate_paginated(
        api.list_treatment_proposals(
            TEST_USERS["chief_conservator_headers"], params={"artwork_id": work_a["id"]}
        )
    )
    assert meta["total_count"] == 0, "no proposal was created"


def test_a_second_proposal_on_the_same_survey_is_refused(api):
    """PRD §3.4: "Only one live proposal may exist per survey: if another proposal
    already cites the same `assessment_id` and sits in `DRAFT`, `SUBMITTED`,
    `REVISION_REQUESTED`, `APPROVED` or `IN_EXECUTION`, the draft is refused with
    `ERR_DUPLICATE_ACTIVE_PROPOSAL`."

    Design: Corner/errors/proposal_creation_refuses_unfinalized_foreign_and_already_used_surveys
    """
    register = setup_register(api)
    artwork = register["artwork"]
    conservator = create_conservator(api)
    survey = setup_assessment_finalized(api, artwork["id"])
    first = create_proposal_with_lines(
        api, artwork["id"], conservator["id"], survey["id"], lines=[]
    )
    assert first["status"] == "DRAFT"

    # Drafting moved the work's own version, so the second attempt re-reads it.
    validate_error(
        api.create_treatment_proposal(
            treatment_proposal_payload(
                artwork["id"],
                conservator["id"],
                survey["id"],
                current_artwork_version(api, artwork["id"]),
                treatment_scope="STABILIZATION",
                engagement_start="2026-11-01T00:00:00Z",
                engagement_end="2026-11-05T00:00:00Z",
            ),
            TEST_USERS["chief_conservator_headers"],
        ),
        ApiErrorId.ERR_DUPLICATE_ACTIVE_PROPOSAL.value,
    )

    first_after = read_proposal(api, first["id"])
    assert first_after["status"] == "DRAFT"
    assert_no_version_change(first, first_after, "treatment proposal")
    _, meta = validate_paginated(
        api.list_treatment_proposals(
            TEST_USERS["chief_conservator_headers"], params={"assessment_id": survey["id"]}
        )
    )
    assert meta["total_count"] == 1, "the survey still backs exactly one proposal"


# --------------------------------------------------------------------------
# Reserving money: the purpose/link pairing and the availability ceiling
# --------------------------------------------------------------------------
def _percent_for_art_pool(api, set_aside_cents: int = 100_000) -> dict:
    """A set-aside pool: no principal, no draw rate and no administrative fee."""
    return get_success_data(
        api.create_funding_pool(
            {
                "pool_code": "PFA-2026",
                "pool_type": "PERCENT_FOR_ART",
                "fiscal_year": 2026,
                "set_aside_cents": set_aside_cents,
            },
            TEST_USERS["finance_headers"],
        ),
        201,
    )


def _draft_proposal_to_fund(api) -> dict:
    """A DRAFT treatment proposal a reservation can name."""
    register = setup_register(api)
    conservator = create_conservator(api)
    survey = setup_assessment_finalized(api, register["artwork"]["id"])
    return create_proposal_with_lines(
        api, register["artwork"]["id"], conservator["id"], survey["id"], lines=[]
    )


def test_maintenance_reservation_carrying_a_proposal_link_is_refused(api):
    """PRD §3.10: "Exactly one link must accompany the purpose: `TREATMENT`
    requires a `proposal_id` with `visit_id` left null, and `MAINTENANCE` requires
    a `visit_id` with `proposal_id` left null. Supplying the wrong link, or both,
    is refused with `ERR_ALLOCATION_LINK_MISMATCH`."

    Design: Corner/errors/allocation_refuses_link_mismatches_and_overdraws_at_the_exact_balance
    """
    proposal = _draft_proposal_to_fund(api)
    pool = _percent_for_art_pool(api)
    assert pool["available_cents"] == 100_000

    validate_error(
        api.create_funding_allocation(
            funding_allocation_payload(
                pool["id"],
                current_pool_version(api, pool["id"]),
                purpose="MAINTENANCE",
                amount_cents=50_000,
                proposal_id=proposal["id"],
            ),
            TEST_USERS["finance_headers"],
        ),
        ApiErrorId.ERR_ALLOCATION_LINK_MISMATCH.value,
    )

    pool_after = read_pool(api, pool["id"])
    assert pool_after["available_cents"] == 100_000, "a refused reservation encumbers nothing"
    assert_no_version_change(pool, pool_after, "funding pool")
    _, meta = validate_paginated(
        api.list_funding_allocations(
            TEST_USERS["finance_headers"], params={"pool_id": pool["id"]}
        )
    )
    assert meta["total_count"] == 0, "no allocation was created"


def test_reservation_beyond_the_pool_balance_is_refused_at_the_exact_edge(api):
    """PRD §3.10: "The requested `amount_cents` must not exceed the pool's
    `available_cents` at reservation time, failing which the request draws
    `ERR_POOL_FUNDS_INSUFFICIENT`."
    PRD §3.10: "A successful reservation is created in `RESERVED` with
    `release_reason` of `NONE` and `released_at` null, lowers the pool's
    `available_cents` by `amount_cents`, and increments the pool's own `version` —
    which is what makes a second reservation from a stale read fail."

    Design: Corner/errors/allocation_refuses_link_mismatches_and_overdraws_at_the_exact_balance
    """
    proposal = _draft_proposal_to_fund(api)
    pool = _percent_for_art_pool(api)
    assert pool["available_cents"] == 100_000
    assert pool["admin_fee_cents"] == 0

    # One cent over the balance is refused.
    validate_error(
        api.create_funding_allocation(
            funding_allocation_payload(
                pool["id"],
                current_pool_version(api, pool["id"]),
                purpose="TREATMENT",
                amount_cents=100_001,
                proposal_id=proposal["id"],
            ),
            TEST_USERS["finance_headers"],
        ),
        ApiErrorId.ERR_POOL_FUNDS_INSUFFICIENT.value,
    )
    pool_after_refusal = read_pool(api, pool["id"])
    assert pool_after_refusal["available_cents"] == 100_000
    assert_no_version_change(pool, pool_after_refusal, "funding pool")

    # The exact balance is not an overdraw; it drives availability to zero.
    allocation = reserve_allocation(
        api,
        pool["id"],
        purpose="TREATMENT",
        amount_cents=100_000,
        proposal_id=proposal["id"],
    )
    assert allocation["status"] == "RESERVED"
    exhausted = read_pool(api, pool["id"])
    assert exhausted["available_cents"] == 0

    # From an exhausted pool even a single cent is refused.
    validate_error(
        api.create_funding_allocation(
            funding_allocation_payload(
                pool["id"],
                current_pool_version(api, pool["id"]),
                purpose="TREATMENT",
                amount_cents=1,
                proposal_id=proposal["id"],
            ),
            TEST_USERS["finance_headers"],
        ),
        ApiErrorId.ERR_POOL_FUNDS_INSUFFICIENT.value,
    )

    final_pool = read_pool(api, pool["id"])
    assert final_pool["available_cents"] == 0
    assert_no_version_change(exhausted, final_pool, "funding pool")
    _, meta = validate_paginated(
        api.list_funding_allocations(
            TEST_USERS["finance_headers"], params={"pool_id": pool["id"]}
        )
    )
    assert meta["total_count"] == 1, "only the exact-balance reservation exists"


# --------------------------------------------------------------------------
# Insurance: an unbacked basis, a missing credit pool and a zero payout
# --------------------------------------------------------------------------
def test_restoration_claim_without_a_linked_proposal_is_refused(api):
    """PRD §3.11: "A `RESTORATION` basis additionally requires
    `linked_proposal_id` to be set, that proposal to be in `APPROVED`,
    `IN_EXECUTION` or `COMPLETED`, and its `pinned_estimate_total_cents` to be
    non-null; any of those missing yields `ERR_CLAIM_BASIS_UNSUPPORTED`."

    Design: Corner/errors/claim_handling_refuses_an_unbacked_basis_a_missing_credit_pool_and_a_zero_payout
    """
    register = setup_register(api)
    incident = setup_incident_triaged(
        api, register["artwork"]["id"], narrative="base struck and gouged"
    )
    assert incident["damage_status"] == "TRIAGED"
    assert incident.get("linked_proposal_id") is None

    validate_error(
        api.file_insurance_claim(
            incident["id"],
            {"claim_basis": "RESTORATION", "policy_note": "repair cost basis"},
            TEST_USERS["finance_headers"],
        ),
        ApiErrorId.ERR_CLAIM_BASIS_UNSUPPORTED.value,
    )

    after = read_incident(api, incident["id"])
    assert after["claim_status"] == "NONE", "the claim dimension did not move"
    assert after["claim_basis"] == "NONE"
    assert after["damage_status"] == "TRIAGED"
    assert_no_version_change(incident, after, "damage incident")


def test_settling_a_claim_without_a_credited_pool_is_refused(api):
    """PRD §3.11: "A `SETTLE` moves `claim_status` `FILED → SETTLED` and requires
    two things: `settlement_cents` must be strictly greater than zero, so a claim
    computed down to nothing after limit and deductible cannot be settled and
    draws `ERR_NO_SETTLEMENT_PAYABLE`; and `credited_pool_id` must be non-null,
    failing which the request draws `ERR_CREDIT_POOL_REQUIRED`."

    Design: Corner/errors/claim_handling_refuses_an_unbacked_basis_a_missing_credit_pool_and_a_zero_payout
    """
    register = setup_register(api)
    incident = setup_incident_triaged(api, register["artwork"]["id"])
    filed = file_claim(api, incident["id"], "ACV")
    assert filed["claim_status"] == "FILED"
    assert filed.get("credited_pool_id") is None
    assert filed["settlement_cents"] > 0, "this claim is payable; only the pool is missing"

    validate_error(
        api.resolve_insurance_claim(
            incident["id"],
            {"outcome": "SETTLE", "resolution_note": "carrier agreed"},
            TEST_USERS["finance_headers"],
        ),
        ApiErrorId.ERR_CREDIT_POOL_REQUIRED.value,
    )

    after = read_incident(api, incident["id"])
    assert after["claim_status"] == "FILED", "the claim stays filed"
    assert after["damage_status"] == "TRIAGED"
    assert_no_version_change(filed, after, "damage incident")


def test_a_claim_computed_below_the_deductible_cannot_be_settled(api):
    """PRD §3.11: "The gross claim is first capped at the policy limit of
    25,000,000 cents (250,000 dollars), the deductible of 250,000 cents (2,500
    dollars) is then subtracted, and the result is floored at zero."
    PRD §3.11: "A `SETTLE` moves `claim_status` `FILED → SETTLED` and requires two
    things: `settlement_cents` must be strictly greater than zero, so a claim
    computed down to nothing after limit and deductible cannot be settled and
    draws `ERR_NO_SETTLEMENT_PAYABLE`; and `credited_pool_id` must be non-null,
    failing which the request draws `ERR_CREDIT_POOL_REQUIRED`."

    Design: Corner/errors/claim_handling_refuses_an_unbacked_basis_a_missing_credit_pool_and_a_zero_payout
    """
    artist = create_artist(api)
    site = create_site(api)
    artwork = create_artwork(
        api,
        artist["id"],
        site["id"],
        accession_number="2024.009",
        title="Small Marker",
        significance_tier="STANDARD",
        footprint_units=1,
        insured_value_cents=300_000,
        acquisition_document_ref="DEED-2014-009",
    )
    pool = _percent_for_art_pool(api)
    incident = setup_incident_triaged(
        api,
        artwork["id"],
        damage_extent_pct=0.5,
        credited_pool_id=pool["id"],
        narrative="second strike on the same base",
    )

    filed = file_claim(api, incident["id"], "ACV")
    assert filed["claim_status"] == "FILED"
    assert filed["claimed_gross_cents"] <= DEDUCTIBLE_CENTS
    assert filed["settlement_cents"] == 0

    validate_error(
        api.resolve_insurance_claim(
            incident["id"], {"outcome": "SETTLE"}, TEST_USERS["finance_headers"]
        ),
        ApiErrorId.ERR_NO_SETTLEMENT_PAYABLE.value,
    )

    after = read_incident(api, incident["id"])
    assert after["claim_status"] == "FILED"
    assert after["damage_status"] == "TRIAGED"
    assert_no_version_change(filed, after, "damage incident")
    pool_after = read_pool(api, pool["id"])
    assert pool_after["recovery_credits_cents"] == 0, "a refused settlement credits nothing"
    assert pool_after["available_cents"] == 100_000


# --------------------------------------------------------------------------
# Two clock-driven refusals: a late artist reply and the annual care ceiling
# --------------------------------------------------------------------------
def test_artist_response_at_the_due_instant_is_already_too_late(api):
    """PRD §3.6: "A `CONCUR` moves the row `PENDING → CONCURRED` and an `OBJECT`
    moves it `PENDING → OBJECTED`; both stamp `responded_at` from the logical
    clock, and both require the logical clock to be strictly before `due_at`."
    PRD §3.6: "A response arriving at or after `due_at` is refused with
    `ERR_CONSULTATION_WINDOW_CLOSED`."

    Design: Corner/errors/a_late_artist_response_and_a_second_annual_application_are_refused
    """
    register = setup_register(api)
    artist = register["artist"]
    consultation = open_consultation(
        api, register["artwork"]["id"], artist["id"], subject="RELOCATION"
    )
    assert consultation["status"] == "PENDING"

    # Stand the clock exactly on the due instant: the window is already closed.
    set_clock(api, consultation["due_at"])

    validate_error(
        api.respond_to_consultation(
            consultation["id"],
            {"response": "CONCUR", "response_note": "one instant too late"},
            make_artist_representative_headers(artist["id"]),
        ),
        ApiErrorId.ERR_CONSULTATION_WINDOW_CLOSED.value,
    )

    after = read_consultation(api, consultation["id"])
    assert after["status"] == "PENDING", "the row stays pending"
    assert after["responded_at"] is None
    assert_no_version_change(consultation, after, "artist consultation")


def test_second_annual_application_of_a_protocol_cannot_complete(api):
    """PRD §3.3: "Completion is refused with `ERR_MAX_ANNUAL_APPLICATIONS` unless
    the number of already-`COMPLETED` visits for this same work and this same
    protocol within the logical clock's year is strictly less than the protocol's
    `max_annual_applications`."

    Design: Corner/errors/a_late_artist_response_and_a_second_annual_application_are_refused
    """
    register = setup_register(api)
    artwork = register["artwork"]
    protocol = create_protocol(api, max_annual_applications=1)

    first = schedule_visit(api, artwork["id"], protocol["id"])
    set_clock(api, first["window_start"])
    validate_success(
        api.start_maintenance_visit(first["id"], {}, TEST_USERS["crew_headers"])
    )
    completed = validate_success(
        api.complete_maintenance_visit(
            first["id"], {"completion_note": "washed and rinsed"}, TEST_USERS["crew_headers"]
        )
    )
    assert completed["status"] == "COMPLETED"

    # Scheduling and starting a second visit are legal; the ceiling bites only
    # at completion time.
    second = schedule_visit(
        api,
        artwork["id"],
        protocol["id"],
        window_start="2026-09-10T09:00:00Z",
        window_end="2026-09-11T17:00:00Z",
    )
    set_clock(api, second["window_start"])
    started = validate_success(
        api.start_maintenance_visit(second["id"], {}, TEST_USERS["crew_headers"])
    )
    assert started["status"] == "IN_PROGRESS"

    validate_error(
        api.complete_maintenance_visit(second["id"], {}, TEST_USERS["crew_headers"]),
        ApiErrorId.ERR_MAX_ANNUAL_APPLICATIONS.value,
    )

    after = read_visit(api, second["id"])
    assert after["status"] == "IN_PROGRESS", "the refused completion leaves the visit running"
    assert after["completed_at"] is None
    assert_no_version_change(started, after, "maintenance visit")
    artwork_after = read_artwork(api, artwork["id"])
    assert artwork_after["maintenance_applications_ytd"] == 1
