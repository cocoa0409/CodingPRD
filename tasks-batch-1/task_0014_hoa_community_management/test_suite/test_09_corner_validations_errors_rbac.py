"""Corner-design translations from queue (B): validations §4, errors §6,
rbac §7, cross-cutting complexity §8, consistency model §9."""
from test_helpers import (
    ApiErrorId,
    apply_payment,
    bootstrap_election_open_with_voters,
    bootstrap_lien_via_cascade,
    bootstrap_tenant,
    cast_vote,
    create_assessment,
    create_community,
    create_election,
    create_owner,
    create_property,
    set_clock,
    validate_error,
    validate_success,
)
from test_helpers.test_users import (
    make_acc_member_headers,
    make_board_president_headers,
    make_board_secretary_headers,
    make_homeowner_headers,
    make_platform_admin_headers,
    make_treasurer_headers,
)
from prd_bench_local_runner.testing import build_user_headers


# ─────────────────────────────────────────────────────────────────────────────
# Section: validations
# ─────────────────────────────────────────────────────────────────────────────

def test_payment_amount_above_remaining_outstanding_rejected(api):
    """PRD §3.2: "The system first verifies that `amount_cents` does not
    exceed `principal_cents + late_fee_cents - paid_cents` on the target
    assessment; if it does, the payment is rejected with `ERR_OVERPAYMENT`
    (no partial application — the entire request is refused)."

    Setup: principal 10000, no fees, DUE. Submit payment 15000 → rejected
    with ERR_OVERPAYMENT.

    Design: Corner/validations/overpayment_against_active_assessment_returns_overpayment_error
    """
    _community, _owner, prop = bootstrap_tenant(
        community_name="OvPay", owner_email="op@x.com", owner_name="OP",
        unit_label="OP-1", regular_assessment_cents=10000,
    )
    a = create_assessment(
        prop["id"], kind="REGULAR", principal_cents=10000,
        due_date="2027-01-01T00:00:00Z",
    )
    resp = api.create_payment(
        {
            "assessment_id": a["id"],
            "amount_cents": 15000,
            "expected_assessment_version": a["version"],
        },
        make_treasurer_headers(),
    )
    validate_error(resp, ApiErrorId.ERR_OVERPAYMENT)


def test_duplicate_owner_email_within_community_rejected(api):
    """PRD §3.1: "Owners are registered next, each `Owner` belonging to a
    `Community` by `community_id` and identified by `email` and `full_name`.
    The `email` must be unique within its community; a duplicate yields
    `ERR_DUPLICATE_OWNER_EMAIL`."

    Design: Corner/validations/duplicate_owner_email_in_same_community_rejected
    """
    community = create_community(name="DupEmail", regular_assessment_cents=10000)
    create_owner(community["id"], email="same@x.com", full_name="A")
    resp = api.create_owner(
        {
            "community_id": community["id"],
            "email": "same@x.com",
            "full_name": "B",
        },
        make_platform_admin_headers(),
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_OWNER_EMAIL)


def test_duplicate_unit_label_within_community_rejected(api):
    """PRD §3.1: "Properties are then bound to owners: a `Property` carries
    `community_id`, the current `owner_id` of record, and a `unit_label`
    (e.g. \"12-A\") that must be unique within its community; a duplicate
    label yields `ERR_DUPLICATE_UNIT_LABEL`."

    Design: Corner/validations/duplicate_unit_label_in_community_rejected
    """
    community = create_community(name="DupUnit", regular_assessment_cents=10000)
    owner = create_owner(community["id"], email="du@x.com", full_name="DU")
    create_property(community["id"], owner["id"], unit_label="U-Dup")
    resp = api.create_property(
        {
            "community_id": community["id"],
            "owner_id": owner["id"],
            "unit_label": "U-Dup",
        },
        make_platform_admin_headers(),
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_UNIT_LABEL)


def test_duplicate_cast_vote_for_same_owner_rejected(api):
    """PRD §3.7: "Each owner may have at most one `CAST` vote per election:
    a second attempt while a prior `CAST` vote exists for the same
    election yields `ERR_DUPLICATE_VOTE`."

    Setup: Election OPEN, owner casts vote. Submit a second vote for the
    same (election, owner) → ERR_DUPLICATE_VOTE.

    Design: Corner/validations/duplicate_vote_cast_blocked
    """
    _community, owners, election = bootstrap_election_open_with_voters(
        community_name="DupVote",
        eligible_owner_count=1,
        cycle_label="DV-FY",
        opens_at="2026-02-01T00:00:00Z",
        closes_at="2026-02-16T00:00:00Z",
        clock_before_open="2026-01-15T00:00:00Z",
        clock_after_open="2026-02-02T00:00:00Z",
    )
    owner = owners[0]
    cast_vote(election["id"], owner["id"], candidate_name="Alice")
    resp = api.create_vote(
        {
            "election_id": election["id"],
            "owner_id": owner["id"],
            "candidate_name": "Bob",
        },
        make_homeowner_headers(owner["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_VOTE)


def test_retracted_vote_does_not_block_subsequent_cast(api):
    """PRD §3.7: "An owner who wishes to change their mind may retract a
    `CAST` vote while the election remains `OPEN`, moving its `state` to
    `RETRACTED`; a `RETRACTED` vote does NOT block the same owner from
    subsequently casting a fresh `CAST` vote (so the uniqueness rule is
    properly stated as one CAST vote per pairing, not one row per pairing)."

    Setup: Owner casts then retracts a vote. A subsequent new cast must
    succeed.

    Design: Corner/validations/retracted_vote_does_not_block_new_vote
    """
    _community, owners, election = bootstrap_election_open_with_voters(
        community_name="Retract",
        eligible_owner_count=1,
        cycle_label="RE-FY",
        opens_at="2026-02-01T00:00:00Z",
        closes_at="2026-02-16T00:00:00Z",
        clock_before_open="2026-01-15T00:00:00Z",
        clock_after_open="2026-02-02T00:00:00Z",
    )
    owner = owners[0]
    v1 = cast_vote(election["id"], owner["id"], candidate_name="Alice")
    validate_success(
        api.retract_vote(v1["id"], make_homeowner_headers(owner["id"])),
        expected_status=200,
    )
    resp = api.create_vote(
        {
            "election_id": election["id"],
            "owner_id": owner["id"],
            "candidate_name": "Bob",
        },
        make_homeowner_headers(owner["id"]),
    )
    v2 = validate_success(resp, expected_status=201)
    assert v2["state"] == "CAST"


# ─────────────────────────────────────────────────────────────────────────────
# Section: errors
# ─────────────────────────────────────────────────────────────────────────────

def test_missing_role_header_returns_unauthenticated(api):
    """PRD §2.1: "Every request must carry two HTTP headers: `X-User-ID`,
    identifying the acting user, and `X-User-Role`, naming the operational
    capacity in which they are acting. A request that omits either header
    is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/errors/error_unauthenticated_missing_role_header
    """
    # Empty headers dict → both X-User-ID and X-User-Role missing.
    resp = api.get_community(
        "00000000-0000-0000-0000-000000000000", headers={},
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


def test_unrecognized_role_returns_unauthorized(api):
    """PRD §2.1: "A request whose `X-User-Role` is not one of the names
    enumerated below is rejected with `ERR_UNAUTHORIZED` (HTTP 403), as
    is any request whose role is recognized but not permitted to call
    the targeted endpoint."

    Design: Corner/errors/error_unauthorized_unknown_role
    """
    community = create_community(name="Unauth", regular_assessment_cents=10000)
    hacker_headers = build_user_headers("attacker-1", "Hacker")
    resp = api.get_community(community["id"], hacker_headers)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)


def test_segregation_of_duties_president_same_id_as_opening_secretary(api):
    """PRD §3.7: "From `CLOSED_QUORUM_MET`, the `BoardPresident` may
    certify the election, moving it to `CERTIFIED` (terminal). The certify
    action is subject to a segregation-of-duties check: the `X-User-ID`
    of the certifying president must not equal the `X-User-ID` of the
    secretary who issued the OPEN. A self-certification attempt is
    refused with `ERR_SEGREGATION_OF_DUTIES`."

    Setup: Same X-User-ID ("same-officer-id") issues OPEN as
    BoardSecretary, then attempts to certify as BoardPresident → must
    yield ERR_SEGREGATION_OF_DUTIES.

    Design: Corner/errors/error_segregation_of_duties_president_certifies_after_opening
    """
    community = create_community(
        name="SegDut", regular_assessment_cents=30000, election_quorum_pct=1,
    )
    owner = create_owner(community["id"], email="sd@x.com", full_name="SD")
    create_property(community["id"], owner["id"], unit_label="SD-1")
    set_clock("2026-01-15T00:00:00Z")
    election = validate_success(
        api.create_election(
            {
                "community_id": community["id"],
                "cycle_label": "SD-FY",
                "opens_at": "2026-02-01T00:00:00Z",
                "closes_at": "2026-02-16T00:00:00Z",
            },
            build_user_headers("same-officer-id", "BoardSecretary"),
        ),
        expected_status=201,
    )
    validate_success(
        api.open_election(
            election["id"], community["version"],
            build_user_headers("same-officer-id", "BoardSecretary"),
        ),
        expected_status=200,
    )
    set_clock("2026-02-02T00:00:00Z")
    cast_vote(election["id"], owner["id"], candidate_name="Alice")
    set_clock("2026-02-17T00:00:00Z")
    validate_success(
        api.close_election(
            election["id"],
            build_user_headers("same-officer-id", "BoardSecretary"),
        ),
        expected_status=200,
    )
    resp = api.certify_election(
        election["id"],
        build_user_headers("same-officer-id", "BoardPresident"),
    )
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)


def test_vote_before_election_open_returns_election_not_open(api):
    """PRD §3.7: "A vote outside the window — either before OPEN, after
    `closes_at`, or against an election no longer `OPEN` — is refused
    with `ERR_ELECTION_NOT_OPEN`."

    Setup: Election in DRAFT (never OPEN'd) with an eligible voter who
    owns a Property in the community. A POST /votes must reject with
    ERR_ELECTION_NOT_OPEN.

    Design: Corner/errors/error_election_not_open_vote_before_window
    """
    community, owner, _prop = bootstrap_tenant(
        community_name="EarlyVote", owner_email="ev@x.com", owner_name="EV",
        unit_label="EV-1",
    )
    set_clock("2026-01-15T00:00:00Z")
    election = create_election(
        community["id"], cycle_label="EV-FY",
        opens_at="2026-02-01T00:00:00Z",
        closes_at="2026-02-16T00:00:00Z",
    )
    assert election["status"] == "DRAFT"
    resp = api.create_vote(
        {
            "election_id": election["id"],
            "owner_id": owner["id"],
            "candidate_name": "Alice",
        },
        make_homeowner_headers(owner["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_ELECTION_NOT_OPEN)


# ─────────────────────────────────────────────────────────────────────────────
# Section: rbac
# ─────────────────────────────────────────────────────────────────────────────

def test_homeowner_cannot_create_assessment(api):
    """PRD §2.1: "A request whose `X-User-Role` is not one of the names
    enumerated below is rejected with `ERR_UNAUTHORIZED` (HTTP 403), as
    is any request whose role is recognized but not permitted to call
    the targeted endpoint."
    PRD §4 table: "POST `/hoa/assessments` ... Treasurer".

    Design: Corner/rbac/homeowner_cannot_create_assessment
    """
    _community, owner, prop = bootstrap_tenant(
        community_name="RBAC1", owner_email="rb1@x.com", owner_name="RB1",
        unit_label="RB1-1",
    )
    resp = api.create_assessment(
        {
            "property_id": prop["id"],
            "kind": "REGULAR",
            "principal_cents": 10000,
            "due_date": "2027-01-01T00:00:00Z",
        },
        make_homeowner_headers(owner["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)


def test_acc_member_cannot_initiate_foreclosure(api):
    """PRD §2.1: "A request whose `X-User-Role` is not one of the names
    enumerated below is rejected with `ERR_UNAUTHORIZED` (HTTP 403), as
    is any request whose role is recognized but not permitted to call
    the targeted endpoint."
    PRD §4 table: "POST `/hoa/liens/{id}/initiate-foreclosure` ...
    BoardPresident".

    Design: Corner/rbac/acc_member_cannot_initiate_foreclosure
    """
    _community, _owner, _prop, _assess, lien = bootstrap_lien_via_cascade(
        community_name="RBAC2", owner_email="rb2@x.com", owner_name="RB2",
        unit_label="RB2-1",
    )
    resp = api.initiate_foreclosure(lien["id"], make_acc_member_headers())
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)


# ─────────────────────────────────────────────────────────────────────────────
# Section: cross_cutting_complexity_layers
# ─────────────────────────────────────────────────────────────────────────────

def test_stale_assessment_version_on_second_payment_returns_stale_version(api):
    """PRD §2.8: "When a client submits a payment, the request body must
    include `expected_assessment_version` as a non-optional integer field
    carrying the `version` value of the target `Assessment` that the
    client most recently observed. The server compares this to the
    assessment's current `version` at the moment the payment is processed;
    if the assessment has been mutated by any other writer since the
    client last read it — whether a competing payment, a waiver, or a
    clock-driven overdue recomputation that recomputed `late_fee_cents`
    — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), and
    the client must re-fetch the assessment before retrying."

    Setup: principal 20000, version=1. First POST /payments with
    expected_assessment_version=1 succeeds and advances version. Second
    POST /payments with the same stale expected_assessment_version=1 →
    ERR_STALE_VERSION.

    Design: Corner/cross_cutting_complexity_layers/occ_stale_assessment_version_rejected
    """
    _community, _owner, prop = bootstrap_tenant(
        community_name="OCC1", owner_email="occ1@x.com", owner_name="OCC1",
        unit_label="OCC1-1", regular_assessment_cents=10000,
    )
    a = create_assessment(
        prop["id"], kind="REGULAR", principal_cents=20000,
        due_date="2027-06-01T00:00:00Z",
    )
    stale_version = a["version"]
    apply_payment(a["id"], 5000, stale_version)
    resp = api.create_payment(
        {
            "assessment_id": a["id"],
            "amount_cents": 5000,
            "expected_assessment_version": stale_version,
        },
        make_treasurer_headers(),
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


def test_stale_community_version_on_open_election_returns_stale_version(api):
    """PRD §2.8: "Similarly, opening a board election requires the request
    body to include `expected_community_version` carrying the `version`
    of the target `BoardElection`'s parent `Community` as the client last
    observed it; a mismatch yields `ERR_STALE_VERSION` (HTTP 412),
    reflecting that the election's snapshot of voter eligibility is
    governed by `Community`-level config (`election_quorum_pct` and so
    on) and a stale community view means the snapshot the transition is
    about to freeze may diverge from what the caller believes is correct."

    Setup: Community at version v (created with v=1). Try to OPEN with
    `expected_community_version = v - 1` (an arithmetic-stale value) →
    ERR_STALE_VERSION.

    Design: Corner/cross_cutting_complexity_layers/occ_stale_community_version_rejects_election_open
    """
    community, _owner, _prop = bootstrap_tenant(
        community_name="OCC2", owner_email="occ2@x.com", owner_name="OCC2",
        unit_label="OCC2-1",
    )
    set_clock("2026-01-15T00:00:00Z")
    election = create_election(
        community["id"], cycle_label="OCC2-FY",
        opens_at="2026-02-01T00:00:00Z",
        closes_at="2026-02-16T00:00:00Z",
    )
    stale_version = community["version"] - 1
    resp = api.open_election(
        election["id"], stale_version, make_board_secretary_headers(),
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


# ─────────────────────────────────────────────────────────────────────────────
# Section: consistency_model
# ─────────────────────────────────────────────────────────────────────────────

def test_assessment_visible_in_immediately_following_get(api):
    """PRD §2.2: "All successful API responses (those with 2xx status
    codes) follow this standard envelope format in their JSON body".
    PRD §3.2: "The new `Assessment` is born in the `DUE` state with
    `late_fee_cents` of zero, `paid_cents` of zero, and `outstanding_cents`
    equal to `principal_cents`."

    The POST response data IS the just-created Assessment (PRD §2.2:
    "operations that create or modify a resource will return the created
    or updated resource object in the data field"), and an immediately
    following GET returns the same row — there is no eventual-consistency
    delay window in this API.

    Design: Corner/consistency_model/assessment_creation_visible_in_immediate_get_response
    """
    _community, _owner, prop = bootstrap_tenant(
        community_name="Imm", owner_email="im2@x.com", owner_name="IM2",
        unit_label="IM2-1", regular_assessment_cents=10000,
    )
    post_resp = api.create_assessment(
        {
            "property_id": prop["id"],
            "kind": "REGULAR",
            "principal_cents": 10000,
            "due_date": "2027-06-01T00:00:00Z",
        },
        make_treasurer_headers(),
    )
    posted = validate_success(post_resp, expected_status=201)
    assert posted["status"] == "DUE"
    got = validate_success(
        api.get_assessment(posted["id"], make_treasurer_headers()),
        expected_status=200,
    )
    assert got["id"] == posted["id"]
    assert got["status"] == "DUE"
