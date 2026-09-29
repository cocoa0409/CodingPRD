"""The heaviest write in the API, and the folio dimensions a community drags around.

Putting a panel in force ripples five hops out from the map to a lender's notice,
and a community's standing moves a folio's monitoring dimension and its money
without touching its coverage dimension.  The last test here pins the one place
where the two evaluation variants of Section 3.5 disagree outright.
"""

from prd_bench_local_runner.testing import (
    validate_paginated,
    validate_success,
)

from test_helpers import (
    api_client,
    change_participation,
    folio_version,
    issue_determination,
    make_agency_headers,
    make_analyst_headers,
    publish_successor_panel,
    read_folio,
    report_insurance,
    set_clock,
    setup_base_chain,
    setup_folio_with_mandatory_notice,
    walk_panel_to_lfd_issued,
)

CLOCK = "2026-08-01T00:00:00Z"
EFFECTIVE_CLOCK = "2027-05-01T00:00:00Z"


def assert_instant(actual, expected_utc):
    """Compare a timestamp field to an instant.

    PRD 2.4 fixes the wire format at three fractional digits, so an instant the
    test supplied as ``...T00:00:00Z`` is read back as ``...T00:00:00.000Z``.
    """
    assert actual is not None, f"expected the instant {expected_utc}, got null"
    assert actual.replace(".000Z", "Z") == expected_utc, (
        f"{actual!r} is not the instant {expected_utc}"
    )


def read_panel(map_panel_id):
    return validate_success(
        api_client.get_map_panel(map_panel_id, headers=make_analyst_headers())
    )


def read_determination(determination_id):
    return validate_success(
        api_client.get_determination(determination_id, headers=make_analyst_headers())
    )


def read_notice(compliance_notice_id):
    return validate_success(
        api_client.get_compliance_notice(
            compliance_notice_id, headers=make_analyst_headers()
        )
    )


def read_community(community_id):
    return validate_success(
        api_client.get_community(community_id, headers=make_analyst_headers())
    )


def read_structure(structure_id):
    return validate_success(
        api_client.get_structure(structure_id, headers=make_analyst_headers())
    )


def setup_successor_over_a_noticed_folio(successor_overrides=None, **chain_kwargs):
    """A noticed folio on panel 1 plus its sequence-2 successor sitting in LFD_ISSUED.

    The clock ends at 2027-05-01, which is past both the posted appeal window and
    the 180-day letter-of-final-determination wait, so the successor is ready to
    be put in force.
    """
    chain = setup_folio_with_mandatory_notice(clock=CLOCK, **chain_kwargs)
    successor = publish_successor_panel(
        chain["community"]["id"], chain["panel"], **(successor_overrides or {})
    )
    chain["successor"] = walk_panel_to_lfd_issued(successor["id"])
    set_clock(EFFECTIVE_CLOCK, headers=make_agency_headers())
    return chain


def test_putting_a_panel_in_force_walks_five_hops_out_to_the_lenders_notice():
    """One agency call moves a panel, retires its predecessor, flags every determination
    that was reading the retired sheet, re-prices nothing, and closes the mandatory
    purchase notice that was riding on the flagged determination.  Each hop exists only
    because the hop before it happened.

    PRD §3.2: "In the first hop the panel itself moves `LFD_ISSUED → EFFECTIVE`."
    PRD §3.2: "In the second hop, because this panel is now effective, the predecessor panel it names in `supersedes_panel_id` moves `EFFECTIVE → SUPERSEDED` with its `superseded_at` set to the current logical instant."
    PRD §3.2: "In the third hop, because that predecessor is now superseded, every determination whose `map_panel_id` is the predecessor and whose `status` is `ISSUED` moves `ISSUED → FLAGGED_FOR_REVIEW` with `flagged_reason` set to `MAP_REVISION`."
    PRD §3.2: "In the fourth hop, because those determinations are now flagged, each loan folio referenced by them re-counts `pending_redetermination_count` and recomputes `compliance_posture`, which the clause ladder of Section 3.6 resolves to `REVIEW_PENDING`."
    PRD §3.2: "In the fifth hop, because those folios are now review-pending, every compliance notice on them whose `status` is `SENT` and whose `notice_type` is either `MANDATORY_PURCHASE` or `FORCE_PLACEMENT_WARNING` moves `SENT → SUPERSEDED` with `closed_at` set to the current logical instant, and each of those folios re-counts `open_notice_count`."
    PRD §3.6: "Beyond acknowledgement, a `SENT` notice leaves that state in only two ways: it expires, when a monitoring sweep or a force placement observes that the current logical instant is strictly past its `response_deadline_at`, and it is superseded, when the determination it cites leaves the governing position or the folio's coverage obligation is satisfied — the fifth hop of the panel-effective cascade, the fifth hop of the sustained-dispute cascade, or the folio's move into `BORROWER_PROVIDED`."

    Design: Difficulty/transitive_cascade/panel_effective_five_hop_cascade_to_notice_supersession
    """
    chain = setup_successor_over_a_noticed_folio()
    predecessor_id = chain["panel"]["id"]
    successor_id = chain["successor"]["id"]
    determination_id = chain["determination"]["id"]
    folio_id = chain["folio"]["id"]
    notice_id = chain["notice"]["id"]

    assert chain["determination"]["sfha_flag"] is True
    assert chain["determination"]["mandatory_purchase_flag"] is True
    assert chain["folio"]["open_notice_count"] == 1
    before = read_notice(notice_id)
    assert_instant(before["response_deadline_at"], "2026-09-15T00:00:00Z")
    assert before["status"] == "SENT", (
        "the 2026-09-15 deadline lapsed months ago, but only a monitoring sweep or a "
        "force placement lapses a notice — reading the clock forward does not"
    )
    assert before["closed_at"] is None

    effective = validate_success(
        api_client.make_panel_effective(successor_id, headers=make_agency_headers())
    )
    assert effective["revision_status"] == "EFFECTIVE", "hop 1: LFD_ISSUED -> EFFECTIVE"

    retired = read_panel(predecessor_id)
    assert retired["revision_status"] == "SUPERSEDED", "hop 2: the predecessor retires"
    assert_instant(retired["superseded_at"], EFFECTIVE_CLOCK)

    flagged = read_determination(determination_id)
    assert flagged["status"] == "FLAGGED_FOR_REVIEW", "hop 3: the determination is flagged"
    assert flagged["flagged_reason"] == "MAP_REVISION"
    assert flagged["map_panel_id"] == predecessor_id, (
        "flagging marks the determination for review; it does not re-determine it, so "
        "the row still names the panel it was actually computed against"
    )
    assert flagged["zone_code"] == "AE", "no geometry was re-evaluated"
    assert flagged["sfha_flag"] is True

    folio = read_folio(folio_id)
    assert folio["pending_redetermination_count"] == 1, "hop 4: one flagged determination"
    assert folio["compliance_posture"] == "REVIEW_PENDING"

    closed = read_notice(notice_id)
    assert closed["status"] == "SUPERSEDED", "hop 5: the notice is superseded, not expired"
    assert_instant(closed["closed_at"], EFFECTIVE_CLOCK)
    assert folio["open_notice_count"] == 0, "hop 5 re-counts the folio's open notices"

    assert folio["insurance_status"] == "NONE", "the cascade flags; it does not sell cover"
    assert folio["required_coverage_cents"] == 25_000_000, (
        "the obligation is untouched: min(28000000 principal, 32000000 replacement, "
        "25000000 single-family cap)"
    )
    on_the_new_panel, meta = validate_paginated(
        api_client.list_determinations(
            headers=make_analyst_headers(), params={"map_panel_id": successor_id}
        )
    )
    assert meta["total_count"] == 0, (
        "the cascade issues no re-determination against the new panel"
    )
    assert on_the_new_panel == []


def test_every_hop_of_that_cascade_is_readable_first_try_and_stable_second_try():
    """The deepest write in the system settles inside the request that triggered it.  The
    POST response already carries the new status, the first read of every downstream row
    already shows its terminal value, and a second read of all five rows returns exactly
    what the first one did.

    PRD §2.8: "Third, cascades run to completion within the request that triggered them and their effects are visible to the very next read; there is no deferred or eventual settlement anywhere in this API."
    PRD §2.8: "First, every row a cascade writes is a real mutation of that row: its `updated_at` is refreshed to the current logical instant and its `version` increases by 1, exactly as if a client had written it directly."
    PRD §3.6: "Third, if `pending_redetermination_count` is greater than zero the posture is `REVIEW_PENDING`."
    PRD §3.6: "Only mandatory-purchase notices participate in the fifth and sixth clauses, and notices that have reached `SUPERSEDED` or `ACKNOWLEDGED` are excluded from both."
    PRD §3.6: "The clause order is load-bearing: a folio that has both a lapsed notice and a pending re-determination reports `REVIEW_PENDING`, not `FORCE_PLACE_ELIGIBLE`, so an in-flight map revision blocks force placement."

    Design: Corner/consistency_model/corner_panel_effective_cascade_is_readable_with_no_lag
    """
    chain = setup_successor_over_a_noticed_folio()
    predecessor_id = chain["panel"]["id"]
    successor_id = chain["successor"]["id"]
    determination_id = chain["determination"]["id"]
    folio_id = chain["folio"]["id"]
    notice_id = chain["notice"]["id"]
    panel_version_before = chain["panel"]["version"]
    determination_version_before = chain["determination"]["version"]
    notice_version_before = chain["notice"]["version"]

    posted = validate_success(
        api_client.make_panel_effective(successor_id, headers=make_agency_headers())
    )
    assert posted["revision_status"] == "EFFECTIVE", (
        "the response body itself reports the terminal status; nothing is deferred"
    )

    first_predecessor = read_panel(predecessor_id)
    first_determination = read_determination(determination_id)
    first_folio = read_folio(folio_id)
    first_notice = read_notice(notice_id)
    first_successor = read_panel(successor_id)

    assert first_predecessor["revision_status"] == "SUPERSEDED"
    assert_instant(first_predecessor["superseded_at"], EFFECTIVE_CLOCK)
    assert first_determination["status"] == "FLAGGED_FOR_REVIEW"
    assert first_determination["flagged_reason"] == "MAP_REVISION"
    assert first_folio["pending_redetermination_count"] == 1
    assert first_folio["compliance_posture"] == "REVIEW_PENDING", (
        "the clause ladder stops at the third clause even though the notice deadline "
        "lapsed in 2026: a pending re-determination outranks force-place eligibility"
    )
    assert first_folio["open_notice_count"] == 0
    assert first_notice["status"] == "SUPERSEDED"
    assert_instant(first_notice["closed_at"], EFFECTIVE_CLOCK)

    assert first_predecessor["version"] > panel_version_before, (
        "each hop is a real mutation of the row it touches"
    )
    assert first_determination["version"] > determination_version_before
    assert first_notice["version"] > notice_version_before
    assert_instant(first_predecessor["updated_at"], EFFECTIVE_CLOCK)
    assert_instant(first_determination["updated_at"], EFFECTIVE_CLOCK)
    assert_instant(first_notice["updated_at"], EFFECTIVE_CLOCK)

    assert read_panel(successor_id) == first_successor, (
        "there is no convergence step left to wait out"
    )
    assert read_panel(predecessor_id) == first_predecessor
    assert read_determination(determination_id) == first_determination
    assert read_folio(folio_id) == first_folio
    assert read_notice(notice_id) == first_notice


def test_dropping_the_community_to_emergency_standing_swaps_the_statutory_cap():
    """Nothing about the loan, the building or the determination changes, and yet the
    amount the borrower must buy falls from 25,000,000 cents to 3,500,000 cents, because
    the cap is read off the community's standing at recompute time.

    PRD §2.9: "Each community carries a `participation_status` describing its standing in the national program and a `cbrs_flag` recording whether it sits inside a Coastal Barrier Resources System unit, and from those two inputs the system derives `coverage_availability` by evaluating the following clauses from top to bottom and taking the first that matches: if `cbrs_flag` is true the availability is `UNAVAILABLE`; otherwise if `participation_status` is `SUSPENDED`, `NON_PARTICIPATING` or `WITHDRAWN` the availability is `UNAVAILABLE`; otherwise if `participation_status` is `EMERGENCY` the availability is `EMERGENCY_LIMITS_ONLY`; otherwise if `participation_status` is `PROBATION` the availability is `FULL_WITH_SURCHARGE`; otherwise — that is, when `participation_status` is `REGULAR` — the availability is `FULL`."
    PRD §3.1: "The change recomputes `coverage_availability`, stamps `last_participation_change_at` with the current logical instant, and then reaches into every loan folio sitting on a property in that community."
    PRD §3.1: "Those folios then recompute `required_coverage_cents` and `uninsured_exposure_cents` — a community dropping to `EMERGENCY` standing lowers the caps and can therefore lower the required amount without anything about the loan or the structure changing — and finally recompute `compliance_posture`, which becomes `COVERAGE_UNAVAILABLE` on the suspending direction and is otherwise re-derived from the unchanged coverage dimension and notice set."
    PRD §3.6: "When it is true, the system first picks a statutory cap from the structure's `occupancy_type`: in a community whose `coverage_availability` is `EMERGENCY_LIMITS_ONLY` the cap is 3,500,000 cents (thirty-five thousand dollars) for a `SINGLE_FAMILY` or `TWO_TO_FOUR_FAMILY` building and 10,000,000 cents (one hundred thousand dollars) for an `OTHER_RESIDENTIAL` or `NON_RESIDENTIAL` building, while in a community at any other availability the cap is 25,000,000 cents (two hundred and fifty thousand dollars) for a `SINGLE_FAMILY` or `TWO_TO_FOUR_FAMILY` building and 50,000,000 cents (five hundred thousand dollars) for an `OTHER_RESIDENTIAL` or `NON_RESIDENTIAL` building."
    PRD §3.6: "`required_coverage_cents` is then the smallest of three integer amounts: the folio's `principal_balance_cents`, the structure's `replacement_cost_cents`, and that cap."
    PRD §3.6: "`uninsured_exposure_cents` is 0 whenever the folio's `insurance_status` is `FORCE_PLACED`, because a force-placed folio has no gap by construction; otherwise it is `required_coverage_cents` minus `reported_coverage_cents`, floored at 0 so that over-reported coverage never produces a negative exposure."
    PRD §3.6: "Seventh and otherwise, the posture is `NOTICE_DUE`."

    Design: Corner/calculations/corner_emergency_program_caps_replace_regular_caps
    """
    chain = setup_base_chain(clock=CLOCK)
    community_id = chain["community"]["id"]
    folio_id = chain["folio"]["id"]
    structure_id = chain["structure"]["id"]
    determination_id = chain["determination"]["id"]

    assert chain["community"]["coverage_availability"] == "FULL"
    assert chain["folio"]["required_coverage_cents"] == 25_000_000, (
        "min(28000000 principal, 32000000 replacement, 25000000 regular single-family cap)"
    )
    assert chain["folio"]["uninsured_exposure_cents"] == 25_000_000, (
        "nothing has been reported, so the whole obligation is exposed"
    )
    assert chain["folio"]["reported_coverage_cents"] == 0

    changed = change_participation(community_id, "EMERGENCY")
    assert changed["participation_status"] == "EMERGENCY"
    assert changed["coverage_availability"] == "EMERGENCY_LIMITS_ONLY", (
        "the third clause of the availability ladder"
    )
    assert_instant(changed["last_participation_change_at"], CLOCK)
    assert changed == read_community(community_id), (
        "the participation change returns the updated community it just wrote"
    )

    folio = read_folio(folio_id)
    assert folio["required_coverage_cents"] == 3_500_000, (
        "the emergency-programme cap for a SINGLE_FAMILY building now binds: "
        "min(28000000, 32000000, 3500000)"
    )
    assert folio["uninsured_exposure_cents"] == 3_500_000, (
        "3500000 required minus 0 reported"
    )
    assert folio["compliance_posture"] == "NOTICE_DUE", (
        "the first clause does not fire: EMERGENCY_LIMITS_ONLY is not UNAVAILABLE"
    )
    assert folio["insurance_status"] == "NONE"
    assert folio["principal_balance_cents"] == 28_000_000, "the loan did not change"

    assert read_structure(structure_id)["replacement_cost_cents"] == 32_000_000, (
        "the building did not change either; only the cap moved"
    )
    determination = read_determination(determination_id)
    assert determination["sfha_flag"] is True
    assert determination["mandatory_purchase_flag"] is True, (
        "an emergency-programme community can still write coverage, so the purchase "
        "requirement stands"
    )


def test_the_monitoring_dimension_cycles_while_the_insurance_dimension_stays_put():
    """A folio carries two independent status dimensions.  Suspending and then reinstating
    the community walks `monitoring_status` ACTIVE -> SUSPENDED -> ACTIVE and never once
    touches `insurance_status`, which stays pinned at BORROWER_PROVIDED across both moves.

    PRD §3.6: "From `NONE` the folio moves `NONE → BORROWER_PROVIDED`: `reported_coverage_cents` is stored, `uninsured_exposure_cents` recomputes to 0, `compliance_posture` recomputes to `COMPLIANT`, and every notice on the folio in `status` `SENT` whose `notice_type` is `MANDATORY_PURCHASE` or `FORCE_PLACEMENT_WARNING` moves `SENT → SUPERSEDED` with `closed_at` set, after which `open_notice_count` is re-counted."
    PRD §3.1: "Each such folio has its monitoring dimension re-evaluated: a folio whose `monitoring_status` is `ACTIVE` moves `ACTIVE → SUSPENDED` when the community's new `coverage_availability` is `UNAVAILABLE`, and a folio whose `monitoring_status` is `SUSPENDED` moves `SUSPENDED → ACTIVE` when the new availability is anything other than `UNAVAILABLE` — that is, when the community has been restored to `REGULAR`, `EMERGENCY` or `PROBATION` standing."
    PRD §3.1: "Neither direction of that transition touches the folio's `insurance_status`; the two dimensions are independent, and a force-placed folio in a suspended community keeps its coverage dimension untouched while its monitoring dimension goes dormant."
    PRD §3.1: "Those folios then recompute `required_coverage_cents` and `uninsured_exposure_cents` — a community dropping to `EMERGENCY` standing lowers the caps and can therefore lower the required amount without anything about the loan or the structure changing — and finally recompute `compliance_posture`, which becomes `COVERAGE_UNAVAILABLE` on the suspending direction and is otherwise re-derived from the unchanged coverage dimension and notice set."
    PRD §3.6: "First, if the community's `coverage_availability` is `UNAVAILABLE` the posture is `COVERAGE_UNAVAILABLE`."
    PRD §3.6: "Fourth, if `required_coverage_cents` is 0, or `reported_coverage_cents` is at or above `required_coverage_cents`, the posture is `COMPLIANT`."

    Design: Difficulty/non_linear_state_machine/folio_monitoring_and_insurance_dimensions_move_independently
    """
    chain = setup_base_chain(clock=CLOCK)
    community_id = chain["community"]["id"]
    folio_id = chain["folio"]["id"]
    determination_id = chain["determination"]["id"]

    insured = report_insurance(folio_id, chain["lender"]["id"], 25_000_000)
    assert insured["insurance_status"] == "BORROWER_PROVIDED"
    assert insured["monitoring_status"] == "ACTIVE"
    assert insured["reported_coverage_cents"] == 25_000_000
    assert insured["uninsured_exposure_cents"] == 0
    assert insured["compliance_posture"] == "COMPLIANT"
    determination_before = read_determination(determination_id)
    assert determination_before["mandatory_purchase_flag"] is True

    suspended = change_participation(community_id, "SUSPENDED")
    assert suspended["coverage_availability"] == "UNAVAILABLE"
    assert_instant(suspended["last_participation_change_at"], CLOCK)

    dormant = read_folio(folio_id)
    assert dormant["monitoring_status"] == "SUSPENDED", (
        "the monitoring dimension goes dormant while cover cannot be written"
    )
    assert dormant["insurance_status"] == "BORROWER_PROVIDED", (
        "the coverage dimension is untouched by a participation change"
    )
    assert dormant["reported_coverage_cents"] == 25_000_000
    assert dormant["compliance_posture"] == "COVERAGE_UNAVAILABLE", (
        "the first clause of the posture ladder short-circuits every later clause"
    )
    assert read_determination(determination_id) == determination_before, (
        "the participation change reaches communities and folios, never determinations"
    )

    reinstated = change_participation(community_id, "REGULAR")
    assert reinstated["coverage_availability"] == "FULL"

    revived = read_folio(folio_id)
    assert revived["monitoring_status"] == "ACTIVE", "the monitoring dimension revives"
    assert revived["insurance_status"] == "BORROWER_PROVIDED", (
        "and it revives without disturbing the coverage dimension a second time"
    )
    assert revived["required_coverage_cents"] == 25_000_000, (
        "the regular single-family cap is back: min(28000000, 32000000, 25000000)"
    )
    assert revived["reported_coverage_cents"] == 25_000_000
    assert revived["uninsured_exposure_cents"] == 0
    assert revived["compliance_posture"] == "COMPLIANT", (
        "reported coverage is at the required amount, so the fourth clause matches"
    )
    assert read_determination(determination_id) == determination_before, (
        "two participation changes later the determination is still the row it was"
    )


def test_the_two_zone_variants_disagree_on_the_same_zero_offset_structure():
    """A panel that pushes the hazard boundary out by exactly the structure's offset leaves
    the building sitting on the line with a zero buffer, which is INDETERMINATE.  The
    prospective projection resolves that conservatively into the SFHA, while the
    life-of-loan re-read of the very same structure, property and panel carries the old
    OUTSIDE answer forward — same inputs, opposite `sfha_flag`.

    PRD §3.5: "The applicable buffer in feet is the sum of the property's method-derived positional buffer — 0 for `ROOFTOP`, 25 for `PARCEL_CENTROID`, 250 for `ZIP_CENTROID`, 0 for `FAILED` — and the governing panel's `horizontal_uncertainty_ft`."
    PRD §3.5: "The structure's effective offset in feet is its `sfha_offset_ft` minus the panel's `sfha_boundary_shift_ft`, which is how a panel that pushed the hazard boundary outward drags buildings into the SFHA without anyone re-surveying them."
    PRD §3.5: "Both comparisons are exact decimal comparisons against zero and both are strict, so an effective offset whose buffered value lands exactly on zero yields `INDETERMINATE` rather than a definite side."
    PRD §3.5: "Under the strict variant — used for every `ORIGINATION` determination, for every `DISPUTE_REVISION` determination, and for every prospective evaluation performed by the preliminary-map projection of Section 3.3 — an `INDETERMINATE` result resolves conservatively to the panel's `zone_code` with `sfha_flag` true, so that whenever the buffer straddles the boundary the lender is told insurance is mandatory."
    PRD §3.5: "Under the lenient variant — used for every `LIFE_OF_LOAN_REVIEW` determination, whether issued manually or minted by a monitoring sweep — an `INDETERMINATE` result carries forward the superseded determination's `zone_code` and `sfha_flag` unchanged, so an ambiguous re-read never flips a borrower's obligation; if there is no prior determination to carry forward, the lenient variant falls back to the strict rule."
    PRD §3.5: "The consequence is that identical structure, property and panel inputs can produce `sfha_flag` true under the strict variant and `sfha_flag` false under the lenient one, whenever the prior determination said the building was outside."
    PRD §3.5: "Any prior determination for the same folio and structure that was in `ISSUED` or `FLAGGED_FOR_REVIEW` is moved to `SUPERSEDED` with its `superseded_at` set to the current logical instant, and the new row names it in `supersedes_determination_id`; on the flagged path the retired row keeps the `flagged_reason` it was carrying and the folio's `pending_redetermination_count` is decremented, while on the plain issued path there is no flagged reason to carry."
    PRD §3.3: "`newly_in_sfha_count` is the number of those structures whose current determination has a false `sfha_flag` while the prospective classification yields a true one."
    PRD §3.3: "`aggregate_new_required_coverage_cents` is the sum, over the newly-in-SFHA structures only, of the required coverage each would carry under the prospective classification, computed by the coverage rule of Section 3.6 using the prospective determination, the structure, its folio and its community."

    Design: Difficulty/dual_variant_calc/zone_determination_strict_vs_lenient_on_indeterminate_structure
    """
    chain = setup_base_chain(
        clock=CLOCK,
        property_overrides={
            "street_address": "44 Ridge Line Rd",
            "latitude": 25.7743,
            "longitude": -80.1937,
        },
        structure_overrides={
            "structure_label": "Ridge dwelling",
            "sfha_offset_ft": 30.0,
        },
        folio_overrides={
            "loan_number": "LN-9012",
            "borrower_user_id": "borrower-d",
            "principal_balance_cents": 19_000_000,
            "policy_anniversary_date": "2027-01-10T00:00:00Z",
            "escrow_balance_cents": 400_000,
        },
    )
    folio_id = chain["folio"]["id"]
    structure_id = chain["structure"]["id"]
    origination = chain["determination"]
    assert origination["position_class"] == "OUTSIDE", (
        "30.0 offset minus a 0.0 shift, minus a 0.0 buffer, is strictly greater than zero"
    )
    assert origination["sfha_flag"] is False
    assert origination["zone_code"] == "X"
    assert origination["base_flood_elevation_ft"] is None
    assert origination["mandatory_purchase_flag"] is False
    assert chain["folio"]["insurance_status"] == "NOT_REQUIRED"
    assert chain["folio"]["required_coverage_cents"] == 0

    successor = publish_successor_panel(
        chain["community"]["id"], chain["panel"], sfha_boundary_shift_ft=30.0
    )
    successor = walk_panel_to_lfd_issued(successor["id"])
    assert successor["zone_code"] == "VE"
    assert successor["base_flood_elevation_ft"] == 12.50
    set_clock(EFFECTIVE_CLOCK, headers=make_agency_headers())

    projection = validate_success(
        api_client.get_impact_analysis(successor["id"], headers=make_analyst_headers())
    )
    assert projection["map_panel_id"] == successor["id"]
    assert projection["revision_status"] == "LFD_ISSUED"
    assert projection["structures_evaluated"] == 1, "one structure, and it has a folio"
    assert projection["newly_in_sfha_count"] == 1, (
        "the strict variant resolves the straddling structure into the hazard area, so a "
        "currently-false sfha_flag becomes a prospectively-true one"
    )
    assert projection["newly_out_of_sfha_count"] == 0
    assert projection["bfe_increase_count"] == 0, (
        "the current determination carries a null base flood elevation, so it cannot "
        "count as an increase"
    )
    assert projection["folios_requiring_new_notice_count"] == 1, (
        "the folio behind the newly-in structure is NOT_REQUIRED today"
    )
    assert projection["aggregate_new_required_coverage_cents"] == 19_000_000, (
        "min(19000000 principal, 32000000 replacement, 25000000 single-family cap)"
    )

    validate_success(
        api_client.make_panel_effective(successor["id"], headers=make_agency_headers())
    )
    assert read_determination(origination["id"])["status"] == "FLAGGED_FOR_REVIEW"

    review = issue_determination(
        folio_id, structure_id,
        determination_type="LIFE_OF_LOAN_REVIEW",
        expected_version=folio_version(folio_id),
    )
    assert review["map_panel_id"] == successor["id"], (
        "the retired panel no longer qualifies; the new sheet governs"
    )
    assert review["position_class"] == "INDETERMINATE", (
        "30.0 offset minus a 30.0 shift is exactly 0.0 against a 0.0 buffer, and both "
        "comparisons are strict"
    )
    assert review["sfha_flag"] is False, (
        "the lenient variant carries the superseded OUTSIDE answer forward rather than "
        "flipping the borrower's obligation on an ambiguous re-read"
    )
    assert review["zone_code"] == "X"
    assert review["base_flood_elevation_ft"] is None, (
        "the panel's 12.50 is snapshotted only when sfha_flag is true"
    )
    assert review["freeboard_ft"] is None
    assert review["mandatory_purchase_flag"] is False
    assert review["status"] == "ISSUED"
    assert review["supersedes_determination_id"] == origination["id"]

    retired = read_determination(origination["id"])
    assert retired["status"] == "SUPERSEDED"
    assert_instant(retired["superseded_at"], EFFECTIVE_CLOCK)
    assert retired["flagged_reason"] == "MAP_REVISION", (
        "the retired row keeps the flagged reason it was carrying"
    )

    folio = read_folio(folio_id)
    assert folio["current_determination_id"] == review["id"]
    assert folio["pending_redetermination_count"] == 0, "the flagged row was retired"
    assert folio["required_coverage_cents"] == 0
    assert folio["insurance_status"] == "NOT_REQUIRED"
    assert folio["compliance_posture"] == "COMPLIANT"

    assert projection["newly_in_sfha_count"] == 1 and review["sfha_flag"] is False, (
        "byte-identical structure, property and panel inputs: the strict variant would "
        "have written zone VE with sfha_flag true, the lenient one wrote zone X with "
        "sfha_flag false"
    )
