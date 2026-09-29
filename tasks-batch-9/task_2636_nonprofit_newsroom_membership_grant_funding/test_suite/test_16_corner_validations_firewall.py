"""Firewall paperwork: supersede targeting, voiding under a live award, the two
risk bases at the hard bar, institutional money, and rehabilitation.
"""

import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    attest_disclosure,
    close_proposal,
    file_disclosure,
    log_influence_contact,
    open_fiscal_period,
    read_coverage_area,
    read_funder,
    read_proposal,
    read_report,
    register_coverage_area,
    register_funder,
    rule_on_funder,
    setup_awarded_restricted_proposal,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import DO_HEADERS, ED_HEADERS
from test_helpers.test_users import USER_IDS

_CLIMATE_TEXT = (
    "Ironwood funds climate coverage; the climate desk retains editorial control."
)
_HOUSING_TEXT = (
    "Ironwood also funds housing coverage; the housing desk retains editorial "
    "control."
)
_REVISED_CLIMATE_TEXT = (
    "Revised climate firewall statement replacing the original disclosure."
)


def _create_disclosure(funder_id, coverage_area_id, expected_funder_version, **extra):
    """Raw filing so a bad supersede target can be inspected."""
    payload = {
        "funder_id": funder_id,
        "coverage_area_id": coverage_area_id,
        "disclosure_text": _CLIMATE_TEXT,
        "expected_funder_version": expected_funder_version,
    }
    payload.update(extra)
    return api_client.create_firewall_disclosure(payload, ED_HEADERS)


def _read_disclosure(disclosure_id):
    return validate_success(
        api_client.get_firewall_disclosure(disclosure_id, ED_HEADERS)
    )


def _setup_climate_disclosure_and_a_second_beat():
    """One CLEARED foundation holding an ACTIVE disclosure on CLIMATE, plus an
    untouched HOUSING beat to aim a mistargeted supersede at."""
    climate = register_coverage_area(area_code="CLIMATE", name="Climate")
    housing = register_coverage_area(area_code="HOUSING", name="Housing")
    funder = register_funder(legal_name="Ironwood Trust", funder_type="FOUNDATION")
    funder = rule_on_funder(funder["id"], "CLEAR", "SELF_ATTESTED")
    disclosure = file_disclosure(
        funder["id"],
        climate["id"],
        funder["version"],
        disclosure_text=_CLIMATE_TEXT,
    )
    return {
        "climate": climate,
        "housing": housing,
        "funder": read_funder(funder["id"]),
        "disclosure": disclosure,
    }


class TestSupersedeTargetMustShareTheFunderAndCoverageArea:
    """The target must match on both halves of the pair."""

    def test_a_target_covering_another_beat_of_the_same_funder_is_refused(self):
        """The funder matches and only the beat differs, and the filing is still
        refused with the earlier row left live.

        PRD: "When `supersedes_disclosure_id` is supplied, the target must be in
        status `ACTIVE` or `REATTESTATION_REQUIRED` and must carry the *same*
        `funder_id` and `coverage_area_id` as the new disclosure; a target that is
        already `SUPERSEDED` or `VOID`, or that covers a different pair, is
        `ERR_SUPERSEDE_TARGET_INVALID` (HTTP 409)."

        Design: Corner/Validations/val_supersede_target_must_share_the_funder_and_coverage_area
        """
        ctx = _setup_climate_disclosure_and_a_second_beat()

        validate_error(
            _create_disclosure(
                ctx["funder"]["id"],
                ctx["housing"]["id"],
                ctx["funder"]["version"],
                disclosure_text=_HOUSING_TEXT,
                supersedes_disclosure_id=ctx["disclosure"]["id"],
            ),
            ApiErrorId.ERR_SUPERSEDE_TARGET_INVALID,
        )

        assert _read_disclosure(ctx["disclosure"]["id"])["status"] == "ACTIVE"
        _, meta = validate_paginated(api_client.list_firewall_disclosures(ED_HEADERS))
        assert meta["total_count"] == 1

    def test_the_matching_pair_retires_the_earlier_row(self):
        """Only the beat in the request changes, and now the supersede lands and
        pushes the original into its terminal status.

        PRD: "Where the filing supersedes an earlier disclosure, that earlier row
        moves to the terminal status `SUPERSEDED`."

        Design: Corner/Validations/val_supersede_target_must_share_the_funder_and_coverage_area
        """
        ctx = _setup_climate_disclosure_and_a_second_beat()
        _create_disclosure(
            ctx["funder"]["id"],
            ctx["housing"]["id"],
            ctx["funder"]["version"],
            disclosure_text=_HOUSING_TEXT,
            supersedes_disclosure_id=ctx["disclosure"]["id"],
        )

        successor = validate_success(
            _create_disclosure(
                ctx["funder"]["id"],
                ctx["climate"]["id"],
                ctx["funder"]["version"],
                disclosure_text=_REVISED_CLIMATE_TEXT,
                supersedes_disclosure_id=ctx["disclosure"]["id"],
            ),
            expected_status=201,
        )
        assert successor["status"] == "ACTIVE"
        assert successor["supersedes_disclosure_id"] == ctx["disclosure"]["id"]
        assert _read_disclosure(ctx["disclosure"]["id"])["status"] == "SUPERSEDED"

    def test_superseding_does_not_double_count_the_funder_on_the_beat(self):
        """Two rows have covered CLIMATE and only one is live, so the beat still
        reports a single disclosed funder.

        PRD: "`disclosed_funder_count` counts the distinct funders that currently
        hold an `ACTIVE` firewall disclosure for this beat."

        Design: Corner/Validations/val_supersede_target_must_share_the_funder_and_coverage_area
        """
        ctx = _setup_climate_disclosure_and_a_second_beat()
        _create_disclosure(
            ctx["funder"]["id"],
            ctx["climate"]["id"],
            ctx["funder"]["version"],
            disclosure_text=_REVISED_CLIMATE_TEXT,
            supersedes_disclosure_id=ctx["disclosure"]["id"],
        )

        assert read_coverage_area(ctx["climate"]["id"])["disclosed_funder_count"] == 1
        assert read_coverage_area(ctx["housing"]["id"])["disclosed_funder_count"] == 0


def _void(disclosure_id):
    """Raw attestation with void true so the in-use refusal can be inspected."""
    return api_client.attest_firewall_disclosure(
        disclosure_id, {"void": True}, ED_HEADERS
    )


def _setup_awarded_project_grant_on_housing():
    """A PROJECT_RESTRICTED 350000-cent AWARDED grant backed by an ACTIVE
    disclosure on HOUSING, on annual reporting, with nothing released."""
    return setup_awarded_restricted_proposal(
        requested_amount_cents=350000,
        award_date="2026-08-01",
        reporting_cadence="ANNUAL",
        restriction_type="PROJECT_RESTRICTED",
        restriction_start_date="2026-09-01",
        restriction_end_date="2027-07-31",
        legal_name="Ironwood Trust",
        title="Housing accountability project",
    )


class TestVoidIsRefusedWhileAnAwardedGrantReliesOnTheDisclosure:
    """The guard looks for an `AWARDED` proposal on the exact pair."""

    def test_the_live_award_keeps_the_disclosure_on_the_record(self):
        """Nothing has been released, and the award alone is enough to freeze the
        paperwork in place.

        PRD: "Voiding has one precondition of its own: no grant proposal in status
        `AWARDED` may still reference that funder-and-beat pair, because retiring
        the disclosure under a live award would leave awarded money undisclosed.
        That refusal is `ERR_DISCLOSURE_IN_USE` (HTTP 409)."

        Design: Corner/Validations/val_void_is_refused_while_an_awarded_grant_relies_on_the_disclosure
        """
        ctx = _setup_awarded_project_grant_on_housing()

        validate_error(
            _void(ctx["disclosure"]["id"]), ApiErrorId.ERR_DISCLOSURE_IN_USE
        )

        unchanged = _read_disclosure(ctx["disclosure"]["id"])
        assert unchanged["status"] == "ACTIVE"
        assert unchanged["reattestation_reason"] is None

        area = read_coverage_area(ctx["area"]["id"])
        assert area["restricted_grant_count"] == 1
        assert area["disclosed_funder_count"] == 1

    def test_closing_the_grant_returns_the_principal_and_waives_the_report(self):
        """Closure is what releases the disclosure, and it also empties the
        unreleased bucket and retires the single annual obligation.

        PRD: "Closure waives every still-`SCHEDULED` report, adds any remaining
        `unreleased_cents` to `returned_cents` and zeroes it, recomputes the fiscal
        period's sustainability fields and the beat's `restricted_grant_count`, and
        leaves the proposal in the terminal status `CLOSED`."

        Design: Corner/Validations/val_void_is_refused_while_an_awarded_grant_relies_on_the_disclosure
        """
        ctx = _setup_awarded_project_grant_on_housing()
        assert len(ctx["reports"]) == 1

        closed = close_proposal(
            ctx["proposal"]["id"],
            closure_justification=(
                "Funder cancelled the project; the unreleased balance is returned."
            ),
        )
        assert closed["status"] == "CLOSED"
        assert closed["unreleased_cents"] == 0
        assert closed["returned_cents"] == 350000

        assert read_report(ctx["reports"][0]["id"])["status"] == "WAIVED"

    def test_the_identical_void_succeeds_once_no_award_relies_on_the_pair(self):
        """The same request retires the disclosure, and the beat is left with no
        disclosed funder and no restricted grant.

        PRD: "With `void` set to true the same operation retires the disclosure
        instead, moving it from `ACTIVE` or from `REATTESTATION_REQUIRED` to the
        terminal status `VOID`, and re-deriving the coverage area's
        `disclosed_funder_count`, `disclosure_status` and `publication_gate`."

        Design: Corner/Validations/val_void_is_refused_while_an_awarded_grant_relies_on_the_disclosure
        """
        ctx = _setup_awarded_project_grant_on_housing()
        _void(ctx["disclosure"]["id"])
        close_proposal(
            ctx["proposal"]["id"],
            closure_justification="Funder cancelled the project.",
        )

        voided = validate_success(_void(ctx["disclosure"]["id"]))
        assert voided["status"] == "VOID"

        area = read_coverage_area(ctx["area"]["id"])
        assert area["restricted_grant_count"] == 0
        assert area["disclosed_funder_count"] == 0
        assert read_proposal(ctx["proposal"]["id"])["status"] == "CLOSED"


def _clear_funder(funder_id, basis, **extra):
    """Raw clearance so a refusal at the hard bar can be inspected."""
    payload = {"decision": "CLEAR", "basis": basis}
    payload.update(extra)
    return api_client.funder_independence_clearance(funder_id, payload, ED_HEADERS)


def _setup_affiliated_corporate_funder():
    """One CORPORATE funder affiliated with CLIMATE that self-attests advocacy:
    25 for the type, 12 for an advocacy index of 3 and 10 for the affiliation."""
    area = register_coverage_area(area_code="CLIMATE", name="Climate")
    funder = register_funder(
        legal_name="Meridian Energy Corp",
        funder_type="CORPORATE",
        affiliated_coverage_area_id=area["id"],
        self_attested_advocacy=True,
    )
    return {"area": area, "funder": funder}


class TestAuditedAdvocacyIndexPushesTheRiskScorePastTheHardBar:
    """One funder, two bases, opposite sides of the hard bar."""

    def test_the_self_attested_registration_scores_forty_seven(self):
        """The stored advocacy index is the flat 3 the self-attested basis assigns,
        so the five terms sum to 47 and the funder is merely a prospect.

        PRD: "Under the `SELF_ATTESTED` basis - the default at registration, and
        the basis in force whenever a clearance is filed declaring it - the advocacy
        index is 3 when `self_attested_advocacy` is true and 0 when it is false, and
        `audited_advocacy_index` is ignored even if a value is stored."

        Design: Corner/Validations/val_audited_advocacy_index_pushes_the_risk_score_past_the_hard_bar
        """
        ctx = _setup_affiliated_corporate_funder()

        funder = ctx["funder"]
        assert funder["independence_risk_score"] == 47
        assert funder["risk_basis"] == "SELF_ATTESTED"
        assert funder["status"] == "PROSPECT"
        assert funder["audited_advocacy_index"] is None
        assert funder["self_attested_advocacy"] is True

    def test_an_audited_index_of_ten_is_refused_at_the_hard_bar(self):
        """Taking the audited 10 verbatim replaces 12 with 40 and lifts the same
        funder from 47 to 75, and no disclosure could rescue it.

        PRD: "The recomputed `independence_risk_score` must be strictly below the
        hard bar of 60; at 60 or above the clearance fails with
        `ERR_FUNDER_RISK_TOO_HIGH`, and no disclosure can rescue it."

        Design: Corner/Validations/val_audited_advocacy_index_pushes_the_risk_score_past_the_hard_bar
        """
        ctx = _setup_affiliated_corporate_funder()

        validate_error(
            _clear_funder(ctx["funder"]["id"], "AUDITED", audited_advocacy_index=10),
            ApiErrorId.ERR_FUNDER_RISK_TOO_HIGH,
        )

        unchanged = read_funder(ctx["funder"]["id"])
        assert unchanged["status"] == "PROSPECT"
        assert unchanged["risk_basis"] == "SELF_ATTESTED"
        assert unchanged["independence_risk_score"] == 47

    def test_the_self_attested_clearance_passes_once_the_beat_is_disclosed(self):
        """47 has crossed the disclosure floor, so the same funder needs its
        affiliated beat disclosed before the clearance the audited basis refused.

        PRD: "If the recomputed score has reached the disclosure floor of 40 or
        more, then `affiliated_coverage_area_id` must be non-null and an `ACTIVE`
        firewall disclosure must exist for that exact funder-and-beat pair; a
        missing one is `ERR_DISCLOSURE_REQUIRED`, and a disclosure for some *other*
        beat does not satisfy the requirement."

        Design: Corner/Validations/val_audited_advocacy_index_pushes_the_risk_score_past_the_hard_bar
        """
        ctx = _setup_affiliated_corporate_funder()
        _clear_funder(ctx["funder"]["id"], "AUDITED", audited_advocacy_index=10)

        disclosure = file_disclosure(
            ctx["funder"]["id"],
            ctx["area"]["id"],
            ctx["funder"]["version"],
            disclosure_text=(
                "Meridian funds climate coverage; assignment and editing stay with "
                "the climate desk."
            ),
        )
        assert disclosure["status"] == "ACTIVE"

        cleared = validate_success(
            _clear_funder(ctx["funder"]["id"], "SELF_ATTESTED")
        )
        assert cleared["status"] == "CLEARED"
        assert cleared["independence_risk_score"] == 47
        assert cleared["risk_basis"] == "SELF_ATTESTED"
        assert cleared["cleared_by_user_id"] == USER_IDS["editorial_director"]


def _create_proposal(funder_id, period_id):
    """Raw drafting so the non-institutional refusal can be inspected."""
    return api_client.create_grant_proposal(
        {
            "funder_id": funder_id,
            "fiscal_period_id": period_id,
            "title": "Newsroom capacity grant",
            "requested_amount_cents": 350000,
            "restriction_type": "UNRESTRICTED",
        },
        DO_HEADERS,
    )


def _setup_corporate_and_government_prospects():
    """One period and two PROSPECT funders differing only in `funder_type`."""
    period = open_fiscal_period()
    corporate = register_funder(
        legal_name="Meridian Energy Corp", funder_type="CORPORATE"
    )
    government = register_funder(
        legal_name="State Media Fund", funder_type="GOVERNMENT"
    )
    return {"period": period, "corporate": corporate, "government": government}


class TestCorporateFunderCannotSourceAGrantProposal:
    """The test is on `funder_type`, and the funder's status plays no part."""

    def test_a_corporate_donor_cannot_be_the_source_of_a_grant(self):
        """The payload is otherwise a perfectly ordinary unrestricted request, and
        nothing is written.

        PRD: "Only institutional money can be a grant: the named funder's
        `funder_type` must be `FOUNDATION` or `GOVERNMENT`, and an individual or
        corporate donor is refused with `ERR_FUNDER_NOT_INSTITUTIONAL` (HTTP 422)."

        Design: Corner/Validations/val_corporate_funder_cannot_source_a_grant_proposal
        """
        ctx = _setup_corporate_and_government_prospects()

        validate_error(
            _create_proposal(ctx["corporate"]["id"], ctx["period"]["id"]),
            ApiErrorId.ERR_FUNDER_NOT_INSTITUTIONAL,
        )

        _, meta = validate_paginated(api_client.list_grant_proposals(DO_HEADERS))
        assert meta["total_count"] == 0

    def test_the_identical_payload_from_a_government_funder_is_accepted(self):
        """The government funder is just as much a `PROSPECT`, which is what shows
        the refusal turned on the type alone.

        PRD: "Development's own probability estimate is `award_probability_bps`, an
        integer between 0 and 10000 that defaults to 5000 and is used by nothing
        except the pipeline revenue projection of §3.9."

        Design: Corner/Validations/val_corporate_funder_cannot_source_a_grant_proposal
        """
        ctx = _setup_corporate_and_government_prospects()
        _create_proposal(ctx["corporate"]["id"], ctx["period"]["id"])

        drafted = validate_success(
            _create_proposal(ctx["government"]["id"], ctx["period"]["id"]),
            expected_status=201,
        )
        assert drafted["status"] == "DRAFT"
        assert drafted["award_probability_bps"] == 5000
        assert drafted["revision_round_count"] == 0
        assert drafted["report_count"] == 0
        assert read_funder(ctx["government"]["id"])["status"] == "PROSPECT"


def _setup_restricted_funder_with_a_stale_disclosure():
    """Ironwood is CLEARED with an ACTIVE disclosure on CLIMATE; an
    editorial-direction contact then restricts it and stales the disclosure."""
    area = register_coverage_area(area_code="CLIMATE", name="Climate")
    funder = register_funder(legal_name="Ironwood Trust", funder_type="FOUNDATION")
    funder = rule_on_funder(funder["id"], "CLEAR", "SELF_ATTESTED")
    disclosure = file_disclosure(
        funder["id"],
        area["id"],
        funder["version"],
        disclosure_text=_CLIMATE_TEXT,
    )
    log_influence_contact(
        funder["id"],
        contact_type="EDITORIAL_DIRECTION_REQUEST",
        occurred_at="2026-08-01T00:00:00Z",
        summary="Funder asked us to drop a story about one of its grantees.",
        coverage_area_id=area["id"],
    )
    return {
        "area": area,
        "funder": read_funder(funder["id"]),
        "disclosure": _read_disclosure(disclosure["id"]),
    }


class TestStaleDisclosureBlocksRehabilitatingARestrictedFunder:
    """A score of 18 is far below both policy lines, and the paperwork still
    decides the request."""

    def test_the_logged_request_restricts_the_funder_and_stales_its_paperwork(self):
        """The contact drove the restriction, so the disclosure records
        `INFLUENCE_CONTACT` rather than a director's own filing.

        PRD: "Because the funder is restricted, every firewall disclosure of that
        funder currently in `ACTIVE` moves to `REATTESTATION_REQUIRED` and records
        why in `reattestation_reason` - `FUNDER_RESTRICTED` when an editorial
        director filed the restriction directly, `INFLUENCE_CONTACT` when a logged
        contact drove it."

        Design: Corner/Validations/val_stale_disclosure_blocks_rehabilitating_a_restricted_funder
        """
        ctx = _setup_restricted_funder_with_a_stale_disclosure()

        funder = ctx["funder"]
        assert funder["status"] == "RESTRICTED"
        assert funder["independence_risk_score"] == 18
        assert funder["prior_editorial_requests_count"] == 1
        assert funder["restricted_at"].startswith("2026-08-01T00:00:00")

        assert ctx["disclosure"]["status"] == "REATTESTATION_REQUIRED"
        assert ctx["disclosure"]["reattestation_reason"] == "INFLUENCE_CONTACT"

    def test_re_clearance_is_refused_while_the_disclosure_is_stale(self):
        """18 is under the disclosure floor of 40 entirely, so only the staleness
        rung can explain the refusal.

        PRD: "And when the funder is being rehabilitated out of `RESTRICTED`, none
        of its disclosures may still be sitting in `REATTESTATION_REQUIRED` - the
        firewall paperwork has to be current again first, and a stale one is
        `ERR_DISCLOSURE_STALE`."

        Design: Corner/Validations/val_stale_disclosure_blocks_rehabilitating_a_restricted_funder
        """
        ctx = _setup_restricted_funder_with_a_stale_disclosure()

        validate_error(
            _clear_funder(ctx["funder"]["id"], "SELF_ATTESTED"),
            ApiErrorId.ERR_DISCLOSURE_STALE,
        )

        unchanged = read_funder(ctx["funder"]["id"])
        assert unchanged["status"] == "RESTRICTED"
        assert unchanged["restricted_at"].startswith("2026-08-01T00:00:00")

    def test_re_attestation_admits_the_identical_clearance(self):
        """The clearance request is unchanged, and the rehabilitated funder keeps
        both the score the contact cost it and the instant it was restricted.

        PRD: "On success `cleared_by_user_id` is set to the acting `X-User-ID`, the
        funder's `version` increments by 1, and - this is deliberate and
        load-bearing - `restricted_at` is **left untouched**, so the cooling-off
        window of §3.7 keeps running against the instant of the original restriction
        even after rehabilitation."

        Design: Corner/Validations/val_stale_disclosure_blocks_rehabilitating_a_restricted_funder
        """
        ctx = _setup_restricted_funder_with_a_stale_disclosure()
        _clear_funder(ctx["funder"]["id"], "SELF_ATTESTED")

        reattested = attest_disclosure(ctx["disclosure"]["id"])
        assert reattested["status"] == "ACTIVE"
        assert reattested["reattestation_reason"] is None

        cleared = validate_success(_clear_funder(ctx["funder"]["id"], "SELF_ATTESTED"))
        assert cleared["status"] == "CLEARED"
        assert cleared["independence_risk_score"] == 18
        assert cleared["prior_editorial_requests_count"] == 1
        assert cleared["restricted_at"].startswith("2026-08-01T00:00:00")
        assert cleared["cleared_by_user_id"] == USER_IDS["editorial_director"]
