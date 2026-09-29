"""Certificate issuance reads the notice ledger of a different entity."""

from prd_bench_local_runner.testing import validate_error

from test_helpers import (
    ERR_OPEN_VIOLATION_EXISTS,
    ERR_PARCEL_NOT_INSPECTED,
    PASS_CLEARANCES,
    add_zones,
    assert_end_of_day,
    assert_instant,
    assert_posture,
    complete_inspection,
    create_parcel,
    decide_certificate,
    decision_payload,
    failed_world,
    get_certificate,
    get_notice,
    get_parcel,
    open_certificate,
    schedule_inspection,
    serve_notice,
    set_clock,
)
from test_helpers.test_users import PROGRAM_ADMIN_HEADERS


def _cited_and_uninspected_world(client):
    """One cited parcel with a live REINSPECTION and one never-inspected parcel.

    The cited parcel failed an INITIAL inspection at 2026-08-22 and carries one
    ISSUED MAJOR notice; its REINSPECTION is already noticed and measured at
    passing clearances so that the citation can be lifted on demand.  Each parcel
    carries an INSURANCE certificate request standing in REQUESTED.
    """
    world = failed_world(client, fail_at="2026-08-22T00:00:00Z")
    fresh = create_parcel(client)

    reinspection = schedule_inspection(
        client,
        world["parcel"]["id"],
        world["cycle"]["id"],
        world["inspector"]["id"],
        scheduled_start_utc="2026-09-05T15:00:00Z",
        scheduled_end_utc="2026-09-05T17:00:00Z",
        inspection_type="REINSPECTION",
    )
    reinspection = serve_notice(client, reinspection["id"])
    add_zones(client, reinspection["id"], world["inspector"]["id"], PASS_CLEARANCES)

    world["fresh"] = fresh
    world["reinspection"] = reinspection
    world["cert_cited"] = open_certificate(
        client, world["parcel"]["id"], requester_kind="INSURANCE"
    )
    world["cert_fresh"] = open_certificate(
        client, fresh["id"], requester_kind="INSURANCE"
    )
    return world


class TestCertificateEligibilityGate:
    """Issuance is blocked by the parcel's open citation, not by the certificate."""

    def test_open_notice_blocks_issuance_until_the_reinspection_clears_it(
        self, client
    ):
        """The ISSUE decision is refused while the citation stands, and the
        identical decision succeeds once a passing REINSPECTION lifts it.

        PRD: "Certificate eligibility - issuance requires the parcel's
        compliance_status to be COMPLIANT or EXEMPT and requires that no violation
        notice on the parcel is in ISSUED, EXTENDED, OVERDUE or
        ABATEMENT_AUTHORIZED."

        PRD: "When the completing inspection's inspection_type is REINSPECTION,
        every violation notice on that parcel standing in ISSUED, EXTENDED or
        OVERDUE transitions to CLEARED with cleared_at_utc stamped at the logical
        clock; because those notices cleared, the parcel's open_violation_count is
        recomputed and each cleared notice's version advances by 1."

        PRD: "An ISSUE decision moves the certificate REQUESTED -> ISSUED and
        stamps four fields: issued_at_utc at the logical clock; expires_at_utc at
        the calendar date 90 days after issuance, expressed at 23:59:59 UTC on that
        date; snapshot_risk_class pinned to the parcel's risk_class at that moment;
        and snapshot_compliance_status pinned to the parcel's posture, which will
        therefore be either COMPLIANT or EXEMPT."

        Design: Difficulty/cross_entity_state_dependency/certificate_issuance_gated_on_no_open_violation_notice
        """
        world = _cited_and_uninspected_world(client)
        certificate_id = world["cert_cited"]["id"]
        assert get_notice(client, world["notice"]["id"])["status"] == "ISSUED"
        assert world["cert_cited"]["status"] == "REQUESTED"

        validate_error(
            client.certificate_decision(
                certificate_id,
                decision_payload("ISSUE"),
                headers=PROGRAM_ADMIN_HEADERS,
            ),
            ERR_OPEN_VIOLATION_EXISTS,
        )
        blocked = get_certificate(client, certificate_id)
        assert blocked["status"] == "REQUESTED"
        assert blocked["issued_at_utc"] is None
        assert blocked["expires_at_utc"] is None
        assert blocked["snapshot_risk_class"] is None
        assert blocked["snapshot_compliance_status"] is None

        # Clear the gate on the other entity only.
        set_clock(client, "2026-09-05T16:00:00Z")
        complete_inspection(
            client, world["reinspection"]["id"], world["inspector"]["id"], "PASS"
        )
        assert get_notice(client, world["notice"]["id"])["status"] == "CLEARED"
        assert_posture(
            get_parcel(client, world["parcel"]["id"]),
            "COMPLIANT",
            open_violation_count=0,
        )

        issued = decide_certificate(client, certificate_id, "ISSUE")
        assert issued["status"] == "ISSUED"
        assert_instant(issued["issued_at_utc"], "2026-09-05T16:00:00Z")
        assert_end_of_day(issued["expires_at_utc"], "2026-12-04")
        assert issued["snapshot_compliance_status"] == "COMPLIANT"
        assert issued["snapshot_risk_class"] == "MODERATE"

    def test_never_inspected_parcel_takes_the_other_branch_and_deny_is_ungated(
        self, client
    ):
        """A PENDING_INSPECTION parcel reports ERR_PARCEL_NOT_INSPECTED, while a
        DENY decision is allowed even with the citation still open.

        PRD: "Error selection is unambiguous: ERR_PARCEL_NOT_INSPECTED when
        compliance_status is PENDING_INSPECTION, and ERR_OPEN_VIOLATION_EXISTS in
        every other failing case (409)."

        PRD: "A DENY decision moves the certificate REQUESTED -> DENIED, records
        the supplied text as decision_note, and leaves every snapshot field null."

        Design: Difficulty/cross_entity_state_dependency/certificate_issuance_gated_on_no_open_violation_notice
        """
        world = _cited_and_uninspected_world(client)
        assert (
            get_parcel(client, world["fresh"]["id"])["compliance_status"]
            == "PENDING_INSPECTION"
        )

        validate_error(
            client.certificate_decision(
                world["cert_fresh"]["id"],
                decision_payload("ISSUE"),
                headers=PROGRAM_ADMIN_HEADERS,
            ),
            ERR_PARCEL_NOT_INSPECTED,
        )
        assert get_certificate(client, world["cert_fresh"]["id"])["status"] == (
            "REQUESTED"
        )

        # The gate covers only the ISSUE branch.
        denied = decide_certificate(
            client, world["cert_cited"]["id"], "DENY", "Open citation on file"
        )
        assert denied["status"] == "DENIED"
        assert denied["decision_note"] == "Open citation on file"
        assert denied["issued_at_utc"] is None
        assert denied["expires_at_utc"] is None
        assert denied["snapshot_risk_class"] is None
        assert denied["snapshot_compliance_status"] is None
        assert get_notice(client, world["notice"]["id"])["status"] == "ISSUED"
