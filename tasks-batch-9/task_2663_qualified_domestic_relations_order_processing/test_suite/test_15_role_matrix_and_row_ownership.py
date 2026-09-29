"""Who may act is settled before what the act would have done.

The two opaque operator roles are peers, not a hierarchy: the determination powers
and the review-correspondence powers are held by different offices and neither
office can borrow the other's. The two entity-backed roles are peers of a different
kind: their identifier IS a row, so their reach is a graph walk from the resource
back to that row, and everything outside the walk is refused rather than hidden.
"""

from prd_bench_local_runner.testing import NON_EXISTENT_UUID, validate_success

from test_helpers import api_errors, factories, fixtures
from test_helpers.assertions import (
    assert_ap_account_totals,
    assert_case_dimensions,
    assert_error_envelope,
    assert_fields_equal,
    assert_ids_in_order,
)
from test_helpers.constants import CLOCK_2026_09_01
from test_helpers.test_users import (
    ADMIN_HEADERS,
    ANALYST_HEADERS,
    NO_CREDENTIALS,
    make_alternate_payee_headers,
)
from test_helpers.types import (
    APPROACH_SEPARATE_INTEREST,
    CODE_MISSING_MODEL_LANGUAGE,
    DENIAL_ORDER_NOT_QUALIFIABLE,
    DRAFT_QUALIFIED,
    DRAFT_UNDER_REVIEW,
    EARNINGS_PERIOD_END,
    FORMULA_PERCENTAGE_OF_ACCOUNT,
    NOTICE_ISSUED,
    RECIPIENT_PARTICIPANT,
    REVIEW_UNDER_REVIEW,
    SEGREGATION_HELD,
    SOURCE_PRE_TAX_DEFERRAL,
    TEMPLATE_DETERMINATION_QUALIFIED,
)

DUTIES_PLAN = {
    "acceptable_formula_codes": [FORMULA_PERCENTAGE_OF_ACCOUNT],
    "allowed_approaches": [APPROACH_SEPARATE_INTEREST],
    "earnings_adjustment_method": EARNINGS_PERIOD_END,
    "requires_model_language": True,
    "permits_benefit_not_otherwise_available": False,
    "max_assignable_pct_bps": 5000,
    "max_assignable_amount_cents": 2000000,
}


def _clean_and_faulty_cases(client):
    """One draft that would qualify today, and one that has a deficiency to report."""
    clean = fixtures.setup_case_with_held_hold(
        client,
        "Duties Plan",
        plan_overrides=DUTIES_PLAN,
        participant_overrides={
            "full_name": "Katarina Lund",
            "ssn_last4": "6601",
            "date_of_birth": "1976-06-06",
            "participation_start_date": "2010-01-01",
        },
        case_overrides={
            "alternate_payee_name": "Anders Lund",
            "alternate_payee_dob": "1978-07-07",
            "marital_period_start": "2012-03-01",
            "marital_period_end": "2026-02-01",
        },
        draft_overrides={"document_reference": "DRO-2663-RB1"},
    )
    assert clean["draft"]["deficiency_codes"] == []
    faulty = fixtures.setup_case_with_held_hold(
        client,
        "Duties Plan B",
        clock=None,
        plan_overrides=DUTIES_PLAN,
        participant_overrides={
            "full_name": "Rurik Ahonen",
            "ssn_last4": "6602",
            "date_of_birth": "1977-08-08",
            "participation_start_date": "2010-01-01",
        },
        case_overrides={
            "alternate_payee_name": "Sirpa Ahonen",
            "alternate_payee_dob": "1979-09-09",
            "marital_period_start": "2012-03-01",
            "marital_period_end": "2026-02-01",
        },
        draft_overrides={
            "document_reference": "DRO-2663-RB2",
            "uses_model_language": False,
        },
    )
    assert faulty["draft"]["deficiency_codes"] == [CODE_MISSING_MODEL_LANGUAGE]
    return clean, faulty


def test_neither_opaque_role_may_perform_the_other_s_exclusive_acts(client):
    """Five administrator powers and two analyst powers are refused to the other office.

    PRD: "**Role authorisation.** The presented role appears among the called
    endpoint's authorised roles — otherwise `ERR_FORBIDDEN_ROLE` (403). Applies to
    every endpoint."

    Design: Corner/rbac/the_two_opaque_roles_deny_each_others_exclusive_operations_symmetrically
    """
    clean, faulty = _clean_and_faulty_cases(client)
    clean_draft_id = clean["draft"]["id"]
    faulty_draft_id = faulty["draft"]["id"]

    # The determination powers, refused to the reviewer. The first of these would
    # have succeeded on the merits, which is exactly why the role rung must speak
    # before any state, window or readiness check.
    assert_error_envelope(
        client.qualify_draft_order(clean_draft_id, ANALYST_HEADERS),
        api_errors.ERR_FORBIDDEN_ROLE,
        403,
    )
    assert_error_envelope(
        client.deny_draft_order(
            clean_draft_id,
            factories.denial_payload(DENIAL_ORDER_NOT_QUALIFIABLE),
            ANALYST_HEADERS,
        ),
        api_errors.ERR_FORBIDDEN_ROLE,
        403,
    )
    assert_error_envelope(
        client.set_current_utc(
            factories.clock_payload("2026-09-03T00:00:00Z"), ANALYST_HEADERS
        ),
        api_errors.ERR_FORBIDDEN_ROLE,
        403,
    )
    assert_error_envelope(
        client.run_segregation_sweep(ANALYST_HEADERS),
        api_errors.ERR_FORBIDDEN_ROLE,
        403,
    )
    assert_error_envelope(
        client.create_plan(
            factories.plan_payload(plan_name="Analyst Plan"), ANALYST_HEADERS
        ),
        api_errors.ERR_FORBIDDEN_ROLE,
        403,
    )

    # The asymmetry-breaking half: the administrator is not a superuser over the
    # reviewer's own two exclusives.
    assert_error_envelope(
        client.create_deficiency_notice(
            faulty_draft_id,
            factories.deficiency_notice_payload(
                reviewer_notes="administrator attempt"
            ),
            ADMIN_HEADERS,
        ),
        api_errors.ERR_FORBIDDEN_ROLE,
        403,
    )
    assert_error_envelope(
        client.create_communication(
            faulty["case"]["id"],
            factories.communication_payload(
                recipient_type=RECIPIENT_PARTICIPANT,
                template_code=TEMPLATE_DETERMINATION_QUALIFIED,
            ),
            ADMIN_HEADERS,
        ),
        api_errors.ERR_FORBIDDEN_ROLE,
        403,
    )

    # Seven refusals wrote nothing at all.
    assert fixtures.read_notices(client, faulty_draft_id) == []
    assert_fields_equal(
        fixtures.read_draft(client, clean_draft_id),
        {"status": DRAFT_UNDER_REVIEW, "revision_number": 1},
    )
    assert_case_dimensions(
        fixtures.read_case(client, clean["case"]["id"]),
        REVIEW_UNDER_REVIEW,
        SEGREGATION_HELD,
        version=2,
    )

    # Each office then performs its own exclusives on the very fixtures that
    # refused the other, so the denials were about identity and not about state.
    notice = fixtures.issue_notice(
        client, faulty_draft_id, reviewer_notes="analyst does its own job"
    )
    assert_fields_equal(
        notice,
        {
            "notice_sequence": 1,
            "status": NOTICE_ISSUED,
            "deficiency_codes": [CODE_MISSING_MODEL_LANGUAGE],
            # The refused clock call left the logical clock where it was.
            "issued_at": CLOCK_2026_09_01,
        },
    )
    determined = fixtures.qualify(client, clean_draft_id)
    assert determined["status"] == DRAFT_QUALIFIED


def _two_participants_and_one_funded_payee(client):
    """P1 with an untouched case, P2 with a qualified case and an established payee."""
    plan = fixtures.create_published_plan(
        client, plan_name="Ownership Plan", **DUTIES_PLAN
    )
    fixtures.set_clock(client, CLOCK_2026_09_01)
    people = []
    for full_name, ssn_last4, dob, payee_name, payee_dob in (
        ("Ilona Varga", "7701", "1975-01-01", "Zsolt Varga", "1977-02-02"),
        ("Nuno Peixoto", "7702", "1976-03-03", "Ines Peixoto", "1978-04-04"),
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
        people.append({"participant": participant, "case": case})

    # P2's case is carried through to a determination, which is the only way an
    # AlternatePayee identity comes into existence at all.
    second = people[1]
    draft = fixtures.receive_draft(
        client,
        second["case"]["id"],
        second["case"]["version"],
        document_reference="DRO-2663-OWN2",
    )
    fixtures.qualify(client, draft["id"])
    second["ap_account"] = fixtures.ap_account_for_case(client, second["case"]["id"])
    return people[0], second


def test_the_entity_backed_roles_reach_their_own_rows_and_nothing_else(client):
    """A participant and a payee act on their own rows and are refused on the others'.

    PRD: "**Resource ownership.** An entity-backed role's `X-User-ID` matches the
    resource reached — otherwise `ERR_NOT_RESOURCE_OWNER` (403). Applies to every
    endpoint whose authorised roles include `Participant`, `AlternatePayee`, or
    `Attorney`."

    Design: Corner/rbac/entity_backed_roles_reach_their_own_rows_and_nothing_else
    """
    first, second = _two_participants_and_one_funded_payee(client)
    p1_headers = fixtures.participant_headers(first["participant"])
    case_1, case_2 = first["case"], second["case"]

    # The participant's own case is reachable for the heaviest write the role has.
    own_draft = fixtures.receive_draft(
        client,
        case_1["id"],
        case_1["version"],
        headers=p1_headers,
        document_reference="DRO-2663-OWN",
    )
    assert own_draft["status"] == DRAFT_UNDER_REVIEW
    assert own_draft["attorney_authorization_id"] is None

    # The participant-scoped list walks draft -> case -> participant the same way.
    assert_ids_in_order(
        validate_success(
            client.list_participant_qdro_cases(
                first["participant"]["id"],
                p1_headers,
                {"review_status": REVIEW_UNDER_REVIEW},
            )
        ),
        [case_1["id"]],
    )

    # Both reads name endpoints where Participant IS an authorised role, so a role
    # error would be the wrong answer and a 404 would be the wrong answer too.
    assert_error_envelope(
        client.get_qdro_case(case_2["id"], p1_headers),
        api_errors.ERR_NOT_RESOURCE_OWNER,
        403,
    )
    assert_error_envelope(
        client.get_participant(second["participant"]["id"], p1_headers),
        api_errors.ERR_NOT_RESOURCE_OWNER,
        403,
    )

    # Filing on the other party's case is refused by the ownership walk even though
    # the supplied case version is perfectly fresh.
    assert_error_envelope(
        client.create_draft_order(
            factories.draft_order_payload(
                case_2["id"],
                fixtures.read_case(client, case_2["id"])["version"],
                document_reference="DRO-2663-FOREIGN",
            ),
            p1_headers,
        ),
        api_errors.ERR_NOT_RESOURCE_OWNER,
        403,
    )

    # The payee identity is the account id itself, so it reaches its own row.
    ap_account = second["ap_account"]
    mine = fixtures.read_ap_account(
        client, ap_account["id"], headers=fixtures.payee_headers(ap_account)
    )
    assert_ap_account_totals(mine, [], established_balance_cents=400000)
    assert mine["balance_cents"] == 400000

    # The same path read under a different payee identity is refused.
    assert_error_envelope(
        client.get_alternate_payee_account(
            ap_account["id"], make_alternate_payee_headers(NON_EXISTENT_UUID)
        ),
        api_errors.ERR_NOT_RESOURCE_OWNER,
        403,
    )

    # And the read P1 is entitled to is refused outright without credentials, one
    # rung earlier than either ownership refusal above.
    assert_error_envelope(
        client.get_qdro_case(case_1["id"], NO_CREDENTIALS),
        api_errors.ERR_UNAUTHENTICATED,
        401,
    )
