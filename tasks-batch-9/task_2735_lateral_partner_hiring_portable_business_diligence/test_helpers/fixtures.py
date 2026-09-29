"""Composite setup helpers for the Lateral Partner Hiring API.

Every helper builds its preconditions from scratch through PRD-declared
endpoints, because the harness restarts the server against an empty database
before each test. Setup calls use the lenient ``get_success_data`` validator so a
broken precondition reports as a setup failure rather than as a mysterious
assertion.

The scenario dictionaries returned by these helpers use stable keys:

    practice_group, second_practice_group, search_firm, engagement, candidate,
    questionnaire, entries (client_name -> entry), records, assessment,
    conflict_checks (client_name -> check), waiver, declinations, offer, votes,
    plan, introduction, and the pre-threaded header dicts candidate_headers and
    leader_headers.
"""

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import DEFAULT_CLOCK
from .factories import (
    DEFAULTS,
    cast_vote_payload,
    clear_conflict_check_payload,
    create_assessment_payload,
    create_candidate_payload,
    create_client_book_entry_payload,
    create_collection_record_payload,
    create_conflict_check_payload,
    create_conflict_waiver_payload,
    create_engagement_payload,
    create_integration_plan_payload,
    create_introduction_payload,
    create_offer_payload,
    create_performance_review_payload,
    create_practice_group_payload,
    create_questionnaire_payload,
    create_search_firm_payload,
    refuse_waiver_payload,
    submit_offer_payload,
)
from .test_users import (
    CHAIR_USER_ID,
    MEMBER_1_USER_ID,
    MEMBER_2_USER_ID,
    MEMBER_3_USER_ID,
    PEER_CHAIR_USER_ID,
    TEST_USERS,
    make_candidate_headers,
    make_committee_chair_headers,
    make_committee_member_headers,
    make_practice_group_leader_headers,
)

ADMIN = TEST_USERS["system_admin_headers"]
COORDINATOR = TEST_USERS["recruiting_coordinator_headers"]
COUNSEL = TEST_USERS["conflicts_counsel_headers"]
CHAIR = TEST_USERS["committee_chair_headers"]
PEER_CHAIR = TEST_USERS["peer_committee_chair_headers"]


# ----------------------------------------------------------------------
# Canonical client book specifications
# ----------------------------------------------------------------------

# Entry A yields baseline_portable_amount_usd 1269000.00.
ENTRY_A_SPEC = {
    "client_name": "Northwind Holdings",
    "relationship_role": "BILLING_ATTORNEY",
    "client_consent_status": "CONSENT_CONFIRMED",
    "claimed_annual_billings_usd": 1600000.00,
    "claimed_portability_pct": 0.8000,
    "claimed_realization_rate": 1.0000,
    "matter_types": ["M_AND_A", "SECURITIES"],
}
ENTRY_A_RECORDS = [
    ("2023-12-31T00:00:00.000Z", 1410000.00),
    ("2024-12-31T00:00:00.000Z", 1410000.00),
    ("2025-12-31T00:00:00.000Z", 1410000.00),
]

# Entry B yields baseline_portable_amount_usd 332112.15.
ENTRY_B_SPEC = {
    "client_name": "Calder Manufacturing",
    "relationship_role": "RELATIONSHIP_PARTNER",
    "client_consent_status": "CONSENT_PENDING",
    "claimed_annual_billings_usd": 900000.00,
    "claimed_portability_pct": 0.7000,
    "claimed_realization_rate": 0.8800,
    "matter_types": ["LITIGATION", "EMPLOYMENT"],
}
ENTRY_B_RECORDS = [
    ("2023-12-31T00:00:00.000Z", 740000.00),
    ("2024-12-31T00:00:00.000Z", 740000.00),
    ("2025-12-31T00:00:00.000Z", 740001.00),
]

# Entry C yields baseline_portable_amount_usd 219450.00.
ENTRY_C_SPEC = {
    "client_name": "Ridgeline Foods",
    "relationship_role": "SERVICE_PARTNER",
    "client_consent_status": "CONSENT_CONFIRMED",
    "claimed_annual_billings_usd": 500000.00,
    "claimed_portability_pct": 0.8200,
    "claimed_realization_rate": 0.9900,
    "matter_types": ["TAX"],
}
ENTRY_C_RECORDS = [
    ("2023-12-31T00:00:00.000Z", 420000.00),
    ("2024-12-31T00:00:00.000Z", 420000.00),
    ("2025-12-31T00:00:00.000Z", 420000.00),
]

BOOK_SPECS = {
    "SLIM": [(ENTRY_A_SPEC, ENTRY_A_RECORDS)],
    "AB": [(ENTRY_A_SPEC, ENTRY_A_RECORDS), (ENTRY_B_SPEC, ENTRY_B_RECORDS)],
    "FULL": [
        (ENTRY_A_SPEC, ENTRY_A_RECORDS),
        (ENTRY_B_SPEC, ENTRY_B_RECORDS),
        (ENTRY_C_SPEC, ENTRY_C_RECORDS),
    ],
}


# ----------------------------------------------------------------------
# Tier 0: primitives
# ----------------------------------------------------------------------


def set_logical_clock(to_iso8601: str) -> dict:
    """Move the logical clock, running the three clock-driven sweeps."""
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


def new_practice_group(**overrides) -> dict:
    return get_success_data(
        api_client.create_practice_group(create_practice_group_payload(**overrides), ADMIN)
    )


def new_search_firm(**overrides) -> dict:
    return get_success_data(
        api_client.create_search_firm(create_search_firm_payload(**overrides), ADMIN)
    )


def new_engagement(search_firm_id, practice_group_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_search_firm_engagement(
            create_engagement_payload(search_firm_id, practice_group_id, **overrides),
            COORDINATOR,
        )
    )


def new_candidate(practice_group_id, engagement_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_candidate(
            create_candidate_payload(practice_group_id, engagement_id, **overrides),
            COORDINATOR,
        )
    )


def append_collection_record(candidate_id, client_book_entry_id=None, **overrides) -> dict:
    return get_success_data(
        api_client.create_collection_record(
            candidate_id,
            create_collection_record_payload(client_book_entry_id, **overrides),
            COORDINATOR,
        )
    )


def read_candidate(candidate_id, headers=None) -> dict:
    return get_success_data(
        api_client.get_candidate(candidate_id, headers or COORDINATOR)
    )


def read_questionnaire(questionnaire_id, headers=None) -> dict:
    return get_success_data(
        api_client.get_questionnaire(questionnaire_id, headers or COORDINATOR)
    )


def read_practice_group(practice_group_id, headers=None) -> dict:
    return get_success_data(
        api_client.get_practice_group(practice_group_id, headers or ADMIN)
    )


def read_offer(offer_id, headers=None) -> dict:
    return get_success_data(api_client.get_offer(offer_id, headers or CHAIR))


def read_client_book_entry(entry_id, headers=None) -> dict:
    return get_success_data(
        api_client.get_client_book_entry(entry_id, headers or COORDINATOR)
    )


def read_assessment(assessment_id, headers=None) -> dict:
    return get_success_data(
        api_client.get_portability_assessment(assessment_id, headers or COORDINATOR)
    )


def read_integration_plan(plan_id, headers=None) -> dict:
    return get_success_data(
        api_client.get_integration_plan(plan_id, headers or COORDINATOR)
    )


def read_conflict_check(check_id, headers=None) -> dict:
    return get_success_data(
        api_client.get_conflict_check(check_id, headers or COUNSEL)
    )


# ----------------------------------------------------------------------
# Tier 1/2: configuration and the candidate spine
# ----------------------------------------------------------------------


def setup_config(pg_overrides=None, sf_overrides=None, eng_overrides=None) -> dict:
    """One OPEN PracticeGroup, one SearchFirm and one ACTIVE engagement."""
    practice_group = new_practice_group(**(pg_overrides or {}))
    search_firm = new_search_firm(**(sf_overrides or {}))
    engagement = new_engagement(
        search_firm["id"], practice_group["id"], **(eng_overrides or {})
    )
    return {
        "practice_group": practice_group,
        "search_firm": search_firm,
        "engagement": engagement,
        "leader_headers": make_practice_group_leader_headers(practice_group["id"]),
    }


def setup_sourced_candidate(
    pg_overrides=None, sf_overrides=None, eng_overrides=None, cand_overrides=None
) -> dict:
    """Configuration plus one Candidate in SOURCED / NOT_STARTED."""
    ctx = setup_config(pg_overrides, sf_overrides, eng_overrides)
    ctx["candidate"] = new_candidate(
        ctx["practice_group"]["id"], ctx["engagement"]["id"], **(cand_overrides or {})
    )
    ctx["candidate_headers"] = make_candidate_headers(ctx["candidate"]["id"])
    return ctx


def setup_approached_candidate(**kwargs) -> dict:
    """Candidate advanced SOURCED -> APPROACHED through the confidential approach."""
    ctx = setup_sourced_candidate(**kwargs)
    ctx["candidate"] = get_success_data(
        api_client.approach_candidate(ctx["candidate"]["id"], COORDINATOR)
    )
    return ctx


def setup_questionnaire_in_draft(lpq_overrides=None, **kwargs) -> dict:
    """Candidate in DILIGENCE with a DRAFT LateralQuestionnaire and an empty book."""
    ctx = setup_approached_candidate(**kwargs)
    ctx["questionnaire"] = get_success_data(
        api_client.create_questionnaire(
            ctx["candidate"]["id"],
            create_questionnaire_payload(**(lpq_overrides or {})),
            COORDINATOR,
        )
    )
    ctx["candidate"] = read_candidate(ctx["candidate"]["id"])
    ctx["entries"] = {}
    ctx["records"] = []
    return ctx


# ----------------------------------------------------------------------
# Tier 3: the disclosed client book
# ----------------------------------------------------------------------


def add_book_entry(ctx, spec, records=(), entry_overrides=None, record_status="VERIFIED"):
    """Disclose one client relationship and append its collection evidence."""
    payload = create_client_book_entry_payload(**dict(spec, **(entry_overrides or {})))
    entry = get_success_data(
        api_client.create_client_book_entry(
            ctx["questionnaire"]["id"], payload, ctx["candidate_headers"]
        )
    )
    ctx["entries"][entry["client_name"]] = entry
    for period_end_date, amount_usd in records:
        ctx["records"].append(
            append_collection_record(
                ctx["candidate"]["id"],
                entry["id"],
                record_type="HISTORICAL",
                period_end_date=period_end_date,
                amount_usd=amount_usd,
                status=record_status,
            )
        )
    return entry


def setup_book(ctx, variant="SLIM"):
    """Disclose the named book variant against the questionnaire already in ctx."""
    for spec, records in BOOK_SPECS[variant]:
        add_book_entry(ctx, spec, records)
    ctx["book_variant"] = variant
    ctx["questionnaire"] = read_questionnaire(ctx["questionnaire"]["id"])
    return ctx


def setup_submitted_questionnaire(variant="SLIM", **kwargs) -> dict:
    """Questionnaire moved DRAFT -> SUBMITTED with the named book disclosed."""
    ctx = setup_questionnaire_in_draft(**kwargs)
    setup_book(ctx, variant)
    ctx["questionnaire"] = get_success_data(
        api_client.submit_questionnaire(
            ctx["questionnaire"]["id"], ctx["candidate_headers"]
        )
    )
    return ctx


def setup_questionnaire_under_review(variant="SLIM", **kwargs) -> dict:
    """Questionnaire moved SUBMITTED -> UNDER_REVIEW; version captured."""
    ctx = setup_submitted_questionnaire(variant, **kwargs)
    ctx["questionnaire"] = get_success_data(
        api_client.start_review_questionnaire(ctx["questionnaire"]["id"], COORDINATOR)
    )
    ctx["questionnaire_version"] = ctx["questionnaire"]["version"]
    return ctx


def setup_assessed_candidate(
    variant="SLIM", assessment_overrides=None, **kwargs
) -> dict:
    """Questionnaire UNDER_REVIEW plus one CURRENT PortabilityAssessment."""
    ctx = setup_questionnaire_under_review(variant, **kwargs)
    ctx["assessment"] = create_assessment(ctx, **(assessment_overrides or {}))
    return ctx


def create_assessment(ctx, **overrides) -> dict:
    """Value the book at the questionnaire's current version."""
    questionnaire = read_questionnaire(ctx["questionnaire"]["id"])
    payload = create_assessment_payload(questionnaire["version"], **overrides)
    assessment = get_success_data(
        api_client.create_portability_assessment(
            questionnaire["id"], payload, COORDINATOR
        )
    )
    ctx["questionnaire"] = read_questionnaire(questionnaire["id"])
    ctx["assessment"] = assessment
    return assessment


# ----------------------------------------------------------------------
# Tier 3: conflicts clearance
# ----------------------------------------------------------------------


def open_conflict_check(ctx, client_name, **overrides) -> dict:
    """Open a ConflictCheck against one disclosed relationship."""
    entry = ctx["entries"][client_name]
    defaults = dict(create_conflict_check_payload())
    defaults["affected_matter_types"] = [entry["matter_types"][0]]
    defaults.update(overrides)
    check = get_success_data(
        api_client.create_conflict_check(entry["id"], defaults, COUNSEL)
    )
    ctx.setdefault("conflict_checks", {})[client_name] = check
    ctx["candidate"] = read_candidate(ctx["candidate"]["id"])
    return check


def clear_conflict_check(ctx, client_name, **overrides) -> dict:
    check = ctx["conflict_checks"][client_name]
    cleared = get_success_data(
        api_client.clear_conflict_check(
            check["id"], clear_conflict_check_payload(**overrides), COUNSEL
        )
    )
    ctx["conflict_checks"][client_name] = cleared
    ctx["candidate"] = read_candidate(ctx["candidate"]["id"])
    return cleared


def setup_cleared_candidate(variant="SLIM", check_overrides=None, **kwargs) -> dict:
    """Assessed candidate whose single conflicts check has been cleared outright,
    so ``clearance_status`` is CLEARED."""
    ctx = setup_assessed_candidate(variant, **kwargs)
    first_client = BOOK_SPECS[variant][0][0]["client_name"]
    open_conflict_check(ctx, first_client, **(check_overrides or {}))
    clear_conflict_check(ctx, first_client)
    return ctx


def block_entry_through_refused_waiver(ctx, client_name, waiver_overrides=None) -> dict:
    """Run the declination cascade on one entry: open an IMPUTED check, pursue a
    waiver, then refuse it."""
    check = open_conflict_check(ctx, client_name, severity="IMPUTED")
    waiver = get_success_data(
        api_client.create_conflict_waiver(
            check["id"], create_conflict_waiver_payload(**(waiver_overrides or {})), COUNSEL
        )
    )
    ctx["waiver"] = waiver
    refused = get_success_data(
        api_client.refuse_conflict_waiver(waiver["id"], refuse_waiver_payload(), COUNSEL)
    )
    ctx["waiver"] = refused
    ctx["conflict_checks"][client_name] = read_conflict_check(check["id"])
    ctx["entries"][client_name] = read_client_book_entry(
        ctx["entries"][client_name]["id"]
    )
    ctx["candidate"] = read_candidate(ctx["candidate"]["id"])
    declinations, _meta = _list_declinations(ctx["entries"][client_name]["id"])
    ctx["declinations"] = declinations
    return ctx


def _list_declinations(entry_id):
    from prd_bench_local_runner.testing import validate_paginated

    return validate_paginated(
        api_client.list_matter_declinations(
            COUNSEL, params={"client_book_entry_id": entry_id, "limit": 100, "offset": 0}
        )
    )


def declinations_for_entry(entry_id):
    """All MatterDeclination rows on one entry, ordered by created_at ascending."""
    declinations, _meta = _list_declinations(entry_id)
    return declinations


# ----------------------------------------------------------------------
# Tier 4: the compensation offer lifecycle
# ----------------------------------------------------------------------


def draft_offer(ctx, chair_headers=None, **overrides) -> dict:
    """Create a CompensationOffer at the candidate's current version."""
    candidate = read_candidate(ctx["candidate"]["id"])
    payload = create_offer_payload(
        ctx["assessment"]["id"], candidate["version"], **overrides
    )
    offer = get_success_data(
        api_client.create_offer(
            candidate["id"], payload, chair_headers or make_committee_chair_headers(CHAIR_USER_ID)
        )
    )
    ctx["offer"] = offer
    ctx["candidate"] = read_candidate(candidate["id"])
    return offer


def setup_drafted_offer(variant="SLIM", offer_overrides=None, **kwargs) -> dict:
    """Cleared candidate with one CompensationOffer in DRAFTED."""
    ctx = setup_cleared_candidate(variant, **kwargs)
    draft_offer(ctx, **(offer_overrides or {}))
    return ctx


def submit_offer(ctx, eligible_voter_count=3, chair_headers=None) -> dict:
    offer = get_success_data(
        api_client.submit_offer(
            ctx["offer"]["id"],
            submit_offer_payload(eligible_voter_count=eligible_voter_count),
            chair_headers or make_committee_chair_headers(CHAIR_USER_ID),
        )
    )
    ctx["offer"] = offer
    ctx["practice_group"] = read_practice_group(ctx["practice_group"]["id"])
    return offer


def setup_offer_in_committee_review(
    variant="SLIM", eligible_voter_count=3, offer_overrides=None, **kwargs
) -> dict:
    """Offer moved DRAFTED -> COMMITTEE_REVIEW with the guarantee reserved."""
    ctx = setup_drafted_offer(variant, offer_overrides, **kwargs)
    submit_offer(ctx, eligible_voter_count=eligible_voter_count)
    return ctx


def cast_vote(ctx, voter_user_id, decision="APPROVE", round_number=None, **overrides):
    payload = cast_vote_payload(
        decision=decision,
        round_number=round_number
        if round_number is not None
        else ctx["offer"]["round_number"],
        **overrides,
    )
    vote = get_success_data(
        api_client.cast_vote(
            ctx["offer"]["id"], payload, make_committee_member_headers(voter_user_id)
        )
    )
    ctx.setdefault("votes", []).append(vote)
    ctx["offer"] = read_offer(ctx["offer"]["id"])
    return vote


def finalize_offer(ctx, chair_headers=None) -> dict:
    """Close the tally. The peer chair finalizes, never the drafting chair."""
    offer = get_success_data(
        api_client.finalize_offer(
            ctx["offer"]["id"],
            chair_headers or make_committee_chair_headers(PEER_CHAIR_USER_ID),
        )
    )
    ctx["offer"] = offer
    ctx["candidate"] = read_candidate(ctx["candidate"]["id"])
    ctx["practice_group"] = read_practice_group(ctx["practice_group"]["id"])
    return offer


def setup_approved_offer(variant="SLIM", offer_overrides=None, **kwargs) -> dict:
    """Two APPROVE ballots on a three-voter roll clear the 60 percent quorum floor
    and the two-thirds approval rule, so finalization approves the offer."""
    ctx = setup_offer_in_committee_review(variant, 3, offer_overrides, **kwargs)
    cast_vote(ctx, MEMBER_1_USER_ID, "APPROVE")
    cast_vote(ctx, MEMBER_2_USER_ID, "APPROVE")
    finalize_offer(ctx)
    return ctx


def setup_hired_candidate(variant="SLIM", offer_overrides=None, **kwargs) -> dict:
    """Candidate accepted the approved offer, so pipeline_status is HIRED."""
    ctx = setup_approved_offer(variant, offer_overrides, **kwargs)
    ctx["offer"] = get_success_data(
        api_client.accept_offer(ctx["offer"]["id"], ctx["candidate_headers"])
    )
    ctx["candidate"] = read_candidate(ctx["candidate"]["id"])
    ctx["practice_group"] = read_practice_group(ctx["practice_group"]["id"])
    ctx["engagement"] = get_success_data(
        api_client.get_search_firm_engagement(ctx["engagement"]["id"], COORDINATOR)
    )
    return ctx


# ----------------------------------------------------------------------
# Tier 5: integration, cross-selling and performance
# ----------------------------------------------------------------------


def draft_plan(ctx, leader_headers=None, **overrides) -> dict:
    """Draft the IntegrationPlan for the hired candidate, acting as the leader of
    the receiving practice group."""
    payload = create_integration_plan_payload(
        ctx["practice_group"]["id"], ctx["offer"]["id"], **overrides
    )
    plan = get_success_data(
        api_client.create_integration_plan(
            ctx["candidate"]["id"],
            payload,
            leader_headers or ctx["leader_headers"],
        )
    )
    ctx["plan"] = plan
    return plan


def setup_plan_in_draft(variant="SLIM", plan_overrides=None, **kwargs) -> dict:
    """Hired candidate with one IntegrationPlan in DRAFT."""
    ctx = setup_hired_candidate(variant, **kwargs)
    draft_plan(ctx, **(plan_overrides or {}))
    return ctx


def activate_plan(ctx, leader_headers=None) -> dict:
    plan = get_success_data(
        api_client.activate_integration_plan(
            ctx["plan"]["id"], leader_headers or ctx["leader_headers"]
        )
    )
    ctx["plan"] = plan
    ctx["practice_group"] = read_practice_group(ctx["practice_group"]["id"])
    return plan


def setup_active_plan(variant="SLIM", plan_overrides=None, **kwargs) -> dict:
    """IntegrationPlan moved DRAFT -> ACTIVE, consuming one onboarding slot."""
    ctx = setup_plan_in_draft(variant, plan_overrides, **kwargs)
    activate_plan(ctx)
    return ctx


def add_introduction(ctx, leader_headers=None, **overrides) -> dict:
    introduction = get_success_data(
        api_client.create_introduction(
            ctx["plan"]["id"],
            create_introduction_payload(**overrides),
            leader_headers or ctx["leader_headers"],
        )
    )
    ctx.setdefault("introductions", []).append(introduction)
    ctx["introduction"] = introduction
    ctx["plan"] = read_integration_plan(ctx["plan"]["id"])
    return introduction


def complete_introduction(ctx, introduction=None, leader_headers=None) -> dict:
    target = introduction or ctx["introduction"]
    completed = get_success_data(
        api_client.complete_introduction(
            target["id"], leader_headers or ctx["leader_headers"]
        )
    )
    ctx["introduction"] = completed
    ctx["plan"] = read_integration_plan(ctx["plan"]["id"])
    return completed


def setup_plan_with_introduction(variant="SLIM", intro_overrides=None, **kwargs) -> dict:
    """ACTIVE plan carrying one PROPOSED cross-selling introduction."""
    ctx = setup_active_plan(variant, **kwargs)
    add_introduction(ctx, **(intro_overrides or {}))
    return ctx


def add_performance_review(ctx, leader_headers=None, **overrides) -> dict:
    review = get_success_data(
        api_client.create_performance_review(
            ctx["candidate"]["id"],
            create_performance_review_payload(ctx["plan"]["id"], **overrides),
            leader_headers or ctx["leader_headers"],
        )
    )
    ctx.setdefault("reviews", []).append(review)
    ctx["review"] = review
    return review


# ----------------------------------------------------------------------
# Multi-aggregate helpers
# ----------------------------------------------------------------------


def add_second_practice_group(ctx, **overrides) -> dict:
    """A second, independently owned PracticeGroup for foreign-ownership probes."""
    payload_overrides = dict(
        {"name": DEFAULTS["SECOND_PRACTICE_GROUP_NAME"]}, **overrides
    )
    group = new_practice_group(**payload_overrides)
    ctx["second_practice_group"] = group
    ctx["foreign_leader_headers"] = make_practice_group_leader_headers(group["id"])
    return group


def add_second_candidate(ctx, cand_overrides=None) -> dict:
    """A second Candidate on the same engagement, for cross-aggregate probes."""
    overrides = dict(
        {"full_name": DEFAULTS["SECOND_CANDIDATE_FULL_NAME"]}, **(cand_overrides or {})
    )
    candidate = new_candidate(
        ctx["practice_group"]["id"], ctx["engagement"]["id"], **overrides
    )
    ctx["second_candidate"] = candidate
    ctx["second_candidate_headers"] = make_candidate_headers(candidate["id"])
    return candidate


def setup_second_assessed_candidate(ctx, variant="SLIM") -> dict:
    """Take a second candidate on the same engagement all the way to one CURRENT
    assessment, and return its own scenario dictionary."""
    other = {
        "practice_group": ctx["practice_group"],
        "search_firm": ctx["search_firm"],
        "engagement": ctx["engagement"],
        "leader_headers": ctx["leader_headers"],
    }
    other["candidate"] = add_second_candidate(ctx)
    other["candidate_headers"] = make_candidate_headers(other["candidate"]["id"])
    other["candidate"] = get_success_data(
        api_client.approach_candidate(other["candidate"]["id"], COORDINATOR)
    )
    other["questionnaire"] = get_success_data(
        api_client.create_questionnaire(
            other["candidate"]["id"], create_questionnaire_payload(), COORDINATOR
        )
    )
    other["entries"] = {}
    other["records"] = []
    setup_book(other, variant)
    other["questionnaire"] = get_success_data(
        api_client.submit_questionnaire(
            other["questionnaire"]["id"], other["candidate_headers"]
        )
    )
    other["questionnaire"] = get_success_data(
        api_client.start_review_questionnaire(other["questionnaire"]["id"], COORDINATOR)
    )
    create_assessment(other)
    ctx["second_scenario"] = other
    return other


def all_member_headers():
    """The five distinct CommitteeMember voters used by the vote-roll fixtures."""
    return [
        make_committee_member_headers(MEMBER_1_USER_ID),
        make_committee_member_headers(MEMBER_2_USER_ID),
        make_committee_member_headers(MEMBER_3_USER_ID),
    ]
