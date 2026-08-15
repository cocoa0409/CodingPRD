"""PLC program version control: supersede-on-release, OCC anchor, uniqueness."""
import pytest

from test_helpers import (
    ApiErrorId,
    create_program_version_payload,
    new_customer,
    new_job,
    new_panel,
    unique_content_hash,
    validate_error,
    validate_paginated,
    validate_success,
)

HASH_V1 = "aaaa0000eeff0011223344556677889900112233445566778899aabbccddeeff00"
HASH_V2 = "bbbb0000eeff0011223344556677889900112233445566778899aabbccddeeff00"


def _fresh_panel(api, company="Sup Co", job_number="J-SP1", panel_tag="P-SP1",
                 designer="de-sp"):
    customer = new_customer(company_name=company)
    job = new_job(customer["id"], job_number=job_number, quoted_price_cents=100000)
    panel = new_panel(job["id"], design_engineer_id=designer, panel_tag=panel_tag)
    return customer, job, panel


class TestSupersedeOnRelease:
    def test_program_release_supersedes_prior_released_version(self, api, ce_headers):
        """PRD §3.5: "Either path transitions the version `DRAFT → RELEASED`, sets
        `released_at` to the current time, supersedes every other version of the same
        panel that was previously `RELEASED` (each such version transitions to
        `SUPERSEDED`), and increments the panel's `version` by one".

        Design: Corner/state_machines/program_release_supersedes_prior_released_version
        """
        _c, _j, panel = _fresh_panel(api)
        v1 = validate_success(
            api.create_program_version(
                panel["id"],
                create_program_version_payload(
                    expected_panel_version=panel["version"],
                    version_tag="v1.0.0", content_hash=unique_content_hash(),
                ),
                ce_headers,
            ),
            201,
        )
        assert v1["status"] == "RELEASED"

        current = validate_success(api.get_panel(panel["id"], ce_headers), 200)
        v2 = validate_success(
            api.create_program_version(
                panel["id"],
                create_program_version_payload(
                    expected_panel_version=current["version"],
                    version_tag="v2.0.0", content_hash=unique_content_hash(),
                ),
                ce_headers,
            ),
            201,
        )
        assert v2["status"] == "RELEASED"

        v1_after = validate_success(api.get_program_version(v1["id"], ce_headers), 200)
        assert v1_after["status"] == "SUPERSEDED", (
            f"prior release must cascade to SUPERSEDED, got {v1_after['status']}"
        )
        released, _ = validate_paginated(
            api.list_panel_program_versions(panel["id"], ce_headers,
                                            params={"status": "RELEASED"})
        )
        assert [p["id"] for p in released] == [v2["id"]], (
            "at most one RELEASED version per panel at any time"
        )


class TestContentHashUniqueness:
    def test_duplicate_content_hash_same_panel_rejected(self, api, ce_headers):
        """PRD §3.5: "Each version carries a human `version_tag` (such as `v1.2.0`,
        unique within the panel; duplicates are rejected with `ERR_DUPLICATE`) and a
        `content_hash` — the SHA-256 hex of the compiled program archive, also unique
        within the panel; a duplicate hash is likewise rejected with `ERR_DUPLICATE`."

        Design: Corner/validations/duplicate_content_hash_same_panel_rejected
        """
        shared_hash = "dead0000eeff0011223344556677889900112233445566778899aabbccddeeff00"
        _c, job, panel_1 = _fresh_panel(api, company="DH Co", job_number="J-DH1",
                                        panel_tag="P-DH1", designer="de-dh")
        panel_2 = new_panel(job["id"], design_engineer_id="de-dh", panel_tag="P-DH2")

        validate_success(
            api.create_program_version(
                panel_1["id"],
                create_program_version_payload(
                    expected_panel_version=panel_1["version"],
                    version_tag="v1.0.0", content_hash=shared_hash,
                ),
                ce_headers,
            ),
            201,
        )

        # Same hash on a DIFFERENT panel: uniqueness is scoped per panel.
        other = validate_success(
            api.create_program_version(
                panel_2["id"],
                create_program_version_payload(
                    expected_panel_version=panel_2["version"],
                    version_tag="v1.0.0", content_hash=shared_hash,
                ),
                ce_headers,
            ),
            201,
        )
        assert other["status"] == "RELEASED"

        # Same hash on the SAME panel: duplicate.
        current = validate_success(api.get_panel(panel_1["id"], ce_headers), 200)
        resp = api.create_program_version(
            panel_1["id"],
            create_program_version_payload(
                expected_panel_version=current["version"],
                version_tag="v1.0.1", content_hash=shared_hash,
            ),
            ce_headers,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE, 409)


class TestOccHappyPath:
    def test_occ_correct_version_succeeds_and_bumps_panel_version(self, api, ce_headers):
        """PRD §3.5: "The create succeeds only when `expected_panel_version` equals
        the panel's current `version`; on a mismatch the create is rejected with
        `ERR_STALE_VERSION` (HTTP 412)."
        PRD §3.5: "increments the panel's `version` by one — the panel's `version` is
        the OCC anchor that future create-with-release calls are validated against."

        Design: Corner/cross_cutting_layers/occ_correct_version_succeeds_and_bumps_panel_version
        """
        _c, _j, panel = _fresh_panel(api, company="OC Co", job_number="J-OC1",
                                     panel_tag="P-OC1", designer="de-oc")
        v0 = panel["version"]
        validate_success(
            api.create_program_version(
                panel["id"],
                create_program_version_payload(
                    expected_panel_version=v0,
                    version_tag="v1.0.0", content_hash=unique_content_hash(),
                ),
                ce_headers,
            ),
            201,
        )
        after = validate_success(api.get_panel(panel["id"], ce_headers), 200)
        assert after["version"] == v0 + 1, (
            f"exactly one increment for the release: {v0} -> {after['version']}"
        )


class TestStaleBeatsDuplicate:
    def _panel_with_two_releases(self, api, ce_headers):
        _c, _j, panel = _fresh_panel(api, company="Lambda Packaging",
                                     job_number="J-9002", panel_tag="P-O1",
                                     designer="de-008")
        validate_success(
            api.create_program_version(
                panel["id"],
                create_program_version_payload(
                    expected_panel_version=panel["version"],
                    version_tag="v1.0.0", content_hash=HASH_V1,
                ),
                ce_headers,
            ),
            201,
        )
        current = validate_success(api.get_panel(panel["id"], ce_headers), 200)
        validate_success(
            api.create_program_version(
                panel["id"],
                create_program_version_payload(
                    expected_panel_version=current["version"],
                    version_tag="v1.1.0", content_hash=HASH_V2,
                ),
                ce_headers,
            ),
            201,
        )
        return panel

    def test_stale_version_and_duplicate_hash_reports_stale_version(self, api, ce_headers):
        """PRD §2.9: "When a request fails more than one validation, the server
        reports the failure with the lowest priority number."
        PRD §2.9: "7. `ERR_STALE_VERSION` — OCC `expected_*_version` mismatch." and
        "16. `ERR_DUPLICATE` — uniqueness violation on `part_number`, `content_hash`
        per panel, `version_tag` per panel, `panel_tag` per job, `job_number` per
        customer, or duplicate component on a panel."

        Design: Difficulty/priority_pair_validation_conflict/stale_version_beats_duplicate_hash_on_program_release
        """
        panel = self._panel_with_two_releases(api, ce_headers)
        # Client holds the pre-v1.1.0 version number and reuses v1.0.0's hash:
        # both OCC (stale) and uniqueness (duplicate hash) are violated.
        stale_version = panel["version"] + 1  # version observed after v1.0.0 only
        resp = api.create_program_version(
            panel["id"],
            create_program_version_payload(
                expected_panel_version=stale_version,
                version_tag="v1.2.0", content_hash=HASH_V1,
            ),
            ce_headers,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, 412)

    def test_stale_version_rejection_creates_no_program_version(self, api, ce_headers):
        """PRD §3.5: "The create succeeds only when `expected_panel_version` equals
        the panel's current `version`; on a mismatch the create is rejected with
        `ERR_STALE_VERSION` (HTTP 412)."

        Design: Difficulty/priority_pair_validation_conflict/stale_version_beats_duplicate_hash_on_program_release
        """
        panel = self._panel_with_two_releases(api, ce_headers)
        before = validate_success(api.get_panel(panel["id"], ce_headers), 200)
        versions_before, _ = validate_paginated(
            api.list_panel_program_versions(panel["id"], ce_headers)
        )
        assert len(versions_before) == 2

        resp = api.create_program_version(
            panel["id"],
            create_program_version_payload(
                expected_panel_version=panel["version"] + 1,  # stale by one release
                version_tag="v1.2.0", content_hash=unique_content_hash(),
            ),
            ce_headers,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, 412)

        after = validate_success(api.get_panel(panel["id"], ce_headers), 200)
        assert after["version"] == before["version"], "rejected release must not bump the anchor"
        versions_after, _ = validate_paginated(
            api.list_panel_program_versions(panel["id"], ce_headers)
        )
        assert len(versions_after) == 2, "rejected release must not create a version"
