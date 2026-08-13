"""Auth/RBAC denial tests and the wool-lot OCC regrade rule."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    create_completed_clip,
    create_flock,
    grade_lot,
    setup_graded_lot,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestAuthentication:

    def test_unauthenticated_request_rejected(self, api):
        """PRD §2.1: "A request missing either header, or presenting a role
        string that is not one of the declared roles, is rejected with
        `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/rbac/unauthenticated_request_rejected
        """
        resp = api.create_flock(
            {"flock_name": "Anon Ranch", "species": "SHEEP", "baseline_headcount": 100},
            headers={})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value, expected_status=401)

    def test_unauthenticated_missing_user_id_rejected(self, api):
        """PRD §2.1: "Every request carries two headers: `X-User-ID`,
        identifying the acting operator, and `X-User-Role`, naming the
        operator's role. A request missing either header, or presenting a role
        string that is not one of the declared roles, is rejected with
        `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/rbac/unauthenticated_request_rejected
        """
        resp = api.create_flock(
            {"flock_name": "Anon2 Ranch", "species": "SHEEP", "baseline_headcount": 100},
            headers={"X-User-Role": "RanchManager"})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value, expected_status=401)


class TestRbacDenials:

    def test_wool_lot_create_as_range_hand_forbidden(self, api, range_hand_headers, ranch_manager_headers):
        """PRD §4: POST /api/wool-lots is authorized for RanchManager only.
        PRD §2.1: "A request whose role is not listed among the roles permitted
        on the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)".

        Design: Corner/rbac/wool_lot_create_as_range_hand_forbidden
        """
        flock = create_flock(flock_name="Rbac Ranch", species="SHEEP", baseline_headcount=500)
        clip, _event, _crew = create_completed_clip(flock["id"], crew_name="Crew RB")
        resp = api.create_wool_lot(
            {"clip_id": clip["id"], "lot_code": "RB1", "weight_lbs": 50.0},
            range_hand_headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value, expected_status=403)
        _, meta = validate_paginated(
            api.list_wool_lots(ranch_manager_headers, params={"clip_id": clip["id"]}))
        assert meta["total_count"] == 0, "no lot created on the clip"


class TestLotOccRegrade:

    def test_lot_regrade_stale_version_rejected(self, api, ranch_manager_headers):
        """PRD §2.6: "Recording a regrade on a wool lot requires the request to
        carry `expected_wool_lot_version`, holding the caller's last observed
        `version` of that lot. If the lot's current `version` no longer matches
        — because another writer has already regraded the lot, superseding the
        grade the caller based its estimate on — the regrade is rejected with
        `ERR_STALE_LOT_VERSION` (HTTP 412)".
        PRD §2.9: "Every transition writes the new state, increments the
        entity's `version` by exactly 1".

        Design: Corner/cross_cutting_layers/lot_regrade_stale_version_rejected
        """
        flock, clip, lot = setup_graded_lot(
            estimated_micron=20.0, flock_name="Occ Ranch", crew_name="Crew OC")
        assert lot["lot_status"] == "GRADED"
        stale_version = lot["version"]  # version observed before REGRADING
        lot = validate_success(api.transition_wool_lot(
            lot["id"], {"to": "REGRADING"}, ranch_manager_headers))
        fresh_version = lot["version"]
        assert fresh_version == stale_version + 1, "transition increments version by exactly 1"

        # Regrade carrying the pre-REGRADING version -> stale.
        resp = api.regrade_wool_lot(lot["id"], {
            "estimated_micron": 18.0, "expected_wool_lot_version": stale_version,
        }, ranch_manager_headers)
        validate_error(resp, ApiErrorId.ERR_STALE_LOT_VERSION.value, expected_status=412)

        # Regrade with the current version succeeds.
        lot = validate_success(api.regrade_wool_lot(lot["id"], {
            "estimated_micron": 18.0, "expected_wool_lot_version": fresh_version,
        }, ranch_manager_headers))
        assert lot["lot_status"] == "GRADED"
        assert lot["grade_code"] == "SUPERFINE", "18.0 < 19.5"
        assert lot["version"] == fresh_version + 1

    def test_lot_regrade_occ_second_stale_pairing(self, api, ranch_manager_headers):
        """PRD §2.6: "If the lot's current `version` no longer matches —
        because another writer has already regraded the lot, superseding the
        grade the caller based its estimate on — the regrade is rejected with
        `ERR_STALE_LOT_VERSION` (HTTP 412), preventing the caller from
        overwriting a grade it never observed."

        Design: Corner/cross_cutting_layers/lot_regrade_stale_version_rejected
        """
        flock, clip, lot = setup_graded_lot(
            estimated_micron=22.0, flock_name="Occ3 Ranch", crew_name="Crew OC3")
        lot = validate_success(api.transition_wool_lot(
            lot["id"], {"to": "REGRADING"}, ranch_manager_headers))
        resp = api.regrade_wool_lot(lot["id"], {
            "estimated_micron": 21.0,
            "expected_wool_lot_version": lot["version"] + 9,
        }, ranch_manager_headers)
        validate_error(resp, ApiErrorId.ERR_STALE_LOT_VERSION.value, expected_status=412)


class TestBodyFkNotFound:

    def test_birth_record_body_fk_not_found_returns_404(self, api, range_hand_headers):
        """PRD §2.8: "Existence — path identifiers resolve left-to-right, then
        body foreign-key references (`flock_id`, `season_id`, `clip_id`,
        `lot_id`, `pasture_id`, `contract_id`, `crew_id`) resolve to existing
        rows, else `ERR_NOT_FOUND`."

        Design: Corner/errors/birth_record_body_fk_not_found_returns_404
        """
        resp = api.create_birth_record({
            "season_id": NON_EXISTENT_UUID,
            "birth_date": "2026-12-30T06:00:00Z",
            "births_reported": 4, "born_alive": 4, "born_dead": 0,
        }, range_hand_headers)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value, expected_status=404)
