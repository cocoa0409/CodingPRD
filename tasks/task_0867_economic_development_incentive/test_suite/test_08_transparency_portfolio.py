"""Transparency disclosure snapshots, the portfolio dashboard aggregate shape, list
pagination envelope, and FK reverse-reachability by program filter."""
from test_helpers import (
    validate_success, validate_paginated,
    create_program, setup_executed_agreement,
    make_officer_headers, make_director_headers, TEST_USERS,
)

OFFICER = make_officer_headers("officer-1")
DIRECTOR = make_director_headers("director-1")
PUBLIC = TEST_USERS["public_headers"]


def test_disclosure_snapshots_agreement_fields(api):
    """PRD §3.8: "Publication snapshots five public facts at the moment of disclosure:
    `disclosed_recipient_name` from the originating application's `applicant_name`,
    `disclosed_incentive_type` from the agreement's `incentive_type`, `disclosed_max_incentive_cents`
    from the agreement's `max_incentive_cents`, `disclosed_net_disbursed_cents` from the
    agreement's `net_disbursed_cents` at publication, and `disclosed_jobs_committed` from the
    agreement's `awarded_jobs`."

    Design: Corner/cross_cutting_complexity_layers/disclosure_snapshots_agreement_fields
    """
    ctx = setup_executed_agreement(app_overrides={"but_for_attested": True})
    disc = validate_success(api.create_disclosure(ctx["agreement"]["id"], {"disclosure_year": 2027}, OFFICER),
                            expected_status=201)
    assert disc["disclosed_max_incentive_cents"] == 50_000_000, disc["disclosed_max_incentive_cents"]
    assert disc["disclosed_jobs_committed"] == 100, disc["disclosed_jobs_committed"]
    assert disc["disclosed_incentive_type"] == "GRANT"
    assert disc["status"] == "PUBLISHED"


def test_portfolio_summary_returns_aggregate_shape(api):
    """PRD §3.8: "It reports `active_agreement_count` as the number of agreements in `ACTIVE`,
    `defaulted_agreement_count` as the number in `DEFAULTED`, `total_committed_cents` as the sum of
    every program's `committed_cents`, `total_disbursed_cents` as the sum of every program's
    `disbursed_cents`, and `total_recaptured_cents` as the sum of `assessed_amount_cents` across
    recapture assessments in status `FINALIZED`."

    Design: Corner/endpoints/portfolio_summary_returns_aggregate_shape
    """
    data = validate_success(api.portfolio_summary(PUBLIC))
    assert data["active_agreement_count"] == 0
    assert data["defaulted_agreement_count"] == 0
    assert data["total_committed_cents"] == 0
    assert data["total_disbursed_cents"] == 0
    assert data["total_recaptured_cents"] == 0


def test_list_programs_pagination_envelope(api):
    """PRD §2.3: "The `limit` defaults to 10, must be at least 1, and may not exceed 100; the
    `offset` defaults to 0 and must be at least 0." The list meta carries total_count and
    has_more.

    Design: Corner/endpoints/list_programs_pagination_envelope
    """
    create_program()
    data, meta = validate_paginated(api.list_programs(PUBLIC))
    assert meta["total_count"] >= 1
    assert meta["limit"] == 10
    assert meta["offset"] == 0
    assert "has_more" in meta


def test_agreement_reverse_reachable_by_program_filter(api):
    """PRD §2.3: "agreements by `program_id`, `application_id`, `parcel_id`, and `status`". Filtering
    agreements by program_id returns the agreement just executed under that program.

    Design: Corner/consistency_model/agreement_reverse_reachable_by_program_filter
    """
    ctx = setup_executed_agreement(app_overrides={"but_for_attested": True})
    agr_id = ctx["agreement"]["id"]
    data, _ = validate_paginated(api.list_agreements(DIRECTOR, params={"program_id": ctx["program"]["id"]}))
    match = [a for a in data if a["id"] == agr_id]
    assert match, f"agreement {agr_id} not reverse-reachable by program filter"
    assert match[0]["status"] == "EXECUTED"
