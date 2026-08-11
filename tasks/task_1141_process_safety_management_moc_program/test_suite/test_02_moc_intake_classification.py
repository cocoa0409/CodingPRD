"""MOC intake: required fields, initial state, classification, screening risk."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    TEST_USERS,
    assert_moc,
    classify,
    classify_payload,
    create_moc_payload,
    get_moc,
    list_moc_reviews,
    make_requester_headers,
    new_draft_moc,
    new_personnel,
    new_study,
    new_unit,
    validate_error,
    validate_paginated,
    validate_success,
)

MANAGER = TEST_USERS["manager_headers"]


class TestMocIntake:
    def test_moc_create_missing_required_field_returns_invalid_request(self, api):
        """PRD §2.9: "any request that is malformed — a missing required field, a
        value of the wrong type, an unknown enum value, or an invalid date — is
        rejected with `ERR_INVALID_REQUEST`."
        PRD §3.2: a MOC is created "supplying a `title`, a `description`, and a
        `discipline` of `MECHANICAL`, `CHEMICAL`, `ELECTRICAL`, or `PROCESS`" —
        omitting `discipline` is a missing required field.

        Design: Corner/entities/moc_create_missing_required_field_returns_invalid_request
        """
        unit = new_unit(name="U", unit_code="U1", pha_cycle_months=12)
        req = new_personnel("Req", "E-REQ")
        resp = api.create_moc(unit["id"], {"title": "M", "description": "d"},
                              make_requester_headers(req["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)
        # No MocRequest row was created.
        _, meta = validate_paginated(api.list_unit_mocs(unit["id"], MANAGER))
        assert meta["total_count"] == 0

    def test_nested_child_create_requires_existing_parent(self, api):
        """PRD §2.8: "Requests that target nested resources are validated strictly
        left-to-right along the path: the unit is resolved before the MOC, the MOC
        before its child collection, and so on. The first identifier that does not
        correspond to an existing resource produces that resource type's not-found
        error — `ERR_UNIT_NOT_FOUND`" (the unit is the first path segment here).

        Design: Corner/entities/nested_child_create_requires_existing_parent
        """
        req = new_personnel("Req", "E-REQ")
        resp = api.create_moc(NON_EXISTENT_UUID, create_moc_payload(), make_requester_headers(req["id"]))
        validate_error(resp, ApiErrorId.ERR_UNIT_NOT_FOUND.value)

    def test_moc_create_computed_field_input_ignored(self, api):
        """PRD §3.2: "it starts in `DRAFT` status at `version` 1, with
        `change_class` still unset and `review_round` at zero" — the client cannot
        seed system-managed fields; the screening score only appears "On
        classification" (PRD §3.2), so a freshly created MOC carries none.

        Design: Corner/entities/moc_create_computed_field_input_ignored
        """
        unit = new_unit(name="U", unit_code="U1", pha_cycle_months=12)
        req = new_personnel("Req", "E-REQ")
        payload = create_moc_payload()
        payload["screening_risk_score"] = 99.99
        payload["status"] = "CLOSED"
        resp = api.create_moc(unit["id"], payload, make_requester_headers(req["id"]))
        moc = validate_success(resp, 201)
        assert_moc(moc)
        assert moc["status"] == "DRAFT", f"Client-supplied status must be ignored, got {moc['status']}"
        assert moc["screening_risk_score"] is None, (
            f"Client-supplied screening_risk_score must be ignored, got {moc['screening_risk_score']}"
        )

    def test_moc_initial_state_draft(self, api):
        """PRD §3.2: "The new MOC is stamped with the creating user as its
        `requester_id` and with the owning unit from the creation path as its
        `unit_id`; it starts in `DRAFT` status at `version` 1, with `change_class`
        still unset and `review_round` at zero."

        Design: Corner/state_machines/moc_initial_state_draft
        """
        unit = new_unit(name="U", unit_code="U1", pha_cycle_months=12)
        req = new_personnel("Req", "E-REQ")
        resp = api.create_moc(unit["id"], create_moc_payload(discipline="PROCESS"),
                              make_requester_headers(req["id"]))
        moc = validate_success(resp, 201)
        assert_moc(moc)
        assert moc["status"] == "DRAFT"
        assert moc["review_round"] == 0
        assert moc["version"] == 1
        assert moc["requester_id"] == req["id"]
        assert moc["unit_id"] == unit["id"]
        assert moc["change_class"] is None
        assert moc["screening_risk_score"] is None
        assert moc["requires_pssr"] is None

    def test_classify_twice_returns_invalid_state(self, api):
        """PRD §3.2: "Classification is a `PsmManager` act that turns a `DRAFT` MOC
        into a `CLASSIFIED` one (any other from-state yields
        `ERR_MOC_INVALID_STATE`)."

        Design: Corner/state_machines/classify_twice_returns_invalid_state
        """
        unit = new_unit(name="U", unit_code="U1", pha_cycle_months=12)
        req = new_personnel("Req", "E-REQ")
        moc = new_draft_moc(unit["id"], req["id"])
        classify(moc["id"], change_class="PERMANENT", severity=1, likelihood=1)

        resp = api.classify_moc(moc["id"], classify_payload(change_class="PERMANENT",
                                                            screening_severity=1, screening_likelihood=1),
                                MANAGER)
        validate_error(resp, ApiErrorId.ERR_MOC_INVALID_STATE.value)
        assert get_moc(moc["id"])["status"] == "CLASSIFIED"

    def test_rik_bypass_branch_skips_technical_review(self, api):
        """PRD §3.3: "A `REPLACEMENT_IN_KIND` change bypasses technical review
        entirely, moving `CLASSIFIED` → `APPROVAL_PENDING` in one step."
        PRD §3.2: "Classification also fixes the PSSR obligation: `requires_pssr`
        is set to false only when the class is `REPLACEMENT_IN_KIND` and
        `requires_pssr_override` is not true; in every other case it is true."
        PRD §3.2: screening uses "a change-class multiplier — 1.0 for
        `PERMANENT`, 1.2 for `TEMPORARY`, and 0.5 for `REPLACEMENT_IN_KIND`".

        Design: Corner/state_machines/rik_bypass_branch_skips_technical_review
        """
        unit = new_unit(name="U", unit_code="U1", pha_cycle_months=12)
        new_study(unit["id"], method="CHECKLIST", initial_validated_at="2026-04-01")
        req = new_personnel("Req", "E-REQ")
        moc = new_draft_moc(unit["id"], req["id"], discipline="MECHANICAL")
        classify(moc["id"], change_class="REPLACEMENT_IN_KIND", severity=2, likelihood=2)

        resp = api.submit_moc(moc["id"], make_requester_headers(req["id"]))
        submitted = validate_success(resp, 200)
        assert submitted["status"] == "APPROVAL_PENDING", (
            f"RIK must bypass review to APPROVAL_PENDING, got {submitted['status']}"
        )
        assert submitted["review_round"] == 0, "RIK bypass mints no review round"
        assert submitted["requires_pssr"] is False
        assert submitted["screening_risk_score"] == pytest.approx(2.00, abs=0.001)
        assert submitted["risk_rank"] == "LOW"
        reviews = list_moc_reviews(moc["id"])
        assert reviews == [], f"RIK bypass must create no TechnicalReview, got {reviews}"


class TestTempDurationBoundary:
    def test_temp_duration_max_inclusive_boundary_allows_max(self, api):
        """PRD §3.2: "a duration below 1 day or beyond the unit's
        `temp_moc_max_days` is rejected with `ERR_TEMP_DURATION_EXCEEDS_MAX`" —
        beyond means strictly greater, so a duration equal to the 180-day default
        maximum classifies successfully.
        PRD §3.2: "For a temporary MOC the system derives `temporary_end_date` as
        the start date plus the duration" — 2026-06-01 + 180 days = 2026-11-28.

        Design: Difficulty/boundary_precision_check/temp_duration_max_inclusive_boundary
        """
        unit = new_unit(name="U", unit_code="U1", pha_cycle_months=12)
        req = new_personnel("Req", "E-REQ")
        moc = new_draft_moc(unit["id"], req["id"])
        resp = api.classify_moc(
            moc["id"],
            classify_payload(change_class="TEMPORARY", screening_severity=1, screening_likelihood=1,
                             temporary_start_date="2026-06-01", temporary_duration_days=180),
            MANAGER,
        )
        classified = validate_success(resp, 200)
        assert classified["status"] == "CLASSIFIED"
        assert classified["temporary_end_date"] == "2026-11-28T00:00:00Z", (
            f"180-day duration from 2026-06-01 must end 2026-11-28, got {classified['temporary_end_date']}"
        )

    def test_temp_duration_max_inclusive_boundary_rejects_over_max(self, api):
        """PRD §3.2: "a duration below 1 day or beyond the unit's
        `temp_moc_max_days` is rejected with `ERR_TEMP_DURATION_EXCEEDS_MAX`" —
        181 days is beyond the 180-day default maximum, and the MOC stays DRAFT.

        Design: Difficulty/boundary_precision_check/temp_duration_max_inclusive_boundary
        """
        unit = new_unit(name="U", unit_code="U1", pha_cycle_months=12)
        req = new_personnel("Req", "E-REQ")
        moc = new_draft_moc(unit["id"], req["id"])
        resp = api.classify_moc(
            moc["id"],
            classify_payload(change_class="TEMPORARY", screening_severity=1, screening_likelihood=1,
                             temporary_start_date="2026-06-01", temporary_duration_days=181),
            MANAGER,
        )
        validate_error(resp, ApiErrorId.ERR_TEMP_DURATION_EXCEEDS_MAX.value)
        assert get_moc(moc["id"])["status"] == "DRAFT"


class TestScreeningVariant:
    def test_screening_variant_computed_at_classify(self, api):
        """PRD §3.2: "On classification the system stores those inputs and
        computes the provisional `screening_risk_score`: severity multiplied by
        likelihood multiplied by a change-class multiplier — 1.0 for `PERMANENT`,
        1.2 for `TEMPORARY`, and 0.5 for `REPLACEMENT_IN_KIND` — rounded half-up
        to two decimal places." — 3 × 3 × 1.2 = 10.80.
        PRD §3.2: "The `risk_rank` is mapped from that score: below 5 is `LOW`;
        at least 5 but below 12 is `MEDIUM`; at least 12 but below 20 is `HIGH`;
        and 20 or higher is `CRITICAL`." — 10.80 is MEDIUM.

        Design: Difficulty/dual_variant_calc/moc_screening_vs_definitive_risk_score
        """
        unit = new_unit(name="Alkylation", unit_code="ALK1", pha_cycle_months=12)
        req = new_personnel("Req One", "E-REQ")
        moc = new_draft_moc(unit["id"], req["id"], title="Swap exchanger",
                            description="Like-for-like-plus")
        classified = classify(moc["id"], change_class="TEMPORARY", severity=3, likelihood=3,
                              temporary_start_date="2026-06-01", temporary_duration_days=180)
        assert classified["screening_risk_score"] == pytest.approx(10.80, abs=0.001), (
            f"screening 3*3*1.2 must be 10.80, got {classified['screening_risk_score']}"
        )
        assert classified["risk_rank"] == "MEDIUM"
        assert classified["definitive_risk_score"] is None, (
            "The provisional variant carries no detection term; definitive is computed at review time"
        )
