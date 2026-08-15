"""Creation defaults, request-shape validation, 404s, and the response
envelope (including pagination and immediate-consistency reads)."""
import pytest

from test_helpers import (
    ADMIN,
    DETAILER,
    FOREMAN,
    NON_EXISTENT_UUID,
    ApiErrorId,
    api_client,
    assert_job,
    assert_piece,
    assert_shop_drawing,
    create_drawing,
    create_job,
    create_job_payload,
    create_piece_payload,
    create_sequence,
    make_detailer_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestJobCreationDefaults:

    def test_job_creation_defaults_applied(self):
        """PRD section 3.1: "A new job opens in `ESTIMATING` with every
        aggregate at zero, and the job register can be listed with an optional
        `status` filter or read individually with its computed aggregates."
        PRD section 3.1: "The optional `requires_aisc_hold` flag defaults to
        false; when set true, no load of the job may ship until a passed AISC
        audit inspection exists for the job (§3.7)."
        PRD section 3.1: "`retainage_releasable_cents` sits at zero through
        the job's whole life until the moment it auto-completes, when it is set
        equal to the then-current `retainage_held_cents` — the amount the
        fabricator may now bill for release."

        Design: Corner/entities/job_creation_defaults_applied
        """
        resp = api_client.create_job(
            create_job_payload(name="Job D"), ADMIN
        )
        data = validate_success(resp, expected_status=201)
        assert_job(data)
        assert data["status"] == "ESTIMATING", \
            f"new job must open in ESTIMATING, got {data['status']}"
        assert data["requires_aisc_hold"] is False, \
            "omitted requires_aisc_hold must default to false"
        for field in ("total_weight_lbs", "erected_weight_lbs",
                      "billed_to_date_cents", "retainage_held_cents",
                      "pending_backcharge_cents", "settled_backcharge_cents",
                      "retainage_releasable_cents"):
            assert data[field] == 0, \
                f"new job aggregate {field} must start at 0, got {data[field]}"
        assert data["pct_complete"] == pytest.approx(0.0, abs=1e-9)


class TestShopDrawingCreation:

    def test_shop_drawing_creation_revision_one(self, detailer_headers):
        """PRD section 3.2: "A drawing begins when a `DETAILER` creates it
        against a `job_id` with a `drawing_number`. The first revision is
        numbered 1 and opens in `DRAFT`."
        PRD section 3.2: "A successful revise creates a brand-new drawing row:
        its `revision` is the source's revision plus one, its `supersedes_id`
        is the source's `id`, and it opens in `DRAFT` ready for its own
        submit-decide cycle."

        Design: Corner/entities/shop_drawing_creation_revision_one
        """
        job = create_job("Job E")
        resp = api_client.create_shop_drawing(
            {"job_id": job["id"], "drawing_number": "D-100"}, DETAILER
        )
        data = validate_success(resp, expected_status=201)
        assert_shop_drawing(data)
        assert data["revision"] == 1, \
            f"first revision must be numbered 1, got {data['revision']}"
        assert data["status"] == "DRAFT"
        assert data["supersedes_id"] is None, \
            "a first revision has no source, so supersedes_id must be null"

        got = validate_success(
            api_client.get_shop_drawing(data["id"], detailer_headers)
        )
        assert got["id"] == data["id"]
        assert got["revision"] == 1
        assert got["status"] == "DRAFT"


class TestPieceCreationComputedFields:

    def test_piece_stale_revision_input_ignored(self):
        """PRD section 3.4: "A new piece opens in `DETAILED` with
        `stale_revision` false and `load_id` null, and its creation immediately
        recomputes the job's `total_weight_lbs`."

        Design: Corner/entities/piece_stale_revision_input_ignored
        """
        job = create_job("Job G")
        drawing = create_drawing(job["id"], "D-1")
        sequence = create_sequence(job["id"], 1)
        payload = create_piece_payload(
            job["id"], drawing["id"], sequence["id"],
            piece_mark="G-P1", weight_lbs=800,
        )
        payload["stale_revision"] = True  # computed field; must be ignored
        resp = api_client.create_piece(payload, FOREMAN)
        data = validate_success(resp, expected_status=201)
        assert_piece(data)
        assert data["stale_revision"] is False, \
            "a new piece opens with stale_revision false regardless of input"
        assert data["load_id"] is None
        assert data["status"] == "DETAILED"


class TestRequestShapeValidation:

    def test_invalid_enum_value_rejected(self):
        """PRD section 2.8: "Missing required fields, wrong types, out-of-range
        enum values, non-positive integers where a positive value is required,
        an empty `repair_lines` array, or a `window_end` that is not strictly
        after its `window_start` fail as `ERR_INVALID_REQUEST` (HTTP 400)."
        PRD section 3.1: "A `FABRICATOR_ADMIN` creates one with a `name`, a
        `contract_value_cents` that must be a positive integer, and a
        `billing_basis` of either `WEIGHT` or `COUNT` — a permanent choice that
        selects which percent-complete variant every billing of the job will
        use."

        Design: Corner/entities/invalid_enum_value_rejected
        """
        resp = api_client.create_job(
            create_job_payload(name="Job H", billing_basis="TONS"), ADMIN
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_missing_required_field_rejected(self):
        """PRD section 2.8: "Missing required fields, wrong types, out-of-range
        enum values, non-positive integers where a positive value is required,
        an empty `repair_lines` array, or a `window_end` that is not strictly
        after its `window_start` fail as `ERR_INVALID_REQUEST` (HTTP 400)."
        PRD section 3.1: "A `FABRICATOR_ADMIN` creates one with a `name`, a
        `contract_value_cents` that must be a positive integer, and a
        `billing_basis` of either `WEIGHT` or `COUNT` — a permanent choice that
        selects which percent-complete variant every billing of the job will
        use."

        Design: Corner/entities/missing_required_field_rejected
        """
        resp = api_client.create_job(
            {"name": "Job H2", "billing_basis": "WEIGHT"}, ADMIN
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestReferenceResolution:

    def test_unknown_id_returns_not_found(self, fabricator_admin_headers):
        """PRD section 2.8: "Path identifiers are validated left to right —
        for a path carrying both a load `id` and a `piece_id`, the load
        resolves first — and the first identifier that does not resolve fails
        as `ERR_NOT_FOUND` (HTTP 404)."

        Design: Corner/entities/unknown_id_returns_not_found
        """
        resp = api_client.get_job(NON_EXISTENT_UUID, fabricator_admin_headers)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestListPagination:

    def test_list_pagination_envelope(self, detailer_headers):
        """PRD section 2.3: "List responses carry four pagination fields in the
        `meta` object of the response envelope: `limit`, `offset`,
        `total_count`, and `has_more`."
        PRD section 2.3: "The `limit` parameter caps how many items come back;
        it defaults to 10, accepts a minimum of 1, and is capped at a maximum
        of 100. The `offset` parameter states how many items to skip and
        defaults to 0."

        Design: Corner/entities/list_pagination_envelope
        """
        create_job("Job P")
        create_job("Job Q", contract_value_cents=20_000_000,
                   billing_basis="COUNT")

        page1, meta1 = validate_paginated(
            api_client.list_jobs(detailer_headers, params={"limit": 1,
                                                           "offset": 0})
        )
        assert len(page1) == 1, f"limit=1 must return one row, got {len(page1)}"
        assert meta1["total_count"] == 2
        assert meta1["has_more"] is True
        assert meta1["limit"] == 1
        assert meta1["offset"] == 0

        page2, meta2 = validate_paginated(
            api_client.list_jobs(detailer_headers, params={"limit": 1,
                                                           "offset": 1})
        )
        assert len(page2) == 1
        assert meta2["total_count"] == 2
        assert meta2["has_more"] is False
        assert page1[0]["id"] != page2[0]["id"], \
            "the two pages must carry different jobs"


class TestImmediateConsistency:

    def test_mutation_visible_in_same_response(self):
        """PRD section 2.4: "Recomputation is immediate: a response to any
        mutating request reflects every derived value the mutation touched,
        with no eventual-consistency window."
        PRD section 3.2: "Submission moves a drawing from `DRAFT` to
        `SUBMITTED` and captures the caller as `submitted_by_user_id`."

        Design: Corner/consistency_model/mutation_visible_in_same_response
        """
        job = create_job("Job CM1")
        drawing = create_drawing(job["id"], "D-1")
        resp = api_client.submit_drawing(
            drawing["id"], make_detailer_headers("det-1")
        )
        data = validate_success(resp, expected_status=200)
        assert_shop_drawing(data)
        assert data["status"] == "SUBMITTED", \
            "the submit response itself must carry status SUBMITTED"
        assert data["submitted_by_user_id"] == "det-1", \
            "the submit response itself must carry submitted_by_user_id"
