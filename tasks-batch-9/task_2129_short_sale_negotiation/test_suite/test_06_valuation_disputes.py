"""Filing value disputes, the three adjudication branches, and the five-hop chain
that a moved value fires across the file."""

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    adjudicate_payload,
    assert_valuation_dispute,
    file_dispute_payload,
    setup_letter_with_extension_request,
    setup_open_dispute,
    setup_recorded_valuation,
    validate_error,
    validate_success,
)

NEG = TEST_USERS["negotiator_headers"]
ANALYST = TEST_USERS["servicer_analyst_headers"]
ANALYST2 = TEST_USERS["second_analyst_headers"]


def test_variance_below_five_percent_is_refused(api):
    """PRD §3.6: "The variance must be **at least `0.05`** — a disagreement of less than
    five percent is not worth the servicer's time and is refused with
    `ERR_DISPUTE_VARIANCE_TOO_SMALL`; a variance of exactly `0.05` is admissible."

    Design: Corner/validations/dispute_variance_below_minimum_rejected
    """
    scenario = setup_recorded_valuation(clock="2026-08-06T00:00:00Z")
    valuation_id = scenario["valuation"]["id"]

    # |26_000_000 - 25_200_000| / 25_200_000 rounds to 0.0317.
    validate_error(
        api.file_dispute(
            valuation_id,
            file_dispute_payload(26_000_000, 5, rationale="Marginally higher comps"),
            NEG,
        ),
        ApiErrorId.ERR_DISPUTE_VARIANCE_TOO_SMALL.value,
    )

    stored = validate_success(api.get_valuation(valuation_id, ANALYST), 200)
    assert stored["status"] == "RECEIVED"
    disputes = validate_success(api.list_valuation_disputes(valuation_id, ANALYST), 200)
    assert len(disputes) == 0


def test_evidence_below_three_comparables_is_refused(api):
    """PRD §3.6: "Then the evidence must be sufficient: **at least 3** comparable sales,
    or the filing is refused with `ERR_DISPUTE_EVIDENCE_INSUFFICIENT`. Because the
    variance test runs first, a filing that fails both is reported as a variance
    failure."

    Design: Corner/validations/dispute_evidence_below_minimum_comparables_rejected
    """
    scenario = setup_recorded_valuation(clock="2026-08-06T00:00:00Z")
    valuation_id = scenario["valuation"]["id"]

    # The variance clears at 0.0714, so only the evidence floor can refuse this.
    validate_error(
        api.file_dispute(
            valuation_id,
            file_dispute_payload(27_000_000, 2, rationale="Only two comps available"),
            NEG,
        ),
        ApiErrorId.ERR_DISPUTE_EVIDENCE_INSUFFICIENT.value,
    )

    stored = validate_success(api.get_valuation(valuation_id, ANALYST), 200)
    assert stored["status"] == "RECEIVED"
    disputes = validate_success(api.list_valuation_disputes(valuation_id, ANALYST), 200)
    assert len(disputes) == 0


def test_partial_resolution_rounds_the_midpoint_half_up(api):
    """PRD §3.6: "**`PARTIAL`** splits the difference: `resolved_value_cents` becomes the
    average of the claimed value and the valuation's current recorded value — their sum
    divided by two, rounded half up to whole cents — and the valuation likewise moves
    from `DISPUTED` to `REVISED` carrying that value."
    PRD §3.6: "Filing stamps `filed_by_user_id` and computes `variance_pct`: take the
    absolute difference between the claimed value and the valuation's current recorded
    value, divide it by that recorded value, and round half up to **four** decimal
    places."

    Design: Corner/calculations/dispute_partial_resolution_uses_rounded_midpoint
    """
    scenario = setup_open_dispute(
        clock="2026-08-06T00:00:00Z",
        claimed_value_cents=27_000_001,
        comparable_count=4,
        filer_headers=NEG,
    )

    resolved = validate_success(
        api.adjudicate_dispute(
            scenario["dispute"]["id"], adjudicate_payload("PARTIAL"), ANALYST2
        ),
        200,
    )

    assert resolved["status"] == "PARTIAL"
    # (27_000_001 + 25_200_000) / 2 == 26_100_000.5, which rounds half up.
    assert resolved["resolved_value_cents"] == 26_100_001
    assert resolved["variance_pct"] == pytest.approx(0.0714)
    assert_valuation_dispute(resolved)

    valuation = validate_success(api.get_valuation(scenario["valuation"]["id"], ANALYST), 200)
    assert valuation["value_cents"] == 26_100_001
    assert valuation["status"] == "REVISED"

    case_after = validate_success(api.get_case(scenario["case"]["id"], ANALYST), 200)
    assert case_after["final_value_cents"] == 26_100_001
    assert case_after["minimum_acceptable_net_cents"] == 22_968_001


def test_adjudicating_a_resolved_dispute_is_refused(api):
    """PRD §3.6: "A `ServicerAnalyst` other than the one who ordered the valuation
    adjudicates an `OPEN` dispute by supplying a `resolution` of `SUSTAINED`, `PARTIAL`
    or `DENIED`, optionally with a `note`; adjudicating a dispute that is not `OPEN` is
    refused with `ERR_DISPUTE_NOT_OPEN`."

    Design: Corner/state_machines/adjudicate_dispute_twice_second_returns_dispute_not_open
    """
    scenario = setup_open_dispute(clock="2026-08-06T00:00:00Z")
    dispute_id = scenario["dispute"]["id"]
    validate_success(
        api.adjudicate_dispute(dispute_id, adjudicate_payload("PARTIAL"), ANALYST2), 200
    )

    validate_error(
        api.adjudicate_dispute(dispute_id, adjudicate_payload("SUSTAINED"), ANALYST2),
        ApiErrorId.ERR_DISPUTE_NOT_OPEN.value,
    )

    disputes = validate_success(
        api.list_valuation_disputes(scenario["valuation"]["id"], ANALYST), 200
    )
    assert disputes[0]["status"] == "PARTIAL"
    assert disputes[0]["resolved_value_cents"] == 26_100_000

    valuation = validate_success(api.get_valuation(scenario["valuation"]["id"], ANALYST), 200)
    assert valuation["value_cents"] == 26_100_000, (
        "the refused second adjudication must not move the value again"
    )


def test_a_final_valuation_admits_no_further_dispute(api):
    """PRD §3.6: "Either a `Negotiator` or a `ServicerAnalyst` may file a dispute against
    a valuation whose status is `RECEIVED` or `REVISED`; a dispute filed against a
    valuation in any other status — including one already locked — is refused with
    `ERR_VALUATION_NOT_ACTIONABLE`."
    PRD §3.6: "A `FINAL` valuation is locked — no further dispute may ever be filed
    against it — and because the value did not move, the case's `final_value_cents` and
    `minimum_acceptable_net_cents` are not recomputed and nothing downstream is
    disturbed."

    Design: Corner/state_machines/denied_dispute_locks_valuation_against_a_new_dispute
    """
    scenario = setup_open_dispute(clock="2026-08-06T00:00:00Z")
    validate_success(
        api.adjudicate_dispute(
            scenario["dispute"]["id"], adjudicate_payload("DENIED"), ANALYST2
        ),
        200,
    )

    validate_error(
        api.file_dispute(
            scenario["valuation"]["id"],
            file_dispute_payload(22_000_000, 5, rationale="Second opinion"),
            NEG,
        ),
        ApiErrorId.ERR_VALUATION_NOT_ACTIONABLE.value,
    )

    valuation = validate_success(api.get_valuation(scenario["valuation"]["id"], ANALYST), 200)
    assert valuation["status"] == "FINAL"
    assert valuation["value_cents"] == 25_200_000

    disputes = validate_success(
        api.list_valuation_disputes(scenario["valuation"]["id"], ANALYST), 200
    )
    assert len(disputes) == 1, "the refused filing must not be persisted"


def test_denied_branch_locks_the_valuation_without_moving_the_value(api):
    """PRD §3.6: "**`DENIED`** keeps the original: `resolved_value_cents` is set equal to
    the valuation's existing `value_cents`, which is itself left untouched, and the
    valuation moves from `DISPUTED` to the terminal `FINAL`."

    Design: Difficulty/non_linear_state_machine/dispute_denied_branch_locks_valuation_and_leaves_value_untouched
    """
    scenario = setup_open_dispute(
        clock="2026-08-06T00:00:00Z", claimed_value_cents=27_000_000, comparable_count=4,
        filer_headers=ANALYST2,
    )
    assert scenario["valuation"]["status"] == "DISPUTED"

    resolved = validate_success(
        api.adjudicate_dispute(
            scenario["dispute"]["id"],
            adjudicate_payload("DENIED", note="Comps not adjusted for lot size"),
            ANALYST2,
        ),
        200,
    )

    assert resolved["status"] == "DENIED"
    assert resolved["resolved_value_cents"] == 25_200_000
    assert resolved["variance_pct"] == pytest.approx(0.0714)

    valuation = validate_success(api.get_valuation(scenario["valuation"]["id"], ANALYST), 200)
    assert valuation["status"] == "FINAL"
    assert valuation["value_cents"] == 25_200_000


def test_denied_branch_leaves_the_case_floor_undisturbed(api):
    """PRD §3.6: "**`DENIED`** keeps the original: `resolved_value_cents` is set equal to
    the valuation's existing `value_cents`, which is itself left untouched, and the
    valuation moves from `DISPUTED` to the terminal `FINAL`. A `FINAL` valuation is
    locked — no further dispute may ever be filed against it — and because the value did
    not move, the case's `final_value_cents` and `minimum_acceptable_net_cents` are not
    recomputed and nothing downstream is disturbed."

    Design: Difficulty/non_linear_state_machine/dispute_denied_branch_locks_valuation_and_leaves_value_untouched
    """
    scenario = setup_open_dispute(
        clock="2026-08-06T00:00:00Z", claimed_value_cents=27_000_000, comparable_count=4,
        filer_headers=ANALYST2,
    )
    before = validate_success(api.get_case(scenario["case"]["id"], ANALYST), 200)
    assert before["final_value_cents"] == 25_200_000
    assert before["minimum_acceptable_net_cents"] == 22_176_000

    validate_success(
        api.adjudicate_dispute(
            scenario["dispute"]["id"], adjudicate_payload("DENIED"), ANALYST2
        ),
        200,
    )

    after = validate_success(api.get_case(scenario["case"]["id"], ANALYST), 200)
    assert after["final_value_cents"] == 25_200_000
    assert after["minimum_acceptable_net_cents"] == 22_176_000, (
        "a denied dispute recomputes nothing on the case"
    )


def test_the_ordering_analyst_may_not_adjudicate_the_dispute(api):
    """PRD §2.10: "The analyst who ordered a valuation — recorded as `ordered_by_user_id`
    when the order was placed — is permanently barred from adjudicating any dispute filed
    against that valuation."
    PRD §2.10: "Either violation is refused with `ERR_SEGREGATION_OF_DUTIES` and HTTP
    403."

    Design: Corner/rbac/ordering_analyst_cannot_adjudicate_own_valuation_dispute
    """
    scenario = setup_open_dispute(clock="2026-08-06T00:00:00Z", filer_headers=NEG)

    # The valuation was ordered by sa-100, so sa-100 is barred here.
    validate_error(
        api.adjudicate_dispute(
            scenario["dispute"]["id"], adjudicate_payload("SUSTAINED"), ANALYST
        ),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value,
    )

    disputes = validate_success(
        api.list_valuation_disputes(scenario["valuation"]["id"], ANALYST), 200
    )
    assert disputes[0]["status"] == "OPEN"
    assert disputes[0]["adjudicated_by_user_id"] is None

    valuation = validate_success(api.get_valuation(scenario["valuation"]["id"], ANALYST), 200)
    assert valuation["value_cents"] == 25_200_000
    assert valuation["status"] == "DISPUTED"


def test_sustained_dispute_rewrites_the_value_and_the_case_floor(api):
    """PRD §3.6: "**`SUSTAINED`** adopts the filer's number outright:
    `resolved_value_cents` becomes the `claimed_value_cents`, and the valuation moves
    from `DISPUTED` to `REVISED` carrying that value."
    PRD §3.6: "Hop three, caused by hop two, recomputes the case's `final_value_cents`
    and `minimum_acceptable_net_cents` from the new controlling valuation."

    Design: Difficulty/transitive_cascade/dispute_sustained_voids_underwater_approval_and_cancels_extensions
    """
    scenario = setup_letter_with_extension_request()
    case_id = scenario["case"]["id"]
    before = validate_success(api.get_case(case_id, ANALYST), 200)
    assert before["minimum_acceptable_net_cents"] == 21_426_000

    dispute = validate_success(
        api.file_dispute(
            scenario["valuation"]["id"],
            file_dispute_payload(
                27_000_000, 4,
                rationale="Post-BPO closed comps support a higher value",
            ),
            ANALYST2,
        ),
        201,
    )
    resolved = validate_success(
        api.adjudicate_dispute(dispute["id"], adjudicate_payload("SUSTAINED"), ANALYST2), 200
    )

    assert resolved["status"] == "SUSTAINED"
    assert resolved["resolved_value_cents"] == 27_000_000

    valuation = validate_success(api.get_valuation(scenario["valuation"]["id"], ANALYST), 200)
    assert valuation["status"] == "REVISED"
    assert valuation["value_cents"] == 27_000_000

    case_after = validate_success(api.get_case(case_id, ANALYST), 200)
    assert case_after["final_value_cents"] == 27_000_000
    # 27_000_000 * 0.88 = 23_760_000, less the 750_000 approved MI contribution.
    assert case_after["minimum_acceptable_net_cents"] == 23_010_000


def test_sustained_dispute_voids_the_underwater_letter_and_cancels_its_extensions(api):
    """PRD §3.6: "Hop four, caused by hop three, examines every approval letter on the
    case whose status is `ACTIVE`: any letter whose `approved_net_proceeds_cents` is now
    strictly below the newly computed `minimum_acceptable_net_cents` is under water and
    moves from `ACTIVE` to `VOIDED`."
    PRD §3.6: "Hop five, caused by hop four, cleans up behind the voided letter — every
    extension request against it whose status is `REQUESTED` moves to `CANCELLED` — and,
    where the voided letter was the case's only active one, carries the case's
    negotiation dimension from `APPROVAL_ACTIVE` back to `RENEGOTIATION`, returning the
    file to the negotiating table with its offers still intact."

    Design: Difficulty/transitive_cascade/dispute_sustained_voids_underwater_approval_and_cancels_extensions
    """
    scenario = setup_letter_with_extension_request()
    letter = scenario["letter"]
    assert letter["status"] == "ACTIVE"
    assert letter["approved_net_proceeds_cents"] == 22_122_539

    dispute = validate_success(
        api.file_dispute(
            scenario["valuation"]["id"],
            file_dispute_payload(
                27_000_000, 4,
                rationale="Post-BPO closed comps support a higher value",
            ),
            ANALYST2,
        ),
        201,
    )
    validate_success(
        api.adjudicate_dispute(dispute["id"], adjudicate_payload("SUSTAINED"), ANALYST2), 200
    )

    letter_after = validate_success(api.get_approval_letter(letter["id"], ANALYST), 200)
    assert letter_after["status"] == "VOIDED"
    assert letter_after["approved_net_proceeds_cents"] == 22_122_539, (
        "only the status moves; the committed net is left as issued"
    )

    extensions = validate_success(
        api.list_letter_extension_requests(letter["id"], ANALYST), 200
    )
    assert extensions[0]["id"] == scenario["extension"]["id"]
    assert extensions[0]["status"] == "CANCELLED"

    case_after = validate_success(api.get_case(scenario["case"]["id"], ANALYST), 200)
    assert case_after["negotiation_status"] == "RENEGOTIATION"

    offer_after = validate_success(api.get_offer(scenario["offer"]["id"], NEG), 200)
    assert offer_after["status"] == "ACCEPTED", "voiding the letter does not un-accept the offer"
