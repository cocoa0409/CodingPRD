"""Composite setup helpers.

Two layers live here:

* **Atoms** — one thin wrapper per write endpoint that performs the bookkeeping
  the PRD forces on every caller: fetching the work version before filing a
  registration, fetching the period version before building a statement,
  routing each call through the correct role, and keeping the fuzzy matcher and
  the reviewing analyst distinct.
* **Composites** — the multi-step preambles that several test claims share
  (a matched usage batch, a calculated pool, an issued statement, a closed
  period, an audit engagement with its data production complete).

Every atom uses ``get_success_data`` so a broken precondition reports as a
setup failure rather than a confusing assertion failure.
"""

from prd_bench_local_runner.testing import get_success_data

from .constants import TEST_DEFAULTS
from .factories import (
    audit_engagement_payload,
    composition_payload,
    data_production_payload,
    dispute_payload,
    findings_payload,
    period_payload,
    pool_payload,
    rate_schedule_payload,
    rejection_payload,
    rights_holder_payload,
    rights_registration_payload,
    settlement_payload,
    statement_payload,
    usage_batch_payload,
    usage_line_payload,
    work_payload,
)
from .test_users import (
    TEST_USERS,
    make_rights_holder_user_headers,
)

ADMIN = TEST_USERS["royalty_admin_headers"]
ANALYST = TEST_USERS["rights_ops_analyst_headers"]
REGULATOR = TEST_USERS["regulatory_officer_headers"]
MATCHER = TEST_USERS["fuzzy_matcher_headers"]
REVIEWER = TEST_USERS["reviewer_headers"]
SETTLING_ADMIN = TEST_USERS["settling_admin_headers"]


# ─────────────────────────────────────────────────────
# Atoms
# ─────────────────────────────────────────────────────

def set_clock(api, to_iso8601, headers=ADMIN):
    """Move the logical clock to an exact instant."""
    response = api.set_clock(to_iso8601, headers)
    assert 200 <= response.status_code < 300, (
        f"Setup step failed: clock could not be set to {to_iso8601} "
        f"(HTTP {response.status_code})"
    )
    return response


def create_holder(api, **overrides):
    return get_success_data(
        api.create_rights_holder(rights_holder_payload(**overrides), ADMIN)
    )


def create_label(api, legal_name="Northbeam Records", territory="GB", rate_bps=800):
    return create_holder(
        api,
        legal_name=legal_name,
        holder_type="LABEL",
        home_territory_code=territory,
        direct_deal_rate_bps=rate_bps,
    )


def create_publisher(api, legal_name="Harbourline Publishing", territory="GB", rate_bps=None):
    payload = {
        "legal_name": legal_name,
        "holder_type": "PUBLISHER",
        "home_territory_code": territory,
    }
    if rate_bps is not None:
        payload["direct_deal_rate_bps"] = rate_bps
    return create_holder(api, **payload)


def create_collective(api, legal_name="British Mechanical Collective", territory="WORLD"):
    return create_holder(
        api,
        legal_name=legal_name,
        holder_type="COLLECTIVE",
        home_territory_code=territory,
    )


def create_work(api, **overrides):
    return get_success_data(api.create_work(work_payload(**overrides), ANALYST))


def create_recording(api, identifier=None, title=None, artist=None, linked_work_id=None):
    payload = {
        "work_type": "RECORDING",
        "identifier": identifier or TEST_DEFAULTS["RECORDING_A_ISRC"],
        "title": title or TEST_DEFAULTS["RECORDING_A_TITLE"],
        "artist_credit": artist or TEST_DEFAULTS["RECORDING_A_ARTIST"],
    }
    if linked_work_id is not None:
        payload["linked_work_id"] = linked_work_id
    return create_work(api, **payload)


def create_composition(api, identifier=None, title=None):
    """A composition carries no artist credit, so the field is left out."""
    return get_success_data(
        api.create_work(
            composition_payload(
                identifier=identifier or TEST_DEFAULTS["COMPOSITION_A_ISWC"],
                title=title or TEST_DEFAULTS["COMPOSITION_A_TITLE"],
            ),
            ANALYST,
        )
    )


def create_period(api, **overrides):
    return get_success_data(api.create_period(period_payload(**overrides), ADMIN))


def create_batch(api, period_id, **overrides):
    return get_success_data(
        api.create_usage_batch(usage_batch_payload(period_id, **overrides), ANALYST)
    )


def append_line(api, batch_id, **overrides):
    return get_success_data(
        api.append_usage_line(batch_id, usage_line_payload(**overrides), ANALYST)
    )


def seal_batch(api, batch_id):
    return get_success_data(api.seal_usage_batch(batch_id, ANALYST))


def match_batch(api, batch_id, headers=MATCHER):
    """Run matching as the fuzzy-matching analyst, who may not later approve
    the claims their provisional matches enable."""
    return get_success_data(api.match_usage_batch(batch_id, headers))


def seal_and_match_batch(api, batch_id, headers=MATCHER):
    seal_batch(api, batch_id)
    return match_batch(api, batch_id, headers)


def work_version(api, work_id, headers=ANALYST):
    return get_success_data(api.get_work(work_id, headers))["version"]


def period_version(api, period_id, headers=ADMIN):
    return get_success_data(api.get_period(period_id, headers))["version"]


def file_registration(api, work_id, claimant_id, headers=None, **overrides):
    """File a claim, reading the work's current version immediately beforehand."""
    payload = rights_registration_payload(
        work_id, claimant_id, work_version(api, work_id), **overrides
    )
    return get_success_data(
        api.create_rights_registration(
            payload, headers or make_rights_holder_user_headers(claimant_id)
        )
    )


def review_registration(api, registration_id, headers=REVIEWER):
    return get_success_data(api.review_rights_registration(registration_id, headers))


def approve_registration(api, registration_id, headers=REVIEWER):
    return get_success_data(api.approve_rights_registration(registration_id, headers))


def reject_registration(api, registration_id, headers=REVIEWER, **overrides):
    return get_success_data(
        api.reject_rights_registration(registration_id, rejection_payload(**overrides), headers)
    )


def request_evidence(api, registration_id, headers=REVIEWER):
    return get_success_data(api.request_registration_evidence(registration_id, headers))


def submit_evidence(api, registration_id, holder_id):
    return get_success_data(
        api.submit_registration_evidence(
            registration_id, make_rights_holder_user_headers(holder_id)
        )
    )


def dispute_registration(api, registration_id, disputing_holder_id):
    return get_success_data(
        api.dispute_rights_registration(
            registration_id,
            dispute_payload(disputing_holder_id),
            make_rights_holder_user_headers(disputing_holder_id),
        )
    )


def file_and_approve_registration(api, work_id, claimant_id, **overrides):
    """File, take into review and approve one claim."""
    registration = file_registration(api, work_id, claimant_id, **overrides)
    review_registration(api, registration["id"])
    return approve_registration(api, registration["id"])


def file_registration_under_review(api, work_id, claimant_id, **overrides):
    registration = file_registration(api, work_id, claimant_id, **overrides)
    return review_registration(api, registration["id"])


def create_schedule(api, **overrides):
    return get_success_data(
        api.create_rate_schedule(rate_schedule_payload(**overrides), REGULATOR)
    )


def promulgate_schedule(api, schedule_id, supersede_incumbent=None):
    payload = {} if supersede_incumbent is None else {"supersede_incumbent": supersede_incumbent}
    return get_success_data(
        api.promulgate_rate_schedule(schedule_id, REGULATOR, payload)
    )


def create_effective_schedule(api, supersede_incumbent=None, **overrides):
    """Record a proposed schedule and bring it into force."""
    schedule = create_schedule(api, **overrides)
    return promulgate_schedule(api, schedule["id"], supersede_incumbent)


def create_pool(api, period_id, **overrides):
    return get_success_data(api.create_pool(pool_payload(period_id, **overrides), ADMIN))


def calculate_pool(api, pool_id):
    return get_success_data(api.calculate_pool(pool_id, ADMIN))


def finalize_pool(api, pool_id):
    return get_success_data(api.finalize_pool(pool_id, ADMIN))


def create_calculated_pool(api, period_id, **overrides):
    pool = create_pool(api, period_id, **overrides)
    return calculate_pool(api, pool["id"])


def create_finalized_pool(api, period_id, **overrides):
    pool = create_pool(api, period_id, **overrides)
    calculate_pool(api, pool["id"])
    return finalize_pool(api, pool["id"])


def create_statement(api, rights_holder_id, period_id):
    """Build a draft statement, reading the period version immediately beforehand."""
    return get_success_data(
        api.create_statement(
            statement_payload(rights_holder_id, period_id, period_version(api, period_id)),
            ADMIN,
        )
    )


def issue_statement(api, statement_id):
    return get_success_data(api.issue_statement(statement_id, ADMIN))


def create_and_issue_statement(api, rights_holder_id, period_id):
    statement = create_statement(api, rights_holder_id, period_id)
    return issue_statement(api, statement["id"])


def statement_lines(api, statement_id, headers=ADMIN, **filters):
    params = {"statement_id": statement_id}
    params.update(filters)
    return get_success_data(api.list_statement_lines(headers, params=params))


def close_period(api, period_id):
    return get_success_data(api.close_period(period_id, ADMIN))


def create_engagement(api, rights_holder_id, statement_id, **overrides):
    return get_success_data(
        api.create_audit_engagement(
            audit_engagement_payload(rights_holder_id, statement_id, **overrides),
            make_rights_holder_user_headers(rights_holder_id),
        )
    )


def produce_audit_data(api, engagement_id, statement_line_ids):
    return get_success_data(
        api.produce_audit_data(
            engagement_id, data_production_payload(statement_line_ids), ADMIN
        )
    )


def record_findings(api, engagement_id, rights_holder_id, asserted_underpayment_cents, **overrides):
    return get_success_data(
        api.record_audit_findings(
            engagement_id,
            findings_payload(asserted_underpayment_cents, **overrides),
            make_rights_holder_user_headers(rights_holder_id),
        )
    )


def settle_engagement(api, engagement_id, resolution, **overrides):
    """Settle as an admin who is not the user that recorded the finding."""
    return get_success_data(
        api.settle_audit_engagement(
            engagement_id, settlement_payload(resolution, **overrides), SETTLING_ADMIN
        )
    )


# ─────────────────────────────────────────────────────
# Composites
# ─────────────────────────────────────────────────────

CANONICAL_SCHEDULE = dict(
    proceeding_ref=TEST_DEFAULTS["SCHEDULE_PROCEEDING_REF"],
    territory_code="GB",
    subscription_tier="INDIVIDUAL",
    revenue_share_bps=7000,
    per_subscriber_minimum_cents=500,
    mechanical_share_bps=4000,
    performance_share_bps=6000,
    statutory_floor_per_play_millicents=100,
    effective_from=TEST_DEFAULTS["SCHEDULE_EFFECTIVE_FROM"],
    effective_to=TEST_DEFAULTS["SCHEDULE_EFFECTIVE_TO"],
)


def setup_gb_individual_usage(
    api,
    *,
    with_schedule=True,
    with_label=True,
    fuzzy_second_line=True,
    third_line=True,
    schedule_overrides=None,
):
    """The shared GB/INDIVIDUAL usage preamble.

    Creates an EFFECTIVE GB/INDIVIDUAL rate schedule, the 2026-06 period, the
    'Midnight Ledger' recording (and the 'Neon Ledger' recording when a third
    line is requested), and one sealed, matched batch:

    * line 1 — 300000 plays reported with the exact ISRC of 'Midnight Ledger';
    * line 2 — 150000 plays reported either with the same exact ISRC
      (``fuzzy_second_line=False``) or with messy title/artist text that only
      normalization resolves (``fuzzy_second_line=True``);
    * line 3 — 50000 plays reported with the bare title 'Neon Ledger' and no
      ISRC and no artist, which no automatic rung can resolve
      (``third_line=True``).

    Returns a dict of every entity created.
    """
    fixture = {}

    if with_label:
        fixture["label"] = create_label(api)

    if with_schedule:
        overrides = dict(CANONICAL_SCHEDULE)
        overrides.update(schedule_overrides or {})
        fixture["schedule"] = create_effective_schedule(api, **overrides)

    fixture["period"] = create_period(api)
    fixture["recording_a"] = create_recording(
        api,
        identifier=TEST_DEFAULTS["RECORDING_A_ISRC"],
        title=TEST_DEFAULTS["RECORDING_A_TITLE"],
        artist=TEST_DEFAULTS["RECORDING_A_ARTIST"],
    )
    if third_line:
        fixture["recording_b"] = create_recording(
            api,
            identifier=TEST_DEFAULTS["RECORDING_B_ISRC"],
            title=TEST_DEFAULTS["RECORDING_B_TITLE"],
            artist=TEST_DEFAULTS["RECORDING_B_ARTIST"],
        )

    fixture["batch"] = create_batch(api, fixture["period"]["id"])
    batch_id = fixture["batch"]["id"]

    lines = [
        append_line(
            api,
            batch_id,
            reported_isrc=TEST_DEFAULTS["RECORDING_A_ISRC"],
            reported_title=TEST_DEFAULTS["RECORDING_A_TITLE"],
            reported_artist=TEST_DEFAULTS["RECORDING_A_ARTIST"],
            territory_code="GB",
            subscription_tier="INDIVIDUAL",
            play_count=300000,
        )
    ]
    if fuzzy_second_line:
        lines.append(
            append_line(
                api,
                batch_id,
                reported_title=TEST_DEFAULTS["MESSY_TITLE_A"],
                reported_artist=TEST_DEFAULTS["MESSY_ARTIST_A"],
                territory_code="GB",
                subscription_tier="INDIVIDUAL",
                play_count=150000,
            )
        )
    else:
        lines.append(
            append_line(
                api,
                batch_id,
                reported_isrc=TEST_DEFAULTS["RECORDING_A_ISRC"],
                reported_title=TEST_DEFAULTS["RECORDING_A_TITLE"],
                reported_artist=TEST_DEFAULTS["RECORDING_A_ARTIST"],
                territory_code="GB",
                subscription_tier="INDIVIDUAL",
                play_count=150000,
            )
        )
    if third_line:
        lines.append(
            append_line(
                api,
                batch_id,
                reported_title=TEST_DEFAULTS["RECORDING_B_TITLE"],
                territory_code="GB",
                subscription_tier="INDIVIDUAL",
                play_count=50000,
            )
        )

    fixture["usage_lines"] = lines
    fixture["batch_after_match"] = seal_and_match_batch(api, batch_id)
    return fixture


def setup_canonical_matched_batch(api, **kwargs):
    """Three GB/INDIVIDUAL lines, the third left unresolved at 5000 confidence."""
    return setup_gb_individual_usage(api, fuzzy_second_line=True, third_line=True, **kwargs)


def setup_all_matched_batch(api, **kwargs):
    """Two GB/INDIVIDUAL lines, both resolved by exact ISRC, nothing unmatched."""
    return setup_gb_individual_usage(api, fuzzy_second_line=False, third_line=False, **kwargs)


def _add_master_registration(api, fixture):
    fixture["master_registration"] = file_and_approve_registration(
        api,
        fixture["recording_a"]["id"],
        fixture["label"]["id"],
        right_type="MASTER",
        routing="DIRECT",
        share_bps=10000,
        territory_set=["WORLD"],
    )
    return fixture


def _add_pool(api, fixture, *, finalize=False, pool_overrides=None):
    overrides = dict(
        territory_code="GB",
        subscription_tier="INDIVIDUAL",
        subscriber_count=TEST_DEFAULTS["CANONICAL_SUBSCRIBER_COUNT"],
        gross_revenue_cents=TEST_DEFAULTS["CANONICAL_GROSS_REVENUE_CENTS"],
    )
    overrides.update(pool_overrides or {})
    pool = create_pool(api, fixture["period"]["id"], **overrides)
    fixture["pool"] = calculate_pool(api, pool["id"])
    if finalize:
        fixture["pool"] = finalize_pool(api, pool["id"])
    return fixture


def setup_canonical_pool_calculated(api, *, pool_overrides=None, **kwargs):
    """Canonical batch, the master claim approved, and the GB/INDIVIDUAL pool
    CALCULATED but deliberately not frozen."""
    fixture = setup_canonical_matched_batch(api, **kwargs)
    _add_master_registration(api, fixture)
    return _add_pool(api, fixture, finalize=False, pool_overrides=pool_overrides)


def setup_canonical_pool_finalized(api, *, pool_overrides=None, **kwargs):
    """Canonical batch, master claim approved, pool FINALIZED (period DISTRIBUTED)."""
    fixture = setup_canonical_matched_batch(api, **kwargs)
    _add_master_registration(api, fixture)
    return _add_pool(api, fixture, finalize=True, pool_overrides=pool_overrides)


def setup_canonical_statement_issued(api, *, pool_overrides=None, **kwargs):
    """Canonical fixture carried all the way to an ISSUED statement for the label.

    The statement carries exactly two lines: one USAGE MASTER line and one
    RESIDUAL line for the two cents of rounding residue.
    """
    fixture = setup_canonical_pool_finalized(api, pool_overrides=pool_overrides, **kwargs)
    fixture["statement"] = create_and_issue_statement(
        api, fixture["label"]["id"], fixture["period"]["id"]
    )
    fixture["statement_lines"] = statement_lines(api, fixture["statement"]["id"])
    return fixture


def setup_all_matched_pool_finalized(api, *, pool_overrides=None, **kwargs):
    """All-matched fixture with the master claim approved and the pool FINALIZED."""
    fixture = setup_all_matched_batch(api, **kwargs)
    _add_master_registration(api, fixture)
    return _add_pool(api, fixture, finalize=True, pool_overrides=pool_overrides)


def setup_all_matched_statement_drafted(api, **kwargs):
    """All-matched fixture with the label's statement built but not yet issued."""
    fixture = setup_all_matched_pool_finalized(api, **kwargs)
    fixture["statement"] = create_statement(
        api, fixture["label"]["id"], fixture["period"]["id"]
    )
    return fixture


def setup_all_matched_statement_issued(api, **kwargs):
    """All-matched fixture with the label's single-line statement ISSUED."""
    fixture = setup_all_matched_pool_finalized(api, **kwargs)
    fixture["statement"] = create_and_issue_statement(
        api, fixture["label"]["id"], fixture["period"]["id"]
    )
    fixture["statement_lines"] = statement_lines(api, fixture["statement"]["id"])
    return fixture


def setup_all_matched_closed_period(api, closing_clock="2026-08-30T00:00:00Z", **kwargs):
    """All-matched fixture issued, the clock moved past the claim window, and the
    period CLOSED — nothing is left in holding, so the close is legal."""
    fixture = setup_all_matched_statement_issued(api, **kwargs)
    set_clock(api, closing_clock)
    fixture["period_after_close"] = close_period(api, fixture["period"]["id"])
    return fixture


def setup_audit_engagement(api, *, produce_all_lines=True, base=None, **kwargs):
    """An audit engagement against the canonical two-line issued statement.

    With ``produce_all_lines=True`` every line of the audited statement has been
    produced, so production_status is COMPLETE and a finding may be asserted.
    """
    fixture = base if base is not None else setup_canonical_statement_issued(api, **kwargs)
    fixture["engagement"] = create_engagement(
        api, fixture["label"]["id"], fixture["statement"]["id"]
    )
    if produce_all_lines:
        for line in fixture["statement_lines"]:
            fixture["engagement"] = produce_audit_data(
                api, fixture["engagement"]["id"], [line["id"]]
            )
    return fixture


def setup_registration_under_review_for_recording_b(api, *, second_label=False, **kwargs):
    """Canonical fixture with the pool CALCULATED and a master claim over the
    unresolved 'Neon Ledger' recording sitting in UNDER_REVIEW.

    This is the state from which one approve produces the full three-link
    cascade, and from which a dispute by a rival holder reverses it.
    """
    fixture = setup_canonical_pool_calculated(api, **kwargs)
    if second_label:
        fixture["rival_label"] = create_label(
            api, legal_name="Kestrel Tapes", territory="GB", rate_bps=800
        )
    fixture["claim_registration"] = file_registration_under_review(
        api,
        fixture["recording_b"]["id"],
        fixture["label"]["id"],
        right_type="MASTER",
        routing="DIRECT",
        share_bps=10000,
        territory_set=["WORLD"],
    )
    return fixture
