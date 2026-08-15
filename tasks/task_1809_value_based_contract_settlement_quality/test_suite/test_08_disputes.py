"""Settlement disputes: filing window, review, resolution, SoD, recalculation."""
from test_helpers import (
    ADJUDICATOR, ApiErrorId, CLAIMS, CLOCK_DISPUTE, CLOCK_FINALIZE,
    CLOCK_RESOLUTION_PAST, CLOCK_WINDOW_PAST, assert_settlement_chain,
    begin_review, canonical_two_member_journey, create_dispute_payload,
    file_dispute, finalize_settlement, get_settlement, get_year, make_group,
    make_practice_group_rep_headers, resolve_dispute, set_clock,
    single_member_journey, validate_error, validate_success,
)
from test_helpers import make_dispute_adjudicator_headers


def test_settlement_dispute_upheld_recalculates_to_provisional(api, claims_processor_headers):
    """PRD §3.11: "An `UPHELD` resolution (`UNDER_REVIEW → UPHELD`) cascades the settlement `DISPUTED → RECALCULATING` and then, in the same request, automatically recalculates the settlement from the corrected data, moving it `RECALCULATING → PROVISIONAL` with all computed fields refreshed, `settlement_seq` unchanged, and `needs_recompute` cleared to `false`."
    PRD §3.7: "From `PAID` the processor may void it (`PAID → VOIDED`) provided the year is not in `SETTLED` or `CLOSED` (`ERR_YEAR_LOCKED`)."

    Design: Difficulty/non_linear_state_machine/settlement_dispute_recalc_cycle
    """
    pipe = canonical_two_member_journey(stage="FINALIZED")
    settlement = pipe["settlement"]
    assert settlement["net_payable_cents"] == 117500  # pre-dispute baseline

    dispute = file_dispute(
        settlement["id"], pipe["group"]["id"],
        dispute_ref="D-1", reason_code="CLAIMS_MISSING", claimed_adjustment_cents=700000,
    )
    # The 700,000-cent claim is voided while the settlement is DISPUTED.
    validate_success(api.void_claim(pipe["claims"][1]["id"], claims_processor_headers))
    begin_review(dispute["id"])
    resolved = resolve_dispute(dispute["id"], "UPHELD", adjudicator_user_id="adj-9")
    assert resolved["dispute_status"] == "UPHELD"

    after = get_settlement(settlement["id"])
    assert after["settlement_status"] == "PROVISIONAL", (
        "RECALCULATING -> PROVISIONAL executed atomically in the resolve request"
    )
    # Corrected data: actual 400,000; pool 20,000; gross 1,400,000; rate 7777;
    # shared 180,000 (cap); adjusted 90,000; released 10,000 -> net 100,000.
    assert after["net_payable_cents"] == 100000
    assert after["needs_recompute"] is False
    assert after["settlement_seq"] == settlement["settlement_seq"]


def test_settlement_refinalizes_after_upheld_recalc(api):
    """PRD §3.10: "Finalization (`PROVISIONAL → FINALIZED`) is performed by a `SettlementOfficer` and is gated by two preconditions: the logical clock date must be at or after the year's `period_end` plus the reconciliation runout (`ERR_RECONCILIATION_RUNOUT_INCOMPLETE`), and `needs_recompute` must be `false` (`ERR_SETTLEMENT_STALE` while it is true). Finalization recomputes every computed field from current data using the **final** variant — actuals only, with no completion factor or annualization applied — and stamps `finalized_on` with the logical clock date and `finalized_by_user_id` with the calling officer's `X-User-ID`."

    Design: Difficulty/non_linear_state_machine/settlement_dispute_recalc_cycle
    """
    pipe = canonical_two_member_journey(stage="FINALIZED")
    settlement = pipe["settlement"]
    dispute = file_dispute(settlement["id"], pipe["group"]["id"], dispute_ref="D-1")
    validate_success(api.void_claim(pipe["claims"][1]["id"], CLAIMS))
    begin_review(dispute["id"])
    resolve_dispute(dispute["id"], "UPHELD")

    year = get_year(pipe["year"]["id"])
    assert year["actual_cost_cents"] == 400000
    assert year["withhold_pool_cents"] == 20000

    refinalized = finalize_settlement(settlement["id"], clock="2027-06-03T00:00:00Z")
    assert refinalized["settlement_status"] == "FINALIZED"
    assert refinalized["finalized_on"] == "2027-06-03", (
        "re-finalization restamps the anchor from the logical clock"
    )
    assert refinalized["net_payable_cents"] == 100000


def test_dispute_upheld_attribution_exclusion_cascade(api, attribution_analyst_headers):
    """PRD §3.5: "Exclusion triggers a two-link cascade: first, the year's `total_member_months` and `benchmark_cost_cents` are recomputed without this record; second, the year's settlement, if it is in `PROVISIONAL` or `FINALIZED`, has its `needs_recompute` set to `true` — this is the serialization point between attribution edits and downstream settlement."
    PRD §3.11: "An `UPHELD` resolution (`UNDER_REVIEW → UPHELD`) cascades the settlement `DISPUTED → RECALCULATING` and then, in the same request, automatically recalculates the settlement from the corrected data, moving it `RECALCULATING → PROVISIONAL` with all computed fields refreshed, `settlement_seq` unchanged, and `needs_recompute` cleared to `false`."

    Design: Difficulty/transitive_cascade/dispute_upheld_attribution_exclusion_cascade
    """
    pipe = canonical_two_member_journey(stage="FINALIZED")
    settlement = pipe["settlement"]
    dispute = file_dispute(
        settlement["id"], pipe["group"]["id"],
        dispute_ref="D-1", reason_code="ATTRIBUTION_ERROR",
        claimed_adjustment_cents=600000,
    )
    # M2's record is excluded mid-dispute; the rollups move under the settlement.
    validate_success(api.exclude_attribution_record(pipe["records"][1]["id"], attribution_analyst_headers))
    begin_review(dispute["id"])
    resolved = resolve_dispute(dispute["id"], "UPHELD")
    assert resolved["dispute_status"] == "UPHELD"

    after = get_settlement(settlement["id"])
    assert after["settlement_status"] == "PROVISIONAL"
    year = get_year(pipe["year"]["id"])
    assert year["total_member_months"] == 12
    assert year["benchmark_cost_cents"] == 1200000
    assert year["actual_cost_cents"] == 400000, (
        "claims of the excluded member leave the measurement input set"
    )


def test_dispute_upheld_recalculation_amounts(api, attribution_analyst_headers):
    """PRD §3.10: "The gross, stored on `gross_savings_cents`, is `benchmark_cost_cents` minus `actual_cost_cents` and may be negative."
    PRD §3.11: "An `UPHELD` resolution (`UNDER_REVIEW → UPHELD`) cascades the settlement `DISPUTED → RECALCULATING` and then, in the same request, automatically recalculates the settlement from the corrected data, moving it `RECALCULATING → PROVISIONAL` with all computed fields refreshed, `settlement_seq` unchanged, and `needs_recompute` cleared to `false`."

    Design: Difficulty/transitive_cascade/dispute_upheld_attribution_exclusion_cascade
    """
    pipe = canonical_two_member_journey(stage="FINALIZED")
    settlement = pipe["settlement"]
    dispute = file_dispute(settlement["id"], pipe["group"]["id"], dispute_ref="D-1")
    validate_success(api.exclude_attribution_record(pipe["records"][1]["id"], attribution_analyst_headers))
    begin_review(dispute["id"])
    resolve_dispute(dispute["id"], "UPHELD")

    after = get_settlement(settlement["id"])
    # Corrected: benchmark 1,200,000 - actual 400,000 = gross 800,000; rate 6666;
    # shared = min(400,000, cap 120,000) = 120,000; adjusted 60,000;
    # pool 20,000 x 5000 bp = 10,000 released -> net 70,000.
    assert_settlement_chain(
        after,
        gross_savings_cents=800000,
        net_payable_cents=70000,
    )
    assert after["needs_recompute"] is False


def test_dispute_resolve_from_filed_rejected(api, dispute_adjudicator_headers):
    """PRD §3.11: "A `DisputeAdjudicator` begins review (`FILED → UNDER_REVIEW`), which stamps `review_started_on`. From `UNDER_REVIEW` the adjudicator resolves the dispute by supplying an `outcome` of `UPHELD` or `OVERRULED`."
    PRD §2.8: "6. **State preconditions** — the target resource is in a from-state of the invoked transition; failures produce `ERR_INVALID_STATE_TRANSITION` or one of the more specific state-family errors listed in §5 (all 409)."

    Design: Corner/state_machines/dispute_resolve_from_filed_rejected
    """
    pipe = single_member_journey(stage="FINALIZED")
    dispute = file_dispute(pipe["settlement"]["id"], pipe["group"]["id"])
    assert dispute["dispute_status"] == "FILED"

    resp = api.resolve_dispute(dispute["id"], {"outcome": "UPHELD"}, dispute_adjudicator_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
    reread = validate_success(api.get_dispute(dispute["id"], dispute_adjudicator_headers))
    assert reread["dispute_status"] == "FILED"
    assert get_settlement(pipe["settlement"]["id"])["settlement_status"] == "DISPUTED"


def test_segregation_of_duties_resolve_rejected(api):
    """PRD §3.11: "Resolution is gated by two preconditions applied in cascade order: the logical clock date must be on or before `filed_on` plus the dispute-resolution window (`ERR_DISPUTE_RESOLUTION_WINDOW_ELAPSED`), and the caller's `X-User-ID` must differ from the settlement's `finalized_by_user_id` (`ERR_SEGREGATION_OF_DUTIES`). The resolve transition writes `resolved_on` from the clock, writes `resolved_by_user_id` from the header, and writes `resolution_outcome` to the supplied outcome."
    PRD §3.11: "An `OVERRULED` resolution (`UNDER_REVIEW → OVERRULED`) cascades the settlement `DISPUTED → FINALIZED` with amounts unchanged."

    Design: Corner/errors/segregation_of_duties_resolve_rejected
    """
    pipe = single_member_journey(stage="FINALIZED", finalize_officer="so-1")
    dispute = file_dispute(pipe["settlement"]["id"], pipe["group"]["id"])
    begin_review(dispute["id"])

    # The certifying officer may not adjudicate their own settlement.
    set_clock("2027-06-03T00:00:00Z")
    same_user = api.resolve_dispute(
        dispute["id"], {"outcome": "OVERRULED"}, make_dispute_adjudicator_headers("so-1")
    )
    validate_error(same_user, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

    resolved = validate_success(api.resolve_dispute(
        dispute["id"], {"outcome": "OVERRULED"}, make_dispute_adjudicator_headers("adj-9")
    ))
    assert resolved["dispute_status"] == "OVERRULED"
    assert resolved["resolved_by_user_id"] == "adj-9"
    assert get_settlement(pipe["settlement"]["id"])["settlement_status"] == "FINALIZED"


def test_dispute_resolution_window_elapsed_then_expire(api, dispute_adjudicator_headers):
    """PRD §3.11: "Resolution is gated by two preconditions applied in cascade order: the logical clock date must be on or before `filed_on` plus the dispute-resolution window (`ERR_DISPUTE_RESOLUTION_WINDOW_ELAPSED`), and the caller's `X-User-ID` must differ from the settlement's `finalized_by_user_id` (`ERR_SEGREGATION_OF_DUTIES`)."
    PRD §3.11: "A `DisputeAdjudicator` may expire the dispute (`FILED → EXPIRED` or `UNDER_REVIEW → EXPIRED`) once the logical clock date is strictly greater than `filed_on` plus the resolution window (`ERR_DISPUTE_NOT_EXPIRABLE`); expiry likewise cascades the settlement `DISPUTED → FINALIZED`."

    Design: Corner/errors/dispute_resolution_window_elapsed_then_expire
    """
    pipe = single_member_journey(stage="FINALIZED")
    settlement_id = pipe["settlement"]["id"]
    dispute = file_dispute(settlement_id, pipe["group"]["id"])
    begin_review(dispute["id"])

    # A year past filing: the resolution window has elapsed under any plausible
    # window length, and expiry is permitted.
    set_clock(CLOCK_RESOLUTION_PAST)
    late = api.resolve_dispute(
        dispute["id"], {"outcome": "UPHELD"}, make_dispute_adjudicator_headers("adj-9")
    )
    validate_error(late, ApiErrorId.ERR_DISPUTE_RESOLUTION_WINDOW_ELAPSED)
    reread = validate_success(api.get_dispute(dispute["id"], dispute_adjudicator_headers))
    assert reread["dispute_status"] == "UNDER_REVIEW"

    expired = validate_success(api.expire_dispute(dispute["id"], dispute_adjudicator_headers))
    assert expired["dispute_status"] == "EXPIRED"
    settlement = get_settlement(settlement_id)
    assert settlement["settlement_status"] == "FINALIZED"
    assert settlement["net_payable_cents"] == 74200, "expiry returns amounts unchanged"
    assert settlement["finalized_on"] == "2027-06-01"


def test_dispute_file_after_window_rejected(api):
    """PRD §3.11: "Filing requires the settlement to be in `FINALIZED` (`ERR_SETTLEMENT_NOT_FINAL`) and requires the logical clock date to be on or before `finalized_on` plus the dispute window (`ERR_DISPUTE_WINDOW_CLOSED`)."

    Design: Corner/validations/dispute_file_after_window_rejected
    """
    pipe = single_member_journey(stage="FINALIZED")
    settlement_id = pipe["settlement"]["id"]

    # A full year after finalization the filing window is closed under any
    # plausible window length.
    set_clock(CLOCK_WINDOW_PAST)
    resp = api.create_dispute(
        settlement_id,
        create_dispute_payload(
            dispute_ref="D-LATE", reason_code="BENCHMARK_ERROR",
            claimed_adjustment_cents=1000,
        ),
        make_practice_group_rep_headers(pipe["group"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_DISPUTE_WINDOW_CLOSED)
    assert get_settlement(settlement_id)["settlement_status"] == "FINALIZED", (
        "a rejected filing must not flip the settlement to DISPUTED"
    )


def test_practice_group_rep_files_and_withdraws_own_dispute(api):
    """PRD §3.11: "Filing transitions the settlement `FINALIZED → DISPUTED` and stamps `filed_on` with the logical clock date. The dispute's `dispute_status` is created as `FILED`."
    PRD §3.11: "The owning `PracticeGroupRep` may withdraw (`FILED → WITHDRAWN` or `UNDER_REVIEW → WITHDRAWN`); the scope check of §2.1 enforces ownership (`ERR_FORBIDDEN_GROUP_SCOPE`), and withdrawal cascades the settlement `DISPUTED → FINALIZED`."
    PRD §3.11: "When a dispute exits via `OVERRULED`, `WITHDRAWN`, or `EXPIRED`, the settlement returns to `FINALIZED` with `finalized_on` unchanged — the original dispute-window anchor is preserved, so the mark-settled and authorize-distribution windows continue to be measured from the first finalization, not from any dispute resolution."

    Design: Corner/rbac/practice_group_rep_files_and_withdraws_own_dispute
    """
    pipe = single_member_journey(stage="FINALIZED")
    settlement_id = pipe["settlement"]["id"]
    rep = make_practice_group_rep_headers(pipe["group"]["id"])

    # One day past finalization: inside the dispute window under any plausible
    # window length; filed_on must stamp from this clock.
    set_clock(CLOCK_DISPUTE)
    filed = validate_success(api.create_dispute(
        settlement_id,
        create_dispute_payload(
            dispute_ref="D-1", reason_code="CLAIMS_MISSING", claimed_adjustment_cents=5000
        ),
        rep,
    ), 201)
    assert filed["dispute_status"] == "FILED"
    assert filed["filed_on"] == "2027-06-02", "filed_on stamps from the logical clock"
    assert get_settlement(settlement_id)["settlement_status"] == "DISPUTED"

    withdrawn = validate_success(api.withdraw_dispute(filed["id"], rep))
    assert withdrawn["dispute_status"] == "WITHDRAWN"
    settlement = get_settlement(settlement_id)
    assert settlement["settlement_status"] == "FINALIZED"
    assert settlement["net_payable_cents"] == 74200, "withdrawal leaves amounts unchanged"
    assert settlement["finalized_on"] == "2027-06-01", (
        "the dispute-window anchor is not restarted by a withdrawn dispute"
    )


def test_adjudicator_cannot_file_dispute(api, dispute_adjudicator_headers):
    """PRD §3.11: "A `PracticeGroupRep` whose group owns the contract behind a finalized settlement may file a `SettlementDispute` by supplying a `dispute_ref` unique within the settlement, a `reason_code` drawn from `ATTRIBUTION_ERROR`, `CLAIMS_MISSING`, `RISK_SCORE_ERROR`, `QUALITY_DATA_ERROR`, or `BENCHMARK_ERROR`, and a strictly positive `claimed_adjustment_cents`."
    PRD §2.1: "A request whose role is recognized but which is not authorized for the targeted endpoint is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."

    Design: Corner/rbac/adjudicator_cannot_file_dispute
    """
    pipe = single_member_journey(stage="FINALIZED")
    resp = api.create_dispute(
        pipe["settlement"]["id"],
        create_dispute_payload(
            dispute_ref="D-X", reason_code="BENCHMARK_ERROR", claimed_adjustment_cents=1000
        ),
        dispute_adjudicator_headers,
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)


def test_practice_group_rep_cannot_finalize(api):
    """PRD §3.10: "Finalization (`PROVISIONAL → FINALIZED`) is performed by a `SettlementOfficer` and is gated by two preconditions: the logical clock date must be at or after the year's `period_end` plus the reconciliation runout (`ERR_RECONCILIATION_RUNOUT_INCOMPLETE`), and `needs_recompute` must be `false` (`ERR_SETTLEMENT_STALE` while it is true)."
    PRD §2.1: "A request whose role is recognized but which is not authorized for the targeted endpoint is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."

    Design: Corner/rbac/practice_group_rep_cannot_finalize
    """
    pipe = single_member_journey(stage="SETTLEMENT")
    settlement_id = pipe["settlement"]["id"]
    set_clock(CLOCK_FINALIZE)
    resp = api.finalize_settlement(
        settlement_id, make_practice_group_rep_headers(pipe["group"]["id"])
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)
    assert get_settlement(settlement_id)["settlement_status"] == "PROVISIONAL"


def test_practice_group_rep_scope_violation_forbidden(api):
    """PRD §2.1: "The remaining role is entity-backed. When `X-User-Role` is `PracticeGroupRep`, `X-User-ID` is the `id` of the acting `PracticeGroup`; ownership checks on any resource that references a `PracticeGroup` compare the resource's foreign-key field to `X-User-ID`. A `PracticeGroupRep` caller attempting to read or mutate a settlement or a dispute whose underlying contract is owned by a different `PracticeGroup` is rejected with `ERR_FORBIDDEN_GROUP_SCOPE` (HTTP 403); this scope check is applied to settlement and dispute GET endpoints and to the dispute create and withdraw actions whenever the caller's role is `PracticeGroupRep`."

    Design: Corner/rbac/practice_group_rep_scope_violation_forbidden
    """
    pipe = single_member_journey(stage="SETTLEMENT")
    settlement_id = pipe["settlement"]["id"]
    other_group = make_group(group_name="G2", tin="100000002")

    scoped_out = api.get_settlement(
        settlement_id, make_practice_group_rep_headers(other_group["id"])
    )
    validate_error(scoped_out, ApiErrorId.ERR_FORBIDDEN_GROUP_SCOPE)

    own = api.get_settlement(
        settlement_id, make_practice_group_rep_headers(pipe["group"]["id"])
    )
    data = validate_success(own)
    assert data["net_payable_cents"] == 74200
