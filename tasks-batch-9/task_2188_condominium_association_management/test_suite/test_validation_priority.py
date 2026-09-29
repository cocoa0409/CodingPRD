"""Two defects at once: the lower-numbered ladder rung must answer.

Each scenario stages a request that fails two independent checks
simultaneously, asserts the earlier identifier, then repairs the earlier
defect alone and shows the later one surfacing unchanged -- which is the only
way to prove the second defect was genuinely present all along.
"""

from __future__ import annotations

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_success,
)

from test_helpers.api_client import ApiClient
from test_helpers.assertions import (
    assert_instant_equals,
    read_budget,
    read_contract,
    read_element,
    read_meeting,
    read_work_order,
)
from test_helpers.fixtures import (
    add_contract,
    add_element,
    add_work_order,
    award_and_activate_contract,
    build_board,
    convene,
    create_association,
    draft_budget,
    notice_meeting,
    schedule_meeting,
    set_clock,
)
from test_helpers.test_users import MANAGER_HEADERS


# ======================================================================
# Rank 13 meeting-not-in-session outranks rank 43 reserve-too-low
# ======================================================================
def _unconvened_ratification_world(api: ApiClient):
    """A noticed budget whose reserve floor was raised, at an unconvened meeting.

    The budget's ``reserve_contribution_cents`` is exactly the statutory minimum
    at the default of 1000 basis points, so it passed the proposal gate; raising
    ``reserve_contribution_min_bp`` to 2000 afterwards makes it short by
    ratification time.  The clock is moved to the meeting's start but nobody
    convenes it, so both defects are live at once.
    """
    ctx = create_association(api, legal_name="Harborview Condominium Association")
    build_board(ctx)
    schedule_meeting(
        ctx,
        "mtg1",
        ["BUDGET_RATIFICATION"],
        "2026-09-05T18:00:00Z",
        "2026-09-05T21:00:00Z",
    )
    budget = draft_budget(
        ctx,
        fiscal_year=2026,
        operating_total_cents=12_000_000,
        reserve_contribution_cents=1_200_000,
        ratification_meeting_id=ctx.meetings["mtg1"],
    )
    get_success_data(ctx.api.propose_budget(budget["id"], MANAGER_HEADERS))
    get_success_data(ctx.api.send_budget_notice(budget["id"], MANAGER_HEADERS))
    get_success_data(
        ctx.api.update_association(
            ctx.association_id,
            {"reserve_contribution_min_bp": 2000},
            ctx.treasurer("tr"),
        )
    )
    set_clock(api, "2026-09-05T18:00:00Z")
    return ctx, budget


def test_unconvened_meeting_and_short_reserve_report_the_meeting_defect(
    api: ApiClient,
) -> None:
    """Rank 13 answers first even though the reserve floor is also breached.

    PRD 2.9: "Requests are validated in a single fixed order, and the **first**
    failing check determines the response. This ordering is normative: when two
    checks would both fail, the lower-numbered one wins, and a test that
    supplies two simultaneous defects expects the earlier error identifier."

    PRD 2.9: "13. The hosting board meeting is `IN_SESSION` when a ratification
    or a hearing decision is recorded -- otherwise `ERR_MEETING_NOT_IN_SESSION`,
    on budget ratification and hearing decision recording."

    Design: Difficulty/priority_pair_validation_conflict/state_p13_meeting_not_in_session_beats_business_fiscal_p43_reserve_too_low_on_ratify
    """
    ctx, budget = _unconvened_ratification_world(api)

    validate_error(
        ctx.api.ratify_budget(budget["id"], ctx.director("d1")),
        "ERR_MEETING_NOT_IN_SESSION",
        expected_status=409,
    )


def test_unconvened_ratification_does_not_report_the_absent_quorum(
    api: ApiClient,
) -> None:
    """Rank 13 also outranks rank 14, so quorum is never the reported defect.

    PRD 2.9: "because meeting session (rank 13) precedes quorum (rank 14), a
    decision recorded at a meeting that was never convened reports
    `ERR_MEETING_NOT_IN_SESSION` even though quorum is also absent."

    Design: Difficulty/priority_pair_validation_conflict/state_p13_meeting_not_in_session_beats_business_fiscal_p43_reserve_too_low_on_ratify
    """
    ctx, budget = _unconvened_ratification_world(api)
    assert read_meeting(api, ctx.meetings["mtg1"], MANAGER_HEADERS)["quorum_met"] is False

    response = ctx.api.ratify_budget(budget["id"], ctx.director("d1"))

    assert response.json()["data"]["error_id"] == "ERR_MEETING_NOT_IN_SESSION"


def test_rejected_ratification_leaves_the_budget_and_the_units_untouched(
    api: ApiClient,
) -> None:
    """A refused ratification is a no-op: no adoption, no allocation.

    PRD 3.2: "On `NOTICED → ADOPTED`, the server writes `no_weight_bp` and
    stamps `adopted_at` with the logical clock, then runs a five-hop cascade. Hop
    one computes the allocation snapshot and writes every unit's
    `monthly_assessment_cents`, advancing each `Unit.version` by 1."

    Design: Difficulty/priority_pair_validation_conflict/state_p13_meeting_not_in_session_beats_business_fiscal_p43_reserve_too_low_on_ratify
    """
    ctx, budget = _unconvened_ratification_world(api)

    validate_error(
        ctx.api.ratify_budget(budget["id"], ctx.director("d1")),
        "ERR_MEETING_NOT_IN_SESSION",
    )

    reread = read_budget(api, budget["id"], MANAGER_HEADERS)
    assert reread["status"] == "NOTICED"
    assert reread["adopted_at"] is None
    assert reread["allocation_snapshot"] == []
    assert ctx.unit("101")["monthly_assessment_cents"] == 0


def test_convening_the_meeting_exposes_the_short_reserve_contribution(
    api: ApiClient,
) -> None:
    """With rank 13 satisfied the ratification-time reserve re-check answers.

    PRD 3.2: "The reserve-contribution minimum is re-checked here as well,
    because the association's `reserve_contribution_min_bp` may have changed
    since the proposal."

    PRD 2.9: "43. The reserve contribution meets the statutory minimum share of
    the operating total -- otherwise `ERR_RESERVE_CONTRIBUTION_TOO_LOW`, on
    budget proposal and budget ratification."

    At 2000 basis points the floor is 2400000, so the proposal-time contribution
    of 1200000 no longer clears it.

    Design: Difficulty/priority_pair_validation_conflict/state_p13_meeting_not_in_session_beats_business_fiscal_p43_reserve_too_low_on_ratify
    """
    ctx, budget = _unconvened_ratification_world(api)

    session = convene(ctx, "mtg1", ("d1", "d2", "tr"))
    assert session["status"] == "IN_SESSION"
    assert session["seated_director_count"] == 3
    assert session["quorum_met"] is True

    validate_error(
        ctx.api.ratify_budget(budget["id"], ctx.director("d1")),
        "ERR_RESERVE_CONTRIBUTION_TOO_LOW",
        expected_status=422,
    )
    assert read_budget(api, budget["id"], MANAGER_HEADERS)["status"] == "NOTICED"


def test_ratification_adopts_once_both_defects_are_repaired(api: ApiClient) -> None:
    """Lowering the floor back to the default clears the last obstruction.

    PRD 3.2: "On `NOTICED → ADOPTED`, the server writes `no_weight_bp` and
    stamps `adopted_at` with the logical clock, then runs a five-hop cascade."

    The pool is round_half_up(13200000 / 12) == 1100000, which splits 3400 /
    3300 / 3300 basis points into 374000, 363000 and 363000.

    Design: Difficulty/priority_pair_validation_conflict/state_p13_meeting_not_in_session_beats_business_fiscal_p43_reserve_too_low_on_ratify
    """
    ctx, budget = _unconvened_ratification_world(api)
    convene(ctx, "mtg1", ("d1", "d2", "tr"))
    get_success_data(
        ctx.api.update_association(
            ctx.association_id,
            {"reserve_contribution_min_bp": 1000},
            ctx.treasurer("tr"),
        )
    )

    adopted = validate_success(ctx.api.ratify_budget(budget["id"], ctx.director("d1")))

    assert adopted["status"] == "ADOPTED"
    assert adopted["no_weight_bp"] == 0
    assert adopted["monthly_assessable_cents"] == 1_100_000
    assert_instant_equals(adopted["adopted_at"], "2026-09-05T18:00:00Z")
    assert ctx.unit("101")["monthly_assessment_cents"] == 374_000
    assert ctx.unit("102")["monthly_assessment_cents"] == 363_000
    assert ctx.unit("103")["monthly_assessment_cents"] == 363_000


# ======================================================================
# Rank 16 insurance-lapsed outranks rank 20 element-spec-changed
# ======================================================================
def _stale_pin_and_lapsed_cert_world(api: ApiClient):
    """A suspended contract whose certificate lapsed and whose award went stale.

    The roof award pinned ``CommonElement.version`` 1; a later revision of the
    component's effective age advances it to 2, and the certificate renewal
    lands before the clock is pushed past it.  The contract term still has
    months to run, so only the two intended defects are live.
    """
    ctx = create_association(api, legal_name="Kestrel Ridge Condominium Association")
    build_board(ctx)
    add_element(
        ctx,
        "roof",
        name="Main Roof Membrane",
        element_class="ROOF",
        replacement_cost_cents=9_000_000,
        useful_life_years=30,
        effective_age_years=10,
    )
    add_contract(
        ctx,
        "ct1",
        "roof",
        vendor_name="Ridgeline Roofing LLC",
        contract_cap_cents=5_000_000,
        insurance_cert_expires_at="2027-06-01T00:00:00Z",
        effective_from="2026-09-01T00:00:00Z",
        effective_to="2027-06-01T00:00:00Z",
    )
    schedule_meeting(
        ctx,
        "mtg_ca",
        ["CONTRACT_AWARD"],
        "2026-09-10T18:00:00Z",
        "2026-09-10T21:00:00Z",
    )
    notice_meeting(ctx, "mtg_ca")
    set_clock(api, "2026-09-10T18:00:00Z")
    convene(ctx, "mtg_ca", ("d1", "d2", "tr"))
    award_and_activate_contract(ctx, "ct1", "mtg_ca")

    order = add_work_order(
        ctx,
        "ct1",
        "roof",
        scope="Membrane seam recoating",
        window_start="2026-10-05T08:00:00Z",
        window_end="2026-10-07T18:00:00Z",
        estimated_cost_cents=1_200_000,
    )
    get_success_data(
        ctx.api.suspend_contract(
            ctx.contracts["ct1"], {"suspension_reason": "PERFORMANCE"}, MANAGER_HEADERS
        )
    )
    get_success_data(
        ctx.api.update_insurance_certificate(
            ctx.contracts["ct1"],
            {"insurance_cert_expires_at": "2026-12-01T00:00:00Z"},
            MANAGER_HEADERS,
        )
    )
    get_success_data(
        ctx.api.update_common_element(
            ctx.elements["roof"], {"effective_age_years": 12}, MANAGER_HEADERS
        )
    )
    set_clock(api, "2027-01-15T00:00:00Z")
    return ctx, order


def _renew_certificate(ctx) -> None:
    get_success_data(
        ctx.api.update_insurance_certificate(
            ctx.contracts["ct1"],
            {"insurance_cert_expires_at": "2027-06-01T00:00:00Z"},
            MANAGER_HEADERS,
        )
    )


def test_suspended_contract_holds_its_order_and_its_stale_pin(api: ApiClient) -> None:
    """Suspension parks the order without releasing a cent of the encumbrance.

    PRD 3.6: "every work order of that contract whose `status` is `SCHEDULED` or
    `IN_PROGRESS` becomes `ON_HOLD` with `hold_reason` set to
    `CONTRACT_SUSPENDED`, `encumbered_cents` is left untouched so
    `committed_cents` is unchanged, each such order's `version` advances by 1,
    and `VendorContract.version` advances by 1."

    Design: Difficulty/priority_pair_validation_conflict/business_safety_p16_insurance_lapsed_beats_business_referential_p20_element_spec_changed_on_reinstate
    """
    ctx, order = _stale_pin_and_lapsed_cert_world(api)

    contract = read_contract(api, ctx.contracts["ct1"], MANAGER_HEADERS)
    assert contract["status"] == "SUSPENDED"
    assert contract["suspension_reason"] == "PERFORMANCE"
    assert contract["committed_cents"] == 1_200_000
    assert contract["invoiced_cents"] == 0
    assert contract["pinned_element_version"] == 1
    assert read_element(api, ctx.elements["roof"], MANAGER_HEADERS)["version"] == 2

    held = read_work_order(api, order["id"], MANAGER_HEADERS)
    assert held["status"] == "ON_HOLD"
    assert held["hold_reason"] == "CONTRACT_SUSPENDED"
    assert held["encumbered_cents"] == 1_200_000


def test_lapsed_certificate_and_stale_pin_report_the_insurance_defect(
    api: ApiClient,
) -> None:
    """Rank 16 answers first even though the pinned element version also moved.

    PRD 2.9: "16. The vendor's certificate of insurance is still in force --
    otherwise `ERR_VENDOR_INSURANCE_LAPSED`, on work-order starting, contract
    activation, and contract reinstatement."

    PRD 2.9: "Requests are validated in a single fixed order, and the **first**
    failing check determines the response. This ordering is normative: when two
    checks would both fail, the lower-numbered one wins, and a test that
    supplies two simultaneous defects expects the earlier error identifier."

    Design: Difficulty/priority_pair_validation_conflict/business_safety_p16_insurance_lapsed_beats_business_referential_p20_element_spec_changed_on_reinstate
    """
    ctx, _ = _stale_pin_and_lapsed_cert_world(api)

    validate_error(
        ctx.api.reinstate_contract(ctx.contracts["ct1"], MANAGER_HEADERS),
        "ERR_VENDOR_INSURANCE_LAPSED",
        expected_status=409,
    )


def test_refused_reinstatement_leaves_the_contract_and_order_as_they_were(
    api: ApiClient,
) -> None:
    """Neither the suspension reason nor the held order moves on a refusal.

    PRD 3.6: "Reinstating moves `SUSPENDED → ACTIVE` and requires that
    `insurance_cert_expires_at` be strictly after the logical clock, that the
    logical clock be strictly before `effective_to`, and that the element's
    `version` still equal `pinned_element_version`; the effects are that
    `suspension_reason` returns to `NONE`, every work order of the contract whose
    `status` is `ON_HOLD` **and** whose `hold_reason` is `CONTRACT_SUSPENDED`
    returns to `SCHEDULED` with `hold_reason` set to `NONE` and its own `version`
    advanced by 1, and `VendorContract.version` advances by 1."

    Design: Difficulty/priority_pair_validation_conflict/business_safety_p16_insurance_lapsed_beats_business_referential_p20_element_spec_changed_on_reinstate
    """
    ctx, order = _stale_pin_and_lapsed_cert_world(api)

    validate_error(
        ctx.api.reinstate_contract(ctx.contracts["ct1"], MANAGER_HEADERS),
        "ERR_VENDOR_INSURANCE_LAPSED",
    )

    contract = read_contract(api, ctx.contracts["ct1"], MANAGER_HEADERS)
    assert contract["status"] == "SUSPENDED"
    assert contract["suspension_reason"] == "PERFORMANCE"
    assert read_work_order(api, order["id"], MANAGER_HEADERS)["status"] == "ON_HOLD"


def test_renewing_the_certificate_exposes_the_invalidated_board_award(
    api: ApiClient,
) -> None:
    """With rank 16 satisfied the stale pin becomes the reported defect.

    PRD 2.9: "20. The board's award is still valid because
    `CommonElement.version` equals `pinned_element_version` -- otherwise
    `ERR_ELEMENT_SPEC_CHANGED`, on contract activation and reinstatement."

    Design: Difficulty/priority_pair_validation_conflict/business_safety_p16_insurance_lapsed_beats_business_referential_p20_element_spec_changed_on_reinstate
    """
    ctx, _ = _stale_pin_and_lapsed_cert_world(api)

    _renew_certificate(ctx)

    validate_error(
        ctx.api.reinstate_contract(ctx.contracts["ct1"], MANAGER_HEADERS),
        "ERR_ELEMENT_SPEC_CHANGED",
        expected_status=409,
    )
    contract = read_contract(api, ctx.contracts["ct1"], MANAGER_HEADERS)
    assert contract["status"] == "SUSPENDED"
    assert contract["suspension_reason"] == "PERFORMANCE"


def test_a_further_element_revision_cannot_restore_the_pin(api: ApiClient) -> None:
    """Every revision moves the version further from the pinned figure.

    PRD 3.6: "A manager may revise a component's `replacement_cost_cents`,
    `useful_life_years`, `effective_age_years`, `status`, or
    `reserve_designated_cents`; every such revision advances
    `CommonElement.version` by 1, which -- as §3.6 explains below -- invalidates
    any board award that pinned the old version."

    Design: Difficulty/priority_pair_validation_conflict/business_safety_p16_insurance_lapsed_beats_business_referential_p20_element_spec_changed_on_reinstate
    """
    ctx, _ = _stale_pin_and_lapsed_cert_world(api)
    _renew_certificate(ctx)

    revised = get_success_data(
        ctx.api.update_common_element(
            ctx.elements["roof"], {"replacement_cost_cents": 9_500_000}, MANAGER_HEADERS
        )
    )
    assert revised["version"] == 3

    validate_error(
        ctx.api.reinstate_contract(ctx.contracts["ct1"], MANAGER_HEADERS),
        "ERR_ELEMENT_SPEC_CHANGED",
    )
    assert (
        read_contract(api, ctx.contracts["ct1"], MANAGER_HEADERS)[
            "pinned_element_version"
        ]
        == 1
    )


def test_termination_is_the_available_exit_from_the_doubly_blocked_suspension(
    api: ApiClient,
) -> None:
    """The board can still terminate, and the compensation releases the cap.

    PRD 3.6: "Both legs perform the same compensation: every work order whose
    `status` is `SCHEDULED` or `ON_HOLD` becomes `CANCELLED` with
    `encumbered_cents` set to 0, `committed_cents` is recomputed to equal the sum
    of `encumbered_cents` over the contract's non-cancelled orders as Invariant E
    requires, and `VendorContract.version` advances by 1."

    Design: Difficulty/priority_pair_validation_conflict/business_safety_p16_insurance_lapsed_beats_business_referential_p20_element_spec_changed_on_reinstate
    """
    ctx, order = _stale_pin_and_lapsed_cert_world(api)

    terminated = validate_success(
        ctx.api.terminate_contract(
            ctx.contracts["ct1"],
            ctx.director("d1"),
            payload={"reason": "Certificate lapsed and award invalidated"},
        )
    )

    assert terminated["status"] == "TERMINATED"
    assert terminated["committed_cents"] == 0
    cancelled = read_work_order(api, order["id"], MANAGER_HEADERS)
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["encumbered_cents"] == 0
