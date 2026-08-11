"""Case intake, posture transitions, terminal lockdown, and conversion cascade."""
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS, create_case_payload, create_asset_payload,
    create_avoidance_action_payload, make_trustee_headers,
    create_creditor, create_case, create_asset, file_claim, get_case,
    setup_case_in_claims_administration,
)

TRUSTEE = TEST_USERS["trustee_headers"]
CLERK = TEST_USERS["clerk_headers"]
COURT = TEST_USERS["court_headers"]


class TestCaseCreation:
    def test_case_creation_assigns_open_status_and_defaults(self, api):
        """PRD §3.1: "A new case begins in `OPEN` posture with `bar_date_noticed`
        false, `no_asset_report_filed` false, and both derived totals at zero."
        PRD §2.5: "`version` (integer): a system-managed integer that increments
        with every modification to the resource."

        Design: Corner/entities/case_creation_assigns_open_status_and_version_1
        """
        resp = api.create_case(create_case_payload(case_number="26-20001"), CLERK)
        data = validate_success(resp, expected_status=201)
        assert data["status"] == "OPEN"
        assert data["bar_date_noticed"] is False
        assert data["no_asset_report_filed"] is False
        assert data["estate_cash_on_hand_cents"] == 0
        assert data["allowed_claims_total_cents"] == 0
        assert data["claim_bar_date"] is None
        # The PRD declares version an integer without pinning its initial value.
        assert isinstance(data["version"], int)

    def test_case_creation_duplicate_case_number_rejected(self, api):
        """PRD §3.1: "A `Clerk` opens a bankruptcy case by supplying the court
        docket number as `case_number` (unique across all cases; a collision is
        rejected with `ERR_DUPLICATE`), the debtor's full legal name as
        `debtor_name`, the petition filing date as `filed_on` (the anchor from
        which every preference lookback window is measured), the federal judicial
        district code as `district`, and the `trustee_user_id` of the panel
        trustee being assigned."

        Design: Corner/entities/case_creation_duplicate_case_number_rejected
        """
        first = api.create_case(create_case_payload(case_number="26-20002"), CLERK)
        validate_success(first, expected_status=201)
        resp = api.create_case(
            create_case_payload(case_number="26-20002", debtor_name="D2",
                                filed_on="2026-01-16T00:00:00Z"), CLERK)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE)


class TestTerminalLockdown:
    def test_case_closed_blocks_further_mutation(self, api):
        """PRD §2.6: "Once a case reaches `CLOSED` or `CONVERTED_DISMISSED` it is
        frozen: no case-scoped mutation endpoint may operate on it, and any such
        attempt is rejected with `ERR_CASE_CLOSED` (HTTP 409)."
        PRD §3.1: "Filing sets `no_asset_report_filed` to true and closes the
        case; each of these case-level posture changes increments the case's
        `version`."

        Design: Corner/state_machines/case_closed_blocks_further_mutation
        """
        case = create_case(case_number="26-20015")
        closed = validate_success(api.file_no_asset_report(case["id"], TRUSTEE))
        assert closed["status"] == "CLOSED"
        assert closed["no_asset_report_filed"] is True
        resp = api.create_asset(case["id"], create_asset_payload(), TRUSTEE)
        validate_error(resp, ApiErrorId.ERR_CASE_CLOSED)


class TestConversionCascade:
    def test_convert_or_dismiss_cascades_children(self, api):
        """PRD §3.1: "Conversion cascades atomically through the aggregate —
        every claim in `FILED`, `UNDER_REVIEW`, or `OBJECTED` becomes `WITHDRAWN`;
        every asset in `SCHEDULED`, `UNDER_INVESTIGATION`, `MARKED_FOR_SALE`, or
        `IN_AUCTION` becomes `ABANDONED`; and every avoidance action not already
        in `RESCINDED`, `ABANDONED`, `SETTLED`, or `JUDGMENT` becomes
        `ABANDONED` — and the case's `version` increments."

        Design: Corner/state_machines/convert_or_dismiss_cascades_children
        """
        ctx = setup_case_in_claims_administration(case_number="26-20013")
        case_id = ctx["case"]["id"]
        cred_id = ctx["creditor"]["id"]
        claim = file_claim(case_id, cred_id)
        action = get_success_data(api_client.create_avoidance_action(
            case_id,
            create_avoidance_action_payload(transferee_creditor_id=cred_id,
                                            transfer_amount_cents=50000,
                                            demand_amount_cents=50000),
            TRUSTEE))

        validate_success(api.convert_or_dismiss(case_id, COURT))

        claim_after = validate_success(api.get_claim(claim["id"], COURT))
        asset_after = validate_success(api.get_asset(ctx["asset"]["id"], COURT))
        action_after = validate_success(api.get_avoidance_action(action["id"], COURT))
        assert claim_after["status"] == "WITHDRAWN"
        assert asset_after["status"] == "ABANDONED"
        assert action_after["status"] == "ABANDONED"
