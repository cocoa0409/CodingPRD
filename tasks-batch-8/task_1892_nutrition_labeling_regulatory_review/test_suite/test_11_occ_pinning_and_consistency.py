"""Optimistic concurrency on the product version, panel-snapshot pinning at
submit-review, and immediate (synchronous) visibility of mutations."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    approve_label,
    assert_iso8601_three_fractional,
    compute_panel,
    create_client,
    create_ingredient,
    create_label_draft,
    create_label_version_payload,
    create_product,
    create_recipe,
    get_label_version,
    get_product,
    make_client_rep_headers,
    release_label,
    setup_wafer_workspace,
    submit_label,
    validate_error,
    validate_success,
    reject_label,
)

ADMIN = TEST_USERS["platform_admin_headers"]
ANALYST = TEST_USERS["label_analyst_headers"]


class TestOptimisticConcurrency:
    def test_occ_stale_version_on_label_create(self, api):
        """PRD §2.6: "Exactly two write operations participate in optimistic
        concurrency control, both pinned to the parent `Product`: creating a
        label-version draft, and releasing a label version. Each of these
        requests must carry the field `expected_product_version`, holding the
        value of the product's `version` as the client last observed it. If
        another writer has advanced the product's version since that
        observation — for example because a draft was created that withdrew
        the prior draft, or a competing release superseded the prior release —
        the request is rejected with `ERR_STALE_VERSION` (HTTP 412),
        preventing the caller from acting on a product state it never saw."

        Design: Corner/cross_cutting_layers/xlayer_occ_stale_version_on_label_create
        """
        ws = setup_wafer_workspace()
        # The version observed at product creation is stale: LV1's creation
        # already advanced the product's version past it.
        payload = create_label_version_payload(
            ws["racc"]["id"], ws["product"]["version"],
            ws["label"]["ingredient_statement_text"],
            ws["label"]["contains_text"],
            declared_format="SIMPLIFIED",
        )
        resp = api.create_label_version(ws["product"]["id"], payload, ANALYST)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, expected_status=412)
        assert get_label_version(ws["label"]["id"])["review_status"] == "DRAFT", (
            "the rejected write leaves the existing draft untouched"
        )

    def test_occ_stale_version_on_release(self, api):
        """PRD §2.6: "Exactly two write operations participate in optimistic
        concurrency control, both pinned to the parent `Product`: creating a
        label-version draft, and releasing a label version. Each of these
        requests must carry the field `expected_product_version`, holding the
        value of the product's `version` as the client last observed it."
        PRD §3.6: "Release is the second optimistic-concurrency point: the
        request must carry `expected_product_version` matching the product's
        current `version`, failing which `ERR_STALE_VERSION` is returned."

        Design: Corner/cross_cutting_layers/xlayer_occ_stale_version_on_release
        """
        ws = setup_wafer_workspace()
        lv_a = ws["label"]
        submit_label(lv_a["id"])
        lv_b = create_label_draft(ws["product"]["id"], ws["racc"]["id"],
                                  declared_format="SIMPLIFIED",
                                  statement_recipe_id=ws["recipe"]["id"])
        submit_label(lv_b["id"])
        approve_label(lv_a["id"])
        approve_label(lv_b["id"])

        observed = get_product(ws["product"]["id"])["version"]
        release_label(ws["product"]["id"], lv_a["id"], ws["client"]["id"])

        # LV_B's release carries the product version observed before LV_A's
        # release advanced it.
        resp = api.release_label(
            lv_b["id"], {"expected_product_version": observed},
            ws["quality_manager_headers"])
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, expected_status=412)
        assert get_label_version(lv_b["id"])["release_status"] == "NOT_RELEASED"

    def test_product_version_increments_on_label_create(self, api):
        """PRD §3.6: "The new draft initializes with `review_status` `DRAFT`,
        `release_status` `NOT_RELEASED`, `review_round` 0, and `prepared_by`
        set to the creating analyst's `X-User-ID`; the product's `version`
        increments as part of the same write."
        PRD §2.4: "Every resource type in the system — clients, products,
        ingredients, recipes, lab analyses, nutrient panels, RACC assignments,
        label versions, claim assessments, market variants, format checks,
        artwork audits, and audit findings — carries a uniform set of
        system-managed fields: an `id`, which is a server-minted UUID with no
        type prefix; a `created_at` timestamp in ISO 8601 UTC form with three
        fractional digits; an `updated_at` timestamp of the same form,
        refreshed on every mutation; and a `version` integer that increments
        by one on every mutation."

        Design: Corner/cross_cutting_layers/xlayer_product_version_increments_on_label_create
        """
        ws = setup_wafer_workspace(with_label=False)
        before = get_product(ws["product"]["id"])["version"]
        create_label_draft(ws["product"]["id"], ws["racc"]["id"],
                           statement_recipe_id=ws["recipe"]["id"])
        after = get_product(ws["product"]["id"])["version"]
        assert after == before + 1, "a single increment per label-draft create"


class TestVersionPinning:
    def test_version_pinning_snapshot_retained(self, api):
        """PRD §3.6: "On success the submission pins `panel_snapshot_id` to
        the most recently created `CURRENT` panel of the recipe with the
        matching method, advances `review_round` by one, auto-creates a format
        check, recomputes `content_status`, moves `review_status` to
        `IN_REVIEW`, and increments the label's `version`."
        PRD §3.6: "Rejection moves the label from `IN_REVIEW` back to `DRAFT`
        — the same `ERR_LABEL_NOT_IN_REVIEW` guard applies — optionally
        recording a free-text `reason`, clearing `approved_by`, and
        deliberately leaving the declared content untouched:
        `ingredient_statement_text`, `contains_text`, `declared_format`,
        `declared_type_size_in`, and the pinned `panel_snapshot_id` all
        survive rejection unchanged, so the analyst can correct and resubmit
        without re-entering the artwork facts."

        Design: Corner/cross_cutting_layers/xlayer_version_pinning_snapshot_retained
        """
        ws = setup_wafer_workspace()
        submitted = submit_label(ws["label"]["id"])
        assert submitted["panel_snapshot_id"] == ws["panel"]["id"]

        # A second DATABASE panel computed later must not retarget the pin.
        panel2 = compute_panel(ws["recipe"]["id"], method="DATABASE")
        held = get_label_version(ws["label"]["id"])
        assert held["panel_snapshot_id"] == ws["panel"]["id"]

        reject_label(ws["label"]["id"], reason="re-pin")
        resubmitted = submit_label(ws["label"]["id"])
        assert resubmitted["panel_snapshot_id"] == panel2["id"], (
            "resubmission pins the most recently created CURRENT panel"
        )


class TestImmediateConsistency:
    def test_immediate_visibility(self, api):
        """PRD §2.2: "Unless otherwise noted, operations that create or modify
        a resource will return the created or updated resource object in the
        data field."
        PRD §3.2: "A `ClientRep` locks a recipe that is currently `DRAFT` —
        locking from any other status is rejected with
        `ERR_INVALID_STATE_TRANSITION` — and the lock sets the recipe's
        `status` to `LOCKED` and increments its `version`."
        PRD §2.4: "Every resource type in the system — clients, products,
        ingredients, recipes, lab analyses, nutrient panels, RACC assignments,
        label versions, claim assessments, market variants, format checks,
        artwork audits, and audit findings — carries a uniform set of
        system-managed fields: an `id`, which is a server-minted UUID with no
        type prefix; a `created_at` timestamp in ISO 8601 UTC form with three
        fractional digits; an `updated_at` timestamp of the same form,
        refreshed on every mutation; and a `version` integer that increments
        by one on every mutation."

        Design: Corner/consistency_model/consistency_immediate_visibility
        """
        client = create_client()
        product = create_product(client)
        wafer = create_ingredient(client, name="Wafers")
        recipe = create_recipe(product["id"], client["id"],
                               [{"ingredient_id": wafer["id"], "quantity_g": 100}])

        locked = validate_success(
            api.lock_recipe(recipe["id"], make_client_rep_headers(client["id"])),
            200,
        )
        assert locked["status"] == "LOCKED", "the write response carries the mutation"

        fetched = validate_success(api.get_recipe(recipe["id"], ADMIN), 200)
        assert fetched["status"] == "LOCKED", (
            "the follow-up read agrees — no eventual-consistency lag"
        )
        assert fetched["version"] == recipe["version"] + 1
        assert_iso8601_three_fractional(fetched["updated_at"], "updated_at")

        panel = validate_success(
            api.create_nutrient_panel(recipe["id"], {"method": "DATABASE"}, ANALYST),
            201,
        )
        assert panel["status"] == "CURRENT"
        assert panel["kcal_per_100g"] == pytest.approx(400.0), (
            "computed fields are present in the write response"
        )
