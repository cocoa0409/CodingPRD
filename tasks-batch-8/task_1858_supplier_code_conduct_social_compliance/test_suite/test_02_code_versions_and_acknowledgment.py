"""Code of Conduct versions and the supplier acknowledgment chain (PRD §3.1, §2.7)."""
from test_helpers import (
    ADMIN,
    OFFICER,
    ApiErrorId,
    acknowledge_code,
    assert_code_acknowledgment,
    assert_code_version,
    create_code_acknowledgment_payload,
    create_code_version,
    create_code_version_payload,
    create_supplier,
    get_supplier,
    make_auditor_headers,
    make_supplier_contact_headers,
    validate_error,
    validate_success,
    create_auditor,
)


class TestAcknowledgmentSupersedeChain:
    def test_acknowledgment_supersede_chain(self, api):
        """PRD §3.1: "On success, `acknowledged_at` is stamped from the logical
        clock, and `supersedes_acknowledgment_id` is set to the supplier's
        previously latest acknowledgment — the one with the greatest
        `acknowledged_at`, with ties broken by the greatest `created_at` —
        remaining null on the supplier's first acknowledgment."
        PRD §3.1: "The acknowledgment increments the supplier's `version` by one
        and sets the supplier's `current_code_version_id` to the acknowledged
        version; a supplier's first acknowledgment also moves it automatically
        from `ONBOARDING` to `ACTIVE`."

        Design: Corner/entities/acknowledgment_supersede_chain
        """
        cv1 = create_code_version(version_label="CoC v1.0",
                                  zero_tolerance_categories=("FORCED_LABOR",))
        cv2 = create_code_version(
            version_label="CoC v2.0", effective_from="2026-06-01T00:00:00Z",
            zero_tolerance_categories=("FORCED_LABOR", "CHILD_LABOR"),
        )
        supplier = create_supplier(legal_name="Umbrella Goods", sector="FOOD")
        v0 = supplier["version"]

        ack1 = acknowledge_code(supplier, cv1["id"])
        assert_code_acknowledgment(ack1)
        assert ack1["supersedes_acknowledgment_id"] is None, (
            "the first acknowledgment supersedes nothing"
        )
        after_first = get_supplier(supplier["id"])
        assert after_first["status"] == "ACTIVE", (
            "the first acknowledgment moves ONBOARDING -> ACTIVE"
        )
        assert after_first["current_code_version_id"] == cv1["id"]
        assert after_first["version"] == v0 + 1, (
            "the acknowledgment increments the supplier version by one"
        )

        ack2 = acknowledge_code(after_first, cv2["id"])
        assert ack2["supersedes_acknowledgment_id"] == ack1["id"], (
            "the second acknowledgment points at the previously latest one"
        )
        after_second = get_supplier(supplier["id"])
        assert after_second["current_code_version_id"] == cv2["id"]
        assert after_second["version"] == after_first["version"] + 1


class TestAcknowledgmentOptimisticConcurrency:
    def test_acknowledgment_stale_version_rejected(self, api):
        """PRD §2.7: "The request must carry `expected_supplier_version`,
        holding the `version` of the target Supplier as the caller last observed
        it. If the value does not match the supplier's current `version` —
        because a successful acknowledgment legitimately supersedes the
        supplier's current code version and advances `Supplier.version` — the
        create is rejected with `ERR_STALE_VERSION` (HTTP 412), and the caller
        must re-read the supplier before acknowledging."

        Design: Corner/cross_cutting_complexity_layers/acknowledgment_stale_version_rejected
        """
        cv1 = create_code_version(version_label="CoC v1.0")
        cv2 = create_code_version(version_label="CoC v2.0",
                                  effective_from="2026-06-01T00:00:00Z")
        supplier = create_supplier(legal_name="Sierra D", sector="FOOD")
        observed_v = supplier["version"]
        contact = make_supplier_contact_headers(supplier["id"])

        ack1 = validate_success(
            api.create_code_acknowledgment(
                create_code_acknowledgment_payload(
                    supplier["id"], cv1["id"], observed_v
                ),
                contact,
            ),
            201,
        )
        assert ack1["code_version_id"] == cv1["id"]

        # Replay with the pre-first-ack version: stale.
        stale_resp = api.create_code_acknowledgment(
            create_code_acknowledgment_payload(
                supplier["id"], cv2["id"], observed_v
            ),
            contact,
        )
        validate_error(stale_resp, ApiErrorId.ERR_STALE_VERSION, 412)

        mid = get_supplier(supplier["id"])
        assert mid["version"] == observed_v + 1, (
            "the stale write changed nothing: version advanced only by ack1"
        )
        assert mid["current_code_version_id"] == cv1["id"]

        # Re-read and re-send with the fresh version: succeeds.
        ack2 = validate_success(
            api.create_code_acknowledgment(
                create_code_acknowledgment_payload(
                    supplier["id"], cv2["id"], mid["version"]
                ),
                contact,
            ),
            201,
        )
        assert ack2["supersedes_acknowledgment_id"] == ack1["id"]
        final = get_supplier(supplier["id"])
        assert final["version"] == mid["version"] + 1
        assert final["current_code_version_id"] == cv2["id"]


class TestCodeVersionStates:
    def test_acknowledgment_with_draft_code_version_rejected(self, api):
        """PRD §3.1: "The referenced code version must be `PUBLISHED` —
        otherwise the filing is rejected with
        `ERR_CODE_VERSION_NOT_PUBLISHED`"

        Design: Corner/validations/ack_with_draft_code_version_rejected
        """
        cv = create_code_version(version_label="CoC draft", publish=False)
        assert cv["status"] == "DRAFT"
        supplier = create_supplier(legal_name="Papa A", sector="FOOD")
        resp = api.create_code_acknowledgment(
            create_code_acknowledgment_payload(
                supplier["id"], cv["id"], supplier["version"]
            ),
            make_supplier_contact_headers(supplier["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_CODE_VERSION_NOT_PUBLISHED)
        assert get_supplier(supplier["id"])["status"] == "ONBOARDING", (
            "a rejected acknowledgment leaves the supplier ONBOARDING"
        )

    def test_code_version_retired_is_terminal(self, api):
        """PRD §3.1: "Any transition attempted from a from-state that does not
        allow it, such as publishing a version that is not `DRAFT` or retiring
        one that is not `PUBLISHED`, is rejected with
        `ERR_CODE_VERSION_INVALID_STATE`. Retirement is not retroactive:
        suppliers that already acknowledged the version keep their
        `current_code_version_id` unchanged, and `RETIRED` is terminal."

        Design: Corner/state_machines/code_version_retired_transition_rejected
        """
        cv = create_code_version(version_label="CoC v9", publish=False)
        published = validate_success(
            api.transition_code_version(cv["id"], {"to_status": "PUBLISHED"}, ADMIN)
        )
        assert_code_version(published)
        retired = validate_success(
            api.transition_code_version(cv["id"], {"to_status": "RETIRED"}, ADMIN)
        )
        assert retired["status"] == "RETIRED"
        resp = api.transition_code_version(
            cv["id"], {"to_status": "PUBLISHED"}, ADMIN
        )
        validate_error(resp, ApiErrorId.ERR_CODE_VERSION_INVALID_STATE)
        reread = validate_success(api.get_code_version(cv["id"], OFFICER))
        assert reread["status"] == "RETIRED", "RETIRED is terminal"


class TestCodeVersionRbac:
    def test_code_version_create_forbidden_for_auditor(self, api):
        """PRD §2.1: "Access to each operation is restricted by role; an attempt
        to perform an action outside the caller's designated role is rejected
        with `ERR_INSUFFICIENT_PERMISSIONS`."
        PRD §4: POST /code-versions is authorized for SourcingProgramAdmin only.

        Design: Corner/rbac/code_version_create_forbidden_for_auditor
        """
        auditor = create_auditor()
        resp = api.create_code_version(
            create_code_version_payload(version_label="CoC rogue"),
            make_auditor_headers(auditor["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS, 403)
