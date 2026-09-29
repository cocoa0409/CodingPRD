"""Endpoint surfaces: the parcel round trip, a read-time metric, an exempt
issuance and the three links a discretionary notice writes at once."""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_success,
)

from test_helpers import (
    ERR_INSPECTION_NOT_FOUND,
    ERR_PARCEL_NOT_INSPECTED,
    assert_end_of_day,
    assert_instant,
    assert_posture,
    assert_risk,
    assert_version,
    create_parcel,
    cycle_metrics,
    decision_payload,
    discretionary_notice_payload,
    failed_world,
    get_certificate,
    get_cycle,
    get_notice,
    get_parcel,
    ids_of,
    list_notices,
    list_parcels,
    open_certificate,
    open_cycle,
    parcel_patch,
)
from test_helpers.test_users import PROGRAM_ADMIN_HEADERS


def _patch_parcel(client, parcel_id, expected_version, **changes):
    return validate_success(
        client.update_parcel(
            parcel_id,
            parcel_patch(expected_version, **changes),
            headers=PROGRAM_ADMIN_HEADERS,
        )
    )


class TestParcelSurfaceRoundTrip:
    """Create, read, update and list are one coherent surface on the inventory."""

    def test_a_patch_of_scoring_fields_rebands_the_row_and_moves_it_between_filters(
        self, client
    ):
        """An email-only PATCH versions the row without rescoring; a scoring PATCH
        clamps the parcel to 100.00 EXTREME and the list filter follows it there.

        PRD: "A ProgramAdmin may revise access_constraint, roof_class,
        vegetation_type, slope_pct, hazard_zone, owner_email, community_id,
        owner_hardship_flag and exemption_flag; every such request carries
        expected_parcel_version and is refused with ERR_STALE_PARCEL_VERSION when that
        value does not match the parcel's current version."

        PRD: "When any scoring attribute changes, the score and band are recomputed -
        under the intake-provisional variant unless a completed inspection has already
        pinned the basis to POST_INSPECTION_VERIFIED, in which case the verified basis
        is retained."

        PRD: "Every successful update increments the parcel's version by 1."

        PRD: "The product is then clamped so that it can never exceed 100.00, and the
        clamped value is rounded half up to two decimal places to give risk_score.
        Clamping happens before rounding, not after."

        PRD: "a score of 75.00 or above is EXTREME"

        PRD: "List parcels, filterable by community_id, compliance_status and
        risk_class, paginated with limit and offset."

        Design: Corner/endpoints/parcel_create_read_update_list_round_trip
        """
        created = create_parcel(client)
        assert_risk(created, 63.83, "HIGH", basis="INTAKE_PROVISIONAL")
        assert_version(created, 1)

        # The read surface reports exactly what the create surface returned.
        read_back = get_parcel(client, created["id"])
        assert_risk(read_back, 63.83, "HIGH", basis="INTAKE_PROVISIONAL")
        assert read_back["id"] == created["id"]
        assert read_back["apn"] == created["apn"]

        # owner_email is revisable but is not one of the five scoring attributes.
        renamed = _patch_parcel(
            client, created["id"], created["version"], owner_email="rosa2@example.com"
        )
        assert_version(renamed, 2)
        assert renamed["owner_email"] == "rosa2@example.com"
        assert_risk(renamed, 63.83, "HIGH", basis="INTAKE_PROVISIONAL")

        # slope 50 scores 100, MIXED_CONIFER 90, an unrated roof 100 and a locked
        # gate 60: the weighted subtotal is 91.00 and the VERY_HIGH surcharge lifts
        # it to 118.30, which the ceiling cuts back to 100.00.
        rescored = _patch_parcel(
            client,
            created["id"],
            renamed["version"],
            slope_pct=50,
            vegetation_type="MIXED_CONIFER",
            roof_class="NONE",
            access_constraint="LOCKED_GATE",
            hazard_zone="VERY_HIGH",
        )
        assert_version(rescored, 3)
        assert_risk(rescored, 100.00, "EXTREME", basis="INTAKE_PROVISIONAL")
        assert rescored["risk_score"] != 118.30, "the ceiling is 100.00"

        extreme_rows, extreme_meta = list_parcels(client, risk_class="EXTREME")
        assert extreme_meta["total_count"] == 1
        assert created["id"] in ids_of(extreme_rows)

        _high_rows, high_meta = list_parcels(client, risk_class="HIGH")
        assert high_meta["total_count"] == 0, "the row left its old band"


class TestDistrictMetricsOnEmptyEligibleSet:
    """A metrics read is a pure computation over the eligible set."""

    def test_a_district_of_pending_and_exempt_parcels_reports_a_null_rate(self, client):
        """Neither parcel is eligible, so the rate is null rather than 0.00 and the
        repeated read is identical.

        PRD: "A parcel is eligible when its compliance_status is COMPLIANT,
        NON_COMPLIANT or ABATEMENT_PENDING. Parcels sitting in PENDING_INSPECTION or
        EXEMPT are excluded from both the numerator and the denominator - they are not
        counted as failures, they are simply not counted."

        PRD: "Where the eligible set is empty the rate is null, which is a distinct
        value from 0.00 and must be reported as null rather than as a zero."

        PRD: "The district metrics read computes its numbers fresh at read time rather
        than serving stored values, and returns eligible_parcel_count,
        compliant_parcel_count, compliance_rate_pct, survived_compliant_pct,
        survived_noncompliant_pct, survival_delta_pp and the cycle's current epoch."

        PRD: "Setting exemption_flag to true has two immediate consequences beyond the
        flag itself: compliance_status becomes EXEMPT and inspection_priority_rank is
        cleared to null."

        Design: Corner/endpoints/cycle_metrics_returns_null_rate_with_no_eligible_parcels
        """
        cycle = open_cycle(client)
        pending = create_parcel(client)
        exempt = create_parcel(client)
        exempt = _patch_parcel(
            client, exempt["id"], exempt["version"], exemption_flag=True
        )

        assert_posture(get_parcel(client, pending["id"]), "PENDING_INSPECTION")
        assert_posture(exempt, "EXEMPT")
        assert exempt["inspection_priority_rank"] is None

        metrics = cycle_metrics(client, cycle["id"])
        assert metrics["eligible_parcel_count"] == 0
        assert metrics["compliant_parcel_count"] == 0
        assert metrics["compliance_rate_pct"] is None, "an empty set is null, not 0.00"
        assert metrics["survived_compliant_pct"] is None
        assert metrics["survived_noncompliant_pct"] is None
        assert metrics["survival_delta_pp"] is None
        assert metrics["epoch"] == 0

        # Reading twice cannot move anything: the numbers are computed, not stored.
        again = cycle_metrics(client, cycle["id"])
        for field in (
            "eligible_parcel_count",
            "compliant_parcel_count",
            "compliance_rate_pct",
            "survived_compliant_pct",
            "survived_noncompliant_pct",
            "survival_delta_pp",
            "epoch",
        ):
            assert again[field] == metrics[field], "%s moved on a second read" % field
        assert get_cycle(client, cycle["id"])["epoch"] == 0


class TestCertificateOnAnExemptParcel:
    """Eligibility is a posture test, not a history test."""

    def test_an_exempt_parcel_that_was_never_inspected_is_still_certifiable(
        self, client
    ):
        """EXEMPT satisfies issuance even with last_passed_inspection_at_utc null, and
        the snapshot pins HIGH and EXEMPT.

        PRD: "Issuance is only available on a parcel with a clean posture: its
        compliance_status must be COMPLIANT or EXEMPT, and it must hold no violation
        notice standing in ISSUED, EXTENDED, OVERDUE or ABATEMENT_AUTHORIZED."

        PRD: "An ISSUE decision moves the certificate REQUESTED -> ISSUED and stamps
        four fields: issued_at_utc at the logical clock; expires_at_utc at the calendar
        date 90 days after issuance, expressed at 23:59:59 UTC on that date;
        snapshot_risk_class pinned to the parcel's risk_class at that moment; and
        snapshot_compliance_status pinned to the parcel's posture, which will therefore
        be either COMPLIANT or EXEMPT."

        PRD: "Error selection between the two failure modes is unambiguous - a parcel
        whose compliance_status is PENDING_INSPECTION answers ERR_PARCEL_NOT_INSPECTED,
        and every other failing case, including a NON_COMPLIANT or ABATEMENT_PENDING
        posture and the open-notice case, answers ERR_OPEN_VIOLATION_EXISTS."

        PRD: "last_passed_inspection_at_utc, which holds the completion instant of the
        most recent passing inspection on the parcel and stays null until one exists."

        Design: Corner/endpoints/certificate_issue_permitted_on_exempt_parcel
        """
        parcel = create_parcel(client)
        parcel = _patch_parcel(
            client, parcel["id"], parcel["version"], exemption_flag=True
        )
        assert parcel["risk_class"] == "HIGH"
        assert_posture(parcel, "EXEMPT")
        assert parcel["last_passed_inspection_at_utc"] is None

        requested = open_certificate(client, parcel["id"])
        assert requested["status"] == "REQUESTED"
        for field in (
            "issued_at_utc",
            "expires_at_utc",
            "snapshot_risk_class",
            "snapshot_compliance_status",
            "revoked_at_utc",
        ):
            assert requested[field] is None, "%s is stamped only at decision" % field

        issued = validate_success(
            client.certificate_decision(
                requested["id"],
                decision_payload("ISSUE", "Exemption on file"),
                headers=PROGRAM_ADMIN_HEADERS,
            )
        )
        assert issued["status"] == "ISSUED"
        assert_instant(issued["issued_at_utc"], "2026-08-01T00:00:00Z")
        assert_end_of_day(issued["expires_at_utc"], "2026-10-30")
        assert issued["snapshot_risk_class"] == "HIGH"
        assert issued["snapshot_compliance_status"] == "EXEMPT"

        stored = get_certificate(client, requested["id"])
        assert stored["decision_note"] == "Exemption on file"
        assert stored["revoked_at_utc"] is None
        assert_version(stored, 2)

        # The same request against a parcel still awaiting its first visit fails on
        # the posture gate rather than on any history of passing inspections.
        untouched = create_parcel(client)
        assert_posture(untouched, "PENDING_INSPECTION")
        pending_certificate = open_certificate(client, untouched["id"])
        validate_error(
            client.certificate_decision(
                pending_certificate["id"],
                decision_payload("ISSUE", "No exemption on file"),
                headers=PROGRAM_ADMIN_HEADERS,
            ),
            ERR_PARCEL_NOT_INSPECTED,
            409,
        )


class TestDiscretionaryNoticeLinks:
    """One write resolves the path parcel, the body inspection and the notice it
    replaces."""

    def test_the_new_citation_voids_the_old_one_and_the_open_count_stays_at_one(
        self, client
    ):
        """The superseded notice is VOIDED with its reason recorded, the new notice
        points back at it, and the parcel still carries exactly one live citation.

        PRD: "Because a parcel may hold only one live citation, issuing this notice
        supersedes whatever was open: any existing notice on the same parcel standing
        in ISSUED, EXTENDED or OVERDUE is driven to VOIDED with its void_reason
        recorded as SUPERSEDED_BY_NEW_NOTICE, and the new notice's supersedes_notice_id
        is set to the identifier of the notice it replaced."

        PRD: "The new notice's delivered_at_utc, compliance_days and deadline_utc are
        computed by the rules above, the parcel's open_violation_count is recomputed,
        its compliance_status is set to NON_COMPLIANT, and its version advances by 1."

        PRD: "Where the notice was handed over in person or sent by email,
        delivered_at_utc equals issued_at_utc - service is instantaneous."

        PRD: "a MINOR deficiency earns the owner 60 days, a MAJOR deficiency 30 days,
        and a CRITICAL deficiency only 14."

        PRD: "Once every path segment resolves, foreign keys supplied in the request
        body are validated in a fixed declaration order: cycle_id, then parcel_id, then
        community_id, then inspector_id, then contractor_id, then inspection_id, then
        violation_notice_id, then support_program_id."

        PRD: "as a list filtered by parcel_id, by the originating inspection_id, by
        supersedes_notice_id to find what replaced what, and by status."

        Design: Corner/endpoints/discretionary_notice_links_parcel_inspection_and_prior_notice
        """
        world = failed_world(client)
        parcel = world["parcel"]
        first_notice = world["notice"]
        assert first_notice["status"] == "ISSUED"
        assert first_notice["supersedes_notice_id"] is None
        assert_posture(parcel, "NON_COMPLIANT", open_violation_count=1)

        # The body reference is resolved before anything is written.
        validate_error(
            client.create_discretionary_notice(
                parcel["id"],
                discretionary_notice_payload(
                    NON_EXISTENT_UUID, parcel["version"], notice_method="EMAIL"
                ),
                headers=PROGRAM_ADMIN_HEADERS,
            ),
            ERR_INSPECTION_NOT_FOUND,
            404,
        )
        assert_version(get_parcel(client, parcel["id"]), parcel["version"])

        replacement = validate_success(
            client.create_discretionary_notice(
                parcel["id"],
                discretionary_notice_payload(
                    world["inspection"]["id"],
                    parcel["version"],
                    notice_method="EMAIL",
                ),
                headers=PROGRAM_ADMIN_HEADERS,
            ),
            201,
        )
        assert replacement["parcel_id"] == parcel["id"]
        assert replacement["inspection_id"] == world["inspection"]["id"]
        assert replacement["supersedes_notice_id"] == first_notice["id"]
        assert replacement["severity"] == "MAJOR"
        assert_instant(replacement["delivered_at_utc"], "2026-08-01T00:00:00Z")
        assert replacement["compliance_days"] == 30
        assert_end_of_day(replacement["deadline_utc"], "2026-08-31")

        superseded = get_notice(client, first_notice["id"])
        assert superseded["status"] == "VOIDED"
        assert superseded["void_reason"] == "SUPERSEDED_BY_NEW_NOTICE"
        assert superseded["cleared_at_utc"] is None

        # One citation closed and one opened leaves the count where it was.
        after = get_parcel(client, parcel["id"])
        assert_posture(after, "NON_COMPLIANT", open_violation_count=1)
        assert after["open_violation_count"] != 2

        rows, meta = list_notices(client, supersedes_notice_id=first_notice["id"])
        assert meta["total_count"] == 1
        assert ids_of(rows) == [replacement["id"]]
