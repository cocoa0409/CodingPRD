"""Two status dimensions on one offer, and a valuation that cycles twice.

A preference offer grades conduct on a track that never touches the bargaining
track. An appraisal walks out to challenge and back to report twice on the same
row, and the second lap reads its thresholds from the value the first lap wrote.
"""

from test_helpers import fixtures as fx
from test_helpers import find_row, get_success_data


def _offer_with_one_officer_round(api):
    """A live negotiation with a single opening position on the record.

    The parcel is appraised at 100,000,000 with one lien cured at 250,000, so the
    floor quoted to the housing authority is 64,750,000. One custodian round has
    been tendered, which moved the bargaining dimension off its opening status.
    """
    ctx = fx.build_valued_parcel(
        api,
        appraised_value_cents=100000000,
        book_value_cents=70000000,
        cured_lien_actual_cents=250000,
        lien_estimate_cents=250000,
    )
    ctx = fx.build_preference_offer(api, ctx, preference_category="AFFORDABLE_HOUSING")
    fx.append_officer_round(api, ctx["offer"]["id"], 80000000)
    ctx["offer"] = get_success_data(
        api.get_preference_offer(ctx["offer"]["id"], fx.OFFICER_HEADERS)
    )
    return ctx


def _sustained_then_challengeable_appraisal(api):
    """A reported valuation already revised once by a sustained challenge.

    A designated fund exists so a forfeiture has somewhere to land, the county
    was served the statutory notice so it has standing, and the first challenge
    asserting 90,000,000 against a deposit of 1,000,000 has been sustained at
    92,000,000.
    """
    ctx = {}
    ctx["fund"] = fx.make_fund(
        api,
        priority_rank=1,
        allocation_pct=1.0,
        name="Land Acquisition Reserve",
        fund_code="F-LAND",
    )
    ctx.update(
        fx.build_valued_parcel(api, appraised_value_cents=100000000, accept=False)
    )
    ctx["challenger_agency"] = fx.make_agency(
        api,
        name="Riverbend County",
        agency_type="COUNTY",
        contact_email="assessor@riverbendcounty.gov",
    )
    ctx["declaration"] = fx.make_adopted_declaration(api, ctx["parcel"]["id"])
    ctx["notices"] = fx.issue_notices(
        api, ctx["declaration"]["id"], [ctx["challenger_agency"]["id"]], 60
    )
    first = fx.file_challenge(
        api,
        ctx["appraisal"]["id"],
        ctx["challenger_agency"]["id"],
        asserted_value_cents=90000000,
        deposit_paid_cents=1000000,
    )
    ctx["first_challenge"] = fx.sustain_challenge(api, first["id"], 92000000)
    return ctx


def test_01_opening_the_compliance_review_leaves_the_bargaining_dimension_alone(api):
    """Grading conduct moves one dimension and touches nothing on the other.

    "A preference offer carries two status dimensions that advance independently
    on the same row." "Neither dimension constrains the other's transitions, and
    an operation that drives one dimension leaves the other exactly as it was."

    Design: Difficulty/non_linear_state_machine/preference_offer_negotiation_and_good_faith_dimensions_advance_independently
    """
    ctx = _offer_with_one_officer_round(api)
    assert ctx["offer"]["negotiation_status"] == "IN_NEGOTIATION", (
        "the first round moved the bargaining dimension, got "
        f"{ctx['offer']['negotiation_status']!r}"
    )
    assert ctx["offer"]["good_faith_status"] == "UNREVIEWED", (
        "conduct has not been graded yet, got "
        f"{ctx['offer']['good_faith_status']!r}"
    )

    opened = fx.open_good_faith_review(api, ctx["offer"]["id"])
    assert opened["good_faith_status"] == "UNDER_REVIEW", (
        "opening the review moves the compliance dimension, got "
        f"{opened['good_faith_status']!r}"
    )
    assert opened["negotiation_status"] == "IN_NEGOTIATION", (
        "and must leave the bargaining dimension exactly where it stood, got "
        f"{opened['negotiation_status']!r}"
    )
    assert opened["interim_good_faith_score"] == 15, (
        "one custodian round earns 15 engagement points and nothing else, got "
        f"{opened['interim_good_faith_score']}"
    )


def test_02_the_round_log_keeps_growing_while_the_review_is_open(api):
    """A second round is accepted with the compliance review already running.

    "Appending a round then recomputes the offer's `officer_round_count`,
    `entity_round_count` and `timely_response_count`, recomputes its
    `ah_minimum_price_cents` under the rules of §3.7, and recomputes
    `interim_good_faith_score` using the interim variant of the good-faith score
    described below."

    Design: Difficulty/non_linear_state_machine/preference_offer_negotiation_and_good_faith_dimensions_advance_independently
    """
    ctx = _offer_with_one_officer_round(api)
    fx.open_good_faith_review(api, ctx["offer"]["id"])

    second = fx.append_officer_round(api, ctx["offer"]["id"], 70000000)
    assert second["round_number"] == 2, (
        f"rounds are numbered densely from 1, got {second['round_number']}"
    )
    assert second["party"] == "CUSTODIAN_AGENCY", (
        f"the custodian agency tendered this round, got {second['party']!r}"
    )
    assert second["is_timely"] is False, (
        "a round that answers nothing can never be timely, got "
        f"{second['is_timely']!r}"
    )

    offer = get_success_data(
        api.get_preference_offer(ctx["offer"]["id"], fx.OFFICER_HEADERS)
    )
    assert offer["good_faith_status"] == "UNDER_REVIEW", (
        "the compliance dimension stays where the review left it, got "
        f"{offer['good_faith_status']!r}"
    )
    assert offer["negotiation_status"] == "IN_NEGOTIATION", (
        "and the bargaining dimension holds its self-loop, got "
        f"{offer['negotiation_status']!r}"
    )
    assert offer["officer_round_count"] == 2, (
        f"two custodian rounds now stand on the record, got {offer['officer_round_count']}"
    )
    assert offer["entity_round_count"] == 0, (
        f"the entity has written nothing, got {offer['entity_round_count']}"
    )
    assert offer["timely_response_count"] == 0, (
        f"and so has answered nothing in time, got {offer['timely_response_count']}"
    )
    assert offer["interim_good_faith_score"] == 30, (
        "two custodian rounds earn 30 engagement points, got "
        f"{offer['interim_good_faith_score']}"
    )
    assert not offer.get("final_good_faith_score"), (
        "no determination has run, so no final score is frozen, got "
        f"{offer.get('final_good_faith_score')!r}"
    )
    assert not offer.get("agreed_price_cents"), (
        "nothing has been agreed, got " f"{offer.get('agreed_price_cents')!r}"
    )
    declaration = get_success_data(
        api.get_declaration(ctx["declaration"]["id"], fx.OFFICER_HEADERS)
    )
    assert declaration["status"] == "NOTICED", (
        "the statutory window is still open on the declaration, got "
        f"{declaration['status']!r}"
    )


def test_03_sustaining_a_challenge_returns_the_report_and_rewrites_the_value(api):
    """The first lap of the cycle overwrites the valuation and refunds the deposit.

    "The deposit comes back in full: `deposit_refunded_cents` is set to
    `deposit_paid_cents` and `deposit_forfeited_cents` stays zero. The parent
    appraisal then returns `CHALLENGED → REPORTED` with its
    `appraised_value_cents` overwritten by the revised value and
    `revaluation_required` set to true; `effective_date` is not re-dated, so
    `expires_on` is unchanged and the revision does not buy the report extra
    validity."

    Design: Difficulty/non_linear_state_machine/appraisal_reported_challenged_reported_revision_cycle_repeats
    """
    ctx = _sustained_then_challengeable_appraisal(api)

    first = ctx["first_challenge"]
    assert first["status"] == "SUSTAINED", (
        f"the board sustained the challenge, got {first['status']!r}"
    )
    assert first["revised_value_cents"] == 92000000, (
        f"at the revised value it named, got {first['revised_value_cents']}"
    )
    assert first["deposit_refunded_cents"] == 1000000, (
        "the whole deposit comes back, got " f"{first['deposit_refunded_cents']}"
    )
    assert first["deposit_forfeited_cents"] == 0, (
        "and nothing is forfeited, got " f"{first['deposit_forfeited_cents']}"
    )

    appraisal = get_success_data(
        api.get_appraisal(ctx["appraisal"]["id"], fx.OFFICER_HEADERS)
    )
    assert appraisal["status"] == "REPORTED", (
        "the appraisal is back on the reported side of the loop, got "
        f"{appraisal['status']!r}"
    )
    assert appraisal["appraised_value_cents"] == 92000000, (
        "carrying the revised value, got " f"{appraisal['appraised_value_cents']}"
    )
    assert appraisal["revaluation_required"] is True, (
        "and flagged for revaluation, got " f"{appraisal['revaluation_required']!r}"
    )
    assert appraisal["challenge_count"] == 1, (
        f"one challenge has been filed against it, got {appraisal['challenge_count']}"
    )
    assert appraisal["expires_on"] == "2027-08-01T00:00:00.000Z", (
        "the revision buys no extra validity, got " f"{appraisal['expires_on']!r}"
    )
    assert appraisal["reported_at"] == "2026-08-01T00:00:00.000Z", (
        "and does not re-date the report, got " f"{appraisal['reported_at']!r}"
    )


def test_04_the_second_lap_reads_its_thresholds_from_the_revised_value(api):
    """Filing again is only possible because the report came back, and it costs less.

    "Because the appraisal is `REPORTED` again, it can be challenged again, and
    the `REPORTED → CHALLENGED → REPORTED` loop may repeat." "The requirement is
    computed as the appraised value multiplied by one hundredth, rounded half up
    to a whole cent, and then clamped: if that raw figure is below 100,000 cents
    — one thousand dollars — the requirement is 100,000 cents, and if it is above
    2,500,000 cents — twenty-five thousand dollars — the requirement is 2,500,000
    cents."

    Design: Difficulty/non_linear_state_machine/appraisal_reported_challenged_reported_revision_cycle_repeats
    """
    ctx = _sustained_then_challengeable_appraisal(api)

    second = fx.file_challenge(
        api,
        ctx["appraisal"]["id"],
        ctx["challenger_agency"]["id"],
        asserted_value_cents=86000000,
        deposit_paid_cents=920000,
        grounds="Revised value still ignores the deferred maintenance schedule.",
    )
    assert second["required_deposit_cents"] == 920000, (
        "one hundredth of the revised 92,000,000 is 920,000, inside the clamp, "
        f"got {second['required_deposit_cents']}"
    )
    assert second["status"] == "SUBMITTED", (
        f"the second filing is admissible, got {second['status']!r}"
    )

    appraisal = get_success_data(
        api.get_appraisal(ctx["appraisal"]["id"], fx.OFFICER_HEADERS)
    )
    assert appraisal["status"] == "CHALLENGED", (
        "the second filing drives the loop out again, got "
        f"{appraisal['status']!r}"
    )
    assert appraisal["challenge_count"] == 2, (
        f"and the count reaches two, got {appraisal['challenge_count']}"
    )


def test_05_denying_the_second_challenge_forfeits_the_deposit_to_the_first_fund(api):
    """The second lap closes on a denial, and the money goes to the ranked fund.

    "Link two, caused by the forfeiture: an allocation row is created with no
    conveyance behind it — its `conveyance_id` is null — whose `fund_id` is the
    designated fund with the lowest `priority_rank`, whose `allocation_basis` is
    `CHALLENGE_FORFEITURE`, whose `amount_cents` equals the forfeited deposit,
    whose `residual_included_cents` is zero and whose `status` is `POSTED`."

    Design: Difficulty/non_linear_state_machine/appraisal_reported_challenged_reported_revision_cycle_repeats
    """
    ctx = _sustained_then_challengeable_appraisal(api)
    second = fx.file_challenge(
        api,
        ctx["appraisal"]["id"],
        ctx["challenger_agency"]["id"],
        asserted_value_cents=86000000,
        deposit_paid_cents=920000,
        grounds="Revised value still ignores the deferred maintenance schedule.",
    )

    denied = fx.deny_challenge(api, second["id"])
    assert denied["status"] == "DENIED", (
        f"the board denied the second challenge, got {denied['status']!r}"
    )
    assert denied["deposit_forfeited_cents"] == 920000, (
        "the whole deposit is forfeited, got "
        f"{denied['deposit_forfeited_cents']}"
    )
    assert denied["deposit_refunded_cents"] == 0, (
        "and nothing is refunded, got " f"{denied['deposit_refunded_cents']}"
    )
    assert not denied.get("revised_value_cents"), (
        "a denial names no revised value, got "
        f"{denied.get('revised_value_cents')!r}"
    )

    appraisal = get_success_data(
        api.get_appraisal(ctx["appraisal"]["id"], fx.OFFICER_HEADERS)
    )
    assert appraisal["status"] == "REPORTED", (
        "the appraisal returns to the reported side once more, got "
        f"{appraisal['status']!r}"
    )
    assert appraisal["appraised_value_cents"] == 92000000, (
        "with the value the sustained challenge left intact, got "
        f"{appraisal['appraised_value_cents']}"
    )

    rows = get_success_data(
        api.list_fund_allocations(
            ctx["fund"]["id"],
            fx.FINANCE_HEADERS,
            {"allocation_basis": "CHALLENGE_FORFEITURE", "limit": 100},
        )
    )
    assert len(rows) == 1, (
        f"exactly one forfeiture row is posted, got {len(rows)}"
    )
    row = rows[0]
    assert row["amount_cents"] == 920000, (
        f"for the forfeited deposit, got {row['amount_cents']}"
    )
    assert row["residual_included_cents"] == 0, (
        f"carrying no residual, got {row['residual_included_cents']}"
    )
    assert row["status"] == "POSTED", f"and posted, got {row['status']!r}"
    assert not row.get("conveyance_id"), (
        "a forfeiture row has no conveyance behind it, got "
        f"{row.get('conveyance_id')!r}"
    )

    fund = get_success_data(api.get_fund(ctx["fund"]["id"], fx.FINANCE_HEADERS))
    assert fund["balance_cents"] == 920000, (
        f"the fund balance rises by the forfeiture, got {fund['balance_cents']}"
    )
    assert fund["lifetime_credits_cents"] == 920000, (
        "and so does its lifetime credit total, got "
        f"{fund['lifetime_credits_cents']}"
    )
    assert find_row(rows, fund_id=ctx["fund"]["id"]) is not None, (
        "the row must name the lowest-ranked designated fund"
    )
