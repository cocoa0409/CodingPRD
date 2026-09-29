"""Field, state and eligibility gates on creation and adjudication.

Each corner here drives one validation gate to its rejection and then repairs
only the offending value, so the gate is shown to be a rule about that value
rather than a blanket refusal of the request.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    CLAIMS_EXAMINER_HEADERS,
    ERR_AGREEMENT_NOT_ACTIVE,
    ERR_ALLOWED_EXCEEDS_BILLED,
    ERR_INVALID_REQUEST,
    ERR_NO_POOL_FOR_SERVICE_DATE,
    ERR_PANEL_CLOSED_TO_NEW,
    ERR_POOL_SHARE_SUM_INVALID,
    ERR_SPECIALTY_AGE_BAND_MISMATCH,
    IPA_ADMIN_HEADERS,
    NETWORK_MANAGER_HEADERS,
    agreement_payload,
    assert_fields,
    assert_panel_size,
    assignment_payload,
    claim_payload,
    create_active_agreement,
    create_active_physician,
    create_agreement,
    create_claim,
    create_enrollee,
    create_pool,
    enrollee_version,
    read_agreement,
    read_claim,
    read_physician,
    read_pool,
    set_clock,
    state_payload,
)

UNBALANCED_TAX_ID = "94-3000061"


def _unbalanced_share_payload():
    """A payload whose two shares are individually legal but sum to 9000."""
    return agreement_payload(
        payer_name="Corner Share Sum Health",
        payer_tax_id=UNBALANCED_TAX_ID,
        professional_pool_share_bps=6000,
        institutional_pool_share_bps=3000,
    )


class TestPoolShareSumGate:
    def test_shares_that_do_not_sum_to_par_are_refused(self, api):
        """PRD §2.10: "`professional_pool_share_bps` and
        `institutional_pool_share_bps` add to exactly 10000."

        Design: Corner/validations/agreement_pool_shares_not_summing_to_10000_rejected
        """
        set_clock(api, "2026-08-01T00:00:00Z")

        response = api.create_agreement(_unbalanced_share_payload(), IPA_ADMIN_HEADERS)
        validate_error(response, ERR_POOL_SHARE_SUM_INVALID, 422)

    def test_the_sum_failure_is_not_a_request_shape_error_and_persists_nothing(self, api):
        """PRD §2.10: "The body parses; every required input field is present;
        every field has its declared type; every enum-typed field carries a
        declared member; every numeric field satisfies its declared range;
        `coverage_month` is four digits, a hyphen, then a month from `01` through
        `12`; `measurement_period` is exactly four digits; `limit` is between 1 and
        100 inclusive and `offset` is not negative."

        Design: Corner/validations/agreement_pool_shares_not_summing_to_10000_rejected
        """
        set_clock(api, "2026-08-01T00:00:00Z")

        response = api.create_agreement(_unbalanced_share_payload(), IPA_ADMIN_HEADERS)
        error = validate_error(response, ERR_POOL_SHARE_SUM_INVALID, 422)
        assert error["error_id"] != ERR_INVALID_REQUEST

        rows, meta = validate_paginated(
            api.list_agreements(IPA_ADMIN_HEADERS, {"limit": 100, "offset": 0})
        )
        assert meta["total_count"] == 0
        assert all(row["payer_tax_id"] != UNBALANCED_TAX_ID for row in rows)


class TestPoolSharesSummingToPar:
    def test_shares_summing_to_par_are_accepted_at_creation(self, api):
        """PRD §2.10: "`professional_pool_share_bps` and
        `institutional_pool_share_bps` add to exactly 10000."

        Design: Corner/validations/agreement_pool_shares_summing_to_10000_accepted
        """
        set_clock(api, "2026-08-01T00:00:00Z")

        created = validate_success(
            api.create_agreement(
                agreement_payload(
                    payer_name="Corner Share Sum Ok Health",
                    payer_tax_id="94-3000062",
                    professional_pool_share_bps=6000,
                    institutional_pool_share_bps=4000,
                ),
                IPA_ADMIN_HEADERS,
            ),
            201,
        )
        assert_fields(
            created,
            {
                "professional_pool_share_bps": 6000,
                "institutional_pool_share_bps": 4000,
                "status": "DRAFT",
            },
        )

    def test_the_same_sum_is_re_checked_at_activation_and_passes(self, api):
        """PRD §3.1: "The two pool shares are checked for sum at creation, and
        they are checked again at activation — the agreement moves `DRAFT → ACTIVE`
        only when `status` is `DRAFT` and `professional_pool_share_bps` and
        `institutional_pool_share_bps` together come to exactly 10000; a mismatch
        is refused with `ERR_POOL_SHARE_SUM_INVALID`."

        Design: Corner/validations/agreement_pool_shares_summing_to_10000_accepted
        """
        set_clock(api, "2026-08-01T00:00:00Z")
        agreement = create_agreement(
            api,
            payer_name="Corner Share Sum Ok Health",
            payer_tax_id="94-3000062",
            professional_pool_share_bps=6000,
            institutional_pool_share_bps=4000,
        )

        activated = validate_success(
            api.set_agreement_state(
                agreement["id"], state_payload("ACTIVE"), IPA_ADMIN_HEADERS
            ),
            200,
        )
        assert_fields(activated, {"status": "ACTIVE", "capitation_posture": "CURRENT"})
        assert read_agreement(api, agreement["id"])["capitation_posture"] == "CURRENT"


def _two_specialties_and_two_age_bands(api):
    """One INTERNAL_MEDICINE and one PEDIATRICS panel, one member of each band."""
    set_clock(api, "2026-08-01T00:00:00Z")
    agreement = create_active_agreement(
        api,
        payer_name="Corner Specialty Gate Health",
        base_pmpm_cents=20000,
        max_panel_size=5,
    )
    internist = create_active_physician(
        api, agreement["id"], full_name="Dr Internist", specialty="INTERNAL_MEDICINE"
    )
    pediatrician = create_active_physician(
        api, agreement["id"], full_name="Dr Pediatrician", specialty="PEDIATRICS"
    )
    pediatric_member = create_enrollee(
        api,
        agreement["id"],
        external_member_id="V8-PEDS",
        age_band="PEDIATRIC",
        risk_score_bps=10000,
    )
    adult_member = create_enrollee(
        api,
        agreement["id"],
        external_member_id="V8-ADULT",
        age_band="ADULT",
        risk_score_bps=10000,
    )
    return agreement, internist, pediatrician, pediatric_member, adult_member


class TestSpecialtyAgeBandGate:
    def test_a_pediatric_member_may_not_sit_on_an_internal_medicine_panel(self, api):
        """PRD §2.10: "An enrollee whose `age_band` is `PEDIATRIC` may be placed
        only with a physician whose `specialty` is `PEDIATRICS` or `PRIMARY_CARE`;
        an enrollee whose `age_band` is `SENIOR` may be placed only with a
        physician whose `specialty` is `INTERNAL_MEDICINE` or `PRIMARY_CARE`."

        Design: Corner/validations/pediatric_enrollee_assigned_to_internal_medicine_rejected
        """
        _agreement, internist, pediatrician, pediatric_member, _adult = (
            _two_specialties_and_two_age_bands(api)
        )
        assert pediatric_member["gross_pmpm_cents"] == 13000

        response = api.create_assignment(
            assignment_payload(
                pediatric_member["id"],
                internist["id"],
                enrollee_version(api, pediatric_member["id"]),
                effective_date="2026-08-01T00:00:00Z",
            ),
            NETWORK_MANAGER_HEADERS,
        )
        validate_error(response, ERR_SPECIALTY_AGE_BAND_MISMATCH, 422)
        assert_panel_size(read_physician(api, internist["id"]), 0)

        accepted = validate_success(
            api.create_assignment(
                assignment_payload(
                    pediatric_member["id"],
                    pediatrician["id"],
                    enrollee_version(api, pediatric_member["id"]),
                    effective_date="2026-08-01T00:00:00Z",
                ),
                NETWORK_MANAGER_HEADERS,
            ),
            201,
        )
        assert accepted["physician_id"] == pediatrician["id"]

    def test_the_same_internal_medicine_panel_accepts_an_adult_member(self, api):
        """PRD §3.4: "The same age-band and specialty rule guards both the initial
        placement and the transfer proposal: a `PEDIATRIC` member may sit only with
        a `PEDIATRICS` or `PRIMARY_CARE` physician and a `SENIOR` member only with
        an `INTERNAL_MEDICINE` or `PRIMARY_CARE` physician, and a violation on
        either operation is refused with `ERR_SPECIALTY_AGE_BAND_MISMATCH`."

        Design: Corner/validations/pediatric_enrollee_assigned_to_internal_medicine_rejected
        """
        _agreement, internist, _pediatrician, _pediatric_member, adult_member = (
            _two_specialties_and_two_age_bands(api)
        )

        accepted = validate_success(
            api.create_assignment(
                assignment_payload(
                    adult_member["id"],
                    internist["id"],
                    enrollee_version(api, adult_member["id"]),
                    effective_date="2026-08-01T00:00:00Z",
                ),
                NETWORK_MANAGER_HEADERS,
            ),
            201,
        )
        assert_fields(accepted, {"status": "ACTIVE", "physician_id": internist["id"]})
        assert_panel_size(read_physician(api, internist["id"]), 1)


def _suspended_agreement_with_a_closed_panel(api):
    """An agreement suspended after its only panel was OPEN and ACTIVE."""
    set_clock(api, "2026-08-01T00:00:00Z")
    agreement = create_active_agreement(
        api, payer_name="Corner Suspended Gate Health", max_panel_size=5
    )
    physician = create_active_physician(
        api, agreement["id"], full_name="Dr Suspended Gate"
    )
    enrollee = create_enrollee(
        api, agreement["id"], external_member_id="V10-0001", risk_score_bps=10000
    )
    suspended = validate_success(
        api.set_agreement_state(
            agreement["id"], state_payload("SUSPENDED"), IPA_ADMIN_HEADERS
        ),
        200,
    )
    assert suspended["status"] == "SUSPENDED"
    return agreement, physician, enrollee, enrollee_version(api, enrollee["id"])


class TestSuspendedAgreementOutranksTheClosedPanel:
    def test_an_assignment_under_a_suspended_agreement_reports_the_agreement_error(
        self, api
    ):
        """PRD §2.10: "The `DelegationAgreement` under which the operation runs
        has `status` equal to `ACTIVE`."

        Design: Corner/validations/assignment_under_suspended_agreement_rejected_before_the_panel_check
        """
        agreement, physician, enrollee, version = _suspended_agreement_with_a_closed_panel(
            api
        )
        assert read_physician(api, physician["id"])["panel_status"] == "CLOSED_TO_NEW"

        response = api.create_assignment(
            assignment_payload(
                enrollee["id"],
                physician["id"],
                version,
                effective_date="2026-08-01T00:00:00Z",
            ),
            NETWORK_MANAGER_HEADERS,
        )
        error = validate_error(response, ERR_AGREEMENT_NOT_ACTIVE, 409)
        assert error["error_id"] != ERR_PANEL_CLOSED_TO_NEW
        assert read_agreement(api, agreement["id"])["total_assigned_members"] == 0

    def test_reinstatement_does_not_reopen_the_panel_so_the_panel_error_surfaces(
        self, api
    ):
        """PRD §3.1: "It deliberately does not reopen anything: panels closed by
        the suspension stay `CLOSED_TO_NEW` until a `NetworkManager` reopens them
        one at a time."

        Design: Corner/validations/assignment_under_suspended_agreement_rejected_before_the_panel_check
        """
        agreement, physician, enrollee, version = _suspended_agreement_with_a_closed_panel(
            api
        )

        reinstated = validate_success(
            api.set_agreement_state(
                agreement["id"], state_payload("ACTIVE"), IPA_ADMIN_HEADERS
            ),
            200,
        )
        assert reinstated["status"] == "ACTIVE"

        response = api.create_assignment(
            assignment_payload(
                enrollee["id"],
                physician["id"],
                version,
                effective_date="2026-08-01T00:00:00Z",
            ),
            NETWORK_MANAGER_HEADERS,
        )
        validate_error(response, ERR_PANEL_CLOSED_TO_NEW, 409)
        assert read_physician(api, physician["id"])["panel_status"] == "CLOSED_TO_NEW"
        assert read_agreement(api, agreement["id"])["total_assigned_members"] == 0


def _agreement_with_a_professional_2026_pool(api):
    """An ACTIVE agreement, a 2026 PROFESSIONAL pool and one assigned member."""
    set_clock(api, "2026-08-01T00:00:00Z")
    agreement = create_active_agreement(
        api, payer_name="Corner Claim Guards Health", max_panel_size=5
    )
    pool = create_pool(api, agreement["id"], pool_type="PROFESSIONAL")
    physician = create_active_physician(
        api, agreement["id"], full_name="Dr Claim Guards"
    )
    enrollee = create_enrollee(
        api, agreement["id"], external_member_id="V11-0001", risk_score_bps=10000
    )
    validate_success(
        api.create_assignment(
            assignment_payload(
                enrollee["id"],
                physician["id"],
                enrollee_version(api, enrollee["id"]),
                effective_date="2026-08-01T00:00:00Z",
            ),
            NETWORK_MANAGER_HEADERS,
        ),
        201,
    )
    return agreement, pool, physician, enrollee


class TestClaimFiscalGates:
    def test_a_service_date_outside_every_pool_period_has_no_pool_to_resolve(self, api):
        """PRD §2.10: "A claim's `service_date` falls inside the closed period of
        some risk pool of the claim's agreement whose `pool_type` matches the
        claim's `pool_type`."

        Design: Corner/validations/claim_allowed_above_billed_and_service_date_outside_pool_rejected
        """
        agreement, pool, physician, enrollee = _agreement_with_a_professional_2026_pool(
            api
        )

        response = api.create_claim(
            claim_payload(
                agreement["id"],
                enrollee["id"],
                physician["id"],
                downstream_provider_name="Out Of Period Imaging LLC",
                billed_cents=10000,
                service_date="2027-01-01T00:00:00Z",
            ),
            CLAIMS_EXAMINER_HEADERS,
        )
        validate_error(response, ERR_NO_POOL_FOR_SERVICE_DATE, 422)

        on_the_closing_instant = create_claim(
            api,
            agreement["id"],
            enrollee["id"],
            physician["id"],
            downstream_provider_name="Endpoint Imaging LLC",
            billed_cents=10000,
            service_date="2026-12-31T23:59:59Z",
        )
        assert on_the_closing_instant["pool_id"] == pool["id"]

    def test_an_allowed_amount_above_billed_is_refused_and_equal_is_accepted(self, api):
        """PRD §2.10: "The `allowed_cents` supplied on an approval transition is
        at most the claim's `billed_cents`."

        Design: Corner/validations/claim_allowed_above_billed_and_service_date_outside_pool_rejected
        """
        agreement, pool, physician, enrollee = _agreement_with_a_professional_2026_pool(
            api
        )
        claim = create_claim(
            api,
            agreement["id"],
            enrollee["id"],
            physician["id"],
            downstream_provider_name="Endpoint Imaging LLC",
            billed_cents=10000,
            service_date="2026-12-31T23:59:59Z",
        )

        response = api.set_claim_state(
            claim["id"],
            state_payload("ADJUDICATED_APPROVED", allowed_cents=10001),
            CLAIMS_EXAMINER_HEADERS,
        )
        validate_error(response, ERR_ALLOWED_EXCEEDS_BILLED, 422)
        assert read_claim(api, claim["id"])["status"] == "RECEIVED"

        approved = validate_success(
            api.set_claim_state(
                claim["id"],
                state_payload("ADJUDICATED_APPROVED", allowed_cents=10000),
                CLAIMS_EXAMINER_HEADERS,
            ),
            200,
        )
        assert_fields(
            approved, {"status": "ADJUDICATED_APPROVED", "allowed_cents": 10000}
        )
        assert read_pool(api, pool["id"])["paid_claims_cents"] == 0
