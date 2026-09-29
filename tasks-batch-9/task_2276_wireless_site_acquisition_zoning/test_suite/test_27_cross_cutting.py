"""Two version guards and one selector policy that never looks at a record id."""

from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as S
from test_helpers.api_client import ApiClient
from test_helpers.api_errors import ApiError
from test_helpers.assertions import (
    assert_fields,
    assert_instant,
    assert_money,
    assert_pagination_meta,
    assert_score,
    created,
    failed,
    ok,
    page,
)
from test_helpers.constants import iso

# --- candidate version guard ------------------------------------------------
STALE_CANDIDATE_VERSION = 3
FRESH_CANDIDATE_VERSION = 4
VERSION_AFTER_ANALYSIS = 5

# --- ring version guard ----------------------------------------------------
HEARING_DATE = iso("2026-10-01")
SECOND_CANDIDATE_LAT = 42.3525
SECOND_CANDIDATE_LON = -71.0635
SECOND_CANDIDATE_DISTANCE_M = 230

# --- selector-driven forecast ----------------------------------------------
TARGET_ON_AIR_DATE = iso("2027-06-01")
BASELINE_FORECAST_DATE = iso("2027-02-28")
RISK_ADJUSTED_FORECAST_DATE = iso("2027-04-12")
CLAMPED_RISK_SCORE = 0.00


def test_an_analysis_opened_on_a_stale_candidate_version_is_refused(
    api: ApiClient,
) -> None:
    """The qualification the client never saw moved the version; the retry succeeds.

    PRD: "Creating a structural analysis requires a non-optional
    `expected_candidate_version` field carrying the client's last observed `version` of
    the target candidate. A new analysis supersedes the candidate's prior analysis and
    rewrites the candidate's `feasibility_status`, so if `expected_candidate_version` does
    not equal the candidate's current `version`, the request is rejected with
    `ERR_STALE_CANDIDATE_VERSION` (412)."

    PRD: "Clients read the current `version` of a ring or a candidate from the
    corresponding single-resource read."

    PRD: "Creating an analysis has three effects beyond the new record, which begins in
    `IN_PROGRESS` with `capacity_utilization_pct` null and `result` at `PENDING`."

    PRD: "The candidate's `feasibility_status` moves to `STRUCTURAL_HOLD`, whether it was
    `RF_QUALIFIED` or `STRUCTURALLY_CLEARED` beforehand."

    Design: Corner/cross-cutting complexity layers/corner_stale_candidate_version_on_analysis_create
    """
    chain = S.engaged_candidate(api)
    stale_version = S.candidate_version(api, chain["cand_id"])
    assert stale_version == STALE_CANDIDATE_VERSION, (
        f"the engaged candidate should read version {STALE_CANDIDATE_VERSION}"
    )
    qualified = S.rf_qualify(api, chain["cand_id"])
    assert_fields(
        qualified, feasibility_status="RF_QUALIFIED", version=FRESH_CANDIDATE_VERSION
    )

    refused = api.create_structural_analysis(
        F.structural_analysis_payload(chain["cand_id"], stale_version),
        headers=S.analyst(),
    )
    failed(refused, ApiError.STALE_CANDIDATE_VERSION, expected_status=412)

    rows, meta = page(
        api.list_structural_analyses(
            {"candidate_id": chain["cand_id"]}, headers=S.analyst()
        )
    )
    assert rows == [], "the refused create opened no analysis"
    assert_pagination_meta(meta, total_count=0)

    reread = ok(api.get_candidate(chain["cand_id"], headers=S.analyst()))
    assert_fields(
        reread, feasibility_status="RF_QUALIFIED", version=FRESH_CANDIDATE_VERSION
    )

    analysis = created(
        api.create_structural_analysis(
            F.structural_analysis_payload(chain["cand_id"], reread["version"]),
            headers=S.analyst(),
        )
    )
    assert_fields(analysis, status="IN_PROGRESS", result="PENDING")
    assert analysis["capacity_utilization_pct"] is None, "nothing is computed yet"

    on_hold = ok(api.get_candidate(chain["cand_id"], headers=S.analyst()))
    assert_fields(
        on_hold, feasibility_status="STRUCTURAL_HOLD", version=VERSION_AFTER_ANALYSIS
    )


def test_a_selection_on_a_stale_ring_version_is_refused(api: ApiClient) -> None:
    """A second candidate joined the ring behind the director's read, so the guard fires.

    PRD: "Selecting the winning site on a search ring requires a non-optional
    `expected_search_ring_version` field carrying the client's last observed `version` of
    the ring. Selection commits capex against a candidate pool and may supersede an
    earlier selection that a reopen undid, so if `expected_search_ring_version` does not
    equal the ring's current `version`, the request is rejected with
    `ERR_STALE_RING_VERSION` (412)."

    PRD: "The winner is written to the ring's `selected_candidate_id`, the ring moves
    `OPEN → SITE_SELECTED`, and `committed_capex_usd` is recomputed."

    PRD: "`candidate_count` tracks the number of candidates attached to the ring whose
    `acquisition_status` is anything other than `RELINQUISHED`, and is recomputed whenever
    a candidate joins the ring or is relinquished or disqualified."

    Design: Corner/cross-cutting complexity layers/corner_stale_ring_version_on_select_site
    """
    chain = S.build_ready_chain(api, hearing_date=HEARING_DATE)
    stale_ring_version = S.ring_version(api, chain["ring_id"])

    S.create_candidate(
        api,
        chain["ring_id"],
        chain["ll_id"],
        chain["jur_id"],
        lat=SECOND_CANDIDATE_LAT,
        lon=SECOND_CANDIDATE_LON,
        distance_from_center_m=SECOND_CANDIDATE_DISTANCE_M,
    )

    refused = api.select_site(
        chain["ring_id"],
        {"expected_search_ring_version": stale_ring_version},
        headers=S.director(),
    )
    failed(refused, ApiError.STALE_RING_VERSION, expected_status=412)

    unselected = ok(api.get_search_ring(chain["ring_id"], headers=S.director()))
    assert_fields(unselected, status="OPEN")
    assert unselected["selected_candidate_id"] is None, "nothing was selected"
    assert unselected["version"] == stale_ring_version + 1, (
        "the second candidate moved the ring's version exactly once"
    )

    selected = ok(
        api.select_site(
            chain["ring_id"],
            {"expected_search_ring_version": unselected["version"]},
            headers=S.director(),
        )
    )
    assert_fields(
        selected,
        status="SITE_SELECTED",
        selected_candidate_id=chain["cand_id"],
        candidate_count=2,
    )
    assert_money(selected["committed_capex_usd"], 0.00, "committed_capex_usd")


def test_the_forecast_driver_is_the_earlier_of_two_identically_scored_candidates(
    api: ApiClient,
) -> None:
    """Score ties fall through to `created_at`, and the slip clamps the score to zero.

    PRD: "Otherwise the driver is chosen from the ring's candidates whose
    `acquisition_status` is not `RELINQUISHED` and whose `feasibility_status` is not
    `DISQUALIFIED`, ranked by `rf_qualification_score` from highest to lowest with
    candidates whose score is still null ranking last, ties broken by `created_at`
    earliest first."

    PRD: "Scoring is a single-candidate computation: it reads only the candidate named in
    the request and the ring reached through its `search_ring_id`, and never aggregates
    over sibling candidates."

    PRD: "The **baseline** variant is simply the current logical clock advanced by the
    total remaining days — nominal durations, no delay factor, no continuance penalty —
    and is stored as `baseline_forecast_date`."

    PRD: "The **risk-adjusted** variant inflates the work: the remaining days are
    multiplied by the jurisdiction's `historical_delay_factor` and rounded *up* to a whole
    number of days, and to that is added the continuance count multiplied by the
    jurisdiction's `hearing_cadence_days`, so each continuance the authority granted costs
    one full hearing cycle."

    PRD: "The result is clamped to the range 0 through 100 and then rounded half up to two
    decimal places."

    PRD: "`risk_band` bands that score: `HIGH` at 70.00 or above, `MEDIUM` at 40.00 or
    above but below 70.00, and `LOW` below 40.00."

    Design: Corner/cross-cutting complexity layers/corner_selector_policy_drives_on_air_forecast_without_ids
    """
    chain = S.base_reference_data(api)
    first = S.create_candidate(api, chain["ring_id"], chain["ll_id"], chain["jur_id"])
    first_scored = S.rf_qualify(api, first["id"])
    second = S.create_candidate(api, chain["ring_id"], chain["ll_id"], chain["jur_id"])
    second_scored = S.rf_qualify(api, second["id"])

    assert_score(
        first_scored["rf_qualification_score"],
        C.CANDIDATE_RF_SCORE,
        "rf_qualification_score",
    )
    assert_score(
        second_scored["rf_qualification_score"],
        C.CANDIDATE_RF_SCORE,
        "rf_qualification_score",
    )

    plan = created(
        api.create_on_air_plan(
            {
                "search_ring_id": chain["ring_id"],
                "target_on_air_date": TARGET_ON_AIR_DATE,
            },
            headers=S.director(),
        )
    )
    assert_fields(
        plan, driver_candidate_id=first["id"], risk_band="LOW", status="PLANNED"
    )
    assert_instant(
        plan["baseline_forecast_date"], BASELINE_FORECAST_DATE, "baseline_forecast_date"
    )
    assert_instant(
        plan["risk_adjusted_forecast_date"],
        RISK_ADJUSTED_FORECAST_DATE,
        "risk_adjusted_forecast_date",
    )
    assert_score(plan["schedule_risk_score"], CLAMPED_RISK_SCORE, "schedule_risk_score")

    ring = ok(api.get_search_ring(chain["ring_id"], headers=S.director()))
    assert_fields(ring, candidate_count=2)
    assert ring["selected_candidate_id"] is None, "the driver came from the pool, not a selection"
