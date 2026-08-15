"""Rate agreements: mode exclusivity, validity windows, revocation guards,
the half-open coverage boundary, and OCC on contributor version."""
from test_helpers import (
    ApiErrorId,
    add_rate_agreement,
    bootstrap_desk,
    create_assignment,
    create_contributor,
    create_rate_agreement_payload,
    get_contributor,
    get_success_data,
    set_clock,
    setup_contributor_with_agreement,
    validate_error,
    validate_success,
    walk_assignment,
)
from test_helpers import api_client as _api  # noqa: F401  (parity with suite)
from test_helpers.test_users import TEST_USERS

ADMIN = TEST_USERS["desk_admin_headers"]
EDITOR = TEST_USERS["editor_headers"]


def test_per_word_agreement_rejects_flat_fee_field(api):
    """PRD section 3.2: "Field-shape violations — both rate fields set,
    neither set, a rate below 1 — yield `ERR_INVALID_REQUEST`."

    Design: Corner/entities/rate_agreement_mode_exclusivity
    """
    bootstrap_desk()
    contributor = create_contributor(legal_name="Mode Max", email="max@x.com")
    payload = create_rate_agreement_payload(
        pricing_mode="PER_WORD", per_word_rate_cents=75, kill_fee_pct_num=25,
        rights_default="FIRST", effective_from="2026-08-01T00:00:00Z",
        expected_contributor_version=contributor["version"])
    payload["flat_fee_cents"] = 50000  # both rate fields set
    resp = api.create_rate_agreement(contributor["id"], payload, ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_new_window_predating_active_agreement_rejected(api):
    """PRD section 3.2: "The window itself is validated — `effective_to` must
    be null or strictly later than `effective_from`, and the new agreement's
    `effective_from` must be at or after the prior active agreement's
    `effective_from`; a violation yields `ERR_INVALID_WINDOW`."

    Design: Corner/errors/invalid_window_on_agreement
    """
    contributor, _agr = setup_contributor_with_agreement(
        legal_name="Window Wanda", email="wanda@x.com")
    fresh = get_contributor(contributor["id"])
    payload = create_rate_agreement_payload(
        pricing_mode="FLAT", flat_fee_cents=60000, kill_fee_pct_num=25,
        rights_default="FIRST", effective_from="2026-07-01T00:00:00Z",
        expected_contributor_version=fresh["version"])
    resp = api.create_rate_agreement(contributor["id"], payload, ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_WINDOW)


def test_revoke_agreement_referenced_by_in_flight_assignment(api):
    """PRD section 3.2: "A `DeskAdmin` may revoke an `ACTIVE` agreement,
    moving it to `REVOKED`, but only when no in-flight assignment references
    it — that is, no assignment whose `editorial_status` is `OFFERED`,
    `ACCEPTED`, `IN_PROGRESS`, `SUBMITTED`, or `UNDER_VERIFICATION` pins this
    agreement."

    Design: Corner/errors/revoke_agreement_in_use_rejected
    """
    contributor, agreement = setup_contributor_with_agreement(
        legal_name="Revoke Ray", email="ray@x.com")
    assignment = create_assignment(contributor["id"], title="RS")
    walk_assignment(assignment["id"], contributor["id"],
                    "UNDER_VERIFICATION")

    resp = api.revoke_rate_agreement(agreement["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    after = get_success_data(api.get_rate_agreement(agreement["id"], ADMIN))
    assert after["status"] == "ACTIVE"


class TestRateAgreementHalfOpenWindow:
    """Adjacent agreements [from, to) never double-cover an instant."""

    def test_offer_one_second_before_boundary_pins_old_agreement(self, api):
        """PRD section 3.3: "an `ACTIVE` rate agreement must cover the current
        time (its `effective_from` at or before now and its `effective_to`
        either null or strictly after now)".
        PRD section 3.3: "On success the agreement is version-pinned into
        `rate_agreement_id`, `agreed_fee_cents` is locked from that agreement
        (for `PER_WORD`, the commissioned word count multiplied by
        `per_word_rate_cents`; for `FLAT`, the `flat_fee_cents`), and a
        `RightsPurchase` row is created alongside the assignment with
        `rights_kind` copied from the agreement's `rights_default` and
        `status` `ACTIVE`."

        Design: Difficulty/resource_temporal_overlap/rate_agreement_window_half_open
        """
        contributor, agr1 = setup_contributor_with_agreement(
            legal_name="Window Wes", email="wes@x.com",
            pricing_mode="PER_WORD", per_word_rate_cents=50,
            effective_from="2026-08-01T00:00:00Z",
            effective_to="2026-08-15T00:00:00Z")
        assignment = create_assignment(contributor["id"], title="Early",
                                       deadline_utc="2026-08-20T00:00:00Z")
        set_clock("2026-08-14T23:59:59Z")

        offered = validate_success(
            api.offer_assignment(assignment["id"], EDITOR))
        assert offered["rate_agreement_id"] == agr1["id"]
        assert offered["agreed_fee_cents"] == 5000, "100 words at 50 c/word"

    def test_offer_exactly_at_boundary_pins_new_agreement(self, api):
        """PRD section 3.3: "an `ACTIVE` rate agreement must cover the current
        time (its `effective_from` at or before now and its `effective_to`
        either null or strictly after now)".
        PRD section 3.2: "At most one agreement per contributor is `ACTIVE` at
        any time. Creating a new agreement while one is already active
        supersedes the prior record: its `status` flips to `SUPERSEDED` and
        its `version` bumps, while the new row is born `ACTIVE`."

        Design: Difficulty/resource_temporal_overlap/rate_agreement_window_half_open
        """
        contributor, agr1 = setup_contributor_with_agreement(
            legal_name="Window Wes", email="wes@x.com",
            pricing_mode="PER_WORD", per_word_rate_cents=50,
            effective_from="2026-08-01T00:00:00Z",
            effective_to="2026-08-15T00:00:00Z")
        # Superseding agreement whose window begins exactly where A1's ends.
        agr2 = add_rate_agreement(get_contributor(contributor["id"]),
                                  pricing_mode="PER_WORD",
                                  per_word_rate_cents=100,
                                  effective_from="2026-08-15T00:00:00Z")
        assignment = create_assignment(contributor["id"], title="Boundary",
                                       deadline_utc="2026-08-20T00:00:00Z")
        set_clock("2026-08-15T00:00:00Z")

        offered = validate_success(
            api.offer_assignment(assignment["id"], EDITOR))
        assert offered["rate_agreement_id"] == agr2["id"], (
            "at the boundary instant the old window has ended (exclusive) "
            "and the new one has begun (inclusive)")
        assert offered["agreed_fee_cents"] == 10000, "100 words at 100 c/word"

        agr1_after = get_success_data(api.get_rate_agreement(agr1["id"],
                                                             ADMIN))
        agr2_after = get_success_data(api.get_rate_agreement(agr2["id"],
                                                             ADMIN))
        assert agr1_after["status"] == "SUPERSEDED"
        assert agr2_after["status"] == "ACTIVE"


def test_rate_agreement_create_with_stale_contributor_version(api):
    """PRD section 2.4: "Creating a rate agreement against a contributor
    requires the request to carry `expected_contributor_version`, the
    contributor `version` the client last observed; if it does not match the
    contributor's current `version`, the request is rejected with
    `ERR_STALE_VERSION` (HTTP 412)."
    PRD section 3.1: "Suspension by a `DeskAdmin` moves them to `SUSPENDED`,
    refreshing `updated_at` and bumping `version`; while suspended, no new
    assignment may be offered to them."
    PRD section 2.4: "Any mutation of an entity refreshes its `updated_at`
    and increments its `version` by one."

    Design: Corner/cross_cutting_layers/occ_rate_agreement_stale_version
    """
    contributor, agr1 = setup_contributor_with_agreement(
        legal_name="Occ Olga", email="olga@x.com")
    stale_version = contributor["version"]
    # Advance the contributor's version through PRD-stated mutations
    # (suspend bumps version; reinstate is a further mutation).
    get_success_data(api.suspend_contributor(contributor["id"], ADMIN))
    get_success_data(api.reinstate_contributor(contributor["id"], ADMIN))
    current = get_contributor(contributor["id"])
    assert current["version"] > stale_version, "setup must advance version"

    stale_payload = create_rate_agreement_payload(
        pricing_mode="FLAT", flat_fee_cents=60000, kill_fee_pct_num=25,
        rights_default="FIRST", effective_from="2026-08-02T00:00:00Z",
        expected_contributor_version=stale_version)
    resp = api.create_rate_agreement(contributor["id"], stale_payload, ADMIN)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION, 412)

    agreements = get_success_data(
        api.list_rate_agreements(contributor["id"], ADMIN))
    assert len(agreements) == 1, "no supersede happened on the failed write"
    assert agreements[0]["id"] == agr1["id"]
    assert agreements[0]["status"] == "ACTIVE"

    # Control: the same write carrying the current version succeeds and
    # supersedes the prior agreement (PRD 3.2 supersede pattern).
    ok_payload = create_rate_agreement_payload(
        pricing_mode="FLAT", flat_fee_cents=60000, kill_fee_pct_num=25,
        rights_default="FIRST", effective_from="2026-08-02T00:00:00Z",
        expected_contributor_version=current["version"])
    created = validate_success(
        api.create_rate_agreement(contributor["id"], ok_payload, ADMIN), 201)
    assert created["status"] == "ACTIVE"
    agr1_after = get_success_data(api.get_rate_agreement(agr1["id"], ADMIN))
    assert agr1_after["status"] == "SUPERSEDED"
