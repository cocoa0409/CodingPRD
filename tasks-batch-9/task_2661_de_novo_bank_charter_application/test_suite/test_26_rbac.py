"""
Who may act: the exclusive money role, the endpoint shared by two roles, the
segregation-of-duties comparison on identity, and the entity-backed peer roles.
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    CHARTERING_EXAMINER_HEADERS,
    COUNSEL_HEADERS,
    ESCROW_AGENT_HEADERS,
    fixtures as fx,
    make_independent_director_headers,
    make_lead_organizer_headers,
)
from test_helpers.assertions import assert_fields_equal
from test_helpers.factories import (
    evidence_payload,
    funding_payload,
    policy_document_payload,
)
from test_helpers.types import (
    CATEGORY_MANAGEMENT,
    CATEGORY_POLICY,
    CLEARANCE_UNSCREENED,
    CONDITION_EVIDENCE_SUBMITTED,
    DOMAIN_LENDING,
    DOMAIN_RISK_MANAGEMENT,
    FUNDING_EVENT_FUND,
    FUNDING_FUNDED,
    FUNDING_PLEDGED,
    POLICY_BOARD_ADOPTED,
    POLICY_DRAFT,
    RAISE_OPEN,
)


def _open_raise_with_one_pledge(api):
    """An open offering carrying a single unfunded, unscreened pledge of 1,000,000 shares."""
    world = fx.bare_open_raise(api)
    world["s1"] = fx.add_subscription(
        api, world["raise_id"], "Harbor Trust LP", 1_000_000
    )
    return world


# ---------------------------------------------------------------------------
# Corner / rbac
# ---------------------------------------------------------------------------
def test_the_escrow_agent_alone_moves_the_money_in(api):
    """
    Funding is the escrow agent's own right, and exercising it works end to end: the pledge
    becomes funded and a billion cents lands in the funded balance. Escrow itself stays empty,
    because money that has not been screened does not count — the row is still unscreened and
    still counts toward nothing.

    PRD: "`EscrowAgent` is the independent escrow agent and is the only role that may record subscriptions, move subscription money, record investor-screening outcomes, or lock and release escrow."
    PRD: "`FUND` moves `funding_state` from `PLEDGED` to `FUNDED` and requires the parent raise to be `OPEN` (`ERR_RAISE_NOT_OPEN`); a subscription that is not `PLEDGED` is refused with `ERR_FUNDING_TRANSITION_NOT_ALLOWED`."
    PRD: "The two dimensions advance in either order and impose no ordering on each other; `counts_toward_escrow` is true for exactly those rows where `funding_state` is `FUNDED` **and** `clearance_state` is `CLEARED`."
    PRD: "Alongside them, `funded_gross_cents` is the sum of `amount_cents` over rows whose `funding_state` is `FUNDED` regardless of screening, and `refunded_gross_cents` is the sum over rows whose `funding_state` is `REFUNDED`; refunded rows feed neither of the two bases."

    Design: Corner/rbac/rbac_escrow_agent_may_post_a_funding_event
    """
    world = _open_raise_with_one_pledge(api)

    funded = validate_success(
        api.record_funding_event(
            world["s1"], funding_payload(FUNDING_EVENT_FUND), ESCROW_AGENT_HEADERS
        ),
        expected_status=200,
    )
    assert_fields_equal(
        funded,
        funding_state=FUNDING_FUNDED,
        clearance_state=CLEARANCE_UNSCREENED,
        counts_toward_escrow=False,
    )
    assert_fields_equal(
        fx.read_raise(api, world["raise_id"]),
        status=RAISE_OPEN,
        funded_gross_cents=1_000_000_000,
        pledged_gross_cents=1_000_000_000,
        cleared_escrow_cents=0,
    )


def test_neither_counsel_nor_an_examiner_may_move_the_money(api):
    """
    The mirror image of the escrow agent's right. Counsel structured this very offering and an
    examiner will decide the application it funds, yet neither may record a payment: both are
    refused on the role and the pledge stays a pledge, with nothing funded. What counsel could
    not do to the money it had already done to the paperwork — the pledge itself is intact.

    PRD: "If the role is declared but is not among the roles authorized for the endpoint being called, the rejection is `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."
    PRD: "`EscrowAgent` is the independent escrow agent and is the only role that may record subscriptions, move subscription money, record investor-screening outcomes, or lock and release escrow."

    Design: Corner/rbac/rbac_charter_counsel_cannot_post_a_funding_event
    """
    world = _open_raise_with_one_pledge(api)

    for headers in (COUNSEL_HEADERS, CHARTERING_EXAMINER_HEADERS):
        validate_error(
            api.record_funding_event(
                world["s1"], funding_payload(FUNDING_EVENT_FUND), headers
            ),
            "ERR_ROLE_NOT_PERMITTED",
            expected_status=403,
        )

    assert_fields_equal(
        fx.read_subscription(api, world["s1"]),
        funding_state=FUNDING_PLEDGED,
        counts_toward_escrow=False,
    )
    assert_fields_equal(
        fx.read_raise(api, world["raise_id"]),
        funded_gross_cents=0,
        pledged_gross_cents=1_000_000_000,
    )


def test_counsel_and_the_lead_organizer_file_remediation_evidence_alike(
    api, conditionally_approved_group
):
    """
    Two conditions, two different callers, one identical effect: counsel files the management
    package and the lead organizer files the policy package, and both conditions move sideways
    into the submitted state carrying the reference they were given. Filing evidence is not an
    adjudication, so neither condition's audit counter moves. A third role that is on neither
    of the endpoint's two lines is refused. The filing's posture reflects it exactly: two
    conditions, neither blocking, and nothing settled, because a submitted condition is still
    unsettled.

    PRD: "Remediation evidence is submitted by `CharterCounsel` or by a `LeadOrganizer` and carries a single `evidence_reference` string, which must be at least 20 characters long — a bare ticket number is not an audit trail."
    PRD: "On success `status` becomes `EVIDENCE_SUBMITTED` and `evidence_reference` is overwritten with the supplied value, so it always reflects the most recent submission."
    PRD: "Note that `EVIDENCE_SUBMITTED` is itself a blocking status: submitting evidence does not reduce `open_blocking_condition_count`, it merely moves the condition sideways within the blocking set."

    Design: Corner/rbac/rbac_evidence_submission_is_shared_by_counsel_and_lead_organizer
    """
    world = conditionally_approved_group
    c1 = fx.add_condition(api, world["f_ca"], "MGMT-01", CATEGORY_MANAGEMENT, False)
    c2 = fx.add_condition(api, world["f_ca"], "POL-01", CATEGORY_POLICY, False)

    first = validate_success(
        api.submit_condition_evidence(
            c1, evidence_payload("DOC-MGMT-BIO-PACKET-SIGNED-001"), COUNSEL_HEADERS
        ),
        expected_status=200,
    )
    assert_fields_equal(
        first,
        status=CONDITION_EVIDENCE_SUBMITTED,
        evidence_reference="DOC-MGMT-BIO-PACKET-SIGNED-001",
        adjudication_count=0,
    )

    second = validate_success(
        api.submit_condition_evidence(
            c2,
            evidence_payload("DOC-POL-ADOPTION-MINUTES-001"),
            make_lead_organizer_headers(world["o1"]),
        ),
        expected_status=200,
    )
    assert_fields_equal(
        second,
        status=CONDITION_EVIDENCE_SUBMITTED,
        evidence_reference="DOC-POL-ADOPTION-MINUTES-001",
        adjudication_count=0,
    )

    validate_error(
        api.submit_condition_evidence(
            c1, evidence_payload("DOC-MGMT-BIO-PACKET-SIGNED-002"), ESCROW_AGENT_HEADERS
        ),
        "ERR_ROLE_NOT_PERMITTED",
        expected_status=403,
    )
    assert_fields_equal(
        fx.read_condition(api, c1),
        evidence_reference="DOC-MGMT-BIO-PACKET-SIGNED-001",
    )
    assert_fields_equal(
        fx.read_filing(api, world["f_ca"]),
        condition_total_count=2,
        open_blocking_condition_count=0,
        settled_condition_count=0,
    )


def test_the_organizer_who_drafted_a_policy_may_not_adopt_it_himself(
    api, composition_met_group
):
    """
    The drafter is a lead organizer of this very group, so he is neither the wrong role nor a
    stranger — he is simply the wrong person for the second signature, and the refusal says so.
    The draft is left unadopted with no adopter recorded. An independent director adopts it
    instead, stamping the adoption with the logical clock and his own identity, while the
    drafter's name stays exactly where it was.

    PRD: "The acting principal may not be the drafter: `X-User-ID` must differ from the policy's `drafted_by_organizer_id`, and a self-adoption is refused with `ERR_SEGREGATION_OF_DUTIES_VIOLATION` regardless of which of the two adopting roles is used."
    PRD: "On success `status` becomes `BOARD_ADOPTED`, `adopted_by_organizer_id` is set from `X-User-ID`, `adopted_at` is set to the current logical clock, and the policy's `version` increments by one."

    Design: Corner/rbac/rbac_policy_drafter_cannot_adopt_the_same_policy
    """
    world = composition_met_group
    policy_id = fx.draft_policy(
        api, world, DOMAIN_LENDING, "Lending and Credit Administration Policy"
    )

    error = validate_error(
        api.adopt_policy_document(policy_id, make_lead_organizer_headers(world["o1"])),
        "ERR_SEGREGATION_OF_DUTIES_VIOLATION",
        expected_status=409,
    )
    assert error["error_id"] not in (
        "ERR_ROLE_NOT_PERMITTED",
        "ERR_ORGANIZER_IDENTITY_MISMATCH",
    ), "the drafter is a lead organizer of the policy's own group"
    assert_fields_equal(
        fx.read_policy(api, policy_id),
        status=POLICY_DRAFT,
        adopted_by_organizer_id=None,
        adopted_at=None,
    )

    adopted = validate_success(
        api.adopt_policy_document(
            policy_id, make_independent_director_headers(world["o3"])
        ),
        expected_status=200,
    )
    assert_fields_equal(
        adopted,
        status=POLICY_BOARD_ADOPTED,
        adopted_by_organizer_id=world["o3"],
        drafted_by_organizer_id=world["o1"],
    )
    assert adopted["adopted_at"].startswith("2026-08-01T00:00:00"), (
        f"adoption must be stamped from the logical clock: {adopted['adopted_at']!r}"
    )


def test_both_entity_backed_roles_may_draft_but_only_from_inside_the_group(api):
    """
    A lead organizer who belongs to another charter project is a real organizer with a real
    identifier, so this is neither an unknown row nor a forbidden role: it is the wrong group,
    and the identity check says so before the body is even considered. Nothing is written. The
    two entity-backed roles are otherwise peers on this endpoint — an independent director of
    the group drafts the lending policy and a lead organizer of the group drafts the risk
    policy, both naming the same drafter — so the group ends with two policies from two
    different callers.

    PRD: "A mismatch is `ERR_ORGANIZER_IDENTITY_MISMATCH` (HTTP 403), and this check runs immediately after the endpoint role check and before request-body schema validation."
    PRD: "Concretely, for either of these two roles the supplied `X-User-ID` must be the `id` of an existing `Organizer` row whose `group_id` is the group in scope for the request — the group named in the path, or the group of the parent entity named in the path, or the `group_id` carried in the request body."
    PRD: "A policy is drafted by a `LeadOrganizer` or an `IndependentDirector` and carries `group_id`, `domain`, `drafted_by_organizer_id` naming the organizer who authored it, and `document_title`, 1 to 160 non-blank characters."

    Design: Corner/rbac/rbac_peer_entity_roles_must_belong_to_the_group_in_scope
    """
    world = fx.composition_met_group(api)
    other = fx.second_group(api)
    lending = policy_document_payload(
        world["group_id"],
        world["o1"],
        domain=DOMAIN_LENDING,
        document_title="Lending and Credit Administration Policy",
    )

    error = validate_error(
        api.create_policy_document(
            lending, make_lead_organizer_headers(other["ob1"])
        ),
        "ERR_ORGANIZER_IDENTITY_MISMATCH",
        expected_status=403,
    )
    assert error["error_id"] not in (
        "ERR_ROLE_NOT_PERMITTED",
        "ERR_ORGANIZER_NOT_FOUND",
    ), "the foreign organizer exists and the role is on the endpoint's list"
    _, empty = validate_paginated(
        api.list_policy_documents(COUNSEL_HEADERS, params={"group_id": world["group_id"]})
    )
    assert empty["total_count"] == 0, (
        f"no policy may have been drafted, found {empty['total_count']}"
    )

    by_director = get_success_data(
        api.create_policy_document(
            lending, make_independent_director_headers(world["o4"])
        ),
        expected_status=201,
    )
    assert_fields_equal(by_director, status=POLICY_DRAFT, domain=DOMAIN_LENDING)

    by_lead = get_success_data(
        api.create_policy_document(
            policy_document_payload(
                world["group_id"],
                world["o1"],
                domain=DOMAIN_RISK_MANAGEMENT,
                document_title="Enterprise Risk Management Policy",
            ),
            make_lead_organizer_headers(world["o1"]),
        ),
        expected_status=201,
    )
    assert_fields_equal(by_lead, status=POLICY_DRAFT, domain=DOMAIN_RISK_MANAGEMENT)

    _, both = validate_paginated(
        api.list_policy_documents(COUNSEL_HEADERS, params={"group_id": world["group_id"]})
    )
    assert both["total_count"] == 2, (
        f"both peer roles must have reached the endpoint, found {both['total_count']}"
    )
