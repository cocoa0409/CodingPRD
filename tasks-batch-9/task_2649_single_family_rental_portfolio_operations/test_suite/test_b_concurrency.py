"""The two mandatory version fields, and what they do and do not guard.

Neither of these is a workflow check. Re-underwriting a home and re-verifying a prospect
are both legitimate at any time, so the only thing a replayed request can be refused for
is having read a version that has since moved on -- and once the caller re-reads, the
identical payload is accepted.
"""

from test_helpers import factories as f
from test_helpers import fixtures as x
from test_helpers.api_errors import (
    ERR_STALE_HOME_VERSION,
    ERR_STALE_PROSPECT_VERSION,
)
from test_helpers.assertions import (
    assert_fields,
    assert_money_group,
    assert_page_meta,
    assert_version,
    created,
    failed,
    ok,
    page,
)
from test_helpers.constants import (
    CASE_DRAFT,
    CASE_SUPERSEDED,
    CLOCK_AUG_01,
    FRAUD_VARIANT_POST,
    IDENTITY_VERIFIED,
)
from test_helpers.test_users import make_prospect_headers


def test_the_case_the_patch_invalidated_is_refused_and_the_re_read_one_supersedes_twice(api):
    """Version 1 is stale, version 2 is accepted -- twice, because staleness is the only guard.

    PRD SS2.6: "Opening an underwriting case requires `expected_home_version` in the request body.
    This field is mandatory, not optional, and it must carry the `version` of the target `Home` as
    the client last read it. If it does not equal the home's current `version`, the create is
    rejected with `ERR_STALE_HOME_VERSION` (HTTP 412) and nothing is written. This check exists
    because re-underwriting a scattered-site home is legitimate at any time, and a newly created case
    supersedes the prior non-terminal case for that home; on product semantics alone a second create
    observing the same stored state would succeed, so the stale-version comparison is what makes the
    supersede deterministic."  The supersede is PRD SS3.2's: "Every prior underwriting case on the
    same home whose `status` is `DRAFT`, `SUBMITTED` or `REVISION_REQUESTED` is moved to
    `SUPERSEDED` ... The new case is created in `DRAFT` with `revision_round` 0".  The basis is
    step (1) of PRD SS3.2's skeleton -- "the all-in basis is `purchase_price_cents` plus
    `acquisition_closing_costs_cents` plus a renovation figure" -- over the PRD's own per-line
    benchmark: in "a market whose `cost_index_bps` is 10250 ... an interior paint at 285050 cents for
    one unit" prices at "292176".  The patch that moves the version is PRD SS3.1's: "only the
    supplied fields are overwritten. ... Either way the home's `version` increments by 1."

    Design: Corner/cross_cutting_complexity_layers/underwriting_case_create_rejects_a_stale_home_version
    """
    x.set_clock(api, CLOCK_AUG_01)
    market = x.create_market(api)
    paint = x.create_scope_template(api, f.scope_template_general())
    home = x.create_home(api, market["id"])
    assert_version(home, 1)

    repriced = ok(api.patch_home(home["id"], {"asking_rent_cents": 220000}, x.ANALYST))
    assert_version(repriced, 2)
    lines = [f.scope_line(paint["id"], 1)]

    failed(
        api.create_underwriting_case(
            f.underwriting_case_payload(home["id"], home["version"], lines), x.ANALYST
        ),
        ERR_STALE_HOME_VERSION,
    )
    _, empty = page(api.list_underwriting_cases(x.ANALYST, {"home_id": home["id"]}))
    assert_page_meta(empty, total_count=0)

    first = created(
        api.create_underwriting_case(
            f.underwriting_case_payload(home["id"], repriced["version"], lines), x.ANALYST
        )
    )
    assert_fields(first, status=CASE_DRAFT, revision_round=0)
    assert_money_group(
        first,
        underwritten_all_in_basis_cents=26042176,
        planned_renovation_budget_cents=292176,
    )

    second = created(
        api.create_underwriting_case(
            f.underwriting_case_payload(
                home["id"], repriced["version"], lines, purchase_price_cents=24500000
            ),
            x.ANALYST,
        )
    )
    assert_fields(second, status=CASE_DRAFT)
    assert_fields(
        ok(api.get_underwriting_case(first["id"], x.ANALYST)), status=CASE_SUPERSEDED
    )
    assert_version(ok(api.get_home(home["id"], x.ANALYST)), 2)

    rows, meta = page(api.list_underwriting_cases(x.ANALYST, {"home_id": home["id"]}))
    assert_page_meta(meta, total_count=2)
    assert sorted(row["id"] for row in rows) == sorted([first["id"], second["id"]])


def test_replaying_the_pre_verification_version_is_refused_and_the_retry_rescores_the_same(api):
    """Identical signals, identical score, and only the counters move -- when they are allowed to.

    PRD SS2.6: "Recording an identity verification against a prospect requires
    `expected_prospect_version` in the request body, again mandatory, carrying the `version` of the
    target `Prospect` as the client last read it. A mismatch with the prospect's current `version` is
    rejected with `ERR_STALE_PROSPECT_VERSION` (HTTP 412). Re-verification is always permitted and
    legitimately supersedes the stored document, device and income signals, so the guard is expressed
    purely as a stale-version comparison against `Prospect.version` and never against any workflow
    status."  Each accepted attempt is PRD SS3.6's: "Every supplied signal overwrites the stored one,
    `verification_attempt_count` increases by 1, and the prospect's `version` increases by 1. The
    outcome is a two-clause conjunction: `identity_status` becomes `VERIFIED` when
    `selfie_liveness_pass` is true **and** `document_match_score_bps` is at or above 5000".  The
    self-loop is explicitly legal -- PRD SS3.6: "the self-loop `VERIFIED` -> `VERIFIED` when an
    already-verified prospect submits another passing attempt -- the re-verification supersede case
    the version check guards. Every one of those attempts rescores the prospect with the
    post-verification variant and stamps `fraud_score_variant` `POST_VERIFICATION`."  The score is
    the PRD's own worked figure: "The same prospect then verifies with a document score of 9200,
    liveness true, a verified income of 560000, a device reputation of 8800 and 15 km of geo
    distance: identity becomes 800, income becomes 1111, history stays 1500, device becomes 1200,
    and the score falls to 1093 basis points".  A refused attempt writes nothing, PRD SS2.9: "if a
    guard rejects the operation, nothing at all is written, including the cascade targets."

    Design: Corner/cross_cutting_complexity_layers/identity_reverification_rejects_a_stale_prospect_version
    """
    x.set_clock(api, CLOCK_AUG_01)
    market = x.create_market(api)
    prospect = x.create_prospect(api, market["id"])
    assert_version(prospect, 1)
    acting = make_prospect_headers(prospect["id"])

    verified = ok(
        api.verify_identity(
            prospect["id"],
            f.identity_verification_payload(prospect["version"]),
            acting,
        )
    )
    assert_fields(
        verified,
        identity_status=IDENTITY_VERIFIED,
        verification_attempt_count=1,
        fraud_risk_score_bps=1093,
        fraud_score_variant=FRAUD_VARIANT_POST,
    )
    assert_version(verified, 2)

    failed(
        api.verify_identity(
            prospect["id"],
            f.identity_verification_payload(prospect["version"]),
            acting,
        ),
        ERR_STALE_PROSPECT_VERSION,
    )
    unmoved = ok(api.get_prospect(prospect["id"], acting))
    assert_fields(unmoved, verification_attempt_count=1, fraud_risk_score_bps=1093)
    assert_version(unmoved, 2)

    again = ok(
        api.verify_identity(
            prospect["id"],
            f.identity_verification_payload(verified["version"]),
            acting,
        )
    )
    assert_fields(
        again,
        identity_status=IDENTITY_VERIFIED,
        verification_attempt_count=2,
        fraud_risk_score_bps=1093,
        fraud_score_variant=FRAUD_VARIANT_POST,
    )
    assert_version(again, 3)
