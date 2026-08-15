"""Expirable credentials: expiry-risk scoring, lapse/suspension cascades,
renewal reinstatement, and scheduled term expiry."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    add_credential,
    create_approved_member,
    create_member_record,
    create_member_with_active_grant,
    flip_grant_active_via_fppe,
    refresh_credential,
    refresh_grant,
    refresh_member,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

COORD = TEST_USERS["coordinator_headers"]

SURG_CRITERIA = {
    "specialty_code": "SURG",
    "privilege_line": "SURG-GENERAL",
    "min_training_months": 24,
    "min_case_volume_24mo": 20,
    "required_board_cert": True,
    "fppe_case_count": 1,
    "volume_tier_table": [
        {"tier_name": "BASIC", "min_cases": 20, "score_multiplier": 0.10},
    ],
}


def _member_with_lapsing_license(name="Dr. Lapse", npdb="NPDB-L1"):
    """ACTIVE member with one ACTIVE SURG-GENERAL grant, a long-lived
    BOARD_CERT, and a STATE_LICENSE expiring 2026-08-10."""
    ws = create_approved_member(
        name, npdb,
        criteria_overrides=SURG_CRITERIA,
        credentials=[
            {"credential_kind": "BOARD_CERT", "credential_number": "BC-L1",
             "issued_on": "2026-01-01T00:00:00Z",
             "expires_on": "2027-08-01T00:00:00Z"},
            {"credential_kind": "STATE_LICENSE", "credential_number": "SL-L1",
             "issued_on": "2025-01-01T00:00:00Z",
             "expires_on": "2026-08-10T00:00:00Z"},
        ],
        item_kind="STATE_LICENSE",
        is_primary_source=True,
        delineation_overrides={"privilege_line": "SURG-GENERAL",
                               "documented_training_months": 40,
                               "documented_cases_24mo": 120})
    flip_grant_active_via_fppe(ws)
    return ws


def _state_license_of(member_id, api):
    data, _meta = validate_paginated(
        api.list_expirable_credentials(
            COORD, params={"member_id": member_id,
                           "credential_kind": "STATE_LICENSE"}))
    return data[0]


class TestCredentialRiskVariants:
    def _member_with_malpractice(self):
        set_clock("2026-08-01T00:00:00Z")
        member = create_member_record("Dr. B", "NPDB-B", "EMED")
        add_credential(member["id"], "MALPRACTICE_INSURANCE", "MI-9",
                       "2026-07-15T00:00:00Z", "2026-08-25T00:00:00Z")
        return member

    def test_credential_risk_forward_looking_score(self, api):
        """PRD §3.6: "A credential already past its expiry contributes one
        hundred points; one expiring in thirty days or fewer contributes fifty
        points; one expiring in more than thirty but no more than ninety days
        contributes twenty-five points; anything further out contributes
        nothing. Contributions from `STATE_LICENSE` and `MALPRACTICE_INSURANCE`
        credentials are then multiplied by one-and-a-half."

        Twenty-four days to expiry: 50 points x 1.5 = 75.00.

        Design: Difficulty/dual_variant_calc/credential_risk_forward_vs_chronological
        """
        member = self._member_with_malpractice()
        data = validate_success(api.get_credential_risk(member["id"], COORD))
        assert data["risk_score"] == 75.00

    def test_credential_risk_chronological_asof_variant(self, api):
        """PRD §3.6: "A retroactive read serves auditors: the same calculation
        can be evaluated as of a past instant supplied as `as_of`, considering
        only credentials whose `issued_on` is on or before that instant and
        measuring days-to-expiry from it rather than from the current clock."

        As of 2026-07-01 the credential (issued 2026-07-15) did not yet exist:
        the score is 0.00 while the live score is 75.00.

        Design: Difficulty/dual_variant_calc/credential_risk_forward_vs_chronological
        """
        member = self._member_with_malpractice()
        asof = validate_success(api.get_credential_risk(
            member["id"], COORD, params={"as_of": "2026-07-01T00:00:00Z"}))
        live = validate_success(api.get_credential_risk(member["id"], COORD))
        assert asof["risk_score"] == 0.00
        assert live["risk_score"] == 75.00
        assert asof["risk_score"] != live["risk_score"], (
            "The same credential legitimately scores differently under the "
            "live and chronological variants")


class TestRiskThresholdBoundary:
    def test_credential_risk_threshold_exactly_75_flags_suspension(self, api):
        """PRD §3.6: "one expiring in thirty days or fewer contributes fifty
        points; one expiring in more than thirty but no more than ninety days
        contributes twenty-five points" and "a score at or above the suspension
        threshold of 75.00 flags the member for the auto-suspension cascade
        below."

        A STATE_LICENSE thirty days out scores 50 x 1.5 = 75.00, exactly at
        threshold; thirty-one days out drops to the 25-point tier: 37.50.

        Design: Corner/calculations/credential_risk_threshold_exactly_75_flags_suspension
        """
        set_clock("2026-08-01T00:00:00Z")
        mr30 = create_member_record("Dr. R30", "NPDB-R30", "CARD")
        add_credential(mr30["id"], "STATE_LICENSE", "SL-30",
                       "2025-01-01T00:00:00Z", "2026-08-31T00:00:00Z")
        mr31 = create_member_record("Dr. R31", "NPDB-R31", "CARD")
        add_credential(mr31["id"], "STATE_LICENSE", "SL-31",
                       "2025-01-01T00:00:00Z", "2026-09-01T00:00:00Z")

        risk30 = validate_success(api.get_credential_risk(mr30["id"], COORD))
        risk31 = validate_success(api.get_credential_risk(mr31["id"], COORD))
        assert risk30["risk_score"] == 75.00
        assert risk31["risk_score"] == 37.50


class TestCredentialRenewalGuards:
    def test_error_credential_renew_not_lapsed(self, api):
        """PRD §3.6: "A coordinator renews a credential only from `LAPSED`
        (`ERR_CREDENTIAL_NOT_LAPSED`)".

        Design: Corner/errors/error_credential_renew_not_lapsed
        """
        member = create_member_record("Dr. Curr", "NPDB-CUR", "CARD")
        credential = add_credential(member["id"], "STATE_LICENSE", "SL-CUR",
                                    "2026-01-01T00:00:00Z", "2027-01-01T00:00:00Z")

        resp = api.renew_expirable_credential(
            credential["id"],
            {"credential_number": "SL-CUR-2",
             "issued_on": "2026-08-01T00:00:00Z",
             "expires_on": "2028-01-01T00:00:00Z"},
            COORD)
        validate_error(resp, ApiErrorId.ERR_CREDENTIAL_NOT_LAPSED, 409)
        assert refresh_credential(
            credential["id"])["credential_status"] == "CURRENT"


class TestLapseCascade:
    def test_credential_lapse_suspends_grant(self, api):
        """PRD §3.6: "Lapse is automatic: the instant the clock reaches
        `expires_on`, a `CURRENT` credential moves to `LAPSED`. That single flip
        is the second cascade link. The member's risk score recomputes; and when
        the lapsed kind is `STATE_LICENSE`, `BOARD_CERT`, or
        `MALPRACTICE_INSURANCE`, every `ACTIVE` privilege grant of the member
        whose specialty criteria require that kind moves to `SUSPENDED`, with
        `suspension_reason` recording the lapsed `credential_kind`."

        Design: Difficulty/transitive_cascade/credential_lapse_three_hop_cascade
        """
        ws = _member_with_lapsing_license()
        license_row = _state_license_of(ws["member"]["id"], api)

        set_clock("2026-08-11T00:00:00Z")

        lapsed = refresh_credential(license_row["id"])
        assert lapsed["credential_status"] == "LAPSED", (
            "hop 1: the credential lapses when the clock reaches expires_on")

        grant = refresh_grant(ws["grant"]["id"])
        assert grant["grant_status"] == "SUSPENDED", (
            "hop 2: the ACTIVE grant suspends on the mandatory-kind lapse")
        assert grant["suspension_reason"] == "STATE_LICENSE"

    def test_credential_lapse_recomputes_member_counters(self, api):
        """PRD §3.6: "Each suspended grant decrements the member's
        `active_privilege_line_count` by one, and `privilege_posture` is
        recomputed — falling to `NONE` when every line is suspended, or to
        `EMERGENCY_ONLY` when a temporary privilege still stands."

        Design: Difficulty/transitive_cascade/credential_lapse_three_hop_cascade
        """
        ws = _member_with_lapsing_license()
        assert ws["member"]["active_privilege_line_count"] == 1

        set_clock("2026-08-11T00:00:00Z")

        member = refresh_member(ws["member"]["id"])
        assert member["active_privilege_line_count"] == 0, (
            "hop 3: the sole ACTIVE line is gone")
        assert member["privilege_posture"] == "NONE"


class TestSuspendReinstateInvariant:
    def test_suspend_reinstate_count_after_lapse(self, api):
        """PRD §3.6: "Each suspended grant decrements the member's
        `active_privilege_line_count` by one".

        Design: Difficulty/compensating_invariant/grant_suspend_reinstate_preserves_active_line_count
        """
        ws = _member_with_lapsing_license("Dr. Inv", "NPDB-INV1")
        assert ws["member"]["active_privilege_line_count"] == 1

        set_clock("2026-08-11T00:00:00Z")

        member = refresh_member(ws["member"]["id"])
        assert member["active_privilege_line_count"] == 0
        assert refresh_grant(ws["grant"]["id"])["grant_status"] == "SUSPENDED"

    def test_suspend_reinstate_restores_count_and_clears_reason(self, api):
        """PRD §3.6: "The reinstatement cascade follows: every grant of the
        member sitting in `SUSPENDED` whose `suspension_reason` matches the
        renewed credential's kind moves back to `ACTIVE`, its `suspension_reason`
        is cleared, the member's `active_privilege_line_count` is incremented
        accordingly, posture is recomputed, and the risk score recomputes once
        more."
        PRD §3.6: "Renewal writes a fresh `CURRENT` row whose
        `supersedes_credential_id` points at the old row, which itself moves to
        the terminal `RENEWED` state".

        Design: Difficulty/compensating_invariant/grant_suspend_reinstate_preserves_active_line_count
        """
        ws = _member_with_lapsing_license("Dr. Inv", "NPDB-INV1")
        license_row = _state_license_of(ws["member"]["id"], api)
        count_before = ws["member"]["active_privilege_line_count"]

        set_clock("2026-08-11T00:00:00Z")
        assert refresh_member(
            ws["member"]["id"])["active_privilege_line_count"] == 0

        validate_success(api.renew_expirable_credential(
            license_row["id"],
            {"credential_number": "SL-INV-2",
             "issued_on": "2026-08-11T00:00:00Z",
             "expires_on": "2028-08-10T00:00:00Z"},
            COORD))

        member = refresh_member(ws["member"]["id"])
        assert member["active_privilege_line_count"] == count_before, (
            "Suspend + reinstate must show zero net drift on the line count")
        grant = refresh_grant(ws["grant"]["id"])
        assert grant["grant_status"] == "ACTIVE"
        assert grant["suspension_reason"] is None
        assert refresh_credential(
            license_row["id"])["credential_status"] == "RENEWED"


class TestScheduledTermExpiry:
    def test_scheduled_term_expiry_lapses_member_and_grants(self, api):
        """PRD §3.4: "More generally, whenever the clock passes
        `current_term_end` with no approved reappointment in place, an `ACTIVE`
        member moves to `LAPSED`, all their `ACTIVE` grants move to `EXPIRED`,
        and posture falls to `NONE`."
        PRD §3.5: "Expiry is clock-driven: the instant the clock reaches
        `effective_until`, an `ACTIVE` grant moves to `EXPIRED`, with the same
        recomputation."

        Design: Corner/cross_cutting_layers/scheduled_term_expiry_lapses_member_and_grants
        """
        ws = create_member_with_active_grant("Dr. Exp", "NPDB-EXP")
        member_id = ws["member"]["id"]
        assert ws["grant"]["grant_status"] == "ACTIVE"

        set_clock("2028-08-01T00:00:00Z")

        member = refresh_member(member_id)
        assert member["membership_status"] == "LAPSED"
        assert member["privilege_posture"] == "NONE"
        assert member["active_privilege_line_count"] == 0
        assert refresh_grant(ws["grant"]["id"])["grant_status"] == "EXPIRED"
