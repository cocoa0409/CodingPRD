"""Request validation, structural ceilings and the pinned order of evaluation.

Each test assembles its own world from the endpoints the PRD publishes: the
service starts every test from an empty database with the logical clock reading
2026-08-01T00:00:00Z, so nothing here relies on state left by a neighbour.
"""
from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import api_client, factories as f, fixtures
from test_helpers.test_users import TEST_USERS

UW = TEST_USERS["underwriter_headers"]
UM = TEST_USERS["manager_headers"]
RE = TEST_USERS["risk_engineer_headers"]
CA = TEST_USERS["claim_adjuster_headers"]
CA2 = TEST_USERS["claim_adjuster_2_headers"]

# A small FIRE_RESISTIVE / INLAND new-construction account. Its submission score
# is 6 points (6 for the construction class, nothing else), so it screens
# ELIGIBLE on grade A and rates straight to QUOTED.
CEDAR_PROJECT = {
    "name": "Cedar Mills Warehouse",
    "site_address": "12 Mill Rd, Cedar",
    "construction_type": "FIRE_RESISTIVE",
    "project_kind": "NEW_CONSTRUCTION",
    "hard_cost_value_cents": 400000000,
    "cat_zone": "INLAND",
    "planned_start_date": "2026-09-01T00:00:00Z",
    "projected_completion_date": "2027-03-01T00:00:00Z",
}

# term 2026-09-01 .. 2027-03-20 is 200 whole days; 4000 rated units at 80 cents
# per $1,000 gives a base premium of 320000 cents with no loads and no credit.
CEDAR_POLICY = {
    "term_start_date": "2026-09-01T00:00:00Z",
    "term_end_date": "2027-03-20T00:00:00Z",
    "includes_existing_structure": False,
    "deductible_tier": "STANDARD_25K",
    "limit_cents": 200000000,
    "daily_delay_rate_cents": 0,
}

MATERIALS_ONLY = (("MATERIALS_ON_SITE", 100000000),)


def cedar_project_overrides(**overrides) -> dict:
    payload = dict(CEDAR_PROJECT, engineering_grade="A")
    payload.update(overrides)
    return payload


def cedar_draft(parts, with_owner=False, project_overrides=None,
                **policy_overrides) -> fixtures.Account:
    options = dict(CEDAR_POLICY)
    options.update(policy_overrides)
    return fixtures.draft_account(
        parts=parts, with_owner=with_owner,
        project_overrides=project_overrides or cedar_project_overrides(),
        **options)


def cedar_in_force(parts, project_overrides=None, **policy_overrides) -> fixtures.Account:
    options = dict(CEDAR_POLICY)
    options.update(policy_overrides)
    return fixtures.in_force_account(
        parts=parts,
        project_overrides=project_overrides or cedar_project_overrides(),
        **options)


def total_count(response) -> int:
    _rows, meta = validate_paginated(response)
    return meta["total_count"]


def create_policy_on(project, **overrides):
    """POST a policy against a project, defaulting to the Cedar Mills terms."""
    options = dict(CEDAR_POLICY)
    options.update(overrides)
    payload = f.create_policy_payload(
        project["id"], project["version"], **options)
    return api_client.create_policy(payload, UW)


def test_duplicate_site_code_is_rejected_on_the_second_register():
    """A facility site_code is unique across every facility on the books, and a
    registration reusing an existing code is refused with ERR_DUPLICATE_SITE_CODE
    (PRD 3.5).

    Design: Corner/validations/corner_duplicate_facility_site_code_is_rejected_on_the_second_register
    """
    first = fixtures.register_facility(
        name="Northside Warehouse", site_code="WH-01",
        distance_from_site_miles=12, aggregate_capacity_cents=500000000,
        protection_class="SPRINKLERED")

    collision = api_client.create_facility(
        f.create_facility_payload(
            name="Southside Yard", site_code="WH-01",
            distance_from_site_miles=40, aggregate_capacity_cents=100000000,
            protection_class="NON_SPRINKLERED"),
        RE)
    validate_error(collision, "ERR_DUPLICATE_SITE_CODE", expected_status=409)

    assert total_count(api_client.list_facilities(RE)) == 1

    incumbent = validate_success(api_client.get_facility(first["id"], RE))
    assert incumbent["name"] == "Northside Warehouse"
    assert incumbent["aggregate_capacity_cents"] == 500000000
    assert incumbent["version"] == 1


def test_a_distinct_site_code_registers_with_active_defaults():
    """A newly registered facility is ACTIVE with committed_value_cents at 0, and
    only a reused site_code collides (PRD 3.5).

    Design: Corner/validations/corner_a_distinct_site_code_registers_with_active_defaults
    """
    first = fixtures.register_facility(
        name="Northside Warehouse", site_code="WH-01",
        distance_from_site_miles=12, aggregate_capacity_cents=500000000,
        protection_class="SPRINKLERED")

    second = validate_success(
        api_client.create_facility(
            f.create_facility_payload(
                name="Northside Warehouse Annex", site_code="WH-02",
                distance_from_site_miles=12, aggregate_capacity_cents=500000000,
                protection_class="SPRINKLERED"),
            RE),
        expected_status=201)

    assert second["id"] and second["id"] != first["id"]
    assert second["status"] == "ACTIVE"
    assert second["committed_value_cents"] == 0

    rows, meta = validate_paginated(api_client.list_facilities(RE))
    assert meta["total_count"] == 2
    assert sorted(row["site_code"] for row in rows) == ["WH-01", "WH-02"]


def test_term_end_equal_to_or_before_term_start_is_invalid():
    """A policy's term_end_date must be strictly later than its term_start_date,
    and a breach of that date pair is refused with ERR_DATE_RANGE_INVALID
    (PRD 2.11 and 3.2).

    Design: Corner/validations/corner_term_end_before_and_equal_to_term_start_are_both_invalid
    """
    project = fixtures.eligible_project(**cedar_project_overrides())

    equal_end = create_policy_on(project, term_end_date="2026-09-01T00:00:00Z")
    validate_error(equal_end, "ERR_DATE_RANGE_INVALID", expected_status=422)

    earlier_end = create_policy_on(project, term_end_date="2026-08-31T00:00:00Z")
    validate_error(earlier_end, "ERR_DATE_RANGE_INVALID", expected_status=422)

    one_day = validate_success(
        create_policy_on(project, term_end_date="2026-09-02T00:00:00Z"),
        expected_status=201)
    assert one_day["original_term_days"] == 1

    assert total_count(api_client.list_policies(
        UW, params={"project_id": project["id"]})) == 1


def test_sublimit_sum_may_equal_the_limit_but_not_pass_it():
    """The sum of sublimit_cents over a policy's ACTIVE coverage parts, counting
    the row being created or the new value being patched, must not exceed
    limit_cents; a breach is ERR_SUBLIMIT_EXCEEDS_LIMIT (PRD 3.2).

    Design: Corner/validations/corner_sublimit_sum_may_equal_the_limit_but_not_pass_it_by_one_cent
    """
    account = cedar_draft(
        parts=(("MATERIALS_ON_SITE", 150000000), ("IN_TRANSIT", 50000000)))
    in_transit = account.part("IN_TRANSIT")
    baseline_version = in_transit["version"]

    # The two scheduled parts already total exactly limit_cents (200000000).
    over_by_one_cent = api_client.create_coverage_part(
        f.create_coverage_part_payload(
            account.policy_id, part_type="WATER_DAMAGE", sublimit_cents=1),
        UW)
    validate_error(over_by_one_cent, "ERR_SUBLIMIT_EXCEEDS_LIMIT",
                   expected_status=422)

    patch_over = api_client.patch_coverage_part(
        in_transit["id"], {"sublimit_cents": 50000001}, UW)
    validate_error(patch_over, "ERR_SUBLIMIT_EXCEEDS_LIMIT", expected_status=422)

    untouched = validate_success(
        api_client.get_coverage_part(in_transit["id"], UW))
    assert untouched["sublimit_cents"] == 50000000
    assert untouched["version"] == baseline_version

    patched = validate_success(api_client.patch_coverage_part(
        in_transit["id"], {"sublimit_cents": 49999999}, UW))
    assert patched["sublimit_cents"] == 49999999
    assert patched["available_cents"] == 49999999
    assert patched["version"] == baseline_version + 1

    # The freed cent is immediately reusable.
    validate_success(
        api_client.create_coverage_part(
            f.create_coverage_part_payload(
                account.policy_id, part_type="WATER_DAMAGE", sublimit_cents=1),
            UW),
        expected_status=201)

    rows, meta = validate_paginated(api_client.list_policy_coverage_parts(
        account.policy_id, UW, params={"limit": 100}))
    assert meta["total_count"] == 3
    assert sorted(row["sublimit_cents"] for row in rows) == [1, 49999999, 150000000]


def test_duplicate_part_type_is_rejected_even_when_the_sum_still_fits():
    """Each part_type may appear at most once per policy in any status, so a
    second part of the same type is refused with ERR_DUPLICATE_COVERAGE_PART
    (PRD 3.2).

    Design: Corner/validations/corner_duplicate_part_type_is_rejected_even_when_the_sum_still_fits
    """
    account = cedar_draft(parts=(("MATERIALS_ON_SITE", 1),))
    version_before = account.policy["version"]

    duplicate = api_client.create_coverage_part(
        f.create_coverage_part_payload(
            account.policy_id, part_type="MATERIALS_ON_SITE", sublimit_cents=1),
        UW)
    validate_error(duplicate, "ERR_DUPLICATE_COVERAGE_PART", expected_status=409)

    # The same one-cent sublimit under a different bucket is admissible.
    validate_success(
        api_client.create_coverage_part(
            f.create_coverage_part_payload(
                account.policy_id, part_type="IN_TRANSIT", sublimit_cents=1),
            UW),
        expected_status=201)

    assert total_count(api_client.list_policy_coverage_parts(
        account.policy_id, UW)) == 2

    policy = validate_success(api_client.get_policy(account.policy_id, UW))
    assert policy["version"] == version_before + 1


def test_interest_schedule_caps_the_pct_sum_and_the_payee_priority():
    """The sum of insurable_interest_pct across a policy's interests, counting the
    row being added, must not exceed 100 (ERR_INTEREST_PCT_EXCEEDED), and
    loss_payee_priority must be unique within the policy wherever present
    (ERR_DUPLICATE_PAYEE_PRIORITY) — PRD 3.3.

    Design: Corner/validations/corner_interest_schedule_caps_the_pct_sum_and_the_payee_priority
    """
    account = cedar_draft(parts=())
    fixtures.add_interest(
        account, party_role="OWNER", insurable_interest_pct=60,
        party_name="Cedar Mills Owner LLC", loss_payee_priority=1)
    fixtures.add_interest(
        account, party_role="GENERAL_CONTRACTOR", insurable_interest_pct=40,
        party_name="Ridgeline Construction", loss_payee_priority=2)

    # The schedule already sums to exactly 100, so one more point is too many.
    over_pct = api_client.create_named_insured_interest(
        f.create_interest_payload(
            account.policy_id, party_role="SUBCONTRACTOR",
            insurable_interest_pct=1, party_name="Peninsula Glazing",
            loss_payee_priority=3),
        UW)
    validate_error(over_pct, "ERR_INTEREST_PCT_EXCEEDED", expected_status=422)

    # A zero-percent lender still competes for the payee ordering.
    reused_priority = api_client.create_named_insured_interest(
        f.create_interest_payload(
            account.policy_id, party_role="LENDER", insurable_interest_pct=0,
            party_name="Harbor Trust Bank", loss_payee_priority=2),
        UW)
    validate_error(reused_priority, "ERR_DUPLICATE_PAYEE_PRIORITY",
                   expected_status=409)

    lender = validate_success(
        api_client.create_named_insured_interest(
            f.create_interest_payload(
                account.policy_id, party_role="LENDER", insurable_interest_pct=0,
                party_name="Harbor Trust Bank", loss_payee_priority=3),
            UW),
        expected_status=201)
    assert lender["acknowledgment_status"] == "PENDING"
    assert lender["insurable_interest_pct"] == 0

    rows, meta = validate_paginated(api_client.list_policy_named_insured_interests(
        account.policy_id, UW, params={"limit": 100}))
    assert meta["total_count"] == 3
    assert sorted(row["loss_payee_priority"] for row in rows) == [1, 2, 3]


def test_existing_structure_election_requires_a_renovation_carrying_value():
    """includes_existing_structure may only be true when the project is a
    RENOVATION whose existing_structure_value_cents is strictly greater than
    zero; otherwise the create is refused with
    ERR_EXISTING_STRUCTURE_NOT_APPLICABLE (PRD 3.2).

    Design: Corner/validations/corner_existing_structure_election_requires_a_renovation_carrying_value
    """
    new_build = fixtures.eligible_project(
        engineering_grade="A", name="Newbuild Alpha", site_address="1 Alpha Rd",
        construction_type="FIRE_RESISTIVE", project_kind="NEW_CONSTRUCTION",
        hard_cost_value_cents=400000000, cat_zone="INLAND",
        planned_start_date="2026-09-01T00:00:00Z",
        projected_completion_date="2027-03-01T00:00:00Z")
    # The field is omitted here, so it defaults to 0.
    bare_renovation = fixtures.eligible_project(
        engineering_grade="A", name="Reno Beta", site_address="2 Beta Rd",
        construction_type="FIRE_RESISTIVE", project_kind="RENOVATION",
        hard_cost_value_cents=400000000, cat_zone="INLAND",
        planned_start_date="2026-09-01T00:00:00Z",
        projected_completion_date="2027-03-01T00:00:00Z")
    standing_renovation = fixtures.eligible_project(
        engineering_grade="A", name="Reno Gamma", site_address="3 Gamma Rd",
        construction_type="FIRE_RESISTIVE", project_kind="RENOVATION",
        hard_cost_value_cents=400000000, existing_structure_value_cents=500000000,
        cat_zone="INLAND", planned_start_date="2026-09-01T00:00:00Z",
        projected_completion_date="2027-03-01T00:00:00Z")

    on_new_build = create_policy_on(
        new_build, includes_existing_structure=True, limit_cents=900000000)
    validate_error(on_new_build, "ERR_EXISTING_STRUCTURE_NOT_APPLICABLE",
                   expected_status=422)

    on_bare_renovation = create_policy_on(
        bare_renovation, includes_existing_structure=True, limit_cents=900000000)
    validate_error(on_bare_renovation, "ERR_EXISTING_STRUCTURE_NOT_APPLICABLE",
                   expected_status=422)

    policy = validate_success(
        create_policy_on(standing_renovation, includes_existing_structure=True,
                         limit_cents=900000000),
        expected_status=201)
    assert policy["insured_tiv_cents"] == 900000000

    assert total_count(api_client.list_project_policies(
        new_build["id"], UW)) == 0
    assert total_count(api_client.list_project_policies(
        bare_renovation["id"], UW)) == 0

    reread = validate_success(
        api_client.get_project(bare_renovation["id"], UW))
    assert reread["existing_structure_value_cents"] == 0


def test_coverage_part_permission_depends_on_the_policy_configuration():
    """An EXISTING_STRUCTURE part may only be scheduled when the policy's
    includes_existing_structure is true, and a DELAY_IN_COMPLETION part only when
    daily_delay_rate_cents is strictly greater than zero; either violation is
    ERR_COVERAGE_PART_NOT_PERMITTED (PRD 3.2).

    Design: Corner/validations/corner_coverage_part_permission_depends_on_the_policy_configuration
    """
    project = fixtures.eligible_project(
        engineering_grade="A", name="Millworks Renovation",
        site_address="9 Loom St, Cedar", construction_type="FIRE_RESISTIVE",
        project_kind="RENOVATION", hard_cost_value_cents=400000000,
        existing_structure_value_cents=500000000, cat_zone="INLAND",
        planned_start_date="2026-09-01T00:00:00Z",
        projected_completion_date="2027-03-01T00:00:00Z")

    # First policy: no existing-structure election and no delay rate at all.
    plain = validate_success(
        create_policy_on(project, limit_cents=900000000,
                         includes_existing_structure=False,
                         daily_delay_rate_cents=0),
        expected_status=201)

    no_election = api_client.create_coverage_part(
        f.create_coverage_part_payload(
            plain["id"], part_type="EXISTING_STRUCTURE",
            sublimit_cents=100000000),
        UW)
    validate_error(no_election, "ERR_COVERAGE_PART_NOT_PERMITTED",
                   expected_status=422)

    no_delay_rate = api_client.create_coverage_part(
        f.create_coverage_part_payload(
            plain["id"], part_type="DELAY_IN_COMPLETION",
            sublimit_cents=100000000),
        UW)
    validate_error(no_delay_rate, "ERR_COVERAGE_PART_NOT_PERMITTED",
                   expected_status=422)

    # An unconditional bucket is untouched by either gate.
    validate_success(
        api_client.create_coverage_part(
            f.create_coverage_part_payload(
                plain["id"], part_type="MATERIALS_ON_SITE",
                sublimit_cents=100000000),
            UW),
        expected_status=201)

    # Second policy: both terms bought, so both buckets open up.
    refreshed = validate_success(api_client.get_project(project["id"], UW))
    configured = validate_success(
        create_policy_on(refreshed, limit_cents=900000000,
                         includes_existing_structure=True,
                         daily_delay_rate_cents=1200000),
        expected_status=201)

    for part_type in ("EXISTING_STRUCTURE", "DELAY_IN_COMPLETION"):
        part = validate_success(
            api_client.create_coverage_part(
                f.create_coverage_part_payload(
                    configured["id"], part_type=part_type,
                    sublimit_cents=100000000),
                UW),
            expected_status=201)
        assert part["status"] == "ACTIVE"
        assert part["available_cents"] == 100000000

    assert total_count(api_client.list_policy_coverage_parts(
        plain["id"], UW)) == 1
    assert total_count(api_client.list_policy_coverage_parts(
        configured["id"], UW)) == 2


def test_bind_requires_every_interest_acknowledged_and_a_schedule_of_one_hundred():
    """A bind demands that every NamedInsuredInterest be ACKNOWLEDGED and that the
    OWNER plus GENERAL_CONTRACTOR percentages total exactly 100; an
    unacknowledged payee and a schedule short of 100 both answer
    ERR_INTERESTS_NOT_ACKNOWLEDGED (PRD 3.2).

    Design: Corner/validations/corner_bind_requires_every_interest_acknowledged_and_a_schedule_of_exactly_one_hundred
    """
    pending_payee = cedar_draft(
        parts=MATERIALS_ONLY,
        project_overrides=cedar_project_overrides(
            name="Cedar Mills A", site_address="12 Mill Rd, Cedar"))
    owner = fixtures.add_interest(
        pending_payee, party_role="OWNER", insurable_interest_pct=60,
        party_name="Cedar Mills Owner LLC")
    fixtures.acknowledge_interest(pending_payee, owner)
    contractor = fixtures.add_interest(
        pending_payee, party_role="GENERAL_CONTRACTOR",
        insurable_interest_pct=40, party_name="Ridgeline Construction")
    fixtures.acknowledge_interest(pending_payee, contractor)
    # The lender never acknowledges, and it alone holds the bind back.
    lender = fixtures.add_interest(
        pending_payee, party_role="LENDER", insurable_interest_pct=0,
        party_name="Harbor Trust Bank")
    assert lender["acknowledgment_status"] == "PENDING"
    fixtures.quote_account(pending_payee)
    assert pending_payee.policy["status"] == "QUOTED"
    assert pending_payee.policy["quoted_premium_cents"] == 320000

    short_schedule = cedar_draft(
        parts=MATERIALS_ONLY,
        project_overrides=cedar_project_overrides(
            name="Cedar Mills B", site_address="14 Mill Rd, Cedar"))
    short_owner = fixtures.add_interest(
        short_schedule, party_role="OWNER", insurable_interest_pct=60,
        party_name="Cedar Mills Owner LLC")
    fixtures.acknowledge_interest(short_schedule, short_owner)
    short_gc = fixtures.add_interest(
        short_schedule, party_role="GENERAL_CONTRACTOR",
        insurable_interest_pct=30, party_name="Ridgeline Construction")
    fixtures.acknowledge_interest(short_schedule, short_gc)
    fixtures.quote_account(short_schedule)

    validate_error(api_client.bind_policy(pending_payee.policy_id, UW),
                   "ERR_INTERESTS_NOT_ACKNOWLEDGED", expected_status=409)
    validate_error(api_client.bind_policy(short_schedule.policy_id, UW),
                   "ERR_INTERESTS_NOT_ACKNOWLEDGED", expected_status=409)

    for account in (pending_payee, short_schedule):
        policy = validate_success(api_client.get_policy(account.policy_id, UW))
        assert policy["status"] == "QUOTED"
        assert policy["written_premium_cents"] == 0
        assert policy["bound_at"] is None
    assert total_count(api_client.list_policy_premium_transactions(
        pending_payee.policy_id, UW)) == 0

    fixtures.acknowledge_interest(pending_payee, lender)
    bound = validate_success(
        api_client.bind_policy(pending_payee.policy_id, UW))
    assert bound["status"] == "BOUND"
    assert bound["written_premium_cents"] == 320000

    ledger, meta = validate_paginated(api_client.list_policy_premium_transactions(
        pending_payee.policy_id, UW, params={"limit": 100}))
    assert meta["total_count"] == 1
    assert ledger[0]["sequence_no"] == 1
    assert ledger[0]["txn_type"] == "INITIAL"
    assert ledger[0]["amount_cents"] == 320000


def test_a_second_bind_on_the_same_project_is_rejected_while_the_first_is_live():
    """A project may carry only one live policy: with another policy of the same
    project already BOUND or IN_FORCE, the bind is refused with
    ERR_ACTIVE_POLICY_EXISTS, and a fresh draft only supersedes a draft (PRD 3.2).

    Design: Corner/validations/corner_a_second_bind_on_the_same_project_is_rejected_while_the_first_is_live
    """
    first = cedar_draft(parts=MATERIALS_ONLY, with_owner=True)
    fixtures.quote_account(first)
    fixtures.bind_account(first)
    assert first.policy["status"] == "BOUND"
    assert first.policy["written_premium_cents"] == 320000

    # The first policy has left DRAFT, so this second draft supersedes nothing.
    refreshed = validate_success(api_client.get_project(first.project_id, UW))
    second = fixtures.draft_account(
        project=refreshed, parts=MATERIALS_ONLY, with_owner=True,
        **dict(CEDAR_POLICY, deductible_tier="HIGH_250K"))
    fixtures.quote_account(second)
    # The eleven percent high-deductible credit takes 320000 down to 284800.
    assert second.policy["quoted_premium_cents"] == 284800

    validate_error(api_client.bind_policy(second.policy_id, UW),
                   "ERR_ACTIVE_POLICY_EXISTS", expected_status=409)

    stalled = validate_success(api_client.get_policy(second.policy_id, UW))
    assert stalled["status"] == "QUOTED"
    assert stalled["written_premium_cents"] == 0
    assert stalled["bound_at"] is None

    incumbent = validate_success(api_client.get_policy(first.policy_id, UW))
    assert incumbent["status"] == "BOUND"

    rows, meta = validate_paginated(api_client.list_project_policies(
        first.project_id, UW, params={"limit": 100}))
    assert meta["total_count"] == 2
    assert sorted(row["status"] for row in rows) == ["BOUND", "QUOTED"]


def test_cancel_date_must_sit_inside_the_term_and_never_behind_the_clock():
    """A cancellation's effective date must be strictly later than
    term_start_date, at or before term_end_date, and at or after the logical
    clock; a back-dated or out-of-term date is ERR_CANCEL_DATE_INVALID (PRD 3.9).

    Design: Corner/validations/corner_cancel_date_must_sit_inside_the_term_and_never_behind_the_clock
    """
    account = cedar_in_force(parts=MATERIALS_ONLY)
    sweep = fixtures.set_clock("2026-10-01T00:00:00Z")
    assert sweep["expired_policy_count"] == 0

    for bad_date in ("2026-09-15T00:00:00Z", "2026-09-01T00:00:00Z",
                     "2027-03-21T00:00:00Z"):
        refused = api_client.cancel_policy(
            account.policy_id,
            f.cancel_policy_payload("INSURED_REQUEST", bad_date), UM)
        validate_error(refused, "ERR_CANCEL_DATE_INVALID", expected_status=422)

    still_live = validate_success(api_client.get_policy(account.policy_id, UW))
    assert still_live["status"] == "IN_FORCE"
    assert still_live["cancel_effective_date"] is None

    # The last admissible date is term_end_date itself: nothing is unearned.
    cancelled = validate_success(api_client.cancel_policy(
        account.policy_id,
        f.cancel_policy_payload("INSURED_REQUEST", "2027-03-20T00:00:00Z"), UM))
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["return_premium_cents"] == 0
    assert cancelled["written_premium_cents"] == 320000

    ledger, meta = validate_paginated(api_client.list_policy_premium_transactions(
        account.policy_id, UW, params={"limit": 100}))
    assert meta["total_count"] == 2
    assert [txn["txn_type"] for txn in ledger] == ["INITIAL", "RETURN_PREMIUM"]
    assert ledger[1]["amount_cents"] == 0
    assert ledger[1]["effective_date"] is not None

    summary = fixtures.premium_summary(account)
    assert summary["ledger_sum_cents"] == 320000
    assert summary["balanced"] is True

    part = validate_success(api_client.get_coverage_part(
        account.part("MATERIALS_ON_SITE")["id"], UW))
    assert part["status"] == "CLOSED"

    project = validate_success(api_client.get_project(account.project_id, UW))
    assert project["in_force_policy_count"] == 0


def test_revised_completion_date_must_reconcile_with_the_requested_days():
    """revised_completion_date must equal the policy's current
    adjusted_completion_date advanced by exactly requested_extension_days; a date
    that does not reconcile is ERR_REVISED_DATE_MISMATCH (PRD 3.6).

    Design: Corner/validations/corner_revised_completion_date_must_reconcile_with_the_requested_days
    """
    account = cedar_in_force(parts=MATERIALS_ONLY)
    policy_version = account.policy["version"]
    assert account.policy["adjusted_completion_date"] == "2027-03-01T00:00:00Z"

    # Twenty days off 2027-03-01 is 2027-03-21 and nothing else.
    for wrong_date in ("2027-03-22T00:00:00Z", "2027-03-20T00:00:00Z"):
        refused = api_client.create_extension_endorsement(
            f.create_endorsement_payload(
                account.policy_id, policy_version, 20, wrong_date), UW)
        validate_error(refused, "ERR_REVISED_DATE_MISMATCH", expected_status=422)

    endorsement = validate_success(
        api_client.create_extension_endorsement(
            f.create_endorsement_payload(
                account.policy_id, policy_version, 20, "2027-03-21T00:00:00Z"),
            UW),
        expected_status=201)
    assert endorsement["status"] == "REQUESTED"
    assert endorsement["requested_extension_days"] == 20
    # 20/200 is a tenth of the term, so the slip prices at factor 1.00 on a
    # daily base of 1600 cents: 32000 cents of additional premium.
    assert endorsement["slip_factor"] == 1.00
    assert endorsement["additional_premium_cents"] == 32000

    assert total_count(api_client.list_policy_extension_endorsements(
        account.policy_id, UW)) == 1

    policy = validate_success(api_client.get_policy(account.policy_id, UW))
    assert policy["version"] == policy_version + 1
    # Filing prices the slip; only an approval moves the term.
    assert policy["term_end_date"] == "2027-03-20T00:00:00Z"
    assert policy["cumulative_extension_days"] == 0


def test_cumulative_extension_ratio_admits_exactly_half_the_original_term():
    """cumulative_extension_days plus the requested days, divided by
    original_term_days, must not exceed one half; beyond that the request is
    refused with ERR_EXTENSION_LIMIT_EXCEEDED (PRD 3.6).

    Design: Corner/validations/corner_cumulative_extension_ratio_admits_exactly_half_the_original_term
    """
    account = cedar_in_force(parts=MATERIALS_ONLY)
    policy_version = account.policy["version"]
    assert account.policy["original_term_days"] == 200

    # 101/200 is 0.505, a whisker past the ceiling.
    over_ceiling = api_client.create_extension_endorsement(
        f.create_endorsement_payload(
            account.policy_id, policy_version, 101, "2027-06-10T00:00:00Z"),
        UW)
    validate_error(over_ceiling, "ERR_EXTENSION_LIMIT_EXCEEDED",
                   expected_status=422)

    # 100/200 is exactly one half, which the ceiling admits.
    endorsement = validate_success(
        api_client.create_extension_endorsement(
            f.create_endorsement_payload(
                account.policy_id, policy_version, 100, "2027-06-09T00:00:00Z"),
            UW),
        expected_status=201)
    assert endorsement["status"] == "REQUESTED"
    # A ratio past a quarter prices at 1.40: 1600 * 100 * 1.40.
    assert endorsement["slip_factor"] == 1.40
    assert endorsement["additional_premium_cents"] == 224000

    assert total_count(api_client.list_policy_extension_endorsements(
        account.policy_id, UW)) == 1

    policy = validate_success(api_client.get_policy(account.policy_id, UW))
    assert policy["cumulative_extension_days"] == 0


def test_delay_adjustment_requires_a_completed_project():
    """A DELAY peril requires the project to have declared its
    actual_substantial_completion_date as well as an ACTIVE DELAY_IN_COMPLETION
    part; the missing declaration is ERR_PROJECT_NOT_COMPLETE (PRD 3.7).

    Design: Corner/validations/corner_delay_adjustment_requires_a_completed_project
    """
    account = cedar_in_force(
        parts=(("MATERIALS_ON_SITE", 100000000),
               ("DELAY_IN_COMPLETION", 20000000)),
        daily_delay_rate_cents=1200000)
    # The delay sublimit adds a 12000 soft-cost component to the 320000 base.
    assert account.policy["written_premium_cents"] == 332000

    fixtures.set_clock("2027-03-15T00:00:00Z")
    claim = fixtures.report_claim(
        account, peril="DELAY", loss_date="2027-03-15T00:00:00Z",
        description="Substantial completion overran the scheduled date")

    too_early = api_client.adjust_claim(
        claim["id"], f.adjust_claim_payload(
            outcome="ADJUST", adjustment_basis="ACTUAL_LOSS"), CA)
    validate_error(too_early, "ERR_PROJECT_NOT_COMPLETE", expected_status=422)

    unvalued = validate_success(api_client.get_claim(claim["id"], CA))
    assert unvalued["adjustment_status"] == "REPORTED"
    assert unvalued["indemnity_cents"] == 0

    project = fixtures.declare_substantial_completion(
        account, "2027-03-15T00:00:00Z")
    assert project["status"] == "SUBSTANTIALLY_COMPLETE"
    assert project["actual_substantial_completion_date"] == "2027-03-15T00:00:00Z"

    # 14 raw days of slip less the 5 waiting days leaves 9 indemnified days.
    adjusted = validate_success(api_client.adjust_claim(
        claim["id"], f.adjust_claim_payload(
            outcome="ADJUST", adjustment_basis="ACTUAL_LOSS"), CA))
    assert adjusted["adjustment_status"] == "ADJUSTED"
    assert adjusted["delay_days_indemnified"] == 9
    assert adjusted["indemnity_cents"] == 10800000
    # The money deductible never bites a delay line and the sublimit is ample.
    assert adjusted["uncovered_cents"] == 0

    lines = adjusted["allocation_lines"]
    assert len(lines) == 1
    assert lines[0]["part_type"] == "DELAY_IN_COMPLETION"
    assert lines[0]["gross_loss_cents"] == 10800000
    assert lines[0]["deductible_applied_cents"] == 0


def test_storage_loss_requires_an_assignment_covering_the_loss_date():
    """A TEMPORARY_STORAGE loss item requires a storage assignment of the same
    policy whose window contains the loss_date and which was APPROVED at that
    date; otherwise the adjustment is ERR_STORAGE_NOT_APPROVED (PRD 3.7).

    Design: Corner/validations/corner_storage_loss_requires_an_assignment_covering_the_loss_date
    """
    account = cedar_in_force(
        parts=(("MATERIALS_ON_SITE", 100000000),
               ("TEMPORARY_STORAGE", 10000000)))
    facility = fixtures.register_facility(
        name="Northside Warehouse", site_code="WH-01",
        distance_from_site_miles=12, aggregate_capacity_cents=500000000,
        protection_class="SPRINKLERED")
    # This occupancy ends six weeks before the loss.
    fixtures.assign_storage(account, facility, 5000000,
                            "2026-09-01T00:00:00Z", "2026-10-01T00:00:00Z",
                            headers=RE)

    claim = fixtures.report_claim(
        account, peril="THEFT", loss_date="2026-11-15T00:00:00Z",
        description="Switchgear stolen from the off-site store")
    storage_items = [f.loss_item("TEMPORARY_STORAGE", 5000000)]

    uncovered_location = api_client.adjust_claim(
        claim["id"], f.adjust_claim_payload(
            outcome="ADJUST", adjustment_basis="ACTUAL_LOSS",
            loss_items=storage_items), CA)
    validate_error(uncovered_location, "ERR_STORAGE_NOT_APPROVED",
                   expected_status=422)

    unvalued = validate_success(api_client.get_claim(claim["id"], CA))
    assert unvalued["adjustment_status"] == "REPORTED"
    assert unvalued["indemnity_cents"] == 0
    assert unvalued["allocation_lines"] == []

    second = fixtures.assign_storage(
        account, facility, 5000000,
        "2026-11-01T00:00:00Z", "2026-12-01T00:00:00Z", headers=RE)
    assert second["status"] == "APPROVED"
    # Both assignments are APPROVED, so the warehouse holds both commitments.
    held = validate_success(api_client.get_facility(facility["id"], RE))
    assert held["committed_value_cents"] == 10000000

    adjusted = validate_success(api_client.adjust_claim(
        claim["id"], f.adjust_claim_payload(
            outcome="ADJUST", adjustment_basis="ACTUAL_LOSS",
            loss_items=storage_items), CA))
    assert adjusted["adjustment_status"] == "ADJUSTED"
    # The single occurrence deductible of 2500000 lands on the only line.
    assert adjusted["indemnity_cents"] == 2500000
    assert adjusted["uncovered_cents"] == 2500000

    lines = adjusted["allocation_lines"]
    assert len(lines) == 1
    assert lines[0]["part_type"] == "TEMPORARY_STORAGE"
    assert lines[0]["covered_basis_cents"] == 5000000
    assert lines[0]["deductible_applied_cents"] == 2500000


def test_payment_is_capped_by_its_allocation_line_and_must_name_an_allocated_part():
    """A payment's part_type must name a bucket that actually received an
    allocation on the claim (ERR_PAYMENT_PART_NOT_ALLOCATED), and its amount may
    not exceed that allocation line (ERR_PAYMENT_EXCEEDS_ALLOCATION) — PRD 3.8.

    Design: Corner/validations/corner_payment_is_capped_by_its_allocation_line_and_must_name_an_allocated_part
    """
    account = cedar_in_force(
        parts=(("MATERIALS_ON_SITE", 60000000), ("IN_TRANSIT", 10000000)))
    claim = fixtures.adjusted_claim(
        account, [f.loss_item("MATERIALS_ON_SITE", 15000000)],
        loss_date="2026-11-15T00:00:00Z")
    # 15000000 less the single 2500000 deductible allocates 12500000.
    assert claim["indemnity_cents"] == 12500000
    settled = fixtures.settle_claim(claim, headers=CA2)
    claim_version = settled["version"]
    payee = account.owner_interest

    # IN_TRANSIT is ACTIVE on the policy but absent from the allocation.
    unallocated = api_client.create_loss_payment(
        f.create_loss_payment_payload(
            claim["id"], claim_version, payee["id"], "IN_TRANSIT", 1), CA)
    validate_error(unallocated, "ERR_PAYMENT_PART_NOT_ALLOCATED",
                   expected_status=422)

    over_line = api_client.create_loss_payment(
        f.create_loss_payment_payload(
            claim["id"], claim_version, payee["id"], "MATERIALS_ON_SITE",
            12500001), CA)
    validate_error(over_line, "ERR_PAYMENT_EXCEEDS_ALLOCATION",
                   expected_status=422)

    # A refused payment writes no row and leaves the claim's version alone.
    untouched = validate_success(api_client.get_claim(claim["id"], CA))
    assert untouched["version"] == claim_version
    assert untouched["paid_cents"] == 0

    payment = validate_success(
        api_client.create_loss_payment(
            f.create_loss_payment_payload(
                claim["id"], claim_version, payee["id"], "MATERIALS_ON_SITE",
                12500000), CA),
        expected_status=201)
    assert payment["status"] == "ISSUED"
    assert payment["amount_cents"] == 12500000

    paid = validate_success(api_client.get_claim(claim["id"], CA))
    assert paid["paid_cents"] == 12500000
    assert paid["outstanding_reserve_cents"] == 0
    assert paid["payment_status"] == "PAID"
    assert paid["adjustment_status"] == "CLOSED"

    materials = validate_success(api_client.get_coverage_part(
        account.part("MATERIALS_ON_SITE")["id"], UW))
    assert materials["eroded_cents"] == 12500000
    assert materials["available_cents"] == 47500000

    in_transit = validate_success(api_client.get_coverage_part(
        account.part("IN_TRANSIT")["id"], UW))
    assert in_transit["eroded_cents"] == 0


def test_payment_is_capped_by_the_part_availability_eroded_after_the_adjustment():
    """A payment may not exceed what the named coverage part can still pay —
    sublimit_cents less eroded_cents — and a breach of that availability is
    ERR_PAYMENT_EXCEEDS_RESERVE (PRD 3.8).

    Design: Corner/validations/corner_payment_is_capped_by_the_part_availability_eroded_after_the_adjustment
    """
    account = cedar_in_force(parts=(("MATERIALS_ON_SITE", 60000000),))
    payee = account.owner_interest

    # Both claims are valued before any money moves, so both see the full
    # 60000000 of headroom.
    claim_a = fixtures.adjusted_claim(
        account, [f.loss_item("MATERIALS_ON_SITE", 50000000)],
        peril="FIRE", loss_date="2026-10-10T00:00:00Z")
    claim_b = fixtures.adjusted_claim(
        account, [f.loss_item("MATERIALS_ON_SITE", 30000000)],
        peril="THEFT", loss_date="2026-10-20T00:00:00Z")
    assert claim_a["indemnity_cents"] == 47500000
    assert claim_b["indemnity_cents"] == 27500000

    settled_a = fixtures.settle_claim(claim_a, headers=CA2)
    settled_b = fixtures.settle_claim(claim_b, headers=CA2)
    claim_b_version = settled_b["version"]

    validate_success(
        api_client.create_loss_payment(
            f.create_loss_payment_payload(
                claim_a["id"], settled_a["version"], payee["id"],
                "MATERIALS_ON_SITE", 47500000), CA),
        expected_status=201)

    # 27500000 sits inside claim B's own allocation and reserve, so only the
    # part's remaining 12500000 of availability can refuse it.
    over_availability = api_client.create_loss_payment(
        f.create_loss_payment_payload(
            claim_b["id"], claim_b_version, payee["id"], "MATERIALS_ON_SITE",
            27500000), CA)
    validate_error(over_availability, "ERR_PAYMENT_EXCEEDS_RESERVE",
                   expected_status=422)

    # The refusal wrote nothing: no payment row and no version movement.
    unpaid_b = validate_success(api_client.get_claim(claim_b["id"], CA))
    assert unpaid_b["version"] == claim_b_version
    assert unpaid_b["paid_cents"] == 0
    assert total_count(api_client.list_loss_payments(
        CA, params={"claim_id": claim_b["id"]})) == 0

    remainder = validate_success(
        api_client.create_loss_payment(
            f.create_loss_payment_payload(
                claim_b["id"], claim_b_version, payee["id"],
                "MATERIALS_ON_SITE", 12500000), CA),
        expected_status=201)
    assert remainder["amount_cents"] == 12500000

    part = validate_success(api_client.get_coverage_part(
        account.part("MATERIALS_ON_SITE")["id"], UW))
    assert part["eroded_cents"] == 60000000
    assert part["available_cents"] == 0

    reread_b = validate_success(api_client.get_claim(claim_b["id"], CA))
    assert reread_b["paid_cents"] == 12500000
    assert reread_b["outstanding_reserve_cents"] == 15000000
    assert reread_b["payment_status"] == "PARTIALLY_PAID"
    assert reread_b["adjustment_status"] == "SETTLED"

    policy = validate_success(api_client.get_policy(account.policy_id, UW))
    assert policy["eroded_total_cents"] == 60000000

    assert total_count(api_client.list_loss_payments(
        CA, params={"claim_id": claim_b["id"]})) == 1


def test_policy_create_rejects_the_lowest_numbered_priority_first():
    """When one request breaks several rules at once the answer is the earliest
    rule in the pinned order of evaluation: the date-range check precedes the
    parent-version freshness check, which precedes the underwriting safety rules
    (PRD 2.11).

    Design: Corner/validations/corner_policy_create_rejects_the_lowest_numbered_priority_first
    """
    project = fixtures.eligible_project(
        engineering_grade="A", name="Newbuild Alpha", site_address="1 Alpha Rd",
        construction_type="FIRE_RESISTIVE", project_kind="NEW_CONSTRUCTION",
        hard_cost_value_cents=400000000, cat_zone="INLAND",
        planned_start_date="2026-09-01T00:00:00Z",
        projected_completion_date="2027-03-01T00:00:00Z")
    project_version = project["version"]

    def attempt(expected_project_version, term_start_date, term_end_date,
                includes_existing_structure):
        payload = f.create_policy_payload(
            project["id"], expected_project_version,
            term_start_date=term_start_date, term_end_date=term_end_date,
            includes_existing_structure=includes_existing_structure,
            deductible_tier="STANDARD_25K", limit_cents=900000000,
            daily_delay_rate_cents=0)
        return api_client.create_policy(payload, UW)

    # Reversed term dates, a stale parent version and an election that this
    # project kind cannot carry: the date range is checked first.
    everything_wrong = attempt(
        project_version - 1, "2027-03-20T00:00:00Z", "2026-09-01T00:00:00Z", True)
    validate_error(everything_wrong, "ERR_DATE_RANGE_INVALID",
                   expected_status=422)

    stale_view = attempt(
        project_version - 1, "2026-09-01T00:00:00Z", "2027-03-20T00:00:00Z", True)
    validate_error(stale_view, "ERR_STALE_PROJECT_VERSION", expected_status=412)

    bad_election = attempt(
        project_version, "2026-09-01T00:00:00Z", "2027-03-20T00:00:00Z", True)
    validate_error(bad_election, "ERR_EXISTING_STRUCTURE_NOT_APPLICABLE",
                   expected_status=422)

    policy = validate_success(
        attempt(project_version, "2026-09-01T00:00:00Z",
                "2027-03-20T00:00:00Z", False),
        expected_status=201)
    assert policy["status"] == "DRAFT"
    assert policy["insured_tiv_cents"] == 400000000
    assert policy["original_term_days"] == 200

    # Only the accepted create moved the project.
    reread = validate_success(api_client.get_project(project["id"], UW))
    assert reread["version"] == project_version + 1
