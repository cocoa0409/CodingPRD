"""The two civil-money-penalty basis variants on identical redemption history.

The same four closed monitoring periods produce a different penalty depending on
how long the store has been authorized when the charge letter issues: a seasoned
store is averaged over its trailing history, an unseasoned one over its three
largest periods.
"""
from typing import Any, Dict, List, Tuple

from test_helpers import (
    ADMIN,
    advance_clock,
    assert_fields,
    assert_ledger_conservation,
    authorized_store,
    elect_cmp,
    file_reply,
    four_closed_periods,
    issue_charge_letter,
    issue_determination,
    ledger_entries,
    open_case,
    refresh_case,
    refresh_owner,
    rows,
    api_client,
    substantiated_ineligible_investigation,
    substantiated_trafficking_investigation,
)


def hardship_case_charged_at(
    charge_instant: str, violation_type: str = "INELIGIBLE_ITEMS_HARDSHIP"
) -> Tuple[Any, Dict[str, Any], List[Dict[str, Any]], Dict[str, Any]]:
    """An authorized store with four closed periods, a substantiated
    investigation and a sanction case whose charge letter issues at
    `charge_instant`, answered by a timely election and a reply."""
    context = authorized_store()
    periods = four_closed_periods(context.store_id)
    if violation_type == "TRAFFICKING":
        investigation = substantiated_trafficking_investigation(context.store_id)
    else:
        investigation = substantiated_ineligible_investigation(context.store_id)
    case = open_case(investigation["id"], violation_type)
    advance_clock(charge_instant)
    case = issue_charge_letter(case["id"])
    election = elect_cmp(case, context.owner)
    file_reply(case["id"], context.owner)
    return context, case, periods, election


def test_trailing_twelve_period_average_is_selected_after_a_full_year():
    """A charge letter issued 396 days after authorization averages every closed
    period, in descending period order.

    The specification seasons the basis on the store's own history: the trailing
    variant applies once the store has at least a year of authorized history, and
    it averages the most recent twelve closed periods. With only four closed
    periods on file the average of 1,234,567c, 1,000,000c, 900,000c and
    2,000,000c is 1,283,642c after the half-up rounding, and the basis is listed
    from the highest period index down.

    Design: Difficulty/dual_variant_calc/cmp_basis_trailing_twelve_period_variant_selected_after_full_year
    """
    context, case, periods, _election = hardship_case_charged_at("2027-09-01T00:00:00Z")

    issue_determination(case["id"], "CMP_IN_LIEU")

    case = refresh_case(case["id"])
    assert_fields(
        case,
        {
            "cmp_basis_variant": "TRAILING_12_PERIOD_AVERAGE",
            "avg_monthly_redemption_cents": 1283642,
            "monthly_penalty_cents": 128364,
            "disqualification_months": 3,
            "cmp_amount_cents": 385092,
            "cmp_capped": False,
            "cmp_outstanding_cents": 385092,
            "status": "DETERMINED",
            "admin_review_due_at": "2027-09-11T00:00:00Z",
        },
        "determined case",
    )
    expected_ids = [periods[3]["id"], periods[2]["id"], periods[1]["id"], periods[0]["id"]]
    assert case["cmp_basis_period_ids"] == expected_ids, (
        f"cmp_basis_period_ids {case['cmp_basis_period_ids']} is not the four closed "
        f"periods in descending index order {expected_ids}"
    )


def test_trailing_variant_penalty_reaches_the_ledger_and_the_owner_rollup():
    """The assessed penalty is posted once to the append-only ledger and rolled
    up onto the owner as active civil-money-penalty debt.

    The specification ties the three together: the ledger is append-only, the
    case's `cmp_outstanding_cents` is the signed sum of its ledger entries, and
    the owner "carries the `HAS_ACTIVE_CMP_DEBT` flag until the balance reaches
    zero."

    Design: Difficulty/dual_variant_calc/cmp_basis_trailing_twelve_period_variant_selected_after_full_year
    """
    context, case, _periods, election = hardship_case_charged_at("2027-09-01T00:00:00Z")

    issue_determination(case["id"], "CMP_IN_LIEU")

    case = refresh_case(case["id"])
    entries = ledger_entries(case["id"])
    assert len(entries) == 1, f"expected exactly one ledger entry, got {entries}"
    assert_fields(
        entries[0],
        {
            "entry_type": "CMP_ASSESSED",
            "amount_cents": 385092,
            "balance_after_cents": 385092,
        },
        "assessment entry",
    )
    assert_ledger_conservation(entries, case)

    owner = refresh_owner(context.owner_id)
    assert_fields(
        owner,
        {"cmp_outstanding_cents": 385092, "sanction_flag": "HAS_ACTIVE_CMP_DEBT"},
        "owner rollup",
    )

    elections = rows(api_client.list_cmp_elections(case["id"], ADMIN))
    assert len(elections) == 1, f"expected one election on the case, got {elections}"
    assert elections[0]["id"] == election["id"]
    assert elections[0]["status"] == "APPROVED", (
        f"the election accepted by the determination should be APPROVED, "
        f"got {elections[0]['status']}"
    )


def test_peak_three_period_average_is_selected_before_a_full_year():
    """A charge letter issued 92 days after authorization averages only the three
    largest closed periods, in descending amount order.

    The specification selects the peak variant while the store is unseasoned, and
    it takes the three highest-redemption closed periods. On the same four
    periods the peak basis is 2,000,000c, 1,234,567c and 1,000,000c, averaging
    1,411,522c — a strictly larger figure than the trailing variant reaches on
    identical data.

    Design: Difficulty/dual_variant_calc/cmp_basis_peak_three_period_variant_selected_before_full_year
    """
    context, case, periods, _election = hardship_case_charged_at("2026-11-01T00:00:00Z")

    issue_determination(case["id"], "CMP_IN_LIEU")

    case = refresh_case(case["id"])
    assert_fields(
        case,
        {
            "cmp_basis_variant": "PEAK_3_PERIOD_AVERAGE",
            "avg_monthly_redemption_cents": 1411522,
            "monthly_penalty_cents": 141152,
            "disqualification_months": 3,
            "cmp_amount_cents": 423456,
            "cmp_capped": False,
            "cmp_outstanding_cents": 423456,
        },
        "determined case",
    )
    expected_ids = [periods[3]["id"], periods[0]["id"], periods[1]["id"]]
    assert case["cmp_basis_period_ids"] == expected_ids, (
        f"cmp_basis_period_ids {case['cmp_basis_period_ids']} is not the three largest "
        f"periods in descending amount order {expected_ids}"
    )


def test_peak_variant_amount_is_quoted_on_the_election_and_the_owner_rollup():
    """The election filed against the charged case quotes the same basis variant
    the determination later applies, and the owner rollup carries the larger peak
    figure.

    The election endpoint files "an election to pay a civil money penalty in lieu
    of disqualification, quoting the amount from the case's charge date and the
    store's closed redemption history", so an election filed while the store is
    unseasoned must quote PEAK_3_PERIOD_AVERAGE.

    Design: Difficulty/dual_variant_calc/cmp_basis_peak_three_period_variant_selected_before_full_year
    """
    context, case, _periods, election = hardship_case_charged_at("2026-11-01T00:00:00Z")

    assert election["quoted_basis_variant"] == "PEAK_3_PERIOD_AVERAGE", (
        f"the election filed 92 days after authorization should quote the peak "
        f"variant, got {election['quoted_basis_variant']!r}"
    )

    issue_determination(case["id"], "CMP_IN_LIEU")

    owner = refresh_owner(context.owner_id)
    assert_fields(
        owner,
        {"cmp_outstanding_cents": 423456, "sanction_flag": "HAS_ACTIVE_CMP_DEBT"},
        "owner rollup",
    )
