"""Membership onboarding: registration, food-safety paperwork, review loop,
compliance evaluation and member equity."""

from test_helpers import (
    CLOCK_BASE,
    HUB,
    ApiErrorId,
    assert_producer,
    assert_producer_document,
    attach_document,
    create_draft_producer,
    create_producer_payload,
    is_valid_uuid,
    make_compliance_officer_headers,
    make_producer_headers,
    onboard_active_producer,
    read_producer,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestProducerRegistration:
    def test_registering_a_producer_lands_it_in_draft_with_zeroed_counters(self, api):
        """PRD 3.1: "The new producer lands in `onboarding_status` `DRAFT` with
        nothing proven about it: compliance not yet satisfied, a
        `food_safety_tier` of `TIER_NONE`, a `review_cycles` counter and a
        `suspension_count` counter both at 0, and every cooperative money field
        — `paid_in_capital_cents`, `patronage_volume_cents`,
        `shrink_charge_cents`, `retained_patronage_cents` — at 0, along with
        `voting_shares` at 0."

        Design: Corner/entities/create_producer_returns_201_with_declared_defaults
        """
        resp = api.create_producer(create_producer_payload(), HUB)
        data = validate_success(resp, 201)
        assert_producer(data)
        assert data["onboarding_status"] == "DRAFT"
        assert data["compliance_ok"] is False
        assert data["food_safety_tier"] == "TIER_NONE"
        assert data["review_cycles"] == 0
        assert data["suspension_count"] == 0
        assert data["paid_in_capital_cents"] == 0
        assert data["voting_shares"] == 0
        assert data["patronage_volume_cents"] == 0
        assert data["retained_patronage_cents"] == 0
        assert data["shrink_charge_cents"] == 0
        assert data["version"] == 1, "version begins at 1 when the resource is created"
        assert is_valid_uuid(data["id"]), "id must be a bare UUID with no type prefix"

    def test_reading_an_unknown_producer_id_reports_producer_not_found(self, api):
        """PRD 2.4: "if a producer id in the path does not resolve, the request
        fails with `ERR_PRODUCER_NOT_FOUND` before the request body is examined
        at all"

        Design: Corner/entities/get_producer_with_unknown_id_returns_not_found
        """
        resp = api.get_producer("00000000-0000-4000-8000-000000000000", HUB)
        validate_error(resp, ApiErrorId.ERR_PRODUCER_NOT_FOUND.value, 404)

    def test_producer_version_increments_when_the_application_is_submitted(self, api):
        """PRD 2.4: "`version` as an integer that begins at 1 when the resource
        is created and increases by exactly 1 on every mutation of that
        resource"
        PRD 3.1: "Before it can be reviewed it must assemble its food-safety
        paperwork (§3.2), and only then may it submit its application, moving
        `DRAFT → SUBMITTED`."

        Design: Corner/cross_cutting_complexity_layers/entity_version_increments_on_every_mutating_call
        """
        set_clock(CLOCK_BASE)
        producer = create_draft_producer()
        assert producer["version"] == 1
        gap = attach_document(producer["id"], "GAP_AUDIT")
        assert gap["version"] == 1
        attach_document(producer["id"], "LIABILITY_INSURANCE")
        attach_document(producer["id"], "HACCP_PLAN")

        resp = api.submit_application(
            producer["id"], make_producer_headers(producer["id"])
        )
        data = validate_success(resp, 200)
        assert data["onboarding_status"] == "SUBMITTED"
        assert data["version"] == 2, "the application mutation increases version by 1"


class TestFoodSafetyPaperwork:
    def test_application_without_all_three_required_categories_is_refused(self, api):
        """PRD 3.1: "A producer missing any of the three is refused with
        `ERR_MISSING_REQUIRED_DOCUMENTS`, whether the gap is a category never
        uploaded or one whose only document was rejected outright."

        Design: Corner/state_machines/application_without_required_documents_is_rejected
        """
        set_clock(CLOCK_BASE)
        producer = create_draft_producer()
        attach_document(producer["id"], "GAP_AUDIT")
        attach_document(producer["id"], "LIABILITY_INSURANCE")

        resp = api.submit_application(
            producer["id"], make_producer_headers(producer["id"])
        )
        validate_error(resp, ApiErrorId.ERR_MISSING_REQUIRED_DOCUMENTS.value, 422)
        assert read_producer(producer["id"])["onboarding_status"] == "DRAFT"

    def test_second_decision_on_a_verified_document_is_refused(self, api):
        """PRD 3.2: "Either way, the acting user id is stamped into
        `adjudicated_by_user_id`, and a document that is not currently
        `SUBMITTED` cannot be adjudicated at all — a second decision on the same
        document is refused with `ERR_INVALID_DOCUMENT_STATE`."

        Design: Corner/state_machines/verify_an_already_verified_document_returns_invalid_document_state
        """
        set_clock(CLOCK_BASE)
        onboarded = onboard_active_producer()
        gap = onboarded["documents"]["GAP_AUDIT"]

        resp = api.adjudicate_document(
            gap["id"], {"decision": "VERIFY"},
            make_compliance_officer_headers("co-verify-5"),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_DOCUMENT_STATE.value, 409)

        current = validate_success(
            api.list_producer_documents(
                onboarded["producer_id"], HUB, params={"doc_type": "GAP_AUDIT"}
            )
        )[0]
        assert current["status"] == "VERIFIED"
        assert current["adjudicated_by_user_id"] == "co-verify-1"

    def test_verifying_a_replacement_supersedes_the_document_it_replaces(self, api):
        """PRD 3.2: "Verification also retires the paperwork it replaces — any
        other document of the same producer and the same `doc_type` that
        currently stands `VERIFIED`, `REJECTED` or `EXPIRED` is retired along
        `VERIFIED → SUPERSEDED`, `REJECTED → SUPERSEDED` or `EXPIRED →
        SUPERSEDED` respectively, and `SUPERSEDED` is where a document's life
        ends."

        Design: Corner/state_machines/verifying_a_replacement_document_supersedes_the_prior_verified_one
        """
        set_clock(CLOCK_BASE)
        onboarded = onboard_active_producer()
        pid = onboarded["producer_id"]
        replacement = attach_document(
            pid, "GAP_AUDIT", expires_on="2028-01-01T00:00:00Z"
        )

        data = validate_success(
            api.adjudicate_document(
                replacement["id"], {"decision": "VERIFY"},
                make_compliance_officer_headers("co-verify-1"),
            )
        )
        assert data["status"] == "VERIFIED"
        assert_producer_document(data)

        docs = validate_success(
            api.list_producer_documents(pid, HUB, params={"limit": 100})
        )
        by_id = {d["id"]: d for d in docs}
        assert by_id[onboarded["documents"]["GAP_AUDIT"]["id"]]["status"] == "SUPERSEDED"
        assert by_id[onboarded["documents"]["LIABILITY_INSURANCE"]["id"]]["status"] == (
            "VERIFIED"
        )
        producer = read_producer(pid)
        assert producer["compliance_ok"] is True
        assert producer["onboarding_status"] == "ACTIVE"

    def test_audited_tier_requires_a_counting_organic_cert_and_water_test(self, api):
        """PRD 3.2: "On top of that, `food_safety_tier` is `TIER_AUDITED` when
        the producer is compliant **and** additionally holds a counting document
        for both `ORGANIC_CERT` and `WATER_TEST`; it is `TIER_BASIC` when the
        producer is compliant without both of those extras; and it is
        `TIER_NONE` otherwise."

        Design: Corner/calculations/audited_tier_requires_both_organic_cert_and_water_test
        """
        set_clock(CLOCK_BASE)
        onboarded = onboard_active_producer(
            doc_types=["GAP_AUDIT", "LIABILITY_INSURANCE", "HACCP_PLAN", "ORGANIC_CERT"]
        )
        pid = onboarded["producer_id"]
        water = attach_document(pid, "WATER_TEST")
        assert onboarded["producer"]["food_safety_tier"] == "TIER_BASIC"

        validate_success(
            api.adjudicate_document(
                water["id"], {"decision": "VERIFY"},
                make_compliance_officer_headers("co-verify-1"),
            )
        )
        producer = read_producer(pid)
        assert producer["food_safety_tier"] == "TIER_AUDITED"
        assert producer["compliance_ok"] is True

    def test_producer_document_list_returns_only_that_producers_file(self, api):
        """PRD 2.3: "Beyond `limit` and `offset`, collection endpoints accept
        domain filters that are how the system exposes reverse navigation from a
        parent to its children. A producer's document list filters on `doc_type`
        and `status`."
        PRD 3.2: "A producer's onboarding file holds documents, each attached
        with a `doc_type` drawn from `GAP_AUDIT`, `LIABILITY_INSURANCE`,
        `HACCP_PLAN`, `ORGANIC_CERT` and `WATER_TEST`, an `issued_on` instant
        and an `expires_on` instant that must fall strictly after `issued_on`."

        Design: Corner/entities/producer_documents_sub_resource_lists_only_that_producers_documents
        """
        set_clock(CLOCK_BASE)
        first = onboard_active_producer()
        second = onboard_active_producer(
            legal_name="Stony Creek Dairy",
            region_code="ALL",
            contact_email="sc@example.org",
            verifier_user_id="co-verify-2",
            approver_user_id="co-approve-8",
        )

        data, meta = validate_paginated(
            api.list_producer_documents(first["producer_id"], HUB)
        )
        assert meta["total_count"] == 3
        assert len(data) == 3
        assert data[0]["producer_id"] == first["producer_id"]
        assert all(d["producer_id"] != second["producer_id"] for d in data)


class TestMembershipReviewLoop:
    def test_request_changes_increments_the_cycle_and_resubmission_reopens_review(
        self, api
    ):
        """PRD 3.1: "Requesting changes moves the producer `UNDER_REVIEW →
        CHANGES_REQUESTED` and increments `review_cycles` by 1; the producer
        fixes what was flagged and submits again, which moves it
        `CHANGES_REQUESTED → SUBMITTED` under the same completeness gate as the
        first submission, and the first adjudication of any of its documents
        then takes it back to `UNDER_REVIEW`."

        Design: Difficulty/non_linear_state_machine/producer_changes_requested_resubmission_cycle
        """
        set_clock(CLOCK_BASE)
        producer = create_draft_producer(
            legal_name="Bramble Ridge Farm",
            region_code="CAS",
            contact_email="br@example.org",
        )
        pid = producer["id"]
        gap = attach_document(pid, "GAP_AUDIT")
        attach_document(pid, "LIABILITY_INSURANCE")
        attach_document(pid, "HACCP_PLAN")
        validate_success(api.submit_application(pid, make_producer_headers(pid)))

        officer = make_compliance_officer_headers("co-verify-1")
        validate_success(api.adjudicate_document(gap["id"], {"decision": "VERIFY"},
                                                 officer))
        after_first = validate_success(
            api.review_producer(
                pid, {"decision": "REQUEST_CHANGES", "note": "GAP scope too narrow"},
                officer,
            )
        )
        assert after_first["review_cycles"] == 1
        assert after_first["onboarding_status"] == "CHANGES_REQUESTED"

        resubmitted = validate_success(
            api.submit_application(pid, make_producer_headers(pid))
        )
        assert resubmitted["onboarding_status"] == "SUBMITTED"

    def test_second_revision_round_returns_the_producer_to_changes_requested(self, api):
        """PRD 3.1: "Requesting changes moves the producer `UNDER_REVIEW →
        CHANGES_REQUESTED` and increments `review_cycles` by 1; the producer
        fixes what was flagged and submits again, which moves it
        `CHANGES_REQUESTED → SUBMITTED` under the same completeness gate as the
        first submission, and the first adjudication of any of its documents
        then takes it back to `UNDER_REVIEW`."
        PRD 3.2: "A producer's `compliance_ok` is true when, and only when, it
        holds such a document for each of the three required categories:
        `GAP_AUDIT`, `LIABILITY_INSURANCE` and `HACCP_PLAN`."

        Design: Difficulty/non_linear_state_machine/producer_changes_requested_resubmission_cycle
        """
        set_clock(CLOCK_BASE)
        producer = create_draft_producer(
            legal_name="Bramble Ridge Farm",
            region_code="CAS",
            contact_email="br@example.org",
        )
        pid = producer["id"]
        gap = attach_document(pid, "GAP_AUDIT")
        ins = attach_document(pid, "LIABILITY_INSURANCE")
        hac = attach_document(pid, "HACCP_PLAN")
        validate_success(api.submit_application(pid, make_producer_headers(pid)))

        officer = make_compliance_officer_headers("co-verify-1")
        validate_success(api.adjudicate_document(gap["id"], {"decision": "VERIFY"},
                                                 officer))
        validate_success(
            api.review_producer(
                pid, {"decision": "REQUEST_CHANGES", "note": "GAP scope too narrow"},
                officer,
            )
        )
        validate_success(api.submit_application(pid, make_producer_headers(pid)))
        validate_success(api.adjudicate_document(ins["id"], {"decision": "VERIFY"},
                                                 officer))
        final = validate_success(
            api.review_producer(
                pid,
                {"decision": "REQUEST_CHANGES", "note": "insurance limit too low"},
                officer,
            )
        )
        assert final["onboarding_status"] == "CHANGES_REQUESTED"
        assert final["review_cycles"] == 2
        assert final["compliance_ok"] is False

        docs = validate_success(
            api.list_producer_documents(pid, HUB, params={"limit": 100})
        )
        by_id = {d["id"]: d for d in docs}
        assert by_id[hac["id"]]["status"] == "SUBMITTED"

    def test_fourth_request_changes_hits_the_review_cycle_ceiling(self, api):
        """PRD 3.1: "This revision loop is bounded: a producer may be sent back
        for changes at most three times, and a fourth `REQUEST_CHANGES` decision
        — one issued when `review_cycles` has already reached the ceiling of 3 —
        is refused with `ERR_REVIEW_CYCLE_LIMIT`."

        Design: Corner/state_machines/fourth_request_changes_hits_the_review_cycle_limit
        """
        set_clock(CLOCK_BASE)
        producer = create_draft_producer()
        pid = producer["id"]
        gap = attach_document(pid, "GAP_AUDIT")
        ins = attach_document(pid, "LIABILITY_INSURANCE")
        hac = attach_document(pid, "HACCP_PLAN")
        org = attach_document(pid, "ORGANIC_CERT")
        officer = make_compliance_officer_headers("co-verify-1")
        producer_hdrs = make_producer_headers(pid)

        validate_success(api.submit_application(pid, producer_hdrs))
        for doc, note in ((gap, "round 1"), (ins, "round 2"), (hac, "round 3")):
            validate_success(
                api.adjudicate_document(doc["id"], {"decision": "VERIFY"}, officer)
            )
            validate_success(
                api.review_producer(
                    pid, {"decision": "REQUEST_CHANGES", "note": note}, officer
                )
            )
            validate_success(api.submit_application(pid, producer_hdrs))
        validate_success(
            api.adjudicate_document(org["id"], {"decision": "VERIFY"}, officer)
        )

        resp = api.review_producer(
            pid, {"decision": "REQUEST_CHANGES", "note": "round 4"}, officer
        )
        validate_error(resp, ApiErrorId.ERR_REVIEW_CYCLE_LIMIT.value, 409)

        final = read_producer(pid)
        assert final["review_cycles"] == 3
        assert final["onboarding_status"] == "UNDER_REVIEW"
        assert final["compliance_ok"] is True

    def test_approving_a_producer_whose_paperwork_is_incomplete_is_refused(self, api):
        """PRD 3.1: "Approval, by contrast, moves the producer `UNDER_REVIEW →
        ACTIVE`, but only if its compliance evaluation currently passes; an
        approval attempted against a producer whose required documents are not
        all verified and unexpired is refused with `ERR_PRODUCER_NOT_COMPLIANT`."

        Design: Corner/state_machines/approving_a_producer_without_full_compliance_is_rejected
        """
        set_clock(CLOCK_BASE)
        producer = create_draft_producer()
        pid = producer["id"]
        gap = attach_document(pid, "GAP_AUDIT")
        ins = attach_document(pid, "LIABILITY_INSURANCE")
        attach_document(pid, "HACCP_PLAN")
        validate_success(api.submit_application(pid, make_producer_headers(pid)))
        officer = make_compliance_officer_headers("co-verify-1")
        validate_success(api.adjudicate_document(gap["id"], {"decision": "VERIFY"},
                                                 officer))
        validate_success(api.adjudicate_document(ins["id"], {"decision": "VERIFY"},
                                                 officer))

        resp = api.review_producer(
            pid, {"decision": "APPROVE"}, make_compliance_officer_headers("co-approve-9")
        )
        validate_error(resp, ApiErrorId.ERR_PRODUCER_NOT_COMPLIANT.value, 422)

        final = read_producer(pid)
        assert final["onboarding_status"] == "UNDER_REVIEW"
        assert final["compliance_ok"] is False

    def test_a_terminated_producer_cannot_be_reinstated(self, api):
        """PRD 3.1: "Termination is the exit door, and it is guarded by a
        settlement condition rather than a state condition: a producer may be
        terminated along `ACTIVE → TERMINATED`, `SUSPENDED → TERMINATED` or
        `CHANGES_REQUESTED → TERMINATED`, but only when no allocation drawn on
        any of its catalog items is still `RESERVED` or `STAGED`."
        PRD 3.1: "`TERMINATED` is final — there is no path back."

        Design: Corner/state_machines/terminated_producer_cannot_be_reinstated
        """
        set_clock(CLOCK_BASE)
        onboarded = onboard_active_producer()
        pid = onboarded["producer_id"]
        validate_success(
            api.review_producer(
                pid, {"decision": "TERMINATE", "note": "member resigned"}, HUB
            )
        )

        resp = api.review_producer(pid, {"decision": "REINSTATE"}, HUB)
        validate_error(resp, ApiErrorId.ERR_INVALID_PRODUCER_STATE.value, 409)
        assert read_producer(pid)["onboarding_status"] == "TERMINATED"


class TestDocumentExpiryBoundary:
    def test_a_verified_document_survives_the_millisecond_before_its_expiry(self, api):
        """PRD 3.2: "A document counts toward compliance if and only if it is
        `VERIFIED` and its `expires_on` is strictly later than the current
        logical clock instant; documents that are `SUBMITTED`, `REJECTED`,
        `EXPIRED` or `SUPERSEDED` never count, and a document whose expiry
        instant exactly equals the clock is already expired."

        Design: Difficulty/boundary_precision_check/document_expiry_boundary_is_strict_at_the_equal_instant
        """
        set_clock(CLOCK_BASE)
        onboarded = onboard_active_producer(
            expiries={"GAP_AUDIT": "2026-10-01T00:00:00Z"}
        )
        pid = onboarded["producer_id"]

        set_clock("2026-09-30T23:59:59.999Z")

        producer = read_producer(pid)
        assert producer["compliance_ok"] is True
        assert producer["onboarding_status"] == "ACTIVE"
        assert producer["food_safety_tier"] == "TIER_BASIC"
        docs = validate_success(
            api.list_producer_documents(pid, HUB, params={"doc_type": "GAP_AUDIT"})
        )
        assert docs[0]["status"] == "VERIFIED"

    def test_a_document_expires_at_the_exact_instant_and_suspends_the_producer(
        self, api
    ):
        """PRD 3.2: "Advancing the logical clock past a verified document's
        `expires_on` moves that document `VERIFIED → EXPIRED` — again strictly,
        so an expiry instant equal to the new clock instant is expired — and
        then re-evaluates the owning producer. If that producer was `ACTIVE` and
        its compliance has just flipped from satisfied to unsatisfied, it is
        suspended automatically, `ACTIVE → SUSPENDED`, with exactly the same
        consequences as a hand-issued suspension."

        Design: Difficulty/boundary_precision_check/document_expiry_boundary_is_strict_at_the_equal_instant
        """
        set_clock(CLOCK_BASE)
        onboarded = onboard_active_producer(
            expiries={"GAP_AUDIT": "2026-10-01T00:00:00Z"}
        )
        pid = onboarded["producer_id"]
        set_clock("2026-09-30T23:59:59.999Z")

        set_clock("2026-10-01T00:00:00Z")

        docs = validate_success(
            api.list_producer_documents(pid, HUB, params={"limit": 100})
        )
        by_id = {d["id"]: d for d in docs}
        assert by_id[onboarded["documents"]["GAP_AUDIT"]["id"]]["status"] == "EXPIRED"
        assert by_id[onboarded["documents"]["LIABILITY_INSURANCE"]["id"]]["status"] == (
            "VERIFIED"
        )

        producer = read_producer(pid)
        assert producer["compliance_ok"] is False
        assert producer["food_safety_tier"] == "TIER_NONE"
        assert producer["onboarding_status"] == "SUSPENDED"
        assert producer["suspension_count"] == 1

    def test_the_clock_starts_at_its_declared_default_instant(self, api):
        """PRD 2.5: "At startup the logical clock reads exactly
        `2026-08-01T00:00:00Z`, and it stays at that instant until an
        administrator moves it: an administrative capability accepts a
        `to_iso8601` instant and sets the clock to it."
        PRD 3.2: "Verification carries one extra precondition of its own: a
        document whose `expires_on` has already been reached on the logical
        clock cannot be verified, and the attempt is refused with the same
        `ERR_INVALID_DOCUMENT_STATE`."

        Design: Corner/endpoints/logical_clock_defaults_to_2026_08_01_before_any_set_call
        """
        producer = create_draft_producer()
        pid = producer["id"]
        doc_eq = attach_document(
            pid, "GAP_AUDIT", expires_on="2026-08-01T00:00:00Z"
        )
        doc_late = attach_document(
            pid, "GAP_AUDIT", expires_on="2026-08-01T00:00:01Z"
        )
        officer = make_compliance_officer_headers("co-verify-1")

        resp = api.adjudicate_document(doc_eq["id"], {"decision": "VERIFY"}, officer)
        validate_error(resp, ApiErrorId.ERR_INVALID_DOCUMENT_STATE.value, 409)

        late = validate_success(
            api.adjudicate_document(doc_late["id"], {"decision": "VERIFY"}, officer)
        )
        assert late["status"] == "VERIFIED"

        docs = validate_success(
            api.list_producer_documents(pid, HUB, params={"limit": 100})
        )
        by_id = {d["id"]: d for d in docs}
        assert by_id[doc_eq["id"]]["status"] == "SUBMITTED"


class TestMemberEquity:
    def test_the_share_unit_boundary_is_inclusive(self, api):
        """PRD 3.1: "Voting weight is then re-derived: `voting_shares` is the
        paid-in capital divided by the share unit of 25000 cents — that is, one
        share per 250 dollars of capital — taken down to the whole share below,
        and then capped at 10 shares no matter how much more capital a member
        contributes. The boundary is inclusive at the share unit: exactly 25000
        cents earns 1 share, while 24999 cents earns none."

        Design: Difficulty/boundary_precision_check/voting_shares_threshold_at_the_exact_equity_unit
        """
        set_clock(CLOCK_BASE)
        producer = create_draft_producer(
            legal_name="Hollow Pine Orchard",
            region_code="PIE",
            contact_email="hp@example.org",
        )
        pid = producer["id"]

        below = validate_success(
            api.create_equity_contribution(
                pid, {"amount_cents": 24999, "memo": "initial subscription"}, HUB
            ),
            201,
        )
        assert below["voting_shares"] == 0

        at_unit = validate_success(
            api.create_equity_contribution(pid, {"amount_cents": 1}, HUB), 201
        )
        assert at_unit["paid_in_capital_cents"] == 25000
        assert at_unit["voting_shares"] == 1

    def test_voting_shares_are_capped_at_ten(self, api):
        """PRD 3.1: "Voting weight is then re-derived: `voting_shares` is the
        paid-in capital divided by the share unit of 25000 cents — that is, one
        share per 250 dollars of capital — taken down to the whole share below,
        and then capped at 10 shares no matter how much more capital a member
        contributes. The boundary is inclusive at the share unit: exactly 25000
        cents earns 1 share, while 24999 cents earns none."

        Design: Difficulty/boundary_precision_check/voting_shares_threshold_at_the_exact_equity_unit
        """
        set_clock(CLOCK_BASE)
        producer = create_draft_producer(
            legal_name="Hollow Pine Orchard",
            region_code="PIE",
            contact_email="hp@example.org",
        )
        pid = producer["id"]
        validate_success(
            api.create_equity_contribution(
                pid, {"amount_cents": 24999, "memo": "initial subscription"}, HUB
            ),
            201,
        )
        validate_success(
            api.create_equity_contribution(pid, {"amount_cents": 1}, HUB), 201
        )

        validate_success(
            api.create_equity_contribution(pid, {"amount_cents": 275000}, HUB), 201
        )
        final = read_producer(pid)
        assert final["paid_in_capital_cents"] == 300000
        assert final["voting_shares"] == 10
