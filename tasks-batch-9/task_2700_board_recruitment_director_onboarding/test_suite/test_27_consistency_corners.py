"""Cross-cutting corners: the two version echoes, the education deadline the clock
walks onto, and the immediate visibility of every derived field."""
from prd_bench_local_runner.testing import validate_error, validate_success
from test_helpers import api_errors as E
from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as X
from test_helpers.assertions import (
    assert_committee_ledger,
    assert_fields_equal,
    assert_onboarding_rollup,
    assert_page,
)
from test_helpers.test_users import SECRETARY, STAFF

# The whole authorized board stands on the working slate, so a one or two nominee
# card never approaches the seat ceiling and only the version echo can refuse it.
SLATE_SEAT_COUNT = 9

# A slate opens at version 1; the first accepted nominee add re-derives its rollups
# and carries it to 2, and the second accepted add carries it to 3.
SLATE_VERSION_AT_CREATE = 1
SLATE_VERSION_AFTER_FIRST_ADD = 2
SLATE_VERSION_AFTER_SECOND_ADD = 3

# A committee chartered with three seats but a single minimum seat, so one active
# chair already carries it to full strength.
COMMITTEE_AUTHORIZED_SEATS = 3
COMMITTEE_MIN_SEATS = 1

# A committee opens at version 1; the first assignment proposal carries it to 2 and
# the activation of that proposal carries it to 3.
COMMITTEE_VERSION_AT_CHARTER = 1
COMMITTEE_VERSION_AFTER_FIRST_PROPOSAL = 2
COMMITTEE_VERSION_AFTER_ACTIVATION = 3

# Closed-interval committee terms: the working cycle, and a following cycle that
# shares no day with it so no overlap rule can be confused with the version echo.
TERM_START_ON = "2026-01-01"
TERM_END_ON = "2026-12-31"
LATER_TERM_START_ON = "2027-01-01"
LATER_TERM_END_ON = "2027-12-31"

# Two half-sized continuing-education modules: either one alone leaves the director
# short of the eight hours the policy requires, and both together meet it exactly.
EDUCATION_MODULE_HOURS = 4.0
EDUCATION_HOURS_AFTER_ONE_MODULE = 4.0
EDUCATION_HOURS_AFTER_BOTH_MODULES = 8.0

# The education leg is tested against 31 December of the policy's cycle year, so the
# day before the deadline is still clear and the deadline day itself is not.
DAY_BEFORE_DEADLINE = "2026-12-30T00:00:00Z"
CYCLE_DEADLINE = "2026-12-31T00:00:00Z"
EDUCATION_DUE_ON = "2026-12-31"

# One director on the board, so every clock move reports exactly one recomputation.
RECOMPUTED_DIRECTOR_COUNT = 1

# The single required orientation module behind the immediate-visibility walk, and
# the chair term that opens on the default clock date.
ORIENTATION_MODULE_CODE = "BUSINESS_ORIENTATION_101"
ORIENTATION_CREDIT_HOURS = 2.0
ORIENTATION_DUE_ON = "2026-09-30"
CHAIR_TERM_START_ON = "2026-08-01"
CHAIR_TERM_END_ON = "2026-12-31"


def _incumbents(client):
    """A governing policy plus three SEATED independent directors to renominate."""
    X.adopt_policy(client)
    return [
        X.new_seated_director(
            client,
            full_name=name,
            email=email,
            birth_date=birth_date,
            appointed_on="2021-01-01",
            is_independent=True,
        )
        for name, email, birth_date in (
            ("Ada One", "ada@issuer.example", "1968-01-01"),
            ("Ben Two", "ben@issuer.example", "1969-01-01"),
            ("Cai Three", "cai@issuer.example", "1970-01-01"),
        )
    ]


def _slate_carrying_one_incumbent(client):
    """A DRAFT slate whose first nominee has already consumed the create-time version."""
    directors = _incumbents(client)
    slate = X.new_slate(client, cycle_year=C.CYCLE_YEAR, seat_count=SLATE_SEAT_COUNT)
    X.add_nominee(
        client,
        slate["id"],
        SLATE_VERSION_AT_CREATE,
        1,
        incumbent_director_id=directors[0]["id"],
    )
    return slate, directors


def _committee_carrying_one_proposal(client):
    """An AUDIT committee whose CHAIR proposal has consumed the charter-time version."""
    directors = _incumbents(client)
    committee = X.new_committee(
        client,
        code="AUDIT",
        name="Audit Committee",
        authorized_seats=COMMITTEE_AUTHORIZED_SEATS,
        min_seats=COMMITTEE_MIN_SEATS,
    )
    assignment = validate_success(
        client.create_assignment(
            committee["id"],
            F.assignment_payload(
                directors[0]["id"],
                COMMITTEE_VERSION_AT_CHARTER,
                seat_role="CHAIR",
                term_start_on=TERM_START_ON,
                term_end_on=TERM_END_ON,
            ),
            SECRETARY,
        ),
        201,
    )
    return committee, directors, assignment


def _director_with_two_education_modules(client):
    """One SEATED director holding two optional modules, the first already completed."""
    X.adopt_policy(client)
    director = X.new_seated_director(
        client,
        full_name="Edda Ucation",
        email="edda@issuer.example",
        birth_date="1968-01-01",
        appointed_on="2021-01-01",
    )
    modules = [
        X.new_onboarding_item(
            client,
            director["id"],
            module_code=module_code,
            category="CONTINUING_EDUCATION",
            is_required=False,
            credit_hours=EDUCATION_MODULE_HOURS,
            due_on=EDUCATION_DUE_ON,
        )
        for module_code in ("CE_AUDIT_TRENDS_2026", "CE_CYBER_BRIEFING_2026")
    ]
    X.complete_item(client, modules[0]["id"], STAFF)
    return director, modules


def test_replaying_a_consumed_slate_version_is_refused_and_writes_no_nominee(client):
    """The first accepted add consumed version 1, so a second add echoing 1 is refused
    on the version comparison alone even though seats and the fee budget are free.

    PRD: "The server compares `expected_slate_version` to the slate's current `version` and to nothing else."

    Design: Corner/cross_cutting_complexity_layers/a_stale_expected_slate_version_is_refused_with_412_and_the_fresh_one_succeeds
    """
    slate, directors = _slate_carrying_one_incumbent(client)

    replayed = client.add_slate_nominee(
        slate["id"],
        F.nominee_payload(
            SLATE_VERSION_AT_CREATE, 2, incumbent_director_id=directors[1]["id"]
        ),
        STAFF,
    )

    validate_error(replayed, E.ERR_STALE_SLATE_VERSION, 412)
    assert_fields_equal(
        X.get_slate(client, slate["id"]),
        {"nominee_count": 1, "version": SLATE_VERSION_AFTER_FIRST_ADD},
    )
    assert_page(client.list_slate_nominees(STAFF), expected_total=1)


def test_the_same_nominee_add_lands_once_it_echoes_the_freshly_read_version(client):
    """Re-reading the slate and sending the version it now reports accepts the identical
    nominee, and that accepted write increments the version once more in turn.

    PRD: "Recomputation of a derived field counts as a mutation: when a nominee is added and the owning slate's `nominee_count` and `independent_nominee_pct` are re-derived, that slate's `updated_at` is refreshed and its `version` is incremented."

    Design: Corner/cross_cutting_complexity_layers/a_stale_expected_slate_version_is_refused_with_412_and_the_fresh_one_succeeds
    """
    slate, directors = _slate_carrying_one_incumbent(client)

    fresh_version = X.slate_version(client, slate["id"])
    retried = validate_success(
        client.add_slate_nominee(
            slate["id"],
            F.nominee_payload(fresh_version, 2, incumbent_director_id=directors[1]["id"]),
            STAFF,
        ),
        201,
    )

    assert fresh_version == SLATE_VERSION_AFTER_FIRST_ADD, fresh_version
    assert_fields_equal(retried, {"status": "PROPOSED", "ballot_order": 2})
    assert_fields_equal(
        X.get_slate(client, slate["id"]),
        {"nominee_count": 2, "version": SLATE_VERSION_AFTER_SECOND_ADD},
    )


def test_a_committee_proposal_built_on_a_consumed_version_is_refused(client):
    """Proposing the first assignment moved the committee's version on, so a second
    proposal echoing the charter version is refused while seats are still free.

    PRD: "The server compares `expected_committee_version` to the committee's current `version` and to nothing else; a mismatch is refused with `ERR_STALE_COMMITTEE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/a_stale_expected_committee_version_is_refused_with_412
    """
    committee, directors, _first = _committee_carrying_one_proposal(client)

    stale = client.create_assignment(
        committee["id"],
        F.assignment_payload(
            directors[1]["id"],
            COMMITTEE_VERSION_AT_CHARTER,
            seat_role="MEMBER",
            term_start_on=TERM_START_ON,
            term_end_on=TERM_END_ON,
        ),
        SECRETARY,
    )

    validate_error(stale, E.ERR_STALE_COMMITTEE_VERSION, 412)
    assert_page(client.list_assignments(SECRETARY), expected_total=1)

    fresh_version = X.committee_version(client, committee["id"])
    assert fresh_version == COMMITTEE_VERSION_AFTER_FIRST_PROPOSAL, fresh_version
    corrected = validate_success(
        client.create_assignment(
            committee["id"],
            F.assignment_payload(
                directors[1]["id"],
                fresh_version,
                seat_role="MEMBER",
                term_start_on=TERM_START_ON,
                term_end_on=TERM_END_ON,
            ),
            SECRETARY,
        ),
        201,
    )
    assert_fields_equal(corrected, {"status": "PROPOSED", "seat_role": "MEMBER"})


def test_activating_an_assignment_also_moves_the_committee_version_on(client):
    """Activation is not version-guarded itself but it does mutate the committee, so a
    proposal echoing the version read before the activation is refused afterwards.

    PRD: "Both operations increment the committee's `version` by 1, and either operation attempted on an assignment that is already `ENDED` or `REVOKED` is refused with `ERR_ASSIGNMENT_STATE_INVALID`."

    Design: Corner/cross_cutting_complexity_layers/a_stale_expected_committee_version_is_refused_with_412
    """
    committee, directors, first = _committee_carrying_one_proposal(client)

    activated = X.activate_assignment(client, first["id"])
    stale_after_activation = client.create_assignment(
        committee["id"],
        F.assignment_payload(
            directors[0]["id"],
            COMMITTEE_VERSION_AFTER_FIRST_PROPOSAL,
            seat_role="MEMBER",
            term_start_on=LATER_TERM_START_ON,
            term_end_on=LATER_TERM_END_ON,
        ),
        SECRETARY,
    )

    assert_fields_equal(activated, {"status": "ACTIVE"})
    assert_committee_ledger(X.get_committee(client, committee["id"]), 1, "AT_STRENGTH")
    validate_error(stale_after_activation, E.ERR_STALE_COMMITTEE_VERSION, 412)
    assert_fields_equal(
        X.get_committee(client, committee["id"]),
        {"version": COMMITTEE_VERSION_AFTER_ACTIVATION},
    )


def test_the_education_posture_turns_on_the_deadline_date_and_not_a_day_earlier(client):
    """The same four completed hours read as compliant on 30 December and delinquent on
    31 December, because only the clock's arrival at the deadline engages the leg.

    PRD: "which is the only way an `EDUCATION_DELINQUENT` posture becomes reachable: the education deadline is a date, and the date only arrives when the clock is moved"

    Design: Corner/cross_cutting_complexity_layers/the_continuing_education_threshold_flips_exactly_on_the_cycle_deadline
    """
    director, _modules = _director_with_two_education_modules(client)

    day_before = X.set_clock(client, DAY_BEFORE_DEADLINE)
    before_deadline = X.get_director(client, director["id"])
    deadline_day = X.set_clock(client, CYCLE_DEADLINE)
    on_deadline = X.get_director(client, director["id"])

    assert_fields_equal(
        before_deadline,
        {
            "education_hours_cycle": EDUCATION_HOURS_AFTER_ONE_MODULE,
            "compliance_status": "COMPLIANT",
        },
    )
    assert_fields_equal(
        on_deadline,
        {
            "education_hours_cycle": EDUCATION_HOURS_AFTER_ONE_MODULE,
            "compliance_status": "EDUCATION_DELINQUENT",
        },
    )
    assert_fields_equal(
        day_before, {"recomputed_director_count": RECOMPUTED_DIRECTOR_COUNT}
    )
    assert_fields_equal(
        deadline_day, {"recomputed_director_count": RECOMPUTED_DIRECTOR_COUNT}
    )


def test_the_second_module_clears_the_delinquent_posture_at_exactly_the_requirement(client):
    """Completing the remaining module brings the cycle total to exactly the eight hours
    required, and the strictly-less-than test therefore no longer fails.

    PRD: "Completing a continuing-education item that brings `education_hours_cycle` up to the requirement clears the posture back to `COMPLIANT`, provided the overboarding and ownership legs both pass."

    Design: Corner/cross_cutting_complexity_layers/the_continuing_education_threshold_flips_exactly_on_the_cycle_deadline
    """
    director, modules = _director_with_two_education_modules(client)
    X.set_clock(client, CYCLE_DEADLINE)
    assert (
        X.get_director(client, director["id"])["compliance_status"]
        == "EDUCATION_DELINQUENT"
    )

    X.complete_item(client, modules[1]["id"], STAFF)

    cleared = X.get_director(client, director["id"])
    assert_fields_equal(
        cleared,
        {
            "education_hours_cycle": EDUCATION_HOURS_AFTER_BOTH_MODULES,
            "compliance_status": "COMPLIANT",
        },
    )
    # Both modules are optional, so the required denominator is zero throughout.
    assert_onboarding_rollup(cleared, "NOT_STARTED", 0.00)


def test_derived_fields_are_visible_in_the_same_request_that_changes_them(client):
    """Each write's own response body already carries the recomputed state, and the read
    that follows it needs no retry to see the seat ledger the activation moved.

    PRD: "The server performs those changes itself, immediately, within the same request"

    Design: Corner/consistency_model/derived_fields_are_visible_in_the_same_request_that_changes_them
    """
    X.adopt_policy(client)
    director = X.new_onboarding_director(
        client,
        full_name="Vera Visible",
        email="vera@issuer.example",
        birth_date="1972-01-01",
        appointed_on="2026-07-01",
        is_independent=True,
    )
    item = X.new_onboarding_item(
        client,
        director["id"],
        module_code=ORIENTATION_MODULE_CODE,
        category="BUSINESS_ORIENTATION",
        is_required=True,
        credit_hours=ORIENTATION_CREDIT_HOURS,
        due_on=ORIENTATION_DUE_ON,
    )
    committee = X.new_committee(
        client,
        code="AUDIT",
        name="Audit Committee",
        authorized_seats=COMMITTEE_AUTHORIZED_SEATS,
        min_seats=COMMITTEE_MIN_SEATS,
    )
    assignment = validate_success(
        client.create_assignment(
            committee["id"],
            F.assignment_payload(
                director["id"],
                COMMITTEE_VERSION_AT_CHARTER,
                seat_role="CHAIR",
                term_start_on=CHAIR_TERM_START_ON,
                term_end_on=CHAIR_TERM_END_ON,
            ),
            SECRETARY,
        ),
        201,
    )

    validate_success(client.complete_onboarding_item(item["id"], STAFF), 200)
    after_completion = X.get_director(client, director["id"])
    seated = X.seat_director(client, director["id"])
    activated = X.activate_assignment(client, assignment["id"])
    after_activation = X.get_committee(client, committee["id"])

    assert_onboarding_rollup(after_completion, "COMPLETE", 100.00)
    assert_fields_equal(seated, {"service_status": "SEATED"})
    assert_fields_equal(
        activated, {"status": "ACTIVE", "activated_at": C.CLOCK_DEFAULT}
    )
    assert_committee_ledger(after_activation, 1, "AT_STRENGTH")
    assert_fields_equal(
        after_activation, {"version": COMMITTEE_VERSION_AFTER_ACTIVATION}
    )
