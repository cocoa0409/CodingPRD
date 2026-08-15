"""No-contact directives: windows, supersession, exposure scoring, OCC."""
from test_helpers import (
    ApiErrorId,
    assert_instant_equals,
    case_version,
    create_case,
    create_directive,
    create_measure,
    get_case,
    make_cast,
    make_coordinator_headers,
    no_contact_directive_payload,
    report_violation,
    set_clock,
    substantiate_violation,
    terminate_measure,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import api_client


def _case_with_assault_directive(cast):
    """Case [SEXUAL_ASSAULT] with one ACTIVE open-ended MUTUAL directive."""
    case = create_case(cast, categories=["SEXUAL_ASSAULT"], received_via="EMAIL")
    directive = create_directive(
        case["id"], cast["coord"]["id"],
        party_side="MUTUAL", restrictions=["IN_PERSON"],
        effective_from="2026-08-01T00:00:00Z",
    )
    return case, directive


class TestDirectiveLiftTerminal:
    def test_directive_lift_then_relift_rejected(self, api):
        """PRD 3.2: "Lifting an `ACTIVE` directive moves it to `LIFTED`,
        recomputes the exposure score with the active-directive points removed,
        appends `DIRECTIVE_LIFTED`, and increments `version`."
        PRD 2.11: "**State** — the target entity must be in a from-state from which
        the requested transition exists in its machine, with terminal states
        rejecting all further transitions (`ERR_INVALID_STATE_TRANSITION`, 409)".

        Design: Corner/state_machines/directive_lift_then_relift_rejected
        """
        cast = make_cast("comp", "resp", "coord")
        coord_h = make_coordinator_headers(cast["coord"]["id"])
        case, directive = _case_with_assault_directive(cast)

        # Exposure: 40 base + 10 active-directive.
        assert get_case(case["id"], cast["coord"]["id"])["exposure_score"] == 50

        lifted = validate_success(api.lift_no_contact_directive(directive["id"], coord_h))
        assert lifted["status"] == "LIFTED"
        assert get_case(case["id"], cast["coord"]["id"])["exposure_score"] == 40

        resp = api.lift_no_contact_directive(directive["id"], coord_h)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
        # No double subtraction of the active-directive points.
        assert get_case(case["id"], cast["coord"]["id"])["exposure_score"] == 40


class TestExposureScoring:
    def test_violation_substantiation_score_arithmetic(self, api):
        """PRD 2.7: "A case becomes **interim-suspension eligible** when its score
        reaches the threshold of 70, and that boundary is inclusive: a score of
        exactly 70 confers eligibility, 69 does not."
        PRD 3.2: "Substantiating moves the report `PENDING → SUBSTANTIATED`,
        stamps `substantiated_at` from the logical clock (this timestamp drives
        the rolling 365-day window of §2.7), raises the directive's
        `substantiated_violation_count` by one, recomputes the case exposure
        score — flipping `interim_suspension_eligible` to true if the score
        crosses to at least 70 — appends `VIOLATION_SUBSTANTIATED`, and
        increments the case `version`."

        Design: Difficulty/transitive_cascade/violation_substantiation_exposure_contagion_cascade
        """
        cast = make_cast("comp", "resp", "coord")
        case, directive = _case_with_assault_directive(cast)
        vio1 = report_violation(
            directive["id"], cast["comp"]["id"], "party",
            occurred_at="2026-08-03T15:00:00Z", description="Approached in library",
        )
        vio2 = report_violation(
            directive["id"], cast["comp"]["id"], "party",
            occurred_at="2026-08-05T15:00:00Z", description="Text message sent",
        )

        substantiate_violation(vio1["id"], cast["coord"]["id"])
        mid = get_case(case["id"], cast["coord"]["id"])
        # 40 base + 10 active-directive + 10 * 1 in-window violation.
        assert mid["exposure_score"] == 60
        assert mid["interim_suspension_eligible"] is False

        substantiate_violation(vio2["id"], cast["coord"]["id"])
        end = get_case(case["id"], cast["coord"]["id"])
        # 40 + 10 + 10 * 2 = 70: the inclusive threshold is crossed by the
        # cascade, not by a direct case write.
        assert end["exposure_score"] == 70
        assert end["interim_suspension_eligible"] is True

    def test_violation_substantiation_increments_directive_counter(self, api):
        """PRD 3.2: "Each directive also carries the computed
        `substantiated_violation_count`, the number of its violation rows in
        `SUBSTANTIATED` status."
        PRD 3.2: "Substantiating moves the report `PENDING → SUBSTANTIATED`,
        stamps `substantiated_at` from the logical clock (this timestamp drives
        the rolling 365-day window of §2.7), raises the directive's
        `substantiated_violation_count` by one, recomputes the case exposure
        score — flipping `interim_suspension_eligible` to true if the score
        crosses to at least 70 — appends `VIOLATION_SUBSTANTIATED`, and
        increments the case `version`."

        Design: Difficulty/transitive_cascade/violation_substantiation_exposure_contagion_cascade
        """
        cast = make_cast("comp", "resp", "coord")
        coord_h = make_coordinator_headers(cast["coord"]["id"])
        case, directive = _case_with_assault_directive(cast)
        vio1 = report_violation(
            directive["id"], cast["comp"]["id"], "party",
            occurred_at="2026-08-03T15:00:00Z", description="Approach",
        )
        vio2 = report_violation(
            directive["id"], cast["comp"]["id"], "party",
            occurred_at="2026-08-05T15:00:00Z", description="Text",
        )
        before = validate_success(api.get_no_contact_directive(directive["id"], coord_h))
        assert before["substantiated_violation_count"] == 0

        substantiate_violation(vio1["id"], cast["coord"]["id"])
        mid = validate_success(api.get_no_contact_directive(directive["id"], coord_h))
        assert mid["substantiated_violation_count"] == 1

        substantiate_violation(vio2["id"], cast["coord"]["id"])
        after = validate_success(api.get_no_contact_directive(directive["id"], coord_h))
        assert after["substantiated_violation_count"] == 2, (
            "the counter must increment once per substantiation"
        )

    def test_exposure_rolling_window_ages_out_old_violation(self, api):
        """PRD 2.7: "The third component is **violation history**: 10 points for
        each substantiated directive violation on the case's directives whose
        `substantiated_at` falls within the rolling window from 365 days before
        the evaluation instant through the evaluation instant itself — both
        window bounds are inclusive."
        PRD 3.2: "Each directive also carries the computed
        `substantiated_violation_count`, the number of its violation rows in
        `SUBSTANTIATED` status."

        Design: Corner/calculations/exposure_rolling_window_ages_out_old_violation
        """
        cast = make_cast("comp", "resp", "coord")
        coord_h = make_coordinator_headers(cast["coord"]["id"])
        case, directive = _case_with_assault_directive(cast)
        vio = report_violation(
            directive["id"], cast["comp"]["id"], "party",
            occurred_at="2026-08-01T08:00:00Z", description="Approach",
        )
        # Substantiated at the default clock instant 2026-08-01T00:00:00Z.
        substantiate_violation(vio["id"], cast["coord"]["id"])
        assert get_case(case["id"], cast["coord"]["id"])["exposure_score"] == 60

        # 2026-08-01 + 365 days == 2027-08-01; at 2027-08-02 the violation has
        # aged out of the inclusive rolling window.
        set_clock("2027-08-02T00:00:00Z")
        api.lift_no_contact_directive(directive["id"], coord_h)

        case_after = get_case(case["id"], cast["coord"]["id"])
        assert case_after["exposure_score"] == 40, (
            "aged-out violation contributes nothing; lifted directive contributes nothing"
        )
        assert case_after["interim_suspension_eligible"] is False

        # The all-time per-directive counter is unaffected by window aging.
        dir_after = validate_success(api.get_no_contact_directive(directive["id"], coord_h))
        assert dir_after["substantiated_violation_count"] == 1


class TestDirectiveWindows:
    def test_directive_window_overlap_then_adjacency(self, api):
        """PRD 2.8: "Two no-contact directives on the same case and a shared party
        scope — where a `MUTUAL` directive shares both party scopes — must not
        overlap as half-open intervals unless the new directive is created with
        supersession; adjacency is allowed, meaning a new directive whose
        `effective_from` equals an existing directive's `effective_to` (zero gap)
        does not overlap. An improper overlap is rejected with
        `ERR_DIRECTIVE_WINDOW_OVERLAP` (422)."

        Design: Difficulty/boundary_precision_check/directive_window_adjacency_half_open
        """
        cast = make_cast("comp", "resp", "coord")
        coord_h = make_coordinator_headers(cast["coord"]["id"])
        case = create_case(cast, categories=["STALKING"])
        d1 = create_directive(
            case["id"], cast["coord"]["id"],
            party_side="RESPONDENT", restrictions=["IN_PERSON"],
            effective_from="2026-08-01T00:00:00Z", effective_to="2026-08-10T00:00:00Z",
        )

        # One second inside D1's half-open window: overlap.
        overlap = api.create_no_contact_directive(
            case["id"],
            no_contact_directive_payload(
                case_version(case["id"], cast["coord"]["id"]),
                party_side="RESPONDENT", restrictions=["ELECTRONIC"],
                effective_from="2026-08-09T23:59:59Z", effective_to="2026-08-20T00:00:00Z",
            ),
            coord_h,
        )
        validate_error(overlap, ApiErrorId.ERR_DIRECTIVE_WINDOW_OVERLAP)

        # Exactly at D1.effective_to: zero gap, adjacency allowed.
        adjacent = api.create_no_contact_directive(
            case["id"],
            no_contact_directive_payload(
                case_version(case["id"], cast["coord"]["id"]),
                party_side="RESPONDENT", restrictions=["ELECTRONIC"],
                effective_from="2026-08-10T00:00:00Z", effective_to="2026-08-20T00:00:00Z",
            ),
            coord_h,
        )
        d2 = validate_success(adjacent, 201)
        assert d2["status"] == "ACTIVE"

    def test_directive_window_adjacency_leaves_incumbent_untouched(self, api):
        """PRD 2.8: "adjacency is allowed, meaning a new directive whose
        `effective_from` equals an existing directive's `effective_to` (zero gap)
        does not overlap."

        Design: Difficulty/boundary_precision_check/directive_window_adjacency_half_open
        """
        cast = make_cast("comp", "resp", "coord")
        coord_h = make_coordinator_headers(cast["coord"]["id"])
        case = create_case(cast, categories=["STALKING"])
        d1 = create_directive(
            case["id"], cast["coord"]["id"],
            party_side="RESPONDENT", restrictions=["IN_PERSON"],
            effective_from="2026-08-01T00:00:00Z", effective_to="2026-08-10T00:00:00Z",
        )
        d2 = validate_success(
            api.create_no_contact_directive(
                case["id"],
                no_contact_directive_payload(
                    case_version(case["id"], cast["coord"]["id"]),
                    party_side="RESPONDENT", restrictions=["ELECTRONIC"],
                    effective_from="2026-08-10T00:00:00Z", effective_to="2026-08-20T00:00:00Z",
                ),
                coord_h,
            ),
            201,
        )
        assert d2["status"] == "ACTIVE"
        # Pure adjacency triggers no supersession of the incumbent.
        d1_after = validate_success(api.get_no_contact_directive(d1["id"], coord_h))
        assert d1_after["status"] == "ACTIVE"
        assert d1_after.get("superseded_by_directive_id") is None
        assert_instant_equals(d1_after["effective_to"], "2026-08-10T00:00:00Z", "d1.effective_to")


class TestDirectiveSupersession:
    def test_directive_supersede_truncates_overlapping_window(self, api):
        """PRD 3.2: "unless the creation sets `supersede_existing` true, in which
        case each overlapping `ACTIVE` directive is superseded: its
        `effective_to` is truncated to the new directive's `effective_from`, its
        `superseded_by_directive_id` points at the new directive, it lands in
        `SUPERSEDED`, and `DIRECTIVE_SUPERSEDED` is appended."

        Design: Difficulty/resource_temporal_overlap/directive_supersede_truncates_overlapping_window
        """
        cast = make_cast("comp", "resp", "coord")
        coord_h = make_coordinator_headers(cast["coord"]["id"])
        case = create_case(cast, categories=["DATING_VIOLENCE"])
        d1 = create_directive(
            case["id"], cast["coord"]["id"],
            party_side="RESPONDENT", restrictions=["IN_PERSON"],
            effective_from="2026-08-01T00:00:00Z", effective_to="2026-08-10T00:00:00Z",
        )

        rejected = api.create_no_contact_directive(
            case["id"],
            no_contact_directive_payload(
                case_version(case["id"], cast["coord"]["id"]),
                party_side="RESPONDENT", restrictions=["ELECTRONIC"],
                effective_from="2026-08-05T00:00:00Z", effective_to="2026-08-20T00:00:00Z",
            ),
            coord_h,
        )
        validate_error(rejected, ApiErrorId.ERR_DIRECTIVE_WINDOW_OVERLAP)

        accepted = api.create_no_contact_directive(
            case["id"],
            no_contact_directive_payload(
                case_version(case["id"], cast["coord"]["id"]),
                party_side="RESPONDENT", restrictions=["ELECTRONIC"],
                effective_from="2026-08-05T00:00:00Z", effective_to="2026-08-20T00:00:00Z",
                supersede_existing=True,
            ),
            coord_h,
        )
        d2 = validate_success(accepted, 201)
        assert d2["status"] == "ACTIVE"

        d1_after = validate_success(api.get_no_contact_directive(d1["id"], coord_h))
        assert d1_after["status"] == "SUPERSEDED"
        assert_instant_equals(
            d1_after["effective_to"], "2026-08-05T00:00:00Z",
            "incumbent effective_to truncated to the newcomer's effective_from",
        )
        assert d1_after["superseded_by_directive_id"] == d2["id"]

    def test_directive_supersede_keeps_single_active_directive_points(self, api):
        """PRD 2.7: "The fourth component is a flat 10 points when any no-contact
        directive on the case currently has `ACTIVE` status, and zero otherwise."

        Design: Difficulty/resource_temporal_overlap/directive_supersede_truncates_overlapping_window
        """
        cast = make_cast("comp", "resp", "coord")
        coord_h = make_coordinator_headers(cast["coord"]["id"])
        case = create_case(cast, categories=["DATING_VIOLENCE"])
        d1 = create_directive(
            case["id"], cast["coord"]["id"],
            party_side="RESPONDENT", restrictions=["IN_PERSON"],
            effective_from="2026-08-01T00:00:00Z", effective_to="2026-08-10T00:00:00Z",
        )
        # DATING_VIOLENCE base 35 + 10 while D1 is ACTIVE.
        assert get_case(case["id"], cast["coord"]["id"])["exposure_score"] == 45

        d2 = validate_success(
            api.create_no_contact_directive(
                case["id"],
                no_contact_directive_payload(
                    case_version(case["id"], cast["coord"]["id"]),
                    party_side="RESPONDENT", restrictions=["ELECTRONIC"],
                    effective_from="2026-08-05T00:00:00Z", effective_to="2026-08-20T00:00:00Z",
                    supersede_existing=True,
                ),
                coord_h,
            ),
            201,
        )
        assert d2["status"] == "ACTIVE"
        # Supersession replaces, not stacks: exactly one ACTIVE directive, so
        # the flat 10-point component lands exactly once.
        assert get_case(case["id"], cast["coord"]["id"])["exposure_score"] == 45
        d1_after = validate_success(api.get_no_contact_directive(d1["id"], coord_h))
        assert d1_after["status"] == "SUPERSEDED"
        assert d1_after["superseded_by_directive_id"] == d2["id"]


class TestDirectiveCreateOcc:
    def test_occ_directive_create_stale_version_rejected(self, api):
        """PRD 2.10: "If that value does not equal the case's current `version` at
        write time — because another writer has advanced the case's version since
        the client last read it — the request is rejected with
        `ERR_STALE_CASE_VERSION` (HTTP 412), forcing the client to re-read the
        case before writing."

        Design: Corner/cross_cutting_complexity_layers/occ_directive_create_stale_version_rejected
        """
        cast = make_cast("comp", "resp", "coord")
        coord_h = make_coordinator_headers(cast["coord"]["id"])
        case = create_case(cast, categories=["STALKING"], received_via="EMAIL")
        measure = create_measure(
            case["id"], cast["coord"]["id"],
            measure_type="ESCORT", party_side="BOTH", description="Escort",
        )
        observed = case_version(case["id"], cast["coord"]["id"])
        # An intervening write advances the case version after the client's read.
        terminate_measure(measure["id"], cast["coord"]["id"])

        resp = api.create_no_contact_directive(
            case["id"],
            no_contact_directive_payload(
                observed,
                party_side="MUTUAL", restrictions=["IN_PERSON"],
                effective_from="2026-08-01T00:00:00Z",
            ),
            coord_h,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_CASE_VERSION)

        directives, _ = validate_paginated(api.list_case_directives(case["id"], coord_h))
        assert directives == [], "a stale create must not persist any directive row"
