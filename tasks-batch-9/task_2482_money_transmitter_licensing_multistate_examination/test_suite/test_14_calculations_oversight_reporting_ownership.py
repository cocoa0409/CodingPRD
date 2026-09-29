"""Pinned arithmetic on three families: oversight scoring, the reporting calendar
and the two ownership figures of the control chain.

Every expected value in this file is computed by hand from the PRD prose and
written down as a literal, so a formula that is right in shape but wrong in
rounding, in weight or in evaluation order fails here. The logical clock is left
at its process-start instant of 2026-08-01T00:00:00Z throughout.
"""

from prd_bench_local_runner.testing import get_success_data, validate_success

from test_helpers import MoneyTransmitterApiClient
from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as fx
from test_helpers.test_users import (
    MANAGER_HEADERS,
    OFFICER_HEADERS,
    make_delegate_operator_headers,
    make_state_regulator_headers,
)


def _instant(value):
    # Reduce an ISO 8601 UTC stamp to second precision for comparison.
    assert value is not None, "expected a timestamp, got null"
    return value[:19]


def _review(api, delegate_id, training, aml, recordkeeping, headers=None):
    # One oversight review submitted through the delegate's own endpoint.
    return validate_success(
        api.submit_oversight_review(
            delegate_id,
            F.oversight_review_payload(training, aml, recordkeeping),
            headers or OFFICER_HEADERS,
        )
    )


# ===========================================================================
# Instance: oversight_score_floors_the_weighted_average
# ===========================================================================


def test_oversight_score_floors_the_weighted_average(
    api: MoneyTransmitterApiClient, licensee: dict
) -> None:
    """A weighted oversight average of 81.85 is floored to 81, never rounded to 82.

    PRD 3.6: "Either a `ComplianceOfficer` — for any delegate — or a `DelegateOperator` acting for its own delegate row submits three component scores, each on a nought-to-one-hundred scale: `training_score`, `aml_test_score` and `recordkeeping_score`."
    PRD 3.6: "The resulting `oversight_score` is the training score weighted at 4000 basis points, plus the anti-money-laundering test score weighted at 3500 basis points, plus the recordkeeping score weighted at 2500 basis points, that sum divided by 10000 and rounded down to a whole number."
    PRD 3.6: "`last_oversight_review_at` is stamped from the logical clock."
    PRD 3.6: "The row starts in `ONBOARDING`, the other statuses being `ACTIVE`, `SUSPENDED` and the terminal `TERMINATED`."
    PRD 2.5: "**Floor** (round down toward zero) governs every division inside the permissible-investment coverage computation, every hop of the ownership attribution chain, the class-multiplier step of the surety bond computation, and the weighted delegate oversight score."
    PRD 2.4: "The server holds a **logical clock** that starts at `2026-08-01T00:00:00Z` when the process starts and never advances on its own."

    Design: Corner/calculations/oversight_score_floors_the_weighted_average
    """
    delegate = fx.create_delegate(api, licensee["id"], legal_name=C.SEED_DELEGATE_NAME)
    assert delegate["oversight_score"] is None
    assert delegate["last_oversight_review_at"] is None

    reviewed = _review(api, delegate["id"], 81, 82, 83)

    # 81 * 4000 = 324000; 82 * 3500 = 287000; 83 * 2500 = 207500.
    # (324000 + 287000 + 207500) / 10000 = 81.85, floored to 81.
    assert reviewed["oversight_score"] == 81

    # The clock has not been moved, so the stamp is the process-start instant.
    assert _instant(reviewed["last_oversight_review_at"]) == "2026-08-01T00:00:00"
    # Scoring alone does not put an agent to work: only activation does.
    assert reviewed["status"] == "ONBOARDING"


def test_oversight_component_weights_are_four_thousand_thirty_five_hundred_and_twenty_five_hundred(
    api: MoneyTransmitterApiClient, licensee: dict
) -> None:
    """Each component carries its own declared basis-point weight and no other.

    PRD 3.6: "The resulting `oversight_score` is the training score weighted at 4000 basis points, plus the anti-money-laundering test score weighted at 3500 basis points, plus the recordkeeping score weighted at 2500 basis points, that sum divided by 10000 and rounded down to a whole number."
    PRD 2.5: "**Floor** (round down toward zero) governs every division inside the permissible-investment coverage computation, every hop of the ownership attribution chain, the class-multiplier step of the surety bond computation, and the weighted delegate oversight score."

    Design: Corner/calculations/oversight_score_floors_the_weighted_average
    """
    training_only = fx.create_delegate(api, licensee["id"], legal_name="Training Only Agents")
    aml_only = fx.create_delegate(api, licensee["id"], legal_name="AML Only Agents")
    records_only = fx.create_delegate(api, licensee["id"], legal_name="Records Only Agents")

    # 100 * 4000 / 10000 = 40 exactly: the training weight alone.
    assert _review(api, training_only["id"], 100, 0, 0)["oversight_score"] == 40
    # 100 * 3500 / 10000 = 35 exactly: the anti-money-laundering weight alone.
    assert _review(api, aml_only["id"], 0, 100, 0)["oversight_score"] == 35
    # 100 * 2500 / 10000 = 25 exactly: the recordkeeping weight alone.
    assert _review(api, records_only["id"], 0, 0, 100)["oversight_score"] == 25


# ===========================================================================
# Instance: latest_oversight_review_replaces_the_earlier_score
# ===========================================================================


def test_latest_oversight_review_replaces_the_earlier_score(
    api: MoneyTransmitterApiClient, licensee: dict
) -> None:
    """A 90 followed by a 40 leaves the score at 40, not at an average of the two.

    PRD 3.6: "The resulting `oversight_score` is the training score weighted at 4000 basis points, plus the anti-money-laundering test score weighted at 3500 basis points, plus the recordkeeping score weighted at 2500 basis points, that sum divided by 10000 and rounded down to a whole number."
    PRD 3.6: "Only the most recent review counts: the new score **replaces** the old one outright and earlier reviews are not averaged in."
    PRD 3.6: "`last_oversight_review_at` is stamped from the logical clock."

    Design: Corner/calculations/latest_oversight_review_replaces_the_earlier_score
    """
    delegate = fx.create_delegate(api, licensee["id"], legal_name=C.SEED_DELEGATE_NAME)

    # 90 * 4000 + 90 * 3500 + 90 * 2500 = 900000; / 10000 = 90 exactly.
    first = _review(api, delegate["id"], 90, 90, 90)
    assert first["oversight_score"] == 90

    # 40 * 4000 + 40 * 3500 + 40 * 2500 = 400000; / 10000 = 40 exactly.
    # An average of the two reviews would read 65 and is wrong.
    second = _review(api, delegate["id"], 40, 40, 40)
    assert second["oversight_score"] == 40

    fetched = get_success_data(api.get_delegate(delegate["id"], MANAGER_HEADERS))
    assert fetched["oversight_score"] == 40
    assert _instant(fetched["last_oversight_review_at"]) == "2026-08-01T00:00:00"


def test_a_delegate_operator_review_of_its_own_row_replaces_the_officer_score(
    api: MoneyTransmitterApiClient, licensee: dict
) -> None:
    """The agent's own operator may rescore its own row, and that score replaces the last.

    PRD 3.6: "Either a `ComplianceOfficer` — for any delegate — or a `DelegateOperator` acting for its own delegate row submits three component scores, each on a nought-to-one-hundred scale: `training_score`, `aml_test_score` and `recordkeeping_score`."
    PRD 3.6: "Only the most recent review counts: the new score **replaces** the old one outright and earlier reviews are not averaged in."
    PRD 2.1: "`DelegateOperator` is an agent's own operator and may self-report oversight metrics for its own delegate row only."

    Design: Corner/calculations/latest_oversight_review_replaces_the_earlier_score
    """
    delegate = fx.create_delegate(api, licensee["id"], legal_name=C.SEED_DELEGATE_NAME)

    # 90 * 4000 + 90 * 3500 + 90 * 2500 = 900000; / 10000 = 90 exactly.
    assert _review(api, delegate["id"], 90, 90, 90)["oversight_score"] == 90

    # 40 * 4000 + 40 * 3500 + 40 * 2500 = 400000; / 10000 = 40 exactly.
    self_reported = _review(
        api,
        delegate["id"],
        40,
        40,
        40,
        headers=make_delegate_operator_headers(delegate["id"]),
    )
    assert self_reported["oversight_score"] == 40


# ===========================================================================
# Instance: quarterly_call_report_derives_due_at_and_rounds_the_fee_half_up
# ===========================================================================


def test_quarterly_call_report_derives_period_end_and_due_at_from_the_label(
    api: MoneyTransmitterApiClient, active_license: fx.Scenario
) -> None:
    """Label 2026Q2 fixes period_end at 30 June and due_at forty-five days later.

    PRD 3.5: "The label is a reporting-period key: for a jurisdiction whose `call_report_frequency` is `QUARTERLY` it is a four-digit year followed by the letter Q and a digit from 1 to 4; for an `ANNUAL` jurisdiction it is a four-digit year followed by the letters FY."
    PRD 3.5: "From the label the server derives `period_end`, at midnight UTC on the last day of the labelled period in the labelled year: the 31st of March for Q1, the 30th of June for Q2, the 30th of September for Q3, and the 31st of December for both Q4 and a full fiscal year."
    PRD 3.5: "`due_at` is then `period_end` plus forty-five days, again at midnight UTC."
    PRD 3.5: "`filed_at` is stamped from the logical clock."
    PRD 3.5: "The report's `status` follows a strictly ordered two-test rule: the report is `LATE` if the logical clock is strictly past `due_at`; otherwise it is `FILED_DEFICIENT` if `transaction_count` is exactly zero while `transmission_volume_cents` is greater than zero; otherwise it is `FILED`."
    PRD 3.5: "Regardless of status, every filing adds its `transmission_volume_cents` to the licence's `annual_volume_cents` and recomputes `bond_requirement_cents`, since the volume tier may have moved."
    PRD 3.4: "A volume of at most one billion cents — that is, ten million dollars — is tier one at a tier bond of two and a half million cents; a volume above one billion cents but at most ten billion cents is tier two at ten million cents; a volume above ten billion cents is tier three at twenty-five million cents."
    PRD 3.4: "Step two takes the greater of the jurisdiction's `base_bond_cents` and the sum of the tier bond plus the delegate count multiplied by the jurisdiction's `per_delegate_bond_cents`; the delegate count is zero in an application context and the licence's `active_delegate_count` otherwise."
    PRD 2.8: "It is `OPEN` exactly when all five of the following hold: `license_status` is `ACTIVE`, `bond_status` is `POSTED`, `reporting_status` is `CURRENT`, `exam_findings_open` is false, and the owning licensee's `coverage_posture` is either `COMPLIANT` or `WATCH`."
    PRD 2.4: "Day arithmetic on the clock adds exact multiples of twenty-four hours, and all instants are millisecond-exact ISO 8601 UTC."

    Design: Corner/calculations/quarterly_call_report_derives_due_at_and_rounds_the_fee_half_up
    """
    report = validate_success(
        api.file_call_report(
            F.call_report_payload(active_license.license_id, "2026Q2", 40_000_200, 700),
            MANAGER_HEADERS,
        ),
        201,
    )

    # Q2 of 2026 ends at midnight UTC on the 30th of June.
    assert _instant(report["period_end"]) == "2026-06-30T00:00:00"
    # 2026-06-30 plus 45 exact twenty-four-hour periods is 2026-08-14.
    assert _instant(report["due_at"]) == "2026-08-14T00:00:00"
    # The clock has not been moved off its process-start instant.
    assert _instant(report["filed_at"]) == "2026-08-01T00:00:00"

    # 2026-08-01 is not strictly past 2026-08-14, and 700 transactions is not
    # zero, so neither the lateness test nor the deficiency test fires.
    assert report["status"] == "FILED"

    licence = fx.get_license(api, active_license.license_id)
    # The single filing is the licence's whole annual volume: 0 + 40,000,200.
    assert licence["annual_volume_cents"] == 40_000_200
    # 40,000,200 cents is at most 1,000,000,000, so the tier bond is 2,500,000;
    # max(5,000,000 base, 2,500,000 + 0 delegates) = 5,000,000; the
    # MONEY_TRANSMISSION multiplier of 10000 bps leaves it; min with the
    # 40,000,000 cap = 5,000,000.
    assert licence["bond_requirement_cents"] == 5_000_000
    assert licence["reporting_status"] == "CURRENT"
    assert licence["expansion_gate"] == "OPEN"


def test_call_report_assessment_fee_rounds_a_half_cent_up(
    api: MoneyTransmitterApiClient, active_license: fx.Scenario
) -> None:
    """A 25 bps fee landing on exactly 100000.5 cents is taken up to 100001.

    PRD 3.5: "The report also carries its own `assessment_fee_cents`, computed as `transmission_volume_cents` multiplied by the jurisdiction's `assessment_rate_bps`, divided by 10000, with the result rounded half up to whole cents."
    PRD 2.5: "**Round half up** governs the assessment step of the renewal fee, the per-report call-report assessment fee, and the per-line whole-dollar rounding of the annual assessment invoice."
    PRD 2.5: "All monetary amounts are integers denominated in cents; all rates, ratios and ownership stakes are integers denominated in basis points, where 10,000 basis points is one hundred percent."

    Design: Corner/calculations/quarterly_call_report_derives_due_at_and_rounds_the_fee_half_up
    """
    report = validate_success(
        api.file_call_report(
            F.call_report_payload(active_license.license_id, "2026Q2", 40_000_200, 700),
            MANAGER_HEADERS,
        ),
        201,
    )

    # California's assessment_rate_bps is 25: 40,000,200 * 25 = 1,000,005,000,
    # and 1,000,005,000 / 10000 = 100000.5, which rounds half up to 100001.
    # Truncation would give 100000 and is wrong.
    assert report["assessment_fee_cents"] == 100_001
    assert isinstance(report["assessment_fee_cents"], int)


# ===========================================================================
# Instance: annual_call_report_period_end_is_the_labelled_year_end
# ===========================================================================


def test_annual_call_report_period_end_is_the_labelled_year_end(
    api: MoneyTransmitterApiClient
) -> None:
    """An ANNUAL state takes 2026FY to 31 December 2026 and a due date of 14 February 2027.

    PRD 3.5: "The label is a reporting-period key: for a jurisdiction whose `call_report_frequency` is `QUARTERLY` it is a four-digit year followed by the letter Q and a digit from 1 to 4; for an `ANNUAL` jurisdiction it is a four-digit year followed by the letters FY."
    PRD 3.5: "From the label the server derives `period_end`, at midnight UTC on the last day of the labelled period in the labelled year: the 31st of March for Q1, the 30th of June for Q2, the 30th of September for Q3, and the 31st of December for both Q4 and a full fiscal year."
    PRD 3.5: "`due_at` is then `period_end` plus forty-five days, again at midnight UTC."
    PRD 3.5: "The report's `status` follows a strictly ordered two-test rule: the report is `LATE` if the logical clock is strictly past `due_at`; otherwise it is `FILED_DEFICIENT` if `transaction_count` is exactly zero while `transmission_volume_cents` is greater than zero; otherwise it is `FILED`."
    PRD 3.5: "The report also carries its own `assessment_fee_cents`, computed as `transmission_volume_cents` multiplied by the jurisdiction's `assessment_rate_bps`, divided by 10000, with the result rounded half up to whole cents."
    PRD 3.5: "Regardless of status, every filing adds its `transmission_volume_cents` to the licence's `annual_volume_cents` and recomputes `bond_requirement_cents`, since the volume tier may have moved."
    PRD 3.1: "Two further fields shape process rather than arithmetic: `participates_in_multistate`, a boolean defaulting to true that says whether the state may join a coordinated examination, and `call_report_frequency`, which is either `QUARTERLY` or `ANNUAL` and fixes the shape of the reporting calendar for every licence issued there."
    PRD 2.4: "Day arithmetic on the clock adds exact multiples of twenty-four hours, and all instants are millisecond-exact ISO 8601 UTC."

    Design: Corner/calculations/annual_call_report_period_end_is_the_labelled_year_end
    """
    # Nevada FID is the ANNUAL jurisdiction of the reference set, at 10 bps.
    scenario = fx.setup_active_license(api, C.NV_CONFIG)

    report = validate_success(
        api.file_call_report(
            F.call_report_payload(scenario.license_id, "2026FY", 30_000_000, 1_200),
            MANAGER_HEADERS,
        ),
        201,
    )

    # A full fiscal year ends at midnight UTC on the 31st of December.
    assert _instant(report["period_end"]) == "2026-12-31T00:00:00"
    # 2026-12-31 plus 45 exact twenty-four-hour periods is 2027-02-14.
    assert _instant(report["due_at"]) == "2027-02-14T00:00:00"

    # The clock at 2026-08-01 is far short of 2027-02-14, so the filing is not
    # LATE even though the labelled period has not ended, and 1,200
    # transactions keeps it out of FILED_DEFICIENT.
    assert report["status"] == "FILED"

    # Nevada's assessment_rate_bps is 10: 30,000,000 * 10 = 300,000,000, and
    # 300,000,000 / 10000 = 30,000 with nothing to round.
    assert report["assessment_fee_cents"] == 30_000

    licence = fx.get_license(api, scenario.license_id)
    assert licence["annual_volume_cents"] == 30_000_000
    assert licence["reporting_status"] == "CURRENT"


# ===========================================================================
# Instance: information_request_window_comes_from_the_requesting_jurisdiction
# ===========================================================================


def test_information_request_window_comes_from_the_requesting_jurisdiction(
    api: MoneyTransmitterApiClient, active_license: fx.Scenario
) -> None:
    """On a California-led exam each state's request is due on its own window, not the lead's.

    PRD 3.8: "Its `due_at` is the current logical clock plus the requesting jurisdiction's `response_window_days`, expressed as that many exact twenty-four-hour periods."
    PRD 3.8: "The requesting state must be the exam's lead or appear in `participating_jurisdiction_ids`; an outsider's request is rejected with `ERR_JURISDICTION_NOT_PARTICIPATING` (HTTP 422)."
    PRD 3.8: "The row starts in `OPEN` — the other statuses being `RESPONDED`, `OVERDUE` and the terminal `ACCEPTED` — with `reopen_count` and `submitted_item_count` at zero and `responded_at` null."
    PRD 3.8: "Because `open_request_count` is by definition the number of the exam's requests sitting in `OPEN`, `OVERDUE` or `RESPONDED`, opening a request raises it by one."
    PRD 3.8: "On success the exam starts in `SCHEDULED` and `participating_state_count` is set to the distinct count of participating jurisdictions including the lead."
    PRD 3.8: "Every listed participant must be eligible — its `participates_in_multistate` must be true and the examined licensee must hold a `StateLicense` there whose `license_status` is `ACTIVE`; a participant failing either test is rejected with `ERR_JURISDICTION_NOT_MULTISTATE` (HTTP 422)."
    PRD 2.4: "Day arithmetic on the clock adds exact multiples of twenty-four hours, and all instants are millisecond-exact ISO 8601 UTC."

    Design: Corner/calculations/information_request_window_comes_from_the_requesting_jurisdiction
    """
    ca_id = active_license.jurisdiction_id
    texas = fx.add_license_in_jurisdiction(api, active_license.licensee_id, C.TX_CONFIG)
    tx_id = texas["jurisdiction"]["id"]

    exam = fx.setup_exam_in_fieldwork(
        api,
        active_license.licensee_id,
        ca_id,
        fieldwork_start="2026-09-01T00:00:00Z",
        fieldwork_end="2026-09-15T00:00:00Z",
        participating_jurisdiction_ids=[ca_id, tx_id],
    )
    # Distinct participants including the lead: California and Texas.
    assert exam["participating_state_count"] == 2

    lead_request = validate_success(
        api.create_information_request(
            F.information_request_payload(
                exam["id"],
                ca_id,
                subject="California delegate settlement ledgers",
                requested_item_count=2,
            ),
            make_state_regulator_headers(ca_id),
        ),
        201,
    )
    participant_request = validate_success(
        api.create_information_request(
            F.information_request_payload(
                exam["id"],
                tx_id,
                subject="Texas agent contracts",
                requested_item_count=2,
            ),
            make_state_regulator_headers(tx_id),
        ),
        201,
    )

    # California's response_window_days is 15: 2026-08-01 plus 15 exact
    # twenty-four-hour periods is 2026-08-16.
    assert _instant(lead_request["due_at"]) == "2026-08-16T00:00:00"
    # Texas's response_window_days is 10, and the request it issues takes its
    # own window rather than the California lead's: 2026-08-01 plus 10 days is
    # 2026-08-11, five days ahead of the lead's own deadline.
    assert _instant(participant_request["due_at"]) == "2026-08-11T00:00:00"

    assert lead_request["status"] == "OPEN"
    assert lead_request["reopen_count"] == 0
    assert lead_request["submitted_item_count"] == 0
    assert lead_request["responded_at"] is None
    assert participant_request["status"] == "OPEN"

    refreshed = get_success_data(api.get_exam(exam["id"], make_state_regulator_headers(ca_id)))
    # Two requests opened, neither dispositioned: 0 + 1 + 1 = 2.
    assert refreshed["open_request_count"] == 2


# ===========================================================================
# Instance: control_determination_boundary_at_two_thousand_five_hundred_bps
# ===========================================================================


def test_control_determination_boundary_at_two_thousand_five_hundred_bps(
    api: MoneyTransmitterApiClient, licensee: dict
) -> None:
    """A non-officer holder at exactly 2500 bps is CONTROL while 2499 bps is NON_CONTROL.

    PRD 3.2: "The control test uses the attributed figure, never the economic one."
    PRD 3.2: "`control_determination` is `CONTROL` when `attributed_ownership_bps` is at least 2500 basis points **or** the holder's `role_title` is one of the four officer titles `CEO`, `CFO`, `COO` or `CCO`; otherwise it is `NON_CONTROL`."
    PRD 3.2: "Exactly 2500 basis points is `CONTROL`; 2499 is `NON_CONTROL`."
    PRD 3.2: "A `DIRECTOR`, an `ENTITY_HOLDER` and a `PASSIVE_INVESTOR` are officers for no purpose here — they reach `CONTROL` only through the attributed stake."
    PRD 3.2: "The **economic** figure, `effective_ownership_bps`, multiplies the chain: for a direct holder it is simply `direct_ownership_bps`; otherwise it is the row's `direct_ownership_bps` multiplied by the parent's `effective_ownership_bps`, divided by 10000 with the result rounded down at that hop."
    PRD 3.2: "The **attributed** figure, `attributed_ownership_bps`, applies the regulatory attribution convention instead: for a direct holder it is again `direct_ownership_bps`; if the parent's own `direct_ownership_bps` is at least 2500 basis points, the parent link is treated as controlling and the row's stake is attributed at full value, so `attributed_ownership_bps` equals the row's `direct_ownership_bps` unchanged; only when the parent's direct stake is below 2500 basis points does the row's stake get diluted, becoming the row's `direct_ownership_bps` multiplied by the parent's `attributed_ownership_bps` divided by 10000 and rounded down."

    Design: Corner/calculations/control_determination_boundary_at_two_thousand_five_hundred_bps
    """
    at_threshold = fx.create_control_person(
        api,
        licensee["id"],
        full_name="Dana Whitfield",
        role_title="ENTITY_HOLDER",
        direct_ownership_bps=2500,
    )
    below_threshold = fx.create_control_person(
        api,
        licensee["id"],
        full_name="Ravi Menon",
        role_title="ENTITY_HOLDER",
        direct_ownership_bps=2499,
    )

    # Both are direct holders with a null parent, so both figures are simply
    # direct_ownership_bps with no hop and no dilution.
    assert at_threshold["effective_ownership_bps"] == 2500
    assert at_threshold["attributed_ownership_bps"] == 2500
    assert below_threshold["effective_ownership_bps"] == 2499
    assert below_threshold["attributed_ownership_bps"] == 2499

    # 2500 is at least 2500; ENTITY_HOLDER is not an officer title.
    assert at_threshold["control_determination"] == "CONTROL"
    # 2499 falls one basis point short and no title rescues it.
    assert below_threshold["control_determination"] == "NON_CONTROL"


def test_control_determination_drives_the_background_check_and_the_chain_aggregate(
    api: MoneyTransmitterApiClient, licensee: dict
) -> None:
    """The 2500-bps holder alone takes a background check and moves the chain to PENDING_CHECKS.

    PRD 3.2: "From `control_determination` two obligations follow immediately."
    PRD 3.2: "`background_check_status` is set to `PENDING` for a control person and to `NOT_REQUIRED` otherwise; its full value set is `NOT_REQUIRED`, `PENDING`, `CLEARED` and `ADVERSE`, and it defaults to `NOT_REQUIRED`."
    PRD 3.2: "`change_of_control_status` is set to `PENDING_APPROVAL` when the holder is a control person **and** the licensee's `active_license_count` is greater than zero, and to `NOT_REQUIRED` in every other case; its value set is `NOT_REQUIRED`, `PENDING_APPROVAL`, `APPROVED` and `DENIED`."
    PRD 3.2: "At the same moment the server pins `required_approval_count` to the licensee's `active_license_count` as it stands at creation time — the quorum is frozen then and does not move as licences come and go."
    PRD 3.2: "`approving_jurisdiction_ids` starts as an empty array, `disqualifying_finding` starts false, and the row's own `status` starts at `PROPOSED`, the other values being `SEATED` and `REMOVED`."
    PRD 3.2: "A holder becomes `SEATED` — the system's way of saying the appointment is effective — when its `background_check_status` is either `NOT_REQUIRED` or `CLEARED` **and** its `change_of_control_status` is either `NOT_REQUIRED` or `APPROVED`, while the row itself is still `PROPOSED`. The transition is automatic; no operator asks for it."
    PRD 3.2: "Above the individual holders sits the licensee's `control_chain_status`, an aggregate over the non-`REMOVED` holders whose `control_determination` is `CONTROL`, with values `VERIFIED`, `PENDING_CHECKS` and `BLOCKED` and a default of `VERIFIED`."
    PRD 3.2: "It is recomputed on every control-person creation, every background-check adjudication and every change-of-control decision, by this precedence: `BLOCKED` if any such holder has `background_check_status` of `ADVERSE` or `change_of_control_status` of `DENIED`; otherwise `PENDING_CHECKS` if any such holder has `background_check_status` of `PENDING` or `change_of_control_status` of `PENDING_APPROVAL`; otherwise `VERIFIED`."
    PRD 3.1: "A freshly created licensee starts with `version` at 1, `coverage_posture` at `COMPLIANT`, `coverage_ratio_bps` at 10000 — vacuously perfect, since there are no obligations yet — `control_chain_status` at `VERIFIED`, and every counter at zero: `aggregate_outstanding_obligations_cents`, `eligible_investment_value_cents`, `book_investment_value_cents`, `consecutive_failed_test_count` and `active_license_count`."

    Design: Corner/calculations/control_determination_boundary_at_two_thousand_five_hundred_bps
    """
    assert licensee["control_chain_status"] == "VERIFIED"
    assert licensee["active_license_count"] == 0

    at_threshold = fx.create_control_person(
        api,
        licensee["id"],
        full_name="Dana Whitfield",
        role_title="ENTITY_HOLDER",
        direct_ownership_bps=2500,
    )
    below_threshold = fx.create_control_person(
        api,
        licensee["id"],
        full_name="Ravi Menon",
        role_title="ENTITY_HOLDER",
        direct_ownership_bps=2499,
    )

    assert at_threshold["background_check_status"] == "PENDING"
    assert below_threshold["background_check_status"] == "NOT_REQUIRED"

    # active_license_count is 0 for this licensee, so no change of control is
    # required even for the control person, and the frozen quorum is 0.
    assert at_threshold["change_of_control_status"] == "NOT_REQUIRED"
    assert below_threshold["change_of_control_status"] == "NOT_REQUIRED"
    assert at_threshold["required_approval_count"] == 0
    assert below_threshold["required_approval_count"] == 0

    assert at_threshold["approving_jurisdiction_ids"] == []
    assert at_threshold["disqualifying_finding"] is False
    # The 2500-bps holder owes a PENDING check, so it cannot seat yet. The
    # 2499-bps holder owes nothing on either dimension, so the automatic
    # seating rule fires immediately.
    assert at_threshold["status"] == "PROPOSED"
    assert below_threshold["status"] == "SEATED"

    refreshed = fx.get_licensee(api, licensee["id"])
    # The aggregate sees exactly one CONTROL holder, and its check is PENDING,
    # so the precedence ladder stops at PENDING_CHECKS.
    assert refreshed["control_chain_status"] == "PENDING_CHECKS"


# ===========================================================================
# Instance: officer_title_forces_control_at_zero_ownership
# ===========================================================================


def test_officer_title_forces_control_at_zero_ownership(
    api: MoneyTransmitterApiClient, licensee: dict
) -> None:
    """A CFO holding nothing at all is still a control person on the title disjunct.

    PRD 3.2: "`control_determination` is `CONTROL` when `attributed_ownership_bps` is at least 2500 basis points **or** the holder's `role_title` is one of the four officer titles `CEO`, `CFO`, `COO` or `CCO`; otherwise it is `NON_CONTROL`."
    PRD 3.2: "`background_check_status` is set to `PENDING` for a control person and to `NOT_REQUIRED` otherwise; its full value set is `NOT_REQUIRED`, `PENDING`, `CLEARED` and `ADVERSE`, and it defaults to `NOT_REQUIRED`."
    PRD 3.2: "The **economic** figure, `effective_ownership_bps`, multiplies the chain: for a direct holder it is simply `direct_ownership_bps`; otherwise it is the row's `direct_ownership_bps` multiplied by the parent's `effective_ownership_bps`, divided by 10000 with the result rounded down at that hop."
    PRD 3.2: "The **attributed** figure, `attributed_ownership_bps`, applies the regulatory attribution convention instead: for a direct holder it is again `direct_ownership_bps`; if the parent's own `direct_ownership_bps` is at least 2500 basis points, the parent link is treated as controlling and the row's stake is attributed at full value, so `attributed_ownership_bps` equals the row's `direct_ownership_bps` unchanged; only when the parent's direct stake is below 2500 basis points does the row's stake get diluted, becoming the row's `direct_ownership_bps` multiplied by the parent's `attributed_ownership_bps` divided by 10000 and rounded down."
    PRD 3.2: "It is recomputed on every control-person creation, every background-check adjudication and every change-of-control decision, by this precedence: `BLOCKED` if any such holder has `background_check_status` of `ADVERSE` or `change_of_control_status` of `DENIED`; otherwise `PENDING_CHECKS` if any such holder has `background_check_status` of `PENDING` or `change_of_control_status` of `PENDING_APPROVAL`; otherwise `VERIFIED`."

    Design: Corner/calculations/officer_title_forces_control_at_zero_ownership
    """
    officer = validate_success(
        api.create_control_person(
            F.control_person_payload(
                licensee["id"],
                full_name="Priya Raman",
                role_title="CFO",
                direct_ownership_bps=0,
            ),
            MANAGER_HEADERS,
        ),
        201,
    )

    # A direct holder at 0 bps reads 0 on both variants, so the stake disjunct
    # is false and only the officer-title disjunct can carry the row.
    assert officer["effective_ownership_bps"] == 0
    assert officer["attributed_ownership_bps"] == 0
    assert officer["control_determination"] == "CONTROL"
    assert officer["background_check_status"] == "PENDING"

    refreshed = fx.get_licensee(api, licensee["id"])
    assert refreshed["control_chain_status"] == "PENDING_CHECKS"


# ===========================================================================
# Instance: removed_ancestor_zeroes_both_ownership_variants_downstream
# ===========================================================================


def test_removed_ancestor_zeroes_both_ownership_variants_downstream(
    api: MoneyTransmitterApiClient, ca_jurisdiction: dict, licensee: dict
) -> None:
    """An adverse adjudication on the holding company zeroes the child's two ownership figures.

    PRD 3.2: "The **economic** figure, `effective_ownership_bps`, multiplies the chain: for a direct holder it is simply `direct_ownership_bps`; otherwise it is the row's `direct_ownership_bps` multiplied by the parent's `effective_ownership_bps`, divided by 10000 with the result rounded down at that hop."
    PRD 3.2: "The **attributed** figure, `attributed_ownership_bps`, applies the regulatory attribution convention instead: for a direct holder it is again `direct_ownership_bps`; if the parent's own `direct_ownership_bps` is at least 2500 basis points, the parent link is treated as controlling and the row's stake is attributed at full value, so `attributed_ownership_bps` equals the row's `direct_ownership_bps` unchanged; only when the parent's direct stake is below 2500 basis points does the row's stake get diluted, becoming the row's `direct_ownership_bps` multiplied by the parent's `attributed_ownership_bps` divided by 10000 and rounded down."
    PRD 3.2: "A `REMOVED` ancestor contributes zero to both figures, and both are recomputed for every descendant whenever an ancestor is removed."
    PRD 3.2: "A `StateRegulator` adjudicates the background check, supplying an `outcome` and, where relevant, a `disqualifying_finding` flag."
    PRD 3.2: "An `outcome` of `ADVERSE` accompanied by `disqualifying_finding` true sets `background_check_status` to `ADVERSE`, sets the row's `disqualifying_finding` to true, and drives the holder from `PROPOSED` straight to the terminal `REMOVED`; the licensee's `control_chain_status` is then forced to `BLOCKED`, and every child holder whose `parent_control_person_id` names the removed row has both `effective_ownership_bps` and `attributed_ownership_bps` recomputed to zero and is itself set to `REMOVED`."
    PRD 2.1: "For control-person adjudications and change-of-control decisions the test is broader: `X-User-ID` must be a jurisdiction in which the licensee either holds a `StateLicense` whose `license_status` is `ACTIVE` or has a `LicenseApplication` in a non-terminal status."
    PRD 2.5: "**Floor** (round down toward zero) governs every division inside the permissible-investment coverage computation, every hop of the ownership attribution chain, the class-multiplier step of the surety bond computation, and the weighted delegate oversight score."

    Design: Corner/calculations/removed_ancestor_zeroes_both_ownership_variants_downstream
    """
    # A SUBMITTED California application is a non-terminal filing, which is what
    # puts California in scope for this licensee's control-person adjudications.
    application = fx.create_application(api, licensee["id"], ca_jurisdiction["id"])
    fx.submit_application(api, application["id"])

    root = fx.create_control_person(
        api,
        licensee["id"],
        full_name="Dana Whitfield",
        role_title="ENTITY_HOLDER",
        direct_ownership_bps=6000,
    )
    child = fx.create_control_person(
        api,
        licensee["id"],
        full_name="Ravi Menon",
        role_title="ENTITY_HOLDER",
        direct_ownership_bps=4000,
        parent_control_person_id=root["id"],
    )

    # Before the removal the two variants diverge on the same one hop:
    #   economic  floor(4000 * 6000 / 10000) = floor(2400) = 2400
    #   attributed: the parent's own direct stake of 6000 is at least 2500, so
    #   the child's 4000 is attributed at full value and stays 4000.
    assert child["effective_ownership_bps"] == 2400
    assert child["attributed_ownership_bps"] == 4000
    # 4000 is at least 2500 on the attributed figure that the control test uses,
    # even though 2400 economically is below the threshold.
    assert child["control_determination"] == "CONTROL"

    removed_root = validate_success(
        api.adjudicate_background_check(
            root["id"],
            F.background_check_payload("ADVERSE", disqualifying_finding=True),
            make_state_regulator_headers(ca_jurisdiction["id"]),
        )
    )
    assert removed_root["background_check_status"] == "ADVERSE"
    assert removed_root["disqualifying_finding"] is True
    assert removed_root["status"] == "REMOVED"

    recomputed = get_success_data(api.get_control_person(child["id"], MANAGER_HEADERS))
    # A REMOVED ancestor contributes zero to both figures, so the child's
    # economic figure falls 2400 -> 0 and its attributed figure 4000 -> 0.
    assert recomputed["effective_ownership_bps"] == 0
    assert recomputed["attributed_ownership_bps"] == 0
    assert recomputed["status"] == "REMOVED"
