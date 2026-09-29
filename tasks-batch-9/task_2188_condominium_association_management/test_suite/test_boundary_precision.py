"""Single-unit boundaries where the inclusive edge and the truncation both bite.

The supermajority tally is probed one basis point either side of the statutory
threshold on a roster engineered so the share lands exactly on it; the invoice
overrun ceiling is probed one cent either side of a floor whose fractional part
is 0.7, which a rounding implementation would round the wrong way.
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
    assert_contract_authorization_conserved,
    read_contract,
    read_element,
    read_special_assessment,
    read_work_order,
)
from test_helpers.fixtures import (
    add_contract,
    add_element,
    add_owner,
    add_unit,
    add_work_order,
    award_and_activate_contract,
    build_board,
    cast_owner_ballots,
    convene,
    create_association,
    notice_meeting,
    open_special_assessment,
    patch_association,
    post_charge,
    schedule_meeting,
    set_clock,
)
from test_helpers.test_users import MANAGER_HEADERS


# ======================================================================
# The supermajority threshold: 6666 fails, 6667 approves
# ======================================================================
def _alder_point(api: ApiClient):
    """A roster of 3333 / 3333 / 3333 / 1 basis points summing to exactly 10000.

    The one-basis-point storage unit is what makes a yes weight of 6666 and one
    of 6667 both reachable on the same roster.
    """
    ctx = create_association(api, legal_name="Alder Point Condominium Association")
    add_owner(ctx, "d1", full_name="Dana Reyes", board_role="PRESIDENT", is_seated=True)
    add_owner(ctx, "d2", full_name="Elliot Shaw", board_role="DIRECTOR", is_seated=True)
    add_owner(ctx, "tr", full_name="Priya Nandan", board_role="TREASURER", is_seated=True)
    add_owner(ctx, "oa", full_name="Owner A")
    add_owner(ctx, "ob", full_name="Owner B")
    add_owner(ctx, "oc", full_name="Owner C")
    add_owner(ctx, "od", full_name="Owner D")
    add_unit(ctx, "A", "oa", 3333, 1200)
    add_unit(ctx, "B", "ob", 3333, 1200)
    add_unit(ctx, "C", "oc", 3333, 1200)
    add_unit(ctx, "S1", "od", 1, 60)
    return ctx


def _tally(ctx, *, total_amount_cents: int, ballots, purpose: str):
    assessment = open_special_assessment(
        ctx, total_amount_cents=total_amount_cents, installment_count=4, purpose=purpose
    )
    cast = cast_owner_ballots(ctx, "SPECIAL_ASSESSMENT", assessment["id"], ballots)
    closed = validate_success(
        ctx.api.close_ballot(assessment["id"], ctx.director("d1"))
    )
    return assessment, cast, closed


def test_yes_share_one_basis_point_short_of_the_threshold_fails_the_ballot(
    api: ApiClient,
) -> None:
    """6666 basis points of yes weight out of 10000 is a failure, not an approval.

    PRD 3.4: "Otherwise the yes share in basis points is `yes_weight_bp`
    multiplied by 10000, divided by `eligible_weight_bp`, and floored; the
    assessment is approved when that share is greater than or equal to
    `special_assessment_approval_bp`."

    PRD 3.4: "With the default two-thirds-plus threshold of 6667 basis points, a
    yes share of exactly 6667 approves and 6666 fails."

    Design: Difficulty/boundary_precision_check/sa_tally_yes_share_bp_6666_rejects_6667_approves_and_floor_beats_round_half_up
    """
    ctx = _alder_point(api)

    _, _, closed = _tally(
        ctx,
        total_amount_cents=800_000,
        ballots=(
            ("oa", "A", "YES"),
            ("ob", "B", "YES"),
            ("oc", "C", "NO"),
            ("od", "S1", "ABSTAIN"),
        ),
        purpose="Ballot A - elevator modernization",
    )

    assert closed["approval_status"] == "FAILED"
    assert closed["eligible_weight_bp"] == 10_000
    assert closed["yes_weight_bp"] == 6_666
    assert_instant_equals(closed["ballot_closed_at"], "2026-08-01T00:00:00Z")
    assert closed["funding_status"] == "UNFUNDED"


def test_failed_ballot_designates_no_reserve_cash(api: ApiClient) -> None:
    """The failure branch writes the tally fields and touches no money.

    PRD 3.4: "On `BALLOTING → FAILED`, the server writes the same three fields —
    `eligible_weight_bp`, `yes_weight_bp`, and `ballot_closed_at` — does **not**
    change `reserve_designated_cents`, and advances `SpecialAssessment.version`
    by 1."

    Design: Difficulty/boundary_precision_check/sa_tally_yes_share_bp_6666_rejects_6667_approves_and_floor_beats_round_half_up
    """
    ctx = _alder_point(api)

    _tally(
        ctx,
        total_amount_cents=800_000,
        ballots=(
            ("oa", "A", "YES"),
            ("ob", "B", "YES"),
            ("oc", "C", "NO"),
            ("od", "S1", "ABSTAIN"),
        ),
        purpose="Ballot A - elevator modernization",
    )

    assert ctx.association()["reserve_designated_cents"] == 0


def test_abstain_ballot_is_counted_yet_adds_nothing_to_the_yes_weight(
    api: ApiClient,
) -> None:
    """The storage unit's single basis point stays in the denominator regardless.

    PRD 3.4: "`yes_weight_bp` is the sum of `weight_bp` over the counted ballots
    whose `choice` is `YES`; `ABSTAIN` ballots add nothing to the numerator and do
    not leave the denominator."

    Design: Difficulty/boundary_precision_check/sa_tally_yes_share_bp_6666_rejects_6667_approves_and_floor_beats_round_half_up
    """
    ctx = _alder_point(api)

    _, cast, closed = _tally(
        ctx,
        total_amount_cents=800_000,
        ballots=(
            ("oa", "A", "YES"),
            ("ob", "B", "YES"),
            ("oc", "C", "NO"),
            ("od", "S1", "ABSTAIN"),
        ),
        purpose="Ballot A - elevator modernization",
    )

    abstention = cast[-1]
    assert abstention["choice"] == "ABSTAIN"
    assert abstention["weight_bp"] == 1
    assert abstention["counted"] is True
    assert closed["eligible_weight_bp"] == 10_000
    assert closed["yes_weight_bp"] == 6_666


def test_yes_share_exactly_at_the_threshold_approves_the_assessment(
    api: ApiClient,
) -> None:
    """Swinging the one-basis-point unit to YES carries the ballot at 6667.

    PRD 3.4: "With the default two-thirds-plus threshold of 6667 basis points, a
    yes share of exactly 6667 approves and 6666 fails."

    Design: Difficulty/boundary_precision_check/sa_tally_yes_share_bp_6666_rejects_6667_approves_and_floor_beats_round_half_up
    """
    ctx = _alder_point(api)

    _, _, closed = _tally(
        ctx,
        total_amount_cents=1_000_000,
        ballots=(
            ("oa", "A", "YES"),
            ("ob", "B", "YES"),
            ("od", "S1", "YES"),
            ("oc", "C", "NO"),
        ),
        purpose="Ballot B - elevator modernization",
    )

    assert closed["approval_status"] == "APPROVED"
    assert closed["eligible_weight_bp"] == 10_000
    assert closed["yes_weight_bp"] == 6_667
    assert closed["funding_status"] == "UNFUNDED"


def test_approved_ballot_designates_the_whole_assessment_in_reserves(
    api: ApiClient,
) -> None:
    """The approval branch is the only one with a fiscal side effect.

    PRD 3.4: "On `BALLOTING → APPROVED`, the server writes `eligible_weight_bp`,
    `yes_weight_bp`, and `ballot_closed_at` from the logical clock, increases the
    association's `reserve_designated_cents` by `total_amount_cents` and advances
    `Association.version` by 1, leaves `funding_status` untouched at `UNFUNDED`,
    and advances `SpecialAssessment.version` by 1."

    Design: Difficulty/boundary_precision_check/sa_tally_yes_share_bp_6666_rejects_6667_approves_and_floor_beats_round_half_up
    """
    ctx = _alder_point(api)

    _tally(
        ctx,
        total_amount_cents=1_000_000,
        ballots=(
            ("oa", "A", "YES"),
            ("ob", "B", "YES"),
            ("od", "S1", "YES"),
            ("oc", "C", "NO"),
        ),
        purpose="Ballot B - elevator modernization",
    )

    assert ctx.association()["reserve_designated_cents"] == 1_000_000


def test_ineligible_unit_leaves_the_denominator_so_6666_now_carries(
    api: ApiClient,
) -> None:
    """The same 6666 yes weight approves once the denominator drops to 6667.

    PRD 3.4: "`eligible_weight_bp` is the sum of `interest_bp` over every unit of
    the association whose `voting_eligible` is true, so a unit that never cast a
    ballot still sits in the denominator."

    Unit C is on the lien rung at tally time, so the denominator is 3333 + 3333 +
    1 rather than 10000 and the unchanged 6666 of yes weight now clears 6667.

    Design: Difficulty/boundary_precision_check/sa_tally_yes_share_bp_6666_rejects_6667_approves_and_floor_beats_round_half_up
    """
    ctx = _alder_point(api)
    set_clock(api, "2026-10-18T00:00:00Z")
    post_charge(
        ctx,
        "C",
        entry_type="COLLECTION_COST",
        amount_cents=200_000,
        due_on="2026-04-01T00:00:00Z",
        effective_period="2026-04",
        memo="collection costs advanced",
    )
    assert ctx.unit("C")["delinquency_stage"] == "LIEN_FILED"
    assert ctx.unit("C")["voting_eligible"] is False

    _, _, closed = _tally(
        ctx,
        total_amount_cents=1_200_000,
        ballots=(("oa", "A", "YES"), ("ob", "B", "YES")),
        purpose="Ballot C - elevator modernization",
    )

    assert closed["eligible_weight_bp"] == 6_667
    assert closed["yes_weight_bp"] == 6_666
    assert closed["approval_status"] == "APPROVED"
    assert ctx.association()["reserve_designated_cents"] == 1_200_000


def test_an_empty_electorate_is_refused_rather_than_tallied_as_a_failure(
    api: ApiClient,
) -> None:
    """A zero denominator is its own error, distinct from the 6666 failure.

    PRD 3.4: "If `eligible_weight_bp` is 0 — every unit having escalated to
    `LIEN_FILED` or `FORECLOSURE_REFERRAL` — the close is rejected with
    `ERR_NO_ELIGIBLE_VOTERS` rather than being treated as a failure."

    Design: Difficulty/boundary_precision_check/sa_tally_yes_share_bp_6666_rejects_6667_approves_and_floor_beats_round_half_up
    """
    ctx = create_association(api, legal_name="Marsh Lane Condominium Association")
    add_owner(ctx, "d1", full_name="Dana Reyes", board_role="PRESIDENT", is_seated=True)
    add_owner(ctx, "tr", full_name="Priya Nandan", board_role="TREASURER", is_seated=True)
    add_owner(ctx, "oa", full_name="Owner A")
    add_unit(ctx, "A", "oa", 10_000, 1200)
    assessment = open_special_assessment(
        ctx, total_amount_cents=500_000, installment_count=2, purpose="Sole-unit ballot"
    )
    set_clock(api, "2026-10-18T00:00:00Z")
    post_charge(
        ctx,
        "A",
        entry_type="COLLECTION_COST",
        amount_cents=200_000,
        due_on="2026-04-01T00:00:00Z",
        effective_period="2026-04",
        memo="collection costs advanced",
    )
    assert ctx.unit("A")["voting_eligible"] is False

    validate_error(
        ctx.api.close_ballot(assessment["id"], ctx.director("d1")),
        "ERR_NO_ELIGIBLE_VOTERS",
        expected_status=409,
    )
    assert (
        read_special_assessment(api, assessment["id"], MANAGER_HEADERS)[
            "approval_status"
        ]
        == "BALLOTING"
    )


# ======================================================================
# The overrun ceiling: floor(1234567 * 11 / 10) == 1358023
# ======================================================================
def _completed_order_world(api: ApiClient):
    """A completed roof order estimated at 1234567 cents, awaiting its invoice.

    Operating cash of 2000000 and a cap of 5000000 both comfortably cover a
    final cost of 1358024, so neither the cap gate nor the cash gate can be
    responsible for a refusal at that figure.
    """
    ctx = create_association(api, legal_name="Larkspur Terrace Condominium Association")
    patch_association(ctx, operating_cash_cents=2_000_000)
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
        vendor_name="Meridian Roofing LLC",
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
        scope="Membrane recoat",
        window_start="2026-10-05T08:00:00Z",
        window_end="2026-10-07T18:00:00Z",
        estimated_cost_cents=1_234_567,
    )
    set_clock(api, "2026-10-05T08:00:00Z")
    get_success_data(ctx.api.start_work_order(order["id"], MANAGER_HEADERS))
    set_clock(api, "2026-10-07T20:00:00Z")
    completed = get_success_data(
        ctx.api.complete_work_order(
            order["id"], MANAGER_HEADERS, payload={"resets_component": False}
        )
    )
    return ctx, completed


def test_completed_order_baseline_still_holds_its_whole_estimate(
    api: ApiClient,
) -> None:
    """Completion returns the element to service without releasing the money.

    PRD 3.6: "Completing work moves it `IN_PROGRESS → COMPLETED`, requires that
    the logical clock have reached `window_start`, drives the element's `status`
    to `SERVICEABLE`, stamps the element's `last_serviced_at` with the logical
    clock, and — when the payload sets the optional `resets_component` flag to
    true — resets the element's `effective_age_years` to 0, which changes the
    fully-funded basis used by the reserve computation below; both
    `CommonElement.version` and `MaintenanceWorkOrder.version` advance by 1."

    Design: Difficulty/boundary_precision_check/invoice_overrun_ceiling_floor_1358023_accepts_1358024_rejects
    """
    ctx, order = _completed_order_world(api)

    assert order["status"] == "COMPLETED"
    assert order["encumbered_cents"] == 1_234_567
    contract = read_contract(api, ctx.contracts["ct1"], MANAGER_HEADERS)
    assert contract["committed_cents"] == 1_234_567
    assert contract["invoiced_cents"] == 0
    assert ctx.association()["operating_cash_cents"] == 2_000_000
    element = read_element(api, ctx.elements["roof"], MANAGER_HEADERS)
    assert element["status"] == "SERVICEABLE"
    assert element["effective_age_years"] == 10


def test_one_cent_above_the_floored_ceiling_is_refused(api: ApiClient) -> None:
    """1358024 is exactly one cent past floor(1234567 * 11 / 10).

    PRD 3.6: "The overrun tolerance admits a `final_cost_cents` no greater than
    `estimated_cost_cents` multiplied by 11 and divided by 10 with the result
    floored — a ten percent overrun, inclusive of the boundary — and the sum of
    the contract's `invoiced_cents` and `final_cost_cents` must not exceed
    `contract_cap_cents`; either failure yields `ERR_INVOICE_EXCEEDS_TOLERANCE`."

    13580237 divided by 10 truncates to 1358023, so an implementation that
    rounds half up to 1358024 -- or multiplies by 1.1 in floating point --
    wrongly accepts this figure.

    Design: Difficulty/boundary_precision_check/invoice_overrun_ceiling_floor_1358023_accepts_1358024_rejects
    """
    ctx, order = _completed_order_world(api)

    validate_error(
        ctx.api.invoice_work_order(
            order["id"], {"final_cost_cents": 1_358_024}, MANAGER_HEADERS
        ),
        "ERR_INVOICE_EXCEEDS_TOLERANCE",
        expected_status=409,
    )


def test_the_refused_invoice_is_not_the_cap_or_the_cash_gate(api: ApiClient) -> None:
    """Both other fiscal gates on this endpoint pass at 1358024.

    PRD 3.6: "Separately, the association's `operating_cash_cents` must be at
    least `final_cost_cents`, or the response is
    `ERR_INSUFFICIENT_OPERATING_CASH`."

    The cap leaves 5000000 of authorization against a 1358024 invoice and cash on
    hand is 2000000, so only the overrun ceiling can be refusing the request.

    Design: Difficulty/boundary_precision_check/invoice_overrun_ceiling_floor_1358023_accepts_1358024_rejects
    """
    ctx, order = _completed_order_world(api)

    response = ctx.api.invoice_work_order(
        order["id"], {"final_cost_cents": 1_358_024}, MANAGER_HEADERS
    )

    assert response.json()["data"]["error_id"] == "ERR_INVOICE_EXCEEDS_TOLERANCE"
    contract = read_contract(api, ctx.contracts["ct1"], MANAGER_HEADERS)
    assert contract["contract_cap_cents"] == 5_000_000
    assert contract["invoiced_cents"] == 0
    assert ctx.association()["operating_cash_cents"] == 2_000_000


def test_the_refused_invoice_leaves_the_order_completed_and_encumbered(
    api: ApiClient,
) -> None:
    """A refusal releases nothing, so the order can still be invoiced correctly.

    PRD 3.6: "On success `encumbered_cents` becomes 0, the contract's
    `committed_cents` falls by `estimated_cost_cents` while its `invoiced_cents`
    rises by `final_cost_cents` with `VendorContract.version` advancing by 1, the
    association's `operating_cash_cents` falls by `final_cost_cents` with
    `Association.version` advancing by 1, and `MaintenanceWorkOrder.version`
    advances by 1."

    Design: Difficulty/boundary_precision_check/invoice_overrun_ceiling_floor_1358023_accepts_1358024_rejects
    """
    ctx, order = _completed_order_world(api)

    validate_error(
        ctx.api.invoice_work_order(
            order["id"], {"final_cost_cents": 1_358_024}, MANAGER_HEADERS
        ),
        "ERR_INVOICE_EXCEEDS_TOLERANCE",
    )

    reread = read_work_order(api, order["id"], MANAGER_HEADERS)
    assert reread["status"] == "COMPLETED"
    assert reread["encumbered_cents"] == 1_234_567
    assert reread["final_cost_cents"] is None


def test_exactly_the_floored_ceiling_is_admitted(api: ApiClient) -> None:
    """The bound is inclusive, so the truncated ceiling itself must be accepted.

    PRD 3.6: "The overrun tolerance admits a `final_cost_cents` no greater than
    `estimated_cost_cents` multiplied by 11 and divided by 10 with the result
    floored — a ten percent overrun, inclusive of the boundary — and the sum of
    the contract's `invoiced_cents` and `final_cost_cents` must not exceed
    `contract_cap_cents`; either failure yields `ERR_INVOICE_EXCEEDS_TOLERANCE`."

    Design: Difficulty/boundary_precision_check/invoice_overrun_ceiling_floor_1358023_accepts_1358024_rejects
    """
    ctx, order = _completed_order_world(api)

    invoiced = validate_success(
        ctx.api.invoice_work_order(
            order["id"], {"final_cost_cents": 1_358_023}, MANAGER_HEADERS
        )
    )

    assert invoiced["status"] == "INVOICED"
    assert invoiced["final_cost_cents"] == 1_358_023
    assert invoiced["encumbered_cents"] == 0
    contract = read_contract(api, ctx.contracts["ct1"], MANAGER_HEADERS)
    assert contract["committed_cents"] == 0
    assert contract["invoiced_cents"] == 1_358_023
    assert ctx.association()["operating_cash_cents"] == 641_977
    assert (
        assert_contract_authorization_conserved(
            api, ctx.contracts["ct1"], MANAGER_HEADERS
        )
        == 0
    )


def test_one_cent_below_the_ceiling_is_admitted_too(api: ApiClient) -> None:
    """The accept path is not an off-by-one: 1358022 passes as well.

    PRD 3.6: "Invoicing moves a completed order `COMPLETED → INVOICED` and may be
    recorded by a `CommunityManager` or a `BoardTreasurer` supplying
    `final_cost_cents`."

    Design: Difficulty/boundary_precision_check/invoice_overrun_ceiling_floor_1358023_accepts_1358024_rejects
    """
    ctx, order = _completed_order_world(api)

    invoiced = validate_success(
        ctx.api.invoice_work_order(
            order["id"], {"final_cost_cents": 1_358_022}, MANAGER_HEADERS
        )
    )

    assert invoiced["status"] == "INVOICED"
    assert invoiced["final_cost_cents"] == 1_358_022
    assert ctx.association()["operating_cash_cents"] == 641_978
