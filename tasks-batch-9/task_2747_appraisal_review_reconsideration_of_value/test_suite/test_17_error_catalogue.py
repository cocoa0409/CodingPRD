"""
The error catalogue: which code fires, at which status, and what it leaves behind.

These cases probe the refusal side of the contract. Each one drives a single violation and
then shows the same request accepted once the violation is removed, so the code being observed
is pinned to the rule under test rather than to the shape of the request. Every refusal is also
checked for having written nothing.
"""

from test_helpers import (
    CHIEF_APPRAISER_HEADERS,
    COMPLIANCE_HEADERS,
    DESK_REVIEWER_HEADERS,
    LOAN_OFFICER_HEADERS,
    NO_HEADERS,
    ApiErrorId,
    assert_instant,
    factories as f,
    fixtures as fx,
    make_amc_headers,
    make_appraiser_headers,
    make_borrower_headers,
    make_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

UNKNOWN_LOAN_FILE_ID = "00000000-0000-4000-8000-000000000001"
UNKNOWN_PANEL_MEMBERSHIP_ID = "00000000-0000-4000-8000-000000000002"
UNKNOWN_BIAS_FLAG_ID = "00000000-0000-4000-8000-000000000003"
UNKNOWN_DESK_REVIEW_ID = "00000000-0000-4000-8000-000000000004"
UNKNOWN_ESCALATION_ORDER_ID = "00000000-0000-4000-8000-000000000005"
UNKNOWN_ROV_REQUEST_ID = "00000000-0000-4000-8000-000000000006"
UNKNOWN_DISPUTE_CASE_ID = "00000000-0000-4000-8000-000000000007"

CLEAN_GRID = [
    {
        "street_address": "1 Alder Street",
        "sale_price_cents": 39000000,
        "gross_adjustment_cents": 390000,
        "net_adjustment_cents": 390000,
        "distance_miles": 1.0,
        "sale_date": "2026-05-01T00:00:00Z",
    },
    {
        "street_address": "2 Alder Street",
        "sale_price_cents": 40000000,
        "gross_adjustment_cents": 400000,
        "net_adjustment_cents": 0,
        "distance_miles": 1.5,
        "sale_date": "2026-06-01T00:00:00Z",
    },
    {
        "street_address": "3 Alder Street",
        "sale_price_cents": 41000000,
        "gross_adjustment_cents": 410000,
        "net_adjustment_cents": -410000,
        "distance_miles": 2.0,
        "sale_date": "2026-06-15T00:00:00Z",
    },
]


def _author(license_number, full_name="Alice Author"):
    return {
        "full_name": full_name,
        "license_number": license_number,
        "license_state": "CA",
    }


def _grid():
    return [dict(row) for row in CLEAN_GRID]


def test_a_request_carrying_no_identity_headers_is_unauthenticated(api):
    """Reads are not exempt from the identity requirement.

    The very same read succeeds once the two headers are supplied, which proves the identifier
    in the path was never the problem, and the refusal arrives in the standard error envelope.

    PRD: "Every request to every endpoint — reads included — must carry two headers:
    `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming the role that
    principal is acting in. If either header is absent or empty, the request is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/errors/error_unauthenticated_missing_headers_and_unknown_role_rejected
    """
    loan = fx.create_loan_file(
        api, loan_number="LN-2747-C701", borrower_display_name="Bea Borrower"
    )

    refused = api.get_loan_file(loan["id"], NO_HEADERS)
    error = validate_error(refused, ApiErrorId.ERR_UNAUTHENTICATED, 401)
    assert error["message"]
    assert refused.json()["response_type"] == "error"

    allowed = validate_success(api.get_loan_file(loan["id"], LOAN_OFFICER_HEADERS))
    assert allowed["loan_number"] == "LN-2747-C701"


def test_an_undeclared_role_is_unauthenticated_rather_than_forbidden(api):
    """An unrecognised role name fails authentication before any permission lookup.

    The role offered is not one of the seven the system declares, so the answer is the 401 of
    authentication rather than the 403 of authorisation.

    PRD: "The same `ERR_UNAUTHENTICATED` and the same 401 status are returned when
    `X-User-Role` carries a string that is not one of the seven roles declared below — an
    unrecognised role is treated as a failure to authenticate, never as a permission problem."

    Design: Corner/errors/error_unauthenticated_missing_headers_and_unknown_role_rejected
    """
    loan = fx.create_loan_file(
        api, loan_number="LN-2747-C701", borrower_display_name="Bea Borrower"
    )

    refused = api.get_loan_file(
        loan["id"], make_headers("ghost_user_1", "PortfolioAnalyst")
    )
    error = validate_error(refused, ApiErrorId.ERR_UNAUTHENTICATED, 401)
    assert error["message"]


def test_every_path_addressable_type_reports_its_own_not_found_code(api):
    """Each type in a path position answers with the code named for that type.

    The adjudication probe is the interesting one: the flag identifier is resolved before the
    flag's own state is considered, so an unknown flag reports a not-found rather than a state
    error.

    PRD: "Every resource named in a path position exists, checked left to right — otherwise
    that type's own not-found code (404)."

    Design: Corner/errors/error_not_found_codes_for_every_path_addressable_entity
    """
    fx.create_amc(api, name="Not Found Probe AMC")

    probes = [
        (
            api.get_loan_file(UNKNOWN_LOAN_FILE_ID, LOAN_OFFICER_HEADERS),
            ApiErrorId.ERR_LOAN_FILE_NOT_FOUND,
        ),
        (
            api.get_panel_membership(
                UNKNOWN_PANEL_MEMBERSHIP_ID, CHIEF_APPRAISER_HEADERS
            ),
            ApiErrorId.ERR_PANEL_MEMBERSHIP_NOT_FOUND,
        ),
        (
            api.adjudicate_bias_flag(
                UNKNOWN_BIAS_FLAG_ID,
                f.adjudicate_payload("CLEAR", rationale="Probe."),
                COMPLIANCE_HEADERS,
            ),
            ApiErrorId.ERR_BIAS_FLAG_NOT_FOUND,
        ),
        (
            api.get_desk_review(UNKNOWN_DESK_REVIEW_ID, DESK_REVIEWER_HEADERS),
            ApiErrorId.ERR_DESK_REVIEW_NOT_FOUND,
        ),
        (
            api.get_escalation_order(
                UNKNOWN_ESCALATION_ORDER_ID, CHIEF_APPRAISER_HEADERS
            ),
            ApiErrorId.ERR_ESCALATION_ORDER_NOT_FOUND,
        ),
        (
            api.get_rov_request(UNKNOWN_ROV_REQUEST_ID, DESK_REVIEWER_HEADERS),
            ApiErrorId.ERR_ROV_REQUEST_NOT_FOUND,
        ),
        (
            api.get_dispute_case(UNKNOWN_DISPUTE_CASE_ID, CHIEF_APPRAISER_HEADERS),
            ApiErrorId.ERR_DISPUTE_CASE_NOT_FOUND,
        ),
    ]

    for response, expected in probes:
        error = validate_error(response, expected, 404)
        assert response.json()["response_type"] == "error"
        assert error["message"]


def _one_delivered_report(api, suffix, borrower, amc_name, **appraisal):
    env = fx.panel_and_loan(
        api,
        amc={"name": amc_name},
        appraiser=_author("CA-AL-C%s" % suffix),
        loan={
            "loan_number": "LN-2747-C%s" % suffix,
            "borrower_display_name": borrower,
        },
    )
    env["appraisal"] = fx.deliver_appraisal(
        api, env["loan"]["id"], env["appraiser"]["id"], env["amc"]["id"], **appraisal
    )
    return env


def test_pagination_bounds_are_rejected_before_any_page_is_built(api):
    """A limit outside the range or a negative offset is a request error, not an empty page.

    All three probes go to a listing that does hold a row, so what comes back is the error
    envelope rather than any part of a page.

    PRD: "`limit` defaults to 10 when omitted, must be an integer, and must fall in the
    inclusive range from a minimum of 1 to a maximum of 100. `offset` defaults to 0 when
    omitted, must be an integer, and must be zero or greater. A `limit` outside that range, a
    negative `offset`, or a non-integer value for either is rejected with
    `ERR_INVALID_PAGINATION` (HTTP 400)."

    Design: Corner/errors/error_invalid_pagination_bounds_rejected_on_a_list_read
    """
    _one_delivered_report(api, "702", "Cal Borrower", "Pagination AMC")

    for params in ({"limit": 0}, {"limit": 101}, {"limit": 10, "offset": -1}):
        response = api.list_appraisals(DESK_REVIEWER_HEADERS, params)
        validate_error(response, ApiErrorId.ERR_INVALID_PAGINATION, 400)
        assert "data" in response.json()
        assert not isinstance(response.json()["data"], list)


def test_the_extreme_but_legal_page_is_served(api):
    """The upper bound of the limit range and the lower bound of the offset are both inside.

    A limit of exactly 100 with an offset of exactly 0 is legal, and the single delivered report
    comes back with the page metadata reporting no further pages.

    PRD: "`limit` defaults to 10 when omitted, must be an integer, and must fall in the
    inclusive range from a minimum of 1 to a maximum of 100. `offset` defaults to 0 when
    omitted, must be an integer, and must be zero or greater."

    Design: Corner/errors/error_invalid_pagination_bounds_rejected_on_a_list_read
    """
    env = _one_delivered_report(api, "702", "Cal Borrower", "Pagination AMC")

    rows, meta = validate_paginated(
        api.list_appraisals(DESK_REVIEWER_HEADERS, {"limit": 100, "offset": 0})
    )
    assert meta["total_count"] == 1
    assert meta["limit"] == 100
    assert meta["offset"] == 0
    assert meta["has_more"] is False
    assert [row["id"] for row in rows] == [env["appraisal"]["id"]]


def _rov_answered_once(api, outcome, **response_fields):
    """A routed reconsideration that the authoring appraiser has already answered."""
    env = _one_delivered_report(api, "703", "Dot Borrower", "ROV Gate AMC")
    fx.add_comparables(api, env["appraisal"]["id"], env["amc"]["id"], _grid())
    env["appraisal"] = fx.run_rule_checks(api, env["appraisal"]["id"])
    env = fx.rov_awaiting_appraiser(api, env, requested_value_cents=40600000)
    env["rov"] = fx.rov_respond(
        api, env["rov"]["id"], env["appraiser"]["id"], outcome, **response_fields
    )
    return env


def test_an_affirmation_closes_the_reconsideration_on_the_original_value(api):
    """Affirming answers the borrower without moving the value.

    The request comes to rest in the answered state and the contested appraisal returns to the
    accepted side of the review dimension carrying the value it was delivered with.

    PRD: "Either way the request moves `AWAITING_APPRAISER → RESPONDED`,
    `appraiser_responded_at` is stamped from the logical clock, and `responded_late` is set true
    when that instant is past `response_deadline_at` for the current round and false otherwise."

    PRD: "Affirming the value moves the appraisal `VALUE_CONTESTED → VALUE_ACCEPTED`"

    Design: Corner/errors/error_rov_not_awaiting_response_on_a_second_appraiser_answer_rejected
    """
    env = _rov_answered_once(
        api, "VALUE_AFFIRMED",
        response_note="The grid already reflects those sales.",
    )

    assert env["rov"]["status"] == "RESPONDED"
    assert env["rov"]["outcome"] == "VALUE_AFFIRMED"
    assert env["rov"]["revised_value_cents"] is None
    assert env["rov"]["responded_late"] is False
    appraisal = fx.read_appraisal(api, env["appraisal"]["id"])
    assert appraisal["review_status"] == "VALUE_ACCEPTED"
    assert appraisal["current_value_cents"] == 40000000


def test_a_second_answer_to_the_same_reconsideration_is_refused(api):
    """Once answered, the reconsideration is no longer awaiting a response.

    The appraiser changes their mind and tries to revise instead. The refusal carries the
    channel's own conflict code rather than the generic state error, and nothing the revision
    would have written appears: no value movement, no revision row, and no dent in the
    appraiser's standing.

    PRD: "The request must be in `AWAITING_APPRAISER`, or the response is refused with
    `ERR_ROV_NOT_AWAITING_RESPONSE` (HTTP 409)."

    Design: Corner/errors/error_rov_not_awaiting_response_on_a_second_appraiser_answer_rejected
    """
    env = _rov_answered_once(
        api, "VALUE_AFFIRMED",
        response_note="The grid already reflects those sales.",
    )

    response = api.rov_appraiser_response(
        env["rov"]["id"],
        f.rov_response_payload(
            "VALUE_REVISED",
            response_note="Reconsidered after all.",
            revised_value_cents=40600000,
        ),
        make_appraiser_headers(env["appraiser"]["id"]),
    )
    validate_error(response, ApiErrorId.ERR_ROV_NOT_AWAITING_RESPONSE, 409)

    rov = fx.read_rov_request(api, env["rov"]["id"])
    assert rov["status"] == "RESPONDED"
    assert rov["outcome"] == "VALUE_AFFIRMED"
    assert rov["revised_value_cents"] is None
    appraisal = fx.read_appraisal(api, env["appraisal"]["id"])
    assert appraisal["current_value_cents"] == 40000000
    assert fx.list_value_revisions(api, env["appraisal"]["id"]) == []
    assert fx.read_appraiser(api, env["appraiser"]["id"])["revision_rate_bps"] == 0


def _returned_then_superseded(api):
    """A report thrown back to the company and then replaced by a fresh delivery.

    A message is filed against the first report while it is still live, so the trail can be
    inspected after supersession.
    """
    env = _one_delivered_report(api, "704", "Eve Borrower", "Comms Lock AMC")
    fx.add_comparables(api, env["appraisal"]["id"], env["amc"]["id"], _grid())
    env["first_message"] = fx.send_communication(
        api, env["appraisal"]["id"], "APPRAISER", "ORDER_STATUS",
        body_text="Report received, thank you.",
    )
    fx.run_rule_checks(api, env["appraisal"]["id"])
    fx.run_bias_screen(api, env["appraisal"]["id"])
    review = fx.open_desk_review(api, env["appraisal"]["id"])
    fx.submit_desk_review(api, review["id"], findings_note="Grid needs work.")
    fx.decide_desk_review(
        api, review["id"], "RETURN", decision_note="Back to the company."
    )
    env["replacement"] = fx.deliver_appraisal(
        api, env["loan"]["id"], env["appraiser"]["id"], env["amc"]["id"],
        effective_date="2026-07-20T00:00:00Z",
        reported_value_cents=40200000,
        supersedes_appraisal_id=env["appraisal"]["id"],
    )
    return env


def test_a_superseded_report_stops_accepting_communications(api):
    """The retired report's audit trail is closed along with the report.

    The replacement delivery retires its predecessor, and a further message against that
    predecessor is refused. The trail it already carries is untouched — and since a
    communication has no version and no update endpoint, the existing entry cannot be edited
    either.

    PRD: "Beyond the intent restrictions of §2.10, one state guard applies: an appraisal stops
    accepting communications once its `review_status` is `SUPERSEDED` or `QUARANTINED`, and an
    attempt to record one against such a report is refused with `ERR_COMMUNICATION_LOCKED`
    (HTTP 409)."

    PRD: "Communication records are append-only events carrying only `id` and `created_at`,
    with no `updated_at` and no `version`."

    Design: Corner/errors/error_communication_locked_on_a_superseded_appraisal_rejected
    """
    env = _returned_then_superseded(api)
    assert fx.read_appraisal(api, env["appraisal"]["id"])["review_status"] == "SUPERSEDED"

    response = api.create_communication(
        env["appraisal"]["id"],
        f.communication_payload(
            "APPRAISER", "REPORT_CLARIFICATION",
            "One more question on the retired report.",
        ),
        DESK_REVIEWER_HEADERS,
    )
    validate_error(response, ApiErrorId.ERR_COMMUNICATION_LOCKED, 409)

    rows, meta = validate_paginated(
        api.list_communications(env["appraisal"]["id"], DESK_REVIEWER_HEADERS)
    )
    assert meta["total_count"] == 1
    assert [row["id"] for row in rows] == [env["first_message"]["id"]]
    assert "version" not in rows[0]


def test_the_replacement_report_accepts_the_message_the_retired_one_refused(api):
    """The lock is a property of the report, not of the message.

    The identical body addressed to the live replacement is recorded, stamped from the logical
    clock and attributed to the acting reviewer.

    PRD: "Any of `AppraisalDeskReviewer`, `ChiefAppraiser`, `AMCCoordinator`, `LoanOfficer`, or
    `Borrower` may record a message against an appraisal, supplying the `recipient`, the
    `intent`, and the `body`; the server stamps `sent_at` from the logical clock and records
    `sender_role` and `sender_user_id` from the request headers."

    Design: Corner/errors/error_communication_locked_on_a_superseded_appraisal_rejected
    """
    env = _returned_then_superseded(api)

    recorded = validate_success(
        api.create_communication(
            env["replacement"]["id"],
            f.communication_payload(
                "APPRAISER", "REPORT_CLARIFICATION",
                "One more question on the retired report.",
            ),
            DESK_REVIEWER_HEADERS,
        ),
        201,
    )

    assert recorded["sender_role"] == "AppraisalDeskReviewer"
    assert recorded["sender_user_id"] == "desk_user_1"
    assert_instant(recorded["sent_at"], "2026-08-01T00:00:00Z", "sent_at")
    assert "version" not in recorded


PROHIBITED_BODY = "The file needs 41,000,000 to work."


def test_prohibited_sender_and_intent_pairs_are_refused(api):
    """Three separate prohibitions, one code.

    A loan officer and a borrower are barred from three intents toward the appraiser; the desk
    reviewer is barred from one. None of the three attempts leaves a row behind.

    PRD: "Three prohibitions apply, and any one of them rejects the message with
    `ERR_INDEPENDENCE_VIOLATION` (HTTP 422). A `LoanOfficer` or a `Borrower` may never address
    the appraiser with any of `VALUE_INFLUENCE`, `COMPARABLE_SUGGESTION`, or
    `DEADLINE_PRESSURE` — that is, when `recipient` is `APPRAISER` and `intent` is any of those
    three. An `AppraisalDeskReviewer` may never address the appraiser with `VALUE_INFLUENCE`,
    though the reviewer's other intents toward the appraiser are permitted."

    Design: Corner/errors/error_independence_violation_by_sender_role_and_intent_pair_rejected
    """
    env = _one_delivered_report(api, "705", "Fay Borrower", "Independence AMC")
    attempts = [
        ("VALUE_INFLUENCE", LOAN_OFFICER_HEADERS),
        ("DEADLINE_PRESSURE", make_borrower_headers(env["loan"]["id"])),
        ("VALUE_INFLUENCE", DESK_REVIEWER_HEADERS),
    ]

    for intent, headers in attempts:
        response = api.create_communication(
            env["appraisal"]["id"],
            f.communication_payload("APPRAISER", intent, PROHIBITED_BODY),
            headers,
        )
        validate_error(response, ApiErrorId.ERR_INDEPENDENCE_VIOLATION, 422)

    _, meta = validate_paginated(
        api.list_communications(env["appraisal"]["id"], DESK_REVIEWER_HEADERS)
    )
    assert meta["total_count"] == 0


def test_the_screen_reads_the_declared_intent_and_the_recipient(api):
    """The identical text is admitted whenever the declared pair is permitted.

    The loan officer's own words go through under a permitted intent, the desk reviewer may
    suggest a comparable, and even value influence is admitted when it is aimed at the lender's
    own desk rather than at the appraiser.

    PRD: "A `LoanOfficer` or a `Borrower` may never address the appraiser with any of
    `VALUE_INFLUENCE`, `COMPARABLE_SUGGESTION`, or `DEADLINE_PRESSURE` — that is, when
    `recipient` is `APPRAISER` and `intent` is any of those three. An `AppraisalDeskReviewer`
    may never address the appraiser with `VALUE_INFLUENCE`, though the reviewer's other intents
    toward the appraiser are permitted."

    Design: Corner/errors/error_independence_violation_by_sender_role_and_intent_pair_rejected
    """
    env = _one_delivered_report(api, "705", "Fay Borrower", "Independence AMC")
    admitted = [
        ("APPRAISER", "ORDER_STATUS", PROHIBITED_BODY, LOAN_OFFICER_HEADERS),
        (
            "APPRAISER", "COMPARABLE_SUGGESTION",
            "Consider 12 Birch Lane as an additional sale.", DESK_REVIEWER_HEADERS,
        ),
        ("LENDER_DESK", "VALUE_INFLUENCE", PROHIBITED_BODY, LOAN_OFFICER_HEADERS),
    ]

    created = []
    for recipient, intent, body_text, headers in admitted:
        created.append(
            validate_success(
                api.create_communication(
                    env["appraisal"]["id"],
                    f.communication_payload(recipient, intent, body_text),
                    headers,
                ),
                201,
            )
        )

    assert [row["intent"] for row in created] == [
        "ORDER_STATUS", "COMPARABLE_SUGGESTION", "VALUE_INFLUENCE",
    ]
    rows, meta = validate_paginated(
        api.list_communications(env["appraisal"]["id"], DESK_REVIEWER_HEADERS)
    )
    assert meta["total_count"] == 3
    assert [row["id"] for row in rows] == [row["id"] for row in created]


def _two_submitted_reviews(api):
    """Two reports on one panel whose submitted reviews resolve opposite requirements.

    The first is a complete report on a standard-risk loan; the second carries a single exhibit
    against a high-risk loan, which is what pulls its final quality score under the high-tier
    field-review cut-off.
    """
    amc = fx.create_amc(api, name="Escalation Gate AMC")
    author = fx.create_appraiser(api, **_author("CA-AL-C707"))
    fx.enroll_on_panel(api, author["id"], amc["id"])

    built = []
    for suffix, borrower, risk_tier, appraisal_fields, note in (
        ("A", "Hal Borrower", "STANDARD", {}, "Clean report."),
        ("B", "Ida Borrower", "HIGH", {"exhibit_count": 1}, "Exhibits are thin."),
    ):
        loan = fx.create_loan_file(
            api,
            loan_number="LN-2747-C707%s" % suffix,
            risk_tier=risk_tier,
            borrower_display_name=borrower,
        )
        appraisal = fx.deliver_appraisal(
            api, loan["id"], author["id"], amc["id"], **appraisal_fields
        )
        fx.add_comparables(api, appraisal["id"], amc["id"], _grid())
        fx.run_rule_checks(api, appraisal["id"])
        fx.run_bias_screen(api, appraisal["id"])
        review = fx.open_desk_review(api, appraisal["id"])
        built.append(
            {
                "loan": loan,
                "appraisal": appraisal,
                "review": fx.submit_desk_review(api, review["id"], findings_note=note),
            }
        )
    return built


def test_the_two_submitted_reviews_resolve_opposite_requirements(api):
    """The risk-tier matrix is read with strictly-less-than comparisons.

    The complete report scores a perfect ten thousand on a standard-risk loan, which is not
    below that row's single cut-off, so nothing is required. The thin-exhibit report on a
    high-risk loan lands below the field-review cut-off but not below the second-appraisal one.

    PRD: "On a `HIGH` tier loan, a final score below 7000 basis points requires
    `SECOND_APPRAISAL`; otherwise a score below 8500 requires `FIELD_REVIEW`; otherwise `NONE`."

    PRD: "On a `STANDARD` tier loan, below 6000 requires `FIELD_REVIEW`, and otherwise `NONE`."

    Design: Corner/errors/error_escalation_required_in_both_directions_rejected
    """
    clean, thin = _two_submitted_reviews(api)

    assert clean["review"]["final_quality_score_bps"] == 10000
    assert clean["review"]["required_escalation"] == "NONE"
    assert thin["review"]["final_quality_score_bps"] == 8086
    assert thin["review"]["required_escalation"] == "FIELD_REVIEW"


def test_escalating_a_review_that_requires_nothing_is_refused(api):
    """`ESCALATE` is available only when the matrix asked for something.

    The review stays where submission left it and no order is manufactured.

    PRD: "The action must agree with the resolved requirement: `ACCEPT` is permitted only when
    `required_escalation` is `NONE`, and `ESCALATE` only when it is anything other than `NONE`;
    either mismatch is refused with `ERR_ESCALATION_REQUIRED` (HTTP 422)."

    Design: Corner/errors/error_escalation_required_in_both_directions_rejected
    """
    clean, _ = _two_submitted_reviews(api)

    response = api.decide_desk_review(
        clean["review"]["id"],
        f.desk_review_decide_payload(
            "ESCALATE", decision_note="Escalating a review that needs nothing."
        ),
        CHIEF_APPRAISER_HEADERS,
    )
    validate_error(response, ApiErrorId.ERR_ESCALATION_REQUIRED, 422)

    assert fx.read_desk_review(api, clean["review"]["id"])["status"] == "SUBMITTED"
    _, meta = validate_paginated(
        api.list_escalation_orders(
            CHIEF_APPRAISER_HEADERS, {"desk_review_id": clean["review"]["id"]}
        )
    )
    assert meta["total_count"] == 0


def test_accepting_a_review_that_requires_a_field_review_is_refused(api):
    """`ACCEPT` is the mirror-image mismatch and carries the same code.

    Nothing about the value of record moves: the loan's pointer is still empty.

    PRD: "The action must agree with the resolved requirement: `ACCEPT` is permitted only when
    `required_escalation` is `NONE`, and `ESCALATE` only when it is anything other than `NONE`;
    either mismatch is refused with `ERR_ESCALATION_REQUIRED` (HTTP 422)."

    Design: Corner/errors/error_escalation_required_in_both_directions_rejected
    """
    _, thin = _two_submitted_reviews(api)

    response = api.decide_desk_review(
        thin["review"]["id"],
        f.desk_review_decide_payload(
            "ACCEPT", decision_note="Accepting a review that needs a field review."
        ),
        CHIEF_APPRAISER_HEADERS,
    )
    validate_error(response, ApiErrorId.ERR_ESCALATION_REQUIRED, 422)

    assert fx.read_desk_review(api, thin["review"]["id"])["status"] == "SUBMITTED"
    assert fx.read_loan_file(api, thin["loan"]["id"])["value_of_record_appraisal_id"] is None


def test_each_review_admits_the_action_its_requirement_names(api):
    """Swap the two actions around and both decisions land.

    The clean review becomes the value of record with the loan's ratio and impact recomputed;
    the thin review is escalated and exactly one order is created, typed from the requirement
    the matrix resolved.

    PRD: "The loan file's `value_of_record_appraisal_id` is pointed at this appraisal, its
    `collateral_status` moves `UNDER_REVIEW → VALUE_ACCEPTED`, and
    `current_appraised_value_cents`, `effective_value_cents`, `ltv_bps`, and `decision_impact`
    are all recomputed as described in §3.9, with the underwriting cascade following from the
    resulting impact tier."

    PRD: "`ESCALATE` moves the review `SUBMITTED → ESCALATED` and the appraisal
    `IN_DESK_REVIEW → ESCALATED`, and it creates an escalation order in `PENDING_ASSIGNMENT`
    whose `escalation_type` is copied from `required_escalation` and whose `due_at` is stamped
    as described in §3.7."

    Design: Corner/errors/error_escalation_required_in_both_directions_rejected
    """
    clean, thin = _two_submitted_reviews(api)

    accepted = fx.decide_desk_review(api, clean["review"]["id"], "ACCEPT",
                                     decision_note="Clean report accepted.")
    assert accepted["status"] == "ACCEPTED"
    loan = fx.read_loan_file(api, clean["loan"]["id"])
    assert loan["value_of_record_appraisal_id"] == clean["appraisal"]["id"]
    assert loan["ltv_bps"] == 7500
    assert loan["decision_impact"] == "NO_IMPACT"

    escalated = fx.decide_desk_review(api, thin["review"]["id"], "ESCALATE",
                                      decision_note="Field review ordered.")
    assert escalated["status"] == "ESCALATED"
    rows, meta = validate_paginated(
        api.list_escalation_orders(
            CHIEF_APPRAISER_HEADERS, {"desk_review_id": thin["review"]["id"]}
        )
    )
    assert meta["total_count"] == 1
    assert rows[0]["status"] == "PENDING_ASSIGNMENT"
    assert rows[0]["escalation_type"] == "FIELD_REVIEW"


def _order_with_an_outsider_candidate(api):
    """A field-review order plus two candidates: one on the company's panel and one not.

    The outsider is in perfect standing and approved for review work — with the wrong company.
    """
    first = fx.create_amc(api, name="Panel Scope AMC One")
    second = fx.create_amc(api, name="Panel Scope AMC Two")
    author = fx.create_appraiser(api, **_author("CA-AL-C708"))
    insider = fx.create_appraiser(api, **_author("CA-BR-C708", "Bruno Backup"))
    outsider = fx.create_appraiser(api, **_author("CA-CL-C708", "Cleo Outsider"))
    fx.enroll_on_panel(api, author["id"], first["id"])
    fx.enroll_on_panel(api, insider["id"], first["id"], tier="REVIEW_SPECIALIST")
    outside_membership = fx.enroll_on_panel(
        api, outsider["id"], second["id"], tier="REVIEW_SPECIALIST"
    )

    loan = fx.create_loan_file(
        api, loan_number="LN-2747-C708", risk_tier="HIGH",
        borrower_display_name="Jan Borrower",
    )
    appraisal = fx.deliver_appraisal(
        api, loan["id"], author["id"], first["id"], exhibit_count=1
    )
    fx.add_comparables(api, appraisal["id"], first["id"], _grid())
    fx.run_rule_checks(api, appraisal["id"])
    fx.run_bias_screen(api, appraisal["id"])
    review = fx.open_desk_review(api, appraisal["id"])
    fx.submit_desk_review(api, review["id"], findings_note="Exhibits are thin.")
    fx.decide_desk_review(api, review["id"], "ESCALATE",
                          decision_note="Field review ordered.")
    return {
        "amc": first,
        "insider": insider,
        "outsider": outsider,
        "outside_membership": outside_membership,
        "order": fx.escalation_order_for(api, review["id"]),
    }


def test_a_candidate_on_the_wrong_company_panel_is_refused(api):
    """Panel membership is scoped to the escalated report's company.

    The candidate is active and enrolled — just with a different company — so the refusal names
    the panel rung rather than the standing rung that follows it. Nothing is written: the order
    keeps its null cost, the candidate takes on no work, and the company's ledger stays empty.

    PRD: "The candidate must hold an `ACTIVE` panel membership with the escalated appraisal's
    management company, or the request is refused with `ERR_APPRAISER_NOT_ON_PANEL`."

    Design: Corner/errors/error_appraiser_not_on_panel_for_this_amc_on_assign_rejected
    """
    env = _order_with_an_outsider_candidate(api)
    assert env["outside_membership"]["status"] == "ACTIVE"
    assert fx.read_appraiser(api, env["outsider"]["id"])["panel_status"] == "ACTIVE"

    response = api.assign_escalation_order(
        env["order"]["id"],
        f.assign_payload(
            env["outsider"]["id"], "2026-08-02T09:00:00Z", "2026-08-02T12:00:00Z"
        ),
        CHIEF_APPRAISER_HEADERS,
    )
    validate_error(response, ApiErrorId.ERR_APPRAISER_NOT_ON_PANEL, 422)

    order = fx.read_escalation_order(api, env["order"]["id"])
    assert order["status"] == "PENDING_ASSIGNMENT"
    assert order["total_cost_cents"] is None
    assert fx.read_appraiser(api, env["outsider"]["id"])["open_assignment_count"] == 0
    assert fx.read_amc(api, env["amc"]["id"])["ytd_escalation_spend_cents"] == 0


def test_the_same_order_is_staffed_from_the_right_panel(api):
    """The candidate enrolled with the escalated report's own company is accepted.

    Pricing then runs and the money fields appear for the first time, which is what distinguishes
    an accepted assignment from a refused one.

    PRD: "A successful assignment writes all four cost fields, adds `total_cost_cents` to the
    management company's `ytd_escalation_spend_cents`, increments the assignee's
    `open_assignment_count`, and reserves the inspection window on that appraiser so it
    participates in future conflict checks."

    Design: Corner/errors/error_appraiser_not_on_panel_for_this_amc_on_assign_rejected
    """
    env = _order_with_an_outsider_candidate(api)

    assigned = validate_success(
        api.assign_escalation_order(
            env["order"]["id"],
            f.assign_payload(
                env["insider"]["id"], "2026-08-02T09:00:00Z", "2026-08-02T12:00:00Z"
            ),
            CHIEF_APPRAISER_HEADERS,
        )
    )

    assert assigned["status"] == "ASSIGNED"
    assert assigned["assigned_appraiser_id"] == env["insider"]["id"]
    assert assigned["base_fee_cents"] == 45000
    assert assigned["total_cost_cents"] == 45000
    assert fx.read_appraiser(api, env["insider"]["id"])["open_assignment_count"] == 1


def _report_with_one_dispute(api):
    env = _one_delivered_report(api, "709", "Kim Borrower", "Dispute Basis AMC")
    env["dispute"] = fx.file_dispute(
        api, env["appraisal"]["id"], env["amc"]["id"], env["appraiser"]["id"],
        dispute_basis="COMP_SELECTION",
        slot_start="2026-08-03T09:00:00Z", slot_end="2026-08-03T11:00:00Z",
    )
    return env


def test_a_second_unresolved_dispute_on_the_same_basis_is_refused(api):
    """One unresolved dispute per appraisal and basis, whatever the slot says.

    The second filing asks for a slot on a different day, so it overlaps nothing and the
    company's capacity of two is nowhere near reached — the refusal is about the basis alone. The
    first dispute's deadline is the snapshot of its creation instant plus the company's default
    response allowance.

    PRD: "At most one non-resolved dispute may exist for any one combination of appraisal and
    basis, and a second is refused with `ERR_DUPLICATE_DISPUTE_BASIS` (HTTP 422) — the same
    appraisal may perfectly well carry simultaneous open disputes on two *different* bases."

    PRD: "Its `response_deadline_at` is snapshotted at creation as the dispute's `created_at`
    plus the company's `sla_response_hours` — a snapshot, so a later change to the company's SLA
    parameter does not move an existing dispute's deadline."

    Design: Corner/errors/error_duplicate_dispute_basis_on_the_same_appraisal_rejected
    """
    env = _report_with_one_dispute(api)
    assert_instant(
        env["dispute"]["response_deadline_at"], "2026-08-04T00:00:00Z",
        "response_deadline_at",
    )

    response = api.create_dispute_case(
        f.dispute_payload(
            env["appraisal"]["id"], env["amc"]["id"], env["appraiser"]["id"],
            "COMP_SELECTION", "2026-08-04T09:00:00Z", "2026-08-04T11:00:00Z",
        ),
        DESK_REVIEWER_HEADERS,
    )
    validate_error(response, ApiErrorId.ERR_DUPLICATE_DISPUTE_BASIS, 422)

    assert fx.read_amc(api, env["amc"]["id"])["open_dispute_count"] == 1
    _, meta = validate_paginated(
        api.list_dispute_cases(
            CHIEF_APPRAISER_HEADERS, {"appraisal_id": env["appraisal"]["id"]}
        )
    )
    assert meta["total_count"] == 1


def test_a_different_basis_is_admitted_on_the_same_report(api):
    """The dedup key is the pair, so a second basis is a separate dispute.

    The slot that was refused under the duplicated basis is accepted verbatim under a different
    one, and the company's open tally moves once per accepted filing.

    PRD: "At most one non-resolved dispute may exist for any one combination of appraisal and
    basis, and a second is refused with `ERR_DUPLICATE_DISPUTE_BASIS` (HTTP 422) — the same
    appraisal may perfectly well carry simultaneous open disputes on two *different* bases."

    PRD: "Filing increments the company's `open_dispute_count`."

    Design: Corner/errors/error_duplicate_dispute_basis_on_the_same_appraisal_rejected
    """
    env = _report_with_one_dispute(api)

    second = validate_success(
        api.create_dispute_case(
            f.dispute_payload(
                env["appraisal"]["id"], env["amc"]["id"], env["appraiser"]["id"],
                "ADJUSTMENT_SUPPORT", "2026-08-04T09:00:00Z", "2026-08-04T11:00:00Z",
            ),
            DESK_REVIEWER_HEADERS,
        ),
        201,
    )

    assert second["status"] == "OPEN"
    assert second["dispute_basis"] == "ADJUSTMENT_SUPPORT"
    assert fx.read_amc(api, env["amc"]["id"])["open_dispute_count"] == 2


def _enrolled_once(api):
    amc = fx.create_amc(api, name="Duplicate Panel AMC")
    appraiser = fx.create_appraiser(api, **_author("CA-AL-C710"))
    fx.enroll_on_panel(api, appraiser["id"], amc["id"])
    fresh = fx.read_appraiser(api, appraiser["id"])
    assert fresh["panel_membership_count"] == 1
    return {"amc": amc, "appraiser": appraiser, "version": fresh["version"]}


def test_a_second_enrolment_on_a_covered_state_is_refused_whatever_the_tier(api):
    """The uniqueness key is appraiser, company and coverage state — the tier is not in it.

    The second enrolment asks for a different tier over the same state, and that is still the
    same triple. Because the request never succeeds it consumes no token: the appraiser's version
    is exactly where the first enrolment left it, so the same token is still spendable, and the
    membership tally has not moved.

    PRD: "At most one active membership may exist for any one combination of appraiser, company,
    and coverage state; a second attempt at the same triple is rejected with
    `ERR_DUPLICATE_PANEL_MEMBERSHIP` (HTTP 422)."

    Design: Corner/errors/error_duplicate_panel_membership_on_the_same_coverage_state_rejected
    """
    env = _enrolled_once(api)

    response = api.create_panel_membership(
        f.panel_membership_payload(
            env["appraiser"]["id"], env["amc"]["id"], env["version"],
            tier="REVIEW_SPECIALIST",
        ),
        CHIEF_APPRAISER_HEADERS,
    )
    validate_error(response, ApiErrorId.ERR_DUPLICATE_PANEL_MEMBERSHIP, 422)

    after = fx.read_appraiser(api, env["appraiser"]["id"])
    assert after["version"] == env["version"]
    assert after["panel_membership_count"] == 1


def test_a_second_state_is_a_different_triple_and_is_admitted(api):
    """A new coverage state clears the uniqueness key, and the accepted write spends the token.

    The same token that survived the refused duplicate is spent here, which is the clearest proof
    that the earlier refusal left the appraiser untouched.

    PRD: "Enrolment is one of the three operations guarded by the stale-read token of §2.6, so
    `expected_appraiser_version` must carry the appraiser's current `version`; a successful
    enrolment increments that appraiser's `version` by 1 and increments the appraiser's
    `panel_membership_count`."

    Design: Corner/errors/error_duplicate_panel_membership_on_the_same_coverage_state_rejected
    """
    env = _enrolled_once(api)

    second = validate_success(
        api.create_panel_membership(
            f.panel_membership_payload(
                env["appraiser"]["id"], env["amc"]["id"], env["version"],
                coverage_state="NV", tier="REVIEW_SPECIALIST",
            ),
            CHIEF_APPRAISER_HEADERS,
        ),
        201,
    )

    assert second["status"] == "ACTIVE"
    assert second["coverage_state"] == "NV"
    after = fx.read_appraiser(api, env["appraiser"]["id"])
    assert after["panel_membership_count"] == 2
    assert after["version"] == env["version"] + 1


def _report_awaiting_a_large_revision(api):
    """A contested report whose borrower asks for a value 2250 basis points above the record.

    The ask itself is admissible at intake — nothing caps what a borrower may request — so the
    cap only bites when the appraiser tries to adopt it.
    """
    env = _one_delivered_report(api, "711", "Lou Borrower", "Revision Cap AMC")
    fx.add_comparables(api, env["appraisal"]["id"], env["amc"]["id"], _grid())
    fx.run_rule_checks(api, env["appraisal"]["id"])
    return fx.rov_awaiting_appraiser(
        api, env, requested_value_cents=49000000, prefix="Birch"
    )


def _answer(api, env, revised_value_cents, note):
    return api.rov_appraiser_response(
        env["rov"]["id"],
        f.rov_response_payload(
            "VALUE_REVISED", response_note=note,
            revised_value_cents=revised_value_cents,
        ),
        make_appraiser_headers(env["appraiser"]["id"]),
    )


def test_a_revision_above_the_cap_is_refused_and_writes_nothing(api):
    """The movement is measured against the value of record, and 2250 basis points is too far.

    The refusal leaves the reconsideration exactly where it was — still the appraiser's to answer,
    with no outcome recorded — the appraisal keeps the value it reported, and no revision row is
    written, so the appraiser's revision rate stays at zero.

    PRD: "Whenever a reconsideration appraiser-response, an escalation completion, or a dispute
    resolution proposes a new value, the system computes 10000 multiplied by the absolute
    difference between the proposed value and the appraisal's current `current_value_cents`,
    divided by that current value, rounded half up, and requires the result to be at most 2000
    basis points; a larger movement is refused with `ERR_REVISION_EXCEEDS_CAP` (HTTP 422)."

    Design: Corner/errors/error_revision_exceeds_cap_at_and_above_the_bound_rejected
    """
    env = _report_awaiting_a_large_revision(api)

    validate_error(
        _answer(api, env, 49000000, "Adopting both sales in full."),
        ApiErrorId.ERR_REVISION_EXCEEDS_CAP, 422,
    )

    rov = fx.read_rov_request(api, env["rov"]["id"])
    assert rov["status"] == "AWAITING_APPRAISER"
    assert rov["outcome"] is None
    assert fx.read_appraisal(api, env["appraisal"]["id"])["current_value_cents"] == 40000000
    assert fx.list_value_revisions(api, env["appraisal"]["id"]) == []
    assert fx.read_appraiser(api, env["appraiser"]["id"])["revision_rate_bps"] == 0


def test_a_revision_exactly_on_the_cap_is_admitted_and_costs_the_appraiser(api):
    """At exactly 2000 basis points the bound is inclusive, so the revision lands.

    Accepting it writes the revision, moves the value of record, and re-scores the author: one
    revision against one delivered report is a rate of 10000 basis points, which drives the
    performance score to 4000 and takes the appraiser straight off the panel.

    PRD: "Within the cap, the appraisal moves `VALUE_CONTESTED → VALUE_REVISED`, a value revision
    with `source_type` `ROV` is written, the appraisal's `current_value_cents` is set to the
    revised value, the loan file's `collateral_status` moves `VALUE_CONTESTED → VALUE_REVISED`
    with its value, `ltv_bps`, and `decision_impact` recomputed and the underwriting cascade
    following, and the appraiser's revision tally is incremented with both performance-score
    variants recomputed."

    Design: Corner/errors/error_revision_exceeds_cap_at_and_above_the_bound_rejected
    """
    env = _report_awaiting_a_large_revision(api)

    answered = validate_success(
        _answer(api, env, 48000000, "Adopting both sales with a market adjustment.")
    )
    assert answered["status"] == "RESPONDED"
    assert answered["outcome"] == "VALUE_REVISED"

    appraisal = fx.read_appraisal(api, env["appraisal"]["id"])
    assert appraisal["current_value_cents"] == 48000000
    assert appraisal["review_status"] == "VALUE_REVISED"

    revisions = fx.list_value_revisions(api, env["appraisal"]["id"])
    assert len(revisions) == 1
    assert revisions[0]["source_type"] == "ROV"
    assert revisions[0]["is_compensating"] is False

    author = fx.read_appraiser(api, env["appraiser"]["id"])
    assert author["revision_rate_bps"] == 10000
    assert author["performance_score_bps"] == 4000
    assert author["panel_status"] == "SUSPENDED"
