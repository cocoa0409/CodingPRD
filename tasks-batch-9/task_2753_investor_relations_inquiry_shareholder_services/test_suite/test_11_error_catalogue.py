"""Error-catalogue corners: which code each refusal must actually carry.

Every test here builds its own world through the documented endpoints only. The
server is restarted before each test, so the store starts empty with the logical
clock at its default instant.
"""

from test_helpers import (
    ApiClient,
    ApiErrorId,
    DISCLOSURE_OFFICER,
    IR_ADMIN,
    IR_ANALYST,
    MISSING_ROLE_HEADERS,
    MISSING_USER_ID_HEADERS,
    NON_EXISTENT_UUID,
    NO_AUTH_HEADERS,
    TRANSFER_AGENT,
    TRANSFER_AGENT_2,
    UNKNOWN_ROLE_HEADERS,
    assertions,
    factories,
    fixtures,
    make_investor_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

DEFAULT_CLOCK = "2026-08-01T00:00:00Z"


def test_absent_and_undeclared_role_headers_are_unauthenticated(api: ApiClient):
    """PRD §2.1: "Every request to every endpoint must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the capacity in which that user acts."
    PRD §2.1: "If either header is absent, or if `X-User-Role` is not one of the five declared role names, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."
    PRD §2.1: "Authentication is checked before authorisation, and both are checked before anything else about the request — including whether the request body parses."

    Design: Corner/errors/missing_role_header_returns_unauthenticated
    """
    fixtures.set_clock(api, DEFAULT_CLOCK)
    company = fixtures.create_company(
        api, ticker="AUT", legal_name="Auth Corp", shares_outstanding=1000000
    )

    for label, headers in (
        ("no headers at all", NO_AUTH_HEADERS),
        ("X-User-Role absent", MISSING_ROLE_HEADERS),
        ("X-User-ID absent", MISSING_USER_ID_HEADERS),
        ("an undeclared role name", UNKNOWN_ROLE_HEADERS),
    ):
        response = api.get_company(company["id"], headers)
        assert response.status_code == 401, f"{label}: expected 401, got {response.status_code}"
        validate_error(response, ApiErrorId.UNAUTHENTICATED.value, 401)
        body = response.json()
        assert body["response_type"] == "error"
        assert isinstance(body["meta"]["api_request_id"], str)
        assert body["meta"]["api_request_id"].startswith("req_")
        assert isinstance(body["meta"]["api_request_timestamp"], str)

    # A well-formed role on the endpoint's list still reads the same row.
    validate_success(api.get_company(company["id"], IR_ADMIN))


def test_each_addressable_entity_has_its_own_not_found_code(api: ApiClient):
    """PRD §3.4: "Addressing a disclosure that does not exist — or citing one that does not exist — yields `ERR_DISCLOSURE_NOT_FOUND`."
    PRD §3.6: "Drafts may be listed with filters on `inquiry_id`, `cited_disclosure_id`, `author_user_id`, `status` and `disclosure_class` — this listing is the only discovery channel for a draft that a cascade has quietly moved to `BLOCKED` — and addressing a draft that does not exist yields `ERR_RESPONSE_DRAFT_NOT_FOUND`."
    PRD §3.8: "Events may be listed by `company_id`, `event_type` and `status`; addressing one that does not exist yields `ERR_ROADSHOW_EVENT_NOT_FOUND`."
    PRD §3.8: "Requests may be listed by `event_id`, `contact_id` and `status` — the discovery channel for requests a cascade has promoted, released or declined — and addressing one that does not exist yields `ERR_MEETING_REQUEST_NOT_FOUND`."
    PRD §3.9: "Instructions may be listed by `company_id`, `instruction_type` and `status`, and addressing one that does not exist yields `ERR_INSTRUCTION_NOT_FOUND`."
    PRD §2.11: "This same left-to-right discipline governs the single-segment paths as well: the addressed row must exist before any state, ownership or business rule about it is evaluated."
    PRD §3.5: "A `contact_id` or `linked_prior_inquiry_id` that resolves to nothing yields `ERR_CONTACT_NOT_FOUND` or `ERR_INQUIRY_NOT_FOUND` respectively, and a contact that exists but belongs to a different issuer than the one named is refused with `ERR_CONTACT_COMPANY_MISMATCH`."

    Design: Corner/errors/every_remaining_entity_path_has_its_own_not_found_code
    """
    fixtures.set_clock(api, DEFAULT_CLOCK)

    probes = (
        (api.get_disclosure(NON_EXISTENT_UUID, DISCLOSURE_OFFICER), ApiErrorId.DISCLOSURE_NOT_FOUND),
        (api.get_inquiry(NON_EXISTENT_UUID, IR_ANALYST), ApiErrorId.INQUIRY_NOT_FOUND),
        (
            api.get_response_draft(NON_EXISTENT_UUID, IR_ANALYST),
            ApiErrorId.RESPONSE_DRAFT_NOT_FOUND,
        ),
        (api.get_roadshow_event(NON_EXISTENT_UUID, IR_ADMIN), ApiErrorId.ROADSHOW_EVENT_NOT_FOUND),
        (
            api.get_meeting_request(NON_EXISTENT_UUID, IR_ADMIN),
            ApiErrorId.MEETING_REQUEST_NOT_FOUND,
        ),
        (api.get_instruction(NON_EXISTENT_UUID, TRANSFER_AGENT), ApiErrorId.INSTRUCTION_NOT_FOUND),
    )
    seen = []
    for response, expected in probes:
        assert response.status_code == 404, (
            f"{expected.value}: expected 404, got {response.status_code}"
        )
        validate_error(response, expected.value, 404)
        seen.append(response.json()["data"]["error_id"])

    assert seen == [
        ApiErrorId.DISCLOSURE_NOT_FOUND.value,
        ApiErrorId.INQUIRY_NOT_FOUND.value,
        ApiErrorId.RESPONSE_DRAFT_NOT_FOUND.value,
        ApiErrorId.ROADSHOW_EVENT_NOT_FOUND.value,
        ApiErrorId.MEETING_REQUEST_NOT_FOUND.value,
        ApiErrorId.INSTRUCTION_NOT_FOUND.value,
    ], "each collection must answer with its own not-found code, in path order"
    assert len(set(seen)) == 6, "no two collections may collapse onto a shared not-found code"


def test_estimate_without_granted_model_access_is_refused_then_accepted(api: ApiClient):
    """PRD §3.7: "The filing contact's `model_access_status` must be `GRANTED`, because an analyst who has not been given the model has nothing to build an estimate on; otherwise the filing is refused with `ERR_MODEL_ACCESS_REQUIRED`."
    PRD §3.2: "Three fields are seeded by the system and cannot be supplied at creation: `model_access_status` starts at `NONE`, `threat_level` starts at `NONE`, and `dividend_received_cents` starts at 0."
    PRD §3.3: "A successful grant increments the contact's `version` by 1 and touches nothing else."
    PRD §3.7: "A successful filing is born with `status` `ACCEPTED` and `submitted_at` stamped from the logical clock, and it supersedes the filer's own history: any earlier submission by the same contact for the same `metric` and the same `period_label` that is still `ACCEPTED` transitions to `SUPERSEDED`."

    Design: Corner/errors/estimate_without_granted_model_access_is_rejected
    """
    fixtures.set_clock(api, DEFAULT_CLOCK)
    company = fixtures.create_company(
        api, ticker="MAR", legal_name="Model Access Required Corp", shares_outstanding=1000000
    )
    analyst = fixtures.create_analyst(
        api,
        company["id"],
        display_name="Ungranted Analyst",
        email="mar@bank.test",
        nda_on_file=True,
        coverage_status="INITIATED",
    )
    analyst_id = analyst["id"]
    investor_headers = make_investor_headers(analyst_id)

    before = fixtures.read_contact(api, analyst_id)
    assert before["model_access_status"] == "NONE"
    assert before["coverage_status"] == "INITIATED"
    assert before["nda_on_file"] is True
    version_before_grant = before["version"]
    assert version_before_grant == 1

    refused = api.create_estimate(
        factories.estimate_payload(
            analyst_id,
            version_before_grant,
            metric="REVENUE",
            period_label="FY2026",
            value=1200.0000,
        ),
        investor_headers,
    )
    validate_error(refused, ApiErrorId.MODEL_ACCESS_REQUIRED.value, 403)

    filed, _meta = validate_paginated(
        api.list_contact_estimates(analyst_id, headers=IR_ADMIN)
    )
    assert filed == [], "a refused filing must not leave an EstimateSubmission row behind"

    fixtures.grant_model_access(api, analyst_id, DISCLOSURE_OFFICER)
    granted = fixtures.read_contact(api, analyst_id)
    assert granted["model_access_status"] == "GRANTED"
    assert granted["version"] == version_before_grant + 1

    accepted = validate_success(
        api.create_estimate(
            factories.estimate_payload(
                analyst_id,
                granted["version"],
                metric="REVENUE",
                period_label="FY2026",
                value=1200.0000,
            ),
            investor_headers,
        ),
        201,
    )
    assert accepted["status"] == "ACCEPTED"
    assert accepted["contact_id"] == analyst_id
    assert accepted["metric"] == "REVENUE"
    assert accepted["period_label"] == "FY2026"
    assertions.assert_ts_equals(accepted["submitted_at"], DEFAULT_CLOCK, "submitted_at")

    rows, meta = validate_paginated(api.list_contact_estimates(analyst_id, headers=IR_ADMIN))
    assert meta["total_count"] == 1
    assert [row["status"] for row in rows] == ["ACCEPTED"]


def test_estimate_from_a_non_covering_analyst_is_rejected(api: ApiClient):
    """PRD §3.7: "And the filing contact must be a `SELL_SIDE_ANALYST` whose `coverage_status` is exactly `INITIATED`; an analyst who has not initiated coverage, one whose coverage is `SUSPENDED` or `NOT_COVERING`, or a holder row attempting to file at all, is refused with `ERR_COVERAGE_NOT_INITIATED`."
    PRD §3.2: "`coverage_status` defaults to `NOT_COVERING` and may otherwise be `INITIATED` or `SUSPENDED`; and `activist_flag` defaults to false."
    PRD §3.3: "The two dimensions are genuinely independent and never gate each other: an analyst whose access is `REVOKED` can still be escalated to `CRITICAL`, and a contact already at `CRITICAL` can still be granted model access."

    Design: Corner/errors/estimate_from_a_non_covering_analyst_is_rejected
    """
    fixtures.set_clock(api, DEFAULT_CLOCK)
    company = fixtures.create_company(
        api, ticker="CVG", legal_name="Coverage Corp", shares_outstanding=1000000
    )
    analyst = fixtures.create_analyst(
        api,
        company["id"],
        display_name="Not Covering Analyst",
        email="cvg@bank.test",
        nda_on_file=True,
        coverage_status=None,
    )
    analyst_id = analyst["id"]
    fixtures.grant_model_access(api, analyst_id, DISCLOSURE_OFFICER)

    before = fixtures.read_contact(api, analyst_id)
    assert before["coverage_status"] == "NOT_COVERING"
    assert before["model_access_status"] == "GRANTED"

    refused = api.create_estimate(
        factories.estimate_payload(
            analyst_id, before["version"], metric="EPS", period_label="FY2026", value=2.0000
        ),
        make_investor_headers(analyst_id),
    )
    validate_error(refused, ApiErrorId.COVERAGE_NOT_INITIATED.value, 422)

    filed, meta = validate_paginated(
        api.list_contact_estimates(analyst_id, headers=IR_ADMIN)
    )
    assert filed == []
    assert meta["total_count"] == 0


def test_dividend_execution_before_the_payable_date_is_rejected(api: ApiClient):
    """PRD §3.9: "The logical clock must have reached `payable_date`, compared inclusively at calendar-date granularity, or it is refused with `ERR_PAYABLE_DATE_NOT_REACHED`."
    PRD §3.9: "A new instruction is born in `SUBMITTED` with `acknowledged_by_user_id`, `executed_by_user_id`, `snapshot_holder_count`, `snapshot_shares_total`, `payout_ledger`, `total_payout_cents`, `executed_at` and `decision_reason` all null, and `version` at 1."
    PRD §3.9: "It then moves the money: the issuer's `dividend_reserve_cents` decreases by `total_payout_cents` while its `dividend_paid_cents` increases by the same figure, with the issuer's `version` incremented by 1."

    Design: Corner/errors/dividend_execution_before_the_payable_date_is_rejected
    """
    world = fixtures.build_dividend_world(
        api,
        ticker="PAY",
        legal_name="Payable Date Corp",
        shares_outstanding=1000000,
        dividend_reserve_cents=100000,
        holder_shares=[1000],
        clock=DEFAULT_CLOCK,
    )
    company_id = world["company_id"]
    instruction = fixtures.build_acknowledged_dividend(
        api,
        company_id,
        record_date="2026-08-15",
        payable_date="2026-08-25",
        declared_rate_cents_per_share=1.0000,
        funding_mode="DECLARED_RATE",
        submitter_headers=IR_ADMIN,
        acknowledger_headers=TRANSFER_AGENT,
    )
    assert instruction["status"] == "ACKNOWLEDGED"

    # The clock is still at 2026-08-01, well before the 2026-08-25 payable date.
    refused = api.execute_instruction(instruction["id"], TRANSFER_AGENT)
    validate_error(refused, ApiErrorId.PAYABLE_DATE_NOT_REACHED.value, 409)

    after = fixtures.read_instruction(api, instruction["id"])
    assert after["status"] == "ACKNOWLEDGED"
    assert after["payout_ledger"] is None
    assert after["total_payout_cents"] is None
    assert after["executed_at"] is None
    assert after["executed_by_user_id"] is None

    company = fixtures.read_company(api, company_id)
    assert company["dividend_reserve_cents"] == 100000
    assert company["dividend_paid_cents"] == 0
    holder = fixtures.read_contact(api, world["holders"][0]["id"])
    assert holder["dividend_received_cents"] == 0


def test_reversal_exactly_at_the_window_edge_is_rejected(api: ApiClient):
    """PRD §3.9: "It requires a non-empty `reason`, stored as `decision_reason`; an instruction that is not in `EXECUTED` is refused with `ERR_INSTRUCTION_NOT_EXECUTED`; and the logical clock must be strictly earlier than `executed_at` plus 72 hours — three days after execution the window has closed and the attempt is refused with `ERR_REVERSAL_WINDOW_EXPIRED`."
    PRD §3.9: "A successful execution writes `payout_ledger` and `total_payout_cents`, sets `status` to `EXECUTED`, stamps the acting user as `executed_by_user_id` and the logical clock as `executed_at`, and increments the instruction's `version` by 1."
    PRD §3.9: "The issuer's `dividend_reserve_cents` increases by `total_payout_cents` while `dividend_paid_cents` decreases by the same figure, with the issuer's `version` incremented by 1, and each ledger row debits that holder's `dividend_received_cents` by the row's `amount_cents` with that contact's `version` incremented by 1."

    Design: Corner/errors/reversal_exactly_at_the_window_edge_is_rejected
    """
    world = fixtures.build_dividend_world(
        api,
        ticker="RVW",
        legal_name="Reversal Window Corp",
        shares_outstanding=1000000,
        dividend_reserve_cents=100000,
        holder_shares=[1000],
        clock=DEFAULT_CLOCK,
    )
    company_id = world["company_id"]
    holder_id = world["holders"][0]["id"]

    executed = fixtures.build_executed_dividend(
        api,
        company_id,
        execute_at="2026-08-25T00:00:00Z",
        record_date="2026-08-15",
        payable_date="2026-08-25",
        declared_rate_cents_per_share=1.0000,
        funding_mode="DECLARED_RATE",
        submitter_headers=IR_ADMIN,
        acknowledger_headers=TRANSFER_AGENT,
    )
    assert executed["status"] == "EXECUTED"
    assert executed["total_payout_cents"] == 1000
    assertions.assert_ts_equals(executed["executed_at"], "2026-08-25T00:00:00Z", "executed_at")
    assertions.assert_payout_ledger(
        executed, [{"contact_id": holder_id, "shares_held": 1000, "amount_cents": 1000}]
    )

    # Exactly executed_at + 72 hours: the window is strictly bounded, so this is out.
    fixtures.set_clock(api, "2026-08-28T00:00:00Z")
    refused = api.reverse_instruction(
        executed["id"], "Late reversal request from the transfer agent.", TRANSFER_AGENT
    )
    validate_error(refused, ApiErrorId.REVERSAL_WINDOW_EXPIRED.value, 409)

    after = fixtures.read_instruction(api, executed["id"])
    assert after["status"] == "EXECUTED"
    assert after["decision_reason"] is None
    assert after["total_payout_cents"] == 1000

    company = fixtures.read_company(api, company_id)
    assert company["dividend_reserve_cents"] == 99000
    assert company["dividend_paid_cents"] == 1000
    holder = fixtures.read_contact(api, holder_id)
    assert holder["dividend_received_cents"] == 1000


def test_non_dividend_instruction_execution_is_rejected(api: ApiClient):
    """PRD §3.9: "The `instruction_type` must be `DIVIDEND_PAYMENT`, or it is refused with `ERR_INSTRUCTION_TYPE_NOT_PAYABLE` — a `RECORD_DATE_SET` or `RECORD_INQUIRY` instruction is complete at `ACKNOWLEDGED` and has no payout step at all."
    PRD §3.9: "The snapshot counts the issuer's contacts whose `contact_type` is `INSTITUTIONAL_HOLDER` or `RETAIL_HOLDER` and whose `shares_held` is strictly greater than zero, writing that count to `snapshot_holder_count`, and sums those same rows' `shares_held` into `snapshot_shares_total`."

    Design: Corner/errors/non_dividend_instruction_execution_is_rejected
    """
    fixtures.set_clock(api, DEFAULT_CLOCK)
    company = fixtures.create_company(
        api,
        ticker="NPY",
        legal_name="Not Payable Corp",
        shares_outstanding=1000000,
        dividend_reserve_cents=50000,
    )
    holder = fixtures.create_holder(
        api,
        company["id"],
        500,
        display_name="Record Inquiry Holder",
        email="npy@retail.test",
        contact_type="RETAIL_HOLDER",
    )

    instruction = fixtures.create_instruction(
        api,
        company["id"],
        headers=IR_ADMIN,
        instruction_type="RECORD_INQUIRY",
        notes="Holder requests a position statement.",
    )
    acknowledged = fixtures.acknowledge_instruction(
        api, instruction["id"], headers=TRANSFER_AGENT
    )
    assert acknowledged["status"] == "ACKNOWLEDGED"
    assert acknowledged["snapshot_holder_count"] == 1
    assert acknowledged["snapshot_shares_total"] == 500

    refused = api.execute_instruction(instruction["id"], TRANSFER_AGENT_2)
    validate_error(refused, ApiErrorId.INSTRUCTION_TYPE_NOT_PAYABLE.value, 422)

    after = fixtures.read_instruction(api, instruction["id"])
    assert after["status"] == "ACKNOWLEDGED"
    assert after["snapshot_holder_count"] == 1
    assert after["snapshot_shares_total"] == 500
    assert after["payout_ledger"] is None
    assert after["total_payout_cents"] is None
    assert after["executed_at"] is None

    reread_company = fixtures.read_company(api, company["id"])
    assert reread_company["dividend_reserve_cents"] == 50000
    assert reread_company["dividend_paid_cents"] == 0
    assert fixtures.read_contact(api, holder["id"])["dividend_received_cents"] == 0


def test_reversing_an_unexecuted_instruction_is_rejected(api: ApiClient):
    """PRD §3.9: "It requires a non-empty `reason`, stored as `decision_reason`; an instruction that is not in `EXECUTED` is refused with `ERR_INSTRUCTION_NOT_EXECUTED`; and the logical clock must be strictly earlier than `executed_at` plus 72 hours — three days after execution the window has closed and the attempt is refused with `ERR_REVERSAL_WINDOW_EXPIRED`."
    PRD §3.9: "Both branches require the instruction to still be in `SUBMITTED` — anything else is refused with `ERR_INSTRUCTION_ALREADY_DECIDED` — both are barred to the user recorded as `submitted_by_user_id` by `ERR_SEGREGATION_OF_DUTIES`, and both stamp the acting user as `acknowledged_by_user_id` and increment the instruction's `version` by 1."

    Design: Corner/errors/reversing_an_unexecuted_instruction_is_rejected
    """
    world = fixtures.build_dividend_world(
        api,
        ticker="NEX",
        legal_name="Not Executed Corp",
        shares_outstanding=1000000,
        dividend_reserve_cents=100000,
        holder_shares=[1000],
        clock=DEFAULT_CLOCK,
    )
    instruction = fixtures.build_acknowledged_dividend(
        api,
        world["company_id"],
        record_date="2026-08-15",
        payable_date="2026-08-25",
        declared_rate_cents_per_share=1.0000,
        submitter_headers=IR_ADMIN,
        acknowledger_headers=TRANSFER_AGENT,
    )

    refused = api.reverse_instruction(
        instruction["id"],
        "Attempting to unwind a payment that never happened.",
        TRANSFER_AGENT,
    )
    validate_error(refused, ApiErrorId.INSTRUCTION_NOT_EXECUTED.value, 409)

    after = fixtures.read_instruction(api, instruction["id"])
    assert after["status"] == "ACKNOWLEDGED"
    assert after["snapshot_holder_count"] == 1
    assert after["snapshot_shares_total"] == 1000
    assert after["version"] == 2
    assert after["decision_reason"] is None
    assert after["payout_ledger"] is None
    assert after["total_payout_cents"] is None

    company = fixtures.read_company(api, world["company_id"])
    assert company["dividend_reserve_cents"] == 100000
    assert company["dividend_paid_cents"] == 0


def test_third_revision_attempt_is_rejected_at_the_limit(api: ApiClient):
    """PRD §3.6: "The acting `X-User-ID` is stamped as `author_user_id` and becomes the only user permitted to move the draft forward; `reviewer_user_id`, `reviewer_note`, `pinned_disclosure_version` and `blocked_reason` all start null, `status` starts at `DRAFT`, `revision_round` starts at 1, and `version` starts at 1."
    PRD §3.6: "The cycle is bounded: a revision is refused with `ERR_REVISION_LIMIT_REACHED` once `revision_round` has already reached 3, so a draft that has consumed all three authoring rounds is dead and the inquiry needs a fresh draft instead."
    PRD §3.6: "A permitted revision returns the draft to `DRAFT`, increases `revision_round` by 1, clears `blocked_reason` back to null, clears `reviewer_note` back to null, clears `pinned_disclosure_version` back to null, and replaces `body_text`, `disclosure_class` and `cited_disclosure_id` with whichever of those three the author supplied, leaving the others as they were."
    PRD §3.6: "The parent inquiry remains in `DRAFTING` throughout — revision touches only the draft's own `version`."

    Design: Corner/errors/fourth_revision_attempt_is_rejected_at_the_limit
    """
    world = fixtures.build_register_world(
        api,
        ticker="RVL",
        legal_name="Revision Limit Corp",
        shares_outstanding=1000000,
        holder_shares=20000,
        clock=DEFAULT_CLOCK,
    )
    inquiry = fixtures.create_routed_inquiry(
        api,
        world["company_id"],
        world["contact_id"],
        topic_category="GUIDANCE",
        subject="A question that keeps coming back.",
    )
    draft = fixtures.create_draft(
        api,
        inquiry["id"],
        body_text="Round one wording.",
        disclosure_class="PUBLIC_DOMAIN",
    )
    # Born at round 1, so the limit of 3 admits exactly two accepted revisions.
    assert draft["status"] == "DRAFT"
    assert draft["revision_round"] == 1

    for accepted_round, wording in ((2, "Round two wording."), (3, "Round three wording.")):
        fixtures.submit_for_review(api, draft["id"], IR_ANALYST)
        fixtures.decide_review(
            api,
            draft["id"],
            inquiry["id"],
            decision="REQUEST_CHANGES",
            reviewer_note=f"Tighten the wording (pass {accepted_round - 1}).",
            headers=DISCLOSURE_OFFICER,
        )
        revised = fixtures.revise_draft(api, draft["id"], body_text=wording)
        assert revised["revision_round"] == accepted_round
        assert revised["status"] == "DRAFT"
        assert revised["blocked_reason"] is None
        assert revised["reviewer_note"] is None
        assert revised["pinned_disclosure_version"] is None
        assert revised["body_text"] == wording

    # A third round-trip leaves the draft in CHANGES_REQUESTED at round 3.
    fixtures.submit_for_review(api, draft["id"], IR_ANALYST)
    fixtures.decide_review(
        api,
        draft["id"],
        inquiry["id"],
        decision="REQUEST_CHANGES",
        reviewer_note="Tighten the wording (pass 3).",
        headers=DISCLOSURE_OFFICER,
    )
    at_limit = fixtures.read_draft(api, draft["id"])
    assert at_limit["status"] == "CHANGES_REQUESTED"
    assert at_limit["revision_round"] == 3

    refused = api.revise_draft(
        draft["id"], factories.revise_payload(body_text="Round four wording."), IR_ANALYST
    )
    validate_error(refused, ApiErrorId.REVISION_LIMIT_REACHED.value, 409)

    after = fixtures.read_draft(api, draft["id"])
    assert after["status"] == "CHANGES_REQUESTED"
    assert after["revision_round"] == 3
    assert after["body_text"] == "Round three wording."
    assert fixtures.read_inquiry(api, inquiry["id"])["status"] == "DRAFTING"


def test_draft_calls_out_of_their_required_state_are_rejected(api: ApiClient):
    """PRD §3.6: "Submitting for review moves the draft `DRAFT` → `IN_REVIEW` and is available only to the author: another user is refused with `ERR_DRAFT_AUTHOR_MISMATCH`, and a draft in any status other than `DRAFT` is refused with `ERR_DRAFT_INVALID_STATE`."
    PRD §3.6: "It accepts a draft in `CHANGES_REQUESTED` or in `BLOCKED` — any other status is refused with `ERR_DRAFT_INVALID_STATE` — and only from the recorded `author_user_id`, with anyone else refused by `ERR_DRAFT_AUTHOR_MISMATCH`."
    PRD §3.6: "It is refused with `ERR_DRAFT_INVALID_STATE` on a draft that is not `APPROVED`, with `ERR_DRAFT_AUTHOR_MISMATCH` when anyone but the author attempts it, and with `ERR_DISCLOSURE_BLACKOUT` when the issuer's stored `disclosure_posture` is `BLACKOUT` — an answer approved before the quiet period began still cannot leave the building during it."
    PRD §3.6: "A successful submission increments the draft's `version` by 1 and drives the parent inquiry `DRAFTING` → `AWAITING_APPROVAL`, incrementing the inquiry's `version` by 1."

    Design: Corner/errors/draft_calls_out_of_their_required_state_are_rejected
    """
    world = fixtures.build_register_world(
        api,
        ticker="DIS",
        legal_name="Draft State Corp",
        shares_outstanding=1000000,
        holder_shares=20000,
        clock=DEFAULT_CLOCK,
    )
    inquiry = fixtures.create_routed_inquiry(
        api,
        world["company_id"],
        world["contact_id"],
        topic_category="OTHER",
        subject="A question answered in the wrong order.",
    )
    draft = fixtures.create_draft(
        api,
        inquiry["id"],
        body_text="Nothing here is material.",
        disclosure_class="PUBLIC_DOMAIN",
    )
    assert draft["status"] == "DRAFT"

    # Dispatch and revision are both undefined from DRAFT, for the author too.
    validate_error(
        api.send_draft(draft["id"], IR_ANALYST), ApiErrorId.DRAFT_INVALID_STATE.value, 409
    )
    validate_error(
        api.revise_draft(
            draft["id"],
            factories.revise_payload(body_text="Trying to revise before any review."),
            IR_ANALYST,
        ),
        ApiErrorId.DRAFT_INVALID_STATE.value,
        409,
    )

    in_review = validate_success(api.submit_draft_for_review(draft["id"], IR_ANALYST))
    assert in_review["status"] == "IN_REVIEW"

    # Neither a repeated submission nor a revision is defined from IN_REVIEW.
    validate_error(
        api.submit_draft_for_review(draft["id"], IR_ANALYST),
        ApiErrorId.DRAFT_INVALID_STATE.value,
        409,
    )
    validate_error(
        api.revise_draft(
            draft["id"],
            factories.revise_payload(body_text="Trying to revise while the officer holds it."),
            IR_ANALYST,
        ),
        ApiErrorId.DRAFT_INVALID_STATE.value,
        409,
    )

    after = fixtures.read_draft(api, draft["id"])
    assert after["status"] == "IN_REVIEW"
    assert after["body_text"] == "Nothing here is material."
    assert after["revision_round"] == 1
    assert after["reviewer_user_id"] is None
    assert fixtures.read_inquiry(api, inquiry["id"])["status"] == "AWAITING_APPROVAL"


def test_allocation_without_pending_requests_is_rejected(api: ApiClient):
    """PRD §3.8: "Three preconditions guard it: the event must be in `OPEN_FOR_REQUESTS` (otherwise `ERR_EVENT_INVALID_STATE`), the issuer's stored `disclosure_posture` must not be `BLACKOUT` (otherwise `ERR_DISCLOSURE_BLACKOUT`, since a quiet period is no time to be taking investor meetings), and at least one of the event's requests must be in `REQUESTED` (otherwise `ERR_NO_PENDING_REQUESTS`)."
    PRD §2.10: "8. The addressed resource's own state precondition for the requested transition."
    PRD §2.10: "16. Aggregate and collective checks — summed holder positions, the presence of pending requests, the presence of eligible estimates."
    PRD §3.8: "The run finishes by recomputing the event's counters, setting `status` to `LOCKED` and incrementing the event's `version` by 1, and it reports back `event_id`, the resulting `event_status`, the `evaluated_count` of candidates it scored, the resulting `allocated_count` and `waitlisted_count`, and a `threshold_deferred_count` that isolates the requests waitlisted because their score fell below 25 rather than because capacity ran out."

    Design: Corner/errors/allocation_without_pending_requests_is_rejected
    """
    fixtures.set_clock(api, DEFAULT_CLOCK)
    company = fixtures.create_company(
        api, ticker="NPR", legal_name="No Pending Requests Corp", shares_outstanding=1000000
    )
    holder = fixtures.create_holder(
        api, company["id"], 20000, display_name="Pending Holder", email="npr@funds.test"
    )
    event = fixtures.open_event(
        api,
        company["id"],
        event_type="CONFERENCE",
        venue_city="Madrid",
        window_start="2026-09-01T09:00:00Z",
        window_end="2026-09-01T12:00:00Z",
        slot_minutes=30,
        capacity_slots=2,
    )
    assert event["status"] == "OPEN_FOR_REQUESTS"
    assert event["request_ledger_total"] == 0

    empty_run = api.allocate_event(event["id"], IR_ADMIN)
    validate_error(empty_run, ApiErrorId.NO_PENDING_REQUESTS.value, 409)
    assert fixtures.read_event(api, event["id"])["status"] == "OPEN_FOR_REQUESTS"

    request = fixtures.create_meeting_request(
        api,
        event["id"],
        holder["id"],
        headers=IR_ADMIN,
        requested_slot_start="2026-09-01T09:00:00Z",
        requested_slot_end="2026-09-01T09:30:00Z",
    )
    summary = validate_success(api.allocate_event(event["id"], IR_ADMIN))
    assert summary["event_status"] == "LOCKED"
    assert summary["evaluated_count"] == 1
    assert summary["allocated_count"] == 1
    assert summary["waitlisted_count"] == 0
    assert summary["threshold_deferred_count"] == 0

    allocated = fixtures.read_meeting_request(api, request["id"])
    assert allocated["status"] == "ALLOCATED"
    # TIER_2 35 + engagement 8.00 + lead bonus 5, times the 1.20 institutional multiplier.
    assert allocated["final_priority_score"] == assertions.approx_2dp(57.60)

    # The priority-8 state check now answers first, even though nothing is pending.
    locked_run = api.allocate_event(event["id"], IR_ADMIN)
    validate_error(locked_run, ApiErrorId.EVENT_INVALID_STATE.value, 409)
