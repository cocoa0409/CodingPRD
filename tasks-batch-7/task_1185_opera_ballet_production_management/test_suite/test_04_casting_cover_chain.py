"""Casting, cover links, principal uniqueness, and the cover-promotion cascade."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_active_contract,
    create_cast_assignment,
    create_cast_assignment_payload,
    create_production,
    create_production_in_state,
    create_role,
    get_cast_assignment,
    get_role,
    release_cast_assignment,
    setup_confirmed_principal,
    setup_fully_cast_role,
    transition_production,
    validate_error,
    validate_success,
)

ANY = TEST_USERS["any_headers"]
CD = TEST_USERS["casting_director_headers"]


class TestCoverLinkIntegrity:
    def test_cover_link_to_other_role_rejected(self, api):
        """PRD §3.5: "The cover link must reference a `PRINCIPAL`-slot assignment on the same role; a missing or invalid link is rejected with `ERR_COVER_LINK_INVALID` (HTTP 422)."

        Design: Corner/validations/cover_link_to_other_role_rejected
        """
        production = create_production_in_state("BUILD")
        role_o = create_role(production["id"], role_name="Odette/Odile",
                             voice_type="DANCER_F", is_title_role=True)
        role_s = create_role(production["id"], role_name="Siegfried",
                             voice_type="DANCER_M", is_title_role=False)
        _, contract_a = create_active_contract(production["id"])
        principal = create_cast_assignment(role_o["id"], contract_a["id"], slot="PRINCIPAL")
        confirm_resp = api.confirm_cast_assignment(principal["id"], CD)
        validate_success(confirm_resp, 200)
        _, contract_b = create_active_contract(
            production["id"], artist_overrides={"full_name": "Bella Cover"},
            engagement_type="COVER", hourly_rate_cents=6_000, weekly_hours_cap=25,
        )

        resp = api.create_cast_assignment(
            create_cast_assignment_payload(
                role_s["id"], contract_b["id"], slot="COVER_1",
                covers_assignment_id=principal["id"],
            ),
            CD,
        )
        validate_error(resp, ApiErrorId.ERR_COVER_LINK_INVALID)

    def test_cross_production_contract_rejected(self, api):
        """PRD §3.5: "The contract must belong to the same production as the role, else `ERR_CROSS_PRODUCTION_REFERENCE` (HTTP 422)."

        Design: Corner/validations/cross_production_contract_rejected
        """
        prod_a = create_production_in_state("BUILD", title="Swan Lake",
                                            build_budget_cents=100_000_000)
        prod_b = create_production_in_state("BUILD", title="Otello", work_type="OPERA",
                                            build_budget_cents=80_000_000)
        role_a = create_role(prod_a["id"], role_name="Odette/Odile",
                             voice_type="DANCER_F", is_title_role=True)
        _, contract_b = create_active_contract(prod_b["id"])

        resp = api.create_cast_assignment(
            create_cast_assignment_payload(role_a["id"], contract_b["id"], slot="PRINCIPAL"),
            CD,
        )
        validate_error(resp, ApiErrorId.ERR_CROSS_PRODUCTION_REFERENCE)


class TestPrincipalUniqueness:
    def test_second_principal_confirm_rejected(self, api):
        """PRD §3.5: "Confirming an assignment runs three guards in the pipeline order of §2.9: the contract must be `ACTIVE`, else `ERR_CONTRACT_NOT_ACTIVE`; for a cover slot, the assignment referenced by `covers_assignment_id` must itself be `CONFIRMED`, else `ERR_COVER_LINK_INVALID`; and for a principal slot, no other `CONFIRMED` principal may exist on the same role, else `ERR_ROLE_PRINCIPAL_TAKEN` (HTTP 409)."

        Design: Corner/validations/second_principal_confirm_rejected
        """
        scenario = setup_confirmed_principal()
        role = scenario["role"]
        production = scenario["production"]
        _, contract_b = create_active_contract(
            production["id"], artist_overrides={"full_name": "Bella Second"}
        )
        second = create_cast_assignment(role["id"], contract_b["id"], slot="PRINCIPAL")

        resp = api.confirm_cast_assignment(second["id"], CD)
        validate_error(resp, ApiErrorId.ERR_ROLE_PRINCIPAL_TAKEN)
        after = get_cast_assignment(second["id"])
        assert after["status"] == "PROPOSED", "rejected confirm leaves the assignment PROPOSED"


class TestCoverPromotionCascade:
    def test_principal_release_promotes_cover1(self, api):
        """PRD §3.5: "Releasing a `CONFIRMED` assignment moves it to `RELEASED` — and when the released assignment was the role's principal, the cover-promotion cascade fires: among the assignments whose `covers_assignment_id` pointed at the released principal and whose status is `CONFIRMED`, the one with the lowest slot rank (`COVER_1` before `COVER_2`) is chosen, ties broken by earliest `created_at`; the promoted assignment's `slot` becomes `PRINCIPAL` and its `covers_assignment_id` is cleared while its status stays `CONFIRMED`; every other `CONFIRMED` cover of the released principal is re-pointed so its `covers_assignment_id` references the promoted assignment."

        Design: Difficulty/transitive_cascade/principal_release_cover_promotion_cascade
        """
        scenario = setup_fully_cast_role()
        role = scenario["role"]
        principal = scenario["principal"]
        cover1 = scenario["cover1"]

        before = get_role(role["id"])
        assert before["casting_status"] == "FULLY_CAST"

        released = release_cast_assignment(principal["id"])
        assert released["status"] == "RELEASED"

        promoted = get_cast_assignment(cover1["id"])
        assert promoted["slot"] == "PRINCIPAL", "cascade link 1: COVER_1 auto-promoted"
        assert promoted["covers_assignment_id"] is None, "promoted cover's link is cleared"
        assert promoted["status"] == "CONFIRMED", "promotion keeps confirmation"

        role_after = get_role(role["id"])
        assert role_after["casting_status"] == "PRINCIPAL_SET", (
            "cascade link 2: FULLY_CAST -> PRINCIPAL_SET (no confirmed cover remains)"
        )

    def test_release_proposed_assignment_withdraws_without_cascade(self, api):
        """PRD §3.5: "A `PROPOSED` assignment becomes `WITHDRAWN` with no further ceremony."
        PRD §3.5: "it is `FULLY_CAST` when a `CONFIRMED` principal assignment and at least one `CONFIRMED` cover assignment exist on the role, `PRINCIPAL_SET` when a `CONFIRMED` principal exists but no confirmed cover does, and `UNFILLED` otherwise."

        Design: Difficulty/transitive_cascade/principal_release_cover_promotion_cascade
        """
        production = create_production_in_state("BUILD")
        role = create_role(production["id"], role_name="Odette/Odile", voice_type="DANCER_F")
        _, contract = create_active_contract(production["id"])
        proposed = create_cast_assignment(role["id"], contract["id"], slot="PRINCIPAL")

        withdrawn = release_cast_assignment(proposed["id"])
        assert withdrawn["status"] == "WITHDRAWN"
        role_after = get_role(role["id"])
        assert role_after["casting_status"] == "UNFILLED", (
            "withdrawing a PROPOSED assignment fires no promotion cascade"
        )


class TestCoverPromotionSelector:
    def test_cover_promotion_selector_determinism(self, api):
        """PRD §3.5: "the one with the lowest slot rank (`COVER_1` before `COVER_2`) is chosen, ties broken by earliest `created_at`; the promoted assignment's `slot` becomes `PRINCIPAL` and its `covers_assignment_id` is cleared while its status stays `CONFIRMED`; every other `CONFIRMED` cover of the released principal is re-pointed so its `covers_assignment_id` references the promoted assignment."
        PRD §3.5: "it is `FULLY_CAST` when a `CONFIRMED` principal assignment and at least one `CONFIRMED` cover assignment exist on the role, `PRINCIPAL_SET` when a `CONFIRMED` principal exists but no confirmed cover does, and `UNFILLED` otherwise."

        Design: Corner/state_machines/cover_promotion_selector_determinism
        """
        scenario = setup_fully_cast_role(with_second_cover=True)
        role = scenario["role"]
        principal = scenario["principal"]
        cover1 = scenario["cover1"]
        cover2 = scenario["cover2"]

        release_cast_assignment(principal["id"])

        promoted = get_cast_assignment(cover1["id"])
        assert promoted["slot"] == "PRINCIPAL", "COVER_1 promoted before COVER_2 (slot rank)"

        remaining = get_cast_assignment(cover2["id"])
        assert remaining["slot"] == "COVER_2"
        assert remaining["covers_assignment_id"] == cover1["id"], (
            "remaining cover is re-pointed to the promoted principal"
        )

        role_after = get_role(role["id"])
        assert role_after["casting_status"] == "FULLY_CAST", (
            "promoted principal plus remaining confirmed cover keeps the role FULLY_CAST"
        )
