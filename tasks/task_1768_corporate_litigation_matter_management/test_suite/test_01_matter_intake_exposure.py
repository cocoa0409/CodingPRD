"""Matter intake, exposure triplet validation, and exposure tier classification."""
import re

from test_helpers import (
    NON_EXISTENT_UUID,
    VARIANT_EXPOSURE,
    create_matter,
    create_matter_payload,
    create_staff_user,
    make_counsel_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import ApiErrorId, MatterStatus, Posture


def _counsel():
    return create_staff_user("Casey Counsel", "casey@corp.example", "LEGAL")


class TestMatterCreationDefaults:
    def test_matter_creation_applies_defaults_and_system_fields(self, api):
        """PRD §3.1: "The new matter starts in `INTAKE` with `accrued_to_date_cents`
        initialized to zero and its posture computed fresh."
        PRD §3.1: "The server mints a `matter_number` for display: the literal prefix
        `MTR-`, the four-digit year, and a six-digit sequence assigned in creation order."
        PRD §3.9: "the request body must carry `close_checklist_ack` set to true — the
        flag defaults to false on the matter"
        PRD §2.9: "Otherwise, if the matter's `status` is `INTAKE`, `ASSESSMENT`, or
        `SETTLEMENT_PENDING`, the posture is `RESTRICTED`."

        Design: Corner/entities/matter_creation_applies_defaults_and_system_fields
        """
        counsel = _counsel()
        resp = api.create_matter(
            create_matter_payload(owning_counsel_id=counsel["id"], title="New matter"),
            make_counsel_headers(counsel["id"]))
        matter = validate_success(resp, 201)

        assert matter["status"] == MatterStatus.INTAKE.value
        assert matter["accrued_to_date_cents"] == 0
        assert matter["close_checklist_ack"] is False
        assert matter["posture"] == Posture.RESTRICTED.value, \
            "INTAKE maps to RESTRICTED on the posture ladder"
        assert re.fullmatch(r"MTR-\d{4}-\d{6}", matter["matter_number"]), \
            f"matter_number must be MTR-<year>-<6 digits>, got {matter['matter_number']}"
        assert matter["id"], "id must be populated"
        assert isinstance(matter["version"], int), "version must be an integer"
        assert matter.get("created_at"), "created_at must be populated"
        assert matter.get("updated_at"), "updated_at must be populated"

    def test_matter_get_not_found_returns_404(self, api):
        """PRD §2.10: "the first identifier in the path that does not correspond to an
        existing resource yields `ERR_NOT_FOUND` (HTTP 404)".

        Design: Corner/entities/matter_get_not_found_returns_404
        """
        counsel = _counsel()
        resp = api.get_matter(NON_EXISTENT_UUID, make_counsel_headers(counsel["id"]))
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_matter_list_pagination_envelope(self, api):
        """PRD §2.3: "The `limit` parameter caps the number of items returned: it
        defaults to 10, with a minimum of 1 and a maximum of 100."
        PRD §2.3: "Paginated list responses carry `limit`, `offset`, `total_count`,
        and `has_more` in the `meta` object of the envelope."

        Design: Corner/entities/matter_list_pagination_envelope
        """
        counsel = _counsel()
        headers = make_counsel_headers(counsel["id"])
        for i, mtype in enumerate(("COMMERCIAL", "EMPLOYMENT", "IP"), start=1):
            create_matter(counsel["id"], with_exposure=False,
                          title=f"M{i}", matter_type=mtype)
        resp = api.list_matters(headers, params={"limit": 2, "offset": 0})
        data, meta = validate_paginated(resp)

        assert len(data) == 2, f"limit=2 must return 2 rows, got {len(data)}"
        assert meta["total_count"] == 3
        assert meta["has_more"] is True
        assert meta["limit"] == 2
        assert meta["offset"] == 0


class TestExposureFieldConstraints:
    def test_exposure_high_below_low_rejected(self, api):
        """PRD §3.1: "The low end must be at least zero; the high end must be greater
        than or equal to the low end; the probability of loss is an integer percent
        between 0 and 100 inclusive. A value violating any of these shapes, or an enum
        outside its declared set, is rejected with `ERR_FIELD_CONSTRAINT`."

        Design: Corner/entities/exposure_high_below_low_rejected
        """
        counsel = _counsel()
        resp = api.create_matter(
            create_matter_payload(owning_counsel_id=counsel["id"], title="Bad range",
                                  exposure_low_cents=5_000_000,
                                  exposure_high_cents=1_000_000,
                                  probability_of_loss_pct=50),
            make_counsel_headers(counsel["id"]))
        validate_error(resp, ApiErrorId.ERR_FIELD_CONSTRAINT)

    def test_invalid_enum_matter_type_rejected(self, api):
        """PRD §3.1: "A value violating any of these shapes, or an enum outside its
        declared set, is rejected with `ERR_FIELD_CONSTRAINT`."

        Design: Corner/entities/invalid_enum_matter_type_rejected
        """
        counsel = _counsel()
        resp = api.create_matter(
            create_matter_payload(owning_counsel_id=counsel["id"], title="Bad enum",
                                  matter_type="ANTITRUST"),
            make_counsel_headers(counsel["id"]))
        validate_error(resp, ApiErrorId.ERR_FIELD_CONSTRAINT)

    def test_computed_fields_rejected_on_matter_create(self, api):
        """PRD §2.11: "a missing required field, an empty string where a non-empty
        value is required, a malformed scalar type, or any field not declared in the
        endpoint's input list — explicitly including computed or system-managed fields
        such as `posture`, `exposure_tier`, `accrued_to_date_cents`, `id`, or `version`
        sent by a client — is rejected with `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/entities/matter_create_with_computed_fields_returns_invalid_request
        """
        counsel = _counsel()
        payload = create_matter_payload(
            owning_counsel_id=counsel["id"],
            exposure_low_cents=1_000_000, exposure_high_cents=4_000_000,
            probability_of_loss_pct=60)
        payload["posture"] = "FROZEN"
        payload["accrued_to_date_cents"] = 999
        resp = api.create_matter(payload, make_counsel_headers(counsel["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_missing_required_field_returns_invalid_request(self, api):
        """PRD §2.11: "Request-shape checking at step 23 is strict: a missing required
        field, an empty string where a non-empty value is required, a malformed scalar
        type, or any field not declared in the endpoint's input list — explicitly
        including computed or system-managed fields such as `posture`, `exposure_tier`,
        `accrued_to_date_cents`, `id`, or `version` sent by a client — is rejected
        with `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/endpoints/missing_required_field_returns_invalid_request
        """
        counsel = _counsel()
        payload = create_matter_payload(owning_counsel_id=counsel["id"])
        del payload["matter_type"]
        resp = api.create_matter(payload, make_counsel_headers(counsel["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestExposureTierVariants:
    def test_base_variant_commercial_classifies_tier_2(self, api):
        """PRD §3.1: "For most matter types the expected loss in cents is the sum of
        `exposure_low_cents` and `exposure_high_cents`, multiplied by
        `probability_of_loss_pct`, divided by two hundred with floor division."
        PRD §3.1: "An expected loss strictly below 25,000,000 cents (two hundred fifty
        thousand dollars) lands in `TIER_1`; below 100,000,000 cents in `TIER_2`;
        below 500,000,000 cents in `TIER_3`; anything at or above that in `TIER_4`."

        Design: Difficulty/dual_variant_calc/exposure_tier_base_vs_conservative_classification
        """
        low, high, prob = VARIANT_EXPOSURE
        counsel = _counsel()
        matter = create_matter(counsel["id"], matter_type="COMMERCIAL",
                               exposure=(low, high, prob), title="Commercial dispute")
        # (1,000,000 + 101,000,000) * 100 // 200 = 51,000,000 -> TIER_2
        assert matter["exposure_tier"] == "TIER_2", (
            f"base midpoint variant must land 51,000,000 in TIER_2, "
            f"got {matter['exposure_tier']}")

    def test_conservative_variant_class_action_classifies_tier_3(self, api):
        """PRD §3.1: "Two matter types get a deliberately more conservative reading:
        for a `CLASS_ACTION` or `REGULATORY` matter the expected loss is computed from
        the high end of the range alone — `exposure_high_cents` multiplied by
        `probability_of_loss_pct`, divided by one hundred with floor division — so such
        a matter tiers strictly higher than a `COMMERCIAL` matter with identical numbers."

        Design: Difficulty/dual_variant_calc/exposure_tier_base_vs_conservative_classification
        """
        low, high, prob = VARIANT_EXPOSURE
        counsel = _counsel()
        commercial = create_matter(counsel["id"], matter_type="COMMERCIAL",
                                   exposure=(low, high, prob), title="Commercial dispute")
        class_action = create_matter(counsel["id"], matter_type="CLASS_ACTION",
                                     exposure=(low, high, prob), title="Class action")
        # Conservative: 101,000,000 * 100 // 100 = 101,000,000 -> TIER_3
        assert class_action["exposure_tier"] == "TIER_3", (
            f"conservative high-end variant must land 101,000,000 in TIER_3, "
            f"got {class_action['exposure_tier']}")
        assert commercial["exposure_tier"] == "TIER_2"
        assert class_action["exposure_tier"] != commercial["exposure_tier"], \
            "identical exposure numbers must tier differently across the two variants"


class TestExposureTierBoundaries:
    def test_expected_loss_exactly_at_tier1_max_lands_in_tier_2(self, api):
        """PRD §3.1: "Because the boundary test is a strict less-than, an expected loss
        of exactly 25,000,000 cents classifies as `TIER_2`, not `TIER_1`."

        Design: Corner/calculations/exposure_tier_boundary_exactly_at_tier1_max
        """
        counsel = _counsel()
        at_boundary = create_matter(counsel["id"], matter_type="COMMERCIAL",
                                    exposure=(25_000_000, 25_000_000, 100),
                                    title="Boundary")
        # (25,000,000 + 25,000,000) * 100 // 200 = 25,000,000 -> NOT < TIER1_MAX
        assert at_boundary["exposure_tier"] == "TIER_2"

    def test_expected_loss_one_cent_under_tier1_max_lands_in_tier_1(self, api):
        """PRD §3.1: "An expected loss strictly below 25,000,000 cents (two hundred
        fifty thousand dollars) lands in `TIER_1`; below 100,000,000 cents in `TIER_2`;
        below 500,000,000 cents in `TIER_3`; anything at or above that in `TIER_4`."

        Design: Corner/calculations/exposure_tier_boundary_exactly_at_tier1_max
        """
        counsel = _counsel()
        under = create_matter(counsel["id"], matter_type="COMMERCIAL",
                              exposure=(24_999_998, 25_000_000, 100),
                              title="Just under")
        # (49,999,998) * 100 // 200 = 24,999,999 < 25,000,000 -> TIER_1
        assert under["exposure_tier"] == "TIER_1"
