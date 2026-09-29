"""
Role authority: who owns each write, who is refused it, and which refusal wins.

The happy chain is walked once with every step performed by the role that owns it, so that
five different operator roles each leave their own mark on one report. The refusals are then
driven from the other side: a reviewer reaching for the chief's decision, a compliance
officer reaching for the same, a reviewer reaching for the compliance screen, one operator
identity deciding its own submission, and two entity-backed roles reaching across into
another owner's resources.
"""

from test_helpers import (
    CHIEF_APPRAISER_HEADERS,
    CHIEF_APPRAISER_HEADERS_2,
    CHIEF_USER_1,
    CHIEF_USER_2,
    COMPLIANCE_HEADERS,
    DESK_REVIEWER_HEADERS,
    DESK_USER_1,
    LOAN_OFFICER_HEADERS,
    ApiErrorId,
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


def _author(license_number):
    return {
        "full_name": "Alice Author",
        "license_number": license_number,
        "license_state": "CA",
    }


def test_the_whole_chain_lands_with_each_step_taken_by_its_owning_role(api):
    """Five operator roles each contribute one write to a single report.

    The panel is built by the chief appraiser, the loan registered by the loan officer, the
    report and its grid delivered by the management company, the receipt battery run by the
    desk reviewer, the bias screen run by the compliance officer, and the review opened,
    submitted and finally decided by the desk and the chief in turn. Every step is accepted,
    and the two screening figures written by two different roles both stand on the appraisal.

    PRD: "Two entities in this system carry two independent status dimensions on the same
    row, and conflating them is the single most common way to get this domain wrong. An
    appraisal carries `review_status`, its review lifecycle, and `bias_screen_status`, its
    compliance screening lifecycle."

    PRD: "A `ComplianceOfficer` cannot open, submit, or decide a desk review at all, and an
    `AppraisalDeskReviewer` cannot run the bias screen or adjudicate a bias flag; the
    compliance opinion and the review opinion are produced by different people by
    construction."

    Design: Corner/rbac/exclusive_operations_each_authority_role_performs_its_own_writes
    """
    env = fx.accepted_report(
        api,
        amc={"name": "Exclusive Ops AMC"},
        appraiser=_author("CA-AL-C501"),
        loan={"loan_number": "LN-2747-C501", "borrower_display_name": "Ola Borrower"},
        comparables=[dict(row) for row in CLEAN_GRID],
    )

    memberships, _ = validate_paginated(
        api.list_panel_memberships(
            CHIEF_APPRAISER_HEADERS, {"appraiser_id": env["appraiser"]["id"]}
        )
    )
    assert [row["status"] for row in memberships] == ["ACTIVE"]

    appraisal = fx.read_appraisal(api, env["appraisal"]["id"])
    assert appraisal["completeness_score_bps"] == 10000
    assert appraisal["bias_screen_status"] == "CLEAR"
    assert appraisal["review_status"] == "VALUE_ACCEPTED"

    review = fx.read_desk_review(api, env["desk_review"]["id"])
    assert review["status"] == "ACCEPTED"
    assert review["required_escalation"] == "NONE"
    assert review["final_quality_score_bps"] == 10000
    assert review["created_by_user_id"] == DESK_USER_1
    assert review["submitted_by_user_id"] == DESK_USER_1
    assert review["decided_by_user_id"] == CHIEF_USER_1


def test_the_accepted_chain_leaves_the_loan_priced_off_the_accepted_value(api):
    """The lender-side figures follow from the value the chief accepted.

    Acceptance carries the report's value through to the loan, whose derived ratio is the
    loan amount over that value and whose banding is the mildest tier. The collateral
    dimension records the acceptance.

    PRD: "`ltv_bps` is 10000 multiplied by `loan_amount_cents`, divided by
    `effective_value_cents`, rounded half up."

    PRD: "`decision_impact` is then a four-way banding of `ltv_bps` with **inclusive** upper
    bounds, which is where implementations most often drift by one: the impact is `NO_IMPACT`
    when `ltv_bps` is at most 8000, `PRICING_ADJUSTMENT` when it is at most 9500,
    `CONDITION_REQUIRED` when it is at most 9700, and `DENIAL_RECOMMENDED` otherwise."

    Design: Corner/rbac/exclusive_operations_each_authority_role_performs_its_own_writes
    """
    env = fx.accepted_report(
        api,
        amc={"name": "Exclusive Ops AMC"},
        appraiser=_author("CA-AL-C501"),
        loan={"loan_number": "LN-2747-C501", "borrower_display_name": "Ola Borrower"},
        comparables=[dict(row) for row in CLEAN_GRID],
    )

    loan = fx.read_loan_file(api, env["loan"]["id"])
    assert loan["current_appraised_value_cents"] == 40000000
    assert loan["effective_value_cents"] == 40000000
    assert loan["ltv_bps"] == 7500
    assert loan["decision_impact"] == "NO_IMPACT"
    assert loan["collateral_status"] == "VALUE_ACCEPTED"


def _submitted_by_the_desk(api, suffix, amc_name, borrower, submit_headers=None):
    return fx.submitted_review(
        api,
        submit_headers=submit_headers,
        amc={"name": amc_name},
        appraiser=_author("CA-AL-%s" % suffix),
        loan={
            "loan_number": "LN-2747-%s" % suffix,
            "borrower_display_name": borrower,
        },
        comparables=[dict(row) for row in CLEAN_GRID],
    )


def test_neither_the_reviewer_nor_the_compliance_officer_may_decide_a_review(api):
    """The decision belongs to the chief appraiser alone.

    The reviewer who submitted the review would also trip the segregation-of-duties check if
    it got that far, but the role gate sits above it, so the reviewer is turned away purely
    for not owning the endpoint. The compliance officer is turned away for the same reason.
    The review is still awaiting its decision afterwards.

    PRD: "3. The acting role is authorised for the endpoint — otherwise `ERR_FORBIDDEN_ROLE`
    (403).
    4. For the entity-backed roles, `X-User-ID` matches the target's own owning identifier —
    otherwise `ERR_NOT_RESOURCE_OWNER` (403).
    5. On a desk-review decision, the acting `X-User-ID` differs from `submitted_by_user_id`
    — otherwise `ERR_SEGREGATION_OF_DUTIES` (403)."

    PRD: "A `ComplianceOfficer` cannot open, submit, or decide a desk review at all, and an
    `AppraisalDeskReviewer` cannot run the bias screen or adjudicate a bias flag; the
    compliance opinion and the review opinion are produced by different people by
    construction."

    Design: Corner/rbac/cannot_perform_other_roles_exclusive_review_decision
    """
    env = _submitted_by_the_desk(api, "C502", "Role Gate AMC", "Pia Borrower")
    review_id = env["desk_review"]["id"]

    by_reviewer = api.decide_desk_review(
        review_id,
        f.desk_review_decide_payload("ACCEPT", decision_note="Self approving."),
        DESK_REVIEWER_HEADERS,
    )
    validate_error(by_reviewer, ApiErrorId.ERR_FORBIDDEN_ROLE, 403)

    by_compliance = api.decide_desk_review(
        review_id,
        f.desk_review_decide_payload("ACCEPT", decision_note="Compliance approving."),
        COMPLIANCE_HEADERS,
    )
    validate_error(by_compliance, ApiErrorId.ERR_FORBIDDEN_ROLE, 403)

    review = fx.read_desk_review(api, review_id)
    assert review["status"] == "SUBMITTED"
    assert review["decided_by_user_id"] is None


def test_the_reviewer_may_not_run_the_compliance_screen_even_with_a_current_token(api):
    """A current guard token does not buy a role the endpoint it does not own.

    The reviewer supplies exactly the version the appraisal is on, so nothing but the role
    gate can be refusing. The refusal costs the appraisal nothing: its version is where the
    screen left it.

    PRD: "A `ComplianceOfficer` cannot open, submit, or decide a desk review at all, and an
    `AppraisalDeskReviewer` cannot run the bias screen or adjudicate a bias flag; the
    compliance opinion and the review opinion are produced by different people by
    construction."

    PRD: "3. The acting role is authorised for the endpoint — otherwise `ERR_FORBIDDEN_ROLE`
    (403)."

    Design: Corner/rbac/cannot_perform_other_roles_exclusive_review_decision
    """
    env = _submitted_by_the_desk(api, "C502", "Role Gate AMC", "Pia Borrower")
    appraisal_id = env["appraisal"]["id"]
    before = fx.read_appraisal(api, appraisal_id)

    response = api.run_bias_screen(
        appraisal_id, f.version_payload(before["version"]), DESK_REVIEWER_HEADERS,
    )
    validate_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE, 403)

    after = fx.read_appraisal(api, appraisal_id)
    assert after["version"] == before["version"]
    assert after["bias_screen_status"] == "CLEAR"


def test_the_submitting_identity_may_not_decide_its_own_review(api):
    """Segregation of duties bites once the acting role is the right one.

    The review was submitted by an operator who also holds chief authority. Deciding it under
    that same identity passes the role gate and is refused by the segregation check instead.
    The review keeps its submitter and remains undecided, and the appraisal is still in
    review.

    PRD: "The other face of independence is segregation of duties inside the lender. A desk
    review records three separate operator identities — `created_by_user_id` at creation,
    `submitted_by_user_id` at submission, and `decided_by_user_id` at decision — and the
    decision is refused with `ERR_SEGREGATION_OF_DUTIES` when the deciding identity equals
    the submitting one."

    Design: Corner/rbac/segregation_of_duties_submitter_cannot_also_decide
    """
    env = _submitted_by_the_desk(
        api,
        "C504",
        "SoD AMC",
        "Sol Borrower",
        submit_headers=make_headers(CHIEF_USER_2, "AppraisalDeskReviewer"),
    )
    review_id = env["desk_review"]["id"]
    assert env["desk_review"]["submitted_by_user_id"] == CHIEF_USER_2

    response = api.decide_desk_review(
        review_id,
        f.desk_review_decide_payload(
            "ACCEPT", decision_note="Approving my own submission."
        ),
        CHIEF_APPRAISER_HEADERS_2,
    )
    validate_error(response, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 403)

    review = fx.read_desk_review(api, review_id)
    assert review["status"] == "SUBMITTED"
    assert review["submitted_by_user_id"] == CHIEF_USER_2
    assert review["decided_by_user_id"] is None
    assert fx.read_appraisal(api, env["appraisal"]["id"])["review_status"] == (
        "IN_DESK_REVIEW"
    )


def test_a_different_chief_appraiser_may_decide_the_same_submission(api):
    """The identical decision from a second identity is accepted.

    Nothing about the body changes; only the deciding operator does. The review is accepted,
    records that second identity as the decider, and the acceptance carries through to the
    appraisal and the loan's derived ratio.

    PRD: "The other face of independence is segregation of duties inside the lender. A desk
    review records three separate operator identities — `created_by_user_id` at creation,
    `submitted_by_user_id` at submission, and `decided_by_user_id` at decision — and the
    decision is refused with `ERR_SEGREGATION_OF_DUTIES` when the deciding identity equals
    the submitting one."

    PRD: "`ltv_bps` is 10000 multiplied by `loan_amount_cents`, divided by
    `effective_value_cents`, rounded half up."

    Design: Corner/rbac/segregation_of_duties_submitter_cannot_also_decide
    """
    env = _submitted_by_the_desk(
        api,
        "C504",
        "SoD AMC",
        "Sol Borrower",
        submit_headers=make_headers(CHIEF_USER_2, "AppraisalDeskReviewer"),
    )

    review = validate_success(
        api.decide_desk_review(
            env["desk_review"]["id"],
            f.desk_review_decide_payload(
                "ACCEPT", decision_note="Independent chief review."
            ),
            CHIEF_APPRAISER_HEADERS,
        )
    )

    assert review["status"] == "ACCEPTED"
    assert review["decided_by_user_id"] == CHIEF_USER_1
    assert fx.read_appraisal(api, env["appraisal"]["id"])["review_status"] == (
        "VALUE_ACCEPTED"
    )
    assert fx.read_loan_file(api, env["loan"]["id"])["ltv_bps"] == 7500


def _delivered_for_comms(api):
    return fx.delivered_report(
        api,
        amc={"name": "Comms AMC"},
        appraiser=_author("CA-AL-C503"),
        loan={"loan_number": "LN-2747-C503", "borrower_display_name": "Rex Borrower"},
        comparables=[],
    )


def test_the_communication_channel_admits_all_five_of_its_declared_roles(api):
    """Five different roles each record one message against the same report.

    The desk, the chief, the management company, the loan officer and the borrower all write
    to the audit trail, and each row echoes the acting role and the acting identity from the
    headers it was sent with — which for the two entity-backed senders means the company's own
    identifier and the loan file's own identifier. The trail lists back in creation order,
    oldest first, and carries no version field because the rows are immutable events.

    PRD: "Communications live alongside the screen because they are the other half of the
    independence record. Any of `AppraisalDeskReviewer`, `ChiefAppraiser`, `AMCCoordinator`,
    `LoanOfficer`, or `Borrower` may record a message against an appraisal, supplying the
    `recipient`, the `intent`, and the `body`; the server stamps `sent_at` from the logical
    clock and records `sender_role` and `sender_user_id` from the request headers.
    Communication records are append-only events carrying only `id` and `created_at`, with no
    `updated_at` and no `version`."

    PRD: "List results are always returned in ascending `created_at` order — oldest first —
    and where two rows share a `created_at` value the ordering remains `created_at` ascending
    as the only sanctioned deterministic fallback; resource `id` values never participate in
    ordering, ranking, tie-breaking, or conflict resolution anywhere in this system."

    Design: Corner/rbac/shared_operations_communication_channel_open_to_five_roles
    """
    env = _delivered_for_comms(api)
    appraisal_id = env["appraisal"]["id"]
    amc_id = env["amc"]["id"]
    loan_id = env["loan"]["id"]

    senders = [
        (
            DESK_REVIEWER_HEADERS,
            "AppraisalDeskReviewer",
            DESK_USER_1,
            "APPRAISER",
            "REPORT_CLARIFICATION",
            "Please confirm the gross living area source.",
        ),
        (
            CHIEF_APPRAISER_HEADERS,
            "ChiefAppraiser",
            CHIEF_USER_1,
            "AMC",
            "ORDER_STATUS",
            "Review is queued.",
        ),
        (
            make_amc_headers(amc_id),
            "AMCCoordinator",
            amc_id,
            "LENDER_DESK",
            "ORDER_STATUS",
            "Report delivered on schedule.",
        ),
        (
            LOAN_OFFICER_HEADERS,
            "LoanOfficer",
            None,
            "LENDER_DESK",
            "ORDER_STATUS",
            "Borrower has questions about the timeline.",
        ),
        (
            make_borrower_headers(loan_id),
            "Borrower",
            loan_id,
            "LENDER_DESK",
            "REPORT_CLARIFICATION",
            "Which sales were used?",
        ),
    ]

    written = []
    for headers, role, user_id, recipient, intent, body_text in senders:
        row = validate_success(
            api.create_communication(
                appraisal_id,
                f.communication_payload(recipient, intent, body_text),
                headers,
            ),
            201,
        )
        assert row["sender_role"] == role
        if user_id is not None:
            assert row["sender_user_id"] == user_id
        assert row["recipient"] == recipient
        assert row["intent"] == intent
        assert row["body"] == body_text
        assert "version" not in row
        written.append(row["id"])

    rows, meta = validate_paginated(
        api.list_communications(appraisal_id, DESK_REVIEWER_HEADERS)
    )
    assert meta["total_count"] == 5
    assert [row["id"] for row in rows] == written


def test_the_appraiser_is_not_one_of_the_channels_declared_senders(api):
    """A declared system role is still refused an endpoint it does not own.

    The acting role exists and its identity resolves to the report's own author, but the
    channel names five sender roles and this is not one of them. The attempt is refused on
    the role gate and the audit trail stays empty.

    PRD: "Communications live alongside the screen because they are the other half of the
    independence record. Any of `AppraisalDeskReviewer`, `ChiefAppraiser`, `AMCCoordinator`,
    `LoanOfficer`, or `Borrower` may record a message against an appraisal, supplying the
    `recipient`, the `intent`, and the `body`; the server stamps `sent_at` from the logical
    clock and records `sender_role` and `sender_user_id` from the request headers."

    PRD: "3. The acting role is authorised for the endpoint — otherwise `ERR_FORBIDDEN_ROLE`
    (403)."

    Design: Corner/rbac/shared_operations_communication_channel_open_to_five_roles
    """
    env = _delivered_for_comms(api)
    appraisal_id = env["appraisal"]["id"]

    response = api.create_communication(
        appraisal_id,
        f.communication_payload(
            "LENDER_DESK", "ORDER_STATUS", "Appraiser acknowledging."
        ),
        make_appraiser_headers(env["appraiser"]["id"]),
    )
    validate_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE, 403)

    _, meta = validate_paginated(
        api.list_communications(appraisal_id, DESK_REVIEWER_HEADERS)
    )
    assert meta["total_count"] == 0


def _two_owners(api):
    first_amc = fx.create_amc(api, name="Owner AMC One")
    second_amc = fx.create_amc(api, name="Owner AMC Two")
    appraiser = fx.create_appraiser(api, **_author("CA-AL-C505"))
    fx.enroll_on_panel(api, appraiser["id"], first_amc["id"])
    first_loan = fx.create_loan_file(
        api, loan_number="LN-2747-C505A", borrower_display_name="Tam Borrower",
    )
    second_loan = fx.create_loan_file(
        api, loan_number="LN-2747-C505B", borrower_display_name="Uri Borrower",
    )
    appraisal = fx.deliver_appraisal(
        api, first_loan["id"], appraiser["id"], first_amc["id"]
    )
    fx.add_comparables(api, appraisal["id"], first_amc["id"], [dict(CLEAN_GRID[0])])
    appraisal = fx.run_rule_checks(api, appraisal["id"])
    return {
        "first_amc": first_amc,
        "second_amc": second_amc,
        "appraiser": appraiser,
        "first_loan": first_loan,
        "second_loan": second_loan,
        "appraisal": appraisal,
    }


def test_a_coordinator_may_not_deliver_a_report_for_another_company(api):
    """Delivery compares the acting company against the company named in the body.

    Every reference in the body resolves and the loan file's guard token is current, so the
    only thing left to refuse the call is the ownership comparison — and the acting
    coordinator belongs to the other company. The loan is left untouched, with its version
    unspent and no report against it.

    PRD: "Delivery is the management company's move. An `AMCCoordinator` hands over a
    completed report against a loan file, naming the `loan_file_id` it values, the
    `appraiser_id` who authored it, and the `amc_id` that delivered it — and because an
    `AMCCoordinator` is entity-backed, the `amc_id` in the body must equal the coordinator's
    own `X-User-ID` or the delivery is refused with `ERR_NOT_RESOURCE_OWNER`."

    Design: Corner/rbac/entity_backed_roles_confined_to_their_own_resources
    """
    env = _two_owners(api)
    second_loan = fx.read_loan_file(api, env["second_loan"]["id"])

    response = api.create_appraisal(
        f.appraisal_payload(
            second_loan["id"],
            env["appraiser"]["id"],
            env["first_amc"]["id"],
            second_loan["version"],
        ),
        make_amc_headers(env["second_amc"]["id"]),
    )
    validate_error(response, ApiErrorId.ERR_NOT_RESOURCE_OWNER, 403)

    after = fx.read_loan_file(api, second_loan["id"])
    assert after["version"] == second_loan["version"]
    assert after["value_of_record_appraisal_id"] is None
    _, meta = validate_paginated(
        api.list_appraisals(
            DESK_REVIEWER_HEADERS, {"loan_file_id": second_loan["id"]}
        )
    )
    assert meta["total_count"] == 0


def test_a_borrower_may_not_open_a_reconsideration_on_another_loan(api):
    """Intake compares the acting borrower identity against the loan named in the body.

    The acting identity is a real loan file, just not the one being contested. The filing is
    refused on ownership and the contested loan's reconsideration tally stays at zero.

    PRD: "When a `Borrower` files it, `X-User-ID` must equal the `loan_file_id` in the body,
    or the filing is refused with `ERR_NOT_RESOURCE_OWNER`."

    Design: Corner/rbac/entity_backed_roles_confined_to_their_own_resources
    """
    env = _two_owners(api)

    response = api.create_rov_request(
        f.rov_request_payload(
            env["first_loan"]["id"],
            env["appraisal"]["id"],
            requested_value_cents=41000000,
            borrower_statement="I am not the borrower on this loan.",
        ),
        make_borrower_headers(env["second_loan"]["id"]),
    )
    validate_error(response, ApiErrorId.ERR_NOT_RESOURCE_OWNER, 403)

    assert fx.read_loan_file(api, env["first_loan"]["id"])["rov_request_count"] == 0
    _, meta = validate_paginated(api.list_rov_requests(DESK_REVIEWER_HEADERS))
    assert meta["total_count"] == 0


def test_the_loans_own_borrower_opens_the_reconsideration_at_intake(api):
    """The same body from the right identity is accepted.

    Only the acting identity changes. The request is born at the first round with no
    admissible evidence yet and nothing recorded against the appraiser, and filing loads the
    loan's reconsideration tally.

    PRD: "A new request is created with `status` `INTAKE` and `round_number` 1, with
    `admissible_evidence_count` at 0, and with `response_deadline_at`,
    `appraiser_responded_at`, `outcome`, `revised_value_cents`, `intake_note`,
    `response_note`, `next_round_reason`, and `closure_note` all null and `responded_late`
    false. Filing also increments the loan file's `rov_request_count`."

    Design: Corner/rbac/entity_backed_roles_confined_to_their_own_resources
    """
    env = _two_owners(api)

    request = validate_success(
        api.create_rov_request(
            f.rov_request_payload(
                env["first_loan"]["id"],
                env["appraisal"]["id"],
                requested_value_cents=41000000,
                borrower_statement="Two better sales were omitted.",
            ),
            make_borrower_headers(env["first_loan"]["id"]),
        ),
        201,
    )

    assert request["status"] == "INTAKE"
    assert request["round_number"] == 1
    assert request["admissible_evidence_count"] == 0
    assert request["loan_file_id"] == env["first_loan"]["id"]
    assert request["appraisal_id"] == env["appraisal"]["id"]
    assert request["response_deadline_at"] is None
    assert request["appraiser_responded_at"] is None
    assert request["responded_late"] is False
    assert fx.read_loan_file(api, env["first_loan"]["id"])["rov_request_count"] == 1
