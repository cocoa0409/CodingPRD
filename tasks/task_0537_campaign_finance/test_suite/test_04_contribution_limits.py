"""Per-cycle contribution limits, boundary, and source-prohibition precedence."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    create_contribution_payload,
    TEST_USERS, make_treasurer_headers,
    set_clock, create_active_committee, add_contribution,
)

REGULATOR = TEST_USERS["regulator_headers"]


def test_contribution_at_exact_limit_accepted(api):
    """PRD §3.2: "The comparison is strict: the contribution is rejected with
    ERR_CONTRIBUTION_LIMIT_EXCEEDED only when the new aggregate is strictly greater than the
    limit; an aggregate exactly equal to the limit is allowed."

    Design: Difficulty/boundary_precision_check/contribution_limit_boundary
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    committee = create_active_committee(api, name="Kappa", committee_type="CANDIDATE")
    cid = committee["id"]
    # contributor r1 already at aggregate 300000
    add_contribution(api, cid, contributor_ref="r1", contributor_type="INDIVIDUAL", amount_cents=300000)
    # +30000 => aggregate exactly 330000 (== INDIVIDUAL->CANDIDATE limit) is allowed
    at_limit = validate_success(
        api.create_contribution(
            cid, create_contribution_payload(contributor_ref="r1", contributor_type="INDIVIDUAL", amount_cents=30000),
            make_treasurer_headers(cid),
        ),
        expected_status=201,
    )
    assert at_limit["settlement_status"] == "RECORDED", "at-limit aggregate 330000 must be accepted"


def test_contribution_one_over_limit_rejected(api):
    """PRD §3.2: "An INDIVIDUAL may give up to 330000 to a CANDIDATE committee" and "the
    contribution is rejected with ERR_CONTRIBUTION_LIMIT_EXCEEDED only when the new aggregate
    is strictly greater than the limit."

    Design: Difficulty/boundary_precision_check/contribution_limit_boundary
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    committee = create_active_committee(api, name="Kappa2", committee_type="CANDIDATE")
    cid = committee["id"]
    add_contribution(api, cid, contributor_ref="r1", contributor_type="INDIVIDUAL", amount_cents=330000)
    # +1 => aggregate 330001 > 330000 => rejected
    resp = api.create_contribution(
        cid, create_contribution_payload(contributor_ref="r1", contributor_type="INDIVIDUAL", amount_cents=1),
        make_treasurer_headers(cid),
    )
    validate_error(resp, ApiErrorId.ERR_CONTRIBUTION_LIMIT_EXCEEDED.value)


def test_prohibited_source_beats_limit_error_id(api):
    """PRD §2.7: "A source that is outright prohibited is rejected with ERR_PROHIBITED_SOURCE
    even if, numerically, the amount would also be within a limit."

    Design: Difficulty/priority_pair_validation_conflict/source_prohibition_beats_limit
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    committee = create_active_committee(api, name="Theta", committee_type="CANDIDATE")
    cid = committee["id"]
    # CORPORATION -> CANDIDATE is prohibited (corporations may give only to a PAC)
    resp = api.create_contribution(
        cid, create_contribution_payload(contributor_ref="corp1", contributor_name="BigCorp",
                                         contributor_type="CORPORATION", amount_cents=1000000),
        make_treasurer_headers(cid),
    )
    validate_error(resp, ApiErrorId.ERR_PROHIBITED_SOURCE.value)


def test_prohibited_source_not_reported_as_limit_error(api):
    """PRD §3.2: "A CORPORATION may contribute only to a PAC committee — never to a CANDIDATE
    or PARTY committee ... Any of these prohibited combinations is rejected with
    ERR_PROHIBITED_SOURCE."

    Design: Difficulty/priority_pair_validation_conflict/source_prohibition_beats_limit
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    committee = create_active_committee(api, name="Theta2", committee_type="CANDIDATE")
    cid = committee["id"]
    resp = api.create_contribution(
        cid, create_contribution_payload(contributor_ref="corp1", contributor_name="BigCorp",
                                         contributor_type="CORPORATION", amount_cents=1000000),
        make_treasurer_headers(cid),
    )
    err = validate_error(resp, ApiErrorId.ERR_PROHIBITED_SOURCE.value)
    assert err["error_id"] != ApiErrorId.ERR_CONTRIBUTION_LIMIT_EXCEEDED.value, (
        "source prohibition (step 13) must be decided before the limit aggregate (step 14)"
    )


def test_foreign_national_source_prohibited(api):
    """PRD §3.2: "A FOREIGN_NATIONAL may not contribute to any committee type ... Any of
    these prohibited combinations is rejected with ERR_PROHIBITED_SOURCE."

    Design: Corner/validations/foreign_national_prohibited_source_rejected
    """
    committee = create_active_committee(api, name="PacCo", committee_type="PAC")
    cid = committee["id"]
    resp = api.create_contribution(
        cid, create_contribution_payload(contributor_ref="fn1", contributor_name="Overseas",
                                         contributor_type="FOREIGN_NATIONAL", amount_cents=5000),
        make_treasurer_headers(cid),
    )
    validate_error(resp, ApiErrorId.ERR_PROHIBITED_SOURCE.value)
