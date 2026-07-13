"""Design workflow: auto-layout gates, the proofing revision loop, approval cascade, OCC."""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    create_customer, create_template, create_project, create_address,
    setup_laid_out_project, setup_project_in_proof,
    upload_photo, upload_n_photos, autolayout, generate_proof,
    make_customer_headers,
)


def _photo_statuses(api, project_id, headers):
    data, _ = validate_paginated(api.list_photos(project_id, headers))
    return [p["status"] for p in data]


class TestAutoLayoutBoundary:
    """photo_count floor at template.min_photos: 1 photo fails, 2 photos lay out."""

    def test_one_photo_below_min_rejected(self, api):
        """PRD 3.2: "the project's photo_count must be at least the template's min_photos, else
        ERR_INSUFFICIENT_PHOTOS (the empty-photo-set case is caught here)"

        Design: Difficulty/boundary_precision_check/autolayout_min_photos_boundary
        """
        cust = create_customer()
        h = make_customer_headers(cust["id"])
        tmpl = create_template(min_photos=2, max_photos=50)
        proj = create_project(cust, tmpl, headers=h)
        upload_photo(proj, h, filename="only.jpg")
        res = api.autolayout(proj["id"], h)
        validate_error(res, "ERR_INSUFFICIENT_PHOTOS", 422)

    def test_exactly_min_photos_lays_out(self, api):
        """PRD 3.2: "When all three gates pass, every photo moves from UPLOADED to PLACED, the
        project's placed_photo_count is recomputed as the number of photos in PLACED or LOCKED
        status, the project state becomes LAID_OUT, and the project version is bumped."

        Design: Difficulty/boundary_precision_check/autolayout_min_photos_boundary
        """
        cust = create_customer()
        h = make_customer_headers(cust["id"])
        tmpl = create_template(min_photos=2, max_photos=50)
        proj = create_project(cust, tmpl, headers=h)
        upload_n_photos(proj, h, n=2)
        data = validate_success(api.autolayout(proj["id"], h), 200)
        assert data["state"] == "LAID_OUT", f"2 photos meets the floor exactly, got {data['state']}"

    def test_autolayout_from_laid_out_rejected(self, api):
        """PRD 3.2: "It is admissible only while the project is in DRAFT; attempting it from any
        other state yields ERR_INVALID_PROJECT_STATE."

        Design: Corner/state_machines/corner_autolayout_from_laid_out_invalid
        """
        ctx = setup_laid_out_project()
        res = api.autolayout(ctx["proj"]["id"], ctx["headers"])
        validate_error(res, "ERR_INVALID_PROJECT_STATE", 409)

    def test_low_resolution_photo_rejected(self, api):
        """PRD 3.2: "every uploaded photo must have a dpi at least equal to the template's min_dpi,
        and if any single photo falls below that floor the entire request is rejected with
        ERR_PHOTO_LOW_RESOLUTION (individual photos are never partially placed — the layout succeeds
        or fails as a whole)."

        Design: Corner/validations/corner_photo_low_resolution_rejected
        """
        cust = create_customer()
        h = make_customer_headers(cust["id"])
        tmpl = create_template(min_photos=2, max_photos=50, min_dpi=150)
        proj = create_project(cust, tmpl, headers=h)
        upload_photo(proj, h, filename="hi.jpg", dpi=300)
        upload_photo(proj, h, filename="lo.jpg", width_px=800, height_px=600, dpi=100)
        res = api.autolayout(proj["id"], h)
        validate_error(res, "ERR_PHOTO_LOW_RESOLUTION", 422)

    def test_too_many_photos_rejected(self, api):
        """PRD 3.2: "and photo_count must be at most the template's max_photos, else
        ERR_TOO_MANY_PHOTOS."

        Design: Corner/validations/corner_too_many_photos_rejected
        """
        cust = create_customer()
        h = make_customer_headers(cust["id"])
        tmpl = create_template(product_type="CARD", base_unit_price_cents=500, surface_count=1,
                               production_days=1, min_photos=1, max_photos=2)
        proj = create_project(cust, tmpl, headers=h)
        upload_n_photos(proj, h, n=3)
        res = api.autolayout(proj["id"], h)
        validate_error(res, "ERR_TOO_MANY_PHOTOS", 422)


class TestProofApprovalCascade:
    """Approving the current proof cascades Proof -> Project -> Photo (depth 3)."""

    def test_approve_sets_proof_and_project_approved(self, api):
        """PRD 3.3: "Approval is the depth-three cascade of Section 2.9: the proof becomes APPROVED,
        then the project state becomes APPROVED, then every photo moves from PLACED to LOCKED, and
        the project version is bumped."

        Design: Difficulty/transitive_cascade/proof_approve_cascade_project_photo_lock
        """
        ctx = setup_project_in_proof()
        proof = validate_success(api.approve_proof(ctx["proof"]["id"], ctx["headers"]), 200)
        assert proof["state"] == "APPROVED"
        proj = validate_success(api.get_project(ctx["proj"]["id"], ctx["headers"]), 200)
        assert proj["state"] == "APPROVED", f"cascade hop 2 -> project APPROVED, got {proj['state']}"

    def test_approve_locks_every_placed_photo(self, api):
        """PRD 3.3: "Approval is the depth-three cascade of Section 2.9: the proof becomes APPROVED,
        then the project state becomes APPROVED, then every photo moves from PLACED to LOCKED, and
        the project version is bumped."

        Design: Difficulty/transitive_cascade/proof_approve_cascade_project_photo_lock
        """
        ctx = setup_project_in_proof()
        api.approve_proof(ctx["proof"]["id"], ctx["headers"])
        statuses = _photo_statuses(api, ctx["proj"]["id"], ctx["headers"])
        assert statuses and all(s == "LOCKED" for s in statuses), f"all photos LOCKED, got {statuses}"

    def test_second_approve_on_approved_proof_rejected(self, api):
        """PRD 3.3: "Approving a proof is permitted only when the project is IN_PROOF, the target
        proof is in GENERATED state, and that proof is the project's current proof (its id equals
        the project's current_proof_id); a violation of the state precondition is ERR_PROOF_NOT_PENDING."

        Design: Corner/state_machines/corner_approve_non_pending_proof_rejected
        """
        ctx = setup_project_in_proof()
        validate_success(api.approve_proof(ctx["proof"]["id"], ctx["headers"]), 200)
        res = api.approve_proof(ctx["proof"]["id"], ctx["headers"])
        validate_error(res, "ERR_PROOF_NOT_PENDING", 409)


class TestRevisionCycle:
    """Requesting changes drives the cyclic back-edge IN_PROOF -> DRAFT and unlocks photos."""

    def test_request_changes_reverts_project_to_draft(self, api):
        """PRD 3.3: "It sets the proof to CHANGES_REQUESTED, drives the project back along the
        revision back-edge from IN_PROOF to DRAFT, unlocks the design by reverting every photo from
        PLACED back to UPLOADED, and bumps the project version."

        Design: Difficulty/non_linear_state_machine/project_revision_cycle_in_proof_back_to_draft
        """
        ctx = setup_project_in_proof()
        proof = validate_success(api.request_changes(ctx["proof"]["id"], {"note": "fix cover"}, ctx["headers"]), 200)
        assert proof["state"] == "CHANGES_REQUESTED"
        proj = validate_success(api.get_project(ctx["proj"]["id"], ctx["headers"]), 200)
        assert proj["state"] == "DRAFT", f"cycle back-edge -> DRAFT, got {proj['state']}"

    def test_request_changes_unlocks_placed_photos(self, api):
        """PRD 3.3: "It sets the proof to CHANGES_REQUESTED, drives the project back along the
        revision back-edge from IN_PROOF to DRAFT, unlocks the design by reverting every photo from
        PLACED back to UPLOADED, and bumps the project version."

        Design: Difficulty/non_linear_state_machine/project_revision_cycle_in_proof_back_to_draft
        """
        ctx = setup_project_in_proof()
        api.request_changes(ctx["proof"]["id"], {"note": "fix cover"}, ctx["headers"])
        statuses = _photo_statuses(api, ctx["proj"]["id"], ctx["headers"])
        assert statuses and all(s == "UPLOADED" for s in statuses), f"all photos UPLOADED, got {statuses}"


class TestOptimisticConcurrency:
    """Proof generation is OCC-guarded on expected_project_version."""

    def test_stale_version_on_second_proof_generation_rejected(self, api):
        """PRD 2.7: "Because each successful proof generation itself bumps the project version and
        supersedes the prior proof, a second generate call that still carries the pre-supersede
        version is a stale write and is rejected on this check."

        Design: Corner/cross_cutting_complexity_layers/corner_occ_stale_project_version_on_proof
        """
        ctx = setup_laid_out_project()
        stale_version = validate_success(api.get_project(ctx["proj"]["id"], ctx["headers"]), 200)["version"]
        # First generation succeeds and bumps the version past `stale_version`.
        validate_success(
            api.generate_proof(ctx["proj"]["id"], {"expected_project_version": stale_version}, ctx["headers"]), 201
        )
        res = api.generate_proof(ctx["proj"]["id"], {"expected_project_version": stale_version}, ctx["headers"])
        validate_error(res, "ERR_STALE_PROJECT_VERSION", 412)

    def test_version_increments_by_one_on_photo_upload(self, api):
        """PRD 2.4: "an integer version that begins at 1 and increments by exactly 1 on each mutation"
        PRD 3.2: "Every upload increments the project's photo_count and bumps the project version."

        Design: Corner/cross_cutting_complexity_layers/corner_version_increments_on_each_mutation
        """
        cust = create_customer()
        h = make_customer_headers(cust["id"])
        tmpl = create_template()
        proj = validate_success(
            api.create_project({"customer_id": cust["id"], "template_id": tmpl["id"], "title": "P"}, h), 201
        )
        assert proj["version"] == 1, f"project starts at version 1, got {proj['version']}"
        upload_photo(proj, h, filename="a.jpg")
        after = validate_success(api.get_project(proj["id"], h), 200)
        assert after["version"] == 2, f"version 2 after one upload, got {after['version']}"


class TestAddressBook:
    """First address is the default; subsequent ones are not."""

    def test_first_address_is_default_second_is_not(self, api):
        """PRD 3.1: "The very first address a customer creates is automatically marked as the default
        ship-to by setting is_default to true; every subsequently created address has is_default set
        to false."

        Design: Corner/entities/corner_first_address_is_default
        """
        cust = create_customer()
        h = make_customer_headers(cust["id"])
        a1 = validate_success(api.create_address(cust["id"], {"recipient_name": "C", "line1": "1 A St",
                              "city": "SF", "region": "CA", "postal_code": "94101", "country": "US"}, h), 201)
        a2 = validate_success(api.create_address(cust["id"], {"recipient_name": "C", "line1": "2 B St",
                              "city": "SF", "region": "CA", "postal_code": "94102", "country": "US"}, h), 201)
        assert a1["is_default"] is True, "first address must be default"
        assert a2["is_default"] is False, "second address must not be default"
