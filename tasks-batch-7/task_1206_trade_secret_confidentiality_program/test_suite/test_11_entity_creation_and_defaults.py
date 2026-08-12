"""Entity creation, defaults, system-field handling, FK integrity, and the
list envelope (PRD §3.1, §3.3, §2.4, §2.2/§2.3)."""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    assert_same_instant,
    ApiErrorId,
    NON_EXISTENT_UUID,
    create_asset_payload,
    create_measure_payload,
    create_employee_payload,
    create_employee_record,
    create_active_employee,
    get_pending_ack_id,
    TEST_USERS,
)

IP = TEST_USERS["ip_counsel_headers"]
HR = TEST_USERS["hr_partner_headers"]
SEC = TEST_USERS["security_officer_headers"]


class TestAssetCreation:
    def test_create_asset_success_with_defaults(self, api):
        """PRD §3.1: "New assets start in `DRAFT` with both scores at zero,
        `protection_posture` of `DEFICIENT`, and an `active_grant_count` of
        zero."
        PRD §2.4: "**`version` (integer):** a system-managed integer that
        increments by one on every mutation of the resource."

        Design: Corner/entities/create_asset_success_with_defaults
        """
        resp = api.create_asset(
            create_asset_payload(
                title="Etch recipe", description="plasma etch",
                classification="RESTRICTED", owner_department="FAB",
                exposure_estimate_cents=200000,
            ), IP
        )
        data = validate_success(resp, expected_status=201)
        assert data["status"] == "DRAFT"
        assert data["score_operational"] == 0 and data["score_documentary"] == 0
        assert data["protection_posture"] == "DEFICIENT"
        assert data["active_grant_count"] == 0
        assert data["version"] == 1

    def test_create_asset_missing_required_title_returns_400(self, api):
        """PRD §2.12: "Tenth (10) aggregate and field-constraint rules —
        training currency, measure evidence, marking evidence, findings
        arithmetic, claim lines, hash format, email uniqueness — else
        `ERR_TRAINING_NOT_CURRENT`, `ERR_MEASURE_EVIDENCE_REQUIRED`,
        `ERR_MARKING_EVIDENCE_REQUIRED`, `ERR_INVALID_HASH`,
        `ERR_INVALID_REQUEST`, or `ERR_DUPLICATE_EMAIL`."
        PRD §3.1: "Counsel opens the register by drafting a **SecretAsset**
        with a human-readable `title`."

        Design: Corner/entities/create_asset_missing_required_title_returns_400
        """
        resp = api.create_asset(
            {"description": "no title", "classification": "INTERNAL",
             "owner_department": "ENG", "exposure_estimate_cents": 100},
            IP,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        data, meta = validate_paginated(api.list_assets(IP))
        assert meta["total_count"] == 0

    def test_create_asset_invalid_enum_rejected(self, api):
        """PRD §3.1: "a `classification` of `INTERNAL`, `CONFIDENTIAL`,
        `RESTRICTED`, or `CROWN_JEWEL` (in ascending sensitivity)."

        Design: Corner/entities/create_asset_invalid_enum_rejected
        """
        resp = api.create_asset(
            create_asset_payload(classification="TOP_SECRET"), IP
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_get_asset_not_found_returns_404(self, api):
        """PRD §2.10: "a body foreign key that names a nonexistent asset,
        employee, NDA, obligation, review, letter, notice, evidence item,
        training assignment, audit, measure, disclosure, or counterparty is
        rejected with `ERR_NOT_FOUND` (HTTP 404)."

        Design: Corner/entities/get_asset_not_found_returns_404
        """
        resp = api.get_asset(NON_EXISTENT_UUID, IP)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_create_asset_system_fields_input_ignored(self, api):
        """PRD §2.4: "**`id` (string):** a server-minted UUID with no type
        prefix."
        PRD §3.1: "New assets start in `DRAFT` with both scores at zero,
        `protection_posture` of `DEFICIENT`, and an `active_grant_count` of
        zero."

        Design: Corner/entities/create_asset_system_fields_input_ignored
        """
        resp = api.create_asset(
            create_asset_payload(
                title="Spoof attempt", description="x", classification="INTERNAL",
                owner_department="ENG", exposure_estimate_cents=100,
                id="11111111-2222-3333-4444-555555555555",
                status="REGISTERED", version=99,
            ), IP
        )
        data = validate_success(resp, expected_status=201)
        assert data["id"] != "11111111-2222-3333-4444-555555555555"
        assert data["status"] == "DRAFT" and data["version"] == 1


class TestMeasureFkIntegrity:
    def test_measure_create_with_unknown_asset_returns_404(self, api):
        """PRD §2.10: "a body foreign key that names a nonexistent asset,
        employee, NDA, obligation, review, letter, notice, evidence item,
        training assignment, audit, measure, disclosure, or counterparty is
        rejected with `ERR_NOT_FOUND` (HTTP 404)."

        Design: Corner/entities/measure_create_with_unknown_asset_returns_404
        """
        resp = api.create_measure(
            create_measure_payload(NON_EXISTENT_UUID, measure_type="PHYSICAL",
                                   title="orphan", evidence_uri=""),
            SEC,
        )
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestEmployeeCreateAutoSeeds:
    def test_employee_create_auto_seeds_ack_and_training(self, api):
        """PRD §3.3: "Creation cascades immediately: a fresh **Acknowledgment**
        for the employee is issued at the program's current policy version, and
        a `BASIC_TS` **TrainingAssignment** is auto-assigned with its `due_at`
        set thirty days after `hired_at`."
        PRD §3.3: "Each **Acknowledgment** carries the `employee_id`, the
        `policy_version` stamped from the program's `current_policy_version` at
        issuance, and a computed `due_at` ten days after creation."

        Design: Corner/entities/employee_create_auto_seeds_ack_and_training
        """
        resp = api.create_employee(
            create_employee_payload(
                full_name="Uma Fresh", email="uma@x.com", department="ENG",
                role_title="SDE", access_clearance="STANDARD",
                hired_at="2026-05-01T00:00:00Z",
            ), HR
        )
        emp = validate_success(resp, expected_status=201)
        assert emp["status"] == "PREBOARDING"

        acks, _meta = validate_paginated(
            api.list_acknowledgments(HR, params={"employee_id": emp["id"]})
        )
        assert len(acks) == 1
        assert acks[0]["status"] == "PENDING"
        assert acks[0]["policy_version"] == "v1"
        assert_same_instant(
            acks[0]["due_at"], "2026-05-11T00:00:00Z",
            label=f"due_at is created_at + 10 days; got {acks[0]['due_at']}")

        trainings, _meta2 = validate_paginated(
            api.list_training_assignments(HR, params={"employee_id": emp["id"]})
        )
        assert len(trainings) == 1
        assert trainings[0]["module"] == "BASIC_TS"
        assert trainings[0]["status"] == "ASSIGNED"
        assert_same_instant(
            trainings[0]["due_at"], "2026-05-31T00:00:00Z",
            label=f"due_at is hired_at + 30 days; got {trainings[0]['due_at']}")


class TestListPaginationDefaults:
    def test_list_pagination_defaults_applied(self, api):
        """PRD §2.3: "The `limit` parameter sets the maximum number of items
        returned; it defaults to 10, with a minimum of 1 and a maximum of 100.
        The `offset` parameter sets how many items to skip and defaults to 0."
        PRD §2.3: "Paginated list responses carry `limit`, `offset`,
        `total_count`, and `has_more` in the `meta` object of the envelope."

        Design: Corner/entities/list_pagination_defaults_applied
        """
        for title in ["A1", "A2", "A3"]:
            validate_success(api.create_asset(
                create_asset_payload(title=title, description="x",
                                     classification="INTERNAL", owner_department="ENG",
                                     exposure_estimate_cents=1), IP
            ), expected_status=201)
        data, meta = validate_paginated(api.list_assets(IP))
        assert meta["total_count"] == 3
        assert meta["has_more"] is False
        assert meta["limit"] == 10 and meta["offset"] == 0
        assert len(data) == 3


class TestEvidenceItemSeal:
    def test_evidence_seal_stamps_sealed_at_and_stores_hash_verbatim(self, api):
        """PRD §3.8: "Sealing — `COLLECTED → SEALED` — is a security step that
        stamps `sealed_at`; a sealed item's content fields are no longer
        modifiable."
        PRD §3.8: "An **EvidenceItem** is collected by security into a review
        with `review_id`, a `source` of `FORENSIC_IMAGE`, `EMAIL_EXPORT`,
        `ACCESS_LOG`, `DEVICE_IMAGE`, or `MARKED_COPY`, a `sha256` content hash,
        and a non-negative `byte_size`."

        Design: Corner/entities/evidence_item_has_no_update_endpoint
        """
        # PRD §3.6/§3.8 precondition: a manual forensic review may be opened
        # only while the employee is ACTIVE or NOTICE (or within 90 days after
        # departure), so the fixture must activate the employee first.
        emp = create_active_employee(
            complete_training=False,
            full_name="Vic Probe", email="vic@x.com", department="ENG",
            role_title="SDE", access_clearance="STANDARD",
            hired_at="2026-05-01T00:00:00Z",
        )
        resp = api.create_forensic_review(
            {"employee_id": emp["id"], "trigger_reason": "POLICY"}, IP
        )
        review = validate_success(resp, expected_status=201)
        sha = "d" * 64
        resp = api.create_evidence_item(
            {"review_id": review["id"], "source": "EMAIL_EXPORT",
             "sha256": sha, "byte_size": 512}, SEC
        )
        ev = validate_success(resp, expected_status=201)
        data = validate_success(api.transition_evidence_item(ev["id"], {"to_status": "SEALED"}, SEC))
        assert data["status"] == "SEALED"
        assert_same_instant(
            data["sealed_at"], "2026-05-01T00:00:00Z",
            label="sealed_at is stamped at the current logical clock (default 2026-05-01)")
        fetched = validate_success(api.get_evidence_item(ev["id"], SEC))
        assert fetched["sha256"] == sha, "content hash stored verbatim"
