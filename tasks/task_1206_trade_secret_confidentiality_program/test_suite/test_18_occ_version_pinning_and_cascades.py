"""Optimistic concurrency, version pinning on disclosure approval, the
execution evidence cascade, and immediate read-after-write consistency
(PRD §2.6, §3.5, §2.10)."""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    assert_same_instant,
    ApiErrorId,
    create_counterparty,
    create_active_nda,
    create_registered_asset,
    add_verified_measure,
    create_employee_record,
    create_under_review_disclosure,
    create_asset_payload,
    make_employee_headers,
    make_counterparty_rep_headers,
    make_ip_counsel_headers,
    SHA256_CD,
    TEST_USERS,
)

IP = TEST_USERS["ip_counsel_headers"]
SEC = TEST_USERS["security_officer_headers"]


class TestOccAssetPatch:
    def test_occ_asset_patch_stale_version_rejected(self, api):
        """PRD §2.6: "Updating a SecretAsset's descriptive record requires the
        non-optional field `expected_asset_version`, carrying the asset version
        the client last read. Because a descriptive update on a `REGISTERED`
        asset is otherwise legitimate for any later writer, the stale view —
        not any state precondition — is the only thing that can reject it."
        PRD §2.6: "if that value does not match the parent's current `version`,
        the write is rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_asset_patch_stale_version_rejected
        """
        asset = validate_success(api.create_asset(
            create_asset_payload(title="OCC probe", description="x",
                                 classification="INTERNAL", owner_department="ENG",
                                 exposure_estimate_cents=10), IP
        ), expected_status=201)
        a_v = asset["version"]
        updated = validate_success(api.patch_asset(
            asset["id"], {"expected_asset_version": a_v, "title": "OCC probe v2"}, IP
        ))
        assert updated["title"] == "OCC probe v2" and updated["version"] == a_v + 1
        resp = api.patch_asset(
            asset["id"], {"expected_asset_version": a_v, "title": "OCC probe stale"}, IP
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        data = validate_success(api.get_asset(asset["id"], IP))
        assert data["title"] == "OCC probe v2", "stale write did not apply"


class TestOccNdaAmendment:
    def test_occ_nda_amendment_stale_version_rejected(self, api):
        """PRD §2.6: "Creating an amendment NDA against an existing agreement
        requires the non-optional field `expected_superseded_nda_version`,
        carrying the version of the NDA being superseded; if that agreement's
        version has advanced since the client last observed it — a
        breach-allegation loop recorded in the meantime, for instance — the
        amendment is refused, because amendment legitimately supersedes the
        prior agreement and a stale basis must not silently do so."

        Design: Corner/cross_cutting_layers/occ_nda_amendment_stale_version_rejected
        """
        cp = create_counterparty(legal_name="OCC Nda Ltd", counterparty_type="VENDOR")
        nda = create_active_nda(
            cp["id"], template_version="t24", governing_law="ID",
            effective_date="2026-01-01T00:00:00Z", expiry_date="2026-12-31T00:00:00Z",
            survival_months=3, classification_ceiling="INTERNAL",
        )
        stale_v = validate_success(api.get_nda(nda["id"], IP))["version"]
        # A breach-allegation transition advances the version in the meantime
        validate_success(api.transition_nda(nda["id"], {"to_status": "BREACH_ALLEGED"}, IP))

        amendment_payload = {
            "template_version": "t25", "governing_law": "ID",
            "effective_date": "2026-06-01T00:00:00Z",
            "expiry_date": "2027-05-31T00:00:00Z",
            "survival_months": 6, "classification_ceiling": "CONFIDENTIAL",
        }
        resp = api.create_nda_amendment(
            nda["id"], {**amendment_payload, "expected_superseded_nda_version": stale_v}, IP
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

        fresh_v = validate_success(api.get_nda(nda["id"], IP))["version"]
        resp = api.create_nda_amendment(
            nda["id"], {**amendment_payload, "expected_superseded_nda_version": fresh_v}, IP
        )
        amendment = validate_success(resp, expected_status=201)
        assert amendment["status"] == "DRAFT"
        assert amendment["supersedes_id"] == nda["id"]


def _setup_pinned_disclosure(api):
    """REGISTERED asset with ADEQUATE posture; ACTIVE NDA; disclosure
    SUBMITTED then UNDER_REVIEW (pins taken at SUBMITTED)."""
    cp = create_counterparty(legal_name="Pin Ltd", counterparty_type="VENDOR")
    nda = create_active_nda(
        cp["id"], template_version="t26", governing_law="ID",
        effective_date="2026-01-01T00:00:00Z", expiry_date="2027-01-01T00:00:00Z",
        survival_months=3, classification_ceiling="CONFIDENTIAL",
    )
    asset = create_registered_asset(
        title="Pin probe", description="x", classification="CONFIDENTIAL",
        owner_department="ENG", exposure_estimate_cents=1000,
    )
    add_verified_measure(asset["id"], "TECHNICAL", title="t", evidence_uri="s3://ev/t.pdf")
    add_verified_measure(asset["id"], "PHYSICAL", title="p", evidence_uri="s3://ev/p.pdf")
    emp = create_employee_record(
        full_name="Pin Requester", email="pin@x.com", department="ENG",
        role_title="SDE", access_clearance="STANDARD",
        hired_at="2026-05-01T00:00:00Z",
    )
    disc = create_under_review_disclosure(
        emp["id"], asset["id"], nda["id"],
        purpose="p", marking_protocol="STAMPED_CONFIDENTIAL",
        planned_disclosure_date="2026-07-01T00:00:00Z",
    )
    return cp, nda, asset, emp, disc


class TestVersionPinningOnApproval:
    def test_version_pinning_stale_reference_blocks_approval(self, api):
        """PRD §3.5: "The asset's current `version` must still equal
        `pinned_asset_version` and the NDA's current `version` must still equal
        `pinned_nda_version`, otherwise `ERR_STALE_REFERENCE`; this is the
        intended serialization point that makes descriptive asset edits and NDA
        amendments visible to the approver."

        Design: Corner/cross_cutting_layers/version_pinning_stale_reference_blocks_approval
        """
        _cp, _nda, asset, _emp, disc = _setup_pinned_disclosure(api)
        # OCC-valid descriptive patch advances the asset version past the pin
        current_v = validate_success(api.get_asset(asset["id"], IP))["version"]
        validate_success(api.patch_asset(
            asset["id"],
            {"expected_asset_version": current_v, "description": "updated description"},
            IP,
        ))
        resp = api.transition_disclosure(
            disc["id"], {"to_status": "APPROVED"}, make_ip_counsel_headers("counsel_1")
        )
        validate_error(resp, ApiErrorId.ERR_STALE_REFERENCE)
        data = validate_success(api.get_disclosure(disc["id"], IP))
        assert data["status"] == "UNDER_REVIEW"


class TestExecuteCreatesSealedMarkedCopy:
    def test_cascaded_execute_creates_sealed_marked_copy(self, api):
        """PRD §3.5: "Executing seals the marked copy: an **EvidenceItem** is
        created directly in `SEALED` status with `source` of `MARKED_COPY`, its
        `disclosure_id` set to this request, its `review_id` empty, its
        `sha256` taken from `marking_sha256`, and `sealed_at` stamped at the
        current clock."

        Design: Corner/cross_cutting_layers/cascaded_execute_creates_sealed_marked_copy
        """
        cp = create_counterparty(legal_name="Mark Ltd", counterparty_type="CUSTOMER")
        nda = create_active_nda(
            cp["id"], template_version="t27", governing_law="ID",
            effective_date="2026-01-01T00:00:00Z", expiry_date="2027-01-01T00:00:00Z",
            survival_months=3, classification_ceiling="INTERNAL",
        )
        asset = create_registered_asset(
            title="Mark probe", description="x", classification="INTERNAL",
            owner_department="MKT", exposure_estimate_cents=100,
        )
        add_verified_measure(asset["id"], "TECHNICAL", title="t", evidence_uri="s3://ev/t.pdf")
        add_verified_measure(asset["id"], "PHYSICAL", title="p", evidence_uri="s3://ev/p.pdf")
        emp = create_employee_record(
            full_name="Exec Req", email="exec@x.com", department="MKT",
            role_title="Designer", access_clearance="STANDARD",
            hired_at="2026-05-01T00:00:00Z",
        )
        disc = create_under_review_disclosure(
            emp["id"], asset["id"], nda["id"],
            purpose="p", marking_protocol="ENCRYPTED_DELIVERY",
            planned_disclosure_date="2026-05-20T00:00:00Z",
        )
        validate_success(api.transition_disclosure(
            disc["id"], {"to_status": "APPROVED"}, make_ip_counsel_headers("counsel_1")
        ))
        data = validate_success(api.transition_disclosure(
            disc["id"],
            {"to_status": "EXECUTED", "marking_evidence_uri": "s3://ev/marked.bin",
             "marking_sha256": SHA256_CD},
            IP,
        ))
        assert data["status"] == "EXECUTED"
        items = validate_success(
            api.list_evidence_items(SEC, params={"disclosure_id": disc["id"]})
        )
        assert isinstance(items, list) and len(items) == 1
        assert items[0]["status"] == "SEALED"
        assert items[0]["source"] == "MARKED_COPY"
        assert_same_instant(
            items[0]["sealed_at"], "2026-05-01T00:00:00Z",
            label="sealed_at stamped at the current logical clock (default 2026-05-01)")


class TestImmediateConsistency:
    def test_immediate_visibility_patch_response_and_read(self, api):
        """PRD §2.10: "every such cascade is immediate: the mutation and all
        of its downstream effects are visible in the same response and in any
        subsequent read."
        PRD §3.1: "A successful update increments the asset's `version` by
        one."

        Design: Corner/consistency_model/immediate_visibility_patch_response_and_read
        """
        asset = validate_success(api.create_asset(
            create_asset_payload(title="Consistency probe", description="x",
                                 classification="INTERNAL", owner_department="ENG",
                                 exposure_estimate_cents=10), IP
        ), expected_status=201)
        patched = validate_success(api.patch_asset(
            asset["id"],
            {"expected_asset_version": asset["version"],
             "title": "Consistency probe renamed"},
            IP,
        ))
        assert patched["title"] == "Consistency probe renamed"
        assert patched["version"] == asset["version"] + 1
        fetched = validate_success(api.get_asset(asset["id"], IP))
        assert fetched["title"] == patched["title"]
        assert fetched["version"] == patched["version"], \
            "read-after-write identical within the same logical instant"
