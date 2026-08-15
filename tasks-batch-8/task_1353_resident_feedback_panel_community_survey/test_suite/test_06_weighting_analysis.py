"""Weight snapshots (RIM vs POST_STRAT divergence, OCC, supersede, computability),
wave analysis read (projected/final rates, representativeness score)."""
import pytest

from test_helpers import (
    validate_success, validate_error, ApiErrorId, TEST_USERS,
    create_cell, create_panelist, create_locked_instrument, create_fielding_wave,
    create_wave, dispatch_invitation, submit_response, accept_response,
    set_clock, current_wave_version, create_snapshot, create_snapshot_payload,
)

PM = TEST_USERS["panel_manager"]
DA = TEST_USERS["data_analyst"]

from test_helpers import api_client as _api


def _enroll(pid):
    return validate_success(_api.enroll_panelist(pid, PM), 200)


def _cell_with_panelists(target_size, n, age_band="AGE_18_29", district="D1",
                         tenure="RENTER", locale="en"):
    cell = create_cell(target_size=target_size, age_band=age_band,
                       district=district, tenure_bucket=tenure)
    out = []
    for _ in range(n):
        p = create_panelist(age_band=age_band, district=district,
                            tenure_bucket=tenure, preferred_locale=locale)
        out.append(_enroll(p["id"]))
    return cell, out


def _invite_and_answer(wave_id, panelists, completeness=100, seconds=300):
    responses = []
    for p in panelists:
        inv = dispatch_invitation(wave_id, p["id"])
        r = submit_response(inv["id"], completeness_pct=completeness,
                            completion_seconds=seconds)
        accept_response(r["id"])
        responses.append(r)
    return responses


def test_weighting_method_rim_vs_post_strat_divergence(api):
    """PRD §3.7: "Under `POST_STRAT`, each represented cell's raw weight is its
    `target_size` divided by the number of the wave's accepted responses seated in
    it, and every respondent in a cell receives that cell's raw weight. Under
    `RIM`, every respondent starts at weight 1 and a single deterministic rake pass
    runs over a fixed margin order: first the age-band margin, where each band's
    target is the sum of `target_size` across its cells and each band's current
    total is the sum of the weights of respondents seated in that band, scaling
    every such respondent's weight by the band's target divided by its current
    total; then the tenure margin, computed the same way over `RENTER` and `OWNER`
    after the age adjustment. Because both margins are attributes of whole cells,
    respondents sharing a cell still share a weight under raking; the two methods
    nevertheless diverge whenever cells share a margin."

    Design: Difficulty/dual_variant_calc/weighting_method_rim_vs_post_strat_divergence
    """
    c1, ps1 = _cell_with_panelists(3, 1, age_band="AGE_18_29", tenure="RENTER")
    c2, ps2 = _cell_with_panelists(1, 1, age_band="AGE_30_44", tenure="RENTER")
    c3, ps3 = _cell_with_panelists(2, 1, age_band="AGE_30_44", tenure="OWNER")
    instr = create_locked_instrument()
    wave = create_fielding_wave(instr["id"], min_response_rate=1.0)
    _invite_and_answer(wave["id"], ps1 + ps2 + ps3)
    set_clock("2026-08-11T00:00:00Z")
    validate_success(api.close_wave(wave["id"], PM), 200)

    snap_ps = create_snapshot(wave["id"], method="POST_STRAT")
    snap_rim = create_snapshot(wave["id"], method="RIM")

    # POST_STRAT: raw 3, 1, 2 -> normalized to mass 3 -> 1.5 / 0.5 / 1.0.
    ps_shares = snap_ps["weighted_cell_shares"]
    assert ps_shares[c1["id"]] == pytest.approx(0.5, abs=1e-6)
    assert ps_shares[c2["id"]] == pytest.approx(0.166667, abs=1e-6)
    assert ps_shares[c3["id"]] == pytest.approx(0.333333, abs=1e-6)

    # RIM: age margin AGE_18_29 -> 3/1 = 3, AGE_30_44 -> 3/2 = 1.5; tenure margin
    # RENTER -> 4/4.5, OWNER -> 2/1.5; renormalized to mass 3.
    rim_shares = snap_rim["weighted_cell_shares"]
    assert rim_shares[c1["id"]] == pytest.approx(0.444444, abs=1e-6)
    assert rim_shares[c2["id"]] == pytest.approx(0.222222, abs=1e-6)
    assert rim_shares[c3["id"]] == pytest.approx(0.333333, abs=1e-6)

    ps_after = validate_success(api.get_weight_snapshot(snap_ps["id"], DA), 200)
    assert ps_after["status"] == "SUPERSEDED"
    assert snap_rim["weight_mass"] == pytest.approx(3, abs=1e-6)


def test_weighting_post_strat_equal_weights_within_cell(api):
    """PRD §3.7: "Under `POST_STRAT`, each represented cell's raw weight is its
    `target_size` divided by the number of the wave's accepted responses seated in
    it, and every respondent in a cell receives that cell's raw weight." and
    "The snapshot's `weight_mass` is the sum of the final weights, equal to N up to
    rounding; `accepted_count` records N; `weighted_cell_shares` maps each
    represented cell to the sum of its respondents' weights divided by
    `weight_mass` ..."

    Design: Difficulty/dual_variant_calc/weighting_method_rim_vs_post_strat_divergence
    """
    c1, ps1 = _cell_with_panelists(3, 1, age_band="AGE_18_29", tenure="RENTER")
    c2, ps2 = _cell_with_panelists(1, 1, age_band="AGE_30_44", tenure="RENTER")
    c3, ps3 = _cell_with_panelists(2, 1, age_band="AGE_30_44", tenure="OWNER")
    instr = create_locked_instrument()
    wave = create_fielding_wave(instr["id"], min_response_rate=1.0)
    _invite_and_answer(wave["id"], ps1 + ps2 + ps3)
    set_clock("2026-08-11T00:00:00Z")
    validate_success(api.close_wave(wave["id"], PM), 200)

    snap = create_snapshot(wave["id"], method="POST_STRAT")
    assert snap["accepted_count"] == 3
    assert snap["weight_mass"] == pytest.approx(3, abs=1e-6)
    shares = snap["weighted_cell_shares"]
    assert shares[c1["id"]] == pytest.approx(0.5, abs=1e-6)
    assert shares[c2["id"]] == pytest.approx(0.166667, abs=1e-6)
    assert shares[c3["id"]] == pytest.approx(0.333333, abs=1e-6)


def test_projected_vs_final_response_rate_divergence(api):
    """PRD §3.7: "While the wave is `FIELDING`, the projection credits expected
    uptake on still-open invitations: `completed_count` plus half of the
    invitations still `SENT`, divided by `invited_count`. Once the wave is
    `CLOSED`, `WEIGHTED`, or `PUBLISHED`, the projection equals the final ratio of
    `completed_count` to `invited_count`. When no invitations were ever dispatched,
    the rate is 0. The `final_response_rate` is that completions-over-invitations
    ratio once the wave has closed and null before then ..."

    Design: Difficulty/dual_variant_calc/projected_vs_final_response_rate_divergence
    """
    c1, ps1 = _cell_with_panelists(6, 2, age_band="AGE_18_29", tenure="RENTER")
    c2, ps2 = _cell_with_panelists(6, 2, age_band="AGE_30_44", tenure="OWNER")
    instr = create_locked_instrument()
    wave = create_fielding_wave(instr["id"], min_response_rate=0.9)
    # 4 invitations SENT; only the first responds (completed 1, open SENT 3).
    first = dispatch_invitation(wave["id"], ps1[0]["id"])
    for p in ps1[1:] + ps2:
        dispatch_invitation(wave["id"], p["id"])
    submit_response(first["id"])

    mid = validate_success(api.get_wave_analysis(wave["id"], DA), 200)
    assert mid["projected_response_rate"] == pytest.approx(0.625, abs=1e-6)
    # PRD §3.7: final_response_rate is "null before then [the wave's close]".
    assert mid["final_response_rate"] is None

    set_clock("2026-08-11T00:00:00Z")
    validate_success(api.close_wave(wave["id"], PM), 200)
    post = validate_success(api.get_wave_analysis(wave["id"], DA), 200)
    assert post["projected_response_rate"] == pytest.approx(0.25, abs=1e-6)
    assert post["final_response_rate"] == pytest.approx(0.25, abs=1e-6)


def test_projected_rate_null_final_before_close(api):
    """PRD §3.7: "The `final_response_rate` is that completions-over-invitations
    ratio once the wave has closed and null before then ..."

    Design: Difficulty/dual_variant_calc/projected_vs_final_response_rate_divergence
    """
    c1, ps1 = _cell_with_panelists(6, 1)
    instr = create_locked_instrument()
    wave = create_fielding_wave(instr["id"])
    dispatch_invitation(wave["id"], ps1[0]["id"])

    mid = validate_success(api.get_wave_analysis(wave["id"], DA), 200)
    assert mid["final_response_rate"] is None
    # FIELDING: (0 completed + 0.5 * 1 open) / 1 invited = 0.5
    assert mid["projected_response_rate"] == pytest.approx(0.5, abs=1e-6)


def test_representativeness_score_min_capped_multi_input(api):
    """PRD §3.1: "Let T be the sum of `target_size` over every cell; cells with
    `target_size` 0 contribute nothing to T or to the score, and if T is 0 the
    score is 100. Otherwise each cell with a positive target contributes its
    deficit divided by its `target_size` — the ratio capped at 1.0 — weighted by
    that cell's share of T, and the score is 100 minus 100 times the sum of those
    weighted ratios, reported to six decimal places with round-half-up rounding."

    Design: Difficulty/combinatorial_formula/representativeness_score_min_capped_multi_input
    """
    c1 = create_cell(target_size=4)
    c2 = create_cell(target_size=1, age_band="AGE_30_44")
    c3 = create_cell(target_size=2, age_band="AGE_45_64", district="D2",
                     tenure_bucket="OWNER")
    c4 = create_cell(target_size=0, age_band="AGE_65_PLUS", district="D2",
                     tenure_bucket="OWNER")
    p1 = create_panelist()
    _enroll(p1["id"])                                            # seats into c1
    p2 = create_panelist(age_band="AGE_30_44")
    _enroll(p2["id"])                                            # seats into c2
    instr = create_locked_instrument()
    wave = create_wave(instr["id"])

    analysis = validate_success(api.get_wave_analysis(wave["id"], DA), 200)
    # T = 7; deficits 3/4*4/7 + 0 + 2/2*2/7 = 5/7 -> 100 - 500/7 = 28.571429
    assert analysis["representativeness_score"] == pytest.approx(28.571429, abs=1e-6)
    c2_after = validate_success(api.get_panel_cell(c2["id"], PM), 200)
    assert c2_after["status"] == "SATURATED"
    c4_after = validate_success(api.get_panel_cell(c4["id"], PM), 200)
    assert c4_after["status"] == "SATURATED"


def test_representativeness_score_full_seating_is_100(api):
    """PRD §3.1: "A program seated exactly to target everywhere scores 100."

    Design: Difficulty/combinatorial_formula/representativeness_score_min_capped_multi_input
    """
    cell = create_cell(target_size=2)
    _enroll(create_panelist()["id"])
    _enroll(create_panelist()["id"])
    instr = create_locked_instrument()
    wave = create_wave(instr["id"])
    analysis = validate_success(api.get_wave_analysis(wave["id"], DA), 200)
    assert analysis["representativeness_score"] == pytest.approx(100, abs=1e-6)


def test_weights_not_computable_returns_422(api):
    """PRD §3.7: "The weights are computed over the wave's `ACCEPTED` responses
    only, grouped by each respondent's `home_cell_id`; `SUBMITTED`, `QUARANTINED`,
    and `DISCARDED` responses never enter the computation. Let N be the number of
    included responses: when N is 0, creation is refused with
    `ERR_WEIGHTS_NOT_COMPUTABLE` ..."

    Design: Corner/calculations/corner_weights_not_computable_returns_422
    """
    cell, (p1,) = _cell_with_panelists(5, 1)
    instr = create_locked_instrument()
    wave = create_fielding_wave(instr["id"])
    inv = dispatch_invitation(wave["id"], p1["id"])
    submit_response(inv["id"])  # stays SUBMITTED, never accepted
    set_clock("2026-08-11T00:00:00Z")
    validate_success(api.close_wave(wave["id"], PM), 200)

    err = validate_error(
        api.create_weight_snapshot(
            wave["id"], create_snapshot_payload(current_wave_version(wave["id"])), DA),
        ApiErrorId.ERR_WEIGHTS_NOT_COMPUTABLE)
    assert err["error_id"] == "ERR_WEIGHTS_NOT_COMPUTABLE"


def test_design_effect_uniform_weights(api):
    """PRD §3.7: "`design_effect` is one plus the square of the ratio of the
    standard deviation of the included weights to their mean." and "First the raw
    weights are normalized so they sum to N ... Then each weight is trimmed at five
    times the mean weight ... Finally the weights are renormalized exactly once ..."

    Design: Corner/calculations/corner_design_effect_uniform_weights
    """
    # One cell with target 3 and 3 accepted respondents -> uniform weights 1.0.
    cell, panelists = _cell_with_panelists(3, 3)
    instr = create_locked_instrument()
    wave = create_fielding_wave(instr["id"])
    _invite_and_answer(wave["id"], panelists)
    set_clock("2026-08-11T00:00:00Z")
    validate_success(api.close_wave(wave["id"], PM), 200)

    snap = create_snapshot(wave["id"], method="POST_STRAT")
    assert snap["design_effect"] == pytest.approx(1.0, abs=1e-6)
    assert snap["weight_mass"] == pytest.approx(3, abs=1e-6)
    assert snap["accepted_count"] == 3


def test_response_rate_excludes_declined_and_expired(api):
    """PRD §3.7: "The `final_response_rate` is that completions-over-invitations
    ratio once the wave has closed and null before then ..." and "Once the wave is
    `CLOSED`, `WEIGHTED`, or `PUBLISHED`, the projection equals the final ratio of
    `completed_count` to `invited_count`."

    Design: Corner/calculations/corner_response_rate_excludes_declined_and_expired
    """
    cell, (p1, p2, p3) = _cell_with_panelists(5, 3)
    instr = create_locked_instrument()
    wave = create_fielding_wave(instr["id"])
    inv1 = dispatch_invitation(wave["id"], p1["id"])
    inv2 = dispatch_invitation(wave["id"], p2["id"])
    dispatch_invitation(wave["id"], p3["id"])  # never acts -> expires at close
    submit_response(inv1["id"])
    validate_success(api.decline_invitation(inv2["id"], PM), 200)
    set_clock("2026-08-11T00:00:00Z")
    validate_success(api.close_wave(wave["id"], PM), 200)

    analysis = validate_success(api.get_wave_analysis(wave["id"], DA), 200)
    assert analysis["final_response_rate"] == pytest.approx(0.333333, abs=1e-6)


def test_analysis_empty_program_defaults(api):
    """PRD §3.1: "Let T be the sum of `target_size` over every cell; ... and if T
    is 0 the score is 100." and PRD §3.7: "When no invitations were ever
    dispatched, the rate is 0."

    Design: Corner/endpoints/corner_analysis_empty_program_defaults
    """
    instr = create_locked_instrument()
    wave = create_wave(instr["id"])  # DRAFT, never fielded, no cells exist
    analysis = validate_success(api.get_wave_analysis(wave["id"], DA), 200)
    assert analysis["representativeness_score"] == pytest.approx(100, abs=1e-6)
    assert analysis["projected_response_rate"] == pytest.approx(0, abs=1e-6)
    # PRD §3.7: the final rate is "null before then [close]"; a DRAFT wave
    # has not closed, so it is null (not 0).
    assert analysis["final_response_rate"] is None


def test_stale_wave_version_returns_412(api):
    """PRD §2.7: "Creating a weight snapshot against a wave —
    `POST /feedback-panel/survey-waves/{id}/weight-snapshots` — requires the
    request to carry `expected_wave_version` equal to that wave's current
    `version`. If the wave's version has advanced since the client last observed
    it — because a prior snapshot was created or finalized, or a pool mutation
    occurred — the create is rejected with `ERR_STALE_WAVE_VERSION` (HTTP 412)
    rather than silently superseding state the client never saw."

    Design: Corner/validations/corner_stale_wave_version_returns_412
    """
    cell, (p1,) = _cell_with_panelists(5, 1)
    instr = create_locked_instrument()
    wave = create_fielding_wave(instr["id"])
    _invite_and_answer(wave["id"], [p1])
    set_clock("2026-08-11T00:00:00Z")
    validate_success(api.close_wave(wave["id"], PM), 200)
    wv1 = current_wave_version(wave["id"])

    snap1 = create_snapshot(wave["id"], method="POST_STRAT",
                            expected_wave_version=wv1)
    # The first create advanced the wave version; replaying wv1 is stale.
    err = validate_error(
        api.create_weight_snapshot(wave["id"],
                                   create_snapshot_payload(wv1, method="RIM"), DA),
        ApiErrorId.ERR_STALE_WAVE_VERSION)
    assert err["error_id"] == "ERR_STALE_WAVE_VERSION"
    s1_after = validate_success(api.get_weight_snapshot(snap1["id"], DA), 200)
    assert s1_after["status"] == "PROVISIONAL"


def test_finalize_superseded_snapshot_returns_409(api):
    """PRD §3.7: "The wave must be `CLOSED` (else `ERR_WAVE_NOT_CLOSED`), and the
    snapshot must be the wave's latest — one already `SUPERSEDED` fails with
    `ERR_SNAPSHOT_SUPERSEDED`."

    Design: Corner/validations/corner_finalize_superseded_snapshot_returns_409
    """
    cell, (p1,) = _cell_with_panelists(5, 1)
    instr = create_locked_instrument()
    wave = create_fielding_wave(instr["id"])
    _invite_and_answer(wave["id"], [p1])
    set_clock("2026-08-11T00:00:00Z")
    validate_success(api.close_wave(wave["id"], PM), 200)

    s1 = create_snapshot(wave["id"], method="POST_STRAT")
    s2 = create_snapshot(wave["id"], method="RIM")  # supersedes s1
    err = validate_error(api.finalize_weight_snapshot(s1["id"], DA),
                         ApiErrorId.ERR_SNAPSHOT_SUPERSEDED)
    assert err["error_id"] == "ERR_SNAPSHOT_SUPERSEDED"
    s2_after = validate_success(api.get_weight_snapshot(s2["id"], DA), 200)
    assert s2_after["status"] == "PROVISIONAL"


def test_snapshot_create_on_fielding_wave_returns_409(api):
    """PRD §3.7: "Creation is permitted only against a `CLOSED` or `WEIGHTED` wave:
    against any other non-terminal status it fails with `ERR_WAVE_INVALID_STATE`,
    and against a terminal wave with `ERR_WAVE_ALREADY_TERMINAL`."

    Design: Corner/errors/corner_snapshot_create_on_fielding_wave_returns_409
    """
    cell, (p1,) = _cell_with_panelists(5, 1)
    instr = create_locked_instrument()
    wave = create_fielding_wave(instr["id"])
    wv = current_wave_version(wave["id"])
    resp = api.create_weight_snapshot(wave["id"], create_snapshot_payload(wv), DA)
    # FIELDING is a non-terminal status other than CLOSED/WEIGHTED: the PRD
    # sentence above pins ERR_WAVE_INVALID_STATE exactly.
    err = validate_error(resp, ApiErrorId.ERR_WAVE_INVALID_STATE)
    assert err["error_id"] == "ERR_WAVE_INVALID_STATE"
    assert resp.status_code == 409
