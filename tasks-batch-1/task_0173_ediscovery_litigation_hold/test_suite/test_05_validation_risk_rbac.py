"""Validation priority pairs, spoliation risk scoring, scope date overlap,
RBAC and request-shape validations.

Difficulty queue: priority_pair_validation_conflict (SoD>state, existence>temporal),
dual_variant_calc (spoliation provisional vs final), combinatorial_formula
(spoliation three-input nonlinear tier), resource_temporal_overlap (scope overlap).
Corner queue: matter create/validation, RBAC forbidden/unauthenticated, inverted
date range, pagination out of range, listing envelope, production-item immutability.
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    ApiErrorId,
    fixtures as fx,
)


class TestSpoliationRisk:
    def test_provisional_vs_final_diverge_on_pending_custodian(self, api):
        """PRD §3.3: "The provisional variant — displayed live during the
        acknowledgement window — counts every custodian whose ack_state is not
        ACKNOWLEDGED, so custodians still PENDING count as risk. The final variant —
        the value persisted as spoliation_risk_score — counts only custodians who
        have no HoldAcknowledgement record at all, excusing those who have a PENDING
        record."

        Design: Difficulty/dual_variant_calc/spoliation_risk_provisional_vs_final
        """
        fx.set_clock("2026-06-01T00:00:00Z")
        matter = fx.create_matter(caption="Risk Co", bates_prefix="RC")
        c1 = fx.create_custodian(matter["id"], full_name="Alice", email="a@x.com")
        fx.create_custodian(matter["id"], full_name="Bob", email="b@x.com")
        hold = fx.create_hold(matter["id"], ack_deadline="2026-06-20T00:00:00Z")
        fx.issue_hold(hold["id"])
        ack_id = fx.acknowledgement_id_for(c1["id"])
        fx.acknowledge(ack_id, c1["id"])  # c1 ACKNOWLEDGED, c2 still PENDING
        fx.set_clock("2026-06-11T00:00:00Z")  # 10 days since issue
        resp = api.get_matter_risk(matter["id"], fx.LEGALOPS)
        data = validate_success(resp, 200)
        # provisional: U=1 (c2 PENDING) -> base=15+20=35, R<100 mult 1.0 -> 35
        assert data["provisional_risk"] == 35, f"got {data['provisional_risk']}"
        # final: U=0 (both have ack records) -> base=0+20=20 -> 20
        assert data["final_risk"] == 20, f"got {data['final_risk']}"

    def test_three_input_nonlinear_tier_caps_days_at_thirty(self, api):
        """PRD §3.3: "the day contribution is capped — the day term uses the smaller
        of D and 30, so days beyond the thirtieth add nothing."

        Design: Difficulty/combinatorial_formula/spoliation_risk_three_input_nonlinear_tier
        """
        fx.set_clock("2026-06-01T00:00:00Z")
        matter = fx.create_matter(caption="Tier Co", bates_prefix="TC")
        fx.create_custodian(matter["id"], full_name="Al", email="a@x.com")
        fx.create_custodian(matter["id"], full_name="Bo", email="b@x.com")
        hold = fx.create_hold(matter["id"], ack_deadline="2026-06-10T00:00:00Z")
        fx.issue_hold(hold["id"])  # 2 custodians, both PENDING
        fx.set_clock("2026-07-15T00:00:00Z")  # >30 days since issue
        resp = api.get_matter_risk(matter["id"], fx.LEGALOPS)
        data = validate_success(resp, 200)
        # provisional: U=2 (both PENDING), D capped 30 -> base = 30+60 = 90, mult 1.0
        assert data["provisional_risk"] == 90, f"got {data['provisional_risk']}"
        # final: U=0 (both have PENDING records, excused) -> base = 0+60 = 60
        assert data["final_risk"] == 60, f"got {data['final_risk']}"

    def test_provisional_includes_pending_custodian_as_risk(self, api):
        """PRD §3.3: "The provisional variant — displayed live during the
        acknowledgement window — counts every custodian whose ack_state is not
        ACKNOWLEDGED, so custodians still PENDING count as risk."

        Design: Difficulty/dual_variant_calc/spoliation_risk_provisional_vs_final
        """
        fx.set_clock("2026-06-01T00:00:00Z")
        matter = fx.create_matter(caption="Risk2 Co", bates_prefix="RD")
        fx.create_custodian(matter["id"], full_name="Alice", email="a@x.com")
        hold = fx.create_hold(matter["id"], ack_deadline="2026-06-20T00:00:00Z")
        fx.issue_hold(hold["id"])  # 1 custodian PENDING, no acknowledge
        # Read risk on the issue day (D=0): provisional U=1 -> base=15, final U=0 -> 0.
        resp = api.get_matter_risk(matter["id"], fx.LEGALOPS)
        data = validate_success(resp, 200)
        assert data["provisional_risk"] == 15, (
            f"PENDING custodian counts as risk in provisional, got {data['provisional_risk']}"
        )
        assert data["final_risk"] == 0, (
            f"PENDING custodian excused in final, got {data['final_risk']}"
        )

    def test_day_term_uncapped_below_thirty_days(self, api):
        """PRD §3.3: "The base is fifteen points for each unacknowledged custodian
        plus two points for each day since issuance, where the day contribution is
        capped — the day term uses the smaller of D and 30, so days beyond the
        thirtieth add nothing."

        Design: Difficulty/combinatorial_formula/spoliation_risk_three_input_nonlinear_tier
        """
        fx.set_clock("2026-06-01T00:00:00Z")
        matter = fx.create_matter(caption="Tier2 Co", bates_prefix="TD")
        fx.create_custodian(matter["id"], full_name="Al", email="a@x.com")
        hold = fx.create_hold(matter["id"], ack_deadline="2026-06-10T00:00:00Z")
        fx.issue_hold(hold["id"])  # 1 custodian PENDING
        fx.set_clock("2026-06-11T00:00:00Z")  # exactly 10 days (< 30, uncapped)
        resp = api.get_matter_risk(matter["id"], fx.LEGALOPS)
        data = validate_success(resp, 200)
        # provisional: U=1, D=10 -> base = 15 + 20 = 35, R<100 mult 1.0
        assert data["provisional_risk"] == 35, (
            f"uncapped 10-day term: 15+20=35, got {data['provisional_risk']}"
        )
        # final: U=0 -> base = 0 + 20 = 20
        assert data["final_risk"] == 20, f"got {data['final_risk']}"


class TestPriorityConflicts:
    def test_produce_sod_403_beats_state_409(self, api):
        """PRD §3.7: "It is also the point where segregation of duties is enforced:
        the producing operator's X-User-ID must not equal the reviewer_user_id
        recorded on any document review covering a document in this set; if it does,
        the production is rejected with ERR_SEGREGATION_OF_DUTIES."
        PRD §2.8: "Only after a resource is confirmed to exist is its state checked: if
        the resource is not in a state from which the requested transition is defined,
        the request is rejected with ERR_INVALID_STATE."

        Design: Difficulty/priority_pair_validation_conflict/produce_sod_403_beats_state_409
        """
        # A DRAFT (not STAGED) set whose document was decided by reviewer rv-1;
        # produce attempted by Producer acting as rv-1: both SoD(403) and state(409)
        # apply; SoD wins.
        base = fx.setup_matter_with_acknowledged_custodian(
            caption="SoD Co", bates_prefix="SD", email="a@x.com",
        )
        m_id, c_id = base["matter"]["id"], base["custodian"]["id"]
        scope, docs, _job = fx.setup_processed_scope(m_id, c_id, ["h1"], expected_doc_count=1)
        batch, _reviews = fx.setup_completed_batch(
            m_id, docs, ["RESPONSIVE_NOT_PRIV"], reviewer_user_id="rv-1",
        )
        ps = fx.create_production_set(m_id, batch["id"])
        fx.add_item(ps["id"], docs[0]["id"])  # set stays DRAFT
        # produce as rv-1 (same operator who decided the doc).
        resp = api.produce_production_set(
            ps["id"],
            {"X-User-ID": "rv-1", "X-User-Role": "Producer", "Content-Type": "application/json"},
        )
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403)

    def test_scope_create_existence_404_beats_temporal_422(self, api):
        """PRD §2.8: "Existence of all path and foreign-key-referenced resources
        (ERR_NOT_FOUND) is verified next, evaluated left to right so that the first
        identifier in the request that names no existing resource is the one reported."
        PRD §3.4: "The range_start must be strictly before range_end; a start that is
        not strictly before the end is rejected with ERR_INVALID_DATE_RANGE."

        Design: Difficulty/priority_pair_validation_conflict/scope_create_existence_404_beats_temporal_422
        """
        matter = fx.create_matter(caption="Safe Co", bates_prefix="SF")
        # Non-existent custodian_id (existence) AND empty date range (temporal):
        # existence (404) is higher priority than temporal (422).
        resp = api.create_collection_scope(
            {
                "matter_id": matter["id"],
                "custodian_id": "00000000-0000-4000-8000-000000000099",
                "source_label": "Mbx",
                "range_start": "2026-06-01T00:00:00Z",
                "range_end": "2026-06-01T00:00:00Z",
                "expected_doc_count": 1,
            },
            fx.LEGALOPS,
        )
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value, 404)

    def test_produce_by_deciding_reviewer_on_staged_set_rejected(self, api):
        """PRD §3.7: "It is also the point where segregation of duties is enforced:
        the producing operator's X-User-ID must not equal the reviewer_user_id
        recorded on any document review covering a document in this set; if it does,
        the production is rejected with ERR_SEGREGATION_OF_DUTIES."

        Design: Difficulty/priority_pair_validation_conflict/produce_sod_403_beats_state_409
        """
        # A correctly STAGED set (no state conflict) still rejects the deciding
        # reviewer at produce — isolating the segregation-of-duties rule itself.
        base = fx.setup_matter_with_acknowledged_custodian(
            caption="SoD2 Co", bates_prefix="SE", email="a@x.com",
        )
        m_id, c_id = base["matter"]["id"], base["custodian"]["id"]
        scope, docs, _job = fx.setup_processed_scope(m_id, c_id, ["h1"], expected_doc_count=1)
        batch, _reviews = fx.setup_completed_batch(
            m_id, docs, ["RESPONSIVE_NOT_PRIV"], reviewer_user_id="rv-9",
        )
        ps = fx.create_production_set(m_id, batch["id"])
        fx.add_item(ps["id"], docs[0]["id"])
        fx.validate_set(ps["id"])  # STAGED
        resp = api.produce_production_set(
            ps["id"],
            {"X-User-ID": "rv-9", "X-User-Role": "Producer", "Content-Type": "application/json"},
        )
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403)

    def test_scope_create_nonexistent_matter_reported_first(self, api):
        """PRD §2.8: "Existence of all path and foreign-key-referenced resources
        (ERR_NOT_FOUND) is verified next, evaluated left to right so that the first
        identifier in the request that names no existing resource is the one reported."

        Design: Difficulty/priority_pair_validation_conflict/scope_create_existence_404_beats_temporal_422
        """
        # Non-existent matter_id (existence) plus an inverted range (temporal):
        # existence still pre-empts the temporal field-shape check.
        resp = api.create_collection_scope(
            {
                "matter_id": "00000000-0000-4000-8000-000000000088",
                "custodian_id": "00000000-0000-4000-8000-000000000099",
                "source_label": "Mbx",
                "range_start": "2026-06-10T00:00:00Z",
                "range_end": "2026-06-01T00:00:00Z",
                "expected_doc_count": 1,
            },
            fx.LEGALOPS,
        )
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value, 404)


class TestScopeDateOverlap:
    def test_overlapping_scope_for_same_custodian_rejected(self, api):
        """PRD §3.4: "two scopes for the same custodian on the same matter may not
        have overlapping windows; because the interval is half-open, one scope's
        window touching another exactly at the shared boundary instant does not
        overlap, but any genuine overlap is rejected with ERR_SCOPE_DATE_OVERLAP."

        Design: Difficulty/resource_temporal_overlap/scope_date_range_half_open_overlap
        """
        matter = fx.create_matter(caption="Ovl Co", bates_prefix="OV")
        custodian = fx.create_custodian(matter["id"], email="a@x.com")
        fx.create_scope(
            matter["id"], custodian["id"], source_label="Mbx",
            range_start="2026-06-01T00:00:00Z", range_end="2026-06-30T00:00:00Z",
            expected_doc_count=1,
        )
        # Second scope [2026-06-15, 2026-07-15) genuinely overlaps [06-01, 06-30).
        resp = api.create_collection_scope(
            {
                "matter_id": matter["id"], "custodian_id": custodian["id"],
                "source_label": "Mbx2",
                "range_start": "2026-06-15T00:00:00Z",
                "range_end": "2026-07-15T00:00:00Z",
                "expected_doc_count": 1,
            },
            fx.LEGALOPS,
        )
        validate_error(resp, ApiErrorId.ERR_SCOPE_DATE_OVERLAP.value, 409)

    def test_adjacent_scope_at_shared_boundary_not_overlap(self, api):
        """PRD §3.4: "Furthermore, two scopes for the same custodian on the same
        matter may not have overlapping windows; because the interval is half-open,
        one scope's window touching another exactly at the shared boundary instant
        does not overlap, but any genuine overlap is rejected with
        ERR_SCOPE_DATE_OVERLAP."

        Design: Difficulty/resource_temporal_overlap/scope_date_range_half_open_overlap
        """
        matter = fx.create_matter(caption="Adj Co", bates_prefix="AJ")
        custodian = fx.create_custodian(matter["id"], email="a@x.com")
        fx.create_scope(
            matter["id"], custodian["id"], source_label="Mbx",
            range_start="2026-06-01T00:00:00Z", range_end="2026-06-30T00:00:00Z",
            expected_doc_count=1,
        )
        # Second scope starts exactly at the prior end: [06-30, 07-15) — no overlap.
        resp = api.create_collection_scope(
            {
                "matter_id": matter["id"], "custodian_id": custodian["id"],
                "source_label": "Mbx2",
                "range_start": "2026-06-30T00:00:00Z",
                "range_end": "2026-07-15T00:00:00Z",
                "expected_doc_count": 1,
            },
            fx.LEGALOPS,
        )
        validate_success(resp, 201)


class TestScopeShapeValidation:
    def test_scope_inverted_date_range_rejected(self, api):
        """PRD §3.4: "The range_start must be strictly before range_end; a start that
        is not strictly before the end is rejected with ERR_INVALID_DATE_RANGE."

        Design: Corner/validations/scope_inverted_date_range_rejected
        """
        matter = fx.create_matter(caption="IDR Co", bates_prefix="ID")
        custodian = fx.create_custodian(matter["id"], email="a@x.com")
        resp = api.create_collection_scope(
            {
                "matter_id": matter["id"], "custodian_id": custodian["id"],
                "source_label": "Mbx",
                "range_start": "2026-06-01T00:00:00Z",
                "range_end": "2026-06-01T00:00:00Z",  # start == end
                "expected_doc_count": 1,
            },
            fx.LEGALOPS,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_DATE_RANGE.value, 422)


class TestMatterCreation:
    def test_create_matter_returns_201_with_system_fields(self, api):
        """PRD §3.1: "A new matter begins with its lifecycle axis (lifecycle_status)
        at OPEN and its hold axis (hold_status) at NO_HOLD, with next_bates_seq
        initialized to 1."

        Design: Corner/entities/create_matter_returns_201_with_system_fields
        """
        resp = api.create_matter(
            {"caption": "Acme v Beta", "bates_prefix": "ABC"}, fx.LEGALOPS
        )
        data = validate_success(resp, 201)
        assert data["lifecycle_status"] == "OPEN", f"got {data['lifecycle_status']}"
        assert data["hold_status"] == "NO_HOLD", f"got {data['hold_status']}"
        assert data["next_bates_seq"] == 1, f"got {data['next_bates_seq']}"
        assert data["version"] == 1, f"got {data['version']}"

    def test_create_matter_missing_bates_prefix_rejected(self, api):
        """PRD §3.1: "A LegalOps operator opens the case file by creating a Matter
        with a caption (the case name, a non-empty string of 1 to 200 characters) and
        a bates_prefix."

        Design: Corner/entities/create_matter_missing_bates_prefix_returns_invalid_request
        """
        resp = api.create_matter({"caption": "No Prefix"}, fx.LEGALOPS)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value, 422)

    def test_create_matter_lowercase_bates_prefix_rejected(self, api):
        """PRD §3.1: "The bates_prefix must consist of uppercase letters only and be
        1 to 8 characters long; a prefix that violates this shape is rejected with
        ERR_INVALID_REQUEST, and the prefix is immutable once the matter is created."

        Design: Corner/entities/create_matter_bad_bates_prefix_lowercase_rejected
        """
        resp = api.create_matter(
            {"caption": "Bad Prefix", "bates_prefix": "abc"}, fx.LEGALOPS
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value, 422)

    def test_get_matter_nonexistent_returns_not_found(self, api):
        """PRD §2.8: "Existence of all path and foreign-key-referenced resources
        (ERR_NOT_FOUND) is verified next, evaluated left to right so that the first
        identifier in the request that names no existing resource is the one reported."

        Design: Corner/entities/get_matter_nonexistent_returns_not_found
        """
        resp = api.get_matter("00000000-0000-4000-8000-000000000000", fx.LEGALOPS)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value, 404)

    def test_list_matters_pagination_envelope(self, api):
        """PRD §2.3: "List responses include the following fields in the meta object
        of the envelope: limit, offset, total_count, and has_more."

        Design: Corner/entities/list_matters_pagination_envelope
        """
        fx.create_matter(caption="M1", bates_prefix="AA")
        resp = api.list_matters(fx.LEGALOPS, params={"limit": 10, "offset": 0})
        data, meta = validate_paginated(resp)
        assert "total_count" in meta and "has_more" in meta
        assert isinstance(data, list)

    def test_production_item_has_no_version_field(self, api):
        """PRD §2.4: "The ProductionItem resource is a lightweight join record and
        does not carry the full common-field set: it has only an id and a created_at.
        It has no updated_at and no version field."

        Design: Corner/entities/production_item_immutable_no_version_field
        """
        bundle = fx.setup_produced_set_from_responsive_docs(
            caption="PItem Co", bates_prefix="PI", num_docs=1,
        )
        item_id = bundle["items"][0]["id"]
        item = get_success_data(api.get_production_item(item_id, fx.PRODUCER))
        assert "version" not in item, "ProductionItem must not carry a version field"
        assert "updated_at" not in item, "ProductionItem must not carry updated_at"
        assert "created_at" in item, "ProductionItem must carry created_at"


class TestPagination:
    def test_pagination_limit_out_of_range_rejected(self, api):
        """PRD §2.3: "The limit parameter caps how many items are returned; it
        defaults to 10 when omitted, with a minimum of 1 and a maximum of 100."
        PRD §2.3: "A limit or offset outside its permitted range is rejected with
        ERR_VALIDATION_OUT_OF_RANGE."

        Design: Corner/validations/pagination_limit_out_of_range_rejected
        """
        resp = api.list_matters(fx.LEGALOPS, params={"limit": 500})
        validate_error(resp, ApiErrorId.ERR_VALIDATION_OUT_OF_RANGE.value, 422)


class TestRbac:
    def test_custodian_cannot_create_matter_forbidden(self, api):
        """PRD §2.1: "When an authenticated user invokes an endpoint their role is not
        permitted to call, the request is rejected with ERR_FORBIDDEN_ROLE."

        Design: Corner/rbac/custodian_cannot_create_matter_forbidden
        """
        custodian_headers = fx.make_custodian_headers("00000000-0000-4000-8000-000000000001")
        resp = api.create_matter(
            {"caption": "M", "bates_prefix": "AA"}, custodian_headers
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value, 403)

    def test_producer_cannot_decide_review_forbidden(self, api):
        """PRD §2.1: "When an authenticated user invokes an endpoint their role is not
        permitted to call, the request is rejected with ERR_FORBIDDEN_ROLE."

        Design: Corner/rbac/producer_cannot_decide_review_forbidden
        """
        base = fx.setup_matter_with_acknowledged_custodian(
            caption="RB Co", bates_prefix="RB", email="a@x.com",
        )
        m_id, c_id = base["matter"]["id"], base["custodian"]["id"]
        scope, docs, _job = fx.setup_processed_scope(m_id, c_id, ["h1"], expected_doc_count=1)
        batch = fx.create_batch(m_id, name="B1")
        review = fx.add_review(batch["id"], docs[0]["id"])
        fx.open_review(batch["id"])
        # A Producer invoking the Reviewer-exclusive decide endpoint.
        resp = api.decide_review(
            review["id"],
            {"decision": "RESPONSIVE_NOT_PRIV"},
            {"X-User-ID": "pr-1", "X-User-Role": "Producer", "Content-Type": "application/json"},
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value, 403)

    def test_missing_headers_unauthenticated(self, api):
        """PRD §2.1: "If either header is missing, or if X-User-Role does not name one
        of the recognized roles, the request is rejected with ERR_UNAUTHENTICATED."

        Design: Corner/rbac/missing_headers_unauthenticated
        """
        resp = api.list_matters({"Content-Type": "application/json"})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)
