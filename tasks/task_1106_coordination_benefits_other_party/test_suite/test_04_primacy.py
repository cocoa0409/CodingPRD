"""Primacy determination rule selection, supersession branching, and the MSP
void cascade (PRD §3.4, §3.5)."""
from test_helpers import (
    TEST_USERS,
    create_config,
    create_member,
    create_verified_coverage,
    current_member_version,
    draft_and_finalize_determination,
    draft_determination,
    finalize_determination,
    get_success_data,
    validate_paginated,
    validate_success,
)

COB = TEST_USERS["cob_analyst_headers"]


def _setup_dependent_child_with_two_parent_coverages():
    """Father (dob 1975-03-15, MALE), mother (dob 1978-07-20, FEMALE), child
    subscribed under father, with one VERIFIED parent-held coverage each."""
    father = create_member(
        member_external_id="F", full_name="Father", date_of_birth="1975-03-15",
        gender="MALE",
    )
    mother = create_member(
        member_external_id="M", full_name="Mother", date_of_birth="1978-07-20",
        gender="FEMALE",
    )
    child = create_member(
        member_external_id="C", full_name="Child", date_of_birth="2010-01-01",
        gender="OTHER", relation_to_subscriber="CHILD",
        subscriber_member_id=father["id"], employer_size=0,
    )
    cov_father = create_verified_coverage(
        child["id"], payer_id="PF", plan_name="Dad's Plan",
        coverage_kind="GROUP_HEALTH", subscriber_relationship="PARENT",
        policy_holder_dob="1975-03-15", policy_holder_gender="MALE",
        effective_from="2026-01-01", verification_source="MEMBER_SURVEY",
    )
    cov_mother = create_verified_coverage(
        child["id"], payer_id="PM", plan_name="Mom's Plan",
        coverage_kind="GROUP_HEALTH", subscriber_relationship="PARENT",
        policy_holder_dob="1978-07-20", policy_holder_gender="FEMALE",
        effective_from="2026-01-01", verification_source="MEMBER_SURVEY",
    )
    return father, mother, child, cov_father, cov_mother


class TestDependentPrimacyVariants:
    def test_birthday_rule_orders_earlier_calendar_birthday_first(self, api):
        """PRD §3.5: "4. `BIRTHDAY_RULE` — for a dependent child with two
        parent-held coverages: order by the `policy_holder_dob` month-and-day in
        ascending calendar order, so the parent whose birthday occurs earlier in
        the calendar year holds the primary coverage". March 15 precedes July 20
        in the calendar, so the father's coverage is primary.

        Design: Difficulty/dual_variant_calc/birthday_vs_gender_rule_dependent_primacy
        """
        create_config(config_name="bday", dependent_primacy_rule="BIRTHDAY_RULE")
        _f, _m, child, cov_father, cov_mother = (
            _setup_dependent_child_with_two_parent_coverages()
        )
        determination = draft_and_finalize_determination(child["id"], "2026-03-01")
        assert determination["status"] == "FINALIZED"
        assert determination["deciding_rule"] == "BIRTHDAY_RULE"
        assert determination["ordered_coverage_ids"][0] == cov_father["id"]
        assert cov_mother["id"] in determination["ordered_coverage_ids"]

    def test_gender_rule_orders_male_policy_holder_first_and_supersedes(self, api):
        """PRD §3.5: "5. `GENDER_RULE` — for a dependent child, but only when the
        active configuration's `dependent_primacy_rule` is `GENDER_RULE`: the
        coverage whose `policy_holder_gender` is `MALE` comes first; dates of
        birth are never consulted on this path." And §3.5: "the incumbent
        transitions from `FINALIZED` to `SUPERSEDED`, its `superseded_by_id` is
        set to the new determination's `id`".

        Design: Difficulty/dual_variant_calc/birthday_vs_gender_rule_dependent_primacy
        """
        config = create_config(config_name="bday", dependent_primacy_rule="BIRTHDAY_RULE")
        _f, _m, child, cov_father, _cov_mother = (
            _setup_dependent_child_with_two_parent_coverages()
        )
        pd_birthday = draft_and_finalize_determination(child["id"], "2026-03-01")
        assert pd_birthday["deciding_rule"] == "BIRTHDAY_RULE"

        create_config(
            config_name="gender", dependent_primacy_rule="GENDER_RULE",
            expected_active_config_version=config["version"],
        )
        pd_gender = draft_and_finalize_determination(child["id"], "2026-03-01")
        assert pd_gender["deciding_rule"] == "GENDER_RULE"
        assert pd_gender["ordered_coverage_ids"][0] == cov_father["id"]

        old = validate_success(
            api.get_primacy_determination(child["id"], pd_birthday["id"], COB), 200
        )
        assert old["status"] == "SUPERSEDED"
        assert old["superseded_by_id"] == pd_gender["id"]


class TestSupersedeBranching:
    def test_new_finalized_determination_supersedes_incumbent(self, api):
        """PRD §3.5: "when a newly finalized determination overlaps an incumbent
        `FINALIZED` determination for the same member and service date, the
        incumbent transitions from `FINALIZED` to `SUPERSEDED`, its
        `superseded_by_id` is set to the new determination's `id`".

        Design: Difficulty/non_linear_state_machine/primacy_determination_supersede_branching
        """
        from test_helpers import setup_member_with_our_plan_and_group

        member, _own, _group = setup_member_with_our_plan_and_group()
        pd1 = draft_and_finalize_determination(member["id"], "2026-03-01")
        pd2 = draft_and_finalize_determination(member["id"], "2026-03-01")

        old = validate_success(
            api.get_primacy_determination(member["id"], pd1["id"], COB), 200
        )
        assert old["status"] == "SUPERSEDED"
        assert old["superseded_by_id"] == pd2["id"]
        new = validate_success(
            api.get_primacy_determination(member["id"], pd2["id"], COB), 200
        )
        assert new["status"] == "FINALIZED"

    def test_incumbent_stays_finalized_until_new_draft_finalizes(self, api):
        """PRD §3.5: "if a `FINALIZED` determination already exists for the same
        member with an overlapping `as_of_service_date`, that incumbent is
        automatically superseded once the new determination finalizes." Merely
        drafting the successor leaves the incumbent FINALIZED.

        Design: Difficulty/non_linear_state_machine/primacy_determination_supersede_branching
        """
        from test_helpers import setup_member_with_our_plan_and_group

        member, _own, _group = setup_member_with_our_plan_and_group()
        pd1 = draft_and_finalize_determination(member["id"], "2026-03-01")

        pd2 = draft_determination(member["id"], "2026-03-01")
        mid = validate_success(
            api.get_primacy_determination(member["id"], pd1["id"], COB), 200
        )
        assert mid["status"] == "FINALIZED"

        finalize_determination(member["id"], pd2["id"])
        after = validate_success(
            api.get_primacy_determination(member["id"], pd1["id"], COB), 200
        )
        assert after["status"] == "SUPERSEDED"


class TestSameServiceDateSupersede:
    def test_same_service_date_collision_supersedes_with_link(self, api):
        """PRD §3.5: "when a newly finalized determination overlaps an incumbent
        `FINALIZED` determination for the same member and service date, the
        incumbent transitions from `FINALIZED` to `SUPERSEDED`, its
        `superseded_by_id` is set to the new determination's `id`".

        Design: Difficulty/resource_temporal_overlap/primacy_determination_same_service_date_supersede
        """
        from test_helpers import setup_member_with_our_plan_and_group

        member, _own, _group = setup_member_with_our_plan_and_group()
        pd1 = draft_and_finalize_determination(member["id"], "2026-03-01")
        pd2 = draft_and_finalize_determination(member["id"], "2026-03-01")

        old = validate_success(
            api.get_primacy_determination(member["id"], pd1["id"], COB), 200
        )
        assert old["status"] == "SUPERSEDED"
        assert old["superseded_by_id"] == pd2["id"]
        new = validate_success(
            api.get_primacy_determination(member["id"], pd2["id"], COB), 200
        )
        assert new["status"] == "FINALIZED"

    def test_status_filter_lists_exactly_one_finalized_after_supersede(self, api):
        """PRD §3.5: "Determinations are listed per member with a `status`
        filter" and §3.5: "the incumbent transitions from `FINALIZED` to
        `SUPERSEDED`".

        Design: Difficulty/resource_temporal_overlap/primacy_determination_same_service_date_supersede
        """
        from test_helpers import setup_member_with_our_plan_and_group

        member, _own, _group = setup_member_with_our_plan_and_group()
        pd1 = draft_and_finalize_determination(member["id"], "2026-03-01")
        pd2 = draft_and_finalize_determination(member["id"], "2026-03-01")

        finalized, _ = validate_paginated(
            api.list_primacy_determinations(member["id"], COB, params={"status": "FINALIZED"})
        )
        assert [d["id"] for d in finalized] == [pd2["id"]]
        superseded, _ = validate_paginated(
            api.list_primacy_determinations(member["id"], COB, params={"status": "SUPERSEDED"})
        )
        assert [d["id"] for d in superseded] == [pd1["id"]]
