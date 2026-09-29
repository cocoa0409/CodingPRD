"""Regulator dockets: the two evidence filings, their fork-join and the closure gate.

The docket is answered by two independent filings that may arrive in either
order. Each branch carries its own precondition, the join to `RESPONSE_COMPLETE`
only fires once both branch timestamps are non-null, and closure is refused
until it has.
"""

from datetime import datetime
from typing import Any, Dict, Tuple

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import ApiErrorId, api_client
from test_helpers.constants import REFERENCE_NOW
from test_helpers.factories import build_close_inquiry_payload, build_filing_payload
from test_helpers.fixtures import (
    ReferenceEnvironment,
    build_reference_environment,
    create_investigated_complaint,
    create_regulator_inquiry,
    dismiss_complaint,
    set_clock,
    uphold_complaint,
)
from test_helpers.test_users import REGULATORY_LIAISON_HEADERS
from test_helpers.types import (
    ComplaintState,
    CreditBasis,
    FilingType,
    RegulatorInquiryState,
)

# The docket's own deadline and the two instants the filings land on.
RESPONSE_DUE_AT = "2026-09-30T00:00:00Z"
FIRST_FILING_AT = REFERENCE_NOW  # 2026-09-01T00:00:00Z
SECOND_FILING_AT = "2026-10-01T00:00:00Z"
SERVICE_OBSERVED_DATE = "2026-09-01T12:00:00Z"

TECHNICAL_EVIDENCE_REF = "PKT-2026-0042-A"
TECHNICAL_EVIDENCE_REF_REPEAT = "PKT-2026-0042-A2"
RESOLUTION_EVIDENCE_REF = "RPT-2026-0042-B"
DISMISSED_RESOLUTION_EVIDENCE_REF = "RPT-2026-0077-A"


# ---------------------------------------------------------------------------
# Local helpers: instant comparison and the two docket worlds
# ---------------------------------------------------------------------------


def _instant(value: str) -> datetime:
    """Parse an ISO-8601 UTC instant, tolerating both `Z` and `+00:00` forms."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _assert_instant(resource: Dict[str, Any], field: str, expected: str) -> None:
    actual = resource.get(field)
    assert actual is not None, f"{field} should have been recorded"
    assert _instant(actual) == _instant(expected), (
        f"{field}: expected the logical clock at {expected}, got {actual}"
    )


def _read_docket(inquiry_id: str) -> Dict[str, Any]:
    return validate_success(
        api_client.get_regulator_inquiry(inquiry_id, REGULATORY_LIAISON_HEADERS)
    )


def _read_complaint(complaint_id: str) -> Dict[str, Any]:
    return validate_success(
        api_client.get_complaint(complaint_id, REGULATORY_LIAISON_HEADERS)
    )


def _file(
    inquiry_id: str,
    filing_type: str,
    evidence_ref: str,
    summary: str,
):
    """The filing call itself, so the raw response can be validated."""
    return api_client.file_inquiry_filing(
        inquiry_id,
        build_filing_payload(
            filing_type=filing_type, evidence_ref=evidence_ref, summary=summary
        ),
        REGULATORY_LIAISON_HEADERS,
    )


def _close(inquiry_id: str, closure_note: str):
    return api_client.close_regulator_inquiry(
        inquiry_id,
        build_close_inquiry_payload(closure_note=closure_note),
        REGULATORY_LIAISON_HEADERS,
    )


def _docket_on_upheld_complaint() -> Tuple[ReferenceEnvironment, str, str]:
    """A docket in `RECEIVED` whose complaint is already resolved `UPHELD`, so
    both branch preconditions hold: the disputed label is substantiated and the
    complaint has reached a state the resolution report accepts."""
    env = build_reference_environment()
    complaint = create_investigated_complaint(
        env.account_id, env.label_id, service_observed_date=SERVICE_OBSERVED_DATE
    )
    uphold_complaint(
        complaint["id"],
        credit_basis=CreditBasis.PRORATA_DAYS.value,
        resolution_note="Shortfall confirmed against the pinned label",
    )
    inquiry = create_regulator_inquiry(
        complaint["id"], response_due_at=RESPONSE_DUE_AT
    )
    return env, complaint["id"], inquiry["id"]


def _docket_on_investigated_complaint() -> Tuple[ReferenceEnvironment, str, str]:
    """A docket in `RECEIVED` whose complaint is still `UNDER_INVESTIGATION`."""
    env = build_reference_environment()
    complaint = create_investigated_complaint(
        env.account_id, env.label_id, service_observed_date=SERVICE_OBSERVED_DATE
    )
    inquiry = create_regulator_inquiry(
        complaint["id"], response_due_at=RESPONSE_DUE_AT
    )
    return env, complaint["id"], inquiry["id"]


def _file_technical_packet(inquiry_id: str) -> Dict[str, Any]:
    response = _file(
        inquiry_id,
        FilingType.TECHNICAL_PACKET.value,
        TECHNICAL_EVIDENCE_REF,
        "Methodology, run window and pooled samples behind the typical-speed claim",
    )
    return validate_success(response)


def _file_resolution_report(
    inquiry_id: str,
    evidence_ref: str = RESOLUTION_EVIDENCE_REF,
    summary: str = "Upheld finding, credit issued and remediation summary",
) -> Dict[str, Any]:
    return validate_success(
        _file(inquiry_id, FilingType.RESOLUTION_REPORT.value, evidence_ref, summary)
    )


# ---------------------------------------------------------------------------
# The fork that joins
# ---------------------------------------------------------------------------


class TestRegulatorInquiryForkJoin:
    """Two filing branches, one shared assembly state, one join, one closure gate."""

    def test_close_before_any_filing_leaves_the_docket_in_received(self):
        """A docket with neither filing on record cannot be closed at all.

        PRD: "Closing the docket carries a `closure_note` and is only admissible
        from `RESPONSE_COMPLETE`; a docket still in `RECEIVED` or
        `EVIDENCE_ASSEMBLY` answers `ERR_INQUIRY_FILINGS_INCOMPLETE`."

        Design: Difficulty/non_linear_state_machine/regulator_inquiry_fork_join_requires_both_filings
        """
        _, _, inquiry_id = _docket_on_upheld_complaint()

        response = _close(inquiry_id, "Premature closure attempt")
        validate_error(response, ApiErrorId.ERR_INQUIRY_FILINGS_INCOMPLETE.value)

        docket = _read_docket(inquiry_id)
        assert docket["state"] == RegulatorInquiryState.RECEIVED.value, (
            "a refused closure must leave the docket in RECEIVED"
        )
        assert docket["closed_at"] is None, "closed_at must still be null"
        assert docket["closure_note"] is None, "closure_note must still be null"
        assert docket["technical_packet_filed_at"] is None
        assert docket["resolution_report_filed_at"] is None

    def test_first_filing_forks_to_evidence_assembly_and_the_branch_cannot_repeat(self):
        """Either branch may be taken first, and once taken it is closed to a repeat.

        PRD: "Whichever filing arrives first moves the docket `RECEIVED →
        EVIDENCE_ASSEMBLY`. The second filing must name the branch whose
        timestamp is still null and must satisfy that branch's own precondition;
        naming a branch already filed, or filing at all against a docket whose
        state is `RESPONSE_COMPLETE` or `CLOSED`, answers
        `ERR_INQUIRY_INVALID_STATE`."

        Design: Difficulty/non_linear_state_machine/regulator_inquiry_fork_join_requires_both_filings
        """
        _, _, inquiry_id = _docket_on_upheld_complaint()

        filed = _file_technical_packet(inquiry_id)
        assert filed["state"] == RegulatorInquiryState.EVIDENCE_ASSEMBLY.value, (
            "the first filing forks RECEIVED → EVIDENCE_ASSEMBLY"
        )
        assert filed["technical_evidence_ref"] == TECHNICAL_EVIDENCE_REF
        _assert_instant(filed, "technical_packet_filed_at", FIRST_FILING_AT)
        assert filed["resolution_report_filed_at"] is None, (
            "the untaken branch keeps a null timestamp"
        )
        assert filed["resolution_report_ref"] is None

        repeat = _file(
            inquiry_id,
            FilingType.TECHNICAL_PACKET.value,
            TECHNICAL_EVIDENCE_REF_REPEAT,
            "Duplicate technical packet",
        )
        validate_error(repeat, ApiErrorId.ERR_INQUIRY_INVALID_STATE.value)

        docket = _read_docket(inquiry_id)
        assert docket["technical_evidence_ref"] == TECHNICAL_EVIDENCE_REF, (
            "the refused repeat must not overwrite the branch's evidence reference"
        )
        _assert_instant(docket, "technical_packet_filed_at", FIRST_FILING_AT)
        assert docket["state"] == RegulatorInquiryState.EVIDENCE_ASSEMBLY.value

    def test_join_fires_only_on_the_second_branch_and_flags_the_late_answer(self):
        """One branch is not enough; the join fires on the second and dates the answer.

        PRD: "The second filing records its branch's reference and timestamp and
        then joins: because both `technical_packet_filed_at` and
        `resolution_report_filed_at` are now non-null, the docket moves
        `EVIDENCE_ASSEMBLY → RESPONSE_COMPLETE`. At that join the docket's
        `filed_late` is set to true when the later of the two filing timestamps
        is strictly after `response_due_at`, and to false otherwise."

        Design: Difficulty/non_linear_state_machine/regulator_inquiry_fork_join_requires_both_filings
        """
        _, _, inquiry_id = _docket_on_upheld_complaint()

        _file_technical_packet(inquiry_id)

        premature = _close(inquiry_id, "Still premature")
        validate_error(premature, ApiErrorId.ERR_INQUIRY_FILINGS_INCOMPLETE.value)
        assert (
            _read_docket(inquiry_id)["state"]
            == RegulatorInquiryState.EVIDENCE_ASSEMBLY.value
        ), "with only one branch filed the join has not fired"

        set_clock(SECOND_FILING_AT)
        joined = _file_resolution_report(inquiry_id)

        assert joined["state"] == RegulatorInquiryState.RESPONSE_COMPLETE.value, (
            "both branch timestamps are now non-null, so the docket joins"
        )
        assert joined["resolution_report_ref"] == RESOLUTION_EVIDENCE_REF
        _assert_instant(joined, "resolution_report_filed_at", SECOND_FILING_AT)
        _assert_instant(joined, "technical_packet_filed_at", FIRST_FILING_AT)
        assert joined["filed_late"] is True, (
            f"the later filing at {SECOND_FILING_AT} is strictly after the "
            f"response_due_at of {RESPONSE_DUE_AT}, so filed_late is true"
        )

    def test_closure_of_an_answered_docket_records_the_terminal_state(self):
        """Once both branches are on record the docket may be closed.

        PRD: "Closure sets `state` to `CLOSED`, its terminal state, records
        `closed_at` as the logical clock, and stores the supplied
        `closure_note`."

        Design: Difficulty/non_linear_state_machine/regulator_inquiry_fork_join_requires_both_filings
        """
        _, _, inquiry_id = _docket_on_upheld_complaint()

        _file_technical_packet(inquiry_id)
        set_clock(SECOND_FILING_AT)
        _file_resolution_report(inquiry_id)

        closed = validate_success(_close(inquiry_id, "Docket answered on both branches"))

        assert closed["state"] == RegulatorInquiryState.CLOSED.value
        _assert_instant(closed, "closed_at", SECOND_FILING_AT)
        assert closed["closure_note"] == "Docket answered on both branches"
        assert closed["filed_late"] is True, (
            "the lateness settled at the join survives closure"
        )


# ---------------------------------------------------------------------------
# The resolution-report branch depends on a complaint in another aggregate
# ---------------------------------------------------------------------------


class TestResolutionReportRequiresTerminalComplaint:
    """The docket's own transition is gated on the state of its complaint."""

    def test_resolution_report_refused_while_the_complaint_is_under_investigation(self):
        """The report branch cannot be filed against a live investigation.

        PRD: "A `RESOLUTION_REPORT` filing may only be made when the docket's
        complaint has reached one of `UPHELD`, `DISMISSED` or `WITHDRAWN`, or it
        is rejected with `ERR_COMPLAINT_NOT_TERMINAL`; it records
        `resolution_report_ref` from the supplied `evidence_ref` and
        `resolution_report_filed_at` as the logical clock."

        Design: Difficulty/cross_entity_state_dependency/resolution_report_filing_requires_terminal_complaint
        """
        _, complaint_id, inquiry_id = _docket_on_investigated_complaint()

        response = _file(
            inquiry_id,
            FilingType.RESOLUTION_REPORT.value,
            DISMISSED_RESOLUTION_EVIDENCE_REF,
            "Premature resolution report",
        )
        validate_error(response, ApiErrorId.ERR_COMPLAINT_NOT_TERMINAL.value)

        assert (
            _read_complaint(complaint_id)["state"]
            == ComplaintState.UNDER_INVESTIGATION.value
        ), "the complaint that gated the filing is still under investigation"

        docket = _read_docket(inquiry_id)
        assert docket["state"] == RegulatorInquiryState.RECEIVED.value, (
            "a refused filing must not fork the docket"
        )
        assert docket["resolution_report_ref"] is None
        assert docket["resolution_report_filed_at"] is None

    def test_dismissed_complaint_admits_the_resolution_report(self):
        """`DISMISSED` is inside the branch's accepted set of three states.

        PRD: "A `RESOLUTION_REPORT` filing may only be made when the docket's
        complaint has reached one of `UPHELD`, `DISMISSED` or `WITHDRAWN`, or it
        is rejected with `ERR_COMPLAINT_NOT_TERMINAL`; it records
        `resolution_report_ref` from the supplied `evidence_ref` and
        `resolution_report_filed_at` as the logical clock."

        Design: Difficulty/cross_entity_state_dependency/resolution_report_filing_requires_terminal_complaint
        """
        _, complaint_id, inquiry_id = _docket_on_investigated_complaint()

        dismiss_complaint(
            complaint_id, resolution_note="Measurement did not reproduce"
        )
        assert (
            _read_complaint(complaint_id)["state"] == ComplaintState.DISMISSED.value
        ), "the complaint must be DISMISSED before the report branch is admissible"

        filed = _file_resolution_report(
            inquiry_id,
            evidence_ref=DISMISSED_RESOLUTION_EVIDENCE_REF,
            summary="Dismissed after investigation",
        )

        assert filed["state"] == RegulatorInquiryState.EVIDENCE_ASSEMBLY.value, (
            "the admitted filing forks RECEIVED → EVIDENCE_ASSEMBLY"
        )
        assert filed["resolution_report_ref"] == DISMISSED_RESOLUTION_EVIDENCE_REF
        _assert_instant(filed, "resolution_report_filed_at", FIRST_FILING_AT)

    def test_report_branch_alone_neither_joins_nor_permits_closure(self):
        """The gate the complaint opened only unlocks one of the two branches.

        PRD: "Closing the docket carries a `closure_note` and is only admissible
        from `RESPONSE_COMPLETE`; a docket still in `RECEIVED` or
        `EVIDENCE_ASSEMBLY` answers `ERR_INQUIRY_FILINGS_INCOMPLETE`."

        Design: Difficulty/cross_entity_state_dependency/resolution_report_filing_requires_terminal_complaint
        """
        _, complaint_id, inquiry_id = _docket_on_investigated_complaint()

        dismiss_complaint(
            complaint_id, resolution_note="Measurement did not reproduce"
        )
        _file_resolution_report(
            inquiry_id,
            evidence_ref=DISMISSED_RESOLUTION_EVIDENCE_REF,
            summary="Dismissed after investigation",
        )

        docket = _read_docket(inquiry_id)
        assert docket["technical_packet_filed_at"] is None, (
            "the technical branch is still untaken"
        )
        assert docket["state"] != RegulatorInquiryState.RESPONSE_COMPLETE.value, (
            "one non-null branch timestamp cannot fire the join"
        )
        assert docket["state"] == RegulatorInquiryState.EVIDENCE_ASSEMBLY.value

        response = _close(inquiry_id, "Docket answered on both branches")
        validate_error(response, ApiErrorId.ERR_INQUIRY_FILINGS_INCOMPLETE.value)

        assert (
            _read_docket(inquiry_id)["state"]
            == RegulatorInquiryState.EVIDENCE_ASSEMBLY.value
        ), "the refused closure leaves the docket assembling evidence"
