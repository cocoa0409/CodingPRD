"""Shop drawing revision cycle: invalid transitions, uniqueness, the OCC
token on revise, and the supersede cascade into pieces and loads."""
from test_helpers import (
    ADMIN,
    DETAILER,
    EOR,
    FOREMAN,
    ApiErrorId,
    api_client,
    add_line,
    create_approved_drawing,
    create_drawing,
    create_job,
    create_load,
    create_piece,
    create_ready_to_ship_piece,
    revise_and_approve_drawing,
    revise_drawing,
    setup_fabrication_ready,
    submit_drawing,
    validate_error,
    validate_success,
)


class TestDrawingInvalidTransitions:

    def test_drawing_decide_from_draft_rejected(self):
        """PRD section 2.8: "The target entity must be in a valid from-state
        for the requested transition — including a mill order placed only
        against a job that is not `ESTIMATING`, load line edits only while the
        load is `STAGING` or `LOADING`, and a field fix reported only on a
        `SHIPPED` or `ERECTED` piece — failing as `ERR_INVALID_STATE`
        (HTTP 409)."
        PRD section 4: "Approve or reject a submitted drawing; approval fires
        the supersede and staleness cascade" — decide applies to a SUBMITTED
        drawing only.

        Design: Corner/state_machines/drawing_decide_from_draft_rejected
        """
        job = create_job("Job SM1")
        drawing = create_drawing(job["id"], "D-1")
        resp = api_client.decide_drawing(
            drawing["id"], {"decision": "APPROVE"}, EOR
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        after = validate_success(api_client.get_shop_drawing(drawing["id"], EOR))
        assert after["status"] == "DRAFT", \
            "a rejected decide must leave the drawing DRAFT"

    def test_drawing_double_submit_rejected(self):
        """PRD section 3.2: "Submission moves a drawing from `DRAFT` to
        `SUBMITTED` and captures the caller as `submitted_by_user_id`."
        PRD section 2.8: "The target entity must be in a valid from-state for
        the requested transition — including a mill order placed only against a
        job that is not `ESTIMATING`, load line edits only while the load is
        `STAGING` or `LOADING`, and a field fix reported only on a `SHIPPED` or
        `ERECTED` piece — failing as `ERR_INVALID_STATE` (HTTP 409)."

        Design: Corner/state_machines/drawing_double_submit_rejected
        """
        job = create_job("Job SM2")
        drawing = create_drawing(job["id"], "D-1")
        submit_drawing(drawing["id"])
        resp = api_client.submit_drawing(drawing["id"], DETAILER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestDrawingUniqueness:

    def test_duplicate_drawing_number_rejected(self):
        """PRD section 3.2: "The triple of `job_id`, `drawing_number`, and
        `revision` must be unique; a collision is rejected with
        `ERR_DRAWING_NOT_UNIQUE`."

        Design: Corner/errors/duplicate_drawing_number_rejected
        """
        job = create_job("Job ER5")
        create_drawing(job["id"], "D-1")
        resp = api_client.create_shop_drawing(
            {"job_id": job["id"], "drawing_number": "D-1"}, DETAILER
        )
        validate_error(resp, ApiErrorId.ERR_DRAWING_NOT_UNIQUE)


class TestDrawingReviseOcc:

    def test_occ_stale_drawing_revise_rejected(self):
        """PRD section 2.7: "Revising a shop drawing requires the request to
        carry `expected_drawing_version`, holding the source drawing's
        `version` as the client last observed it. If that value does not match
        the drawing's current `version` — because, for instance, another writer
        has already cut the next revision from the same source — the request is
        rejected with `ERR_STALE_VERSION` (HTTP 412)."
        PRD section 3.2: "The act of revising also increments the source
        drawing's `version` by one, which is exactly what makes a second
        client's stale `expected_drawing_version` detectable."

        Design: Corner/validations/occ_stale_drawing_revise_rejected
        """
        job = create_job("Job V5")
        drawing = create_approved_drawing(job["id"], "D-1")
        observed = validate_success(
            api_client.get_shop_drawing(drawing["id"], DETAILER)
        )
        first = revise_drawing(drawing["id"], observed["version"])
        assert first["revision"] == 2, \
            f"new revision must be source revision + 1, got {first['revision']}"
        assert first["status"] == "DRAFT"
        assert first["supersedes_id"] == drawing["id"]
        # Replaying the same observed version is stale: the first revise
        # already advanced the source drawing's version.
        resp = api_client.revise_drawing(
            drawing["id"], {"expected_drawing_version": observed["version"]},
            DETAILER,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


class TestSupersedeCascade:

    def _setup_piece_on_load(self):
        """Piece READY_TO_SHIP and loaded; its pinned drawing is APPROVED."""
        ctx = setup_fabrication_ready("Job S")
        piece = create_ready_to_ship_piece(ctx, "S-P1", 5000)
        load = create_load(ctx["job"]["id"], load_number="L-S1",
                           laydown_slot="Y-S", trailer_capacity_lbs=20000)
        add_line(load["id"], piece["id"])
        return ctx, piece, load

    def test_supersede_marks_piece_stale_and_strips_load(self):
        """PRD section 3.2: "If the newly approved drawing's `supersedes_id`
        points at a revision still in `APPROVED`, that predecessor moves to
        `SUPERSEDED`. Every piece pinned to the superseded revision via
        `drawing_id` whose status is not `SHIPPED` or `ERECTED` has its
        `stale_revision` flag set to true — pieces already shipped or standing
        are grandfathered and stay clean."
        PRD section 3.2: "Any piece thus marked stale that was sitting on a
        shipping load is pulled off: its `load_id` is cleared to null, the
        load's `total_weight_lbs` is recomputed, and if that load was in
        `LOADING` and now holds no lines at all, it falls back to `STAGING`."

        Design: Difficulty/transitive_cascade/drawing_supersede_load_cascade
        """
        ctx, piece, load = self._setup_piece_on_load()
        new_rev = revise_and_approve_drawing(ctx["drawing"]["id"])
        assert new_rev["status"] == "APPROVED"
        assert new_rev["revision"] == 2

        old = validate_success(
            api_client.get_shop_drawing(ctx["drawing"]["id"], DETAILER)
        )
        assert old["status"] == "SUPERSEDED", (
            f"approving the next revision must supersede the predecessor, "
            f"got {old['status']}"
        )

        piece_after = validate_success(api_client.get_piece(piece["id"], FOREMAN))
        assert piece_after["stale_revision"] is True, \
            "piece pinned to the superseded revision must turn stale"
        assert piece_after["load_id"] is None, \
            "a stale piece must be pulled off its load (load_id null)"

    def test_supersede_empties_load_back_to_staging(self):
        """PRD section 3.2: "Any piece thus marked stale that was sitting on a
        shipping load is pulled off: its `load_id` is cleared to null, the
        load's `total_weight_lbs` is recomputed, and if that load was in
        `LOADING` and now holds no lines at all, it falls back to `STAGING`."

        Design: Difficulty/transitive_cascade/drawing_supersede_load_cascade
        """
        ctx, piece, load = self._setup_piece_on_load()
        revise_and_approve_drawing(ctx["drawing"]["id"])

        load_after = validate_success(
            api_client.get_shipping_load(load["id"], FOREMAN)
        )
        assert load_after["total_weight_lbs"] == 0, (
            f"stripped load must recompute to 0 lbs, "
            f"got {load_after['total_weight_lbs']}"
        )
        assert load_after["status"] == "STAGING", (
            f"an emptied LOADING load must fall back to STAGING, "
            f"got {load_after['status']}"
        )
        lines = validate_success(api_client.list_load_lines(load["id"], FOREMAN))
        assert lines == [], f"the emptied load must list no lines, got {lines}"


class TestStalePieceStart:

    def test_stale_piece_start_rejected(self):
        """PRD section 3.4: "Four conditions guard the start, evaluated in this
        order: the piece's `stale_revision` must be false
        (`ERR_PIECE_STALE_REVISION` — a piece detailed from a superseded
        revision must be re-pinned before it can be worked); the pinned drawing
        must be `APPROVED` (`ERR_DRAWING_NOT_APPROVED`); the piece's sequence
        must be `RELEASED` (`ERR_SEQUENCE_NOT_RELEASED`); and at least one mill
        order of the job must be `RECEIVED` (`ERR_MATERIAL_NOT_RECEIVED`)."

        Design: Corner/endpoints/stale_piece_start_rejected
        """
        ctx = setup_fabrication_ready("Job EP2")
        piece = create_piece(
            ctx["job"]["id"], ctx["drawing"]["id"], ctx["sequence"]["id"],
            piece_mark="P1", weight_lbs=800,
        )
        # Approve revision 2: revision 1 is superseded and the piece goes stale.
        revise_and_approve_drawing(ctx["drawing"]["id"])

        stale = validate_success(api_client.get_piece(piece["id"], FOREMAN))
        assert stale["stale_revision"] is True

        resp = api_client.start_piece(piece["id"], FOREMAN)
        validate_error(resp, ApiErrorId.ERR_PIECE_STALE_REVISION)
        after = validate_success(api_client.get_piece(piece["id"], FOREMAN))
        assert after["status"] == "DETAILED", \
            "a rejected start must leave the piece DETAILED"
