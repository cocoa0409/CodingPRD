"""Requests that violate two rules at once, where only the error id reveals the order.

Each pair is built so that both violations are genuinely live: the companion test removes
the higher-priority violation and shows the lower-priority rule firing on its own.
"""

from test_helpers import *  # noqa: F401,F403


# ---------------------------------------------------------------------------
# State before the review hold
# ---------------------------------------------------------------------------


def _held_submission_left_in_submitted():
    """A SUBMITTED design that the probation cascade has put on hold."""
    context = setup_active_agreement()
    mark = create_league_mark()
    submission = create_submission(
        context["agreement"]["id"],
        context["licensee"]["id"],
        [mark["id"]],
        sample_required=False,
    )
    submit_submission(submission["id"], context["licensee"]["id"])
    # Three seizures put the index at 45, which is the probation band.
    create_seizure_factors(context["licensee"]["id"], 3)
    context["close_counters"] = quarter_close("2026Q3")
    context["submission"] = get_submission(submission["id"])
    return context


def test_a_state_violation_outranks_the_review_hold_on_the_same_submit(api):
    """PRD §2.8: "12. The target entity's current state — or, for a `LicenseAgreement`, the
    relevant one of its two state dimensions — admits the requested transition. Otherwise
    `ERR_INVALID_STATE`."

    Design: Difficulty/priority_pair_validation_conflict/state_before_review_hold_returns_invalid_state
    """
    context = _held_submission_left_in_submitted()
    submission = context["submission"]

    assert context["close_counters"]["submissions_held"] == 1
    assert get_agreement(context["agreement"]["id"])["compliance_posture"] == "PROBATION"
    assert submission["status"] == "SUBMITTED"
    assert submission["review_hold"] is True

    response = api.submit_product_submission(
        submission["id"], None, make_licensee_headers(context["licensee"]["id"])
    )
    # Both rules are violated; the ordered catalogue answers with the state rule.
    validate_error(response, ApiErrorId.INVALID_STATE.value, 409)

    unchanged = get_submission(submission["id"])
    assert unchanged["status"] == "SUBMITTED"
    assert unchanged["revision_round"] == 0


def test_the_review_hold_fires_when_the_state_admits_the_transition(api, ops_headers):
    """PRD §2.8: "15. The submission's `review_hold` is false. This guards three
    operations: submitting or re-submitting a design, recording a review decision, and
    recording a sample verdict. In all three the rejection is `ERR_REVIEW_ON_HOLD`."

    Design: Difficulty/priority_pair_validation_conflict/state_before_review_hold_returns_invalid_state
    """
    context = _held_submission_left_in_submitted()
    submission = context["submission"]

    # SUBMITTED does admit BEGIN_REVIEW, so nothing masks the hold this time.
    response = api.create_submission_review_decision(
        submission["id"], submission_review_decision_payload("BEGIN_REVIEW"), ops_headers
    )
    validate_error(response, ApiErrorId.REVIEW_ON_HOLD.value, 409)

    assert get_submission(submission["id"])["status"] == "SUBMITTED"


# ---------------------------------------------------------------------------
# The term bound before the closeout hard limit
# ---------------------------------------------------------------------------


def _closeout_capable_operation():
    """A closeout-enabled account whose window reaches past the agreement's term."""
    return setup_licensed_operation(
        closeout_allowed=True,
        minimum_guarantee_cents=1000000,
        required_advance_cents=250000,
        term_start_date="2026-01-01",
        term_end_date="2027-12-31",
    )


def _over_limit_lines(authorization_id):
    """900 000 of closeout against 2 000 000 gross breaches the 4000 bps hard limit."""
    return simple_report_lines(
        authorization_id, 2000000, units=4000, closeout_sales_cents=900000
    )


def test_a_period_outside_the_term_outranks_the_closeout_hard_limit(api):
    """PRD §2.8: "25. The report's `period_quarter` lies within the agreement's term — at
    or after the quarter of `term_start_date` and at or before the quarter of
    `term_end_date`. Guards report creation; otherwise `ERR_PERIOD_OUTSIDE_TERM`. This
    referential check outranks every fiscal line check on the same request."

    Design: Difficulty/priority_pair_validation_conflict/period_outside_term_outranks_closeout_limit
    """
    context = _closeout_capable_operation()
    agreement_id = context["agreement"]["id"]
    version_before = agreement_version(agreement_id)

    payload = royalty_report_payload(
        agreement_id, "2028Q1", _over_limit_lines(context["authorization"]["id"]), version_before
    )
    response = api.create_royalty_report(
        payload, make_licensee_headers(context["licensee"]["id"])
    )
    validate_error(response, ApiErrorId.PERIOD_OUTSIDE_TERM.value, 422)

    listing = api.list_royalty_reports(
        TEST_USERS["finance_controller_headers"], {"agreement_id": agreement_id}
    )
    data, meta = validate_paginated(listing)
    assert data == []
    assert meta["total_count"] == 0
    assert agreement_version(agreement_id) == version_before


def test_the_closeout_hard_limit_fires_once_the_period_is_inside_the_term(api):
    """PRD §2.8: "30. For every channel line, `closeout_sales_cents` is at most
    `gross_sales_cents`, and also at most `gross_sales_cents` multiplied by the category's
    `closeout_hard_limit_bps` divided by 10000 and floored. Guards report creation and
    report line correction; otherwise `ERR_CLOSEOUT_LIMIT_EXCEEDED`."

    Design: Difficulty/priority_pair_validation_conflict/period_outside_term_outranks_closeout_limit
    """
    context = _closeout_capable_operation()
    agreement_id = context["agreement"]["id"]

    payload = royalty_report_payload(
        agreement_id,
        "2026Q2",
        _over_limit_lines(context["authorization"]["id"]),
        agreement_version(agreement_id),
    )
    response = api.create_royalty_report(
        payload, make_licensee_headers(context["licensee"]["id"])
    )
    validate_error(response, ApiErrorId.CLOSEOUT_LIMIT_EXCEEDED.value, 422)


# ---------------------------------------------------------------------------
# Off-price capacity before the retailer window buffer
# ---------------------------------------------------------------------------


def _licensee_at_off_price_capacity():
    """Two live off-price accounts, both overlapping the window a third would want."""
    licensee = create_active_licensee()
    outlet_a = create_authorized_retailer_authorization(
        licensee["id"],
        retailer_name="Outlet A",
        channel_class="OFF_PRICE",
        closeout_allowed=True,
        authorized_from="2026-01-01",
        authorized_to="2026-06-30",
    )
    outlet_b = create_authorized_retailer_authorization(
        licensee["id"],
        retailer_name="Outlet B",
        channel_class="OFF_PRICE",
        closeout_allowed=True,
        authorized_from="2026-06-01",
        authorized_to="2026-12-31",
    )
    return {"licensee": licensee, "outlet_a": outlet_a, "outlet_b": outlet_b}


def _third_off_price_request(licensee_id):
    return retailer_authorization_payload(
        licensee_version(licensee_id),
        retailer_name="Outlet A",
        channel_class="OFF_PRICE",
        sku_classes=["JERSEY"],
        authorized_from="2026-06-15",
        authorized_to="2026-12-31",
        closeout_allowed=True,
    )


def test_off_price_capacity_outranks_the_retailer_window_buffer(api, ops_headers):
    """PRD §2.8: "36. Off-price aggregate capacity, as described in Section 3.6. Guards
    retailer-authorization creation and the approve action; otherwise
    `ERR_OFF_PRICE_CAPACITY_EXCEEDED`."

    Design: Difficulty/priority_pair_validation_conflict/off_price_capacity_outranks_retailer_window_conflict
    """
    context = _licensee_at_off_price_capacity()
    licensee_id = context["licensee"]["id"]

    response = api.create_retailer_authorization(
        licensee_id, _third_off_price_request(licensee_id), ops_headers
    )
    validate_error(response, ApiErrorId.OFF_PRICE_CAPACITY_EXCEEDED.value, 409)

    assert get_authorization(context["outlet_a"]["id"])["status"] == "AUTHORIZED"
    assert get_authorization(context["outlet_b"]["id"])["status"] == "AUTHORIZED"
    listing = api.list_retailer_authorizations(
        ops_headers, {"licensee_id": licensee_id, "channel_class": "OFF_PRICE"}
    )
    _, meta = validate_paginated(listing)
    assert meta["total_count"] == 2


def test_the_window_buffer_fires_once_capacity_is_free_again(api, ops_headers):
    """PRD §3.6: "The off-price capacity rule counts only the same licensee's
    authorizations whose `channel_class` is `OFF_PRICE` and whose `status` is `PENDING` or
    `AUTHORIZED` and whose closed windows overlap the requested closed window"

    Design: Difficulty/priority_pair_validation_conflict/off_price_capacity_outranks_retailer_window_conflict
    """
    context = _licensee_at_off_price_capacity()
    licensee_id = context["licensee"]["id"]

    # A revoked row is counted by neither aggregate rule, so capacity is back to one.
    revoked = set_authorization_status(context["outlet_b"]["id"], "REVOKE")
    assert revoked["status"] == "REVOKED"

    response = api.create_retailer_authorization(
        licensee_id, _third_off_price_request(licensee_id), ops_headers
    )
    # Outlet A's window ends 2026-06-30, exactly inside the thirty-day buffer.
    validate_error(response, ApiErrorId.RETAILER_WINDOW_CONFLICT.value, 409)


# ---------------------------------------------------------------------------
# A frozen posture before a closed distribution
# ---------------------------------------------------------------------------


def _filed_local_report_after_the_quarter_was_distributed():
    """One licensee with a central and a non-central agreement in the same quarter.

    The central report is accepted and pooled; the non-central one stays FILED, which is
    why the run could still be locked and distributed.
    """
    create_club()
    jersey = create_jersey_category()
    novelty = create_category(minimal_category_payload())
    licensee = create_active_licensee()

    central = setup_active_agreement(
        category=jersey,
        licensee=licensee,
        minimum_guarantee_cents=1000000,
        required_advance_cents=250000,
        central_licensing_flag=True,
    )
    local = setup_active_agreement(
        category=novelty,
        licensee=licensee,
        minimum_guarantee_cents=500000,
        required_advance_cents=125000,
        central_licensing_flag=False,
    )
    authorization = create_authorized_retailer_authorization(
        licensee["id"], sku_classes=["JERSEY", "NOVELTY"]
    )

    central_lines = simple_report_lines(authorization["id"], 6250000, units=12500)
    central_report = create_report(
        central["agreement"]["id"], "2026Q2", central_lines, licensee["id"]
    )
    file_report(central_report["id"], licensee["id"])
    accept_report(central_report["id"])

    local_lines = simple_report_lines(authorization["id"], 1000000, units=2000)
    local_report = create_report(local["agreement"]["id"], "2026Q2", local_lines, licensee["id"])
    local_report = file_report(local_report["id"], licensee["id"])

    run = create_distribution_run("2026Q2")
    lock_run(run["id"])
    run = distribute_run(run["id"])

    return {
        "licensee": licensee,
        "central_agreement": central["agreement"],
        "local_agreement": local["agreement"],
        "local_report": local_report,
        "run": run,
    }


def test_a_frozen_posture_outranks_the_closed_distribution_on_the_same_accept(
    api, finance_headers
):
    """PRD §2.8: "16. The governing agreement's `compliance_posture` is not `FROZEN`. This
    guards six operations: opening a product submission under an agreement, submitting or
    re-submitting a design, recording a review decision, creating a territory grant under
    an agreement, changing a retailer authorization's status, and recording a review
    decision on a royalty report. In all six the rejection is `ERR_POSTURE_FROZEN`."

    Design: Difficulty/priority_pair_validation_conflict/posture_frozen_outranks_distribution_already_closed
    """
    context = _filed_local_report_after_the_quarter_was_distributed()
    report_id = context["local_report"]["id"]

    assert context["run"]["status"] == "DISTRIBUTED"
    assert context["run"]["pool_gross_cents"] == 500000
    assert context["run"]["report_count"] == 1

    # Four seizures put the index at 60, and the close drives the posture to FROZEN.
    create_seizure_factors(context["licensee"]["id"], 4)
    quarter_close("2026Q3")
    assert get_licensee(context["licensee"]["id"])["compliance_risk_index"] == 60
    assert get_agreement(context["local_agreement"]["id"])["compliance_posture"] == "FROZEN"
    assert context["local_report"]["status"] == "FILED"
    assert context["local_report"]["royalty_due_cents"] == 100000

    response = api.create_report_review_decision(
        report_id, report_review_decision_payload("ACCEPT"), finance_headers
    )
    validate_error(response, ApiErrorId.POSTURE_FROZEN.value, 409)

    assert get_report(report_id)["status"] == "FILED"
    assert get_agreement(context["local_agreement"]["id"])["cumulative_royalty_cents"] == 0


def test_the_closed_distribution_fires_when_the_posture_is_clear(api, finance_headers):
    """PRD §2.8: "37. Distribution interlocks, evaluated as three sub-conditions in this
    written order. Accepting a report requires that no distribution run for the same
    `period_quarter` has `status` `DISTRIBUTED`, otherwise
    `ERR_DISTRIBUTION_ALREADY_CLOSED`."

    Design: Difficulty/priority_pair_validation_conflict/posture_frozen_outranks_distribution_already_closed
    """
    context = _filed_local_report_after_the_quarter_was_distributed()
    report_id = context["local_report"]["id"]

    assert get_agreement(context["local_agreement"]["id"])["compliance_posture"] == "CLEAR"

    response = api.create_report_review_decision(
        report_id, report_review_decision_payload("ACCEPT"), finance_headers
    )
    validate_error(response, ApiErrorId.DISTRIBUTION_ALREADY_CLOSED.value, 409)

    assert get_report(report_id)["status"] == "FILED"
