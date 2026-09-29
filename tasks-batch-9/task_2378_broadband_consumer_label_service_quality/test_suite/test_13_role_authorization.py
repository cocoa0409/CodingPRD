"""Role-based access control: the positive matrix, cross-role denial, the
`Subscriber`'s account scope, and the two maker-checker controls (PRD §2.1,
§2.10, §2.11, §4).
"""

from typing import Any, Callable, Dict, NamedTuple, Optional

import pytest
from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    is_iso8601_timestamp,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import ApiErrorId, api_client
from test_helpers.assertions import (
    assert_evidence_sample_total,
    assert_immutable_audit_event,
    assert_label_dimensions,
    assert_posture,
)
from test_helpers.constants import REFERENCE_NOW
from test_helpers.factories import (
    build_complaint_payload,
    build_disclosure_payload,
    build_measurement_probe_payload,
    build_plan_amendment_payload,
    build_plan_change_notice_payload,
    build_regulator_inquiry_payload,
    build_sample,
    build_service_plan_payload,
    build_test_run_payload,
    build_translation_payload,
    build_triage_payload,
    build_withdraw_complaint_payload,
    build_withdraw_label_payload,
)
from test_helpers.fixtures import (
    add_translation,
    build_reference_environment,
    create_measured_plan,
    create_subscriber_account,
    draft_label,
    file_complaint,
    read_complaint,
    read_label,
    read_service_plan,
    read_subscriber_account,
    set_clock,
)
from test_helpers.test_users import (
    COMPLAINT_ANALYST_HEADERS,
    COMPLIANCE_OFFICER_2_HEADERS,
    COMPLIANCE_OFFICER_2_USER_ID,
    COMPLIANCE_OFFICER_HEADERS,
    COMPLIANCE_OFFICER_USER_ID,
    LOCALIZATION_SPECIALIST_2_HEADERS,
    LOCALIZATION_SPECIALIST_2_USER_ID,
    LOCALIZATION_SPECIALIST_HEADERS,
    NETWORK_ENGINEER_HEADERS,
    REGULATORY_LIAISON_HEADERS,
    RETAIL_AGENT_HEADERS,
    make_subscriber_headers,
)
from test_helpers.types import (
    AccessibleFormat,
    ComplaintState,
    DisclosureChannel,
    LabelPosture,
    NoticeState,
    PricingPhase,
    PublicationState,
    RegulatorInquiryState,
    SubstantiationStatus,
    TranslationStatus,
)

# ---------------------------------------------------------------------------
# Shared literals of the reference world used by every scenario below
# ---------------------------------------------------------------------------

#: The clock every chain here reads, and therefore the instant the server writes.
CLOCK_UTC = REFERENCE_NOW
CLOCK_TIMESTAMP = "2026-09-01T00:00:00.000Z"

#: The reference plan's own figures: six samples in the evidence pool, an
#: introductory net of 3766 cents, and a post-promotional monthly total of 11681
#: cents once the base charge is amended to 8999.
REFERENCE_EVIDENCE_SAMPLE_TOTAL = 6
REFERENCE_NET_MONTHLY_INTRO_CENTS = 3766
AMENDED_MONTHLY_PRICE_CENTS = 8999
AMENDED_MONTHLY_TOTAL_POST_PROMO_CENTS = 11681

SECOND_LABEL_EFFECTIVE_FROM = "2026-10-01T00:00:00Z"
SERVICE_OBSERVED_DATE = "2026-09-02T12:00:00Z"
NOTICE_EFFECTIVE_DATE = "2026-10-05T00:00:00Z"


def _build_published_label_world() -> Dict[str, Any]:
    """The reference world plus one complaint in `INTAKE` against the published
    label, which is the world both denial families are exercised against."""
    env = build_reference_environment()
    complaint = file_complaint(
        env.account_id, env.label_id, service_observed_date=SERVICE_OBSERVED_DATE
    )
    return {"env": env, "complaint": complaint}


# ===========================================================================
# Every role exercises one of its exclusive operations
# ===========================================================================


def test_each_role_exercises_an_operation_only_it_may_call():
    """All seven roles act in sequence, each on an operation only its own role is
    listed for, and every call is accepted.

    PRD: "A `ComplianceOfficer` owns plan and label governance — plan definition
    and amendment, fee itemisation, methodology publication, attestation
    certification, label drafting, publication and withdrawal, and the voiding of
    remediation credits. A `NetworkEngineer` owns performance measurement —
    authoring methodology documents, registering probes, recording and
    invalidating measurement runs, and computing attestations."

    Design: Corner/rbac/every_role_exercises_one_of_its_exclusive_operations
    """
    env = build_reference_environment()
    second_label = draft_label(env.plan_id, effective_from=SECOND_LABEL_EFFECTIVE_FROM)
    complaint = file_complaint(
        env.account_id, env.label_id, service_observed_date=SERVICE_OBSERVED_DATE
    )

    # The clock capability is shared by every role, so a second role may reposition
    # it to the same instant without error.
    clock_data = validate_success(
        api_client.set_clock(CLOCK_UTC, NETWORK_ENGINEER_HEADERS)
    )
    assert is_iso8601_timestamp(clock_data["current_utc"]), (
        "repositioning the clock answers with an ISO-8601 current_utc, got "
        f"{clock_data['current_utc']!r}"
    )

    # NetworkEngineer only: registering a probe panel.
    probe_payload = build_measurement_probe_payload(
        market_code="US-TX-HOU", panel_size=40, max_concurrent_windows=1
    )
    probe = validate_success(
        api_client.create_measurement_probe(probe_payload, NETWORK_ENGINEER_HEADERS),
        expected_status=201,
    )
    assert probe["probe_code"] == probe_payload["probe_code"], (
        "the engineer's probe registration must return the registered probe_code"
    )

    # LocalizationSpecialist only: adding a translation to a drafted label.
    translation = validate_success(
        api_client.create_label_translation(
            second_label["id"],
            build_translation_payload(
                locale="en-US", translated_summary="October label, English"
            ),
            LOCALIZATION_SPECIALIST_HEADERS,
        ),
        expected_status=201,
    )
    assert translation["status"] == TranslationStatus.DRAFT.value

    # ComplaintAnalyst only: triaging an intaken complaint.
    triaged = validate_success(
        api_client.triage_complaint(
            complaint["id"],
            build_triage_payload(priority_note="Evening shortfall, needs measurement"),
            COMPLAINT_ANALYST_HEADERS,
        )
    )
    assert triaged["state"] == ComplaintState.TRIAGED.value

    # RegulatoryLiaison only: opening a regulator docket.
    inquiry = validate_success(
        api_client.create_regulator_inquiry(
            build_regulator_inquiry_payload(complaint["id"]),
            REGULATORY_LIAISON_HEADERS,
        ),
        expected_status=201,
    )
    assert inquiry["state"] == RegulatorInquiryState.RECEIVED.value

    # RetailAgent only: sending a plan-change notice.
    notice = validate_success(
        api_client.create_plan_change_notice(
            build_plan_change_notice_payload(
                env.account_id,
                env.plan_id,
                NOTICE_EFFECTIVE_DATE,
                reason="Consumer-requested change",
            ),
            RETAIL_AGENT_HEADERS,
        ),
        expected_status=201,
    )
    assert notice["state"] == NoticeState.SENT.value

    # Subscriber only: acknowledging the notice on their own account.
    acknowledged = validate_success(
        api_client.acknowledge_plan_change_notice(
            notice["id"], make_subscriber_headers(env.account_id)
        )
    )
    assert acknowledged["state"] == NoticeState.ACKNOWLEDGED.value
    assert acknowledged["acknowledged_at"] == CLOCK_TIMESTAMP, (
        "acknowledgement records acknowledged_at from the logical clock"
    )

    # ComplianceOfficer only, and last because amending the plan moves the posture.
    amended = validate_success(
        api_client.amend_service_plan(
            env.plan_id,
            build_plan_amendment_payload(
                change_justification="Annual repricing",
                monthly_price_cents=AMENDED_MONTHLY_PRICE_CENTS,
            ),
            COMPLIANCE_OFFICER_HEADERS,
        )
    )
    assert amended["monthly_price_cents"] == AMENDED_MONTHLY_PRICE_CENTS
    assert_posture(amended, LabelPosture.RESTRICTED.value)
    assert (
        read_label(second_label["id"])["monthly_total_post_promo_cents"]
        == AMENDED_MONTHLY_TOTAL_POST_PROMO_CENTS
    ), "the amendment recomputes the itemisation of every draft label of the plan"


# ===========================================================================
# Cross-role calls are denied with ERR_UNAUTHORIZED
# ===========================================================================


class _RoleDenial(NamedTuple):
    """One call made by a role the endpoint does not list."""

    name: str
    call: Callable[[Dict[str, Any]], Any]
    confirm_no_write: Optional[Callable[[Dict[str, Any]], None]] = None


def _engineer_creates_a_service_plan(world: Dict[str, Any]):
    payload = build_service_plan_payload(display_name="Engineer writing the catalogue")
    world["denied_plan_payload"] = payload
    return api_client.create_service_plan(payload, NETWORK_ENGINEER_HEADERS)


def _confirm_plan_code_is_still_free(world: Dict[str, Any]) -> None:
    """The refused plan_code is still free, so nothing was written: a collision
    on `plan_code` would have answered `ERR_DUPLICATE_PLAN_CODE`."""
    validate_success(
        api_client.create_service_plan(
            world["denied_plan_payload"], COMPLIANCE_OFFICER_HEADERS
        ),
        expected_status=201,
    )


def _officer_records_a_test_run(world: Dict[str, Any]):
    env = world["env"]
    payload = build_test_run_payload(
        env.probe_id,
        env.plan_id,
        env.methodology_id,
        window_start="2026-08-11T00:00:00Z",
        window_end="2026-08-12T00:00:00Z",
        samples=[build_sample("2026-08-11T19:10:00Z", 250, 120, 20)],
    )
    return api_client.create_test_run(payload, COMPLIANCE_OFFICER_HEADERS)


def _specialist_withdraws_a_published_label(world: Dict[str, Any]):
    return api_client.withdraw_label_version(
        world["env"].label_id,
        build_withdraw_label_payload(
            reason="Localization specialist withdrawing a label"
        ),
        LOCALIZATION_SPECIALIST_HEADERS,
    )


def _agent_triages_a_complaint(world: Dict[str, Any]):
    return api_client.triage_complaint(
        world["complaint"]["id"],
        build_triage_payload(priority_note="Retail agent triaging"),
        RETAIL_AGENT_HEADERS,
    )


def _analyst_opens_a_regulator_docket(world: Dict[str, Any]):
    return api_client.create_regulator_inquiry(
        build_regulator_inquiry_payload(world["complaint"]["id"]),
        COMPLAINT_ANALYST_HEADERS,
    )


def _agent_withdraws_a_complaint(world: Dict[str, Any]):
    return api_client.withdraw_complaint(
        world["complaint"]["id"],
        build_withdraw_complaint_payload(
            withdraw_reason="Agent withdrawing on the consumer's behalf"
        ),
        RETAIL_AGENT_HEADERS,
    )


def _agent_lists_regulator_dockets(world: Dict[str, Any]):
    return api_client.list_regulator_inquiries(RETAIL_AGENT_HEADERS)


_CROSS_ROLE_DENIALS = (
    _RoleDenial(
        "network_engineer_creates_a_service_plan",
        _engineer_creates_a_service_plan,
        _confirm_plan_code_is_still_free,
    ),
    _RoleDenial("compliance_officer_records_a_test_run", _officer_records_a_test_run),
    _RoleDenial(
        "localization_specialist_withdraws_a_label",
        _specialist_withdraws_a_published_label,
    ),
    _RoleDenial("retail_agent_triages_a_complaint", _agent_triages_a_complaint),
    _RoleDenial(
        "complaint_analyst_opens_a_regulator_docket", _analyst_opens_a_regulator_docket
    ),
    _RoleDenial("retail_agent_withdraws_a_complaint", _agent_withdraws_a_complaint),
    _RoleDenial("retail_agent_lists_regulator_dockets", _agent_lists_regulator_dockets),
)


@pytest.fixture
def cross_role_world() -> Dict[str, Any]:
    """The published-label world every cross-role denial is attempted against.

    Built per case: server state is in-memory only, so a world shared across
    cases could not survive between them. Every case re-checks that the world it
    built is still intact after the refusal, since none of the denied calls may
    write.
    """
    return _build_published_label_world()


def _assert_cross_role_world_is_intact(world: Dict[str, Any]) -> None:
    env = world["env"]
    assert_evidence_sample_total(
        read_service_plan(env.plan_id), REFERENCE_EVIDENCE_SAMPLE_TOTAL
    )
    assert (
        read_label(env.label_id)["publication_state"]
        == PublicationState.PUBLISHED.value
    ), "a refused withdrawal must leave the published label published"
    assert (
        read_complaint(world["complaint"]["id"])["state"] == ComplaintState.INTAKE.value
    ), "a refused triage or withdrawal must leave the complaint in INTAKE"


@pytest.mark.parametrize("denial", _CROSS_ROLE_DENIALS, ids=lambda d: d.name)
def test_a_role_outside_the_endpoints_role_list_is_refused(
    cross_role_world, denial: _RoleDenial
):
    """Each role is refused another role's operation — writes and reads alike —
    and the refusal writes nothing.

    PRD: "A request whose role is recognised but is not authorised for the
    operation being called is rejected with `ERR_UNAUTHORIZED` (403)."

    Design: Corner/rbac/cross_role_calls_are_denied_with_unauthorized
    """
    response = denial.call(cross_role_world)

    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED.value)

    _assert_cross_role_world_is_intact(cross_role_world)
    if denial.confirm_no_write is not None:
        denial.confirm_no_write(cross_role_world)


def test_unauthorized_precedes_existence_for_an_unknown_complaint():
    """An unauthorized caller naming a complaint that does not exist is refused as
    unauthorized, so the refusal never discloses whether the record exists.

    PRD: "When several rules could reject the same request, the system evaluates
    them in the fixed order below and returns the first failure it finds."

    Design: Corner/rbac/cross_role_calls_are_denied_with_unauthorized
    """
    response = api_client.triage_complaint(
        NON_EXISTENT_UUID,
        build_triage_payload(priority_note="Unauthorized caller, unknown complaint"),
        RETAIL_AGENT_HEADERS,
    )

    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED.value)


# ===========================================================================
# A Subscriber cannot reach another account's records
# ===========================================================================


def _peer_headers(world: Dict[str, Any]) -> Dict[str, str]:
    """`X-User-ID` of the second account holder: for the `Subscriber` role it is
    the acting account's own id."""
    return make_subscriber_headers(world["peer_account"]["id"])


def _peer_reads_another_account(world: Dict[str, Any]):
    return api_client.get_subscriber_account(
        world["env"].account_id, _peer_headers(world)
    )


def _peer_records_a_disclosure_on_another_account(world: Dict[str, Any]):
    return api_client.record_label_disclosure(
        world["env"].account_id, build_disclosure_payload(), _peer_headers(world)
    )


def _peer_files_a_complaint_for_another_account(world: Dict[str, Any]):
    env = world["env"]
    return api_client.create_complaint(
        build_complaint_payload(
            env.account_id,
            env.label_id,
            SERVICE_OBSERVED_DATE,
            affected_days=2,
            narrative="Complaining about a neighbour's account",
        ),
        _peer_headers(world),
    )


def _peer_withdraws_another_accounts_complaint(world: Dict[str, Any]):
    return api_client.withdraw_complaint(
        world["complaint"]["id"],
        build_withdraw_complaint_payload(
            withdraw_reason="Withdrawing someone else's complaint"
        ),
        _peer_headers(world),
    )


def _peer_lists_another_accounts_remediation_credits(world: Dict[str, Any]):
    return api_client.list_complaint_remediation_credits(
        world["complaint"]["id"], _peer_headers(world)
    )


_PEER_ACCOUNT_DENIALS = (
    ("subscriber_reads_a_peers_account", _peer_reads_another_account),
    (
        "subscriber_records_a_disclosure_on_a_peers_account",
        _peer_records_a_disclosure_on_another_account,
    ),
    (
        "subscriber_files_a_complaint_for_a_peers_account",
        _peer_files_a_complaint_for_another_account,
    ),
    (
        "subscriber_withdraws_a_peers_complaint",
        _peer_withdraws_another_accounts_complaint,
    ),
    (
        "subscriber_lists_a_peers_remediation_credits",
        _peer_lists_another_accounts_remediation_credits,
    ),
)


@pytest.fixture
def peer_account_world() -> Dict[str, Any]:
    """The reference world plus a second account on the same plan, so scope can be
    tested between two real `SubscriberAccount` ids. Built per case, because
    server state is in-memory only and cannot be shared between cases."""
    world = _build_published_label_world()
    world["peer_account"] = create_subscriber_account(
        world["env"].plan_id,
        service_start_date=CLOCK_UTC,
        discount_program_enrolled=False,
    )
    return world


@pytest.mark.parametrize(
    "case_name,call", _PEER_ACCOUNT_DENIALS, ids=[c[0] for c in _PEER_ACCOUNT_DENIALS]
)
def test_subscriber_is_refused_every_operation_on_a_peers_records(
    peer_account_world, case_name: str, call
):
    """Reads and writes alike are refused when the acting subscriber's own id is
    not the account the record belongs to, and nothing is written.

    PRD: "A `Subscriber` who targets a record belonging to a different account is
    rejected with `ERR_ACCOUNT_SCOPE_VIOLATION` (403)."

    Design: Corner/rbac/subscriber_cannot_reach_another_accounts_records
    """
    response = call(peer_account_world)

    validate_error(response, ApiErrorId.ERR_ACCOUNT_SCOPE_VIOLATION.value)

    env = peer_account_world["env"]
    assert (
        read_complaint(peer_account_world["complaint"]["id"])["state"]
        == ComplaintState.INTAKE.value
    ), "a refused withdrawal must leave the complaint in INTAKE"
    owner_account = read_subscriber_account(env.account_id)
    assert owner_account["last_disclosed_label_version_id"] is None, (
        "a refused disclosure must leave last_disclosed_label_version_id null"
    )


def test_subscriber_reaches_its_own_account_and_the_unscoped_plan_read(
    peer_account_world,
):
    """The same disclosure endpoint succeeds on the caller's own account, and a
    plan read — which is not one of the scoped operations — succeeds too.

    PRD: "This scoping applies to reading one account, listing accounts, listing
    and recording that account's disclosures, filing a complaint, reading one
    complaint, listing complaints, withdrawing a complaint, listing a complaint's
    remediation credits, reading one notice, listing notices, and acknowledging a
    notice."

    Design: Corner/rbac/subscriber_cannot_reach_another_accounts_records
    """
    env = peer_account_world["env"]
    peer_account_id = peer_account_world["peer_account"]["id"]
    headers = make_subscriber_headers(peer_account_id)

    own_account = validate_success(
        api_client.get_subscriber_account(peer_account_id, headers)
    )
    assert own_account["id"] == peer_account_id
    assert own_account["pricing_phase"] == PricingPhase.INTRO.value

    disclosure = validate_success(
        api_client.record_label_disclosure(
            peer_account_id,
            build_disclosure_payload(
                channel=DisclosureChannel.ACCOUNT_PORTAL.value,
                locale="en-US",
                accessible_format=AccessibleFormat.STANDARD_WEB.value,
            ),
            headers,
        ),
        expected_status=201,
    )
    assert_immutable_audit_event(disclosure)
    assert disclosure["account_id"] == peer_account_id
    assert disclosure["disclosed_by_user_id"] == peer_account_id

    label = read_label(env.label_id)
    assert label["net_monthly_intro_cents"] == REFERENCE_NET_MONTHLY_INTRO_CENTS
    disclosed_cents = disclosure["disclosed_net_monthly_cents"]
    assert disclosed_cents == label["net_monthly_intro_cents"], (
        "an INTRO-phase account is disclosed the label's net_monthly_intro_cents, "
        f"expected {label['net_monthly_intro_cents']}, got {disclosed_cents}"
    )

    plan = validate_success(api_client.get_service_plan(env.plan_id, headers))
    assert plan["id"] == env.plan_id, "reading a plan is not account-scoped"


# ===========================================================================
# Maker-checker: no self-publish and no self-review
# ===========================================================================


def _build_maker_checker_world() -> Dict[str, Any]:
    """A certified attestation, a `DRAFT` label drafted by the first officer and a
    `DRAFT` en-US translation authored by the first specialist."""
    set_clock(CLOCK_UTC)
    measured = create_measured_plan()
    label = draft_label(measured["plan"]["id"], effective_from=CLOCK_UTC)
    translation = add_translation(label["id"], locale="en-US")
    return {
        "plan_id": measured["plan"]["id"],
        "label": label,
        "translation": translation,
    }


def _translation_status(label_version_id: str, translation_id: str) -> str:
    rows, _meta = validate_paginated(
        api_client.list_label_translations(label_version_id, COMPLIANCE_OFFICER_HEADERS)
    )
    matches = [row for row in rows if row["id"] == translation_id]
    assert len(matches) == 1, f"expected one translation row for {translation_id}"
    return matches[0]["status"]


def test_translation_may_not_be_verified_by_its_author():
    """The specialist who authored the translation cannot verify it, while a second
    holder of the same role can.

    PRD: "A `LabelTranslation` may not be verified by the specialist who authored
    it: if the verifying `X-User-ID` equals the translation's
    `created_by_user_id`, the request is rejected with `ERR_SOD_SELF_REVIEW`
    (403)."

    Design: Corner/rbac/maker_checker_blocks_self_publish_and_self_review
    """
    world = _build_maker_checker_world()
    label_id = world["label"]["id"]
    translation_id = world["translation"]["id"]

    self_review = api_client.verify_label_translation(
        label_id, translation_id, LOCALIZATION_SPECIALIST_HEADERS
    )

    validate_error(self_review, ApiErrorId.ERR_SOD_SELF_REVIEW.value)
    assert (
        _translation_status(label_id, translation_id) == TranslationStatus.DRAFT.value
    ), "a refused self-review must leave the translation in DRAFT"

    verified = validate_success(
        api_client.verify_label_translation(
            label_id, translation_id, LOCALIZATION_SPECIALIST_2_HEADERS
        )
    )
    assert verified["status"] == TranslationStatus.VERIFIED.value
    assert verified["verified_by_user_id"] == LOCALIZATION_SPECIALIST_2_USER_ID
    assert read_label(label_id)["verified_locale_count"] == 1


def test_label_may_not_be_published_by_the_officer_who_drafted_it():
    """The drafting officer is refused before the coverage prerequisite is even
    consulted, is still refused once coverage is satisfied, and a second officer
    publishes.

    PRD: "A `LabelVersion` may not be published by the officer who drafted it: if
    the publishing `X-User-ID` equals the label's `created_by_user_id`, the request
    is rejected with `ERR_SOD_SELF_PUBLISH` (403)." And: "Both checks are
    evaluated after the target's state precondition and before the accessibility
    and referential prerequisites."

    Design: Corner/rbac/maker_checker_blocks_self_publish_and_self_review
    """
    world = _build_maker_checker_world()
    label_id = world["label"]["id"]
    translation_id = world["translation"]["id"]

    # The en-US translation is still DRAFT, so translation coverage is unsatisfied
    # too — but the maker-checker control is decided first.
    early_self_publish = api_client.publish_label_version(
        label_id, COMPLIANCE_OFFICER_HEADERS
    )
    validate_error(early_self_publish, ApiErrorId.ERR_SOD_SELF_PUBLISH.value)

    validate_success(
        api_client.verify_label_translation(
            label_id, translation_id, LOCALIZATION_SPECIALIST_2_HEADERS
        )
    )

    late_self_publish = api_client.publish_label_version(
        label_id, COMPLIANCE_OFFICER_HEADERS
    )
    validate_error(late_self_publish, ApiErrorId.ERR_SOD_SELF_PUBLISH.value)

    published = validate_success(
        api_client.publish_label_version(label_id, COMPLIANCE_OFFICER_2_HEADERS)
    )
    assert_label_dimensions(
        published,
        PublicationState.PUBLISHED.value,
        SubstantiationStatus.SUBSTANTIATED.value,
    )
    assert published["published_by_user_id"] == COMPLIANCE_OFFICER_2_USER_ID
    assert published["created_by_user_id"] == COMPLIANCE_OFFICER_USER_ID

    plan = read_service_plan(world["plan_id"])
    assert plan["active_label_version_id"] == label_id
    assert_posture(plan, LabelPosture.OPEN.value)
