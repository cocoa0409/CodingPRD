"""Declared state machines: seeded initial states, refused transitions and terminal lockdowns.

Every entity on this platform is seeded in a declared initial state and moves
only along declared edges. This module walks the edges that do *not* exist as
well as the ones that do: certification demanded of a batch that was never
scored, a second scoring of an already scored batch, a second claim over a batch
whose settlement dimension has closed for good, a standing change against a
delisted publisher, and the two terminal appeal outcomes - the overturn that
ripples through four entities and the uphold that must leave every one of them
exactly where it stood.
"""
import pytest

from test_helpers import (
    ANALYST_AUTHOR_USER_ID,
    ANALYST_REVIEWER_USER_ID,
    AUDITOR_AUTHOR_USER_ID,
    OFFICER_USER_ID,
    OPERATOR_USER_ID,
    ApiErrorId,
    advance_clock,
    factories,
    make_admin_headers,
    make_officer_headers,
    make_operator_headers,
    read_advertiser,
    read_batch,
    read_campaign,
    read_claim,
    read_classification,
    read_page,
    read_publisher,
    setup_advertiser,
    setup_base_world,
    setup_campaign,
    setup_classification,
    setup_filed_appeal,
    setup_ingested_batch,
    setup_inventory_list,
    setup_methodology_version,
    setup_pre_bid_segment,
    setup_proposed_finding,
    setup_publisher,
    setup_quarantined_batch,
    setup_reviewed_classification,
    setup_submitted_claim,
    validate_error,
    validate_paginated,
    validate_success,
)

CLOCK = "2026-08-10T00:00:00Z"

#: A publisher that buys 40% of its sessions from traffic vendors. The share is
#: one of the four made-for-advertising inputs and is read at classification time.
SOURCED_PUBLISHER = {"sourced_traffic_pct": 0.40}

#: Sensor figures whose coverage_rate is 9000/10000 = 0.9000, comfortably above
#: the 0.7 floor, with the whole in-view claim accepted wholesale.
FULL_COVERAGE_FIGURES = {"measurable_impressions": 9000, "in_view_impressions": 9000}

#: Sensor figures whose coverage_rate is 6000/10000 = 0.6000, below the 0.7
#: floor, so certification lands the batch in QUARANTINED.
SHORT_COVERAGE_FIGURES = {"measurable_impressions": 6000, "in_view_impressions": 6000}

#: An attested HIGH_RISK verdict: one ARMS category weighs 40 risk points, a
#: HUMAN classifier attracts no confidence inflation and the mild
#: made-for-advertising signals leave the flag down, so adjusted_risk_points
#: lands at 40.00 in HIGH_RISK - one rung below a MEDIUM_RISK campaign floor.
ARMS_CLASSIFICATION = {
    "classifier_kind": "HUMAN",
    "category_codes": ["ARMS"],
    "ad_density_ratio": 0.10,
    "refresh_seconds": 0,
    "originality_score": 90,
}


def _appealed_world(api, reason_code: str):
    """A HIGH_RISK page attested by analyst-2, a QUARANTINED batch cited by a
    live claim, and an appeal filed against the attested classification.

    This is the position from which one DisputeOfficer decision either ripples
    through four entities or must change nothing at all beyond the appeal itself.
    """
    world = setup_base_world(api, clock=CLOCK, publisher_overrides=SOURCED_PUBLISHER)
    classification = setup_reviewed_classification(
        api,
        world["page"],
        world["suitability_version"]["id"],
        decision="CONFIRM",
        reviewer_user_id=ANALYST_REVIEWER_USER_ID,
        classification_overrides=dict(ARMS_CLASSIFICATION),
        review_note="Firearms editorial confirmed",
    )
    batch = setup_quarantined_batch(api, world, **FULL_COVERAGE_FIGURES)
    claim = setup_submitted_claim(api, world, batch_ids=[batch["id"]])
    filed = setup_filed_appeal(
        api,
        world,
        classification=classification,
        reason_code=reason_code,
        evidence_note="Page is a product safety review, not arms promotion",
    )
    return {
        "world": world,
        "classification": classification,
        "batch": batch,
        "claim": claim,
        "appeal": filed["appeal"],
    }


def test_certify_before_scoring_returns_invalid_batch_state(api):
    """Certification demanded of a batch that is still INGESTED is refused, and no
    scoring happens as a side effect of the refusal.

    PRD: "It is available only on a batch whose `scoring_status` is `SCORED`; anything else answers `ERR_INVALID_BATCH_STATE`."

    Design: Corner/state_machines/certify_before_scoring_returns_invalid_batch_state
    """
    world = setup_base_world(api, clock=CLOCK, publisher_overrides=SOURCED_PUBLISHER)
    setup_classification(api, world["page"], world["suitability_version"]["id"])
    batch = setup_ingested_batch(api, world, **FULL_COVERAGE_FIGURES)
    assert batch["scoring_status"] == "INGESTED", (
        f"expected INGESTED at ingestion, got {batch['scoring_status']}"
    )

    refused = api.certify_measurement_batch(
        batch["id"], make_operator_headers(OPERATOR_USER_ID)
    )
    validate_error(refused, ApiErrorId.ERR_INVALID_BATCH_STATE.value, 409)

    after = read_batch(api, batch["id"])
    assert after["scoring_status"] == "INGESTED", (
        f"expected INGESTED, got {after['scoring_status']} after the refused certify"
    )
    assert after["version"] == 1, (
        f"expected version 1, got {after['version']} after the refused certify"
    )
    assert after["scored_at"] is None, (
        f"expected scored_at null, got {after['scored_at']} after the refused certify"
    )
    assert after["settlement_status"] == "UNBILLED", (
        f"expected UNBILLED, got {after['settlement_status']} after the refused certify"
    )

    publisher = read_publisher(api, world["publisher"]["id"])
    assert publisher["certified_batch_count"] == 0, (
        f"expected certified_batch_count 0, got {publisher['certified_batch_count']}"
    )
    assert publisher["quarantined_batch_count"] == 0, (
        f"expected quarantined_batch_count 0, got {publisher['quarantined_batch_count']}"
    )

    campaign = read_campaign(api, world["campaign"]["id"])
    assert campaign["certified_measured_impressions"] == 0, (
        "expected certified_measured_impressions 0, got "
        f"{campaign['certified_measured_impressions']} after the refused certify"
    )
    assert campaign["certified_measurable_impressions"] == 0, (
        "expected certified_measurable_impressions 0, got "
        f"{campaign['certified_measurable_impressions']} after the refused certify"
    )
    assert campaign["coverage_status"] == "UNKNOWN", (
        f"expected UNKNOWN, got {campaign['coverage_status']} after the refused certify"
    )


def test_scoring_the_same_batch_twice_is_refused_on_the_second_call(api):
    """The first scoring of an INGESTED batch computes every figure; the replay of
    the same call is refused rather than silently recomputing them.

    PRD: "Scoring is requested on a batch whose `scoring_status` is `INGESTED`; anything else answers `ERR_INVALID_BATCH_STATE`, and so does any scoring attempt on a `DECERTIFIED` batch."

    Design: Corner/state_machines/scoring_the_same_batch_twice_is_refused_on_the_second_call
    """
    world = setup_base_world(api, clock=CLOCK, publisher_overrides=SOURCED_PUBLISHER)
    setup_classification(api, world["page"], world["suitability_version"]["id"])
    batch = setup_ingested_batch(api, world, **FULL_COVERAGE_FIGURES)
    operator = make_operator_headers(OPERATOR_USER_ID)

    scored = validate_success(api.score_measurement_batch(batch["id"], operator), 200)
    assert scored["scoring_status"] == "SCORED", (
        f"expected SCORED, got {scored['scoring_status']} after the first score"
    )
    assert scored["coverage_rate"] == pytest.approx(0.9000, abs=0.0001), (
        f"expected coverage_rate 0.9000, got {scored['coverage_rate']}"
    )
    assert scored["viewability_rate"] == pytest.approx(1.0000, abs=0.0001), (
        f"expected viewability_rate 1.0000, got {scored['viewability_rate']}"
    )
    assert scored["qualified_in_view_impressions"] == 9000, (
        "expected qualified_in_view_impressions 9000, got "
        f"{scored['qualified_in_view_impressions']}"
    )
    assert scored["unmeasurable_impressions"] == 1000, (
        f"expected unmeasurable_impressions 1000, got {scored['unmeasurable_impressions']}"
    )
    assert scored["non_viewable_impressions"] == 0, (
        f"expected non_viewable_impressions 0, got {scored['non_viewable_impressions']}"
    )
    assert scored["assessed_tier"] == "SAFE", (
        f"expected assessed_tier SAFE, got {scored['assessed_tier']}"
    )
    assert scored["suitability_breach_flag"] is False, (
        f"expected suitability_breach_flag false, got {scored['suitability_breach_flag']}"
    )
    assert scored["scored_at"] == "2026-08-10T00:00:00.000Z", (
        f"expected scored_at stamped from the clock, got {scored['scored_at']}"
    )
    assert scored["version"] == 2, (
        f"expected version 2, got {scored['version']} after the first score"
    )

    replayed = api.score_measurement_batch(batch["id"], operator)
    validate_error(replayed, ApiErrorId.ERR_INVALID_BATCH_STATE.value, 409)

    after = read_batch(api, batch["id"])
    assert after["scoring_status"] == "SCORED", (
        f"expected SCORED, got {after['scoring_status']} after the refused replay"
    )
    assert after["version"] == 2, (
        f"expected version still 2, got {after['version']} after the refused replay"
    )
    assert after["scored_at"] == "2026-08-10T00:00:00.000Z", (
        f"expected scored_at unchanged, got {after['scored_at']} after the refused replay"
    )
    assert after["coverage_rate"] == pytest.approx(0.9000, abs=0.0001), (
        f"expected coverage_rate unchanged at 0.9000, got {after['coverage_rate']}"
    )


def test_new_counterparties_and_campaign_start_in_their_declared_initial_states(api):
    """A freshly registered publisher, its advertiser counterparty and a new
    campaign all stand in their declared opening positions with zeroed counters.

    PRD: "A newly registered publisher stands at `publisher_status` `ACTIVE` with a null `status_reason`, and every quality counter — `mfa_page_count`, `quarantined_batch_count`, `certified_batch_count`, `decided_appeal_count`, `overturned_appeal_count` and `credit_issued_cents_total` — starts at 0."

    Design: Corner/state_machines/every_entity_starts_in_its_declared_initial_state
    """
    advance_clock(api, CLOCK)
    advertiser = setup_advertiser(api, credit_cap_cents=1000000)
    publisher = setup_publisher(api, **SOURCED_PUBLISHER)
    campaign = setup_campaign(api, advertiser["id"])

    assert publisher["publisher_status"] == "ACTIVE", (
        f"expected ACTIVE at registration, got {publisher['publisher_status']}"
    )
    assert publisher["status_reason"] is None, (
        f"expected status_reason null at registration, got {publisher['status_reason']}"
    )
    for counter in (
        "mfa_page_count",
        "quarantined_batch_count",
        "certified_batch_count",
        "decided_appeal_count",
        "overturned_appeal_count",
        "credit_issued_cents_total",
    ):
        assert publisher[counter] == 0, (
            f"expected {counter} 0 at registration, got {publisher[counter]}"
        )

    assert advertiser["credit_received_cents_total"] == 0, (
        "expected credit_received_cents_total 0 at registration, got "
        f"{advertiser['credit_received_cents_total']}"
    )
    assert advertiser["settled_claim_count"] == 0, (
        f"expected settled_claim_count 0, got {advertiser['settled_claim_count']}"
    )

    assert campaign["status"] == "ACTIVE", (
        f"expected ACTIVE at creation, got {campaign['status']}"
    )
    assert campaign["coverage_status"] == "UNKNOWN", (
        f"expected coverage_status UNKNOWN at creation, got {campaign['coverage_status']}"
    )
    assert campaign["certified_measured_impressions"] == 0, (
        "expected certified_measured_impressions 0 at creation, got "
        f"{campaign['certified_measured_impressions']}"
    )
    assert campaign["certified_measurable_impressions"] == 0, (
        "expected certified_measurable_impressions 0 at creation, got "
        f"{campaign['certified_measurable_impressions']}"
    )
    assert campaign["open_claim_count"] == 0, (
        f"expected open_claim_count 0 at creation, got {campaign['open_claim_count']}"
    )


def test_a_freshly_authored_methodology_version_stands_provisional(api):
    """A methodology version is usable for scoring the moment it is authored: it
    opens at PROVISIONAL with every audit field still null.

    PRD: "A freshly authored version stands at `accreditation_status` `PROVISIONAL`, and the platform stamps `authored_by_user_id` from the authoring auditor's `X-User-ID`."

    Design: Corner/state_machines/every_entity_starts_in_its_declared_initial_state
    """
    advance_clock(api, CLOCK)
    version = setup_methodology_version(
        api, standard_family="SUITABILITY", author_user_id=AUDITOR_AUTHOR_USER_ID
    )

    assert version["accreditation_status"] == "PROVISIONAL", (
        f"expected PROVISIONAL at authoring, got {version['accreditation_status']}"
    )
    assert version["authored_by_user_id"] == AUDITOR_AUTHOR_USER_ID, (
        f"expected authored_by_user_id {AUDITOR_AUTHOR_USER_ID}, "
        f"got {version['authored_by_user_id']}"
    )
    for field in (
        "audit_outcome",
        "audit_finding_rate",
        "deficiency_note",
        "lead_auditor_user_id",
    ):
        assert version[field] is None, (
            f"expected {field} null until an audit concludes, got {version[field]}"
        )
    assert version["decertified_batch_count"] == 0, (
        f"expected decertified_batch_count 0, got {version['decertified_batch_count']}"
    )
    assert version["version"] == 1, (
        f"expected version 1 at authoring, got {version['version']}"
    )


def test_new_page_list_segment_and_classification_start_in_their_declared_initial_states(api):
    """A registered page carries no verdict at all, and the list, the segment and
    the first classification record each open in their own declared position.

    PRD: "A new page stands at `classification_state` `UNCLASSIFIED` with `current_tier` null, `current_classification_id` null, `latest_category_codes` empty, `mfa_score` null, `mfa_flag` false and `appeal_count` 0."

    Design: Corner/state_machines/every_entity_starts_in_its_declared_initial_state
    """
    world = setup_base_world(api, clock=CLOCK, accredit=False)
    page = world["page"]

    assert page["classification_state"] == "UNCLASSIFIED", (
        f"expected UNCLASSIFIED at registration, got {page['classification_state']}"
    )
    assert page["current_classification_id"] is None, (
        "expected current_classification_id null at registration, got "
        f"{page['current_classification_id']}"
    )
    assert page["current_tier"] is None, (
        f"expected current_tier null at registration, got {page['current_tier']}"
    )
    assert page["latest_category_codes"] == [], (
        f"expected latest_category_codes empty, got {page['latest_category_codes']}"
    )
    assert page["mfa_flag"] is False, (
        f"expected mfa_flag false at registration, got {page['mfa_flag']}"
    )
    assert page["appeal_count"] == 0, (
        f"expected appeal_count 0 at registration, got {page['appeal_count']}"
    )

    exclusion_list = setup_inventory_list(
        api, world["advertiser"], list_type="EXCLUSION"
    )
    assert exclusion_list["status"] == "DRAFT", (
        f"expected DRAFT at creation, got {exclusion_list['status']}"
    )
    assert exclusion_list["entry_count"] == 0, (
        f"expected entry_count 0 at creation, got {exclusion_list['entry_count']}"
    )
    assert exclusion_list["published_version"] is None, (
        f"expected published_version null, got {exclusion_list['published_version']}"
    )
    assert exclusion_list["published_at"] is None, (
        f"expected published_at null, got {exclusion_list['published_at']}"
    )
    assert exclusion_list["stale_reason"] is None, (
        f"expected stale_reason null, got {exclusion_list['stale_reason']}"
    )

    segment = setup_pre_bid_segment(
        api,
        world["advertiser"],
        world["campaign"]["id"],
        exclusion_list_id=exclusion_list["id"],
    )
    assert segment["sync_status"] == "PENDING", (
        f"expected PENDING at creation, got {segment['sync_status']}"
    )
    assert segment["synced_at"] is None, (
        f"expected synced_at null at creation, got {segment['synced_at']}"
    )
    assert segment["synced_exclusion_version"] is None, (
        "expected synced_exclusion_version null at creation, got "
        f"{segment['synced_exclusion_version']}"
    )
    assert segment["synced_inclusion_version"] is None, (
        "expected synced_inclusion_version null at creation, got "
        f"{segment['synced_inclusion_version']}"
    )

    classification = setup_classification(
        api, page, world["suitability_version"]["id"]
    )
    assert classification["review_state"] == "PENDING_REVIEW", (
        f"expected PENDING_REVIEW at creation, got {classification['review_state']}"
    )
    assert classification["classifier_user_id"] == ANALYST_AUTHOR_USER_ID, (
        f"expected classifier_user_id {ANALYST_AUTHOR_USER_ID}, "
        f"got {classification['classifier_user_id']}"
    )
    assert classification["reviewed_by_user_id"] is None, (
        f"expected reviewed_by_user_id null, got {classification['reviewed_by_user_id']}"
    )
    assert classification["review_note"] is None, (
        f"expected review_note null, got {classification['review_note']}"
    )


def test_a_new_batch_seeds_both_status_dimensions_independently(api):
    """One measurement batch row carries two status machines, and ingestion seeds
    each of them separately: the measurement side at INGESTED, the money side at
    UNBILLED.

    PRD: "A freshly ingested batch stands at `scoring_status` `INGESTED` and `settlement_status` `UNBILLED`, with every computed figure at its default and `scored_at` null."

    Design: Corner/state_machines/every_entity_starts_in_its_declared_initial_state
    """
    world = setup_base_world(api, clock=CLOCK, accredit=False)
    batch = setup_ingested_batch(api, world, **FULL_COVERAGE_FIGURES)

    assert batch["scoring_status"] == "INGESTED", (
        f"expected scoring_status INGESTED at ingestion, got {batch['scoring_status']}"
    )
    assert batch["settlement_status"] == "UNBILLED", (
        f"expected settlement_status UNBILLED at ingestion, got {batch['settlement_status']}"
    )
    assert batch["scored_at"] is None, (
        f"expected scored_at null at ingestion, got {batch['scored_at']}"
    )
    assert batch["version"] == 1, (
        f"expected version 1 at ingestion, got {batch['version']}"
    )


def test_a_proposed_finding_starts_inert_and_contributes_nothing(api):
    """A detector finding opens at PROPOSED with a derived GIVT family, and while it
    sits there the batch's invalid-traffic figures stay at zero.

    PRD: "A new finding stands at `status` `PROPOSED` with `retract_reason` null, and a proposed finding contributes nothing at all to the batch's figures."

    Design: Corner/state_machines/every_entity_starts_in_its_declared_initial_state
    """
    world = setup_base_world(api, clock=CLOCK, accredit=False)
    batch = setup_ingested_batch(api, world, **FULL_COVERAGE_FIGURES)
    finding = setup_proposed_finding(
        api,
        batch["id"],
        ivt_class="DATACENTER",
        flagged_impressions=400,
        confidence=0.90,
        detector_note="ASN block match",
    )

    assert finding["status"] == "PROPOSED", (
        f"expected PROPOSED at creation, got {finding['status']}"
    )
    assert finding["ivt_family"] == "GIVT", (
        f"expected ivt_family GIVT derived from DATACENTER, got {finding['ivt_family']}"
    )
    assert finding["retract_reason"] is None, (
        f"expected retract_reason null at creation, got {finding['retract_reason']}"
    )

    after = read_batch(api, batch["id"])
    assert after["ivt_impressions"] == 0, (
        f"expected ivt_impressions 0 while the finding is only PROPOSED, "
        f"got {after['ivt_impressions']}"
    )
    assert after["ivt_rate"] == pytest.approx(0.0, abs=0.0001), (
        f"expected ivt_rate 0.0 while the finding is only PROPOSED, got {after['ivt_rate']}"
    )
    assert after["sophistication_flag"] is False, (
        f"expected sophistication_flag false, got {after['sophistication_flag']}"
    )


def test_terminal_closed_no_credit_batch_blocks_a_second_claim(api):
    """A rejected claim closes its cited batch for settlement for good: the same
    batch may not be re-filed even though its measurement side still says
    QUARANTINED.

    PRD: "Every cited batch moves `settlement_status` `CLAIMED → CLOSED_NO_CREDIT`, which is terminal for the money dimension — such a batch can never be cited by another claim — the campaign's `open_claim_count` decrements by 1, both credit ledgers are left completely untouched, `decided_by_user_id` is stamped, and the claim's `version` increments by 1."

    Design: Corner/state_machines/terminal_closed_no_credit_batch_blocks_a_second_claim
    """
    world = setup_base_world(api, clock=CLOCK, publisher_overrides=SOURCED_PUBLISHER)
    batch = setup_quarantined_batch(api, world, **SHORT_COVERAGE_FIGURES)
    assert batch["scoring_status"] == "QUARANTINED", (
        f"expected QUARANTINED on a 0.6000 coverage_rate, got {batch['scoring_status']}"
    )
    assert batch["coverage_rate"] == pytest.approx(0.6000, abs=0.0001), (
        f"expected coverage_rate 0.6000, got {batch['coverage_rate']}"
    )

    officer = make_officer_headers(OFFICER_USER_ID)
    first_claim = setup_submitted_claim(api, world, batch_ids=[batch["id"]])
    validate_success(api.review_refund_claim(first_claim["id"], officer), 200)
    rejected = validate_success(
        api.reject_refund_claim(
            first_claim["id"],
            factories.reject_claim_payload(
                "EVIDENCE_INSUFFICIENT",
                decision_note="Screenshots do not cover the disputed window",
            ),
            officer,
        ),
        200,
    )
    assert rejected["claim_state"] == "REJECTED", (
        f"expected REJECTED, got {rejected['claim_state']}"
    )
    assert rejected["reject_reason_code"] == "EVIDENCE_INSUFFICIENT", (
        f"expected EVIDENCE_INSUFFICIENT, got {rejected['reject_reason_code']}"
    )
    assert rejected["claimed_impressions"] == 10000, (
        f"expected claimed_impressions 10000, got {rejected['claimed_impressions']}"
    )
    assert rejected["provisional_credit_cents"] == 8750, (
        f"expected provisional_credit_cents 8750, got {rejected['provisional_credit_cents']}"
    )

    closed = read_batch(api, batch["id"])
    assert closed["settlement_status"] == "CLOSED_NO_CREDIT", (
        f"expected CLOSED_NO_CREDIT after the rejection, got {closed['settlement_status']}"
    )
    assert closed["scoring_status"] == "QUARANTINED", (
        "expected the measurement dimension untouched at QUARANTINED, got "
        f"{closed['scoring_status']}"
    )
    campaign = read_campaign(api, world["campaign"]["id"])
    assert campaign["open_claim_count"] == 0, (
        f"expected open_claim_count 0 after the rejection, got {campaign['open_claim_count']}"
    )
    assert read_publisher(api, world["publisher"]["id"])["credit_issued_cents_total"] == 0, (
        "expected credit_issued_cents_total 0: a rejection touches no ledger"
    )
    assert read_advertiser(api, world["advertiser"]["id"])["credit_received_cents_total"] == 0, (
        "expected credit_received_cents_total 0: a rejection touches no ledger"
    )

    refiled = api.create_refund_claim(
        factories.create_refund_claim_payload(
            campaign["id"],
            world["publisher"]["id"],
            [batch["id"]],
            campaign["version"],
        ),
        world["advertiser_headers"],
    )
    validate_error(refiled, ApiErrorId.ERR_BATCH_ALREADY_CLAIMED.value, 409)

    _, meta = validate_paginated(
        api.list_refund_claims(
            world["advertiser_headers"], params={"campaign_id": campaign["id"]}
        )
    )
    assert meta["total_count"] == 1, (
        f"expected the refused re-file to create nothing, got total_count {meta['total_count']}"
    )
    after = read_batch(api, batch["id"])
    assert after["settlement_status"] == "CLOSED_NO_CREDIT", (
        f"expected CLOSED_NO_CREDIT unchanged, got {after['settlement_status']}"
    )
    assert read_campaign(api, campaign["id"])["open_claim_count"] == 0, (
        "expected open_claim_count still 0 after the refused re-file"
    )


def test_delisted_publisher_is_locked_against_every_further_status_change(api):
    """DELISTED is terminal for a publisher: reinstatement, a repeat delisting and a
    restriction are all refused with the dedicated delisted error.

    PRD: "`DELISTED` is terminal: any further standing change against a delisted publisher answers `ERR_PUBLISHER_DELISTED`, and a `new_status` that is not reachable from the publisher's current `publisher_status` — asking for `ACTIVE` on a publisher that is already `ACTIVE`, for instance — answers `ERR_INVALID_PUBLISHER_STATE`."

    Design: Corner/state_machines/delisted_publisher_is_locked_against_every_further_status_change
    """
    advance_clock(api, CLOCK)
    admin = make_admin_headers()
    publisher = setup_publisher(api, **SOURCED_PUBLISHER)
    delisted = validate_success(
        api.change_publisher_status(
            publisher["id"],
            factories.change_publisher_status_payload(
                "DELISTED", reason="Repeated policy breach"
            ),
            admin,
        ),
        200,
    )
    assert delisted["publisher_status"] == "DELISTED", (
        f"expected DELISTED, got {delisted['publisher_status']}"
    )
    assert delisted["status_reason"] == "ADMIN_ACTION", (
        f"expected status_reason ADMIN_ACTION, got {delisted['status_reason']}"
    )
    assert delisted["version"] == 2, (
        f"expected version 2 after one standing change, got {delisted['version']}"
    )

    for requested in ("ACTIVE", "DELISTED", "RESTRICTED"):
        refused = api.change_publisher_status(
            publisher["id"],
            factories.change_publisher_status_payload(requested),
            admin,
        )
        validate_error(refused, ApiErrorId.ERR_PUBLISHER_DELISTED.value, 409)
        after = read_publisher(api, publisher["id"])
        assert after["publisher_status"] == "DELISTED", (
            f"expected DELISTED unchanged after asking for {requested}, "
            f"got {after['publisher_status']}"
        )
        assert after["version"] == 2, (
            f"expected version still 2 after the refused {requested} request, "
            f"got {after['version']}"
        )
        assert after["status_reason"] == "ADMIN_ACTION", (
            f"expected status_reason still ADMIN_ACTION after the refused {requested} "
            f"request, got {after['status_reason']}"
        )


def test_appeal_overturn_cascade_vacates_the_classification_and_auto_rejects_the_claim(api):
    """One overturn decision vacates the disputed verdict, reclassifies the page,
    clears the batch's breach and rejects the live claim that depended on it.

    PRD: "In the fourth hop, a claim whose recomputed `claimed_impressions` falls to 0 is rejected outright by the platform: it moves `SUBMITTED → REJECTED` or `UNDER_REVIEW → REJECTED` with `reject_reason_code` set to `APPEAL_OVERTURNED`, every batch it cited moves `CLAIMED → CLOSED_NO_CREDIT`, and the campaign's `open_claim_count` decrements by 1."

    Design: Corner/state_machines/appeal_overturn_cascade_vacates_the_classification_and_auto_rejects_the_claim
    """
    fixture = _appealed_world(api, "CATEGORY_MISREAD")
    world = fixture["world"]
    classification = fixture["classification"]
    batch = fixture["batch"]
    claim = fixture["claim"]
    appeal = fixture["appeal"]

    assert classification["assigned_tier"] == "HIGH_RISK", (
        f"expected HIGH_RISK on one ARMS category, got {classification['assigned_tier']}"
    )
    assert classification["review_state"] == "CONFIRMED", (
        f"expected CONFIRMED before the appeal, got {classification['review_state']}"
    )
    assert classification["reviewed_by_user_id"] == ANALYST_REVIEWER_USER_ID, (
        f"expected reviewed_by_user_id {ANALYST_REVIEWER_USER_ID}, "
        f"got {classification['reviewed_by_user_id']}"
    )
    page_before = read_page(api, world["page"]["id"])
    assert page_before["classification_state"] == "APPEALED", (
        f"expected APPEALED while the appeal is live, got {page_before['classification_state']}"
    )
    assert page_before["appeal_count"] == 1, (
        f"expected appeal_count 1, got {page_before['appeal_count']}"
    )
    batch_before = read_batch(api, batch["id"])
    assert batch_before["scoring_status"] == "QUARANTINED", (
        f"expected QUARANTINED on the breach, got {batch_before['scoring_status']}"
    )
    assert batch_before["assessed_tier"] == "HIGH_RISK", (
        f"expected assessed_tier HIGH_RISK, got {batch_before['assessed_tier']}"
    )
    assert batch_before["suitability_breach_flag"] is True, (
        "expected suitability_breach_flag true against a MEDIUM_RISK floor, got "
        f"{batch_before['suitability_breach_flag']}"
    )
    assert batch_before["settlement_status"] == "CLAIMED", (
        f"expected CLAIMED once cited, got {batch_before['settlement_status']}"
    )
    assert claim["claim_state"] == "SUBMITTED", (
        f"expected SUBMITTED at intake, got {claim['claim_state']}"
    )
    assert claim["claimed_impressions"] == 10000, (
        f"expected claimed_impressions 10000 on the gross basis, got "
        f"{claim['claimed_impressions']}"
    )
    assert claim["provisional_credit_cents"] == 8750, (
        f"expected provisional_credit_cents 8750, got {claim['provisional_credit_cents']}"
    )
    assert read_campaign(api, world["campaign"]["id"])["open_claim_count"] == 1, (
        "expected open_claim_count 1 while the claim is live"
    )

    decided = validate_success(
        api.decide_appeal(
            appeal["id"],
            factories.decide_appeal_payload(
                outcome="OVERTURNED",
                revised_tier="SAFE",
                decision_note="Editorial context accepted",
            ),
            make_officer_headers(OFFICER_USER_ID),
        ),
        200,
    )
    assert decided["appeal_state"] == "OVERTURNED", (
        f"expected OVERTURNED, got {decided['appeal_state']}"
    )
    assert decided["revised_tier"] == "SAFE", (
        f"expected revised_tier SAFE, got {decided['revised_tier']}"
    )
    assert decided["decided_by_user_id"] == OFFICER_USER_ID, (
        f"expected decided_by_user_id {OFFICER_USER_ID}, got {decided['decided_by_user_id']}"
    )
    remedy_id = decided["remedy_classification_id"]
    assert remedy_id is not None, "expected a minted remedy record on the overturn"

    vacated = read_classification(api, classification["id"])
    assert vacated["review_state"] == "VACATED", (
        f"expected VACATED on the disputed record, got {vacated['review_state']}"
    )
    remedy = read_classification(api, remedy_id)
    assert remedy["classifier_kind"] == "APPEAL_REMEDY", (
        f"expected classifier_kind APPEAL_REMEDY, got {remedy['classifier_kind']}"
    )
    assert remedy["assigned_tier"] == "SAFE", (
        f"expected the remedy record at the awarded SAFE tier, got {remedy['assigned_tier']}"
    )
    assert remedy["review_state"] == "CONFIRMED", (
        f"expected the remedy record CONFIRMED, got {remedy['review_state']}"
    )

    page_after = read_page(api, world["page"]["id"])
    assert page_after["classification_state"] == "RECLASSIFIED", (
        f"expected RECLASSIFIED, got {page_after['classification_state']}"
    )
    assert page_after["current_classification_id"] == remedy_id, (
        f"expected current_classification_id {remedy_id}, "
        f"got {page_after['current_classification_id']}"
    )
    assert page_after["current_tier"] == "SAFE", (
        f"expected current_tier SAFE, got {page_after['current_tier']}"
    )

    batch_after = read_batch(api, batch["id"])
    assert batch_after["assessed_tier"] == "SAFE", (
        f"expected assessed_tier recomputed to SAFE, got {batch_after['assessed_tier']}"
    )
    assert batch_after["suitability_breach_flag"] is False, (
        f"expected suitability_breach_flag cleared, got {batch_after['suitability_breach_flag']}"
    )
    assert batch_after["scoring_status"] == "QUARANTINED", (
        "expected the coverage verdict untouched at QUARANTINED, got "
        f"{batch_after['scoring_status']}"
    )
    assert batch_after["settlement_status"] == "CLOSED_NO_CREDIT", (
        f"expected CLOSED_NO_CREDIT, got {batch_after['settlement_status']}"
    )

    claim_after = read_claim(api, claim["id"])
    assert claim_after["claim_state"] == "REJECTED", (
        f"expected REJECTED by the cascade, got {claim_after['claim_state']}"
    )
    assert claim_after["reject_reason_code"] == "APPEAL_OVERTURNED", (
        f"expected reject_reason_code APPEAL_OVERTURNED, got {claim_after['reject_reason_code']}"
    )
    assert claim_after["claimed_impressions"] == 0, (
        f"expected claimed_impressions 0, got {claim_after['claimed_impressions']}"
    )
    assert claim_after["provisional_credit_cents"] == 0, (
        f"expected provisional_credit_cents 0, got {claim_after['provisional_credit_cents']}"
    )
    assert claim_after["credited_impressions"] is None, (
        f"expected credited_impressions null on an unapproved claim, "
        f"got {claim_after['credited_impressions']}"
    )
    assert claim_after["net_credit_cents"] is None, (
        f"expected net_credit_cents null on an unapproved claim, "
        f"got {claim_after['net_credit_cents']}"
    )
    assert read_campaign(api, world["campaign"]["id"])["open_claim_count"] == 0, (
        "expected open_claim_count 0 after the cascade rejected the claim"
    )

    publisher = read_publisher(api, world["publisher"]["id"])
    assert publisher["decided_appeal_count"] == 1, (
        f"expected decided_appeal_count 1, got {publisher['decided_appeal_count']}"
    )
    assert publisher["overturned_appeal_count"] == 1, (
        f"expected overturned_appeal_count 1, got {publisher['overturned_appeal_count']}"
    )
    assert publisher["credit_issued_cents_total"] == 0, (
        f"expected credit_issued_cents_total 0, got {publisher['credit_issued_cents_total']}"
    )
    advertiser = read_advertiser(api, world["advertiser"]["id"])
    assert advertiser["credit_received_cents_total"] == 0, (
        f"expected credit_received_cents_total 0, got "
        f"{advertiser['credit_received_cents_total']}"
    )
    assert advertiser["settled_claim_count"] == 0, (
        f"expected settled_claim_count 0, got {advertiser['settled_claim_count']}"
    )


def test_upheld_appeal_returns_the_page_to_human_confirmed_without_any_tier_change(api):
    """An upheld appeal closes against the publisher and leaves the page, the
    disputed record, the batch and the live claim exactly as they stood.

    PRD: "The appeal moves `FILED → UPHELD`, `decided_by_user_id` and `decision_note` are stamped, the page moves `APPEALED → HUMAN_CONFIRMED` with `current_classification_id`, `current_tier` and `latest_category_codes` all left exactly as they were, the publisher's `decided_appeal_count` increments by 1, and both the appeal's `version` and the page's `version` increment by 1."

    Design: Corner/state_machines/upheld_appeal_returns_the_page_to_human_confirmed_without_any_tier_change
    """
    fixture = _appealed_world(api, "CONTEXT_IGNORED")
    world = fixture["world"]
    classification = fixture["classification"]
    batch = fixture["batch"]
    claim = fixture["claim"]
    appeal = fixture["appeal"]
    classification_version_before = read_classification(api, classification["id"])["version"]

    decided = validate_success(
        api.decide_appeal(
            appeal["id"],
            factories.decide_appeal_payload(
                outcome="UPHELD", decision_note="Original categorisation stands"
            ),
            make_officer_headers(OFFICER_USER_ID),
        ),
        200,
    )
    assert decided["appeal_state"] == "UPHELD", (
        f"expected UPHELD, got {decided['appeal_state']}"
    )
    assert decided["decided_by_user_id"] == OFFICER_USER_ID, (
        f"expected decided_by_user_id {OFFICER_USER_ID}, got {decided['decided_by_user_id']}"
    )
    assert decided["revised_tier"] is None, (
        f"expected revised_tier null on an uphold, got {decided['revised_tier']}"
    )
    assert decided["remedy_classification_id"] is None, (
        f"expected no remedy record on an uphold, got {decided['remedy_classification_id']}"
    )
    assert decided["round_no"] == 1, (
        f"expected round_no 1, got {decided['round_no']}"
    )

    page_after = read_page(api, world["page"]["id"])
    assert page_after["classification_state"] == "HUMAN_CONFIRMED", (
        f"expected HUMAN_CONFIRMED, got {page_after['classification_state']}"
    )
    assert page_after["current_classification_id"] == classification["id"], (
        f"expected current_classification_id {classification['id']}, "
        f"got {page_after['current_classification_id']}"
    )
    assert page_after["current_tier"] == "HIGH_RISK", (
        f"expected current_tier still HIGH_RISK, got {page_after['current_tier']}"
    )
    assert page_after["latest_category_codes"] == ["ARMS"], (
        f"expected latest_category_codes ['ARMS'], got {page_after['latest_category_codes']}"
    )
    assert page_after["appeal_count"] == 1, (
        f"expected appeal_count 1, got {page_after['appeal_count']}"
    )

    disputed_after = read_classification(api, classification["id"])
    assert disputed_after["review_state"] == "CONFIRMED", (
        f"expected the disputed record still CONFIRMED, got {disputed_after['review_state']}"
    )
    assert disputed_after["version"] == classification_version_before, (
        f"expected the disputed record's version unchanged at "
        f"{classification_version_before}, got {disputed_after['version']}"
    )

    _, meta = validate_paginated(
        api.list_page_classifications(
            make_admin_headers(), params={"page_id": world["page"]["id"]}
        )
    )
    assert meta["total_count"] == 1, (
        f"expected no APPEAL_REMEDY record minted, got total_count {meta['total_count']}"
    )

    batch_after = read_batch(api, batch["id"])
    assert batch_after["assessed_tier"] == "HIGH_RISK", (
        f"expected assessed_tier still HIGH_RISK, got {batch_after['assessed_tier']}"
    )
    assert batch_after["suitability_breach_flag"] is True, (
        f"expected suitability_breach_flag still true, got {batch_after['suitability_breach_flag']}"
    )
    assert batch_after["settlement_status"] == "CLAIMED", (
        f"expected settlement_status still CLAIMED, got {batch_after['settlement_status']}"
    )

    claim_after = read_claim(api, claim["id"])
    assert claim_after["claim_state"] == "SUBMITTED", (
        f"expected the claim still SUBMITTED, got {claim_after['claim_state']}"
    )
    assert claim_after["claimed_impressions"] == 10000, (
        f"expected claimed_impressions still 10000, got {claim_after['claimed_impressions']}"
    )
    assert claim_after["provisional_credit_cents"] == 8750, (
        f"expected provisional_credit_cents still 8750, got "
        f"{claim_after['provisional_credit_cents']}"
    )
    assert read_campaign(api, world["campaign"]["id"])["open_claim_count"] == 1, (
        "expected open_claim_count still 1 after the uphold"
    )

    publisher = read_publisher(api, world["publisher"]["id"])
    assert publisher["decided_appeal_count"] == 1, (
        f"expected decided_appeal_count 1, got {publisher['decided_appeal_count']}"
    )
    assert publisher["overturned_appeal_count"] == 0, (
        f"expected overturned_appeal_count 0 on an uphold, got "
        f"{publisher['overturned_appeal_count']}"
    )
