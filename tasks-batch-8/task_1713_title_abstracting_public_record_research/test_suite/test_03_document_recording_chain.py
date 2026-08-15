"""Recording instruments: scope window, chain of title, uniqueness, listing (PRD §3.4)."""
from test_helpers import (
    ApiErrorId,
    assert_record_document,
    assert_search_assignment,
    create_assignment,
    create_document,
    create_document_payload,
    create_order,
    get_assignment,
    make_abstracter_headers,
    make_ops_headers,
    setup_order_with_assignment,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestDocumentRecordingValidation:
    def test_record_document_invalid_enum_rejected(self, api):
        """PRD §3.1: "A request missing a required field, presenting an enum
        outside its declared values, or violating a range — a `search_period_years`
        of 0 or 61, a `state_code` in lowercase — is rejected with `ERR_VALIDATION`
        (HTTP 400)."
        PRD §3.4: "an `instrument_type` of `DEED`, `MORTGAGE`, `LIEN`, `JUDGMENT`,
        `TAX_LIEN`, `EASEMENT`, or `RESTRICTION`"

        Design: Corner/entities/record_document_invalid_enum_rejected
        """
        ctx = setup_order_with_assignment("client_804", "abs_804")
        resp = api.create_record_document(
            create_document_payload(
                ctx["order"]["id"],
                ctx["assignment"]["id"],
                instrument_type="WILL",
                instrument_number="INST-804-A",
            ),
            make_abstracter_headers("abs_804"),
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION)

    def test_duplicate_instrument_number_rejected(self, api):
        """PRD §3.4: "Within a single order, an `instrument_number` may appear on
        only one non-`VOID` document; a duplicate is rejected with
        `ERR_DUPLICATE_INSTRUMENT` (HTTP 409)."

        Design: Corner/validations/duplicate_instrument_number_rejected
        """
        ctx = setup_order_with_assignment("client_824", "abs_824")
        first = api.create_record_document(
            create_document_payload(
                ctx["order"]["id"],
                ctx["assignment"]["id"],
                instrument_number="INST-824-A",
                recording_date="2001-01-01",
            ),
            make_abstracter_headers("abs_824"),
        )
        validate_success(first, 201)

        dup = api.create_record_document(
            create_document_payload(
                ctx["order"]["id"],
                ctx["assignment"]["id"],
                grantor_name="X",
                grantee_name="Y",
                instrument_number="INST-824-A",
                recording_date="2002-01-01",
            ),
            make_abstracter_headers("abs_824"),
        )
        validate_error(dup, ApiErrorId.ERR_DUPLICATE_INSTRUMENT)


class TestChainOfTitle:
    def test_record_document_chain_break_flag_computed(self, api):
        """PRD §3.4: "The chain flag `chain_break_flag` applies only to a `DEED`
        whose `prior_document_id` is set: it is true when the new deed's
        `grantor_name`, after trimming surrounding whitespace, differs —
        case-sensitively — from the prior document's `grantee_name` trimmed the
        same way, and false in every other case (non-deed instruments, or no
        predecessor supplied)."

        Design: Corner/entities/record_document_chain_break_flag_computed
        """
        ctx = setup_order_with_assignment("client_805", "abs_805", search_period_years=40)
        prior = create_document(
            ctx["order"]["id"],
            ctx["assignment"]["id"],
            "abs_805",
            grantor_name="A Smith",
            grantee_name="B Jones",
            instrument_number="INST-805-A",
            recording_date="2000-01-01",
        )

        broken = api.create_record_document(
            create_document_payload(
                ctx["order"]["id"],
                ctx["assignment"]["id"],
                grantor_name="Bob Jones",
                grantee_name="C Lee",
                instrument_number="INST-805-B",
                recording_date="2005-01-01",
                prior_document_id=prior["id"],
            ),
            make_abstracter_headers("abs_805"),
        )
        broken_doc = validate_success(broken, 201)
        assert_record_document(broken_doc)
        assert broken_doc["chain_break_flag"] is True, (
            "grantor 'Bob Jones' != prior grantee 'B Jones' — chain continuity broken"
        )

        intact = api.create_record_document(
            create_document_payload(
                ctx["order"]["id"],
                ctx["assignment"]["id"],
                grantor_name="B Jones",
                grantee_name="C Lee",
                instrument_number="INST-805-C",
                recording_date="2006-01-01",
                prior_document_id=prior["id"],
            ),
            make_abstracter_headers("abs_805"),
        )
        intact_doc = validate_success(intact, 201)
        assert intact_doc["chain_break_flag"] is False, "exact trimmed match carries no break"

    def test_chain_break_not_computed_for_non_deed_subject(self, api):
        """PRD §3.4: "The chain flag `chain_break_flag` applies only to a `DEED`
        whose `prior_document_id` is set: it is true when the new deed's
        `grantor_name`, after trimming surrounding whitespace, differs —
        case-sensitively — from the prior document's `grantee_name` trimmed the
        same way, and false in every other case (non-deed instruments, or no
        predecessor supplied)."

        Design: Corner/calculations/chain_break_not_computed_for_non_deed_subject
        """
        ctx = setup_order_with_assignment("client_823", "abs_823")
        prior = create_document(
            ctx["order"]["id"],
            ctx["assignment"]["id"],
            "abs_823",
            grantor_name="A",
            grantee_name="B Jones",
            instrument_number="INST-823-A",
            recording_date="2001-01-01",
        )
        mortgage = api.create_record_document(
            create_document_payload(
                ctx["order"]["id"],
                ctx["assignment"]["id"],
                instrument_type="MORTGAGE",
                grantor_name="Totally Different",
                grantee_name="Bank",
                instrument_number="INST-823-B",
                recording_date="2002-01-01",
                prior_document_id=prior["id"],
            ),
            make_abstracter_headers("abs_823"),
        )
        mortgage_doc = validate_success(mortgage, 201)
        assert mortgage_doc["chain_break_flag"] is False, (
            "chain continuity is only evaluated for DEED subjects"
        )

    def test_chain_link_to_non_deed_rejected(self, api):
        """PRD §3.4: "`prior_document_id`, when present, must reference a document
        of the same order whose `instrument_type` is `DEED` and whose status is not
        `VOID`, else the recording is rejected with `ERR_CHAIN_LINK_INVALID`
        (HTTP 422)."

        Design: Corner/validations/chain_link_to_non_deed_rejected
        """
        ctx = setup_order_with_assignment("client_825", "abs_825")
        mortgage = create_document(
            ctx["order"]["id"],
            ctx["assignment"]["id"],
            "abs_825",
            instrument_type="MORTGAGE",
            grantor_name="A",
            grantee_name="Bank",
            instrument_number="INST-825-A",
            recording_date="2001-01-01",
        )
        resp = api.create_record_document(
            create_document_payload(
                ctx["order"]["id"],
                ctx["assignment"]["id"],
                instrument_number="INST-825-B",
                recording_date="2002-01-01",
                prior_document_id=mortgage["id"],
            ),
            make_abstracter_headers("abs_825"),
        )
        validate_error(resp, ApiErrorId.ERR_CHAIN_LINK_INVALID)

    def test_chain_link_to_other_orders_document_rejected(self, api):
        """PRD §3.4: "`prior_document_id`, when present, must reference a document
        of the same order whose `instrument_type` is `DEED` and whose status is not
        `VOID`, else the recording is rejected with `ERR_CHAIN_LINK_INVALID`
        (HTTP 422)."

        Design: Corner/validations/chain_link_to_other_orders_document_rejected
        """
        order1 = create_order("client_826", property_address="42 Ash St")
        asg1 = create_assignment(
            order1["id"], "abs_826a", window_start="2026-08-01T09:00:00Z",
            window_end="2026-08-01T12:00:00Z",
        )
        deed = create_document(
            order1["id"], asg1["id"], "abs_826a",
            instrument_number="INST-826-A", recording_date="2001-01-01",
        )

        order2 = create_order("client_826", property_address="43 Ash St")
        asg2 = create_assignment(
            order2["id"], "abs_826b", window_start="2026-08-01T09:00:00Z",
            window_end="2026-08-01T12:00:00Z",
        )
        resp = api.create_record_document(
            create_document_payload(
                order2["id"],
                asg2["id"],
                grantor_name="B",
                grantee_name="C",
                instrument_number="INST-826-B",
                recording_date="2002-01-01",
                prior_document_id=deed["id"],
            ),
            make_abstracter_headers("abs_826b"),
        )
        validate_error(resp, ApiErrorId.ERR_CHAIN_LINK_INVALID)


class TestScopeWindowBounds:
    def _setup_scope_order(self, api, client_ref, abstracter_ref):
        return setup_order_with_assignment(
            client_ref, abstracter_ref, search_period_years=30, effective_date="2026-01-15"
        )

    def test_recording_exactly_on_scope_start_date_is_in_scope(self, api):
        """PRD §3.1: "The scope window opens at `scope_start_date`, computed as
        `effective_date` minus `search_period_years` calendar years, keeping the
        same month and day — a thirty-year search effective 2026-03-15 opens on
        1996-03-15."
        PRD §3.4: "The scope flag `in_scope` is true exactly when `recording_date`
        falls on or after the order's `scope_start_date` and on or before its
        `effective_date` — both bounds are inclusive, so an instrument recorded
        exactly on `scope_start_date` is in scope while one recorded the day before
        is not."

        Design: Difficulty/boundary_precision_check/scope_window_inclusive_start_date
        """
        ctx = self._setup_scope_order(api, "client_751", "abs_751")
        assert ctx["order"]["scope_start_date"] == "1996-01-15", (
            f"30y from 2026-01-15 opens 1996-01-15, got {ctx['order']['scope_start_date']}"
        )
        resp = api.create_record_document(
            create_document_payload(
                ctx["order"]["id"],
                ctx["assignment"]["id"],
                grantor_name="Old Owner",
                grantee_name="Mid Owner",
                instrument_number="INST-751-EDGE",
                recording_date="1996-01-15",
            ),
            make_abstracter_headers("abs_751"),
        )
        doc = validate_success(resp, 201)
        assert doc["in_scope"] is True, (
            "recording_date exactly at scope_start_date is IN scope (inclusive bound)"
        )

    def test_recording_one_day_before_scope_start_is_out_of_scope(self, api):
        """PRD §3.4: "The scope flag `in_scope` is true exactly when
        `recording_date` falls on or after the order's `scope_start_date` and on or
        before its `effective_date` — both bounds are inclusive, so an instrument
        recorded exactly on `scope_start_date` is in scope while one recorded the
        day before is not."

        Design: Difficulty/boundary_precision_check/scope_window_inclusive_start_date
        """
        ctx = self._setup_scope_order(api, "client_751", "abs_751")
        resp = api.create_record_document(
            create_document_payload(
                ctx["order"]["id"],
                ctx["assignment"]["id"],
                grantor_name="Older Owner",
                grantee_name="Old Owner",
                instrument_number="INST-751-OUT",
                recording_date="1996-01-14",
            ),
            make_abstracter_headers("abs_751"),
        )
        doc = validate_success(resp, 201)
        assert doc["in_scope"] is False, "one day before scope_start_date is OUT of scope"

    def test_document_scope_effective_date_upper_bound(self, api):
        """PRD §3.4: "The scope flag `in_scope` is true exactly when
        `recording_date` falls on or after the order's `scope_start_date` and on or
        before its `effective_date` — both bounds are inclusive, so an instrument
        recorded exactly on `scope_start_date` is in scope while one recorded the
        day before is not."

        Design: Corner/calculations/document_scope_effective_date_upper_bound
        """
        ctx = setup_order_with_assignment("client_822", "abs_822")
        at_effective = api.create_record_document(
            create_document_payload(
                ctx["order"]["id"],
                ctx["assignment"]["id"],
                instrument_number="INST-822-A",
                recording_date="2026-01-15",
            ),
            make_abstracter_headers("abs_822"),
        )
        doc_in = validate_success(at_effective, 201)
        assert doc_in["in_scope"] is True, "recording exactly on effective_date is in scope"

        past_effective = api.create_record_document(
            create_document_payload(
                ctx["order"]["id"],
                ctx["assignment"]["id"],
                instrument_number="INST-822-B",
                recording_date="2026-01-16",
            ),
            make_abstracter_headers("abs_822"),
        )
        doc_out = validate_success(past_effective, 201)
        assert doc_out["in_scope"] is False, "one day after effective_date is out of scope"


class TestDocumentListing:
    def test_record_documents_list_filters_and_pagination(self, api):
        """PRD §2.3: "The `limit` parameter caps the number of returned items; it
        defaults to 10, with a minimum of 1 and a maximum of 100. The `offset`
        parameter skips a number of items from the front of the result set and
        defaults to 0."
        PRD §2.3: "Paginated list responses carry `limit`, `offset`,
        `total_count`, and `has_more` in the `meta` object of the envelope."
        PRD §4: "List recorded documents with pagination and filters, including
        chain children via the predecessor filter"

        Design: Corner/entities/record_documents_list_filters_and_pagination
        """
        ctx = setup_order_with_assignment("client_807", "abs_807")
        for inst_type, number, date in (
            ("DEED", "INST-807-A", "2001-01-01"),
            ("DEED", "INST-807-B", "2002-01-01"),
            ("LIEN", "INST-807-C", "2003-01-01"),
        ):
            create_document(
                ctx["order"]["id"],
                ctx["assignment"]["id"],
                "abs_807",
                instrument_type=inst_type,
                grantor_name="A",
                grantee_name="B" if inst_type != "LIEN" else "IRS",
                instrument_number=number,
                recording_date=date,
            )

        deeds, deeds_meta = validate_paginated(
            api.list_record_documents(
                make_ops_headers(),
                params={"order_id": ctx["order"]["id"], "instrument_type": "DEED"},
            )
        )
        assert deeds_meta["total_count"] == 2, (
            f"DEED filter must return exactly 2 rows, got {deeds_meta['total_count']}"
        )
        assert len(deeds) == 2

        page, page_meta = validate_paginated(
            api.list_record_documents(
                make_ops_headers(),
                params={"order_id": ctx["order"]["id"], "limit": 1, "offset": 0},
            )
        )
        assert len(page) == 1
        assert page_meta["total_count"] == 3
        assert page_meta["has_more"] is True
        assert page_meta["limit"] == 1
        assert page_meta["offset"] == 0

    def test_fk_reverse_reachability_filtered_lists(self, api):
        """PRD §4: "List assignments with pagination and filters"
        PRD §4: "List recorded documents with pagination and filters, including
        chain children via the predecessor filter"
        PRD §3.4: "Two optional inputs complete the record: `prior_document_id`,
        which links a deed to its chain-of-title predecessor, and
        `exception_applies` (default false), which marks an instrument — typically
        an `EASEMENT` or `RESTRICTION` — as one that must surface as a title
        exception in the report."

        Design: Corner/endpoints/fk_reverse_reachability_filtered_lists
        """
        order = create_order("client_841", property_address="60 Bee St")
        asg1 = create_assignment(
            order["id"], "abs_841", window_start="2026-08-01T09:00:00Z",
            window_end="2026-08-01T12:00:00Z",
        )
        asg2 = create_assignment(
            order["id"], "abs_841", search_type="LIEN_JUDGMENT_TAX",
            window_start="2026-08-01T13:00:00Z", window_end="2026-08-01T16:00:00Z",
        )
        d1 = create_document(
            order["id"], asg1["id"], "abs_841",
            instrument_number="INST-841-A", recording_date="2001-01-01",
        )
        d2 = create_document(
            order["id"], asg1["id"], "abs_841",
            instrument_number="INST-841-B", recording_date="2005-01-01",
            prior_document_id=d1["id"],
        )

        asgs, asgs_meta = validate_paginated(
            api.list_search_assignments(make_ops_headers(), params={"order_id": order["id"]})
        )
        assert asgs_meta["total_count"] == 2
        assert {a["id"] for a in asgs} == {asg1["id"], asg2["id"]}

        docs, docs_meta = validate_paginated(
            api.list_record_documents(make_ops_headers(), params={"assignment_id": asg1["id"]})
        )
        assert docs_meta["total_count"] == 2
        assert {d["id"] for d in docs} == {d1["id"], d2["id"]}

        children, children_meta = validate_paginated(
            api.list_record_documents(make_ops_headers(), params={"prior_document_id": d1["id"]})
        )
        assert children_meta["total_count"] == 1
        assert children[0]["id"] == d2["id"], (
            "the self-referential chain link is reverse-reachable through the predecessor filter"
        )


class TestDocumentCountConservation:
    def test_recording_document_increments_assignment_document_count(self, api):
        """PRD §3.3: "Each assignment tracks three read-only counters:
        `document_count`, the number of linked documents not in `VOID` status;
        `verified_count`, the number of linked documents in `VERIFIED` status; and
        `revision_count`, which starts at 0 and increments by one each time the
        assignment is returned for correction."
        PRD §3.4: "Each recording recomputes the assignment's `document_count`."

        Design: Difficulty/compensating_invariant/document_create_then_void_conserves_assignment_document_count
        """
        ctx = setup_order_with_assignment("client_782", "abs_782")
        assert ctx["assignment"]["document_count"] == 0

        create_document(
            ctx["order"]["id"],
            ctx["assignment"]["id"],
            "abs_782",
            instrument_type="EASEMENT",
            grantor_name="B Jones",
            grantee_name="City of Austin",
            instrument_number="INST-782-A",
            recording_date="2005-06-30",
            exception_applies=True,
        )
        refreshed = get_assignment(ctx["assignment"]["id"])
        assert_search_assignment(refreshed)
        assert refreshed["document_count"] == 1, "create must move the count 0 -> 1"

    def test_voiding_document_restores_assignment_document_count(self, api):
        """PRD §3.4: "Voiding moves a mistakenly recorded document from `REPORTED`
        to `VOID`; voiding is available both to the assigned abstracter and to an
        `OperationsManager`, accepts an optional `reason`, and recomputes the
        assignment's `document_count` — record-then-void is a compensating pair
        that leaves `document_count` unchanged."

        Design: Difficulty/compensating_invariant/document_create_then_void_conserves_assignment_document_count
        """
        ctx = setup_order_with_assignment("client_782", "abs_782")
        doc = create_document(
            ctx["order"]["id"],
            ctx["assignment"]["id"],
            "abs_782",
            instrument_type="EASEMENT",
            grantor_name="B Jones",
            grantee_name="City of Austin",
            instrument_number="INST-782-A",
            recording_date="2005-06-30",
            exception_applies=True,
        )
        assert get_assignment(ctx["assignment"]["id"])["document_count"] == 1

        voided = api.void_record_document(
            doc["id"], {"reason": "duplicate entry, wrong instrument"},
            make_abstracter_headers("abs_782"),
        )
        void_doc = validate_success(voided, 200)
        assert void_doc["status"] == "VOID"

        restored = get_assignment(ctx["assignment"]["id"])
        assert restored["document_count"] == 0, (
            "create + void is a compensating pair restoring the exact prior count"
        )
