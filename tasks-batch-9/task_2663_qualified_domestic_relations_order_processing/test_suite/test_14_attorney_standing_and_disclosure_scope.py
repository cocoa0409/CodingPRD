"""Counsel's reach is measured twice: how much may be said, then who may say it.

Correspondence addressed to a lawyer is filtered by two independent gates that sit
on different rungs of the ladder, so the same revoked authorization answers two
different errors depending only on how much detail the letter asks for. The same
authorization row is simultaneously the lawyer's identity as an actor, which makes
a revocation reach forward over reading and filing as well as over letters.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import api_errors, factories, fixtures
from test_helpers.assertions import (
    assert_attorney_email_absent,
    assert_case_dimensions,
    assert_communication_sequence,
    assert_error_envelope,
    assert_fields_equal,
    assert_hold,
    assert_ids_in_order,
    assert_statuses_in_order,
)
from test_helpers.constants import CLOCK_2026_09_01
from test_helpers.test_users import ANALYST_HEADERS
from test_helpers.types import (
    APPROACH_SEPARATE_INTEREST,
    AUTHORIZATION_ACTIVE,
    AUTHORIZATION_REVOKED,
    DISCLOSURE_FULL,
    DISCLOSURE_LIMITED,
    DRAFT_UNDER_REVIEW,
    EARNINGS_PERIOD_END,
    FORMULA_PERCENTAGE_OF_ACCOUNT,
    HOLD_HELD,
    ORIGIN_MANUAL,
    ORIGIN_SYSTEM,
    RECIPIENT_ALTERNATE_PAYEE,
    RECIPIENT_AP_ATTORNEY,
    RECIPIENT_PARTICIPANT,
    RECIPIENT_PARTICIPANT_ATTORNEY,
    REPRESENTS_ALTERNATE_PAYEE,
    REPRESENTS_PARTICIPANT,
    REVIEW_UNDER_REVIEW,
    SEGREGATION_HELD,
    SOURCE_PRE_TAX_DEFERRAL,
    TEMPLATE_DEFICIENCY_NOTICE,
    TEMPLATE_DETERMINATION_QUALIFIED,
    TEMPLATE_RECEIPT_ACKNOWLEDGMENT,
)

COUNSEL_PLAN = {
    "acceptable_formula_codes": [FORMULA_PERCENTAGE_OF_ACCOUNT],
    "allowed_approaches": [APPROACH_SEPARATE_INTEREST],
    "earnings_adjustment_method": EARNINGS_PERIOD_END,
    "requires_model_language": True,
    "permits_benefit_not_otherwise_available": False,
    "max_assignable_pct_bps": 5000,
    "max_assignable_amount_cents": 2000000,
}

# The clock sits inside both windows below, so neither authorization is refused
# for being out of time — status and scope are the only variables left.
WINDOW = {"effective_from": "2026-08-01", "expires_at": "2027-12-31T00:00:00Z"}
SHORT_WINDOW = {"effective_from": "2026-08-01", "expires_at": "2027-08-01T00:00:00Z"}

# Scenario A: the participant's lawyer holds only LIMITED scope and is revoked,
# while the payee's lawyer holds FULL scope and keeps it.
HALVORSEN = {
    "full_name": "Pieter Halvorsen",
    "ssn_last4": "2277",
    "date_of_birth": "1981-01-31",
    "participation_start_date": "2010-01-01",
}
HALVORSEN_CASE = {
    "alternate_payee_name": "Sissel Halvorsen",
    "alternate_payee_dob": "1983-08-08",
    "marital_period_start": "2012-03-01",
    "marital_period_end": "2026-02-01",
}
OLA_LIMITED = dict(
    WINDOW,
    represents=REPRESENTS_PARTICIPANT,
    attorney_name="Ola Sandvik",
    attorney_bar_number="BAR-44120",
    attorney_email="ola@sandvikfamilylaw.example",
    disclosure_scope=DISCLOSURE_LIMITED,
)
REIDUN_FULL = dict(
    WINDOW,
    represents=REPRESENTS_ALTERNATE_PAYEE,
    attorney_name="Reidun Vik",
    attorney_bar_number="BAR-51993",
    attorney_email="reidun@vikqdro.example",
    disclosure_scope=DISCLOSURE_FULL,
)

# Scenario B: the scopes are mirrored, so the refusals must move with them.
AALTONEN = {
    "full_name": "Maren Aaltonen",
    "ssn_last4": "5150",
    "date_of_birth": "1975-05-05",
    "participation_start_date": "2010-01-01",
}
AALTONEN_CASE = {
    "alternate_payee_name": "Eino Aaltonen",
    "alternate_payee_dob": "1979-10-10",
    "marital_period_start": "2012-03-01",
    "marital_period_end": "2026-02-01",
}
HALLA_FULL = dict(
    SHORT_WINDOW,
    represents=REPRESENTS_PARTICIPANT,
    attorney_name="Halla Ingimundur",
    attorney_bar_number="BAR-77120",
    attorney_email="halla@ingimundur-law.example",
    disclosure_scope=DISCLOSURE_FULL,
)
PEKKA_LIMITED = dict(
    SHORT_WINDOW,
    represents=REPRESENTS_ALTERNATE_PAYEE,
    attorney_name="Pekka Rautio",
    attorney_bar_number="BAR-77121",
    attorney_email="pekka@rautio-law.example",
    disclosure_scope=DISCLOSURE_LIMITED,
)

RECEIPT_LETTER = (
    RECIPIENT_PARTICIPANT,
    TEMPLATE_RECEIPT_ACKNOWLEDGMENT,
    DISCLOSURE_LIMITED,
    ORIGIN_SYSTEM,
)


def _case_with_counsel_on_both_sides(
    client,
    plan_name,
    reference,
    participant_overrides,
    case_overrides,
    participant_auth,
    payee_auth,
):
    """One under-review case carrying one authorization per side."""
    setup = fixtures.setup_case_with_held_hold(
        client,
        plan_name,
        plan_overrides=COUNSEL_PLAN,
        participant_overrides=participant_overrides,
        case_overrides=case_overrides,
        draft_overrides={"document_reference": reference},
    )
    # A faultless draft keeps the case at UNDER_REVIEW rather than QUALIFIED, which
    # is what the payee-side disclosure ceiling is measured against.
    assert setup["draft"]["deficiency_codes"] == []
    assert_case_dimensions(
        setup["case"], REVIEW_UNDER_REVIEW, SEGREGATION_HELD, version=2
    )
    assert_hold(setup["hold"], status=HOLD_HELD, hold_amount_cents=400000)
    case_id = setup["case"]["id"]
    setup["auth_participant"] = fixtures.authorize_attorney(
        client, case_id, **participant_auth
    )
    setup["auth_payee"] = fixtures.authorize_attorney(client, case_id, **payee_auth)
    for authorization in (setup["auth_participant"], setup["auth_payee"]):
        assert authorization["status"] == AUTHORIZATION_ACTIVE
        assert authorization["revoked_at"] is None
        assert authorization["qdro_case_id"] == case_id
    return setup


def _send(client, case_id, recipient_type, disclosure_level, template_code):
    """The raw call, so a refusal can be inspected instead of raising."""
    return client.create_communication(
        case_id,
        factories.communication_payload(
            recipient_type=recipient_type,
            template_code=template_code,
            disclosure_level=disclosure_level,
        ),
        ANALYST_HEADERS,
    )


def _scenario_a(client, plan_name, reference="DRO-2663-S1"):
    """Scenario A with the participant's LIMITED authorization already revoked."""
    setup = _case_with_counsel_on_both_sides(
        client,
        plan_name,
        reference,
        HALVORSEN,
        HALVORSEN_CASE,
        OLA_LIMITED,
        REIDUN_FULL,
    )
    revoked = fixtures.revoke_authorization(client, setup["auth_participant"]["id"])
    assert_fields_equal(
        revoked,
        {
            "status": AUTHORIZATION_REVOKED,
            "revoked_at": CLOCK_2026_09_01,
            "disclosure_scope": DISCLOSURE_LIMITED,
            "attorney_email": "ola@sandvikfamilylaw.example",
        },
    )
    setup["auth_participant"] = revoked
    return setup


def test_the_scope_objection_outranks_the_missing_standing(client):
    """FULL detail to a revoked LIMITED attorney is a scope refusal, not a standing one.

    PRD: "That resolution happens **regardless of the authorization's status**, and
    if the request asks for `disclosure_level` `FULL` while the resolved
    authorization's `disclosure_scope` is `LIMITED`, the request is rejected with
    `ERR_DISCLOSURE_SCOPE_EXCEEDED` (HTTP 403). Because the disclosure rung precedes
    the cross-entity readiness rung, an over-scoped request addressed to a *revoked*
    attorney reports the scope violation rather than `ERR_ATTORNEY_NOT_AUTHORIZED`;
    the authorization must be `ACTIVE` only once the scope itself is acceptable."

    Design: Difficulty/priority_pair_validation_conflict/disclosure_scope_check_precedes_attorney_authorization_check
    """
    setup = _scenario_a(client, "Ordering Plan C")
    case_id = setup["case"]["id"]

    # The addressee resolves to the revoked row anyway, and its LIMITED scope is
    # the first thing the FULL request collides with.
    assert_error_envelope(
        _send(
            client,
            case_id,
            RECIPIENT_PARTICIPANT_ATTORNEY,
            DISCLOSURE_FULL,
            TEMPLATE_DEFICIENCY_NOTICE,
        ),
        api_errors.ERR_DISCLOSURE_SCOPE_EXCEEDED,
        403,
    )

    # A refusal on an append-only journal must leave the journal exactly as it was.
    letters = fixtures.read_communications(client, case_id)
    assert_communication_sequence(letters, [RECEIPT_LETTER])
    assert_attorney_email_absent(letters)
    assert fixtures.read_communications(client, case_id, origin=ORIGIN_MANUAL) == []

    # Neither the revocation nor the refusal disturbs the case itself: the version
    # still stands where the receipt (2) and the two recorded authorizations left
    # it — "recording one increments the case's version by one" (PRD 3.3) — while
    # a revocation increments only the authorization's own version.
    assert_case_dimensions(
        fixtures.read_case(client, case_id),
        REVIEW_UNDER_REVIEW,
        SEGREGATION_HELD,
        version=4,
    )


def test_dropping_the_detail_level_uncovers_the_standing_failure(client):
    """The identical letter at LIMITED detail reaches the later rung and fails there.

    PRD: "Correspondence addressed to counsel additionally requires a matching
    `ACTIVE` authorization on the case for the side addressed, failing which the
    request is refused with `ERR_ATTORNEY_NOT_AUTHORIZED`."

    Design: Difficulty/priority_pair_validation_conflict/disclosure_scope_check_precedes_attorney_authorization_check
    """
    setup = _scenario_a(client, "Ordering Plan D", reference="DRO-2663-S2")
    case_id = setup["case"]["id"]

    # Same addressee, same template, one notch less detail: the scope rung is
    # satisfied, so the refusal now comes from the authorization's status.
    assert_error_envelope(
        _send(
            client,
            case_id,
            RECIPIENT_PARTICIPANT_ATTORNEY,
            DISCLOSURE_LIMITED,
            TEMPLATE_DEFICIENCY_NOTICE,
        ),
        api_errors.ERR_ATTORNEY_NOT_AUTHORIZED,
        403,
    )

    # The other side of the same case holds an ACTIVE FULL authorization, so the
    # very detail level just refused for one lawyer is delivered to the other.
    delivered = fixtures.send_manual_communication(
        client,
        case_id,
        recipient_type=RECIPIENT_AP_ATTORNEY,
        template_code=TEMPLATE_DEFICIENCY_NOTICE,
        disclosure_level=DISCLOSURE_FULL,
    )
    assert_fields_equal(
        delivered,
        {
            "recipient_type": RECIPIENT_AP_ATTORNEY,
            "template_code": TEMPLATE_DEFICIENCY_NOTICE,
            "disclosure_level": DISCLOSURE_FULL,
            "origin": ORIGIN_MANUAL,
            "sent_at": CLOCK_2026_09_01,
            "attorney_email": setup["auth_payee"]["attorney_email"],
        },
    )
    # The address is a copy of the authorization's value, not a pointer to it.
    assert delivered["attorney_email"] == "reidun@vikqdro.example"

    # The other half of the same rung: the payee herself is capped at LIMITED
    # until the case is qualified, with no lawyer involved at all.
    assert_error_envelope(
        _send(
            client,
            case_id,
            RECIPIENT_ALTERNATE_PAYEE,
            DISCLOSURE_FULL,
            TEMPLATE_DETERMINATION_QUALIFIED,
        ),
        api_errors.ERR_DISCLOSURE_SCOPE_EXCEEDED,
        403,
    )

    # Exactly one hand-composed entry survived the three calls.
    assert_ids_in_order(
        fixtures.read_communications(client, case_id, origin=ORIGIN_MANUAL),
        [delivered["id"]],
    )
    assert_communication_sequence(
        fixtures.read_communications(client, case_id),
        [
            RECEIPT_LETTER,
            (RECIPIENT_AP_ATTORNEY, TEMPLATE_DEFICIENCY_NOTICE,
             DISCLOSURE_FULL, ORIGIN_MANUAL),
        ],
    )

    # The revocation removed one of the two authorizations from the ACTIVE set
    # without deleting the row.
    assert_ids_in_order(
        fixtures.read_authorizations(client, case_id, status=AUTHORIZATION_ACTIVE),
        [setup["auth_payee"]["id"]],
    )
    both = fixtures.read_authorizations(client, case_id)
    assert len(both) == 2, f"the revoked row is still listed: {both}"
    assert sorted(row["status"] for row in both) == [
        AUTHORIZATION_ACTIVE,
        AUTHORIZATION_REVOKED,
    ]


def _scenario_b(client, plan_name, reference="DRO-2663-D1"):
    """Scenario B: the participant's lawyer holds FULL, the payee's only LIMITED."""
    return _case_with_counsel_on_both_sides(
        client,
        plan_name,
        reference,
        AALTONEN,
        AALTONEN_CASE,
        HALLA_FULL,
        PEKKA_LIMITED,
    )


def test_each_side_is_measured_against_its_own_authorization(client):
    """The addressed side selects the authorization, and its scope decides the answer.

    PRD: "For correspondence addressed to counsel — `recipient_type` of
    `PARTICIPANT_ATTORNEY` or `AP_ATTORNEY` — the server resolves the authorization
    on the case whose `represents` matches the addressed side:
    `PARTICIPANT_ATTORNEY` resolves the authorization representing `PARTICIPANT`, and
    `AP_ATTORNEY` resolves the one representing `ALTERNATE_PAYEE`."

    Design: Difficulty/cross_entity_state_dependency/attorney_communication_gated_by_authorization_status_and_scope
    """
    setup = _scenario_b(client, "Disclosure Plan")
    case_id = setup["case"]["id"]

    # The participant's side holds FULL scope, so the fullest letter is delivered.
    to_participant_counsel = fixtures.send_manual_communication(
        client,
        case_id,
        recipient_type=RECIPIENT_PARTICIPANT_ATTORNEY,
        template_code=TEMPLATE_DEFICIENCY_NOTICE,
        disclosure_level=DISCLOSURE_FULL,
    )
    assert_fields_equal(
        to_participant_counsel,
        {
            "recipient_type": RECIPIENT_PARTICIPANT_ATTORNEY,
            "disclosure_level": DISCLOSURE_FULL,
            "origin": ORIGIN_MANUAL,
            "sent_at": CLOCK_2026_09_01,
            "attorney_email": setup["auth_participant"]["attorney_email"],
        },
    )
    assert to_participant_counsel["attorney_email"] == "halla@ingimundur-law.example"

    # The payee's side is ACTIVE too, so only the narrower scope can explain a
    # refusal of the identical request.
    assert_error_envelope(
        _send(
            client,
            case_id,
            RECIPIENT_AP_ATTORNEY,
            DISCLOSURE_FULL,
            TEMPLATE_DEFICIENCY_NOTICE,
        ),
        api_errors.ERR_DISCLOSURE_SCOPE_EXCEEDED,
        403,
    )

    # Dropping to the level that authorization actually grants is accepted.
    to_payee_counsel = fixtures.send_manual_communication(
        client,
        case_id,
        recipient_type=RECIPIENT_AP_ATTORNEY,
        template_code=TEMPLATE_DEFICIENCY_NOTICE,
        disclosure_level=DISCLOSURE_LIMITED,
    )
    assert to_payee_counsel["attorney_email"] == setup["auth_payee"]["attorney_email"]
    assert to_payee_counsel["attorney_email"] == "pekka@rautio-law.example"

    # Two hand-composed letters, each carrying the address of its own side.
    assert_communication_sequence(
        fixtures.read_communications(client, case_id),
        [
            RECEIPT_LETTER,
            (RECIPIENT_PARTICIPANT_ATTORNEY, TEMPLATE_DEFICIENCY_NOTICE,
             DISCLOSURE_FULL, ORIGIN_MANUAL),
            (RECIPIENT_AP_ATTORNEY, TEMPLATE_DEFICIENCY_NOTICE,
             DISCLOSURE_LIMITED, ORIGIN_MANUAL),
        ],
    )
    payee_side = fixtures.read_communications(
        client, case_id, recipient_type=RECIPIENT_AP_ATTORNEY
    )
    assert_ids_in_order(payee_side, [to_payee_counsel["id"]])
    assert payee_side[0]["disclosure_level"] == DISCLOSURE_LIMITED
    assert_statuses_in_order(
        fixtures.read_authorizations(client, case_id, status=AUTHORIZATION_ACTIVE),
        [AUTHORIZATION_ACTIVE, AUTHORIZATION_ACTIVE],
    )


def test_the_revocation_reaches_the_letter_and_the_filing_alike(client):
    """After revocation the same FULL letter is refused and the lawyer cannot file.

    PRD: "An attorney's reach over the case is bounded in three ways at once: by the
    case named in the authorization, by the `disclosure_scope` recorded on it, and by
    time. The authorization is operative from `effective_from` until `expires_at`, and
    revocation ends it immediately — after revocation no correspondence may cite the
    authorization and an attorney acting under it is rejected with
    `ERR_ATTORNEY_NOT_AUTHORIZED`."

    Design: Difficulty/cross_entity_state_dependency/attorney_communication_gated_by_authorization_status_and_scope
    """
    setup = _scenario_b(client, "Disclosure Plan B", reference="DRO-2663-D2")
    case_id = setup["case"]["id"]
    draft_id = setup["draft"]["id"]
    authorization = setup["auth_participant"]

    # The letter is accepted while the authorization stands, which fixes the
    # baseline the revocation is measured against.
    fixtures.send_manual_communication(
        client,
        case_id,
        recipient_type=RECIPIENT_PARTICIPANT_ATTORNEY,
        template_code=TEMPLATE_DEFICIENCY_NOTICE,
        disclosure_level=DISCLOSURE_FULL,
    )

    revoked = fixtures.revoke_authorization(client, authorization["id"])
    assert_fields_equal(
        revoked,
        {
            "status": AUTHORIZATION_REVOKED,
            "revoked_at": CLOCK_2026_09_01,
            "disclosure_scope": DISCLOSURE_FULL,
        },
    )

    # The scope is still FULL, so the scope rung cannot be what refuses this now.
    assert_error_envelope(
        _send(
            client,
            case_id,
            RECIPIENT_PARTICIPANT_ATTORNEY,
            DISCLOSURE_FULL,
            TEMPLATE_DEFICIENCY_NOTICE,
        ),
        api_errors.ERR_ATTORNEY_NOT_AUTHORIZED,
        403,
    )

    # The same row is the lawyer's identity as an actor, so filing dies with it.
    current = fixtures.read_case(client, case_id)
    assert_error_envelope(
        client.create_draft_order(
            factories.draft_order_payload(
                case_id,
                current["version"],
                document_reference="DRO-2663-D3",
                attorney_authorization_id=authorization["id"],
            ),
            fixtures.attorney_headers(authorization),
        ),
        api_errors.ERR_ATTORNEY_NOT_AUTHORIZED,
        403,
    )

    # Nothing was superseded and no second hold was placed by the refused filing.
    live = fixtures.read_draft(client, draft_id)
    assert_fields_equal(
        live,
        {
            "revision_number": 1,
            "status": DRAFT_UNDER_REVIEW,
            "document_reference": "DRO-2663-D2",
            "attorney_authorization_id": None,
        },
    )
    holds = fixtures.read_holds(client, qdro_case_id=case_id)
    assert len(holds) == 1, f"the refused filing placed a second hold: {holds}"
    assert_hold(holds[0], status=HOLD_HELD, hold_amount_cents=400000)
    assert_communication_sequence(
        fixtures.read_communications(client, case_id),
        [
            RECEIPT_LETTER,
            (RECIPIENT_PARTICIPANT_ATTORNEY, TEMPLATE_DEFICIENCY_NOTICE,
             DISCLOSURE_FULL, ORIGIN_MANUAL),
        ],
    )


def _two_cases_each_with_counsel(client):
    """Two cases on two participants of one plan, with counsel recorded on both."""
    plan = fixtures.create_published_plan(client, plan_name="Cross Link Plan", **COUNSEL_PLAN)
    fixtures.set_clock(client, CLOCK_2026_09_01)
    people = []
    for full_name, ssn_last4, dob, payee_name, payee_dob in (
        ("Anselm Faber", "8801", "1976-02-02", "Judit Faber", "1978-03-03"),
        ("Boris Kaleta", "8802", "1977-04-04", "Lenka Kaleta", "1979-05-05"),
    ):
        participant = fixtures.enroll_participant(
            client,
            plan["id"],
            full_name=full_name,
            ssn_last4=ssn_last4,
            date_of_birth=dob,
            participation_start_date="2010-01-01",
        )
        account = fixtures.open_plan_account(client, participant["id"])
        fixtures.add_money_source(
            client, account["id"], SOURCE_PRE_TAX_DEFERRAL, 1000000, basis_cents=0
        )
        fixtures.add_snapshot(client, account["id"], "2026-06-30", 1000000)
        case = fixtures.open_case(
            client,
            participant["id"],
            alternate_payee_name=payee_name,
            alternate_payee_dob=payee_dob,
            marital_period_start="2012-03-01",
            marital_period_end="2026-02-01",
        )
        people.append({"participant": participant, "account": account, "case": case})

    case_a, case_b = people[0]["case"], people[1]["case"]
    auth_a1 = fixtures.authorize_attorney(client, case_a["id"], **dict(
        WINDOW,
        represents=REPRESENTS_PARTICIPANT,
        attorney_name="Aslak Nyholm",
        attorney_bar_number="BAR-60001",
        attorney_email="nyholm@faberlaw.example",
        disclosure_scope=DISCLOSURE_FULL,
    ))
    auth_a2 = fixtures.authorize_attorney(client, case_a["id"], **dict(
        WINDOW,
        represents=REPRESENTS_ALTERNATE_PAYEE,
        attorney_name="Trude Osland",
        attorney_bar_number="BAR-60002",
        attorney_email="osland@oslandqdro.example",
        disclosure_scope=DISCLOSURE_LIMITED,
    ))
    auth_b1 = fixtures.authorize_attorney(client, case_b["id"], **dict(
        WINDOW,
        represents=REPRESENTS_PARTICIPANT,
        attorney_name="Mikkel Roine",
        attorney_bar_number="BAR-60003",
        attorney_email="roine@kaletalaw.example",
        disclosure_scope=DISCLOSURE_FULL,
    ))
    # "recording one increments the case's `version` by one" (PRD 3.3), so the
    # rows captured at intake are stale for a later draft-order receipt; re-read
    # them so `expected_case_version` carries the version actually observable.
    return {
        "case_a": fixtures.read_case(client, case_a["id"]),
        "case_b": fixtures.read_case(client, case_b["id"]),
        "auth_a1": auth_a1,
        "auth_a2": auth_a2,
        "auth_b1": auth_b1,
    }


def test_the_filing_attorney_must_be_this_case_s_and_only_their_own(client):
    """A stranger to the case and a borrowed authorization fail one rung apart.

    PRD: "Whenever an entity-backed role — `Participant`, `AlternatePayee`, or
    `Attorney` — presents an `X-User-ID` that does not match the resource it is acting
    on, the request is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403). An acting
    `Attorney` faces one further gate: the authorization whose `id` is the presented
    `X-User-ID` must be in `ACTIVE` status, and the logical clock must fall inside the
    authorization's operative window — on or after `effective_from` (interpreted as
    that calendar date at midnight UTC) and at or before `expires_at`. When a draft
    order is submitted by an acting `Attorney` and the body carries an
    `attorney_authorization_id`, that value must equal the acting attorney's
    `X-User-ID`. Any of these failures is rejected with `ERR_ATTORNEY_NOT_AUTHORIZED`
    (HTTP 403)."

    Design: Corner/endpoints/an_attorney_is_linked_to_exactly_one_case_and_only_through_a_live_authorization
    """
    setup = _two_cases_each_with_counsel(client)
    case_a = setup["case_a"]
    auth_a1, auth_a2, auth_b1 = setup["auth_a1"], setup["auth_a2"], setup["auth_b1"]

    def filing(body_authorization_id):
        return factories.draft_order_payload(
            case_a["id"],
            case_a["version"],
            document_reference="DRO-2663-XREF-a",
            attorney_authorization_id=body_authorization_id,
        )

    # The other case's lawyer names a genuine case-A authorization in the body, but
    # the acting identity is resolved against the case the request reaches.
    assert_error_envelope(
        client.create_draft_order(
            filing(auth_a1["id"]), fixtures.attorney_headers(auth_b1)
        ),
        api_errors.ERR_NOT_RESOURCE_OWNER,
        403,
    )

    # Both authorizations are on this case and both are ACTIVE, so only the
    # equality rule can refuse a lawyer filing under a colleague's number.
    assert_error_envelope(
        client.create_draft_order(
            filing(auth_a2["id"]), fixtures.attorney_headers(auth_a1)
        ),
        api_errors.ERR_ATTORNEY_NOT_AUTHORIZED,
        403,
    )

    # Changing only the body id turns the identical request into a receipt.
    accepted = fixtures.receive_draft(
        client,
        case_a["id"],
        case_a["version"],
        headers=fixtures.attorney_headers(auth_a1),
        document_reference="DRO-2663-XREF-a",
        attorney_authorization_id=auth_a1["id"],
    )
    assert_fields_equal(
        accepted,
        {
            "status": DRAFT_UNDER_REVIEW,
            "revision_number": 1,
            "attorney_authorization_id": auth_a1["id"],
        },
    )

    # The link is queryable from the authorization's end as well.
    linked = validate_success(
        client.list_draft_orders(
            fixtures.attorney_headers(auth_a1),
            {"attorney_authorization_id": auth_a1["id"], "limit": 10, "offset": 0},
        )
    )
    assert_ids_in_order(linked, [accepted["id"]])
    assert fixtures.read_holds(client, qdro_case_id=setup["case_b"]["id"]) == [], (
        "the refused filing by case B's lawyer must not have touched case B either"
    )

    # Standing is evaluated per request against the live row, so the identity that
    # created the draft cannot read it once the authorization is revoked.
    assert (
        fixtures.revoke_authorization(client, auth_a1["id"])["status"]
        == AUTHORIZATION_REVOKED
    )
    assert_error_envelope(
        client.get_draft_order(accepted["id"], fixtures.attorney_headers(auth_a1)),
        api_errors.ERR_ATTORNEY_NOT_AUTHORIZED,
        403,
    )

    # Revoking an authorization is not a cascade over the work already filed.
    survivor = fixtures.read_draft(client, accepted["id"])
    assert_fields_equal(
        survivor,
        {
            "status": DRAFT_UNDER_REVIEW,
            "revision_number": 1,
            "attorney_authorization_id": auth_a1["id"],
        },
    )
    assert_hold(
        fixtures.hold_for_case(client, case_a["id"]),
        status=HOLD_HELD,
        hold_amount_cents=400000,
    )
