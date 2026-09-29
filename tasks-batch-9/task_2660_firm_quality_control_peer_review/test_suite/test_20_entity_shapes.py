"""Entity shape, default, identity and relationship rules of the PRD.

Every test starts from an empty database and builds its own state through the
endpoints the PRD declares, using the shared helpers in ``test_helpers``.
Headers for the five entity-backed roles are always built from the id of the
row backing the acting identity.
"""
from prd_bench_local_runner.testing import validate_error, validate_paginated

from test_helpers import assertions, factories, fixtures
from test_helpers.api_errors import (
    ERR_INVALID_ENUM_VALUE,
    ERR_PARTNER_FIRM_MISMATCH,
    ERR_PEER_REVIEW_NOT_FOUND,
    ERR_VALIDATION_FAILED,
)
from test_helpers.constants import DEFAULT_CLOCK
from test_helpers.test_users import make_qc_director_headers

# The firm under test throughout this module.
FIRM_UNDER_TEST = dict(
    legal_name="Harbor & Vance LLP",
    state_code="TX",
    aa_hours_last_year=9000,
    enrolled_program="AICPA_PRC",
    peer_review_year_end="2026-06-30",
)

UNKNOWN_ID = "00000000-0000-4000-8000-0000000000ff"


def _firm_context(api):
    """Pin the logical clock, then register the firm and its partner roster."""
    fixtures.set_clock(api, DEFAULT_CLOCK)
    return fixtures.firm_context(api, **FIRM_UNDER_TEST)


def _accept_engagement(api, ctx, partner=None, **overrides):
    """Accept a client engagement, driven by the firm's managing partner."""
    partner = partner or ctx["ep"]
    return assertions.created_entity(
        api.create_engagement(
            factories.engagement_payload(ctx["firm_id"], partner["id"], **overrides),
            headers=ctx["mp_headers"],
        )
    )


def test_firm_create_returns_declared_defaults_and_version_one(api, admin_headers):
    """Registering a firm starts every derived value at its floor with version 1.

    "Registration starts every derived value at its floor: `risk_posture` is
    `STABLE`, `open_deficiency_count`, `open_material_failure_count` and
    `critical_risk_count` are each 0, `last_peer_review_rating` is `NONE`,
    `prior_reviewer_ids` is an empty array and `unassigned_review_flag` is
    false."

    Design: Corner/entities/firm_create_returns_declared_defaults_and_version_one
    """
    fixtures.set_clock(api, DEFAULT_CLOCK)

    firm = assertions.created_entity(
        api.create_firm(factories.firm_payload(**FIRM_UNDER_TEST), headers=admin_headers)
    )

    assertions.assert_fields(
        firm,
        risk_posture="STABLE",
        open_deficiency_count=0,
        open_material_failure_count=0,
        critical_risk_count=0,
        last_peer_review_rating="NONE",
        prior_reviewer_ids=[],
        unassigned_review_flag=False,
    )
    assertions.assert_common_fields(firm, expected_version=1)
    assert isinstance(firm["id"], str) and firm["id"], "id must be a non-empty string"


def test_partner_get_round_trips_designations_and_computes_eqr_eligible(api):
    """A partner read returns the stored roster data plus the derived eqr_eligible.

    "`eqr_eligible` is recomputed on every partner write and is true only when
    all three of the following hold: the partner's `status` is `ACTIVE`, their
    `cpe_hours_last_3y` is at least 120, and their `designations` array contains
    `EQ_REVIEWER`."

    Design: Corner/entities/partner_get_round_trips_designations_and_computes_eqr_eligible
    """
    ctx = _firm_context(api)
    reviewer = fixtures.new_partner(
        api,
        ctx["firm_id"],
        full_name="Lena Ortiz",
        cpa_license_state="TX",
        designations=["EQ_REVIEWER"],
        cpe_hours_last_3y=150,
    )

    read = assertions.read_entity(
        api.get_partner(
            reviewer["id"], headers=make_qc_director_headers(ctx["qc"]["id"])
        )
    )

    assertions.assert_fields(
        read,
        full_name="Lena Ortiz",
        cpa_license_state="TX",
        designations=["EQ_REVIEWER"],
        cpe_hours_last_3y=150,
        eqr_eligible=True,
        status="ACTIVE",
        open_eqr_count=0,
        open_engagement_count=0,
        last_inspected_year=None,
    )


def test_engagements_list_filters_by_workflow_state_and_paginates(api):
    """A filtered engagement list counts the whole filtered set, not the page.

    "The `meta` object of a list response carries `limit`, `offset`,
    `total_count` (the number of rows matching the filters before pagination is
    applied) and `has_more` (true when rows remain beyond the current page)."

    Design: Corner/entities/engagements_list_filters_by_workflow_state_and_paginates
    """
    ctx = _firm_context(api)
    for client_name, engagement_type in (
        ("Aurora Metals Inc", "REVIEW"),
        ("Calder Foods LLC", "REVIEW"),
        ("Dunmore Paper Co", "ATTESTATION"),
    ):
        _accept_engagement(
            api,
            ctx,
            client_name=client_name,
            engagement_type=engagement_type,
            period_end="2026-03-31",
        )

    rows, meta = validate_paginated(
        api.list_engagements(
            headers=make_qc_director_headers(ctx["qc"]["id"]),
            params={
                "firm_id": ctx["firm_id"],
                "workflow_state": "PLANNING",
                "limit": 2,
                "offset": 0,
            },
        )
    )

    assert len(rows) == 2, f"expected one page of 2 rows, got {len(rows)}"
    assert meta["total_count"] == 3, f"expected total_count 3, got {meta['total_count']}"
    assert meta["has_more"] is True, "a third PLANNING row remains beyond the page"
    assert meta["limit"] == 2 and meta["offset"] == 0
    for row in rows:
        assertions.assert_fields(row, workflow_state="PLANNING", file_state="OPEN")


def test_peer_review_get_with_unknown_id_returns_not_found(api, committee_headers):
    """An unknown peer review id yields that entity's own 404 identifier.

    "`{peer_review_id}` gives `ERR_PEER_REVIEW_NOT_FOUND`" — all of these are
    HTTP 404.

    Design: Corner/entities/peer_review_get_with_unknown_id_returns_not_found
    """
    fixtures.set_clock(api, DEFAULT_CLOCK)

    response = api.get_peer_review(UNKNOWN_ID, headers=committee_headers)

    error = validate_error(response, ERR_PEER_REVIEW_NOT_FOUND, expected_status=404)
    assert error["error_id"] == ERR_PEER_REVIEW_NOT_FOUND
    assert isinstance(error["message"], str) and error["message"].strip()


def test_engagement_create_missing_period_end_is_rejected(api):
    """Accepting an engagement without period_end is a request-shape failure.

    "Every required input field must be present and correctly typed ...
    Violations give `ERR_VALIDATION_FAILED` (HTTP 422)."

    Design: Corner/entities/engagement_create_missing_period_end_is_rejected
    """
    ctx = _firm_context(api)

    response = api.create_engagement(
        {
            "firm_id": ctx["firm_id"],
            "client_name": "Aurora Metals Inc",
            "engagement_type": "REVIEW",
            "engagement_partner_id": ctx["ep"]["id"],
        },
        headers=ctx["mp_headers"],
    )

    validate_error(response, ERR_VALIDATION_FAILED, expected_status=422)
    _rows, meta = validate_paginated(
        api.list_engagements(
            headers=ctx["mp_headers"], params={"firm_id": ctx["firm_id"]}
        )
    )
    assert meta["total_count"] == 0, "no Engagement row may be created"


def test_partner_create_omitting_optional_input_applies_declared_defaults(
    api, admin_headers
):
    """Every optional partner input falls back to its declared empty or floor value.

    "Four further inputs are optional and each defaults to an empty collection
    or a floor value ... and `status` is either `ACTIVE` (the default) or
    `INACTIVE`."

    Design: Corner/entities/partner_create_omitting_optional_input_applies_declared_defaults
    """
    fixtures.set_clock(api, DEFAULT_CLOCK)
    firm = fixtures.new_firm(api, **FIRM_UNDER_TEST)

    partner = assertions.created_entity(
        api.create_partner(
            firm["id"],
            {"full_name": "Priya Raman", "cpa_license_state": "TX"},
            headers=admin_headers,
        )
    )

    assertions.assert_fields(
        partner,
        designations=[],
        industry_specializations=[],
        prior_engagement_team_clients=[],
        independence_conflict_client_names=[],
        cpe_hours_last_3y=0,
        status="ACTIVE",
        eqr_eligible=False,
        last_inspected_year=None,
    )
    assertions.assert_common_fields(partner, expected_version=1)


def test_engagement_create_computes_risk_score_and_eqr_required(api):
    """Acceptance computes the weighted risk score and the review requirement.

    "The final `risk_score` is the signed sum of base plus load penalty minus
    specialization credit ... Immediately after the score, the server decides
    `eqr_required` on the same engagement."

    Design: Corner/entities/engagement_create_computes_risk_score_and_eqr_required
    """
    ctx = _firm_context(api)
    ep_ebp = fixtures.new_partner(
        api,
        ctx["firm_id"],
        full_name="Tomas Iglesias",
        cpa_license_state="TX",
        designations=["ENGAGEMENT_PARTNER"],
        industry_specializations=["EBP"],
        cpe_hours_last_3y=60,
    )

    engagement = _accept_engagement(
        api,
        ctx,
        partner=ep_ebp,
        client_name="Sable Retirement Plan",
        engagement_type="ERISA_AUDIT",
        period_end="2026-04-30",
        is_first_year_client=True,
        prior_finding_count_3y=2,
    )

    # 30 (ERISA_AUDIT) + 15 (first year) + min(20, 4 * 2) = 53, no load penalty,
    # minus the 10-point EBP specialization credit.
    assertions.assert_fields(
        engagement,
        risk_score=43,
        eqr_required=True,
        workflow_state="PLANNING",
        file_state="OPEN",
    )
    partner = assertions.read_entity(
        api.get_partner(ep_ebp["id"], headers=ctx["qc_headers"])
    )
    assertions.assert_fields(partner, open_engagement_count=1)


def test_partner_patch_unknown_designation_returns_invalid_enum(api, admin_headers):
    """A designation outside the declared set is an enum violation, not a shape one.

    "Every enum-typed input ... must be a member of its declared set, otherwise
    `ERR_INVALID_ENUM_VALUE` (HTTP 422)."

    Design: Corner/entities/partner_patch_unknown_designation_returns_invalid_enum
    """
    fixtures.set_clock(api, DEFAULT_CLOCK)
    firm = fixtures.new_firm(api, **FIRM_UNDER_TEST)
    reviewer = fixtures.new_partner(
        api,
        firm["id"],
        full_name="Lena Ortiz",
        cpa_license_state="TX",
        designations=["EQ_REVIEWER"],
        cpe_hours_last_3y=150,
    )

    response = api.update_partner(
        reviewer["id"], {"designations": ["CHIEF_AUDITOR"]}, headers=admin_headers
    )

    validate_error(response, ERR_INVALID_ENUM_VALUE, expected_status=422)
    read = assertions.read_entity(
        api.get_partner(reviewer["id"], headers=admin_headers)
    )
    assertions.assert_fields(read, designations=["EQ_REVIEWER"], version=1)


def test_quality_risk_create_likelihood_above_range_is_rejected(api):
    """A likelihood outside 1 through 5 is refused before any score is computed.

    "numeric inputs must honour their declared ranges — `likelihood` from 1
    through 5, `impact` from 1 through 5 ... Violations give
    `ERR_VALIDATION_FAILED` (HTTP 422)."

    Design: Corner/entities/quality_risk_create_likelihood_above_range_is_rejected
    """
    ctx = _firm_context(api)

    response = api.create_quality_risk(
        ctx["firm_id"],
        factories.quality_risk_payload(
            component="ENGAGEMENT_PERFORMANCE",
            quality_objective_code="EP-01",
            risk_statement="Insufficient review of significant judgements.",
            likelihood=6,
            impact=4,
        ),
        headers=ctx["qc_headers"],
    )

    validate_error(response, ERR_VALIDATION_FAILED, expected_status=422)
    _rows, meta = validate_paginated(
        api.list_quality_risks(
            headers=ctx["qc_headers"], params={"firm_id": ctx["firm_id"]}
        )
    )
    assert meta["total_count"] == 0, "no QualityRisk row may be created"


def test_engagement_create_with_foreign_firm_partner_is_rejected(api):
    """The engagement partner named on acceptance must belong to the accepting firm.

    "The named engagement partner must belong to the accepting firm, otherwise
    `ERR_PARTNER_FIRM_MISMATCH`."

    Design: Corner/entities/engagement_create_with_foreign_firm_partner_is_rejected
    """
    ctx = _firm_context(api)
    other_firm = fixtures.new_firm(
        api,
        legal_name="Northgate Audit Group",
        state_code="NV",
        aa_hours_last_year=400,
        peer_review_year_end="2026-06-30",
    )
    foreign_partner = fixtures.new_partner(
        api,
        other_firm["id"],
        full_name="Owen Fairchild",
        cpa_license_state="NV",
        designations=["ENGAGEMENT_PARTNER"],
    )

    response = api.create_engagement(
        factories.engagement_payload(
            ctx["firm_id"],
            foreign_partner["id"],
            client_name="Aurora Metals Inc",
            engagement_type="REVIEW",
            period_end="2026-03-31",
        ),
        headers=ctx["mp_headers"],
    )

    validate_error(response, ERR_PARTNER_FIRM_MISMATCH, expected_status=409)
    _rows, meta = validate_paginated(
        api.list_engagements(
            headers=ctx["mp_headers"], params={"firm_id": ctx["firm_id"]}
        )
    )
    assert meta["total_count"] == 0, "no Engagement row may be created"


def test_inspection_selection_junction_is_reachable_from_both_parents(api):
    """An inspection selection is reachable from either of its two parents.

    "Selections may be listed filtered by `inspection_id`, by `engagement_id` or
    by `is_must_select`."

    Design: Corner/entities/inspection_selection_junction_is_reachable_from_both_parents
    """
    ctx = _firm_context(api)
    engagement = _accept_engagement(
        api,
        ctx,
        client_name="Aurora Metals Inc",
        engagement_type="REVIEW",
        period_end="2026-03-31",
    )
    for state in ("FIELDWORK", "EQR_PENDING", "EQR_CLEARED", "REPORT_RELEASED"):
        fixtures.workflow_step(api, engagement, state, ctx["ep_headers"])
    inspection = fixtures.new_inspection(
        api, ctx, inspection_year=2026, target_engagement_count=1
    )
    fixtures.run_selector(api, ctx, inspection["id"])
    by_inspection = fixtures.selections_of(api, ctx, inspection["id"])
    assert len(by_inspection) == 1, f"expected one selection, got {by_inspection}"

    rows, meta = validate_paginated(
        api.list_inspection_selections(
            headers=ctx["qc_headers"], params={"engagement_id": engagement["id"]}
        )
    )

    assert meta["total_count"] == 1, f"expected total_count 1, got {meta['total_count']}"
    selection = rows[0]
    assert selection["id"] == by_inspection[0]["id"], (
        "the engagement-filtered read must return the same junction row"
    )
    assertions.assert_fields(
        selection,
        inspection_id=inspection["id"],
        engagement_id=engagement["id"],
        selected_rank=1,
        is_must_select=True,
        selection_reason="MUST_SELECT_PARTNER_COVERAGE",
        finding_count=0,
    )
    assertions.assert_decimal_equals(selection["weighted_points"], 0.00)
