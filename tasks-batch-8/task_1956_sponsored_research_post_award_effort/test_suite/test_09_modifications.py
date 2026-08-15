"""Modification requests: NCE routing on nce_count, the 25% rebudget
significance boundary, the zero-sum invariant with F&A compensation, OCC on
award version, and NCE timing (PRD §3.8)."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    api_client, TEST_USERS,
    create_modification_request_payload,
    setup_sponsor_pi, create_active_award, get_award_version,
    ApiErrorId,
)

SPO = TEST_USERS["spo_headers"]
GC = TEST_USERS["coordinator_headers"]
GA = TEST_USERS["accountant_headers"]
SO = TEST_USERS["sponsor_official_headers"]
ADMIN = TEST_USERS["system_admin_headers"]


_REBUDGET_LINES_SPEC = [
    {"category": "PERSONNEL_SALARIES", "authorized_cents": 4_000_000},
    {"category": "FRINGE_BENEFITS", "authorized_cents": 2_400_000},
    {"category": "TRAVEL", "authorized_cents": 600_000},
    {"category": "MATERIALS_SUPPLIES", "authorized_cents": 600_000},
    {"category": "OTHER_DIRECT", "authorized_cents": 400_000},
    {"category": "EQUIPMENT", "authorized_cents": 500_000},
    {"category": "SUBAWARDS", "authorized_cents": 1_000_000,
     "mtdc_eligible_cents": 250_000},
]
# directs 9500000; MTDC = 9500000 - 500000 - 1000000 + 250000 = 8250000;
# F&A = round(0.5 * 8250000) = 4125000; grand total 13625000.
_REBUDGET_OBLIGATED = 13_625_000


def _setup_rebudget_award(api, award_number):
    sponsor, pi = setup_sponsor_pi()
    award, lines = create_active_award(
        sponsor["id"], pi["id"], award_number, _REBUDGET_LINES_SPEC,
        _REBUDGET_OBLIGATED)
    return award, lines


class TestRebudgetExactly25PctBoundary:
    """Difficulty instance: exactly 25% is not significant; one cent over is."""

    def test_exactly_25pct_approves_under_grantee_authority(self, api):
        """PRD §3.8: "the change is significant when the baseline is positive
        and the absolute change times one hundred exceeds twenty-five times the
        baseline — exactly 25% is not significant — or when the baseline is
        zero and the new value is positive."
        PRD §3.8: "when `requires_sponsor` is false the request is `APPROVED`
        immediately under grantee authority and its effects apply..."
        PRD §3.8: "...grantee-authority approvals leave baselines untouched."

        Design: Difficulty/boundary_precision_check/rebudget_exactly_25pct_not_significant_vs_one_cent_over
        """
        award, lines = _setup_rebudget_award(api, "R-001")
        # Every listed line moves by exactly 25% of its 4000000/2400000/600000/
        # 400000 baseline (new 5000000 / 1800000 / 450000 / 300000).
        m1 = validate_success(api.create_modification_request(
            create_modification_request_payload(
                award["id"], get_award_version(award["id"]),
                mod_type="REBUDGET", extension_months=None,
                justification="exactly-25-percent salary realignment",
                rebudget_lines=[
                    {"budget_line_id": lines["PERSONNEL_SALARIES"]["id"],
                     "new_authorized_cents": 5_000_000},
                    {"budget_line_id": lines["FRINGE_BENEFITS"]["id"],
                     "new_authorized_cents": 1_800_000},
                    {"budget_line_id": lines["TRAVEL"]["id"],
                     "new_authorized_cents": 450_000},
                    {"budget_line_id": lines["MATERIALS_SUPPLIES"]["id"],
                     "new_authorized_cents": 450_000},
                    {"budget_line_id": lines["OTHER_DIRECT"]["id"],
                     "new_authorized_cents": 300_000},
                ]), GC), 201)
        assert m1["requires_sponsor"] is False
        validate_success(api.submit_modification(m1["id"], GC), 200)
        approved = validate_success(api.internal_approve_modification(m1["id"], SPO), 200)
        assert approved["status"] == "APPROVED"
        sal = validate_success(api.get_budget_line(
            lines["PERSONNEL_SALARIES"]["id"], GA), 200)
        assert sal["authorized_cents"] == 5_000_000
        assert sal["baseline_authorized_cents"] == 4_000_000  # not refreshed

    def test_one_cent_over_25pct_routes_to_sponsor(self, api):
        """PRD §3.8: "the change is significant when the baseline is
        positive and the absolute change times one hundred exceeds twenty-five
        times the baseline — exactly 25% is not significant — or when the
        baseline is zero and the new value is positive."
        PRD §3.8: "when true it routes to `SPONSOR_REVIEW`, where a
        `SponsorOfficial` records a `decision` of approve or deny with an
        optional `reason` — approval applies the effects, denial moves the
        request to `DENIED` and sets `sponsor_decision_reason`."
        PRD §3.8: "A rebudget writes each listed line's `authorized_cents` to
        its new value, recomputes the `F_AND_A` line's authorization over the
        new authorized bases, and — only when approval came through the
        sponsor-decision channel — refreshes every line's
        `baseline_authorized_cents` to its current `authorized_cents`;
        grantee-authority approvals leave baselines untouched."

        Design: Difficulty/boundary_precision_check/rebudget_exactly_25pct_not_significant_vs_one_cent_over
        """
        award, lines = _setup_rebudget_award(api, "R-002")
        # SAL new 5000001: 1000001 * 100 > 25 * 4000000 -> significant.
        m2 = validate_success(api.create_modification_request(
            create_modification_request_payload(
                award["id"], get_award_version(award["id"]),
                mod_type="REBUDGET", extension_months=None,
                justification="one-cent-over salary realignment plan",
                rebudget_lines=[
                    {"budget_line_id": lines["PERSONNEL_SALARIES"]["id"],
                     "new_authorized_cents": 5_000_001},
                    {"budget_line_id": lines["FRINGE_BENEFITS"]["id"],
                     "new_authorized_cents": 1_800_000},
                    {"budget_line_id": lines["TRAVEL"]["id"],
                     "new_authorized_cents": 450_000},
                    {"budget_line_id": lines["MATERIALS_SUPPLIES"]["id"],
                     "new_authorized_cents": 450_000},
                    {"budget_line_id": lines["OTHER_DIRECT"]["id"],
                     "new_authorized_cents": 299_999},
                ]), GC), 201)
        assert m2["requires_sponsor"] is True
        validate_success(api.submit_modification(m2["id"], GC), 200)
        routed = validate_success(api.internal_approve_modification(m2["id"], SPO), 200)
        assert routed["status"] == "SPONSOR_REVIEW"
        approved = validate_success(api.sponsor_decision_modification(
            m2["id"], {"decision": "APPROVE"}, SO), 200)
        assert approved["status"] == "APPROVED"
        sal = validate_success(api.get_budget_line(
            lines["PERSONNEL_SALARIES"]["id"], GA), 200)
        assert sal["baseline_authorized_cents"] == 5_000_001  # refreshed


class TestRebudgetIntoEquipmentRequiresFandaCompensation:
    def test_unbalanced_equipment_shift_fails_zero_sum(self, api):
        """PRD §3.8: "A rebudget must satisfy the grand-total invariant: after
        applying the new authorizations to the listed direct lines and
        recomputing the `F_AND_A` authorization over authorized bases per §3.1,
        the grand total must still equal `total_obligated_cents` exactly
        (`ERR_REBUDGET_NOT_ZERO_SUM`)."

        Design: Corner/calculations/rebudget_into_equipment_requires_fanda_compensation
        """
        award, lines = _setup_rebudget_award(api, "RB-001")
        # +300000 into EQUIPMENT, -300000 out of FRINGE: directs stay 9500000
        # but MTDC drops 300000 -> F&A drops 150000 -> total 13475000.
        m1 = validate_success(api.create_modification_request(
            create_modification_request_payload(
                award["id"], get_award_version(award["id"]),
                mod_type="REBUDGET", extension_months=None,
                justification="unbalanced equipment purchase request",
                rebudget_lines=[
                    {"budget_line_id": lines["EQUIPMENT"]["id"],
                     "new_authorized_cents": 800_000},
                    {"budget_line_id": lines["FRINGE_BENEFITS"]["id"],
                     "new_authorized_cents": 2_100_000},
                ]), GC), 201)
        res = api.submit_modification(m1["id"], GC)
        validate_error(res, ApiErrorId.ERR_REBUDGET_NOT_ZERO_SUM.value)

    def test_compensating_boost_balances_and_recomputes_fanda(self, api):
        """PRD §3.8: "Because F&A moves with the MTDC base, shifting cents
        into a non-MTDC category such as equipment demands a compensating boost
        elsewhere in MTDC-bearing lines — at a 5000-basis-point rate, moving m
        cents into equipment requires a net boost of m/3 cents across other
        MTDC-bearing lines."
        PRD §3.8: "The flag is true when any line is significant, or any listed
        `EQUIPMENT` line's new value exceeds its current value, or any listed
        `PARTICIPANT_SUPPORT` line's new value falls below its current
        value."

        Design: Corner/calculations/rebudget_into_equipment_requires_fanda_compensation
        """
        award, lines = _setup_rebudget_award(api, "RB-001")
        m1 = validate_success(api.create_modification_request(
            create_modification_request_payload(
                award["id"], get_award_version(award["id"]),
                mod_type="REBUDGET", extension_months=None,
                justification="unbalanced equipment purchase request",
                rebudget_lines=[
                    {"budget_line_id": lines["EQUIPMENT"]["id"],
                     "new_authorized_cents": 800_000},
                    {"budget_line_id": lines["FRINGE_BENEFITS"]["id"],
                     "new_authorized_cents": 2_100_000},
                ]), GC), 201)
        api.submit_modification(m1["id"], GC)
        # Balanced variant: +100000 to SAL (MTDC-bearing) restores the total.
        m2 = validate_success(api.create_modification_request(
            create_modification_request_payload(
                award["id"], get_award_version(award["id"]),
                mod_type="REBUDGET", extension_months=None,
                justification="balanced equipment purchase with boost",
                rebudget_lines=[
                    {"budget_line_id": lines["EQUIPMENT"]["id"],
                     "new_authorized_cents": 800_000},
                    {"budget_line_id": lines["FRINGE_BENEFITS"]["id"],
                     "new_authorized_cents": 2_100_000},
                    {"budget_line_id": lines["PERSONNEL_SALARIES"]["id"],
                     "new_authorized_cents": 4_100_000},
                ]), GC), 201)
        assert m2["requires_sponsor"] is True   # net increase into EQUIPMENT
        validate_success(api.submit_modification(m2["id"], GC), 200)
        validate_success(api.internal_approve_modification(m2["id"], SPO), 200)
        approved = validate_success(api.sponsor_decision_modification(
            m2["id"], {"decision": "APPROVE"}, SO), 200)
        assert approved["status"] == "APPROVED"
        fa_lines = validate_success(api.list_budget_lines(
            GA, params={"award_id": award["id"], "category": "F_AND_A"}), 200)
        # new MTDC = 8050000; F&A = round(0.5 * 8050000) = 4025000.
        assert fa_lines[0]["authorized_cents"] == 4_025_000


class TestNceRouting:
    def test_first_nce_grantee_second_nce_sponsor(self, api):
        """PRD §3.8: "For a no-cost extension the flag is true when the award's
        `nce_count` is already at least 1 — the first extension is a
        grantee-authority action, later ones need the sponsor."
        PRD §3.8: "A no-cost extension adds `extension_months` calendar months
        to `current_end_date` (the day clamped to month end), increments
        `nce_count`..."

        Design: Corner/state_machines/modification_nce_first_grantee_second_sponsor
        """
        sponsor, pi = setup_sponsor_pi()
        award, _lines = create_active_award(
            sponsor["id"], pi["id"], "N1-001",
            [{"category": "TRAVEL", "authorized_cents": 100_000}], 150_000)
        m1 = validate_success(api.create_modification_request(
            create_modification_request_payload(
                award["id"], get_award_version(award["id"]),
                mod_type="NO_COST_EXTENSION", extension_months=6,
                justification="first no-cost extension request here"), GC), 201)
        assert m1["requires_sponsor"] is False
        validate_success(api.submit_modification(m1["id"], GC), 200)
        st1 = validate_success(api.internal_approve_modification(m1["id"], SPO), 200)
        assert st1["status"] == "APPROVED"
        award_after = validate_success(api.get_award(award["id"], GA), 200)
        assert award_after["current_end_date"] == "2027-06-30T00:00:00Z"
        assert award_after["nce_count"] == 1
        m2 = validate_success(api.create_modification_request(
            create_modification_request_payload(
                award["id"], award_after["version"],
                mod_type="NO_COST_EXTENSION", extension_months=3,
                justification="second no-cost extension request here"), GC), 201)
        assert m2["requires_sponsor"] is True
        validate_success(api.submit_modification(m2["id"], GC), 200)
        st2 = validate_success(api.internal_approve_modification(m2["id"], SPO), 200)
        assert st2["status"] == "SPONSOR_REVIEW"
        st3 = validate_success(api.sponsor_decision_modification(
            m2["id"], {"decision": "APPROVE"}, SO), 200)
        assert st3["status"] == "APPROVED"
        award_final = validate_success(api.get_award(award["id"], GA), 200)
        assert award_final["current_end_date"] == "2027-09-30T00:00:00Z"
        assert award_final["nce_count"] == 2

    def test_nce_submit_after_end_date_rejected(self, api):
        """PRD §3.8: "A no-cost extension must be submitted while the logical
        clock is still before `current_end_date` (`ERR_NCE_AFTER_END_DATE`)."

        Design: Corner/errors/nce_submit_after_end_date_rejected
        """
        sponsor, pi = setup_sponsor_pi()
        award, _lines = create_active_award(
            sponsor["id"], pi["id"], "NE-001",
            [{"category": "TRAVEL", "authorized_cents": 100_000}], 150_000)
        version = get_award_version(award["id"])
        get_success_data(api.set_clock({"to_iso8601": "2027-01-15T00:00:00Z"}, ADMIN))
        m = validate_success(api.create_modification_request(
            create_modification_request_payload(
                award["id"], version, mod_type="NO_COST_EXTENSION",
                extension_months=6,
                justification="late extension attempt after end date"), GC), 201)
        res = api.submit_modification(m["id"], GC)
        validate_error(res, ApiErrorId.ERR_NCE_AFTER_END_DATE.value)
        award_after = validate_success(api.get_award(award["id"], GA), 200)
        assert award_after["current_end_date"] == "2026-12-31T00:00:00Z"


class TestOccOnModificationCreate:
    def test_modification_create_stale_award_version(self, api):
        """PRD §2.6: "Creating a modification request likewise requires
        `expected_award_version` matching the award's current `version`, with
        the same `ERR_STALE_AWARD_VERSION` (HTTP 412) on mismatch, because
        rebudget line sets and no-cost-extension arithmetic are computed
        against the baselines and `current_end_date` the client observed."

        Design: Corner/cross_cutting_layers/occ_modification_create_stale_award_version
        """
        sponsor, pi = setup_sponsor_pi()
        award, _lines = create_active_award(
            sponsor["id"], pi["id"], "OC-002",
            [{"category": "TRAVEL", "authorized_cents": 100_000}], 150_000)
        v = award["version"]
        m1 = validate_success(api.create_modification_request(
            create_modification_request_payload(
                award["id"], v, mod_type="NO_COST_EXTENSION", extension_months=6,
                justification="first extension at observed version"), GC), 201)
        assert m1["award_id"] == award["id"]
        res = api.create_modification_request(
            create_modification_request_payload(
                award["id"], v, mod_type="NO_COST_EXTENSION", extension_months=3,
                justification="second extension at stale version"), GC)
        validate_error(res, ApiErrorId.ERR_STALE_AWARD_VERSION.value)


class TestRbacOnSponsorDecision:
    def test_coordinator_cannot_issue_sponsor_decision(self, api):
        """PRD §2.1: "`SponsorOfficial` is the sponsor-side actor: it ...
        decides sponsor-review modifications..." PRD §2.1: "a role not
        permitted on the endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP
        403)."

        Design: Corner/rbac/coordinator_cannot_issue_sponsor_decision
        """
        award, lines = _setup_rebudget_award(api, "RB-900")
        m = validate_success(api.create_modification_request(
            create_modification_request_payload(
                award["id"], get_award_version(award["id"]),
                mod_type="REBUDGET", extension_months=None,
                justification="significant salary realignment request",
                rebudget_lines=[
                    {"budget_line_id": lines["PERSONNEL_SALARIES"]["id"],
                     "new_authorized_cents": 5_000_001},
                    {"budget_line_id": lines["FRINGE_BENEFITS"]["id"],
                     "new_authorized_cents": 1_800_000},
                    {"budget_line_id": lines["TRAVEL"]["id"],
                     "new_authorized_cents": 450_000},
                    {"budget_line_id": lines["MATERIALS_SUPPLIES"]["id"],
                     "new_authorized_cents": 450_000},
                    {"budget_line_id": lines["OTHER_DIRECT"]["id"],
                     "new_authorized_cents": 299_999},
                ]), GC), 201)
        validate_success(api.submit_modification(m["id"], GC), 200)
        routed = validate_success(api.internal_approve_modification(m["id"], SPO), 200)
        assert routed["status"] == "SPONSOR_REVIEW"
        res = api.sponsor_decision_modification(m["id"], {"decision": "APPROVE"}, GC)
        validate_error(res, ApiErrorId.ERR_FORBIDDEN_ROLE.value)
        m_after = validate_success(api.get_modification_request(m["id"], GA), 200)
        assert m_after["status"] == "SPONSOR_REVIEW"
