"""Who may call: authentication, role lists, ownership and segregation of duties.

The four access rungs answer in their declared order and each names a different
code: rung 1 rejects a malformed identity before any lookup, rung 2 rejects a
recognised role that is off the endpoint's list, rung 6 rejects an entity-backed
role reaching across to another organisation's or another constituent's rows,
and rung 12 rejects the very user who submitted the copy from reviewing it.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as F
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_NOT_RESOURCE_OWNER,
    ERR_ROLE_NOT_PERMITTED,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_UNAUTHENTICATED,
)
from test_helpers.assertions import (
    assert_count,
    assert_field,
    assert_page,
    assert_version_is,
)
from test_helpers.test_users import (
    USER_CAMPAIGN_DIRECTOR,
    USER_COMPLIANCE_OFFICER,
    USER_DUAL_ROLE,
    make_campaign_director_headers,
    make_compliance_officer_headers,
    make_field_organizer_headers,
    make_message_strategist_headers,
    make_partner_delegate_headers,
    make_supporter_headers,
    headers_missing_role,
    headers_missing_user_id,
    headers_unrecognised_role,
)
from test_helpers.types import (
    CAMPAIGN_DRAFT,
    CHANNEL_EMAIL,
    CHANNEL_SMS,
    CONSENT_NONE,
    LAWFUL_BASIS_VERBAL_RECORDED,
    PARTNER_ACTIVE,
    PARTNER_TIER_ANCHOR,
    PARTNER_TIER_CORE,
    REVIEW_DECISION_APPROVE,
    ROLE_CAMPAIGN_DIRECTOR,
    VARIANT_APPROVED,
    VARIANT_IN_REVIEW,
)


def test_a_broken_identity_header_is_unauthenticated_before_any_lookup(api):
    """A real campaign id leaks nothing to three differently broken identities.

    PRD: "1. **Authentication.** Both `X-User-ID` and `X-User-Role` are present and `X-User-Role` is one of the six declared roles — otherwise `ERR_UNAUTHENTICATED`. Applies to every endpoint."

    PRD: "When a single request violates several rules at once, the response always carries the `error_id` of the **lowest-numbered** rung below."

    Design: Corner/rbac/absent_or_unrecognised_role_header_is_unauthenticated_before_any_lookup
    """
    fx.park_clock(api)
    campaign = fx.create_draft_campaign(api)
    campaign_id = campaign["id"]

    validate_error(
        api.get_campaign(campaign_id,
                         headers=headers_missing_role(USER_CAMPAIGN_DIRECTOR)),
        ERR_UNAUTHENTICATED, expected_status=401)
    validate_error(
        api.get_campaign(campaign_id,
                         headers=headers_unrecognised_role("u_ghost_1")),
        ERR_UNAUTHENTICATED, expected_status=401)
    validate_error(
        api.get_campaign(campaign_id,
                         headers=headers_missing_user_id(ROLE_CAMPAIGN_DIRECTOR)),
        ERR_UNAUTHENTICATED, expected_status=401)

    after = fx.read_campaign(api, campaign_id)
    assert_field(after, "status", CAMPAIGN_DRAFT)
    assert_version_is(after, 1)


def test_compliance_cannot_author_copy_and_field_cannot_launch(api):
    """Two exclusive operations, two wrong roles, one code and no side effects.

    PRD: "2. **Role permission.** The acting role appears in the target endpoint's authorised list — otherwise `ERR_ROLE_NOT_PERMITTED`. Applies to every endpoint."

    PRD: "A `ComplianceOfficer` may not create, launch, close or override a campaign, may not create, start or complete an activation, and may not create, submit or lock a message variant."

    PRD: "A `FieldOrganizer` may not create, clear or block an activation, may not create or review a message variant, and may not perform any campaign lifecycle call."

    PRD: "Campaign creation, launch, close, posture overrides, milestone creation, milestone rescheduling and coalition-partner creation are exclusively theirs."

    Design: Corner/rbac/compliance_officer_cannot_author_copy_and_field_organizer_cannot_launch
    """
    fx.park_clock(api)
    campaign = fx.create_draft_campaign(api)
    campaign_id = campaign["id"]

    validate_error(
        api.create_variant(
            F.variant_payload(campaign_id,
                              headline="Vote yes on HB-1420",
                              body="Ask your representative to vote yes on HB-1420.",
                              channel_scope=[CHANNEL_EMAIL]),
            headers=make_compliance_officer_headers()),
        ERR_ROLE_NOT_PERMITTED, expected_status=403)
    validate_error(
        api.launch_campaign(campaign_id, headers=make_field_organizer_headers()),
        ERR_ROLE_NOT_PERMITTED, expected_status=403)

    assert_page(api.list_variants(headers=make_message_strategist_headers()),
                expected_total=0, expected_len=0)
    after = fx.read_campaign(api, campaign_id)
    assert_field(after, "status", CAMPAIGN_DRAFT)
    assert_version_is(after, 1)


def test_entity_backed_roles_cannot_act_for_another_partner_or_supporter(api):
    """Ownership answers above existence: both target rows are real and unchanged.

    PRD: "6. **Resource ownership.** For the two entity-backed roles, the acting `X-User-ID` owns the addressed resource — otherwise `ERR_NOT_RESOURCE_OWNER`. This rung guards exactly four operations: appending a consent event, creating a partner endorsement, revoking a partner endorsement, and opening a spokesperson profile."

    PRD: "When `X-User-Role` is `PartnerDelegate`, `X-User-ID` is the `id` of the acting `CoalitionPartner`; ownership checks on any resource that references a `CoalitionPartner` compare the resource's partner reference to `X-User-ID`, so a delegate may only endorse or withdraw where the `partner_id` equals `X-User-ID`, and may only revoke endorsements owned by that partner."

    PRD: "When `X-User-Role` is `Supporter`, `X-User-ID` is the `id` of the acting `Supporter`; a supporter may only append consent events and open a story profile whose `supporter_id` equals `X-User-ID`, and may only read their own consent log and their own spokesperson profiles."

    PRD: "Any entity-backed role acting outside its own rows is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

    Design: Corner/rbac/entity_backed_roles_cannot_act_for_another_partner_or_another_supporter
    """
    world = fx.create_active_campaign(api)
    campaign_id = world["campaign_id"]
    supporter_one = fx.add_supporter(api, campaign_id)
    supporter_two = fx.add_supporter(
        api, campaign_id, with_phone=True, full_name="Sup Two",
        email="s2@example.org", phone="+15550100002",
        consent_source_reference="web-form-2")
    variant = fx.create_approved_variant(api, campaign_id)
    partners = fx.add_partners(api, campaign_id,
                              [PARTNER_TIER_ANCHOR, PARTNER_TIER_CORE])
    pinned = fx.read_variant(api, variant["id"])

    validate_error(
        api.create_endorsement(
            F.endorsement_payload(partners[1]["id"], variant["id"],
                                  pinned["version"]),
            headers=make_partner_delegate_headers(partners[0]["id"])),
        ERR_NOT_RESOURCE_OWNER, expected_status=403)
    validate_error(
        api.create_consent_event(
            F.grant_payload(supporter_two["id"], CHANNEL_SMS,
                            lawful_basis=LAWFUL_BASIS_VERBAL_RECORDED,
                            source_reference="call-centre-note-9"),
            headers=make_supporter_headers(supporter_one["id"])),
        ERR_NOT_RESOURCE_OWNER, expected_status=403)

    assert_page(api.list_endorsements(headers=make_campaign_director_headers()),
                expected_total=0, expected_len=0)
    after_variant = fx.read_variant(api, variant["id"])
    assert_count(after_variant["endorsement_count"], 0)
    assert_version_is(after_variant, pinned["version"])
    after_supporter = fx.read_supporter(api, supporter_two["id"])
    assert_field(after_supporter, "sms_consent_state", CONSENT_NONE)
    assert_version_is(after_supporter, supporter_two["version"])


def test_the_submitting_user_cannot_record_the_review_decision(api):
    """Holding the compliance role is not enough when the id is the author's own.

    PRD: "The variant must be `IN_REVIEW`, and the reviewing `X-User-ID` must differ from the stored `submitted_by_user_id`, otherwise `ERR_SEGREGATION_OF_DUTIES`."

    PRD: "In both cases `reviewed_by_user_id` is set to the reviewing `X-User-ID` and the variant's `version` increments by 1."

    PRD: "Either way the server records `submitted_by_user_id` as the `X-User-ID` of the submitting request and increments the variant's `version` by 1."

    PRD: "A new draft lands in `status` `DRAFT` with `revision_round` of 1 and its `required_endorsement_quorum` computed from the current coalition."

    Design: Corner/rbac/the_submitting_user_cannot_record_the_review_decision_on_that_variant
    """
    world = fx.create_active_campaign(api)
    variant = fx.add_variant(api, world["campaign_id"])
    submitted = fx.submit_variant(api, variant["id"],
                                 author_user_id=USER_DUAL_ROLE,
                                 submission_note="ready for review")
    assert_field(submitted, "submitted_by_user_id", USER_DUAL_ROLE)
    assert_field(submitted, "status", VARIANT_IN_REVIEW)

    validate_error(
        api.review_variant(
            variant["id"],
            F.review_decision_payload(REVIEW_DECISION_APPROVE,
                                      review_note="self-review attempt"),
            headers=make_compliance_officer_headers(USER_DUAL_ROLE)),
        ERR_SEGREGATION_OF_DUTIES, expected_status=403)
    assert_field(fx.read_variant(api, variant["id"]), "status", VARIANT_IN_REVIEW)

    approved = validate_success(api.review_variant(
        variant["id"],
        F.review_decision_payload(REVIEW_DECISION_APPROVE,
                                  review_note="copy is compliant"),
        headers=make_compliance_officer_headers()))
    assert_field(approved, "reviewed_by_user_id", USER_COMPLIANCE_OFFICER)
    assert_field(approved, "status", VARIANT_APPROVED)
    assert_count(fx.read_variant(api, variant["id"])["revision_round"], 1)


def test_a_delegate_and_a_supporter_cannot_read_outside_their_own_surface(api):
    """Read denial is role-scoped, and each denial names the role code, not ownership.

    PRD: "2. **Role permission.** The acting role appears in the target endpoint's authorised list — otherwise `ERR_ROLE_NOT_PERMITTED`. Applies to every endpoint."

    PRD: "It has no exclusive operations. It may not read a campaign's outcome report, and it may not write supporters, consent events, segments, activations, action records, spokesperson profiles or meetings."

    PRD: "A `Supporter` may not list campaigns, legislators or activations, may not read the outcome report, and may not write any campaign, milestone, legislator, segment, variant, partner, activation, action-record or meeting resource."

    PRD: "6. **Resource ownership.** For the two entity-backed roles, the acting `X-User-ID` owns the addressed resource — otherwise `ERR_NOT_RESOURCE_OWNER`. This rung guards exactly four operations: appending a consent event, creating a partner endorsement, revoking a partner endorsement, and opening a spokesperson profile."

    Design: Corner/rbac/partner_delegate_and_supporter_cannot_read_outside_their_own_surface
    """
    world = fx.create_active_campaign(api)
    campaign_id = world["campaign_id"]
    supporter = fx.add_supporter(api, campaign_id)
    partner = fx.add_partner(api, campaign_id)

    validate_error(
        api.get_outcome_report(
            campaign_id, headers=make_partner_delegate_headers(partner["id"])),
        ERR_ROLE_NOT_PERMITTED, expected_status=403)
    validate_error(
        api.get_supporter(supporter["id"],
                          headers=make_supporter_headers(supporter["id"])),
        ERR_ROLE_NOT_PERMITTED, expected_status=403)

    events, _ = assert_page(
        api.list_supporter_consent_events(
            supporter["id"], headers=make_supporter_headers(supporter["id"])),
        expected_total=1, expected_len=1)
    assert_field(events[0], "channel", CHANNEL_EMAIL)

    own_partner = validate_success(api.get_partner(
        partner["id"], headers=make_partner_delegate_headers(partner["id"])))
    assert_field(own_partner, "status", PARTNER_ACTIVE)
