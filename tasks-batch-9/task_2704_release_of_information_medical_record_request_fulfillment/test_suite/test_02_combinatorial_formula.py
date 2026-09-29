"""Multi-term formulas whose composition order is load bearing."""

from prd_bench_local_runner.testing import get_success_data

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import (
    Instant,
    assert_event_count,
    assert_line,
    assert_line_sequence_contiguous,
    assert_no_line_type,
    assert_subtotal_reconciles,
    line_types,
)
from test_helpers.test_users import INTAKE_1, PLATFORM_ADMIN


# --------------------------------------------------------------------------
# statutory_due_at_composes_anchor_toll_and_extension
# --------------------------------------------------------------------------
def _request_parked_on_a_defect(api):
    """A third-party request whose authorization is DEFECTIVE, parked on the defect
    at 2026-08-05T00:00:00Z with the clock then moved to 2026-08-08T06:00:00Z."""
    world = fx.third_party_world(api, signature_verified=False)
    request = fx.open_third_party_request(api, world)

    fx.set_clock(api, "2026-08-05T00:00:00Z")
    get_success_data(
        api.intake_decision(
            request["id"],
            f.intake_decision_payload("DEFECT", defect_reasons=["signature not verified"]),
            INTAKE_1,
        )
    )
    fx.set_clock(api, "2026-08-08T06:00:00Z")
    return {"world": world, "request_id": request["id"]}


def _cure(api, authorization_id):
    return get_success_data(
        api.cure_authorization(
            authorization_id,
            f.authorization_cure_payload(signed_at="2026-08-07T12:00:00Z"),
            INTAKE_1,
        )
    )


def test_deadline_composes_the_max_anchor_and_the_toll_in_the_pinned_order(api):
    """Anchor is chosen before days are added, and the toll is added after them.

    PRD: "Step two selects the anchor, and it does so *before* any days are added: for a `PATIENT_RIGHT_OF_ACCESS` request the anchor is simply the request's `received_at`, because such a request has no authorization; for a `THIRD_PARTY_AUTHORIZATION` request the anchor is the later of the request's `received_at` and the governing authorization's `signed_at`, so an authorization signed after the request arrived pushes the anchor forward."

    Design: Difficulty/combinatorial_formula/statutory_due_at_composes_anchor_toll_and_extension
    """
    scenario = _request_parked_on_a_defect(api)
    request_id = scenario["request_id"]

    parked = fx.read_request(api, request_id)
    assert parked["fulfillment_status"] == "AUTH_DEFECT_PENDING"
    assert parked["defect_opened_at"] == Instant("2026-08-05T00:00:00Z")
    assert parked["tolled_seconds"] == 0
    assert parked["statutory_due_at"] == Instant("2026-08-31T00:00:00Z")

    authorization = _cure(api, scenario["world"]["authorization_id"])
    assert authorization["status"] == "VALID"
    assert authorization["defect_reasons"] == []

    cured = fx.read_request(api, request_id)
    assert cured["fulfillment_status"] == "INTAKE_REVIEW"
    assert cured["defect_opened_at"] is None
    assert cured["tolled_seconds"] == 280800
    assert cured["statutory_due_at"] == Instant("2026-09-09T18:00:00Z")


def test_the_extension_is_the_last_term_added_to_the_deadline(api):
    """Fifteen extension days land on top of the anchor-plus-days-plus-toll instant.

    PRD: "Step five, last of all, adds the extension: when `extension_applied` is true, the governing rule's `extension_days` multiplied by 86400 seconds is added; when it is false, nothing is added."

    Design: Difficulty/combinatorial_formula/statutory_due_at_composes_anchor_toll_and_extension
    """
    scenario = _request_parked_on_a_defect(api)
    request_id = scenario["request_id"]
    _cure(api, scenario["world"]["authorization_id"])
    assert fx.read_request(api, request_id)["statutory_due_at"] == Instant("2026-09-09T18:00:00Z")

    get_success_data(api.notice_extension(request_id, f.extension_payload(), INTAKE_1))

    extended = fx.read_request(api, request_id)
    assert extended["extension_applied"] is True
    assert extended["extension_noticed_at"] == Instant("2026-08-08T06:00:00Z")
    assert extended["statutory_due_at"] == Instant("2026-09-24T18:00:00Z")
    assert extended["tolled_seconds"] == 280800


def test_no_penalty_accrues_while_the_clock_stays_before_the_composed_deadline(api):
    """The whole tolling and extension story leaves both penalty measures at 0.

    PRD: "If the effective completion instant is at or before `statutory_due_at`, both measures are 0 and no compliance event is appended — a request delivered exactly at its deadline is on time."

    Design: Difficulty/combinatorial_formula/statutory_due_at_composes_anchor_toll_and_extension
    """
    scenario = _request_parked_on_a_defect(api)
    request_id = scenario["request_id"]
    _cure(api, scenario["world"]["authorization_id"])
    get_success_data(api.notice_extension(request_id, f.extension_payload(), INTAKE_1))

    request = fx.read_request(api, request_id)
    assert request["penalty_exposure_cents"] == 0
    assert request["safe_harbor_penalty_cents"] == 0

    turnaround = get_success_data(api.get_turnaround(request_id, PLATFORM_ADMIN))
    assert turnaround["breached"] is False
    assert turnaround["penalty_exposure_cents"] == 0
    assert turnaround["safe_harbor_penalty_cents"] == 0
    assert_event_count(fx.read_events(api, request_id), "STATUTORY_DEADLINE_BREACHED", 0)


# --------------------------------------------------------------------------
# invoice_lines_round_per_line_then_sum_to_4501
# --------------------------------------------------------------------------
def _paper_mail_certified_sixty_two_pages(api):
    """62 billable pages, PAPER_MAIL, certification requested, priced once.  The
    facility carries a 2000-cent legacy surcharge but the request has no legacy
    segment, so no LEGACY_RETRIEVAL line may appear."""
    world = fx.third_party_world(api)
    scenario = fx.simple_third_party_request_at_release_ready(
        api, world, 62, delivery_format="PAPER_MAIL", certification_requested=True
    )
    invoice = fx.create_invoice(api, scenario["request_id"])
    return {"world": world, "request_id": scenario["request_id"], "invoice": invoice}


def test_five_lines_round_individually_and_sum_to_4501_not_4500(api):
    """Two half-cent lines each round up; summing first would lose one cent.

    PRD: "A tier-1 line of 25 pages at 27500 millicents rounds 687.5 up to 688, and a tier-2 line of 37 pages at 12500 millicents rounds 462.5 up to 463; summing the two unrounded figures and rounding once would yield a total one cent lower."

    Design: Difficulty/combinatorial_formula/invoice_lines_round_per_line_then_sum_to_4501
    """
    scenario = _paper_mail_certified_sixty_two_pages(api)
    invoice = scenario["invoice"]
    lines = fx.read_lines(api, invoice["id"])

    assert len(lines) == 5
    assert_line_sequence_contiguous(lines)
    assert_line(lines[0], "BASE_RETRIEVAL", 1, 1500000, 1500)
    assert_line(lines[1], "PER_PAGE_TIER1", 25, 27500, 688)
    assert_line(lines[2], "PER_PAGE_TIER2", 37, 12500, 463)
    assert_line(lines[3], "CERTIFICATION", 1, 1000000, 1000)
    assert_line(lines[4], "POSTAGE", 1, 850000, 850)

    assert invoice["subtotal_cents"] == 4501
    assert invoice["subtotal_cents"] != 4500


def test_line_types_that_do_not_apply_are_omitted_entirely(api):
    """No LEGACY_RETRIEVAL despite the facility surcharge, and no MEDIA for paper mail.

    PRD: "Fourth, a `LEGACY_RETRIEVAL` line with `quantity` 1 and a `unit_millicents` equal to the facility's `legacy_retrieval_surcharge_cents` multiplied by 1000, emitted only when at least one `RETRIEVED` segment of the request has `source_system` `LEGACY_ARCHIVE` **and** that surcharge is above 0, and charged exactly once per invoice no matter how many legacy segments the request contains."

    Design: Difficulty/combinatorial_formula/invoice_lines_round_per_line_then_sum_to_4501
    """
    scenario = _paper_mail_certified_sixty_two_pages(api)
    lines = fx.read_lines(api, scenario["invoice"]["id"])

    facility = fx.read_facility(api, scenario["world"]["facility_id"])
    assert facility["legacy_retrieval_surcharge_cents"] == 2000

    assert_no_line_type(lines, "LEGACY_RETRIEVAL")
    assert_no_line_type(lines, "MEDIA")
    assert_no_line_type(lines, "PER_PAGE_FLAT")
    assert line_types(lines) == [
        "BASE_RETRIEVAL",
        "PER_PAGE_TIER1",
        "PER_PAGE_TIER2",
        "CERTIFICATION",
        "POSTAGE",
    ]


def test_the_paper_cap_does_not_bite_and_no_forfeiture_applies(api):
    """4501 sits under the 12000 all-format cap, so the amount due is the subtotal.

    PRD: "For an electronic delivery the invoice's `applicable_cap_cents` is the smaller of the fee rule's `electronic_delivery_total_cap_cents` and its `total_fee_cap_cents`; for any other format it is simply `total_fee_cap_cents`."

    Design: Difficulty/combinatorial_formula/invoice_lines_round_per_line_then_sum_to_4501
    """
    scenario = _paper_mail_certified_sixty_two_pages(api)
    invoice = scenario["invoice"]

    assert invoice["applicable_cap_cents"] == 12000
    assert invoice["cap_adjustment_cents"] == 0
    assert invoice["forfeiture_cents"] == 0
    assert invoice["amount_due_cents"] == 4501
    assert_subtotal_reconciles(invoice, fx.read_lines(api, invoice["id"]))
    assert_no_line_type(fx.read_lines(api, invoice["id"]), "CAP_ADJUSTMENT")


# --------------------------------------------------------------------------
# invoice_amount_due_pins_cap_before_forfeiture
# --------------------------------------------------------------------------
def _late_patient_access_invoice_of_eight_hundred_pages(api):
    """800 flat-rate pages (8000 cents) against a 6500-cent electronic cap, priced one
    day after the 2026-08-16T00:00:00Z right-of-access deadline."""
    world = fx.patient_access_world(api)
    scenario = fx.simple_patient_access_request_at_release_ready(api, world, 800)
    request_id = scenario["request_id"]
    assert fx.read_request(api, request_id)["statutory_due_at"] == Instant("2026-08-16T00:00:00Z")

    fx.set_clock(api, "2026-08-17T00:00:00Z")
    invoice = fx.create_invoice(api, request_id)
    return {"world": world, "request_id": request_id, "invoice": invoice}


def test_the_cap_bites_before_the_forfeiture_is_measured(api):
    """8000 is capped to 6500, then 2500 is forfeited from the capped figure: 4000.

    PRD: "Note carefully that the forfeiture is measured against the **capped** figure, never against the raw subtotal."

    Design: Difficulty/combinatorial_formula/invoice_amount_due_pins_cap_before_forfeiture
    """
    invoice = _late_patient_access_invoice_of_eight_hundred_pages(api)["invoice"]

    assert invoice["variant"] == "PATIENT_ACCESS_COST_BASED"
    assert invoice["penalty_snapshot_cents"] == 2500
    assert invoice["subtotal_cents"] == 8000
    assert invoice["applicable_cap_cents"] == 6500
    assert invoice["cap_adjustment_cents"] == -1500
    assert invoice["gross_total_cents"] == 6500
    assert invoice["forfeiture_cents"] == 2500
    assert invoice["amount_due_cents"] == 4000
    assert invoice["amount_due_cents"] != 5500


def test_the_adjustment_and_forfeiture_lines_close_the_reconciliation(api):
    """Three lines: the priced flat line plus the two negative adjustment lines.

    PRD: "When `forfeiture_cents` is above 0 a `LATE_FEE_FORFEITURE` line is emitted as the final `sequence` with `quantity` 1, a `unit_millicents` of the negated `forfeiture_cents` multiplied by 1000, and an `amount_cents` equal to the negated `forfeiture_cents`."

    Design: Difficulty/combinatorial_formula/invoice_amount_due_pins_cap_before_forfeiture
    """
    scenario = _late_patient_access_invoice_of_eight_hundred_pages(api)
    invoice = scenario["invoice"]
    lines = fx.read_lines(api, invoice["id"])

    assert len(lines) == 3
    assert_line_sequence_contiguous(lines)
    assert_line(lines[0], "PER_PAGE_FLAT", 800, 10000, 8000)
    assert_line(lines[1], "CAP_ADJUSTMENT", 1, -1500000, -1500)
    assert_line(lines[2], "LATE_FEE_FORFEITURE", 1, -2500000, -2500)
    assert_subtotal_reconciles(invoice, lines)


def test_pricing_a_late_capped_request_appends_the_cap_and_breach_events(api):
    """The cap adjustment and the passed deadline each leave one event behind.

    PRD: "When `cap_adjustment_cents` is not 0, a `CAP_ADJUSTMENT` line is emitted as the next `sequence` after the priced lines with `quantity` 1, a `unit_millicents` of `cap_adjustment_cents` multiplied by 1000, and an `amount_cents` equal to `cap_adjustment_cents` — so the line set always reconciles to the gross total — and a `FEE_CAP_APPLIED` compliance event is appended against the request."

    Design: Difficulty/combinatorial_formula/invoice_amount_due_pins_cap_before_forfeiture
    """
    scenario = _late_patient_access_invoice_of_eight_hundred_pages(api)
    events = fx.read_events(api, scenario["request_id"])

    assert_event_count(events, "FEE_CAP_APPLIED", 1)
    assert_event_count(events, "STATUTORY_DEADLINE_BREACHED", 1)
    assert fx.read_request(api, scenario["request_id"])["penalty_exposure_cents"] == 2500
