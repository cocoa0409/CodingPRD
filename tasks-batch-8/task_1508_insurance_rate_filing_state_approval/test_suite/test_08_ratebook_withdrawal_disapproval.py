"""Rate book supersession, withdrawal and disapproval cascades (PRD §2.10, §3.6)."""
from test_helpers import (
    ApiErrorId,
    add_final_component,
    create_deviation,
    create_deviation_payload,
    create_filing,
    find_calendar_entry,
    get_success_data,
    set_clock,
    setup_draft_filing,
    setup_effective_filing,
    setup_effective_with_wave,
    setup_ready_filing,
    setup_submitted_filing,
    validate_error,
    validate_success,
)
from test_helpers import fixtures as fx

NV_FAU = {"filing_method": "FILE_AND_USE", "deemer_days": 0}


def _nv_effective_scenario(api):
    return setup_effective_filing(
        state_code="NV", profile_overrides=dict(NV_FAU)
    )


def _build_successor(api, scenario, proposed_effective_date):
    """Create + READY + SUBMIT + APPROVE a successor NV filing at the current
    clock (2026-10-01 after the first filing went effective)."""
    filing = create_filing(
        scenario["product"]["id"],
        "NV",
        scenario["indication"]["id"],
        proposed_change_pct=0.05,
        proposed_effective_date=proposed_effective_date,
    )
    add_final_component(
        filing["id"],
        component_type="RATE",
        name="NV Base Rates v2",
        content_ref="s3://fil/nv-rate-v2.pdf",
    )
    get_success_data(api.mark_filing_ready(filing["id"], fx.ANALYST))
    get_success_data(api.submit_filing(filing["id"], fx.OFFICER))
    return get_success_data(api.approve_filing(filing["id"], fx.REGULATOR))


def test_same_day_effectiveness_is_overlap(api):
    """PRD §2.10: "A new filing may enter the rate book only at the head of the
    chain: no currently `EFFECTIVE` filing for the same product and state may
    have an `actual_effective_date` on or after the incoming filing's own. An
    equal date is an overlap, not a succession — two filings of one rate book
    can never take effect on the same day — and the attempt is rejected with
    `ERR_RATEBOOK_OVERLAP` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/ratebook_half_open_strictly_later_supersede
    """
    scenario = _nv_effective_scenario(api)  # incumbent effective 2026-10-01
    successor = _build_successor(api, scenario, "2026-10-01")
    assert successor["actual_effective_date"] == "2026-10-01"

    res = api.mark_filing_effective(successor["id"], fx.OFFICER)
    validate_error(res, ApiErrorId.ERR_RATEBOOK_OVERLAP)
    after = get_success_data(api.get_filing(successor["id"], fx.OFFICER))
    assert after["status"] == "APPROVED"

    incumbent = get_success_data(api.get_filing(scenario["filing"]["id"], fx.OFFICER))
    assert incumbent["status"] == "EFFECTIVE"


def test_strictly_later_effectiveness_supersedes_incumbent(api):
    """PRD §2.10: "A strictly later date succeeds, and the incumbent
    `EFFECTIVE` filing is superseded in the same motion, its
    `superseded_at_date` set to the successor's `actual_effective_date` so the
    chain never gaps and never overlaps."

    Design: Difficulty/resource_temporal_overlap/ratebook_half_open_strictly_later_supersede
    """
    scenario = _nv_effective_scenario(api)

    # Same-day successor collides, then withdraws cleanly.
    colliding = _build_successor(api, scenario, "2026-10-01")
    validate_error(
        api.mark_filing_effective(colliding["id"], fx.OFFICER),
        ApiErrorId.ERR_RATEBOOK_OVERLAP,
    )
    withdrawn = validate_success(
        api.withdraw_filing(colliding["id"], fx.OFFICER), 200
    )
    assert withdrawn["status"] == "WITHDRAWN"

    # A strictly later date succeeds.
    successor = _build_successor(api, scenario, "2026-10-02")
    set_clock("2026-10-02T00:00:00Z")
    effective = validate_success(
        api.mark_filing_effective(successor["id"], fx.OFFICER), 200
    )
    assert effective["status"] == "EFFECTIVE"
    assert effective["actual_effective_date"] == "2026-10-02"

    incumbent = get_success_data(api.get_filing(scenario["filing"]["id"], fx.OFFICER))
    assert incumbent["status"] == "SUPERSEDED"
    assert incumbent["superseded_at_date"] == "2026-10-02"


def _supersede_chain_scenario(api):
    """CA filing A EFFECTIVE (2026-10-16) carrying an APPROVED deviation;
    filing B APPROVED with actual 2026-12-01; clock moved to 2026-12-01."""
    scenario = setup_ready_filing()  # CA PRIOR_APPROVAL, DRAFT->READY
    filing_a = scenario["filing"]
    deviation = create_deviation(
        filing_a["id"],
        **{
            "deviation_type": "RATE_FACTOR",
            "base_reference": "CW-TERR-REL",
            "deviation_factor": 1.05,
            "justification": "Wildfire load for CA territories",
        },
    )
    get_success_data(api.submit_filing(filing_a["id"], fx.OFFICER))
    get_success_data(api.approve_deviation(deviation["id"], fx.REGULATOR))
    set_clock("2026-09-01T00:00:00Z")
    get_success_data(api.approve_filing(filing_a["id"], fx.REGULATOR))
    set_clock("2026-10-16T00:00:00Z")
    filing_a = get_success_data(api.mark_filing_effective(filing_a["id"], fx.OFFICER))
    assert filing_a["status"] == "EFFECTIVE"

    filing_b = create_filing(
        scenario["product"]["id"],
        "CA",
        scenario["indication"]["id"],
        proposed_change_pct=0.05,
        proposed_effective_date="2026-12-01",
    )
    add_final_component(
        filing_b["id"],
        component_type="RATE",
        name="CA Base Rates v2",
        content_ref="s3://fil/ca-rate-v2.pdf",
    )
    get_success_data(api.mark_filing_ready(filing_b["id"], fx.ANALYST))
    get_success_data(api.submit_filing(filing_b["id"], fx.OFFICER))
    filing_b = get_success_data(api.approve_filing(filing_b["id"], fx.REGULATOR))
    assert filing_b["actual_effective_date"] == "2026-12-01"
    set_clock("2026-12-01T00:00:00Z")

    scenario["filing"] = filing_a
    scenario["deviation"] = deviation
    scenario["filing_b"] = filing_b
    return scenario


def test_mark_effective_supersedes_incumbent_filing(api):
    """PRD §3.5: "Success moves the filing to `EFFECTIVE`, supersedes the
    incumbent `EFFECTIVE` filing of the rate book (its `superseded_at_date`
    becomes the successor's `actual_effective_date`, and at the same moment
    its `APPROVED` deviations move to `SUPERSEDED` and its `FINAL` components
    move to `SUPERSEDED`), and marks the `EFFECTIVE_DATE` calendar entry
    `MET`."

    Design: Difficulty/transitive_cascade/mark_effective_supersede_deviation_chain
    """
    scenario = _supersede_chain_scenario(api)
    effective = validate_success(
        api.mark_filing_effective(scenario["filing_b"]["id"], fx.OFFICER), 200
    )
    assert effective["status"] == "EFFECTIVE"

    incumbent = get_success_data(
        api.get_filing(scenario["filing"]["id"], fx.OFFICER)
    )
    assert incumbent["status"] == "SUPERSEDED"
    assert incumbent["superseded_at_date"] == "2026-12-01"


def test_incumbent_supersession_retires_deviation_and_components(api):
    """PRD §3.5: "supersedes the incumbent `EFFECTIVE` filing of the rate book
    (its `superseded_at_date` becomes the successor's `actual_effective_date`,
    and at the same moment its `APPROVED` deviations move to `SUPERSEDED` and
    its `FINAL` components move to `SUPERSEDED`)".

    Design: Difficulty/transitive_cascade/mark_effective_supersede_deviation_chain
    """
    scenario = _supersede_chain_scenario(api)
    get_success_data(api.mark_filing_effective(scenario["filing_b"]["id"], fx.OFFICER))

    deviation = get_success_data(
        api.get_deviation(scenario["deviation"]["id"], fx.OFFICER)
    )
    assert deviation["status"] == "SUPERSEDED"
    component = get_success_data(
        api.get_component(scenario["components"][0]["id"], fx.OFFICER)
    )
    assert component["status"] == "SUPERSEDED"


def test_deviation_approve_requires_submitted_filing(api):
    """PRD §3.3: "The regulator adjudicates proposed deviations while the
    filing is `SUBMITTED` or `UNDER_OBJECTION`, approving them to `APPROVED` or
    rejecting them to `REJECTED` (a filing in any other state draws
    `ERR_INVALID_STATE`)".

    Design: Corner/state_machines/deviation_approve_requires_submitted_filing
    """
    scenario = setup_draft_filing()
    deviation = create_deviation(scenario["filing"]["id"])
    assert deviation["status"] == "PROPOSED"

    res = api.approve_deviation(deviation["id"], fx.REGULATOR)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)
    after = get_success_data(api.get_deviation(deviation["id"], fx.REGULATOR))
    assert after["status"] == "PROPOSED"


def test_deviation_rejected_by_regulator(api):
    """PRD §3.3: "The regulator adjudicates proposed deviations while the
    filing is `SUBMITTED` or `UNDER_OBJECTION`, approving them to `APPROVED` or
    rejecting them to `REJECTED`".

    Design: Corner/state_machines/deviation_rejected_by_regulator
    """
    scenario = setup_submitted_filing()
    deviation = get_success_data(
        api.create_deviation(
            create_deviation_payload(
                scenario["filing"]["id"],
                deviation_type="FORM_TEXT",
                base_reference="CW-FORM-1",
                deviation_factor=1.0,
                justification="State disclosure wording",
            ),
            fx.ANALYST,
        )
    )
    rejected = validate_success(
        api.reject_deviation(deviation["id"], fx.REGULATOR), 200
    )
    assert rejected["status"] == "REJECTED"


def test_withdraw_under_objection_cascades(api):
    """PRD §3.6: "From `SUBMITTED`, the same component and proposed-deviation
    withdrawals occur, any `APPROVED` deviations move to `SUPERSEDED` rather
    than `WITHDRAWN`, and the filing's `DEEMER_DATE` and `EFFECTIVE_DATE`
    calendar entries are waived."
    PRD §3.6: "From `UNDER_OBJECTION`, all of the submitted-state cascades
    apply and, in addition, every non-terminal objection is moved to
    `WITHDRAWN` with its `resolved_at` stamped and its still-pending calendar
    entry waived."

    Design: Corner/state_machines/withdraw_submitted_filing_cascades
    """
    scenario = setup_ready_filing()
    filing_id = scenario["filing"]["id"]
    component = scenario["components"][0]
    deviation = create_deviation(
        filing_id,
        **{
            "deviation_type": "RATE_FACTOR",
            "base_reference": "CW-TERR-REL",
            "deviation_factor": 1.05,
            "justification": "Wildfire load",
        },
    )
    get_success_data(api.submit_filing(filing_id, fx.OFFICER))
    set_clock("2026-08-10T12:00:00Z")
    objection = get_success_data(
        api.create_objection(
            {"filing_id": filing_id, "question_text": "Support the deviation."},
            fx.REGULATOR,
        )
    )
    under = get_success_data(api.get_filing(filing_id, fx.OFFICER))
    assert under["status"] == "UNDER_OBJECTION"

    withdrawn = validate_success(api.withdraw_filing(filing_id, fx.OFFICER), 200)
    assert withdrawn["status"] == "WITHDRAWN"

    assert (
        get_success_data(api.get_component(component["id"], fx.OFFICER))["status"]
        == "WITHDRAWN"
    )
    assert (
        get_success_data(api.get_deviation(deviation["id"], fx.OFFICER))["status"]
        == "WITHDRAWN"
    )
    assert (
        get_success_data(api.get_objection(objection["id"], fx.OFFICER))["status"]
        == "WITHDRAWN"
    )
    assert (
        find_calendar_entry(filing_id=filing_id, entry_type="DEEMER_DATE")["status"]
        == "WAIVED"
    )
    assert (
        find_calendar_entry(filing_id=filing_id, entry_type="EFFECTIVE_DATE")["status"]
        == "WAIVED"
    )
    assert (
        find_calendar_entry(
            objection_id=objection["id"], entry_type="OBJECTION_RESPONSE_DUE"
        )["status"]
        == "WAIVED"
    )


def test_disapprove_submitted_filing_waives_calendar(api):
    """PRD §3.6: "Against a `SUBMITTED` filing, disapproval moves it to
    `DISAPPROVED` and waives its `DEEMER_DATE` and `EFFECTIVE_DATE` calendar
    entries."

    Design: Corner/state_machines/disapprove_submitted_filing_pre_decision
    """
    scenario = setup_submitted_filing()
    filing_id = scenario["filing"]["id"]

    disapproved = validate_success(
        api.disapprove_filing(filing_id, fx.REGULATOR), 200
    )
    assert disapproved["status"] == "DISAPPROVED"
    assert (
        find_calendar_entry(filing_id=filing_id, entry_type="DEEMER_DATE")["status"]
        == "WAIVED"
    )
    assert (
        find_calendar_entry(filing_id=filing_id, entry_type="EFFECTIVE_DATE")["status"]
        == "WAIVED"
    )


def test_post_effective_disapproval_rejected_for_prior_approval(api):
    """PRD §3.6: "It is available only where the filing method permits
    post-effective review: the profile's `filing_method` must be `FILE_AND_USE`
    or `USE_AND_FILE`, and an attempt against a `PRIOR_APPROVAL` filing is
    rejected with `ERR_INVALID_STATE`."

    Design: Corner/validations/post_effective_disapproval_prior_approval_rejected
    """
    scenario = setup_effective_filing()  # CA PRIOR_APPROVAL
    set_clock("2026-10-20T00:00:00Z")
    res = api.disapprove_filing(scenario["filing"]["id"], fx.REGULATOR)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)
    after = get_success_data(api.get_filing(scenario["filing"]["id"], fx.REGULATOR))
    assert after["status"] == "EFFECTIVE"


def test_post_effective_disapproval_window_closed(api):
    """PRD §3.6: "The regulator must act within the statutory window: the
    current date may be no later than `disapproval_window_days` after the
    filing's `actual_effective_date`, or the attempt is rejected with
    `ERR_DISAPPROVAL_WINDOW_CLOSED` (HTTP 409)."

    Design: Corner/validations/post_effective_disapproval_window_closed
    """
    scenario = _nv_effective_scenario(api)  # effective 2026-10-01, window 90d
    # 2026-10-01 + 90 days = 2026-12-30; 2026-12-31 is past the window.
    set_clock("2026-12-31T00:00:00Z")
    res = api.disapprove_filing(scenario["filing"]["id"], fx.REGULATOR)
    validate_error(res, ApiErrorId.ERR_DISAPPROVAL_WINDOW_CLOSED)
    after = get_success_data(api.get_filing(scenario["filing"]["id"], fx.REGULATOR))
    assert after["status"] == "EFFECTIVE"


def test_disapproval_blocked_by_completed_wave(api):
    """PRD §3.6: "And the book must still be reversible: if any implementation
    wave of the filing has reached `COMPLETED`, the disapproval is blocked with
    `ERR_WAVE_NOT_REVERSIBLE` (HTTP 409)."

    Design: Corner/validations/disapproval_blocked_by_completed_wave
    """
    scenario = setup_effective_with_wave(
        state_code="NV",
        profile_overrides=dict(NV_FAU),
        policies=[("NV-3001", 100_000, 1.0, "2026-11-20")],
    )
    policy = scenario["policies"][0]
    wave = scenario["wave"]
    get_success_data(api.release_wave(wave["id"], fx.LEAD))

    set_clock("2026-10-05T00:00:00Z")
    get_success_data(api.send_policy_notice(policy["id"], fx.LEAD))
    set_clock("2026-11-20T00:00:00Z")
    get_success_data(api.complete_policy_renewal(policy["id"], fx.LEAD))

    # The 2026-12-16 sweep closes the wave window with every policy settled.
    set_clock("2026-12-16T00:00:00Z")
    wave_after = get_success_data(api.get_wave(wave["id"], fx.LEAD))
    assert wave_after["status"] == "COMPLETED"

    res = api.disapprove_filing(scenario["filing"]["id"], fx.REGULATOR)
    validate_error(res, ApiErrorId.ERR_WAVE_NOT_REVERSIBLE)
    after = get_success_data(api.get_filing(scenario["filing"]["id"], fx.REGULATOR))
    assert after["status"] == "EFFECTIVE"
