"""Criteria library: sets, guideline versions, supersession, OCC (PRD §3.1, §2.6)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_criteria_set,
    basic_um_environment,
    create_criteria_set,
    create_criteria_set_payload,
    create_guideline_version,
    get_criteria_set,
    get_guideline_version,
    make_active_criteria_set,
    pended_request,
    publish_guideline_version,
    reviewer_decide,
    transition_criteria_set,
    validate_error,
    validate_success,
)

EDITOR = TEST_USERS["policy_editor_headers"]


def _environment_with_pinned_pending_request():
    """Active set + provider + one pended request pinned to the published
    guideline version. Returns (provider, criteria_set, guideline_version,
    request)."""
    provider, cs, gv = basic_um_environment()
    req = pended_request(provider["id"], cs["id"])
    assert req["guideline_version_id"] == gv["id"]
    return provider, cs, gv, req


class TestCriteriaSetLifecycle:
    def test_criteria_set_creation_ignores_client_system_fields(self, api):
        """PRD §3.1: "A new set starts in `DRAFT` status."
        PRD §2.4: "Every primary resource carries a server-minted `id` formatted as a bare UUID with no type prefix, plus a `created_at` timestamp in ISO 8601 UTC with three fractional digits. Most resources additionally carry `updated_at` (same format, refreshed on any mutation) and `version` (an integer starting at 1 that increments by one on every mutation)."

        Design: Corner/entities/criteria_set_creation_client_system_fields_input_ignored
        """
        payload = create_criteria_set_payload(
            name="Ignored Fields Set", line_of_business="MEDICAID",
            service_category="DME",
        )
        payload["id"] = "11111111-2222-3333-4444-555555555555"
        payload["status"] = "ACTIVE"
        payload["version"] = 99
        data = validate_success(
            api.create_criteria_set(payload, EDITOR), expected_status=201,
        )
        assert_criteria_set(data)
        assert data["id"] != "11111111-2222-3333-4444-555555555555", (
            "server must mint the id, ignoring the client-supplied value"
        )
        assert data["status"] == "DRAFT"
        assert data["version"] == 1

    def test_activation_without_published_version_rejected(self, api):
        """PRD §3.1: "The set itself activates from `DRAFT` to `ACTIVE` only when at least one of its guideline versions is `PUBLISHED`; activation with zero published versions is rejected with `ERR_NO_ACTIVE_GUIDELINE`, and activation from any state other than `DRAFT` is `ERR_INVALID_CRITERIA_SET_TRANSITION`."

        Design: Corner/state_machines/criteria_set_activation_without_published_rejected
        """
        cs = create_criteria_set(name="Empty Library Set",
                                 line_of_business="MEDICAID",
                                 service_category="DME")
        create_guideline_version(cs["id"], version_label="0.1")
        resp = api.transition_criteria_set(cs["id"], {"to_status": "ACTIVE"}, EDITOR)
        validate_error(resp, ApiErrorId.ERR_NO_ACTIVE_GUIDELINE)
        assert get_criteria_set(cs["id"])["status"] == "DRAFT"

    def test_retired_criteria_set_reactivation_rejected(self, api):
        """PRD §3.1: "`DRAFT → RETIRED` and any transition out of `RETIRED` are invalid."
        PRD §3.1: "activation from any state other than `DRAFT` is `ERR_INVALID_CRITERIA_SET_TRANSITION`."

        Design: Corner/validations/retired_criteria_set_reactivation_rejected
        """
        cs, _gv = make_active_criteria_set(name="Retire Set")
        retired = transition_criteria_set(cs["id"], "RETIRED")
        assert retired["status"] == "RETIRED"
        resp = api.transition_criteria_set(cs["id"], {"to_status": "ACTIVE"}, EDITOR)
        validate_error(resp, ApiErrorId.ERR_INVALID_CRITERIA_SET_TRANSITION)

    def test_guideline_retire_from_draft_succeeds(self, api):
        """PRD §3.1: "A `DRAFT` version retires freely (subject to the OCC guard)."

        Design: Corner/state_machines/guideline_retire_from_draft_succeeds
        """
        cs = create_criteria_set(name="Draft Retire Set",
                                 line_of_business="MEDICARE",
                                 service_category="DME")
        gv = create_guideline_version(cs["id"], version_label="0.1")
        retired = validate_success(
            api.transition_guideline_version(
                gv["id"],
                {"to_status": "RETIRED",
                 "expected_criteria_set_version": cs["version"]},
                EDITOR,
            )
        )
        assert retired["status"] == "RETIRED"

    def test_republish_published_guideline_rejected(self, api):
        """PRD §3.1: "The owning criteria set must be in `DRAFT` or `ACTIVE` — publishing under a `RETIRED` set is rejected with `ERR_INVALID_GUIDELINE_TRANSITION`, as is any publish attempted on a version not currently `DRAFT`."

        Design: Corner/validations/republish_published_guideline_rejected
        """
        cs = create_criteria_set(name="Republish Set")
        gv = create_guideline_version(cs["id"])
        publish_guideline_version(gv["id"], cs["version"])
        fresh_version = get_criteria_set(cs["id"])["version"]
        resp = api.transition_guideline_version(
            gv["id"],
            {"to_status": "PUBLISHED",
             "expected_criteria_set_version": fresh_version},
            EDITOR,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_GUIDELINE_TRANSITION)

    def test_occ_stale_criteria_set_version_rejected(self, api):
        """PRD §2.6: "A request to publish or retire a guideline version must carry `expected_criteria_set_version`, a non-optional input holding the client's last observed `version` of the owning criteria set. If the value does not match the criteria set's current `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/validations/occ_stale_criteria_set_version_rejected
        """
        cs = create_criteria_set(name="OCC Set")
        gv1 = create_guideline_version(
            cs["id"], version_label="1.0",
            effective_until="2026-06-30T00:00:00Z",
        )
        # This publish bumps the set version, leaving cs["version"] stale.
        publish_guideline_version(gv1["id"], cs["version"])
        gv2 = create_guideline_version(
            cs["id"], version_label="2.0",
            effective_from="2026-07-01T00:00:00Z",
        )
        resp = api.transition_guideline_version(
            gv2["id"],
            {"to_status": "PUBLISHED",
             "expected_criteria_set_version": cs["version"]},
            EDITOR,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        assert get_guideline_version(gv2["id"])["status"] == "DRAFT", (
            "rejected transition leaves the version untouched"
        )


class TestGuidelineWindowConflicts:
    def _setup_set_with_published_v1(self):
        cs = create_criteria_set()
        gv1 = create_guideline_version(
            cs["id"], version_label="1.0",
            effective_until="2026-06-30T00:00:00Z",
        )
        publish_guideline_version(gv1["id"], cs["version"])
        return cs, gv1

    def test_touching_closed_windows_rejected(self, api):
        """PRD §3.1: "The new version's closed effective window — from `effective_from` through `effective_until`, with a null `effective_until` extending indefinitely — must not intersect the closed window of any other `PUBLISHED` version in the same set; the version being superseded is excluded from this overlap check. An intersecting publish is rejected with `ERR_GUIDELINE_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/guideline_closed_window_adjacency_rejected
        """
        cs, _gv1 = self._setup_set_with_published_v1()
        gv2 = create_guideline_version(
            cs["id"], version_label="2.0",
            effective_from="2026-06-30T00:00:00Z",
        )
        set_version = get_criteria_set(cs["id"])["version"]
        resp = api.transition_guideline_version(
            gv2["id"],
            {"to_status": "PUBLISHED",
             "expected_criteria_set_version": set_version},
            EDITOR,
        )
        validate_error(resp, ApiErrorId.ERR_GUIDELINE_WINDOW_OVERLAP)
        assert get_guideline_version(gv2["id"])["status"] == "DRAFT", (
            "closed intervals share the instant 2026-06-30T00:00:00Z, so the "
            "publish is rejected and the version is untouched"
        )

    def test_disjoint_window_publishes_after_rejected_overlap(self, api):
        """PRD §3.1: "The new version's closed effective window — from `effective_from` through `effective_until`, with a null `effective_until` extending indefinitely — must not intersect the closed window of any other `PUBLISHED` version in the same set; the version being superseded is excluded from this overlap check. An intersecting publish is rejected with `ERR_GUIDELINE_WINDOW_OVERLAP`."
        PRD §2.4: "Every mutation of a resource — whether driven by a client call or by an internal cascade such as a guideline publish bumping its owning criteria set — refreshes `updated_at` and increments `version` on the mutated resource."

        Design: Difficulty/resource_temporal_overlap/guideline_closed_window_adjacency_rejected
        """
        cs, _gv1 = self._setup_set_with_published_v1()
        gv2 = create_guideline_version(
            cs["id"], version_label="2.0",
            effective_from="2026-06-30T00:00:00Z",
        )
        gv3 = create_guideline_version(
            cs["id"], version_label="3.0",
            effective_from="2026-07-01T00:00:00Z",
        )
        set_version = get_criteria_set(cs["id"])["version"]
        resp = api.transition_guideline_version(
            gv2["id"],
            {"to_status": "PUBLISHED",
             "expected_criteria_set_version": set_version},
            EDITOR,
        )
        validate_error(resp, ApiErrorId.ERR_GUIDELINE_WINDOW_OVERLAP)
        # The failed publish did not bump the set version: the same expected
        # version authorizes the disjoint publish below.
        published = validate_success(
            api.transition_guideline_version(
                gv3["id"],
                {"to_status": "PUBLISHED",
                 "expected_criteria_set_version": set_version},
                EDITOR,
            )
        )
        assert published["status"] == "PUBLISHED", (
            "window [2026-07-01, open) is disjoint from [2026-01-01, 2026-06-30]"
        )


class TestPublishSupersedeInvariant:
    def _setup(self):
        cs = create_criteria_set()
        gv1 = create_guideline_version(cs["id"], version_label="1.0")
        publish_guideline_version(gv1["id"], cs["version"])
        return cs, gv1

    def _published_versions(self, api, criteria_set_id):
        return validate_success(
            api.list_guideline_versions(
                EDITOR,
                params={"criteria_set_id": criteria_set_id, "status": "PUBLISHED"},
            )
        )

    def test_publish_supersede_keeps_single_published_version(self, api):
        """PRD §3.1: "On a successful publish the version becomes `PUBLISHED`; if it named a superseded version, that version moves to `SUPERSEDED` and its `effective_until` is clamped to one second before the new version's `effective_from`; and the owning criteria set's `version` increments by one. The `PUBLISHED → SUPERSEDED` move happens only as this side effect — never via a direct transition call."

        Design: Difficulty/compensating_invariant/publish_supersede_published_count_invariant
        """
        cs, gv1 = self._setup()
        before = self._published_versions(api, cs["id"])
        assert [v["id"] for v in before] == [gv1["id"]]
        gv2 = create_guideline_version(
            cs["id"], version_label="2.0", auto_approve_eligible=True,
            effective_from="2026-09-01T00:00:00Z",
            supersedes_version_id=gv1["id"],
        )
        set_version = get_criteria_set(cs["id"])["version"]
        published = publish_guideline_version(gv2["id"], set_version)
        assert published["status"] == "PUBLISHED"
        after = self._published_versions(api, cs["id"])
        assert [v["id"] for v in after] == [gv2["id"]], (
            "exactly one PUBLISHED version per set before and after supersession"
        )
        assert get_guideline_version(gv1["id"])["status"] == "SUPERSEDED"

    def test_superseded_version_window_clamped(self, api):
        """PRD §3.1: "if it named a superseded version, that version moves to `SUPERSEDED` and its `effective_until` is clamped to one second before the new version's `effective_from`"

        Design: Difficulty/compensating_invariant/publish_supersede_published_count_invariant
        """
        cs, gv1 = self._setup()
        gv2 = create_guideline_version(
            cs["id"], version_label="2.0", auto_approve_eligible=True,
            effective_from="2026-09-01T00:00:00Z",
            supersedes_version_id=gv1["id"],
        )
        set_version = get_criteria_set(cs["id"])["version"]
        publish_guideline_version(gv2["id"], set_version)
        superseded = get_guideline_version(gv1["id"])
        assert superseded["status"] == "SUPERSEDED"
        assert superseded["effective_until"] == "2026-08-31T23:59:59.000Z", (
            "clamped to v2.effective_from minus one second"
        )


class TestCrossSetSupersedesPriority:
    def _setup_two_sets(self):
        csa = create_criteria_set(name="Set A")
        gva = create_guideline_version(csa["id"], version_label="1.0",
                                       content="A criteria")
        publish_guideline_version(gva["id"], csa["version"])
        csb = create_criteria_set(name="Set B", line_of_business="MEDICARE",
                                  service_category="DME")
        gvb = create_guideline_version(csb["id"], version_label="1.0",
                                       content="B criteria")
        publish_guideline_version(gvb["id"], csb["version"])
        return csa, gva, csb, gvb

    def test_cross_set_supersedes_rejected_before_window_check(self, api):
        """PRD §3.1: "If `supersedes_version_id` is present it must belong to the same criteria set (`ERR_SUPERSEDES_CROSS_SET`, HTTP 422) and must currently be `PUBLISHED` (`ERR_INVALID_GUIDELINE_TRANSITION` otherwise)."
        PRD §2.7: "Eighth, cross-reference consistency rules. Ninth, the guideline-retire in-flight guard. Tenth, temporal interval conflicts."
        PRD §2.7: "A request that fails an earlier category never surfaces a later category's error."

        Design: Difficulty/priority_pair_validation_conflict/guideline_supersedes_referential_beats_window_temporal
        """
        csa, _gva, _csb, gvb = self._setup_two_sets()
        # Draft in set A whose window [2026-06-01, open) also overlaps set A's
        # published [2026-01-01, open): both the referential and the temporal
        # rule are violated; the referential error surfaces first.
        gvd = create_guideline_version(
            csa["id"], version_label="9.9", content="cross-set draft",
            effective_from="2026-06-01T00:00:00Z",
            supersedes_version_id=gvb["id"],
        )
        set_version = get_criteria_set(csa["id"])["version"]
        resp = api.transition_guideline_version(
            gvd["id"],
            {"to_status": "PUBLISHED",
             "expected_criteria_set_version": set_version},
            EDITOR,
        )
        validate_error(resp, ApiErrorId.ERR_SUPERSEDES_CROSS_SET)

    def test_rejected_publish_leaves_version_and_set_untouched(self, api):
        """PRD §2.7: "A request that fails an earlier category never surfaces a later category's error."
        PRD §2.4: "Every mutation of a resource — whether driven by a client call or by an internal cascade such as a guideline publish bumping its owning criteria set — refreshes `updated_at` and increments `version` on the mutated resource."

        Design: Difficulty/priority_pair_validation_conflict/guideline_supersedes_referential_beats_window_temporal
        """
        csa, _gva, _csb, gvb = self._setup_two_sets()
        gvd = create_guideline_version(
            csa["id"], version_label="9.9", content="cross-set draft",
            effective_from="2026-06-01T00:00:00Z",
            supersedes_version_id=gvb["id"],
        )
        set_version = get_criteria_set(csa["id"])["version"]
        resp = api.transition_guideline_version(
            gvd["id"],
            {"to_status": "PUBLISHED",
             "expected_criteria_set_version": set_version},
            EDITOR,
        )
        validate_error(resp, ApiErrorId.ERR_SUPERSEDES_CROSS_SET)
        assert get_guideline_version(gvd["id"])["status"] == "DRAFT", (
            "publish rejected atomically"
        )
        assert get_criteria_set(csa["id"])["version"] == set_version, (
            "no mutation, so no version increment on the owning set"
        )


class TestGuidelineRetireInFlightGuard:
    def test_retire_blocked_while_request_pending(self, api):
        """PRD §3.1: "A `PUBLISHED` version retires only when no request pinned to it sits in `PENDED_REVIEW` or `ESCALATED_MD`; otherwise the retire is rejected with `ERR_GUIDELINE_HAS_INFLIGHT_REQUESTS`."

        Design: Difficulty/cross_entity_state_dependency/guideline_retire_blocked_by_inflight_request
        """
        _provider, cs, gv, req = _environment_with_pinned_pending_request()
        assert req["status"] == "PENDED_REVIEW"
        set_version = get_criteria_set(cs["id"])["version"]
        resp = api.transition_guideline_version(
            gv["id"],
            {"to_status": "RETIRED",
             "expected_criteria_set_version": set_version},
            EDITOR,
        )
        validate_error(resp, ApiErrorId.ERR_GUIDELINE_HAS_INFLIGHT_REQUESTS)

    def test_retire_succeeds_once_request_determined(self, api):
        """PRD §3.1: "A `PUBLISHED` version retires only when no request pinned to it sits in `PENDED_REVIEW` or `ESCALATED_MD`; otherwise the retire is rejected with `ERR_GUIDELINE_HAS_INFLIGHT_REQUESTS`."
        PRD §2.4: "Every mutation of a resource — whether driven by a client call or by an internal cascade such as a guideline publish bumping its owning criteria set — refreshes `updated_at` and increments `version` on the mutated resource."

        Design: Difficulty/cross_entity_state_dependency/guideline_retire_blocked_by_inflight_request
        """
        _provider, cs, gv, req = _environment_with_pinned_pending_request()
        set_version = get_criteria_set(cs["id"])["version"]
        resp = api.transition_guideline_version(
            gv["id"],
            {"to_status": "RETIRED",
             "expected_criteria_set_version": set_version},
            EDITOR,
        )
        validate_error(resp, ApiErrorId.ERR_GUIDELINE_HAS_INFLIGHT_REQUESTS)
        reviewer_decide(req["id"], "APPROVE", reason_code="MEDICAL_NECESSITY_MET")
        # The failed retire mutated nothing, so the same expected version
        # authorizes the second attempt once the in-flight set is empty.
        retired = validate_success(
            api.transition_guideline_version(
                gv["id"],
                {"to_status": "RETIRED",
                 "expected_criteria_set_version": set_version},
                EDITOR,
            )
        )
        assert retired["status"] == "RETIRED"
