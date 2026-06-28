"""Introduction suggestion, the two-party negotiation, and OCC version checks."""
from test_helpers import (
    validate_success,
    validate_error,
    TEST_USERS,
    make_member_headers,
    ApiErrorId,
    fixtures as fx,
)
import test_helpers.factories as f

ADMIN = TEST_USERS["billing_admin_headers"]
SCREENING = TEST_USERS["screening_officer_headers"]
MATCHMAKER = TEST_USERS["matchmaker_headers"]


def test_introduction_one_sided_then_declined_branch(api):
    """PRD §3.5: "The first accept moves the introduction from `SUGGESTED` to `ONE_SIDED".
    PRD §3.5: "A decline by either party, from SUGGESTED or ONE_SIDED, records that
    party's response as DECLINED and moves the introduction to DECLINED. A decline
    refunds this introduction's credits_consumed back to member A's guarantee ... so
    member A's guarantee_remaining_forecast is restored."

    Design: Difficulty/non_linear_state_machine/introduction_branching_one_sided_to_mutual_or_declined
    """
    ctx = fx.setup_suggested_introduction(a_email="a2@x.com", b_email="b6@x.com")
    a_id, b_id = ctx["member_a"]["id"], ctx["member_b"]["id"]
    intro = ctx["introduction"]

    # member_a accepts -> ONE_SIDED
    intro = fx.respond(intro["id"], a_id, "ACCEPTED", intro["version"])
    assert intro["status"] == "ONE_SIDED", f"after first accept expected ONE_SIDED, got {intro['status']}"

    # member_b declines -> DECLINED, credit refunded
    resp = api.respond_introduction(
        intro["id"], f.respond_introduction_payload("DECLINED", intro["version"]),
        make_member_headers(b_id),
    )
    declined = validate_success(resp, 200)
    assert declined["status"] == "DECLINED", f"expected DECLINED, got {declined['status']}"

    member_a = validate_success(api.get_member(a_id, MATCHMAKER), 200)
    assert member_a["guarantee_remaining_forecast"] == 8, (
        f"decline must restore forecast to 8, got {member_a['guarantee_remaining_forecast']}"
    )


def test_introduction_second_accept_reaches_mutual(api):
    """PRD §3.5: "The second accept — by the other party — completes the quorum: with both `a_response` and `b_response` now `ACCEPTED`, the introduction advances from `SUGGESTED` or `ONE_SIDED` to `MUTUAL`."

    Design: Difficulty/non_linear_state_machine/introduction_branching_one_sided_to_mutual_or_declined
    """
    ctx = fx.setup_suggested_introduction(a_email="a2b@x.com", b_email="b6b@x.com")
    a_id, b_id = ctx["member_a"]["id"], ctx["member_b"]["id"]
    intro = ctx["introduction"]

    intro = fx.respond(intro["id"], a_id, "ACCEPTED", intro["version"])
    assert intro["status"] == "ONE_SIDED"
    resp = api.respond_introduction(
        intro["id"], f.respond_introduction_payload("ACCEPTED", intro["version"]),
        make_member_headers(b_id),
    )
    mutual = validate_success(resp, 200)
    assert mutual["status"] == "MUTUAL", f"second accept must reach MUTUAL, got {mutual['status']}"


def test_respond_on_declined_introduction_returns_invalid_state(api):
    """PRD §3.5: "A response against an introduction that is no longer open (already declined or closed, or otherwise not in a respondable state) is rejected with `ERR_INVALID_INTRODUCTION_STATE`."

    Design: Corner/state_machines/respond_on_declined_introduction_returns_invalid_state
    """
    ctx = fx.setup_suggested_introduction(a_email="ca1@x.com", b_email="cb1@x.com")
    a_id, b_id = ctx["member_a"]["id"], ctx["member_b"]["id"]
    intro = ctx["introduction"]

    # member_b declines first -> DECLINED
    intro = fx.respond(intro["id"], b_id, "DECLINED", intro["version"])
    assert intro["status"] == "DECLINED"

    # member_a now tries to respond on the DECLINED introduction
    resp = api.respond_introduction(
        intro["id"], f.respond_introduction_payload("ACCEPTED", intro["version"]),
        make_member_headers(a_id),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_INTRODUCTION_STATE.value, 409)


def test_introduction_suggest_requires_both_members_eligible(api):
    """PRD §3.4: "Both parties must be eligible: each must be in status `ACTIVE` with an `APPROVED` screening, or the request fails with `ERR_MEMBER_NOT_ELIGIBLE`."

    Design: Difficulty/cross_entity_state_dependency/introduction_suggest_requires_both_members_eligible
    """
    fx.set_clock()
    plan = fx.create_plan()
    member_a, _ = fx.create_active_member(plan["id"], "a10@x.com", gender="MALE",
                                          pref_overrides={"seeking_gender": "FEMALE"})
    # member_b only registered (PROSPECT), never screened/activated
    member_b = fx.register_prospect("b13@x.com", gender="FEMALE")

    a_ver = fx.current_version(member_a["id"])
    resp = api.create_introduction(
        f.create_introduction_payload(member_a["id"], member_b["id"], a_ver), MATCHMAKER
    )
    validate_error(resp, ApiErrorId.ERR_MEMBER_NOT_ELIGIBLE.value, 422)


def test_introduction_suggest_rejects_exited_member_b(api):
    """PRD §3.4: "Both parties must be eligible: each must be in status `ACTIVE` with an `APPROVED` screening, or the request fails with `ERR_MEMBER_NOT_ELIGIBLE`." A member_b
    whose screening was REJECTED is EXITED (not ACTIVE) and so is ineligible.

    Design: Difficulty/cross_entity_state_dependency/introduction_suggest_requires_both_members_eligible
    """
    fx.set_clock()
    plan = fx.create_plan()
    member_a, _ = fx.create_active_member(plan["id"], "elig_a@x.com", gender="MALE",
                                          pref_overrides={"seeking_gender": "FEMALE"})
    # member_b rejected at screening -> EXITED.
    member_b = fx.register_prospect("elig_b@x.com", gender="FEMALE")
    fx.open_and_decide_screening(member_b["id"], decision="REJECTED",
                                 questionnaire_score=10, identity_verified=False)

    a_ver = fx.current_version(member_a["id"])
    resp = api.create_introduction(
        f.create_introduction_payload(member_a["id"], member_b["id"], a_ver), MATCHMAKER
    )
    validate_error(resp, ApiErrorId.ERR_MEMBER_NOT_ELIGIBLE.value, 422)


def test_self_introduction_rejected(api):
    """PRD §3.4: "The two parties must be distinct existing members; a request whose `member_a_id` equals its `member_b_id` is rejected with `ERR_SELF_INTRODUCTION`."

    Design: Corner/validations/self_introduction_rejected
    """
    fx.set_clock()
    plan = fx.create_plan()
    member_a, _ = fx.create_active_member(plan["id"], "ca10@x.com", gender="MALE",
                                          pref_overrides={"seeking_gender": "FEMALE"})
    a_ver = fx.current_version(member_a["id"])
    resp = api.create_introduction(
        f.create_introduction_payload(member_a["id"], member_a["id"], a_ver), MATCHMAKER
    )
    validate_error(resp, ApiErrorId.ERR_SELF_INTRODUCTION.value, 422)


def test_introduction_not_found_on_respond(api):
    """PRD §2.7: "rejects the request at the **first** identifier that does not resolve to an existing resource, returning that identifier's specific 404 error". PRD §5
    lists ERR_INTRODUCTION_NOT_FOUND as 404.

    Design: Corner/errors/introduction_not_found_on_respond
    """
    member = fx.register_prospect("ca15@x.com", gender="MALE")
    bad_intro = "00000000-0000-4000-8000-000000000abc"
    resp = api.respond_introduction(
        bad_intro, f.respond_introduction_payload("ACCEPTED", 1), make_member_headers(member["id"])
    )
    validate_error(resp, ApiErrorId.ERR_INTRODUCTION_NOT_FOUND.value, 404)


def test_occ_intro_create_stale_member_version_rejected(api):
    """PRD §2.10: "A suggestion request must carry `expected_member_a_version` equal to
    the current `version` of the suggesting member (member A)."
    PRD §2.10: "if member A's `version` has advanced since the caller last read it — for
    instance because another suggestion already consumed credits — the request is
    rejected with `ERR_STALE_VERSION` and HTTP status 412."

    Design: Corner/cross_cutting_complexity_layers/occ_intro_create_stale_member_version_rejected
    """
    fx.set_clock()
    plan = fx.create_plan()
    member_a, _ = fx.create_active_member(plan["id"], "ca16@x.com", gender="MALE",
                                          pref_overrides={"seeking_gender": "FEMALE"})
    member_b, _ = fx.create_active_member(plan["id"], "cb16@x.com", gender="FEMALE",
                                          pref_overrides={"seeking_gender": "MALE"})
    member_c, _ = fx.create_active_member(plan["id"], "cc16@x.com", gender="FEMALE",
                                          pref_overrides={"seeking_gender": "MALE"})

    stale_ver = fx.current_version(member_a["id"])
    # First create succeeds and bumps member_a's version.
    validate_success(
        api.create_introduction(
            f.create_introduction_payload(member_a["id"], member_b["id"], stale_ver), MATCHMAKER
        ),
        201,
    )
    # Second create reuses the pre-bump version -> stale.
    resp = api.create_introduction(
        f.create_introduction_payload(member_a["id"], member_c["id"], stale_ver), MATCHMAKER
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value, 412)


def test_occ_respond_stale_intro_version_rejected(api):
    """PRD §2.10: "A response request must carry `expected_introduction_version` equal
    to the current `version` of the target introduction."
    PRD §2.10: "a client acting on an introduction whose `version` has already advanced
    — because the counterpart's response was recorded first — is rejected with
    `ERR_STALE_VERSION` and HTTP status 412".

    Design: Corner/cross_cutting_complexity_layers/occ_respond_stale_intro_version_rejected
    """
    ctx = fx.setup_suggested_introduction(a_email="ca17@x.com", b_email="cb17@x.com")
    a_id, b_id = ctx["member_a"]["id"], ctx["member_b"]["id"]
    intro = ctx["introduction"]
    stale_ver = intro["version"]

    # member_a accepts, bumping the introduction version.
    validate_success(
        api.respond_introduction(
            intro["id"], f.respond_introduction_payload("ACCEPTED", stale_ver),
            make_member_headers(a_id),
        ),
        200,
    )
    # member_b responds with the now-stale version.
    resp = api.respond_introduction(
        intro["id"], f.respond_introduction_payload("ACCEPTED", stale_ver),
        make_member_headers(b_id),
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value, 412)
