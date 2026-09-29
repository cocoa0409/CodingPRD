"""The life-of-loan sweep and the read-only projection of a preliminary map.

The sweep has two independently filtered phases and reports counters that must
agree with the rows it actually touched.  The projection reports the damage a
panel would do without touching a single row.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    ApiErrorId,
    api_client,
    correct_geocode,
    create_community,
    create_property,
    create_structure,
    issue_determination,
    make_agency_headers,
    make_analyst_headers,
    open_folio,
    publish_panel,
    read_folio,
    run_monitoring,
    set_clock,
    setup_base_chain,
    setup_folio_with_mandatory_notice,
    walk_panel_to_lfd_issued,
)

CLOCK = "2026-08-01T00:00:00Z"
DEADLINE = "2026-09-15T00:00:00Z"


def assert_instant(actual, expected_utc):
    """Compare a timestamp field to an instant.

    PRD 2.4 fixes the wire format at three fractional digits, so an instant the
    test supplied as ``...T00:00:00Z`` is read back as ``...T00:00:00.000Z``.
    """
    assert actual is not None, f"expected the instant {expected_utc}, got null"
    assert actual.replace(".000Z", "Z") == expected_utc, (
        f"{actual!r} is not the instant {expected_utc}"
    )


def read_determination(determination_id):
    return validate_success(
        api_client.get_determination(determination_id, headers=make_analyst_headers())
    )


def determinations_for(loan_folio_id):
    return validate_paginated(
        api_client.list_determinations(
            headers=make_analyst_headers(), params={"loan_folio_id": loan_folio_id}
        )
    )


def test_the_sweep_admits_only_flagged_determinations_and_only_lapsed_notices():
    """Both phases filter, and they filter on different things.  A determination that
    was never flagged is never re-read, and a notice whose response window is still
    open is not expired — so a sweep run the day the notice went out reports one
    determination scanned and no notices closed.

    PRD §3.7: "Phase one takes as its scope every determination whose `status` is `FLAGGED_FOR_REVIEW`, restricted by whichever filters were supplied, and processes them in `created_at` ascending order; that ordering is total for a single-writer request sequence and the identifier is never consulted as a tie-break."
    PRD §3.7: "For each flagged determination the sweep re-selects the governing panel by the effective-panel rule of Section 3.5 and re-classifies the structure under the lenient variant, so an `INDETERMINATE` re-read carries the flagged determination's own `zone_code` and `sfha_flag` forward rather than flipping the borrower into the hazard area."
    PRD §3.7: "When the re-classification reproduces both the flagged determination's `zone_code` and its `sfha_flag`, nothing of substance has changed and the determination returns `FLAGGED_FOR_REVIEW → ISSUED`: `flagged_reason` is cleared to null, `map_panel_id` is repointed at the panel the re-selection chose, the folio's `pending_redetermination_count` is decremented and its `compliance_posture` recomputed."
    PRD §3.7: "No new determination row is created and no notice is sent."
    PRD §3.7: "Every compliance notice whose `status` is `SENT` and whose `response_deadline_at` is strictly earlier than the current logical instant moves `SENT → EXPIRED` with `closed_at` set and the owning folio's `open_notice_count` re-counted, and `notices_expired` is incremented once per notice so closed."
    PRD §3.7: "The response reports `determinations_scanned` (the size of phase one's scope), `redeterminations_cleared`, `redeterminations_issued`, `notices_sent`, `notices_expired`, and `run_at`, the logical instant at which the sweep ran."

    Design: Corner/calculations/corner_monitoring_sweep_scans_only_flagged_and_expires_only_lapsed
    """
    chain = setup_folio_with_mandatory_notice(
        clock=CLOCK,
        property_overrides={
            "latitude": 25.7600,
            "longitude": -80.1900,
            "geocode_method": "ZIP_CENTROID",
            "geocode_confidence_score": 0.80,
        },
        structure_overrides={"sfha_offset_ft": -500.0},
    )
    notice = chain["notice"]
    assert_instant(notice["response_deadline_at"], DEADLINE)

    other_property = create_property(
        chain["community"]["id"], street_address="27 Bayfront Rd",
        latitude=25.7620, longitude=-80.1920,
        geocode_method="ROOFTOP", geocode_confidence_score=0.96,
    )
    other_structure = create_structure(
        other_property["id"], foundation_type="CRAWLSPACE",
        replacement_cost_cents=21_000_000, sfha_offset_ft=-12.0,
    )
    other_folio = open_folio(
        chain["lender"]["id"], other_property["id"], loan_number="LN-4402",
        borrower_user_id="borrower-b", principal_balance_cents=40_000_000,
    )
    other_determination = issue_determination(
        other_folio["id"], other_structure["id"],
        expected_version=other_folio["version"],
    )
    other_folio = read_folio(other_folio["id"])

    correct_geocode(
        chain["property"]["id"], latitude=25.7617, longitude=-80.1918,
        geocode_method="ROOFTOP", geocode_confidence_score=0.97,
    )
    assert read_determination(chain["determination"]["id"])["status"] == "FLAGGED_FOR_REVIEW"
    assert read_determination(other_determination["id"])["status"] == "ISSUED"

    run = run_monitoring()
    assert run["determinations_scanned"] == 1, (
        "only the flagged determination is in phase one's scope"
    )
    assert run["redeterminations_cleared"] == 1, (
        "the lenient re-read of offset -500.0 reproduces AE/true, so the flag clears"
    )
    assert run["redeterminations_issued"] == 0
    assert run["notices_sent"] == 0
    assert run["notices_expired"] == 0, (
        "the notice's deadline is not strictly earlier than the clock"
    )
    assert_instant(run["run_at"], CLOCK)

    cleared = read_determination(chain["determination"]["id"])
    assert cleared["status"] == "ISSUED"
    assert cleared["flagged_reason"] is None
    assert cleared["map_panel_id"] == chain["panel"]["id"]
    _, meta = determinations_for(chain["folio"]["id"])
    assert meta["total_count"] == 1, "a cleared review supersedes nothing"

    folio = read_folio(chain["folio"]["id"])
    assert folio["pending_redetermination_count"] == 0
    assert folio["open_notice_count"] == 1

    untouched = read_folio(other_folio["id"])
    assert untouched == other_folio, (
        "the out-of-scope folio was not written at all, down to its version"
    )
    still_sent = validate_success(
        api_client.get_compliance_notice(notice["id"], headers=chain["lender_headers"])
    )
    assert still_sent["status"] == "SENT"
    assert still_sent["closed_at"] is None


def test_a_community_scoped_sweep_leaves_the_other_communitys_flag_standing():
    """The scope filter bounds phase one only, and it bounds it strictly: the flagged
    determination in the other community is not reconciled as a side effect, so its
    folio is still reporting REVIEW_PENDING when the scoped run returns.  A later
    unscoped run picks up exactly the row the first one skipped.

    PRD §3.7: "The sweep accepts two optional filters, `community_id` and `map_panel_id`, which narrow the work to one community or one panel; with neither supplied it processes everything outstanding."
    PRD §3.7: "Phase one takes as its scope every determination whose `status` is `FLAGGED_FOR_REVIEW`, restricted by whichever filters were supplied, and processes them in `created_at` ascending order; that ordering is total for a single-writer request sequence and the identifier is never consulted as a tie-break."
    PRD §3.7: "When the re-classification reproduces both the flagged determination's `zone_code` and its `sfha_flag`, nothing of substance has changed and the determination returns `FLAGGED_FOR_REVIEW → ISSUED`: `flagged_reason` is cleared to null, `map_panel_id` is repointed at the panel the re-selection chose, the folio's `pending_redetermination_count` is decremented and its `compliance_posture` recomputed."
    PRD §3.7: "Phase two always runs, even when phase one's scope was empty."
    PRD §3.6: "Third, if `pending_redetermination_count` is greater than zero the posture is `REVIEW_PENDING`."

    Design: Corner/endpoints/corner_monitoring_run_honours_community_scope_filter
    """
    florida = setup_base_chain(
        clock=CLOCK,
        property_overrides={
            "geocode_method": "PARCEL_CENTROID",
            "geocode_confidence_score": 0.88,
        },
        structure_overrides={"sfha_offset_ft": -500.0},
        folio_overrides={"loan_number": "LN-FL-01", "borrower_user_id": "borrower-fl"},
    )

    carolina_community = create_community(
        community_id_code="370229", name="New Hanover County NC", state_code="NC",
    )
    carolina_panel = publish_panel(
        carolina_community["id"], map_panel_number="37129C0088H",
        zone_code="AE", base_flood_elevation_ft=14.20,
        effective_date="2018-04-03T00:00:00Z",
    )
    carolina_property = create_property(
        carolina_community["id"], street_address="5 Masonboro Loop",
        city="Wilmington", postal_code="28409", map_panel_number="37129C0088H",
        latitude=34.1954, longitude=-77.8710,
        geocode_method="PARCEL_CENTROID", geocode_confidence_score=0.86,
    )
    carolina_structure = create_structure(
        carolina_property["id"], foundation_type="PIER_PILE",
        replacement_cost_cents=24_000_000, sfha_offset_ft=-500.0,
    )
    carolina_folio = open_folio(
        florida["lender"]["id"], carolina_property["id"], loan_number="LN-NC-01",
        borrower_user_id="borrower-nc", principal_balance_cents=21_000_000,
        policy_anniversary_date="2027-05-01T00:00:00Z",
    )
    carolina_determination = issue_determination(
        carolina_folio["id"], carolina_structure["id"],
        expected_version=carolina_folio["version"],
    )

    correct_geocode(
        florida["property"]["id"], latitude=25.7618, longitude=-80.1919,
        geocode_method="ROOFTOP", geocode_confidence_score=0.98,
    )
    correct_geocode(
        carolina_property["id"], latitude=34.1955, longitude=-77.8711,
        geocode_method="ROOFTOP", geocode_confidence_score=0.97,
    )
    for determination_id in (florida["determination"]["id"], carolina_determination["id"]):
        flagged = read_determination(determination_id)
        assert flagged["status"] == "FLAGGED_FOR_REVIEW"
        assert flagged["flagged_reason"] == "GEOCODE_CORRECTION"

    scoped = run_monitoring({"community_id": florida["community"]["id"]})
    assert scoped["determinations_scanned"] == 1, "the filter bounds phase one's scope"
    assert scoped["redeterminations_cleared"] == 1
    assert scoped["redeterminations_issued"] == 0
    assert scoped["notices_sent"] == 0
    assert scoped["notices_expired"] == 0, "there is no SENT notice anywhere to expire"

    assert read_determination(florida["determination"]["id"])["status"] == "ISSUED"
    assert read_determination(carolina_determination["id"])["status"] == "FLAGGED_FOR_REVIEW", (
        "the out-of-scope determination is not reconciled as a side effect"
    )
    carolina_after_scope = read_folio(carolina_folio["id"])
    assert carolina_after_scope["pending_redetermination_count"] == 1
    assert carolina_after_scope["compliance_posture"] == "REVIEW_PENDING"

    unscoped = run_monitoring()
    assert unscoped["determinations_scanned"] == 1, (
        "only the row the scoped run skipped is still flagged"
    )
    assert unscoped["redeterminations_cleared"] == 1
    assert unscoped["notices_sent"] == 0
    assert unscoped["notices_expired"] == 0

    assert read_determination(carolina_determination["id"])["status"] == "ISSUED"
    assert read_folio(carolina_folio["id"])["pending_redetermination_count"] == 0
    assert read_folio(florida["folio"]["id"])["pending_redetermination_count"] == 0


def test_the_projection_counts_the_damage_of_a_preliminary_panel_and_writes_nothing():
    """The six figures are each pinned to a different input.  A building already inside
    the hazard area is not "newly in" even though the boundary moved past it again; a
    building with no base flood elevation cannot show a BFE increase; and only the
    newly-in buildings contribute to the aggregate obligation.  Nothing is written.

    PRD §3.3: "The projection creates no determination, mutates no structure and sends no notice."
    PRD §3.3: "For each structure it locates the loan folio on the same property whose `current_determination_id` names a determination for that structure; structures with no such folio are skipped entirely and do not count toward any figure."
    PRD §3.3: "`structures_evaluated` is the number of structures that had a folio."
    PRD §3.3: "`newly_in_sfha_count` is the number of those structures whose current determination has a false `sfha_flag` while the prospective classification yields a true one."
    PRD §3.3: "`newly_out_of_sfha_count` is the mirror image: current `sfha_flag` true, prospective `sfha_flag` false."
    PRD §3.3: "`bfe_increase_count` is the number of structures whose current determination carries a non-null `base_flood_elevation_ft`, where the panel under study also carries a non-null `base_flood_elevation_ft`, and where the panel's figure is greater than the determination's."
    PRD §3.3: "`folios_requiring_new_notice_count` is the number of distinct folios behind the newly-in-SFHA structures whose `insurance_status` is `NONE` or `NOT_REQUIRED` — the folios that would need a fresh mandatory-purchase notice."
    PRD §3.3: "`aggregate_new_required_coverage_cents` is the sum, over the newly-in-SFHA structures only, of the required coverage each would carry under the prospective classification, computed by the coverage rule of Section 3.6 using the prospective determination, the structure, its folio and its community."
    PRD §3.5: "The structure's effective offset in feet is its `sfha_offset_ft` minus the panel's `sfha_boundary_shift_ft`, which is how a panel that pushed the hazard boundary outward drags buildings into the SFHA without anyone re-surveying them."
    PRD §3.6: "`required_coverage_cents` is then the smallest of three integer amounts: the folio's `principal_balance_cents`, the structure's `replacement_cost_cents`, and that cap."

    Design: Corner/calculations/corner_impact_analysis_projects_counts_and_writes_nothing
    """
    inside = setup_base_chain(clock=CLOCK)
    preliminary = publish_panel(
        inside["community"]["id"],
        revision_sequence=2,
        supersedes_panel_id=inside["panel"]["id"],
        zone_code="VE",
        base_flood_elevation_ft=12.50,
        sfha_boundary_shift_ft=100.0,
        effective_date="2027-04-28T00:00:00Z",
        study_case_number="26-04-1234P",
    )
    assert preliminary["revision_status"] == "PRELIMINARY"
    assert inside["determination"]["sfha_flag"] is True
    assert inside["determination"]["base_flood_elevation_ft"] == 7.75

    outside_property = create_property(
        inside["community"]["id"], street_address="27 Bayfront Rd",
        latitude=25.7620, longitude=-80.1920,
        geocode_method="ROOFTOP", geocode_confidence_score=0.96,
    )
    outside_structure = create_structure(
        outside_property["id"], replacement_cost_cents=32_000_000, sfha_offset_ft=30.0,
    )
    outside_folio = open_folio(
        inside["lender"]["id"], outside_property["id"], loan_number="LN-4402",
        borrower_user_id="borrower-b", principal_balance_cents=19_000_000,
    )
    outside_determination = issue_determination(
        outside_folio["id"], outside_structure["id"],
        expected_version=outside_folio["version"],
    )
    assert outside_determination["sfha_flag"] is False
    assert outside_determination["zone_code"] == "X"
    assert outside_determination["base_flood_elevation_ft"] is None
    outside_folio = read_folio(outside_folio["id"])
    assert outside_folio["insurance_status"] == "NOT_REQUIRED"
    inside_folio = read_folio(inside["folio"]["id"])
    assert inside_folio["insurance_status"] == "NONE"

    projection = validate_success(
        api_client.get_impact_analysis(preliminary["id"], headers=make_analyst_headers())
    )
    assert projection["map_panel_id"] == preliminary["id"]
    assert projection["revision_status"] == "PRELIMINARY"
    assert projection["structures_evaluated"] == 2
    assert projection["newly_in_sfha_count"] == 1, (
        "offset 30.0 minus a 100.0 shift lands at -70.0, while the -12.0 building was "
        "already inside"
    )
    assert projection["newly_out_of_sfha_count"] == 0
    assert projection["bfe_increase_count"] == 1, (
        "only the building with a non-null 7.75 snapshot can show an increase to 12.50"
    )
    assert projection["folios_requiring_new_notice_count"] == 1
    assert projection["aggregate_new_required_coverage_cents"] == 19_000_000, (
        "min(19000000 principal, 32000000 replacement, 25000000 cap) for the newly-in "
        "building only"
    )

    for determination in (inside["determination"], outside_determination):
        after = read_determination(determination["id"])
        assert after["status"] == "ISSUED"
        assert after["map_panel_id"] == inside["panel"]["id"]
        assert after["zone_code"] == determination["zone_code"]
        assert after["version"] == determination["version"]
    _, meta = validate_paginated(
        api_client.list_determinations(
            headers=make_analyst_headers(), params={"map_panel_id": preliminary["id"]}
        )
    )
    assert meta["total_count"] == 0, "the projection minted no determination"
    _, notice_meta = validate_paginated(
        api_client.list_compliance_notices(
            headers=make_analyst_headers(), params={"loan_folio_id": outside_folio["id"]}
        )
    )
    assert notice_meta["total_count"] == 0, "the projection sent no notice"
    assert read_folio(outside_folio["id"])["version"] == outside_folio["version"]
    assert read_folio(inside["folio"]["id"])["version"] == inside_folio["version"]


def test_the_projection_is_refused_for_a_live_panel_and_for_a_retired_one():
    """A live panel is not a hypothesis, and neither is a retired one: the gate admits
    only the three pre-effective statuses.  It is also checked before the projection
    walks any structure, so a panel with nothing to evaluate answers with zeroes rather
    than an error.

    PRD §3.3: "The panel under study must have a `revision_status` of `PRELIMINARY`, `APPEAL_OPEN` or `LFD_ISSUED`; asking for a projection against an `EFFECTIVE` or `SUPERSEDED` panel is rejected with `ERR_PANEL_NOT_PRELIMINARY` (HTTP 409), since a live panel is not a hypothesis."
    PRD §3.3: "The projection considers every property in the panel's community whose `map_panel_number` equals the panel's own and whose `geocode_status` is `GEOCODED`, and then every structure on those properties walked in `created_at` ascending order."
    PRD §3.3: "`structures_evaluated` is the number of structures that had a folio."
    PRD §3.2: "In the second hop, because this panel is now effective, the predecessor panel it names in `supersedes_panel_id` moves `EFFECTIVE → SUPERSEDED` with its `superseded_at` set to the current logical instant."

    Design: Corner/endpoints/corner_impact_analysis_refused_for_effective_panel
    """
    set_clock(CLOCK)
    community = create_community()
    effective = publish_panel(community["id"])
    assert effective["revision_status"] == "EFFECTIVE"
    preliminary = publish_panel(
        community["id"], revision_sequence=2, supersedes_panel_id=effective["id"],
        zone_code="VE", base_flood_elevation_ft=12.50,
        effective_date="2027-04-28T00:00:00Z", study_case_number="26-04-1234P",
    )

    validate_error(
        api_client.get_impact_analysis(effective["id"], headers=make_analyst_headers()),
        ApiErrorId.ERR_PANEL_NOT_PRELIMINARY,
        409,
    )

    empty = validate_success(
        api_client.get_impact_analysis(preliminary["id"], headers=make_analyst_headers())
    )
    assert empty["revision_status"] == "PRELIMINARY"
    assert empty["structures_evaluated"] == 0, (
        "an empty structure set is a valid projection, not an error"
    )
    for figure in (
        "newly_in_sfha_count",
        "newly_out_of_sfha_count",
        "bfe_increase_count",
        "folios_requiring_new_notice_count",
        "aggregate_new_required_coverage_cents",
    ):
        assert empty[figure] == 0, f"{figure} must read 0 over an empty structure set"

    walk_panel_to_lfd_issued(preliminary["id"])
    set_clock("2027-05-01T00:00:00Z", headers=make_agency_headers())
    now_effective = validate_success(
        api_client.make_panel_effective(preliminary["id"], headers=make_agency_headers())
    )
    assert now_effective["revision_status"] == "EFFECTIVE"
    retired = validate_success(
        api_client.get_map_panel(effective["id"], headers=make_analyst_headers())
    )
    assert retired["revision_status"] == "SUPERSEDED"

    validate_error(
        api_client.get_impact_analysis(effective["id"], headers=make_analyst_headers()),
        ApiErrorId.ERR_PANEL_NOT_PRELIMINARY,
        409,
    )
    validate_error(
        api_client.get_impact_analysis(preliminary["id"], headers=make_analyst_headers()),
        ApiErrorId.ERR_PANEL_NOT_PRELIMINARY,
        409,
    )


def test_the_sweeps_counters_agree_with_the_rows_the_next_read_returns():
    """The counters are not a summary written later — they describe writes that have
    already landed.  The read taken straight after the response shows the flag cleared
    and the folio's own count reconciled, and an immediate second run finds nothing
    left to sweep.  The sweep reconciles determinations; it does not re-geocode.

    PRD §2.8: "Third, cascades run to completion within the request that triggered them and their effects are visible to the very next read; there is no deferred or eventual settlement anywhere in this API."
    PRD §2.8: "`pending_redetermination_count` in particular is the number of determinations belonging to that folio whose `status` is `FLAGGED_FOR_REVIEW`, with no other filter applied."
    PRD §3.7: "When the re-classification reproduces both the flagged determination's `zone_code` and its `sfha_flag`, nothing of substance has changed and the determination returns `FLAGGED_FOR_REVIEW → ISSUED`: `flagged_reason` is cleared to null, `map_panel_id` is repointed at the panel the re-selection chose, the folio's `pending_redetermination_count` is decremented and its `compliance_posture` recomputed."
    PRD §3.7: "The sweep's `redeterminations_cleared` counter is incremented by one."
    PRD §3.7: "The response reports `determinations_scanned` (the size of phase one's scope), `redeterminations_cleared`, `redeterminations_issued`, `notices_sent`, `notices_expired`, and `run_at`, the logical instant at which the sweep ran."
    PRD §3.4: "In the first hop those four values replace the stored ones, `geocode_status` and `geocode_buffer_ft` are recomputed from them, and `geocode_corrected_count` is incremented by 1 to record how many accepted corrections this property has had."
    PRD §3.6: "Seventh and otherwise, the posture is `NOTICE_DUE`."

    Design: Corner/consistency_model/corner_sweep_counters_agree_with_the_rows_they_describe
    """
    chain = setup_base_chain(
        clock=CLOCK,
        property_overrides={
            "geocode_method": "PARCEL_CENTROID",
            "geocode_confidence_score": 0.88,
        },
    )
    corrected = correct_geocode(
        chain["property"]["id"], latitude=25.7617, longitude=-80.1918,
        geocode_method="ROOFTOP", geocode_confidence_score=0.97,
    )
    assert corrected["geocode_corrected_count"] == 1
    assert read_determination(chain["determination"]["id"])["status"] == "FLAGGED_FOR_REVIEW"

    first = run_monitoring()
    assert first["determinations_scanned"] == 1
    assert first["redeterminations_cleared"] == 1
    assert first["redeterminations_issued"] == 0
    assert_instant(first["run_at"], CLOCK)

    _, meta = determinations_for(chain["folio"]["id"])
    assert meta["total_count"] == 1, "clearing a review mints no second row"
    swept = read_determination(chain["determination"]["id"])
    assert swept["status"] == "ISSUED"
    assert swept["flagged_reason"] is None

    folio = read_folio(chain["folio"]["id"])
    assert folio["pending_redetermination_count"] == 0, (
        "the folio-level recount landed in the same request as the determination write"
    )
    assert folio["compliance_posture"] == "NOTICE_DUE", (
        "no review is pending, an obligation exists and no notice is out"
    )

    second = run_monitoring()
    assert second["determinations_scanned"] == 0, (
        "the first run's effects are already visible, so no row is swept twice"
    )
    assert second["redeterminations_cleared"] == 0
    assert second["redeterminations_issued"] == 0

    unchanged = validate_success(
        api_client.get_property(chain["property"]["id"], headers=make_analyst_headers())
    )
    assert unchanged["geocode_corrected_count"] == 1, (
        "the sweep reconciles determinations, it does not re-geocode"
    )
    assert unchanged["geocode_method"] == "ROOFTOP"


def test_a_notice_expires_only_strictly_past_its_deadline_and_an_empty_sweep_is_a_success():
    """Phase two's comparison is strict, so a sweep run at exactly the deadline instant
    closes nothing and reports a full row of zeroes — a success, not an error.  One
    second later the same sweep expires the notice, and the folio's posture steps from
    NOTICE_PENDING to FORCE_PLACE_ELIGIBLE on that single second.

    PRD §3.6: "A notice that survives all of that is created in `status` `SENT` with `sent_at` at the current logical instant, and its `response_deadline_at` is computed as `sent_at` plus a response window that depends on the type: 45 days for `MANDATORY_PURCHASE`, 30 days for `FORCE_PLACEMENT_WARNING`, 30 days for `RE_DETERMINATION` and 15 days for `COVERAGE_UNAVAILABLE`."
    PRD §3.7: "Phase two always runs, even when phase one's scope was empty."
    PRD §3.7: "Every compliance notice whose `status` is `SENT` and whose `response_deadline_at` is strictly earlier than the current logical instant moves `SENT → EXPIRED` with `closed_at` set and the owning folio's `open_notice_count` re-counted, and `notices_expired` is incremented once per notice so closed."
    PRD §3.7: "An empty scope is a success, not an error: every counter reads 0 and no row is written."
    PRD §3.6: "Fifth, if a compliance notice exists on this folio whose `notice_type` is `MANDATORY_PURCHASE`, whose `status` is `SENT` or `EXPIRED`, and whose `response_deadline_at` is strictly earlier than the current logical instant, the posture is `FORCE_PLACE_ELIGIBLE`."
    PRD §3.6: "Sixth, if a compliance notice exists on this folio whose `notice_type` is `MANDATORY_PURCHASE`, whose `status` is `SENT`, and whose `response_deadline_at` is at or after the current logical instant, the posture is `NOTICE_PENDING`."
    PRD §2.10: "`open_notice_count` on a folio is defined as the number of compliance notices on that folio whose `status` is `SENT`, counted across every notice type and with no time window applied, and it is recomputed by full re-count after every notice creation and after every notice transition out of `SENT`."

    Design: Difficulty/boundary_precision_check/notice_expiry_strict_instant_and_empty_sweep_zero_counts
    """
    chain = setup_folio_with_mandatory_notice(clock=CLOCK)
    notice = chain["notice"]
    determination_id = chain["determination"]["id"]
    assert_instant(notice["response_deadline_at"], DEADLINE)
    assert read_determination(determination_id)["status"] == "ISSUED"

    set_clock(DEADLINE)
    at_the_deadline = run_monitoring()
    for counter in (
        "determinations_scanned",
        "redeterminations_cleared",
        "redeterminations_issued",
        "notices_sent",
        "notices_expired",
    ):
        assert at_the_deadline[counter] == 0, (
            f"{counter} must read 0: nothing is in scope at exactly the deadline"
        )
    assert_instant(at_the_deadline["run_at"], DEADLINE)
    assert "error_id" not in at_the_deadline, "an empty scope is a success, not an error"

    still_open = validate_success(
        api_client.get_compliance_notice(notice["id"], headers=chain["lender_headers"])
    )
    assert still_open["status"] == "SENT", (
        "the deadline instant is not strictly earlier than itself"
    )
    assert still_open["closed_at"] is None
    folio = read_folio(chain["folio"]["id"])
    assert folio["open_notice_count"] == 1
    assert folio["compliance_posture"] == "NOTICE_PENDING"
    assert folio["pending_redetermination_count"] == 0
    assert read_determination(determination_id)["status"] == "ISSUED", (
        "the empty sweep wrote nothing at all"
    )

    set_clock("2026-09-15T00:00:01Z")
    one_second_later = run_monitoring()
    assert one_second_later["notices_expired"] == 1
    assert one_second_later["determinations_scanned"] == 0
    assert one_second_later["redeterminations_cleared"] == 0
    assert one_second_later["redeterminations_issued"] == 0
    assert one_second_later["notices_sent"] == 0

    expired = validate_success(
        api_client.get_compliance_notice(notice["id"], headers=chain["lender_headers"])
    )
    assert expired["status"] == "EXPIRED"
    assert_instant(expired["closed_at"], "2026-09-15T00:00:01Z")
    folio = read_folio(chain["folio"]["id"])
    assert folio["open_notice_count"] == 0
    assert folio["compliance_posture"] == "FORCE_PLACE_ELIGIBLE"
    assert folio["pending_redetermination_count"] == 0
    assert read_determination(determination_id)["status"] == "ISSUED"
