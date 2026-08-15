"""Asset conform/lock interlock, change-list deltas, and supersede fork."""

from test_helpers import (
    ApiErrorId, change_list_entry, create_change_list, create_turnover,
    create_vendor, create_vendor_bid, current_turnover_version, award_bid,
    issue_turnover, setup_verified_asset, setup_issued_turnover,
    stage_turnover, validate_error, validate_success,
)
from test_helpers.test_users import make_conform_editor_headers

CE = make_conform_editor_headers()


class TestAssetConformGate:
    def test_asset_conform_requires_turnover_staged_rejected(self, api):
        """PRD §3.5: "A `ConformEditor` conforms an asset — moving it from
        `VERIFIED` to `CONFORMED` — only while the project is `ACTIVE` and the
        asset is referenced by at least one `CONFORM` turnover in `STAGED` or
        `ISSUED`."

        Design: Difficulty/cross_entity_state_dependency/asset_conform_requires_turnover_staged
        """
        project, _batch, asset = setup_verified_asset(
            project_overrides={"title": "PA", "client_code": "CL014",
                               "storage_quota_gb": 100})
        # No turnover exists for the project: conform must be refused.
        resp = api.conform_asset(project["id"], asset["id"], CE)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        after = validate_success(api.get_asset(project["id"], asset["id"], CE))
        assert after["status"] == "VERIFIED"

    def test_asset_conform_succeeds_with_staged_conform_turnover(self, api):
        """PRD §3.5: "A `ConformEditor` conforms an asset — moving it from
        `VERIFIED` to `CONFORMED` — only while the project is `ACTIVE` and the
        asset is referenced by at least one `CONFORM` turnover in `STAGED` or
        `ISSUED`."
        PRD §3.5: "a `CONFORM` turnover additionally requires at least one
        project asset in `VERIFIED` or `CONFORMED` so there is something to
        conform."

        Design: Difficulty/cross_entity_state_dependency/asset_conform_requires_turnover_staged
        """
        project, _batch, asset = setup_verified_asset(
            project_overrides={"title": "PA", "client_code": "CL014",
                               "storage_quota_gb": 100})
        turnover = create_turnover(project["id"], turnover_kind="CONFORM",
                                   sequence_label="SEQ-01")
        stage_turnover(project["id"], turnover["id"])
        conformed = validate_success(api.conform_asset(project["id"], asset["id"], CE))
        assert conformed["status"] == "CONFORMED"


class TestChangeListDelta:
    def test_change_list_net_frames_delta_mixed_operations(self, api):
        """PRD §3.5: "its `net_frames_delta` is computed at creation as the sum
        over all entries of each `frames_delta` taken positively for `ADD` and
        `SLIP` operations and negatively for `TRIM` and `DELETE` operations."

        Design: Corner/calculations/change_list_net_frames_delta_mixed_operations
        """
        project, _batch, asset = setup_verified_asset(
            project_overrides={"title": "P", "client_code": "CL301",
                               "storage_quota_gb": 10})
        turnover = create_turnover(project["id"], turnover_kind="CONFORM",
                                   sequence_label="SEQ-01")
        stage_turnover(project["id"], turnover["id"])
        entries = [
            change_list_entry(asset["id"], "ADD", 10),
            change_list_entry(asset["id"], "SLIP", 3),
            change_list_entry(asset["id"], "TRIM", 4),
            change_list_entry(asset["id"], "DELETE", 2),
        ]
        resp = api.create_change_list(project["id"], {
            "turnover_id": turnover["id"], "entries": entries}, CE)
        cl = validate_success(resp, expected_status=201)
        # +10 +3 -4 -2 = +7
        assert cl["net_frames_delta"] == 7, (
            f"Expected net_frames_delta 7 (+10+3-4-2), got {cl['net_frames_delta']}")
        assert cl["status"] == "OPEN"
        assert cl["revision"] == 1


class TestChangeListSupersedeFork:
    def test_change_list_supersede_fork_apply_branch(self, api):
        """PRD §3.5: "A successful apply moves the list to `APPLIED` and performs
        a chain of side effects: ... every other change list on the same turnover
        still `OPEN` transitions to `SUPERSEDED`, a state the lifecycle never
        exits; the turnover's `version` increments by one."

        Design: Difficulty/non_linear_state_machine/change_list_supersede_fork
        """
        # PRD §3.5: "a `CONFORM` turnover additionally requires at least one
        # project asset in `VERIFIED` or `CONFORMED`" at staging time — so the
        # verified asset must exist BEFORE the CONFORM turnover is staged.
        project, _batch0, _asset0 = setup_verified_asset(
            project_overrides={"title": "PF", "client_code": "CL006",
                               "storage_quota_gb": 100})
        project, turnover, vendor, _bid = setup_issued_turnover(
            project=project,
            turnover_overrides={"turnover_kind": "CONFORM",
                                "sequence_label": "SEQ-01"},
            vendor_overrides={"capabilities": ["CONFORM"]})
        # An asset must exist and be conformable; add a second verified asset.
        # (Labels must differ from the setup batch/asset: PRD §3.2 requires
        # batch_label unique within the project and (reel, clip) unique among
        # non-purged assets.)
        from test_helpers import create_batch, create_asset, start_ingest, finish_ingest, proxy_complete, verify_asset
        batch = create_batch(project["id"], batch_label="DAY02")
        start_ingest(project["id"], batch["id"])
        asset = create_asset(project["id"], batch["id"], clip_name="C002",
                             source_bytes=1000, duration_frames=100)
        finish_ingest(project["id"], batch["id"])
        proxy_complete(project["id"], asset["id"], 500)
        verify_asset(project["id"], asset["id"])
        cl1 = create_change_list(project["id"], turnover["id"],
                                 [change_list_entry(asset["id"], "TRIM", 10)])
        cl2 = create_change_list(project["id"], turnover["id"],
                                 [change_list_entry(asset["id"], "ADD", 5)])
        turn_v = current_turnover_version(project["id"], turnover["id"])
        resp = api.apply_change_list(project["id"], cl1["id"],
                                     {"expected_turnover_version": turn_v}, CE)
        applied = validate_success(resp)
        assert applied["status"] == "APPLIED"
        cl2_after = validate_success(api.get_change_list_flat(cl2["id"], CE))
        assert cl2_after["status"] == "SUPERSEDED", (
            f"Sibling OPEN change list must be SUPERSEDED after the apply; "
            f"got {cl2_after['status']}")

    def test_change_list_supersede_fork_resets_open_count(self, api):
        """PRD §3.5: "every other change list on the same turnover still `OPEN`
        transitions to `SUPERSEDED` ... and, through the supersession cascade,
        the project's `open_change_list_count` is recomputed."
        PRD §3.5: "the project's `open_change_list_count` — the count of its
        change lists still in `OPEN` status — is recomputed."

        Design: Difficulty/non_linear_state_machine/change_list_supersede_fork
        """
        # PRD §3.5: "a `CONFORM` turnover additionally requires at least one
        # project asset in `VERIFIED` or `CONFORMED`" at staging time — so the
        # verified asset must exist BEFORE the CONFORM turnover is staged.
        project, _batch0, _asset0 = setup_verified_asset(
            project_overrides={"title": "PF", "client_code": "CL006",
                               "storage_quota_gb": 100})
        project, turnover, vendor, _bid = setup_issued_turnover(
            project=project,
            turnover_overrides={"turnover_kind": "CONFORM",
                                "sequence_label": "SEQ-01"},
            vendor_overrides={"capabilities": ["CONFORM"]})
        from test_helpers import (create_batch, create_asset, start_ingest,
                                  finish_ingest, proxy_complete, verify_asset)
        batch = create_batch(project["id"], batch_label="DAY02")
        start_ingest(project["id"], batch["id"])
        asset = create_asset(project["id"], batch["id"], clip_name="C002",
                             source_bytes=1000, duration_frames=100)
        finish_ingest(project["id"], batch["id"])
        proxy_complete(project["id"], asset["id"], 500)
        verify_asset(project["id"], asset["id"])
        cl1 = create_change_list(project["id"], turnover["id"],
                                 [change_list_entry(asset["id"], "TRIM", 10)])
        cl2 = create_change_list(project["id"], turnover["id"],
                                 [change_list_entry(asset["id"], "ADD", 5)])
        proj_mid = validate_success(api.get_project(project["id"],
                                                    make_conform_editor_headers()))
        assert proj_mid["open_change_list_count"] == 2
        turn_v = current_turnover_version(project["id"], turnover["id"])
        api.apply_change_list(project["id"], cl1["id"],
                              {"expected_turnover_version": turn_v}, CE)
        proj_after = validate_success(api.get_project(project["id"],
                                                      make_conform_editor_headers()))
        assert proj_after["open_change_list_count"] == 0, (
            f"After apply+supersede, open_change_list_count must be 0; "
            f"got {proj_after['open_change_list_count']}")
        cl2_after = validate_success(api.get_change_list_flat(cl2["id"], CE))
        assert cl2_after["status"] == "SUPERSEDED"


class TestChangeListConformability:
    def test_asset_not_conformable_on_change_list_apply(self, api):
        """PRD §3.5: "The parent turnover must be `ISSUED` or `ACKED`, and every
        entry's `asset_id` must resolve to an asset in `VERIFIED`, `CONFORMED`,
        or `LOCKED` — any other asset is rejected with
        `ERR_ASSET_NOT_CONFORMABLE`."
        PRD §2.9 item 17: "Applying a change list requires every referenced asset
        to be in a conformable state; otherwise `ERR_ASSET_NOT_CONFORMABLE`
        (HTTP 422)."

        Design: Corner/validations/asset_not_conformable_on_change_list_apply
        """
        # PRD §3.5: "a `CONFORM` turnover additionally requires at least one
        # project asset in `VERIFIED` or `CONFORMED`" at staging time — so a
        # verified asset must exist BEFORE the CONFORM turnover is staged. The
        # change-list entry below targets a DIFFERENT asset that stays INGESTED
        # (never verified), which is what makes the apply non-conformable.
        project, _batch0, _asset0 = setup_verified_asset(
            project_overrides={"title": "P", "client_code": "CL402",
                               "storage_quota_gb": 100})
        project, turnover, vendor, _bid = setup_issued_turnover(
            project=project,
            turnover_overrides={"turnover_kind": "CONFORM",
                                "sequence_label": "SEQ-01"},
            vendor_overrides={"capabilities": ["CONFORM"]})
        from test_helpers import create_batch, create_asset, start_ingest
        batch = create_batch(project["id"], batch_label="D1")
        start_ingest(project["id"], batch["id"])
        # Asset stays INGESTED — never verified, so not conformable. (clip_name
        # differs from the setup asset's C001: PRD §3.2 requires (reel, clip)
        # unique among the project's non-purged assets.)
        asset = create_asset(project["id"], batch["id"], clip_name="C002",
                             source_bytes=1000, duration_frames=100)
        cl = create_change_list(project["id"], turnover["id"],
                                [change_list_entry(asset["id"], "TRIM", 5)])
        turn_v = current_turnover_version(project["id"], turnover["id"])
        resp = api.apply_change_list(project["id"], cl["id"],
                                     {"expected_turnover_version": turn_v}, CE)
        validate_error(resp, ApiErrorId.ERR_ASSET_NOT_CONFORMABLE)
