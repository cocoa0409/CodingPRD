"""Mold inventory, the swab-and-release changeover protocol, segregation of
duties, and optimistic concurrency on the line version."""
from test_helpers import (
    OPERATOR,
    PLANNER,
    ApiErrorId,
    create_changeover_payload,
    create_line,
    create_mold,
    get_changeover,
    get_line,
    make_quality_manager_headers,
    make_sanitation_lead_headers,
    open_changeover,
    run_changeover_cycle,
    swab_changeover,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestChangeoverLifecycle:
    def test_shape_only_then_allergen_wash(self, api):
        """PRD §3.3: "if a `to_mold_id` was named, the mold previously referenced
        by the line's `current_mold_id` — if any — returns to `AVAILABLE`, the new
        mold becomes `INSTALLED`, each affected mold's `version` increments, and
        the line's `current_mold_id` points at the new mold."
        PRD §3.3: "an `ALLERGEN_WASH` release sets the line's `cleared_allergens`
        to exactly the changeover's `target_allergens`, while a `SHAPE_ONLY` or
        `FULL` release resets `cleared_allergens` to empty."

        Design: Corner/state_machines/changeover_lifecycle_installs_mold_and_clearance
        """
        mold = create_mold(shape_code="STAR")
        line = create_line()

        ch_1 = run_changeover_cycle(line["id"], "SHAPE_ONLY",
                                    to_mold_id=mold["id"])
        assert ch_1["status"] == "RELEASED"

        line = get_line(line["id"])
        assert line["status"] == "AVAILABLE"
        assert line["current_mold_id"] == mold["id"]
        assert line["cleared_allergens"] == [], "a mold swap strips clearance"

        molds, _ = validate_paginated(
            api.list_molds(PLANNER, params={"shape_code": "STAR"}))
        assert molds[0]["status"] == "INSTALLED"

        ch_2 = run_changeover_cycle(line["id"], "ALLERGEN_WASH",
                                    target_allergens=["MILK"])
        assert ch_2["status"] == "RELEASED"
        line = get_line(line["id"])
        assert line["status"] == "AVAILABLE"
        assert sorted(line["cleared_allergens"]) == ["MILK"]
        assert line["current_mold_id"] == mold["id"], (
            "a wash without a mold swap leaves the installed mold in place")


class TestSwabGate:
    def test_failed_swab_rejected_and_changeover_stays_pending(self, api):
        """PRD §3.3: "A failed swab — `swab_passed` recorded as false — is
        rejected with `ERR_SWAB_FAILED` and the changeover remains `PENDING_SWAB`,
        awaiting re-wash and a new swab."

        Design: Corner/validations/changeover_swab_failed_rejected
        """
        line = create_line()
        changeover = open_changeover(line["id"], "SHAPE_ONLY")

        resp = api.record_swab(changeover["id"], {"swab_passed": False},
                               make_sanitation_lead_headers("san-1"))
        validate_error(resp, ApiErrorId.ERR_SWAB_FAILED)

        changeover = get_changeover(changeover["id"])
        assert changeover["status"] == "PENDING_SWAB"
        assert get_line(line["id"])["status"] == "CHANGEOVER", (
            "the line stays in changeover until a release")


class TestSegregationOfDuties:
    def test_release_by_swab_recorder_rejected(self, api):
        """PRD §3.3: "Segregation of duties is enforced here: the releasing
        operator's `X-User-ID` must differ from the recorded `swab_recorded_by`,
        or the release is rejected with `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/validations/changeover_release_same_user_rejected
        """
        line = create_line()
        changeover = open_changeover(line["id"], "ALLERGEN_WASH",
                                     target_allergens=["MILK"])
        swab_changeover(changeover["id"], user_id="sam-7")

        # The swab recorder may not release, even with the QualityManager role.
        resp = api.release_changeover(changeover["id"],
                                      make_quality_manager_headers("sam-7"))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        assert get_changeover(changeover["id"])["status"] == "PENDING_QA"

        released = validate_success(api.release_changeover(
            changeover["id"], make_quality_manager_headers("qm-1")))
        assert released["status"] == "RELEASED"
        assert released["qa_released_by"] == "qm-1"
        line = get_line(line["id"])
        assert line["status"] == "AVAILABLE"
        assert line["cleared_allergens"] == ["MILK"]


class TestMoldExclusivity:
    def test_changeover_to_installed_mold_rejected(self, api):
        """PRD §3.3: "a named mold must be `AVAILABLE` in inventory, and naming
        one that is already installed elsewhere is rejected with
        `ERR_MOLD_NOT_AVAILABLE`."

        Design: Corner/errors/changeover_to_installed_mold_rejected
        """
        mold = create_mold(shape_code="STAR")
        line_2 = create_line("LINE-2")
        run_changeover_cycle(line_2["id"], "SHAPE_ONLY", to_mold_id=mold["id"])
        line_1 = create_line("LINE-1")

        payload = create_changeover_payload(
            "SHAPE_ONLY", get_line(line_1["id"])["version"],
            to_mold_id=mold["id"])
        resp = api.create_changeover(line_1["id"], payload, OPERATOR)
        validate_error(resp, ApiErrorId.ERR_MOLD_NOT_AVAILABLE)

        molds, _ = validate_paginated(
            api.list_molds(PLANNER, params={"shape_code": "STAR"}))
        assert molds[0]["status"] == "INSTALLED"
        assert get_line(line_1["id"])["status"] == "AVAILABLE", (
            "no changeover is opened by the rejected request")


class TestLineOptimisticConcurrency:
    def test_changeover_create_with_stale_line_version_rejected(self, api):
        """PRD §2.8: "Opening a changeover on a line requires the non-optional
        field `expected_line_version`, carrying the `version` of the production
        line as the client last observed it. A mismatch with the line's current
        `version` is rejected with `ERR_STALE_VERSION` (HTTP 412), because a
        changeover supersedes the line's mold and clearance state and must not be
        built on an unobserved revision."

        Design: Corner/complexity_layers/changeover_create_stale_line_version_rejected
        """
        mold = create_mold(shape_code="STAR")
        line = create_line()
        stale_version = line["version"]

        # A full changeover cycle advances the line's version past the observed one.
        run_changeover_cycle(line["id"], "SHAPE_ONLY", to_mold_id=mold["id"])
        assert get_line(line["id"])["version"] > stale_version

        payload = create_changeover_payload(
            "ALLERGEN_WASH", stale_version, target_allergens=["MILK"])
        resp = api.create_changeover(line["id"], payload, OPERATOR)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        assert get_line(line["id"])["status"] == "AVAILABLE", (
            "the stale changeover is not opened")
