"""Lifecycle transition guards: undeclared moves, terminal states and the
preconditions that stand in front of the irreversible commitments.

Every scenario is built through the API's own endpoints with the helpers in
``test_helpers.fixtures``; nothing reaches behind the service.
"""

from test_helpers import (
    CLEARANCE_SUPERVISOR,
    EO_MIN_PREMIUM_CENTS,
    LEGAL_COUNSEL,
    PRODUCTION_ADMIN,
    REVIEWING_COUNSEL,
    REVIEWING_COUNSEL_USER_ID,
    assert_asset_dimensions,
    assert_posture,
    assert_production_counters,
    create_and_execute_license,
    create_archive_with_rate_card,
    create_asset,
    create_asset_with_selected_source,
    create_eo_review_payload,
    create_fair_use_analysis,
    create_license,
    create_opinion_letter,
    create_production_in_clearance,
    create_subject_release,
    drive_fair_use_analysis,
    drive_production,
    drive_subject_release,
    get_asset,
    get_chart,
    get_delivery_package,
    get_license,
    get_production,
    get_production_version,
    get_success_data,
    open_eo_application,
    pin_chart,
    renew_license_payload,
    setup_licensed_footage_production,
    setup_validated_delivery_package,
    standard_all_media_fee_cents,
    state_payload,
    submit_eo_application,
    terminate_license,
    validate_error,
    validate_paginated,
    validate_success,
)


# ─── Private setup chains this module needs beyond fixtures.py ────────────────


def _setup_draft_footage_license(api):
    """A production in CLEARANCE holding one licence still in `DRAFT`.

    The asset is traced and sourced so licence creation passes the selected-source
    guard, but no negotiation round is posted, so the licence never leaves `DRAFT`.
    """
    production = create_production_in_clearance(api)
    archive, _card = create_archive_with_rate_card(api)
    asset, _candidate = create_asset_with_selected_source(
        api, production["id"], archive["id"])
    license_row = create_license(api, production["id"], asset["id"], archive["id"])
    return production, archive, asset, license_row


def _setup_release_signed_without_approval_rights(api):
    """A production in CLEARANCE with one `SIGNED` release that granted no approval."""
    production = create_production_in_clearance(api)
    release = create_subject_release(api, production["id"], "dunne-martin",
                                     release_type="LIFE_RIGHTS",
                                     depiction_from_date="2026-06-01",
                                     depiction_to_date="2026-06-30")
    drive_subject_release(api, release["id"], "SENT")
    signed = drive_subject_release(api, release["id"], "SIGNED", CLEARANCE_SUPERVISOR)
    return production, signed


def _setup_submitted_analysis_with_draft_letter(api):
    """A `SUBMITTED` fair-use analysis backed only by a letter still in `DRAFT`."""
    production = create_production_in_clearance(api)
    asset = create_asset(api, production["id"], title="Contested clip",
                         timecode_in_seconds=0, timecode_out_seconds=20,
                         usage_purpose="CRITICAL_COMMENTARY")
    analysis = create_fair_use_analysis(api, asset["id"], transformative_score=90,
                                        nature_score=60, amount_used_score=40,
                                        market_harm_score=50)
    drive_fair_use_analysis(api, analysis["id"], "SUBMITTED")
    letter = create_opinion_letter(api, analysis["id"], counsel_firm="Donaldson & Callif",
                                  letter_reference="OL-12", risk_rating="LOW")
    return production, asset, analysis, letter


def _setup_pinned_chart_and_draft_eo(api):
    """An assetless production in CLEARANCE with a `PINNED` chart and a `DRAFT` E&O file."""
    production = create_production_in_clearance(api)
    version_before_pin = get_production_version(api, production["id"])
    chart = pin_chart(api, production["id"], "v1")
    application = open_eo_application(api, production["id"], chart["id"],
                                      coverage_limit_cents=4000000,
                                      retention_cents=100000)
    return production, chart, application, version_before_pin


# ─── Licence lifecycle ───────────────────────────────────────────────────────


def test_license_execution_from_draft_is_refused_as_not_quoted(api):
    """A `DRAFT` licence cannot be executed, and the answer is the specific code.

    PRD §3.4: "Requesting execution from any other status is refused with
    `ERR_LICENSE_NOT_QUOTED` (HTTP 409), which displaces the generic
    invalid-transition answer." PRD §2.12 rung 10 pins the same routing: "requesting
    licence execution from any status other than `QUOTED` returns
    `ERR_LICENSE_NOT_QUOTED` (rung 12)". No money may move on the rejected call: PRD
    §2.9 requires `committed_fee_cents` to equal the sum of `executed_fee_cents` over
    the live licences, and a `DRAFT` licence is excluded from that set.

    Design: Corner/state_machines/license_execute_from_draft_rejected_as_not_quoted
    """
    production, _archive, asset, license_row = _setup_draft_footage_license(api)
    assert license_row["status"] == "DRAFT"
    assert license_row["version"] == 1
    assert license_row["executed_fee_cents"] is None

    response = api.set_license_state(license_row["id"], state_payload("EXECUTED"),
                                     CLEARANCE_SUPERVISOR)
    validate_error(response, "ERR_LICENSE_NOT_QUOTED")

    after = get_license(api, license_row["id"])
    assert after["status"] == "DRAFT", "the rejected execution must not move the licence"
    assert after["executed_fee_cents"] is None
    assert after["version"] == 1, "a rejected request is not a mutation, so version stands"

    assert get_production(api, production["id"])["committed_fee_cents"] == 0
    assert_asset_dimensions(get_asset(api, asset["id"]), "IN_NEGOTIATION",
                            rights_basis="UNDETERMINED", lapse_count=0)


def test_terminated_license_refuses_every_further_state_transition(api):
    """`TERMINATED` is terminal, and the ledger debit fires exactly once.

    PRD §3.4: "`EXPIRED`, `TERMINATED` and `LAPSED` are terminal for a licence."
    PRD §2.12 rung 10: "The requested transition is declared for the resource's
    current state — otherwise `ERR_INVALID_STATE_TRANSITION`. Applies to all eight
    state-driving operations (production, archive, licence, fair-use analysis,
    opinion letter, subject release, E&O application, delivery package), and covers
    any attempt to leave a terminal state." A request to execute is the one case
    routed elsewhere: "requesting licence execution from any status other than
    `QUOTED` returns `ERR_LICENSE_NOT_QUOTED` (rung 12)". PRD §3.4 fixes the money:
    "the production's `committed_fee_cents` is debited by exactly this licence's
    `executed_fee_cents`".

    Design: Corner/state_machines/terminated_license_is_terminal_and_rejects_every_further_transition
    """
    scenario = setup_licensed_footage_production(api)
    production_id = scenario["production"]["id"]
    license_id = scenario["license"]["id"]
    assert scenario["license"]["executed_fee_cents"] == standard_all_media_fee_cents()

    terminated = terminate_license(api, license_id, reason="Shot dropped")
    assert terminated["status"] == "TERMINATED"
    version_after_termination = terminated["version"]
    assert get_production(api, production_id)["committed_fee_cents"] == 0

    for to_status in ("TERMINATED", "ACTIVE", "LAPSED"):
        response = api.set_license_state(license_id, state_payload(to_status, reason="again"),
                                         CLEARANCE_SUPERVISOR)
        validate_error(response, "ERR_INVALID_STATE_TRANSITION")

    execute_again = api.set_license_state(license_id, state_payload("EXECUTED"),
                                          CLEARANCE_SUPERVISOR)
    validate_error(execute_again, "ERR_LICENSE_NOT_QUOTED")

    after = get_license(api, license_id)
    assert after["status"] == "TERMINATED"
    assert after["version"] == version_after_termination, (
        "four rejected transitions must leave the licence row untouched")
    assert after["executed_fee_cents"] == standard_all_media_fee_cents()

    assert get_production(api, production_id)["committed_fee_cents"] == 0, (
        "the executed fee was debited exactly once, not once per rejected call")
    assert_asset_dimensions(get_asset(api, scenario["asset"]["id"]), "LAPSED",
                            rights_basis="UNDETERMINED", lapse_count=1)


def test_terminated_license_cannot_be_renewed(api):
    """Renewal of a terminal licence is refused on the status gate, not the window.

    PRD §2.12 rung 12: "A licence is `QUOTED` before it may be executed, and is
    `ACTIVE` or `EXPIRING` before it may be renewed — otherwise
    `ERR_LICENSE_NOT_QUOTED`. Applies to licence execution and licence renewal."
    PRD §3.8 repeats it for the renewal path: "the licence must be in `ACTIVE` or
    `EXPIRING`, and any other status is refused with `ERR_LICENSE_NOT_QUOTED`".

    Design: Corner/state_machines/terminated_license_is_terminal_and_rejects_every_further_transition
    """
    scenario = setup_licensed_footage_production(api)
    license_id = scenario["license"]["id"]
    terminated = terminate_license(api, license_id, reason="Shot dropped")
    version_after_termination = terminated["version"]

    response = api.renew_license(license_id, renew_license_payload(12),
                                 CLEARANCE_SUPERVISOR)
    validate_error(response, "ERR_LICENSE_NOT_QUOTED")

    after = get_license(api, license_id)
    assert after["status"] == "TERMINATED"
    assert after["version"] == version_after_termination
    assert after["term_months"] == 36, "a rejected renewal extends nothing"
    assert after["term_end_date"] == "2029-08-15"
    assert get_production(api, scenario["production"]["id"])["committed_fee_cents"] == 0


# ─── Subject release lifecycle ───────────────────────────────────────────────


def test_second_send_of_a_sent_release_is_an_invalid_transition(api):
    """Re-sending a `SENT` release is an error rather than an idempotent replay.

    PRD §3.6: "`DRAFT → SENT` sends the paper out and has no preconditions." From
    `SENT` the declared moves are `SIGNED`, `REVISION_REQUESTED` and `REFUSED`, so a
    second send is undeclared and PRD §2.12 rung 10 applies: "The requested
    transition is declared for the resource's current state — otherwise
    `ERR_INVALID_STATE_TRANSITION`." PRD §2.4 makes the absence of a side effect
    observable: `version` "is incremented by exactly one on every mutation of the
    row", so a rejected call leaves it standing.

    Design: Corner/state_machines/subject_release_second_send_is_rejected_as_invalid_transition
    """
    production = create_production_in_clearance(api)
    release = create_subject_release(api, production["id"], "walsh-eileen")
    assert release["status"] == "DRAFT"
    assert release["version"] == 1

    sent = drive_subject_release(api, release["id"], "SENT")
    assert sent["status"] == "SENT"
    assert sent["version"] == 2
    assert sent["revision_round_count"] == 0

    response = api.set_subject_release_state(release["id"], state_payload("SENT"),
                                             PRODUCTION_ADMIN)
    validate_error(response, "ERR_INVALID_STATE_TRANSITION")

    after = get_success_data(api.get_subject_release(release["id"], PRODUCTION_ADMIN))
    assert after["status"] == "SENT"
    assert after["version"] == 2, "the rejected send fired no side effect"
    assert after["revision_round_count"] == 0


def test_refused_release_blocks_the_depiction_dimension_only(api):
    """A refusal drives dimension B to `BLOCKED` while dimension A stays `CLEARED`.

    PRD §3.6: "A refusal instead moves the linked asset's dimension B `PENDING →
    BLOCKED`." PRD §3.1 keeps the two dimensions apart: "Dimension A is
    `licensing_status`, taking `UNCLEARED`, `IN_NEGOTIATION`, `PARTIALLY_CLEARED`,
    `CLEARED` or `LAPSED`, and it advances on licence and fair-use events. Dimension
    B is `depiction_status`, taking `NOT_REQUIRED`, `PENDING`, `OBTAINED` or
    `BLOCKED`, and it advances only on subject-release events." PRD §2.8 rule 2:
    "Otherwise, if at least one asset has `depiction_status` of `BLOCKED`, or at
    least one asset has `licensing_status` of `LAPSED`, posture is `BLOCKED`."

    Design: Corner/state_machines/refused_release_blocks_the_asset_depiction_dimension_and_the_posture
    """
    production = create_production_in_clearance(api)
    archive, _card = create_archive_with_rate_card(api)
    asset, _candidate = create_asset_with_selected_source(
        api, production["id"], archive["id"], title="Interview cutaway",
        depiction_subject_key="walsh-eileen")
    create_and_execute_license(api, production["id"], asset["id"], archive["id"])

    before_asset = get_asset(api, asset["id"])
    assert_asset_dimensions(before_asset, "CLEARED", depiction_status="PENDING",
                            rights_basis="LICENSED", lapse_count=0)
    before_production = get_production(api, production["id"])
    assert_posture(before_production, "RESTRICTED")
    assert_production_counters(before_production, asset_count=1, cleared_asset_count=1,
                              open_asset_count=0)

    release = create_subject_release(api, production["id"], "walsh-eileen",
                                     asset_id=asset["id"],
                                     approval_rights="ROUGH_CUT_APPROVAL")
    drive_subject_release(api, release["id"], "SENT")

    response = api.set_subject_release_state(
        release["id"], state_payload("REFUSED", reason="Subject declined to sign"),
        PRODUCTION_ADMIN)
    refused = validate_success(response, 200)
    assert refused["status"] == "REFUSED"

    after_asset = get_asset(api, asset["id"])
    assert_asset_dimensions(after_asset, "CLEARED", depiction_status="BLOCKED",
                            rights_basis="LICENSED", lapse_count=0)

    after_production = get_production(api, production["id"])
    assert_posture(after_production, "BLOCKED")
    assert_production_counters(after_production, asset_count=1, cleared_asset_count=1,
                              open_asset_count=0)
    assert after_production["committed_fee_cents"] == standard_all_media_fee_cents(), (
        "a depiction refusal moves no money")


def test_approval_decisions_are_refused_when_no_approval_rights_were_granted(api):
    """Both approval outcomes bounce off a release whose `approval_rights` is `NONE`.

    PRD §3.6: "Both `SIGNED → APPROVAL_GRANTED` and `SIGNED → APPROVAL_WITHHELD`
    require `approval_rights` to be something other than `NONE` — a release granting
    no approval rights has no approval to give, and either request against such a
    release is refused with `ERR_NO_APPROVAL_RIGHTS` (HTTP 409)." The same section
    supplies the default that makes the guard fire: "`approval_rights` grants the
    subject a negotiated approval over the cut, taking `NONE`, `ROUGH_CUT_APPROVAL`
    or `FINAL_APPROVAL`, and defaults to `NONE`."

    Design: Corner/state_machines/approval_transition_without_approval_rights_rejected
    """
    _production, signed = _setup_release_signed_without_approval_rights(api)
    assert signed["approval_rights"] == "NONE"
    assert signed["status"] == "SIGNED"
    version_when_signed = signed["version"]

    for to_status in ("APPROVAL_GRANTED", "APPROVAL_WITHHELD"):
        response = api.set_subject_release_state(
            signed["id"], state_payload(to_status, cut_reference="RC-3"),
            CLEARANCE_SUPERVISOR)
        validate_error(response, "ERR_NO_APPROVAL_RIGHTS")

    after = get_success_data(api.get_subject_release(signed["id"], PRODUCTION_ADMIN))
    assert after["status"] == "SIGNED"
    assert after["version"] == version_when_signed
    assert after["cut_reference"] is None, "a refused decision stores no cut reference"


def test_release_revision_loop_is_capped_at_three_rounds(api):
    """The revision loop terminates on a counter and leaves the release usable.

    PRD §3.6: "`SENT → REVISION_REQUESTED` records the subject's counsel asking for
    changes; it is permitted only while `revision_round_count` is below 3, and the
    fourth request is refused with `ERR_RELEASE_REVISION_LIMIT` (HTTP 409). Each
    accepted revision request raises `revision_round_count` by one, and
    `REVISION_REQUESTED → SENT` returns the revised paper to the subject, so
    negotiated approvals may bounce between the subject's counsel and the production
    for up to three revision rounds." PRD §3.6 also declares the escape the ceiling
    does not close: "`SENT → SIGNED` records consent."

    Design: Corner/state_machines/release_revision_cycle_rejected_after_three_rounds
    """
    production = create_production_in_clearance(api)
    release = create_subject_release(api, production["id"], "walsh-eileen",
                                     release_type="DEPICTION_AGREEMENT",
                                     approval_rights="ROUGH_CUT_APPROVAL")
    assert release["revision_round_count"] == 0
    drive_subject_release(api, release["id"], "SENT")

    for expected_count in (1, 2, 3):
        revised = drive_subject_release(api, release["id"], "REVISION_REQUESTED",
                                        reason=f"Cycle {expected_count}")
        assert revised["status"] == "REVISION_REQUESTED"
        assert revised["revision_round_count"] == expected_count
        drive_subject_release(api, release["id"], "SENT")

    response = api.set_subject_release_state(
        release["id"], state_payload("REVISION_REQUESTED", reason="Cycle 4"),
        PRODUCTION_ADMIN)
    validate_error(response, "ERR_RELEASE_REVISION_LIMIT")

    after_rejection = get_success_data(api.get_subject_release(release["id"],
                                                              PRODUCTION_ADMIN))
    assert after_rejection["status"] == "SENT"
    assert after_rejection["revision_round_count"] == 3

    sign = api.set_subject_release_state(release["id"], state_payload("SIGNED"),
                                         CLEARANCE_SUPERVISOR)
    signed = validate_success(sign, 200)
    assert signed["status"] == "SIGNED", (
        "hitting the revision ceiling closes the loop without poisoning the release")
    assert signed["revision_round_count"] == 3


# ─── Fair-use analysis lifecycle ─────────────────────────────────────────────


def test_fair_use_acceptance_without_an_issued_letter_is_refused(api):
    """A `DRAFT` letter does not satisfy the acceptance gate, and it is checked first.

    PRD §3.5: "Acceptance has two, and their order matters: the opinion-letter
    requirement is checked first, so an analysis with no supporting letter is refused
    with `ERR_NO_ISSUED_OPINION_LETTER` (HTTP 409) even when its score is also too
    low, and only once at least one opinion letter on the analysis is in `ISSUED`
    does the score gate apply, refusing a `strength_score` below 0.6000 with
    `ERR_FAIR_USE_SCORE_INSUFFICIENT` (HTTP 422)." The score here is above the
    threshold, per the worked example of the same section: "factor scores of 90, 60,
    40 and 50 score 0.6750 under the transformative weighting and clear the
    acceptance threshold". PRD §2.12 rung 22 states the gate itself: "At least one
    opinion letter on the analysis is in `ISSUED` — otherwise
    `ERR_NO_ISSUED_OPINION_LETTER`."

    Design: Corner/state_machines/fair_use_accept_without_an_issued_opinion_letter_rejected
    """
    _production, asset, analysis, letter = _setup_submitted_analysis_with_draft_letter(api)
    assert analysis["weighting_variant"] == "TRANSFORMATIVE_WEIGHTED"
    assert analysis["strength_score"] == 0.6750
    assert letter["status"] == "DRAFT"

    response = api.set_fair_use_analysis_state(
        analysis["id"], state_payload("ACCEPTED", decision_rationale="Strong critique"),
        LEGAL_COUNSEL)
    validate_error(response, "ERR_NO_ISSUED_OPINION_LETTER")

    after_analysis = get_success_data(api.get_fair_use_analysis(analysis["id"],
                                                               LEGAL_COUNSEL))
    assert after_analysis["status"] == "SUBMITTED"
    assert after_analysis["decision_rationale"] is None
    assert after_analysis["strength_score"] == 0.6750

    letters, _meta = validate_paginated(
        api.list_opinion_letters(analysis["id"], LEGAL_COUNSEL, params={"limit": 100}))
    assert [row["status"] for row in letters] == ["DRAFT"]

    assert_asset_dimensions(get_asset(api, asset["id"]), "UNCLEARED",
                            rights_basis="UNDETERMINED", lapse_count=0)


# ─── Clearance chart and E&O lifecycle ───────────────────────────────────────


def test_superseded_chart_cannot_back_an_eo_submission(api):
    """A second pinning demotes the first chart even though its rows never moved.

    PRD §2.10: "Pinning a fresh chart on the same production moves every earlier
    chart of that production, whether it was `PINNED` or already `STALE`, to
    `SUPERSEDED`, and a `SUPERSEDED` chart likewise cannot back a submission or a
    validation — that refusal carries `ERR_CHART_SUPERSEDED` (HTTP 409)." PRD §3.7
    applies it to the submission: "the referenced chart must still be `PINNED`, so a
    chart that has gone stale is refused with `ERR_CHART_STALE` and one that has been
    superseded with `ERR_CHART_SUPERSEDED`". The same section explains why the second
    pin needs a fresh expected version: "the production's `version` increments — which
    is why two clients cannot pin back-to-back charts without the second re-reading
    first."

    Design: Corner/state_machines/chart_superseded_by_a_later_pinning_cannot_back_an_eo_submission
    """
    production, first_chart, application, version_before_pin = \
        _setup_pinned_chart_and_draft_eo(api)
    assert first_chart["status"] == "PINNED"
    assert first_chart["pinned_row_count"] == 0

    version_after_pin = get_production_version(api, production["id"])
    assert version_after_pin != version_before_pin, (
        "pinning a chart increments the production's version")

    second_chart = pin_chart(api, production["id"], "v2")
    assert second_chart["status"] == "PINNED"
    assert second_chart["pinned_row_count"] == 0, (
        "the production has no assets, so the demotion cannot be row-driven")
    assert get_chart(api, first_chart["id"])["status"] == "SUPERSEDED"

    response = api.set_eo_application_state(application["id"], state_payload("SUBMITTED"),
                                            CLEARANCE_SUPERVISOR)
    validate_error(response, "ERR_CHART_SUPERSEDED")

    after = get_success_data(api.get_eo_application(application["id"],
                                                    CLEARANCE_SUPERVISOR))
    assert after["status"] == "DRAFT"
    assert after["premium_cents"] is None
    assert after["legal_review_status"] == "PENDING"
    assert after["underwriting_review_status"] == "PENDING"
    assert after["clearance_chart_id"] == first_chart["id"]


def test_first_failed_review_declines_the_application_and_clears_the_premium(api):
    """A failing first review carries the application straight to `DECLINED`.

    PRD §3.7: "The failure case has one shortcut worth stating plainly: when the very
    first review recorded on a `SUBMITTED` application is a `FAIL`, the single call
    carries the application through `SUBMITTED → IN_REVIEW → DECLINED`, and the
    observable end state is `DECLINED`." The same section fixes the fiscal side
    effect: "When either dimension reads `FAILED`, the application moves `IN_REVIEW →
    DECLINED` and `premium_cents` is reset to null — a declined application is not a
    priced one, and it forbids any delivery." It also fixes the attribution: "An
    accepted review sets its dimension to `PASSED` or `FAILED` according to the
    `outcome`, stamps the acting `X-User-ID` into `legal_reviewer_user_id` or
    `underwriting_reviewer_user_id`, and increments the application's `version`." The
    rated premium is the floor of PRD §3.7: base premium 4000000 × 0.0125 = 50000,
    no rateable rows, retention credit 100000 × 0.30 = 30000, and "`premium_cents` is
    the base premium plus the loading total minus the retention credit, floored at a
    minimum premium of 25000 cents".

    Design: Corner/state_machines/first_failed_review_declines_the_eo_application_and_clears_the_premium
    """
    _production, _chart, application, _version = _setup_pinned_chart_and_draft_eo(api)
    submitted = submit_eo_application(api, application["id"])
    assert submitted["status"] == "SUBMITTED"
    assert submitted["premium_cents"] == EO_MIN_PREMIUM_CENTS
    assert submitted["legal_review_status"] == "PENDING"
    assert submitted["underwriting_review_status"] == "PENDING"

    response = api.create_eo_review(
        application["id"],
        create_eo_review_payload("LEGAL", "FAIL", notes="Unresolved chain of title"),
        REVIEWING_COUNSEL)
    # PRD §4: 201 is reserved for operations that bring a new resource into
    # existence. Recording a review branch mutates the E&O application (there is
    # no review resource and no way to read one back), so this answers 200 OK.
    validate_success(response, 200)

    after = get_success_data(api.get_eo_application(application["id"],
                                                    CLEARANCE_SUPERVISOR))
    assert after["status"] == "DECLINED"
    assert after["legal_review_status"] == "FAILED"
    assert after["legal_reviewer_user_id"] == REVIEWING_COUNSEL_USER_ID
    assert after["premium_cents"] is None, "the DECLINED side effect clears the premium"
    assert after["underwriting_review_status"] == "PENDING", (
        "the second branch was never joined")
    assert after["underwriting_reviewer_user_id"] is None
    assert after["policy_number"] is None


# ─── Production lifecycle ────────────────────────────────────────────────────


def test_abandonment_is_refused_while_a_licence_is_still_live(api):
    """Abandonment is gated on an aggregate over the production's licences.

    PRD §3.1: "From `CLEARANCE`, abandonment first checks that no licence of the
    production sits in `EXECUTED`, `ACTIVE` or `EXPIRING`; if one does, the request is
    refused with `ERR_LICENSES_STILL_LIVE`, because a film cannot be walked away from
    while binding money is outstanding." PRD §3.4 supplies the cure and its exact
    compensation: "From `EXECUTED`, `ACTIVE` or `EXPIRING`, a `ClearanceSupervisor`
    may move the licence to `TERMINATED`; the supplied `reason` is stored as
    `termination_reason`, the production's `committed_fee_cents` is debited by exactly
    this licence's `executed_fee_cents`".

    Design: Corner/state_machines/production_abandon_rejected_while_a_license_is_still_live
    """
    scenario = setup_licensed_footage_production(api)
    production_id = scenario["production"]["id"]
    license_id = scenario["license"]["id"]
    assert get_license(api, license_id)["status"] == "EXECUTED"

    refused = api.set_production_state(
        production_id, state_payload("ABANDONED", reason="Financing collapsed"),
        PRODUCTION_ADMIN)
    validate_error(refused, "ERR_LICENSES_STILL_LIVE")

    still_in_clearance = get_production(api, production_id)
    assert still_in_clearance["status"] == "CLEARANCE"
    assert still_in_clearance["committed_fee_cents"] == standard_all_media_fee_cents()

    terminate_license(api, license_id, reason="Production abandoned")

    accepted = api.set_production_state(
        production_id, state_payload("ABANDONED", reason="Financing collapsed"),
        PRODUCTION_ADMIN)
    abandoned = validate_success(accepted, 200)
    assert abandoned["status"] == "ABANDONED"
    assert abandoned["committed_fee_cents"] == 0
    assert_asset_dimensions(get_asset(api, scenario["asset"]["id"]), "LAPSED",
                            rights_basis="UNDETERMINED", lapse_count=1)


def test_production_delivery_is_refused_without_a_delivered_package(api):
    """The final production move counts `DELIVERED` packages, not `VALIDATED` ones.

    PRD §3.1: "The move `LOCKED → DELIVERED`, also a `ClearanceSupervisor` move,
    requires at least one delivery package of the production in `DELIVERED`, failing
    which the answer is `ERR_NO_DELIVERED_PACKAGE`." PRD §3.8 states the separate
    package-level gate that this production is already able to pass: "Moving
    `VALIDATED → DELIVERED` requires the production's `posture` to be exactly `OPEN`,
    refusing a merely restricted production with `ERR_PRODUCTION_POSTURE_RESTRICTED`;
    it requires the referenced chart to still be `PINNED`, refusing a stale one with
    `ERR_CHART_STALE`; and it requires the production to hold an E&O application in
    `BOUND`, refusing an uninsured delivery with `ERR_EO_NOT_BOUND`."

    Design: Corner/state_machines/production_delivered_rejected_without_a_delivered_package
    """
    scenario = setup_validated_delivery_package(api)
    production_id = scenario["production"]["id"]
    package_id = scenario["delivery_package"]["id"]
    assert scenario["delivery_package"]["status"] == "VALIDATED"
    assert scenario["eo_application"]["status"] == "BOUND"
    assert get_chart(api, scenario["chart"]["id"])["status"] == "PINNED"

    locked = drive_production(api, production_id, "LOCKED", CLEARANCE_SUPERVISOR)
    assert locked["status"] == "LOCKED"
    assert_posture(locked, "OPEN")

    refused = api.set_production_state(production_id, state_payload("DELIVERED"),
                                       CLEARANCE_SUPERVISOR)
    validate_error(refused, "ERR_NO_DELIVERED_PACKAGE")
    assert get_production(api, production_id)["status"] == "LOCKED"
    assert get_delivery_package(api, package_id)["status"] == "VALIDATED"

    deliver_package = api.set_delivery_package_state(
        package_id, state_payload("DELIVERED"), CLEARANCE_SUPERVISOR)
    delivered_package = validate_success(deliver_package, 200)
    assert delivered_package["status"] == "DELIVERED"
    assert delivered_package["cue_sheet_row_count"] == 0
    assert delivered_package["rights_chart_row_count"] == 1
    assert delivered_package["music_leg_gap_count"] == 0

    accepted = api.set_production_state(production_id, state_payload("DELIVERED"),
                                        CLEARANCE_SUPERVISOR)
    delivered_production = validate_success(accepted, 200)
    assert delivered_production["status"] == "DELIVERED"
