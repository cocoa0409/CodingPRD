"""The tariff rate book: approval, withdrawal, the parity cap and window overlap."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_errors import (
    ERR_ACCESS_REFORM_RATE_CAP_EXCEEDED,
    ERR_INVALID_TARIFF_FILING_STATE,
    ERR_INVALID_TARIFF_WINDOW,
    ERR_TARIFF_WINDOW_OVERLAP,
)
from test_helpers.assertions import assert_rate
from test_helpers.constants import (
    BENCHMARK_INTERSTATE_RATE,
    DOCKET_LOCAL,
    RATE_LOCAL,
    T_2026_08_01,
    T_2026_12_01,
    T_2027_01_01,
)
from test_helpers.factories import tariff_filing_payload
from test_helpers.fixtures import read_tariff_filing, setup_local_reciprocal_tariff


def test_tariff_filing_approval_moves_filed_to_effective(api, regulator_headers):
    """Approving a FILED reciprocal-compensation filing stamps approved_at and bumps version.

    PRD 3.5: "Approval moves the filing `FILED → EFFECTIVE`."
    PRD 3.5: "Approval stamps `approved_at` from the logical clock and increments the filing's `version` by 1."
    PRD 3.5: "A new filing lands in `status` `FILED`, with `approved_at`, `superseded_by_filing_id` and `superseded_at` all null."

    Design: Corner/state_machines/tariff_filing_approval_moves_filed_to_effective
    """
    filing = setup_local_reciprocal_tariff(api, approve=False)
    assert filing["status"] == "FILED"

    response = api.approve_tariff_filing(filing["id"], {}, regulator_headers)
    approved = validate_success(response, expected_status=200)

    assert approved["status"] == "EFFECTIVE"
    assert approved["approved_at"] == T_2026_08_01, (
        f"approved_at must come from the logical clock, got {approved['approved_at']}"
    )
    assert approved["superseded_by_filing_id"] is None
    assert approved["superseded_at"] is None
    assert_rate(approved["rate_per_mou_usd"], RATE_LOCAL, "rate_per_mou_usd")
    assert approved["version"] == 2, f"expected version 2, got {approved['version']}"


def test_approving_the_same_tariff_filing_twice_is_refused(api, regulator_headers):
    """A second approval finds the filing EFFECTIVE, not FILED, and is refused.

    PRD 3.5: "Both approval and withdrawal require the filing to be in `FILED`; any other status — `EFFECTIVE`, `SUPERSEDED` or `WITHDRAWN` — is refused with `ERR_INVALID_TARIFF_FILING_STATE`."
    PRD 3.5: "Approval stamps `approved_at` from the logical clock and increments the filing's `version` by 1."

    Design: Corner/state_machines/approving_the_same_tariff_filing_twice_is_refused
    """
    filing = setup_local_reciprocal_tariff(api, approve=True)
    assert filing["status"] == "EFFECTIVE"

    response = api.approve_tariff_filing(filing["id"], {}, regulator_headers)
    validate_error(response, ERR_INVALID_TARIFF_FILING_STATE, expected_status=409)

    unchanged = read_tariff_filing(api, filing["id"])
    assert unchanged["status"] == "EFFECTIVE"
    assert unchanged["approved_at"] == T_2026_08_01
    assert unchanged["version"] == 2, (
        f"the refused approval must not bump version, got {unchanged['version']}"
    )


def test_tariff_filing_withdrawn_before_approval_never_becomes_effective(
    api, regulator_headers
):
    """Withdrawing a never-approved filing is terminal and leaves no EFFECTIVE rate.

    PRD 3.5: "A filing that was never approved may be **withdrawn** by a `RegulatoryAffairsSpecialist` with a `withdrawal_reason`, moving it `FILED → WITHDRAWN`, which is terminal, and incrementing its `version` by 1."
    PRD 3.5: "A new filing lands in `status` `FILED`, with `approved_at`, `superseded_by_filing_id` and `superseded_at` all null."

    Design: Corner/state_machines/tariff_filing_withdrawn_before_approval_never_becomes_effective
    """
    filing = setup_local_reciprocal_tariff(api, approve=False)
    assert filing["filing_docket"] == DOCKET_LOCAL

    response = api.withdraw_tariff_filing(
        filing["id"],
        {
            "withdrawal_reason": "Commission staff requested a refiling with the revised cost study"
        },
        regulator_headers,
    )
    withdrawn = validate_success(response, expected_status=200)

    assert withdrawn["status"] == "WITHDRAWN"
    assert withdrawn["version"] == 2
    assert withdrawn["approved_at"] is None
    assert withdrawn["superseded_by_filing_id"] is None
    assert withdrawn["superseded_at"] is None

    rows, meta = validate_paginated(
        api.list_tariff_filings(
            regulator_headers, params={"rate_element": "LOCAL_RECIPROCAL_COMP"}
        )
    )
    assert meta["total_count"] == 1
    assert [row["status"] for row in rows] == ["WITHDRAWN"], (
        "a withdrawn filing must never appear as an EFFECTIVE rate"
    )


def test_intrastate_rate_cap_beats_the_tariff_window_ordering_error(
    api, regulator_headers
):
    """A filing that breaches the parity cap and inverts its window reports the cap.

    PRD 3.5: "A filing whose `rate_element` is `INTRASTATE_SWITCHED_ACCESS` may not price above the carrier's own interstate benchmark: its `rate_per_mou_usd` must be no greater than its `benchmark_interstate_rate_per_mou_usd`, with equality being compliant."
    PRD 3.5: "A breach is refused with `ERR_ACCESS_REFORM_RATE_CAP_EXCEEDED`."
    PRD 2.7: "Within that tenth band the ordering is likewise fixed. Regulatory caps come first: the access charge reform parity cap, the reciprocal compensation rate cap, and the traffic factor sum ceiling are evaluated before the transit-permission and unrateable-record refusals."
    PRD 2.7: "A regulatory cap breach surfaces as its own code rather than being masked by a later capacity or fiscal check, and a state conflict always beats a business-rule breach on the same request — a dispute in the wrong status is reported as an invalid dispute state, not as a credit-amount problem."

    Design: Difficulty/priority_pair_validation_conflict/intrastate_rate_cap_safety_beats_temporal_window_error
    """
    _, meta = validate_paginated(
        api.list_tariff_filings(
            regulator_headers, params={"rate_element": "INTRASTATE_SWITCHED_ACCESS"}
        )
    )
    assert meta["total_count"] == 0, "the intrastate rate book must start empty"

    response = api.create_tariff_filing(
        tariff_filing_payload(
            filing_docket="TF-2026-IST-BAD",
            rate_element="INTRASTATE_SWITCHED_ACCESS",
            rate_per_mou_usd=0.6,
            benchmark_interstate_rate_per_mou_usd=BENCHMARK_INTERSTATE_RATE,
            effective_date="2026-09-01T00:00:00.000Z",
            expiry_date="2026-08-15T00:00:00.000Z",
        ),
        regulator_headers,
    )
    validate_error(response, ERR_ACCESS_REFORM_RATE_CAP_EXCEEDED, expected_status=422)

    rows, meta = validate_paginated(
        api.list_tariff_filings(
            regulator_headers, params={"rate_element": "INTRASTATE_SWITCHED_ACCESS"}
        )
    )
    assert meta["total_count"] == 0, "the refused filing must not be persisted"
    assert [row["filing_docket"] for row in rows] == []


def test_tariff_window_ordering_is_reported_when_the_parity_cap_is_satisfied(
    api, regulator_headers
):
    """With the rate at parity the same inverted window surfaces the window error alone.

    PRD 3.5: "A filing whose `rate_element` is `INTRASTATE_SWITCHED_ACCESS` may not price above the carrier's own interstate benchmark: its `rate_per_mou_usd` must be no greater than its `benchmark_interstate_rate_per_mou_usd`, with equality being compliant."
    PRD 3.5: "The expiry instant must fall strictly after the effective instant, and otherwise the filing is refused with `ERR_INVALID_TARIFF_WINDOW`."
    PRD 2.7: "Uniqueness, window-overlap, capacity and round-limit constraints come next, followed by the two payload-shape constraints on installed trunks and agreed minutes and the clock monotonicity check. Temporal window checks follow — first the four that carry HTTP 422 (tariff window ordering, measurement period ordering, usage period ordering and closure, the dispute filing window, and the committed due date), then the three that carry HTTP 409 (agreement effective date reached, dispute SLA not yet expired, invoice due date reached)."

    Design: Difficulty/priority_pair_validation_conflict/intrastate_rate_cap_safety_beats_temporal_window_error
    """
    response = api.create_tariff_filing(
        tariff_filing_payload(
            filing_docket="TF-2026-IST-BAD",
            rate_element="INTRASTATE_SWITCHED_ACCESS",
            rate_per_mou_usd=BENCHMARK_INTERSTATE_RATE,
            benchmark_interstate_rate_per_mou_usd=BENCHMARK_INTERSTATE_RATE,
            effective_date="2026-09-01T00:00:00.000Z",
            expiry_date="2026-08-15T00:00:00.000Z",
        ),
        regulator_headers,
    )
    validate_error(response, ERR_INVALID_TARIFF_WINDOW, expected_status=422)

    _, meta = validate_paginated(
        api.list_tariff_filings(
            regulator_headers, params={"rate_element": "INTRASTATE_SWITCHED_ACCESS"}
        )
    )
    assert meta["total_count"] == 0, "the refused filing must not be persisted"


def test_tariff_rate_windows_may_touch_at_the_expiry_instant(api, regulator_headers):
    """A successor whose effective instant equals the incumbent's expiry is accepted.

    PRD 3.5: "Because the windows are half-open, **adjacency is not overlap**: a new filing whose `effective_date` equals an existing filing's `expiry_date` is accepted without complaint."
    PRD 2.8: "A **half-open window** written as a start instant and an end instant includes the start and excludes the end; tariff filing effective windows work this way, which is why a new filing whose effective instant equals a prior filing's expiry instant does not overlap it."
    PRD 3.5: "A new filing lands in `status` `FILED`, with `approved_at`, `superseded_by_filing_id` and `superseded_at` all null."

    Design: Difficulty/resource_temporal_overlap/tariff_rate_windows_may_touch_but_never_overlap
    """
    incumbent = setup_local_reciprocal_tariff(api, approve=True)
    assert incumbent["expiry_date"] == T_2027_01_01

    response = api.create_tariff_filing(
        tariff_filing_payload(
            filing_docket="TF-2027-LOC-002",
            rate_element="LOCAL_RECIPROCAL_COMP",
            rate_per_mou_usd=0.055,
            benchmark_interstate_rate_per_mou_usd=BENCHMARK_INTERSTATE_RATE,
            effective_date=T_2027_01_01,
            expiry_date="2027-07-01T00:00:00.000Z",
        ),
        regulator_headers,
    )
    successor = validate_success(response, expected_status=201)

    assert successor["status"] == "FILED"
    assert successor["effective_date"] == T_2027_01_01, (
        "the successor shares the incumbent's expiry instant"
    )
    assert successor["approved_at"] is None
    assert_rate(successor["rate_per_mou_usd"], 0.055, "rate_per_mou_usd")

    _, meta = validate_paginated(
        api.list_tariff_filings(
            regulator_headers, params={"rate_element": "LOCAL_RECIPROCAL_COMP"}
        )
    )
    assert meta["total_count"] == 2


def test_tariff_rate_windows_that_truly_overlap_are_refused(api, regulator_headers):
    """A filing straddling both existing windows is refused and leaves the book untouched.

    PRD 3.5: "A new filing's half-open window must not overlap the window of any existing filing for the same `rate_element` whose `status` is `FILED` or `EFFECTIVE`; an overlap is refused with `ERR_TARIFF_WINDOW_OVERLAP`."
    PRD 3.5: "Two filings for the same rate element may not both claim the same instant."

    Design: Difficulty/resource_temporal_overlap/tariff_rate_windows_may_touch_but_never_overlap
    """
    incumbent = setup_local_reciprocal_tariff(api, approve=True)
    validate_success(
        api.create_tariff_filing(
            tariff_filing_payload(
                filing_docket="TF-2027-LOC-002",
                rate_element="LOCAL_RECIPROCAL_COMP",
                rate_per_mou_usd=0.055,
                benchmark_interstate_rate_per_mou_usd=BENCHMARK_INTERSTATE_RATE,
                effective_date=T_2027_01_01,
                expiry_date="2027-07-01T00:00:00.000Z",
            ),
            regulator_headers,
        ),
        expected_status=201,
    )

    response = api.create_tariff_filing(
        tariff_filing_payload(
            filing_docket="TF-2027-LOC-003",
            rate_element="LOCAL_RECIPROCAL_COMP",
            rate_per_mou_usd=0.05,
            benchmark_interstate_rate_per_mou_usd=BENCHMARK_INTERSTATE_RATE,
            effective_date=T_2026_12_01,
            expiry_date="2027-03-01T00:00:00.000Z",
        ),
        regulator_headers,
    )
    validate_error(response, ERR_TARIFF_WINDOW_OVERLAP, expected_status=409)

    rows, meta = validate_paginated(
        api.list_tariff_filings(
            regulator_headers, params={"rate_element": "LOCAL_RECIPROCAL_COMP"}
        )
    )
    assert meta["total_count"] == 2, "the overlapping filing must not be persisted"
    assert "TF-2027-LOC-003" not in [row["filing_docket"] for row in rows]

    unchanged = read_tariff_filing(api, incumbent["id"])
    assert unchanged["status"] == "EFFECTIVE"
    assert unchanged["expiry_date"] == T_2027_01_01
    assert unchanged["superseded_by_filing_id"] is None
