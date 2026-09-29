"""One rejection per guard, arranged so each call has exactly one defect.

The ladder is climbed from its first rung upward: identity, request shape, the
data-element matrix, the uniqueness and referential keys, the input-completeness
guards, the two correction ceilings, the docket's calendar and procedural gates,
the money gates, the collection gates, and finally one wrong-state rejection per
state-guarded record.
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import constants as k
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import test_users as u
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_clock_stamp,
    assert_error_envelope_shape,
    assert_penalty_breakdown,
    assert_penalty_ledger,
    assert_registration_number_format,
    assert_submission_totals,
    assert_window_ledger,
)
from test_helpers.types import (
    AuditCaseStatus,
    BasisVariant,
    MethodologyChangeStatus,
    PlantStatus,
    ProductClass,
    PurchaseType,
    RegistrationStatus,
    ReportCategory,
    ReportClass,
    ReportingWindowStatus,
    Species,
    SubmissionStatus,
    SuspendedReason,
    ViolationType,
    WeightingVariant,
)

ZERO_HEAD_HISTORY = {"2021": 0, "2022": 0, "2023": 0, "2024": 0, "2025": 0}
SWINE_HISTORY = {
    "2021": 200000,
    "2022": 200000,
    "2023": 200000,
    "2024": 200000,
    "2025": 200000,
}
HISTORY_MISSING_A_LOOKBACK_YEAR = {
    "2021": 130000,
    "2023": 130000,
    "2024": 130000,
    "2025": 130000,
}
COMPLETE_HISTORY = {
    "2021": 130000,
    "2022": 130000,
    "2023": 130000,
    "2024": 130000,
    "2025": 130000,
}


def test_01_identity_is_checked_before_the_endpoints_role_list(api):
    """Three malformed identities are 401; two well-formed wrong ones are 403.

    An absent role header, an absent user header and a role name outside the six
    declared roles all collapse to the same authentication failure, while a public
    reader and a reporting firm -- both perfectly well identified -- are turned
    away from the reporter registry and the plant register by the role list.

    PRD §2.1: "If either header is absent, or if `X-User-Role` is not one of the
    six role names below, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP
    401)."

    Design: Corner/validations/missing_headers_and_role_gate_returns_401_403
    """
    entity = fx.create_entity(api, legal_name="Alpha Packing")

    for headers in (
        u.HEADERS_WITHOUT_ROLE,
        u.HEADERS_WITHOUT_USER_ID,
        u.HEADERS_UNRECOGNISED_ROLE,
    ):
        validate_error(
            api.list_reporting_entities(headers),
            ApiErrorId.ERR_UNAUTHENTICATED.value,
            401,
        )

    refused_public = api.list_reporting_entities(u.PUBLIC_USER)
    validate_error(refused_public, ApiErrorId.ERR_UNAUTHORIZED.value, 403)
    assert_error_envelope_shape(refused_public)

    validate_error(
        api.create_plant(
            f.plant_payload(
                entity["id"],
                plant_code="EST-999",
                annual_head_history=dict(ZERO_HEAD_HISTORY),
            ),
            u.reporter_agent(entity["id"]),
        ),
        ApiErrorId.ERR_UNAUTHORIZED.value,
        403,
    )

    _plants, meta = validate_paginated(api.list_plants(u.PROGRAM_ADMIN))
    assert meta["total_count"] == 0, meta


def test_02_malformed_payloads_and_page_arguments_are_all_one_bad_request(api):
    """Four shapes of malformation, one error id, no lookup ever reached.

    A missing required field, a value outside a declared enum, a trade period
    running backwards, a deadline chain out of order and page arguments outside
    their declared ranges are all rejected as malformed requests -- and although
    every identifier in those payloads is real, nothing is created.

    PRD §2.3: "A `limit` below 1 or above 100, or a negative `offset`, is a
    malformed request and is rejected with `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/validations/malformed_inputs_return_400_invalid_request
    """
    entity = fx.create_entity(api, legal_name="Alpha Packing")
    history = {"2021": 1, "2022": 1, "2023": 1, "2024": 1, "2025": 1}

    validate_error(
        api.create_plant(
            {
                "reporting_entity_id": entity["id"],
                "plant_code": "EST-101",
                "annual_head_history": history,
            },
            u.PROGRAM_ADMIN,
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value,
        400,
    )
    validate_error(
        api.create_plant(
            f.plant_payload(
                entity["id"], species="GOAT", annual_head_history=history
            ),
            u.PROGRAM_ADMIN,
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value,
        400,
    )

    validate_error(
        api.create_reporting_window(
            f.reporting_window_payload(
                period_start=k.WINDOW_PERIOD_END, period_end=k.WINDOW_PERIOD_START
            ),
            u.PROGRAM_ADMIN,
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value,
        400,
    )
    validate_error(
        api.create_reporting_window(
            f.reporting_window_payload(
                submission_deadline_utc="2026-08-19T15:00:00Z",
                correction_deadline_utc="2026-08-18T15:00:00Z",
                publication_release_utc="2026-08-20T12:00:00Z",
            ),
            u.PROGRAM_ADMIN,
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value,
        400,
    )

    for params in ({"limit": 0}, {"limit": 101}, {"offset": -1}):
        validate_error(
            api.list_plants(u.PROGRAM_ADMIN, params=params),
            ApiErrorId.ERR_INVALID_REQUEST.value,
            400,
        )

    _plants, plant_meta = validate_paginated(api.list_plants(u.PROGRAM_ADMIN))
    assert plant_meta["total_count"] == 0, plant_meta
    _windows, window_meta = validate_paginated(
        api.list_reporting_windows(u.PROGRAM_ADMIN)
    )
    assert window_meta["total_count"] == 0, window_meta


def test_03_the_required_element_matrix_is_enforced_in_both_polarities(api):
    """Three missing elements, two forbidden ones, one inverted span, one success.

    Each purchase type is probed for the element it must carry and for the ones it
    must not, the delivery span is probed for inversion, and only the seventh
    append -- a well-formed forward contract -- lands on the filing, so none of the
    six refusals left any trace in the booked totals.

    PRD §3.4: "The mirror rule is equally strict: a `NEGOTIATED` or `PACKER_OWNED`
    line must carry none of `formula_base_reference`,
    `grid_premium_discount_per_cwt`, `forward_delivery_start` or
    `forward_delivery_end`, and a `FORMULA` line must not carry
    `grid_premium_discount_per_cwt`; a forbidden element present on a line is
    rejected with `ERR_FORBIDDEN_PURCHASE_TYPE_ELEMENT`."

    Design: Corner/validations/purchase_type_data_element_rules_rejected
    """
    firm = fx.obligated_firm(api, legal_name="Alpha Packing")
    window = fx.create_standard_window(api)
    filing = fx.draft_filing(
        api, firm["entity"]["id"], firm["plant"]["id"], window["id"]
    )
    reporter = u.reporter_agent(firm["entity"]["id"])

    for payload in (
        f.transaction_payload(
            purchase_type=PurchaseType.FORMULA.value,
            head_count=100,
            avg_net_price_per_cwt=290.00,
            avg_carcass_weight_cwt=9.00,
        ),
        f.transaction_payload(
            purchase_type=PurchaseType.NEGOTIATED_GRID.value,
            head_count=100,
            avg_net_price_per_cwt=285.50,
            avg_carcass_weight_cwt=8.80,
        ),
        f.transaction_payload(
            purchase_type=PurchaseType.FORWARD_CONTRACT.value,
            head_count=100,
            avg_net_price_per_cwt=284.00,
            avg_carcass_weight_cwt=8.50,
        ),
    ):
        validate_error(
            api.add_transaction(filing["id"], payload, reporter),
            ApiErrorId.ERR_MISSING_PURCHASE_TYPE_ELEMENT.value,
            422,
        )

    for payload in (
        f.transaction_payload(
            purchase_type=PurchaseType.NEGOTIATED.value,
            formula_base_reference="CME_LIVE_CATTLE_INDEX",
        ),
        f.transaction_payload(
            purchase_type=PurchaseType.FORMULA.value,
            head_count=100,
            avg_net_price_per_cwt=292.25,
            avg_carcass_weight_cwt=9.40,
            formula_base_reference="CME_LIVE_CATTLE_INDEX",
            grid_premium_discount_per_cwt=3.25,
        ),
    ):
        validate_error(
            api.add_transaction(filing["id"], payload, reporter),
            ApiErrorId.ERR_FORBIDDEN_PURCHASE_TYPE_ELEMENT.value,
            422,
        )

    validate_error(
        api.add_transaction(
            filing["id"],
            f.forward_transaction_payload(
                forward_delivery_start="2026-09-17T00:00:00Z",
                forward_delivery_end="2026-09-10T00:00:00Z",
                head_count=500,
                avg_net_price_per_cwt=284.00,
                avg_carcass_weight_cwt=8.50,
            ),
            reporter,
        ),
        ApiErrorId.ERR_FORWARD_DELIVERY_INTERVAL_INVALID.value,
        422,
    )

    accepted = get_success_data(
        api.add_transaction(
            filing["id"],
            f.forward_transaction_payload(
                forward_delivery_start="2026-09-10T00:00:00Z",
                forward_delivery_end="2026-09-17T00:00:00Z",
                head_count=500,
                avg_net_price_per_cwt=284.00,
                avg_carcass_weight_cwt=8.50,
            ),
            reporter,
        ),
        expected_status=201,
    )
    assert accepted["line_value_dollars"] == 1207000.00, accepted
    assert_submission_totals(
        fx.read_submission(api, filing["id"]), reported_head=500
    )


def test_04_the_determination_docket_is_unique_per_firm_and_year_not_per_firm(api):
    """The same firm may hold two files if the years differ.

    A second 2026 file for a firm that already has one is refused and leaves the
    incumbent's basis alone, while a 2027 file for that same firm and a 2026 file
    for a different firm are both opened in the very next calls.

    PRD §3.2: "Only one determination file may be live per firm and year: if a
    record for that pair already exists in any status other than `REVOKED`, the
    creation is rejected with `ERR_DUPLICATE_REGISTRATION_YEAR`."

    Design: Corner/validations/duplicate_registration_year_rejected_but_other_year_accepted
    """
    alpha = fx.create_entity(api, legal_name="Alpha Packing")
    bravo = fx.create_entity(api, legal_name="Bravo Beef")
    fx.create_plant(api, alpha["id"], plant_code="EST-101")
    fx.create_plant(api, bravo["id"], plant_code="EST-202")
    incumbent = fx.draft_registration(api, alpha["id"])
    version_before = fx.entity_version(api, alpha["id"])

    validate_error(
        api.create_registration(
            f.registration_payload(
                alpha["id"],
                determination_year=2026,
                basis_variant=BasisVariant.PRIOR_YEAR_ACTUAL.value,
            ),
            u.PROGRAM_ADMIN,
        ),
        ApiErrorId.ERR_DUPLICATE_REGISTRATION_YEAR.value,
        409,
    )
    assert (
        fx.read_registration(api, incumbent["id"])["basis_variant"]
        == BasisVariant.FIVE_YEAR_AVERAGE.value
    )
    assert fx.entity_version(api, alpha["id"]) == version_before

    next_year = get_success_data(
        api.create_registration(
            f.registration_payload(
                alpha["id"],
                determination_year=2027,
                basis_variant=BasisVariant.FIVE_YEAR_AVERAGE.value,
            ),
            u.PROGRAM_ADMIN,
        ),
        expected_status=201,
    )
    assert next_year["determination_year"] == 2027, next_year
    assert next_year["status"] == RegistrationStatus.DRAFT.value, next_year

    other_firm = get_success_data(
        api.create_registration(
            f.registration_payload(bravo["id"], determination_year=2026),
            u.PROGRAM_ADMIN,
        ),
        expected_status=201,
    )
    assert other_firm["determination_year"] == 2026, other_firm
    assert other_firm["status"] == RegistrationStatus.DRAFT.value, other_firm

    _rows, meta = validate_paginated(api.list_registrations(u.PROGRAM_ADMIN))
    assert meta["total_count"] == 3, meta


def test_05_live_animal_and_wholesale_reporting_may_not_bleed_into_each_other(api):
    """Four referential guards, at each of their declared sites.

    A swine plant cannot file into a cattle window, a boxed-beef report cannot be
    opened over a live-animal window, the line-item class guard bites in both
    directions, and a plant whose wholesale volume never reached the threshold
    cannot attach a wholesale lot at all.

    PRD §3.5: "And the line's kind must match the window's class: transaction lines
    belong only to `LIVE_ANIMAL` windows and wholesale lots only to `BOXED_BEEF` or
    `WHOLESALE_CUTS` windows, with a mismatch rejected as
    `ERR_LINE_ITEM_CLASS_MISMATCH`."

    Design: Corner/validations/class_and_wholesale_authorization_mismatches_rejected
    """
    alpha = fx.firm_with_plants(
        api,
        [
            {"plant_code": "EST-101", "boxed_beef_volume_lbs_prior_year": 2500000},
            {
                "plant_code": "EST-102",
                "annual_head_history": dict(ZERO_HEAD_HISTORY),
                "boxed_beef_volume_lbs_prior_year": 0,
            },
        ],
        legal_name="Alpha Packing",
    )
    alpha_id = alpha["entity"]["id"]
    swine = fx.obligated_firm(
        api,
        legal_name="Swine Co",
        plant_code="EST-501",
        species=Species.SWINE.value,
        species_scope=Species.SWINE.value,
        annual_head_history=dict(SWINE_HISTORY),
    )

    live_window = fx.create_standard_window(api)
    boxed_window = fx.create_relaxed_window(
        api, report_class=ReportClass.BOXED_BEEF.value, min_reported_head=1
    )

    live_filing = fx.draft_filing(
        api, alpha_id, alpha["plants"][0]["id"], live_window["id"]
    )
    boxed_filing = fx.draft_filing(
        api, alpha_id, alpha["plants"][0]["id"], boxed_window["id"]
    )

    validate_error(
        api.create_submission(
            f.submission_payload(
                swine["plant"]["id"],
                live_window["id"],
                fx.window_version(api, live_window["id"]),
            ),
            u.reporter_agent(swine["entity"]["id"]),
        ),
        ApiErrorId.ERR_SPECIES_CLASS_MISMATCH.value,
        422,
    )

    validate_error(
        api.create_market_report(
            f.market_report_payload(
                live_window["id"],
                category=ReportCategory.BOXED_BEEF_CUTOUT.value,
                weighting_variant=WeightingVariant.HEAD_WEIGHTED.value,
            ),
            u.MARKET_ANALYST,
        ),
        ApiErrorId.ERR_SPECIES_CLASS_MISMATCH.value,
        422,
    )
    _reports, report_meta = validate_paginated(
        api.list_market_reports(u.MARKET_ANALYST)
    )
    assert report_meta["total_count"] == 0, report_meta

    validate_error(
        api.add_wholesale_lot(
            live_filing["id"],
            f.wholesale_lot_payload(
                product_class=ProductClass.BOXED_BEEF_CHOICE_CUTOUT.value
            ),
            u.reporter_agent(alpha_id),
        ),
        ApiErrorId.ERR_LINE_ITEM_CLASS_MISMATCH.value,
        422,
    )
    validate_error(
        api.add_transaction(
            boxed_filing["id"], f.transaction_payload(), u.reporter_agent(alpha_id)
        ),
        ApiErrorId.ERR_LINE_ITEM_CLASS_MISMATCH.value,
        422,
    )

    unauthorized_filing = fx.draft_filing(
        api, alpha_id, alpha["plants"][1]["id"], boxed_window["id"]
    )
    validate_error(
        api.add_wholesale_lot(
            unauthorized_filing["id"],
            f.wholesale_lot_payload(),
            u.reporter_agent(alpha_id),
        ),
        ApiErrorId.ERR_WHOLESALE_NOT_AUTHORIZED.value,
        409,
    )

    for submission_id in (
        live_filing["id"],
        boxed_filing["id"],
        unauthorized_filing["id"],
    ):
        resting = fx.read_submission(api, submission_id)
        assert resting["status"] == SubmissionStatus.DRAFT.value, resting
        assert_submission_totals(
            resting,
            reported_head=0,
            reported_cwt=0.00,
            reported_value_dollars=0.00,
            reported_pounds=0.00,
            reported_load_count=0,
        )

    for window_id in (live_window["id"], boxed_window["id"]):
        assert_window_ledger(
            fx.read_window(api, window_id),
            total_head_reported=0,
            accepted_submission_count=0,
        )


def test_06_the_determination_checks_its_inputs_before_measuring_anything(api):
    """A gap in the history and an empty eligible set, on two separate firms.

    A firm whose only operating plant is missing one lookback year cannot be
    measured, and a firm whose sole plant is closed has nothing to measure even
    though that plant's history is complete -- and neither refusal writes a
    measurement of any kind.

    PRD §3.2: "Only plants of the firm whose `status` is `ACTIVE` or `IDLE`
    participate — a `CLOSED` plant never contributes a single head."

    Design: Corner/validations/determination_prerequisites_rejected
    """
    echo = fx.create_entity(api, legal_name="Echo Meats")
    fx.create_plant(
        api,
        echo["id"],
        plant_code="EST-701",
        annual_head_history=dict(HISTORY_MISSING_A_LOOKBACK_YEAR),
    )
    echo_file = fx.draft_registration(api, echo["id"])

    foxtrot = fx.create_entity(api, legal_name="Foxtrot Foods")
    fx.create_plant(
        api,
        foxtrot["id"],
        plant_code="EST-801",
        status=PlantStatus.CLOSED.value,
        annual_head_history=dict(COMPLETE_HISTORY),
    )
    foxtrot_file = fx.draft_registration(api, foxtrot["id"])

    validate_error(
        api.determine_registration(echo_file["id"], u.PROGRAM_ADMIN),
        ApiErrorId.ERR_INCOMPLETE_SLAUGHTER_HISTORY.value,
        422,
    )
    validate_error(
        api.determine_registration(foxtrot_file["id"], u.PROGRAM_ADMIN),
        ApiErrorId.ERR_NO_ELIGIBLE_PLANTS.value,
        409,
    )

    for created in (echo_file, foxtrot_file):
        untouched = fx.read_registration(api, created["id"])
        assert untouched["status"] == RegistrationStatus.DRAFT.value, untouched
        assert untouched["determination_outcome"] is None, untouched
        assert untouched["registration_number"] is None, untouched
        assert untouched["version"] == created["version"], untouched
        assert untouched["measured_head"] == created["measured_head"], untouched
        assert untouched["threshold_head"] == created["threshold_head"], untouched


def test_07_the_correction_ceiling_yields_to_the_correction_deadline(api):
    """The same request, refused for the count and then for the calendar.

    A filing that has already been through both permitted correction rounds is
    refused a third reopening for the count, and once the clock passes the
    correction deadline the identical request violates both rules and reports the
    deadline instead -- and the filing sits still through both refusals.

    PRD §3.5: "Two gates apply to this reporter-facing route: the filing's
    `resubmission_count` must be below 2, or the request is refused with
    `ERR_RESUBMISSION_LIMIT_REACHED`, and the logical clock must be at or before
    the window's `correction_deadline_utc`, or it is refused with
    `ERR_CORRECTION_WINDOW_CLOSED`".

    Design: Corner/validations/correction_limit_then_closed_deadline_rejected
    """
    firm = fx.obligated_firm(api, legal_name="Alpha Packing")
    entity_id = firm["entity"]["id"]
    window = fx.create_standard_window(api)
    filing = fx.accepted_filing(
        api,
        entity_id,
        firm["plant"]["id"],
        window["id"],
        lines=[
            f.transaction_payload(
                head_count=100,
                avg_net_price_per_cwt=280.00,
                avg_carcass_weight_cwt=8.00,
            )
        ],
    )

    for round_number in (1, 2):
        fx.reopen_filing(api, filing["id"], f"restatement {round_number}")
        fx.resubmit_filing(api, entity_id, filing["id"])
        settled = fx.accept_filing(api, filing["id"])
        assert settled["resubmission_count"] == round_number, settled

    validate_error(
        api.open_correction(
            filing["id"],
            f.correction_payload(correction_reason="restatement 3"),
            u.COMPLIANCE_AUDITOR,
        ),
        ApiErrorId.ERR_RESUBMISSION_LIMIT_REACHED.value,
        409,
    )

    fx.set_clock(api, k.CORRECTION_DEADLINE_PLUS_ONE_SECOND)
    validate_error(
        api.open_correction(
            filing["id"],
            f.correction_payload(correction_reason="restatement 3, retried late"),
            u.COMPLIANCE_AUDITOR,
        ),
        ApiErrorId.ERR_CORRECTION_WINDOW_CLOSED.value,
        409,
    )

    resting = fx.read_submission(api, filing["id"])
    assert resting["status"] == SubmissionStatus.ACCEPTED.value, resting
    assert resting["resubmission_count"] == 2, resting
    assert_window_ledger(
        fx.read_window(api, window["id"]),
        total_head_reported=100,
        accepted_submission_count=1,
    )


def test_08_both_docket_notice_periods_are_inclusive_thirty_day_minimums(api):
    """Twenty-nine days fails on either anchor; thirty passes on both.

    A comment period ending 29 days after the proposal instant is refused and an
    effective date 29 days after the comment close is refused, while the proposal
    that allows exactly 30 days on both counts opens the docket -- so only one
    record exists after three attempts.

    PRD §3.9: "Two notice periods are enforced at proposal time, each of 30 days:
    `comment_period_end` must be at least 30 days after the logical clock at
    proposal, failing which the proposal is rejected with
    `ERR_COMMENT_PERIOD_TOO_SHORT`, and `effective_from` must be at least 30 days
    after `comment_period_end` so that the industry receives genuine notice,
    failing which the proposal is rejected with `ERR_EFFECTIVE_DATE_TOO_SOON`."

    Design: Corner/validations/comment_period_and_notice_minimums_rejected
    """
    validate_error(
        api.create_methodology_change(
            f.methodology_change_payload(
                change_code="MC-2026-A",
                comment_period_end="2026-08-30T00:00:00Z",
                effective_from="2026-10-31T00:00:00Z",
            ),
            u.PROGRAM_ADMIN,
        ),
        ApiErrorId.ERR_COMMENT_PERIOD_TOO_SHORT.value,
        422,
    )
    validate_error(
        api.create_methodology_change(
            f.methodology_change_payload(
                change_code="MC-2026-B",
                comment_period_end="2026-08-31T00:00:00Z",
                effective_from="2026-09-29T00:00:00Z",
            ),
            u.PROGRAM_ADMIN,
        ),
        ApiErrorId.ERR_EFFECTIVE_DATE_TOO_SOON.value,
        422,
    )

    docket = get_success_data(
        api.create_methodology_change(
            f.methodology_change_payload(
                change_code="MC-2026-C",
                comment_period_end="2026-08-31T00:00:00Z",
                effective_from="2026-09-30T00:00:00Z",
            ),
            u.PROGRAM_ADMIN,
        ),
        expected_status=201,
    )
    assert docket["status"] == MethodologyChangeStatus.COMMENT_OPEN.value, docket
    assert docket["comment_count"] == 0, docket
    assert docket["industry_notice_issued_at"] is None, docket
    assert docket["restated_report_count"] == 0, docket

    _dockets, meta = validate_paginated(api.list_methodology_changes(u.PROGRAM_ADMIN))
    assert meta["total_count"] == 1, meta


def test_09_a_docket_closes_only_on_time_and_adopts_only_over_a_response(api):
    """Two sibling dockets differing only in whether the public answered.

    Closing before the comment period ends is refused and then succeeds at exactly
    that instant, and the docket that drew no comment cannot be adopted while its
    sibling, which drew one, adopts and stamps its industry notice.

    PRD §3.9: "**A change may not be adopted over silence**: if `comment_count` is
    0, adoption is rejected with `ERR_NO_PUBLIC_COMMENTS`."

    Design: Corner/validations/comment_close_and_adoption_prerequisites_rejected
    """
    silent = fx.open_docket(
        api,
        change_code="MC-2026-S",
        affected_category=ReportCategory.LIVE_STEER_HEIFER.value,
        comment_period_end="2026-08-31T00:00:00Z",
        effective_from="2026-09-30T00:00:00Z",
    )
    answered = fx.open_docket(
        api,
        change_code="MC-2026-T",
        affected_category=ReportCategory.LIVE_COW_BULL.value,
        comment_period_end="2026-08-31T00:00:00Z",
        effective_from="2026-09-30T00:00:00Z",
    )
    comment = fx.add_comment(api, answered["id"])
    assert comment["methodology_change_id"] == answered["id"], comment

    validate_error(
        api.close_comment_period(silent["id"], u.PROGRAM_ADMIN),
        ApiErrorId.ERR_COMMENT_PERIOD_NOT_ENDED.value,
        409,
    )
    assert (
        fx.read_methodology_change(api, silent["id"])["status"]
        == MethodologyChangeStatus.COMMENT_OPEN.value
    )

    fx.set_clock(api, "2026-08-31T00:00:00Z")
    closed_silent = validate_success(
        api.close_comment_period(silent["id"], u.PROGRAM_ADMIN)
    )
    assert (
        closed_silent["status"] == MethodologyChangeStatus.COMMENT_CLOSED.value
    ), closed_silent

    validate_error(
        api.adopt_methodology_change(silent["id"], u.PROGRAM_ADMIN),
        ApiErrorId.ERR_NO_PUBLIC_COMMENTS.value,
        409,
    )
    assert (
        fx.read_methodology_change(api, silent["id"])["status"]
        == MethodologyChangeStatus.COMMENT_CLOSED.value
    )

    validate_success(api.close_comment_period(answered["id"], u.PROGRAM_ADMIN))
    adopted = validate_success(
        api.adopt_methodology_change(answered["id"], u.PROGRAM_ADMIN)
    )
    assert adopted["status"] == MethodologyChangeStatus.ADOPTED.value, adopted
    assert adopted["comment_count"] == 1, adopted
    assert_clock_stamp(
        adopted["industry_notice_issued_at"],
        "2026-08-31T00:00:00Z",
        "industry_notice_issued_at",
    )
    assert adopted["restated_report_count"] == 0, adopted

    _answered_comments, answered_meta = validate_paginated(
        api.list_public_comments(answered["id"], u.PROGRAM_ADMIN)
    )
    assert answered_meta["total_count"] == 1, answered_meta
    _silent_comments, silent_meta = validate_paginated(
        api.list_public_comments(silent["id"], u.PROGRAM_ADMIN)
    )
    assert silent_meta["total_count"] == 0, silent_meta


def test_10_an_unpaid_penalty_blocks_activation_and_payment_must_be_exact(api):
    """The one configuration where the amount is nothing but the base.

    Against a firm whose file is merely determined there is no governing
    registration, so neither the volume factor nor the suspension surcharge moves
    and the failure-to-register assessment is exactly its base. That outstanding
    balance blocks activation, one cent short of the balance is refused as a
    mismatch, the exact figure settles the row, a replayed payment hits the
    terminal guard, and activation then goes through.

    PRD §3.8: "The payer supplies `paid_amount_cents`, which must equal the
    assessment's `assessed_amount_cents` exactly; a partial or excess figure is
    rejected with `ERR_PAYMENT_AMOUNT_MISMATCH`."

    Design: Corner/validations/penalty_money_gates_and_activation_block_rejected
    """
    firm = fx.obligated_firm(api, legal_name="Alpha Packing", activate=False)
    entity_id = firm["entity"]["id"]
    registration_id = firm["registration"]["id"]

    assessment = fx.assess_penalty(
        api, entity_id, ViolationType.NON_REGISTRATION.value
    )
    assert_penalty_breakdown(
        assessment,
        base_amount_cents=1000000,
        repeat_index=0,
        day_tier_multiplier=1.00,
        repeat_multiplier=1.00,
        volume_factor=1.000,
        suspension_surcharge=1.00,
        assessed_amount_cents=1000000,
        points=8,
    )
    assert_penalty_ledger(
        fx.read_entity(api, entity_id),
        assessed_penalty_cents=1000000,
        paid_penalty_cents=0,
        outstanding_penalty_cents=1000000,
        delinquency_points=8,
    )

    validate_error(
        api.activate_registration(registration_id, u.PROGRAM_ADMIN),
        ApiErrorId.ERR_OUTSTANDING_PENALTY_BLOCKS_ACTIVATION.value,
        409,
    )
    assert (
        fx.read_registration(api, registration_id)["status"]
        == RegistrationStatus.DETERMINED.value
    )

    validate_error(
        api.pay_penalty_assessment(
            assessment["id"], f.payment_payload(999999), u.PENALTY_OFFICER
        ),
        ApiErrorId.ERR_PAYMENT_AMOUNT_MISMATCH.value,
        422,
    )
    still_open = fx.read_penalty(api, assessment["id"])
    assert still_open["status"] == "ASSESSED", still_open
    assert still_open["settled_at"] is None, still_open

    paid = fx.pay_penalty(api, assessment["id"], 1000000)
    assert paid["status"] == "PAID", paid
    assert paid["settled_at"] is not None, paid
    assert_penalty_ledger(
        fx.read_entity(api, entity_id),
        assessed_penalty_cents=1000000,
        paid_penalty_cents=1000000,
        outstanding_penalty_cents=0,
        delinquency_points=8,
    )

    validate_error(
        api.pay_penalty_assessment(
            assessment["id"], f.payment_payload(1000000), u.PENALTY_OFFICER
        ),
        ApiErrorId.ERR_PENALTY_ALREADY_SETTLED.value,
        409,
    )

    activated = validate_success(
        api.activate_registration(registration_id, u.PROGRAM_ADMIN)
    )
    assert activated["status"] == RegistrationStatus.ACTIVE.value, activated
    assert_registration_number_format(activated["registration_number"], 2026, 1)


def test_11_an_empty_filing_and_a_locked_window_both_refuse_the_filing(api):
    """The collection gates, sequenced so each is the only defect at its call.

    An empty draft is refused for having no line at all while the window is still
    collecting; the lock then succeeds at exactly the period end because a draft is
    not a filing awaiting review; a line may still be appended to that draft
    afterwards, but filing it is refused because the window has closed, and so is
    starting a fresh filing against it.

    PRD §3.5: "And the filing must not be empty: a `LIVE_ANIMAL` window requires at
    least one transaction line, a `BOXED_BEEF` or `WHOLESALE_CUTS` window at least
    one wholesale lot, failing which the attempt returns `ERR_EMPTY_SUBMISSION`."

    Design: Corner/validations/locked_window_and_empty_filing_rejected
    """
    firm = fx.firm_with_plants(
        api,
        [
            {"plant_code": "EST-101"},
            {
                "plant_code": "EST-102",
                "annual_head_history": dict(ZERO_HEAD_HISTORY),
            },
        ],
        legal_name="Alpha Packing",
    )
    entity_id = firm["entity"]["id"]
    reporter = u.reporter_agent(entity_id)
    window = fx.create_standard_window(api)
    filing = fx.draft_filing(api, entity_id, firm["plants"][0]["id"], window["id"])

    validate_error(
        api.submit_submission(filing["id"], reporter),
        ApiErrorId.ERR_EMPTY_SUBMISSION.value,
        409,
    )
    empty = fx.read_submission(api, filing["id"])
    assert empty["status"] == SubmissionStatus.DRAFT.value, empty
    assert empty["submitted_at"] is None, empty

    fx.set_clock(api, k.WINDOW_PERIOD_END)
    locked = validate_success(
        api.lock_reporting_window(window["id"], u.PROGRAM_ADMIN)
    )
    assert locked["status"] == ReportingWindowStatus.LOCKED.value, locked

    fx.add_transaction(
        api,
        entity_id,
        filing["id"],
        f.transaction_payload(
            head_count=100, avg_net_price_per_cwt=280.00, avg_carcass_weight_cwt=8.00
        ),
    )
    assert_submission_totals(
        fx.read_submission(api, filing["id"]),
        reported_head=100,
        reported_value_dollars=224000.00,
    )

    validate_error(
        api.submit_submission(filing["id"], reporter),
        ApiErrorId.ERR_WINDOW_NOT_OPEN.value,
        409,
    )
    assert (
        fx.read_submission(api, filing["id"])["status"]
        == SubmissionStatus.DRAFT.value
    )

    validate_error(
        api.create_submission(
            f.submission_payload(
                firm["plants"][1]["id"],
                window["id"],
                fx.window_version(api, window["id"]),
            ),
            reporter,
        ),
        ApiErrorId.ERR_WINDOW_NOT_OPEN.value,
        409,
    )
    _filings, meta = validate_paginated(api.list_submissions(u.PROGRAM_ADMIN))
    assert meta["total_count"] == 1, meta

    assert_window_ledger(
        fx.read_window(api, window["id"]),
        total_head_reported=0,
        accepted_submission_count=0,
    )


def test_12_each_state_guarded_record_reports_its_own_wrong_state_error(api):
    """Five live records, five wrong actions, five distinct error ids.

    A perfectly valid line posted to a filing that is already under review, a
    refiling of an accepted filing, a suspension of a draft determination, a
    finalization of a queued audit case and an adoption of an open docket are each
    refused by the guard belonging to that record's own machine, and the window
    ledger is exactly where it was before all five.

    PRD §3.5: "Any lifecycle action requested from a status that does not permit it
    — filing anything but a `DRAFT`, reviewing anything but a `SUBMITTED` or
    `RESUBMITTED` filing, reopening anything but an `ACCEPTED` filing, refiling
    anything but an `UNDER_CORRECTION` filing, or any action at all on a terminal
    filing — is rejected with `ERR_INVALID_SUBMISSION_STATE`."

    Design: Corner/validations/lifecycle_actions_from_wrong_non_terminal_state_rejected
    """
    firm = fx.firm_with_plants(
        api,
        [
            {"plant_code": "EST-101"},
            {
                "plant_code": "EST-102",
                "annual_head_history": dict(ZERO_HEAD_HISTORY),
            },
        ],
        legal_name="Alpha Packing",
    )
    entity_id = firm["entity"]["id"]
    reporter = u.reporter_agent(entity_id)
    window = fx.create_standard_window(api)

    under_review = fx.submitted_filing(
        api,
        entity_id,
        firm["plants"][0]["id"],
        window["id"],
        lines=[
            f.transaction_payload(
                head_count=100,
                avg_net_price_per_cwt=280.00,
                avg_carcass_weight_cwt=8.00,
            )
        ],
    )
    booked = fx.accepted_filing(
        api,
        entity_id,
        firm["plants"][1]["id"],
        window["id"],
        lines=[
            f.transaction_payload(
                head_count=50,
                avg_net_price_per_cwt=280.00,
                avg_carcass_weight_cwt=8.00,
            )
        ],
    )
    queued_case = get_success_data(
        api.create_audit_case(
            f.audit_case_payload(booked["id"]), u.COMPLIANCE_AUDITOR
        ),
        expected_status=201,
    )
    draft_file = fx.draft_registration(api, entity_id, determination_year=2027)
    open_docket = fx.open_docket(api)

    validate_error(
        api.add_transaction(
            under_review["id"],
            f.transaction_payload(
                head_count=25,
                avg_net_price_per_cwt=281.00,
                avg_carcass_weight_cwt=8.20,
            ),
            reporter,
        ),
        ApiErrorId.ERR_SUBMISSION_NOT_EDITABLE.value,
        409,
    )
    assert_submission_totals(
        fx.read_submission(api, under_review["id"]), reported_head=100
    )

    validate_error(
        api.resubmit_submission(booked["id"], reporter),
        ApiErrorId.ERR_INVALID_SUBMISSION_STATE.value,
        409,
    )
    assert (
        fx.read_submission(api, booked["id"])["status"]
        == SubmissionStatus.ACCEPTED.value
    )

    validate_error(
        api.suspend_registration(
            draft_file["id"],
            f.suspend_payload(suspended_reason=SuspendedReason.ADMIN_ACTION.value),
            u.PROGRAM_ADMIN,
        ),
        ApiErrorId.ERR_INVALID_REGISTRATION_STATE.value,
        409,
    )
    resting_file = fx.read_registration(api, draft_file["id"])
    assert resting_file["status"] == RegistrationStatus.DRAFT.value, resting_file
    assert resting_file["suspended_reason"] is None, resting_file

    validate_error(
        api.finalize_audit_case(
            queued_case["id"],
            f.finalize_audit_payload(50, 112000.00),
            u.COMPLIANCE_AUDITOR_2,
        ),
        ApiErrorId.ERR_INVALID_AUDIT_STATE.value,
        409,
    )
    resting_case = fx.read_case(api, queued_case["id"])
    assert resting_case["status"] == AuditCaseStatus.OPEN.value, resting_case
    assert resting_case["verified_head"] is None, resting_case
    assert resting_case["finalized_by_user_id"] is None, resting_case

    validate_error(
        api.adopt_methodology_change(open_docket["id"], u.PROGRAM_ADMIN),
        ApiErrorId.ERR_INVALID_METHODOLOGY_STATE.value,
        409,
    )
    assert (
        fx.read_methodology_change(api, open_docket["id"])["status"]
        == MethodologyChangeStatus.COMMENT_OPEN.value
    )

    assert_window_ledger(
        fx.read_window(api, window["id"]),
        total_head_reported=50,
        accepted_submission_count=1,
    )
