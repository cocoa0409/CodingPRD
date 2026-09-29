"""Role authorization and entity-backed peer identity.

Every test builds its own preconditions through declared endpoints against a
freshly launched server, and drives each call with the acting role the endpoint
table names.
"""

from typing import Any, Dict

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import assertions, constants, factories, fixtures
from test_helpers.api_errors import (
    ERR_IDENTITY_MISMATCH,
    ERR_PLAN_STATE_INVALID,
    ERR_ROLE_NOT_PERMITTED,
)
from test_helpers.constants import CLOCK_EPOCH
from test_helpers.test_users import make_expert_headers, make_participant_headers
from test_helpers.types import (
    AddressStatus,
    AmendmentScope,
    Cohort,
    DataStatus,
    ElectionChoice,
    ElectionStatus,
    ExpertStatus,
    InsurerStatus,
    PlanStatus,
    SafestAvailableOpinion,
    StrategyType,
)


def _open_window_with_notices(
    api, plan_id: str, opens_at: str = "2026-09-01T00:00:00Z"
) -> Dict[str, Any]:
    """Schedule a window, move the clock to its opening instant, and open it."""
    window = fixtures.create_window(api, plan_id, opens_at=opens_at)
    fixtures.set_clock(api, opens_at)
    return fixtures.open_window(api, window["id"])


class TestExclusiveOperationsRejectOtherRoles:
    """Each write is closed to every role outside its authorized-role list."""

    def test_rbac_exclusive_writes_reject_every_role_outside_their_list(
        self, api, sponsor, fiduciary, actuary, administrator, regulator
    ):
        """Five exclusive writes refuse the wrong role with ERR_ROLE_NOT_PERMITTED, and the owning role then succeeds on the identical body.

        Every request must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which that user acts.
        If the headers are well formed but the declared role does not appear in the target endpoint's authorized-role list (see §4), the request is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403).

        Design: Corner/rbac/each_exclusive_operation_rejects_the_other_roles_before_any_state_check
        """
        fixtures.set_clock(api, CLOCK_EPOCH)
        plan = fixtures.create_plan(api)

        plan_body = factories.plan_payload()
        strategy_body = factories.strategy_payload(StrategyType.HYBRID_WINDOW_AND_BUYOUT.value)
        participant_body = factories.participant_payload()
        insurer_body = factories.insurer_payload(insurer_name="Northwall Life Assurance")
        window_body = factories.window_payload()

        # Plan registration belongs to the sponsor alone.
        validate_error(api.create_plan(plan_body, actuary), ERR_ROLE_NOT_PERMITTED)
        # Drafting a strategy belongs to the actuary alone.
        validate_error(
            api.create_strategy(plan["id"], strategy_body, fiduciary), ERR_ROLE_NOT_PERMITTED
        )
        # Loading a participant belongs to the administrator alone.
        validate_error(
            api.create_participant(plan["id"], participant_body, actuary), ERR_ROLE_NOT_PERMITTED
        )
        # Registering a carrier belongs to the regulator alone.
        validate_error(api.create_insurer(insurer_body, sponsor), ERR_ROLE_NOT_PERMITTED)
        # Scheduling a window belongs to the administrator alone.
        validate_error(
            api.create_window(plan["id"], window_body, fiduciary), ERR_ROLE_NOT_PERMITTED
        )

        # The owning role is admitted with the very same body each refusal carried.
        strategy = validate_success(
            api.create_strategy(plan["id"], strategy_body, actuary), 201
        )
        participant = validate_success(
            api.create_participant(plan["id"], participant_body, administrator), 201
        )
        insurer = validate_success(api.create_insurer(insurer_body, regulator), 201)
        window = validate_success(api.create_window(plan["id"], window_body, administrator), 201)

        assert strategy["strategy_type"] == StrategyType.HYBRID_WINDOW_AND_BUYOUT.value
        assert participant["participant_reference"] == participant_body["participant_reference"]
        assert insurer["insurer_name"] == insurer_body["insurer_name"]
        assert window["window_label"] == window_body["window_name"]

        # None of the refused calls wrote a row: exactly one child of each kind exists.
        _rows, meta = validate_paginated(api.list_strategies(plan["id"], actuary))
        assert meta["total_count"] == 1, meta
        _rows, meta = validate_paginated(
            api.list_participants(administrator, {"plan_id": plan["id"]})
        )
        assert meta["total_count"] == 1, meta
        _rows, meta = validate_paginated(api.list_windows(plan["id"], administrator))
        assert meta["total_count"] == 1, meta

    def test_rbac_role_authorization_is_decided_before_the_plan_state_check(
        self, api, sponsor, regulator
    ):
        """The sponsor's attempt at the regulator's filing review is refused on the role, not on the plan's ONGOING status, which the same request earns once the role is right.

        When a single request violates several rules, exactly one error is returned, and which one is fully determined.
        The families below are evaluated in the order listed; the first family that finds a violation decides the response, and later families are not consulted.
        **Role authorization** — the acting role appears in the endpoint's authorized-role list, else `ERR_ROLE_NOT_PERMITTED`. Applies to every endpoint.
        **Own-state precondition** — the target resource's own status field permits the requested transition, else the entity-specific conflict error: `ERR_PLAN_STATE_INVALID`, `ERR_STRATEGY_STATE_INVALID`, `ERR_PARTICIPANT_STATE_INVALID`, `ERR_AUDIT_STATE_INVALID`, `ERR_WINDOW_STATE_INVALID`, `ERR_ELECTION_STATE_INVALID`, `ERR_TRANCHE_STATE_INVALID`, `ERR_QUOTE_STATE_INVALID`, `ERR_EXPERT_STATE_INVALID`, `ERR_TRANSFER_STATE_INVALID`, or `ERR_COMPLAINT_STATE_INVALID`, all HTTP 409. Applies to every state-transition endpoint.
        The `Regulator` reviews the filing with a `review_decision` of `APPROVE` or `RETURN_DEFICIENT`, and the plan must be in `TERMINATION_FILED` for either.

        Design: Corner/rbac/each_exclusive_operation_rejects_the_other_roles_before_any_state_check
        """
        fixtures.set_clock(api, CLOCK_EPOCH)
        plan = fixtures.create_plan(api)
        assert plan["plan_status"] == PlanStatus.ONGOING.value

        review_body = factories.filing_review_payload()

        # Role comes first: the sponsor never reaches the status comparison.
        validate_error(
            api.post_filing_review(plan["id"], review_body, sponsor), ERR_ROLE_NOT_PERMITTED
        )
        # The authorized role reaches it and is refused on the plan's own state.
        validate_error(
            api.post_filing_review(plan["id"], review_body, regulator), ERR_PLAN_STATE_INVALID
        )

        after = fixtures.read_plan(api, plan["id"])
        assert after["plan_status"] == PlanStatus.ONGOING.value
        assert after["version"] == plan["version"]

    def test_rbac_valuation_update_admits_only_the_sponsor_and_the_actuary(
        self, api, sponsor, actuary, administrator
    ):
        """A shared operation is shared only with its declared roles: the administrator's valuation update is refused although its body and expected version are valid, while both declared roles are admitted.

        If the headers are well formed but the declared role does not appear in the target endpoint's authorized-role list (see §4), the request is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403).
        Either a `PlanSponsor` or an `Actuary` may record it, and because the write supersedes the prior measurement it carries `expected_plan_version` under the stale-version rule of §2.9.

        Design: Corner/rbac/each_exclusive_operation_rejects_the_other_roles_before_any_state_check
        """
        fixtures.set_clock(api, CLOCK_EPOCH)
        plan = fixtures.create_plan(api)
        body = factories.valuation_update_payload(plan["version"], plan_assets_cents=93000000)

        validate_error(
            api.post_valuation_update(plan["id"], body, administrator), ERR_ROLE_NOT_PERMITTED
        )

        refused = fixtures.read_plan(api, plan["id"])
        assert refused["version"] == plan["version"]
        assert refused["plan_assets_cents"] == plan["plan_assets_cents"]

        by_actuary = validate_success(api.post_valuation_update(plan["id"], body, actuary), 200)
        assert by_actuary["plan_assets_cents"] == 93000000
        assert by_actuary["version"] == plan["version"] + 1
        assert by_actuary["accounting_funded_status_bp"] == constants.funded_status_bp(
            93000000, by_actuary["total_liability_cents"]
        )

        sponsor_body = factories.valuation_update_payload(
            by_actuary["version"], plan_assets_cents=94000000
        )
        by_sponsor = validate_success(
            api.post_valuation_update(plan["id"], sponsor_body, sponsor), 200
        )
        assert by_sponsor["plan_assets_cents"] == 94000000
        assert by_sponsor["version"] == by_actuary["version"] + 1


class TestParticipantPeerIdentity:
    """A `Participant` may only touch the election that is their own."""

    def _two_member_open_window(self, api):
        authorized = fixtures.build_authorized_plan(
            api,
            participants=[
                fixtures.ParticipantSpec(
                    stated_monthly_benefit_cents=20000,
                    cohort=Cohort.DEFERRED_VESTED.value,
                    credited_service_months=240,
                ),
                fixtures.ParticipantSpec(
                    stated_monthly_benefit_cents=24000,
                    cohort=Cohort.DEFERRED_VESTED.value,
                    credited_service_months=240,
                ),
            ],
            strategy_type=StrategyType.LUMP_SUM_WINDOW.value,
            amendment_scope=AmendmentScope.LUMP_SUM_ONLY.value,
        )
        member_a, member_b = authorized.participants
        for member in (member_a, member_b):
            assert member["address_status"] == AddressStatus.CONFIRMED.value
            assert member["data_status"] == DataStatus.CLEAN.value
        window = _open_window_with_notices(api, authorized.plan_id)
        assert window["notice_count"] == 2, window
        election_a = fixtures.election_for(api, window["id"], member_a["id"])
        election_b = fixtures.election_for(api, window["id"], member_b["id"])
        assert election_a["election_status"] == ElectionStatus.NOTICE_SENT.value
        assert election_b["election_status"] == ElectionStatus.NOTICE_SENT.value
        return member_a, member_b, election_a, election_b

    def test_rbac_participant_cannot_elect_on_another_members_notice(self, api, administrator):
        """Member B electing on member A's notice is refused as an identity mismatch, the administrator is refused on the role, and A's own election is priced and accepted.

        When `X-User-Role` is `Participant`, `X-User-ID` is the `id` of the acting `ParticipantRecord`. On an election or a revocation, `X-User-ID` must equal the election's `participant_id`; on a complaint filing, `X-User-ID` must equal the participant identifier in the request path.
        Any of those ownership comparisons failing yields `ERR_IDENTITY_MISMATCH` (HTTP 403).
        Choosing the lump sum moves the election `NOTICE_SENT → ELECTED_LUMP_SUM`, stamps `elected_at` with the logical clock, records `election_choice`, and prices the offer immediately, storing `raw_pv_cents`, `admin_fee_bp`, `admin_fee_cents`, and `net_lump_sum_cents`.

        Design: Corner/rbac/participant_cannot_act_on_another_members_election
        """
        member_a, member_b, election_a, _election_b = self._two_member_open_window(api)
        lump_sum = factories.election_payload(ElectionChoice.LUMP_SUM.value)

        validate_error(
            api.post_election(election_a["id"], lump_sum, make_participant_headers(member_b["id"])),
            ERR_IDENTITY_MISMATCH,
        )
        untouched = fixtures.read_election(api, election_a["id"])
        assert untouched["election_status"] == ElectionStatus.NOTICE_SENT.value
        assert untouched["version"] == election_a["version"]

        # Electing is a Participant-exclusive operation.
        validate_error(
            api.post_election(election_a["id"], lump_sum, administrator), ERR_ROLE_NOT_PERMITTED
        )

        elected = validate_success(
            api.post_election(election_a["id"], lump_sum, make_participant_headers(member_a["id"])),
            200,
        )
        assert elected["election_status"] == ElectionStatus.ELECTED_LUMP_SUM.value
        assertions.assert_election_pricing(
            elected,
            constants.raw_lump_sum_pv(
                member_a["audited_monthly_benefit_cents"], member_a["cohort"]
            ),
        )

    def test_rbac_participant_cannot_revoke_another_members_election(self, api):
        """Member B revoking member A's election is refused as an identity mismatch and leaves A's election untouched, while B's own annuity election is accepted unpriced.

        When `X-User-Role` is `Participant`, `X-User-ID` is the `id` of the acting `ParticipantRecord`. On an election or a revocation, `X-User-ID` must equal the election's `participant_id`; on a complaint filing, `X-User-ID` must equal the participant identifier in the request path.
        Any of those ownership comparisons failing yields `ERR_IDENTITY_MISMATCH` (HTTP 403).
        Choosing the annuity moves the election `NOTICE_SENT → ELECTED_ANNUITY` and likewise stamps `elected_at` and records `election_choice`, but no pricing runs: `raw_pv_cents`, `admin_fee_bp`, `admin_fee_cents`, and `net_lump_sum_cents` all stay null, because the participant is keeping their annuity and staying in the plan.

        Design: Corner/rbac/participant_cannot_act_on_another_members_election
        """
        member_a, member_b, election_a, election_b = self._two_member_open_window(api)

        elected = fixtures.elect(
            api, election_a["id"], member_a["id"], ElectionChoice.LUMP_SUM.value
        )
        assert elected["election_status"] == ElectionStatus.ELECTED_LUMP_SUM.value
        assert elected["revocation_count"] == 0

        validate_error(
            api.post_election_revocation(
                election_a["id"], {}, make_participant_headers(member_b["id"])
            ),
            ERR_IDENTITY_MISMATCH,
        )
        after = fixtures.read_election(api, election_a["id"])
        assert after["election_status"] == ElectionStatus.ELECTED_LUMP_SUM.value
        assert after["revocation_count"] == 0
        assert after["version"] == elected["version"]

        own = validate_success(
            api.post_election(
                election_b["id"],
                factories.election_payload(ElectionChoice.ANNUITY.value),
                make_participant_headers(member_b["id"]),
            ),
            200,
        )
        assert own["election_status"] == ElectionStatus.ELECTED_ANNUITY.value
        assertions.assert_null_fields(
            own, "raw_pv_cents", "admin_fee_bp", "admin_fee_cents", "net_lump_sum_cents"
        )


class TestIndependentExpertPeerIdentity:
    """An `IndependentExpertUser` may only sign the opinion of its own engagement."""

    def _two_engaged_experts(self, api):
        fixtures.set_clock(api, CLOCK_EPOCH)
        plan = fixtures.create_plan(api)
        first = fixtures.create_expert(api, plan["id"], "Marlowe Independent Advisers")
        second = fixtures.create_expert(api, plan["id"], "Rowntree Fiduciary Counsel")
        first = fixtures.review_expert(api, first["id"])
        second = fixtures.review_expert(api, second["id"])
        assert first["expert_status"] == ExpertStatus.ENGAGED.value
        assert second["expert_status"] == ExpertStatus.ENGAGED.value
        return first, second

    def test_rbac_expert_cannot_issue_another_engagements_opinion(self, api):
        """Firm B signing firm A's opinion is refused as an identity mismatch, A's own opinion is accepted, and nothing leaks onto B's engagement.

        When `X-User-Role` is `IndependentExpertUser`, `X-User-ID` is the `id` of the acting `IndependentExpert`. On an opinion issuance, `X-User-ID` must equal the expert engagement identifier in the request path.
        Any of those ownership comparisons failing yields `ERR_IDENTITY_MISMATCH` (HTTP 403).
        The engagement must be in `ENGAGED`, otherwise `ERR_EXPERT_NOT_ENGAGED`, and the acting `X-User-ID` must be this engagement's own identifier, otherwise `ERR_IDENTITY_MISMATCH`.
        Issuing the opinion moves the engagement `ENGAGED → OPINION_ISSUED`, stores the opinion, stamps `opinion_issued_at` from the logical clock, and bumps the `version`.

        Design: Corner/rbac/independent_expert_cannot_opine_on_another_engagement
        """
        first, second = self._two_engaged_experts(api)
        opinion = factories.expert_opinion_payload(SafestAvailableOpinion.AFFIRMATIVE.value)

        validate_error(
            api.post_expert_opinion(first["id"], opinion, make_expert_headers(second["id"])),
            ERR_IDENTITY_MISMATCH,
        )
        refused = fixtures.read_expert(api, first["id"])
        assert refused["expert_status"] == ExpertStatus.ENGAGED.value
        assert refused["version"] == first["version"]

        issued = validate_success(
            api.post_expert_opinion(first["id"], opinion, make_expert_headers(first["id"])), 200
        )
        assert issued["expert_status"] == ExpertStatus.OPINION_ISSUED.value
        assert issued["safest_available_opinion"] == SafestAvailableOpinion.AFFIRMATIVE.value
        assertions.assert_timestamps_present(issued, "opinion_issued_at")

        peer = fixtures.read_expert(api, second["id"])
        assert peer["expert_status"] == ExpertStatus.ENGAGED.value
        assert peer["safest_available_opinion"] is None
        assert peer["opinion_issued_at"] is None
        assert peer["version"] == second["version"]

    def test_rbac_expert_opinion_rejects_the_engaging_fiduciary(self, api, fiduciary):
        """The fiduciary that engaged the firm cannot issue the opinion on its behalf, and the engagement stays ENGAGED.

        If the headers are well formed but the declared role does not appear in the target endpoint's authorized-role list (see §4), the request is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403).
        The engaged firm itself, acting as `IndependentExpertUser`, then issues its opinion by supplying a `safest_available_opinion` of `AFFIRMATIVE`, `QUALIFIED`, or `ADVERSE`.

        Design: Corner/rbac/independent_expert_cannot_opine_on_another_engagement
        """
        first, _second = self._two_engaged_experts(api)
        opinion = factories.expert_opinion_payload(SafestAvailableOpinion.AFFIRMATIVE.value)

        validate_error(
            api.post_expert_opinion(first["id"], opinion, fiduciary), ERR_ROLE_NOT_PERMITTED
        )

        after = fixtures.read_expert(api, first["id"])
        assert after["expert_status"] == ExpertStatus.ENGAGED.value
        assert after["safest_available_opinion"] is None
        assert after["version"] == first["version"]


class TestRegulatorWriteSurface:
    """The `Regulator` reads everything and writes only the registry and the filing review."""

    def test_rbac_regulator_reads_the_plan_but_cannot_write_to_it(
        self, api, regulator, administrator
    ):
        """The same regulator session that reads the plan, its participants and its funded status cannot load a participant or adopt the settlement amendment.

        If the headers are well formed but the declared role does not appear in the target endpoint's authorized-role list (see §4), the request is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403).
        Its accounting figure, `accounting_funded_status_bp`, is 0 whenever `total_liability_cents` is 0; otherwise it is `plan_assets_cents` multiplied by 10,000 and rounded half up over `total_liability_cents`, so a fully funded plan reads 10000 basis points.

        Design: Corner/rbac/regulator_cannot_write_outside_the_registry_and_filing_review
        """
        fixtures.set_clock(api, CLOCK_EPOCH)
        plan = fixtures.create_plan(api)
        participant = fixtures.create_participant(api, plan["id"])

        read_plan = validate_success(api.get_plan(plan["id"], regulator), 200)
        assert read_plan["plan_status"] == PlanStatus.ONGOING.value

        rows, meta = validate_paginated(api.list_participants(regulator, {"plan_id": plan["id"]}))
        assert assertions.ids_of(rows) == [participant["id"]]
        assert meta["total_count"] == 1

        funded = validate_success(api.get_funded_status(plan["id"], regulator), 200)
        assertions.assert_funded_status_shape(funded)
        assert funded["accounting_funded_status_bp"] == constants.funded_status_bp(
            read_plan["plan_assets_cents"], read_plan["total_liability_cents"]
        )

        validate_error(
            api.create_participant(plan["id"], factories.participant_payload(), regulator),
            ERR_ROLE_NOT_PERMITTED,
        )
        validate_error(
            api.post_settlement_amendment(
                plan["id"],
                factories.amendment_adopt_payload(
                    AmendmentScope.BUYOUT_ONLY.value, "2026-08-15T00:00:00Z"
                ),
                regulator,
            ),
            ERR_ROLE_NOT_PERMITTED,
        )

        _rows, meta = validate_paginated(
            api.list_participants(administrator, {"plan_id": plan["id"]})
        )
        assert meta["total_count"] == 1, meta
        after = fixtures.read_plan(api, plan["id"])
        assert after["plan_status"] == PlanStatus.ONGOING.value
        assert after["amendment_scope"] is None
        assert after["version"] == plan["version"]

    def test_rbac_carrier_registry_writes_are_regulator_exclusive(self, api, regulator, fiduciary):
        """The regulator may register a carrier and record a rating action on it, and the fiduciary's registration attempt is refused without writing a row.

        If the headers are well formed but the declared role does not appear in the target endpoint's authorized-role list (see §4), the request is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403).
        **The carrier registry** is the `Regulator`'s to keep.
        A newly registered carrier has `insurer_status` `ACTIVE`, `committed_capacity_cents` 0, `available_capacity_cents` equal to its `capacity_cents`, and `rating_changed_at` null.
        A rating action supplies a new `rating_grade`, optionally a revised `capital_ratio_bp`, and optionally a new `insurer_status` of `ACTIVE`, `UNDER_REVIEW`, or `WITHDRAWN` — the registry standing is moved only by these regulator actions.

        Design: Corner/rbac/regulator_cannot_write_outside_the_registry_and_filing_review
        """
        fixtures.set_clock(api, CLOCK_EPOCH)

        insurer = validate_success(
            api.create_insurer(
                factories.insurer_payload(
                    insurer_name="Northwall Life",
                    rating_grade="AA",
                    capital_ratio_bp=4200,
                    capacity_cents=500000000,
                ),
                regulator,
            ),
            201,
        )
        assertions.assert_insurer_shape(insurer)
        assert insurer["insurer_status"] == InsurerStatus.ACTIVE.value
        assertions.assert_capacity(insurer, 0, 500000000)

        rated = validate_success(
            api.post_rating_change(
                insurer["id"],
                factories.rating_change_payload("AA_MINUS", capital_ratio_bp=3900),
                regulator,
            ),
            200,
        )
        assert rated["rating_grade"] == "AA_MINUS"
        assert rated["capital_ratio_bp"] == 3900
        assert rated["insurer_status"] == InsurerStatus.ACTIVE.value
        assertions.assert_timestamps_present(rated, "rating_changed_at")
        assertions.assert_capacity(rated, 0, 500000000)

        refused_body = factories.insurer_payload(
            insurer_name="Sablefield Assurance",
            rating_grade="A",
            capital_ratio_bp=3600,
            capacity_cents=400000000,
        )
        validate_error(api.create_insurer(refused_body, fiduciary), ERR_ROLE_NOT_PERMITTED)

        # The refused registration claimed no name: the regulator may still use it.
        second = validate_success(api.create_insurer(refused_body, regulator), 201)
        assert second["insurer_name"] == "Sablefield Assurance"
