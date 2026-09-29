"""Depth tests for the accreditation renewal cycle.

The accreditation walks APPROVED -> EXPIRING -> RENEWAL_PENDING -> APPROVED, and
the re-entry into APPROVED must RECOMPUTE the term and the forum grant rather
than copy the previous round's values.
"""

from test_helpers import factories
from test_helpers.assertions import assert_fields, created, ok
from test_helpers.fixtures import Env, set_clock
from test_helpers.test_users import program_director_headers

# ---------------------------------------------------------------------------
# accreditation_renewal_cycle_reenters_approved_with_partial_forum_ceiling
# ---------------------------------------------------------------------------


def _setup_partial_accreditation(api):
    """A PARTIAL accreditation approved at 2026-09-01 against a wide recognition.

    The recognition authorizes USCIS, ASYLUM_OFFICE and EOIR_IMMIGRATION_COURT
    and the request asks for USCIS plus EOIR_IMMIGRATION_COURT, but the PARTIAL
    ceiling reaches only USCIS and ASYLUM_OFFICE, so the three-way intersection
    is exactly ['USCIS'].
    """
    env = Env(api)
    director = program_director_headers()
    set_clock(api, "2026-09-01T00:00:00.000Z")

    cycle = created(
        api.create_capacity_cycle(
            factories.cycle_payload(
                cycle_label="MULTIYEAR",
                period_start_date="2026-08-01",
                period_end_date="2033-12-31",
                total_case_slots=10,
                reserved_detained_slots=2,
            ),
            headers=director,
        )
    )
    recognition = created(
        api.create_recognition(
            factories.recognition_payload(
                recognition_number="R-2290-001",
                effective_date="2026-01-01",
                expiry_date="2033-12-31",
                authorized_forums=["USCIS", "ASYLUM_OFFICE", "EOIR_IMMIGRATION_COURT"],
            ),
            headers=director,
        )
    )
    approver = created(
        api.create_representative(
            factories.staff_attorney_payload(
                full_name="Dov Halberstam",
                languages=["en"],
                max_case_load=10,
                max_supervisees=5,
            ),
            headers=director,
        )
    )
    accredited_rep = created(
        api.create_representative(
            factories.accredited_rep_payload(
                full_name="Yusra Bekele",
                languages=["en", "am"],
                max_case_load=15,
                max_supervisees=0,
                weekly_capacity_hours=35,
            ),
            headers=director,
        )
    )
    accreditation = created(
        api.create_accreditation(
            factories.accreditation_payload(
                accredited_rep["id"],
                recognition["id"],
                accreditation_type="PARTIAL",
                requested_forums=["USCIS", "EOIR_IMMIGRATION_COURT"],
            ),
            headers=director,
        )
    )
    ok(
        api.transition_accreditation(
            accreditation["id"],
            {"action": "APPROVE", "decision_reason_code": "CREDENTIALS_VERIFIED"},
            headers=env.attorney_headers(approver["id"]),
        )
    )
    env.set(
        cycle_id=cycle["id"],
        rec_id=recognition["id"],
        approver_id=approver["id"],
        arep_id=accredited_rep["id"],
        acc_id=accreditation["id"],
    )
    return env


def test_checkpoint_is_the_only_way_into_expiring_and_authorization_survives_it(api):
    """EXPIRING is a system-actor state: no caller action can reach it.

    The first term runs 2026-09-01..2029-08-31 (effective plus 1095 days), so a
    clock at 2029-08-21 sits inside the 90-day window and the sweep's credential
    aging phase moves the row. EXPIRING is still a qualifying status, so the
    representative stays AUTHORIZED_ACCREDITED throughout.

    Design: Difficulty/non_linear_state_machine/accreditation_renewal_cycle_reenters_approved_with_partial_forum_ceiling
    """
    env = _setup_partial_accreditation(api)

    approved = env.accreditation(env["acc_id"])
    assert_fields(
        approved,
        status="APPROVED",
        effective_date="2026-09-01",
        expiry_date="2029-08-31",
        renewal_round=0,
        decision_reason_code="CREDENTIALS_VERIFIED",
    )
    assert approved["authorized_forums"] == ["USCIS"], (
        "the PARTIAL ceiling reaches only USCIS and ASYLUM_OFFICE, so the "
        "requested EOIR_IMMIGRATION_COURT must be dropped"
    )
    assert_fields(
        env.representative(env["arep_id"]),
        authorization_status="AUTHORIZED_ACCREDITED",
        supervision_required=True,
    )

    set_clock(api, "2029-08-21T00:00:00.000Z")
    ok(api.checkpoint_cycle(env["cycle_id"], headers=env.director))

    assert env.accreditation(env["acc_id"])["status"] == "EXPIRING"
    assert (
        env.representative(env["arep_id"])["authorization_status"]
        == "AUTHORIZED_ACCREDITED"
    )


def test_renewal_reenters_approved_with_a_recomputed_term_and_the_same_ceiling(api):
    """The second APPROVED is not a copy of the first: every derived field moves.

    Renewal consumes the recognition's optimistic-concurrency token, so the
    recognition's version advances by one, and the grant is computed at the
    approval that follows -- where the PARTIAL ceiling again intersects the
    widened request down to USCIS alone.

    Design: Difficulty/non_linear_state_machine/accreditation_renewal_cycle_reenters_approved_with_partial_forum_ceiling
    """
    env = _setup_partial_accreditation(api)
    set_clock(api, "2029-08-21T00:00:00.000Z")
    ok(api.checkpoint_cycle(env["cycle_id"], headers=env.director))

    recognition_version = env.recognition(env["rec_id"])["version"]
    renewed = ok(
        api.renew_accreditation(
            env["acc_id"],
            {
                "expected_recognition_version": recognition_version,
                "requested_forums": ["USCIS", "EOIR_IMMIGRATION_COURT", "BIA"],
            },
            headers=env.attorney_headers(env["approver_id"]),
        )
    )
    assert renewed["status"] == "RENEWAL_PENDING"
    assert env.recognition(env["rec_id"])["version"] == recognition_version + 1

    reapproved = ok(
        api.transition_accreditation(
            env["acc_id"],
            {"action": "APPROVE", "decision_reason_code": "CREDENTIALS_VERIFIED"},
            headers=env.attorney_headers(env["approver_id"]),
        )
    )
    assert_fields(
        reapproved,
        status="APPROVED",
        renewal_round=1,
        effective_date="2029-08-21",
        expiry_date="2032-08-20",
    )
    assert reapproved["authorized_forums"] == ["USCIS"], (
        "BIA and EOIR_IMMIGRATION_COURT sit above the PARTIAL ceiling and must "
        "be dropped again at renewal"
    )
    assert (
        env.representative(env["arep_id"])["authorization_status"]
        == "AUTHORIZED_ACCREDITED"
    )
