"""Stale parent versions, a re-arming guard, and a snapshot frozen at approval."""

import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    approved_proof,
    approved_version,
    asset_with_obsolete_predecessor,
    assign_root_cause,
    clear_claim,
    coord,
    create_artwork_version_payload,
    dispute_escape,
    new_approved_brief,
    new_asset,
    new_claim,
    new_escape,
    new_printer,
    new_version,
    quality,
    raise_recovery_claim,
    read_asset,
    read_escape,
    read_version,
    recovery_claim_payload,
    reject_claim,
    release_payload,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestAssetStalenessGuardReArmsAfterEveryWrite:
    """The pinned value names the parent asset, which the create itself moves on."""

    def test_the_same_expected_value_cannot_be_spent_twice(self):
        """A stale pin is a 412 that writes nothing; a refreshed one is a 201 that re-arms.

        PRD §2.6: "A `POST /artwork-assets/{id}/versions` request must carry
        `expected_artwork_asset_version` as a required input field, holding the `version`
        of the `ArtworkAsset` as the client last read it. If that value does not equal the
        asset's current `version`, the create is rejected with `ERR_STALE_ASSET_VERSION`
        and HTTP 412."

        PRD §3.3: "Creating a version increments the asset's `version_counter` by 1 and
        stamps the new row's `version_no` with the resulting value, so revision numbers are
        sequential within the asset and never reused; the asset's own `version` is
        incremented by 1 as well."

        Design: Corner/cross_cutting_complexity_layers/stale_expected_asset_version_is_a_412_while_the_refreshed_value_succeeds
        """
        brief = new_approved_brief()
        asset = new_asset(brief["id"])
        assert asset["version"] == 1
        assert asset["version_counter"] == 0
        asset_v1 = asset["version"]

        v1 = new_version(asset)
        assert v1["version_no"] == 1
        assert v1["state"] == "DRAFT"
        assert v1["supersedes_version_id"] is None

        validate_error(
            api_client.create_artwork_version(
                asset["id"],
                create_artwork_version_payload(
                    asset_v1,
                    reason_for_change_code="NEW_LAUNCH",
                    change_description=(
                        "Second revision authored from a stale read of the asset."
                    ),
                ),
                coord(),
            ),
            ApiErrorId.ERR_STALE_ASSET_VERSION.value,
            412,
        )

        rows, meta = validate_paginated(
            api_client.list_artwork_versions(
                coord(), params={"artwork_asset_id": asset["id"], "limit": 100}
            )
        )
        assert meta["total_count"] == 1
        assert [row["version_no"] for row in rows] == [1]

        refreshed = read_asset(asset["id"])
        assert refreshed["version"] == 2
        assert refreshed["version_counter"] == 1
        asset_v2 = refreshed["version"]

        v2 = validate_success(
            api_client.create_artwork_version(
                asset["id"],
                create_artwork_version_payload(
                    asset_v2,
                    reason_for_change_code="MARKETING_REFRESH",
                    change_description=(
                        "Second revision authored from a refreshed read of the asset."
                    ),
                    supersedes_version_id=v1["id"],
                ),
                coord(),
            ),
            201,
        )
        assert v2["version_no"] == 2
        assert v2["state"] == "DRAFT"
        assert v2["supersedes_version_id"] == v1["id"]
        assert v2["author_user_id"] == "u_coord"

        after = read_asset(asset["id"])
        assert after["version"] == 3
        assert after["version_counter"] == 2

        validate_error(
            api_client.create_artwork_version(
                asset["id"],
                create_artwork_version_payload(
                    asset_v2,
                    reason_for_change_code="NEW_LAUNCH",
                    change_description=(
                        "Third revision replaying the now-stale second read."
                    ),
                ),
                coord(),
            ),
            ApiErrorId.ERR_STALE_ASSET_VERSION.value,
            412,
        )

        closing, closing_meta = validate_paginated(
            api_client.list_artwork_versions(
                coord(), params={"artwork_asset_id": asset["id"], "limit": 100}
            )
        )
        assert closing_meta["total_count"] == 2
        assert [row["version_no"] for row in closing] == [1, 2]
        assert read_asset(asset["id"])["version"] == 3


class TestEscapeStalenessOutranksTheStateCheck:
    """Three writes behind: the withdrawn apportionment can never be re-billed."""

    def test_the_withdrawn_share_is_refused_and_the_replay_is_a_412_not_a_409(self):
        """A pin from before the dispute is a 412, and so is a spent pin on a claimed row.

        PRD §2.6: "A `POST /error-escapes/{id}/recovery-claim` request must carry
        `expected_error_escape_version` as a required input field, holding the `version` of
        the `ErrorEscape` as the client last read it. If that value does not equal the
        escape's current `version`, the claim is rejected with `ERR_STALE_ESCAPE_VERSION`
        and HTTP 412."

        PRD §2.7: "Fifth, the two optimistic-concurrency checks of §2.6, asset staleness
        (`ERR_STALE_ASSET_VERSION`) before escape staleness (`ERR_STALE_ESCAPE_VERSION`)."

        PRD §3.9: "Each of the four lines is multiplied by `printer_share_pct` and rounded
        half up to a whole cent **individually, in that order**, and only then are the four
        rounded figures summed; summing the raw lines and rounding once at the end is a
        different and incorrect result."

        Design: Corner/cross_cutting_complexity_layers/stale_expected_escape_version_after_a_revised_apportionment_is_a_412_that_outranks_the_state_check
        """
        _brief, asset, v1, _v2 = asset_with_obsolete_predecessor()
        assert asset["standard_unit_cost_cents"] == 42
        printer = new_printer()
        assert printer["recovery_liability_cap_cents"] == 5000000

        escape = new_escape(
            v1["id"], printer, discovered_stage="PACKING", units_affected=3000
        )
        assert escape["investigation_fee_cents"] == 60000

        first_apportionment = assign_root_cause(escape["id"], "PRINTER", 1.00)
        assert first_apportionment["state"] == "ROOT_CAUSE_ASSIGNED"
        escape_v_a = first_apportionment["version"]

        withdrawn_basis = raise_recovery_claim(escape["id"])
        # 126000 reprint + 21000 scrap + 0 freight + 60000 investigation at share 1.00.
        assert withdrawn_basis["provisional_recovery_cents"] == 207000

        disputed = dispute_escape(
            escape["id"],
            printer,
            dispute_reason="The plate file we received already carried the defect.",
        )
        assert disputed["state"] == "DISPUTED"

        revised = assign_root_cause(escape["id"], "SHARED", 0.40)
        assert revised["state"] == "ROOT_CAUSE_ASSIGNED"
        assert revised["provisional_recovery_cents"] is None
        assert revised["liability_cap_applied"] is False

        validate_error(
            api_client.raise_recovery_claim(
                escape["id"], recovery_claim_payload(escape_v_a), quality()
            ),
            ApiErrorId.ERR_STALE_ESCAPE_VERSION.value,
            412,
        )

        mid = read_escape(escape["id"])
        assert mid["state"] == "ROOT_CAUSE_ASSIGNED"
        assert mid["root_cause_party"] == "SHARED"
        assert mid["printer_share_pct"] == pytest.approx(0.40, abs=0.01)
        assert mid["provisional_recovery_cents"] is None
        assert mid["liability_cap_applied"] is False
        escape_v_c = mid["version"]
        assert escape_v_c == escape_v_a + 3

        reclaimed = validate_success(
            api_client.raise_recovery_claim(
                escape["id"], recovery_claim_payload(escape_v_c), quality()
            ),
            200,
        )
        assert reclaimed["state"] == "RECOVERY_CLAIMED"
        # Per line at 0.40: 50400 reprint, 8400 scrap, 0 freight, 24000 investigation.
        assert reclaimed["provisional_recovery_cents"] == 50400 + 8400 + 0 + 24000
        assert reclaimed["provisional_recovery_cents"] == 82800
        assert reclaimed["provisional_recovery_cents"] != 207000
        assert reclaimed["liability_cap_applied"] is False

        validate_error(
            api_client.raise_recovery_claim(
                escape["id"], recovery_claim_payload(escape_v_c), quality()
            ),
            ApiErrorId.ERR_STALE_ESCAPE_VERSION.value,
            412,
        )

        closing = read_escape(escape["id"])
        assert closing["state"] == "RECOVERY_CLAIMED"
        assert closing["provisional_recovery_cents"] == 82800
        assert closing["printer_share_pct"] == pytest.approx(0.40, abs=0.01)

        rows, meta = validate_paginated(
            api_client.list_error_escapes(
                quality(),
                params={"printer_id": printer["id"], "state": "RECOVERY_CLAIMED"},
            )
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == escape["id"]
        assert rows[0]["provisional_recovery_cents"] == 82800


class TestPinnedSnapshotIsJudgedInsteadOfTheLiveLibrary:
    """A withdrawal and a fresh clearance of the same code cannot rescue a release."""

    def test_a_lapsed_pinned_entry_blocks_release_even_after_the_code_is_recleared(self):
        """One expired entry of two is enough, and the snapshot never repoints or refreshes.

        PRD §3.5: "A pass reaching `COMPLETE_APPROVED` moves the version `IN_REVIEW →
        APPROVED`, stamps `approved_at` from the logical clock, and freezes
        `pinned_claim_snapshot` as one entry per `claim_ids` element, in `claim_ids` order,
        each entry recording that claim's `marketing_claim_id`, its `claim_code` and its
        `cleared_until_utc` as they stood at the moment of approval."

        PRD §3.7: "Every entry of `pinned_claim_snapshot` must still have a
        `cleared_until_utc` strictly later than the current logical-clock instant, else
        `ERR_CLAIM_CLEARANCE_EXPIRED` — this is the version-pinning check that catches a
        claim whose clearance lapsed between approval and release."

        PRD §3.2: "Because overlap detection consults only rows whose `legal_status` is
        `CLEARED`, a withdrawal frees that code-and-market interval for a fresh clearance."

        Design: Corner/cross_cutting_complexity_layers/pinned_claim_snapshot_is_frozen_at_approval_so_a_fresh_clearance_of_the_same_code_cannot_rescue_the_release
        """
        lapsing = new_claim(
            claim_code="NAS-01",
            claim_text="NO ADDED SUGAR",
            claim_type="NUTRIENT_CONTENT",
            substantiation_ref="DOSSIER-NAS-2026-01",
        )
        clear_claim(
            lapsing["id"],
            cleared_from_utc="2026-08-01T00:00:00Z",
            cleared_until_utc="2026-08-15T00:00:00Z",
        )
        durable = new_claim(
            claim_code="GF-02",
            claim_text="GLUTEN FREE",
            claim_type="FREE_FROM",
            substantiation_ref="DOSSIER-GF-2026-02",
        )
        clear_claim(
            durable["id"],
            cleared_from_utc="2026-08-01T00:00:00Z",
            cleared_until_utc="2026-12-31T00:00:00Z",
        )

        _brief, _asset, version = approved_version(
            claim_ids=[lapsing["id"], durable["id"]]
        )
        assert version["state"] == "APPROVED"
        assert version["compliance_score"] == pytest.approx(100.0, abs=0.01)
        assert version["requires_reverification"] is False

        printer = new_printer()
        proof = approved_proof(version["id"], printer)
        assert proof["proof_state"] == "PROOF_APPROVED"
        assert proof["press_check_status"] == "NOT_REQUIRED"

        before = read_version(version["id"])
        assert before["approved_at"].startswith("2026-08-01T00:00:00")
        assert before["released_at"] is None
        snapshot = before["pinned_claim_snapshot"]
        assert len(snapshot) == 2
        assert snapshot[0]["marketing_claim_id"] == lapsing["id"]
        assert snapshot[0]["claim_code"] == "NAS-01"
        assert snapshot[0]["cleared_until_utc"].startswith("2026-08-15T00:00:00")
        assert snapshot[1]["marketing_claim_id"] == durable["id"]
        assert snapshot[1]["claim_code"] == "GF-02"
        assert snapshot[1]["cleared_until_utc"].startswith("2026-12-31T00:00:00")

        set_clock("2026-08-20T00:00:00Z")
        validate_error(
            api_client.release_to_print(
                version["id"],
                release_payload(release_note="Released against the approved proof."),
                coord(),
            ),
            ApiErrorId.ERR_CLAIM_CLEARANCE_EXPIRED.value,
            422,
        )

        retracted = reject_claim(
            lapsing["id"],
            rejection_reason="Substantiation dossier retracted by the supplier.",
        )
        assert retracted["legal_status"] == "REJECTED"
        assert retracted["cleared_from_utc"].startswith("2026-08-01T00:00:00")
        assert retracted["cleared_until_utc"].startswith("2026-08-15T00:00:00")

        successor = new_claim(
            claim_code="NAS-01",
            claim_text="NO ADDED SUGAR",
            claim_type="NUTRIENT_CONTENT",
            substantiation_ref="DOSSIER-NAS-2026-01",
        )
        recleared = clear_claim(
            successor["id"],
            cleared_from_utc="2026-08-15T00:00:00Z",
            cleared_until_utc="2026-12-31T00:00:00Z",
        )
        assert recleared["legal_status"] == "CLEARED"
        assert recleared["id"] != lapsing["id"]

        after = read_version(version["id"])
        assert after["pinned_claim_snapshot"] == snapshot
        assert after["pinned_claim_snapshot"][0]["marketing_claim_id"] == lapsing["id"]
        assert after["pinned_claim_snapshot"][0]["cleared_until_utc"].startswith(
            "2026-08-15T00:00:00"
        )

        validate_error(
            api_client.release_to_print(
                version["id"],
                release_payload(release_note="Released against the approved proof."),
                coord(),
            ),
            ApiErrorId.ERR_CLAIM_CLEARANCE_EXPIRED.value,
            422,
        )

        rows, meta = validate_paginated(
            api_client.list_marketing_claims(
                coord(),
                params={
                    "claim_code": "NAS-01",
                    "market_code": "US",
                    "legal_status": "CLEARED",
                },
            )
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == successor["id"]

        closing = read_version(version["id"])
        assert closing["state"] == "APPROVED"
        assert closing["released_at"] is None
