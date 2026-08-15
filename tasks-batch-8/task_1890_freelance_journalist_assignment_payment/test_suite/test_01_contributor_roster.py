"""Contributor roster: creation defaults, email uniqueness, lifecycle
lockdown, the suspension offer guard, and the termination cascade."""
from test_helpers import (
    ApiErrorId,
    add_rate_agreement,
    assert_assignment,
    assert_contributor,
    bootstrap_desk,
    create_assignment,
    create_contributor,
    create_contributor_payload,
    get_assignment,
    get_contributor,
    get_success_data,
    is_iso8601_timestamp,
    is_valid_uuid,
    offer_assignment,
    setup_assignment_in_state,
    setup_contributor_with_agreement,
    validate_error,
    validate_success,
    walk_assignment,
)
from test_helpers import api_client as _api
from test_helpers.test_users import TEST_USERS

ADMIN = TEST_USERS["desk_admin_headers"]
EDITOR = TEST_USERS["editor_headers"]


def test_contributor_creation_applies_documented_defaults(api):
    """PRD section 3.1: "A new contributor starts in `ACTIVE` status." and
    "an optional `pen_name` byline (empty string when not supplied), a contact
    `email`, a `tax_residency` class, and an optional `backup_withholding_flag`
    (defaulting to false)."
    PRD section 2.4: "Every persisted entity carries an `id` (a server-minted
    UUID with no type prefix), a `created_at` timestamp, an `updated_at`
    timestamp, and an integer `version`."

    Design: Corner/entities/contributor_creation_defaults_and_computed
    """
    bootstrap_desk()
    resp = api.create_contributor(
        create_contributor_payload(legal_name="New Nell", email="nell@x.com",
                                   tax_residency="DOMESTIC_US"),
        ADMIN)
    data = validate_success(resp, 201)
    assert_contributor(data)
    assert data["status"] == "ACTIVE"
    assert data["ytd_gross_cents"] == 0, "no ledger postings yet"
    assert data["reportable_threshold_crossed"] is False
    assert data["backup_withholding_flag"] is False
    assert data["pen_name"] == "", "pen_name defaults to empty string"
    assert is_valid_uuid(data["id"])
    assert is_iso8601_timestamp(data["created_at"])
    assert data["version"] == 1


def test_contributor_email_unique_case_insensitively(api):
    """PRD section 3.1: "Email uniqueness is enforced case-insensitively
    across the entire roster: a duplicate submission is rejected with
    `ERR_DUPLICATE_EMAIL`."

    Design: Corner/entities/contributor_email_case_insensitive_uniqueness
    """
    bootstrap_desk()
    create_contributor(legal_name="Case One", email="case@x.com")
    resp = api.create_contributor(
        create_contributor_payload(legal_name="Case Two", email="CASE@x.com",
                                   tax_residency="FOREIGN"),
        ADMIN)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_EMAIL)


def test_terminated_contributor_rejects_further_transitions(api):
    """PRD section 3.1: "Termination — allowed from either `ACTIVE` or
    `SUSPENDED` — moves the contributor to `TERMINATED` and cascades
    downward: every rate agreement still `ACTIVE` for the contributor flips
    to `SUPERSEDED`, and every assignment still in `DRAFT` or `OFFERED` is
    killed with `kill_fee_tier` set to `PRE_DELIVERY` and its final fee
    computed by the kill-variant rule (§3.4)." (no transition out of
    TERMINATED exists).
    PRD section 3.11: "Authentication comes first (missing or malformed
    headers yield `ERR_UNAUTHENTICATED`), then role authorization
    (`ERR_FORBIDDEN_ROLE`), then path existence left-to-right
    (`ERR_NOT_FOUND`), then state-machine legality including terminal-state
    lockdown (`ERR_INVALID_STATE`)."

    Design: Corner/state_machines/contributor_terminated_lockdown
    """
    bootstrap_desk()
    contributor = create_contributor(legal_name="Term Tom", email="tom@x.com")
    terminated = get_success_data(
        api.terminate_contributor(contributor["id"], ADMIN))
    assert terminated["status"] == "TERMINATED"

    resp_suspend = api.suspend_contributor(contributor["id"], ADMIN)
    validate_error(resp_suspend, ApiErrorId.ERR_INVALID_STATE)
    resp_reinstate = api.reinstate_contributor(contributor["id"], ADMIN)
    validate_error(resp_reinstate, ApiErrorId.ERR_INVALID_STATE)
    assert get_contributor(contributor["id"])["status"] == "TERMINATED"


class TestOfferGuardedByContributorStatus:

    def test_offer_to_suspended_contributor_rejected(self, api):
        """PRD section 3.1: "while suspended, no new assignment may be offered
        to them."
        PRD section 3.3: "The precondition is threefold, evaluated in order:
        the assignment must be in `DRAFT`, the contributor must be `ACTIVE`,
        and an `ACTIVE` rate agreement must cover the current time (its
        `effective_from` at or before now and its `effective_to` either null
        or strictly after now); the last of these, when unmet, is rejected
        with `ERR_NO_ACTIVE_RATE_AGREEMENT`."

        Design: Difficulty/cross_entity_state_dependency/offer_guarded_by_contributor_status
        """
        contributor, _agr = setup_contributor_with_agreement(
            legal_name="Suspended Sam", email="sam@x.com")
        assignment = create_assignment(contributor["id"], title="SS")
        get_success_data(api.suspend_contributor(contributor["id"], ADMIN))

        resp = api.offer_assignment(assignment["id"], EDITOR)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert get_assignment(assignment["id"])["editorial_status"] == "DRAFT"

    def test_offer_after_reinstate_succeeds_control(self, api):
        """PRD section 3.1: "Reinstatement moves `SUSPENDED` back to
        `ACTIVE`."
        PRD section 3.3: "On success the agreement is version-pinned into
        `rate_agreement_id`, `agreed_fee_cents` is locked from that agreement
        (for `PER_WORD`, the commissioned word count multiplied by
        `per_word_rate_cents`; for `FLAT`, the `flat_fee_cents`), and a
        `RightsPurchase` row is created alongside the assignment with
        `rights_kind` copied from the agreement's `rights_default` and
        `status` `ACTIVE`."

        Design: Difficulty/cross_entity_state_dependency/offer_guarded_by_contributor_status
        """
        contributor, agreement = setup_contributor_with_agreement(
            legal_name="Reinstate Rae", email="rae@x.com",
            pricing_mode="FLAT", flat_fee_cents=50000)
        assignment = create_assignment(contributor["id"], title="RS")
        get_success_data(api.suspend_contributor(contributor["id"], ADMIN))
        get_success_data(api.reinstate_contributor(contributor["id"], ADMIN))

        offered = validate_success(api.offer_assignment(assignment["id"],
                                                        EDITOR))
        assert offered["editorial_status"] == "OFFERED"
        assert offered["rate_agreement_id"] == agreement["id"]
        assert offered["agreed_fee_cents"] == 50000


def test_terminate_cascades_only_to_open_assignments(api):
    """PRD section 3.1: "Termination — allowed from either `ACTIVE` or
    `SUSPENDED` — moves the contributor to `TERMINATED` and cascades downward:
    every rate agreement still `ACTIVE` for the contributor flips to
    `SUPERSEDED`, and every assignment still in `DRAFT` or `OFFERED` is killed
    with `kill_fee_tier` set to `PRE_DELIVERY` and its final fee computed by
    the kill-variant rule (§3.4)."
    PRD section 3.4: "The tier percentage is 25 when `kill_fee_tier` is
    `PRE_DELIVERY`, or the desk's `kill_fee_post_delivery_pct_num` (default
    50) when `POST_DELIVERY`."

    Design: Corner/cross_cutting_layers/cascade_terminate_kills_open_assignments
    """
    contributor, agreement = setup_contributor_with_agreement(
        legal_name="Term Tina", email="tina@x.com", pricing_mode="FLAT",
        flat_fee_cents=40000)
    asg_offered = create_assignment(contributor["id"], title="TA")
    walk_assignment(asg_offered["id"], contributor["id"], "OFFERED")
    asg_in_progress = create_assignment(contributor["id"], title="TB")
    walk_assignment(asg_in_progress["id"], contributor["id"], "IN_PROGRESS")

    terminated = validate_success(
        api.terminate_contributor(contributor["id"], ADMIN))
    assert terminated["status"] == "TERMINATED"

    agr_after = get_success_data(api.get_rate_agreement(agreement["id"],
                                                        ADMIN))
    assert agr_after["status"] == "SUPERSEDED"

    a_after = get_assignment(asg_offered["id"])
    assert a_after["editorial_status"] == "KILLED"
    assert a_after["kill_fee_tier"] == "PRE_DELIVERY"
    assert a_after["final_fee_cents"] == 10000, "25% of agreed 40000"

    b_after = get_assignment(asg_in_progress["id"])
    assert b_after["editorial_status"] == "IN_PROGRESS", (
        "conditional cascade kills only DRAFT/OFFERED assignments")
    assert_assignment(b_after)
