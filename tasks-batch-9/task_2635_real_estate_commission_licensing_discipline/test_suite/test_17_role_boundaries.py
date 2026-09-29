"""Who may act, whose record it is, and which seat the identity was recorded in."""

import pytest

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import factories, fixtures
from test_helpers.api_errors import (
    ERR_AUDITOR_MISMATCH,
    ERR_FORBIDDEN_ROLE,
    ERR_INVALID_STATE,
    ERR_NOT_RESOURCE_OWNER,
    ERR_PANEL_CHAIR_MISMATCH,
    ERR_UNAUTHENTICATED,
)
from test_helpers.constants import CLOCK_STARTUP_DEFAULT
from test_helpers.test_users import (
    MISSING_ROLE_HEADERS,
    MISSING_USER_ID_HEADERS,
    UNKNOWN_ROLE_HEADERS,
    make_analyst_headers,
    make_auditor_headers,
    make_chair_headers,
    make_counsel_headers,
    make_provider_admin_headers,
    make_public_headers,
    make_respondent_headers,
    make_salesperson_headers,
    make_trustee_headers,
)

NO_HEADERS: dict = {}
APPLICANT_NAME = "Nia Alder"


class TestAnUnauthenticatedCallIsRefusedBeforeAnythingElseIsLookedAt:
    """Three header defects, one error, and no path resolution in between."""

    @pytest.mark.parametrize(
        "label, headers",
        [
            ("no headers at all", NO_HEADERS),
            ("an undeclared role name", UNKNOWN_ROLE_HEADERS),
            ("a declared role with no user id", MISSING_USER_ID_HEADERS),
            ("a user id with no role", MISSING_ROLE_HEADERS),
        ],
    )
    def test_every_header_defect_collapses_to_the_same_401(self, client, label, headers):
        """An unrecognised role fails authentication before the roles list is consulted.

        The PRD says "Every request — reads included — must carry two headers:
        `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the
        capacity in which that user acts. If either header is absent, or if
        `X-User-Role` is not one of the ten role names below, the request is
        rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/rbac/a_call_missing_x_user_headers_is_unauthenticated_before_any_path_id_resolves
        """
        validate_error(
            client.create_licensee(
                factories.licensee_payload("SALESPERSON", APPLICANT_NAME), headers
            ),
            ERR_UNAUTHENTICATED,
            expected_status=401,
        )

        _rows, meta = validate_paginated(client.list_licensees(make_analyst_headers()))
        assert meta["total_count"] == 0, f"the refusal for {label} created a row"

    def test_an_anonymous_read_of_an_unknown_id_answers_401_and_not_404(self, client):
        """Rung 1 outranks path resolution, so existence is never leaked.

        The PRD says "1. **Header presence and role recognition** —
        `ERR_UNAUTHENTICATED`, on every endpoint."

        The PRD says "4. **Path identifier resolution**, left to right — the
        entity-specific 404 of §2.6."

        Design: Corner/rbac/a_call_missing_x_user_headers_is_unauthenticated_before_any_path_id_resolves
        """
        validate_error(
            client.get_licensee(NON_EXISTENT_UUID, NO_HEADERS),
            ERR_UNAUTHENTICATED,
            expected_status=401,
        )

    def test_the_same_body_with_both_headers_present_is_accepted(self, client):
        """All four refusals were header defects and nothing about the request.

        The PRD says "An applicant enters the system when a `LicensingAnalyst`
        opens a licence application, supplying the class of licence applied for as
        `person_type` (either `SALESPERSON` or `BROKER`), the applicant's legal name
        as `full_name`, and the classroom pre-licence education hours claimed at
        application as `prelicense_hours`, which may be 0 but never negative."

        Design: Corner/rbac/a_call_missing_x_user_headers_is_unauthenticated_before_any_path_id_resolves
        """
        validate_error(
            client.create_licensee(
                factories.licensee_payload("SALESPERSON", APPLICANT_NAME), NO_HEADERS
            ),
            ERR_UNAUTHENTICATED,
        )

        created = validate_success(
            client.create_licensee(
                factories.licensee_payload("SALESPERSON", APPLICANT_NAME), make_analyst_headers()
            ),
            expected_status=201,
        )
        assert created["full_name"] == APPLICANT_NAME
        assert created["license_status"] == "APPLICANT"

        _rows, meta = validate_paginated(client.list_licensees(make_analyst_headers()))
        assert meta["total_count"] == 1


FIRM_NAME = "Harbor Realty Group"
BROKER_NAME = "Dana Broker"
SALESPERSON_NAME = "Sam Reed"
SCREENER = "counsel-05"
COMPLAINANT = "Ora Buyer"
ALLEGED_LOSS_CENTS = 300000
AMENDED_LOSS_CENTS = 400000
APPROPRIATION_CENTS = 750000


def _firm_with_one_agent(client):
    """A live firm, its self-supervising broker, and one active salesperson."""
    firm = fixtures.bootstrap_active_brokerage(
        client,
        name=FIRM_NAME,
        broker_name=BROKER_NAME,
        trust_account_required=False,
        open_escrow=False,
    )
    agent = fixtures.affiliate_new_salesperson(
        client, firm["brokerage"]["id"], firm["broker"]["id"], SALESPERSON_NAME
    )
    return {"firm": firm, "agent": agent}


class TestAnExclusiveOperationOfANeighbouringRoleIsRefusedAtRungTwo:
    """The commission-side roles are peers: none of them is a super-role."""

    def test_a_shared_intake_succeeds_for_public_while_an_exclusive_create_is_refused(
        self, client
    ):
        """Complaint intake is shared; opening a licence application is not.

        The PRD says "If the role is recognised but is not among the roles
        authorised for the requested operation (see the table in §4), the request is
        rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

        Design: Corner/rbac/an_exclusive_operation_of_a_neighbouring_role_is_refused_at_priority_two
        """
        world = _firm_with_one_agent(client)

        filed = validate_success(
            client.create_complaint(
                factories.complaint_payload(
                    world["agent"]["id"], "MISREPRESENTATION", ALLEGED_LOSS_CENTS, COMPLAINANT
                ),
                make_public_headers(),
            ),
            expected_status=201,
        )
        assert filed["status"] == "SUBMITTED"

        validate_error(
            client.create_licensee(
                factories.licensee_payload("SALESPERSON", "Wilder Vance"), make_auditor_headers()
            ),
            ERR_FORBIDDEN_ROLE,
            expected_status=403,
        )
        _rows, meta = validate_paginated(client.list_licensees(make_analyst_headers()))
        assert meta["total_count"] == 2, "the refused create left the register alone"

    def test_the_trustee_may_not_dispose_of_a_complaint_that_counsel_then_disposes(
        self, client
    ):
        """The identical body that a peer is refused for succeeds for its owner.

        The PRD says "2. **Role authorisation for the operation** —
        `ERR_FORBIDDEN_ROLE`, on every endpoint."

        Design: Corner/rbac/an_exclusive_operation_of_a_neighbouring_role_is_refused_at_priority_two
        """
        world = _firm_with_one_agent(client)
        complaint = fixtures.file_complaint(
            client, world["agent"]["id"], "MISREPRESENTATION", ALLEGED_LOSS_CENTS, COMPLAINANT
        )
        body = factories.complaint_disposition_payload("INVESTIGATE", investigator_user_id=SCREENER)

        validate_error(
            client.complaint_disposition(complaint["id"], body, make_trustee_headers()),
            ERR_FORBIDDEN_ROLE,
            expected_status=403,
        )
        assert fixtures.read_complaint(client, complaint["id"])["status"] == "SUBMITTED"

        screened = validate_success(
            client.complaint_disposition(complaint["id"], body, make_counsel_headers(SCREENER))
        )
        assert screened["status"] == "INVESTIGATION"
        assert screened["investigator_user_id"] == SCREENER

    def test_the_exclusion_runs_the_other_way_on_the_recovery_fund(self, client):
        """Counsel cannot appropriate; the trustee's identical body can.

        The PRD says "A `RecoveryFundTrustee` administers the fund: crediting
        appropriations and running the award waterfall are theirs exclusively, and
        they may also file recovery claims and read the fund, claims, orders and
        licensees."

        Design: Corner/rbac/an_exclusive_operation_of_a_neighbouring_role_is_refused_at_priority_two
        """
        _firm_with_one_agent(client)
        body = factories.appropriation_payload(APPROPRIATION_CENTS)

        validate_error(
            client.create_appropriation(body, make_counsel_headers()),
            ERR_FORBIDDEN_ROLE,
            expected_status=403,
        )
        assert fixtures.read_fund(client)["appropriated_cents"] == 0

        credited = validate_success(
            client.create_appropriation(body, make_trustee_headers())
        )
        assert credited["appropriated_cents"] == APPROPRIATION_CENTS

    def test_counsel_owns_the_disposition_channel_and_the_public_owns_the_amendment(
        self, client
    ):
        """Two adjacent channels on one complaint, each closed to the other's role.

        The PRD says "`Public` is the unauthenticated-equivalent external actor:
        complaint intake, complaint amendment, recovery-claim filing and public
        reads."

        Design: Corner/rbac/an_exclusive_operation_of_a_neighbouring_role_is_refused_at_priority_two
        """
        world = _firm_with_one_agent(client)
        complaint = fixtures.file_complaint(
            client, world["agent"]["id"], "MISREPRESENTATION", ALLEGED_LOSS_CENTS, COMPLAINANT
        )
        fixtures.dispose_complaint(
            client, complaint["id"], "INVESTIGATE", counsel_user_id=SCREENER
        )
        paused = fixtures.dispose_complaint(
            client, complaint["id"], "REQUEST_AMENDMENT", counsel_user_id=SCREENER
        )
        assert paused["status"] == "AMENDMENT_REQUESTED"
        body = factories.amendment_payload(
            "The buyer's revised statement raises the loss.",
            amended_alleged_loss_cents=AMENDED_LOSS_CENTS,
        )

        validate_error(
            client.create_amendment(complaint["id"], body, make_counsel_headers(SCREENER)),
            ERR_FORBIDDEN_ROLE,
            expected_status=403,
        )
        assert fixtures.read_complaint(client, complaint["id"])["amendment_count"] == 0

        amended = validate_success(
            client.create_amendment(complaint["id"], body, make_public_headers())
        )
        assert amended["status"] == "INVESTIGATION"
        assert amended["amendment_count"] == 1
        assert amended["alleged_loss_cents"] == AMENDED_LOSS_CENTS


SECOND_AGENT_NAME = "Rae Nunez"
PROVIDER_NAME = "Summit Education"
OWNING_ADMIN = "prov-admin-01"
FOREIGN_ADMIN = "prov-admin-02"
FINE_CENTS = 500000
INSTALMENT_CENTS = 100000


def _two_agents_a_fine_and_an_owned_school(client):
    """One fined salesperson, one bystander, and a provider owned by one admin."""
    firm = fixtures.bootstrap_active_brokerage(
        client,
        name=FIRM_NAME,
        broker_name=BROKER_NAME,
        trust_account_required=False,
        open_escrow=False,
    )
    brokerage_id = firm["brokerage"]["id"]
    broker_id = firm["broker"]["id"]
    sam = fixtures.affiliate_new_salesperson(client, brokerage_id, broker_id, SALESPERSON_NAME)
    rae = fixtures.affiliate_new_salesperson(client, brokerage_id, broker_id, SECOND_AGENT_NAME)

    complaint = fixtures.complaint_at_probable_cause(
        client, sam["id"], "MISREPRESENTATION", ALLEGED_LOSS_CENTS
    )
    order = fixtures.issue_order_by_consent(
        client, complaint["id"], sam["id"], "FINE", FINE_CENTS, 0
    )
    assert order["status"] == "ISSUED"
    assert fixtures.read_licensee(client, sam["id"])["discipline_status"] == "SANCTIONED"

    provider = fixtures.approve_provider(
        client, fixtures.register_provider(client, PROVIDER_NAME, OWNING_ADMIN)["id"]
    )
    assert provider["status"] == "APPROVED"
    assert provider["admin_user_id"] == OWNING_ADMIN

    return {"sam": sam, "rae": rae, "order": order, "provider": provider}


class TestAnEntityBackedRoleMayNotActOnAnotherPersonsRecord:
    """Rung 6 sits below rung 2, so the two refusals stay distinguishable."""

    def test_the_two_refusals_a_salesperson_can_earn_are_different_errors(self, client):
        """Off the roles list is rung 2; on the list but not the owner is rung 6.

        The PRD says "When `X-User-Role` is `Salesperson`, `X-User-ID` is likewise
        the `id` of the acting `Licensee`, and the same ownership comparison
        applies."

        The PRD says "6. **Entity-backed ownership** — `ERR_NOT_RESOURCE_OWNER`, on
        licence status changes, respondent consent responses, fine payments,
        instructor enrolment and course-completion reporting."

        Design: Corner/rbac/an_entity_backed_role_may_not_act_on_another_persons_record
        """
        world = _two_agents_a_fine_and_an_owned_school(client)
        sam_headers = make_salesperson_headers(world["sam"]["id"])

        validate_error(
            client.create_licensee(
                factories.licensee_payload("SALESPERSON", "Wilder Vance"), sam_headers
            ),
            ERR_FORBIDDEN_ROLE,
            expected_status=403,
        )

        validate_error(
            client.create_status_change(
                world["rae"]["id"], factories.status_change_payload("GO_INACTIVE"), sam_headers
            ),
            ERR_NOT_RESOURCE_OWNER,
            expected_status=403,
        )
        assert fixtures.read_licensee(client, world["rae"]["id"])["license_status"] == "ACTIVE"

    def test_ownership_of_a_fine_payment_is_resolved_through_the_order(self, client):
        """The path names the order, so the owner is read from its respondent link.

        The PRD says "When `X-User-Role` is `Respondent`, `X-User-ID` is the `id` of
        the acting `Licensee`; for a consent agreement the server compares it to the
        `respondent_licensee_id` of the agreement's parent complaint, and for a fine
        payment it compares it to the order's `respondent_licensee_id`."

        Design: Corner/rbac/an_entity_backed_role_may_not_act_on_another_persons_record
        """
        world = _two_agents_a_fine_and_an_owned_school(client)
        order_id = world["order"]["id"]
        body = factories.fine_payment_payload(INSTALMENT_CENTS, "2026-08-15")

        validate_error(
            client.create_fine_payment(
                order_id, body, make_respondent_headers(world["rae"]["id"])
            ),
            ERR_NOT_RESOURCE_OWNER,
            expected_status=403,
        )
        assert fixtures.read_sanction_order(client, order_id)["fine_paid_cents"] == 0

        paid = validate_success(
            client.create_fine_payment(
                order_id, body, make_respondent_headers(world["sam"]["id"])
            )
        )
        assert paid["fine_paid_cents"] == INSTALMENT_CENTS
        assert paid["status"] == "ISSUED"

    def test_ownership_of_an_enrolment_is_resolved_from_the_stored_admin_id(self, client):
        """A stranger's admin id does not match, and the owner's identical body does.

        The PRD says "When `X-User-Role` is `ProviderAdmin`, `X-User-ID` is the
        identifier recorded as `admin_user_id` on the acting `EducationProvider`;
        ownership checks compare that provider's `admin_user_id` to `X-User-ID` —
        for instructor enrolment the provider named by the path segment, and for a
        course completion the provider named by `education_provider_id` in the body."

        Design: Corner/rbac/an_entity_backed_role_may_not_act_on_another_persons_record
        """
        world = _two_agents_a_fine_and_an_owned_school(client)
        provider_id = world["provider"]["id"]
        body = factories.instructor_payload("Tia Teach", "SUBJECT_EXPERT")

        validate_error(
            client.create_instructor(
                provider_id, body, make_provider_admin_headers(FOREIGN_ADMIN)
            ),
            ERR_NOT_RESOURCE_OWNER,
            expected_status=403,
        )

        enrolled = validate_success(
            client.create_instructor(
                provider_id, body, make_provider_admin_headers(OWNING_ADMIN)
            ),
            expected_status=201,
        )
        assert enrolled["status"] == "PENDING"
        assert enrolled["education_provider_id"] == provider_id

    def test_a_sanctioned_licensee_may_still_park_their_own_licence(self, client):
        """Ownership is satisfied on one's own record, whatever the discipline column says.

        The PRD says "A `Salesperson` or `Broker` may invoke it for themselves only,
        so an entity-backed actor whose `X-User-ID` is not the licensee named in the
        path is refused with `ERR_NOT_RESOURCE_OWNER`; a `LicensingAnalyst` may
        invoke it on anyone's behalf."

        Design: Corner/rbac/an_entity_backed_role_may_not_act_on_another_persons_record
        """
        world = _two_agents_a_fine_and_an_owned_school(client)

        parked = validate_success(
            client.create_status_change(
                world["sam"]["id"],
                factories.status_change_payload("GO_INACTIVE"),
                make_salesperson_headers(world["sam"]["id"]),
            )
        )
        assert parked["license_status"] == "INACTIVE"
        assert parked["discipline_status"] == "SANCTIONED"
        assert parked["inactive_since"] == CLOCK_STARTUP_DEFAULT

        assert fixtures.read_licensee(client, world["rae"]["id"])["license_status"] == "ACTIVE"


ASSIGNED_AUDITOR = "auditor-31"
UNRELATED_AUDITOR = "auditor-32"
AS_OF_DATE = "2026-08-31"
FIELDWORK_START = "2026-08-01T00:00:00Z"
FIELDWORK_END = "2026-08-01T17:00:00Z"
OBLIGATION_CENTS = 1000000
DEPOSIT_CENTS = 800000
SHORTAGE_CENTS = 200000


def _scheduled_audit_over_a_short_account(client):
    """A BOOK audit assigned to one auditor over an account 200,000 cents short."""
    firm = fixtures.bootstrap_active_brokerage(
        client, name=FIRM_NAME, broker_name=BROKER_NAME
    )
    account_id = firm["account"]["id"]
    fixtures.append_ledger_entry(
        client, account_id, "OBLIGATION_OPENED", OBLIGATION_CENTS, "2026-08-01", "OBL-1"
    )
    fixtures.append_ledger_entry(
        client, account_id, "DEPOSIT", DEPOSIT_CENTS, "2026-08-01", "DEP-1",
        cleared_date="2026-08-01",
    )
    audit = fixtures.schedule_audit(
        client, account_id, ASSIGNED_AUDITOR, "BOOK", AS_OF_DATE, FIELDWORK_START, FIELDWORK_END
    )
    assert audit["status"] == "SCHEDULED"
    assert audit["auditor_user_id"] == ASSIGNED_AUDITOR
    return {"firm": firm, "account_id": account_id, "audit_id": audit["id"]}


class TestOnlyTheAssignedAuditorMayDriveTheAuditLifecycle:
    """The wrong role and the wrong auditor are two errors, not one."""

    def test_the_scheduling_analyst_is_off_the_fieldwork_roles_list_entirely(self, client):
        """Scheduling the audit grants no power to work it.

        The PRD says "2. **Role authorisation for the operation** —
        `ERR_FORBIDDEN_ROLE`, on every endpoint."

        Design: Corner/rbac/only_the_assigned_auditor_may_drive_the_audit_lifecycle
        """
        world = _scheduled_audit_over_a_short_account(client)

        validate_error(
            client.open_fieldwork(
                world["audit_id"], factories.fieldwork_payload(), make_analyst_headers()
            ),
            ERR_FORBIDDEN_ROLE,
            expected_status=403,
        )
        assert fixtures.read_audit(client, world["audit_id"])["status"] == "SCHEDULED"

    def test_the_right_role_with_the_wrong_identity_is_an_auditor_mismatch(self, client):
        """A genuine auditor who is not this audit's auditor is refused at rung 7.

        The PRD says "Two of those recorded identifiers gate later access rather
        than merely documenting history: only the exact user whose id equals a
        `TrustAudit`'s `auditor_user_id` may perform that audit's fieldwork or any of
        its dispositions — anyone else, including another `TrustAuditor`, is refused
        with `ERR_AUDITOR_MISMATCH` (HTTP 403) — and only the user whose id equals a
        `Hearing`'s `panel_chair_user_id` may dispose of that hearing, with
        `ERR_PANEL_CHAIR_MISMATCH` (HTTP 403) for anyone else."

        Design: Corner/rbac/only_the_assigned_auditor_may_drive_the_audit_lifecycle
        """
        world = _scheduled_audit_over_a_short_account(client)
        body = factories.fieldwork_payload()

        validate_error(
            client.open_fieldwork(world["audit_id"], body, make_auditor_headers(UNRELATED_AUDITOR)),
            ERR_AUDITOR_MISMATCH,
            expected_status=403,
        )
        assert fixtures.read_audit(client, world["audit_id"])["status"] == "SCHEDULED"

        opened = validate_success(
            client.open_fieldwork(world["audit_id"], body, make_auditor_headers(ASSIGNED_AUDITOR))
        )
        assert opened["status"] == "FIELDWORK"
        assert opened["computed_shortage_cents"] == SHORTAGE_CENTS

    def test_the_identity_check_answers_before_the_from_state_check(self, client):
        """On a SCHEDULED audit the stranger gets the mismatch, the owner gets the state error.

        The PRD says "Only the audit's own auditor may act, on pain of
        `ERR_AUDITOR_MISMATCH`, and every action requires the audit to be in the
        state that action departs from, on pain of `ERR_INVALID_STATE`."

        Design: Corner/rbac/only_the_assigned_auditor_may_drive_the_audit_lifecycle
        """
        world = _scheduled_audit_over_a_short_account(client)
        body = factories.audit_disposition_payload("ISSUE_FINDINGS", remediation_days=3)

        validate_error(
            client.audit_disposition(
                world["audit_id"], body, make_auditor_headers(UNRELATED_AUDITOR)
            ),
            ERR_AUDITOR_MISMATCH,
            expected_status=403,
        )
        validate_error(
            client.audit_disposition(
                world["audit_id"], body, make_auditor_headers(ASSIGNED_AUDITOR)
            ),
            ERR_INVALID_STATE,
            expected_status=409,
        )
        assert fixtures.read_audit(client, world["audit_id"])["status"] == "SCHEDULED"
        assert fixtures.read_trust_account(client, world["account_id"])["status"] == "OPEN"

    def test_the_cascade_belongs_to_the_assigned_auditors_successful_call_only(self, client):
        """The stranger's identical disposition moves nothing; the owner's moves everything.

        The PRD says "Second, the account moves `OPEN → RESTRICTED`, barring further
        disbursements."

        Design: Corner/rbac/only_the_assigned_auditor_may_drive_the_audit_lifecycle
        """
        world = _scheduled_audit_over_a_short_account(client)
        fixtures.start_fieldwork(client, world["audit_id"], ASSIGNED_AUDITOR)
        body = factories.audit_disposition_payload("ISSUE_FINDINGS", remediation_days=3)

        validate_error(
            client.audit_disposition(
                world["audit_id"], body, make_auditor_headers(UNRELATED_AUDITOR)
            ),
            ERR_AUDITOR_MISMATCH,
        )
        assert fixtures.read_audit(client, world["audit_id"])["status"] == "FIELDWORK"
        assert fixtures.read_trust_account(client, world["account_id"])["status"] == "OPEN"

        ordered = validate_success(
            client.audit_disposition(
                world["audit_id"], body, make_auditor_headers(ASSIGNED_AUDITOR)
            )
        )
        assert ordered["status"] == "REMEDIATION_ORDERED"
        assert ordered["remediation_round"] == 1
        assert fixtures.read_trust_account(client, world["account_id"])["status"] == "RESTRICTED"


SEATED_CHAIR = "chair-11"
UNSEATED_CHAIR = "chair-12"
HEARING_ROOM = "HR-1"
HEARING_START = CLOCK_STARTUP_DEFAULT
HEARING_END = "2026-08-01T02:00:00Z"
HEARING_FINE_CENTS = 400000


def _hearing_seated_at_the_current_instant(client):
    """A hearing whose slot has just opened, chaired by one named user."""
    firm = fixtures.bootstrap_active_brokerage(
        client,
        name=FIRM_NAME,
        broker_name=BROKER_NAME,
        trust_account_required=False,
        open_escrow=False,
    )
    sam = fixtures.affiliate_new_salesperson(
        client, firm["brokerage"]["id"], firm["broker"]["id"], SALESPERSON_NAME
    )
    complaint = fixtures.complaint_at_probable_cause(
        client, sam["id"], "MISREPRESENTATION", ALLEGED_LOSS_CENTS, investigator_user_id=SCREENER
    )
    hearing = fixtures.schedule_hearing(
        client,
        complaint["id"],
        SEATED_CHAIR,
        scheduled_start_at=HEARING_START,
        scheduled_end_at=HEARING_END,
        hearing_room=HEARING_ROOM,
        counsel_user_id=SCREENER,
    )
    assert hearing["status"] == "SCHEDULED"
    assert hearing["panel_chair_user_id"] == SEATED_CHAIR
    assert fixtures.read_complaint(client, complaint["id"])["status"] == "HEARING_SCHEDULED"
    return {"sam": sam, "complaint": complaint, "hearing": hearing}


class TestOnlyTheSeatedPanelChairMayConveneAndDecide:
    """Naming the chair does not grant counsel the chair's powers."""

    def test_the_scheduling_counsel_cannot_convene_the_hearing_they_created(self, client):
        """The disposition endpoint lists the chair's role alone.

        The PRD says "2. **Role authorisation for the operation** —
        `ERR_FORBIDDEN_ROLE`, on every endpoint."

        Design: Corner/rbac/only_the_seated_panel_chair_may_convene_and_decide
        """
        world = _hearing_seated_at_the_current_instant(client)

        validate_error(
            client.hearing_disposition(
                world["hearing"]["id"],
                factories.hearing_disposition_payload("CONVENE"),
                make_counsel_headers(SCREENER),
            ),
            ERR_FORBIDDEN_ROLE,
            expected_status=403,
        )
        held = validate_success(
            client.get_hearing(world["hearing"]["id"], make_analyst_headers())
        )
        assert held["status"] == "SCHEDULED"

    def test_an_unseated_chair_is_refused_and_the_seated_one_convenes(self, client):
        """The role is right, the identity is not — and the slot is already open.

        The PRD says "Thereafter only the presiding chair may act, proved by
        requiring the caller's `X-User-ID` to equal `panel_chair_user_id`; anyone
        else, including another `HearingPanelChair`, is refused with
        `ERR_PANEL_CHAIR_MISMATCH`."

        The PRD says "Convening at exactly `scheduled_start_at` is allowed."

        Design: Corner/rbac/only_the_seated_panel_chair_may_convene_and_decide
        """
        world = _hearing_seated_at_the_current_instant(client)
        body = factories.hearing_disposition_payload("CONVENE")

        validate_error(
            client.hearing_disposition(
                world["hearing"]["id"], body, make_chair_headers(UNSEATED_CHAIR)
            ),
            ERR_PANEL_CHAIR_MISMATCH,
            expected_status=403,
        )
        held = validate_success(
            client.get_hearing(world["hearing"]["id"], make_analyst_headers())
        )
        assert held["status"] == "SCHEDULED"

        convened = validate_success(
            client.hearing_disposition(
                world["hearing"]["id"], body, make_chair_headers(SEATED_CHAIR)
            )
        )
        assert convened["status"] == "CONVENED"
        assert convened["convened_at"] == HEARING_START

    def test_the_unseated_chair_cannot_decide_and_no_order_appears(self, client):
        """The identity gate holds on the second action of the same hearing too.

        The PRD says "8. **Assigned-panel-chair identity** —
        `ERR_PANEL_CHAIR_MISMATCH`, on hearing disposition."

        Design: Corner/rbac/only_the_seated_panel_chair_may_convene_and_decide
        """
        world = _hearing_seated_at_the_current_instant(client)
        hearing_id = world["hearing"]["id"]
        fixtures.dispose_hearing(client, hearing_id, SEATED_CHAIR, "CONVENE")

        validate_error(
            client.hearing_disposition(
                hearing_id,
                factories.hearing_disposition_payload(
                    "DECIDE",
                    finding="VIOLATION_FOUND",
                    sanction_type="FINE",
                    fine_cents=HEARING_FINE_CENTS,
                    suspension_days=0,
                ),
                make_chair_headers(UNSEATED_CHAIR),
            ),
            ERR_PANEL_CHAIR_MISMATCH,
            expected_status=403,
        )

        held = validate_success(client.get_hearing(hearing_id, make_analyst_headers()))
        assert held["status"] == "CONVENED"
        assert fixtures.orders_for_complaint(client, world["complaint"]["id"]) == []
        assert fixtures.read_licensee(client, world["sam"]["id"])["discipline_status"] == (
            "PENDING_HEARING"
        )

    def test_the_seated_chairs_decision_issues_the_only_order(self, client):
        """The identical body from the seated chair carries the whole cascade.

        The PRD says "A finding of `VIOLATION_FOUND` creates a sanction order with
        `source` `HEARING`, `status` `ISSUED` and `effective_at` at the current
        instant, moves the complaint `HEARING_SCHEDULED → ADJUDICATED`, moves the
        respondent's `discipline_status` `PENDING_HEARING → SANCTIONED`, applies the
        same `license_status` consequence and the same revocation cascade as the
        consent channel, and recomputes the brokerage posture."

        Design: Corner/rbac/only_the_seated_panel_chair_may_convene_and_decide
        """
        world = _hearing_seated_at_the_current_instant(client)
        hearing_id = world["hearing"]["id"]
        fixtures.dispose_hearing(client, hearing_id, SEATED_CHAIR, "CONVENE")

        decided = fixtures.dispose_hearing(
            client,
            hearing_id,
            SEATED_CHAIR,
            "DECIDE",
            finding="VIOLATION_FOUND",
            sanction_type="FINE",
            fine_cents=HEARING_FINE_CENTS,
            suspension_days=0,
        )
        assert decided["status"] == "DECIDED"
        assert decided["finding"] == "VIOLATION_FOUND"

        assert fixtures.read_complaint(client, world["complaint"]["id"])["status"] == "ADJUDICATED"
        order = fixtures.only_order_for_complaint(client, world["complaint"]["id"])
        assert order["source"] == "HEARING"
        assert order["sanction_type"] == "FINE"
        assert order["fine_cents"] == HEARING_FINE_CENTS
        assert order["respondent_licensee_id"] == world["sam"]["id"]

        sam = fixtures.read_licensee(client, world["sam"]["id"])
        assert sam["discipline_status"] == "SANCTIONED"
        assert sam["license_status"] == "ACTIVE", "a fine alone does not touch the licence"
