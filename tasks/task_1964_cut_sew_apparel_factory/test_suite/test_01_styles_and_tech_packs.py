"""Styles, tech packs, and the grading foundation (PRD §3.1)."""
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    api_client,
    assert_style,
    create_operation_spec_payload,
    create_style,
    create_style_payload,
    create_draft_tech_pack,
    create_tech_pack_payload,
    add_operation_spec,
    approve_tech_pack,
    get_style,
    get_success_data,
    submit_tech_pack,
    validate_error,
    validate_success,
)

MERCH = TEST_USERS["merchandiser_headers"]
PM = TEST_USERS["plant_manager_headers"]
ANY = TEST_USERS["any_headers"]


class TestStyleCreation:
    def test_create_style_applies_defaults_and_system_fields(self):
        """PRD §3.1: "A new style starts with `status` `DRAFT`,
        `certification_status` `UNCERTIFIED`, its content fields unset
        (`domestic_content_pct_cost` and `domestic_component_ratio` null,
        `content_qualification` `UNDETERMINED`), `active_tech_pack_id` null,
        and `created_by_user_id` stamped from the caller."

        Design: Corner/entities/create_style_applies_defaults_and_system_fields
        """
        payload = create_style_payload(
            style_code="ST-E1", size_run=["S", "M", "L"],
        )
        resp = api_client.create_style(payload, MERCH)
        data = validate_success(resp, 201)
        assert_style(data)
        assert data["status"] == "DRAFT"
        assert data["certification_status"] == "UNCERTIFIED"
        assert data["content_qualification"] == "UNDETERMINED"
        assert data["domestic_content_pct_cost"] is None
        assert data["domestic_component_ratio"] is None
        assert data["active_tech_pack_id"] is None
        assert data["created_by_user_id"] == "u-m1"

    def test_create_style_missing_required_style_code_returns_invalid_request(self):
        """PRD §2.6: "Required fields present, types correct, enum members
        valid, scalar ranges respected ... otherwise `ERR_INVALID_REQUEST`."
        PRD §3.1: a Style is created "by supplying a `style_code` (unique
        across all styles), an optional `description`, the `base_size` ...
        and an ordered `size_run`".

        Design: Corner/entities/create_style_missing_required_style_code_returns_invalid_request
        """
        payload = create_style_payload()
        del payload["style_code"]
        resp = api_client.create_style(payload, MERCH)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestTechPackBasics:
    def test_create_tech_pack_with_bogus_style_returns_not_found(self):
        """PRD §2.5: "Request bodies that reference other resources by foreign
        key — `style_id`, ... — are held to the same standard: each referenced
        resource must exist. Any existence failure is rejected with
        `ERR_NOT_FOUND` (HTTP 404)."

        Design: Corner/entities/create_tech_pack_with_bogus_style_returns_not_found
        """
        payload = create_tech_pack_payload(style_id=NON_EXISTENT_UUID)
        resp = api_client.create_tech_pack(payload, MERCH)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_create_operation_spec_invalid_enum_returns_invalid_request(self):
        """PRD §3.1: "a `machine_type` of `SINGLE_NEEDLE`, `OVERLOCK`,
        `COVERSTITCH`, `BUTTONHOLE`, or `MANUAL`".
        PRD §2.6: "Required fields present, types correct, enum members valid
        ... otherwise `ERR_INVALID_REQUEST`."

        Design: Corner/entities/create_operation_spec_invalid_enum_returns_invalid_request
        """
        style = create_style(style_code="ST-E2")
        pack = create_draft_tech_pack(style["id"], MERCH)
        payload = create_operation_spec_payload(
            tech_pack_id=pack["id"], machine_type="GLUE"
        )
        resp = api_client.create_operation_spec(payload, MERCH)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_duplicate_operation_sequence_rejected(self):
        """PRD §3.1: "a `sequence_no` (an integer of at least 1, unique within
        the pack — a reused number is rejected with
        `ERR_DUPLICATE_OPERATION_SEQUENCE`, HTTP 409)".

        Design: Corner/validations/duplicate_operation_sequence_rejected
        """
        style = create_style(style_code="ST-V9")
        pack = create_draft_tech_pack(style["id"], MERCH)
        add_operation_spec(pack["id"], MERCH, sequence_no=1, name="join")
        payload = create_operation_spec_payload(
            tech_pack_id=pack["id"], sequence_no=1, name="hem", sam_seconds=30,
            piece_rate_cents=5,
        )
        resp = api_client.create_operation_spec(payload, MERCH)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_OPERATION_SEQUENCE)


class TestTechPackSubmit:
    def test_submit_pack_without_operations_rejected(self):
        """PRD §3.1: "The pack must currently be `DRAFT` (otherwise
        `ERR_INVALID_STATE_TRANSITION`, HTTP 409), must have at least one
        `OperationSpec` (otherwise `ERR_NO_OPERATION_SPECS`, HTTP 409)".

        Design: Corner/errors/submit_pack_without_operations_rejected
        """
        style = create_style(style_code="ST-R8")
        pack = create_draft_tech_pack(style["id"], MERCH)
        resp = api_client.submit_tech_pack(pack["id"], MERCH)
        validate_error(resp, ApiErrorId.ERR_NO_OPERATION_SPECS)
        pack_after = get_success_data(api_client.get_tech_pack(pack["id"], ANY))
        assert pack_after["status"] == "DRAFT"

    def test_submit_pending_pack_returns_invalid_state(self):
        """PRD §3.1: "The pack must currently be `DRAFT` (otherwise
        `ERR_INVALID_STATE_TRANSITION`, HTTP 409)".

        Design: Corner/state_machines/submit_pending_pack_returns_invalid_state
        """
        style = create_style(style_code="ST-S1")
        pack = create_draft_tech_pack(style["id"], MERCH)
        add_operation_spec(pack["id"], MERCH)
        submit_tech_pack(pack["id"], MERCH)
        resp = api_client.submit_tech_pack(pack["id"], MERCH)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
        pack_after = get_success_data(api_client.get_tech_pack(pack["id"], ANY))
        assert pack_after["status"] == "PENDING_APPROVAL"


class TestTechPackEditability:
    def test_edit_approved_pack_rejected(self):
        """PRD §3.1: "Both kinds of line are accepted only while the referenced
        pack is `DRAFT`; once the pack has left `DRAFT`, creation attempts fail
        with `ERR_TECH_PACK_NOT_EDITABLE` (HTTP 409)".

        Design: Corner/errors/edit_approved_pack_rejected
        """
        style, pack, _ops = _approved_pack_with_one_op("ST-R1")
        payload = create_operation_spec_payload(
            tech_pack_id=pack["id"], sequence_no=2, name="hem", sam_seconds=30,
            piece_rate_cents=5,
        )
        resp = api_client.create_operation_spec(payload, MERCH)
        validate_error(resp, ApiErrorId.ERR_TECH_PACK_NOT_EDITABLE)


class TestTechPackReview:
    def test_tech_pack_self_review_rejected(self):
        """PRD §2.10: "A tech pack may not be reviewed by the `Merchandiser`
        who created it: the reviewer's `X-User-ID` must differ from the pack's
        `created_by_user_id`, or the review is rejected with
        `ERR_SOD_SELF_REVIEW` (HTTP 403)."

        Design: Corner/validations/tech_pack_self_review_rejected
        """
        style = create_style(style_code="ST-V2")
        pack = create_draft_tech_pack(style["id"], MERCH)  # creator u-m1
        add_operation_spec(pack["id"], MERCH)
        submit_tech_pack(pack["id"], MERCH)
        # Same human (u-m1) now holds the PlantManager role for this call.
        pm_as_creator = TEST_USERS["pm_as_u_m1_headers"]
        resp = api_client.review_tech_pack(
            pack["id"],
            {"decision": "APPROVE", "expected_style_version": style["version"]},
            pm_as_creator,
        )
        validate_error(resp, ApiErrorId.ERR_SOD_SELF_REVIEW)
        pack_after = get_success_data(api_client.get_tech_pack(pack["id"], ANY))
        assert pack_after["status"] == "PENDING_APPROVAL"

    def test_review_superseded_pack_returns_not_pending_review(self):
        """PRD §3.1: "`SUPERSEDED` is terminal for a pack." and "The pack must
        be `PENDING_APPROVAL` (otherwise `ERR_TECH_PACK_NOT_PENDING_REVIEW`,
        HTTP 409)".

        Design: Corner/state_machines/review_superseded_pack_returns_not_pending_review
        """
        style = create_style(style_code="ST-S5")
        pack_a = create_draft_tech_pack(style["id"], MERCH, version_no=1)
        add_operation_spec(pack_a["id"], MERCH)
        submit_tech_pack(pack_a["id"], MERCH)
        style = get_style(style["id"])
        api_resp = api_client.review_tech_pack(
            pack_a["id"],
            {"decision": "APPROVE", "expected_style_version": style["version"]},
            PM,
        )
        validate_success(api_resp, 200)
        pack_b = create_draft_tech_pack(style["id"], MERCH, version_no=2)
        add_operation_spec(pack_b["id"], MERCH)
        submit_tech_pack(pack_b["id"], MERCH)
        style = get_style(style["id"])
        api_resp = api_client.review_tech_pack(
            pack_b["id"],
            {"decision": "APPROVE", "expected_style_version": style["version"]},
            PM,
        )
        validate_success(api_resp, 200)
        # pack_a is now SUPERSEDED; attempt to review it again with a fresh version.
        style = get_style(style["id"])
        resp = api_client.review_tech_pack(
            pack_a["id"],
            {"decision": "APPROVE", "expected_style_version": style["version"]},
            PM,
        )
        validate_error(resp, ApiErrorId.ERR_TECH_PACK_NOT_PENDING_REVIEW)
        pack_a_after = get_success_data(api_client.get_tech_pack(pack_a["id"], ANY))
        assert pack_a_after["status"] == "SUPERSEDED"


class TestTechPackRevisionCycleAndSupersede:
    def test_revision_cycle_rejected_pack_returns_to_draft(self):
        """PRD §3.1: "A `REJECTED` pack returns to `DRAFT` when a
        `Merchandiser` revises it — the from-state must be `REJECTED` or the
        revise is rejected with `ERR_INVALID_STATE_TRANSITION` — so the loop
        `DRAFT` → `PENDING_APPROVAL` → `REJECTED` → `DRAFT` is cyclic".

        Design: Difficulty/non_linear_state_machine/tech_pack_revision_cycle_and_supersede
        """
        style = create_style(style_code="ST-TP1")
        pack = create_draft_tech_pack(style["id"], MERCH, version_no=1)
        assert pack["status"] == "DRAFT"
        add_operation_spec(pack["id"], MERCH)
        pack = submit_tech_pack(pack["id"], MERCH)
        assert pack["status"] == "PENDING_APPROVAL"
        pack = get_success_data(api_client.review_tech_pack(
            pack["id"],
            {"decision": "REJECT", "expected_style_version": style["version"]},
            PM,
        ))
        assert pack["status"] == "REJECTED"
        pack = get_success_data(api_client.revise_tech_pack(pack["id"], MERCH))
        assert pack["status"] == "DRAFT"

    def test_sibling_approval_supersedes_prior_approved_pack(self):
        """PRD §3.1: "any previously `APPROVED` sibling pack of the same style
        is automatically moved to `SUPERSEDED` (its own `version` incremented);
        the style's `active_tech_pack_id` is re-pointed to the newly approved
        pack".

        Design: Difficulty/non_linear_state_machine/tech_pack_revision_cycle_and_supersede
        """
        style = create_style(style_code="ST-TP1")
        pack_a = create_draft_tech_pack(style["id"], MERCH, version_no=1)
        add_operation_spec(pack_a["id"], MERCH, sam_seconds=60)
        submit_tech_pack(pack_a["id"], MERCH)
        # Revision loop on pack A: reject then revise back to DRAFT.
        get_success_data(api_client.review_tech_pack(
            pack_a["id"],
            {"decision": "REJECT", "expected_style_version": style["version"]},
            PM,
        ))
        get_success_data(api_client.revise_tech_pack(pack_a["id"], MERCH))
        submit_tech_pack(pack_a["id"], MERCH)
        style = get_style(style["id"])
        pack_a = get_success_data(api_client.review_tech_pack(
            pack_a["id"],
            {"decision": "APPROVE", "expected_style_version": style["version"]},
            PM,
        ))
        assert pack_a["status"] == "APPROVED"
        # Second pack approved -> pack A auto-superseded.
        pack_b = create_draft_tech_pack(
            style["id"], MERCH, version_no=2,
            base_measurements=[{"point": "chest", "base_value_in": 20.5}],
            labor_cost_cents_per_unit=820,
        )
        add_operation_spec(pack_b["id"], MERCH, sam_seconds=58)
        submit_tech_pack(pack_b["id"], MERCH)
        style = get_style(style["id"])
        pack_b = get_success_data(api_client.review_tech_pack(
            pack_b["id"],
            {"decision": "APPROVE", "expected_style_version": style["version"]},
            PM,
        ))
        assert pack_b["status"] == "APPROVED"
        pack_a_after = get_success_data(api_client.get_tech_pack(pack_a["id"], ANY))
        assert pack_a_after["status"] == "SUPERSEDED"
        style_after = get_style(style["id"])
        assert style_after["active_tech_pack_id"] == pack_b["id"]


class TestOccTechPackReview:
    def test_occ_tech_pack_review_stale_style_version(self):
        """PRD §2.7: "If the style's version has advanced since — for instance
        because another pack approval re-pointed `active_tech_pack_id` — the
        review is rejected with `ERR_STALE_VERSION` (HTTP 412)".

        Design: Corner/cross_cutting_layers/occ_tech_pack_review_stale_style_version
        """
        style = create_style(style_code="ST-X1")
        pack_a = create_draft_tech_pack(style["id"], MERCH, version_no=1)
        add_operation_spec(pack_a["id"], MERCH)
        submit_tech_pack(pack_a["id"], MERCH)
        stale_version = style["version"]
        get_success_data(api_client.review_tech_pack(
            pack_a["id"],
            {"decision": "APPROVE", "expected_style_version": stale_version},
            PM,
        ))
        pack_b = create_draft_tech_pack(
            style["id"], MERCH, version_no=2,
            base_measurements=[{"point": "chest", "base_value_in": 20.5}],
            labor_cost_cents_per_unit=810,
        )
        add_operation_spec(pack_b["id"], MERCH, sam_seconds=58)
        submit_tech_pack(pack_b["id"], MERCH)
        resp = api_client.review_tech_pack(
            pack_b["id"],
            {"decision": "APPROVE", "expected_style_version": stale_version},
            PM,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        pack_b_after = get_success_data(api_client.get_tech_pack(pack_b["id"], ANY))
        assert pack_b_after["status"] == "PENDING_APPROVAL"
        fresh_version = get_style(style["id"])["version"]
        pack_b = get_success_data(api_client.review_tech_pack(
            pack_b["id"],
            {"decision": "APPROVE", "expected_style_version": fresh_version},
            PM,
        ))
        assert pack_b["status"] == "APPROVED"
        pack_a_after = get_success_data(api_client.get_tech_pack(pack_a["id"], ANY))
        assert pack_a_after["status"] == "SUPERSEDED"


def _approved_pack_with_one_op(style_code):
    """Style + 1-op pack approved. Returns (style, pack, ops)."""
    style = create_style(style_code=style_code)
    pack = create_draft_tech_pack(style["id"], MERCH)
    ops = [add_operation_spec(pack["id"], MERCH)]
    pack = approve_tech_pack(pack["id"], PM)
    return get_style(style["id"]), pack, ops
