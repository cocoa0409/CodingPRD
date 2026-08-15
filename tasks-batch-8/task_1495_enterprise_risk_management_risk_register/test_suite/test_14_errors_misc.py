"""Corner: errors — kri_observation_on_draft_kri_rejected and
category_cycle_rejected."""
import pytest

from test_helpers import (
    api_client,
    validate_success, validate_error,
    ApiErrorId,
    create_category,
    create_kri,
    make_risk_manager_headers,
    USER_RISK_MANAGER,
)


class TestKriObservationOnDraftKri:
    def test_observation_on_draft_kri_rejected(self):
        """PRD §3.6: "Three guards apply, in precedence order: the indicator
        must be `ACTIVE` (`ERR_KRI_NOT_ACTIVE`)".
        PRD §3.6: "it may change only while the indicator is `ACTIVE`".

        Design: Corner/errors/kri_observation_on_draft_kri_rejected
        """
        cat = create_category(name="DK")
        kri = create_kri(
            cat["id"], name="Dormant", direction="ABOVE",
            amber_threshold=50, red_threshold=75,
            min_observation_interval_days=0,
        )
        # Never activated → still DRAFT
        res = api_client.create_kri_observation(
            kri["id"],
            {"observed_value": 10, "observed_at": "2026-08-01T00:00:00Z"},
            make_risk_manager_headers(USER_RISK_MANAGER),
        )
        validate_error(res, ApiErrorId.ERR_KRI_NOT_ACTIVE.value)


class TestCategoryCycle:
    """PRD §3.1: "The parent chain of a category must never contain the
    category itself: any create or reparenting that would close such a loop
    is rejected with `ERR_CATEGORY_CYCLE`, and reparenting is likewise
    rejected when the proposed new parent is one of the category's own
    descendants." """

    def _build_taxonomy(self):
        """Root -> Child -> Grandchild; Root also has Sibling."""
        root = create_category(name="Root")
        child = create_category(name="Child", parent_category_id=root["id"])
        grandchild = create_category(name="Grandchild",
                                       parent_category_id=child["id"])
        sibling = create_category(name="Sibling",
                                    parent_category_id=root["id"])
        return {
            "root": root, "child": child,
            "grandchild": grandchild, "sibling": sibling,
        }

    def test_reparent_under_own_descendant_rejected(self):
        """PRD §3.1: "reparenting is likewise rejected when the proposed new
        parent is one of the category's own descendants."

        Design: Corner/errors/category_cycle_rejected
        """
        t = self._build_taxonomy()
        # Root -> Grandchild would close a cycle
        res = api_client.reparent_category(
            t["root"]["id"],
            {"parent_category_id": t["grandchild"]["id"]},
            make_risk_manager_headers(USER_RISK_MANAGER),
        )
        validate_error(res, ApiErrorId.ERR_CATEGORY_CYCLE.value)

    def test_reparent_under_sibling_subtree_succeeds(self):
        """PRD §3.1: "A successful reparenting increments the category's
        `version` by 1."
        PRD §3.1: "the direct children of a category are listed through its
        subcategories view".

        Design: Corner/errors/category_cycle_rejected
        """
        t = self._build_taxonomy()
        # Reparent Child under Sibling — sibling is not a descendant of child
        res = api_client.reparent_category(
            t["child"]["id"],
            {"parent_category_id": t["sibling"]["id"]},
            make_risk_manager_headers(USER_RISK_MANAGER),
        )
        updated = validate_success(res, 200)
        assert updated["parent_category_id"] == t["sibling"]["id"]
        # Verify via the subcategories view
        subs = validate_success(
            api_client.list_subcategories(
                t["sibling"]["id"],
                make_risk_manager_headers(USER_RISK_MANAGER),
            ), 200,
        )
        assert any(c["id"] == t["child"]["id"] for c in subs)
