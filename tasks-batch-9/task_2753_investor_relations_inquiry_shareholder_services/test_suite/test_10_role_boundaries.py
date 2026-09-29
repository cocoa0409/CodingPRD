"""Role boundaries: authorisation, entity-backed investor identity and the two
segregation-of-duties walls.

Every test in this module translates exactly one instance of the corner-design
`rbac` section. The server is restarted before each test, so each one builds its
own world through the documented endpoints.
"""

from test_helpers import (
    ApiClient,
    ApiErrorId,
    NON_EXISTENT_UUID,
    assertions,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import (
    ACK_DECISION_ACKNOWLEDGE,
    CLASS_PUBLIC_DOMAIN,
    CONTACT_INSTITUTIONAL_HOLDER,
    COVERAGE_INITIATED,
    DECISION_APPROVE,
    DISCLOSURE_FORM_8K,
    DRAFT_APPROVED,
    DRAFT_DRAFT,
    DRAFT_IN_REVIEW,
    DRAFT_SENT,
    EVENT_CONFERENCE,
    INQUIRY_ANSWERED,
    INQUIRY_AWAITING_APPROVAL,
    INQUIRY_NEW,
    INSTRUCTION_ACKNOWLEDGED,
    INSTRUCTION_EXECUTED,
    INSTRUCTION_SUBMITTED,
    METRIC_EPS,
    POSTURE_OPEN,
    QUEUE_IR_DESK,
    REQUEST_REQUESTED,
    TOPIC_GUIDANCE,
    TOPIC_OTHER,
)
from test_helpers import (
    DISCLOSURE_OFFICER,
    DISCLOSURE_OFFICER_2,
    DUAL_HAT_ANALYST,
    DUAL_HAT_OFFICER,
    IR_ADMIN,
    IR_ANALYST,
    IR_ANALYST_2,
    TRANSFER_AGENT,
    TRANSFER_AGENT_2,
    make_investor_headers,
)

CLOCK = "2026-08-01T00:00:00Z"


def _boundary_world(api: ApiClient):
    """An issuer, one institutional holder and one routed guidance inquiry, so the
    probed request bodies are otherwise valid."""
    fixtures.set_clock(api, CLOCK)
    company = fixtures.create_company(
        api, ticker="RBA", legal_name="Role Boundary Corp", shares_outstanding=1000000
    )
    holder = fixtures.create_holder(
        api,
        company["id"],
        20000,
        display_name="Boundary Holder",
        email="rba@funds.test",
        contact_type=CONTACT_INSTITUTIONAL_HOLDER,
    )
    inquiry = fixtures.create_inquiry(
        api,
        company["id"],
        holder["id"],
        headers=IR_ADMIN,
        topic_category=TOPIC_GUIDANCE,
        subject="A question used only as a valid body.",
    )
    inquiry = fixtures.route_inquiry(api, inquiry["id"])
    return company, holder, inquiry


class TestExclusiveOperationsAreClosedToPeerRoles:
    def test_each_role_is_refused_a_peers_exclusive_operation(self, api: ApiClient):
        """PRD §2.1: "When both headers are well formed but the named role does not appear on the endpoint's authorised-role list in §4, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
        PRD §3.1: "An `IRAdmin` registers one by supplying a `ticker`, a `legal_name` and a `shares_outstanding` count."
        PRD §3.4: "A `DisclosureOfficer` owns it exclusively, and no other role may create, publish or withdraw one."
        PRD §3.6: "Only an `IRAnalyst` may open one, against an inquiry named by `inquiry_id`, supplying `body_text` (non-empty, at most 4000 characters, and the text that will actually be sent to the contact) and a `disclosure_class` that declares what kind of information the answer contains: `PUBLIC_DOMAIN` for material already in the public record, `GUIDANCE_REPEAT` for a restatement of published guidance, or `MATERIAL_NONPUBLIC` for anything beyond it."
        PRD §3.5: "Either an `IRAdmin` or an `IRAnalyst` intakes one on the inquirer's behalf, naming the issuer through `company_id` and the inquirer through `contact_id`, and supplying a `topic_category` — one of `DIVIDEND`, `RECORD_DATE`, `PROXY`, `GUIDANCE`, `MODEL_REQUEST` or `OTHER` — plus a `subject` line that must be non-empty and at most 200 characters."

        Design: Corner/rbac/each_role_cannot_reach_another_roles_exclusive_operation
        """
        company, holder, inquiry = _boundary_world(api)
        unauthorized = ApiErrorId.UNAUTHORIZED.value

        validate_error(
            api.create_company(
                {
                    "ticker": "XXA",
                    "legal_name": "Analyst Tries To Register",
                    "shares_outstanding": 500000,
                },
                IR_ANALYST,
            ),
            unauthorized,
        )
        validate_error(
            api.create_disclosure(
                {
                    "company_id": company["id"],
                    "disclosure_type": DISCLOSURE_FORM_8K,
                    "fact_key": "8K-RBA-01",
                },
                IR_ADMIN,
            ),
            unauthorized,
        )
        validate_error(
            api.create_response_draft(
                {
                    "inquiry_id": inquiry["id"],
                    "body_text": "An officer trying to author.",
                    "disclosure_class": CLASS_PUBLIC_DOMAIN,
                },
                DISCLOSURE_OFFICER,
            ),
            unauthorized,
        )
        validate_error(
            api.create_roadshow_event(
                {
                    "company_id": company["id"],
                    "event_type": EVENT_CONFERENCE,
                    "venue_city": "Zurich",
                    "window_start": "2026-09-01T09:00:00Z",
                    "window_end": "2026-09-01T12:00:00Z",
                    "slot_minutes": 30,
                    "capacity_slots": 4,
                },
                TRANSFER_AGENT,
            ),
            unauthorized,
        )
        validate_error(
            api.create_inquiry(
                {
                    "company_id": company["id"],
                    "contact_id": holder["id"],
                    "topic_category": TOPIC_OTHER,
                    "subject": "An investor trying to open a ticket directly.",
                },
                make_investor_headers(holder["id"]),
            ),
            unauthorized,
        )

        # None of the refused probes brought a row into existence.
        _companies, company_meta = validate_paginated(api.list_companies(IR_ADMIN))
        assert company_meta["total_count"] == 1
        _disclosures, disclosure_meta = validate_paginated(
            api.list_disclosures(DISCLOSURE_OFFICER)
        )
        assert disclosure_meta["total_count"] == 0
        _drafts, draft_meta = validate_paginated(api.list_response_drafts(IR_ANALYST))
        assert draft_meta["total_count"] == 0
        _events, event_meta = validate_paginated(api.list_roadshow_events(IR_ADMIN))
        assert event_meta["total_count"] == 0
        _inquiries, inquiry_meta = validate_paginated(api.list_inquiries(IR_ANALYST))
        assert inquiry_meta["total_count"] == 1

    def test_role_check_outranks_the_missing_instruction_path_segment(
        self, api: ApiClient
    ):
        """PRD §2.1: "Authentication is checked before authorisation, and both are checked before anything else about the request — including whether the request body parses."
        PRD §3.9: "Acknowledgement is a `TransferAgentLiaison` operation and a two-branch fork on a single `decision` field, either `ACKNOWLEDGE` or `REJECT`."
        PRD §2.10: "Checks therefore run in a fixed order, and the **first** check to fail decides the response; later checks are never reached."

        Design: Corner/rbac/each_role_cannot_reach_another_roles_exclusive_operation
        """
        _boundary_world(api)

        validate_error(
            api.acknowledge_instruction(
                NON_EXISTENT_UUID,
                {"decision": ACK_DECISION_ACKNOWLEDGE},
                IR_ANALYST,
            ),
            ApiErrorId.UNAUTHORIZED.value,
        )


def _two_analyst_world(api: ApiClient):
    """Two covering analysts on one issuer; only the second one has been granted
    model access, so it is the only one that could legitimately file."""
    fixtures.set_clock(api, CLOCK)
    company = fixtures.create_company(
        api, ticker="OWN", legal_name="Ownership Scope Corp", shares_outstanding=1000000
    )
    first = fixtures.create_analyst(
        api,
        company["id"],
        display_name="Analyst One",
        email="own1@bank.test",
        nda_on_file=True,
        coverage_status=COVERAGE_INITIATED,
    )
    second = fixtures.create_analyst(
        api,
        company["id"],
        display_name="Analyst Two",
        email="own2@bank.test",
        nda_on_file=True,
        coverage_status=COVERAGE_INITIATED,
    )
    second = fixtures.grant_model_access(api, second["id"])
    return company, first, second


class TestInvestorIdentityIsEntityBacked:
    def test_investor_cannot_file_an_estimate_for_another_contact(self, api: ApiClient):
        """PRD §2.1: "An `Investor` filing a consensus estimate or requesting a management meeting must supply its own `id` as the `contact_id` in the body; an `Investor` reading a single contact record, or listing the estimates filed under a contact, may only address the contact whose `id` equals its `X-User-ID`."
        PRD §2.1: "Acting on another contact's behalf is refused with `ERR_CONTACT_OWNERSHIP_MISMATCH` (HTTP 403)."
        PRD §2.1: "This ownership check is evaluated after authentication, authorisation, request-shape validation and existence checks, and before optimistic-concurrency checks."
        PRD §3.7: "Because the `Investor` identity is entity-backed, a filer whose `X-User-ID` does not equal the supplied `contact_id` is refused with `ERR_CONTACT_OWNERSHIP_MISMATCH`."

        Design: Corner/rbac/investor_cannot_act_for_another_contact
        """
        _company, first, second = _two_analyst_world(api)
        second_version = fixtures.contact_version(api, second["id"])

        validate_error(
            api.create_estimate(
                {
                    "contact_id": second["id"],
                    "metric": METRIC_EPS,
                    "period_label": "FY2026",
                    "value": 2.0000,
                    "expected_contact_version": second_version,
                },
                make_investor_headers(first["id"]),
            ),
            ApiErrorId.CONTACT_OWNERSHIP_MISMATCH.value,
        )

        # The ownership check outranks the filer's own missing model access and the
        # pinned contact version, and it left no submission behind.
        _rows, meta = validate_paginated(
            api.list_contact_estimates(second["id"], IR_ADMIN)
        )
        assert meta["total_count"] == 0

    def test_investor_cannot_read_another_contacts_record_or_estimate_history(
        self, api: ApiClient
    ):
        """PRD §2.1: "An `Investor` filing a consensus estimate or requesting a management meeting must supply its own `id` as the `contact_id` in the body; an `Investor` reading a single contact record, or listing the estimates filed under a contact, may only address the contact whose `id` equals its `X-User-ID`."
        PRD §2.1: "Acting on another contact's behalf is refused with `ERR_CONTACT_OWNERSHIP_MISMATCH` (HTTP 403)."

        Design: Corner/rbac/investor_cannot_act_for_another_contact
        """
        _company, first, second = _two_analyst_world(api)
        mismatch = ApiErrorId.CONTACT_OWNERSHIP_MISMATCH.value
        borrowed_identity = make_investor_headers(first["id"])

        validate_error(api.get_contact(second["id"], borrowed_identity), mismatch)
        validate_error(
            api.list_contact_estimates(second["id"], borrowed_identity), mismatch
        )

        # Addressing its own row through the same identity is what the role allows.
        own = validate_success(api.get_contact(first["id"], borrowed_identity), 200)
        assert own["id"] == first["id"]


def _dual_hat_review_world(api: ApiClient):
    """A PUBLIC_DOMAIN draft authored by the dual-hatted user and already in review."""
    fixtures.set_clock(api, CLOCK)
    company = fixtures.create_company(
        api,
        ticker="SOD",
        legal_name="Separation Of Duties Corp",
        shares_outstanding=1000000,
    )
    holder = fixtures.create_holder(
        api,
        company["id"],
        20000,
        display_name="Duties Holder",
        email="sod@funds.test",
        contact_type=CONTACT_INSTITUTIONAL_HOLDER,
    )
    pipeline = fixtures.build_answer_pipeline(
        api,
        company["id"],
        holder["id"],
        stage="in_review",
        topic_category=TOPIC_OTHER,
        subject="Who may approve this answer?",
        body_text="Everything here is already public.",
        disclosure_class=CLASS_PUBLIC_DOMAIN,
        author_headers=DUAL_HAT_ANALYST,
    )
    return company, pipeline


class TestReviewWallExcludesTheAuthor:
    def test_the_author_wearing_the_officer_hat_cannot_approve_its_own_draft(
        self, api: ApiClient
    ):
        """PRD §2.8: "The `X-User-ID` recorded as a draft's `author_user_id` may not be the `X-User-ID` that decides that draft's review; an attempt is refused with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."
        PRD §3.6: "Three preconditions are shared by both branches: the draft must be in `IN_REVIEW` (otherwise `ERR_DRAFT_INVALID_STATE`), the supplied inquiry version must match the parent inquiry's current `version` (otherwise `ERR_STALE_INQUIRY_VERSION`), and the acting `X-User-ID` must differ from the draft's `author_user_id` (otherwise `ERR_SEGREGATION_OF_DUTIES`)."
        PRD §3.6: "Both branches stamp the acting user as `reviewer_user_id` and increment both the draft's `version` and the parent inquiry's `version` by 1."

        Design: Corner/rbac/draft_review_requires_a_different_user_than_the_author
        """
        _company, pipeline = _dual_hat_review_world(api)
        inquiry_version = fixtures.inquiry_version(api, pipeline["inquiry_id"])

        validate_error(
            api.review_draft(
                pipeline["draft_id"],
                {
                    "decision": DECISION_APPROVE,
                    "expected_inquiry_version": inquiry_version,
                },
                DUAL_HAT_OFFICER,
            ),
            ApiErrorId.SEGREGATION_OF_DUTIES.value,
        )

        untouched = fixtures.read_draft(api, pipeline["draft_id"])
        assertions.assert_response_draft(
            untouched,
            status=DRAFT_IN_REVIEW,
            reviewer_user_id=None,
            author_user_id="u_dual_1",
        )
        assert (
            fixtures.inquiry_version(api, pipeline["inquiry_id"]) == inquiry_version
        )

    def test_a_second_officer_approves_at_the_version_the_refusal_did_not_consume(
        self, api: ApiClient
    ):
        """PRD §2.8: "The `X-User-ID` recorded as a draft's `author_user_id` may not be the `X-User-ID` that decides that draft's review; an attempt is refused with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."
        PRD §3.6: "An approval that clears all of these moves the draft `IN_REVIEW` → `APPROVED` and captures the cited disclosure's current `version` into `pinned_disclosure_version`; when the draft cites nothing, `pinned_disclosure_version` stays null."
        PRD §3.6: "The parent inquiry deliberately stays in `AWAITING_APPROVAL` — its version advances, but its status does not, because the answer has not yet gone out."

        Design: Corner/rbac/draft_review_requires_a_different_user_than_the_author
        """
        _company, pipeline = _dual_hat_review_world(api)
        inquiry_version = fixtures.inquiry_version(api, pipeline["inquiry_id"])
        review_body = {
            "decision": DECISION_APPROVE,
            "expected_inquiry_version": inquiry_version,
        }

        validate_error(
            api.review_draft(pipeline["draft_id"], review_body, DUAL_HAT_OFFICER),
            ApiErrorId.SEGREGATION_OF_DUTIES.value,
        )

        approved = validate_success(
            api.review_draft(pipeline["draft_id"], review_body, DISCLOSURE_OFFICER_2),
            200,
        )
        assertions.assert_response_draft(
            approved,
            status=DRAFT_APPROVED,
            reviewer_user_id="u_do_2",
            author_user_id="u_dual_1",
            pinned_disclosure_version=None,
        )

        parent = fixtures.read_inquiry(api, pipeline["inquiry_id"])
        assertions.assert_inquiry(
            parent, status=INQUIRY_AWAITING_APPROVAL, version=inquiry_version + 1
        )


def _dividend_world(api: ApiClient):
    """One holder of 1,000 shares and a DIVIDEND_PAYMENT instruction submitted by
    the first liaison, at a declared rate of one cent per share."""
    fixtures.set_clock(api, CLOCK)
    company = fixtures.create_company(
        api,
        ticker="DSD",
        legal_name="Dividend Duties Corp",
        shares_outstanding=1000000,
        dividend_reserve_cents=100000,
    )
    holder = fixtures.create_holder(
        api,
        company["id"],
        1000,
        display_name="Dividend Holder",
        email="dsd@funds.test",
        contact_type=CONTACT_INSTITUTIONAL_HOLDER,
    )
    instruction = fixtures.submit_dividend(
        api,
        company["id"],
        record_date="2026-08-15",
        payable_date="2026-08-25",
        declared_rate_cents_per_share=1.0000,
        headers=TRANSFER_AGENT,
    )
    return company, holder, instruction


class TestDividendWallExcludesTheSubmitter:
    def test_the_submitter_cannot_acknowledge_its_own_instruction(self, api: ApiClient):
        """PRD §2.8: "The `X-User-ID` recorded as a transfer-agent instruction's `submitted_by_user_id` may neither acknowledge nor execute that same instruction; both attempts are refused with `ERR_SEGREGATION_OF_DUTIES`."
        PRD §2.8: "This matters because the `TransferAgentLiaison` role is permitted to submit instructions as well as to decide and execute them, so the wall — not the role list — is what keeps a single liaison from instructing and paying a dividend alone."
        PRD §3.9: "Both branches require the instruction to still be in `SUBMITTED` — anything else is refused with `ERR_INSTRUCTION_ALREADY_DECIDED` — both are barred to the user recorded as `submitted_by_user_id` by `ERR_SEGREGATION_OF_DUTIES`, and both stamp the acting user as `acknowledged_by_user_id` and increment the instruction's `version` by 1."
        PRD §3.9: "The snapshot counts the issuer's contacts whose `contact_type` is `INSTITUTIONAL_HOLDER` or `RETAIL_HOLDER` and whose `shares_held` is strictly greater than zero, writing that count to `snapshot_holder_count`, and sums those same rows' `shares_held` into `snapshot_shares_total`."

        Design: Corner/rbac/dividend_acknowledge_and_execute_both_exclude_the_submitter
        """
        _company, _holder, instruction = _dividend_world(api)
        acknowledge_body = {"decision": ACK_DECISION_ACKNOWLEDGE}

        validate_error(
            api.acknowledge_instruction(
                instruction["id"], acknowledge_body, TRANSFER_AGENT
            ),
            ApiErrorId.SEGREGATION_OF_DUTIES.value,
        )

        untouched = fixtures.read_instruction(api, instruction["id"])
        assertions.assert_instruction(
            untouched,
            status=INSTRUCTION_SUBMITTED,
            submitted_by_user_id="u_ta_1",
            acknowledged_by_user_id=None,
            snapshot_holder_count=None,
            snapshot_shares_total=None,
            version=1,
        )

        # The wall is about the user, not the role: the peer liaison clears it.
        acknowledged = validate_success(
            api.acknowledge_instruction(
                instruction["id"], acknowledge_body, TRANSFER_AGENT_2
            ),
            200,
        )
        assertions.assert_instruction(
            acknowledged,
            status=INSTRUCTION_ACKNOWLEDGED,
            submitted_by_user_id="u_ta_1",
            acknowledged_by_user_id="u_ta_2",
            snapshot_holder_count=1,
            snapshot_shares_total=1000,
            version=2,
        )

    def test_the_submitter_cannot_execute_the_instruction_it_submitted(
        self, api: ApiClient
    ):
        """PRD §2.8: "The `X-User-ID` recorded as a transfer-agent instruction's `submitted_by_user_id` may neither acknowledge nor execute that same instruction; both attempts are refused with `ERR_SEGREGATION_OF_DUTIES`."
        PRD §3.9: "The acting `X-User-ID` must differ from `submitted_by_user_id`, or it is refused with `ERR_SEGREGATION_OF_DUTIES`."
        PRD §3.9: "A successful execution writes `payout_ledger` and `total_payout_cents`, sets `status` to `EXECUTED`, stamps the acting user as `executed_by_user_id` and the logical clock as `executed_at`, and increments the instruction's `version` by 1."
        PRD §3.9: "It then moves the money: the issuer's `dividend_reserve_cents` decreases by `total_payout_cents` while its `dividend_paid_cents` increases by the same figure, with the issuer's `version` incremented by 1."

        Design: Corner/rbac/dividend_acknowledge_and_execute_both_exclude_the_submitter
        """
        company, _holder, instruction = _dividend_world(api)
        fixtures.acknowledge_instruction(
            api, instruction["id"], headers=TRANSFER_AGENT_2
        )
        fixtures.set_clock(api, "2026-08-25T00:00:00Z")

        validate_error(
            api.execute_instruction(instruction["id"], TRANSFER_AGENT),
            ApiErrorId.SEGREGATION_OF_DUTIES.value,
        )

        still_acknowledged = fixtures.read_instruction(api, instruction["id"])
        assertions.assert_instruction(
            still_acknowledged,
            status=INSTRUCTION_ACKNOWLEDGED,
            executed_by_user_id=None,
            total_payout_cents=None,
            executed_at=None,
        )

        executed = validate_success(
            api.execute_instruction(instruction["id"], TRANSFER_AGENT_2), 200
        )
        assertions.assert_instruction(
            executed,
            status=INSTRUCTION_EXECUTED,
            executed_by_user_id="u_ta_2",
            total_payout_cents=1000,
        )
        assertions.assert_ts_equals(executed["executed_at"], "2026-08-25T00:00:00Z")

        payer = fixtures.read_company(api, company["id"])
        assertions.assert_company(
            payer, dividend_reserve_cents=99000, dividend_paid_cents=1000
        )


def _authorship_world(api: ApiClient):
    """A PUBLIC_DOMAIN draft authored by the first analyst on a routed inquiry."""
    fixtures.set_clock(api, CLOCK)
    company = fixtures.create_company(
        api, ticker="AUM", legal_name="Authorship Matters Corp", shares_outstanding=1000000
    )
    holder = fixtures.create_holder(
        api,
        company["id"],
        20000,
        display_name="Authorship Holder",
        email="aum@funds.test",
        contact_type=CONTACT_INSTITUTIONAL_HOLDER,
    )
    inquiry = fixtures.create_routed_inquiry(
        api,
        company["id"],
        holder["id"],
        topic_category=TOPIC_OTHER,
        subject="A question only its own author may push along.",
        headers=IR_ANALYST,
    )
    draft = fixtures.create_draft(
        api,
        inquiry["id"],
        body_text="Everything in this answer is already public.",
        disclosure_class=CLASS_PUBLIC_DOMAIN,
        headers=IR_ANALYST,
    )
    return company, inquiry, draft


class TestAuthorshipWallOnTheDraftsOwnStations:
    def test_a_peer_analyst_cannot_submit_someone_elses_draft_for_review(
        self, api: ApiClient
    ):
        """PRD §2.8: "The wall runs in the other direction too, as an authorship rule: only the user recorded as `author_user_id` may submit that draft for review, revise it, or send it, and anyone else attempting one of those three actions is refused with `ERR_DRAFT_AUTHOR_MISMATCH` (HTTP 403)."
        PRD §3.6: "Submitting for review moves the draft `DRAFT` → `IN_REVIEW` and is available only to the author: another user is refused with `ERR_DRAFT_AUTHOR_MISMATCH`, and a draft in any status other than `DRAFT` is refused with `ERR_DRAFT_INVALID_STATE`."
        PRD §3.6: "A successful submission increments the draft's `version` by 1 and drives the parent inquiry `DRAFTING` → `AWAITING_APPROVAL`, incrementing the inquiry's `version` by 1."

        Design: Corner/rbac/non_author_analyst_cannot_submit_revise_or_send
        """
        _company, inquiry, draft = _authorship_world(api)

        validate_error(
            api.submit_draft_for_review(draft["id"], IR_ANALYST_2),
            ApiErrorId.DRAFT_AUTHOR_MISMATCH.value,
        )

        untouched = fixtures.read_draft(api, draft["id"])
        assertions.assert_response_draft(
            untouched, status=DRAFT_DRAFT, author_user_id="u_ira_1", version=1
        )

        submitted = validate_success(
            api.submit_draft_for_review(draft["id"], IR_ANALYST), 200
        )
        assertions.assert_response_draft(
            submitted, status=DRAFT_IN_REVIEW, author_user_id="u_ira_1", version=2
        )
        assertions.assert_inquiry(
            fixtures.read_inquiry(api, inquiry["id"]), status=INQUIRY_AWAITING_APPROVAL
        )

    def test_a_peer_analyst_cannot_send_an_approved_draft_it_did_not_author(
        self, api: ApiClient
    ):
        """PRD §2.8: "The wall runs in the other direction too, as an authorship rule: only the user recorded as `author_user_id` may submit that draft for review, revise it, or send it, and anyone else attempting one of those three actions is refused with `ERR_DRAFT_AUTHOR_MISMATCH` (HTTP 403)."
        PRD §3.6: "Dispatch is the author's final station and moves the draft `APPROVED` → `SENT`."
        PRD §3.6: "A successful dispatch drives the parent inquiry `AWAITING_APPROVAL` → `ANSWERED` with `answered_at` stamped from the logical clock and the inquiry's `version` incremented, and then recounts the issuer's `open_inquiry_count` — `ANSWERED` being the one status outside the open set — incrementing the issuer's `version` by 1 as well."

        Design: Corner/rbac/non_author_analyst_cannot_submit_revise_or_send
        """
        company, inquiry, draft = _authorship_world(api)
        fixtures.submit_for_review(api, draft["id"], headers=IR_ANALYST)
        fixtures.decide_review(
            api, draft["id"], inquiry["id"], headers=DISCLOSURE_OFFICER
        )

        validate_error(
            api.send_draft(draft["id"], IR_ANALYST_2),
            ApiErrorId.DRAFT_AUTHOR_MISMATCH.value,
        )
        assertions.assert_response_draft(
            fixtures.read_draft(api, draft["id"]), status=DRAFT_APPROVED
        )
        assertions.assert_inquiry(
            fixtures.read_inquiry(api, inquiry["id"]),
            status=INQUIRY_AWAITING_APPROVAL,
            answered_at=None,
        )

        sent = validate_success(api.send_draft(draft["id"], IR_ANALYST), 200)
        assertions.assert_response_draft(
            sent, status=DRAFT_SENT, author_user_id="u_ira_1"
        )
        answered = fixtures.read_inquiry(api, inquiry["id"])
        assertions.assert_inquiry(answered, status=INQUIRY_ANSWERED)
        assertions.assert_ts_equals(answered["answered_at"], CLOCK)
        assertions.assert_company(
            fixtures.read_company(api, company["id"]), open_inquiry_count=0
        )


def _shared_operation_world(api: ApiClient):
    """An issuer with no blackout window and no activists, one institutional holder,
    and one event open for requests with room for four meetings."""
    fixtures.set_clock(api, CLOCK)
    company = fixtures.create_company(
        api, ticker="SHR", legal_name="Shared Operations Corp", shares_outstanding=1000000
    )
    holder = fixtures.create_holder(
        api,
        company["id"],
        20000,
        display_name="Shared Holder",
        email="shr@funds.test",
        contact_type=CONTACT_INSTITUTIONAL_HOLDER,
    )
    event = fixtures.open_event(
        api,
        company["id"],
        event_type=EVENT_CONFERENCE,
        venue_city="Boston",
        window_start="2026-09-02T13:00:00Z",
        window_end="2026-09-02T18:00:00Z",
        slot_minutes=30,
        capacity_slots=4,
    )
    return company, holder, event


class TestSharedOperationsAdmitBothDeclaredRoles:
    def test_both_the_admin_and_the_analyst_may_intake_an_inquiry(self, api: ApiClient):
        """PRD §3.5: "Either an `IRAdmin` or an `IRAnalyst` intakes one on the inquirer's behalf, naming the issuer through `company_id` and the inquirer through `contact_id`, and supplying a `topic_category` — one of `DIVIDEND`, `RECORD_DATE`, `PROXY`, `GUIDANCE`, `MODEL_REQUEST` or `OTHER` — plus a `subject` line that must be non-empty and at most 200 characters."
        PRD §3.5: "A new ticket is born in status `NEW`, with `answered_at` null, and intake recounts the issuer's `open_inquiry_count` and increments the issuer's `version` by 1."
        PRD §2.11: "It is the number of that issuer's inquiry tickets whose status is `NEW`, `ROUTED`, `DRAFTING`, `AWAITING_APPROVAL` or `ESCALATED` — that is, every status except `ANSWERED`."
        PRD §4: "Operations that bring a new resource into existence return `201 Created`."

        Design: Corner/rbac/shared_operations_admit_both_declared_roles
        """
        company, holder, _event = _shared_operation_world(api)

        for headers, subject in (
            (IR_ADMIN, "The admin took this one at the front desk."),
            (IR_ANALYST, "The analyst took this one from the phone queue."),
        ):
            ticket = validate_success(
                api.create_inquiry(
                    {
                        "company_id": company["id"],
                        "contact_id": holder["id"],
                        "topic_category": TOPIC_OTHER,
                        "subject": subject,
                    },
                    headers,
                ),
                201,
            )
            assertions.assert_inquiry(
                ticket,
                status=INQUIRY_NEW,
                routing_queue=QUEUE_IR_DESK,
                answered_at=None,
                version=1,
            )

        assertions.assert_company(
            fixtures.read_company(api, company["id"]), open_inquiry_count=2
        )

    def test_both_the_admin_and_the_officer_may_refresh_the_stored_posture(
        self, api: ApiClient
    ):
        """PRD §3.1: "Because posture is stored rather than queried, the system offers an operator-triggered refresh, available to an `IRAdmin` or a `DisclosureOfficer`."
        PRD §3.1: "The refresh re-derives `disclosure_posture` and recounts `open_inquiry_count`, stamps `posture_recomputed_at` with the logical clock, and increments the issuer's `version` by 1."
        PRD §2.7: "Otherwise the posture is `OPEN`."

        Design: Corner/rbac/shared_operations_admit_both_declared_roles
        """
        company, _holder, _event = _shared_operation_world(api)

        for headers in (IR_ADMIN, DISCLOSURE_OFFICER):
            before = fixtures.company_version(api, company["id"])
            refreshed = validate_success(
                api.recompute_posture(company["id"], headers), 200
            )
            assertions.assert_company(
                refreshed,
                disclosure_posture=POSTURE_OPEN,
                open_inquiry_count=0,
                version=before + 1,
            )
            assertions.assert_ts_equals(refreshed["posture_recomputed_at"], CLOCK)

    def test_both_the_investor_and_the_admin_may_lodge_a_meeting_request(
        self, api: ApiClient
    ):
        """PRD §3.8: "A **MeetingRequest** is one investor's bid for a slot, and either the `Investor` themselves or an `IRAdmin` on their behalf may lodge one, naming the event through `event_id`, the requester through `contact_id`, and the wanted slot through `requested_slot_start` and `requested_slot_end`."
        PRD §3.8: "A surviving request is born in `REQUESTED` with `final_priority_score` null, `allocated_at` null, `release_reason` null and `promoted_from_waitlist` false, and it increments the parent event's `request_ledger_total` by 1 along with the event's `version`."
        PRD §4: "Operations that bring a new resource into existence return `201 Created`."

        Design: Corner/rbac/shared_operations_admit_both_declared_roles
        """
        _company, holder, event = _shared_operation_world(api)

        for headers, start, end in (
            (
                make_investor_headers(holder["id"]),
                "2026-09-02T13:00:00Z",
                "2026-09-02T13:30:00Z",
            ),
            (IR_ADMIN, "2026-09-02T15:00:00Z", "2026-09-02T15:30:00Z"),
        ):
            bid = validate_success(
                api.create_meeting_request(
                    {
                        "event_id": event["id"],
                        "contact_id": holder["id"],
                        "requested_slot_start": start,
                        "requested_slot_end": end,
                    },
                    headers,
                ),
                201,
            )
            assertions.assert_meeting_request(
                bid,
                status=REQUEST_REQUESTED,
                final_priority_score=None,
                allocated_at=None,
                release_reason=None,
                promoted_from_waitlist=False,
                version=1,
            )

        assertions.assert_roadshow_event(
            fixtures.read_event(api, event["id"]), request_ledger_total=2
        )
